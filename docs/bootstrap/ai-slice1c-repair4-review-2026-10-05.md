# AI 1C 第四轮补修复审（2026-10-05）

结论：**U1/U2 已闭环，U3 的直接反例与单份草稿恢复已修复，但仍有 V1 一处 P1 文字丢失，暂不通过部署准备门槛。** 下一步只补双份草稿同字段的保留边界，不重做 1C。

依据：[第四轮结果](ai-slice1c-repair4-result-2026-10-05.md)、[第四轮交接](ai-slice1c-repair4-opencode-prompt-2026-10-05.md)、[第三轮复审](ai-slice1c-repair3-review-2026-10-05.md)、[1C 规格](../specs/ai-settings-ui-1c.md)。审阅实际完整未提交工作区；HEAD 仍为 `1647fc934d41b29a844a807d454031e66a2b45af`。未写业务代码、读取私人配置、安装依赖、另起代理、连接数据库/供应商、启动服务器、SSH、迁移、部署或 commit/push。仅新增复审与下一轮交接，历史报告保留。没有施工前完整快照，不独立证明实现者历史文件改动范围。

## 1. V1（P1）：保留修改时，普通与适配草稿同字段双 dirty 会丢一份

位置：`frontend/src/components/ai/PromptGuidanceCard.vue:438`–`:457`，keepEditsNewBaseline。

普通框和适配草稿可以同时存在真实用户改动。适配请求期的 adapting 锁只覆盖提交飞行窗口；关闭适配保留文字后，普通框正常可编辑。实际页面可达序列：

1. 初始个人基于 v1、最新契约 v2，处于 adaptation_required。
2. 打开适配，在 f1 输入适配草稿 A；真实 cancelAdapt 关闭面板，文字保留。
3. 在普通编辑框 f1 输入不同的草稿 B，点击保存。
4. 另一会话已适配到 v2/current/rev2，普通保存按旧 expected 返回 409；companion GET 停放真实远端 current、完整新字段与 map。
5. 点击“保留我的修改，以最新版本作为提交基线”。

splitAdaptDraft 的 keep 中仍含 A，但循环先选 `boxVal !== oldVal` 的普通草稿 B，跳过同字段 keep。随后清空 adaptDraft/target，而 removed 只包含不在目标字段集的文字，因此 A 被删除。提示却声称适配文字已移入普通面。

一次性离线驱动实际组件、真实 Vue reactivity、实际 openAdapt/cancelAdapt/saveNormal/keepEditsNewBaseline 动作，结果：

```text
before: pending=true, hasAdapt=true, hasNormal=true
after: normalPreserved=true, adaptPreserved=false,
       adaptDraftKeys=0, removedKeys=0
```

没有直接修改被禁用输入；两份文字在适配提交飞行窗口之外输入，属于正常可达流程。这里不能以“普通框优先”代替用户选择：规格要求保留未保存文字，第四轮交接也禁止静默删一份。无须自动合并同字段两份文本；应保持两份文字可查、可显式处置，或在既有流程的明确动作中让用户决定保留/放弃，不能先删再提示已保留。若必须新增选择流程，先报告具体产品决定点，不自行替用户定优先级。

## 2. 已成立的修复

| 项目 | 本次判断 |
| --- | --- |
| U1 | 比较重载只更新默认目标，保留 pending/latest；提示要求先解决个人冲突，显式动作后下一次 expected 正确；接受增加待适配守卫，状态化 mock 验证恢复链成立 |
| U2 | 识别管理员 409 后立即记录任务 pending，再 await GET；挂起时重选/A→B→A 门禁保持、旧 GET orphan、恢复重试后显式选择并按新 expected 发布成立 |
| U3 载入 | adoptLatest 清全部适配残留，真实远端 current 后无隐藏 dirty 成立 |
| U3 保留 | 只有适配同名文字被编辑时，文字迁到普通面可保存/放弃；契约收缩移除文字迁到区块外只读展示并有显式放弃入口成立；同字段双 dirty 待 V1 |
| 报告纠正 | 真实 current/based=latest 夹具已补，旧 adaptation_required 夹具声明已书面纠正，历史报告保留 |

第四轮报告 §8 声称没有双框合并，但代码实际包含普通文字优先的双草稿选择分支；该分支对异名字段可保留，对同名双 dirty 不完整。因此不接受其“保留路径全部不静默丢失”的泛化结论。

## 3. 协调者独立验证

- frontend `npm run typecheck`：通过，退出 0。
- `npm run build`：通过，退出 0；既有 >500kB chunk 警告保留，不要求无关拆包。
- `node scripts/ai-settings-1c-check.mjs`：29/29。
- `node scripts/ai-settings-1c-state-regression.mjs`：321/321。
- 仓库 `git diff --check`：通过。

补充复现采用现有 state-regression harness/fixtures 前缀，在 Python 标准库 subprocess 中传 stdin 给 `node --input-type=module`，修正相对模块路径后驱动实际组件 script setup；不写持久测试脚本，不引入依赖，无 DOM/服务器/网络/数据库。合成 409 与真实远端已适配 DTO；输出仅场景与布尔/计数，不打印 secret/载荷。退出 0 表示复现程序完成，V1 实际业务断言为适配文字丢失。

321 项覆盖已有单份草稿路径，未覆盖 V1 的同字段两份草稿。模板布局/disabled/只读区域的真实 DOM、C1–C7 尚未验收；1A/1B 后端/MySQL/迁移/日周/Word 本次未重跑，不复用历史结果冒充本轮执行。

## 4. 下一步

按[第五轮最小补修交接](ai-slice1c-repair5-opencode-prompt-2026-10-05.md)只补 V1，交付后再只读复审。当前不授权部署，不启动其他 AI 切片。

复审通过后形成完整 1A+1B+1C 工作区的部署源/哈希清单、依赖/迁移与主密钥安全准备和既定远程实例部署方案；SSH/迁移/部署另获授权，之后执行真实浏览器 C1–C7。代码审阅与离线回归不代表产品验收完成。
