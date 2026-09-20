# ADR 0001 技术栈与数据库选型

状态：已接受。用户在本次会话中接受 MySQL 8.4 推荐，随后确认部署与任务方案；本文记录既有决定，不构成安装或迁移授权。

## 背景

项目为 clean-slate 实现。初始 AGENTS.md 包含 SQLite 候选，但用户要求比较 PostgreSQL 与 MySQL，并更正部署目标为 `ssh aliyun`。该服务器只读检查发现已有 `mysql:8.4` 容器；小内存且与现有应用共存，需要考虑运维成本。

业务要求包括多人保存、周计划唯一性、可恢复删除、版本确认，以及能够恢复的后台 AI 任务。约 30 人并发是验证目标，不是选型即能兑现的保证。

## 决策

- 前端采用 Vue 3、TypeScript、Vite、Element Plus。
- 后端采用 Python、FastAPI、SQLAlchemy 2.x、Alembic。
- 首版业务数据库采用 MySQL 8.4 / InnoDB，替代 SQLite 候选。
- 优先评估复用现有 MySQL 实例；是否实际复用仍待部署前核查。
- 若复用，使用独立数据库、低权限账号、迁移及备份流程，不共享或导入旧系统业务表。

不同时支持多个业务数据库作为首版需求；不因服务器已有旧应用而继承其 schema、流程或代码。

## 比较与原因

PostgreSQL 和 MySQL / InnoDB 都支持事务、行锁及 `SKIP LOCKED`，都能用于任务领取。PostgreSQL 可用部分唯一索引直接表达“同班同学期同周仅一份未删除计划”；MySQL 可通过生成列与唯一索引表达，具体表设计在实施规格中确定。

现有 MySQL 8.4 实例减少了额外部署另一数据库服务的需要。在当前服务器条件及未发现 PostgreSQL 专属业务需求的前提下，选择 MySQL。若是空服务器且运维条件相同，PostgreSQL 的条件唯一性表达会更直接，但这不足以在当前环境新增另一数据库服务。

此决定不宣称 MySQL 更快或更省内存，也不证明现有实例可安全复用。

## 后果与边界

- SQLite WAL 和 SQLite 在线备份建议失效，不能作为实现默认值。
- 保存业务数据与登记任务须使用同一事务；AI 网络等待和 Word 生成不放在长数据库事务内。
- 复用实例会共享数据库进程资源、故障与升级影响，需要核查而非静默接受。
- 数据库补丁版本、连接池、任务并发及内存参数在实施前根据环境确定。
- MySQL 一致性备份及恢复纳入 ADR 0003，不以容器 healthy 状态替代验证。

## 参考

- [PostgreSQL 条件唯一索引](https://www.postgresql.org/docs/current/indexes-partial.html)。
- [PostgreSQL SELECT 与 SKIP LOCKED](https://www.postgresql.org/docs/current/sql-select.html)。
- [MySQL 8.4 锁定读取](https://dev.mysql.com/doc/refman/8.4/en/innodb-locking-reads.html)。
- [MySQL 8.4 索引](https://dev.mysql.com/doc/refman/8.4/en/create-index.html)。
