# 智能助手修复与验收

更新：2026-09-06。范围为智能助手的数据口径、流式协议、会话记忆和可重复回归；业务库的数据及运行配置未更改。

## 已实现

- 所有换刀明细查询共用有效刀位过滤，遵守现有 122 刀位范围；预建但尚未检查的空行不再充当统计样本。历史已更换记录仍计入现场观测。
- 开仓结果区分已确认的人工汇总和现场明细，显示数量来源、确认状态及不一致提示；人工确认数量不被明细总数覆盖。缺少磨损分类时不再显示异常率 0%。开仓数量属于整仓汇总，不假称已按刀型或刀位拆分。
- 刀位排行真正应用环号范围；掘进环号极值按数字计算。磨损分类兼容“崩口”和 `CHIP`。
- 刀具追溯按项目、盾构机、刀位和新旧实例关联，拆卸时的旧刀磨损不会算到同一行新安装刀具上。未知状态、推断安装环号和历史拆卸推断均明确标示；缺少依据不输出确定寿命。推荐结果仍可包含带警告的历史推断样本，不等于厂家验证结论。
- HTTP 数据查询在缺少明确项目时拒绝查询，包括推荐、寿命和检查效率问法。现有用户 scope 和项目权限边界未扩展。
- SSE 使用原生异步响应，同步 ORM 经异步桥接；连接关闭向下游传播取消。Agent 必须成功查询工具并取得完整最终输出，工具失败、无工具、空结果文本或迭代上限均不能当作成功回答保存。
- SSE 新增可选 `answer` 事件：`{"type":"answer","content":"最终权威全文"}`。它校正临时 `chunk` 文本；存储使用最终全文。客户端检查业务 code、响应类型、坏 JSON、异常 EOF，并确保单次终态和 reader 清理。
- 前端通过操作代次和稳定消息 ID 隔离历史、发送、重置、停止及卸载竞态；重置失败保留历史。“再问一次”创建新轮次，刷新后与后端一致。
- 历史默认 50 条，支持 `before_sequence` 排他游标、最多 100 条及加载更早消息，前插保持滚动位置。Markdown 支持独立列表、代码和表格，继续转义 HTML；快捷刀位使用有效的 `S1L`。
- legacy 保持 `message_store` 格式，改为同一事务写入完整 human/ai 轮次与槽位，增加索引和持久 generation；Django 也按 generation 拒绝重置后的迟到回答。双向双写包含消息和槽位。
- 记忆读取默认只取最近 6 条并保留准确总数；摘要另取最多 200 条、默认 6000 token 的未摘要完整轮次。摘要在有界后台队列执行，回答完成不再等待模型摘要。
- health 仅返回服务存活信息，不初始化或调用模型。评测命令要求明确项目，每题使用独立实验 scope，并标明计时只涵盖同步服务层。

## 验证结果

本机最终验证：

- PostgreSQL 隔离测试库：116 项通过，包含 AI、盾构业务及权限回归；使用真实 system/AI 迁移，shield 根据当前模型创建测试表。
- 前端真实源码测试：34 项通过，覆盖协议终态、乱序、停止、重置失败、逐帧输出、权威答案、历史分页、刷新一致性、Markdown 与转义。
- `npm run build`、Django 系统检查、`makemigrations --check --dry-run` 和 `git diff --check` 通过。构建仍有原有第三方 eval、大包提示；未执行完整 `vue-tsc` 检查。
- 使用真实 Vue 组件、真实 SSE 客户端与合成 API 的隔离浏览器验收通过：渐进展示、断流报错、主动停止、成功/失败重置、最终答案校正、列表/表格、再次提问刷新一致性，以及 60 条历史按 50+10 分页。1366×768 截图布局正常，无横向溢出或控制台错误。
- 实际业务库以 PostgreSQL `READ ONLY` 事务核对 6 条规则查询及项目快照，覆盖汇总、最近范围、分段、绝对范围、排行和已确认开仓；未写记忆、未调用模型。

可重复运行（从相应目录）：

```powershell
# backend
python manage.py test application.ai_assistant.tests application.shield.tests application.shield.test_permissions --settings=application.settings_ci --keepdb --noinput
python manage.py check
python manage.py makemigrations --check --dry-run

# web
node --test src/views/ai-assistant/__tests__/chat-session.test.cjs src/views/ai-assistant/__tests__/message-presentation.test.cjs src/api/ai-assistant/__tests__/stream-protocol.test.cjs
npm.cmd run build

# 仓库根目录
git diff --check
```

`application.settings_ci` 只用于测试，使用独立 `test_ai_ci` 数据库；禁止用它启动业务服务或执行生产迁移。CI 已接入该设置和前端交互测试。

## 交付和上线边界

1. 已纳入 AI `0001_initial`、`0002_assistantmemoryscope_generation` 及其必要依赖 system `0001_initial`。后者只有建模操作，没有数据脚本。shield 历史迁移仍是仓库既有的交付缺口，测试使用 syncdb 不代表完整业务迁移链已通过部署验收。
2. 当前默认仍为 `legacy`。首次使用新版 legacy 时会自动创建伴随 generation/slots 表及索引；原消息格式保持兼容。切换 Django 前按既定流程执行迁移、旧历史 dry-run、正式导入及消息/槽位对账。本次没有对真实业务库运行 migrate、修改环境或切换 backend。
3. 双写是尽力同步，不是跨库事务；镜像失败保留主库完整轮次并记录日志。所有 worker 应使用同一 active backend，对账后统一切换；不要混合两个主写后端运行。
4. 后台摘要为单进程单 worker、最多 8 个待处理 scope；重启或队列满可能推迟摘要，完整历史不丢失。CAS 冲突、模型失败或超预算保留旧摘要，后续请求重试。它不提供持久任务队列的交付保证。
5. 本轮未调用外部真实模型，未验收生产反向代理或完整登录态应用；Agent 使用真实 LangChain 编排配合假模型测试，浏览器使用合成服务。上线仍需验证目标模型、代理流式首包和历史对账。
6. 后续独立增强可增加“待确认开仓汇总 / 待厂家反馈 / 待归档旧刀”只读工作清单。项目权限、多会话隔离和自动业务写入不在本轮范围。

## Git 与回滚

修改前检查点为 `7d5f5ec`，工作分支为 `codex/ai-assistant-hardening`。共享分支另有明细页任务提交 `953cab0`、`7012812`，必须保留。

代码与验证提交为：

- `d11238f`：统计和生命周期口径。
- `d545bd9`：原子记忆、重置代次和迁移。
- `3a8c61d`：异步流、会话交互、分页和后台摘要。
- `2cfa2ef`：评测隔离和 CI。

回滚时先检查 `git log` 和工作区，仅按逆序 `git revert 2cfa2ef 3a8c61d d545bd9 d11238f`，保留其他任务提交。不要对整个分支执行 `reset --hard 7d5f5ec`。代码回退时保留新增表、字段和旧历史库，数据库逆向迁移需另行核对，不能把删除历史当作代码回滚。交付说明另行提交，不影响业务运行。
