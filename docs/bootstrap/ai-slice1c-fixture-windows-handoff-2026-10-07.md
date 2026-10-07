# AI 1C 独立夹具 Windows 交接入口（2026-10-07）

准备依据：[实际远程结果](ai-slice1c-fixture-remote-preparation-result-2026-10-07.md)。场景行为继续按[夹具方案 §4–§5](ai-slice1c-fixture-plan-2026-10-07.md)和[原桌面补验提示词](ai-slice1abc-desktop-codex-prompt-2026-10-05.md)执行；方案 A 保持确认口径。本交接记录准备完成，不代替 Windows 补验、v2/v3 发布或故障密钥切换的授权。

## 当前真实基线

- 只使用 **https://kg-next-ai-fixture.ywyz.tech**，当前独立服务正常；原 kg-next-verify 域名不是本轮契约／密钥故障目标。
- release 为 `ai1c-v1-20261007-176b5ed`，工具哈希和 170 文件源身份见远程结果；正常独立 K_good，七任务全部 v1。
- daily_lesson_split 最新默认现场为 r8／v1；每次发布前托管者重新 inspect 后填写真实 expected，不用旧 r1 假设。
- `tfr_i5` 未初始化任何个人 head，适合契约案例；`tow_i5` 供既有手工链路定向验证。五个账号及原密码保留，仅登录临时实例。
- 账号私密文件在服务器 `/opt/kindergarten-manager-next-ai-fixture/private/acceptance-accounts.json`，通过已有私密通道交接；Windows 如需另存，沿用既有受限 ACL 目录，不放仓库或截图。
- 当前 sessions=0；B_contract 已实际恢复，恢复前后全部 25 表匹配。备份与配置在同一私密目录的 B_contract.sql／B_contract-app.env。

## 本轮执行授权与入口

2026-10-07 用户在了解 Windows／WSL 分工后明确授权契约发布、故障密钥切换及相应补验。授权已具备，无需重复申请；发布与切换仍按桌面阶段就绪信息顺序执行。本 WSL 会话没有 node_repl、cua_repl 或浏览器控制工具；Windows Codex／Edge 进程存在不等于当前会话能够操作真实 DOM。

第一步使用[Windows 首阶段提示词](ai-slice1c-fixture-windows-stage1-prompt-2026-10-07.md)，仅建立 C5 的 v1 个人状态并交回版本证据。收到并核对就绪报告后才发布 v2；在此之前保留正常主密钥与 v1 基线。未执行场景不记为通过。

## 下一阶段安排

授权后先由桌面端对照当前实际 URL／角色／基线。契约案例仍按 C5→V1/U3 四组及各变体推进：Windows 先在 v1 建立各例所需个人状态，托管者收到当前阶段就绪信息后才逐次发布；取得成功 manifest 后 Windows 继续真实 DOM／HTTP 动作，不先一次性发完 v2/v3。各例恢复 B_contract 时先退出并关闭自建页面，托管者停临时 API、归档证据、还原精确临时库与配套配置、清会话、重启核验，再重新登录。

缺／错主密钥阶段另交接：Windows 在临时 UI 保存新合成 secret，托管者核对当前版本确由 K_good 加密，建立 B_crypto 并实际恢复；之后才进入每轮服务配置切换与真实重启。错误主密钥下显式提交新 secret 可重新加密，不写成必然503。每轮恢复正常密钥与匹配数据后核验；供应商调用不在这些补验范围。

报告分别记录准备、发布、服务器配置状态、浏览器真实结果；仍受阻或未跑子例保持原状态。下载和手工 Word 定向回归不冒称完整 W6 或 Office/WPS 全页补验。完成后退出测试登录、关闭自建页面并按托管者交接恢复正常基线；退役与清理另定范围。
