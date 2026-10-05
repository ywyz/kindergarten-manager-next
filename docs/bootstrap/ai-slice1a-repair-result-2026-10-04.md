# AI 1A 补修结果报告（2026-10-04）

状态：**R1–R7 定向补修与补测完成；真实 MySQL（一次性专用容器）验证通过；未 commit／push；未进入 1B／1C；等待协调者复审，复审通过前 1A 不记为收口。**
执行者：OpenCode。开工基线：HEAD `1647fc9`；12 份既有未提交文档（含 2026-10-03 首轮全部交付与审阅文档）与全部代码文件保留未回退、未清理；未读 `.env` 或任何现有私密密钥；未复制旧项目；未新增 Skill／MCP；未启动额外编码代理。直接依赖与 Lock 完全未变（无新包、无解释器下载；仅用既有 uv 按锁检查）。

历史结论保留：本轮**不重写** `docs/bootstrap/ai-slice1a-implementation-result-2026-10-03.md`（其历史记录仍写"26 tests OK"，该描述保留在原文件中）；协调者审阅 `ai-slice1a-review-2026-10-04.md` 已按 R1–R7 确认该首轮自报未达到收口门槛，本报告补足缺口并以新证据覆盖，不代表首轮实现即正确。

## 1. R 逐项：改动、缺陷复现 → 修复证据

### R1 筟入与 typed 错误（阻塞）

改动：`prompt_service.py`（补 `ai_prompt_registry` 模块导入与 `FieldViolation`；`get_task_types` 改为真实模块引用并补 docstring）；`ai_locks.py`（删除引用未导入 PromptDefaultVersion 且未被调用的 `latest_default_row_locked`——按"名不副实的 locked 函数不得残留"原则删除而非改名）。

失败复现（补修前）：审阅中复现的 `NameError: name 'ai_prompt_registry' is not defined`（任务列表）、空 patch 触发 `NameError: FieldViolation`，可稳定复现。
修复证据（新增单元 `tests/unit/test_ai1a_service_inputs.py`，20 用例）：
- `test_task_list_resolves`：`get_task_types()` 返回 7 类，无 NameError；
- `test_list_tasks_real_entry_covers_all`：真实入口的 TaskStatus 构造；
- `test_empty_patch_rejected_before_db`／`test_empty_accepted_fields_and_bad_versions_rejected`：空／非 dict patch、空 accepted_fields、`0`／`True` 作目标修订号在进入数据库前即 typed `FieldViolation`；
- `test_unknown_task_rejected`：`UnknownTaskType`（服务层，不只是 registry）；
- `test_config_secret_null_empty_and_protocol`：save_config 对显式 null／"" secret、未支持协议、明文 http URL 均为 typed 校验错误。

### R2 字段适配按相应 contract（阻塞）

改动：`prompt_service.py` 新增 `_validate_map_for_fields`／`_validate_patch_for_fields`（依据"已发布 contract 行 guidance_fields"校验，不再用 v1 registry 字段集）；initialize（最新 contract）、accept（兼容性核对后按该 contract 校验选定字段与合成后全量 map）、adapt（锁内 target==latest 后按目标 contract 校验全量 map）、personal_edit（按个人版本 based contract 校验 patch 与合成 map，不静默改结构或补新字段）、update_default（按最新 contract 校验 patch）。任务白名单与字段集校验分离（`require_task_type` vs contract 行）；shape／长度检查提前但字段集必须在数据库访问后按 contract 判定。reject 幂等判定移到目标修订存在与契约兼容核对之后（顺序勘误）。8000 字符、严格字符串、未知字段拒绝保持。

失败复现（补修前）：使用真正在 v1 字段集之外新增字段（`assist_notes_v2`）的合成 v2 全量映射调 `adapt`，在进入数据库前即 `FieldViolation`（审阅复现路径）。
修复证据（新增集成 `E2ContractFieldsetScenarios` 5 用例＋改造夹具）：
- 夹具 `publish_variant_contract`：DML＋锚点排他锁，v2 的 `guidance_fields`＝v1 字段集 + **真实新增字段 `assist_notes_v2`**（v1 不存在），默认修订含新字段预填全文（revision 全局追加，不与 v1 revision 1 冲突）；`publish_contract_v3` 再真实新增 `assist_notes_v3`；
- `test_a_initialize_after_publish_uses_v2_fields`：初始化 based=2、map 含 `assist_notes_v2`、`accepted_default_revision` ＝ v2 匹配默认修订；
- `test_b_adapt_after_publish_with_v2_map`：全量 v2 map（含新字段）适配成功；
- `test_c_personal_edit_validates_against_based_contract`：v1-based 版本上以 v2 新字段 patch 被拒；v1 字段 patch 成功且 based 保持 1、map 不含新字段；
- `test_d_admin_default_update_uses_latest_contract`：管理员 v2 新字段默认发布成功（revision=variant+1、contract=2）；
- `test_e_publish_v3_old_variant_adapt_rejected`：v3 发布后旧目标（v2）adapt → `ContractAdvanced`，无新版本行／无 adapt 事件／审计为 0，重读后 v3 适配成功。

### R3 就绪必须认证当前密文（阻塞）

改动：`ai_config_service._evaluate_ready` 有 secret 时以行自身的 account/version/key_id 调用 `ai_crypto.decrypt_secret` 完成认证解密；任何失败（材料缺失／格式错误／key_id 不同／主密钥错误／密文或 AAD 篡改）→ ready=false `DECRYPT_UNAVAILABLE`；成功即丢弃明文（`del plaintext`），不缓存、不改 head；无 secret 仍 `MISSING_SECRET`。

失败复现（补修前）：篡改密文并把行 `key_id` 改为他值后，`_evaluate_ready` 仍返回 `(True, None)`（审阅用合成行复现）。
修复证据（新增集成 `J1ReadinessCertifiesCiphertext` 5 用例）：正常配置 ready=true 且视图无明文；篡改密文后 ready=False／`DECRYPT_UNAVAILABLE` 且 head 不变；换主密钥→False，恢复→True；行 key_id 不匹配→False；缺材料→False 且清除路径仍成功（`MISSING_SECRET` 新版本）。单元（`test_ai1a_url_crypto` 原既有组）继续覆盖合成行 isolate 语义；真实行证据不再只验证 `load_material` 格式。

### R4 内部对象防通用编码泄漏（阻塞）

改动：`DecryptedConfig` 改为非 dataclass、`__slots__`（无 `__dict__`、无迭代／键视图出口）、secret 以 `SecretStr` 封装、仅 `reveal_secret()` 显式取值；`__setattr__`／`__delattr__`／`__reduce__`／`__bytes__`/`__iter__`/`keys`/`__getitem__` 拒绝；repr 脱敏。

失败复现（补修前）：`dataclasses.asdict` 与 `jsonable_encoder` 对旧 dataclass 产生含明文 secret 的输出（审阅复现）。
修复证据（单元 `test_ai1a_service_inputs.R4SerializationTest` 8 用例）：`vars()`／`list()`／`dict()`／`obj["secret"]`／`keys()`／`asdict()`／`jsonable_encoder`／pickle／copy 全部拒绝（或输出经确证不含明文）；`reveal_secret()` 唯一明文出口且对象不可变；`AiConfigView` 正常 asdict／jsonable_encoder 且键集无 `secret`。所有测试只用合成材料（`SYNTHETIC-S3CRET`），不打印 secret。

### R5 导出 schema 与运行时一致（阻塞；迁移种子修正）

改动：`ai_prompt_registry.py`：
- 必填字段去默认：拆分六字段、周游戏五槽（四槽显式 null 合法→`Optional[T]` 无默认必需）、材料 items 的 text/origin/evidence_refs 全必需（suggested 显式 `[]`）；
- 枚举改 `Literal`（group_kind／context_kind／target_slot／origin→schema enum）；可省略但不可显式 null 的日活动部分以"具体类型＋默认 None"导出（schema 无 null 联合，运行时拒绝显式 null）；递归 extra=forbid 保持；
- 清理未用 helper（`_one_of`／`_require_valid_iso_date`／拆分键 presence 重复校验），无共享可变默认。
迁移 `20261003_ai1a_config_prompts.py`：仅重写 `SEED_ROWS` 固定字面量（仍为 JSON 字符串字面量＋插入前 `json.loads`，不 import 运行时 registry；revision／七表不变）。未触碰 I1–I4 迁移；本片只在一次性测试库执行过、无共享持久环境，故就地修正如审阅决议（未连接远程库查证）。

失败复现（补修前）：旧 `model_json_schema` 中拆分六字段／周五槽 required 缺失、枚举无 enum、可省略字段 schema 带 null。
修复证据（单元 `test_ai1a_service_inputs.R5SchemaExportTest` 7 用例）：required 集、enum 集、null 边界、extra 拒绝、默认无共享状态全部按导出 schema 断言；迁移种子内含 enum／required（`grep`＋断言）；`test_ai1a_registry_defaults` 的"种子↔registry JSON 内容比较"继续通过（键序无关）。

### R6 当前指针与关联版本读取（阻塞；静态确认＋真库补验）

改动：
- `ai_config_service._read_version_row(..., current=False/True)`：写路径（保留／清除读取头所指向的行）改 `current=True`（FOR SHARE＋populate_existing）；展示读保持普通读；
- `prompt_service._read_current_version(..., current=True)`：initialize 幂等分支、save_guidance、accept、reject、adapt 的 head 指向版本读取全部 current 锁定读；展示路径保持普通读；
- `_latest_default_row` 增加 lock 模式（None／share／update）：管理员发布使用排他 current 读（不再可能因旧快照算出重复修订），个人写内匹配默认用共享 current 读；
- `ai_locks` 增加 `contract_row_locked`（save_guidance 按基于的契约读取时 FOR SHARE＋populate_existing）；锁序不变（account→session→head→契约 v1锚点），内部解析不提交调用方事务。

失败复现（补修前）：静态路径（审阅§R6）；本轮在真库补验。
修复证据（新增集成 `K1StaleSnapshotWritePaths` 4 用例，每条先建 REPEATABLE READ 旧快照再由另一连接推进）：
- 配置保留更新：正确新 expected 成功（v3），旧 expected `VersionConflict`（无 NoResultFound／重复 revision IntegrityError），版本／head／审计真实断言；
- 配置清除：旧快照 expected=0 冲突、正确 expected=1 成功 v2；
- 个人编辑→另一连接推进后旧 expected 冲突、正确 expected=2 接受成功（个人版本 3，未经旧窗口文字覆盖）；
- 管理员默认发布在默认前移后旧 expected 冲突、正确 expected 成功新 revision。

### R7 迁移与约束证据补齐（必补验证）

- `A1MigrationCompatibility.test_b`：升级前通过既有服务创建日计划（内容＋审计）＋周计划（草稿含主题 patch）＋确认快照（sync 状态、确认内容、facts），升级前后按 `dump_world_rows` 比较 16 张旧表**整行**（JSON 内容键序无关标准化：daily_plans／daily_plan_contents／weekly_plans／weekly_plan_contents／weekly_plan_confirmed_contents／weekly_plan_sync_states／operation_records／accounts／sessions／classes／teacher_assignments／terms／calendar_revisions／calendar_days／school_settings／first_admin_control）。空库升级重新验证（test_a）。
- CHECK 负例重做：前置条件先满足（真实账号＋审计行＋可引用的个人版本），单独违反目标约束并断言约束名：`ck_pph_adapt_ref`（adaptation_required 下 required NULL）、`ck_ai_config_versions_secret_key`、NOT NULL（current_personal_revision）分别有专属用例；`nacc2 不存在`式伪造不再出现。
- 发布/适配竞争（R2 夹具真实新增字段）：E1 的发布先（旧 adapt 回滚完整、事件与审计为 0、重读后 v2 适配含新字段与匹配默认修订）与适配先（发布等共享锚点、随后 `ADAPTATION_REQUIRED`、钉住旧版本 ready）两顺序均真库验证；拒绝/接受两顺序语义保持（F1 5 用例不变通过）。
- 新增测试先证明补修前失败：R2 场景在补修前对真实新字段夹具失败（`FieldViolation` 于数据库前）；R3 场景在补修前返回 ready=true 转 false 修复后；R6 旧行为若有缺陷静止复现路径在补修后直接跑过旧快照场景（本轮未复现运行时中断，报告按"补测覆盖"记录）。

## 2. 命令与结果

| 命令 | 结果 |
| --- | --- |
| `APP_DISABLE_DOTENV=1 .venv/bin/python -m unittest discover -s tests/unit -t .` | **598 tests OK**（新增 20 个 1A 单元；旧 578 通过不作为 R 修复证据，仅作为回归） |
| `AI1A_TEST_ALLOW_DESTRUCTIVE=yes AI1A_TEST_DATABASE_URL=… unittest tests.integration.test_ai1a_config_prompts`（专用容器 127.0.0.1:13387，whitelist 两库） | **42 tests OK**（R1–R7 覆盖全部含于其中；无 mock 数据库） |
| `uv lock --check` | 通过（lock 未改动） |
| `git diff --check` | 通过 |
| 迁移 heads | `ensure_schema` 断言 `heads == current == 20261003_ai1a_config_prompts`（两库升级路径均通过） |

资源：容器 `ai1a-mysql-13387`（本次新建，仅 loopback 127.0.0.1:13387）＋专用匿名卷，测试后 `docker rm -f -v` 删除；预存容器（`kg-next-i5-slice4-mysql-20261001`）与其他 volume 未触碰；白名单库随容器销毁。无密钥、凭证、DSN 写入本报告或代码。

## 3. 局部一致性处理记录

- reject 幂等顺序移至目标默认存在＋契约兼容核对之后（身份／expected 仍最先），无重复事件（`F1.test_duplicate_reject_idempotent` 继续通过）。
- 畸形 URL：`urlsplit` 异常路径（未加方括号 IPv6、端口不合法）统一映射 `BaseUrlInvalid`；空 query／fragment 分隔符（`?`／`#` 结尾）仍拒绝；未新增 DNS／连接／transport 实现。
- guard／Alembic 失败证据只显示脱敏目标（driver/port/db 名）与错误类别；不拼完整 DSN、不继承连接凭证。
- 测试不再导入带 I5 guard 的 support 模块；日内容为 AI1A 纯夹具（AI 专用 `full_day_content`）。
- 动态来源 helper 维持原有定位（结构层能力，非业务第二层校验收口），无游戏分类／去重／材料采business 扩展。

## 4. 未执行项

- 产品验收、供应商调用、W6 真机、远程实例仍全部未触；API／UI／worker／transport／候选落库／材料闭环／secret 清理未实现（属 1B／后续片）；无 schema 编辑入口新增。
- R6 静态异议项（`_evaluate_ready`／`latest_default_row` 等）在补修前未能由协调者在 MySQL 复现过运行时错误；本轮通过先行旧快照用例补上运行时覆盖，其"补修前必然失败"只能由静态路径与审阅结论佐证，不虚称"新测试补修前失败已实测"。
- guard 负例（I5 库名／错端口／无开关拒绝）延续首轮结构，本轮未重复执行。

## 5. 停止声明

提交物仅本轮 1A 范围：prompt／config 服务、guard、测试与**本轮新增**迁移种子；未改既有业务、未扩散范围。交付后停止，等待协调者复审；1B（API／权限定稿与实现）未获授权，不自动启动。
