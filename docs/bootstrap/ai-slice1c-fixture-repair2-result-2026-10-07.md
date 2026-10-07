# AI 1C 夹具第二轮集中补修结果报告（2026-10-07）

状态：**S1–S6 与测试／报告问题集中补修完成，离线验证完成；停止于"交协调者复审"停止点**。真库资源未获授权、未具备，全部集成真库用例如实登记 skip，未连接任何数据库服务器，未创建库／容器，未安装／拉镜像，未操作主密钥，未调用供应商，未 commit／push。

依据：[补修复审](ai-slice1c-fixture-repair-review-2026-10-07.md)、[第二轮集中补修提示词](ai-slice1c-fixture-repair2-opencode-prompt-2026-10-07.md)、[上轮提示词](ai-slice1c-fixture-repair-opencode-prompt-2026-10-07.md)、[夹具方案](ai-slice1c-fixture-plan-2026-10-07.md)、[上轮补修结果](ai-slice1c-fixture-repair-result-2026-10-07.md)（历史保留，不追溯改写）。

工具 R1（发布返回值捕获／COMMIT 边界）已由协调者确认成立，本轮未重做、未改动 `backend/scripts/ai1c_acceptance_fixture.py`。方案 A 口径不变。协调者与用户已有文档修改全部保留。

## 1. 实际修改文件（本轮范围）

| 文件 | 内容 |
| --- | --- |
| `backend/tests/integration/ai1c_guard.py` | S1 导入 `create_engine`；S2 统一 `TEACHER_ACCOUNT`（消除未定义 `FIXTURE_TEACHER_ID` 的三处引用）；S3 `world_state` 用 `session.scalars(...).one_or_none()` 提取 SchoolSettings ORM 实体；新增 S4/S5 断言语义纯函数（`assert_protected_state_untouched`／`assert_audits_unchanged`／`assert_audits_append_only`／`assert_product_audit_append_legal`）、`AUDIT_KEYS`／`PROTECTED_KEYS` |
| `backend/tests/integration/test_ai1c_acceptance_fixture.py` | S4 只校验拒绝方错误码、成功方另行校验；S5 保护／审计断言分离并替换全部旧 `_assert_personal_untouched` 调用点；S6 删除时刻/间隔推定，新增受控锁持有／释放测试×2、确定性方向覆盖×2、不使用时间推定的工具×产品真实同锚点争用（原单测试重写，未删除真实竞争）；产品竞争会话 `expire_on_commit=False`；`tearDownClass`／`setUp` 线程退出确认后才允许 reset；新增三个离线检查类（12 项，不连接数据库） |
| `backend/tests/unit/test_ai1c_acceptance_fixture.py` | 资源清理：5 处 SQLite 内存引擎改用 `self.addCleanup(engine.dispose)`；注册显式 sqlite3 datetime/date 适配器消除 Python 3.12+ 默认适配器 DeprecationWarning。测试逻辑与计数未变（38 项） |
| `docs/bootstrap/ai-slice1c-fixture-repair2-result-2026-10-07.md` | 本报告 |

未改动：`backend/scripts/ai1c_acceptance_fixture.py`（R1 已收口）、`app/` 全部产品代码、API、产品会话配置、registry、models、迁移、前端、依赖、产品规则。`git status` 中协调者文档修改与既有未跟踪文档全部保留，无 reset／stash／覆盖。

## 2. S1：make_engine 导入与接入顺序

* 修复：`ai1c_guard.py` 补 `from sqlalchemy import create_engine, ...`（此前 `make_engine` 调用时 NameError）。
* 离线替身验证（`MakeEngineGuardOfflineTests`，2 项）：
  * 合成 13387 精确库 URL 下，`make_engine` 真实到达 engine 创建入口：替换 guard 模块 `create_engine` 符号为记录替身（不连库），恰好调用一次、端口／库名／驱动／`NullPool`／`REPEATABLE READ` 参数与白名单一致；
  * 非法目标（13386 远程验收库）：拒绝发生在 `create_engine` 之前，替身零调用。
* 缺陷敏感度验证（编码后独立执行，见 §8）：模拟 `create_engine` 符号缺失（删除模块全局）后，本离线检查立即报错——检查能捕获原缺陷。

## 3. S2：身份常量统一

* 修复：`seed_v1_world` 内 personal version／head 种子的三处 `FIXTURE_TEACHER_ID` 全部改为既有常量 `TEACHER_ACCOUNT`（`tow_ai1c`，与 accounts 原始种子一致）。
* 离线验证（`SeedAndWorldStateOfflineTests` 用真实 SQLAlchemy Session 执行真实 `seed_v1_world` → `world_state`）：种子沿真实函数路径执行成功；个人版本 map 为完整六字段（键集 = `V1_FIELDS`）、身份为 `TEACHER_ACCOUNT`；head 五个保护列 `(1,'current',None,1,None)` 与种子一致；管理员账号＋有效会话进入快照面。
* 缺陷敏感度验证：模拟 `TEACHER_ACCOUNT` 缺失后，本离线检查在 `seed_v1_world` 内报 `NameError`——检查按真实函数路径验证，不以 import 成功替代。

## 4. S3：SchoolSettings 提取形状

* 修复：`world_state` 的查询单行改为 `session.scalars(select(SchoolSettings)).one_or_none()`，返回 ORM 实体本身；规范化字段快照（school_name／version／schedule_version／plans_started_at）与无行分支（`school=None`）保留。
* 离线覆盖（真实 SQLAlchemy Session，非字符串比对）：
  * 实拍结果形状：`scalars(...).one_or_none()` 返回 `SchoolSettings` 实体且 `school_name` 可读；同一 select 的旧行为 `execute(...).one_or_none()` 返回包装 Row，读 `.school_name` 直接 `AttributeError`（对照组固定在测试内，防止回归）；
  * 无行分支：清空 school_settings 后快照仍完整产出（`school=None`，其余键不变式面完好），两种提取均得 `None`；
  * 规范化不变式证据保留：同一世界两次快照逐键一致、`changed_keys` 空集、含合成业务记录与管理员会话的完整快照面。

## 5. S4：同 expected 双发布者断言语义

* 修复（`test_concurrent_publishers_same_expected_at_most_one_success`）：结果按状态分组——恰好 1 成功＋1 拒绝；**错误码断言只作用于拒绝方**（确定 `ERR_TRANSITION_REFUSED`：败者被锚点锁序列化到胜者提交之后，锁内锁定读必然见到契约 v2，(v2→v2) 顺序判定即拒绝）；成功方结果另行单独校验（契约 [1,2]、默认 [1,2]、快照变化键恰为 `{contracts_daily, defaults_daily}`）。
* 离线回归（`RaceAssertionSemanticsOfflineTests`）：用合成合法两结果复现旧行为判定必然失败（收集包含成功方 `None` 的错误码集合不属于允许集合），并由断言纯函数的集成语义固化——不再以"先通过"掩盖合法结果。
* 真实竞争保留（屏障同时放行，未删除；无时间推定断言）。

## 6. S5：保护与审计断言分离

* 修复：guard 新增纯函数；集成断言拆分为按动作独立的类别：
  * 工具发布成功（含拒绝路径）：`assert_protected_state_untouched`＋`assert_audits_unchanged`——审计必须零增量（工具发布不写审计）；
  * 真实管理员发布成功：`assert_protected_state_untouched`＋`assert_product_audit_append_legal`——审计恰好合法追加：旧行一字不改、无删除、每键恰新增 1 行，且新行形状为 operation（operator=管理员 account、`prompt_default_update`、school/singleton、target_version_after=NULL）＋change record（`default_update`、任务／默认修订／契约目标、`changed_fields` 与 patch 一致、与新增 operation 关联）。
  * 原 `_assert_personal_untouched`（把审计变化也判非法）全部调用点替换完毕；`test_publish_v2_success_is_atomic`、高修订编号、两份写失败、后置失败、拒绝矩阵、工具×产品各方向测试均已按上述语义重建。
* 离线回归（7 项合成语义）：两种合法胜负（工具胜出＝审计不变；产品胜出＝审计合法追加）均通过；非法额外写入全部被拒绝——工具胜出却写审计、工具胜出却改写个人保护列、产品胜出缺审计、产品胜出删改旧行、新行动作不符、记录链接断开、changed_fields 与 patch 不符。

## 7. S6：锁竞争证据方式重建

旧证据（屏障放行间隔 <5s、输家完成时刻 ≥ 胜家完成时刻）全部移除，不再参与任何断言。替代结构：

1. **受控锁持有／释放**（`test_anchor_lock_blocks_tool_publish_until_holder_releases`、`test_anchor_lock_blocks_product_update_default_until_released`）：控制连接以发布路径完全相同的真实 `SELECT … FOR UPDATE` 持有 v1 锚点排他行锁（不伪造、不改产品实现）；
   * 阶段事件：竞争线程记录 `attempting`（到达发布尝试）→ `exited`，断言线程确实到达尝试；
   * 持有窗口内不能进入受保护临界区：两竞争方（工具 run_publish／产品 update_default）分别以最短 `SET SESSION innodb_lock_wait_timeout = 2` 被 MySQL 锁管理器**自身**确定拒绝（工具→固定去敏码 `AI1C_DB_OPERATIONAL`；产品→ MySQL 1205 锁等待超时错误实拍），持有期间完整快照与 `before` 相等（零增量，包含审计零增量）；
   * 释放后同一 expected 立即成功（工具→v2/r2；产品→r2＋合法审计追加），证明拒绝只依赖锚点锁的持有；
   * 全部等待有限：锁等待超时 2s、`join(timeout=60)`＋确认退出断言；测试内引擎均 dispose，控制连接 rollback（best-effort）后 close＋dispose。
2. **确定性方向覆盖**（`test_tool_wins_…`／`test_product_wins_…`）：工具胜出→产品以旧 expected 在真实锚点锁内锁定读 r2 读到确定失配 `VersionConflict` 且零增量；产品胜出（先种 r42 基线，管理员发布推进 r43，非 1→2→3）→工具以旧 expected=42 在该锁内锁定读 r43 读到确定失配 `ERR_EXPECTED_MISMATCH` 且零增量。两方向分别核对提交结果／拒绝码、MAX+1、以及第 6 条的动作化审计断言。
3. **不使用时间推定的真实同锚点争用**（`test_tool_and_product_race_same_anchor_at_most_one_wins`，替代原单测试，保留真实竞争）：双方以合法身份（种子管理员＋有效会话）、合法版本基线、屏障同时放行，真实争用同一锚点排他行锁；胜者由锁顺序自然决定；按实际落点断言：恰好一胜一败、败者错误只来自拒绝方（产品败→`VersionConflict`／工具败→`ERR_EXPECTED_MISMATCH`）、契约/默认落点、MAX+1（基线+1）、审计按动作、保护状态未变。任何间隔或完成时刻都不进入断言。
4. **产品会话口径**：所有产品竞争／发布使用 `Session(..., expire_on_commit=False)`，与真实 API（`app/database.py` 两个 SessionLocal 分支）一致，消除"错误混杂"来源。
5. **线程生命周期与清理**：所有线程登记到类容器，测试内 `join(timeout=60)`＋`assertFalse(is_alive())`；`tearDownClass` 先有限 join（30s），只有全部退出才 `reset_prompt_tables`＋`seed_v1_world` 后 dispose；有线程未退出则**跳过 reset**并提示，绝不在活跃线程运行时删除其数据；`setUp` 进入前亦确认上一测试线程全部退出。

## 8. 新增离线检查与缺陷敏感度（本轮独立验证记录）

新增 12 项离线检查（不属于 skip；不连接任何数据库）：

| 类 | 项 | 覆盖 |
| --- | --- | --- |
| `MakeEngineGuardOfflineTests` | 2 | S1: 合法目标到达 engine 创建入口；非法目标先拒绝（替身零调用） |
| `SeedAndWorldStateOfflineTests` | 3 | S2: 真实种子路径执行；S3: Row/实体形状实拍（含旧行为对照组）、无行分支、规范化不变式 |
| `RaceAssertionSemanticsOfflineTests` | 7 | S4/S5: 两种合法胜负通过；七种非法额外写入/审计形状不被放行 |

缺陷敏感度验证（编码后独立脚本执行，不进入仓库）：

* 模拟 S1（删除 guard 模块 `create_engine` 全局）→ 2 项 MakeEngine 检查立即 error；
* 模拟 S2（删除 `TEACHER_ACCOUNT` 全局）→ 3 项 Seed/World 检查在 `seed_v1_world` 内 NameError；
* S3/对照：结果形状差异在测试内以真实 SQLAlchemy 结果固定；
* 模拟 S4 旧逻辑（收集含成功方 None 的错误码集合）→ 对合法两结果判 False；
* 模拟 S5 旧断言（审计必须不变）→ 对合法产品胜出判 False，新断言纯函数通过。

边界声明：离线检查基于**SQLite 内存离线单元证据**（真实 SQLAlchemy Session、真实种子／快照／断言函数），不泛称 oracle，不宣称 MySQL 方言、锁或事务验证，不替代真库锁／回滚验证。未写任何源代码字符串比对检查；未通过删除保护或宽泛忽略异常让测试通过。

## 9. 资源清理与报告口径修正

* 清理：离线 SQLite 内存 engine 全部在 `addCleanup` 中 dispose（unit 文件 5 处＋integration 离线引擎）；`PYTHONWARNINGS=always` 全量运行无任何警告输出；以 `-W error::ResourceWarning` 运行两个模块（64 项）仍全部 OK——未关闭连接 ResourceWarning 消除。
* 同时注册显式 sqlite3 显式适配器消除 Python 3.12+ 默认 datetime/date 适配器 DeprecationWarning（语义与默认一致）。
* 报告口径：本报告与测试代码中，内存引擎一律表述为"SQLite 内存离线单元证据"，不泛称 oracle，不宣称 MySQL 验证。
* **原补修报告 §9 修正**（原报告历史保留）：`backend/app/database.py:15–51` 已核实——真实 API 的 `get_sessionlocal()` 两个分支（配置项存在与否）均为 `sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False)`。因此"实际 API 必然在 commit 后触发过期属性刷新"的前提不成立；不据此判定线上缺陷，也不新增产品编码任务。可保留的条件性观察仅剩"函数若被其他 expire_on_commit=True 调用者使用可能触发 commit 后刷新"，且已注明实际 API 会话配置。方案 A 不受影响。

## 10. 实际执行的命令与结果（本轮）

环境（所有后端命令统一前缀）：
`env -u DATABASE_URL -u AI_MASTER_KEY -u AI_MASTER_KEY_ID -u AI1C_TEST_ALLOW_PREPARE -u AI1C_TEST_DATABASE_URL -u AI1C_FIXTURE_DATABASE_URL -u AI1C_FIXTURE_ALLOW_PUBLISH APP_DISABLE_DOTENV=1 PYTHONDONTWRITEBYTECODE=1`，均使用现有 `backend/.venv/bin/python`，未安装任何依赖。

| 命令（均在 backend/ 下） | 结果 |
| --- | --- |
| `.venv/bin/python -m unittest discover -s tests/unit -t . -q`（+ PYTHONWARNINGS=always） | **Ran 686 tests, OK**（unit 测试代码零改动计数变化；测试逻辑与计数未变） |
| `.venv/bin/python -m unittest tests.unit.test_ai1c_acceptance_fixture -q` | **Ran 38 tests, OK**（仅资源清理改动，计数不变） |
| `.venv/bin/python -m unittest tests.integration.test_ai1c_acceptance_fixture -v` | **Ran 26 tests, OK (skipped=14)**：12 项离线检查全部实跑通过；14 项真库用例因 guard 未启用统一 skip（§7 条目逐一列出） |
| `.venv/bin/python -m unittest discover -s tests/integration -t .` | **Ran 288 tests, OK (skipped=276)**；0 failure／0 error（新增 12 项离线实跑；真库套件继续全口径 skip，不算真库通过） |
| `-W error::ResourceWarning` 运行 unit＋integration 两模块 | **Ran 64 tests, OK (skipped=14)**——无未关闭连接 ResourceWarning |
| `PYTHONWARNINGS=always` 全量 unit／integration 运行 | 输出中零警告（ResourceWarning 与 sqlite3 DeprecationWarning 均消除） |
| 缺陷敏感度脚本（/tmp 独立执行，不进仓库） | §8 五项全部证实"检查能捕获原缺陷形态" |
| CLI 冒烟（工具未改动）：无 DSN inspect／非法目标 inspect | 均 `exit 2`＋固定 `AI1C_TARGET_REFUSED` 去敏短句，无连接、无输入回显、无 traceback（与上轮记录一致） |
| `git diff --check`（仓库根） | 通过（无输出）；已修改文件仅上述测试/guard 与本报告 |

敏感输出检查：全部本轮输出无 DSN、无密钥材料、无原始异常细节或 traceback；合成标记不出现在固定输出断言中。

## 11. 真库执行：仍受阻（本轮未执行）

* 集成真库用例全量 skip 的原因不变：`AI1C_TEST_ALLOW_PREPARE=yes` 与专用 `AI1C_TEST_DATABASE_URL` 未设置，一次性 MySQL 8.4／127.0.0.1:13387／精确 `kindergarten_test_ai1c_fixture` 资源未授权、未具备。按提示词未创建库／容器、未安装／拉镜像、未借其他套件库、未用 SQLite 替代真库。
* 资源具备后的执行命令与门槛：
  `cd backend && .venv/bin/python -m unittest tests.integration.test_ai1c_acceptance_fixture -v`（环境变量同 §10 前缀），要求 **0 failure／0 error／0 skip** 后才形成远程准备清单；满足前不声称远程可用。
* 离线检查不能替代的真库内容：真实锁竞争（受控持有 1205 实拍、双发布者与工具×产品争用落点）、MySQL JSON 解码、超长 ID DataError 转换与整体回滚、高修订 MAX+1 编号、CLI 子进程端到端、剥离 / 重建顺序（reset／seed 与 alembic 头）。

## 12. 停止点清单（按要求单列）

* S1–S6 集中补修编码＋离线验证：完成（§2–§10；真实竞争未删除、保护断言保留、语义不放宽）。
* 真库执行（13387 集成套件实测）：**受阻**，等待已获授权的一次性 MySQL 8.4 资源与专用 DSN；本轮未连接任何数据库服务器。
* 远程验收实例、Windows 验收、commit／push：未进入本轮范围／未授权；未执行。
* 本轮交付到此为止，等待协调者只读复审；不自行进入远程发布或 Windows 验收。方案 A 无须再确认，无产品决定待补充。
