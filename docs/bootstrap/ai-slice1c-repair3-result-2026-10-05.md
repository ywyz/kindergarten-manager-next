# AI 1C 第三轮最小补修结果记录（2026-10-05）

依据：[第二轮补修复审 T1–T4](ai-slice1c-repair2-review-2026-10-05.md)、[第三轮补修交接](ai-slice1c-repair3-opencode-prompt-2026-10-05.md)、[1C 规格](../specs/ai-settings-ui-1c.md)、[1B API 定稿](../specs/ai-settings-api-1b.md)。只处理 T1–T4 及复审指出的报告/代码差异；S1–S4 与 R1–R7 既有修复全部保留。**本记录是编码与离线定向验证证据，不是产品验收；真实浏览器 C1–C7 桌面验收仍未执行。**

## 1. 开工与收工状态

- 施工前 HEAD：`1647fc934d41b29a844a807d454031e66a2b45af`（与复审记录一致）；全程未 commit/push，收工后 HEAD 不变。
- 施工前 `git status` 67 项（含协调者本日新交付的两份复审/交接文档）；全程未回退、未覆盖、未清理任何既有改动；收工后新增仅本报告。
- 未读 `.env`／私密密钥；未安装依赖/Skill/MCP；未另起代理；未连接数据库/供应商；未启动任何服务器；未 SSH/迁移/部署/commit/push；未初始化浏览器。
- 本轮改动文件：
  - `frontend/src/components/ai/PromptGuidanceCard.vue`（T1/T3/T4）
  - `frontend/src/components/ai/AdminPromptDefaultsCard.vue`（T2）
  - `frontend/src/components/ai/AiConfigCard.vue`（报告纠正，使代码与 repair2 §5 声明一致）
  - `frontend/scripts/ai-settings-1c-state-regression.mjs`（新增 T1–T4 与视图/模板回归）
  - `docs/bootstrap/ai-slice1c-repair3-result-2026-10-05.md`（本报告）
- 未改：backend 全部、auth 业务规则、日/周/Word、依赖/锁、`ai-settings-shared.ts`、`api.ts`/`types.ts`、`SettingsView.vue`（本轮未触碰）。

## 2. T1（P1）：适配在途锁定普通编辑面（采用规格的"请求期明确锁编辑"方案）

复审复现：适配提交挂起期间普通 textarea 仍可编辑，而 `commitWriteOut` 的 adapt 分支只对账 `adaptDraft` 随后整表替换 `normalDraft`——普通框在途输入被静默丢弃。

**最终选择：最小锁定**（复审建议的优先路径），不引入"双框同字段在途合并"的新产品规则：

1. 新增 `adapting: reactive(Set)`（每任务），由 `submitAdapt` 在捕获 token/置 busy 的同一步置位，finally 在与 busy 相同的所有权条件下（`guard.alive(at) && busyAt.get(taskType) === at`）释放；`clearStaleBusy` 释放死 epoch 的残留锁（adapting 与 busyAt 恒成对，新所有者切换时不会卡死）；`teardownAll` 一并清空。
2. 模板：普通 textarea 增加 `:disabled="adapting.has(selected!)"`；"放弃适配草稿"增加 `:disabled="busy.has(selected!)"`，且 `discardAdaptDraft` 函数体补 `if (busy.has(taskType)) return` 兜底（含 Enter/重复点击边界）。适配框本身**不锁**——其既有在途对账路径按选择维持有效（见下）。
3. 锁定覆盖的全部实际可编辑入口盘点（适配飞行的其余入口均已 busy 禁用，本轮未动）：保存修改／放弃修改／打开默认比较／打开完整适配／比较面板各按钮／冲突块按钮／重新获取／载入最新目标均为既有 busy 绑定；新增仅普通 textarea 与放弃适配草稿两处；任务切换与"关闭适配"保持既有孤儿化语义不变（复审已确认成立的路径，不倒退）。
4. 锁定后飞行的唯一可编辑面是适配框：其 `boxAtSend` 快照对账不变；响应后普通框落服务端 committed 值（无伪 dirty、无静默丢字）；在途期间不存在第二份可编辑草稿，故不产生"丢一份"或"复活已放弃文字"。
5. **既有在途对账路径维持有效（未适配/未删任何反例）**：普通保存同字段在途输入（S2）、接受期间未选/所选字段输入（S2b）、适配框同字段在途输入（S2c）——这些路径对应的编辑面在各自请求期间保持可编辑，回归原样通过。

新增回归（`T1` section，8 条）：

- 适配飞行置 `adapting.has(TASK)=true`（即 textarea disabled 绑定的驱动状态）且 busy 锁定写按钮；响应落地后锁释放。
- 适配框在途输入 `LATE-ADAPT-TYPE` 仍经既有对账保留为普通面 dirty；未触及字段落 committed（dirty 恰为 1，无伪 dirty）；committed map=提交全量；面板与 target 成功后关闭清空。

测试说明：按锁定方案，本轮**没有**再模拟"直接改被锁普通输入"的路径作为用户输入断言（复审明确不把直接 mutation 当正常用户输入）；具体反例由"锁定状态 + 模板绑定检查 + 响应后无丢字/无伪dirty"共同闭环。

## 3. T2（P2）：管理员冲突门禁随任务保存

复审复现：409→比较出现→不选择→重点当前任务按钮，`selectTask` 无条件清全局 `conflictLatest/conflictPending` 后命中缓存返回，旧基线与草稿仍在，再次发布产生第二次 PATCH。

代码（`AdminPromptDefaultsCard.vue`）：

1. `AdminTaskState` 增加 `conflictLatest / conflictPending`——冲突状态与每任务 `detail/draft` 同缓存。
2. `selectTask` 不再清冲突状态（重选当前任务与 A→B→A 均保留门禁与比较视图）；任务 B 无继承冲突，返回 A 时视图与门禁原样恢复。
3. `save()` 门禁改为检查**当前任务 state** 的冲突字段；成功同时清两者的 task state；409 比较 GET 成功/失败分别写 task state 的 `conflictLatest/conflictPending`（失败保持安全恢复入口）。
4. `loadLatestIntoInputs/keepInputsRebaseVersion/retryConflictLatest` 全部作用于 selectedState；模板经与原引用同名的 computed（`conflictLatest/conflictPending` 派生自 selectedState）**零改动对接**，发布按钮 disabled 绑定不变但语义变为每任务。
5. 账号切换/卸载仍经 `states.clear()` 连同冲突状态一起清空（teardown 语义不变）；旧 epoch 失效、finally 所有权、`saving/detailLoading` 新所有者清位规则全部保留，未清新请求锁。

新增回归（`T2` section，14 条）：

- 409→pending+latest(v8)→重选当前任务：pending/latest 原样保留，再点发布无第二次 PATCH（写计数 1）。
- A→B→A：B 无继承冲突；返回 A 视图与门禁恢复；仍未选择时无写入；显式"保留输入"清门禁且草稿未动；下一次发布 expected=8（写计数 2）。
- 比较 GET 失败变体：pending 保持且无比较视图；重选后失败态仍在、仍无写入；`retryConflictLatest` 取得 v5；显式 keep 后发布 expected=5。

## 4. T3（P2）：pendingConflict 自身保护基线、视图与写门禁

复审复现：409→pending→用户把文字改回旧基线→重选任务触发 GET，`noteFreshDetail` 未检查 `pendingConflict` 而直接采用 fresh 并清冲突（基线静默推进 rev1→3）。

代码：`noteFreshDetail` 停放条件首位加 `d.pendingConflict ||`——未解决的冲突本身即停放理由，即使 dirty=0、适配未编辑或面板已关闭；只读 GET／重选／切换返回只能刷新停放的 latest，永远不能自动清 pending 或推进 expected；解除只剩显式动作（载入最新/保留修改/比较重载/适配冲突解决）。

新增回归（`T3` section，13 条）：

- 回退文字（dirty=0）后重选当前任务：GET 成功只停放 latest（rev3），pending 保持，基线仍 1，保存被门禁拦住（写计数 1）。
- GET 失败变体：pending 保持；`retryConflictLatest` 显式重取（rev4 停放）；`keepEditsNewBaseline` 解除并移动基线到 4。
- 远端已适配变体：停放的 fresh 为 `adaptation_required`——pending 仍由 GET 保持；显式 `adoptLatest` 落适配态并清冲突；随后 `openAdapt` 可达（无死锁）。

## 5. T4（P2）：比较重载绑定发起时面板身份

复审复现（页面可达流程）：真实接受 409 形成 stale→点"载入最新默认并重新勾选"（GET 挂起）→"关闭比较"→旧 GET 返回 503，reload 的 catch 只有 `detailOwnerOk` 检查 → 面板已关闭仍 setAlert（`closed=true, alertRelit=true`）。

代码：`reloadCompareLatest` 在入口捕获发起时的 compare 对象身份 `panel`（无面板不发起）；success 与 catch 在 `detailOwnerOk` 之外一律要求 `d && d.compare === panel` 才落任何面板状态（替换比较、清勾选、清 pending、setAlert）；面板已关闭/已更换时整响应孤儿化——任务级 `pendingConflict` 保留为可见恢复入口，面板错误不重新点亮；finally 的 busy/busyAt token 所有权检查保留（旧 finally 不操作较新请求锁）。

新增回归（`T4` section，14 条；全程真实动作驱动：接受 409→companion→stale→载入挂起→关闭→迟到响应，不设 adaptOpen/compare 冒充）：

- 真实 409 形成 `stale=true + pendingConflict=true`；重载 GET 挂起期间持有写锁（busy）——该时刻"打开默认比较"按钮模板上被 busy 禁用（复审同样确认），不在测试中用直接函数重开冒充产品路径。
- 关闭面板（关闭按钮无 busy 门禁，可达）→用户清掉旧提示→迟到 reload **error**（未知码 raw 503）：不点亮任何提示、面板保持关闭、任务级 pending 保留（恢复入口仍在）、无卡死 busy。
- 迟到 reload **success**：完全孤儿化（不换面板、无提示、不触碰任务级停放数据），恢复链（重取→保留修改）仍可重开比较面。

## 6. 适配编辑→关闭→SettingsView 返回确认（真实卡片 exposed 接入页面驱动）

按交接要求补齐上轮"桩卡片页面驱动"的升级：`T1-View` section 同时挂载**真实指导卡**（真实 `<script setup>` + 真实 Vue reactivity）与真实 SettingsView 脚本，把真实卡的 `exposed.hasUnsavedChanges` 直接接入页面 `promptCard` ref（其余两卡仍为桩），不再伪造卡片返回值：

- 干净页面：`requestLeave('back')` 直接放行（go-back）。
- 真实卡 openAdapt→编辑→**真实 `cancelAdapt` 关闭**→暴露检测为 true→`requestLeave('back')` 打开确认行；`cancelLeave` 留在页面。
- 真实卡显式"放弃适配草稿"→干净→再次返回直接放行（go-back 第二次）。
（既有桩驱动场景保留未动，两种驱动并存。）

## 7. 模板绑定检查补充（不替代 DOM 验收）

`T-模板` section（沿用 vue/compiler-sfc parse，退化为源码绑定）新增断言：

- 普通 textarea `:disabled="adapting.has(selected!)"`（T1 锁定的用户面绑定）；
- "放弃适配草稿"的 busy-disabled 绑定；
- "载入最新默认并重新勾选"的 `v-if="selectedDraft.compare.stale"` 且 busy-disabled（T4 审阅可达入口）;
- 管理员冲突视图绑定每任务 state（selectedState 派生 computed）。

## 8. 报告纠正（repair2-result §5 与源码差异）

复审指出：repair2-result §5 称"配置卡的 load 重新读取不再清空活跃冲突视图（conflictLatest 移出 load 成功路径的清理点）"，但当时 `AiConfigCard.vue` 的 `load()` 成功路径**仍清空** `conflictLatest/conflictPending`——声明与代码不符（该路径在模板上位于无 baseline 分支，无可达 UI 冲突态，未列为部署阻塞）。本轮处理：

1. **修正代码使声明成立**：移除 `load()` 成功路径对 `conflictLatest/conflictPending` 的清理（显式重读永不清冲突视图，用户仍须显式选择）；代码现存行为与 §5 声明一致。
2. **明确声明差异事实**：repair2 当时的代码并未实现该声明，声明不能当作验证证据；本报告即为书面纠正，repair2-result 原文按要求保留不覆盖。

## 9. 实际命令与结果（Node v26.10.0，frontend 目录）

| 命令 | 结果 |
| --- | --- |
| `npm run typecheck`（vue-tsc --noEmit） | 通过，退出 0，0 错误 |
| `npm run build`（vite build） | 成功；既有 >500kB chunk 警告保留（非本片引入） |
| `node scripts/ai-settings-1c-check.mjs` | **29/29 通过**（原共享函数定向检查，未删未改） |
| `node scripts/ai-settings-1c-state-regression.mjs` | **258/258 通过**（原 204 项全保留；新增 54 条 T1–T4/视图/模板断言） |
| `git diff --check` | 通过 |
| 外部 grep 复核脚本输出 | 合成 secret／raw 标记命中 0 |

回归在成形过程中捕获的真实问题（harness 侧次序修正，非组件缺陷）：T4 场景中接受 409 的既有提示在迟到重载结果到达前未被清除会与断言混淆——按复审复现口径改为"用户可关闭提示后再到达"，反例本身（关闭面板后迟到结果不点亮）保持成立。

## 10. 未执行项与偏离（如实）

- **真实浏览器 C1–C7 桌面验收未执行**（不启动任何服务器/浏览器/实例）。
- 离线 harness 只编译 `<script setup>` 并以真实 Vue reactivity 驱动；无 DOM——disabled 绑定的实际交互、按钮可视性仍是桌面目视项；模板绑定检查不替代 DOM 验收（已在脚本注释与本报告明示）。
- T1 采用"适配请求期锁普通编辑面"方案（规格二选一之一）；普通保存/接受期间输入自由的快照对账路径与适配框在途对账按选择全部保留（未删任何反例；仅 T4 两条断言按"用户可关闭提示"的复核口径调整时序，原因如 §9）。
- "面板挂起期间被替换后再到的重载响应"只能经不可达的直接函数重开构造（该时刻打开按钮被 busy 禁用，复审亦不列为产品路径），身份门控在代码层覆盖该情形；本轮仅以可达的关闭/迟到序列做断言，未夸大覆盖。
- 适配飞行期间"关闭适配"按既有孤儿化语义保持可用（复审已确认该路径成立），未纳入本轮锁定范围。
- `AdminPromptDefaultsCard.detailSnapshotRevision` 历史残留未引用代码仍未删除（非本轮范围）。
- 1A/1B 后端、MySQL、迁移与既有日周/Word 未重跑；未 commit/push。交付到此停止，等待协调者只读复审；不部署、不启动下一业务切片。
