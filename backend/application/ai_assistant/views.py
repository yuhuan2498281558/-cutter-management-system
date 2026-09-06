"""
Django视图 - 提供HTTP接口
"""

import json
import logging
import asyncio
import time

from django.http import StreamingHttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from .llm_service import get_assistant
from .llm_provider import LLMProviderError, get_llm_config

logger = logging.getLogger(__name__)


def _resolve_request_project_id(project_id=None) -> str:
    """Use the sole configured project when the client has no project selector.

    The current AI page does not expose a project selector. Falling back to the
    demo project id silently returns an empty dataset, while aggregating every
    project would create a cross-project data leak. Therefore automatic
    inference is allowed only when exactly one project exists.
    """
    if project_id not in (None, ""):
        return str(project_id)

    from application.shield.models import ProjectInfo

    project_ids = list(
        ProjectInfo.objects.values_list("project_id", flat=True)[:2]
    )
    return str(project_ids[0]) if len(project_ids) == 1 else ""


def success(data):
    return Response({'code': 2000, 'data': data, 'msg': 'success'})


def error(message, code=4000):
    return Response({'code': code, 'data': None, 'msg': message})


def _build_project_snapshot(project_id: str) -> dict:
    """
    查询项目的实时数据快照，注入到每次对话上下文中。
    让模型了解"当前项目有多少数据、最新到哪个环号"，避免盲目推断。
    """
    if not project_id:
        return {}
    try:
        from application.shield.models import (
            WarehouseOpeningBasicInfo,
            ToolChangeDetail,
            CutterPositionInfo,
        )
        from django.db.models import Count, IntegerField, Max
        from django.db.models.functions import Cast

        # 开仓记录统计
        warehouse_qs = WarehouseOpeningBasicInfo.objects.filter(
            project__project_id=project_id
        )
        warehouse_stats = warehouse_qs.annotate(
            ring_int=Cast('ring_no', output_field=IntegerField())
        ).aggregate(
            total=Count('id'),
            latest_ring=Max('ring_int'),
        )
        total_openings = warehouse_stats['total'] or 0
        latest_ring = warehouse_stats['latest_ring'] or '未知'

        # 换刀记录总数
        total_changes = ToolChangeDetail.objects.filter(
            warehouse__project__project_id=project_id
        ).count()

        # 已更换次数
        total_replaced = ToolChangeDetail.objects.filter(
            warehouse__project__project_id=project_id,
            is_replaced=True,
        ).count()

        # 刀位总数
        total_positions = CutterPositionInfo.objects.count()

        return {
            'snapshot_total_openings': total_openings,
            'snapshot_latest_ring': latest_ring,
            'snapshot_total_changes': total_changes,
            'snapshot_total_replaced': total_replaced,
            'snapshot_total_positions': total_positions,
        }
    except Exception as e:
        logger.warning(f"项目快照查询失败（project_id={project_id}）：{e}")
        return {}


def _build_context(request) -> dict:
    ctx = {
        "user_id": request.user.id,
        "username": request.user.username,
    }
    body = request.data
    project_id = _resolve_request_project_id(body.get("project_id"))
    if project_id:
        ctx["project_id"] = project_id
        ctx.update(_build_project_snapshot(project_id))
    if body.get("project_name"):
        ctx["project_name"] = body["project_name"]
    if body.get("ring_range") and isinstance(body["ring_range"], list) and len(body["ring_range"]) == 2:
        ctx["ring_range"] = body["ring_range"]
    return ctx


def _auth_user(request):
    """从 Authorization: JWT <token> 头手动验证，返回 user 或 None"""
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth_header.startswith("JWT "):
        logger.warning(f"stream auth: 无 JWT 头，收到：{auth_header[:30]!r}")
        return None
    try:
        raw_token = auth_header.split(" ", 1)[1]
        auth = JWTAuthentication()
        validated = auth.get_validated_token(raw_token)
        return auth.get_user(validated)
    except Exception as e:
        logger.warning(f"stream auth 失败：{e}")
        return None


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chat(request):
    """
    POST /api/ai/chat/
    Body: { "query": "...", "project_id": "P001", "project_name": "...", "ring_range": [100, 300] }
    """
    user_query = request.data.get('query', '').strip()
    if not user_query:
        return error("查询内容不能为空")

    started_at = time.perf_counter()
    context = _build_context(request)
    context_ready_ms = (time.perf_counter() - started_at) * 1000
    if request.data.get('route_mode'):
        context['route_mode'] = request.data.get('route_mode')
    try:
        assistant = get_assistant()
        assistant_ready_ms = (time.perf_counter() - started_at) * 1000
        result = assistant.chat(user_query, context)
        logger.info(
            "AI chat timing user_id=%s project_id=%s route_stage=%s rule_branch=%s "
            "context_ready_ms=%.1f assistant_ready_ms=%.1f total_ms=%.1f",
            request.user.id,
            context.get("project_id", ""),
            result.get("route_stage", ""),
            result.get("rule_branch", ""),
            context_ready_ms,
            assistant_ready_ms,
            (time.perf_counter() - started_at) * 1000,
        )
        return success(result)
    except Exception as e:
        logger.error(f"对话接口异常：{e}")
        return error(f"服务异常：{str(e)}")


def _iterate_async(async_iterable):
    loop = asyncio.new_event_loop()
    iterator = async_iterable.__aiter__()
    try:
        while True:
            try:
                yield loop.run_until_complete(iterator.__anext__())
            except StopAsyncIteration:
                break
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            loop.close()


def chat_stream(request):
    """
    真正的 token 级流式接口（SSE）
    POST /api/ai/chat/stream/
    Body: 同 chat 接口
    Response: text/event-stream
        data: {"type": "chunk", "content": "..."}   <- 每个 token 片段
        data: {"type": "done"}                       <- 结束
        data: {"type": "error", "content": "..."}   <- 出错
    """
    if request.method != "POST":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["POST"])

    # 手动鉴权（async 视图不能用 @permission_classes）
    user = _auth_user(request)
    if user is None:
        from django.http import JsonResponse
        return JsonResponse({"code": 4010, "msg": "未授权"}, status=401)

    import json as _json
    try:
        body = _json.loads(request.body)
    except Exception:
        body = {}

    user_query = body.get("query", "").strip()
    if not user_query:
        from django.http import JsonResponse
        return JsonResponse({"code": 4000, "msg": "查询内容不能为空"}, status=400)

    started_at = time.perf_counter()
    context = {"user_id": user.id, "username": user.username}
    project_id = _resolve_request_project_id(body.get("project_id"))
    if project_id:
        context["project_id"] = project_id
        context.update(_build_project_snapshot(project_id))
    if body.get("project_name"):
        context["project_name"] = body["project_name"]
    if body.get("ring_range") and isinstance(body["ring_range"], list) and len(body["ring_range"]) == 2:
        context["ring_range"] = body["ring_range"]
    if body.get("route_mode"):
        context["route_mode"] = body.get("route_mode")

    context_ready_ms = (time.perf_counter() - started_at) * 1000
    assistant = get_assistant()
    assistant_ready_ms = (time.perf_counter() - started_at) * 1000

    def event_generator():
        route_stage = ""
        rule_branch = ""
        first_chunk_ms = None
        completed = False
        try:
            yield ": connected\n\n"
            for event in _iterate_async(assistant.chat_stream(user_query, context)):
                if event.get("type") == "meta":
                    route_stage = event.get("route_stage", "")
                    rule_branch = event.get("rule_branch", "")
                elif event.get("type") == "chunk" and first_chunk_ms is None:
                    first_chunk_ms = (time.perf_counter() - started_at) * 1000
                elif event.get("type") == "done":
                    completed = True
                data = json.dumps(event, ensure_ascii=False)
                yield f"data: {data}\n\n"
        except Exception as e:
            data = json.dumps({"type": "error", "content": str(e)}, ensure_ascii=False)
            yield f"data: {data}\n\n"
        finally:
            logger.info(
                "AI stream timing user_id=%s project_id=%s route_stage=%s rule_branch=%s "
                "context_ready_ms=%.1f assistant_ready_ms=%.1f first_chunk_ms=%s "
                "total_ms=%.1f completed=%s llm_ready=%s agent_ready=%s",
                user.id,
                context.get("project_id", ""),
                route_stage,
                rule_branch,
                context_ready_ms,
                assistant_ready_ms,
                f"{first_chunk_ms:.1f}" if first_chunk_ms is not None else "none",
                (time.perf_counter() - started_at) * 1000,
                completed,
                assistant.llm_runtime_ready,
                assistant.agent_runtime_ready,
            )

    response = StreamingHttpResponse(event_generator(), content_type="text/event-stream; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    response["Content-Encoding"] = "identity"
    response["X-Accel-Buffering"] = "no"
    response["Connection"] = "keep-alive"
    return response


@api_view(['GET'])
@permission_classes([])
def health_check(request):
    try:
        assistant = get_assistant()
        test_result = assistant.llm.invoke("你好")
        text = test_result.content if hasattr(test_result, 'content') else str(test_result)
        config = get_llm_config()
        return success({
            "status": "LLM服务正常",
            "provider": config.provider,
            "model": config.model,
            "base_url": config.base_url,
            "test_response": text[:50] + "..." if len(text) > 50 else text
        })
    except LLMProviderError as e:
        logger.error(f"LLM provider 配置失败：{e}")
        return error(f"LLM provider 配置失败：{str(e)}")
    except Exception as e:
        logger.error(f"健康检查失败：{e}")
        return error(f"LLM服务异常：{str(e)}")


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def conversation_history(request):
    """
    GET /api/ai/history/
    返回当前用户记忆中的对话消息，用于页面刷新后回填。只读接口，不触发模型调用。
    """
    try:
        assistant = get_assistant()
        return success(assistant.get_history(str(request.user.id)))
    except Exception as e:
        logger.error(f"获取对话历史失败：{e}")
        return error(f"获取历史失败：{str(e)}")


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reset_conversation(request):
    try:
        assistant = get_assistant()
        assistant.reset_memory(user_id=str(request.user.id))
        return success({"message": "对话已重置"})
    except Exception as e:
        logger.error(f"重置对话失败：{e}")
        return error(f"重置失败：{str(e)}")
