# AI 1A 实施结果报告（2026-10-03）

状态：**实现与自动测试完成；未做产品验收；未 commit／push；未进入 1B／1C。**
实施依据：`docs/bootstrap/ai-slice1a-implementation-checklist-2026-10-03.md`（v3）＋ 用户编码提示词（2026-10-03）。执行者：OpenCode（业务代码唯一写入者）。开工基线：HEAD `1647fc9`，7 份既有未提交文档 + 3 份未跟踪文档全部保留未动；未读 `.env`、未复制旧项目、未新增 Skill／MCP、未启动额外编码代理。

## 1. 实际文件改动（对照清单 §1）

| 文件 | 状态 |
| --- | --- |
| `backend/app/models.py` | 追加 7 个模型类（`AiConfigVersion`／`AiConfigHead`／`PromptContractVersion`／`PromptDefaultVersion`／`PersonalPromptVersion`／`PersonalPromptHead`／`PromptChangeRecord`），既有 17 表零改动 |
| `backend/migrations/versions/20261003_ai1a_config_prompts.py` | 新增；7 表 DDL（复合 FK 处理：head 指针在其引用键表之后 `create_foreign_key`；种子 bulk_insert 于全部 DDL 完成后写入），revision `20261003_ai1a_config_prompts`，down_revision `20260924_i4_weekly_plans`；downgrade 抛 `RuntimeError` 阻断 |
| `backend/app/services/ai_prompt_registry.py` | 新增；7 类任务 registry（strict Pydantic、递归 extra=forbid、输入变量声明含 required/nullable/origin、候选输出 schema、guidance 字段＋22 条默认正文、动态来源校验函数） |
| `backend/app/services/ai_config_url.py` | 新增；HTTPS base_url 规范化与离线校验（query/fragment/userinfo/明文 HTTP/非公网 IP 字面量/本机主机名/完整端点路径拒绝；IPv4-mapped-IPv6 一律拒绝） |
| `backend/app/services/ai_crypto.py` | 新增；AES-256-GCM、12B 随机 nonce、AAD=`account_id:config_version`、惰性主密钥加载（无全局缓存、import／启动期零校验）、typed 错误（`KeyMaterialMissing`／`KeyMaterialInvalid`／`DecryptUnavailable`） |
| `backend/app/services/ai_config_service.py` | 新增；配置版本追加（expected_version 语义、head 缺失视为 0）、secret 保留重加密／轮换／清除、ready 判定与理由、`AiConfigView`（脱敏）与 `DecryptedConfig`（内部对象、repr 脱敏、pickle/copy 拒绝）分型 |
| `backend/app/services/prompt_service.py` | 新增；初始化／编辑／接受／拒绝／适配／管理员默认修订追加、`resolve_prompt`（最新解析＋钉住读取分离）、`read_task`／`list_tasks` 纯读、事件与审计同事务 |
| `backend/app/services/ai_locks.py` | **新增内部帮助文件（超出 §1 清单，需报告）**：config 与 prompt 两服务重复所需的身份／锚点锁 helper（`lock_self`＝沿 `auth_service._lock_account`＋`validate_locked_session` 未改动的既有规则；`lock_config_head`／`lock_personal_head`／`lock_contract_anchor` FOR SHARE／FOR UPDATE；`latest_contract_locked` locking read＋populate_existing）。原因为清单 §1 允许"必要纯内部锁帮助文件"；未重构 auth_service |
| `backend/app/config.py` | 新增可选 `ai_master_key`／`ai_master_key_id`（SecretStr，默认空＝降级态） |
| `backend/pyproject.toml` | 直接声明 `cryptography==50.0.1` |
| `backend/uv.lock` | 仅项目包元数据区新增两条（dependencies 与 requires-dist 各一行 `cryptography ==50.0.1`）；`cryptography` 节点保持 50.0.1 不动，其余 26 包不变 |
| `backend/tests/unit/test_ai1a_url_crypto.py` | 新增（含 §9.1 可选 view-masking 组） |
| `backend/tests/unit/test_ai1a_registry_defaults.py` | 新增 |
| `backend/tests/integration/ai1a_guard.py` | 新增独立 guard（AI1A_TEST_ALLOW_DESTRUCTIVE ＋ AI1A_TEST_DATABASE_URL，端口 13387） |
| `backend/tests/integration/test_ai1a_config_prompts.py` | 新增（26 用例） |

零修改：`routers/`／`schemas.py`／`frontend/`／既有迁移／`word_export_*`／其他 docs。未 commit／push。

## 2. 表与迁移

7 表全部 InnoDB／utf8mb4／utf8mb4_unicode_ci，主键 id 为 String(32) binary collation；版本列 INT（非空 ≥1 CHECK）；审计事件 6 条形态 CHECK＋修订列 NULL-or-≥1（清单 v3 §2.7 修复版）；`ck_pph_adapt_ref` 用显式 `IS NOT NULL` 堵 NULL 放行；复合 FK：

- `fk_ai_config_heads_current`：(account_id, config_version) → `ai_config_versions(account_id, version)`；
- `fk_prompt_default_versions_contract`、`fk_ppv_contract`、`fk_ppv_default`、`fk_pph_current`、`fk_pph_required_contract` 同 §2 命名。

种子：contract_version=1 ×7 与 default_revision=1 ×7 作为**逐字段字面量**写入迁移文件（JSON 以固定字符串字面量存储、插入前 `json.loads` 后由 SQLAlchemy 绑定为 JSON；键序无关比较）；`created_by=NULL`（PF-2）；种子不产生 operation_records。

## 3. 依赖与锁

- `uv lock --check` 通过；`uv sync --offline` 校验 26 包 installed/hash 一致；`.venv` 内 `cryptography` 50.0.1（Python 3.14.4）。未新增 SDK／HTTP 客户端／pytest／jsonschema，未下载解释器，未升级其他依赖。
- Alembic 子进程只注入经 guard 校验的 `DATABASE_URL`（`authorized_migration_env` 过滤并覆写 `DATABASE_URL`，强制 `APP_DISABLE_DOTENV=1`）；迁移受 guard 保护（端口 13387＋库白名单校验先行）。

## 4. 验证命令与结果

| 命令 | 结果 |
| --- | --- |
| `APP_DISABLE_DOTENV=1 .venv/bin/python -m unittest discover -s tests/unit -t .` | **578 tests OK**（含新增 `test_ai1a_url_crypto` 16、`test_ai1a_registry_defaults` 16；全量旧 unit 作为集中 models/config 回归通过） |
| `AI1A_TEST_ALLOW_DESTRUCTIVE=yes AI1A_TEST_DATABASE_URL=… .venv/bin/python -m unittest tests.integration.test_ai1a_config_prompts` | **26 tests OK**（真实 MySQL 8.4.11 / InnoDB，专门容器 127.0.0.1:13387） |
| guard 负例（一次性命令，非测试文件）：库 `kindergarten_test_i5` → guard 在任何连接前拒绝（"AI 1A integration tests refuse non-AI1A database"）；端口 13386 → 拒绝；无开关 → `INTEGRATION_ENABLED=False`（用例跳过） | 通过 |
| 迁移：空 `kindergarten_test_ai1a_fresh` 全链 `alembic upgrade head`；`kindergarten_test_ai1a` 升至 `20260924_i4_weekly_plans` → 放 I1–I3 代表行（含服务层真实创建日计划＋内容＋审计）→ `upgrade head` → 代表行逐列不变、计数不变 | 通过；`heads == current == 20261003_ai1a_config_prompts` |
| `git diff --check` | 通过 |

真实 MySQL 覆盖场景（对应 §9.2 矩阵，全部真实连接非 mock）：本人隔离（非本人目标操作一律 `Forbidden`）、并发首初始化恰好一次（account 锁串行化，无第二版本行／无悬空行）、同 expected 配置双写恰一成功一 `VersionConflict`（IntegrityError 原样 re-raise 形态保留）、适配→发布两顺序（发布先提交→旧目标 adapt `ContractAdvanced` 全回滚、adapt 先提交→发布等待共享锚点后推进、`resolve_prompt` 返回 `ADAPTATION_REQUIRED`、钉住读取保持旧版本 ready）、拒绝先／接受先两顺序（reject 不推进版本；accept 随后可成功；accept 先提交旧 expected reject 冲突且不写事件）、重复拒绝幂等（完整校验先行、无重复事件）、双管理员同 expected 恰一成功（锚点排他锁串行化）、保留重加密／轮换／清除（URL/model-only PATCH → 新 nonce＋新版本 AAD、旧行字节不变；篡改旧密文 → `DecryptUnavailable` 且新版本行／head／审计全回滚、重读仍指旧版本；key_id 不匹配拒绝；无主密钥下 clear 成功）、NULL／CHECK 直接 SQL 触发（head 无版本 FK 拒绝、cipher 有值 key_id NULL CHECK 拒绝、adaptation_required 下 required NULL CHECK 拒绝）、注入 `_add_event` 失败 → 版本行／head／审计／事件全部回滚且重连持久、无主密钥与错格式主密钥下手工日计划保存／周计划创建确认／日周 Word 导出（docx zip 真实字节数据）可用、执行器读取语义（最新解析 vs 钉住旧版本保持）。

## 5. 资源身份与清理（§9.2 全程仅本片资源）

- 镜像：`mysql:8.4.11`（授权内新拉取）。
- 容器：`ai1a-mysql-13387`（仅 loopback 127.0.0.1:13387 → 3306），专用匿名卷 `3146af333bf0b97da55aa60d7669396268bb376509a097b48af5ef479610daaa`。
- 白名单库：`kindergarten_test_ai1a`／`kindergarten_test_ai1a_fresh`（本次创建）。
- 清理：`docker rm -f -v ai1a-mysql-13387` → 容器与匿名卷删除；端口 13387free； 未删除预存容器（`kg-next-i5-slice4-mysql-20261001` 保留）、卷、镜像或其他库。测试凭证不写入仓库与文档，仅存于测试会话环境并已丢弃。

## 6. 实现要点核对（关键项）

- 锁序：account → 交互 session（既有 `validate_locked_session`）→ 自身 head → contract v1 锚点；个人写 FOR SHARE、默认／协议发布 FOR UPDATE；锚点共享锁持有至个人写事务提交；锁内最新契约／默认用 locking read＋populate_existing，不依赖 REPEATABLE READ 普通快照（E1 专门用"同一连接先建普通快照再发布"把快照陷阱暴露）。
- secret 保留＝解密最新版本后以新 nonce＋新版本 AAD 重加密，旧行字节不变；解密失败整事务回滚，不会落"secret 缺失"新版本行；清除不需解密；设置视图 / 内部对象分型（`AiConfigView`／`DecryptedConfig`；repr、pickle、copy.deepcopy 均脱敏／拒绝）。
- reject 不创建新个人版本；`accepted_default_revision` 记录最后 init／accept／adapt 的默认修订；`changed_fields` 只记字段名；初始化／接受／拒绝／适配按 §7.2 推进 `last_seen`＝max(旧或 0, 本次目标)，GET／read 均不推进；`pending_default_update = latest_default_revision > last_seen(或 0)`。
- 审计：`operation_records` 真实 `accounts.version` 不推进账号版本；school 行 `target_version_after=NULL`（PF-1）；不在 operation_records 写提示词全文；版本行／head／审计／事件同事务原子。
- 无主密钥／错格式主密钥仅 DECRYPT_UNAVAILABLE 暂停 AI（含该任务 ADAPTATION_REQUIRED 的独立暂停），不阻断启动与手工路径。

## 7. 未执行项（不冒充完成）

1. **产品验收未做**：无真实 AI 供应商调用、无 W6 材料真机验收、无远程验收实例触达（按用户口径不得连接远程实例）；1A 状态=实现＋自动验证。
2. API／UI／worker／transport／候选落库／材料业务／secret 清理作业／execution 引用登记／任务与调用日志表：全部未实现（属后续片）。
3. DNS／连接钉住、重定向、TLS 层的 SSRF 完整防护未做（本片仅为离线字符串校验，不宣称完整 SSRF 通过）。
4. I1–I5 既有集成套件未重跑（未改既有 schema／契约）；前端未改动未跑。
5. downgrade 行为未在数据库实测（迁移 downgrade 阻断）。
6. `chinesecalendar==1.11.0` 仅声明依赖（延续 I2 约定），1A 未使用真实日历库。

## 8. 设计偏离与新增文件说明

1. 新增 `backend/app/services/ai_locks.py`（内部锁／身份 helper，避免重复 8 行身份序列；未改 auth_service，属清单 §1 允许的"必要纯内部帮助文件"）。
2. 测试侧新增 `reset_base_tables`／`_reset_variant_contracts`／`_seed_ai_tables`：world 重置会连带清种（alembic 不重放已应用 revision），故每用例世界重置后从迁移文件字面量重灌契约／默认表；按清单 §7.3 "测试夹具按系统发布协议（DML＋锚点排他锁）发布合成 v2，不新增产品 schema 编辑入口"，未改动迁移 / product schema。
3. 拒绝／接受校验组合：滑动到"目标身份→expected→身份和行与快照一致性→契约兼容性校验→幂等重试路径"——PF-3 要求重复拒绝**仍先完整校验**，实现按此顺序：identity → expected → （锚点锁内）最新契约及 based 契约派生状态（adaptation_required 一律阻断）→ 幂等判定 → 目标修订存在性与契约归属。
4. 无产品决定缺项；无系统级架构变更（未动 ARCHITECTURE.md、未新增组件）。

## 9. 停止声明

本轮不 commit／push、不部署、不进入 1B／1C；交付后停止等待协调者只读审阅。
