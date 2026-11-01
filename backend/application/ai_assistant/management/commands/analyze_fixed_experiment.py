"""独立重评分与按题配对分析；判读标准固定于实验设计。"""

import csv
import json
import math
import random
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

from django.core.management.base import BaseCommand, CommandError

from .run_fixed_experiment import TOKEN_KEYS, case_turns, data_fingerprint, read_records, readonly

ISSUES = ("wrong_number", "missing_number", "format_only", "missing_objects", "bad_sort", "unrequested_section")


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * fraction
    low, high = math.floor(index), math.ceil(index)
    return values[low] + (values[high] - values[low]) * (index - low)


def paired_bootstrap(pairs, samples=10000, seed=20261028, ratio=False):
    # 每次抽取整题的配对汇总，重复回答不充当独立样本。
    if not pairs:
        return None
    rng = random.Random(seed)
    values = [a / b if ratio else a - b for a, b in pairs]
    statistic = median if ratio else mean
    draws = [statistic(rng.choices(values, k=len(values))) for _ in range(samples)]
    return {"estimate": statistic(values), "low": percentile(draws, .025), "high": percentile(draws, .975),
            "improved": sum(v < (1 if ratio else 0) for v in values),
            "equal": sum(v == (1 if ratio else 0) for v in values),
            "worse": sum(v > (1 if ratio else 0) for v in values), "n": len(pairs)}


def expected_contexts(gold, answer):
    def leaves(value):
        if isinstance(value, dict):
            for item in value.values():
                yield from leaves(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield from leaves(item)
        elif value is not None and not isinstance(value, bool):
            yield str(value)
    contexts = []
    for value in sorted(set(leaves(gold))):
        variants = {value}
        if re.fullmatch(r"-?\d+(\.\d+)?", value):
            variants.add(f"{float(value):,}".rstrip("0").rstrip(".") if "." in value else f"{int(value):,}")
        matches = sorted({(m.start(), m.end()) for text in variants for m in re.finditer(re.escape(text), answer)})
        contexts.append({"expected": value, "matches": [{"start": a, "end": b, "context": answer[max(0, a - 40):b + 40]} for a, b in matches]})
    return contexts


def aggregate(rows):
    counts = {kind: mean(any(i["kind"] == kind for i in r["score"]["issues"]) for r in rows) for kind in ISSUES}
    usage = {}
    for key in TOKEN_KEYS:
        values = [r["provider_usage"].get(key) if r["model_requests"] else 0 for r in rows]
        usage[key] = mean(values) if all(v is not None for v in values) else None
    return {"answers": len(rows), "repetitions": len({r["rep"] for r in rows}),
            "pass_rate": mean(r["passed"] for r in rows), "runtime_failures": sum(not r["success"] for r in rows),
            **counts, "number_error": mean(any(i["kind"] in {"wrong_number", "missing_number"} for i in r["score"]["issues"]) for r in rows),
            "check_issue": mean(any(i["kind"] in {"missing_objects", "bad_sort"} for i in r["score"]["issues"]) for r in rows),
            "latency_median_ms": median(r["latency_ms"] for r in rows), "latency_p95_ms": percentile([r["latency_ms"] for r in rows], .95),
            "requests_per_answer": mean(r["model_requests"] for r in rows),
            "requests_per_question": sum(r["model_requests"] for r in rows) / len({r["rep"] for r in rows}), **usage}


def fmt(value, percent=False):
    return "未知" if value is None else f"{value * 100:.2f}%" if percent else f"{value:.3f}"


def interval(result, percent=False, higher_better=False):
    if result is None:
        return "无法计算区间（没有完整配对题）"
    better, worse = (result["worse"], result["improved"]) if higher_better else (result["improved"], result["worse"])
    return (f"{fmt(result['estimate'], percent)}，95% CI [{fmt(result['low'], percent)}, {fmt(result['high'], percent)}]；"
            f"配对 {result['n']} 题，改善 / 持平 / 变差 = {better} / {result['equal']} / {worse}")


def hypotheses(cases, grouped, summaries, samples, seed, repeat=5):
    def compare(a, b, metric, subset=None, turn=None, ratio=False):
        pairs = []
        for case in cases.values():
            if subset and not subset(case):
                continue
            left, right = grouped.get((case["id"], a), []), grouped.get((case["id"], b), [])
            expected = {(rep, t) for rep in range(repeat) for t in range(len(case_turns(case))) if turn is None or t == turn}
            if turn is not None:
                left, right = [r for r in left if r["turn"] == turn], [r for r in right if r["turn"] == turn]
            if {(r["rep"], r["turn"]) for r in left} != expected or {(r["rep"], r["turn"]) for r in right} != expected:
                continue
            av, bv = aggregate(left)[metric], aggregate(right)[metric]
            if av is not None and bv is not None and (not ratio or bv > 0):
                pairs.append((av, bv))
        return paired_bootstrap(pairs, samples, seed, ratio)

    def judgement(results, condition):
        return "无法判断" if any(r is None for r in results) else "支持" if condition else "不支持"

    passed = compare("hybrid", "agent", "pass_rate")
    latency = compare("hybrid", "agent", "latency_median_ms", ratio=True)
    # H1 的速度阈值使用两组回答中位数，另报按题配对的中位延迟比。
    h, a = summaries.get("hybrid"), summaries.get("agent")
    overall_ratio = h["latency_median_ms"] / a["latency_median_ms"] if h and a and a["latency_median_ms"] > 0 else None
    h1 = judgement([passed, latency], overall_ratio is not None and overall_ratio <= .1 and passed is not None and passed["low"] >= -.05)
    lines = ["## H1 双路径", f"{h1}。回答中位延迟比 hybrid/agent = {fmt(overall_ratio)}，阈值 ≤ 0.1；",
             f"按题配对中位延迟比：{interval(latency)}。", f"通过率差 hybrid−agent：{interval(passed, True, True)}；下限要求 ≥ −5 个百分点。"]
    rule = lambda case: case["expected_path"] == "rule"
    formatted = compare("hybrid", "hybrid_no_template", "format_only", rule)
    h2 = judgement([formatted], formatted is not None and formatted["estimate"] < 0)
    lines += ["", "## H2 模板", f"{h2}。仅 rule 题；格式不可核对率差（模板−关模板）：{interval(formatted, True)}。"]
    for metric in ("wrong_number", "missing_number", "number_error"):
        result = compare("hybrid", "hybrid_no_template", metric, rule)
        lines.append(f"{metric} 发生率差：{interval(result, True)}；错误数值率不预设方向。")
    missing = compare("agent", "agent_no_check", "missing_objects")
    sorting = compare("agent", "agent_no_check", "bad_sort")
    combined = compare("agent", "agent_no_check", "check_issue")
    # 以漏列或排序的并集判读，两项分别列出；某项两组都没出现时不拖累判读
    h3 = judgement([combined], combined is not None and combined["estimate"] < 0)
    lines += ["", "## H3 回答核对", f"{h3}。发生率差均为开核对−关核对：",
              f"漏列 missing_objects：{interval(missing, True)}。", f"排序 bad_sort：{interval(sorting, True)}。",
              f"漏列或排序（并集）：{interval(combined, True)}。",
              f"开核对增加的每题模型调用次数：{interval(compare('agent', 'agent_no_check', 'requests_per_question'))}。"]
    chain = lambda case: bool(case.get("turns")) and len(case["turns"]) >= 2
    follow = compare("hybrid", "agent", "pass_rate", chain, turn=1)
    lines += ["", "## H4 追问", "无法判断（仅作描述性报告，不作方向性假设判断）。"]
    for arm in ("hybrid", "agent"):
        rates = [mean(r["passed"] for r in rows if r["turn"] == 1) for (cid, group), rows in grouped.items()
                 if group == arm and chain(cases[cid]) and any(r["turn"] == 1 for r in rows)]
        lines.append(f"{arm} 第二轮按题平均通过率 {fmt(mean(rates) if rates else None, True)}，覆盖 {len(rates)} 条追问链。")
    lines.append(f"第二轮通过率差 hybrid−agent：{interval(follow, True, True)}。")
    return lines


class Command(BaseCommand):
    help = "重评分 V2 固定实验，生成 analysis.md 和 per_case.csv"

    def add_arguments(self, parser):
        parser.add_argument("--input-dir", required=True)
        parser.add_argument("--output", default="", help="报告路径（.md）或输出目录；CSV 与报告同目录")
        parser.add_argument("--bootstrap", type=int, default=10000)
        parser.add_argument("--seed", type=int, default=20261028)

    def handle(self, *args, **options):
        from application.ai_assistant.evaluation.fixed_suite import collect_gold, load_fixed_cases, score_answer
        directory = Path(options["input_dir"]).resolve()
        meta = json.loads((directory / "run_meta.json").read_text(encoding="utf-8"))
        records = read_records(directory)
        if not records or options["bootstrap"] < 1:
            raise CommandError("需要原始记录和正数 bootstrap 次数")
        selected = {c["id"] for c in meta["cases"]}
        cases = {c["id"]: c for c in load_fixed_cases() if c["id"] in selected}
        fingerprint = data_fingerprint()
        with readonly():
            gold = collect_gold(meta["project_id"])
        grouped = defaultdict(list)
        seen = set()
        for row in records:
            key = (row["case_id"], row["arm"], row["rep"], row["turn"])
            if key in seen or row["run_id"] != meta["run_id"]:
                raise CommandError("原始记录包含重复样本或不同 run_id")
            seen.add(key)
            case = cases[row["case_id"]]
            row["score"] = score_answer(case, row["answer"], gold, turn=row["turn"])
            row["passed"] = bool(row["success"] and row["score"]["passed"])
            row["review_contexts"] = expected_contexts(gold[row["case_id"]], row["answer"]) if not row["passed"] else []
            grouped[(row["case_id"], row["arm"])].append(row)
        by_arm = defaultdict(list)
        for row in records:
            by_arm[row["arm"]].append(row)
        summaries = {arm: aggregate(rows) for arm, rows in by_arm.items()}
        ledger_path = directory / "model_requests.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        usage_totals = {key: sum(entry["response"][key] for entry in ledger if entry.get("response", {}).get(key) is not None) for key in TOKEN_KEYS}
        usage_known = {key: sum(entry.get("response", {}).get(key) is not None for entry in ledger) for key in TOKEN_KEYS}
        lines = ["# V2 固定题实验分析", ""]
        if fingerprint != meta["data_fingerprint_start"] or meta.get("data_fingerprint_end") != meta["data_fingerprint_start"]:
            lines += ["**数据已变化，评分可能不准**", ""]
        lines += ["## 运行概况", f"组：{', '.join(by_arm)}；题数 {len({r['case_id'] for r in records})}；记录数 {len(records)}；"
                  f"评分失败 {sum(not r['passed'] for r in records)}；运行失败 {sum(not r['success'] for r in records)}；模型 HTTP 请求 {len(ledger)}。",
                  f"总账已知 token（输入/输出/缓存）：{'/'.join(str(usage_totals[k]) for k in TOKEN_KEYS)}；"
                  f"有用量的请求数：{'/'.join(str(usage_known[k]) for k in TOKEN_KEYS)}/{len(ledger)}，缺失部分未知。",
                  f"commit={meta['commit']}；dirty={meta['dirty']}；配置模型={meta['configured_model']}；project_id={meta['project_id']}。",
                  f"统计单位为题；先汇总每题重复比例，再配对 bootstrap。假设判读仅纳入两组均有完整 {meta['repeat']} 次重复的题。",
                  f"bootstrap={options['bootstrap']}；seed={options['seed']}。多项比较未做校正，结论以区间和题数为准。",
                  "H2/H3 按配对发生率的方向判读，并列出区间；H4 仅描述。未报告 p 值。",
                  "请求数来自 httpx 实际发送边界（含重试与核对补全）；总账含预算中断但未完成回答的请求。",
                  "token 与实际模型来自 ContextUsage.record_response 的供应商元数据；缺失记 null，不用配置模型冒充实际模型。",
                  "每条请求与 token 均值针对已完成回答；总账另含中断的开销。token 均值仅在全部回答有用量时报告；0 请求回答的 token 为 0。",
                  "路由：hybrid=默认规则优先，agent=跳过规则直答；所有消融默认 0，仅对应实验组置 1；规则润色固定 0，记忆为内存 legacy。", ""]
        models = {arm: sorted({entry["response"]["model"] for entry in ledger if entry.get("arm") == arm
                              and entry.get("response", {}).get("model")}) for arm in meta["arms"]}
        lines.append(f"各组供应商实际模型：{json.dumps(models, ensure_ascii=False)}。")
        if len({tuple(v) for v in models.values() if v}) > 1:
            lines.append("**不同组的实际模型名不一致，存在模型混淆因素。**")
        if any(not entry.get("response", {}).get("model") for entry in ledger):
            lines.append("部分模型响应缺少实际模型名，无法完整核验同一模型。")
        lines += ["", "## 各组指标", "", "| 组 | 题/回答 | 回答通过率 | 按题平均通过率 | wrong_number | missing_number | format_only | missing_objects | bad_sort | unrequested_section | 延迟 P50/P95 ms | 请求/条 | 输入/输出/缓存 token/条 | 总输入/输出 token |",
                  "|" + "---|" * 14]
        for arm, summary in summaries.items():
            units = [aggregate(rows) for (cid, group), rows in grouped.items() if group == arm]
            tokens = [summary[k] * len(by_arm[arm]) if summary[k] is not None else None for k in TOKEN_KEYS[:2]]
            lines.append("| " + " | ".join([arm, f"{len(units)}/{summary['answers']}", fmt(summary["pass_rate"], True),
                fmt(mean(u["pass_rate"] for u in units), True), *[fmt(summary[k], True) for k in ISSUES],
                f"{fmt(summary['latency_median_ms'])}/{fmt(summary['latency_p95_ms'])}", fmt(summary["requests_per_answer"]),
                "/".join(fmt(summary[k]) for k in TOKEN_KEYS), "/".join(map(fmt, tokens))]) + " |")
        lines += ["", "问题率为出现该类问题的回答比例，同一回答可计入多个问题。"]
        lines += hypotheses(cases, grouped, summaries, options["bootstrap"], options["seed"], meta["repeat"])
        lines += ["", "## 失败回答复核清单", "期望值的每处命中均保留前后各 40 字及字符位置；matches=[] 表示未找到。CSV 保留全部失败明细。"]
        for arm, rows in by_arm.items():
            failures = [r for r in rows if not r["passed"]]
            lines.append(f"\n### {arm}（失败 {len(failures)} 条）")
            for row in failures[:30]:
                evidence = {k: row[k] for k in ("question", "error", "review_contexts")}
                evidence["issues"] = row["score"]["issues"]
                lines.append(f"- {row['case_id']} rep={row['rep']} turn={row['turn']}：{json.dumps(evidence, ensure_ascii=False)}")
            if len(failures) > 30:
                lines.append(f"其余 {len(failures) - 30} 条见 per_case.csv。")
        output = Path(options["output"]).resolve() if options["output"] else directory
        report = output if output.suffix == ".md" else output / "analysis.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        csv_rows = []
        for (cid, arm), rows in sorted(grouped.items()):
            csv_rows.append({"case_id": cid, "arm": arm, "kind": cases[cid]["kind"], **aggregate(rows), "complete": len(rows) == meta["repeat"] * len(case_turns(cases[cid])),
                             "repetition_pass_rates": json.dumps({rep: mean(r["passed"] for r in rows if r["rep"] == rep) for rep in sorted({r["rep"] for r in rows})}),
                             "failures": json.dumps([{k: r[k] for k in ("rep", "turn", "question", "answer", "error", "score", "review_contexts")} for r in rows if not r["passed"]], ensure_ascii=False)})
        with (report.parent / "per_case.csv").open("w", encoding="utf-8-sig", newline="") as sink:
            writer = csv.DictWriter(sink, fieldnames=list(csv_rows[0]))
            writer.writeheader()
            writer.writerows(csv_rows)
        self.stdout.write(f"分析完成：{report}；{report.parent / 'per_case.csv'}")
