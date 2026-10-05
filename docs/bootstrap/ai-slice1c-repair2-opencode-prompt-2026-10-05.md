# AI 1C 第二轮最小补修交接（2026-10-05）

依据：[补修复审](ai-slice1c-re-review-2026-10-05.md)。原 R1–R7 主要修复保留，本轮只处理 S1–S4 和验证缺口。

```text
你是 kindergarten-manager-next 业务代码唯一写入者 OpenCode。读 AGENTS.md、ai-settings-ui-1c.md、ai-settings-api-1b.md、ai-slice1c-re-review-2026-10-05.md、原审阅/补修交接及补修报告。保留 HEAD/status/全部既有工作区改动和历史报告。

本轮允许本片三个AI卡片、shared纯辅助、必要SettingsView离开衔接与现有定向脚本；可新增本片必要纯状态辅助文件。不得改backend/auth.ts业务规则/日周Word/依赖锁，不扩架构，不读.env/私人密钥，不安装依赖/Skill/MCP，不另起代理，不连数据库/供应商，不启动服务器，不SSH/迁移/部署/commit/push。

按复审全文处理：
S1 首次详情loading由请求所有者持有；失效槽位在切换时释放、新请求可重试，旧finally不清新槽。所有同资源detailSeq的finally也检查序号所有权。
S2 提交过的同一字段在请求后再输入必须保留；捕获请求草稿快照与响应对账，或请求期明确锁编辑。不要仅验证另一个未提交字段。接受/适配/初始化响应也验证实际可编辑边界，不复活旧文字。
S3 普通+适配dirty共同保护编辑基线和目标快照。适配预填与已编辑草稿正确区分；关闭保留文字仍属于未保存，离开必须确认。关闭面板真正失效对应success/error/finally，完整检查accept/reject/adapt；拒绝默认与接受同样绑定用户所见比较快照。后台GET不改变适配expected，直到用户明确采纳。不能靠直接设adaptOpen冒充关闭/恢复流程。
S4 配置PATCH/DELETE和管理员发布在待处理冲突期间阻断重复写，显式选择后再允许提交；冲突GET失败仍有安全恢复入口。管理员展示最新默认具体文字与草稿供用户比较。个人pendingConflict始终有可见恢复入口，dirty回到旧基线/远端已适配/关闭比较后也不能死锁。

补实际组件回归：首次A加载未完成→B→A→迟到success/error→A能再读；旧seq finally不解锁新请求；同字段写后继续编辑；适配dirty后台GET不推进expected；打开仅预填不算改动，编辑→关闭→返回设置离开确认；关闭比较/适配后的旧success/error/finally；比较v1后台看到v2后拒绝仍目标v1；配置/管理员409后不选动作无新增写、显式选择后可写；冲突GET失败可重试；个人dirty变干净且冲突未处理仍有恢复动作；管理员最新文字可见。对SettingsView实际requestLeave/confirmLeave/cancelLeave/退出清密钥动作离线驱动，不能仅检查卡片hasUnsavedChanges。模板恢复入口可用现有compiler-sfc或源码绑定检查，无新依赖；明确不替代DOM验收。

验证脚本防泄漏要实际捕获/检查输出或有可重复外部runner，不用ok(...,true)当证据；日志只输出场景名称/计数，不输出合成secret/请求载荷。复跑typecheck、build、原29项和增强后的组件回归、git diff --check。真实浏览器C1–C7仍未执行。

新增 docs/bootstrap/ai-slice1c-repair2-result-<实际日期>.md，记录S1–S4到代码/具体新增测试/实际命令结果、未执行与偏离、纠正上一报告gating/生命周期不符的声明，不覆盖历史。交付后停止等待复审，不部署。
```
