# -*- coding: utf-8 -*-
"""磨损状态的统一判定口径（全系统唯一真源）。

背景：wear_condition 是自由文本字段，历史上并存三套词表——
  1) models.py 声明的英文选项 GOOD/NORMAL/MODERATE/SEVERE/ABNORMAL；
  2) 开仓信号自动建明细时写入的英文 "NORMAL"；
  3) 现场实际录入的中文（正常/偏磨/刀圈崩刃/刀圈脱落/漏油/轴承损坏）。
各处统计各自为政（有的用中文白名单、有的用 != '正常' 黑名单），导致
同一个"异常率"在助手、看板、页面上给出数量级不同的答案。

本模块给出唯一判定：
  * 归一化为三态：NORMAL / ABNORMAL / None(未记录)；
  * **未记录不参与异常率的分子与分母**——"没录"不等于"正常"，也不等于"异常"；
  * 判定同时兼容中英文，且对未来新增的异常词表自动生效
    （凡是"有记录且不属于正常词"即为异常）。
"""

from django.db.models import Q

# 判定为"正常"的取值（中英文兼容，大小写不敏感）
NORMAL_WEAR_VALUES = (
    "正常", "良好", "完好", "无异常",
    "NORMAL", "GOOD",
)

# 已知的异常词，仅用于对外展示/文档；判定逻辑不依赖它（见模块注释）
KNOWN_ABNORMAL_VALUES = (
    "偏磨", "刀圈崩刃", "崩刃", "刀圈脱落", "脱落", "漏油",
    "轴承损坏", "断裂", "严重磨损", "中度磨损", "异常",
    "ABNORMAL", "MODERATE", "SEVERE",
)

_NORMAL_UPPER = {v.upper() for v in NORMAL_WEAR_VALUES}


def normalize_wear(value):
    """归一化磨损状态。

    返回 'NORMAL' / 'ABNORMAL' / None（未记录或无法识别）。
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.upper() in _NORMAL_UPPER:
        return "NORMAL"
    return "ABNORMAL"


def is_abnormal_wear(value):
    """是否为异常磨损（未记录返回 False，不要用它做分母）。"""
    return normalize_wear(value) == "ABNORMAL"


def is_wear_recorded(value):
    """该行是否记录了磨损状态（异常率的分母口径）。"""
    return normalize_wear(value) is not None


def classify_wear_counts(values):
    """批量分桶，返回 {'normal': n, 'abnormal': n, 'unrecorded': n, 'recorded': n}。"""
    normal = abnormal = unrecorded = 0
    for value in values:
        state = normalize_wear(value)
        if state == "NORMAL":
            normal += 1
        elif state == "ABNORMAL":
            abnormal += 1
        else:
            unrecorded += 1
    return {
        "normal": normal,
        "abnormal": abnormal,
        "unrecorded": unrecorded,
        "recorded": normal + abnormal,
    }


def abnormal_rate(values, ndigits=1):
    """异常率 = 异常数 / 有记录数（无记录时返回 None，而不是 0）。"""
    counts = classify_wear_counts(values)
    if not counts["recorded"]:
        return None
    return round(counts["abnormal"] / counts["recorded"] * 100, ndigits)


# ── ORM 侧的等价条件（供 Count(filter=...) / filter() 使用） ──────────────
# 注意：这里用"有记录 且 不属于正常词"来定义异常，与 normalize_wear 保持一致，
# 因此新增异常词表无需改代码。

def q_wear_recorded(field="wear_condition"):
    return ~Q(**{f"{field}__isnull": True}) & ~Q(**{field: ""})


def q_wear_normal(field="wear_condition"):
    return Q(**{f"{field}__in": NORMAL_WEAR_VALUES})


def q_wear_abnormal(field="wear_condition"):
    return q_wear_recorded(field) & ~q_wear_normal(field)


Q_WEAR_RECORDED = q_wear_recorded()
Q_WEAR_NORMAL = q_wear_normal()
Q_WEAR_ABNORMAL = q_wear_abnormal()


# 英文码 → 中文展示名（现场录入本身就是中文，原样返回即可）
_DISPLAY_MAP = {
    "NORMAL": "正常", "GOOD": "良好",
    "MODERATE": "中度磨损", "SEVERE": "严重磨损", "ABNORMAL": "异常磨损",
}


def wear_display(value):
    """磨损状态的可读文案：英文码转中文，中文原样返回，未记录返回空串。"""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return _DISPLAY_MAP.get(text.upper(), text)
