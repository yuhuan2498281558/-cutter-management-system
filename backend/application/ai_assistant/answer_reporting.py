"""Presentation only: render tool results without changing query calculations."""

from datetime import datetime
from math import isfinite
import re


def requested_sections(kind, question):
    metrics = {
        'tool_change': {'counts': ('观测', '更换', '换刀'), 'positions': ('刀位',), 'wear': ('磨损',), 'abnormal': ('异常',)},
        'opening': {'interval': ('间隔', '多少环'), 'duration': ('时长',), 'counts': ('检查', '更换'), 'abnormal': ('异常',)},
        'manufacturer_service': {'service': ('寿命', '服役', '异常率', '磨损率'), 'abnormal_types': ('类型',),
                                 'supply': ('供货', '金额', '登记', '成本', '费用'),
                                 'unconfirmed': ('待反馈', '未确认', '缺确认', '身份', '在役')},
        'old_tool_repairs': {'status': ('进度', '反馈', '归档'), 'scrap': ('报废',), 'amount': ('金额', '钱', '费用'),
                             'reasons': ('部件', '轴承', '刀圈', '刀毂', '失效原因')},
    }
    selected = {key for key, words in metrics.get(kind, {}).items() if any(word in question for word in words)}
    if any(word in question for word in ('全面', '综合', '详细', '完整', '报告')) or not selected:
        selected = set(metrics.get(kind, {}))
        selected.add('full')
    if any(word in question for word in ('明细', '名单', '哪些刀', '旧刀有哪些')) or ('列出' in question and not re.search(r'数量|多少|金额|报价|损坏', question)):
        selected.add('details')
    return selected


def opening_positions(record):
    if record.get('positions_all_once'):
        return '各 1 次'
    return '、'.join(f"{p['cutter_position_no']}（{p['count']}）" for p in record.get('top_replaced_positions') or [] if p['count'] >= 2) or '—'


def opening_means(data):
    count, total = len(data.get('recent_records') or []), data.get('total_openings', data.get('total', 0))
    lines = []
    if count < total:
        lines.append(f"最近 {count} 次：平均间隔 {display(data.get('recent_avg_rings_between_openings'))} 环，平均开仓时长 {display(data.get('recent_avg_opening_duration_hours'))} 小时。")
    lines.append(f"全部 {total} 次：平均间隔 {display(data.get('avg_rings_between_openings'))} 环，平均开仓时长 {display(data.get('avg_opening_duration_hours'))} 小时。")
    return lines


def number(value):
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        result = float(str(value).rstrip("%"))
        return result if isfinite(result) else None
    except (ValueError, TypeError):
        return None


# 每转贯入量：第 5 环推进速度 ÷ 贯入度逐点积分的圈数与刀盘计数器吻合
PENETRATION_UNIT = "mm/r"


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


def _refresh_table(report, title, headers, rows, total=None):
    count = len(rows) if total is None else total
    if count > 20:
        report.text(f"{title}：共 {count} 条，显示前 {min(20, len(rows))} 条。")
    report.table(title, headers, rows[:20], limit=20)


def _money_text(value):
    amount = number(value)
    return f"{amount:.2f}" if amount is not None else "暂无"


# “各型号内……分别排序”这类按组排序的说法
GROUPED_SORT = re.compile(r"(?:各|每个|每种|每一)[^，。；\n]{0,8}?(?:内|中|里)|分别")


def wants_manufacturer_prices(question):
    return bool(re.search(r"逐家|各厂家|按厂家|每家", question) and re.search(r"报价|价格|单价", question))


def manufacturer_price_order(question, query_spec=None):
    match = re.search(r"每环(?:报价|价格|单价)[^，。；\n]{0,12}?(从低到高|从高到低|升序|降序)", question)
    if match:
        return "desc" if match[1] in ("从高到低", "降序") else "asc"
    return "asc" if (query_spec or {}).get("sort_by") == "price_per_ring" else None


def manufacturer_price_table(recommendations, order, grouped=False):
    rows, seen, models = [], set(), {}
    for item in recommendations:
        index = models.setdefault(item.get("tool_type_name"), len(models))
        for quote in item.get("manufacturer_prices") or []:
            key = (item.get("tool_type_name"), quote.get("manufacturer"), quote.get("brand") or "")
            if key in seen:
                continue
            seen.add(key)
            rows.append((index, item, quote))
    if not rows:
        return []
    def sort_key(row):
        value = row[2].get("price_per_ring_yuan" if order else "unit_price_yuan")
        price = (value is None, -(value or 0) if order == "desc" else (value or 0))
        return price if order and not grouped else (row[0], *price)
    rows.sort(key=sort_key)
    lines = ["### 各厂家新刀报价（系统按查询结果生成）", "",
             "| 型号 | 厂家 | 品牌 | 新刀报价（元） | 平均服役环数（完成服役数） | 每环报价（元/环） |",
             "| --- | --- | --- | --- | --- | --- |"]
    for _, item, quote in rows:
        average = item.get("avg_service_rings")
        service = f"{display(average) if average is not None else '—'}（{item.get('completed_service_count', 0)}）"
        cells = [item.get("tool_type_name") or "—", quote.get("manufacturer") or "—", quote.get("brand") or "—",
                 _money_text(quote.get("unit_price_yuan")), service,
                 _money_text(quote["price_per_ring_yuan"]) if quote.get("price_per_ring_yuan") is not None else "—"]
        lines.append("| " + " | ".join(str(c).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ") for c in cells) + " |")
    return [*lines, "", "每环报价 = 新刀报价 ÷ 该型号已拆下刀具的平均服役环数；平均服役环数按型号统计，不是该厂家刀具的服役环数。没有服役样本的型号不算每环报价。"]


def _ratio_text(items):
    return "、".join(f"{row.get('label', row.get('code'))} {percent(row.get('pct'))}" for row in items or []) or "暂无"


def _render_refresh_report(kind, data, table, scope):
    titles = {"stratum_area": "地层面积组成", "opening_stratum": "开仓位置和区间地层",
              "tool_inspections": "现场检查情况", "old_tool_repairs": "旧刀返修记录",
              "tool_lifecycle": "单把刀追溯", "manufacturer_service": "厂家服役表现和供货登记",
              "tool_cost_catalog": "新刀和维修报价", "registered_amounts": "项目登记金额",
              "data_catalog": "可查数据和覆盖范围"}
    scope = {**(scope or {}), **(data.get("scope") or {})}
    question = scope.get("question", "")
    sections = scope.get('sections', requested_sections(kind, question))
    report = Report(titles[kind], data, table, scope)
    parts = [scope_text(scope)]
    if scope.get("rings"):
        parts[0] = "第 " + "、".join(map(str, scope["rings"])) + " 环"
    elif scope.get("ring_no") is not None:
        parts[0] = f"第 {scope['ring_no']} 环开仓"
    elif scope.get("recent_openings"):
        parts[0] = f"最近 {scope['recent_openings']} 次开仓（环号从大到小）"
    if scope.get("tool_ids"):
        parts[0] = "刀具编号：" + "、".join(scope["tool_ids"])
    if scope.get("manufacturers"):
        parts.append("厂家：" + "、".join(scope["manufacturers"]))
    if scope.get("tool_model"):
        parts.append("型号：" + scope["tool_model"])
    for key, label in (("inspection_status", "厂家反馈状态"), ("disposition", "处置"), ("check_result", "检查结果")):
        if scope.get(key):
            parts.append(f"{label}：{_status_label(scope[key])}")
    if scope.get("opening_count") is not None:
        parts.append(f"匹配 {scope['opening_count']} 次开仓")
    bases = {"tool_inspections": "有效刀位的检查明细（含未检查）", "old_tool_repairs": "现场观测记录对应的旧刀",
             "manufacturer_service": "原安装厂家的确认服役段", "registered_amounts": "现场观测记录的登记金额",
             "tool_lifecycle": "安装、拆下身份和厂家确认记录", "tool_cost_catalog": "共用报价库",
             "data_catalog": "现场业务按项目，型号和报价为共用资料库"}
    parts.append(data.get("basis_label") or bases.get(kind, "开仓快照与现有地层表"))
    bounds = scope.get("data_ring_range") or [scope.get("ring_min"), scope.get("ring_max")]
    if len(bounds) == 2 and all(value is not None for value in bounds):
        parts.append("实际覆盖：" + range_text(bounds))
    report.lines[2:] = ["查询范围：" + "；".join(parts) + "。"]
    if data.get("error"):
        report.text(f"查询失败：{data['error']}")
        return report.finish("未取得完整数据，不作统计判断。")
    report.notes.extend([data.get("note"), data.get("source_note")])
    if kind == "stratum_area":
        report.text(f"查询 {display(data.get('ring_count_requested'))} 环，有可用面积数据 {display(data.get('ring_count_with_data'))} 环，缺少 {display(data.get('missing_ring_count'))} 环。")
        _refresh_table(report, "地层面积", ["地层类别", "平均面积占比", "出现的环数", "面积等效环数"], [
            [r.get('label'), percent(r.get('share_pct')), r.get('positive_ring_count'), r.get('area_equivalent_rings')]
            for r in data.get('classes') or []])
        _refresh_table(report, "逐环占比", ["环号", "地层面积占比"], [
            [r.get('ring_no'), _ratio_text(r.get('ratios'))] for r in data.get('per_ring') or []])
    elif kind == "opening_stratum":
        from .tools import STRATUM_TYPE_NAMES
        for row in data.get('openings') or []:
            report.text(f"### 第 {row.get('ring_no')} 环开仓\n\n上次开仓环号：{display(row.get('previous_opening_ring'))}；经过区间：{range_text(row.get('interval'))}。")
            snapshot = row.get('saved_snapshot') or {}
            saved = snapshot.get('stratum_info_between')
            saved_text = "、".join(f"{STRATUM_TYPE_NAMES.get(k, k)} {v}" for k, v in saved.items()) if isinstance(saved, dict) else display(saved)
            report.text(f"当时保存：区间地层 {saved_text or '暂无'}；工程条件 {str(display(snapshot.get('geological_conditions'))).rstrip('。')}。")
            current = row.get('current_ring') or {}
            report.text("现在重算的开仓位置：历史标签 " + ("、".join(r['label'] for r in current.get('legacy_labels') or []) or "暂无") + "。")
            report.text("纵断面六类面积：" + _ratio_text(current.get('longitudinal_area')) + "。")
            report.text("横断面岩性占比：" + _ratio_text(current.get('cross_section')) + "。")
            summary = row.get('interval_summary') or {}
            report.text("现在重算的区间标签：" + ("、".join(f"{STRATUM_TYPE_NAMES.get(k, k)} {v} 环" for k, v in (summary.get('legacy_label_ring_counts') or {}).items()) or "暂无") + "。")
            basis = 'cross_section' if any(word in question for word in ('横断面', '岩性')) else 'longitudinal_area'
            _refresh_table(report, "经过区间的平均面积组成", ["地层类别", "平均面积占比", "出现的环数", "面积等效环数"], [
                [r.get('label'), percent(r.get('share_pct')), r.get('positive_ring_count'), r.get('area_equivalent_rings')]
                for r in summary.get(basis) or []])
            if row.get('snapshot_differs_from_current'):
                report.text("当时保存的地层快照与现在重算的结果不一致，以上分别列出。")
    elif kind == "tool_inspections":
        attention, unchecked = data.get('attention_not_replaced') or {}, data.get('unchecked') or {}
        report.text(f"需关注但未更换：{display(attention.get('record_count'))} 条，涉及 {display(attention.get('position_count'))} 个刀位。")
        report.text(f"未检查：{display(unchecked.get('record_count'))} 条，涉及 {display(unchecked.get('position_count'))} 个刀位。")
        groups = [('未检查明细', unchecked)] if any(w in question for w in ('未检查', '没检查')) else [('需关注未更换明细', attention)]
        if any(w in question for w in ('完成', '检查完', '移动任务')):
            _refresh_table(report, "各次开仓检查完成情况", ["环号", "明细数", "已检查", "未检查", "已更换", "需关注未换", "移动任务状态"], [
                [r.get('ring_no'), r.get('position_count'), r.get('checked_count'), r.get('unchecked_count'), r.get('replaced_count'),
                 r.get('attention_not_replaced_count'),
                 '、'.join(_status_label(s) for s in r.get('task_status') or []) or '暂无'] for r in data.get('opening_completion') or []])
            report.text("移动任务：" + ('、'.join(f"{_status_label(k)} {v} 条" for k, v in (data.get('task_status_counts') or {}).items()) or '暂无') + "。")
        elif 'details' in sections:
            for title, group in groups:
                _refresh_table(report, title, ["环号", "刀位", "检查结果", "磨损状态"], [
                    [r.get('ring_no'), r.get('cutter_position_no'), _status_label(r.get('check_result')), r.get('wear_condition')]
                    for r in group.get('records') or []], group.get('record_count'))
    elif kind == "old_tool_repairs":
        report.notes = []
        if 'amount' in sections:
            report.notes.append('金额为登记值，不代表实际支出；已确认金额包含已归档，不含待反馈。')
        if 'scrap' in sections:
            report.notes.append('报废只计已确认及已归档；待反馈的报废标记仅为建议。')
        if 'status' in sections:
            report.notes.append('按旧刀返修记录统计，三种反馈状态分别计数。')
        if 'scrap' in sections:
            report.text(f"已报废：{display(data.get('scrapped_count'))} 把。")
            report.text(f"报废建议：{display(data.get('scrap_suggestion_count'))} 把，仍待厂家反馈。")
        counts = data.get('status_counts') or {}
        if 'status' in sections:
            report.text("返修状态：" + '；'.join(f"{label} {display(counts.get(key))} 条" for key, label in (
                ('PENDING_VENDOR_FEEDBACK', '待厂家反馈'), ('CONFIRMED', '已确认'), ('CLOSED', '已归档'))) + "。")
        amounts = data.get('registered_repair_amount') or {}
        if 'amount' in sections:
            report.text(f"已确认及已归档的登记维修金额：{_money_text(amounts.get('confirmed_yuan'))} 元。")
            if '已确认' not in question or '待反馈' in question:
                report.text(f"待反馈登记维修金额：{_money_text(amounts.get('pending_yuan'))} 元。")
        components = scope.get('components') or []
        reasons = [r for r in data.get('failure_reasons') or [] if not components or r.get('component') in components]
        if 'reasons' in sections:
            _refresh_table(report, "失效原因", ["部件", "原因", "记录数"], [[r.get('component'), r.get('label'), r.get('record_count')] for r in reasons])
            report.notes.append('一把刀可有多个原因，原因计数不等于刀数。')
        records = data.get('records') or []
        if 'details' in sections:
            if 'scrap' in sections:
                records = [r for r in records if r.get('disposition') == 'SCRAP']
            if '已确认' in question and '进度' not in question:
                records = [r for r in records if r.get('inspection_status') in {'CONFIRMED', 'CLOSED'}]
            _refresh_table(report, "返修明细", ["旧刀编号", "环号", "刀位", "厂家反馈状态", "处置", "登记维修金额（元）", "失效原因"], [
                [r.get('old_tool_number'), r.get('ring_no'), r.get('cutter_position_no'), _status_label(r.get('inspection_status')),
                 _status_label(r.get('disposition')), _money_text(r.get('repair_price_yuan')),
                 '、'.join(f"{f.get('component')}：{f.get('label')}" for f in r.get('failure_reasons') or []) or '暂无'] for r in records], scope.get('record_count'))
    elif kind == "tool_lifecycle":
        basis_labels = {'confirmed': '确认', 'suggested': '建议身份', 'inferred': '推断', 'in_service': '在役'}
        for row in data.get('results') or []:
            report.text(f"### {row.get('query')}\n\n刀具状态：{display((row.get('instance') or {}).get('status_label'))}。")
            segments = row.get('service_segments') or []
            _refresh_table(report, "安装与拆下", ["刀位", "安装环", "拆下环", "拆下依据", "服役环数"], [
                [s.get('cutter_position_no'), s.get('install_ring'), s.get('removal_ring'), basis_labels.get(s.get('removal_basis'), '暂无'),
                 s.get('service_rings') if s.get('removal_basis') == 'confirmed' else None] for s in segments])
            _refresh_table(report, "期间检查", ["环号", "检查结果", "磨损状态"], [
                [r.get('ring_no'), _status_label(r.get('check_result')), r.get('wear_condition')]
                for s in segments for r in s.get('inspections') or []])
            for segment in segments:
                repair = segment.get('repair')
                if repair:
                    report.text(f"第 {display(segment.get('removal_ring'))} 环拆下后的返修：{_status_label(repair.get('inspection_status'))}；处置 {_status_label(repair.get('disposition'))}；登记维修金额 {_money_text(repair.get('repair_price_yuan'))} 元。")
            report.text("缺失环节：" + ('；'.join(row.get('missing_steps') or []) or '无') + "。")
            if row.get('truncated'):
                report.notes.append(f"{row.get('query')} 只返回最近 20 段。")
    elif kind == "manufacturer_service":
        report.lines[0] = '## 厂家服役表现'
        report.data = {**data, 'warnings': [warning for warning in data.get('warnings') or []
                                           if 'unconfirmed' in sections and any(word in warning for word in ('在役', '待反馈', '缺确认身份'))]}
        report.notes = ['只比较原安装厂家的确认拆下服役段，异常率以已分类样本为分母；小样本不代表质量高低。']
        report.text(f"确认配对：{display((data.get('summary') or {}).get('confirmed_segment_count'))} 个。")
        items = data.get('service_by_install_manufacturer') or []
        insufficient = data.get('insufficient_samples') or []
        if 'service' in sections:
            _refresh_table(report, "按原安装厂家的已确认服役表现", ["原安装厂家", "确认样本数", "平均服役环数", "已分类异常率", "样本说明"], [
                [r.get('manufacturer'), r.get('confirmed_segment_count'), r.get('avg_service_rings'), percent(r.get('abnormal_rate_pct'), r.get('classified_count')),
                 '样本不足，不参与比较' if r in insufficient else '达到最少样本数'] for r in items + insufficient])
        if 'abnormal_types' in sections:
            types = sorted({key for r in items + insufficient for key in r.get('abnormal_types', {})})
            _refresh_table(report, "各厂家异常类型分布", ["原安装厂家", *types], [
                [r.get('manufacturer'), *[r.get('abnormal_types', {}).get(key, 0) for key in types]] for r in items + insufficient])
        if 'supply' in sections:
            _refresh_table(report, "本次新装的供货次数和登记金额", ["本次新装厂家", "供货次数", "登记金额（元）"], [
                [r.get('manufacturer'), r.get('install_count'), _money_text(r.get('registered_amount_yuan'))] for r in data.get('supply_by_new_manufacturer') or []])
        if 'unconfirmed' in sections:
            unconfirmed = data.get('unconfirmed') or {}
            report.text(f"未确认：待厂家反馈 {display(unconfirmed.get('pending_feedback_count'))} 条；缺确认身份或配对不完整 {display(unconfirmed.get('no_confirmed_identity_count'))} 条。")
            report.text(f"当前在役：{display(unconfirmed.get('in_service_count'))} 把。")
    elif kind == "tool_cost_catalog":
        report.text(f"匹配 {display(scope.get('model_count'))} 个型号、{display(scope.get('quote_count'))} 条报价。")
        price_types = [(code, prefix, label) for code, prefix, label in (
            ('NEW_TOOL', 'new_tool', '新刀报价区间（元）'), ('REPAIR', 'repair', '维修报价区间（元）'))
            if not scope.get('cost_type') or scope['cost_type'] == code]
        _refresh_table(report, "型号报价区间", ["型号", *[label for _, _, label in price_types]], [
            [r.get('tool_model'), *[f"{_money_text(r.get(prefix + '_price_min_yuan'))}–{_money_text(r.get(prefix + '_price_max_yuan'))}"
                                   if r.get(prefix + '_price_min_yuan') is not None else '暂无' for _, prefix, _ in price_types]]
            for r in data.get('by_model') or []])
        rows = [[r['tool_model'], r['manufacturer'], *[
            '、'.join(f"{p['brand'] or '未登记品牌'}：{_money_text(p['unit_price_yuan'])}" for p in r[key]) or '—'
            for key in ('new_tool_prices', 'repair_prices')]] for r in data.get('by_manufacturer') or []]
        report.text(f"厂家报价：显示 {len(rows)} 条型号 × 厂家记录，覆盖全部 {display(scope.get('quote_count'))} 条报价。")
        report.table('厂家报价', ['型号', '厂家', '新刀价（元）', '维修价（元）'], rows, limit=len(rows))
    elif kind == "registered_amounts":
        for key, label in (('new_install', '新装登记金额'), ('confirmed_repair', '已确认返修登记金额'), ('total', '登记合计'), ('pending_repair', '待反馈返修登记金额')):
            value = data.get('total_registered_cost_yuan') if key == 'total' else (data.get(key) or {}).get('amount_yuan')
            report.text(f"{label}：{_money_text(value)} 元" + ('（单列，不计入合计）。' if key == 'pending_repair' else '。'))
        group_by = scope.get('group_by', 'none')
        label = {'manufacturer': '厂家', 'tool_type': '刀型', 'opening': '开仓环号'}.get(group_by, '分组')
        _refresh_table(report, f"按{label}统计", [label, "新装登记金额（元）", "已确认返修（元）", "登记合计（元）", "待反馈（元）"], [
            [r.get('ring_no') if group_by == 'opening' else _status_label(r.get(group_by)),
             _money_text((r.get('new_install') or {}).get('amount_yuan')), _money_text((r.get('confirmed_repair') or {}).get('amount_yuan')),
             _money_text(r.get('total_registered_cost_yuan')), _money_text((r.get('pending_repair') or {}).get('amount_yuan'))] for r in data.get('groups') or []])
    elif kind == "data_catalog":
        coverage = data.get('data_coverage') or {}
        labels = {'openings': '开仓记录', 'tool_change_observations': '现场观测记录', 'tunneling': '掘进参数', 'stratum': '地层',
                  'cost_quotes': '报价', 'old_tool_repairs': '旧刀返修', 'mobile_tasks': '移动任务',
                  'opening_readings': '开仓刀盘读数', 'tunneling_revolutions': '掘进刀盘圈数'}
        rows = []
        for key, item in coverage.items():
            count = next((item[field] for field in ('count', 'observation_count', 'record_count', 'ring_count') if field in item), None)
            if key == 'cost_quotes':
                count = f"新刀 {item.get('new_tool_count')}；维修 {item.get('repair_count')}"
            elif key == 'opening_readings':
                count = f"两侧都有读数 {item['count']} / 开仓总数 {item['total']}"
            elif key == 'tunneling_revolutions':
                count = f"计数器圈数 {item['counter_ring_count']} 环；积分圈数 {item['integrated_ring_count']} 环"
            elif 'status_counts' in item:
                count = '；'.join(f"{_status_label(k)} {v}" for k, v in item['status_counts'].items())
            elif key == 'tool_change_observations':
                count = f"{item.get('observation_count')}（其中更换 {item.get('replacement_count')}）"
            bounds = [item.get('ring_min'), item.get('ring_max')]
            times = [item.get('time_min', item.get('open_time_min')), item.get('time_max', item.get('open_time_max'))]
            rows.append([labels.get(key, key), count, range_text(bounds) if all(v is not None for v in bounds) else '—',
                         ' 至 '.join(str(t).replace('T', ' ')[:16] for t in times) if all(times) else '—'])
        _refresh_table(report, "数据覆盖", ["数据", "记录数", "环号覆盖", "时间覆盖"], rows)
        if '编码' in question:
            for key, label in (('legacy_labels', '历史地层标签'), ('longitudinal_area', '纵断面六类面积'), ('cross_section', '横断面岩性')):
                _refresh_table(report, label, ["编码", "名称", "出现环数"], [
                    [r.get('code'), r.get('label'), r.get('ring_count', r.get('positive_ring_count'))] for r in (data.get('stratum_codes') or {}).get(key) or []])
        if '型号' in question or '刀型' in question:
            _refresh_table(report, "刀具型号", ["型号", "编码", "刀型"], [
                [r.get('name'), r.get('code'), _status_label(r.get('tool_type'))] for r in data.get('tool_models') or []])
        report.text("当前不能查询：" + '、'.join(data.get('not_available') or []) + "。")
    return report.finish()


def _status_label(value):
    return {'PENDING': '待检查', 'NOT_REPLACED': '未更换', 'NORMAL': '正常', 'ATTENTION': '需关注',
            'ABNORMAL_NOT_REPLACED': '异常未换', 'PENDING_VENDOR_FEEDBACK': '待厂家反馈', 'CONFIRMED': '已确认',
            'CLOSED': '已归档', 'SCRAP': '报废', 'REPAIRABLE': '可维修', 'DRAFT': '草稿',
            'UNASSIGNED': '未分配', 'ASSIGNED': '已分配', 'IN_PROGRESS': '进行中', 'COMPLETED': '已完成',
            'SAVED': '已保存', 'SUBMITTED': '已提交', 'DISC': '滚刀', 'SCRAPER': '刮刀', 'RIPPER': '撕裂刀'}.get(value, display(value))


def segment_label(segment):
    if segment.get("segment_index"):
        return f"环号 {display(segment.get('ring_range'))} 第 {display(segment.get('segment_index'))}/{display(segment.get('segment_count'))} 段"
    return display(segment.get("ring_range"))


def _report_coverage(report, data):
    coverage = data.get("coverage") or {}
    for key, label in (("tunneling", "掘进"), ("tool_change", "换刀"), ("stratum", "地层")):
        item = coverage.get(key) or {}
        bounds = [item.get('ring_min'), item.get('ring_max')]
        time_min = item.get('open_time_min') if key == 'tool_change' else item.get('time_min')
        time_max = item.get('open_time_max') if key == 'tool_change' else item.get('time_max')
        count = item.get('observation_count') if key == 'tool_change' else item.get('record_count', item.get('ring_count'))
        report.text(f"{label}数据覆盖：{range_text(bounds)}；时间 {display(time_min)} 至 {display(time_max)}；记录数 {display(count)}（全项目）。")
    if data.get("window_counts") is not None:
        counts = data['window_counts']
        report.text(f"分析窗口：{range_text(data.get('ring_range'))}；窗口内掘进 {display(counts.get('tunneling'))} 条、现场观测记录 {display(counts.get('tool_change'))} 条、地层 {display(counts.get('stratum'))} 条。")
        report.notes.append("覆盖范围按全项目统计，窗口内记录数另列；地层时间为登记时间。")
    report.text(f"可比环段 {display(data.get('comparable_segment_count'))} 个；缺掘进数据的环段 {display(data.get('segments_missing_tunneling'))}，缺现场观测的环段 {display(data.get('segments_missing_observation'))}。")
    tunneling_range = [(coverage.get("tunneling") or {}).get(key) for key in ("ring_min", "ring_max")]
    change_range = [(coverage.get("tool_change") or {}).get(key) for key in ("ring_min", "ring_max")]
    if None not in (*tunneling_range, *change_range) and (tunneling_range[1] < change_range[0] or change_range[1] < tunneling_range[0]):
        report.text("掘进数据和换刀数据的环号、年份都不重合，只分别列出。")
    report.notes.append("掘进数据和换刀数据按环段并列显示，不代表两者有关联或因果。")


def render_report(kind, data, table, scope=None, penetration_unit=PENETRATION_UNIT):
    if kind == 'group_service':
        label = {'DISC': '滚刀', 'SCRAPER': '刮刀'}.get((scope or {}).get('tool_type'), '刀具')
        report = Report(f'{label}服役环数', {**data, 'warnings': []}, table, scope)
        if data.get('error'):
            report.text(f"查询失败：{data['error']}")
            return report.finish()
        summary = data.get('service_summary') or {}
        report.text(f"已确认拆下 {display(summary.get('completed_service_count'))} 段，平均服役 {display(summary.get('avg_service_rings'))} 环（总环数 ÷ 段数）。")
        rows = data.get('service_by_model') or []
        report.table('各型号服役环数', ['型号', '段数', '平均服役环数'], [
            [r['tool_type_name'], r['completed_service_count'], r['avg_service_rings']] for r in rows], limit=len(rows))
        peaks = data.get('peak_segments') or []
        if peaks:
            report.text('更换最多的环段：' + '、'.join(f"{str(s['ring_range']).replace('-', '–')} 环 {s['replaced']} 次" for s in peaks) + '。')
        return report.finish('仅统计已确认拆下的服役段；更换次数集中不代表磨损原因。')
    if kind == 'tool_mileage':
        report = Report('刀具里程', data, table, scope)
        if data.get('error'):
            report.text(f"查询失败：{data['error']}")
            return report.finish()
        def spread(value):
            if not value:
                return '—'
            if 'median' in value:
                return f"中位 {value['median']:.1f}（{value['q1']:.1f}–{value['q3']:.1f}）"
            return '、'.join(display(v) for v in value['values'])
        position = data.get('position')
        excluded = position.get('excluded') or [] if position else data.get('excluded') or []
        # 问单个刀位时只答这个刀位，全项目分带表和未计入数不附上
        if not position:
            rows = []
            for group in data.get('groups') or []:
                for band in group['bands']:
                    for cell in band['cells']:
                        rows.append([f"{group['label']} {band['radius_min']}–{band['radius_max']} mm", cell['manufacturer'],
                                     cell['removed_count'], spread(cell['life_km']), f"{cell['abnormal_count']} / {cell['classified_count']}",
                                     spread(cell['wear_per_100km']), cell['cost_per_km'] if cell['cost_per_km'] is not None else '—',
                                     f"{cell['in_service_count']} / {spread(cell['in_service_km'])}"])
            report.table('按轨迹分带和厂家统计', ['轨迹分带', '厂家', '已拆段', '至更换里程（km）', '非正常 / 已分类',
                         '每百公里磨损（mm）', '每公里成本（元/km）', '在役（把 / 已走 km）'], rows, limit=len(rows))
        else:
            sources = {'reading': '开仓读数', 'counter': '掘进计数器', 'integrated': '掘进积分推算', 'reference': '参考值估算'}
            report.text(f"### 刀位 {position['cutter_position_no']}（轨迹半径 {display(position.get('radius_mm'))} mm）")
            report.lines.append('')
            report.lines.extend(table(['安装环', '拆除环', '服役环数', '里程（km）', '圈数来源', '厂家'], [
                [r['installation_ring_no'], r['ring_no'], r['service_rings'], r['km'],
                 '、'.join(label for key, label in sources.items() if r['revolution_sources'].get(key)), r['manufacturer']]
                for r in position['segments']]))
            report.text(f"累计已核实里程：{display(position.get('covered_km'))} km（含在役已走里程）。")
        if excluded:
            report.text(f"未计入里程 {sum(r['count'] for r in excluded)} 把：" + '、'.join(f"{r['reason']} {r['count']}" for r in excluded) + '。')
        return report.finish('里程 = 2π × 轨迹半径 × 服役期间刀盘总圈数，服役期间为安装环之后到拆除环。')
    if kind == 'opening':
        sections = (scope or {}).get('sections') or set()
        report = Report('开仓记录', data, table, scope)
        for line in opening_means(data):
            report.text(line)
        records = data.get('recent_records') or []
        if (scope or {}).get('sort_abnormal'):
            records = sorted(records, key=lambda r: (number(r.get('abnormal_rate')) is not None, number(r.get('abnormal_rate')) or 0), reverse=True)
            report.text('按已分类异常率从高到低排列；无分类数据时异常率为暂无。')
        fields = [('ring_no', '环号')]
        if 'interval' in sections:
            fields += [('last_ring_no', '上次开仓环号'), ('rings_between_openings', '间隔环数'), ('open_time', '开仓时间')]
        if 'duration' in sections:
            fields += [('opening_duration', '开仓时长（h）')]
        show_counts = bool(sections & {'counts', 'abnormal'})
        sources = {r.get('count_source') for r in records}
        mixed_sources = show_counts and len(sources) > 1
        if show_counts:
            fields += [('tool_change_total', '检查数'), ('tool_change_replaced', '更换数')]
        headers = [label for _, label in fields]
        if 'abnormal' in sections:
            headers += ['异常数 / 已分类数', '异常率']
        if 'counts' in sections:
            headers += ['更换较多的刀位']
        if mixed_sources:
            headers += ['数量来源']
        readings = any(r.get('revolutions_since_previous') is not None for r in records)
        if readings:
            headers += ['刀盘圈数（距上次读数）']
        rows = [[*[r.get(key) for key, _ in fields],
                 *([f"{display(r.get('abnormal_count'))} / {display(r.get('abnormal_rate_denominator'))}", r.get('abnormal_rate')] if 'abnormal' in sections else []),
                 *([opening_positions(r)] if 'counts' in sections else []),
                 *(['已确认汇总' if r.get('count_source') == 'confirmed_summary' else '现场明细（未确认）'] if mixed_sources else []),
                 *([r.get('revolutions_since_previous')] if readings else [])] for r in records]
        report.table('最近开仓间隔' if sections <= {'interval', 'details'} else '开仓统计', headers, rows, limit=len(rows))
        note = '间隔为本次与上次开仓相隔环数。'
        if show_counts:
            if mixed_sources:
                note = '检查、更换数按各仓的数量来源取值，见"数量来源"列；异常率以有效刀位已分类观测数为分母。'
            elif sources == {'confirmed_summary'}:
                note = '整仓检查、更换数采用确认汇总；异常率以有效刀位已分类观测数为分母。'
            else:
                note = '检查、更换数取现场明细（开仓汇总尚未确认）；异常率以有效刀位已分类观测数为分母。'
            # 同一条提示只写一次，涉及的环号并在前面
            rings_by_warning = {}
            for r in records:
                for warning in r.get('warnings') or []:
                    if any(word in warning for word in ('尚未确认', '人工汇总', '检查数或更换数')):
                        rings_by_warning.setdefault(warning, []).append(display(r.get('ring_no')))
            report.notes.extend(f"环号 {'、'.join(rings)}：{warning}" for warning, rings in rings_by_warning.items())
        return report.finish(note)
    if kind in {"stratum_area", "opening_stratum", "tool_inspections", "old_tool_repairs", "tool_lifecycle",
                "manufacturer_service", "tool_cost_catalog", "registered_amounts", "data_catalog"}:
        return _render_refresh_report(kind, data, table, scope)
    titles = {
        "change_trend": "换刀分段统计", "manufacturer": "厂家记录对比",
        "stratum_distribution": "地层分布", "stratum_wear": "地层与换刀记录对照",
        "position_stratum": "刀位与地层记录对照", "tunneling_summary": "掘进参数概览",
        "tunneling_trend": "掘进参数分段统计", "tunneling_anomaly": "掘进参数分段均值偏高筛查",
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
    if kind.startswith("tunneling_") and kind != "tunneling_correlation" and data.get("total_records") == 0:
        if not data.get("message"):
            report.text("未找到符合条件的掘进动态记录。")
        return report.finish("没有可分析样本，不能将缺失数据解释为参数正常、无异常或工况平稳。")
    if kind == "change_trend":
        segments = data.get("segments") or []
        valid = [s for s in segments if (number(s.get("total")) or 0) > 0 and number(s.get("replacement_rate")) is not None]
        report.text(f"按 **{display(data.get('interval'))} 环/段** 展示，共 {len(segments)} 段，其中 {len(valid)} 段有可计算更换率的观测记录。")
        if len(valid) >= 2 and data.get("trend") != "数据不足":
            first, last = valid[0], valid[-1]
            report.text(f"首个有效段（{segment_label(first)}）更换率 {percent(first.get('replacement_rate'))}，末个有效段（{segment_label(last)}）为 {percent(last.get('replacement_rate'))}。")
        else:
            report.text("有效分段不足 2 个，无法比较首尾变化。")
        report.table("分段明细", ["环段", "现场观测记录数", "更换次数", "更换率", "已分类异常率", "正常数", "异常数", "未分类数"], [
            [segment_label(s), s.get("total"), s.get("replaced"), percent(s.get("replacement_rate"), s.get("total")), percent(s.get("abnormal_rate")), s.get("normal_count"), s.get("abnormal_count"), s.get("unknown_count")] for s in segments
        ])
        if data.get("first_last_change_pct_points") is not None and data.get("note") and data.get("trend") != "数据不足":
            report.text(data.get("note"))
        if any(s.get("abnormal_rate") is None for s in segments):
            report.notes.append("已分类异常率为暂无的分段：工具未提供该字段或该段没有已分类观测记录。")
        return report.finish("更换率 = 更换记录数 ÷ 该段观测记录数；不是每百环换刀频率。", "已分类异常率 = 异常观测数 ÷（正常观测数 + 异常观测数），未分类不计入分母。", "首尾比率比较不构成统计趋势检验，不能据此判断整个过程平稳或持续升降。", "空段没有观测，不能将工具返回的 0% 解释为未发生更换；尾段裁剪到查询范围内的实际数据末环。")
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
        has_replacements = any(item.get("replacement_count") is not None for item in items)
        headers = ["刀位", "地层标签关联次数", "各地层关联次数"] + (["实际更换次数"] if has_replacements else [])
        report.table("刀位与地层", headers, [
            [item.get("position"), item.get("total"), "、".join(f"{name} {display(count)}次" for name, count in (item.get("by_stratum") or {}).items()) or None] + ([item.get("replacement_count")] if has_replacements else []) for item in items
        ], limit=max(1, len(items)))
        return report.finish("同一更换记录对应多个地层标签时会重复计数，合计不一定等于该刀位实际更换次数。", "关联次数受观测量影响，不能据此认定刀位受地层影响更大或推断因果。")
    if kind in {"tunneling_summary", "tunneling_anomaly"}:
        metrics = data.get("metrics") or {}
        report.text(f"匹配 **{display(data.get('total_records'))}** 条掘进动态记录。")
        fields = [("thrust", "总推力", "kN"), ("torque", "刀盘扭矩", "kNm"), ("cutterhead_speed", "刀盘转速", "r/min"), ("penetration", "贯入度", penetration_unit), ("advance_speed", "推进速度", "mm/min")]
        if data.get('counter_ring_count') is not None:
            report.text(f"有计数器圈数 {data['counter_ring_count']} 环，有积分圈数 {data['integrated_ring_count']} 环。")
        report.table("参数统计", ["参数", "单位", "平均值", "最小值", "最大值"], [[label, unit, (metrics.get(key) or {}).get("avg"), (metrics.get(key) or {}).get("min"), (metrics.get(key) or {}).get("max")] for key, label, unit in fields])
        if kind == "tunneling_anomaly":
            anomalies = data.get("anomaly_fields") or []
            eligible = [key for key in ("thrust", "torque", "penetration") if number((metrics.get(key) or {}).get("avg")) not in (None, 0) and number((metrics.get(key) or {}).get("max")) is not None]
            report.text(f"已有规则标记 **{len(anomalies)}** 项分段均值偏高指标。" if anomalies else "本次未标记分段均值偏高指标；不等同于全部参数正常。")
            if len(eligible) < 3:
                report.notes.append("部分指标缺少有效均值/最大值，或均值为 0，无法完成峰值倍数比较。")
            names = {key: (label, unit) for key, label, unit in fields}
            report.table("分段均值偏高筛查", ["参数", "单位", "平均值", "最大值"], [[names.get(a.get("field"), (a.get("field"), "未标注"))[0], names.get(a.get("field"), ("", "未标注"))[1], a.get("avg"), a.get("max")] for a in anomalies])
            records = data.get("anomaly_records") or []
            report.table("命中的分段记录", ["环号", "段号", "开始时间", "结束时间", "参数", "数值", "平均值", "均值倍数"], [
                [r.get("ring_no"), r.get("segment_index"), r.get("start_time"), r.get("end_time"), names.get(r.get("metric"), (r.get("metric"), ""))[0], r.get("value"), r.get("average"), r.get("ratio")] for r in records
            ], limit=max(1, len(records)))
            report.notes.append(f"按分段均值与总体均值的倍数筛查，阈值 {display(data.get('threshold_k'))} 倍，不是故障诊断。")
            if not records:
                report.notes.append("命中记录的环号、段号、时间和数值暂无：工具未提供命中记录或本次没有命中。")
        recent = data.get("recent_records") or []
        report.table("最近记录", ["环号", "记录时间", "推力（kN）", "扭矩（kNm）", "转速（r/min）", f"贯入度（{penetration_unit}）"], [[r.get("ring_no"), r.get("record_time"), r.get("thrust"), r.get("torque"), r.get("cutterhead_speed"), r.get("penetration")] for r in recent], limit=max(1, len(recent)), total=data.get("total_records"))
        return report.finish("各指标按非空值计算；总记录数不等于每项指标的有效样本数。暂无与实测 0 分别展示。", "未提供时序与地层控制分析，不根据均值或最大值直接推断地层、操作原因或设备故障。")
    if kind in {"tunneling_trend", "tunneling_correlation"}:
        segments = data.get("segments") or []
        time_mode = any(s.get("segment_index") for s in segments)
        report.text(f"匹配 **{display(data.get('total_records'))}** 条掘进记录，共 {len(segments)} 段；" + ("按单环内时间顺序分段统计。" if time_mode else f"按 {display(data.get('interval'))} 环分段。"))
        if not data.get("ring_range") and segments:
            report.text(f"分段覆盖：{segment_label(segments[0])} 至 {segment_label(segments[-1])}；分段边界不一定是实际采样首末环。")
        valid = [s for s in segments if number(s.get("avg_penetration")) is not None]
        comparable = number(data.get("comparable_segment_count"))
        if kind == "tunneling_correlation":
            _report_coverage(report, data)
        if len(valid) < 2 or data.get("trend") == "数据不足":
            report.text("贯入度有效分段不足 2 个，无法比较首尾变化。")
        elif kind != "tunneling_correlation" or (comparable is not None and comparable >= 2):
            report.text(f"贯入度首个有效段均值 {display(valid[0].get('avg_penetration'), penetration_unit)}，末个有效段均值 {display(valid[-1].get('avg_penetration'), penetration_unit)}；仅作首尾描述，不构成统计趋势结论。")
        report.table("掘进分段明细", ["环段", "采样点数" if time_mode else "记录数", "平均推力（kN）", "平均扭矩（kNm）", "平均转速（r/min）", f"平均贯入度（{penetration_unit}）", "起止时间"], [
            [segment_label(s), s.get("count", s.get("tunneling_count")), s.get("avg_thrust"), s.get("avg_torque"), s.get("avg_cutterhead_speed"), s.get("avg_penetration"), f"{display(s.get('start_time'))} 至 {display(s.get('end_time'))}" if s.get("start_time") or s.get("end_time") else None] for s in segments
        ])
        if time_mode:
            report.notes.append("单环时间分段的采样点数来自汇总记录的点数字段；字段缺失或为 0 时工具回退为 1，不能视为已验证的原始采样点总数。分段均值来自对应汇总记录，与数据库记录条数分别展示。")
        if kind == "tunneling_correlation":
            if comparable is None or comparable < 2:
                report.text("可比环段不足 2 个或未提供，不作掘进和换刀的对照结论。")
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
        report.table("型号服役表现", ["排名", "型号", "刀型", "安装数", "完成服役数", "在役数", "平均服役（环）", "最短/最长（环）", "未确认拆下数"], [[i.get("rank"), i.get("tool_type_name"), i.get("tool_parent_type"), i.get("installed_count"), i.get("completed_service_count"), i.get("in_service_count"), i.get("avg_service_rings"), f"{display(i.get('min_service_rings'))} / {display(i.get('max_service_rings'))}", i.get("unconfirmed_removed_count")] for i in items], limit=max(1, len(items)), total=data.get("ranked_count"))
        prices = []
        for item in items:
            low, high = item.get("new_tool_price_min_yuan"), item.get("new_tool_price_max_yuan")
            price = "暂无新刀报价" if low is None else display(low) if high is None or low == high else f"{display(low)}–{display(high)}"
            prices.append([item.get("tool_type_name"), price, item.get("price_basis")])
        report.table("价格参考", ["型号", "新刀报价区间（元）", "报价依据"], prices, limit=max(1, len(prices)))
        if wants_manufacturer_prices((scope or {}).get("question", "")):
            report.lines.extend(["", *manufacturer_price_table(scope.get("manufacturer_price_recommendations", items + insufficient), scope.get("manufacturer_price_order"),
                                                               grouped=bool(GROUPED_SORT.search(scope.get("question", ""))))])
        report.table("样本不足的返回型号", ["型号", "安装数", "完成服役数"], [[i.get("tool_type_name"), i.get("installed_count"), i.get("completed_service_count")] for i in insufficient], limit=max(1, len(insufficient)))
        if not items:
            report.text("暂无满足排名条件的型号；不据此指定优先采购型号。")
        return report.finish("平均服役环数只用厂家已确认的拆下记录；报价是各厂家的新刀报价区间，不代表某一家。", "服役环数按安装与拆卸依据计算；未拆下刀具不参与已完成服役平均值，该均值不代表全部刀具的真实寿命或剩余寿命。", "新刀报价区间未提供时不使用旧单价替代，暂无新刀报价不代表报价为 0。", "样本不足型号可能已被查询限制截取，不代表全量清单。", "型号排序未控制地层和工况差异，不能直接替代备刀数量计划。")
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


def render_abnormal_cause(change, stratum, tunneling, opening, params, table, penetration_unit=PENETRATION_UNIT):
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
    report.table("掘进与换刀分段", ["环段", "掘进记录数", "平均扭矩（kNm）", f"平均贯入度（{penetration_unit}）", "更换次数", "异常磨损次数"], [[s.get("ring_range"), s.get("tunneling_count"), s.get("avg_torque"), s.get("avg_penetration"), s.get("replacement_count"), s.get("abnormal_wear_count")] for s in tunneling.get("segments") or []])
    _report_coverage(report, tunneling)
    records = opening.get("recent_records") or []
    report.table("整仓与现场明细核对", ["开仓环号", "整仓更换数", "数量来源", "现场明细数", "已分类异常率", "更换较多的刀位"], [[r.get("ring_no"), r.get("tool_change_replaced"), "已确认汇总" if r.get("count_source") == "confirmed_summary" else "现场明细（未确认）", r.get("detail_record_count"), r.get("abnormal_rate"), opening_positions(r)] for r in records])
    for name, source in [("换刀", change), ("地层", stratum), ("掘进", tunneling), ("开仓", opening)]:
        if source.get("error"):
            report.notes.append(f"{name}查询失败：{source['error']}；该来源未取得有效结果，不能解读为无记录。")
        report.notes.extend(f"{name}：{warning}" for warning in source.get("warnings") or [])
        if source.get("message"):
            report.notes.append(f"{name}：{source['message']}")
    for record in records:
        report.notes.extend(f"开仓环号 {display(record.get('ring_no'))}：{warning}" for warning in record.get("warnings") or [])
    return report.finish("更换率按观测记录计算；异常率按已分类磨损记录计算，二者分母不同。空值不按 0 处理。", "地层标签可重叠，关联计数不能跨地层直接求和；开仓整仓汇总与现场明细分别核对。", "上述结果没有相关性检验、因果识别或工况控制，不能由高频刀位、地层标签或峰值重合直接断言安装异常、硬岩冲击或掘进参数导致磨损。")
