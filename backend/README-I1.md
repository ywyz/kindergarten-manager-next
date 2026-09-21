# Backend I1 说明

本目录包含 I1「账号注册、登录与待分配访问」的后端实现。

## 范围

- 注册：首个成功注册账号为管理员，后续为待分配教师。
- 登录/退出：基于 HttpOnly Cookie 的持久会话，不返回 token 到 JSON。
- 本人设置：修改姓名、修改密码（旧会话全部失效）。
- 管理员：教师账号列表与密码重置（目标全部会话失效）。
- 服务器本地恢复命令：重置管理员密码。
- Alembic 迁移：创建账号、会话、首次管理员控制、操作记录表。

不包含班级/学期/日历/计划/AI/导出/工作进程。

## 本地开发配置

配置通过进程环境变量或 `backend/.env` 加载。需要覆盖时直接设置环境变量，例如：

```bash
export APP_DISABLE_DOTENV=1
export DATABASE_URL=mysql+pymysql://user:pass@127.0.0.1:3306/kindergarten_dev
export COOKIE_SECURE=false
export ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

密码哈希使用标准库 `hashlib.scrypt`，不新增依赖。没有独立的 session secret 配置项。

## 隔离测试库准备（破坏性，只用于本地验证）

下面的命令会破坏目标库，**只能用于专门创建的隔离测试库**，不可在生产或共享业务库执行。

```sql
CREATE DATABASE kindergarten_test_i1 CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 隔离测试专用账号（集成测试运行用，非生产账号）
CREATE USER 'kg_test_i1'@'127.0.0.1' IDENTIFIED BY '...';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES, DROP ON kindergarten_test_i1.*
  TO 'kg_test_i1'@'127.0.0.1';

-- 单独授权给执行迁移的账号（需要 DDL 与 DML 权限）
CREATE USER 'kg_test_ddl'@'127.0.0.1' IDENTIFIED BY '...';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES, DROP ON kindergarten_test_i1.*
  TO 'kg_test_ddl'@'127.0.0.1';
```

> 注意：本段所有创建数据库、账号、授权、迁移与测试命令均尚未执行，必须根据你的环境另行授权和确认。

最小权限说明：
- 生产或日常运行账号仅需要目标库的 `SELECT/INSERT/UPDATE/DELETE`；本文档中的 `kg_test_i1`/`kg_test_ddl` 是隔离测试专用账号，不得用于生产。
- 隔离迁移与集成测试需要 `CREATE/ALTER/INDEX/REFERENCES/DROP`（`TRUNCATE` 依赖 `DROP`），同时 Alembic 与批量初始化需要 `SELECT/INSERT/UPDATE/DELETE`。
- 测试仅允许 `127.0.0.1/localhost` 和数据库名 `kindergarten_test_i1`。
- MySQL 8.4 中 `GRANT` 立即生效，不需要 `FLUSH PRIVILEGES`。

## 迁移（必须单独执行后再测试）

迁移需要能执行 DDL 的数据库账号，且必须显式指向隔离测试库。不要在生产或共享业务库上执行。

```bash
cd backend
export APP_DISABLE_DOTENV=1
export DATABASE_URL=mysql+pymysql://kg_test_ddl:...@127.0.0.1:3306/kindergarten_test_i1
.venv/bin/alembic upgrade head
```

## 运行服务

```bash
cd backend
export APP_DISABLE_DOTENV=1
export DATABASE_URL=mysql+pymysql://user:pass@127.0.0.1:3306/kindergarten_dev
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

前端通过 Vite 代理访问 `/api`。

## 管理员密码恢复

在服务器本地终端执行，不通过 Web 入口：

```bash
cd backend
export APP_DISABLE_DOTENV=1
export DATABASE_URL=mysql+pymysql://user:pass@127.0.0.1:3306/kindergarten_dev
.venv/bin/python -m app.cli reset-admin-password --username <管理员用户名>
```

按提示输入并确认新密码。该命令不创建账号、不改角色、不改变启用状态；
被停用的管理员仍可恢复密码并保持停用。成功后会撤销该管理员全部会话。

## 测试

不依赖数据库的单元测试（无需 MySQL）：

```bash
cd backend
export APP_DISABLE_DOTENV=1
unset DATABASE_URL
.venv/bin/python -m unittest discover -s tests/unit -v
```

集成测试需要隔离 MySQL 8.4 / InnoDB，且迁移已单独完成：

```bash
export APP_DISABLE_DOTENV=1
export I1_TEST_ALLOW_DESTRUCTIVE=yes
export I1_TEST_DATABASE_URL=mysql+pymysql://kg_test_i1:...@127.0.0.1:3306/kindergarten_test_i1
cd backend
.venv/bin/python -m unittest discover -s tests/integration -v
```

**本次未执行集成测试**，因为没有已授权并准备好的隔离 MySQL 8.4 测试库。不得以 SQLite 或 mock 替代 MySQL 并发验证。

## 限流与并发说明

- 单进程内存限流：注册按客户端 IP、登录按 IP 及用户名计数。当前实现里 `rate_limit_max_requests` 只在注册与登录路由使用，其他修改请求未计入该桶。
- 可配置参数（均为正整数，默认值见 `app/config.py`）：`rate_limit_window_seconds=60`、`rate_limit_max_requests=10`、`rate_limit_max_failures=20`、`rate_limit_max_keys=10000`、`session_ttl_seconds=43200`。
- 失败计数器 `rate_limit_max_failures` 用于登录失败等场景；该桶当前已记录失败次数并占用键容量，但尚未对未使用它的路由提供主动拦截。
- 首次管理员注册使用 `SELECT ... FOR UPDATE` 锁定固定控制行。
- 密码重置与改密在事务内撤销目标全部未撤销会话，并递增 `auth_version`。
- 认证写操作提交前通过 `FOR UPDATE` 重查操作者/目标版本，避免覆盖并发修改；修改前额外锁定当前会话并校验未过期/未撤销。
