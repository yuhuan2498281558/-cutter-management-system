# 模型调用预算与可逆工具压缩

`llm_provider.create_chat_model()` 返回 `GuardedChatModel`。所有通过该工厂创建的模型在每次同步、异步及流式调用前检查预算，覆盖 Agent 后续工具轮次、直聊、可选润色和摘要。规则直答仍不初始化模型。

## 处理流程

1. 接收最终消息列表，复制消息，不改动执行记录。
2. 对长 `ToolMessage` 的同构标量对象数组尝试列式编码；保存列名、逐行值和明确路径，附带解码说明。只在收益大于等于去空白 JSON 的 5% 且至少 32 个估算 token 时采用。
3. 将系统提示、历史、用户问题、工具调用参数、工具结果、实际工具 schema 和调用选项纳入估算，另加消息封装开销。
4. 输入限额 = 配置窗口 − 输出上限 − 安全余量。压缩后仍超限则抛出明确错误，要求缩小范围或拆分问题；不静默删除证据或更改查询范围。
5. 将输出上限实际传给供应商。供应商明确返回 `finish_reason=length` 或 `done_reason=length` 时视为未完成；直聊/Agent 不保存该轮，也不发送成功 `done`。可选润色失败仍沿用原有的完整规则回答回退。

原 `intermediate_steps`、工具事件、参数校验及纠错关联均保留原文。压缩不合并均值、不重算分母、不改变 TopK，不将未知值补为零；错误、异常 JSON、重复键及存在数值精度风险的输入保持原文。统计约束也写入共用 `ANSWER_POLICY`。不增加跨请求缓存或证据引用存储。

## 配置

环境变量优先，其次是 Django settings；配置在模型首次初始化时固定。调整后须按现有流程重新加载后端模型实例。

- `AI_CONTEXT_WINDOW_TOKENS`：应用预算窗口。OpenAI/DeepSeek/兼容 API 默认 `16384`；Ollama 默认取 `OLLAMA_NUM_CTX`（缺省 `4096`），不得超过该值。
- `AI_CONTEXT_OUTPUT_TOKENS`：预留并实际限制输出。API 默认 `2048`；Ollama 默认取 `OLLAMA_NUM_PREDICT`（缺省 `1024`）。显式配置优先。
- `AI_CONTEXT_SAFETY_MARGIN_TOKENS`：API 默认 `1024`，Ollama 默认 `512`。
- `AI_CONTEXT_COMPACTION_MIN_TOKENS`：默认 `1000`，低于阈值的工具正文不改写。
- `AI_CONTEXT_TOOL_PROTOCOL_TOKENS`：默认 `1024`，有非空tools/functions的请求额外计入一次协议预留，包括tool_choice=none；工具schema仍完整计数。用于供应商工具模板开销，与安全余量分开。

五项必须为正整数，窗口必须大于输出与安全余量之和。配置不合法时模型初始化报错；纯规则路径仍可使用。API 默认输入预算为 `13312`。窗口是应用的运行限制，不代表自动探测到的供应商能力；部署时需核对具体模型的输入/输出限制。Ollama 默认 4096 的输入空间不足以容纳当前完整系统提示和 14 工具，应依据本机模型与资源配置更大的 `OLLAMA_NUM_CTX`，不能靠裁掉工具掩盖。

计数沿用汉字 1.5、其他字符 0.25 的启发式，但按消息正文、工具参数、schema和其他选项分别计算，正文及参数不再经过整包JSON二次转义。忽略本地消息ID、usage、artifact等字段，已解析调用与additional_kwargs重复调用只计一份；未知消息类型保守回退。历史记忆估算不变，工具schema即使在tool_choice=none下也保留计数。它不是供应商tokenizer或计费值；安全余量不能保证绝不触及供应商限制。目前只支持文本内容，图片/音频请求明确拒绝。

OpenAI 使用本机 SDK 的 `max_completion_tokens` 约定；DeepSeek、`api` 和 `openai-compatible` 在最终 Chat Completions payload 中保留 `max_tokens`。Ollama 在构造时设置 `num_predict`，不传无效的顶层调用参数。调用者可降低 API 输出 cap；Ollama 通过配置修改。禁止动态 `model`、`num_ctx`、`extra_body`、嵌套 `options/model_kwargs` 覆盖预算。升级 LangChain/provider SDK 后须回归最终请求 payload 测试。

## 验证与边界（2026-10-12）

在 `backend` 目录运行：

```powershell
& 'D:/anaconda/python.exe' manage.py test application.ai_assistant.tests --settings=application.settings_ci --keepdb --noinput
& 'D:/anaconda/python.exe' manage.py check --settings=application.settings_ci
```

本次完整助手套件 220 项通过，随后增加的 2 项 Agent 服务层测试也通过（该测试文件合计 19 项）。累计 222 个独立测试，含 44 个本次新增测试。使用隔离测试数据库、本地确定性假模型及真实 LangChain AgentExecutor；没有真实模型请求。覆盖二轮预算、流事件/用量、参数纠错、原始证据、流关闭、截断/超限不保存，以及实际 SDK 请求格式。Django 检查和 `git diff --check` 通过。

7 份已保存的真实工具输出回放均可完整恢复；473 段逐环趋势去空白 JSON 的估算为 8536，生产编码（含解码说明）为 2604，减少约 69.5%。小结果或无收益结果保留原文。与当前完整提示和 14 工具组合的代表性调用，从 17262 降至 9442 个估算 token；该例未添加额外历史，不能代表所有请求。生产编码比早期原型多了解码说明和保护条件，不沿用原型 2538 的数字。

选择这一实现是因为本项目的长上下文主要来自重复字段的逐环工程数据，且数值、口径、缺失说明需要完整保留。与滑动窗口删消息或语义摘要相比，它不依赖模型判断哪些证据可以丢弃；代价是对自由文本或不规则 JSON 的收益有限，超预算时需要拆分问题。完整 QDEC 证据选择器暂未接入：现有合成实验未显示其优于简单强基线。这里不宣称列式表示本身为新算法，也不宣称已验证真实模型回答质量、费用或延迟改善；这些仍需同条件 A/B。

本次没有重启服务、迁移业务库、提交代码或部署。现有运行服务是否加载改动需要另行确认。

## 后续真实模型验证（2026-10-12）

已补做固定工具快照的真实API对照：30题每组3次默认预算测试，另对10道长题采用共同32k实验窗口。配置为deepseek-chat，响应模型名实际为deepseek-flash。长题实际输入token减少40.4%，但字段与解释通过原始26/30、压缩25/30；跨段求和与范围聚合仍会出错，不能宣称无准确性损失。窗口只在评测进程改变，生产配置未调整。

纠正回放预算解释：上述阅读实验使用tool_choice=none。后续完全相同messages/schema的4次API对照显示，两份长输入改为auto后分别从12413增至15635、14942增至18164，均增加3222，且超过13312输入预算。因此“27/30实际输入低于预算”仅是none模式的观测，不能据此认定真实Agent误拦，生产预算与字符系数没有调低。结构性重复计数修正与供应商模板差异是两个问题。完整方法、失败案例及私有证据索引见仓库本地 `deliverables/AI_ASSISTANT_LIVE_CONTEXT_AB_2026-10-12.md`。

## 确定性统计

换刀趋势新增summary：由相同筛选记录计算total_records、replaced_count、replacement_rate_pct、segment_count和nonempty_segment_count，保留requested/effective_ring_range与计数口径。空样本比率为null；已观测但无更换才为0。旧segments及字段保留。

换刀和掘进趋势的末段标签截到实际数据上限，避免固定分段标签超过筛选范围；不会增加或删除明细记录。换刀统计明确仅来自现场明细，地层明确来自地层基础信息表且没有开仓点过滤或磨损关联。

地层明确标签出现次数、地层记录数及按项目和数值环号去重数；多标签或重复标签不冒充去重环数或面积。掘进趋势补记录数、分段数、范围；原分段count在单环和多环模式含义不同，缺少各指标原始sum/count时不合成原始点总体均值。

模型可见工具说明和共用回答契约要求直接引用这些统计，范围改变后重新查询。它减少模型遍历长数组的需求，但不是对自由文本答案的全量数值校验，也不替代多范围查询正确性验证。

最终241项助手回归、Django检查及补丁检查通过。真实ToolAssistant+AgentExecutor+生产工具+只读数据库：18/18结构化回答、4/4自然回答的数字/范围/来源复核通过，44次模型调用。最大实际输入11007，最大估算低估194，小于1024安全余量；短请求仍有明显高估，不代表所有输入都能精确或保守计数。此前自然回答发现的来源误述和末段标签问题已修复后用相同问题重跑，原失败记录保留。最终证据在仓库本地`.codex-tmp/context-live-statistics-e2e-20261012-013015/`。只替代记忆load/append持久化边界，非HTTP/SSE浏览器或真实会话落库验收；数据含演示填充，不作为论文现场准确率。
