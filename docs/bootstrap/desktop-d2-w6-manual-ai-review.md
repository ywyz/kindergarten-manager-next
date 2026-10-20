# W6 本机合成AI人工入口：Codex核查

更新：2026-10-19。状态：基础独立验证壳M01–M06关闭；H06-R01修复工程复验及候选编辑预览／明确取消关闭候选框的人工复验通过；继续候选采用与后续验收。

## 1. 来源与边界

用户要求继续W6人工验收，仍禁止应用真实AI或发布；最新确认重启后主题／过程正常，并明确无AI导出跳过、AI引入后再导出。既有人工通过结果见[人工记录](desktop-d2-w6-manual-acceptance.md)。为使三类触发、候选编辑采用及后续在途操作可以由用户逐项完成，本轮仅补必要的独立人工验证入口／控制器／打包及测试，不新增产品业务或网络策略。

原完整包`56346c0ac1d874bbf00e947739a40c005f4a2a611b20d6fabf1a7d35a89fafb2`及182文件保持，原人工根`build/desktop-d2/manual-acceptance-20261019-190131/`和运行中的PID36164保留。生产backend、frontend和原宿主不得改动；若确需变更先交回具体证据做设计核查。新包为单独验证壳，不能静默替换原已验包身份。

OpenCode为唯一实现、测试及构建写入者，复用原会话`ses_ead8af71dffeJphI1NOWg4jZgI`，指定`opencode-go/deepseek-v4.1-flash`；Codex只写规格／核查文档、执行相关验证，不另起实现者／子代理。不安装升级、不真实AI／WebDAV／远程更改／发布／commit／push。

## 2. 已读入口与必要性

按codebase-memory技能尝试list_projects及check_index_coverage，均返回Transport closed；无有效图谱generation或覆盖结论。已直接读取`d1_main.py`的专用phase／参数守卫、build_runtime、run_selftest和run_interactive，以及W6驱动、`build_d2.py`和`w3_tls.py`；仅对这些实际源码作判断。

普通交互启动不接受synthetic-provider注入；现有专用selftest相位会由driver自动操作并destroy窗口，且有自动自检watchdog。不能通过放宽普通入口、挂机自动自检或改写用户结果来替代人工体验。独立验证入口可复用既有构建运行时、执行器、前端和关闭协调，提供专用合成参数、手动窗口及本机TLS控制器；保持既有业务源码不变。

## 3. 开工证据及核查门槛

独立证据根`%TEMP%/kgm-d2-w6-manual-ai-codex-20261019-194019`：446个可见文件hash、原包182文件hash及Git状态已保存；CLI日志`opencode-manual-ai-run.jsonl`／stderr／实际exit将分别保留。正式启动前仍须核对实际模型元数据，不能只依据命令行参数。

- 新入口在任何LocalRuntime构造／prepare前检查显式新session根／标记、data containment及必需provider／测试CA；拒绝默认教师根、原人工根和非loopback解析，普通启动网络边界保持。
- 冻结spawn在GUI／参数副作用前分流；真实执行器、TLS证书校验、Job、正常关窗／worker退出继续复用，不允许以未确认退出放行运行锁。
- 控制器仅受控loopback、仅合成响应；日志不记录Authorization或密钥。正式人工模式不自动发起、采用、保存或导出；自动smoke使用另外的合成根，不能自动消费正式人工会话。
- 当前活动SQLite仅只读一致性backup克隆到新根，独立凭据及dotenv禁用；不直接文件复制活动库或迁移原根。
- 原包及生产源码／前端／模板／迁移hash不变，新包生产代码与当前及原包严格同源；新入口身份另记。自测与独立复核、合成协议验证与真实AI质量、工程与用户确认分别记录。
- 通过前不启动正式人工会话，不将实现者自动自测记成用户验收；先完成有限smoke、守卫反例、实际整包TLS／spawn／Job／三类候选及退出证据，再交用户操作。

## 4. 实施初稿预审与交回（尚未关闭）

- M01：新增入口finally空置，异常启动／GUI路径缺收口；worker未确认时丢runtime所有权并按None谎报已释放锁；service.stop异常吞掉、置None后当服务已停。交回按实际ServiceRun.alive及worker结果、保留所有权和准确报告修复。
- M02：新增入口从`__file__.parents[1]`推原人工根，冻结后变成包路径，原根保护失效；入口与控制器需统一显式新session／data／source及独立LOCALAPPDATA检查，源码和冻结都有效。默认数据路径已直接核对`app/local/sqlite.py`。
- M03：初稿同源主动移除导入的d1_main，遗漏核心宿主；交回保留该生产模块并从真实CArchive比较新入口，不能以另行import副本代替。
- M04：控制器先创建目录／backup／构造Runtime，坏根可能在入口守卫前写入；SQLite URI手拼遇特殊字符有歧义；backup完整性只记录不阻断。交回零写入前守卫、新源目标不重叠、统一只读URI和完整性断言。
- M05：smoke子进程无限wait、异常关窗可挂；provider hold线程不理stop；异常／Popen失败路径需记录并收口。交回限定smoke边界，human无自动超时，退出未确认不得写干净。
- M06：固定Temp指纹文件可复用旧清单，模块集不固定；旧包只比文件数和EXE，漏其他181文件。交回独立证据根、全部旧归档生产模块／真实新入口、完整182文件manifest对比及打包路径保护。

这些为新增验证壳／控制器的中途源码问题，不代表原生产包或用户已验事项失效；均通过同一OpenCode会话steer交回。最终是否关闭需稳定源码与独立执行证据，不以实现者声明替代。

测试补口已交回：human无自动操作须执行fake webview／service／runtime并核对实际调用，不能只搜源码字符串；清理失败和worker未确认须有行为反例；坏控制器根要证明零写入／零Runtime；密钥日志测试须真正发送Authorization哨兵；hold中stop要及时释放；中文／空格／#／%路径及源仍打开、有已提交WAL时的一致性克隆须实际覆盖。全部限临时根及spies，不对教师根试错。

19:48独立前缀检查`original-artifacts-prefix-check.json`：开工446文件无既有改动或丢失，原包182文件逐项相同，原人工计划仍v3／既定主题和过程，AI配置及任务仍0。最终交付仍需再次核对，不以此前缀替代最终稳定性。

## 5. 稳定交付及独立执行

OpenCode实际CLI退出0，sanitized会话导出及`model-audit.json`核对本次81条assistant元数据全部为`opencode-go/deepseek-v4.1-flash`、variant default；会话outcome succeeded。实现者结果另见[实现与自测](desktop-d2-w6-manual-ai-result.md)，下面仅列Codex独立结果。

独立证据根仍为`%TEMP%/kgm-d2-w6-manual-ai-codex-20261019-194019`，不混用OpenCode自测根。新增4份源码的完整hash在`independent-source-before.json`，执行后`independent-source-after.json`零差异；开工446个既有文件零修改／零丢失，原包182文件逐项不变。以下检查均为实际exit0：

| 独立检查 | 结果／证据 |
| --- | --- |
| 全量桌面pytest | 196 passed，9.89秒；2条既有第三方弃用警告。`independent-desktop-tests.log`及exit文件；隔离LOCALAPPDATA、dotenv禁用、清除KGM环境 |
| 真实新包归档分析 | 55个项目模块及CArchive实际新入口与当前源码严格一致，仅忽略co_filename；旧包全部54个模块零缺失／零差异，旧真正d1_main入口与新导入d1_main一致。`independent-archive-analysis.json` |
| 新包资源／旧包核对 | `independent-fingerprint.json`全部16项true：前端、模板、迁移、alembic逐文件一致，原包182文件完整清单保持`84fbb22f…` |
| 源码真实窗口smoke | `independent-source-smoke.json`：3类TLS请求各1次、3个成功候选；entry exit0、worker确认退出、服务停止、运行锁释放。未采用或导出 |
| 仓外完整新包smoke | 复制全部182文件到证据根`仓外 中文 %#/KGNext-D2ManualAI/`，系统PATH、无源码前端覆盖；`independent-package-smoke.json`同样三类请求／候选及退出清理全部通过。EXE SHA-256 `18915b7b7da778a7d467ce03fef08fb89e45b878854f1f714cc126bc1fdc9b75`，15,061,746字节 |
| 原人工根保留 | `independent-final-facts.json`：原计划仍v3、主题和过程全文一致、原AI任务0、配置未建立；原PID36164及启动时间保持。两个smoke供应商端口独立连接探针均已关闭 |

源码行为审阅与28项新增反例测试覆盖：human无driver／func／watchdog，异常启动及GUI清理、服务仍在或worker未确认时不释放锁、坏根零写入、只读backup及特殊字符URI、实际HTTP头哨兵不写日志、hold可及时被stop释放。M01–M06均已按上述具体实现和独立执行关闭。`provider.closed()`表示本机监听已关闭，未以该布尔值独自证明线程退出；另有退出后端口探针。原生产代码未改，既有477项backend及前端工程证据继续按原冻结范围引用，本次不重复运行。

## 6. 结论及交接边界

新增4文件仅作为本机合成人工验收壳／控制器／构建／测试，限定工程通过，可以在另一个全新一致性克隆根启动human窗口。新包身份与原`56346c0a…`包分开记录。正式窗口不自动填写、触发、采用或导出；自动smoke根不继续作为人工根。

三类教师触发、候选编辑采用、在途离开／关闭、跨期限真实睡眠和AI采用后Word仍须人工操作及确认；本报告不将其写成通过。受控TLS仅验证协议与任务／候选状态，不证明实际AI质量或G17真实供应商兼容；无真实AI、WebDAV、远程修改、发布、commit或push。

## 7. H06-R01：人工发现候选编辑锁死（修复工程通过，人工待复验）

用户截图及Codex实际UI确认：候选编辑后底部预览／取消禁用，采用因无有效比较亦禁用。组件`blocking`包含dirty，是离开保护；同时用于两个操作按钮disabled造成自锁。EditorView给候选的disabled仅locked或frozen，未把candidateDraftActive回传为disabled；当前源码证据指向CandidatePreview的条件误用，尚不归因到后台或供应商。产品已确认允许预览修改和明确取消，不需要新增需求。

此前M01–M06与新增验证壳限定工程结论保持；本项是人工发现的生产前端缺陷，不能因自动测试通过而关闭。codebase-memory两项查询仍Transport closed，仅以直接阅读为证据。原OpenCode会话、Go DeepSeek V4.1 Flash定点修复，所有实际按钮、dirty离开保护、精确比较token、进行中／pending保护及新完整包须复核。新前端／包另目录，不覆盖原56346c0a…及18915b7b…包或人工现场。证据根`%TEMP%/kgm-d2-w6-h06-r01-codex-20261019-202851`，用户截图副本、452文件开工hash及Git状态已留存；修复自测与Codex独立结果后补，不写成已通过。

### 7.1 定点修复与核查交回

本轮只改1份生产组件`CandidatePreview.vue`：新增`operationBlocked`区分previewing／adopting／pending与dirty；预览、明确取消在dirty时可用；采用仍须有效比较且操作不在进行；取消内部入口也拒绝进行中操作。原`blocking`及dirty关闭／离开保护保持，精确比较token、来源与版本／epoch核对、失联采用查询未改。EditorView、App、backend与原宿主字节均不变。其余4份代码变化是既有前端回归测试及新增人工入口／控制器／构建器；构建与核查支持显式新前端目录，自动DOM模式有限超时，human仍无自动操作／超时。

自测见[OpenCode结果](desktop-d2-w6-h06-r01-result.md)。Codex中途交回并核实：内存renderer按钮选择器曾命中同名dialog，原生driver曾选到正文“过程”、比较选择器缺button限定、关闭可见性／结构断言不严。均已修正，不把这些初稿当通过；早期selector失败已由Codex另存`early-template-selector-failure.log`。有效旧代码红回归为编辑后cancel.disabled=true，与用户反馈一致，保存在`valid-old-code-regression-failed.log`，后续修复并非通过放宽测试断言。

快速8项新增检查使用真实Vue模板＋内存renderer／Element Plus stub，非浏览器DOM；覆盖拆分编辑比较采用、明确取消恢复不写正文、dirty仍拦截关闭、适龄过程编辑、其他活动内容及板块选择、preview／adopt进行中与未知采用保护。原脚本setup检查保留；真实浏览器按钮另由新包验证。

### 7.2 Codex独立稳定复验

OpenCode实际CLI及sanitized导出均exit0；`model-audit.json`核对本轮86条assistant全部为`opencode-go/deepseek-v4.1-flash`、variant default，会话succeeded。实施者已声明停止写入，Codex以下独立执行均exit0，未复用实现者会话根：

| 独立执行 | 结果／证据 |
| --- | --- |
| 前端typecheck及完整test:d1 | 类型检查、原D1纯逻辑、60项D1组件、81项D2组件通过；`independent-typecheck.log`、`independent-frontend-tests.log`及实际exit文件；前后2份前端源码hash不变 |
| 完整桌面pytest | 196 passed，8.62秒、2条既有第三方弃用警告；隔离LOCALAPPDATA及dotenv禁用；`independent-desktop-tests.log`和exit文件 |
| 归档／资源 | `independent-archive.json`：55个项目模块及真正新入口与源码严格同源；旧全部54模块及旧真正入口零缺失／零差异。仓外副本`independent-fingerprint.json`全部16检查true，新前端、模板、迁移及alembic逐文件匹配 |
| 仓外完整新包真实DOM | `independent-dom.json`全部27检查true，entry exit0。实际日期10月20日，新合成计划；只用1次split请求。原生input事件仅改可见候选，正文clean／版本不变；按钮严格enabled并原生click比较采用；回读正文第三行“比较（教师确认）”、baseline第三行“比较”；明确取消不增加版本。候选X及真实宿主关闭均被dirty拦截，编辑保留、closeState结构有效且locked严格false；取消后真实退出0、worker退出、服务停止、运行锁释放；供应商端口另探针确认关闭 |
| 新包三类任务smoke | `independent-smoke.json`：split／adapt／other各1请求、各有成功候选，退出／worker／服务清理通过；独立根，不采用或导出 |
| 源码／旧产物／原数据 | `independent-final-facts.json`：冻结后452文件零变化；开工仅5份授权代码及3份Codex文档变化。旧前端、56346c0a…包与18915b7b…包逐文件零变化。原人工持久计划仍v4、完整原文／既有主题和过程、基准null、成功拆分任务仍1；未消费现场未保存输入 |

新完整包`build/desktop-d2-manual-ai-h06-r01/package/KGNext-D2ManualAI/`，182文件，EXE SHA-256 `209dedcd5dfc4c8995478fc36146ae744ee653570ea318a54b25817b73a56c1b`，15,066,101字节，完整清单SHA-256 `44e58c4e0f1635d1d69e530f32bd6e2a4c4be4c301b1393c9c8f8b5a3add6260`。实际独立复验使用证据根`仓外 中文 %#/KGNext-D2ManualAI/`全部182文件副本，副本与构建目录逐文件相同、系统PATH、无源码前端覆盖。新前端在`build/desktop-d2-manual-ai-h06-r01/frontend/`，未重建旧资源。

### 7.3 当前结论

H06-R01按钮锁死及取消退出死路的修复工程复验通过，可换到新完整人工包继续；用户人工复验尚未取得，H06整体未通过。旧包历史工程记录不扩展为此项人工通过；不重复已通过的Word／无AI睡眠基础／冷重启。当前只使用本机TLS合成响应，无真实AI、WebDAV、发布、安装升级、commit或push。

20:56:52 +08:00已启动新human会话，PID37880，controller session50152；根`build/desktop-d2/manual-ai-h06-r01-human-20261019-205651/`，从原人工v4作只读一致性backup、独立凭据／LOCALAPPDATA，dotenv禁用。`ready.json`／`fixed-human-initial-facts.json`核对同一计划v4、原文存在、主题／过程保持、基准null；同一已成功split任务和同一候选各1，新的合成配置v2，供应商新请求0。Codex以computer-use选定新包实际路径的窗口，打开10月19日并查看原候选，仅导航／读取，未编辑、比较、采用、保存或生成。当前交接人工重做第三行编辑→预览比较→明确取消能关闭候选框，暂不采用；原PID19256失败现场保留。用户结果仍待回报。

后续用户明确反馈“预览、取消均正常”。Codex独立页面与只读DB核对取消后v4已同步、原文及正文保持、基准null、原候选三行未变、新会话供应商请求0，证据`human-preview-cancel-confirmed-facts.json`保存在新human根。H06-R01编辑后按钮及明确取消关闭候选框人工复验通过；整窗正常退出仍须后续人工确认。接续同一候选编辑比较后采用，不重新调用AI；H06／G18及采用后导出未因此整体通过。

### 7.4 输入变化提示的窗口核对及重新交接

用户继续采用时报告“生成输入已变化”。codebase-memory的list_projects／check_index_coverage仍Transport closed，按技能直接核对ai_candidates.candidate_applicability和ai_inputs.project_input／dependency_matches：拆分依赖是已保存原文及候选请求的目标年级，候选编辑文本及全局AI配置版本不属于该指纹。未改代码或放宽守卫。

只读证据`%TEMP%/kgm-d2-w6-source-changed-inspection-20261019.json`、实际窗口路径及控制器报告一致：

- 修复包PID37880于21:18正常exit0，worker确认退出／服务停止／锁释放均为true；根205651仍v4完整原文，原文＋middle严格匹配候选输入。
- 当时可见的旧包PID19256来自旧194019证据副本；旧human根200255已于21:20:34保存为v5、原文为空，候选输入仍是v4完整原文，因此source_changed保护正确。不能据此推断谁或什么操作清空了原文，也不能把旧窗口状态归为新包故障。
- 同名窗口造成交接混淆，Codex已向用户说明。确认旧正文v5已同步、候选只读且无未采用编辑后，Codex正常点击宿主关闭；旧controller75749实际exit0、报告ok，未强制终止或改写数据。旧根和日志保留。

21:25:27重新从完整修复包根205651的v4作只读一致性backup，启动唯一human窗口PID33876／controller35717；新根`build/desktop-d2/manual-ai-h06-r01-human-20261019-212522/`。`ready.json`记录包182文件、EXE209dedcd…及全清单44e58c4e…保持；新配置v3仅合成配置准备。`reopened-human-initial-facts.json`核对同一计划v4、完整原文及既有正文、基准null，同一成功任务／候选各1，业务依赖hash为f053c52d…且与当前原文＋middle严格相同、新provider请求0。实际UI打开原候选，字段可编辑、预览／取消可用，无source_changed提示；Codex仅导航及最大化，未修改／比较／采用／保存／生成。等待用户人工采用，不把可继续操作写成已采用通过。重新启动报告位置为独立H06证据根`reopened-human-result.json`，human仍无自动超时或动作。

### 7.5 拆分采用人工确认

用户明确“采用成功，v5已同步”。当前human根`human-split-adopted-v5-facts.json`／`human-split-adopted-v5-checks.json`的8项只读核对全部true：内容版本仅v4→v5，六字段与预期一致、过程末行含教师确认；基准仍为未编辑模型过程，原文不变，同一成功任务／候选各1，新provider请求0。实际置前的修复包窗口树另存`human-split-adopted-v5-ui.txt`，确认正文及v5已同步、候选框已关闭。用户已确认的预览／取消与本次采用子项通过，H06-R01编辑按钮锁死路径的人工复验已取得；完整宿主人工退出、其他候选及整体验收边界保持未验。下一步只交接中班过程适龄调整的单次合成触发／候选打开，不自动替用户执行或记为通过。

### 7.6 修复包正常退出及同根冷启动

后续适龄、其他活动全选／部分采用、空配置说明与v11手工保存的人工及持久核对详见[唯一人工记录](desktop-d2-w6-manual-acceptance.md)。用户明确关闭完整修复包窗口，原PID33876消失、controller35717／entry均exit0，原entry-exit的worker／服务／锁三项清理均true。H06-R01修复包的预览／明确取消／采用及完整无在途窗口正常退出人工复验已取得，不扩展为在途／dirty关闭所有交错或H06整体通过。

22:26:10以相同209dedcd…EXE及相同212522/data／localappdata直接冷启动，新PID37308／session67132；不走克隆／prepare_session／AI配置准备。原退出报告和日志已按`logs/cold-restart-v11-20261019-222610.previous-*`保留，重启独立launch／运行进程与日志同前缀。`human-cold-restart-v11-readback.json`10项通过，实际窗口显示v11已同步及四行、原班级档案、正文／原文／基准／内容ID及版本链／任务／配置均保持，无新请求。原受控供应商监听已停，本阶段仅读回／导出；未改代码或验证脚本。当前用户冷启动画面及重启后Word逐页尚待确认，结论边界与人工记录一致。
