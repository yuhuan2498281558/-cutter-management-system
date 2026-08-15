# -*- coding: utf-8 -*-
import base64
import time

import requests as _requests
from django.http import JsonResponse
from django.views import View
from django.conf import settings

from application.shield.models import CutterModelMapping, CutterPositionInfo, ToolChangeDetail

BIMFACE_APP_KEY = getattr(settings, "BIMFACE_APP_KEY", "")
BIMFACE_APP_SECRET = getattr(settings, "BIMFACE_APP_SECRET", "")
BIMFACE_FILE_ID = getattr(settings, "BIMFACE_FILE_ID", "")

_access_token_cache = {"token": None, "expires_at": 0}
_view_token_cache = {"token": None, "expires_at": 0}


def _normalize_wear_condition(value):
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    upper = raw.upper()
    if upper in {"GOOD", "NORMAL", "MODERATE", "SEVERE", "ABNORMAL"}:
        return upper
    if any(word in raw for word in ["严重", "崩刃", "脱落", "漏油", "轴承损坏", "断裂"]):
        return "SEVERE"
    if any(word in raw for word in ["中度", "中等"]):
        return "MODERATE"
    if any(word in raw for word in ["偏磨", "异常"]):
        return "ABNORMAL"
    if "良好" in raw:
        return "GOOD"
    if "正常" in raw:
        return "NORMAL"
    return "UNKNOWN"


def _ring_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_cutter_no(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    upper = raw.upper()
    return str(int(upper)) if upper.isdigit() else upper


def _get_credentials_header():
    raw = f"{BIMFACE_APP_KEY}:{BIMFACE_APP_SECRET}"
    return "Basic " + base64.b64encode(raw.encode()).decode()


def _fetch_access_token():
    if not BIMFACE_APP_KEY or not BIMFACE_APP_SECRET:
        raise RuntimeError("BIMFace integration is not configured")
    if _access_token_cache["token"] and time.time() < _access_token_cache["expires_at"]:
        return _access_token_cache["token"]

    resp = _requests.post(
        "https://api.bimface.com/oauth2/token",
        headers={
            "Authorization": _get_credentials_header(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "client_credentials"},
        timeout=30,
    )
    data = resp.json()
    d = data.get("data")
    # data 可能是字符串（token 本身）或对象 {"token": "..."}
    if isinstance(d, str):
        token = d
    elif isinstance(d, dict):
        token = d.get("token") or d.get("access_token")
    else:
        token = data.get("access_token")
    if not token:
        raise RuntimeError(f"获取 AccessToken 失败: {data}")

    _access_token_cache["token"] = token
    _access_token_cache["expires_at"] = time.time() + 12 * 3600 - 600
    return token


def _fetch_view_token():
    if not BIMFACE_FILE_ID:
        raise RuntimeError("BIMFace model file is not configured")
    if _view_token_cache["token"] and time.time() < _view_token_cache["expires_at"] - 300:
        return _view_token_cache["token"]

    access_token = _fetch_access_token()
    resp = _requests.get(
        "https://api.bimface.com/view/token",
        params={"fileId": str(BIMFACE_FILE_ID)},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    data = resp.json()
    d = data.get("data")
    if isinstance(d, str):
        token = d
    elif isinstance(d, dict):
        token = d.get("token")
    else:
        token = data.get("token")
    if not token:
        raise RuntimeError(f"获取 ViewToken 失败: {data}")

    _view_token_cache["token"] = token
    _view_token_cache["expires_at"] = time.time() + 12 * 3600
    return token


class BimfaceViewTokenView(View):
    def get(self, request):
        try:
            view_token = _fetch_view_token()
            return JsonResponse({"code": 2000, "data": {"viewToken": view_token}, "msg": "success"})
        except Exception as e:
            return JsonResponse({"code": 4000, "data": None, "msg": str(e)}, status=200)


class BimfaceCutterModelMappingView(View):
    def get(self, request):
        data = []
        mappings = (
            CutterModelMapping.objects
            .select_related("cutter_position", "cutter_position__tool_info")
            .filter(is_active=True)
        )
        for item in mappings:
            pos = item.cutter_position
            data.append({
                "id": item.id,
                "model_point_code": item.model_point_code,
                "component_id": item.component_id,
                "cutter_position_no": pos.cutter_position_no,
                "tool_type": pos.tool_type,
                "tool_type_display": pos.get_tool_type_display(),
                "tool_name": pos.tool_info.tool_type_name if pos.tool_info else "",
                "screen_x": item.screen_x,
                "screen_y": item.screen_y,
                "sort_no": item.sort_no,
            })
        return JsonResponse({"code": 2000, "data": data, "msg": "success"})


class BimfaceCutterStatusView(View):
    def get(self, request):
        latest_records = {}
        details = (
            ToolChangeDetail.objects
            .select_related("warehouse")
            .filter(cutter_position_no__isnull=False)
            .exclude(cutter_position_no="")
        )
        for detail in details:
            key = _normalize_cutter_no(detail.cutter_position_no)
            ring = _ring_int(detail.warehouse.ring_no if detail.warehouse else None)
            current = latest_records.get(key)
            current_ring = current[0] if current else None
            if current is None or (ring is not None and (current_ring is None or ring > current_ring)):
                latest_records[key] = (ring, detail)

        result = {}
        positions = CutterPositionInfo.objects.select_related("tool_info").all()
        for pos in positions:
            code = pos.cutter_position_no
            record = latest_records.get(_normalize_cutter_no(code), (None, None))[1]
            warehouse = record.warehouse if record else None
            result[code] = {
                "code": code,
                "tool_type": pos.tool_type,
                "tool_type_display": pos.get_tool_type_display(),
                "wear_condition": _normalize_wear_condition(record.wear_condition if record else None),
                "wear_label": record.wear_condition if record else None,
                "is_replaced": record.is_replaced if record else None,
                "ring_no": warehouse.ring_no if warehouse else None,
                "tool_number": record.tool_number if record else None,
            }
        return JsonResponse({"code": 2000, "data": result, "msg": "success"})


class BimfaceComponentPropertiesView(View):
    """查询单个构件的属性，用于从构件 ID 找到刀位编号"""
    def get(self, request, component_id):
        try:
            access_token = _fetch_access_token()
            file_id = str(BIMFACE_FILE_ID)
            headers = {"Authorization": f"Bearer {access_token}"}

            # 尝试多种接口格式
            for url, kwargs in [
                (
                    f"https://api.bimface.com/data/v2/files/{file_id}/elements/properties",
                    {"json": {"objectIds": [component_id]}, "method": "post"},
                ),
                (
                    f"https://api.bimface.com/data/v2/files/{file_id}/elements/{component_id}",
                    {"method": "get"},
                ),
            ]:
                method = kwargs.pop("method", "get")
                fn = getattr(_requests, method)
                resp = fn(url, headers=headers, timeout=15, **kwargs)
                data = resp.json()
                if data.get("code") == "success":
                    return JsonResponse({"ok": True, "data": data.get("data")})

            return JsonResponse({"ok": False, "detail": "构件属性查询失败"}, status=404)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=502)
