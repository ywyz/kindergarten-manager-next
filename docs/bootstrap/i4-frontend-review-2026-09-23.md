# I4 第三片前端审阅（2026-09-23）

审阅基线：`39d58df7e674e1c9ef9369811c1dfa9524ac6815`，上一提交 `cb121c4`。本轮仅审阅、基本检查与后续建议，不修改业务实现，不执行第四片数据库／浏览器验收，不提交或推送。已有 `work/` 内容保留。

## 当前结论

类型检查、构建通过，但第三片仍有需要修复的交互正确性问题。不能把“前端已实现／能构建”表述为“I4 已验收”。

使用 [Codex with ChatGPT](https://chatgpt.com/g/g-p-6ab3c61acea48191aa003d8a6ab6fb81-kindergarten-manager-next/c/6ab3ca7f-4040-83ea-9f05-5971d56ba62d) 完成工作区核验并请求独立审阅。页面曾崩溃；用户重新加载后，已取回完整结构化审阅回复（`STATE: PLAN / c2c_a493 / ITERATION: 0`）。最终意见确认 R1–R3，与本地结论一致；推荐先做第三片小修复，再单独进入第四片验收，没有授权实现。ChatGPT 在最终汇总前也读取了本报告，因此不能把最终一致表述成完全盲审；R1、R2 已在其此前中间回复中独立指出。Codex 已直接读取提交差异，完成本地审阅与以下复现；ChatGPT 侧只能读取当前源码，未核验任意提交范围差异。此次恢复未重复发送任务或运行检查。

### R1 — P1：确认冲突重提会确认尚未展示的新草稿

位置：`frontend/src/views/WeeklyPlanView.vue` 的 `resubmitConflict` 确认分支（754–756 行）。

触发：负责人查看 v1 并勾选事实确认；管理员保存 v2；负责人确认收到 VERSION_CONFLICT；点击“以服务端为基准重提”。代码只取 `conflict.server.draft.version`，立即调用 `doConfirm(expected)`，没有展示 v2 内容或刷新确认事实，且保留旧 ack。

影响：用户仍看到 v1，却可以确认管理员刚改过的 v2。后端只验证目标草稿版本及两个 ack，无法补足前端缺失的复核动作。

ChatGPT 补充了同一根因的另一条分支：若重提 v2 返回 `CONFIRM_ACK_REQUIRED`，普通 `submitConfirm()` 仍使用未更新的 `detail.draft.version`（v1），再次提交会重新进入版本冲突。修复时需同步更新确认所依据的服务端草稿版本、内容和事实，不能只修改请求中的版本号。这一分支本轮为源码路径核对，未新增运行复现。

建议：确认冲突的“重提”应进入最新草稿复核态，展示最新内容与事实、清空旧 ack，待用户再次明确确认后发送请求。保留本地未保存输入；不得把复核变成自动保存或隐式刷新来源。

### R2 — P1：确认成功会丢弃未保存输入

位置：`frontend/src/views/WeeklyPlanView.vue` 的 `doConfirm` 成功分支（约 659–662 行），以及 `load`／`applyFormFrom`。

触发：修改主题或手工栏目，不保存，确认已保存草稿。界面允许该动作，并声明未保存输入不会被丢弃；成功后却调用 `load()`，用服务端内容重置表单和 dirty 状态。

建议：只更新确认结果、服务端状态与历史，同时保留 dirty 字段和本地输入。确认目标仍是已保存草稿，不得擅自将未保存内容自动保存／确认。

### R3 — P2：周计划请求被导航失效后，忙碌标记无法清除

位置：`frontend/src/views/TeacherView.vue` 的 `openPlan`、`openWeekly`（约 114–149 行）。

触发：点击周计划，响应返回前打开日计划。`openPlan` 增加 `weeklyRequestId`，旧请求的 finally 因序号不符不清除 `weeklyCreatingKey`；返回日历后所有 `openWeekly` 调用均因忙碌标记直接返回。

建议：导航离开时显式结束该请求的 UI 忙碌状态，同时继续阻止旧响应导航回来；列表、详情、日计划切换应采用一致的请求失效规则。

## 实际验证及其边界

- `frontend/` 下 `npm run typecheck`：通过。
- `frontend/` 下 `npm run build`：通过，有 bundle 大小警告；本轮不为此开展无关优化。
- 临时脚本 `/tmp/kg-i4-review-repro.cjs`：读取当前 Vue 文件的 script setup，使用现有 TypeScript 转译与 Vue 响应式运行，替换 API 和生命周期为受控桩，确认三个问题的状态转换。
  - R2：确认后本地主题回到服务端旧主题，dirty=false。
  - R1：页面仍为 v1 时发出 expected_draft_version=2 的确认，复用旧 ack。
  - R3：离开再返回后 weeklyCreatingKey 仍为原周次，后续点击被阻塞。
- 以上是脚本级定向复现，**不是 DOM 点击、完整端到端或 MySQL 事务验证**。
- 本轮未启动 API、Vite、数据库或容器，未安装依赖，未读取凭证，未运行全套后端测试。

## 下一步建议

1. 第三片修复片：OpenCode 单一写入上述两个 Vue 文件及必要的定向回归检查。只修复 R1–R3，不重构 1700 行组件，不扩展产品规则。
2. 修复后按 I4 规格 §10–12 单独开展第四片：隔离 MySQL 8.4／InnoDB，V1–V14 集成与 §8 浏览器交互，尤其双标签冲突、管理员修改、未保存输入与来源变化；记录实际通过／失败／未执行。
3. 第四片完成后再进入 Word 导出最小切片的实施准备。它消费不可变确认版本，比同时引入 AI、提示词与持久任务更容易验证教师的完整交付路径；AI 仍在首版范围中。
4. 在相应工作结束时定点更新路线状态。当前 readiness 的“代码未授权”是旧规格阶段记录，与已有 I4 实现提交不同步，不应作为后来用户授权不存在的证据。

## 可交给 OpenCode 的修复任务草案

以下是建议任务，尚未下发，不代表本次审阅已授权实现：

```text
基线：39d58df，先检查 git status，保留其他工作。
读取 docs/bootstrap/i4-frontend-review-2026-09-23.md 与 I4 规格 §8。
只修复 R1、R2、R3，主要写入 WeeklyPlanView.vue、TeacherView.vue；
若需要增加回归文件，限于上述三个状态转换，不引入新依赖。

必须满足：
1. 确认冲突重提先展示最新草稿和事实、重置 ack；用户再确认前无确认请求。
2. 确认已保存草稿后，本地未保存输入及 dirty 标记仍在，可继续保存；
   不自动保存、不隐式刷新来源。
3. 周计划请求期间切到日计划／列表后，旧响应不得抢回导航，
   返回后周计划入口可再次使用。

执行定向回归、npm run typecheck、npm run build；报告实际结果。
不改后端契约、ARCHITECTURE.md，不启动数据库或第四片验收，
不安装依赖，不提交、推送或部署。遇到范围外问题仅记录。
交付：改动文件、每个问题的修复行为与检查结果、尚未验证事项。
```

## 协作建议（讨论稿，不修改工具配置）

| 角色 | 建议职责 | 交付方式 |
| --- | --- | --- |
| 用户 | 确认产品行为、优先级及有后果的资源／发布操作 | 决策与反馈 |
| Codex | 任务切分、跨层定位、复现、集成判断与最终交付；需要时也可直接承担一片实现 | 可追溯发现和实际验证证据 |
| OpenCode | 当前主实现者；沿用已熟悉的上下文完成修复与后续清晰切片 | 范围内 diff、检查结果、未决问题 |
| ChatGPT | 关键规格、跨层状态机与阶段边界的独立推理／审阅 | 有代码依据的意见，不作为唯一验收者 |
| Pi + 方舟 Coding Plan | 先试一个明确的小任务，例如协议核对、定向回归或低风险修复；表现稳定后承接完整切片 | 以具体模型、返工率、耗时和套餐消耗评价 |

建议常规流程为“一个实现者 → 一次有证据的审阅 → 针对发现修复”。无需每次都串行经过 Codex、ChatGPT、OpenCode、Pi 四轮。关键需求不确定时才增加 ChatGPT 讨论；只有文件和职责可隔离时才并行，并由一个角色管理共享 Git 状态与集成。复用同一提交上的有效检查。

每个任务交接只需：基线提交、目标、允许改动范围、相关规格、完成条件、必要检查、停止条件。代码和文档是事实来源，聊天摘要只补充最近决定。当前仓库的历史提示词“用户不再切回 Pi”属于旧轮次安排，不能覆盖本轮用户讨论未来 Pi 的新意图。

Pi 是工具载体，Coding Plan 是模型接入／订阅方式；不能仅凭这两个名字判断模型能力或成本。具体模型尚未核验，不推荐盲目固定某个模型。正式试用可选未来自然发生的两三项小任务，记录一次通过率、主审修正时间、耗时与套餐用量，避免为了对比重做整片功能。

资料核对（2026-09-23）：

- [OpenAI 官方最佳实践](https://learn.chatgpt.com/guides/best-practices)：明确完成条件、定向检查和代码审阅；工具应服务实际工作需求。
- [OpenCode Agents](https://opencode.ai/docs/agents/)：agent 可配置模型、工具和权限；实现与分析角色可以分开设置。
- [Pi 模型文档](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md)：支持配置兼容服务，实际协议行为仍需核对。
- [方舟 Coding Plan 快速开始](https://docs.volcengine.com/docs/ark/coding-plan-personal-get-started?lang=zh)：OpenAI 兼容套餐地址为 `https://ark.cn-beijing.volces.com/api/coding/v3`，Anthropic 兼容地址为 `https://ark.cn-beijing.volces.com/api/coding`；普通 `/api/v3` 不消耗 Coding Plan 额度。未来配置 Pi 时需匹配协议和套餐地址；本轮未修改配置或发起模型调用。
