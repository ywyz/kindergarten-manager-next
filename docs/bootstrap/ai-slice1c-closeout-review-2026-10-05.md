# AI 1C 第五轮补修复审与实现阶段收口（2026-10-05）

结论：**本轮复审通过，V1 已解除；当前未发现阻塞进入远程验收部署准备的问题。** 1C 的实现审阅与离线定向验证达到本片门槛，可接续完整 1A+1B+1C 部署源整理及部署方案。**不表示产品验收完成，不自动授权 SSH、目标库迁移、部署或 commit/push。**

依据：本片有效规格、交付代码及下述最终复核证据。重复的旧结果／审阅与已执行提示词已于 2026-10-07 清理，历史版本可从 Git 查询。

审阅实际完整未提交工作区，HEAD 为 `1647fc934d41b29a844a807d454031e66a2b45af`。未写业务代码、读取 .env/私人密钥、安装依赖、另起代理、连接数据库/供应商、启动服务器、SSH、迁移、部署或 commit/push。当时只新增本收口记录。没有施工前完整快照，不能独立证明实现者历史文件差分范围，未把既有后端和锁改动归因本轮。

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

## 后续状态（2026-10-07 更新）

1A／1B／1C 均已实现并部署，见 [实际部署结果](ai-slice1abc-deployment-result-2026-10-05.md)。本文的测试数量、HEAD 与环境说明是原审阅时的证据，不代表当前工作区的新执行结果。

产品状态以 [Windows 验收报告](ai-slice1c-desktop-validation-2026-10-05.md)为准。剩余契约演进及缺／错主密钥子例仍受阻，当前先完成夹具工具补修与隔离真库验证，再按具体授权准备远程补验。真实 AI、worker、材料及完整 W6 不由本阶段收口替代；当前操作入口见 [文档索引](README.md)。
