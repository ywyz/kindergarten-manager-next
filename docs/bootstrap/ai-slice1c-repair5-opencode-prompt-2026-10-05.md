# AI 1C 第五轮最小补修交接（2026-10-05）

依据：[第四轮补修复审](ai-slice1c-repair4-review-2026-10-05.md)。本交接未自动启动施工或部署。

```text
你是 kindergarten-manager-next 业务代码唯一写入者 OpenCode。读 AGENTS.md、ai-settings-ui-1c.md、ai-settings-api-1b.md、ai-slice1c-repair4-review-2026-10-05.md 和第四轮/历史交接与结果。保留HEAD、所有既有工作区改动、历史报告。

只补V1，保留U1/U2及U3单份草稿已成立路径。允许本片三个AI卡片、shared纯辅助、必要SettingsView衔接、现有定向脚本及本片必要纯状态辅助文件。不得改backend/auth.ts业务规则/日周Word/依赖锁，不扩架构，不读.env/私人密钥，不安装依赖/Skill/MCP，不另起代理，不连数据库/供应商，不启动服务器，不SSH/迁移/部署/commit/push。

实际反例：待适配→openAdapt→f1输入适配草稿A→cancelAdapt关闭保留→普通f1输入不同草稿B→saveNormal返回409→companion GET返回已适配current/based=latest完整map→keepEditsNewBaseline。当前分支优先保留B后清adaptDraft，A无保留槽、静默丢失，提示却称适配文字已移入普通面。

保留修改必须保存两份真实编辑文字，直到用户明确处置；不得自动合并、任意指定普通/适配优先后删另一份，也不能只留一份隐藏内存。沿用已有可见草稿/只读参考/显式保存与放弃语义解决，文字去向和提示必须真实；如果需要新增产品选择流程，先列具体决定点等待确认，不自行增加工作流。真实载入最新明示放弃的路径仍须完整清理；只预填、同字段相同文字、只有一面dirty应保持既有正确语义。

用实际动作补回归：同字段两面不同dirty与相同文字、不同字段两面dirty、关闭适配后普通写409、远端current与仍待适配、被移除字段；保留后两份不同文字可见且可处置（模板绑定检查不替代DOM），保存/放弃后hasUnsavedChanges与SettingsView离开确认准确。mock按真实版本/状态演进，不无条件允许旧expected。不得直接mutate被锁输入冒充用户路径。纠正repair4 §8对双框优先分支与不丢文字覆盖的泛化声明，保留历史原文。

保留29项与321项有效覆盖，不删反例凑计数；防泄漏持续实际捕获输出，日志只场景名/计数，不打印secret/请求载荷。复跑typecheck、build、两定向脚本、git diff --check。新增docs/bootstrap/ai-slice1c-repair5-result-<实际日期>.md，记录V1代码/具体回归/实际命令与计数、未执行/偏离/决定点。真实浏览器C1–C7仍未执行。交付后停止等待复审，不部署、不启动其他切片。
```
