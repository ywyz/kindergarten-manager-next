# AI 1C 第五轮补修复审与实现阶段收口（2026-10-05）

结论：**本轮复审通过，V1 已解除；当前未发现阻塞进入远程验收部署准备的问题。** 1C 的实现审阅与离线定向验证达到本片门槛，可接续完整 1A+1B+1C 部署源整理及部署方案。**不表示产品验收完成，不自动授权 SSH、目标库迁移、部署或 commit/push。**

依据：[第五轮结果](ai-slice1c-repair5-result-2026-10-05.md)、[第五轮交接](ai-slice1c-repair5-opencode-prompt-2026-10-05.md)、[第四轮复审](ai-slice1c-repair4-review-2026-10-05.md)、[1C 规格](../specs/ai-settings-ui-1c.md)、[1B API](../specs/ai-settings-api-1b.md)。此前未通过记录保留为历史，本记录为最新阶段判断。

审阅实际完整未提交工作区，HEAD 为 `1647fc934d41b29a844a807d454031e66a2b45af`。未写业务代码、读取 .env/私人密钥、安装依赖、另起代理、连接数据库/供应商、启动服务器、SSH、迁移、部署或 commit/push。只新增本收口记录；全部历史报告保留。没有施工前完整快照，不能独立证明实现者历史文件差分范围，未把既有后端和锁改动归因本轮。

## 1. V1 复核

`PromptGuidanceCard.vue` 的 keepEditsNewBaseline 现在对同字段两份真实编辑作完整保留：普通文字留在普通编辑框，不同的适配文字转入 adaptRemovedDraft 参考槽。两份相同文字只保留一份，不自动合并或静默删另一份。

参考区在待适配区之外渲染，标题已区分被移除字段原文与未提交适配文字，不再把同名保留文字误称为已移除字段。存在参考槽文字时，既有“放弃适配草稿”动作在 current 与 adaptation_required 两态均可达，busy 禁用规则保留。提示如实说明未合并文字位于只读参考区。

普通文字保存后，参考槽仍保留并计入 hasUnsavedChanges；显式放弃后干净。远端仍待适配时，普通面保存或放弃后重新打开适配，参考文字经既有 split 机制回到适配面；远端 current 时参考文字可查阅及显式放弃，没有引入一键换入普通面的新选择流程。这满足本轮“不静默丢失、可见、可显式处置”的要求。

已检查同字段不同/相同文字、不同字段双 dirty、远端 current/仍待适配、契约收缩、纯预填与单面 dirty、真实卡片接入 SettingsView 离开确认场景。U1/U2 和 U3 已成立路径继续通过；adoptLatest 的明确放弃仍清全部残留。源码与定向证据范围内未发现新增阻塞，不需要新增 ADR 或产品工作流。

## 2. 协调者独立证据

在 frontend 独立执行：

- `npm run typecheck`：退出 0。
- `npm run build`：退出 0；既有 >500kB chunk 警告保留，不要求无关拆包。
- `node scripts/ai-settings-1c-check.mjs`：29/29。
- `node scripts/ai-settings-1c-state-regression.mjs`：356/356；实际输出捕获的合成 secret/raw 标记检查通过。
- 仓库 `git diff --check`：通过。

补充独立 V1 恢复验证：用现有 harness/fixtures 前缀，经 Python 标准库 subprocess 传 stdin 给 `node --input-type=module`，运行实际组件 script setup、已安装 TypeScript、真实 Vue reactivity 与按版本校验的合成 API。真实动作 openAdapt→适配输入 A→cancelAdapt→普通输入 B→saveNormal 409→远端 current/rev2→keep：断言 B 留编辑器、A 留参考槽；再 saveNormal 按 expected=2 成功到 rev3，A 仍保留且页面 unsaved；最后 discardAdaptDraft 后页面干净。三条独立断言通过，退出 0。未写持久脚本、未 mutate 被锁输入，无 DOM/网络/数据库，不输出合成文字或请求载荷。

## 3. 限度与非阻塞呈现事项

真实浏览器 C1–C7 未执行；源码/编译绑定与脚本驱动不能代替真实 DOM、disabled 行为、参考区可视布局及持久化验收。双文字参考区与移除字段参考区共用行标签，需要在桌面验收确认用户可理解且可操作。

第五轮结果列出的“一键把只读文字换入普通面”及参考行单独呈现是可选产品扩展，不属于本轮修复门槛，不自动启动实现。现有文字可查阅、可显式处置，不因未新增该动作否定本轮闭环。

1A/1B 后端、MySQL、迁移及日周/Word 本次未重跑；其实现阶段依据分别为[1A 收口](ai-slice1a-closeout-review-2026-10-04.md)和[1B 收口](ai-slice1b-closeout-review-2026-10-04.md)，不把历史执行当本次新证据。目标验收数据库 migration current、实际服务器配置与主密钥尚未由本复审核验。

## 4. 下一步

下一步是完整工作区的部署准备，不再安排新一轮前端补修：

1. 整理 1A+1B+1C 实际部署文件与 SHA-256 清单，包含未跟踪业务文件、后端依赖锁、唯一新迁移和前端产物；HEAD 单独不足以标识这些未提交实现。部署源清单建立后若源文件变化，须更新清单与相关验证。
2. 形成既定远程独立验收实例的具体部署方案：源传输与构建、依赖、当前/目标迁移版本、目标库备份与恢复步骤、低权限账号、AI 主密钥安全配置、部署后验证。凭证与密钥不写报告，按安全渠道准备；不重新做全环境审计、不扩技术栈。
3. 按 [1C 规格 §7](../specs/ai-settings-ui-1c.md)另获 SSH/目标库迁移/部署授权后执行；部署交接记录实际 HTTPS URL、部署源标识、实际 migration current、角色测试账号与夹具状态。
4. 在部署实例执行桌面真实浏览器 C1–C7，重点补验双会话冲突、关闭/切换、双草稿参考区处置、账号退出密钥清理、原姓名/密码与手工日周/Word。v2 发布与缺错主密钥夹具另按授权准备，未具备子例如实记受阻；不改 registry 冒充发布，不以本机 WSL API 或 mock 页面替代远程实例。

暂不进入 transport、worker、真实 AI 或材料/W6。完整 W6 与 Windows Word/WPS 逐页材料补验仍归后续材料切片，不能由本设置收口替代。
