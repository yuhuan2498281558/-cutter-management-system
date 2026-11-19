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
import sqlparse
from sqlparse.sql import Identifier, IdentifierList, Parenthesis, TokenList
from sqlparse.tokens import Keyword

from django.apps import apps
from django.db import connection, transaction
from pydantic import BaseModel, Field

from .agent_loop import AgentPrompt, invoke_agent
from .context_budget import ContextUsage, context_usage
from .messages import AIMessage, HumanMessage, SystemMessage
from .prompts import ANSWER_POLICY, SYSTEM_PROMPT
from .tooling import Tool
from .chat_model import UsageCollector

from .llm_provider import create_chat_model
from .evaluation.current_data_suite import readonly_database

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

_DATA_CONTRACT = """有效刀位共122个：DISC为1–79、80A、80B、Y1、Y3、Y5，SCRAPER为S1L–S19L及S1R–S19R，编号去首尾空白、大写并去数字前导零，刀型须匹配。
现场观测记录是有效刀位上is_checked或is_replaced为真的明细。
开仓summary_status区分CONFIRMED和DRAFT，只有已确认汇总使用checked_tool_count及replaced_tool_count。
旧刀inspection_status区分PENDING_VENDOR_FEEDBACK（待反馈）、CONFIRMED（已确认）、CLOSED（已归档），已报废只计后两种状态且disposition为SCRAP。
地层longitudinal_type_ratios为纵断面六类面积，stratum_type_ratios为横断面岩性占比，两者不同于历史标签stratum_type_codes。
成本库cost_type区分NEW_TOOL新刀价和REPAIR维修价，共用报价不是项目实际支出，项目金额称登记金额。"""


def _check_tables(tokens):
    source = False
    for token in tokens.tokens:
        if token.is_whitespace or token.ttype in sqlparse.tokens.Comment:
            continue
        if token.ttype in Keyword and (token.normalized == 'FROM' or 'JOIN' in token.normalized):
            source = True
            continue
        if source:
            identifiers = list(token.get_identifiers()) if isinstance(token, IdentifierList) else [token]
            for identifier in identifiers:
                subquery = isinstance(identifier, Parenthesis) or (
                    isinstance(identifier, Identifier) and any(isinstance(t, Parenthesis) for t in identifier.tokens))
                if not subquery:
                    if not isinstance(identifier, Identifier) or identifier.get_real_name() not in _ALLOWED_TABLES:
                        raise ValueError('SQL引用了名单外的表')
                    if identifier.get_parent_name() not in (None, 'public'):
                        raise ValueError('SQL引用了名单外的schema')
                elif not any(t.ttype is sqlparse.tokens.DML and t.normalized == 'SELECT'
                             for t in identifier.flatten()):
                    raise ValueError('FROM只允许业务表或SELECT子查询')
            source = False
        if isinstance(token, TokenList):
            _check_tables(token)


def _usage_callback():
    collector = UsageCollector()
    return collector, lambda: collector.usage_metadata


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
        collector, get_usage = _usage_callback()
        started = time.perf_counter()
        try:
            response = self.llm.invoke(
                [SystemMessage(content=self.SYSTEM), HumanMessage(content=user_query)],
                config={"usage": collector},
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
    return "\n".join(lines) + "\n" + _DATA_CONTRACT


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
""" + "\n" + _DATA_CONTRACT


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
        _check_tables(sqlparse.parse(sql)[0])
        return sql

    @staticmethod
    def _execute(sql: str):
        # 不改写 SQL 加 LIMIT（旧做法在已有 LIMIT 的语句后再拼一次会出错），只取前 200 行
        with readonly_database():
            with connection.cursor() as cursor:
                cursor.execute(sql)
                columns = [c[0] for c in cursor.description]
                rows = [dict(zip(columns, r)) for r in cursor.fetchmany(200)]
        return rows

    def chat(self, user_query: str, context: dict = None) -> dict:
        collector, get_usage = _usage_callback()
        started = time.perf_counter()
        system = SQL_SYSTEM_TEMPLATE.format(schema=self.schema, project_id=self.project_id)
        messages = [SystemMessage(content=system), HumanMessage(content=user_query)]

        sql, rows, failure, repairs = "", None, "", 0
        for attempt in range(self.MAX_REPAIR + 1):
            try:
                raw = self.llm.invoke(
                    messages, config={"usage": collector}
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
                    config={"usage": collector},
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


# ---------------------------------------------------------------------------
# A0：强 Text-to-SQL 对照组。与助手使用同一工具调用循环、同一模型和轮数上限，
# 唯一差别是数据接口：这里只有一个只读 SQL 工具，业务口径写在提示词里；
# 助手则把同样的口径写进领域工具。口径说明与真值计算口径一致，论文附录全文公开。
# ---------------------------------------------------------------------------

SQL_DATA_DICTIONARY = """【数据字典】（只列与业务有关的列；各表都有 id 主键）
- shield_project_info 项目：project_id 项目编号，project_name 项目名称。其他表里的 project_id 列是指向本表 id 的外键，不是项目编号。
- shield_warehouse_opening_basic 开仓：ring_no 开仓所在环号（文本），open_time 开仓时间，project_id、shield_model_id 外键，opening_duration 开仓时长（小时），tool_change_duration 换刀总时长（小时），rings_between_openings 距上次开仓的环数，checked_tool_count / replaced_tool_count 人工填写的整仓检查数 / 更换数，summary_status 汇总状态（CONFIRMED 已确认、DRAFT 草稿）。
- shield_tool_change_detail 换刀明细（每次开仓每个刀位一行）：warehouse_id 所属开仓，cutter_position_no 刀位编号，tool_parent_type 刀型（DISC 滚刀、SCRAPER 刮刀），is_checked 已检查，is_replaced 已更换，wear_condition 现场磨损描述（描述的是检查或换下的旧刀），check_result 检查结论（ATTENTION 需关注、ABNORMAL_NOT_REPLACED 异常未换、NORMAL 正常等），tool_number 本次新装刀具编号，manufacturer / price 本次新装刀具的厂家和登记价格，blade_wear_amount 磨损量。
- shield_new_tool_record 新刀安装记录：tool_change_detail_id 安装所在的明细行，tool_instance_id 安装的刀具实例。
- shield_old_tool_record 旧刀记录（换下的刀）：tool_change_detail_id 拆下所在的明细行，confirmed_tool_instance_id 厂家确认的刀具实例，old_tool_number 旧刀编号，inspection_status 厂家反馈状态（PENDING_VENDOR_FEEDBACK 待厂家反馈、CONFIRMED 已确认、CLOSED 已归档），disposition 处置（SCRAP 报废、REPAIRABLE 可修复），repair_price 返修登记金额，ring_damage / bearing_failure_reasons / hub_failure_reasons 刀圈、轴承、刀毂的失效原因（JSON 数组）。
- shield_tool_instance 刀具实例：display_tool_no 刀具编号，tool_info_id 型号，status 当前状态。
- shield_tool_info 型号：tool_type_name 型号名称，tool_parent_type 刀型。
- shield_tool_cost 报价库（不分项目）：tool_info_id 型号，cost_type（NEW_TOOL 新刀报价、REPAIR 维修报价），manufacturer 厂家，brand 品牌，unit_price 单价（元）。
- shield_stratum_basic_info 地层（每环一行）：project_id 外键，ring_no 环号，stratum_type_codes 历史地层标签（逗号分隔，可多个），longitudinal_type_ratios 纵断面六类面积占比（JSON，键为 AREA_* 编码，值为百分数），stratum_type_ratios 横断面岩性占比。
- shield_tunneling_data 掘进参数（每条记录一行）：project_id 外键，ring_no 环号，record_time 时间，thrust 推力，torque 扭矩，cutterhead_speed 刀盘转速，penetration 贯入度，advance_speed 推进速度。
- shield_machine_basic_info 盾构机、shield_cutter_position_info 刀位、shield_tool_category 刀具类别：一般用不到。
"""

SQL_BUSINESS_RULES = """【业务口径】
1. 项目：当前项目编号为 <PROJECT>，查询都要经 project_id 外键关联 shield_project_info 限定到这个项目（报价库除外）。
2. 环号：ring_no 是文本，先用 ring_no ~ '^[0-9]+$' 过滤再 CAST 成整数比较和排序。换刀明细没有环号，取所属开仓的 ring_no。“第 a 到 b 环”指开仓环号在 [a, b] 内的记录；“最近 N 次开仓”按开仓环号从大到小取前 N 次；“最近 N 环”以最新一次开仓的环号为终点往前数 N 环。
3. 有效刀位共 122 个。编号先去首尾空白、转大写、去掉数字前导零；滚刀（DISC）为 1–79、80A、80B、Y1、Y3、Y5，刮刀（SCRAPER）为 S1L–S19L、S1R–S19R，刀型必须与编号对应。其他编号（G/H、Y2/Y4/Y6、先行刀等）一律不计。
4. 现场观测记录：有效刀位上 is_checked 或 is_replaced 为真的明细行。开仓时系统给每个刀位预建一行，预建行不是检查证据。开仓表里人工填写的 checked_tool_count / replaced_tool_count 是另一个口径，与明细统计分别保留，不能混用。
5. 更换数 = 现场观测记录中 is_replaced 为真的行数；更换率 = 更换数 ÷ 现场观测记录数 × 100%。
6. 磨损分类：wear_condition 去空白、转大写后，属于 <NORMAL> 的算正常，属于 <ABNORMAL> 的算异常，其余算未分类。已分类异常率 = 异常数 ÷（正常数 + 异常数）× 100%。异常类型就是 wear_condition 原文。
7. 需关注未更换：有效刀位上未更换（is_replaced 为假）且 check_result 为 ATTENTION 或 ABNORMAL_NOT_REPLACED 的行；未检查：有效刀位上 is_checked 和 is_replaced 都为假的行。
8. 服役环数（一把刀从装上到拆下经过的环数）：只用 inspection_status 为 CONFIRMED 或 CLOSED 的旧刀记录。用它的 confirmed_tool_instance_id 找安装记录（shield_new_tool_record 里该实例必须恰好一条）；安装行和拆下行都要是有效刀位上的更换行，两次开仓都已确认（summary_status = CONFIRMED）、属同一台盾构机，安装开仓时间不晚于拆下开仓，且安装环号小于拆下环号；服役环数 = 拆下开仓环号 − 安装开仓环号。同一安装行配到多条拆下记录时这些记录都不用。按厂家比较服役环数和异常率时用安装行的 manufacturer（刀具原安装时的厂家），异常按拆下行的 wear_condition 判断；按型号比较用安装实例的型号（shield_tool_instance.tool_info_id → shield_tool_info.tool_type_name）。
9. 厂家的新装供货次数和登记金额：有效刀位上更换行的 manufacturer 计数、price 求和。金额一律称登记金额，不是实际支出。
10. 返修：旧刀记录经 tool_change_detail_id 关联到有效刀位上的更换行。已报废 = inspection_status 为 CONFIRMED 或 CLOSED 且 disposition = SCRAP；还在 PENDING_VENDOR_FEEDBACK 的 SCRAP 只是报废建议。确认返修登记金额 = CONFIRMED 和 CLOSED 记录的 repair_price 之和。
11. 报价：shield_tool_cost 按型号和厂家各登记一条，新刀报价用 cost_type = NEW_TOOL，维修报价用 REPAIR；报价不是实际支出。
12. 地层：问占比、面积默认用纵断面 longitudinal_type_ratios：在范围内逐环取各编码的值（缺失按 0），再按环数取平均。面积编码含义：<AREA_LABELS>；历史标签编码去掉 AREA_ 前缀，含义相同。问地层标签、工程条件用 stratum_type_codes，统计含该标签的环数；不同标签可以共存，环数不能相加成总环数。开仓位置的地层取开仓环号那一环；“上次开仓以来经过的地层”取上一次开仓环号 +1 到本次开仓环号（第一次开仓从第 1 环算起）。面积来自图纸估算，不能据此判断磨损原因。
13. 掘进参数按 ring_no 对应环号；覆盖范围以表里实际记录为准，范围内没有记录时如实说明。
14. 追溯一把刀：按 shield_tool_instance.display_tool_no 找实例；经 shield_new_tool_record.tool_instance_id 找安装明细和开仓环号；经 shield_old_tool_record.confirmed_tool_instance_id 找拆下明细、开仓环号、厂家反馈状态和处置。
"""

SQL_EXAMPLES = """【示例】（有效明细的写法可以照抄）
问：统计100环到300环滚刀的现场观测记录数、更换数和更换率
SQL：
WITH d AS (
  SELECT d.*, CAST(w.ring_no AS INTEGER) AS ring, w.id AS opening_id,
         regexp_replace(upper(trim(d.cutter_position_no)), '^0+(?=[0-9])', '') AS pos,
         upper(trim(d.tool_parent_type)) AS ttype
  FROM shield_tool_change_detail d
  JOIN shield_warehouse_opening_basic w ON w.id = d.warehouse_id
  JOIN shield_project_info p ON p.id = w.project_id
  WHERE p.project_id = '<PROJECT>' AND w.ring_no ~ '^[0-9]+$'
), valid AS (
  SELECT * FROM d
  WHERE (pos ~ '^([1-9]|[1-7][0-9])$' OR pos IN ('80A','80B','Y1','Y3','Y5')) AND ttype = 'DISC'
     OR pos ~ '^S([1-9]|1[0-9])[LR]$' AND ttype = 'SCRAPER'
)
SELECT count(*) AS observed, sum(CASE WHEN is_replaced THEN 1 ELSE 0 END) AS replaced,
       round(100.0 * sum(CASE WHEN is_replaced THEN 1 ELSE 0 END) / count(*), 1) AS replacement_rate_pct
FROM valid WHERE (is_checked OR is_replaced) AND ttype = 'DISC' AND ring BETWEEN 100 AND 300

问：统计滚刀各型号已拆下刀具的平均服役环数和样本数
SQL：（前面接上例的 d、valid 两段）
, pairs AS (
  SELECT o.id AS removal_id, inst.id AS install_detail_id, rem.ring - inst.ring AS service_rings,
         inst.manufacturer AS install_manufacturer, ti.tool_type_name AS model, inst.ttype,
         count(*) OVER (PARTITION BY inst.id) AS uses
  FROM shield_old_tool_record o
  JOIN valid rem ON rem.id = o.tool_change_detail_id AND rem.is_replaced
  JOIN shield_new_tool_record n ON n.tool_instance_id = o.confirmed_tool_instance_id
  JOIN valid inst ON inst.id = n.tool_change_detail_id AND inst.is_replaced
  JOIN shield_warehouse_opening_basic wi ON wi.id = inst.opening_id
  JOIN shield_warehouse_opening_basic wr ON wr.id = rem.opening_id
  JOIN shield_tool_instance t ON t.id = n.tool_instance_id
  JOIN shield_tool_info ti ON ti.id = t.tool_info_id
  WHERE o.inspection_status IN ('CONFIRMED', 'CLOSED')
    AND (SELECT count(*) FROM shield_new_tool_record n2 WHERE n2.tool_instance_id = o.confirmed_tool_instance_id) = 1
    AND wi.summary_status = 'CONFIRMED' AND wr.summary_status = 'CONFIRMED'
    AND wi.shield_model_id = wr.shield_model_id AND wi.open_time <= wr.open_time AND inst.ring < rem.ring
)
SELECT model, count(*) AS samples, round(avg(service_rings), 1) AS avg_service_rings
FROM pairs WHERE uses = 1 AND ttype = 'DISC' GROUP BY model ORDER BY model

问：统计100环到300环各地层的面积占比
SQL：
SELECT key AS area_code, round(sum(value::numeric) / (
         SELECT count(*) FROM shield_stratum_basic_info s2 JOIN shield_project_info p2 ON p2.id = s2.project_id
         WHERE p2.project_id = '<PROJECT>' AND s2.ring_no ~ '^[0-9]+$' AND CAST(s2.ring_no AS INTEGER) BETWEEN 100 AND 300), 1) AS avg_pct
FROM shield_stratum_basic_info s
JOIN shield_project_info p ON p.id = s.project_id
CROSS JOIN LATERAL jsonb_each_text(COALESCE(s.longitudinal_type_ratios, '{}'::jsonb))
WHERE p.project_id = '<PROJECT>' AND s.ring_no ~ '^[0-9]+$' AND CAST(s.ring_no AS INTEGER) BETWEEN 100 AND 300
GROUP BY key ORDER BY key
"""

SQL_QUERY_GUIDE = """【写 SQL 与复杂问题的查法】
- 用 run_sql 执行一条 SELECT 或 WITH … SELECT 语句，不加分号；库是只读的。每次最多返回前 200 行并标注是否截断，需要总数、均值时在 SQL 里聚合。
- 报错时按错误信息修改后再查；可以多次调用，但同一条语句不要重复执行。
- 先把问题拆成几个子问题，每个子问题对应一类数据，再分别查询；各类数据使用同一个项目和环段。
- 不确定某类数据覆盖到哪里时，先查它的环号范围；某类数据在所问范围里没有记录时如实说明，不要换成别的范围凑数。
- 用户问原因、风险或建议时，只列出数据里能看到的待复核线索，不断言原因。
"""


def _prompt_section(name):
    return "【" + name + "】" + SYSTEM_PROMPT.split("【" + name + "】", 1)[1].split("【", 1)[0].rstrip() + "\n"


def sql_agent_prompt(project_code: str) -> str:
    """A0 的系统提示词：沿用助手的边界和回答要求，把工具里的口径改成书面说明。"""
    from .evaluation.fixed_suite import ABNORMAL, AREA_LABELS, NORMAL

    rules = (SQL_BUSINESS_RULES.replace("<NORMAL>", "、".join(sorted(NORMAL)))
             .replace("<ABNORMAL>", "、".join(sorted(ABNORMAL)))
             .replace("<AREA_LABELS>", "、".join(f"{code} {label}" for code, label in AREA_LABELS.items())))
    text = ("你是盾构刀具管理助手，负责查证工程数据、解释结果和提供有依据的复核建议。"
            "你只有一个只读工具 run_sql，用它在当前项目的 PostgreSQL 业务库上执行查询。\n\n"
            + _prompt_section("数据与权限边界") + "\n" + _prompt_section("库里没有的数据") + "\n"
            + SQL_DATA_DICTIONARY + "\n" + rules + "\n" + SQL_EXAMPLES + "\n"
            + SQL_QUERY_GUIDE + "\n" + _prompt_section("结果组织") + ANSWER_POLICY)
    # 工具调用循环会对系统提示词做 str.format，先转义花括号
    return text.replace("<PROJECT>", project_code).replace("{", "{{").replace("}", "}}")


_SQL_FUNCTION_DENY = re.compile(r"\b(pg_\w+|lo_\w+|dblink\w*|set_config|current_setting|query_to_xml\w*)\s*\(", re.IGNORECASE)


def _plan_relations(plan):
    if isinstance(plan, dict):
        if "Relation Name" in plan:
            yield plan.get("Schema", "public"), plan["Relation Name"]
        for value in plan.values():
            yield from _plan_relations(value)
    elif isinstance(plan, list):
        for value in plan:
            yield from _plan_relations(value)


def run_readonly_sql(query: str, max_rows: int = 200):
    """执行一条只读查询，返回 (列名, 行, 是否截断)。表白名单按执行计划里实际访问的表核对。"""
    sql = re.sub(r"^```(?:sql)?|```$", "", (query or "").strip(), flags=re.MULTILINE).strip().rstrip(";").strip()
    if not re.match(r"(?is)^(select|with)\b", sql):
        raise ValueError("只能执行 SELECT 或 WITH … SELECT 语句")
    if ";" in sql:
        raise ValueError("只能执行一条语句")
    if _FORBIDDEN.search(sql) or _SQL_FUNCTION_DENY.search(sql):
        raise ValueError("语句包含不允许的关键字或函数")

    def execute():
        # 外层已有只读事务时开保存点，出错只回滚这一条，不影响后续查询
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SHOW transaction_read_only")
            if cursor.fetchone()[0] != "on":
                raise RuntimeError("未处于只读事务")
            cursor.execute("EXPLAIN (VERBOSE, FORMAT JSON) " + sql)
            plan = cursor.fetchone()[0]
            plan = json.loads(plan) if isinstance(plan, str) else plan
            denied = sorted({f"{schema}.{name}" for schema, name in _plan_relations(plan)
                             if schema != "public" or name not in _ALLOWED_TABLES})
            if denied:
                raise ValueError("SQL 引用了不允许的表：" + "、".join(denied))
            cursor.execute(sql)
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchmany(max_rows + 1)
        return columns, rows[:max_rows], len(rows) > max_rows

    if connection.in_atomic_block:
        return execute()
    with readonly_database():
        return execute()


class SqlQueryInput(BaseModel):
    query: str = Field(description="一条只读的 SELECT 或 WITH … SELECT 语句，不加分号")


class SqlAgentBaseline:
    """A0：工具调用循环 + 只读 SQL 工具 + 书面口径说明。"""

    ARM = "sql_agent"
    MAX_ITERATIONS = 10
    MAX_ROWS = 200
    STOPPED = {"Agent stopped due to max iterations.", "Agent stopped due to iteration limit or time limit."}

    def __init__(self, model_name=None):
        self.llm = create_chat_model(model_name)

    def chat(self, user_query: str, context: dict = None) -> dict:
        context = context or {}
        usage = ContextUsage()
        token = context_usage.set(usage)
        collector = UsageCollector()
        started = time.perf_counter()
        calls = []

        def run_sql(query):
            call = {"tool": "run_sql", "args": {"query": query}}
            try:
                columns, rows, truncated = run_readonly_sql(query, self.MAX_ROWS)
                call.update(row_count=len(rows), truncated=truncated)
                observation = json.dumps({"columns": columns, "rows": rows, "row_count": len(rows),
                                          "truncated": truncated}, ensure_ascii=False, default=str)
            except Exception as error:
                message = str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__
                call["error"] = message
                observation = "查询失败：" + message
            call["result"] = observation
            calls.append(call)
            return observation

        sql_tool = Tool("run_sql", "在当前项目的只读业务库上执行一条 SELECT 或 WITH … SELECT 语句，返回列名和至多 200 行结果。",
                        SqlQueryInput, run_sql, handle_validation_error=lambda error: f"参数错误：{error}")
        history = []
        for question, answer in context.get("history", []):
            history += [HumanMessage(content=question), AIMessage(content=answer)]
        ctx_msg = context.get("context_message")
        query = f"{ctx_msg}\n\n{user_query}" if ctx_msg else user_query
        prompt = AgentPrompt(sql_agent_prompt(context.get("project_id", "")))
        answer, error, retried = "", "", False
        try:
            while True:
                result = invoke_agent(self.llm, prompt, [sql_tool], {"input": query, "chat_history": history},
                                      max_iterations=self.MAX_ITERATIONS, config={"usage": collector})
                # 与助手相同：一次都没查就作答时，提醒后重试一次
                if not result.get("intermediate_steps") and not history and not retried:
                    query += ("\n\n【系统提示】你上一次回答没有调用任何工具，直接编造了数据，这是错误的。"
                              "请立即调用对应工具查询真实数据，不得编造任何数字或结论。")
                    retried = True
                    continue
                break
            answer = result.get("output") or ""
            if answer.strip() in self.STOPPED:
                answer, error = "", "max_iterations"
            elif not answer.strip():
                error = "empty_answer"
        except Exception as exc:
            answer, error = "", type(exc).__name__
            logger.error("SqlAgentBaseline 调用失败：%s", exc)
        finally:
            context_usage.reset(token)
        return {
            "success": bool(answer.strip()) and not error,
            "answer": answer,
            "error": error,
            "type": "sql_agent",
            "route": "sql_agent",
            "route_stage": "sql_agent",
            "tool_calls": calls,
            "retry_count": int(retried),
            "usage": collector.usage_metadata,
            "context": {"provider_usage": usage.provider_usage},
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
