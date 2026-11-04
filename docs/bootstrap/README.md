# 文档与报告索引

更新：2026-11-04。当前工作按 [AGENTS.md](../../AGENTS.md)、[Architecture v2 实施入口](architecture-v2-readiness.md) 和 [ADR 0004](../adr/0004-local-desktop-architecture-proposal.md) 执行。系统级事实见 [ARCHITECTURE.md](../../ARCHITECTURE.md)，规格与历史报告不等于当前任务授权。

## 当前：回归修复通过，接续测试机增量

已按用户允许普通merge整合ead1e99测试交接与cb4e7ed恢复片，完成旧预期／清理、selftest绑定、观察导出异常终态及轻量spawn夹具回修。Codex独立完整local **1229通过**、desktop **628通过**，前端14脚本／typecheck／D1构建及观察源码窗口17检查通过，549非文档文件验证前后相同，见[回归修复核查](desktop-regression-repair-review.md)。首轮1214／14失败、取消夹具竞态及各负对照保留，不以重试／扩大时限收口。

下一步返回原Windows11测试机，按新提交做完整local及[手动恢复](../specs/desktop-renderer-recovery.md)限定增量；实际renderer／browser故障及独立进程保持的历史源码证据见[生命周期核查](desktop-renderer-lifecycle-review.md)。只按[唯一入口](../tasks/current.md)执行，原配置两根保留、无须为保留配置再发付费请求；新CI候选和目标结论另核。SAC4551不启动受阻EXE／冻结helper或改变保护，不发行。

## 已完成：Q5/Q6目标测试与白屏／并发／Word补核

[目标机独立核查](desktop-weekly-ai-windows11-target-review.md)保留原CI策略拦截、SQLAlchemy与来源一致性修复、三个候选身份、三次真实DeepSeek、新材料Word四页、完整备份／保护包／旧0007恢复和独立重开。[白屏／并发／Word补核](desktop-windows11-white-concurrency-review.md)§1–5的后端62／桌面35为当时限定通过，§6完整回归失败另列；本轮回修见顶部新核查。并发最小测试修复已审核，白屏受控重开数据保持、精确触发未证实，Word当前功能正常但/r历史差异未知。按用户授权普通提交推送后，由[唯一入口](../tasks/current.md)交开发机继续限定源码核查及白屏复现／恢复方案，不改系统保护、不启动4551主系统候选／helper、不发行，新CI制品另核身份。

## 当前：周计划另机补测与教师确认已收口

本轮另机Windows11测试、两项最小回修和新包补测已完成：最终Python3.14.10下90项后端、前端、54／59静态及49只读预检通过，13份独立Word共43页已逐页检查。用户明确“目前全部通过，有问题届时再通过小补丁或者更新的方式修改，请提交并推送”，按本次整体确认收口所列39项教师清单。准确身份、原候选备份恢复与新包补测的范围、首失败和未验边界归[另机测试收口](desktop-weekly-target-test-closeout.md)。本机修复包build_id为`763706b0-c9c0-4064-96b4-f2b8c0b43843`，不能与原GitHub制品或旧r03混用结论；不自动进入Q5/Q6或公开发行。

原GitHub源提交`57806b2`的完整构建／54／59静态／上传及下载侧50项受限复核仍归[原构建核查](desktop-weekly-windows11-review.md)，可重复步骤见[测试手册](desktop-weekly-windows11-manual.md)。旧制品不含本次修复，不能以其下载链接替代修复包身份；后续自动CI制品如有生成，须按各自来源和静态结果另核，不继承本机实际Word／教师结论。

## 固定r03：目标1与指定Word教师确认已收口

2026-10-31 用户授权两 OpenCode／两 Command Code 原生会话（DeepSeek V4.1 Flash max）按互斥文件责任实施并由 Codex 独立审核。[新候选结果](desktop-windows11-portable-result.md)与[独立核查](desktop-windows11-portable-review.md)记录最终 **493 desktop、实际目录 54／ZIP 59 静态通过**；当时开发机 PS7 对新解压副本的只读预检 49 项通过，主 EXE 未签名。首候选静态失败及修正另列，实际 r03 物理根与 r01 逻辑 ZIP 名称按 build_id／SHA 区分。该开发机阶段未启动候选或操作目标电脑，后续目标机实测另列。

[目标机独立测试记录](desktop-windows11-target-review.md)新增 2026-11-01 目标 1 的实际预检、普通业务、完整备份／恢复、原生保存与 W1–W8 Word 工程页检；SQLite 写锁保存失败时保留当前稿并阻止旧稿导出的实测只覆盖该分支。首失败与复验、权限受阻及跳过均保留，不能称所有测试单轮全通过。用户已于 2026-11-01 逐项确认八份 Word 通过，本轮指定 Word 教师体验收口；用户本轮不做跨 Windows 用户恢复测试，该项未验且不列本轮追测。产品及签名／发行未整体验收，原开发机 PS5.1 执行受阻历史保持。

[唯一入口](../tasks/current.md)承接本轮周计划源码收口及下一片新身份候选安排；[中文手册](desktop-windows11-portable-manual.md)保留可重复步骤，[原计划与责任合同](desktop-windows11-portable-plan.md)保留当轮范围。新包须另行核定身份和验证，不能沿用本轮 r03 结论。不运行已知 4551 机器上的候选或降低保护，不自动真实 AI、WebDAV、签名、远控或公开发行。

## 已完成：周计划首片源码工程收口

Q1–Q6已确认；Q1–Q4首片及明暗已实施，backend1006／desktop553／C17完整前端exit0；C18两处历史文案的typecheck／UI13及最后正常重开通过。真实保存确认、旧确认保稿导出、W01五页／W02三页Word、明文／加密备份及保护包接续已有实际结果，详见[实施核查](desktop-weekly-plan-review.md)。[唯一入口](../tasks/current.md)承接精确Git收口与下一片候选安排；[产品](../specs/desktop-weekly-plan.md)及[工程](../specs/desktop-weekly-plan-engineering.md)保持权威，Q5/Q6不提前实现。

## 明暗模式与受控并行实施

[外观规格](../specs/desktop-appearance.md)的两态手动、档案偏好及保持Word／照片边界已实施；独立专项、共享接线及实际light／dark备份恢复、正常重开已核。新候选静态见顶部；目标视觉条件与本轮教师体验仍另验，不以自动测试代替未做的视觉检查。

## 文档适用范围与分支

最新桌面分支为codex/desktop-v2-foundation，main是已合并基线，不因内部测试切分支或替换r03。2026-11-01[文档维护核查](documentation-maintenance-review.md)已修正过时入口、历史计划标识及旧环境附件链接；旧实际证据保留，AGENTS中的独有历史边界已归并该记录。日期旧不自动表示可删除；唯一执行提示词仍为current。

## 已完成：源码合并与完整本地备份／恢复

2026-10-31：[唯一当前入口](../tasks/current.md)对应的源码整理已由原OpenCode正常推送并快进main至`e836726`，见[整合核查](desktop-source-integration-review.md)。[完整本地备份／恢复](../specs/desktop-backup-restore.md)的P01–P06均已确认，B1已推送`7d2759b`，后续核心、宿主及B3真实源码窗口限定工程独立通过，最终 **848 local／469 desktop**、完整前端类型／测试／构建及逐项实际窗口证据见[独立核查§38](desktop-backup-restore-review.md#38-b3-最终限定源码结论完整本地备份恢复通过)。[实现记录](desktop-backup-restore-result.md)保留实施者自测与各轮首失败；原会话已按56文件核定清单普通推送`91e6a553`，实际树／远端／clean及保护源复核见[核查§40](desktop-backup-restore-review.md#40-git-实际收口与下一阶段基线)。源码工作收口；教师人工体验、冻结包与发行尚未通过，最早无guard轮次历史缺口与后续受控guard0证据分列，不启动WebDAV或公开历史改写。

## 已完成：AI手动重试与GitHub更新（源码验证）

2026-10-30用户补充：AI生成可能不稳定，失败／结果不明应可由用户主动重试；更新通过本项目GitHub Releases最新正式版判断。原OpenCode同会话／指定Go模型实施及回修，Codex[独立核查§4](desktop-retry-github-review.md#4-最终独立结论与源码交付)限定源码／合成工程通过，RG-R01–R10关闭：全local761、最终桌面368、完整前端及最终观察62／typecheck、真实源码窗口17。实际GitHub当前无正式Release，源码仅检查、不下载或替换程序；不发行、不执行受阻冻结包、不接WebDAV。唯一执行入口仍为[current.md](../tasks/current.md)。

## 已完成：MIT 开源准备与源码验证

用户确认采用 MIT，先做开源版本，并确认清理后的受控 Word 模板具备公开分发及 MIT 授权；当前继续源码验证。README、维护者、第三方说明和 [Certum 申请资料](../opensource/certum-application.md) 已按 [开源准备检查](open-source-readiness-review.md) 在当前文件范围独立核查：导出／模板117、桌面327、源码窗口17、证据根两种条件各1项及Word10份分页对比通过。仓库已经公开，当前文件清理不等于旧 Git 历史已移除；不自动改默认分支、可见性或重写历史。唯一执行入口仍为 [current.md](../tasks/current.md)。

## 当前阶段：E14源码／静态工程通过，冻结运行待签名

2026-10-28 E14已由原Go套餐DeepSeek V4.1 Flash max会话实施回修，[独立核查§6–§7](desktop-game-observation-e14-review.md#6-最终独立结论源码与静态工程通过冻结整体验证受阻)确认：local759、短根桌面327、完整前端、源码真实窗口17／旧库升级22、静态包26／便携归档15通过，E14-R01–R06在该范围关闭。r03完整候选190文件，便携归档在`build/desktop-e14-r03/dist/`；[实现者结果](desktop-game-observation-e14-result.md)与独立结果分列。本轮DeepSeek2次（整份生成unknown未重发、process重写成功采用重开），5个原配置／DB／凭据源hash保持。SAC4551仍阻止冻结运行；用户准备申请证书，E14整体／教师体验未通过，不发行。已核查源码／文档按授权由原OpenCode正常提交推送，后续签名及整包补验见[唯一入口](../tasks/current.md)。长根WinError206、正式更新源／信任身份及D2／D3未验保持。

此前2026-10-28导出片收口：原OpenCode会话以Go套餐DeepSeek V4.1 Flash max实施及回修，[导出独立核查 §6](desktop-game-observation-export-review.md#6-最终独立结论本片限定工程核查通过)通过，R01–R13关闭：全local758、最终桌面302／导出API专项41、最终全前端（观察54）、HTTP37及真实WebView2 16项；7份合成Word逐页、600图及大于30MiB完整交付、真实原生取消／明确重试／保存与正常关闭有实证。见[实现交接](desktop-game-observation-export-result.md)，由原OpenCode正常提交推送至5808078。当时应用真实AI调用0次，原配置／凭据及旧数据保持；该时点未验不由E14源码／静态结果改写。

前片[页面核查 §6](desktop-game-observation-pages-review.md#6-最终独立结论本片限定工程核查通过)全local728、桌面285、前端观察38、HTTP37及WebView2 9项与实际中文差异预览、勾选四目标采用保存v14结果保持，R01–R15已关闭；该片基线提交b4b2f77，不以本片导出替代其历史证据。

前片E06／E07[服务层核查](desktop-game-observation-ai-review.md)718项全local、85项相关桌面、图文容量及真实DeepSeek生成／五领域重写／采用闭环保持，R01–R12关闭；原R13误判处理已撤回。前片真实请求共4次含1次unknown且不自动重放，与本片合成验证分开记录。

此前[应用更新](../specs/desktop-application-update.md)U1–U3已推送d52fa8a；D4产品／工程／E13设计保持，基础、E03（5e3e46f）及E05／E08（541bc82）证据保留。跨设备、真实更新安装、发行源／4551、教师体验及D2／D3既有未验保持，不安排签名、WebDAV、微软提交或发行。以下各历史轮次保留当时状态及授权，当前观察范围以顶部及唯一任务为准。

此前W6状态与处理决定见[W6收口及三项后续事件](desktop-d2-w6-closeout.md)和[逐项人工记录](desktop-d2-w6-manual-acceptance.md)：已验Word／候选／保存／重启／在途子项保持；跨120秒睡眠不再验证，白屏等复发，额外任务用户倾向误点、保留观察。三项留作同类再现处理，不主动追测，不改记为技术通过／已修复。用户已授权相关Git提交／推送，未授权应用真实AI或发布。

2026-10-20后续授权的[普通运行验证包整合](desktop-d2-normal-package-result.md)已由OpenCode使用同一Go套餐DeepSeek V4.1 Flash完成，并经[Codex独立核查§6](desktop-d2-normal-package-review.md#6-最终独立核查与交付结论)通过：新包位于build/desktop-d2-normal-r01/，普通入口与54模块同源、前端与已验R01一致；独立前端、196桌面、8项构建路径保护及仓外冻结130项通过，旧包及保护数据未变。N01／N02回修关闭；相关修改已按2026-10-21用户授权提交并推送（2cafa49），未上传包、数据库或凭据。

2026-10-21 [G17方案](desktop-d2-g17-acceptance-plan.md)不设计预算限额；[官方文档核对](desktop-d2-g17-provider-compatibility-review.md)后，用户决定应用仅使用DeepSeek官方与MiMo标准API，并确认[实时思考与等待反馈](../specs/desktop-ai-streaming-progress.md)默认展开／可折叠、阶段／计时显示。已由OpenCode沿用原Go套餐DeepSeek V4.1 Flash实现，并经[Codex独立核查§11](desktop-d2-streaming-review.md#11-最终交付限定合成工程核查通过)通过：源码窗口33项、新完整普通包142项通过，R01–R11关闭；新包位于build/desktop-d2-streaming-r10-r11/，旧包与失败材料保留，下一步仅准备G17。应用真实调用0次、尚未授权，不把文档符合或配置ready当作G17通过。

2026-10-22 DeepSeek旧三类真实闭环、v5、冷重启及两份Word技术核查通过，用户确认旧Word两页正常，并提出换行、编号及晨间全户外整改。三项指导r2已完成限定离线核查；r03为182文件、50项归档同源，首轮129/142、同包W5复跑33/33，不声称单轮全通过或窗口波动已修复。**r03新A已审阅采用保存v6；新B成功返回且技术审阅完成，教师确认难度适合但反馈“缺少教师的话”，本轮停在B未采用，新C未发起。** 累计DeepSeek5次attempt，MiMo本轮不测且仍0次；最新快照与反馈见[G17结果§7](desktop-d2-g17-result.md#7-r03真实质量复验2026-10-22)，旧证据保持于§2–6。教师话语r3源码整改与限定离线检查通过，但新teacher-talk-r01包被Windows策略以WinError4551阻止启动，已停止；G17质量未整体通过，完整G18及产品／发行未验，暂不发布。

2026-10-23 [后续定因与关闭处理](desktop-d2-g17-result.md#8-4551定因与设置窗口关闭2026-10-23)：4551已确认是Smart App Control的VerifiedAndReputableDesktop策略拒绝未签名新EXE；无下载来源标记，本机两个My存储无代码签名证书。微软单EXE复核曾获授权，但在登录前停止；用户随后明确取消提交，EXE和说明均未上传，材料保留。国内渠道核对与签名前清点见[G17结果§9](desktop-d2-g17-result.md#9-国内签名渠道与下一步提示词2026-10-23)：腾讯云自营仅企业，阿里云市场Certum个人SKU／用途待确认；现包99个PE候选中76个签名Valid、23个NotSigned。此前个人签名资格提示词现由顶部D3-A任务替代，未联系商家、申请或购买，尚未解除拦截或恢复真实B／C。旧MiMo窗口的独立AI草稿已通过对应取消按钮还原并正常关闭，两库hash／版本／调用数保持。未改安全设置或实现代码。

已进入 `codex/desktop-v2-foundation`，采用 Windows 11 原生开发。OpenCode 写实现、测试、迁移及构建脚本；Codex 负责技术核查、规划设计、审阅、相关验证与 Git／发布管理，均按当前授权执行。

- [唯一当前任务](../tasks/current.md)：D2 W1数据迁移／凭据保存已由OpenCode实施并经Codex核查关闭。[W1实现结果](desktop-d2-w1-result.md)。[产品规格](../specs/desktop-ai-daily-plan.md)、[工程规格及清单](../specs/desktop-ai-engineering.md)、[W1独立核查](desktop-d2-w1-review.md)。W1独立全local286项、迁移18项及冻结重启探针通过，R01–R09已关闭（核查§12）；[W2](desktop-d2-w2-review.md)已由OpenCode使用Go套餐DeepSeek V4.1 Flash交付并经Codex核查通过；[实现结果](desktop-d2-w2-result.md)含后续接口交接；[W3实现](desktop-d2-w3-result.md)及[独立核查](desktop-d2-w3-review.md)已完成，当前Windows 11合成环境工程通过；[W4实现](desktop-d2-w4-result.md)及[独立核查§10](desktop-d2-w4-review.md#10-最终工程结论w4通过停在w4)已完成，独立全local470项／桌面146项及API复核通过，R01–R09关闭；[W5实现](desktop-d2-w5-result.md)与[W5独立核查§8](desktop-d2-w5-review.md#8-最终工程结论w5限定源码集成通过)已完成，三类候选采用及退出已用独立真实源码窗口复核；[W6实现](desktop-d2-w6-result.md)及[Codex独立核查§9](desktop-d2-w6-review.md#9-最终工程结论w6限定环境工程核查通过)已完成，独立477项local／168项桌面、前端及新完整包130项通过，54归档模块和真实入口同源，R01–R09关闭；后续指定Word及合成人工验收结果以本页上方2026-10-20收口记录为准；G17最新真实结果见上方2026-10-22记录，不宣布D2完整产品或发行完成。
- [D1本轮教师体验收口](desktop-d1-result.md#208-t6-b核对与本轮教师体验收口2026-10-17)与[独立复核](desktop-d1-review.md#209-t6-b复核与本轮人工验证收口2026-10-17)：原R1–R17工程通过、R18关闭、T6-A／T6-B／T7通过；配置v4、新旧表头和两份单日文件已核对。微软拼音按用户反馈正常，不再复验或穷举输入法。长园所2页、合并7页及起始页1／4／6、121导出相关／146桌面和c6dc1928…包证据保持，产品与发行未整体验收。
- [D1B第八轮复审§17](desktop-d1-review.md#17-d1b-第八轮修复复审与工程收口2026-10-17)：原R17关闭、17项全部关闭，**当轮当前Windows 11开发机工程复审通过**。133本地／108回归／146桌面、纯逻辑＋60组件及构建通过；独立真实窗口9/9，137文件包同源。后续人工体验与R18见结果§20–21／审阅§20，完整产品与发行未验。
- [D1A 独立审阅 §7](desktop-d1-review.md#7-版本统一与-d1a-放行2026-10-13)：R1–R6关闭及87／108项历史基线保留；3.12失败证据不再作唯一门槛，不重复派发已关闭问题。
- [Python 版本与运行时方案](desktop-d1-technical-review.md#8-d1-统一运行时准备方案2026-10-14)：3.14.7标准Windows x64的D1环境／锁已落实，26项业务依赖不变；当前包137文件，55个二进制／扩展条目与来源一致，旧缓存来源43个DLL未再收集，干净构建／发行再现性未验，不重开选型。
- [D1实施结果](desktop-d1-result.md)§19：第八轮R17设置保护及§19.12工程收口；§20保留人工体验、同库重启、微软拼音和实际导出样本的三项格式反馈。旧失败与未验范围保留。
- [D1 实施规格](../specs/desktop-manual-daily-plan.md)：D1A 数据／API 基线；§9–13 为已收敛的 D1B 产品、接口、工作项与新增验证门槛。
- [Codex D1 技术核查](desktop-d1-technical-review.md)：五项源码核查、SQLite 原语实验和后续边界。
- [D0 独立审阅](desktop-d0-review.md)：§7 为 2026-10-11 第三轮复审及真实 GUI 检查；工程复审通过，保留自检极端挂起限制、用户体验与环境未验边界。
- [D0 实施结果](desktop-d0-result.md)：OpenCode 原实施与后续修复共用报告，原通过记录须结合最新审阅读取。
- [D0 规格与后续顺序](../specs/desktop-foundation-plan.md)：本地窗口、SQLite 合成持久化、真实 Word 生成与原生保存、目录式测试包；之后才做本地手工日计划与 AI 闭环。
- [v2 待办与验证门槛](architecture-v2-readiness.md)：已确认决定、实施状态和后续参数。

用户已确认单教师档案、Windows 11 首发及无需旧业务数据导入。Vue／TypeScript、Python／FastAPI、SQLite、WebDAV 与数据库业务历史方向已确认；pywebview＋WebView2 优先验证，PyInstaller 为候选。第三轮 92 项测试通过，最新包仓外三进程、普通关闭／重启、原生保存／取消／占用重试和 Word 两页查看已验。当前 Windows 11 开发机 D0 工程验证可收口；干净机器、Win10、WPS、其他 DPI、用户本人体验仍未验，不宣布真实日计划或发行完成。

## v1 AI 1C：最新结果与未验项

- [C5 Windows 最新结果](ai-slice1c-fixture-c5-windows-result-2026-10-07.md)：2026-10-07 20:50，v2 主流程与真实提交飞行窗口已通过；个人 revision 4、based／latest contract 2、default／accepted revision 9、状态 current。
- [v2 实际发布记录](ai-slice1c-fixture-c5-v2-publication-2026-10-07.md)、[v1 准备阶段结果](ai-slice1c-fixture-windows-stage1-result-2026-10-07.md)：保留实际发布身份及原保存 HTTP 未捕获的证据边界。
- [剩余夹具规格](ai-slice1c-fixture-plan-2026-10-07.md)、[历史状态与剩余事项](ai-slice1c-fixture-windows-handoff-2026-10-07.md)：V1/U3、v3 与 C7 缺／错主密钥仍未验，不能宣布 AI 1A–1C 产品验收全通过。
- [真库复审](ai-slice1c-fixture-mysql-review-2026-10-07.md)：37 项含 14 项真实 MySQL 通过、零 skip；专用容器已停止并保留数据。[远程准备与实际恢复](ai-slice1c-fixture-remote-preparation-result-2026-10-07.md)记录独立资源及准备期 v1 基线，不代表发布 v2 后的最新状态。
- [原 Windows 验收报告](ai-slice1c-desktop-validation-2026-10-05.md)：保留方案 A 等产品决定与当时各项结果。

旧云端未结项不自动成为桌面方向的总阻塞，也不自动启动远程操作。新方向按复用范围确定应补验的场景；[v1 待办原文](architecture-v1-readiness.md)保留历史身份。

## v1 实现、验收与部署证据

| 事项 | 最终记录 | 配套规格／来源 |
| --- | --- | --- |
| I1 账号 | [MySQL 验证](i1-mysql-validation.md) | [账号规格](../specs/identity-registration-and-access.md) |
| I2 班级、学期、日历 | [实施与验证](i2-implementation-status.md) | [班级与日历规格](../specs/class-assignment-and-calendar.md) |
| I3 日计划 | 验证记录在规格中 | [日计划规格](../specs/manual-daily-plan-save.md) |
| I4 周计划与确认 | 验证记录在规格中 | [I4 规格](../specs/manual-weekly-plan-confirmation.md) |
| I5 已实现 Word 链路 | [正式收口](i5-final-closeout-2026-10-03.md) | [导出规格](../specs/word-export-implementation.md)、[原验收环境](../specs/i5-validation-environment.md) |
| AI 1A 数据、迁移与服务 | [阶段收口](ai-slice1a-closeout-review-2026-10-04.md) | [工程清单](ai-slice1a-implementation-checklist-2026-10-03.md) |
| AI 1B API 与权限 | [阶段收口](ai-slice1b-closeout-review-2026-10-04.md) | [API 规格](../specs/ai-settings-api-1b.md) |
| AI 1C 设置前端 | [实现阶段收口](ai-slice1c-closeout-review-2026-10-05.md) | [UI 规格](../specs/ai-settings-ui-1c.md)、上方 Windows 结果 |
| 1ABC 云端部署 | [部署结果](ai-slice1abc-deployment-result-2026-10-05.md) | [部署源 JSON](ai-slice1abc-deployment-source-2026-10-05.json)、[当时方案](ai-slice1abc-deployment-plan-2026-10-05.md) |
| 浏览器工具 | [代理修复](browser-proxy-repair-2026-10-05.md) | [浏览器与 Word 能力实证](browser-repair-and-i5-capabilities-2026-10-02.md) |

I5 的 D／F／G／H 报告覆盖不同案例、版本或证据窗口，由最终收口逐一引用；对应 JSON、下载文件、截图、完整性记录和历史部署源继续保留。完整 W6 非空材料仍未通过；本地版仍须实际导出并在 Windows Word／WPS 检查全页。

[AI 协同规格索引](../specs/ai-capabilities-implementation.md)保留 v1 的 P1–P4 决定与实施记录；AI Service 调用、持久任务、业务 AI 与材料仍未实现。进入新切片前按 ADR 0004 审查适用范围。材料参考见 [提取记录](i5-material-reference-extraction-2026-10-03.md)及配套 JSON。

## 提示词与报告维护

`docs/tasks/current.md` 是唯一当前执行提示词。任务结束或替换时，将独有决定、未验事项和实际结论归并到规格或结果／审阅记录，再更新当前提示词；不新增带日期或 `repair2/3` 的提示词副本，也不另建归档目录堆放副本。

2026-10-09 清理了 9 份已使用或被替代的 v1 提示词，相关引用改为规格与结果。Git 历史仍可查询；包含这些文件的历史提交为 `b3c5bbf`。多轮结果与复审含独有缺陷、失败和验证证据，继续保留，索引优先展示最终记录。独立资源身份、原始证据与产品决定不随提示词删除。
