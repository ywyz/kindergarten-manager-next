# 当前：桌面周计划＋明暗模式并行实施交接

更新：2026-11-01。**用户已明确 Q1–Q6 全部按推荐，产品规格定稿；用户新增黑暗模式切换并要求更新提示词、提交推送，为即将并行开工作准备；本轮只交文档并执行Git，尚未启动原生编码会话。** 后续按本入口正式执行时，依 G0→G4 开工；不重新问六项产品问题。当前 r03 测试由用户在另一台 Win11 开展，尚无回执，不预填通过。

## 唯一依据与当前范围

必须读 [AGENTS](../../AGENTS.md)、[已定稿产品规格](../specs/desktop-weekly-plan.md)、[工程设计](../specs/desktop-weekly-plan-engineering.md)、[明暗模式规格](../specs/desktop-appearance.md)及本文件相应角色。[阶段计划](../bootstrap/desktop-next-development-plan.md)记录交付顺序；旧 I4／I5 只按新规格的非冲突映射使用，不照搬账号／MySQL／全班投影。

首片是本人来源／手工编辑／保存／确认／历史查看与导出／Word／表头设置／完整备份配套。材料无候选仍空；三个周AI操作和四栏输入虽已确认，当前不提前注册任务或开放按钮。继续 Windows原生现有依赖和 `codex/desktop-v2-foundation`，业务源码基线2a469489；文档提交后的开工HEAD以实际Git记录为准，不自填提交SHA。已有规划／规格改动保留整合，不 reset／清理／覆盖。不与 WSL 共享环境，不安装新工具／Skill／MCP。

## 分支与并行安排

继续codex/desktop-v2-foundation；main为已合并基线，不为用户r03固定包测试切分支。建议后续受控并行G0/G1与用户测试，当前尚未启动。G2前由Codex结合目标启动、保存重开、备份恢复的实际反馈评估；Word逐页可并行。只有签名／系统策略受阻可继续源码工程；通用保存／恢复／关闭缺陷优先暂停相交文件并返修，不等所有人工样例完成才整理技术工作。

## 共同开工与交回合同

- 各原生会话先记录本轮起点／真实模型 metadata、Git HEAD、dirty路径和负责文件；实际源码／schema已变化先报 Codex，不能照旧指纹继续。不 fork 或另派子代理，不接管他方在途文件，不还原别人修改。
- 源码和UI文字保持UTF-8；工具对大段中文／长命令有编码或长度限制时拆成小patch并核字节，不交乱码占位。原始日志／metadata私下保留，只输出必要字段；达到会话回合限制保留实际退出，再按同一会话／固定模型续接，不把派发参数当真实模型证据。
- **G0 先只读接口核对**：A 给七表、唯一0007（含ui_theme/version）、外观API、DTO／来源／回执；B 给纯内容输入输出；C 给稳定identity／busy／Q3双分支及独立主题controller／CSS token；D 给固定确认 manifest／token／宿主方法。以工程设计为共同合同，交 Codex 核定矛盾后才实施。后续授权执行本入口时在此完成技术核对，无须用户再确认已决产品规则。
- G1 仅 A/B 数据与纯内容；C在G1独占主题模块及其色值文件，A统一外观API／0007和共享接线，D准备不冲突材料。A/B核心停写、Codex独立专项通过后才G2接周页面／导出；主题不提前依赖未冻结周API。共享模型和迁移始终A一人写，接口需变先暂停受影响方更新合同。
- 只用新的合成 data／credential／导出／备份根或明确授权副本；守卫在 app imports／Runtime 前安装，子进程同样受控。首失败和源身份保留，不读真实密钥、不自动重发未知任务，不删除未知文件。当前真实原件、旧库／凭据和已交付候选只保留，不用于试迁移。
- 各轮交真实命令／退出、改动与 source hash、首失败和复验、已验／未验，完成后自然停写交 Codex。Codex 独立读源／核关键反例和受影响回归，失败交原唯一责任方；不吞异常或为了通过改断言。
- 当前已知4551机不运行候选EXE／helper、不改名换目录绕过。工程源码验证不冒称冻结／目标运行。真实AI、WebDAV、签名、下载／安装／升级、公开发行、目标机远控不在本次设计或首片自动执行范围。新构建／Git按具体门禁安排，不能用旧 r03 结果代新包。

## 提示词 A：原 OpenCode，核心与共享整合

续 `ses_ead8af71dffeJphI1NOWg4jZgI`，build／`opencode-go/deepseek-v4.1-flash#max`。你不是唯一写入者；你的准确文件白名单为工程设计 §8 A 行，不改 B/C/D 文件。

G0 先核模型／0007／JSON／API与回执、B纯内容边界和D导出模型字段，交 Codex。核定后 G1 实施：真实SQLite约束和七表、班级两表头字段preview/apply、独立外观偏好（不增config_version）及appearance API、周来源与稳定实际周唯一、create/save/refresh/confirm／持久回执、备份源revision先验后隔离升级／全历史逻辑校验。新内容函数消费 B 交付，不再自行建一套结构。操作回放的是原结果，不能回放最新稿。

G1可等C主题模块停写后做自己的main／App／Settings／Workbench主题接线；周核心独立通过后再做App／leave／bridge／router／runtime的周功能整合；C给专属周页面，D给导出服务／host，不能代写其文件。稳定 editor identity 不含保存会变的草稿版本，切周 actionKey须含目标。Q3旧确认导出不保存 dirty 稿。注册周临时work的排除、退役和恢复失效，已有日／观察不受影响。

测试含并发唯一、复合FK、同键异载荷／冷重启回执、源新增／恢复／当前game缺失、合法旧历史与伪造源、0006升级／007备份与保护包再恢复、表头与原资料保持。新增测试优先独立文件，旧fixture改动仅你的白名单。每片停写等核查；未得到Codex精确源清单与新根前不打包；最终Git只按核定文件/blob/parent/tree普通提交推送，不add-all／amend／force或改main/tag/Release。

## 提示词 B：辅助 OpenCode，纯内容与反例

续 `ses_e72ecd5f9ffeYJaLRNypsdu5Pi`，build／`opencode-go/deepseek-v4.1-flash#max`。你不是唯一写入者；只写新 `backend/app/local/weekly_plan_content.py`、`backend/tests/local/test_weekly_plan_content.py`，不改旧 services同名文件或A模型／API。

G0 按工程§3和A受信快照定义固定 schema、正规化／hash／facts／完整刷新目标。核定后 G1 实施纯函数，不 import Session/models/runtime，不自己查DB／鉴权；手工ID由A注入。覆盖 Q1有效手填与明确空／null；真实同名不同来源及共用内容；材料null／非法ai拒绝；保留旧引用并明确missing；草稿与确认快照不变性及canonical顺序。反例要区分实际失败原因，不用相同坏路径掩盖另一个限额。交源hash／真实测试／首失败并停写；不碰共享fixture、前端、宿主、构建或Git。

## 提示词 C：Command Code，专属周页面

续 `8cf528de-8773-4a06-9cc5-31e96fab515f`，`deepseek/deepseek-v4.1-flash`／effort max。你不是唯一写入者；只写工程§8 C行的周新文件，以及明暗规格§4明确新增的theme模块／11个既有视图颜色样式白名单；App、main、leave、bridge、Settings、Workbench、shared types均由A接线。既有视图仅换语义色值，不改业务流程。

G0 先交 DTO消费、EditorBridge／稳定identity、busy和Q3两条状态链；G0核定主题DTO／CSS语义变量及样式责任后，G1可独立做theme.ts/theme.css/ThemeToggle和主题测试，按明暗规格处理快速切换／迟到响应／初始化及恢复重载；不依赖浏览器origin存跨重启偏好。A挂接API／共享入口，B/D不接主题。周核心G1通过后才G2实现列表／编辑／历史／导出UI。Q1单组最终格；Q2自动存草稿再离开，不自动确认；Q3当前链保存后如又输入／切周就停止，旧确认链完全不存不清dirty。确认目标必须完整显示来源日期／版本／目标指导而非只看名称。显示已存／已确认／缺项／源旧／进行中多个维度；无周AI空按钮。

主题另交亮／暗实际可读性、不同端口重启记忆、首次页到初始化、快速切换、维护／恢复及不改dirty/Word/照片的反例；交周页面的日常、IME settle、提交后又输入、切两不同周、旧响应、确认失败／unknown、dirty旧版导出与close／维护busy专项。需要A接线用明确接口清单交回，不越界改共享文件；不改生产模型、migration、host、模板或Git。

## 提示词 D：Command Code，周Word及受限交付

续 `16cf76b5-ea0b-47f5-bc94-26147c9d3689`，`deepseek/deepseek-v4.1-flash`／effort max。你不是唯一写入者；只写工程§8 D行的新周export服务／API、d1_host_api.py和独立专项测试。七表／迁移／router挂载／shared TS由A写。

G0给固定manifest／token／attempt字段、API和两个原生方法与A/C对齐；G1前不接未冻结模型。G2按工程§6实现确认快照导出，预览不自动保存稿；明确旧确认不受当前草稿／新确认指针变化拒绝。只用确认钉住日历／表头／列，旧mapper不得实时重算日期。既有30MiB save_docx和观察协议不变，新weekly128MiB通道固定地址，token10分钟、同名幂等／异名拒绝；create/retry带request_id、持久回执，同launch可取回同一token，跨launch仅失效元数据；retry须旧failed/cancelled attempt且唯一后继，query不新发保存。共享_save_mutex／_save_inflight，原生返回后再校验retire／维护，回执丢失不重写。

先自动验证token用途／scope／跨profile／过期／并发、完整Word／版本／日历，真原生取消／成功／占用与明确重试及Word全页按Codex安排一次一个执行者；不运行受阻EXE。所有Word须由本轮源码真实UI导出，不能拿静态夹具或旧文件冒充。需要models字段或work清理先交A，不自己改归属文件。交真实证据和未验、停写，不构建／Git。

## 本次文档Git与后续开工

用户已授权本次汇总文档提交推送；Codex核定准确文件/blob/parent/tree后，原OpenCode只做普通Git，当前不得顺带启动G0/G1源码实施。提交内容包括此前产品／工程／文档审计积累及新增主题规格；先独立核查，再交下一轮按本入口启动。文档内不回填自己的提交SHA形成循环。

## 目标测试与缺陷插队

下方保留用户目标测试的完整身份和步骤。若收到保存／恢复／导出缺陷，Codex先登记真实触发及最小影响，暂停相交的周片文件写入并固定当前源身份，再给唯一责任会话；不得同时向同一原生会话派两个在途任务，或让缺陷修复和周片并行写同文件。修复后的新包不能改写用户正在测试的旧ZIP通过状态。

## 既有 r03 交付身份（用户目标测试）

先读 [AGENTS](../../AGENTS.md)、[最终独立核查](../bootstrap/desktop-windows11-portable-review.md)、[实际构建结果](../bootstrap/desktop-windows11-portable-result.md)及[中文操作手册](../bootstrap/desktop-windows11-portable-manual.md)。业务依据保持[备份 P01–P06](../specs/desktop-backup-restore.md#1-产品决定与集中确认)、[日计划](../specs/desktop-manual-daily-plan.md)及[观察 A01–A22](../specs/desktop-game-observation.md#7-验收条件与证据矩阵)，不重问既有产品决定。

| 项目 | 唯一使用身份 |
| --- | --- |
| 分支／构建基线 | 继续 `codex/desktop-v2-foundation`；候选在带本轮变更的 `91e6a553db6d25a1603849f139f22e9d9097537b` 上构建，不能写成纯基线构建；本轮源码提交以实际分支历史为准 |
| 物理根 | `build/desktop-e14-win11-r03`；首失败 `desktop-e14-win11-r01`、已过静态的 `desktop-e14-win11-r02` 与旧 `desktop-e14-r03` 均只读保留 |
| 完整 ZIP | `build/desktop-e14-win11-r03/dist/KGNext-E14-win11-r01.zip`，43,963,980 bytes；逻辑 basename 保留 r01 |
| ZIP SHA-256 | `0a1b9c0b55612de889e621f70ed1374d8e792d3755d9fce1eadf17b7b6532470` |
| build_id | `5babc817-5b2a-466b-b382-36cffa02cace` |
| source freeze | 248 files，`e1bbc5b01a1b55efece4a45089dc22f9e34fc872908bbb9c261aea85d0c03208` |
| 版本／schema | `0.1.0`／`20261025_0006_local_game_observations`，Windows x64 |
| 另带预检脚本 | [desktop/check_windows11_target.ps1](../../desktop/check_windows11_target.ps1)，SHA `d7cdb39576a83ad76c71490b7416fa47e41f312acd8b7f1d8ca67bbc5ed1caaf` |
| 合成种子 | `build/desktop-e14-win11-r03/handoff-synthetic/` 完整四文件，明文／加密身份见结果 §9.2；合成密码 `KGM-W11-Synthetic-Only` |

已证范围：493 desktop 单轮通过；实际目录 54 项／ZIP 59 项静态通过，导入前外层启动守卫事件 0；本机 PS7 对新解压副本只读预检 49 项通过；107 PE 中 76 Valid、31 NotSigned，主 EXE 未签名。原后端 848／前端只按生产源码未变引用，未冒称本轮重跑。PS5.1 parser 0 errors，但本机文件执行受 Restricted 阻止，PS5.1 实际运行未验。合成种子经源码服务生成及独立校验，不是冻结程序 UI 备份证明。

## 顺序与退出条件

1. 目标机上的用户／有访问授权的测试者按手册 §2 校验 ZIP 和脚本 SHA，使用普通权限、新的自有测试根进行只读预检。记录 Windows 版本、原生架构、WebView2 Runtime、可读策略、全部 PE 签名与文件身份；脚本报告注明“目标1”，不把开发机报告换标签复用。
2. 首先处理预检失败／未知。ARM64、缺组件、策略或权限未知均按实际记录，不自动安装、改栈或管理员重试。脚本受策略阻止时保留错误，按手册查看设置，不能 Bypass、粘贴整段重跑、去来源标记、改注册表／信任或关闭 SAC／WDAC。当前已知 4551 开发机不执行候选；目标首次拦截也停止，不改名／换目录／hash 反复试。
3. 在目标适用、预检可核对且没有相关阻塞时，按手册 §3–§5 用普通入口与显式新 data／credential 根验证：首次建档／首次页直接恢复、日计划、三类观察、选图排序说明、历史、保存、关闭与新进程接续。不要先创建凭据目录，不用 selftest、桥接替身或直接改库代替普通使用。
4. 实际原生文件取消／成功、自己文件被 Word 占用时的失败及明确重试分别留证；未触发占用失败就记未覆盖。日计划导出遵守已保存快照；观察须先成功保存本次编辑再固定版本，不能交付旧稿冒充当前编辑。
5. 从本轮冻结程序 UI 实际创建明文／加密备份，校验、预览取消、确认替换，保留恢复前完整保护包。新窗口继续编辑保存、全新进程重开，再从 UI 恢复保护包找回替换前工作；首次页空保护、错口令／取消／合成坏包单列。只迁移合成 `.kgmbackup`，不搬 DPAPI；目标无原解密材料时重填合成无效密钥，不发供应商请求。
6. 按手册 §6 从实际新包导出 W1–W8 八份 Word，覆盖单／多日日计划、三类观察、混合选择、0／1／2／3／5 图、横竖、长文／长园所及保存顺序。记录 Word 版本、字体、每份页数和问题页；结构检查、实际 Word 逐页与教师确认分栏。没有 Word 就留未验，不使用旧文件或 XML 代验。
7. 收到真实回执后由 Codex 形成 `docs/bootstrap/desktop-windows11-target-review.md`，归并手册 §7 的最小记录与实际证据别名；尚无真实回执时不创建虚假通过记录。源码、静态、目标预检、普通运行、Word、教师体验、签名／发行逐项结论，首失败与后续复验分开。

## 会话责任：按真实证据派发

**Codex 主会话**：核对交付身份、只读预检与人工回执；掌管目标核查记录、必要手册修正及唯一入口。不在没有目标访问时反复跑本机静态或等待签名充当进展。先收最小真实失败／未验，定位是否属于应用缺陷；AI 失败可恢复不免除应用缺陷。证据不足就列明确缺项，不猜原因。

**Command Go 续原生会话**：固定 `deepseek/deepseek-v4.1-flash`／effort max，不 fork／另派子代理。收到本轮目标预检回执后，独立核对脚本版本、退出码、必需失败／未知、原生架构／Runtime／策略／签名和路径隔离；只读分析，私有原始报告不提交。不重复执行受阻脚本或 EXE，不冒认自己操作目标机。只有 Codex 按具体缺陷分配互斥文件后，才实施对应测试／PS1 修复。

**原 OpenCode**：续 `ses_ead8af71dffeJphI1NOWg4jZgI`，固定 build／`opencode-go/deepseek-v4.1-flash#max`，不 fork／另派子代理。收到具体普通使用／Word 失败时先只读追踪当前源码合同和本轮产物身份，交最小复现与修复范围。只在 Codex 明确唯一文件责任后实现，不抢他方文件、不还原别人改动；没有新缺陷不重建。构建输入一旦改变，需新的停写、回归、freeze、全新物理根及实际静态验证，旧 ZIP／目标／Word 结果不迁移。最终 Git 仍待 Codex 精确文件／blob／parent／tree 门禁。

辅助 OpenCode 仅在有独立具体核验需求且被分配互斥责任时启用；本轮已完成的 builder／verifier／测试不用四会话重复开工。所有原生会话记录实际模型元数据，不能用命令参数代证。

## 持续边界与后续收口

原真实档案／凭据／旧包／首失败现场只复核指纹；数据、照片、备份、导出、故障现场及报告只使用新自有根。公开记录只含设备角色和证据别名，不放用户名、机器名、SID、完整私有路径、真实正文／照片／密钥；不删未知资料、不全局 kill、不把程序包／原始日志入 Git。

本提示词不自动授权目标机远控、真实个人档案替换、应用真实 AI、WebDAV、下载／安装／升级、签名、冻结更新替换、改系统保护或公开发行。不因证书申请中重开无关开发；若目标被策略阻止，先保留阻塞和可完成的手动资料，再待签名／环境条件明确后单独安排。

有修复则由原责任会话完成、Codex 独立复验，再按具体清单普通提交推送当前桌面分支；不改 main／默认分支／可见性、历史、tag 或 Release。完成或替代本提示词前，独有决定和未验项先归规格／结果，再更新本文件，不新增 prompt-final-v2/v3 副本。
