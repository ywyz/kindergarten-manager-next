# AI 1C 独立夹具历史状态与剩余事项（2026-10-07）

2026-10-09 文档整理：本文保留 v1 夹具的已知状态、授权记录、恢复边界和未验定义，不再作为当前桌面开发执行提示词。当前工作以 [Architecture v2 实施入口](architecture-v2-readiness.md)为准；本次整理未连接远程，也未重新核验服务或测试页面是否仍在运行。

**最后一份 Windows 结果已确认 C5 v2 主流程通过。** 2026-10-07 20:50（Asia/Shanghai），`tfr_i5`／`daily_lesson_split` 的个人 revision4、based contract2、latest contract2、default9、accepted default9、adaptation_state=current。普通保存、完整适配、草稿保护、真实提交飞行窗口锁定和刷新持久化均有证据，详见 [C5 Windows 结果](ai-slice1c-fixture-c5-windows-result-2026-10-07.md)。V1/U3 四组及其变体、参考区处置和 C7 缺／错主密钥仍未验，不宣布 1A–1C 全通过。

## 已完成阶段与证据

| 阶段 | 记录与边界 |
| --- | --- |
| 独立实例与 B_contract | [远程准备结果](ai-slice1c-fixture-remote-preparation-result-2026-10-07.md)：独立服务、正常主密钥和七任务 v1 已准备；B_contract 实际恢复前后 25 表匹配。该结果是准备期事实，不是当前 v2 现场。 |
| C5 v1 个人状态 | [首阶段结果](ai-slice1c-fixture-windows-stage1-result-2026-10-07.md)：20:18:33 刷新 GET200，个人 revision2／based1／default8，六份合成标记持久。原保存请求 HTTP 未捕获，缺口仍保留。 |
| C5 v2 唯一发布 | [发布记录](ai-slice1c-fixture-c5-v2-publication-2026-10-07.md)：20:25:17 发布 v2／r9；未修改个人表、未发布 v3、未切主密钥、未调用供应商。 |
| C5 v2 Windows 验证 | [最终结果](ai-slice1c-fixture-c5-windows-result-2026-10-07.md)：20:50 主流程及真实飞行窗口通过；文内早先工具受阻报告保留为历史，不覆盖顶部成功结果。 |

上述阶段的原始执行提示词已清理；阶段结果保留实际动作、HTTP、版本和证据清单。没有记录证明 C5 后已恢复 B_contract、形成 B_crypto 或完成其余子例，不据此推定现场已经复位。

## 历史资源与授权

- 独立夹具域名为 `https://kg-next-ai-fixture.ywyz.tech`；原 `kg-next-verify` 域名不是契约／密钥故障目标。
- 准备期 release 为 `ai1c-v1-20261007-176b5ed`，工具哈希、170 文件源身份、端口和权限见远程准备结果。正常独立密钥称为 K_good；准备时七任务全 v1、daily 最新默认 r8，随后仅 daily 已发布 v2／r9。
- `tfr_i5` 用于契约案例，`tow_i5` 用于手工链路定向验证。五个合成账号与原密码保留，凭据不得进入仓库或截图。
- 服务器私密目录 `/opt/kindergarten-manager-next-ai-fixture/private` 保留 `acceptance-accounts.json`、`B_contract.sql`、`B_contract-app.env` 和发布 manifest；实际文件与权限记录见远程结果。Windows 私密证据位于 `C:\Users\yw980\.codex\tmp\ai1abc-desktop-acceptance-20261005\logs`。
- 用户在 2026-10-07 明确授权过该轮契约发布、故障密钥切换与 Windows 补验；首阶段就绪后才发布 v2，发布成功 manifest 后再进行 Windows 适配。该历史授权及执行范围保留，本轮文档整理不继续远程操作。
- 当时协调会话在 WSL，无真实浏览器工具，因此采用 WSL 托管与 Windows DOM 验收分工。这是该轮环境记录，不是新桌面项目必须使用 WSL 的规则。

## 保留的未验定义与恢复边界

具体场景保留在[夹具方案 §4–§5](ai-slice1c-fixture-plan-2026-10-07.md)，方案 A 的同契约旧默认可接受口径保持不变。

- **V1/U3**：远端已适配／仍待适配、同字段去重／不同字段双草稿、收缩契约移除字段，以及普通框与参考区文字、明确处置、离开确认仍需真实 DOM／HTTP 证据。已完成 C5 不替代这些冲突子例。
- **C7**：B_crypto 尚无已完成记录；必须先在正常 K_good 下通过 UI 保存新合成 secret，确认当前密文身份并形成、实际恢复该基线，才能验证缺／错主密钥。错误主密钥下显式提交新 secret 可重新加密，不能写成必然 503。
- **阶段交接**：历史方案要求 Windows 先准备个人状态，托管者核对后单次发布，再用成功 manifest 接续真实页面；不批量提前发布 v2/v3，不以 API 直调替代 DOM。
- **恢复**：各例恢复 B_contract／B_crypto 前，Windows 退出并关闭自建测试页面，托管者停临时 API、归档证据、还原精确临时库及配套配置、清会话、重启核验，再重新登录。不得修改原实例或把恢复当成产品历史回退。
- **证据边界**：准备、发布、服务器配置、真实浏览器和模拟分别登记。供应商调用不在这些补验范围；手工 Word 下载不替代完整 W6 或 Word／WPS 逐页验收。退役、删除和原环境清理不因文档清理而发生。

这些历史未验项保留原状态，不作为桌面方向的总阻塞。如未来重启其中某项，应根据实际任务范围和现场状态形成当次交接，不能直接重放已使用的提示词。
