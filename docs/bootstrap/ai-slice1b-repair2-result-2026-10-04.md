# AI 1B 第二轮最小补修结果记录（2026-10-04，实际执行日期 2026-10-04）

依据：[1B 定稿](../specs/ai-settings-api-1b.md)、[1B 补修复审](ai-slice1b-re-review-2026-10-04.md)、[第二轮补修交接](ai-slice1b-repair2-opencode-prompt-2026-10-04.md)、[第一轮补修结果](ai-slice1b-repair-result-2026-10-04.md)（保留）。
本轮只修复审 S1/S2 的测试夹具并重跑证据，不重新规划、不进入 1C。**实现与自动验证状态按本记录；产品验收（浏览器/transport/真实 AI/W6）仍未执行，本记录不替代。**

## 1. 开工状态

- HEAD：`1647fc934d41b29a844a807d454031e66a2b45af`（与复审一致；本轮全程未 commit/push）。
- git status：与复审记录一致的全部既有未提交修改（1A/1B 工作区 + 全部历史报告/文档）逐项保留，未回退、未覆盖；新增文件仅本轮三个（下表两个测试 + 本报告）。
- 未读 `.env`/私人密钥；未安装依赖/Skill/MCP；未另起编码代理；未启动 API/Vite/worker；未 SSH/部署；未连接远程库。
- `docs/bootstrap/ai-slice1c-opencode-coding-prompt-2026-10-04.md` 为上轮遗留文件，本轮未创建、未修改（开工时即存在于未提交修改中，予以保留）。

## 2. 实际改动文件

| 文件 | 说明 |
| --- | --- |
| `backend/tests/unit/test_ai1b_api.py`（S2，40→41 用例） | StrictInputTests 重构（见 §4） |
| `backend/tests/integration/test_ai1b_settings_api.py`（S1，23 用例不变） | 身份矩阵逐例独立化 + 两时序测试 accounts.version 精确断言（见 §3） |
| `docs/bootstrap/ai-slice1b-repair2-result-2026-10-04.md` | 本报告 |

未改：router、schemas、services、models、main.py、迁移、依赖/锁、auth_service、日／周／Word 业务、frontend 及全部旧报告。

## 3. S1 ↔ 测试对应（真 MySQL）

复审原文对应的两处夹具缺口修复如下。

### 3.1 身份失效矩阵逐例独立化

原 `test_identity_failure_matrix_401`（`counter`/`flag` 循环连续累积，第一项过期遮蔽其余三项）重写为逐例独立协议，测试名保留 `test_identity_failure_matrix_401`（集成层真实依赖，未 mock 业务服务/身份结果）。每例结构（`_CASES` 四例：expired / revoked / deactivated / auth_version_mismatch）：

1. `_restore_identity()`：先把 teacher_a 账号/会话四条件全部恢复有效（is_active=1、auth_version=1、version=1、password_hash 与种子一致；会话未撤销、未过期、auth_version=1）——每一 case 进入时都是完整有效账号/会话，不叠加前例状态。
2. 同一 cookie（`self.teacher_a`）合法 `GET /api/settings/ai-config` 先行确认 **200**（合法基线；身体 version=0 世界重置）。
3. 该例写集合计数基线 `counts_before`（重连读取）。
4. 仅提交该例目标 UPDATE（另一连接），其余条件不动。
5. 重连核对（`_identity_flags_all` 按位四条件）：目标条件经该例 `flag_sql` 断言已失效；`_identity_flags_others(label)` 断言除目标位外其余三位全部仍有效（`all(others.values())`）。
6. 合法 GET 与合法 PATCH（`expected_version: 0` + CONFIG_META + 合成 secret）均 **401 AUTH_REQUIRED**。
7. 重连 `counts_after` 与 `counts_before` 精确相等（审计 operation_records、事件 prompt_change_records、ai_config_versions、personal_prompt_versions、prompt_default_versions、accounts.version 全字段逐项相等，head 仍 None）——逐例核对，非循环末尾总量。
8. 循环结束兜底总量核对：ai_config_versions=0、operation_records=0、prompt_change_records=0、head=None。

### 3.2 时序测试 accounts.version 精确断言（外部 UPDATE 的 +1 单列基线）

- `test_deactivate_between_snapshot_and_lock_blocks_prompt_write`：外部停用 UPDATE（is_active=0、version+1、auth_version+1）之前先读取 `acc_version_before_external` 作单列基线；401 后重连断言 `row[0] == base + 1`（"accounts.version 应仅为外部 UPDATE 的 +1（请求零增量）"），并再次重连核对数值稳定在基线 +1。row[1]/row[2]（auth_version=2、is_active=0）断言保留。
- `test_auth_version_change_blocks_admin_default_write`：外部 auth_version 推进前先读取 admin `baseline_acc_version`；401 后重连断言 `== baseline + 1`（请求自身零增量），随后同 cookie GET 仍 401（外部变化生效证据）。
- `test_revoke_between_snapshot_and_lock_blocks_config_write`：撤销 SQL 只动 sessions.revoked_at，accounts.version 基线相等的既有断言保留未回退。

### 3.3 保留项

`_request_with_identity_tamper` 真实 snapshot 形成后/锁前时序夹具原样保留（真 cookie → 真实 get_auth_snapshot → 外部连接提交 → 真实服务复核；无 AuthSnapshot 伪造、无业务/身份 mock）；B6 只读零副作用、R2 生命周期/回滚/密文重连对账、错误主密钥与 key_id 变体测试全部未动。

## 4. S2 ↔ 测试对应（无库 ASGI，`StrictInputTests`）

复审命令复现的三项缺口：DELETE 负例被多余 builder 键污染、管理员版本负例 0 次、管理员 guidance_map 矩阵 0 例。修复如下：

| 复审问题 | 修复 | 结果 |
| --- | --- | --- |
| DELETE 复用 config_payload（4 键 → extra 422 掩盖目标） | 新增 `delete_payload(row_builder)`：仅 `{"expected_version": 1}`；DELETE case 全部使用该 builder | DELETE 版本负例 **4**（True/"3"/3.0/-1），且带合法 200 基线 |
| 管理员版本负例 0 次（内部别名 default → VERSION_FIELDS 空迭代） | `admin_case()` 返回 `(PATCH, /api/admin/prompt-defaults/{TASK}, admin_payload, "expected_default_revision")`——真实字段名；类内旧 `default`→real 映射删除 | 管理员版本负例 **4**（True/"1"/1.0/0）+ missing/null/extra 各自构造 |
| AdminPromptDefaultPatchIn 无合法基线（edit_payload：多 expected_personal_revision、缺 expected_default_revision 的杂凑） | 新增 `admin_payload` builder：仅 `{"expected_default_revision": 1, "guidance_map": {"a": "b"}}` | 基线 **200**（admin 身份） |
| 管理员 guidance_map 矩阵 0 例 | 新增 `admin_map_case()` 进入 `_all_cases()`；MAP_FIELDS guidance_map 7 负例全部作用到管理员路由 | **7** 例负例 |

其余矩阵沿用但加强：

- `test_each_field_missing_is_422`：17 case（15 personal/config/DELETE + 管理员版本 + 管理员 guidance_map），每 case 合法 200 基线先行，missing 负例 17，逐一断言 VALIDATION_ERROR。
- `test_each_field_null_is_422`：同 17 case，null 负例 17（本轮补齐 code==VALIDATION_ERROR 断言）。
- `test_each_version_field_rejects_bool_float_string`：版本负例 40（expected_version config 4 + DELETE 4 + expected_personal_revision 12 + target_default_revision 8 + target_contract_version 4 + admin 4），每个负例前有该 case 合法 200 基线。
- `test_each_string_field_rejects_off_type`：9 负例（protocol_id/base_url/model × 9/True/[]），基线齐全。
- `test_each_map_field_rejects_off_type_and_nested`：27 负例（guidance_map：personal 7 + adapt 7 + 管理员 7；accepted_fields 6：5]、{"a":1}、[5]、[None]、[]、["a","a"]）。
- `test_extra_field_rejected_for_each_dto`（新增）：8 个请求 DTO（config PATCH/DELETE、initialize、edit、accept、reject、adapt、管理员 PATCH）逐一构造：合法 payload 复制后仅增加一个未知顶层键 → 422 VALIDATION_ERROR，每个负例前有该 DTO 合法 payload 的 200 基线。
- 保留项：test_initialize_body_shapes（None/[]/{"account_id"}）、test_secret_presence_matrix（省略→SECRET_UNSET 语义）、LeakSafetyTests（URL userinfo/query、恶意键、嵌套 guidance、含标记非法 JSON、validator ctx、typed 异常、`capture_root_log` 退出即恢复 handler 与 level）、OutOfContractResponseBoundaryTests（R4）、ExistingRouteValidationRegression 均未回退。
- 身份与清理：`_assert_baseline_200` 按 `/api/admin` 前缀自动设 admin/teacher 身份；mock.patch.stopall、dependency_overrides.clear、日志 handler 恢复仍由基类 addCleanup 承担，全量 unit 无污染（648 通过，见 §5）。

## 5. 验证（实际执行）

环境：新一轮一次性容器；导入与运行前清除继承 `DATABASE_URL`／`AI_MASTER_KEY`／`AI_MASTER_KEY_ID`，全程 `APP_DISABLE_DOTENV=1`、`PYTHONDONTWRITEBYTECODE=1`；真库测试 `AI1A_TEST_ALLOW_DESTRUCTIVE=yes` ＋ `AI1A_TEST_DATABASE_URL`（指向 `…_fresh`，guard 每次连接与 Alembic 子进程前校验 driver/host/port/库名白名单）。凭证/主密钥仅本轮进程内合成材料，未打印、未写入本报告或任何输出。

| 项 | 命令 | 实际结果 |
| --- | --- | --- |
| 新 1B 单元 | `.venv/bin/python -m unittest tests.unit.test_ai1b_api` | **41 OK**（0 fail／0 skip） |
| 全量 backend unit | `discover -s tests/unit -t . -q`（env 清出口） | **648 OK**（0 fail／0 skip） |
| 原 50 项 1A MySQL | `unittest tests.integration.test_ai1a_config_prompts` | **50 OK**（12.6s／15.0s），含 H1 手工日／周＋Word 缺主密钥（`test_save_and_export_without_master_key`）与错主密钥（`test_save_and_export_with_broken_master_key`）定向回归 |
| 全部 1B 真MySQL | `unittest tests.integration.test_ai1b_settings_api` | **23 OK**（9.8s，0 skip；首轮复跑中 `test_deactivate…` 因基线读取次序记录过一次真实失败 2!=3，按逐例独立口径改为"外部 UPDATE 前读取单列基线"后修正通过，非实现缺陷隐瞒——实现未改） |
| 1A＋1B 同进程 | `unittest tests.integration.test_ai1a_config_prompts tests.integration.test_ai1b_settings_api` | **73 OK**（24.8s） |
| H1 定向复跑 | `unittest …H1ManualPathRegression` | **2 OK** |
| 两库 Alembic current | guard 校验连接直读两库 `alembic_version`（每连接先经 `authorized_url` 白名单校验；等价口径沿用第一轮记录口径） | 两库均 `20261003_ai1a_config_prompts` |
| repository heads | `APP_DISABLE_DOTENV=1 .venv/bin/alembic heads`（不连库） | 唯一 `20261003_ai1a_config_prompts (head)` |
| 依赖锁 | `~/.local/bin/uv lock --check --offline` | Resolved 27 packages（OK），未新增依赖 |
| `git diff --check` | 仓库根 | 通过 |

呑吐过程中的一次性环境记录：首轮真库启动时 `AI1A_TEST_DATABASE_URL` 误指向主库（非 fresh）引发 8 fail／32 error 的整轮失败——该轮数据位于误指向库并已随资源重置后 DROP（错误凭证文件同步销毁），本轮最终验证全部在重置后的正确环境完成；此失败如实列入历史记录，不删改。

## 6. 资源与清理（确切 ID）

本轮一次性资源（全新创建，未复用任何预存容器/卷；镜像 `mysql:8.4.11` 本地已存在，未新拉取）：

- 容器 `ai1b-repair2-mysql-13387`，完整 ID：`d7b7a4ba9c74382b2ca2edf5bd78136104240735905392460b47cfbd1a6d3853`（`mysql:8.4.11`，`127.0.0.1:13387→3306`）。
- 专用匿名卷完整 ID：`a5ad84e9e567ec10f453520675ac62a1b163b51b7e0845234ce31658ebf0f061`（挂载点 `/var/lib/mysql`）。
- 库仅两个白名单库；仅本轮合成凭证/合成主密钥。

清理命令与核查：

```text
docker rm -f -v ai1b-repair2-mysql-13387   # 容器与其匿名卷一并删除
```

- `docker ps -a`：仅余预存 `kg-next-i5-slice4-mysql-20261001`（`5f0682288f1e`，未触碰）。
- `docker volume ls`：仅余预存 `kg-next-i5-slice4-data-20261001`（未删）；本轮卷 `a5ad84e9…` 已不在（grep 计数 0）。
- `ss -tln`：13387 空闲。
- 本轮合成凭证临时文件已即时销毁；`mysql:8.4.11` 镜像按惯例保留。
- （过程说明：由于首轮 DSN 密码含 `/` 导致 URL 解析失败，曾重建同轮容器一次；被重建的首个容器完整 ID 为 `ed8b2dcfa81dbb812e02c55522aa984c03310243b2e8c151c08da19376c81984`，其匿名卷 `136b283f05c7187baa912d21eee232dfcda440c690ecbb36415dced0dd4cc28f` 及首个数据目录在资源重置时一并删除，两个容器/卷均为本轮一次性资源——同轮重建，非复用预存资源。）

**第一轮历史 ID 记录纠正**（沿用复审说明，不覆盖旧报告）：第一轮验证会话的容器 ID 在原实现报告中即为截断形式（`846d84d97ff7…`），该轮容器已删除且记录中无完整 ID，如实标注为不可恢复、不臆造；但原实现报告中的第一轮**匿名卷 ID 已是完整 64 位值**（`0ae97fa0c7848626fd58f713c201f70b831f580012bdf09b3365c87a8fb3ac7e`），上一轮补修报告 §5 将其与容器一并写作"截断/无法恢复"是轻微记录错误，在此纠正；第二轮（`de54af21…`＋卷 `7ee3a3a7…`）与上一轮（`e8dfbe51…`＋卷 `5d349c19…`）组合完整 ID 均已依原报告追溯保留。

## 7. 状态声明

- **实现**：1B 业务实现未在本轮改动（本轮仅测试夹具与报告）；复审 S1/S2 两处夹具缺口已按提示词口径修复。
- **自动验证**：§5 全部命令本轮实际执行并全部通过（含一次环境口径错误的如实记录与重置后重跑）。
- **产品验收**：未执行。1B 不因本记录宣布产品验收完成；等协调者只读复审通过后，另行安排 1C 前提解除、桌面验收与后续切片。
