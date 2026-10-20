# D2 W2 实现交付结果（OpenCode）

更新：2026-10-18。本文件记录 D2 W2「游戏配置及提示词」的实现、测试与 W5 接口交接，供 Codex 最终核查。**W1 限定环境工程通过保持不变；W2 代码与自动测试已交付，产品与发行未整体验收。** 仅 W2；未启动 W3–W6、真实应用 AI、发布/安装，未改 `0001–0004` 历史迁移或旧云端 registry 行为，未改 `ARCHITECTURE.md`，未 commit。

授权与边界：延续 `docs/tasks/current.md`（2026-10-18）与用户「Go 套餐 DeepSeek V4.1 Flash」指示；Codex 独立核查并交回定点修复。本轮追加修复 R02（孤立字段 latest-wins）、R03（游戏 `class_games` 落入 `_plan_window` KeyError 与预览封套）、R04（坏包同步失败阻断全新库建档）、R05（OTHER 输入晨间每 kind 约束），均仅在 W2 范围内。

## 1. 本批改动范围

### 1.1 生产代码

| 文件 | SHA256（前 16） | 改动 |
| --- | --- | --- |
| `backend/app/local/prompt_bundles.py` | `4c2874a812174c4e` | 新增：包内三类 bundle 清单（v1/r1 与 0004 冻结内容/哈希逐项一致）、纯输入/输出契约校验、bundle 登记与头同步（`sync_prompt_bundles`）、有效初版种子（`effective_prompt_seed`） |
| `backend/app/local/prompt_service.py` | `bde5c88e257a63ac` | 新增：三类提示词 list/detail/defaults/PATCH/accept/reject/adapt，`local_ai_operations` 回执 |
| `backend/app/local/config_service.py` | `dfeffce4bdb29a35` | 扩展第六变更类 `class_games`：规范化/限额、preview/apply、不可变 revision 与全局 `config_version` 原子推进、只读读取 |
| `backend/app/local/schemas.py` | `5e2e821dbf9dd83b` | 新增 `class_games` 变更模型、提示词请求/响应模型、`game_revision_id`、只读游戏输出 |
| `backend/app/local/api.py` | `82812e98df86bf46` | 新增提示词路由、只读 `/config/class-games`、AI 同步失败仅挡 AI 的守卫 |
| `backend/app/local/errors.py` | `962f3ef8bef58774` | 新增 `PROMPT_*`、`AI_NOT_FOUND`、`AI_REQUEST_CONFLICT`、`PROMPT_BUNDLE_CONFLICT`、`PROMPT_SYNC_UNAVAILABLE` 等错误码 |
| `backend/app/local/profile_service.py` | `3c6b9173a2e4ba50` | 新档案初版个人指导改由**已登记有效 bundle** 建立（不再引用未登记清单） |
| `backend/app/local/runtime.py` | `e67373cdb481ef93` | 启动尽力同步包内 bundle；失败仅记录 `prompt_sync_error`，不阻断启动与手工路径 |

未改动：`models.py`、`migrations_local/versions/20261017_0004_local.py` 及全部历史迁移、`backend/app/services/ai_prompt_registry.py`、W1 已验 `credentials.py`/`ai_config_service.py`/冻结探针与既有包。

### 1.2 测试（`backend/tests/local/`，新增）

| 文件 | SHA256（前 16） | 覆盖 |
| --- | --- | --- |
| `test_d2_w2_prompts.py` | `7b4647be1f7293a1` | 三类可读只读不增版、空文字/8000、字段集严格、r2/r3 部分接受、精确拒绝、required 升级/适配/孤立字段、重复契约演进 latest-wins、同键异 hash、回执优先/跨域/提交失败回滚、请求保护、坏包/健康新库降级 |
| `test_d2_w2_games.py` | `0dbec705666e936f` | 空初版、每类 30 上限/文本/名称、越权与预算、preview 无写、apply 双版本原子、旧计划不变、no-op 只回执、HTTP preview→normalized_change→apply、回执重放/异体冲突/旧版本、提交失败回滚、只读端点 |
| `test_d2_w2_contracts.py` | `1c822b9c73d76719` | 输入/输出纯校验正反例（拆分六必需 string 可空非 null、适龄仅 process、其他活动≥1 板块、晨间输出恰好一集体一自选每组一 game、额外 ID/反思/显式 null 拒绝、UTF-8 1 MiB 字节上限、错误脱敏、OTHER 输入晨间每 kind 0..1）、清单 hash 与 0004 一致 |
| `test_d2_runtime.py`（W1 已有，夹具收尾） | `cf0bf97154a1c306` | `test_dispose_releases_lock_when_engine_dispose_fails` 持有原 engine 并 `addCleanup` 关闭（在 mock 解除后），保持运行锁释放原断言；新增 `test_dispose_failure_leaves_no_open_sqlite_connection` 以 `gc`＋`ResourceWarning` 核查无未关闭连接 |

## 2. 命令与实际结果

统一解释器：`desktop/.venv-d1/Scripts/python.exe`（CPython 3.14.7 Windows x64，标准 GIL）。仅使用合成数据根，凭据根显式注入合成子目录，未打开原教师体验库。

- 定向 W2：
  `python -m unittest tests.local.test_d2_w2_prompts tests.local.test_d2_w2_games tests.local.test_d2_w2_contracts`
  → **58 项 / 10.793 秒 / 退出 0**。
- 全 local 回归（在 `backend/`）：
  `python -m unittest discover -s tests/local -t .`
  → **345 项 / 138.144 秒 / 退出 0**（含 W1 既有 286 项、W2 新增 58 项及本次夹具复测新增 1 项）；日志 `%TEMP%/kgm-d2-w2-opencode-final.txt`，`ResourceWarning` 出现次数 **0**。
- 夹具复测（`test_d2_runtime.RuntimeLifecycleTests`，含 `-W error::ResourceWarning`）→ **6 项 / 退出 0**，无未关闭连接告警；夹具清理改由 `addCleanup` 在 mock 解除后执行，失败路径同样关闭原 engine。
- 包内 hash 一致性：`test_d2_w2_contracts.BundleSeedTests` 断言 `local_prompt_bundles` 三个 r1 `bundle_hash` 与包清单逐项相等，且独立命令比对 0004 冻结常量 `223a77eb…`/`33dd13f4…`/`a952d500…` 一致。

### 2.1 Codex 独立核查证据（由 Codex 执行，不由 OpenCode 覆写）

- 游戏真实 HTTP 15 项全过：`%TEMP%/kgm-d2-w2-codex-games-zwo65ti7`。
- 提示词 HTTP/跨域回执/并发/请求保护/坏包重启降级＋手工实际 DOCX 25 项全过：`%TEMP%/kgm-d2-w2-codex-api-idif2a0y`。
- R03 复现：`%TEMP%/kgm-d2-w2-codex-98lmfxp5/codex-game-first.json`。
- R02 复现：`%TEMP%/kgm-d2-w2-codex-prompts-4bwj3945/codex-evidence.json`。
- R04 复现：`%TEMP%/kgm-d2-w2-codex-fresh-degrade-s9e4ho6w/codex-evidence.json`；R05：`codex-input-first.json`。
- R02/R04/R05 独立复测 20 项全过：`%TEMP%/kgm-d2-w2-codex-final-cases-kitzp5j4/codex-evidence.json`。

## 3. 定点修复对照

| 编号 | 现象 | 修复 | 回归证据 |
| --- | --- | --- | --- |
| R02 | 已移除字段「删除→重新加入并修改→再次删除」时 `setdefault` 保留首次旧文字 | `prompt_service._merge_orphaned` 改为 latest-wins：活动字段从 orphaned 移除，再次删除写入当前最新值；历史版本行不动 | `test_repeated_contract_evolution_keeps_latest_orphan_text` |
| R03 | `class_games` 落入 `_plan_window` 的 `normalized["date"]` KeyError；规范化返回 `kind+payload` 封套不符 D1 预览回填契约 | `_plan_window` 处理 `class_games`；`_normalize_class_games` 返回平铺 `kind/locations/game_scope/guidance`，`_game_payload` 单点构造存储载荷 | `test_preview_normalized_change_applies_over_http` |
| R04 | 坏包同步失败后全新库初始化仍从未登记清单建初版，FK 触发 HTTP 503，手工入口被阻 | `profile_service.initialize` 改用 `effective_prompt_seed(session)`，只引用**已登记** bundle（失败时回退 0004 冻结 r1）；失败仅置 `prompt_sync_error` 挡 AI | `test_bad_pack_fresh_init_uses_registered_bundle_and_degrades_ai`、`test_healthy_new_pack_uses_latest_registered_default_and_restart_keeps_revision` |
| R05 | OTHER 输入 `morning_games` 缺每 kind 计数校验，两个 collective 被接受 | `_DailyPlanSnapshot` 增 after 校验：每 kind 至多一组；null/空列表/单 kind 合法，不改输出“恰好两组”规则 | `test_morning_input_group_counts_at_most_one_per_kind` |
| 夹具 | W2 启动同步使 `test_d2_runtime` 的 `test_dispose_releases_lock_when_engine_dispose_fails` **故障夹具自身未关闭 engine 连接**：它 mock `Engine.dispose` 抛错后生产 `dispose` 已置空指针，原 engine 丢失，其连接被 GC 时报 `ResourceWarning: unclosed sqlite3.Connection`（非业务缺陷，仅测试夹具） | 仅改该测试：持有原 `real_engine` 并在 mock 解除后 `addCleanup(real_engine.dispose)`／`gc.collect`（失败路径也清理），保留运行锁释放原断言；新增无未关闭连接告警专项测试 | 该类 `-W error::ResourceWarning` → 6 项 / 退出 0；全 local `ResourceWarning` 计数 0 |

## 4. G05/G06 覆盖与本轮边界

- **G05（配置/指导版本）**：游戏 revision 与全局 `config_version` 原子推进、no-op 只回执、旧计划/表头逐字段不变；个人指导只读不增版、r2/r3 竞争只覆盖所选字段、拒绝不改文本、required 升级不覆写个人文字、新字段默认预填、删除字段 orphaned、显式 adapt 才解除适配、`local_ai_operations` 全域回执与跨域 409。**通过范围为本地合成 SQLite/HTTP；排队期间改配置、已开始再改、执行钉版本属 W3/W4。**
- **G06（三类输入/输出）**：包内契约与**本地纯校验**（`validate_input`/`validate_candidate`）覆盖题目列出的输出规则及容量上限；输入/输出非对称（输入 OTHER 允许手工空/null，输出可选字段仅省略不得 null）。**任务来源投影、日历 ±7 日、执行版本钉住、候选采用留 W3/W4，未声称完成。**

## 5. W5 接口交接（准确字段与样例）

所有路径接入既有 session/Host/Origin 保护与 `Cache-Control: no-store`；请求体递归 `extra=forbid`，版本为严格正整数；响应错误沿 `{"error":{code,message,details?}}`。

### 5.1 游戏配置（D1 预览/应用扩展）

- `GET /api/local/config/class-games`（本轮新增，只读，W5 设置页预填用）
  - 返回：`{class_id, class_name, grade, config_version, game_revision_id, revision_no, change}`
  - `change` 即应用就绪体：`{kind:"class_games", locations:[{kind:"area"|"special_room"|"outdoor", name, guidance|null}], game_scope|null, guidance|null}`
  - 样例：`{"class_id":"…","config_version":1,"revision_no":1,"change":{"kind":"class_games","locations":[],"game_scope":null,"guidance":null}}`
  - 不写版本；无范围/偏移参数。
- `POST /api/local/config/preview`、`POST /api/local/config/apply` 沿用 D1 字段，新增 `change.kind=class_games`（当前班级由服务端取得，**不接收 `class_id`**）。
  - `normalized_change` 为平铺 `class_games` 对象，可由客户端直接回填 apply 的 `change`。
  - apply 成功响应新增可选 `game_revision_id`；`calendar_revision_id` 对 `class_games` 为 `null`。
  - 限额：每类最多 30 个地点、名称 1–80、单项指导 ≤2000、`game_scope`/`guidance` 各 ≤8000；`""` 与 `null` 均表示空文字（no-op 等价）。
  - no-op：`status="unchanged"`、不增 `config_version`/不新增 revision；同 `request_id` 重传读回原回执；异体同键 409 `CONFIG_REQUEST_CONFLICT`；版本不符 409 `CONFIG_VERSION_CONFLICT`。
- `GET /api/local/config/operations/{request_id}`：只读回执。

### 5.2 提示词（仅三类日任务）

- `GET /api/local/ai/prompts` → `{items:[PromptOut]}`；`GET /api/local/ai/prompts/{T}` → `PromptOut`
  - `PromptOut={task_type, personal_revision, contract_version, based_default_revision, required_contract_version, latest_default_revision, guidance:{field:text}, fields:[{key,label,default_text}], rejected_default_revision|null, adaptation_required, orphaned_guidance:{field:text}}`
  - `fields` 取自当前 required 契约的 latest 默认；`orphaned_guidance` 的已移除字段保留**最新**教师文字。
- `GET /api/local/ai/prompts/{T}/defaults/{contract_version}/{default_revision}` → `{task_type, contract_version, default_revision, guidance, fields, bundle_hash}`；不存在 404 `AI_NOT_FOUND`。
- `PATCH /api/local/ai/prompts/{T}`：`{request_id, expected_personal_revision, contract_version, guidance}`；完整当前契约字段 map，每字段 0..8000；未知/缺字段 422；需适配时普通编辑仍写旧契约（`contract_version` 不符且等于 required → 409 `PROMPT_ADAPTATION_REQUIRED`，否则 409 `PROMPT_CONTRACT_CHANGED`）。
- `POST /api/local/ai/prompts/{T}/accept-default`：`{request_id, expected_personal_revision, target_contract_version, target_default_revision, selected_fields}`；仅覆盖所选字段并绑定实际查看修订；同契约更晚默认不使该目标失效、也不一并接受。
- `POST /api/local/ai/prompts/{T}/reject-default`：`{request_id, expected_personal_revision, target_contract_version, target_default_revision}`；记录该修订、不改 guidance、不解除 required 适配。
- `POST /api/local/ai/prompts/{T}/adapt`：`{request_id, expected_personal_revision, target_contract_version, target_default_revision, guidance}`；目标 contract 必须当前 required，否则 409；成功后仅当目标字段集变化时把旧字段并入 orphaned。
- 回执：幂等检查先于 expected 版本/契约检查；同键异域/异体 409 `AI_REQUEST_CONFLICT`；成功回执可经 `GET /api/local/ai/operations/{request_id}` 读取。GET 只读不写版本。
- 同步降级：启动包同步失败时，上列 AI 提示词端点返回 503 `PROMPT_SYNC_UNAVAILABLE`（`details.reason` 为内部码），手工读/写/导出不受影响。

### 5.3 无内容/接受拒绝/适配语义摘录（供 W5 绑定）

- 无内容变化或重复动作 → 不增 `personal_revision`。
- `accept` 的 `based_default_revision` 置为所选目标；`latest_default_revision` 可更晚（待处理），不视作已拒绝。
- `reject` 置 `rejected_default_revision`；后续编辑/接受沿用该值（同契约）。
- `required` 契约升级后 `adaptation_required=true`；只有显式 `adapt` 到当前 required 才转 false；adapt 跨契约不携带旧契约的拒绝修订（FK 约束）。

## 6. 规格偏差与未验项

- W2 只交付游戏配置与提示词（G05 相关、G06 包内契约/纯校验）；**任务提交/transport/执行许可/关闭收口（W3）、候选与采用（W4）、设置页 UI（W5）、导出与打包（W6）、真实供应商（G17）均未实现或未验**，不得据本文件记为通过。
- 未调用任何真实应用 AI/供应商、未发布/安装、未运行真实教师库存迁移、未改历史迁移与旧 registry。
- 只读端点 `GET /api/local/config/class-games` 已由 Codex 补入工程规格 §5.2；本实现与其一致（只读读取，不改变任何既有 D1 写入契约）。
- `fields[].label` 当前取字段 key；中文展示由 W5 常规界面实现处理，不作为单独产品需求。
- 干净机器、Win10、WPS、其他 DPI/多显示器、WebDAV 与发行再现性仍未验。原教师体验根 `%TEMP%/kgm-d1-teacher-experience-20261017-104847`、exports、D1 `c6dc1928…` 包、W1 `6a283bdf…` 包未改动。

## 7. 状态声明

W2 代码、纯校验与测试已交付并自验；Codex 已独立复测 R02/R03/R04/R05（`kgm-d2-w2-codex-final-cases-kitzp5j4`）。本文件收齐改动清单、命令与实际结果、W5 接口交接与边界；**W2 是否关闭以 Codex 审阅结论为准**。本文件不代表 D2 产品验收，不启动 W3–W6、真实 AI 或发行。本批到此停止代码修改，交审。
