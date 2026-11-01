"""只运行真实首问判定条件；分支确定后截去查数，快照不依赖业务库。"""
import ast
import json
import types
from pathlib import Path
from unittest.mock import patch

from django.core.management.base import BaseCommand

from application.ai_assistant.evaluation.fixed_suite import load_fixed_cases
from application.ai_assistant.memory_service import MemorySnapshot


ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "evaluation" / "route_snapshot.json"


def build_route_snapshot(bank=None):
    """bank 是 v4 题库的题目；题库文件不入库，测试从已签入的快照里取题。"""
    tree = ast.parse((ROOT / "llm_service.py").read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ToolAssistant")
    for method in cls.body:
        if not isinstance(method, ast.FunctionDef):
            continue
        if method.name == "_direct_route_result":
            for statement in method.body:
                if not isinstance(statement, ast.If):
                    continue
                for result in statement.body:
                    if isinstance(result, ast.Return) and isinstance(result.value, ast.Dict):
                        fields = {key.value: value for key, value in zip(result.value.keys, result.value.values)
                                  if isinstance(key, ast.Constant)}
                        branch = fields.get("rule_branch")
                        if isinstance(branch, ast.Constant):
                            statement.body = ast.parse(f"return {{'rule_branch': {branch.value!r}, 'answer': ''}}").body
                            break
        elif method.name == "_refresh_route":
            end = next(i for i, statement in enumerate(method.body) if isinstance(statement, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "data" for target in statement.targets))
            method.body = method.body[:end] + ast.parse("return {'rule_branch': branch, 'answer': ''}").body
            # 固定快照没有命名厂家/型号；移除分支内的目录查询。
            for statement in ast.walk(method):
                if isinstance(statement, ast.Assign) and any(
                        isinstance(target, ast.Name) and target.id == "models" for target in statement.targets):
                    statement.value = ast.List(elts=[], ctx=ast.Load())
    module = types.ModuleType("application.ai_assistant._fixed_route_snapshot")
    module.__package__ = "application.ai_assistant"
    exec(compile(ast.fix_missing_locations(tree), str(ROOT / "llm_service.py"), "exec"), module.__dict__)
    snapshot = {"project_id": "FIXED-QA-DEMO", "snapshot_latest_ring": 487,
                "snapshot_total_openings": 15, "snapshot_total_positions": 122,
                "context_mode": "new", "route_mode": "rule"}
    module._data_coverage = lambda *args: {"ring_min": 1, "ring_max": snapshot["snapshot_latest_ring"]}
    rows = []
    if bank is None:
        bank = json.loads((ROOT / "question_bank_v4.json").read_text(encoding="utf-8"))
    with patch.object(module, "create_chat_model", side_effect=AssertionError("禁止创建模型")), patch.object(
            module.ToolAssistant, "_named_manufacturers", return_value=[]), patch.object(
            module.ToolAssistant, "_ensure_llm_runtime", side_effect=AssertionError("禁止创建模型")), patch.object(
            module.ToolAssistant, "_recent_ring_range", side_effect=lambda query, context: [
                max(1, snapshot["snapshot_latest_ring"] - assistant._extract_recent_ring_window(query) + 1),
                snapshot["snapshot_latest_ring"]]):
        assistant = module.ToolAssistant()
        for suite, cases in (("quick", [case for case in load_fixed_cases() if case["kind"] == "quick"]),
                             ("question_bank_v4", bank)):
            for case in cases:
                context = assistant._prepare_query_context(
                    case["question"], MemorySnapshot(scope_key="fixed-route"), dict(snapshot))
                result = assistant._direct_route(context["effective_query"], context)
                rows.append({"suite": suite, "id": case["id"], "question": case["question"],
                             "branch": result["rule_branch"] if result else None})
    return rows


def snapshot_differences(previous, current):
    old = {(row["suite"], row["id"]): row for row in previous}
    new = {(row["suite"], row["id"]): row for row in current}
    return [(key[1], old.get(key, {}).get("branch"), new.get(key, {}).get("branch"),
             new.get(key, old.get(key))["question"])
            for key in dict.fromkeys([*old, *new]) if old.get(key) != new.get(key)]


class Command(BaseCommand):
    help = "重新生成固定题单及 v4 题库的首问规则分支快照。"

    def handle(self, *args, **options):
        current = build_route_snapshot()
        previous = json.loads(SNAPSHOT.read_text(encoding="utf-8")) if SNAPSHOT.exists() else []
        differences = snapshot_differences(previous, current)
        if differences:
            self.stdout.write(f"以下 {len(differences)} 题的首问分支与快照不同：")
            for case_id, old, new, question in differences:
                self.stdout.write(f"{case_id}  {old} → {new}  {question[:30]}")
        else:
            self.stdout.write(f"首问分支与快照一致，共 {len(current)} 题。")
        SNAPSHOT.write_text("[\n" + ",\n".join(
            "  " + json.dumps(row, ensure_ascii=False) for row in current) + "\n]\n", encoding="utf-8")
        self.stdout.write("已更新 route_snapshot.json。")
