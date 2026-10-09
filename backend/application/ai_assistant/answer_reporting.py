"""Presentation only: render tool results without changing query calculations."""

from datetime import datetime
from math import isfinite


def number(value):
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        result = float(str(value).rstrip("%"))
        return result if isfinite(result) else None
    except (ValueError, TypeError):
        return None


def display(value, unit=""):
    if value is None or value == "":
        return "暂无"
    if isinstance(value, float):
        if not isfinite(value):
            return "暂无"
        value = f"{value:.3f}".rstrip("0").rstrip(".")
    return f"{value}{unit}"


def percent(value, denominator=None):
    if denominator is not None and number(denominator) == 0:
        return "暂无（无有效样本）"
    return display(value, "" if isinstance(value, str) and value.endswith("%") else "%")


def range_text(value):
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return f"{display(value[0])}–{display(value[1])} 环"
    return "全部环号" if value == "全部" else display(value)


def scope_text(scope=None, include_tool_type=True):
    scope = scope or {}
    parts = [range_text(scope["ring_range"]) if scope.get("ring_range") else "全项目范围（不限定环号）"]
    if include_tool_type:
        parts.append({"DISC": "滚刀", "SCRAPER": "刮刀", "RIPPER": "撕裂刀"}.get(scope.get("tool_type"), "全部刀具"))
    if include_tool_type and scope.get("cutter_position_no"):
        parts.append(f"刀位 {scope['cutter_position_no']}")
    return " · ".join(parts)


class Report:
    def __init__(self, title, data, table, scope=None, object_name="记录", include_tool_type=True):
        self.data = data
        self.table_builder = table
        self.lines = [f"## {title}", ""]
        if scope is not None:
            self.lines.append(f"分析范围：{scope_text(scope, include_tool_type)}。")
        elif data.get("ring_range"):
            self.lines.append(f"数据范围：{range_text(data['ring_range'])}。")
        else:
            self.lines.append(f"分析范围：本次查询匹配的{object_name}；环号覆盖未提供。")
        if scope is not None and data.get("ring_range"):
            self.lines.append(f"结果标注环号范围：{range_text(data['ring_range'])}。")
        self.notes = []

    def text(self, text):
        self.lines.extend(["", text])

    def table(self, title, headers, rows, limit=12, total=None):
        if not rows:
            return
        count = len(rows)
        self.lines.extend(["", f"### {title}", ""])
        if total is not None and total != count:
            self.lines.append(f"共 {display(total)} 项，本次返回 {count} 项，展示 {min(count, limit)} 项。")
        elif count > limit:
            self.lines.append(f"共 {count} 项，展示前 {limit} 项。")
        self.lines.extend(self.table_builder(headers, rows[:limit]))

    def finish(self, *notes):
        all_notes = [*self.notes, *notes, *(self.data.get("warnings") or [])]
        unique = list(dict.fromkeys(str(note) for note in all_notes if note))
        if unique:
            self.lines.extend(["", "### 统计口径与数据限制", "", *[f"- {note}" for note in unique]])
        return "\n".join(self.lines)


def segment_label(segment):
    if segment.get("segment_index"):
        return f"环号 {display(segment.get('ring_range'))} 第 {display(segment.get('segment_index'))}/{display(segment.get('segment_count'))} 段"
    return display(segment.get("ring_range"))


def render_report(kind, data, table, scope=None, penetration_unit=""):
    titles = {
        "change_trend": "换刀分段统计", "manufacturer": "厂家记录对比",
        "stratum_distribution": "地层分布", "stratum_wear": "地层与换刀记录对照",
        "position_stratum": "刀位与地层记录对照", "tunneling_summary": "掘进参数概览",
        "tunneling_trend": "掘进参数分段统计", "tunneling_anomaly": "掘进参数异常筛查",
        "tunneling_correlation": "掘进与换刀分段对照", "recommendation": "刀具选型参考",
        "performance": "刀具服役追溯",
    }
    if isinstance(data, list):
        data = {"recommendations": data}
    report = Report(titles[kind], data, table, scope, include_tool_type=not (kind.startswith("tunneling_") or kind == "stratum_distribution"))
    if kind == "performance":
        report.lines[2:] = ["分析范围：按请求的完整刀具编号追溯，逐条使用安装与拆卸证据，不附加历史环号或刀型条件。"]
    if data.get("error"):
        report.text(f"查询失败：{data['error']}")
        return report.finish("未取得完整数据，不作统计判断。")
    if data.get("message"):
        report.text(str(data["message"]))
    if kind.startswith("tunneling_") and data.get("total_records") == 0:
        if not data.get("message"):
            report.text("未找到符合条件的掘进动态记录。")
        return report.finish("没有可分析样本，不能将缺失数据解释为参数正常、无异常或工况平稳。")
    if kind == "change_trend":
        segments = data.get("segments") or []
        valid = [s for s in segments if (number(s.get("total")) or 0) > 0 and number(s.get("replacement_rate")) is not None]
        report.text(f"按 **{display(data.get('interval'))} 环/段** 展示，共 {len(segments)} 段，其中 {len(valid)} 段有可计算更换率的观测记录。")
        if len(valid) >= 2:
            first, last = valid[0], valid[-1]
            report.text(f"首个有效段（{segment_label(first)}）更换率 {percent(first.get('replacement_rate'))}，末个有效段（{segment_label(last)}）为 {percent(last.get('replacement_rate'))}。")
        else:
            report.text("有效分段不足 2 个，无法比较首尾变化。")
        report.table("分段明细", ["环段", "观测记录数", "更换次数", "更换率"], [
            [segment_label(s), s.get("total"), s.get("replaced"), percent(s.get("replacement_rate"), s.get("total"))] for s in segments
        ])
        return report.finish("更换率 = 更换记录数 ÷ 该段观测记录数；不是每百环换刀频率。", "首尾比率比较不构成统计趋势检验，不能据此判断整个过程平稳或持续升降。", "空段没有观测，不能将工具返回的 0% 解释为未发生更换；尾段分箱边界可能超过实际数据末环。")
    if kind == "manufacturer":
        items = data.get("manufacturers") or []
        report.text(f"匹配 **{display(data.get('total_records'))}** 条含厂家记录，覆盖 **{display(data.get('manufacturer_count', len(items)))}** 个厂家。")
        rows = []
        for item in items:
            denominator = item.get("abnormal_rate_denominator")
            if denominator is None and item.get("normal_wear_count") is not None and item.get("abnormal_wear_count") is not None:
                denominator = item["normal_wear_count"] + item["abnormal_wear_count"]
            rate = percent(item.get("abnormal_rate_pct"), denominator) if denominator is not None else "暂无（分母未提供）"
            rows.append([item.get("manufacturer"), item.get("replaced_count"), denominator, item.get("abnormal_wear_count"), item.get("unclassified_wear_count"), rate, item.get("avg_cost_per_change_yuan")])
        report.table("厂家明细", ["厂家", "更换次数", "已分类样本数", "异常记录数", "未分类记录数", "已分类异常率", "记录平均价格（元）"], rows, total=data.get("manufacturer_count"))
        return report.finish("异常率 = 已更换且已分类的异常磨损记录数 ÷ 已更换且已分类记录数；未分类记录不计入分母。", "保留原结果顺序；无已分类样本时不展示 0% 优势。异常率较低不代表厂家综合表现或质量更好，比较需结合样本量、刀型、地层和服役条件。", "记录平均价格来自带价格字段的明细，不等于实际采购加返修总成本；缺失价格不按 0 元处理。")
    if kind == "stratum_distribution":
        distribution = data.get("stratum_distribution") or {}
        report.text(f"匹配 **{display(data.get('total_rings'))}** 条地层环号记录，包含 {len(distribution)} 类地层标签。")
        report.table("地层标签分布", ["地层", "标签出现记录数"], [[name, count] for name, count in sorted(distribution.items(), key=lambda item: item[1], reverse=True)])
        return report.finish("同一环号可包含多个地层标签，各类计数可以重叠，不能将其相加当作独立环数；无标签的记录仍可能计入匹配总数。")
    if kind == "stratum_wear":
        items = data.get("stratum_analysis") or []
        report.text(f"本次对照 **{display(data.get('stratum_count', len(items)))}** 类地层；未知地层关联记录 **{display(data.get('unknown_stratum_records'))}** 条。")
        report.table("地层与更换记录", ["地层", "地层记录数", "关联观测数", "更换次数", "更换率", "主要磨损", "高频刀位"], [
            [item.get("stratum_name") or item.get("stratum_type"), item.get("ring_count"), item.get("total_records"), item.get("replaced_count"), percent(item.get("replacement_rate"), item.get("total_records")),
             "、".join(f"{display(w.get('wear_condition'))} {display(w.get('count'))}次" for w in item.get("top_wear_conditions") or []) or None,
             "、".join(f"{display(p.get('position'))} {display(p.get('count'))}次" for p in item.get("top_replaced_positions") or []) or None] for item in items
        ], total=data.get("stratum_count"))
        return report.finish("更换率 = 该地层关联更换记录数 ÷ 关联观测记录数，不代表单位推进距离的换刀频率。", "同一环可属于多种地层，关联计数可重复；不同地层计数不能直接相加。主要磨损及高频刀位是工具返回的前列项目。", "本表反映记录关联，不证明地层导致磨损；缺失地层单列，比较需控制刀型、工况与样本量。")
    if kind == "position_stratum":
        items = data.get("top_positions") or []
        report.text(f"本次返回 **{len(items)}** 个刀位的地层关联记录，查询未提供全部匹配刀位总数。")
        report.table("刀位与地层", ["刀位", "地层标签关联次数", "各地层关联次数"], [
            [item.get("position"), item.get("total"), "、".join(f"{name} {display(count)}次" for name, count in (item.get("by_stratum") or {}).items()) or None] for item in items
        ])
        return report.finish("同一更换记录对应多个地层标签时会重复计数，合计不一定等于该刀位实际更换次数。", "关联次数受观测量影响，不能据此认定刀位受地层影响更大或推断因果。")
    if kind in {"tunneling_summary", "tunneling_anomaly"}:
        metrics = data.get("metrics") or {}
        report.text(f"匹配 **{display(data.get('total_records'))}** 条掘进动态记录。")
        fields = [("thrust", "总推力", "kN"), ("torque", "刀盘扭矩", "kNm"), ("cutterhead_speed", "刀盘转速", "r/min"), ("penetration", "贯入力", penetration_unit or "原始单位未标注")]
        report.table("参数统计", ["参数", "单位", "平均值", "最小值", "最大值"], [[label, unit, (metrics.get(key) or {}).get("avg"), (metrics.get(key) or {}).get("min"), (metrics.get(key) or {}).get("max")] for key, label, unit in fields])
        if kind == "tunneling_anomaly":
            anomalies = data.get("anomaly_fields") or []
            eligible = [key for key in ("thrust", "torque", "penetration") if number((metrics.get(key) or {}).get("avg")) not in (None, 0) and number((metrics.get(key) or {}).get("max")) is not None]
            report.text(f"已有规则标记 **{len(anomalies)}** 项峰值偏高指标。" if anomalies else "本次未标记峰值偏高指标；不等同于全部参数正常。")
            if len(eligible) < 3:
                report.notes.append("部分指标缺少有效均值/最大值，或均值为 0，无法完成峰值倍数比较。")
            names = {key: (label, unit) for key, label, unit in fields}
            report.table("异常筛查结果", ["参数", "单位", "平均值", "最大值"], [[names.get(a.get("field"), (a.get("field"), "未标注"))[0], names.get(a.get("field"), ("", "未标注"))[1], a.get("avg"), a.get("max")] for a in anomalies])
            report.notes.append("筛查依据为规则返回的峰值标记，不是故障诊断；本结果未提供各峰值对应时间或环号，不能据此定位异常发生位置。")
        recent = data.get("recent_records") or []
        report.table("最近记录", ["环号", "记录时间", "推力（kN）", "扭矩（kNm）", "转速（r/min）", f"贯入力（{penetration_unit or '原始单位未标注'}）"], [[r.get("ring_no"), r.get("record_time"), r.get("thrust"), r.get("torque"), r.get("cutterhead_speed"), r.get("penetration")] for r in recent], total=data.get("total_records"))
        return report.finish("各指标按非空值计算；总记录数不等于每项指标的有效样本数。暂无与实测 0 分别展示。", "未提供时序与地层控制分析，不根据均值或最大值直接推断地层、操作原因或设备故障。")
    if kind in {"tunneling_trend", "tunneling_correlation"}:
        segments = data.get("segments") or []
        time_mode = any(s.get("segment_index") for s in segments)
        report.text(f"匹配 **{display(data.get('total_records'))}** 条掘进记录，共 {len(segments)} 段；" + ("按单环内时间顺序分段统计。" if time_mode else f"按 {display(data.get('interval'))} 环分段。"))
        if not data.get("ring_range") and segments:
            report.text(f"分段覆盖：{segment_label(segments[0])} 至 {segment_label(segments[-1])}；分段边界不一定是实际采样首末环。")
        valid = [s for s in segments if number(s.get("avg_penetration")) is not None]
        if len(valid) < 2:
            report.text("贯入力有效分段不足 2 个，无法比较首尾变化。")
        else:
            report.text(f"贯入力首个有效段均值 {display(valid[0].get('avg_penetration'), penetration_unit)}，末个有效段均值 {display(valid[-1].get('avg_penetration'), penetration_unit)}；仅作首尾描述，不构成统计趋势结论。")
        report.table("掘进分段明细", ["环段", "采样点数" if time_mode else "记录数", "平均推力（kN）", "平均扭矩（kNm）", "平均转速（r/min）", f"平均贯入力（{penetration_unit or '原始单位未标注'}）", "起止时间"], [
            [segment_label(s), s.get("count", s.get("tunneling_count")), s.get("avg_thrust"), s.get("avg_torque"), s.get("avg_cutterhead_speed"), s.get("avg_penetration"), f"{display(s.get('start_time'))} 至 {display(s.get('end_time'))}" if s.get("start_time") or s.get("end_time") else None] for s in segments
        ])
        if time_mode:
            report.notes.append("单环时间分段的采样点数来自汇总记录的点数字段；字段缺失或为 0 时工具回退为 1，不能视为已验证的原始采样点总数。分段均值来自对应汇总记录，与数据库记录条数分别展示。")
        if kind == "tunneling_correlation":
            report.table("同环段换刀与地层", ["环段", "换刀观测数", "更换次数", "异常磨损记录数", "主要地层"], [[segment_label(s), s.get("tool_change_count"), s.get("replacement_count"), s.get("abnormal_wear_count"), s.get("main_stratum")] for s in segments])
            report.notes.append("同环段聚集不等于因果或统计相关性；未提供相关系数、显著性检验或混杂因素控制。")
            report.notes.append("掘进、换刀明细和地层均按项目及环号关联；本对照不按刀型或具体刀位拆分。")
        for prior, current in zip(segments, segments[1:]):
            if prior.get("end_time") and current.get("start_time"):
                try:
                    gap = (datetime.fromisoformat(str(current["start_time"])) - datetime.fromisoformat(str(prior["end_time"]))).total_seconds() / 60
                    if gap >= 30:
                        report.notes.append(f"{segment_label(prior)} 至 {segment_label(current)} 采集间隔约 {display(gap)} 分钟，需核对停机或数据缺口。")
                except (ValueError, TypeError):
                    pass
        return report.finish("分段均值基于各指标非空样本；暂无不是 0，分段记录数不等于每项有效样本数。", "首尾变化不能证明整体工况平稳、持续升降，也不能直接解释掘进阻力或效率变化。")
    if kind == "recommendation":
        criteria = data.get("criteria") or {}
        items = data.get("recommendations") or []
        insufficient = data.get("insufficient_evidence") or []
        report.text(f"涉及 **{display(data.get('tool_model_count'))}** 种型号，满足排名条件 **{display(data.get('ranked_count', len(items)))}** 种；按历史平均已完成服役环数排序。")
        report.text(f"选型筛选：安装环号 {range_text(criteria.get('ring_range'))}；刀型 {display(criteria.get('tool_type'))}；地层 {'、'.join(criteria['stratum_types']) if isinstance(criteria.get('stratum_types'), list) else display(criteria.get('stratum_types'))}；最少完成服役样本 {display(criteria.get('min_samples', 3))} 把。")
        if criteria.get("max_unit_price_yuan") is not None:
            report.text(f"单价上限：{display(criteria['max_unit_price_yuan'])} 元。")
        report.table("型号服役表现", ["排名", "型号", "刀型", "厂家", "安装数", "完成服役数", "在役数", "平均服役（环）", "最短/最长（环）"], [[i.get("rank"), i.get("tool_type_name"), i.get("tool_parent_type"), i.get("manufacturer"), i.get("installed_count"), i.get("completed_service_count"), i.get("in_service_count"), i.get("avg_service_rings"), f"{display(i.get('min_service_rings'))} / {display(i.get('max_service_rings'))}"] for i in items], total=data.get("ranked_count"))
        report.table("价格参考", ["型号", "参考单价（元）", "折合每环价格（元/环）"], [[i.get("tool_type_name"), i.get("unit_price_yuan"), i.get("cost_per_ring_yuan")] for i in items])
        report.table("样本不足的返回型号", ["型号", "安装数", "完成服役数"], [[i.get("tool_type_name"), i.get("installed_count"), i.get("completed_service_count")] for i in insufficient])
        if not items:
            report.text("暂无满足排名条件的型号；不据此指定优先采购型号。")
        return report.finish("服役环数按安装与拆卸依据计算；未拆下刀具不参与已完成服役平均值，该均值不代表全部刀具的真实寿命或剩余寿命。", "每环价格仅为参考单价除以平均服役环数，不包含完整采购、返修和停机支出。", "库存字段没有独立库存台账验证，本回答不展示为可用库存。样本不足型号可能已被查询限制截取，不代表全量清单。", "型号排序未控制地层和工况差异，不能直接替代备刀数量计划。")
    if kind == "performance":
        items = data.get("tools") or []
        missing = data.get("not_found") or []
        report.text(f"命中 **{len(items)}** 条服役追溯记录；未找到 **{len(missing)}** 个请求编号。")
        rows = []
        lifecycle = {"INSTALLED": "在役", "REMOVED_PENDING_INSPECTION": "待厂家检测", "INSPECTED": "厂家已确认", "REPAIRED_CLOSED": "返修闭环", "SCRAPPED": "已报废"}
        for item in items:
            status = item.get("status")
            service = item.get("service_rings") if status == "已拆下" and not item.get("install_ring_inferred") else None
            evidence = []
            if item.get("install_ring_inferred"):
                evidence.append("安装环号由继承记录推断，可能偏晚")
            if item.get("removal_inferred"):
                evidence.append("拆卸环号由后续换刀记录推断，需核对旧刀记录")
            if service is None:
                evidence.append("安装或拆卸依据不足，暂不给出数值" if status != "在役" else "尚未拆下，暂不给出数值")
            if status not in {"已拆下", "在役"}:
                evidence.append("当前状态：待核实")
            identity = f"机器 {display(item.get('shield_machine_id'))}；实例 {display(item.get('tool_uid'))}"
            rows.append([item.get("tool_number"), identity, item.get("cutter_position_no"), item.get("tool_type_name"), status, item.get("install_ring_no"), item.get("removal_ring_no"), service, lifecycle.get(item.get("lifecycle_status"), item.get("lifecycle_status")), "；".join(evidence) or "按安装与拆卸记录"])
        report.table("服役记录", ["刀具编号", "机器与实例标识", "刀位", "型号", "状态", "安装环号", "拆卸环号", "服役（环）", "生命周期状态", "依据与限制"], rows)
        report.table("检查记录汇总", ["刀具编号", "机器/实例", "厂家", "检查次数", "异常检查次数"], [[i.get("tool_number"), f"{display(i.get('shield_machine_id'))} / {display(i.get('tool_uid'))}", i.get("manufacturer"), i.get("inspection_count"), i.get("abnormal_inspection_count")] for i in items])
        if missing:
            report.text("未找到的编号：" + "、".join(map(str, missing)) + "。请核对完整编号或改查刀位。")
        return report.finish("每条记录按同项目、同盾构机、同刀位的安装与旧刀身份关系追溯；跨记录不得混算。", "服役环数 = 拆卸环号 − 安装环号。在役刀具尚未完成服役，不能与已拆下刀具直接比较寿命；未知状态不等于在役。", "安装当次的磨损属于换下旧刀，不计入新刀的检查历史。")
    raise ValueError(f"Unknown report kind: {kind}")


def render_abnormal_cause(change, stratum, tunneling, opening, params, table, penetration_unit=""):
    """Keep each source's population explicit; no inferred causal explanation."""
    report = Report("异常磨损多源核对", {}, table, params)
    detail_scope = scope_text(params)
    whole_scope = scope_text({"ring_range": params.get("ring_range")})
    report.text("以下为同一请求下的数据对照，用于定位需要复核的记录，不据此认定异常磨损原因。")
    report.table("数据来源与范围", ["数据来源", "范围与筛选", "返回情况"], [
        ["换刀观测", detail_scope, f"观测 {display(change.get('total_records'))} 条；更换 {display(change.get('replaced_count'))} 次"],
        ["地层与磨损", detail_scope, f"{display(stratum.get('stratum_count', len(stratum.get('stratum_analysis') or [])))} 类地层关联"],
        ["掘进与换刀对照", f"掘进参数按环号筛选，不按刀型拆分；查询/分段环号范围 {range_text(tunneling.get('ring_range'))}", f"掘进 {display(tunneling.get('total_records'))} 条；关联明细按环号统计，不能冒充刀型专属因果证据"],
        ["开仓汇总", whole_scope + "；整仓数量，不按刀型/刀位拆分", f"本次返回最近 {len(opening.get('recent_records') or [])} 次，最多 5 次"],
    ])
    report.table("换刀与磨损", ["观测记录数", "更换次数", "更换率"], [[change.get("total_records"), change.get("replaced_count"), percent(change.get("replacement_rate"), change.get("total_records"))]])
    report.table("磨损记录分布", ["磨损状态", "记录数"], [[w.get("wear_condition") or "未分类", w.get("count")] for w in change.get("wear_distribution") or []])
    report.table("地层关联明细", ["地层", "关联观测数", "更换次数", "更换率"], [[s.get("stratum_name") or s.get("stratum_type"), s.get("total_records"), s.get("replaced_count"), percent(s.get("replacement_rate"), s.get("total_records"))] for s in stratum.get("stratum_analysis") or []])
    report.table("掘进与换刀分段", ["环段", "掘进记录数", "平均扭矩（kNm）", f"平均贯入力（{penetration_unit or '原始单位未标注'}）", "更换次数", "异常磨损次数"], [[s.get("ring_range"), s.get("tunneling_count"), s.get("avg_torque"), s.get("avg_penetration"), s.get("replacement_count"), s.get("abnormal_wear_count")] for s in tunneling.get("segments") or []])
    records = opening.get("recent_records") or []
    report.table("整仓与现场明细核对", ["开仓环号", "整仓更换数", "数量来源", "现场明细数", "已分类异常率", "高频刀位"], [[r.get("ring_no"), r.get("tool_change_replaced"), "已确认汇总" if r.get("count_source") == "confirmed_summary" else "现场明细（未确认）", r.get("detail_record_count"), r.get("abnormal_rate"), "、".join(map(str, r.get("top_replaced_positions") or [])) or None] for r in records])
    for name, source in [("换刀", change), ("地层", stratum), ("掘进", tunneling), ("开仓", opening)]:
        if source.get("error"):
            report.notes.append(f"{name}查询失败：{source['error']}；该来源未取得有效结果，不能解读为无记录。")
        report.notes.extend(f"{name}：{warning}" for warning in source.get("warnings") or [])
        if source.get("message"):
            report.notes.append(f"{name}：{source['message']}")
    for record in records:
        report.notes.extend(f"开仓环号 {display(record.get('ring_no'))}：{warning}" for warning in record.get("warnings") or [])
    return report.finish("更换率按观测记录计算；异常率按已分类磨损记录计算，二者分母不同。空值不按 0 处理。", "地层标签可重叠，关联计数不能跨地层直接求和；开仓整仓汇总与现场明细分别核对。", "上述结果没有相关性检验、因果识别或工况控制，不能由高频刀位、地层标签或峰值重合直接断言安装异常、硬岩冲击或掘进参数导致磨损。")
