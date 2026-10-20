# D2 W1：Codex独立核查记录

状态：2026-10-18，D2 W1数据迁移与凭据保存已完成，R01–R09均关闭，当前Windows 11合成环境工程核查通过。独立全local286项、补齐测试根后18项迁移及冻结重启验证通过；最终结论见§12。W2–W6、应用真实AI、产品整体验收和发布均未启动／未通过，不以W1替代。

## 1. 授权与审阅基线

- 用户原话：“可以开始实施，请你直接调用opencode，先完成W1数据迁移和凭据保存，完成后由你核查，如有问题，继续调用opencode进行修复，暂不调用真实AI或发布。”
- 规格：[D2工程规格](../specs/desktop-ai-engineering.md)§2–3、配置／回执契约、G01–G04的W1范围；[当前执行任务](../tasks/current.md)。真实候选采用／非空基准完整业务链仍属W4/W6，不把仅建来源表当整条G03通过。
- 分支`codex/desktop-v2-foundation`；大量既有修改／未跟踪D1代码保留。前置快照位于`%TEMP%/kgm-d2-w1-codex-20261017-201057/`：`before/`、`before-files.json`（276个文件SHA-256）、`before-git-status.txt`。
- OpenCode CLI为本机已安装`2.0.32-x64/opencode-cli.exe`，本轮会话`ses_eb6395d7cffehH4KTL8ju5bQ6r`，首轮输出`opencode-run1.jsonl`位于上述证据根。使用当前配置模型，未修改供应商／凭据配置。
- 首轮于22:09报告R01后退出（CLI退出0）。Codex发现§7.1缺口后，串行启动限定R01修复会话`ses_eb5caabceffeVvxGk7T8lSFmaD`，输出`opencode-run2.jsonl`；没有同时运行多个实现者，仍用当前配置模型。
- 第二会话在修复交付前出现provider.internal流式500并自动重试；本机会话元数据显示当前配置为`opencode/nemotron-3.5-super-vl-free`，没有改模型／付费配置。22:33按实际OpenAPI调用session.compact（控制项`msg_14a482dbe001HbkgS9Q2mbYaVT`）并interrupt?resume=true，恢复同会话执行。日志中的aborted/Step interrupted对应此次主动恢复操作，不伪报新的实现或测试失败。
- API随后回报compaction完成并idle outcome=succeeded；run2观察进程因前述中断退出1，不能写为实现成功。Codex随后用`run --session ses_eb5caabceffeVvxGk7T8lSFmaD`继续同一任务，输出`opencode-run3.jsonl`；没有创建并行实现者。
- run3在22:56完成models局部编辑后，至23:04持续无新工具／文本交付；API仍为running，最新反馈留在inbox。Codex通过同会话`interrupt?resume=true`恢复并处理已排队反馈，保留源码与日志；这是执行恢复，不是测试通过，也未据等待时长伪称新的provider错误。
- 恢复后的公共文本／工具状态另记`opencode-api-progress.jsonl`（不记录内部推理）。23:25 API回到idle，最终文字仍是将重写测试，test_d2_schema.py保持22:04版本；run3观察进程退出1。没有R01合格交付。Codex继续串行拆为小批次，先补15表CHECK实际对照持久测试（测试A），防止再次停在整文件重写计划；剩余W1范围不变。
- 验证解释器已读回：`desktop/.venv-d1/Scripts/python.exe`，CPython3.14.7、AMD64、标准Windows环境。未安装依赖。
- codebase-memory项目查询再次返回Transport closed；按已读技能采用限定源码回退，未安装或重建索引，不宣称全仓结构审计通过。

## 2. 本轮核查门槛

核对OpenCode实际交付后，独立检查：迁移线性及冻结种子、D1历史不变、备份含WAL、失败回滚与旧包拒写；复合FK／唯一约束与初版指针；运行锁和资源释放；DPAPI／ACL／路径与句柄；密文、AAD、原子保存、密钥损坏／重填／清除；配置版本／无变化／幂等回执／密钥不泄漏；不配置AI时D1回归仍可用。

OpenCode交付见[W1实施结果](desktop-d2-w1-result.md)，Codex最终结论见本文§12。其自测声称、Codex复跑、真实Windows API、冻结探针及最终全应用包分别记录，不能互相替代。发现问题在本文件列出具体源码／反例，并交同一OpenCode会话定点修复；不由Codex直接写实现或测试。

## 3. 保留边界

原D1教师体验库、exports及R18已验包保留；自动验证只用独立合成根。微软拼音不复验或穷举输入法。本轮不联网测试供应商、不读取真实.env／密钥、不commit／push／发布；W1之后不自动继续W2。

## 4. 实施过程中的独立观察（交付后重新核对）

2026-10-17首轮实现仍进行中，以下不是最终交付结论，也未由Codex改代码：

- 从实际`LocalAICredential`模型提取`active_has_material` CHECK，在独立内存SQLite表执行active＋nonce=NULL＋非null ciphertext，插入成功（count=1）。SQL CHECK接受NULL结果，当前表达式不能证明active nonce必有12字节。交付时须核对模型和迁移均显式排除NULL，并覆盖key_id及tag长度。
- 从实际`LocalAIExecution.__table__.foreign_keys`读回仅任务四列和profile；此时未见配置版本、个人指导及bundle复合FK。后续须核对物理迁移和ORM一致，不能只在W3业务服务依赖检查。
- OpenCode初次模型语法检查出现IndentationError，已自行修正后继续迁移；首个失败及修复输出保留在run1日志，不把中间失败隐藏成首跑全通过。
- 对当前凭据初稿执行仅内存的真实DPAPI往返（合成32字节，未写凭据目录）：`_dpapi_protect`在`bytes(data_out.pbData[:...])`失败，ValueError“bytes must be in range(0, 256)”，对应签名为`POINTER(c_byte)`。导入成功不代表API往返可用，须交付后重验。
- 当前`_set_restricted_dacl`向SetNamedSecurityInfoW传DACL标志及null pDacl，且先mkdir／mkstemp再调用；尚未形成创建时受保护ACL，也没有读取时owner／ACL核验。Microsoft说明[null DACL会授予所有用户完全访问](https://learn.microsoft.com/en-us/windows/win32/secauthz/null-dacls-and-empty-dacls)。初稿不能据函数名或注释认定权限限制已实现；本轮没有对真实凭据目录运行此函数。
- 配置服务初稿先检查expected版本、没有先查持久回执；no-op只比较“是否有secret”而未比较内容，会把同地址／模型下换密钥误判为无变化。更新分支又复用并修改旧credential，使历史配置引用的密文被覆盖。`clear_secret`仅清active，遗留retired密文；无变化没有写回执。最终须用相同／不同secret、同request_id重传、替换及清除历史等反例复核。
- 配置初稿含secret请求实际写sha256类型指纹，且只记has_secret；凭据模块的derive_hmac_key从secret本身派生。两者均不满足从随机主密钥派生独立HMAC键并验证完整规范请求的规格。GET初稿只读主密钥，未解密验证AES-GCM密文／AAD；损坏ciphertext可能仍报ready。
- 运行锁初稿使用CREATE_NEW且正常关闭才删除文件，进程被终止留下文件后可能永久拒绝启动；应由OS句柄锁判占用，而不是文件存在。backup_before_migration虽已定义，prepare尚未调用；冷升级的数据库占用探测及固定独立credential_root尚未接齐。这些属于在写初稿，须等OpenCode首轮交付后按最终文件确认。

独立运行锁反例：在`%TEMP%/kgm-d2-w1-review-stale-lock-_lvhwxyp`只创建空`.app-runtime.lock`，无持有句柄的进程；调用实际`LocalRuntime.prepare()`得到`LOCAL_APP_ALREADY_RUNNING`。测试未触及真实数据根。

## 5. 修复核对清单（进行中核查已派发同一会话）

以下是首轮中途源码所见的具体核查项。20:47附近又观察到OpenCode为适配旧跨进程测试，将运行锁改为只在迁移期间持有，与已确认规格冲突；Codex通过本机CLI实际OpenAPI的session.prompt（delivery=steer）向同一会话即时派发本清单，要求在当前W1内纠正，不并行启动另一个实现者。交付后Codex逐项复核，不据初稿观察替代最终结论。

| 编号 | 观察及要求 | 必要反例／证据 |
| --- | --- | --- |
| R01 数据关系与种子 | 0004与ORM一致：补执行的配置／个人指导／bundle复合FK、拒绝指导revision的bundle FK、正整数版本和合法枚举／null组合、所有新表created_at及所需索引。active凭据明确nonce非null且12字节、key_id有效、ciphertext含tag；不能依赖SQL CHECK的NULL。三类真实默认bundle冻结在迁移中；旧档案升级与新档案初始化一次性创建AI状态、个人指导头和空游戏revision，不改D1配置版。 | 用实际Alembic库（不能只create_all）拒绝跨计划关系、非法版本／状态／空nonce、双活跃任务和不存在的被钉版本。升级／新初始化数据等价、反复启动不增版。 |
| R02 冷迁移与备份 | 备份函数必须接在已知非空旧库升级前，Windows独占打开探测库仍被旧进程占用则拒绝；检查WAL/SHM相关路径。backup目标带随机id防同秒覆盖，核验revision及完整性／FK，关闭后hash／manifest，备份失败不升级；升级后核对D1逻辑摘要。现有显式事务必须覆盖种子。 | 0001/2/3含历史与WAL库、占用库；建表／种子／提交前故障回滚；摘要和版本不变、备份保留；实际旧D1包拒绝升级副本且不开写API。 |
| R03 运行锁与路径 | 改为OS独占句柄决定占用，崩溃遗留文件可重开；不用CREATE_NEW的存在性当锁。释放只针对本runtime拥有的句柄，不误删别人锁。prepare幂等；dispose和失败路径释放。受管DB路径拒绝重解析／硬链接别名，检查在resolve吞掉重解析信息之前，句柄不继承。 | 两个真实进程同根第二个拒绝、不同根可运行；kill持有者后新进程可启动；未prepare实例dispose不影响持有者；junction/hardlink别名拒绝。 |
| R04 Windows加密及ACL | 修正DPAPI返回带符号byte问题，PromptStruct=null，准确绑定所有64位API。OpenProcessToken/GetTokenInformation来自Advapi32。SDDL转换成实际SECURITY_ATTRIBUTES，在CreateDirectoryW/CreateFileW创建时传入，受保护DACL仅当前SID和SYSTEM。读取通过句柄检查owner/DACL/ACE/reparse/hardlink，不能设置NULL DACL或先落盘后收窄。 | 真DPAPI随机32字节往返；真实创建后独立读取ACL验证，错误ACL／owner／缺失／损坏均拒绝。GET不创建目录、不修ACL、不新建密钥。不能以mock DPAPI/ACL通过代替实际API证据。 |
| R05 文件原子性及密钥生命周期 | 默认root固定LOCALAPPDATA/KindergartenManager/credentials，不能跟随可迁移业务库；测试显式注入。严格验证database_uuid/key_id，祖先路径及文件句柄，限制blob长度，解保护后必须32字节。新secret永远新key_id/credential，不覆写旧文件；同目录受限临时文件、完整写/flush、从未使用目标原子改名、读回解密并比较原key，之后短DB事务提交。GET解密验证AES-GCM及AAD才ready。 | 文件写／flush／rename／读回／DB提交失败均不推进头；错误AAD/ciphertext/缺key仍可手工功能；显式重填新key可恢复，无需读旧key。替换后只为真实活跃执行保留旧密文；本轮无执行则清除退休材料；clear撤销所有历史nonce/ciphertext。 |
| R06 配置原子性与no-op | 省略secret保留，显式null/空/空白拒绝；同secret需实际安全比较，不能只比有无。不同secret必须新credential并推进一版；旧配置引用不可变。状态行重读必须规避SQLAlchemy identity-map缓存（CAS或refresh等），避免并发旧状态通过。文件准备不在长写事务内，最终短事务重新检查回执和expected。 | 相同地址/模型下换secret、无secret改model、同secret无变化、当前密文损坏后重填；双连接同expected只一个成功。无变化仍有回执。 |
| R07 幂等与HMAC | 所有变更先查(profile,request_id)回执再查版本；指纹涵盖操作域、expected及规范完整请求，含secret用随机master key派生独立HMAC键，禁止secret派生或仅has_secret。回执存脱敏原始结果，重复请求直接返回原结果；同键异体/异域409；旧key不可读409 AI_RECEIPT_UNVERIFIABLE附脱敏回执，GET仍读。clear不删回执所需主密钥文件。 | 成功响应丢失、旧expected重传、相同／不同secret重传、跨PATCH/clear冲突；key损坏后原请求查询与重发；no-op／clear已空回执；数据库/日志/异常不含secret或普通secret摘要。 |
| R08 最小API契约 | PATCH的protocol必须固定字面值；base_url/model必填非空且限长，URL做纯本地HTTPS/安全语法校验，不联网；secret区分省略/null，request_id客户端UUID必填。clear不得服务端随机生成request_id；GET未知回执404 AI_OPERATION_NOT_FOUND；版本冲突AI_VERSION_CONFLICT；字段错误不泄露输入。 | 实际本机HTTP验证session/Host/Origin/no-store、bool/浮点版本/额外字段/错误UUID/空地址/错误协议/URL拒绝、422脱敏和所有错误码；操作不联网。 |
| R09 证据与回归 | W1测试必须覆盖上述失败路径，源码结果如实记录首跑失败和修复，不降低断言迎合错误实现。所有测试明确合成credential_root，不生产目录。新增运行锁后调整既有测试生命周期，不能绕过锁当并发证明。补D1相关回归及W1冻结探针，最终全应用D2包继续留W6。 | 记录具体命令、数量、退出码、证据根、关键文件hash；首个迁移测试错误导入sqlite_connect已见run1日志。前端/依赖/旧迁移/原教师库/原D1包不被顺手改动。 |

本清单不要求实现W2提示词编辑、W3执行器、W4采用或W5界面；仅完成W1已授权数据、凭据及其最小可验证接口。G03完整业务链、G16最终D2包、真实AI与人工产品验收继续保留后续边界。

## 6. 独立执行证据（逐项，不代表W1整体通过）

2026-10-17，Codex通过当前0004迁移建立独立空合成库，正常dispose后运行保留的R18实际exe：`KGNext-D1Verify.exe --selftest --data <synthetic>/data --out <synthetic>/old-d1-result.json`。未进入窗口／HTTP服务启动步骤，退出码2，`startup_error`含`LOCAL_DB_VERSION_UNSUPPORTED`，`checks={}`、`ok=false`（这是预期的拒绝启动结果）。exe SHA-256仍为`c6dc19283a24d00a740f2ecbed2cc7159e951f02a37f00636b294b7670369930`。

证据根`%TEMP%/kgm-d2-w1-review-old-d1-35a_ni71`，`codex-evidence.json`记录包身份、返回结果及DB前后SHA-256，均为`c906c387690b5e7f1f0f50f92155c794b29f061c3bfbcf8b1a0f3c868c10cfbb`。本项仅证明G02中的实际旧包拒写0004库；不替代含D1历史/WAL的升级、故障回滚或W1新包验证。

后续过程复核：`%TEMP%/kgm-d2-w1-review-lock-fixed-oqdc8msn`，改为OPEN_ALWAYS后的遗留锁重开、同进程第二runtime拒绝、未prepare实例dispose不影响持有者、正常dispose后重启均通过；尚不代表跨进程kill案例通过。另在`%TEMP%/kgm-d2-w1-review-alias-2fd2ffa6bd5e421e820d4e4babce4d25`创建真实NTFS junction→real，构造LocalRuntime仍接受；check_targets循环再次resolve后才查属性导致检测失效，反例已通过同一会话steer派回修复。

真实跨进程锁追加证据：`%TEMP%/kgm-d2-w1-review-process-lock-hfdyl8y9/codex-evidence.json`。独立持有进程PID2512创建runtime并持锁；第二真实Python进程prepare返回`LOCAL_APP_ALREADY_RUNNING`（诊断退出码17）；Codex强制终止自己创建的持有进程后，第三进程prepare成功（退出码0、ACQUIRED）。当时runtime.py SHA-256为`0f46f8e3825baebf07bb6f48a4926b52461cc872b0bf8a33827aec942eb27dc3`。此项关闭当时版本的持有期互斥／进程死亡后锁恢复反例；路径别名、占用库和迁移保护仍须分别补验。

21:04凭据重写后，Codex对实际DPAPI做3次随机32字节纯内存往返，3/3相等；返回字节问题已修，但PromptStruct参数、ACL、文件原子保存和整条配置服务仍未通过。OpenCode首次实际保存因credential_root不存在而创建目录失败；该轮源码另有mkstemp预建文件后CREATE_NEW必失败及fd泄漏、只检查DACL存在而未检查保护位/ACE、NULL指针误判等问题，已通过同一会话再次定点反馈。其首个命令使用字面合成secret进入了命令参数／运行日志，该命令不能作为“argv／日志无明文”证明；后续明确要求在进程内随机生成并仅输出布尔结果，不删除或掩盖首次失败证据。

凭据正向文件链路追加通过：`%TEMP%/kgm-d2-w1-review-credential-55vn7e6o/codex-evidence.json`，凭据模块SHA-256 `8118eaa5a741be00cf03a563ab1fab3bba63f001cbd0c25849388d587af2797a`。Codex进程内随机生成secret和标识，通过实际save_master_key→load_master_key→AES-GCM encrypt/decrypt断言，未输出任何材料值。另用独立PowerShell Get-Acl读取credential_root、database_uuid目录和dpapi文件，三者均owner为当前SID、AreAccessRulesProtected=true、恰两条非继承Allow ACE且仅当前用户/SYSTEM完全控制；记录在同根`codex-acl.json`。本项是正向文件／ACL证据，尚不替代坏ACL／坏blob／并发／DB失败、配置服务回执及冻结exe证明。

Windows接口核对依据：[GetSecurityDescriptorControl](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-getsecuritydescriptorcontrol)、[控制位WORD类型及保护位](https://learn.microsoft.com/en-us/windows/win32/secauthz/security-descriptor-control)、[DACL存在与NULL区别](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-getsecuritydescriptordacl)。

额外Everyone读取ACE反例：在上述合成key文件上用icacls精确`/grant *S-1-1-0:(R)`并以Get-Acl确认规则已存在后，实际load_master_key拒绝，`LOCAL_STORAGE_ERROR`，`codex-acl-negative.json`记录通过；当时凭据模块hash为`5f7c3d922079c195510b22b4dec9800f643da4863e05f7dfe4fb6db7d8710591`。首次夹具尝试用PowerShell Set-Acl报缺SeSecurityPrivilege、没有成功注入规则，故当次“接受”不能算产品缺陷，也不计负例结果；改用icacls且先验证注入成功后才得到有效反例。合成key文件当前刻意保留坏ACL供证据，未改生产目录。

配置服务过程反例：Codex在真实0004合成库手工插入最小profile/state以独立触达服务（不算初始化验收）。`%TEMP%/kgm-d2-w1-review-config-noop-6dy5o4ns/codex-evidence.json`：无密钥首次v1、同值no-op仍v1、不同内容同键409。`%TEMP%/kgm-d2-w1-review-config-secret-gzvohbh8/codex-evidence.json`（service hash `2626c67d0123b87bded913ede6c375eeaf09a9a8f0a7d52cd1c1c10edeabfb3c`）：随机secret首次v1 ready=true，同secret/no-op仍v1，省略secret换model到v2且ready，更换secret到v3，clear到v4且所有历史nonce/cipher为null、两主密钥文件保留。仍失败四项：完全相同原请求重传误409；已空clear到v5（应v4）；clear重传丢地址/模型；clear使用原PATCH的request_id错误返回v1（应跨域409）。已按实际反例派回同一OpenCode，尚不关闭R06/R07。

后续配置复核：`%TEMP%/kgm-d2-w1-review-config-fixed-9tpc31vc/codex-evidence.json`，service SHA `cfee06080c938e2b9fc2f75c549ec666113ae5449c96594316bcc0002d4d5df1`。相同PATCH重传、不同secret／跨域同键冲突、已空clear不增版、旧HMAC主密钥损坏后重传报`AI_RECEIPT_UNVERIFIABLE`且GET回执仍可读均通过；仍失败：初始未配置时clear报IntegrityError；成功clear相同request_id／原expected重传误报冲突。已交同一会话修复，未关闭R06/R07。

路径追加反例：`%TEMP%/kgm-d2-w1-review-paths-5cde39e48f97455f9b86f9fbeab8a99d/codex-evidence.json`。实际NTFS junction上，显式data_dir已拒绝；环境变量KGM_LOCAL_DATA_DIR及注入credential_root仍被接受。hardlinked_lock的prepare被当时正在改写的迁移错误提前终止，不能计为路径正确拒绝；后在`%TEMP%/kgm-d2-w1-review-directory-acl-5j_rfa9c/codex-evidence.json`只调用实际锁获取，硬链接锁文件被接受，确认仍缺检查。

目录ACL追加反例：上述directory-acl合成根，创建真实DPAPI文件后用icacls给credential_root添加Everyone读取ACE（退出0），load_master_key仍成功；现只验证文件ACL，缺受管目录读取验证。credentials SHA `5f7c3d922079c195510b22b4dec9800f643da4863e05f7dfe4fb6db7d8710591`。未修改生产目录权限，R03/R04/R05仍开。

接口输入预检查：`%TEMP%/kgm-d2-w1-review-validation-j42vsf4b/codex-evidence.json`。当前Pydantic请求模型接受显式secret=null、错误protocol、坏UUID、base_url=null、空白model；额外字段能拒绝。服务URL校验仍接受IPv6回环、带端口的127.0.0.1、99999端口、空格主机及嵌套补全端点。此证据是schema／纯本地函数检查，不冒充真实HTTP结果；UUID等可能另在服务拒绝，完整HTTP须R08修复后复跑。源码另见clear API仍使用服务端随机request_id和重复注册的原config operation路由。

配置回执进一步核对：上述config-fixed库第二次“同secret/no-op”回执实际`fingerprint_kind=sha256`且key_id非空；源码复用同credential时没有载入master_key，落入含secret的普通SHA路径。数值no-op通过不代表秘密指纹合格。回执result当前仅保存version/status/changed等少数字段，PATCH重放会重新读取旧配置／已清除credential计算ready/has_secret，不能保证后续替换或clear后仍返回原提交结果；应保存完整脱敏原结果并按回执返回。最终短事务仍先检查expected后查receipt，两个并发同键同体请求可能误版本冲突。替换旧credential还只是retired而未清除无活跃执行需要的材料。以上在R06/R07后续修复及持久反例测试中一并关闭。

迁移初步可运行证据：`%TEMP%/kgm-d2-w1-review-schema-ey4sq1f0/codex-evidence.json`，0004 SHA `260e7c06ae4445adfc091703421d4be6ee97a3e128d9562d413c47e84881a849`。实际新库prepare成功、15个新表、三类bundle的contract/default均1、FK检查为空，ORM／物理表列和FK集合一致。但execution及两个game/personal头均缺created_at；同根`codex-constraints.json`实际插入证明bundle contract_version接受1.5及文本abc，default_revision接受0及1.5。R01仍未通过，已反馈补严格整数CHECK与正常初始化／旧库种子持久测试。

R01冻结输入复核：重写后的OTHER输入仍只给calendar_state_ref／class_game_config_ref字符串，daily_plan_snapshot仍裸object；不能表达D2已确认实际游戏配置／日历业务值，也不能限制反思／姓名／整段原文或组ID混入。已要求按产品§9.1及工程§2.2补严格嵌套投影、实际配置内容、合法空游戏初版；修正morning_talk指导“空字符串”与object/null schema不一致，保留缺板块不可当清空的规则。只修W1冻结种子，不启动W2服务或W3执行器。

凭据底层故障分支：`%TEMP%/kgm-d2-w1-review-credential-faults-ey6xwgoa/codex-evidence.json`，credentials SHA仍`5f7c3d922079c195510b22b4dec9800f643da4863e05f7dfe4fb6db7d8710591`。实际DPAPI/AES随机往返通过；错误profile/credential AAD、篡改cipher、路径逃逸key_id、缺文件、坏DPAPI、超1MiB文件、可解密但主密钥长度16字节、真实硬链接文件均拒绝。随机秘密只在进程内，未打印值。本项只证明底层拒绝，路径错误当前为LocalValidationError，配置GET是否正确降级ready=false仍待R05/R08；不替代目录ACL、同句柄属性核验、写故障及DB提交原子性。

凭据写故障注入：`%TEMP%/kgm-d2-w1-review-credential-write-faults-13w21dso/codex-evidence.json`，同上credentials SHA。只在独立进程mock单个WriteFile／FlushFileBuffers／MoveFileExW返回失败，实际其他DPAPI/ACL路径照常执行；三项均报LOCAL_STORAGE_ERROR，目标不存在且临时文件0。解保护读回注入错误长度也拒绝，留下无引用的DPAPI文件；旧key_id重复保存拒绝，原blob SHA未变。这是底层故障注入，不是实际磁盘故障或配置DB事务原子性通过。

真实本机HTTP证据：`%TEMP%/kgm-d2-w1-review-http-22gsd0pl/codex-evidence.json`。实际Uvicorn＋HTTPConnection，正常首次initialize返回201，运行时和凭据根均独立注入。通过：无session 401、错Host/Origin 403、UUID/布尔版本422、no-store、随机secret保存ready=true及同PATCH重传、响应／捕获日志不含随机secret。失败：未初始化GET错误200（契约409）；初始空clear仍503 LOCAL_STORAGE_ERROR；错误protocol、secret=null、base_url=null、空白model和IPv6回环URL仍200；clear成功后按客户端request_id查回执404，相同clear重传409 VERSION_CONFLICT；普通版本冲突也仍用VERSION_CONFLICT而非AI_VERSION_CONFLICT。记录API/schema/service SHA（service `9d2ff73750ba41c1ccaca4fbfe2c1c6f6ed0f142be5d562effd23198f79cce41`）。未调用供应商；R06–R08后续必须以真实HTTP反例修复，不能拿schema单测或正常保存通过替代。

配置事务及恢复真实HTTP追加：`%TEMP%/kgm-d2-w1-review-config-faults-qtdlg6ar/codex-evidence.json`，service／credentials SHA分别为`9d2ff73750ba41c1ccaca4fbfe2c1c6f6ed0f142be5d562effd23198f79cce41`／`5f7c3d922079c195510b22b4dec9800f643da4863e05f7dfe4fb6db7d8710591`。首次v1 ready；在INSERT config时注入sqlite磁盘错误实际触发，HTTP503 LOCAL_STORAGE_ERROR，head/credential数不变，新增DPAPI孤立文件不被引用（共2文件）。损坏当前blob后GET200 ready=false/CREDENTIAL_UNAVAILABLE，明确重填成功v2 ready。仍失败：对当前key创建真实硬链接后GET和新secret重填都422 VALIDATION_ERROR，不能按已确认规则降级／另建新key恢复；head保持v2。后续须修凭据路径异常分类与读取/重填边界，不能仅以底层能拒绝硬链接认为恢复流程通过。

真实HTTP并发反例：`%TEMP%/kgm-d2-w1-review-config-races-jqb7mdf0/codex-evidence.json`，service SHA仍`9d2ff73750ba41c1ccaca4fbfe2c1c6f6ed0f142be5d562effd23198f79cce41`。在真实save_master_key完成后加测试Barrier，确认两个请求都已过首次版本检查，再竞争最终短事务。不同request_id／secret：200＋409，只有1配置版/1回执，单胜者通过（错误码仍须改AI_VERSION_CONFLICT）。同request_id同完整请求：也200＋409 VERSION_CONFLICT，而应两者200读同一回执；确认最终事务先查版本后查回执的竞态真实存在，R07仍开。

## 7. 当前修复顺序

### 7.1 R01首轮交付复核：未通过

OpenCode于22:09报告R01完成。Codex独立执行`cd backend; ../desktop/.venv-d1/Scripts/python.exe -m unittest tests.local.test_d2_schema tests.local.test_migrations -v`：26项通过，退出0（8新增＋18原迁移）。但这不能关闭R01：

- `test_fake_execution_config_rejected`缺created_at、task/input等有效前置引用，并用可能不合法的pending execution状态，错误可先由NOT NULL/CHECK触发，不证明目标config FK；跨计划测试用全不存在的ID，不证明两组有效数据间禁止混用。STRICT_INT_COLUMNS定义未用于穷举，旧0001/0002、种子重复和模型物理CHECK一致性仍未覆盖。
- Codex另在`%TEMP%/kgm-d2-w1-review-relations-aknzk7iy/codex-evidence.json`正常初始化（D1 config_version仍1）、建立两份计划、写无secret配置，再成功提交两套完整input/task/execution/candidate/provenance关系。以此为合法基线，跨content/input/execution/plan/candidate、不存在的config/personal/bundle、rejected bundle共9个变体全部返回SQLITE_CONSTRAINT_FOREIGNKEY，回滚后FKcheck为空。个人指导与bundle一致，credential_root未创建。此为物理关系通过，不是候选业务链验收。
- 同根`codex-enums.json`：invalid_task、invalid_grade、invalid task status、active空key_id、hmac指纹无key_id均被实际数据库接受；invalid execution state已被CHECK拒绝。
- models.py没有迁移新增的typeof严格整数CHECK，元数据与物理约束不一致。
- OTHER冻结daily_plan_snapshot仍含raw_lesson_plan且adopted_content为裸object；违背已确认去原文/姓名/反思/组ID投影。晨间最多一个collective/free_choice也未约束。不能用新迁移已跑通替代默认契约合格。
- OpenCode另跑initialize原13项，2项跨进程测试受全生命周期运行锁拒绝；这是应调整测试执行方式的已知工作，不能记整体回归通过或通过绕开锁来修。留R09处理。

关系证据内记录模型／迁移／初始化／测试文件SHA。此次Codex仍未写实现或测试；后续交回OpenCode定点修复上述R01缺口，修复通过后继续R02–R09。

旧revision逐版独立验证补充通过：`%TEMP%/kgm-d2-w1-review-old-revisions-bpma_t_e/codex-evidence.json`，0004 SHA仍`1db83408ff46217da3652e7b33b8dd8ce1f9416d93555f453b637c6002143f16`。分别真实Alembic建立0001/0002/0003，装入两学期、两份计划／历史表头、四个正文版本；按升级前已有D1表／列逐行比较，升级后3/3全部一致。0003配置v4保持v4，0001/2按既有0003迁移取得初版1；重启后数据库UUID与3个人指导头/1游戏头/1AI状态数量不变，FKcheck为空。此项补足历史数据与重启证据，未消除§7.1枚举／CHECK／冻结输入缺口，也不替代冷升级故障回滚。

R02独立WAL备份证据（待其子阶段修复）：`%TEMP%/kgm-d2-w1-review-backup-qhoq4gpt/codex-evidence.json`。真实Alembic 0001建库并装历史夹具，再升级0003；独立Python进程写WAL并os._exit，备份前wal存在且4152字节。实际backup_before_migration备份含最后提交，备份SHA与清单相符，库内revision确为0003；但清单version错误硬编码0004。此次只调用实际备份入口，没有执行正在改写的0004升级；源revision验证与升级前后D1摘要仍待R02。首次夹具误在0003插入0001允许的null term指针而失败，修为真实0001先装数据再升0003；该夹具错误不计产品失败。

同根后续增加真实占用检测：独立Python进程打开并读取该0003库后保持连接，父进程实际check_database_not_occupied拒绝并返回LOCAL_DB_OCCUPIED；测试子进程正常释放后结束，没有杀旧应用。

迁移故障回滚独立通过：`%TEMP%/kgm-d2-w1-review-rollback-fnst3o4p/codex-evidence.json`。取已关闭且校验过的真实0003备份复制到3个独立根，经实际runtime.prepare/Alembic分别在CREATE TABLE local_ai_credentials、INSERT local_prompt_bundles、COMMIT之前注入异常；逐项确认注入确实触发。3/3均LOCAL_DB_MIGRATION_FAILED，旧sqlite_master结构、版本表及全部旧表行完全一致，备份保留，锁可重新取得。migration SHA `1db83408ff46217da3652e7b33b8dd8ce1f9416d93555f453b637c6002143f16`，runtime SHA `0f46f8e3825baebf07bb6f48a4926b52461cc872b0bf8a33827aec942eb27dc3`；仍需修复备份revision/清单及运行时D1摘要检查，不能据此关闭整个R02。

当前OpenCode执行子阶段仍为R01：按§7.1定点修复后由Codex复核；这一子阶段通过不能称W1整体通过。随后继续R02/R03冷升级／路径与锁、R04/R05凭据文件与故障、R06–R08配置回执／接口，再补R09回归及必要冻结探针。清单中的未闭项全部仍属本次已授权W1，不需要用户重复批准。

R01继续修复时发现冻结OTHER输出仍允许显式null、零板块和不限数量晨间组，与工程§5.3不符。已通过同会话steer明确：输入沿D1去ID快照与空板块；输出至少一个板块、可选字段可省略但不可显式null，晨间一旦提供恰好一collective＋一free_choice、每组恰好一game。current.md原“最多”描述已澄清为输入规则，不覆盖已确认的D2输出规则；没有新增产品要求。需用实际schema正反例验证后关闭。

### 7.2 R09提前回归：测试生命周期与新head尚未适配

R01继续修改中的CHECK逐表对照：`%TEMP%/kgm-d2-w1-review-check-parity-3r3gb0u1/codex-evidence.json`，实际Alembic新库15表，比较ORM CheckConstraint与sqlite反射结果（忽略空白／大小写）。仍4表差异：attempts ORM attempt_no缺typeof；candidates ORM缺contract_version/schema_version检查；inputs ORM缺input_schema_version检查；operations的hmac/key_id组合只在ORM新增、迁移缺失。已交回同会话，不是最终交付判定。模型SHA `07974e4dec743d96fb034dd9a4f67f5d16bfb1c4dad572afdbfa7a825b0eb6fd`，迁移SHA `45f99f8bc852b8a8e3735c76cea240a0edd8eacc4f228633e9f0aa710bd923e5`。

上述4处修复后独立复测通过：`%TEMP%/kgm-d2-w1-review-check-parity-fixed-ldix3ik4/codex-evidence.json`，15表CHECK差异为空；模型SHA `cd6ed16e339d09d8572e707f8dbb2ebe5d4ce90018e8a9859d75df5281805925`，迁移SHA `737cc03c313a507de3dc0cce7231cbc2a7b4b15b80f56ebe48ebd7c21208feb8`。冻结OTHER输出仍错误包含group_activity，晨间仅限总数2而未限制每种恰一；输入套用输出非空限制，且指导变动后需重查新档案副本一致性。已继续派回，未关闭整个R01。

默认指导改动后的正常首次初始化复核通过：`%TEMP%/kgm-d2-w1-review-seed-equality-irz7b3v8/codex-evidence.json`，首次created=true、相同请求再次created=false；3类个人指导全部与各自bundle相同，空游戏为`{locations:[],game_scope:null,guidance:null}`；重复初始化后AI state／个人版本／个人头／游戏版本／游戏头数量为1／3／3／1／1，凭据根未创建。profile_service SHA `f8ebd2ce2835af0463091efc66e170a07dddb8361ff2cbca7ca95b5d0cb89848`，迁移SHA `d495082025b5b620436075afc2b066bd40bf030940db48f5b33f1a27a3d67cec`。此项只补当前默认种子一致性，不替代旧revision及持久反例测试。

Codex在backend执行`../desktop/.venv-d1/Scripts/python.exe -m unittest tests.local.test_transactions tests.local.test_restart tests.local.test_paths tests.local.test_guards tests.local.test_export tests.local.test_daily_plans tests.local.test_config tests.local.test_concurrency tests.local.test_calendar_dates -v`，103项、356.685秒，退出1，报告13 failures／5 errors（含路径subTest）。完整输出`%TEMP%/kgm-d2-w1-codex-20261017-201057/codex-d1-regression-before-r09.txt`。这是R01仍修改期间的前置回归，不作为最终源码验收。

- 已跑的普通保存、配置预览／应用、多学期、单日／范围／合并导出及R18格式等用例通过；不能据此声称全套通过。
- `test_paths._copy_backend_resources`仍把0003当head改成sentinel，令新0004的down_revision断链。后续应从真实head定位复制树对应文件并只改复制文件，继续证明实际消费复制资源；不能修改原迁移或取消sentinel断言。
- 路径白名单未列新增的持久`.app-runtime.lock`，引发3个subTest失败；应精确纳入运行锁，不放宽为允许任意邻接文件。
- 两连接／跨进程并发、读快照、写锁及日历重启部分在第一个runtime仍持锁时又prepare第二个，同根被`LOCAL_APP_ALREADY_RUNNING`拒绝，导致等待flag超时。应改为单runtime所有者下的独立事务／并发HTTP或明确受管worker，同时另留真实双进程拒绝／崩溃锁释放测试；不得缩短／绕过产品运行锁以迁就旧测试。
- 失败清理出现unclosed pipe／subprocess ResourceWarning；R09须补失败路径清理。本轮结束后按worker命令识别检查，无残留`tests.local.worker`进程，未终止其他应用。

范围复核：`%TEMP%/kgm-d2-w1-codex-20261017-201057/codex-scope-check-2324.json`重新比较开工前276个源码文件哈希，无文件缺失；其中变化仅local/api、errors、models、profile_service、runtime、schemas及test_migrations七个既有文件。新增D2文件另计，文档由Codex维护。该快照覆盖的旧迁移、前端及依赖文件未变；D1实际exe仍为`c6dc19283a24d00a740f2ecbed2cc7159e951f02a37f00636b294b7670369930`，分支仍`codex/desktop-v2-foundation`。这不是最终交付后的范围检查，后续仍须核对。

### 7.3 R01持久测试分批核查

测试A会话`ses_eb586d02cffesI2hS4VpODglZq`，输出`opencode-run4.jsonl`，仍为既有nemotron免费模型。只在test_d2_schema.py增加CHECK规范化辅助及`test_orm_metadata_matches_reflected_checks_table_by_table`，真实prepare/Alembic＋反射15表，显式独立credential_root，逐表比较条件，保留typeof等语义。OpenCode曾在错误cwd运行临时反射脚本报找不到文件，改用绝对路径后运行；不是产品失败。

OpenCode自测模块9项通过；Codex独立执行`cd backend; ../desktop/.venv-d1/Scripts/python.exe -m unittest tests.local.test_d2_schema -v`，9项、0.928秒，退出0。测试文件SHA `dc2feb53805baf39b02b6c02a2224445cde228ca5ffcfd4a666e9172eb26be2d`。仅关闭测试A；旧跨计划／伪配置反例仍有错误前置条件，不能据9项通过关闭整个R01。下一批B定点修正这两个反例及合法关系基线，然后继续其余W1。

测试B已串行派给同一会话，日志`opencode-run5.jsonl`。B期间仅阅读冻结schema所见、留下一批处理：OTHER输出现只含正确四板块且minProperties=1，但晨间采用prefixItems固定“collective在前/free_choice在后”，超出仅按group_kind各一组的原契约；应在保留数组结构下按组别计数、允许两种排列。输入morning仍未限制每种最多一组；D1合法空内容在其他输入板块也应兼容（D1允许空games/空name、nullable/省略的group_activity及文字），不能直接套用输出非空限制。后续C须对照daily_plan_content实际合法形状验证冻结输入，保留去ID/无反思原文等限制；B不受此观察干扰，不在其运行中另派源码改动。

测试B在修正参数数量、重复bundle、execution缺created_at等夹具错误后，自测9项通过。Codex再次独立运行同模块：9项、0.928秒、退出0；test_d2_schema.py SHA `1196553f59f60abed2ff752726c141d7d76a2106ab01dfdcce6cb56231562d0e`。当前两个反例已能先提交各自合法基线，再捕获不存在content引用的立即FK及不存在config引用的COMMIT延迟FK，较旧反例有实质改进。但每个测试各自只有一套关系，仍未覆盖同库两套合法关系之间的交叉引用；仍只检查异常文字包含FOREIGN KEY，未断言sqlite_errorname；未显式检查基线／回滚后的FKcheck。因此B只记部分补齐，不称全部要求完成。

### 7.4 剩余事项与执行顺序调整

R01持久测试欠项保留至W1收尾（R09），不阻止先修已独立复现的运行时／凭据缺陷，也不关闭R01：同一profile同库的两个不同计划A/B完整合法图，正向commit＋FKcheck后只改单一引用指向另一合法图或不存在版本，并精确断言SQLITE_CONSTRAINT_FOREIGNKEY（含deferred commit）；STRICT_INT_COLUMNS实际覆盖独立版本列及nullable例外，不能仅定义或只测config；已复现input任务/年级、task状态、active空key_id、hmac无key_id等CHECK需持久反例；真实0001/0002/0003逐个升级、D1历史及v4不变、重复启动/初始化不增种子、个人指导与bundle及空游戏payload一致；全部D2测试显式合成credential_root。冻结输入／输出的剩余差异见§7.3，三类契约/指导及去ID边界按规格核对，初版contract/schema为整数1，protocol才是chat_completions_v1，database_uuid为标准随机UUID，业务ID沿opaque规则。

接下来先R03路径／锁，再R02备份／摘要，再R04/R05凭据与R06–R08配置接口，最后集中完成上述R01测试欠项和R09回归／冻结探针。整个W1未通过；顺序调整不减少任何已确认验收要求，不需要用户另行授权。所有源码/测试仍仅OpenCode写，Codex继续独立核查。

R03已串行启动新OpenCode会话`ses_eb56d23b6ffes40mpkEhMEIEx8`，输出`opencode-run6.jsonl`。限定runtime／必要原始路径辅助及新R03测试，不修改R01模型/迁移、凭据或API；current.md已收敛为本子任务，旧R01独有未闭项归并在本节，没有取消。测试B会话已结束（CLI退出0），未并行另起实现者。

R03部分初始化失败反例已实际确认：`%TEMP%/kgm-d2-w1-review-prepare-failure-t8ra_ozg/codex-evidence.json`。只在sessionmaker阶段注入异常，确认触发；失败runtime仍prepared=true而session不可用，同根另一个runtime却能取得锁。凭据根未创建；runtime源码前后SHA均`0f46f8e3825baebf07bb6f48a4926b52461cc872b0bf8a33827aec942eb27dc3`。这证实了半准备状态问题，R03须清空engine/factory并释放本实例资源，不能仅释放锁。

2026-10-18零时补证：`%TEMP%/kgm-d2-w1-review-path-api-faults-m6x81ce_/codex-evidence.json`。在独立合成文件上分别注入GetFileAttributesExW／GetFileInformationByHandle／CreateFileW非不存在错误5，三个当前路径检查均返回“无别名”的False而未拒绝，确认fail-open。此项是API故障注入，不冒充真实ACL拒绝夹具；runtime前后SHA仍为上述0f46f8…。

R03大批次到00:13仍无源码编辑（runtime仍0f46f8…，sqlite仍`2e7ec2f369a19f9e88461629eeb5a4564b943b8b723b7111d1ce9bb4529cf975`）。Codex调用同会话interrupt?resume=false，CLI退出1、active为空，确认没有剩余实现者后收窄批次；不伪报provider错误或实现通过。接下来R03-A只做未resolve的显式/环境/默认根选择与祖先junction检查；R03-B处理DB/WAL/SHM/锁硬链接、最终锁句柄属性与非不存在API失败拒绝；R03-C处理完整生命周期/部分初始化清理以及真实双进程互斥/kill后重开。所有原R03要求保留：OPEN_ALWAYS/share0/不继承、持有到关闭、只关自己句柄、不删别人锁、不全局重入、不为旧测试缩短持锁期。每批都须实际编辑和测试，不用计划文字当交付。

## 8. R02后续交接要点（尚未实施）

2026-10-18 00:21核查解释纠正：R03-A不得把credential_root的路径拒绝放在LocalRuntime构造/prepare中。工程规格§3明确凭据不可用时手工路径仍可用，因此数据/DB原始路径在启动前检查，凭据根仅保留未resolve的原始绝对路径，交给CredentialStore使用时检查；服务层随后把读失败映射为ready=false。不安全受管根仍拒绝保存新secret。已更新current并向运行中的会话`ses_eb55a6685ffedrYB8NPrSIZZao`发steer（`msg_14aaaa3670016CvpCSYIFvP2m1`）。此前要求凭据junction直接阻止启动是Codex工程解释偏差，不是用户需求变更。默认/注入凭据junction的测试应证明手工prepare成功、原始路径未丢失且CredentialStore拒绝使用。

00:27 R03-A中途独立复测：`%TEMP%/kgm-d2-w1-review-raw-roots-ms_ayoo_/codex-evidence.json`。真实junction下，显式data_dir/db_path、KGM_LOCAL_DATA_DIR均拒绝；cwd位于junction的相对data_dir也拒绝。显式credential_root保留别名，正常数据根prepare通过、不创建凭据目录，CredentialStore使用时拒绝。仍有两缺口：`db_path=~/tilde/kindergarten.db`在测试进程USERPROFILE指向junction时漏检（raw未expanduser）；相对credential_root未转绝对。已向同一运行会话反馈，应先expanduser并取未resolve的绝对原始路径再检查/保留，补持久反例；不把中途结果记R03-A通过。

00:32–33 OpenCode新增test_d2_runtime首跑失败，夹具使用CreateSymbolicLinkW却称junction，并以BOOL绑定返回BOOLEAN，未确认真实链接已创建；多个用例仍省略合成data/credential根。Codex已反馈使用真实mklink /J并断言is_junction，默认凭据用例必须显式正常数据根，实际prepare证明手工降级，所有测试与相对cwd均限定合成根；不可skip或放宽拒绝断言。此轮失败不是通过证据，run7保留原始输出。

R03完成后再派发，本节不扩大当前OpenCode子任务。基于§6–7已验证的WAL备份、占用拒绝及三阶段回滚，保留有效代码，定点补齐：

1. 运行锁持有期间分类源库；仅对已知非空旧revision做冷升级。检查备份受管目录原始路径，备份文件以UTC＋随机ID唯一创建，不覆盖已有备份；未知／更新／多行revision不备份不升级。
2. SQLite backup后验证备份完整性、FK及真实revision，revision须与源库检查相符。关闭句柄后计算SHA，清单的version写源库实际revision，不能硬编码目标0004；只含版本／时间／hash。备份或清单失败不得启动迁移。
3. 用备份中已有D1表／列建立确定的业务摘要（包括历史行、当前指针、表头及版本；不含Alembic版本表，也不把升级新增列误当既有数据变化）。排序与类型编码确定，日志只记录摘要／判断，不打印业务行。
4. 在显式BEGIN IMMEDIATE后、迁移前复核源revision和旧数据仍与备份一致，避免备份到写事务之间的变化被遗漏；迁移完成但COMMIT前再次比较旧表旧列摘要并做完整性／FK检查，异常走现有完整ROLLBACK。可通过migrate/env的有限回调接入，不能改既有0001–0003版本脚本或以注释代替检查。
5. 提交后再读回head及完整性／D1摘要，通过后才开放运行时。失败保留原库当前事实和备份，拒绝启动，不自动恢复覆盖、stamp或downgrade。保留现有事务故障回滚行为。
6. 持久与独立复测覆盖真实0001/0002/0003、WAL最后提交、同时间多次备份、占用库、备份/清单失败、摘要不一致、建表/种子/提交前失败；只用独立合成根，已有Codex证据不得原地改写。最终旧D1拒写副本证据已具备，但如相关代码改变须核对影响。

## 9. 2026-10-18续审：运行时、迁移及剩余缺口

R04/R05底层实施中（run10）独立反例：`%TEMP%/kgm-d2-w1-review-credential-r04-mid-kd7dj_io/codex-evidence.json`，credentials SHA `42bcb6bc0fccd7645675dc3e2774a41602e24fa474a72df4641051aa978c401c`。直接受管root首次保存实际32字节成功；嵌套credential_root的非受管parent不存在时首次保存失败（新代码只创建root/uuid，丢失原有父目录创建能力）；预放.tmp-fixed.dpapi并固定随机临时名造成CREATE_NEW碰撞后，错误清理删除了原哨兵。已要求安全创建缺少的非受管父目录但不改变既有父权限/读取副作用，以及只清理本次确实创建的临时文件，补原文件hash不变测试。两个缺口未关闭，不写凭据底层通过。

R02中途反例已派同会话（run9）：
- `%TEMP%/kgm-d2-w1-review-manifest-short-write-36ursijw/codex-evidence.json`：真实0003库，仅在_write_exclusive_bytes内注入实际os.write每次只写1字节，manifest仅1字节而prepare成功、源已0004。原helper忽略os.write返回长度。要求全量写入循环、零进展/异常拒绝、os.fsync成功后才能迁移，并加短写/零写/刷盘失败持久测试；这是实际错误，R02尚不能通过。
- `%TEMP%/kgm-d2-w1-review-digest-columns-215lklll/codex-evidence.json`，d1_digest SHA `cacc82de9f8c1301a31985b6b9f9773d72395dc5b2f3b890f560cb3db5f4c7e1`。实际SQLite local_classes(id,name)一行name值恰为'name'，捕获摘要后把列rename为renamed_name，旧列缺失却摘要仍相同。原因是SELECT未限定双引号标识符触发SQLite DQS字符串回退；必须验证旧表/列存在、允许新增列，并防止缺列被当常量。要求增加迁移内故障回滚测试，不能只对正常数据计算hash。
- `%TEMP%/kgm-d2-w1-review-backup-hash-fault-ud2vu3yk/codex-evidence.json`：真实0003旧库，备份hash读取Path.read_bytes故障确实触发，源仍0003、prepared=false，但原样OSError且无应用错误码。要求对备份目录/文件/hash、guard构建和提交后验证的OS/SQLite异常作安全LocalError映射，保持清理，不改R03 sessionmaker异常语义。

R02已通过的独立部分证据（不能覆盖上面的短写缺口）：
- `%TEMP%/kgm-d2-w1-review-cold-upgrades-final-v_91stg7/codex-evidence.json`：分别真实Alembic0001/2/3＋已审查的合成旧数据夹具，独立按原表/原列逐行比较（不复用生产digest判等）全部一致；备份行也一致，真实源revision/manifest/hash/完整性/FK均对得上；0003配置v4保留，0001/2既有迁移默认v1；重启state相同、不再备份、不创建credentials。第一次独立夹具使用sqlite3连接上下文却未显式close，被占用探测正确拒绝；改为contextlib.closing后重建新合成根复测通过，该夹具错误不记产品失败。
- `%TEMP%/kgm-d2-w1-review-migration-faults-final-28aw265f/codex-evidence.json`：真实子进程提交后os._exit留下4152字节WAL，最新提交在备份内且manifest正确旧revision；实际迁移事务内改名旧列已确认DDL执行成功，随后摘要拒绝并完整还原旧sqlite_master/revision；hash读故障转换LOCAL_STORAGE_ERROR且源0003；提交后强制head不符拒绝启动、保留实际0004且prepared=false。
- 对应runtime `d159ed6a…`、migrate `0198182e…`、d1_digest `80476480…`、env `02d7c615…`；待短写修复后复核最终hash及测试。

01:12 R02本批收口：OpenCode run9已交付，CLI退出0、active为空。Codex独立运行test_d2_migration_safety＋test_d2_runtime＋test_migrations，72项/12.745秒/退出0，日志`%TEMP%/kgm-d2-w1-codex-r02-tests-63b58f6d47a74ec68488f350029fbcb3/codex-tests.txt`。最终runtime `82b77d420f1dafbd7c132393edd7168adb0aa7d3ec7e617fa16ed1987bb79e5f`，test_d2_migration_safety `53abca88…`，其他生产模块hash同上。各事务故障测试已补fired/entered和原因链，改列/删列在DDL成功且列确实消失后才置位。

独立短写复测`%TEMP%/kgm-d2-w1-review-manifest-final-z_56245c/codex-evidence.json`：每次写1字节可补齐完整JSON、hash相符后升级；零写、先写1字节再异常、fsync失败全部LOCAL_STORAGE_ERROR，源保持0003，失败文件事实保留。记录中的calls只统计被注入的函数，未注入的正常fsync不计数。至此关闭上述三项中途缺陷，R02在当前Windows合成环境工程核查通过，仍不代表W1整体通过。

01:12范围核对`%TEMP%/kgm-d2-w1-codex-20261017-201057/codex-scope-check-0112.json`：原276文件无缺失，10个既有文件变化均在W1本地业务/迁移env/迁移测试范围；原0001–0003、前端/依赖未变化。新增W1文件另列本批交付记录。原D1 exe SHA仍`c6dc19283a24d00a740f2ecbed2cc7159e951f02a37f00636b294b7670369930`。下一批R04/R05只修凭据文件底层，配置与密文生命周期另在R06–R08继续。

R03-B/C独立中途验证（待实现者本批完整交付与持久测试）：runtime SHA `610c7479ab3b5515ec7d9dff568d303e9f3ca846a96596abf00159911334f97c`。
- `%TEMP%/kgm-d2-w1-review-runtime-bc-hqbs67to/codex-evidence.json`：DB/WAL/SHM/锁四种真实os.link，实际nlink=2且全部拒绝；GetFileAttributesExW/CreateFileW/GetFileInformationByHandle分别注入error5全部拒绝；sessionmaker故障后prepared=false、session拒绝，同根另实例可prepare；重复prepare未调用ensure_local_schema且返回同一就绪inspection。前后源码hash相同。
- `%TEMP%/kgm-d2-w1-review-lock-processes-final-b_7dv7o0/codex-evidence.json`：独立真实Python持有进程成功；同根第二进程明确LOCAL_APP_ALREADY_RUNNING，不同根成功；只kill本次持有者并回收pipes后，同根新进程成功；真实GetHandleInformation确认锁无继承位。所有根独立、无真实凭据或应用AI。
- Codex独立重跑test_d2_runtime＋test_migrations：43项/9.079秒/退出0，日志`%TEMP%/kgm-d2-w1-codex-r03bc-tests-f86c14b9076748fab6ed0ee11470d7f8/codex-tests.txt`；过程LOCALAPPDATA仅临时合成根。运行后进程清查无test_d2_runtime/lock_worker残留。OpenCode对应43项8.359秒通过；其额外旧D1小组15项10.616秒退出1（6 failures/3 errors，包含subTests），旧路径锁文件白名单、旧迁移head哨兵及旧并发生命周期问题继续留R09，未改旧测试或降低锁约束。最终本批报告仍待OpenCode收口。

00:48 R03-B/C报告已交付，CLI退出0、active为空。runtime `610c7479…`、test_d2_runtime `3c79398f…`、新增lock_worker `59b5f23c…`与核查对象一致。本批R03在当前Windows开发环境工程核查通过；不代表W1或发行通过。已将current切换R02并继续同一已启用免费模型的OpenCode会话，修备份实际版本、事务内D1摘要和故障拒绝。前述额外旧D1失败保留R09，不把未验改通过。

00:41 R01剩余约束再核对：`%TEMP%/kgm-d2-w1-review-empty-key-id-b_pi24qe/codex-evidence.json`，真实新Alembic库/正常initialize后，active凭据key_id空串以及HMAC回执fingerprint_key_id空串均可提交，FK检查为空。models仍`cd6ed16e…`、0004仍`d4950820…`，因此CHECK对照一致并不表示这些逻辑约束合格。当前检查只排除NULL，空串尚未修复，保留在R01收尾清单；至少约束有效key_id形状并在ORM/0004同步，加真实非法行测试。此前“enum/HMAC null检查已补”不涵盖空key通过。不得因此打断正在进行的R03-B/C或改旧迁移。

00:38 R03-A会话已正常退出（run7 CLI退出0，active为空）。Codex独立执行`cd backend; ../desktop/.venv-d1/Scripts/python.exe -m unittest tests.local.test_d2_runtime tests.local.test_migrations -v`，合计26项/3.151秒/退出0，过程LOCALAPPDATA只设为独立合成根；日志`%TEMP%/kgm-d2-w1-codex-r03a-tests-98250f23c80647179133b911b988fa85/codex-tests.txt`。确认真实mklink /J夹具、原始路径/tilde拒绝和凭据别名不阻手工prepare。仍先resolve再查保留raw（不是报告所称“resolve之前”），默认凭据相对路径归一和少量测试断言留R03-B/C合并整理；不关闭R03整体。

编码会话选型调整：此前可选模型问题未收到新偏好，继续原模型到R03-A交付。因多次夹具/API类型和落实偏差，Codex只读查询OpenCode `model.list`，确认`opencode/deepseek-v4.1-flash-free` enabled=true/status=active、输入/输出/缓存标价均0，下一批仅使用CLI会话级--model指定它；不修改全局配置、不使用付费候选、不调用应用AI。仍只有一个OpenCode实现会话，Codex负责独立复核。不是要求用户重复授权W1。

2026-10-18 00:30，`%TEMP%/kgm-d2-w1-review-clear-zero-ispgl6sr/codex-evidence.json`：真实新库/正常initialize后直接调用clear_secret(expected=0)，实际错误为`SQLITE_CONSTRAINT_CHECK`、`ck_local_operation_records_target_version`，不是FK失败。`_store_receipt_and_audit`把外部未配置版本0写进只允许null或>=1的旧审计字段。R06/R07修复应保持state.current_config_version为null、API回执版本0/changed=false，审计target_version_after使用null；不改旧约束、不创建伪版本0配置、不为这个错误添加新列或修改旧迁移。凭据目录没有创建。该证据细化此前HTTP 503，覆盖早先对失败原因的猜测。

01:30 R04/R05底层收口：run10退出0、active为空，credentials最终SHA `d16f7396b83f2371b3d5cd1dab9266ccb0792db557e61a25f3200106bbce0324`，新增test_d2_credentials `d34a6adc…`。Codex独立63项（credentials38＋runtime25）/7.047秒/退出0，日志 `%TEMP%/kgm-d2-w1-codex-r04-tests-b184f2d5d7854ebe95bf6ef846a0307c/codex-tests.txt`。故障代理记录触发次数；真实DPAPI、junction/hardlink与当前用户ACL有正反证。未创建其他Windows账号，不声称跨账号实际通过。

独立ACL证据 `%TEMP%/kgm-d2-w1-review-credential-acl-final-ehxaqosy`：PowerShell Get-Acl单独核验root/UUIDdir/file owner为当前用户、DACL保护、仅当前用户和SYSTEM共两条完全控制Allow；实际icacls给三个合成case分别增加Everyone后，root/UUIDdir错误均拒绝load及新save，只有旧file错误时拒绝load但允许新key保存，原文件hash不变。此恢复语义已明确给OpenCode，不要求一个坏旧file阻止全部重填。

`%TEMP%/kgm-d2-w1-review-credential-collision-fixed-liei2tx8`独立复测的codex-evidence.json确认缺失父目录首存通过；CREATE_NEW临时名碰撞被拒绝，原哨兵hash保留、目标未创建；source SHA同上述最终版。关闭本节两个R04中途回归。该结论仅凭据文件底层；服务GET降级、重填、配置回执、历史密文生命周期仍留R06–R08。current已切换该批，继续同一OpenCode实现会话。

后续R09实施细化（尚未派发，不扩大当前R06–R08）：现有test_concurrency用第二LocalRuntime同时开同根，worker.py也每子进程prepare，与新整程锁相冲突。应保持一个真实owner runtime持锁；事务并发专用测试worker只连接已准备合成DB、创建独立SQLAlchemy session（不迁移、不绕过生产锁）；原restart测试仍用真实完整runtime顺序重启。线程测试可从同一runtime取不同session。startup跨进程锁单测保留真实拒绝。不新增生产ignore_lock或重入特例。support.make_runtime/worker_spec及直接runtime调用全部显式合成credential_root，旧路径白名单只加.app-runtime.lock，复制资源哨兵定位当前真实head，不改旧0001–0003。回归验证保存原有并发单赢家、完整读快照和Word分页断言。

W1冻结探针应由OpenCode新增专用入口/构建脚本，独立build/desktop-d2-w1目录，不调用旧build_d1中的npm ci、不安装依赖、不覆盖旧包。采用已装PyInstaller/cryptography/26包，打包真实local runtime/migrations/credentials/config service；无需GUI、worker网络或W2–W6。父验证进程随机生成合成secret，仅经stdin/受控IPC传给冻结probe；首次真实保存并退出，第二次同库/同凭据根启动且将同一个内存secret再次经stdin传入，实际解密比对，只输出布尔/版本/脱敏错误。不得为了比对把secret或普通SHA落临时文件/env/argv。包括业务根与凭据根分离、仓外含中文/空格/%/#路径、冻结迁移/默认bundle来源核对、实际ACL/无明文扫描。记录此为当前Windows W1基础探针，不冒充完整D2最终GUI/TLS/Job包G16或干净机器发行通过。

R06–R08 run11中途独立验证 `%TEMP%/kgm-d2-w1-review-config-r11-mid-055122z_/codex-evidence.json`（service 92e2204d…）：正常initialize后首次随机secret保存AttributeError，源码在None credential上先取id。URL函数错误拒绝全球单播IPv4/IPv6，仍接受空userinfo、尾部空?/#及localhost；已把反例发回同会话。另指出旧密文保留查询须绑定task.current_execution_id/活跃task，不仅execution未结束；省略secret/跨域回执不得无条件_require_store。实施中结果不记通过。

R06–R08独立HTTP部分通过（等待本批持久测试/最终交付，不关闭整体）：
- `%TEMP%/kgm-d2-w1-review-config-http-r11-xyg1611h/codex-evidence.json`，service a9c9fe8e…：无档案409；clear0为200/v0；首存v1、同secret no-op v1且HMAC、替换v2、clear v3；原PATCH/no-op/clear回放均与原八字段完全相同；历史全部cipher/nonce清空；旧key损坏重放409 AI_RECEIPT_UNVERIFIABLE附脱敏结果，GET receipt仍200原结果。随机合成secret未在响应、捕获日志及合成根文件内发现。
- `%TEMP%/kgm-d2-w1-review-config-http-races-final-aerob9k2/codex-evidence.json`，同hash：真实Uvicorn双HTTP，barrier在两次真实key保存之后；同键两200相同结果/仅1版1回执，异键一200一409 AI_VERSION_CONFLICT/仅1版1回执；线程收口，限制DNS调用只允许测试本机host/port的spy记录外部调用0。
- `%TEMP%/kgm-d2-w1-review-config-recovery-final-f7lrfnfa/codex-evidence.json`，同hash：实际旧key硬链接后GET200/has_secret=true/configured=true/ready=false/CREDENTIAL_UNAVAILABLE；新secret重填v2 ready恢复且旧文件hash不变。受管root改真实junction后GET降级、无secret no-op仍v2、写secret503且头不动、clear成功v3；session/Host/Origin拒绝与no-store均正确。其中手工计划用了学期外10月日期，422是独立夹具错误，不作为产品失败或通过。
- 修正日期到实际初始化9月学期：`%TEMP%/kgm-d2-w1-review-manual-degraded-t0vrqgii/codex-evidence.json`（service f0c4d7db…），凭据root实际junction、当前仍有secret而ready=false；手工创建201/保存200至v2/读回相同。首次export错用/api/local/exports而404，随后按源码正确/api/exports重测，补证在同根codex-export-restart.json：真实runtime重启后AI仍降级、计划v2可读；正确DOCX出口先返回409缺项确认，待带完整expected_context确认后补证。两处夹具修正不隐去原记录，不把合成DOCX结构检查当逐页人工验收。

同一手工降级合成根的codex-export-confirmed.json补证：初次实际EXPORT_ACK_REQUIRED（409），带回完整expected_context并ack_missing=true后出口200、14039字节、有效ZIP且word/document.xml存在；这才是本次导出通过证据。此前404是错误路由、409是正常缺项确认，不隐藏或混写。

01:54 run11已完成（CLI退出0，active空）。Codex独立config43＋credentials38共81项/12.670秒/退出0，日志 `%TEMP%/kgm-d2-w1-codex-r06-tests-7e75e4de8ec848fc8195b819dede67a9/codex-tests.txt`。最终service `7daa8eefb249ecb792342cabcc110d9bba056fadf65e7fbdacf2caa17143d1a0`、schemas `165e48090bf4030790c5afe878e5724c146eab22f0a6138e648b2b6ccbfa4674`、api `8847b21e8fad8b524c3d9c402d037138442a5a4824e57c1ef143f45da1288cbd`、test_d2_config `c1ff6776…`。OpenCode合并106项包含未改变runtime25也通过。其最初并发夹具类型断言、URL错误码、重复个人种子夹具问题均已修复，如实留run11；生产core正向与独立反例证据不由这些自测代替。

`%TEMP%/kgm-d2-w1-review-config-lost-response-785cw586/codex-evidence.json`对应最终service：真实HTTP请求在服务事务写receipt前barrier，确认进入后客户端shutdown+close且未读响应，随后解除barrier；GET receipt 200、原expected原request_id重传200且与原快照一致，只有1版1回执。没有重发供应商请求，只有本机HTTP。

R06/R07及R05服务生命周期在当前Windows工程核查通过：含secret no-op HMAC、完整原回执、无secret坏根降级、重填、clear撤销与活跃已领取执行retired保留（排除pending/paused/unknown/非当前/已结束）都有持久或独立证据。映射IPv6按底层IPv4同样检查是对Codex此前提示的修正，未改变用户需求。孤立surrogate反例 `%TEMP%/kgm-d2-w1-review-config-unicode-cxawu_gr` 已补三个安全422持久用例，正常中文/emoji可用。

R08只剩一处源码误拒：最后修localhost.localdomain时扩大成任意host标签为localhost均拒，误挡localhost.example.com/example.localhost.net这类普通合法域名。限定精确保留名称/后缀，实际DNS私网检查仍W3，不能无理由缩小兼容范围。已并入下一串行R01收尾的单函数/对应URL测试小修。除此之外R08实际HTTP/验证/guard/no-store证据已齐，未据自测数抹掉这一小缺口。全部W1仍待R01/R09。

02:02 R08最后URL误拒复测通过：`%TEMP%/kgm-d2-w1-review-url-final-oaw29luw/codex-evidence.json`，service `f27177ee32fa75fdbbbf6114c8b93658a81d28f79a3d63d4a571d64285e64d73`。localhost.example.com/example.localhost.net按普通合法域名接受，localhost./*.localhost/localhost.localdomain拒绝；公网IPv4与映射公网IPv6接受，映射回环、空端口、IPv6zone拒绝；没有DNS/外联。普通域名真实解析检查仍W3。

R01新增形状CHECK中途反例：`%TEMP%/kgm-d2-w1-review-key-shape-mid-fqp57u3s/codex-evidence.json`，models cec16ff9…，实际ORM表达式在SQLite接受abc+内嵌NUL+/bad，因为GLOB/length在NUL处截断。首条反馈误称BLOB b'a/b'也通过，实际结果为0拒绝，已即时更正并保留证据；同根blob-detail.json证实仅合法字符BLOB b'abc'为1被接受（非文本）。要求两个key_id谓词同步补typeof=text和instr(char(0))=0、真实迁移库持久负例，不把错误描述写成产品事实。

R08最后URL改动的独立持久测试：AiConfigValidationTests 7项/0.003秒/退出0，日志 %TEMP%/kgm-d2-w1-codex-url-tests-3ff90e36daaf4be1ba1884b5ce24ba6a/codex-tests.txt；与上述最终URL反例一起关闭R08小缺口。配置整体将在R09全local回归时随最终模型再核对。

02:07 R01冻结schema中途核查：新OTHER input晨间allOf只设maxContains=1却漏minContains=0，会误要求两kind都出现。已依据[JSON Schema 2020-12 §6.4.5](https://json-schema.org/draft/2020-12/json-schema-validation#name-mincontains)确认minContains缺省为1，并交OpenCode补输入0..1、输出1..1结构断言。仅查阅官方规范，无应用供应商调用、不安装验证器，不宣称W1已运行完整JSON Schema校验引擎。


02:19 R01 run12已交付，CLI退出0、active为空。Codex独立运行test_d2_schema＋test_d2_migration_safety＋test_migrations：64项／8.765秒／退出0，日志`%TEMP%/kgm-d2-w1-codex-r01-tests-cc9cf836144b4e16a05a4eb7a12feb66/codex-tests.txt`。最终models SHA `0aa9a184240214c86bfdabf6ad1c75910f6b9a31ec10a3c9015c7a732bd4de07`，0004 `30a31e5f8a5dbc67c3d243b8d04fa5dcac77282b7abe71fccc272419cadece76`，test_d2_schema `dc083c13a0c607457662e8040f0abc0327f7ed55b602ad84556720dad536f9e1`。持久用例真实构建迁移库，含key的NUL／BLOB／空串拒绝、完整双计划关系正向提交及14项单因子FK反例、独立版本列与可空指针、种子/hash一致及6份冻结schema结构。输入contains明确0..1、输出1..1；无独立JSON Schema运行器，运行时完整校验仍W2/W3。

核查解释更正：local_ai_state.current_config_version／blocked_config_version依靠deferred复合FK引用已有正整数配置版，没有独立CHECK；NULL和有效1可提交，坏值在COMMIT以FOREIGNKEY拒绝是正确证据。Codex最初统一要求CHECK属于过度约束，已在run12 steer中更正；个人rejected_default_revision等自身CHECK仍精确验证。没有为测试新增冗余生产约束。R01分项通过不表示W4候选基准业务链通过。首跑夹具2 errors＋1 failure保留run12；已修正事务、singleton及SPLIT层级定位。核对文档换行后未发现字面反斜杠r/n，因此未做换行替换；历史证据保持。

下一串行批次R09执行旧测试生命周期适配与W1独立冻结凭据探针。仅测试和专用构建／探针代码，已验生产模块保持；若全回归发现实际生产回归，先保留证据再定点修复。无真实AI或发布。


R01独立SQL补证：`%TEMP%/kgm-d2-w1-review-r01-final-om6ujxil/codex-evidence.json`。正常初始化真实Alembic库，合法URL-safe key实际COMMIT成功；空串、内嵌NUL、合法字符BLOB、超长和路径字符五类均精确CHECK拒绝，FKcheck=0。models/0004/test源码hash与run12交付相同。不是仅计算谓词或复述OpenCode结果。


R09 run13在完成部分测试夹具编辑后收到provider.quota／HTTP429／FreeUsageLimitError，CLI退出1、session.active为空；不能写为交付或测试成功。已保留原日志与编辑。model.list只读核对GLM-5.3-Flash Free enabled=true/status=active、输入输出缓存标价全0，run14仅CLI --model切到opencode/glm-5.3-flash-free并继续同一实现会话，不改全局配置／付费配置。Codex同时运行已改6模块独立小组，仍只有一个OpenCode代码写入者；应用真实AI没有启动。


run14同样立即收到provider.quota／429／FreeUsageLimitError，CLI退出1、active为空，无新编辑。未将“模型目录标active”误当可用额度。Codex已向用户提出恢复免费额度或指定已有模型的简短选择；不会擅自使用付费模型，也不会越过AGENTS的OpenCode唯一实现者规则。

R09已完成部分的独立检查：test_concurrency＋test_export＋test_paths＋test_restart＋test_initialize＋test_transactions共48项／58.064秒／退出0。证据`%TEMP%/kgm-d2-w1-codex-r09-mid-tests-babcdeff0ecb42098de5c873e78f5872/codex-tests.txt`。保留一个运行锁owner，事务测试使用独立session／仅测试DB worker，真正restart明确connect_only=False；复制迁移资源哨兵定位当前head，锁文件精确白名单，worker失败清理已加入。生产模块未放宽锁。

尚须由OpenCode补完：test_migrations.py两处直接LocalRuntime显式credential_root（本次运行用进程级合成LOCALAPPDATA隔离，未写真实凭据根）；专用W1冻结probe/build/verify与实现结果报告。test_d2_runtime.py有意测试默认凭据路径的调用已使用隔离LOCALAPPDATA，不应机械更改其测试语义。Codex继续执行全local回归，不能因48项小组通过而关闭R09/W1。

## 10. 本轮收口状态：主体通过，额度受限导致W1尚未关闭

Codex独立全local命令：`desktop/.venv-d1/Scripts/python.exe -m unittest discover -s backend/tests/local -t backend`，PYTHONPATH指向backend，LOCALAPPDATA仅进程级独立合成目录。实际 **286项／118.079秒／退出0**，没有失败或跳过；日志中的log-capture-sanity是日志捕获测试主动写入的哨兵。证据：`%TEMP%/kgm-d2-w1-codex-local-all-b4cc5350d8374369af1c389e556e7d6e/codex-tests.txt`。本结果覆盖本轮R09部分测试编辑后的最终现存源；不替代尚未构建的冻结exe重启证据。

| 项目 | 当前结论 |
| --- | --- |
| R01 数据约束／冻结种子 | 当前Windows合成库通过，§9；冻结schema仅结构检查，完整运行时JSON校验留W2/W3 |
| R02／R03 迁移／备份／运行锁 | 当前Windows实际文件、SQLite及子进程证据通过，§9 |
| R04／R05 DPAPI／ACL／原子保存／恢复及清除 | 当前用户真实Windows API与故障注入通过，§9；不是实际跨账号验证 |
| R06–R08 配置事务／HMAC回执／API | 当前本机实际HTTP与持久用例通过，§9；未调用供应商 |
| R09 D1回归 | 改后48项小组与全local286项独立通过 |
| R09剩余 | 两处test_migrations显式凭据根、冻结probe/build/verify、OpenCode交付报告和Codex包核查未完成 |
| W1整体／D2产品／发行 | W1未关闭；D2产品及发行未验，不启动W2–W6 |

范围核对：`%TEMP%/kgm-d2-w1-codex-20261017-201057/codex-scope-check-r09-partial.json`，原276文件无缺失；18个既有文件变化限定W1本地模块、迁移env及测试。原0001–0003、前端、依赖和旧D1包未变；exe仍`c6dc19283a24d00a740f2ecbed2cc7159e951f02a37f00636b294b7670369930`，分支仍codex/desktop-v2-foundation。检查时没有本轮local worker／discover测试进程残留，OpenCode session.active为空。原教师库、exports、真实密钥及远程不动，无commit/push或发布。

恢复时继续同一OpenCode会话`ses_eb545ac1dffean47OjczPDCEDO`，读取唯一current.md与本节即可。run13在部分编辑后、run14在开始时均收到HTTP429 FreeUsageLimitError；不能把model.list中active当额度可用。需要用户恢复免费额度或指定可用的已配置模型；未授权付费切换，不由Codex代写实现。恢复后先补test_migrations.py两个LocalRuntime的合成credential_root并复测该模块，然后落实仓外特殊路径的专用冻结凭据探针（整个包移出仓库、无开发源码回退、随机secret仅stdin、两次真实进程），最后交付结果并由Codex核查。除有新改动／失败证据，不重复已通过全回归或人工IME。

## 11. 用户指定Go套餐后继续W1收尾

用户先确认偏好deepseek-v4.1-flash或glm5.3-flash，随后明确“使用go套餐的模型”。这替代此前等待免费额度的选择。本机model.list核对`opencode-go/deepseek-v4.1-flash`及`opencode-go/glm-5.3-flash`均enabled=true/status=active，优先前者，继续同一实现会话`ses_eb545ac1dffean47OjczPDCEDO`，run15日志仍在原证据根；仅CLI会话级模型覆盖，不改全局配置、不购买套餐或切其他收费通道。没有创建定时任务。

继续范围：两处迁移测试的合成凭据根、独立冻结probe/build/verify、OpenCode结果报告及Codex最终核查。286项现有通过证据保留，无新改动或失败不重复全量回归。真正供应商调用仍禁止；此处Go仅用于OpenCode编码模型。


run15已补齐test_migrations.py两处LocalRuntime的credential_root=self.credential_root。Codex独立复跑该模块18项／2.652秒／退出0，证据`%TEMP%/kgm-d2-w1-codex-r09-migration-final-7ebd1c4ecc774c58a10fb95c0bf27641/codex-tests.txt`。最终测试SHA为`54a0f211ef524cf08902b08a767430260fec66a9b35373c6e77c897316905f32`。此处仅测试根修正，已验生产代码和其余286项证据保持；尚待冻结探针。


Codex独立冻结证据`%TEMP%/kgm-d2-w1-codex-frozen-final-66tkpuyw/codex-evidence.json`：整个onedir包移至仓外中文／空格／%／#路径，127个文件散列一致；21个归档app/入口模块完整code元数据（仅排除co_filename）与当前源码一致；7份迁移／INI资源字节一致。exe SHA `6a283bdfc9954c683ac2e86c75762ed99a0961ff7dde47580a55419a5e91d9f4`。没有开发PYTHONPATH/PYTHONHOME，TEMP/TMP/LOCALAPPDATA显式合成；三次真实CREATE_NO_WINDOW进程：init保存、verify重启解密相同、再次verify输入另一个随机期望secret时decrypted_matches=false。前两次版本均v1且database_uuid/key_id不变，所有进程使用包内迁移；FK/完整性通过，配置／凭据／回执各一行。整份合成根（含包/cwd/临时目录）文件及捕获输出UTF-8/UTF-16LE扫描没有随机secret明文，未存secret普通hash。

同根`codex-acl.json`由独立PowerShell Get-Acl读取实际root/UUIDdir/keyfile，三处owner均当前用户、DACL保护、各恰两条非继承Allow FullControl，且仅当前用户SID及SYSTEM，均通过。此为当前Windows用户实测，不声明另建账号或干净机器通过。

父验证器中途故障反例`%TEMP%/kgm-d2-w1-review-verifier-faults-9jmtmwfg/codex-evidence.json`，verify脚本SHA `f988edc2e4da2a77cceb21a6a4a18dce49369abc93f12aeaedaba4aaf44ab4bc`：内存注入os.scandir PermissionError时errors为空（os.walk默认吞目录错误）；内存fake子进程结果JSON含随机secret时stdout已脱敏，但返回result仍含原secret，虽result_leaked=true仍可能写入证据。全部随机值只在内存；没有为反例落明文。已要求限定父验证器补onerror与result脱敏、保留原leak标志，不改业务/probe/构建包；等待这两处修复。既有真实包正向证据不因此冒充验证器错误分支正确。

## 12. 最终工程结论：W1通过，停在W1

2026-10-18，OpenCode run15以用户指定的`opencode-go/deepseek-v4.1-flash`完成交付，CLI退出0、session.active为空。Codex已核对[实现结果](desktop-d2-w1-result.md)、最终源／包及独立证据；R01–R09全部关闭。**W1数据迁移、凭据保存、配置回执基础与必要回归在当前Windows 11开发机工程核查通过。** 没有未关闭的W1实现问题，不启动W2–W6，也不等同D2产品或发行通过。

最终证据汇总：

| 范围 | 实际结果／证据 |
| --- | --- |
| 数据迁移／约束／种子 | §9的R01、R02独立实库证据；0001/2/3冷升级、WAL备份、事务故障回滚、D1原行/表头/版本不变；旧D1实际exe拒写升级副本见§6 |
| Windows运行锁／凭据 | §9的R03–R05；真实进程持锁/kill后重开、DPAPI/AES-GCM、实际ACL、路径/硬链接、故障拒绝、重填/清除 |
| 配置与回执 | §9的R06–R08；真实本机HTTP、双提交及断开响应重试、版本/no-op、HMAC原回执、凭据不可用时手工保存/重启/Word导出 |
| 全local回归 | 286项／118.079秒／退出0，`%TEMP%/kgm-d2-w1-codex-local-all-b4cc5350d8374369af1c389e556e7d6e/codex-tests.txt` |
| 最后测试根修正 | 18项／2.652秒／退出0，`%TEMP%/kgm-d2-w1-codex-r09-migration-final-7ebd1c4ecc774c58a10fb95c0bf27641/codex-tests.txt`；未改生产，不重复全组 |
| 冻结包独立实测 | §11，127文件、21归档模块、7迁移/INI资源同源；仓外特殊路径真实init/restart/错误期望secret三进程；版本v1不变、实际解密、完整性/FK及全合成根无明文；独立Get-Acl三处通过 |
| 最后验证器修复 | `%TEMP%/kgm-d2-w1-review-verifier-fixed-bwxz_ele/codex-evidence.json`：目录扫描失败确实记录、结果递归脱敏及原泄漏标志保留；最终verify源码`664a68b6ce815c60df418765f6f714319ae810ca779cd366dd3ecb0bca5f9a20` |
| 最终父验证器独立执行 | `%TEMP%/kgm-d2-w1-codex-parent-final-bb3d2d50209c4c68af979a48d895c8f7/codex-parent-evidence.json`，`--keep --out`退出0，29个布尔检查均true，另有文件数127／DPAPI文件数1两个计数字段 |

数量核对更正：OpenCode最后文字及原结果报告写“30项检查”，实际最终checks中有**29个布尔项**和2个计数字段。Codex已按原JSON校正报告为29；所有布尔项均true，不改变通过结论。不是30个测试用例，也不把负例原始decrypted_matches=false误计为失败（对应negative_decrypted_mismatch检查为true）。

最终范围清单`%TEMP%/kgm-d2-w1-codex-20261017-201057/codex-scope-check-final.json`：原276文件无缺失；18个既有文件变化、14个新源码文件均属W1本地模块/迁移/测试/专用探针。原0001–0003、前端、依赖保持；已验D1 exe SHA仍`c6dc19283a24d00a740f2ecbed2cc7159e951f02a37f00636b294b7670369930`。新W1探针exe为`6a283bdfc9954c683ac2e86c75762ed99a0961ff7dde47580a55419a5e91d9f4`，包manifest为`657b3f01511fc1137843a5b74c6c1ee3ee9c33e9b61653db5fc23b776219cd3d`。未改ARCHITECTURE.md、未commit/push、未发布；原教师体验库和exports未迁移或覆盖。没有创建额度检查自动任务。

W1只完成G01/G02及G03持久关系、G04当前Windows源码/冻结凭据范围；G03有效候选基准的读取/采用/导出整条业务链属W4/W6。冻结JSON Schema仅结构核对，完整运行时校验属W2/W3；未来执行器结束后退役凭据清理仍随W3任务生命周期实现，W1只验证现有配置服务的保留/清除规则。完整D2 GUI/TLS/Job及G16最终包、真实供应商和人工AI体验、跨Windows账户、干净机器、Win10、WPS、其他DPI/多显示器、WebDAV及发行再现性未验。微软拼音按用户已确认结果不重复验证。

当前没有授权中的剩余编码任务。后续用户另行授权W2时再更新唯一current.md；本轮独有决定、证据与未验边界已归并在本文和实现结果，不新增提示词归档副本。
