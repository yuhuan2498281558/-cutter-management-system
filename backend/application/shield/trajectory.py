"""刀具轨迹的统一规则。

轨迹表示刀具中心到刀盘圆心的径向距离，单位为毫米。系统当前刀位号及
安装位置保持不变，按机械图纸集第 19 页的安装位置对应第 20、24、35 页
的标注半径；图纸编号仅用于溯源，不用于重排系统刀位。未核实刀位不返回
猜测值。S19 的中心参考半径与开挖侧定位半径分别列出。
"""


def _normalize_position(value):
    code = str(value or "").strip().upper().replace("-", "")
    if code.isdigit():
        return str(int(code))
    return code


DRAWING_ROLLER_RADII_MM = {
    **{number: 135 + (number - 1) * 120 for number in range(1, 13)},
    13: 1555,
    14: 1655,
    15: 1755,
    16: 1855,
    17: 1955,
    **{number: 2035 + (number - 18) * 80 for number in range(18, 71)},
    71: 6266,
    72: 6352.8,
    73: 6436.3,
    74: 6515.4,
    75: 6591.1,
    76: 6658.4,
    77: 6718.6,
    78: 6770.8,
    79: 6809.8,
    "80A": 6830.0,
    "80B": 6830.0,
}

# Current upper-right/downward arms use different numbers from drawing page 19.
# Keys are CURRENT position numbers; values are drawing references, not new IDs.
CURRENT_TO_DRAWING_ROLLER = {
    14: 18, 16: 21, 25: 30, 28: 33, 37: 42,
    40: 45, 49: 54, 52: 57, 61: 66, 64: 69,
    18: 14, 21: 16, 30: 25, 33: 28, 42: 37,
    45: 40, 54: 49, 57: 52, 66: 61, 69: 64,
}
ROLLER_POSITION_RADII_MM = {
    code: DRAWING_ROLLER_RADII_MM[CURRENT_TO_DRAWING_ROLLER.get(code, code)]
    for code in DRAWING_ROLLER_RADII_MM
}

# Page 19 front view: #1 left, #2 lower-right, #3 upper-right.
# Current positions at those locations are Y3, Y1, Y5 respectively.
CURRENT_TO_DRAWING_Y = {"Y1": "#2", "Y3": "#1", "Y5": "#3"}
Y_ROLLER_POSITION_RADII_MM = {
    "Y1": 6809.8,
    "Y3": 6770.8,
    "Y5": 6830.0,
}


SCRAPER_POSITION_RADII_MM = {
    code: radius
    for number, radius in enumerate(
        (3430, 3620, 3810, 4000, 4190, 4380, 4570, 4760, 4950, 5140,
         5330, 5520, 5710, 5900, 6090, 6303.9, 6493.1, 6651, 6765.2),
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
    drawing_code = code
    if parent_type == "DISC":
        key = int(code) if code.isdigit() else code
        radius = ROLLER_POSITION_RADII_MM.get(key)
        drawing_code = str(CURRENT_TO_DRAWING_ROLLER.get(key, key))
        source = f"机械图纸集.pdf 第19页位置、第24页轨迹；当前{code}号对应图纸{drawing_code}号"
        if radius is None:
            radius = Y_ROLLER_POSITION_RADII_MM.get(code)
            if radius is not None:
                drawing_code = CURRENT_TO_DRAWING_Y[code]
                source = f"机械图纸集.pdf 第19页位置、第20页轨迹；当前{code}对应图纸{drawing_code}"
    elif parent_type == "SCRAPER":
        radius = SCRAPER_POSITION_RADII_MM.get(code)
        source = "机械图纸集.pdf 第19页位置、第20、35页轨迹"
        if code in ("S19L", "S19R"):
            source += "；R6765.2为中心参考，安装按开挖侧R6810定位"
    else:
        radius = None
        source = "刀盘-最终.pdf及更新图纸"

    if radius is not None:
        result = {
            "status": "CONFIRMED",
            "radius_mm": radius,
            "display": f"R{_format_radius(radius)} mm",
            "source": source,
            "drawing_position_no": drawing_code,
        }
        if parent_type == "SCRAPER" and code in ("S19L", "S19R"):
            result["excavation_radius_mm"] = 6810
        return result
    return {
        "status": "PENDING_REVIEW",
        "radius_mm": None,
        "display": "待按最终图纸核对",
        "source": "刀盘-最终.pdf及更新图纸",
    }
