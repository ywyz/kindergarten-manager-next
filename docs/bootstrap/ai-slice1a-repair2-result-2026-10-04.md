# AI 1A 第二轮补修结果报告（2026-10-04，S1–S5）

状态：**S1–S5 定向补修与补验完成；真实 MySQL（一次性专用容器）验证通过；未 commit／push；未进入 1B／1C；等待协调者复审。**
执行者：OpenCode。开工基线：HEAD `1647fc9`；全部既有未提交代码／文档保留未回退、未清理；未读 `.env` 或任何现有私密密钥；未复制旧项目、未新增 Skill／MCP、未启动额外编码代理；依赖与锁零改动（未安装新包、未下载解释器、未升级锁）。

上一轮覆盖声明的缺口（据 [复审](ai-slice1a-re-review-2026-10-04.md) §2，本轮逐条落实）：S1 URL 边界未实际修复并非按"不显示原始地址"；S2 仍在异常中拼原始 stderr（合成凭证可进入异常文本与 repr／traceback）；S3 旧快照成功路径被前置 rollback 消解；S4 任务列表"真实入口"测试并未调用 list_tasks、E2 未能证明发布后 v1-based 编辑保持待适配及 v2 新字段可编辑；S5 CHECK 负例已连带主键／FK 违规、迁移样本仅主题 patch 未选真实来源。旧的历史报告（`ai-slice1a-implementation-result-2026-10-03.md`／`ai-slice1a-repair-result-2026-10-04.md`）原样保留，不代表结论更正。

## S1 URL 边界（实际缺陷→红转绿）

改动：`app/services/ai_config_url.py` 顶部以此顺序校验：原始输入含 `?` 或 `#` 分隔符即 `BaseUrlInvalid`（百分号编码路径不解析）；`urlsplit(...)`／`hostname`／`port` 的畸形解析异常统一转 `_PARSE_INVALID_MESSAGE`（固定消息"base_url 无效：解析失败或组成部分不合法（请填写 HTTPS 供应商前缀）"），不回显原始地址；保持纯离线、不触 DNS／transport。

失败先证（`tests/unit/test_ai1a_url_guard_edges.py` 建立于修复前；`unittest` 复跑输出）：
- `S1UrlBoundaryTest.test_raw_separators_rejected` FAIL（末尾 `?`／`#` 旧行为被接受）；
- `test_malformed_parse_raises_typed_fixed_message` ERROR（`https://[broken/v1` 抛原始 ValueError 等）；
- `test_percent_encoded_path_kept_literal`（旧代码对 `%2F` 保留并在含 `?` 时拒绝不完整 → 修复后绿）。
两条证据在修复前一致复现：6 项失败覆盖 S1 与 S2 的目标行为。

修复后（同一文件转绿）：
- `test_raw_separators_rejected`：8 种 `?`／`#`（含末尾分隔符、`?#`、路径结束 `#`）全拒；
- `test_malformed_parse_raises_typed_fixed_message`：`[broken`／`[::1`／`port` 端口等畸形全部 `BaseUrlInvalid` 固定消息；
- `test_percent_encoded_path_kept_literal`：`%2F` 路径保持原样；
- `test_reasonable_prefixes_still_pass`：合法供应商前缀、路径、端口、公网 IP 字面量仍通过；
- `test_error_type_family`：`BaseUrlInvalid ⊂ AiInputInvalid`。

测试数量（S1 相关）：4 个新测试方法（含修复前同方法红→修复后绿），无业务/schema 变更。

## S2 guard 异常文本（实际泄漏通道→红转绿）

改动：`tests/integration/ai1a_guard.py`：
- `run_alembic` 失败公开异常只含已校验 driver／port／库名、退出码、固定类别 (`category=alembic_child_process_nonzero_exit`)，不拼任何 stdout／stderr／原始解析异常，`raise ... from None` 杜绝异常链回带凭证；
- guard 的拒绝消息全部固定（不再回显输入的库名／主机／端口）：`_REFUSE_*_MESSAGE` 常量集；`require_authorized_url` 以 `RuntimeError` 输出固定消息并在 `make_url` 畸形时包 `from None`；
- guard 模块在导入时强制 `APP_DISABLE_DOTENV=1` 并清除继承的 `DATABASE_URL`／`AI_MASTER_KEY`／`AI_MASTER_KEY_ID` 环境（`AI1A_TEST_DATABASE_URL` 是唯一入口），Alembic 子进程仅取得验证后的 `DATABASE_URL`（无继承主密钥、无 dotenv）。

失败先证（同上文件，修复前）：
- `S2GuardExceptionTest.test_failure_text_carries_no_markers` ERROR→修复前复现 `RuntimeError` 内含 `stdout/stderr`（合成标记 `SCHEMA-TAG-PASSWORD`／`SECRET-TAG-KEY-1` 会拼入）；mock 栈如复审复现（无连接、无真实数据库）；
- `test_guard_refusals_are_fixed_messages` FAIL（旧消息回显库名／主机，且拒绝种类混杂 AssertionError）。

修复后（同一文件转绿）：
- `test_failure_text_carries_no_markers`／`test_no_cause_chain_carries_credentials`：`subprocess.run` mock（仅异常边界，不替代真实 MySQL 业务测试）返回含合成 DSN／密码／密钥标记的 stdout／stderr，断言 `str`、`repr`、`"".join(traceback.format_exception(exc))` 均无标记，且 `__cause__`／`__context__` 为 None，固定类别 / exit= 可见；
- `test_guard_refusals_are_fixed_messages`：非法 host／port／driver／陌生库／畸形 URL 全部 `RuntimeError` 固定消息，文本不回显标签或原 URL；
- `test_disabled_guard_never_connects`：子进程断言 guard 未启用时 `INTEGRATION_ENABLED` 为 False 且 `AI_MASTER_KEY` 等不在环境（无连接）。

## S3 旧快照成功路径（本轮重做，必补验证）

改动：`tests/integration/test_ai1a_config_prompts.py` 删除旧 K1（四个"前置冲突再成功"的混合场景），新建：
- `K1StaleSnapshotWritePaths` 5 条成功路径（分别独立）：
  1) `test_a_config_keep_secret_stale_snapshot_success`：winner 落 v1 → stale Session 普通 SELECT 建立快照 → mover 提交 v2 → stale 普通 SELECT 仍见 v1 且 `stale.in_transaction()` 为 True → **同一事务内**直接 `save_config(expected=2)` 成功 v3；重连断言 head=3／versions=3／`ai_config_save` 审计=3、`read_pinned_config`：v3／v2 保留明文为 mover 的 v2（重加密）、v1 明文与升级前密文字节不变（逐字节比较）；
  2) `test_b_config_clear_stale_snapshot_success`：同快照连续事务内 `clear_secret(expected=2)` → v3 无 secret（cipher/key_id 双 NULL）、v2 密文保留、`ai_config_secret_clear` 审计=1；
  3) `test_c_personal_edit_stale_snapshot_success`：个人编辑在版本推进后以正确 expected=2 成功 r3；重连断言修订、两个编辑事件与审计、选定字段来自 stale patch、未被 mover 改动字段保留、`accounts.version` 仍 1（真实 accounts.version 被记录且不推进）；
  4) `test_d_personal_accept_stale_snapshot_success`：接受在另一连接推进修订后仍在旧快照事务内成功 r3；重连断言选定字段替换（"process"来自所选默认）、未选字段保持（mover 的 key_points）、`accepted_default_revision`＝所选默认修订、事件与账号版本；
  5) `test_e_admin_default_publish_stale_snapshot_success`：管理员发布在另一连接推进默认修订之后同事务成功 r3；重连断言合并字段（未选字段保持 r2 ）、school 目标审计 `target_version_after` NULL（PF-1）、账号版本不变。
- `K2StaleSnapshotConflicts` 3 条独立旧 expected 冲突（配置保留／个人编辑／管理员发布）：独立 Session＋独立快照，断言冲突后版本／修订计数不变（不与成功场景共享 rollback）。
所有断言以数据库行/重连读为主（不只看返回值），无中途 commit／rollback／close 在写入口之前。

未宣称"红转绿"：本轮未（也不应）把成功路径写成此前先失败再修——这是对上一轮证据缺口的**测试重建**（服务实现沿用 R6 已建立的 current locking read，无服务代码改动需求）；冲突路径为已存在语义的独立正向复测。

## S4 真实 list_tasks 与 v2 编辑（必补验证）

改动：
- 删除 `tests/unit/test_ai1a_service_inputs.py.test_list_tasks_real_entry_covers_all`（以仅构造 TaskStatus 冒充真实入口），替换为 `test_task_status_shape_available_for_service` 并注明真库覆盖位置；
- 新增集成 `L1RealTaskListTraversal` 3 条：
  * `test_a_list_tasks_seven_tasks_and_get_no_side_effects`：真库调用 `list_tasks`，7 类状态、初始化后单一任务状态变化、发布 v2 后该任务 `adaptation_state='adaptation_required'`／required=2／pending_default_update、其他任务保持未初始化；GET 前后 `prompt_change_records`／`operation_records`／`personal_prompt_versions`／`personal_prompt_heads` 计数完全不变（GET 无副作用，不推进 last_seen）；
  * `test_b_list_tasks_isolation_forbidden`：非本人目标 `Forbidden`；
  * `test_c_read_task_does_not_advance_last_seen`：三次 read_task 后 `last_seen_default_revision` 仍 1。
- `E2ContractFieldsetScenarios` 修订与扩展：
  * `test_c_personal_edit_validates_against_based_contract` 重写为实际发布 v2：v1-based 编辑保持 v1 字段集、based=1 且 head 处于 `adaptation_required`（required=2）；
  * 新增 `test_f_edit_new_field_after_adapt_to_v2`：v2 发布 + 适配后编辑 `assist_notes_v2` 成功；未知字段 typed `FieldViolation` 且修订计数不变（全回滚）；
  * v2/v3 均由 `publish_variant_contract`／`publish_contract_v3` 真实新增字段发布，未修改运行时 `TASK_REGISTRY`。

## S5 约束负例与迁移样本（必补验证）

- `I1NullConstraintPaths.test_b_adapt_required_null_reference_check` 改为对**已有合法 head** 执行 `UPDATE ... SET adaptation_state='adaptation_required', required_contract_version=NULL`（不 INSERT／不重复主键），断言数据库错误包含 **3819** 与 **ck_pph_adapt_ref**，且失败后原三列逐值不变；`test_required_columns_and_checks` 断言 NOT NULL 拒绝（前提：先建真实账号）；
- `test_c_config_cipher_without_key_id` 断言 **3819** 与 **ck_ai_config_versions_secret_key**，失败后无残留行；
- `A1MigrationCompatibility.test_b`：升级前通过既有 `daily_plan_service`（真实内容写入，prepare 后 group/game 有 id）与 `weekly_plan_read_service.get_detail` 的**真实来源候选**选择：`weekly_plan_service.save_weekly_plan(patch 含 outdoor_game_slots.collective_1 引用 candidate)` → `confirm_weekly_plan`，断言草稿 JSON 与确认 JSON 中 `collective_1` 的 `daily_plan_id`／`game_id` 等于候选身份且 `name`／主题文本非空；随后比较升级前后 16 张旧表**整行**（`dump_world_rows` JSON 键序无关标准化）。空库升级（`test_a`）、固定种子比较（`_assert_seed_matches_registry`）、复合 FK／唯一键（`test_c`）保留并通过。

## 验证命令与结果（本轮实际执行）

| 命令 | 结果 |
| --- | --- |
| `APP_DISABLE_DOTENV=1 .venv/bin/python -m unittest tests.unit.test_ai1a_url_guard_edges` | S1／S2 修复前 6 处失败；修复后 **9 tests OK**（红转绿证据在上方引用） |
| `APP_DISABLE_DOTENV=1 .venv/bin/python -m unittest discover -s tests/unit -t .` | **607 tests OK**（598→607：新增 S1/S2 9 个；未以 598 旧通过替代新证据） |
| `AI1A_TEST_ALLOW_DESTRUCTIVE=yes AI1A_TEST_DATABASE_URL=… unittest tests.integration.test_ai1a_config_prompts` | **50 tests OK**（42 旧 + S3K1/K2 8 + S4L1 3 + S5/I1 3 + E2 改写） |
| `alembic heads`（无连接） | `20261003_ai1a_config_prompts (head)`，唯一 head |
| 两库 `ensure_schema` current | `kindergarten_test_ai1a` 与 `kindergarten_test_ai1a_fresh` 均为 `20261003_ai1a_config_prompts` |
| `uv lock --check` | 通过（未动） |
| `git diff --check` | 通过 |
| 无主密钥／错误主密钥手工日周＋Word 导出回归 | `H1ManualPathRegression.test_save_and_export_without_master_key`／`..._with_broken_master_key` 在 50 例套件中继续通过 |

## 资源与清理

- 镜像 `mysql:8.4.11`（已授权内复用）；容器 `ai1a-mysql-13387`（新建，仅 loopback 127.0.0.1:13387）＋专用匿名卷；白名单 `kindergarten_test_ai1a`／`kindergarten_test_ai1a_fresh`。
- 结束：`docker rm -f -v ai1a-mysql-13387` → 容器与专用卷删除，端口 13387 空闲（`ss` 检查无监听）；预存容器 `kg-next-i5-slice4-mysql-20261001` 与其他卷未触碰；本次合成凭证（包括 root 密码）只存于测试会话环境，已随 `/tmp` 临时文件删除，未写入仓库或报告。
- 无资源阻塞：MySQL 验证未受影响，本轮未发生"资源不可用"退化路径。

## 未执行项 / 边界

- 未新增 API/UI/worker/transport/供应商调用/任务表/候选落库/材料闭环/secret 清理；未改 models、既有迁移、依赖锁、日／周／Word 业务 Service 核心逻辑（本轮无服务实现修改需求，仅测试与 guard／URL 层）。
- 未重跑 I1–I5 旧集成套件（未改既有 schema／业务）；未启动服务器。
- S3 的"成功路径直接写入"按本轮测试重建执行（非 S1/S2 型红转绿），协调者如需进一步红转绿佐证可在复审时单独点名某场景。

停止，等待协调者复审；1B 未获授权，不启动。
