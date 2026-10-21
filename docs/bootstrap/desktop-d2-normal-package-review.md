# 普通运行验证包整合：Codex独立核查

更新：2026-10-20。用户授权把已验修复整合进普通运行验证包，直接调用OpenCode，仍用Go套餐DeepSeek V4.1 Flash，交Codex独立核查并交回问题；禁止应用真实AI与发布。最终结论：本轮普通包整合的当前Windows 11合成环境工程核查通过，N01／N02已关闭，详见§6；不代表真实AI、教师整体验收或发行通过。

## 1. 范围与基线

- 当前分支codex/desktop-v2-foundation，开工HEAD d24a1b7；开工工作区干净。当前任务见[执行入口](../tasks/current.md)，原下一步建议及三项后续事件保留在[W6收口](desktop-d2-w6-closeout.md)，不重启G13／R02／R03排查。
- 证据根为%TEMP%/kgm-d2-normal-codex-20261020-213115/：457个已跟踪文件开工hash、683个旧前端／普通包／人工包／保护human根文件hash、Git状态及脱敏OpenCode会话基线已保存。前置export实际exit0。原体验／人工数据不作为自动测试库。
- 原普通包EXE56346c0a…仍为旧前端，R01完整人工包EXE209dedcd…与其前端保持；新普通包必须独立目录，普通入口仍为d1_main，不混入人工壳或合成配置，不把目录式验证包称为安装发行。
- OpenCode唯一写实现／测试／构建脚本；Codex只写任务／核查文档及执行验证。本次不自动commit/push或发布。

## 2. 实施调用与结构核查

21:31使用本机已安装OpenCode CLI v2.0.32直接run --standalone --session ses_ead8af71dffeJphI1NOWg4jZgI --model opencode-go/deepseek-v4.1-flash --agent build --format json --auto --file docs/tasks/current.md。CLI日志opencode-run1.jsonl／stderr及实际exit将分开保存，最终须核对新增assistant实际模型元数据，不能只据参数推定。

按codebase-memory技能做Verify范围查询：项目C-Users-yw980-code-kindergarten-manager-next，图谱generation 2026-10-20T13:18:34Z；构建／归档同源相关45结果两页已读取。对build_d2.py、verify_d2_w6_package.py、verify_d2_manual_ai.py、d1_main.py、CandidatePreview.vue的coverage均提示metadata_changed，已限定直接补读相关源码，不声明图谱完整或新鲜。确认旧构建脚本frontend/work/spec固定旧根，需要由OpenCode最小参数化或复用既有能力到独立新根；普通入口的受控注入仍限专用selftest，R01按钮逻辑与dirty离开保护保持。

## 3. 独立核查范围（开工计划，实际结果见下文）

核查最小改动范围、参数路径／旧目录保护、真实归档入口与完整模块集合、前端及迁移／模板资源；独立重跑前端与相关脚本／宿主回归、新包仓外真实窗口／保存重启／候选／Word／无AI降级闭环，并核对旧包及原数据hash、实际退出与模型。所有自动运行只用新合成根，明确dotenv禁用和凭据目录隔离，不调用真实供应商。R01按钮层组件及已验前端相同性与普通包窗口证据分别记载，不混同教师确认。

## 4. 首轮独立结果与脚本收口项

Codex实际执行的typecheck、D1纯逻辑、60项D1组件、81项D2组件及196项桌面回归均exit0。独立archive检查12项true：真正d1_main入口、54个生产模块完整集合与当前源码一致，无人工入口；前端与已验R01资源逐字节一致且不同于旧普通包，模板／迁移／Alembic同源，没有数据库、dotenv或fixture材料。

新包EXE e843d11b38ff87fc4876313aad8a20cb60912ff73c61b1f35d908dae81a6ba5c，15,048,169字节；182文件，Windows相对路径清单hash99ae429a998fdae01a187bf9c62a8ebedf718525b3c4b1ce3c612f72f0fdfbd2。independent-archive.json另用POSIX分隔符保存清单，hash053d7822…，两者是序列化路径不同，不是包内容变化。

Codex独立仓外冻结窗口根%TEMP%/opencode/kgm-d2-w6-pkg-4712cc9e/，independent-package-report.json固定130项严格true，missing/failed/extra为空，主进程及两次资源／G14／重启／G15各分支／W5全部实际exit0。包内前端、系统PATH、无源码frontend覆盖，dotenv关闭与独立凭据／合成库。683个受保护旧文件hash零变化。该结果是合成工程验证，不替代教师确认或真实供应商。

N01（首轮发现，现已关闭，见§6）：build_d2.py新增的保护只检查dist_root及旧普通build_root的相等情况，未覆盖frontend/work/spec的实际写入路径；例如--build-root build/desktop-d2-manual-ai-h06-r01同时--dist-root另一个新目录会通过检查，随后重建已验R01前端及旧work/spec。新增--allow-legacy-root也不是本次授权需要。要求删除旧根写入逃生参数，并在任何build前对实际会写入的frontend/work/spec/package（含hash输出）与已知受保护旧前端／包／人工根做路径解析和相交保护；复用只读显式frontend可保留。用只涉及临时合成目录／mock subprocess的针对性验证证明拒绝发生在写入前，不能真对旧产物运行反例。此修复仅构建脚本／必要测试，不触碰已通过的新包或业务源码，若包字节和运行代码未变不重建／重跑整包。

N02（首轮运行说明问题，现已关闭，见§6）：RUN.md曾称普通入口“不接受…合成数据参数”，但普通d1_main明确支持--data用于选择数据根；受控CA单独参数也不是全部被语法拒绝，实际限制是专用selftest才允许受控传输／私网解析及执行器故障注入。说明须按真实行为写清：普通可指定--data／环境数据路径；首次无档案才填写；不自动配置／调用供应商；不要将人工合成根当普通教师根。不得为匹配文字反改已验业务行为。

## 5. 首轮交付与回修调度

首轮OpenCode CLI实际exit0，脱敏export实际exit0，交付实现结果并声明停止写入；Codex未把实现者自测替代独立结果。N01／N02已按用户原授权交回同一会话Go Flash，第二轮日志opencode-run2.jsonl／stderr／exit单独保存。此次仅构建脚本、单一针对性测试、RUN与实现结果可变；新包全部182文件及业务源码保持冻结，既有独立通过证据在最终字节稳定性核对后继续有效，不无故重建／重跑全套。

R01取消／dirty退出路径本次未在普通包重新驱动：使用与已验R01逐字节相同的前端、81项组件回归及原R01冻结包DOM证据组合支持；当前普通包真实窗口直接覆盖编辑／比较／采用及离开／关闭保护。本次没有新的教师确认、Word逐页或真实供应商结果，不扩大已有结论。

## 6. 最终独立核查与交付结论

本轮普通运行验证包整合的当前Windows 11合成环境工程核查通过，无剩余本轮修复项。N01构建写入路径保护、N02运行说明均已由原OpenCode同一Go Flash回修并关闭；Codex实际核对后才作此结论。

| 独立核查 | 实际结果 |
| --- | --- |
| 前端 | typecheck、D1纯逻辑、60项D1组件、81项D2组件均exit0，含R01按钮回归；与已验R01前端逐文件一致 |
| 桌面 | 196 passed／8.22秒／exit0；2条既有第三方弃用警告，未改变依赖 |
| 新构建路径保护 | independent-path-tests.*：8 passed／0.14秒／exit0；独立help exit0且无旧根开关；源码确认所有resolve／相交检查在构建和hash写入前，只读显式前端仍可用；全部测试只用临时合成布局与mock构建 |
| 新包真实冻结窗口 | independent-package-report.json：固定130项严格true，failed/missing/extra空；资源两次、G14与重启、G15各分支、W5全部实际exit0。G14请求split=1/adapt=1/other=0，重启无新请求；W5三类各1、在途适龄最终outcome_unknown且无开放attempt、worker／服务退出确认 |
| 同源与纯净性 | independent-archive.json：真正d1_main入口及归档54模块完整集合与当前源码一致，无不可用／不匹配、无人工入口；前端／Word模板／迁移／Alembic资源匹配，无数据库／dotenv／fixture材料 |
| 最终稳定性 | independent-final-stability.json：新包仍182文件、与独立验证时逐文件零差异；旧683文件数量／集合／hash全保持；业务、schema／迁移、前端、依赖、宿主源码零变化，已跟踪代码仅build_d2.py与verify_d2_w6_package.py改变，另新增单一构建路径测试；8项独立测试的两份源快照保持 |
| 实施模型与退出 | 两轮CLI实际exit0，最终脱敏export exit0；model-audit-final.json核对本轮新增42条assistant全部且仅opencode-go/deepseek-v4.1-flash#default，最终finish=stop、outcome=succeeded；无换模型或另起实现者 |

实际交付为build/desktop-d2-normal-r01/package/KGNext-D2Verify/完整182文件目录。EXE SHA-256 **e843d11b38ff87fc4876313aad8a20cb60912ff73c61b1f35d908dae81a6ba5c**，15,048,169字节；Windows相对路径清单SHA-256 **99ae429a998fdae01a187bf9c62a8ebedf718525b3c4b1ce3c612f72f0fdfbd2**。运行说明与清单位于同一构建根RUN.md／package_hashes.json；完整目录不可拆成单EXE。原56346c0a…普通包、18915b7b…／209dedcd…人工包与原human／诊断资料保留。

最终回修仅构建工具／测试及说明，不进入冻结运行模块，包字节与前端完全不变，因此不重新构建或重复整包／全local回归。Codex未启动普通交互窗口、未修改默认教师库、未触发原人工根的新任务或采用。未调用应用真实AI、WebDAV、旧远程修改、安装升级或发布，本轮未自动commit/push。

结论只覆盖本次整合与既有自动证据。普通包新Word样本未逐页人工确认；R01取消／dirty退出的证据组合边界见§5；G17真实供应商、质量与用量、G18完整教师确认、干净机器、Win10、WPS、其他DPI／多显示器及安装发行仍未验。G13／R02／R03按W6收口的用户决定保留，不复开追查，不记为已验证／已修复。真实AI须另获调用及用量边界授权，当前不启动后续功能。
