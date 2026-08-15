"""人工评分（rubric 题）的汇总与标注一致性检验。

E8 实验：知识题与拒答题没有数值真值，由 3 名标注者按题库里的 rubric（0/1/2 三档）
独立打分。本命令做两件事：

  1. --template  从实验 JSONL 里抽出 rubric 题的答案，生成评分表 CSV
                 （每个标注者复制一份独立填写，互相不可见）；
  2. --input     读回填好的评分表，输出分数分布、逐题均分，以及 Fleiss' κ ——
                 审稿人看到人工评分的第一反应就是问标注者间一致性。

评分表格式（CSV）：case_id, rep, rater, score, answer
  rater 填标注者代号（A/B/C），score 填 0/1/2。

用法：
    python manage.py rubric_kappa --template experiment_r1_hybrid.jsonl --output ratings_template.csv
    python manage.py rubric_kappa --input ratings_A.csv ratings_B.csv ratings_C.csv
"""

import csv
import json
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


def fleiss_kappa(matrix):
    """matrix: list of [n_0, n_1, ..., n_k]，每行一个题目、每列一个分数档的票数。
    所有行的总票数（标注者数）必须相同。"""
    if not matrix:
        return None
    n_raters = sum(matrix[0])
    if n_raters < 2 or any(sum(row) != n_raters for row in matrix):
        return None
    n_items = len(matrix)
    # 每档的边际比例
    totals = [sum(row[j] for row in matrix) for j in range(len(matrix[0]))]
    p_j = [t / (n_items * n_raters) for t in totals]
    p_e = sum(p * p for p in p_j)
    # 每题的观测一致度
    p_i = [
        (sum(c * c for c in row) - n_raters) / (n_raters * (n_raters - 1))
        for row in matrix
    ]
    p_bar = sum(p_i) / n_items
    if p_e == 1.0:
        return 1.0
    return (p_bar - p_e) / (1 - p_e)


class Command(BaseCommand):
    help = "rubric 题人工评分：生成评分模板 / 汇总并计算 Fleiss' κ"

    def add_arguments(self, parser):
        parser.add_argument("--template", default="", help="从该实验 JSONL 生成评分模板")
        parser.add_argument("--output", default="ratings_template.csv")
        parser.add_argument("--input", nargs="*", default=[], help="填好的评分表（可多份）")
        parser.add_argument("--levels", type=int, default=3, help="评分档数，默认 0/1/2 三档")

    def handle(self, *args, **options):
        if options["template"]:
            self._make_template(options)
            return
        if options["input"]:
            self._summarize(options)
            return
        raise CommandError("需要 --template 或 --input 之一")

    # ------------------------------------------------------------------
    def _make_template(self, options):
        path = Path(options["template"])
        if not path.exists():
            raise CommandError(f"文件不存在：{path}")
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("task_type") == "rubric" and not r.get("is_warmup"):
                rows.append(r)
        if not rows:
            raise CommandError("该 JSONL 中没有 rubric 题记录（task_type=rubric）")
        # 同题多次重复：默认全抽；标注量大时可只评第一次非 warmup 重复
        out = Path(options["output"])
        with out.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["case_id", "rep", "rater", "score", "question", "answer"])
            for r in rows:
                writer.writerow([r.get("case_id"), r.get("rep"), "", "",
                                 r.get("question", ""), (r.get("answer") or "").replace("\n", " ")])
        self.stdout.write(self.style.SUCCESS(
            f"评分模板已写出 {out}（{len(rows)} 行）。"
            f"复制三份给标注者独立填写 rater 与 score(0-{options['levels'] - 1})，不要互相参考。"
        ))

    # ------------------------------------------------------------------
    def _summarize(self, options):
        levels = options["levels"]
        votes = defaultdict(lambda: defaultdict(dict))  # (case_id, rep) -> rater -> score
        for path in options["input"]:
            p = Path(path)
            if not p.exists():
                raise CommandError(f"文件不存在：{path}")
            with p.open(encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    rater = (row.get("rater") or "").strip()
                    score = (row.get("score") or "").strip()
                    if not rater or score == "":
                        continue
                    try:
                        score = int(score)
                    except ValueError:
                        continue
                    if not 0 <= score < levels:
                        raise CommandError(
                            f"{path}: {row.get('case_id')} 的分数 {score} 超出 0-{levels - 1}")
                    votes[(row.get("case_id"), row.get("rep"))][rater] = score

        if not votes:
            raise CommandError("没有读到任何有效评分")

        rater_counts = {len(v) for v in votes.values()}
        if len(rater_counts) != 1:
            self.stdout.write(self.style.WARNING(
                f"各题的标注者数不一致：{sorted(rater_counts)}；"
                "Fleiss' κ 只对标注者数相同的题计算"
            ))
        n_raters = max(rater_counts)
        complete = {k: v for k, v in votes.items() if len(v) == n_raters}

        matrix = []
        for scores in complete.values():
            row = [0] * levels
            for s in scores.values():
                row[s] += 1
            matrix.append(row)
        kappa = fleiss_kappa(matrix)

        all_scores = [s for v in votes.values() for s in v.values()]
        dist = [all_scores.count(i) for i in range(levels)]
        self.stdout.write(f"题目 {len(votes)}（完整标注 {len(complete)}），标注者 {n_raters} 人，"
                          f"总评分 {len(all_scores)} 次")
        self.stdout.write("分数分布：" + "，".join(
            f"{i} 分 ×{dist[i]} ({dist[i] / len(all_scores) * 100:.0f}%)" for i in range(levels)))
        self.stdout.write(f"平均分：{sum(all_scores) / len(all_scores):.2f} / {levels - 1}")
        if kappa is not None:
            band = ("poor" if kappa < 0.2 else "fair" if kappa < 0.4 else
                    "moderate" if kappa < 0.6 else "substantial" if kappa < 0.8 else "almost perfect")
            self.stdout.write(self.style.SUCCESS(
                f"Fleiss' κ = {kappa:.3f}（{band}，Landis & Koch 分档）"))
        else:
            self.stdout.write(self.style.WARNING("无法计算 κ（标注者不足 2 人或数据不齐）"))

        # 逐题均分（写文件便于挑分歧大的题做仲裁）
        self.stdout.write("")
        self.stdout.write("分歧最大的题（标准差降序，前 5）：")
        import statistics
        spread = []
        for key, scores in complete.items():
            values = list(scores.values())
            spread.append((statistics.pstdev(values), key, values))
        for sd, key, values in sorted(spread, reverse=True)[:5]:
            self.stdout.write(f"  {key[0]} rep{key[1]}: {values} (σ={sd:.2f})")
