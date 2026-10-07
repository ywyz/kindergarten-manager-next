# AI 1C 夹具锁辅助函数最小补修结果报告（2026-10-07）

状态：**T1／T2 最小补修与新增离线入口验证完成，停止于"交协调者复审"停止点**。工具 R1 与集成 S1–S5 已由复审确认成立，本轮未重做、未改动；产品代码、发布工具、registry、迁移、前端、依赖均未改动；未创建数据库／容器，未安装／拉镜像，未连接远程、未部署、未操作主密钥、未调用供应商、未 commit／push。真库资源仍未授权／未具备，14 项真库用例如实登记 skip；SQLite／替身不替代真库。

依据：[第二轮补修复审](ai-slice1c-fixture-repair2-review-2026-10-07.md)、[第三轮提示词](ai-slice1c-fixture-repair3-opencode-prompt-2026-10-07.md)、[第二轮交付报告](ai-slice1c-fixture-repair2-result-2026-10-07.md)（历史保留）。协调者与用户已有文档改动全部保留，无 reset／stash／覆盖。

## 1. 实际修改文件（本轮范围）

| 文件 | 内容 |
| --- | --- |
| `backend/tests/integration/test_ai1c_acceptance_fixture.py` | T1：`_hold_anchor_lock` 改在连接上执行真实 `SELECT … FOR UPDATE`，`RootTransaction` 只负责 rollback，失败路径函数内部清理已取得资源后原样抛错；T2：`_release_anchor_lock` 缩减为纯资源释放（rollback／close／dispose），发布断言整体恢复到 `test_publish_v2_success_is_atomic`（以该测试真实 `after` 快照核对）；新增 2 个离线检查类（10 项） |
| `docs/bootstrap/ai-slice1c-fixture-repair3-result-2026-10-07.md` | 本报告 |

## 2. T1：锁持有函数的连接／事务职责

* 缺陷（复审已核实）：原实现向 `control_connection.begin()` 返回的 `RootTransaction` 执行 SQL——SQLAlchemy 2 的 `RootTransaction` 只负责事务生命周期、不提供 `execute`（离线核验真实类型 `hasattr(tx, "execute") == False`），调用即 AttributeError；异常发生在返回前，调用方尚未拿到资源三元组，函数也没有自身清理。
* 修复：
  * 锁查询改为 `control_connection.execute(select(...).with_for_update())`——仍是发布路径完全相同的真实 MySQL v1 锚点排他行锁，**不以事件或替身代替 MySQL 锁**；事务对象只用于后续 rollback。
  * 取得连接／begin／执行锁查询任一步失败时，函数按已取得资源逆序清理（tx.rollback → connection.close → engine.dispose，均 best-effort），再原样抛出原始错误，不转换、不吞掉。
  * 成功路径返回完整三元组 `(engine, connection, transaction)`，调用方拿到资源后由 `_release_anchor_lock` 释放。

## 3. T2：释放函数与发布断言分离

* 缺陷（复审已核实）：`_release_anchor_lock` 在 rollback／close／dispose 之后包含一大段 v2／r2／map／head／个人文字断言，且引用在该函数中未定义的 `after`——两个受控锁测试都在"保持 v1、竞争方超时拒绝、尚未再次发布"时调用它，会把合法 v1 状态错判、甚至 NameError，还会在 finally 里掩盖真实原始错误。
* 修复：
  * `_release_anchor_lock` 现在只做 `transaction.rollback()`（best-effort）→ `connection.close()` → `engine.dispose()`；不读业务数据、不假定发布成功、不引用任何快照、不执行发布断言。
  * 原 post-publish 断言整体恢复到 `test_publish_v2_success_is_atomic`，以该测试真实的 `after = world_state(self.engine)` 快照核对，必要断言逐项保留：契约落点 [1,2] 且新契约 `guidance_fields == V2_FIELDS`、`created_by` 为 NULL；默认落点 [1,2]、链到契约 v2、map 键/值与 `recipe_guidance_map(2)` 完整一致（不依赖键序）；`input_vars`／`output_schema` 与上一契约快照原样复制；head 五个保护列与种子及 `before` 快照一致；个人完整文字（六字段合成 map）未被触碰；`changed_keys == {contracts_daily, defaults_daily}`；`_tool_publish_assertions`（S5 保护／审计分离断言）。未通过删除断言绕过问题。

## 4. 两个受控锁测试的调用顺序核对（T1/T2 修复后复核）

`test_anchor_lock_blocks_tool_publish_until_holder_releases` 与 `test_anchor_lock_blocks_product_update_default_until_released` 现均为：

1. `_hold_anchor_lock()`（真实持有 v1 锚点）→
2. 竞争线程在锁等待窗口以最短 `innodb_lock_wait_timeout=2` 被 MySQL 锁管理器自身确定拒绝；持有窗口内断言完整快照零增量（含审计零增量）→
3. `finally` 中 `_release_anchor_lock(...)` ——**纯资源释放，无任何断言**，首次异常（含线程退出确认、拒绝码/1205、零增量断言）不会被 finally 里的无关断言掩盖 →
4. 释放后同一 expected 再次发布成功（工具→v2/r2；产品→r2＋合法审计追加）→
5. 全部状态断言留在测试体内执行。

有限等待与线程退出保护沿用：锁等待 2s、屏障/事件有限超时、`join(timeout=60)`＋退出确认断言、线程登记到类容器、`tearDownClass`／`setUp` 在线程全部退出后才允许 reset／dispose（有线程未退出则跳过 reset，不在活跃线程运行时删除数据）。

## 5. 新增离线检查（10 项；不连接数据库）

替身设计（与真实对象职责对齐，不掩盖缺陷形态）：

* `_FakeConnection`：真实 Connection 职责切面——`begin`／`execute`／`close`；
* `_FakeRootTransaction`：只提供 `rollback`（**故意不提供 execute**——真实 `RootTransaction` 没有 execute；若向事务对象执行 SQL 的缺陷形态回归，检查立即 AttributeError）；
* `_FakeEngine`：`connect`／`dispose` 记录。

| 类 | 项 | 覆盖 |
| --- | --- | --- |
| `LockHelperOfflineTests` | 5 | T1 成功路径返回三元组、锁查询在连接上执行且编译为 `prompt_contract_versions … FOR UPDATE`（真实对象编译产物，非源字符串比对）、成功路径不 dispose／不 rollback；begin 失败：原错重抛＋引擎 dispose 收尾；锁查询失败：rollback→close→dispose 清理次序；T2 释放函数纯清理序列恰为 rollback→close→dispose（替身没有业务读写通道，任何额外访问都会失败）；rollback 失败路径仍 close→dispose 且不抛错 |
| `RestoredPublishV2AssertionsOfflineTests` | 5 | 用合成合法发布结果直接执行**实际** `test_publish_v2_success_is_atomic`（模块级 `world_state`／`_daily_rows` 以合成输入替换，其余断言全真）：合法结果通过；不完整 map、改变个人文字、`created_by` 非 NULL、被改动 `input_vars` 各变体均被实际断言拒绝——断言恢复位置正确 |

边界声明：以上是辅助函数入口与断言语义的离线证据；SQLite／替身不替代真库，不制造"离线全过＝MySQL 通过"的口径。真实锁等待、真实 1205 超时、真实竞争落点仍仅由一次性 MySQL 验证。

## 6. 缺陷敏感度复现（编码后独立脚本执行，不进仓库）

* 复核真实 SQLAlchemy `RootTransaction`：`hasattr(tx, "execute")` → `False`。
* T1 缺陷形态（向事务对象执行 SQL）在职责切面替身上重现 AttributeError——现有 `LockHelperOfflineTests` 可捕获。
* T2 缺陷形态（释放函数含发布断言）：对合法 v1 输入（受控锁测试的未发布状态）断言错判 AssertionError；即便输入 v2 数据也在 `after` 引用处 NameError——与复审离线复现一致，修复后两形态均不存在（释放函数调用序列恰为三项清理）。

## 7. 实际执行的命令与结果（本轮）

环境（所有后端命令统一前缀）：
`env -u DATABASE_URL -u AI_MASTER_KEY -u AI_MASTER_KEY_ID -u AI1C_TEST_ALLOW_PREPARE -u AI1C_TEST_DATABASE_URL -u AI1C_FIXTURE_DATABASE_URL -u AI1C_FIXTURE_ALLOW_PUBLISH APP_DISABLE_DOTENV=1 PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS=always`，均使用现有 `backend/.venv/bin/python`，未安装任何依赖。

| 命令（均在 backend/ 下） | 结果 |
| --- | --- |
| `.venv/bin/python -m unittest discover -s tests/unit -t . -q` | **Ran 686 tests, OK**（unit 文件本轮未改动，计数不变） |
| `.venv/bin/python -m unittest tests.integration.test_ai1c_acceptance_fixture -v` | **Ran 36 tests, OK (skipped=14)**：22 项离线检查全部实跑通过（12 项上轮＋10 项本轮新增）；14 项真库用例全部 skip（guard 未启用） |
| `.venv/bin/python -m unittest discover -s tests/integration -t .` | **Ran 298 tests, OK (skipped=276)**；0 failure／0 error；真库套件仍全口径 skip，不算真库通过 |
| `-W error::ResourceWarning` 运行 unit＋integration 两模块 | **Ran 74 tests, OK (skipped=14)**——无未关闭连接告警 |
| `PYTHONWARNINGS=always` 各运行 | 输出零警告 |
| 缺陷敏感度脚本（/tmp 独立执行） | §6 全部复现并确认可捕获 |
| `git diff --check`（仓库根） | 通过（无输出） |

## 8. 真库执行：仍受阻（本轮未执行）

* 14 项 MySQL 集成用例（v2/v3 原子成功、拒绝矩阵零增量、两份写失败回滚、高修订 MAX+1、双发布者同 expected 竞争、受控锁持有／释放×2、确定性方向×2、工具×产品真实争用、CLI 子进程端到端、registry 不变式、inspect 不变式）继续整体 skip：`AI1C_TEST_ALLOW_PREPARE=yes` 与专用 `AI1C_TEST_DATABASE_URL` 未设置，一次性 MySQL 8.4／127.0.0.1:13387／精确 `kindergarten_test_ai1c_fixture` 资源未授权、未具备。未创建库／容器、未安装／拉镜像、未借其他套件库、未用 SQLite 替代真库。
* 资源具备后必须实际执行：`cd backend && .venv/bin/python -m unittest tests.integration.test_ai1c_acceptance_fixture -v`（环境变量同 §7 前缀），达到 **0 failure／0 error／0 skip** 才进入下一步；未满足前不宣称远程可用。届时重点核对：受控锁测试的 1205 实拍与清线程退出、受控持有窗口零增量、释放后重发布成功、两个确定性方向落点、真实争用落点与审计语义。

## 9. 停止点清单（按要求单列）

* T1／T2 补修＋锁辅助离线入口验证＋恢复断言离线驱动：完成（§2–§7）。
* 真库执行：**受阻**，等待已获授权的一次性 MySQL 8.4 资源与专用 DSN；本轮未连接任何数据库服务器。
* 远程验收实例、Windows 验收、commit／push：未进入本轮范围／未授权；未执行。方案 A 保持不变，无产品决定待补充。
* 本轮交付到此为止，等待协调者只读复审；不自动进入远程发布。
