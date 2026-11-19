"""Validated public tool arguments; project and identity are request-bound."""
from typing import Annotated, Literal
import json

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StringConstraints, field_validator, model_validator

from .agent_views import AGENT_PAGE_SIZE

from application.shield.cutter_position_scope import (
    ACTIVE_CUTTER_POSITION_CODES, normalize_cutter_position_no,
)

Ring = Annotated[StrictInt, Field(ge=1, le=999_999_999)]
Count = Annotated[StrictInt, Field(ge=1, le=100)]
Interval = Annotated[StrictInt, Field(ge=1, le=500)]
PositiveInt = Annotated[StrictInt, Field(ge=1)]
Nonblank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ListLimit = Annotated[StrictInt, Field(ge=1, le=200)]


def tool_validation_error(error):
    """Return a recoverable observation without echoing untrusted input values."""
    fields = [".".join(str(part) for part in item['loc']) for item in error.errors()]
    return json.dumps({
        'error': '工具参数校验失败，请按工具schema纠正参数后重试；不得改成更大的查询范围。',
        'code': 'invalid_tool_arguments', 'fields': fields[:10],
    }, ensure_ascii=False)


class _PagingQuery(BaseModel):
    page: Annotated[StrictInt, Field(ge=1, le=50)] = 1
    page_size: Annotated[StrictInt, Field(ge=5, le=50)] = AGENT_PAGE_SIZE


class RingQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)
    ring_range: list[Ring] = Field(default_factory=list, max_length=2,
                                  description="空数组表示不限环号，否则为递增的两个正整数（含端点）")

    @field_validator("ring_range")
    @classmethod
    def ordered_range(cls, value):
        if value and (len(value) != 2 or value[0] > value[1]):
            raise ValueError("环号范围须为空或两个递增的正整数")
        return value


class ToolQuery(RingQuery):
    tool_type: Literal["", "DISC", "SCRAPER"] = ""

    @field_validator("tool_type", mode="before")
    @classmethod
    def normalized_type(cls, value):
        return value.strip().upper() if isinstance(value, str) else value


class PositionFilterQuery(ToolQuery):
    cutter_position_no: str = Field(default="", max_length=16)

    @field_validator("cutter_position_no")
    @classmethod
    def active_position(cls, value):
        value = normalize_cutter_position_no(value)
        if value and value not in ACTIVE_CUTTER_POSITION_CODES:
            raise ValueError("刀位不在当前有效122刀位范围内")
        return value

    @model_validator(mode="after")
    def matching_type(self):
        if self.tool_type and self.cutter_position_no:
            expected = "SCRAPER" if self.cutter_position_no.startswith("S") else "DISC"
            if self.tool_type != expected:
                raise ValueError("刀型与刀位不匹配，请核对查询对象")
        return self


class ChangeQuery(PositionFilterQuery):
    last_n_openings: Annotated[StrictInt, Field(ge=0, le=100)] = 0


class RecordQuery(RingQuery, _PagingQuery):
    limit: Count = 10


class OpeningQuery(RecordQuery):
    summary_status: Literal["", "CONFIRMED", "DRAFT"] = ""


class PositionImpactQuery(ToolQuery, _PagingQuery):
    top_n: Count = 10


class PositionQuery(PositionFilterQuery, _PagingQuery):
    top_n: Annotated[StrictInt, Field(ge=1, le=122)] = 10
    include_all: StrictBool = False
    sort_by: Literal["replaced", "abnormal"] = "replaced"


class ChangeTrendQuery(ToolQuery, _PagingQuery):
    interval: Interval = 50


class TunnelingTrendQuery(RingQuery, _PagingQuery):
    interval: Interval = 50


class AnomalyQuery(RingQuery, _PagingQuery):
    threshold_k: float = Field(default=1.5, gt=0, allow_inf_nan=False, strict=True)


class PerformanceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_numbers: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(min_length=1, max_length=100)

    @field_validator("tool_numbers")
    @classmethod
    def nonblank_numbers(cls, value):
        if any(not number.strip() for number in value):
            raise ValueError("刀具实例编号不能为空")
        return list(dict.fromkeys(number.strip() for number in value))


class RecommendationQuery(ToolQuery, _PagingQuery):
    sort_by: Literal["service", "price_per_ring"] = "service"
    stratum_types: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(default_factory=list, max_length=50)
    max_unit_price: float = Field(default=0, ge=0, allow_inf_nan=False, strict=True)
    top_n: Annotated[StrictInt, Field(ge=1, le=50)] = 5
    stratum_basis: Literal["label", "longitudinal_area"] = "label"
    min_samples: PositiveInt = 3

    @field_validator("stratum_types")
    @classmethod
    def normalized_codes(cls, value):
        if any(not code.strip() for code in value):
            raise ValueError("地层代码不能为空白")
        return list(dict.fromkeys(code.strip().upper() for code in value))

    @model_validator(mode="after")
    def known_stratum_codes(self):
        from .tools import STRATUM_TYPE_NAMES
        from application.shield.longitudinal_ratios import AREA_LABELS
        allowed = STRATUM_TYPE_NAMES if self.stratum_basis == "label" else AREA_LABELS
        if any(code not in allowed for code in self.stratum_types):
            raise ValueError("地层编码与 stratum_basis 不匹配或不存在")
        return self


class InspectionQuery(PositionFilterQuery, _PagingQuery):
    shield_machine_id: PositiveInt | None = None
    recent_openings: Count | None = None
    check_result: Literal["PENDING", "NOT_REPLACED", "NORMAL", "ATTENTION", "ABNORMAL_NOT_REPLACED"] | None = None
    list_limit: ListLimit = 20

    @model_validator(mode="after")
    def exclusive_window(self):
        if self.ring_range and self.recent_openings is not None:
            raise ValueError("recent_openings 和 ring_range 只能给一个")
        return self


class RepairQuery(PositionFilterQuery, _PagingQuery):
    components: list[Literal["轴承", "刀圈", "刀毂"]] = Field(default_factory=list)
    shield_machine_id: PositiveInt | None = None
    inspection_status: Literal["PENDING_VENDOR_FEEDBACK", "CONFIRMED", "CLOSED"] | None = None
    disposition: Literal["SCRAP", "REPAIRABLE"] | None = None
    list_limit: ListLimit = 20


class LifecycleQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_ids: list[Nonblank] = Field(min_length=1, max_length=20)


class ManufacturerServiceQuery(ToolQuery, _PagingQuery):
    shield_machine_id: PositiveInt | None = None
    manufacturers: list[Nonblank] = Field(default_factory=list)
    min_samples: PositiveInt = 3


class ToolMileageQuery(ToolQuery, _PagingQuery):
    shield_machine_id: PositiveInt | None = None
    manufacturers: list[Nonblank] = Field(default_factory=list)
    cutter_position_no: Nonblank | None = None


class StratumAreaQuery(RingQuery, _PagingQuery):
    rings: list[Ring] = Field(default_factory=list, max_length=50)
    basis: Literal["longitudinal_area", "cross_section"] = "longitudinal_area"

    @model_validator(mode="after")
    def exclusive_rings(self):
        if self.ring_range and self.rings:
            raise ValueError("rings 和 ring_range 只能给一个")
        if len(set(self.rings)) != len(self.rings):
            raise ValueError("rings 中的环号不能重复")
        return self


class OpeningStratumQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shield_machine_id: PositiveInt | None = None
    ring_no: PositiveInt | None = None
    recent_openings: Annotated[StrictInt, Field(ge=1, le=20)] | None = None

    @model_validator(mode="after")
    def exclusive_opening(self):
        if self.ring_no is not None and self.recent_openings is not None:
            raise ValueError("ring_no 和 recent_openings 只能给一个")
        return self


class CostCatalogQuery(_PagingQuery):
    model_config = ConfigDict(extra="forbid")
    tool_type: Literal["DISC", "RIPPER", "SCRAPER"] | None = None
    tool_model: Nonblank | None = None
    brand: Nonblank | None = None
    manufacturer: Nonblank | None = None
    cost_type: Literal["NEW_TOOL", "REPAIR"] | None = None
    list_limit: ListLimit = 50


class RegisteredAmountsQuery(RingQuery, _PagingQuery):
    tool_type: Literal["DISC", "RIPPER", "SCRAPER"] | None = None
    shield_machine_id: PositiveInt | None = None
    group_by: Literal["none", "manufacturer", "tool_type", "opening"] = "none"


class DataCatalogQuery(_PagingQuery):
    model_config = ConfigDict(extra="forbid")
