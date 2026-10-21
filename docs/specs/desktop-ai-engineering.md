# D2 工程核查与 OpenCode 实施清单

状态更新：2026-10-19，E1–E5设计核查完成后，用户已明确授权直接调用OpenCode先实施W1数据迁移和凭据保存，由Codex核查并继续调用OpenCode修复。W1已完成当前Windows 11合成环境工程核查（见W1核查§12），不代表D2产品或发行通过；用户随后授权W2游戏配置与提示词，已通过[当前Windows 11工程核查](../bootstrap/desktop-d2-w2-review.md#8-最终工程结论w2通过停在w2)；W3已通过[当前Windows 11合成环境工程核查](../bootstrap/desktop-d2-w3-review.md)；W4候选与原子采用已通过[当前Windows 11合成环境工程核查](../bootstrap/desktop-d2-w4-review.md)；W5界面与宿主整合已通过[W5核查§8](../bootstrap/desktop-d2-w5-review.md#8-最终工程结论w5限定源码集成通过)所列限定源码集成工程核查，W6导出／无AI降级／新完整包已通过[当前Windows 11合成环境工程核查§9](../bootstrap/desktop-d2-w6-review.md#9-最终工程结论w6限定环境工程核查通过)；新Word逐页、真实系统睡眠、G17–G18仍待验，不调用应用真实AI或发布。本文落实[产品规格](desktop-ai-daily-plan.md)的C1–C17、Q1–Q7及§9–11；具体表结构、执行器、接口和验收以本文为准。实施范围见[当前任务](../tasks/current.md)，独立证据见[W1核查记录](../bootstrap/desktop-d2-w1-review.md)。

## 1. 核查范围和结论

在`codex/desktop-v2-foundation`当前未提交工作区核查，不把HEAD当作全部被审查源码。按`codebase-memory`技能调用`list_projects`再次返回`Transport closed`，没有图谱generation／coverage证据；采用下面的限定源码阅读，没有安装或重建工具。

| 项目 | 只读发现 | 本轮工程决定 |
| --- | --- | --- |
| E1 数据与迁移 | `backend/app/local/models.py`已有内容三元FK与不可变历史；`migrate.py`拒绝未知revision；`migrations_local/env.py`已有显式事务及FK检查。`daily_plan_service.py::_validate_stored_content`拒绝全部非null基准，导出也调用此读取链 | 增量本地迁移，新增来源侧表；合法基准的读取、人工保存及导出同时接通。升级前一致性备份，冷升级，保留旧库；不降级／stamp |
| E2 凭据 | 业务已锁`cryptography==50.0.1`；旧`ai_crypto.load_material`依赖旧配置／`.env`，不可用于桌面 | AES-256-GCM密文在库；随机主密钥经Windows当前用户DPAPI保护后放独立凭据目录。用标准库`ctypes`调用系统API，不增密钥库依赖 |
| E3 执行器 | `desktop/d1_main.py`启动本机服务，`d1_host_api.py::CloseCoordinator`处理关窗；尚无AI进程收口。`httpx`在桌面输入文件中仅是测试依赖 | 主进程单协调线程＋每次尝试一个`multiprocessing spawn`网络子进程，SQLite为唯一任务权威；Job Object收口子进程。标准库HTTP/TLS，业务依赖不新增 |
| E4 接口／界面 | 本机会话保护和配置preview/apply已存在；`frontend/src/d1/leave.ts`有保存／最后输入／关闭代次保护；纯`ai_prompt_registry.py`可审查复用，旧配置及提示词服务带账号／旧库依赖 | 新本地接口；沿用D1统一离开协调，不另造绕过宿主的关闭通道；只开放三种日任务。统一回执键和预览凭证 |
| E5 验收 | D1人工与工程证据不覆盖AI状态、凭据、非空基准或收费调用 | 下文G01–G18按数据库、真实进程、界面、真实供应商和Word区分证据。模拟成功不替代真实供应商／人工验收 |

本方案在Architecture v2已允许的本地执行进程细化范围内；没有改变技术栈、业务数据权威或模块通信方向，不改`ARCHITECTURE.md`。下面的“须／采用”都是待实现要求，不是声称现有代码已具备。

## 2. E1：持久数据、约束和升级

### 2.1 数据约定及具体对象

沿用SQLite、SQLAlchemy与独立`local_alembic_version`迁移链。ID沿用32字符opaque ID；request_id为标准UUID字符串36字符；版本为严格正整数（未配置AI的公开版本为0），时间UTC，hash为SHA-256小写hex。JSON在应用层用严格schema验证；指纹使用排序键、无多余空白、UTF-8、禁止NaN的规范JSON，字符串保留有意义空白，不擅自trim教案。`null`与省略按各schema处理。

下表是实际表／列的实现契约，非执行SQL。`PK/UQ/FK`分别为主键、唯一键、外键；除注明可空及可变字段外，配置／快照／版本／候选追加后不修改。所有新表FK默认RESTRICT，不用级联清除历史。所有表有`created_at`，状态头另有`updated_at`；枚举、正版本、nonce长度及必要null组合用CHECK，JSON语义由服务校验。

| 表 | 列及约束 |
| --- | --- |
| `local_ai_state` | `profile_id PK/FK local_profile`、`database_uuid UQ`、`current_config_version nullable`、`blocked_config_version nullable`、`blocked_reason nullable`。两配置指针分别以`(profile_id,version)`FK指向配置表；仅指针／阻塞信息可变。空库尚未建立档案时无此行 |
| `local_ai_credentials` | `id PK, profile_id FK, key_id, nonce BLOB, ciphertext BLOB, state=active/retired/cleared`；UQ`(profile_id,id)`；active必须nonce12字节且有带tag密文，cleared两者必须null。密文按§3清除时允许变更，版本元数据不清除 |
| `local_ai_config_versions` | PK`(profile_id,version)`；`profile_id FK, protocol_id=chat_completions_v1, base_url, model, credential_id nullable`；复合FK`(profile_id,credential_id)`；`version>=1`。凭据置空表示未配置密钥，不以空串代替 |
| `local_class_game_revisions` | `id PK, class_id FK local_classes, revision_no>=1, payload_json, payload_hash`；UQ`(class_id,revision_no)`、`(class_id,id)` |
| `local_class_game_heads` | `class_id PK/FK, current_revision_id`；复合FK`(class_id,current_revision_id)`指向前表。首次初始化／旧库升级建立空配置第1版，不增加D1全局config_version |
| `local_prompt_bundles` | PK`(task_type,contract_version,default_revision)`；三种task枚举；`input_schema_json, output_schema_json, guidance_defaults_json, bundle_hash`。应用包内清单是新契约来源；同键内容hash不同拒绝该AI配置同步，不能原地改历史 |
| `local_personal_prompt_versions` | PK`(profile_id,task_type,revision)`；`profile_id FK, contract_version, based_default_revision, guidance_json, orphaned_guidance_json, action=initial/edit/accept/reject/adapt, rejected_default_revision nullable`；指向所基于bundle的三元FK；拒绝修订也须引用存在且同contract的bundle。被移除的个人字段留在orphaned，不发往模型 |
| `local_personal_prompt_heads` | PK`(profile_id,task_type)`；`current_revision, required_contract_version, latest_default_revision`；分别复合FK到个人版本及bundle，跨任务指针不合法。可变头部，适配状态由版本匹配派生，不接受客户端布尔标记 |
| `local_ai_inputs` | `id PK, daily_plan_id, content_id, content_version, task_type, target_grade, input_schema_version, payload_json, dependencies_json, dependency_hash, target_hashes_json`；FK`(daily_plan_id,content_id,content_version)`到D1内容三元组；UQ`(daily_plan_id,id,task_type)` |
| `local_ai_tasks` | `id PK, profile_id FK, daily_plan_id, task_type, input_id, status, reason nullable, current_execution_id nullable, generation>=0, runtime_meta_json, updated_at`；复合FK`(daily_plan_id,input_id,task_type)`到输入；UQ`(daily_plan_id,id,input_id,task_type)`；`(id,current_execution_id)`使用下述FK。状态见产品规格§10；任务行是可变调度头 |
| `local_ai_executions` | `id PK, task_id, daily_plan_id, input_id, task_type, generation>=1, launch_id, permit_id, config_version, profile_id, personal_revision, contract_version, default_revision, state, runtime_meta_json, started_at, ended_at nullable`；UQ`(task_id,generation)`、`(task_id,id)`、`(daily_plan_id,task_id,input_id,task_type,id)`；四元FK到task，配置／个人指导／bundle均复合FK。版本身份不得改；state／结束时间可变 |
| `local_ai_attempts` | `id PK, execution_id FK, attempt_no BETWEEN 1 AND 3, state, dispatch_marked_at nullable, ended_at nullable, evidence_code nullable, http_status nullable, provider_request_id nullable, returned_model nullable, usage_json nullable, duration_ms nullable`；UQ`(execution_id,attempt_no)`。只保存白名单诊断元数据，不存Authorization、请求体或错误响应全文 |
| `local_ai_candidates` | `id PK, execution_id, task_id, daily_plan_id, input_id, task_type, contract_version, schema_version, raw_candidate_json, candidate_hash`；UQ`execution_id`、`(daily_plan_id,id)`；五元FK到execution保证计划／任务／输入一致。raw是通过严格校验的模型候选，不是教师改后内容 |
| `local_daily_plan_ai_provenance` | `content_id PK, daily_plan_id, content_version, baseline_candidate_id nullable, adopted_candidate_id nullable, selected_targets_json, adopted_payload_hash nullable`；内容三元FK；两候选各用`(daily_plan_id,candidate_id)`复合FK，禁止跨计划关联。baseline候选必须是同计划成功拆分；这一语义及JSON相等性由共享读取／写入验证器落实 |
| `local_ai_operations` | `id PK, profile_id FK, request_id, operation_kind, request_fingerprint, fingerprint_kind=sha256/hmac_sha256, fingerprint_key_id nullable, result_json`；UQ`(profile_id,request_id)`。覆盖D2 AI配置／指导／任务／采用，键跨这些操作域唯一；同键异域或异内容409。游戏配置继续用原`local_config_operations`，不混成第二套D1回执 |

任务的`(id,current_execution_id)`为DEFERRABLE INITIALLY DEFERRED复合FK到execution的`(task_id,id)`；首次pending为空，再次排队时保留上次执行引用供查询。执行按固定输入追加，resume/retry只重新排队，实际领取才创建新generation，不改旧执行。上述多列UQ是SQLite复合FK所需的父键，不能只留独立id主键后依赖ORM判断。

新增索引：task`(status,created_at,id)`及`(daily_plan_id,created_at,id)`；candidate`(daily_plan_id,created_at,id)`；attempt`execution_id`；各来源FK查询列。部分唯一索引`(daily_plan_id,task_type) WHERE status IN ('pending','claimed','dispatching','retry_wait')`只允许同计划同类型一个活跃任务；paused/unknown可保留多份记录，恢复遇到活跃任务也409。没有持久TTL租约抢占：OS运行锁及执行permit共同保护，过期时钟不能自动认领旧请求。

### 2.2 输入依赖与基准不变式

- 输入载荷遵守产品规格§9.1。依赖指纹仅取实际发送的业务值：拆分=原文＋本次年级；适龄=当前过程＋本次年级＋当前基准来源引用；其他活动=日期／计划周次星期／本次年级／集体活动及四板块／当前有效日历上下文及±7日节假日／游戏修订。生成用的组／游戏ID先剔除；服务端输入对象内保留来源身份供审计。全局config_version、姓名、反思、AI设置及个人指导后续变化不充当候选业务过期条件。
- 其他活动的游戏配置取计划所属class，日历取计划所属term的当前已持久修订，计划表头／week_number不重算。日历仅无关日期变化时比较实际上下文hash，不因全学期revision改变误判；游戏配置修订本身是依赖。库不覆盖的节日只标unknown，不补猜。以相同投影函数创建、发送前及采用前复核。
- `split_baseline`在D2固定为`{group_activity_process: string}`，其值精确取`raw_candidate_json.group_activity.process`；六字段原始拆分完整保存在candidate。已核对`word_export_mapping.py::split_baseline_process`只读取此键，不能将candidate外层封套或`process`键直接塞入基准。空字符串是合法基准，与null无基准不同。
- D1历史无provenance行且baseline=null合法。D2新建／保存／采用版本均写一行provenance：无基准时baseline_candidate_id=null；有基准则继承原引用，手工保存的adopted_candidate_id=null。非null基准但缺来源、类型错误、内容与来源不一致一律存储错误，不降格为无基准。
- 拆分采用同时保存六字段、基准及引用；适龄只改process，其他活动只改选定板块。基准关联来自候选真实输入，当前原文以后修改也不覆盖历史。当前显示“来自所采用的原文版本”；不把它冒充当前原文的拆分结果。
- 采用事务顺序：先查回执 → 验证token及版本、来源、选择／编辑hash → 按当前内容合并选定字段并服务端分配ID → 追加内容与provenance → 条件更新plan当前三元指针 → 写回执和审计 → COMMIT。任何一步失败全部回滚；网络不在事务内。
- 语义内容、基准来源均未变化时只写幂等回执，返回`changed=false`及原版本；不因重新分配ID制造假变化。目标以去ID的业务值比较。已采用候选不提供绕过版本／依赖检查的重放入口。

### 2.3 迁移及保留

1. 新建一个本地revision（建议`20261017_0004_local_ai`，已核对down_revision为`20261014_0003_local`）；不修改既有迁移。新表为主，不重建／回写D1计划和内容表，不添加假AI基准。新增表、空游戏头及已存在档案的AI/prompt初版，在同一显式迁移事务中提交；迁移内默认bundle使用冻结的D2初版快照，不导入会随应用变化的registry来重写历史迁移。首次新档案在原初始化事务中补齐同样对象。
2. 只允许冷升级：先关闭旧／新应用，拿到数据根独占运行锁，再检查schema。升级前用Windows独占打开探测数据库仍被其他进程占用时拒绝升级；不杀旧进程。旧D1不懂新运行锁，因此不声称支持旧进程仍开着的热升级。没有自动安装／替换旧包流程。
3. 对非空已知旧库，用SQLite backup API生成`data_dir/migration-backups/pre-D2-<UTC>-<id>.sqlite`；包含已提交WAL数据，不能只复制`.db`。验证备份`integrity_check`、`foreign_key_check`和revision，关闭句柄后计算SHA-256；写仅含版本／时间／hash的清单，成功后才升级。备份失败拒绝迁移。见[SQLite官方备份说明](https://www.sqlite.org/backup.html)。
4. 迁移沿用现有env显式BEGIN IMMEDIATE与FK检查；故障完整ROLLBACK。保留原库和备份，不自动覆盖式恢复、不stamp、不自动downgrade；未知／更新／多行revision继续拒绝启动。升级后再次检查完整性、D1历史行／指针／表头／版本逻辑摘要一致，旧D1包对升级副本必须报`LOCAL_DB_VERSION_UNSUPPORTED`且不开放写API。
5. D2元数据、候选、输入快照、个人指导、来源及回执本片不自动清理；长期保留策略后续确认。AI凭据是例外，按§3撤销密文，不为历史复现永久保存旧密钥。预览token只在内存，10分钟失效，重启重新预览，不要求持久编辑草稿。

## 3. E2：Windows凭据保存

选择`cryptography`现有AESGCM＋Windows `CryptProtectData/CryptUnprotectData`当前用户模式；**不**设置`CRYPTPROTECT_LOCAL_MACHINE`，设置`CRYPTPROTECT_UI_FORBIDDEN`、PromptStruct=null，释放返回buffer用`LocalFree`。DPAPI通常受用户／机器约束但存在漫游配置例外，产品仅承诺当前设备使用、换机重新填写，不声称绝对硬件绑定。[Microsoft DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)

- 密钥材料固定放`%LOCALAPPDATA%/KindergartenManager/credentials/<database_uuid>/<key_id>.dpapi`，数据库只存key_id和加密secret。`database_uuid`首次生成后不因移动业务库改变；测试必须注入独立credential_root，禁止落真实目录。业务备份不包含credentials，不在安装目录、仓库或`.env`保存材料。
- 首次保存新secret才产生随机32字节主密钥和随机key_id。每条secret用随机12字节nonce；AAD为规范编码的`["kgm-local-ai-v1",database_uuid,profile_id,credential_id,key_id]`。同credential可由多个无密钥变动的配置版本引用，不能把配置版本变化当成可复用nonce的理由。认证失败按凭据不可用，不尝试明文或旧云端key。
- 用`ctypes`准确声明64位结构／参数／返回值；DPAPI来自Crypt32，ACL来自Advapi32，句柄来自Kernel32。凭据目录及文件在创建时设受保护DACL，仅当前用户SID与SYSTEM完全控制，避免先宽权限落盘再收窄；检查owner、ACL及重解析路径，失败即拒绝保存secret。使用SECURITY_ATTRIBUTES和SDDL转换／GetSecurityInfo核验，不靠Python chmod模拟Windows ACL。[文件权限](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights)、[创建时安全描述符](https://learn.microsoft.com/en-us/windows/win32/secauthz/security-descriptors-for-new-objects)
- 顺序：受限同目录临时文件写DPAPI blob → flush/FlushFileBuffers → 原子移到从未使用的key_id路径 → 读回解保护验证 → 短事务保存credential、配置头、回执。文件阶段或DB阶段失败不能切换当前配置；孤立blob无活动引用，不自动删除未知文件。更新已有secret不覆写正在使用的主密钥文件。
- 当前库引用的key文件缺失、损坏、ACL不符或其他用户无法解密时，`ready=false,reason=CREDENTIAL_UNAVAILABLE`，手工路径仍用。不得启动时静默生成新主密钥掩盖故障。教师明确重新填写secret可创建新key_id修复当前配置，旧历史元数据保留；无需恢复旧key才可重填。
- 省略secret保留原凭据；显式null、空串或空白密钥422，清除用独立动作。清除当前密钥创建新配置版且credential_id=null，同时将该档案所有旧credential密文／nonce置null、state=cleared；配置／执行历史引用保留。已发送worker可能仍持内存副本，界面说明清除不撤回在途请求。替换secret后旧凭据仅在已钉住的执行尚需安全重试期间保留，执行结束／退役后清除；不允许恢复旧执行来使用退役key。
- GET仅返回`has_secret,configured,ready,reason`；`has_secret`表示当前配置引用非cleared密文，`configured`表示地址／模型／密钥已填写，`ready`还需本机解密可用，均不表示已连接供应商。内存secret不得写argv、环境变量、临时JSON、日志、前端storage、异常repr。前端密码输入仅在保存期间保留，成功后清空。
- 配置写回执不能存secret明文或其普通SHA摘要。含secret请求用主密钥派生独立HMAC键计算规范请求指纹，回执记key_id；重传验证需要该key，可用则比较，同键不同secret409；key不可读时返回已提交脱敏回执供GET核对并拒绝重新执行该键。clear-secret无secret时用SHA-256。不要用客户端hash代替服务端核验。
- 依赖决定：不新增keyring、pywin32、OpenAI SDK或HTTP运行时依赖；保留业务26包、CPython3.14.7／x64／标准GIL及现有锁。`httpx`仅可作既有测试工具。若实现证据证明必须加依赖，先给必要性和锁／打包影响供技术审阅，不自行扩栈。本轮未调用DPAPI或安装任何东西。

## 4. E3：执行器、网络及生命周期

### 4.1 执行组织与许可

主进程持有SQLite运行时，一个协调线程负责短事务调度与结果落库；每次网络尝试创建一个`multiprocessing.get_context('spawn')`子进程。全应用最多一个在途供应商请求，FIFO按`created_at,id`；暂停项不阻塞后面的就绪项。子进程不打开SQLite、不导入旧配置／云端服务、不启动FastAPI或GUI，只处理一个不可变请求。线程不能可靠终止卡住的DNS或socket，因此选择有独立终止边界的子进程；这不是常驻后台服务。

1. 主进程在`LocalRuntime.prepare`之前独占打开数据根`.app-runtime.lock`（Windows CreateFileW，share mode 0，句柄不继承），持有到子进程收口和DB关闭之后；第二实例报`LOCAL_APP_ALREADY_RUNNING`。规范化实际数据根，拒绝重解析／硬链接别名绕过锁的受管数据库路径；同一root的启动、升级和普通运行共用此锁，不能仅靠PID文件。不同合成根可独立验证。
2. 每次启动生成随机`launch_id`；领取时BEGIN IMMEDIATE复核任务状态、输入投影、配置及指导可用性，新增execution、generation、permit_id并切到claimed。开始后的安全自动重试沿用该execution所钉版本；手动resume/retry只重新排队，下次实际领取才创建新execution并取当时最新有效配置／指导，不能在排队点击时提前钉版本。retry_wait中配置升级不偷换已开始执行。
3. 创建独立匿名Job Object，设置`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`，不允许breakaway；spawn子进程先只等IPC。父进程完成`AssignProcessToJobObject`后才允许准备网络，Job句柄只归父进程且不可继承。赋予Job失败就终止子进程并暂停AI，手工功能继续。父进程在分配前崩溃时，子进程从管道EOF或5秒启动握手超时退出，不能自行发送。Windows支持Job及嵌套Job，但受外层Job限制仍可能失败，须真实包验证。[Job文档](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)、[终止标志](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information)
4. IPC使用每次尝试独享的双向Pipe和有界JSON bytes帧，`send_bytes/recv_bytes(maxlength)`，不接受来自模型的pickle／可执行对象；bootstrap只传必要句柄。控制帧最多16KiB，请求／响应帧最多1MiB正文＋16KiB元信息。秘钥仅通过受控IPC交给该worker内存；不能将key写入启动参数。终止后的Pipe丢弃，下一次新建，不复用可能断裂的队列／锁。[Python进程及终止注意事项](https://docs.python.org/3.14/library/multiprocessing.html)
5. worker完成DNS／TLS后发`READY_TO_SEND`，父进程再次检查关闭代次、permit及业务依赖，在短事务中提交attempt发送标记并设dispatching，然后发一次`SEND`。未收到SEND绝不能写HTTP请求字节。SEND丢失也按可能发送处理；socket send抛错不证明零字节。收到子进程数据还要在父进程严格验证，只有同launch／generation／permit且当前dispatching才可提交。
6. 同一事务提交唯一candidate、attempt结果、execution及task succeeded。重复帧由唯一键／条件更新挡住；取消先提交则迟到帧不能落库，成功先提交则取消读回成功。外部结果已返回但DB提交失败，先只重试本地提交／查询，不重新联网；不可持久化时保留内存结果并停止调度，进程退出后依据发送标记归为unknown。

冻结包入口在参数解析、GUI导入及启动副作用前分流`multiprocessing.freeze_support()`；子进程入口必须可导入且无顶层应用启动。不得让每个worker再开一个主窗口／迁移库。现有PyInstaller版本文档明确需要这一处理；打包验证包括无控制台、资源路径和正常／崩溃退出。[PyInstaller说明](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#multi-processing)

关闭冻结与最终SEND使用同一短临界区：DB发送标记提交后仍须重查冻结／permit，再发控制帧；若此时已关闭冻结，即使尚未发送也保守按标记处理。该锁不跨DB等待、网络或用户对话，原生closing回调不能等待长事务。子进程收到SEND还须检查父进程提供的GetTickCount64绝对期限，休眠期间耗尽预算后不得再开始写请求。

### 4.2 协议和网络边界

2026-10-21用户确认实时思考展示，已按[流式设计](desktop-ai-streaming-progress.md)扩展原非流式协议、现有IPC进度帧及本地只读进度查询；当前Windows 11合成工程核查通过，见[独立结论](../bootstrap/desktop-d2-streaming-review.md#11-最终交付限定合成工程核查通过)。原网络防护、期限、许可、最终校验及恢复语义保持，真实供应商仍未验。

- 采用产品规格§11的Chat Completions文本JSON子集，请求`stream:true`，SSE思考只作临时展示、正文完整后校验；同一请求的合法JSON响应保持兼容，不补发。规范化HTTPS前缀后只追加`/chat/completions`；拒绝userinfo、query、fragment、控制字符、反斜线、内网／回环／链路本地／保留地址、非常规数值IP和完整completion路径。端口允许显式1–65535，不把“公网HTTPS”缩成某供应商品牌名单。
- 每次尝试解析A/AAAA，限制解析结果最多32个且全部必须是允许的全球单播地址；IPv4-mapped IPv6同样检查，混合公私地址直接拒绝。socket连接明确的已验证numeric sockaddr，连接后getpeername与选中地址核对，不让HTTP库按hostname再解析。可在**发送前**依次尝试该批地址，10秒连接总预算不重置；HTTP一旦可能发送，不换地址重发。
- 用标准库`socket`＋`ssl.create_default_context`＋`http.client.HTTPResponse`解析响应；TLS保留原hostname的SNI及证书主机名验证，Host header同源。HTTPS握手后、发送前再检查剩余时限。不要以替换URL host为IP的方式关闭主机名校验。[Python TLS](https://docs.python.org/3.14/library/ssl.html)、[HTTP接口](https://docs.python.org/3.14/library/http.client.html)
- 不继承HTTP_PROXY/HTTPS_PROXY/ALL_PROXY，不自动redirect，不执行CONNECT，不禁用证书验证。固定`Accept-Encoding: identity`、Content-Length、`Connection: close`；首片拒绝gzip/br等非identity Content-Encoding，不做无界解压。拒绝冲突Content-Length／Transfer-Encoding及无效HTTP帧；限制响应头64KiB、正文1MiB（分块读取也累计），不得只相信Content-Length。错误体也受同样上限，避免写入日志。
- 连接预算10秒包含DNS／TCP／TLS；一次尝试从worker启动到完整响应最多120秒，由父进程监督，即使DNS线程卡死也能终止worker。HTTP请求序列化后最多1MiB，不截断输入。父进程用Windows GetTickCount64记包含休眠的期限，UTC只作记录；不能用系统墙钟调整延长调用。[Windows时间说明](https://learn.microsoft.com/en-us/windows/win32/sysinfo/interrupt-time)
- 网络完成：HTTP成功、`choices`恰有一个正常文本选项、`finish_reason=stop`、无tool_calls/function_call/refusal，content为单个严格JSON对象；拒绝重复JSON键、NaN、围栏、前后自由文字、未知候选字段／非法枚举。协议封套允许无关标准元信息，候选schema递归extra=forbid。结果不合规记failed，不发自动修复请求。
- 基础供应商适配器没有“已处理／未处理”的私有错误证明规则。所有HTTP 429/5xx都不自动重发；401/403及已明确识别的配置拒绝暂停，不能仅凭HTTP状态断言未计费。通用5xx／中断为outcome_unknown；完整429错误为paused但`processing_certainty=unknown`。只有DNS／连接／TLS前已确定未发HTTP字节的暂时错误，才最多再试2次，间隔5／30秒。证书／目标策略失败不重试。将来增加供应商“明确未处理”规则须单独证据与审阅。

### 4.3 状态、退出和恢复的确定行为

每次状态变化按事务内expected execution／permit判断，任何GET失败不改变任务状态。task／execution的`runtime_meta_json`固定schema为`{processing_certainty:not_sent|response_received|unknown,user_stop_requested:bool,permit_revoked_at:UTC|null,next_attempt_at:UTC|null}`；有本轮execution时task投影与其同事务推进，不从reason字符串猜测。重新pending为not_sent／false／null／null，上次execution保留原结果且不随pending重置；明确成功或完整无效输出可记response_received，供应商错误不构成未处理证明，重试风险独立判断。

| 事件 | 持久动作及界面结果 |
| --- | --- |
| 提交时未配置／指导未适配 | 409及设置入口，不创建任务；排队后才失效则paused，不丢原input |
| 发送前来源变了 | paused/source_changed，结束旧execution；只能重新生成或取消，resume不暗换input |
| 连接前暂时错误 | 记录attempt not_sent；未超3次→retry_wait；耗尽→failed/connection_unavailable。每次再试先验来源和permit |
| 鉴权／配置／限流暂停 | 本次execution结束；config相关拒绝同时设置blocked_config_version，避免后续任务反复打同一坏配置；修改配置不自动恢复paused任务。显式resume/retry可解除对应版本阻塞并只恢复选中任务 |
| JSON／schema／业务输出不合规 | failed/output_invalid，保留输入和脱敏错误；可显式retry，提示会产生新的请求 |
| 可能发送后失联／超时／停止 | outcome_unknown；保留已发证据，绝无自动重发；手动retry必须确认可能重复处理／费用 |
| 启动恢复 | 获取运行锁后先归并旧状态：pending/claimed且无发送标记、retry_wait且全为not_sent→paused/restart；dispatching有标记无成功提交→outcome_unknown；succeeded保持。恢复不启动外部网络 |
| 休眠恢复 | 不生成新执行；仍在120秒总期限内、有原permit及确定响应可正常提交；过期先退役permit并终止worker，再按是否发送分类。父线程恢复时先检查期限再接受已排队响应，避免超时结果绕过规则 |
| 切日／回工作台 | D1先保存正文，成功后导航；AI继续。候选脏预览须先采用或明确取消编辑；任务通知不能驱动编辑器reset |
| 取消任务 | 未发送→cancelled；已可能发送→outcome_unknown并记user_stop；已成功→返回实际成功。不声称供应商取消成功 |

关窗握手扩展既有`close_request_id＋generation`，不发一个不受宿主约束的shutdown API：宿主接到close意图即冻结新claim／SEND；当前网络可返回并提交。页面先处理正文、设置、候选草稿；失败或新输入撤销此次关闭并解冻。存在active任务时显示“继续等待／停止等待并退出”；继续等待取消close并解冻，已在途保持，未发任务继续排队。

选择停止等待后：宿主验证当前close身份 → 一个短事务撤销所有未完成permit并按发送证据暂停／unknown（成功先提交则保持成功）→ 停止worker，最多2秒协作等待后TerminateJobObject，最多3秒确认退出 → 确认D1保存与最终关闭ack仍有效 → 销毁窗口。DB失败或未能证实worker退出就拒绝正常关闭，保留页面说明；不得调用`os._exit`伪装成功。取消关闭恢复调度只针对本次close尚未退役的任务；已停止的任务留作手动恢复。

宿主销毁的最后一步继续使用D1代次／最后输入／原生保存busy检查，并增加“任务已收口”的后端屏障。仅前端声称已停止不足以放行。重复close、旧ack迟到、最后ack丢失、候选刚提交等均按当前代次复核；没有活动任务时沿用原关闭行为。

## 5. E4：本机接口、提示词和界面契约

### 5.1 通用类型和响应

只对本地当前档案服务，不接收owner/profile/class任意归属；新增API全部接入现有session、Host和Origin保护，响应`Cache-Control: no-store`。请求递归extra=forbid，strict integer拒绝bool／浮点。三种TaskType及Grade枚举与产品规格§9.1相同。每个变更含`request_id`；preview和GET例外。幂等检查在版本检查前：原操作已提交时旧expected版本也读回原结果。

- `ConfigOut={ai_config_version:int>=0,protocol_id,base_url:string|null,model:string|null,has_secret:bool,configured:bool,ready:bool,reason:code|null}`。未配置为version0；读不到key只影响ready。
- `PromptOut={task_type,personal_revision,contract_version,based_default_revision,required_contract_version,latest_default_revision,guidance:map<string,string>,fields:[{key,label,default_text}],rejected_default_revision:null|int,adaptation_required:bool,orphaned_guidance:map}`；详细比较读取指定bundle，不把最新文本冒充旧修订。
- `TaskOut={id,plan_id,task_type,status,reason,processing_certainty,user_stop_requested,created_at,updated_at,input_summary:{content_version,target_grade,dependency_hash},execution:null|{id,generation,ai_config_version,personal_revision,contract_version,default_revision,attempt_no},candidate_id:null|id,allowed_actions:[resume|retry|cancel|view],retry_requires_ack:bool}`。列表不返回材料全文；detail也不带key、完整网络响应或调用stack。
- `CandidateOut={id,plan_id,task_id,execution_id,task_type,contract_version,schema_version,raw_candidate,source:{content_version,target_grade,dependencies,source_excerpt},adoption_state:eligible|source_changed|contract_obsolete,available_targets:[...],latest_content_version}`。source_excerpt只包含该类必要原文／过程／活动输入，通过detail返回，不放列表或日志；不返回私密secret。已落库候选始终可查看。
- `ReceiptOut={request_id,operation_kind,result,committed_at}`。未知request_id返回404 `AI_OPERATION_NOT_FOUND`，不等于失败或未提交；同键重试提交可安全回读，不能自动换键。无法核验含secret旧请求指纹时返回409 `AI_RECEIPT_UNVERIFIABLE`，附已提交脱敏结果，不再次保存；GET仍可读。
- 分页GET统一`limit`默认20、范围1–100，`cursor`为不透明`created_at,id`游标，返回`{items,next_cursor}`；任务可筛plan_id和status，候选列表必须plan路径。错误沿D1`{error:{code,message,...details}}`，details仅含当前版本／阻塞字段／重试动作等白名单。

### 5.2 端点与写入字段

路径中的`T`仅表示三类task_type，`id`为服务端ID；下表列出完整业务输入，通用request_id不再逐格重复。所有空值和省略规则固定，不让前端猜测。

| 方法／路径 | 输入（除request_id） | 成功及冲突行为 |
| --- | --- | --- |
| GET `/api/local/ai/config` | 无 | 200 ConfigOut |
| PATCH `/api/local/ai/config` | `expected_ai_config_version>=0,protocol_id,base_url(1..2048),model(1..200),secret?`；secret1..8192字符且不允许首尾空白／控制字符，省略保留 | 200 ConfigOut；语义无变化不增版；密钥改动由服务端比较，不能存明文摘要 |
| POST `/api/local/ai/config/clear-secret` | `expected_ai_config_version` | 200 ConfigOut；已空无变化；在途处理见§3 |
| GET `/api/local/ai/prompts`、`/prompts/T` | 无 | 200列表／PromptOut，仅日三类 |
| GET `/api/local/ai/prompts/T/defaults/{contract_version}/{default_revision}` | 无 | 200不可变`{task_type,contract_version,default_revision,guidance,fields,bundle_hash}`；不存在404 |
| PATCH `/api/local/ai/prompts/T` | `expected_personal_revision,contract_version,guidance`完整当前可编辑字段map，每字段0..8000字符 | 200 PromptOut；保留空指导，未知／缺字段422；needs_adaptation时普通编辑只保留旧契约文字，不完成适配 |
| POST `/api/local/ai/prompts/T/accept-default` | `expected_personal_revision,target_contract_version,target_default_revision,selected_fields`非空去重 | 200新PromptOut；仅覆盖所选字段，绑定实际查看目标；同契约发布更晚默认不使该目标失效，也不一并接受 |
| POST `/api/local/ai/prompts/T/reject-default` | `expected_personal_revision,target_contract_version,target_default_revision` | 200；记录该修订拒绝，不改guidance，不解除required contract适配 |
| POST `/api/local/ai/prompts/T/adapt` | `expected_personal_revision,target_contract_version,target_default_revision,guidance`完整新契约字段map | 200；目标contract必须当前required；变更后409保留输入；不传`adapted=true` |
| GET `/api/local/config/class-games` | 无；当前班级由服务端取得 | 200 `{class_id,class_name,grade,config_version,game_revision_id,revision_no,change}`；change为可编辑的平铺class_games对象。只读，不创建预览或新版本 |
| POST `/api/local/config/preview`、`/apply` | 沿D1字段，新增`change={kind:class_games,locations,game_scope,guidance}`，无任意class_id；限额见产品规格§9.1 | 沿D1 preview/apply响应；游戏revision和config_version原子推进，旧计划不改。无变化不增任何版本 |
| POST `/api/daily-plans/{id}/ai-tasks` | `task_type,expected_content_version,target_grade` | 202 TaskOut；保存后快照，提交不直接调用；source空422、未配置409、重复活跃409。同键读回原任务即使已完成也不重排 |
| GET `/api/local/ai/tasks`、`/tasks/{id}` | 通用分页／筛选或无 | 200列表／TaskOut；状态失败仍200 |
| POST `/api/local/ai/tasks/{id}/cancel` | `expected_execution_id:id|null`（只在尚无任何执行时为null，否则为当前引用） | 200 TaskOut，幂等cancel；已成功回实际成功，不伪造撤回；取消重新pending仅撤销此次排队，不改上次执行事实 |
| POST `/api/local/ai/tasks/{id}/resume` | `expected_execution_id:id|null` | 202 pending TaskOut；仅确定未发送、来源仍有效且原因已解除的paused任务；领取时建新execution版本。曾发送的暂停改用retry |
| POST `/api/local/ai/tasks/{id}/retry` | `expected_execution_id:id,ack_duplicate_cost:bool=false` | 202 pending TaskOut；仅failed/paused/outcome_unknown；输入未变才重新排队，领取时建新execution。unknown或无法证明未处理的已发送错误必须ack=true；普通failed也明确说明新请求可能计费 |
| GET `/api/daily-plans/{id}/ai-candidates`、`/{candidate_id}` | 分页或无 | 200摘要列表／CandidateOut；foreign plan与不存在统一404 |
| POST `/api/daily-plans/{id}/ai-candidates/{candidate_id}/preview-adoption` | `expected_content_version,selected_targets,edited_candidate` | 200 AdoptionPreview；该候选类型严格校验，不接受正文全量、group_id/game_id、baseline或来源ID |
| POST 同路径`/adopt` | `expected_content_version,preview_token` | 200`{changed,plan_id,content_id,content_version,candidate_id,selected_targets,request_id}`；payload从服务器token缓存读取，不再让客户端换内容 |
| GET `/api/local/ai/operations/{request_id}` | 无 | 200 ReceiptOut／404未知；只读查询，不调用供应商 |

`AdoptionPreview={preview_token,expires_at,content_version,candidate_id,selected_targets,before,after,warnings}`。token是随机32字节base64url、保存在当前会话有界内存，10分钟有效、最多64个（逐出旧项需重新预览），绑定profile／launch／app session scope／plan／candidate／选择／编辑hash／依赖hash／目标hash／当前版本。adopt先查持久回执再查token，所以成功响应丢失后token已耗用也能恢复；token失效409重新预览，未提交操作可同request_id带新预览重试。多token不能绕过内容版本条件更新。

W4接口与不变式细化（2026-10-18，核查R01–R09）：

- 采用请求指纹包含路径plan/candidate、expected版本及**原preview_token本身**。同键同体在token耗用或重启后仍回原结果；已经成功的同键换新token属于异体冲突。未提交操作仍可同键带新预览重试。首次查回执与取token之间可能有另一请求提交，token缺失时须再次查持久回执，不能把已提交重复请求误报过期。
- app session scope为每次创建本地app时生成的内部随机身份，不是X-App-Session密钥，不返回或持久化。事务内复核token绑定版本与请求expected相同、token仍有效及当前required契约；客户端提高expected不能复活旧预览。CAS同时核对plan及原content_id/content_version。
- 通过token/request绑定检查后，采用对当前业务事实按“来源变化 → 目标变化 → 无关版本变化”分类，分别返回`AI_SOURCE_CHANGED`、`AI_TARGET_CHANGED`、`VERSION_CONFLICT`；依赖与目标重叠时来源优先。preview请求expected旧仍是`VERSION_CONFLICT`。这些冲突均不提交正文，W5应保留候选编辑，按原产品规格重新生成或重新预览，不增加流程。
- 候选详情`source.dependencies`及`source_excerpt`来自真实冻结输入；其他活动包括游戏配置、计划快照和日历上下文。列表不包含材料，错误只返回安全变化字段名。按plan和candidate同时在SQL过滤后才物化JSON，外计划与不存在均404，本计划损坏存储仍503。
- 列表、详情、预览、采用及历史基准读取共用候选完整关系校验：同计划task/input/execution/candidate、成功状态、类型与契约身份、候选hash及冻结schema。当前required契约只决定新预览/采用资格，不能使已采用历史基准失效。非string原始过程不得转为空串；合法空串与null继续区分。手工保存/原文后改继承基准与引用，导出读取同一验证链。

W2接口细化（2026-10-18）：游戏preview的`normalized_change`保持平铺、可直接作为apply的change；有修改的apply另返`game_revision_id`，其余动作/无变化可为null，当前修订身份从只读端点取得。空游戏文字`""`规范为null，非空文字保留原空白；个人指导的空字符串原样保留。游戏读取不开放任意班级选择。新增读取端点是W5设置预填所需接口，不增加配置流程。

### 5.3 候选schema及默认指导落地

- 拆分`{group_activity:{theme,objectives,preparation,key_points,difficult_points,process}}`六个必需string，可空；采用目标只能`[group_activity]`。适龄`{process:string}`，目标只能`[group_activity.process]`；空过程可在预览明确显示，不凭空补写。
- 其他活动沿纯registry的`morning_games, morning_talk, post_group_games, afternoon_outdoor`结构：morning组含`group_kind,games:[{name}],focus_guidance?,shared_objectives?,guidance_points?`；talk含`topic,questions`；post组含`context_kind,games,area?,focus_guidance?,objectives?,guidance?,support_strategy?`；afternoon含`games,area?,observation_focus?,objectives?,guidance?,support_strategy?`。可选字段省略合法、显式null不合法；不得接受ID、反思或模板外字段。至少提供一个板块，否则output_invalid；缺板块不可勾选，显示未生成。
- 晨间板块一旦提供，D2生成校验要求恰好一collective组及一free_choice组，每组恰好一game，保留两组的共享文本；现有registry只限制每种最多一组，故需本地D2校验补上，不能据旧模型宣称已满足C6。不改变D1手工保存的组结构规则；固定“体能大循环”由业务／Word模板保持，不交给模型改写。
- 其他活动选择必须非空、去重且为候选已提供板块的子集；预览教师编辑仍使用相同候选schema。除已有业务限额外，新增候选／教师编辑序列化总量最多1MiB、单字符串最多100000字符、数组最多100项，校验深度受固定schema约束；这些是工程容量保护，不截断材料。真实用例若超过再凭证据调整限额。
- 默认bundle在应用内随包交付，只登记三类日任务；纯registry及默认文字逐项复用审查，禁止导入旧prompt_service的账号／MySQL入口。首次档案建三个initial个人版本，使用包内默认快照；AI入口明确显示“使用默认指导”并可展开查看／编辑，无需先配置全部任务。升级仅写新bundle／required与latest头，不改教师个人内容。
- 默认文字更新保持当前指导可执行；拒绝记录准确修订，接受只覆盖选择字段。必需字段升级保留旧个人文字，新字段用目标默认预填，删除字段放orphaned展示；只有显式adapt完成才解除对应任务阻塞。已经开始任务用钉住契约校验响应并保留候选；旧契约候选detail可查，adopt返回`AI_CONTRACT_OBSOLETE`，不自动迁移／生成新候选。系统契约不能由教师编辑。
- accept/reject的目标contract必须与当前个人版本及当前required兼容；不兼容走adapt。无内容／接受拒绝状态变化时不增个人revision，读取／查看不写版本。配置和指导的校验错误只返回字段路径与安全提示，不使用含secret或整段材料的Pydantic原始input／异常文本作为响应。

### 5.4 错误与界面行为

| HTTP／错误码 | 场景与界面动作 |
| --- | --- |
| 422 `VALIDATION_ERROR`、`AI_INPUT_EMPTY`、`AI_INPUT_TOO_LARGE`、`AI_ENDPOINT_INVALID` | 标明字段，保留输入；不建任务、不调用 |
| 404 `AI_NOT_FOUND`、`AI_OPERATION_NOT_FOUND` | 资源不存在／不属该计划；回执未知不判保存失败，不换key重做 |
| 409 `AI_VERSION_CONFLICT`、`PROMPT_VERSION_CONFLICT` | 返回实际版本，保留草稿重读比较；不自动覆盖 |
| 409 `AI_NOT_CONFIGURED`、`CREDENTIAL_UNAVAILABLE`、`PROMPT_ADAPTATION_REQUIRED` | 提供对应设置入口，手工功能可用 |
| 409 `AI_TASK_ACTIVE`、`AI_TASK_STATE_CONFLICT` | 返回已有task或当前execution，重读状态，不另排请求 |
| 409 `AI_SOURCE_CHANGED` | 候选可查，说明变了哪些依赖，只能教师另点重新生成 |
| 409 `AI_TARGET_CHANGED`、`AI_PREVIEW_EXPIRED` | 保留候选编辑，重新对比当前目标并生成token，无需重跑模型；预览请求版本旧时用VERSION_CONFLICT |
| 409 `AI_CONTRACT_OBSOLETE`、`PROMPT_CONTRACT_CHANGED` | 展示契约已变化；旧候选只读，完成对应适配后显式新生成 |
| 409 `AI_REQUEST_CONFLICT`、`AI_RECEIPT_UNVERIFIABLE`、`AI_RETRY_ACK_REQUIRED` | 不执行；同键冲突不能自动换键，风险确认未给就不重发 |
| 503 `AI_EXECUTOR_UNAVAILABLE` | 首次明确拒绝不登记任务、不建立新的未决提交，显示本机AI不可用，手工路径继续；已有旧未决按下文保留原请求 |
| 503 `CREDENTIAL_WRITE_FAILED`、现有本地存储错误 | 保留草稿并说明本机失败；未决写入禁止成功提示、退出放行或联网补偿 |
| 任务reason：`auth_rejected, rate_limited, provider_error, output_invalid, endpoint_blocked, tls_invalid, connection_unavailable, timeout_after_dispatch, user_stop, restart, source_changed` | 状态GET仍200，显示真实原因及服务端allowed_actions；不把未知结果显示成可自动再试 |

前端状态独立为正文save、候选draft、设置draft、AI task、close handshake五部分，复用D1注册／leave协调的一个出口：idle→settle输入→保存正文→检查候选／设置草稿→close任务选择→宿主最终ack。任一步失败／新输入／旧代次响应→stayed，保留各自编辑内容；继续等待→取消本次close。任务轮询正常2秒、隐藏页面5秒，停止组件轮询不取消任务；任务成功只显示查看入口。采用回包仅在planId和editEpoch仍匹配时更新正文基线，否则保留当前输入并提示已保存版本待核对。

W6 G15工程澄清：执行器导入、构造或线程启动失败时，只在确认无遗留worker后降级为AI不可用，手工读取／编辑／保存／重启／原生导出继续；部分启动后退出未确认仍须拒绝启动且保留运行锁。`AI_EXECUTOR_UNAVAILABLE`的首次明确结构化拒绝不产生pending；若已有丢响应的原请求，同键重传返回该错误不能排除原请求仍在并发提交（只读peek回执不是写屏障），必须保留原key/body，最终以回执恢复。普通5xx、丢包及截断成功回包继续保持未知保护。这是已确认C9及幂等边界的工程落实，不新增自动重发或放弃未决操作入口。

## 6. E5：验收矩阵与证据要求

下表是D2整体验收标准。2026-10-18，W1所需G01/G02、G03持久关系子项及G04当前Windows源码/冻结凭据范围已通过，见[W1核查§12](../bootstrap/desktop-d2-w1-review.md#12-最终工程结论w1通过停在w1)；W4已完成G03候选基准链与G10/G11采用范围的源码、合成库及真实本机HTTP核查，见[W4核查§10](../bootstrap/desktop-d2-w4-review.md#10-最终工程结论w4通过停在w4)。其余D2验收按各包记录，不能将W1或W4证据替代最终D2包。每项记录环境、源码／包hash、合成根、用例、实际结果和失败证据；不得用总测试数替代场景覆盖。Windows真实进程及Word人工证据必须关联同一最终包身份。合成根统一用`%TEMP%/kgm-d2-<case>-<UTC>-<random>`，凭据根显式注入其子目录；不得打开原教师体验库执行自动迁移。

| 门槛 | 方式／覆盖 | 明确通过标准 |
| --- | --- | --- |
| G01 新库与旧库升级 | 独立SQLite：全新、0001/0002/0003、含多学期／旧表头／多内容版／WAL提交的D1合成库 | 迁移线性单head；备份含最后WAL提交；内容、表头、当前指针及D1配置版本升级前后相同；空游戏及prompt初始化一次；反复启动不增版 |
| G02 迁移失败与旧版 | 注入建表／种子／提交前故障；未知、多行revision；旧D1实际包开升级副本；占用库 | 失败后原schema与业务逻辑摘要一致、无半迁移；备份保留；未知版本及旧D1拒绝启动且无写API；占用拒绝升级；不自动恢复覆盖原库 |
| G03 关系与基准 | FK、UQ、越权及直接构造损坏合成行 | 跨计划input/execution/candidate/provenance、双活跃任务、伪基准被拒；有效基准可读／人工续存／导出；损坏基准报错不清空；旧null正常 |
| G04 凭据真实API | 当前Windows用户实际DPAPI与ACL；篡改、缺文件、错误AAD、无写权限、DB失败；最终exe重启 | 库／日志／argv／环境／临时文件无合成密钥明文；DPAPI读回一致；任一步失败配置头不推进；损坏只阻AI，重填可恢复；清除撤销密文，历史元数据可读；生产目录未被测试使用 |
| G05 配置／指导版本 | API＋DB；排队期间改配置；已开始再改；同契约默认r2比较时发布r3；required升级 | 未开始用最新、开始后钉旧版；接受r2只接受所选r2字段且r3仍待处理；reject不覆盖个人文字；适配只挡对应AI；保存设置零外部调用；旧契约候选只读 |
| G06 三类输入／输出 | 确定性transport记录请求；严格schema与业务校验 | 拆分六字段可空不补编；适龄只process；其他活动投影无反思／姓名／整段原文，正确日历±7日边界与空配置提示、晨间一集体一自选；手工旧计划年级默认／本次覆盖不改表头 |
| G07 外网连接边界 | transport单测＋受控TLS/socket集成 | 混合DNS、公私地址／IPv6映射、解析后重绑定、redirect、代理环境、坏证书、错误SNI、超大／分块／压缩／畸形HTTP均按规则拒绝；实际连接只用核验IP且保持hostname校验；地址保存不联网 |
| G08 有限重试 | 可控clock与transport，记录真实attempt数及发送计数 | 仅provably-not-sent临时失败最多3次、等待5/30；普通429/5xx、已发送超时、输出错误零自动补发；ack缺失的unknown retry拒绝，显式retry才新generation；旧执行不复活 |
| G09 崩溃窗口 | Windows真实父／子进程，在claim前后、Job分配前后、发送标记提交前后、SEND后、响应到达后、candidate提交后分别强制终止 | 按持久证据恢复paused／unknown／succeeded；重启外部发送计数不增加；父死子进程退出、无残留出站；候选和成功同在或同无；标记后未SEND也保守unknown |
| G10 并发与回执 | 并发提交／采用、同键同体／异体、断开HTTP回包、执行重复回调 | 单任务／单candidate／单内容版；同键读原结果，跨域异体409；无修改不增版；token已耗用仍可回执；回执404不自动换键；密钥指纹不泄露secret |
| G11 来源与采用竞态 | 三类真实本机API；来源／目标／无关字段分别变化；采用提交失败 | 来源变仅查看，目标变重新预览，无关变无需重发；全部选中字段／基准／来源／回执原子保存，未选板块保留；失败保留候选及人工正文；基准必须是原模型过程而非预览改后过程 |
| G12 前端草稿与导航 | 组件＋最终包真实窗口 | 运行可编辑／切日期，任务成功不覆盖输入；正文先保存，候选／设置脏稿阻离开且取消恢复；保存后又输入、采用回包迟到、旧plan响应均不reset新草稿；不新增输入法人工复验要求 |
| G13 退出及休眠 | 真实窗口＋父子进程；继续等待／停止退出、保存失败、DB失败、成功竞争、旧close ack、原生Word保存busy；一次真实睡眠恢复 | 退出前持久分类正确，5秒子进程收口预算内完成或明确拒绝关闭；无孤儿请求进程；旧ack不能关闭新代次；恢复不自动重发，跨120秒期限按发送证据处理；测试clock不能替代真实睡眠案例 |
| G14 Word闭环 | 合成计划：拆分→预览改过程→采用→适龄→教师再改→保存→重启→单日／合并DOCX | 导出只取已保存版本，基准来源不漂移；新增／替换红、纯删不显示、纯移动／格式不红，无基准正常提示；结构验证加相关样本逐页人工查看，保持R18标题／署名／表格非粗体和分页规则 |
| G15 无AI降级 | 空配置／凭据不可用／网络不可用／执行器启动失败 | 读计划、编辑、保存、重启、原生导出仍完整可用；AI失败不长期持DB锁，不阻塞正文保存；没有真实供应商也能完成这项 |
| G16 最终包 | 同源扫描、CPython3.14.7／锁／PyInstaller材料、仓外含空格／中文／%／#路径启动 | child不拉起主窗、不重复迁移、不弹控制台；DPAPI/TLS/Job和冻结资源可用；包包含正确迁移及prompt快照；没有依赖开发机Python；记录实际失败与未覆盖，不宣称干净机器／发行通过 |
| G17 实际兼容 | **另获真实调用授权后**，用户确认可用OpenAI兼容配置与本轮验收范围；只用合成材料。按2026-10-21最新决定，本轮不设计token／费用预算，不设供应商硬预算前置要求 | 三类各至少1次成功，从真实响应到候选／采用／保存闭环；记录配置模型、返回模型、协议、耗时及供应商提供的usage；不伪造缺失usage、不主动制造收费错误／压测。模拟错误验状态，真实服务证兼容，两者分列 |
| G18 教师流程确认 | 工程通过后打开具体样本与窗口，按用户给结果记录 | 三类触发独立、候选编辑采用、旧年级与空游戏配置说明、在途离开／关闭和相关Word可理解可用。与G17/G14关联；不再要求微软拼音或其他输入法逐一验证 |

G07/G09可用专用合成验证入口注入transport、DNS与测试CA；此入口不得在普通应用HTTP请求或环境变量中提供“允许私网／关闭TLS”的开关。至少一组真实子进程调用受控TLS服务验证IPC／超时／终止，另有生产目标策略测试证明普通运行仍拒绝私网；不能拿纯mock函数冒充网络／进程验收。W5/W6专用selftest相位（含只读重启）在任何LocalRuntime构造／prepare前必须要求显式合成data根，缺参数不得落回默认教师目录；要求provider的相位还须核对端口，普通启动及非provider相位不得接受私网解析注入。反例只在spy或独立合成环境验证，不对教师根执行。

D2工程交付需G01–G16对应证据齐备并审阅缺陷关闭；D2完整业务验收还需G17–G18及G14人工页面结果。未拿到真实调用授权时如实标待验，继续完成可独立的合成验证，不把它改成通过。干净机器、Win10、WPS、其他DPI／多显示器、D3历史/WebDAV及发行再现性保留原后续范围。

## 7. OpenCode实施清单（W1–W6限定环境工程通过，人工／真实AI未验）

OpenCode是代码、测试、迁移和构建脚本唯一写入者；Codex负责规格／技术审阅及相应验证。用户授权的W1已由OpenCode完成并经Codex核查通过；用户随后授权的W2已使用Go套餐DeepSeek V4.1 Flash完成并经Codex核查通过，问题已交回修复关闭；W3已使用同一模型完成并经Codex核查通过（W3核查§7）；W4已使用Go套餐DeepSeek V4.1 Flash完成并经Codex核查通过（[W4核查§10](../bootstrap/desktop-d2-w4-review.md#10-最终工程结论w4通过停在w4)），R01–R09关闭；用户本轮授权的W5已使用同一指定模型实现并通过[W5核查§8](../bootstrap/desktop-d2-w5-review.md#8-最终工程结论w5限定源码集成通过)所列限定源码集成工程核查，W6导出／无AI降级／新完整包亦经Codex独立工程核查通过（[W6核查§9](../bootstrap/desktop-d2-w6-review.md#9-最终工程结论w6限定环境工程核查通过)），R01–R09关闭；新Word逐页、真实睡眠、G17–G18仍待验。使用当前分支，不重建仓库、不回退已有未提交改动。

| 顺序／工作包 | 具体交付与文件责任范围 | 进入下一步的证据 |
| --- | --- | --- |
| W1 数据及凭据 | `backend/app/local/` models／schema readiness／凭据模块；`backend/migrations_local/`新增0004；相应`backend/tests/local/`。实现§2–3、回执原语、数据根运行锁和备份入口；原始D1迁移不改 | G01–G04；列实际DDL／约束／升级与回滚结果，证明旧D1拒写；先使用合成secret，无真实密钥 |
| W2 游戏配置及提示词 | 本地config service／schema／routes，三类prompt本地服务和包内bundle；必要时受审查复用纯registry，不能引入旧account／DB服务 | G05、G06相关；默认接受／拒绝／适配竞争，游戏修订与D1全局配置原子更新；同步接口字段给W5 |
| W3 任务及transport | 本地任务／input／execution／attempt服务；`desktop/`启动与受控worker／Job／IPC／关闭接口；标准库网络及测试注入入口 | G07–G09、G13核心真实进程、G15；逐发送窗口证明不会自动重发；冻结spawn最小包先过，不能拖到全UI完成才发现无法收口 |
| W4 候选及采用 | 本地candidate API、`daily_plan_service.py`及共享合法来源验证器；`schemas.py`及候选→业务映射；导出读取同一校验 | G03、G10–G11；先拆分／适龄，再其他活动；原始基准键映射、旧null、幂等与来源过期全部验；手工PATCH仍禁止baseline |
| W5 界面与宿主整合 | `frontend/src/d1/` client／types／editor／leave／App、EditorView／Settings及候选／任务组件；只因D2需要修改`desktop/d1_host_api.py`、启动协调 | G12–G13；设置密钥输入与清除、三类指导、游戏配置、任务状态、独立候选编辑和采用回执；复用已有关闭保护，记录真实窗口交错 |
| W6 导出、打包及验收交接 | `backend/app/local/export_service.py`必要接通；Word纯映射只作确有需要的变更；相关tests及desktop构建／校验脚本 | G14–G16；源码及包同源、无AI降级、人工Word样本。另获授权才G17；工程复审通过再交G18，不能以历史D1包替代新包 |

依赖顺序W1→W2→W3→W4→W5→W6；前端类型可随接口逐包对齐，不把工作包理解为并行派发多个实现者。每包提交审阅材料：实际改动清单、对照本规格的偏差、测试命令／环境／实际结果、未验项及证据路径。若某工程方案在真实Windows包不可行，先带失败证据提出局部替代，不静默删掉保护或扩大产品范围。

源码复用白名单是“可审查候选”，不是直接复制授权：纯registry schema／默认指导、URL规范化、现有内容校验／ID分配／Word映射；必须证明导入链不读取旧`.env`、账号、MySQL或云端锁。新增模块名可按仓库风格确定，但不改变本规格的表语义／接口／流程。

## 8. 设计轮收口及后续入口

- E1–E5已经从待决定事项收敛为明确设计、修改范围和G01–G18验收标准；没有要求用户再答Q1–Q7、指定供应商品牌或现在交密钥。
- 本轮证据为限定源码／依赖声明／现有Contract核对及官方文档核查；未运行D2代码、迁移、DPAPI试验、测试、构建、真实AI或应用窗口。既有业务源码和依赖不在本轮写入范围。
- 文档检查：10份本轮相关文档的232个本地链接目标存在、无尾随空白，受跟踪文档`git diff --check`通过；已核对backend／desktop／frontend及ARCHITECTURE共275个文件，设计前后SHA-256一致。图谱仍不可用这一限制不改写成完整代码审计通过。
- 上述是设计轮当时证据，不代表后来实施结果。后续W1已实施并通过限定环境工程核查，证据另见[W1核查记录](../bootstrap/desktop-d2-w1-review.md)；当前唯一入口为[当前任务](../tasks/current.md)。W2–W4已完成限定环境工程核查；用户本轮授权的W5限定源码集成也已核查通过，见W5核查§8；随后明确授权的W6限定环境工程核查已通过，结果与未验边界见[W6核查§9](../bootstrap/desktop-d2-w6-review.md#9-最终工程结论w6限定环境工程核查通过)。不调用应用真实AI或发布。
