# D2 W4独立工程核查

状态：2026-10-18，**W4通过当前Windows 11合成环境工程核查，停在W4**。用户授权OpenCode使用Go套餐DeepSeek V4.1 Flash实施，Codex独立核查并交回R01–R09修复，均已关闭。最终稳定源码全local470项、桌面146项及独立真实本机HTTP复核通过，详见§8–§10；未调用应用真实AI、未发布，不代表完整D2产品或发行验收。

## 1. 范围与基线

有效入口为[当前任务](../tasks/current.md)、[产品规格§9](../specs/desktop-ai-daily-plan.md)、[工程规格§2.2/§5/§6/§7](../specs/desktop-ai-engineering.md)。W4限候选列表/详情、预览、原子采用、来源与基准严格校验及对应保存/导出读取链；W5完整界面、W6完整包/人工Word页验、真实供应商均未启动。

开工非忽略文件快照417项，证据根 `%TEMP%/kgm-d2-w4-codex-ql230lkl`，`before-sha256.json`、`before/`、`before-git-status.txt`。当前分支 `codex/desktop-v2-foundation`，既有未提交/未跟踪内容保留。

OpenCode会话 `ses_eb10aefb2ffe7hj5Oz7nUjhlFD`，启动参数指定 `opencode-go/deepseek-v4.1-flash`，CLI执行会话53042，日志 `opencode-w4-run1.jsonl`。本轮不另起实现者；Codex不写实现、迁移或测试。

按codebase-memory技能查询项目与相关符号，图谱generation `2026-10-18T03:33:58Z`；相关路径存在metadata_changed，已改用限定源码审阅。图谱仅作定位，不能当最新代码证明；未安装或重建工具。

## 2. 本轮核查门槛

- G03：合法拆分基准及来源完整链、旧null、手工续存/重启/导出可读，损坏关系拒绝且不清空。
- G10：采用回执先查、同键同体/异体/跨域、耗用token后与重启后恢复、多token并发、无变化不增版。
- G11：三类严格编辑schema、原始基准独立于教师预览编辑、来源/目标/无关变更区分、选中字段及来源/版本/回执/审计原子提交，失败全回滚。
- API边界与现有回归：Host/Origin/session、材料不进列表/错误日志、分页、跨计划404；W1–W3与D1保存/导出不回退。

后续追加实际审阅、失败、修复和独立执行证据；模拟与结构证据不替代真实供应商或完整教师/Word验收。

## 3. 首轮审阅发现（历史过程，最终关闭见§9）

以下基于首版源码，尚未宣告最终缺陷状态；需由OpenCode修复并提供先失败后通过的证据。

- R01：`ai_adoption.adopt` 的请求指纹只含plan/candidate/expected_version，完全遗漏preview_token。因此同request_id换成相同候选/版本但不同选择或教师编辑的第二token，会回放第一次成功结果而不是AI_REQUEST_CONFLICT。应绑定完整采用请求（token本身或其服务端可核验身份），并保持token耗用/重启后同体回执可恢复；未提交时换新token同key重试仍允许。
- R02：token虽然记录content_version，但adopt不比较payload.content_version与请求expected/current，只比较请求expected与当前版本。客户端把expected改成新版即可让旧预览在无关字段更新后直接通过。必须在事务内核验token绑定版本、来源、目标、契约及有效期，不允许通过改expected绕过重新预览；来源变与目标变按规格错误码区分。CAS还应核对原content_id/version三元指针。补对应真实HTTP反例。
- R03：`candidate_applicability`及preview/adopt仅检查代码常量SUPPORTED_CONTRACT_VERSIONS，不检查该任务当前required契约。required升级到2后旧v1仍被判eligible并可采用，违反旧契约只读要求；应按当前头部及有效契约判断，且预览后契约变化也要阻断。
- R04：共享`ai_provenance.resolve_baseline`只检查candidate类型/plan/process，未核验成功execution、候选hash/完整schema及输入来源关系；`baseline_from_model_process`还会把非string静默转成空串。合法空串须保留，损坏字段不能修补。候选读取/采用也需要拒绝损坏候选；补失效执行、原始候选畸形/被改、同文不同来源及直接损坏行用例。旧契约候选可读与当前可采用校验应分别处理，不能因旧契约升级破坏历史基准。
- R05：候选详情source缺工程契约规定的dependencies；其他活动source_excerpt不包含实际活动/游戏配置输入，无法核对所用材料；需按§5.1补真实必要来源，列表仍不含材料。来源变化错误应给安全的变化字段提示。

Codex独立首版反例：使用隔离LOCALAPPDATA/credential_root与合成SQLite，经正常create_task→claim→dispatch_mark→finalize_success产生候选，再由真实Uvicorn本机HTTP预览/采用；没有外部AI请求。`%TEMP%/kgm-d2-w4-codex-ql230lkl/codex-prefix-r01-r02.json`记录：R01第二个不同编辑token使用同request_id返回200且与首次结果完全相同；R02先预览v1、保存无关反思为v2、旧token配expected=2仍返回200并产生v3。两反例均确认首版风险，源码hash随证据保存；临时夹具自动清理，原教师库未触及。

第二组Codex独立真实HTTP反例（证据`codex-prefix-r04-r06.json`）：正常候选落库后仅在合成库故障注入execution.state=failed，候选详情仍200、preview200、adopt200，但采用后读日计划变503 LOCAL_STORAGE_ERROR。这确认R04首轮补丁只在已有baseline读取时检查成功执行，尚未在候选读取/预览/采用新候选前校验，能把可用计划写成无法读取。请抽取统一candidate关系验证用于全部三类，不限split已有基准；校验execution/task/input的对应身份、契约/schema等并拒绝错误来源，不将missing input降格成source_changed。

- R06：采用时先比较content.version并抛VERSION_CONFLICT，使正常保存后的来源变更和目标变更都走同一版本错误，AI_TARGET_CHANGED在正常写路径不可达。独立HTTP已证实：旧token后保存新原文、或只保存集体主题，两者均返回VERSION_CONFLICT。应保留token/request绑定检查，在事务内按来源变化→目标变化→无关版本变化分类：分别AI_SOURCE_CHANGED、AI_TARGET_CHANGED、重新预览的版本冲突；都不得写入。preview本身expected旧仍保持VERSION_CONFLICT。三类source/target/无关差异都需覆盖，依赖与target重叠时来源优先。

R02补充：缓存目前为模块全局且只绑定runtime.launch_id，未绑定实际app session；同runtime重新create_local_app更换X-App-Session时，旧token仍可用。请使HTTP预览凭证作用域绑定本次app会话（可用app创建时随机内部scope，不保存会话密钥），并补换session/launch后拒绝、成功回执仍可恢复的验证。不新增产品流程或全局配置。

R04存储错误边界补充：`codex-prefix-malformed-candidate.json` / 同名log记录，在合成库将raw_candidate_json直接故障注入为非JSON文本后，真实HTTP详情返回500 INTERNAL_ERROR（预期503 LOCAL_STORAGE_ERROR）。SQLAlchemy在session.get/列表物化阶段就解析JSON，raw_candidate(candidate)内部try无法覆盖这一步。请在候选/输入/来源行的读取边界处理持久JSON解码/不可规范化异常，列表、详情、预览、采用及已有基准读取保持安全存储错误，不把损坏视作可采用或source_changed。

验证记录要求再次说明：测试进程须显式隔离LOCALAPPDATA与credential_root，并设置APP_DISABLE_DOTENV=1；保留完整日志和实际测试进程退出码。不要仅凭管道tail的退出码记通过。已有71项日志显示OK，但单独保留其有限范围，不替代W4专项和最终回归。

## 4. 验证质量问题（R07，已关闭）

首版`test_multi_token_concurrent_single_success`只有连续两次service调用，并没有线程/进程/屏障，不证明并发；`test_commit_failure_rolls_back_then_retry`在_record_operation抛错，尚未到receipt或COMMIT，证明的是中途回滚，不是提交失败。请如实命名保留这些有价值场景，并另补：真实本机HTTP并发（至少不同token不同key、相同token同key，独立请求/Session在屏障后交错），实际Session.commit边界故障（已flush内容/provenance/审计/回执后失败，核对四类行及计划指针全回滚，同键重试），成功提交后丢响应/重启读取回执，以及三类HTTP采用/strict schema/Host-Origin-session/no-store。真实睡眠/桌面UI/Word人工仍不在本轮。

测试命令继续使用tail且未显式设置LOCALAPPDATA的中间记录不得写成已满足隔离/完整日志要求；请以最终显式隔离环境、完整日志、实际退出码完成对应验证。Codex最后会独立重跑。

## 5. Codex独立HTTP及导出探针（首跑）

`%TEMP%/kgm-d2-w4-codex-ql230lkl/codex-independent-http.json` / `.log`：独立Uvicorn真实HTTP，正常W3服务链产生候选，合成SQLite/credential_root/LOCALAPPDATA，APP_DISABLE_DOTENV=1；执行前后7个核心模块hash一致。70个检查中69个通过，最后1项失败，退出1，不能记成全通过。

已通过：三类HTTP预览/采用；预览零持久写；拆分raw基准与教师编辑分离；适龄只改过程；其他活动仅选中晨间/谈话，未选post组ID不变、共享指导保留；同键准确重放/异token冲突；语义no-op；手改原文/过程保持基准；真实DOCX保存内容/红色差异（同根independent-adopted.docx，结构证据，未人工页验）；来源/目标/无关变化正确分类及改expected拒绝；两线程屏障后的真实HTTP双token200/409、同token同key200/200且只一个新版本；无基准手工适龄；空字符串原始基准；实际Session.commit抛SQLAlchemy OperationalError后的四类行/指针全回滚、同key重试成功；失败execution与损坏JSON拒绝且不破坏计划。

- R08：最后跨计划隔离反例失败。把B计划候选JSON故障注入为非JSON，再在A计划路径请求B候选时，没有返回统一404。`ai_candidates._require_candidate`用session.get按id先取整行，SQLAlchemy先解码JSON，再检查daily_plan_id，导致外计划坏候选泄露为503。应在数据库查询条件中同时限定id与plan.id，先过滤归属再物化JSON；列表/详情/preview/adopt对foreign/notfound保持相同404。同计划坏JSON仍503。补正常foreign、坏JSON foreign及不存在候选的HTTP验证，不弱化本计划存储错误检查。

## 6. Codex独立边界复核

`codex-independent-boundaries.json` / `.log`：44检查/44通过、退出0，执行前后7核心模块hash一致。真实本机HTTP已验证候选编辑unknown/baseline/reflection/null/单串/UTF-8总量/空或重复目标拒绝；Host、Origin、session和no-store；跨域request_id；token过期和同runtime不同app会话；发出HTTP后直接关闭客户端、不读取回包，持久回执及精确重放；冷重启后的未提交token拒绝/已提交回执恢复/基准可读；缺板块不可选；R08外计划坏JSON及不存在候选详情/预览均404，本计划坏JSON503；预览后required契约升级阻止采用、旧候选可读且已采用历史基准仍可读。最终integrity_check=ok、foreign_key_check=[]（JSON损坏行作为明确故障注入不影响FK检查）。无真实供应商调用。

首跑69/70的失败证据保留；R08定向关闭由本节补足。两组检查有重叠，不相加冒充不重复用例总数。当时最终回归、实施者证据及范围比对待收口；最终结果见§8–§10。

## 7. 最终并发复审发现R09（已修复并独立复验）

`codex-prefix-r09.json`：真实Uvicorn双HTTP同token同request_id；仅在第一个请求查回执后、取token前挂屏障，让第二请求完整提交并消费token，再放行第一个请求。结果胜方200，迟后请求409 AI_PREVIEW_EXPIRED，内容仅v2。没有替换路由或持久写入。问题在adopt的首次receipt读取与事务外token.get间窗口：token不存在时直接返回，没有再次读取已提交回执。

这违反“成功回执优先、同键同体回原结果”；已有HttpConcurrencyTests.test_concurrent_same_token_same_key把200/200放宽成允许409，不能作为关闭依据。请在拒绝缺失/已消费token前保证重新检查持久回执，或将权威receipt/token检查组织在同一短写事务内，保持不同请求体409 AI_REQUEST_CONFLICT、真正失效无回执token409不变。补上述确定性交错，断言两个相同请求均200且结果相同/仅一内容版/一回执，不能接受409凑通过。

同轮Codex最终回归已启动，代码若再变以执行前后hash及最终定向复跑区分，不将旧代码回归冒充最终代码通过。

R09关闭补证：`codex-final-r09.json`，Codex再次独立执行同一真实HTTP确定性交错，两个状态均200、结果相同、内容v2、采用回执1，exit0。修复后的ai_adoption.py SHA256 `c5dc3904d85777eaea37df801676b2c83f77f03489c96317365f31fab239ce57`。实现者新增确定性屏障断言，已删除原允许409的放宽条件；47项W4专项最终日志在`%TEMP%/kgm-d2-w4-opencode-run3/unittest.log`，28.644秒/OK，最终仍以Codex完整核查为准。

## 8. 全量回归和源码稳定性

第一轮Codex全local：`final-local/unittest.log` / `result.json`，470项、321.224秒、退出1；唯一失败为`GuardTests.test_local_package_import_is_isolated_from_legacy_configuration`启动独立Python时读到OpenCode正在编辑的ai_adoption.py中间文本，报IndentationError。执行前后104相关文件hash发现ai_adoption.py与test_d2_w4_api.py变化，不能写成通过。当前最终源码AST正常、R09独立探针和实现者47项专项通过；当时待实现者停止写入后重跑完整回归；本轮失败保留，最终稳定复跑见下。

Codex独立桌面回归：`final-desktop/pytest.log` / `result.json`，146项/8.59秒/exit0，APP_DISABLE_DOTENV=1、LOCALAPPDATA隔离；两项既有Starlette/httpx和AnyIO弃用警告，没有安装或调整依赖，也没有真实窗口/睡眠/IME验证。

第二轮Codex全local在实现者结束写入后执行：`final-local-stable/unittest.log` / `result.json`，**470项/303.675秒/exit0**，包装进程总耗时307.123秒。命令为仓库根执行`desktop/.venv-d1/Scripts/python.exe -X utf8 -W always::ResourceWarning -m unittest discover -s backend/tests/local -t backend -v`；显式`APP_DISABLE_DOTENV=1`、独立`LOCALAPPDATA`及各用例合成`credential_root`。CPython3.14.7 AMD64标准GIL；执行前后104个本地实现/测试/desktop相关文件SHA256全部一致，`source_stable=true`、`changed_paths=[]`，无ResourceWarning。测试内`log-capture-sanity`为日志断言的预期输出。第一轮失败不覆盖，本轮最终源码通过据此确认。

## 9. 修复关闭及范围核对

所有实现与测试修改均由同一OpenCode会话完成；session导出实际模型为`providerID=opencode-go`、`id=deepseek-v4.1-flash`，与用户指定Go套餐一致。实现者最终回复明确源码冻结，CLI退出0后，Codex才启动第二轮完整local回归。实现者自测日志已读取：W4专项47项/28.644秒，全local470项/295.127秒，桌面146项/4.28秒，均通过；这些与Codex独立结果分别记录，不以实现者结论代替独立核查。

| 问题 | 最终核对及关闭依据 |
| --- | --- |
| R01 请求指纹不含token | 完整采用请求含原token；独立HTTP同键异token409，同体耗用后/重启后回原结果 |
| R02 token版本/会话绑定 | 独立HTTP改expected不能绕过；同runtime不同app scope拒绝旧token，TTL与冷重启拒绝未提交token；成功回执保留 |
| R03 required契约 | required升级后预览/采用拒绝，旧候选仍可读；已采用历史基准不受新required影响 |
| R04 完整候选/基准链 | 故障注入失败execution、畸形JSON等被拒，采用前阻止损坏计划；严格schema/hash及task/input/execution身份；合法空串、旧null、手改续存和重启/导出读取通过 |
| R05 来源详情 | 详情具有真实dependencies；其他活动源含游戏配置/计划快照/日历；列表无材料，变化提示仅安全字段名 |
| R06 变化分类 | 来源、仅目标、无关版本分别得到规定错误；重叠来源优先；正文及候选编辑不被服务端冲突写入覆盖 |
| R07 验证证据不足 | 补真实HTTP并发、实际Session.commit故障全回滚和同键重试；使用显式隔离根、完整日志、真实测试退出码；旧顺序/中途故障用例如实改名 |
| R08 外计划损坏行 | SQL先过滤plan/id，再物化JSON；独立边界44/44含外计划坏行/不存在404、本计划坏行503 |
| R09 回执/token竞态 | 独立确定性HTTP交错先失败409/200、修复后200/200同结果、一内容版一回执；最终回归严格断言，不接受409放宽 |

范围证据`scope-before-docs-closeout.json`：对开工417个非忽略文件，7个既有Python文件改变，新增3个生产模块及2个W4测试文件；无开工文件消失。12个实现/测试文件的最终SHA256均与[实现结果§1](desktop-d2-w4-result.md#1-本批改动范围)相符。后续Codex只维护任务入口、规格、索引和核查文档。`0001–0004`历史迁移、依赖/锁、前端、desktop实现、ARCHITECTURE.md、旧云端代码及已有非相关工作与开工内容一致；没有安装、commit/push、打包或发布。`git diff --check`未发现错误（Git提示部分既有文件未来LF→CRLF转换）；本轮12个Python文件另查无尾随空白。

文档收口后的`scope-final.json`/`final-sha256.json`记录424个非忽略文件：相对开工14个既有文件改变、7个新增、0个消失，除上述实现/测试外均为本轮文档。全local结束后再次核对104个源码/测试hash，无新增变化；相关Markdown本地文件链接均有效、无尾随空白。最终按仓库原Git配置执行`git diff --check`退出0（`git-diff-check.log`）。

独立真实API探针为本机Uvicorn/SQLite正常任务链＋明确故障注入，未启动外部AI请求。导出样本`independent-adopted.docx`验证已保存文本、原模型基准和教师修改红色差异的OOXML结构；不等于Word/WPS实际逐页验收。完整界面、关窗交错、真实睡眠、最终D2包及其同源/逐页验证、真实供应商、干净机器、Win10、其他DPI/多显示器与发行再现性仍未验；D1已完成人工证据保持，不重复微软拼音验证。

## 10. 最终工程结论：W4通过，停在W4

W4「日计划三类候选与原子采用」在当前Windows 11、CPython3.14.7 x64标准GIL、独立合成SQLite/凭据根环境**工程通过**。OpenCode使用用户指定Go套餐DeepSeek V4.1 Flash实现，Codex独立审阅、执行反例及复验；R01–R09全部关闭，当前无剩余W4编码或修复项。

- G03的W4候选/基准完整链、旧null、合法空串、教师手工续存、重启和导出读取已通过；损坏关系/存储拒绝且不静默清空。
- G10的W4采用回执、同键同体/异体/跨域、丢回包、耗用token/重启恢复、无变化不增版和真实HTTP并发已通过；R09按确定性交错复验。
- G11三类采用、教师预览编辑与原模型基准分离、来源/目标/无关变化区分、未选板块保留、内容/来源/指针/回执/审计原子提交及实际commit故障全回滚已通过。
- 最终独立全local470项与桌面146项通过。API首轮69/70的R08失败已由44/44边界复核关闭；R09另有独立先失败后通过证据。以上含重叠场景，不相加为独立用例总数。

这不是完整D2工程或产品验收。G12、G13完整界面/真实睡眠、G14完整Word人工页验、G16最终整包及G17/G18真实供应商/教师流程等按W5/W6和后续授权继续；W4的DOCX结构证据不替代这些未验项。没有应用真实AI调用、WebDAV、发行、commit/push或新包。原教师体验库/导出文件、D1/W1包及W3探针保留；本轮只使用合成根。

实施独有接口细节已归入[工程规格§5.2](../specs/desktop-ai-engineering.md#52-端点与写入字段)的W4细化段，失败和未验项保留在本记录及[实现结果](desktop-d2-w4-result.md)。[当前任务](../tasks/current.md)收敛为W4完成与下一包边界，不保留新旧提示词副本；W5/W6未启动。
