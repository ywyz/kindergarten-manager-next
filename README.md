# kindergarten-manager-next

面向单个幼儿园教师的教育工作支持系统，全新设计，不默认迁移旧系统代码或数据。

Architecture v1 已确认。截至 2026-09-28，I1–I4 与 I5 Word 导出的片 1 已实现；I5 片 2–4 尚未开始。部署与容量仍未验证。

## 当前状态与下一步（2026-09-28）

- **已实现**：I1 账号与认证，I2 班级分配与有效日历，I3 日计划，I4 周计划（含确认），以及 I5 片 1「导出读取、版本钉住与模板映射纯逻辑」（`backend/app/services/export_read_service.py`、`backend/app/services/word_export_mapping.py` 及对应纯单元测试）。
- **未开始**：I5 片 2（固定模板 docx 生成）、片 3（API 与下载闭环）、片 4（隔离 Word 与浏览器验收）。路由、模板资产、生成依赖、前端导出入口与导出审计均未实施。
- **验证**：后端纯单元测试 425 项通过；I1 24、I2 56、I3 27、I4 52 项隔离真实 MySQL 集成测试在当前 head `20260924_i4_weekly_plans` 通过；前端 `npm run typecheck`、`npm run build` 通过（主包约 1.12 MB，Vite 给出非阻断体积告警）。历史细节见下文“历史验证”与 `docs/bootstrap/`。
- **待决定**：I5 §11.1–§11.6、§11.9 仍待用户决定；前端主包体积告警未处理，留待后续前端性能切片。
- **下一步**：向用户提交 I5 片 2 真正依赖的最小决策并请求授权，不自动开始 docx 生成。

## 文档入口

- [架构基线](ARCHITECTURE.md)：首版范围、技术栈、依赖与数据归属。
- [技术栈与数据库决策](docs/adr/0001-stack-and-database.md)。
- [后台任务与版本决策](docs/adr/0002-background-tasks-and-versions.md)。
- [部署、安全与恢复决策](docs/adr/0003-deployment-security-and-recovery.md)。
- 模块 Contract：[用户与班级](docs/modules/identity-and-class.md)、[提示词](docs/modules/prompts.md)、[AI Service](docs/modules/ai-service.md)、[日计划](docs/modules/daily-plans.md)、[周计划](docs/modules/weekly-plans.md)、[Word 导出](docs/modules/word-export.md)、[操作日志](docs/modules/audit-log.md)。
- [实施准备清单](docs/bootstrap/architecture-v1-readiness.md)：待定事项、验证要求与建议下一步。
- [仓库工作约束](AGENTS.md)。

## 已确认方向

Vue 3 / TypeScript / Vite / Element Plus 前端，Python / FastAPI / SQLAlchemy 2.x / Alembic 后端，MySQL 8.4 / InnoDB 数据库。部署目标为 `ssh aliyun` 对应服务器，复用 Caddy；独立 Python 工作进程执行数据库持久任务。

首版覆盖账号与班级管理、个人 AI 配置与提示词、日计划、全班周计划及固定 Word 模板导出。支持教师分日期备课、周计划自动更新与人工确认。约 30 人并发是待验证的容量目标。

早期骨架页面仅用于检查 Vue / TypeScript / Element Plus。AI、个人提示词、持久任务仍属于首版，按后续任务分步实现。Word 导出目前只完成读取与映射纯逻辑（片 1），docx 生成与下载闭环尚未开始。Word 原型证据仅限记录的 Ubuntu / LibreOffice 环境与固定案例，Microsoft Word 正式使用后反馈。

## 本地环境与目录

- `frontend/`：npm 项目，`package-lock.json` 锁定依赖；`src/App.vue` 为最小页面。
- `backend/`：uv 项目，`uv.lock` 锁定依赖，`.venv/` 隔离 Python 环境；`app/main.py` 为启动入口。
- `backend/migrations/`：Alembic 环境与 revision；`versions/` 已包含 I1–I4 迁移脚本，当前 head 为 `20260924_i4_weekly_plans`。

需要已有 Node.js（22.12+ 的 22 系列，或 24+）、npm、Python 与 uv。本次本机使用 Node 26.8.1、npm 12.0.2、uv 0.12.7、Python 3.14.7；后端 `.python-version` 选择 3.14。下列命令不安装系统工具；`UV_PYTHON_DOWNLOADS=never` 禁止自动下载 Python，若本机没有该解释器会停止。项目声明 Python >=3.12，其他版本尚未做本地启动验证。

## 安装与启动

从仓库根目录分别在两个终端运行。首次安装依赖需要访问包仓库，无需 MySQL、AI 密钥或服务器。

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

若本机现有代理访问包仓库返回 `503 Forwarding failure`，本次安装通过仅对 npm 官方仓库直连解决；后续锁定安装可使用 `NO_PROXY=registry.npmjs.org no_proxy=registry.npmjs.org npm ci --registry=https://registry.npmjs.org`；不修改全局代理或 npm 配置。

打开 <http://127.0.0.1:5173>，点击“检查交互”应更新计数。前端目前不调用后端，因此不需要 CORS 或 API 代理。健康检查为 <http://127.0.0.1:8000/health>，应返回 HTTP 200 和 `{"status":"ok"}`；它只表示 API 进程存活，不代表数据库就绪。两个终端分别按 Ctrl+C 停止。

Vite 开发服务器固定监听 `127.0.0.1:5173`，预览服务器固定监听 `127.0.0.1:4173`；端口占用时直接失败，不自动换端口。后端也只按上述命令监听回环地址。不要为了本地检查改为 `0.0.0.0`。

## 配置约定

无需创建 `.env` 即可启动骨架。需要覆盖配置时直接设置进程环境变量，例如：

```bash
export APP_DISABLE_DOTENV=1
export DATABASE_URL=mysql+pymysql://user:pass@127.0.0.1:3306/kindergarten_dev
export COOKIE_SECURE=false
export ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

实际 `.env`、虚拟环境、依赖和构建输出已加入 `.gitignore`。I1 没有单独的 session secret 配置项。

后端配置优先级为进程环境变量 > `backend/.env`（如未禁用）> 代码默认值。`APP_NAME` 控制 API 标题；`DATABASE_URL` 默认空，仅迁移入口需要，健康检查不会解析或连接它。数据库连接采用 `mysql+pymysql`；不把连接地址写入日志或 `alembic.ini`。

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

启动与构建成功仅是骨架检查，不是登录、权限、日历、计划保存、Word 导出、真实 AI、持久任务或容量验收。骨架阶段没有部署命令，也没有连接 `ssh aliyun`。

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
