# kindergarten-manager-next

面向单个幼儿园教师的教育工作支持系统，全新设计，不默认迁移旧系统代码或数据。

Architecture v1 已确认。I1–I4 与 I5 Word 导出的片 1–3 已实现；2026-10-02 已最小修复导出范围竞态并部署独立远程验收实例。I5 片4的真实浏览器落盘与 Office／WPS 逐页验收仍待 Trae Work 执行，AI、容量和备份恢复分别待验证。

## 当前状态与下一步（2026-10-02）

- **验收入口**：[kg-next-verify.ywyz.tech](https://kg-next-verify.ywyz.tech)。SSH 密钥连接 `root@bwh.ywyz.tech`；独立目录、内部 API、独立 MySQL 8.4.11 与 Caddy HTTPS，保留实例供验证，不使用本机 WSL 验收服务器。
- **已修复**：日／周导出期间改范围使旧响应立即失效，日计划模式变化同样处理；清空旧缺项确认与错误，旧 finally 不清除新请求 loading。源提交 `2cb8d81`；18 项可控延迟检查、前端 typecheck/build、Windows及服务器533项后端单测通过，服务器 I5 集成30项通过、0skip。两个锁文件未变。
- **环境门槛**：Windows 10／11／Server 2022／Server 2025 与 Office 2010 以上桌面 Word／WPS 文字任一组合完成全部必需案例即可通过；不要求所有组合验证。实际下载、哈希和全部页面检查不可省略，见 [当前验收口径](docs/specs/i5-validation-environment.md)。
- **下一步**：将 [Trae Work 提示词](docs/bootstrap/i5-trae-work-prompt-2026-10-02.md)交给 Trae Work。私密测试口令仅在仓库外与服务器 root 配置目录，不入 Git。案例 ID 使用 R01–R16，初始数据见 [夹具清单](docs/bootstrap/i5-remote-fixtures-2026-10-02.json)。
- **状态与边界**：[本轮修复部署记录](docs/bootstrap/i5-remote-validation-2026-10-02.md)分层记录自动检查、HTTPS/API、下载和桌面证据。当前尚不能宣布 I5 片4完成；§11.9与后续 AI Service／提示词／持久任务规格仍按原范围收口，不自动实现。

## 历史状态（2026-10-01，环境限制已由新口径替代）

- **已实现**：I1 账号与认证，I2 班级分配与有效日历，I3 日计划，I4 周计划（含确认），I5 片 1「导出读取、版本钉住与模板映射纯逻辑」，I5 片 2「固定模板 docx 生成」（`word_export_docx.py` + 受控模板 + `lxml`），以及 I5 片 3「API 与下载闭环」（`routers/exports.py` 两条导出路由与 409/上限/审计/文件名/警示头闭环、`api.ts` 二进制下载与 `DailyPlanView`/`WeeklyPlanView`/`WeeklyPlanListView` 导出入口，2026-09-29 已确认 §11.1②/§11.5A/§11.6①）。
- **已授权、待运行环境与桌面能力预检后执行**：I5 片 4。2026-09-29 用户把开发与验收基线改为 Windows 11 Pro 主机 + WSL2 Ubuntu + Office 365／Microsoft 365 随附的 Windows 桌面版 Microsoft Word；WSL2 运行 MySQL/API/Vite/测试，Windows 浏览器完成真实下载，Word 完成 W1–W6 打开与逐页版式验收。
- **验证**：2026-10-01 依赖恢复后复跑全绿——后端纯单元测试 533 项通过（其中片 3 定向 schema/路由 80 项、片 1–3 I5 定向共 170 项）；I5 集成 `tests.integration.test_i5_export_api` 30 项通过、0 skip（mysql:8.4.11 + InnoDB，白名单库 + I5 专用 guard，head `20260924_i4_weekly_plans`，容器用后删除）；I1 24、I2 56、I3 27、I4 52 项隔离 MySQL 结果沿用之前记录；前端 `npm run typecheck`、`npm run build` 通过（主包 1135.42 kB，Vite 既有非阻断体积告警）；隔离 API/Vite 启动、`/api` 代理、合法口令登录与 `Cache-Control` 已核验。Windows 浏览器下载与 Word 逐页验收待人工（交接表见 [片 4 验证记录](docs/bootstrap/i5-slice4-validation-2026-10-01.md)）。历史细节见 `docs/bootstrap/`。
- **下一步**：按 [2026-10-01 完整提示词](docs/bootstrap/i5-slice4-opencode-prompt-2026-10-01.md)恢复锁定项目依赖并做分层预检，完成独立自动检查后执行 Windows 浏览器真实下载与 W1–W6 Word 验收。OpenCode 缺少桌面能力时准备人工交接并暂停对应阶段，保留“待人工验收”状态；LibreOffice 不替代 Word 门槛。
- **待决定**：I5 §11.9（确认后日历/学期变化的导出布局）留到日历影响处理能力开放前；前端主包体积告警未处理，留待后续前端性能切片。

## 文档入口

- [架构基线](ARCHITECTURE.md)：首版范围、技术栈、依赖与数据归属。
- [技术栈与数据库决策](docs/adr/0001-stack-and-database.md)。
- [后台任务与版本决策](docs/adr/0002-background-tasks-and-versions.md)。
- [部署、安全与恢复决策](docs/adr/0003-deployment-security-and-recovery.md)。
- 模块 Contract：[用户与班级](docs/modules/identity-and-class.md)、[提示词](docs/modules/prompts.md)、[AI Service](docs/modules/ai-service.md)、[日计划](docs/modules/daily-plans.md)、[周计划](docs/modules/weekly-plans.md)、[Word 导出](docs/modules/word-export.md)、[操作日志](docs/modules/audit-log.md)。
- [实施准备清单](docs/bootstrap/architecture-v1-readiness.md)：待定事项、验证要求与建议下一步。
- [仓库工作约束](AGENTS.md)。
- [WSL 与 Windows 验收能力报告](docs/bootstrap/wsl-windows-validation-review-2026-10-01.md)。
- [I5 片 4 完整 OpenCode 提示词](docs/bootstrap/i5-slice4-opencode-prompt-2026-10-01.md)。

## 已确认方向

Vue 3 / TypeScript / Vite / Element Plus 前端，Python / FastAPI / SQLAlchemy 2.x / Alembic 后端，MySQL 8.4 / InnoDB 数据库。当前 I5 验收部署目标为 SSH `root@bwh.ywyz.tech`，复用 Caddy；系统设计仍由独立 Python 工作进程执行数据库持久任务，尚未实现。

首版覆盖账号与班级管理、个人 AI 配置与提示词、日计划、全班周计划及固定 Word 模板导出。支持教师分日期备课、周计划自动更新与人工确认。约 30 人并发是待验证的容量目标。

早期骨架页面仅用于检查 Vue / TypeScript / Element Plus。AI、个人提示词、持久任务仍属于首版，按后续任务分步实现。Word 导出已完成片1–3与本轮范围竞态修复，片4的Trae Work真实下载与Word／WPS逐页验收待执行。旧Ubuntu／LibreOffice原型只保留为历史补充证据。

## 本地开发与历史环境（不是当前验收服务器）

以下 WSL 采集和启动说明保留为 2026-10-01 开发记录。当前 Windows checkout 为 `C:\Users\admin\code\kindergarten-manager-next`，PowerShell 7.6.6 在 `D:\Program Files\PowerShell\7\pwsh.exe`；本轮本地恢复依赖用于修复检查，产品验收访问远程 HTTPS。不要求安装或恢复 WSL。

2026-10-01 只读检查确认当前为 WSL2 Ubuntu 26.04.1（内核 `6.18.33.2-microsoft-standard-WSL2`）；Windows `EditionID=Professional`，25H2，build `26200.9457`；Office Click-to-Run 安装版本与 Word 文件版本均为 `16.0.20326.20158`，Office 平台为 x64。安装信息不证明 Word 可交互使用或产品版式通过。后端 `.venv`、前端 `node_modules` 本轮检查时缺失，尚未恢复或运行测试。

仓库、Python／uv、Node／npm、Docker／MySQL、API、Vite 和自动测试继续在 WSL2 内运行；Windows 浏览器与桌面版 Word 用于产品验收。浏览器版本、WSL 工具版本、Word 界面显示的版本／build／更新渠道和桌面能力在实际验收时重新确认。

- `frontend/`：npm 项目，`package-lock.json` 锁定依赖；`src/App.vue` 为登录／待分配／教师／管理员／设置页面入口，业务页面在 `src/views/`。
- `backend/`：uv 项目，`uv.lock` 锁定依赖，`.venv/` 隔离 Python 环境；`app/main.py` 为启动入口。
- `backend/migrations/`：Alembic 环境与 revision；`versions/` 已包含 I1–I4 迁移脚本，当前 head 为 `20260924_i4_weekly_plans`。

需要已有 Node.js（22.12+ 的 22 系列，或 24+）、npm、Python 与 uv。2026-09-21 旧环境记录为 Node 26.8.1、npm 12.0.2、uv 0.12.7、Python 3.14.7，不代表当前 WSL 工具版本；后端 `.python-version` 选择 3.14。下列命令不安装系统工具；`UV_PYTHON_DOWNLOADS=never` 禁止自动下载 Python，若本机没有该解释器会停止。项目声明 Python >=3.12，其他版本尚未做本地启动验证。

## 安装与启动

从仓库根目录分别在两个终端运行。首次恢复锁定依赖需要访问包仓库；仅进程启动和 `/health` 检查无需 MySQL、AI 密钥或服务器。登录、班级、计划与导出依赖已迁移的 MySQL 测试库，片 4 使用下方提示词的隔离环境，不连接真实业务库。

后端：

```sh
cd backend
UV_PYTHON_DOWNLOADS=never uv sync --locked
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

前端：

```sh
cd frontend
npm ci --registry=https://registry.npmjs.org
npm run dev
```

旧环境曾遇到代理访问包仓库返回 `503 Forwarding failure`，当时通过仅对 npm 官方仓库直连解决；后续锁定安装可使用 `NO_PROXY=registry.npmjs.org no_proxy=registry.npmjs.org npm ci --registry=https://registry.npmjs.org`；不修改全局代理或 npm 配置。

Windows 浏览器打开 <http://127.0.0.1:5173>。当前前端会调用 `/api`，Vite 已代理到 `http://127.0.0.1:8000`；注册／登录及业务操作需要显式配置的隔离 MySQL 和现有迁移，写请求的 Origin 必须满足后端配置。健康检查 <http://127.0.0.1:8000/health> 应返回 HTTP 200 和 `{"status":"ok"}`，仅证明 API 存活，不代表数据库就绪或业务通过。两个终端分别按 Ctrl+C 停止。

Vite 开发服务器固定监听 `127.0.0.1:5173`，预览服务器固定监听 `127.0.0.1:4173`；端口占用时直接失败，不自动换端口。后端也只按上述命令监听回环地址。不要为了本地检查改为 `0.0.0.0`。

## 配置约定

无需创建 `.env` 即可启动 API 进程并检查 `/health`；业务接口仍需要数据库配置。需要覆盖配置时直接设置进程环境变量，例如：

```bash
export APP_DISABLE_DOTENV=1
export DATABASE_URL=mysql+pymysql://user:pass@127.0.0.1:3306/kindergarten_dev
export COOKIE_SECURE=false
export ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

实际 `.env`、虚拟环境、依赖和构建输出已加入 `.gitignore`。I1 没有单独的 session secret 配置项。

后端配置优先级为进程环境变量 > `backend/.env`（如未禁用）> 代码默认值。`APP_NAME` 控制 API 标题；`DATABASE_URL` 默认空，迁移和访问持久数据的业务接口需要它，健康检查不会连接数据库。数据库连接采用 `mysql+pymysql`；不把连接地址写入日志或 `alembic.ini`。

前端采用 Vite 配置约定，`VITE_APP_TITLE` 为公开的页面标题，缺省使用代码默认值；进程环境优先于环境文件。`VITE_*` 会进入浏览器产物，绝不能存放密钥。修改后重启开发服务器；构建产物需重新构建。

## 本地检查与迁移边界

```sh
cd frontend
npm run typecheck
npm run build
# 可选：本地查看构建产物，结束后 Ctrl+C
npm run preview
```

后端启动后可在另一个终端检查（Python 标准库，无额外测试依赖）：

```sh
cd backend
uv run --locked python -c 'import json, urllib.request; r = urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5); assert r.status == 200; assert json.load(r) == {"status": "ok"}; print("health OK")'
# 只读取迁移目录；当前 head 为 20260924_i4_weekly_plans，不连接数据库
uv run --locked alembic heads
```

以下段落记录 2026-09-21 骨架阶段的历史边界，已被后续 I1–I4 实施取代：当时不创建数据库、不生成 revision、不运行任何迁移，`target_metadata=None`。当前 `versions/` 已含 I1–I4 迁移，实际迁移按各切片授权在隔离库执行；应用启动仍不执行建表或迁移。

仅启动与构建成功属于进程／构建检查，不是登录、权限、日历、计划保存、Word 导出、真实 AI、持久任务或容量验收。骨架阶段没有部署命令，也没有连接 `ssh aliyun`。

配置参考：[Vite](https://vite.dev/guide/)、[FastAPI](https://fastapi.tiangolo.com/)、[Alembic](https://alembic.sqlalchemy.org/en/latest/tutorial.html)。

## 历史验证（2026-09-21 至 2026-09-22）

以下 I2 收尾检查与骨架检查均为历史记录，保留用于追溯；它们不代表 I3/I4/I5 或当前 head 的验证结果。当前状态以上文“当前状态与下一步”为准。

### I2 收尾检查（2026-09-22，历史）

I2 已完成本轮实施及直接相关验证，停止于 I2。最新范围、真实 MySQL 及浏览器证据见 [I2 实施与验证记录](docs/bootstrap/i2-implementation-status.md)。下文 2026-09-21 骨架检查为历史记录。

后端单元测试：

```bash
cd backend
export APP_DISABLE_DOTENV=1
unset DATABASE_URL
.venv/bin/python -m unittest discover -s tests/unit -v
# Ran 45 tests ... OK
```

后端集成测试（仅隔离测试库）：

```bash
export APP_DISABLE_DOTENV=1
export I2_TEST_ALLOW_DESTRUCTIVE=yes
export I2_TEST_DATABASE_URL=mysql+pymysql://kg_test_i2:...@127.0.0.1:13384/kindergarten_test_i2
cd backend
.venv/bin/python -m unittest tests.integration.test_class_assignment tests.integration.test_terms_calendar tests.integration.test_i2_concurrency tests.integration.test_i2_remaining -v
# Ran 56 tests ... OK
```

前端：

```bash
cd frontend
npm run typecheck   # exit 0
npm run build       # exit 0
```

新增 `tests/integration/test_i2_remaining.py` 覆盖 A-E：真实 `chinesecalendar` 调休/假日、学期范围变更保留/移除/周号、预览过期、密码重置与分配竞争、子进程重启读持久日历、`plans_started_at` 门槛。详见 `backend/README-I2.md`。


## 2026-09-21 骨架检查（历史）

- `npm run typecheck`、`npm run build` 通过，生成本地 `dist/`。
- `npm run dev` 在回环地址启动；首页、`/src/main.ts`、`/src/App.vue` 均返回 HTTP 200，入口及组件内容符合预期。
- 后端在数据库地址为空时启动，`/health` 返回 HTTP 200 和预期 JSON；OpenAPI 标题验证了环境变量覆盖，业务路由仅 `/health`。
- `.env.example` 配置读取检查及 `alembic heads` 通过，后者无 revision 输出；未运行迁移。
- 本次启动的前后端临时进程已停止。没有可用浏览器连接，未执行浏览器点击或视觉检查；这部分仍需按上面的操作人工检查。

（历史）骨架阶段的下一步是另行授权实施用户与班级、有效日历及手工日计划保存的最小切片；该阶段停止于骨架，后续 I1–I4 与 I5 片 1 已实施。

## I1 账号与认证（历史说明）

I1（账号注册、登录与待分配访问）已在 `backend/` 实现，说明见 [backend/README-I1.md](backend/README-I1.md)。上文“本次实际检查”中的骨架启动结果属于历史验证，不代表 I1 的登录、权限或数据库行为已验收。
