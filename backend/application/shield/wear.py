# -*- coding: utf-8 -*-
"""磨损状态的统一判定口径（全系统唯一真源）。

背景：wear_condition 是自由文本字段，历史上并存三套词表——
  1) models.py 声明的英文选项 GOOD/NORMAL/MODERATE/SEVERE/ABNORMAL；
  2) 开仓信号自动建明细时写入的英文 "NORMAL"；
  3) 现场实际录入的中文（正常/偏磨/刀圈崩刃/刀圈脱落/漏油/轴承损坏）。
各处统计各自为政（有的用中文白名单、有的用 != '正常' 黑名单），导致
同一个"异常率"在助手、看板、页面上给出数量级不同的答案。

本模块给出唯一判定：
  * 归一化为三态：NORMAL / ABNORMAL / None(未记录或未识别)；
  * 只有已识别状态参与异常率分母，未知文本不能推断成异常；
  * 判定同时兼容中英文，Python 与 ORM 共用词表和首尾空白规则。
"""

from django.db.models import CharField, F, Func, Q, Value
from django.db.models.functions import Upper
from django.db.models.lookups import In

# 判定为"正常"的取值（中英文兼容，大小写不敏感）
NORMAL_WEAR_VALUES = (
    "正常", "良好", "完好", "无异常", "正常磨损", "轻微磨损", "未见异常",
    "NORMAL", "GOOD",
)

# 只有已确认含义的词进入异常桶；新增词需在此处明确分类。
KNOWN_ABNORMAL_VALUES = (
    "偏磨", "刀圈崩刃", "崩刃", "刀圈脱落", "脱落", "漏油",
    "轴承损坏", "断裂", "严重磨损", "中度磨损", "异常", "异常磨损",
    "崩口", "刀圈磨平", "刀体磨损", "CHIP",
    "ABNORMAL", "MODERATE", "SEVERE",
)

_NORMAL_UPPER = {v.upper() for v in NORMAL_WEAR_VALUES}
_ABNORMAL_UPPER = {v.upper() for v in KNOWN_ABNORMAL_VALUES}
# Python str.strip() 的空白字符集；SQL TRIM 默认仅处理普通空格。
_WEAR_WHITESPACE = " \t\n\r\v\f\x1c\x1d\x1e\x1f\x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"


def normalize_wear(value):
    """归一化磨损状态。

    返回 'NORMAL' / 'ABNORMAL' / None（未记录或无法识别）。
    """
    if value is None:
        return None
    text = str(value).strip(_WEAR_WHITESPACE)
    if not text:
        return None
    if text.upper() in _NORMAL_UPPER:
        return "NORMAL"
    if text.upper() in _ABNORMAL_UPPER:
        return "ABNORMAL"
    return None


def is_abnormal_wear(value):
    """是否为异常磨损（未记录或未识别返回 False，不要用它做分母）。"""
    return normalize_wear(value) == "ABNORMAL"


def is_wear_recorded(value):
    """该行是否记录了可识别磨损状态（异常率的分母口径）。"""
    return normalize_wear(value) is not None


def classify_wear_counts(values):
    """批量分桶；保留 unrecorded 字段名，包含未记录和未识别状态。"""
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
    """异常率 = 异常数 / 已识别状态数（无可分类记录返回 None）。"""
    counts = classify_wear_counts(values)
    if not counts["recorded"]:
        return None
    return round(counts["abnormal"] / counts["recorded"] * 100, ndigits)


# ── ORM 侧的等价条件（供 Count(filter=...) / filter() 使用） ──────────────
# 与 normalize_wear 同样 trim/upper 后按明确词表分类，未知不进入分母。

class _WearTrim(Func):
    function = "BTRIM"
    output_field = CharField()

    def as_sqlite(self, compiler, connection, **extra_context):
        return self.as_sql(compiler, connection, function="TRIM", **extra_context)


def _q_wear_tokens(field, values):
    normalized = Upper(_WearTrim(F(field), Value(_WEAR_WHITESPACE)))
    return Q(In(normalized, tuple(value.upper() for value in values)))


def q_wear_recorded(field="wear_condition"):
    return _q_wear_tokens(field, NORMAL_WEAR_VALUES + KNOWN_ABNORMAL_VALUES)


def q_wear_normal(field="wear_condition"):
    return _q_wear_tokens(field, NORMAL_WEAR_VALUES)


def q_wear_abnormal(field="wear_condition"):
    return _q_wear_tokens(field, KNOWN_ABNORMAL_VALUES)


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
