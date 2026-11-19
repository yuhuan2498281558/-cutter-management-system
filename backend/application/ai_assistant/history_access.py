from dataclasses import replace
from hashlib import sha256
import json

from django.core.exceptions import EmptyResultSet

from application.shield.analysis_metrics import scoped_queryset
from application.shield.models import WarehouseOpeningBasicInfo
from .memory_service import MemoryService, MemorySnapshot


def access_stamp(project_id) -> str:
    # 对实际过滤 SQL 取指纹，避免另写一套权限规则后与实时查询分歧。
    queryset = scoped_queryset(WarehouseOpeningBasicInfo.objects.filter(project__project_id=project_id))
    try:
        scope = str(queryset.query)
    except EmptyResultSet:
        scope = "EmptyResultSet"
    return sha256(f"{project_id or ''}\n{scope}".encode("utf-8")).hexdigest()[:32]


def authorized_snapshot(snapshot: MemorySnapshot, project_id, stamp) -> MemorySnapshot:
    if snapshot.backend == "ablate":
        return snapshot
    project_id = str(project_id or "")
    turns = MemoryService._complete_turns(snapshot.messages)
    allowed = [turn for turn in turns
               if turn[0].metadata.get("project_id") == project_id
               and turn[0].metadata.get("access_stamp") == stamp]
    events = [turn for turn in snapshot.context_events
              if turn["project_id"] == project_id and any(
                  event["kind"] in {"turn_commit", "compaction"}
                  and json.loads(event["payload"]).get("access_stamp") == stamp
                  for event in turn["events"])]
    # 槽位由最后保存的一轮写入：只有存储里最后一条就是获授权的回答时才沿用，末尾残缺的轮次也不算
    return replace(
        snapshot, messages=[item for turn in allowed for item in turn], context_events=events,
        slots=dict(snapshot.slots) if allowed and allowed[-1][1].sequence == snapshot.last_sequence else {},
        withheld_turns=snapshot.withheld_turns + len(turns) - len(allowed),
    )
