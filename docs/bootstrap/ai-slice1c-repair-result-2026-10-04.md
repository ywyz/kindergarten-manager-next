# AI 1C 最小修复结果记录（2026-10-04）

依据：[1C 编码审阅](ai-slice1c-review-2026-10-04.md)、[最小补修交接](ai-slice1c-repair-opencode-prompt-2026-10-04.md)、[1C 规格](../specs/ai-settings-ui-1c.md)、[1B API 定稿](../specs/ai-settings-api-1b.md)。本轮由 OpenCode 按审阅 R1–R7 完成最小修复；**本记录是编码与离线定向验证证据，不是产品验收；真实浏览器 C1–C7 桌面验收仍未执行**。

## 1. 开工与收工状态

- 施工前 HEAD：`1647fc934d41b29a844a807d454031e66a2b45af`（与审阅记录一致）；全程未 commit/push，收工后 HEAD 不变。
- 施工前 `git status`：1A/1B 全部既有修改与未跟踪文件逐项保留（backend 1A/1B 实现、全部历史报告、`AGENTS.md`/`backend/*` 修改、`api.ts`/`types.ts` 既有修改），未回退、未覆盖、未清理；全程 status 变化仅限本片允许文件。
- 未读 `.env`／私密密钥；未安装 Skill/MCP/依赖；未另起代理；未连接数据库/供应商；未启动 API/Vite/worker；未 SSH/部署/迁移/commit/push；未初始化浏览器。

## 2. 本轮实际改动文件

| 文件 | 类别 | 涉及 |
| --- | --- | --- |
| `frontend/src/components/ai/AiConfigCard.vue` | 修改 | R1/R4/R6 |
| `frontend/src/components/ai/PromptGuidanceCard.vue` | 修改 | R2/R3/R4/R5 |
| `frontend/src/components/ai/AdminPromptDefaultsCard.vue` | 修改 | R4/R6（重写草稿存储） |
| `frontend/src/components/ai/ai-settings-shared.ts` | 修改 | R7（`aiErrorNotice`） |
| `frontend/src/views/SettingsView.vue` | 修改 | R6（离开确认 + 退出清密钥衔接） |
| `frontend/scripts/ai-settings-1c-state-regression.mjs` | 新增 | 组件级离线回归（无新依赖） |
| `docs/bootstrap/ai-slice1c-repair-result-2026-10-04.md` | 新增 | 本报告 |

未改：`App.vue`、`auth.ts`、backend 全部文件、依赖/锁、日/周/Word 页面。`api.ts`/`types.ts` 本轮**未再改**（审阅后判定无本片必要修正；它们仍保留此前 1C 编码时的修改未被触动）。

## 3. R1（P1）配置卡首次读取与生命周期

- `mountCard → AiConfigCard`（script setup 末尾新增 `void load()`）：进入设置即触发首次只读 GET；回归 `R1: mount fires the first read-only GET exactly once`（修复前为 0）。
- `onBeforeUnmount`（新增注册）：`guard.bump()` 使在途请求失效 + `secretInput.value=''` + 清 alert；回归 `R1: unmount clears the secret input immediately`、`R4: response arriving after unmount never writes baseline`（挂起 GET 于卸载后 resolve 不回写）。
- `loadLatestIntoInputs`：现在真正写 `baseUrlInput/modelInput`（回填服务端最新元信息）；密钥输入**既不回填遮罩也从服务端不取明文**，未提交进行中的密钥保留；回归 `R1: 载入最新 truly updates the URL/model input`、`never backfills a mask / server text into the secret input`。
- `keepInputsRebaseVersion`（保留输入）保持独立：只移动 expected 基线（`applyResponse`），不触任何输入；回归 `R1: 保留输入 keeps my URL input`、`moves expected to v9`。
- 失败可重试：新增 `baselineError`；模板明确区分 正在读取 / 读取失败（可重试按钮）/ 空闲重试行，不再在失败后长期显示“正在读取配置…”转轮文案；回归 `failed read shows retriable error state`。

## 4. R2（P1）个人指导：保存基线 / 本地草稿 / latest 比较三层分离

- `TaskDraft` 新增 `latest: AiPromptDetailOut | null` 与 `pendingConflict: boolean`；`detail` 现在永远是“编辑基线”（下一次提交的 expected）。
- `noteFreshDetail`（替代原 `applyFreshDetail`）：
  - 草稿 dirty 时：**不改动 `detail`（expected 不推进）**，把 GET 结果停放在 `latest`；回归 `R2: quiet GET while dirty does NOT advance expected`、`editing baseline NOT advanced by the 409/GET`。
  - 草稿干净时：采纳 fresh 为新基线并干净地重建草稿（clean → follow fresh），同时清理冲突状态。
- `saveNormal/acceptSelected/rejectDefault/submitAdapt` 的 409 分支改为统一 `loadConflictLatest(taskType, desc)`：fetch 最新详情仅入 `latest`、置 `pendingConflict=true`、给出固定中文提示；**“再次点击保存”不再隐式确认冲突**——`pendingConflict` 期间保存/接受/保留/适配按钮全部禁用（模板）；用户在“最新服务端内容”面板显式选择：
  - `keepEditsNewBaseline`：保留我的修改、以服务端最新版本作为提交基线（之后用户再点“保存修改”，`expected_personal_revision` 携带新版本）；回归 `keep: baseline explicitly moved to rev 2`、`submit after explicit keep uses the adopted revision`。
  - `adoptLatest`：载入最新（放弃未保存修改显式丢弃）；回归 `adopt: baseline follows server rev 6`。
  - `discardNormalDraft` 在停放较新状态时自动等价于“载入最新”，避免旧提交基线回写。
- 比较早快照固定（R2 末条）：`noteFreshDetail` 不再触碰 `compare`；比较目标与勾选只在显式动作时重建（`openCompare` / `reloadCompareLatest`）；回归 `背景 GET 不替换比较快照`、`selection survives the background refresh`。

## 5. R3（P1）写成功回写本次提交的编辑状态

- `commitWriteOut`（替代原 `mergeWriteOut`）：成功后
  1. `detail` 直接以本次响应（`PersonalWriteOut/PersonalInitOut`）组装：`personal_revision/guidance_map/based_contract_version/accepted_default_revision/adaptation_state`；
  2. `based_guidance_fields = Object.keys(out.guidance_map)`（服务端回显完整合并映射的键，永远非客户端硬编码；依据：后端 `save_guidance/accept_default/adapt` 返回完整 resulting map，prompt_service.py 762/993/1108 行）；
  3. 草稿同步：提交过的字段取提交值（对基线干净）；未提交字段若“当前框中文字 ≠ 服务端 committed 值”则保留（即请求在途期间真正新增的修改，继续 dirty），否则落服务端文字。
- 回归验收：
  - `accept 提交时 …no fake dirty after commit`、`committed field shows accepted text`、`unselected field keeps original text`、`refresh failure does not resurrect the old text`（隐藏场景：接受成功、刷新 GET 失败，编辑框仍为 accepted 文本、dirty=0、alert 含“已保存成功（版本 2）”）。
  - `adapt success`：`adapt success closes the editor`、`committed map = submitted full map`、`based field set follows the write response keys`、`no fake dirty after adapt success`、`refresh failure keeps the success acknowledged`。
  - `initialize`：`applyInitOut` 用 init 响应合成已初始化编辑面（字段集来自响应 map 键），刷新失败时编辑面仍正确。
  - 管理员：`commitAdminWrite` 同语义；回归 `post-request typing survives`、`submitted field committed per THIS response`。

## 6. R4（P1）请求所有权与 loading/busy 生命周期

- 禁止 `guard.alive(guard.token())`：`AiConfigCard.handleSaveFailure` 与 `clearSecret` 的 409 比较改为 await 前 `const at2 = guard.token()` + await 后 `guard.alive(at2)`；管理员 `save` 409 比较均为既有捕获 `at`/新增 `at2` 于 await 前；回归已并入各 409 场景（冲突比较晚到仍需所有权匹配）。
- 写方法防重入（含 Enter 路径）：`AiConfigCard.save()/clearSecret()` 入口 `saving/clearing/baselineLoading` 且 `canSave` 检查；`PromptGuidanceCard` 各写方法 `busy.has/hasOwnProperty ownership`；管理员 `save()` `saving/detailLoading` 且 changed=0 短路；回归 `R4: PATCH re-entry blocked while first in flight`、`clear blocked while save in flight`、`duplicate submit blocked`、`dirty normal draft blocks submitting adaptation`。
- 任务/面板/账号/卸载使旧 success/error/finally 失效：
  - `selectTask`：bump 后 `clearStaleBusy()`（清理死 token 的 busy/busyAt 残留）+ `detailError=false`、`globalAlert=null`；A→B→A 老写成功/错误全部丢弃且 busy 不残留——回归 `R4: A→B→A busy cleared by the new owner`、`stale write success discarded`、`B draft preserved`。
  - 管理员 `selectTask` 的 catch **先所有权检查再置 error**（修复前先清 detail/error 再查 token 导致 B 视图被旧 A 失败清空）；回归 `stale A failure cannot clear the B view`、`sets no error state`、`did not create a phantom A state`。
  - `refreshAfterWrite/refreshDetail/loadConflictLatest/reloadCompareLatest` 全部 per-task `detailSeq` 序号所有权；回归 `out-of-order — the later-issued GET response still owns state`（后发响应先到仍是权威）、`stale A failure cannot clear…`。
  - 关闭面板使在途提交失效：`acceptSelected` 锁定打开时的 compare 对象身份（`panel`），await 后 `d.compare === panel` 才落 UI；`submitAdapt` 同规则绑定 `adaptTarget` 身份；回归 `late success after panel close is orphaned`、`panel closed`。
- 同 epoch 双击同一任务按钮（live write）：`selectTask` 检测该任务仍有存活写 token 时直接 return，不再 bump/扰动；回归 `re-clicking the current task does not reset its draft`。

## 7. R5（P2）适配 409 恢复路径

- `adaptTarget` 语义改为 `{ contractVersion, fields }`：契约目标与**完整字段集合快照**在打开/显式载入时绑定（`openAdapt` 每次以当前 detail 重建 target；草稿文字按 `splitAdaptDraft` 拆分）。`submitAdapt` 从 `target.fields` 组装提交 map（绑定目标，不再从后续刷新后的 detail 取另一套字段）。
- expected personal revision 不再 pin 死在 target：提交时永远取当前编辑基线 `detail.personal_revision`——本人此页显式保存已更新基线后可正常提交；另一会话推进则按 409 流程停放 latest；重复提交不得越过 pendingConflict（回归 `R5: repeat submit … does NOT hit the server`）。
- 两类 409 均转 `loadConflictLatest`：保留适配文字；面板给出“载入最新目标（保留适配文字，重新检查后提交）”→ `resolveAdaptConflict`：显式采纳 fresh 为新基线、重建 target（契约/字段快照同步）、同名文字保留、**被移除的未保存适配文字进 `adaptRemovedDraft` 且模板在只读区显示（新增字段预填、移除原文可查）**。回归：
  - revision 409：`R5: revision 409 keeps the adapt draft`、`explicit resume adopts the remote revision`、`resolved submit carries the adopted revision`；
  - contract 409（PROMPT_CONTRACT_CHANGED）：`target rebound to the v4 field set`、`added field prefilled from the newest default`、`removed typed text stays consultable`、`resolved submit goes to v4`。
- 普通 dirty 指导与适配互斥：`openAdapt`/`submitAdapt` 检查 `isDirty`（普通编辑面）——回归 `dirty normal draft blocks opening/submitting adaptation`。

## 8. R6（P2）管理员草稿与离开衔接

- 管理员卡草稿重存储：`states: reactive Map<task_type, { detail, draft }>`。
  - `selectTask`：任务切换/同任务再点均**保留既有草稿**（缓存直接 return，不再无确认清空、也不重置 detail）；回归 `switching away and back keeps the per-task draft`、`re-clicking the current task does not reset its draft`。
  - 发布在途编辑锁定：textarea `:disabled="saving"`（请求期间明确锁定编辑，满足“请求后新增文字保留或在途锁定”其一）；commit 同时保留“提交后新增输入”的 reconcile 语义（见 R3）。
  - 409：输入保留 + `conflictLatest` 展示 + 显式“载入最新默认 / 保留输入按最新版本重新发布”两动作；`keepInputsRebaseVersion` 之后下一次发布携带新 expected（回归 `next publish submits against the adopted v8`）。
- 离开设置页 dirty 确认：三卡均 `defineExpose({ hasUnsavedChanges })`：
  - 配置卡：密钥非空或元信息 dirty；`R1` 回归；
  - 个人卡：任一任务 `normalDraft` dirty 或适配编辑面修改未提交；回归 `dirty draft → hasUnsavedChanges true`、`uncommitted adapt draft counts as unsaved`；
  - 管理员卡：任一任务草稿与其 detail 存在差异。
  - `SettingsView.requestLeave('back' | 'logout')`：存在未保存修改时不立即导航，先显示页内确认（`leaveConfirm` 状态 + `确认离开（不保存）/留在此页继续编辑` 双按钮，`confirmLeave` 才 emit('go-back') 或执行 logout）；无修改则直接放行；退出登录无条件立即清密钥（`teardownSecretInput`）；401 流程不经过确认门槛。
- 草稿仍是本页内存：不加 localStorage/sessionStorage/URL/任何浏览器存储；账号切换/卸载清空全部内存草稿。

## 9. R7（P2）未知/网络/非 JSON 错误固定 fallback

- `aiErrorNotice` 重构：
  - `AUTH_REQUIRED`/401 → `null`（全局 401 流程接管）；
  - 已知固定错误码 → 既有固定中文文案（不变）；
  - 未知 code 但命中安全状态码（403/404/422/503）→ 固定状态码文案覆盖；
  - 其余未知 code / 网络错误 / 非 JSON → 仅调用方提供的固定 fallback；**绝不回显 `err.message`**。
- 回归 `R7: unknown error message never surfaces`、`fixed status wording overrides (422/503)`、组件级 `raw network text never reaches the notice`；合成标记（`SYNTHETIC-RAW-ERROR-MARKER`）与合成密钥（`__SYNTHETIC-SECRET-NEVER-PRINT__`）在整个脚本输出与全部 notice 中零命中（CI grep 计数 0）。

## 10. 草稿与版本状态表（修复后实际列位置义）

| 卡片 | 保存基线（expected） | 本地草稿 | latest 比较 | 冲突 gating |
| --- | --- | --- | --- | --- |
| AiConfigCard | `baseline`（GET/PATCH/DELETE 响应） | `baseUrlInput/modelInput/secretInput` | `conflictLatest`（409 后 GET） | `conflictLatest` 非空时保存禁用，须选 载入最新/保留输入 |
| PromptGuidanceCard | `drafts.get(t).detail`（含 personal_revision） | `normalDraft`（含 in-flight 新增修改） | `latest`（409/后台 GET 停放） | `pendingConflict` 期间全部写按钮禁用，须选 载入最新/保留修改 |
| AdminPromptDefaultsCard | `states.get(t).detail`（default_revision） | `states.get(t).draft`（每任务保留） | `conflictLatest`（仅 409 path） | `conflictLatest` 非空时发布禁用，须选 载入最新/保留输入 |

生命周期：任务切换/面板内打开比较-适配/退出/401/卸载/账号切换均经 `createEpochGuard().bump()`，全部 await 后的写入由 `guard.alive(captured)` + per-resource seq/对象身份共同把关。

## 11. 验证证据（实际命令与结果；Node 26.10.0，frontend 目录）

| 命令 | 结果 |
| --- | --- |
| `npm run typecheck`（vue-tsc --noEmit） | 通过，0 错误 |
| `npm run build`（vite build） | 成功；既有 >500kB chunk 警告仍保留（非本片引入） |
| `node scripts/ai-settings-1c-check.mjs` | 29/29 通过（原共享函数定向检查） |
| `node scripts/ai-settings-1c-state-regression.mjs`（新增） | **108/108 通过**：真实组件（TS transpile + 真实 Vue reactivity）离线驱动、mock API 仅前端模拟；全文输出中 `SYNTHETIC` 标记计数 0 |
| `git diff --check` | 通过 |

修复过程中的真实回归（脚本在成形过程中捕获的真组件缺陷，说明验证非空头）：

- `detailOwnerOk` 初版误含 `drafts.has(task)`，导致 selectTask 建档路径全部无效（场景 3/4 捕获）→ 已修复；
- `splitAdaptDraft` 原实现参照被交换后的 detail 计算旧预填（场景 9 捕获）→ 改为显式传入 previous。

## 12. 对原实现报告结论的纠正（组件代码不支持之处）

原文《[实现结果](ai-slice1c-implementation-result-2026-10-04.md)》以下声明未被组件代码支持，本轮已修正并列为回归场景：

1. “后续状态 GET 不能覆盖正在编辑的 dirty 文字 / expected 基线不静默推进”（§7）——原 `applyFreshDetail` 直接 `d.detail = fresh`，409 后 GET 即推进 personal_revision；现由 `noteFreshDetail` + `pendingConflict` 落实。
2. “接受成功：响应写回基线，比较关闭，提示仅更新所选字段；409 …重新 GET 并按最新默认重建比较”（§6）——原接受成功未同步草稿（伪 dirty 反向提交风险），409 分支**自动**重建比较并清空勾选（相当于替用户确认）；现由 `commitWriteOut` + 比较 stale 标记 + 显式 `reloadCompareLatest` 落实。
3. “epoch 失效（含 finally）经脚本验证”（§8）——原脚本只验证了共享 epoch helper 本身；组件内 `guard.alive(guard.token())`、管理员 catch 顺序缺陷均未被其覆盖；现由组件级回归覆盖。
4. “载入最新配置”与“保留输入”在原实现中效果等同（都不写输入）——已按 R1 修正。
5. “卸载清空草稿”，但卸载路径未注册 onBeforeUnmount 且未约定弹出确认；现在配置卡有 hook + 页面级离开确认。
6. §7 “task／面板切换及退出使过期请求失效”面板关闭不在失效路径——现比较/适配身份 pin 已落实。

## 13. 未执行项与偏离（如实）

- **真实浏览器 C1–C7 桌面验收未执行**（不启动任何服务器/浏览器；模拟证据范围已在脚本头部与输出注明）。
- 本轮修复覆盖 R1–R7 的前端状态与生命周期；1A/1B 后端事务、会话与迁移未重验（保持已收口状态）。
- 验证 harness 只编译 `<script setup>` 正文并以真实 Vue reactivity 驱动；未渲染模板 DOM——按钮 disabled 绑定、el-alert 展示位置等属桌面验收目视项。
- `AdminPromptDefaultsCard` 的管理员 401 分支无 `account-invalid` emit（保持既有行为：全局 request() 的 401 流程接管）。
- 方案口径偏离项之一：管理员发布冲突请求期间选择“锁定编辑”而非“commit 自由输后 reconcile”双保险（规格允许二选一）；配卡/个人卡仍为输入自由 + in-flight reconcile。
- 提交方式保持：未 commit/push；等待协调者只读复审。

交付到此，停止，等待协调者复审。不自动部署、不启动桌面验收。
