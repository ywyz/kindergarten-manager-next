# AI 1C 隔离 MySQL 准备与验证复审（2026-10-07）

状态：**隔离 MySQL 验证及两项测试加固通过；本报告交付时进入远程资源准备清单授权阶段，尚未准备远程夹具；后续用户授权后已完成准备，见[实际结果](ai-slice1c-fixture-remote-preparation-result-2026-10-07.md)。** 授权为用户在[第三轮复审](ai-slice1c-fixture-repair3-review-2026-10-07.md)与[资源清单](ai-slice1c-fixture-mysql-plan-2026-10-07.md)交付后回复“授权”。本轮范围不含远程、主密钥切换、部署、供应商调用、commit／push 或资源删除。

## 实际资源身份

| 项 | 核验结果 |
| --- | --- |
| Docker | Server 29.8.2，复用已有镜像，未安装／拉取 |
| 镜像 | mysql:8.4.11；`sha256:6ea90827b1100f8f2ae306a539f86d2c264a26ed435a2a9f75551dd5c3aeb242` |
| 容器 | 新建 `kg-next-ai1c-fixture-mysql-20261007` |
| Volume | 新建 `kg-next-ai1c-fixture-data-20261007`，local |
| 监听 | 实际仅 `127.0.0.1:13387` → 3306；33060 未发布 |
| 数据库 | 实际账号连接后 SELECT DATABASE() 为 `kindergarten_test_ai1c_fixture` |
| 版本／引擎 | 实际 SELECT 为 8.4.11／InnoDB |
| 账号 | `ai1c_fixture_test`；USAGE 全局，ALL PRIVILEGES 仅精确本库，无 GRANT OPTION |
| 权限模式 | partial_revokes=ON，数据库权限按字面库名处理，不使下划线变为跨库匹配 |
| 私密文件 | `/home/ywyz/.local/state/kg-next-ai1c-fixture-20261007`，目录 0700、凭证文件 0600；未记录凭证或 DSN |

初始化镜像脚本在 partial_revokes=ON 下仍给库名下划线添加转义，造成首次测试账号连接 OperationalError。协调者仅撤销本新建账号的初始化授权并重新授予精确本库权限；SHOW GRANTS 与实际账号连接已核验通过。未修改其他账号、容器、库或历史资源。

## OpenCode 交接

使用[本轮交接](ai-slice1c-fixture-mysql-opencode-prompt-2026-10-07.md)启动独立 OpenCode run。只给该进程注入专用集成开关与 DSN，清除继承应用 DSN／主密钥及其他夹具变量；日志私密保存，展示内容去敏。协调者保留启动前受版本控制文件哈希，用于交付后核对写入范围。代码仅 OpenCode 写入，协调者不直接修正测试或产品实现。

OpenCode 的较大交接调用数次在输出长度限制处结束，未完成对应改动，不能用进程 exit 0 算交付成功。协调者拆成小步骤后，OpenCode 实际只写了本片集成测试文件：完整 v2 map dict 断言及字段文字互换离线变体、持锁函数的失败清理、释放函数保留原错并诊断独立清理失败、旧 rollback 失败检查按新语义更新。未修改产品代码或发布工具。新增 connect／close／dispose 组合故障覆盖由协调者临时离线探针执行，未伪称已新增仓库自动测试。

## 独立验证与审阅结论

真库进程仅注入专用集成开关与精确 DSN；离线单元进程另清除两个集成变量，统一禁用 dotenv、字节缓存并启用 PYTHONWARNINGS=always。原应用 DSN／主密钥及其他夹具变量均清除。

| 实际执行者／命令或检查 | 结果 |
| --- | --- |
| 协调者：真库 `FixtureIntegrationTests -v`（清理加固前的基线） | 14 项全部通过，66.378 秒，0 failure／error／skip |
| OpenCode：map 离线 `RestoredPublishV2AssertionsOfflineTests -v` | 6 项通过，0.008 秒；实际值互换变体被拒绝 |
| 协调者：最终 `tests.integration.test_ai1c_acceptance_fixture -v` | **37 项全部通过，9.597 秒；14 项真实 MySQL＋23 项离线，0 failure／error／skip** |
| 协调者：`tests.unit.test_ai1c_acceptance_fixture -q`（集成变量清除） | 38 项通过，7.504 秒，0 skip；预期非法 CLI 参数／开关拒绝 stderr 不算警告 |
| 协调者：实际锁辅助入口的组合故障临时探针 | 5 组通过：connect／begin／execute 主失败分别伴随清理失败；释放函数有原错／无原错且三步全部失败。验证原异常对象身份、全部应清理步骤都尝试、固定 notes／RuntimeError 不含合成 secret marker |
| 协调者：迁移与表引擎 | 唯一 head `20261003_ai1a_config_prompts`；25 张表全部 InnoDB；首轮结束恢复后的 daily 契约为 v1 |
| `git diff --check` | 通过 |

临时探针第一次从仓库根运行未设置模块路径，导入 tests 失败；随后显式 PYTHONPATH=backend 后实跑通过，不将第一次失败抹去。最终仓库测试与探针均未输出警告。本轮没有重跑全部 686 单元或其他集成套件；686 项结果属于前一轮独立复审。

最终 14 项真库逐项实际执行：两个受控锁持有／释放、CLI 子进程、同 expected 双发布者、inspect 不变式、后置失败回滚、产品先赢、v2 原子成功、v3 高修订 MAX+1、registry 不变式、重复／旧 expected 拒绝、第二份写失败回滚、工具与产品同时争用、工具先赢。产品受控锁测试实际核对 MySQL 1205；工具侧核对去敏 operational 错误、持锁期间零增量及释放后成功，不把工具侧错误码冒称单独读取了 1205。保护／审计语义均由真实快照核对。

代码审阅确认：持锁失败各步 best-effort 清理后原样抛出原错；释放函数三步均尝试，有活动异常时附固定 notes，不覆盖原错，无活动异常时清理失败显式报固定错误。没有业务查询或发布断言进入释放辅助函数。v2 map 比较完整字段与对应文字，值互换离线变体可拒绝。V3 成功用例保留既有字段集检查，本轮未扩成新的 V3 字段互换回归，不据此宣称该变体已自动覆盖。

启动前受版本控制文件哈希与加固后比较无变化；实际代码 Edit 日志只指向原本未跟踪的本片集成测试文件，保留用户既有修改与删除。协调者另检查 2026-10-05 部署机器清单的 170 个本地文件：全部存在且 SHA-256 全匹配；这只证明本地候选源未漂移，远程当前身份尚须现场核验。

## 产物身份与资源收尾

| 文件 | SHA-256 |
| --- | --- |
| `backend/tests/integration/test_ai1c_acceptance_fixture.py` | `29f8f6509a655debc0014fba0668432924016658722655b099b19da9a4d2ab26` |
| `backend/scripts/ai1c_acceptance_fixture.py` | `634f94d3cfb4ce0a6183a29c295dd82dd81838611cc63949c6639f38ac6ece47` |
| `backend/tests/integration/ai1c_guard.py` | `3b8ed2775d011278fd61d767397ef7cd541094bbb943c762f263d8b1b4c3eb88` |
| 私密 `coordinator-baseline-mysql.log` | `b2272b0506714ebddf2ee0bc0d033d04755003ec5217502e9483c63e62aabc5a` |
| 私密 `coordinator-final-mysql.log` | `e3047a55ebf822bf30e9178008cc27e7966274498729a391f65f961fdf67dbc9` |

测试进程及本轮 OpenCode 进程均结束后，已停止本次容器，实际 exited／exit code 0，13387 无监听。保留专用 volume、私密凭证及日志，未删除资源，未改历史 I5 容器。后续恢复本次容器仍须按实际任务授权使用，不能把其库当远程验收数据。

本报告当时的下一步是[远程准备执行清单](ai-slice1c-fixture-remote-preparation-plan-2026-10-07.md)的具体授权；后续执行身份见上述实际结果。真实 C5／V1／U3／C7 仍未补验，不宣布 1A–1C 产品全通过，不启动其他切片。
