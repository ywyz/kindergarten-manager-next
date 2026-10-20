# D0 Windows 桌面可行性验证结果

更新：2026-10-11（Codex 独立复审与 GUI 验证补记）。本报告由 OpenCode 在实施后创建并随修复/复验持续更新，§1–8 保留各轮身份；最新状态见下方补记及独立审阅 §7。依据 [D0 规格 §5](../specs/desktop-foundation-plan.md)与[当前任务](../tasks/current.md)。**本报告不代表完整每日活动计划完成，也不代表 Windows 10 / 干净机器 / 真实 AI 已验证。**

> **首轮独立审阅（2026-10-10，历史）：D0 暂不通过，进入修复复验。** [审阅记录](desktop-d0-review.md)包含 R1–R10 和最新 D0 矩阵判定。本轮重跑 37 项 Python 测试通过，但当前源码类型检查失败、无控制台目录包启动失败、Word 中途写入失败会损坏目标；自检还未覆盖完整页面导出与保存前重启读回。以下 §1–4 和 §6 保留 OpenCode 首轮报告身份，其“通过”仅代表当时所报告的特定路径，不能替代本次复核。尤其“日志均无令牌”与“窗口完整生成保存”描述须按 R9／R10 收窄。修复后由 OpenCode 在本文件追加实际复验，不覆盖原始失败／未验；当前任务已改为修复与复验。

> **2026-10-10 第二轮独立复审（历史）：两个 P1 核心已修，75 项测试、类型检查及源码三进程窗口验证通过；当时 R10 版本断言和异常自检结束仍需补齐，R1 启动超时清理随同补正。** 当时最终 EXE 被本机应用控制策略阻止，原生对话框与全页目测未验。见 [审阅 §6](desktop-d0-review.md#6-第二轮独立复审2026-10-10)，不将原交付声称当作当时独立复审结论。

> **2026-10-10 第三轮（OpenCode 交付）：按审阅 §6 补齐 R10 版本断言、R10 异常自检自动结束与 R1 启动超时／失败清理。** 92 项测试通过（新增 17 项）、源码真实窗口 first/restart/verify 通过并新增异常自检自动结束实测；本轮重建的最终包取得无控制台、无重定向运行证据。详情见 [§8](#8-2026-10-10-第三轮r10-断言异常结束与-r1-清理补项)，§7.7 相应的“R10／清理仍须补齐”以 §8 为准。当时原生对话框及 Word 全页查看仍未执行；后续补验以下方 10 月 11 日记录为准。

> **2026-10-11 Codex 独立复审：D0 工程复审通过，可进入 D1 契约准备。** 独立重跑 92 项测试、复验同一最终包 `3AC3D5ED…` 的仓外无控制台三进程 A/v1→B/v2；经真实 GUI 完成普通关闭／重启、原生取消、中文空格路径保存、Word 占用失败及释放后同目标重试，并在 Word 查看全部两页。原 R1–R10 关闭；watchdog 极端阻塞为非阻塞 P3，不能保证所有挂起均在 300 秒内强退。详细证据、散列和 D0 矩阵见 [审阅 §7](desktop-d0-review.md#7-第三轮独立复审与-gui-验证2026-10-11)。干净机器、Win10、WPS、其他 DPI、用户本人体验仍未验，不宣布发行完成；Codex 已完成[D1 技术核查](desktop-d1-technical-review.md)，当前提示词为 D1A 本地数据与 API 编码；真实业务仍未实现。

## 1. 实施摘要

- 新增 `desktop/` 桌面验证切片：隔离入口（pywebview＋WebView2）、独立 FastAPI 应用、SQLAlchemy 2.x SQLite 探针、复用 I5 日 Word 生成器的合成映射、最小受限宿主保存接口、PyInstaller 目录式测试包构建脚本与自动化窗口驱动。
- 前端仅新增独立 D0 验证构建入口（`frontend/d0.html`、`frontend/src/d0/*`、`frontend/vite.d0.config.ts`），未改动 `App.vue`、主构建入口和任何业务页面。
- 未挂载旧业务路由；未读取旧 `.env`/配置；未做任何数据库迁移；未做 Git 暂存/提交/推送。

### 1.1 实际修改文件

| 文件 | 内容 |
| --- | --- |
| `desktop/d0_paths.py` | dev/打包两态路径解析（前端 dist、Word 模板、数据目录、自动保存目录） |
| `desktop/d0_db.py` | SQLite 合成探针（SQLAlchemy 2.x、显式 `BEGIN IMMEDIATE`、失败回滚、stack 事实汇报） |
| `desktop/d0_word.py` | 合成记录 → `word_export_mapping.map_daily_plan` → `generate_daily_export_docx`（模板路径以参数传入） |
| `desktop/d0_server.py` | D0 独立 FastAPI：Host 精确校验、Origin 精确校验、会话令牌守卫、liveness、静态前端同源挂载 |
| `desktop/d0_host_api.py` | `get_session` 与 `save_docx`（原生保存对话框；只认 .docx；仅写字节；无读取/命令桥接） |
| `desktop/d0_main.py` | 入口：回环端口、就绪等待、开窗、退出清理、失败弹窗、`--selftest` |
| `desktop/d0_driver.py` | 自动化窗口驱动（真实 WebView2 页面执行用户流程并产出 JSON 证据） |
| `desktop/d0_jsdiag.py` | 独立 JS 桥诊断脚本（验证期工具） |
| `desktop/build_d0.py` | 前端构建 + PyInstaller onedir 打包脚本 |
| `desktop/requirements-d0.txt` / `requirements-d0-dev.txt` / `requirements-d0.lock.txt` | 依赖声明与锁定 |
| `desktop/tests/conftest.py`、`test_d0_guard.py`、`test_d0_db.py`、`test_d0_word.py`、`test_d0_host_save.py`、`test_d0_startup.py` | 自动测试（37 项） |
| `frontend/d0.html`、`frontend/src/d0/main.ts`、`App.vue`、`client.ts`、`helpers.ts`、`frontend/vite.d0.config.ts` | D0 独立验证窗口前端 |
| `.gitignore` | 追加 `build/` 排除 |

### 1.2 依赖与锁定版本（`desktop/.venv`，`uv venv --python 3.12`）

核心运行：fastapi==0.143.0、uvicorn==0.54.0、sqlalchemy==2.0.54、lxml==6.1.3、pydantic==2.14.0、pywebview==6.2.1（Windows 后端经 pythonnet==3.2.1）。
构建/测试：pyinstaller==6.22.3（hooks-contrib==2026.8）、pytest==8.4.2、httpx==0.28.1（lock 全文见 `desktop/requirements-d0.lock.txt`）。

系统组件检测：**WebView2 Runtime 已安装（154.0.4258.62，HKLM EdgeUpdate Clients）**，无需全机安装。未安装新 Skill/MCP，未修改全机配置。

### 1.3 数据与产物位置

- 合成 SQLite 数据（打包运行默认）：`%LOCALAPPDATA%\KindergartenManager-D0\data\d0_probe.db`（可 `KGM_D0_DATA_DIR` 覆盖）；**独立于程序解包目录**。
- 前端 D0 构建：`build/desktop-d0/frontend/`；最终包：`build/desktop-d0/package/KGNext-D0Verify/`（两者分离，`build/` 已 gitignore）。
- 自动窗口证据 JSON：`build/desktop-d0/selftest-dev.json`（开发态）；仓外运行证据在 `%TEMP%\opencode\d0-run\selftest1.json`、`restart-a.json`、`restart-b.json`。
- 宿主保存的 DOCX：仓内自检 `build/desktop-d0/selftest/autosave/D0自动保存_日计划.docx`；仓外 `%TEMP%\opencode\d0-run\autosave\D0自动保存_日计划.docx`。

### 1.4 可复现命令

> 2026-10-10 修复补记：安装命令改用已存在的锁文件 `requirements-d0.lock.txt`（含构建/测试依赖），不再从宽泛 requirements 安装；默认完整构建入口是 `build_d0.py`，`--skip-frontend`（旧 `--package-only`）只复用已构建前端。当前源码的自动检查与打包结果见 §7。

```powershell
# 隔离环境（一次）：与锁文件逐项一致（39 个包，2026-10-10 复核）
uv venv --python 3.12 desktop/.venv
uv pip install --python desktop/.venv -r desktop/requirements-d0.lock.txt

# 自动测试
desktop/.venv/Scripts/python -m pytest desktop/tests -q

# 前端类型检查（最终源码）
cd frontend; npm run typecheck

# 默认完整构建（前端构建 + PyInstaller onedir 包；构建输出与包输出分离）
desktop/.venv/Scripts/python desktop/build_d0.py
# 只复用已构建前端并打包：desktop/.venv/Scripts/python desktop/build_d0.py --skip-frontend

# 开发态运行（交互窗口）
desktop/.venv/Scripts/python desktop/d0_main.py
# 开发态自动窗口自检（阶段：first / restart / verify）
KGM_D0_AUTOSAVE_DIR=<dir> desktop/.venv/Scripts/python desktop/d0_main.py --selftest --selftest-phase first --out <json>

# 打包态运行（交互）与打包态自检（仓外；无控制台、无重定向）
build\desktop-d0\package\KGNext-D0Verify\KGNext-D0Verify.exe
KGM_D0_AUTOSAVE_DIR=<dir> KGNext-D0Verify.exe --selftest --selftest-phase first --out <json>
KGM_D0_AUTOSAVE_DIR=<dir> KGNext-D0Verify.exe --selftest --selftest-phase restart --expect-content "<A>" --expect-version <vA> --out <json>
KGM_D0_AUTOSAVE_DIR=<dir> KGNext-D0Verify.exe --selftest --selftest-phase verify --expect-content "<B>" --expect-version <vB> --out <json>
```

## 2. 验收矩阵 D0-1 至 D0-7

> 证据分三类记录：`自动测试`＝pytest；`真实窗口`＝脚本驱动的真实 WebView2 窗口操作（非模拟接口）；`人工`＝需人工 GUI 操作，未执行处如实标注。

### D0-1 Windows 11 运行打包程序，显示 Vue 窗口 — **已实现；打包+自动窗口通过；人工目视待验收**

- 自动测试（历史首轮声称）：前端 `npm run typecheck` 通过；服务 shell 路由测试通过。
  - **2026-10-10 更正：**该“typecheck 通过”在审阅时对当前源码并不成立（`helpers.ts` 返回类型缺字段，TS2353、exit 1，见 R3）。修复后已在最终源码复验通过，见 §7.3。
- 真实窗口（开发态）：`selftest-dev.json` `page_ready=true`，真实 Vue/Element Plus 页面在 WebView2 中挂载完成。
- 真实窗口（**打包、仓外**）：`%TEMP%\opencode\d0-run\` 复制的包执行 `--selftest`，`selftest1.json`：`page_ready=true`，无手动开发服务器/无 Vite/无 Python 安装要求。
- `token_in_url=false`；启动失败时以原生 MessageBox 提示（端口占用、WebView2 缺失、前端缺失均有明确文案），不是空白窗口。
- 环境事实：Windows 11（win32），Python 3.12.10（desktop/.venv），WebView2 Runtime 154.0.4258.62，包标识 `KGNext-D0Verify`（PyInstaller 6.22 onedir，约 45MB）。
- **未执行（人工）**：真人肉眼确认窗口字体、布局与中文渲染细节；无障碍/DPI 细察。

### D0-2 窗口写入合成记录 → 完整退出 → 重启读回 — **已实现；自动+真实窗口+打包仓外通过**

- 自动测试：`test_d0_db.py` 首存/递增版本/跨实例重开读回（模拟完整退出重启）。
- 真实窗口（开发态）：UI 保存 → 版本 4 → Python 侧独立读回 `content_matches=true`。
- 真实窗口（打包仓外）：`restart-a.json`（接续 `selftest1.json` 的 v1 → 保存为 v2，内容一致）、`restart-b.json`（旧记录可见，新保存 v3，读回一致）。
- 数据位置：`%LOCALAPPDATA%\KindergartenManager-D0\data\d0_probe.db`（已核实文件存在、内容/版本正确）；非临时解包目录。
- 驱动方式记录：SQLAlchemy 2.0.54 + pysqlite（sqlite3 模块），SQLite 库版本见 `selftest*.json` `sqlite_library_version`；`PRAGMA foreign_keys=ON`（每次连接启用并验证返回值）；`journal_mode=wal`；事务为显式 `BEGIN IMMEDIATE … COMMIT/ROLLBACK`（`isolation_level=None`，SQLAlchemy 文档模式）；提交前写后读校验。
- 退出清理：window 关闭后 `server.should_exit` + join；`server_stopped_clean=true`；进程退出（run1/run2 后无残留 python/KGNext 进程）。
- **未执行（人工）**：真人关闭窗口按钮的完整手工流程（自动驱动等价代码路径已验，人工点击待 Codex 验收）。

### D0-3 模拟写入失败/端口不可用/服务启动失败 — **已实现；自动+真实窗口通过**

- 自动测试：CHECK 约束触发 IntegrityError → 返回 failed；原记录与版本不递增；重试成功且版本顺延（`test_d0_db.py::TestFailureSimulated...`、`test_d0_startup.py` 端口占用 → `start_and_wait=false` + 明确 error 文案）。
- 真实窗口：`selftest-dev.json`：勾选"模拟写入失败"后 UI 显示"保存失败"，记录仍为原版本 v4（`failure_kept_previous=true`、`failure_not_reported_as_success=true`）；重试成功（版本顺延）。
- 端口占用/启动失败：只弹原生错误框并退出码 2，不挂假窗口。
- **未执行（人工）**：真实磁盘写满等极端条件。

### D0-4 无会话/错误会话/不受信来源被拒；正常窗口读写成功 — **已实现；自动+真实窗口通过**

- 自动测试（TestClient）：无/错误令牌 GET→401；无 Origin/错误 Origin POST→403；精确 Origin+会话→成功；错误 Host（GET 与 POST）→403 `FORBIDDEN_HOST`；`/health` 不暴露任何数据/配置/凭据字段。
- 真实窗口：窗口内无会话头 fetch→401（`state_get_without_session`）；正常流程读写成功；`token_in_url=false`；驱动 JSON 与日志中均无令牌出现。
- 令牌机制：每次启动重新生成（`secrets.token_urlsafe`），仅存于启动内存与窗口 JS 内存；不进 URL/业务库/日志；历史校验为 constant-time。

### D0-5 合成日 Word：含中文/空格路径保存 — **已实现；自动+真实窗口(自动路径)通过；Word COM 自动化打开通过（人工目视未执行）；WPS 未执行；人工对话框待验收**

- 自动测试：`generate_daily_export_docx` 产 14458 字节有效 DOCX（ZIP 完整、document.xml 含全部合成内容、模板为受控仓库资产、SHA-256 校验通过）；`write_docx_file` 实写"含 中文 与空格.docx"成功且字节核验一致。
- 真实窗口：窗口内触发生成+极简宿主保存（autosave 预授权目录）→ `saved`，文件存在。
- **Word 打开（COM 自动化，真实 Word）**：Word 2024 打开 OK，2 页，无损坏（本机为开发机）。
- **WPS：未执行——本机未安装 WPS**。待目标机器人工验收（打开同一 DOCX 检查分页/字体）。
- 取舍记录：WebView2 的浏览器下载（Blob + `a.download`）无法可靠反馈"保存成功/取消"，按规格允许改用最小受限宿主保存接口（原生另存对话框 + 单次 .docx 写入 + fsync + 字节数核验）；不提供任意读取/命令执行。
- **未执行（人工）**：真人通过原生另存对话框选择含中文+空格的目标路径完成保存并目测 Word／WPS 渲染。

### D0-6 取消保存/不可写位置/失败后重试 — **实现完成；自动测试通过；真人对话框流程未执行**

- 自动测试：对话框关闭→`canceled`（不报成功）；占用目标→`failed` 且既有文件字节不变、无多余文件；失败后重试→`saved`（`test_d0_host_save.py`）。
- **未执行（人工）**：真人触发取消、选择不可写位置（如只读盘/被占用文件）流程及其 UI 提示。
- 取消/失败 UI 文案已实现："已取消保存（未成功，未生成文件）"/"保存失败：…"。

### D0-7 脱离仓库工作目录及开发环境启动测试包 — **已实现；打包+仓外自检通过；干净机器未执行**

- 实测：包复制到 `%TEMP%\opencode\d0-run\`，工作目录设为该处执行 `--selftest`，全部通过（`selftest1.json`/`restart-a.json`/`restart-b.json`）。资源与模板路径来自固定打包布局（`_internal/desktop_resources/*`），不依赖 CWD/仓库/开发 venv/Node。
- WebView2 条件：本机已安装并检测（154.0.4258.62）；入口含"缺失→明确提示"分支（未在本机实测该分支，因无缺失环境）。
- **未执行**：真正干净机器（无 Python/无开发链）冷启动；Windows 10；Network 断网运行（本地 API 仍需回环，判断不受限）。

## 3. 环境边界声明

- 打包自检虽"复制离仓"运行，但**仍在开发机上**（同一 Windows 11、同一用户配置、已装 WebView2 与 Word）；不视为"干净机器"证据。
- 未连接旧远程实例/旧 MySQL；无真实 AI 调用与付费凭据；无每日活动计划业务实现。
- Win10、WPS、干净机器、安装器、签名、自动更新、WebDAV、遥测均**未验证**。
- 早期遗留：一轮系统 WebView 子进程被测试期批次误杀（系统自动重建，无影响）；已确认当前进程列表仅含系统 SearchHost 的 WebView。

## 4. 可复用基础 / 验证探针 / 待 D1 适配

| 类别 | 内容 |
| --- | --- |
| 可复用基础（候选) | LaunchContext/守卫中间件（Host/Origin/会话）、`SQLiteProbe` 事务模板（BEGIN IMMEDIATE、外键启用、写后读、失败回滚）、`d0_paths` 冻结态解析、`write_docx_file`、onedir 打包参数（add-data 布局）、WebView2 检测 |
| 仅供 D0 验证探针（D1 应移除/替换） | `d0_server` 全部探针路由与静态 shell、D0 前端页面、`d0_driver`/`d0_jsdiag`、`KGM_D0_AUTOSAVE_DIR` 机制 |
| 待 D1 适配业务 | 单教师档案与班级/学期上下文、真实模型与 Alembic SQLite 基线、并发/版本竞态、草稿保护、真实日计划页面与导出范围链路、宿主保存对话框默认目录与体验 |

## 5. 进入 D1 的实际阻塞

- 原首轮结论经修复和多轮复审已更新；2026-10-11 原 R1–R10 关闭，当前 Windows 11 开发机 D0 工程验证可收口。真实包、原生对话框及 Word 全页查看证据见 [审阅 §7](desktop-d0-review.md)。
- Codex 已完成 D1 技术核查并落定[D1A 契约](../specs/desktop-manual-daily-plan.md)，当前交给 OpenCode 编码本地数据与 API。干净机器、Win10、WPS、其他 DPI、用户本人体验继续保留未验边界，不扩大已验结论或新增发行任务。
- D1A 契约已明确；真实文件数据库、迁移及竞态待编码后验证。D1B 再接页面、离开自动保存和 Word；配置维护交互仍须细化。

## 6. 剩余问题（如实记录）

1. `pywebview 6.2.1` 通过 pythonnet/WinForms 启动 `edgechromium` 后端；关闭窗口偶发控制台报出 user-data 清理噪声（不影响退出与数据，属 pywebview 已知噪声，需在多轮复验中确认无泄漏）。
2. 自动窗口驱动不代表全部人工路径；文件对话框仅可人工驱动。
3. `simulate_failure` 探针通过真实 CHECK 约束触发，但 D0 未覆盖"磁盘写满/防病毒锁定"等 OS 级失败。

## 7. 2026-10-10 D0 修复与复验（R1–R10）

本节由 OpenCode 在本轮修复后追加，保留上文首轮失败／未验历史，不覆盖 Codex 的独立审阅结论。修复以审阅记录的触发条件和验收要求为准；范围集中在 `desktop/` 与 `frontend/src/d0/`，未改旧业务生成器或一级技术栈，未做 D1／迁移／真实 AI／WebDAV，未暂存／提交／推送。

### 7.1 本轮修改文件

| 文件 | 改动 | 对应 |
| --- | --- | --- |
| `desktop/d0_main.py` | 无控制台时给 stdout/stderr 绑定 devnull；`ServiceRun` 收口 uvicorn 启动 `SystemExit`；失败路径释放 SQLite 引擎；WebView2 按 hive／体系结构检测；自检阶段与总体断言、启动流诊断 | R1、R8、R10 |
| `desktop/d0_host_api.py` | 统一 `.docx` 后缀边界；同目录临时文件 → flush/fsync → 校验字节数 → `os.replace` 原子替换；失败清理临时文件、保护原目标 | R2、R7 |
| `desktop/d0_driver.py` | 每项必需断言进入 `checks`；`combine_ok` 要求全真；写入前先读旧状态；first/restart/verify 阶段；Word 走真实页面导出入口→API→宿主 | R10、R5 |
| `desktop/d0_jsdiag.py` | 诊断只记录布尔就绪状态；去掉硬编码路径；输出到 `build/desktop-d0/diag/` | R9 |
| `desktop/build_d0.py` | 原生 Windows 解析 npm/npx（`.cmd` 经 `cmd /c`）；`--skip-frontend` 生效 | R4 |
| `frontend/src/d0/bridge.ts`（新增） | 等待实际桥函数就绪（可注入时钟/休眠） | R6 |
| `frontend/src/d0/bridge.test.mjs`（新增） | Node 桥延迟/超时回归 | R6 |
| `frontend/src/d0/helpers.ts` | 补齐 `triggerUiSave` 返回类型；保存/导出按页面序号等待；导出注入自动保存目标 | R3、R5、R10 |
| `frontend/src/d0/App.vue` | 编辑输入与已保存记录分离；失败保留输入；桥就绪容错并始终置 `__d0PageReady`；导出结果结构化 | R5、R6、R10 |
| `desktop/tests/*` | 新增 7 个回归测试文件，修改端口占用测试 | R1–R10 |
| `build/desktop-d0/jsdiag.json` | 脱敏旧诊断产物中的原始令牌（未跟踪构建产物） | R9 |

依赖未变：`requirements-d0.lock.txt` 未修改；复核安装环境 39 个包与锁文件逐项一致。

### 7.2 R1–R10 对照

| 编号 | 修复要点 | 验证方式 | 结果 |
| --- | --- | --- | --- |
| R1 | 无控制台日志适配；`--windowed` 不依赖 stdout/stderr 或重定向；初始化/服务失败/退出释放资源；定位 `page_ready=false` | 自动：`test_d0_no_console.py`（stdout/stderr=None 下 uvicorn `configure_logging` 不抛）；真实包仓外无句柄启动 `startup_streams={stdout_none:true,stderr_none:true}` | 修复；`page_ready=true`、`mount_stage=ready`、`server_stopped_clean=true` |
| R2 | 统一落盘边界：同目录临时写入→flush/fsync→校验→原子替换；失败保护原文件并清理临时文件 | 自动：`test_d0_host_atomic.py`（部分写入／fsync／replace 失败、成功无残留） | 修复；原文件字节不变，无半成品 |
| R3 | 修正 `triggerUiSave` 返回类型 | 自动：`npm run typecheck`（最终源码） | 修复；exit 0 |
| R4 | 原生 Windows npm/npx 解析；`--skip-frontend` 生效 | 自动：`test_d0_build_tools.py`；实跑默认完整构建 | 修复；默认 `build_d0.py` exit 0，解析到 `npm.CMD` |
| R5 | 保存失败保留待重试输入，旧库内容与版本不变；区分编辑态与读回 | 真实包：restart 阶段模拟失败后输入仍为 B、库仍为 A/v1；取消模拟后重试保存 B 成功 | 修复；`failure_input_kept_b=true`、`db_unchanged_after_failure=true` |
| R6 | 可靠等待实际桥函数就绪，处理迟到/超时；不用固定延时掩盖竞态 | 自动：`bridge.test.mjs`（已就绪／延迟注入／超时）；真实包 `session_api_ready=true` | 修复；`page_ready=true` |
| R7 | 人工与自动路径统一后缀约束，创建文件前校验 | 自动：`test_d0_host_atomic.py`（大小写/无后缀/其他后缀；对话框非 .docx 拒绝） | 修复；非 .docx 不创建文件 |
| R8 | 按 hive／体系结构检测 WebView2（含每用户 HKCU 路径） | 自动：`test_d0_webview2.py`（系统/每用户/64 位/缺失/0.0.0.0） | 修复；不修改真实注册表 |
| R9 | 诊断只记录布尔状态，不记录原始令牌；脱敏旧产物 | 自动：`test_d0_diag.py`；扫描本轮证据目录 | 修复；本轮 JSON 证据无 `launch_token`；旧 `jsdiag.json` 已脱敏 |
| R10 | 每项必需断言进入总体结果；失败/超时/清理失败非零；写入前读旧状态；跨进程重启；Word 走真实页面链路 | 自动：`test_d0_selftest.py`；真实包 first/restart/verify 三进程 | 修复；三阶段 `ok=true`、exit 0；`FAILED_CHECKS=[]` |

### 7.3 自动检查结果（最终源码，2026-10-10）

- `desktop/.venv/Scripts/python -m pytest desktop/tests -q`：**75 passed，2 warnings，exit 0**（首轮 37 项）。新增回归：`test_d0_no_console.py`、`test_d0_host_atomic.py`、`test_d0_webview2.py`、`test_d0_build_tools.py`、`test_d0_selftest.py`、`test_d0_bridge.py`、`test_d0_diag.py`；保留既有守卫与 SQLite 回滚测试，并修正端口占用线程异常收口。
- 剩余 2 个警告均为既有、非本轮缺陷：Starlette `testclient`/`httpx` 弃用、`sqlite3.version` 弃用。首轮的端口占用 `PytestUnhandledThreadExceptionWarning` 已随 `ServiceRun` 收口消失。
- `frontend` 下 `npm run typecheck`（vue-tsc）：**exit 0**。
- `node frontend/src/d0/bridge.test.mjs`：**OK bridge readiness regression tests**（也由 `test_d0_bridge.py` 调用）。
- 默认完整构建 `desktop/.venv/Scripts/python desktop/build_d0.py`：**exit 0**（日志 `build/desktop-d0/build-default.log`），前端构建与最终包目录分离。

### 7.4 包、运行环境与实测边界

- 前端构建产物：`build/desktop-d0/frontend/`（入口 `d0.html`、`assets/index-B8PpVevh.js` 前缀 SHA-256 `8ED60BB682B98792`，构建于 19:34），与最终包目录分离；包内同名资源一致。
- 最终包：`build/desktop-d0/package/KGNext-D0Verify/`（PyInstaller 6.22.3 onedir `--windowed`，102 个文件、约 45 MB，构建于 2026-10-10 19:45），EXE SHA-256 `0A69FA8C80A91EEB2BBB2A40ED21C33FADA42D83B28D3AA5F06D5034031B58B2`。默认完整构建入口 `build_d0.py` exit 0（`build/desktop-d0/build-default.log`）；`--skip-frontend` 也 exit 0（`build/desktop-d0/build-skipfrontend.log`）。
- **打包态实测（仓外、无控制台、无重定向）**：包复制到 `%TEMP%\opencode\d0-rev2\`，以“无继承标准句柄”方式启动（自检摘要 `startup_streams={"stdout_none": true, "stderr_none": true}`），first/restart/verify 三阶段 `ok=true`、exit 0；该次构建 EXE SHA-256 `4BF7A5E8BC843FE5D6C87F090DF8752E629019D84D00F2F948F07C67EF614015`（2026-10-10 19:35）。
- **最终包启动受限（环境，非代码缺陷）**：本机 Smart App Control 处于强制状态（`HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy\VerifiedAndReputablePolicyState=1`）。19:45 构建的最终 EXE 从任意仓外目录（temp 与用户主目录）启动均被应用程序控制策略阻止（`OSError [WinError 4551] 应用程序控制策略阻止了此文件`；bash 与 `Start-Process` 结果一致），而 19:35 构建（在已记录的那次启动中获准）仍可运行。修改 SAC 或全机安全策略不在本轮授权范围，故未更改；不能从当前结果推断所有新构建都会被拦。最终源码另有开发态真实窗口自检证据（下条），不替代最终包运行验收。
- **最终源码开发态实测（真实 WebView2 窗口，`desktop/.venv`）**：`d0_main.py --selftest` 三阶段（first/restart/verify）`ok=true`、exit 0，`page_ready=true`、`FAILED_CHECKS=[]`；产出 DOCX 与打包 rev2 输出逐字节一致（SHA-256 `10E68D60CD74D45B90A8BFF59A77BAD8132883ACA52567644D156D0D5EE14AAB`，14458 字节、ZIP 13 项、`testzip=None`）。
- Word 链：真实页面按钮 → `/api/probe/export` → 宿主 `save_docx`（预授权自动保存目录）；Windows Word（COM 自动化）打开 2 页 / 380 词，标题、教师、反思内容均在（人工全页目视未执行）。
- 数据位置：`%TEMP%\opencode\d0-rev2\data\data\d0_probe.db`（打包 rev2）与 `%TEMP%\opencode\d0-dev-final\data\...`（开发态），均独立于解包目录，`pkg/` 下无数据。
- 环境：Windows 11（win32，10.0.26200）、Python 3.12.10、WebView2 Runtime 154.0.4258.62、Node v26.10.0 / npm 11.19.1。
- 本轮结束后无残留 `KGNext-D0Verify`/`WINWORD` 进程；本轮 JSON 证据与诊断不含启动令牌。

### 7.5 D0-1 至 D0-7 当前判定

| 项目 | 代码 | 自动检查 | 真实窗口/包 | 人工 | 打包环境 |
| --- | --- | --- | --- | --- | --- |
| D0-1 | 已修复 | pytest 通过 | 仓外无控制台包（19:35 构建）`page_ready=true`、中文页面；最终包被 SAC 拦（环境） | 真人目视字体/DPI 未执行 | onedir 包，无 Vite/Python 依赖 |
| D0-2 | 已修复 | SQLite 重开读回通过 | 三进程重启：A/v1 → B/v2 读回一致 | 人工关闭按钮未执行 | 数据在独立用户目录 |
| D0-3 | 已修复 | CHECK 回滚、端口占用收口 | 模拟失败不报成功、旧值保留 | 磁盘写满等极端未执行 | 启动失败弹原生错误框 |
| D0-4 | 已修复 | 无/错误会话、错误 Host/Origin 拒绝 | 窗口内无会话 401、正常请求成功 | — | 无会话健康检查不暴露数据 |
| D0-5 | 已修复 | 生成器/ZIP/内容校验 | 页面导出→API→宿主保存成功 | 真人另存对话框、WPS 目视未执行 | 中文+空格路径 |
| D0-6 | 已修复 | 部分写入/fsync/replace 失败保护原文件 | 窗口取消/失败重试未验；对应证据为宿主自动测试 | 原生对话框取消/占用/重试未执行 | — |
| D0-7 | 已修复 | — | 仓外无句柄启动成功（19:35 构建）；最终包受 SAC 限制 | 干净机器、Win10 未执行 | WebView2 已装并正确检测；缺失分支未实测 |

### 7.6 人工未执行项与接续步骤

未执行（无真人 GUI 条件，按规格保留）：
1. 交互窗口真人关闭、窗口字体/布局/DPI 目视。
2. 原生另存对话框：选含中文+空格路径、取消、目标不可写/被占用、失败后重试。
3. Windows Word／WPS 全页目视（Word 仅 COM 自动化 2 页；WPS 未安装）。
4. WebView2 缺失分支、真正干净机器、Windows 10。

接续步骤（Codex）：
> 注意（环境）：已记录最终 EXE `0A69FA8C…` 被本机应用控制策略阻止，第二轮独立复审再次观察到该错误；不由此推断所有新构建必然被拦。最终包需在允许运行该包的环境中验证，不修改安全策略或尝试绕过。开发态验证仅提供源码运行证据。19:35 历史包位于 `%TEMP%\opencode\d0-rev2\pkg`（EXE SHA-256 `4BF7A5E8BC843FE5D6C87F090DF8752E629019D84D00F2F948F07C67EF614015`），保留其历史运行证据，不称为最终包的等价替代。
1. 使用包 `build/desktop-d0/package/KGNext-D0Verify/KGNext-D0Verify.exe`（可复制到任意非仓库目录）。
2. 直接双击（无控制台）确认 Vue 窗口与中文，关闭窗口确认无残留进程。
3. 在 Word 保存卡片点“生成并保存日计划 DOCX”，在原生对话框选含中文及空格的路径保存；用 Word 或 WPS 打开全页检查。
4. 分别触发取消、选择被占用/只读目标、失败后重试，核对无半成品、原文件不变。
5. 如需复核重启：`KGM_D0_AUTOSAVE_DIR=<dir> KGNext-D0Verify.exe --selftest --selftest-phase first --out <json>`，再 `--selftest-phase restart --expect-content "<A>" --expect-version <vA>`，最后 `--selftest-phase verify --expect-content "<B>" --expect-version <vB>`。

### 7.7 已修 / 未修

- OpenCode 本轮交付声称 R1–R10 全部已修；第二轮独立复审确认 R2–R9 及 R1 核心修复，R10 与失败路径清理仍须按审阅 §6 补齐，不将交付声称当成复审通过。
- 未修/未验：上列人工项与干净机器、Win10、WPS；D0 产品验收仍由 Codex 组织，本轮不宣布 D0 全部通过，不进入 D1。
- **更新（第三轮）**：R10 版本断言、R10 异常自检自动结束与 R1 启动失败／超时清理已按审阅 §6 补齐，证据见 [§8](#8-2026-10-10-第三轮r10-断言异常结束与-r1-清理补项)。§7 其余人工／环境未验项不变。

## 8. 2026-10-10 第三轮：R10 断言、异常结束与 R1 清理补项

本节由 OpenCode 在第三轮修复后追加，保留 §1–§7 的历史失败与未验。范围仅限审阅 §6 指定的三项（R10 版本断言、R10 异常自检结束、R1 启动超时／失败清理），未改前端、Word 生成器、一级技术栈，未做 D1／迁移／真实 AI／WebDAV，未暂存／提交／推送。

### 8.1 本轮修改文件

| 文件 | 改动 | 对应 |
| --- | --- | --- |
| `desktop/d0_driver.py` | 每次成功保存断言 `new_version = old_version + 1`（空库首次为 1），并核对 API 与独立 DB 的内容＋版本一致；新增 `save_a_version_advanced`、`save_a_api_db_consistent`、`failure_api_db_consistent`、`retry_version_advanced`、`retry_api_db_consistent`；每次保存记录 API/DB 版本到结果；窗口关闭职责交回调用方 | R10 版本断言 |
| `desktop/d0_main.py` | 新增 `_stop_service`（幂等，含 None）；`build_runtime` 初始化失败时停止已建服务并释放探针；新增 `close_selftest_windows` 与自检 watchdog；`run_interactive` 在错误框出现前先停止本轮服务；`run_selftest` 启动失败先停止服务，驱动异常经 `finally` 自动关窗并记 `selftest_window_closed`／`window_close_error` | R10 异常结束、R1 清理 |
| `desktop/tests/test_d0_driver_versions.py`（新增） | 直接执行 `drive_window` 的版本断言回归：版本未变／错误版本／API 与 DB 版本或内容不一致均判失败，正确路径判成功 | R10 版本断言 |
| `desktop/tests/test_d0_selftest.py`（扩展） | 驱动异常后无需人工即关窗结束、正常自检关窗、关窗失败仍为明确失败 | R10 异常结束 |
| `desktop/tests/test_d0_failure_cleanup.py`（新增） | 延迟 startup 超时、普通启动失败、初始化失败、正常退出四条清理路径；错误框在服务停止后才出现；`build_runtime` 失败释放服务＋探针 | R1 清理 |

未改前端（第二轮 `npm run typecheck` exit 0 仍适用）；`requirements-d0.lock.txt` 未修改。

### 8.2 R10 版本断言（对照审阅 §6.2）

- 首次保存：以写入前读到的旧版本为基准，要求 `new = old + 1`（空库旧版本视为 0，首次为 1），并要求 API 视图与独立 SQLite 读取的内容和版本两项都一致。
- 失败保留后重试：以失败后仍不变的旧版本为基准，要求重试结果 `new = old + 1`，并同样核对 API／DB 内容与版本一致。
- 现在“内容正确但版本未变”、“版本跳变”和“API／DB 不一致”都会置对应 check 为 False，经 `combine_ok` 使总体 `ok=false`、进程非零。本轮未发现真实 SQLite 版本错误；这是自检可信度修复，不写成业务数据曾出错。

### 8.3 R10 异常自检结束

- `drive_task` 的 `finally` 无条件调用 `close_selftest_windows(summary)`，因此驱动抛异常或正常结束时自检窗口都会被关闭，`webview.start()` 无需人工即可返回；关闭失败写入 `window_close_error` 并置 `selftest_window_closed=false`。
- 另有 300 s 上限的 watchdog：若 GUI 循环仍未结束，则强制关闭、写失败摘要并 `os._exit(3)`，避免无限等待（正常运行远早于此）。
- **2026-10-11 独立复审收窄：** 上述为设计意图；实际 watchdog 先同步关闭窗口，若 `destroy()` 本身阻塞，仍到不了强退。普通驱动异常已修，此极端限制为非阻塞 P3，见审阅 §7.1，不将 300 秒写成无条件硬保证。
- 实测（源码真实窗口，驱动注入异常）：`driver_error` 记录、`selftest_window_closed=true`、`server_stopped_clean=true`、进程 exit 3，约 6 秒内自动结束，无人工关窗。

### 8.4 R1 启动超时／失败清理（对照审阅 §6.2）

- `run_interactive` 与 `run_selftest` 在 `start_and_wait()` 失败后立即 `_stop_service()`：交互错误框在其后弹出，避免等待用户关闭模态期间服务继续启动；`finally` 再做一次幂等停止。
- `build_runtime` 在创建服务后、宿主 API 初始化失败时停止服务并释放 SQLite 引擎，不再只释放引擎。
- 这是函数级清理，不宣称“完整进程退出后仍遗留服务”；daemon 随主进程退出的既有行为不作为清理已完成的证据。

### 8.5 自动检查结果

- `desktop/.venv/Scripts/python -m pytest desktop/tests -q`：**92 passed，2 warnings，exit 0**（第二轮 75 项；本轮新增 17 项：`test_d0_driver_versions.py` 9、`test_d0_failure_cleanup.py` 5、`test_d0_selftest.py` 扩展 3）。剩余 2 个警告仍为既有 Starlette/httpx 与 `sqlite3.version` 弃用，非本轮缺陷。
- 前端未改，引用第二轮结果：`frontend` 下 `npm run typecheck` exit 0。
- 相关新增回归覆盖：版本未变／错误版本／API 与 DB 版本或内容不一致、驱动异常自动关窗、关窗失败明确失败、延迟 startup 超时清理、启动失败停止服务、初始化失败释放资源、正常退出清理。

### 8.6 源码真实窗口三进程复验（`desktop/.venv`，隔离合成数据目录）

| 阶段 | 写前读回 | 保存结果 | 结果 |
| --- | --- | --- | --- |
| first | 空库 | A/v1 保存，`save_a_version_advanced=true`、`save_a_api_db_consistent=true`，页面导出→宿主保存有效 DOCX | `ok=true`、exit 0 |
| restart | 新进程读 A/v1 | 模拟失败后输入仍为 B、库仍为 A/v1（`failure_input_kept_b`、`failure_kept_previous`、`failure_api_db_consistent` 均 true）；重试 B/v2（`retry_version_advanced`、`retry_api_db_consistent` true） | `ok=true`、exit 0 |
| verify | 第三进程读回 B/v2 | 只读校验 `verify_content`、`restart_content_matches`、`restart_version_matches` true | `ok=true`、exit 0 |

三阶段每项 check 均为 true（含本轮新增的 `selftest_window_closed=true`、`window_closed_without_error=true`）；每个进程结束时服务正常停止、无残留 `KGNext-D0Verify` 进程。DOCX 与历史一致：14458 字节、ZIP 13 项、`testzip=None`、SHA-256 `10E68D60CD74D45B90A8BFF59A77BAD8132883ACA52567644D156D0D5EE14AAB`。

### 8.7 最终包构建与无控制台运行

- 默认完整构建入口 `desktop/.venv/Scripts/python desktop/build_d0.py`：exit 0，前端产物 `build/desktop-d0/frontend/`（`index-B8PpVevh.js`）与包目录 `build/desktop-d0/package/KGNext-D0Verify/` 分离。
- 本轮包标识：`KGNext-D0Verify.exe` SHA-256 `3AC3D5ED12C507315DE727C5CDF1AB3BFA1DB2642452081D3879B00055702DD9`，10,578,103 字节；包目录 102 个文件；构建时间 2026-10-10T20:19:40。源码工作区 HEAD 仍为 `b3c5bbf`（D0 源码未提交）。
- **无控制台、无重定向运行证据**：包复制到仓外 `%TEMP%\opencode\d0-r3\pkg-r3`，以 `os.startfile`（不继承标准句柄）运行。自检摘要 `startup_streams={"stdout_none": true, "stderr_none": true}`；first/restart/verify 三阶段各 `ok=true`，`page_ready=true`，`server_stopped_clean=true`；验证空库 A/v1 → 失败保留 A/v1 → 重试 B/v2 → 第三进程读回 B/v2。
- **关于应用控制策略**：第二轮记录的最终 EXE `0A69FA8C…` 被本机应用控制策略阻止属已观察环境事实；本轮重建包 `3AC3D5ED…` 在未改系统安全设置、未换名规避的情况下成功启动，仅记录该具体包结果，不推断所有新构建均通过或旧包等价。

### 8.8 本轮已修 / 未修

- 已修（代码＋自动测试＋真实窗口证据）：R10 版本断言与 API／DB 一致性；R10 驱动异常自动结束（含关窗失败明确失败）；R1 启动超时／失败清理与错误框前停止服务。
- 未修／未验（不因本轮改变）：交互窗口真人关闭与字体/DPI 目视；原生另存对话框（中文+空格路径、取消、不可写/被占用、失败后重试）；Word 全页人工目视（Word 仅历史 COM 自动化 2 页）、WPS（未安装）；真正干净机器、Windows 10。D0-6 的取消／占用仍为宿主自动测试证据，未写成真实窗口流程已验。
- D0 产品验收仍由 Codex 组织；本轮不宣布 D0 全部通过，不进入 D1。D1 仍先落规格 §6 契约。
