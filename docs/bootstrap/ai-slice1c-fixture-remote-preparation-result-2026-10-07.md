# AI 1C 独立远程夹具准备结果（2026-10-07）

结论：**独立远程实例与正常 v1 基线已准备完成，B_contract 已实际恢复并核对通过；真实契约演进和缺／错主密钥的 Windows 子例尚未补验。** 用户在[远程执行清单](ai-slice1c-fixture-remote-preparation-plan-2026-10-07.md)交付后要求“请提交 推送 然后授权”；本轮先将夹具、验证及既有文档整理提交并推送 `176b5ed` 到 origin/main，再接续执行远程准备范围。最后核验时间为 **2026-10-07 16:40:38（Asia/Shanghai）**，原始 UTC 为 `2026-10-07T08:40:38.979195+00:00`。

## 实际身份与边界

| 对象 | 实际结果 |
| --- | --- |
| HTTPS／SSH | https://kg-next-ai-fixture.ywyz.tech ／ root@bwh.ywyz.tech；A 与 AAAA 均与原服务器匹配，真实 HTTPS health 成功 |
| release／current | `/opt/kindergarten-manager-next-ai-fixture/releases/ai1c-v1-20261007-176b5ed`；独立 current 指向该 release |
| 服务／运行账号 | `kg-next-ai-fixture-api.service` enabled、active；低权限 `kg-next-ai-fixture` |
| API 监听 | 仅 `127.0.0.1:18091`；无 worker |
| MySQL／目标库 | 既有 MySQL 8.4.11／InnoDB、127.0.0.1:13386；只写 `kg_next_ai1c_fixture` |
| 数据库权限 | 新 `kg_next_ai1c_app` 仅本库 SELECT／INSERT／UPDATE／DELETE；新 `kg_next_ai1c_prepare` 仅本库准备权限；无其他业务库授权与 GRANT OPTION |
| 权限模式 | 服务器 partial_revokes=0；按该模式转义库名下划线，SHOW GRANTS 与实际账号连接均验证成功，未更改服务器全局模式 |
| 运行源 | 原 `ai1abc-20261005-b08234d51044` 的[170 文件机器清单](ai-slice1abc-deployment-source-2026-10-05.json)；原源、新副本最终逐文件 SHA-256 全匹配；工具另列，不以本轮 Git HEAD 代替运行身份 |
| Python | 复制独立 .venv，解释器实际为 /usr/bin/python3.12；26 项已安装依赖版本与原源全匹配，无安装／升级 |
| 主密钥／配置 | 新随机独立 K_good，实际验证合法 32 字节且不等于原实例材料；key ID `ai1c-fixture-20261007`；禁用 dotenv；私密配置仅服务器 root 可读 |
| Cookie | 真实登录核对 Secure／HttpOnly／host-only，无跨子域 Domain |
| 原实例 | 原 18090 服务与原 HTTPS health 持续通过；未改变原 current、数据库内容、密码、主密钥、服务或原 Caddy 站点文件 |

实际 Caddy 原路由在 `/etc/caddy/kg-next-i5/verify.caddy`，由主 Caddyfile import。本轮保留该文件，主配置只追加独立域名对应块；备份、validate 后 reload。原路由哈希最终不变，其他同机应用、容器与路由未改。

## 合成数据、正常基线与恢复

原库账号精确为既有五个合成验收身份 `adm_i5`、`tow_i5`、`tsw_i5`、`tcr_i5`、`tfr_i5`，与原私密验收账号文件一致；按既有合成数据来源与本次账号核验取得一致性快照。快照未含跨库 USE／CREATE DATABASE／DROP DATABASE，使用精确临时库准备账号导入。所有 24 张非会话表规范化行哈希与原库一致；临时会话清空。实际 schema 无独立恢复令牌表／列，未凭空修改账号历史。

| 基线指标 | 最终实际值 |
| --- | --- |
| Migration | 唯一 `20261003_ai1a_config_prompts` |
| 契约 | 七任务全部 v1；daily_lesson_split 的唯一契约为 v1，六字段固定锚点存在 |
| 默认 | 全库 14 行；daily_lesson_split 最新默认 **r8／contract v1**；后续发布先现场 inspect，不硬编码旧 r1 |
| 未初始化教师 | `tfr_i5` 的 personal heads 为 0，真实 GET 后仍为 0；未删除个人历史冒充初始 |
| 会话 | 最终临时 sessions 为 0 |
| 业务数据 | accounts 5；daily_plans 32／contents 44；weekly_plans 10／contents 28／confirmed_contents 13 |

五账号真实 HTTPS 登录、me、AI 配置 GET、七任务列表及七详情读取、登出通过。管理员默认 GET200，四教师403。adm／tsw／tcr／tfr 当前 NOT_CONFIGURED，tow 当前 MISSING_SECRET，未测试供应商调用。临时实例使用正常有效主密钥不等于账号已配置合成 secret；B_crypto 尚未形成，后续 Windows 在临时 UI 清除旧 secret 并保存新合成 secret 后再建立该基线，历史密文不重写。

发布工具实际 acceptance inspect 成功，发布开关未打开：v1／r8、MySQL 8.4.11、目标迁移及六字段均匹配。本轮没有发布 v2／v3。公网 index.html 和两份 JS／CSS 逐文件哈希与运行源匹配。

先停止临时 API、清临时会话，再备份 B_contract 与配套正常配置；实际将 SQL 恢复到同一精确临时库，清会话并核对 **25 张表恢复前后规范化行哈希完全一致**、七个 v1、迁移与未初始化教师状态。重启后 tfr 的真实 HTTPS 登录／me／七任务及详情读取／登出通过；再清临时会话并重启，最终临时与原实例 health 均成功。不是只有备份哈希的恢复声明。

## 证据与私密交接

私密目录 `/opt/kindergarten-manager-next-ai-fixture/private` 为 0700，文件为 0600。包含 app.env、fixture.env、mysql-accounts.json、acceptance-accounts.json、源清单、数据复制核验、inspect、HTTPS 冒烟、依赖版本、服务／Caddy身份、恢复核验及最终状态。SQL、密码哈希、密文、凭据和主密钥未进入 Git 或终端输出。

| 产物 | SHA-256 |
| --- | --- |
| 发布工具 | `634f94d3cfb4ce0a6183a29c295dd82dd81838611cc63949c6639f38ac6ece47` |
| 原合成一致性快照（491885 字节） | `f7ed78d9bfe1e9394721b224d0951786cbe7f900b5c280af1719d8af62c0fe60` |
| B_contract.sql（479427 字节） | `21cfa2e017eeb111e7464321f7f777a6387223a4fecb98ecba9e1396def4ea2e` |
| 新 service 单元 | `61c41df6abdd6484f3384341c5be8547134ec10d04cab93db7b666b6cd2f1cb4` |
| 原 Caddy 站点文件（不变） | `7a58f70915705d27b0c7a56df52afe2bd4483a9518ec576b5e068f1ac577865c` |
| Caddy 主配置备份／新增后 | `2706c948e63cc64c89ab2b1bfe10569fd9e7539ce6054634461251976a33b54f` ／ `fbf49d3db3fae5d7f636b7251580c0c7c111afa9bc43b2a1aca30c9dad8ff588` |

本机另保留去敏汇总 `/home/ywyz/.local/state/kg-next-ai1c-remote-20261007/remote-evidence.json` 及私密执行日志，不纳入 Git。Windows 交接见[准备完成后的桌面入口](ai-slice1c-fixture-windows-handoff-2026-10-07.md)。

## 失败记录与停止点

首次导入因协调者把 docker exec 的环境选项放在容器名后而失败，未导入或写原库；修正参数位置后精确目标导入成功。首次 Caddy 模板查找错误地假定原域名块在主文件，查找失败时新 API 未启动、Caddy 未改；核实真实 import 后追加站点成功。预启动探测的新 API／新域名连接失败保留为该时间窗口记录，不追溯改写成通过。服务器无 rg，使用 Python 文件搜索，未安装工具。

准备通过不替代真实 C5／V1／U3／C7 验收。后续契约发布、故障密钥切换及 Windows 场景仍按阶段授权与 manifest 交接，不自动执行。B_crypto、完整 W6、其他切片与原环境清理均未进入本轮范围。临时服务现保留正常运行，未退役或删除资源。
