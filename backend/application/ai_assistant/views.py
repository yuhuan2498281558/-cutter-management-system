"""
Django视图 - 提供HTTP接口
"""

import json
import logging
import re
import time
from contextlib import aclosing
from types import SimpleNamespace

from asgiref.sync import sync_to_async
from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from application.shield.analysis_metrics import ANALYSIS_REQUEST, scoped_queryset
from application.shield.models import ProjectInfo

from .llm_service import get_assistant, _data_coverage, FOCUS_SOURCE_LABELS

logger = logging.getLogger(__name__)

_GUEST_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


def _analysis_scope_request(user):
    """借用数据分析页总览接口的权限范围：返回一个只用于数据范围过滤的请求对象。"""
    # 过滤器按请求地址精确找按钮，分析页每个接口各有一份范围，AI 统一用总览这份
    return SimpleNamespace(user=user, method="GET", path="/api/shield/analysis/overview/",
                           parser_context={"kwargs": {}})


def _resolve_request_project_id(project_id=None) -> str:
    """未指定项目时，仅在权限范围内恰好有一个项目时自动补全。"""
    if project_id not in (None, ""):
        return str(project_id)

    project_ids = list(
        scoped_queryset(ProjectInfo.objects.all()).values_list("project_id", flat=True)[:2]
    )
    return str(project_ids[0]) if len(project_ids) == 1 else ""


def _authorized_project_id(project_id=None) -> str:
    project_id = _resolve_request_project_id(project_id)
    if project_id and not scoped_queryset(ProjectInfo.objects.filter(project_id=project_id)).exists():
        raise PermissionError("无权查看该项目的数据")
    return project_id


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
            CutterPositionInfo,
        )
        from application.shield.cutter_position_scope import is_active_cutter_position
        from .tools import _active_detail_query
        from django.db.models import Count, IntegerField, Max, Q
        from django.db.models.functions import Cast

        # 开仓记录统计
        warehouse_qs = scoped_queryset(WarehouseOpeningBasicInfo.objects.filter(
            project__project_id=project_id
        ))
        warehouse_stats = warehouse_qs.filter(ring_no__regex=r'^\d+$').annotate(
            ring_int=Cast('ring_no', output_field=IntegerField())
        ).aggregate(
            total=Count('id'),
            latest_ring=Max('ring_int'),
        )
        total_openings = warehouse_stats['total'] or 0
        latest_ring = warehouse_stats['latest_ring'] or '未知'

        changes = _active_detail_query({'project_id': project_id}).aggregate(
            total=Count('id'), replaced=Count('id', filter=Q(is_replaced=True)),
        )
        total_changes, total_replaced = changes['total'], changes['replaced']
        positions = scoped_queryset(CutterPositionInfo.objects.filter(
            shield_machine_id__in=warehouse_qs.values('shield_model_id'),
        )).values_list('cutter_position_no', 'tool_type')
        total_positions = sum(is_active_cutter_position(code, kind) for code, kind in positions)

        return {
            'snapshot_total_openings': total_openings,
            'snapshot_latest_ring': latest_ring,
            'snapshot_total_changes': total_changes,
            'snapshot_total_replaced': total_replaced,
            'snapshot_total_positions': total_positions,
            'snapshot_tunneling_coverage': _data_coverage(project_id, "掘进"),
            'snapshot_stratum_coverage': _data_coverage(project_id, "地层"),
        }
    except Exception as e:
        logger.warning(f"项目快照查询失败（project_id={project_id}）：{e}")
        return {}


def _memory_user_id(user, token=None) -> str | int:
    """Keep shared web-guest conversations isolated by login session."""
    if user.username != settings.WEB_GUEST_USERNAME:
        return user.id

    payload = getattr(token, "payload", token)
    get_claim = getattr(payload, "get", None)
    session_id = get_claim(settings.WEB_GUEST_SESSION_CLAIM) if get_claim else None
    if not session_id and get_claim:
        session_id = get_claim("jti")
    session_id = str(session_id or "")
    if not _GUEST_SESSION_RE.fullmatch(session_id):
        raise ValueError("游客会话标识无效，请重新登录")
    return f"guest-session-{user.id}-{session_id}"


def _context_for_user(user, body, token=None) -> dict:
    ctx = {
        "user_id": _memory_user_id(user, token),
        "username": user.username,
        "require_project": True,
        "data_scope": _analysis_scope_request(user),
    }
    scope_token = ANALYSIS_REQUEST.set(ctx["data_scope"])
    try:
        project_id = _authorized_project_id(body.get("project_id"))
        if project_id:
            ctx["project_id"] = project_id
            ctx.update(_build_project_snapshot(project_id))
    finally:
        ANALYSIS_REQUEST.reset(scope_token)
    if body.get("project_name"):
        ctx["project_name"] = body["project_name"]
    if body.get("ring_range") and isinstance(body["ring_range"], list) and len(body["ring_range"]) == 2:
        ctx["ring_range"] = body["ring_range"]
    if body.get("route_mode"):
        ctx["route_mode"] = body["route_mode"]
    ctx["context_mode"] = body.get("context_mode", "auto")
    ctx["clear_slots"] = list(body.get("clear_slots", []))
    ctx["focus_sources"] = list(dict.fromkeys(body.get("focus_sources", [])))
    return ctx


def _build_context(request) -> dict:
    return _context_for_user(request.user, request.data, request.auth)


def _validate_body(body):
    if not isinstance(body, dict):
        return "请求内容必须为 JSON 对象"
    query = body.get('query')
    if not isinstance(query, str) or not query.strip():
        return "查询内容不能为空"
    if len(query) > 10000:
        return "查询内容不能超过 10000 个字符"
    if body.get('project_id') is not None and not isinstance(body['project_id'], (str, int)):
        return "项目编号格式错误"
    if body.get('route_mode') is not None and body['route_mode'] not in ('rule', 'agent', 'hybrid'):
        return "查询模式格式错误"
    if body.get('context_mode', 'auto') not in ('auto', 'new', 'continue'):
        return "上下文模式必须为 auto、new 或 continue"
    focus_sources = body.get('focus_sources', [])
    if (not isinstance(focus_sources, list) or len(focus_sources) > 10
            or any(not isinstance(source, str) or source not in FOCUS_SOURCE_LABELS for source in focus_sources)):
        return "focus_sources 只能包含：tool_change、opening、inspection、position、stratum、tunneling、manufacturer、cost、repair、lifecycle"
    clear_slots = body.get('clear_slots', [])
    if (not isinstance(clear_slots, list) or len(clear_slots) > 3
            or any(not isinstance(slot, str) or slot not in (
                'ring_range', 'tool_type', 'cutter_position_no',
            ) for slot in clear_slots)):
        return "只能清除环号范围、刀具类型或刀位条件"
    rings = body.get('ring_range')
    if rings:
        if not isinstance(rings, list) or len(rings) != 2 or any(type(value) is not int or value < 1 for value in rings) or rings[0] > rings[1]:
            return "环号范围必须为两个递增的正整数"
    return None


def _auth_user(request):
    """从 Authorization: JWT <token> 头手动验证，返回 user 或 None"""
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth_header.startswith("JWT "):
        logger.warning("stream auth: JWT authorization header missing")
        return None
    try:
        raw_token = auth_header.split(" ", 1)[1]
        auth = JWTAuthentication()
        validated = auth.get_validated_token(raw_token)
        request.ai_validated_token = validated
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
    validation_error = _validate_body(request.data)
    if validation_error:
        return Response({'code': 4000, 'data': None, 'msg': validation_error}, status=400)
    user_query = request.data['query'].strip()

    started_at = time.perf_counter()
    try:
        context = _build_context(request)
    except PermissionError:
        return Response({'code': 4030, 'data': None, 'msg': '无权查看该项目的数据'}, status=403)
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


async def chat_stream(request):
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
    user = await sync_to_async(_auth_user)(request)
    if user is None:
        return JsonResponse({"code": 4010, "msg": "未授权"}, status=401)

    try:
        body = json.loads(request.body)
    except Exception:
        body = {}

    validation_error = _validate_body(body)
    if validation_error:
        return JsonResponse({"code": 4000, "msg": validation_error}, status=400)
    user_query = body['query'].strip()

    started_at = time.perf_counter()
    try:
        context = await sync_to_async(_context_for_user)(
            user,
            body,
            getattr(request, "ai_validated_token", None),
        )
    except PermissionError:
        return JsonResponse({'code': 4030, 'msg': '无权查看该项目的数据'}, status=403)

    context_ready_ms = (time.perf_counter() - started_at) * 1000
    assistant = await sync_to_async(get_assistant)()
    assistant_ready_ms = (time.perf_counter() - started_at) * 1000

    async def event_generator():
        route_stage = ""
        rule_branch = ""
        first_chunk_ms = None
        completed = False
        try:
            yield ": connected\n\n"
            async with aclosing(assistant.chat_stream(user_query, context)) as events:
                async for event in events:
                    if event.get("type") == "meta":
                        route_stage = event.get("route_stage", "")
                        rule_branch = event.get("rule_branch", "")
                    elif event.get("type") in ("chunk", "answer") and first_chunk_ms is None:
                        first_chunk_ms = (time.perf_counter() - started_at) * 1000
                    elif event.get("type") == "done":
                        completed = True
                    data = json.dumps(event, ensure_ascii=False)
                    yield f"data: {data}\n\n"
        except Exception as e:
            logger.exception("AI stream response failed")
            data = json.dumps({"type": "error", "content": "对话服务暂时不可用，请稍后重试"}, ensure_ascii=False)
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
    """Liveness only; public monitoring must never spend model quota."""
    return success({"status": "服务在线", "model_checked": False})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def conversation_history(request):
    """
    GET /api/ai/history/
    返回当前用户记忆中的对话消息，用于页面刷新后回填。只读接口，不触发模型调用。
    """
    try:
        assistant = get_assistant()
        try:
            before = request.query_params.get('before_sequence')
            before = int(before) if before is not None else None
            limit = int(request.query_params.get('limit', 50))
            if before is not None and before < 1 or not 1 <= limit <= 100:
                raise ValueError
        except (TypeError, ValueError):
            return error('历史分页参数格式错误')
        memory_user_id = _memory_user_id(request.user, request.auth)
        scope_token = ANALYSIS_REQUEST.set(_analysis_scope_request(request.user))
        try:
            project_id = _authorized_project_id(request.query_params.get('project_id'))
            return success(assistant.get_history(str(memory_user_id), before_sequence=before, limit=limit,
                                                 project_id=project_id))
        finally:
            ANALYSIS_REQUEST.reset(scope_token)
    except PermissionError:
        return Response({'code': 4030, 'data': None, 'msg': '无权查看该项目的数据'}, status=403)
    except Exception as e:
        logger.error(f"获取对话历史失败：{e}")
        return error(f"获取历史失败：{str(e)}")


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reset_conversation(request):
    try:
        assistant = get_assistant()
        memory_user_id = _memory_user_id(request.user, request.auth)
        assistant.reset_memory(user_id=str(memory_user_id))
        return success({"message": "对话已重置"})
    except Exception as e:
        logger.error(f"重置对话失败：{e}")
        return error(f"重置失败：{str(e)}")
