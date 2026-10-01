# 给 OpenCode 的 I5 片 4 完整执行提示词

状态：2026-10-01 修订版，替代 2026-09-29 执行提示词。保留既有验收范围、授权与 W1–W6 完成条件，补充实测环境、版本采集、分层执行与人工交接。可将下文完整交给 WSL2 Ubuntu 内的 OpenCode。

请从实际仓库根目录（当前为 `/home/ywyz/code/kindergarten-manager-next`）执行 I5 片 4“Windows／WSL2／Microsoft Word 产品验收”。

先读取并遵守：

- `AGENTS.md`
- `ARCHITECTURE.md`（只读，不修改）
- `docs/specs/word-export-implementation.md`，重点 §3、§5、§7–§12
- `docs/specs/word-template-validation.md`
- `docs/specs/word-template-prototype-results.md`（只作历史证据，不冒充当前产品验收）
- `docs/modules/word-export.md`
- `docs/modules/audit-log.md`
- `backend/app/services/export_read_service.py`
- `backend/app/services/word_export_mapping.py`
- `backend/app/services/word_export_docx.py`
- `backend/app/routers/exports.py`、`class_scope.py`
- `backend/app/schemas.py`、`main.py`、`deps.py`
- `backend/tests/integration/i5_guard.py`
- `backend/tests/integration/i5_support.py`
- `backend/tests/integration/test_i5_export_api.py`
- `frontend/src/api.ts`、`types.ts`、`word-export.ts`
- `frontend/src/views/DailyPlanView.vue`
- `frontend/src/views/WeeklyPlanView.vue`
- `frontend/src/views/WeeklyPlanListView.vue`
- 管理员复用入口 `AdminDailyPlansView.vue`、`AdminWeeklyPlansView.vue`

开始先核对实际 HEAD、最近提交、`origin/main` 和工作区。当前协调审阅基线为 `main` / `3ad97dd`；本地 `origin/main` 指向同一提交（未刷新远端）。此前代码审阅基线为：

- `224bdfd`：I5 片 3 API 与下载闭环；
- `0c5c3a1`：片 3 审阅后四项前端窄修复，且当时已推送到 `origin/main`。

如已有后续提交，只核对与本任务相关的差异。旧切片提示词与临时审核材料已在当前基线清理；需要追溯时查看上述提交及 Git 历史，不恢复为当前指令。保留用户已有 `.codex/config.toml` 及其他未提交修改，不覆盖、不回退、不暂存、不顺手整理。不要启用或安装新的 MCP／Skill，不修改 Windows、WSL、Office、浏览器、Docker 或全局 Codex 配置。

## 当前事实与执行分层

2026-10-01 只读实测：WSL2 Ubuntu 26.04.1，内核 `6.18.33.2-microsoft-standard-WSL2`；Windows `EditionID=Professional`，25H2，build `26200.9457`；Office Click-to-Run `OfficePackageVersion=16.0.20326.20158`，`OfficeProductReleaseIds=O365HomePremRetail`，平台 x64；Word 文件版本同为 `16.0.20326.20158`。这是当日安装信息，不证明 Word 可交互使用、浏览器下载或产品版式通过。项目 `.venv`／`node_modules` 当日缺失。执行时重新查询并记录实际值。

本片分三阶段：

1. **版本与环境采集**：WSL/Linux 只读信息与 Windows PowerShell 只读查询；区分命令可达、软件安装信息、GUI 实际可用性。
2. **独立自动检查与交接准备**：即使尚无 GUI 能力，也可恢复锁定项目依赖、运行纯单元测试和前端 typecheck/build、核对模板哈希，并准备人工案例表。已有工具缺失时列出缺项，不安装系统工具。隔离 MySQL 集成可按本片既有授权执行并用后清理；不把集成测试当真实 UI 下载。
3. **Windows 浏览器与 Word 验收**：由已有且可验证的桌面工具执行，或由用户人工执行并交回逐项证据。OpenCode 负责夹具、服务、追溯和整合；仅 OpenCode 写业务修复。人工／桌面协调者不并行修改业务代码。

没有 GUI 能力时不得让用户先安装 Windows 版 OpenCode，也不得自行安装 Computer Use、浏览器扩展或 MCP。完成独立检查后提交具体交接清单，状态为“自动检查完成／待人工验收”，暂停 GUI 阶段。不能宣布 I5／片 4 完成。

## 执行门槛与授权边界

独立自动检查先核对其必要工具；进入 GUI 验收前，只读确认以下条件：

1. 主机实际为 Windows 11 Pro；
2. 仓库和开发命令运行于 WSL2 Ubuntu，而不是 WSL1 或其他 Linux 发行版；
3. Windows 侧存在可交互使用的桌面版 Microsoft Word，能够打开本轮真实下载的 `.docx` 并查看全部页面／打印预览；
4. Windows 浏览器能访问 WSL2 内本片临时启动的产品页面并完成真实下载（服务启动后检查）。
5. 明确实际操作者：OpenCode 已有 GUI 工具、已具备权限的桌面协调者，或用户人工验收；不能仅凭“安装桌面应用”认定具备 GUI 工具。

目标 OS／Word 不满足时记录阻塞；OpenCode 缺少界面能力时完成可独立执行的自动检查与交接，再暂停 GUI 阶段。人工路径须有用户明确反馈的实际浏览器与 Word 操作结果，记录其为人工证据；用户尚未反馈时记“待人工验收”。不得安装软件、切回旧环境验收、把 Word 项写成通过，亦不得仅完成 WSL 自动检查后宣布片 4 完成。

按上述分层与必要门槛，本片既有授权包括：

1. 在 WSL2 内启动一个全新、一次性、仅监听回环地址的 MySQL 8.4／InnoDB 容器和白名单测试库，执行现有 Alembic 迁移并播种专用验收数据。
2. 以 `APP_DISABLE_DOTENV=1` 和显式测试 DSN 启动临时 FastAPI 与 Vite；使用 Windows 浏览器完成真实 UI 操作和下载。
3. 使用已安装的 Windows 桌面版 Microsoft Word 打开本轮产品 DOCX，检查修复／转换提示、页面视图或打印预览、全部页面、分页、表格、字体、颜色和内容。浏览器下载产生的安全提示／Protected View 与损坏修复提示必须分开记录；必要时只对本片可信测试副本启用编辑，不保存修改。
4. 在仓库外创建边界明确的 WSL 临时目录和 Windows 本片专用临时目录；完成后只精确删除本片路径。
5. 发现可复现的片 1–3 缺陷时，只做最小定向修复并补相应测试；若涉及未确认产品行为、架构边界、模板资产或 §11.9，停止该分支并报告。
6. 新增片 4 结果记录，最小更新 I5 规格、readiness 和 README；完成后按现有流程 commit 并 push 当前分支。

本片不授权：

- 部署、SSH、生产数据库、用户真实数据、真实 AI 或外部服务调用；
- 新迁移、新表／列、异步任务、落盘导出、对象存储或下载链接；
- 安装系统软件、Office 组件、浏览器扩展、新 npm／Python 依赖或新测试框架；
- 修改模板资产、模板哈希、模块 Contract、ADR 或 `ARCHITECTURE.md` 来规避失败；
- Excel、PowerPoint、Outlook、WPS、实体打印或生产容量验收；
- 强制执行 LibreOffice；如环境恰好已有，可作为补充证据，但不能替代 Word 门槛；
- 自行决定 §11.9，或人工制造当前 `plans_started_at` 门槛下不可达的日历／学期变更语义；
- 把历史原型、PDF、纯 OOXML 单测或片 3 集成结果冒充 Windows 浏览器／Word 产品验收。

## Windows 与 Office 只读采集方法

优先在 WSL 调用 `powershell.exe -NoProfile -NonInteractive -Command` 与 `wsl.exe --version`，Linux 命令采集 Ubuntu／内核及开发工具。只读查询范围：

- `Get-CimInstance Win32_OperatingSystem`：仅取 Caption、Version、BuildNumber。
- `HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion`：仅取 EditionID、DisplayVersion、CurrentBuild／UBR，避免设备标识。
- Office Click-to-Run：`HKLM:\SOFTWARE\Microsoft\Office\ClickToRun\Inventory\Office\16.0` 的 `OfficePackageVersion`、`OfficeProductReleaseIds`；不把 Configuration 的 `VersionToReport` 当安装版本权威。
- Configuration 仅取 Platform、UpdateChannel、CDNBaseUrl，作为平台和渠道配置证据。
- 从 App Paths 找 WINWORD.EXE，只读其 FileVersion／ProductVersion；不启动 COM、不执行宏。
- GUI 阶段再记录 Word“关于 Word”显示的产品、版本、build、位数／渠道，核对安装信息；缺失字段单列，不猜测版本营销名称。

仅查询命名属性，不输出注册表整项、Microsoft 账户、许可证、产品密钥或设备唯一标识。处理 PowerShell 编码后再记录中文名称；EditionID 可用于交叉核对。

采集依据：[WSL 互操作](https://learn.microsoft.com/en-us/windows/wsl/filesystems)、[Office 安装版本检测](https://learn.microsoft.com/en-us/microsoft-365-apps/updates/microsoft-guidance-on-office-build-install)。

若 `powershell.exe` 出现 WSL vsock／互操作错误，区分 Agent 沙箱阻断与系统互操作不可用。按当前执行环境的权限流程请求该只读命令必要的权限；不关闭沙箱、不修改 WSL／注册表。不能执行时提供命名属性的 PowerShell 查询给用户手动运行，缺少反馈记待确认。

## 环境预检与证据边界

执行时重新采集并记录，不从提示词推断版本：

- Windows：edition、version、OS build；
- WSL：`wsl --version` 的 WSL 版本，以及 Ubuntu 发行版、版本和内核；
- Windows 浏览器：名称、版本；
- Microsoft Word：产品名、版本、build、32／64 位、更新渠道；
- WSL 开发工具：Python、uv、Node、npm、Docker；
- MySQL 镜像及运行实例版本；
- Word 实际使用字体及可观察到的字体替代。

可通过 Windows 系统信息／PowerShell 和 Word“文件 → 帐户 → 关于 Word”等只读入口采集；不得读取 Office 凭据、账户令牌或修改注册表。报告不写 Microsoft 账户、许可证标识或设备唯一标识。

2026-09-20 的 Ubuntu／LibreOfficeDev 结果仅是模板隔离原型历史证据。2026-09-29 迁移前的 Omarchy／LibreOffice 环境也不是当前目标。两者均不得填入本轮结果矩阵。

先检查端口、Docker 容器和相关进程，不能停止或删除不属于本片的资源。若 API `8000` 或 Vite `5173` 被其他进程占用，不得杀进程或偷偷改产品配置；停止并报告。不得修改 Windows 防火墙、WSL 网络模式或系统代理来强行通过；Windows 到 WSL 的 localhost 转发不可用时记为受阻。

## 隔离环境

建议使用下列独立标识；如实际调整，必须保持同等隔离并写入报告：

- 容器：`kg-next-i5-slice4-mysql-YYYYMMDD`（以实际日期替换）
- volume：`kg-next-i5-slice4-data-YYYYMMDD`（以实际日期替换）
- 映射：`127.0.0.1:13386 -> 3306`
- 数据库：`kindergarten_test_i5_fresh`
- MySQL：`mysql:8.4`，运行版本须为 8.4.x，默认引擎须为 InnoDB
- API：WSL2 `127.0.0.1:8000`
- Vite：WSL2 `127.0.0.1:5173`
- 下载目录：Windows 侧新建的本片专用临时目录，不复用或清空通用 Downloads
- WSL 临时目录：使用 `mktemp -d` 并记录精确路径

数据库名和端口沿用 I5 guard 的白名单；不得放宽 guard、加入通配库名或连接 `.env`。凭据只放当前进程环境，不写入仓库、结果文档、截图或最终报告。

启动后断言并记录：

- 实际 host、port、database、`SELECT VERSION()`、`default_storage_engine`；
- `alembic heads`、迁移前后 `alembic current`，最终为仓库实际唯一 head；不得把提示词中的历史 head 当作事实；
- API `/health` 返回 200；
- Windows 浏览器可打开 Vite，`/api` 代理实际走本片临时 API；
- Origin、cookie 与 `Cache-Control: no-store` 由真实浏览器请求验证。

使用现有模型、服务和 I5 support builder 准备验收世界；允许写仓库外临时播种脚本，禁止提交第二套业务算法或明文凭据。浏览器账号须使用当前密码规则生成合法 hash，不能把仅供直接 session 的 `password_hash="x"` 当作登录账号。播种前再次断言目标 DSN。

## 产品生成文件要求

W1–W6 DOCX 必须来自当前 HEAD 的真实导出路由：

- `POST /api/exports/daily-plans`
- `POST /api/exports/weekly-plans`

核心文件须经 Windows 真实浏览器页面点击下载到本片目录；同一临时 API 的认证 HTTP 请求仅可补充构造案例，不能替代对应浏览器闭环，也不得直接调用 `generate_export_docx()` 冒充产品结果。交给 Word 的文件必须能追溯到本轮 HTTP 响应。

每个输出记录案例、操作者／角色、请求模式、范围或确认版本、浏览器下载文件名、字节数、SHA-256、MIME、警示头、审计和来源版本。不得记录 cookie、密码、完整认证头、DSN 或完整计划正文。

生成前后核对受控模板 SHA-256；Word 打开时不保存更改，必要时再次核对下载文件哈希：

- `daily_plan.docx`：`99008f92ae42cc87da7e42e84009ffcd8bbefdf43602f09a59ae4027e5ddc9bd`
- `weekly_plan.docx`：`24ccaa9e557522c40a653643381e31f319ea6ae5e9f3e30e9dfa41da21986aed`

## W1–W6 产品级复跑

严格以 `docs/specs/word-template-validation.md` 为准。每个主例和子例分别记“通过／失败／受阻／未执行”，不能只写“W1–W6 通过”。

### W1 普通与全空日计划

- 普通单日：栏目、表头、主题、一项集体 + 一项自选游戏及目标／指导准确；无拆分基准时 Word 内过程不标红，浏览器显示 `no_split_baseline`，提示不写入正文。
- 全空内容：首次 409 展示逐日期／逐栏目 facts；明确确认后下载；结构保留、内容为空，不补样例或 AI 文本。
- 同班非创建者教师可导出，但页面仍只读且无编辑／确认能力。

### W2 长过程分页与标红

- 用既定 baseline／final 夹具覆盖新增、替换、纯删除、纯移动、仅格式变化，并使过程确实跨页。
- 在 Word 页面视图或打印预览逐页确认顺序、分页、无裁切／重叠／丢行；新增及替换文字红色，未改文字保持原色，删除不输出、不出现删除线，移动与仅格式变化不标红。
- 记录实际红字的最小脱敏描述；不得仅凭 OOXML 属性或 PDF 宣布视觉通过。

### W3 多日日计划合并

- 范围内三份、范围外两份；输入乱序时仍只含范围内三份并按日期升序，每份恰一次。
- 每份从新页开始，长内容自然分页，无分隔操作导致的额外空白页。
- 至少两份同时生成单份文件，在 Word 中逐页比较单份与合并对应内容；页数变化须解释。

### W4 调休、假期及特殊周

- 固定日历覆盖周日上课、周四／周五停课、某教学日无日计划；缺计划不能伪装成假期，周日仍属同周，表头边界正确。
- 覆盖五列、教学周末增列后的六列、七列及零教学日周单份；日期排序，不截断、不越界。
- 只验证产品消费已持久化有效日历；不得声称法定日历库覆盖、自动调休判断或 §11.9 已验证。

### W5 跨月、整周选择、去重与无匹配

- 跨两周时按周起始日排序，每周完整一次，同周命中多天不重复，不裁切范围外的同周栏目。
- 单日命中导出整份周计划。
- 仅命中非教学日／无已确认计划时显示 `EXPORT_NO_MATCH`，不得下载空文件或扩大范围。
- 多周合并每份从新页开始，无额外空白计划块；在 Word 中确认单份与合并内容一致。

### W6 已确认版本、未确认与警示

- 当前确认 V1 与后续 draft 分离；当前或显式历史确认版本逐字段等于快照，不混入草稿／候选／实时来源。
- 响应含 `confirmed_not_latest` 时页面展示既定提示，并按夹具记录原因。
- 未确认计划不得伪装为草稿下载；单份返回 `CONFIRMATION_NOT_FOUND`，范围排除未确认项。
- 完整版本保持两项集体 + 一项自选；不完整版本不得复制来源凑数；各栏目不串栏。
- “模拟 AI 材料”只验证已确认文本映射与版式，不声称 AI 能力通过。

## Windows 浏览器下载闭环

使用 Windows 真实浏览器，至少覆盖：

1. 教师本人班级、同班非创建者只读教师、跨班教师、待分配教师、管理员显式班级上下文的入口和服务端权限；不能把按钮隐藏当权限证明。
2. 日计划单日／所在周／所在月／自选范围；当前日期无计划时不扩大范围。
3. 首次缺项 409 → facts → 明确确认 → 下载；第二会话在两请求间保存造成 `context_changed` 后，旧确认失效并展示最新 facts。
4. `context_changed` 且最新 facts 归零时仍要求再次确认，勾选后才原样回传新 `expected_context`。
5. `no_split_baseline` 与 `confirmed_not_latest` 来自本次响应 header，不从页面状态预判。
6. 周计划当前确认、历史行和确认全文弹窗的显式版本下载；未确认计划无草稿下载。
7. `EXPORT_NO_MATCH`、`EXPORT_RANGE_TOO_LARGE`、`CONFIRMATION_NOT_FOUND` 的中文提示和失败不下载；UI 至少核对一个超限分支。
8. MIME、ASCII fallback／RFC 5987 中文文件名、危险班名清理、`.docx` 后缀、ZIP 完整性；页面、控制台、localStorage 不出现 bytes、cookie、认证头或完整计划日志。
9. 快速重复点击只触发一次有效下载和一条成功审计。
10. 三类导出弹窗分别制造可控延迟后关闭／切换上下文；旧响应不得下载、toast 或覆盖新状态。可用现有浏览器调试能力，不加入生产延时。
11. object URL 不长期留存；重开对话框不复用旧 error、facts、expected context 或 warnings。

UI 无法直接发起的越权分支可在同一真实浏览器会话中构造请求，检查 403／404、无文件、无成功审计。逐例记录角色、入口、状态码、是否下载、文件名、提示和审计变化。截图只保留不含凭据的必要证据，不向 Git 加入下载文件、浏览器 profile、cookie 或大批截图。

## Windows Microsoft Word 检查

所有 W1–W6 产品输出均须由 Windows 桌面版 Microsoft Word 实际打开。逐文件记录：

- 是否出现文件损坏、修复、恢复、转换或兼容性警告；Protected View 单独记录，不能误报为损坏，也不能停留在其中代替页面检查；
- 页面视图或打印预览中的实际页数和全部页面可读性；
- 缺字、字体替代、截断、遮挡、表格越界、异常大空白、额外空白页、分页与计划边界；
- W2 红字；W3／W5 单份与合并；W4 五／六／七列和假期；W6 栏目映射；
- 检查后关闭且不保存，下载文件与仓库模板不得被 Word 改写。

可用 Word 自带 PDF 导出或打印预览截图保留最小辅助证据，但不是强制项，也不能取代逐页观察。不得通过 Office COM 宏、信任中心放宽、全局 Normal 模板修改或安装字体规避问题。页数与历史 LibreOffice 原型不同不自动判失败，只要内容完整且符合标准；不得为追求固定页数缩字、删栏目或改模板。

若 OpenCode 无法控制或观察 Word，交由明确的人工／已有桌面协调者逐页验收，结果注明操作者与证据来源，不冒充 OpenCode 自动观察。没有逐页反馈或证据不足的项记“待人工验收／受阻”，片 4 不得标记完成。LibreOffice、WPS 和实体打印均不是替代方案。

## 人工与桌面协调者交接

GUI 能力缺失时先完成可独立执行的检查，提供交接表；不要在等待未知时长的人工反馈期间无期限保留服务、容器或含测试数据的下载。默认清理本轮资源并记录重建方法；仅用户明确要求保留时记录资源、用途和清理责任。需要现场浏览器／Word 验收时与操作者约定可执行窗口后重建夹具。

交接表至少包含：案例及子例 ID、角色、浏览器操作、请求／范围／确认版本、预期状态与提示、预期下载文件名、响应文件 SHA-256／大小、Word 应检查的全部页面／颜色／表格事项、实际页数、修复提示与 Protected View、实际结果、操作者、时间、证据来源。浏览器下载完成后由 WSL 或 Windows 只读哈希关联实际文件，不能只用 API 补充请求的哈希代替浏览器文件。

人工操作者执行 Windows 浏览器真实页面点击与 Word 实际逐页检查并反馈；截图脱敏，不能包含账户、许可证、cookie、密码或真实教师资料。OpenCode 核对夹具、文件及来源后整合。证据不完整时提出精确缺项；用户笼统回复“看起来没问题”不足以判所有子例通过。

桌面版 ChatGPT／Codex 如果已经具有可用 Computer Use 和所需权限，可以作为 GUI 协调者；仅打开测试页面／文件，不改业务代码。普通聊天、WSL 命令能力或内置浏览器能力不等于 Word 桌面能力。不得为本片主动安装新插件、扩展或 MCP。

## 审计和数据边界

抽查 `operation_records`：每次成功下载恰一条 `action="export_word"`、`target_type="class"`、`target_id=resolved_class_id`、`target_version_after=null`，操作者正确；不得记录范围、版本、文件名、facts 或内容。失败、409、无匹配、超限和过期响应分别核对服务端实际请求，不能只凭 UI toast 推断审计。

验收前后比较计划、内容、确认、指针、同步状态等业务表；除构造场景明确执行的保存／确认和成功导出审计外，导出不得产生业务写入。不要把为 `context_changed` 主动执行的保存误报成导出写入。

## 失败处理

先保留最小脱敏证据并定位：

- 数据／权限／选择／409／审计：片 1 或片 3；
- OOXML 内容、分页、标红、动态列、模板锚点：片 1 或片 2；
- 文件名、header、Blob、警示、弹窗状态：片 3；
- Windows／WSL localhost、Word build、字体或 Office 安全策略：验收环境，不默认改代码。

只有缺陷可复现且预期已由规格明确时才修复。若需改变一级技术栈、模块边界、数据权威、通信机制、模板资产或选择 §11.9，停止并报告。

修复后重跑失败案例、相邻同层案例、I5 定向单测、后端全量单测、前端 typecheck/build。若改读取、事务、权限或审计，重跑 I5 隔离 MySQL 集成并要求 0 skip；若只改前端，仍复跑受影响 Windows 浏览器案例；若改生成／映射，复跑受影响 W 案例和 Word。不得用 mock、LibreOffice 或 PDF 冒充 Word 复核。

## 文档更新

新增 `docs/bootstrap/i5-slice4-validation-YYYY-MM-DD.md`（替换为实际执行日期），至少记录：

- 实际基线、修复提交（如有）、最终 HEAD；
- 自动检查／浏览器下载／Word 验收各层状态、实际操作者与证据来源；待人工项不写成已完成；
- Windows、WSL2、Ubuntu、浏览器、Word 产品／版本／build／位数／更新渠道及开发工具版本；
- 隔离 MySQL 资源、版本、InnoDB、Alembic head；
- W1–W6 每个主例和子例状态、文件 SHA-256／大小／Word 页数、浏览器入口、警示、审计和版式结论；
- 浏览器权限、409、`context_changed`（含 facts 归零）、无匹配、超限、确认版本、警示、文件名、重复点击和过期响应矩阵；
- Word 打开、Protected View／修复提示、页面视图或打印预览、字体替代和逐页结果；
- 历史 Ubuntu／LibreOffice 与本轮证据边界；LibreOffice 如执行须单列为补充；
- 模板前后哈希、问题、最小修复、复核范围；
- 未执行项：Office 其他应用、WPS、实体打印、部署、AI、性能；
- Windows／WSL 进程、容器、volume、测试库和两个临时目录的清理与可恢复性。

完成后最小更新：

- `docs/specs/word-export-implementation.md`：片 4 状态与分层结果；
- `docs/specs/word-template-validation.md`：只补实际结果引用或已验证环境事实；
- `docs/bootstrap/architecture-v1-readiness.md`：完成／受阻边界和下一步；
- `README.md`：实际通过项、环境限制和精确测试结果。

当前文档已在 2026-10-01 校正阶段、API 代理与环境信息；不重复重写历史结果。不要修改 `ARCHITECTURE.md`、ADR、模块 Contract、模板资产或历史事实。任一 Windows 浏览器或 Word 必需项受阻时，必须精确写到哪一层完成，不能笼统写“I5／片 4 全部完成”。

## 回归命令

开始前和任何修复后至少在 WSL2 Ubuntu 中运行：

```bash
cd backend
UV_PYTHON_DOWNLOADS=never uv sync --locked
APP_DISABLE_DOTENV=1 .venv/bin/python -m unittest \
  tests.unit.test_i5_export_read_service \
  tests.unit.test_i5_export_mapping \
  tests.unit.test_i5_word_export_docx \
  tests.unit.test_i5_export_api_schemas \
  tests.unit.test_i5_export_api_routes -v
APP_DISABLE_DOTENV=1 .venv/bin/python -m unittest discover -s tests/unit -q

cd ../frontend
# 仅首次恢复锁定依赖时执行 npm ci；依赖已就绪的修复回归无需重复安装
npm ci --registry=https://registry.npmjs.org
npm run typecheck
npm run build

cd ..
git diff --check
git status --short
```

历史基线是 I5 定向 170 项、后端全量 533 项；报告实际精确数量和差异原因。前端构建若仍只有既有主包体积告警，记为非阻断既有项，不顺手拆包。

## 清理与交付

记录本片启动的精确 WSL PID、容器、volume，以及本片 Windows 浏览器／Word 窗口和两个临时目录。验收结束后：

1. 只停止本片 API、Vite 和相关浏览器／Word 实例；不能宽泛 `pkill`／`taskkill`，不能关闭用户原有窗口或文档。
2. 精确停止并删除本片 MySQL 容器和 volume，确认二者不存在；不得触碰其他资源。
3. 先记录哈希与结果，再精确删除 WSL 临时目录和 Windows 专用验收目录；不得递归删除 `$HOME`、`%USERPROFILE%`、通用 Downloads、仓库根或通配路径。
4. 说明临时数据库、下载及截图／PDF（如有）删除后不可恢复；Git 内脱敏文字和哈希可恢复。
5. 确认 Git 未纳入凭据、cookie、认证头、计划全文、DOCX／PDF bytes、浏览器 profile、Office 临时文件、截图缓存或临时日志。

最终检查 diff，确认没有纳入 `.codex/config.toml` 或其他用户既有修改。按既有片 4 授权与实际环境权限 commit／push 本任务验证记录、直接相关状态文档及确有必要的最小修复／测试，不强推。协调者本轮未提交的文档更新须逐项核对属于本任务，不能盲目 git add 全部；不要重新提交未改动的提示词或配置。不要部署，不要创建 PR，不要自动开始其他功能。

结束报告必须包含：实际基线与最终 HEAD、Windows／WSL2／Ubuntu／浏览器／Word 版本、隔离资源、数据构造方式、W1–W6 逐项结果、浏览器矩阵、Word 逐页／打印预览结果、历史 LibreOffice 证据边界、模板哈希、审计与零非预期业务写入、定向／全量测试精确数量、typecheck/build、发现和修复、Windows 与 WSL 清理、commit/push、未执行项、剩余风险及最终 diff 摘要。

---
