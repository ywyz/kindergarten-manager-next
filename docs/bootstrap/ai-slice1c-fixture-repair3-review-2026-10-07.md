# AI 1C 夹具第三轮补修复审（2026-10-07）

结论：**T1／T2 的原阻塞已解除，可以进入获授权的隔离 MySQL 8.4 验证阶段；尚不放行远程夹具使用或 Windows 补验。** 不再要求先进行一轮重复离线补修。下面两项测试加固应由 OpenCode 在真库阶段一并完成，最终放行前核对；不改产品代码或发布工具。

依据：[第三轮交付](ai-slice1c-fixture-repair3-result-2026-10-07.md)、[本轮要求](ai-slice1c-fixture-repair3-opencode-prompt-2026-10-07.md)、[第二轮复审](ai-slice1c-fixture-repair2-review-2026-10-07.md)。协调者只读审阅代码、执行离线检查及更新文档，未创建资源、连接数据库／远程、部署、调用供应商或 commit／push；既有工作区改动保留。

## 已成立的修复

- T1：`_hold_anchor_lock` 在 Connection 上执行真实 `SELECT … FOR UPDATE`，RootTransaction 仅承担 rollback；成功返回资源三元组，begin／查询失败时清理取得的连接和事务。离线替身不提供事务 execute，实际辅助入口已覆盖。
- T2：`_release_anchor_lock` 已移除业务读取与发布断言，不再引用未定义的 after；v2/r2、created_by、复制的 input_vars／output_schema、head 和个人文字断言恢复到真实发布测试。
- 两个受控锁测试顺序正确：持锁、竞争方拒绝、持有窗口零增量、释放、重新发布、测试体内断言。有限等待、线程退出确认及恢复保护保留。真实锁管理器是否按预期运行仍待 MySQL 实测。
- R1 与 S1–S5 沿用此前已成立结论。本轮不重新审查产品规则，方案 A 保持不变。

## 独立执行证据

后端命令均使用现有 `.venv/bin/python`；清除 DATABASE_URL、AI_MASTER_KEY、AI_MASTER_KEY_ID、AI1C_TEST_ALLOW_PREPARE、AI1C_TEST_DATABASE_URL、AI1C_FIXTURE_DATABASE_URL、AI1C_FIXTURE_ALLOW_PUBLISH；设置 APP_DISABLE_DOTENV=1、PYTHONDONTWRITEBYTECODE=1，测试设置 PYTHONWARNINGS=always。

| 实际执行 | 结果 |
| --- | --- |
| `-m unittest tests.unit.test_ai1c_acceptance_fixture tests.integration.test_ai1c_acceptance_fixture -q` | 74 项，60 项离线实跑通过、14 项真库 skip；6.776 秒 |
| `-m unittest discover -s tests/unit -t . -q` | 686 项通过；16.571 秒 |
| 实际发布断言的字段文字互换探针 | 互换 theme／objectives 的值仍通过，确认下面的断言缺口 |
| 实际释放函数的 close 失败探针 | 原 ValueError 被 RuntimeError 盖过，原错只剩异常 context |
| `git diff --check` | 通过 |

测试输出包含拒绝开关及 argparse 非法参数用例的预期 stderr，没有警告输出。本轮未独立重跑全部 integration discover 或 ResourceWarning 专项；交付者的相关结果只作为交付记录。14 项真库 skip 不能计为通过。

## 真库阶段一并完成的测试加固

1. `test_publish_v2_success_is_atomic` 当前分别比较 map 的键集合和值集合，不能证明每个字段对应正确文字。应直接比较 dict 与 `recipe_guidance_map(2)`，仍不依赖键序；加一个字段间值互换会失败的离线变体。本轮已实际驱动该测试证明缺口，交付报告中“map 完整一致”的描述强于当前证据。
2. `_release_anchor_lock` 只忽略 rollback 错误，close／dispose 仍可能掩盖原测试错误；`_hold_anchor_lock` 的失败清理中 dispose 也未保护。应保证各步清理都被尝试，保留原始失败，并让单独的清理失败可被诊断；补 close／dispose 失败及 connect 失败入口验证。本项属于测试异常诊断加固，原 T2 的未定义 after／错误发布断言已解除，不再混记为同一阻塞。

业务与配套代码仍由 OpenCode 唯一写入；协调者没有直接修正这些函数。加固范围仅现有本片测试及必要离线覆盖，不扩展产品功能，不新增源字符串检查。加固后再复跑直接相关离线用例及本片真库套件。

## 下一步与放行门槛

下一步采用[一次性 MySQL 验证资源清单](ai-slice1c-fixture-mysql-plan-2026-10-07.md)。只读资源核对已确认 Docker Server 29.8.2、已有 mysql:8.4／mysql:8.4.11 镜像、13387 无监听；唯一列出的历史 I5 容器已停止，不能借用它的库或数据。尚未连接任何 MySQL，不能据此断言服务与表引擎已通过。

该清单经资源授权后准备独立容器、精确测试库和仅本库账号，由 OpenCode 一并加固上述测试并实际运行 14 项真库案例。必须本片 36 项（若新增覆盖则计数相应增加）全部实际执行，0 failure／error／skip，确认 MySQL 8.4／InnoDB、迁移及锁竞争落点，协调者复审后才形成远程执行清单。真库暴露失败时保留证据并交 OpenCode 最小修正，不把离线通过替代实测。

本机只运行一次性集成数据库，不启动 WSL 产品验收服务器。远程实例、原验收库、主密钥切换、Windows 子例及其他切片仍按既有门槛分别授权与登记。
