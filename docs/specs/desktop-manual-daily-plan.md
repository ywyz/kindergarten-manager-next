# D1 本地手工日计划实施规格

状态更新：2026-10-17。适用Architecture v2；§2–6、§8保留D1A基线，§9–13保持已确认契约。**D1B第八轮复审关闭R17，原17项全部关闭，在当前Windows 11开发机工程复审通过，见[审阅§17](../bootstrap/desktop-d1-review.md#17-d1b-第八轮修复复审与工程收口2026-10-17)。** 原133本地／108回归／146桌面、纯逻辑＋60组件及28e3e60e…包证据保持。用户确认读回一致、修改v4和微软拼音；§12.4的R18格式修复已实现，独立121导出相关／146桌面、新c6dc1928…包137文件／12模块和3次真实窗口检查通过。用户已确认新Word正常、Codex已补看v4完整两页；用户又逐页确认长园所2页、合并7页及1／4／6页起始、署名和表格粗细正常，R18已关闭，见[复审§20.6](../bootstrap/desktop-d1-review.md#206-用户逐页验收与r18关闭2026-10-17)。T6-A／T6-B／T7及微软拼音本轮验证通过，教师体验按§13.4收口；产品与发行未整体验收，下一步见[当前任务](../tasks/current.md)。

## 1. 分片及产品决定

| 切片 | 范围 | 不等于 |
| --- | --- | --- |
| D1A，3.14.7 基线上工程通过 | 独立本地数据库／Alembic、一次原子初始化、上下文／有效日历读取、手工日计划创建／读取／保存及真实数据库测试 | 桌面页面、Word、本地配置维护或完整 D1 已交付 |
| D1B，原R1–R17工程通过；R18已关闭，本轮教师体验收口 | 首次设置页、工作台及真实日计划表单、离开自动保存、当前班级维护、多学期及日历维护、Word 范围／缺项确认及原生保存 | 当前Windows 11＋Word下本轮体验通过不等于完整产品／发行验收；多班新增／切换、AI 闭环、WebDAV、发行及其他业务不在本片 |

用户于 2026-10-11 确认：首次一起填写**姓名、班级名称＋年级、学期名称＋起止日期**；园所名称可留空后补。关闭窗口、切日期或离开编辑页时，有未保存内容则**自动保存成功后离开，失败留在当前页**。技术核查与规格由 Codex 完成，OpenCode 负责代码、测试、迁移及构建脚本的写入。

继承[身份 Contract](../modules/identity-and-class.md)、[日计划 Contract](../modules/daily-plans.md)及旧规格的非冲突规则：一个稳定本地身份；同班同日一份有效计划；允许空内容保存；创建时表头快照不可变；日历例外优先、未知年份不猜测；内容版本追加、过期保存拒绝。旧账号／分班／管理员、MySQL 行锁、全班周投影及 `plans_started_at` 配置冻结不进入本地契约。

## 2. 本地入口与隔离

- 新增 `backend/app/local/` 包，独立 Base／模型、数据库事务封装、schema、服务和 app factory；内部组织可按职责拆文件。不得导入旧 `app.main/config/database/models/deps` 或挂载旧认证／管理员／周计划／AI 路由。
- 使用现有 SQLAlchemy 2.x、Alembic、sqlite3、FastAPI 和日期库。新增 `backend/alembic-local.ini`、`backend/migrations_local/`，独立版本表及初始 revision；保留 `backend/migrations/` 历史。禁止把旧 MySQL revision stamp 到新库或用 `create_all()` 代替正常初始化／升级。
- D1A 验证环境使用独立 `backend/.venv`。允许用现有本机 Python 及 `uv sync --locked` 恢复 `backend/uv.lock` 已锁定依赖（含 Alembic 1.20.0、chinesecalendar 1.11.0）；不新增／升级依赖、不改声明和锁、不改 D0 环境或系统包、不下载新解释器。锁定依赖的下载属于本片环境准备，不解除 Skill／MCP 安装限制；不得以缺少 Alembic 为由把真迁移改为 mock 或 `create_all()`。
- 2026-10-13 [版本核查 §7](../bootstrap/desktop-d1-technical-review.md#7-python-版本统一核查2026-10-13)确定 D1 开发、桌面宿主及打包统一目标为 **CPython 3.14.7／Windows x64／标准 GIL**。后端已使用此版本；D0 环境仍为 3.12，保持历史身份。后续独立 D1 桌面环境以 backend 业务锁为基线补齐桌面／打包依赖，两套锁不能直接拼接。版本与依赖配置由 OpenCode 在相应环境落实任务中对齐，本次决定不等于已安装、切换或新包通过；3.12 不再是唯一放行门槛，3.15 不在当前验证基线。
- 正式数据目录为 `%LOCALAPPDATA%\KindergartenManager\data\`，数据库名 `kindergarten.db`；路径在本地入口中解析为绝对路径。测试必须注入临时数据根目录，不能污染真实教师目录。D0 的 `KindergartenManager-D0` 和 `d0_probe.db` 保持隔离，无导入、改名或搬迁。
- 首次运行仅对空库执行本地基线迁移，已有已知 revision 升到当前 head；较新／未知 revision，或非空业务库没有本地版本记录，明确拒绝启动，不清库、不降级、不自动 stamp。异常保留原文件并报告，不能继续开放可写 API。
- D1A 提供可被宿主调用的 app factory，注入数据路径及本次启动的 host／port／session token；不启动 GUI 或新发行构建。绑定 `127.0.0.1`，保持 D0 已验证的精确 Host、写请求 Origin、`X-App-Session` 校验，全部业务读写含首次设置也受保护；禁用公开文档页，不放开 CORS。健康检查仅返回就绪状态，不含档案、路径或会话材料。
- 会话 token 每次启动生成，只存内存；不能写 URL、日志或业务表。该 token 与稳定教师 ID 是两个不同概念。业务 API 失败不得产生旧登录／重置密码流程。

## 3. D1A 持久对象与约束

以下为必需语义及数据库保证，物理命名可在 `local/` 内保持清晰一致。

| 对象 | 必需内容与约束 |
| --- | --- |
| 本地教师档案 | 随机稳定不透明 ID（沿用 22 位 URL-safe ID 形式）、非空姓名；singleton 键 CHECK 为 1 且 UNIQUE，最多一个档案。姓名不是主键，也不随启动重新生成 |
| 本地设置 | 单例；园所名可空；当前班级关联；初始化请求 ID 及正规化输入指纹用于重试。首次事务一起建立，不允许半初始化 |
| 班级 | 稳定 ID、正规化名称、`small/middle/large` 年级；本地范围名称唯一；升班未来保持 ID。D1A 只有首次创建，不提供增删／切换入口 |
| 学期 | 稳定 ID、名称、起止日期，CHECK `start_date <= end_date`；闭区间不重叠／不共端点由短写事务内重查保证；当前日历修订指针归属本学期 |
| 日历修订与日历日 | 修订号、学期、库版本、完整有效日期快照；`(term_id, revision)`、`(term_id, id)` 和 `(revision_id, date)` 唯一，修订号 CHECK ≥ 1；逐日保存基础状态、例外及生效状态，允许 `unknown`；首个修订原子生成。已存修订不随库升级重算 |
| 日计划头 | ID、班级／学期／作者 FK、日期、周次／星期、创建所用日历修订、创建时四项表头快照、时间、当前内容指针；保留软删字段但不开放删除／恢复 API |
| 日计划内容 | ID、计划 FK、version、raw_lesson_plan、split_baseline、adopted_content、编辑者及时间；历史追加，不修改旧版本 |
| 操作记录 | 本地 actor FK、动作、业务对象、实际提交版本、时间；初始化、创建、保存与其业务变更同事务提交；不保留旧账号专属字段 |

约束固定为：

1. 有效计划采用唯一局部索引 `(class_id, plan_date) WHERE deleted_at IS NULL`，不再使用冗余 `effective_date`。不可把教师或学期加入该唯一键而放宽约束。
2. 内容具备 `UNIQUE(daily_plan_id, version)` 及 `UNIQUE(daily_plan_id, id, version)`。头部的 `current_content_id/current_content_version` 均非空、版本 CHECK ≥ 1；内联复合 FK `(id,current_content_id,current_content_version)` 引用内容三元组，`DEFERRABLE INITIALLY DEFERRED`。预分配两个 ID，同事务插入头、首版内容及日志后提交，缺首版无法提交。
3. 日历修订具有候选键 `UNIQUE(term_id,id)`；学期 `(id,current_calendar_revision_id)` 与日计划 `(term_id,calendar_revision_id)` 均以复合 FK 引用它，约束修订归属。学期首个非空指针与修订通过延迟 FK 同事务建立；日历日／内容／操作记录的外键必须在每个连接上生效。
4. SQLite 使用原生 TEXT 二进制比较、`length()` 与命名 CHECK／FK／索引，不注册 MySQL 同名函数／collation 掩盖旧 schema。日期使用标准 ISO 日期，时间使用 UTC；业务周次根据本地日期而非 UTC 时刻计算。
5. SQLite 原语实验已经通过，真实 Alembic 必须再次验证循环 FK 建表与提交。后续 batch 重建不假定自动处理全部循环关系；本片不实现降级或删除真实业务库。

字段长度沿用已审查正规化：姓名 1–80、班级／学期名 1–80、园所名空或 1–120；剔除首尾空白，不添加样例姓名或推测学期日期。游戏配置、班级教师名单和保育员不新增为首次必填项；D1A 不用空配置假称已完成 AI／周计划配置。

## 4. 初始化与有效日历

`GET /api/local/context` 返回 `uninitialized` 或 `ready`。就绪时包含稳定 profile、school_name、当前班级、学期及当前日历修订；未初始化时不伪造默认业务资料。schema／持久数据损坏是错误，不回退到首次设置覆盖已有库。

`POST /api/local/initialize` 输入 `request_id`（UUID）、`display_name`、`class_name`、`grade`、`term_name`、`start_date`、`end_date`，可选 `school_name`。ID、创建人和日历版本由后端产生，拒绝额外字段。

处理顺序：正规化参数 → 短读事务检查已提交的初始化记录并返回相同 key 的已有结果或冲突 → 若尚未初始化，结束读事务并构建完整日历候选 → `BEGIN IMMEDIATE` → 再次检查是否已经初始化 → 建立档案、配置、班级、学期、日历修订／日期和审计 → 提交后才返回 ready。库不支持的年份可保存 `unknown` 日，不伪造上课日；日历库运行故障则失败，不能混成年份未覆盖。已经提交的同 key 重试只读回原对象，不因当前日历库故障而重新构建或失败。

首次成功返回 201；相同 request_id 与相同正规化输入重试返回已建对象 200，不重复建数据／审计。同 key 不同输入返回 `INITIALIZATION_REQUEST_CONFLICT`，其他 key 在已初始化后返回 `ALREADY_INITIALIZED`（均 409），不覆盖原档案。前端将来在结果不明时重用原 key，可通过 context 读回；初始化全部失败后仍为 uninitialized。两个进程竞争也不得生成第二套配置。

日期判断只读已持久化的有效修订。周一至周日为一周，起始日所在周为第 1 周；假期计周、跨年不重置、调休按真实日期所在周。非上课日／学期外／unknown 拒绝新建且返回明确原因；已有计划仍能读取。D1A 尚未提供逐日例外和学期维护 API，这些入口属于 D1B，不能宣称未知年份已经可由教师完整配置使用。

## 5. D1A API 与保存契约

除 health 外，所有端点须通过应用会话保护；只有 context 与 initialize 可在无档案时使用，其余返回 409 `LOCAL_PROFILE_REQUIRED`。身份、班级、日期对应学期由服务器推导，客户端不得传入 creator／class／term 或权限字段来切换归属。

| 接口 | 输入及输出 |
| --- | --- |
| `GET /api/local/calendar?from=YYYY-MM-DD&to=YYYY-MM-DD` | 闭区间，from ≤ to，最多 366 日；逐日返回 date、term_id（或空）、week_number／weekday、effective_state、date_eligible、reason、revision_id、existing_plan_id（或空）。创建资格与已有计划入口分开；无上课资格仍可打开已有记录 |
| `GET /api/daily-plans?from=...&to=...&offset=0&limit=100` | 已保存有效计划，日期升序，返回 items／total／offset／limit；limit 1–200，范围两端必填且 from ≤ to，不过滤为仅当前上课日 |
| `GET /api/daily-plans/by-date?date=...` | 当前班级该日有效计划，存在返回详情，不存在 404 `DAILY_PLAN_NOT_FOUND` |
| `GET /api/daily-plans/{id}` | 本地所属计划详情；未找到／软删返回同一 404，不需要日期仍然可新建 |
| `POST /api/daily-plans` | plan_date，可选 raw_lesson_plan、adopted_content；新建首版 version=1，201；同日已有返回现有详情 200，不改任何版本／内容／日志 |
| `PATCH /api/daily-plans/{id}` | 严格整数 expected_content_version ≥ 1，可选 raw_lesson_plan、adopted_content；提交成功返回规范化完整详情，200 |

详情保留旧 `DailyPlanOut` 的身份、日期、表头、当前指针、内容、时间字段，**去掉 weekly_sync_state**；不生成替代空摘要。内容结构与[手工保存规格](manual-daily-plan-save.md)及 `daily_plan_content.py` 一致：允许空内容，原文可编辑；组／游戏 ID 服务器生成，新对象不带 ID，旧 ID 只能属于当前计划当前版本，拒绝未知、重复及跨计划 ID。`split_baseline` 仅服务器持有，本片为 null，客户端提交此字段即拒绝；不能从人工表单伪造基准。

PATCH 中遗漏字段继承当前值，显式 raw_lesson_plan=null 清空，adopted_content 若出现必须为对象。成功保存追加版本 +1；无修改的离开操作由前端不发请求，后端不擅自去重用户明确保存。过期 expected version 返回 409 `VERSION_CONFLICT`，不自动用最新版本再提交。重复创建先读已有有效记录，已有记录不因新建日期资格变化而失去打开能力。

错误统一采用 `{error:{code,message}}`，不暴露 SQL／本机绝对路径／token。字段或结构非法 422 `VALIDATION_ERROR`；新建资格为 `OUTSIDE_TERM`／`DATE_NOT_ELIGIBLE`／`YEAR_NOT_COVERED`（422）；错误会话 401 `APP_SESSION_REQUIRED`，不受信任 Host／Origin 403；数据库忙 503 `LOCAL_DATABASE_BUSY`，I/O／完整性／持久数据错误 503 `LOCAL_STORAGE_ERROR`；默认日历运行故障 503 `CALENDAR_UNAVAILABLE`。不把任何完整性错误统一解释为重复创建或版本冲突。

## 6. SQLite 事务与保存失败

- 每个物理连接启用并核验 `foreign_keys=ON`、`busy_timeout=5000`、`synchronous=FULL`；文件库为 WAL。每请求独立 Session，读写事务开始方式统一封装，关闭 sqlite3 隐式 BEGIN，避免 ORM 与驱动双重起事务。
- 最终写事务在其中的任何业务读之前发出 `BEGIN IMMEDIATE`；允许初始化的独立短读预检，但必须先结束预检事务，不从身份依赖或预检已开启的读事务升级写事务。参数结构校验、日历候选构建在锁外；锁内重读上下文、日期／当前版本，完成必要校验和短写入。
- 保存锁内核对 expected version；追加内容、带旧版本条件更新指针并检查影响行数、写操作记录、COMMIT。提交成功才能响应成功。保护范围包括 flush 和 COMMIT 阶段；延迟 FK 提交失败也必须 rollback。
- 读取使用实际 SQL `BEGIN` 包围所有关联 SELECT，得到完整旧版本或完整新版本，不能只凭 `Session.begin()` 表象认为 sqlite3 已提供快照。不能把读事务延续到 Word 生成或宿主对话框。
- 通过 `sqlite_errorcode/sqlite_errorname` 分类忙等待、I/O 和约束失败；仅确认是有效日期唯一约束冲突时，rollback 后以新事务读取赢家作为“打开已有”。忙等待最多 5 秒，失败保留原内容；不自动重发提交结果未知的保存。
- 不创建周投影、未来任务占位或 outbox。保留作者与内容版本足以为以后本人周来源提供依据，本片日保存无周服务依赖。

## 7. D1B 已确认行为与后续设计边界

本节约束后续实现，**不纳入当前 D1A 编码**。

1. 复用真实表单及空值／组 ID 映射，采用服务端成功返回的正规化内容建立 dirty 基线。手动保存与离开保存共用明确的成功／失败结果；409 保留输入，不静默覆盖。
2. 关闭窗口、切日期、返回日历、进入设置等统一经过离开协调。dirty 时等待保存完成，成功才执行原动作；失败留页并保留输入。保存期间防重复离开与并发编辑造成新输入遗漏；无 dirty 不产生新版本。宿主先取消正常关闭请求，等待页面确认后才销毁；不能靠 `onBeforeUnmount`／`beforeunload` 等待异步保存，不扩为定时自动保存或强制终止后的草稿恢复。
3. 导出仍使用**数据库已保存版本**，导出操作不修改计划。离开自动保存不扩为导出自动保存或强制保存门槛。范围按日期升序、多份新页开始，无匹配不生成空文件，缺项确认后允许留空输出。
4. 显式读事务内固定计划、内容版本与缺项确认事实并物化 DTO；结束事务后生成 Word；需要生成审计时另开短写事务。确认对象变化则重新 409。原生保存结果区分生成失败／取消／保存失败／实际保存成功，不以下载开始或生成审计宣称落盘成功。
5. 配置维护落实园所后补、资料与班级／学期维护、逐日例外、已有计划影响预览与版本复核。2026-10-14 的范围决定及具体契约见 §9–10；不沿用第一份计划后永久冻结配置，不静默改历史表头。删除／恢复、内容历史版本浏览恢复、AI 配置另按切片安排；旧学期已保存计划的日常访问／编辑属于本轮。

## 8. D1A 必需验证与交付

| 验证 | 必需证据 |
| --- | --- |
| 本地 Alembic | 临时真实文件空库升至 head；重复启动不改数据；未知／更高 revision 及无版本的非空库拒绝；连接与 FK／CHECK／索引实存 |
| 初始化 | 必填／日期／年级校验；整套原子创建；中途失败无半初始化；同 key 重试、不同 key 竞争、同 key 改输入不覆盖；成功后日历 provider 故障，同 key 仍读回 200，不同 key 仍 409 |
| 内容和归属 | 空内容、所有真实栏目、原文、稳定游戏 ID；拒绝假归属／基准／跨计划 ID；创建表头和日期信息不可变 |
| 指针与回滚 | 缺首版、错版本、跨计划指针及重复内容版本被拒绝；内容插入、指针更新、审计、提交各阶段失败保持原内容／版本／日志 |
| 真实文件并发 | 至少两个独立连接，并有独立进程重复创建验证；同日只有一份，两个同 expected version 保存只有一个成功，冲突不多写历史／日志 |
| 数据库忙与读取 | 写锁超时返回明确失败，释放后重试正常；用同步屏障验证多 SELECT 一致快照，不依赖碰运气 sleep |
| 日期 | 端点／周次／跨年、库调休、unknown 和库故障分离；缺日历行报错，重启不按库新版本重算；已有记录读取不依赖当前 date_eligible |
| 进程重启 | 临时文件真实退出重开，教师 ID、班级／学期、日历、内容历史、当前指针和日志保持一致 |
| 依赖及防护 | 不加载旧 settings／dotenv，不连接 MySQL，不依赖旧账号／周表；无／错 token、错误 Host／Origin、额外归属字段被拒绝；正常请求成功 |

OpenCode 编写并运行必要测试，报告命令、exit code、数量、skip 原因及临时路径；不以纯 mock／内存数据库取代上表真库证据。D1A 结果统一写入 `docs/bootstrap/desktop-d1-result.md`；Codex 独立复审并执行相关验证。2026-10-13 [最新审阅 §7](../bootstrap/desktop-d1-review.md#7-版本统一与-d1a-放行2026-10-13)：R1–R6 及日期边界代码问题已关闭；所选 3.14.7 基线的 87 项本地测试、108 项相关回归通过，D1A 工程放行。3.12 全套及串行重跑的原生异常和未知根因保留，不能写成两套均通过；本轮版本核查沿用散列未变的既有测试证据，没有重新执行全套。

后续统一桌面环境后须运行完整 D1A 套件，若共享依赖变化则重跑相关回归，并补真实 WebView2／宿主回调／关闭／原生保存和同解释器目录包仓外运行证据。2026-10-14 配置维护范围与工程接口收敛见 §9–13；不能用“D1A 放行”代替 D1B 验证。

D1B 再增加真实 Windows 启动／退出自动保存、失败留页、版本冲突、长内容与空内容、范围／确认变化、原生取消／占用失败／重试，以及 Word 全页查看。D0 92 项测试与合成 Word 通过不替代这些业务验收。

## 9. D1B 产品范围收敛（2026-10-14）

本轮先核对 §1、§7、[身份 Contract](../modules/identity-and-class.md)、[历史表头决定](manual-daily-plan-save.md#43-历史表头规则已决定a)和[I2 P1–P3](class-assignment-and-calendar.md)，只就班级维护范围、学期及已有计划编辑范围提问。用户在本轮明确选择两项推荐方案，以下没有待实现者猜测的产品分支。

| 事项 | 分类与依据 | D1B 结果及已有计划影响 |
| --- | --- | --- |
| 姓名、园所名称维护 | 已确认维护方向，§7／身份 Contract；园所可后补见 2026-10-11 决定 | 设置中可改姓名、补填／修改／清空园所；使用原长度和正规化规则，姓名不得为空。既有四项表头不变，空园所的旧计划不被补写 |
| 当前班级名称、年级及升班 | **本轮用户确认**；年级集合、升班沿用 ID 已由 I2 P2/P3 和 §3 继承 | 可改名、改年级，同班升班沿用原 class_id；不另造新班，不改旧计划表头或归属 |
| 班级新增／多班切换 | **本轮用户确认后置** | D1B 不提供成功的新增／切换接口或入口；日计划仍由服务端确定唯一当前班级 |
| 学期新增、名称／起止日期维护及切换 | **本轮用户确认纳入** | 可新增学期、改名、改起止日期、选择学期浏览；闭区间不得重叠或共端点，原 term_id 保持 |
| 旧学期、移出范围或改为停课的已有计划 | **本轮用户确认继续编辑、导出** | 读取／保存不再检查当前新建资格；保留原 class_id、term_id、日期、周次、weekday、创建日历修订和四项表头。内容保存仍追加版本 |
| 创建时快照，不按计划日期追溯资料 | 已确认：手工保存规格 §4.3／§5.7 与本规格 §1 | 修改资料前提前创建的未来计划保留旧资料；修改后回补旧日期的新计划用创建当时当前资料。不新增按日期维护班级／姓名版本 |
| 日历例外、影响预览、确认复核、新修订 | 已确认行为，身份 Contract「日历调整」「调休判断」；协议由工程设计确定 | 例外优先，unknown 不猜测；改范围／例外不静默重算历史。具体见 §10 |
| 切学期的状态与日期解析 | 工程设计可确定，落实上述用户范围 | 切换仅改变浏览筛选，不修改计划归属、不把“选中学期”当作新建日期归属；不持久化额外的“当前学期权威指针” |

旧云端“调班后原班计划不可修改”依赖旧权限流程，不继承为本地旧学期只读规则。旧学期当前保存版本的日常访问属于 D1B；**内容历史版本的查阅／比较／恢复**仍后置。AI、班级游戏配置、班级教师名单／保育员、WebDAV、删除／恢复、其他业务与发行不扩入本轮。

## 10. D1B 本地上下文与配置契约

以下为待 OpenCode 实现的增量契约，不表示接口已存在。沿用 §2 的会话保护、§6 的显式事务；§5 的错误 envelope 增量为 `{error:{code,message,details?}}`，details 按 code 承载下文配置版本、确认事实或限制，不改变旧错误的 code/message。须同时适配本地异常 handler、schema 与 D1 客户端，不能在 handler 中丢弃 details。日期为 ISO 日期，配置版本为严格正整数；拒绝额外字段。全局 `config_version` 属于单一本地档案的配置并发控制，不是内容版本，也不是架构或数据权威变更。

### 10.1 上下文、日期与历史入口

| 接口 | 请求与响应语义 |
| --- | --- |
| `GET /api/local/context?date=YYYY-MM-DD` | date 可省略，省略时使用宿主电脑本地日期。未初始化仍返回 `status=uninitialized`；ready 返回原 profile／school_name／class，新增 `config_version`、`as_of_date`、`terms:[{id,name,start_date,end_date,current_calendar_revision_id}]`（start_date、id 升序）。原 `term`／`calendar_revision` 表示 as_of_date 所在学期及修订，学期外均为 null，不能将 ready 误判为未初始化 |
| `POST /api/local/initialize` | §4 的输入与 201／200／409 保持；首次 config_version=1，响应采用增量 context 结构。同 key 重试返回当前配置，不能把后续维护回滚为首次输入 |
| `GET /api/local/calendar?from=...&to=...` | 保留 §5 的日期窗口和逐日结构。term／revision／week_number 表示当前有效配置对日期的解释；`existing_plan_id` 独立查询当前班级同日记录，**包括当前学期外**，不因资格为 false/null 清除 |
| `GET /api/local/terms/{term_id}/daily-plans?offset=0&limit=100` | 新增旧学期入口，按计划保存的 term_id 查询全部有效记录，不用修改后的学期起止日期再裁切。items／total／offset／limit、排序与 §5 一致，item 补 class_id／term_id；不存在的学期 404 `TERM_NOT_FOUND` |
| 既有日计划列表、by-date、详情和 PATCH | 日期列表仍可跨学期；详情按已存 ID／归属返回，PATCH 不重验新建资格。无／错班级记录 404；不接受客户端伪造 creator／class／term 来改变归属 |
| `POST /api/daily-plans` | 先找当前班级同日已存记录，存在仍 200 打开且不改内容；只有不存在才按日期解析不重叠的学期及该学期有效修订。新增可选严格整数 `expected_config_version`；D1B 页面必须传入最近读取值，不符返回 409 `CONFIG_VERSION_CONFLICT` 并重取日期解释后由用户重新点击创建。省略保留 D1A 调用兼容，服务端仍在写锁内解析当前配置 |

现有列表的日期必填契约不改；新 term 列表解决“原学期计划被移出新范围后不可见”的问题。一个日期落入新学期而该日已有旧学期计划时，日历的当前日期解释与计划详情可能不同：明确显示提示，打开／重复创建均返回原计划，不迁移归属、不建立第二份。唯一键继续是 `(class_id,plan_date)`，不能加入 term_id。

工作台先读 context，再读日历和已保存列表。默认显示本机今天所在月份；没有匹配学期仍显示已保存入口和“选择／设置学期”，不伪造学期。选择某学期定位到其起始月份，并提供其全部已保存计划列表；列表中的范围外记录附状态提示且可打开。首次设置的字段、初始化 request_id 重试和半初始化错误遵守 §4；服务／持久数据错误显示重试，不进入空设置页覆盖数据。

所有日期、学期和详情读取带前端请求序号；只应用当前选择对应响应。加载中不允许对旧详情写入。点击无记录且可创建的日期先展示创建确认，确定后 POST；普通浏览不自动创建空计划。已有记录入口优先于 date_eligible；未知年份可进入设置逐日配置，不能弹旧“联系管理员”文案。

### 10.2 配置请求与预览响应

采用一个预览／应用协议，保证每次确认对应同一组修改，不需要新的服务或消息组件。允许的 `change` 为以下互斥对象；本轮不实现跨操作批量事务。

| kind | change 字段 | 规则 |
| --- | --- | --- |
| `profile` | `display_name, school_name` | 两字段完整提交，school_name=null 清空；稳定 profile ID 不变 |
| `current_class` | `name, grade` | 当前班级完整提交；仅 small/middle/large，ID 不变 |
| `term_create` | `name, start_date, end_date` | ID 由服务端产生；事务内再次检查所有学期范围不相交 |
| `term_update` | `term_id, name, start_date, end_date` | 改指定本地学期；没有删除、换 ID 或批量转移计划 |
| `calendar_override` | `term_id, date, state, reason` | 一次一个日期，state 为 teaching/non_teaching/null；非 null 时 reason 首尾去空后 1–200 字，null 撤销例外且 reason 必须 null；日期必须在该学期当前范围 |

`POST /api/local/config/preview` 输入 `{expected_config_version, change}`，不写业务表、版本或审计。200 返回：

- `expected_config_version, normalized_change, changed`；无实际修改 `changed=false`，不能制造新修订。
- `preview_token, expires_at`（包括 changed=false 的预览）；令牌绑定本次启动、正规化修改、配置版本、候选日历摘要与完整影响事实，使用独立内存密钥 HMAC-SHA256 签名，有效期 10 分钟，不包含教案正文。重启／过期需重新预览，不落盘密钥。
- `before, after`（资料或学期字段）；`calendar_diff:[{date,before_state,after_state,before_week,after_week,override_before,override_after}]`，学期外状态显式为 outside_term，包含例外原因变化；仅改名不虚构日期变更。
- `impact:{retained_header_count, affected_plans:[{id,plan_date,term_id,content_version,stored_week_number,proposed_week_number,creation_eligible_after,reasons}], counts}`。资料／班级维护列出保留旧表头的真实计划；范围／日历维护列出状态、周次或当前日期解释会变化的真实记录。`reasons` 使用 `header_retained/date_state_changed/week_changed/outside_new_range`；显示已有记录仍可编辑导出且不会重写，不显示占位“影响 0 条”。新学期覆盖原有记录日期也须列出。

界面展示字段前后值、日期变化、已有计划数量和可查看完整清单。用户确认后调用应用；编辑任意输入、关闭预览或更新配置后废弃令牌，不能沿用旧确认。

`POST /api/local/config/apply` 输入 `{request_id:UUID, expected_config_version, change, preview_token}`。首次提交 200 返回 `{status:"applied",request_id,config_version,changed:true,affected_plan_ids,calendar_revision_id}`；资料修改的 calendar_revision_id=null。同 request_id＋同正规化请求重复返回原提交结果（可额外 `replayed:true`），不能再写版本／审计；同 key 异输入 409 `CONFIG_REQUEST_CONFLICT`。输入指纹绑定 expected_config_version＋normalized_change，不包含 request_id 和可重新签发的 preview_token；重试先查成功回执，再查令牌期限。前端随后重读 context／当前视图。preview 的 changed=false 由 UI 直接结束，不调用 apply；如客户端仍提交该有效预览令牌，服务端锁内核实无变化后返回 `{status:"unchanged",request_id,config_version,changed:false,affected_plan_ids:[],calendar_revision_id:null}`，只记录同 key 幂等回执，不新增配置版本、修订或审计。其后配置变化，同 key 重试仍返回原 unchanged，不能突然实施旧请求。

持久成功回执只保存 request_id、输入指纹、结果 JSON、提交配置版本和时间，用于结果不明后确认；不保存整份教案。新增 `GET /api/local/config/operations/{request_id}` 返回同一成功回执，未提交 404 `CONFIG_OPERATION_NOT_FOUND`。读取失败不推断未提交；查询不存在也不自动换 key 重发。用户明确重试复用原 key，先查已提交回执，再校验令牌是否过期。

错误补充：409 `CONFIG_VERSION_CONFLICT`／`CONFIG_PREVIEW_STALE`（含影响对象变化）／`CONFIG_PREVIEW_EXPIRED`／`CONFIG_REQUEST_CONFLICT`；422 `TERM_OVERLAP`、`VALIDATION_ERROR`（含例外越界和非法／缺失令牌）；404 `TERM_NOT_FOUND`。版本冲突在 `error.details` 返回最新 config_version，不泄露正文。错误保留设置输入并清除旧确认，重读和重新预览后才能确认；503 沿用本地存储／忙／日历故障分类。

### 10.3 事务、新修订与数据增量

1. 新增 `LocalSettings.config_version`，D1A 升级初值 1，CHECK ≥1；新增配置成功回执表（request_id 唯一）。使用**新的本地 Alembic revision**，不修改既有 revision、不重建库、不改旧 MySQL 链。初始化和 D1A 原字段、历史数据保持。新增表／列由 OpenCode 实施与真库验证。
2. 预览在显式短读事务中取得配置、当前修订及相关计划头／版本，物化后结束事务；在锁外建立候选并签名。应用先短读检查同 key 成功回执，再用短读快照重建同样候选；库调用、正规化及差异计算不占写锁。
3. 最终 `BEGIN IMMEDIATE` 后先重查成功回执，再查 config_version、全部学期的范围／当前指针、相关完整计划集合和版本。与预览摘要不同，即使影响减少，也返回 `CONFIG_PREVIEW_STALE`；不得只比较影响数量。新增计划、内容保存、另一配置提交均可能使相关预览失效。
4. 锁内确认无重叠、对象仍存在且所有候选前提未变，才写资料／学期、日历新修订及全部日期、当前修订指针、config_version+1、操作记录及成功回执，一次 COMMIT。任一 flush／COMMIT 失败整体 rollback。无变化不增加配置版本。普通内容保存不增加 config_version，但预览的计划版本摘要会检测它。
5. 园所／姓名／班级修改不产生日历修订；学期仅改名也不产生修订。新增学期建首个完整修订；起止日期或例外实际改变建 revision_no+1。旧修订和日期不被覆盖，既有计划的 calendar_revision_id／周次等不改，也不增加其内容版本。
6. 沿用 [I2 日历修订规则](class-assignment-and-calendar.md)：新范围与**当前修订范围的交集**复制既有基础值、库版本和例外；新增日期按本次库输入建立基础值，override=null，不从旧修订自动恢复曾经移出的例外。范围缩后再扩亦遵守此规则，预览说明重新纳入日期的当前默认状态；教师需要例外时显式设置。只对本次指定日期设置／撤销例外，交集内其他日期不借机因库升级重算；撤销回落到持久基础值，基础为 unknown 时恢复 unknown。移出日期的旧行／例外仍留在旧修订，无删除、无追溯改写。
7. 未知年份的新增日期持久化 unknown；本次库调用真正故障返回 CALENDAR_UNAVAILABLE，不混作 unknown。既有日期的例外调整可使用已存基础，不因库版本升级主动调用库。有效状态始终等于 override 或 base；新修订完整覆盖新范围，读取缺行仍报存储错误。
8. 对计划只更新 UI 的当前日期解释，不追溯改变原 term_id、周次和历史表头。D1B 不存在周计划业务，因此不制造空周表或假“已处理周冲突”；以后周计划进入本地规格时再补对应影响契约。

采用全局配置版本是单档案下的简洁并发保证；计划内容采用自身 expected version，二者不能混用。预览令牌保护用户看到的具体影响，回执解决配置提交响应丢失后的重试；它们都不代替 SQLite 写锁与事务内重查。

## 11. 表单保存、统一离开与宿主握手

### 11.1 页面与 dirty 基线

新增独立 D1 前端入口（建议 `frontend/d1.html`、`src/d1/`、`vite.d1.config.ts`），首次设置／工作台／编辑器／设置在同一应用壳内切换。复用真实栏目与 `daily-plan-content.ts` 的纯映射，不能直接挂载旧 App 的账号／管理员导航、旧 API 客户端和 weekly_sync_state。所有本地请求带内存 `X-App-Session`；会话不可用显示宿主连接失败，不能跳旧登录页。`get_bootstrap()` 仅向受信任同源 D1 页面提供本次会话和桥接协议版本，不通过 URL、持久存储或日志传 token。

编辑器状态明确为 loading／ready／saving／conflict／save_failed。只在对应 planId 的详情成功加载后允许编辑；首次打开不存在的日期另设 create_confirmation，不能把 404 或加载失败当作空计划保存。

`baseline` 是服务端成功返回的 raw_lesson_plan 和 adopted_content **经 serverToForm 再 buildAdoptedContent 得到的可保存值**；raw 使用统一空值／换行正规化。dirty 比较同样的正规化投影，不包含时间、版本号、消息、加载状态或只读表头。保持栏目缺失、空字符串／null、游戏组／游戏 ID 的既有映射，不凭显示默认值制造“体能大循环”数据。数组顺序有语义，不排序抹平。允许真正空内容保存。

手动与离开保存使用同一个 `saveCurrent()`，返回 `{status:unchanged|saved|failed|conflict|indeterminate, plan_id, version?}`。无 dirty 时返回 unchanged、不发 PATCH，手动保存按钮可禁用；后端对其他明确提交的 PATCH 仍遵守 §5 的追加版本契约，不在本轮改为内容去重。

### 11.2 保存期间输入、冲突与结果不明

1. 保存前同步置 saving／离开 busy，阻止新导航、组增删／排序和其他编辑入口；已开始的输入法组合继续接收最终 compositionend／input，不提前禁用当前输入控件或丢弃末次事件。组合结束且 Vue 更新完成后才锁定全部文字／结构／程序编辑，捕获 planId、expected version、editEpoch 和不可变 payload。持续组合输入时继续留页，不靠超时截断最后一段汉字。
2. 每个计划最多一个在途保存。重复手动保存或离开共用同一 Promise，不并发 PATCH。服务成功响应后使用正规化内容和服务器组／游戏 ID 建基线；无中途输入才能整体回填表单。
3. 仍需防御锁生效边缘的晚到输入：每次编辑递增 editEpoch；响应的 planId／epoch 不符时，不调用全量 applyPlan 覆盖新值，不执行离开。已提交 payload 的返回内容保留为新 baseline／version，新输入继续 dirty。新组／游戏以本次提交前的界面临时 key 与提交顺序关联返回 ID，只回填仍为同一对象的 ID，不覆盖后续内容、删除或新对象；临时 key 不送入 API。不能可靠关联时进入保留两份内容的冲突处理，不能猜测 ID。再次明确保存成功后才允许再次离开。
4. 409 VERSION_CONFLICT 保留原稿和原基线，取消本次离开；可另行读取服务端版本供比较，不能用读取结果替换编辑器。沿用已验证的显式操作：用户可选择放弃本地并载入服务端，或检查差异后以最新版本重新提交。后者明确以本地完整内容作为替代稿：对照本次展示的服务端当前组／游戏 ID 集合，仍存在的 ID 保留，已不存在的 ID 仅从提交副本中去掉，作为新对象让服务器生成；本地文字、顺序和组结构不删除、不按名称猜配，也不放宽后端当前版本 ID 校验。再次 409 仍留稿重新比较，不能自动换版本循环重试。用户未选择前不自动合并、重试或放行，原 pending action 清除。
5. 422／503／连接失败保留输入并显示原因；提交结果不明标为 indeterminate，不谎报未提交、不自动重发 PATCH。可读回服务端供核对：只有版本及完整正规化内容／对象身份可确定对应本次提交时才建立新基线，否则进入冲突比较。不要只凭“版本+1”判断已保存。用户显式重试仍携带原 expected version，不能先换最新版静默覆盖。

界面要区分“保存失败”“保存结果待核对”和“版本冲突”。任何失败均不离开；一次已确认无修改的普通离开不产生内容版本或保存审计。

### 11.3 离开协调与关闭协议

应用壳唯一 `requestLeave(action)` 管理关闭窗口、切日期、切学期、返回日历和进入设置；编辑器注册保存回调，路由／父组件不得先卸载。协调器状态 idle／saving_for_leave／leaving，一次只保存一个目标动作。同一目标重复触发共用 Promise，不同目标在进行中不替换或排队；失败后恢复 idle，用户重新选择。

- clean 立即放行；dirty 等 saveCurrent 的 saved／unchanged 且再次核对当前 planId、editEpoch 与 dirty=false，才执行原动作。
- saving 时新离开等待同一保存结果；一旦有新输入、失败或冲突，留页并取消动作，不靠“请求曾经成功”放行。
- 导出不是离开动作，点击导出不调用此保存流程；原生保存正在进行时先等待其结束，再处理关闭，见 §12。
- 设置修改必须预览确认，不能借窗口关闭绕过确认自动应用。设置表单用明确的预览／应用／取消编辑状态；未确认草稿时关闭请求留在设置并提示完成确认或取消编辑。首次设置亦不得因关闭触发半初始化；原子初始化完成后才是 ready。这不改变日计划已确认的离开自动保存。

宿主接口采用 `bridge_protocol=1`：

| 方向 | 协议与状态 |
| --- | --- |
| 页面 → 宿主 | `page_ready({bridge_protocol:1})`：页面完成启动和协调器注册后握手；重复同版本幂等，版本不匹配显示错误，不能执行业务桥接 |
| 宿主 → 页面 | `request_close({close_request_id})`：在 pywebview closing 回调中**立即返回 False**，异步在 UI 回调之外通知协调器；同一在途关闭不重发多次请求。超时／销毁失败发送 `close_aborted({close_request_id,reason})`，页面仅取消匹配的关闭动作及关闭专用冻结；不取消已提交保存或忽略其成功响应 |
| 页面 → 宿主 | `complete_close({close_request_id,allow:boolean}) → {accepted:boolean,state:pending/closing/canceled/unknown}`：仅匹配当前请求有效。allow=true 仅在协调器确认保存成功或无 dirty、无原生对话框后发送；false 解除 pending 并留窗。发送 true 前锁定编辑；只有 accepted=true/state=closing 才维持关闭锁，过期或不匹配返回 accepted=false 并恢复编辑 |
| 页面 → 宿主 | `get_close_state({close_request_id}) → {state:pending/closing/canceled/unknown}`：complete_close 响应丢失时查询；pending 等待，closing 保持关闭锁，canceled/unknown 解除锁并留页。不能将查询失败解释为允许销毁 |
| 宿主销毁 | 验证当前 ID 后置一次性 allow_close 标记，再调用 destroy；重入 closing 原子核对当前请求 ID／许可仍有效后才消费一次并放行，过期或撤销均返回 False。窗口真实 closed 后才停止本机服务并释放数据库／资源 |

不在 closing 的同步 UI 回调里等待 JavaScript、数据库或网络。过时／重复 ack 不重复销毁；没有 page_ready、桥接异常或 30 秒无响应时，**仅对尚未放行最终 closing 的请求**默认不关闭、撤销许可并置 canceled，允许重新请求，迟到 true 返回 accepted=false。宿主通知页面取消；只有能确认 destroy 尚未执行，或已明确失败且窗口仍可用时，才撤销标记、置 canceled 并通知解锁。一旦最终 closing 已放行，状态保持 closing，不能仅因未收到 closed 或等待超时就声称可留窗并解锁。桥接回包丢失时按 ID 查询；无法确认终态则保留关闭专用冻结和错误提示，不能一边继续编辑一边可能销毁。30 秒只否决未放行的关闭，不否定仍在途的数据库保存；其响应仍照常更新保存状态。未初始化且页面干净可按协议正常关闭。不能以 beforeunload／onBeforeUnmount 等待异步保存，也不提供“超时自动强关”捷径。系统强制终止、断电或进程崩溃不承诺自动保存或草稿恢复；本轮不新增该能力。

### 11.4 D4 观察接入的页面写屏障扩展（2026-10-27）

沿用 `bridge_protocol=1`、本节关闭代次与更新握手。`get_bootstrap()` 为当前页面启动签发不透明 `page_ticket`；新页面在 `page_ready` 中回传，后续 `set_page_busy({page_ticket,seq,busy})` 只可改变该已接受页面的写屏障。`seq` 为正整数；旧票据、无效序号及迟到通知不回退当前状态，同页重复 ready 不清忙。宿主票据校验及状态更新在线程锁下原子完成；票据／legacy 资格在更新就绪确认等副作用前核实，有等待则复核。旧 D1 无票据首次握手可兼容；一旦已接受票据页面，后续新 bootstrap 待绑定期间也不重新放行无票据旧 ready。票据不入日志、遥测或 URL，不增加公开桥方法以外的任意操作能力。

该屏障覆盖观察准备性保存、创建／导入／采用／恢复／AI 提交等真实在途写与待核实提交。AI 提交确认持久化后，准备屏障解除；持续 AI 执行通过原全局任务快照和“继续等待／停止等待”关闭选择协调。准备意图不得跨只读轮询而阻止该选择；未采用观察候选可保留离开。最后一条 busy 状态失败或回包丢失须独立重试，新状态接管旧 retry 责任；卸载与旧响应不重启重试。票据写屏障叠加原生保存忙状态，不替代 `complete_close`／最终冻结或失败留页规则。

本扩展仅说明当前切片的页面／宿主参数与时序，工程证据见[观察页核查](../bootstrap/desktop-game-observation-pages-review.md)；不表示真实更新安装、冻结发行或完整教师体验已通过。

## 12. D1B Word 范围、确认与原生保存

### 12.1 范围与本地导出接口

复用固定日计划模板、内容映射和 DOCX 生成器，增加本地读取适配；不挂载旧 exports 路由的账号／管理员／MySQL 查询依赖。只提供日计划，周计划与材料不进入 D1B。

页面提供单日、按周、按月、自选范围，最终统一为闭区间 from/to：单日同一天；周为所选日期实际周一至周日；月为自然月首末日；自选必须两端完整且 from≤to。范围不会被当前学期截断或扩大；后端按当前班级、实际 plan_date 及有效记录选择，不过滤当前上课资格、当前学期或是否有拆分基准。计划日期升序，每份新页开始，份内自然分页。按**实际选中份数**最多 31 份，不把 31 天作为自选日期跨度上限。

`POST /api/exports/daily-plans` 请求 `{from,to,ack_missing:false,expected_context:null}`；客户端不得传 class_id／term_id／creator。200 返回 DOCX 二进制、正确 Content-Type、Content-Disposition 建议中文文件名及 `X-Export-Warnings`。404 `EXPORT_NOT_FOUND` 无匹配；422 `EXPORT_LIMIT_EXCEEDED` 超 31 份／`VALIDATION_ERROR` 范围非法；503 `LOCAL_STORAGE_ERROR` 读取失败，生成器失败为 500 `EXPORT_GENERATION_FAILED`。响应不得含 traceback、SQL、路径或 token。

只读取数据库已保存版本。dirty 时提示“将导出已保存的版本，当前未保存输入不会写入文件”，继续允许导出；不自动保存、不强制先保存、不清除 dirty。无 split_baseline 的手工计划按最终内容导出、不标红，并显示“无原始拆分基准，无法比较”提示，不伪造基准。空栏目保留，通过缺项确认允许留空。

### 12.2 确认事实与事务边界

首次有缺项返回 409 `EXPORT_ACK_REQUIRED`，结构为 `{error:{code,message,details:{reason:"missing",facts,expected_context}}}`。facts 沿用既有日计划缺项规则，包含计划／日期／栏目定位及完整缺项集合。expected_context 明确包含：

- 服务器确定的 class_id、from、to；
- 按日期及 ID 排序的完整 `{plan_id,content_id,content_version}` 清单及数量；
- 全部缺项 facts 的稳定规范 JSON SHA256 和数量；不能只绑定计数或第一项。

用户确认后以相同范围、`ack_missing:true` 和完整 expected_context 重试。每次请求都在**显式读事务的同一快照**中选记录、验证持久内容、读取头部快照及内容、计算 facts／context，并物化无 ORM 懒加载的 DTO。确认值必须完全相符；选集、版本或完整缺项发生变化，即使缺项已清空，仍 409 EXPORT_ACK_REQUIRED，reason=context_changed，返回新事实供重新确认。ack_missing=true 但没有完整 context 返回 422，不可当作无缺项新请求绕过。

确认只覆盖本次读快照。读事务结束后才做映射、比较和 DOCX 生成；后续另一个保存成功不会把已物化 DTO 换成新内容，也不要求生成结束再重新读取。首次无缺项可直接生成；这不等于允许复用过期的显式确认。

生成审计如保留，使用生成结束后的独立短写事务，记录实际 DTO 中的计划／版本及生成结果，不修改计划或确认状态；审计失败显示独立警告，不把已生成字节写成“已经落盘”。不得将旧读事务升级为写事务，也不能把数据库事务延续到原生对话框。

### 12.3 原生交付和过时响应

前端获取有效二进制后，经受限宿主接口 `save_docx({request_id:UUID,filename,payload_base64})` 交付；filename 仅建议 basename，宿主净化名称和 `.docx` 后缀、严格校验 base64、非空 DOCX 与解码后不超过 30 MiB。超过当前桥接上限返回 `PAYLOAD_TOO_LARGE`，不打开对话框或声称保存成功；如真实样本达到上限，先报告再另行评估传输方案。本轮不把 D0 的 autosave_target 夹具口暴露为正式任意路径写入能力，也不允许 URL 下载代替已生成内容。

宿主使用原生另存为；同一目录临时文件写完、flush/fsync，并核对 DOCX／字节后执行原子替换，以替换成功为提交点。提交点前失败清理本次临时文件、保留原目标；提交后检查如果不能确定结果，返回 unknown，不能声称旧目标一定未变。实际替换及结果核验成功才 saved。只接受当前受信任页面和已完成握手的调用，一次一个对话框。同 request_id 和相同 filename＋载荷 SHA256 指纹重复调用共用在途操作或返回缓存结果，不再开第二个窗口；同 key 异载荷返回 `SAVE_REQUEST_CONFLICT`。新增 `get_save_result({request_id}) → {status:pending/saved/canceled/failed/unknown,...}`，缓存当前宿主会话内全部已用 ID 的指纹和结果元信息，不缓存已完成的正文；未知 ID 查询绝不发起写入。宿主重启或 unknown 不代表未写，不自动重新调用 save_docx；用户核对实际文件后才能明确发起新保存。用户在取消／失败后明确重试使用新 request_id。

| 结果 | 页面状态与允许动作 |
| --- | --- |
| API 读取／生成失败 | `generation_failed`，显示原因，无原生对话框，无“已保存” |
| `save_docx → {status:"canceled"}` | `canceled`，提示未保存，保留编辑内容及导出选择 |
| `→ {status:"failed",code,message}` | `save_failed`，含占用／权限／I/O 等脱敏原因，允许解除占用后重新另存；不能报成功 |
| `→ {status:"saved",filename,bytes}` | `saved`，只有实际写入及核验成功才显示“文件已保存”；本地计划内容版本不改变 |
| 桥接响应丢失／宿主无响应 | `save_result_unknown`，不报已保存，先按相同 request_id 查询或重取缓存结果，不自动再次写文件 |

页面以 exportSeq 绑定范围、确认弹窗及请求；范围改变、取消确认、离开页面使旧请求失效。即使取消 HTTP 没生效，迟到响应也不能打开原生对话框或覆盖新状态。原生对话框已打开后，范围控件／再次导出／离开动作暂不可执行，关闭请求等待对话框结果，再走 §11；不得在 bridge 返回前清 busy。等待结果超时不自动解锁并允许第二次写入，应保留操作 ID 供核对。

字节／base64 仅在本次交付期间驻留内存，结果确定或明确取消后释放；无长期导出仓库，不用 localStorage 保存正文。失败后“重试导出”重新读取数据库并重新校验缺项确认；如果选择重试同一已生成文件的原生保存，必须明确它仍是原保存版本，不能把缓存字节称作当前数据库版本。

### 12.4 日计划 Word 格式（2026-10-17 用户确认，R18）

教师体验中用户明确要求下列三项调整，适用于单日及按周／月／自选范围导出的**每份日计划块**。本条覆盖旧日计划格式中相冲突的模板继承及“署名显示年级”约定；不追溯改写旧I5验收，不扩展周计划模块。

1. **第一行整体居中。** 文本仍由该计划创建快照 `school_name` 加“一日活动计划”组成，以段落居中实现，不以空格／制表符模拟；空园所只显示“一日活动计划”，保持居中。长园所自然换行后仍居中，不新增学期、年份或占位园所。
2. **署名为“班级 教师名称”。** 使用该计划快照 `class_name` 和 `creator_display_name`，以一个空格分隔，不额外拼接 `grade`（如“体验中四班 体验教师”，不加“中班”前缀）。班级名称本身按原文输出，不能误删名称中的“小班／中班／大班”文字。年级仍保留在数据库／快照／映射及其他现有业务中；既有计划不得回填当前配置。
3. **表格内全部文字不加粗。** 包括周次、日期、固定栏目、字段标签、游戏名称、目标、准备、重点／难点、活动过程、指导／支持、反思，以及合并导出每份表格中的文字。处理直接格式与样式继承，不能仅删除显式bold后又从样式继承加粗；活动过程的既有差异标红保留，标红文字也不加粗。

除三项已确认调整外，保持既有两列表格、栏目、字体／字号、颜色与标红规则、单份内自然分页、每份新页开始、内容与保存／范围／缺项确认语义。标题及署名的原有其他字体属性不因“表格取消加粗”被顺带改动。优先在日计划生成范围定点处理；共享写入器的周计划调用不得受影响。若选择变更受控日模板资产，须同时更新资产哈希、说明及包内资源证据；不得关闭模板校验或覆盖用户原文件。

验收需要输出级结构检查和新包实际导出：有／无园所、长园所、不同班级／教师快照的多份日计划、长活动过程、空栏目和标红run均覆盖；每块标题显式居中，署名没有额外年级，全部表格文字有效bold=false。保留周计划现有输出回归。新样本与生成链已变化，旧同字节Word样本不能替代新样本在Windows Word中的逐页检查，需用户再次确认格式。现有年级显示测试中的日计划断言按本条更新，不能删除周计划断言或放宽内容完整性检查。

## 13. OpenCode 工作项、验证与准入

### 13.1 依赖顺序与文件边界

以下是准备好的实施拆分，须在后续明确编码／环境落实任务授权后执行。本轮不向其他聊天派发实现任务，不替 OpenCode 写代码。

| 项 | 模块／拟改文件 | 前置与交付接口 | 必需验证 |
| --- | --- | --- | --- |
| B0 统一环境 | backend／desktop 版本声明，D1 独立声明与锁、后续 D1 构建脚本；具体文件及命令见技术核查 §8 | 已定 3.14.7 标准 Windows x64；保留 D0 环境／包；业务锁固定后解析桌面集合 | 解释器／GIL／位数／依赖导入、完整 D1A、相关回归；环境实际可运行才进入桌面集成 |
| B1 配置与多学期核心 | `backend/app/local/{models,schemas,profile_service,calendar_read,daily_plan_service,api}.py`，新增配置服务／预览与回执；新 `migrations_local/versions/*`；`backend/tests/local/` | §9 全部产品选择已确认；§10 请求／事务 | D1A 数据升级不损坏，配置原子性／重试／冲突、日历完整修订、多学期与历史访问、预览并发失效 |
| B2 真实页面 | `frontend/d1.html`、`frontend/vite.d1.config.ts`、`frontend/src/d1/`；经审查提取真实表单和纯内容映射，必要 `package.json` 脚本 | B1 的 context／配置 API；D1A 创建／保存 API | 首次设置、异常重试、日历／旧计划入口、全部真实栏目、空内容／长内容、配置预览与返回后的状态 |
| B3 保存与宿主 | D1 leave/save 协调器、D1 API/type；`desktop/d1_main.py`、`d1_host_api.py`、路径／静态入口适配及相应测试 | B2；§11 协议；基于 D0 会话／进程生命周期进行限定适配 | 自动保存后离开、失败留页、409、重复动作、IME／晚到输入、关闭 pending/过期 ack、服务退出顺序；真实 WebView2 |
| B4 Word 闭环 | 新本地 export 读取／路由适配、D1 导出 UI、受限宿主保存；复用 `word_export_mapping.py`／`word_export_docx.py` | B1 日期／历史规则、B2/B3；§12 | 快照一致性／确认变化／31份边界、原生取消／占用失败／重试、文件全页；不改旧生成器或 MySQL 链 |
| B5 同解释器目录包 | `desktop/build_d1.py` 及 D1 spec/资源清单，独立输出路径；同一 D1 结果记录 | B0–B4 检查通过；不得覆写 D0 spec／旧包 | 目录包复制仓外、临时合成数据三进程启动／保存／重开、原生流程和实际导出的 Word 全页查看 |

B1/B2 的设计准备与 B0 可独立审阅；Windows 集成和打包验证必须等待 B0 的真实通过结果。模块内文件可合理拆分，但不得跨越已确认模块边界，或顺带重构旧 auth／AI／周投影。若复用生成器必须改动，先提交具体原因与影响给 Codex 核查，不以本表授权重写。

### 13.2 D1B 新增验证矩阵

§8 的完整 D1A 验证继续保留，不能用下表替代或禁用旧失败用例。D1B 必要新测试由 OpenCode 编写；已有测试因新增明确接口字段／多学期语义需适配时，说明原因并保留原原子性、隔离和冲突断言。自动测试、GUI 实测、用户产品验收分栏记录。

| 场景 | 可观察通过条件 |
| --- | --- |
| 配置基础维护 | 姓名／园所后补／清空、班级改名／升班 ID 不变；旧计划四项表头不变且内容版本／日志不增加。提前创建未来计划保留旧资料；回补过去日期新计划用创建时当前资料 |
| 学期与历史入口 | 新增不相交／端点冲突拒绝；改起始日预览周次差异但旧周次不改；缩小范围后 term 列表仍列出旧计划；新学期覆盖该日仍打开原计划；非上课／unknown／学期外已有内容可保存导出，新建被拒绝 |
| 日历例外 | teaching/non_teaching/撤销、unknown 手工配置；范围缩后再扩时重新纳入日期按库建立无例外基础，旧例外只保留在历史修订、不静默恢复；只建立新修订，旧修订不变；provider 故障与 unknown 分开，无交集日期的库升级静默重算 |
| 预览和应用竞态 | 两配置同时提交、预览后新建／保存相关计划、同影响数量但不同版本、过期／篡改／重启令牌均不误用确认；锁内再查；同 request_id 只提交一次，无变化回执跨后续配置提交仍不执行旧操作，flush/COMMIT 故障全回滚；真实 API handler 保留 error.details |
| 首次设置与上下文 | 同 key 重试、重复点击与维护后重试不重建／回滚资料；多学期 context 可 ready；今天无学期不跳首次设置；不显示管理员／账号流程 |
| 无修改与正常离开 | 初次加载即 clean；无修改手动／离开不新增版本；关闭、切日期、切学期、返日历、进设置各自先保存成功再动作；重启可读到新版本 |
| 失败／冲突／新输入 | 真实写锁超时、存储故障、409 均留页；服务端删除过组／游戏后的显式重提可获得新 ID 且文字不丢；响应丢失不自动重复保存；重复点击不多提交；保存中 IME／新增组／晚到输入不丢失、不被响应覆盖、不误离开 |
| 关闭握手 | 关闭先被取消；保存完成且clean才销毁；页面未就绪、拒绝、超时、重复／过时 ack 不关窗；30 秒超时后保存成功仍留页并解除关闭锁，destroy 异常撤销许可；回包丢失可查状态；closed 前不先停止 API；真实关闭后可再次启动 |
| 导出范围与确认 | day/week/month/custom、跨学期、学期外旧计划、0/1/31/32份、日期排序新页；完整缺项确认、版本变化、选集变化、缺项变少至空仍重确认；dirty 导出不保存、不改变版本 |
| 导出快照与并发 | 用同步屏障证明读事务完整物化 DTO、生成时另一保存可提交；生成内容仍对应指定旧快照；不带着读事务写审计／打开对话框 |
| 原生文件交付 | 中文文件名，实际非空 DOCX；生成失败／取消／占用失败／解除后重试结果正确，失败保留原文件；过时范围响应不开框；同 request_id 无第二次写入，30MiB边界和非法载荷拒绝 |
| Windows 与 Word | 真实 WebView2 的桥接、关闭、原生保存全部实测；同解释器包仓外运行且 D0 未受影响；通过产品导出空／代表性／长内容及多份文件，在 Windows Word 页面视图／打印预览检查每一页，记录版本和字体 |

后续结果继续写 `docs/bootstrap/desktop-d1-result.md`，Codex 复审继续写 `desktop-d1-review.md`，环境证据写技术核查／结果对应段落；每项记录命令／版本、exit code、计数／skip、临时数据路径和证据。未执行明确写未执行；失败保留首次和后续证据，不以偶然重跑成功抹去失败。

### 13.3 本轮准入结论

本节保留2026-10-14实施前的准入历史；当前工程结论见本文顶部及审阅§17，下述“尚未实施／未实测”为当时状态。

**产品范围与独立工程设计均已收敛，没有未答产品问题，具备交给 OpenCode 的规格条件。** 实施所需统一运行时步骤、拟改文件及门槛见[技术核查 §8](../bootstrap/desktop-d1-technical-review.md#8-d1-统一运行时准备方案2026-10-14)。该结论是“可形成后续实施授权”，不是本轮已经授权执行安装／编码／打包，也不是运行时已经通过。

D1A 既有 87 项本地测试和 108 项回归通过沿用原证据，本轮没有重跑。D1B 尚未实施，3.14 桌面组合和新包未实测；D1 产品、干净机器、Win10、WPS、其他 DPI 与用户体验仍按各阶段保留未验。3.12 原生异常未解及 D0 原包证据不改写。

### 13.4 本轮人工验证范围与收口（2026-10-17）

用户明确微软拼音验证正常、不需要再次复验，且不要求验证全部输入法。微软拼音按该人工反馈通过，撤销候选词细分动作和为此补录缩放的待办；不以其他输入法未逐一验证阻塞本轮收口。不丢字、正确保存及关闭保护的既有行为要求不变，后续若有具体输入故障，再针对实际问题核查。

当前Windows 11＋Microsoft Word下，读回与保存、T6-A草稿保护／取消还原、T6-B应用／新旧快照与单日导出、T7人工保存路径及R18页面验证均已取得本轮反馈与核对证据，详见[结果§20.8](../bootstrap/desktop-d1-result.md#208-t6-b核对与本轮教师体验收口2026-10-17)和[复审§20.9](../bootstrap/desktop-d1-review.md#209-t6-b复核与本轮人工验证收口2026-10-17)。本轮教师体验收口，可进入D2规格准备；不要求重复已确认的人工操作，不泛化为所有环境或完整产品／发行通过。
