"""Validated public tool arguments; project and identity are request-bound."""
from typing import Annotated, Literal
import json

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from application.shield.cutter_position_scope import (
    ACTIVE_CUTTER_POSITION_CODES, normalize_cutter_position_no,
)

Ring = Annotated[StrictInt, Field(ge=1, le=999_999_999)]
Count = Annotated[StrictInt, Field(ge=1, le=100)]
Interval = Annotated[StrictInt, Field(ge=1, le=500)]


def tool_validation_error(error):
    """Return a recoverable observation without echoing untrusted input values."""
    fields = [".".join(str(part) for part in item['loc']) for item in error.errors()]
    return json.dumps({
        'error': '工具参数校验失败，请按工具schema纠正参数后重试；不得改成更大的查询范围。',
        'code': 'invalid_tool_arguments', 'fields': fields[:10],
    }, ensure_ascii=False)


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


class ChangeQuery(ToolQuery):
    last_n_openings: Annotated[StrictInt, Field(ge=0, le=100)] = 0
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


class RecordQuery(RingQuery):
    limit: Count = 10


class PositionQuery(ToolQuery):
    top_n: Count = 10


class ChangeTrendQuery(ToolQuery):
    interval: Interval = 50


class TunnelingTrendQuery(RingQuery):
    interval: Interval = 50


class AnomalyQuery(RingQuery):
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


class RecommendationQuery(ToolQuery):
    stratum_types: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(default_factory=list, max_length=50)
    max_unit_price: float = Field(default=0, ge=0, allow_inf_nan=False, strict=True)
    top_n: Annotated[StrictInt, Field(ge=1, le=50)] = 5

    @field_validator("stratum_types")
    @classmethod
    def normalized_codes(cls, value):
        if any(not code.strip() for code in value):
            raise ValueError("地层代码不能为空白")
        return list(dict.fromkeys(code.strip().upper() for code in value))
