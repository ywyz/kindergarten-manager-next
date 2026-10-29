# D3-U 应用更新：Codex独立核查

> 公开版隐私处理（2026-10-30）：本机用户路径、私有部署地址或联系标识已替换为占位符；原始记录由维护者私下保留，历史日期、结论和产物哈希不因此改变。

更新：2026-10-25。最新状态：**U1–U3在当前Windows 11限定源码／合成环境工程通过，原R01–R07、U2-R01–R07及U3-R01–R03关闭，最终证据见§20。真实冻结更新、发行源／安装与4551仍未验。** 历轮状态按各节当时结论保留。

## 1. 授权、基线和保护边界

用户已审核同意按`docs/tasks/current.md`调用原OpenCode会话，以Go套餐DeepSeek V4.1 Flash实施应用更新，Codex独立审核，不通过交回修复；通过后提交推送，再撰写下一步提示词，待用户审核后继续。此授权替代旧提示词的未派发和禁止提交推送状态；不授权发布、真实AI、签名、新冻结包构建运行或修改系统防护。

分支保持`codex/desktop-v2-foundation`。开工已有8份修改文档及未跟踪的应用更新规格，完整差异和已跟踪文件hash保存于`%TEMP%/kgm-update-codex-20261024-103957/`。保留全部现有修改与独有资料。保护快照只对非凭据文件取hash，不读取真实密钥；旧包、两份真实库与原始失败材料保持。

OpenCode CLI 2.1.2通过`api --standalone GET /api/session/ses_ead8af71dffeJphI1NOWg4jZgI`核对原会话空闲、outcome=succeeded、实际模型`opencode-go/deepseek-v4.1-flash#default`后派发方案轮。使用`run --standalone --session ... --model opencode-go/deepseek-v4.1-flash#default --agent build --format json --auto --file docs/tasks/current.md`；日志、stderr及实际exit分开保留。本轮先交限定文件与工程方案，核定后才接续U1，U1审核后接续U2／U3。OpenCode唯一写实现／测试／迁移／构建验证脚本，Codex不代写实现。

## 2. 核查方法

使用已安装codebase-memory技能，项目`C-Users-yw980-code-kindergarten-manager-next`，索引代次`2026-10-24T02:33:21Z`。桌面宿主／入口／构建相关查询35条已取全。7份候选路径覆盖为`no_recorded_issue`且`metadata_changed`，因此回读限定源码，不将覆盖信号写成完整性证明。既有完整onedir包、关闭代次／保存／AI退出屏障和本地冷迁移是本轮复用基础，不是更新已实现的证据。

真实`KGNext-G17-20261022`数据／凭据、原r03和teacher-talk包不作升级测试。仅独立合成程序、数据、凭据根及受控下载源；失败保留首次现场并停止对应链。4551、签名暂停、冻结包和教师发行体验未验状态保持。

## 3. 当前结论

阶段最新结论见§20：U1–U3限定工程通过；以下是开工方案核定时的判断，历轮失败保留以便核对。

开工方案已收到；核定决定及修正已归入[规格§8](../specs/desktop-application-update.md#8-2026-10-24开工方案核定限定源码合成工程)。小更新器属于现有宿主维护实现细化，不改变模块边界或业务通信，不要求另立ADR。元数据认证与Windows代码签名职责分开；仅允许合成测试身份，不启用正式发行源或真实私钥。

原方案尚需修正PID复用、就绪回执防重放、并行安装、失败现场自动清理及Windows路径别名等约束；由同一OpenCode在U1／U2实现时落实。U1可按修订规格实施；正式发行配置缺失明确属于工程交付边界，不冒充真实在线更新通过。实现者自测、Codex独立执行、真实包及教师体验分别记录。

## 4. U1首轮中途审阅点（待稳定交付后复核，未关闭）

以下来自初稿限定源码，不是独立测试通过或最终缺陷清单；实现者仍在写入。交付后先核对是否已改，再对仍存在项作反例验证及交回修复。

| 编号 | 初稿证据与需要核对的结果 |
| --- | --- |
| R01 | `update_manifest.py`使用普通`json.loads`，重复字段被静默覆盖，`schema_version=True`与1相等；需拒绝重复键／非有限数和bool等错误类型，覆盖实际验签与清单读取 |
| R02 | 解包只比较已resolve路径，暂存祖先重解析点可改变权威根；检查目录条目前提前continue；文件集合遍历跳过所有同名`package_manifest.json`，可能漏掉嵌套额外文件。须检查全部条目和真实受管路径，不能只靠字符串断言 |
| R03 | `parse_signed_manifest`对同版及旧版全部抛错，`UpdateManager`无正常“没有新版”路径；需要签名合法的同版正常结束，旧版仍拒绝，不依赖错误文本判断 |
| R04 | `READ_TIMEOUT`尚未使用，也没有总期限；取消仅在读块前检查，末块读取后可直接进入ready；shutdown仅join2秒，不确认网络线程结束。须验证实际延迟／中断和末块取消，旧结果不能重新放行 |
| R05 | 初始配置验证失败后`check()`仍可执行请求；下载目录创建在异常状态处理外。需以实际调用计数证明非法配置零请求，权限／占用失败呈现明确状态 |
| R06 | frozen身份缺失或损坏静默降为source身份；包内身份未核全部平台／渠道字段；必需资源路径与现有PyInstaller `_internal`布局尚需对齐。应拒绝不确定安装身份，不让合成夹具掩盖真实包布局 |
| R07 | `App.vue::scheduleUpdatePoll`要求更新面板已打开；启动后台check立即返回checking而不打开面板，此后不再取结果，无法提示发现新版。必须在后台检查结束后确实提示新版本，关闭面板不应使在途状态失去核对；覆盖真实SFC异步返回及迟到响应／卸载后回包 |

另核对异常消息脱敏、首次失败材料保留、暂存与数据／凭据路径隔离及签名信任配置不可由页面／环境／CLI覆盖。结果文档有`desktop-ai-engineering.md`相对链接应指向`../specs/`，交付前修正。

## 5. 首轮自测首次失败（不是Codex独立结果）

OpenCode首轮`desktop/.venv-d1/Scripts/python.exe -m pytest tests/test_update_u1.py -q -s`记录为7项中5通过、2失败（7.04秒）。非法ADS路径已被拒绝但错误分类与契约不符；取消用例等待真实下载进度时失败，源码`response.read`尚未返回部分块。原始输出保存在开工证据根`opencode-u1-r01.jsonl`。随后针对两项的调试输出仍失败，部分命令带head／tail管道，其shell返回值不能当pytest实际退出码。实现者仍在修正，不记为交付通过；稳定交付后Codex另行直接执行。

## 6. U1首轮独立核查：不通过

OpenCode首轮CLI实际exit0、声明停止源码写入后，Codex锁定16份源码／测试／包配置并独立验证，前后hash零变化。脱敏完整会话导出exit0、会话idle／succeeded；实现者自测12项Python、4项SFC、94项既有D2组件、typecheck及临时前端构建与独立结论分开。图谱更新代次`2026-10-24T03:21:08Z`，5个关键符号已取全；16份路径均`no_recorded_issue/metadata_changed`，以源码回读补证。

完整脱敏导出增量模型审计为本轮新增127条assistant全部且仅`opencode-go/deepseek-v4.1-flash#default`，最终finish=stop，证据`u1-r01-model-audit.json`。不以50条分页快照冒充完整审计。

独立证据仍位于开工根，以下为Codex实际命令结果：

| 检查 | 实际结果 |
| --- | --- |
| `python -X utf8 -m pytest tests/test_update_u1.py -q --basetemp=<全新独立根>`（cwd desktop，禁dotenv） | exit0，12 passed／8.38秒，无skip |
| `node src/d1/d1.update.test.mjs`（cwd frontend） | exit0，4项；仅覆盖UpdatePanel，不覆盖App启动异步协调 |
| 独立签名元数据／真实ZIP反例 | exit1，5例中4个应拒绝输入被接受：重复信封字段、bool schema_version、异根目录条目、包内arm64身份；嵌套未列名清单文件正确拒绝 |
| Windows真实junction暂存反例 | exit1，`managed-stage`是指向独立`outside-stage`的junction，验证仍接受，并实际将EXE写入outside-stage |
| 真实TLS末块取消确定性交错 | exit1，在真实`read1`返回最后1849字节前调用实际`manager.cancel()`，当时为downloading，最终仍ready；真实字节／摘要／解包均执行，未mock文件成功 |

具体文件为`u1-r01-independent-pytest.log`、`u1-r01-independent-sfc.log`、`u1-r01-counterexamples.log`、`u1-r01-junction.log`和`u1-r01-cancel-last-block.log`。反例只使用各自独立临时根、测试密钥及受控TLS；junction两端均在本次独立证据根内，未触碰教师文件或真实凭据。失败材料保留，不继续U2，不以既有测试通过覆盖反例。

### 6.1 必须交回修复

- **R01开放**：所有网络／包内JSON需严格拒绝重复字段、非有限数、错误bool／数字类型。已独立复现重复信封字段和bool schema被接受；错误字段不能因签名仍有效而放行。
- **R02开放**：受管暂存的原始路径及全部祖先／条目必须拒绝junction、重解析、硬链接／链接绕过；真实junction已写出声明权威根。所有ZIP条目（包含目录）应在同一包根且符合规则，不能在目录分支提前跳过。嵌套同名清单遗漏已修且独立拒绝，保持该保护。
- **R03关闭至当前U1范围**：同版本元数据正常up_to_date，旧版不下载；原12项及限定源码核对通过，不将整个元数据校验一并记为通过。
- **R04开放**：末块取消仍ready已独立复现；还缺实际读取超时、总期限、检查／下载线程关闭确认。取消必须在接收、校验和最终发布ready前复核；关闭不能留下可继续发布结果的旧线程。用真实延迟TLS和确定性屏障验证，不仅延长等待。
- **R05部分修复、仍开放**：无效源已加unconfigured守卫，但须以实际网络调用计数证明0；下载目录创建／占用／权限失败仍在状态处理外。须有明确失败、可重试状态及完整路径隔离检查。每次验证采用全新根，禁止复用`rm -rf`／pytest basetemp清除首次失败根。
- **R06开放**：包内arm64而外层windows/x64仍通过已独立复现；frozen身份缺损静默source回退、`manifest.executable`必须存在并与稳定主入口相符、资源应匹配真实PyInstaller `_internal`布局。按真实包布局构造合成目录，不实际构建新冻结包。坏更新配置只禁用更新，不阻塞手工启动。
- **R07开放**：App启动check即时返回checking，但面板未打开导致轮询不启动，无法提示后台发现新版；4项面板SFC未覆盖。须补实际App异步启动→提示、关闭面板后的在途核对、请求代次／迟到回包和卸载后不再应用状态／启动定时器。后台失败保持手工可用。

修复由同一OpenCode Go Flash完成，不由Codex改实现；先补能复现当前错误的回归，再修复并直接执行相关检查。补受影响关闭／保存／AI屏障和前端回归，失败先停对应链保留现场。交付停止写入后Codex再独立审阅，U1通过才继续U2。真实发行源、冻结包、4551、教师体验及正式发行均仍未验。

## 7. U1第二轮独立复核：原反例已修，剩余项不通过

OpenCode第二轮exit0并声明停止写入，完整脱敏会话导出exit0；累计新增245条assistant全部为指定Go Flash default、finish=stop。近期编辑仅报告期间，Codex先对17份源码取hash复核；与最终交付比对零变化。以下结果不混同实现者22项Python／8项SFC／94项组件／typecheck／临时前端自测。

### 7.1 已独立确认

- `u1-r02-counterexamples.log`：重复信封字段、bool schema、嵌套未列清单、异根目录、包内arm64等5例全部正确拒绝，exit0；按真实`_internal`布局构造。
- `u1-r02-junction.log`：真实junction被拒绝为`UPDATE_STAGING_UNSAFE`，outside根实际文件数0，exit0。
- `u1-r02-cancel-last-block.log`：实际TLS最后1999字节返回前调用真实cancel，最终cancelled，exit0。
- `u1-r02-independent-sfc.log`：8项独立通过，包含实际App启动后台提示、关闭面板后在途核对、卸载／迟到响应，exit0。R07关闭。
- R01、R02原反例、R03及R05非法源零调用／目录失败部分保持已修；不宣称全部Windows权限或路径组合均已穷尽。

### 7.2 本轮首次失败与诊断

`u1-r02-independent-pytest.log`直接执行22项，20通过、2失败，13.14秒、exit1，现场未删除。

1. 重复包内清单用例在深层独立根先遇到WinError206（路径过长），被归入通用下载失败，未到达预期清单校验。直接定位日志`u1-r02-long-root-diagnosis.log`为`target.parent.mkdir`失败；仅该用例在全新短根定点执行，exit0／1 passed（`u1-r02-duplicate-short-root.log`）。不误称严格JSON失效，也不将长路径问题记为已修；后续完整验证使用明确短合成根，长路径单列边界。
2. 取消用例硬断言`cancel()`必须瞬间返回downloading，实际已返回正确终态cancelled；这是合法异步时序，需改为对最终cancelled、文件清理及线程状态作确定性验证。不能接受ready或failed作为通过，也不能删去最终保护。

### 7.3 剩余阻塞项（只交回这些）

- **R04仍开放**：`u1-r02-lifecycle-probes.log`使用真实延迟TLS，进行中检查时调用shutdown，返回True但状态仍被旧检查发布为available。检查连接未纳入关闭，关闭后仍可重新check；需关闭代次／状态与实际连接中止，禁止关闭后的所有迟到发布及新操作。总期限0.1秒、读取超时2秒、响应中途停顿0.8秒时，实际0.841秒才返回超时；需将剩余总期限落实到实际阻塞读取，不只在返回后看时钟。运行时／安装准备必须消费关闭确认。补相应有效回归及上面的取消测试时序修正。
- **R05仍开放（隔离部分）**：`build_runtime`未向UpdateManager提供实际数据／凭据根，Manager也未校验暂存与其相同、互为祖先或别名的重叠。当前只检查链接／创建异常，不能据此声称已落实数据根分离。补运行时真实根绑定及下载前隔离核对；合成哨兵文件／库hash不变、重叠根零下载或写入，不读取密钥。该要求来自原规格数据保护，不引入新产品流程。
- **R06仍开放（当前身份语义）**：同一生命周期探针将当前身份JSON的app_id改为another-application、arch改为arm64，`require_packaged=True`仍返回有效AppIdentity。缺损／坏JSON拒绝已修，但仍需严格核对固定应用／渠道／平台／架构／包格式、有效SemVer／UUID／Python／数据库revision等语义；无效身份明确禁用更新且手工可用，不伪装source。目标包内身份原反例已修，保持。

`u1-r02-scan-denial.log`另做目录扫描故障注入，当前整体包校验正确拒绝未列额外文件，保留该结果，不将辅助遍历单一分支当作完整权限审计。每次使用独立新根，不清除首次失败；仅补上述剩余项及相关验证后再交回，不重开已关闭项或提前U2。

## 8. U1第三轮独立复核：仅R04关闭连接响应期限未通过

OpenCode第三轮exit0并停止写入。完整脱敏导出exit0，累计301条新增assistant全部且仅指定Go Flash default，finish=stop／succeeded。Codex近期仅报告编辑时先锁定17份源码复核，最终交付hash零变化。实现者首次24项自测的两项失败完整另存`u1-r03-first-pytest-failure.log`，随后修正；不覆盖首次现场。

### 8.1 独立通过范围

| 检查 | 实际结果 |
| --- | --- |
| U1 Python，新短合成根 | exit0，24 passed／12.60秒，无skip，`u1-r03-independent-pytest.log` |
| 更新SFC与TypeScript | exit0，8项SFC及typecheck，`u1-r03-independent-sfc.log`与typecheck日志 |
| 宿主关闭／原生保存／AI退出屏障／无AI降级／H2保护 | exit0，88 passed／4.73秒，`u1-r03-independent-host-corrected.log`；首次命令的basetemp参数拼接错误exit4未运行测试，已更正，不归因产品缺陷 |
| 真实延迟TLS检查中shutdown | 返回True，关闭后状态closed，再check仍closed，旧检查不发布available |
| 当前身份正负例 | 合法身份接受；another-application、arm64和DB revision不符均拒绝；生产使用runtime实际revision校验 |
| 暂存／实际数据与凭据根隔离 | `u1-r03-root-isolation.log`：实际受控TLS元数据检查后，同根、数据／凭据后代和二者祖先5种布局均`UPDATE_STAGING_OVERLAP`，包请求0、暂存目录未创建、真实合成SQLite及凭据哨兵hash不变；独立分离布局ready、1次包请求、哨兵不变 |

R05／R06在上述范围关闭；R01／R02原反例／R03／R07保持。正常metadata None渠道状态不是隔离证明：`u1-r03-lifecycle-probes.log`早期3个离线重叠观察只说明未配置短路，随后专门用配置有效的真实TLS完成上表隔离证明，不混用。

### 8.2 唯一剩余阻塞：R04的Connection: close分支

`u1-r03-lifecycle-probes.log`使用实际TLS，`read_timeout=2`、`total_timeout=0.1`：keep-alive响应约0.126秒正确超时；相同中途停顿但带`Connection: close`的包响应约0.846秒才失败，未落实总期限。`u1-r03-metadata-close-deadline.log`进一步给元数据分段响应加同一关闭头，0.861秒后竟进入available（exit1），不是仅报错耗时偏差。

原因来自实际`HTTPConnection.getresponse()`的关闭连接响应处理：此后`conn.sock`可已为None，响应文件仍持有实际读取socket。当前代码只对`conn.sock`设置剩余timeout／关闭它，无法约束该实际阻塞读取；`_read_exact`整块读取后也缺少期限复核。不能用keep-alive单一路径的通过关闭本项。

仅修这一分支：持有并约束实际连接／响应读取socket及生命周期，检查和下载均需在连接、响应头／正文各阶段按剩余总期限限时，关闭／取消能中止实际读取，迟到完整元数据不能进入available。补`Connection: close`与正常持久连接、部分正文延迟／分段滴流、关闭／取消交错的实际TLS回归。不要只增加sleep或放宽超时断言，不重做已通过模块，不提前U2；直接有效验证后简要更新同一result并停止写入。阶段源码与合成工程、正式发行源／新冻结包／教师体验边界不变。

## 9. R04第四轮中途定点复核：长停顿已修，持续滴流仍越过期限

本项对12:34左右的17文件hash快照验证，前后零变化；OpenCode仍未正式交付，后续如源码变化需重新核对。`u1-r04-metadata-deadline.log`使用实际受控TLS及完整合法签名元数据、`read_timeout=2/total_timeout=0.1`：

- `Connection: close`，响应头＋前10字节后停顿0.8秒：约0.123秒正确失败。
- 同关闭头，合法元数据平均分为20片，每后续片延迟0.04秒：约0.820秒才失败。
- 同样20片持续滴流但keep-alive头：约0.799秒才失败。

均实际1次请求。虽已避免迟到元数据进入available，但仍未在总期限内中止读取，反例exit1。`_read_exact`仍调用`response.read(剩余长度)`，该内部缓冲读取可通过持续小片到达反复重置socket超时，外层循环直到完整响应才获得控制；只在末尾看时钟不能落实总期限。应采用能逐段返回的读取／等价真正总期限约束，并对每片按剩余时间限时；补上述真实20片／0.04秒滴流回归，不能将期限断言放宽到整个响应自然结束。此为§8.2已要求的分段／滴流场景，不扩展产品范围。

此外，独立完整`npm run test:d1`整组exit0，包含纯逻辑及60项D1组件、94项W5、22项历史、8项更新组件检查（不虚构纯逻辑计数）；日志`u1-independent-frontend-regression.log`。前端未再变化时不重复全跑。

`u1-r04-io-lifecycle.log`又对相同未变源码实测关闭头下的部分正文：进入实际response读取后调用shutdown约0.798秒才返回True／closed，下载收到64字节后cancel约0.819秒才cancelled且清理；两者均等到服务端0.8秒等待自然结束。完整正常包仍ready，未把所有下载一概拒绝。源代码按`(response, sock, conn)`依次close，先关闭缓冲响应文件会等读取锁，尚未实际中断底层socket；应先真正中断socket再关闭响应对象并确认线程。验证应在服务端余块尚被屏障扣住时确认取消／关闭完成，不能用等待服务端自然结束冒充中止。此仍属R04实际IO生命周期要求。

第四轮随后正式exit0并停止写入，最终17文件hash仍零变化，故上述反例适用于正式交付。实现者26项Python／8项SFC／94项组件／typecheck及临时前端构建自测通过，仅作为其自测范围，不覆盖本节失败。`u1-r04-server-barrier.log`进一步用真实TLS生成器＋Event扣住余块：取消与shutdown在余块未释放时均不能返回，释放后才分别cancelled／closed（exit1）；排除仅凭延迟秒数推测。只交回逐段元数据读取和真正中断底层IO两点，不重开其余模块。后续实现者可仅提供命令、exit、数量和停止写入声明，由Codex依据原始日志归并本次结果文档，减少报告编辑往返；实现／测试／构建脚本仍由原OpenCode唯一写入。

## 10. U1第五轮独立复核：总期限已修，正文读取中取消／关闭仍不通过

第五轮exit0、停止写入；完整脱敏导出累计354条新增assistant全部且仅指定Go Flash default，finish=stop／succeeded。17份源码验证前后hash零变化。独立`u1-r05-independent-pytest.log`为28 passed／14.84秒、exit0，无skip。实际签名元数据20片／每0.04秒滴流的close与keep-alive、前10字节后长停顿三例均约0.123秒失败为`UPDATE_DOWNLOAD_TIMEOUT`，每例实际1次请求，`u1-r05-metadata-deadline.log` exit0。R04总期限子项在该范围通过。

唯一阻塞是正文已进入阻塞读取后的实际IO中止。`u1-r05-server-barrier.log`使用实际TLS生成器，在响应头及前64字节后以Event扣住余块；调用前确认active_response，取消还确认downloaded>0。read_timeout=10、total_timeout=20，API独立线程在服务端屏障仍扣住的1秒内均不能返回，释放后才closed／cancelled，exit1。不能将服务端自然结束或读取超时当作主动中止。

`u1-r05-blocked-stack.log`在屏障仍扣住时取得真实线程栈：shutdown停在`_close_io→HTTPResponse.close→_close_conn`，工作线程仍在`_read_exact→HTTPResponse.read1→SSLSocket.read`。调整close次序和先调用shutdown仍未充分中断此生命周期；不能凭此推断所有socket.shutdown都抛错。当前BarrierTlsServer只等待服务端发送首块的事件就立即取消，尚未确认客户端解析响应头／消费首块／进入下一次读取，会提前命中另一个时序，因此28项通过没有覆盖本反例。仅交回这一准确分支及有效回归，不重开已通过项，不进入U2；不要求重跑未变前端或编辑报告表格。

## 11. U1第六轮：回归断言写反，R04仍未通过

OpenCode第六轮exit0并停止写入，自报30项通过；`u1-r05-first-red.log`实际也是2项通过，不能称为复现失败。新增两项测试在服务端屏障扣住时断言API线程`is_alive()`，要求错误阻塞行为继续存在，与本轮验收目标相反。新增`_interrupt_socket`调用`SSLSocket.dup()`，但当前Python3.14.7标准库该方法明确抛出NotImplementedError，异常吞掉后未实现该分支中止；不接受这一修复说明。

Codex在停止写入后锁定17份源码，独立`u1-r06-independent-server-barrier.log` exit1：元数据正文shutdown及下载消费首块后cancel，API在1秒内均未返回，网络线程仍活，服务端release始终false；释放后才结束。验证前后源码hash零变化。只交回正确的正向回归断言与实际底层socket中止，不进入U2；不重跑已无变化的前端或其余合格场景。

## 12. U1最终限定工程结论：通过，接续U2

第七轮exit0并停止写入；实现者先将反向断言纠正，`u1-r06-corrected-first-red.log`实际2 failed／2.80秒，再修复为socket自身`_real_close()`关闭所持句柄并置fd=-1，未构造SSL副本或raw fd重复close。其定点2项及完整30项自测分别通过；首次失败保留。该私有标准库路径限定当前CPython3.14.7／Windows11验证，未来运行时变化须复核，不宣称跨平台通过。

Codex最终独立结果：

| 检查 | 证据与结果 |
| --- | --- |
| 当前U1全组 | `u1-r07-independent-pytest.log`，exit0，30 passed／9.76秒、无skip；全新短根`%TEMP%/kgmu-r7-e92bc984ca95` |
| 正文实际阻塞IO | `u1-r07-independent-server-barrier.log`，exit0；元数据shutdown约0.0011秒closed、包正文cancel约0.0061秒cancelled；两者API已返回、网络线程已退出时服务端release仍false；同真实TLS正常完整包ready |
| 源码稳定与模型 | 17份源码验证前后hash零变化；完整脱敏导出exit0，累计400条新增assistant全部且仅`opencode-go/deepseek-v4.1-flash#default`，finish=stop、session idle／succeeded |

R04在上述范围关闭；R01／R02原反例／R03／R05／R06／R07保持已关闭。此前独立8项SFC、88项宿主及完整前端回归在未变源码上继续有效，不重复全跑。总期限三例约0.123秒通过，路径／严格元数据／身份／真实数据根隔离及末块取消等证据见§7–10。U1通过只涵盖发现、下载及可信包状态，不等于完整应用更新通过。

依用户本轮授权，接续同一OpenCode U2，不另求确认。U2／U3尚未实现；真实发行URL／公钥、冻结构建／安装、SAC4551、教师体验与发行仍未验。独立短根通过不代表WinError206长路径已修。真实数据／凭据／旧包保护边界不变。

## 13. U2实现中定点审阅（未交付，待源码稳定复核）

图谱更新代次`2026-10-24T05:18:14Z`，新`update_process`40条符号已取全，路径覆盖`no_recorded_issue/metadata_changed`，回读源码；这不是独立测试通过。当前仅记录需在正式交付复核的问题，不能在实现者仍修改时预填最终缺陷或通过：

- `open_verified_process`把OpenProcess失败／读取身份失败统一返回None，`wait_for_process_exit`把None直接当已退出；`process_matches`也可能把无法确认当不存活。须区分确认死亡／PID已复用与AccessDenied、身份读取失败等未知，未知必须禁止切换或回退。待稳定后按真实调用分支构造反例，不以查询失败证明进程已死。
- 初稿`FILE_GENERIC_READ=0x00100000`、`FILE_GENERIC_WRITE=0x00040000`实际是SYNCHRONIZE／WRITE_DAC，与读写访问命名不符；核对最终CreateFile访问位、共享模式和实际占用／锁行为，不要求不必要的ACL修改权。

### 13.1 中途独立反例（源码六文件快照未变，交付后复核）

证据仍在开工独立根，`u2-mid-core-before.json`锁定install／helper／process及三个测试夹具，以下验证前后六文件hash零变化。OpenCode仍在写其他文件，尚未正式交付，后续以最终源码是否变化为准。

`u2-mid-counterexamples.log` exit1，在全新短根`%TEMP%/kgmu-u2p-20a08d1518`逐项实测：

1. 向真实进程查询分支注入Win32 AccessDenied，`wait_for_process_exit`竟返回True；未知被当作已退出。
2. 实际连续写first／second两个阶段，最终JSON只保留second一项；`_safe_json`只接受dict而阶段文件写list，后续读被当损坏后重置。
3. 实际LocalRuntime已prepare，但没有启动服务／页面或加载目标应用身份，ReadyReceiptWriter接受合法回显并声称0.2.0就绪；service_ready硬编码，身份取自plan而非当前包。
4. 修改已保存计划使app／exe越出声明的install_root，并带任意new_app_command，load_plan仍接受；构造时test_only检查不能替代helper重读后的产品路径／命令／信任边界。
5. 实际Coordinator绑定关闭后，再次prepare被接受，生成另一plan并二次调用helper启动边界；bound未包含在重复安装守卫内。
6. 新进程身份未能确认（identity=None）时，合法plan字段但错误creation_time／exe的回执仍被helper判success。

`u2-mid-revoked-after-authorized.log` exit1，独立短根`%TEMP%/kgmu-u2a-ff52f07a2d`运行真实旧进程／运行锁、真实helper和新Runtime／服务夹具：等helper阶段已authorized且旧进程仍活，实际把对应授权写成revoked（destroy_failed），再正常停止旧进程。helper exit0并写success，原app旧marker消失、备份旧marker存在，而授权最终仍revoked——真实发生了不应发生的切换。首次现场与所有程序／库／凭据哨兵均保留；仅测试专用进程正常收口，无教师进程或真实数据参与。

这些反例不是以mock复制证明安装成功：权限错误为受控注入，其他状态／JSON／计划／实际目录和进程行为按各自观察分开记录。已有常量已在实现者中途改为GENERIC_READ／GENERIC_WRITE，最终复核保持，不把旧草稿问题重复交回。

随后`u2-mid-ordinary-helper-command.log` exit1，在独立短根`%TEMP%/kgmu-u2c-145c69b795`对原签名包不改动，仅改已保存plan的new_app_command为当前测试Python向本根写标记文件。通过普通helper `--plan`入口（无allow-launcher或故障注入开关）运行，真实旧进程正常退出后，helper实际切换程序并执行该命令，标记文件存在；结果仅因没有ready而unknown／INSTALL_PROCESS_EXITED。没有执行任意外部业务或访问真实目录，但证明产品入口与构造时test_only的隔离没有落实到helper读取边界。产品只能执行固定安装目录内经认证的主入口；测试替代启动需显式的专用验证上下文，不能由持久化plan字段决定。

实现者随后自行修正了阶段JSON顺序追加、增加helper布局核对及真实0004→0005／ZIP篡改／缺页面就绪／切换中断／未知revision测试。早期“篡改／回执”用例被旧进程超时提前截断的覆盖不足不直接套在最终测试上；交付后按最终源码和达到的真实阶段复核。布局的部分修正不能覆盖上述普通入口命令执行或授权撤销反例。

## 14. 2026-10-25 U2首轮正式交付独立核查：不通过

用户本日明确要求按既定顺序继续：核对原会话和U2交付、独立核查、剩余问题交回同一会话修复，通过后接续U3。原会话`ses_ead8af71dffeJphI1NOWg4jZgI`经实际CLI API核对为idle／succeeded，模型仍为`opencode-go/deepseek-v4.1-flash#default`；上一轮最终回复已明确停止写入。上一轮脱敏模型审计累计620条新增assistant均为指定模型，finish=stop。

本轮证据根`%TEMP%/kgmu-codex-20261025-a78be6fa/`。`u2-prior-source-comparison.json`将24份当前交付文件逐一与上轮正式交付`u2-r01-final-source.json`比较，changed=0。因此§13真实撤销和普通helper命令执行反例，以及上轮正式`u2-r01-final-counterexamples.log`，对本次交付继续有效；不把中途已修的AccessDenied和顺序追加问题重复列为未修。

图谱代次`2026-10-24T05:50:29Z`，限定名称查询6条全取；8个相关路径均为`no_recorded_issue/metadata_changed`，已回读process／install／helper、宿主相关接线及测试夹具。覆盖信号不作完整性证明。

独立命令在desktop下执行`APP_DISABLE_DOTENV=1`、`.venv-d1/Scripts/python.exe -m pytest tests/test_update_u2.py -q --basetemp=<全新短根>`，`u2-independent-pytest-corrected.log`为**14 passed／1 failed，26.02秒，exit1，无skip**；根`%TEMP%/kgmu-u2ind-0616a96c/`保留。失败为`test_interrupted_directory_switch_keeps_old_backup_without_new_process`读取尚为空的old-ready JSON，不是安装行为已通过。首次执行有PowerShell原生命令参数拼接错误、pytest exit4，单独日志保留；纠正命令后才得到上述有效结果，不覆盖首次材料。

`u2-independent-remaining-probes-corrected.log`，exit1，全新根`%TEMP%/kgmu-u2verify-re_v1eop/`，重新实测：当前活PID＋相同creation_time、错误exe仍被当作已退出；只有真实Runtime而无服务／目标身份的writer仍accepted；Coordinator处于bound时再次prepare仍accepted并调用helper启动边界。首次探针因审阅命令未显式UTF-8读取元数据导致验签失败，单独保留；纠正读取编码后才采用本节行为证据。

### 14.1 交回同一OpenCode的剩余项

| 编号 | 剩余问题及验收结果 |
| --- | --- |
| U2-R01 | helper获取authorized后等待旧进程期间，授权可被revoked，但切换前未复核。§13已用真实进程与目录证明撤销后仍success／实际切换。须在旧进程退出及切换前核对同一plan／nonce／close代次授权，撤销／不明即禁止切换；覆盖窗口destroy失败和后续普通关窗。 |
| U2-R02 | 普通helper入口信任持久化plan的`new_app_command`，能执行测试Python命令；`new_app_path`及发行信任配置也不能由plan任意指定而替换产品权威。产品入口仅允许固定受管布局及经可信包认证的固定主入口，来源公钥取自当前受信任更新器的发行配置。测试替代启动／发行配置须显式专用源码验证上下文，不能由plan自证test_only；冻结入口不得启用测试参数。回归需进入实际普通helper，不能仅测试构造器拒绝。 |
| U2-R03 | AccessDenied已修；但相同活PID／创建时间且exe不符仍返回definitely_gone，缺失exe／查询失败与WAIT_FAILED也须保守拒绝。真实存活进程不能因计划身份不一致被当作退出；真实确认死亡或PID复用与未知分开，不强杀。 |
| U2-R04 | ReadyReceiptWriter只校验runtime，目标version／build取自plan、service_ready硬编码；合成夹具绕过d1_main实际身份校验，不能证明“实际目标包＋服务＋页面就绪”。d1_main已有部分身份校验，须保留并将真实当前身份、数据／凭据根、实际服务就绪、page_ready及新进程绑定落实在生产调用链和夹具中；无服务／错误包／未page_ready均不得产出成功回执。未验证新进程回执已改unknown，保持。 |
| U2-R05 | `prepare_from_manager`未将bound列为busy，能生成第二plan并再次启动helper。对pending／bound／authorized及helper存活或结果不明保持单一安装；unknown先核对再重试，不能只改按钮或允许旧helper仍活时新建plan。 |
| U2-R06 | 顺序追加已修；跨进程read-modify-replace仍丢阶段。上轮两进程预期62条实际34条，两writer均exit0。须以同一安装的跨进程安全记录方式完整保留阶段，坏记录不能静默清空；结果核对不依赖可丢失阶段猜测。 |
| U2-R07 | 真实旧进程夹具直接write_text发布ready，测试只等待文件存在，独立发生空JSON读取。改原子发布或等待可解析且身份已完整的真实ready，并保留超时失败；不放宽安装断言或反复重跑至绿。 |

同一OpenCode先补能复现错误的有效回归再修复；每轮全新短合成根，原始失败保留。只改本任务实现／测试／必要构建支持，不改报告／提示词／哈希表，不实际构建或运行冻结包，不重跑无变化前端构建。最终回复真实命令、exit、数量／skip、未验边界并明确停止写入。Codex复核通过后才接续U3，不重开U1已关闭项。

## 15. U2第二轮独立复核：原主要反例已修，R05／R06剩余分支不通过

原会话第二轮exit0、明确停止写入，API再次核对idle／succeeded及指定Go Flash default。脱敏导出exit0，模型审计见本日证据根`u2-r02-model-audit.json`。24份源码在复核前后hash零变化。

独立`.venv-d1/Scripts/python.exe -m pytest tests/test_update_u2.py -q --basetemp=%TEMP%/kgmu-u2r2ind-857b4da6`：**24 passed／32.70秒，exit0，无skip**，`u2-r02-independent-pytest.log`。包含真实authorized后撤销阻断切换、正常完整包重启／实际0004→0005、两进程62条phase、原子ready及关闭钩子。独立13项更新SFC及typecheck均exit0，日志`u2-r02-independent-sfc.log`／`u2-r02-independent-typecheck.log`。R01、R02固定产品布局／主入口／更新器自身发行配置、R03活PID错误exe、R04实际身份／服务／page_ready、R07原子ready在本轮限定源码／合成范围通过；未构建冻结入口，测试参数拒绝仅为源码分支验证。新的回归首次执行已在修复实现上全绿，修复前失败依据原始独立日志，不伪称本轮先红。

唯一剩余项见`u2-r02-independent-restart-phase-probes.log`，exit1，独立根`%TEMP%/kgmu-u2r2probe-2bnvn0w_/`：

- **U2-R05仍开放（重启后核对）**：实际写入unknown结果及new_process_started阶段，原Coordinator正确禁用安装；用同一程序／状态根新建Coordinator后再次prepare仍accepted，生成第二plan并调用一次helper启动边界，旧unknown文件仍原样存在。当前busy只检查内存`_plan`／`_helper`，没有恢复持久化未决状态。安装锁本身不能替代发起前核对。须在新宿主启动／prepare前恢复并核对受管install-state中的未决安装，helper存活／未知／记录损坏时阻止重复安装；按实际结果和进程证据核对，不盲目重放、不自动恢复库。合法完成或确认未切换的旧记录不能永久阻断正常后续安装。复测跨Coordinator／真实进程重启，不仅给同一对象设unknown。
- **U2-R06仍开放（异常出口）**：独立实际保存new_process_started阶段再增加损坏JSON，受控注入post-launch OSError并走真实`helper.main`异常出口，最终将status写为failed。代码虽令read_phases拒绝坏记录，main仍catch后置空列表，将无法判明阶段当未启动。须保留损坏材料并将阶段／是否启动不能确认的情况记unknown；不能依赖可失败的阶段读取证明“从未启动”，不得据此回退或放行再次安装。此为受控异常注入和真实文件／main出口核查，不冒充实际新进程启动成功。

仅交回上述两点及有效回归；已通过U1和本轮其余U2项保持，不要求重跑未变前端构建。每次全新短根、保留首次失败，稳定交付后Codex独立复核，通过才接续U3。

## 16. U2第三轮独立复核：R06关闭，R05刷新及终态绑定仍未通过

原会话exit0、明确停止写入，实际idle／succeeded、Go Flash default；脱敏导出与模型审计见`u2-r03-model-audit.json`。24份源码独立验证前后零变化。实现者29项U2／88项相关回归通过，未重跑未变前端；最早3项失败、后续NameError失败与修正日志均保留，不冒充先红回归。

Codex独立在desktop下执行`.venv-d1/Scripts/python.exe -m pytest tests/test_update_u2.py -q --basetemp=%TEMP%/kgmu-u2r3ind-3b62ea8f`，`u2-r03-independent-pytest.log`：**29 passed／27.19秒、exit0、无skip**。包含跨Coordinator／真实子进程重启unknown阻断、真实helper异常出口unknown及损坏材料保留。U2-R06在限定源码／合成范围关闭；其余已通过项保持。

R05补充反例`u2-r03-independent-live-refresh-terminal.log`，exit1：

1. 全新根`%TEMP%/kgmu-u2r3live-qv571ev6/`使用真实old/helper/new-runtime/service/page_ready进程链，仅以专用源码gate暂缓新夹具启动。helper到new_process_started时新建Coordinator，正确看到INSTALL_HELPER_ALIVE；释放gate后真实安装success、回执0.2.0，helper已退出，但同一Coordinator仍needs_review／INSTALL_HELPER_ALIVE／不可安装；另建Coordinator才idle。`_recovery_checked`将首次扫描永久缓存，后续state／prepare均不能重新核对正常完成。须在实际状态查询／安装前安全刷新未决状态；已确定完成后不要求用户重开应用才能恢复更新能力。
2. 全新根`%TEMP%/kgmu-u2r3terminal-3sgan4nv/`保存安装计划后写入nonce错误且无有效receipt的success记录，新的Coordinator仍idle／install_available=True。扫描未载入并关联plan／result／receipt，仅schema+status即接受成功。须拒绝损坏／错plan／错nonce／缺关键回执的终态，不以自称success跳过核对；合法历史成功需按自身plan/target核对，不能要求当前应用永远等于旧历史版本。

中途gate探针`u2-r03-mid-live-result-refresh.log`及其他辅助探针保留，但以上正式交付反例才作为本轮结论。仅交回R05这两点及真实正常／未决两侧回归；不重开R06或其他通过项，不提前U3。

## 17. U2最终限定工程结论：通过，接续U3

第四轮exit0、停止写入；API核对idle／succeeded，脱敏导出exit0，以本轮user消息为边界复核13条新增assistant均为指定Go Flash default，finish=stop。24份源码验证前后零变化（`u2-r04-source-before.json`／`u2-r04-source-after-review.json`）。

| 独立核查 | 结果 |
| --- | --- |
| U2全组 | desktop下`.venv-d1/Scripts/python.exe -m pytest tests/test_update_u2.py -q --basetemp=%TEMP%/kgmu-u2r4ind-6c8b0216`，`u2-r04-independent-pytest.log`：30 passed／30.11秒、exit0、无skip |
| 同实例实际刷新及错误终态 | `u2-r04-independent-live-refresh-terminal.log`，exit0；全新`%TEMP%/kgmu-u2r4live-130zke76/`，真实helper／新Runtime／服务／page_ready，gate扣住时HELPER_ALIVE不可安装，释放后真实success／0.2.0、helper退出，同一Coordinator刷新为idle／可安装；另全新`%TEMP%/kgmu-u2r4terminal-b8abf3g2/`的错nonce／缺receipt终态被拒绝为INSTALL_RECOVERY_RECORD_INVALID |
| 保持的相关证据 | 上轮独立13项更新SFC／typecheck及真实授权撤销、进程核对、0004→0005、62条并发阶段、异常unknown、原子ready与关闭钩子通过；未变前端不重复构建。实现者相关88项回归exit0／10.32秒 |

R05在本节范围关闭；U2-R01–R07均在限定源码／当前Windows 11合成进程工程范围关闭，不宣称全部路径与环境穷尽。历史失败及修正保留。U1／U2通过不等于更新产品验收完成。依用户2026-10-25接续授权，同一OpenCode进入U3：真实源码WebView2界面链、数据／历史／配置／凭据／AI状态及Word回归；仍不构建运行冻结包、不触碰真实数据或AI、不签名发布、不解除4551。

U2收口另将原开工快照中的453份非凭据保护文件逐一比较，changed=0，`u2-final-protected-file-check.json`；未读取真实密钥。此为所列文件hash保持，不扩大为未列文件或凭据内容审计。

模型轮次边界复核：以各轮最后user消息时间取全assistant，第二／三／四轮分别83／36／13条，全部指定Go Flash default，见`u2-r02/r03/r04-model-audit-user-bound.json`。原CLI首事件时间过滤漏首条的第三／四轮审计文件保留，正文数量已按user边界更正。

## 18. U3实现中审阅点（尚未正式交付，待稳定源码复核）

本节不是最终U3缺陷清单或通过结论。首轮自测`u3-chain-first.log`／`u3-chain-first-report.json`记录实际源码窗口未达到startup available，随后未找到安装结果，ok=false，根`%TEMP%/kgmu-u3-chain-acadbbd4/`保留。第二轮仍在实现者调试中，不能用旧的U1／U2通过替代U3。

图谱代次`2026-10-25T08:29:14Z`，4个相关路径覆盖`no_recorded_issue/metadata_changed`，已回读d1_main验证入口与U3驱动、harness、实际验证脚本及TLS夹具调用；新鲜度信号不作完整性证明。

- `u3-mid-product-entry-guard.log`，exit1，独立`%TEMP%/kgmu-u3guard-m3jt0p1d/`只调用真实`_validate_synthetic_entry`，未创建Runtime／未访问真实根。普通源码启动带u3_config、模拟冻结普通启动带u3_config、模拟冻结selftest/u3-update带配置，三例均未在Runtime前拒绝；当时d1_main SHA256为`35ca535e85de59f82a49542158168ae9694d05934f67f69e9c562644cfca36ae`。当前build_runtime可据此注入来源／密钥／路径／命令，与固定产品边界冲突。正式交付需复核全部U3参数在普通及冻结入口被拒绝；READY验证上下文也不能仅凭产品环境变量启用。模拟冻结仅为源码分支探针，未构建冻结包。
- 当前窗口驱动只有取消下载，未见既有关闭握手取消／保存失败后仍保留正文与旧程序的实际UI集成证据；须按稳定交付实际达到阶段复核，不用下载取消替代关闭取消。
- 当前`no_post_update_ai_provider_requests`只再次比较seed阶段已停止的服务计数为1，不是更新／重启阶段零发送的实际观察。正式交付须核对任务／attempt／候选和真实受控网络计数的覆盖，不能把不再变化的seed计数写成整个更新阶段零发送。真实供应商仍不授权。

以上待最终源码稳定后复核；实现者仍在写入，不提前预填U3通过或最终缺陷关闭。

## 19. U3首轮独立复核：正向源码链通过，整体尚未通过

原会话exit0、声明停止写入；实际idle／succeeded，脱敏导出exit0，以本轮user消息为边界取全113条assistant，均为指定Go Flash default、finish=stop。26份相关源码独立验证前后hash零变化。

在仓库根执行`APP_DISABLE_DOTENV=1`、`desktop/.venv-d1/Scripts/python.exe desktop/verify_d3_u3_update.py --frontend <LOCAL_USERPROFILE>/AppData/Local/Temp/kgmu-u3fe-s0QCMt --out <本日证据根>/u3-r01-independent-chain-report.json`，`u3-r01-independent-chain.log`：exit0、现有脚本32项顶层检查全部true、无skip，新根`%TEMP%/kgmu-u3-chain-f04973ec/`。实际WebView2旧页面发现／下载／下载取消／重试／安装确认／关闭保存、真实helper切换合成程序目录、新源码Runtime／服务／Vue page_ready、版本／build／PID及Word文件内容等正向链通过。实现者相关118项Python回归通过作为其自测记录，不冒充本轮独立118项。

**入口探针更正**：§18及`u3-r01-independent-product-entry-guard.log`只调用内部`_validate_synthetic_entry`，未覆盖最终源码在`build_runtime`紧接着增加的U3参数守卫，不能据此断言最终产品入口接受U3配置。改用真实`build_runtime`并在LocalRuntime构造边界设置不可进入哨兵，`u3-r01-independent-runtime-entry-guard.log` exit0，新根`%TEMP%/kgmu-u3entry-dso37r2m/`：普通源码／模拟冻结普通／模拟冻结U3自检三例均在Runtime前拒绝。原探针文件保留并由本段限定其含义；未运行冻结包。

以下仍是当前授权U3范围的剩余项，不以32项现有检查全绿覆盖：

| 编号 | 剩余问题与必要证据 |
| --- | --- |
| U3-R01 | `d1_main.build_runtime`创建ReadyReceiptWriter仍直接用`KGM_UPDATE_VERIFICATION_CONTEXT=1`决定verification_context，未限定为已校验的专用源码相位／非冻结运行；helper的测试启动也需清除产品继承的该变量。U3 CLI参数守卫已通过，保持；仅将ready测试上下文绑定已验证源码入口，普通／冻结运行不能因环境变量免除目标exe核对。此为限定源码接线审阅，不声称已绕过helper独立的产品回执校验。补普通／模拟冻结环境变量与合法源码相位两侧有效回归。 |
| U3-R02 | 当前真实UI仅取消下载；尚无“确认安装进入既有关闭握手后，取消关闭或保存失败，原页／输入／旧程序仍在且未切换”的集成证据。按current原要求补至少一条，随后仍能正常安装；不能用下载取消代替，不能直接调用host安装绕过页面。多plan结果须绑定实际本次plan／nonce，避免选到旧撤销记录。 |
| U3-R03 | 完善既定数据／AI／凭据验收：当前`no_post_update_ai_provider_requests`只是重比seed已停止的provider计数1，未观察更新／重启期间发送；须使用持续受控计数／受控网络边界覆盖old→new并确认零新增发送，保留真实任务／attempt／候选／已发送状态且不重放（仅合成，无真实AI）。`local_daily_plan_ai_provenance`与`local_daily_plans`被整表排除且前者无旧行subset核对，须保留旧归因行和计划不变字段，精确允许保存所需新版本／指针／时间增量；合成凭据目前只比文件hash，须在新源码进程以实际同机存储验证可解密使用，输出摘要／布尔而非密钥正文。 |

本轮程序包是有签名元数据及文件清单的合成形状夹具；EXE／模板／迁移条目不是真实冻结发行资源。新窗口实际运行当前仓库源码与独立前端构建，身份读取切换后的build_identity。正向源码协议链不证明冻结载荷资源执行、真实安装或4551已验，仍不构建／运行冻结包。Word为当前实际源码模板导出与XML内容核对，不作教师逐页验收。

历次首次失败、元数据key_id、下载观察窗口、关闭driver收口、source config、venv PID和Word确认／预期修正均保留在`u3-chain-first…twelfth/final*.log`与各独立根；不将这些自测失败归为用户环境已修。只交回上述三组剩余项，不重开U1／U2；稳定交付后Codex再独立核查。

## 20. 最终独立核查：U1–U3限定源码／合成工程通过

原会话第二轮U3修复exit0、明确停止写入，API核对idle／succeeded。完整脱敏导出exit0，以本轮user消息为边界取全46条assistant，均为`opencode-go/deepseek-v4.1-flash#default`，finish=stop，`u3-r02-model-audit.json`。27份变更源码／测试／前端文件独立验证前后hash零变化，`u3-r02-source-before.json`／`u3-r02-source-after-review.json`。

### 20.1 Codex独立结果

命令均为实际直接执行，无head／tail管道替代测试exit。证据根`%TEMP%/kgmu-codex-20261025-a78be6fa/`，只用独立合成程序、业务及凭据根：

| 检查 | 实际命令／结果 |
| --- | --- |
| 完整源码窗口链及关闭失败后再安装 | 仓库根`APP_DISABLE_DOTENV=1`，`desktop/.venv-d1/Scripts/python.exe desktop/verify_d3_u3_update.py --u3-close-cancel --frontend <LOCAL_USERPROFILE>/AppData/Local/Temp/kgmu-u3fe-s0QCMt --out <证据根>/u3-r02-independent-chain-report.json`；`u3-r02-independent-chain.log` exit0，42／42顶层检查通过，无skip，根`%TEMP%/kgmu-u3-chain-d2774482/` |
| U1／U2／U3与关闭保存回归 | desktop下`.venv-d1/Scripts/python.exe -m pytest tests/test_update_u3.py tests/test_update_u2.py tests/test_update_u1.py tests/test_d1_close.py tests/test_d1_host_save.py -q --basetemp=%TEMP%/kgmu-u3ind-867655de`；`u3-r02-independent-pytest.log` exit0，120 passed／46.14秒，无skip |
| 真实SFC及类型检查 | frontend下`node src/d1/d1.update.test.mjs`，`u3-r02-independent-sfc.log` exit0，13项；`npm run typecheck`，`u3-r02-independent-typecheck.log` exit0。前端本轮未变，不重复构建 |
| 保护文件 | 原开工快照453份非凭据文件全部hash一致，changed=0，`u3-final-protected-file-check.json`。不读取真实密钥，不扩大为未列文件或凭据内容审计 |

Git收口前另直接执行更新后的`npm run test:d1`完整前端脚本，`final-frontend-regression.log` exit0；覆盖原纯逻辑、组件、W5、历史及更新SFC串联。相对路径文档链接与暂存差异检查通过，未加入库、凭据、包或窗口产物。

U3真实Vue／WebView2页面执行启动提示、应用内分段下载／取消／重试、完整校验、安装确认；以仅针对日计划PATCH的受控保存失败，验证既有关闭握手留页、正文仍脏、关闭锁释放、安装授权revoked及旧程序未切换，截图`u3-close-cancelled.bmp`已独立查看。恢复该测试故障后由真实UI再次安装，旧进程正常退出、数据锁释放、helper重新校验原包并切换，实际新版源码Runtime／服务／Vue page_ready产生就绪回执，截图`u3-new-page-ready.bmp`已独立查看。故障注入用于验证UI及宿主的失败处理，不冒称实际磁盘故障根因已修。

本次撤销plan为`968c4430eb3a46889ef347eecd2f3860`、status=revoked；最终plan为`7a47175361184b139c84d3c87945a478`、status=success，plan／nonce与receipt逐一对应，互不混用。新源码PID及receipt均为18156。应用合成版本0.1.0→0.2.0保持实际head `20261023_0005_local_history`；真实0004→0005迁移另见U2独立通过范围，未造0006。

持续受控TLS供应商贯穿seed到新版退出，全程requests=1／split=1，只有seed一次、更新与重启新增0；AI表摘要保持，未调用真实AI。旧内容、操作及provenance行均保留；计划除当前内容指针／版本／时间外字段保持，版本精确+1，对应内容6→7、归因6→7、操作8→9。凭据文件摘要保持；新版关闭后在独立真实LocalRuntime中经`ai_config_service.get_config`得到configured／ready／has_secret=true，ready实际要求CredentialStore主密钥加载与AES-GCM／AAD解密成功（源码回读321–445，非仅文件存在），未输出密钥。Word导出200、14286字节，核对当前保存的“U3 关闭前反思”及“历史v1”来源，未把原始教案raw字段强行当作Word正文导出。

### 20.2 关闭范围及边界

- U3-R01：环境变量仅在非冻结、专用selftest/u3-verify、显式来源身份且已通过入口校验时参与源码上下文；产品helper清除继承变量，普通／模拟冻结两侧回归通过。§19对内部校验探针的更正保持。
- U3-R02：实际关闭保存失败的UI留页／撤销／原程序保持及重试成功通过，不与下载取消混为一项。
- U3-R03：持续计数、AI表、旧归因行、计划固定字段及真实同机合成凭据解密核对通过。凭据读取发生于新版退出后的独立Runtime，未伪称由新版窗口发出真实AI验证。

U1原R01–R07、U2-R01–R07及U3-R01–R03在当前CPython3.14.7／Windows 11限定源码与合成工程范围关闭；不声称所有系统、权限、长路径、网络或进程组合穷尽。真实发行URL／正式公钥未配置、真实冻结载荷执行／安装、首次安装与快捷方式、SAC4551、教师逐页Word体验、Win10／WPS等仍未验；本轮没有构建运行新冻结包、签名、微软提交、防护变更、WebDAV或发布。U3仍使用形状目录包＋当前仓库源码／独立前端，不将合成成功当真实更新发行可用；活动AI“停止等待并退出”UI分支未由本轮重验，既有D2证据与未验边界保持。U1中私有socket关闭路径限定当前Python／Windows验证，未来运行时变更需复核；WinError206长根未修状态保持。

失败根及所有原始日志保留；本轮`u3-r01-r03-first-report.json`记录关闭失败留页已通过但再次安装尚未恢复，后续修正后才完成上述独立成功。按用户既有授权进入相关Git提交／推送，再准备游戏观察记录规格的下一步待审提示词；不自动派发游戏实现。
