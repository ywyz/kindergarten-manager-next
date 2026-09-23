# Backend I2 说明

本目录包含 I2「班级、教师分配、学期与有效日历」的后端实现。

## 范围

- 园所配置单行（`school_settings`），含不可逆 `plans_started_at` 阶段门槛。
- 班级创建/列表/详情/编辑：名称、年级（small/middle/large）、表头教师名单、保育员。
- 教师首次分配：管理员选择真实班级后生效；不改 `auth_version`、不撤销会话。
- 学期创建/编辑：闭区间、不可重叠（含端点）、持久日历修订。
- 有效日历：默认来自 `chinesecalendar`（已声明 `==1.11.0`），管理员例外优先；缺年份保持 `unknown`。
- 配置变更预览/确认：版本校验、并发冲突、30 分钟过期、幂等应用。
- 操作记录扩展通用目标字段，保留 I1 账号记录语义。

不交付：调班、解除归属、账号停用/启用、周计划接管、计划/任务 schema、AI、导出、工作进程。

## 本地开发配置

配置通过进程环境变量或 `backend/.env` 加载。需要覆盖时直接设置环境变量，例如：

```bash
export APP_DISABLE_DOTENV=1
export DATABASE_URL=mysql+pymysql://user:pass@127.0.0.1:13384/kindergarten_dev
export COOKIE_SECURE=false
export ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

依赖声明见 `pyproject.toml`。`uv.lock` 已同步 `chinesecalendar==1.11.0`，并已安装到 `.venv`；未升级其他依赖。

## 隔离测试库准备（破坏性，只用于本地验证）

下面的命令会破坏目标库，**只能用于专门创建的隔离测试库**，不可在生产或共享业务库执行。

```sql
CREATE DATABASE kindergarten_test_i2 CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE kindergarten_test_i2_fresh CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 隔离测试专用账号（集成测试运行用，非生产账号）
CREATE USER 'kg_test_i2'@'127.0.0.1' IDENTIFIED BY '...';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES, DROP ON kindergarten_test_i2.*
  TO 'kg_test_i2'@'127.0.0.1';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES, DROP ON kindergarten_test_i2_fresh.*
  TO 'kg_test_i2'@'127.0.0.1';
```

> 注意：本段为破坏性命令模板，执行前必须根据你的环境另行授权和确认，且只允许在专门创建的隔离测试库执行。

最小权限说明：
- 生产或日常运行账号仅需要目标库的 `SELECT/INSERT/UPDATE/DELETE`；本文档中的 `kg_test_i2` 是隔离测试专用账号，不得用于生产。
- 隔离迁移与集成测试需要 `CREATE/ALTER/INDEX/REFERENCES/DROP`（`TRUNCATE` 依赖 `DROP`）。
- 测试仅允许 `127.0.0.1/localhost`、数据库名 `kindergarten_test_i2` 或 `kindergarten_test_i2_fresh`、驱动 `mysql+pymysql`。
- MySQL 8.4 中 `GRANT` 立即生效，不需要 `FLUSH PRIVILEGES`。

## 迁移（必须单独执行后再测试）

迁移需要能执行 DDL 的数据库账号，且必须显式指向隔离测试库。不要在生产或共享业务库上执行。

I2 迁移链：

```
20260921_i1_identity_reg
  ↓
20260921_i2_classes_assignments
  ↓
20260922_i2_terms_calendar
```

空库升级到当前 head：

```bash
cd backend
export APP_DISABLE_DOTENV=1
export DATABASE_URL=mysql+pymysql://kg_test_i2:...@127.0.0.1:13384/kindergarten_test_i2_fresh
uv run alembic upgrade head
```

从 I1 升级到 I2 并验证 I1 夹具保留：

```bash
cd backend
export KG_TEST_DATABASE_URL=mysql+pymysql://kg_test_i2:...@127.0.0.1:13384/kindergarten_test_i2
bash scripts/i2_mysql_fixture.sh i2
```

空库链式升级到 I2 head：

```bash
cd backend
export KG_TEST_DATABASE_URL=mysql+pymysql://kg_test_i2:...@127.0.0.1:13384/kindergarten_test_i2_fresh
bash scripts/i2_mysql_fixture.sh fresh
```

脚本会按传入 mode 重建目标库、执行迁移，并断言 I1 夹具（accounts/sessions/operation_records 旧字段及 I2 回填字段）完整保留；不输出任何凭据。

## 运行服务

```bash
cd backend
export APP_DISABLE_DOTENV=1
export DATABASE_URL=mysql+pymysql://user:pass@127.0.0.1:13384/kindergarten_dev
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

前端通过 Vite 代理访问 `/api`。

## 测试

### 不依赖数据库的单元测试

```bash
cd backend
export APP_DISABLE_DOTENV=1
unset DATABASE_URL
.venv/bin/python -m unittest discover -s tests/unit -v
```

### 集成测试

集成测试需要隔离 MySQL 8.4 / InnoDB，且迁移已单独完成：

```bash
export APP_DISABLE_DOTENV=1
export I2_TEST_ALLOW_DESTRUCTIVE=yes
export I2_TEST_DATABASE_URL=mysql+pymysql://kg_test_i2:...@127.0.0.1:13384/kindergarten_test_i2
cd backend
.venv/bin/python -m unittest discover -s tests/integration -v
```

测试白名单：仅 `kindergarten_test_i2` 或 `kindergarten_test_i2_fresh`；驱动必须是 `mysql+pymysql`；主机必须是 `127.0.0.1/localhost`；端口必须是 `13384`。其他数据库（包括 `kindergarten_test_i1`）会被拒绝。

## 本轮验证结果

### 后端

```bash
cd backend
export APP_DISABLE_DOTENV=1
unset DATABASE_URL
.venv/bin/python -m unittest discover -s tests/unit -v
# Ran 45 tests ... OK
```

```bash
export APP_DISABLE_DOTENV=1
export I2_TEST_ALLOW_DESTRUCTIVE=yes
export I2_TEST_DATABASE_URL=mysql+pymysql://kg_test_i2:...@127.0.0.1:13384/kindergarten_test_i2
.venv/bin/python -m unittest tests.integration.test_class_assignment tests.integration.test_terms_calendar tests.integration.test_i2_concurrency tests.integration.test_i2_remaining -v
# Ran 56 tests ... OK
```

集成测试在 `I2_TEST_ALLOW_DESTRUCTIVE` 未设置时会跳过，不会连接数据库。

### 前端

```bash
cd frontend
npm run typecheck   # exit 0
npm run build       # exit 0
```

## V1–V14 验证状态

| 编号 | 状态 | 说明 |
| --- | --- | --- |
| V1 迁移衔接 | 通过 | `scripts/i2_mysql_fixture.sh i2/fresh` 在本地 13384 成功；I1 夹具保留，12 表全 InnoDB |
| V2 班级资料 | 通过 | `test_class_assignment.py` 覆盖创建/编辑/唯一性/权限 |
| V3 首次分配竞争 | 通过 | 并发用例：独立管理员 session、异常捕获、精确计数 |
| V4 权限 | 通过 | 访客/待分配/已分配/管理员越权用例 |
| V5 学期约束 | 通过 | `test_terms_calendar.py` 覆盖端点/部分重叠/相邻 |
| V6 周次 | 通过 | 覆盖跨周、跨年 |
| V7 默认与例外 | 通过 | 真实 1.11.0 调休／假日落库、管理员例外优先、普通库异常不写入 |
| V8 缺失年份 | 通过 | unknown、部分例外、撤销回 unknown |
| V9 库升级与范围 | 通过 | 重导入、扩大／缩短／起始日变化、旧快照及移出例外 |
| V10 预览竞争 | 通过 | 版本变化后旧预览失效、换操作者 apply |
| V11 事务故障 | 通过 | flush 后真实 MySQL 语句错误回滚 |
| V12 读一致性 | 通过 | 事务内阻挡／释放验证完整修订；独立子进程重启后不调用库仍读同一快照 |
| V13 后续能力门槛 | 通过 | `plans_started_at` 阻断 |
| V14 前端基本流程 | 通过 | main 在 Chrome 真实执行分配、班级／园所／学期、批量例外、刷新恢复、取消、双页面冲突重算、教师只读及切月 |

## I2 收尾修复

- 前端 `TeacherView` 与 `TermCalendarView`：`changeMonth` 后通过 `watch(month)` 触发 `loadCalendar`，并加入异步最后请求保护，失败时清空旧日历避免“新标题配旧数据”。
- 后端配置预览路由改用 `model_dump(exclude_unset=True)`，builder 按字段 key 判断是否提交；`class_update` 支持显式 `caregiver_name: null` 清空与 `header_teacher_names: []` 清空，省略字段保留原值。

## 已知限制

- 未实现调班、解除归属、账号停用/启用、接管等 I2 之后的切片能力。

最终交付与逐项证据见 [I2 实施与验证记录](../docs/bootstrap/i2-implementation-status.md)。最后一批预览 candidate 响应经真实数据库定向检查：pending 可恢复，applied 不返回候选，教师访问被拒绝。API、Vite 与 MySQL 验证容器均已停止。
