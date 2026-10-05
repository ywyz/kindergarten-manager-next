# AI 1C 第三轮最小补修交接（2026-10-05）

依据：[第二轮补修复审](ai-slice1c-repair2-review-2026-10-05.md)。这是可交付的编码提示词，不表示协调者已启动施工或授权部署。

```text
你是 kindergarten-manager-next 业务代码唯一写入者 OpenCode。先读 AGENTS.md、ai-settings-ui-1c.md、ai-settings-api-1b.md、ai-slice1c-repair2-review-2026-10-05.md、本轮及历史补修交接/结果。保留 HEAD、全部既有工作区改动和历史报告。

只补 T1–T4，不重做1C。允许本片三个AI卡片、shared纯辅助、必要SettingsView衔接、现有定向脚本及本片必要纯状态辅助文件。不得改 backend/auth.ts业务规则/日周Word/依赖锁，不扩架构，不读.env/私人密钥，不安装依赖/Skill/MCP，不另起代理，不连数据库/供应商，不启动服务器，不SSH/迁移/部署/commit/push。

T1：适配请求期间普通 textarea 也可编辑，响应当前只对账adaptDraft却替换normalDraft，导致普通框在途输入丢失。覆盖全部实际可编辑入口；可按规格在适配请求期间明确锁定相关编辑/放弃操作，或捕获两份快照正确保留，不能静默丢一份、生成伪dirty、复活已放弃文字。优先最小锁定避免新增双框冲突合并产品规则。若选择锁定，检查模板绑定与实际边界，不能把直接调用被锁输入的mutation当正常用户输入；普通保存/接受和适配框既有在途对账路径按最终选择维持有效。

T2：管理员409状态随任务保存，重选当前任务与A→B→A不得清conflictLatest/pending后按旧基线再发PATCH。保留每任务草稿、最新比较数据、GET失败恢复入口；显式载入/保留后才能再写。保留旧epoch失效和finally所有权，不清新请求锁。

T3：个人pendingConflict本身保护基线与写门禁，即使普通文字回到旧基线、适配未编辑或已关闭。只读GET/重选/切换返回只能停放latest，不能自动清pending/推进expected。latest取得或失败、关闭比较、远端已适配等状态始终有显式恢复动作，不死锁。

T4：reloadCompareLatest绑定发起时compare身份；真实接受409形成stale→载入最新GET挂起→closeCompare→迟到success/error/finally不能更新已关闭或其他面板消息/目标/锁。task级必要冲突恢复状态保留，面板error不能重新点亮。核对模板busy禁用入口，勿只用不可达直接函数重开证明产品路径。

增强实际组件回归，逐项覆盖上述序列，断言新输入保留或真实锁定、pending/基线/目标、API写计数、显式恢复后下一次expected、迟到success/error/finally。保留原29项与204项有效覆盖；测试可按明确锁编辑方案适配，但说明替换原因，不删反例凑通过数。适配编辑→关闭→SettingsView返回确认可直接接入真实卡片exposed，补充已有桩卡片页面驱动；模板绑定检查不替代DOM验收。

纠正 repair2-result §5 中“配置load不再清冲突”的声明与实际源码差异；保持审阅指出的UI可达性边界，不夸大成已验收。日志只输出场景名/计数，持续实际捕获检查防泄漏；不打印合成secret/请求载荷。

复跑 npm run typecheck、npm run build、node scripts/ai-settings-1c-check.mjs、node scripts/ai-settings-1c-state-regression.mjs、git diff --check。新增 docs/bootstrap/ai-slice1c-repair3-result-<实际日期>.md，列T1–T4代码/具体测试/实际命令和数量、未执行/偏离、报告纠正。真实浏览器C1–C7仍未执行。交付后停止等待复审，不部署。
```
