# I1 MySQL 真实验证记录

日期：2026-09-21

本文档记录 I1「账号注册、登录与待分配访问」在真实 MySQL / InnoDB 环境下的集成验证事实。此轮仅进行测试与说明修正，未改变任何产品行为；前端、业务代码、迁移文件均未变更。

## 验证环境

- MySQL：**8.4.11**，独立 Docker 容器
  - 容器名：`kg-next-i1-mysql-20260921`
  - 专用数据卷：`kg-next-i1-mysql-20260921-data`
  - 仅监听 `127.0.0.1:13384` -> 容器内 3306（不对其他主机暴露）
- 存储引擎：默认引擎 InnoDB
- 事务隔离级别：**REPEATABLE-READ**（MySQL/InnoDB 默认）
- 数据库名：`kindergarten_test_i1`（专用隔离库）
- 迁移版本（alembic head）：**`20260921_i1_identity_reg`**
- 表引擎：四张业务表 `accounts`、`first_admin_control`、`sessions`、`operation_records` 以及 `alembic_version` 均为 **InnoDB**
- 测试账号权限：应用与集成测试统一使用 `kg_test_i1`，权限仅限 `kindergarten_test_i1.*` 的 `SELECT/INSERT/UPDATE/DELETE/CREATE/DROP/REFERENCES/INDEX/ALTER`，无其他库权限
- 连接凭据保存在私有文件 `/tmp/kg-next-i1-validation/test.env`（私有权限，不写入仓库、不在本文档输出）

验证过程中未安装任何依赖或软件；后端使用仓库已有的 `.venv`。

## 测试范围与结果

测试文件：`backend/tests/integration/test_identity.py`（本轮所有变更均只发生在此文件及文档）。

- 首轮：**17 项通过，1 项失败，0 项跳过**。唯一失败为操作记录按 `created_at` 排序时同一秒内顺序不确定（MySQL DATETIME 秒级精度），通过改为按 action + 变更后 version 精确定位记录修复。pi 复现时原 18 项曾全部通过，说明原断言存在不稳定性。
- 扩充测试期间，脱敏用例曾因夹具重复注册管理员失败，修正了测试账号初始化方式。
- 修正后：测试扩展为 24 项，**24 项全部通过，0 失败、0 跳过**，一次完整通过用时约 6.851s。随后发起的重复循环已由 main 中止，不计作额外通过证据。
- main 整合审查发现两个直接证据缺口，本轮修正后只定向重跑受影响的 5 项：
  - `test_failed_registration_does_not_consume_first_admin`
  - `test_password_write_failure_rolls_back_everything`
  - `test_admin_reset_failure_rolls_back_everything`
  - `test_cli_reset_failure_rolls_back_everything`
  - `test_persistence_contains_no_raw_secrets`

  结果：**5/5 通过，0 失败、0 跳过（1.786s）**。其余 19 项结果沿用上述完整运行，未重新验证。

覆盖首管并发竞争、同名并发与规范化唯一性、待分配教师访问管理接口被拒、三种密码变更后的会话失效、登录与重置竞争、版本冲突、失败回滚和操作记录脱敏。未执行 I2 或后续模块验证。

## 实际命令

main 使用已有镜像创建专用卷和容器（环境文件由本地脚本生成，凭据不输出）：

```bash
docker volume create kg-next-i1-mysql-20260921-data
docker run -d --name kg-next-i1-mysql-20260921 \
  --label purpose=kindergarten-manager-next-i1-test \
  --env-file /tmp/kg-next-i1-validation/mysql.env \
  -p 127.0.0.1:13384:3306 \
  -v kg-next-i1-mysql-20260921-data:/var/lib/mysql mysql:8.4.11
```

随后通过容器内 MySQL 客户端建立测试账号，并只授予上述测试库权限。迁移、测试的实际核心命令如下，均从 `backend/` 执行：

```bash
source /tmp/kg-next-i1-validation/test.env
.venv/bin/alembic upgrade head
.venv/bin/python -m unittest discover -s tests/integration -v
```

迁移成功；数据库查询确认版本号、表引擎和账号授权。pi 的 24 项完整通过运行使用同一 discovery 命令（未带 `-v`）。最后定向执行：

```bash
.venv/bin/python -m unittest -v \
  tests.integration.test_identity.IdentityIntegrationTests.test_failed_registration_does_not_consume_first_admin \
  tests.integration.test_identity.IdentityIntegrationTests.test_password_write_failure_rolls_back_everything \
  tests.integration.test_identity.IdentityIntegrationTests.test_admin_reset_failure_rolls_back_everything \
  tests.integration.test_identity.IdentityIntegrationTests.test_cli_reset_failure_rolls_back_everything \
  tests.integration.test_identity.IdentityIntegrationTests.test_persistence_contains_no_raw_secrets
```

## 两个证据缺口的修正

### 1. 故障注入改为"先写真实记录并 flush，再由真实 MySQL 报错"

`_fail_with_real_mysql_error` 现保留对原始 `record_operation` 的引用（模块加载时捕获，避免 patch 后递归到自身），故障点行为为：

1. 先调用原始 `record_operation` 写入真实操作记录；
2. 执行 `db.flush()`，使账号、首次管理员控制行、会话撤销 UPDATE、操作记录等全部挂起写入确实发送给 MySQL（均在同一未提交事务内）；
3. 再对一张不存在的表执行 INSERT，由**真实 MySQL 服务器**返回语句错误（1146），随后应用回滚整个事务。

本人改密失败用例（原先是测试内手工构造的异常）也改用此 helper，因此四个回滚用例（注册、本人改密、管理员重置、CLI 重置）均以真实数据库报错验证；各用例仍保留清晰的快照断言（password_hash / version / auth_version / 撤销时间 / 审计 action 列表）。

### 2. 持久化无原始秘密的检查加强

`test_persistence_contains_no_raw_secrets` 现覆盖：

- 登录后立即保存 admin/teacher 的原始会话 token（仅作为测试局部变量，从不打印）；
- 捕获每次改密前后账号真实 `password_hash`，纳入"禁存值"集合（初次注册 hash、本人改密后 hash、管理员重置后 hash、CLI 重置后 hash）；
- 直接对数据库执行 `SELECT *`，将 `operation_records` 与 `sessions` 的**所有实际列**序列化，断言不含任何原始密码、原始会话 token；并断言操作记录不含任何账号 `password_hash`；
- 明确断言 `sessions.token_hash` 等于对应原始 token 的 SHA-256（admin/teacher 各对应自己的登录会话）；
- 为注册、姓名更新、本人改密、管理员重置等请求补充了状态码断言；
- 删除了原先无意义的"密码文本 SHA-256 与 token_hash 集合不相交"对比。

## 关于 mock 的边界

本次并发与事务验证**不是** mock，也**不是** SQLite 替代；数据库始终是真实的 MySQL 8.4.11 / InnoDB。mock 仅用于：

- 在事务的精确时点调度故障（patch `record_operation` / 个别用例中的会话与校验函数）；
- 为 CLI 提供终端输入（`getpass`、`input`、`isatty`）。

## 前端状态

main 启动 `.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000` 和前端 `npm run dev`，通过 Chrome 实际点击验证：

- 教师注册成功回登录页，登录后显示待分配、暂不能备课；姓名初始为未填写。
- 本人设置保存姓名成功；第二页面恢复同一会话与已保存姓名。
- 双页面修改触发真实 409；前端保留本页编辑，显示服务器最新姓名，不自动覆盖；再次手动提交成功。
- 退出返回登录页；管理员登录后可查看教师列表；重置对话框显示准确目标和“该账号现有登录将失效”，取消后清除目标。

浏览器未提交本人改密或管理员密码重置；这些写操作及会话失效由真实 MySQL 接口测试覆盖。浏览器工具对更改凭据要求用户接管，因此未将其计为浏览器端到端点击通过，也未阻断数据库验证。CLI 输入通过测试注入，未进行真实人工终端输入验证。

前端没有变更，未重跑类型检查或构建；此前 31 项无数据库测试及前端检查仅为交接记录，不作为本轮执行结果。

## 收尾

main 已停止临时 Vite（5173）/ API（8000）进程，并执行 `docker stop kg-next-i1-mysql-20260921`。容器状态为 `exited`，三个端口均无监听；容器、专用卷与测试数据保留，未删除。浏览器测试页已关闭，测试账号保留在隔离库内。凭据目录权限为 700，`test.env` 为 600；临时文件可能在系统清理 `/tmp` 时消失。

没有安装或系统权限阻塞，没有需要用户执行的修复命令。需要复现时，可执行 `docker start kg-next-i1-mysql-20260921`，待 MySQL 就绪后加载上述配置并运行测试（会清理隔离测试库）。若临时凭据文件已丢失，需重新设置该隔离测试账号凭据。

全程使用 pi `coding-plan / ark-code-latest` 执行测试代码修正；main 负责环境、证据核对、浏览器检查和本记录整合。未切换 OpenCode，未暂存、提交、推送或部署。
