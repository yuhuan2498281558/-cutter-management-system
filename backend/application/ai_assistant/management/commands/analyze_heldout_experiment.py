"""同条件对照实验评分与统计：以题为分析单位，相邻两组做配对比较。"""

import json
import random
from collections import Counter, defaultdict
from math import comb
from pathlib import Path

from django.core.management.base import BaseCommand

from application.ai_assistant.management.commands.run_fixed_experiment import readonly

ORDER = ("sql_agent", "agent_bare", "agent", "hybrid_bare", "hybrid", "hybrid_ungated")
NAMES = {"sql_agent": "A0 强 Text-to-SQL", "agent_bare": "A1 领域工具", "agent": "A1+ 领域工具+程序表格与核对",
         "hybrid_bare": "A2 +双路径", "hybrid": "A3 完整系统",
         "hybrid_ungated": "A3 改进前路由"}
# 最后一对比较规则直答的覆盖检查：同一完整系统，改进前路由 → 改进后路由；第四轮只比较纯智能体路径上加不加程序表格与核对
COMPARISONS = (("sql_agent", "agent_bare"), ("agent_bare", "hybrid_bare"), ("hybrid_bare", "hybrid"), ("hybrid_ungated", "hybrid"),
               ("agent_bare", "agent"))


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * fraction
    low, high = int(position), min(int(position) + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def bootstrap(values, samples=10000, seed=20261108):
    """题级重抽样的均值 95% 区间；先排序，结果与题目的遍历顺序无关。"""
    values = sorted(values)
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(samples))
    return means[int(samples * 0.025)], means[int(samples * 0.975) - 1]


def mcnemar_exact(b, c):
    """双侧精确 McNemar：b、c 为两组结论不一致的题数。"""
    n = b + c
    if not n:
        return 1.0
    tail = sum(comb(n, k) for k in range(0, min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def holm(pvalues):
    ranked = sorted(range(len(pvalues)), key=pvalues.__getitem__)
    adjusted, running = [0.0] * len(pvalues), 0.0
    for rank, index in enumerate(ranked):
        running = max(running, min(1.0, (len(pvalues) - rank) * pvalues[index]))
        adjusted[index] = running
    return adjusted


def request_cost(response, prices):
    prompt, completion = response.get("prompt_tokens") or 0, response.get("completion_tokens") or 0
    hit = response.get("cache_hit_tokens") or 0
    return ((prompt - hit) * prices["miss"] + hit * prices["hit"] + completion * prices["output"]) / 1e6


class Command(BaseCommand):
    help = "给同条件对照实验评分并做题级统计，输出 JSON、Markdown 摘要和盲审抽样表"

    def add_arguments(self, parser):
        parser.add_argument("--input-dir", required=True)
        parser.add_argument("--offline-dir", help="模型不可用时的离线运行目录")
        parser.add_argument("--items", default="heldout_items.json")
        parser.add_argument("--price-miss", type=float, help="输入未命中缓存单价（元/百万 token）")
        parser.add_argument("--price-hit", type=float, help="输入命中缓存单价（元/百万 token）")
        parser.add_argument("--price-output", type=float, help="输出单价（元/百万 token）")
        parser.add_argument("--audit", type=int, default=0, help="随机抽取多少条回答写入盲审表")

    def handle(self, *args, **options):
        from application.ai_assistant.evaluation.heldout_suite import (collect_heldout_gold, load_items, score_turn,
                                                                       untraceable_numbers)
        from application.ai_assistant.llm_service import ToolAssistant
        from application.ai_assistant.views import _build_project_snapshot

        directory = Path(options["input_dir"]).resolve()
        meta = json.loads((directory / "run_meta.json").read_text(encoding="utf-8"))
        records = [json.loads(line) for line in (directory / "records.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        items = {item["id"]: item for item in load_items(options["items"])}
        case_ids = [case["id"] for case in meta["cases"]]
        with readonly():
            gold = collect_heldout_gold(meta["project_id"], [items[case_id] for case_id in case_ids])
            snapshot = _build_project_snapshot(meta["project_id"])
        # 两类组都收到同一条项目上下文消息，其中的数字也算可溯源
        context_text = ToolAssistant()._build_context_message({**snapshot, "project_id": meta["project_id"]}) or ""

        # 逐条评分
        for row in records:
            row["score"] = score_turn(row["answer"], gold[row["case_id"]][row["turn"]])
            sources = [row["question"], context_text] + [str(call.get("result", "")) for call in row.get("tool_calls") or []]
            row["numbers_found"], row["numbers_untraced"] = untraceable_numbers(row["answer"], sources)

        arms = [arm for arm in ORDER if arm in meta["arms"]]
        # 每题每次重复：多轮题各轮都对才算对
        runs = defaultdict(dict)
        for row in records:
            key = (row["arm"], row["case_id"], row["rep"])
            runs[key][row["turn"]] = row
        per_question = defaultdict(lambda: defaultdict(list))
        for (arm, case_id, rep), turns in runs.items():
            if len(turns) == len(gold[case_id]):
                per_question[arm][case_id].append(all(turn["score"]["correct"] for turn in turns.values()))

        summary = {}
        for arm in arms:
            rows = [row for row in records if row["arm"] == arm]
            questions = per_question[arm]
            shares = [sum(values) / len(values) for values in questions.values()]
            facts = [hit for row in rows for hit in row["score"]["fact_hits"]]
            found = sum(row["numbers_found"] for row in rows)
            untraced = sum(len(row["numbers_untraced"]) for row in rows)
            latencies = [row["latency_ms"] / 1000 for row in rows]
            responses = [response for row in rows for response in row.get("model_responses") or []]
            low, high = bootstrap(shares) if shares else (None, None)
            summary[arm] = {
                "name": NAMES[arm], "questions": len(questions), "records": len(rows),
                "accuracy": sum(shares) / len(shares) if shares else None, "accuracy_ci": [low, high],
                "majority_correct": sum(share > 0.5 for share in shares) / len(shares) if shares else None,
                "all_reps_correct": sum(share == 1 for share in shares) / len(shares) if shares else None,
                "fact_recall": sum(facts) / len(facts) if facts else None,
                "failure_rate": sum(not row["success"] for row in rows) / len(rows) if rows else None,
                "rule_share": sum(row.get("route_stage") == "rule" for row in rows) / len(rows) if rows else None,
                "rule_declined": sum(bool(row.get("rule_declined")) for row in rows),
                "untraceable_rate": untraced / found if found else None, "numbers_found": found, "numbers_untraced": untraced,
                "latency_p50_s": percentile(latencies, 0.5), "latency_p95_s": percentile(latencies, 0.95),
                "model_requests_per_turn": sum(row["model_requests"] for row in rows) / len(rows) if rows else None,
                "prompt_tokens": sum(r.get("prompt_tokens") or 0 for r in responses),
                "cache_hit_tokens": sum(r.get("cache_hit_tokens") or 0 for r in responses),
                "completion_tokens": sum(r.get("completion_tokens") or 0 for r in responses),
                "routes": dict(Counter(row.get("route_stage") or "失败" for row in rows)),
            }
            if all(options[key] is not None for key in ("price_miss", "price_hit", "price_output")):
                prices = {"miss": options["price_miss"], "hit": options["price_hit"], "output": options["price_output"]}
                summary[arm]["cost_cny"] = sum(request_cost(r, prices) for r in responses)

        # 相邻两组：每题多数正确做精确 McNemar，Holm 校正；题级正确比例差做配对 bootstrap
        comparisons = []
        for left, right in COMPARISONS:
            if left not in per_question or right not in per_question:
                continue
            shared = sorted(set(per_question[left]) & set(per_question[right]))
            major = {arm: {q: sum(v) / len(v) > 0.5 for q, v in per_question[arm].items()} for arm in (left, right)}
            b = sum(major[left][q] and not major[right][q] for q in shared)
            c = sum(major[right][q] and not major[left][q] for q in shared)
            diffs = [sum(per_question[right][q]) / len(per_question[right][q]) - sum(per_question[left][q]) / len(per_question[left][q])
                     for q in shared]
            low, high = bootstrap(diffs)
            comparisons.append({"from": left, "to": right, "questions": len(shared), "only_from_correct": b, "only_to_correct": c,
                                "p_exact": mcnemar_exact(b, c), "accuracy_gain": sum(diffs) / len(diffs), "gain_ci": [low, high]})
        for comparison, adjusted in zip(comparisons, holm([item["p_exact"] for item in comparisons])):
            comparison["p_holm"] = adjusted

        # 分组：完整系统多数重复走规则直答的题 vs 其余
        routes = defaultdict(Counter)
        for row in records:
            if row["arm"] == "hybrid" and row["turn"] == 0:
                routes[row["case_id"]][row["route_stage"]] += 1
        rule_questions = {case_id for case_id, counter in routes.items() if counter.most_common(1)[0][0] == "rule"}
        subgroups = {}
        for label, selected in (("规则覆盖", rule_questions), ("规则覆盖外", set(case_ids) - rule_questions)):
            subgroups[label] = {arm: (sum(sum(v) / len(v) for q, v in per_question[arm].items() if q in selected)
                                      / max(1, sum(q in selected for q in per_question[arm]))) for arm in arms}
            subgroups[label]["questions"] = len(selected)

        result = {"run_id": meta["run_id"], "suite": meta.get("suite"), "model": meta["configured_model"],
                  "repeat": meta["repeat"], "commit": meta["commit"], "patch_sha256": meta.get("patch_sha256"),
                  "data_fingerprint": meta["data_fingerprint_start"]["sha256"], "summary": summary,
                  "comparisons": comparisons, "subgroups": subgroups,
                  "per_question": {arm: {q: v for q, v in per_question[arm].items()} for arm in arms}}

        if options["offline_dir"]:
            offline = Path(options["offline_dir"]).resolve()
            offline_rows = [json.loads(line) for line in (offline / "records.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
            result["offline"] = {}
            for arm in sorted({row["arm"] for row in offline_rows}, key=ORDER.index):
                rows = [row for row in offline_rows if row["arm"] == arm]
                correct = [score_turn(row["answer"], gold[row["case_id"]][row["turn"]])["correct"] for row in rows]
                result["offline"][arm] = {"turns": len(rows), "answered": sum(bool(row["answer"].strip()) for row in rows),
                                          "correct": sum(correct)}

        (directory / "scored_records.jsonl").write_text(
            "\n".join(json.dumps({k: row[k] for k in ("arm", "case_id", "rep", "turn", "route_stage", "score",
                                                       "numbers_found", "numbers_untraced")}, ensure_ascii=False)
                      for row in records) + "\n", encoding="utf-8")
        (directory / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        (directory / "analysis.md").write_text(self.markdown(result, arms), encoding="utf-8")
        if options["audit"]:
            self.audit_sheet(directory, records, gold, options["audit"])
        self.stdout.write(self.markdown(result, arms))

    @staticmethod
    def markdown(result, arms):
        pct = lambda v: "—" if v is None else f"{v * 100:.1f}%"
        lines = [f"# 同条件对照实验结果（{result['suite']}，{result['model']}，每题重复 {result['repeat']} 次）", "",
                 "| 组 | 题数 | 题级正确率 [95% CI] | 多数正确 | 三次全对 | 事实召回 | 失败率 | 未溯源数字率 | 规则直答占比 | P50/P95 延迟(s) | 每轮模型请求 | 费用(元) |",
                 "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for arm in arms:
            s = result["summary"][arm]
            ci, cost = s["accuracy_ci"], f"{s['cost_cny']:.2f}" if "cost_cny" in s else "—"
            lines.append(f"| {s['name']} | {s['questions']} | {pct(s['accuracy'])} [{pct(ci[0])}, {pct(ci[1])}] | {pct(s['majority_correct'])} | "
                         f"{pct(s['all_reps_correct'])} | {pct(s['fact_recall'])} | {pct(s['failure_rate'])} | {pct(s['untraceable_rate'])} | "
                         f"{pct(s['rule_share'])} | "
                         f"{s['latency_p50_s']:.1f}/{s['latency_p95_s']:.1f} | {s['model_requests_per_turn']:.2f} | {cost} |")
        lines += ["", "| 比较 | 题数 | 仅前者对 | 仅后者对 | 正确率变化 [95% CI] | 精确 McNemar p | Holm 校正 p |", "|---|---|---|---|---|---|---|"]
        for c in result["comparisons"]:
            lines.append(f"| {NAMES[c['from']]} → {NAMES[c['to']]} | {c['questions']} | {c['only_from_correct']} | {c['only_to_correct']} | "
                         f"{c['accuracy_gain'] * 100:+.1f} [{c['gain_ci'][0] * 100:+.1f}, {c['gain_ci'][1] * 100:+.1f}] | "
                         f"{c['p_exact']:.4f} | {c['p_holm']:.4f} |")
        lines += ["", "| 题组 | 题数 | " + " | ".join(NAMES[a] for a in arms) + " |", "|---|---|" + "---|" * len(arms)]
        for label, values in result["subgroups"].items():
            lines.append(f"| {label} | {values['questions']} | " + " | ".join(pct(values[a]) for a in arms) + " |")
        if result.get("offline"):
            lines += ["", "模型不可用时：" + "；".join(f"{NAMES[a]} 答出 {v['answered']}/{v['turns']} 轮，答对 {v['correct']}"
                                                  for a, v in result["offline"].items())]
        return "\n".join(lines) + "\n"

    @staticmethod
    def audit_sheet(directory, records, gold, count):
        """隐去组别的盲审表：审核人对照真值判断回答是否正确，再与评分器结论比对。"""
        rng = random.Random(20261108)
        sample = rng.sample(records, min(count, len(records)))
        key, lines = [], ["# 盲审表（组别已隐去）", "", "每条请对照真值判断：回答是否给出了全部所问的数值和对象，且没有错误数值。填“对/错”。", ""]
        for number, row in enumerate(sample, 1):
            g = gold[row["case_id"]][row["turn"]]
            facts = "；".join(f"{'/'.join(f['anchors'])} {f['label']} = {round(f['value'], 2)}" for f in g["facts"]) or "（应说明库里没有该数据）"
            lines += [f"## 第 {number} 条（{row['case_id']} 第 {row['turn'] + 1} 轮）", "", f"问题：{row['question']}", "",
                      f"真值：{facts}" + (f"；须列出：{'、'.join(g['objects'])}" if g.get("objects") else "")
                      + (f"；须按此先后：{' > '.join('/'.join(group) for group in g['order'])}" if g.get("order") else ""), "",
                      "回答：", "", "> " + (row["answer"] or "（无回答）").replace("\n", "\n> "), "", "人工判断：", ""]
            key.append({"number": number, "arm": row["arm"], "case_id": row["case_id"], "rep": row["rep"], "turn": row["turn"],
                        "scorer_correct": row["score"]["correct"]})
        (directory / "audit_sheet.md").write_text("\n".join(lines), encoding="utf-8")
        (directory / "audit_key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
