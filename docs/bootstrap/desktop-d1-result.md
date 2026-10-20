# D1 本地手工日计划实施结果

实施记录更新：2026-10-17；独立复审注记更新：2026-10-17。实施者：OpenCode；复审注记：Codex。依据[D1 实施规格](../specs/desktop-manual-daily-plan.md)、[Codex D1 技术核查](desktop-d1-technical-review.md)；D0 依据见[D0 第三轮复审 §7](desktop-d0-review.md)。

**当前结论（2026-10-17）：R18已关闭，T6-A／T6-B及T7本轮人工验证通过；当前Windows 11＋Word下本轮教师体验收口。** T6-B配置v4、新旧计划表头、两份单日文件及正常退出已独立核对，见[§20.8](#208-t6-b核对与本轮教师体验收口2026-10-17)。用户明确微软拼音验证正常、不需要复验或覆盖所有输入法，按此收口，不再安排IME细分补验。长样本逐页验收见[§21.10](#2110-长样本人工逐页验收与r18关闭2026-10-17)，T7保存路径与T6-A证据见§20.6–20.7。下一步进入D2规格准备，未启动实现、真实AI或发行；产品与发行未整体验收。下列交付记录及历史轮次的“待复审／待补验”保留其当时状态，以最新结论为准。

**历史范围（截至 §10 的 OpenCode 自测记录）：** D1A 已编码并执行规格 §8 的必要验证；2026-10-12 完成 R1–R6 定点修复（见 §9），2026-10-13 按[独立审阅 §5](desktop-d1-review.md#5-r1r6-修复后独立复审2026-10-13)完成 R3／R4 第三轮修复与两套解释器复跑（见 §10）。该阶段自测不能替代独立复审，后续结论分别见下方注记与审阅记录。本文件保留实际执行内容和首次失败，不预填未执行项。

**D1B 实施记录（2026-10-14）：** B0–B5 已按当时任务实施，统一记录见 §11（含完成状态、命令、数量、证据与未验边界），其中“待 Codex 复审”为交付当时状态。**2026-10-15 独立复审未放行**，R1–R14 及本轮129／108／116项自动检查、包身份核对和真实交互未验范围见[审阅 §9](desktop-d1-review.md#9-d1b-实施复审2026-10-15)。原自测事实保持；D1 产品未验收，接续见[当前修复任务](../tasks/current.md)。

**OpenCode修复交付记录（2026-10-15，见 §12）：** R1–R14均有修复改动，新增真实窗口阶段与组件回归；自动检查133／108／129、纯逻辑套件＋21项组件检查通过；最终137文件包（EXE `f7c1a14f…`）仓外5进程串行记录和Element Plus入口修复保留。原生人工另存为、Word逐页及关闭失联／超时真实窗口注入仍未验。

**最新独立复审注记（Codex，2026-10-17）：** [第八轮修复审阅§17](desktop-d1-review.md#17-d1b-第八轮修复复审与工程收口2026-10-17)关闭R17，累计17项全部关闭，**D1B在当前Windows 11开发机工程复审通过**。独立原组件反例和真实窗口9/9通过，草稿留页保留、显式取消后可重试关闭；133／108／146项、纯逻辑＋60组件及前端检查通过，28e3e60e…包137文件同源。§19.12保留工程收口与未验范围；下一步按[当前清单](../tasks/current.md)做教师流程与实际IME体验，再准备D2规格。D1产品或发行未验收。

**OpenCode修复交付记录（2026-10-16，见 §16）：** 只按审阅 §13.3 修复 R1“新宿主关闭 B 先于旧 A 撤销通知到达”的残留：新关闭 ID 到达即按 ID 退役被替代的旧 open handler／协调器等待，不依赖旧通知或旧回包；组件回归 40→45、新增 `close-order`（撤销迟送／丢失两变体）与 `save-dialog`（真实原生对话框：中文名／取消／真实占用失败／解除后新 ID 重试／旧目标保护）窗口阶段；133／108／136 与 typecheck／build 复跑通过；新包 EXE `167b352b9465a546f0a0c8ee964bb4996bae1b147d01058161eacde638ba5385`（14,721,796 字节，180 文件）身份与源码一致，仓外 9 进程 returncode 全 0，Word 样本与已目视复核样本逐字节一致。R6 未改；实际输入法按键、人手动原生对话框、WPS／干净机器／Win10／其他 DPI／教师体验仍未验。**本节不自行写成 Codex 已关闭或 D1B 已放行。**

**OpenCode修复交付记录（2026-10-16 第六轮，见 §17）：** 只按审阅 §14.3／§14.4 修复 R1“迟到的旧 request_close 通知退役当前请求”与 R16“保存异常未脱敏”：页面先以宿主 `get_close_state` 连续两次 `pending` 确认当前请求，未确认的通知完全静默、不退役任何请求；宿主在发送 request 通知前复核当前 ID／状态；保存失败按占用／权限／I/O／对话框给出稳定脱敏原因，提交后核验失败保持 unknown。组件回归 45→49、桌面 136→142；新增源码／包 `close-order --close-order-request delayed|lost` 窗口变体（16／15 项，A 静默、B 单一许可）与 R16 占用文案检查；133／108／142／typecheck／build 通过；新包 EXE `8d1a4dbb3a97987552c16b0e7a5d2122d50da27c72e4df9afc1a12aee4a59199`（137 文件）与源码一致，仓外 11 进程 returncode 全 0；同 tag Word 样本与已目视复核样本逐字节一致。**本节不自行写成 Codex 已关闭或 D1B 已放行。**

**OpenCode修复交付记录（2026-10-17 第七轮，见 §18）：** 按审阅 §15.2–§15.3 先修 R17“最终核对后的等待窗口允许新输入仍放行关闭”再收束 R1“最后一次确认回包迟到仍可退役当前 B”：宿主在锁内为每个关闭请求分配递增代际并绑定通知与 `get_close_state` 回答，页面保留已接受代际、在每个 await 后拒绝过期确认、确认中收到撤销即静默；`finishClose` 在全部等待结束后重新落定 IME 并同步复核 dirty／identity，最后一次核对与冻结之间无 await，新输入留页不丢字。组件回归 49→55、桌面 142→146；新增 `close-order --close-order-request lastack`（A 最终回包迟到、撤销已送／丢失两变体各 13 项）与 `late-input-close`（最终确认等待中真实表单输入、两变体各 16 项）窗口变体，最终源码 15 阶段与包内 15 进程 returncode 全 0、checks 全 true；133／108／146／typecheck／build 通过；新包 EXE `f243b4473cf5f9d13fcdf9f3b5b2ad2309a0a8fddab92f6be34ae4650db0a2dd`（14,734,848 字节、137 文件）与源码一致，Word 样本与已目视复核样本逐字节一致。**本节不自行写成 Codex 已关闭或 D1B 已放行。**

**OpenCode修复交付记录（2026-10-17 第八轮，见 §19）：** 按审阅 §16.3–§16.6 只收束 R17 设置页残留：`finishClose` 的最终同步核对在日计划 dirty／identity 之外同时复核设置草稿／预览确认状态（`isSettingsDraftBlocking()`），等待中新草稿一律留页、保留全部输入并显式释放 pending，不自动应用或丢弃；入口检查、R1 代际保护与 IME 落定规则不变。组件回归 55→60（等待中新输入／预览中／等待失败／请求替代／超时五组），真实新增 `--phase settings-draft-close`（撤销已送／丢失两变体各 22 项）；最终源码 17 阶段与包内 17 进程 returncode 全 0、checks 全 true；133／108／146／typecheck／build 通过；新包 EXE `28e3e60e31615fde859526447b47e0bdbf3f51a56719429a2008510d4c5822a3`（14,741,133 字节、137 文件）与源码一致；f243b447… 及更早包保留；Word 样本仍与已目视复核样本逐字节一致。**本节不自行写成 Codex 已关闭或 D1B 已放行。**

**OpenCode R18 实施与验证记录（2026-10-17，见 §21）：** 按规格 §12.4 定点实现日计划标题显式居中、署名仅班级＋教师、表格全部文字显式非粗体（含标红run）；先失败后通过输出级检查（10项先失败、周计划字节不变）；109／108／134／146 项测试通过；新包 EXE `c6dc19283a24d00a740f2ecbed2cc7159e951f02a37f00636b294b7670369930`（14,743,868 字节、137 文件）与源码／模板／前端一致，7 个真实窗口阶段＋99 项样本输出检查通过，Word 16.0 逐页 38 页 0 处粗体问题；旧 28e3e60e… 包与体验记录保留。**R18 待 Codex 复审与用户复看新格式，本节不自行关闭。**

后续独立复审注记（Codex，2026-10-13）：[审阅 §7](desktop-d1-review.md#7-版本统一与-d1a-放行2026-10-13)依据[版本核查](desktop-d1-technical-review.md#7-python-版本统一核查2026-10-13)选定 D1 统一目标为 CPython 3.14.7 标准 Windows x64；R1–R6 全部闭合，87 项本地测试、108 项回归通过，D1A 工程放行，可进入 D1B 规格收敛。桌面环境对齐、新包与 D1B 业务未验证。3.12 独立复验原生异常及未知根因保留在[审阅 §6](desktop-d1-review.md#6-r3r4-收口复审与运行时验证阻塞2026-10-13)，不再作唯一门槛。本文件以上及 §10 保留 OpenCode 当时自测事实，不改写为 Codex 两套复验均通过。

## 1. 改动文件与功能

### 1.1 新增：本地入口、模型、事务、服务与 API

| 文件 | 功能 |
| --- | --- |
| `backend/app/local/base.py` | 独立 `LocalBase`（不导入旧 `app.database`）、UTC 时间约定 |
| `backend/app/local/models.py` | 单档案、设置、班级、学期、日历修订／日历日、日计划头／内容、操作记录 9 张表与命名 CHECK／FK／局部唯一索引 |
| `backend/app/local/sqlite.py` | 数据目录解析（`%LOCALAPPDATA%\KindergartenManager\data`）、`kindergarten.db`、pysqlite engine、每连接 `foreign_keys=ON`／`busy_timeout=5000`／`synchronous=FULL`／WAL、`isolation_level=None` 关闭驱动隐式 BEGIN |
| `backend/app/local/runtime.py` | `LocalRuntime`：目录、迁移准备、engine／per-request Session 生命周期 |
| `backend/app/local/migrate.py` | 真实 Alembic 状态检查与升级：空库基线、已知 revision 升到 head、未知／较新 revision 与非空无版本库拒绝、不可读文件拒绝；不清库、不 stamp、不降级 |
| `backend/app/local/tx.py` | 显式读取 `BEGIN`、写事务 `BEGIN IMMEDIATE`、回滚、按 `sqlite_errorcode`／`sqlite_errorname` 分类 busy／唯一冲突，`storage_errors` 统一映射 503 |
| `backend/app/local/errors.py` | §5 错误码实现与启动拒绝异常 `LocalDatabaseStateError` |
| `backend/app/local/normalize.py` | 初始化输入正规化（姓名／班级／学期 1–80、园所空或 1–120、small/middle/large、ISO 日期、去首尾空白）、重试指纹、raw 文本与日期范围校验；复用已审查的 `config_normalize` |
| `backend/app/local/calendar_build.py` | 初始化时构建完整日历候选；`unknown` 与库运行故障区分；周次复用 `calendar_service.week_info` |
| `backend/app/local/calendar_read.py` | `GET /api/local/calendar` 逐日解释：term_id／week_number／weekday／effective_state／date_eligible／reason／revision_id／existing_plan_id；缺持久行报数据错误 |
| `backend/app/local/profile_service.py` | 上下文读取；初始化顺序（短读预检 → 锁外构建日历 → `BEGIN IMMEDIATE` 复核 → 原子建立档案／设置／班级／学期／修订／日历日／审计）；同 key 重试、冲突与已初始化决策 |
| `backend/app/local/daily_plan_service.py` | 创建或打开（先读已有有效记录）、按日期／ID／范围读取、追加版本保存（旧版本条件更新指针并核对影响行数、审计同事务） |
| `backend/app/local/schemas.py` | 请求模型 `extra="forbid"`（拒绝归属／`split_baseline` 等伪造字段）；响应模型保持旧 `DailyPlanOut` 形状并去掉 `weekly_sync_state` |
| `backend/app/local/api.py` | 全部路由；归属字段（body 与查询参数）拒绝；身份／班级／学期服务器推导 |
| `backend/app/local/app.py` | 可被宿主调用的 app factory（数据路径＋host／port／session token）；精确 Host、写请求 Origin、`X-App-Session` 守卫；禁用公开文档；错误统一 `{error:{code,message}}` |

### 1.2 新增：独立 Alembic 环境与基线

- `backend/alembic-local.ini`、`backend/migrations_local/env.py`、`script.py.mako`：SQLite-only 迁移入口，独立版本表 `local_alembic_version`，不读取旧 `DATABASE_URL`／`.env`；DDL 在一个显式 `BEGIN IMMEDIATE` 内执行，失败整体回滚。
- `backend/migrations_local/versions/20261012_0001_local_baseline.py`：一次性基线，含循环内联复合延迟外键、`(class_id, plan_date) WHERE deleted_at IS NULL` 局部唯一索引、命名 CHECK；`downgrade()` 明确拒绝。
- 旧 `backend/migrations/` 未改动，未向新库 stamp 任何旧 revision，未使用 `create_all()`。

### 1.3 最小解耦改动（既有文件）

- `backend/app/ids.py`（新增）：22 位 URL-safe ID 原语，无配置依赖。
- `backend/app/security.py`：`generate_id()` 委托 `app.ids.new_opaque_id()`，行为不变。
- `backend/app/services/daily_plan_content.py`：改引 `app.ids`，内容校验不再经由 `app.security` 间接加载旧 settings；结构／ID 规则不变（既有 66 项内容／日期／安全测试通过）。

### 1.4 新增：D1A 测试

`backend/tests/local/`：`support.py`（临时数据根守卫、真实 Uvicorn＋`http.client`、子进程 worker、触发器等）、`worker.py`（跨进程动作）与 8 个测试模块共 67 项（见 §3）。测试全部注入临时目录，`assert_inside` 守卫保证不触碰真实教师目录；D0 的 `KindergartenManager-D0`／`d0_probe.db` 未导入、未改名、未搬迁。

## 2. 实际实现的契约要点

- 单档案：随机 22 位不透明 ID，`singleton` CHECK=1 且 UNIQUE；姓名不是主键、重启不重新生成。
- 初始化：`request_id`(UUID)＋姓名＋班级名＋年级＋学期名＋起止日期（园所名可空）；同 key 同输入重试 200 读回原对象、同 key 改输入 409 `INITIALIZATION_REQUEST_CONFLICT`、其他 key 409 `ALREADY_INITIALIZED`；失败（含库故障、触发注入的中途失败）全部回滚为 uninitialized；已提交后库故障不影响重试读回。
- 日历：`unknown` 不伪造上课日；库运行故障 503 `CALENDAR_UNAVAILABLE`；缺持久日历行为数据错误；已存修订不随库升级或重启重算；已有计划在日期不再具备新建资格时仍可读取、打开与保存。
- 日计划：允许空内容；`raw_lesson_plan` 原文保留；组／游戏 ID 服务器生成、只允许当前计划当前版本的旧 ID，拒绝未知／重复／跨计划；`split_baseline` 仅服务器持有（本片为 null），客户端提交即 422；创建时表头快照与 `calendar_revision_id` 不可变；保存追加版本 +1、过期版本 409 不重发、冲突不新增历史／日志。
- 事务：写事务先 `BEGIN IMMEDIATE` 再做业务读；读取用真实 `BEGIN` 包围；仅确认是有效日期局部唯一索引冲突时才按“打开赢家”处理，其余完整性／I/O 错误按 503 `LOCAL_STORAGE_ERROR`；总线忙 503 `LOCAL_DATABASE_BUSY`，等待上限 5 秒。
- 隔离：本地包不导入旧 `app.main/config/database/models/deps`／`app.security`，不挂载旧鉴权／管理员／周计划／AI 路由，不依赖 MySQL、不建周表／占位同步；token 仅内存、不入 URL／日志／业务表。

## 3. 验证命令、数量与结果

> 本节为初次实施轮（2026-10-12 上午）记录，保留原事实；同日 R1–R6 修复轮的两套解释器复跑与新增测试见 §9.2（本地套件由 67 项增至 84 项）。

全部命令在 `C:\Users\yw980\code\kindergarten-manager-next\backend` 下执行，`APP_DISABLE_DOTENV=1`、`PYTHONIOENCODING=utf-8`、`-X utf8`。

| # | 命令 | 结果 |
| --- | --- | --- |
| 1 | `backend/.venv/Scripts/python.exe -m unittest discover -s tests/local -t .` | **67 passed，0 skipped，exit 0**（多次运行 41–70s；Python 3.14.7／SQLite 3.50.4） |
| 2 | 桌面目标解释器临时环境（`uv sync --frozen --python 3.12`，仓库外）同命令 | **67 passed，0 skipped，exit 0**（41–56s；Python 3.12.10／SQLite 3.49.1） |
| 3 | `python -m unittest tests.unit.test_i3_content_validation tests.unit.test_security tests.unit.test_calendar_boundaries tests.unit.test_i3_api_schemas` | **66 passed，exit 0**（受影响内容／日期／安全规则） |
| 4 | `python -m unittest discover -s tests/unit -t .` | 686 项，**685 passed，1 error（既有 Windows 环境限制）**，详见 §5 |
| 5 | 仓库根 `desktop/.venv/Scripts/python.exe -m pytest desktop/tests -q` | **92 passed，2 warnings，8.26s**（D0 套件未受影响；未重跑 GUI 验收） |

测试分布（`tests/local/`）：`test_migrations` 11、`test_initialize` 13、`test_daily_plans` 12、`test_transactions` 9、`test_concurrency` 5、`test_calendar_dates` 6、`test_guards` 10、`test_restart` 1。

### 3.1 规格 §8 逐项证据

| §8 验证 | 实际证据 |
| --- | --- |
| 本地 Alembic | 临时真实文件空库升至 head（版本表 `local_alembic_version`＝`20261012_0001_local`）；重复启动不改数据；未知／较新 revision（`LOCAL_DB_VERSION_UNSUPPORTED`）、非空无版本库（`LOCAL_DB_NOT_MANAGED`）、不可读文件（`LOCAL_DB_UNREADABLE`）拒绝且保留原文件；`create_local_app` 拒绝时无可写 API；CLI `python -m alembic -c alembic-local.ini upgrade head` exit 0；FK／CHECK／局部唯一索引 DDL 与 5000ms／FULL／WAL pragma 逐连接核验 |
| 初始化 | 必填／日期／年级／额外字段 422；整套行数与完整 30 天日历、审计各 1；日历日插入触发器注入失败后计数全 0 且仍 uninitialized；同 key 重试 200 无新行；同 key 改输入与不同 key 409；初始化后切换为故障日历 provider，同 key 仍 200、不同 key 仍 409；库故障初始化 503 且无半初始化；未知年份保存 `unknown` |
| 内容和归属 | 空内容、全部真实栏目、原文（含换行／全角空格）、稳定游戏／组 ID；未知／重复／跨计划 ID 422；创建表头、日期、`calendar_revision_id` 保存后不变；`split_baseline`、归属字段 body／query 均 422 |
| 指针与回滚 | 直接 SQL：缺首版、版本不匹配、跨计划指针均在提交时被延迟 FK 拒绝；重复内容版本被唯一约束拒绝；内容插入、指针更新（提交期延迟 FK 失败）、审计插入三类触发注入均 503 且内容／指针／日志回到原状态；创建路径注入失败不被解释为“打开已有” |
| 真实文件并发 | 两个独立引擎（线程屏障）同日创建仅 1 行；两个独立进程同日创建仅 1 行；两个进程同 expected version 保存恰 1 成功、1 个 `VERSION_CONFLICT` 且内容 2 行／保存审计 1 行；同日唯一索引拒绝第二份有效记录 |
| 数据库忙与读取 | 子进程持写锁时写入在 ≥4s 后返回 `LOCAL_DATABASE_BUSY`（上限 5s），释放后重试成功；快照一致性用文件屏障：显式 BEGIN 内两次 SELECT 在并发提交后仍一致，结束后可见新版本 |
| 日期 | 端点／周次（周一为首日、起始周为第 1 周）／跨年不重置、调休按真实日期所在周、`unknown` 与库故障分离、缺日历行报错、重启不按库新版本重算、已有记录读取不依赖当前 `date_eligible` |
| 进程重启 | 三个连续独立进程：初始化＋创建＋两次保存（版本 1→3），重启进程读回档案 ID、班级／学期、日历修订、3 条内容历史、当前指针与 4 条审计一致；第三个进程可继续保存到 v4 |
| 依赖及防护 | 无／错 token 401 `APP_SESSION_REQUIRED`；错误 Host／Origin 403；只读请求不要求 Origin；`/docs`、`/redoc`、`/openapi.json` 404；未知路由 404 信封、方法不符 405 信封；子进程导入本地包后 `app.config/app.security/app.database/app.models/app.main/app.deps/pymysql/dotenv/pydantic_settings` 均不在 `sys.modules`；正常请求链路（health→context→initialize→calendar→create→save→list→by-date）成功 |

### 3.2 数据库与竞态证据位置

- 可检查的持久证据：`%TEMP%\kgm-d1a-evidence\` — 含 `data\kindergarten.db`（135,168 字节；单档案、30 天日历、1 计划、3 版本、4 审计，`PRAGMA foreign_key_check` 为空、`journal_mode=wal`、`synchronous=2`）与 `summary.json`（迁移状态、HTTP 状态码、重启读回、行数、内容历史与指针；摘录：初始化 201、重试 200、重复创建 200 同 ID、过期保存 409 `VERSION_CONFLICT`、重启后 `current_content_version=3`）。
- 竞态证据：测试内多进程 worker 使用临时目录（`%TEMP%\kgm-d1a-test-*`，用例结束自动清理），关键断言见 §3.1“真实文件并发”“数据库忙与读取”。
- 测试用临时数据库均为真实文件（SQLite WAL）；未使用内存数据库或 mock 替代真库证据；故障注入使用真实 SQLite 触发器与延迟 FK 提交失败。

## 4. 环境与版本

| 环境 | 用途 | 版本 |
| --- | --- | --- |
| `backend/.venv`（2026-10-12 按用户批准新建） | 主验证环境，由 `uv sync --frozen` 依 `backend/pyproject.toml`＋`uv.lock` 创建；按 `backend/.python-version` 使用 Python 3.14.7 | SQLAlchemy 2.0.54、Alembic 1.20.0、SQLite 3.50.4、FastAPI 0.141.1、Pydantic 2.13.5、Starlette 1.6.0、Uvicorn 0.53.0、chinesecalendar（发行版）1.11.0 |
| 仓库外临时 venv（与 `uv.lock` 同一冻结集合，仅换解释器） | 桌面目标解释器复跑 | Python 3.12.10、SQLite 3.49.1、SQLAlchemy 2.0.54、Alembic 1.20.0、FastAPI 0.141.1 |
| `desktop/.venv`（D0） | 未改动，未安装任何新包；D0 套件复跑 | Python 3.12.10、SQLite 3.49.1 |

未安装 Skill／MCP，未新增项目依赖（Alembic 与 chinesecalendar 本为 backend 已声明依赖），未连接旧 MySQL／远程服务，未读取真实密钥或旧 `.env`，未调用真实 AI，未提交／推送，未改动前端页面、D0 通过代码、Word 生成器、旧 MySQL 模型／迁移或 `ARCHITECTURE.md`。

## 5. 既有测试的已知环境限制（非 D1A 引入，未在本片修复）

- `tests/unit/test_ai1a_url_guard_edges.py::test_disabled_guard_never_connects` 硬编码 Linux 路径 `.venv/bin/python`；当前 Windows 检出无该路径。这是既有 Windows 环境限制（该测试设计于 Linux／WSL 会话），与 D1A 改动无关；补齐需另行授权（超出本片范围）。
- `tests/unit/test_ai1c_acceptance_fixture.py` 的 3 项输出脱敏测试用 `text=True`（UTF-8）读取子进程输出，而本机控制台默认 GBK，导致子进程输出解码失败；设置 `PYTHONIOENCODING=utf-8` 后 3 项全部通过。属环境编码差异，与 D1A 无关。
- 未运行 `backend/tests/integration/`（需白名单隔离 MySQL 的 v1 套件），不属 D1A 范围。

## 6. 实现取舍与待 Codex 确认的细节

以下为规格未逐字固定、由本片按最小冲突原则决定的细节，均已在测试中固定行为，请复审确认：

1. 计划详情响应包含 `calendar_revision_id`（§3 表头字段“创建所用日历修订”），其余保持旧 `DailyPlanOut` 形状并去掉 `weekly_sync_state`，未生成替代空摘要。
2. `POST /api/daily-plans` 先读已有有效记录：日期已无新建资格但已有计划时返回 200 打开（依据 §5“已有记录不因新建日期资格变化而失去打开能力”）；无计划的不合格日期仍返回 422。
3. `POST` 显式 `adopted_content: null` 按“字段出现但非对象”返回 422，与 PATCH 规则一致。
4. 未受信任 Host／Origin 的 403 码取 `FORBIDDEN_HOST`／`FORBIDDEN_ORIGIN`（规格只固定状态码 403）。
5. 健康检查路径 `/api/local/health`，仅返回 `{"status":"ok"}`，无需会话。
6. 本地上下文要求恰好一个学期（D1A 只允许一次初始化创建）；出现多学期按持久数据错误处理，学期维护／切换属 D1B。
7. Alembic CLI 与测试可用 `KGM_LOCAL_DATA_DIR`／`KGM_LOCAL_DB_PATH` 指定位置；生产默认仍为 `%LOCALAPPDATA%\KindergartenManager\data\kindergarten.db`。
8. 有效日期唯一冲突仅在 `sqlite_errorname=SQLITE_CONSTRAINT_UNIQUE` 且消息含 `class_id, plan_date` 时按“打开赢家”处理，并以其后新事务实际读到的记录为准。

## 7. 遗留与未验边界

- D1B 未开始：首次设置页、工作台／真实表单、离开自动保存、配置维护、Word 范围／缺项确认与原生保存均未实现；**D1A 通过不等于 D1 桌面业务已验收**。
- D1A 自己的真库验证均为工程验证：未做用户本人操作、真机教师数据、WPS／Word 全页、干净机器或 Win10 验证；这些属于后续切片与发行范围。
- 未验证：WebDAV 一致性快照与接续、历史恢复、删除／恢复、AI 与周计划依赖、旧数据导入（按规格均不在本片范围）。
- 评测环境差异：主验证为 Python 3.14.7／SQLite 3.50.4（backend 声明解释器），已在桌面目标 3.12.10／SQLite 3.49.1 复跑同一套 67 项；最终打包解释器仍以 D1B／发行验证为准。

## 9. R1–R6 定点修复（2026-10-12 第二轮）

依据[独立审阅](desktop-d1-review.md) §2 与[当前任务](../tasks/current.md)；本轮只做 R1–R6、审阅 §4 的 `date.max` 边界及必要测试，不改审阅结论、不进入 D1B。

### 9.1 逐项改动与验证

| 项 | 实现改动 | 新增／修正验证 |
| --- | --- | --- |
| R1 完整版本保护 | `migrate.inspect_database` 读取 `local_alembic_version` 全部记录：多行（已知＋未知任一插入顺序、重复已知行）一律按 `LOCAL_DB_VERSION_UNSUPPORTED` 拒绝，空／非文本单记录同样拒绝；原库不清、不 stamp、不降级 | `test_multi_row_version_states_are_refused_in_both_orders`（3 种顺序，均断言拒绝且行逐条不变）；既有单未知／较新拒绝、重复启动与 `test_paths` 重启覆盖正常单 head 启动。持久证据 `summary.json`→`R1`：3 种状态拒绝后行完全保持 |
| R2 首修订非空保证 | `models.py` 指针改 `Mapped[str]`、`nullable=False`；`profile_service._create_initialized` 预分配修订 ID，先插学期（非空指针、复合延迟 FK）再插首修订，同一事务提交；新增迁移 `20261012_0002_local`：先校验每个学期指针存在且归属本学期的修订（NULL／悬空／错归属即拒绝，保留原库），再按 SQLite 文档流程重建 `local_terms` 为 NOT NULL；`env.py` 迁移事务改为 FK OFF ＋提交前 `PRAGMA foreign_key_check`（应用连接仍每连接 `foreign_keys=ON`）；基线 0001 保持历史 nullable，约束由 0002 加到新旧库 | `test_migrations`：空库 head DDL／`PRAGMA table_info` NOT NULL 与索引键检查；`test_old_head_with_valid_pointer_upgrades_and_keeps_data`（真实 Alembic 0001＋完整初始化→升级，ID／指针／30 天日历保留，重开后可读可存）；NULL／悬空／错归属三拒绝（文件、版本、行、nullable 全保留）；`test_failed_upgrade_rolls_back_midway_and_preserves_old_data`（复制期 CHECK 失败→版本 0001、原行与新表残留均无）；`test_term_revision_pointer_schema_constraints`（NULL 即时 NOT NULL 失败；悬空延迟 FK 在 COMMIT 失败；循环两行同事务提交成功且 `foreign_key_check=[]`）。持久证据 `summary.json`→`R2` 与 `r2-old-head-valid\data\kindergarten.db`、`r2-old-head-null\data\kindergarten.db` |
| R3 路径编码 | `alembic_config` 对 `script_location` 与 `sqlalchemy.url` 做 `%`→`%%` 转义，另以 `config.attributes["sqlalchemy_url"]` 传原始 URL 供 env.py 使用；`sqlite.readonly_sqlite_uri` 改用 `Path.as_uri()+?mode=ro`（`#`／`%`／空格／中文全部百分号编码）；`inspect_database` 记录打开前 `-wal`/`-shm` 是否存在，仅移除本次只读打开创建的空日志文件，绝不动已存在的文件 | `tests/local/test_paths.py`：`teacher%name`、`teacher#name`、`中文 空格%号#目录` 三路径各自首次迁移＋重启读回，数据目录只有数据库文件、父目录无 `teacher` 等旁路文件；未知版本拒绝前后目录快照逐项相同；CLI `alembic upgrade head` 经 `KGM_LOCAL_DATA_DIR` 对特殊路径成功。持久证据 `summary.json`→`R3` 与 `r3-paths\...\data\kindergarten.db` |
| R4 持久内容损坏边界 | `daily_plan_service._load_content`：`session.get` 的 JSON 解码失败（`JSONDecodeError`/ValueError）与 `split_baseline` 解码失败映射 503 `LOCAL_STORAGE_ERROR`；`_validate_stored_content` 用纯结构解析（不生成 ID、不修复）校验对象／栏目结构，并要求持久 ID 为非空、内容内唯一；读取、按日期读、重复创建打开、PATCH 遗漏与显式提供内容全部经过该边界，非法客户端输入仍在锁外保持 422 | `test_daily_plans`：5 类损坏值（非法 JSON、未知栏目对象、数组、缺 group_id、重复 ID）× GET／by-date／POST 同日打开均 503 且 list 仍按表头工作；PATCH 遗漏／改原文／显式新内容三路径 503 且版本、指针、内容行数、审计行数不变；错误响应不含损坏文本与数据库路径；显式非法客户端内容仍 422；`split_baseline` 非法 JSON 也 503 |
| R5 锁外输入结构校验 | `save` 在 `BEGIN IMMEDIATE` 之前完成 expected version 整数校验、`raw_lesson_plan` 纯正规化与 `adopted_content` 结构解析；锁内重新读取上下文、计划、当前内容与 stored version，再以 `materialize_adopted_content` 对刚读出的当前内容做 ID 归属／重复校验；共享模块仅拆出 `materialize_adopted_content`，`prepare_content` 行为不变 | `test_concurrency.test_locked_write_rejects_invalid_structure_without_busy_wait`：独立进程持写锁时真实 HTTP PATCH 非法结构 <2s 返回 422，内容／审计无新增，释放后合法保存 200；既有忙等待 ≥4s 503 与两进程 save 竞争测试不变；v1 内容 ID 规则回归 108 项通过 |
| R6 关键测试漏检 | `worker.py` 新增 `read_list_snapshot`／`read_detail_snapshot`：用 `after_cursor_execute` 在生产 `list_plans`／`get_by_date` 的显式读事务内部架设文件屏障（旧 `snapshot_reader` 原语探针移除）；同日唯一约束测试改为断言 INSERT 阶段 `SQLITE_CONSTRAINT_UNIQUE`、消息含 `class_id`/`plan_date` 且非 FK；迁移测试补 `PRAGMA index_list`（unique=1、partial=1）与 `PRAGMA index_info` 恰为 `(class_id, plan_date)` | `test_list_read_uses_one_snapshot_under_concurrent_commit`（count 后并发提交第二份计划：total 与 items 同为 1，随后新读为 2）；已做反证：临时禁用 `begin_read` 的真实 `BEGIN` 后该测试失败（total=1、items=2）；`test_detail_read_stays_internally_consistent_under_concurrent_save`；`test_second_effective_plan_is_rejected_by_unique_index_at_insert` 与删除索引后完全合法重复提交成功的对照用例 |
| 审阅 §4 日期边界 | `calendar_service.iter_dates` 在 `end` 处结束而不做越界的 `+1 天`（闭区间语义不变） | `test_calendar_dates.test_max_date_boundary_does_not_overflow`：`9999-12-31` 单日与两日范围 200 且 `outside_term`，计划列表同日范围 200 |

### 9.2 修复轮复跑命令与结果

全部命令工作目录 `backend`，环境变量 `APP_DISABLE_DOTENV=1`、`PYTHONIOENCODING=utf-8`，解释器加 `-X utf8`。

| # | 命令 | 结果 |
| --- | --- | --- |
| 1 | `%TEMP%\kgm-d1a-py312-venv\Scripts\python.exe -m unittest discover -s tests/local -t . -v` | **84 passed，0 skipped，exit 0**（43.136s；Python 3.12.10／SQLite 3.49.1；日志 `local-py312.log`） |
| 2 | `backend/.venv/Scripts/python.exe -m unittest discover -s tests/local -t . -v` | **84 passed，0 skipped，exit 0**（45.873s；Python 3.14.7／SQLite 3.50.4；日志 `local-py314.log`） |
| 3 | `python -X utf8 -m unittest tests.unit.test_i3_content_validation tests.unit.test_security tests.unit.test_calendar_boundaries tests.unit.test_i3_api_schemas tests.unit.test_i5_export_read_service -v` | **108 passed，exit 0**（0.352s；受影响内容／日期／安全与 Word 读取回归；日志 `regression-v1.log`） |

修复轮测试分布（84 项）：`test_migrations` 18、`test_daily_plans` 15、`test_initialize` 13、`test_transactions` 10、`test_guards` 10、`test_calendar_dates` 7、`test_concurrency` 7、`test_paths` 3、`test_restart` 1。依赖：两环境均 SQLAlchemy 2.0.54、Alembic 1.20.0、FastAPI 0.141.1、Pydantic 2.13.5，`chinesecalendar` 发行版 1.11.0；临时 3.12 环境另有 Starlette 1.6.0、Uvicorn 0.53.0。未新增／升级依赖，未改 `pyproject.toml`／`uv.lock`。

先反例后全套的次序：R1–R6 相关模块先逐一运行通过（含上表各反例），再跑两套完整本地套件；未重复 D0 92 项与 v1 全量验收。

### 9.3 旧 head 升级与故障回滚持久证据

证据目录 `%TEMP%\kgm-d1a-r1r6-20261012\`（含 `summary.json` 与本轮三份日志；临时路径不保证长期留存，结论以本文为准）：

- `summary.json`→`R2`：真实 `20261012_0001_local` 文件经正常初始化后，`local_terms.current_calendar_revision_id` 由 nullable(0)→NOT NULL(1)，profile／term／修订 ID 与指针保留，`PRAGMA foreign_key_check=[]`，30 条日历日与日历修订完整迁移到 `20261012_0002_local`；可继续用持久化日历保存计划（测试内同时验证）。
- `r2-old-head-null\data\kindergarten.db`：NULL 指针旧库升级返回 `LOCAL_DB_MIGRATION_FAILED`，版本仍 0001、行与 NULL 指针、nullable 模式全部保留。
- `summary.json`→`R1`：三种多行版本状态同样拒绝且行不变；`R3`：特殊路径迁移／重启后目录只有 `kindergarten.db`，未知版本拒绝前后目录列表一致。
- 复制期中途失败回滚由 `test_failed_upgrade_rolls_back_midway_and_preserves_old_data` 覆盖：迁移失败后版本、超长名行、非空指针与旧 nullable schema 均保持原样，无 `_local_terms_rebuild` 残留。

### 9.4 遗留与未验边界

- 本轮仅为修复完成与本地复跑；**Codex 独立复审尚未进行**，不能写成 D1A 审阅通过。D1B 未实施，D1 产品未验收。
- §4 的初次实施环境差异仍然成立：原任务要求 3.12.10 与 `uv sync --locked`，初次实施使用 3.14.7 与 `uv sync --frozen`；修复轮按要求用现有 3.12.10 临时环境做主复跑、3.14.7 做兼容复跑，未销毁或重建任何环境。
- 未重跑 D0 GUI／合成 Word，未跑 `tests/integration/`（需隔离 MySQL 的 v1 套件），未连接旧 MySQL／远程业务、未读真实 `.env`／密钥、未调用真实 AI、未提交／推送。
- 学期范围变更后的已有计划入口、多学期维护、真实桌面页面、离开自动保存、配置维护与 Word 仍属 D1B；本轮没有新增对应 API。`date.max` 只修遍历终止，没有新增任意日期范围限制。
- （后续记录：2026-10-13 独立复审见[审阅 §5](desktop-d1-review.md#5-r1r6-修复后独立复审2026-10-13)，R1／R2／R5／R6 及日期上限通过核查，R3／R4 反例在本文 §10 定点修复。）

## 10. R3／R4 第三轮定点修复（2026-10-13）

依据[独立审阅 §5](desktop-d1-review.md#5-r1r6-修复后独立复审2026-10-13)与[当前任务](../tasks/current.md)：只修复 R3 迁移配置／资源路径与 R4 持久 `split_baseline` 校验，保留 R1／R2／R5／R6 及 `date.max` 已通过实现，不进入 D1B。修复前先用临时探针在合成目录复现两个反例，修复后先跑相关模块，再跑完整本地套件与受影响回归。

### 10.1 改动

| 项 | 文件 | 实际改动 |
| --- | --- | --- |
| R3 | `backend/alembic-local.ini` | 去掉全部 `%(here)s`：`script_location = migrations_local`、`prepend_sys_path = .`（受支持 CLI 在 `backend` 目录运行）。ConfigParser 会对替换后的值再次插值，INI 所在目录含 `%` 时原写法抛 `InterpolationSyntaxError` |
| R3 | `backend/app/local/migrate.py` | 新增 `_escape_ini_value`；`alembic_config()` 除 `script_location` 外同时以绝对路径覆盖 `prepend_sys_path`（均 `%`→`%%`），程序入口不再依赖工作目录 |
| R4 | `backend/app/local/daily_plan_service.py` | `_validate_stored_content` 在共享读取边界拒绝任何非 null 的持久 `split_baseline`（D1A 手工内容契约为 null）；不生成、不正规化、不清空、不复制 |
| 测试 | `backend/tests/local/test_paths.py` | 新增资源路径矩阵：特殊迁移资源目录 × {普通数据目录、特殊数据目录}，程序入口与 CLI 各自首次迁移／正常重启／未知版本拒绝；复制资源树时把 head revision 改写为哨兵 `20990101_0000_resource_sentinel`，证明实际消费的是注入资源；目录快照与旁路库检查保留 |
| 测试 | `backend/tests/local/test_daily_plans.py` | 新增 `split_baseline` 故障矩阵与 null 基准回归；客户端非法输入仍 422；每次失败后核对版本／指针／内容历史／审计，并断言服务日志无合成标记／路径／token |
| 测试 | `backend/tests/local/support.py` | 新增 `ServerLogCapture`（挂接 uvicorn／uvicorn.error／uvicorn.access／fastapi 记录器） |

未改前端、D0 代码、Word 生成器、旧 MySQL 模型／迁移、`ARCHITECTURE.md`、`pyproject.toml`／`uv.lock`。

### 10.2 R3 结果

修复前探针（把原 INI 复制到 `teacher%name` 后仅替换 `ALEMBIC_INI_PATH`，调用真实 `ensure_local_schema`）：空库首次迁移返回 `LOCAL_DB_MIGRATION_FAILED`，cause 为 `InterpolationSyntaxError: '%' must be followed by '%' or '(', found: '%name'`。CLI 端把 INI 还原为修复前取值后同样反例：rc=1、未创建数据库、stderr 含 `InterpolationSyntaxError`（`mutation-r3.log`）。

修复后覆盖（`test_paths.py`，两套解释器均通过）：

- 程序入口：`teacher%name`、`teacher#name`、`中文 空格%号#目录` 三个资源目录 × {普通数据目录、`数据 %#空格` 数据目录}；空库首次迁移写入哨兵 head，正常重启保持 current，未知版本拒绝且目录快照与版本行不变；数据目录仅允许数据库及 WAL 边车，holder 内无旁路 `kindergarten.db`，也无截断路径文件。
- CLI：`backend% 检出#` 资源目录 × 普通／`数据 %#cli` 数据目录；`python -m alembic -c alembic-local.ini upgrade head` 首次与重启 exit 0、版本为哨兵 head；未知版本 rc≠0 且版本与目录不变。
- 程序入口在仓库根目录运行同样完成到 head（不再依赖工作目录相对定位）。
- 变异反证：移除 `script_location` 覆盖后新用例失败；CLI 恢复旧 INI 取值后在特殊目录 rc=1 且未建库，即用例矩阵能识别两类回归。
- 既有数据路径回归（特殊目录初始化／重启、未知版本目录快照、CLI 特殊数据目录）保留并继续通过。

### 10.3 R4 结果

修复前（真实 HTTP、合成故障库）：数组基准 GET 500；PATCH 在 `session.commit()` 之后因响应模型校验 500，实际已把 v1→v2、内容 +1、审计 +1；Uvicorn 日志输出 `ResponseValidationError` 完整损坏基准原值（含合成标记）。修复后同一探针：GET／PATCH 均 503 `LOCAL_STORAGE_ERROR`，版本、指针、内容数、审计不变，stderr 为空。

矩阵用例 `test_persisted_split_baseline_corruption_is_storage_error_matrix`：

- 故障值：非法 JSON 原文、JSON 数组、JSON 字符串、非法对象（各含合成标记）。
- 请求：GET by-id、GET by-date、POST 同日重复创建（打开已有）、PATCH 遗漏内容、PATCH 只改原文、PATCH 显式提供合法内容——每类均 503 `LOCAL_STORAGE_ERROR`，且每次失败后断言版本、当前指针、内容历史行数、审计行数不变。
- 客户端非法输入（`adopted_content` 非法结构）仍 422 `VALIDATION_ERROR` 且状态不变。
- `test_null_split_baseline_still_reads_and_saves`：损坏计划旁的合法 null 基准计划可正常读取与追加保存（v1→v2，基准仍 null），损坏计划未因此被修复。
- 日志：捕获器先自检再断言无合成标记、数据库路径、token、`ResponseValidationError`。
- 变异反证：恢复第二轮校验后矩阵用例失败（4 个子用例），证明测试能识别该回归。

### 10.4 复跑命令与结果

工作目录 `backend`；`APP_DISABLE_DOTENV=1`、`PYTHONIOENCODING=utf-8`、`-X utf8`。

| # | 命令 | 环境 | 结果 |
| --- | --- | --- | --- |
| 1 | `%TEMP%\kgm-d1a-py312-venv\Scripts\python.exe -X utf8 -m unittest discover -s tests/local -t . -v` | Python 3.12.10／SQLite 3.49.1 | **87 项，0 skip，exit 0**（55.578s；`local-py312.log`） |
| 2 | `backend/.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests/local -t . -v` | Python 3.14.7／SQLite 3.50.4 | **87 项，0 skip，exit 0**（76.230s；`local-py314.log`） |
| 3 | `python -X utf8 -m unittest tests.unit.test_i3_content_validation tests.unit.test_security tests.unit.test_calendar_boundaries tests.unit.test_i3_api_schemas tests.unit.test_i5_export_read_service -v` | Python 3.14.7 | **108 项，exit 0**（0.576s；`regression-v1.log`） |

分布（87 项）：`test_migrations` 18、`test_daily_plans` 16、`test_initialize` 13、`test_transactions` 10、`test_guards` 10、`test_calendar_dates` 7、`test_concurrency` 7、`test_paths` 5、`test_restart` 1。两环境依赖一致：SQLAlchemy 2.0.54、Alembic 1.20.0、FastAPI 0.141.1、Pydantic 2.13.5、chinesecalendar 1.11.0、Uvicorn 0.53.0、Starlette 1.6.0；`pyproject.toml`／`uv.lock` SHA256 与审阅 §3 相同（`E5F9…8961`／`CC58…5495`），未新增／升级依赖、未改锁、未下载解释器。

### 10.5 临时证据位置

`%TEMP%\kgm-d1a-r3r4-20261013\`（临时路径不保证长期留存，关键结论以本文为准）：`local-py312.log`、`local-py314.log`、`regression-v1.log`、`versions-dump.py`、`r3-probe.py`、`r3-before-fix-record.txt`、`r4-probe.py`、`r4-before-fix-out/err.txt`（含修复前 `ResponseValidationError` 泄漏原文）、`r4-after-fix-out/err.txt`、`mutation-r3.py/.log`、`mutation-r4.py/.log`、`summary.json`、`source-hashes.json`。

### 10.6 遗留与未验边界

- 本轮修改与本地复跑完成，**尚未经 Codex 复审**；不得据此写成 R3／R4 已关闭、D1A 审阅通过或可进入 D1B。
- 受支持 CLI 明确为在 `backend` 目录运行 `python -m alembic -c alembic-local.ini upgrade head`；从其他工作目录使用相对 INI 不在支持范围（去掉 `%(here)s` 的直接代价；程序入口不受影响）。该点需与 D1B 打包／安装位置设计一并复核。
- 环境差异仍成立：原任务要求 3.12.10 与 `uv sync --locked`，初次实施为 3.14.7 与 `uv sync --frozen`；本轮按要求以已有的 3.12.10 做主复跑、3.14.7 做兼容复跑，未销毁／重建环境。
- R4 的严格 null 契约只针对 D1A 手工内容；未引入 AI 基准生成／迁移，未来需要时另走规格与迁移。
- 未重跑 D0 GUI／合成 Word、v1 integration（MySQL）、旧远程／夹具、真实 AI；未读取旧 `.env`／密钥；未提交／推送／部署。
- 学期范围变更后的已有计划入口、多学期维护、桌面页面、离开自动保存、配置维护与 Word 仍属 D1B。

## 11. D1B 实施记录（2026-10-14 开始）

统一任务入口见[当前任务](../tasks/current.md)；按 B0–B5 顺序实施并分别记录。以下各节只记录实际执行的事实；自动检查、真实 GUI／文件验证与产品验收分列，不把准备或局部结果写成 D1B 验收完成。

### 11.1 B0 统一运行时（通过）

依据[技术核查 §8](desktop-d1-technical-review.md#8-d1-统一运行时准备方案2026-10-14)文件清单与命令实施。证据目录：`%TEMP%\kgm-d1b-runtime-aed3e6cf\`（含 `b0-summary.json`、各命令 stdout/stderr 日志、`backend-baseline.txt`、前后散列与测试日志；临时路径不保证长期留存，关键结论以本节为准）。

**声明与文件（新增／修改）：**

| 文件 | 改动 |
| --- | --- |
| `backend/.python-version` | `3.14` → `3.14.7` |
| `desktop/.python-version` | 新增 `3.14.7` |
| `desktop/requirements-d1.in` | 新增；仅桌面／测试／打包输入（pywebview 6.2.1、pythonnet 3.2.1、clr-loader 0.3.1、pyinstaller 6.22.3、pyinstaller-hooks-contrib 2026.8、pytest 8.4.2、httpx 0.28.1、proxy-tools 0.1.0） |
| `desktop/requirements-d1-build-constraints.txt` | 新增；仅 `setuptools==84.0.0` |
| `desktop/requirements-d1.lock.txt` | 新增；单次求解的完整含 hash 安装锁（46 项） |
| `.gitignore` | 增加 `.venv-d1/` |

`backend/pyproject.toml`、`backend/uv.lock` 未改动；前后 SHA-256 均为 `E5F948…8961`／`CC589C…5495`，`Compare-Object` 无差异。

**命令、exit code 与结果（专用 PowerShell 会话；`APP_DISABLE_DOTENV=1`、`PYTHONIOENCODING=utf-8`）：**

| 步骤 | 命令 | 结果 |
| --- | --- | --- |
| 解释器核对 | `C:\Python314\python.exe` 断言 3.14.7／win-amd64／64bit／`Py_GIL_DISABLED=0` | exit 0；SQLite 3.50.4；`_base_executable=C:\Python314\python.exe` |
| 业务约束导出 | `uv export --project backend --locked --no-dev --no-emit-project --no-hashes …` | exit 0；27 包（26 发行包＋项目条目） |
| D1 统一求解 | `uv pip compile backend/pyproject.toml desktop/requirements-d1.in --constraints … --build-constraints … --python-version 3.14.7 --python-platform x86_64-pc-windows-msvc --generate-hashes …` | exit 0；Resolved 46 packages in 15.26s |
| 锁与业务基线比对 | Python 比对片段（tech review §8.3） | `business_count=26`、`missing=[]`、`changed={}`；新增 20 项（见下） |
| 环境创建 | `uv venv desktop\.venv-d1 --python C:\Python314\python.exe --no-project --no-python-downloads --no-managed-python` | exit 0（目标原先不存在，未覆盖任何目录） |
| 安装 | `uv pip sync desktop/requirements-d1.lock.txt --require-hashes --build-constraints … --only-binary <45 项非 proxy-tools> --strict …` | exit 0；仅 `proxy-tools==0.1.0` 为已审查源码制品（sdist SHA-256 `ccb375f1…8010`），其余 45 项均 wheel |
| 依赖检查 | `uv pip check --python desktop/.venv-d1/Scripts/python.exe` | exit 0（无不相容输出） |
| 发行版核对 | 锁内 46 项逐个与 `importlib.metadata` 比对 | `DIST-CHECK-OK`；环境解释器／基解释器／SQLite：`desktop\.venv-d1\Scripts\python.exe`／`C:\Python314\python.exe`／3.50.4 |
| 导入矩阵 | `import fastapi,uvicorn,sqlalchemy,alembic,pydantic,lxml,chinese_calendar,webview,clr,clr_loader,PyInstaller` | exit 0 |
| 完整 D1A | `desktop/.venv-d1/Scripts/python.exe -X utf8 -m unittest discover -s tests/local -t . -v`（cwd `backend`） | **87 项，0 skip，exit 0**（62.809s；日志 `local-d1b0.log`） |
| 相关回归 | 同解释器 `-m unittest tests.unit.test_i3_content_validation tests.unit.test_security tests.unit.test_calendar_boundaries tests.unit.test_i3_api_schemas tests.unit.test_i5_export_read_service -v` | **108 项，0 skip，exit 0**（0.353s；日志 `regression-d1b0.log`） |

**新增 20 项及来源（均为桌面／测试／打包传递依赖，非业务版本变更）：**

- pywebview 传递：`bottle`、`proxy-tools`。
- pythonnet／clr-loader 传递：`clr-loader`。
- PyInstaller 传递：`altgraph`、`packaging`、`pefile`、`pywin32-ctypes`、`setuptools`（构建约束固定 84.0.0）。
- pytest 传递：`colorama`、`iniconfig`、`pluggy`、`pygments`。
- httpx 传递：`certifi`、`httpcore`。
- 直接声明的测试／打包包：`pyinstaller`、`pyinstaller-hooks-contrib`、`pytest`、`httpx`。

**边界：** 未改动 `backend/.venv`、`desktop/.venv`、D0 包与任何旧证据；未安装系统组件／WebView2／Office；未执行发行、远程操作或真实数据操作。B0 通过仅表示该解释器组合可运行并通过既有测试，不表示桌面业务、Word 或打包已通过。

### 11.2 B1 配置与多学期数据／API（完成，待 Codex 复审）

依据[D1 规格](../specs/desktop-manual-daily-plan.md) §9–10 实施。沿用 D1A 的隔离、约束与事务保证；未重写既有 revision、旧 MySQL 模型／迁移或 D1A 通过路径。

**改动文件：**

| 文件 | 改动 |
| --- | --- |
| `backend/app/local/models.py` | `LocalSettings.config_version`（CHECK ≥1）；新增 `local_config_operations` 回执表（request_id 唯一、输入指纹、结果 JSON、配置版本、时间） |
| `backend/migrations_local/versions/20261014_0003_local_config_maintenance.py`（新增） | D1A 升级初值 1 的 `config_version` 列＋回执表；既有 revision 不动；downgrade 明确拒绝 |
| `backend/app/local/config_service.py`（新增） | 五类 change 的规范化、预览、候选日历、影响事实、令牌绑定、应用事务、回执与结果查询 |
| `backend/app/local/config_tokens.py`（新增） | 每进程内存密钥 HMAC-SHA256 预览令牌；10 分钟有效期；重启即失效 |
| `backend/app/local/profile_service.py` | 多学期 context（`as_of_date`、`terms`、按日期解释的 `term`／`calendar_revision`）；初始化重试读回当前配置；`config_version=1` 初始化 |
| `backend/app/local/api.py` | `context?date=`、`/terms/{term_id}/daily-plans`、`/config/preview`、`/config/apply`、`/config/operations/{request_id}`、创建计划 `expected_config_version` |
| `backend/app/local/schemas.py` | context 增量字段、学期列表、配置请求／响应模型（discriminated union、extra=forbid、严格整数版本） |
| `backend/app/local/errors.py`／`app.py` | `error.details` 增量；新增 TERM_NOT_FOUND／TERM_OVERLAP／CONFIG_VERSION_CONFLICT／CONFIG_PREVIEW_STALE／CONFIG_PREVIEW_EXPIRED／CONFIG_REQUEST_CONFLICT／CONFIG_OPERATION_NOT_FOUND |
| `backend/app/local/calendar_read.py` | 学期外日期仍返回 `existing_plan_id`（已有记录入口独立于资格） |
| `backend/app/local/daily_plan_service.py` | 学期解析按日期跨全部学期；创建时锁内校验 `expected_config_version`（先打开已有记录）；按已存 term_id 的旧学期列表入口 |
| `backend/tests/local/`（新增 `test_config.py`；适配 `test_initialize`／`test_restart`／`test_migrations`／`test_calendar_dates`／`test_paths`／`worker.py`） | 31 项配置／多学期／协议测试；既有断言按新 context 语义与 0003 head 适配（多学期、`terms` 列表、旧的旧 head 数据改用真实旧 schema 原始行构造，原子性／并发／拒绝断言保留） |

**实现要点与工程决定（规格未逐字固定的细节，请在复审确认）：**

1. 预览令牌载荷绑定：配置版本、规格化 change、候选日历摘要、完整前提摘要（资料／班级／全部学期范围与指针／受影响修订逐日行／相关计划集合及版本）与完整影响事实摘要；应用在锁外重建候选并逐一比对，锁内重查版本＋前提摘要后才写入，影响减少也返回 `CONFIG_PREVIEW_STALE`。
2. `not changed` 判定：profile／class 按字段相等；term_update 按名称＋起止日期相等（仅改名不产生修订）；override 按（override 状态，原因）相等；term_create 恒为 changed。`changed=false` 的 apply 只写幂等回执（status=unchanged，config_version 不变）。
3. `impact.retained_header_count` 取当前有效计划总数（配置维护从不改写表头）；profile／class 的 `affected_plans` 列出全部保留旧表头的真实计划；范围／日历维护只列出状态、周次或解释实际变化的记录。`counts.existing_plan_count` 对资料／班级为全部计划，对学期／例外为相关日期窗口内的计划。
4. 日历差异（`calendar_diff`）仅在字段实际不同时产生项：仅改名 → 空；扩围 → 新纳入日期以 `outside_term` 为前值；缩围 → 移出日期以 `outside_term` 为后值；例外项含原因前后值。
5. `calendar_override` 仅复制既有逐日行并改动目标日；不调用日历库（库故障时仍可配置例外，测试已覆盖）；修订头沿用旧 `library_version`。范围变更时新纳入日期才建立库基础值。
6. 学期／例外应用以真实历史行验证：交集保留基础值、库版本与例外；缩后再扩的新纳入日期 `override=null`；旧修订与旧例外保留、不静默恢复。
7. 首次设置（initialize）响应与 `GET /context` 默认均以宿主本地日期为 `as_of_date`；设置学期的起止日期不含今天时 `term`／`calendar_revision` 为 null 而 `status=ready`。初始化同 key 重试返回当前配置（维护不回滚）。
8. `POST /daily-plans` 先打开当前班级同日已存记录（即使 `expected_config_version` 过期）；仅无已存记录时校验版本并在写锁内解析当前配置。
9. 回执查询（`GET /config/operations/{id}`）不返回 `replayed` 字段；重复 apply 的重放响应附加 `replayed:true`。

**验证（专用 D1 环境 `desktop/.venv-d1/Scripts/python.exe`，cwd `backend`，`APP_DISABLE_DOTENV=1`、`PYTHONIOENCODING=utf-8`、`-X utf8`）：**

| 命令 | 结果 |
| --- | --- |
| `python -m unittest discover -s tests/local -t . -v` | **118 项，0 skip，exit 0**（76.510s；D1A 87 项＋B1 新增 31 项） |
| `python -m unittest tests.unit.test_i3_content_validation tests.unit.test_security tests.unit.test_calendar_boundaries tests.unit.test_i3_api_schemas tests.unit.test_i5_export_read_service -v` | **108 项，0 skip，exit 0**（0.390s） |

分布（118 项）：`test_config` 31、`test_migrations` 18、`test_daily_plans` 16、`test_initialize` 13、`test_guards` 10、`test_transactions` 10、`test_calendar_dates` 7、`test_concurrency` 7、`test_paths` 5、`test_restart` 1。

**B1 覆盖要点：** 多学期 context 与按日期解释；初始化重试不回滚维护；资料／班级维护保留旧表头与内容版本、ID 不变；学期新增端点重叠拒绝、范围修改的修订与交集保留、移出计划的日历入口／列表／继续编辑；例外设置／改原因／撤销与缩后再扩不恢复旧例外；未知年份手工配置；库故障与 unknown 分离；版本冲突 details；令牌篡改／过期／错配；相关计划新建或保存后预览失效（含影响数量不变但版本变化）；另一配置提交后冲突；同 request_id 并发只提交一次；回执重放／冲突／查询；注入故障全量回滚；`config_version` CHECK；真实 HTTP＋真实文件库，未使用 mock 或内存库。

### 11.3 B2–B3 真实页面、保存与宿主（完成，待 Codex 复审）

按规格 §11 新增独立 D1 前端与宿主入口；未挂载旧账号／管理员／周投影／MySQL 入口，未以 D0 探针页面代替业务页面。

**前端（`frontend/`，仅新增 D1 文件，不改旧 `src/App.vue` 等云端入口）：**

| 文件 | 职责 |
| --- | --- |
| `frontend/d1.html`、`vite.d1.config.ts`、`src/d1/main.ts` | D1 独立入口，构建输出 `build/desktop-d1/frontend`（不与 D0／旧输出共用） |
| `src/d1/client.ts` | 同源 fetch 封装、内存会话头、`{error:{code,message,details?}}` 类型化错误（保留 details） |
| `src/d1/bridge.ts` | 宿主桥接：`get_bootstrap`／`page_ready(bridge_protocol=1)`；`complete_close`＋`get_close_state` 回包丢失回退；`onRequestClose`／`onCloseAborted` 注册；协议版本不匹配显示错误 |
| `src/d1/leave.ts` | 统一离开协调器：同一目标共享 Promise、不同目标拒绝排队、保存后再次核对 dirty 与身份、失败／冲突／新输入留页 |
| `src/d1/editor.ts` | 可保存值基线（`serverToForm`→`buildAdoptedContent`）、raw 空值／换行正规化、dirty 比较、临时 key 晚到输入 ID 回填、显式重提的失效 ID 摘除（不猜 ID） |
| `src/d1/App.vue` | 应用壳：首次设置／工作台／编辑器／设置在应用壳内切换；关闭握手（先否决、异步保存、完成／取消／查询、超时只撤销未放行请求、closing 后不因超时解锁）；设置草稿不得借关闭绕过确认 |
| `src/d1/views/SetupView.vue` | 首次设置（姓名／班级＋年级／学期名＋起止日期／园所可空）；request_id 生命周期内复用，结果不明重试同 key；ALREADY_INITIALIZED 读回既有资料 |
| `src/d1/views/WorkbenchView.vue` | 默认本机当前月；学期筛选定位起始月并显示该学期全部已保存计划（按已存 term_id）；已有记录入口优先于创建资格；点击可创建日期先确认再创建，浏览不自动创建；请求序号防旧响应覆盖 |
| `src/d1/views/EditorView.vue` | 真实栏目表单（复用 `daily-plan-content.ts` 纯映射，去掉周摘要／账号）；loading／ready／saving／conflict／save_failed＋create_confirmation；IME 组合结束并 Vue 更新后才锁定；单在途保存；epoch 与临时 key 晚到输入保护；409 显式放弃／比较后重提；结果不明显式核对不自动重发 |
| `src/d1/views/SettingsView.vue` | 资料／班级／学期／逐日例外维护，全部经预览（before／after、日历差异、完整影响清单）确认后应用；配置版本冲突重读；编辑即废弃旧预览；未确认草稿阻止离开与关闭 |
| `src/d1/views/ExportDialog.vue` | 日／周／月／自选范围的 409 缺项确认闭环、`expected_context` 原样回传、原生保存结果状态区分（见 §11.4） |
| `src/d1/d1.test.mjs` | Node 纯逻辑回归：离开协调器、dirty 基线、晚到输入回填、失效 ID 摘除、关闭结果解析、桥接等待 |

**宿主（`desktop/`，保留 D0 全部文件与行为）：**

| 文件 | 职责 |
| --- | --- |
| `d1_main.py` | D1 入口：资源解析、WebView2 检查、注入合成数据目录、本机服务与就绪等待、窗口与关闭处理器、退出清理；`--selftest --phase first/restart/verify` 经真实窗口 JS 驱动真实页面函数完成打包验证 |
| `d1_host_api.py` | `CloseCoordinator`（pending／closing／canceled；一次性放行重入消费；30s 只撤销未放行请求；destroy 失败撤销许可并通知）；受限 `save_docx`（操作 ID＋文件名／载荷 SHA256 绑定、30MiB／base64／DOCX 校验、原子替换提交点、saved／canceled／failed／unknown）与只读 `get_save_result`；不暴露任意路径或 D0 autosave_target |
| `d1_server.py` | 复用 `create_local_app` 的会话／Host／Origin 防护，另挂同源 D1 前端壳 |
| `d1_paths.py` | D1 资源定位（前端构建、冻结包内前端）；验证用预授权保存目录仅由宿主环境变量控制，不经 JS |
| `tests/test_d1_close.py`、`tests/test_d1_host_save.py`、`tests/test_d1_paths.py` | 关闭状态机（重复／迟到 ack、超时不撤销已放行、destroy 失败）、保存绑定／缓存／上限／占用失败重试／替换提交点、路径解析，共 24 项 |

**验证（D1 环境，命令与结果）：**

| 命令 | 结果 |
| --- | --- |
| `npm --prefix frontend ci --no-audit --no-fund` | exit 0（68 包，未新增／升级依赖） |
| `npm --prefix frontend run typecheck` | exit 0（vue-tsc 无错误） |
| `node frontend/src/d1/d1.test.mjs` | `OK D1 pure-logic regression tests`（exit 0） |
| `npx vite build --config vite.d1.config.ts`（frontend） | exit 0；输出 `build/desktop-d1/frontend/d1.html`＋assets |
| `desktop/.venv-d1/Scripts/python.exe -X utf8 -m pytest desktop/tests -q` | **116 passed**（D0 92 项未受影响＋D1 宿主 24 项） |

**边界与未验：** 真实 WebView2 窗口流程见 §11.5（B5 包内实测）；本节自动检查不等于真实窗口验收。D0 既有 92 项测试通过，未改动 D0 文件。

### 11.4 B4 Word 与原生文件交付（完成，待 Codex 复审）

按规格 §12 增加本地导出读取／路由（`backend/app/local/export_service.py`＋`/api/exports/daily-plans`）与 D1 导出 UI／宿主保存；复用固定模板、映射与生成器（`word_export_mapping.py`／`word_export_docx.py` 未改动），未挂载旧认证／MySQL 导出路由。

**实现要点：**

1. 一次显式读事务内完成：当前班级按实际 `plan_date` 选记录（含旧学期、移出范围、非上课日记录）、校验并物化当前内容版本、计算完整缺项 facts 与 `expected_context`（class_id、from/to、按日期与 ID 排序的 `{plan_id,content_id,content_version}` 清单、完整缺项 JSON 的 SHA256 与数量），随后结束事务再映射／生成 DOCX；生成失败 500 `EXPORT_GENERATION_FAILED`，不含 traceback／路径。
2. `ack_missing=true` 而缺完整 context 一律 422；确认值必须完全相符，选集、版本或完整缺项任一变化（含缺项清空）返回 409 `context_changed` 并要求重新确认；首次无缺项直接生成。
3. 范围：单日／周／月／自选闭区间，按实际选中份数最多 31 份（第 32 份 422 `EXPORT_LIMIT_EXCEEDED`），日期升序、每份新页；0 份 404 `EXPORT_NOT_FOUND`；无 `split_baseline` 的手工计划按最终内容导出并返回 `X-Export-Warnings`（`no_split_baseline`，无伪造标红基准）；导出不修改计划、不增加内容版本。
4. 前端确认闭环绑定 `expected_context` 原样回传；dirty 导出提示不改动未保存输入；原生保存经受限 `save_docx`（操作 ID＋指纹、30MiB、脱敏失败原因、取消不报成功、结果不明可查询不自动重写、取消／失败后新 ID 重试）。

**验证：**

| 命令 | 结果 |
| --- | --- |
| `python -m unittest discover -s tests/local -t . -v`（含 `test_export` 11 项） | **129 项，0 skip，exit 0**（83.510s） |
| `python -m unittest tests.unit.test_i3_content_validation tests.unit.test_security tests.unit.test_calendar_boundaries tests.unit.test_i3_api_schemas tests.unit.test_i5_export_read_service -v` | **108 项，exit 0** |
| `pytest desktop/tests`（D1 宿主保存／原子替换／占用失败／结果缓存） | 116 passed |

**B4 覆盖要点：** 单日／月／多份导出的真实 DOCX（ZIP 可解析、模板日期与周次、每份分页）；移出学期后仍导出；0／31／32 份边界；缺项确认、context 变化（缺项清空仍重确认）、ack 缺 context 422；生成失败脱敏；同步屏障证明读事务先物化 DTO、生成期间并发保存已提交而导出内容仍对应旧快照；导出不产生版本或更新时间变化。

**未验（宿主原生项需人工／B5）：** 真实原生对话框的取消、文件名输入与占用文件重试（占用失败在宿主单测中以真实文件锁复现，见 §11.5 包外流程）；Word／WPS 逐页查看。

### 11.5 B5 目录包与交付验证

**构建（最终版）：** `desktop/.venv-d1/Scripts/python.exe -X utf8 desktop/build_d1.py --skip-frontend --hash-out <evidence>\package-hashes.json`（前端已先以 `npx vite build --config vite.d1.config.ts` 构建），exit 0；输出 `build/desktop-d1/package/KGNext-D1Verify`（onedir，137 个文件；`KGNext-D1Verify.exe` 14,679,519 字节，SHA256 前 16 位 `5ad0dd1dff1f12d3`；完整逐文件散列见证据目录 `package-hashes.json`）。包内已核对：`alembic-local.ini` 1 项、`migrations_local` 12 项、`app/assets/word_templates/daily_plan.docx`（`99008f92…`）与前端 `d1.html`＋assets；D0 构建脚本与旧包未改动。

**仓外运行（真实 WebView2 窗口，4 个独立进程串行，同一合成数据目录）：** 整个 onedir 目录复制到 `%TEMP%\kgm-d1b-runtime-aed3e6cf\package-outside\KGNext-D1Verify`，从不同 cwd（证据目录）启动；数据目录 `%TEMP%\...\packaged-data`、导出目录 `%TEMP%\...\packaged-saves`（宿主内验收专用预授权目录，仅环境变量控制，不经 JS）。每个阶段使用 `--selftest` 经真实页面函数完成操作；汇总 `b5-summary.json`：

| 进程 | 阶段与操作 | exit |
| --- | --- | --- |
| 1 | 首次设置（姓名／班级／学期）→ 创建工作台日期计划 → 空内容按周导出（`空` 样本）→ 键入代表性内容并保存（v1→v2）→ 单日导出 → 返回工作台（离开保存链路） | 0 |
| 2 | 读回第一次内容并断言一致 → 追加长内容保存（v2→v3）→ 创建并保存第二个日期计划 → 自选闭区间导出两份（`长内容／多份` 样本） | 0 |
| 3 | 再次读回并断言版本／原文一致 → 单日导出 | 0 |
| 4 | 在编辑器保留未保存输入后关闭窗口 → 关闭握手自动保存（v3→v4）后真实销毁 | 0 |

核对结果：数据库 `local_alembic_version = 20261014_0003_local`（包内 Alembic 正常迁移）、计划 2 份、内容历史 6 条、日历修订 1 个、`PRAGMA foreign_key_check` 为空；日期版本 `2026-09-15→v4`（含“关闭自动保存”文本）、`2026-09-16→v2`；四个进程全部正常退出，结束时无 `KGNext-D1Verify.exe` 残留进程、`netstat` 无该实例监听端口（`ports_before/after`、`during/after tasklist` 均已保存）。

**Word 样本与页面核对：** 样本快照（`sample-snapshots/{first,restart,verify}`，平整副本 `word-samples/`）：空内容 1 份（14,021 B）、代表性 1 份（14,038 B）、长内容＋多份（2 计划、5 页、14,443 B，验证每份新页）、长内容单份（14,092 B）。使用真实 Microsoft Word（版本 16.0）只读打开全部 4 个文件并统计：**2／2／5／3 页**、字数 185／193／1987／1794，全部为有效 DOCX（ZIP＋document.xml），证明文件可被 Word 正常解析；**逐页的页面视图／打印预览人工目视核对仍待用户或后续审阅执行**（最短步骤：打开 `word-samples/` 四个文件，在 Word“视图→页面视图”与“文件→打印”预览逐页核对分页、表头与末页）。

**首次失败与修复记录（保留，不重写）：** 最早两次打包窗口运行未通过：①页面启动与 pywebview 注入 `window.pywebview.api` 存在竞态，`bootstrap()` 过早将“尚未注入”判为致命错误，且驱动在 `evaluate_js` 永久等待时无界；②编辑器“返回日历”的 run 回调未真正切换视图；③同类样本文件名覆盖（空／代表性互相覆盖）；④关闭握手在驱动异常路径下不销毁窗口。修复：`bootstrap()` 改为等待 `get_bootstrap` 实际出现（12s 上限）后才判定宿主缺失；驱动 `evaluate_js` 全部改为带 25s 上限的线程调用并新增看门狗“驱动完成但 45s 内未能销毁即显式失败退出”；`leaveForAction` 在保存确认后执行真实导航；空内容样本改按周导出、并按阶段快照样本；新增 dirty-close 阶段与关闭等待导出、设置草稿守卫。修复后连续两次完整 B5 通过（中间一次为导出等待守卫加入前的版本，均记录于 `build-d1.log`／`build-d1-final.log`／`b5-run.log`／`b5-run-final.log`）。

**未验边界（如实保留）：** 干净机器、Windows 10、WPS、其他 DPI、多显示器与用户本人操作体验未验证；原生另存为对话框的人工操作（自选文件名、取消对话框、占用文件的真实弹窗重试）未在本轮自动执行——占用失败后的重试链路已在宿主单测中用真实文件锁复现（失败保留原文件、解除后新操作成功），取消路径由“取消不报成功”的单测与页面状态机覆盖，但真实对话框交互需人工执行；AI、WebDAV、删除／恢复、多班与发行均不在本轮。上述未验项不因本包通过而改变。

## 12. D1B 复审问题定点修复与补验（2026-10-15）

依据[审阅 §9](desktop-d1-review.md#9-d1b-实施复审2026-10-15)与[当前任务](../tasks/current.md)，逐项修复 R1–R14，并按“先定点回归、再完整套件、再真实窗口、再重新打包与 Word 样本”的顺序补验。修复、自动检查、真实 GUI／文件、产品验收分列记录；既有审阅项不自行写成已获 Codex 关闭。

### 12.1 改动文件与逐项映射

| 项 | 根因与修复 | 主要文件 |
| --- | --- | --- |
| R1 | 关闭许可发出后才冻结、查询失败按 stay 解锁、迟到回包可覆盖 closing。改为：完成 IME／保存与 clean 复核后、发送 `allow=true` **之前**冻结（`freezeForClose`）；`completeCloseWithFallback` 返回 `closing/canceled/unknown/pending/unconfirmed` 五值；查询失败／未答复／pending 保留冻结与请求 ID；仅宿主对本 ID 明确 canceled/unknown 才解锁留页；`onCloseAborted` 仅接受本 ID，最终 closing 不被迟到通知撤销（destroy_failed 例外）；新关闭请求 ID 到达时旧未决冻结按协议释放 | `frontend/src/d1/bridge.ts`、`frontend/src/d1/App.vue` |
| R2 | `saveCurrent` 未检查 indeterminate，普通离开重发 PATCH。改为未决时直接返回 `indeterminate`（不发送 PATCH），只经显式“读取服务端核对”或冲突重提流程继续；清除未决后才允许新提交 | `frontend/src/d1/views/EditorView.vue` |
| R3 | 应用成功后的全量表单重置清掉其他草稿。改为 `pendingAppliedMerge`：重载到达时仅对“仍等于本次提交值”的字段采用新基线（逐字段），保留其他区域草稿与应用期间的新输入；term_create 只清理本次新学期的草稿字段并列出新行 | `frontend/src/d1/views/SettingsView.vue` |
| R4 | 迟到预览响应恢复旧确认。改为输入版本 `inputSeq`（输入／取消／context 更新／卸载均递增）＋配置版本＋`changeStillBound`（按当前表单重建 change 比较）双重绑定；响应与提交前都复核，过期响应只静默丢弃（版本冲突仍触发重读） | `frontend/src/d1/views/SettingsView.vue` |
| R5 | 设置页“返回工作台”误绑到 settings 路由。改为 `onSettingsLeave` → `leaveForAction('calendar')`，未确认草稿阻止离开的规则保留 | `frontend/src/d1/App.vue` |
| R6 | 导出只有单一 busy：pending/unknown 后清 busy 可再次保存或关窗；生成中改范围留下 busy=true。改为 `generating`（HTTP 读取／生成）与 `nativeBusy`（原生保存互斥）分离：范围改变安全失效生成并恢复操作，迟到响应不开框；pending/unknown 保留 ID 与互斥、只读查询、禁止再次导出与关窗；unknown 经“我已核对目标文件”显式确认后才允许新操作；base64 转换 await 边界复核序号；原生阶段禁用范围控件与对话框关闭 | `frontend/src/d1/views/ExportDialog.vue` |
| R7 | rename-only／no-op 时 `revision=None` 断言失败 500。改为候选解释在无新修订时使用当前解释 | `backend/app/local/config_service.py` |
| R8 | 跨中间学期移动时中间学期日期未物化被当缺行。改为按旧新范围包络物化所有相交学期的当前修订；比较前值用完整当前解释，中间未改变学期不产生虚假差异或影响记录 | `backend/app/local/config_service.py` |
| R9 | 例外候选直接克隆缺行修订。新增完整性校验：当前修订必须精确覆盖学期范围，缺行即 `LOCAL_STORAGE_ERROR` 拒绝预览／应用（不克隆、不静默重建），预览、应用与锁内重建同路径生效 | `backend/app/local/config_service.py` |
| R10 | 非 ASCII 令牌 `encode("ascii")`／`compare_digest` 抛未转换异常 500。改为先做 ASCII 编码校验，非法即 422 `VALIDATION_ERROR`；HMAC、期限、完整影响与幂等检查不变 | `backend/app/local/config_tokens.py` |
| R11 | 原生保存按 ID 记录但未全局互斥；关闭可越过在途保存。新增跨 ID 全局保存互斥（第二个操作等待）、在途计数 `_save_in_progress`；关闭协调器 `complete(allow=true)` 与放行标志消费在保存未完成时撤销并通知 `save_in_flight`，绝不销毁；同 ID 同载荷继续共用 pending／缓存结果 | `desktop/d1_host_api.py`、`desktop/d1_main.py` |
| R12 | 受限桥递归暴露内部协调器与通知方法；业务入口未验证握手。内部成员全部改私有（`_close_coordinator`／`_notify_*`）；新增 `BRIDGE_ALLOWED_ENDPOINTS`（6 个约定入口）；`save_docx`、`get_save_result` 未完成 `page_ready` 握手时拒绝 | `desktop/d1_host_api.py`、`desktop/d1_main.py` |
| R13 | 仅检查 PK 前缀。新增 `validate_docx_bytes`：有效 ZIP＋`[Content_Types].xml`＋`word/document.xml` 且可解码，任何非法输入在对话框／替换提交点之前拒绝，不覆盖旧目标；成功样本改用真实最小 DOCX | `desktop/d1_host_api.py`、`desktop/tests/test_d1_host_save.py` |
| R14 | 超时回调未绑定请求 ID。改为 `_on_timeout(bound_request_id)` 持锁复核自身 ID／状态，旧回调不能取消新请求或已放行 closing | `desktop/d1_host_api.py` |

**修复轮新发现并修复（不在 R1–R14 列表内）：** `frontend/src/d1/main.ts` 未注册 Element Plus（D0 与旧入口均有 `app.use(ElementPlus)`），真实窗口把 `el-*` 渲染为未解析自定义元素，全部表单控件不显示。修复为与既有入口一致。真实窗口 DOM 证据：修复前 150 元素／0 textarea／0 `el-input`，修复后 419 元素／19 textarea／8 `el-input`（`fix_ime_dom`）。该缺陷此前自动套件与钩子驱动均未覆盖，属本轮补验直接发现。

### 12.2 自动检查（最终一轮命令与结果）

后端命令工作目录 `backend`，环境 `APP_DISABLE_DOTENV=1`、`PYTHONIOENCODING=utf-8`，解释器 `desktop/.venv-d1/Scripts/python.exe`（CPython 3.14.7／Windows x64／SQLite 3.50.4）加 `-X utf8`；前端在 `frontend` 下执行；桌面在 `desktop` 下执行。

| # | 命令 | 结果 |
| --- | --- | --- |
| 1 | `python.exe -X utf8 -m unittest discover -s tests/local -t .` | **133 项，0 skip，exit 0**（81.690s；修复前基线 129，新增 R7–R10 回归 4 项） |
| 2 | `python.exe -X utf8 -m unittest tests.unit.test_i3_content_validation tests.unit.test_security tests.unit.test_calendar_boundaries tests.unit.test_i3_api_schemas tests.unit.test_i5_export_read_service` | **108 项，0 skip，exit 0**（0.339s） |
| 3 | `.venv-d1/Scripts/python.exe -X utf8 -m pytest tests/ -q -p no:cacheprovider` | **129 passed，2 warnings，exit 0**（修复前基线 116） |
| 4 | `npm run test:d1` | 纯逻辑套件 OK ＋ **21 项组件级异步回归**（实际 SFC setup＋真实 Vue refs／watch＋受控桥，exit 0） |
| 5 | `npm run typecheck`、`npm run build:d1` | 均 exit 0；构建输出并入最终包 |

新增回归覆盖：R7 有计划改名／无变化、R8 跨中间学期移动与虚假影响反例、R9 缺行预览／应用拒绝且零副作用、R10 Unicode／非法令牌 422；宿主 R11（不同 ID 串行／同 ID 共用与冲突／在途探针）、R12（暴露清单与握手拒绝）、R13（PK 假载荷、缺部件、截断 ZIP、旧目标保护）、R14（迟到超时回调 A/B 交错）；前端 R1（冻结先于许可、失联保留锁、pending、明确 canceled/unknown、迟到撤销）、R2（未决不重发）、R3/R4/R5（多区草稿、迟到预览、绑定复核、返回路由）、R6（pending 保留互斥、unknown 显式核对、范围竞态、桥回复丢失、终态释放）。测试全部自注入临时目录，未在父会话强加 `KGM_LOCAL_DB_PATH`。

### 12.3 真实窗口补验（修复回归阶段）

新增 `--selftest --phase fix-regression` 驱动真实 WebView2 页面执行：无修改保存不产生版本 → 全部真实表单栏目写入并 HTTP 核回 → IME 组合中输入保存等待 `compositionend` 且保存最终文本 → 外部持写锁时保存 5.66s 后 `503` 留页、释放后重试成功 → 外部更新后 `409` 留稿、显式重提获得新组／游戏 ID 且文字不丢 → 设置多区草稿跨应用保留、配置版本 +1 → 切日期前输入先保存后离开 → 真实导出经范围／缺项确认保存成功。

源码运行（`--frontend build/desktop-d1/frontend`）与最终包内运行（见 §12.4）均 exit 0，`checks` 全部为 true；写锁失败等待 5.66s、错误文案为“本地数据库正忙，请稍后重试”。关闭握手仍由既有 `dirty-close` 阶段在真实窗口执行（未保存输入 → 关闭请求 → 自动保存 v9→v10 → 真实销毁，宿主日志含 `complete_close(allow=True)` → `closing allowed (flag consumed)`）。

**首次失败与修正（保留）：** ① IME 步骤首次运行时 DOM 无任何 `<textarea>`、页面为 `el-*` 未解析元素——由此发现并修复 D1 入口未注册 Element Plus（§12.1 末段）；② 修复渲染后，首次按“组合中 dirty 即等待”的写法超时，原因是 Element Plus 在自身组合期间忽略 `input`、只在 `compositionend` 后提交最终值，属实现语义正确的边界；改为“组合前已有内容＋组合末段”，验证保存等待到 `compositionend` 且保存的是最终文本，两次失败仅存在于调用方步骤设计与渲染缺陷，产品语义不变；③ `word-verify` 首次 exit 3 是证据准备脚本以文本模式写期望原文产生 CRLF、与存档 `\n` 不符，修正后重跑通过（调用方失误，非产品缺陷）。

### 12.4 最终包与仓外运行

**构建：** `desktop/.venv-d1/Scripts/python.exe -X utf8 desktop/build_d1.py --skip-frontend --hash-out <证据>/package-hashes-final.json`，exit 0；输出 `build/desktop-d1/package/KGNext-D1Verify`，**137 文件**，`KGNext-D1Verify.exe` 14,689,690 字节、SHA-256 前 16 位 `f7c1a14f20eaf2d0`。与修复前包（`5ad0dd1d…`，已复制保留于 `build/desktop-d1/package/KGNext-D1Verify-pre-d1b-fix`）相比仅 EXE、`base_library.zip`、前端资产（新增 `index-BsmK-xyL.js`／`index-lYknSwL5.css`，移除旧两项）与 `d1.html` 变化；`alembic-local.ini`、`migrations_local`、模板未变。包内 `_internal` 含 `alembic-local.ini`、`migrations_local`、`frontend`、`app/assets/word_templates/daily_plan.docx`。

**仓外运行：** 整个 onedir 复制到 `%TEMP%\kgm-d1b-fix-20261015\package-outside-final\KGNext-D1Verify`，从证据目录启动，合成数据 `final\data`，预授权导出目录 `final\saves`（仅宿主环境变量控制，不经 JS）。5 个独立进程串行、全部 exit 0：

| 进程 | 阶段 | 结果 |
| --- | --- | --- |
| 1 | `first`（初始化→空内容按周导出→代表性内容保存 v2→单日导出→离开） | checks 全 true |
| 2 | `restart`（读回断言→长内容 v3→第二日期→两份导出） | checks 全 true |
| 3 | `fix-regression`（§12.3 全部场景，含 IME 与 DOM 渲染证据） | checks 全 true |
| 4 | `dirty-close`（关闭握手自动保存 v9→v10） | exit 0 |
| 5 | `verify`（读回 v10／原文一致→单日导出） | checks 全 true |

核对：`local_alembic_version = 20261014_0003_local`（包内迁移正常）、计划 2 份（v10／v2）、内容历史 12 条、审计 14 条、`PRAGMA foreign_key_check` 空、`journal_mode=wal`；全部进程正常退出，结束后 `tasklist` 无 `KGNext-D1Verify.exe` 残留。

### 12.5 Word 样本（最终包重新生成）

`final-word\samples`（先经 ZIP＋必要部件校验；页数／版式查看未执行）：

| 样本 | 字节 | SHA-256 前 16 位 |
| --- | --- | --- |
| 样本A-空内容-按周.docx | 14,021 | `1b3d4e21da0d7a7b` |
| 样本B-代表性内容-单日.docx | 14,042 | `0fac2db3049e4d4e` |
| 样本C-长内容-两份.docx | 14,446 | `87d77d7bdafab768` |
| 样本D-长内容-单日.docx | 14,096 | `f4903889afdea9fe` |

**未验：** Word／WPS 页面视图或打印预览逐页核对（分页、表头、末页）未执行；最短复验步骤：用 Word 打开上述 4 个文件，在“视图→页面视图”与“文件→打印”预览逐页核对并记录版本与页数。

### 12.6 未验边界与再次复审条件

1. **保持未验：** 真实原生另存为的人工操作（自选中文文件名、取消对话框、占用文件后的真实弹窗重试与解除后新 ID 重试）；Word／WPS 逐页查看；关闭超时／桥失联／再次关闭的**真实窗口注入**（现由组件级与宿主级回归覆盖，真实窗口未做故障注入）；设置预览乱序的真实窗口时序（组件级覆盖）；干净机器、Windows 10、WPS、其他 DPI、多显示器与教师本人体验；真实教师数据与旧远程资源未触碰。
2. **自动与包证据：** 133 本地、108 回归、129 桌面、前端 22 项与构建、真实窗口两轮（源码＋最终包）、最终包 137 文件身份与 5 进程仓外运行、4 份真实 DOCX 样本均已记录；`fix-regression` 为新增真实窗口回归阶段，后续 D1 包可复用。
3. **证据根：** `%TEMP%\kgm-d1b-fix-20261015\`（含 `package-hashes.json`／`package-hashes-final.json`、`fix-regression.json`、`final\` 与 `final-word\` 各阶段汇总、`run.log` 宿主日志、样本目录；临时路径不保证长期留存，关键结论以本节为准）。
4. **再次复审条件：** R1–R14 均有实现改动与可复跑回归，真实窗口与最终包证据就绪，具备交 Codex 独立复审的条件；产品验收、发行与后续切片不因本节自动成立。

## 13. D1B 剩余修复与补验（2026-10-15 第二轮，R1／R6／R11／R13／R15）

依据[审阅 §10](desktop-d1-review.md#10-d1b-修复后复审2026-10-15)与[当前任务](../tasks/current.md)，只继续 R1、R6、R11、R13 与新增 R15；已关闭的 R2–R5、R7–R10、R12、R14 保持历史结论，不重复派发。环境仍为 `desktop/.venv-d1`（CPython 3.14.7／Windows x64／标准 GIL、SQLite 3.50.4），未安装或升级依赖，未改 backend 业务声明／锁与 D0 环境。本节不自行写成 Codex 已关闭本轮修复。

### 13.1 改动文件与逐项映射

| 项 | 根因与修复 | 主要文件 |
| --- | --- | --- |
| R11 | `complete_close(allow=true)` 在 `destroy()` 同步重入后固定返回 `accepted=true/state=closing`，即使重入已因保存开始而撤销；撤销路径在同步 FormClosing 回调内直接 `evaluate_js` 通知页面。改为：`_destroy()` 返回后按当前请求 ID 读取真实状态并如实返回（重入撤销→`accepted=false/state=canceled`）；`handle_closing` 撤销时只改状态并在回调外由独立线程发送 `close_aborted`，绝不在 FormClosing 内等待 UI 线程 | `desktop/d1_host_api.py` |
| R1 | 迟到 `closing` 回包在撤销通知清 ID/解锁后仍可设 `closeFinalAllowed=true`，且旧回包可能污染新请求；关闭未决冻结只覆盖编辑器。改为：回包按请求 ID 复核当前 `activeCloseId`，已终态或已被替换的迟到回包只记录自身结论、绝不复活也不触碰新请求；`closeResolution` 单变量改为按请求 ID 的 `closeVerdicts`；非 close 导航在冻结（含最终放行前的未决）时一律拒绝；`WorkbenchView`／`SettingsView` 增加 `frozen`，冻结输入、预览／应用提交、返回与日历／月份／学期导航 | `frontend/src/d1/App.vue`、`views/WorkbenchView.vue`、`views/SettingsView.vue` |
| R15 | `leave.ts` 在 `isDirty=false` 时直接离开、`saveCurrent` 在组合结束等待前返回 unchanged：初始 clean 页面上 IME 组合中尚未进入 v-model 的最终文字被跳过。改为：协调器在 dirty 判定前先 `settle()`；`saveCurrent` 先占用在途槽并在 `runGuardedSave` 中等待 `settleComposition`（组合结束＋Vue 更新），再计算 dirty；编辑器桥暴露 `settle`，验证钩子增加 `composing` | `frontend/src/d1/leave.ts`、`views/EditorView.vue`、`App.vue` |
| R6 | `ExportDialog` 把 pending 与 unknown 合为同一状态，`confirmFileChecked` 只检查 `nativeBusy`：宿主明确 pending、查询仍 pending 时点“我已核对目标文件”即解除互斥并可产生第二次 fetch／save_docx＋新 UUID。改为：`unresolvedKind` 区分 `pending`（仅只读查询，不提供核对解锁）、`unknown`（明确未决→既有文件核对恢复）、`unconfirmed`（查询／桥通信失败，不当作明确 unknown，只能重查）；只有明确 unknown 的核对可解除互斥；原生阶段范围控件与关闭保持冻结 | `frontend/src/d1/views/ExportDialog.vue` |
| R13 | `validate_docx_bytes` 只要求两个 ZIP entry 存在并读取：空 XML 或坏 XML 的 ZIP 仍可覆盖旧目标并返回 saved。改为：必要部件必须非空、可解析为 XML 且根元素符合 `[Content_Types].xml` 的 `Types` 与 `word/document.xml` 的 `document` 命名空间；保持严格 base64、30 MiB、ZIP／CRC、原子替换提交点与提交后 unknown；不引入完整 OOXML schema | `desktop/d1_host_api.py` |

回归文件：`desktop/tests/test_d1_close.py`、`desktop/tests/test_d1_host_save.py`、`frontend/src/d1/d1.test.mjs`、`frontend/src/d1/d1.components.test.mjs`；真实窗口回归步骤：`desktop/d1_main.py`（`fix-regression` 新增 clean-IME 场景）。

本轮变化文件 SHA256 前 16 位（完整源码在工作区）：

| 文件 | SHA256 前 16 位 |
| --- | --- |
| `desktop/d1_host_api.py` | `e5c11baf3e5455e0` |
| `desktop/d1_main.py` | `e19a951941d29354` |
| `desktop/tests/test_d1_close.py` | `0f7e8244f66a1cce` |
| `desktop/tests/test_d1_host_save.py` | `aeef93134b73b1f3` |
| `frontend/src/d1/App.vue` | `64ba2d380e09ab53` |
| `frontend/src/d1/leave.ts` | `4ebd9b8918a83e3d` |
| `frontend/src/d1/views/EditorView.vue` | `5487561a4d8f212c` |
| `frontend/src/d1/views/WorkbenchView.vue` | `f82a2ec4033568a2` |
| `frontend/src/d1/views/SettingsView.vue` | `dc2280df6100b087` |
| `frontend/src/d1/views/ExportDialog.vue` | `e4a4445bf982ec8e` |
| `frontend/src/d1/d1.test.mjs` | `77d15ae657e98a95` |
| `frontend/src/d1/d1.components.test.mjs` | `9f8b984e221d14d5` |
| `frontend/src/d1/bridge.ts`（本轮未改，供复审对照） | `0ba1267ea65560e7` |

### 13.2 自动检查（最终一轮命令与结果）

后端命令工作目录 `backend`，环境 `APP_DISABLE_DOTENV=1`、`PYTHONIOENCODING=utf-8`，解释器 `desktop/.venv-d1/Scripts/python.exe`（CPython 3.14.7／SQLite 3.50.4）加 `-X utf8`；前端在 `frontend` 下执行；桌面在 `desktop` 下执行。

| # | 命令 | 结果 |
| --- | --- | --- |
| 1 | `python.exe -X utf8 -m unittest discover -s tests/local -t .` | **133 项，0 skip，exit 0**（79.950s；后端无本轮改动，数量与修复前基线一致） |
| 2 | `python.exe -X utf8 -m unittest tests.unit.test_i3_content_validation tests.unit.test_security tests.unit.test_calendar_boundaries tests.unit.test_i3_api_schemas tests.unit.test_i5_export_read_service` | **108 项，0 skip，exit 0** |
| 3 | `.venv-d1/Scripts/python.exe -X utf8 -m pytest tests/ -q -p no:cacheprovider` | **136 passed，2 warnings，exit 0**（修复前基线 129，新增 R11 关闭 3 项＋R13 DOCX 4 项） |
| 4 | `npm run test:d1` | 纯逻辑套件 OK ＋ **29 项组件级异步回归**（修复前基线为纯逻辑套件＋21 项组件检查；新增 R1 迟到回包／冻结覆盖 4 项、R15 2 项、R6 2 项；实际 SFC setup＋真实 Vue refs／watch＋受控桥） |
| 5 | `npm run typecheck`、`npm run build:d1` | 均 exit 0；构建输出 `d1.html`＋`index-pUd7naIw.js`（1,060.11 kB）＋`index-CY5NfqE0.css`，保留分块大小提示 |

新增回归覆盖（均先有确定反例）：宿主 R11「permit→保存恰在允许与重入之间开始→重入撤销→回执必须是 canceled 且通知不在主线程同步送达」「重入正常消费→仍返回 closing」「无重入→许可保持待消费」；R13「空 XML 部件 ZIP」「坏 XML」「错误根元素」均在对话框／替换前拒绝且旧目标字节不变、真实最小 DOCX 仍接受；前端 R1「A 取消通知先到→迟到 closing 回包不复活终态→B 请求仍真实到达宿主」「未决冻结阻止 shell 导航直至明确结果」「工作台冻结」「设置冻结（不产生新草稿／提交）」；R15「初始 clean＋活跃组合下手动保存等待最终文字、两次保存共享一次 PATCH」「协调器 clean 分支先 settle 再判定 dirty／保持 clean 不产生版本／settle 失败留页」「关闭路径在组合收尾后才发 allow」；R6「明确 pending 只能查询、核对不解锁、无第二次 fetch／save_docx／无关闭」「查询失败为 unconfirmed、只有明确 unknown 才可用文件核对恢复→新操作」；R2–R5、R7–R10、R12、R14 的原回归全部保留并通过。

### 13.3 真实窗口补验（本轮）

**Codex证据口径注记：** 以下为真实WebView2 DOM上的程序化CompositionEvent及textarea setter，经生产HTTP保存／导航链路执行；不是实际中文输入法按键操作。新增5项clean-IME checks，另保留2项既有dirty-IME checks。其他离开方式与故障路径的实测边界见审阅§11.5。

`desktop/d1_main.py` 的 `fix-regression` 阶段新增 R15 clean-IME 场景：**已保存且 clean** 的计划上先 `compositionstart` 并置入未进入 v-model 的文字，再分别执行手动保存与切日期离开；组合期间版本不变、页面不动，`compositionend` 后最终文字通过真实 HTTP 落库（版本 +1）后才保存／离开。源码窗口运行与最终包运行均通过，相关 checks：`fix_clean_ime_dirty_before_final`、`fix_clean_ime_save_waits`、`fix_clean_ime_final_text_saved`、`fix_clean_ime_leave_waits`、`fix_clean_ime_leave_saved` 全为 true；原有 dirty 组合、写锁失败、409 重提、设置草稿、切日期、导出与离开全流程保持通过。

源码窗口另跑 `dirty-close`：真实关闭请求→页面自动保存→`complete_close(allow=True)`→宿主重入消费许可→窗口销毁；宿主日志为 `close request begun` → `complete_close(allow=True)` → `closing allowed (flag consumed)` → `webview.start returned`，进程 exit 0（无 watchdog、无挂起）；数据库该计划 v9→v10 且 `raw_lesson_plan` 与关闭前输入逐字一致。

**对 §12.3 首次 IME 失败解释的补充（不篡改旧日志）：** §12 把当时“组合中保存超时、改为组合前已有内容＋组合末段后通过”归因于调用方步骤设计与渲染缺陷；该结论对“组合前先制造 dirty”的分支仍然成立。本轮进一步发现：那条路径始终以已有 dirty 为前提，而 **clean 分支（`dirty=false`）会完全绕过组合收尾**——手动保存与离开都把尚未进入 v-model 的最终组合文字当作“无修改”，这是此前未覆盖的真实产品缺陷（R15），不是纯步骤错误。新证据为 §13.3 的 clean-IME 场景与 §13.2 的组件回归；旧失败日志与解释原文保留。

**冻结覆盖边界：** 关闭交错（permit→保存开始→重入）与导出 pending 互斥由宿主线屏障探针与真实 SFC 组件序列覆盖；本轮**未**在真实窗口内注入保存恰在许可与重入之间的时序，也未在真实窗口内制造宿主 pending——这两项的窗口内故障注入保持未验（见 §13.5）。

### 13.4 最终包、仓外运行与样本

**构建：** `desktop/.venv-d1/Scripts/python.exe -X utf8 desktop/build_d1.py --skip-frontend --hash-out <证据>/package-hashes-fix2.json`，exit 0；输出 `build/desktop-d1/package/KGNext-D1Verify`，**137 文件**，`KGNext-D1Verify.exe` 14,691,692 字节、SHA-256 `61aba4eb8c58ec830f75071de987393f362a9360e24eade93c59c2f64ab87755`（前 16 位 `61aba4eb8c58ec83`）。上一轮 `f7c1a14f…` 包保留为 `build/desktop-d1/package/KGNext-D1Verify-f7c1a14f`，再上一轮 `5ad0dd1d…` 包保留为 `KGNext-D1Verify-pre-d1b-fix`；旧失败证据未动。

**包内身份（证据脚本 `verify-package.py`，独立读取 EXE 内嵌归档）：** `d1_main`、`d1_host_api`、`d1_paths`、`d1_server`、`app.local.config_service`、`app.local.config_tokens`、`app.local.daily_plan_service`、`app.local.migrate` 共 8 个关键模块的归档代码对象与当前源码即时编译结果逐一等价；`_internal/frontend/d1.html` 与 2 个 assets 与构建输出逐字节一致；包内 `alembic-local.ini`、`migrations_local/versions/20261014_0003_local_config_maintenance.py` 与 `app/assets/word_templates/daily_plan.docx` 存在。

**仓外运行（Codex复审澄清计数）：** 整个onedir复制到证据目录package-outside/KGNext-D1Verify，从不同cwd以合成数据final/data和预授权导出目录final/saves完成下列5个逻辑阶段。实际共6次包启动：verify首跑exit 3，verify2复跑exit 0，其余4阶段exit 0。下表记录各阶段最终成功结果，首次失败仍见下文及原JSON。

| 进程 | 阶段 | 结果 |
| --- | --- | --- |
| 1 | `first`（初始化→空内容按周导出→代表性内容保存 v2→单日导出→离开） | checks 全 true |
| 2 | `restart`（读回断言→长内容 v3→第二日期→两份导出） | checks 全 true |
| 3 | `fix-regression`（全部场景＋新增 clean-IME） | checks 全 true（含 7 项 clean-IME／原 IME checks） |
| 4 | `dirty-close`（关闭握手自动保存） | exit 0，宿主日志含 `complete_close(allow=True)`／`closing allowed (flag consumed)` |
| 5 | `verify`（读回 v12／原文一致→单日导出） | checks 全 true |

核对：`local_alembic_version = 20261014_0003_local`（包内迁移正常）、计划 2 份、内容历史 14 条、`PRAGMA foreign_key_check` 空、`journal_mode=wal`；所有进程正常退出，结束后 `tasklist` 无 `KGNext-D1Verify.exe` 残留；模板路径经真实导出生成验证。

**首次失败与修正（保留）：** ① 新 clean-IME 驱动步骤首次等待条件误用 JS `in`（应为 `Array.includes`），源码窗口首跑超时；`source-run\` 的 JSON 与日志保留，属调用方步骤错误，修正后通过。② 仓外 `verify` 首跑用了错误的 `--expect-version 10`（实际 12）返回 exit 3；`verify.json` 保留，改用 12 复跑 `verify2.json` exit 0。均为调用方参数错误，非产品缺陷；不篡改 §12.3 的旧日志。

**Word 样本（最终包，`final-word\`）：** 4 份文件全部通过本轮更严格的 DOCX 校验（有效 ZIP、CRC 无损坏、必要部件非空、XML 可解析且根元素正确）：

| 样本 | 字节 | SHA-256 前 16 位 |
| --- | --- | --- |
| 样本A-空内容-按周.docx（09-14~09-20，与上一轮样本A逐字节一致） | 14,021 | `1b3d4e21da0d7a7b` |
| 样本B-长内容-两份.docx（09-15~09-16 两份） | 14,450 | `35b474a1873c44c2` |
| 样本C-关闭保存内容-单日.docx（09-15，`verify2` 读回后导出） | 14,193 | `a321a381846bca5c` |
| 样本D-第二日期-单日.docx（09-16） | 14,044 | `1ba0480e2d5e8d69` |

**未验：** Word／WPS 页面视图或打印预览逐页核对（分页、表头、末页）未执行；最短复验步骤：用 Word 打开上述 4 个文件，在“视图→页面视图”与“文件→打印”预览逐页核对并记录版本与页数。

### 13.5 未验边界与再次复审条件

1. **保持未验：** 真实原生另存为的人工操作（自选中文文件名、取消对话框、占用文件后的真实弹窗重试与解除后新 ID 重试）——预授权目录只走同一写入路径并已验证中文文件名落盘，不能替代人工对话框；真实窗口内的关闭交错注入与导出 pending 注入；Word／WPS 逐页版式；干净机器、Windows 10、WPS、其他 DPI、多显示器与教师本人体验；真实教师数据与旧远程资源未触碰。
2. **本轮相对于 §12 的变化：** R1／R6／R11／R13／R15均有实现改动与回归；新增3＋4＋8项自动回归，真实窗口新增5项clean-IME checks并保留2项原dirty-IME checks；新包61aba4eb…身份与源码一致，仓外5阶段最终通过、实际6次启动含一次verify失败；§12的133／108／129／21基线与旧包f7c1a14f…保留。本轮独立关闭结论以审阅§11为准。
3. **证据根：** `%TEMP%\opencode\kgm-d1b-fix2-20261015\`（`source-run\`、`source-run2\`、`package-outside\`、`final-word\`、`package-hashes-fix2.json`、`package-verify.json`、`verify-package.py`；临时路径不保证长期留存，关键结论以本节为准）。
4. **再次复审条件：** 剩余 4 项与 R15 的定点反例均有自动回归，真实窗口 clean-IME 与关闭路径有本轮证据；交 Codex 独立复审，不自行宣布关闭。产品验收、发行与后续切片不因本节自动成立。

## 14. D1B 剩余修复与补验（2026-10-15 第三轮，R1／R6）

依据[审阅 §11](desktop-d1-review.md#11-d1b-第二轮修复复审2026-10-15)与[当前任务](../tasks/current.md)，只继续 R1、R6；已关闭 13 项保留其保护与回归，不重复派发、不泛化重构。环境仍为 `desktop/.venv-d1`（CPython 3.14.7／Windows x64／标准 GIL、SQLite 3.50.4），未安装或升级依赖，未改 backend 业务声明／锁、D1 锁或 D0 环境／包。本节不自行写成 Codex 已关闭或 D1B 已放行；教师产品体验、干净机器、Win10、WPS、其他 DPI 与发行仍不在本轮。

### 14.1 改动文件与逐项映射

| 项 | 根因与修复 | 主要文件 |
| --- | --- | --- |
| R1 | 权威撤销只清 UI 关闭锁，协调器的旧等待不结束：`finishClose` 的 `complete_close` 桥接 Promise 未返回时，`LeaveCoordinator.active` 仍被该 close ID 占用，新导航返回 `busy`、新关闭发 `allow:false`，直到旧 Promise 完成才恢复。新增按 close ID 的 `cancelClose` 释放等待；运行恢复后只返回 `stayed`，不执行旧动作、不重新冻结、不清除新任务；权威撤销时不丢弃在途保存 | `frontend/src/d1/leave.ts`、`frontend/src/d1/App.vue` |
| R6 | 查询结果未绑定操作代际：`queryLastResult` 在 await 后直接 `applySaveResult`，Q1 迟到的 A `saved` 可覆盖新操作 B 的权威 pending 并解除 `nativeBusy`，允许关闭和第三次保存。新增操作代际＋请求 ID 绑定、终态归还代际、查询在途计数与 await 后复核 | `frontend/src/d1/views/ExportDialog.vue` |

**R1 修复细节：**

1. `LeaveCoordinator` 新增 `cancelClose(closeRequestId)`：仅当 `active` 恰为 `close:<该ID>` 时置条目 `cancelled` 并释放 `active`；其他 ID 或其他目标返回 `false`，不误伤当前离开。该入口只由宿主明确 `close_aborted`（权威撤销）调用。
2. `run` 在 settle 后、保存返回后、`execute` 动作执行前与动作完成后复核 `cancelled`：迟到完成只返回 `stayed`，不执行旧动作、不重新冻结；`requestLeave` 的清理改为条目身份比对，旧任务不清理新任务。
3. `App.vue.onCloseAborted`：对同 ID 权威撤销调用 `cancelClose`，释放成功时为该 ID 写入 `canceled` 终态（`onRequestClose` 迟到续段不再补发 allow/deny）；最终 closing 冻结、`destroy_failed` 撤销许可、按 ID 终态保护与迟到回包隔离保持不变。
4. 边界保持：通信失败与页面自有查询超时仍为 `unconfirmed`／保留冻结，不调用 `cancelClose`；保存中撤销后协调器继续等待并消费保存结果（保存不丢弃、不进第二次提交），只是不再执行离开动作。

**R6 修复细节：**

1. 新增操作代际 `saveEpoch` 与请求 ID 绑定 `SaveOperation`；`beginSaveOperation` 在新原生操作开始时递增并分配新 UUID；`applySaveResult(op, …)` 先复核代际与请求 ID，旧结果不更新新操作的状态、文件名或 `busy`。
2. 终态结果（saved／canceled／failed）与显式文件核对调用 `endSaveOperation` 归还代际：同操作终态后迟到的 pending／失败不回退；查询在 await 后以 `operationIsOpen` 复核（当前、未决、仍为同一操作）。
3. `queryLastResult` 明确在途计数 `queriesInFlight`（查询按钮 loading／禁用、只读查询），查询仅在当前未决操作上发起；通信失败不把显式 pending／unknown 降级。
4. 关闭／重开对话框（非原生阶段）递增代际；重试清空请求 ID 并由新操作递增；pending 只读查询、unknown 显式核对、同 ID 幂等、不同 ID 宿主串行、30 MiB／base64／DOCX 校验与终态语义均保持。

本轮变化文件（SHA256 前 16 位）：

| 文件 | SHA256 前 16 位 |
| --- | --- |
| `frontend/src/d1/leave.ts` | `664b37cd9f8569a9` |
| `frontend/src/d1/App.vue` | `5a9249037490c4ac` |
| `frontend/src/d1/views/ExportDialog.vue` | `7d6c9e8830abafaf` |
| `frontend/src/d1/d1.test.mjs` | `2e07218bf6410d40` |
| `frontend/src/d1/d1.components.test.mjs` | `1c0ff7b1888195cc` |
| `desktop/d1_main.py`（验证驱动：新增 `fix-regression2`／`clean-ime-close` 阶段） | `2c070491e8ceb40d` |

### 14.2 先补失败回归（修复前实际输出，保留）

| 命令（cwd `frontend`） | 修复前结果 |
| --- | --- |
| `node src/d1/d1.test.mjs` | exit 1：`TypeError: coordinator.cancelClose is not a function`（新增协调器回归即失败） |
| `node src/d1/d1.components.test.mjs` | exit 1：`AssertionError: the wait bound to A is released — true !== false`（R1 反例在真实 SFC setup 中复现） |

**新增回归覆盖：**

- 纯逻辑（`d1.test.mjs` 新增 2 项）：保存中收到权威撤销时释放等待且保存保持共享、不丢弃、不重复；旧动作迟到完成只报 `stayed`、不启动旧动作、不清除新请求；不同 ID／未激活时 `cancelClose` 返回 `false`。
- 组件（`d1.components.test.mjs` 新增 7 项检查，29→36）：A 永不返回时权威撤销后导航与新关闭 B 立即接续（判定时 A 的桥接 Promise 仍未完成）；撤销发生在保存中时保存仍完成、旧 ID 零 allow/deny、不重新冻结；B 进行中 A 迟到 `closing` 不触碰 B 的终态与冻结；Q1 延迟→Q2 终态→B 权威 pending→Q1 迟到不回退（B 保留原 ID、互斥、无第三次保存、不能关闭或改范围）；同 ID 乱序查询终态不回退；查询失败不降级 pending 且不解除互斥、显式 unknown 恢复；终态重试绑定新操作并只应用新结果。

### 14.3 自动检查（最终一轮命令与结果）

后端命令工作目录 `backend`，环境 `APP_DISABLE_DOTENV=1`、`PYTHONIOENCODING=utf-8`，解释器 `desktop/.venv-d1/Scripts/python.exe`（CPython 3.14.7／SQLite 3.50.4）加 `-X utf8`；前端在 `frontend` 下执行；桌面在 `desktop` 下执行。

| # | 命令 | 结果 |
| --- | --- | --- |
| 1 | `python.exe -X utf8 -m unittest discover -s tests/local -t .` | **133 项，0 skip，exit 0**（94.977s；后端本轮无改动） |
| 2 | `python.exe -X utf8 -m unittest tests.unit.test_i3_content_validation tests.unit.test_security tests.unit.test_calendar_boundaries tests.unit.test_i3_api_schemas tests.unit.test_i5_export_read_service` | **108 项，0 skip，exit 0**（0.458s） |
| 3 | `.venv-d1/Scripts/python.exe -X utf8 -m pytest tests/ -q -p no:cacheprovider` | **136 passed，2 warnings，exit 0**（3.59s） |
| 4 | `npm run test:d1` | 纯逻辑套件 OK ＋ **36 项组件级异步回归**（29→36；实际 SFC setup＋真实 Vue refs／watch＋受控桥，exit 0） |
| 5 | `npm run typecheck`、`npm run build:d1` | 均 exit 0；构建输出 `d1.html`＋`index-CAvd46nC.js`（1,060.94 kB）＋`index-D1xaaJRm.css`，保留分块大小提示 |
| 6 | `uv pip check --python backend/.venv/Scripts/python.exe`／`--python desktop/.venv-d1/Scripts/python.exe` | 26 项业务包／46 项 D1 锁包全部兼容，exit 0；环境为 CPython 3.14.7、win-amd64、标准 GIL、SQLite 3.50.4 |

依赖声明与锁散列保持不变（复核值）：`backend/pyproject.toml`＝`e5f948d2…28961`、`backend/uv.lock`＝`cc589c0a…d5495`（与审阅 §3／§11 记录一致）；`desktop/requirements-d1.lock.txt`＝`db1a0e586b7a17f4…`、`desktop/requirements-d1.in`＝`c0b73435631d0d23…`。

### 14.4 真实 WebView2 补验（本轮）

新增两个 selftest 阶段，均在真实 WebView2 窗口内驱动真实页面；生产路径不加任何钩子，故障注入只发生在页面内包装桥接函数（丢失/推迟回包）或驱动进程临时替换宿主 `_perform_save`（减慢一次真实落盘）。`desktop/d1_main.py` 仅新增验证驱动代码。

`--phase fix-regression2`（源码窗口与包内窗口均通过，19/19 checks 为 true）：

| 场景 | 窗口内证据 |
| --- | --- |
| 关闭悬挂／丢回复 | 页面包装 `complete_close` 返回永不完成的 Promise（宿主收不到 allow）；关闭冻结阻止导航（`__d1App.view()` 保持 editor） |
| 30 秒超时后恢复 | 宿主真实 30s 超时（源码窗口 29.1s／包内 29.0s 观测）经真实 `evaluate_js` 送达 `close_aborted(timeout)`；同 ID；页面前往工作台成功，旧 Promise 仍未完成；宿主状态 `canceled`、窗口未销毁 |
| 导出 pending／迟到查询 | Q1 延迟、Q2 终态 saved；新操作 B 权威 pending；Q1 迟到后 B 保持 `save_result_unknown`／`pending`／busy=true、两次保存 ID 唯一、重试不产生第三次 `save_docx` |
| 设置预览乱序 | 挂起真实 `/config/preview` 响应→期间改动输入→放行后 `previewVisible()===false`、草稿保留、apply 无回执 |
| clean-IME 离开路径 | 返回日历／进设置：组合进行中版本不变、页面不动；`compositionend` 后最终文字经真实 HTTP 落库（版本 +1）才导航 |
| 许可与保存交错（页面侧） | 关闭请求到达时原生 Word 保存仍在途（驱动临时减慢真实 `_perform_save`）：页面不发 allow；保存完成后才发 `allow=True`，宿主回执 `accepted=True/state=closing`；宿主日志顺序 `fix2 slow save completed` → `complete_close(..., allow=True)` → `closing allowed` |

宿主日志（`package-run.log`）同时保留 30s 超时段的 `close request begun` → `close timeout` → `notified close_aborted timeout` 全过程。宿主内部“allow 与保存恰好交错时撤销许可”的分支仍以 §11 已关闭的 R11 线程探针为证据，本轮未在真实窗口内注入该宿主内部时序（需宿主侧钩子，见 §14.7）。

`--phase clean-ime-close`（4/4 checks 为 true）：已保存且 clean 的计划上启动组合、最终文字尚未进入 v-model；驱动返回后真实窗口关闭，页面侧计时器结束组合；关闭前版本不变，离开保存等待最终文字并落库；**关闭完成后**直接读取 SQLite 校验：`raw_lesson_plan＝关窗前组合最终文字`、版本 = 关闭前 +1。

**口径说明：** 以上 IME 证据均为真实 WebView2 DOM 上的程序化 `CompositionEvent` 与 textarea setter，不是实际中文输入法按键操作；页面包装只存在于验证驱动，不代表生产桥接行为。普通 dirty-close（§12）不替代上述故障路径。

### 14.5 新包、仓外运行与 Word 样本

**构建：** `desktop/.venv-d1/Scripts/python.exe -X utf8 desktop/build_d1.py --skip-frontend --hash-out <证据>/package/package-hashes-fix3.json`，exit 0；输出 `build/desktop-d1/package/KGNext-D1Verify`，**137 文件**，`KGNext-D1Verify.exe` 14,699,752 字节、SHA-256 `caa7a12725051066f223bcc9c67c014ad2fad81134c02d80c31f9e2cf37435de`。上一轮 61aba4eb… 包保留为 `KGNext-D1Verify-61aba4eb`；f7c1a14f… 与 `pre-d1b-fix` 旧包及全部旧失败证据未动。

**身份核对：** 仓内包 137/137 文件与本次清单（路径、大小、SHA256）逐一相符、无额外文件；`verify-package.py`（含 `co_exceptiontable` 比较）确认 8 个关键归档模块（`d1_main`、`d1_host_api`、`d1_paths`、`d1_server`、`app.local.config_service`、`app.local.config_tokens`、`app.local.daily_plan_service`、`app.local.migrate`）与当前源码编译结果一致；`_internal/frontend/d1.html`＋2 个 assets 与构建输出逐字节一致；`alembic-local.ini`、`migrations_local/versions/20261014_0003_local_config_maintenance.py`、`app/assets/word_templates/daily_plan.docx` 存在。

**仓外运行：** 整个 onedir 复制到 `<证据>/package-outside/KGNext-D1Verify`，从不同 cwd 启动，合成数据 `<证据>/package-data`、预授权导出目录 `<证据>/package-saves`（驱动进程剥离全部继承的 `KGM_*` 后注入；包内摘要记录 data_dir 均在临时证据根，未回退教师目录）。6 个独立进程、全部 exit 0：

| 进程 | 阶段 | 结果 |
| --- | --- | --- |
| 1 | `first`（初始化→空内容按周导出→代表性内容 v2→单日导出→离开） | checks 全 true |
| 2 | `restart`（读回断言→长内容 v3→第二日期→两份导出） | checks 全 true |
| 3 | `fix-regression`（既有 R2–R15 窗口回归全部场景） | checks 全 true |
| 4 | `fix-regression2`（§14.4 全部场景＋真实关闭） | checks 全 true（19/19） |
| 5 | `verify`（读回 v13 与原文“设置离开最终文本”核对→单日导出） | checks 全 true |
| 6 | `clean-ime-close`（组合关窗＋关闭后数据库核对） | checks 全 true（4/4） |

核对：`local_alembic_version = 20261014_0003_local`（包内迁移正常）、计划 2 份（09-15=v14、09-16=v2）、内容历史 16 条、审计 18 条、日历修订 1 个、`PRAGMA foreign_key_check` 为空、`journal_mode=wal`；结束后无 `KGNext-D1Verify.exe` 残留。本轮包场景首次即通过，无产品失败；修复前的两条失败回归保留在 §14.2。

**Word 样本（最终包 `package-saves` → `word-samples`，空／代表性／长内容多份／第二日期）：**

| 样本 | 字节 | SHA-256 前 16 位 | 页面视图页数 |
| --- | --- | --- | --- |
| 样本A-空内容-按周.docx（与上一轮 A 逐字节一致） | 14,021 | `1b3d4e21da0d7a7b` | 2 |
| 样本B-代表性-单日.docx | 14,165 | `05bff8c24cd77d7c` | 2 |
| 样本C-长内容-两份.docx | 14,443 | `6313a2c17b9a7006` | 5 |
| 样本D-第二日期-单日.docx | 14,038 | `2d1adb2e4e56975a` | 2 |

**Word 16.0 页面视图逐页核查（程序化提取＋逐页截图）：** 用 Word COM 以 `wdPrintView` 打开全部样本，逐页提取真实排版文本并核查：页数 2／2／5／2；每份计划首页表头（“…一日活动计划”／班级＋教师／周次／月日星期）完整；内容页栏目齐全（含 `FIX3` 标记；样本 B 五类栏目与户外支持策略）；样本 C 在第 3 页页尾存在显式分页符、第 4 页顶开始第二份计划（9 月 16 日）表头，两份计划不共页；末页均为“一日活动反思”且非空白（空样本的反思按设计为空）。字体集合：Times New Roman／仿宋／楷体，字号 10.5／12／16 pt；表格 1／1／2／1 个。全部 11 页已在真实 Word 页面视图逐页截图（PrintWindow，非 PDF），页数与状态栏一致（如“第 4 页，共 5 页”）；截图可供目视复核。**未做人工逐页目视审美判定与 WPS 复核**（见 §14.7）。

**证据工具首次失败与修正（保留，不计为产品缺陷）：** ① 首次 Word 自动化脚本把含中文的样本路径直接写在 PowerShell 脚本里，Windows PowerShell 5.1 按 ANSI 解析导致路径乱码、`Documents.Open` 报 0x800A141F；改为 ASCII 脚本＋UTF-8 JSON 清单后正常。② 首次整屏截图被同机其他窗口遮挡中心区域；改用 `PrintWindow` 直接捕获 Word 窗口（不受遮挡）后取得 11 页干净截图。

### 14.6 未验边界与再次复审条件

**Codex复审注记（2026-10-15）：** 本节为OpenCode交付当时记录，最终判断见[审阅§12](desktop-d1-review.md#12-d1b-第三轮修复复审2026-10-15)。§14.4的R6场景完整替换save_docx／get_save_result并构造pending／saved，属真实页面＋受控桥注入，不能称真实宿主权威状态或仅推迟真实回包。预览包装在release时才发出realFetch，之后固定等1秒而未断言响应处理完成，尚不足以证明迟到响应已丢弃。verify记录v13是读回观察值，未传expect-version，只有原文匹配断言。6份包JSON和6次正常returned日志已核实，外层进程returncode行未留存，本次没有独立重跑GUI。§14.5的11张截图已由Codex目视复核正文／表格／分页；双页视图有重复，C第3–5页物理页下方空白边缘不完整，具体边界见审阅§12.5。文中“§14.7”均应读作§14.6；证据脚本实际名为`package/verify-package.py`，不是下文`package/package-verify.py`。两条代码残留与原生人工交付等必要缺口仍阻止放行；原实施事实与首次失败不改写。

1. **保持未验：** 真实原生另存为的人工操作（自选中文文件名、取消对话框、实际占用文件及解除后新 ID 重试、旧目标保护）——该对话框是原生模态操作，本轮未由人实际点击；写入路径本身（含真实文件锁占用失败→解除后新 ID 重试、取消不报成功、提交点前失败保留旧文件、中文名落盘）已有 136 项桌面单测与预授权目录实跑覆盖，但预授权目录不能替代人工对话框。最短人工步骤：不设 `KGM_D1_VERIFY_SAVE_DIR` 以交互模式启动包内 EXE→打开计划→导出→在原生另存为对话框中分别执行“输入中文文件名保存／取消／占用目标后保存→解除占用用新操作 ID 重试”，逐项记录结果。真实窗口内的宿主内部“许可与保存交错”注入（需宿主钩子）同保持未验；实际中文输入法按键（非程序化 CompositionEvent）未执行；WPS、干净机器、Windows 10、其他 DPI、多显示器与教师本人体验保留后续边界。真实教师数据与旧远程资源未触碰。
2. **证据根：** `%TEMP%\opencode\kgm-d1b-fix3-20261015\`（修复前失败日志、`source-run\`、`package-outside\`、`package-data\`／`package-saves\`、`package/package-hashes-fix3.json`、`package/package-verify.json`、`package/package-verify.py`、`word-samples\`、`word-pages\`（11 页截图＋`word-verify.json`）、`word-analysis.json`、`word-fonts.json`、`package-run.log`；临时路径不保证长期留存，关键结论以本节为准）。
3. **再次复审条件：** R1、R6 均有确定反例回归、实现改动与真实窗口补验；新包身份与源码一致；交 Codex 独立复审两项关闭与本片必要证据，满足后才工程放行。产品验收、发行与后续切片不因本节自动成立。

## 15. D1B R1／R6 残留修复与补验（2026-10-15 第四轮）

依据[审阅 §12](desktop-d1-review.md#12-d1b-第三轮修复复审2026-10-15)与[当前任务](../tasks/current.md)，只处理 R1／R6 两条残留（原两条反例由 §14 修复并继续保留其回归）；已关闭 13 项保护不删减、不泛化重构。环境仍为 `desktop/.venv-d1`（CPython 3.14.7／Windows x64／标准 GIL、SQLite 3.50.4），未安装或升级依赖，未改 backend 声明／锁、D1 锁或 D0 环境／包。本节不自行写成 Codex 已关闭或 D1B 已放行。

### 15.1 改动文件与逐项映射

| 项 | 残留根因与修复 | 主要文件 |
| --- | --- | --- |
| R1／P2 | `onRequestClose` 在进入协调器前先等待原生保存（`waitForExportIdle`）；该阶段没有协调器条目，也没有 `activeCloseId`，宿主权威撤销被丢弃——保存结束后旧 A 仍会补发 allow、重新冻结并占用新 B。修复：关闭生命周期从 `onRequestClose` 入口覆盖（`openCloseIds`），权威撤销按 ID 留存（`abortedCloseIds`），在原生保存等待、协调器等待与补发拒绝前逐处复核；已撤销 A 零许可、不冻结、不占 B，真实保存结果继续正常消费 | `frontend/src/d1/App.vue` |
| R6／P2 | 查询 loading（`queriesInFlight`）跨操作共用：A 的 Q1 悬挂后经显式文件核对与关闭／重开进入新操作 B，旧计数仍为 1，B 的查询按钮持续 loading／disabled。修复：查询在途归属操作代际（`saveEpoch`）——终态、显式核对、关闭／重开、新操作均退役旧计数；旧查询的 `finally` 只在自身代际仍当前时递减，迟到返回／抛错不干扰新代际计数与结果 | `frontend/src/d1/views/ExportDialog.vue`；`frontend/src/d1/views/SettingsView.vue` 仅增加只读验证钩子 `inputVersion`（供窗口证据等待输入失效，不改产品行为） |

本轮变化文件（SHA256 前 16 位）：

| 文件 | SHA256 前 16 位 |
| --- | --- |
| `frontend/src/d1/App.vue` | `366fe1eb9961f54d` |
| `frontend/src/d1/views/ExportDialog.vue` | `576b35a585bbcd3b` |
| `frontend/src/d1/views/SettingsView.vue` | `59d06a1b43dec0e6` |
| `frontend/src/d1/d1.components.test.mjs` | `6a4bbb3bc28ba606` |
| `desktop/d1_main.py`（验证驱动：R1 保存等待撤销、R6 实际按钮、预览完成信号） | `5ee03feff9cd5417` |

### 15.2 先补失败回归（修复前实际输出，保留）

| 场景 | 修复前结果 |
| --- | --- |
| 组件·R1 残留（`node src/d1/d1.components.test.mjs`） | exit 1：`AssertionError: the aborted A sends no allow/deny — 1 !== 0`（保存等待期间撤销后旧 A 补发许可）；日志 `prefix4-components.log` |
| 组件·R6 残留（同一套件，单独捕获） | exit 1：`AssertionError: the explicit file check retires the old query loading — 1 !== 0`；日志 `prefix4-components-r6.log` |
| Codex 独立探针复跑（修复后） | `r1-expected-behavior.mjs` exit 0，4/4 正向预期 PASS（A 零许可、B allow=true、B 占用终态、B 最终关闭）；`r6-recovery-regression.mjs` exit 0，B-pending 快照 `queriesInFlight＝0`、`queryButtonLoading＝false`，B 查询返回 B.docx |

**新增回归覆盖（组件 36→40）：** R1：保存等待期间撤销后 A 零许可／不冻结、导航与新 B 接续（A 旧桥 Promise 仍未完成）；同场景下真实保存窗口不被丢弃且随后可导航。R6：A 显式 unknown→Q1 悬挂→显式文件核对→关闭／重开→B pending 时，驱动按钮的 loading 绑定为 0、B 可查询并返回 B.docx，旧 Q1 迟到不影响 B；旧 Q1 抛错同样不影响 B 计数与结果。旧 Q1 迟到继续不改 B 的文件名／终态。

### 15.3 自动检查（最终一轮命令与结果）

工作目录与解释器同 §14.3；后端在 `backend`、前端在 `frontend`、桌面在 `desktop` 下执行，全部使用测试自身的临时合成库。

| # | 命令 | 结果 |
| --- | --- | --- |
| 1 | `python.exe -X utf8 -m unittest discover -s tests/local -t .` | **133 项，0 skip，exit 0**（80.638s） |
| 2 | `python.exe -X utf8 -m unittest tests.unit.test_i3_content_validation tests.unit.test_security tests.unit.test_calendar_boundaries tests.unit.test_i3_api_schemas tests.unit.test_i5_export_read_service` | **108 项，0 skip，exit 0** |
| 3 | `.venv-d1/Scripts/python.exe -X utf8 -m pytest tests/ -q -p no:cacheprovider` | **136 passed，2 warnings，exit 0**（3.35s） |
| 4 | `npm run test:d1` | 纯逻辑套件 OK ＋ **40 项组件级异步回归**（36→40，实际 SFC setup＋真实 Vue refs／watch＋受控桥，exit 0） |
| 5 | `npm run typecheck`、`npm run build:d1` | 均 exit 0；构建输出 `index-B2JWCfC1.js`＋`index-ILAyuRJW.css`，保留分块大小提示 |
| 6 | `uv pip check`（backend／desktop） | 26／46 包兼容，exit 0；声明与锁散列未变（同 §14.3 记录值） |

### 15.4 真实 WebView2 补验（新增与改进场景）

`--phase fix-regression2` 在源码窗口与包内窗口均通过（31/31 checks 为 true；原 19 项保护全保留）。新增/改进：

| 场景 | 窗口内证据与口径 |
| --- | --- |
| R1 保存等待期间撤销（新增 1b） | 驱动进程临时减慢真实 `_perform_save`；原生保存在途时请求关闭 A；宿主真实超时（**该场景把超时界缩短为 5 秒，同一超时路径与通知**）经真实 `evaluate_js` 送达 `close_aborted`；A 期间与保存结束后的记录均为零 `complete_close`；宿主状态 `canceled`；保存完成后导出正常收口（`busy()=false`、宿主无在途保存）且导航到工作台成功。宿主日志：`slow save begin` → `close request begun` → `close timeout` → `notified close_aborted` → `slow save completed` |
| R6 实际查询按钮（新增 2b） | 真实 DOM 按钮：A 显式 unknown → 点击真实查询按钮 → 按钮进入 disabled（loading）→ 点击真实“我已核对目标文件” → 真实“取消”关闭对话框 → 真实工具栏按钮重开 → 再次导出（含真实缺项确认 ack 勾选路径，首次尝试的 ack 超时为驱动工具迭代，见证据 `fix2-first-attempt-ack-timeout.json`）→ B pending 时查询按钮 **disabled=false**（修复证据）→ 点击按钮查询返回 `B.docx`；旧 Q1 迟到返回后 B 的文件名／终态与保存次数（2）均不变。bridge 状态为受控注入（页面包装 `save_docx`／`get_save_result`），按钮、对话框与勾选为真实 DOM 操作 |
| 预览响应处理完成后的旧结果丢弃（改进） | 包装在放行时发出真实请求并记录 `served`（响应真实返回）；先等待输入失效（`inputVersion` 递增）再放行；随后等待预览按钮从 loading 回到可点击（组件 finally 处理完成）才断言：`previewVisible()=false`、草稿保留、apply 无回执。固定等待不再代替响应与处理完成 |
| 保留场景 | 丢回包＋真实 30s 超时恢复（§14.4）、导出 pending＋迟到查询、clean-IME 返回日历／进设置、clean-ime-close 组合关窗与关闭后直接读库核对、最终关闭等待在途原生保存后才 allow —— 均全 true |

**证据分类：** 受控桥注入＝fix-regression2 步骤 1／2／2b 的页面包装（丢失／悬挂／构造 pending、saved、unknown）；真实宿主回包与能力＝步骤 1 的 30s 真实超时与 `evaluate_js` 通知、1b 的真实超时、步骤 5 的真实原生保存与真实 `complete_close(allow=True)`／`closing allowed`、clean-ime-close 的真实保存与关闭后读库；程序化 `CompositionEvent`＝步骤 4 与 clean-ime-close；**实际输入法按键未执行**。宿主内部“allow 与保存恰好交错时撤销许可”仍以已关闭的 R11 线程探针为证据，本轮未在真实窗口注入该宿主内部时序。

### 15.5 新包、仓外运行与样本

**构建与身份：** `desktop/build_d1.py --skip-frontend --hash-out <证据>/package/package-hashes-fix4.json`，exit 0；`KGNext-D1Verify` **137 文件**，EXE 14,704,113 字节、SHA-256 `9a8e90c854ed45cd2b31b447176f441c7be8c03f72fc58de5f2c93b6e2fec1e0`；上一轮 `caa7a127…` 保留为 `KGNext-D1Verify-caa7a127`（更早 61aba4eb…／f7c1a14f…／pre-d1b-fix 与旧失败证据未动）。仓内 137/137 文件与清单逐一相符、无额外文件；`verify-package.py`（含异常表比较）确认 8 个关键归档模块与源码一致；前端 `d1.html`＋`index-B2JWCfC1.js`＋`index-ILAyuRJW.css` 与构建输出逐字节一致；迁移配置、revision 与 Word 模板存在。

**仓外运行：** 包复制到 `<证据>/package-outside`，从不同 cwd 启动，合成数据／预授权导出目录在证据根下（驱动进程剥离继承 `KGM_*` 后注入）。6 个独立进程、实际返回码全部 0，逐进程记录于 `pkg-phases-result.json`：

| 进程 | 阶段 | 返回码 | checks |
| --- | --- | --- | --- |
| 1 | `first` | 0 | 6/6 |
| 2 | `restart` | 0 | 6/6 |
| 3 | `fix-regression` | 0 | 28/28 |
| 4 | `fix-regression2` | 0 | 31/31 |
| 5 | `verify` | 0 | 5/5 |
| 6 | `clean-ime-close` | 0 | 4/4 |

核对：`local_alembic_version = 20261014_0003_local`、计划 2 份（v14／v2）、内容 16、审计 18、`PRAGMA foreign_key_check` 空、`journal_mode=wal`；无残留进程。

**Word 样本：** 本轮包导出的 4 份样本与本文件 §14.5 所记、且已由[审阅 §12.5](desktop-d1-review.md#125-补验证据的实际含义)目视复核的上一轮样本**逐字节一致**（A `1b3d4e21da0d7a7b`、B `05bff8c24cd77d7c`、C `6313a2c17b9a7006`、D `2d1adb2e4e56975a`；14,021／14,165／14,443／14,038 字节），渲染链未变化。复核页级结构仍为 2／2／5／2（首页表头、样本 C 第 4 页新页开始第二份计划、末页反思非空、无空白页，`problems=0`）；字体仍为 Times New Roman／仿宋／楷体（10.5／12／16 pt）。另生成 11 张 100% 缩放逐页截图（PrintWindow 窗口捕获，状态栏页号可见；非 PDF）；非 100% 缩放会得到模糊缩放表面，故未用整页适配，页数完整性以 Word 自身页数＋逐页文本范围为准。未做新一轮人工审美判定与 WPS 复核。

### 15.6 未验边界与再次复审条件

**Codex复审注记（2026-10-16）：** R6已关闭，R1通知乱序残留仍需修复，最终结论见[审阅§13](desktop-d1-review.md#13-d1b-第四轮修复复审2026-10-16)。仓外6进程returncode=0和全部阶段JSON已独立核实；源码日志实际为6次启动、4次正常完成，其中两次点击导出后等待unknown约60秒且未点击ack，后续补ack后成功。现存`fix2-first-attempt-ack-timeout.json`为事后说明及诊断摘录，原始失败完整JSON／返回码未保留；证据支持漏确认步骤解释，不能确认两次全部根因或称源码仅启动4次。预览已等待真实fetch settle和组件loading结束，但served在resolve／reject两支都置true，未存HTTP状态／有效正文，故不独立证明HTTP200有效预览曾返回。R1窗口补验证实A撤销先送达的修复，未覆盖B先于A撤销通知的新反例；原生人工保存仍未执行。原记录与首次失败保留，不改写为全部通过。

1. **保持未验：** 真实原生另存为的人工操作（中文文件名／取消／实际占用及解除后新 ID 重试、旧目标保护）仍未由人实际点击，步骤与原因同 §14.6；实际输入法按键、真实窗口内的宿主内部许可／保存交错注入、WPS、干净机器、Windows 10、其他 DPI、多显示器与教师本人体验保留后续边界。真实教师数据与旧远程资源未触碰。
2. **证据根：** `%TEMP%\opencode\kgm-d1b-fix4-20261015\`（修复前失败日志 `prefix4-*.log`、`source-run\`（4 个阶段 JSON 全 true）、`package-outside\`、`package-data\`／`package-saves\`、`pkg-phases-result.json`、`package/package-hashes-fix4.json`、`package/verify-package.py`、`package/package-verify.json`、`word-samples\`、`word-pages\`（11 张截图）、`word-analysis.json`、`word-fonts.json`、`package-run.log`、`fix2-first-attempt-ack-timeout.json`；临时路径不保证长期留存，关键结论以本节为准）。
3. **再次复审条件：** R1、R6 两条残留均有先失败回归、实现改动与真实窗口补验（实际按钮与保存等待撤销已覆盖）；新包身份与源码一致、仓外返回码逐进程留存；交 Codex 独立复审两项关闭与本片必要证据，满足后才工程放行。产品验收、发行与后续切片不因本节自动成立。

## 16. D1B R1 通知乱序残留修复与补验（2026-10-16 第五轮）

依据[审阅 §13.3](desktop-d1-review.md#133-r1--p2-残留新关闭先于旧撤销通知到达)、[审阅 §13.6 接续](desktop-d1-review.md#136-接续)与[当前任务](../tasks/current.md)，只修 R1“新宿主关闭先于旧撤销通知到达”（§13.3）的残留并补齐本片必要证据；R6 已关闭不再派发，其余 13 项保护与其回归保留，不扩大重构。环境仍为 `desktop/.venv-d1`（CPython 3.14.7／Windows x64／标准 GIL、SQLite 3.50.4；`uv pip check` backend 26 包、desktop 46 包兼容，exit 0），未安装或升级依赖，未改 backend 声明／锁与 D1 锁；未读真实 `.env`／密钥／教师库，未连接旧 MySQL／远程业务，未调用真实 AI。本节不自行写成 Codex 已关闭或 D1B 已放行。

### 16.1 改动与修复

| 项 | 根因与修复 | 主要文件 |
| --- | --- | --- |
| R1／P2（§13.3） | `onRequestClose` 面对新关闭 ID 只释放 UI 冻结：被宿主已结束的旧 A 仍留在 `openCloseIds`／协调器等待中，保存结束后旧 A 可按旧路径补发 `allow`、重新冻结或占住 B（B 被 `busy` 否决）。修复：新宿主关闭 ID 到达时，按 ID 退役其替代的**所有**旧开放 close handler 与协调器等待（`retireReplacedClose`）——旧 ID 进入既有的静默集合（保存／IME／数据库保存等待后逐处复核均不再动作），旧协调器等待被 `cancelClose` 释放；不依赖旧撤销通知或旧回包先返回。既有的同 ID 幂等、最终 closing 冻结、通信失败保留冻结与真实在途保存照常消费均保持 | `frontend/src/d1/App.vue` |
| 补验驱动 | 新增 `--phase close-order`（真实宿主状态机的通知乱序：慢真实保存＋真实超时＋迟送／丢失 `close_aborted`＋新 B 先到）与 `--phase save-dialog`（真实原生另存为对话框；仅验证驱动代码），并补预览 HTTP 状态证据 | `desktop/d1_main.py` |

**R1 修复细节：**

1. 新增 `retireReplacedClose(closeRequestId)`：若该 ID 仍占据协调器等待则 `cancelClose` 释放并写入 `canceled` 终态；若其 handler 仍开放则记入静默集合。退役请求不补发 allow／deny、不重新冻结、不占用更新的请求；在途保存不被丢弃。
2. `onRequestClose` 在登记新 ID 前先退役 `openCloseIds` 中所有其他未决 ID；若当前冻结属于其他 ID，退役后按既有规则释放冻结（宿主只会在上一请求结束后开始新请求，新 ID 到达即为其权威依据）。
3. `onCloseAborted` 不变更语义：迟到的撤销通知对已退役 ID 成为幂等空操作；仅当没有更新的关闭请求在处理时才提示“可以继续编辑”，避免新关闭进行中弹出误导提示。
4. 边界保持：通信失败与页面自有查询超时仍不视为权威取消；同 ID 重复请求仍幂等；最终 closing 后迟到请求／通知仍被忽略。

**变化文件（SHA256 前 16 位）：**

| 文件 | SHA256 前 16 位 |
| --- | --- |
| `frontend/src/d1/App.vue` | `7b9521b2f5e5fef6` |
| `frontend/src/d1/d1.components.test.mjs` | `8e55c0e0f3ddada8` |
| `desktop/d1_main.py`（验证驱动：close-order／save-dialog 阶段与预览状态记录） | `d892391b37b8a53a` |

未变化文件保上轮身份：`leave.ts` `664b37cd9f8569a9`、`ExportDialog.vue` `576b35a585bbcd3b`、`SettingsView.vue` `59d06a1b43dec0e6`、`d1_host_api.py` `e5c11baf3e5455e0`；backend 声明／锁（`e5f948d2…`／`cc589c0a…`）与 D1 锁（`c0b73435…`／`db1a0e58…`）散列不变。

### 16.2 先补失败回归（修复前实际输出，保留）

**组件（真实 SFC setup＋真实 Vue refs／watch＋受控桥；`node src/d1/d1.components.test.mjs`）：** 按 §13.3 反例新增 5 项（40→45），修复前逐项实际结果：

| 新增回归（阶段） | 修复前实际结果（exit 1） |
| --- | --- |
| 宿主已超时 A、撤销丢失、B 先送达，保存结束（原生保存等待） | `B must not be denied or occupied by the replaced A — false !== true`（B 被旧 A 判 busy 发 deny） |
| A 在 IME settle 等待中被 B 接替 | `timed out waiting for B settle pending`（B 被判 busy，未进入自身路径） |
| A 在协调器数据库保存中被 B 接替 | `1 !== 0`（保存未结束，B 已发 deny） |
| A 已在等旧桥回包、B 先送达 | `B must not be denied by the stranded A wait — false !== true` |
| A 撤销迟到但先于保存结束送达（保护项） | 修复前即通过（对照）；修复后仍通过 |

日志：`prefix5-components-first-failure.log` 与 `prefix5-components-subset1..4.log`（首次失败与逐项子集日志；subset1–3 为新增反例的 exit 1 与断言原文，subset4 为保护项通过）。

**窗口级正向失败：** 用修复前 9a8e90c8… 包内前端资产（旧 App.vue）运行新的 `close-order` 阶段：exit 3、`ok=false`；主机侧记录旧 A 与 B 都发出 `allow:true`（A 的迟到许可被真实宿主按“非当前请求”拒绝），检查 `close_order_a_silent=false`、`close_order_b_single_allow=false`；修复后的同一阶段为空 A 许可、单一 B 许可。日志 `close-order-prefix-buggy.log`／JSON 保留。

**驱动自身首次失败（保留，不补造根因）：**

- `close-order` 首次源码运行：阶段在真实关窗后仍在写主机侧结论，主线程先把摘要写出，JSON 少 4 项检查、`close_order` 为空（`close-order-delayed.log` 保留首次过程）；修复为 `run_selftest` 在 close-order 阶段等 `close_order` 结论有界出现后写摘要，不改产品行为。
- `save-dialog` 前三次源码尝试（`save-dialog.json`／`save-dialog2.json`／`save-dialog3.json`，均 exit 3）：①② 第二轮导出后 `runConfirmed` 因上一轮残留 ack 上下文追加一次导出，第二名原生对话框无人处理而挂起（`timeout_state.phase='idle'／busy=true`）；③ 占用目标时对“确认另存为”使用同步 `SendMessage` 点击，跨线程等待对话框内嵌套消息循环而死锁。最终改为每个用例先关闭／重开导出对话框取得干净 ack 上下文、按钮点击用 `PostMessage`、循环处理确认对话框（`save-dialog4.json` 全通过）；原始尝试与日志全部保留。

### 16.3 自动检查（最终一轮命令与结果）

命令工作目录：后端 `backend`、前端 `frontend`、桌面 `desktop`；均使用测试自身的临时合成库，清除继承的 `KGM_*`。

| # | 命令 | 结果 |
| --- | --- | --- |
| 1 | `python.exe -X utf8 -m unittest discover -s tests/local -t . -v` | **133 项，0 skip，exit 0**（83.327s） |
| 2 | `python.exe -X utf8 -m unittest tests.unit.test_i3_content_validation tests.unit.test_security tests.unit.test_calendar_boundaries tests.unit.test_i3_api_schemas tests.unit.test_i5_export_read_service` | **108 项，0 skip，exit 0** |
| 3 | `.venv-d1/Scripts/python.exe -X utf8 -m pytest tests/ -q -p no:cacheprovider` | **136 passed，exit 0**；2 项依赖弃用警告 |
| 4 | `npm run test:d1` | 纯逻辑套件 OK＋**45 项组件级异步回归**（40→45），exit 0 |
| 5 | `npm run typecheck`、`npm run build:d1` | 均 exit 0；构建输出 `d1.html`＋`index--wglywrR.js`＋`index-ILAyuRJW.css`，保留大于 500kB 分块提示 |
| 6 | `uv pip check`（backend／desktop） | 26／46 包兼容，exit 0 |

后端全套与 5 组回归为保留回归（本片未改后端）；组件新增 5 项中 4 项为“正向失败→修复后通过”，1 项为保护项。

### 16.4 真实窗口补验（源码）

`--phase close-order`（新增，§13.3 的通知顺序）：慢真实原生保存进行中关闭 A；宿主真实超时（同一路径，界缩短为 5 秒）将 A 置 canceled 并由验证包装暂扣 `close_aborted`；再次关窗产生 B 并先送达页面（页面此时仍没有 A 的撤销通知）；随后按变体释放／丢弃撤销；保存结束后旧的 A 零许可，B 自己发出 `allow=true` 并被真实宿主接受关闭窗口。源码延迟与丢失两变体各 **13/13 checks**、exit 0：

| 变体 | 主机侧结论（JSON） |
| --- | --- |
| `--close-order-abort delayed` | 单一 `complete_close`＝B `allow=true`；A 仅有 `timeout` 记录且送达晚于 B 的送达；`save_done ≤ allow`；A 状态 `unknown`、B `closing` |
| `--close-order-abort lost` | 同上；A 的撤销通知完全未送达，B 仍正常收口（不依赖旧通知） |

`--phase save-dialog`（新增，§14.6 最短步骤的真实对话框版，**不使用**预授权保存目录）：真实原生另存为对话框由驱动进程用 Win32 消息设置全路径（剪贴板＋`WM_PASTE`，IFileDialog 不响应 `WM_SETTEXT`）并点击真实“保存(&S)／取消／是(&Y)”按钮；4 个用例 **8/8 checks**、exit 0：

| 用例 | 窗口内结果 |
| --- | --- |
| A 中文名另存为 | 1 个真实对话框；中文路径粘贴成功；页面 `saved`，`saved_filename=中文名-真实验证.docx`；落盘 14,165 字节、必要 XML 解析通过 |
| B 取消 | 真实“取消”按钮；页面 `canceled`；目录清单前后一致（零写入） |
| C 真实占用失败 | 目标文件被另一句柄以 `FILE_SHARE_READ` 占用（非模拟）；确认“是(&Y)”后页面 `save_failed`；旧目标字节原样、无 `.tmp` 残留 |
| D 解除后新 ID 重试 | 释放占用后再次导出（新 operation ID `84218b2b…≠` 失败 ID `3d3629c0…`）；确认后 `saved`；目标文件为有效 DOCX 且字节数吻合（旧内容被原子替换） |

`--phase fix-regression2`（回归）：源码 **32/32 checks**、exit 0（原 31 项全部保留）；预览场景补强为记录真实响应 `status=200` 且等组件处理完成（按钮退出 loading）后再断言旧预览被丢弃、草稿保留、apply 无回执；真实 30 秒超时（29.0s）与“保存结束≤许可”顺序记录保留。

**证据分类：** close-order＝**真实宿主**状态机与真实 `evaluate_js` 通知＋真实原生保存（驱动临时减慢一次落盘），页面包装仅记录不改行为；save-dialog＝**真实原生对话框**（驱动 Win32 自动化，非预授权目录、非人手动点击）；fix-regression2 的受控桥注入（丢回包／构造 pending）、真实宿主超时与程序化 `CompositionEvent` 继续分别记录；**实际输入法按键未执行**。

### 16.5 新包、仓外运行与 Word 样本

**构建与身份：** `desktop/build_d1.py --skip-frontend --hash-out <证据>/package/package-hashes-fix5.json`，exit 0；`KGNext-D1Verify` **180 文件**，EXE 14,721,796 字节、SHA-256 `167b352b9465a546f0a0c8ee964bb4996bae1b147d01058161eacde638ba5385`。仓内与仓外复制各 180/180 文件与清单逐一相符（无缺失／额外／大小／散列差异）；`verify-package.py` 确认 8 个关键归档模块（`d1_main`、`d1_host_api`、`d1_paths`、`d1_server`、`config_service`、`config_tokens`、`daily_plan_service`、`migrate`）与当前源码一致、前端 `d1.html`＋2 assets 与构建输出逐字节一致、迁移／模板资源存在，problems=0。较上轮 137 文件多出的 42 个 `api-ms-win-*.dll` 与 `ucrtbase.dll` 来自 PyInstaller 对新增 `ctypes` 导入（验证驱动用 Win32 消息操作真实对话框）的系统 DLL 收集；`_ctypes.pyd`／`libffi-8.dll` 上轮已在包内。上一轮 9a8e90c8… 包（保留为 `KGNext-D1Verify-9a8e90c8`）及更早包、全部旧失败证据未动。

**仓外运行：** 包复制到 `<证据>/package-outside`，从不同 cwd（`<证据>/run-cwd`）启动，驱动进程剥离全部继承 `KGM_*` 后注入合成数据／预授权导出目录（`save-dialog` 阶段不注入预授权目录）。**9 个独立进程实际 returncode 全部 0**，逐进程记录于 `package-logs/pkg-phases-result.json`：

| 进程 | 阶段 | 返回码 | checks |
| --- | --- | --- | --- |
| 1 | `first` | 0 | 6/6 |
| 2 | `restart` | 0 | 6/6 |
| 3 | `fix-regression` | 0 | 28/28 |
| 4 | `fix-regression2` | 0 | 32/32 |
| 5 | `close-order --close-order-abort delayed` | 0 | 13/13 |
| 6 | `close-order --close-order-abort lost` | 0 | 13/13 |
| 7 | `save-dialog` | 0 | 8/8 |
| 8 | `verify` | 0 | 5/5（原文断言=“设置离开最终文本”，v13 为读回观察值） |
| 9 | `clean-ime-close` | 0 | 4/4 |

合成库（只读核对）：`local_alembic_version=20261014_0003_local`；2 计划（09-15=v14、09-16=v2）、16 内容、18 操作记录、1 日历修订、1 配置操作；`foreign_key_check` 空、`integrity_check=ok`、`journal_mode=wal`；09-15 原文“关窗前组合最终文字”。结束后无包进程残留。

**Word 样本：** 本轮包导出的 4 份样本与 §14.5 所记、且已由[审阅 §13.5](desktop-d1-review.md#135-补验证据与未验边界)沿用目视复核的样本**逐字节一致**（A `1b3d4e21…` 14,021；B `05bff8c2…` 14,165；C `6313a2c1…` 14,443；D `2d1adb2e…` 14,038；明细 `package/word-samples-compare.json`），内容与渲染链未变，沿用 2／2／5／2 页与既有目视复核范围，本轮无需补页。`save-dialog` 用例 A 另存的中文名文件 `中文名-真实验证.docx`（14,165 字节、有效 DOCX）保留在 `package-saves/native-dialog/`。

### 16.6 未验边界与再次复审条件

**Codex第五轮复审注记（2026-10-16）：** 最终结论见[审阅§14](desktop-d1-review.md#14-d1b-第五轮修复复审2026-10-16)。上轮R1反例通过，但旧request_close(A)本身迟到会错误退役当前B，R1/P2保留；真实窗口占用失败的result_text含绝对路径，新增R16/P2。累计16项中14项关闭，D1B仍不放行。原生对话框Win32自动化已补上真实文件交付证据，不能再称只有预授权目录写入；规格§13.2不要求所有动作均由人点击，“仍需人工步骤”保留为体验未验，不单独否定工程实测。

本轮独立核实仓内／外180文件、8关键归档模块、独立前端构建、9进程返回码及阶段JSON、最终合成库和4份同字节Word样本。更正三项证据表述：①43个新增DLL实际来自Codex缓存的native/libheif/libheif/bin，按当前PATH选中，不能确认“新增ctypes导入必然导致”该收集；保留干净构建／发行可再现性边界，未据此新增运行缺陷。②§16.4“源码”表中中文名保存14,165字节实际为包样本，源码save-dialog4.json为14,021字节，均有效。③最终源码预览32项证据为fix-regression2b.json，旧fix-regression2.json的31项保留。取消dialog_count=2不能推断为两次独立保存，驱动未记录HWND；第三次SendMessage失败的具体首阻塞按钮不能从日志精确确认。前两次runConfirmed重复调用原因已由实际SFC和真实按钮路径对照支持。历史失败不抹去；原实现记录与本注记合并读取。

1. **保持未验：** 真实原生另存为对话框本轮由驱动进程以 Win32 消息操作真实对话框完成（中文文件名、取消、真实占用失败、解除后新 ID 重试、旧目标保护），**不是人手动点击**；仍需一次人手动执行 §14.6 最短步骤。实际中文输入法按键未执行；真实窗口内的宿主内部“许可与保存交错”注入、WPS、干净机器、Windows 10、其他 DPI、多显示器与教师本人体验保留后续边界。真实教师数据与旧远程资源未触碰。
2. **证据根：** `%TEMP%\opencode\kgm-d1b-fix5-20261016\`（`prefix\`：修复前组件失败与子集日志、修复后组件／纯逻辑／typecheck／桌面／后端日志；`source-run\`：close-order 两变体与修复前反例、save-dialog 三次失败与最终 JSON、fix-regression2；`package\`：`package-hashes-fix5.json`、`manifest-repo.json`／`manifest-outside.json`、`verify-package.py`／`package-verify.json`、`compare-manifest.py`、`run-outside.py`、`final-source-hashes.json`、`word-samples-compare.json`、`db-check.json`、`probe-dialog*.py/out`；`package-outside\`、`package-data\`／`package-saves\`、`package-logs\`（逐阶段 JSON 与 `pkg-phases-result.json`）、`word-samples\`、`git-diff-check.log`；临时路径不保证长期留存，关键结论以本节为准）。
3. **再次复审条件：** R1 新通知顺序有先失败回归（组件 4 项＋窗口级反例）、实现改动与真实窗口两变体补验；R6 及其他 13 项保护回归保留；新包身份与源码一致、仓外 9 进程返回码逐进程留存；交 Codex 独立复审 R1 关闭与本片必要证据，满足后才工程放行。产品验收、发行与后续切片不因本节自动成立；不自动启动 D2、AI、WebDAV 或发行。

## 17. D1B R1 旧 request 通知生命周期与 R16 保存错误脱敏（2026-10-16 第六轮）

依据[审阅 §14.3](desktop-d1-review.md#143-r1--p2迟到的旧请求通知退役当前请求)、[§14.4](desktop-d1-review.md#144-r16--p2保存异常未脱敏即返回桥与页面)、[§14.7 接续](desktop-d1-review.md#147-接续与文档归并)与[当前任务](../tasks/current.md)，只修 R1“迟到的旧 request_close 通知退役当前请求”与 R16“保存异常未脱敏”，含 R6 的 14 项已关闭保护与其回归保留，不扩大重构。环境仍为 `desktop/.venv-d1`（CPython 3.14.7／Windows x64／标准 GIL、SQLite 3.50.4；`uv pip check` backend 26 包、desktop 46 包兼容，exit 0），未安装或升级依赖，未改 backend 声明／锁与 D1 锁，未读真实 `.env`／密钥／教师库，未连接旧 MySQL／远程业务，未调用真实 AI。本节不自行写成 Codex 已关闭或 D1B 已放行。

### 17.1 R1 改动：以宿主当前请求确认为准，不依赖通知抵达顺序

页面（`frontend/src/d1/bridge.ts`、`frontend/src/d1/App.vue`）：

1. 新增 `confirmCurrentCloseRequest(id)`：向宿主 `get_close_state(id)` 连续取得两次 `pending` 才把该 id 视为宿主的当前关闭请求。单个回答可能是旧答案（产生于该 id 仍当前时、在新请求出现后才送达），第二次查询只在收到第一问之后发出，因此宿主已移动位置时不可能再答 `pending`；每次尝试 2s 上限，传输失败各阶段重试 2 次（间隔 120ms），其他状态（canceled／unknown／closing）或无法取得回答都返回未确认。
2. `onRequestClose` 在确认前完全静默：不登记 handler、不退役任何请求、不发 allow／deny；`verifyingCloseIds` 对并发重复通知同步去重。仅在确认当前后，才按 ID 退役其他开放 handler 与协调器等待，再进入既有设置草稿／原生保存／协调器流程。
3. 新增 `waitForCloseVerifications()` 门（10s 有界）：在 `finishClose` 发送允许前、以及原生保存等待结束后复核。若保存恰在“新请求确认中”结束，被替代的旧 A 等确认落定、由新请求退役后保持静默；据此上轮“B 先于 abort(A) 退役旧 A”的保护在异步确认下仍然成立。
4. 既有保护不变：同 ID 幂等、最终 closing 冻结、通信失败不当作权威取消（保持冻结／保留请求）、在途原生保存与桥回包等待照常消费、旧回包与旧通知不触碰新请求。

宿主（`desktop/d1_host_api.py`）：`_safe_notify_page` 在调用通知回调前于协调器锁内复核 `current_id == request_id 且 state == pending`；已被替代或已解决的通知不再送达。通知回调运行后的抵达顺序仍无保证，因此权威判断在页面侧完成；页面与宿主同包发布，探针验证需要能回答 `get_close_state`（通信失败按未确认、静默处理）。

### 17.2 R16 改动：稳定的脱敏失败原因

`write_docx_atomic` 与 `D1HostApi` 的对外边界不再拼接原始异常：

- 提交前 `OSError` 统一经 `_classify_write_failure`：`SAVE_TARGET_IN_USE`（共享冲突，或访问被拒后占用探针成立：目标 `r+b` 打开成功／共享冲突，或打开被拒但 `os.access(W_OK)` 为真）、`SAVE_PERMISSION_DENIED`（访问被拒且目标不可写）、`SAVE_IO_ERROR`（磁盘空间不足／保存位置不存在／其他 I/O）。
- 对话框异常在 `_perform_save` 转为固定 `SAVE_DIALOG_FAILED`；内层 `_save_docx_inner` 与桥最外层 `save_docx` 兜底为固定 `SAVE_FAILED` 文案；宿主诊断日志只记录异常类型名（不含消息／路径）。
- 提交后核验失败保持 `status=unknown`（`SAVE_RESULT_UNKNOWN`，“文件可能已写入，请核对”），不改成 failed、不声称旧目标未变。
- DOCX 解析／读取错误只保留固定原因（不再附解析位置等异常细节）；同 ID 幂等缓存查询、不同载荷冲突、旧文件保护、临时文件清理与解除后新 ID 重试均不变。

### 17.3 变化文件（SHA256 前 16 位）

| 文件 | 上一轮 | 本轮 |
| --- | --- | --- |
| `frontend/src/d1/App.vue` | `7b9521b2f5e5fef6` | `0ed0b8e8ccd8991b` |
| `frontend/src/d1/bridge.ts` | `0ba1267ea65560e7` | `6b3132235a01d458` |
| `frontend/src/d1/d1.components.test.mjs` | `8e55c0e0f3ddada8` | `8826e087d7fd09d6` |
| `desktop/d1_host_api.py` | `e5c11baf3e5455e0` | `f49fb4ffd0578954` |
| `desktop/d1_main.py`（驱动：request 变体与 R16 检查） | `d892391b37b8a53a` | `97cf90a528d4cea9` |
| `desktop/tests/test_d1_close.py` | `0f7e8244f66a1cce`（第三轮后未变） | `ab109d785cc1baad` |
| `desktop/tests/test_d1_host_save.py` | `aeef93134b73b1f3`（第三轮后未变） | `9630a66168bdf41f` |

未变化保留上轮身份：`leave.ts` `664b37cd9f8569a9`、`ExportDialog.vue` `576b35a585bbcd3b`、`SettingsView.vue` `59d06a1b43dec0e6`、`d1.test.mjs` `77d15ae657e98a95`、`build_d1.py`、backend `pyproject.toml`／`uv.lock`（`e5f948d2…`／`cc589c0a…`）与 D1 锁（`c0b73435…`／`db1a0e58…`）散列不变；`final-source-hashes.json` 14 文件快照仅上述 5 个文件变化。

### 17.4 先补失败证据（保留，不补造根因）

1. **组件反例（按到达顺序信任的等价变异）**：把确认函数临时改为恒真（等价修复前“不同 ID 到达即退役”的行为），新增 4 项回归逐项实际失败：A 迟到被处理并到达桥（`the stale A stays silent — 2 !== 0`，exit 1）；旧 A 先到被登记（`1 !== 0`，exit 1）；权威查询失败仍处理（`1 !== 0`，exit 1）；“确认窗口内保存结束”保护项在变异下也通过（该保护本就在实现内，exit 0）。日志 `prefix/components-prefix-mutation.log`。
2. **宿主 R16 反例（恢复原始异常文案的等价变异）**：`TestFailureDesensitization` 5 项与提交点测试逐项失败（6 failed／23 passed，exit 1），失败点即“响应／缓存含路径或异常细节、分类非占用”。日志 `prefix/desktop-prefix-mutation.log`。
3. **宿主通知线程复核后的既有计数等待竞态**：临时还原旧“只等第一条通知”的助手时，6 项用例失败（6 failed／11 deselected，exit 1）；恢复为按期望条数确定性等待后 17 passed。日志 `prefix/desktop-close-wait-first-failure.log`。
4. **`save-dialog` 源码首跑（真实占用分类）**：exit 3，唯一失败项 `save_dialog_locked_reason_desensitized`；原因是占用探针误判为权限（`SAVE_PERMISSION_DENIED`），JSON 与启动日志保留为 `source-run/save-dialog-first-failure.json/.log`；修正探针后 9/9 通过。
5. **窗口级修复前反例（167b352b 前端 + 新驱动）**：`close-order --close-order-request delayed` exit 3；旧页面把迟到的 A 当新请求、A 发出 `allow=True`、B 停留在 `pending`，false 检查 `close_order_a_silent`／`close_order_b_single_allow`／`close_order_b_host_closing`（`source-run/close-order-request-delayed-prefix-167b.json`）。另保留更早 9a8e90c8 前端的运行作为历史谱系对照：该更早页面表现为 A 发 deny、B 允许并关闭（不同的旧实现时序，不混为一谈）。
6. **同 tag 样本首轮对比**：比较脚本漏跑 `verify` 阶段时 B 样本停留在 first 阶段内容（`word-samples-compare-first-attempt.json` 保留）；按完整阶段谱系修正后逐字节一致（见 §17.8）。

### 17.5 自动检查（最终一轮命令与结果）

后端命令工作目录 `backend`，环境 `APP_DISABLE_DOTENV=1`、`PYTHONIOENCODING=utf-8`、`-X utf8`；完整本地套件设临时数据根兜底（不注入父级 DB 路径），其余按用例自身隔离；前端／桌面在各自目录。

| # | 命令 | 结果 |
| --- | --- | --- |
| 1 | `python.exe -X utf8 -m unittest discover -s tests/local -t . -v` | **133 项，0 skip，exit 0**（150.540s；后端本片未改） |
| 2 | `python.exe -X utf8 -m unittest tests.unit.test_i3_content_validation tests.unit.test_security tests.unit.test_calendar_boundaries tests.unit.test_i3_api_schemas tests.unit.test_i5_export_read_service -v` | **108 项，0 skip，exit 0**（0.480s） |
| 3 | `.venv-d1/Scripts/python.exe -X utf8 -m pytest tests/ -q -p no:cacheprovider` | **142 passed，exit 0**（136→142：R16 5 项＋通知复核 1 项）；2 项依赖弃用警告 |
| 4 | `npm run test:d1` | 纯逻辑套件 OK＋**49 项组件级异步回归**（45→49），exit 0 |
| 5 | `npm run typecheck`、`npm run build:d1` | 均 exit 0；构建输出 `d1.html`＋`index-BZikfdrE.js`＋`index-ILAyuRJW.css`，保留分块大小提示 |
| 6 | `uv pip check`（backend／desktop） | 26／46 包兼容，exit 0 |

新增回归覆盖（先失败后修复）：组件——旧 request 迟到不退役当前 B 且重复迟到静默、旧 request 先到被拒绝、权威无法确认完全静默、“确认窗口内保存结束”门保护；宿主——占用失败首答／缓存脱敏且分类为占用、对话框失败、内层兜底、桥最外层兜底、坏 XML 无解析细节、提交后核验仍 unknown 且脱敏、被替代或已解决请求不再重复通知。旧反例与 14 项已关闭保护全部保留并通过。

### 17.6 真实 WebView2 补验（源码与包内）

`desktop/d1_main.py` 新增 `--close-order-request delayed|lost` 两变体（`--phase close-order` 家族）：慢真实保存进行中关闭 A，A 的 **request 通知**被暂扣／丢弃；宿主真实超时（5s 同路径）后 `abort(A)` 先真实送达；随后关闭 B，B 先到页面；再按变体释放（并重复一次）或永不送达 A 的 request；保存结束后旧的 A 零许可、B 单独发出 `allow=true` 并被真实宿主接受关闭窗口。源码两变体 **16/16、15/15 checks**、exit 0；包内同样 **16/16、15/15**、returncode 0。关键记录（源码／包一致）：`received=[B, A, A]`（延迟）或 `[B]`（丢失）、`held_requests=[A]`、`aborted_calls=[(A, timeout)]`、`complete_calls=[B allow=True]`、`host_state_a=unknown`、`host_state_b=closing`、`save_done ≤ allow`。

`save-dialog` 阶段新增 R16 检查并复用既有 4 用例：真实占用失败时首答、`get_save_result` 缓存与页面 `result_text` 三处均为 `SAVE_TARGET_IN_USE`“目标文件正被其他程序占用…”固定文案，无目录、目标名、`.tmp` 或 `WinError` 文本；旧目标字节保持、无临时残留；解除后新 ID 重试成功。源码 9/9、包内 9/9、exit 0；真实中文名另存为 14,165 字节、取消零写入、重试写入均保持上轮证据。

**口径：** close-order request 变体为真实宿主状态机、真实保存与真实 `evaluate_js` 通知，页面包装仅记录不改行为；save-dialog 为真实原生对话框（驱动 Win32 消息，非预授权目录、非人手动点击）；受控桥注入与程序化 `CompositionEvent` 的既有证据边界不变；**实际输入法按键、宿主内部许可／保存交错注入未执行**。

### 17.7 新包、构建来源与仓外运行

**构建与身份：** `desktop/build_d1.py --skip-frontend --hash-out <证据>/package/package-hashes-fix6.json`，exit 0；`KGNext-D1Verify` **137 文件**，EXE 14,726,530 字节、SHA-256 `8d1a4dbb3a97987552c16b0e7a5d2122d50da27c72e4df9afc1a12aee4a59199`；上一轮 167b352b… 包保留为 `KGNext-D1Verify-167b352b`，更早各包与全部旧失败证据未动。仓内与仓外复制各 137/137 文件与清单相符（无缺失／额外／大小／散列差异）；`verify-package.py` 确认 8 个关键归档模块（`d1_main`、`d1_host_api`、`d1_paths`、`d1_server`、`config_service`、`config_tokens`、`daily_plan_service`、`migrate`）与当前源码一致、前端 `d1.html`＋2 assets 与构建输出逐字节一致、迁移／模板资源存在，problems=0。

**构建来源记录（只记事实）：** 本轮 `COLLECT-00.toc` 共 18 个二进制，全部来自 `C:\Python314`（python314.dll、VCRUNTIME140、sqlite3、libffi 等）与 `desktop/.venv-d1/Lib/site-packages`（pywebview／pythonnet／clr_loader）；**上一轮的 42 个 `api-ms-win-*.dll`＋`ucrtbase.dll`（共 43 文件）本轮未再收集**，TOC 中无 `api-ms-win`／`ucrtbase`／`libheif`／`codex-runtimes` 记录。这与上轮已核实的“按构建环境 PATH 从该缓存目录选中”一致：DLL 收集随构建环境变化，未将它与新增 ctypes 写成因果关系；干净构建／发行再现性边界保留，不据此新增运行缺陷、不清理环境。

**仓外运行：** 包复制到 `<证据>/package-outside`，从不同 cwd（`<证据>/run-cwd`）启动，驱动进程剥离全部继承 `KGM_*` 后注入合成数据／预授权导出目录（`save-dialog` 阶段不注入预授权目录）。**11 个独立进程实际 returncode 全部 0**，逐进程记录于 `package-logs/pkg-phases-result.json`：

| 进程 | 阶段 | 返回码 | checks |
| --- | --- | --- | --- |
| 1 | `first` | 0 | 6/6 |
| 2 | `restart` | 0 | 6/6 |
| 3 | `fix-regression` | 0 | 28/28 |
| 4 | `fix-regression2` | 0 | 32/32 |
| 5 | `close-order --close-order-abort delayed` | 0 | 13/13 |
| 6 | `close-order --close-order-abort lost` | 0 | 13/13 |
| 7 | `close-order --close-order-request delayed` | 0 | 16/16 |
| 8 | `close-order --close-order-request lost` | 0 | 15/15 |
| 9 | `save-dialog` | 0 | 9/9 |
| 10 | `verify` | 0 | 5/5（原文断言=“设置离开最终文本”） |
| 11 | `clean-ime-close` | 0 | 4/4 |

合成库（只读核对，`package/db-check.json`）：`local_alembic_version=20261014_0003_local`；2 计划（09-15=v14、09-16=v2）、16 内容、18 操作记录、1 日历修订、1 配置操作；`foreign_key_check` 空、`integrity_check=ok`、`journal_mode=wal`；09-15 原文“关窗前组合最终文字”。11 份启动日志均有启动与正常返回；运行结束后无 `KGNext-D1Verify.exe` 残留。

### 17.8 Word 样本

本片未改导出读取／映射／生成器与模板（backend 未变化），样本差异只可能来自驱动写入的合成内容。用与上轮已目视复核样本相同的阶段谱系与同一 session tag（FIX3）经新包重跑（`first→restart→fix-regression→fix-regression2→verify`，5 进程 returncode 全 0），4 份样本与上轮样本**逐字节一致**（`package/word-samples-compare.json`，`all_identical=true`）：

| 样本 | 字节 | SHA-256 前 16 位 |
| --- | --- | --- |
| 样本A-空内容-按周.docx | 14,021 | `1b3d4e21da0d7a7b` |
| 样本B-代表性-单日.docx | 14,165 | `05bff8c24cd77d7c` |
| 样本C-长内容-两份.docx | 14,443 | `6313a2c17b9a7006` |
| 样本D-第二日期-单日.docx | 14,038 | `2d1adb2e4e56975a` |

按既定规则（样本或渲染链变化才补 Word 页），本轮**无需补页**，沿用既有 2／2／5／2 页与目视复核范围；不声称本轮重新打开 Word。

### 17.9 未验边界与再次复审条件

1. **保持未验：** 实际中文输入法按键（程序化 `CompositionEvent` 与真实 HTTP 保存链路有记录，但不等于实际按键）；真实窗口内宿主内部“许可与保存交错”注入（仍以已关闭的 R11 线程探针为证据）；人手动原生另存为点击（Win32 驱动自动化已完成真实对话框文件操作，非人工）；WPS、干净机器、Windows 10、其他 DPI、多显示器与教师本人体验保留后续边界。真实教师数据与旧远程资源未触碰。
2. **证据根：** `%TEMP%\opencode\kgm-d1b-fix6-20261016\`（`prefix\`：变异与首跑失败日志、最终组件／纯逻辑／typecheck／build／桌面／后端日志；`source-run\`：request 变体两 JSON／日志、save-dialog 首跑失败与最终 JSON、修复前反例、`source-phases-result.json`；`package\`：`package-hashes-fix6.json`、`manifest-repo.json`／`manifest-outside.json`、`verify-package.py`／`package-verify.json`、`run-outside.py`、`compare-run.py`、`compare-manifest.py`、`final-source-hashes.json`、`word-samples-compare*.json`、`db-check.py`／`db-check.json`；`package-outside\`、`package-data\`／`package-saves\`、`package-logs\`（逐阶段 JSON 与 `pkg-phases-result.json`）、`word-samples\`、`git-diff-check.log`；临时路径不保证长期留存，关键结论以本节为准）。
3. **再次复审条件：** R1 旧 request 生命周期（页面权威确认＋宿主送达前复核）有先失败回归、实现改动与真实窗口（源码＋包内）两变体补验；R16 有真实占用下首答／缓存／页面三处脱敏断言与修复前等价变异失败；R6 及其他 13 项保护回归保留；新包身份与源码一致、仓外 11 进程返回码逐进程留存；交 Codex 独立复审 R1／R16 关闭与本片必要证据，满足后才工程放行。产品验收、发行与后续切片不因本节自动成立；不自动启动 D2、AI、WebDAV 或发行。


### 17.10 第六轮独立复审补充（Codex，2026-10-16）

[审阅§15](desktop-d1-review.md#15-d1b-第六轮修复复审2026-10-16)确认本节旧request通知反例已修复，R16真实占用首答／缓存／页面脱敏、异常边界与提交后unknown语义通过，**R16关闭**。但§17.1“两次pending可确认当前”的论证未覆盖第二次回答本身迟到：B已确认后，旧A最后一问仍可退役B，R1/P2保留。另新增R17/P1：finishClose在协调器最终输入检查后等待确认，此时仍可编辑，等待结束未重查dirty便发送allow，可能丢失未保存内容。两条正向探针均实际exit 1，复现与修复判据见审阅§15.2–15.3，不改写本节原始实施和自测事实。

独立133本地／108回归／142桌面、纯逻辑＋49组件及类型检查／构建通过；8d1a4dbb…包仓内仓外各137文件、8归档模块、前端和资源同源。11进程返回码和真实窗口日志核对有效；本轮Codex未重跑GUI。四份Word样本对应本轮同tag的package-compare-saves，与既有已目视样本逐字节一致，普通FIX6的package-saves不能与该组混用。当前18个二进制与TOC来源文件相符，上轮43个缓存来源DLL本包未再收集；干净构建／发行再现性仍未验。

累计17项中15项关闭，R16／R6保持关闭，**D1B仍不放行**。实际IME按键、宿主内部许可／保存交错真实窗口注入、手动教师体验与发行兼容边界继续保留。下一步见[唯一当前任务](../tasks/current.md)，优先修R17，再收束R1并补相关窗口和同环境包证据；工程收口后教师体验，再准备D2规格。本轮没有代写实现、安装、提交／推送、派发其他聊天或启动后续切片。

## 18. D1B R17 最终核对窗口与 R1 代际绑定修复（2026-10-17 第七轮）

依据[审阅 §15.2](desktop-d1-review.md#152-r17--p1最终检查后的等待允许新输入却仍放行关闭)／[§15.3](desktop-d1-review.md#153-r1--p2第二次确认回包也会迟到并退役当前b)与[当前任务](../tasks/current.md)：先修 R17“关闭最终核对后的等待仍可编辑，等待结束未复核便放行”，再收束 R1“第二次确认回包迟到仍可退役当前 B”。不改 §11–13 的产品行为，不重开 R16／R6 等 15 项已关闭问题。环境仍为 `desktop/.venv-d1`（CPython 3.14.7／Windows x64／标准 GIL、SQLite 3.50.4；`uv pip check` desktop 46 包、backend 26 包兼容，exit 0），未安装或升级依赖，未改 backend 声明／锁与 D1 锁，未读真实 `.env`／密钥／教师库，未连接旧 MySQL／远程业务，未调用真实 AI。本节不自行写成 Codex 已关闭或 D1B 已放行。

### 18.1 R1 改动：宿主请求代际绑定确认，过期确认在 await 后拒绝

宿主（`desktop/d1_host_api.py`）：

1. `CloseCoordinator` 在锁内维护递增的请求代际：`_begin_request` 分配 `_current_generation`，与请求 ID 同生命周期；被替代或结束时旧 ID 只答 `unknown`。
2. 新增 `state_answer(close_request_id)`：当前请求返回 `{"state": <pending/canceled/closing>, "generation": <本次代际>}`，其他 ID 返回 `{"state": "unknown"}`（无代际）。`D1HostApi.get_close_state` 改用它；`complete_close`／`state()` 的既有语义不变。
3. `_safe_notify_page(request_id, generation)` 在锁内复核当前 ID／状态后把代际随通知交给页面；`D1HostApi._notify_request_close(id, generation)` 生成 `onRequestClose(id, generation)`。复核与送达之间仍无顺序保证，权威判断仍在页面侧。

页面（`frontend/src/d1/bridge.ts`、`frontend/src/d1/App.vue`）：

4. `confirmCurrentCloseRequest` 改为返回 `{generation}` 或 `null`：要求连续两次 `pending`、两次回答携带相同且为正整数的代际；缺代际、代际不一致、非 `pending` 或无法回答都不确认（旧“仅两次 pending”不再足够，回包迟到的第二问因此无法冒充当前请求）。
5. `App.vue` 新增 `acceptedCloseGeneration`：通知到达时若其代际 ≤ 已接受代际立即静默；每次 `await` 确认后再次比较，过期确认不退役任何请求、不发 allow／deny。确认通过的请求先在代际上记账，再按既有“新 ID 退役旧请求”逻辑处理，代际只增不减。
6. `onCloseAborted` 对“确认仍在进行中”（`verifyingCloseIds`）的请求也记录撤销；确认返回后的撤销检查补齐该阶段，确认中的撤销与迟到回包都不能复活旧请求。同 ID 幂等、最终 closing、通信失败保持冻结、在途保存照常消费等既有保护不变。

### 18.2 R17 改动：最终核对与冻结之间不再有可编辑等待

`App.vue` 的 `finishClose`（`frontend/src/d1/App.vue`）：

1. 进入时记录协调器 clean 检查所对应的编辑器 identity；等待“其他请求确认”的验证门（既有 R1 §14.3 保护）结束后，**再次** `settle()` 落定可能新开始的 IME 组合，然后**同步**复核 `dirty=false` 且 identity 未变，随即同步 `freezeForClose` 发送 allow——最后一次核对与冻结之间没有 await，不再存在可编辑等待窗口。
2. 等待期间出现新输入（普通输入、组合输入或 identity 变化）时按 §11.3“新输入留页”规则处理：取消本次关闭、保留内容并提示，随后释放宿主 pending（explicit deny），不丢字、不关窗；未新增保存轮次或自动重试规则。
3. 页面验证钩子 `window.__d1App.closeState()` 新增只读 introspection（open／verifying／aborted／acceptedGeneration／locked／finalAllowed／activeId），与 `__d1Editor` 同口径，供真实窗口驱动读取页面事实，不改变任何校验或保存路径。

### 18.3 先补失败证据（保留，不补造根因）

1. **纯逻辑反例（修复前的 confirm 只返回布尔）**：新增“两次 pending＋代际应返回 `{generation}`”等在旧实现下实际失败：`true` 与 `{ generation: 3 }` deepEqual **exit 1**（`prefix/pure-logic-first-failure.log`）。
2. **组件 R1 反例（审阅 §15.3 等价时序）**：A 第一问 pending 已到、第二问 pending 已生成未交付；A 超时（撤销先送／丢失两变体）；B 已确认；释放旧 A 第二问。旧实现下 A 退役 B 并发出 allow=true：`the stale A stays silent (abort delivered=true) — 1 !== 0`，**exit 1**（`prefix/components-first-failure.log`）。
3. **组件 R17 反例（审阅 §15.2 等价时序，真实 EditorView＋App）**：宿主当前 B；旧 A 查询回包暂扣；B 确认后经过 clean 检查进入 `finishClose` 等待；向真实编辑器模型输入新文字并更新 editEpoch；释放 A。旧实现下 `B allow=true` 且 dirty=true：`B must never allow while the real editor holds new unsaved input — 1 !== 0`，**exit 1**（`prefix/r17-components-first-failure.log`）。
4. **宿主反例**：`4 failed, 17 passed`——`state_answer` 不存在（AttributeError ×3）与真实 `js_bridge_call` 线程探针中暂扣回答仍为 `{"state": "pending"}` 无代际字段（`prefix/desktop-close-first-failure.log`）。
5. **源码首轮 request-lost 回归失败（新增驱动包装后的遗漏，保留）**：首轮全阶段源码运行中 `close-order-request-lost-regression` **exit 3**，`driver_error="close-order: A 的 request 通知未被暂扣"`——驱动暂扣包装未接收新增的代际参数，真实宿主侧通知未送达页面包装；补齐参数后同一环境重跑两变体均通过（`source-run/close-order-request-lost-regression.json`、`source-run/close-order-request-*.json` 保留）。

### 18.4 新增与适配的回归

组件（`frontend/src/d1/d1.components.test.mjs`，49→55 项）：

- `testCloseLateFinalConfirmationNeverRetiresCurrentB`：A 第二问 pending 已生成未交付，A 超时（撤销送达／丢失两轮），B 确认后释放旧 A 回包；A 零 complete_close、B 单次 allow=true、宿主 closing。
- `testCloseThreeGenerationsOnlyNewestActs`：A 最终回包暂扣、B 确认后被 C 替代、旧回包后到；A／B 静默、C 单独 allow。
- `testCloseStaleConfirmationWithoutGenerationStaysSilent`：缺代际的 pending 绝不确认。
- `testCloseGateTimeoutStillRechecksBeforeAllow`：三个旧请求确认交错暂扣使验证门超过 10s 有界期限；期限到时仍有确认在途，B 仍须先 settle 并复核编辑器（此处 clean）才 allow，旧请求全部静默；实际等待 ≥10s 由断言记录。
- `testCloseGateLateInputStaysAndKeepsInput`：真实 EditorView 在 B 等待窗口输入、递增 editEpoch；B 不发 allow、显式 deny、输入保留、零 PATCH。
- `testCloseGateCompositionInputSettlesBeforeDecision`：等待窗口中新组合输入未落定前不发 allow；组合结束提交文字后留页保字（R15 保留）。
- 既有测试适配：宿主模型加代际、手动 closeState 桩补代际、`finishClose` 二次 settle 使两个 IME 门测试按“显式完成信号”释放（无固定等待）。

纯逻辑（`frontend/src/d1/d1.test.mjs`）：新增确认绑定五组——同代际两 pending 确认、代际不一致拒绝、缺代际拒绝、非 pending／无法回答拒绝、传输失败重试后仍绑定代际（第一次失败重试共 3 次调用）。

宿主（`desktop/tests/test_d1_close.py`，17→21 项）：代际单调且随当前请求（替换后旧 ID 无代际）、通知携带代际且过期不重发、`D1HostApi.get_close_state` 暴露代际、真实 pywebview `js_bridge_call` 工作线程下“A 第二问 pending 生成于 A 仍当前、交付于 B 确认之后”——本体接收 `{"state":"pending","generation":2}`，迟到 A 的 allow 被拒 `{"accepted":false,"state":"pending"}`；`test_d1_host_save.py` 的通知桩同步适配。

### 18.5 自动检查（最终一轮命令与结果）

后端命令工作目录 `backend`，环境 `APP_DISABLE_DOTENV=1`、`PYTHONIOENCODING=utf-8`、`-X utf8`；完整本地套件设临时数据根兜底（不注入父级 DB 路径）；前端／桌面在各自目录。本轮未改后端代码。

| # | 命令 | 结果 |
| --- | --- | --- |
| 1 | `python.exe -X utf8 -m unittest discover -s tests/local -t . -v` | **133 项，0 skip，exit 0**（81.833s） |
| 2 | `python.exe -X utf8 -m unittest tests.unit.test_i3_content_validation tests.unit.test_security tests.unit.test_calendar_boundaries tests.unit.test_i3_api_schemas tests.unit.test_i5_export_read_service -v` | **108 项，0 skip，exit 0**（0.376s） |
| 3 | `.venv-d1/Scripts/python.exe -X utf8 -m pytest tests/ -q -p no:cacheprovider` | **146 passed，exit 0**（142→146）；2 项依赖弃用警告 |
| 4 | `npm run test:d1` | 纯逻辑套件 OK＋**55 项组件级异步回归**（49→55），exit 0 |
| 5 | `npm run typecheck`、`npm run build:d1` | 均 exit 0；输出 `d1.html`＋`index-1CjZ5jPO.js`＋`index-ILAyuRJW.css`，保留分块大小提示 |
| 6 | `uv pip check`（backend／desktop） | 26／46 包兼容，exit 0 |

### 18.6 真实 WebView2 补验（源码与包内）

`desktop/d1_main.py` 新增两个窗口阶段族（`drive_close_lastack`／`drive_late_input_close`），沿用真实宿主状态机、真实保存、真实 `evaluate_js` 通知与真实 `get_close_state` 桥调用；受控部分仅为按请求暂扣回答的宿主包装与页面审计包装（记录不改行为），窗口级完成信号取自页面 `__d1App.closeState()` 与实际调用记录，不使用固定等待替代。宿主超时沿用真实超时路径，缩短为 1.2s 以在页面单次查询上限内完成时序。

**`--close-order-request lastack`（撤销送达／丢失两变体，各 13/13、returncode 0）：** A 第一问 pending 送达、第二问 pending（`generation=1`）生成后暂扣；真实超时撤销 A；B 建立并确认（两问 `generation=2`）；随后释放旧 A 第二问。记录：`state_calls` 为 A `{pending,1}`×2、B `{pending,2}`×2；A 零 `complete_close`；B 单次 `allow=true` 且真实宿主 `closing`；关键检查 `lastack_a_second_answer_pending`／`lastack_a_generation_bound`／`lastack_a_still_verifying_at_b_confirmation`／`lastack_no_send_before_release`／`lastack_a_silent`／`lastack_b_single_allow`／`lastack_b_host_closing` 全 true。

**`--phase late-input-close`（撤销送达／丢失两变体，各 16/16、returncode 0）：** A 第一问 pending 生成即暂扣（A 停留在确认中）；真实超时撤销 A；B 建立并确认、在 `finishClose` 等待 A；此时真实表单仍可编辑（`textarea.disabled=false`）；以真实 DOM `input` 事件写入“关闭确认等待期间的未保存输入 FIX7”（非实际输入法按键）；随后释放 A。记录：A 零许可、B 仅一次 explicit deny（`allow=false`）、宿主 B 非 closing、页面无最终许可且未锁定、输入保留（`raw` 为预期原文、dirty=true、内容版本未变）；随后再次真实关窗由协调器保存该输入（真实 PATCH）并允许关闭，关闭后数据库检查原文与版本 +1（`late_input_saved_after_retry` true）。两个变体 `state_after_deny` 均为 `open=[]、verifying=[]、locked=false、finalAllowed=false`。

**最终源码全阶段（`source-run/final-source-phases-result.json`，15 进程）：** first 6/6、restart 6/6、fix-regression 28/28、fix-regression2 32/32、verify 5/5（原文“设置离开最终文本”）、`close-order` 撤销 delayed 13/13、lost 13/13、request delayed 16/16、lost 15/15、lastack delayed 13/13、lost 13/13、`late-input-close` delayed 16/16、lost 16/16、save-dialog 9/9、clean-ime-close 4/4——**returncode 全 0，checks 无 false**。

**口径：** lastack／late-input 的“新输入”为真实 DOM `input` 事件写入实际表单模型（受控桥记录，非实际输入法按键）；组合输入在等待窗口的覆盖为组件级真实 EditorView `composing` 状态，而本轮最终源码与包内均**实际执行**了既有 `clean-ime-close` 阶段（各 4/4，真实 `CompositionEvent` 的干净关窗）——其程序化 `CompositionEvent` 仍不等于实际输入法按键；宿主内部“许可与保存交错”注入、实际 IME 按键、人手动另存为仍按 §17.9／§15.6 保留未验。

### 18.7 新包、构建来源与仓外运行

**构建与身份：** `desktop/build_d1.py --skip-frontend --hash-out <证据>/package/package-hashes-fix7.json`，exit 0；`KGNext-D1Verify` **137 文件**，EXE 14,734,848 字节、SHA-256 `f243b4473cf5f9d13fcdf9f3b5b2ad2309a0a8fddab92f6be34ae4650db0a2dd`；上一轮 8d1a4dbb… 包在同一 `build/desktop-d1/package/` 下改名保留，更早各包与全部旧失败记录未动。前端按 `build/desktop-d1/frontend` 重建且与证据目录构建产物逐字节一致。仓内与仓外复制各 **137/137** 文件与 `package-hashes-fix7.json` 清单相符（无缺失／额外／大小／散列差异）；`verify-package.py` 确认 8 个关键归档模块（`d1_main`、`d1_host_api`、`d1_paths`、`d1_server`、`config_service`、`config_tokens`、`daily_plan_service`、`migrate`）与当前源码代码等价（仅忽略 co_filename），前端 `d1.html`＋2 assets 与构建输出逐字节一致、迁移／模板资源存在，problems=0。

**构建来源记录（只记事实）：** 本轮 `COLLECT-00.toc` 共 55 个二进制／扩展条目（18 BINARY＋37 EXTENSION），逐字节与来源文件一致：`C:\Python314` 4 项、`C:\Python314\DLLs` 24 项、`desktop/.venv-d1/Lib/site-packages`（含 clr_loader、cryptography、greenlet、lxml、markupsafe、pydantic_core、pythonnet、sqlalchemy、webview）27 项；TOC 中无 `api-ms-win-*`／`ucrtbase.dll`（与上轮“缓存来源 DLL 未再收集”一致）；未将新旧包差异与 ctypes 或其它因果关联，干净构建／发行再现性边界保留，不据此安装或清理环境。

**仓外运行（`package/run-outside.py`，`package-logs/pkg-phases-result.json`）：** 包复制到 `<证据>/package-outside`，从不同 cwd（`<证据>/run-cwd`）启动，剥离全部继承 `KGM_*` 后注入合成数据／预授权导出目录（save-dialog 阶段不注入预授权目录）。**15 个独立进程实际 returncode 全部 0、checks 全 true、无残留进程**：

| 进程 | 阶段 | 返回码 | checks |
| --- | --- | --- | --- |
| 1 | `first` | 0 | 6/6 |
| 2 | `restart` | 0 | 6/6 |
| 3 | `fix-regression` | 0 | 28/28 |
| 4 | `fix-regression2` | 0 | 32/32 |
| 5 | `verify` | 0 | 5/5 |
| 6 | `close-order --close-order-abort delayed` | 0 | 13/13 |
| 7 | `close-order --close-order-abort lost` | 0 | 13/13 |
| 8 | `close-order --close-order-request delayed` | 0 | 16/16 |
| 9 | `close-order --close-order-request lost` | 0 | 15/15 |
| 10 | `close-order --close-order-request lastack --close-order-abort delayed` | 0 | 13/13 |
| 11 | `close-order --close-order-request lastack --close-order-abort lost` | 0 | 13/13 |
| 12 | `late-input-close --close-order-abort delayed` | 0 | 16/16 |
| 13 | `late-input-close --close-order-abort lost` | 0 | 16/16 |
| 14 | `save-dialog` | 0 | 9/9 |
| 15 | `clean-ime-close` | 0 | 4/4 |

合成库（只读核对，`package/db-check.json`）：`local_alembic_version=20261014_0003_local`；2 计划（09-15=v16、09-16=v2）、18 内容、20 操作记录、1 日历修订、1 配置操作；`foreign_key_check` 空、`integrity_check=ok`、`journal_mode=wal`。09-15 的**最终**当前原文为 clean-ime-close 阶段最后写入的“关窗前组合最终文字”（v16）；late-input retry 保存的“关闭确认等待期间的未保存输入 FIX7”为其前一内容版本（阶段中间数据，见审阅 §16.5 的口径更正）。

### 18.8 Word 样本

导出读取／映射／生成器与模板未变（backend 未改）；用与已目视复核样本相同的阶段谱系（`first→restart→fix-regression→fix-regression2→verify`，默认会话标记）经新包重跑（5 进程 returncode 全 0），4 份样本与 `kgm-d1b-fix6-20261016/word-samples`（与 fix5 已目视复核样本逐字节一致）**逐字节一致**（`package/word-samples-compare.json`，`all_identical=true`，无额外交付文件）：样本A 14,021 字节 `1b3d4e21da0d7a7b`、样本B 14,165 字节 `05bff8c24cd77d7c`、样本C 14,443 字节 `6313a2c17b9a7006`、样本D 14,038 字节 `2d1adb2e4e56975a`。按既定规则（样本或渲染链变化才补 Word 页），本轮**无需补页**，沿用既有 2／2／5／2 页与目视复核范围；不声称本轮重新打开 Word。

### 18.9 变化文件（SHA256 前 16 位）

| 文件 | 上一轮 | 本轮 |
| --- | --- | --- |
| `frontend/src/d1/bridge.ts` | `6b3132235a01d458` | `032a2651e23c2f76` |
| `frontend/src/d1/App.vue` | `0ed0b8e8ccd8991b` | `39e5b2b1bf13a464` |
| `frontend/src/d1/d1.components.test.mjs` | `8826e087d7fd09d6` | `2508d0b1d22a1a40` |
| `frontend/src/d1/d1.test.mjs` | `2e07218bf6410d40` | `9bb02a169ea2c85a` |
| `desktop/d1_host_api.py` | `f49fb4ffd0578954` | `248f419a5ee634fa` |
| `desktop/d1_main.py` | `97cf90a528d4cea9` | `1a65b44023b45913` |
| `desktop/tests/test_d1_close.py` | `ab109d785cc1baad` | `2a43123d6ad8241f` |
| `desktop/tests/test_d1_host_save.py` | `9630a66168bdf41f` | `2ea80e7e4025bd1e` |

未变化保留上轮身份：`leave.ts` `664b37cd9f8569a9`、`EditorView.vue`、`ExportDialog.vue`、`SettingsView.vue`、backend `pyproject.toml`／`uv.lock`（`e5f948d2…`／`cc589c0a…`）与 D1 锁（`c0b73435…`／`db1a0e58…`）散列不变；`git diff --check` exit 0（仅保留既有换行转换提示）。

### 18.10 未验边界与再次复审条件

1. **保持未验：** 实际中文输入法按键（本轮等待窗口中的输入为真实 DOM `input` 事件，组件级组合为 `composing` 状态；本轮源码与包内实际执行了 `clean-ime-close` 的程序化 `CompositionEvent` 干净关窗各 4/4，但仍不等于实际 IME 按键）；真实窗口内宿主内部“许可与保存交错”注入；人手动原生另存为交互；WPS、干净机器、Windows 10、其他 DPI、多显示器；教师本人手动体验；干净构建／发行再现性。真实教师数据与旧远程资源未触碰。
2. **证据根：** `%TEMP%\opencode\kgm-d1b-fix7-20261017\`（`prefix\`：before／final 源码散列、纯逻辑／组件／R17／桌面首次失败与最终日志、typecheck／build、后端本地与回归日志；`source-run\`：final-* 逐阶段 JSON／启动日志、`run-source-final.py`、`final-source-phases-result.json`、首轮 request-lost 回归失败记录；`package\`：`package-hashes-fix7.json`、`manifest-repo.json`／`manifest-outside.json`／`manifest-compare.json`、`binary-provenance.json`、`verify-package.py`／`package-verify.json`、`run-outside.py`、`compare-run.py`、`word-samples-compare.json`、`db-check.json`、`final-source-hashes.txt`；`package-outside\`、`package-data`／`package-saves`、`package-logs\`、`run-cwd\`、`package-compare-*`／`package-compare-saves`；临时路径不保证长期留存，关键结论以本节为准）。
3. **再次复审条件：** R17 有先失败组件反例（真实 EditorView＋App）与源码／包 `late-input-close` 两变体（真实 DOM 输入、显式 deny、内容保留、retry 保存后关闭且库内核验）证据；R1 有先失败组件反例（最后一问迟到、撤销送达／丢失）与源码／包 `lastack` 两变体（代际 1／2、A 静默、B 单一许可）证据，宿主代际绑定有单测与真实 `js_bridge_call` 线程探针；R6 及其他已关闭项回归保留（组件 55／桌面 146／本地 133／回归 108）；新包 137 文件与源码／资产／manifest 一致、仓外 15 进程返回码逐进程留存；同字节 Word 样本证据有效。交 Codex 独立复审 R17／R1 关闭与本片必要证据，满足后才工程放行。产品验收、发行与后续切片不因本节自动成立；不自动启动 D2、AI、WebDAV 或发行。

### 18.11 第七轮独立复审补充（Codex，2026-10-17）

[审阅§16](desktop-d1-review.md#16-d1b-第七轮修复复审2026-10-17)关闭R1；R17日计划原P1反例通过，独立SFC探针保留新输入、B显式deny，源码／包窗口补验有效。但同一等待窗口漏掉设置草稿最终复核，R17按P2保留：独立实际App＋SettingsView反例exit 1，真实WebView2源码窗口反例exit 3；输入框未禁用、draftActive=true后B仍allow，宿主accepted=true／closing且窗口实际关闭，合成库姓名未变、config_version=1、配置操作0。累计17项中16项关闭，R16／R6保持关闭，D1B仍不放行。详细时序与修复判据见审阅§16.3。

独立133本地／108回归／146桌面、纯逻辑＋55组件、typecheck／build通过；f243b447…包仓内仓外各137文件、8归档模块、前端与资源同源，55个二进制／扩展条目与实际来源一致。最终源码及包各15进程的returncode、checks和原始记录核对有效；Codex本轮另跑一次设置残留窗口，不将核对记录写成重跑全部窗口。四份package-compare-saves与已目视样本逐字节一致，保留Word既有范围。

**证据口径更正：** §18.7的最终合成库09-15原文实际为“关窗前组合最终文字”（v16）；late-input新文字是此前阶段保存并核验的中间状态。§18.6／§18.10称本轮未重复clean-ime-close也应修正：最终源码和包各有本轮4/4记录；程序化CompositionEvent并非实际IME按键。原阶段事实和首次失败保留，不以更正替代实际产品体验。

下一步只修设置页最终关闭保护并补相关组件／窗口／同环境包证据，见[唯一当前任务](../tasks/current.md)。工程收口后教师流程与实际IME体验，再准备D2规格；产品验收、干净构建和兼容性边界保留。本轮没有改仓库实现、测试、迁移或构建脚本，没有安装、提交／推送、派发其他聊天或启动后续切片。

## 19. D1B R17 设置草稿关闭保护（2026-10-17 第八轮）

依据[审阅 §16.3](desktop-d1-review.md#163-r17--p2设置页等待期间的新草稿仍被关闭丢弃)（§16.5 口径更正、§16.6 接续）与[当前任务](../tasks/current.md)：只收束 R17 设置页残留——关闭确认等待期间产生的设置草稿仍会被关窗丢弃。R1 保持关闭，R16／R6 等 16 项不动；不改 §11–13 产品行为（尤其 §11.3：未确认设置草稿的关闭须留页并提示预览确认或取消，不得借关窗自动应用）。环境仍为 `desktop/.venv-d1`（CPython 3.14.7／Windows x64／标准 GIL、SQLite 3.50.4；`uv pip check` desktop 46 包、backend 26 包兼容，exit 0），未安装或升级依赖，未改 backend 声明／锁与 D1 锁，未读真实 `.env`／密钥／教师库，未连接旧 MySQL／远程业务，未调用真实 AI。本节不自行写成 Codex 已关闭或 D1B 已放行。

### 19.1 改动：最终核对同时复核设置草稿／预览确认状态

`App.vue` 的 `finishClose`（`frontend/src/d1/App.vue`）：

1. 在验证门与 `settle()` 等全部等待结束之后、`freezeForClose` 与发送 allow 之前，除既有日计划 `dirty=false`／identity 检查外，新增同步的 `isSettingsDraftBlocking()` 复核（设置页且存在未确认输入、新术语／范围／例外草稿，或已打开预览——按 SettingsView 实际 `draftActive` 上报）；命中即提示“设置修改尚未确认”、留页并保留全部输入，由既有 `onRequestClose` 路径释放宿主 pending（explicit deny）。检查与冻结之间仍无 await，也无“等待中新草稿可在末尾被跳过”的窗口。
2. 不得自动应用或丢弃设置草稿：关闭流程不发任何配置 POST；用户需按既有预览／确认或“取消编辑”流程处理后重新关闭。入口处的一次设置检查（快速拒绝路径）、R1 代际保护、日计划 IME 落定与最终 closing／通信失败冻结语义全部保留。
3. 页面验证钩子 `window.__d1App.closeState()` 增加只读 `settingsDraft` 字段（与 `__d1Editor` 同口径的 introspection，不改变校验路径）。组件回归按真实模板绑定 `@draft-active="(active) => settingsDraftActive = active"` 接线实际 SettingsView 的 emit，不以独立布尔桩替代。

### 19.2 先补失败证据（保留）

1. **组件反例（审阅 §16.3 等价，实际 App＋SettingsView＋真实 draft-active 传递）**：B 在验证门内等待时向真实设置模型输入姓名草稿，`isSettingsDraftBlocking()` 已为 true；释放旧 A 后旧实现仍 `B allow=true`：`an unconfirmed settings draft created during the wait must not allow the close — true !== false`，**exit 1**（`prefix/settings-components-first-failure.log`）。
2. **真实窗口反例（f243b447 同源预修复前端＋新驱动 `--phase settings-draft-close --close-order-abort delayed`）**：设置页初始无草稿；A 第一问 pending 暂扣、真实超时撤销；B 确认后在验证门等待；真实 DOM 输入姓名后 `draftActive()=true` 且仍无 POST 与 complete_close；释放 A 后旧实现 `B allow=true`、真实宿主 `accepted=true/state=closing`、窗口真实关闭、草稿随关窗丢失。`settings_draft_never_allow` false，`driver_error="settings-draft 反例：未确认设置草稿被关窗丢弃（B allow=true）"`，进程 **exit 3**；`before`／`after_input`／`complete_calls`（allow=true 且 accepted）保留（`source-run/prefix-settings-draft-close.json`、`prefix-settings-draft-close.stdout.log`）。
3. **驱动首跑内部遗漏（保留事实，不混作产品反例）**：首次运行因 `_http_json` 返回 `(status, body)` 元组未解包，尚未到达反例即报 `'tuple' object has no attribute 'get'`；修正后重跑得到上述第 2 条反例（同路径 stdout 被该次重跑覆盖，结论以保留的 JSON 为准）。

### 19.3 修复后的回归（组件 55→60；宿主与后端无改动）

- `testCloseSettingsDraftDuringWaitStaysAndKeepsDraft`：等待中新姓名草稿→B 单次 explicit deny、宿主 canceled、页面未锁定、输入保留、零配置 POST；经真实 `cancelDraft()` 取消后，下一次关闭 allow=true 并关闭（初始 clean 的正常关闭由该 retry 覆盖）。
- `testCloseSettingsPreviewDuringWaitStays`：等待中经真实 `previewChange` 打开预览（preview POST 1 次）→deny、预览保留、apply POST 0 次。
- `testCloseSettingsDraftAfterFailedWaitStays`：等待失败（权威查询丢失、验证快速失败）→最终复核仍见草稿，deny。
- `testCloseSettingsDraftDuringWaitAfterReplacementStays`：B 被 C 替代后，最新请求 C 同样在最终核对时拒绝草稿（A／B 静默、C 单次 deny）。
- `testCloseSettingsDraftDuringWaitTimeoutStays`：验证门 10s 有界期限到期时仍有旧确认在途→B 仍先复核草稿再决定（deny；实际等待 ≥10s 有断言），旧请求全部静默。
- 既有 55 项组件、146 项桌面宿主、R1／R16 保护与日计划等待窗口用例全部保留通过；桌面与后端代码本轮未改。

### 19.4 自动检查（最终一轮命令与结果）

后端命令工作目录 `backend`，环境 `APP_DISABLE_DOTENV=1`、`PYTHONIOENCODING=utf-8`、`-X utf8`；完整本地套件设临时数据根兜底；前端／桌面在各自目录。

| # | 命令 | 结果 |
| --- | --- | --- |
| 1 | `python.exe -X utf8 -m unittest discover -s tests/local -t . -v` | **133 项，0 skip，exit 0**（80.551s） |
| 2 | `python.exe -X utf8 -m unittest tests.unit.test_i3_content_validation tests.unit.test_security tests.unit.test_calendar_boundaries tests.unit.test_i3_api_schemas tests.unit.test_i5_export_read_service -v` | **108 项，0 skip，exit 0**（0.349s） |
| 3 | `.venv-d1/Scripts/python.exe -X utf8 -m pytest tests/ -q -p no:cacheprovider` | **146 passed，exit 0**；2 项依赖弃用警告 |
| 4 | `npm run test:d1` | 纯逻辑套件 OK＋**60 项组件级异步回归**（55→60），exit 0 |
| 5 | `npm run typecheck`、`npm run build:d1` | 均 exit 0；构建输出 `d1.html`＋`index-DHhfIjJV.js`＋`index-ILAyuRJW.css`，保留分块大小提示 |
| 6 | `uv pip check`（backend／desktop） | 26／46 包兼容，exit 0 |

### 19.5 真实 WebView2 补验（源码与包内）

`desktop/d1_main.py` 新增 `--phase settings-draft-close`（`drive_settings_draft_close`）：进入真实设置页（初始无草稿；经真实 API 记录姓名与 config_version、经只读连接记录配置操作数）→ A 第一问 pending 暂扣→真实超时撤销 A（`--close-order-abort delayed` 撤销实际送达并记录，`lost` 丢弃）→ B 建立、确认并等待 A→真实姓名输入框写入“关闭等待期间修改姓名 FIX8”（真实 DOM `input` 事件，输入框 disabled=false）→等待真实 `__d1Settings.draftActive()=true`（并记录 `closeState().settingsDraft`、`posts`、`sent`）→释放 A。修复后记录：A 零 complete_close、B 单次 `allow=false`、真实宿主 canceled 且非 closing、页面 locked=false／finalAllowed=false、输入值保留、仍在设置页、`posts=[]`；随后点击真实“取消编辑（还原当前配置）”控件→`draftActive()=false`→再次关窗 C `allow=true`、宿主 closing、窗口真实关闭。关闭后库内核验（`settings_draft_profile_unchanged`／`settings_draft_config_version_unchanged`／`settings_draft_no_config_operation_added`）全部 true。

- **最终源码 17 阶段（`source-run/final8-source-phases-result.json`）**：first 6/6、restart 6/6、fix-regression 28/28、fix-regression2 32/32、verify 5/5（原文“设置离开最终文本”）、close-order 撤销 delayed 13/13、lost 13/13、request delayed 16/16、lost 15/15、lastack delayed 13/13、lost 13/13、late-input delayed 16/16、lost 16/16、**settings-draft delayed 22/22、lost 22/22**、save-dialog 9/9、clean-ime-close 4/4——**returncode 全 0，checks 无 false**。
- **仓外包 17 进程（`package-logs/pkg-phases-result.json`）**：同组阶段、returncode 全 0、`all_ok=true`；settings-draft 两变体各 22/22。包内运行记录：`name_before=验证教师`、`config_version_before=2`、`config_ops_before=1`（为 fix-regression 阶段已提交的配置变更），两轮 settings-draft 后仍为 2／1，草稿未应用；每轮均先 deny 释放 B，再显式取消后 C allow 关闭。
- **口径：** 该阶段输入为真实 DOM `input` 事件（受控桥记录，非实际输入法按键）；受控部分为按请求暂扣回答、缩短真实超时与审计包装；窗口级完成信号取自真实 `draftActive()`／`closeState()`／`complete_close` 记录与 `closed` 事件，不以固定等待冒充完成。组合输入／实际 IME 边界与 §18 相同（`clean-ime-close` 程序化 `CompositionEvent` 各 4/4 仍非实际按键）。

### 19.6 新包、构建来源与仓外运行

**构建与身份：** `desktop/build_d1.py --skip-frontend --hash-out <证据>/package/package-hashes-fix8.json`，exit 0；`KGNext-D1Verify` **137 文件**，EXE 14,741,133 字节、SHA-256 `28e3e60e31615fde859526447b47e0bdbf3f51a56719429a2008510d4c5822a3`；上一轮 f243b447… 包改名 `KGNext-D1Verify-f243b447` 保留，更早各包与全部旧失败记录未动；前端重建后为 `index-DHhfIjJV.js`＋`index-ILAyuRJW.css`（较上轮 `index-1CjZ5jPO.js` 更新，CSS 不变）。仓内与仓外复制各 **137/137** 文件与清单相符（无缺失／额外／大小／散列差异）；`verify-package.py` 确认 8 个关键归档模块与当前源码代码等价（仅忽略 co_filename），前端 `d1.html`＋2 assets 与构建输出逐字节一致、迁移／模板资源存在，problems=0。

**构建来源记录（只记事实）：** 本轮 `COLLECT-00.toc` 共 55 个二进制／扩展条目（18 BINARY＋37 EXTENSION），逐字节与来源文件一致：`C:\Python314` 4 项、`C:\Python314\DLLs` 24 项、`desktop/.venv-d1/Lib/site-packages` 27 项；无 `api-ms-win-*`／`ucrtbase.dll`；干净构建／发行再现性边界保留，不据此安装或清理环境。

**仓外运行（`package/run-outside.py`）：** 包复制到 `<证据>/package-outside`，从不同 cwd（`<证据>/run-cwd`）启动，剥离全部继承 `KGM_*` 后注入合成数据／预授权导出目录（save-dialog 阶段不注入预授权目录）。**17 个独立进程实际 returncode 全部 0、checks 全 true、无残留进程**：

| 进程 | 阶段 | 返回码 | checks |
| --- | --- | --- | --- |
| 1 | `first` | 0 | 6/6 |
| 2 | `restart` | 0 | 6/6 |
| 3 | `fix-regression` | 0 | 28/28 |
| 4 | `fix-regression2` | 0 | 32/32 |
| 5 | `verify` | 0 | 5/5 |
| 6 | `close-order --close-order-abort delayed` | 0 | 13/13 |
| 7 | `close-order --close-order-abort lost` | 0 | 13/13 |
| 8 | `close-order --close-order-request delayed` | 0 | 16/16 |
| 9 | `close-order --close-order-request lost` | 0 | 15/15 |
| 10 | `close-order --close-order-request lastack --close-order-abort delayed` | 0 | 13/13 |
| 11 | `close-order --close-order-request lastack --close-order-abort lost` | 0 | 13/13 |
| 12 | `late-input-close --close-order-abort delayed` | 0 | 16/16 |
| 13 | `late-input-close --close-order-abort lost` | 0 | 16/16 |
| 14 | `settings-draft-close --close-order-abort delayed` | 0 | 22/22 |
| 15 | `settings-draft-close --close-order-abort lost` | 0 | 22/22 |
| 16 | `save-dialog` | 0 | 9/9 |
| 17 | `clean-ime-close` | 0 | 4/4 |

### 19.7 合成库最终状态（区分阶段中间数据）

只读核对（`package/db-check.json`）：`local_alembic_version=20261014_0003_local`；2 计划（09-15=v16、09-16=v2）、18 内容、20 操作记录、1 日历修订、1 配置操作；`foreign_key_check` 空、`integrity_check=ok`、`journal_mode=wal`。姓名=验证教师（等待期间的草稿从未应用），`config_version=2`（来自 fix-regression 阶段已提交并核验的配置变更，非关闭流程写入；settings-draft 两轮前后均 2／1 不变）；09-15 最终原文为 clean-ime-close 最后写入的“关窗前组合最终文字”，late-input retry 的保存文本为其前一内容版本（阶段中间数据）。

### 19.8 §18 口径更正（按审阅 §16.5）

已就地更正 §18 三处表述：§18.7 最终合成库 09-15 原文为“关窗前组合最终文字”（v16，clean-ime-close 最后写入；late-input 文本为中间数据）；§18.6 与本§19.5相同口径改为本轮源码与包内**实际执行** `clean-ime-close` 各 4/4（程序化 CompositionEvent 仍非实际 IME 按键）；§18.10 同步更正为“实际执行各 4/4，但不等于实际按键”。原阶段事实与首次失败保留，不以更正替代实际产品体验。

### 19.9 Word 样本

导出读取／映射／生成器、模板与内容生成链本轮未改；同谱系（`first→restart→fix-regression→fix-regression2→verify`，默认会话标记）经新包重跑（5 进程 returncode 全 0），4 份样本与已目视复核样本（fix6 `word-samples`，与 fix5 逐字节一致）**逐字节一致**（`package/word-samples-compare.json`，`all_identical=true`，无额外交付文件）：14,021／14,165／14,443／14,038 字节，前 16 位 `1b3d4e21da0d7a7b`／`05bff8c24cd77d7c`／`6313a2c17b9a7006`／`2d1adb2e4e56975a`。按既定规则**无需补 Word 页**，沿用既有 2／2／5／2 页与目视复核范围；不声称本轮重新打开 Word。

### 19.10 变化文件（SHA256 前 16 位）

| 文件 | 上一轮 | 本轮 |
| --- | --- | --- |
| `frontend/src/d1/App.vue` | `39e5b2b1bf13a464` | `f3aba04b043e5ae2` |
| `frontend/src/d1/d1.components.test.mjs` | `2508d0b1d22a1a40` | `091b95a198267873` |
| `desktop/d1_main.py` | `1a65b44023b45913` | `96fcbb9a92dde8b5` |

未变化保留上轮身份：`bridge.ts` `032a2651e23c2f76`、`d1.test.mjs` `9bb02a169ea2c85a`、`d1_host_api.py` `248f419a5ee634fa`、`test_d1_close.py` `2a43123d6ad8241f`、`test_d1_host_save.py` `2ea80e7e4025bd1e`、`leave.ts`／`EditorView.vue`／`ExportDialog.vue`／`SettingsView.vue`、backend `pyproject.toml`／`uv.lock` 与 D1 锁散列不变；`git diff --check` exit 0（仅保留既有换行转换提示）。

### 19.11 未验边界与再次复审条件

1. **保持未验：** 实际中文输入法按键（等待窗口输入为真实 DOM `input` 事件；`clean-ime-close` 的程序化 `CompositionEvent` 各 4/4 仍非实际按键）；真实窗口内宿主内部“许可与保存交错”注入；人手动原生另存为交互；WPS、干净机器、Windows 10、其他 DPI、多显示器；教师本人手动体验；干净构建／发行再现性。真实教师数据与旧远程资源未触碰。
2. **证据根：** `%TEMP%\opencode\kgm-d1b-fix8-20261017\`（`prefix\`：before／final 源码散列、设置组件首次失败与最终日志、typecheck／build、后端与桌面日志、`git-diff-check.log`；`source-run\`：`run-source-final.py`、`final8-source-phases-result.json`、`final2-*` 逐阶段 JSON／启动日志、`source-data-run3`／`source-saves-run3`、预修复反例 `prefix-*`（含 `prefix-settings-draft-close.json`）与 `source-data-final`；`package\`：`package-hashes-fix8.json`、`manifest-*`／`manifest-compare.json`、`binary-provenance.json`、`verify-package.py`／`package-verify.json`、`run-outside.py`、`compare-run.py`、`word-samples-compare.json`、`db-check.json`、`final-source-hashes.txt`；`package-outside\`、`package-data`／`package-saves`、`package-logs\`、`run-cwd\`、`package-compare-*`；临时路径不保证长期留存，关键结论以本节为准）。
3. **再次复审条件：** R17 设置残留有先失败组件反例（实际 App＋SettingsView 的 draft-active 传递）与预修复真实窗口反例（B allow=true、窗口关闭、草稿丢失，exit 3）；修复后组件 60 项含等待中新输入／预览中／等待失败／请求替代／超时五组，真实源码与包内 `settings-draft-close` 两变体各 22 项（deny、输入保留、零配置 POST、显式取消后 retry 关闭、关闭后库内姓名／config_version／配置操作不变）；R1／R16／R6 等 16 项关闭事实与回归保留（桌面 146／本地 133／回归 108）；新包 137 文件与源码／资产／manifest 一致、仓外 17 进程返回码逐进程留存；同字节 Word 样本证据有效。交 Codex 独立复审 R17 设置残留与必要证据，满足后才判断 D1B 工程放行。产品验收、发行与后续切片不因本节自动成立；不自动启动 D2、AI、WebDAV 或发行。

### 19.12 第八轮独立复审与工程收口（Codex，2026-10-17）

[审阅§17](desktop-d1-review.md#17-d1b-第八轮修复复审与工程收口2026-10-17)确认R17设置残留关闭，累计17项全部关闭；**D1B在当前Windows 11开发机上的工程复审通过**，R1／R16／R6既有关闭事实不变。独立上轮组件反例通过：草稿保留、零配置POST、B单deny；补充“显式应用在途→拒绝关闭→提交完成且确认上下文更新→下次关闭”组件检查通过。独立真实WebView2窗口9/9、exit 0：新草稿留页保留、显式取消后重试实际关闭，库内姓名／版本1／操作0不变。首次Codex临时驱动选择器错误及退出3保留并与产品行为区分，详情见审阅§17.2。

独立133本地／108回归／146桌面、纯逻辑＋60组件、typecheck／build通过；28e3e60e…包仓内仓外各137文件、8归档模块、前端及迁移／模板同源，55个二进制／扩展条目与实际来源一致。OpenCode最终源码及仓外包各17进程returncode和逐阶段JSON核对有效；源码设置变体实际标记D1验证，包标记FIX8，分别对应输入记录。同字节Word样本沿用既有目视边界，本轮不声称重开Word。

本结论不是D1产品或发行验收。实际IME、教师本人体验、人手动保存、宿主内部许可／保存交错真实窗口注入、干净机器、Win10、WPS、其他DPI／多显示器、干净构建及发行再现性仍未验。下一步按[当前清单](../tasks/current.md)安排合成数据教师流程与实际IME体验，之后再准备D2规格。本轮仅核查、验证和文档，没有改仓库实现／测试／迁移／构建，没有安装、提交／推送、派发其他聊天或启动后续切片。

## 20. D1 教师流程与实际 IME 体验（2026-10-17）

用户明确要求以独立合成数据启动最新包，按清单由本人体验教师流程与实际中文输入法。启动时人工步骤均待执行；后续反馈及核对见§20.3–20.8和§21.10。**读回、v4、T6-A／T6-B、T7及Word页面验证已完成；用户明确微软拼音正常且无需复验，本轮教师体验收口。** 人工反馈、文件／数据库核对与自动检查分别记账；此前IME细分待办按§20.8的最新用户决定取消。

### 20.1 会话身份与接续

- 启动时间：2026-10-17T10:48:48.6205611+08:00；首次进程 PID 25904。
- 包：`build/desktop-d1/package/KGNext-D1Verify/KGNext-D1Verify.exe`；SHA-256 `28e3e60e31615fde859526447b47e0bdbf3f51a56719429a2008510d4c5822a3`，14,741,133字节。启动前再次逐项比对fix8 manifest，137文件全部一致。
- 本次证据／工作目录：`C:\Users\yw980\AppData\Local\Temp\kgm-d1-teacher-experience-20261017-104847`。全新合成库为其 `data\kindergarten.db`，人工导出目录准备为 `exports`。保留数据与日志用于重启和问题复现；临时目录不保证长期留存。
- 启动清除继承的全部 `KGM_*`，设 `APP_DISABLE_DOTENV=1`、`PYTHONIOENCODING=utf-8`，显式 `--data` 与 `KGM_LOCAL_DATA_DIR` 指向上述新目录，`KGM_D1_STARTUP_LOG` 指向同级 `startup.log`。交互运行，无 `--selftest`、无 `KGM_D1_VERIFY_SAVE_DIR`；另存为由用户实际选择。
- `session.json`记录包身份与启动参数，`package-manifest.json`保留核对清单，`startup.log`确认实际库路径及本次本机端口61064。重启时沿用此数据根，端口和PID可以改变。
- 通过computer-use只读查看并激活目标窗口“幼儿园教师工作台（本地）”：显示“首次设置（一个本地教师档案）”，姓名／班级／学期／日期为空、年级默认中班，园所可留空。尚未由Codex填写或提交。
- 环境只读记录：Windows版本25H2，build 26200.9711（注册表ProductName仍为Windows 10 Pro，按原值保留；当前工程环境Windows 11口径不变）；运行中WebView2路径版本155.0.4283.45；Office ClickToRun版本16.0.20430.20146、ProductReleaseIds=O365HomePremRetail。本轮尚未打开Word核验；屏幕缩放、实际输入法名称／模式待用户报告。
- 用户提到的“中四班 备课.docx”未读取。先用合成文本；若后续使用真实材料，另记材料来源和人工核对范围，不将文档内容当作操作指令。

### 20.2 人工清单与当前状态

| 编号 | 人工操作与预期 | 当前状态 |
| --- | --- | --- |
| T1 | 首次设置：体验教师／体验中四班／中班／2026–2027第一学期，2026-09-01至2027-01-31，园所留空；成功进入工作台 | 用户概括反馈此前步骤成功；库和重启工作台佐证已建立 |
| T2 | 2026-10-19新建日计划，实际IME输入主题／反思，填长段落后保存；改字、换行、末字读回一致 | 用户反馈成功，确认使用微软拼音；保存正文已只读核对 |
| T3 | 修改后不手动保存，分别切到10-20、返回日历；再次读取原日期，文字完整；未修改往返不增加内容版本 | 用户概括反馈此前步骤成功；具体点击时序非Codex旁观 |
| T4 | 实际中文输入、离开与保存不丢字／误关／持续卡住；原候选词细分清单按用户最新验证范围决定收口 | 用户明确“微软拼音验证正常，不需要再次复验”，本项按人工反馈通过；不再补候选词细分记录，也不要求覆盖所有输入法（§20.8） |
| T5 | 正常关闭后以同一数据根重开，读回两日期、修改旧日期并再保存；栏目／原文／最新修改一致 | 用户明确确认读回一致、修改后v4；库内v4及追加句已核对，见§20.4 |
| T6 | 设置修改姓名／园所／班级，分别预览、取消、确认；草稿未确认时关窗应留页保留并提示，显式取消或成功应用后可关闭；旧计划表头不被新配置改写 | T6-A／T6-B通过：草稿保护、取消还原／版本不变和正常关闭获用户确认；确认应用后配置v4，新旧表头、旧内容／版本保持及退出均已独立核对（§20.7–20.8） |
| T7 | 保存后导出当前日期，人工另存为取消一次再重试，中文名保存到exports；取消不报成功，成功DOCX可实际打开；再导出所在周或多日范围，按实际页数逐页检查内容和顺序；缺项按实际内容明确确认 | 本轮通过：原生取消／重试／Word打开获用户确认，实际两日文件已核对（§20.6）；T6-B两份文件分别仅含10-19或10-21一份计划，补齐当前日期导出证据（§20.8）；R18长园所2页、合并7页及起始页1／4／6已由用户逐页确认（§21.10） |

合成文本、分步引导通过本聊天交付。实际IME段落由用户按键，长文本可粘贴用于排版检查，两类证据区分记录。本轮教师体验按§20.8收口，R18按§21.10关闭；完整产品与发行验收不在此结论范围。若以后出现具体丢字、误关窗、保存或导出异常，再针对实际问题保留证据并核查，不凭通用覆盖要求重复本轮验证。

### 20.3 用户反馈与第一次重启（11:03）

用户反馈原文：“以上均成功，现在开始测试重启读回，我已经关闭窗口”。据其当前进入重启步骤的上下文，记录为**此前已执行步骤用户报告成功**；不把该概括反馈扩写为每一种候选词分支均独立见证，也不提前确认重启后的读回、设置全流程或Word逐页检查。输入法名称、具体组合行为和缩放比例仍待补充。

Codex确认首次进程已退出，原启动日志11:02:42有 `complete_close(..., allow=True)` 和 `closing allowed`。11:03:25以SQLite `mode=ro`／`query_only`对本次合成库留存 `restart-before-db.json`，没有写入业务数据：integrity_check=ok，foreign_key_check为空。

| 关闭后、重启前基线 | 实际读取 |
| --- | --- |
| 2026-10-19 | v3；主题“有趣的树叶”，目标及完整过程已存；反思“幼儿愿意交流自己的发现，下次增加不同形状的叶片。”；晨间问题设计“测试问题”，话题为空；原始教案为空字符串 |
| 2026-10-20 | v1；结构化内容为空对象，原始教案null；需用户核对这是否符合关闭前状态，不能自行补写或认定丢失 |
| 档案／计划快照 | 当前档案姓名“教师”；两份既有计划的创建姓名仍为“体验教师”、班级“体验中四班”、园所空。此为实际读值，不替代完整设置流程判定 |

11:03:26再次验证EXE SHA与28e3e60e…一致，清除继承KGM变量后显式沿用同一 `data` 根启动，PID 23756，无selftest／预授权另存为。新启动信息见 `restart-session.json` 和 `restart-20261017-110326.log`；未更改原始启动日志。computer-use只激活并观察窗口，确认直接进入工作台、没有再次要求初始化，本月已保存计划显示10-19版本3、10-20版本1。

**本次完成：** 原进程退出核对、关闭后库基线留存、同库重启、工作台恢复与两计划索引显示。**仍待用户：** 逐字段读回是否符合关闭前输入、无修改返回不增版本、旧日期追加一句并保存后再打开可见。T5尚不记为整体通过；当前窗口留给用户手动检查。

### 20.4 重启读回确认、微软拼音与Word格式反馈

用户明确反馈：“读回一致、修改后的版本号v4，以及使用的输入法名称:微软拼音输入法（微软自带）。” Codex随后以同一只读连接方式核对：10-19为v4，反思末尾实际追加“重启后验证通过。”；10-20仍为v1。保存值沿用用户实际输入，不把引导示例“重启后修改验证通过。”与用户自行简写混同为丢字。证据 `restart-after-user-db.json`。T5按用户确认通过；无修改往返的逐点击记录未另行采集，不伪造该独立证据。输入法名称已明确，屏幕缩放仍未知。

用户随后要求调整日计划Word：①园所名称＋一日活动计划整体居中；②署名为班级＋教师名称，不加入年级；③表格内所有文字不加粗，包括活动过程。三项作为2026-10-17用户明确的格式决定进入[D1规格§12.4](../specs/desktop-manual-daily-plan.md#124-日计划-word-格式2026-10-17-用户确认r18)及R18任务，不假称已有实现完成。

**实际导出样本：** 用户提供 `C:\Users\yw980\Desktop\日计划_体验中四班_2026-10-19_2026-10-25.docx`。14,911字节，SHA-256 `6359e832530fc7c378e76a5c19300987e39649da5f5f8cc4f4df10b229d59720`，含2份日计划表格；其反思尚未含本轮v4追加句，此文件是已导出的时间点副本，不据此判定v4丢失。原件未修改；同字节副本保存为本体验目录 `word-before-r18.docx`，只读结构证据为 `word-format-before.json`。实际备课原文文件仍未读取。

| 项目 | Codex独立核对实际样本与当前源码 |
| --- | --- |
| 标题对齐 | 两个标题段落均未显式设置 `w:jc`；默认段落样式Normal（styleId=a）为 `w:jc=both`，因此继承两端对齐。生成器复制原模板段落属性后只换文字，没有覆盖对齐 |
| 署名 | 两份都是“中班 体验中四班 体验教师”；`generate_daily_export_docx`明确按grade、class_name、creator_display_name拼接。新要求应输出“体验中四班 体验教师”，仍读创建快照 |
| 表格加粗 | 71个含文字run中54个显式 `w:b`为开，含活动过程。`_capture_templates`取单元格首个rPr，`_CellWriter`／`_make_run`复制到新文字；模板标签的加粗被扩散至正文。固定栏目亦须一并取消加粗，不能只处理动态正文 |

此为用户目视反馈＋Codex文件结构／源码核查；本轮Codex未宣称重新逐页查看Word，也未更改导出DOCX、生成器、模板、测试或构建。当前样本有明确格式待改，修复后须通过新包重新导出并逐页核对，不能沿用旧样本同字节通过结论。

**接续与未验事项：** R18由OpenCode定点实施，Codex复审后再请用户确认新文件。教师清单T6及T7其余分支、IME候选词细分动作和屏幕缩放待补；宿主内部许可／保存交错真实窗口注入、干净机器、Win10、WPS、其他DPI／多显示器、干净构建／发行再现性仍未验。教师体验与Word结论明确后再准备D2规格，不自动启动D2／真实AI／WebDAV／发行。原体验清单独有决定、合成库位置及尚未完成事项已归并本§20，唯一current转为R18，不新增旧提示词副本。

### 20.5 R18关闭后T7人工验证接续（2026-10-17 16:21）

用户在确认两份Word逐页正常后要求记录并继续验证，R18关闭依据见§21.10及审阅§20.6。本次只启动既有新验证包并导航到已保存计划，把原生保存操作留给用户。

- 启动前确认没有`KGNext-D1Verify.exe`进程、原体验`data/kindergarten.db`存在；EXE散列与`c6dc19283a24d00a740f2ecbed2cc7159e951f02a37f00636b294b7670369930`一致。未重新构建或重跑既有通过测试。
- 16:21:00（北京时间）启动PID 32236，沿用§20.1原合成体验根，显式`--data`和`KGM_LOCAL_DATA_DIR`指向原`data`。清除继承的`KGM_*`后设置`APP_DISABLE_DOTENV=1`、`PYTHONIOENCODING=utf-8`及本次启动日志；无`--selftest`、无`KGM_D1_VERIFY_SAVE_DIR`。这是用户人工交互会话，不是向原库运行自动夹具。
- 接续记录`manual-t7-r18-20261017-162100.json`及同名`.log`保存在原体验根；日志确认实际数据库路径及本机端口55563。启动前数据库文件SHA-256为`b338e825b29daf53568c11849f62ccba5ad4abbccbc1565a8f65545cad2bb5db`，该文件散列不代替数据库内容／版本核对。原`exports`目录当时为空。
- computer-use已显示工作台：档案姓名“教师”、班级“体验中四班”、园所未填写，10-19／10-20已有计划，列表可见10-19内容版本4。Codex只点击10-19已有计划；首次编辑页截图显示“正在读取日计划…”。后续截图报`IGraphicsCaptureItemInterop.CreateForMonitor failed: Could not capture the given monitor. (0x80070057)`，刷新窗口绑定后重试仍同错，已停止桌面操作。不能把读取中截图写成编辑页完整内容已核对；后续由用户确认正常显示并进行T7。
- **T7当时交付的操作标准：** 10-19已保存计划→“导出 Word”→当前日期；如提示缺项，明确确认按当前内容导出。第一次进入系统另存为后取消，观察不报保存成功、不产生目标文件；显式重试，以新中文文件名保存到原`exports`并用Word打开。取消／重试应保留原计划，不修改正文、不覆盖旧桌面样本。建议目标名`另存为验证_2026-10-19.docx`。后续用户正常反馈见§20.6。

本节保留启动、可见界面与操作安排；后续实际人工结果按§20.6及§20.2更新。实现、测试、迁移、构建、架构文件和既有Word样本未改，未提交／推送或启动D2。

### 20.6 T7人工反馈与T6接续（2026-10-17）

在上一轮明确交付T7五步人工操作及“取消提示是否正确、取消后是否无文件、重试是否成功、Word是否正常打开”的反馈标准后，用户回复“验证正常”。按该直接上下文记录：本轮人工原生另存为取消、显式重试保存和Word打开路径由用户报告通过，包含所交付的10-19日期与原反思文字核对要求；这是用户总体反馈，不伪造逐点击旁观、独立截图或文件散列。

Codex首次只读检查建议目标`%TEMP%/kgm-d1-teacher-experience-20261017-104847/exports/另存为验证_2026-10-19.docx`时，文件不存在、`exports`目录为空，因此曾询问实际路径；未据此推断用户未保存、误报或产品失败。该次检查中PID 32236仍沿原合成库运行。用户随后明确表示“文件位置中已经存在了文件，请检测并继续”，后续核对如下，文件位置缺口已补齐。

- 同一建议路径现在存在文件：14,965字节，SHA-256 `2b2b7f26ae9313ae31fd1fb079134b0d42c2e523140348f8b1e315fbf041fce2`；文件最后修改时间2026-10-17 16:54:50（北京时间）。DOCX含13个ZIP成员，主XML解析正常；反思含“重启后验证通过。”，两份署名均为“体验中四班 体验教师”，72个表格run均显式关闭`b`／`bCs`，0问题。
- **实际内容是10月19日、10月20日两份计划**，不因文件名写10-19就记作单日输出。本证据支持取消后重试落盘及Word打开反馈，不独立证明用户当时选择了“当前日期”，也不猜测范围选择或判定范围缺陷。T6-B重新导出旧10-19计划时核对当前日期只包含该日即可；本次不要求重做取消／重试。文件布局采用用户正常反馈，Codex本次仅做结构和文字检查，未重渲染。
- 独立文件记录为原体验根`manual-t7-file-check.json`；旧人工会话记录已补入实际文件身份，T7文件路径无需再询问。
- 后续核对时验证应用已退出。17:01:35（北京时间）重新核对同一c6dc1928…EXE及原库存在后，以仅配置子进程环境的方式启动PID 28424，仍显式`--data`／`KGM_LOCAL_DATA_DIR`指向原体验`data`，`APP_DISABLE_DOTENV=1`，无selftest／预授权保存目录。日志`manual-t6-startup.log`确认原数据库路径、本机端口50390及启动完成；本轮未截图或操作设置。首个合并检查／启动命令被自动审批以`blocked by policy`拒绝、未执行，随后分开只读检查与限定子进程启动成功；未把拒绝记为应用故障。

**当时交付T6-A标准（后续反馈见§20.7）：** 在当前验证应用进入设置，先记录原姓名／园所及配置版本；把姓名填为“设置验证教师”、园所填为“设置验证园所”，只对“姓名与园所”点“预览修改”，检查前后值与保留旧表头的影响，再点“取消预览”。取消预览不应用修改，输入草稿可以保留；此时点窗口右上角关闭，应阻止关闭、提示处理草稿并保留输入。之后点“取消编辑（还原当前配置）”，姓名／园所恢复原值、配置版本不增加，再点窗口关闭应正常退出。此阶段先不确认应用，不修改班级／学期／日期，也不编辑计划正文。

T6-A反馈后，由Codex沿同一合成数据根重开，继续T6-B姓名／园所和班级分别预览确认、旧10-19单日导出与表头保持、新建计划使用新设置；再安排微软拼音候选细分动作及缩放记录。T6-B未提前标为通过，T7实际文件位置已补齐，不新增无依据的实现任务。

### 20.7 T6-A通过与T6-B人工验证接续（2026-10-17）

用户明确反馈：“验证正常，预览取消后草稿保留并阻止关闭，取消编辑后恢复原值、配置版本不变，最后已正常关闭。请记录并继续下一步。”据此将T6-A姓名／园所预览取消、草稿关闭保护、显式取消编辑及正常关闭四项记为人工通过；没有把尚未执行的确认应用、班级修改或新旧表头验证提前算入。

独立佐证：`manual-t6-startup.log`在17:05:28记录首次`complete_close(..., allow=False)`，17:05:42记录第二次`allow=True`与`closing allowed`；核查时`KGNext-D1Verify.exe`已无进程。退出后以SQLite`mode=ro`／`query_only`和短读事务查看原合成库，记录`manual-t6a-after-readonly.json`：姓名“教师”，园所null，班级“体验中四班”、中班，配置版本2，配置操作记录1条；10-19仍v4、10-20仍v1，旧计划创建姓名“体验教师”、园所null、班级“体验中四班”，没有10-21计划；integrity_check=ok、foreign_key_check为空。配置版本“未增加”来自用户前后观察，独立读值为完成后v2，不冒充本轮有独立读取的操作前配置版本。读取未写业务数据，也未运行自动夹具。

17:07:07（北京时间）再次验证c6dc1928…EXE身份、原库存在和应用已退出后，用相同数据根启动PID 32032，显式`--data`／`KGM_LOCAL_DATA_DIR`，子进程中清除继承KGM变量并设`APP_DISABLE_DOTENV=1`；无selftest／预授权保存。新日志`manual-t6b-startup.log`、接续记录`manual-t6b-session.json`与上述只读记录均在原体验根；旧T6-A日志保留。该启动不代替后续设置人工操作证据。

**T6-B当时交付标准（现已完成，结果见§20.8）：**

1. 姓名／园所改为“设置验证教师”／“设置验证园所”，在该区域预览后确认应用，观察提交成功、配置版本2→3；再单独把当前班级名称改为“设置验证中四班”（年级保持中班），预览后确认应用，配置版本3→4。每次先应用一组，待刷新完成再改下一组；不修改学期或日历。
2. 返回工作台，打开旧10-19计划，正文不改，导出明确选择“当前日期”（起止均为2026-10-19），缺项按当前内容明确确认，另存为`exports/设置后旧计划_2026-10-19.docx`。文件应仅含10-19一份计划（可跨多页），标题仍“一日活动计划”，署名仍“体验中四班 体验教师”，反思追加句保留；旧计划内容版本仍v4。该步同时补齐T7当前日期单日文件身份。
3. 选尚无计划的2026-10-21新建，在反思填“新设置验证。”并保存，导出当前日期（起止均为2026-10-21），另存为`exports/设置后新计划_2026-10-21.docx`。应仅含10-21一份计划，标题使用“设置验证园所”，署名“设置验证中四班 设置验证教师”，反思为刚保存的文字。两份新文件均保留，不覆盖旧导出。
4. 完成后正常关闭应用；用户反馈两次提交／版本、新旧表头、每份实际日期／计划数及关闭结果后，Codex再只读核对两份导出与原合成库。当时计划随后补微软拼音候选细分动作和缩放记录，现按§20.8用户决定取消该待办。

本节记录当时核查、启动交互会话与维护记录，T6-B当时待验；无实现／测试／迁移／构建改动，未提交／推送或启动D2。最新结果见下节。

### 20.8 T6-B核对与本轮教师体验收口（2026-10-17）

用户明确反馈：“T6-B验证正常，配置版本已到v4，旧计划表头不变，新计划表头正确，两份文件都只包含对应日期的一份计划，已保存到exports目录，应用已正常关闭。请核对并记录结果，微软拼音验证正常，不需要再次复验，这个系统用到的输入法千千万万，不需要全部验证”。T6-B按该人工反馈通过，并完成以下独立核对。

证据根沿用 `%TEMP%/kgm-d1-teacher-experience-20261017-104847`，包身份仍为c6dc1928…；以SQLite `mode=ro`、`query_only`和短读事务读取原合成库，不写入业务数据。核对结果保存于 `manual-t6b-final-check.json`，前基线为 `manual-t6a-after-readonly.json`，旧内容基线为 `restart-after-user-db.json`。

| 核对项 | 实际结果 |
| --- | --- |
| 当前配置 | 姓名“设置验证教师”、园所“设置验证园所”、班级“设置验证中四班”、年级middle（中班）；配置版本4，配置操作版本记录为2／3／4，与T6-A结束时v2及本轮两次应用一致 |
| 旧计划保持 | 10-19仍v4、10-20仍v1；创建快照仍为“体验教师”、园所null、“体验中四班”。两份旧计划的快照、版本及已采纳内容均与上述基线一致；10-19反思末尾“重启后验证通过。”仍在 |
| 新计划 | 10-21当前内容版本3，创建快照为新姓名／园所／班级，反思“新设置验证。”已保存。内容版本3是实际读值，与配置版本4分别记录 |
| 数据完整性 | `integrity_check=ok`，`foreign_key_check`为空 |
| 正常退出 | `manual-t6b-startup.log`在17:22:12记录`complete_close(a7b77427, allow=True)`及`closing allowed`；核对时无`KGNext-D1Verify.exe`进程。与用户正常关闭反馈一致，不推断未采集的进程退出码 |

两份DOCX均位于上述根的`exports`，ZIP校验无错误；各有且仅有一个计划表格、一个对应日期，标题和署名居中，表格含文字run均显式关闭`w:b`／`w:bCs`：

| 文件 | 身份与结构核对 |
| --- | --- |
| `设置后旧计划_2026-10-19.docx` | 14,608字节；SHA-256 `c99b9cb75ab3e858ea042c0a7ce39392a151c875228b856054cfdba69bd9802d`；日期仅10月19日，标题“一日活动计划”，署名“体验中四班 体验教师”，38个表格文字run非粗体，旧反思完整；散列与此前已验v4文件相同 |
| `设置后新计划_2026-10-21.docx` | 14,056字节；SHA-256 `606b7881fe45436cd464a2bb0f3fab85e02910df4cab3f6dfdbd4b295615a579`；日期仅10月21日，标题“设置验证园所一日活动计划”，署名“设置验证中四班 设置验证教师”，34个表格文字run非粗体，反思“新设置验证。” |

两份单日文件补齐T7当前日期输出的证据；此前T7文件确实含两日的记录保持。页面正常来自用户人工检查，以上独立核对为文件／数据库／日志证据，不宣称本轮Codex再次打开Word或旁观每个点击。

**输入法验证范围决定：** 微软拼音按用户明确反馈记为验证正常，不再安排复验、候选词细分动作或为该项补录缩放；不要求穷举其他输入法。先前待办由此收口，未逐项采集的动作不补写成独立实测。其他DPI兼容性保留在后续环境验证范围，不作为重开本轮微软拼音体验的理由。此决定已同步规格§13.4。

**本轮结论：** 当前Windows 11＋Microsoft Word下，教师流程人工验证收口，T6-A／T6-B／T7通过，R18保持关闭。下一步为D2每日活动计划AI规格准备；本次没有启动D2实现、真实AI、WebDAV或发行。宿主内部许可／保存交错的真实窗口注入、干净机器、Win10、WPS、其他DPI／多显示器及干净构建／发行再现性保留原未验边界，不将本轮收口写成整体产品或发行通过。仅核对和更新记录，未改实现、测试、迁移、构建、原合成库或导出文件，未重跑无变更的已通过测试。

## 21. R18 日计划 Word 格式定点修复与验证（2026-10-17，OpenCode，待 Codex 复审）

**后续状态：** 本节§21.1–21.7为实施交付时记录；Codex复审及证据口径补正见§21.8，随后用户确认与v4补验见§21.9，长样本人工逐页验收和R18关闭见§21.10。各小节中的待验描述保留其当时状态，不代表最新结论。

**结论：** 按[当前任务](../tasks/current.md)、[D1规格 §12.4](../specs/desktop-manual-daily-plan.md#124-日计划-word-格式2026-10-17-用户确认r18)与[Word Contract](../modules/word-export.md)完成 R18-A／B／C 三项定点实现、先失败后通过的输出级检查、新 D1 验证包构建及新包实际导出样本的 Windows Word 逐页检查。**本节不关闭 R18、不写成产品／发行验收通过**；新格式交 Codex 复审后再由用户复看确认。旧 28e3e60e… 包、体验会话、旧样本及全部历史记录保留；模板资产未改。

证据根：`%TEMP%\opencode\kgm-d1b-r18-20261017\`（`prefix\` 修复前证据与周计划基线、`auto\` 测试日志、`package\` 构建清单与检查脚本及结果 JSON、`package-logs\` 逐阶段 JSON／启动日志、`package-saves*\`／`word-shots`／`word-pdf` 样本与截图；临时目录不保证长期留存，关键结论以本节为准）。

### 21.1 实现（仅日计划生成路径定点正规化）

| 项 | 实现 |
| --- | --- |
| R18-A 标题居中 | `backend/app/services/word_export_docx.py` 新增 `_force_paragraph_alignment`：每份日计划标题段落显式写入 `w:jc=center`（按 CT_PPr 顺序插入），覆盖原模板复制段落对 Normal 两端对齐的继承；空园所只显示“一日活动计划”，长园所自然换行仍居中 |
| R18-B 署名 | 日计划署名 parts 由 `grade, class_name, creator_display_name` 改为 `class_name, creator_display_name`，单空格连接与空段过滤不变；年级仍保留在数据库／创建快照／映射，班级原文不删改；周计划班级行不变 |
| R18-C 表格不加粗 | 新增 `_force_daily_table_not_bold`：日计划表格内每个 run 移除原 `w:b`／`w:bCs` 后显式写入 `w:b=false`／`w:bCs=false`（按 CT_RPr 顺序插入），以直接格式覆盖模板直接粗体与样式继承；固定栏目、周次日期、标签、动态正文、活动过程、反思及标红 run 全部覆盖。共享 `_CellWriter` 与周计划生成路径未改；标题／署名不在取消加粗范围 |
| 模板资产 | `daily_plan.docx`／`weekly_plan.docx` 字节未改（受控 SHA 与既有模板测试不变）；未读取或覆盖用户实际备课文件 |
| 测试与验证工具 | `test_i5_word_export_docx.py` 按新决定更新日计划年级断言并新增 `R18DailyFormatDocxTests`；`test_export.py` 新增真实 HTTP＋生成链的 R18 输出检查；`d1_main.py` 新增 `word-r18` 阶段（真实 DOM input 事件写入长过程、真实保存后导出单日／多日）与 `--init-school`；`build_d1.py` 新增 `--dist-root`（当前包在用时的独立输出位置） |

### 21.2 先失败后通过的输出级检查（失败证据保留）

- 修改前（`prefix/daily-before.json`）：标题 `jc=null`（继承两端对齐）；署名为“中班 中一 甲老师”；表格 36 个 run 中 27 个显式粗体、0 个显式关闭、0 个 `w:bCs`。
- 新检查先对旧实现运行并如实保留失败：`tests.unit.test_i5_word_export_docx` **10 项失败**（R18-A 2、R18-B 4、R18-C 2、按新决定更新的既有断言 2），原始输出 `prefix/tests-before-fix.txt`。
- 修复后（`prefix/daily-after.json`）：标题 `jc=center`；署名“中一 甲老师”且署名段落保持 center；36/36 个 run 同时具备 `w:b` 与 `w:bCs` 显式 false；插入元素按 schema 顺序（0 处乱序）。
- 周计划回归：修复前用同一 view 生成 `prefix/weekly-before.docx`，修复后输出与其**逐字节一致**（SHA-256 `6b479484a53ed57e…`），证明共享写入器与周计划路径输出未变。

### 21.3 自动检查（实际命令与结果）

后端工作目录 `backend`（`APP_DISABLE_DOTENV=1`、`PYTHONIOENCODING=utf-8`、`-X utf8`；完整本地套件注入临时数据根，不指向体验库）；桌面为 `desktop/.venv-d1`。

| # | 命令 | 结果 |
| --- | --- | --- |
| 1 | `python -m unittest tests.unit.test_i5_word_export_docx tests.unit.test_i5_export_mapping tests.unit.test_i5_export_read_service -v` | **109 项，0 失败，exit 0** |
| 2 | `python -m unittest tests.unit.test_i3_content_validation tests.unit.test_security tests.unit.test_calendar_boundaries tests.unit.test_i3_api_schemas tests.unit.test_i5_export_read_service -v` | **108 项，0 失败，exit 0** |
| 3 | `python -m unittest discover -s tests/local -t . -v` | **134 项，0 失败，exit 0**（133→134，新增 R18 导出输出检查） |
| 4 | `.venv-d1/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider`（desktop） | **146 passed，exit 0** |
| 5 | `python -m unittest discover -s tests/unit -t .`（补充全量） | 692 项中 691 通过；1 项**既有环境性错误**：`test_ai1a_url_guard_edges.test_disabled_guard_never_connects` 硬编码 `.venv/bin/python`（POSIX 路径），Windows 下必然 `FileNotFoundError`，与本轮改动无关 |
| 6 | `uv pip check`（backend／desktop `.venv-d1`） | 26／46 包兼容，exit 0 |

未重复全部 17 阶段窗口回归（前端与关闭链未改）；3.12 异常、D0／D1A 及原 R1–R17 历史不变。

### 21.4 新 D1 验证包与来源一致性

- 构建：`desktop/build_d1.py --dist-root build/desktop-d1/package-r18 --hash-out …/package-hashes-r18.json`，exit 0；含前端重建（`npm ci`＋vite v8.3.0，输出 `index-DHhfIjJV.js`／`index-ILAyuRJW.css`，与旧包内前端逐字节一致）。
- 新 EXE：SHA-256 `c6dc19283a24d00a740f2ecbed2cc7159e951f02a37f00636b294b7670369930`，14,743,868 字节；包内 137 文件。旧包（`build/desktop-d1/package/KGNext-D1Verify`，EXE `28e3e60e…`）字节未动；新包输出到独立目录 `package-r18`，构建与验证未终止用户窗口（构建前检查时旧窗口仍在运行；收尾时该进程已不在运行，非本轮操作）。
- 与 fix8 清单对比：文件集合一致（137/137）；仅 EXE 与 `_internal/base_library.zip` 不同——后者条目集合／CRC／大小／时间戳全部一致、仅 zip 条目顺序不同（PyInstaller 构建内部非确定性），不涉及源码内容；干净构建／发行再现性边界不变。
- `verify-package-r18.py`（证据脚本，`problems=0`）：10 个归档模块（含 `app.services.word_export_docx`／`word_export_mapping`）与当前源码代码等价（忽略 co_filename）；前端 `d1.html`＋2 assets 与构建输出及旧包逐字节一致；模板／`alembic-local.ini`／迁移资源与仓库一致。
- 仓外运行：包复制到 `…\package-outside`，与仓库清单 **137/137** 相符（无缺失／额外／大小／散列差异），从独立 cwd、剥离全部继承 `KGM_*` 后运行。

### 21.5 新包实际导出样本与输出检查

7 个真实窗口阶段（前端／关闭链未改，未重复关闭类回归），全部 returncode=0、checks 无 false：

| 阶段 | 内容 | checks |
| --- | --- | --- |
| A-first（园所“验证园所”） | 首次设置、空内容按周导出、保存代表内容后单日导出 | 6/6 |
| A-restart | 长反思（短句重复200次，并非200个换行段落）续写、第二日期计划、两计划自定义范围导出 | 6/6 |
| A-word-r18 | 真实 DOM input 事件写入 720 字长过程并真实保存（v1→v2），单日＋三计划合并导出 | 7/7 |
| A-save-dialog | 真实原生对话框：中文名保存、取消（无写入）、占用失败（旧目标保护＋脱敏）、解除后新 ID 重试 | 9/9 |
| B-first（`--init-school ""`，空园所） | 空园所快照：按周＋单日导出 | 6/6 |
| B-word-r18 | 空园所长过程单日＋两计划合并导出 | 7/7 |
| C-first（30 字长园所） | 长园所快照：按周＋单日导出 | 6/6 |

样本输出检查（`package/sample-checks.json`，13 个文件）：**99 项检查全部通过、0 失败**。覆盖：非空／空／长园所标题显式 center 且文本无空格模拟；署名均为“验证中一班 验证教师”（无年级）；全部表格 run `w:b`／`w:bCs` 显式 false；长过程 120 次出现于单日与合并样本；长反思 200 段；空栏目样本无内容残留；合并文档每份新页（A 合并 7 页 3 份标题页 1/4/6，B 合并 4 页 2 份标题页 1/3）；原生对话框中文文件名、取消后无文件、占用失败保留旧目标、解除重试与对话框保存字节一致（SHA-256 `17013e60ece6…`，14,110 字节）。全部样本无标红（本片无 split_baseline，D1 真实导出不含比较标红）；标红／无基准语义在输出级测试覆盖（有基准：红 run 保留 FF0000 且显式非粗体；无基准：无红、不伪造）。

### 21.6 Windows Word 逐页检查（新样本，非旧样本）

Windows 11（build 26200.9711）、Microsoft Word 16.0（构建 16.0.20430；Office ClickToRun 16.0.20430.20146），页面视图（wdPrintView），由 Word 自身对象模型逐页核对，另存 38 张逐页截图（`word-shots`，DPI 感知 PrintWindow 捕获）：

- 13 个样本共 38 页；每份日计划标题段落 Word 实测 `Alignment=1`（居中）；署名位于各份首页；每份从新页开始。
- 全部表格非空文字段落 Word 实测 `Range.Bold=False`：13 文件累计 **0 处粗体问题**；标红词计数 0；文档字体为模板楷体／仿宋，字号未变。
- 目视复核（截图＋本节记录）：非空园所单日（“验证园所一日活动计划”居中）、空园所单日（仅“一日活动计划”居中）、30 字长园所标题自然换行两行仍居中、长过程页自然分页且文字非粗体、三计划合并第二／三份从新页开始。
- 已知工具边界：Word 自动化中 `ExportAsFixedFormat` 与多步操作后的 `SaveAs2(PDF)` 在本机挂起（打开后立即 SaveAs2 可成功）；PDF 副本未生成，不属于本检查必需项，如实记录，不据此推断用户环境行为。
- 生成链已改，本节不复用旧四份同字节样本作为 Word 通过；WPS 等未验边界继续保留。

### 21.7 变化文件与未验边界

变化文件（SHA-256 前 16 位）：`backend/app/services/word_export_docx.py` `a8b20b2a33ec1a90`；`backend/tests/unit/test_i5_word_export_docx.py` `8decc004633af994`；`backend/tests/local/test_export.py` `b83ecb5cd85281ae`；`desktop/d1_main.py` `27ab274934042937`；`desktop/build_d1.py` `631ac55f29bd4e74`。`git diff --check` exit 0（仅既有换行转换提示）。模板与前端源码未改。

**保持未验：** 用户对新导出格式的复看确认；R18 未最终关闭；教师清单 T6／T7 其余分支、IME 候选词细分动作与屏幕缩放；WPS、干净机器、Windows 10、其他 DPI／多显示器；干净构建／发行再现性；宿主内部许可／保存交错注入。本轮自动验证未新做人手IME按键或人工另存为；§20用户已报告的微软拼音、读回一致和v4仍有效，不能倒退为完全未测。真实教师库／体验合成库未被本轮自动测试写入（体验库保持用户会话状态；自动验证全部使用独立合成目录）。D0／D1A、原 R1–R17 与 28e3e60e… 包历史不变；不启动 D2／真实 AI／WebDAV／发行。

### 21.8 Codex独立复审与证据口径补正

2026-10-17，[审阅§20](desktop-d1-review.md#20-r18-独立复审2026-10-17)确认三项格式修复的代码、相关自动检查及新包一致性通过，未发现新增代码缺陷；**完整Word逐页目视及用户格式确认待补，R18尚未最终关闭。** Codex独立121项导出相关／146项桌面检查通过；仓内外各137文件、12个关键归档模块（仅忽略co_filename，其余代码元数据保留）、前端／模板／迁移与源码一致。新包3次独立真实窗口运行6/6、7/7、5/5通过；OpenCode7次运行及13份样本结构证据核对有效。全量unit的1项既有Windows路径错误保留，未写成全通过。

补正§21.4–21.6的证据精度（不改变原始日志）：原OpenCode归档比较还排除了行号等元数据，并非仅忽略co_filename；本次独立12模块严格比较补足。长反思是短句重复200次，不是200个换行段落。38张截图为100%视图各页位置截图，多数没有完整页底，不能当作38页完整目视证据。目录实际已有93,481字节的2页Word PDF及probe文件，故“PDF副本未生成”仅适用于后续批量尝试；Codex已核对该PDF文字对应A空内容样本，并完整渲染／目视两页。长园所、长过程及合并样本仅独立查看已有局部截图；新开Word捕获连续失败（GetCursorPos拒绝访问、CreateForMonitor失败），完整页面补验仍待完成，详见审阅§20.3。

Codex通过原体验库的只读SQLite备份副本，以新包重新导出10-19 v4，文件位于 `%TEMP%/kgm-d1b-codex-r18-review-20261017/experience-saves/日计划_体验中四班_2026-10-19_2026-10-19.docx`，14,608字节，SHA-256 `c99b9cb75ab3e858ea042c0a7ce39392a151c875228b856054cfdba69bd9802d`；标题居中、署名“体验中四班 体验教师”、38个表格run均非粗体，反思含“重启后验证通过。”。原体验库v4／v1及正文与此前记录一致，完整性通过；旧桌面DOCX与10个受检实现／测试／模板／构建文件散列未变。收尾证据在同根 `final-evidence-audit.json`。首次临时审计脚本误纳入Word的 `~$` 锁文件而报BadZipFile，排除锁文件后通过，是审计驱动问题，非导出文件损坏。

唯一current已转为新Word复看与教师清单剩余项；三项需求与新包身份、旧样本和数据保护边界均已归并规格／本结果／审阅。当前先补验，不安排无依据的代码修改；结果明确后再准备D2规格，不自动启动AI实现或发行。

### 21.9 用户Word确认与重试补验

用户明确反馈已看Word、显示正常，并说明之前可能因自己操作电脑／关闭窗口导致捕获失败，要求重试。Codex重新打开同一v4新样本后，computer-use捕获成功，在Word打印布局单页47%视图补看完整2页（433字），未见截断、重叠或异常分页；用户格式确认及v4完整页面检查已完成。未把用户对原因的推测写成确诊。

打开30字长园所样本后捕获再次报CreateForMonitor失败；刷新选择、激活重试报 `failed to activate captured window`，按技能规则停止操作。长园所2页与三计划合并7页完整页面仍待补，R18尚未最终关闭。v4／长园所／合并样本SHA仍为c99b9cb7…／d72c57f3…／8a0fe5dd…，未修改文件、实现或体验库；没有重跑已通过测试。详情及对应聊天截图见[审阅§20.5](desktop-d1-review.md#205-用户确认与word捕获重试)。T6／T7剩余人工分支与IME细分动作继续按项记账，不扩写为D1产品全通过。

### 21.10 长样本人工逐页验收与R18关闭（2026-10-17）

用户明确反馈：“两份文件都已逐页检查，长园所2页、合并7页均正常，三天计划分别从第1、4、6页开始，署名和表格粗细也正常。请记录结果，继续下一步验证。”验收对象为§21.5中新包实际导出的两份文件：长园所单日14,127字节、SHA-256 `d72c57f35c785584527f5d5c83bff0a2fe48072770dfa59822429253f6f28cef`；三天合并14,779字节、SHA-256 `8a0fe5dd2133f7e31ac4c5b522bdfb1df26af471ad60d2dddbbfcaea9c7afbcb`。交付前只读散列核对一致，完整路径及标准见[审阅§20.6](desktop-d1-review.md#206-用户逐页验收与r18关闭2026-10-17)。

长标题换行居中、长过程／反思续页、页底／末尾无截断重叠、三计划顺序及新页、署名和表格不加粗按用户逐页反馈通过；这是用户人工证据，不冒充Codex独立全页截图。交付时Word自动化窗口读取在重新定位后仍超时，Codex已按技能停止输入，用户随后自行逐页完成检查。

结合§21.8代码／新包／结构检查和§21.9用户格式确认、v4完整两页，**R18关闭**。原R1–R17、D0／D1A和旧包历史不变，无新实现／测试／构建变更，无需重复既有通过测试。下一步先T7人工另存为取消后重试，再T6设置及微软拼音细分动作；D1产品与发行未整体验收，不启动D2／真实AI／WebDAV／发行。
