# D4 E14：整包及集成独立核查

2026-10-30后续产品决定：用户接受AI生成可能不稳定，要求失败／结果不明时提供主动重试；此类可恢复结果不单独作为产品不通过理由。后续验收检查提示、内容保护、费用确认与手动重试，不抹去本文件原请求事实或尚未通过的冻结包／教师体验；实施与独立验证见[AI重试与GitHub更新核查](desktop-retry-github-review.md)。

> 公开版隐私处理（2026-10-30）：本机用户路径、私有部署地址或联系标识已替换为占位符；原始记录由维护者私下保留，历史日期、结论和产物哈希不因此改变。

更新：2026-10-30。状态：**E14-R01–R06源码／构建／静态分发可修项独立核查通过；冻结运行受Smart App Control阻止，E14整体及教师体验未通过，未发行。** 工程结论见§6，用户10月30日决定暂按源码验证及Certum申请准备见§8；实现者停写自测另见[结果](desktop-game-observation-e14-result.md)，不相互冒充。Git按§7由原OpenCode正常提交推送已核查源码／文档，不能把Git收口写成冻结包运行通过。

## 1. 授权、基线与保护

用户本轮要求接续E14整包和集成验证，准备教师体验新包；原OpenCode使用Go套餐DeepSeek V4.1 Flash max实施，Codex独立审核，失败交回修复直至通过，最后OpenCode提交推送；允许真实AI，全部功能完成以后可发行进行测试。旧导出片停点由本次授权替代。完整需求见[产品A01–A22](../specs/desktop-game-observation.md#7-验收条件与证据矩阵)，执行见[唯一入口](../tasks/current.md)。教师体验、工程测试和发行结果分别记录。

开工工作区干净，分支`codex/desktop-v2-foundation`，基线`5808078`，无新分支。原会话`ses_ead8af71dffeJphI1NOWg4jZgI`经CLI 2.1.4 `api --standalone GET /api/session/{id}`核对为idle／succeeded、build、`opencode-go/deepseek-v4.1-flash#max`；同一会话以显式相同模型及代理派发。未另起／fork会话、实现者或子代理。

证据根`<LOCAL_USERPROFILE>/AppData/Local/Temp/kgm-observation-e14-20261028-2f5a8ac1/`。开工Git、会话及280个已跟踪产品／桌面路径hash保存在根目录；实现者仅写`opencode-evidence/`，Codex独立结果写`codex-evidence/`。CLI每轮JSONL、stderr和实际exit分开保留，最终核对新增assistant实际模型及代理元数据。开工脱敏会话导出为`session-opening-sanitized.json`，包含6452消息，略晚于派发；最终模型审计按开工会话时间／消息ID划定，不将该计数直接当派发前边界。

原体验库／配置／凭据、OneDrive原件、旧包及远程资源保留。自动验证只用独立合成库／图片或已授权只读副本；真实AI只传独立合成资料。凭据只经既有服务在内存中只读使用，不进入日志、代码或分发包。不安装／升级依赖、Skill或MCP，不改ARCHITECTURE.md，不启动WebDAV／跨设备或无关功能。Windows系统保护不更改，遇实际阻止保留证据，不重建试错绕过。

## 2. 核查方法及证据边界

已按仓库要求读取codebase-memory技能。项目`C-Users-yw980-code-kindergarten-manager-next`索引ready，代次`2026-10-28T01:31:52Z`；构建文件19个符号及build_package一跳双向关系全部取回。5个相关路径覆盖检查为`no_recorded_issue`，但freshness为`metadata_changed`，故构建、资源解析、普通入口及验证器回读实际源码，不据图谱断言穷尽。图谱将subprocess.run解析成update_helper.run的关系不能作为调用事实；以实际源码为准。

独立检查分层：源码及故障／回归、冻结包资源与同源、普通入口及真实WebView2／原生IO、实际产品Word逐页、真实供应商闭环、交付归档与Git。前片证据仅在代码／资源hash不变且适用范围一致时复用，并明确标注旧轮身份；不能用selftest替代普通入口，不能用假供应商替代真实调用，也不能用XML替代Word排版。

## 3. 首轮交接与外部阻塞

- 原OpenCode r01自然exit 0，已停写交接；新增build_e14.py／verify_e14_package.py，调整verify_observation_multi.py及结果文档。初始包199文件，EXE SHA256 `64ef4ad3433eaa40fc9b48b83f97598662d12e7cb10f48bea600f8c04352354c`。原轮产物及失败保留。
- 实现者13项静态检查通过，冻结首次运行失败；Codex尚未批准本轮，不Git／发行。独立全local已启动，待实际退出及源hash复核后填写结果。
- Codex只读取得本次CodeIntegrity 3033／3077，Policy GUID与2026-10-23已核定的Smart App Control `VerifiedAndReputableDesktop`相同；新EXE和旧r03均NotSigned，CI注册表VerifiedAndReputablePolicyState=1。`code-integrity-events.json`与`package-signature.json`留证，不再次启动同一受阻包。用户答复当前无证书／其他测试电脑，准备申请证书；继续可独立推进的回修、源码及真实AI验证，冻结运行仍保留阻塞。没有由此取得购买、证件提交、签名私钥或改变系统防护的授权。
- 既有发行规格尚未选定真实发行URL／正式公钥；E14先交付可独立使用的完整本地测试包和校验归档。在线更新发行需要具体既有资源及产物对应证据，不把合成签名源当实际发行渠道。用户本次发行授权有效，不重复询问权限；若缺目标或身份，仅列实际缺项。

## 4. 首轮审核：未通过，交回同一会话修复

| 编号 | 独立复现及要求 | 状态 |
| --- | --- | --- |
| E14-R01 | 新`build_e14.py`只拒绝候选位于两个旧根内部，遗漏祖先重叠及旧manual-ai根，且未对frontend/hash/source-freeze等写入目标逐一校验。对仓库根和旧manual-ai根的两次无写入探针均到达构建函数；若真传仓库根，Vite的`--emptyOutDir`会以源码`frontend/`为输出。须在任何写入前解析检查全部写入路径与源码／旧包／独立输出根，补有区分力的拒绝回归，不实际尝试擦除目录。`early-builder-guard.json`记录builder hash `eb5f7113…`和两条`build_reached=true`；探针只拦截构建调用，未写产品文件。 | 开放 |
| E14-R02 | `source_freeze`在构建后采集且递归包含pycache，遗漏新builder和多份实际宿主／更新模块；13项静态检查只比较资源，不能支持“前后端／应用代码同源”。补构建前后稳定的产品／构建来源清单（排除缓存），直接读取CArchive／PYZ对真实入口及打包生产模块比较结构摘要，资源及观察／更新／AI关键模块明确列清。受4551阻止时不运行EXE，归档核对仍可完成；结果区分静态同源与运行证据。 | 开放 |
| E14-R03 | 新包没有`build_identity.json`，现有冻结入口会将其识别为`UPDATE_IDENTITY_UNAVAILABLE`。按既有AppIdentity契约给本次候选生成真实UUID构建身份、当前已确认版本与0006 revision，核对包内身份和产物清单；不虚构正式发行源／签名信任或安装通过。Pillow许可证缺失不能只写false仍打出“完整”分发包，须明确失败。 | 开放 |
| E14-R04 | “未找到真实AI配置”与既有G17配置证据冲突。可只读复用的DeepSeek源为`%LOCALAPPDATA%/KGNext-G17-20261022/deepseek/data/kindergarten.db`及其独立`LocalAppData/KindergartenManager/credentials`；前片稳定入口在e0607证据根`opencode-evidence/verify_observation_ai_real.py`。复用既有服务在内存解密并注册全新合成根，执行必要生成／审阅／采用／单栏重写／重开，实际请求与unknown分列；原源文件前后hash保持。不遍历用户目录找秘密，不回显或复制明文，不自动重试。冻结受阻时只能声称源码真实闭环，MiMo无凭据仍列未验。 | 开放 |
| E14-R05 | 旧0005升级仅以日计划／内容／任务数量断言“保持”，不能辨别内容、历史、来源、回执或密文被改；用旧行主键及值摘要逐项比较，明确允许的source列回填，校验完整性／FK／备份／无重放。verify_observation_multi对空园所回退到其他记录／OBS园所也不是产品预期，必须按每份已保存字段独立核对、空园所保留空白，并补不同园所／空园所的有效验证。 | 开放 |
| E14-R06 | 报告／README必须把前片复制样本和容量证据标为复用，不冒称本轮重跑或冻结输出。A21“诊断未含姓名／路径／正文／凭据”缺少明确扫描范围；收窄至实际检查。初轮曾调用PowerShell Bypass的事实应如实留存，不同时宣称本轮从未使用；后续只走已有Python.NET入口，不调用Bypass／改策略。完成代码修复后归并本次授权及实际状态，冻结阻塞不得写成通过；独立通过及Git白名单前继续不提交。 | 开放 |

R01–R06为代码／证据可修复项；4551、正式发行URL／信任身份与缺少MiMo凭据单列外部未验，不靠重建／改名／换目录反复尝试绕过，不以源码验证代签冻结包。

r02中途独立无写入探针`r02-plan-probes.json`（builder hash `3584bd46…`）确认仍有两个剩余点：R01的`frontend_is_input=True`接受位于本次`dist-root/KGNext-E14/_internal/frontend`的路径，后续PyInstaller的清理会改变该“只读”输入，须拒绝其与实际写入目录相交；R02实际调用顺序为`frontend_build → source_freeze → package_build`，须改为覆盖Vite开始之前的冻结，才能证明完整构建来源稳定。两次探针均拦截构建函数，没有写产品文件。

R06另有证据保留偏差：原OpenCode r02曾在修正独立旧库探针的`DatabaseInspection.head_revision`属性错误后，以`rm -rf`清理并重用`opencode-evidence/r02/old-upgrade-probe`。CLI JSONL中的原失败及命令保留，但不能声称该目录的首次现场完整保留。后续必须用新命名根，不删除、覆盖或重新灌入旧失败根；原丢失目录不可由后续成功倒推恢复。本偏差不涉及原体验库或配置，仍须如实记入结果。

R06的r02交接还需校正：实际ZIP的`KGNext-E14/EVIDENCE/real-ai-source-hash-comparison.json`包含原G17受保护文件的绝对路径（`r02-dist-scope.json`留证）；尚未上传，但这类私有审计材料不应进入后续分发归档。将完整日志／原路径hash清单留本机，分发只带完整产品目录、便携README和相对路径校验清单；`package-info.json`亦不需携带构建机绝对路径。结果A07只能写process单栏重写，不能写“四栏输出已验”；容量复用须区分16张noise产物大于30MiB与33张noise超64MiB拒绝，不能合并为33张成功。

## 5. 独立执行记录

| 验证 | 实际结果与限制 |
| --- | --- |
| 全部backend local | `backend-local.log`：**759 passed，771.77秒，exit 0**。验证前后171个后台产品／迁移／local测试文件hash零变化，当前源码仍与该窗口一致时可复用；不用前片758冒充本轮。 |
| r01直接归档核对 | `r01-archive.json`：读取CArchive／PYZ，真实入口结构与源码相同，78个仓内归档模块比较中1项`verify_observation_multi`不符（打包后调整的验证模块），其余77匹配；build_identity缺失。未执行EXE。该结果补强R02／R03，不等于冻结运行通过。 |
| 前端 | typecheck与完整test:d1均exit 0；核心逻辑、D1组件60、W5组件94、历史22、更新13、观察54均实际通过。73个前端源／配置路径hash前后零变化。 |
| r02全desktop首次 | `desktop-all.log`实际**310 passed／7 failed，51.61秒，exit 1**，2项既有warning保留；92份desktop源／测试hash前后零变化。7项均为U2 helper在长合成根中得到`INSTALL_PACKAGE_INVALID`，不写成317项通过。 |
| U2长根定因／短根复验 | `u2-long-path-proof.json`在原失败fixture新建`verified-proof`旁证目录，直接验证同一ZIP时真实抛`WinError 206`，目录名长259字符；未执行程序，原失败保留。只将7个失败用例移到新独立短根，`u2-short.log`为**7 passed／23 deselected，23.22秒，exit 0**。此为既有D3长路径边界的复现，不称长根已修，亦不合成为单轮整套通过。 |
| 本轮真实DeepSeek | 两次实际请求：整份generate HTTP200后`outcome_unknown/provider_error`，27422ms，无candidate且usage不可得；单栏process rewrite HTTP200／succeeded，7031ms，returned_model=`deepseek-flash`、total_tokens=2185。没有自动重发生成请求，后续rewrite启动executor时原unknown仍仅1 attempt。原5个配置／DB／密文源hash保持。 |
| 真实结果独立复核 | `real-ai-independent.json`只读核对11项全true：integrity／FK、draft与history2相同、revision5、仅process变化且逐字等于candidate、所有历史照片顺序／说明相同、6个受管原图／派生hash有效、仅2 attempts／1 candidate／1 provenance。Codex未新增调用；整份generate不记成功，复杂照片／教学质量未验。 |

真实输入只有两张48×36纯色合成JPEG及少量“共同搭建”文字，不能代表复杂照片效果。rewrite候选无具体姓名-动作指派、精确分钟或审核标签混入正文；工程保存核对与教师质量分开。初轮live JSON日志实际为GB18030，Codex按该编码解码后再核对SQLite与canonical文本；显示工具的错误编码不构成应用数据乱码，不据此修正文或延续旧R13误判。

## 6. 最终独立结论：源码与静态工程通过，冻结整体验证受阻

原会话r01／r02／r03均自然exit 0并停写；r03没有执行新冻结EXE或新增真实AI调用。Codex实际源读、无写入反例、独立执行及产物交叉核对后，**E14-R01–R06在当前Windows 11／CPython3.14.7标准GIL的源码、构建及静态分发范围关闭**。R06首轮失败目录保留偏差仍如§4所记，后续成功不改写该事实。

| 最终独立验证 | 实际结果 |
| --- | --- |
| 后端／前端 | 全local **759 passed**、typecheck与完整test:d1 exit 0；D1组件60／W5 94／历史22／更新13／观察54实际通过。171个后端与73个前端路径最终仍与测试前相同，不重复无变化套件。 |
| 桌面全套 | r03后新短根单轮`final-desktop.log`：**327 passed，60.14秒，exit 0**，2项既有warning保留；包括25项新构建保护回归。首次长根310通过／7失败及WinError206旁证、7项短根复验均保留，不宣称长路径已修。 |
| 源码真实WebView2 | 新合成库、r03前端、`final-window/report.json`：**17项全true，实际exit 0，notes空**；编辑／保存／历史／冲突／跨页选集／手调／单份及16份混合导出、不同园所与空园所标题、取消及busy归零／正常关窗通过。不是冻结入口或本轮原生Save As对话框证据。 |
| 旧库升级 | `final-old-upgrade/report.json`：**22项全true，exit 0**；0005→0006真实迁移旧25行逐字段保持、文档化回填、运行时prompt同步分列；升级前备份及manifest、完整性／FK、旧计划／内容／任务与二次重开均核对。只用合成旧库／假凭据。 |
| 冻结包静态 | `final-static.json`：**26项全true，exit 0**；仓外中文／空格／%／#路径副本，前端3文件、无缓存迁移／模板／Alembic、Pillow插件／许可、真实UUID身份及CArchive入口／PYZ 76生产模块均核对。不执行EXE，不把插件存在写成包内实际解码通过。 |
| 分发归档 | `final-archive.json`：**15项全true**；`final-artifact-linkage.json`另直接核对ZIP产品190文件与实际包及两份清单的集合／大小／hash完全一致；外层README／相对校验清单、无私有审计条目，文本无受保护源路径。不是仅相信ZIP内自己的清单。 |
| 源码及数据保护 | `final-source-before/after.json`：**336路径前后0变化**；实际构建冻结219路径与当前源逐项匹配、before/after稳定；原5个DB／WAL／SHM／锁／凭据blob最终hash均保持。原体验库、原件、旧包和远程资源未用于写入测试。 |

最终候选为`build/desktop-e14-r03/package/KGNext-E14/`，190文件、80,158,627字节；EXE SHA256 `524f9787d1dc8e455e73fdcd88621fa950ac0783fe36bef0d82b94e75b318b28`，build id `0d7e5bef-b44d-4e9b-b593-2d27a9cc1817`，版本0.1.0、schema 0006。完整便携归档及README／清单已按相同hash保留到仓库忽略的`build/desktop-e14-r03/dist/`；ZIP为43,645,128字节、SHA256 `d603aec85c391765c6a4907ce9392712cc57444578a09849a81e2dd4cf57cdf6`。只复制EXE不足以运行。

本轮应用真实DeepSeek共**2次**：整份生成HTTP200后unknown，无候选／usage不可得且未自动重发；process单栏重写成功，采用并重开独立核对11项全true。此前4次真实请求保持各自历史，不冒称本次四栏生成成功。MiMo无凭据、复杂照片与教师质量未验。7份Word逐页／原生保存及600图／大于30MiB容量仅按生产源码和模板hash不变复用前片；不是本轮新冻结输出实证。

**E14整包运行仍未通过。** r01实际被SAC以WinError4551阻止；当前没有签名证书或另一台测试设备，用户准备申请证书。r02／r03不以改名／换路径／新hash反复试跑，不修改系统保护。只读清点本候选107个PE，76个签名Valid、31个NotSigned，清单在`final-signature-inventory.json`；这不是签名或执行许可。后续证书具备后，需签名、重算产物清单／归档，并补普通冻结入口、包内图片实际解码、空／旧库冷启动、Word／原生保存、包内AI及相关关闭／更新集成。用户已授权完成后测试发行，当前条件尚未满足；正式更新URL／信任身份、安装／4551、Win10／WPS／干净机器／其他DPI显示器及D2／D3既有未验继续分列，不启动WebDAV／跨设备。

## 7. Git收口与接续

本次Git授权来自用户原始要求，源码／构建／静态可修项现已独立通过；据此由原OpenCode、build、`opencode-go/deepseek-v4.1-flash#max`在同一分支按Codex逐文件Git blob OID白名单正常提交推送已审核源码、测试及归并文档，以保存可继续签名补验的工作。**不将提交推送等同E14整体或产品／发行验收通过。** 不上传包、数据库、照片、凭据、日志或本地私有证据；不amend／强推／空提交，不另开实现者、分支或PR。

Codex随后核对批准树、父提交5808078、HEAD与远端、clean工作区及最终实际模型／代理元数据，回执保存在本证据根`git-final-check.json`与`model-audit-final.json`，不为回填自身SHA制造额外提交。唯一下一入口为[当前任务](../tasks/current.md)，剩余主阻塞为签名后的整包运行验证，不能用源码或静态结果替代。

Git前脱敏会话审计：开工时间边界后的303条assistant全部为原会话build／`opencode-go/deepseek-v4.1-flash#max`，最后finish=stop／succeeded；3次agent-switched均build→build，1次自动compaction同模型max、无agent字段，单列处理。三轮日志工具为shell／write／edit／read，task／子代理工具0，未发现嵌套OpenCode实施run。r01的199文件与r02的200文件分别再次逐项匹配其原manifest；最终原5个配置／DB／密文源hash保持。Git回执以随后独立文件为准，不在本段预写尚未发生的提交结果。

## 8. 暂按源码验证与Certum申请准备（2026-10-30）

本节保留当日证书选型阶段的记录；用户随后明确选择 MIT、授权开源准备，并确认模板由本人制作或已具备公开／MIT授权。MIT落地、当前文件隐私清理及源码复验结果另见[开源准备检查](open-source-readiness-review.md)。以下“未启动／未修改”等说明限选型研究时点，不作为后续开源准备仍未执行的判断。

用户决定当前暂用源码验证，近日自行申请Certum官网证书；起初要求按是否开源比较，随后明确先做开源版本，未来如商业化再从开源版fork，现阶段暂无商业化目标。具体许可证与公开范围仍需落实，本轮未更改仓库可见性、添加许可证或提交身份／程序材料。该决定不改变§6的冻结包未验结论，也不改变系统保护；源码工作不再以取得证书为前置条件。未来如需实现变更，仍由原OpenCode、指定Go模型实施，Codex独立审核。

本轮仅核对官方公开材料及本地声明。仓库已跟踪路径中未发现LICENSE／COPYING／NOTICE或项目开源许可声明；不能用npm的`private: true`判断远端仓库可见性，本轮没有据此作可见性结论，也未修改公开状态。

- [Certum产品说明](https://www.certum.eu/en/code-signing-certificates/)明确Standard（OV）可签发给个人。按用户随后作出的开源决定，当前优先建议Open Source云版；项目须先具备官方可核验的公开开源资料，后续商业分发另用适用的Standard等通用证书。
- [官方材料清单](https://support.certum.eu/en/code-signing-required-documents/)列明个人身份核验及本人抬头的水／电／燃气／电话等账单；开源款另需公开可查的项目网址及申请人与项目的明确关系，仅向个人签发，商业分发用途可导致撤销。中国大陆证件、中文账单、账单时效／替代材料及翻译公证是否需要，公开页面未具体闭合，应付款前向官方确认。
- 官网当前起价：[Open Source云版](https://shop.certum.eu/open-source-code-signing-on-simplysign.html)€49，[Standard云版](https://shop.certum.eu/standard-code-signing-in-the-cloud.html)€209；均需SimplySign手机及桌面客户端／网络，说明上限5000次签名／月。不是整包次数承诺，逐文件计次、实际可购套餐、税费及大陆服务可用性待官方确认。[商品列表](https://shop.certum.eu/code-signing.html)中的€25／€139是已有兼容卡和读卡器的电子激活码，不能当作首次完整签名方案总价。
- 证书用途与源码许可分开处理。[OSI说明](https://opensource.org/faq)中开源可用于商业用途，但copyleft可能对衍生分发有相同许可要求，另建fork不消除这些义务。[MIT许可](https://opensource.org/license/mit)可作为便于以后商业分支的候选，也允许其他人商业使用，仍须保留版权和许可声明；本轮只提出候选，未替用户确定许可证。后续还须核对第三方依赖／资源许可及贡献代码权利，不能只靠根目录LICENSE覆盖第三方材料。

不替用户注册账号、联系供应商、购买、上传证件或改变仓库许可；未启动OpenCode、应用、新冻结EXE、真实AI、签名或发行。仅更新当前决定和申请研究，未新增验证结果，不重复运行无变化测试。
