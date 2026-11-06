# 文档维护核查与历史边界归并

最新维护见 §6。§1–§5 保留 2026-11-01 的分支、核查方法和历史边界。

## 1. 范围与分支结论

实际本地分支 `codex/desktop-v2-foundation`，HEAD `2a4694893a083e32ba6203bfee6dbd83f890f02e`。远端桌面分支同值；远端main／默认HEAD为 `e836726f008676fc603a7b4cb058e5d96cafe60b`／main。两个分支并非同一版本，文档不能把main称作最新桌面成果。继续当前桌面分支，不切换、不合并main、不改默认分支。

用户验证固定r03候选；新周计划设计和未来合成开发不改变其ZIP身份。受控并行建议先G0/G1，进入G2前检查目标启动、保存重开及备份恢复基础反馈；Word逐页可并行。若只有签名／系统策略阻挡，可继续源码工程；发现通用保存／恢复／关闭缺陷则暂停相交文件，先修共同基础。当前没有启动这些原生实施会话。

## 2. 已处理的文档问题

| 问题 | 处理 |
| --- | --- |
| AGENTS过长、旧D2／B1-B2仍称当前 | 保留当前门槛与权限，具体旧数字／授权／边界原文归本记录§5；新执行只读current及有效规格。 |
| README把main当最新源码，状态仅旧E14 | 区分已合并main与桌面分支；更新备份／内部候选／周计划设计状态及源码克隆分支。 |
| ARCHITECTURE含尚未SQLite迁移／观察未定义等过时进度 | 只清除实施时点判断，改为架构职责及规格链接；未改变技术栈、层次、数据权威或模块通信，不构成新ADR。 |
| v2实施入口仍停10月27日、基础规格仍当前D1A／E03 | v2入口给最新摘要；早期foundation正文保留并标历史，旧门槛不代替唯一任务。 |
| AI适用索引及模块Contract混用旧待定状态 | 接六项已决周计划、现有D2／观察／备份结果；历史段标时点，保留未验限制。 |
| 旧部署／G17计划仍像当前授权 | 加历史横幅并指结果及current，不删除独有材料或重放操作。 |
| 5条证据下载链接指旧环境 | 保留文件名和历史位置说明，去掉不能兑现的下载链接；不删除实际证据文件、不虚构附件。 |

## 3. 删除与保留结论

`git ls-files -- docs/tasks`只有唯一`docs/tasks/current.md`，没有发现可直接删除且无独有内容的旧执行提示词。v1 fixture／handoff已有历史说明，保留资源恢复边界、失败／未验案例；历史报告不因日期旧就删除。未跟踪的周计划规格／工程／阶段计划是本轮在用资料，保留。用户授权的“更新或删除”按实际证据执行，本次选择更新、归并和去误导状态，不为减少文件数删除有效记录。

## 4. 检查方法和限制

对根README／ARCHITECTURE／AGENTS和docs内Markdown自动扫描本地链接、UTF-8及当前状态候选；人工定向审入口、治理、相关Contract、foundation／AI适用索引及旧计划。另两个只读审阅分别核历史计划和治理／模块状态；不声称逐条重新验收所有历史技术结论。初扫151份Markdown／1385本地文件引用，5条不可访问目标全是历史环境证据，仓内引用目标没有缺失。最终检查与具体改动范围以本轮实际Git差异为准，不拿文档校验代代码／Word测试。

最终校验：扫描**152份Markdown、1427条本地文件引用**，缺失目标0；UTF-8及git diff --check通过。本次清理实际触及20份文档；工作区23份文档改动包含此前未提交的周计划规划／规格，不是本轮新改了23份。没有删除已跟踪文档，代码／迁移／模板未改，r03 ZIP SHA仍为 `0a1b9c0b55612de889e621f70ed1374d8e792d3755d9fce1eadf17b7b6532470`。分支／HEAD及远端引用只读核对未变，当前未提交／推送。

后续接续：用户已明确要求记录明暗模式、更新实施提示词并提交推送。§4“未提交”描述的是整理完成时点；本次具体Git按Codex精确清单由原OpenCode执行，实际身份以Git历史／独立回执为准，不在本文回填自身SHA。当前未启动源码开发、构建或替换用户r03包。

## 5. 原AGENTS历史阶段与独有边界归并

**以下为整理前的历史原文，不是新的当前任务或操作授权。** 保留当时数字、提交身份、未验与用户决定，不能把旧“当前”“下一步”“允许真实调用”等字样用于自动恢复实施。最新执行仅见[current.md](../tasks/current.md)，新产品以各有效规格为准。

### 5.1 旧阶段记录（截至2026-10-31及此前）

2026-10-31当前：完整备份／恢复的源码范围结论及91e6a553前轮回执保持。用户随后授权两OpenCode／两Command Code原生会话（DeepSeek V4.1 Flash max）实施完整未签名Win11内部便携候选，Codex独立审核：最终493 desktop、r03实际目录54／ZIP59静态及本机PS7只读预检49通过；实际根build/desktop-e14-win11-r03，逻辑ZIP文件名仍含r01，身份以结果／SHA为准。首候选失败、旧包、原资料及历史边界保留。见docs/bootstrap/desktop-windows11-portable-result.md及desktop-windows11-portable-review.md；唯一下一步入口docs/tasks/current.md，目标手册desktop-windows11-portable-manual.md。另一台Windows 11尚未操作，普通运行／Word／教师体验未验，PS5.1仅解析通过且文件执行受策略阻止，签名证书申请中。不在已知4551电脑执行候选，不降低保护、不自动签名／真实AI／WebDAV／远控或公开发行；原OpenCode仅按Codex具体Git清单普通提交推送。

2026-10-30前项完成：AI手动重试与本项目GitHub Releases最新正式版检查已由原OpenCode同会话／指定Go模型实施，Codex限定源码／合成工程独立通过，RG-R01–R10关闭。源码可只读检查版本、不可下载安装；实际GitHub暂无正式Release。规格见desktop-game-observation.md§5.1、desktop-application-update.md§10，结果见docs/bootstrap/desktop-retry-github-review.md§4。AI失败作为可恢复结果，不自动重发或免除应用缺陷。

2026-10-30 MIT开源准备：用户确认采用MIT，先做开源版、未来如商业化再fork；受控Word模板由本人制作或已取得公开／MIT授权。原OpenCode同会话Go套餐DeepSeek V4.1 Flash max完成模板隐私及必要实现回修，Codex独立核查通过并整理README、维护者和Certum资料。仓库已公开；只清理当前文件不等于历史安全，不自动改可见性／默认分支、重写历史或强推。见docs/bootstrap/open-source-readiness-review.md及唯一入口docs/tasks/current.md。2026-10-28 E14-R01–R06在源码／构建／静态范围已独立关闭并由原OpenCode正常提交推送6b5770c，local759／短根desktop327／完整前端／源码窗口17／旧库升级22／静态26／归档15及190文件r03候选保持各自源身份；SAC4551、E14整体与教师体验未通过，不发行。新模板不得复用旧包结论；旧包、原库／凭据及原始待脱敏证据私下保留，不改系统保护。历史Word／容量／原生保存及D3长根WinError206边界继续分列。

阶段边界：D3-U已推送d52fa8a；D4产品C1–C33、E01–E14及E13六份Contract已核定。数据基础、E03材料、E05／E08保存历史及E06／E07视觉AI服务层限定工程通过；前片独立718项全local／85项相关桌面、容量及真实DeepSeek闭环保持，真实请求共4次含1次unknown且无自动重发，原R13换行误判处理已撤回。当前页面／关闭、Word／原生另存为仅按相应合成环境限定范围通过，完整A01–A22、整包及教师体验未整体通过，MiMo真实未验。后续切片、跨设备、真实冻结更新／安装、发行源、4551、签名／WebDAV／发行不自动启动，D3-A／D2既有边界保持。

**Architecture v2 已确认（2026-10-08）／D0 工程复审通过／D1A 工程通过／D1B原R1–R17在当前Windows 11开发机工程复审通过；R18日计划Word格式修复的代码、新包及页面验收通过，用户已逐页确认长园所2页、合并7页正常，R18已关闭。T6-A／T6-B／T7及微软拼音已验证，本轮教师体验收口；D2 W1数据迁移与凭据保存、W2游戏配置与提示词已通过当前Windows 11合成环境工程核查；W3、W4已由OpenCode实现并通过Codex当前Windows 11合成环境工程核查；W5界面与宿主整合已通过限定源码集成工程核查；W6导出／无AI降级／完整包已通过当前Windows 11合成环境工程核查；指定Word与合成人工子项按2026-10-20用户决定收口，三项事件留作同类再现处理，真实AI未授权；产品与发行未整体验收。** 用户确认见 `docs/adr/0004-local-desktop-architecture-proposal.md`。现有代码仍包含 v1 云端实现，不得将架构确认或局部代码交付写成迁移或产品验收完成。

当前有效架构见 `ARCHITECTURE.md`，决策原因见 `docs/adr/`，模块 Contract 见 `docs/modules/`，实施入口见 `docs/bootstrap/architecture-v2-readiness.md`。

2026-10-19 用户已明确授权继续W6，直接由OpenCode使用Go套餐DeepSeek V4.1 Flash实施，Codex独立核查并交回修复；此前“停在W5／不启动W6”由本次授权替代。W6限定环境工程核查已通过，指定人工子项与三项后续事件按2026-10-20用户决定收口：跨120秒睡眠不再验证，白屏等复发，额外任务用户倾向误点、保留观察；同类再现一并处理。用户已授权本次相关源码／测试／文档提交并推送，仍不调用应用真实AI或发布。最新入口见`docs/tasks/current.md`及`docs/bootstrap/desktop-d2-w6-closeout.md`，不把不再追测写成已验证／已修复。

架构确认不等于代码、迁移、安装、付费 AI 调用或部署授权，按用户当前任务范围执行。

2026-10-20后续普通包已由OpenCode整合、Codex核查通过，N01／N02关闭，证据见`docs/bootstrap/desktop-d2-normal-package-review.md`§6，修改已推送（2cafa49）。2026-10-21用户确定应用只接DeepSeek官方与MiMo标准API，不接Token Plan／Go；并确认实时思考默认展开、可折叠、阶段／等待时间显示，已由OpenCode Go套餐DeepSeek V4.1 Flash实现并经Codex限定合成工程核查通过（源码窗口33项、新普通包142项），R01–R11关闭；规格见`docs/specs/desktop-ai-streaming-progress.md`，最终证据与新包身份见`docs/bootstrap/desktop-d2-streaming-review.md`§11。G17方案见`docs/bootstrap/desktop-d2-g17-acceptance-plan.md`；不设计预算，应用真实AI／发布仍未授权，旧包与人工数据保持。

### 5.2 旧并行例外与当时门槛

2026-10-30本轮用户进一步允许多个OpenCode会话并行：均使用Go套餐DeepSeek V4.1 Flash max，按明确文件责任分工，共享核心与Git整合仍由原会话负责；Codex统一独立审核。不fork原会话、不由各会话另派子代理，不并行改同一文件；B1未通过前，其他会话只做不冲突的设计与验证材料准备，不提前接入B2。

2026-10-31用户进一步允许本轮并行调用已安装的Command Code，固定DeepSeek V4.1 Flash max。仅在Codex明确互斥文件责任后参与实施／测试，作为上述OpenCode唯一写入规则的本轮限定例外；不接管在途会话的文件，不另派子代理。共享整合与最终提交推送仍由原OpenCode负责，Codex独立审核。优先Windows原生，不与WSL共用虚拟环境或node_modules；不安装新工具，不发行。

### 5.3 旧优先级与历史证据原文

#### 原历史标题：当前最高优先级与历史证据

当前优先读取 `docs/specs/desktop-ai-daily-plan.md`（D2产品决定：C1–C17及Q1–Q6已确认，Q7按可配置OpenAI兼容收敛；E1–E5设计核查完成，详见 `docs/specs/desktop-ai-engineering.md`；W1已实施并核查通过，结果见 `docs/bootstrap/desktop-d2-w1-result.md` 及 `docs/bootstrap/desktop-d2-w1-review.md` §12；其余G项按后续工作包验收，W2已由OpenCode使用Go套餐DeepSeek V4.1 Flash实现并经Codex核查通过（desktop-d2-w2-review.md §8）；W3工程核查通过（desktop-d2-w3-review.md §7）；W4候选与原子采用工程通过（desktop-d2-w4-review.md §10），W5限定源码集成工程通过（desktop-d2-w5-review.md §8），W6限定环境工程通过（desktop-d2-w6-review.md §9））、`docs/specs/desktop-manual-daily-plan.md`（§12.4格式、§13.4验证范围）、`docs/bootstrap/desktop-d1-review.md`（§20.9人工收口）、`docs/bootstrap/desktop-d1-result.md`（§20.8、§21）及 `docs/tasks/current.md`。原R1–R17工程通过历史保持；R18代码、新c6dc1928…包与页面验收通过，已关闭。独立121导出相关／146桌面、137文件／12模块同源、3次真实窗口通过；用户逐页确认长园所2页、合并7页及起始页1／4／6正常。T6-A／T6-B／T7人工通过；配置v4、新旧表头、两份单日文件及退出已核对，本轮Windows 11＋Word教师体验收口。用户明确微软拼音正常、无需复验、不需穷举输入法，取消原IME细分待办。当前D2设计核查及实施清单已完成，不重复询问已确认Q1–Q7，W1已完成（独立286项全local、18项迁移及冻结凭据重启探针通过），W2游戏配置与提示词已工程通过，当前无剩余W2编码任务；W3已通过工程核查；W4由OpenCode使用Go套餐DeepSeek V4.1 Flash实现，Codex独立470项全local／146项桌面及真实本机HTTP复核通过，R01–R09关闭，当前无剩余W4编码任务；W5限定源码集成已独立核查通过，见desktop-d2-w5-review.md §8；W6由OpenCode使用同一指定模型实施，Codex独立477项local／168项桌面、前端及新包130项通过，54归档模块及真实入口同源，见desktop-d2-w6-review.md §9；后续指定Word／合成人工结果及三项事件处理见desktop-d2-w6-closeout.md；G17真实AI未授权，不调用真实AI、WebDAV或发行。原体验库与文件保留，自动验证仅独立合成库或副本。部分窗口分支、干净机器、Win10、WPS、其他DPI／多显示器及发行再现性仍未验。CPython3.14.7／Windows x64／标准GIL保持；原业务26包版本不变，E03新增Pillow后的27包见本片核查，3.12异常保留。班级维护／升班、多学期和旧计划编辑已确认，多班新增／切换后置。旧规格按 `docs/specs/ai-capabilities-implementation.md` 映射。

I1–I4、I5 Word 导出片 1–3 和 AI 1A–1C 是 v1 历史成果。I5 已实现链路收口见 `docs/bootstrap/i5-final-closeout-2026-10-03.md`；完整 W6 非空材料仍须随材料能力真实下载并逐页补验。AI 1C 的 C5 v2 已验范围以 `docs/bootstrap/ai-slice1c-fixture-c5-windows-result-2026-10-07.md` 最新结果为准，剩余项见 `docs/bootstrap/ai-slice1c-fixture-windows-handoff-2026-10-07.md`，不将局部通过或未验写成全体验收结论。这些结果不等于桌面版通过，也不因转向而改成全通过。

旧远程实例、数据和记录保留；不自动续跑云端夹具或修改远程环境。旧云端未结项不作为桌面方向的总阻塞。桌面交付需验证目标 Windows、本地运行与数据、真实 AI 任务状态、文件保存及 Word／WPS；具体范围按切片定义。

文档总入口见 `docs/bootstrap/README.md`。不重新开展无关的环境全面审计，不把旧项目功能当作新版需求。

## 6. 2026-11-06 文档同步与功能设计交接

本次基于桌面分支 `b670587`。产品提交为 `b657363`，随后两次提交交付原 Windows 11 测试机的运行与键盘回执。README、协作规则、任务入口及两份索引改为指向这些实际结果。周计划、AI、观察、Word、备份的有效规格和模块合同已对齐各自阶段的证据；旧手册与结果继续保留原构建、首失败和环境边界。两处指向已改名章节的历史链接已修正。

核查覆盖仓库内 174 份 Markdown（含新设计草案）的 UTF-8 读取及文档内相对文件、章节引用；另查改动空白与唯一任务入口。本轮只改文档。倾听样例仅用于核对表头、图文配对及评价栏，公开设计采用虚构例子；功能决定见[倾听记录草案](../specs/desktop-one-to-one-listening.md)，执行范围见[当前任务](../tasks/current.md)。
