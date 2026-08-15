# -*- coding: utf-8 -*-
"""刀位编号的归一化、排序与业务有效刀位判定。"""

ACTIVE_CUTTER_POSITION_CODES = {
    *{str(number) for number in range(1, 80)},
    "80A",
    "80B",
    "Y1",
    "Y3",
    "Y5",
    *{f"S{number}{side}" for number in range(1, 20) for side in ("L", "R")},
}


def normalize_cutter_position_no(value):
    """归一化刀位编号：去空格、转大写；纯数字去掉前导零。

    与 views.py 的 _normalize_cutter_no 保持同一口径——此前两者不一致，
    导致 "046" 在一处通过、在另一处被拒。
    """
    code = str(value or "").strip().upper()
    if code.isdigit():
        return str(int(code))
    return code


def is_active_cutter_position(value, shield_machine_id=None):
    """判断刀位是否属于当前业务需要记录的范围。"""
    return normalize_cutter_position_no(value) in ACTIVE_CUTTER_POSITION_CODES


def cutter_position_sort_key(value):
    code = normalize_cutter_position_no(value)
    if code.isdigit():
        return (0, int(code), 0, "")
    if len(code) > 1 and code[:-1].isdigit() and code[-1:].isalpha():
        suffix = code[-1:]
        suffix_rank = ord(suffix) - ord("A") + 1
        return (0, int(code[:-1]), suffix_rank, "")
    if code.startswith("Y") and code[1:].isdigit():
        return (1, int(code[1:]), 0, "")
    if code.startswith("S"):
        body = code[1:]
        side = body[-1:] if body[-1:].isalpha() else ""
        number = body[:-1] if side else body
        if number.isdigit():
            side_rank = {"L": 0, "R": 1}.get(side, 2)
            return (2, int(number), side_rank, "")
    # G / H 等其他前缀：按数字排序、组内保持稳定，避免全部挤进兜底分组
    if len(code) > 1 and code[0].isalpha():
        digits = "".join(ch for ch in code if ch.isdigit())
        return (3, int(digits) if digits else 0, 0, code)
    return (9, 0, 0, code)


def sort_cutter_position_values(values):
    return sorted(values, key=cutter_position_sort_key)


def sort_cutter_position_items(items, key=lambda item: item):
    return sorted(items, key=lambda item: cutter_position_sort_key(key(item)))
