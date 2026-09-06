from django.db.models import IntegerField, Q
from django.db.models.functions import Cast

from application.shield.models import NewToolRecord, OldToolRecord


def _previous_tool_instance(detail):
    """Return the most recent installed instance before the current opening."""
    try:
        current_ring = int(detail.warehouse.ring_no)
    except (AttributeError, TypeError, ValueError):
        return None

    candidates = (
        NewToolRecord.objects
        .filter(
            tool_change_detail__warehouse__project=detail.warehouse.project,
            tool_change_detail__warehouse__shield_model=detail.warehouse.shield_model,
            tool_change_detail__cutter_position_no=detail.cutter_position_no,
        )
        .exclude(tool_change_detail=detail)
        .select_related("tool_instance", "tool_change_detail__warehouse")
        .filter(tool_change_detail__warehouse__ring_no__regex=r"^\d+$")
        .annotate(
            ring_int=Cast(
                "tool_change_detail__warehouse__ring_no",
                output_field=IntegerField(),
            )
        )
        .filter(
            Q(ring_int__lt=current_ring)
            | (
                Q(ring_int=current_ring)
                & Q(tool_change_detail__warehouse__open_time__lt=detail.warehouse.open_time)
            )
        )
        .order_by("-ring_int", "-tool_change_detail__warehouse__open_time")
    )
    used_ids = OldToolRecord.objects.exclude(
        confirmed_tool_instance=None
    ).values_list("confirmed_tool_instance_id", flat=True)
    record = candidates.exclude(tool_instance_id__in=used_ids).first()
    return record.tool_instance if record else None


def resolve_removed_tool_identity(detail):
    """Resolve the instance and number removed by the current replacement.

    After a replacement, ``ToolChangeDetail.tool_number`` represents the newly
    installed tool. It may only be used as the removed-tool fallback before a
    ``NewToolRecord`` exists.
    """
    old_record = getattr(detail, "old_tool_record", None)
    instance = None
    if old_record is not None:
        instance = (
            old_record.confirmed_tool_instance
            or old_record.suggested_tool_instance
        )
    if instance is None:
        instance = _previous_tool_instance(detail)

    existing_number = (
        str(old_record.old_tool_number or "").strip()
        if old_record is not None else ""
    )
    if existing_number:
        return instance, existing_number

    current_install = getattr(detail, "new_tool_record", None)
    detail_number = str(detail.tool_number or "").strip()
    if current_install is None and detail_number:
        return instance, detail_number

    instance_number = str(
        getattr(instance, "display_tool_no", "") or ""
    ).strip()
    return instance, instance_number
