# AI 1C 第二轮最小补修结果记录（2026-10-05）

依据：[补修复审 S1–S4](ai-slice1c-re-review-2026-10-05.md)、[第二轮补修交接](ai-slice1c-repair2-opencode-prompt-2026-10-05.md)、[1C 规格](../specs/ai-settings-ui-1c.md)、[1B API 定稿](../specs/ai-settings-api-1b.md)。作用范围仅限复审 S1–S4 边界；R1–R7 既有修复保留未动，不重做 1C。**本记录是编码与离线定向验证证据，不是产品验收；真实浏览器 C1–C7 桌面验收仍未执行。**

## 1. 开工与收工状态

- 施工前 HEAD：`1647fc934d41b29a844a807d454031e66a2b45af`（与复审记录一致）；全程未 commit/push，收工后 HEAD 不变。
- 施工前 `git status`：66 项既有工作区改动（1A/1B 后端、全部历史报告、`AGENTS.md`、`api.ts`/`types.ts`/`SettingsView.vue` 既有修改等）逐项保留，未回退、未覆盖、未清理；全程 status 变化仅涉及本片允许文件。
- 未读 `.env`／私密密钥；未安装依赖/Skill/MCP；未另起代理；未连接数据库/供应商；未启动任何服务器；未 SSH/迁移/部署/commit/push；未初始化浏览器。
- 本轮改动文件：
  - `frontend/src/components/ai/PromptGuidanceCard.vue`（S1/S2/S3）
  - `frontend/src/components/ai/AiConfigCard.vue`（S4）
  - `frontend/src/components/ai/AdminPromptDefaultsCard.vue`（S4）
  - `frontend/scripts/ai-settings-1c-state-regression.mjs`（增强组件回归，无新依赖）
  - `docs/bootstrap/ai-slice1c-repair2-result-2026-10-05.md`（本报告）
- 未改：backend 全部、`auth` 业务规则、日/周/Word、依赖/锁、`ai-settings-shared.ts`、`api.ts`/`types.ts`（本轮未再触碰）。

## 2. S1（P1）首次详情 loading 所有权与 seq finally

代码（`PromptGuidanceCard.vue`）：

1. 新增 `detailLoadingAt: Map<string, number>`：首次建档 loading 槽位由**发起该 GET 的请求**（其 guard token）持有。
2. `selectTask` 在 `guard.bump()` 后释放全部失效槽位（ owning epoch 已死 → `detailLoading.delete` + 槽主记录删除），再进入原有 `detailLoading.has()` 短路判断——失效槽位不再永久卡死，新请求可重试；同任务在途存活写请求的早期 return 不受影响。
3. 首档 finally 改为三重检查：`guard.alive(at) && detailLoadingAt.get(taskType) === at && detailSeq.get(taskType) === req`——旧 finally 不能清新请求的槽位。
4. `refreshDetail` finally 由"仅 epoch 检查"改为 `guard.alive(at) && detailSeq.get(task) === req` 才清 `d.refreshing`：同 epoch 内重叠的同资源旧 finally 不会解锁较新的在途请求（复审要求"所有同资源 detailSeq 的 finally 也检查序号所有权"）。`teardownAll` 同步清空 `detailLoadingAt`。

新增回归（脚本 S1 两个 section，共 16 条）：

- 首次 A GET 未完成 → 切 B（断言 A 失效槽位被新所有者释放）→ 回 A 发出新 GET（修复前被 `detailLoading.has` 卡死、计数不变）→ 迟到旧 GET success（v99）被丢弃，A 保持 retry 结果 rev7 → 再次选中 A 能正常刷新读取（rev8）；`getPromptDetail` 总数 4（A/B/A-retry/A-refresh）。
- 迟到旧 GET **error**（503 + 未知码 raw 变体）：不污染新失败状态（`detailError` 不被覆盖），错误行的 `selectTask` 重试路径可再读取（`detail.state === 'initialized'`）。
- 同 epoch 两次重叠 `refreshDetail`（seq1/seq2）：解析旧 seq 的 **成功响应** 被丢弃（seq 所有权检查）；旧 finally 在新请求在途时**不清 refreshing**（修复前仅 epoch 检查会提前解锁）；新 seq 到达后状态为 最新响应、 finally 正常清位。

## 3. S2（P1）提交过的同一字段请求后再输入必须保留

代码：`commitWriteOut(d, out, submitted, boxAtSend, boxSource)`：

- 三个写路径在**请求发出时**捕获全量框快照：`saveNormal` 与 `acceptSelected` 捕 `{ ...task.normalDraft }`，`submitAdapt` 捕 `{ ...task.adaptDraft }`（`boxSource:'adapt'`）。
- 回写对账规则（响应永远来自 `out.guidance_map`，不复活旧文字）：
  - 已提交字段：当前框文字 === 发出时快照 → 落到服务端 committed 值（干净）；**同一字段在途新增输入（≠快照）→ 保留为 dirty**（与 committed 不同，受 GET 保护，下次保存按新基线提交）。
  - 未提交字段：保持既有"真实更新保留/否则回服务端文字"语义。
  - 适配路径：在途输入保留为 `normalDraft` 未保存文字（面板成功后关闭，文字带入普通编辑面，不丢失、不伪装已适配）。
- `initialize`（`applyInitOut`）维持响应合成——未初始化页无任何可编辑输入，实际可编辑边界即响应 map；`rejectDefault` 不含文字变更，无复活面。旧的"对 submitted 键无条件写响应值"路径已消除。

新增回归（S2/S2b/S2c，共 15 条）：

- 保存路径：提交 `SUBMIT-ME` 后在**同一字段**在途输入 `TYPED-AFTER-SUBMIT` → 响应后框中文字仍为在途输入（修复前为 submitted 值）→ dirty 保护 → 与响应一致的后续 GET 仍显示在途输入 → 再次显式保存携带该文字与 expected=2 → 干净。
- 接受路径：所选字段落服务端 committed 文字、无伪 dirty；**另一字段**在途输入保留为 dirty；第二轮在同一所选字段在途输入同样保留；accept 目标始终为用户所见比较快照。
- 适配路径：未编辑字段落 committed 提交值；在途对适配框的输入保留为普通编辑面 dirty 文字；committed map = 目标全量；适配成功关闭面板与 target。
- 初始化：响应合成编辑面（f1/f2 = INIT-1/INIT-2），无伪 dirty（其刷新 GET 返回合成后状态，mock 按调用次序提供，不复活旧文字）。

## 4. S3（P1）适配/普通 dirty 与快照生命周期

代码变更：

1. `adaptTarget` 升级为 `{ contractVersion, fields, prefill, carried }`：`openAdapt`/`discardAdaptDraft`/`resolveAdaptConflict` 均以**独立拷贝**记录该面板打开/重载时的组合预填，`carried` 记录显式重开/解决冲突时带入的未发送用户文字。
2. `isAdaptWorkDirty`（替代只判断 map 非空的 `isAdaptDirty`）：预填未动 ≠ dirty（"打开仅预填不算改动"）；文字偏离预填 = dirty；被移除字段的未保存原文总计入；无绑定时按残余草稿判断。
3. `noteFreshDetail` 停放条件从"normal dirty"扩展为 `isDirty(d) || isAdaptWorkDirty(d) || d.adaptOpen`——**适配 dirty 或面板开启时背景 GET 只停放 latest，不推进编辑基线/适配 expected**；显式动作（`resolveAdaptConflict` 等）是唯一推进途径。
4. `cancelAdapt` 保留草稿与 target 预填基线（关闭 ≠ 放弃）；`anyDraftDirty` / `hasUnsavedChanges` 同时计入普通与适配（含关闭后面板）→ 关闭保留的编辑文字仍属未保存，SettingsView 离开必确认（真实流程驱动，见 §6）。
5. 面板关闭真正失效在途请求：`acceptSelected`/`rejectDefault` 在 success **和** catch 全部以面板对象身份判定（关闭/重开后迟到响应既不落状态也不点亮 notice；409 的任务级冲突停放保留，保证恢复入口）；`submitAdapt` 成功/错误均要求 `d.adaptTarget === target && d.adaptOpen`——真实 `cancelAdapt` 即 orphan，不再出现"关闭后旧 success 抢闸"；reject 的目标改为**打开比较时的快照** `compare.defaultValue.default_revision`（此前用 `detail.latest_default`，后台 GET 可推进 v2 而拒绝实际打到 v1）。
6. 模板：适配区 `载入最新目标` 按钮条件从 `pendingConflict && latest` 放宽为 `latest`（停放的 newer 状态始终有显式出口）；冲突块显示条件见 §5。

新增回归（S3 四个 section，共 24 条；面板关闭/重开全部走真实 `cancelAdapt`/`closeCompare`/`openAdapt` 动作，不再直接写 `adaptOpen`）：

- 预填不算改动：openAdapt 后 `hasUnsavedChanges()===false`。
- 编辑 → 真实关闭仍属未保存（hasUnsavedChanges=true，离开须确认）；重开保留文字且 `carried` 记录；显式"放弃适配草稿"清除。
- late accept success/error（真实关闭后）完全 orphan：无 commit、无 alert；仅发出一次请求。late reject success 不推版本、late error 不点亮 notice。
- 比较快照绑定：openCompare 时快照 v1；后台 GET 见 v2 后，reject 载荷 `target_default_revision === 1`（仍目标用户所见的 v1）；成功后个人文字不变。
- 适配 dirty（f1='ADAPT-DIRTY'）+ 切换任务背景 GET → expected 仍 1、latest 停放 7、target 快照（v2 契约与字段集）不变；显式 resolveAdaptConflict 才采纳 rev7 且文字保留、carried 生效（未提交仍 unsaved）。
- 未触及（纯预填）面板开启同样停留基线（背景 GET 只停放）；预填态不算 unsaved；显式 resolve 后按服务端真值重组且 unsaved 清零。

## 5. S4（P2）配置/管理员冲突 gating 与恢复入口

代码：

1. `AiConfigCard`：新增 `conflictPending`（409 后保持 true，直到显式选择 载入最新/保留输入）。`canSave`/`canClear` 在 `conflictLatest || conflictPending` 时为 false；`save()`/`clearSecret()` 入口同样检查（覆盖 Enter 提交路径），在途期间再点只给固定提示、不发新请求。冲突比较 GET 失败仍保持 `conflictPending` 并提供 `retryConflictLatest()` + 模板"重新获取最新配置"恢复行（`v-if="conflictPending && !conflictLatest"`）；载入最新/保留输入成功选择后清空 pending。`load()` 的重新读取不再清空活跃冲突视图（`conflictLatest` 移出 load 成功路径的清理点）。PATCH/DELETE 成功同时复位两个标志。
2. `AdminPromptDefaultsCard`：`save()` 入口与发布按钮同规则阻断（`conflictLatest !== null || conflictPending`）；比较 GET 失败保留 `conflictPending` + `retryConflictLatest()` 恢复行；**冲突区并列展示服务端最新默认逐字段文字与本人草稿**（"我的输入（未发布）／服务端最新默认文字"两列，绑定 `conflictLatest.guidance_map`），满足"保留输入重新发布之前用户看到具体最新文字"。
3. `PromptGuidanceCard`：个人冲突块显示条件去掉 `(dirty || !latest)` 约束——`pendingConflict` 期间**始终可见**，latest 存在显示 保留修改/载入最新 两动作，否则显示 重新获取最新状态 重试行；仍无新增写入口（`pendingConflict` 期间写按钮禁用不变）。

新增回归（S4 四个 section + 管理员最新文字功能断言，共 21 条）：

- 配置卡：首折 409 → 比较呈现 v9/pending → `canSave=false`、`canClear=false` → 再 save 无第 2 次 PATCH、clearSecret 无 DELETE → `keepInputsRebaseVersion`（显式）后 pending 清零、canSave 重新为 true。比较 GET 失败变体：pending 保持、无比较视图、save 仍禁发 → `retryConflictLatest` 重新取得 v11 → 显式选择后下一次保存携带 expected_version=11。
- 管理员：发布 409 → conflictLatest v8（含逐字段 map 数据）→ 冲突期间再 save 无新增 PATCH → 显式 keep 后发布 expected_default_revision=8。比较 GET 失败变体：pending 保持、save 无新增写入 → retry 取得 v5 → keep 后发布 target v5。
- 个人：409 → pending；用户把文字改回旧基线（dirty→0）后，再点保存不产生第 2 次写，`keepEditsNewBaseline` 恢复动作仍可用并解开死锁。
- 管理员最新文字可见：功能断言 conflictLatest 携带 default_revision + guidance_map；模板绑定检查见 §7。

## 6. SettingsView 实际离开/退出动作驱动

本轮不再只检查卡片 `hasUnsavedChanges`：脚本的 `mountCard` 增加 `which:'settings'`（真实 `SettingsView.vue` `<script setup>`（ts transpile + 真实 Vue reactivity）执行，子组件以桩映射 `.vue` id，四张卡 ref 由场景直接注入 `aiConfigCard/promptCard/adminCard` stub），mono 需要 harness 侧 `defineEmits` shim 修正为"返回 emit 函数"（此前签名错误导致 emit 不可用；同时帮助暴露原检查盲区）。

覆盖（`S4-View` section，7 条）：

- 无未保存：`requestLeave('back')` 直接 emit `go-back`，无确认行。
- 有 card dirty：`requestLeave('back')` 置 `leaveConfirm='back'` 且不离开；`cancelLeave` 留在页面；再次 request/`confirmLeave` 真正 emit `go-back`。
- 退出登录：`requestLeave('logout')` **立即**调用 `aiConfigCard.teardownSecretInput()`（wipe 先于确认行），确认行仍显示；`cancelLeave` 后密钥已被清（不复活）；再次 request + `confirmLeave` → `doLogout()` 执行、账号置空、emit `logged-out`。密钥清空动作共 3 次请求路径各一次（取消轮与确认轮都即时清空）。

## 7. 模板恢复入口检查（源码绑定，不替代 DOM 验收）

`S3/S4-模板` section：优先用现有 `vue/compiler-sfc`（无新依赖）`parse` 三个卡片，SFC 解析 0 错误，并在**模板内容**上断言：

- 个人冲突块 `v-if="selectedDraft.pendingConflict"`（恒显示，不再由 dirty 决定隐藏）。
- 适配区 `v-if="selectedDraft.latest"` 的"载入最新目标"显式入口（含 `resolveAdaptConflict` 调用绑定）。
- 配置卡恢复行 `v-if="conflictPending && !conflictLatest"` 与 `retryConflictLatest`。
- 管理员冲突区并列 `conflictLatest.guidance_map` / "服务端最新默认文字" / "我的输入"；发布按钮 disabled 含 `conflictLatest !== null || conflictPending`。

此检查为源码/编译级证据；按钮可视布局与交互顺序仍以真实浏览器 C1–C7 验收为准。

## 8. 防泄漏验证改为实际捕获（替代 ok(..., true) 常量）

- 脚本头部将 `console.log/error/warn` 全部替换为带捕获的包装：本进程**实际输出的每一行**存入 `capturedOutput`；结束前一条真实断言扫描全部捕获文本，合成密钥标记 与 raw error 标记命中数必须为 0（替换原 `ok('script never printed…', true)` 占位）。已额外用外部 runner grep 复核输出文件命中数为 0。
- 日志仍只输出场景名称/pass-fail 计数；脚本不打印合成 secret 或请求载荷（fixtures 只在 API mock 表内流转）。

## 9. 实际命令与结果（Node v26.10.0，frontend 目录）

| 命令 | 结果 |
| --- | --- |
| `npm run typecheck`（vue-tsc --noEmit） | 通过，退出 0，0 错误 |
| `npm run build`（vite build） | 成功；既有 >500kB chunk 警告保留（非本片引入，未拆包） |
| `node scripts/ai-settings-1c-check.mjs` | 29/29 通过（原共享函数定向检查） |
| `node scripts/ai-settings-1c-state-regression.mjs`（增强后） | **204/204 通过**（原 108 项全保留；新增 96 条 S1–S4 与模板/视图/防泄漏断言） |
| `git diff --check` | 通过 |
| 外部 grep 复核脚本输出 | 两类标记命中 0 |

回归在成形过程中捕获并修复的真实问题（证明非空头验证）：

1. `openAdapt` 首版把 `target.prefill` 与 `task.adaptDraft` 指向同一对象 → 编辑框每次输入都把预填基线一起改掉（S3 场景捕获 `edited-then-closed…unsaved` FAIL）→ 预填改为独立拷贝。
2. `initialize` 用例初版刷新 mock 始终返回 not_initialized → 成功后被覆盖 → mock 按调用次序合成状态后通过（同时暴露需按流程次序断言而非单点状态）。
3. harness `defineEmits` shim 原把事件处理器当宏传入 → SettingsView `emit` undefined；修正后驱动出真实 `logout()` 3 次清密钥路径（取消轮/确认轮共两次 `requestLeave` + confirm），并依此把断言改为逐轮断言而非固定次数低估。

## 10. 对上一轮报告不符声明的纠正

依据复审 §2 的记录：

1. 上轮"108 项验证……有实质改进"中标题为"离开 dirty 确认"的场景实为只调用指导卡 exposed 检查，**未驱动** SettingsView 的 `requestLeave/confirmLeave/cancelLeave` 实际动作，也未验证退出清密钥——本轮以真实 SettingsView 组件脚本执行补齐（§6）。
2. 上轮"防泄漏 CI grep 计数 0"中的最后一条脚本断言为 `ok(..., true)` 常量，不构成自动检测证据——本轮改为进程内真实输出捕获＋断言，并有可重复外部 grep 复核（§8）。
3. 上轮报告表述"适配草稿 dirty 保护"实际存在复审所指的预填即 dirty（`isAdaptDirty` 仅判 map 非空）与"关闭面板不失效在途适配提交"两个生命周期缺口——本轮由预填基线与 `adaptOpen` 身份门修正（§4），并被新回归覆盖。
4. 上轮"冲突期间保存禁用"在配置/管理员两卡仅依赖按钮 disabled，实际 `save()` 入口与 `canSave`/管理员发布均未检查 conflictLatest——本轮在状态与入口两层共同落实（§5），并以"409 后未选动作无新增写"回归固化。

## 11. 未执行项与偏离（如实）

- **真实浏览器 C1–C7 桌面验收未执行**（不启动任何服务器/浏览器；模板按钮 disabled 绑定等仍属桌面目视项）。
- 验证 harness 仍只编译 `<script setup>` 正文离线驱动；无 DOM、无网络、无数据库。SettingsView 亦未渲染模板 DOM（文本框/按钮的可视状态未验证）。
- 接受/拒绝/适配在"面板已关闭"后的响应被整体孤儿化（无 commit/无提示）；服务端此请求可能已生效（尤其 reject 侧），后续以版本冲突/刷新流程自然恢复。该产品口径沿袭复审 S3"关闭面板真正失效对应 success/error"要求执行，未自行改为"照常同步"。
- 适配提交响应期间对适配框的在途输入按"快照对账"保留（S2 选项 A：捕获快照与响应对账），未采用"请求期锁定适配框"（规格允许二选一，与普通面口径一致）；管理员卡维持已有的请求期锁定不变。
- `AdminPromptDefaultsCard.detailSnapshotRevision` 为历史残留未引用代码，本轮按"不主动重构无关功能"未删除。
- `SettingsView.vue` 本轮**未改内容**（既有 1C 修改保留未动；其离开衔接经离线驱动验证通过）。
- 未 commit/push；交付到此停止，等待协调者复审。不部署、不启动桌面验收。
