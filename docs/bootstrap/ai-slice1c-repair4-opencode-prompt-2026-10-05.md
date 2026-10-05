# AI 1C 第四轮最小补修交接（2026-10-05）

依据：[第三轮补修复审](ai-slice1c-repair3-review-2026-10-05.md)。仅为下一轮可交付提示词；协调者未启动业务施工或部署。

```text
你是 kindergarten-manager-next 业务代码唯一写入者 OpenCode。读 AGENTS.md、ai-settings-ui-1c.md、ai-settings-api-1b.md、ai-slice1c-repair3-review-2026-10-05.md 与第三轮/历史交接和结果。保留HEAD、全部既有工作区改动和历史文档。

只补 U1–U3，保留 T1–T4 已成立修复。允许三个AI卡片、shared纯辅助、必要SettingsView衔接、现有定向脚本及本片必要纯状态辅助文件。不得改backend/auth.ts业务规则/日周Word/依赖锁，不扩架构，不读.env/私人密钥，不安装依赖/Skill/MCP，不另起代理，不连数据库/供应商，不启动服务器，不SSH/迁移/部署/commit/push。

U1：真实接受409→companion最新个人rev2→比较保持开启→显式重载GET成功→重新勾选→下一次提交。当前noteFreshDetail因pending停放fresh，随后reload却清latest/pending，detail仍rev1，下一次expected又1。区分后台停放与显式解决；明确采纳时正确同步基线/文字/比较，或保留门禁并要求已有个人冲突动作。不能清门禁丢恢复数据却仍用旧基线，不能覆盖请求期间dirty。覆盖fresh为current与adaptation_required、同名文字变化，且版本校验mock真实拒绝旧expected、成功仅允许正确版本；验证正常恢复完整成功，不能只断言比较目标变新。关闭/迟到error/finally既有身份保护保留。

U2：管理员识别409后、await companion GET之前立即保存该任务pending。GET挂起期间重选当前任务或A→B→A不能解除门禁、不能新增PATCH；旧GET success/error/finally不清新任务锁。补success/失败/失效后恢复重试→显式载入/保留→下一次expected正确。不要只测GET已经完成后的重选。

U3：用真实远端已适配夹具（adaptation_state=current、based=latest、完整最新字段与个人map），不要用adaptation_required冒充。本人适配草稿已编辑→适配409→远端current→点击载入最新或保留修改，两种动作均必须可恢复。载入最新“放弃未保存修改”完整处理适配残留与target/open/removed，使无隐藏dirty；保留的文字应始终可见且有既有显式保存/放弃入口，不藏在已消失适配区、也不静默删除。不自行发明双框合并/新工作流，规格内不能确定时报告具体产品决定点。补真实卡片hasUnsavedChanges接入SettingsView离开动作，确认没有不可处置的隐藏草稿。纠正repair3-result §4“远端已适配”实际夹具仍待适配的覆盖声明，历史报告保留。

全部验证按实际模板可达动作设计；mock必须按真实状态/版本更新，不能永远返回初始态或无条件允许旧expected。保留29项和258项有效覆盖；若因明确方案调整测试，列具体替换原因，不删反例凑计数。防泄漏继续实际捕获输出，日志只场景名称/计数，不打印合成secret/请求载荷；模板检查不替代DOM。

复跑npm run typecheck、npm run build、node scripts/ai-settings-1c-check.mjs、node scripts/ai-settings-1c-state-regression.mjs、git diff --check。新增docs/bootstrap/ai-slice1c-repair4-result-<实际日期>.md，逐项映射U1–U3代码/具体测试/实际命令结果与数量、未执行/偏离和声明纠正。真实浏览器C1–C7仍未执行。交付后停止等待复审，不部署或启动其他切片。
```
