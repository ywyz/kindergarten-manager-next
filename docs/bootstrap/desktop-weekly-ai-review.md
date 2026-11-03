# 桌面周计划 Q5/Q6 实施与验证核查

更新：2026-11-03。文档先提交、G0核定、旧档案／备份先行、页面实现与限定独立审核已完成；真实游戏／材料生成采用成功，新候选构建及独立54／59静态检查通过。材料原生页面后半流程受远程桌面捕获／输入影响仍未验，新包未作目标运行，不宣布全矩阵或产品验收通过。最终来源、异常恢复、构建身份及下一步见§12–15。用户本轮已授权业务实现、构建、真实应用AI和审核后提交，不自动推送。唯一执行入口为[current](../tasks/current.md)，合同见[工程](../specs/desktop-weekly-ai-engineering.md)，案例见[矩阵](../specs/desktop-weekly-ai-validation.md)；已接受教师清单不重验，旧包身份保持。

## 1. 文档基线与原生执行

9份准备／入口文档已由原A按Codex精确门禁普通提交为`51ec4d3271a81b8980833727f466edf0d1f637b2`，parent `0285a7c2984d267985a1f25edbb8ae957922c0ae`，tree `71d906507ea3cbad6ff5d4c9fe4106af5d4f6195`。门禁核对准确路径、工作树SHA-256、暂存blob／tree、parent及空白检查；回读一致、提交后工作区干净，未推送、amend、rebase、reset或改默认分支。

本轮A/B/C/D延续[准备轮](desktop-weekly-ai-preparation-review.md)指定的原生会话；OpenCode为build／`opencode-go/deepseek-v4.1-flash#max`，Command Go为`deepseek/deepseek-v4.1-flash`／max。G0期间仅只读源码、自有私有报告；A另有上述Git授权。Codex独占正式文档与最终审核。私有任务、原始stdout／stderr、exit、报告、门禁和metadata在`%TEMP%/kgm-q56-20261103-r01/`；中间metadata已确认模型及无fork／子代理工具调用，G0最终自然停写及metadata见§4。

结构探索采用已安装codebase-memory Verify：项目`C-Users-yw980-code-kindergarten-manager-next` ready，generation `2026-11-02T22:43:35Z`；有界查create_task、load_source_snapshot、validate_content并作create_task双向一跳追踪。9个相关路径无已记录gap，但freshness为metadata_changed；已回读实际函数、schema／迁移／守卫／备份和执行器分支。图谱只作导航，不声称完整影响闭包。

G0审核特别核对：完整本人日来源和配置须独立冻结；逐任务白名单与无关配置修订分离；采用起点、人工编辑与源过期分离；schema1原JSON／hash保留；冷升级守卫不因新增提示词登记而放宽；旧档案按冻结旧表／旧列原始值及照片字节比较，不能用新metadata或JSON规范化掩盖重写。最终接口、错误、文件表和放行回执已归工程§9及本结果§4；G2期间图谱工具报Transport closed，后续有界结构核查使用实际源码回读，不安装或重建工具。

## 2. 既有应用AI配置检查

用户补充“之前已经配置过，请检查是否可用”。当前无运行中的业务应用窗口，固定默认档案不存在；根据G17正式结果定位到已知合成隔离验收根，仅通过现有`ai_config_service.get_config`脱敏通道检查，没有启动旧EXE/helper或迁移原根。

DeepSeek既有配置v1为官方`https://api.deepseek.com`／`deepseek-flash`，`has_secret/configured/ready`均true；MiMo配置v0、未配置。此处ready只证明本机凭据通道可以解密，不证明供应商当前连通或新周业务成功。检查禁用dotenv、阻断网络、SQLite只读，数据库及已有侧文件SHA-256前后一致；没有输出密钥、主密钥或密文。

首个私有检查器误用`as_dict`导致AttributeError，首回执保留；改用实际公共`to_dict`后取得上述r02结果。这是检查器问题，不计应用失败或供应商请求。后续真实周任务必须使用新合成副本、保留原G17资料及凭据文件，待G1通过再执行，不自动补发未知结果。

## 3. G0结束时未验与下一门

G0结束时，46项假供应商矩阵、0007→0008迁移、全旧档案／照片保留、schema2采用、明文／加密备份与保护包、页面／维护／关闭、真实周AI、新构建／静态／归档均未执行；G1过程证据续记§5。G0报告和CLI成功不记为这些案例通过。

当时G1由Codex按工程§9冻结并放行；A共享数据／任务／迁移，B纯合同，D备份与旧档案证据先行，C页面等待G1门通过。不自动签名、WebDAV、安装更新、公开发行或运行已知受阻EXE/helper。

## 4. G0最终核查与G1放行

A/B/C/D四份报告均已自然CLI0。最终metadata-g0-final.json pass=true：A新增97条、B66条assistant均为build／OpenCode Go Flash max；C15次、D79次model_request_end均为Command Go Flash max，精确原会话、无parent/fork／子代理／换模型，分页覆盖本轮起点。计数是原生metadata口径，不作供应商计费次数。

Codex已把实际迁移、纯函数、raw/typed manifest、DTO／错误和互斥文件表归[工程§9](../specs/desktop-weekly-ai-engineering.md)，并修正配置修订误过期、采用后自身stale、材料空串no-op、可信AI原值PATCH回传、立即复合FK写入顺序与带周归属的回执查询。当时明确放行G1，A/B/D只在激活范围写入；C保持只读。G0结束时46项矩阵仍未执行，不把G0提案和CLI0记为通过。

为独立旧档案证据冻结51ec4d3的backend源码ZIP，SHA-256 `4155251b352cfb7719a179308ec6c1a9eefa76e8bf66cac2bac5555eb2a777be`，保留于私有根；不作为新构建来源。G1使用本轮短新TEMP和Python子进程继承的仅loopback连接守卫，dotenv禁用；真实供应商检查待G1门通过。

## 5. G1进行中证据

本节保留进行中的证据和首失败顺序，最终G1状态以§6为准。

A已通过151项既有迁移安全／日AI任务、执行器、API、候选及runtime回归，另有17项D2 schema回归；D首个真实0007→0008副本迁移及当前备份数据库校验通过，既有快照15项通过；B已有纯输出合同8项、材料5项中间结果。以上为原owner进行中回执，尚未停写或由Codex最终独立复跑，不代表完整WAI案例、全历史保留或G1通过。

首失败均保留：测试选到缺Pillow／pytest的backend环境、私有scratch未创建、D自有源码文本转义导致SyntaxError、B纯函数联调／新schema预期与A旧prompt计数等，按原owner修正，不把后续通过倒填首试。执行环境已核：既有desktop/.venv-d1为CPython3.14.10／Windows x64／标准GIL，Pillow、pytest及桌面依赖齐全；私有runner统一用此解释器，无安装／升级。UTF-8输出及外部DNS／连接守卫自检已通过；该守卫是Python层防护，不声称OS全局隔离。

Codex对进行中代码另作采用身份／并发回执／冻结输入与当前稿分离、候选链完整性、普通保存继承原采用起点及错误安全投影的独立审阅；暂存意见留于各owner私有review文件，待原owner自然停写后按最终源码核定并交回修复。C页面、真实周AI和构建继续等待G1门。

B两轮修正后81项纯测试通过；Codex在B自然停写后独立复跑81项，9个B文件SHA-256前后一致，原C发现的材料证据替源反例已拒绝。习惯输入已收窄到明确白名单，已存候选及冻结材料依据校验归工程§9.8／§9.9。此结果只覆盖B纯层，不替代A数据库链或D恢复验证。

D首段触及CLI默认100回合上限exit8，已沿原会话接续。接续进程长时间无输出后恢复；Codex的重启诊断误启动了同会话第二进程，08:23核实身份后仅结束重复PID24864，exit4294967295，原D继续。重复段14次工具调用只写D自有test_weekly_ai_backup.py的周prompt断言及运行测试；两份原始日志保留，须由原D在最终复核中确认合并结果。此段不能记作自然CLI0或无重叠执行。

随后Codex另用合成SQLite独立复现：改写已存payload，或在后继稿篡改provenance.candidate_hash并重算content_hash，首轮备份校验均未拒绝。原B／D确认存储输入接口缺口，已归工程§9.10；B新增唯一纯helper并补空地点配置范围／指导进入真实业务basis，94项纯测试通过。Codex独立复跑94项，9文件与ready的SHA-256一致，guard仅加载且无外联；A/D实际读取／采用／恢复接入仍待核，不把纯层通过转写为WAI42通过。

D接续段已自然CLI0，受影响备份／恢复／快照／导出162项通过；其0007合成档案48旧表原列值及5个照片文件指纹相同，新增周引用null、采用表空。D报告明确WAI42／43仅部分完成；当前由原D继续补来源元数据、真实材料采用后手改／清空恢复及旧token／permit断言，C页面仍未放行。原始探针、首失败及分层回执均保留。

## 6. G1独立核定及G2放行

ROOT-G1-gate.json pass=true。四原生最新段均自然CLI0，metadata-g1-final.json pass=true（A565／B387条OpenCode assistant，C58／D680次Command Go model_request_end，固定原会话Flash max；不是计费次数）。D历史exit8接续、重复进程exit4294967295及原D最终核对分别保留。

Codex冻结327个Python文件后独立验证：后端／旧日与周回归249项（ROOT-6b086cd4a1）、备份／旧档案／恢复41项（ROOT-f1fcdcbce8）；此前B停写后纯层94项（ROOT-476dd9c49d）。源码指纹复核全部相同，guard仅加载、0外联拦截事件。原payload、后继provenance、同周同文换input/execution、改原采用值并重算hash、未知行schema及多余target hash探针均转为拒绝。正常基线先通过再做篡改，不能把其他坏字段碰巧拒绝当作原点绑定通过。

旧0007来源ZIP、48旧表原列逐原值、4份日内容、8份观察历史、周草稿／确认／回执及5照片文件已核保留；新周列null、采用表空，runtime只增周prompt记录。schema1/2混存、新采用后手改／清空、明文／加密／保护包再恢复、旧token与恢复后未发／已标发permit均有真实SQLite证据。D在最后仅改周原点校验，最终受影响122项通过；较早166项属原先源码，分开记，不倒填。

Codex现明确激活工程§9.11／9.12的G2互斥责任：C页面与周编辑器，A共享session代与测试入口，D必要宿主／导出／构建支持，B只读。先完成源码接线与审核，再冻结新构建；不执行已知受阻EXE/helper，不重验已接受教师清单。

## 7. G2进行中与首次真实周请求

A共享client会话代及两个测试入口已交付，自有测试通过；C页面和D配套仍在各自原生段，整体G2尚未核定。A仅清除既有测试一行尾空白，AST不变，不改G1后端业务。

真实验证只用已知G17合成源的新副本。普通文件复制首次丢失凭据保护DACL，应用正确降为CREDENTIAL_UNAVAILABLE，0请求；首副本保留。第二副本经既有CredentialStore受保护写入路径仅复制opaque DPAPI密文，正常get_config可用；未改原根／保护逻辑或输出明文密钥，原数据库／侧文件及凭据4个保护文件指纹相同。

第二副本仅播种明确合成日来源并经正常周服务／原执行器发送1个weekly_games请求。官方域名DNS／TLS连接各1，HTTP200后得到provider_error／outcome_unknown，1attempt、0候选、草稿v2不变，无自动采用或重发。尚不能据此判配置已可完成业务生成，也不能仅凭该安全摘要认定供应商SSE错误；传输detail未保留，原HTTP／思考正文不记录。当前只读核对传输分类，按工程§6.3等待用户对这1个未知请求显式重试的可能重复费用确认；其余G2工作继续。

原A只读诊断已自然CLI0：HTTP200的provider_error可来自帧头／长度／正文上限或非SSE正文读取异常，SSE事件错误沿现有代码归output_invalid，不能据摘要倒推供应商错误。没有保留该次detail，因而不足以裁定供应商响应不合法或应用验证过严；后续若获显式重试确认，仅采集固定安全detail枚举与计数，不记录原响应、思考或密钥。

## 8. G2配套独立复核

D构建／归档要求已同步唯一0008及8个新周模块，旧0007迁移仍保留；宿主生产代码无需改动。原D构建守卫33项、宿主／维护103项、快照／导出100项通过。tiny-package夹具首轮仍写0007导致19过2失败，Codex精确追加该测试文件责任后由原D更新正向夹具，保留旧revision拒绝反例，21项全部通过，未放宽生产验证器；首失败保留。

Codex独立复跑构建守卫、静态归档及真实周claim关闭联动共56项（ROOT-8d27db4b4b），另独立执行schema1/2确认混存导出新增用例1项（ROOT-c2903af638），均通过，禁用dotenv且guard无外联。旧确认重复导出仍取其原冻结快照，不取当前schema2草稿。

新增合成材料Word为18,876字节，SHA-256 `c4d2d91df6d1acfdaa3bdcc06cddd06cb02da6e0014f745b93601a901f5be1ba`。Codex使用本机Word实际打开：1页，两行材料及换行完整可见，表格未截断，没有来源列；未编辑／保存，检查后指纹相同（ROOT-G2-Word-QA.json）。此证据只覆盖该新材料样例，不重验或继承原13份／43页结果。

Codex私有真实SFC探针ROOT-G2-panel-probe-r02复现三项缺陷：首次采用后材料编辑区computed仍false、采用GET等待期间换session仍reconcile、候选刷新等待期间换session仍写回旧候选。首r01的采用子测未断言到达GET，不计该子测通过，修正r02后才形成结论。另查持久任务重进读取、逐await代次、未知票据不覆盖及预览选择意图；G2尚不通过，原C修复后需独立重核。

B以原会话只读审核真实DTO后自然CLI0，确认路由／Task DTO／cancel nullable／组状态优先级匹配；发现allowed_actions未消费及材料证据／游戏before-after展示测试不足。Codex冻结工程§9.13：延续现有认证candidate detail的物化展示source六键；raw/wire/hash继续五键，不新增handle映射协议或擅改后端接口。C按真实DTO补可信出处、目标格式化与回归。

原C首轮自然CLI0后，Codex沿同会话交回§9.13修复。继续独立检查确认：真实controller的applyLaterInput漏合并materials；真正挂载SFC／实际控制器的输入事件还复现材料只在局部textarea变化、controller内容未改且isDirty=false（ROOT-G2-material-dirty-probe-r01）。后者会绕过统一保存／leave，必须由原C修复，不因现有全前端测试通过而延期。另由原B按§9.14在四个自有纯测试补现有大小／严格JSON／日历边界证据，不扩生产接口。

原B边界补充已自然CLI0，仅改三份自有纯测试，四个生产纯模块指纹与G1相同。97个独立函数通过，Codex独立复跑97项（ROOT-6179eead8e）、9文件hash匹配、guard无外联。材料100／101项、text300／301、quote2000／2001、合成正文20000／20001均先合法后越界；另单独证明provenance超过512KiB而整稿仍小于1MiB时拒绝，复用既有整稿1MiB与严格JSON测试。家园±7边界、普通周末、日期／节名及unknown coverage有实际纯投影证据。首provenance夹具同时超过整稿上限，修正隔离分支后才记通过，首失败保留。

Codex回读错误接点：共享_text的直接parse超限可带安全INPUT_INVALID；已存候选_rethrow_stored统一OUTPUT_INVALID，实际executor将ValueError归任务output_invalid，无候选。此内层差别不改变公开任务／存储错误合同，不为统一内部字符串修改已冻结生产代码。

原C首轮review-fix已自然CLI0，10项新core／18项新SFC setup场景及全前端测试／typecheck／build:d1通过。Codex在停写后独立复跑原五项页面反例（ROOT-G2-panel-probe-r04）全部转通过，真实controller晚theme／materials反例也转通过（ROOT-G2-late-materials-probe-r02）。这些setup探针不冒充挂载／宿主证据。

继续真实loopback HTTP联调发现任务动作查询接错入口：创建pending周任务后cancel 200，周operations读该request为404，既有local AI operations为200且task／周匹配（ROOT-88a365b4b5／ROOT-G2-action-receipt-probe-r01，0发送）。工程§9.15冻结正确既有适配，不放宽后端周四种回执白名单；与前述真实挂载的材料dirty缺陷一并交原C最后小补丁，G2继续等待该补丁与源码窗口独立验证。

原C随后两段均自然CLI0。材料实际挂载输入已使真实controller同步变更、dirty=true（ROOT-G2-material-dirty-probe-r02）；正确动作回执适配及逐任务ack、busy token已接入。Codex另复现并交回慢保存重复点击丢未知票据、Vue ref代理导致正常采用误拒、旧批刷新覆盖新批三项；修复后独立create-save r03为1POST且保原ticket、raw-controller r02正常采用1次、refresh-generation r02保留新批，均通过。合法基线先通过再核拒绝，避免“所有采用都被拒”掩盖负例。

读取异常继续发现refreshBatch向挂载void调用传播reject而无安全提示（ROOT-G2-read-error-probe-r01），由原C在同一面板补读取错误／新批未读状态，不改后端或自动补发。G2最终冻结与源码窗口待该小补丁后独立验证。


## 9. G2源码独立回归与窗口边界

原C读取错误小补丁已自然CLI0，Codex独立重核最终C5九文件hash一致。全前端14个脚本（包含新增10项core／27项UI）、typecheck、build:d1分别通过，回执ROOT-b49d8bb7ce／ROOT-679d208e38／ROOT-b7d21bcb75；285文件来源摘要`f4cc867e096f71799a0ddcf32647f13bf936ad4efa4d34dd23803aba48403e2c`前后稳定。五项原页面反例r05、真实挂载材料输入r03、正常raw-controller采用、慢保存重复create、刷新代次及安全读取错误的最终探针均通过。这是C5来源身份；其后小补丁不能沿用此摘要冒充最新全测。

源码Python／真实WebView2／正常loopback API使用全新合成根`C:/kgm-q56-ui-20261103-r02`和现有假worker私有注入，未注册生产假供应商。实际窗口完成周游戏生成、完整来源展示、预览及明确采用，随后一次提交四栏目，逐栏成功、完整预览并明确采用；生成阶段草稿不变，采用后draft v2→v3→v4，任务／execution／attempt／candidate各5、采用事件5、模拟发送5，材料仍null，无连发。只读SQLite回执game-generated／game-adopted／columns-generated／columns-adopted分别保留。面板采用人工“刷新候选与状态”，不记自动轮询通过。

随后窗口截图恢复报`IGraphicsCaptureItemInterop.CreateForMonitor … 0x80070057`，新窗口清单仍只有源码应用及Codex；仅辅助功能读取可用，尝试键盘恢复又报`GetCursorPos … 0x80070005`。已停止输入并告知用户，未操作安全设置／锁屏或执行EXE/helper。材料生成／采用／手改／leave／重进、无执行器源码窗口的后半流程尚未完成，不记为目标或教师通过；实际挂载输入、后端材料采用／恢复及原宿主自动回归证据分别保持。源码合成窗口仍保留，不能冒称已正常关闭。

最后独立慢保存反例又发现任务action未服从预保存mutex：create等待save时cancel进入，posted为cancel／games（ROOT-G2-presave-action-probe-r01）。工程§9.17已精确交原C仅修面板及其UI测试，A同时仅改后端，文件互斥；最终来源和门待两段自然停写重核。

## 10. 已批准重试与真实响应上限

用户明确答复“允许多次重试，接受重复计费，若api返回费用不够，请跟我说”。原合成task使用正常retry_task、当前execution条件和ack_duplicate_cost=true显式重试两次，未换key创建替代任务；加上首次共3次实际发送，各1attempt。两份新安全诊断均HTTP200、provider_error／outcome_unknown、固定detail=`body_too_large`，候选0、草稿v2不变。后次只累计进度数字：121帧、13,104思考字符、答案0字符；不记录原思考、响应、header或密钥。目前未见余额不足返回，不推断账户余额。

原A只读诊断自然CLI0：1MiB响应限制实际计入HTTP chunk／SSE framing、JSON及reasoning开销，未设置输出token预算；旧detail缺失的首次尝试不能回填具体原因。新增两次enum和后次进度证明已进入思考流且本地wire上限拒绝，不能声称候选内容超过1MiB，也不能归为供应商5xx或SSE error。

Codex按工程§9.16激活周专用有界修复：原A负责transport／worker／executor和合成真实transport回归；原B只读审核预算绑定、预检一致性和旧路径隔离。保持思考模式、配置、最终content1MiB、完整响应与未知结果保护，固定周输出token和wire预算，不全局放宽日／观察路径。修复后须独立回归、再次明确合成请求验证并以新来源冻结构建；当前尚未记实际生成可用。


C6预保存mutex已自然CLI0，仍仅面板／UI测试两文件，另外7个C文件hash相同。Root独立原action反例r02转通过（仅games发出），并在最新SFC来源重编译五项r06、真实挂载材料r04、create-save r04、raw-controller r03、refresh-generation r03、read-error r03，均pass=true；正常采用1次的对照保持。最新C6全前端14脚本（10core／29 SFC setup）／typecheck／build:d1分别独立通过（ROOT-3df35f0038／ROOT-8ae0fa7cce／ROOT-e5399f01a6），104个frontend文件前后SHA摘要均为`4d7bf147762776efb8e3e12361d7eb218048c78d2f0b9ae79aaf3310604e55ae`；这是frontend范围冻结，A并行后端补丁不在该摘要中。测试脚本中的“mounted”标签实际为setup调用，真正挂载证据来自Root独立memory renderer，不扩大为原生宿主。

源码窗口实际采用后的数据库以只读SQLite backup复制至新私有根，经当前完整backup_validate检查0008／schema／FK／逻辑链通过（ROOT-c97e2b74dc，副本987,136字节，SHA-256 `7c92012e47fa5b4a89a76259ee6ffe3399b9d0b13745713972daa4b4d8f4baf2`）。首次验证器scratch目录未建而失败，修正私有脚本后通过；首回执保留。真实请求重试后原合成G17的数据库／侧文件／受保护凭据4文件指纹仍一致（ROOT-G3-original-protection-after-retries）。


## 11. 流式补丁独立核定与提示说明缺口

原A按§9.16自然CLI0，仅改transport／worker／executor、序列化计长helper及新增bounds测试五文件，Root逐文件SHA匹配。Root独立211项后端（ROOT-8478095040）通过，393个Python文件和285个product/build/verification来源文件前后稳定，产品摘要`77b1551f54e096258077c69a7afc17e85de22f3d212139e18c0e3d5425f92f72`。这是提示说明补丁之前的来源，不将其倒填到之后的B修订。

另Root独立12项实际transport.send／HTTPResponse解析及multiprocessing.Pipe检查通过（ROOT-872c0f0356）：2,100,726字节合法SSE在周分支成功、同体在默认日分支被旧上限拒绝；Content-Length／chunked均有对照；真实chunked累计超过16MiB拒绝。正文1,048,576字节且含大量JSON转义可成功，+1拒绝；实际IPC为2,097,209字节完整返回。缺DONE、未结束尾、DONE后非空及length结束均无候选。固定大小和完整性保护保持，不保存合成思考或材料正文。

原B最终只读复审自然CLI0。其F1指出计长helper仅按task_type选择预算，未单独接source_kind；Root裁定该函数只计长，任务真实数据库分支、executor和worker已共同精确配对，直接构造不合法Python实参不代表可达应用授权路径，不以此重构已验证状态机。F2为内部send可接受预算对象的未来调用边界，目前无用户／模型控制路径。B所列转义IPC、length、chunked／分片部分缺口由Root上述独立反例补证；没有声明事件／wire所有字节位置的穷举矩阵。

同一合成任务随后又各显式发送一次（r05／r06，共5次实际发送）：transport完整SUCCESS、HTTP200、returned_model=deepseek-flash与usage可用，但业务parser仍failed/output_invalid、0候选、草稿v2不变。r06仅采集安全校验code／固定路径，得到`WEEKLY_AI_OUTPUT_INVALID / games.outdoor_game_slots.collective_1.kind`，未记录原响应／思考。前两次完整响应usage分别total5000／6476 token；不把这些已返回用量套到原unknown尝试，不推断金额或余额，尚未见余额不足响应。

Root回读确认：默认游戏output_schema只列三个槽与focus，未向模型说明kind/source_handle及AI补充变体；材料items也只有object，未说明origin/evidence_refs/codepoint。该应用说明缺口不能推给供应商或通过放宽parser绕开。工程§9.18已激活原B仅合同与两份自有测试补完整schema／中文guidance、实际改动默认修订升2，CONTRACT_VERSION和raw/parser不变。旧提示行／个人head／冻结任务保留；新真实验证须用明确新操作和实际based_default_revision=2，不用重试旧任务冒称新提示验证。

## 12. 提示契约最终核定、恢复事件与独立回归

上一节末尾default_revision=2是首案，实际被同步层结构守卫拒绝，最终按工程§9.19：游戏／材料提示契约2/default1，四栏目1/1；raw和input仍1，周content仍2，数据库仍唯一0008。旧bundle、个人文本／head及已冻结任务未重写；旧1游戏／材料候选过期但详情、采用及确认历史可读，备份仍完整接受其合法链；未知版本、栏目2、日／观察2继续拒绝。原A仅把创建／pending／领取三个版本门接入按task_type的支持谓词，不将全局支持集改成(1,2)，不改发送状态机。

原B101项纯层由Root独立复跑（ROOT-2e5a2ad400），9文件与最终ready一致；原A最终周服务／API／采用71项及日／观察77项通过。Root在A／D最终停写后独立执行13个受影响模块共271项（ROOT-171f737e69／ROOT-G3-contract2-backend.json），包括实际周创建、采用、备份、迁移、提示同步、日任务／执行器及观察合同／业务；全部通过，393个Python文件前后相同。285个产品／构建／验证来源摘要为`4c18635e1b524719f38ce6517d5fb49ab75232c6bf9d8b692923c7bb46a7461c`。较早211项及12项实际transport／Pipe仍按§11自己的来源记账，不混加为一次运行总数。

必须保留的执行异常：原D在g3contract2中先WriteAllText再ReadAllText，误将自有backup_validate.py从97,646字节截为352字节，导致当时A测试IndentationError；当时另有3个提示版本门错误，均未冒充通过。Root从原A本项目OpenCode快照树`bac3f3b7f2380e34667657bcf0d96dd3f3a34ddb`只读提取截断前文件，SHA-256 `476ae7ed07b7770c9154a7a45dbd2649e2ab92313aa118ad5706ec0b3dea9829`与事前冻结一致；旧HEAD重建或反编译稿未用于恢复。原D未及时收到协调后开始旧基线重建，Root核实无子进程后仅中断该原生Node PID37428及其wrapper38572，exit4294967295；沿同一原D会话g3recover恢复精确快照，再补唯一支持谓词。Codex没有写生产文件。

恢复后文件97,948字节，SHA-256 `f657ed81ca4cce89c0331b423c33bd981a517a5a5d848fd21b8c3087d9955993`；Root将新增谓词块还原为原断言作AST对照，整个原AST完全一致，恰好1处语义块变更（ROOT-D-recovery-semantic.json）。原D恢复段自然CLI0，备份及validator正反例通过，原v1实际窗口采用链副本在新validator下仍完整有效（987,136字节，SHA-256 `7c92012e47fa5b4a89a76259ee6ffe3399b9d0b13745713972daa4b4d8f4baf2`）。首截断文件、失败输出、中断回执、恢复报告与差异均保留。

最后原C仅清除面板和UI测试的文件末空行；Root逐字节确认除尾部CR/LF外内容相同，25个未跟踪文件的独立空白检查全部通过（首失败也保留）。前述271来源至构建来源只差这两处非语义末尾；最终285文件摘要为`ee38fabd35a74b31e13b85a865ab3a8aa1e52dab5c0e23ec4f1486e22eb30e56`。C6全部前端测试、真正挂载输入及异步探针结论保持其明确范围；新完整Vite构建也通过。

## 13. 真实应用契约2生成与明确采用

新合成副本`C:/kgm-q56-live-20261103-r03`在发送前断言游戏／材料个人提示head为2/1，使用正常服务和AiExecutor，不重试旧冻结v1任务冒称新合同。游戏r07：task `qwYXgayWJeGZ0D5lbXN25Q`，HTTP200／deepseek-flash，1发送／1attempt／1候选，usage为1,844输入＋3,262输出＝5,106 token；生成保持草稿v2，明确预览采用后才v3。

材料r08为另一明确操作：task `omBGhFBqZuCqSAPFbY4z_g`，同为HTTP200／deepseek-flash及提示2/1，1发送／1attempt／1候选，含7项；usage为1,509＋3,914＝5,423 token。生成保持v3，明确预览采用后才v4，材料正文24字符、provenance存在，无自动串发、自动采用或确认。只记录安全状态、计数、usage和校验枚举，不记录原响应／思考／密钥。

本轮实际应用发送共7次：旧同task的3次unknown及2次完整但output_invalid，另有新契约游戏／材料各1次成功；这些次数与开发CLI调用数分开。用户已接受显式重复费用，未收到余额不足错误，不推断余额数值或未知请求用量。原合成G17数据库／侧文件及受保护凭据4文件最终指纹均保持（ROOT-G3-original-protection-final.json）。

新真实服务采用链通过当前完整backup_validate（ROOT-980b31c315／ROOT-G3-real-v2-database-validation.json），只读备份副本1,150,976字节，SHA-256 `10f1e17b6b72164b13f9c96095ce31142b3fbfa30869b825154a1c2152ccd62c`。这是正常应用服务／执行器链，未经过原生页面，不记作UI通过；私有检查器曾误标actual_ui_chain_valid，已更正为actual_service_chain_valid，首次标记及更正回执保留。

## 14. 新候选构建与独立静态身份

ROOT-G2-gate只放行已取得来源／回归证据的完整构建和静态核查，native_ui_full_pass=false。原D在全新合法根`build/desktop-e14-q56-r01`实际执行Vite、PyInstaller和portable打包，无skip／复用旧产物／安装升级。构建及原D目录54／ZIP59静态均exit0，自然停写；Root另独立复跑相同两项静态检查，分别54／59通过（ROOT-39c12751e4、ROOT-e19b6893ad）。

| 身份 | 本次实际值 |
| --- | --- |
| 来源 | HEAD `51ec4d3271a81b8980833727f466edf0d1f637b2`＋实际dirty来源freeze；285文件摘要`ee38fabd35a74b31e13b85a865ab3a8aa1e52dab5c0e23ec4f1486e22eb30e56`，构建前后稳定 |
| build_id | `e1b727c8-6ba9-4b39-82bf-a6b4fe81cdc3` |
| 运行库／数据库 | CPython3.14.10、Windows x64、标准GIL；`20261102_0008_local_weekly_ai` |
| 前端 | 3个产物，摘要`c59776fca32fefc75ef71b0e44458f29f865b83a04395782177993f757ca2be5` |
| EXE | `build/desktop-e14-q56-r01/package/KGNext-E14/KGNext-E14.exe`；17,147,586字节；SHA-256 `d9e61e5c3ff6552a6b60b866cb34151e65000e9c57a4742749b653e2a8eff321` |
| ZIP | `build/desktop-e14-q56-r01/portable/KGNext-E14-win11-r01.zip`；44,370,339字节／195项；SHA-256 `7a47e3cf74829461c594da042d37c74042e28501d2eddaf912897b76f1d2652f` |

5模板、至0008的迁移及alembic资源匹配，Pillow插件8个；PYZ共1,859模块，实际扫描121个，生产模块不匹配／不可用均0。路径／密钥／绝对元数据、文本及代码隐私检查均0异常，仅既知SBOM项；构建38、目录1、归档1条Python守卫记录无外联拦截。独立检查器也只执行static模式。没有运行EXE、helper或目标PS脚本，没有签名／安装／更新／WebDAV／发行。包内source_commit保持真实构建时HEAD，不因其后普通提交改写成新SHA或旧目标已验身份。

## 15. 原生窗口重试、最终范围及下一步

旧r02源码窗口退出已取得进程exit0，用户恢复桌面后只读检查仍为v4、5任务／5模拟发送及材料null；未观察退出动作，不能记为已验证正常关窗。新r03源码Python／WebView2窗口使用新合成根和同一私有假worker，数据库0008、六提示head及2/1版本正常，播种草稿v2。多次恢复／重新绑定及一次JS内核重置后，先仍报截图0x80070057／输入0x80070005；按用户最后“从远程桌面重试”再次观察，截图调用不再报错但画面全黑，辅助功能仍能读取工作台。一次周计划点击、激活重读及一次Tab均未产生可观察的导航／焦点变化；没有使用盲坐标或改变安全设置。

最后只读检查ROOT-G2-ui-r03-rdp-retry-no-observed-input.json仍是v2、材料null、0任务／execution／attempt／candidate／采用／确认、0模拟发送。该结果只证明尚未完成界面操作，不将黑色捕获归为应用白屏／W6复发，也不记材料采用／手改／leave／重进／确认或无执行器503窗口通过。真实服务链、SFC挂载输入、源代码宿主回归和新包静态分别保持，不互相替代。

最终技术审核在以上限定范围内完成，允许按新精确门禁提交实现和结果；不宣布全46项、G4目标／教师验收或发行通过。metadata-g3-final-precommit.json pass=true，原A/B/C/D最新交付均自然0、固定原会话Flash max、无fork／子代理／换模型；D历史exit8续跑及两次主动中断均作为明确例外保留，不能称全部阶段自然退出。Git按当前分支、准确68文件、raw SHA／暂存blob／parent／tree普通提交，提交身份由Git回执读取，不循环写进本提交；未授权推送。

下一步优先补远程桌面可实际观察操作时的材料页面后半及无执行器手工闭环，然后在适合运行的新Windows11目标环境对本次build_id做Q5/Q6增量包运行、升级／恢复与持久历史核查。已接受39项教师清单、13份／43页Word、微软拼音及W6不重追；新包不继承旧运行／Word结论。已知SAC4551机继续不运行受阻EXE/helper；不改名换根或降低保护。Win10／WPS／干净机、其它显示条件、跨Windows用户、真实断电和长根206等原边界保留；不据本次提交启动签名、更新或发行。
