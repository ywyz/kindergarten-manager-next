<!-- codebase-memory-mcp:start -->
For structural codebase exploration, use the installed `codebase-memory` skill.
<!-- codebase-memory-mcp:end -->

# kindergarten-manager-next

## 当前阶段

本仓库是 kindergartenManager 的全新实现。

2026-10-30当前：用户已授权执行源码合并整理，再推进完整本地备份／恢复，见唯一入口docs/tasks/current.md。先独立审核桌面源码与公开入口，再由原OpenCode正常提交推送并合入main；备份先集中确认范围／恢复／加密等关键产品行为，再由原OpenCode同会话／Go套餐DeepSeek V4.1 Flash max实施，Codex独立审核回修。继续源码验证，不发行、不启动WebDAV，不自动重写公开历史。合并实际状态见docs/bootstrap/desktop-source-integration-review.md。

2026-10-30前项完成：AI手动重试与本项目GitHub Releases最新正式版检查已由原OpenCode同会话／指定Go模型实施，Codex限定源码／合成工程独立通过，RG-R01–R10关闭。源码可只读检查版本、不可下载安装；实际GitHub暂无正式Release。规格见desktop-game-observation.md§5.1、desktop-application-update.md§10，结果见docs/bootstrap/desktop-retry-github-review.md§4。AI失败作为可恢复结果，不自动重发或免除应用缺陷。

2026-10-30 MIT开源准备：用户确认采用MIT，先做开源版、未来如商业化再fork；受控Word模板由本人制作或已取得公开／MIT授权。原OpenCode同会话Go套餐DeepSeek V4.1 Flash max完成模板隐私及必要实现回修，Codex独立核查通过并整理README、维护者和Certum资料。仓库已公开；只清理当前文件不等于历史安全，不自动改可见性／默认分支、重写历史或强推。见docs/bootstrap/open-source-readiness-review.md及唯一入口docs/tasks/current.md。2026-10-28 E14-R01–R06在源码／构建／静态范围已独立关闭并由原OpenCode正常提交推送6b5770c，local759／短根desktop327／完整前端／源码窗口17／旧库升级22／静态26／归档15及190文件r03候选保持各自源身份；SAC4551、E14整体与教师体验未通过，不发行。新模板不得复用旧包结论；旧包、原库／凭据及原始待脱敏证据私下保留，不改系统保护。历史Word／容量／原生保存及D3长根WinError206边界继续分列。

阶段边界：D3-U已推送d52fa8a；D4产品C1–C33、E01–E14及E13六份Contract已核定。数据基础、E03材料、E05／E08保存历史及E06／E07视觉AI服务层限定工程通过；前片独立718项全local／85项相关桌面、容量及真实DeepSeek闭环保持，真实请求共4次含1次unknown且无自动重发，原R13换行误判处理已撤回。当前页面／关闭、Word／原生另存为仅按相应合成环境限定范围通过，完整A01–A22、整包及教师体验未整体通过，MiMo真实未验。后续切片、跨设备、真实冻结更新／安装、发行源、4551、签名／WebDAV／发行不自动启动，D3-A／D2既有边界保持。

**Architecture v2 已确认（2026-10-08）／D0 工程复审通过／D1A 工程通过／D1B原R1–R17在当前Windows 11开发机工程复审通过；R18日计划Word格式修复的代码、新包及页面验收通过，用户已逐页确认长园所2页、合并7页正常，R18已关闭。T6-A／T6-B／T7及微软拼音已验证，本轮教师体验收口；D2 W1数据迁移与凭据保存、W2游戏配置与提示词已通过当前Windows 11合成环境工程核查；W3、W4已由OpenCode实现并通过Codex当前Windows 11合成环境工程核查；W5界面与宿主整合已通过限定源码集成工程核查；W6导出／无AI降级／完整包已通过当前Windows 11合成环境工程核查；指定Word与合成人工子项按2026-10-20用户决定收口，三项事件留作同类再现处理，真实AI未授权；产品与发行未整体验收。** 用户确认见 `docs/adr/0004-local-desktop-architecture-proposal.md`。现有代码仍包含 v1 云端实现，不得将架构确认或局部代码交付写成迁移或产品验收完成。

当前有效架构见 `ARCHITECTURE.md`，决策原因见 `docs/adr/`，模块 Contract 见 `docs/modules/`，实施入口见 `docs/bootstrap/architecture-v2-readiness.md`。

2026-10-19 用户已明确授权继续W6，直接由OpenCode使用Go套餐DeepSeek V4.1 Flash实施，Codex独立核查并交回修复；此前“停在W5／不启动W6”由本次授权替代。W6限定环境工程核查已通过，指定人工子项与三项后续事件按2026-10-20用户决定收口：跨120秒睡眠不再验证，白屏等复发，额外任务用户倾向误点、保留观察；同类再现一并处理。用户已授权本次相关源码／测试／文档提交并推送，仍不调用应用真实AI或发布。最新入口见`docs/tasks/current.md`及`docs/bootstrap/desktop-d2-w6-closeout.md`，不把不再追测写成已验证／已修复。

架构确认不等于代码、迁移、安装、付费 AI 调用或部署授权，按用户当前任务范围执行。

2026-10-20后续普通包已由OpenCode整合、Codex核查通过，N01／N02关闭，证据见`docs/bootstrap/desktop-d2-normal-package-review.md`§6，修改已推送（2cafa49）。2026-10-21用户确定应用只接DeepSeek官方与MiMo标准API，不接Token Plan／Go；并确认实时思考默认展开、可折叠、阶段／等待时间显示，已由OpenCode Go套餐DeepSeek V4.1 Flash实现并经Codex限定合成工程核查通过（源码窗口33项、新普通包142项），R01–R11关闭；规格见`docs/specs/desktop-ai-streaming-progress.md`，最终证据与新包身份见`docs/bootstrap/desktop-d2-streaming-review.md`§11。G17方案见`docs/bootstrap/desktop-d2-g17-acceptance-plan.md`；不设计预算，应用真实AI／发布仍未授权，旧包与人工数据保持。

## 核心原则

这是一个 clean-slate 项目。旧 kindergartenManager 仅作业务行为、Word 模板、已验证规则和历史经验参考；不得因代码已存在就复制或迁移。默认重新设计，复用旧代码须经过明确审查。

## 当前产品方向与技术栈

面向教师个人的本地教育工作支持应用，首发保证 Windows 11，Windows 10 后续验证，其他系统以后考虑；不需要手机编辑、同时编辑、同班查看或管理员集中管理。

2026-10-08 已确认：一个本地教师档案，首次填写姓名、班级和学期后直接进入工作台，无需旧注册、登录与管理员分班。用户说明云端目前没有数据，首版从全新本地数据开始，不安排旧业务数据导入；不得据此清理旧远程资源。

Architecture v2 已确认：

- 前端：Vue 3、TypeScript、Vite、Element Plus。
- 本地业务：Python、FastAPI；保持前后端分离，通过本机 API 通信。
- 数据访问与迁移：SQLAlchemy 2.x、Alembic；本地数据库 SQLite，替代桌面版 MySQL 服务，模型与迁移仍须适配验证。
- 桌面窗口：优先验证 pywebview＋WebView2；PyInstaller 为打包候选，发行方案尚未实测定版。
- AI：由教师电脑调用供应商；不承诺消除所有超时。
- 跨设备与备份：WebDAV 一致性快照、接续检查与恢复，协议待细化。
- 历史版本：数据库业务版本与确认快照；Git 留作后续候选。

不得自行扩展技术栈；ADR 0001–0003 中冲突的云端部署、MySQL、多人权限与 S3 首选规则已由 ADR 0004 替代，不再作为桌面默认值。

## 业务顺序与边界

先完成每日活动计划，再做游戏观察记录。AI Service、提示词、本地身份与班级配置、保存和 Word 导出按每日活动计划需要配套细化。周计划不是孤立模块：游戏只参考制作者本人的日计划与班级配置，另一位教师的集体活动名称、晨间谈话主题由制作者输入；其他 AI 输入与触发细节仍需规格确认。

一对一倾听、人数管理、因病缺勤统计、退费表格、周计划后续能力与拍照点名后置，不因架构讨论自动启动。单档案内部标识、配置细节与观察记录具体流程按规格落实，不得自行猜测。

## Agent 权限

产品行为由用户决定，Agent 不拥有产品需求最终解释权。不得自行增加需求、改变教师工作流程、为技术便利改变产品行为、重构无关功能、扩大任务范围或为“架构更先进”增加组件。不确定的产品行为须明确列出。

**OpenCode 是实现代码、测试、迁移及构建打包脚本的唯一写入者；Codex 负责技术核查、规划设计文档、审阅、执行相关验证及 Git／发布管理。** 各项操作须匹配当前有效授权，不默认发布；已有授权范围内持续推进，不重复索要确认。协调或审阅不另起实现者，历史特定轮次的直接修复或部署授权不自动延续到本轮。

## 当前开发环境

以 Windows 11 原生开发为主，使用 Windows 本机 VS Code／终端，OpenCode 原生运行，当前桌面 Codex 协调。无需迁入 WSL；WSL 仅作独立辅助，不与 Windows 共用虚拟环境、`node_modules` 或运行库。继续使用当前分支 `codex/desktop-v2-foundation`，不因本轮文档和交接另建分支。

## Skills / MCP 临时规则

Skills / MCP 审计约束继续有效，不因实施、桌面方向或环境迁移自动解除。完成审计前：

- 不得为了任务主动安装新 Skill 或 MCP Server。
- 不因全局存在某 Skill/MCP 就认定项目必须使用。
- 简单文件搜索、Git、测试等普通任务不要求知识图谱工具。
- 对已有 Skill/MCP 的处理先审计，再决定 KEEP / DISABLE / REMOVE-CANDIDATE。

## Architecture Governance

`ARCHITECTURE.md` 只描述当前有效的系统级架构事实。单一 Feature 不得自行修改；改变一级技术栈、层级依赖方向、模块边界、数据权威来源或模块通信机制时，停止相关实现并提出 ADR 草案。ADR 未确认前不得实施变更。

## 文档职责

- `ARCHITECTURE.md`：当前系统架构事实。
- `docs/adr/`：架构决策及其原因。
- `docs/modules/`：模块边界与 Contract。
- `docs/specs/`：Feature 规格及适用范围。
- `docs/bootstrap/`：实施入口、审计与阶段报告。
- `docs/tasks/current.md`：唯一当前执行提示词，指向有效规格与必要证据。

任务完成或被替代后，先将提示词中的独有决定、未验事项归并到规格或结果／审阅记录，再删除已跟踪的旧提示词并修正引用，由 Git 保留历史。不新增 `prompt-final-v2/v3` 或归档副本堆积；未跟踪的独有资料不得直接删除。阶段结论写入结果或审阅记录，不留在新的提示词版本中。

AGENTS.md 保持简短，不作为完整项目百科全书。文档中的实现、自动测试与产品验收状态分别记录，不相互替代。

## 当前最高优先级与历史证据

当前优先读取 `docs/specs/desktop-ai-daily-plan.md`（D2产品决定：C1–C17及Q1–Q6已确认，Q7按可配置OpenAI兼容收敛；E1–E5设计核查完成，详见 `docs/specs/desktop-ai-engineering.md`；W1已实施并核查通过，结果见 `docs/bootstrap/desktop-d2-w1-result.md` 及 `docs/bootstrap/desktop-d2-w1-review.md` §12；其余G项按后续工作包验收，W2已由OpenCode使用Go套餐DeepSeek V4.1 Flash实现并经Codex核查通过（desktop-d2-w2-review.md §8）；W3工程核查通过（desktop-d2-w3-review.md §7）；W4候选与原子采用工程通过（desktop-d2-w4-review.md §10），W5限定源码集成工程通过（desktop-d2-w5-review.md §8），W6限定环境工程通过（desktop-d2-w6-review.md §9））、`docs/specs/desktop-manual-daily-plan.md`（§12.4格式、§13.4验证范围）、`docs/bootstrap/desktop-d1-review.md`（§20.9人工收口）、`docs/bootstrap/desktop-d1-result.md`（§20.8、§21）及 `docs/tasks/current.md`。原R1–R17工程通过历史保持；R18代码、新c6dc1928…包与页面验收通过，已关闭。独立121导出相关／146桌面、137文件／12模块同源、3次真实窗口通过；用户逐页确认长园所2页、合并7页及起始页1／4／6正常。T6-A／T6-B／T7人工通过；配置v4、新旧表头、两份单日文件及退出已核对，本轮Windows 11＋Word教师体验收口。用户明确微软拼音正常、无需复验、不需穷举输入法，取消原IME细分待办。当前D2设计核查及实施清单已完成，不重复询问已确认Q1–Q7，W1已完成（独立286项全local、18项迁移及冻结凭据重启探针通过），W2游戏配置与提示词已工程通过，当前无剩余W2编码任务；W3已通过工程核查；W4由OpenCode使用Go套餐DeepSeek V4.1 Flash实现，Codex独立470项全local／146项桌面及真实本机HTTP复核通过，R01–R09关闭，当前无剩余W4编码任务；W5限定源码集成已独立核查通过，见desktop-d2-w5-review.md §8；W6由OpenCode使用同一指定模型实施，Codex独立477项local／168项桌面、前端及新包130项通过，54归档模块及真实入口同源，见desktop-d2-w6-review.md §9；后续指定Word／合成人工结果及三项事件处理见desktop-d2-w6-closeout.md；G17真实AI未授权，不调用真实AI、WebDAV或发行。原体验库与文件保留，自动验证仅独立合成库或副本。部分窗口分支、干净机器、Win10、WPS、其他DPI／多显示器及发行再现性仍未验。CPython3.14.7／Windows x64／标准GIL保持；原业务26包版本不变，E03新增Pillow后的27包见本片核查，3.12异常保留。班级维护／升班、多学期和旧计划编辑已确认，多班新增／切换后置。旧规格按 `docs/specs/ai-capabilities-implementation.md` 映射。

I1–I4、I5 Word 导出片 1–3 和 AI 1A–1C 是 v1 历史成果。I5 已实现链路收口见 `docs/bootstrap/i5-final-closeout-2026-10-03.md`；完整 W6 非空材料仍须随材料能力真实下载并逐页补验。AI 1C 的 C5 v2 已验范围以 `docs/bootstrap/ai-slice1c-fixture-c5-windows-result-2026-10-07.md` 最新结果为准，剩余项见 `docs/bootstrap/ai-slice1c-fixture-windows-handoff-2026-10-07.md`，不将局部通过或未验写成全体验收结论。这些结果不等于桌面版通过，也不因转向而改成全通过。

旧远程实例、数据和记录保留；不自动续跑云端夹具或修改远程环境。旧云端未结项不作为桌面方向的总阻塞。桌面交付需验证目标 Windows、本地运行与数据、真实 AI 任务状态、文件保存及 Word／WPS；具体范围按切片定义。

文档总入口见 `docs/bootstrap/README.md`。不重新开展无关的环境全面审计，不把旧项目功能当作新版需求。
