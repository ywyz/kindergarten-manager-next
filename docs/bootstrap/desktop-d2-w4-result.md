# D2 W4 实现交付结果（OpenCode）

更新：2026-10-18。本文件记录 D2 W4「日计划三类候选与原子采用」的实现、自测、跨轮修复（R01–R09）与剩余未验范围，供 Codex 独立核查。**W1–W3 限定环境工程通过保持不变；W4 实现、自动测试与自测证据已交付，本文件不代表 D2 产品验收、真实供应商兼容或发行通过，也不自行宣告 Codex 验收通过。**

授权与边界：延续 `docs/tasks/current.md`（2026-10-18 用户授权实施 W4）与用户「Go 套餐 DeepSeek V4.1 Flash」指示；Codex 独立核查并分轮交回 R01–R09，均由同一 OpenCode 会话修复。仅 W4；未启动 W5/W6、未调用应用真实 AI/供应商、未发布/安装，未改 `0001–0004` 历史迁移、旧云端 registry、`ARCHITECTURE.md`、依赖或锁文件，未 commit/push，原教师体验根、D1/W1 包与 W3 探针未改动。

## 1. 本批改动范围

### 1.1 生产代码（新增）

| 文件 | SHA256（前 16） | 作用 |
| --- | --- | --- |
| `backend/app/local/ai_provenance.py` | `08e53c29bd4a70d3` | 共享候选关系链与拆分基准校验器：候选摘要/冻结 schema、成功 execution/task/input 身份、基准值等于来源拆分候选的**原始模型过程**；`null` 基准合法；任何损坏组合一律存储错误（不降级、不清空）。含 `load_candidate` / `load_candidate_for_plan`，在 SQL 层按 plan 过滤候选，foreign 候选即使自身 JSON 损坏也统一 404。 |
| `backend/app/local/ai_candidates.py` | `760e078ca6b9474f` | 候选只读服务：有界游标分页列表（不含候选正文/来源）、详情（含真实 `source.dependencies` 与 `source_excerpt`）、当前适用性（eligible/source_changed/contract_obsolete，按**当前 required 契约**判定）、跨计划统一 404、来源变化安全字段提示。 |
| `backend/app/local/ai_adoption.py` | `c5dc3904d85777ea` | 采用服务：严格编辑校验、非空去重且为候选已有板块子集的目标校验、10 分钟/最多 64 条内存 token（随机 32 字节 base64url，绑定 launch/session scope/profile/plan/candidate/版本/目标/编辑 hash/依赖 hash/目标 hash）、原子采用事务（合并选中字段、服务端分配 ID、追加内容与 provenance、CAS 当前三元指针、写回执与审计、一起提交）、失败全回滚、token 成功提交后才消费；回执优先且在 token 缺失时二次复查回执以消除 R09 竞态。 |

### 1.2 生产代码（修改）

| 文件 | SHA256（前 16） | 改动 |
| --- | --- | --- |
| `backend/app/local/ai_inputs.py` | `d7b15bb22953e21e` | 新增共享 `dependency_matches`（来源校验唯一入口）与 `source_excerpt`（其他活动含 `game_config`/`daily_plan_snapshot`/`calendar_context`）；基准来源改由 `ai_provenance.resolve_baseline` 落实。 |
| `backend/app/local/ai_task_service.py` | `9cd1e72b7ed9f55f` | `_revalidate_source` 复用共享校验器；`task_out` 对损坏候选 JSON 返回存储错误而非 500。 |
| `backend/app/local/daily_plan_service.py` | `d68176cdfcadea42` | `_validate_stored_content` 接受**合法**AI 基准（经共享校验器），仍拒绝损坏；`create_or_open`/`save` 每个 D2 版本写一行 provenance 并继承基准来源；手工 PATCH 仍禁止 `split_baseline`。 |
| `backend/app/local/schemas.py` | `b3e4e538f8dc9773` | 候选列表/详情、预览、采用请求与响应模型（`extra=forbid`、严格整数）。 |
| `backend/app/local/api.py` | `8f3b8ed9b30398ab` | 候选列表/详情、`preview-adoption`、`adopt` 路由；采用/预览传入 launch id 与本次 app 会话内部 scope。 |
| `backend/app/local/app.py` | `b6f383b7795e0cb6` | 应用创建时生成随机内部 `session_scope`（非会话密钥、不返回、不持久），用于绑定本次会话的预览凭证。 |

### 1.3 测试与夹具

| 文件 | SHA256（前 16） | 覆盖 |
| --- | --- | --- |
| `backend/tests/local/test_d2_w4_candidates.py` | `ebfefbecaaa7230f` | 候选读（分页/无材料/跨计划 404/详情来源）、预览（只读、严格 schema、目标规则、过期、容量上限、版本冲突）、采用（拆分基准、原文模型过程优先于教师编辑、适龄仅改过程并继承基准、其他活动仅选中板块、无变化不增版、回执耗用/重启恢复、同键异体冲突、中途/COMMIT 边界故障全回滚并同键重试）、来源/目标/无关版本分类（R06）、损坏链（失效执行、缺输入、篡改/畸形候选、非 JSON 列、基准不匹配/缺 provenance、同文不同来源、foreign 坏行 404）、保存/重启/导出 DOCX 结构。 |
| `backend/tests/local/test_d2_w4_api.py` | `35ff0fa0b58eb418` | 真实 Uvicorn+`http.client`：三类采用、严格 schema/目标 422、列表无材料与 `no-store`、Host/Origin/session、版本冲突、来源/目标变化 409、丢响应/重启回执、换 app 会话拒绝旧 token、真实并发（异 token 异键单成功；同 token 同键**确定性屏障**交错必须 200/200 同结果）、坏 JSON 本计划 503、foreign 坏候选 404。 |
| `backend/tests/local/test_d2_w3_tasks.py` | `9e6110afc77ac6e7` | 夹具必要调整：D2 每个版本现在都写 provenance 行，原基准身份用例由“新增一行”改为“在既有版本行上挂基准来源”，并令基准文本等于来源候选的原始模型过程，符合 W4 严格不变式；未弱化断言。 |

## 2. 命令与实际结果（显式隔离）

统一解释器 `desktop/.venv-d1/Scripts/python.exe`（CPython 3.14.7 Windows x64，标准 GIL）。全部测试进程显式隔离 `LOCALAPPDATA` 与 `credential_root`（`LocalTestCase` 注入临时根），设置 `APP_DISABLE_DOTENV=1`，仅使用独立合成根；完整日志落盘，退出码为测试进程本身退出码（非管道 `tail` 退出码）。

- W4 专项（本实现者自测）：
  `LOCALAPPDATA=<root>/localappdata APP_DISABLE_DOTENV=1 python -X utf8 -W always::ResourceWarning -m unittest tests.local.test_d2_w4_candidates tests.local.test_d2_w4_api`
  → **47 项 / 28.6 秒 / 实际退出码 0**，日志 `%TEMP%/kgm-d2-w4-opencode-run3/unittest.log`；无 `ResourceWarning`。
- 全 local 回归（本实现者自测）：
  `... -m unittest discover -s tests/local -t .` → **470 项 / 295.1 秒 / 实际退出码 0**，日志 `%TEMP%/kgm-d2-w4-opencode-full2/unittest.log`；无 `ResourceWarning`。
- 既有桌面回归（本实现者自测）：
  `python -m pytest desktop/tests -q` → **146 passed / 2 warnings / 退出码 0**，日志 `%TEMP%/kgm-d2-w4-opencode-desktop/pytest.log`（两项为既有 Starlette/anyio 弃用警告）。
- R09 先失败后通过（本实现者自测，仅证据不提交）：确定性同 token 同键交错在**禁用提交后回执复查**（模拟修复前路径）时，首个请求得到 `LocalAiPreviewExpired`；启用修复后同一交错两请求均 200 且结果一致、仅一内容版一回执。脚本 `%TEMP%/kgm-d2-w4-opencode-run3/probe_r09_pre_fix.py`，输出 `%TEMP%/kgm-d2-w4-opencode-run3/probe_r09.log`。

Codex 独立证据（**非本实现者结论**，仅据核查记录转述）：首轮真实 HTTP 反例 `%TEMP%/kgm-d2-w4-codex-ql230lkl/codex-prefix-r01-r02.json` 与 `codex-prefix-r04-r06.json`、`codex-prefix-malformed-candidate.json`；边界复核 44/44；R09 相同确定性交错独立复验 200/200（`codex-final-r09.json`）。最终通过与否以 Codex 核查记录为准。

## 3. 规格对照

- 产品 §9.4 / 工程 §5.1–§5.2 接口：候选列表/详情、`preview-adoption`、`adopt` 全部经本机 session/Host/Origin 保护并 `no-store`；列表不含材料全文，详情含真实来源（含 §5.1 要求的 `dependencies`）与当前适用性、可选目标；跨计划与不存在统一 404。
- 工程 §2.2 / §9.3 基准：拆分基准固定为 `{group_activity_process: <原始模型过程>}`；教师预览编辑只进正式六字段，不改基准；适龄只改 `process`，其他活动只改选中板块；手工保存与原文后续修改继承基准及来源；`null` 基准（旧 D1）合法；非 null 基准缺来源、结构错误、与来源候选内容不一致、来源执行非成功、候选被篡改/畸形一律存储错误，不静默清空。
- 工程 §2.2 采用事务与幂等：先查持久回执；事务内复核契约/版本/来源/目标/编辑 hash/有效期；分配服务端 ID；追加内容与 provenance；CAS 当前 `(content_id, content_version)` 三元指针；写回执与审计；一起提交，失败全回滚；token 成功提交后才消费；语义内容与基准来源均不变时 `changed=false` 且不新增版本、不因新 ID 造假变化。
- 工程 §5.3 严格编辑 schema：未知字段、ID、来源 ID、反思、显式 null、空/重复/越界目标均 422；字符/数组/UTF-8 总量沿用冻结容量保护。
- 工程 §5.4 错误：来源变化 `AI_SOURCE_CHANGED`（含安全 `changed_fields`）、仅目标变化 `AI_TARGET_CHANGED`、无关字段变化重新预览的 `VERSION_CONFLICT`、token 过期/换会话 `AI_PREVIEW_EXPIRED`、旧契约只读 `AI_CONTRACT_OBSOLETE`、同键异体 `AI_REQUEST_CONFLICT`、回执未知 404、损坏存储 503；事务内按“来源 → 目标 → 版本”分类，依赖与目标重叠时来源优先（R06）。
- 工程 §5.1 契约：候选可用性按**当前 required 契约**判定（R03），且预览后契约变化在事务内再次阻断；历史基准读取不依赖当前 required 契约，契约升级不破坏已采用基准（R04）。
- 工程 §2.1 / §7 W4 导出读取：`export_service._load_records` 经同一 `_load_content` 校验链读取真实基准，导出使用已保存版本，Word 差异规则与 R18 格式未改动。

## 4. 跨轮缺陷与修复（R01–R09）

1. **R01 采用回执绑定完整请求**：指纹由 `plan/candidate/expected_version` 扩展为**含 preview_token 本身**，同键换不同编辑/选择 token → `AI_REQUEST_CONFLICT`；同键同体在 token 耗用后与重启后仍回读原结果；未提交时换新 token 同键重试仍允许。回归：`test_same_key_different_token_conflicts`、`test_lost_response_and_restart_receipt`。
2. **R02 token 版本绑定与会话作用域**：事务内校验 token 绑定版本 == 请求 expected，改 expected 不能复活旧预览（`AI_PREVIEW_EXPIRED`）；有效期在事务内复查；CAS 同时核对原 `content_id` 与 `content_version`。预览凭证绑定本次 app 会话内部随机 scope（非会话密钥），换 app 会话后拒绝旧 token，但成功回执仍可恢复（`AI_PREVIEW_EXPIRED` + 回执 200）。回归：`test_changed_expected_cannot_bypass_preview`、`test_new_app_session_rejects_old_token`、`test_lost_response_and_restart_receipt`、`test_concurrent_different_tokens_single_success`。
3. **R03 旧契约只读按当前 required 判定**：`candidate_applicability`/preview/adopt 用任务当前 required 契约判断，required 升级到 2 后旧 v1 候选详情只读、预览/采用 `AI_CONTRACT_OBSOLETE`；历史基准读取不受影响。回归：`test_old_contract_candidate_readable_but_not_adoptable`。
4. **R04 候选关系链与存储边界**：抽出统一 `require_candidate_chain` 供列表/详情/预览/采用共用，覆盖 execution/task/input 身份、成功执行、候选 hash 与冻结 schema；`baseline_from_model_process` 不再把非 string 静默转空串；SQLAlchemy 行物化阶段 JSON 解码失败（非 JSON 文本）也在读取边界映射为 503（`load_candidate`/列表物化/`task_out`）。回归：`test_failed_execution_blocks_read_preview_adopt`、`test_missing_input_is_storage_error`、`test_tampered_candidate_body_is_storage_error`、`test_malformed_candidate_body_is_storage_error`、`test_non_json_candidate_column_is_storage_error`、`test_baseline_mismatch_and_missing_provenance_rejected`、`test_same_text_different_source_identity`、`test_malformed_candidate_row_is_503`。
5. **R05 候选详情真实来源**：`source` 增加 §5.1 要求的 `dependencies`；其他活动 `source_excerpt` 增加 `game_config`/`daily_plan_snapshot`/`calendar_context`/`target_grade`；列表仍无材料；来源变化错误带安全 `changed_fields`。回归：`test_detail_includes_real_source_and_excerpt`、`test_other_source_excerpt_includes_game_config_and_snapshot`。
6. **R06 来源/目标/无关变化分类**：采用事务按来源 → 目标 → 版本的顺序分类，避免版本冲突提前遮蔽；依赖与目标重叠时来源优先。回归：`test_unrelated_change_is_version_conflict`、`test_target_change_is_target_error`、`test_source_change_is_source_error`、`test_other_activity_overlapping_change_is_source_first`、`test_source_and_target_change_over_http`。
7. **R07 验证质量**：顺序并发用例更名 `test_second_token_rejected_after_first_success` 并注明真实并发另测；新增**真实 COMMIT 边界故障**（内容/provenance/审计/回执 flush 后 `commit` 失败，四类行与计划指针全回滚、同键重试成功）、**真实 HTTP 并发**（异 token 异键单成功；同 token 同键在确定性屏障下必须 200/200 同结果）、丢响应/重启回执、三类 HTTP 采用、strict schema 与 Host/Origin/session/no-store；所有最终自测显式隔离 `LOCALAPPDATA`/`credential_root`、`APP_DISABLE_DOTENV=1`，记录完整日志与实际退出码。
8. **R08 foreign 坏候选统一 404**：`_require_candidate` 改为 `load_candidate_for_plan`，在 SQL 中同时限定 candidate id 与 plan id；foreign/不存在统一 `AI_NOT_FOUND`，本计划坏 JSON 仍 503。回归：`test_foreign_corrupt_candidate_is_404`、`test_foreign_corrupt_candidate_is_404_not_503`。
9. **R09 receipt→token 查询间竞态**：token 缺失时二次复查持久回执；并发同键同 token 的重复请求在提交回执落地后回读 200 而非 `AI_PREVIEW_EXPIRED`。回归：`test_same_token_same_key_replays_under_deterministic_race`（确定性屏障，严格断言 200/200 同结果、一版本一回执）；先失败后通过 probe 见 §2。真正的无回执过期 token 仍 409、异体仍 409（`test_token_expiry_is_enforced`、`test_new_app_session_rejects_old_token`、`test_same_key_different_token_conflicts`）。

## 5. 未验范围与偏差

- **真实供应商（G17）未执行**：无凭据/授权；本轮全部为本机合成 SQLite 与真实 Uvicorn HTTP，未发任何外部 AI 请求。
- **W5 完整界面/教师窗口与 W6 打包/人工 Word 页验未实现**：本轮仅验证相关 DOCX 结构（已采用基准 + 教师再改后导出，`word/document.xml` 含最终过程文本、无 `no_split_baseline` 警告），完整单日/合并 Word 逐页人工查看留待 W6。
- **一次真实睡眠、桌面 UI 交错、干净机器、Win10、WPS、其他 DPI/多显示器、发行再现性**仍未验；微软拼音已验，不重复。
- 并发验证为本机同进程 Uvicorn + SQLite WAL（`busy_timeout=5000`）真实 HTTP，非跨进程/跨机器；异 token 异键的落败请求错误码依赖当时状态为 `AI_TARGET_CHANGED` 或 `VERSION_CONFLICT`（断言二者之一）。
- `docs/tasks/current.md` 与核查记录由 Codex 维护，本文件不改写其结论；W4 未自称通过 Codex 验收。

## 6. 状态声明

W4 生产代码、候选/预览/采用接口、共享校验链、保存/导出读取接通及自动测试已交付并通过本实现者自测（W4 专项 47 项、全 local 470 项、桌面 146 项，均实际退出码 0）；R01–R09 已按 Codex 交回逐项修复并补先失败后通过/确定性回归。Codex 已独立复验边界与 R09 竞态（详见 `desktop-d2-w4-review.md`）；最终工程结论以 Codex 核查记录为准。本文件不代表 D2 产品验收、真实 AI 兼容或发行通过，不启动 W5/W6。下一工作包边界为 W5 界面与宿主整合（未授权）。
