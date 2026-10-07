# 基础配置与提示词 1A 实施清单（2026-10-03 协调者设计定稿 v3）

状态：本文保留 2026-10-03 v3 工程定稿与当时预检基线。1A 已实现并通过 [阶段收口](ai-slice1a-closeout-review-2026-10-04.md)，实际部署见 [部署结果](ai-slice1abc-deployment-result-2026-10-05.md)。本文本身不构成重新编码或验收授权。依据链：AGENTS.md → ARCHITECTURE.md → ADR 0002 → AI Service／提示词／日志 Contract → 四份协同规格（[AI Service](../specs/ai-service-implementation.md)／[提示词](../specs/prompts-implementation.md)／[持久任务](../specs/persistent-ai-tasks-implementation.md)／[材料](../specs/weekly-materials-implementation.md)）→ 现有代码（`backend/app/models.py` 17 表、迁移链 head `20260924_i4_weekly_plans`、`backend/app/services/auth_service.py` 的 `record_operation` 与 `_lock_account`、`backend/app/services/daily_plan_service.py` 的锁与事务模式、`backend/tests/integration/i3_guard.py`／`i4_guard.py`／`i5_guard.py` 隔离模式、`backend/app/config.py`）。

开工前 git 状态已重录：HEAD `1647fc9`；当时已有 7 份文档未提交修改 + 1 份未跟踪准备文件，全部保留不动。未读 `.env`、未连数据库、未安装依赖、未启动服务、未调用供应商、未 commit／push。预检未做任何业务写入；本文件本身是文档，不构成编码授权。v2为OpenCode补正版；v3由协调者按用户授权收敛设计，取代v2冲突规则。此为实施前预检记录；现行阶段判断见上方收口报告。

## 0. 范围声明

1A 交付：7 张新表 + 迁移（含固定快照种子）、7 类任务 registry（输入变量／输出 schema／指导字段及默认正文）、默认指导与个人指导版本化服务、配置版本与加密服务、URL 离线校验、就绪判定与供执行器调用的版本解析接口、设置变更审计落库；纯服务层，无 API、无 UI、无 worker、无 transport（HTTP 客户端／DNS 钉住）、无候选落库、无材料业务。

不改变架构（P1–P4 均已确认，无 ADR 需求）；若编码中发现必须改动模块边界，停下提 ADR 草案。

## 1. 实际修改文件清单

| # | 文件 | 操作 | 内容 |
| --- | --- | --- | --- |
| 1 | `backend/app/models.py` | 修改 | 追加 7 个模型类（§2），不动既有任何模型 |
| 2 | `backend/migrations/versions/20261003_ai1a_config_prompts.py` | 新增 | 建表 + `prompt_contract_versions`（contract_version=1 ×7）／`prompt_default_versions`（default_revision=1 ×7）**固定快照种子**（§2.9），downgrade 照 I4 模式抛 `RuntimeError` 阻断 |
| 3 | `backend/app/services/ai_prompt_registry.py` | 新增 | 7 类任务 registry（§3）：task_type、输入变量声明、候选输出 schema、允许指导字段、默认正文常量；未知任务／字段、非法结构拒绝；候选 schema 与业务保存 schema 显式分型 |
| 4 | `backend/app/services/ai_config_url.py` | 新增 | HTTPS base_url 规范化与离线校验 |
| 5 | `backend/app/services/ai_crypto.py` | 新增 | 加密、密钥材料惰性加载与降级（§5.1–5.3） |
| 6 | `backend/app/services/ai_config_service.py` | 新增 | 配置版本追加、expected_version 并发、secret 仅写／保留重加密／轮换／清除、ready 判定、钉住与最新版本读取、脱敏视图类型（§4.1、§5.4） |
| 7 | `backend/app/services/prompt_service.py` | 新增 | 个人指导修订式 CRUD、默认接受／拒绝／按字段接受、必需字段适配、首次初始化、就绪与版本解析、管理员默认修订追加（§4.2、§7） |
| 8 | `backend/app/config.py` | 修改 | 新增可选 `ai_master_key`／`ai_master_key_id`（SecretStr，默认空＝降级态）；惰性使用，格式错误不在启动期抛错（§5.2） |
| 9 | `backend/pyproject.toml` | 修改 | 直接声明 `cryptography==50.0.1`（与既有间接锁定一致，不升级、不引入 HTTP 客户端） |
| 10 | `backend/uv.lock` | 修改 | 仅项目包元数据区反映新直接依赖；`cryptography` 保持 50.0.1，不动其他节点 |
| 11 | `backend/tests/unit/test_ai1a_url_crypto.py` | 新增 | URL 校验与加密单元用例（§9.1） |
| 12 | `backend/tests/unit/test_ai1a_registry_defaults.py` | 新增 | registry 覆盖 7 类、字段限制、默认文案与种子一致性 |
| 13 | `backend/tests/integration/ai1a_guard.py` | 新增 | 独立 guard（§9.2；在任何测试连接或迁移连接之前生效） |
| 14 | `backend/tests/integration/test_ai1a_config_prompts.py` | 新增 | 迁移兼容 + 事务并发隔离验证（§9.2） |

零修改：`backend/app/routers/`、`backend/app/schemas.py`、`frontend/`、既有迁移文件、`word_export_*`、其他 `docs/`（当前未提交文档保持原样）。

## 2. 表结构（列／FK／CHECK／唯一键与迁移）

全部 InnoDB / utf8mb4 / utf8mb4_unicode_ci；主键均为 `id String(32)`（binary collation），ID 由 `security.generate_id()` 生成（复用既有安全模块）。版本数均为INT，可空性以逐表定义为准，非空值均须>=1；时间列DateTime NOT NULL，模型UTC默认，迁移种子显式传UTC时间。

### 2.1 `ai_config_versions`（append-only；行创建后不改写）

| 列 | 类型 | nullable | 约束 |
| --- | --- | --- | --- |
| id | String(32) | NOT NULL | PK |
| account_id | String(32) | NOT NULL | FK accounts.id；index |
| version | INT | NOT NULL | CHECK `version >= 1`（ck_ai_config_versions_version） |
| protocol_id | VARCHAR(50) | NOT NULL | CHECK `IN ('chat_completions_v1')`（ck_ai_config_versions_protocol） |
| base_url | VARCHAR(500) | NOT NULL | （规范化后存；规范化在服务层先行完成） |
| model | VARCHAR(200) | NOT NULL | — |
| secret_ciphertext | TEXT | 可 NULL（NULL＝该版本无密钥） | — |
| key_id | VARCHAR(64) | 可 NULL | CHECK `(secret_ciphertext IS NULL AND key_id IS NULL) OR (secret_ciphertext IS NOT NULL AND key_id IS NOT NULL)`（ck_ai_config_versions_secret_key） |
| operation_record_id | String(32) | NOT NULL | FK operation_records.id（每版本行记录产生它的那次审计） |
| created_by | String(32) | NOT NULL | FK accounts.id |
| created_at | DateTime | NOT NULL | default UTC |

唯一键：`UNIQUE(account_id, version)`（uq_ai_config_versions_account_version；同时支持按版本钉住读取与 heads 复合 FK）。

### 2.2 `ai_config_heads`（每账号至多一行当前指针）

| 列 | 类型 | nullable | 约束 |
| --- | --- | --- | --- |
| account_id | String(32) | NOT NULL | PK；FK accounts.id |
| config_version | INT | NOT NULL | CHECK `config_version >= 1`（ck_ai_config_heads_version） |
| updated_at | DateTime | NOT NULL | default UTC |

复合 FK：`(account_id, config_version)` → `ai_config_versions(account_id, version)`（fk_ai_config_heads_current；head 不可能指向他人版本，DB 强制）。head 不存在→服务层 expected_version 语义为 0（§4.1）。可空性：本表无业务可空列。

### 2.3 `prompt_contract_versions`（append-only；字段协议）

| 列 | 类型 | nullable | 约束 |
| --- | --- | --- | --- |
| id | String(32) | NOT NULL | PK |
| task_type | VARCHAR(50) | NOT NULL | CHECK `IN ('daily_lesson_split','daily_process_adapt','daily_other_activities','weekly_games','weekly_columns','weekly_theme_suggestion','weekly_materials')`（ck_prompt_contract_versions_task_type） |
| contract_version | INT | NOT NULL | CHECK `>= 1` |
| input_vars | JSON | NOT NULL | — |
| output_schema | JSON | NOT NULL | — |
| guidance_fields | JSON | NOT NULL | — |
| created_by | String(32) | 可 NULL（种子＝系统发布；后续协议发布也属于系统迁移，不伪造管理员操作） | FK accounts.id |
| created_at | DateTime | NOT NULL | default UTC |

唯一键：`UNIQUE(task_type, contract_version)`（uq_prompt_contract_versions_task_contract）。

### 2.4 `prompt_default_versions`（append-only；默认指导修订）

| 列 | 类型 | nullable | 约束 |
| --- | --- | --- | --- |
| id | String(32) | NOT NULL | PK |
| task_type | VARCHAR(50) | NOT NULL | 同 2.3 CHECK 7 类（ck_prompt_default_versions_task_type） |
| default_revision | INT | NOT NULL | CHECK `>= 1` |
| contract_version | INT | NOT NULL | 复合 FK `(task_type, contract_version)` → 2.3（fk_prompt_default_versions_contract） |
| guidance_map | JSON | NOT NULL | 字段集须覆盖该协议 guidance_fields 全部字段（服务层强制，§2.8 分工） |
| created_by | String(32) | 可 NULL（种子迁移行＝系统，PF-2） | FK accounts.id |
| created_at | DateTime | NOT NULL | default UTC |

唯一键：`UNIQUE(task_type, default_revision)`。

### 2.5 `personal_prompt_versions`（append-only；本人指导版本）

| 列 | 类型 | nullable | 约束 |
| --- | --- | --- | --- |
| id | String(32) | NOT NULL | PK |
| account_id | String(32) | NOT NULL | FK accounts.id；index |
| task_type | VARCHAR(50) | NOT NULL | CHECK 7 类 |
| personal_revision | INT | NOT NULL | CHECK `>= 1` |
| guidance_map | JSON | NOT NULL | 字段集与 based contract 的 guidance_fields 完全一致（服务层强制）；单字段 ≤8000 字符（服务层 CHAR_LENGTH 校验，依据提示词规格 §5） |
| based_contract_version | INT | NOT NULL | 复合 FK `(task_type, based_contract_version)` → 2.3（fk_ppv_contract） |
| accepted_default_revision | INT | NOT NULL | 复合 FK `(task_type, accepted_default_revision)` → 2.4（fk_ppv_default） |
| created_by | String(32) | NOT NULL | FK accounts.id（＝本人） |
| created_at | DateTime | NOT NULL | default UTC |

唯一键：`UNIQUE(account_id, task_type, personal_revision)`；索引 `(account_id)`。

### 2.6 `personal_prompt_heads`（每 (account, task_type) 至多一行）

| 列 | 类型 | nullable | 约束 |
| --- | --- | --- | --- |
| account_id | String(32) | NOT NULL | 联合 PK 之一；FK accounts.id |
| task_type | VARCHAR(50) | NOT NULL | 联合 PK 之一；CHECK 7 类 |
| current_personal_revision | INT | **NOT NULL** | 复合 FK `(account_id, task_type, current_personal_revision)` → 2.5（fk_pph_current）；CHECK `>= 1`（ck_pph_current_revision） |
| adaptation_state | VARCHAR(30) | NOT NULL | CHECK `IN ('current','adaptation_required')`（ck_pph_adaptation_state） |
| required_contract_version | INT | 可 NULL（仅 'current' 态可为 NULL） | CHECK `(adaptation_state = 'current' AND required_contract_version IS NULL) OR (adaptation_state = 'adaptation_required' AND required_contract_version IS NOT NULL AND required_contract_version >= 1)`；复合FK `(task_type, required_contract_version)` → `prompt_contract_versions(task_type, contract_version)`（ck_pph_adapt_ref；**已修正**：显式 `IS NOT NULL`，堵住 MySQL CHECK 对 `NULL >= 1` 结果为 NULL 即放行的漏洞） |
| last_seen_default_revision | INT | 可 NULL | CHECK `(last_seen_default_revision IS NULL) OR (last_seen_default_revision >= 1)` |
| last_rejected_default_revision | INT | 可 NULL | CHECK `(last_rejected_default_revision IS NULL) OR (last_rejected_default_revision >= 1)` |
| created_at / updated_at | DateTime | NOT NULL | default UTC |

有效适配状态以个人版本based_contract_version和最新协议比较为权威；以下约束针对成功写事务对齐的head，不要求未触碰的历史缓存随协议发布全量更新：`adaptation_state='current'` 时，`current_personal_revision` 所属个人版本行的 `based_contract_version` 必须等于当时的最新 contract_version；`adaptation_state='adaptation_required'` 时，`required_contract_version` 必须等于当时的最新 contract_version 且大于该版本行的 `based_contract_version`。

### 2.7 `prompt_change_records`（append-only 审计明细）

| 列 | 类型 | nullable | 约束 |
| --- | --- | --- | --- |
| id | String(32) | NOT NULL | PK |
| operation_record_id | String(32) | NOT NULL | FK operation_records.id |
| task_type | VARCHAR(50) | NOT NULL | CHECK 7 类（ck_pcr_task_type） |
| event_kind | VARCHAR(30) | NOT NULL | CHECK `IN ('default_update','personal_init','personal_edit','accept_default','reject_default','adapt')`（ck_pcr_event_kind） |
| personal_revision_before | INT | 可 NULL | CHECK `(… IS NULL) OR (… >= 1)` |
| personal_revision_after | INT | 可 NULL | 同上 |
| default_revision_target | INT | 可 NULL | CHECK `(… IS NULL) OR (… >= 1)` |
| contract_version_target | INT | 可 NULL | CHECK `(… IS NULL) OR (… >= 1)` |
| changed_fields | JSON | NOT NULL | 字段名列表，不含正文；init／adapt为完整字段集，edit／default_update为本次提交字段，accept为选定字段，reject为[]（服务层强制） |
| created_at | DateTime | NOT NULL | default UTC |

事件形态条件 CHECK（拒绝行 before＝after、版本可相同；v2 新增 6 条）：

- ck_pcr_default_update：`event_kind<>'default_update' OR (personal_revision_before IS NULL AND personal_revision_after IS NULL AND contract_version_target IS NOT NULL AND default_revision_target IS NOT NULL)`
- ck_pcr_personal_init：`event_kind<>'personal_init' OR (personal_revision_before IS NULL AND personal_revision_after IS NOT NULL AND default_revision_target IS NOT NULL AND contract_version_target IS NOT NULL)`
- ck_pcr_personal_edit：`event_kind<>'personal_edit' OR (personal_revision_before IS NOT NULL AND personal_revision_after IS NOT NULL AND personal_revision_after <> personal_revision_before AND default_revision_target IS NULL AND contract_version_target IS NULL)`
- ck_pcr_accept_default：`event_kind<>'accept_default' OR (personal_revision_before IS NOT NULL AND personal_revision_after IS NOT NULL AND personal_revision_after <> personal_revision_before AND default_revision_target IS NOT NULL AND contract_version_target IS NOT NULL)`
- ck_pcr_reject_default：`event_kind<>'reject_default' OR (personal_revision_before IS NOT NULL AND personal_revision_after IS NOT NULL AND personal_revision_after = personal_revision_before AND default_revision_target IS NOT NULL AND contract_version_target IS NOT NULL)`
- ck_pcr_adapt：`event_kind<>'adapt' OR (personal_revision_before IS NOT NULL AND personal_revision_after IS NOT NULL AND personal_revision_after <> personal_revision_before AND default_revision_target IS NOT NULL AND contract_version_target IS NOT NULL)`；“contract_version_target 为该事件所属任务**当时最新** contract_version”超出表级 CHECK 表达力，由服务层在同一事务内断言（配合 §6.2/§7.4 的重读核对）。

索引 `(operation_record_id)`、`(task_type)`。修订列不加FK（历史日志语义，版本不删除）；changed_fields与事件字段集合在服务层验证，不保存指导正文。

### 2.8 FK／CHECK 强制 vs 服务事务强制的分工

| 不变式 | 强制层 |
| --- | --- |
| head 指针＝本人版本（配置与个人提示词） | **FK 复合强制**（fk_ai_config_heads_current、fk_pph_current） |
| 版本/修订正整数、事件枚举、事件形态列组合 | **CHECK 强制** |
| 默认/个人修订必挂同一 task 的既有协议；accepted default 指向该 task 的既有修订 | **FK 复合强制**（fk_prompt_default_versions_contract、fk_ppv_contract、fk_ppv_default） |
| 每 (account,task) 至多一个 head；每 (account,task,revision) 恰一版本行 | **唯一约束强制** |
| guidance_map 字段集与协议 guidance_fields 一致；单字段 ≤8000 字符；候选结构中的非空text及枚举 | **服务事务强制**（JSON 内部不可 CHECK） |
| 版本行 + head 指针 + operation_records + 变更明细行同事务原子提交（含首次初始化） | **服务事务强制**（“首次初始化不能提交残缺head”：先写首版personal_prompt_versions再写NOT NULL指针head，二者同事务，任一失败整体回滚；FK 保证 head 不指他人版本，事务保证无 head 无版本） |
| 操作者身份、本人隔离、目标归属、事件行与版本行的修订引用一致 | **服务事务强制**（§7） |

### 2.9 迁移种子为固定版本快照

- 种子（contract_version=1 ×7，default_revision=1 ×7）以**逐字段字面量**写入迁移文件（作者时从 registry 复制的固定快照），迁移文件 `import` 不依赖运行时 `ai_prompt_registry` 模块；此后 registry／默认正文的任何变化都**追加新 contract_version / default_revision**（经审阅的新迁移 + registry 同步），不改写历史种子行。
- 种子行 `created_by=NULL`（PF-2，工程建议）；`operation_records` 不受种子影响（系统发布不写账号审计）。
- 一致性验证：集成测试比较“种子行 == 1A registry v1/revision 1 快照”；后续 registry 演进时该测试随新迁移同步推进，作为双方（迁移与 registry）漂移检查，不定义跨代一致性。
- downgrade 阻断（照 I4 模式）；两条库形态（空库、含 I1–I4 代表行）均需 `upgrade head` 验证。

## 3. 7 类任务 registry（完整定义）

协议分工：系统组装顺序 = 字段协议 → 个人指导 → 业务输入数据；个人指导只覆盖 guidance_fields 内文字；字段名、输出 JSON 结构、来源身份、权限、版本与确认逻辑不可由个人文字改写。输出候选 schema 与业务保存 schema 显式分型（如日拆分候选≠`adopted_content` 直存；采用时另按既有业务校验）；新建对象的group_id／game_id／candidate_id／item_id由服务端分配，不能由模型生成；周游戏选择只允许原样引用输入已有source_ref及group/game身份，须校验全部匹配。

**统一schema规则**：注册器使用项目已有Pydantic表达并导出JSON schema，不新增jsonschema库。候选递归extra=forbid、strict类型；每个输入变量必须声明必需性，除明确可null项外不接受null。grade均为small/middle/large，引用ID均为非空字符串、ISO日期必须有效，int不接受bool。input_vars保存结构及来源声明；不在1A构建真实业务输入。嵌套业务快照沿用现有只读结构，不调用prepare_content分配ID或写计划。结构校验与动态来源校验分别标注：1A执行结构验证；真实来源集合／quote核对由未来业务执行层完成，不能把占位引用通过当作来源已验。

**长度限制依据标注**（适用于 §3 全表）：
- `grade` 枚举 `small/middle/large`：**既有规则**（`config_normalize.normalize_grade` + `classes.ck_classes_grade`）。
- `group_kind ∈ {collective, free_choice}`、`context_kind ∈ {area, outdoor, special_room}`：**既有 I3 校验**（`daily_plan_content.py`）。
- 晨间游戏组数量 `≤1 集体 + ≤1 自选`：**既有 I3 校验**（`_check_morning_group_counts`）。
- 文本字段长度（涉及主题、目标、过程等业务文本）：**既有代码未规定上限**——I3／I4 内容校验对 JSON 内字符串无 max；transport后续按请求／响应1MiB总限额兜底，迁移不负责网络字节限额（**AI Service 规格 §3 工程限额**）。1A 对这些字段**不新增输出长度上限**，维持既有未规定状态，不改变手工保存行为；如需收紧，须回到业务切片单独决定。
- 个人指导单字段 ≤8000 字符：**规格工程限额**（提示词规格 §5）。
- 材料任务 items 100 项／text 300 字符／quote 2000 字符／总 20000 字符：**已写明规格**（材料规格 §3 工程限额）。
- 补足游戏（insufficient_supplements）数量：**既有规格未见限定**——1A 候选校验不新增数量上限（标"未规定"），依赖 1MiB 响应限额及业务第二层校验兜底。

### 3.1 `daily_lesson_split`

| 输入变量 | 类型 | 来源 |
| --- | --- | --- |
| raw_lesson_plan | str | 该日计划某内容版本的 `daily_plan_contents.raw_lesson_plan`（服务端按执行时钉住版本读取） |
| grade | enum(small/middle/large) | `classes.grade` |

输出候选：必需 key `group_activity`，单对象；全部 6 字段必需出现且为字符串，可为空字符串＝“原文未写”；**不以空串伪造有内容**；无列表字段、无枚举字段（`grade` 枚举在输入侧）。空候选规则：对象不可缺、字段可空。

指导字段与中文默认正文（v3协调者已核对覆盖和可理解性，作为首版实现文案；不表述为用户逐条确认的教学规则，不影响手工路径）：

| 字段 | 默认正文（首版实现文案） |
| --- | --- |
| theme | “从原始教案中摘出集体活动的活动主题名称；只用教案已有的表述；教案未写主题时输出空字符串，不要编造。” |
| objectives | “从原始教案摘出活动目标；保留原文语句与顺序，多条用换行分隔；未写时输出空字符串。” |
| preparation | “从原始教案摘出活动准备内容（物质准备、经验准备等）；保留原文表述；未写时输出空字符串。” |
| key_points | “从原始教案摘出活动重点；保留原文语句；未写时输出空字符串。” |
| difficult_points | “从原始教案摘出活动难点；保留原文语句；未写时输出空字符串。” |
| process | “从原始教案摘出活动过程，保持原文的动作步骤顺序和语句，不补写教案里没有的环节；未写时输出空字符串。” |

### 3.2 `daily_process_adapt`

| 输入变量 | 类型 | 来源 |
| --- | --- | --- |
| process_source | str | 拆分基准候选中的 process（或该日计划当前已存 process），由业务模块在执行时读取 |
| grade | enum(small/middle/large) | `classes.grade` |

输出候选：必需key `process`，字符串；空串表示未生成可用过程，不代表“无需调整”，后续采用不能用空候选清空原过程。无需调整时返回输入过程原文。

指导字段与默认正文（首版实现文案）：

| 字段 | 默认正文 |
| --- | --- |
| process | “根据班级年级调整输入活动过程的年龄适宜性，保留活动主题和主要教学意图，可调整表达、步骤和难度。返回完整的调整后过程；无需调整时返回原过程。结果供教师比较和选择，不编造已发生的课堂事实。” |

### 3.3 `daily_other_activities`

| 输入变量 | 类型 | 来源 |
| --- | --- | --- |
| plan_date | str（ISO 日期） | 该日计划 plan_date |
| week_number | int ≥1 | 既有周次算法（执行时按当日配置计算） |
| calendar_state_ref | str | 该学期当前持久有效日历版本（服务端构建） |
| weekday | int，ISO 1–7 | plan_date对应星期 |
| class_grade | enum(small/middle/large) | classes.grade |
| holiday_context | list[{date: ISO日期字符串, name: 非空字符串}]，允许[] | 服务端按有效日历＋库支持的节日名称构建前后各7日窗口；未覆盖不猜测，不新增说明或外部来源 |
| class_game_config_ref | str或null | 后续班级游戏配置版本引用；1A不建实体，来源未实现时明确null，不伪造版本；执行输入构建留业务片 |
| daily_plan_snapshot | JSON对象 | 本次目标日计划钉住版本的内容快照，沿用I3结构，不是同班他人计划的隐式集合 |

输出候选：四个section均可省略，不接受显式null（省略表示未生成该部分）。对象递归拒绝未知字段；不接受group_id／game_id／reflection／morning_exercise_label。候选字符串严格为str，不转换数字或布尔值。

- `morning_games`：list，可空；每组必需group_kind（collective/free_choice）和games（非空list[{name:非空且非全空白字符串}]）；可省略字符串focus_guidance／shared_objectives／guidance_points，出现时可为空串；每种group_kind最多一组。
- `morning_talk`：单对象；必需字符串topic／questions，允许空串。
- `post_group_games`：list，可空；每组必需context_kind（area/outdoor/special_room）和非空games（同上）；可省略字符串area／focus_guidance／objectives／guidance／support_strategy，出现时允许空串。
- `afternoon_outdoor`：**单对象**；必需非空games（同上）；可省略字符串area／observation_focus／objectives／guidance／support_strategy，出现时允许空串；无context_kind。沿用既有AfternoonOutdoorModel业务形态。
- {}是合法空候选，不冒充生成完成。未注明的文本及列表上限保持未规定；games及name非空是候选有效性要求，不收紧手工保存schema。
- 不含reflection；morning_exercise_label不属模型输出，1A不实现其业务写入。

指导字段与默认正文（首版实现文案）：

| 字段 | 默认正文 |
| --- | --- |
| morning_games | “根据日期、周次、班级年级、可用游戏配置和当前日计划，提出晨间集体与自选／自主游戏建议，可含共用目标、指导要点和重点指导。可生成新游戏建议，不伪造日计划引用或活动事实。节日仅供参考，不强制安排节日活动。” |
| morning_talk | “根据日期、周次、班级年级和当前日计划，提出晨间谈话话题与问题，与当天活动自然衔接。节日只作可选参考，不强制安排节日谈话；无可用建议时输出空字符串。” |
| post_group_games | “根据班级年级、可用游戏配置和当前日计划，生成集体活动之后的室内区域／户外／专用室游戏建议，可含目标、指导和支持策略。可提出新游戏建议，不把生成内容声称为真实日计划来源。节日仅供参考。” |
| afternoon_outdoor | “根据班级年级、可用户外游戏配置和当前日计划，生成一组下午户外游戏安排建议，可含区域、游戏名称、观察重点、目标、指导和支持策略。可提出新游戏建议，不伪造真实来源或活动事实。节日仅供参考。” |

### 3.4 `weekly_games`

| 输入变量 | 类型 | 来源 |
| --- | --- | --- |
| week_source_manifest | list（来源候选集合快照） | 服务端由该周全班日计划构建（既有 `weekly_plan_content.build_source_candidates` 同源数据模型） |
| current_draft_snapshot | JSON | 当前周计划草稿的已选槽位内容（服务端读取） |
| class_grade | enum(small/middle/large) | `classes.grade` |
| class_game_config_ref | 同 3.3 说明 | 未建的班级游戏配置版本 |

输出候选：顶层collective_1／collective_2／free_choice_1／focus_area／insufficient_supplements五个key全部必需，禁止额外字段。

- `collective_1`／`collective_2`／`free_choice_1`：各可为 null（=缺项候选，该业务本来就允许缺项）；非 null 时 `{source_ref, game_id, group_id, name}`，其中source_ref／game_id／group_id是引用输入已有身份而非生成新身份，必须严格命中 week_source_manifest 中的某个候选（服务端验证）；目标／指导由服务端从源整组读取填入，不信任模型重写。
- `focus_area`：null或同样的{source_ref, game_id, group_id, name}对象，四项必需且为非空字符串；引用重点区域候选集合，由服务端回填完整区域／目标／指导／支持策略，不让模型输出改写的来源正文。
- `insufficient_supplements`：list，元素 `{target_slot, name, objectives, guidance_points}`，四项必需；target_slot枚举collective_1/collective_2/free_choice_1/focus_area，后三项为非空且非全空白字符串；用于把补足建议关联到缺项，具体采用和AI补足来源结构留业务片，kind 由服务端固定 'ai'，无日引用；数量未规定（依赖 1MiB 响应限额 + 业务第二层兜底）。

指导字段与默认正文（首版实现文案）：

| 字段 | 默认正文 |
| --- | --- |
| collective_selection | “从本周全班日计划的晨间集体游戏候选中，选出两项最贴合本周主题的集体游戏；只能引用候选集合中真实存在的来源；候选不足时对应槽输出null，补足建议写insufficient_supplements，不虚构日计划来源。” |
| free_choice_selection | “从本周全班日计划的晨间自选／自主游戏候选中，选出当周自选游戏；只能引用候选集合中的真实来源；候选不足时对应槽输出null，补足建议写insufficient_supplements，不虚构。” |
| focus_area_selection | “从本周全班日计划中集体活动之后的区域／户外／专用室游戏候选里，选出本周重点区域；只能引用真实存在的候选来源，保持其所属区域与游戏完整对应，不跨来源拼接目标与指导；候选不足时对应槽输出null，补足建议写insufficient_supplements。” |
| insufficient_supplement | “仅在缺少候选且需要补足时，根据本周主题与班级年级补充游戏名称、目标与指导要点；target_slot指明需补足的槽位，补足内容会标为AI补充，不得写成来自日计划的引用，不模仿日计划口吻虚构来源。” |

### 3.5 `weekly_columns`

| 输入变量 | 类型 | 来源 |
| --- | --- | --- |
| week_daily_plans_snapshot | list | 该周全班日计划内容快照（服务端读取） |
| valid_date_context | JSON | 本周上课日列表、学期归属与周次（服务端构建） |

输出候选：4 个必需 key `key_week_focus`／`environment_setup`／`habit_culture`／`home_cooperation`，各为字符串，可为空字符串＝无该条内容；全部 key 必须出现（**空候选规则**：字段值为空串而非 key 缺省，避免结构歧义）。

指导字段与默认正文（首版实现文案）：

| 字段 | 默认正文 |
| --- | --- |
| key_week_focus | “根据本周全班日计划与有效日期上下文，概括本周工作重点；内容应来自本周计划实际出现过的活动方向，不虚构未出现过的内容；无把握时输出空字符串。” |
| environment_setup | “根据本周日计划中出现的游戏与活动，提出教室／区域环境创设的调整建议；只能基于本周已有活动内容推导，不新增未出现过的主题要求。” |
| habit_culture | “根据本周日计划的作息与活动安排，提出生活习惯培养要点；内容贴合本班真实安排，无把握时留空。” |
| home_cooperation | “根据本周日计划，提出家园共育建议，例如家长可配合的事项；建议应具体可行，不新增教学或流程要求，无把握时留空。” |

### 3.6 `weekly_theme_suggestion`

| 输入变量 | 类型 | 来源 |
| --- | --- | --- |
| week_daily_plans_snapshot | list | 该周全班日计划内容快照 |
| current_theme_context | str（允许空字符串） | 当前草稿已有主题或空 |

输出候选：必需 key `theme_suggestion`（非空字符串；空即无意义候选；**空候选不允许**——若模型输出空字符串则该次输出按 output_invalid 处理）。

指导字段与默认正文（首版实现文案）：

| 字段 | 默认正文 |
| --- | --- |
| theme_suggestion | “根据本周日计划内容，提出一个适合本周的主题名称建议；把名称写入theme_suggestion字段，遵守系统JSON结构；本周已有主题时给出补充或替代建议；最终采用与否由负责人决定。” |

### 3.7 `weekly_materials`

| 输入变量 | 类型 | 来源 |
| --- | --- | --- |
| material_basis | JSON（服务端 MaterialBasis 快照） | 确切游戏／区域选择 + 整组目标／指导／支持策略 + 班级年级 + 依据标识（材料规格 §2 已写明字段；1A 不实现快照构建本身） |

输出候选（按材料规格 §3）：必需 key `items`，list 0–100项（可为空；提取与补充均写入同一items列表，不输出额外正文）；每项 `{text(≤300 字符), origin ∈ (extracted, suggested), evidence_refs(list)}`；text须非空且非全空白；`extracted`项evidence_refs至少一项，每个ref须含 `{source_ref, field_path, quote(≤2000 字符)}`，且服务端校验该 ref 在启动快照中真实存在、quote 确为该 field_path 的原文片段，quote须非空且非全空白（空串子串不得作为证据）；`suggested`项 evidence_refs 为空（不伪造引用）。规格允许“建议可说明理由”，但 items 现有字段集不含理由字段；1A 不新增 `reason` 字段，理由的表达方式（随附文本或列表项附注）留到材料片实施时登记，不在本片引入候选结构变更。候选合成材料文本总长 ≤20000；项目顺序保留；相同材料允许预览编辑合并，不自动跨来源丢证据；超限整体拒绝完整候选，不截断采用。

指导字段与默认正文（首版实现文案）：

| 字段 | 默认正文 |
| --- | --- |
| extraction | “优先从输入给的所选游戏／区域整组文本中逐项提取明确提到的具体用品名称；每项须给出真实依据位置与原文片段；原文未明确提到的用品不提取，不把‘材料／工具’等泛称当作具体用品。” |
| supplement | “仅在明确用品不足时，根据游戏目标、指导、支持策略与班级年级提出补充材料建议；建议标为suggested，evidence_refs为空，不附加schema外理由字段或正文；不把支持策略全文当作材料。” |

## 4. 服务输入／输出与冲突规则（纯服务层）

### 4.1 `ai_config_service`

| 接口 | 输入 | 输出／规则 |
| --- | --- | --- |
| `get_config(operator, target_account_id)` | — | 当前 version、protocol、base_url、model、`has_secret`、`ready`、`ready_reason`（MISSING_URL／MISSING_MODEL／MISSING_SECRET／DECRYPT_UNAVAILABLE）；**脱敏返回对象**（§5.4），不含任何明文 |
| `save_config(operator, target, expected_version, protocol, base_url, model, secret?)` | operator＝target＝本人（§7.1） | 未传 secret→**保留同一明文密钥语义**：新版本行对该密钥以新随机 nonce + 绑定**新 config_version 的 AAD** 重新加密写入（§5.1）；`null`／空串→`VALIDATION_ERROR`；非空新值→轮换（同样新 nonce＋新 AAD，旧版本行字节不变）；仅传 URL／model 改动同样走“保留重加密”路径。已有无密钥版本且未传secret时保持NULL／key_id=NULL，保存非密钥元信息且ready=false，无需解密。head缺失如secret未传→`VALIDATION_ERROR`（首个有效配置必须 URL＋model＋secret）。expected_version：head 缺失→须为 0 才接受首建；head 存在严格相等，不等→`VersionConflict`（409 类） |
| `clear_secret(operator, target, expected_version)` | — | 产生新“未配置”版本：URL／model 保留、secret 置 NULL；**不需要解密旧密文**（加密材料缺失时仍可执行清除）；expected_version 规则同上；head 缺失且 expected=0 时无密钥可清，幂等返回 |
| `resolve_effective_config(target_account_id)` | — | head 缺失→not_ready `NOT_CONFIGURED`；否则按 head 版本行判 ready／reason，供 API 与 worker 共用函数（与提示词模块一样区分最新解析与钉住读取） |
| `read_pinned_config(target_account_id, config_version)` | — | 精确版本读取（含解密→**内部对象**，§5.4）；不改 head、不推理最新、**不做适配／就绪过滤**（调用方自判）；AAD 按该行自己的版本／账号校验。集成测试验证两点语义（§9.2“执行器读取语义”行）：给定旧版本读取仍可解密且该行密文字节保持不变（含随后轮换场景），以及 head 已推进时读取指定旧版本不换代；不冒充真实 worker 领取验收 |

写路径：版本行 + head 指针 + `operation_records`(target_type='account') + 行内 `operation_record_id` 同事务提交，失败全部回滚；版本变化不登记 AI 任务、不写日／周计划、不同步修改历史确认或导出内容（**同事务回滚规则，§7.3**）。

### 4.2 `prompt_service`

| 接口 | 输入 | 输出／冲突规则 |
| --- | --- | --- |
| `list_tasks(operator, target_account_id)` | — | 7 类；每类含 task_type、是否有个人版本、`adaptation_state`、是否存在待处理默认修订（按§7.2已处理修订规则提示更新） |
| `read_task(operator, target_account_id, task_type)` | — | 无个人版本→`"not_initialized"` + 当前 contract + 当前 default 全文字段映射（不写库、不静默初始化）；有→current personal_revision + guidance_map + accepted_default_revision + 状态 |
| `initialize_task(operator, target_account_id, task_type)` | — | **显式调用**（1B 由页面触发；读接口、worker 均不触发，不得因 worker 读取而静默初始化全部任务）；同一事务内创建第 1 版 personal_prompt_versions 行 + head 指针，**不允许无版本的 head，也不允许无指针引用的悬空首版**（事务原子，分工见 §2.8）；记录 accepted_default_revision（＝初始化时被接受为其字面快照来源的 default_revision）+ `personal_init` 事件 |
| `save_guidance(operator, target_account_id, task_type, fields, expected_personal_revision)` | fields⊂guidance_fields；单字段 ≤8000 | 未初始化先显式initialize，不允许expected=0的save暗中初始化；成功＝新personal_revision（map＝旧 map 中选定字段覆盖），head 指针推进 + `personal_edit` 事件同事务 |
| `reject_default(operator, target_account_id, task_type, target_default_revision, expected_personal_revision)` | target_default_revision必须存在且与当前有效contract相同 | 不改个人文字、不产生新个人版本；仅更新 `last_rejected_default_revision` + `reject_default` 事件（同事务）；重复拒绝同一修订→**仍先完整校验** operator／target／expected／目标修订存在性（§7.4），同一有效状态下才幂等返回且不追加事件（PF-3）；此后可主动 accept；**adaptation_required 态下拒绝操作同样返回 `PromptAdaptationRequired`，不得绕过适配**（§6.2） |
| `accept_default(operator, target_account_id, task_type, target_default_revision, accepted_fields, expected_personal_revision)` | accepted_fields为非空、无重复字段名列表，且⊂guidance_fields；可接受与个人based contract及最新contract均相同的既有默认修订；跨contract→DefaultContractMismatch（409类），不得自动映射 | 只替换选定字段为新默认快照，未选字段保持不变；产生新 personal_revision + `accept_default` 事件；`accepted_default_revision` 语义见 §7.5；**adaptation_required 时 accept 同样拒绝运行**，必须先 adapt |
| `update_default(operator(admin), task_type, fields, expected_default_revision)` | operator.role=admin | 追加新 default_revision（不原地覆盖）+ `default_update` 事件，school 目标审计；**不修改 schema／字段集／输出结构**（contract 推进只走 registry／迁移，§6.1）；并发靠 `UNIQUE(task_type, default_revision)` 竞争 + 锁序（§7.3） |
| `adapt(operator, target_account_id, task_type, target_contract_version, full_guidance_map, expected_personal_revision)` | map 必须对目标 contract 完整；提交时须核对目标仍为当时最新contract，并读取该contract匹配的最新默认（§7.4） | 成功→新 personal_revision（based＝目标 contract）+ head `adaptation_state='current'`、`required_contract_version=NULL`；`adapt` 事件；新预填字段基于的默认修订记入该版本的 `accepted_default_revision`（§6.2） |
| `resolve_prompt(target_account_id, task_type, pinned_revision=None)` | — | 供 API／worker 共用：`(personal_revision, guidance_map, based_contract_version, adaptation_state, ready, ready_reason)`；**当前就绪判定** = head 派生状态（§7.2）；**钉住读取** = 精确修订 + 其 based_contract_version，不做适配／就绪过滤；未适配时 ready=false `ADAPTATION_REQUIRED` 只阻该 task_type 的 AI，其他任务与手工保存／确认／导出不受阻 |
| 校验 | — | 未知 task_type→`UnknownTaskType`；未知字段／改结构／改字段名→`FieldViolation`；单字段 >8000→`FieldViolation`（均 422 类，1B 映射） |

## 5. 加密材料加载与手工链路降级

### 5.1 加密格式与密钥保留

使用cryptography的AESGCM（AES-256-GCM）；每次os.urandom生成12字节nonce；AAD固定为UTF-8编码的account_id + ":" + config_version十进制字符串。存储标准Base64(nonce || AESGCM.encrypt返回的ciphertext含tag)，解析严格校验Base64和最小长度，不自行拼拆加密算法。密钥与AAD不落日志。

- PATCH 不传 secret 的“保留”指**保留同一明文密钥**（业务等值），但落为新版本行时**必须以新随机 12B nonce + 绑定新 config_version 的 AAD 重新加密写入**；旧版本行的密文字节保持不变（旧密文只绑其原 AAD，不复用、不搬移，避免错绑）。仅传 URL／model 变更也走同一“保留重加密”路径。
- 旧密文**无法解密**时的失败与完整回滚：保留路径需先成功解密当前版本密文才允许落新版本；解密失败（`DecryptUnavailable`，含密钥材料缺失／格式错误／密文被改／AAD 账号或版本不符）→ **整个事务回滚**（新版本行、head 指针推进、审计行全不落库），返回该 typed 错误（1B 映射），**不得**落一个“secret 缺失”的新版本行来替代保留失败；`clear_secret` 不依赖解密、不受此限（加密材料缺失时仍可清除）。
- `read_pinned_config` 对某旧版本读取仍按**该行自己的** AAD 校验（绑定关系），不因新版本存在而失败；集成断言“旧版本行字节在轮换后仍保持不变”基于此。

### 5.2 主密钥编码、长度、key_id 匹配及加载时机

- 编码：Base64 标准字母表（`=padding` 允许）；解码后必须恰 32 字节（AES-256）；`ai_master_key_id`：`[A-Za-z0-9._-]{1,64}`。
- 加载时机：`ai_crypto.load_material()` **惰性**执行——每次加密／解密调用现读现解码（无全局缓存），配置字段由 `app/config.py` preset（可选 SecretStr，默认空）；**进程启动和 import 不做任何非默认格式校验**，格式错误→`KeyMaterialInvalid`（与缺失同效，AI 相关能力 ready=false `DECRYPT_UNAVAILABLE`），**不得导致应用启动失败或既有手工链路（手工日／周计划保存、确认、导出）不可用**——ai_crypto 仅服务模块，手工服务 `import` 面为空（集成/单元覆盖）。
- key_id 与解密目标行的 key_id **必须完全匹配**才允许解密；不匹配→`DecryptUnavailable`（不推断新主密钥语义；真实轮换属后续切片）。
- 测试注入：单元用例用测试生成的密钥（运行中生成，不读 `.env`）；集成测试不依赖 `.env`，密钥仅通过显式测试参数传入。

### 5.3 加密失败与事务边界

- 加密在事务内执行但**不改变回滚语义**：任何后续 INSERT／UPDATE／审计失败或回滚都会连同该新版本行一起回滚、head 保持原值；不存在“新版本已写入但后续失败仍部分保留”的状态。
- 加密／解密在 1A 的一切路径都必须发生在数据库事务内安全性可回滚的位置（版本行写入前完成加密；解密在提交前完成校验）；typed 错误（`KeyMaterialMissing`／`KeyMaterialInvalid`／`DecryptUnavailable`）不并入 `VersionConflict`，由 1B 定稿各自 HTTP 映射。

### 5.4 脱敏返回对象 vs 内部获授权解密结果

| 对象 | 用途 | 可含内容 | 泄漏防线 |
| --- | --- | --- | --- |
| `AiConfigView` | 设置页 / GET / 日志 | protocol、base_url、model、version、`has_secret`（bool）、ready／ready_reason | 到处可用可序列化 |
| `DecryptedConfig` | **仅**供授权执行者（未来 worker 经 `read_pinned_config`／授权执行路径）使用 | 上述元信息 + 明文 secret（进程内存短暂存在） | 非序列化对象；`__repr__` 脱敏（不出现密文字节或明文）；写日志／错误／响应一律不含；调用后即释放引用 |

两者为不同类型（脱敏视图通过单独的建造函数产出），类型系统上不可混淆；无授权执行路径（1A 无 worker）时 `DecryptedConfig` 只在 `read_pinned_config` 返回后立即消费完，不跨请求缓存。

## 6. 协议推进及适配

### 6.1 契约发布权限

- 系统字段协议（contract）只经**经过审阅的 registry／迁移**发布（新 contract_version 行 + 新迁移 + registry 同步）；管理员日常编辑仅修改**默认指导**（`update_default`），不存在也不新增“管理员任意编辑 schema／字段集合”的任何能力；1B 的 admin 端点也只开放 `update_default`。

### 6.2 contract 变化时的适配

- 发布新 contract_version 后，对每 (account, task_type)：
  - **无 head**（未初始化）→ 读取时仍显示“not_initialized”，不静默推进；后续首次初始化基于当时最新contract及该contract匹配的最新默认。
  - **有 head 且 based_contract_version < 最新** → 服务层判定函数 `adaptation_state` 派生为 `'adaptation_required'`，`required_contract_version` = 最新 contract_version；**持久化时机** = 该head下一次成功写路径提交时对齐；失败事务不单独提交缓存（同一事务、同一锁序）；纯读路径不改行，只在返回值中给出该状态（API和未来worker使用同一判定函数，§7.2）。
  - **有 head 且 based_contract_version = 最新** → 'current'。
- 旧个人文字保留：适配流程只要求 map 覆盖**新字段集**（新增字段从对应默认预填）；已有字段的个人文字原样带入；**适配明示“完成适配”必须重新提交全量 map**（不因 checkbox 或局部提交而虚标完成；未保存、关窗、或只按“保留当前”不构成适配）。
- `adapt` 提交须**再次核对**：expected_personal_revision；target_contract_version 在head锁和契约共享锚点锁保护下通过locking read读取，仍为该任务当前最新contract_version；不满足则 `ContractAdvanced`（typed 错误，HTTP 映射由 1B 定稿，错误码不并入 `VersionConflict`）。提交失败整体回滚，个人指导及适配状态不变，提示重新读取后再适配。
- 普通默认接受／拒绝不能绕过必需字段适配：head 处于 `adaptation_required` 时，`accept_default`／`reject_default` 一律返回 `PromptAdaptationRequired`、不执行动作；解除该状态仅能通过显式 `adapt` 成功（缺失新字段按当时默认预填）实现；不存在也不新增任何静默代为改写或代为适配的路径。
- **指定旧版本读取 vs 当前就绪判定**：钉住读取返回该具体版本与其 based contract（不判状态）；当前就绪判定使用 head 派生状态 + 最新 contract 比较。两者使用不同函数，不得混用。

## 7. 服务身份与事务

### 7.1 身份与调用边界

个人设置读写均传受信任operator身份，并断言target_account_id=operator.account_id；不能只传目标ID宣称本人隔离。管理员默认写入还须检查锁定账号role=admin、is_active=true；待分配教师可维护本人设置。

交互写服务接受现有AuthSnapshot，在锁账号后沿既有顺序调用validate_locked_session，检查auth_version／role／会话，防止API预检查与提交之间权限撤销。设置读入口验证受信任当前身份；1A不暴露任意账号解密API。未来worker在业务授权事务内锁定真实计费／提示词账号后调用不依赖会话的内部解析函数，不能伪造登录快照；1A只提供内部核心，不实现worker授权。

### 7.2 适配状态和处理状态

当前有效适配状态由个人版本based_contract_version与当前contract比较派生；head中adaptation_state是缓存，不单独授权AI。纯读不写库；成功写路径对齐缓存。失败事务全部回滚，不能为更新缓存提交半个失败请求。derive输入须包含个人版本based_contract_version，不能仅比较head缓存。

last_seen_default_revision表示“已显式处理到的修订”，不因GET或打开页面推进。initialize设为初版默认；accept／reject／adapt设为max(原值或0,本次目标修订)；personal_edit不修改。更新提示为latest_default_revision > (last_seen或0)。拒绝后允许主动接受同修订；接受成功若last_rejected等于目标则清除该标记。处理旧修订不隐藏更新修订。适配提示优先；普通接受／拒绝不能解除适配。

### 7.3 固定契约行锁与事务

不新增表或组件：每个task的contract_version=1种子行作为永久锁锚点，不修改其数据，也不删除。固定行通过(task_type,contract_version)精确定位。

- 配置写：account FOR UPDATE → 交互session校验 → config head FOR UPDATE；缺head也由account行串行化首建。
- 个人指导写：account → session → personal head → 同任务contract v1锚点FOR SHARE → 最新contract／所需默认locking read（FOR SHARE，populate_existing）。按task_type固定registry顺序锁定；1A每次只处理一个任务。
- 管理员默认发布：account → session → 同任务锚点FOR UPDATE → 最新contract/default locking read → 比较expected_default_revision → 追加新默认及审计。不得从锚点反向取得个人账号或head。
- 系统contract发布：经过审阅的迁移在所有DDL完成后，用独立DML事务先拿锚点FOR UPDATE，再locking read当前contract/default，追加新contract及匹配默认，最后提交。MySQL DDL隐式提交不能混在该DML锁保护区。1A只种入v1；未来发布不得绕过协议。测试夹具按相同协议发布合成v2/v3，不增加产品schema编辑服务。
- 锚点共享锁持有到个人写事务提交；发布者排他锁与其互斥。若发布先提交，adapt的locking read看到新契约并拒绝旧目标；若adapt先提交，发布随后推进，下一次读取正确显示待适配。前者不得因普通快照读取误用旧契约。只验证两个合法提交顺序，不声称能拒绝尚未发生的未来发布。
- 新增提示词锁在未来worker业务／sync锁之后、task锁之前；本片不取得班级／计划锁，不在锁内做网络。

写事务：锁定／校验 → INSERT审计并flush取得引用 → INSERT新版本并flush → 更新或建立head → INSERT提示词事件 → commit；reject无新个人版本，写处理状态及事件；幂等重试无写入。失败rollback全部对象。不能先插入NOT NULL operation_record_id尚无对应审计的配置行。服务写入口负责提交，与现有服务模式一致；内部解析函数不提交调用方事务、不嵌套commit。加密或数据完整性错误不伪装版本冲突；错误须脱敏，不能输出含secret的SQL参数。

### 7.4 并发规则（实施和测试使用同一预期）

| 案例 | 明确结果 |
| --- | --- |
| 同账号首次initialize | account锁串行化；首个创建版本/head/事件，后者锁内读到已初始化并幂等返回，无第二初版；config首建相同expected=0则后者VersionConflict |
| 同expected个人／配置双写 | 先者推进版本，后者锁内比较失败；恰一成功 |
| 不同管理员发布同expected | 共用锚点排他锁串行化；后者locking read看到已推进默认，VersionConflict；已知revision唯一键1062仅作冲突退守，其他FK/CHECK/截断错误按真实原因回报 |
| 拒绝先于接受 | reject不推进个人版本；相同expected的accept可随后成功，是允许“拒绝后主动接受”的顺序化结果；最终文字来自所选默认，拒绝目标标记清除，两条真实事件，无版本冲突承诺 |
| 接受先于拒绝 | accept推进个人版本；旧expected的reject冲突且不写事件，不覆盖新处理状态 |
| 同修订重复拒绝 | 先校验身份、expected及目标契约兼容性；已有相同拒绝标记则幂等返回，无新个人版本或重复事件 |
| contract先发布、旧adapt后提交 | locking read当前contract与target不同，ContractAdvanced（409类）；个人版本、head、审计全部回滚；即使Session更早建立普通读取快照也须如此 |
| adapt先提交、contract后发布 | adapt在旧contract仍有效时合法提交；发布随后推进，解析返回adaptation_required，旧钉住读取保持原版本；发布事务不能插入到adapt持锁区间 |
| 历史默认接受 | 只允许与当前有效contract相同的默认修订且选定字段全存在；跨contract拒绝，不静默删补或改变based_contract_version |

### 7.5 默认快照与按字段审计

accepted_default_revision记录最后一次init／accept／adapt所基于的默认修订，不代表每个字段都来自该修订。guidance_map保存完整文字快照；prompt_change_records.changed_fields记录明确选择的字段名，结合版本序列追溯按字段来源。字段正文不写操作日志。普通accept只替换非空selected字段集合，其余字段保持；空集合拒绝，不产生无意义revision。save_guidance／update_default同样拒绝空patch和未知字段。

## 8. 指定旧版本读取与执行引用边界

- `read_pinned_config`／`read_pinned_prompt`（§4）可读取任意已存在版本，不清理、不推断；已钉住执行中任务保留启动版本完成；清除／轮换不把旧请求换为新 secret。
- 1A **不**实现：execution 引用登记（属持久任务片）、secret 清理作业（须在真实调用启动前基于真实 execution 引用完成）、引用状态推断；1A 不删除可能仍被使用的旧 secret、不运行清理作业。

## 9. 验证计划

### 9.1 单元测试（纯单元，无 DB，无服务进程）

| 文件 | 必须覆盖 |
| --- | --- |
| `backend/tests/unit/test_ai1a_url_crypto.py` | 加密随机 nonce（每次调用产生不同密文）、AAD 绑定篡改失败、**保留重加密**（URL/model-only PATCH 的新版本行基于新 nonce＋新 AAD 加密，且旧版本行密文字节保持不变）、轮换／清除三形态、key_id 不匹配拒绝、密钥材料缺失／格式错误（typed 失败，不影响 import／启动；手工模块 import 面为空）、`DecryptedConfig` repr 无明文；URL规范化（保留供应商前缀，不重复追加/v1；base_url不混入/chat/completions端点，最终端点由未来transport追加一次）、query／fragment／userinfo 拒绝、明文 HTTP 拒绝、loopback／private／link-local／保留地址／IPv4-mapped-IPv6 绕过拒绝（**标注：不冒充完整 SSRF 防护通过，DNS／TLS 级属 transport 片**） |
| `backend/tests/unit/test_ai1a_registry_defaults.py` | 7 类全部注册且 task_type 唯一；每类 input_vars／output_schema／guidance_fields 完整；逐字段默认正文齐全（22条），与v3定稿相同且符合JSON字段契约；未知任务／字段、改字段名／改结构、单字段 >8000 拒绝；输出候选 schema 与业务保存 schema 分型；默认正文与迁移种子内容一致性比较（固定快照校验） |
| `backend/tests/unit/test_ai1a_view_masking.py`（可选，纳入 ai_config 单元组） | `AiConfigView`（脱敏对象）不含任何明文 secret / 认证头/ 解密内容；`DecryptedConfig` 反序列化不可达 / repr 脱敏 |

### 9.2 隔离真实 MySQL 8.4 / InnoDB 验证（专用 guard，一次授权一次性环境）

`backend/tests/integration/ai1a_guard.py` 模式（照 I 系列先例）：

- 独立环境变量：`AI1A_TEST_ALLOW_DESTRUCTIVE=yes` + `AI1A_TEST_DATABASE_URL`；库白名单 `kindergarten_test_ai1a`／`kindergarten_test_ai1a_fresh`；端口独占 13387；仅 127.0.0.1／localhost + `mysql+pymysql`；与 I2／I3／I4／I5 的破坏开关互不借用；**guard 在被 import / 任何测试或迁移连接打开前生效**（`os.environ["APP_DISABLE_DOTENV"]="1"` 恒置 + 白名单校验先于 `create_engine`）。
- 资源：一次性 `mysql:8.4.11` 容器（I3 先例），仅 loopback 暴露 13387；测试后容器及数据卷删除；实施报告列容器／端口／库清单与清理证据。**该自动测试数据库不是本机 WSL 产品验收服务器；1C 产品验收仍按现有远程实例口径，部署须单独授权。**

| 验证 | 必须证据 |
| --- | --- |
| 迁移兼容 | 空库 + 含 I1–I4 代表行的库均 `alembic upgrade head`；原计划、确认、来源及审计约束保持；`heads == current == 20261003_ai1a_config_prompts`；唯一 head 及 current 一致；迁移种子JSON解析内容与固定v1/revision 1一致（不比较MySQL JSON键顺序或字节格式）；如提供降级说明其数据删除边界，不对共享库执行 |
| 个人隔离与结构 | 不能读写他人配置／指导；7 类协议全部覆盖、结构不可被个人改写、版本复合 FK 归属一致；**非本人目标操作一律 `Forbidden`** |
| 初次并发建立 | 线程级并发首建head → account锁串行化，唯一约束退守，恰一个可读当前版本，不产生两个 head 行；**不出现无版本 head 或无 head 的悬空版本行**（事务原子） |
| 同版本双更新 | 相同 expected_version 双写→恰一成功一 `VersionConflict`，输入不丢失；**未被 typed 分类的强制 IntegrityError 原样 re-raise**（不统一伪装 409） |
| 适配期 contract 推进 | 按§7.4分别验证发布先提交（旧adapt拒绝）及adapt先提交（发布等待、随后派生待适配）；对应任务阻而其他任务及手工路径可用；**普通 accept／reject 在 adaptation_required 态被拒绝（“不能绕过适配”）为一条独立断言** |
| **保留重加密 / 轮换 / 清除** | URL/model-only PATCH：新版本行换新 nonce／新 AAD，旧版本行密文**字节不变**；篡改旧密文后保留式 PATCH → `DecryptUnavailable`，事务整体回滚（无不完整新版本行或审计），重读仍指旧版本；key_id 不匹配 → 拒绝；`clear_secret` 在主密钥缺失下仍成功（新“未配置”版本），不依赖解密 |
| **NULL约束** | 对 NOT NULL 列非法 NULL 写入（含`required_contract_version` 在 `adaptation_required` 下 NULL、head 无 current_revision 等）被服务层和 DB CHECK 分别验证服务拒绝及直接SQL触发对应NOT NULL／CHECK约束 |
| 身份隔离 / 管理员权限 | 教师试图 update_default → `Forbidden`；operator≠target 的个人目标写入 → `Forbidden`；无效账号（is_active=false）或快照角色／auth_version／交互会话与锁定行不一致路径均被拒 |
| 适配／默认竞争 | 分别验证§7.4的reject先／accept先两种顺序；两管理员同expected恰一成功；contract先发布则旧adapt回滚、adapt先提交则发布等待并随后派生待适配；含预先建立REPEATABLE READ快照的测试 |
| 失败回滚 / 持久 | 注入失败 → 版本行／head／审计／事件全部回滚，重连后一致性持久 |
| 候选schema与默认兼容 | afternoon_outdoor单对象、未知字段/系统ID拒绝；holiday_context固定列表；extracted空证据或空quote拒绝；空适龄候选不解释为无需调整；跨contract默认接受拒绝、只按选择字段替换；未初始化save拒绝 |
| 无主密钥手工回归 | 缺失及格式错误两种材料下，手工日／周计划服务和Word导出路径仍可用；提供实际定向证据，不只检查import |
| 执行器读取语义 | 仅验证 `resolve_effective_config`／`resolve_prompt` “读取最新有效版本”与“指定旧版本保持不变”两点；**不冒充真实 worker 领取／运行验收** |
| 直接回归 | 触及集中模型／账号审计 → 全量后端单元测试复跑基线；I1–I5 集成套件不重跑（未改既有 schema／契约）；无前端改动不重跑前端，有明确风险才扩大 |

实施交付逐项记录通过／失败／skip、实际命令、迁移 head、依赖锁与未执行事项。排队／claimed 运行、网络目标防护、真实供应商、任务恢复、业务采用及 W6 均留给对应后续切片，不以本片测试替代。

## 10. 明确边界（后续落地条目）

| 条目 | 边界 |
| --- | --- |
| reject-default API 入口 | 1A 只交付服务层；1B 拟 `POST /api/settings/prompts/{task_type}/reject-default`，携带 expected 个人版本及目标 default revision，并允许之后主动接受；API 定稿在 1B 前明确 |
| 首次个人指导初始化 | 1A 交付显式 `initialize_task` 服务（含并发初版、所接受默认版本可追溯、事务原子性）；1B／1C 落实页面触发；1A 不得因 worker 读取而静默批量初始化全部任务 |
| DELETE expected 版本 | 1A 交付服务层语义（head 缺失时 expected=0 才接受；head 存在时严格比较；清除产生新“未配置”版本并保留非密钥元信息）；请求输入 schema 与端点定稿在 1B |
| 执行引用与 secret 清理 | 持久任务片登记真实 execution 引用后实现；清理须在真实调用启动前完成；1A 不猜引用状态、不删可能仍被使用的旧 secret、不运行清理作业 |
| `ai_call_records` 调用日志 | 依赖 execution／attempt 的 FK、唯一键、结果同事务关联，属持久任务片；1A 只保留调用元信息接口契约（invoke 输入字段清单）；不建无真实 execution 的成功日志，不提前引入任务表 |
| transport／网络防护 | DNS 解析到实际连接钉住、TLS、重定向拒绝、代理绕过、无隐式重试、响应 1MiB 限额属 transport 交付；1A 离线字符串校验不冒充完整 SSRF 防护通过 |
| `class_game_config` 数据实体 | I2 范围已排除；1A 只在 registry 声明变量名与来源层级，不建表、不发明该配置的产品语义 |
| API／UI／worker／候选／材料业务 | 全部不在 1A；`weekly_materials` 仅落协议表（契约可建），不提前扩入材料正文、采用或确认实现；不把未来能力记为已验 |

## 11. 产品决定状态

无缺产品决定。已确认继承并直接约束 1A 的：P1 管理员本人入口；提示词接受／拒绝／适配规则；追加式版本规则（ADR 0002）；密钥仅写不回显。默认正文由协调者修正并核对，作为首版实现文案，不固化为用户逐条确认的教学规则。OpenCode按定稿编码，不自行设定教学限制。

## 12. 工程决定（v3协调者收敛，不增加产品要求）

| 编号 | 事项 | 状态 / 建议 |
| --- | --- | --- |
| PF-1 | `school` 目标审计行的 `target_version_after` 取值 | **采用NULL**：默认指导发布不修改 school_settings.version，填既有版本号会有“目标已变更”的歧义；实际默认修订由 `prompt_change_records.default_revision_target` 关联记录，`operation_records` 的 school 行保留 operator／target_id／action；该列本就 nullable，且 `ck_operation_record_account_target` 只约束 account 目标行，不涉 school 行——**与现有表结构无冲突**。 |
| PF-2 | `prompt_default_versions.created_by` 种子行 | **采用NULL**（＝系统发布）；FK accounts.id 允许 NULL（nullable=True），日常管理员发布时该列填非空，与既有表语义兼容；唯一键不含该列，无冲突。 |
| PF-3 | 重复拒绝同一修订 | **采用同一有效状态（operator／target／expected／last_rejected 一致）重复拒绝→幂等返回，不追加个人版本也不追加事件行**；仍先完整校验身份和 expected；目标或 expected 不同则走各自 typed 错误。与 `ck_pcr_reject_default` 兼容——幂等路径不写行，该 CHECK 不受影响。 |
| PF-4 | 候选输出文本字段长度上限细节 | **既有“未规定”处保持未规定**（具体每字段见 §3 长度依据列）；仅材料任务使用材料规格已写明限额；输出总负载以 AI Service 规格 1MiB 响应限额为兜底；不新增其他候选字段长度上限，避免提前收紧业务尚未确认的边界。 |

## 13. 实施前准备结论（历史）

当前1A设计可交OpenCode编码，无新增产品决定或Architecture v1变更。业务游戏配置、候选采用、网络调用和材料闭环仍留后续片，不把占位输入记为已实现。协调者规划／设计及只读审阅，OpenCode唯一业务代码写入。

## 14. v3收敛说明

1. 下午户外恢复单对象，精确嵌套字段和空值；节日输入固定列表，补回星期与年级，游戏配置缺失明确null。
2. 拒绝／接受按真实提交顺序验证，不新增处理状态版本；已处理修订只在显式动作推进，GET不推进。
3. 历史默认须契约兼容，空选择拒绝；增加changed_fields字段名审计，追溯按字段接受。
4. 固定contract v1行协调契约发布、默认发布和个人写入；locking read避免旧快照，两个提交顺序结果明确，不增加表或组件。
5. 删除适龄调整不得增删步骤、日游戏名只能来自输入等未确认限制，区分生成建议与真实引用。
6. 提取要求非空证据／quote，默认正文遵守JSON；修复事件CHECK的NULL放行、缓存与有效适配状态关系、无密钥版本更新及审计插入顺序。
7. PF-1–PF-4已收敛，设计和验证矩阵同步，固定种子比较JSON内容；未执行代码、测试、安装或数据库操作。

## 15. 当前状态与历史边界

本片编码及补修提示词已经执行，现由 [1A 最终审阅](ai-slice1a-closeout-review-2026-10-04.md)保留阶段结论与验证限度，不再作为待执行任务。本文中的文件清单、旧 head、预检与 v3 收敛说明均属于实施前的工程基线，不代表当前工作区文件差分或数据库状态。

### 附：URL与纯读取实现边界

URL离线校验沿AI Service规格：base_url是HTTPS供应商前缀，存储时仅规范化host／端口／末尾斜杠，不静默改写中间路径或追加端点；拒绝完整/chat/completions地址并提示填写前缀。拒绝query／fragment／userinfo、非公网IP字面量和显然本机主机名；不进行DNS或真实连接。未完成transport前不得声明完整SSRF防护已通过。纯读取只返回所请求版本的不可变快照；执行启动的当前版本解析须在调用方短事务既定锁序下进行，1A不承诺任意无锁读取与未来发布具有原子性。
