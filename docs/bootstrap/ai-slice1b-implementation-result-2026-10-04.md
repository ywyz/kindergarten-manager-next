# AI 1B 实现结果记录（2026-10-04）

依据：[1B 定稿规格](../specs/ai-settings-api-1b.md)、[1A 第二轮收口](ai-slice1a-closeout-review-2026-10-04.md)。
本片为自动验证／实现记录；产品验收（浏览器、transport、真实 AI、W6）另行记录，本记录不替代。

## 1. 开工状态

- HEAD：`1647fc934d41b29a844a807d454031e66a2b45af`（本轮全程未 commit/push）。
- 既有未提交修改（1A 工作区）全部保留：`AGENTS.md`、`backend/app/config.py`、`models.py`、`pyproject.toml`、`uv.lock` 及全部 1A 新文件、docs 草案，均未回退、覆盖或提交。
- 本轮未读 `.env`/私密密钥、未 SSH/部署、未启动 API/Vite/worker、未安装 Skill/MCP/依赖。

## 2. 实际改动文件

| 文件 | 说明 |
| --- | --- |
| `backend/app/routers/ai_settings.py`（新增） | 本片唯一 router：个人配置与提示词 10 条 + 管理员默认 2 条，共 12 条；身份取 `get_auth_snapshot`，个人 target 固定 `snapshot.account_id`；typed 错误仅映射固定 code，`raise ... from None`，不回显异常文本 |
| `backend/app/schemas.py`（独立新区域） | 1B 请求/响应 DTO：全部 `extra="forbid"`；版本字段 `strict=True` 整数（拒绝 bool/浮点/字符串）；secret 用 `model_fields_set` 区分省略/显式 null/空串；响应为显式白名单模型（AiConfigOut/TaskStatusOut/PromptDetailOut/PersonalInitOut/PersonalWriteOut/PersonalRejectOut/PromptDefaultOut/TaskStatusListOut） |
| `backend/app/main.py` | 注册 `ai_settings.router` 与 `admin_router`；`RequestValidationError` handler 对 `/api/settings/ai-config`、`/api/settings/prompts`、`/api/admin/prompt-defaults` 前缀分支固定 422 `VALIDATION_ERROR`（无 fields/msg/loc/input/ctx/body），既有路由处理不变 |
| `backend/app/services/prompt_service.py` | 仅最小只读扩展（原因：1B DTO 需要同事务快照内的完整详情）：`read_task` 结构性扩充（latest_default、based_guidance_fields、未初始化时的显式 null/current 字段；已知任务缺契约/默认或 based contract 缺行抛 `UnknownTaskType`→503）；`list_tasks` 的 `_task_status` 同步改为缺行即 503；新增管理员只读 `read_default`（verify_self_read 后核验真实管理员）；`update_default` 返回增加 `guidance_fields`。不改 models/锁序/事务/注册表 |
| `backend/tests/unit/test_ai1b_api.py`（新增，27 用例） | 标准库 ASGI 驱动，mock 服务 + dependency override；12 条路径注册、身份/权限矩阵、Origin/Content-Type 拒绝、no-store、secret 未传 vs null/空串、bool/字符串/浮点版本拒绝、空 patch/重复字段、8000/8001、未知 task 404、teacher→admin 403 优先、503/409/422 固定映射、响应白名单、合成 secret 标记不出现在 HTTP body、既有路由 fields 形状回归 |
| `backend/tests/integration/test_ai1b_settings_api.py`（新增，13 用例） | 真 MySQL ASGI：真实 cookie、`get_auth_snapshot`、真实服务与库；跨本人隔离、管理员本人配置独立、teacher→admin 403（含未知 task 顺序）、待分配教师本人设置、失效会话 401；另一连接在 snapshot 后/服务锁前撤销会话 → 401 且版本/审计/head 零增量；GET 全量无副作用（versions/events/ops/accounts.version 不变）；未初始化→显式初始化幂等；编辑/接受保留未选字段/拒绝幂等与再接受/旧 expected 409；v2 实际发布后旧 based 编辑保持待适配、accept/reject 409、旧 contract adapt 409、缺/未知字段 422、完整 adapt 后新字段可编辑；配置清除/保留/轮换/缺失-错误主密钥降级与 503 边界实际执行；成功写响应版本与真实 head 对账 |

未改：models、迁移、依赖/锁（`uv lock --check --offline` 通过）、auth_service、ai_config_service、ai_crypto、ai_locks、registry、日周/Word 业务、frontend。

## 3. 12 条接口

`GET/PATCH/DELETE /api/settings/ai-config`；`GET /api/settings/prompts`；`GET /api/settings/prompts/{task_type}`；`POST .../initialize`；`PATCH /api/settings/prompts/{task_type}`；`POST .../accept-default`；`POST .../reject-default`；`POST .../adapt`；`GET/PATCH /api/admin/prompt-defaults/{task_type}`。

## 4. 验证（实际执行；两轮会话各自实际运行，均通过）

| 项 | 命令/结果 |
| --- | --- |
| 新增 1B 单元 | `python -m unittest tests.unit.test_ai1b_api -q` → 27 OK（两轮均复跑通过） |
| 全量 backend/tests/unit | `python -m unittest discover -s tests/unit -t . -q` → **634 tests OK**（两轮均复跑通过） |
| 既有 1A MySQL 集成 | `AI1A_TEST_ALLOW_DESTRUCTIVE=yes AI1A_TEST_DATABASE_URL=…fresh … unittest tests.integration.test_ai1a_config_prompts` → **50 tests OK**（含 H1 手工日周/Word 定向回归：缺/错主密钥路径；第二轮会话复核通过） |
| 新增 1B MySQL 集成 | 同上环境变量 `unittest tests.integration.test_ai1b_settings_api` → **13 tests OK**（第二轮会话复核通过） |
| Alembic | `alembic heads` 唯一 head `20261003_ai1a_config_prompts`；fresh/主库经 guard 校验连接实际读取 `alembic_version` 均为 `20261003_ai1a_config_prompts` |
| 依赖锁 | `uv lock --check --offline`（`~/.local/bin/uv`）→ Resolved 27 packages（OK），未新增依赖 |
| `git diff --check` | 通过 |

无 secret 证据：合成标记 `sk-ai1b-synthetic-marker-*`/`SECRET_MARKER` 仅存在于测试输入；断言其不出现于 HTTP body；应用日志未记录异常文本（路由只映射固定 code，服务异常 `from None`）。DSN/凭证/主密钥未写入本记录与测试输出。

## 5. 资源与清理

- 实现会话一次性容器：`ai1b-mysql-13387`（ID `846d84d97ff7…`，`mysql:8.4.11`，127.0.0.1:13387→3306），专用匿名卷 `0ae97fa0c7848626fd58f713c201f70b831f580012bdf09b3365c87a8fb3ac7e`，`docker rm -f -v` 已删除。
- 验证复核会话一次性容器：`ai1b-mysql-13387`（ID `de54af218afb228880d1788ec935033532a9ba23ecf5ca297206fdd9db4d78c8`，`mysql:8.4.11`，127.0.0.1:13387→3306；镜像已存在未新拉取），专用匿名卷 `7ee3a3a73b4679bcbb97e1564b52f8f0981932df0e3e370727a9bc28f426c831`。全部 B1–B6 验证在该资源实际执行后 `docker rm -f -v ai1b-mysql-13387` → 容器与专用卷均已删除，`ss -tln` 确认 13387 空闲。
- 两轮容器均仅含白名单库 `kindergarten_test_ai1a`、`kindergarten_test_ai1a_fresh`（本轮创建/使用），仅本轮合成凭证与合成主密钥（进程内传递，未打印/未入报告）；每次连接与测试前由 guard 清除继承 `DATABASE_URL`/`AI_MASTER_KEY`/`AI_MASTER_KEY_ID` 并校验授权。
- 清理后检查：`docker ps -a` 仅余预存 `kg-next-i5-slice4-mysql-20261001`（未触碰）；卷列表仅余预存 `kg-next-i5-slice4-data-20261001`（未删）；未删除其他容器/卷/镜像（`mysql:8.4.11` 镜像保留）。

## 6. 偏离与未执行项

- 单元路由注册断言按新 FastAPI 的 `_IncludedRouter` 形态遍历 `original_router`（环境事实，不改变 API 行为）。
- 验证复核会话未独立复跑 guard 负例命令（guard 模块未改动，既有证据保留）；两库 Alembic current 经 guard 校验连接直接读取 `alembic_version` 表核对（等价 `alembic current`，避免绕过 guard 环境约束）。
- 管理员 GET/PATCH 权限较定稿新增显式路由级 `_check_admin_snapshot`（先于 task_type 校验）：教师访问 admin 默认接口固定 403，服务事务内二次核验保留，未偏离定稿 §2。
- 未执行：1C 前端/浏览器产品验收、worker、transport/DNS/供应商调用、AI 测试端点、任务/调用日志表、候选采用、材料闭环、secret 清理、完整 W6、部署、commit/push。
