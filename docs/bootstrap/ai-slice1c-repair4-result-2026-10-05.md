# AI 1C 第四轮最小补修结果记录（2026-10-05）

依据：[第三轮补修复审 U1–U3](ai-slice1c-repair3-review-2026-10-05.md)、[第四轮最小补修交接](ai-slice1c-repair4-opencode-prompt-2026-10-05.md)、[1C 规格](../specs/ai-settings-ui-1c.md)、[1B API 定稿](../specs/ai-settings-api-1b.md)。只补 U1–U3，保留 T1–T4 已成立修复、S1–S4 与 R1–R7 既有修复全部不动。**本记录是编码与离线定向验证证据，不是产品验收；真实浏览器 C1–C7 桌面验收仍未执行。**

## 1. 开工与收工状态

- 施工前 HEAD：`1647fc934d41b29a844a807d454031e66a2b45af`；全程未 commit/push，收工后 HEAD 不变。
- 施工前 `git status` 72 项（54 项未跟踪＋18 项已修改，与第三轮收工时一致，另含协调者本日交付的 repair3-review 与 repair4 交接两份文档）；收工后 72 项＋本报告一份，未回退、未覆盖、未清理任何既有改动。
- 未读 `.env`／私密密钥；未安装依赖/Skill/MCP；未另起代理；未连接数据库/供应商；未启动任何服务器；未 SSH/迁移/部署/commit/push；未初始化浏览器。
- 本轮改动文件：
  - `frontend/src/components/ai/PromptGuidanceCard.vue`（U1／U3）
  - `frontend/src/components/ai/AdminPromptDefaultsCard.vue`(U2)
  - `frontend/scripts/ai-settings-1c-state-regression.mjs`（新增 U1–U3 回归；section 5 一条断言按方案调整，原因见 §5）
  - `docs/bootstrap/ai-slice1c-repair4-result-2026-10-05.md`（本报告）
- 未改：backend 全部、auth 业务规则、日/周/Word、依赖/锁、`ai-settings-shared.ts`、`api.ts`/`types.ts`、`SettingsView.vue`（本轮未触碰；其既有 exposed 接线原样复用）。

## 2. U1（P2）：比较重载清冲突却未采纳新个人基线

代码（`PromptGuidanceCard.vue` `reloadCompareLatest`）：

1. 删除"-比较重载成功且普通文字干净就清 `latest`/`pendingConflict`"的分支。该分支正是复审复现的门禁解除路径：pending=true 时 `noteFreshDetail` 把 fresh 停放进 latest，重载随后又清空，detail 仍 rev1，下一次 expected 仍旧。现在重载只刷新**默认比较目标**（`d.compare` 重建为 fresh.latest_default、勾选清空、stale 清除）；个人版本冲突一律按既有 T3 语义停放，由既有显式动作（冲突块的"载入最新／保留我的修改"）解除，基线与停放恢复数据在显式选择前不动。请求期间在普通框输入的 dirty 完全不覆盖（`noteFreshDetail` 停放路径本身不动 draft）。
2. 重载提示按门禁状态区分：门禁未解时不再提示"请重新勾选后再提交"，改为"仍存在未处理的个人版本冲突，请先在冲突提示处选择载入最新或保留您的修改，之后重新勾选再提交"；门禁已解时维持原文。
3. `acceptSelected` 增加 `adaptation_state !== 'current'` 守卫（与既有 `rejectDefault`、`openCompare` 同一文案）：停放 fresh 可为 adaptation_required，显式采纳落地该状态后，已打开的比较面板不得再提供接受入口（规格"待适配禁止接受／拒绝默认"，否则必然服务端 409 PROMPT_ADAPTATION_REQUIRED）。
4. T4 既有身份保护原样保留：面板身份 `d.compare === panel` 门控、409 后 `compare.stale` 标记、迟到 success/error 孤儿化、finally token 所有权均未触碰（T4 12 条回归原样通过）。

测试：

- `section('5.…')`（14 条）：改造为真实版本校验 mock——`acceptPromptDefault` 仅当 `expected_personal_revision ===` 服务端当前个人版本时成功并真实推进存储，旧 expected 一律 409（先前该段 mock 无条件拒绝，无法证明"成功仅允许正确版本"）。覆盖：接受真实 409→companion 停放 rev5（同名文字 R5-f1 变化）→比较保持开启→显式重载 GET 成功→**门禁与停放 latest 保留、基线仍 rev4**→提示不诱导提交→后台 GET 只再停放不清门禁→勾选后被门禁拦住不重发→显式"载入最新"落地 rev6→重新勾选→下一次接受 expected=6 真实成功（rev7、面板关闭、无 dirty）。不是只断言比较目标变新。
- `section('U1: 重载停放 fresh 为 adaptation_required…')`（12 条）：状态化个人存储 mock（服务端状态与版本真实演进）。覆盖：真实 409→停放 rev2 **adaptation_required**（同名 R2-f1）→重载 GET 挂起期间在普通框输入→fresh rev3 停放、门禁保留、**在途输入不被覆盖**、提示不诱导→门禁拦截不重发→显式采纳落地 adaptation_required→接受被待适配守卫拦截且不触服务器→完整适配入口可达（v2 目标/三字段）→适配提交 expected=3 真实成功（rev4、转 current）→比较/接受路径恢复，expected=4 真实成功（rev5）。

## 3. U2（P2）：管理员 409 与比较 GET 之间仍可绕过门禁

代码（`AdminPromptDefaultsCard.vue` `save()` catch 409 分支）：在识别 409 后、`await api.getAdminPromptDefault` 之前立即 `state.conflictPending = true`。该 GET 的结果只**补充**已停放冲突（成功写 `conflictLatest`，失败保留安全恢复入口）；bump 后旧 GET success/error 一律孤儿化，不触碰新选择的视图与锁（既有 `guard.alive`＋`selected` 检查未动，`finally` 的 saving 所有权未动）。GET 挂起窗口内任务级门禁由此持续成立：发布按钮 disabled 绑定与 `save()` 门禁（`conflictLatest || conflictPending`）均派生自任务 state。

测试（`section('U2: …')`，16 条；状态化按任务存储 mock，发布仅在 expected=当前 default_revision 时成功并真实推进）：

- (a) 8 条：发布→PATCH 真实 409（expected=1 vs 已被另一会话推进的 rev8）→**GET 尚未完成时门禁已成立**（conflictPending=true、conflictLatest=null）→窗口内再点发布不新增 PATCH→**挂起期间重选当前任务**门禁保持→仍无写入→旧 GET 迟到 success 孤儿化（不填视图、不清门禁）→"重新获取最新默认"取得 rev8→"保留输入"清门禁→发布 expected=8 真实成功（存储推进 rev9）。
- (b) 8 条：**GET 挂起期间 A→B→A**——B 无继承冲突、返回 A 门禁恢复、无新增 PATCH→旧 GET 迟到 **error** 孤儿化（门禁保留、不点亮提示；先按可达动作关闭门禁提示避免断言混淆，harness 时序说明）→恢复重试取得 rev8→"载入最新默认"清门禁并重建输入→再次修改后发布 expected=8 真实成功。

不只在 GET 完成后测重选：核心断言即"GET 尚未 resolve 时门禁已成立"。

## 4. U3（P2）：远端已适配后采纳最新，旧适配草稿被藏在不可操作状态

**夹具纠正**：本轮全部 U3 场景使用真实远端已适配夹具——companion 停放的 fresh 为 `adaptation_state='current'`、`based_contract_version=latest`、`based_guidance_fields`＝最新完整字段集、个人 `guidance_map` 含全部最新字段（另一会话已完成适配的个人最新版本）。不再用 adaptation_required 冒充"远端已适配"。

代码（`PromptGuidanceCard.vue`）：

1. `adoptLatest`（"载入最新（放弃我的未保存修改）"）：除既有基线/草稿/门禁处理外，完整清理适配残留——`adaptOpen=false`、`adaptTarget=null`、`adaptDraft={}`、`adaptRemovedDraft={}`。该动作明示放弃全部未保存修改，落地 current 状态后适配区消失，不再留隐藏 dirty。
2. `keepEditsNewBaseline`（"保留我的修改，以最新版本作为提交基线"）：无适配在途工作（且面板未开）时维持既有行为（普通框文字原样保留、仅移基线），既有 S4/T3 断言不受影响。存在适配在途工作时：按既有 S3 语义（"纯预填不算改动"）用既有 `splitAdaptDraft` 把**真实编辑过的同名文字**载入普通编辑面（始终可见，带既有"保存修改／放弃修改"入口）；被最新契约移除字段的草稿原文进入 `adaptRemovedDraft`；未触及字段取远端已适配的已存文字；随后结束适配会话（`adaptOpen/adaptTarget/adaptDraft` 清空）。动作附 info 提示说明文字去向与只读区位置。
3. 模板：`removed-box`（被移除字段原文／未提交适配草稿文字只读区）从待适配块内迁出，改为详情级渲染，条件不变（`removedFields` 或 `adaptRemovedDraft` 非空）。待适配状态下展示位置仅由"块内嵌套"变为"前置同级"；关键差异是状态转为 current（适配区消失）后该区域仍渲染。并在适配块不显示（状态非 adaptation_required）且存在残余草稿文字时，提供既有"放弃适配草稿"动作（复用 `discardAdaptDraft`，busy 门禁不变）。不新增双框合并或任何新工作流。

测试（`section('U3: …')`，27 条；状态化个人存储 mock，适配/普通保存均在 expected=当前 personal_revision 时才成功并真实推进）：

- (a) 载入最新（7 条）：真实夹具确认（fresh=current、based=2、based 字段集=f1|f2|f3new、map 含 O-f3）→版本校验 mock 真实拒绝旧 expected=1→`adoptLatest` 落 rev2/current、编辑面重建为远端已适配文字、**target/open/draft/removed 全清**、`hasUnsavedChanges()===false`（无隐藏 dirty）→随后普通编辑→保存 expected=2 真实成功（可恢复）。
- (b) 保留修改→保存（6 条）：保留文字 'MY-ADAPT' 载入普通编辑面（普通字段集已含三字段，实际可见）；未触及字段取远端已适配文字；适配会话退场无残留；唯一 unsaved 即可见保留文字；保存 expected=2、map 仅 f2='MY-ADAPT' 真实成功（rev3、干净）。
- (b2) 保留修改→放弃（1 条）：既有"放弃修改"入口清掉保留文字，无隐藏残留。
- (c) 契约收缩真实夹具（6 条）：远端已适配至 v3（f3new 被移除，fields=f1|f2）；用户在 v2 适配目标编辑了 f2 与 f3new→适配 409→保留修改：同名 f2 文字载入普通面，**f3new 草稿文字进入 removed 槽保存、不静默删除**，`hasUnsavedChanges` 持续为真→仅经既有"放弃适配草稿"显式动作清除→再经"放弃修改"完全干净→可继续编辑保存成功（无不可处置隐藏草稿、可恢复）。
- (d) 真实卡片 `hasUnsavedChanges` 接入真实 SettingsView（5 条）：保留修改后暴露检测为真→`requestLeave('back')` 打开确认行→`cancelLeave` 留页→既有"保存修改"处置干净→再次返回直接放行（go-back 一次）。
- (d2) 载入最新经真实 SettingsView（2 条）：采纳后 `hasUnsavedChanges()===false`→返回直接放行。
- 模板绑定（`T-模板` 新增 2 条，vue/compiler-sfc parse，不替代 DOM）：removed-box 渲染位于 adaptation_required 块之外（kept text 不藏在已消失适配区）；块外保留既有显式"放弃适配草稿"入口且仅在状态非待适配时出现。

## 5. 测试调整与计数明细（258→321）

第三轮收工 258 条全部保留运行，除以下一处按明确方案调整外未删任何反例：

- **替换 1 条**（section 5 原"explicit reload clears selections and the conflict"，1 条含三个子条件）：它断言的正是复审 U1 判定为缺陷的行为（显式重载清 pendingConflict）。本轮方案（保留门禁、由既有个人冲突动作解除）使其不可能同时成立，故替换为修正后的 U1 断言组（门禁保留、基线不动、提示不诱导、门禁拦截、显式采纳后恢复链完整成功）。原断言无独立保留价值，不属于删反例凑计数。
- **新增 63 条**：section 5 改造后净增 7（版本校验化接受 mock＋门禁/提示/后台只停放＋恢复成功链）、U1b 新增 12、U2 新增 16、U3 新增 27、T-模板新增 2。
- 29 项共享函数定向检查（`ai-settings-1c-check.mjs`）未改动，29/29 原样通过。
- 全部新 mock 均按真实状态/版本演进：服务端存储只在版本匹配时接受写入并真实推进；旧 expected 一律 409。场景日志仅含场景名、布尔与计数；进程级实际输出捕获复检合成 secret／raw 标记命中 0（该断言在脚本尾部，非占位常量）。
- harness 时序修正（非组件缺陷）：U2(b) 中被门禁拦下的发布提示先按可达动作关闭（el-alert 可关闭），再让旧 GET 迟到失败，避免与孤儿化断言混淆；反例本身不变。

## 6. 声明纠正（历史报告原文保留不覆盖）

repair3-result §4 的 T3"远端已适配变体"与其回归实际使用 `adaptation_required` 停放夹具，验证的是"远端仍待适配时显式采纳后适配入口可达"，**未验证远端已适配（current、based=latest）状态**；"远端已适配"的称呼与实际夹具不符，该覆盖声明不能当作 U3 情形的证据。本轮以真实 current 夹具的 27 条 U3 回归补齐；repair3-review §3 已先行指出同一问题，repair3-result 原文按约定保留。同时，本轮脚本内该变体注释已改为"Remote-still-pending variant"并注明真实 current 夹具在 U3 覆盖。

## 7. 实际命令与结果（Node v26.10.0，frontend 目录）

| 命令 | 结果 |
| --- | --- |
| `npm run typecheck`（vue-tsc --noEmit） | 通过，退出 0，0 错误 |
| `npm run build`（vite build） | 成功，退出 0；保留既有 >500kB chunk 警告（非本片引入） |
| `node scripts/ai-settings-1c-check.mjs` | **29/29 通过** |
| `node scripts/ai-settings-1c-state-regression.mjs` | **321/321 通过**（258 条原覆盖除 1 条按上节原因替换外全保留；U1 共 26 条含改造段、U2 16 条、U3 27 条、模板新增 2 条） |
| `git diff --check`（仓库根） | 通过，退出 0 |
| 进程级输出复检 | 实际捕获输出中合成 secret／raw 标记命中 0（脚本尾部断言，非占位） |

## 8. 方案内已确定的产品行为与留给复审的决定点

本轮未新增工作流、未发明双框合并；以下两点是在既有语义内作的落实选择，列出供复审确认：

1. **保留路径对"未触及字段"的处理**：适配面板中纯预填（未编辑）按既有 S3 语义不算用户工作，保留修改时这些字段取远端已适配的已存文字，仅真实编辑的同名文字与被移除字段原文保留。理由：该场景下冲突对照区（基于普通框）本就无差异可显示，"保留我的修改"唯一可指的即用户的未保存工作；与普通路径"框文字原样保留"（对照区可见差异时的语义）分属两种可达情形，两者均不静默。
2. **removed 只读区迁出待适配块**：为满足"保留的文字不藏在已消失适配区、也不静默删除"，只读区改为详情级渲染并在 current 状态下保留既有"放弃适配草稿"入口。展示内容与条件与原实现一致，无新增编辑能力。

## 9. 未执行项与偏离（如实）

- **真实浏览器 C1–C7 桌面验收未执行**（未启动任何服务器/浏览器/实例）；模板绑定检查沿用 vue/compiler-sfc 源码绑定口径，不替代 DOM 验收。
- 离线 harness 只驱动真实 `<script setup>` 与真实 Vue reactivity，无 DOM：disabled 的实际交互、按钮可视性、removed-box 迁出后的真实视觉布局仍属桌面目视项。
- "载入最新默认并重新勾选"在**面板挂起期间被替换后再到**的响应仍只能经不可达路径构造（该时刻打开按钮被 busy 禁用），身份门控在代码层覆盖，本轮未夸大该覆盖（与第三轮口径一致）。
- 契约收缩（v3 移除字段）属服务器端事件，本片设置界面不产生它；U3(c) 夹具按 API 数据如实构造该服务端状态，属"真实远端状态可达"口径，非 UI 新入口。
- `AdminPromptDefaultsCard.detailSnapshotRevision` 历史残留未引用代码仍未删除（非本轮范围）。
- 1A/1B 后端、MySQL、迁移与既有日周/Word 未重跑；未 commit/push。

## 10. 交付

到此停止，等待协调者只读复审。不部署、不启动下一业务切片；部署源/哈希清单、迁移与主密钥准备仍按既有收口文档另行授权。
