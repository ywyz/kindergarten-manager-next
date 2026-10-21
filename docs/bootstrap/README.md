# 文档与报告索引

更新：2026-10-21。当前工作按 [AGENTS.md](../../AGENTS.md)、[Architecture v2 实施入口](architecture-v2-readiness.md) 和 [ADR 0004](../adr/0004-local-desktop-architecture-proposal.md) 执行。系统级事实见 [ARCHITECTURE.md](../../ARCHITECTURE.md)，规格与历史报告不等于当前任务授权。

## 当前阶段：D2 W6限定工程通过，指定人工验收收口，真实AI待授权

最新状态与处理决定见[W6收口及三项后续事件](desktop-d2-w6-closeout.md)和[逐项人工记录](desktop-d2-w6-manual-acceptance.md)：已验Word／候选／保存／重启／在途子项保持；跨120秒睡眠不再验证，白屏等复发，额外任务用户倾向误点、保留观察。三项留作同类再现处理，不主动追测，不改记为技术通过／已修复。用户已授权相关Git提交／推送，未授权应用真实AI或发布。

2026-10-20后续授权的[普通运行验证包整合](desktop-d2-normal-package-result.md)已由OpenCode使用同一Go套餐DeepSeek V4.1 Flash完成，并经[Codex独立核查§6](desktop-d2-normal-package-review.md#6-最终独立核查与交付结论)通过：新包位于build/desktop-d2-normal-r01/，普通入口与54模块同源、前端与已验R01一致；独立前端、196桌面、8项构建路径保护及仓外冻结130项通过，旧包及保护数据未变。N01／N02回修关闭；相关修改已按2026-10-21用户授权提交并推送（2cafa49），未上传包、数据库或凭据。

2026-10-21 [G17真实AI验收方案](desktop-d2-g17-acceptance-plan.md)不设计预算限额；用户指定DeepSeek、MiMo及OpenCode Go的[官方文档兼容性核对](desktop-d2-g17-provider-compatibility-review.md)已完成。DeepSeek官方API与MiMo标准API可准备后续验收，MiMo Token Plan不适用本后端，Go用途／客户端要求尚未满足；具体型号／账户类型／顺序待定。当前真实调用0次、尚未授权，不把文档符合或配置ready当作G17通过。

已进入 `codex/desktop-v2-foundation`，采用 Windows 11 原生开发。OpenCode 写实现、测试、迁移及构建脚本；Codex 负责技术核查、规划设计、审阅、相关验证与 Git／发布管理，均按当前授权执行。

- [唯一当前任务](../tasks/current.md)：D2 W1数据迁移／凭据保存已由OpenCode实施并经Codex核查关闭。[W1实现结果](desktop-d2-w1-result.md)。[产品规格](../specs/desktop-ai-daily-plan.md)、[工程规格及清单](../specs/desktop-ai-engineering.md)、[W1独立核查](desktop-d2-w1-review.md)。W1独立全local286项、迁移18项及冻结重启探针通过，R01–R09已关闭（核查§12）；[W2](desktop-d2-w2-review.md)已由OpenCode使用Go套餐DeepSeek V4.1 Flash交付并经Codex核查通过；[实现结果](desktop-d2-w2-result.md)含后续接口交接；[W3实现](desktop-d2-w3-result.md)及[独立核查](desktop-d2-w3-review.md)已完成，当前Windows 11合成环境工程通过；[W4实现](desktop-d2-w4-result.md)及[独立核查§10](desktop-d2-w4-review.md#10-最终工程结论w4通过停在w4)已完成，独立全local470项／桌面146项及API复核通过，R01–R09关闭；[W5实现](desktop-d2-w5-result.md)与[W5独立核查§8](desktop-d2-w5-review.md#8-最终工程结论w5限定源码集成通过)已完成，三类候选采用及退出已用独立真实源码窗口复核；[W6实现](desktop-d2-w6-result.md)及[Codex独立核查§9](desktop-d2-w6-review.md#9-最终工程结论w6限定环境工程核查通过)已完成，独立477项local／168项桌面、前端及新完整包130项通过，54归档模块和真实入口同源，R01–R09关闭；后续指定Word及合成人工验收结果以本页上方2026-10-20收口记录为准；G17真实AI未授权，不宣布D2完整产品或发行完成。
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
