"""规则直答的覆盖检查：问句要求的指标、条件和对象在模板回答里都找得到，才采用规则直答，否则交给智能体。

模板只输出所在分支已有的字段。问句要的指标、筛选条件或并列对象若不在其中，模板会直接略过，
所以在采用规则直答前，逐项核对问句的要求是否出现在模板回答里。只对照文字，不调用模型。
"""
import re

# “最近、最新”不算最值；“并列出”“并列列出”是“并且列出”，不是并列名次
SUPERLATIVE = r"最(?!近|新|后|终)|并列(?=的|第|最|都|就|全)"
# 明确要前 N 名时，排行表本身就是答案
TOP_N = r"前\s*(?:\d+|[一二三四五六七八九十]+)\s*(?:个|名|位|家|种|次)?"

# (要求, 问句中的说法, 模板回答中对应的写法)
DEMANDS = (
    ("现场观测数", r"观测", r"观测"),
    ("更换率", r"更换率|换刀率", r"更换率"),
    ("已分类异常率", r"异常率", r"异常率"),
    ("换刀时长", r"换刀.{0,6}(?:时长|多久|多长时间|耗时|用时|小时)", r"换刀(?:总)?时长|换刀用时"),
    ("开仓时长", r"开仓.{0,6}(?:时长|多久|多长时间|耗时|用时)", r"开仓(?:总)?时长|开仓用时|时长（h）"),
    ("开仓间隔", r"间隔|隔了|相隔|隔得|离上(?:一)?次", r"间隔"),
    ("平均每次更换", r"平均(?:每次)?.{0,3}(?:换|更换)(?:了)?(?:几|多少)", r"平均(?:每次)?(?:更换|换)"),
    ("报价差额", r"差多少|差价|相差|差额|价差", r"差价|相差|差额|价差"),
    ("供货次数", r"供货|新装.{0,6}(?:多少|几)(?:次|把)", r"供货次数|新装(?:次数|数量|把数)"),
    ("按厂家", r"各(?:个)?厂家|每(?:个|一)?(?:家|厂家)|按厂家|哪(?:家|个厂家)", r"厂家"),
    ("旧刀总数", r"换下.{0,4}旧刀.{0,8}(?:一共|总共|共|数量|多少|几把)|旧刀(?:一共|总共|共有)", r"(?:一共|共|合计|总计)\s*\**\d"),
    ("轴承失效把数", r"轴承.{0,8}(?:几把|多少把)", r"轴承[^|\n]{0,12}\d+\s*把"),
    ("刀圈损坏把数", r"刀圈.{0,8}(?:几把|多少把)", r"刀圈[^|\n]{0,12}\d+\s*把"),
    # 起止相同的“218–218 环”只是单环，不算区间
    ("上次开仓以来的区间", r"上(?:一)?次开仓.{0,12}(?:到|至|以来|之间)", r"上(?:一)?次开仓|间隔|(?<!\d)(\d+)\s*[–-]\s*(?!\1\s*环)\d+\s*环"),
)
# 库里没有的数据，规则模板不会说明，交给智能体
UNSUPPORTED = r"预测|剩余寿命|还能用|能用多少|还能撑"
STATUSES = {"待厂家反馈": r"待(?:厂家)?反馈", "已确认": r"已(?:经)?确认", "已归档": r"已(?:经)?归档"}


def _compact(text):
    return re.sub(r"\s+", "", text or "")


def coverage_gaps(question, answer, model_names=()):
    """返回问句中模板回答没有覆盖的要求；为空表示可以采用规则直答。"""
    question, answer = question or "", answer or ""
    gaps = [name for name, asked, covered in DEMANDS if re.search(asked, question) and not re.search(covered, answer)]
    if re.search(SUPERLATIVE, question) and not re.search(TOP_N, question) and not re.search(SUPERLATIVE, answer):
        gaps.append("最值")
    if re.search(UNSUPPORTED, question):
        gaps.append("库中没有的数据")
    compact_question, compact_answer = _compact(question), _compact(answer)
    gaps += [f"型号 {name}" for name in model_names
             if _compact(name) in compact_question and _compact(name) not in compact_answer]
    # 查询范围里只筛了一种反馈状态，问句却还问到其他状态
    scope = re.search(r"厂家反馈状态：(待厂家反馈|已确认|已归档)", answer)
    if scope and any(re.search(pattern, question) and status != scope.group(1) for status, pattern in STATUSES.items()):
        gaps.append("反馈状态筛选")
    return gaps
