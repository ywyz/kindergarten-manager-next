# 当前：关闭／恢复目标机增量结果与保留项

更新：2026-11-06。继续 `codex/desktop-v2-foundation`，唯一执行入口。开发机已完成获授权的限定修复与审核，结果见[开发机§10](../bootstrap/desktop-regression-repair-review.md#10-2026-11-06测试机回执接收与关闭交错回修)。原实现责任已结束，不重放旧白名单。

## 1. 已接收与已验证

已快进接收用户指定 `96dc1d7a555a1eec8bd33c2139a74f0a706c0e06`（parent6b0a99e，tree6133b1e7d9f1b4ecdd0d62c4cff4cf1cf9a2bedf），测试机原文见[目标§9](../bootstrap/desktop-windows11-white-concurrency-review.md#9-2026-11-056b0a99e接收及3e0e42b候选限定复验)。其101项源码及source3e0e42b／build e12d7af1／run42010782459／artifact13406493851的冻结外部恢复、提示X、退出与完整指纹通过保留原身份，未迁移为本轮补丁的冻结结论。

开发机已修复故障与close协议交接、一次性许可语义、owner／安装撤销失败和并发唤醒、清理失败被误报成功退出，以及验证器首失败／精确新旧窗口所有权／watchdog收尾。Codex独立216项相关测试及8个反例复测通过，最后550份非Markdown源码指纹稳定；实际真实服务／内部对象合同通过，窗口与adapter为替身。首失败、中间回归、原生metadata及边界均归§10。未新增依赖、迁移、教师流程或改后端runtime终结合同。

原A `ses_ead8af71dffeJphI1NOWg4jZgI` 固定build／opencode-go/deepseek-v4.1-flash#max；原C `8cf528de-8773-4a06-9cc5-31e96fab515f` 固定deepseek/deepseek-v4.1-flash／max，只读交叉审阅。Codex负责正式文档、独立审核验证与Git门禁。后续修复须按新证据重新明确互斥文件责任，不fork／子代理、不冒用测试机会话、不接管在途修改；C权限拒绝保留，不放宽或绕过。

## 2. 本轮目标机结果与证据

指定 b657363c12901d5f559f3ef88e1ff5f0bd7926f0／tree 3b23e76d288083f84e2e0731579f2bec223416f0 的原 Windows 11 增量已完成，见[目标机核查 §10](../bootstrap/desktop-windows11-white-concurrency-review.md#10-2026-11-06b657363-原-windows-11-关闭恢复增量)。run 42130919515／attempt 1／artifact 13463875656 的普通保存关闭、renderer／browser 外部恢复与独立冷开均通过。六次正式宿主 exit 0，完整默认与 runtime 指纹逐阶段保持。F01 取证写盘、F02 过早读取回执均已原机留证。后续候选仍须单独核对同源自动 CI 及包身份；不主动 dispatch 或重跑旧 CI。

## 3. 下一步与保留项

本轮没有待回修的产品失败。普通许可不复用及 ack／fault 精确交错分别保留“源码已验、冻结运行未验”。原测试机已人工确认同一冻结包 renderer 提示的默认 Enter 与 Escape 均保留故障窗口，见[目标机 §10.6](../bootstrap/desktop-windows11-white-concurrency-review.md#106-原测试机人工键盘补验)。冻结内部身份、退休顺序及真实 vendor 回调阻塞仍未验；若需收口，先确定最小可观察方案及授权。无需重复已经完成的外部故障、冷开或全套源码测试。

本次结果按 Codex 审核的两份文档、准确 blob、parent 和 staged tree 交测试机原 OpenCode 普通提交推送；远端变化时重新核对，禁止 add-all、amend、rebase／force 或 merge 提交。

## 4. 持续边界

开发机SAC4551不启动受阻新旧EXE／helper，不改名、换路径、去来源标记或降低保护重试。既有输入能力拒绝不绕过。仍用CPython3.14.10 x64标准GIL／锁定依赖，禁dotenv／pyc、SQLAlchemy纯Python、Python loopback守卫；守卫不外推OS／WebView隔离。合成根与源／目标边界先核；真实原库／照片／key／DPAPI、旧包及首失败保留，应用真实AI0，不重发unknown。

旧失败原因、自然白屏、Word/r差异、长根206、Win10／WPS／干净机／其它显示条件保持原未验。不重跑整套backend、旧39项、13份43页Word、微软拼音或W6跨120秒睡眠。不启动签名、安装更新、真AI、WebDAV、Office注册修复、远控或发行。
