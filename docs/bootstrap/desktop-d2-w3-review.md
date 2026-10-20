# D2 W3独立工程核查

2026-10-18最终结论：用户授权的W3已由OpenCode使用Go套餐DeepSeek V4.1 Flash实施，Codex独立核查通过，R01–R09已修复关闭。结论限当前Windows 11合成环境及W3工程范围，详见§6–7；应用真实AI和发布未执行。前文“待修复”标注保留发现时状态，以§6最终核查为准。

## 1. 基线和范围

有效入口：[当前任务](../tasks/current.md)、[工程规格§4/§7](../specs/desktop-ai-engineering.md)。W1/W2已通过的结论保留。W3限持久任务、标准库受控transport、spawn/Job/IPC和宿主核心生命周期；W4采用、W5完整界面、W6最终包及真实供应商不自动实施。

开工全工作区非忽略文件快照399项：`%TEMP%/kgm-d2-w3-codex-7byz_ufm/before-sha256.json`，副本在同根`before/`，Git状态在`before-git-status.txt`。当前分支codex/desktop-v2-foundation；既有未提交/未跟踪工作保留，不能用HEAD差异代替本轮差异。

按codebase-memory技能查询当前项目、CloseCoordinator/LocalRuntime/任务模型。图谱generation为2026-10-18T01:45:53Z；6个相关路径均metadata_changed，已采用限定源码读取补查，不把图谱当作最新实现证明。没有安装或重建工具。

## 2. 待核查门槛

G07网络边界，G08有限重试，G09逐发送窗口真实父子进程，G13核心退出/期限及宿主代次，G15手工降级；W3涉及的版本钉住/输入/幂等及结果原子落地。冻结spawn最小包单列身份，不能替代完整D2包或真实睡眠/教师流程。每个缺陷保留首次失败及修复证据。

实施过程使用单一OpenCode会话`ses_eb3361a51ffey5U3huUnRJsYfA`，模型providerID=opencode-go、id=deepseek-v4.1-flash，CLI进程会话44005。JSONL在本轮证据根`opencode-w3-run1.jsonl`，仅提取公开文本/工具结果，不能将内部推理展示给用户。发现、失败及修复过程保留于下文，最终结论见§6–7。

## 3. 独立验证设计（待实现后执行）

| 核查面 | 独立观察与判定 |
| --- | --- |
| API与回执 | 真HTTP提交、同键旧expected重传、异域冲突、并发同计划同类型；body多余字段/strict版本拒绝，TaskOut无材料/secret，404查询不改变状态 |
| 来源与版本 | 三任务投影分别更改原文/过程/反思/姓名/游戏/无关日历日；只业务相关依赖变更阻止发送；排队改配置取新版，开始后安全重试保持旧版 |
| 结果和竞争 | 有效/无效/重复候选帧、取消先提交/成功先提交、当前与旧permit、结果COMMIT失败；唯一candidate与成功同时存在，本地重提不加外发次数 |
| 实际网络 | 专用CA受控TLS，SNI和peer绑定、代理不使用、重复/冲突长度、畸形chunk、头/body上限、压缩和重定向；普通入口拒私网，测试口不泄漏到产品配置 |
| 重试与停止 | DNS/连接暂时失败恰好最多3次及5/30秒；HTTP 429/500/401、证书失败、输出无效不自动补发；unknown风险确认，重新pending不改上代事实 |
| 进程与崩溃 | 分配Job前EOF/5秒退出、分配后父死Job回收；各mark/SEND/response/commit窗口重启分类与计数，进程句柄确认退出 |
| 关闭与期限 | close冻结同SEND闸门、等待解冻、停止DB失败拒关、旧代次拒绝、native-save busy、2+3秒收口；包含休眠的时钟先于响应接收 |
| 保留与降级 | 历史迁移/包/既有数据身份不变；退役旧凭据按live执行保留后清除；AI失败仍能保存/重启/导出，冻结探针不依赖开发Python |

此节是开工时的验证设计；实际执行证据和未验边界分别见§5–7，不以设计表代替运行结果。

## 4. 实施中发现与交回

### R01 适龄输入缺少基准来源身份（待修复复核）

首版`ai_inputs.py::project_input`只将`split_baseline`文字加入适龄依赖，未读取provenance的baseline_candidate_id。同样过程文字可能来自两个不同拆分候选，不能据文字相等判定来源引用未变，违反工程§2.2。这是源码审阅发现，尚无独立运行复现。首版副本：`%TEMP%/kgm-d2-w3-codex-7byz_ufm/ai_inputs-first-review.py`。

已交回同一OpenCode会话`ses_eb3361a51ffey5U3huUnRJsYfA`修正共享投影和定向测试，要求旧D1 null/无provenance保持合法；不提前开放W4采用或非null手工写入。

### R02 transport前缀、连接预算、HTTP完整性和诊断（待修复复核）

首版prepare丢弃base_url路径前缀，固定发送`/chat/completions`；连接预算在DNS完成后才启动。独立inline fake-socket验证（无外部网络）还发现：正文短于Content-Length但本身为完整JSON、两个冲突Content-Length、未知Transfer-Encoding均返回success；正常对照也success。首轮结果为`transport-first-independent.json`，源码副本`ai_transport-first-review.py`，均在本轮证据根。

已交回修正并补单测/真实受控TLS同类案例，同时要求request_id/model/usage白名单和容量控制、JSON失败诊断不包含模型给出的键名。独立fake-socket不替代G07真实TLS门槛。

### R03 任务首版状态与版本边界（待修复复核）

源码首版审阅发现：retry_wait记录旧版本但组装请求取当前配置/指导；发送标记缺来源/完整许可复核；暂停和retry_wait取消未同步结束execution；cancel可把unknown洗成cancelled/not_sent；第三次未发送失败误归unknown，发送后POLICY却误归not_sent；resume/retry缺原因解除/活跃冲突/配置解阻塞；结束路径缺旧凭据清理；系统消息未含输出契约。worker首版帧上限为2MiB+64KiB而非规格要求的正文1MiB+16KiB。

首版副本`ai_task_service-first-review.py`在证据根，已一次性列明A–I交回原会话，要求完成后用场景证据逐项关闭。此节为实现中源码发现，不把尚未运行的用例记为失败测试。

### R04 执行器freeze/退出/失败恢复屏障（待修复复核）

首版源码：freeze未与最终SEND共锁；检查后释放锁再发帧；claim/stop也有交接空窗。恢复DB失败被吞后仍启动调度；连接超时/EOF以`__released__`返回可遗留claimed；清理_active和_thread未证实进程/线程结束；drain与协调线程可并发使用/关闭Pipe；dispatch Session未关闭；poll之后未再次检查包含休眠的deadline。

已交回原会话，要求明确所有权/短闸门、失败闭锁与保留未确认句柄，真实进程验证。首版`ai_executor-first-review.py`保留在证据根。

继续审阅发现，大bootstrap的send_bytes、poll后部分帧的recv_bytes仍可阻塞协调线程。要求真实“不读大帧/只发部分帧”故障验证绝对期限及停止；中间helper实现长join、不保留线程引用、gate内等待以及超时后并发写同Pipe也已交回修正。Job赋予失败后未确认资源必须由executor保留实际引用，不能只留布尔值。

### R05 API回执优先与取消事务交接（待修复复核）

首版任务变更API在查回执前要求executor存在，使已成功操作在执行器降级时无法重读。executor对象存在也不等于恢复/线程可用。取消先设置立即abort再提交DB，旧expected/冲突键/DB失败可能已导致原worker终止，事后清flag无法恢复。已要求使用绑定expected执行的待提交冻结，提交后才停止，失败恢复原许可；回执重放应无额外调度副作用，并补实际HTTP交错测试。新提交还需runtime.prompt_sync_error和凭据ready检查，不仅看配置引用非空。

### R06 请求序列化容量未在提交前检查（待修复复核）

独立SQLite/真实凭据、无网络案例：OTHER六字段各75000个反斜线，业务输入JSON为900352字节，create_task(runtime=rt)仍建pending任务；实际messages序列化body为1804727字节，超过1MiB。证据`%TEMP%/kgm-d2-w3-independent-cap-hk7hpdib/evidence.json`。已交回要求在提交/领取联网前用实际结构指导+个人指导+材料计算最终请求及IPC尺寸，不以worker联网后output_invalid代替输入422；补转义/UTF8和元信息边界。

### R07 宿主接入顺序和关闭收口（待修复复核）

实施中源码发现：d1_main在runtime.prepare之前启动executor，使冷启动恢复可能失败后永久禁用AI；freeze_support位于模块底部，晚于桌面相关导入；worker通过transport导入ai_config_service，连带载入ORM/凭据层。要求在锁/迁移/提示词同步完成后、HTTP接收请求前恢复启动，抽出无数据库依赖的共享端点规范，验证冻结入口。

关闭首版stop_and_drain只冻结并等待进程，没有先单事务撤销所有未完成许可/分类排队任务；Job创建/赋予失败忽略未确认退出；dispose失败后仍无条件释放运行时锁。CloseCoordinator的deny/busy/destroy失败遗漏解冻；结果持久失败的内存保留尚未纳入退出屏障。已交回同一会话，要求真实进程和宿主竞态证据，不能仅凭8项成功测试关闭。

### R08 凭据退役清理和清除后发送（待修复复核）

独立合成SQLite/DPAPI证据`%TEMP%/kgm-d2-w3-independent-credentials-hg3f01tm/evidence.json`：v1领取后替换密钥v2，旧credential在live期间retired并保留密文正确；TLS失败终结execution后旧credential未按预期cleared；再领取v2后执行clear-secret，全部密文已清空，commit_dispatch_mark仍返回True。没有联网。源码_cleanup_credentials未flush就查保留集（运行时autoflush=False），mark只验来源不验已清除凭据。已交回修复并补清理/清除竞态测试，已标记/可能发送的历史仍须按原发送证据处理。

修复后的独立复核`%TEMP%/kgm-d2-w3-independent-credentials-fixed-vz_5o121/evidence.json`三项均通过：live保留旧密文、结束后旧密文清空、clear-secret后标记拒绝。保存状态和源码5a7db782…。该两处缺陷已复核修复；最终状态待同源全回归归并。

### R09 IPC测试和冻结探针的证据有效性（待修复复核）

实现者最新41项定向测试报告通过，但新增两项IPC测试先建任务再start，恢复阶段直接paused，未创建attempt/worker即可通过；no_read模式又在读取完整bootstrap之后才分支，无法证明大帧写阻塞。这两项不能计入IPC门槛。已交回要求独立never_read目标、start后提交、强制核实attempt/PID/fault和耗时；完整畸形JSON不能称部分帧。

冻结探针首版还存在console构建、仅数据根仓外而exe仍仓内、遗漏before-claim/Job前窗口、未spawn却强制要求worker PID、SEND后立即父死却强制网络1次、OpenProcess失败一概当退出等不准确断言。已逐项交回，须实际构建和运行后才记录冻结通过；全部失败过程保留。

第一次冻结运行因verifier读取不存在的normal[run]字段而KeyError。原命令未带--keep，脚本finally删除了该合成根，只有OpenCode JSONL的失败堆栈保留；不能声称该轮有可复查全量根。已要求后续唯一日志/输出、--keep及异常保留。

## 5. 进行中的独立运行证据

- `transport-second-independent.json`：源码f312c20d…稳定；正常/合法chunk通过，短CL/冲突CL/未知TE/缺chunk终止拒绝，供应商`/vendor/v1`前缀正确保留。仅函数级合成socket，R02仍待真实TLS及全部边界。
- `%TEMP%/kgm-d2-w3-independent-state-fuh7nawq/evidence.json`：独立SQLite+真实DPAPI，6项通过，含初次领取、配置更改后的安全重试仍钉原模型和execution、候选成功及重复拒绝、发送前修改原文后paused/source_changed。任务服务当时源码1f76ce6f…且运行期间稳定；没有供应商调用。
- `%TEMP%/kgm-d2-w3-independent-retry-0kepwwba/evidence.json`：429暂停unknown/动作、取消保持unknown、缺风险确认拒绝、retry仅重置task、第三次未发送失败failed/not_sent共5项通过；**取消重新pending会改写上次execution，1项失败**。已交回R03继续修复，连同paused取消的task/execution投影和failed确定性复核。不将前5项通过写成R03关闭。
- `%TEMP%/kgm-d2-w3-independent-tls-po8o6v2h/evidence.json`：首次独立真实TLS的5种HTTP案例均未进入HTTP，测试CA/leaf在Python3.14默认严格验证下被拒，0请求；另行握手定位verify_code=85，Missing Authority Key Identifier。已交回补齐合成证书扩展，禁止通过关闭严格证书/主机名验证来通过测试。本轮只证明默认TLS拒绝不合规测试证书，不计HTTP覆盖。
- `%TEMP%/kgm-d2-w3-codex-transport-0af63c4eeed846bbb2f91e88a2ed4e92/unittest.log`：Codex运行OpenCode所写21项transport测试，0.435秒全部通过，含真实TLS/错误CA；显式ResourceWarning检查未见告警。
- `%TEMP%/kgm-d2-w3-independent-tls-fixed-624lijyu/evidence.json`：独立真实TLS 5例，正常/合法chunk成功，冲突CL/短body/未知TE拒绝；每例实际请求1次，均观察到api.example.com的SNI和`/vendor/v1/chat/completions`路径。保持默认TLS校验。中间一次调用因辅助参数已改为PEM内容、Codex仍传文件路径而报cadata错误，修正调用后完成；不归作生产TLS缺陷。
- `%TEMP%/kgm-d2-w3-codex-task-a46bb557ca514a6f94b3c9b634c084a3/unittest.log`：Codex执行实现者任务测试26项/8.782秒通过，显式ResourceWarning未见告警；覆盖发送错误风险确认、未知结果重排、pending取消保留上一代、重启后resume新generation。此前首版25项的失败及修复过程保留在OpenCode JSONL，单项修复不等于执行器/宿主整体验收。
- `%TEMP%/kgm-d2-w3-independent-api-7tub9_ze/evidence.json`：独立真HTTP/SQLite、无调度stub，创建、创建回执在executor=None重传、取消、strict bool/extra、session/Host/Origin保护共8项通过；取消回执重传在executor=None仍503而非原200结果，1项失败，已交回R05。stub仅用于API/DB核查，不冒充真实执行器。
- `%TEMP%/kgm-d2-w3-codex-executor-2612cc1d562a4fcca89845626485f32d/unittest.log`：Codex运行实现者8项真实spawn/Job测试，9.261秒通过，含生产worker对受控TLS的单次发送及候选落库；显式ResourceWarning未见告警。测试数量与范围不能代替G09逐窗口及冻结探针。
- `%TEMP%/kgm-d2-w3-independent-recheck-85lkzbhd/evidence.json`：独立真HTTP/SQLite无调度stub的6项复核通过：创建202、取消200、无executor时取消回执原样重放且不调度、unknown重试后取消pending保持旧execution完整不变、转义膨胀输入拒绝且无任务/输入/回执部分写入。API源码20d1c3cc…、任务服务e58900c2…。此前rbtqxqbq根的404由Codex测试误写`/api/plans/daily-plans`引起，修正成实际`/api/daily-plans`后通过，不计产品缺陷。
- `%TEMP%/kgm-d2-w3-independent-network-fnx7a745/evidence.json`：独立16项通过，transport源码1f12b0d7…。11项实际TLS覆盖正常（代理环境变量无效）、头超过64KiB、固定/分块body超过1MiB、重定向、gzip、401/429/503、畸形JSON、错误主机名证书。前10例各仅1次请求并保持原SNI，错误证书0次请求。5项只替换DNS结果、不建连接：混合公私、IPv4-mapped回环、link-local、多播拒绝，纯公网地址集合接受。真实请求只连接合成loopback，未调用供应商；DNS测试不冒充公网网络/真实重绑定验证。
- `%TEMP%/kgm-d2-w3-codex-host-27fc894be105495c8f345dfcf9904245/unittest.log`：Codex运行实现者8项宿主测试，6.108秒通过；包括deny/busy/destroy失败/旧代次/timeout解冻、旧页面缺任务选择拒关，以及真实spawn下撤销DB失败保留worker并在取消close后同代完成。7项为无窗口状态机，1项为实际子进程；不冒充W5教师窗口验收。
- `%TEMP%/kgm-d2-w3-independent-requeue-api-74kbv6kt/corrected-evidence.json`：独立真HTTP的resume/retry在prompt_sync_error未解除时均返回503 PROMPT_SYNC_UNAVAILABLE；无新回执、不调度、原状态保留，6项通过。该根首次evidence.json将既定503误断言为409，且用null execution请求retry得到预期422；均为核查输入/预期错误，已纠正并保留记录，不记产品缺陷。
- `%TEMP%/kgm-d2-w3-codex-desktop-0fb77a61ef624bf2aca925d8a1890960/pytest.log`：146项既有桌面pytest通过（7.33秒、exit0），APP_DISABLE_DOTENV=1且LOCALAPPDATA隔离；1项已存在的Starlette/httpx弃用警告，不据此安装依赖。无真实窗口或人工IME复验。
- `%TEMP%/kgm-d2-w3-codex-ipc-a122ce72db0b493489c37d24c6924be1/unittest.log`：R09修正后Codex运行2项真实spawn IPC用例，4.668秒/exit0通过。never_read独立worker从入口不读取bootstrap，测试确认marker/PID、1execution/1attempt、无SEND、时限和dispose；另例仅完整畸形JSON帧。没有把后者或设计审阅冒充“实际部分帧”测试。ResourceWarning未见告警。
- `%TEMP%/kgm-d2-w3-codex-full-83a54633ad5341bc96834d472fcc15c6/unittest.log`：Codex独立执行 `desktop/.venv-d1/Scripts/python.exe -X utf8 -W always::ResourceWarning -m unittest discover -s backend/tests/local -t backend -v`，420项/233.105秒/exit0通过，未见skip或ResourceWarning。LOCALAPPDATA隔离且APP_DISABLE_DOTENV=1；该根保存执行前后源码hash，期间仅冻结探针/验证脚本变化，业务源码和被测测试稳定。此后因冻结故障产生的核心改动须另作相关回归，不能自动套用该结论。
- `%TEMP%/kgm-d2-w3-codex-desktop-final-ef115e0b28aa4dd194772a3b8a171859/pytest.log`：关闭回调并发修复后，Codex执行既有desktop/tests，146项/4.23秒/exit0通过；两项既有Starlette/httpx和AnyIO弃用警告。没有运行真实窗口/睡眠/IME。

### 5.1 冻结探针继续核查

实现者保留的失败根包括 `%TEMP%/kgm-d2-w3-frozen-d4d5a3a5-中文 空格%#`、`kgm-d2-w3-frozen-c44bd21e-中文 空格%#`、`kgm-d2-w3-frozen-c9657607-中文 空格%#`。Codex读取前两根逐场景JSON，DB重启分类、候选及完整性基本符合预期，但Job赋予前父死的子进程未退出（21308/24216的句柄仍WAIT_TIMEOUT且exitcode259）。无控制台包在继承PIPE时stdout/stderr非None本身不证明带控制台；须以PE子系统及真正无标准句柄启动共同核实。最后一根实现者仍报child_started_child_gone失败。因此冻结门槛尚未通过，已要求定位freeze_support阶段本身的父进程句柄失效异常，不能仅修worker入口或延长等待冒充满足退出要求。

后续定位在CPython/PyInstaller的子进程bootstrap：父进程先退出，OpenProcess/复制bootstrap句柄可在进入worker前失败，windowed bootloader显示异常窗口而遗留进程。实现者中间引入全局异常hook强制退出，Codex拒绝该方案；最终共享`ai_spawn.freeze_support_guarded`只识别Windows frozen spawn child，将其bootstrap异常转成非零SystemExit，正常父进程不处理、不改正常dispose。生产d1_main与探针共用；生产worker的临时环境日志已移除。`--disable-windowed-traceback`本身只改变错误展示，不能充当退出保障。

Codex独立运行修复后的包：`%TEMP%/kgm-d2-w3-codex-frozen-final-153fe37145ef4b5299c89db95e8a1773/evidence.json`，实际仓外合成根`%TEMP%/kgm-d2-w3-frozen-4e147f74-中文 空格%#`；11场景/145断言/exit0通过，Job赋予前子进程403ms退出，后续窗口句柄确认退出。PE subsystem=2，额外DEVNULL输出场景正常。这里证明不依赖可见控制台/输出，不将DEVNULL说成Python流必为None。包SHA256 `babc502994331ac24665837dce6d91fc2020025ac23dcecc1dc5c3d917f162a3`；同根`package-source-identity.json`验证24个归档模块（含探针入口、共享spawn helper）代码对象与源码一致，仅规范co_filename；7份迁移/INI资源字节一致；134文件复制一致。此包是W3最小探针，不能代替完整D2应用包。

### 5.2 最后修复后的回归

- `%TEMP%/kgm-d2-w3-codex-final-targeted-fb74bd849e1c47f49b5b30b297601342/unittest.log`：`python -X utf8 -W always::ResourceWarning -m unittest discover -s backend/tests/local -t backend -p 'test_d2_w3*.py' -v`，78项/35.704秒/exit0通过。99个相关源码/测试/桌面脚本执行前后hash一致，证据`stable-sources.json`；未见ResourceWarning。新增共享spawn识别/失败退出分支验证，迟到响应与teardown故障在提交前注入，消除依赖调度时机的测试。
- 同上真实TLS执行器用例：在提交前令finalize_success失败，收到一次实际HTTP结果后候选0、内存pending_persist存在、调度不可用；移除故障后仅重试本地提交，任务succeeded、候选1、pending清空，HTTP仍1。执行器新增后台本地持久重试，关闭仍拒绝遗留未保存结果。该修复及worker/共享spawn helper的最终版本由本次78项覆盖；之前420项全local用于共同基线回归，不把重叠测试相加成唯一用例数。
- `%TEMP%/kgm-d2-w3-codex-desktop-spawn-74a13bfbe44a4d54b52347c86bdad470/pytest.log`：共享spawn入口接入后的既有桌面测试146项/4.11秒/exit0通过，仅原有两项弃用警告。没有调用真实供应商、真实睡眠或教师窗口。

### 5.3 最终冻结矩阵与范围

增加READY之后、发送标记提交之前的真实崩溃窗口后，Codex再次运行`desktop/.venv-d1/Scripts/python.exe -X utf8 desktop/verify_d2_w3_probe.py --out <证据根>/evidence.json`，12场景/159断言/exit0全部通过。证据根`%TEMP%/kgm-d2-w3-codex-frozen-matrix-6d0fd8325062413aa3e0b783301ea7ba`；实际合成根`%TEMP%/kgm-d2-w3-frozen-3acd61b2-中文 空格%#`。同一个babc5029…包及134份仓外副本文件一致，环境PATH只含Windows目录，PYTHONPATH/PYTHONHOME不注入，凭据根和LOCALAPPDATA均隔离。

| 崩溃/运行窗口 | 恢复状态 | 实际HTTP总数 | 候选 |
| --- | --- | --- | --- |
| claim前 | paused/restart，未建execution | 0 | 0 |
| claim后、Job前、Job后、READY后标记前 | paused/restart，attempt已结束 | 0 | 0 |
| 标记已提交、SEND之前 | outcome_unknown/restart | 0 | 0 |
| SEND之后 | outcome_unknown/restart | 本次1（协议允许0或1） | 0 |
| 服务端确实收到HTTP后强杀父进程 | outcome_unknown/restart | 1 | 0 |
| 响应已到、候选提交之前 | outcome_unknown/restart | 1 | 0 |
| 候选提交之后 | succeeded | 1 | 1 |
| 正常完成、DEVNULL输出完成 | succeeded，dispose确认 | 各1 | 各1 |

每场景重复冷恢复不增加HTTP；完整性ok、未结束attempt为0、FK无错误。真实worker子进程用Windows句柄确认退出，Job前窗口401ms，其余记录窗口已退出（0ms）。结果中的worker_gone字段仅在http_sent场景填充，其余以各场景child_gone断言和notes为准，不能把该默认false当作残留。READY窗口证实已完成受控TLS但尚无HTTP/发送标记。探针退出码9为明确模拟父死，不用于正常关闭。

旧失败c965…根遗留PID3576已在核实绝对exe路径和创建时间后停止，证据`%TEMP%/kgm-d2-w3-codex-7byz_ufm/old-failed-probe-cleanup.json`；失败文件保留。最终成功根无残留probe进程。此次清理不触及教师应用或历史数据。

范围比对见基线根`scope-final.json`和`after-sha256.json`：没有删除基线文件；改动限本地AI服务/API/schema/错误、桌面宿主/启动、相应测试和W3探针/文档。ARCHITECTURE、0001–0004迁移、前端、依赖/锁文件保持；既有未提交工作未回退。D1包仍为c6dc19283a24d00a740f2ecbed2cc7159e951f02a37f00636b294b7670369930，W1包仍为6a283bdfc9954c683ac2e86c75762ed99a0961ff7dde47580a55419a5e91d9f4；原教师体验根/exports保留。使用原CPython3.14.7 Windows x64标准GIL及既有依赖，未安装工具/依赖、未改远程、未commit/push。

## 6. 最终缺陷关闭与门槛结论

| 项目 | 最终修复及核查 | 结论 |
| --- | --- | --- |
| R01 输入来源身份 | 适龄依赖包含拆分基准candidate身份、共享来源投影校验；D1旧null保持；任务测试和相关回归通过 | 关闭，W4采用链另验 |
| R02 transport | 保留端点前缀；DNS至TLS预算、全部地址/peer校验、严格HTTP/JSON与诊断限额；真实受控TLS及独立16例通过 | 关闭，G07限定受控网络范围通过 |
| R03 状态/版本/凭据 | 安全重试钉原执行版本，人工重排新generation；当前permit和发送证据决定状态，旧execution不被pending改写；候选与成功原子提交；post-SEND异常保守unknown | 关闭，G05/G06/G08/G10的W3部分通过 |
| R04 执行器屏障 | 同短闸门freeze/SEND、恢复失败闭锁、IPC阻塞受期限监督、保留未确认资源；结果失败只本地重提，不再次联网；定向78项与实际TLS恢复通过 | 关闭，部分帧故障未直接构造，不虚报该专项 |
| R05 API幂等/取消 | 回执先于执行器健康检查；变更提交与pending cancel交接；实际HTTP重放、strict字段、来源/指导阻塞复核通过 | 关闭，W4采用幂等另验 |
| R06 容量 | 提交与领取均计算最终序列化body/IPC上限；转义膨胀拒绝且无部分行/回执 | 关闭 |
| R07 宿主与关闭 | prepare/恢复/监听顺序正确；关闭先持久撤销再收口；DB失败或未确认进程拒关；close回调代次及解冻竞态修复；146桌面/真实spawn宿主用例通过 | 关闭，G13核心通过，真实窗口/睡眠后续 |
| R08 密钥清除 | 清理前flush、只为live钉住执行保留退役凭据；clear-secret后禁止新的发送标记；独立3例复核通过 | 关闭，W1凭据原结论保持 |
| R09 证据有效性/冻结 | 修正无实际worker的假通过和错误断言；真实IPC验证；共享早期spawn失败退出；12场景159断言、仓外包/源码同源通过 | 关闭，G09及W3最小冻结门槛通过 |

G15手工降级由原D1保存/重启/导出回归、无AI手工保存与prepare_export以及AI阻塞API证据共同支持；不声称本轮重新人工查看Word。W3需交付的持久任务、输入投影、单在途执行器、受控transport、有限重试、核心关闭恢复和最小冻结包均已满足本轮工程核查。

## 7. 最终工程结论：W3通过，停在W3

W3在当前Windows 11开发机、合成SQLite/凭据和本机受控TLS环境工程通过。实现结果见[W3实现记录](desktop-d2-w3-result.md)。总回归420项、最后核心定向78项、最终桌面146项和冻结12场景159断言分列，不相加为不重复总数。全过程只有用户授权的OpenCode编码模型调用，没有应用真实AI调用或发布。

下一工作包是W4候选读取/预览/原子采用，包括三类严格编辑schema、拆分基准来源、来源/目标竞争、采用回执及Word保存链；必须沿用本轮投影和许可，不另起网络实现。W4尚未获本轮实施授权，当前不开始编码。W5教师候选/任务/关闭界面与一次真实睡眠、W6完整D2包同源/实际窗口/Word页验、G17真实供应商及G18教师确认仍待相应授权和证据。干净机器、Win10、WPS、其他DPI/多显示器、发行再现性及WebDAV保持原后续边界；微软拼音已验，不重复或穷举输入法。

原W3执行提示词中的独有决定已归并本记录§1–7和工程规格§4–7；当前提示词仅保留完成状态、接续入口与未授权边界，不新增归档prompt副本。
