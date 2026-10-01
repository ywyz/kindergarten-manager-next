# I5 片 4 产品验收记录（2026-10-01 执行轮）

状态：**独立自动检查完成 / Windows 浏览器与 Word 验收待人工**。依据 [i5-slice4-opencode-prompt-2026-10-01.md](i5-slice4-opencode-prompt-2026-10-01.md) 分层执行；本轮无 GUI 能力，GUI 阶段按人工交接表暂停，**不据此宣称 I5 或片 4 完成**。

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
- Windows 浏览器：待人工阶段记录名称与版本。
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
| W1 普通单日 / 全空子例 / 同班只读教师可导出 | 通过（单测+集成覆盖） | 待人工验收 | 待人工验收 |
| W2 长过程分页与标红 | 通过（mapping/docx 单测） | 待人工验收 | 待人工验收（需跨页夹具） |
| W3 三份合并、乱序升序、新页开始 | 通过（集成） | 待人工验收 | 待人工验收 |
| W4 调休／六／七列及停课 | 通过（集成） | 待人工验收 | 待人工验收 |
| W5 跨周排序去重、单日整周、无匹配 | 通过（集成） | 待人工验收 | 待人工验收 |
| W6 确认版本、未确认 404、警示头 | 通过（集成） | 待人工验收 | 待人工验收 |

历史 Ubuntu/LibreOffice（2026-09-20 原型 31 页）与 Omarchy 结果仅为历史证据，未填入上表。

## Windows 浏览器下载闭环矩阵（原计划 11 项）

无 GUI 能力，全部**待人工验收**；UI 不可发起的越权分支可在真实浏览器会话内构查 403/404。执行时逐例记录角色/入口/状态码/是否下载/文件名/提示/审计变化。

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

1. 本片启动的 uvicorn（PID 9828/10374）与 Vite 已精确停止；未触碰其他进程。
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
