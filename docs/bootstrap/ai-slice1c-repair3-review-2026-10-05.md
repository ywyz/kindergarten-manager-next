# AI 1C 第三轮补修复审（2026-10-05）

结论：**仍不进入部署。上轮 T1–T4 的直接反例已修复，但交叉恢复路径仍有 U1–U3 三处 P2 问题；下一步仅做最小补修及回归。** 这不是重新开展架构或环境审计，也不扩大 AI 设置范围。

依据：[第三轮补修报告](ai-slice1c-repair3-result-2026-10-05.md)、[第三轮交接](ai-slice1c-repair3-opencode-prompt-2026-10-05.md)、[第二轮复审](ai-slice1c-repair2-review-2026-10-05.md)、[1C 规格](../specs/ai-settings-ui-1c.md)、[1B API](../specs/ai-settings-api-1b.md)。对象为当前完整未提交工作区；HEAD `1647fc934d41b29a844a807d454031e66a2b45af`，审阅开工 status 70 项。未写业务代码、读取 .env/私人密钥、安装依赖、另起代理、连接数据库/供应商、启动服务器、SSH、迁移、部署或 commit/push。新增本报告与下一轮交接，保留历史文件。

## 1. U1（P2）：比较重载清冲突却未采纳新个人基线

位置：`frontend/src/components/ai/PromptGuidanceCard.vue:729`–`:734`（reloadCompareLatest），`:214`（noteFreshDetail 的 pending 保护）。

T3 新增 pendingConflict 停放条件正确保护后台 GET，但 reloadCompareLatest 的显式采纳流程仍调用同一个停放函数。pending=true 时 fresh 被放入 latest，而 detail 不变；随后普通文字干净，reload 又清 latest/pending，形成“门禁解除、最新恢复数据被丢弃、个人基线仍旧”的状态。

实际组件离线驱动：初始个人 rev1→接受返回真实版本冲突→companion GET 得 rev2→保持比较开启，点击载入最新→GET 得 rev2→重新勾选接受。版本校验 mock 要求 expected=2；实际结果：

```text
parkedBefore=2
afterReload: baseline=1, pending=false, latest=null
writeExpected=[1,1], pendingAfterRetry=true
```

这是可达正常恢复动作，第二次接受仍因旧 expected 再次 409；反复重载/接受可循环失败。现有 T4 测试重载后关闭面板，覆盖 orphan 路径，没有覆盖面板仍开时的恢复成功及下一次 expected。

修复应将“后台停放”与“显式解决”分开处理：若用户明确采纳个人最新状态，正确同步 detail、编辑草稿与比较目标；若该动作仅刷新默认比较，则保留 pending/latest，要求先使用已有显式个人冲突动作。不得只清门禁，不能覆盖请求期间真实 dirty 文字。fresh 可能为 adaptation_required，应保持真实适配状态和完整适配入口，不能提示重新勾选后实际上仍按旧 current 状态提交。

## 2. U2（P2）：管理员 409 与比较 GET 之间仍可绕过门禁

位置：`AdminPromptDefaultsCard.vue:204`–`:212`、selectTask `:87`–`:103`。

每任务冲突缓存修复了“比较已经取得之后重选”的 T2 反例。但 state.conflictPending 直到比较 GET 成功或失败才设置。收到 409 时 GET 尚未完成，saving 暂时阻断写；用户此时重选任务，selectTask bump 并清 saving，而 state 仍无 pending。旧 GET 被 orphan 后，发布按钮与 save 入口重新开放。

实际流程：发布→PATCH 409→companion GET 挂起→重新点击当前任务（任务按钮可用）→再发布。结果：

```text
pendingDuring=false
writeExpected=[1,1]
pendingAfterReselect=false
```

第二次 PATCH 未经过载入/保留选择。应在识别 409 后、await GET 之前立即将对应任务设为 pending；读取完成只补充比较数据或失败恢复提示，任务切换不能解除已知冲突。验证重选当前任务和 A→B→A，以及旧 GET success/error/finally 不影响新任务、恢复重试仍可达。

## 3. U3（P2）：远端已适配后采纳最新，旧适配草稿被藏在不可操作状态

位置：`PromptGuidanceCard.vue:400`–`:415`（个人冲突动作）；适配整个区块由 `detail.adaptation_state === 'adaptation_required'` 控制，`:1395` 附近；hasUnsavedChanges 仍计入适配 dirty。

实际流程：本人待适配→打开适配并编辑→提交 409（另一会话已先适配）→companion GET 返回 based=latest=2、adaptation_state=current 的个人最新版本→点击“载入最新（放弃我的未保存修改）”。adoptLatest 仅重建 normalDraft，没有清旧 adaptDraft/adaptTarget/adaptRemovedDraft/adaptOpen。结果：

```text
before: pending=true, remoteCurrent=true
after: pending=false, adaptSectionVisible=false,
       hasUnsaved=true, adaptDirty=true
```

真实已适配态隐藏整个适配区，用户不能再看到、提交或显式放弃残余文字；普通编辑干净，但返回持续提示存在未保存修改。“保留修改”路径同样需要检查，不能保留一份无可见恢复入口的草稿。

第三轮报告 §4 和 T3 回归把“远端已适配”夹具设置成 adaptation_required，并断言 openAdapt 可达；实际验证的是远端仍待适配，不是 current。这不是措辞可以替代的覆盖，必须换成真实 current/based=latest 夹具并记录差异。

载入最新已明确表示放弃未保存修改，应完整处理适配残留，或明确展示独立处置入口；保留路径要让保留文字可见且可处理，不静默删除。沿用既有保存/放弃/恢复语义，若无法在既有规格内确定产品行为则报告具体决定点，不自行设计新工作流。

## 4. 本轮成立的修复

| 上轮项 | 本轮判断 |
| --- | --- |
| T1 | 每任务 adapting 锁定普通 textarea，busy 禁用并在函数入口阻断放弃适配草稿；适配框仍可编辑且快照对账保留在途输入。源码绑定与状态证据成立，真实 DOM 禁用尚待 C1–C7 |
| T2 | 已取得或已失败的冲突视图随任务保存，重选/A→B→A 不清门禁；GET 尚未完成阶段待 U2 |
| T3 | pending 自身保护后台 GET，普通文字变干净后仍停放 latest；与显式比较重载/真实远端已适配衔接待 U1/U3 |
| T4 | 比较重载捕获发起面板身份，关闭后的 success/error 不再回写，finally 有 token 所有权；面板保持开启的恢复分支待 U1 |
| SettingsView | 真实指导卡 exposed 接入实际页面脚本，适配编辑→关闭→返回确认/取消/放弃后离开成立 |
| 报告纠正 | 配置 load 不再直接清 conflictLatest/pending，与报告纠正一致；不扩称其无 baseline 重读为已做正常冲突态 DOM 验收 |

## 5. 独立验证与证据限度

协调者在 frontend 独立执行：

- `npm run typecheck`：通过，退出 0。
- `npm run build`：通过，退出 0；保留既有 >500kB chunk 警告，不要求无关拆包。
- `node scripts/ai-settings-1c-check.mjs`：29/29。
- `node scripts/ai-settings-1c-state-regression.mjs`：258/258。
- 仓库 `git diff --check`：通过。

补充一次性无文件写入复现：读取现有 state-regression 的 harness/fixtures 前缀，修正 stdin 模块相对路径，用 Python 标准库 subprocess 将代码送入 `node --input-type=module`；执行实际组件 script setup、已安装 TypeScript 与真实 Vue reactivity，合成版本校验 API 与延迟 GET。U1–U3 输出如上，命令退出 0；退出 0 表示复现程序完成，并不表示业务场景通过。无 DOM、服务器、网络、数据库；只输出名称、布尔、计数和版本，不打印 secret/载荷。

没有施工前完整文件快照，无法独立证实第三轮历史“仅改五文件”的差分或全部既有未提交修改的字节级保留；本次针对当前工作区，不把既有后端/锁改动归因本轮。真实浏览器 C1–C7 未执行；1A/1B 后端、MySQL、迁移、日周与 Word 本次未重跑，既有阶段收口记录继续作为历史证据。

## 6. 下一步

交 OpenCode 按[第四轮最小补修交接](ai-slice1c-repair4-opencode-prompt-2026-10-05.md)仅处理 U1–U3；重点跑完整恢复链和 GET 挂起窗口，验证下一次真实 expected 与无新增写，不以增加检查数量替代闭环。交付后再次只读复审。

目前可以梳理部署准备事项，但不能将其当成通过代码门槛或启动部署：后续需完整 1A+1B+1C 工作区部署源/哈希清单、依赖/迁移、既定远程验收实例与主密钥安全准备。待复审通过，再形成具体部署方案；SSH/目标库迁移/部署、真实 v2 发布及缺错主密钥夹具按既定规格另获授权，部署后进行 C1–C7。暂不进入 worker/transport/真实 AI/材料或完整 W6。
