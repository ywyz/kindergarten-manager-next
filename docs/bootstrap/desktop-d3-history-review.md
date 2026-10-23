# D3-A 本机历史恢复：Codex独立核查

日期：2026-10-23。状态：**H1／H2在当前Windows 11隔离合成环境的源码工程核查通过，R01–R11关闭**，最终证据见§9。H3冻结包与教师包体验仍未验，4551保持；源码工程、产品体验及发行不互相替代。

## 1. 授权及基线

用户本轮明确要求按`docs/tasks/current.md`由OpenCode Go套餐DeepSeek V4.1 Flash实施，Codex审核，不通过交回修复，通过后提交并推送；随后撰写下一步提示词，待用户审核后再派发。该授权替代当前提示词末尾的本轮禁止commit／push，但不授权发布、真实AI、签名采购或修改系统防护。

分支保持`codex/desktop-v2-foundation`。开工时已有D2教师话语r3、宿主保护及对应测试／文档未提交；完整状态、差异与源文件hash保存至`%TEMP%/kgm-d3-history-codex-20261023-185311/`，不回退或混写为本轮新实现。

本机OpenCode CLI现为2.1.2，沿用会话`ses_ead8af71dffeJphI1NOWg4jZgI`。派发前通过`api --standalone GET /api/session/{id}`核对idle／succeeded及`opencode-go/deepseek-v4.1-flash#default`；脱敏开工会话保存为`session-before.json`。H1通过`run --standalone --session ... --model opencode-go/deepseek-v4.1-flash#default --agent build --format json --auto --file docs/tasks/current.md`派发，日志为`opencode-h1-r01.jsonl`及独立stderr／exit文件。最终还需核对本轮新增assistant实际模型元数据。

CLI不在当前PATH，使用已安装绝对路径；桌面server要求口令，未读取或输出凭据，改用CLI自身支持的standalone。旧版`/session/status`返回HTML，未将其作为空闲证据；正确v2会话接口核对后才派发。

## 2. 核查方法与边界

本轮使用已安装codebase-memory技能，项目`C-Users-yw980-code-kindergarten-manager-next`可访问，索引代次为`2026-10-23T10:48:43Z`。相关服务／模型／编辑器路径覆盖为`no_recorded_issue`但`metadata_changed`，因此按限定源码回读复核；不继续沿用前轮Transport closed作为当前事实，不把覆盖信号当作完整性保证。后端save／baseline／adopt相关查询31条已分页取全。

OpenCode唯一写实现、测试、迁移和构建／验证脚本；Codex及核查子代理只审阅、写规划／结果文档并执行独立验证。合成验证禁dotenv，使用独立无真实凭据根，不迁移真实教师库，不读取或复制密钥。

重点核对历史正文与身份完整性、基准来源链、复合外键、回执优先及幂等、短事务原子性／竞争／回滚、前端保存／IME／候选草稿协调、迟到响应和结果不明保护，以及恢复后Word基准语义。H1通过前不派H2。

teacher-talk-r01未签名EXE的4551仍独立保留；不改SAC／WDAC／Defender／信任根，不重建试错，不以源码窗口替代冻结包验收。原D2真实A v6、B未采用、C未发起及5次DeepSeek／0次MiMo事实保持。

开工额外记录两份真实数据库及r03／teacher-talk-r01包共414个文件hash（`protected-start-hashes.json`）。两库分别为`d8e87fe2…b584c`和`aa6267e7…639e4`，与前轮关闭后证据相同；仅作字节核对，未迁移、运行或读取凭据。

原有D2改动经独立只读复核：11个源码／测试文件与teacher-talk既有`reviewed-source-hashes.json`逐项一致，原日志确认为58＋63＝121项后端、12项桌面通过，首次冻结包仍WinError4551／exit3。定点22个源码／测试／文档未发现常见真实密钥／私钥／GitHub token模式；新测试仅合成凭据。原D2修改可纳入本次提交，原未跟踪结果文档及D3规格也应保存。该复核不替代新D3验证。

## 3. Certum官网价格及后续签名方向

用户本轮表示预计采用Certum官网证书；当前只查网址和公开价格，不采购、注册、联系销售、上传材料或签名。2026-10-23核对官网欧元商店的期限选项及价格：

| 产品 | 1年总价 | 2年总价 | 3年总价 |
| --- | ---: | ---: | ---: |
| [Standard Code Signing in the Cloud](https://shop.certum.eu/standard-code-signing-in-the-cloud.html) | €209 | €319 | €419 |
| [EV Code Signing in the Cloud](https://shop.certum.eu/ev-code-signing-in-the-cloud.html) | €379 | €599 | €825 |

[Certum官方说明](https://www.certum.eu/en/code-signing-certificates/)允许Standard用于个人或公司，EV面向注册企业；本项目大陆自然人优先考虑Standard云签。公开页面gross与net当时显示同一金额，未进入结账；实际税费和实付总价以购买主体／账单地址后的结果为准。大陆个人材料及受理尚未得到供应商书面确认。

2／3年为服务期限，产品页说明2026-02-27起单张证书最长459天，服务期内需免费重签发。签名能力不等于SAC运行或产品验收通过；旧包、23个未签名候选PE及76个已有有效签名的保护事项仍见[G17结果§8–10](desktop-d2-g17-result.md)。

## 4. H1实施中预审（待交付后复核）

以下来自实施中源码快照，不提前作为最终缺陷或通过结论。首轮交付后逐项核对，仍存在则交回原OpenCode修复：

- R01：`restore`最外层回执重放仅核对档案，未校验计划仍有效且属于当前班级；软删除／错班后同请求可能返回成功，与所有历史接口的归属门槛不一致。
- R02：任意`IntegrityError`被统一改为恢复请求冲突，可能把FK／CHECK／审计写入等存储错误误报为幂等键冲突；无回执时须保留真实错误分类及完整回滚。
- R03：历史列表直接物化内容行，未核对当前指针／历史完整性；损坏JSON未映射存储错误，内容全缺时可能显示空历史。
- R04待核定：预览摘要仅绑定正文及基准值，不含基准来源身份；预览后来源被替换为相同正文的另一条候选时需仍能识别来源变化。

实施中`models.py`曾出现class和docstring合为一行的语法错误，交付及运行前需确保修复；不由Codex直接修改实现。

19:02独立HTTP探针已复现R01／R03（`h1-preliminary-probes.json`，服务SHA256 `cc63a0900cc10bf16e99b3fd0f265f526d033d1209f2367c03213ab037d929bc`）。真实临时SQLite及Uvicorn：软删除后同请求返回200，预期404；历史JSON畸形时列表500／INTERNAL_ERROR，预期明确存储错误。合成现场`%TEMP%/kgm-d1a-test-ug2t0joq`保留，关闭服务／数据库句柄，不触碰真实数据。探针exit0只表示成功记录复现，不表示产品通过。

R05待核对：新历史入口需要拒绝不支持的历史格式；现有`resolve_baseline`对未知候选契约跳过结构校验，不能据此直接恢复未知格式。应在历史入口按支持的契约做限定校验，旧指导r1／r2仍属v1契约，不能误伤；D2历史读取原语义不随本片改变。

首轮测试覆盖还需核对规格§8：真SQLite并发同键／不同键、各写点及COMMIT失败整体回滚、重启后的只读回执、原D1／D2数据升级保留、跨计划三组FK、旧修订基准／旧游戏身份、严格API输入与来源保护、旧AI预览拒绝及候选重新适用性。不以几个主流程用例或原迁移套件的数量替代这些新增行为。

R02独立复现：在隔离库对`restore_daily_plan`审计插入添加仅合成故障触发器，恢复返回409／HISTORY_REQUEST_CONFLICT，预期503／LOCAL_STORAGE_ERROR；当前仍v2、恢复0行、正文2行，原子回滚有效但错误分类不正确。证据`h1-preliminary-audit-failure.json`，现场`%TEMP%/kgm-d1a-test-59vsiwvh`保留，源码hash同上。

## 5. H1首轮交回（19:07）

OpenCode首轮交付7项专项、77项相关回归，CLI exit0。服务hash仍为`cc63a090…929bc`，R01／R02／R03独立复现仍适用；R04／R05源码缺口及R06上述必要新增场景覆盖不足一并交回。结论：**H1首轮审核不通过，H2未派发。**

修复仍由原会话及指定模型执行，日志`opencode-h1-r02.jsonl`。要求修复R01–R05并补R06针对性测试，记录首次语法错误和真实fixture数据根；不改普通save／D2历史读／AI生命周期，不覆盖Codex核查记录。恢复原子回滚已观察到有效的部分事实保留，不能据此忽略错误分类或缺失测试。

### 5.1 回修预审与R07

R02轮修复源码已核对R01–R05：所有回执分支检查归属；非请求唯一键故障归存储错误；当前指针及本页校验／畸形JSON映射补齐；两份快照摘要含baseline候选身份；历史专用格式门槛不改变D2旧读取。仍待交付后独立测试再关闭。

追加R07：当前指针v2但隔离故障库残留v5时，预览v5返回200并可恢复成v3；后续正常追加到v5将与孤立行冲突。正常API不会产生该状态，但本片不应把它当作合法历史。证据`h1-future-content-probe.json`，源码SHA256 `3ad95129361a854217d2b9d601a43a528e89559e31a0b9485a431b8ea3624a24`，现场`%TEMP%/kgm-d1a-test-f7452buf`保留。应在历史读取／预览／提交入口用有界的最新内容指针完整性检查明确拒绝，不能清理、重编号或修复坏库；不扩展成全库扫描。

### 5.2 第二轮独立验证与末轮交回

Codex使用`desktop/.venv-d1/Scripts/python.exe`，`APP_DISABLE_DOTENV=1`及证据根下独立LOCALAPPDATA，执行`python -m unittest -v tests.local.test_d3_history tests.local.test_migrations tests.local.test_d2_schema tests.local.test_daily_plans tests.local.test_d2_w4_api tests.local.test_concurrency`：**93项、55.136秒、exit0、无skip**。日志`h1-independent-r02.log`及独立exit文件。真实测试库由LocalTestCase独立临时fixture建立，LOCALAPPDATA不是业务库目录。

R01–R05在此源码与测试范围关闭；H1仍因R07未通过。19:26向原会话派发末轮`opencode-h1-r03.jsonl`，仅补最新指针完整性边界，并强化R06：相关表回滚前后逐字段一致、真实旧AI数据迁移逐字段一致、确实移除后恢复历史身份、独立runtime冷重启回执。已通过的93项不要求无理由反复全跑，改动后以受影响H1专项为主。

## 6. H1最终核查通过

OpenCode末轮CLI exit0，原会话恢复idle／succeeded。Codex独立运行`python -m unittest -v tests.local.test_d3_history`，**25项、15.698秒、exit0、无skip**；日志`h1-independent-r03.log`。与前一轮93项存在重叠，不相加为118项独立测试。服务SHA256为`6b3defdd01df9fc12b6992fd75b24e55e9d2287b41ad11906133f44488df4dea`，专项测试为`eb47467982c4b69e778e04cc5a41c4632fa0f966efb0532f39623c8f54d0bd64`。

R07在列表／详情／预览及新恢复的事务前后均作同计划最新内容指针检查；回执优先和归属检查仍保留。R06补强了逐字段回滚、旧数据迁移、真实移除后恢复历史身份和独立runtime冷重启。独立只读源码复核未发现剩余阻塞，**R01–R07在上述H1限定范围关闭**。H1通过不等于H2界面、冻结包或教师产品验收通过。

随后按已授权执行顺序派发H2，日志`opencode-h2-r01.jsonl`，仍用原会话及指定模型。额外要求真实源码WebView2窄范围合成验证、可视截图、恢复后冷重启及Word基准回归；新前端构建用独立输出目录，禁止重建冻结包绕过4551。用户本轮预计采用Certum仅更新后续签名方向，未授权采购或实际签名。

H2实施期间用户进一步明确“目前不安排签名，请继续其余内容”。据此取消拟议的下一步签名准备安排；§3价格研究保留为参考，不派发任何签名相关工作。当前H2审核／回修、相关提交推送及撰写非签名下一步提示词继续；下一提示词仍须用户审核后才能派发。

## 7. H2首轮预审

OpenCode已落地历史列表、完整只读比较、恢复确认及源码窗口／冷重启／Word验证。Codex查看首轮比较与确认截图，文字两列可读，当前／历史版本与整份恢复提示可辨；该截图检查不替代状态竞争或教师包验收。

- R08（阻塞）：`EditorView.vue`的`editDisabled`未包括`historyRestoreBlocked`。恢复回执成功后弹窗关闭，父层仍等待GET当前计划；此时正文结构按钮可点。模板内游戏删除直接splice，不增加editEpoch，GET返回后可被applyPlan静默还原。须覆盖恢复提交、结果不明及核对当前版本的整个期间，禁用正文及结构操作，并验证延迟GET窗口；保存和离开已有门禁不能替代编辑控件门禁。
- R09（验证链）：新增H2源码窗口driver的step捕获失败后继续依赖步骤，顶层verifier在第一阶段失败但已有结果版本时仍可冷重启和导出。与本轮遇失败停止对应链的规则不符；须先记录失败、保留合成现场，再停止下游，不用后续成功遮盖首次失败。首轮成功证据仍可保留，不能据此声称失败停止分支已覆盖。

以上待首轮交付后核对并统一交回原OpenCode，H2尚未通过。

R08内联SFC复现（不新增／修改测试文件）exit0：延迟恢复后的GET时`historySettling=true`、`historyBlocked=true`、`editDisabled=false`；直接删除游戏后games=0、epoch=0；释放GET后games=1、epoch=0、version=4、phase=ready、dirty=false。即删除被静默还原并标为干净。编辑器源码SHA256 `4241fbed17a98a39247e295b6cba3fdf97426a4295d75423634605575a054b9d`，SFC harness为`7f69db3eba71892f4f0effc9ca8aaf829e14d6491785439100b8cb46a17fd7f5`。回修应补setup断言及窄真实窗口DOM disabled检查。

Codex首轮独立类型检查、D1纯逻辑、60项D1组件、94项D2组件、20项新增历史组件、独立目录前端构建均exit0；桌面已有宿主边界12项／2.51秒通过。日志`h2-typecheck-r01.log`、`h2-frontend-r01.log`、`h2-build-r01.log`及`h2-desktop-controls-r01.log`。这些通过项未覆盖R08，不抵消阻塞结论。

首轮CLI输出停在截图读取，之后执行通道返回`Unknown process id 68263`，无exit文件；进程清点未发现该轮run，脱敏会话导出末条assistant为19:57的tool-calls。不能据此前会话outcome=succeeded假称H2正常结束。实现及首轮成功源码窗口报告均保留，未强制结束应用或重复运行旧包。按现有缺陷作不通过处理，随后沿用原会话派发R08／R09回修（`opencode-h2-r02.jsonl`），继续补齐交付报告。

R10（比较缺项）：`HistoryPanel.vue`展开“拆分基准变化”只显示warnings及泛化说明；`history.ts`未读取split_baseline，完整历史及差异行不展示实际基准。相同正文、不同合法基准时可显示0处正文差异，教师无法查看两份基准。须按规格§3.4提供独立可展开的当前／历史基准文本（无基准、空值、真实换行可辨，无内部ID／JSON），并用实际不同基准而非仅注入warning的fixture验证。

R08回修首个真实窗口合成根`%TEMP%/kgm-d3-h2-window-19bfa0fe`在20:17的DOM断言失败：宽选择器包含了非正文AI控件，列表第一个INPUT未禁用；其余所列正文控件均disabled。人为延迟GET未在断言失败时释放，宿主正常关闭因此被前端拒绝，首错已写first.json。Codex拟清理这一个已失败的合成进程，但按完整root／phase／入口核对时目标进程数0，因此没有执行Stop-Process；不能写成由Codex成功结束或已验证正常退出。需修正验证选择器及finally清理，保留此首错现场，正常应用行为与测试脚本故障分别记录。

R09回修预审补充：新增`run_chain`只被测试调用，真实main另走一套编排，不能用该helper的spy替代实际入口停止检查。main应统一检查首相位全部必要事实（包括受控请求数），避免`first_provider_split_once=false`仍启动第二相位。应在实际main／driver路径做故障注入和下游调用计数；删除仅为测试另造的重复流程，或让真实入口使用同一流程。该项与R10待下一次交回。

### 7.1 回执与重启证据边界

历史未决请求目前在HistoryPanel组件内存保存，正常在途／unknown期间阻止关闭和离开；没有跨renderer／进程重启的客户端请求自动找回机制。H1已验证持久回执在独立runtime重启后可按原request_id查询，H2源码窗口验证的是成功恢复后冷重启读回当前内容。两者不能合写为“前端结果不明请求可跨异常退出自动接续核对”。非正常退出后的完整教师体验仍未验，不把客户端storage作为业务权威，也不为补此表述擅加新的持久层或重放流程。

### 7.2 第二轮交付与末轮交回

第二轮CLI正常exit0。R08源码复核已闭合：`editDisabled`包括恢复在途／核对状态；三类游戏删除均通过保护函数并更新编辑代次，模板不再直接splice。OpenCode最终合成根`%TEMP%/kgm-d3-h2-window-8e7328d5`两阶段exit0、9项包装检查通过，延迟GET期间28个内容控件中的可编辑控件及3个删除按钮禁用；历史v4恢复为v6后冷重启和Word XML符合预期。第二次夹具失败`...be03dfe7`因全部游戏已被清空而缺少删除按钮，原失败现场保留；修正为保留不同身份的当前游戏后通过。上述仍是实现者自检，最终Codex独立执行待末轮修复后进行。

20:29沿用同一会话／模型派发`opencode-h2-r03.jsonl`：修复R10真实基准展开；R09需真实入口完整门禁与实际调用计数测试，并在DOM断言失败时finally释放延迟GET、恢复fetch，保留首错；修正脚本声称Word应包含raw原文的不准确说明，不改变Word既有导出行为。R08可代码关闭；R09／R10未通过，不因9项孤立helper测试通过提前关闭。

### 7.3 实际JavaScript清理复现

末轮实施中进一步发现R09故障清理缺陷：cleanup先设`__h2ReleaseCalled=true`，而release首句据此返回，挂起GET实际未释放；fallback同样。Codex从`d1_main.py` AST提取真实注入／cleanup JS交已有Node执行，普通及fallback均得到`settled=false,calls=0,released=true,fetchRestored=true`，Node exit0表示复现成功，不是产品通过。证据`h2-r09-cleanup-independent-repro.json`，driver SHA256 `5bdefe5d501aaef18e11be034769a37044dac862962abcaef4d303e582e11cef`。现有FakeDriver仅匹配字符串并制造已释放状态，不能证明实际JS语义。另一个provider计数提前求值问题已在实施中改为首相位返回后读取，最终仍须独立执行确认。R10实际基准逻辑与fixture只读复核通过，剩余教师文案内部字段名应去掉。

### 7.4 历史保存时间

R11（保存时间）：源码窗口截图的20:39本地保存显示为12:39。只读复核确认`base.utc_now`及SQLite时间是naive UTC，历史DTO实际序列化为`2026-10-23T12:39:00`无Z；`historyTimeText`直接`new Date(value)`在Asia/Shanghai视为本地12:39，正确应20:39。已用真实Pydantic响应DTO和本机Node复现，不涉及业务库。需仅在历史展示按既有UTC约定规范无时区时间，保持显式Z／offset语义，覆盖跨日、微秒及非法输入；不修改全局DTO或数据库时间。此项待交回修复，H2仍未提前通过。

## 8. 非签名下一步建议（待用户审核，不派发）

用户最新不安排签名。D3-A源码收口后，建议按既定D3方向进入**D3-B0：一致性快照与跨设备接续的离线工程摸底**。Architecture v2已经确认WebDAV、一致性快照和本地权威，但同步时机、冲突处理及恢复协议尚未细化；本片只交工程证据与待审方案，不提前实现网络功能或教师流程。

拟由原OpenCode负责独立合成验证脚本／测试和结果记录，Codex核查：梳理现有运行锁、连接／WAL、迁移备份、内容／来源／恢复回执、AI状态、业务文件与独立凭据目录；在无真实密钥的临时库验证一致性快照、并发写入、损坏／中断／写失败拒绝、旧／新revision兼容门槛，以及只恢复到新合成根时的逐字段保留。测试只证明本地底座，不能推断WebDAV服务端支持原子MOVE、锁或条件写入。

把备份／接续触发时机、换机重新配置凭据、两端分歧保留双方并由教师选择等写为建议及待确认决定，不自行加入自动覆盖、自动合并或旧AI任务重发。取得工程证据后由Codex收敛协议并交用户决定，再拆实施包。当前不连接WebDAV、不索取账户、不安装工具、不迁移真实库、不恢复签名／冻结包／真实AI或发行；唯一下一提示词须用户审核后再交OpenCode。

## 9. 最终独立核查通过

H2第四轮正常exit0，R09真实driver与Node测试共享同一套注入／清理JS；普通、fallback及cleanup-throws均实际执行挂起请求和finally，验证Promise结束、底层请求仅一次、fetch恢复及原始错误保留。修复中的`//`拼接曾造成JavaScript语法错误，Codex内联探针与OpenCode实际Node测试均捕获，记录保留于`h2-r09-cleanup-independent-fixed.json`及实现结果；后续已改为共享完整JS文本。第五轮仅修R11历史UTC解析及相关测试，正常exit0；R10界面内部字段名已去除。只读最终复核未发现上述问题残留。

| Codex独立检查 | 结果 | 证据 |
| --- | --- | --- |
| H1最终专项 | 25项、15.698秒、exit0，无skip；前轮93项相关回归保持，与25项有重叠 | §6及`h1-independent-r03.log` |
| 类型检查 | exit0 | `h2-typecheck-final.log` |
| 完整前端回归 | D1纯逻辑、60项D1组件、94项D2组件、22项历史组件均通过，exit0 | `h2-frontend-final.log` |
| 宿主及真实JS故障保护 | 15项H2＋12项既有宿主＝27项，9.22秒，exit0，无skip | `h2-desktop-final.log` |
| 独立前端构建 | exit0，1618 modules；沿用Vite大chunk提示，未为本片扩大拆包 | `h2-build-final.log`、`h2-independent-frontend-final/` |
| 真实源码窗口、冷重启、Word XML | 两相位exit0；首相位13项、第二相位5项及外层9项检查均通过 | `h2-independent-window-final.json` |

H1服务／测试hash仍与§6相同；宿主及验证脚本在独立27项之后hash未变，见`h2-desktop-reviewed-hashes.json`及`d3-reviewed-source-hashes-final.json`。最终前端构建来自本次工作树并输出至证据根，未重建冻结包。

最终脱敏会话导出`session-final.json`与开工1184条消息比对：新增490条assistant全部为`opencode-go/deepseek-v4.1-flash#default`，末条finish=stop、会话outcome=succeeded；H1三轮、H2后续四轮均有exit0，H2首轮执行通道中断如§7保留。审计文件`opencode-final-model-audit.json`，不把CLI派发参数单独当作实际模型证据。

独立窗口命令为`desktop/.venv-d1/Scripts/python.exe desktop/verify_d3_h2_window.py --frontend <证据根>/h2-independent-frontend-final --out <证据根>/h2-independent-window-final.json --keep`。最终合成根`%TEMP%/kgm-d3-h2-window-a8962c6b`，本机受控TLS仅1次split，无真实供应商调用。历史v4恢复追加为v6；延迟GET期间28个内容控件中的可编辑控件和3类删除按钮禁用，结构保持。两个真实源码窗口均确认worker退出及服务停止；独立入口也实证provider计数从尚未运行到实际1次后再进入冷重启。

冷重启读回恢复内容、原文、历史身份和来源；新DOCX为14278字节，自动XML检查的红字为`（历史版）四、历史新增`，未含当前版文字，符合保留历史基准的Word规则。原文不应打印在Word中，已通过持久读回验证。Codex另查看独立列表、展开基准和确认截图：本地保存时间为21:06:02／21:06:05，与运行时间一致；真实基准两栏／换行／“无基准”可辨，内部字段名已移除，整份恢复和保留当前版本提示完整。截图及XML不替代人工逐页Word验收。

最终保护清点`protected-final-check.json`：开工414文件、结束414文件，新增／缺失／hash变化均0；两份真实数据库和r03／teacher-talk-r01旧包保持。未读取或复制真实凭据，未构建冻结包、签名、改防护、连接WebDAV或发布。

结论：**H1／H2限定源码工程通过，R01–R11在本报告范围关闭。** H3包运行、教师体验、前端unknown跨异常退出自动找回、Win10／WPS等未验边界保持。当前D2仍为A已采用v6、B未采用、C未发起；本轮不恢复真实AI。开工已审D2改动与本轮H1／H2源码、测试、结果及接续文档按用户授权一起提交推送；不纳入数据库、密钥、日志或构建产物。

已将旧H1／H2提示词的决定与未验事项归入规格及本报告，`docs/tasks/current.md`原位改为D3-B0待审提示词，未另存归档提示词、未派发下一任务。用户最新不安排签名优先，B0只拟离线工程摸底，后续产品协议仍待确认。
