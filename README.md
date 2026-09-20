# kindergarten-manager-next

面向单个幼儿园教师的教育工作支持系统，全新设计，不默认迁移旧系统代码或数据。

Architecture v1 已在本次需求澄清会话中由用户确认。目前仓库处于实施准备阶段，文档描述已确认的设计约束，不代表功能、部署或容量已经实现和验证。

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

当前没有可运行应用，不提供尚未验证的安装、启动或部署命令。架构文档落盘不授权安装依赖、创建数据库、修改现有服务或部署产品。
