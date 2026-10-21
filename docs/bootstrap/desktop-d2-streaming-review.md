# D2 实时思考与等待反馈：Codex独立核查

日期：2026-10-21。状态：**当前Windows 11合成环境工程核查通过，R01–R11关闭；最终交付及边界见§11。§4–10保留缺陷、失败及回修过程，不代表G17／产品／发行通过。**

## 1. 授权、基线与证据

用户已确定应用使用DeepSeek官方API与MiMo标准API，不使用Token Plan／Go；要求思考默认展开、可折叠、真实阶段及已等待时间，并明确开发工具继续沿用Go套餐DeepSeek V4.1 Flash。[设计](../specs/desktop-ai-streaming-progress.md)及[当前交接](../tasks/current.md)为本轮实施范围。无应用真实AI／发布授权，不设计预算限额。

- 当前分支`codex/desktop-v2-foundation`，开始时HEAD为`31a3c9a`；Codex本轮设计及索引文档修改与OpenCode实现分别归属，后者不得回退前者。
- 新证据根：`%TEMP%/kgm-d2-stream-codex-20261021-201112/`。已记录462个已跟踪文件hash及887个受保护旧包／人工资料文件hash；包含此前normal-r01全部交付。后续核对文件集合及字节，不只看声明。
- 20:11直接调用本机已安装OpenCode CLI 2.0.32：同一会话`ses_ead8af71dffeJphI1NOWg4jZgI`，`run --standalone --model opencode-go/deepseek-v4.1-flash --agent build --format json --auto --file docs/tasks/current.md`。完整JSONL／stderr／实际exit及会话导出分别保留，交付后核对新增assistant元数据中的实际模型。
- 本轮按codebase-memory尝试项目与六个已知证据路径覆盖查询，均`Transport closed`；已限定源码fallback核对transport／worker／executor／task投影／前端任务面板与types，未重建索引或做全仓结构审计。
- 原非流式普通包与W1–W6工程结果只作基线，不代替本次流式、断流及进度可见性证据。

## 2. 独立核查重点

1. 核对真实增量接收：最后答案到达前，合成TLS及受控子进程已有思考进度，不能只在最终结果后展示，也不能用一次新AI请求生成说明。
2. 严格分开思考与最终content，直到终止／JSON／任务业务校验和候选原子提交后才可采用；拒绝混入正文、日志、导出或下一次上下文。
3. 检查SSE拆块、中文UTF-8、行／事件结束、心跳、usage、空delta、异常／截断／过大流；保留HTTPS／公网／TLS／framing、1MiB累计及120秒绝对期限。
4. 进度身份绑定当前task／execution／attempt，旧进度或撤销permit后数据不能改新状态。Pipe高频更新不能绕过停止／关闭／总期限；后端缓存有界且只读查询不启动请求。
5. 界面即时等待、计时、默认展开与折叠、纯文本；等待第一段文字仍有反馈。重复点击／丢本地回包／轮询失败／导航重进不换请求ID、不新增同类活跃任务；结果不明不自动重发。
6. 独立执行受影响后端／桌面／前端检查；新普通包的入口／归档模块同源、包内前端、保存／Word／冷重启／无AI降级／正常退出。独立合成根、禁dotenv，不使用教师默认库。
7. 核对实际改动范围、模型元数据、旧包和人工文件集合／hash、未验范围；有问题交回原OpenCode修复，Codex不直接写实现或测试。

## 3. 当前结论

§4–10记录独立缺陷、r01失败与回修过程，不代表最终代码仍有相同问题。源码、回归、真实源码窗口、新完整包及模型最终证据已取得，最终状态见§11。不调用应用真实AI、不上传包或发布；真实供应商与教师质量按G17／G18另验。

追加R09（终稿审阅时待关闭；最终见§11）：`drive_w5_ui`新增无条件实时思考DOM断言，但既有`desktop/verify_d2_w5_window.py`的split夹具仍返回非流式JSON，原源码窗口验证入口将不满足该断言。22:33交回同一OpenCode会话，回执`msg_15ee1c6e0001CYgsaxp2WZSEYp`；仅最小修复相关验证入口及预期注册表，保留真实断言，不改生产期限／流程。最终需独立复跑源码窗口；仅脚本修改不要求重建同源的r01生产包。

## 4. 实施中预审探针（待最终代码复核）

独立进程直接调用当前增量解析器与worker帧编码，无网络／数据库／业务任务；结果保存在证据根`preliminary-parser-probes.json`，当时transport文件SHA-256为`be46bb4e82565d7011ca325ad915f814da13c4bf14c3f7f26cc15d78635fc06b`。当前代码仍在修改，下列是该快照的复现，不提前判定最终交付缺陷：

- 只有content与`[DONE]`、没有正常`finish_reason=stop`时，解析器仍返回success，未保留原正常结束检查。
- 已有stop后接不完整UTF-8尾字节，仍返回success，未完成增量decoder的终态检查。
- 同一合法多data行SSE事件整块输入成功；在CRLF中间拆块后变成output_invalid／stream_invalid，说明换行归一化依赖块边界。
- 单progress帧含8000个中文字符时，worker不是发progress，而替换成`result/provider_error/frame_too_large`；按字符切分未保证16KiB序列化帧上限。

最终交付后重跑这些探针；若仍存在，交回同一OpenCode修复并补有意义的回归测试，不由Codex改实现／测试。

前端预审另外发现待终稿复核的状态一致性风险：只对live任务取进度，终态后保留的旧thinking快照可能继续显示“正在思考”并累加等待；`progressFor`直接返回旧task缓存，未先核对新execution；无快照时每次渲染重设计时起点，可能一直显示0秒。需以当前持久任务状态／execution／attempt为准更新阶段，保留文字不等于保留旧运行状态，并补完成／失败／重试及进度查询失败的组件验证。

另一个独立framing探针保存在`preliminary-framing-probe.json`：HTTP声明Content-Length=9999，实际只有完整stop＋DONE的短SSE正文，当前send仍返回success（仅发一次）。流式分支提前返回，绕过原HTTP完整长度检查。终稿须验证HTTP framing完整性，短体／断流按发送证据处理，不将未完成传输冒充确定响应。

后端临时投影也需终稿核对：`ai_progress.finish`在业务校验／持久成功之前按transport success记completed，API不结合持久任务终态，可能将随后schema失败显示为“已收到结果”；终态elapsed仍用now-start，刷新后会增长；validating等纯本地进度也更新last_data_ticks，混淆实际收到供应商数据的时间。

独立投影探针`preliminary-progress-projection-probe.json`仅在单独进程中替换只读任务投影并操作合成内存缓存，不建库／任务／网络：持久状态设为failed，API仍返回completed；两次时钟值对应elapsed 10000→20000，终态未固定；只有本地validating也写入last_data_ticks，三项均复现。

包验证预审：目前新增`--stream`只把完整SSE bytes一次性返回，并在w6-resources轮询临时缓存；该证据不能单独证明冻结窗口在最终答案前显示了思考。须有受控延迟的分段TLS响应，并在真实包内任务面板核对最终结果前的可见文字／阶段、折叠与请求次数，不能只据最终缓存或布尔标志宣布“包内实时显示通过”。

## 5. 首轮回修要求（当时未关闭，最终状态见§11）

首轮实现者自测后端492项、桌面204项、前端typecheck／84项D2组件及首个streaming候选包不替代独立核查；上述独立复现仍未关闭。OpenCode应逐项最小修复及补回归，Codex再次核查，不把它们降为未验后直接交付：

| 编号 | 必须修复／证明的行为 |
| --- | --- |
| R01 流正常结束 | `[DONE]`不能代替`finish_reason=stop`；始终为单一正常文本choice，拒绝不同choice混入同一答案及stop后继续拼正文。若兼容stop＋无DONE的正常HTTP EOF，须有完整framing证据，不能靠半段字节推断完成。补缺stop／异常finish等真实解析反例。 |
| R02 UTF-8终态 | 完成增量decoder的final检查；不完整多字节尾巴、终止事件旁的非法UTF-8不得被忽略成success。 |
| R03 SSE换行跨块 | 在块间保留CR／CRLF语义，单CR、CRLF中间拆块、多data行、LF、中文UTF-8拆块与事件边界结果应一致。整块成功／拆块失败的独立反例见§4。 |
| R04 中文有界IPC | 按实际JSON UTF-8编码长度切分progress帧（包括转义与metadata），不能按8000字符估字节。大中文／emoji／引号反斜线增量不得被`_send`替换为provider_error result；单帧不越16KiB，全部文字或明确展示截断语义正确。 |
| R05 HTTP完整性与断流 | SSE必须仍验证Content-Length／chunked完整结束及总量，不能遇DONE提前绕过。完整stop＋DONE但短声明体、缺终止chunk等不能成功，未完成传输按已发送／结果不明处理，不补发、不当成已收到完整输出的普通schema失败。修正现有short-body测试对确定失败的错误预期。 |
| R06 界面阶段／身份／计时 | 持久成功／失败／未知之后不继续显示thinking或累加等待；最终缓存可读一次或按任务状态收口，保留文字不保留旧运行状态。重试／新execution／新attempt立即丢弃旧阶段与seq比较基准；不接纳旧attempt；进度缺失／GET失败仍有稳定计时起点。pending待调度、claimed准备连接、dispatching等待服务的文案与事实一致，不一直写“正在提交”。补这些组件行为测试。 |
| R07 进度元数据真实性 | transport success还不是业务校验／持久成功，API阶段须以当前持久任务及当前execution／attempt为准，schema失败不能投影completed。终态elapsed固定在实际结束时，晚查询不增长；last_data_age只根据实际供应商数据更新，纯本地validating不冒充新网络数据；真实心跳可更新数据时间但不伪造思考／生成。 |
| R08 冻结窗口实际进度 | 给受控TLS服务加入可验证的延迟分段，真实普通包窗口在最终响应前已有思考文字／正确阶段、默认展开及折叠；反复点击／查询／折叠不新增请求；成功后阶段收口。需要DOM实际断言与请求计数，不能只在完整响应结束后检查backend cache。包的保存／Word／重启／降级／退出仍须通过。 |

先修源码与专项，完成受影响全套回归后再构建。首个`build/desktop-d2-streaming/`候选包及其失败／自测材料保留，回修包使用新的`build/desktop-d2-streaming-r01/`或未占用专属目录，防止核查字节被覆盖。仍不改数据库／迁移／依赖，不调用应用真实AI，不发布；新增测试fixture／自测分支必须遵守显式合成根和普通模式无私网注入的既有保护。

后续实施者首轮自行修了旧execution显示及中文分段，另建`desktop-d2-streaming-r2`，但上述协议与窗口缺项仍未关闭。Codex通过已安装CLI的本地OpenAPI核实`session.prompt`支持持久steer及`resume:false`后，将本节完整清单投给**同一会话**，未另起循环／实现者：receipt `msg_15e9369f5001paaLoeysTmtqKI`，实际CLI exit0，request／response／stderr／exit分别为证据根`opencode-steer-r01-*`。投递成功不等于已修复，后续逐项核对实际代码与验证。

首轮保护复核：887个已登记文件hash均一致；四个历史完整包的728文件集合无缺失／新增。此证据不扩写成全部构建中间产物或默认教师库的全目录hash审计；自动验证按显式合成根隔离。首个streaming候选182文件另留修前hash，以便后续确认未覆盖。

## 6. 回修中独立复验

`repair-protocol-probes1.json`对transport SHA-256 `aa300853d7dfb449766a14ab40f3502f87e6606582f1de42804036a30a646372`前后稳定的代码，经公开send及合成内存HTTP输入复核：正常流成功、缺stop拒绝、UTF-8尾字节拒绝、多data行CRLF整块／逐字节均成功；短Content-Length及缺终止chunk均unknown，每例只发送一次。R02／R03／R05原反例在此快照的协议层已修正，最终仍须与终稿及新包核对。

R01仍有一个子项未关闭：先收到正常delta.content=`{}`，随后收到`delta`缺失、`finish_reason=stop`且`message={tool_calls:[{id:tool1}]}`的帧，再DONE，当前仍success。兼容完整message的分支在没有字符串content时直接因stop返回，漏掉对message中的非空tool_calls／function_call／refusal检查。应对这些字段同等拒绝，补真实解析回归，不重写其余已修协议。该反例没有网络／数据库／实际模型调用。

R06回修源码仍需收口三处（源码分析，尚未写成DOM已复现）：

1. `progressFor`仅在有currentExecution时创建等待展示，实际新登记的pending任务`execution:null`反而没有进度区；在另一任务后排队时应同样显示稳定等待反馈，不能只测试带历史execution的pending fixture。
2. 终态直接把旧快照phase改为completed／failed，却不再取最终快照；elapsed从“旧elapsed＋本地已等时间”退回旧elapsed。若后续进度GET一直失败，任务完成时计时可能从已显示的几十秒归零。应对已知live→terminal的任务取一次只读最终快照，或至少冻结已显示的等待时间；保留文字、停计时与真实结束值分别落实，不轮询全部历史。
3. `fetchProgress`请求前保存currentAttempt，await后只复核当前execution，未再复核`current.execution.attempt_no`；同一execution切到attempt2后，迟到的attempt1响应仍可能覆盖已存attempt2快照（虽随后展示函数会因不匹配隐藏）。须在写cache前按最新task attempt复核，并补延迟Promise的组件反例，确保旧数据不能抹掉新文字。

R01补充与R06补充已分别以`resume:false`投递同一会话，receipt为`msg_15eac1d5e001hQM3gJLpNNylD5`、`msg_15eb315c7001dW7tLvdvGS96FI`；各自CLI实际exit0，证据根`opencode-steer-r01-extra-*`／`opencode-steer-r06-extra-*`保留。

R07独立函数投影复验见`repair-progress-projection1.json`：隔离进程中的合成缓存／只读任务依赖替身，状态failed投影failed；把真实尝试结束tick设为开始＋1500ms，之后两次查询时钟分别开始＋10000／20000ms，elapsed均1500；仅本地validating不记录网络数据。此快照通过，源码前后hash一致：`ai_progress.py`为`159e58a46c104c79686382929865686b8bc0933b79dae0277a2e0ef20eefc4b0`，`api.py`为`8f99fda97196ad6ce1564720deb0b9a47fe78a82e92aa2419c48f7600b424896`。这不冒充HTTP鉴权、实际供应商或完整任务集成证明，终稿仍核对同源与相关真实合成链。

## 7. 回修整套回归失败／超时记录

实现者`stream_r01_local_full.log`出现两个F；其shell实际返回`Command exceeded timeout of 1800000 ms`，没有实际unittest exit0／完整结果，因此这轮**失败且未完成，不能记510项通过**。Codex已保存当时部分日志为证据根`opencode-r01-local-timeout-snapshot.log`，桌面204项通过快照另存`opencode-r01-desktop-snapshot.log`；原命令及timeout在CLI JSONL中保留。

Codex只枚举测试、不执行，用该轮33项stream专项的已完成名称重建运行时510项顺序，两个F的零基位置300／302对应候选：`IpcBlockingTests.test_child_never_reading_bootstrap_terminates_within_budget`与`LateAndDegradationTests.test_late_response_after_deadline_rejected`（均在`tests.local.test_d2_w3_executor`）。见`failure-position-reconstructed.json`；映射仍须用带名称实际运行确认，不能只据点号宣布根因。

运行期间观察到测试相关高CPU进程，之后PID已消失；未对无法证明归属的进程采取操作。下一步先由OpenCode用verbose／failfast及必要的限时栈诊断定位失败和超时、检查自己测试的清理，不盲目扩大生产期限或降低旧保护断言。修复后恢复适当专项和完整回归，保留全部失败材料；该事项不重开用户已停止追测的G13跨120秒睡眠或R02／R03历史事件。

## 8. r01修前独立核查与候选身份

本节为r01修前独立证据，完整包当时失败及R10／R11见§9–10，R09源码窗口当时也待完成；最终交付见§11，不将下表写成最终通过。全部操作使用独立合成数据／LOCALAPPDATA、`APP_DISABLE_DOTENV=1`，CPython 3.14.7（desktop/.venv-d1）；不调用应用真实供应商，不使用默认教师库。

| Codex独立核查 | 结果与证据（§1证据根内） |
| --- | --- |
| 后端local完整回归 | `unittest discover -v -f -s tests/local -t .`：**511项／473.880秒／exit0**；`independent-backend-final.log`及实际exit。包括34项流式专项、真实spawn／Job＋TLS最终答案前进度、发送后断流／停止不补发、缓存／API投影及既有候选／原子采用／迁移／降级保护。 |
| 桌面完整回归 | **204 passed／8.28秒／exit0**；`independent-desktop-final.*`，2条既有第三方弃用警告。 |
| 前端 | typecheck、D1纯逻辑、60项D1异步组件、92项D2组件均exit0，`independent-frontend-*`。覆盖pending无execution、终态停计时不回退、失败收尾GET、同execution新attempt及旧Promise迟到不覆盖、默认展开／折叠和既有幂等／草稿／关闭保护。 |
| 独立协议反例 | `independent-protocol-final.json`：最终transport SHA fe5c27f5…稳定；正常流成功，缺stop／UTF-8残尾／完整message中三类禁用字段拒绝，多data行CRLF整块与逐字节均成功，短Content-Length／缺终止chunk为unknown，**超过1MiB的无长度SSE为body_too_large**；各例send=1。多字节／转义／控制字符真实编码帧均≤16KiB。R01–R05原反例已修复。 |
| API元数据 | §6独立R07投影证据对应的ai_progress／api文件hash与终稿完全一致；完整回归重验持久终态投影、固定elapsed、本地validating不刷新网络时钟、真实heartbeat及旧attempt拒绝。 |
| 前端构建与包 | 独立`npm run build:d1 -- --outDir <全新证据目录>`实际exit0，三个新资源逐字节等于r01构建与包内前端；`independent-frontend-match.json`。仅既有构建体积提示，未为此改栈／拆包。 |
| 完整归档同源 | `independent-archive-final.json`：直接读EXE的CArchive／PYZ，所有50个选定归档模块（完整app包／主机模块与同源helper）及真实`d1_main`入口code object均与当前源码结构指纹一致；含新增ai_progress，无人工入口。不只核对运行时已加载子集。 |
| 实施模型与结束 | 本轮新增**287条assistant**全部且仅`opencode-go/deepseek-v4.1-flash#default`；末条finish=stop、session outcome=succeeded，CLI实际exit0；`model-audit-final.json`／最终export保留。所有回修均同一会话，没有另起实现者。 |
| 保护材料与包清单 | `independent-protected-package-final.json`：887个已登记保护文件hash保持；四个旧完整包728文件集合无缺失／新增；首个未通过streaming候选182文件hash保持。最终r01包182文件逐项等于实现者清单。范围不扩写为默认教师库／所有中间产物的全树hash审计。 |

§7两项候选测试单独通过、stream专项后接executor48项通过，实现者另有两轮511项完整exit0，Codex上述独立verbose／failfast完整511项也通过。未修改这两项旧断言或放宽生产期限。前次超时／两个F仍保留为失败证据；并发高负载是可疑因素，**没有具名失败堆栈证明其唯一根因**，不把孤立通过写成已定位／已修复全部时序问题。

交付目录为`build/desktop-d2-streaming-r01/package/KGNext-D2Verify/`，完整182文件目录运行，说明为同根`RUN.md`／`package_hashes.json`。EXE **686e6e8b586d96c0d35cbcdccb0c51dc371aefd69f405cad076d343aa7d45429**（15,065,196字节）；Windows相对路径清单 **e1d8f3d7a656403b592cb7a59592dff753206c4efa8edbf97d838d095472193d**。旧normal-r01、普通／人工包、失败候选及现场保留。

应用真实AI调用**0次**，未发布／安装升级／WebDAV／改旧远程。后续G17的准确服务型号、顺序与真实调用授权待确定，不设计预算。真实首字延迟、服务差异、usage、教师质量／G18、Word逐页／WPS、Win10、其他DPI／多显示器、干净机器／发行再现性仍未验。未实等120秒整段流超时，原绝对期限及受控超时／断流保护已查；不重开G13／R02／R03，也不将这些历史事项写成已验证／已修复。

## 9. 终稿追加R10：人工重试排队沿用历史进度（已关闭，见§11）

独立源码确认`ai_task_service._requeue`（873–912行）只将task置pending并更新task元数据，保留历史current_execution_id和attempt，直到新claim才建立新execution。当前API只核对这两个身份，会将历史ended／unknown快照原样投影；`AiTaskPanel.progressFor`同样先命中旧cache，pending仍显示旧失败／结果不明、旧思考和旧计时。R06已有的新execution／新attempt反例没有覆盖新claim之前的排队间隙。若另一任务在运行，该间隙可以持续，不只是瞬间显示。

独立函数探针`independent-r10-before.json`已复现：合成持久任务状态pending、旧execution/attempt保留，API仍返回available=true、phase=unknown和旧思考文字。API SHA为8f99fda9…；仅隔离进程替换只读任务依赖及内存缓存，无网络／业务库／真实模型。首轮CLI已exit0后，以同一会话／同一Go Flash启动run2，要求先最小修复及小专项，不与正在进行的r01冻结窗口并发构建。

回修中独立函数复验`independent-r10-api-after.json`通过：API SHA `48f2694f083a2897ce3d20f5fbea090ea9ac9e66e7e14d156c89e100a6c33a3d`前后稳定，重新pending＋旧execution时available=false／waiting／seq0／无旧思考；首次pending无execution如实空等待；新claim／新execution可正常读取新的思考。当时仅证明该快照接口投影；后续前端／窗口与最终包已完成，整个R10关闭见§11。

末轮独立专项已完成：`independent-r10-streaming.log` **35项／4.545秒／exit0**；`independent-r10-desktop.log` **204项／7.35秒／exit0**（2条既有弃用警告）；`independent-frontend-r10-*`的typecheck、D1逻辑／60组件／D2 **94项**与全新前端构建均exit0。两项R10新增函数的名字及对应ok在实际日志中出现，旧92项输出不作为这两项覆盖。16个实现／测试／验证源码快照为`r10-source-before-independent.json`，新包后仍核对稳定性。只对末轮API／前端与自测夹具的小改动追加相关检查，不重复已独立通过的511全local；511是R10前基线，不写成末轮512全套。

静态复核及专项完成后，Codex经同一会话steer允许构建新根`build/desktop-d2-streaming-r10-r11`，回执`msg_15f0bd016001bvvfKF4hx9myXH`；随后通知独立专项均已完成，直接构建／写RUN与结果后停止，不再扩查或重复整包，回执`msg_15f2021dc001o0ouTyYYed2LcH`。源码窗口与完整冻结包由Codex独立执行，未验仍不得写通过。

要求同一OpenCode最小修复API及前端投影，补终态→人工retry/resume后pending（旧execution仍保留）→新claim的API／组件回归，迟到旧GET不恢复旧文字。不得为临时展示改变持久current_execution_id、历史execution或任务重试协议。r01包与§8测试继续保留为修前快照，**不能在R10关闭前宣布最终通过**；新包须另建未占用根，不覆盖r01。

## 10. r01独立整包失败与R11回修记录（已关闭，见§11）

`independent-package-final.json`及实际exit3：固定141项中4项失败，missing／extra空。49个运行模块同源、真实入口归档同源、思考最终答案前DOM／默认展开／折叠、资源两次、G14保存／候选采用／Word／重启、全部G15降级均通过；失败为`w5p_exit_zero`、`w5p_provider_adapt_once`、`w5p_provider_adapt_received`、`w5p_w5_close_stop_and_exit`。受控W5服务实际只收到split=1／other=1，无adapt。任务最终paused/user_stop、无开放attempt，worker与服务退出确认；冻结宿主状态closing、窗口已关闭，但关闭合成判据false，子相位exit3。

完整失败现场为`%TEMP%/opencode/kgm-d2-w6-pkg-366f283e/`，包括w5-ui.json／startup-w5.log／w5-data；不得覆盖或删除。独立运行只用合成环境，无真实供应商。当前事实不能直接判定为生产关闭缺陷或仅夹具竞态；需原OpenCode诊断，不放宽5秒关闭／120秒尝试、弱化provider恰1次或把paused当已发送。

尤其检查W5 live判据是否只看到claimed/dispatching就提前发起停止（这不证明服务端已收到），以及关闭计时／计数使用的真实依据。若需证明在途关闭，应在测试专用供应商与现有窗口自测中建立真实已接收证据再关闭，不新增生产请求或改变教师流程。R10与R11关闭后另建新包；r01的137项通过只作对应修前包证据，不冒充整包141项通过。

追加源码定位：`start_live_task`实际上只等待`liveCount>=1`，连pending都满足；`_verify_w5_close`的最后布尔直接要求最终outcome_unknown。因此本次adapt=0／paused可以统一解释这4项失败，尚未发现另一独立宿主关闭事实失败。R11首次及追加steer回执分别为`msg_15efd32d4001TbHbxTuz5NZxsf`／`msg_15efecd5a001B5EZ4QVhejOKuo`，均同一会话、`resume:false`、实际CLI exit0。要求通过真实供应商回传的SSE中间内容或等效接收证据同步后关闭，不以固定sleep代替，不修改生产关闭逻辑。

## 11. 最终交付：限定合成工程核查通过

OpenCode使用原Go套餐DeepSeek V4.1 Flash完成实现及全部回修；Codex独立核查后，**R01–R11全部关闭，当前Windows 11合成环境工程通过**。没有剩余本轮编码或构建任务。r01独立137/141失败、未通过候选、超时日志和§4–10原始发现保留；不把它们改写成当时已通过。

| 最终独立证据 | 实际结论 |
| --- | --- |
| 后端与前端 | §8完整local **511项**为R10前基线；末轮API／前端与验证夹具小改后，独立流式／API **35项／4.545秒**、桌面 **204项／7.35秒**、typecheck／D1逻辑／60组件／D2 **94项**及新前端构建均exit0，含两项R10具名回归。没有虚称末轮512项全套。 |
| R10接口及界面 | `independent-r10-api-after.json`及上述具名组件：pending保留历史execution时无旧思考／旧阶段，稳定重新计时，不查询旧进度；迟到旧GET不恢复已隐藏的旧文字，新claim／attempt正常显示新进度。未修改持久执行历史或重试协议。 |
| 源码真实窗口 | `independent-final-source-window.json`：**33项全部true，exit0，missing空**；三类合成provider各1次，适龄实际回传思考可见后再关闭，最终outcome_unknown；默认展开、折叠／展开、草稿／采用／关闭保护通过。R09源码验证入口及R11接收同步已复验，不只看factory。 |
| 新完整冻结包 | `independent-complete-package.json`：**142/142全部true，failed／missing／extra空，实际exit0**。仓外中文／空格／百分号／井号路径副本、资源两次、G14保存／预览编辑／原子采用／Word与同根冷重启、G15未配置／执行器／网络／凭据损坏降级、W5实时思考与关闭全部通过。子相位实际exit均0。 |
| 实际流与请求次数 | W5最终答案前有真实思考DOM，默认展开／折叠／展开均通过；split／other／adapt各**1次**，适龄实际已接收，终态**outcome_unknown**，无开放attempt、worker／服务退出确认。源码窗口也各1次。进度查询／折叠不新增请求，未用缓存完成后的文字冒充实时证据。 |
| 同源与稳定性 | 冻结运行**49个模块**与源一致；另直接读取CArchive／PYZ，完整**50个归档模块及真实d1_main入口**与源码结构指纹一致，含ai_progress，无人工入口。独立新前端3文件与包内逐字节一致；16个实现／测试／验证源码hash在独立检查至最后保持。见`independent-complete-archive.json`／`r10-candidate-pre-window.json`／`complete-stability-protection.json`。 |
| 模型与结束 | 最终会话导出核对本轮新增**336条assistant**全部且仅`opencode-go/deepseek-v4.1-flash#default`，末条finish=stop、outcome=succeeded，两轮CLI实际exit均0；`model-audit-complete.json`。没有另起实现者或换模型；实现、测试和构建脚本均由OpenCode修改，Codex执行独立验证。 |
| 旧材料保护 | 887个已登记文件hash保持；四个旧完整包728文件集合无增／删且字节保持；首个streaming候选182文件保持；失败r01包清单仍e1d8f3d7…，新包清单与验证时一致。所有验证使用显式合成根，不扩写为默认教师库或全部构建中间产物的全树审计。 |

交付为 **`build/desktop-d2-streaming-r10-r11/package/KGNext-D2Verify/`完整182文件目录**，入口仍为`desktop/d1_main.py`，不能只复制EXE。EXE SHA-256 **d0e650e8b572a3a7ca8acf7822a47d1c0eeac607322777a7f79d7492d3cfad14**（15,065,536字节）；Windows相对路径清单SHA-256 **80f15a68f0eedfb82713ae9c74936056f2c8a9314e05afe5d1cc6dd391e0873f**。同根RUN.md／package_hashes.json保留运行说明与逐文件hash。普通交互模式不启用私网、测试CA、合成provider或故障注入，不自动配置或调用供应商。

后端有界临时缓存、前端纯文本显示与候选最终校验分开；没有新增迁移、依赖、一级架构或预算功能。应用运行时准备DeepSeek官方与MiMo标准API；实现工具Go套餐与应用选择分别记录。**应用真实AI调用0次，未发布／安装升级／WebDAV／修改旧远程。** 后续具体型号、顺序与真实调用仍待确定和另获授权，见[G17方案](desktop-d2-g17-acceptance-plan.md)。

本结论不覆盖真实供应商首字／持续响应时延、服务兼容／输出质量／usage、G18教师确认、Word新样本逐页／WPS、Win10、其他DPI／多显示器、干净机器或发行再现性。未实等120秒整段流超时；保留原绝对期限／发送后未知不自动重发规则，不重开G13／R02／R03。§7早期整套失败的唯一根因没有具名堆栈证明，不以本轮通过声称所有环境时序问题已定位或已修复。
