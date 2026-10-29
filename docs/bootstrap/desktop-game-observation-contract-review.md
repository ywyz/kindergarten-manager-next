# D4-E13：游戏观察Contract独立核定

> 公开版隐私处理（2026-10-30）：本机用户路径、私有部署地址或联系标识已替换为占位符；原始记录由维护者私下保留，历史日期、结论和产物哈希不因此改变。

更新：2026-10-26。**结论：E13 Contract设计核定通过，已归并观察主模块及身份／班级、AI、提示词、Word、审计五份扩展。** 仅批准本文及有效Contract中的设计约束；观察未实施，A01–A22全部仍待运行验证，没有新增迁移、图片、AI、宿主、Word或打包通过结论。

后续接续（2026-10-26）：用户另行授权的E01／E02／E04已进入实施与独立核查，见[数据基础核查](desktop-game-observation-foundation-review.md)。本文“仅设计／暂不实施”为本轮设计核定时点结论；后续授权仅覆盖上述切片，其余范围不变。

## 1. 授权、基线及有效文档

用户本轮明确要求：按既定顺序先让原OpenCode会话提交E13草案，由Codex独立核定，问题交回同一会话修订，通过后归并文档，暂不实现。继续分支codex/desktop-v2-foundation；不另起会话、实现者或分支，不提交推送。

基线为[产品C1–C33、A01–A22及R01–R14](../specs/desktop-game-observation.md)、[E01–E14工程设计](../specs/desktop-game-observation-engineering.md)及[前轮K01–K08](desktop-game-observation-engineering-review.md)。本轮不重问已决定产品行为，不新增观察个人指导编辑器、任意图数／人数／导出份数额度或AI选图子集。

| 有效文档 | 本轮归并范围 |
| --- | --- |
| [观察Contract](../modules/game-observations.md) | 内容／材料／版本权威，字段及聚合hash，AI完整来源链，保存／采用／恢复幂等，固定导出与宿主回执 |
| [身份与班级](../modules/identity-and-class.md) | 新建带入、任意日期／同日多份、明确归属及历史不反写配置 |
| [AI Service](../modules/ai-service.md) | 一套状态机、业务input冻结与执行版本时点、全部照片、视觉边界、采用责任隔离 |
| [提示词](../modules/prompts.md) | 两类固定bundle／四栏五领域、简短说明与协议分层、守卫后种子及版本兼容 |
| [Word](../modules/word-export.md) | 三模板、缺项／空记录／坏图、固定选集、受限export_id与原桥隔离 |
| [审计](../modules/audit-log.md) | 非敏感元信息、事务一致、token／姓名／文件名／路径不入日志 |

六份Contract与工程正文已同步。旧草案相反句不作为有效协议；临时原稿、反馈及失败证据保留，不在仓库堆积提示词或草案版本。

## 2. 原会话、三轮交付与审计

继续原会话ses_ead8af71dffeJphI1NOWg4jZgI，历史标题“D2 W6 导出打包工程实施”；该标题不扩展本轮权限。使用现有OpenCode CLI 2.1.2、plan代理及固定opencode-go/deepseek-v4.1-flash#default；没有fork／另建会话。派发仅允许只读规划和回复草案，Codex写入规划文档，未代写实现。

证据根：`<LOCAL_USERPROFILE>/AppData/Local/Temp/kgm-observation-contract-20261026-8a816ea1/`；本机指针`%TEMP%/kgm-observation-contract-current.txt`。Temp不是永久交付仓库，核定所需决定与修正已归并本文及Contract。

| 轮次 | 实际交付／审计 | 独立处理 |
| --- | --- | --- |
| r01 | 完整主Contract及五扩展；CLI exit0；5条assistant均指定模型／plan，finish stop，9次read；501份非凭据仓库文件hash零变化 | 不通过，D01–D09交回原会话 |
| r02 | 完整替换稿；exit0；1条assistant同模型／plan，finish stop，0工具调用；501份hash零变化 | 主体补齐，仍有具体约束／语义缺口，交V01–V08精确修订 |
| r03 | 逐条接受V01–V08，声明旧相反句作废，补充必要澄清；exit0；1条assistant同模型／plan，finish stop，0工具调用；501份hash零变化 | Codex吸收合理澄清、归并唯一正文，独立核定设计通过 |

按本轮初始user消息边界审计：r01为msg_176a36120001x7VEBE10Y9QkOT，r02为msg_176aa458e001jXSQAWWan2bGVo，r03为msg_176b00d3c001RGx8yJF4E2D9da。未用旧session outcome猜当前完成；结合CLI真实退出、最后finish及更新后的idle/succeeded。

证据包括request-r01.md、r01-review-feedback.md、r02-final-review-terms.md、contract-r01/r02/r03.md、各轮JSONL／stderr／exit、脱敏session导出、r0N-model-repository-audit.json、repository-r0N-before.json及independent-source-review.json。501份基线取自Git已跟踪／非忽略文件中可解析的非凭据路径；派发前已含Codex更新的当前任务。一份Git转义显示的历史中文DOCX未纳入此SHA256基线，最终补以工作文件Git blob和HEAD逐项匹配；未将其误记成新文件。哈希结论仅限该范围，不称全盘或真实数据审计。

## 3. D01–D09：首稿退回与关闭依据

| 编号 | 首稿问题 | 最终有效条款 |
| --- | --- | --- |
| D01 | 来源／材料关联只概括，缺四表完整约束与守卫后种子 | 主Contract§3完整非空链、父键／旧daily保留、派生与同record约束；仅DDL／新列回填，两次guard后seed |
| D02 | 将照片简短说明误写成观察个人指导UI；视觉／生成边界不足 | §6固定bundle，不增编辑器；C11/C32边界、全图及视觉／旧文本隔离 |
| D03 | 历史归属、无变化恢复、token已消费后的读回不完整 | §5默认完整历史，仅明确决定覆盖；无变不增计数，回执优先 |
| D04 | 客户端fingerprint及各域回执权威含糊 | §4服务端稳定fingerprint；观察operations主回执／恢复细节、AI回执、宿主报告分域 |
| D05 | review_ack裸bool不能证明对当前来源复核 | §6.3一次性预览绑定及当前差异决定，同候选账本例外、原子采用 |
| D06 | snapshot／token／宿主结果与失败重试未闭合 | §7固定manifest、受限桥、实际IO证据、四态、受控流与有效快照重建 |
| D07 | 审计把原始export_id当普通字段 | §8及审计扩展禁记bearer token／会话／姓名／filename／真实路径，只用非敏感引用／摘要 |
| D08 | auto成功后仍应留历史可能被clean状态跳过 | §5以最近保留节点比较，adapter处理待保存与待留节点；失败留页，不强迫采用候选 |
| D09 | 材料格式及Word缺项／版式／选择边界缺漏 | §7–§8与Word扩展补格式、动画拒绝、方向／去元数据、三模板、明确选集及空记录定义 |

## 4. V01–V08：最终修订及必要澄清

| 条款 | 核定后的唯一协议 |
| --- | --- |
| V01 | records的creator/id父UNIQUE及历史指针deferred FK明确；derivative的record/asset/id三元键与input_photo三元FK防同record内错图；保留旧candidate FK真实父列及既有UNIQUE，不混列序；恢复细节关联operations及同record历史 |
| V02 | payload_hash唯一为SHA256(canonical_json([平铺payload,有序原图manifest]))；term_snapshot只出现一次；工作图及发送依赖另hash |
| V03 | 手工恢复完全不查AI就绪；有效payload/hash及事务写集合一致，无变不增revision/version；仅表头且无四栏正文／有效图才为空 |
| V04 | 通用save_reason仅auto/manual/leave/pre_restore/pre_export；采用／恢复须独立协议；所有写先匹配回执，再做token／当前版本等检查，写事务内再查；不以变化后的当前值重算旧请求fingerprint |
| V05 | 预览绑定当前候选／目标／实际依赖／差异／期限；来源变化后提交adopt_reviewed决定，正常采用不多审批；不认裸bool或仅相同文字；不能复核覆盖坏图／不兼容合同 |
| V06 | snapshot及token绑定profile/launch/session scope，ID不是读取凭证；宿主为外部写入结果来源，经固定API报告，宿主不直连SQLite；同token不重复开对话框，未知为indeterminate；流完成再释放产物，重试只用有效固定snapshot |
| V07 | 业务基础发送字段为类型、日期／起止时段、成人／儿童数、统一年龄、重点姓名及环境；不发送园所／班级／观察者文字、学期快照或内部ID；完整生成含已有四栏，重写按实际矩阵；提交冻结图／参数，开始执行取最新有效配置／提示词并记录实际版本 |
| V08 | 归并为一份主Contract和五扩展，同步工程及唯一入口；仅设计、A项待运行，ARCHITECTURE不改，不自动实施或Git提交推送 |

r03的必要澄清已采纳：review_decision是**来源变化后、提交时**对当前预览差异的决定，预览只绑定差异及允许决定，正常采用不要求该字段；AI就绪只用于AI提交，恢复不检查；execution记录input已冻结并实际使用的派生参数，不在claim时另选工作图参数。没有拒绝项或剩余设计冲突。

## 5. 独立源码、图谱及一致性核对

按已安装codebase-memory进行任务限定Verify查询：项目C-Users-yw980-code-kindergarten-manager-next，开始时generation为2026-10-26T05:12:08Z，末次错误符号覆盖返回自动刷新后的05:45:38Z。查项目／schema、AI模型／create_task、effective_prompt_seed及双向直接调用、历史和错误符号；覆盖检查提示相关源码metadata_changed，故回读限定源码，不把no_recorded_issue当完整覆盖证明。未主动重建索引或安装工具，无全仓库穷尽性结论。

源码核对的重要事实：

- 现有models、ai_inputs／task_service／candidates／adoption及日计划API仍绑定日计划；E13的新观察来源链、任务适配及表均是设计，不能描述为已有能力。
- 现有task提交先读回执，再检查执行器／配置并在事务内再查；E13沿其幂等原则扩展，不放宽或重构旧daily域。
- runtime在升级提交后复核后才同步prompt；profile初始化动态读取已注册bundle；d1_digest捕获旧业务表／列，迁移提前插种子会破坏保护，不能绕guard。
- 现有executor／worker／transport构造文本请求并有1MiB及IPC保护；视觉必须独立协议及容量验证。宿主旧save_docx有30MiB保护、文件名＋内容指纹和保存结果，不足以证明新export_id通道已实现。
- 现有日计划历史、Word导出及leave接口只作为复用审查依据；观察需覆盖待留节点、当前稿固定快照、未采用候选可离开及原生保存／更新协调，不能照搬后改变教师行为。

本轮只核对与Contract有关的源码及文档，没有运行应用测试、合成库、迁移、容量探针、窗口或Word。文档校验及最终差异／非文档哈希核对不代替A01–A22验收。

归并校验：15份相关Markdown识别的272个相对链接（含1个合法目录链接）及51个标题锚点均有效；Git diff --check通过。最终376份基线内非文档文件SHA256零变化，补查的历史中文DOCX blob与HEAD一致，ARCHITECTURE.md未变；本轮只新增观察主Contract及E13报告两份Markdown。证据见document-link-check.json、final-scope-check.json；旧未提交设计文档已保留，未删除未跟踪独有资料。

## 6. 停止点与后续准入

E13设计门槛已完成，当前停止在设计核定及文档归并；不自动派发E01/E02/E04或任何实施切片。未来实施仍由原OpenCode唯一写入，Codex独立核查，须后续授权。

canonical字节、原图／像素／派生、完整请求／Base64／IPC、工作集／复制／并发、超时、DOCX／分块／磁盘及token期限等必须后续合成容量验证再冻结；显著影响教师流程的上限交用户决定，不以先前提案值当已验参数。Pillow、插件／编码器、锁／许可／打包及模板同源均没有本轮运行证据。

迁移／守卫／冷升级、来源FK拒绝、原子保存／恢复／采用、假供应商及发送前后故障、材料／路径／链接边界、宿主另存为与未知结果、真实Windows窗口和Word逐页都仍待验。真实AI、冻结包／真实安装更新、签名／发行、Win10／WPS／干净机器及既有D2/D3未验范围不变。

本轮仓库变化仅Markdown：六份Contract、独立核定记录、相关规格与状态入口。未动实现／测试／迁移／构建／依赖锁或ARCHITECTURE.md，未读真实密钥，未修改旧库、体验文件、OneDrive原件、旧包或远程资源；未真实AI／WebDAV，未提交推送。唯一当前入口为[docs/tasks/current.md](../tasks/current.md)。
