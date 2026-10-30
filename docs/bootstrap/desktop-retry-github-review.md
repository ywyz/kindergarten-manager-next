# AI手动重试与GitHub更新独立核查

更新：2026-10-30。状态：**RG-R01–R10已关闭，当前Windows 11／CPython3.14.7标准GIL下的源码／合成工程独立核查通过；继续源码体验，未发行。** AI失败／结果不明支持手动重试；更新通过固定项目GitHub最新正式Release判断。真实冻结安装、签名／SAC及正式发行资产仍未验。

## 1. 决定与边界

用户明确承认AI生成可能不稳定，要求失败／结果不明时提供重试；随后决定通过GitHub判断有无最新版本。按[观察记录§5.1](../specs/desktop-game-observation.md#51-生成与单栏重写)、[日计划C15](../specs/desktop-ai-daily-plan.md#1-已经确认不再重复询问)及[更新§10](../specs/desktop-application-update.md#10-2026-10-30采用github-releases检查新版)落实。

AI失败样本如实保留，偶发供应商失败不单独构成产品阻塞；检查失败说明、原内容保护、主动重试与成功结果审阅／采用。结果不明不自动重发，重试说明可能重复计费；应用缺陷仍须修复。GitHub来源选择不等于已有正式Release／公钥或冻结更新通过。

这里将AI波动作为产品需要支持的情况，不把既有unknown的具体技术根因改写为已证实的供应商故障；本轮成功也不承诺以后的每次调用都会成功。

继续原OpenCode会话`ses_ead8af71dffeJphI1NOWg4jZgI`、build、`opencode-go/deepseek-v4.1-flash#max`实施代码／测试／必要构建支持，Codex独立审核与文档。当前基线`e94ed688dd6e38f908644692339ffa76e523e28c`，同一分支。MIT准备结果归入[开源核查](open-source-readiness-review.md)，原OpenCode已提交推送，当前工作树开始时clean。

本轮只用独立合成数据／网络，不调用应用真实AI、不接WebDAV、不改Windows保护、不执行受阻EXE、不生成正式私钥、不创建Release或发布。原业务库／凭据／模板原件／旧包及Git历史保持；不安装或升级依赖、Skill、MCP，不改ARCHITECTURE.md，不另起实现者。

## 2. 开工核对

- 日计划`AiTaskPanel.vue`已有手动retry及费用确认，后端共享`retry_task`保留旧执行、创建新generation，并校验输入／当前execution。
- 观察记录后端已有record-bound retry接口；当前编辑页仅在终态提示“查看状态后重试”，未提供显式AI retry入口，且原始任务状态直接显示。需补页面与定点验证，不重新实现任务系统。
- 更新服务当前只读取固定源签名清单，源码模式禁用；现有E14包没有正式发行配置／更新器布局。GitHub latest发现、资产绑定和受限下载跳转须单独接通，不能只上传EXE或放宽成任意URL。
- codebase-memory代次`2026-10-29T23:42:06Z`，相关路径freshness为metadata_changed，故以实际源码／规格定点回读补证。图谱未命中不作为不存在实现的证明。

## 3. 独立结果

以下保留首轮发现和回修过程；最终状态以§4为准，不以实现者自测替代独立结论。

开工只读核对：公开GitHub latest接口实际HTTP404，未发送鉴权，返回`Not Found`；本次没有正式Release可下载，不创建假发行补证。旧5个业务／配置／凭据源hash与前轮保持，原E14 EXE／ZIP另记录本轮起始hash。私有证据保存于本机独立审计目录，不进入仓库。

| 核查组 | 必须取得的证据 | 当前 |
| --- | --- | --- |
| AI提示与明确重试 | failed与unknown区分；未知费用确认前无POST；确认后至多一个retry操作 | 合成页面／后端通过 |
| AI持久闭环 | 旧失败执行保留、新执行成功、候选可预览／采用，正文／照片／历史保持 | 合成持久闭环通过 |
| AI状态竞争 | 双击、保存中编辑、资料变化、切记录、晚响应／旧进度不误写 | 定点用例／探针通过 |
| AI操作未知 | response丢失先回执或同键重交，不换ID重复收费；record-bound回执不能串记录 | 合成用例通过 |
| GitHub版本 | latest正式版本、数字比较、同／旧／新、无Release、draft／pre与格式错误 | 合成通过；真实当前404 |
| GitHub信任 | 缺公钥／资产清楚区分、不能安装；tag／签名清单／资产／平台／build一致 | 测试密钥／完整ZIP通过 |
| GitHub网络 | API／资产域名路径绑定、公网DNS／TLS、有界跳转、deadline／取消、限流失败 | 受控TLS通过；真实API可达 |
| 更新接续 | 主程序与helper配置往返、完整包复核及U1–U3原数据／关闭保护不回归 | 合成程序／真实进程通过 |
| 源码与边界 | 不执行冻结载荷、不触原库／密钥、不真实AI、不生成私钥或发行，源码运行不自更新 | 保护核对通过 |

### 3.1 首轮独立发现（未批准）

下列来自Codex对正在交接的首轮源码的定点回读／独立探针，不用实现者自测通过替代；最终须在停写后复核并交回同会话。

| 编号 | 问题与证据 | 状态 |
| --- | --- | --- |
| RG-R01 | GitHub CDN实际HEAD返回`/github-production-release-asset/...`；实现仅允许`/github-production-release-asset-...`，独立URL探针拒绝真实形状。HEAD只读，无鉴权、无下载程序，时效查询未存储。 | 已复现，待回修 |
| RG-R02 | 实际SFC探针：旧unknown执行→手动retry→新pending仍指旧execution，页面显示旧思考和999999ms；不得用新pending的空绑定接受旧进度。 | 已复现，待回修 |
| RG-R03 | 独立阻塞manifest响应，状态提前available；第二次check导致第2次latest请求，未覆盖整个检查期间的去重。首探针缺少fake HTTPResponse.read1，是验证夹具错误；纠正后才取得此证据，首记录保留。 | 已复现，待回修 |
| RG-R04 | 检查过程向业务data根写update_release.json，但产品helper仍以自身固定配置为权威；该新增写入不应进入业务根，须验证实际产品信任配置接续而非仅test context往返。 | 源读发现，待回修／验证 |
| RG-R05 | 新GitHub用例主要mock掉实际URL连接，available又在签名完成前出现；现有通过数不足以证明真实受控TLS／跳转、完整包／坏签名／hash、取消及helper接续。 | 待补证 |
| RG-R06 | 新AI用例尚缺失败／单栏、retry丢回复同键、重开、成功候选采用及正文照片保护、record-bound后端新generation闭环。 | 待补证 |
| RG-R07 | 新增update_github.py没有进入现有E14构建source_freeze，独立实际调用仍219文件且规范化路径集合缺此模块；静态核查关键模块列表也遗漏。应补来源／归档核查覆盖，不因此启动新构建或复用旧包证明。 | 已复现，待回修 |

首轮实际交接：原OpenCode CLI自然exit 0，20个当时改动／新增文件私下按hash保存。实现者自测为更新专项及U1／U3共47、观察后端53、完整前端与typecheck通过；这不关闭上述独立问题。r01后段已将配置写入移至updater目录，业务根写入部分修正；直接覆盖helper配置的安全写入／安装在途与产品链路仍需核对。首轮result曾出现完整本机路径，已作为r02脱敏要求。随后RG-R01–R07已正式交回同一会话／同模型，尚未Git。

### 3.2 r02期间独立安装反例

RG-R08（必须修复）：r02抽出`_verify_saved_package`后，`run`调用未接收返回值，后面仍引用`verified.root`。Codex在新短根独立执行原`test_helper_reverifies_original_zip_and_switches_directory`，实际1 failed，结果`INSTALL_HELPER_EXCEPTION / NameError / unknown`。该测试使用合成旧进程、临时程序目录／数据库／假凭据；日志和失败现场保留，不触原业务。实现者当时通过的55项命令实际只含GitHub／U1／U3，遗漏U2，不能称原安装回归通过；后续须修复并独立跑完整U2，首次失败不删除。

RG-R09（状态文案）：新增终态分支把`paused`也用“AI结果不明／可能已处理”toast提示；暂停可能是配置或已知未发送，与unknown不同。需按持久状态分别提示，不能用AI波动混淆配置暂停和已发送结果不明。

r02实际交接：原CLI自然exit 0，26个当时改动／新增路径私下保留。Codex独立探针确认：真实CDN形状接受、API来源拒CDN、manifest在途保持checking且第二次check仍仅1次latest、source_freeze现220文件包含新增模块；实际SFC新pending的旧思考隐藏且elapsed=0。独立完整前端／typecheck通过（观察61），全local仍在运行。RG-R08／R09已交回r03同会话，暂不Git。

### 3.3 r03独立结果及最终入口核对

原r03 CLI自然exit 0，RG-R08返回值及RG-R09分别提示已修复。Codex独立全local761通过（757.26秒），381个源码／测试／资源记录中backend路径在测试期间未变；全桌面新短根351通过（62.39秒，2项既有deprecation warning），包含完整U2 30项。新源码前端构建成功，原3份前端文件私下备份；真实WebView2 report 17项全true、实际exit 0、notes空。该窗口检查编辑／保存／历史／导出／关闭等既有流程，不冒称新retry已在真实供应商或原生窗口逐项验收。

实际产品UpdateManager以固定公开仓库、无公钥、源码不可安装配置检查GitHub，结果`no_release / UPDATE_NO_RELEASE`，download_available=false、allow_install=false、shutdown成功且未创建暂存目录；不把没有Release写成已最新。此前只读HEAD仅证实真实CDN跳转形状，本项目仍无正式包可做真实在线升级。

RG-R10（入口隔离，待回修）：`load_github_source`普通产品配置读取路径会解析`test_only`、`connect_host`、`connect_port`、`ca_pem`等测试覆盖。Codex用独立配置文件调用普通loader及validate，实际接受测试模式／回环连接／端口覆盖，网络请求0。产品JSON不得开启这些参数；受控测试须留在显式内存构造／既有专用源码验证入口，修复后补拒绝用例与更新回归。其余已通过范围不因该发现改写成未执行，暂不Git。

## 4. 最终独立结论与源码交付

原会话r01–r04均自然exit 0并停写；实现／测试／必要构建核查支持由原OpenCode完成，Codex未直接修改这些文件。按本轮CLI实际发出的message ID逐一核对导出元数据，351条assistant消息全部为build／`opencode-go/deepseek-v4.1-flash#max`，parentID为空；较早历史会话的plan／default变体不计入本轮。工具为shell／write／edit／read，无子代理；初始文本启发式把含私有opencode日志路径的`npm run`误列为嵌套运行候选，逐条核对均是npm命令，实际没有另起实现运行。

RG-R01–R10最终全部关闭：真实CDN路径与有界跳转、检查去重、旧执行进度隔离、helper固定信任配置、完整受控TLS／ZIP链、AI失败到重试成功候选／采用、构建来源覆盖、U2返回值、暂停提示和产品配置隔离均已复核。普通GitHub及固定源loader遇任何测试专用字段（含false／null）都拒绝；显式内存测试构造保留。未知结果仍不自动重发，重试不保证供应商必成功。

| Codex独立验证 | 实际结果与身份 |
| --- | --- |
| 后端全local | **761 passed**，exit 0，757.26秒；包含合成失败→新generation→成功候选→采用及照片／旧执行保持，相关backend路径在执行期间未变 |
| 最终桌面全套 | **368 passed**，exit 0，65.35秒；新短根，含GitHub40、U1 30、U2 30、U3 2及E14guard26，2项既有deprecation warning，不安装升级依赖；不宣称D3长根206已修 |
| 前端 | r02完整test:d1与typecheck exit 0（组件60／W5 94／历史22／更新14／观察61）；r03最终观察**62**及typecheck再次独立exit 0，最后仅暂停文案／对应用例变化 |
| 前端构建与真实源码窗口 | README使用的`build/source-preview/frontend`已更新，旧3文件私下备份；构建exit 0，实际WebView2 report **17项全true**、exit 0、notes空。新retry的付费故障分支证据来自组件／后端合成，不冒充真实供应商或窗口逐项体验 |
| GitHub实际读取 | 实际产品代码无公钥源码配置读取固定公开latest，返回`no_release / UPDATE_NO_RELEASE`；不可下载／安装，正常shutdown，没有创建暂存目录。另有官方公开资产只读HEAD的真实302路径证据，未下载／执行该程序 |
| 反例复验 | CDN真实形状接受、API-only拒CDN、manifest在途checking／仅1个latest、新pending不显示旧思考与等待、220文件来源清单包含新模块；原配置反例被两个普通loader拒绝 |
| 保护与同源 | 最终403个源码／测试／资源路径在最终桌面测试前后无变化；5个原业务／配置／凭据源及旧E14 EXE／ZIP hash保持；27个当前改动／新增文件的本机Users路径／私钥／GitHub token定点扫描0命中 |

私有日志、首失败、r01／r02源码快照、两种验证夹具误判及纠正记录保留，不用后续成功覆盖原失败。公开文件只保留相对证据名和结果，原始业务、密钥、照片及私有审计材料不进入Git。

Git收口范围为这27个已核对文件，由原OpenCode按批准blob清单正常提交推送；不amend、不强推、不建Release或改默认分支／可见性。实际提交身份以Git及最终回执为准，不为自指SHA再制造提交。

当前无本轮剩余编码事项，可按README继续源码体验。正式发行公钥／签名清单／完整程序资产、首次安装／快捷方式、最新源码对应冻结入口与更新、SAC4551、教师质量／完整体验、MiMo、Win10／WPS／其他显示配置及原D2／D3未验保持；GitHub尚无正式Release，不能称真实在线升级已验。WebDAV／备份后续工作未启动，公开历史个人信息问题仍见开源核查，不在本轮重写历史。
