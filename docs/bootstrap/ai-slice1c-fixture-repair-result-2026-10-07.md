# AI 1C 夹具工具补修结果报告（2026-10-07）

状态：**编码与离线验证完成，继续停在"补修交付、交协调者复审"停止点**；真库集成仍未执行（资源未具备，全部如实登记 skip），未连接远程、未部署、未操作主密钥、未调用供应商、未 commit／push。原[交付报告](ai-slice1c-fixture-tool-result-2026-10-07.md)历史保留，不追溯改写；本报告只记录补修增量。

依据：[复审报告](ai-slice1c-fixture-tool-review-2026-10-07.md)、[补修提示词](ai-slice1c-fixture-repair-opencode-prompt-2026-10-07.md)、[原编码提示词](ai-slice1c-fixture-opencode-prompt-2026-10-07.md)、[夹具方案](ai-slice1c-fixture-plan-2026-10-07.md)。方案 A 口径不变，未新增"默认目标必须最新"检查。

## 1. 实际修改文件（本轮范围）

| 文件 | 内容 |
| --- | --- |
| `backend/scripts/ai1c_acceptance_fixture.py` | R1 提交边界重构（提交前捕获标量、commit 后零 ORM 读取、`AI1C_COMMIT_UNCERTAIN`）；提交前写失败统一转为 `AI1C_DB_OPERATIONAL`；`MESSAGE_UNEXPECTED` 不再无条件声称回滚；inspect 改为最少列查询 |
| `backend/tests/unit/test_ai1c_acceptance_fixture.py` | 新增 R1 离线回归（38 项，+7）：真实 Session（expire_on_commit=True）＋内存 oracle 的零提交后语句断言、高修订 MAX+1 断言、对照组（提交后读属性确实触发 1 次刷新 SELECT）、COMMIT 不确定／提交前写失败契约、CLI 错误边界映射 |
| `backend/tests/integration/ai1c_guard.py` | seed 上下文关闭（R2 生命周期）；R2f 完整六字段合成个人 map；新增管理员账号＋有效会话（供产品默认发布竞争）、school_settings 单行、合成 operation_record＋prompt_change_record；新增 `world_state` 规范化快照与 `changed_keys`；`venv_python()` |
| `backend/tests/integration/test_ai1c_acceptance_fixture.py` | R2a–e 修正；10 项测试重写/新增（含高修订编号、真实产品竞争、线程生命周期、全量快照不变式、CLI 子进程 cwd/解释器/超时） |
| `docs/bootstrap/ai-slice1c-fixture-repair-result-2026-10-07.md` | 本报告 |

未改动：`app/` 全部产品代码、registry、models、migrations、routers、前端、依赖锁、产品规则。`git status` 中协调者文档修改与未跟踪文档全部保留，无 reset／stash／覆盖。

## 2. R1：提交结果（必修改 1）

* `run_publish` 的结果 dict 现在在 **commit 前用纯标量构建**（`prev_version`、`old_default_revision`、`new_revision`、字段列表全部在锁内读取后立即捕获）；`db.commit()` 成功后不再读取任何 ORM 属性、不再执行任何数据库读写。expire_on_commit=True 下再无提交后隐式刷新点。
* 提交边界分为三段（各自固定错误码）：
  * **提交前**（校验、锁读、插入、后置验证）：`FixtureError` 原码回滚后重抛（零增量声称成立）；其他异常（含真实 SQL 写失败）回滚后统一转换为 `FixtureError(AI1C_DB_OPERATIONAL)`，`from None` 抑制原始异常链。
  * **`Session.commit()` 本身抛出的异常** → `AI1C_COMMIT_UNCERTAIN`：不声称回滚、不声称零增量、不自动重试（commit 恰好只尝试一次），只提示"先执行 inspect 只读核对当前契约与默认状态，再决定是否重新发布"。
  * **CLI 未预期路径**（`ERR_UNEXPECTED`）：固定短句改为"事务状态可能已回滚也可能不确定，请先以 inspect 只读核对"，不再无条件声称"事务已回滚"。
* 固定输出保持去敏：无 SQL 参数、无 DSN、无原始异常文本（`raise ... from None`）。

## 3. R2a–f 对应落实

| 子项 | 落实 |
| --- | --- |
| R2a | 拒绝矩阵改为真实旧 expected：重复 publish-v2 → `AI1C_TRANSITION_REFUSED`（(2→2) 顺序不允许）；`(3,1,2)` 旧契约 expected 与 `(3,2,1)` 旧默认 expected → `AI1C_EXPECTED_MISMATCH`；合法 v2→v3 只在成功场景断言；每个拒绝后用 `world_state` 全量快照断言零增量 |
| R2b | `BACKEND_ROOT` 在集成测试文件内定义；CLI 子进程以 `backend/.venv/bin/python`（guard 同款 `venv_python()` 回退 `sys.executable`）、`cwd=BACKEND_ROOT`、`timeout=120` 运行 |
| R2c | 快照全部改用 ORM 读出：`prompt_default_versions.guidance_map` / `input_vars` / `output_schema` 由 SQLAlchemy JSON 类型解码为 dict；map 断言比较键集合与值，不依赖对象键序；仅 `guidance_fields` 作为有序数组比较 |
| R2d | head 查询改为五个保护列（current／adaptation_state／required_contract_version／last_seen／last_rejected），断言 `SEEDED_HEAD=(1,'current',None,1,None)` 并与发布前 `world_state` 快照一致；个人版本行为完整六字段 map |
| R2e | 错误契约按真实转换实现：超长 ID 注入触发真实 SQL 写失败后，核心把提交前写失败 **实际**转换为 `AI1C_DB_OPERATIONAL`＋固定短句；测试断言码与消息精确相等（不再"只接受一个从未被转换的码"），并断言原始异常文本／SQL 参数不出现在 FixtureError 输出；核心与 CLI 各自边界分开测试（内存 oracle 注入 + CLI 映射） |
| R2f | v1 个人种子为完整六字段合成个人 map（`AI1C-FIXTURE-TEACHER-PERSONAL-v1-<字段>`×6），head joined legend 合法；不变式比较的是这份合法状态的"未被改变"，不再用不合法单字段 map 证明 |

无跳过、无删除必要测试、无改配方规避。

## 4. 生命周期与竞争（必修改 3）

* seed 里所有查询／写入均处于 `with engine.begin()` / `with engine.connect()` 上下文，显式关闭。
* 两处并发测试统一线程生命周期协议：屏障（15s 超时）、`join(timeout=60)` 后 `assertFalse(thread.is_alive())`（确认退出）、线程内 try/except 收集异常（仅记录异常类名，不落原始细节）、清理（`engine.dispose()`）在 finally 中随线程退出完成；tearDownClass 在所有线程结束后清理。
* 线程同时启动 ≠ 证明争用的问题用三层证据处理：
  1. 双方先各自执行普通读建立 REPEATABLE READ 快照，再在 `threading.Barrier(2)` 同时放行；
  2. 输家错误只能由"进入同一锚点 critical section 后读到赢家已提交状态"解释（工具输家 → `AI1C_EXPECTED_MISMATCH`；产品输家 → `VersionConflict`），并断言时间线 `loser.finished_at ≥ winner.finished_at`；
  3. 记录双方屏障放行时刻（`time.perf_counter`）并断言差值有限。
* 新增 `test_tool_publish_races_product_update_default_same_anchor`：工具 `run_publish(v2, expected=现场读取)` 与既有 `prompt_service.update_default`（合法 admin `AuthSnapshot`＋种子会话、`expected_default_revision=现场读取`）同任务同锚点真实并发；不修改产品服务；断言至多一方成功，且两种胜负下快照变化键集合逐一匹配（工具赢：契约＋默认；产品赢：默认＋operation_records＋prompt_change_records），任务全历史 MAX+1（新默认修订＝基线+1）。

## 5. 不变式与编号（必修改 4）

* `world_state` 规范化快照（JSON 解码、数组保序、map 无序比较）覆盖：个人完整文字、head 全部保护列、accounts（含 version）、sessions、school_settings、operation_records（含合成业务记录）、prompt_change_records、daily_lesson_split 契约与默认全文、其他任务契约与默认全文。
* 编号：`test_publish_v3_after_high_revision_continues_max_plus_1` 先种入 r42（合法完整 map、链接 v1 契约），再发布 v2→43、v3→44，证明从全历史 MAX+1 延续，而非 1→2→3。
* 真实写失败（零增量＋整体回滚）、后置失败（`AI1C_POST_VERIFY_FAILED` 零增量）、旧 expected 拒绝（零增量）三组断言保留。

## 6. inspect 与使用方法（必修改 5）

* inspect 改为最少列查询（契约号＋字段名、最新默认修订号＋契约号），不再加载 input_vars／output_schema／guidance_map；输出去敏且键保持不变（离线冒烟验证输出键一致、v2 发布后字段名与版本正确推进）。
* 使用方法（统一 cwd，避免相对路径混用）：

```bash
cd backend
.venv/bin/python scripts/ai1c_acceptance_fixture.py --help
.venv/bin/python scripts/ai1c_acceptance_fixture.py --mode acceptance inspect   # 先只读取 expected
.venv/bin/python scripts/ai1c_acceptance_fixture.py --mode acceptance publish-v2 \
  --expected-contract-version <现场 inspect 值> \
  --expected-default-revision <现场 inspect 值>
```

  每次发布前 expected 必须来自当次现场 inspect；工具不自动串联 publish-v2→v3。COMMIT 不确定时（`AI1C_COMMIT_UNCERTAIN`）必须先重新 inspect 核对，不得自动重试。

## 7. 实际执行的命令与结果（本轮）

环境：`env -u DATABASE_URL -u AI_MASTER_KEY -u AI_MASTER_KEY_ID -u AI1C_TEST_ALLOW_PREPARE -u AI1C_TEST_DATABASE_URL -u AI1C_FIXTURE_DATABASE_URL -u AI1C_FIXTURE_ALLOW_PUBLISH APP_DISABLE_DOTENV=1 PYTHONDONTWRITEBYTECODE=1`，均在 `backend/` 下用现有 `.venv/bin/python`。

| 命令 | 结果 |
| --- | --- |
| `.venv/bin/python -m unittest tests.unit.test_ai1c_acceptance_fixture -q` | **Ran 38 tests, OK** |
| `.venv/bin/python -m unittest discover -s tests/unit -t . -q` | **Ran 686 tests, OK**（16–18s；既有基线 679 ＋ 新增 7，无新旧计数混用） |
| `.venv/bin/python -m unittest discover -s tests/integration -t .`（同上环境） | **Ran 272 tests, OK (skipped=272)**；0 failure／0 error，全部因 guard 未启用而 skip，不算真库通过 |
| `.venv/bin/python -m unittest tests.integration.test_ai1c_acceptance_fixture -q` | **Ran 10 tests, OK (skipped=10)** |
| CLI 冒烟：`--help`、无 DSN inspect、非法 DSN inspect | `--help` exit 0；inspect/inspect 非法 DSN 均 `AI1C_TARGET_REFUSED` exit 2，输出不含输入 URL／密码标记，无 traceback |
| CLI 冒烟：commit 不确定（patch 核心入口抛 `AI1C_COMMIT_UNCERTAIN`） | exit 1，首行即固定码＋"COMMIT 结果不确定……请先执行 inspect 只读核对"，无原始异常、无 traceback |
| 内存 oracle 行为断言（编码期验证，已固化进单元测试） | v2 成功发布后提交阶段外 **0 条**语句；对照组（提交后读 ORM 属性）恰好触发 1 条刷新 SELECT；COMMIT 抛错 → `AI1C_COMMIT_UNCERTAIN` 且仅 1 次 commit 尝试；提交前写失败 → `AI1C_DB_OPERATIONAL` |
| `git diff --check`（仓库根） | 通过（无输出） |

新增单元计数细分：`CommitBoundaryRegressionTests` 5 项（零提交后语句、编号 MAX+1、COMMIT 不确定契约、提交前写失败契约、对照组刷新验证）＋ `CliErrorBoundaryTests` 2 项（不确定提交的 CLI 映射、未预期错误不泄漏原始细节）＝ 38 项。

敏感输出检查：全部本轮输出中未出现密码标记、DSN、原始异常 repr 或 traceback；单测用合成标记 `PW-AI1C-UNIT-SECRET-MARK` 在所有错误输出断言中保持缺席。

## 8. 真库执行：仍受阻（本轮未执行）

* 集成套件全量 skip 的原因不变：未设置 `AI1C_TEST_ALLOW_PREPARE=yes` 与专用 `AI1C_TEST_DATABASE_URL`，且 127.0.0.1:13387 一次性 MySQL 8.4／`kindergarten_test_ai1c_fixture` 资源未授权、未具备。按提示词未安装、未拉镜像、未创建库、未借其他套件库、未用 SQLite 替代真库（内存 oracle 仅作为驱动无关的离线单元证据，已在测试内声明边界）。
* **真库仍需独立验证的内容**（离线不替代）：v1 锚点 FOR UPDATE 顺序化与 MySQL JSON 解码；超长 ID 真实 DataError 的转换与整体回滚；双发布者与工具×产品竞争的锁争用；高修订 MAX+1 编号；CLI 子进程端到端。上述均为本轮改动过的测试方法，与旧版本测试在真实 MySQL 上的行为差异只能由真库运行确认。
* 资源要求不变：一次性 MySQL 8.4／InnoDB、127.0.0.1:13387、精确 `kindergarten_test_ai1c_fixture`、独立测试账号及迁移准备权限；运行命令：
  `cd backend && .venv/bin/python -m unittest tests.integration.test_ai1c_acceptance_fixture -v`（环境变量同 §7 前缀）。
* 未 0 failure／0 error／0 skip 之前不声称远程可用；协调者随后按复审报告准备具体资源清单。

## 9. 范围外观察（只报告，未改动）

* 产品 `prompt_service.update_default`（backend/app/services/prompt_service.py:1253–1259）在 `db.commit()` 成功后构建返回 dict 时读取 `latest_contract`／`latest_default` 的 ORM 属性，与 R1 同一模式（commit 后隐式刷新 SELECT；连接级故障会在提交成功后抛错）。属产品代码，本轮范围明确禁止修改，只登记观察，不影响本工具门槛，等待后续切片授权处理。

## 10. 停止点清单（按要求单列）

* 补修编码＋离线验证：完成（§7；单元 686 OK 含新增；integration 全 skip；CLI 冒烟；`git diff --check` 通过）。
* 真库执行（13387 集成套件实测）：**受阻**，等待已获授权的一次性 MySQL 8.4 资源与专用 DSN；本轮未连接任何数据库服务器。
* 远程验收实例（13386 临时库／独立部署）：未准备，本轮未触碰远程；真实 C5／V1(四组)／U3 离开确认／C7 缺错主密钥仍待补验。
* 本轮交付到此为止，等待协调者只读复审；不自行进入远程发布或 Windows 验收。
