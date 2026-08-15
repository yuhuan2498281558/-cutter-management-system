"""对照组基线：纯 LLM 直答 与 text-to-SQL。

论文的核心主张是"用确定性领域工具替代 text-to-SQL 可消除数值幻觉"。这个主张需要
一个真会产生幻觉的对照组来支撑——否则等于自说自话。本模块提供两条基线，接口与
ToolAssistant.chat() 对齐，可以直接喂给同一个评分器。

  NoToolBaseline    只有 LLM，不给工具、不注入任何数据 → 幻觉率的上界
  TextToSQLBaseline LLM 生成 SQL → 只读执行 → LLM 复述结果 → 常见的对照做法

注意 NoToolBaseline 没有复用 ToolAssistant._direct_chat：后者会通过
_build_context_message 注入项目实时数据快照，那就不是"无数据基线"而是
"RAG-lite 基线"了，对照会失真。
"""

import json
import logging
import os
import re
import time

from django.apps import apps
from django.db import connection, transaction
from langchain_core.messages import HumanMessage, SystemMessage

from .llm_provider import create_chat_model

logger = logging.getLogger(__name__)

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|"
    r"vacuum|analyze|call|do|merge)\b",
    re.IGNORECASE,
)

# 只允许查询盾构业务表，避免模型去翻用户表 / 权限表
_ALLOWED_TABLES = {
    "shield_project_info",
    "shield_machine_basic_info",
    "shield_stratum_basic_info",
    "shield_tool_category",
    "shield_tool_info",
    "shield_tool_cost",
    "shield_tunneling_data",
    "shield_cutter_position_info",
    "shield_warehouse_opening_basic",
    "shield_tool_change_detail",
    "shield_tool_instance",
    "shield_new_tool_record",
    "shield_old_tool_record",
}


def _usage_callback():
    try:
        from langchain_core.callbacks import UsageMetadataCallbackHandler
    except ImportError:
        return [], lambda: {}
    handler = UsageMetadataCallbackHandler()
    return [handler], lambda: getattr(handler, "usage_metadata", {}) or {}


class NoToolBaseline:
    """Arm A：LLM 直答，无工具、无数据库、无上下文注入。"""

    ARM = "llm_only"
    SYSTEM = (
        "你是盾构隧道刀具管理领域的专家。请直接回答用户的问题。"
        "如果问题需要具体的工程数据而你手头没有，请明确说明数据缺失，不要编造数字。"
    )

    def __init__(self, model_name=None):
        self.llm = create_chat_model(model_name)

    def chat(self, user_query: str, context: dict = None) -> dict:
        callbacks, get_usage = _usage_callback()
        started = time.perf_counter()
        try:
            response = self.llm.invoke(
                [SystemMessage(content=self.SYSTEM), HumanMessage(content=user_query)],
                config={"callbacks": callbacks} if callbacks else None,
            )
            answer = response.content if hasattr(response, "content") else str(response)
            success = True
            error = ""
        except Exception as e:
            answer, success, error = "", False, str(e)
            logger.error("NoToolBaseline 调用失败：%s", e)
        return {
            "success": success,
            "answer": answer,
            "error": error,
            "type": "text",
            "route": "llm_only",
            "route_stage": "llm_only",
            "tool_calls": [],
            "usage": get_usage(),
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }


def build_schema_prompt() -> str:
    """从 Django models 自动导出 schema 摘要。

    自动导出而不是手写，是为了避免 schema 说明与实际库结构漂移——一旦漂移，
    text-to-SQL 基线的失败就分不清是"方法不行"还是"提示词写错了"。
    """
    lines = []
    for model in apps.get_app_config("shield").get_models():
        table = model._meta.db_table
        if table not in _ALLOWED_TABLES:
            continue
        columns = []
        for field in model._meta.fields:
            desc = f"{field.column} {field.get_internal_type()}"
            choices = getattr(field, "choices", None)
            if choices:
                desc += "(" + "|".join(str(c[0]) for c in choices) + ")"
            if field.is_relation and field.related_model is not None:
                desc += f"->{field.related_model._meta.db_table}.id"
            columns.append(desc)
        lines.append(f"TABLE {table}({', '.join(columns)})")
    return "\n".join(lines)


SQL_SYSTEM_TEMPLATE = """你是 SQL 生成器。根据下面的 PostgreSQL schema，把用户的中文问题翻译成一条 SELECT 语句。

{schema}

规则：
1. 只输出一条 SELECT 语句，不要解释，不要 markdown 代码块，不要分号。
2. ring_no / last_ring_no 是文本列。做数值比较或排序前必须先过滤再转换：
   WHERE ring_no ~ '^[0-9]+$' 之后再用 CAST(ring_no AS INTEGER)。
   直接 CAST 非数字文本在 PostgreSQL 下会报错。
3. 默认限定项目：shield_project_info.project_id = '{project_id}'。
4. shield_stratum_basic_info.stratum_type_codes 是逗号分隔的多值字段。
5. 结果行数不要超过 200。
"""


class TextToSQLBaseline:
    """Arm B：LLM 生成 SQL → 只读执行 → LLM 复述。

    失败分三层统计，论文里要分开报：
      sql_syntax_error  生成的语句不合法或被安全护栏拦下
      sql_exec_error    语句合法但数据库执行报错
      semantic_error    执行成功但结果与真值不符（由评分器判定）
    第三层才是 text-to-SQL 的真正短板，也是与确定性工具对比的关键证据。
    """

    ARM = "text2sql"
    MAX_REPAIR = 1  # 自修复轮数，论文需注明

    def __init__(self, model_name=None, project_id=None):
        project_id = project_id or os.environ.get("DEMO_PROJECT_ID", "demo-project")
        self.llm = create_chat_model(model_name)
        self.project_id = project_id
        self._schema = None

    @property
    def schema(self):
        if self._schema is None:
            self._schema = build_schema_prompt()
        return self._schema

    def _guard(self, raw: str) -> str:
        sql = re.sub(r"^```(?:sql)?|```$", "", (raw or "").strip(), flags=re.MULTILINE).strip()
        sql = sql.rstrip(";").strip()
        if not sql.lower().startswith("select"):
            raise ValueError("生成结果不是 SELECT 语句")
        if ";" in sql:
            raise ValueError("不允许多语句")
        if _FORBIDDEN.search(sql):
            raise ValueError("包含写操作关键字")
        if " limit " not in sql.lower():
            sql += " LIMIT 200"
        return sql

    @staticmethod
    def _execute(sql: str):
        # 只读执行：整个事务强制回滚，即使护栏被绕过也不会留下副作用
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql)
                columns = [c[0] for c in cursor.description]
                rows = [dict(zip(columns, r)) for r in cursor.fetchall()]
            transaction.set_rollback(True)
        return rows

    def chat(self, user_query: str, context: dict = None) -> dict:
        callbacks, get_usage = _usage_callback()
        started = time.perf_counter()
        system = SQL_SYSTEM_TEMPLATE.format(schema=self.schema, project_id=self.project_id)
        messages = [SystemMessage(content=system), HumanMessage(content=user_query)]

        sql, rows, failure, repairs = "", None, "", 0
        for attempt in range(self.MAX_REPAIR + 1):
            try:
                raw = self.llm.invoke(
                    messages, config={"callbacks": callbacks} if callbacks else None
                )
                text = raw.content if hasattr(raw, "content") else str(raw)
            except Exception as e:
                failure = f"sql_syntax_error: 模型调用失败 {e}"
                break
            try:
                sql = self._guard(text)
            except Exception as e:
                failure, repairs = f"sql_syntax_error: {e}", attempt + 1
                messages += [
                    HumanMessage(content=f"上一次输出不合法：{e}。请只输出一条合法的 SELECT 语句。")
                ]
                continue
            try:
                rows = self._execute(sql)
                failure = ""
                break
            except Exception as e:
                failure, repairs = f"sql_exec_error: {e}", attempt + 1
                messages += [
                    HumanMessage(content=f"上一条 SQL 执行失败：{e}\n请修正后重新只输出 SQL。")
                ]

        answer = ""
        if rows is not None:
            try:
                verbalized = self.llm.invoke(
                    [
                        SystemMessage(content=(
                            "把 SQL 查询结果转成简洁的中文回答。"
                            "只能使用结果中出现的数字，不得推算、不得补充结果里没有的数据。"
                        )),
                        HumanMessage(content=(
                            f"问题：{user_query}\n"
                            f"查询结果：{json.dumps(rows, ensure_ascii=False, default=str)}"
                        )),
                    ],
                    config={"callbacks": callbacks} if callbacks else None,
                )
                answer = verbalized.content if hasattr(verbalized, "content") else str(verbalized)
            except Exception as e:
                failure = failure or f"verbalize_error: {e}"

        return {
            "success": rows is not None and not failure,
            "answer": answer,
            "error": failure,
            "failure_stage": failure.split(":")[0] if failure else "",
            "type": "sql",
            "route": "text2sql",
            "route_stage": "text2sql",
            "sql": sql,
            "rows": rows,
            "repair_rounds": repairs,
            "tool_calls": [],
            "usage": get_usage(),
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
