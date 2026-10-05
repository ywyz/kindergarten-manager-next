# AI 1C 第二轮补修复审（2026-10-05）

结论：**仍未通过部署门槛。S1 已闭环，S2–S4 常规路径有实质修复，但仍有四处可复现边界。下一步交 OpenCode 最小补修，不部署、不启动下一业务切片。**

依据：[本轮结果](ai-slice1c-repair2-result-2026-10-05.md)、[本轮交接](ai-slice1c-repair2-opencode-prompt-2026-10-05.md)、[上轮复审](ai-slice1c-re-review-2026-10-05.md)、[1C 规格](../specs/ai-settings-ui-1c.md)、[1B API](../specs/ai-settings-api-1b.md)。审阅实际未提交工作区，HEAD 为 `1647fc934d41b29a844a807d454031e66a2b45af`；开工 status 67 项。协调者未写业务代码、读取私人配置、安装依赖、另起代理、连接数据库或供应商、启动服务器、SSH、迁移、部署、commit/push。仅新增复审与下一轮交接文档；历史文件保留。

## 1. 剩余问题

### T1（P1，S2）：适配在途期间普通编辑框的输入仍丢失

位置：`frontend/src/components/ai/PromptGuidanceCard.vue:247`、`:262`、`:982`、`:994`；普通 textarea 模板 `:1215`。

submitAdapt 只捕获适配框快照；commitWriteOut 的 adapt 分支只对账 adaptDraft，随后完整替换 normalDraft。但普通框在适配面板打开及提交期间仍可编辑，没有 disabled。实际序列：打开适配→提交挂起→同名普通框继续输入→适配响应→一致的后续 GET。普通框新增文字被覆盖；离线结果 `newTypingPreserved=false`。

这不是已补的“适配框同字段再输入”用例；那条确实通过。应覆盖同一任务全部实际可编辑面：可在适配请求期间明确锁定有关编辑/放弃入口，或同时捕获并对账两份草稿。若允许两框同名字段同时在途编辑，必须明确保留策略，不可静默选一份丢另一份。不得把旧普通文字合成伪 dirty，也不得复活用户显式放弃的文字。规格允许请求期锁编辑，可优先以最小锁定避免新增合并行为。

### T2（P2，S4）：管理员重选任务清除冲突门禁

位置：`AdminPromptDefaultsCard.vue:82`–`:97`，任务按钮未禁用；conflict 状态放在卡片全局，任务缓存只存 detail/draft。

409→最新默认比较已出现→不作载入/保留选择→重新点击当前任务。selectTask 无条件清 conflictLatest/conflictPending，随后命中缓存返回，旧基线与草稿仍在；再点发布产生第二次 PATCH。实际结果 `pendingBefore=true, pendingAfter=false, writes=2`。A→B→A 也经过同一清理路径。

应让待处理冲突及其最新比较数据跟随每任务缓存，或采用等效的最小保留方案；同任务重选与跨任务返回都不能被当作解决冲突。409 比较 GET 失败的恢复入口同样须保留。原 task/草稿缓存及在途旧响应失效规则不应倒退。

### T3（P2，S4）：个人冲突在草稿变干净后被 GET 自动解除

位置：`PromptGuidanceCard.vue:202`–`:209`，selectTask 已建档分支调用 refreshDetail。

409→pendingConflict=true、latest 已取得→用户把普通文字改回旧基线→重选当前任务触发 GET。noteFreshDetail 只检查普通/适配 dirty 和 adaptOpen，未检查 pendingConflict，直接采用 fresh 并清冲突。实际结果 `pendingBefore=true, pendingAfter=false, revision=3`；没有任何显式载入/保留动作。随后编辑可直接以自动推进的基线保存。

本轮新增的“dirty 回到旧基线仍有恢复动作”只检查回退后立即调用 save，没有再 GET，因此遗漏。待处理冲突本身也必须保护基线、恢复视图和写门禁；读成功应停放 latest，直到明确解决。覆盖 latest 成功/失败、比较关闭、远端已适配及任务切换返回；不能靠 dirty 偶然维持门禁。

### T4（P2，S3）：关闭比较后，旧的比较重载错误仍回写提示

位置：`PromptGuidanceCard.vue:695`–`:727`（reloadCompareLatest）。

实际动作：打开比较并勾选→接受返回 409（compare.stale=true）→点击“载入最新默认并重新勾选”，GET 挂起→点击“关闭比较”→旧 GET 返回 503。closeCompare 不 bump epoch；reload catch 只检查 detailOwnerOk，仍 setAlert。关闭后清除旧提示再让错误到达，结果 `closed=true, alertRelit=true`。

accept/reject/adapt 的直接 success/error 所有权已有修复，但比较重载 GET 的 error 路径未绑定发起时面板身份。应让面板所属读请求完整检查身份，并确保旧 finally 不操作较新的请求锁；任务级必要冲突恢复状态可以保留，面板提示不能重新点亮。

审阅曾直接调用 openCompare 在在途读取期间重开，观察到旧 success 替换新面板；核对模板后确认该时刻打开按钮被 busy 禁用，**不把该直接调用结果列为独立产品阻塞**。T4 使用上述页面可达的关闭/error 流程。

## 2. 已成立的修复和证据边界

| 项目 | 本次判断 |
| --- | --- |
| S1 | 首次 A→B→A 槽位释放、迟到 success/error 丢弃、同资源 seq finally 检查成立 |
| S2 | 普通保存/接受/适配各自提交框的同字段在途输入对账成立；跨编辑面待 T1 |
| S3 | 预填不算改动、关闭后的适配 dirty 纳入离开确认、后台 GET 不推进适配基线、拒绝绑定比较快照成立；比较重载关闭错误待 T4 |
| S4 | 配置/管理员原地重复写阻断、GET 失败重试、管理员最新具体文字及个人恒显示入口成立；任务重选/干净刷新待 T2/T3 |
| SettingsView | 实际脚本 requestLeave/confirmLeave/cancelLeave/logout 经桩卡片驱动；这是页面逻辑证据，尚非真实卡片+DOM整体验收 |
| 防泄漏 | 脚本实际捕获 console 输出并检测标记，替代旧常量断言；不泛化为所有框架/网络日志均已验证 |

本轮结果 §5 称配置 load 不再清冲突视图，但实际 `AiConfigCard.vue:92`–`:93` 仍清 conflictLatest/conflictPending，报告与代码不符。目前模板中的 load 重试位于无 baseline 分支，未证明正常冲突态可由 UI 触发，故不另列可达阻塞；下一轮须纠正报告或使代码按声明成立，不能把声明当验证证据。

没有上一轮施工前完整文件快照，无法独立证明本轮“仅改五文件”的历史差分；本复审针对当前完整工作区，未把既有 backend/锁改动归因本轮。

## 3. 协调者独立验证

在 frontend 执行 `npm run typecheck && npm run build && node scripts/ai-settings-1c-check.mjs && node scripts/ai-settings-1c-state-regression.mjs`：退出 0；typecheck 通过、build 成功（既有 >500kB 警告）、原 **29/29**、组件 **204/204**。仓库 `git diff --check` 通过。

补充一次性离线复现：Python 标准库读取现有 state-regression 脚本的 harness/fixtures 前缀，改 stdin 的模块路径后通过 `subprocess.run(['node','--input-type=module'], input=...)` 执行；沿用已安装 TypeScript、真实 Vue reactivity、实际组件 script setup、合成 API 与 Deferred，不写组件或持久测试脚本，无 DOM/服务器/网络/数据库。T1–T4 实际结果已逐项记录；输出只有场景名称与布尔/计数/版本，没有 secret 或请求载荷。T4 经真实接受 409 形成 stale，不直接设置 adaptOpen 冒充生命周期。

204 项全通过只证明其所覆盖场景，不能消除新增复现。真实浏览器 C1–C7仍全部未执行；1A/1B 后端、MySQL、迁移与既有日周/Word 本次未重跑，不把历史结果计作本次新证据。

## 4. 下一步

交 OpenCode 按[第三轮最小补修交接](ai-slice1c-repair3-opencode-prompt-2026-10-05.md)处理 T1–T4，以具体反例闭环，保留所有已通过路径。补修之后再次只读复审；当前不授权施工启动、部署或扩展其他 AI 能力。

复审通过后再形成 1A+1B+1C 完整未提交工作区的实际部署源/哈希清单、依赖和迁移准备、既定远程独立验收实例部署计划及主密钥安全准备。目标库迁移、SSH/部署、v2 发布和缺错主密钥夹具按规格另获授权；之后才做 C1–C7 桌面真实验收。不能只部署三个卡片漏掉后端/迁移，也不能以本机 WSL API 或 mock 页面替代远程验收。暂不进入 transport、worker、真实 AI 或材料/W6。
