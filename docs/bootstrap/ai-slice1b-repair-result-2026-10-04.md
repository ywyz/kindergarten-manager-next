# AI 1B 最小补修结果记录（2026-10-04）

依据：[1B 定稿](../specs/ai-settings-api-1b.md)、[1B 审阅](ai-slice1b-review-2026-10-04.md)、[1B 补修交接](ai-slice1b-repair-opencode-prompt-2026-10-04.md)、[原 1B 实现报告](ai-slice1b-implementation-result-2026-10-04.md)（保留）。
本轮只补修 R1–R4，不重新规划、不进入 1C。**实现与自动验证状态按本记录；产品验收（浏览器/transport/真实 AI/W6）仍未执行，本记录不替代。**

## 1. 开工状态

- HEAD：`1647fc934d41b29a844a807d454031e66a2b45af`（与审阅一致；本轮全程未 commit/push）。
- 既有未提交修改（1A 工作区 + 全部历史报告/文档）全部保留，未回退、未覆盖。
- 未读 `.env`/私人密钥；未安装依赖/Skill/MCP；未另起编码代理；未启动 API/Vite/worker；未 SSH/部署。

## 2. 实际改动文件

| 文件 | 说明 |
| --- | --- |
| `backend/app/schemas.py`（仅 1B 响应区域） | R4：`AiConfigOut.protocol_id` 收紧为 `Literal["chat_completions_v1"] \| None`；`ready_reason` 收紧为定稿五个值 `Literal[...] \| None`（新增模块内 `_READY_REASON_VALUES` 常量）；`TaskStatusOut.latest_default_revision/latest_contract_version` 由 `ge=0` 收紧为 `ge=1`。字段名与正常响应形状不变 |
| `backend/app/routers/ai_settings.py`（最小安全分支，见偏离说明） | R4 边界落实：全部 12 条路由的响应 DTO 组装移入同一 `try`，`_map_errors` 新增 `pydantic.ValidationError` 分支 → 固定 503 `SERVICE_UNAVAILABLE` JSON（`raise ... from None`）。服务若产出契约外数据（未知协议／未知 reason／非正 latest 版本），不再 200 透传，也不再以未处理 traceback 进入 ASGI 层（未处理异常会由 ServerErrorMiddleware 原样 re-raise 并可能把含原值的 traceback 带入服务器日志） |
| `backend/tests/unit/test_ai1b_api.py`（重写扩至 40 用例） | R3＋R4 单元边界（见 §3） |
| `backend/tests/integration/test_ai1b_settings_api.py`（扩至 23 用例） | R1＋R2 真库边界（见 §3） |

未改：models、迁移、依赖/锁、auth_service、ai_config_service、ai_crypto、ai_locks、ai_config_url、ai_prompt_registry、main.py（本轮未需改动）、日周/Word 业务、frontend。

## 3. R1–R4 ↔ 测试对应

### R1（集成，`tests/integration/test_ai1b_settings_api.py`）

| 要求 | 测试 | 重连断言 |
| --- | --- | --- |
| 真 cookie 逐项 401：过期／已撤销／停用／auth_version 不符 | `test_identity_failure_matrix_401` | 每项之后 GET 配置仍 401；operation_records／ai_config_versions 零增量、head 仍不存在 |
| 管理员实际保存本人配置；教师/管理员互相隔离 | `test_admin_saves_own_config_then_isolation_both_ways` | 重连 GET：管理员 model=manager 侧本人、教师 model=teacher 侧本人；两账号 ai_config_versions 各 `[1]` |
| snapshot 后、`lock_self` 取锁前的外部撤销 → 配置写 401 | `test_revoke_between_snapshot_and_lock_blocks_config_write` | 零增量（ops/cfg versions/heads/events/accounts.version）且 head 保持 1；另一连接的 revoked_at 已生效（独立记账） |
| 外部停用 → 个人指导写 401 | `test_deactivate_between_snapshot_and_lock_blocks_prompt_write` | head/处理标记/版本/事件/审计零增量；accounts.version 仅为外部 UPDATE 自身的 +1（单独记账）；is_active=0、auth_version=2 为外部生效证据 |
| auth_version 变化 → 管理员默认写 401 | `test_auth_version_change_blocks_admin_default_write` | 默认修订/事件/审计零增量；同一 cookie 后续 GET 仍 401（外部变化生效） |
| 按三个写入口（配置／个人指导／管理员默认）覆盖事务身份复核 | 上三条分别对应 | 见上 |
| 时序夹具不 mock 业务服务／身份；无 account 锁后等待死锁 | 夹具 `_request_with_identity_tamper`：先调用真实 `get_auth_snapshot`（真 cookie 判定出 snapshot），返回前用另一连接提交外部变化，再继续真实服务复核；外部提交发生在请求事务取锁之前 | — |

### R2（集成，同文件）

| 要求 | 测试 | 重连断言 |
| --- | --- | --- |
| 未选中字段文字保留 | `test_accept_preserves_unselected_personal_edit` | 先 PATCH 非选中字段，再按字段接受：响应与重连 GET 中未选字段仍为教师编辑文字；事件计数（init/edit/default_update/accept）与 accept 事件数核对 |
| 重复 reject 对账 + 之后再接受 | `test_reject_repeat_reconcile_then_reaccept` | reject 事件恒为 1、个人版本仍 1、head seen=2/rejected=2；第三次幂等不增事件；接受后 rejected 清空、seen=2 |
| v2 实际发布后实际发送 reject 409 | `test_v2_contract_adaptation_flow`（新增 reject 分支） | 409 `PROMPT_ADAPTATION_REQUIRED`；重连核对 last_rejected 仍 NULL、last_seen 仍 1 |
| 旧 expected／非法结构／缺/未知适配字段失败 → 完整无增量 | `test_failed_writes_reconcile_full_state`（10 个失败请求逐个对账）；`test_conflict_versions_409_and_school_version_untouched`；`test_accept_requires_initialized` | 每次失败后重连核对 prompt head 五元组、版本行、事件、审计、默认行、config 版本行/head、accounts.version 全部不变 |
| 配置保留/轮换/清除重连核对密文认证 | `test_config_ciphertext_reconnect_reconciles_versions` | pinned 读取 v1/v2/v3 解密结果逐一断言 equal 合成明文（不打印）；v4 密文/key_id 为 NULL；版本行 `[1,2,3,4]`、`ai_config_%` 审计恰 4 条 |
| 含密文配置 + 移除主密钥 | `test_missing_master_key_full_write_set_blocked` | GET 200 `DECRYPT_UNAVAILABLE`；保留 PATCH 503、需加密 PATCH 503，二者写集合（ops/版本行/head）零增量；DELETE 200 且新版本密文 NULL、head=2 |
| 错误主密钥 | `test_wrong_master_key_blocks_keep_and_rotate`（格式非法材料；`test_different_key_id_degrades_get` 为换 key_id 变体） | 同上退化与 503、DELETE 成功、零增量 |
| 清除后的无密文元信息保存独立测试 | `test_cleared_config_metadata_save_without_key_independent` | 无主密钥下 PATCH 元信息 200、version 3、`MISSING_SECRET`；重连 GET 版本/URL/model 持久 |

### R3（单元，`tests/unit/test_ai1b_api.py`）

| 要求 | 测试 |
| --- | --- |
| 12 条接口注册 + 表驱动合法响应（200 + no-store + 无 error 体） | `test_all_twelve_routes_registered`、`test_all_twelve_routes_succeed_table_driven` |
| 每个写接口缺/错 Origin 403、非 JSON 422、错误响应 no-store（8 条表驱动） | `test_write_routes_reject_origin_and_ctype_table` |
| 每种输入 DTO 独立必填/extra/type/null；版本字段拒 bool/浮点/字符串 | `test_each_field_missing_is_422`、`test_each_field_null_is_422`、`test_each_version_field_rejects_bool_float_string`、`test_each_string_field_rejects_off_type`、`test_each_map_field_rejects_off_type_and_nested` |
| initialize body 形状 / secret 未传与 null/空串/类型区分 | `test_initialize_body_shapes`、`test_secret_presence_matrix` |
| 8000 边界 mock 服务成功断言 200、8001 422（服务不被调用） | `test_guidance_length_boundary` |
| 空 patch／重复接受字段 | `test_empty_patch_and_duplicate_accepted_fields` |
| 应用日志临时 handler 采集并完整恢复；成功/错误 HTTP body 与应用日志均无合成 secret/主密钥/DSN 标记 | `LeakSafetyTests`：`test_invalid_url_userinfo_and_query`、`test_malicious_unknown_key_and_nested_guidance`、`test_invalid_json_with_markers`、`test_validator_ctx_is_not_echoed`、`test_typed_service_exception_messages_never_leak`、`test_success_and_error_paths_clean`（`capture_root_log` 管理器在退出时移除 handler 并恢复 level） |
| validator ctx／恶意未知键／嵌套 guidance 键值／含标记非法 JSON／typed 服务异常分别构造，不打印标记 | 同上五个测试分别对应；断言固定错误体仅含 `code/message`，`assertNotIn` 检查而不输出标记 |
| 原有路由回归 | `ExistingRouteValidationRegression.test_existing_routes_keep_fields_error_shape`（既有路由保留 fields 形状）、`test_unauthenticated_shape_is_401_no_store` |
| 清理所有 overrides/mock/handler | 基类 `addCleanup(dependency_overrides.clear)`＋`mock.patch.stopall`；日志 handler 上下文管理器恢复 |

### R4（单元，同文件 `OutOfContractResponseBoundaryTests`）

| 要求 | 测试 | 结果 |
| --- | --- | --- |
| 未知 ready_reason 不 200 透传、无未处理 traceback | `test_config_unknown_ready_reason_gets_fixed_503` | 503 `SERVICE_UNAVAILABLE`，body 不含该值 |
| 未知 protocol_id 同上 | `test_config_unknown_protocol_gets_fixed_503` | 503，body 不含该值 |
| 合法五个 reason 表驱动全接受 / ready=true 时 reason=null | `test_config_legal_reasons_table` | 200 |
| TaskStatusOut 两个 latest 版本为正整数 | `test_task_status_zero_latest_versions_get_fixed_503`（0 → 503）、`test_task_status_legal_positive_versions_table`（1/1、7/2 → 200） | 通过 |

## 4. 验证（实际执行）

环境：导入前清除继承 `DATABASE_URL`／`AI_MASTER_KEY`／`AI1A` 等私人变量；`APP_DISABLE_DOTENV=1`、`PYTHONDONTWRITEBYTECODE=1`；`AI1A_TEST_ALLOW_DESTRUCTIVE=yes`＋`AI1A_TEST_DATABASE_URL`（guard 校验 127.0.0.1:13387 ＋两白名单库）。

| 项 | 命令 | 实际结果 |
| --- | --- | --- |
| 新增 1B 单元 | `.venv/bin/python -m unittest tests.unit.test_ai1b_api` | **40 OK**（0 fail／0 skip） |
| 全量 backend unit | `.venv/bin/python -m unittest discover -s tests/unit -t . -q` | **647 OK**（0 fail／0 skip；27+13=40 项 1B） |
| 原 50 项 1A MySQL | （同 env）`unittest tests.integration.test_ai1a_config_prompts` | **50 OK**（含 H1 `test_save_and_export_without_master_key`／`test_save_and_export_with_broken_master_key` 手工日／周与 Word 定向回归） |
| 新增 1B MySQL | （同 env）`unittest tests.integration.test_ai1b_settings_api` | **23 OK**（0 fail／0 skip） |
| 1A＋1B 同进程 | 两模块一次运行 | **73 OK** |
| 两库 Alembic current | guard 校验连接直接读两库 `alembic_version` | `kindergarten_test_ai1a` 与 `…_fresh` 均 `20261003_ai1a_config_prompts` |
| repository heads | `.venv/bin/alembic heads`（不连库） | 唯一 `20261003_ai1a_config_prompts (head)` |
| 依赖锁 | `~/.local/bin/uv lock --check --offline` | Resolved 27 packages（OK），未新增依赖 |
| `git diff --check`（仓库根） | — | 通过 |

无 secret 证据：全部标记（`sk-…-synthetic-…` 等）仅存在于测试输入；断言其不出现在 HTTP body 与采集的应用日志中，测试不打印标记；主密钥材料仅在进程内以 `os.urandom(32)` 生成，DSN／密码未写入本报告或任何输出。

## 5. 资源与清理

本轮一次性资源（全新创建，未复用任何预存容器/卷）：

- 容器 `ai1b-repair-mysql-13387`，完整 ID：`e8dfbe511836664aeb80bcee06e2041d0f9065ac386a9891fddac0cf6185c307`（`mysql:8.4.11`，`127.0.0.1:13387→3306`）。
- 专用匿名卷完整 ID：`5d349c1920d6b5319494161cecd846289b5d298e270115f6aa3e62393893336d`。
- 库仅两个白名单库（本轮创建 `kindergarten_test_ai1a_fresh` 与容器自建 `kindergarten_test_ai1a`）；仅本轮合成凭证/合成主密钥（进程内传递）。

清理命令与核查：

```text
docker rm -f -v ai1b-repair-mysql-13387   # 容器与其匿名卷一并删除
```

- `docker ps -a`：仅余预存 `5f0682288f1e kg-next-i5-slice4-mysql-20261001`（未触碰）。
- `docker volume ls`：仅余预存 `kg-next-i5-slice4-data-20261001`（未删）。
- `ss -tln`：13387 已空闲。
- 本轮合成凭证的临时文件已即时销毁；`mysql:8.4.11` 镜像按惯例保留。

**第一轮历史截断 ID 说明**：原 1B 第一轮容器/卷 ID 在 [原报告](ai-slice1b-implementation-result-2026-10-04.md) 中即为截断形式（`846d84d97ff7…`、匿名卷 `0ae97fa0c784…`），本轮无法将其恢复为完整 ID，如实标注为记录缺口，不臆造；第二轮完整 ID 保留在原报告供追溯。

## 6. 偏离与未执行项

偏离（均属提示词允许的“HTTP 输出安全最小修”与实现命名范围，非产品行为变化）：

1. **router 最小安全分支**：响应 DTO 组装移入 try＋`pydantic.ValidationError` → 固定 503。原实现中 `_config_out` 在 try 之外：mock 证据表明契约外服务数据本会以未处理异常穿过 ASGI（500 透传或 re-raise traceback）。该分支只影响“服务已违反响应契约”的边界，不改变任何正常路径。
2. `schemas.py` 新增 `_READY_REASON_VALUES` 常量（供测试表驱动引用五个固定值）。
3. 单元层“匿名 401 形状”测试采用身份依赖模拟（真实 cookie 身份矩阵全部在集成层以真 MySQL 完成，符合定稿 §8“无库 ASGI 可 override 依赖”分工）。

未执行项（与原报告一致，本轮无新增授权）：

- 1C 前端/浏览器产品验收、transport/DNS/供应商调用、worker、AI 测试端点、任务/调用日志表、候选采用、材料闭环、完整 W6 材料移交补验、secret 清理、部署、commit/push。
- 本轮真库验证基于一次性本地容器；`alembic current` 以 guard 校验连接直读 `alembic_version` 核对（等价口径，沿用原报告记录）。

## 7. 状态声明

- **实现**：R1–R4 已实现（见 §2）。
- **自动验证**：§4 全部命令本轮实际执行并全部通过。
- **产品验收**：未执行。1B 不因本记录宣布产品验收完成；等协调者只读复审后另行安排桌面验收与后续切片。
