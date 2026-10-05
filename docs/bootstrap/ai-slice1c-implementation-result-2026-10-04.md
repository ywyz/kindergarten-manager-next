# AI 设置 1C 前端实现结果记录（2026-10-04，实际执行日期 2026-10-04）

依据：[1C 规格](../specs/ai-settings-ui-1c.md)、[1B API 定稿](../specs/ai-settings-api-1b.md)、[1B 收口复审](ai-slice1b-closeout-review-2026-10-04.md)、[1C 编码交接](ai-slice1c-opencode-coding-prompt-2026-10-04.md)。业务编码由 OpenCode 本轮完成；**本记录是编码与静态／定向验证证据，不是浏览器产品验收，C1–C7 的真实交互验收须由桌面版在获授权远程实例上执行**。

## 1. 开工状态与范围约束

- HEAD：`1647fc934d41b29a844a807d454031e66a2b45af`（与 1B 收口复审一致；全程未 commit/push）。
- 施工前 `git status`：1A/1B 全部既有修改与未跟踪文件（backend 1A/1B 实现及测试、各历史报告、`ai-settings-api-1b.md`、`ai-settings-ui-1c.md`、`ai-slice1c-opencode-coding-prompt-2026-10-04.md`）逐项保留，未回退、未覆盖、未清理。
- 唯一收口判据核对：`ai-slice1b-closeout-review-2026-10-04.md` 结论为复审通过、无阻塞进入 1C 编码；开工时不存在更新的阻塞结论，未改 backend。
- 未读 `.env`／现有私密密钥；未复制旧项目；未安装 Skill／MCP／依赖（`node_modules` 为已安装既有环境）；未另起编码代理；未 SSH／部署／commit/push；未启动 API/Vite/worker 服务器；未连接数据库或供应商。本机无浏览器产品验收。

## 2. 实际改动文件

| 文件 | 类别 | 说明 |
| --- | --- | --- |
| `frontend/src/types.ts` | 修改（追加独立区域） | 1B DTO 映射区：`AiConfigOut`／`AiConfigDeleteIn`/`AiConfigPatchIn`、`TaskStatusOut`/`TaskStatusListOut`、`AiLatestDefaultOut`、`AiPromptDetailOut`、七个写 DTO（init/edit/accept/reject/adapt/管理员 PATCH）、`AiReadyReason` 等；注释明确版本只来自设置接口、账号 version 不借用 |
| `frontend/src/api.ts` | 修改（追加独立区域） | 12 条 typed 调用（§3 表）；全部走既有 `request()`（cookie、JSON Content-Type 自动、401 全局 reset），不手工设置 Origin；DELETE/initialize 显式 JSON body |
| `frontend/src/views/SettingsView.vue` | 重写 | 姓名／密码功能原样保留（含 VERSION_CONFLICT 分支）；新增三张 AI 卡片接入；`<AiConfigCard ref>` 通过 `$refs` 校对 401 后立即清空密钥输入 |
| `frontend/src/components/ai/ai-settings-shared.ts` | 新增 | 无依赖纯模块：七任务中文名 / 未知空类型回退、`ready` 中英文案（"本地配置可用（…尚未验证供应商连接）"）、固定错误码→中文提示、epoch 守卫（普通闭包计数，无响应依赖）、PATCH/DELETE 载荷组装（密钥省略／原样）、dirty 字段差异（服务器字段顺序） |
| `frontend/src/components/ai/AiConfigCard.vue` | 新增 | 本人 AI 配置（§4） |
| `frontend/src/components/ai/PromptGuidanceCard.vue` | 新增 | 七任务个人指导（§5） |
| `frontend/src/components/ai/AdminPromptDefaultsCard.vue` | 新增 | 管理员系统默认面板（§6） |
| `frontend/scripts/ai-settings-1c-check.mjs` | 新增 | 无依赖定向验证脚本（Node 内置 TypeScript type-stripping 直接导入真实共享模块，无测试框架） |
| `docs/bootstrap/ai-slice1c-implementation-result-2026-10-04.md` | 新增 | 本报告 |

未改：`App.vue`（既有 `go-settings` 三角色入口与 settings 页挂载已满足 C1 入口要求，无需变更）、`auth.ts`、其他 views/components、全部 backend 文件、依赖/锁。未引入状态库／路由器／HTTP 库。

## 3. 12 条接口调用与 DTO 对应（与 backend/app/schemas.py 一一核对）

| # | 调用（api.ts） | 方法/路径 | 请求 DTO（types.ts） | 响应 DTO |
| --- | --- | --- | --- | --- |
| 1 | `getAiConfig` | GET `/api/settings/ai-config` | 无 | `AiConfigOut`（version/protocol_id/base_url/model/has_secret/secret_mask/ready/ready_reason） |
| 2 | `patchAiConfig` | PATCH 同路径 | `AiConfigPatchIn`（expected_version + protocol_id/base_url/model 必填，secret 可省略） | `AiConfigOut` |
| 3 | `deleteAiConfig` | DELETE 同路径 | `AiConfigDeleteIn`（仅 expected_version） | `AiConfigOut` |
| 4 | `listPromptTasks` | GET `/api/settings/prompts` | 无 | `TaskStatusListOut`（items 顺序由服务端给出） |
| 5 | `getPromptDetail` | GET `/api/settings/prompts/{task_type}` | 无 | `AiPromptDetailOut`（based/latest 字段集、latest_default、派生状态全套） |
| 6 | `initializePromptTask` | POST `…/initialize` | body 恰为 `{}` | `AiPersonalInitOut`（含 `idempotent`） |
| 7 | `patchPromptGuidance` | PATCH `/api/settings/prompts/{task_type}` | `AiPromptEditIn`（expected_personal_revision + 局部 guidance_map） | `AiPersonalWriteOut` |
| 8 | `acceptPromptDefault` | POST `…/accept-default` | `AiPromptAcceptDefaultIn`（expected_personal_revision + target_default_revision + accepted_fields 非空无重复） | `AiPersonalWriteOut` |
| 9 | `rejectPromptDefault` | POST `…/reject-default` | `AiPromptRejectDefaultIn` | `AiPersonalRejectOut`（state=unchanged、idempotent） |
| 10 | `adaptPrompt` | POST `…/adapt` | `AiPromptAdaptIn`（target_contract_version + 完整 guidance_map） | `AiPersonalWriteOut` |
| 11 | `getAdminPromptDefault` | GET `/api/admin/prompt-defaults/{task_type}` | 无 | `AiPromptDefaultOut` |
| 12 | `patchAdminPromptDefault` | PATCH 同路径 | `AiAdminDefaultPatchIn`（expected_default_revision + 局部 map） | `AiPromptDefaultOut` |

错误处理统一经 `aiErrorNotice`：PATCH/DELETE/accept/reject/adapt 的 409 分码各自固定文案（VERSION_CONFLICT／PROMPT_NOT_INITIALIZED／PROMPT_ADAPTATION_REQUIRED／PROMPT_CONTRACT_CHANGED／PROMPT_DEFAULT_CONTRACT_MISMATCH）；422 固定通用提示（不期待 fields）；403/503 按固定码；404 TASK_TYPE_NOT_FOUND 提示刷新列表；401 由全局 request() 接管并保留静默。原始异常文本、请求载荷、traceback 均不进入提示。

## 4. 入口与身份覆盖

- 教师 / 待分配 / 管理员本人：均走 `SettingsView` 既有入口（PendingView、TeacherView、AdminView 的"系统设置"按钮→ `App.vue` settings 页），不受 class_id/can_prepare 限制。
- 卡片按服务端行为独立：本人配置卡（三人通用）、个人指导卡（三人通用，全部 7 项以服务端 items 为准渲染）、管理员默认面板（`v-if auth.account?.role==='admin'`，与本人指导数据完全分属两个组件，不共享任何 draft/响应）。
- 姓名／密码既有功能逐字保留（原 saveProfile/changePassword/logout/goBack、姓名 409 保留姓名输入、密码 409 清空三个输入框等旧行为未回退）。

## 5. 本人 AI 配置（AiConfigCard）

- GET 仅展示：版本、协议（固定 `chat_completions_v1` 文案）、地址、模型、密钥遮罩 `********`、就绪状态。`ready=true` 文案"本地配置可用（此状态只表示本地配置完整，尚未验证供应商连接）"；页面固定声明无"测试连接"／AI 调用按钮，保存不调用供应商。
- `DECRYPT_UNAVAILABLE` 显示"当前加密配置不可用（保存的密钥暂时无法读取），不影响其他设置和手工备课"。
- 密钥输入独立于已保存状态：空输入＝省略（不发 `secret`，载荷组装在纯模块 `buildConfigPatchPayload`：不出现 `"secret"`、`null`、空串、`********`）；非空原样发送（无 trim）；输入框 `type="password"`；遮罩值永不写回输入框。
- PATCH 每次发完整元信息；`expected_version`＝配置响应版本。首次（version=0）保存按钮要求已输入新密钥；已有 head 且已清除时可省略。
- 独立"清除已保存密钥"：两步确认（提示语明确"地址与模型不会被删除"），DELETE JSON 仅 `{expected_version}`（脚本断言序列化恰为 `{"expected_version":N}`）；无 head version=0 幂等路径由后端契约承接。
- 成功（保存／清除）：以本次响应更新保存基线，**清空密钥输入**；失败：输入保留在本页内存中（不持久化、不写 console/localStorage/sessionStorage/URL/报告）。
- 409（保存与清除两入口）：输入保留 + GET 最新脱敏配置作为 `conflictLatest` 展示（页面行内显示服务端最新地址／模型），提供"载入最新配置"与"保留输入，按最新版本重新保存"两动作；后者仅移动 expected 基线，仍需用户再次点击"保存配置"，无自动重发。全干净表单（与最新一致且未输入密钥）时保存按钮禁用（避免空耗版本）。
- 503：固定文案"加密材料暂不可用……不是供应商连接问题"，允许重试／清除。
- 401：立即清空密钥输入（`onAccountInvalid`→`teardownSecretInput`），全局进入登录流程。
- 账号切换（watch `auth.account.id`）：bump epoch、清空密钥/地址/模型输入、基线与冲突展示清空后重新 GET；卸载时 bump + clearSecretInput。绝不持久化到浏览器存储。
- 输入初始值：首次 GET 成功把服务端地址/模型带入输入框（保证"只轮换密钥"时提交的是原元信息而非空串）；冲突后的刷新从不覆盖输入。

## 6. 七任务个人指导（PromptGuidanceCard）

- 列表：GET items 渲染全部七项（未建立指导／待适配／默认有更新／正常徽标），顺序与字段一律服务端数据，客户端只有 task_type→中文名映射（`daily_lesson_split` 教案拆分、`daily_process_adapt` 过程适龄调整、`daily_other_activities` 日其他活动、`weekly_games` 周游戏、`weekly_columns` 周栏目、`weekly_theme_suggestion` 周主题建议、`weekly_materials` 周材料；未知 task_type 原样回退展示）。**任何字段集合均不写死**。
- 详情 GET 只读打开：未初始化仅展示最新默认并提示"页面不会自动初始化"，显式按钮 POST `/initialize` body `{}`；`idempotent=true` 显示"已有个人指导（保存成功，未做任何更改）"，不得推断已适配。成功后 GET 刷新；刷新失败提示"已建立个人指导（保存成功），状态刷新未完成…"，不误称写失败。
- 普通编辑：字段来自 `based_guidance_fields`（服务端顺序）；文本域 per 字段，maxlength 8000、show-word-limit、允许空串/换行、不 trim、纯文本（无 v-html，全仓 grep 确认）。PATCH 仅发"草稿 ≠ 保存基线"的字段（`changedGuidanceFields`：基线缺失键视作 ''；纯空白差异算变更），空 patch 不可提交（按钮禁用）。待适配状态下旧 based 字段仍可正常保存（与最新比较界面互不阻塞）。
- 派生状态按 API 展示：personal_revision、based/latest contract、latest default revision、accepted_default_revision、last_rejected_default_revision、两个独立状态（正常／待适配），"建立指导"不与"本地配置可用"合并。
- 默认比较：从比较打开时的 `latest_default` 快照驱动；双列表"我的当前文字（已保存口径）／最新默认文字"；勾选行带"将覆盖"标记；`accepted_fields` 按 default map 键序生成（天然无重复、非空才可提交，未选按钮禁用）；dirty 存在时接受/拒绝按钮禁用并有打开侧提示（先"保存修改"或"放弃修改"）。
- 接受成功：响应写回基线，比较关闭，提示仅更新所选字段；409（各分码）输入保留，重新 GET 详情并按最新默认重建比较（选择清空），提示"请重新勾选后再点击接受"——绝不重发旧 target。
- 拒绝（"保留当前指导"）：提示不变版本；响应回写 personal_revision/last_rejected；重复拒绝的 idempotent 语义由后端承接；之后仍可重新打开比较并接受同一默认，无强制弹窗。
- 完整适配：仅 `adaptation_required` 时出现"打开完整适配编辑"；编辑面板按最新 `guidance_fields` 组装，同名原文字保留、新字段预填最新默认（行内标注"新增字段"）、移除字段在独立只读区展示原文且不随提交；提交目标为打开编辑时捕获的 `required_contract_version ?? latest_contract_version` 与 expected_personal_revision；显式"完成适配"才提交**完整**字段集；"关闭适配"保留草稿不标记；"放弃适配草稿"显式重建预填。409 PROMPT_CONTRACT_CHANGED 时重新 GET，按新契约重建预填（同名草稿文字保留），目标版本更替后再由用户显式提交。
- 草稿生命周期：每任务独立内存草稿（任务间切换、面板内关闭均保留，返回时提示存在草稿）；卸载/账号切换全部清空；无浏览器持久存储。

## 7. 请求状态 / 过期失效 / 409 草稿保护机制

- epoch 守卫（`createEpochGuard`：选任务/面板切换/卸载/账号切换 bump）：任何异步操作捕获 token，await 后 token 失配则**成功、错误、finally 一律丢弃**（不更新内容、不写消息、不放 loading）。
- loading 与写锁：指导卡 per-task `busy`/`detailLoading`，配置卡 `saving/clearing/baselineLoading`，默认面板 `saving/detailLoading`；写按钮重复点击被锁。
- 保存基线 / 本地输入 / 最新比较数据分属三个独立状态（`detail`·`normalDraft`/`adaptDraft`/`conflictLatest` 与 `compare.defaultValue` 快照等），刷新合并 `rebuildNormalDraftPreservingDirty`：仅"非 dirty 字段"跟随服务端，dirty 字段绝不覆盖，expected 基线不静默推进——再次提交永远是用户显式点击。
- 写成功后被动的 GET 刷新失败一律声明"写已生效（含版本号）+ 刷新未完成"，不诱导重复提交；刷新列表失败静默（详情已承担反馈）。
- 跨组件 401：全局 request() 派发登录流；配置卡即刻清密钥输入。
- 422/403/503/404 固定文案见 §3；不展示原始异常或请求内容。

## 8. 验证证据（实际执行的命令与结果；Node 26.10.0 经 `~/.nvm/versions/node/v26.10.0/bin` 提供，node_modules 为既有安装）

| 命令（frontend 目录） | 结果 |
| --- | --- |
| `npm run typecheck`（vue-tsc --noEmit） | 通过，0 错误 |
| `npm run build`（vite build） | 成功；既有 chunk >500kB 警告非本片引入（基线时已存在同警告） |
| `node scripts/ai-settings-1c-check.mjs` | 29/29 通过：密钥省略（JSON 无 "secret"/null/空串/遮罩）、原样密钥（含空格原样、只出现一次、无遮罩往返）、DELETE JSON 恰为 `{"expected_version":N}`（含 0）、 dirty 基线（同值/空对缺失/空白不同/换行/多字段顺序）、epoch 失效（bump 后旧 token 死亡）、固定错误码文案、ready 文案、七任务标签 |
| `git diff --check`（仓库根） | 通过 |
| `grep v-html`（frontend/src） | 无匹配 |

历史可用性回归：姓名/密码区域逻辑未改（1B 时该页功能不在本轮 backend 变更面），typecheck/build 覆盖其编译；运行级回归属 C7 桌面验收。

## 9. 编码阶段范围（C1–C7 映射）

| 编号 | 本轮编码阶段证据 | 桌面真实验收要点（未验，待桌面） |
| --- | --- | --- |
| C1 | typecheck/build 通过；三角色入口和三张卡片段落入位（入口按钮既有、App.vue 未动）；默认面板仅 admin 渲染 | 各角色真实登录逐项走查；教师不可见默认面板 |
| C2 | 载荷组装/遮罩/文案/409 流程经定向脚本与 UI 逻辑落实；首次保存需密钥/清除/省略逻辑已实装 | 首存、保留密钥轮换、清除→刷新持久、遮罩不回显、就绪文案；主密钥缺错降级由授权验收夹具记录 |
| C3 | 字段集合全部 API 驱动；initialize 显式 `{}` 且幂等消息；8000 maxlength；空串/换行支持；保存后基线刷新不覆盖 dirty | 七任务逐个真实编辑保存刷新；8001 由后端 422 定向验证留桌面 |
| C4 | 比较/按字段接受/拒绝 UI 与提交语义落实；接受后响应回写基线；拒绝幂等不推进版本 | 管理员真实发布默认→个人不变→逐字段接受→拒绝→再接受 |
| C5 | 待适配 UI（旧字段可编辑、accept/reject 阻断、新字段预填、移除原文只读、目标契约展示、完成适配完整集合）；409 CONTRACT_CHANGED 重建预填 | 系统真实发布 v2 后全流程（发布夹具需单独授权，本轮无且不造） |
| C6 | 409 各入口输入保留、显式 rebase、epoch 失效（含 finally）经脚本验证 | 两浏览器会话真实 409 行为；延迟响应为新前端模拟证据 |
| C7 | 401 即清密钥（代码路径）；422/403/503 固定文案 | 真实 401→密钥清空验证；日/周/Word 既有功能回归 |

## 10. 偏离 / 未执行项（如实）

- **浏览器产品验收（C1–C7 全部交互例）未执行**：本轮不启动任何服务器、不连接远程实例；下表之外没有任何"真实通过"结论。桌面版须按 C1–C7 在获授权远程实例完成；v2 发布与主密钥缺错夹具未授权前相应子例单列受阻。
- API 缺能力问题：无（1B 已提供全部 12 条接口；未扩展接口，未发现需要报告的缺口）。
- 8001 字符超限等越界例依赖后端 422（前端 maxlength=8000 拦截），未做前端单元刻意的越界注入.
- `ai-settings-shared.ts` 中为审计留有 `isKnownTaskType`（当前仅脚本使用）；组建内列表渲染完全依赖服务端返回。
- 定向脚本未覆盖 Vue 组件模板内部（DOM 级交互属桌面验收）；脚本只断言真实共享纯模块行为与载荷序列化.
- 全程未 commit/push；HEAD 与开工一致，既有修改全部保留。

交付到此，停止等待协调者只读复审。
