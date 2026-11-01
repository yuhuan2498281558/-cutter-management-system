# 全文上下文、事件与模型用量（阶段 A）

`llm_provider.create_chat_model()` 返回 `GuardedChatModel`。所有通过该工厂创建的模型在每次同步、异步及流式调用前检查预算，覆盖 Agent 后续工具轮次、直聊、可选润色和摘要。规则直答仍不初始化模型。

## 处理流程

1. 接收最终消息列表，复制消息，不改动执行记录。
2. 对长 `ToolMessage` 的同构标量对象数组尝试列式编码；保存列名、逐行值和明确路径，附带解码说明。只在收益大于等于去空白 JSON 的 5% 且至少 32 个估算 token 时采用。
3. 将系统提示、历史、用户问题、工具调用参数、工具结果、实际工具 schema 和调用选项纳入估算，另加消息封装开销。
4. 输入限额 = 配置窗口 − 输出上限 − 安全余量。压缩后仍超限则抛出明确错误，不静默删除证据或更改查询范围。本轮查询结果导致超限时，提示缩小范围或拆分问题；不算本轮结果、历史本身就已超限时抛出 `HistoryBudgetExceeded`，提示点「重置对话」清空历史，因为缩小范围和 new 模式都不会减少回放的历史。
5. 将输出上限实际传给供应商。供应商明确返回 `finish_reason=length` 时视为未完成；直聊/Agent 不保存该轮，也不发送成功 `done`。可选润色失败仍沿用原有的完整规则回答回退。

原 `intermediate_steps`、工具事件、参数校验及纠错关联均保留原文。列式编码不合并均值、不重算分母、不改变 TopK，不将未知值补为零；错误、异常 JSON、重复键及存在数值精度风险的输入保持原文。统计约束继续使用共用 `ANSWER_POLICY`。早前对话的精简和摘要见下文“阶段 B：自动整理”。

## 事件存储与提交

`ContextEventStore` 在 `LANGCHAIN_HISTORY_DB_URL` 指向的 legacy SQLite 中，通过 SQLAlchemy Core 的 `CREATE TABLE IF NOT EXISTS` 创建 `ai_context_events`，不涉及 Django migration。字段为：`schema_version INTEGER`、`event_id VARCHAR(32) PRIMARY KEY`、`scope_key VARCHAR(255)`、`generation INTEGER`、`turn_id VARCHAR(32)`、`seq INTEGER`、`kind VARCHAR(32)`、`project_id VARCHAR(255)`、`payload TEXT`、`created_at VARCHAR(40)`。版本当前为 1，时间采用 UTC ISO 8601；`(scope_key, generation, turn_id, seq)` 唯一，seq 从 0 按轮内顺序递增。

- `message`：LangChain 协议消息，保存实际 `enriched_input`，共享的 assistant message_log 只保存一次，完整保留 tool_calls 的 ID、名称与参数原文，逐个保存列式编码前的 ToolMessage 字符串和 UTF-8 SHA-256，最后保存最终回答。工具正文不经过 JSON 解析再序列化。
- `usage`：每次模型调用的 provider 用量，以及最后一次调用的 prompt 锚点、provider、请求模型名、实际模型名、system/schema 指纹、对应请求估算和整轮合计。未知用量为 null。
- `turn_commit`：关联 `message_store` 的 human/ai 两行 ID。`prune`、`checkpoint` 仅预留名称，本阶段不写。

事件只在成功回答后追加。事件、turn_commit、问答两行和槽位共同使用既有 SQLite 事务和 generation 检查；任一写入失败整轮回滚。失败、中断、输入超限、输出截断都不进入下轮历史。reset 在同一事务删除该 scope 的问答与事件、清空槽位并提升 generation，迟到回答不能恢复旧会话。规则直答仍只保存问答和槽位，不写事件；历史分页继续读取原 human/ai 格式，默认每页 50 条。

读取历史（`load()`、历史分页）用只读快照，不取写锁；JSON 解码在事务之外进行，长历史不会让其他用户的保存和重置排队。作用域行不存在时先短暂取写锁建好，全量 reset 递增它的 generation 后，读到旧快照的迟到写入照样被拒绝。写入仍用 `BEGIN IMMEDIATE` 并检查 generation。

## 重建顺序与项目边界

请求顺序为固定 system 与工具 schema → 按问答行顺序重建的全部已提交历史 → 当前轮上下文、槽位和问题组成的 enriched_input → 本轮 scratchpad。历史轮次为 enriched_input → assistant tool_calls → 各 ToolMessage（可重复多个调用批次）→ 最终回答。当前工作状态只出现在当前轮输入，旧 enriched_input 不重新生成；无损列式编码对相同正文确定性执行，API 历史前缀在后续轮次保持一致。

回放前检查调用 ID 唯一、结果配对及正文哈希。不完整轮次记录 warning 并整体退回该轮原问答。没有事件的旧行也只提供问答，不补造证据。不同项目轮次只带原问答，并在用户消息前加“（以下为项目 X 的对话，结果不能作为当前项目的证据）”；不带该轮工具结果。没有项目元数据的旧问答按原文保留，不能获得工具证据资格。

auto/new/continue 只影响查询条件的继承，均保留完整历史；清空对话仍使用 reset，ablate 仍关闭记忆读写。`AI_MEMORY_RECENT_TURNS` 和 `AI_MEMORY_CONTEXT_TOKEN_BUDGET` 不再截断模型上下文。已清除或本轮未启用的条件由当前输入明确覆盖，不能从历史恢复。提示词允许直接使用同项目历史工具结果解释、比较和追问；新范围、新条件或最新状态仍要求重查，已有统计契约不变。

同步和流式共用 `_history_evidence_covers()` 判断本轮能否不调用工具，满足以下条件之一才放行，拿不准时要求查库：
- 问题含“最新、实时、现在、目前、今天、截至、进度”时，一律重查。
- 问题没写环号、刀型、刀位，并且识别不出统计意图（`_followup_query_spec` 为空），或者明确指向上一个回答（这些、上面、其中、第 N 行……），属于追问，可以用历史回答。
- 其余情况：本轮范围取问题里写明的条件和解析后槽位的并集。历史里要有一次同项目、成功的工具调用（不含数据目录工具），工具属于本轮问题的工具组；它带的每个筛选条件，本轮都有且落在其内：环号区间包含本轮区间，刀型、刀位相同。没带筛选的调用覆盖任意范围；带了筛选而本轮没写的，视为本轮要全范围，不覆盖。

`AI_MEMORY_BACKEND=django` 本阶段不读写协议事件，只重建全部完整问答，同样取消 3 轮/1200 token 和 new 清空历史限制。既有 Django 摘要维护保留，但摘要不替代或重复注入原文；双写仍只镜像问答和槽位，不迁移事件。

## 真实计量与 ContextInfo v2

流式请求带 `stream_options.include_usage`，最后一个分片返回整次用量。同步和流式每次模型调用只记录一次；流式先合并全部分片，包括最后单独的 usage chunk。DeepSeek 的 `prompt_cache_hit_tokens` 单独保留，既不与 prompt_tokens 相加，也不从上下文占用扣除。

turn 的 `used` 取本轮调用峰值：每次调用优先实际 prompt_tokens，缺失时用该次估算；`measurement` 指出峰值来源，`last_prompt_tokens_actual` 单独报告最后一次调用。`provider_usage` 累加本轮已取得的 prompt/completion/cache_hit 用量，没有 usage 为 null。`parts` 始终是估算分项，实际计量时不要求其合计等于 used；memory 包括整个历史协议。`history` 提供 turns、tool_results、legacy_qa_turns、other_project_turns 和 tokens。旧字段保留，`memory.recent_turns/recent_budget` 为 null；`thresholds.evidence_soft_tokens` 已删除。

history 接口 baseline 为下一问起步预测：`最后一次实际 prompt_tokens + 当前待发请求估算 − 锚点请求估算`，将最后回答及新增输入相对原请求的增量计入。接口尚无下一问文本，按空问题及可知项目/槽位预测；完整问题发送后再计入 turn。可传 `project_id` 指定当前项目，未传时以最近已保存项目预测。schema、system、provider 或请求模型变化，或没有有效锚点时，退回完整估算；baseline 的 measurement 始终为 estimated，provider_usage 为 null。

baseline 只使用配置和纯消息编码/估算，不初始化模型客户端、不调用有副作用的 prepare、不请求供应商。供应商别名仍按最近返回的实际模型名记录；同一别名在供应商侧重新映射，只有下一次响应才能得知。直接聊天和不同工具组的 system/schema 与默认全工具 baseline 不同时也会完整估算。

### 阶段 B 前端约定（2026-10-27）

后端没提供的字段，页面不显示对应内容。精简版后端已提供除 `compaction.manual` 和 `POST /api/ai/compact/` 之外的全部字段。

- `compaction.auto: true`：后端到触发线会自动整理。面板说明改为“用到 X 时先精简早前的大查询结果……”，接近触发线时圆环提示“到了会自动整理早前对话”。
- `compaction.manual: true`：提供手动整理接口。历史至少 2 轮时，面板底部显示“整理早前对话”按钮。
- `compaction.through_sequence`：最近一次摘要覆盖到的最后一条问答行序号（legacy 为 `message_store.id`），没有摘要为 null。页面在这条消息之后画“以上对话已整理成摘要”分隔线；它后面还没有消息时不画。turn、baseline 和手动整理返回的 ContextInfo 都要带。
- `compaction.last_before / last_after`：最近一次整理前后的上下文估算，两者都有时面板显示“早前对话已整理：210k → 41k”。
- 流式事件 `{"type": "status", "stage": "compacting"}`：开始整理时发送，生成中的“正在生成”改为“正在整理早前对话”；整理结束发送 `{"type": "status", "stage": "done"}`（任何非 compacting 的值都会清除提示）。
- `POST /api/ai/compact/`：立即整理当前用户的早前对话，成功返回 `{"code": 2000, "data": {"context": <baseline ContextInfo>}}`；失败按现有格式返回 `msg`，页面显示“整理失败：<msg>”。
- memory 事件和同步结果的 `memory` 已带 `turn_sequences: [问题序号, 回答序号]`（本次已实现），页面据此给本次会话的新消息补序号。

## 阶段 B：自动整理（精简版，2026-10-27）

参考业界智能体框架“先裁剪、再摘要、保留最近原文”的分层思路，自行实现；没有引入外部代码。只在 legacy 记忆后端生效，Django 后端和 ablate 不整理（`compaction.auto` 为 false）。

**何时整理**：规则直答不调模型，不整理。其余路径在调用模型之前，按“系统提示 + 全部工具 schema + 回放的历史 + 本轮输入”估算第一次调用的输入量；有实测锚点时乘以“实测 / 估算”比例（限 0.5–1.5 倍），与用量圆环的口径一致。超过触发线才整理。

**怎么整理**：
1. 从最近一轮往前累加，装得下 `window × retain_ratio` 的完整轮次保留原文；再往前的轮次参与整理。整理以轮为单位，不会拆开工具调用和结果的配对。
2. 先精简：参与整理的轮次里，不小于 1000 估算 token 的工具结果换成“【早前查询结果已精简】……保留的汇总”，标量字段照抄，长列表换成条数。工具调用参数保留在历史里，模型需要明细时按原参数重查。精简后的结果不再算作“历史证据”，追问这些轮次的数字要重新查库。
3. 精简后仍超触发线，就把参与整理的轮次（连同之前的摘要）写成摘要。提示词见 `prompts.CHECKPOINT_PROMPT`，分为用户目标与纠正、查询范围、已执行的查询、关键数字、结论与证据限制、未完成事项六栏。摘要里的数字逐个核对，必须能在材料中找到（个位整数不查）；对不上就告诉模型并重写一次，仍对不上或模型调用失败时，改用“之前的摘要 + 每轮问题和回答开头”的节选。摘要调用的计费计入本轮。
4. 回放时，摘要覆盖的轮次替换为一问一答：问为“【早前对话摘要】……”，答为固定的确认语；之后的轮次按精简记录或原文回放。

**记录**：每次整理在 `ai_context_events` 追加一条 `kind=compaction` 的记录，payload 为 `{"mode": "prune" | "checkpoint", "through_sequence", "summary"（仅摘要）, "before", "after"}`，写入时检查 generation，对话被重置后不写。回放只看最新的摘要和最远的精简位置，因此两次整理之间历史前缀不变，供应商前缀缓存仍可命中。reset 会连同这些记录一起删除。

**超长重试**：工具调用路径（同步与流式）在供应商报上下文超长，或本地预算超限时，强制整理一次（不看触发线；没有可保留的轮次时整理全部历史）并重跑本轮。流式只在页面还没收到回答文字时重试。整理不出空间时照常报错，历史本身超限仍提示“请点「重置对话」”。

**页面**：流式在整理前后发送 `status` 事件（compacting / done）。`compaction` 字段为 `{"state": "none" | "pruned" | "checkpoint", "auto", "manual": false, "checkpoints", "pruned_results", "last_at", "last_before", "last_after", "through_sequence"}`，`history` 另带 `summarized_turns` 和 `pruned_results`。精简版不提供手动整理接口和回查原文工具。

## 配置

环境变量优先，其次是 Django settings；配置在模型首次初始化时固定。调整后须按现有流程重新加载后端模型实例。

- `AI_CONTEXT_WINDOW_TOKENS`：应用预算窗口，默认 `256000`。
- `AI_CONTEXT_OUTPUT_TOKENS`：预留并实际限制输出，默认 `8192`。
- `AI_CONTEXT_SAFETY_MARGIN_TOKENS`：默认 `4096`。
- `AI_CONTEXT_TRIGGER_RATIO`：默认 `0.8`，触发线 `window × trigger_ratio = 204800`，本轮第一次调用的预计输入量超过它时整理早前对话。
- `AI_CONTEXT_RETAIN_RATIO`：默认 `0.16`，整理时最近约 `window × retain_ratio = 40960` 的完整轮次保留原文；必须满足 `0 < retain_ratio < trigger_ratio < 1`。
- `AI_CONTEXT_COMPACTION_MIN_TOKENS`：默认 `1000`，低于阈值的工具正文不改写。
- `AI_CONTEXT_TOOL_PROTOCOL_TOKENS`：默认 `1024`，有非空tools/functions的请求额外计入一次协议预留，包括tool_choice=none；工具schema仍完整计数。用于供应商工具模板开销，与安全余量分开。

五项 token 参数必须为正整数，窗口必须大于输出与安全余量之和。配置不合法时模型初始化报错；纯规则路径仍可使用。API 默认硬输入预算为 `243712`。删除原 24000 软上限、`AI_CONTEXT_EVIDENCE_SOFT_TOKENS` 和早前结果摘要逻辑。窗口是应用的运行限制，不代表自动探测到的供应商能力。

预检计数沿用汉字 1.5、其他字符 0.25 的启发式，按消息正文、工具参数、schema 和其他选项分别计算，正文及参数不经过整包 JSON 二次转义。忽略本地消息 ID、usage、artifact 等字段，原文 tool_calls 优先于解析后重序列化的参数，重复调用只计一份；未知消息类型保守回退。工具 schema 即使在 tool_choice=none 下也保留计数。预检估算不是供应商 tokenizer 或计费值；安全余量不能保证绝不触及供应商限制。目前只支持文本内容，图片/音频请求明确拒绝。

模型调用由 `chat_model.ChatCompletionsModel` 经 openai SDK 发出，只支持 OpenAI 兼容的 Chat Completions 接口（2026-11-01 起不再支持 Ollama）。OpenAI 在请求体中用 `max_completion_tokens`；DeepSeek、`api` 和 `openai-compatible` 用 `max_tokens`。调用者可降低输出上限，不能提高。禁止动态 `model`、`extra_body`、嵌套 `options/model_kwargs` 覆盖预算。升级 openai SDK 后须回归最终请求 payload 测试。

## 阶段 A 验证与实际输出示例（2026-10-26）

完整助手套件 416 项通过（原 406 项，移除 7 项软摘要测试，新增 17 项相关测试），使用隔离 SQLite、确定性假模型和真实 AgentExecutor。覆盖五轮协议原文回放、无关键词 auto 历史、槽位清除、跨项目、失败/中断/超限不提交、事务回滚、reset、旧行与 Django 问答兼容、usage 尾分片、缓存不重复计算、锚点失效以及 history 懒初始化。旧行为断言按全文历史修改，其余校验保留。

2026-10-27 按独立审查修复三处（历史证据按范围覆盖、读取不占写锁、历史超限提示重置），新增 5 项测试，完整助手套件 421 项通过；新增测试在修复前的代码上均失败。

下面是隔离测试实际返回的完整 ContextInfo v2；provider usage 来自确定性假模型，不是真实 DeepSeek 请求。本例两个模型调用，每次 prompt=15000、completion=24、cache_hit=12000。baseline 的估算为 5831，最后请求估算为 5649，因此预测为 15000 + 5831 − 5649 = 15182。

turn：

```json
{
  "kind": "turn",
  "window": 256000,
  "input_budget": 243712,
  "output_reserve": 8192,
  "safety_margin": 4096,
  "used": 15000,
  "parts": {"system":4326,"tools":1082,"memory":0,"question":11,"results":56,"other":174},
  "results_raw": 36,
  "compacted_results": 0,
  "summarized_results": 0,
  "paged_lists": 0,
  "schema_version": 2,
  "measurement": "actual",
  "estimated": false,
  "last_prompt_tokens_actual": 15000,
  "trigger_tokens": 204800,
  "hard_input_limit": 243712,
  "provider_usage": {"prompt_tokens":30000,"completion_tokens":48,"cache_hit_tokens":24000},
  "history": {"turns":0,"tool_results":0,"legacy_qa_turns":0,"other_project_turns":0,"tokens":0},
  "compaction": {"state":"none","checkpoints":0,"pruned_results":0,"last_at":null,"last_before":null,"last_after":null},
  "page_requests": 0,
  "exceeded": false,
  "model_calls": 2,
  "thresholds": {"compaction_min_tokens":1000},
  "memory": {"backend":"legacy","recent_turns":null,"recent_budget":null,"recent_tokens":0,"included_turns":0,"summary_tokens":0,"summary_trigger_tokens":null,"pending_tokens":null}
}
```

baseline：

```json
{
  "kind": "baseline",
  "window": 256000,
  "input_budget": 243712,
  "output_reserve": 8192,
  "safety_margin": 4096,
  "used": 15182,
  "parts": {"system":4309,"tools":1082,"memory":391,"question":0,"results":0,"other":49},
  "results_raw": 36,
  "compacted_results": 0,
  "summarized_results": 0,
  "paged_lists": 0,
  "schema_version": 2,
  "measurement": "estimated",
  "estimated": true,
  "last_prompt_tokens_actual": 15000,
  "trigger_tokens": 204800,
  "hard_input_limit": 243712,
  "provider_usage": null,
  "history": {"turns":1,"tool_results":2,"legacy_qa_turns":0,"other_project_turns":0,"tokens":391},
  "compaction": {"state":"none","checkpoints":0,"pruned_results":0,"last_at":null,"last_before":null,"last_after":null},
  "page_requests": 0,
  "exceeded": false,
  "model_calls": 0,
  "thresholds": {"compaction_min_tokens":1000},
  "memory": {"backend":"legacy","recent_turns":null,"recent_budget":null,"recent_tokens":32,"included_turns":1,"summary_tokens":0,"summary_trigger_tokens":null,"pending_tokens":null}
}
```

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
