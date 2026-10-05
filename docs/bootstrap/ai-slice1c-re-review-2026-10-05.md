# AI 1C 补修复审（2026-10-05）

结论：**本轮仍未通过部署门槛。补修解决了主要常规路径，但 S1–S4 尚有可复现的组件状态问题。下一步只补这些边界及验证，不重做 1C，不启动远程部署。**

依据：[首次审阅](ai-slice1c-review-2026-10-04.md)、[补修报告](ai-slice1c-repair-result-2026-10-04.md)、[补修交接](ai-slice1c-repair-opencode-prompt-2026-10-04.md)、[1C 规格](../specs/ai-settings-ui-1c.md)。补修报告使用 2026-10-04 日期，本次协调者实际复审为 2026-10-05，不推定实现者跨日执行。审阅实际未提交工作区，HEAD 仍为 `1647fc934d41b29a844a807d454031e66a2b45af`。未修改业务代码、读取私密配置、安装依赖、连接数据库、启动服务器、SSH／部署或 commit/push。

## 1. 剩余阻塞

### S1（P1，原 R4）：首次详情加载的失效 loading 未清理

位置：`frontend/src/components/ai/PromptGuidanceCard.vue:376`、`:394`、`:398`、selectTask finally。

selectTask bump 后只 clearStaleBusy，未清理旧 epoch 的 detailLoading。首次打开 A 的 GET 未完成→切 B→A 的旧 GET 返回后被丢弃，finally 因 epoch 失效不清 A loading；再选 A 被 `detailLoading.has(A)` 短路，不会重新请求或建档。

离线复现最终 **A draft 不存在、A loading=true、GET 总数只有 2（A/B）**。现有 A→B→A 回归先成功建档再挂起写请求，覆盖 busy，但不覆盖首次建档 GET。需要为首次详情 loading 定义请求所有权，切换由新所有者释放失效槽位并允许重试；旧 finally 不能清新请求。refreshDetail 的 finally 也只有 epoch 检查、没有 detailSeq 校验，应一并补同资源旧 finally 不解锁新请求的检查。

### S2（P1，原 R3／R6）：提交过的同一字段仍丢失后续输入

位置：`PromptGuidanceCard.vue:203`（commitWriteOut）、`:476`（saveNormal）。

commitWriteOut 对 submitted 中的字段直接写 submitted[field]，不比较用户在 await 期间是否又改了同一字段；个人指导 textarea 未锁定。发送 submitted→继续输入 typed-after-submit→写响应与一致的后续 GET 返回，最终框中文字为 **submitted**，后续输入丢失。上轮修复报告承诺保留在途新增修改，但脚本只覆盖未提交的另一个字段。

应捕获请求发出时的草稿快照，回写时比较当前文字与发出时文字：仅仍等于发出时值的框更新到已提交响应；真正新增输入保留为 dirty。或按规格在请求期间明确锁住所有相关编辑入口。接受／适配／初始化也须检查其实际可编辑路径，不能把所有 submitted 键无条件视为当前框仍未变。

### S3（P1，原 R2／R5／R6）：适配草稿未纳入基线与离开约束

位置：`PromptGuidanceCard.vue:184`（noteFreshDetail）、`:801`（cancelAdapt）、`:829`（isAdaptDirty）、`:969`（anyDraftDirty）。

- noteFreshDetail 仅检查普通 normalDraft dirty。适配面已输入未保存文字、普通框干净时，后台 GET 或切换任务返回会直接采用 fresh.personal_revision。复现适配输入仍保留，但无需用户选择 expected 已从 **1→2**，仍是原 R2 的静默基线推进，只是发生在适配路径。
- anyDraftDirty 仅在 adaptOpen=true 时计入适配草稿。修改适配文字后关闭面板，文字仍存在，但 **hasUnsavedChanges=false**；返回设置上一页可无提示丢失。关闭不提交且保留草稿，不能等同放弃修改。
- isAdaptDirty 只判断 map 非空，把刚预填而尚未修改的面板也算作 dirty；需有适配预填／编辑基线，准确区分未提交改动。
- cancelAdapt 只改 adaptOpen，未更换 adaptTarget 身份；submitAdapt await 后只检查 target 身份，关闭面板没有实现报告所称的在途适配响应失效。相同问题也应检查 accept/reject 的 error／finally 路径：接受 success 有 panel 判断，catch 没有；拒绝后续提示／刷新没有完整 panel 判断。
- rejectDefault 使用 detail.latest_default.default_revision，而接受使用打开比较时的 compare 快照。后台 GET 可以更新 detail 而保持 compare 不变，因此比较 v1 时“保留当前指导”可能拒绝 v2。接受和拒绝都应绑定用户看到的目标快照。

需将普通／适配草稿与面板快照一起纳入读取采纳条件；适配 target 的 expected 和字段集在明确动作前保持不变；关闭保留已编辑文字和离开确认，同时正确失效关闭面板的请求状态。补真实动作序列，不直接设置 adaptOpen=true 冒充完整离开流程。

### S4（P2，原 R2／R4）：配置／管理员冲突 gating 未实现，恢复界面仍有缺口

位置：`AiConfigCard.vue:299`（canSave）、`:208`（clearSecret 附近）；`AdminPromptDefaultsCard.vue:147`（save）；`PromptGuidanceCard.vue:1123`（冲突面板模板）。

配置 canSave 不检查 conflictLatest，管理员 save／发布按钮同样不检查 conflictLatest。离线在首次 409 比较已出现后、不做任何选择再次调用保存，两卡均产生 **2 次写请求**。它们仍携带旧版本，通常由服务端再拒绝，但不符合报告中“冲突期间保存禁用，须先选载入／保留”的状态约束。配置 clearSecret 也应遵守相同规则。

管理员冲突区只显示版本，不展示服务端最新 guidance_map；“保留输入重新发布”之前用户没有看到具体最新文字，不能完成规格要求的比较。需要并列显示本人草稿与 latest 默认文字。

个人普通冲突区以 `pendingConflict && (dirty || !latest)` 控制显示；若用户冲突后把文字改回旧基线，或另一会话已完成适配使本地普通框仍干净，latest 已取得却无可用比较／适配面板时，pendingConflict 会阻断动作但解决入口隐藏。冲突状态必须始终有可见恢复动作，不能由 dirty 偶然决定是否可解决。

## 2. 本轮成立的修复与独立检查

| 原问题 | 本轮判断 |
| --- | --- |
| R1 | 首次配置 void load、失败重试、卸载清密钥、载入最新地址／模型成立 |
| R2 | 普通指导 dirty／409 的 detail、latest、pendingConflict 分离成立；适配路径与配置／管理员 gating 尚待 S3／S4 |
| R3 | 接受成功无伪 dirty、适配成功字段回写、初始化成功后刷新失败保持结果成立；同字段在途新输入待 S2 |
| R4 | 捕获 token、管理员旧 error 在写状态前检查、旧 busy 清理成立；首次 loading、seq finally、面板关闭待 S1／S3 |
| R5 | 两类适配 409 通过显式 resolve 更新目标、完整字段绑定和移除文字只读成立；后台读取与关闭状态待 S3 |
| R6 | 管理员每任务缓存、发布期间 textarea 锁定、SettingsView 返回确认已实现；关闭适配草稿漏确认待 S3 |
| R7 | 未知／网络 message 改固定 fallback 成立 |

协调者在 frontend 独立执行：

- `npm run typecheck`：退出 0。
- `npm run build`：退出 0，保留既有 >500kB 警告，不要求拆包。
- `node scripts/ai-settings-1c-check.mjs`：**29 项通过**。
- `node scripts/ai-settings-1c-state-regression.mjs`：**108 项通过**。
- `git diff --check`：通过。
- 一次性离线补充检查：用已安装 TypeScript transpileModule＋vm 执行实际组件 script setup，真实 Vue reactivity、合成 API 及延迟响应，无 DOM／网络／数据库。实际复现 S1、S2、S3 前两条、S4 重复提交；其他问题依据明确源码控制流和模板条件，不虚称已做浏览器复现。

108 项验证相比旧共享函数检查有实质改进，但不完整：首次加载 A→B→A、提交同字段后续编辑、关闭后适配 dirty、SettingsView 的 requestLeave/confirmLeave 实际动作未覆盖。脚本标题“离开 dirty 确认”实际只调用指导卡 exposed 检查；日志防泄漏末项 `ok(..., true)` 是常量，报告另称外部检查输出标记，不应将常量断言视为自动检测证据。下一轮补可重复有效检查，避免继续只增加通过计数。

## 3. 下一步

交 OpenCode 按[第二轮最小补修交接](ai-slice1c-repair2-opencode-prompt-2026-10-05.md)处理 S1–S4；保持 1A／1B 收口、前端范围和无新依赖。不自动部署、不新增业务能力。

补修复审通过后，下一步才是形成 1A＋1B＋1C 完整工作区的部署源／哈希清单、迁移与依赖准备、AI 主密钥安全准备和既定远程实例部署计划；目标库迁移及部署另获授权。部署后按 C1–C7 桌面真实验收，v2 发布与缺错主密钥夹具单独授权／未具备时如实受阻。现阶段不进入 worker／transport／真实 AI／材料或完整 W6。
