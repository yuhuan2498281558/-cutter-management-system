"""聚合实验 JSONL，产出论文可用的统计结果。

替代 generate_ai_benchmark_report（那个脚本的"结论"章节是与数据无关的硬编码文本，
且 pivot 用 aggfunc="first" 会静默丢弃重复运行的数据）。本命令：
  * 只做统计，不写任何预设结论；
  * 每题多次重复全部纳入，正确率给 Wilson 95% 置信区间；
  * 两组对照用 McNemar 精确检验（配对二值，同题同轮次），报 p 值；
  * 延迟报 P50/P95 而不是被冷启动污染的 min/max。

用法：
    python manage.py analyze_experiment --input experiment_r1_hybrid.jsonl experiment_r1_agent.jsonl
    python manage.py analyze_experiment --input experiment_r1_*.jsonl --compare hybrid agent
    python manage.py analyze_experiment --input *.jsonl --output analysis_r1
"""

import glob
import json
import math
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


# ---------------------------------------------------------------------------
# 统计工具（纯函数，便于单测）
# ---------------------------------------------------------------------------
def wilson_ci(successes: int, total: int, z: float = 1.96):
    """二项比例的 Wilson 95% 置信区间。"""
    if total == 0:
        return None, None
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def mcnemar_exact(b: int, c: int) -> float:
    """McNemar 精确检验（双侧二项）。b/c 为两组不一致的两种方向计数。"""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) * (0.5 ** n)
    return min(1.0, 2 * tail)


def percentile(sorted_values, q: float):
    if not sorted_values:
        return None
    idx = (len(sorted_values) - 1) * q
    lo, hi = math.floor(idx), math.ceil(idx)
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (idx - lo)


def rate(part, whole):
    return (part / whole) if whole else None


def fmt_rate(value, ci=None):
    if value is None:
        return "-"
    text = f"{value * 100:.1f}%"
    if ci and ci[0] is not None:
        text += f" [{ci[0] * 100:.1f}, {ci[1] * 100:.1f}]"
    return text


# ---------------------------------------------------------------------------
class Command(BaseCommand):
    help = "聚合实验 JSONL，输出各组指标与配对显著性检验"

    def add_arguments(self, parser):
        parser.add_argument("--input", nargs="+", required=True, help="JSONL 文件或 glob")
        parser.add_argument("--include-warmup", action="store_true")
        parser.add_argument("--compare", nargs=2, metavar=("ARM_A", "ARM_B"),
                            help="对这两组做 McNemar 配对检验")
        parser.add_argument("--output", default="", help="输出前缀，写 <前缀>.md 与 <前缀>_per_case.csv")

    def handle(self, *args, **options):
        paths = []
        for pattern in options["input"]:
            hits = sorted(glob.glob(pattern))
            paths.extend(hits if hits else [pattern])
        records = []
        for path in paths:
            p = Path(path)
            if not p.exists():
                raise CommandError(f"文件不存在：{path}")
            for line in p.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
        if not options["include_warmup"]:
            records = [r for r in records if not r.get("is_warmup")]
        if not records:
            raise CommandError("没有可分析的记录（全部是 warmup？加 --include-warmup）")

        by_arm = defaultdict(list)
        for r in records:
            by_arm[r.get("arm") or "unknown"].append(r)

        lines = ["# 实验结果汇总", ""]
        lines.append(f"记录总数 {len(records)}（已剔除 warmup），实验组：{'、'.join(sorted(by_arm))}")
        lines.append("")

        # ---- 各组主指标 ----
        lines.append("## 各组主指标")
        lines.append("")
        header = ("| 组 | N | 数值完全正确 (Wilson 95%CI) | 幻觉数字率 | 路由正确 | 工具选择正确 "
                  "| 参数正确 | 指代继承 | P50延迟 | P95延迟 | tokens(入/出) |")
        lines.append(header)
        lines.append("|" + "---|" * 11)
        for arm in sorted(by_arm):
            rows = by_arm[arm]
            gt_rows = [r for r in rows if r.get("gt_available")]
            # exact_match=None 表示该题没有数值断言（如空结果边界题），不进分母
            scored_rows = [r for r in gt_rows if r.get("exact_match") is not None]
            em = sum(1 for r in scored_rows if r.get("exact_match"))
            hall = [r for r in gt_rows if r.get("has_hallucinated_number") is not None]
            hall_n = sum(1 for r in hall if r.get("has_hallucinated_number"))
            latencies = sorted(float(r.get("latency_ms") or 0) for r in rows)
            tokens_in = tokens_out = 0
            for r in rows:
                for counts in (r.get("usage") or {}).values():
                    tokens_in += counts.get("input_tokens", 0) or 0
                    tokens_out += counts.get("output_tokens", 0) or 0

            def _r(key):
                vals = [r.get(key) for r in rows if r.get(key) is not None]
                return fmt_rate(rate(sum(1 for v in vals if v), len(vals))) if vals else "-"

            lines.append(
                f"| {arm} | {len(rows)} | {fmt_rate(rate(em, len(scored_rows)), wilson_ci(em, len(scored_rows)))} "
                f"| {fmt_rate(rate(hall_n, len(hall))) if hall else '-'} "
                f"| {_r('route_ok')} | {_r('tool_selection_ok')} | {_r('tool_args_ok')} | {_r('carryover_ok')} "
                f"| {percentile(latencies, 0.5):.0f}ms | {percentile(latencies, 0.95):.0f}ms "
                f"| {tokens_in}/{tokens_out} |"
            )
        lines.append("")

        # ---- 稳定性：同题多次重复结果是否一致 ----
        lines.append("## 稳定性（同题重复间结果一致的比例）")
        lines.append("")
        for arm in sorted(by_arm):
            outcomes = defaultdict(set)
            for r in by_arm[arm]:
                if r.get("exact_match") is not None:
                    outcomes[r.get("case_id")].add(bool(r.get("exact_match")))
            consistent = sum(1 for v in outcomes.values() if len(v) == 1)
            lines.append(f"- {arm}: {consistent}/{len(outcomes)} 题在所有重复中结果一致"
                         if outcomes else f"- {arm}: 无可判定用例")
        lines.append("")

        # ---- text2sql 失败分层 ----
        t2s = by_arm.get("text2sql") or []
        if t2s:
            lines.append("## text2sql 失败分层")
            lines.append("")
            stages = defaultdict(int)
            for r in t2s:
                stage = r.get("failure_stage") or (
                    "semantic_error" if (r.get("gt_available") and r.get("exact_match") is False and r.get("success"))
                    else ("ok" if r.get("exact_match") else "other")
                )
                stages[stage] += 1
            for stage, count in sorted(stages.items(), key=lambda kv: -kv[1]):
                lines.append(f"- {stage}: {count}")
            lines.append("")

        # ---- 按类别 ----
        lines.append("## 按类别的数值正确率")
        lines.append("")
        categories = sorted({r.get("category") for r in records if r.get("category")})
        lines.append("| 类别 | " + " | ".join(sorted(by_arm)) + " |")
        lines.append("|" + "---|" * (len(by_arm) + 1))
        for cat in categories:
            cells = []
            for arm in sorted(by_arm):
                rows = [r for r in by_arm[arm]
                        if r.get("category") == cat and r.get("exact_match") is not None]
                cells.append(fmt_rate(rate(sum(1 for r in rows if r.get("exact_match")), len(rows))) if rows else "-")
            lines.append(f"| {cat} | " + " | ".join(cells) + " |")
        lines.append("")

        # ---- 鲁棒性：变体类型 vs 种子 ----
        robust = [r for r in records if r.get("variant_type")]
        if robust:
            lines.append("## 鲁棒性（按扰动类型的数值正确率）")
            lines.append("")
            for arm in sorted(by_arm):
                parts = []
                for vt in ("paraphrase", "colloquial", "typo", "noise"):
                    rows = [r for r in by_arm[arm] if r.get("variant_type") == vt and r.get("gt_available")]
                    if rows:
                        parts.append(f"{vt} {fmt_rate(rate(sum(1 for r in rows if r.get('exact_match')), len(rows)))}")
                if parts:
                    lines.append(f"- {arm}: " + "，".join(parts))
            lines.append("")

        # ---- McNemar ----
        compare = options.get("compare")
        if compare:
            arm_a, arm_b = compare
            pair_a = {(r.get("case_id"), r.get("rep")): bool(r.get("exact_match"))
                      for r in by_arm.get(arm_a, [])
                      if r.get("gt_available") and r.get("exact_match") is not None}
            pair_b = {(r.get("case_id"), r.get("rep")): bool(r.get("exact_match"))
                      for r in by_arm.get(arm_b, [])
                      if r.get("gt_available") and r.get("exact_match") is not None}
            common = sorted(set(pair_a) & set(pair_b))
            b = sum(1 for k in common if pair_a[k] and not pair_b[k])
            c = sum(1 for k in common if not pair_a[k] and pair_b[k])
            p_value = mcnemar_exact(b, c)
            lines.append(f"## McNemar 配对检验：{arm_a} vs {arm_b}")
            lines.append("")
            lines.append(f"- 配对样本 {len(common)}；仅 {arm_a} 对 {b} 次，仅 {arm_b} 对 {c} 次")
            lines.append(f"- 精确双侧 p = {p_value:.4g}")
            lines.append("")

        report = "\n".join(lines)
        self.stdout.write(report)

        prefix = options.get("output")
        if prefix:
            Path(f"{prefix}.md").write_text(report, encoding="utf-8")
            with Path(f"{prefix}_per_case.csv").open("w", encoding="utf-8-sig", newline="") as f:
                import csv
                writer = csv.writer(f)
                writer.writerow(["arm", "case_id", "rep", "category", "exact_match",
                                 "hallucinated", "route_stage", "rule_branch",
                                 "route_ok", "tool_selection_ok", "tool_args_ok",
                                 "carryover_ok", "latency_ms", "failure_stage"])
                for r in records:
                    writer.writerow([
                        r.get("arm"), r.get("case_id"), r.get("rep"), r.get("category"),
                        r.get("exact_match"), r.get("has_hallucinated_number"),
                        r.get("route_stage"), r.get("rule_branch"),
                        r.get("route_ok"), r.get("tool_selection_ok"), r.get("tool_args_ok"),
                        r.get("carryover_ok"), r.get("latency_ms"), r.get("failure_stage"),
                    ])
            self.stdout.write(self.style.SUCCESS(f"已写出 {prefix}.md 与 {prefix}_per_case.csv"))
