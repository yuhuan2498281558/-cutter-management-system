import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Generate benchmark tables, charts, and a paper-ready experiment report."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hybrid",
            default="benchmark_hybrid_deepseek.json",
            help="Hybrid benchmark JSON file.",
        )
        parser.add_argument(
            "--agent",
            default="benchmark_agent_deepseek.json",
            help="Agent benchmark JSON file.",
        )
        parser.add_argument(
            "--output-dir",
            default="ai_assistant_benchmark_report",
            help="Directory for generated report files.",
        )

    def handle(self, *args, **options):
        import pandas as pd
        import matplotlib.pyplot as plt

        hybrid_path = Path(options["hybrid"])
        agent_path = Path(options["agent"])
        output_dir = Path(options["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)

        hybrid = self._load_json(hybrid_path)
        agent = self._load_json(agent_path)

        rows = []
        rows.extend(self._flatten(hybrid, "Hybrid"))
        rows.extend(self._flatten(agent, "Agent"))
        df = pd.DataFrame(rows)

        summary_df = self._summary(df)
        question_df = self._question_compare(df)

        summary_csv = output_dir / "benchmark_summary.csv"
        detail_csv = output_dir / "benchmark_detail.csv"
        question_csv = output_dir / "benchmark_question_compare.csv"
        summary_df.to_csv(summary_csv, index=False, encoding="utf-8-sig")
        df.to_csv(detail_csv, index=False, encoding="utf-8-sig")
        question_df.to_csv(question_csv, index=False, encoding="utf-8-sig")

        self._setup_matplotlib(plt)
        self._plot_summary(plt, summary_df, output_dir / "latency_summary.png")
        self._plot_question_latency(plt, question_df, output_dir / "latency_by_question.png")
        self._plot_answer_chars(plt, question_df, output_dir / "answer_length_by_question.png")

        report_path = output_dir / "experiment_report.md"
        report_path.write_text(
            self._build_markdown(summary_df, question_df, hybrid, agent),
            encoding="utf-8",
        )

        self.stdout.write(self.style.SUCCESS(f"Generated report directory: {output_dir}"))
        for path in [summary_csv, detail_csv, question_csv, report_path]:
            self.stdout.write(str(path))

    def _load_json(self, path: Path) -> dict:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _flatten(self, payload: dict, mode_label: str) -> list[dict]:
        summary = payload["summary"]
        rows = []
        for index, item in enumerate(payload["results"], start=1):
            rows.append({
                "index": index,
                "mode": mode_label,
                "provider": summary["provider"],
                "model": summary["model"],
                "route_mode": summary["route_mode"],
                "question": item["question"],
                "success": bool(item["success"]),
                "type": item.get("type", ""),
                "elapsed_ms": float(item["elapsed_ms"]),
                "elapsed_s": round(float(item["elapsed_ms"]) / 1000, 3),
                "answer_chars": int(item.get("answer_chars", 0)),
            })
        return rows

    def _summary(self, df):
        grouped = df.groupby("mode", sort=False)
        summary = grouped.agg(
            provider=("provider", "first"),
            model=("model", "first"),
            route_mode=("route_mode", "first"),
            question_count=("question", "count"),
            success_count=("success", "sum"),
            avg_latency_ms=("elapsed_ms", "mean"),
            median_latency_ms=("elapsed_ms", "median"),
            max_latency_ms=("elapsed_ms", "max"),
            min_latency_ms=("elapsed_ms", "min"),
            avg_answer_chars=("answer_chars", "mean"),
            analysis_count=("type", lambda s: int((s == "analysis").sum())),
            text_count=("type", lambda s: int((s == "text").sum())),
        ).reset_index()
        summary["success_rate_pct"] = summary["success_count"] / summary["question_count"] * 100
        summary["analysis_ratio_pct"] = summary["analysis_count"] / summary["question_count"] * 100
        for column in [
            "avg_latency_ms",
            "median_latency_ms",
            "max_latency_ms",
            "min_latency_ms",
            "avg_answer_chars",
            "success_rate_pct",
            "analysis_ratio_pct",
        ]:
            summary[column] = summary[column].round(2)
        return summary

    def _question_compare(self, df):
        pivot = df.pivot_table(
            index=["index", "question"],
            columns="mode",
            values=["elapsed_ms", "answer_chars"],
            aggfunc="first",
        )
        pivot.columns = [f"{metric}_{mode}".lower() for metric, mode in pivot.columns]
        pivot = pivot.reset_index()
        pivot["latency_speedup_agent_over_hybrid"] = (
            pivot["elapsed_ms_agent"] / pivot["elapsed_ms_hybrid"]
        ).round(2)
        pivot["latency_reduction_pct"] = (
            (pivot["elapsed_ms_agent"] - pivot["elapsed_ms_hybrid"]) / pivot["elapsed_ms_agent"] * 100
        ).round(2)
        return pivot

    def _setup_matplotlib(self, plt):
        plt.rcParams["font.sans-serif"] = [
            "Microsoft YaHei",
            "SimHei",
            "Arial Unicode MS",
            "DejaVu Sans",
        ]
        plt.rcParams["axes.unicode_minus"] = False

    def _plot_summary(self, plt, summary_df, output):
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.bar(summary_df["mode"], summary_df["avg_latency_ms"] / 1000, color=["#2f7ed8", "#d95f02"])
        ax.set_title("Average Response Latency")
        ax.set_ylabel("Seconds")
        for idx, value in enumerate(summary_df["avg_latency_ms"] / 1000):
            ax.text(idx, value, f"{value:.2f}s", ha="center", va="bottom")
        fig.tight_layout()
        fig.savefig(output, dpi=180)
        plt.close(fig)

    def _plot_question_latency(self, plt, question_df, output):
        labels = [f"Q{int(i)}" for i in question_df["index"]]
        x = range(len(labels))
        width = 0.38
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.bar([i - width / 2 for i in x], question_df["elapsed_ms_hybrid"] / 1000, width, label="Hybrid")
        ax.bar([i + width / 2 for i in x], question_df["elapsed_ms_agent"] / 1000, width, label="Agent")
        ax.set_title("Latency by Question")
        ax.set_ylabel("Seconds")
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels)
        ax.legend()
        fig.tight_layout()
        fig.savefig(output, dpi=180)
        plt.close(fig)

    def _plot_answer_chars(self, plt, question_df, output):
        labels = [f"Q{int(i)}" for i in question_df["index"]]
        x = range(len(labels))
        width = 0.38
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.bar([i - width / 2 for i in x], question_df["answer_chars_hybrid"], width, label="Hybrid")
        ax.bar([i + width / 2 for i in x], question_df["answer_chars_agent"], width, label="Agent")
        ax.set_title("Answer Length by Question")
        ax.set_ylabel("Characters")
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels)
        ax.legend()
        fig.tight_layout()
        fig.savefig(output, dpi=180)
        plt.close(fig)

    def _build_markdown(self, summary_df, question_df, hybrid, agent) -> str:
        hybrid_summary = summary_df[summary_df["mode"] == "Hybrid"].iloc[0]
        agent_summary = summary_df[summary_df["mode"] == "Agent"].iloc[0]
        speedup = agent_summary["avg_latency_ms"] / hybrid_summary["avg_latency_ms"]
        reduction = (
            (agent_summary["avg_latency_ms"] - hybrid_summary["avg_latency_ms"])
            / agent_summary["avg_latency_ms"]
            * 100
        )

        fastest = question_df.sort_values("latency_speedup_agent_over_hybrid", ascending=False).head(3)

        lines = [
            "# 智能助手性能对比实验报告",
            "",
            "## 实验设置",
            "",
            f"- 模型服务商：{hybrid['summary']['provider']}",
            f"- 模型：{hybrid['summary']['model']}",
            "- 对比模式：Hybrid 混合路由 vs Agent 纯工具调用",
            f"- 问题数量：{hybrid['summary']['question_count']} 个",
            "",
            "Hybrid 模式表示明确业务问题优先由规则路由调用确定性工具函数，开放式问题再交由大模型处理。Agent 模式表示数据类问题也交由大模型进行工具选择和结果组织。",
            "",
            "## 总体结果",
            "",
            "| 模式 | 成功率 | 平均耗时(ms) | 中位耗时(ms) | 最大耗时(ms) | analysis占比 | 平均回答长度 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for _, row in summary_df.iterrows():
            lines.append(
                f"| {row['mode']} | {row['success_rate_pct']:.2f}% | {row['avg_latency_ms']:.2f} | "
                f"{row['median_latency_ms']:.2f} | {row['max_latency_ms']:.2f} | "
                f"{row['analysis_ratio_pct']:.2f}% | {row['avg_answer_chars']:.2f} |"
            )

        lines.extend([
            "",
            f"总体上，Hybrid 模式平均耗时为 {hybrid_summary['avg_latency_ms']:.2f} ms，Agent 模式平均耗时为 {agent_summary['avg_latency_ms']:.2f} ms。Hybrid 相比 Agent 平均提速约 {speedup:.2f} 倍，延迟降低约 {reduction:.2f}%。",
            "",
            "## 分问题对比",
            "",
            "| 编号 | 问题 | Hybrid耗时(ms) | Agent耗时(ms) | 提速倍数 | 延迟降低 |",
            "|---:|---|---:|---:|---:|---:|",
        ])
        for _, row in question_df.iterrows():
            question = str(row["question"]).replace("|", "\\|")
            lines.append(
                f"| Q{int(row['index'])} | {question} | {row['elapsed_ms_hybrid']:.2f} | "
                f"{row['elapsed_ms_agent']:.2f} | {row['latency_speedup_agent_over_hybrid']:.2f} | "
                f"{row['latency_reduction_pct']:.2f}% |"
            )

        lines.extend([
            "",
            "## 典型结果分析",
            "",
            "Hybrid 模式在结构化业务问题上优势明显，尤其是地层磨损关联、厂家对比、开仓统计、刀位排行、换刀趋势等任务。这些任务具有明确的数据来源和固定计算逻辑，使用规则路由直接调用领域工具函数可以避免大模型进行工具选择、长上下文推理和二次生成，从而显著降低响应延迟。",
            "",
            "提速最明显的三个问题为：",
        ])
        for _, row in fastest.iterrows():
            lines.append(
                f"- Q{int(row['index'])}：{row['question']}，提速 {row['latency_speedup_agent_over_hybrid']:.2f} 倍。"
            )

        lines.extend([
            "",
            "Agent 模式的优势在于回答更具自然语言组织能力，尤其适合开放式解释和综合建议类问题。但在结构化工程数据分析场景中，纯 Agent 模式需要额外完成工具选择和结果组织，导致响应时间显著增加。",
            "",
            "## 结论",
            "",
            "实验表明，在盾构刀具管理这类结构化工程数据系统中，混合式智能助手架构比纯 Agent 架构更适合实际应用。其核心优势在于：",
            "",
            "1. 明确业务意图由规则路由直接分发，提高工具选择稳定性。",
            "2. 数据计算由后端确定性工具完成，降低数字幻觉风险。",
            "3. 大模型主要承担开放式解释和语言生成任务，减少 token 消耗和响应延迟。",
            "4. 系统同时保留 Agent 模式，能够处理模糊问题和复杂多步骤问题。",
            "",
            "因此，本文采用“规则路由 + 领域工具函数 + API 大模型”的混合式架构，能够在准确性、响应效率和工程可控性之间取得更好的平衡。",
            "",
            "## 图表文件",
            "",
            "- `latency_summary.png`：平均响应延迟对比",
            "- `latency_by_question.png`：逐问题延迟对比",
            "- `answer_length_by_question.png`：逐问题回答长度对比",
            "- `benchmark_summary.csv`：总体统计表",
            "- `benchmark_question_compare.csv`：逐问题对比表",
        ])

        return "\n".join(lines) + "\n"
