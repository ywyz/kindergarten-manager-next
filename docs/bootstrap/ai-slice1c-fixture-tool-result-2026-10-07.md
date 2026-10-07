# AI 1C 夹具工具交付报告（2026-10-07）

状态：编码与离线验证完成，交付在"工具可复审"停止点；未部署、未连接远程验收服务器、未发布任何真实契约，未 commit／push。

依据：[编码提示词](ai-slice1c-fixture-opencode-prompt-2026-10-07.md)、[夹具方案](ai-slice1c-fixture-plan-2026-10-07.md)、[Windows 报告](ai-slice1c-desktop-validation-2026-10-05.md)。方案 A 口径不变；本工具不读取 AI_MASTER_KEY，不迁移、不建库、不 GRANT、不启动服务，也不提供 reset／drop／truncate 或任意 schema 编辑。

## 1. 实际修改文件（本轮新增，全部为新增文件，零产品代码改动）

| 文件 | 内容 |
| --- | --- |
| `backend/scripts/ai1c_acceptance_fixture.py` | 验收专用固定配方发布工具：仅 `inspect`／`publish-v2`／`publish-v3`；连接前目标保护；发布为单事务原子追加契约＋完整默认；去敏输出 |
| `backend/tests/unit/test_ai1c_acceptance_fixture.py` | 31 项离线单元测试（guard、配方、expected、开关、argparse、import／--help 无连接、输出去敏） |
| `backend/tests/integration/ai1c_guard.py` | 集成 guard：专用开关 `AI1C_TEST_ALLOW_PREPARE`＋`AI1C_TEST_DATABASE_URL` 精确限定 127.0.0.1:13387 `kindergarten_test_ai1c_fixture`；alembic 子进程只用校验后的 URL；v1 世界 seed／reset 仅作用于该一次性库 |
| `backend/tests/integration/test_ai1c_acceptance_fixture.py` | 9 组真库测试（原子成功、重复／旧 expected 零增量、后置校验回滚、第二份插入失败双回滚、registry 不被改、同 expected 并发至多一个成功、inspect 派生不变式、CLI 子进程端到端）；guard 关闭时整体 skip |

未改动：`app/` 全部产品代码、registry、models、migrations、routers、前端、依赖锁。`git status` 中协调者的文档修改与未跟踪文档全部保留，无 reset／stash／覆盖。

## 2. 固定配方与协议（实现摘要）

- 任务仅 `daily_lesson_split`；v1 必须实读匹配六字段 `theme、objectives、preparation、key_points、difficult_points、process`（顺序固定），否则拒绝（`AI1C_ANCHOR_V1_INVALID`）。
- v2：移除 `preparation`、其余同名保留、末尾新增 `acceptance_support`；v3：在 v2 基础上移除 `process`。只允许 v1→v2、v2→v3（`AI1C_TRANSITION_REFUSED`）。
- 每版默认 map 与字段集完全一致；文字为固定公开合成标记（`AI1C-FIXTURE-vN-字段`），每字段 ≤8000。`input_vars`／`output_schema` 从数据库上一契约行原样复制（deepcopy），不改代码 registry。
- 发布协议：v1 锚点 `FOR UPDATE` → 锁内 locking read 最新契约（`populate_existing`）→ 上一契约字段与该契约最新默认 map 完整性 → expected 契约／默认修订精确匹配 → 任务全历史默认 revision MAX+1（不按新契约重新编号）→ 同一事务原子追加一份契约行＋一份完整默认行（created_by NULL、UTC 时间）→ 事务内后置校验；任何失败回滚零增量；重复／旧 expected 全部拒绝，无 UPDATE 覆盖、upsert 或模糊幂等。
- 不写：personal head／versions、accounts、school_settings、其他任务、operation_records／prompt_change_records（不伪造 default_update 事件）。

## 3. 目标保护（连接前拒绝）

- DSN 只来自 `AI1C_FIXTURE_DATABASE_URL`；`--mode acceptance`（mysql+pymysql、127.0.0.1／localhost、13386、精确 `kg_next_ai1c_fixture`）与 `--mode integration`（同 driver、13387、精确 `kindergarten_test_ai1c_fixture`）以外的一切目标（尤其 `kg_next_i5_acceptance`、其他套件库、其他 host／port／driver、空目标、任何 URL 查询参数）在建 engine 前 `AI1C_TARGET_REFUSED`。
- 发布需显式 `AI1C_FIXTURE_ALLOW_PUBLISH=yes`，缺开关在建 engine／连接之前拒绝（`AI1C_PUBLISH_SWITCH_MISSING`）。integration 一次性库的破坏性准备／恢复用独立开关 `AI1C_TEST_ALLOW_PREPARE`＋`AI1C_TEST_DATABASE_URL`，不沿用任何其他切片开关。
- 模块 import 即设置 `APP_DISABLE_DOTENV=1` 并丢弃本进程继承的 `DATABASE_URL`／`AI_MASTER_KEY`／`AI_MASTER_KEY_ID`（不改父 shell）；import 与 `--help` 不连库、不加载私密配置（含单元测试验证）。
- 连接后只读核对：实际 `DATABASE()`、MySQL 8.4、InnoDB、唯一迁移头 `20261003_ai1a_config_prompts`、所需表、v1 锚点；不符即 `AI1C_DB_CHECK_FAILED`，目标保持不变。
- inspect 无需发布开关；输出去敏 target（mode／库名由固定白名单给出）、迁移头、契约演进字段名与最新默认版本号，不读取／输出配置密文、密码哈希、指导全文。

## 4. 实际执行的命令与结果

- `backend/.venv/bin/python -m unittest discover -s tests/unit -t .` → **Ran 679 tests, OK**（既有基线各测试均在；注意以本轮实际执行计数为准，非引用历史 648）。
- `backend/.venv/bin/python -m unittest discover -s tests/integration -t .` → **Ran 271 tests, OK (skipped=271)**：全部 skip，其中新增 9 项 AI1C 夹具真库测试因 guard 未启用而 skip。
- `backend/.venv/bin/python -m unittest tests.unit.test_ai1c_acceptance_fixture` 单独跑 = 31 项全过（guard 拒绝、配方、expected、开关、argparse、import／--help 无连接、import 环境清泄、去敏输出、transition_recipe_matches）。
- CLI 冒烟：`--help` exit 0；inspect 无 DSN → stderr `AI1C_TARGET_REFUSED: ...固定句...`，exit 2；带合成密码标记的非法 DSN → 输出不含该标记／目标库名／主机，无 traceback；publish 缺开关 → `AI1C_PUBLISH_SWITCH_MISSING`（engine 未创建，跟踪替换计 0）。
- `git diff --check` → 通过。

## 5. 真库执行：受阻（本轮未执行）

- 本地探测 `127.0.0.1:13386`／`13387`：**端口均未监听**（本轮 socket 探测 closed），无符合"既有可用一次性 MySQL 8.4、127.0.0.1:13387、精确 `kindergarten_test_ai1c_fixture`、已获资源授权"的现成实例。按提示词未安装、未拉镜像、未创建任何数据库。
- 集成测试中涉及的 MySQL 行为（v1 锚点 FOR UPDATE 顺序化、同任务默认发布争用、InnoDB 回滚语义等）依赖 MySQL 方言；另做了一个离线 SQLite 逻辑级冒烟（注册 utf8mb4_bin collation＋精简本工具触及表）：v2/v3 原子成功、重复与旧 expected 拒绝零增量、后置校验失败回滚、personal／审计／accounts 不变、默认 revision 按全历史 MAX+1 均通过——仅证明代码路径成立，不替代真库证据。
- 所需资源（一次即可解锁）：一次性 MySQL 8.4 实例监听 `127.0.0.1:13387`，其中已创建空库 `kindergarten_test_ai1c_fixture`（建库属资源授权操作，不在本工具或测试内），并给测试账号提供可读可写凭据。运行方式：
  - `AI1C_TEST_ALLOW_PREPARE=yes`
  - `AI1C_TEST_DATABASE_URL=mysql+pymysql://<用户>:<密码>@127.0.0.1:13387/kindergarten_test_ai1c_fixture`
  - `cd backend && .venv/bin/python -m unittest tests.integration.test_ai1c_acceptance_fixture -v`
  - guard 在任何测试连接与 alembic 之前生效；所有失败读数只允许精确该库；其他环境变量照常不被读取。
- 集成测试覆盖清单（待真库跑通后即为 C5 发布依据）：v2/v3 原子成功并重建 v1 基线；个人文字／head／accounts.version／其他任务／prompt_change_records 不变；重复调用与旧 expected 全部零增量；后置校验失败与"第二份插入失败"均整体回滚；两个发布者持相同 expected 在同任务锁锚点顺序化、至多一个成功；发布前后 `ai_prompt_registry` contract_snapshot 与 guidance_defaults_snapshot 与 `TASK_REGISTRY` 未被修改（不以改 registry 冒充发布）。测试自身不导入运维工具的破坏性函数；seed／reset 仅作用于该一次性精确库。

## 6. 远程实例与剩余验收（未准备／未执行）

- 远程验收（`kg_next_ai1c_fixture`）实例、独立服务、备份基线、密钥状态切换均未准备，本轮不涉及。
- 真实 C5 基础适配、V1/U3-1…4 四组、适配参考区离开确认、C7 缺／错主密钥降级仍待补验；离线测试与单元证据不替代。
- 方案 A 的同契约旧默认可接受行为按已确认口径处理；本轮未发现新的产品代码缺陷需登记（现有"旧 accept target"行为差异已按 2026-10-05 报告与方案 A 归档，不再作为修复阻塞）。

## 7. 使用方法（不含凭证）

每次发布前，托管者在本机（或验收实例侧）执行：

1. `APP_DISABLE_DOTENV=1`
2. `AI1C_FIXTURE_DATABASE_URL` =（验收实例的 13386 `kg_next_ai1c_fixture` 专用应用 DSN，私密渠道提供；不要写入命令行历史或仓库）
3. 只读核对并取 expected：
   `backend/.venv/bin/python scripts/ai1c_acceptance_fixture.py --mode acceptance inspect`
   → 输出包含 `latest_contract_version` 与 `latest_default_revision`，这就是下一次 publish 的两个 expected 值。
4. Windows 阶段准备完成后，托管者单次执行：
   `AI1C_FIXTURE_ALLOW_PUBLISH=yes backend/.venv/bin/python scripts/ai1c_acceptance_fixture.py --mode acceptance publish-v2 --expected-contract-version <现场值> --expected-default-revision <现场值>`
   （同一命令模板用于 `publish-v3`，expected 必须来自当时现场 inspect，不能沿用上一次发布的结果值。）
5. 成功输出一行 JSON（task_type、old/new contract、old/new default revision、字段名、status），可直接重定向为私密 manifest；任何失败输出仅固定错误码＋固定短句，非 0 退出。工具不自动串联 publish-v2→publish-v3；每个阶段独立、单次、以现场 inspect 的 expected 为准。

## 8. 交付停止点清单（按要求单列）

- 编码／离线验证：完成（见 §4；单元 679 全过含新增；CLI 冒烟通过；`git diff --check` 通过）。
- 真库执行（13387 集成套件实测）：受阻，缺一次性 MySQL 8.4 实例与 `kindergarten_test_ai1c_fixture` 建库＋可写测试账号（资源授权另记）。
- 远程验收实例（13386 临时库／独立部署）：未准备，本轮未触碰远程。
- 真实 C5／V1(四组)／U3 离开确认／C7 缺错主密钥：仍待补验，依赖上一项与托管者远程执行清单。
