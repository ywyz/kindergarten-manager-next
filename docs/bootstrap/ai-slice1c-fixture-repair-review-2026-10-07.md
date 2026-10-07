# AI 1C 夹具工具补修复审（2026-10-07）

结论：**工具 R1 已解除，R2 集成验证仍未收口，暂不进入远程发布。** 下一步交 OpenCode 集中修正集成测试与 guard，再在获授权的一次性 MySQL 8.4 上实际运行。方案 A、产品入口及原验收实例保持既定范围。

依据：[补修报告](ai-slice1c-fixture-repair-result-2026-10-07.md)、[首次复审](ai-slice1c-fixture-tool-review-2026-10-07.md)、[夹具方案](ai-slice1c-fixture-plan-2026-10-07.md)。本轮只读代码与本地离线验证，协调者仅写文档；未修改工具或测试代码、未创建 MySQL 资源、未连接远程、未部署或 commit／push。

## 已确认的修复

- run_publish 的返回值全部在 commit 前捕获为普通标量／容器，成功 commit 后直接返回，无 ORM 属性读取。提交前 SQL 错误实际转换为固定去敏码；COMMIT 异常使用 AI1C_COMMIT_UNCERTAIN，要求 inspect 核对，不宣称零增量或自动重试。R1 解除。
- inspect 仅读取契约号／字段名和默认修订号／契约号，不加载指导正文。
- 上一轮的合法 v2→v3 拒绝矩阵、BACKEND_ROOT、原始 JSON 文本读取、head 查询列数、个人 map 完整性等修正方向成立。默认 r42→v2/r43→v3/r44 的测试已加入，真实执行仍待验证。

协调者独立运行：在 backend 下清除继承应用 DSN、主密钥、夹具发布与集成环境变量，APP_DISABLE_DOTENV=1、PYTHONDONTWRITEBYTECODE=1，`.venv/bin/python -m unittest discover -s tests/unit -t . -q` 得 **686 项 OK，16.943 秒**。本轮输出同时有 **5 条 SQLite 未关闭连接 ResourceWarning**，不能描述为无警告。新增所谓“内存 oracle”实际是 SQLite 内存引擎；只作为 SQLAlchemy 提交／过期行为的离线证据，不作为 MySQL 事务、锁或架构证据。无需将 SQLite 用于运行环境，建议关闭测试引擎消除警告。

定向 `.venv/bin/python -m unittest tests.integration.test_ai1c_acceptance_fixture -q` 得 **10 项全部 skip**；没有任何真实 MySQL 执行。

## S1–S5：确定的集成错误（阻塞）

以下五项均已用现有函数、合成数据和离线替身复现；探针本身没有创建 engine 或数据库连接。数据库部署后不应才发现这些基础运行错误。

| 编号 | 位置 | 事实与实际影响 | 最小修正 |
| --- | --- | --- | --- |
| S1 | ai1c_guard.py:55、131 | make_engine 调用 create_engine，但模块未导入该符号。给符合白名单的合成 URL 后直接 NameError(create_engine)，setUpClass 无法开始 | 补正确导入；离线验证 guard通过后确实进入预期创建入口、非法目标仍先拒绝 |
| S2 | ai1c_guard.py:369、375、382 | FIXTURE_TEACHER_ID 未定义，已有常量是 TEACHER_ACCOUNT。离线调用 seed_v1_world 已复现该 NameError | 统一真实种子账号常量并检查其余引用，不增造两个不一致身份 |
| S3 | ai1c_guard.py:444–452 | execute(select(SchoolSettings)).one_or_none() 返回包装 ORM 对象的 Row，不是 SchoolSettings；school_row.school_name 将 AttributeError | 使用 scalar_one_or_none／scalars提取对象；保留无行分支与实际字段快照。使用真实SQLAlchemy Row构造已复现属性访问错误 |
| S4 | test_ai1c_acceptance_fixture.py:475–481 | 同 expected 并发应一成功一拒绝，但收集所有 record.get(code) 包含成功方的 None。随后要求集合只含错误码，因此合法结果也必然断言失败 | 只校验拒绝方码，同时独立校验成功方结果。离线用合法两结果已复现 subset=False |
| S5 | test_ai1c_acceptance_fixture.py:199–209、643–664 | 产品发布胜出时，测试明确预期新增 operations／change_records，末尾却调用要求二者不变的 _assert_personal_untouched；合法产品胜出也必然失败 | 分离个人／身份／学校保护断言和本次动作允许的审计变化断言；工具胜出要求审计不变，产品胜出要求新增正确审计。离线给合法新增审计已复现 AssertionError |

## S6：竞争证据和时间线不可靠（阻塞验证）

新增工具×产品竞争仍以“屏障放行间隔小于5秒”和“输家函数返回晚于赢家函数返回”推定确实等待同一锁。这两项不足以证明实际重叠争用：双方可以在放行后顺序运行，输家读取新状态；而赢家 commit 释放锁后还可能被线程调度暂停，输家函数可以先返回，finished_at断言产生假失败。

此外竞争测试为产品服务构造默认 Session(expire_on_commit=True)，与实际 API 的会话设置不同。产品 update_default 在返回时读取 ORM 属性；在真实竞争中这次额外刷新还可能读到工具后续发布的更新状态，使错误来源混杂。

修正要求：用受控锁持有／释放和线程阶段事件建立实际竞争，验证另一方在锁持有窗口尚不能进入发布临界区，释放后再核对真实提交状态／失败码。事件不绕过数据库锁，不改变产品实现。产品竞争会话使用实际 API 的 expire_on_commit=False；分别可重复验证工具和产品两种胜负，审计断言按动作判定。SQL锁等待与工作线程设有限超时，所有线程退出后才允许reset／dispose；不能通过删掉竞争测试或放宽到任意错误通过。

## 范围外产品观察的判定修正

补修报告 §9 称 product update_default 的 commit 后属性读取是同类产品风险。本轮核对 backend/app/database.py:37–49，真实 API SessionLocal 两个分支均明确 expire_on_commit=False。因此“实际API必然触发过期属性刷新”这一前提不成立；不能把使用默认 Session 的测试路径直接归类为线上缺陷，也不据此开启产品补修。

报告可保留“函数若被其他 expire_on_commit=True 调用者使用可能触发刷新”的条件性观察，但须同时说明已核实的实际 API 会话配置。方案 A 不受此结论影响。

## 下一步与放行门槛

1. 按[第二轮集中补修提示词](ai-slice1c-fixture-repair2-opencode-prompt-2026-10-07.md)修正 S1–S6、测试资源清理及报告口径；增加覆盖这些 dormant 入口与合法竞争结果的离线检查，避免全skip掩盖确定运行错误。
2. 复审通过后申请／准备一次性 MySQL 8.4／InnoDB、127.0.0.1:13387、精确 kindergarten_test_ai1c_fixture、独立仅本库测试与迁移账号；不借用原远程库，不拉新镜像或安装依赖。资源授权另记。
3. 集成全部实际执行、0 failure／0 error／0 skip，真实回滚／锁竞争／编号／CLI结果通过后，再形成具体远程部署清单和 Windows 接续交接。

本轮无需用户补充产品决定。测试未通过不能阻止继续本地补修，但不能将“686单元通过＋10集成skip”作为远程工具验收结论。
