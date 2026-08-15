"""
LLM服务封装 - 使用LangChain Tool Calling Agent + Ollama
历史记录通过 SQLChatMessageHistory 持久化到数据库，服务重启不丢失
"""

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import SQLChatMessageHistory
from .llm_provider import create_chat_model, get_llm_config
from .tools import (
    query_tool_change_data,
    query_stratum_data,
    calculate_tool_performance,
    recommend_tools,
    compare_manufacturer_performance,
    analyze_stratum_wear_correlation,
    query_opening_records,
    query_cutter_position_stats,
    query_tool_change_trend,
    query_position_stratum_impact,
    query_tunneling_summary,
    query_tunneling_trend,
    query_tunneling_anomaly,
    query_tunneling_wear_correlation,
)
from .prompts import SYSTEM_PROMPT
import logging
import json
import time
import os
import re
import asyncio
import threading
import functools
from datetime import datetime

try:  # langchain-core >= 0.3.30
    from langchain_core.callbacks import UsageMetadataCallbackHandler
except ImportError:  # 旧版本不提供该回调，token 统计降级为空
    UsageMetadataCallbackHandler = None

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 工具调用埋点
#
# 论文实验需要分层指标（路由准确率 / 工具选择准确率 / 工具参数准确率 / 数值正确率），
# 但规则直答路径是直接调用 tools.py 的函数、不经过 AgentExecutor，因此拿不到
# intermediate_steps。这里在模块层给 14 个领域工具套一层记录器：
#   - 规则直答路径：函数被直接调用，记录器命中；
#   - Agent 路径：@tool 包装器内部同样调用这些模块级名字，记录器也命中。
# 记录写在 threading.local 上，按请求隔离；不开启记录（未调用 _trace_start）时
# 记录器只是透传，运行时开销可忽略。
# ---------------------------------------------------------------------------
_TRACE = threading.local()


_TRACE_RESULT_LIMIT = 20000


def _trace_start():
    _TRACE.calls = []


def _trace_calls(include_results: bool = False) -> list:
    calls = getattr(_TRACE, "calls", []) or []
    if include_results:
        return [dict(c) for c in calls]
    return [{k: v for k, v in c.items() if k != "result"} for c in calls]


def _trace_stop():
    _TRACE.calls = None


def _traced_tool(func):
    @functools.wraps(func)
    def wrapper(params_str):
        calls = getattr(_TRACE, "calls", None)
        if calls is None:
            return func(params_str)
        try:
            args = json.loads(params_str) if isinstance(params_str, str) else params_str
        except Exception:
            args = {"_raw": str(params_str)[:200]}
        result = func(params_str)
        # 同时记录返回值：一方面支撑"模板化格式化"消融（关掉模板后需要把工具原始
        # 返回交给 LLM 复述），另一方面让评测脚本可以把最终答案里的数字与工具返回的
        # 数值集合做包含性校验，从而量化数值幻觉率。
        calls.append({
            "tool": func.__name__,
            "args": args,
            "result": result[:_TRACE_RESULT_LIMIT] if isinstance(result, str) else result,
        })
        return result
    return wrapper


query_tool_change_data = _traced_tool(query_tool_change_data)
query_stratum_data = _traced_tool(query_stratum_data)
calculate_tool_performance = _traced_tool(calculate_tool_performance)
recommend_tools = _traced_tool(recommend_tools)
compare_manufacturer_performance = _traced_tool(compare_manufacturer_performance)
analyze_stratum_wear_correlation = _traced_tool(analyze_stratum_wear_correlation)
query_opening_records = _traced_tool(query_opening_records)
query_cutter_position_stats = _traced_tool(query_cutter_position_stats)
query_tool_change_trend = _traced_tool(query_tool_change_trend)
query_position_stratum_impact = _traced_tool(query_position_stratum_impact)
query_tunneling_summary = _traced_tool(query_tunneling_summary)
query_tunneling_trend = _traced_tool(query_tunneling_trend)
query_tunneling_anomaly = _traced_tool(query_tunneling_anomaly)
query_tunneling_wear_correlation = _traced_tool(query_tunneling_wear_correlation)


def _new_usage_callback():
    """返回 (callbacks列表, 取用量的函数)。旧版 langchain 下降级为空实现。"""
    if UsageMetadataCallbackHandler is None:
        return [], lambda: {}
    handler = UsageMetadataCallbackHandler()
    return [handler], lambda: getattr(handler, "usage_metadata", {}) or {}


def _merge_usage(*usages) -> dict:
    """合并多次调用的 token 用量，按模型名聚合。"""
    merged = {}
    for usage in usages:
        for model, counts in (usage or {}).items():
            bucket = merged.setdefault(model, {})
            for key, value in (counts or {}).items():
                if isinstance(value, (int, float)):
                    bucket[key] = bucket.get(key, 0) + value
    return merged

# 可重试的错误关键词
_RETRYABLE_ERRORS = ("timeout", "connection", "rate limit", "overloaded", "503", "502")
_OLLAMA_RUNNER_ERRORS = (
    "llama runner process has terminated",
    "model runner has unexpectedly stopped",
    "runner process has terminated",
)

# 历史记录数据库连接（使用 Django 项目同一数据库）
# 从环境变量读取，默认使用 SQLite 文件（与 Django settings 中的 db 路径一致）
_HISTORY_DB_URL = os.environ.get(
    "LANGCHAIN_HISTORY_DB_URL",
    "sqlite:///langchain_history.db"
)


_DEFAULT_PROJECT_ID = os.environ.get("DEMO_PROJECT_ID", "demo-project")
PENETRATION_FORCE_UNIT = os.environ.get("AI_ASSISTANT_PENETRATION_FORCE_UNIT", "")


def _route_mode() -> str:
    return os.environ.get("AI_ASSISTANT_ROUTE_MODE", "hybrid").strip().lower()


_TRUTHY = {"1", "true", "yes", "on"}


def _flag_enabled(name: str, default: str = "0") -> bool:
    """统一的布尔型环境变量读取（实验开关与消融开关共用）。"""
    return os.environ.get(name, default).strip().lower() in _TRUTHY


# 消融 / 实验开关。全部默认关闭，线上行为与改造前一致。
#   AI_STRICT_AGENT        agent 模式下关闭规则直答的例外分支，使其成为纯净对照组
#   AI_ABLATE_TOOL_GROUP   关闭工具分组裁剪，一律注入全部 14 个工具
#   AI_ABLATE_TEMPLATE     关闭模板化格式化，规则路由改为把工具原始返回交给 LLM 复述
#   AI_ABLATE_MEMORY       关闭多轮记忆与追问合并，每轮独立
#   AI_TRACE_TOOL_RESULTS  在响应里带上工具原始返回（仅评测用，会显著增大响应体）
_ABLATION_FLAGS = (
    "AI_STRICT_AGENT",
    "AI_ABLATE_TOOL_GROUP",
    "AI_ABLATE_TEMPLATE",
    "AI_ABLATE_MEMORY",
    "AI_ASSISTANT_POLISH_DIRECT",
)


def current_config_signature() -> dict:
    """把本次请求生效的路由模式与消融开关写进返回值，使结果文件自证配置。"""
    signature = {"route_mode": _route_mode()}
    signature.update({name: _flag_enabled(name) for name in _ABLATION_FLAGS})
    return signature


def _to_json(params) -> str:
    """把 dict 或 str 统一转成 JSON 字符串传给工具函数。

    project_id 采用"缺失时填补"而非"无条件覆盖"：此前的写法会把调用方
    （包括 LLM）传入的 project_id 直接丢弃并替换为 _DEFAULT_PROJECT_ID，
    在多项目部署下会静默串数据。现只在未提供时才注入默认项目。
    """
    if isinstance(params, dict):
        params = dict(params)
        if not params.get('project_id'):
            params['project_id'] = _DEFAULT_PROJECT_ID
        return json.dumps(params, ensure_ascii=False)
    return params


# --- 把工具函数包装成 LangChain Tool ---

def _pct_to_float(value) -> float:
    try:
        if isinstance(value, str):
            value = value.strip().rstrip("%")
        return float(value)
    except Exception:
        return 0.0


def _with_analysis_payload(raw: str, kind: str) -> str:
    try:
        data = json.loads(raw)
    except Exception:
        return raw
    if not isinstance(data, dict) or data.get("error") or data.get("facts"):
        return raw

    facts = []
    highlights = []
    warnings = []
    summary = {}
    conclusion_hint = ""

    if kind == "tool_change":
        total = data.get("total_records", 0) or 0
        replaced = data.get("replaced_count", 0) or 0
        facts = [
            f"共查询到 {total} 条换刀检查记录",
            f"实际更换 {replaced} 次，更换率 {data.get('replacement_rate')}",
        ]
        wear = data.get("wear_distribution") or []
        if wear:
            highlights.append(f"最多的磨损状态为 {wear[0].get('wear_condition')}，共 {wear[0].get('count')} 条")
        positions = data.get("top_replaced_positions") or []
        if positions:
            highlights.append(f"更换最频繁刀位为 {positions[0].get('cutter_position_no')}，更换 {positions[0].get('replacement_count')} 次")
        summary = {"total_records": total, "replaced_count": replaced}
        conclusion_hint = "优先关注高频更换刀位和主要磨损状态，再结合地层与掘进参数判断原因。"

    elif kind == "manufacturer":
        manufacturers = data.get("manufacturers") or []
        total = data.get("total_records", 0) or 0
        facts = [f"共分析 {total} 条含厂家信息的换刀记录", f"覆盖 {data.get('manufacturer_count', len(manufacturers))} 个厂家"]
        if manufacturers:
            best = manufacturers[0]
            highlights.append(f"{best.get('manufacturer')} 异常磨损率最低，为 {best.get('abnormal_rate_pct')}%")
            for item in manufacturers[:5]:
                facts.append(f"{item.get('manufacturer')}：更换 {item.get('replaced_count')} 次，异常磨损率 {item.get('abnormal_rate_pct')}%")
        summary = {"total_records": total, "manufacturer_count": len(manufacturers)}
        conclusion_hint = "厂家排序优先参考异常磨损率，同时结合更换次数和成本，避免只看单次价格。"

    elif kind == "stratum_wear":
        strata = data.get("stratum_analysis") or []
        facts = [f"共形成 {len(strata)} 类地层-磨损统计结果"]
        if strata:
            top = strata[0]
            highlights.append(f"{top.get('stratum_name')} 的更换率最高，为 {top.get('replacement_rate')}")
            for item in strata[:5]:
                facts.append(f"{item.get('stratum_name')}：覆盖 {item.get('ring_count')} 环，更换 {item.get('replaced_count')} 次，更换率 {item.get('replacement_rate')}")
        summary = {"stratum_count": len(strata)}
        conclusion_hint = "更换率较高的地层可作为刀具选型、备件配置和掘进参数复核的重点区段。"

    elif kind == "opening":
        records = data.get("recent_records") or []
        total = data.get("total_openings", data.get("total", 0)) or 0
        facts = [
            f"共查询到 {total} 次开仓记录",
            f"平均开仓间隔为 {data.get('avg_rings_between_openings')} 环",
            f"平均开仓时长为 {data.get('avg_opening_duration_hours')} 小时",
        ]
        if records:
            highest = max(records, key=lambda item: _pct_to_float(item.get("abnormal_rate")))
            highlights.append(f"最近记录中环号 {highest.get('ring_no')} 的异常磨损率最高，为 {highest.get('abnormal_rate')}")
        summary = {"total_openings": total, "recent_count": len(records)}
        conclusion_hint = "开仓分析应同时看开仓间隔、换刀数量和异常磨损率，异常率高的开仓可回溯对应地层与掘进参数。"

    elif kind == "cutter_position":
        positions = data.get("top_positions") or []
        total = data.get("total_records", data.get("total", 0)) or 0
        facts = [f"共分析 {total} 条换刀记录"]
        if positions:
            top = positions[0]
            highlights.append(f"更换最频繁刀位为 {top.get('cutter_position_no')}，更换 {top.get('replacement_count')} 次")
            for item in positions[:5]:
                facts.append(f"刀位 {item.get('cutter_position_no')}：更换 {item.get('replacement_count')} 次，刀具类型 {item.get('tool_parent_type')}")
        summary = {"total_records": total, "position_count": len(positions)}
        conclusion_hint = "高频更换刀位应优先检查安装姿态、局部地层冲击、刀盘受力分布和相邻刀位联动磨损。"

    if not (facts or highlights or warnings):
        return raw
    data.update({
        "summary": summary,
        "facts": facts,
        "highlights": highlights,
        "warnings": warnings,
        "conclusion_hint": conclusion_hint,
    })
    return json.dumps(data, ensure_ascii=False)


@tool
def tool_query_tool_change_data(tool_type: str = "", ring_range: list = [], last_n_openings: int = 0, cutter_position_no: str = "") -> str:
    """查询换刀明细记录，支持按刀具类型、环号范围、刀位编号过滤，返回统计数据。
    tool_type 可选值: DISC/RIPPER/SCRAPER，不知道传空字符串。
    ring_range 格式: [起始环号, 结束环号]，不需要传空数组。
    last_n_openings: 查最近N次开仓的换刀数据，如"最近3次开仓"传3，默认0表示不限制。
    cutter_position_no: 刀位编号，如"1"、"S14R"、"MF10L"，查询特定刀位时传入，不需要传空字符串。
    """
    raw = query_tool_change_data(_to_json({"tool_type": tool_type, "ring_range": ring_range, "last_n_openings": last_n_openings, "cutter_position_no": cutter_position_no}))
    return _with_analysis_payload(raw, "tool_change")


@tool
def tool_query_stratum_data(ring_range: list = []) -> str:
    """查询地层分布信息，统计各地层类型的环数占比。
    ring_range 格式: [起始环号, 结束环号]，不需要传空数组。
    """
    return query_stratum_data(_to_json({"ring_range": ring_range}))


@tool
def tool_calculate_tool_performance(tool_numbers: list) -> str:
    """按刀具实例编号追溯单把刀的服役情况：安装环号、拆卸环号、服役环数、磨损检查历史。
    tool_numbers: 刀具实例编号列表，格式形如 "487-S14R-01"（环号-刀位-序号），指的是某一把具体的刀。
    注意区分三种编号，选错工具会答非所问：
      - 刀具实例编号（487-S14R-01）→ 用本工具；
      - 刀位编号（S14R、1、80A）→ 用 tool_query_cutter_position_stats；
      - 刀具型号（如"17寸单刃滚刀"）横向比较 → 用 tool_recommend_tools。
    在役未拆的刀不会给出服役环数（只知道下界），这是正确行为，不要自行推算。
    """
    return calculate_tool_performance(_to_json({"tool_numbers": tool_numbers}))


@tool
def tool_recommend_tools(
    stratum_types: list = [],
    tool_type: str = "",
    ring_range: list = [],
    max_unit_price: float = 0,
    top_n: int = 5,
) -> str:
    """刀具选型/备刀参考：在指定地层与环号范围内，按刀具型号的平均服役环数由高到低排序（服役越久越优）。
    stratum_types: 地层类型代码列表，必须使用系统代码，可选值 ["CLAY_SAND", "SOFT_HARD", "WEAK_GRANITE", "BEDROCK_PROTRUSION", "SOFT_SOIL", "BOULDER"]；不限定地层时传空数组。
    tool_type 可选值: DISC/RIPPER/SCRAPER，不知道传空字符串。
    ring_range 格式: [起始环号, 结束环号]，不需要传空数组。
    max_unit_price: 单价上限（元），不限价传 0。
    top_n: 返回条数，默认5。
    注意：排名依据的是历史平均服役环数（型号维度），不是对在役刀具剩余寿命的预测；样本量不足的型号会单独列在 insufficient_evidence 中，不要把它们当作推荐结果。
    """
    return recommend_tools(_to_json({
        "stratum_types": stratum_types,
        "tool_type": tool_type,
        "ring_range": ring_range,
        "max_unit_price": max_unit_price,
        "top_n": top_n,
    }))


@tool
def tool_compare_manufacturer_performance(tool_type: str = "", ring_range: list = []) -> str:
    """按厂家统计异常磨损率，横向对比不同厂家刀具的质量表现。适用于"哪个厂家好"、"厂家对比"等问题。
    tool_type 可选值: DISC/RIPPER/SCRAPER，不知道传空字符串。
    """
    raw = compare_manufacturer_performance(_to_json({"tool_type": tool_type, "ring_range": ring_range}))
    return _with_analysis_payload(raw, "manufacturer")


@tool
def tool_analyze_stratum_wear_correlation(tool_type: str = "", ring_range: list = []) -> str:
    """分析地层类型与刀具磨损的关联关系，找出哪种地层对刀具损耗最严重。适用于"地层影响"、"哪种地层最损刀"等问题。
    tool_type 可选值: DISC/RIPPER/SCRAPER，不知道传空字符串。
    ring_range 格式: [起始环号, 结束环号]，不需要传空数组。
    """
    raw = analyze_stratum_wear_correlation(_to_json({"tool_type": tool_type, "ring_range": ring_range}))
    return _with_analysis_payload(raw, "stratum_wear")


@tool
def tool_query_opening_records(ring_range: list = [], limit: int = 10) -> str:
    """查询开仓记录，返回每次开仓的环号、换刀统计、高频刀位等。适用于"最近几次开仓"、"平均多少环开一次仓"、"开仓时长"等问题。
    limit: 返回最近几次开仓，按环号从大到小排序。用户说"最近N次"就传N，默认10。"""
    raw = query_opening_records(_to_json({"ring_range": ring_range, "limit": limit}))
    return _with_analysis_payload(raw, "opening")


@tool
def tool_query_cutter_position_stats(tool_type: str = "", top_n: int = 10) -> str:
    """统计各刀位的磨损和更换情况，找出高频更换刀位。适用于"哪个刀位最容易坏"、"刀盘磨损分布"等问题。
    tool_type 可选值: DISC/RIPPER/SCRAPER，不知道传空字符串。
    """
    raw = query_cutter_position_stats(_to_json({"tool_type": tool_type, "top_n": top_n}))
    return _with_analysis_payload(raw, "cutter_position")


@tool
def tool_query_tool_change_trend(tool_type: str = "", interval: int = 50) -> str:
    """按环号区间统计换刀趋势，分析掘进过程中刀具损耗是否在增加。适用于"换刀频率有没有在增加"、"哪个阶段损耗最大"等问题。
    interval 为每段环数，默认50环一段。
    """
    return query_tool_change_trend(_to_json({"tool_type": tool_type, "interval": interval}))


@tool
def tool_query_position_stratum_impact(tool_type: str = "", ring_range: list = [], top_n: int = 10) -> str:
    """分析各刀位在不同地层下的更换次数，找出受地层影响最大的刀位。适用于"哪个刀位受地层影响最大"、"地层对哪个刀位磨损影响最严重"等问题。
    tool_type 可选值: DISC/RIPPER/SCRAPER，不知道传空字符串。
    ring_range 格式: [起始环号, 结束环号]，不需要传空数组。
    top_n: 返回前N个刀位，默认10。
    """
    return query_position_stratum_impact(_to_json({"tool_type": tool_type, "ring_range": ring_range, "top_n": top_n}))


@tool
def tool_query_tunneling_summary(ring_range: list = [], limit: int = 10) -> str:
    """查询掘进动态数据概览。适用于总推力、刀盘扭矩、刀盘转速、贯入力、最近掘进记录等问题。"""
    return query_tunneling_summary(_to_json({"ring_range": ring_range, "limit": limit}))


@tool
def tool_query_tunneling_trend(ring_range: list = [], interval: int = 50) -> str:
    """按环号区间统计掘进动态趋势。适用于掘进参数变化、趋势、阶段对比等问题。"""
    return query_tunneling_trend(_to_json({"ring_range": ring_range, "interval": interval}))


@tool
def tool_query_tunneling_anomaly(ring_range: list = [], threshold_k: float = 1.5) -> str:
    """查询掘进动态异常。适用于推力、扭矩、贯入力异常偏高或异常波动等问题。"""
    return query_tunneling_anomaly(_to_json({"ring_range": ring_range, "threshold_k": threshold_k}))


@tool
def tool_query_tunneling_wear_correlation(ring_range: list = [], interval: int = 50) -> str:
    """关联分析掘进动态、换刀磨损和地层数据。适用于推力/扭矩异常是否和换刀、磨损、地层有关的问题。"""
    return query_tunneling_wear_correlation(_to_json({"ring_range": ring_range, "interval": interval}))


TOOLS = [
    tool_query_tool_change_data,
    tool_query_stratum_data,
    tool_calculate_tool_performance,
    tool_recommend_tools,
    tool_compare_manufacturer_performance,
    tool_analyze_stratum_wear_correlation,
    tool_query_opening_records,
    tool_query_cutter_position_stats,
    tool_query_tool_change_trend,
    tool_query_position_stratum_impact,
    tool_query_tunneling_summary,
    tool_query_tunneling_trend,
    tool_query_tunneling_anomaly,
    tool_query_tunneling_wear_correlation,
]


TOOL_GROUPS = {
    "tool_change": [
        tool_query_tool_change_data,
        tool_query_tool_change_trend,
        tool_query_cutter_position_stats,
        tool_query_opening_records,
        tool_calculate_tool_performance,
        tool_recommend_tools,
    ],
    "opening": [
        tool_query_opening_records,
        tool_query_tool_change_data,
        tool_query_tool_change_trend,
    ],
    "position": [
        tool_query_cutter_position_stats,
        tool_query_position_stratum_impact,
        tool_query_tool_change_data,
    ],
    "manufacturer": [
        tool_compare_manufacturer_performance,
        tool_analyze_stratum_wear_correlation,
        tool_query_stratum_data,
    ],
    "stratum": [
        tool_query_stratum_data,
        tool_analyze_stratum_wear_correlation,
        tool_query_position_stratum_impact,
    ],
    "tunneling": [
        tool_query_tunneling_summary,
        tool_query_tunneling_trend,
        tool_query_tunneling_anomaly,
        tool_query_tunneling_wear_correlation,
    ],
}

class ToolAssistant:
    """刀具管理智能助手"""

    def __init__(self, model_name: str | None = None):
        self.llm_config = get_llm_config(model_name)
        self.llm = create_chat_model(model_name)

        self._prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder("chat_history"),   # Must match history_messages_key
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ])

        base_executor = self._create_executor(TOOLS)

        # 用 RunnableWithMessageHistory 包装，接管历史读写
        # session_id 对应每个用户，history_messages_key 必须与 prompt 中 MessagesPlaceholder 名称一致
        self._executor = RunnableWithMessageHistory(
            base_executor,
            self._get_session_history,
            input_messages_key="input",
            history_messages_key="chat_history",
        )

        # 保留 base_executor 引用，供流式接口的 astream_events 使用
        self._base_executor = base_executor
        self._executor_cache = {"all": base_executor}
        self._history_executor_cache = {"all": self._executor}

        # 内存缓存每用户最近一次注入的上下文消息（不持久化，避免历史膨胀）
        self._context_cache: dict[str, str] = {}

        logger.info(
            "ToolAssistant 初始化成功，provider=%s，model=%s，base_url=%s，历史DB=%s",
            self.llm_config.provider,
            self.llm_config.model,
            self.llm_config.base_url,
            _HISTORY_DB_URL,
        )

    def _create_executor(self, tools: list) -> AgentExecutor:
        agent = create_tool_calling_agent(self.llm, tools, self._prompt)
        return AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=False,
            max_iterations=6,
            handle_parsing_errors=True,
            return_intermediate_steps=True,
        )

    def _is_multi_source_query(self, query: str) -> bool:
        sources = [
            "换刀", "换刀明细", "磨损",
            "地层",
            "厂家", "厂商", "品牌",
            "刀位", "刀盘",
            "寿命", "累计推进",
            "备刀", "推荐",
            "掘进", "推力", "扭矩", "转速", "贯入力",
            "开仓",
        ]
        hit_count = sum(1 for word in sources if word in query)
        return hit_count >= 3 or ("结合" in query and hit_count >= 2) or ("综合" in query and hit_count >= 2)
    def _tool_group_for_query(self, query: str) -> str:
        if self._is_multi_source_query(query):
            return "all"
        if self._is_tunneling_query(query):
            return "tunneling"
        if self._is_tool_recommendation_query(query) or self._is_tool_performance_query(query):
            return "tool_change"
        if self._is_manufacturer_query(query):
            return "manufacturer"
        if self._is_position_stratum_query(query) or self._is_stratum_wear_query(query) or self._is_stratum_distribution_query(query):
            return "stratum"
        if self._is_opening_query(query):
            return "opening"
        if self._is_cutter_position_query(query):
            return "position"
        if self._is_change_trend_query(query) or self._is_tool_change_summary_query(query):
            return "tool_change"
        return "all"

    def _get_executor_for_query(self, query: str, with_history: bool = False):
        # 消融：关闭工具分组裁剪后一律注入全部 14 个工具，用于量化裁剪对
        # 工具选择准确率与 prompt token 的贡献。
        group = "all" if _flag_enabled("AI_ABLATE_TOOL_GROUP") else self._tool_group_for_query(query)
        if group == "all":
            return self._executor if with_history else self._base_executor

        cache = self._history_executor_cache if with_history else self._executor_cache
        if group not in cache:
            base_executor = self._create_executor(TOOL_GROUPS[group])
            if with_history:
                cache[group] = RunnableWithMessageHistory(
                    base_executor,
                    self._get_session_history,
                    input_messages_key="input",
                    history_messages_key="chat_history",
                )
            else:
                cache[group] = base_executor
            logger.info("AI Agent tool group selected: %s, tools=%s", group, len(TOOL_GROUPS[group]))
        return cache[group]

    def _friendly_error(self, error_msg: str) -> str:
        """把底层 LLM 异常转成前端可展示的稳定文案"""
        msg_lower = error_msg.lower()
        if any(part in msg_lower for part in _OLLAMA_RUNNER_ERRORS) or (
            "status code: 500" in msg_lower and "runner" in msg_lower
        ):
            return (
                "本地 Ollama 模型进程异常退出。请先重试一次；如果持续出现，"
                "建议重启 Ollama，或降低模型/上下文配置后再使用。"
            )
        if "timeout" in msg_lower:
            return "处理超时，请稍后重试或简化问题。"
        if "connection" in msg_lower:
            return "无法连接到 LLM 服务，请检查 Ollama 是否运行。"
        return f"处理出错：{error_msg}"

    def _build_direct_messages(self, user_query: str, context: dict = None):
        """非数据查询不走工具 Agent，避免小模型加载工具 schema 后上下文过重"""
        ctx_msg = self._build_context_message(context)
        system = (
            SYSTEM_PROMPT
            + "\n\n【当前模式】本轮问题不需要查询数据库或调用工具。"
              "请只基于专业知识和系统背景简洁回答，不要编造系统中的具体数据。"
        )
        human = f"{ctx_msg}\n\n{user_query}" if ctx_msg else user_query
        return [SystemMessage(content=system), HumanMessage(content=human)]

    def _verbalize_raw_tool_results(self, user_query: str, calls: list):
        """消融用：绕过 _format_* 模板，把工具原始返回直接交给 LLM 自行组织成回答。

        这条路径正是本系统主张要避免的做法——数值不再由确定性模板产出，而是由 LLM
        从 JSON 中复述，因此可用来量化"模板化格式化"对数值一致性的实际贡献。
        返回 (答案 或 None, token用量)；生成失败时回退到模板答案。
        """
        payload = "\n\n".join(
            f"工具 {c.get('tool')} 返回：\n{c.get('result')}"
            for c in (calls or []) if c.get("result")
        )
        if not payload:
            return None, {}
        callbacks, get_usage = _new_usage_callback()
        messages = [
            SystemMessage(content=(
                SYSTEM_PROMPT
                + "\n\n【当前模式】以下是工具查询到的原始结果，请据此直接回答用户问题。"
            )),
            HumanMessage(content=f"用户问题：\n{user_query}\n\n{payload}"),
        ]
        try:
            result = self.llm.invoke(
                messages, config={"callbacks": callbacks} if callbacks else None
            )
            text = result.content if hasattr(result, "content") else str(result)
            return (text.strip() or None), get_usage()
        except Exception as e:
            logger.warning("模板消融路径生成失败，回退模板答案：%s", e)
            return None, get_usage()

    def _direct_chat(self, user_query: str, context: dict = None):
        """返回 (答案, token用量)。"""
        callbacks, get_usage = _new_usage_callback()
        response = self.llm.invoke(
            self._build_direct_messages(user_query, context),
            config={"callbacks": callbacks} if callbacks else None,
        )
        text = response.content if hasattr(response, "content") else str(response)
        return text, get_usage()

    @staticmethod
    def _get_session_history(session_id: str):
        """为每个 session_id（user_id）返回对应的持久化历史对象。

        消融：AI_ABLATE_MEMORY=1 时返回进程内的一次性历史对象，等价于关闭多轮记忆，
        每轮请求都从空历史开始。
        """
        if _flag_enabled("AI_ABLATE_MEMORY"):
            from langchain_core.chat_history import InMemoryChatMessageHistory
            return InMemoryChatMessageHistory()
        return SQLChatMessageHistory(
            session_id=session_id,
            connection_string=_HISTORY_DB_URL,
        )

    def _build_context_message(self, context: dict) -> str | None:
        """把请求上下文转成注入消息，包含项目基本信息和实时数据快照"""
        if not context:
            return None
        parts = []

        # 基础信息
        if context.get("project_id"):
            parts.append(f"当前项目ID：{context['project_id']}")
        if context.get("project_name"):
            parts.append(f"项目名称：{context['project_name']}")
        if context.get("username"):
            parts.append(f"操作人：{context['username']}")
        if context.get("ring_range"):
            r = context["ring_range"]
            parts.append(f"用户关注的环号范围：{r[0]}～{r[1]}环")

        # 项目实时数据快照
        snap_parts = []
        if context.get("snapshot_total_openings") is not None:
            snap_parts.append(f"累计开仓 {context['snapshot_total_openings']} 次")
        if context.get("snapshot_latest_ring") not in (None, '未知', ''):
            snap_parts.append(f"最新环号 {context['snapshot_latest_ring']} 环")
        if context.get("snapshot_total_changes") is not None:
            snap_parts.append(f"换刀明细共 {context['snapshot_total_changes']} 条")
        if context.get("snapshot_total_replaced") is not None:
            snap_parts.append(f"实际更换 {context['snapshot_total_replaced']} 次")
        if context.get("snapshot_total_positions") is not None:
            snap_parts.append(f"刀位总数 {context['snapshot_total_positions']} 个")

        if snap_parts:
            parts.append("【项目数据概况】" + "，".join(snap_parts))

        return "【当前上下文】" + "；".join(parts) if parts else None

    # AI 追问参数的特征词
    _ASKING_PARAMS_KEYWORDS = (
        "请提供", "请指定", "请告知", "请输入", "请问", "您可以",
        "需要您", "能否提供", "请给出", "请确认",
    )

    def _is_asking_for_params(self, ai_message: str) -> bool:
        return any(kw in ai_message for kw in self._ASKING_PARAMS_KEYWORDS)

    def _try_merge_with_previous_question(self, user_query: str, user_id: str) -> str:
        """如果上一条 AI 消息是在追问参数，把原始问题和用户补充合并"""
        if _flag_enabled("AI_ABLATE_MEMORY"):
            return user_query
        try:
            history = self._get_session_history(user_id).messages
            if len(history) < 2:
                return user_query
            last_ai = history[-1]
            last_human = history[-2]
            from langchain_core.messages import AIMessage as AI, HumanMessage as HM
            if isinstance(last_ai, AI) and isinstance(last_human, HM):
                if self._is_asking_for_params(last_ai.content):
                    return f"{last_human.content}\n补充信息：{user_query}"
        except Exception:
            pass
        return user_query

    # 触发工具调用的关键词
    _DATA_QUERY_KEYWORDS = (
        "查询", "查一下", "分析", "统计", "换刀", "开仓", "磨损", "刀位",
        "厂家", "地层", "环号", "更换", "多少", "哪个", "最近", "趋势",
        "记录", "次数", "情况", "数据",
    )

    def _needs_tool_call(self, query: str) -> bool:
        return any(kw in query for kw in self._DATA_QUERY_KEYWORDS)

    def _context_params(self, user_query: str, context: dict = None, **extra) -> dict:
        ctx = context or {}
        params = {
            "project_id": ctx.get("project_id") or _DEFAULT_PROJECT_ID,
            "tool_type": self._infer_tool_type(user_query),
            "ring_range": ctx.get("ring_range") or self._extract_ring_range(user_query),
        }
        cutter_position_no = self._extract_cutter_position_no(user_query)
        if cutter_position_no:
            params["cutter_position_no"] = cutter_position_no
        params.update(extra)
        return params
    def _extract_cutter_position_no(self, query: str) -> str:
        match = re.search(r"([A-Za-z]+\d+[A-Za-z]*|\d+[A-Za-z]*)\s*(?:号)?\s*刀位", query, re.IGNORECASE)
        return match.group(1).upper() if match else ""

    def _tool_type_label(self, tool_type: str) -> str:
        return {"DISC": "滚刀", "SCRAPER": "刮刀", "RIPPER": "撕裂刀"}.get(tool_type or "", "")

    def _prepend_query_scope(self, answer: str, params: dict, user_query: str = "") -> str:
        scope = []
        project_id = params.get("project_id")
        if project_id and project_id in user_query:
            scope.append(f"项目：{project_id}")
        named_manufacturers = [name for name in ("铁建重工", "中铁装备", "海瑞克", "维尔特", "罗宾斯", "盾安重工") if name in user_query]
        if named_manufacturers:
            scope.append("对比厂家：" + "、".join(named_manufacturers))
        tool_label = self._tool_type_label(params.get("tool_type"))
        if tool_label:
            scope.append(f"刀具类型：{tool_label}")
        cutter_position_no = params.get("cutter_position_no")
        if cutter_position_no:
            scope.append(f"刀位：{cutter_position_no}")
        ring_range = params.get("ring_range") or []
        if len(ring_range) == 2:
            scope.append(f"环号范围：{ring_range[0]}-{ring_range[1]}")
        if "贯入力" in user_query and "贯入力" not in answer:
            scope.append("关注指标：贯入力")
        if not scope:
            return answer
        return "分析范围：" + "；".join(scope) + "。\n\n" + answer

    def _is_inventory_query(self, query: str) -> bool:
        return "库存" in query

    def _is_ambiguous_followup_query(self, query: str) -> bool:
        """短指代追问（"那它为什么更严重"）→ 请求澄清。

        实体守卫：句中含有具体业务对象时不算模糊追问——校准实验实测
        "这个项目一共换过多少把刀"（恰好 12 字且含"这个"）被误判为模糊而拒答。
        """
        compact = "".join(query.split())
        if len(compact) > 12 or not any(kw in compact for kw in ("那它", "这个", "那个", "为什么更严重")):
            return False
        entity_tokens = ("刀", "环", "仓", "地层", "厂家", "掘进", "项目", "推力", "扭矩", "贯入")
        return not any(token in compact for token in entity_tokens)

    def _extract_ring_range(self, query: str) -> list:
        # "第100环到第300环"这类两端都带"环"字的写法：旧模式要求数字紧邻"到"，
        # 会漏掉中间的"环"，落到单环分支得出 [100,100]（鲁棒性校准实测）
        match = re.search(r"第?\s*(\d+)\s*环?\s*(?:-|~|到|至)\s*第?\s*(\d+)\s*环", query)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            return [min(start, end), max(start, end)]
        match = re.search(r"(\d+)\s*(?:-|~|到|至)\s*(\d+)\s*环?", query)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            return [min(start, end), max(start, end)]

        single_match = re.search(r"(?:第\s*)?(\d+)\s*环", query)
        if single_match:
            ring = int(single_match.group(1))
            return [ring, ring]

        cn_digits = {
            "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
            "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
        }

        def parse_cn_number(value: str):
            value = value.strip()
            if not value:
                return None
            if value == "十":
                return 10
            if "十" in value:
                left, _, right = value.partition("十")
                tens = cn_digits.get(left, 1 if left == "" else None)
                ones = cn_digits.get(right, 0 if right == "" else None)
                if tens is None or ones is None:
                    return None
                return tens * 10 + ones
            total = 0
            for char in value:
                if char not in cn_digits:
                    return None
                total = total * 10 + cn_digits[char]
            return total

        cn_match = re.search(r"(?:第\s*)?([零〇一二两三四五六七八九十]{1,6})\s*环", query)
        if cn_match:
            ring = parse_cn_number(cn_match.group(1))
            if ring is not None:
                return [ring, ring]
        return []

    def _extract_limit(self, query: str, default: int = 10) -> int:
        match = re.search(r"(?:最近|前)\s*(\d+)\s*(?:次|条|个)", query)
        if match:
            return max(1, min(int(match.group(1)), 50))

        cn_match = re.search(r"(?:最近|近|前)\s*([一二两三四五六七八九十]+)\s*(?:次|条|个)", query)
        if not cn_match:
            return default

        cn_number = cn_match.group(1)
        digit_map = {
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
        }
        if cn_number == "十":
            value = 10
        elif cn_number.startswith("十"):
            value = 10 + digit_map.get(cn_number[1:], 0)
        elif "十" in cn_number:
            tens, ones = cn_number.split("十", 1)
            value = digit_map.get(tens, 1) * 10 + digit_map.get(ones, 0)
        else:
            value = digit_map.get(cn_number, default)
        return max(1, min(value, 50))

    def _extract_recent_ring_window(self, query: str, default: int = 100) -> int:
        match = re.search(r"(?:最近|近)\s*(\d+)\s*环", query)
        if match:
            return max(1, min(int(match.group(1)), 2000))
        cn_match = re.search(r"(?:最近|近)\s*([一二两三四五六七八九十百]+)\s*环", query)
        if not cn_match:
            return default
        cn = cn_match.group(1)
        digit_map = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
        if cn == "百":
            return 100
        if cn.endswith("百"):
            return max(1, min(digit_map.get(cn[:-1], 1) * 100, 2000))
        if "十" in cn:
            left, _, right = cn.partition("十")
            value = digit_map.get(left, 1 if not left else 0) * 10 + digit_map.get(right, 0)
            return max(1, min(value, 2000))
        return max(1, min(digit_map.get(cn, default), 2000))

    def _recent_ring_range(self, user_query: str, context: dict = None) -> list:
        window = self._extract_recent_ring_window(user_query, 100)
        params = {"project_id": (context or {}).get("project_id") or _DEFAULT_PROJECT_ID, "limit": 1}
        raw = query_opening_records(json.dumps(params, ensure_ascii=False))
        data = json.loads(raw)
        records = data.get("recent_records") or []
        if not records:
            return []
        try:
            latest_ring = int(records[0].get("ring_no"))
        except Exception:
            return []
        return [max(1, latest_ring - window + 1), latest_ring]

    def _is_recent_ring_tool_change_query(self, query: str) -> bool:
        return bool(re.search(r"(?:最近|近)\s*(?:\d+|[一二两三四五六七八九十百]+)\s*环", query)) and any(
            kw in query for kw in ("换刀", "更换", "磨损", "刀位")
        ) and not any(kw in query for kw in ("每", "趋势", "分段"))
    def _is_stratum_wear_query(self, query: str) -> bool:
        return "地层" in query and any(kw in query for kw in ("磨损", "关联", "影响", "损刀"))

    def _is_manufacturer_query(self, query: str) -> bool:
        known_manufacturers = ("铁建重工", "中铁装备", "海瑞克", "维尔特", "罗宾斯", "盾安重工")
        return (
            any(kw in query for kw in ("厂家", "厂商", "品牌"))
            or sum(1 for name in known_manufacturers if name in query) >= 1
        ) and any(kw in query for kw in (
            "性能", "对比", "质量", "表现", "好", "差", "异常", "成本",
            # 补：计数/概览类问法。题库用例「有几家刀具厂家的数据」原先只满足前半条件，
            # 实测 10/10 落到 Agent 路径——这是"写了用例却到不了分支"的一例。
            "几家", "多少家", "数据", "情况", "统计",
        ))

    def _is_position_stratum_query(self, query: str) -> bool:
        return "刀位" in query and "地层" in query and any(kw in query for kw in ("影响", "关联", "损耗", "磨损"))

    def _is_cutter_position_query(self, query: str) -> bool:
        return "刀位" in query and any(
            kw in query for kw in ("排行", "排名", "最", "容易", "高频", "磨损", "更换", "风险", "分布")
        )

    def _is_opening_query(self, query: str) -> bool:
        has_opening = "开仓" in query or ("开" in query and "仓" in query)
        return has_opening and any(kw in query for kw in ("最近", "记录", "平均", "间隔", "多少", "时长", "情况", "异常"))

    def _is_opening_stratum_change_query(self, query: str) -> bool:
        return "开仓" in query and "地层" in query and any(
            kw in query for kw in ("换刀", "刀位", "异常", "联动", "结合", "对应")
        )
    def _is_change_trend_query(self, query: str) -> bool:
        return any(kw in query for kw in ("趋势", "阶段", "频率", "增加", "下降", "变化")) and any(
            kw in query for kw in ("换刀", "更换", "磨损")
        )

    def _is_tool_change_summary_query(self, query: str) -> bool:
        return any(kw in query for kw in ("换刀", "更换", "磨损", "损坏", "撕裂刀", "滚刀", "刮刀")) and any(
            kw in query for kw in ("统计", "情况", "数据", "多少", "分布", "汇总")
        )

    def _is_stratum_distribution_query(self, query: str) -> bool:
        return "地层" in query and any(kw in query for kw in ("分布", "类型", "占比", "有哪些", "什么地层", "主要"))

    def _is_tunneling_query(self, query: str) -> bool:
        return any(kw in query for kw in (
            "掘进", "动态", "推力", "扭矩", "刀盘转速", "转速", "贯入力", "贯入度",
            "thrust", "torque", "penetration", "cutterhead"
        ))

    def _is_tunneling_trend_query(self, query: str) -> bool:
        return self._is_tunneling_query(query) and any(kw in query for kw in (
            "趋势", "变化", "阶段", "分段", "上升", "下降", "波动", "分析", "情况", "怎么样"
        ))

    def _is_tunneling_anomaly_query(self, query: str) -> bool:
        return self._is_tunneling_query(query) and any(kw in query for kw in (
            "异常", "偏高", "偏低", "过高", "过低", "突增", "波动", "风险"
        ))

    def _is_recent_abnormal_wear_cause_query(self, query: str) -> bool:
        return any(kw in query for kw in ("异常磨损", "磨损原因", "可能原因", "原因分析")) and any(
            # 补「近期/最近」：该分支本身就以最近 100 环为窗口，时间限定与地层/掘进限定同样合格
            kw in query for kw in ("地层", "掘进", "换刀", "开仓", "近期", "最近")
        )

    def _is_opening_efficiency_query(self, query: str) -> bool:
        if any(kw in query for kw in ("检查一把", "更换一把")) and any(
            kw in query for kw in ("多久", "多长时间", "耗时", "时长", "效率", "小时", "平均")
        ):
            # 「平均更换一把刀多久」这类问句不带"开仓"二字，但问的就是开仓作业效率。
            # 必须同时带时间/效率类限定词——"更换一把X"本身是通用量词短语，
            # 无条件短路会把「更换一把刀的成本」「更换一把滚刀要备哪些件」
            # 「检查一把刀的标准流程」全部劫到本分支（本分支排在链上第 4 位，
            # 压在 tool_recommendation 与 tool_performance 之前）。
            return True
        return "开仓" in query and any(kw in query for kw in (
            "效率", "检查一把", "更换一把", "检查刀具数量", "更换刀具数量", "检查数", "更换数", "多长时间"
        ))

    def _is_tool_recommendation_query(self, query: str) -> bool:
        return any(kw in query for kw in ("备刀", "备件", "采购", "库存", "推荐", "准备", "下一阶段")) and any(
            kw in query for kw in ("刀", "刀具", "刀位", "厂家", "地层", "换刀", "型号", "建议")
        )

    def _is_tool_performance_query(self, query: str) -> bool:
        return any(kw in query for kw in ("寿命", "性能", "耐用", "平均推进", "平均寿命", "服役", "表现")) and (
            any(kw in query for kw in ("刀", "刀具", "刀号", "编号", "刀位"))
            # 补：实例编号本身（环号-刀位-序号，如 487-S14R-01）已足够表明这是单刀追溯，
            # 不必再要求问句里出现"刀"字。分支内部仍会校验能否抽到编号，抽不到自然下沉。
            or bool(re.search(r"\d+-[A-Za-z0-9]+-\d+", query))
        )

    def _is_tunneling_wear_correlation_query(self, query: str) -> bool:
        return self._is_tunneling_query(query) and any(kw in query for kw in (
            "换刀", "磨损", "刀具", "地层", "原因", "影响", "关联", "有关", "导致",
        ))

    def _infer_tool_type(self, query: str) -> str:
        if any(kw in query for kw in ("滚刀", "DISC")):
            return "DISC"
        if any(kw in query for kw in ("刮刀", "SCRAPER")):
            return "SCRAPER"
        if any(kw in query for kw in ("切刀", "先行刀", "撕裂刀", "RIPPER")):
            return "RIPPER"
        return ""

    def _format_recommend_tools_answer(self, raw: str) -> str:
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("error"):
            return f"备刀建议生成失败：{data['error']}"
        items = data if isinstance(data, list) else data.get("recommendations", []) if isinstance(data, dict) else []
        payload = data if isinstance(data, dict) else {}
        if not items:
            message = payload.get("message")
            return message or "未找到可用于备刀建议的刀具数据。"

        criteria = payload.get("criteria") or {}
        scope_bits = []
        stratum = criteria.get("stratum_types")
        if stratum and stratum != "全部":
            scope_bits.append(f"地层 {'、'.join(stratum) if isinstance(stratum, list) else stratum}")
        if criteria.get("tool_type") and criteria["tool_type"] != "全部":
            scope_bits.append(f"刀具类型 {criteria['tool_type']}")
        ring_range = criteria.get("ring_range")
        if isinstance(ring_range, list) and len(ring_range) == 2:
            scope_bits.append(f"环号 {ring_range[0]}-{ring_range[1]}")
        if criteria.get("max_unit_price_yuan"):
            scope_bits.append(f"单价不高于 {criteria['max_unit_price_yuan']:.0f} 元")

        lines = ["刀具选型参考", ""]
        lines.append(f"筛选范围：{'；'.join(scope_bits) if scope_bits else '全部数据（未附加筛选条件）'}")
        lines.append(
            f"排序依据：型号维度的平均服役环数（下次同刀位换刀环号 − 本次安装环号），由高到低；"
            f"参与排名的型号需至少有 {criteria.get('min_samples', 3)} 把已完成服役的刀具。"
        )
        lines.append("")
        lines.append("排名：")
        for item in items[:8]:
            extras = []
            if item.get("manufacturer"):
                extras.append(f"厂家 {item['manufacturer']}")
            if item.get("unit_price_yuan") is not None:
                extras.append(f"单价 {item['unit_price_yuan']:.0f} 元")
            if item.get("cost_per_ring_yuan") is not None:
                extras.append(f"每环成本 {item['cost_per_ring_yuan']:.2f} 元")
            if item.get("inventory") is not None:
                extras.append(f"库存 {item['inventory']}")
            suffix = f"（{'，'.join(extras)}）" if extras else ""
            lines.append(
                f"{item.get('rank', '-')}. {item.get('tool_type_name') or '未登记型号'}"
                f"[{item.get('tool_parent_type') or '未知类型'}]："
                f"安装 {item.get('installed_count', 0)} 把，已完成服役 "
                f"{item.get('completed_service_count', 0)} 把，平均服役 "
                f"{item.get('avg_service_rings')} 环"
                f"（{item.get('min_service_rings')}~{item.get('max_service_rings')} 环）{suffix}"
            )

        insufficient = payload.get("insufficient_evidence") or []
        if insufficient:
            lines.append("")
            lines.append("样本量不足、未参与排名：")
            for item in insufficient[:5]:
                lines.append(
                    f"- {item.get('tool_type_name') or '未登记型号'}："
                    f"安装 {item.get('installed_count', 0)} 把，"
                    f"仅 {item.get('completed_service_count', 0)} 把已完成服役"
                )

        for warning in (payload.get("warnings") or [])[:4]:
            lines.append("")
            lines.append(f"提示：{warning}")

        note = payload.get("note")
        lines.extend([
            "",
            note or "平均服役环数反映历史表现，不构成剩余寿命预测。",
            "建议与近期高频更换刀位、异常磨损率较高的开仓记录交叉校验后再确定备刀方案。",
        ])
        return "\n".join(lines)

    def _format_tool_performance_answer(self, raw: str) -> str:
        data = json.loads(raw)
        if data.get("error"):
            return f"刀具服役追溯失败：{data['error']}"
        tools = data.get("tools") or []
        if not tools:
            not_found = data.get("not_found") or []
            if not_found:
                return (
                    f"未找到编号 {'、'.join(not_found)} 的换刀记录。"
                    "刀具实例编号的格式形如 487-S14R-01（环号-刀位-序号）；"
                    "若你要查的是刀位（如 S14R）请直接问该刀位的更换情况。"
                )
            return "未找到指定刀具的服役记录。"

        lines = ["刀具服役追溯", ""]
        for item in tools[:10]:
            head = f"{item.get('tool_number')}（刀位 {item.get('cutter_position_no') or '未知'}"
            if item.get("tool_type_name"):
                head += f"，型号 {item['tool_type_name']}"
            head += "）"
            lines.append(head)
            lines.append(f"- 安装环号：{item.get('install_ring_no')}"
                         + ("（由继承记录推断，可能偏晚）" if item.get("install_ring_inferred") else ""))
            if item.get("status") == "已拆下":
                lines.append(f"- 拆卸环号：{item.get('removal_ring_no')}")
                lines.append(f"- 服役环数：{item.get('service_rings')} 环")
            else:
                lines.append("- 当前状态：在役，尚未拆下，服役环数只知道下界，暂不给出数值")
            lines.append(
                f"- 检查记录：{item.get('inspection_count', 0)} 次，"
                f"其中异常磨损 {item.get('abnormal_inspection_count', 0)} 次"
            )
            if item.get("manufacturer"):
                lines.append(f"- 厂家：{item['manufacturer']}")
            lines.append("")

        for warning in (data.get("warnings") or [])[:3]:
            lines.append(f"提示：{warning}")
            lines.append("")

        lines.append(
            "说明：服役环数 = 拆卸环号 − 安装环号。在役刀具属于右删失样本，"
            "不可与已拆下的刀直接比较寿命。要横向比较型号请用刀具选型参考。"
        )
        return "\n".join(lines)

    def _format_opening_efficiency_answer(self, raw: str) -> str:
        data = json.loads(raw)
        if data.get("error"):
            return f"开仓效率统计失败：{data['error']}"
        records = data.get("recent_records", []) or []
        if not records:
            return data.get("message", "未找到可用于效率统计的开仓记录。")

        rows = []
        for item in records:
            duration = item.get("opening_duration")
            # 以明细派生值为准：checked_tool_count / replaced_tool_count 是开仓表上
            # 的手填字段，全系统只读不写、长期与实际明细行数不一致；而且原来的 or 链
            # 会把合法的 0 当成"没填"继续向后取值。
            checked = item.get("tool_change_total")
            if checked is None:
                checked = item.get("checked_tool_count")
            replaced = item.get("tool_change_replaced")
            if replaced is None:
                replaced = item.get("replaced_tool_count")
            checked = checked or 0
            replaced = replaced or 0
            try:
                duration = float(duration) if duration is not None else None
            except Exception:
                duration = None
            check_hours = round(duration / checked, 2) if duration and checked else None
            replace_hours = round(duration / replaced, 2) if duration and replaced else None
            rows.append({"item": item, "checked": checked, "replaced": replaced, "check_hours": check_hours, "replace_hours": replace_hours})

        valid_check = [r["check_hours"] for r in rows if r["check_hours"] is not None]
        valid_replace = [r["replace_hours"] for r in rows if r["replace_hours"] is not None]
        avg_check = round(sum(valid_check) / len(valid_check), 2) if valid_check else "暂无"
        avg_replace = round(sum(valid_replace) / len(valid_replace), 2) if valid_replace else "暂无"

        lines = [
            f"开仓作业效率统计：本次分析最近 {len(records)} 次开仓。",
            "",
            "结论：",
            f"- 平均检查一把刀约 {avg_check} 小时；平均更换一把刀约 {avg_replace} 小时。",
            "",
            "关键依据：",
        ]
        for r in rows[:8]:
            item = r["item"]
            lines.append(
                f"- 环号 {item.get('ring_no')}：开仓 {item.get('opening_duration') if item.get('opening_duration') is not None else '暂无'} 小时，"
                f"检查 {r['checked']} 把，更换 {r['replaced']} 把，"
                f"检查效率 {r['check_hours'] if r['check_hours'] is not None else '暂无'} 小时/把，"
                f"更换效率 {r['replace_hours'] if r['replace_hours'] is not None else '暂无'} 小时/把。"
            )
        lines.extend([
            "",
            "建议：检查效率异常偏低时，优先核对开仓组织、刀具检查流程和异常刀位集中度；更换效率异常偏低时，重点看高频刀位、备刀准备和吊装/拆装耗时。",
        ])
        return "\n".join(lines)

    def _format_stratum_wear_answer(self, raw: str) -> str:
        data = json.loads(raw)
        if data.get("error"):
            return f"地层磨损关联分析失败：{data['error']}"
        if data.get("stratum_count", 0) == 0:
            return data.get("message", "未找到地层与磨损的关联数据。")

        rows = data.get("stratum_analysis", [])
        if not rows:
            return "未找到可用的地层磨损分析结果。"

        top = rows[0]
        lines = [
            f"已完成地层类型与磨损情况的关联分析，共识别 {data.get('stratum_count', len(rows))} 种地层。",
            "",
            f"磨损关联最显著的地层是：{top.get('stratum_name', top.get('stratum_type'))}（{top.get('stratum_type')}），更换率 {top.get('replacement_rate')}，关联记录 {top.get('total_records')} 条，实际更换 {top.get('replaced_count')} 次。",
            "",
            "排名前几的地层：",
        ]

        for index, item in enumerate(rows[:5], start=1):
            wear = item.get("top_wear_conditions") or []
            wear_text = "、".join(
                f"{w.get('wear_condition')} {w.get('count')}次"
                for w in wear
                if w.get("wear_condition") is not None
            ) or "无明显磨损类型"
            lines.append(
                f"{index}. {item.get('stratum_name', item.get('stratum_type'))}："
                f"更换率 {item.get('replacement_rate')}，"
                f"记录 {item.get('total_records')} 条，"
                f"主要磨损：{wear_text}"
            )

        positions = top.get("top_replaced_positions") or []
        if positions:
            pos_text = "、".join(
                f"{p.get('position')}（{p.get('count')}次）"
                for p in positions
            )
            lines.extend(["", f"在最高风险地层下，高频更换刀位主要是：{pos_text}。"])

        lines.extend([
            "",
            "结论：更换率越高，说明该地层与刀具损耗的关联更强，应优先在这些地层区间加强刀具检查、备品配置和掘进参数监控。",
        ])
        return "\n".join(lines)

    def _format_tool_change_answer(self, raw: str, ring_range: list = None) -> str:
        data = json.loads(raw)
        if data.get("error"):
            return f"换刀数据查询失败：{data['error']}"
        if data.get("total_records", 0) == 0:
            return data.get("message", "未找到符合条件的换刀记录。")

        lines = [
            f"换刀数据汇总{'（环号 ' + str(ring_range[0]) + '-' + str(ring_range[1]) + '）' if ring_range else ''}：共 {data.get('total_records')} 条记录，实际更换 {data.get('replaced_count')} 次，更换率 {data.get('replacement_rate')}。",
            "",
            "磨损情况分布：",
        ]
        for item in data.get("wear_distribution", [])[:8]:
            lines.append(f"- {item.get('wear_condition')}：{item.get('count')} 次")

        positions = data.get("top_replaced_positions") or []
        if positions:
            lines.extend(["", "高频更换刀位："])
            for pos in positions:
                lines.append(f"- {pos.get('cutter_position_no')}：{pos.get('replacement_count')} 次")
        return "\n".join(lines)

    def _format_manufacturer_answer(self, raw: str) -> str:
        data = json.loads(raw)
        if data.get("error"):
            return f"厂家性能对比失败：{data['error']}"
        if data.get("total_records", 0) == 0:
            return data.get("message", "未找到含厂家信息的换刀记录。")

        manufacturers = data.get("manufacturers", [])
        lines = [
            f"厂家性能对比：共分析 {data.get('total_records')} 条含厂家记录，覆盖 {data.get('manufacturer_count', len(manufacturers))} 个厂家。",
            "",
            "按异常磨损率从低到高排序：",
        ]
        for index, item in enumerate(manufacturers[:8], start=1):
            avg_cost = item.get("avg_cost_per_change_yuan")
            cost_text = f"，平均成本 {avg_cost} 元/次" if avg_cost is not None else ""
            lines.append(
                f"{index}. {item.get('manufacturer')}：异常磨损率 {item.get('abnormal_rate_pct')}%，"
                f"更换 {item.get('replaced_count')} 次，正常磨损 {item.get('normal_wear_count')} 次，"
                f"异常磨损 {item.get('abnormal_wear_count')} 次{cost_text}"
            )
        if manufacturers:
            best = manufacturers[0]
            lines.extend(["", f"结论：当前数据下 {best.get('manufacturer')} 的异常磨损率最低，综合表现相对更好。"])
        return "\n".join(lines)

    def _format_opening_answer(self, raw: str) -> str:
        data = json.loads(raw)
        if data.get("error"):
            return f"开仓记录查询失败：{data['error']}"
        if data.get("total_openings", data.get("total", 0)) == 0:
            return data.get("message", "未找到开仓记录。")

        records = data.get("recent_records", []) or []
        total_openings = data.get("total_openings", data.get("total", 0))
        avg_interval = data.get("avg_rings_between_openings")
        avg_duration = data.get("avg_opening_duration_hours")

        lines = [
            f"开仓记录分析：共查询到 {total_openings} 次开仓，本次返回最近 {len(records)} 次。",
            f"平均开仓间隔 {avg_interval if avg_interval is not None else '暂无'} 环；平均开仓时长 {avg_duration if avg_duration is not None else '暂无'} 小时。",
        ]

        if records:
            highest_abnormal = max(records, key=lambda item: _pct_to_float(item.get("abnormal_rate")))
            highest_replaced = max(records, key=lambda item: int(item.get("tool_change_replaced") or 0))
            lines.extend([
                "",
                "关键发现：",
                f"- 异常磨损率最高：环号 {highest_abnormal.get('ring_no')}，异常率 {highest_abnormal.get('abnormal_rate')}。",
                f"- 换刀数量最多：环号 {highest_replaced.get('ring_no')}，更换 {highest_replaced.get('tool_change_replaced')} 把。",
                "",
                "最近开仓明细：",
            ])

        for index, item in enumerate(records[:10], start=1):
            positions = item.get("top_replaced_positions") or []
            positions_text = "、".join(str(p) for p in positions if p) or "暂无"
            wear_distribution = item.get("wear_distribution") or {}
            wear_text = "、".join(
                f"{name} {count}次" for name, count in list(wear_distribution.items())[:3] if name
            ) or "暂无"
            lines.append(
                f"{index}. 环号 {item.get('ring_no')}：开仓时间 {item.get('open_time') or '暂无'}，"
                f"距上次 {item.get('rings_between_openings') if item.get('rings_between_openings') is not None else '暂无'} 环，"
                f"时长 {item.get('opening_duration') if item.get('opening_duration') is not None else '暂无'} 小时，"
                f"换刀 {item.get('tool_change_replaced')}/{item.get('tool_change_total')}，"
                f"更换率 {item.get('replacement_rate')}，异常率 {item.get('abnormal_rate')}，"
                f"高频刀位 {positions_text}，主要磨损 {wear_text}。"
            )

        if records:
            risk_records = [r for r in records if _pct_to_float(r.get("abnormal_rate")) >= 30]
            if risk_records:
                lines.extend(["", "需要关注："])
                for item in risk_records[:3]:
                    lines.append(
                        f"- 环号 {item.get('ring_no')} 异常率 {item.get('abnormal_rate')}，建议回看该环段地层、推力/扭矩变化和高频刀位 {('、'.join(item.get('top_replaced_positions') or []) or '暂无')}。"
                    )
            else:
                lines.extend(["", "需要关注：最近记录未出现异常率超过 30% 的开仓，优先跟踪换刀数量较高的开仓。"])

        return "\n".join(lines)
    def _format_opening_stratum_change_answer(self, opening_raw: str, context: dict = None) -> str:
        data = json.loads(opening_raw)
        if data.get("error"):
            return f"开仓-地层-换刀联动分析失败：{data['error']}"
        records = data.get("recent_records", []) or []
        if not records:
            return data.get("message", "未找到可用于联动分析的开仓记录。")

        rows = []
        project_id = (context or {}).get("project_id") or _DEFAULT_PROJECT_ID
        for item in records:
            try:
                ring_no = int(item.get("ring_no"))
            except Exception:
                continue
            try:
                last_ring = int(item.get("last_ring_no")) if item.get("last_ring_no") else None
            except Exception:
                last_ring = None
            start_ring = last_ring + 1 if last_ring is not None else ring_no
            ring_range = [min(start_ring, ring_no), max(start_ring, ring_no)]
            stratum_raw = query_stratum_data(json.dumps({"project_id": project_id, "ring_range": ring_range}, ensure_ascii=False))
            stratum = json.loads(stratum_raw)
            distribution = stratum.get("stratum_distribution") or {}
            strata_text = "、".join(
                f"{name} {count}环"
                for name, count in sorted(distribution.items(), key=lambda kv: kv[1], reverse=True)[:3]
            ) or "暂无地层数据"
            rows.append({"item": item, "ring_range": ring_range, "strata": strata_text})

        rows.sort(key=lambda row: _pct_to_float(row["item"].get("abnormal_rate")), reverse=True)
        high_rows = [row for row in rows if _pct_to_float(row["item"].get("abnormal_rate")) >= 30] or rows[:5]

        lines = [
            f"开仓-地层-换刀联动分析：共查询到 {data.get('total_openings')} 次开仓，本次分析最近 {len(records)} 次。",
            f"平均开仓间隔 {data.get('avg_rings_between_openings')} 环；平均开仓时长 {data.get('avg_opening_duration_hours')} 小时。",
            "",
            "关键发现：",
        ]
        if rows:
            top = rows[0]["item"]
            top_positions = "、".join(top.get("top_replaced_positions") or []) or "暂无"
            lines.append(f"- 异常磨损率最高的是环号 {top.get('ring_no')}，异常率 {top.get('abnormal_rate')}，高频刀位 {top_positions}。")
            repeated_positions = {}
            for row in high_rows:
                for pos in row["item"].get("top_replaced_positions") or []:
                    repeated_positions[pos] = repeated_positions.get(pos, 0) + 1
            repeated_text = "、".join(
                f"{pos}({count}次)" for pos, count in sorted(repeated_positions.items(), key=lambda kv: kv[1], reverse=True)[:5]
            ) or "暂无"
            lines.append(f"- 高异常开仓中重复出现的高频刀位：{repeated_text}。")

        lines.extend(["", "高异常开仓对应地层与刀位："])
        for index, row in enumerate(high_rows[:8], start=1):
            item = row["item"]
            positions = "、".join(item.get("top_replaced_positions") or []) or "暂无"
            wear = item.get("wear_distribution") or {}
            wear_text = "、".join(f"{name} {count}次" for name, count in list(wear.items())[:3] if name) or "暂无"
            lines.append(
                f"{index}. 环号 {item.get('ring_no')}（环段 {row['ring_range'][0]}-{row['ring_range'][1]}）："
                f"异常率 {item.get('abnormal_rate')}，换刀 {item.get('tool_change_replaced')}/{item.get('tool_change_total')}，"
                f"高频刀位 {positions}，对应地层 {row['strata']}，主要磨损 {wear_text}。"
            )

        lines.extend([
            "",
            "结论：异常率高的开仓应优先回看对应环段地层变化和重复出现的高频刀位；同一刀位在多个高异常开仓反复出现时，优先检查该刀位安装、相邻刀位联动和对应地层冲击。",
        ])
        return "\n".join(lines)
    def _format_cutter_position_answer(self, raw: str) -> str:
        data = json.loads(raw)
        if data.get("error"):
            return f"刀位统计失败：{data['error']}"
        if data.get("total_records", data.get("total", 0)) == 0:
            return data.get("message", "未找到换刀记录。")

        lines = [
            f"刀位风险排行：共分析 {data.get('total_records')} 条记录。",
            "",
            "高频更换刀位：",
        ]
        for index, item in enumerate(data.get("top_positions", [])[:10], start=1):
            wear = item.get("wear_distribution") or []
            wear_text = "、".join(f"{w.get('wear_condition')} {w.get('count')}次" for w in wear[:3])
            lines.append(
                f"{index}. {item.get('cutter_position_no')}：更换 {item.get('replacement_count')} 次，"
                f"刀具类型 {item.get('tool_parent_type') or '未知'}，主要磨损：{wear_text or '无'}"
            )
        return "\n".join(lines)

    def _format_trend_answer(self, raw: str) -> str:
        data = json.loads(raw)
        if data.get("error"):
            return f"换刀趋势分析失败：{data['error']}"
        if data.get("total", 1) == 0:
            return data.get("message", "未找到换刀记录。")

        lines = [
            f"换刀趋势分析：环号范围 {data.get('ring_range')}，按 {data.get('interval')} 环/段统计，整体趋势为{data.get('trend')}。",
            "",
            "分段结果：",
        ]
        for seg in data.get("segments", [])[:12]:
            lines.append(
                f"- {seg.get('ring_range')}：记录 {seg.get('total')} 条，更换 {seg.get('replaced')} 次，更换率 {seg.get('replacement_rate')}"
            )
        return "\n".join(lines)

    def _format_position_stratum_answer(self, raw: str) -> str:
        data = json.loads(raw)
        if data.get("error"):
            return f"刀位-地层影响分析失败：{data['error']}"
        if data.get("total", 1) == 0:
            return data.get("message", "未找到换刀记录。")

        lines = ["刀位受地层影响排行：", ""]
        for index, item in enumerate(data.get("top_positions", [])[:10], start=1):
            by_stratum = item.get("by_stratum") or {}
            strata = "、".join(f"{name} {count}次" for name, count in list(by_stratum.items())[:4])
            lines.append(f"{index}. {item.get('position')}：合计 {item.get('total')} 次，地层分布：{strata}")
        return "\n".join(lines)

    def _format_stratum_distribution_answer(self, raw: str) -> str:
        data = json.loads(raw)
        if data.get("error"):
            return f"地层分布查询失败：{data['error']}"
        if data.get("total_rings", 0) == 0:
            return data.get("message", "未找到符合条件的地层数据。")

        lines = [
            f"地层分布：共 {data.get('total_rings')} 环，范围：{data.get('ring_range')}。",
            "",
            "各地层类型数量：",
        ]
        distribution = data.get("stratum_distribution", {})
        for name, count in sorted(distribution.items(), key=lambda kv: kv[1], reverse=True):
            lines.append(f"- {name}：{count} 环")
        return "\n".join(lines)

    def _format_metric_stats(self, name: str, stats: dict, unit: str) -> str:
        avg = stats.get("avg")
        min_value = stats.get("min")
        max_value = stats.get("max")
        if avg is None and min_value is None and max_value is None:
            return f"- {name}：暂无有效数据"
        parts = []
        if avg is not None:
            parts.append(f"平均 {round(float(avg), 3)}{unit}")
        if min_value is not None:
            parts.append(f"最小 {round(float(min_value), 3)}{unit}")
        if max_value is not None:
            parts.append(f"最大 {round(float(max_value), 3)}{unit}")
        return f"- {name}：" + "，".join(parts)

    def _format_penetration_force(self, value) -> str:
        if value is None:
            return "暂无"
        unit = PENETRATION_FORCE_UNIT.strip()
        suffix = unit if unit else "（原始值）"
        return f"{round(float(value), 3)}{suffix}"

    def _format_analysis_payload_answer(self, title: str, data: dict) -> str | None:
        if not (data.get("facts") or data.get("highlights") or data.get("warnings")):
            return None
        lines = [title]
        if data.get("highlights"):
            lines.extend(["", "关键发现："])
            lines.extend(f"- {item}" for item in data.get("highlights", [])[:6])
        if data.get("facts"):
            lines.extend(["", "数据依据："])
            lines.extend(f"- {item}" for item in data.get("facts", [])[:8])
        if data.get("warnings"):
            lines.extend(["", "注意事项："])
            lines.extend(f"- {item}" for item in data.get("warnings", [])[:4])
        if data.get("conclusion_hint"):
            lines.extend(["", f"结论：{data.get('conclusion_hint')}"])
        return "\n".join(lines)

    def _should_polish_direct_answer(self) -> bool:
        return os.environ.get("AI_ASSISTANT_POLISH_DIRECT", "false").strip().lower() not in {
            "0", "false", "no", "off"
        }

    def _must_preserve_direct_answer(self, structured_answer: str) -> bool:
        if not structured_answer:
            return False
        return (
            "按单环内时间顺序分段统计" in structured_answer
            and "第 1/10 段" in structured_answer
            and "第 10/10 段" in structured_answer
        )

    def _build_polish_messages(self, user_query: str, structured_answer: str):
        system = (
            "你是盾构刀具管理系统的数据分析表达助手。"
            "规则路由和 Python 工具已经完成查询、统计、排序、异常判断。"
            "你的任务是把给定的结构化分析结果组织成自然、专业的中文回答。"
            "不得新增、改写或推算任何数字、环号、刀位、厂家、比例、排序。"
            "如果数据量不足或有注意事项，必须保留。"
            "不要提到工具、JSON、提示词或内部实现。"
        )
        human = (
            f"用户问题：\n{user_query}\n\n"
            f"结构化分析结果：\n{structured_answer}\n\n"
            "请输出最终回答，建议按“结论、关键依据、注意事项/建议”的顺序组织。"
        )
        return [SystemMessage(content=system), HumanMessage(content=human)]

    def _polish_direct_answer(self, user_query: str, structured_answer: str):
        """返回 (答案, token用量)。

        注意：润色会把已经拼好的模板答案再交给 LLM 重写，这一步同样消耗 token，
        此前未被任何统计覆盖，会低估规则直答路径的实际成本。
        """
        if (
            not self._should_polish_direct_answer()
            or not structured_answer
            or self._must_preserve_direct_answer(structured_answer)
        ):
            return structured_answer, {}
        callbacks, get_usage = _new_usage_callback()
        try:
            result = self.llm.invoke(
                self._build_polish_messages(user_query, structured_answer),
                config={"callbacks": callbacks} if callbacks else None,
            )
            text = result.content if hasattr(result, "content") else str(result)
            return (text.strip() or structured_answer), get_usage()
        except Exception as e:
            logger.warning("直接路由答案润色失败，回退结构化答案：%s", e)
            return structured_answer, get_usage()

    async def _polish_direct_answer_async(self, user_query: str, structured_answer: str) -> str:
        if (
            not self._should_polish_direct_answer()
            or not structured_answer
            or self._must_preserve_direct_answer(structured_answer)
        ):
            return structured_answer
        try:
            result = await self.llm.ainvoke(self._build_polish_messages(user_query, structured_answer))
            text = result.content if hasattr(result, "content") else str(result)
            return text.strip() or structured_answer
        except Exception as e:
            logger.warning("流式直接路由答案润色失败，回退结构化答案：%s", e)
            return structured_answer

    def _format_tunneling_summary_answer(self, raw: str) -> str:
        data = json.loads(raw)
        if data.get("error"):
            return data["error"]
        if data.get("total_records", 0) == 0:
            return data.get("message", "未找到符合条件的掘进动态数据。")

        structured = self._format_analysis_payload_answer(
            f"掘进动态数据概览：共查询到 {data.get('total_records')} 条记录。",
            data,
        )
        if structured:
            return structured

        metrics = data.get("metrics", {})
        lines = [
            f"掘进动态数据概览：共查询到 {data.get('total_records')} 条记录。",
            "",
            "关键参数：",
            self._format_metric_stats("总推力", metrics.get("thrust", {}), "kN"),
            self._format_metric_stats("刀盘扭矩", metrics.get("torque", {}), "kNm"),
            self._format_metric_stats("刀盘转速", metrics.get("cutterhead_speed", {}), "r/min"),
            self._format_metric_stats("贯入力", metrics.get("penetration", {}), PENETRATION_FORCE_UNIT),
        ]
        recent = data.get("recent_records") or []
        if recent:
            lines.extend(["", "最近记录："])
            for item in recent[:5]:
                lines.append(
                    f"- 环号 {item.get('ring_no')}：推力 {item.get('thrust')}kN，"
                    f"扭矩 {item.get('torque')}kNm，转速 {item.get('cutterhead_speed')}r/min，"
                    f"贯入力 {self._format_penetration_force(item.get('penetration'))}"
                )
        return "\n".join(lines)

    def _format_tunneling_trend_answer(self, raw: str) -> str:
        data = json.loads(raw)
        if data.get("error"):
            return data["error"]
        if data.get("total_records", 0) == 0:
            return data.get("message", "未找到符合条件的掘进动态数据。")

        def value(seg, key):
            v = seg.get(key)
            return float(v) if v is not None else None

        def fmt(v, unit=""):
            if v is None:
                return "暂无"
            return f"{round(float(v), 3)}{unit}"

        segments = data.get("segments", []) or []
        valid_penetration = [seg for seg in segments if value(seg, "avg_penetration") is not None]
        valid_thrust = [seg for seg in segments if value(seg, "avg_thrust") is not None]
        valid_torque = [seg for seg in segments if value(seg, "avg_torque") is not None]
        valid_speed = [seg for seg in segments if value(seg, "avg_cutterhead_speed") is not None]

        max_penetration = max(valid_penetration, key=lambda s: value(s, "avg_penetration"), default=None)
        min_penetration = min(valid_penetration, key=lambda s: value(s, "avg_penetration"), default=None)
        max_thrust = max(valid_thrust, key=lambda s: value(s, "avg_thrust"), default=None)
        max_torque = max(valid_torque, key=lambda s: value(s, "avg_torque"), default=None)
        max_speed = max(valid_speed, key=lambda s: value(s, "avg_cutterhead_speed"), default=None)
        first = valid_penetration[0] if valid_penetration else None
        last = valid_penetration[-1] if valid_penetration else None

        def seg_label(seg):
            if not seg:
                return "暂无"
            if seg.get("segment_index"):
                return f"第 {seg.get('segment_index')}/{seg.get('segment_count')} 段"
            return str(seg.get("ring_range"))

        warnings = []
        for idx in range(1, len(segments)):
            prev_end = segments[idx - 1].get("end_time")
            current_start = segments[idx].get("start_time")
            if not prev_end or not current_start:
                continue
            try:
                prev_dt = datetime.fromisoformat(str(prev_end))
                current_dt = datetime.fromisoformat(str(current_start))
            except ValueError:
                continue
            gap_minutes = (current_dt - prev_dt).total_seconds() / 60
            if gap_minutes >= 30:
                warnings.append(
                    f"{seg_label(segments[idx - 1])} 到 {seg_label(segments[idx])} 间隔约 {round(gap_minutes, 1)} 分钟，可能存在停机、换班或数据断点。"
                )
        for seg in segments:
            start_time = seg.get("start_time")
            end_time = seg.get("end_time")
            if not start_time or not end_time:
                continue
            try:
                start_dt = datetime.fromisoformat(str(start_time))
                end_dt = datetime.fromisoformat(str(end_time))
            except ValueError:
                continue
            duration_minutes = (end_dt - start_dt).total_seconds() / 60
            if duration_minutes >= 30:
                warnings.append(
                    f"{seg_label(seg)} 覆盖时长约 {round(duration_minutes, 1)} 分钟，明显长于其他分段，建议核对是否包含停机或采集间断。"
                )

        trend = data.get("trend") or "暂无"
        conclusion = "整体工况较稳定。"
        if first and last:
            start_v = value(first, "avg_penetration")
            end_v = value(last, "avg_penetration")
            delta = end_v - start_v
            if delta < 0:
                conclusion = (
                    f"贯入力从首段 {self._format_penetration_force(start_v)} 降至末段 {self._format_penetration_force(end_v)}，整体呈下降趋势，"
                    "说明后段单位掘进阻力相对减弱或掘进参数被调整。"
                )
            elif delta > 0:
                conclusion = (
                    f"贯入力从首段 {self._format_penetration_force(start_v)} 升至末段 {self._format_penetration_force(end_v)}，整体呈上升趋势，"
                    "说明后段掘进阻力或负荷有所抬升。"
                )
            else:
                conclusion = f"贯入力首末段均为 {self._format_penetration_force(start_v)}，整体变化不明显。"

        if max_penetration and min_penetration:
            spread = value(max_penetration, "avg_penetration") - value(min_penetration, "avg_penetration")
            if spread >= 3:
                warnings.append(
                    f"贯入力峰谷差约 {self._format_penetration_force(spread)}，波动较明显，建议结合地层和操作参数复核。"
                )

        lines = [
            (
                f"掘进动态趋势：共 {data.get('total_records')} 条记录，按单环内时间顺序分段统计。"
                if any(seg.get("segment_index") for seg in segments) else
                f"掘进动态趋势：共 {data.get('total_records')} 条记录，按 {data.get('interval')} 环分段统计。"
            ),
            "",
            "结论：",
            f"- {conclusion}",
            f"- 贯入力整体趋势：{trend}。",
            "",
            "关键变化：",
            f"- 贯入力最高出现在{seg_label(max_penetration)}，平均 {self._format_penetration_force(value(max_penetration, 'avg_penetration'))}；最低出现在{seg_label(min_penetration)}，平均 {self._format_penetration_force(value(min_penetration, 'avg_penetration'))}。",
            f"- 推力峰值出现在{seg_label(max_thrust)}，平均 {fmt(value(max_thrust, 'avg_thrust'), 'kN')}；扭矩峰值出现在{seg_label(max_torque)}，平均 {fmt(value(max_torque, 'avg_torque'), 'kNm')}。",
            f"- 转速最高出现在{seg_label(max_speed)}，平均 {fmt(value(max_speed, 'avg_cutterhead_speed'), 'r/min')}。",
        ]
        if warnings:
            lines.extend(["", "提醒："])
            lines.extend(f"- {item}" for item in warnings[:3])

        lines.extend([
            "",
            "分段结果：",
        ])
        for seg in segments[:12]:
            if seg.get("segment_index"):
                label = f"环号 {seg.get('ring_range')} 第 {seg.get('segment_index')}/{seg.get('segment_count')} 段"
                if seg.get("start_time") and seg.get("end_time"):
                    label += f"（{seg.get('start_time')} 至 {seg.get('end_time')}）"
            else:
                label = seg.get('ring_range')
            lines.append(
                f"- {label}：平均推力 {seg.get('avg_thrust')}kN，"
                f"平均扭矩 {seg.get('avg_torque')}kNm，平均转速 {seg.get('avg_cutterhead_speed')}r/min，"
                f"平均贯入力 {self._format_penetration_force(seg.get('avg_penetration'))}"
            )
        return "\n".join(lines)

    def _format_tunneling_anomaly_answer(self, raw: str) -> str:
        data = json.loads(raw)
        if data.get("error"):
            return data["error"]
        if data.get("total_records", 0) == 0:
            return data.get("message", "未找到符合条件的掘进动态数据。")

        anomalies = data.get("anomaly_fields") or []
        lines = [f"掘进动态异常检查：共查询到 {data.get('total_records')} 条记录。"]
        if not anomalies:
            lines.append("按当前阈值未发现推力、扭矩或贯入力的明显异常峰值。")
        else:
            lines.append("发现以下异常指标：")
            field_names = {"thrust": "总推力", "torque": "刀盘扭矩", "penetration": "贯入力"}
            for item in anomalies:
                lines.append(
                    f"- {field_names.get(item.get('field'), item.get('field'))}："
                    f"平均 {item.get('avg')}，最大 {item.get('max')}"
                )
            lines.append("建议结合对应环号的地层与换刀记录进一步判断是否存在硬岩、孤石或刀具异常磨损影响。")
        return "\n".join(lines)

    def _format_recent_abnormal_wear_cause_answer(self, user_query: str, context: dict = None) -> str:
        project_id = (context or {}).get("project_id") or _DEFAULT_PROJECT_ID
        ring_range = self._recent_ring_range("最近100环", context)
        params = {"project_id": project_id, "ring_range": ring_range, "tool_type": self._infer_tool_type(user_query)}

        change = json.loads(query_tool_change_data(json.dumps(params, ensure_ascii=False)))
        stratum_wear = json.loads(analyze_stratum_wear_correlation(json.dumps(params, ensure_ascii=False)))
        tunneling = json.loads(query_tunneling_wear_correlation(json.dumps({**params, "interval": 50}, ensure_ascii=False)))
        opening = json.loads(query_opening_records(json.dumps({"project_id": project_id, "limit": 5}, ensure_ascii=False)))

        lines = [
            f"近期异常磨损原因分析：本次按环号 {ring_range[0]}-{ring_range[1]} 作为近期窗口。",
            "",
            "关键发现：",
        ]

        if change.get("total_records", 0):
            abnormal_items = [
                item for item in (change.get("wear_distribution") or [])
                if item.get("wear_condition") not in (None, "", "正常", "NORMAL")
            ]
            abnormal_total = sum(int(item.get("count") or 0) for item in abnormal_items)
            abnormal_text = "、".join(f"{item.get('wear_condition')} {item.get('count')}次" for item in abnormal_items[:4]) or "暂无"
            lines.append(
                f"- 近期换刀检查 {change.get('total_records')} 条，实际更换 {change.get('replaced_count')} 次，更换率 {change.get('replacement_rate')}；异常磨损合计 {abnormal_total} 次，主要为 {abnormal_text}。"
            )
            positions = change.get("top_replaced_positions") or []
            if positions:
                pos_text = "、".join(f"{p.get('cutter_position_no')}({p.get('replacement_count')}次)" for p in positions[:5])
                lines.append(f"- 高频更换刀位集中在 {pos_text}，说明局部刀位/区域受力或地层冲击需要优先复核。")
        else:
            lines.append("- 近期窗口内未查询到换刀明细，无法从换刀记录判断异常磨损原因。")

        records = opening.get("recent_records") or []
        high_openings = [r for r in records if _pct_to_float(r.get("abnormal_rate")) >= 30]
        if high_openings:
            top = max(high_openings, key=lambda item: _pct_to_float(item.get("abnormal_rate")))
            lines.append(
                f"- 最近开仓中环号 {top.get('ring_no')} 异常率最高，为 {top.get('abnormal_rate')}；高频刀位 {('、'.join(top.get('top_replaced_positions') or []) or '暂无')}。"
            )

        strata = stratum_wear.get("stratum_analysis") or []
        if strata:
            top_stratum = strata[0]
            lines.append(
                f"- 地层关联上，{top_stratum.get('stratum_name', top_stratum.get('stratum_type'))} 的更换率最高，为 {top_stratum.get('replacement_rate')}，对应更换 {top_stratum.get('replaced_count')} 次。"
            )

        lines.extend(["", "掘进参数可用性："])
        if tunneling.get("total_records", 0):
            segments = tunneling.get("segments") or []
            wear_segments = [seg for seg in segments if (seg.get("abnormal_wear_count") or 0) > 0]
            if wear_segments:
                top_seg = max(wear_segments, key=lambda item: item.get("abnormal_wear_count") or 0)
                lines.append(
                    f"- 掘进动态可关联到环号 {tunneling.get('ring_range')}；异常磨损最多区段为 {top_seg.get('ring_range')}，异常 {top_seg.get('abnormal_wear_count')} 次，平均扭矩 {top_seg.get('avg_torque')}kNm。"
                )
            else:
                lines.append("- 有掘进动态记录，但当前可关联区段未匹配到异常磨损记录，不能证明掘进参数是直接原因。")
            for warning in tunneling.get("warnings") or []:
                lines.append(f"- {warning}")
        else:
            lines.append("- 未找到可与近期换刀窗口关联的掘进动态数据，因此不能把异常磨损直接归因于推力、扭矩或转速。")

        lines.extend(["", "原因判断："])
        reasons = []
        if strata:
            reasons.append("硬岩、孤石或基岩凸起等不利地层导致刀具冲击和偏磨风险升高")
        if change.get("top_replaced_positions"):
            reasons.append("高频刀位重复出现，提示局部刀位安装状态、相邻刀位联动或刀盘受力分布异常")
        if high_openings:
            reasons.append("高异常率开仓与高换刀量同时出现，说明异常不是单条记录噪声，应按开仓环段回溯")
        if not reasons:
            reasons.append("当前数据不足以形成明确原因，需要补充近期换刀、地层或掘进动态数据")
        for index, reason in enumerate(reasons, start=1):
            lines.append(f"{index}. {reason}。")

        lines.extend([
            "",
            "建议：优先复核高异常开仓环段的地层记录和高频刀位；同步检查这些刀位的安装、轴承/密封状态以及相邻刀位磨损。如果需要判断掘进参数影响，需要补齐同一环号范围内的推力、扭矩、转速和贯入力记录。",
        ])
        return "\n".join(lines)
    def _direct_stratum_wear_analysis(self, user_query: str, context: dict = None) -> str:
        params = self._context_params(user_query, context)
        raw = analyze_stratum_wear_correlation(json.dumps(params, ensure_ascii=False))
        return self._format_stratum_wear_answer(raw)

    def _route_mode_for_context(self, context: dict = None) -> str:
        mode = ((context or {}).get("route_mode") or _route_mode()).strip().lower()
        if mode in {"agent", "model", "llm"}:
            return "agent"
        if mode in {"rule", "direct", "hybrid"}:
            return mode
        return "hybrid"

    def _allow_direct_route_in_agent(self, query: str) -> bool:
        """agent 模式下仍强制走规则直答的例外分支。

        这两条例外让 route_mode=agent 并非纯净的 Agent 对照组，在做
        "纯 Agent vs 混合路由" 的对照实验时会污染结果。设置环境变量
        AI_STRICT_AGENT=1 可关闭全部例外，使 agent 模式成为严格对照组。
        实验脚本应一律置 1；线上默认保持原有行为（0）。
        """
        if _flag_enabled("AI_STRICT_AGENT"):
            return False
        return any((
            self._is_recent_ring_tool_change_query(query),
            self._is_opening_efficiency_query(query),
        ))

    def _direct_route(self, user_query: str, context: dict = None) -> dict | None:
        if self._is_inventory_query(user_query):
            return {"rule_branch": "inventory", "type": "text", "answer": "当前智能助手没有库存台账查询工具，无法确认刀具库存数量。请到库存或仓储模块查看具体库存记录。"}
        if self._is_ambiguous_followup_query(user_query):
            return {"rule_branch": "ambiguous_followup", "type": "text", "answer": "这个问题缺少具体对象。请说明具体是哪种刀具、刀位、磨损类型、厂家或环号范围，我再按对应数据分析原因。"}
        if self._is_recent_abnormal_wear_cause_query(user_query):
            return {"rule_branch": "recent_abnormal_wear_cause", "type": "analysis", "answer": self._format_recent_abnormal_wear_cause_answer(user_query, context)}
        if self._is_opening_efficiency_query(user_query):
            params = self._context_params(user_query, context, limit=self._extract_limit(user_query, 10))
            raw = query_opening_records(json.dumps(params, ensure_ascii=False))
            return {"rule_branch": "opening_efficiency", "type": "analysis", "answer": self._prepend_query_scope(self._format_opening_efficiency_answer(raw), params, user_query)}
        if self._is_recent_ring_tool_change_query(user_query):
            params = self._context_params(user_query, context)
            params["ring_range"] = self._recent_ring_range(user_query, context)
            raw = query_tool_change_data(json.dumps(params, ensure_ascii=False))
            return {"rule_branch": "recent_ring_tool_change", "type": "analysis", "answer": self._prepend_query_scope(self._format_tool_change_answer(raw, params.get("ring_range")), params, user_query)}
        if self._is_tool_recommendation_query(user_query):
            # 把问句中能抽到的刀具类型与环号范围一并传下去，
            # 使规则直答与 Agent 走同一套筛选语义（旧实现只传 project_id）。
            params = self._context_params(user_query, context)
            raw = recommend_tools(_to_json({
                "project_id": params.get("project_id"),
                "tool_type": params.get("tool_type") or "",
                "ring_range": params.get("ring_range") or [],
            }))
            return {"rule_branch": "tool_recommendation", "type": "analysis", "answer": self._format_recommend_tools_answer(raw)}
        if self._is_tool_performance_query(user_query):
            # 刀具实例编号的真实形态是「环号-刀位-序号」，环号可能带字母前缀
            # （实测库中形如 R15-S11L-2，docstring 举例形如 487-S14R-01）。
            # 旧正则 [A-Za-z]{1,6}[-_]?\d{1,} 会把 R15-S11L-2 切成 ['R15','S11','L-2']，
            # calculate_tool_performance 因此永远查不到记录、恒定返回 not_found——
            # 这条分支实际上从来不可用，只是此前未被评测触及而未暴露。
            tool_numbers = re.findall(r"[A-Za-z]{0,2}\d{1,6}-[A-Za-z0-9]{1,8}-\d{1,3}", user_query)
            if not tool_numbers:
                # 退回旧正则：用户只给了不完整编号（如 T12）时仍进入本分支，
                # 由工具返回"编号格式形如 487-S14R-01"的显式提示，而不是静默落 Agent。
                tool_numbers = re.findall(r"[A-Za-z]{1,6}[-_]?\d{1,}|T\d+", user_query)
            if tool_numbers:
                raw = calculate_tool_performance(json.dumps({"project_id": (context or {}).get("project_id") or _DEFAULT_PROJECT_ID, "tool_numbers": tool_numbers}, ensure_ascii=False))
                return {"rule_branch": "tool_performance", "type": "analysis", "answer": self._format_tool_performance_answer(raw)}

        if self._is_opening_stratum_change_query(user_query):
            params = self._context_params(user_query, context, limit=self._extract_limit(user_query, 10))
            raw = query_opening_records(json.dumps(params, ensure_ascii=False))
            return {"rule_branch": "opening_stratum_change", "type": "analysis", "answer": self._format_opening_stratum_change_answer(raw, context)}
        if self._is_tunneling_wear_correlation_query(user_query):
            params = self._context_params(user_query, context)
            raw = query_tunneling_wear_correlation(json.dumps(params, ensure_ascii=False))
            data = json.loads(raw)
            structured = self._format_analysis_payload_answer(
                f"掘进-磨损关联分析：共查询到 {data.get('total_records', 0)} 条掘进动态记录。",
                data,
            )
            answer = structured or raw
            return {"rule_branch": "tunneling_wear_correlation", "type": "analysis", "answer": self._prepend_query_scope(answer, params, user_query)}

        if self._is_tunneling_anomaly_query(user_query):
            params = self._context_params(user_query, context)
            raw = query_tunneling_anomaly(json.dumps(params, ensure_ascii=False))
            data = json.loads(raw)
            structured = self._format_analysis_payload_answer(
                f"掘进动态异常检查：共查询到 {data.get('total_records', 0)} 条记录。",
                data,
            )
            answer = structured or self._format_tunneling_anomaly_answer(raw)
            return {"rule_branch": "tunneling_anomaly", "type": "analysis", "answer": self._prepend_query_scope(answer, params, user_query)}

        if self._is_tunneling_trend_query(user_query):
            params = self._context_params(user_query, context)
            raw = query_tunneling_trend(json.dumps(params, ensure_ascii=False))
            return {"rule_branch": "tunneling_trend", "type": "analysis", "answer": self._prepend_query_scope(self._format_tunneling_trend_answer(raw), params, user_query)}

        if self._is_tunneling_query(user_query):
            params = self._context_params(user_query, context)
            raw = query_tunneling_summary(json.dumps(params, ensure_ascii=False))
            return {"rule_branch": "tunneling", "type": "analysis", "answer": self._prepend_query_scope(self._format_tunneling_summary_answer(raw), params, user_query)}

        if self._is_position_stratum_query(user_query):
            params = self._context_params(user_query, context, top_n=self._extract_limit(user_query, 10))
            raw = query_position_stratum_impact(json.dumps(params, ensure_ascii=False))
            return {"rule_branch": "position_stratum", "type": "analysis", "answer": self._prepend_query_scope(self._format_position_stratum_answer(raw), params, user_query)}

        if self._is_stratum_wear_query(user_query):
            params = self._context_params(user_query, context)
            raw = _with_analysis_payload(
                analyze_stratum_wear_correlation(json.dumps(params, ensure_ascii=False)),
                "stratum_wear",
            )
            data = json.loads(raw)
            structured = self._format_analysis_payload_answer("地层-磨损关联分析", data)
            answer = structured or self._format_stratum_wear_answer(raw)
            return {"rule_branch": "stratum_wear", "type": "analysis", "answer": self._prepend_query_scope(answer, params, user_query)}

        if self._is_manufacturer_query(user_query):
            params = self._context_params(user_query, context)
            raw = _with_analysis_payload(
                compare_manufacturer_performance(json.dumps(params, ensure_ascii=False)),
                "manufacturer",
            )
            data = json.loads(raw)
            structured = self._format_analysis_payload_answer("厂家性能对比分析", data)
            answer = structured or self._format_manufacturer_answer(raw)
            return {"rule_branch": "manufacturer", "type": "analysis", "answer": self._prepend_query_scope(answer, params, user_query)}

        if self._is_opening_query(user_query):
            params = self._context_params(user_query, context, limit=self._extract_limit(user_query, 10))
            raw = query_opening_records(json.dumps(params, ensure_ascii=False))
            return {"rule_branch": "opening", "type": "analysis", "answer": self._prepend_query_scope(self._format_opening_answer(raw), params, user_query)}

        # 单刀位点查必须排在刀位排行之前。
        # tool_change_summary 下沉到链尾后，它原本承担的"某个具体刀位换了多少次"
        # 落到了 _is_cutter_position_query 手里，而 query_cutter_position_stats
        # 不接收 cutter_position_no（tools.py 只读 project_id/tool_type/top_n），
        # 结果是返回全项目排行、答案头部却宣称"分析范围：刀位：S14R"。
        # query_tool_change_data 支持该过滤，故点查改走它。
        if self._extract_cutter_position_no(user_query) and not any(
            kw in user_query for kw in ("哪个", "哪些", "排行", "排名", "最多", "最频繁", "top", "TOP")
        ):
            # 函数体与 tool_change_summary 完全一致（同工具、同 payload、同模板），
            # 只有 rule_branch 标签不同——这样 tc_position_g3r / tc_position_46 /
            # boundary_empty_position 三条既有用例的答案文本逐字不变，
            # 抽取正则与真值都不受影响，改动只体现在路由标签上。
            params = self._context_params(user_query, context)
            raw = _with_analysis_payload(
                query_tool_change_data(json.dumps(params, ensure_ascii=False)),
                "tool_change",
            )
            data = json.loads(raw)
            structured = self._format_analysis_payload_answer("换刀数据分析", data)
            answer = structured or self._format_tool_change_answer(raw, params.get("ring_range"))
            return {"rule_branch": "position_point_query", "type": "analysis",
                    "answer": self._prepend_query_scope(answer, params, user_query)}

        if self._is_cutter_position_query(user_query):
            params = self._context_params(user_query, context, top_n=self._extract_limit(user_query, 10))
            raw = _with_analysis_payload(
                query_cutter_position_stats(json.dumps(params, ensure_ascii=False)),
                "cutter_position",
            )
            data = json.loads(raw)
            structured = self._format_analysis_payload_answer("刀位风险分析", data)
            answer = structured or self._format_cutter_position_answer(raw)
            return {"rule_branch": "cutter_position", "type": "analysis", "answer": self._prepend_query_scope(answer, params, user_query)}

        if self._is_change_trend_query(user_query):
            params = self._context_params(user_query, context)
            raw = query_tool_change_trend(json.dumps(params, ensure_ascii=False))
            return {"rule_branch": "change_trend", "type": "analysis", "answer": self._prepend_query_scope(self._format_trend_answer(raw), params, user_query)}

        if self._is_stratum_distribution_query(user_query):
            params = self._context_params(user_query, context)
            raw = query_stratum_data(json.dumps(params, ensure_ascii=False))
            return {"rule_branch": "stratum_distribution", "type": "analysis", "answer": self._prepend_query_scope(self._format_stratum_distribution_answer(raw), params, user_query)}

        # tool_change_summary 是本链上判定最宽的分支（一个刀具词 + 一个统计词即命中），
        # 放在链首会把 12 个窄分支结构性遮蔽掉——「刀位地层磨损情况统计」这类问句
        # 意图明确是刀位×地层，却会先被它截走。宽判定必须排在窄判定之下，
        # 在这里它承担的是“换刀类问句的兜底”职责，而不是优先拦截。
        if self._is_tool_change_summary_query(user_query):
            params = self._context_params(user_query, context)
            if any(kw in user_query for kw in ("最近", "近")) and not params.get("ring_range"):
                params["ring_range"] = self._recent_ring_range(user_query, context)
            raw = _with_analysis_payload(
                query_tool_change_data(json.dumps(params, ensure_ascii=False)),
                "tool_change",
            )
            data = json.loads(raw)
            structured = self._format_analysis_payload_answer("换刀数据分析", data)
            answer = structured or self._format_tool_change_answer(raw, params.get("ring_range"))
            return {"rule_branch": "tool_change_summary", "type": "analysis", "answer": self._prepend_query_scope(answer, params, user_query)}

        return None
    def _invoke_with_retry(self, payload: dict, config: dict, max_retries: int = 2, executor=None) -> dict:
        """带重试的 executor 调用"""
        last_err = None
        for attempt in range(max_retries + 1):
            try:
                return executor.invoke(payload, config=config)
            except Exception as e:
                last_err = e
                err_lower = str(e).lower()
                is_retryable = any(kw in err_lower for kw in _RETRYABLE_ERRORS)
                if is_retryable and attempt < max_retries:
                    wait = 2 ** attempt
                    logger.warning(f"可重试错误（第{attempt+1}次），{wait}s 后重试：{e}")
                    time.sleep(wait)
                else:
                    raise
        raise last_err

    def chat(self, user_query: str, context: dict = None) -> dict:
        user_id = str(context.get("user_id", "anonymous")) if context else "anonymous"

        merged_query = self._try_merge_with_previous_question(user_query, user_id)
        ctx_msg = self._build_context_message(context)
        enriched_input = f"{ctx_msg}\n\n{merged_query}" if ctx_msg else merged_query

        config = {"configurable": {"session_id": user_id}}

        # 埋点：记录本次请求的工具调用、被裁剪出的工具组、token 用量。
        # route 字段保持原有取值（rule / llm）以兼容既有前端；新增 route_stage
        # 用于区分"LLM 直聊"与"Agent 工具调用"——二者原本都返回 route="llm"，
        # 无法在日志与实验数据中区分。
        _trace_start()
        started_at = time.perf_counter()
        tool_group = self._tool_group_for_query(merged_query)
        callbacks, get_usage = _new_usage_callback()
        if callbacks:
            config = {**config, "callbacks": callbacks}

        def _finish(payload: dict, route_stage: str, retry_count: int = 0) -> dict:
            payload.update({
                "route_stage": route_stage,
                "rule_branch": payload.get("rule_branch"),
                "tool_group": tool_group,
                "tool_calls": _trace_calls(
                    include_results=_flag_enabled("AI_TRACE_TOOL_RESULTS")
                ),
                "usage": get_usage(),
                "retry_count": retry_count,
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 1),
                "config": current_config_signature(),
            })
            _trace_stop()
            return payload

        try:
            logger.info(f"[{user_id}] 查询：{user_query}")
            direct = self._direct_route(merged_query, context) if (self._route_mode_for_context(context) != "agent" or self._allow_direct_route_in_agent(merged_query)) else None
            if direct:
                ablate_usage = {}
                if _flag_enabled("AI_ABLATE_TEMPLATE"):
                    raw_answer, ablate_usage = self._verbalize_raw_tool_results(
                        merged_query, _trace_calls(include_results=True)
                    )
                    if raw_answer:
                        direct["answer"] = raw_answer
                answer, polish_usage = self._polish_direct_answer(merged_query, direct["answer"])
                history_store = self._get_session_history(user_id)
                history_store.add_user_message(user_query)
                history_store.add_ai_message(answer)
                base_usage = get_usage()
                result_payload = {
                    "success": True, "answer": answer, "type": direct["type"],
                    "route": "rule", "route_label": "规则直答",
                    "rule_branch": direct.get("rule_branch"),
                    "estimated_time": "通常 1 秒内",
                }
                payload = _finish(result_payload, "rule")
                payload["usage"] = _merge_usage(base_usage, polish_usage, ablate_usage)
                return payload

            if not self._needs_tool_call(merged_query):
                answer, chat_usage = self._direct_chat(merged_query, context)
                history_store = self._get_session_history(user_id)
                history_store.add_user_message(user_query)
                history_store.add_ai_message(answer)
                payload = _finish({
                    "success": True, "answer": answer, "type": "text",
                    "route": "llm", "route_label": "模型分析",
                    "estimated_time": "通常 6-8 秒",
                }, "llm_direct")
                payload["usage"] = _merge_usage(payload.get("usage"), chat_usage)
                return payload

            executor = self._get_executor_for_query(merged_query, with_history=True)
            result = self._invoke_with_retry({"input": enriched_input}, config=config, executor=executor)

            # 验证：需要查数据的问题必须有工具调用记录
            retry_count = 0
            steps = result.get("intermediate_steps", [])
            if self._needs_tool_call(user_query) and not steps:
                logger.warning(f"[{user_id}] 未调用工具，强制重试")
                retry_input = (
                    f"{enriched_input}\n\n"
                    "【系统提示】你上一次回答没有调用任何工具，直接编造了数据，这是错误的。"
                    "请立即调用对应工具查询真实数据，不得编造任何数字或结论。"
                )
                retry_count = 1
                result = self._invoke_with_retry({"input": retry_input}, config=config, executor=executor)

            answer = result.get("output", "")
            logger.info(f"[{user_id}] 回答成功，工具调用次数：{len(result.get('intermediate_steps', []))}")
            return _finish({
                "success": True, "answer": answer, "type": "text",
                "route": "llm", "route_label": "模型分析",
                "estimated_time": "通常 6-8 秒",
            }, "agent", retry_count=retry_count)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"[{user_id}] 查询失败：{error_msg}")
            return _finish({
                "success": False, "error": self._friendly_error(error_msg), "type": "error",
            }, "error")

    async def chat_stream(self, user_query: str, context: dict = None):
        """
        异步生成器，逐 token 产出内容。
        注意：RunnableWithMessageHistory 的 astream_events 需要手动管理历史写入，
        因此流式模式直接使用 base_executor，历史在完成后手动追加到 SQLChatMessageHistory。
        """
        user_id = str(context.get("user_id", "anonymous")) if context else "anonymous"

        ctx_msg = self._build_context_message(context)
        enriched_input = f"{ctx_msg}\n\n{user_query}" if ctx_msg else user_query

        # 从数据库读取历史
        history_store = self._get_session_history(user_id)
        history_messages = history_store.messages

        # 裁剪：保留最近 12 条，防止上下文过长
        if len(history_messages) > 12:
            history_messages = history_messages[-12:]

        try:
            full_answer = []
            direct = self._direct_route(user_query, context) if (self._route_mode_for_context(context) != "agent" or self._allow_direct_route_in_agent(user_query)) else None

            if direct:
                answer = await self._polish_direct_answer_async(user_query, direct["answer"])
                full_answer.append(answer)
                if answer:
                    yield {"type": "meta", "route": "rule", "route_label": "规则直答",
                           "route_stage": "rule", "rule_branch": direct.get("rule_branch"),
                           "estimated_time": "通常 1 秒内"}
                    yield {"type": "chunk", "content": answer}
            elif not self._needs_tool_call(user_query):
                yield {"type": "meta", "route": "llm", "route_label": "模型分析",
                       "route_stage": "llm_direct", "estimated_time": "通常 6-8 秒"}
                async for chunk in self.llm.astream(self._build_direct_messages(user_query, context)):
                    text = chunk.content if hasattr(chunk, "content") else str(chunk)
                    if isinstance(text, str) and text:
                        full_answer.append(text)
                        yield {"type": "chunk", "content": text}
            else:
                yield {"type": "meta", "route": "llm", "route_label": "模型分析",
                       "route_stage": "agent",
                       "tool_group": self._tool_group_for_query(user_query),
                       "estimated_time": "通常 6-8 秒"}
                executor = self._get_executor_for_query(user_query, with_history=False)
                async for event in executor.astream_events(
                    {"input": enriched_input, "chat_history": history_messages},
                    version="v2",
                ):
                    kind = event.get("event")
                    if kind == "on_chat_model_stream":
                        chunk = event["data"].get("chunk")
                        if chunk and hasattr(chunk, "content"):
                            text = chunk.content
                            if isinstance(text, str) and text:
                                full_answer.append(text)
                                yield {"type": "chunk", "content": text}

            answer = "".join(full_answer)
            if answer:
                history_store.add_user_message(user_query)
                history_store.add_ai_message(answer)
            yield {"type": "done"}

        except Exception as e:
            logger.error(f"[{user_id}] 流式查询失败：{e}")
            yield {"type": "error", "content": self._friendly_error(str(e))}

    def reset_memory(self, user_id: str = None):
        """清除指定用户或所有用户的对话历史"""
        if user_id:
            history_store = self._get_session_history(str(user_id))
            history_store.clear()
            logger.info(f"对话记忆已重置，user_id={user_id}")
        else:
            # 清空所有会话：直接操作底层表
            try:
                from sqlalchemy import create_engine, text
                engine = create_engine(_HISTORY_DB_URL)
                with engine.connect() as conn:
                    conn.execute(text("DELETE FROM message_store"))
                    conn.commit()
                logger.info("所有对话记忆已清空")
            except Exception as e:
                logger.error(f"清空所有历史失败：{e}")


_assistant: ToolAssistant | None = None


def get_assistant() -> ToolAssistant:
    global _assistant
    if _assistant is None:
        _assistant = ToolAssistant()
    return _assistant
