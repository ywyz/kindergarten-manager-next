# AI 1C 夹具工具只读复审（2026-10-07）

结论：**暂不通过远程使用门槛。先交 OpenCode 最小补修，再完成隔离真实 MySQL 验证，之后才准备具体远程执行清单。** 当前 1A–1C 产品代码与方案 A 不需因此修改；工具与其集成测试存在独立问题。

依据：[交付报告](ai-slice1c-fixture-tool-result-2026-10-07.md)、[原编码提示词](ai-slice1c-fixture-opencode-prompt-2026-10-07.md)、[夹具方案](ai-slice1c-fixture-plan-2026-10-07.md)。审阅为本地工作区只读代码复核及离线验证，未连接数据库或服务器，未改工具／测试业务文件、未部署、未 commit／push。保留实现者报告的历史身份。

## 已成立的部分

工具范围符合要求：仅 inspect／publish-v2／publish-v3；连接前限定专用 DSN、模式、固定 host／port／库名并拒绝 query，原验收库不在白名单；发布缺开关先拒绝。工具不导入 tests，不提供 reset／drop，不修改 registry／产品入口／迁移或依赖。固定配方符合增删字段方案；发布取 v1 锚点排他锁、锁内 current read，追加契约与匹配默认在同一事务内，默认修订按任务全历史最新值递增。上述锁与事务的真实 MySQL 行为尚未实测。

协调者独立执行：清除继承的 DATABASE_URL／主密钥和本工具发布／集成环境变量，APP_DISABLE_DOTENV=1、PYTHONDONTWRITEBYTECODE=1，在 backend 使用 `.venv/bin/python -m unittest discover -s tests/unit -t . -q`，**679 项 OK，20.610 秒**。定向集成命令 `.venv/bin/python -m unittest tests.integration.test_ai1c_acceptance_fixture -q` 得 **9 项全部 skip**，不算真库通过。

## R1：提交后额外查询可把成功发布报成失败（阻塞）

位置：`backend/scripts/ai1c_acceptance_fixture.py:597–601`。先 db.commit()，再访问 overall_latest.default_revision。实际 CLI 使用默认 expire_on_commit=True 的 Session，commit 会过期 ORM 属性；这次读取可隐式发起新的 SELECT。若数据库此时不可用，except 调用 rollback 并向上抛错，但先前发布已经提交。CLI 最终固定提示“事务已回滚”，操作者可能以为没有发布，发布身份与报告不一致。

独立离线证据（未创建 engine／数据库连接）：实际 SQLAlchemy Session 加入一个 detached、clean 的 PromptDefaultVersion 后 commit，inspect 显示 default_revision 已过期；用同一 run_publish 的锁读与后置校验替身、在提交后读取属性时模拟刷新失败，得到 committed=True、随后 rollback attempts=1、函数抛错。前者确认本地 ORM 行为，后者确认控制流，不声称真实网络断连测试。

补修：提交前把所有结果字段保存为普通标量／容器，构建本次发布结果；commit 成功后不再访问 ORM 属性或执行数据库读写。增加有效的离线回归，证明成功返回没有提交后 refresh；已提交不能用后续读取失败归类为零增量／已回滚。也不要对 COMMIT 本身结果不确定的异常一概保证“零增量”；输出应指导先只读核对，不能自动重试。无需增加任务机制或改变产品代码。

## R2：集成测试尚不可用，不能直接用来放行（阻塞）

| 子项 | 代码事实／影响 | 最小修正 |
| --- | --- | --- |
| R2a 合法发布被当拒绝 | test_ai1c_acceptance_fixture.py:202 在 v2 发布后把 (target=3, expected_contract=2, expected_default=2) 放入 assertRaises。该组合正是合法 v2→v3，执行到这里必然与测试预期冲突；离线替身执行现有测试方法已复现 AssertionError | 拒绝矩阵使用真正旧 expected，合法推进在成功案例断言；各拒绝后比较零增量 |
| R2b CLI 路径变量缺失 | 同文件:313 使用 BACKEND_ROOT，但该模块既未定义也未导入；离线直接执行该测试方法已复现 NameError | 明确定义／导入路径，子进程以确定 cwd 和 interpreter 运行 |
| R2c JSON 未解码且断言对象顺序 | _fixture_rows 用无 JSON 类型标注的 text 查询，PyMySQL 对 JSON 列返回文本；后续 list(raw_fields) 或 raw_map.keys() 不成立。即便解码，MySQL JSON 对象键序也不能等同 guidance_fields 顺序 | 用 ORM／带类型 SQL 或显式 json.loads；数组字段可校验顺序，map 比较键集合与值，不依赖对象键顺序 |
| R2d head 列数不一致 | ai1c_guard.personal_world:261 只读 current_personal_revision、adaptation_state 两列，成功测试:177 却比较四元组 (1,current,None,1) | 查询和断言保持一致，实际核对 required／seen 等保护字段及发布前后快照 |
| R2e SQL 写失败异常类型不一致 | run_publish 仅 rollback 后原样 re-raise；超长 ID 触发 SQLAlchemy DataError／IntegrityError 时，测试:260 却只接受 FixtureError(ERR_DB_OPERATIONAL)。此错误码仅被声明，未转换实际 DB 异常；离线模拟 DataError 已复现未被测试捕获 | 核心与 CLI 明确错误契约；可回滚的 SQL 写失败以固定去敏码对齐，原始异常不能输出；保留真实错误注入 |
| R2f 个人种子不合法 | ai1c_guard:240 为 v1 六字段个人版本仅保存 theme，违反个人 map 完整字段集 Contract | 用六字段完整合成个人 map；不得用不合法状态证明发布不改个人 |

R2c 的判断依据本地驱动／SQLAlchemy 类型路径与源代码审阅，本轮未连接 MySQL；最终须在真实 MySQL 8.4 验证修正，不能以 SQLite 或 mock 代替。

此外 seed_v1_world 使用 engine.connect().execute(...) 未显式关闭连接；并发案例未核对线程是否退出、未统一捕获工作线程异常，也未覆盖“工具发布与真实同任务默认发布竞争”。修正资源生命周期与超时退出，并补足原提示词已要求的争用证据，不能靠多跑两个工具线程代替。

## 证据覆盖及报告补正

现有测试仅统计其他任务行数与提示词事件数，不能证明其他正文／operation_records／school_settings／业务表未改变。采用有意义的发布前后规范化快照比较，并添加默认 r1→较高修订后再发布契约的成功场景，证明编号真按全任务历史 MAX+1，而不只是1→2→3。

inspect 当前 select(PromptDefaultVersion) 会加载 guidance_map，虽未输出但与报告“不读取指导全文”不一致；可按需 select 最少列，保持字段／版本输出不变。

报告使用方法混用 backend/.venv/bin/python 与 scripts/... 相对路径，须明确 cwd（建议先进入 backend，统一 `.venv/bin/python scripts/ai1c_acceptance_fixture.py ...`）。原报告 SQLite 路径冒烟是离线证据，不是本项目 MySQL 验证，不继续用它补齐发布门槛。保持“679单元通过、真库未执行”的分层记录，不追溯改写首次报告。

## 下一步和完成条件

1. 按[最小补修提示词](ai-slice1c-fixture-repair-opencode-prompt-2026-10-07.md)由 OpenCode 补修 R1／R2，协调者独立复审。
2. 真库资源尚未授权／具备：需要一次性 MySQL 8.4／InnoDB、127.0.0.1:13387、精确 kindergarten_test_ai1c_fixture、独立仅本库测试账号；允许其迁移、测试数据准备与恢复。准备资源前先确认端口归属与可用镜像，不安装或拉取新依赖。本轮未建立资源，后续资源清单获授权才运行。
3. 真实集成全部实际执行且0 failure／0 error／0 skip，确认提交结果、故障回滚、锁序与真实默认竞争；再填独立远程实例清单，经相应授权准备。
4. Windows 接续剩余 C5／V1／U3／C7，全部证据收口之后才考虑持久执行核心。

当前不要求用户补充产品规则：方案 A 已确认。阻塞属于工具正确性、验证及资源准备，不是再次选择 A/B。
