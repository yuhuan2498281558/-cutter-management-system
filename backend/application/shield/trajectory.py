"""刀具轨迹的统一规则。

轨迹表示刀具中心到刀盘圆心的径向距离，单位为毫米。滚刀 1-80 的
半径来自机械图纸集第 24 页和最终刀盘图；尚未能从图纸确认的刀位不返回
猜测值，前端统一显示为待核对。
"""


def _normalize_position(value):
    code = str(value or "").strip().upper().replace("-", "")
    if code.isdigit():
        return str(int(code))
    return code


ROLLER_POSITION_RADII_MM = {
    **{number: 135 + (number - 1) * 120 for number in range(1, 13)},
    13: 1555,
    14: 1655,
    15: 1755,
    16: 1855,
    17: 1955,
    **{number: 2035 + (number - 18) * 80 for number in range(18, 71)},
    71: 6195,
    72: 6266,
    73: 6352.8,
    74: 6436.3,
    75: 6515.4,
    76: 6591.1,
    77: 6658.4,
    78: 6718.6,
    79: 6770.8,
    "80A": 6809.8,
    "80B": 6830.0,
}

# Y1/Y3/Y5 are the three retained single-disc positions in the final cutterhead
# plan. Their tracks are the radial distances shown by the same drawing scale
# used for the S-position track list; Y2/Y4/Y6 are intentionally out of scope.
Y_ROLLER_POSITION_RADII_MM = {
    "Y1": 6605,
    "Y3": 6650,
    "Y5": 6670,
}


SCRAPER_POSITION_RADII_MM = {
    code: radius
    for number, radius in enumerate(
        (3390, 3580, 3790, 3960, 4170, 4340, 4590, 4770, 4970, 5150,
         5350, 5540, 5730, 5910, 6120, 6300, 6460, 6670, 6760),
        start=1,
    )
    for code in (f"S{number}L", f"S{number}R")
}


def _format_radius(value):
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.1f}".rstrip("0").rstrip(".")


def get_tool_trajectory(cutter_position_no, tool_parent_type=None):
    """Return a stable trajectory payload for API responses."""
    code = _normalize_position(cutter_position_no)
    parent_type = str(tool_parent_type or "DISC").upper()
    if parent_type == "DISC":
        key = int(code) if code.isdigit() else code
        radius = ROLLER_POSITION_RADII_MM.get(key)
        source = "机械图纸集.pdf 第24页"
        if radius is None:
            radius = Y_ROLLER_POSITION_RADII_MM.get(code)
            if radius is not None:
                source = "刀盘-最终.pdf"
    elif parent_type == "SCRAPER":
        radius = SCRAPER_POSITION_RADII_MM.get(code)
        source = "刀盘-最终.pdf及更新图纸"
    else:
        radius = None
        source = "刀盘-最终.pdf及更新图纸"

    if radius is not None:
        return {
            "status": "CONFIRMED",
            "radius_mm": radius,
            "display": f"R{_format_radius(radius)} mm",
            "source": source,
        }
    return {
        "status": "PENDING_REVIEW",
        "radius_mm": None,
        "display": "待按最终图纸核对",
        "source": "刀盘-最终.pdf及更新图纸",
    }
