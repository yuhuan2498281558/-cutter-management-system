"""统一实验 runner：四路对照 × N 次重复 × 分层指标，逐条写 JSONL。

替代 benchmark_ai_assistant（那个命令只测耗时与"没抛异常"，产不出正确率）。

关键设计：
  * 每 (用例, 重复轮次) 一个独立 session_id，跑完立即 reset_memory。
    原 benchmark 全程共用 user_id="benchmark"，而 chat() 每轮都往持久化历史里写，
    于是第 N 题带着前 N-1 题的上下文，且跨进程、跨实验轮次残留——两个实验组的
    历史都不一样，结果没有可比性。
  * 逐条追加写 JSONL 而不是最后整体 dump，配合 --resume 可以断点续跑。
    四路 × 60 题 × 10 次约 2400 次调用，跑到一半崩了不能全部重来。
  * 每条记录都带 config 签名（路由模式 + 消融开关），结果文件自证配置。
  * 题库支持三种用例形态：
      普通题   带 gt_sql + answer_extract，严格数值判定
      变体题   带 gt_ref，继承种子题的真值与断言（鲁棒性子集零额外真值成本）
      多轮题   带 turns 列表，同一 session 逐轮发问，末轮后才清历史；
               expected_carryover 断言指代参数是否被正确继承

用法：
    python manage.py run_experiment --arm hybrid --repeat 10 --run-id r1
    python manage.py run_experiment --arm text2sql --repeat 5 --run-id r1 --resume
    python manage.py run_experiment --arm agent --repeat 10 --category tool_change
"""

import json
import os
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

# gt_ref 变体从种子题继承这些字段（自身已有的不覆盖）
_INHERITED_KEYS = (
    "gt_sql", "answer_extract", "tolerance",
    "expected_tool", "expected_args", "expected_route", "expected_rule_branch",
)


def resolve_refs(cases):
    """把 gt_ref 变体题展开为完整用例。种子缺失时报错而不是静默跳过。"""
    by_id = {c["id"]: c for c in cases}
    for case in cases:
        ref = case.get("gt_ref")
        if not ref:
            continue
        base = by_id.get(ref)
        if base is None:
            raise CommandError(f"用例 {case['id']} 的 gt_ref={ref} 不存在")
        for key in _INHERITED_KEYS:
            if not case.get(key) and base.get(key):
                case[key] = base[key]
    return cases


class Command(BaseCommand):
    help = "运行 AI 助手对照实验，逐条输出 JSONL"

    ARMS = ("llm_only", "text2sql", "agent", "hybrid")

    def add_arguments(self, parser):
        parser.add_argument("--arm", choices=self.ARMS, required=True)
        parser.add_argument("--bank", default="", help="题库路径，默认 question_bank_v2.json")
        parser.add_argument("--repeat", type=int, default=10, help="每题重复次数")
        parser.add_argument("--warmup", type=int, default=1, help="前 N 次标记为 warmup（分析时剔除）")
        parser.add_argument("--run-id", default="run", help="实验批次标识")
        parser.add_argument("--output", default="", help="JSONL 输出路径")
        parser.add_argument("--model", default="", help="覆盖模型名")
        parser.add_argument("--project", default=os.environ.get("DEMO_PROJECT_ID", "demo-project"))
        parser.add_argument("--category", action="append", default=[])
        parser.add_argument("--case-id", action="append", default=[])
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--resume", action="store_true", help="跳过 JSONL 中已完成的 (用例,轮次)")
        parser.add_argument("--include-todo", action="store_true",
                            help="包含尚未写 gt_sql 的 TODO 用例（默认跳过）")

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        # 幻觉数字率的白名单需要工具原始返回：强制开启调用记录的 result 捕获。
        # JSONL 落盘时仍会剥掉 result（见 _run_unit），文件不会被撑大。
        os.environ["AI_TRACE_TOOL_RESULTS"] = "1"
        arm = options["arm"]
        run_id = options["run_id"]
        repeat = max(1, options["repeat"])
        bank_path = Path(options["bank"] or (Path(__file__).resolve().parents[2] / "question_bank_v2.json"))
        if not bank_path.exists():
            raise CommandError(f"题库不存在：{bank_path}")
        cases = resolve_refs(json.loads(bank_path.read_text(encoding="utf-8-sig")))
        cases = self._filter(cases, options)
        if not options["include_todo"]:
            skipped = [c["id"] for c in cases if self._is_todo(c)]
            cases = [c for c in cases if not self._is_todo(c)]
            if skipped:
                self.stdout.write(self.style.WARNING(
                    f"跳过 {len(skipped)} 条未完成真值的用例（--include-todo 可强制包含）：{'、'.join(skipped)}"
                ))
        if not cases:
            raise CommandError("筛选后没有用例")

        out_path = Path(options["output"] or f"experiment_{run_id}_{arm}.jsonl")
        done = self._load_done(out_path) if options["resume"] else set()

        runner = self._build_runner(arm, options)
        from ...llm_service import current_config_signature

        total = len(cases) * repeat
        finished = 0
        self.stdout.write(f"arm={arm} 用例={len(cases)} 重复={repeat} 输出={out_path}")

        with out_path.open("a", encoding="utf-8") as sink:
            for case in cases:
                for rep in range(repeat):
                    finished += 1
                    if (case["id"], rep) in done:
                        continue
                    session_id = f"{run_id}::{arm}::{case['id']}::{rep}"
                    records = self._run_case(runner, arm, case, rep, session_id, options)
                    for record in records:
                        record.update({
                            "run_id": run_id,
                            "arm": arm,
                            "is_warmup": rep < options["warmup"],
                            "config": current_config_signature(),
                        })
                        sink.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                    sink.flush()
                    head = records[0]
                    flag = "OK " if all(r.get("exact_match") is not False for r in records) else "-- "
                    self.stdout.write(
                        f"[{finished}/{total}] {flag}{case['id']} rep{rep} "
                        f"{head.get('latency_ms', 0):.0f}ms"
                    )
        self.stdout.write(self.style.SUCCESS(f"完成，结果写入 {out_path}"))

    # ------------------------------------------------------------------
    @staticmethod
    def _is_todo(case) -> bool:
        if case.get("task_type") == "rubric":
            return False  # rubric 题照跑，答案留给人工评分
        return not (case.get("gt_sql") or case.get("gt_ref") or case.get("turns"))

    def _filter(self, cases, options):
        categories = set(options.get("category") or [])
        case_ids = set(options.get("case_id") or [])
        picked = [
            c for c in cases
            if (not categories or c.get("category") in categories)
            and (not case_ids or c.get("id") in case_ids)
        ]
        limit = options.get("limit") or 0
        return picked[:limit] if limit else picked

    def _load_done(self, path: Path) -> set:
        done = set()
        if not path.exists():
            return done
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                done.add((row.get("root_case_id") or row.get("case_id"), row.get("rep")))
            except Exception:
                continue
        return done

    def _build_runner(self, arm, options):
        model = options.get("model") or None
        if arm == "llm_only":
            from ...baselines import NoToolBaseline
            return NoToolBaseline(model_name=model)
        if arm == "text2sql":
            from ...baselines import TextToSQLBaseline
            return TextToSQLBaseline(model_name=model, project_id=options["project"])
        # agent / hybrid 都走 ToolAssistant，用 context.route_mode 区分。
        # 不能用 get_assistant()——模块级单例的模型配置在首次构造时固化，
        # 同进程内切 --model 不会生效。
        from ...llm_service import ToolAssistant
        return ToolAssistant(model_name=model) if model else ToolAssistant()

    # ------------------------------------------------------------------
    def _ground_truth(self, unit):
        sql = unit.get("gt_sql")
        if not sql:
            return None, ""
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql)
                columns = [c[0] for c in cursor.description]
                return [dict(zip(columns, r)) for r in cursor.fetchall()], ""
        except Exception as e:
            return None, str(e)

    def _run_case(self, runner, arm, case, rep, session_id, options):
        """返回记录列表：普通题 1 条；多轮题每轮 1 条。"""
        turns = case.get("turns")
        units = turns if turns else [case]
        records = []
        for index, unit in enumerate(units):
            question = unit.get("q") or unit.get("question")
            spec = {**{k: case.get(k) for k in _INHERITED_KEYS if case.get(k)}, **unit}
            record = self._run_unit(runner, arm, case, spec, question, session_id, options)
            record.update({
                "case_id": case["id"] if not turns else f"{case['id']}#t{index + 1}",
                "root_case_id": case["id"],
                "turn_index": (index + 1) if turns else None,
                "category": case.get("category"),
                "rep": rep,
            })
            records.append(record)

        # 会话隔离：整个用例（含全部轮次）跑完再清，轮与轮之间必须保留历史
        reset = getattr(runner, "reset_memory", None)
        if callable(reset):
            try:
                reset(session_id)
            except Exception:
                pass
        return records

    def _run_unit(self, runner, arm, case, spec, question, session_id, options):
        from ...scoring import score_case, score_routing

        gt_rows, gt_error = self._ground_truth(spec)
        context = {"user_id": session_id, "project_id": options["project"]}
        if arm in ("agent", "hybrid"):
            context["route_mode"] = arm

        started = time.perf_counter()
        try:
            response = runner.chat(question, context)
        except Exception as e:
            response = {"success": False, "answer": "", "error": str(e)}
        latency = round((time.perf_counter() - started) * 1000, 1)

        answer = response.get("answer") or ""
        # 幻觉白名单来源：工具调用的原始返回（hybrid/agent）+ SQL 查询结果（text2sql）
        whitelist_sources = list(response.get("tool_calls") or [])
        if response.get("rows") is not None:
            whitelist_sources.append(
                {"result": json.dumps(response["rows"], ensure_ascii=False, default=str)}
            )
        scored = score_case(
            answer, gt_rows, spec, question=question,
            tool_results=whitelist_sources,
        ) if gt_rows is not None else {}

        # 幻觉数字率只对经过 LLM 生成的文本有意义。纯规则路径（润色关、模板消融关）
        # 的答案由确定性代码生成——序号、模板内计算的峰谷差等会被白名单误 flag，
        # 但它们可逐一追溯到代码，不是幻觉。此时幻觉率按构造为零，原始 flag 保留
        # 在 *_raw 字段供诊断（校准实验实测：模板序号 "6." 与峰谷差被误计）。
        cfg = response.get("config") or {}
        deterministic_answer = (
            response.get("route_stage") == "rule"
            and not cfg.get("AI_ASSISTANT_POLISH_DIRECT")
            and not cfg.get("AI_ABLATE_TEMPLATE")
        )
        if scored and deterministic_answer:
            scored["hallucinated_numbers_raw"] = scored.get("hallucinated_numbers")
            scored["hallucinated_numbers"] = []
            scored["has_hallucinated_number"] = False
            scored["hallucination_by_construction"] = True
        routed = score_routing(response, spec)

        carryover_ok = None
        expected_carryover = spec.get("expected_carryover")
        if expected_carryover:
            calls = response.get("tool_calls") or []
            carryover_ok = all(
                any(self._arg_match((c.get("args") or {}).get(key), value) for c in calls)
                for key, value in expected_carryover.items()
            ) if calls else False

        record = {
            "question": question,
            "answer": answer,
            "success": response.get("success"),
            "error": response.get("error", ""),
            "failure_stage": response.get("failure_stage", ""),
            "sql": response.get("sql", ""),
            "repair_rounds": response.get("repair_rounds", 0),
            "route": response.get("route"),
            "route_stage": response.get("route_stage"),
            "rule_branch": response.get("rule_branch"),
            "tool_group": response.get("tool_group"),
            "tool_calls": [
                {"tool": c.get("tool"), "args": c.get("args")}
                for c in (response.get("tool_calls") or [])
            ],
            "usage": response.get("usage") or {},
            "retry_count": response.get("retry_count", 0),
            "latency_ms": response.get("latency_ms") or latency,
            "gt_available": gt_rows is not None,
            "gt_error": gt_error,
            "carryover_ok": carryover_ok,
            "task_type": case.get("task_type"),
            "variant_type": case.get("variant_type"),
        }
        record.update(scored)
        record.update(routed)
        return record

    @staticmethod
    def _arg_match(actual, expected) -> bool:
        if isinstance(expected, list) and isinstance(actual, list):
            return [str(x) for x in actual] == [str(x) for x in expected]
        return str(actual) == str(expected)
