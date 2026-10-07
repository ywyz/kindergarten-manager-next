# kindergarten-manager-next

面向幼儿园教师的教育工作支持系统，全新设计，不默认迁移旧系统代码或数据。Architecture v1 已确认：Vue 3／TypeScript／Vite／Element Plus，Python／FastAPI／SQLAlchemy 2.x／Alembic，MySQL 8.4／InnoDB。

## 当前状态（2026-10-07）

- I1–I4 已实现；I5 手工日／周计划 Word 导出已完成实现、自动验证及已实现链路的产品验收，见 [I5 正式收口](docs/bootstrap/i5-final-closeout-2026-10-03.md)。完整 W6 非空材料仍归后续材料切片必需补验。
- AI 基础配置与提示词 1A／1B／1C 已实现并于 2026-10-05 部署。实际运行源与迁移见 [部署结果](docs/bootstrap/ai-slice1abc-deployment-result-2026-10-05.md)，不能仅以仓库 HEAD 识别运行内容。
- [Windows 验收报告](docs/bootstrap/ai-slice1c-desktop-validation-2026-10-05.md)已补充至 2026-10-07。方案 A 已获确认：可以接受教师已查看勾选的同契约默认修订；较新默认仍保留更新状态。真实契约演进及缺／错主密钥相关子例仍受阻，尚未全通过。
- [验收夹具真库复审](docs/bootstrap/ai-slice1c-fixture-mysql-review-2026-10-07.md)已通过：本片 37 项含 14 项真库全部实跑，零 skip；本机专用容器已停止并保留数据。用户已授权本轮提交／推送后按[远程准备清单](docs/bootstrap/ai-slice1c-fixture-remote-preparation-plan-2026-10-07.md)准备独立正常 v1 基线；真实 Windows 子例仍待补验。transport、worker、业务 AI、材料、容量及备份恢复尚未完成，不自动启动其他切片。

## 文档入口

- [文档与报告索引](docs/bootstrap/README.md)：当前报告、有效提示词及保留证据。
- [当前待办与验证门槛](docs/bootstrap/architecture-v1-readiness.md)。
- [架构基线](ARCHITECTURE.md)、[技术栈与数据库 ADR](docs/adr/0001-stack-and-database.md)、[任务与版本 ADR](docs/adr/0002-background-tasks-and-versions.md)、[部署安全与恢复 ADR](docs/adr/0003-deployment-security-and-recovery.md)。
- [AI 协同实施规格索引](docs/specs/ai-capabilities-implementation.md)、[手工计划规格](docs/specs/manual-plans-and-word-export.md)、[Word 导出规格](docs/specs/word-export-implementation.md)。模块 Contract 在 `docs/modules/`。
- [仓库工作约束](AGENTS.md)。业务代码由 OpenCode 唯一写入；协调者负责文档、只读审阅与证据整合。

## 本地开发

`frontend/` 使用 npm 和 `package-lock.json`；`backend/` 使用 uv、`uv.lock` 和项目 `.venv`。前端 Node 版本要求以 [package.json](frontend/package.json) 为准；后端 Python 要求见 [pyproject.toml](backend/pyproject.toml)，默认解释器由 `.python-version` 指定。

分别在两个终端恢复锁定依赖并启动：

```sh
cd backend
UV_PYTHON_DOWNLOADS=never uv sync --locked
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```sh
cd frontend
npm ci --registry=https://registry.npmjs.org
npm run dev
```

前端访问 `http://127.0.0.1:5173`，`/api` 代理至 `http://127.0.0.1:8000`。开发端口固定为 5173，预览端口为 4173；端口占用时失败。`/health` 返回 200 只证明 API 存活，业务接口需要显式配置并已迁移的 MySQL。应用启动不建表、不执行迁移。

配置优先级为进程环境变量 > `backend/.env` > 默认值；`APP_DISABLE_DOTENV=1` 禁用环境文件。`DATABASE_URL` 默认为空，业务连接使用 `mysql+pymysql`。本地 HTTP 登录需设置 `COOKIE_SECURE=false`，写请求的 Origin 必须满足 `ALLOWED_ORIGINS`；HTTPS 实例保留安全 cookie。AI 主密钥通过受保护配置注入，缺失时手工链路仍应可用。实际凭证、`.env` 和密钥不得入 Git；`VITE_*` 会进入浏览器产物，不能存密钥。

## 检查与验收

前端基本检查：

```sh
cd frontend
npm run typecheck
npm run build
```

后端无数据库单元检查（先清除继承的数据库、主密钥和集成测试配置）：

```sh
cd backend
APP_DISABLE_DOTENV=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests/unit -t . -q
uv run --locked alembic heads
```

当前仓库迁移 head 为 `20261003_ai1a_config_prompts`。`alembic heads` 读取迁移目录，不证明数据库已升级。真实 MySQL 集成检查按各片 guard 与具体授权在隔离库执行。

产品验收访问独立远程 HTTPS 实例，口径见 [验收环境规格](docs/specs/i5-validation-environment.md)。Windows 浏览器真实下载及桌面 Word／WPS 全部页面检查是导出验收的必要部分。编译、单元测试、OOXML 检查和历史原型均不能替代产品验收。
