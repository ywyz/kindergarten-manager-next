# I5 片 4 产品验收记录（2026-10-01 执行轮）

> 历史记录：2026-10-02 当前验收环境已更改，见 [新口径](../specs/i5-validation-environment.md)。本文两张历史 H 表编号不可跨表直接对应，下一轮使用独立 R 编号及语义名称。旧“超 8 周范围”不能作为 422 判据，正确上限是实际入选日计划 32／周计划 9 份；历史 UI 422 属参数校验路径，不算份数超限证据。资源“重建保留”属于桌面协调者第一轮交接，“停止并删除”属于独立自动检查退出记录，均不表示当前服务器资源状态；新部署逐项另记。

状态：**独立自动检查完成；桌面协调者浏览器层 UI 部分完成；文件落盘与 Word 层待人工（Windows 真实浏览器 + Word）**。依据 [i5-slice4-opencode-prompt-2026-10-01.md](i5-slice4-opencode-prompt-2026-10-01.md) 分层执行；不据此宣称 I5 或片 4 完成。

## 基线与 HEAD

- 起始基线 `main` / `3ad97dd`（本地 `origin/main` 同指向，未刷新远端）；本轮无业务代码修复，无修复提交。
- 用户既有未提交改动（`.codex/config.toml`、AGENTS.md、README、readiness、旧提示词标注、两份规格更新）已逐项审阅并保留，不属于本轮验证产物。

## 分层状态

| 层 | 状态 | 操作者 | 证据来源 |
| --- | --- | --- | --- |
| 阶段 1 版本与环境采集 | 完成 | WSL2 OpenCode | Linux 命令 + `powershell.exe` 只读命名属性查询 |
| 阶段 2 独立自动检查（单测 / 集成 / 启动验证） | 完成 | WSL2 OpenCode | `unittest`、`uv`、`npm` 实际返回 |
| 阶段 3 Windows 浏览器真实下载 | 全部**待人工验收** | 人工 | 见下方交接表 |
| 阶段 3 Word 逐页版式 | 全部**待人工验收** | 人工 | 见下方交接表 |

## 实测环境（2026-10-01 重新采集，与当日只读记录一致，无漂移）

- WSL：`wsl.exe --version` 显示 WSL 版本 2.7.14.0、内核版本 6.18.33.2-2、WSLg 1.0.73.2、MSRDC 1.2.7214（UTF-16 输出按字符辨认）。
- Ubuntu 26.04.1 LTS；内核 `6.18.33.2-microsoft-standard-WSL2`。
- Windows：`EditionID=Professional`、`DisplayVersion=25H2`、`CurrentBuild=26200`、`UBR=9457`；CIM Caption 经 EditionID 交叉核对为 Windows 11 Pro。
- Office Click-to-Run：`OfficePackageVersion=16.0.20326.20158`、`OfficeProductReleaseIds=O365HomePremRetail`；Configuration `Platform=x64`，UpdateChannel / CDNBaseUrl GUID `492350f6-3a01-4f97-b9c0-c7c6ddf67d60`（Current Channel 配置值）。
- Word：WINWORD.EXE `FileVersion=16.0.20326.20158`（未启动 Word；“关于 Word” 界面显示与 x64 位数待 GUI 阶段核对）。
- Windows 浏览器：第一轮为桌面协调者"Codex 内置浏览器"（调用 Chrome 失败，经用户授权采用）；Windows 真实桌面浏览器名称/版本待人工阶段记录。
- 开发工具：Python 3.14.4（`UV_PYTHON_DOWNLOADS=never uv sync --locked` 成功恢复 `.venv`）、uv 0.12.21、Node 26.10.0（nvm）、npm 11.19.1、Docker 29.8.2 / Server 29.8.2、mysql:8.4 镜像 digest `sha256:6ea90827b1100f8f2ae306a539f86d2c264a26ed435a2a9f75551dd5c3aeb242`。
- 过程说明：用户不在此前 docker 组，经授权执行 `usermod -aG docker ywyz` 并重启 OpenCode 后生效；docker daemon 无代理曾无法直连 Docker Hub，由用户配置代理（代理配置为用户操作，OpenCode 未改任何全局配置）。

## 隔离资源与启动断言（阶段 2 已验证，用后已清理）

- 容器 `kg-next-i5-slice4-mysql-20261001`，volume `kg-next-i5-slice4-data-20261001`，映射 `127.0.0.1:13386->3306`，镜像 `mysql:8.4`。
- `SELECT VERSION()` 返回 **8.4.11**；`default_storage_engine` = **InnoDB**；库 `kindergarten_test_i5_fresh`（I5 guard 白名单内，端口 13386，DSN 仅在进程环境，未写入本记录）。
- Alembic：`heads` = `20260924_i4_weekly_plans`；`upgrade head` 后 `alembic_version` 为同值；17 张业务表 + `alembic_version` 建齐，均 InnoDB。
- 临时 API：`uvicorn app.main:app`（127.0.0.1:8000，`APP_DISABLE_DOTENV=1` + 显式 DSN + `ALLOWED_ORIGINS` 含 5173 两个来源），`/health` 返回 200 `{"status":"ok"}`。
- 临时 Vite：dev 服务器 127.0.0.1:5173（strictPort），`5173/api/*` 实际代理至 8000 隔离实例（未注册路径返回后端统一 404 JSON）。
- 响应含 `Cache-Control: no-store`（真实 HTTP 响应头核验）。
- 播种：复用 `tests/integration/i5_support.seed_world`（仓库内既有 builder）+ 仓库外一次性脚本 `/tmp/opencode/i5_seed_browser.py` 为 5 个验收账号写入符合 scrypt 校验的密码 hash（口令 ≥12 字符，符合 `security.validate_password`），口令仅出现在进程环境，未入仓库或文档。已验证 `POST /api/auth/login` 携带 5173 Origin 返回 200。
- 端口预检：8000/5173/4173/13386 启动前空闲；未发现关联进程，未停止任何非本片资源。

## 模板哈希（生成前后一致）

| 模板 | SHA-256 |
| --- | --- |
| `daily_plan.docx` | `99008f92ae42cc87da7e42e84009ffcd8bbefdf43602f09a59ae4027e5ddc9bd` |
| `weekly_plan.docx` | `24ccaa9e557522c40a653643381e31f319ea6ae5e9f3e30e9dfa41da21986aed` |

## 自动检查精确结果

| 检查 | 结果 |
| --- | --- |
| I5 定向单元（read service / mapping / docx / schemas / routes） | **170 项通过**（0 失败 0 跳过），与历史基线一致 |
| 后端全量单元 | **533 项通过**（0 失败 0 跳过），与历史基线一致 |
| I5 隔离 MySQL 集成 `test_i5_export_api` | **30 项通过，0 跳过**，I5 guard 日志确认 host/port/db/版本/alembic head |
| 前端 `npm run typecheck` | 通过 |
| 前端 `npm run build` | 通过；主 JS 包 1,135.42 kB（gzip 354.11 kB），触发既有非阻断体积告警，未拆包 |
| `git diff --check` | 通过（无空白问题） |

## 审计与业务写入边界（自动层结论）

- 集成套件已断言：成功导出恰一条 `operation_records`（`action="export_word"`、`target_type="class"`、`target_id=resolved_class_id`、`target_version_after=null`），失败/409/无匹配/超限路径无成功审计、无文件、无业务写入；本轮未发现缺陷。
- 集成后的抽查与“导出前后业务表对比”属产品下载闭环，待人工层在重建夹具后执行。
- 本轮除容器播种与导出外，未对业务表写入；无真实数据、无 AI、无外部服务调用。

## W1–W6 结果矩阵（自动层完成数据/权限/审计；Word 层全部待人工）

| 案例 | 数据/权限/审计逻辑（自动） | Windows 浏览器下载 | Word 逐页版式 |
| --- | --- | --- | --- |
| W1 普通单日 / 全空子例 / 同班只读教师可导出 | 通过（单测+集成覆盖） | UI 层部分通过（H1–H3 状态/文件名/警示头实测；下载落盘 BLOCK） | 待人工验收 |
| W2 长过程分页与标红 | 通过（mapping/docx 单测） | HTTP 层部分通过（H4 200/文件名/无警示头；下载 BLOCK） | 待人工验收（需跨页夹具） |
| W3 三份合并、乱序升序、新页开始 | 通过（集成） | HTTP 层部分通过（H5 200；下载 BLOCK） | 待人工验收 |
| W4 调休／六／七列及停课 | 通过（集成） | H10/H9/H13 涉及部分通过；下载与列数版式 BLOCK/待人工 | 待人工验收 |
| W5 跨周排序去重、单日整周、无匹配 | 通过（集成） | H10/H11 部分通过；无匹配已通过（H9 404） | 待人工验收 |
| W6 确认版本、未确认 404、警示头 | 通过（集成） | HTTP 层部分通过（H11/H13 200；H12 未执行） | 待人工验收 |

历史 Ubuntu/LibreOffice（2026-09-20 原型 31 页）与 Omarchy 结果仅为历史证据，未填入上表。

## Windows 浏览器下载闭环矩阵（原计划 11 项）

第一轮桌面协调者会话（2026-10-01 16:13–16:35 UTC+8，Codex 内置浏览器，非 Windows 桌面浏览器）完成 UI 层部分回填；**任何下载均未落盘**（浏览器无法保存文件），文件层与 Word 层全部待人工。

### 第一轮协调者会话结果与裁定

| ID | 状态码（实测） | 文件名（Content-Disposition 实测） | 下载 | 裁定 / 剩余 |
| --- | --- | --- | --- | --- |
| H1 | 200 | `小班甲_日计划_2026-08-10_2026-08-10.docx`（Content-Length 14486，`no_split_baseline` 警示头） | BLOCK（无文件） | 浏览器层 UI 通过（状态/文件名/警示头）；下载与 Word 待人工 |
| H2 | 409→200 | `小班甲_日计划_2026-08-18_2026-08-18.docx`（14262） | BLOCK | 409 逐项 facts（13 项）→勾选确认→200；空内容 Word 核对待人工 |
| H3 | 200 | 同 H1 | BLOCK | tsw_i5 只读页面无编辑/确认入口、可导出；此前“日历停留”现象复验未复现，撤销缺陷标记 |
| H4 | 200 | `小班甲_日计划_2026-08-13_2026-08-13.docx`（14895，无警示头） | BLOCK | 红字/跨页完整待 Word |
| H5 | 200 | `小班甲_日计划_2026-08-10_2026-08-13.docx`（15865，`no_split_baseline`） | BLOCK | 三份升序/新页/单份一致待 Word |
| H6 | 未执行 | — | — | 界面无入口；构造 403 请求待下一轮 |
| H7 | 登录 200，未执行 | — | — | 待分配提示页正确；403 待下一轮 |
| H8 | 200 | 同 H1 | BLOCK | 管理员显式 class_id 导出成功 |
| H6b | 409（非 422） | — | FAIL→**裁定为交接表口径错误** | 按下限按 §11.1② 以去重后选定份数判定（本轮整学期实测 10 份 ≤31 → 409 缺项先行）；422 分支已由集成测试覆盖；产品无缺陷 |
| H9 | 404 | — | 成功：不下载 | `EXPORT_NO_MATCH` 中文提示；tsw_i5 复核同结果并截图 |
| H10 | 200 | `小班甲_周计划_2026-08-10_2026-10-04.docx`（20259，`confirmed_not_latest` 警示头） | BLOCK | 两份/跳过未确认与停课周待 Word |
| H11 | 200 | `小班甲_周计划_9周_2026-09-28_2026-10-02.docx`（18996，`confirmed_not_latest`） | BLOCK | V1 快照逐字段核对待 Word |
| H12 | 未执行 | — | — | 第 3 周无导出按钮、有“确认当前草稿”；服务端 404 待下一轮 |
| H13 | 200（非 422） | `小班甲_周计划_2026-08-03_2026-10-25.docx`（21443） | FAIL→**裁定为交接表口径错误** | 命中 3 份确认周 ≤8 → 200 符合规格；422 由集成测试覆盖；产品无缺陷 |
| H14 | 未执行 | — | — | context_changed 双会话流程待下一轮 |
| H15 | 200×1 响应 | 同 H1 | BLOCK | 服务端审计恰 1 条（见下）——重复点击防重通过 |
| H16 | 未执行 | — | — | 延迟取消/object URL 待下一轮 |
| H17 | 部分 | 中文 filename*、ASCII fallback、`.docx` 后缀已验证 | BLOCK | ZIP/Word 得核待文件 |
| H18 | 部分 | 控制台 4 条、关键模式匹配 0 | — | localStorage 接口不支持；面向不保留 |

### 审计核对（服务端权威，OpenCode 执行）

- 本轮会话恰 10 条 `operation_records(action="export_word")`：tow_i5×8、tsw_i5×1、adm_i5×1；全部 `target_type="class"`、`target_id=clsi5`、`target_version_after=null`；本地时间与协调者记录逐一对应（如 H15 双击仅 16:31:05 一条）。失败/409/404/422 均未产生成功审计。
- 其中一条 16:13:20 `create_daily_plan`（2026-10-23 空内容计划）来自协调者会话自身创建操作，即 409 facts 中“多出 10-23”的来源；属验收数据操作，非导出行为写入。
- 导出未产生任何其他业务表变更（不含协调者主动创建/确认场景的数据操作）。

原始浏览器层证据由协调者保管（response-evidence.json、H7-unassigned.png、H9-no-match-recheck-tsw.png）。

## Word 检查（退出项与惯例）

逐文件记录损坏/修复/转换提示（Protected View 单列）、页面视图/打印预览页数、全部页面可读性、截断/遮挡/越界/大空白、W2 红色辨认、字体替代；Word 检查不保存修改；关闭后复验下载文件哈希不变。

## 人工交接表

通用约定：服务重建后由操作者在 `<http://127.0.0.1:5173>` 用下页账号登录操作；每个文件记录 SHA-256 与字节数（下载哈希以 Windows 侧 `/mnt/c` 或 `certutil`/`Get-FileHash` 只读核验）；模板哈希前后一致后再交给 Word。

角色 / 凭据约定：名义账号见下列各行；登录口令仅在此轮交接时由 OpenCode 当面提供，不写入文档。临时目录、容器与 DSN 均为一次性。操作者按下列各行执行并在"实际结果"列回填；本表为人工执行时补记结果的载体，机器侧结论已在上方矩阵锁定。

| ID | 角色 | 入口 / 请求 | 预期响应 | 预期下载文件名（UTF-8） | Word 检查项 |
| --- | --- | --- | --- | --- | --- |
| H1 | tow_i5 | 日计划页单日导出 2026-08-10（含过程与两游戏） | 200 下载；必要时显示 `no_split_baseline` | `小班甲_日计划_2026-08-10_2026-08-10.docx` | 两列表格、栏目、周号/星期、主题、“体能大循环”、两游戏、过程无红 |
| H2 | tow_i5 | 全空日计划首次 409 → facts 展示 → 勾选确认 → 下载 | 409（含逐日/逐栏 facts）后 200 | `小班甲_日计划_<from>_<to>.docx`（以响应 Content-Disposition 为准） | 栏目齐全内容为空、无样例文字 |
| H3 | tsw_i5 | 同班日计划导出 | 200；页面只读、无编辑/确认按钮 | 同 H1 模式 | 同 H1，教师名正确 |
| H4 | tow_i5 | 范围 2026-08-10~2026-08-12 三份（其中一份缺基准、一份长过程跨页） | 200 单文件 | `小班甲_日计划_2026-08-10_2026-08-12.docx` | 三份按时序升序、各自新页、无额外空白页、红字仅限有基准方案新增/替换 |
| H5 | adm_i5 | 管理员带 `class_id` 显式导出；tfr_i5 或 tcr_i5 同类请求 | 管理员 200；跨班/待分配 403 | — | — |
| H6 | tow_i5 | 周计划整周范围（第 2 周）合并 2 周 | 200 | `小班甲_周计划_2026-08-10_2026-08-23.docx` 型 | 每份新页、表头起止日期、全栏目 |
| H7 | tow_i5 | 单周计划弹窗显式历史确认版本下载 | 200 + `confirmed_not_latest` 警示头 | `小班甲_周计划_w2_….docx` 型 | 逐字段等于快照 V1，无草稿内容 |
| H8 | tow_i5 | 未确认周计划单份导出 | 404 `CONFIRMATION_NOT_FOUND`，无下载 | — | — |
| H9 | tow_i5 | 仅命中非教学日 / 无已确认计划；超 8 周范围 | 404 `EXPORT_NO_MATCH`；422 `EXPORT_RANGE_TOO_LARGE`（UI 至少核对超限分支），不下载 | — | — |
| H10 | tow_i5 | 409 确认后另一会话再次保存 → 原确认回传 | 409 `context_changed` + 最新 facts；facts 归零时仍需勾选确认 | — | toast 不弹旧响应、无文件 |
| H11 | tow_i5 | 快速双击导出按钮 | 仅一次下载、一条成功审计 | — | — |
| H12 | tow_i5 | 弹窗打开后制造延迟关闭/切换班级 | 旧响应不下载、不覆盖状态 | — | object URL 不复用 |
| H13 | 并行 | 中文文件名、危险班名 ASCII fallback、`.docx` 后缀、ZIP 完整性 | 响应头核验 + Word/浏览器正常打开 | 中文文件 + ASCII fallback 均 | 页面/控制台/localStorage 无敏感值 |

审计抽查：每例成功下载后核对 `operation_records` 恰一条、无范围/版本/文件名泄漏；失败与 409 各例核对无新增成功审计。业务表对比：除构造场景保存外导出前后无写入。

## 清理与可恢复性

1. 本片启动的 uvicorn（PID 9828/10374）与 Vite 已精确停止；未触碰其他进程。2026-10-01 下午应用户要求为人工验收轮重建并保持运行：uvicorn（8000）与 Vite（5173）及容器 `kg-next-i5-slice4-mysql-20261001`——**属用户明确要求保留**，用于后续真实浏览器/Word 验收；本轮验收完成后由 OpenCode 精确清理。
2. 容器与 volume：`docker rm -f kg-next-i5-slice4-mysql-20261001` + `docker volume rm kg-next-i5-slice4-data-20261001`（本轮已删除，含播种数据，**删除后不可恢复**）。
3. 仓库外临时脚本 `/tmp/opencode/i5_seed_browser.py`、日志 ` /tmp/opencode/i5_api.log`、`login.json` 已删除；Windows 专用下载临时目录本轮未创建（无 GUI），若重建时创建须由操作者事后精确删除。
4. 夹具重建方法（记录，供GUI 窗口约定后重建）：
   - `docker run -d --name kg-next-i5-slice4-mysql-<日期> -e MYSQL_ROOT_PASSWORD=<临时口令> -e MYSQL_DATABASE=kindergarten_test_i5_fresh -p 127.0.0.1:13386:3306 -v kg-next-i5-slice4-data-<日期>:/var/lib/mysql mysql:8.4`
   - `cd backend && uv run --locked alembic upgrade head`（需显式 DSN）
   - 用 `tests/integration/i5_support` 的 builder 播种世界并通过仓库外脚本为登录账号写合法口令 hash（同本轮脚本思路）；`APP_DISABLE_DOTENV=1` + 显式 DSN 启动 uvicorn 与 `npm run dev`。
   - 播种前再次断言 DSN 指向白名单库与 13386。

## 未执行项

Office 其他应用（Excel/PowerPoint/Outlook）、WPS、LibreOffice（本机未装）、实体打印、部署与服务器、真实 AI、性能/容量、§11.9、Windows 浏览器名称/版本采集（GUI 层）、Word“关于”界面显示、字体实际呈现。

## 剩余风险

- Word/浏览器接收能力以其真实操作为准；Content-Disposition 中文文件名在 Windows 下载层的最终表现未验证。
- Word GUI 渠道显示可能与注册表 Current Channel 配置存在显示差异，届时单列记录。
- 前端主包体积既有限制未处理，属后续前端性能切片范围。
