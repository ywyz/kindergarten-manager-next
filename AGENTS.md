
# kindergarten-manager-next

## 当前阶段

本仓库是 kindergartenManager 的全新实现。

当前处于：

**Architecture v1 已确认 / 分片实施与产品验收阶段**

I1–I4 与 I5 Word 导出片 1–3 已实现；2026-10-03 已正式收口 I5 当前已实现链路产品验收，完整 W6 非空材料移交后续材料切片必需补验。实现、自动测试与产品验收状态分别记录，不相互替代。

当前有效架构见 `ARCHITECTURE.md`，决策原因见 `docs/adr/`，模块 Contract 见 `docs/modules/`。

架构确认不等于代码、部署或生产操作授权；按用户当前任务范围执行。

## 核心原则

这是一个 clean-slate 项目。

旧 kindergartenManager 仓库仅作为：

* 业务行为参考
* Word 模板参考
* 已验证规则参考
* 历史经验参考

不得因为旧代码“已经存在”就复制或迁移。

默认策略是重新设计；只有经过明确审查后，才允许复用旧代码。

## 当前产品方向

面向幼儿园教师的教育工作支持系统。

采用前后端分离架构。

Architecture v1 已确认技术栈：

Frontend:

* Vue 3
* TypeScript
* Vite
* Element Plus

Backend:

* Python
* FastAPI
* SQLAlchemy 2.x
* Alembic
* MySQL 8.4 / InnoDB

SQLite 候选方案已被已确认的数据库 ADR 替代，不得继续作为实现默认值。不得自行扩展技术栈。

## 已知核心业务能力

当前需要重点考虑：

* 用户系统
* AI Service
* 提示词系统
* 每日活动计划
* 周计划

周计划依赖前述多个基础能力，因此不得将周计划设计为孤立模块。

## Agent 权限

Agent 不拥有产品需求最终解释权。

不得：

* 自行增加业务需求
* 自行改变教师工作流程
* 为技术便利改变产品行为
* 主动重构无关功能
* 主动扩大当前任务范围
* 为“架构更先进”而增加技术组件

遇到不确定的产品行为，应明确列出，不得自行猜测。

## Skills / MCP 临时规则

Skills / MCP 的审计约束继续有效，不因进入实施或迁移到 WSL2 自动解除。

在完成 Skills / MCP Audit 之前：

* 不得为了任务主动安装新的 Skill
* 不得主动安装新的 MCP Server
* 不得因为全局配置中存在某个 Skill/MCP 就默认认为本项目必须使用
* 简单文件搜索、Git、测试等普通任务不要求使用知识图谱工具
* 对已有 Skill/MCP 的处理必须先审计，再决定 KEEP / DISABLE / REMOVE-CANDIDATE

## Architecture Governance

ARCHITECTURE.md 只描述当前有效的系统级架构事实。

单一 Feature 不得自行修改 ARCHITECTURE.md。

如果某个任务要求改变：

* 一级技术栈
* 层级依赖方向
* 模块边界
* 数据权威来源
* 模块通信机制

应停止实现并提出 ADR 草案。

ADR 未确认前不得实施架构变更。

## 文档职责

* `ARCHITECTURE.md`：当前系统架构事实
* `docs/adr/`：重要架构决策及其原因
* `docs/modules/`：模块边界与 Contract
* `docs/specs/`：具体 Feature 规格
* `docs/bootstrap/`：项目启动阶段的审计和临时报告

AGENTS.md 自身应保持简短，不作为完整项目百科全书。

## 当前最高优先级

2026-10-05 用户授权完成 1A＋1B＋1C 远程部署、旧测试实例归档清理及 commit／push。当前运行源与迁移见 `docs/bootstrap/ai-slice1abc-deployment-result-2026-10-05.md`。2026-10-07 Windows 补验与收尾报告已交付，见 `docs/bootstrap/ai-slice1c-desktop-validation-2026-10-05.md`；用户确认方案 A：可接受已查看勾选的同契约默认修订，新默认仍保留更新状态，旧目标行为不再作为修复阻塞。真实 v2/v3 与缺／错主密钥夹具方案及 OpenCode 工具提示词见 `docs/bootstrap/ai-slice1c-fixture-plan-2026-10-07.md`，隔离真库复审见 `docs/bootstrap/ai-slice1c-fixture-mysql-review-2026-10-07.md`：两项加固及14项真库已通过，本机专用容器已停止并保留数据。用户已授权提交／推送及远程准备，独立实例与正常v1基线已完成并实际恢复，见 `docs/bootstrap/ai-slice1c-fixture-remote-preparation-result-2026-10-07.md`；桌面交接见 `docs/bootstrap/ai-slice1c-fixture-windows-handoff-2026-10-07.md`，契约发布／密钥故障及Windows补验仍待阶段授权；相关子例仍未补验，不宣布全通过，不启动其他切片。

当前 I5 已实现链路收口见 `docs/bootstrap/i5-final-closeout-2026-10-03.md`。`docs/specs/ai-capabilities-implementation.md` 中 P1–P4 产品决定已确认，基础配置／提示词 1A／1B／1C 已实现并部署；其余 AI Service 调用、持久任务与材料切片规格已形成，仍待具体实现授权，不自动启动实现或部署。完整 W6 材料真实下载及逐页补验不可省略；继续采用 `docs/specs/i5-validation-environment.md` 的远程实例与 Windows／Word 或 WPS 口径，不使用本机 WSL 验收服务器。

业务代码由 OpenCode 唯一写入；协调、只读审阅和文档更新不另起业务实现者。后续按规格及当前任务范围执行，不自动启动实现或部署。

2026-10-02 用户明确授权本轮协调者直接最小修复两处导出范围竞态、部署验收实例并 commit／push；后续默认写入约束保持不变。

文档入口见 `docs/bootstrap/README.md`，待定事项与建议顺序见 `docs/bootstrap/architecture-v1-readiness.md`。不因后续任务重新开展环境全面审计，也不把旧项目功能当作新版需求。
