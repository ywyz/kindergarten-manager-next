# ead1e99回归修复与恢复片整合核查

日期：2026-11-04。**最终限定源码工程通过**：Codex独立完整local1229、desktop628，均0失败／0error／0skip；前端及观察源码窗口通过，549个非文档文件验证前后相同。下一步返回原Windows11测试机按新身份复核完整local与恢复增量。首轮失败、负对照及未验保持；唯一执行入口为[当前任务](../tasks/current.md)。

## 1. 授权及接收身份

用户本轮要求接收ead1e99后修复，以原生OpenCode／Command Go的DeepSeek V4.1 Flash max实施，Codex独立审核，判断是否交回测试机，最后提交推送。开工工作区干净，当前分支`codex/desktop-v2-foundation`；本机HEAD为`cb4e7ed9bb76cacee8f37dc4bd9fb9c063e6f222`（tree `87def6e2ecb8b3c0fa77870dc613829cd892017a`），fetch后远端为`ead1e99850e4cd4d96f9f53314fbb6a9a750c96c`（tree `a619a73bd98f03b8a5045a9a72a6922cf119939d`），共同父为61ef9f9。按入口的不能快进停止条款报告后，用户明确允许普通merge保留两边成果。

原OpenCode A执行`merge --no-ff --no-commit`，仅`docs/tasks/current.md`冲突，由Codex整合；测试机两份脱敏文档和本机恢复源码均保留。最终交付以实际双父提交和远端为准，不通过改写历史拼接身份。测试机旧报告§6中的“恢复交互待核定”属于其旧源码身份；本机恢复片用户确认及[规格](../specs/desktop-renderer-recovery.md)仍有效，二者不互相覆盖。

## 2. 原生责任与环境

复用本机已核存在且idle的原OpenCode A `ses_ead8af71dffeJphI1NOWg4jZgI`及B `ses_e72ecd5f9ffeYJaLRNypsdu5Pi`，固定build／`opencode-go/deepseek-v4.1-flash#max`；原Command Go C `8cf528de-8773-4a06-9cc5-31e96fab515f`固定`deepseek/deepseek-v4.1-flash`／max。不fork或派子代理。A负责桌面入口、观察导出异常收尾及桌面旧预期；B负责三份后端旧预期／清理测试及静态reparse夹具；Codex独占正式文档、独立验证和最终审核。

C先只读诊断AI整套失败，再获三个后端测试的互斥写权，但`edit_file`被CLI权限拒绝，自然exit0只表示任务结束。实际源码改动0、测试未执行；未启用更宽权限或以shell绕过。确认其停写后，将三文件写权转B，C仅继续只读复核。不把拒绝当作永久系统设置变更。

沿用现有`desktop/.venv-d1/Scripts/python.exe`，实际CPython3.14.10／AMD64／标准GIL；pyvenv.cfg中的3.14.7是既有静态旧文本，不改环境或依赖。新短合成TEMP／TMP，pytest basetemp置其内，APP_DISABLE_DOTENV、SQLAlchemy纯Python、禁pyc和Python loopback-only守卫。守卫不外推原生WebView／OS隔离。前端用现有Node24.16.0执行现有锁定依赖，未安装升级。

图谱仅导航：开工generation `2026-11-04T05:46:20Z`，相关8路径及后续静态测试coverage为metadata_changed；已回读实际源码。图谱自动刷新不作为源码已验，也未手动重建索引。

## 3. 定向独立基线

在AI执行器与相关测试未改动时，Codex独立执行完整`WeeklyAIExecutorTests`类及观察视觉deadline节点，**23 passed，exit0，93.45秒**，JUnit一致。测试机原15项失败仍保留；此结果只表明本机这一新进程定向范围未复现，不能关闭整套／前序污染或测试机环境问题。

C提出spawn／ready时限、子进程收尾及导入上下文等假设，未作为已证根因。Codex未接受“父进程后来删除环境变量会改变已spawn子进程环境”的解释。未增加sleep、重试、skip或改deadline来取得该基线。

前端14份脚本、typecheck及D1构建均exit0，输出位于本轮独立私有证据根；不改前端源码，不生成冻结包。最终全套和源码窗口结论待后续记录。

## 4. 已核修内容与独立反例

A五文件仅涉及selftest绑定、观察导出异常收尾、manifest和U2旧预期；B四文件涉及三个后端旧预期／清理测试及一个Windows reparse夹具。生产变更仅`desktop/d1_main.py`和`desktop/d1_host_api.py`；既有renderer recovery、迁移、依赖、API供应商和保存ack合同未改。

- 后端当前runtime revision四处旧断言改为0008；明确历史0005源／0006目标、旧行摘要／FK及保护包断言保留。四个手建runtime在prepare前登记dispose清理，断言失败也释放根锁。
- 周AI采用表补入精确表集合；注册集合明确日3＋观察2＋周6，而daily可执行集合仍3。桌面manifest保留7条daily历史revision及2条观察的固定hash，新增6条已批准weekly固定hash，总15，逐条删行／改hash仍拒绝。
- U2仅当前HEAD目标改0008，旧0004源及历史迁移断言保持。历史失败节点名`test_real_0004_to_0006...`仍保留以便比较，但该U2用例实际检验0004到当前HEAD，不把名称当作0006目标证据。
- `run_selftest`创建窗口后绑定同一host，再安装关闭处理，与普通入口一致；不据此修改产品取消行为。
- 观察导出attempt创建后的非预期异常补终态：download／dialog在原子文件写入前为failed；write开始后不确定则unknown／indeterminate。保留同一attempt及显式receipt_pending对账，不自动再下载、建attempt或重发。正常取消和已保存结果语义保持。
- generic reparse测试在Windows创建真实NTFS junction，核临时边界、普通父目录、reparse属性／tag和resolve目标，继续验证两种validator拒绝raw parent／reparse traversal／受保护reparse根及不创建泄漏文件。没有mock、skip、提权或改变生产保护；Windows符号链接特权分支仍未验，junction通过不冒称symlink通过。

实施者保留manifest旧9行失败、U2三个旧target失败及观察异常两个新增反例的首失败。Codex另独立导出cb4e7ed原host字节（SHA256 `39db17b3dd1f4a2d8eb8e3845587749763d694e45c9b79c1e0316130e69e16e0`），在新私有目录加载旧模块执行相同两个异常用例，实际**2 failed／exit1**：缺attempt_id／无终态，以及写入异常被误报failed。未覆盖首失败，未改仓库源码作为负对照。

## 5. 本机独立验证与审阅

A／B均自然exit0停写后，Codex冻结548个已跟踪非Markdown文件；独立七份受影响测试**116 passed／exit0／65.19秒**，JUnit一致。完整周执行器类＋视觉deadline的23项基线见§3；两组不可合称一轮完整local。

观察源码窗口使用本轮新D1前端和新空合成数据／凭据根，验证器exit0，宿主exit0，17个report检查全true：创建编辑、历史恢复、冲突离开保存、单份导出、取消导出、宿主／页面busy清除、多份混合分页导出（16份标题和顺序、照片、不同园所）及正常执行器／服务停止。只验证生成的DOCX内容结构及页面流程，未调用Office重新做旧43页页检，不外推Word视觉结论。

Codex回读全部九文件diff及相关异常／回执实现，`diff --check`通过。C只读复核无阻塞项；其指出新增两例未逐项计数attempt／content／result调用，故不把它们单独称作所有零重发路径的测试证明，零重发结构同时以源码审核为据。U2历史节点命名和Windows symlink特权边界按§4保留，没有以加sleep／重试／skip消除失败。

原生metadata独立审核通过：本轮A40／B24条assistant均为原session、build、DeepSeek V4.1 Flash max；C28次model_request_end均为Flash max，包含被拒阶段。六个阶段均自然CLI0、无parent／fork／子代理／换模证据；同模型压缩允许且核其metadata，不以CLI0替代源码交付。最终Git阶段另按实际门禁和回执核验。

Codex首次完整local在本轮548文件冻结下复现周执行器失败：观察视觉deadline在完整前序上下文中通过，但周执行器部分成功、截断响应、发送前重试及其它终态节点在约80%位置再次失败，任务表现为claimed／retry_wait，未见dispatch标记及假供应商trace。该轮保持源码冻结继续至结束，最终数字见§5.1；不将23项定向通过作为关闭证据。

已再次交原A只读定位执行器／spawn／IPC／Job，C互斥只读核前序测试／collection全局污染。该阶段禁止修改已冻结源码或干预首轮进程；新增私有诊断另根保留，先取得具体异常／前序最小反例再核写权，不加sleep／超时／重试／skip掩盖。当时桌面完整回归暂缓，最终执行结果见§5.5。

### 5.1 首次完整local失败（冻结源码，不覆盖）

`R-backend-full`：1228项收集，**1214 passed／14 failed／0 error／0 skipped／91 warnings，exit1，2483.69秒**。JUnit与实际退出一致；前后548个非Markdown已跟踪文件SHA完全相同。观察视觉deadline已在完整上下文通过，原5项后端旧预期及清理错误未复发；剩余14个节点与测试机§6.6周执行器清单对应。首例期望终态而实际retry_wait，发送前trace为空；不将其解释为真实供应商失败或产品并发采用缺陷。

Codex另外的新进程判别：全部1228项collection后只执行首个失败节点，**1 passed／1227 deselected，7.82秒**；同文件Service／Barrier前序加该节点**25 passed，24.03秒**；再加周采用／API／迁移前序**57 passed，56.83秒**。这些是缩小执行顺序影响的证据，不能替代整套通过。首轮没有注入私有observer或改时限。

原A继续只读定位；C未找到已证的import／全局污染点，资源所有权仅是假设。原B仅可编写独立私有observer，Codex先审核再用于后续有界诊断，不加入产品或修改首轮现场。该首轮不能收口，最终新source结论见§5.5。

### 5.2 有界执行顺序对照与会话收束

新增独立对照均保留独立日志/XML，不能相加冒称完整local：D2执行器前序＋首失败节点22通过；视觉合同前序＋该节点13通过；恢复core＋该节点28通过；周合同／输入＋该节点48通过；周AI备份＋该节点17通过；从观察API到周service之前的20个前序文件＋该节点314通过（431.68秒）；整个观察AI文件＋该节点43通过。收集全部后单跑和同文件／近周前序通过见§5.1。故单一已跑前序与collection都尚不足以解释首轮14失败，组合及更早前序继续核。

B仅在私有目录编写observer。Codex首次源码审阅发现`event(name, **{name:...})`参数冲突会改变被测行为，执行前已拒绝并要求修正，原版hash／私有回修记录保留；另修base executable字段和加入异常errno／winerror。审核后同一成功节点实际1通过，记录两次process start／Job／bootstrap及两次成功终态。插件不写入仓库或用于完整验收，不输出请求体／secret，不改deadline、sleep、重试或skip。

原A只读诊断取得近周采用／API＋完整Executor53通过及直接worker spawn三个成功样本（ready约1.6–2.6秒），仍未定位具体异常。其长上下文持续泛查后，Codex按用户明确允许决定是否复用原对话，使用OpenCode公开OpenAPI的`session.interrupt`精确中断该只读阶段，实际`interrupted=true`、该阶段CLI exit1；不是自然完成或源码实施失败。原阶段及私有证据不删。此前误试标准abort路径404和不存在operation的拒绝也保留，随后以实际schema核路径；未全局kill、动系统保护或其它会话。

继续使用新原生OpenCode X `ses_e592476ebffefwUSsNFo7aNSDF`／build／Flash max做短上下文限定诊断，明确为新会话、无fork，不冒称原A。X负责更早D2环境／凭据／runtime／schema前序，Codex负责snapshot前序，均沿新短合成根；当时X未获跟踪源码写权，后续须先核互斥责任，实施见§5.3–5.4。原A仍保留最终Git责任，正式文档和最终审阅由Codex独占。

### 5.3 夹具隔离候选与取消首失败

X限定D2前序组合共398项，397通过／1失败；目标周partial通过，唯一失败为`FreezeAndDrainTests::test_cancel_blocks_send`在DB已claimed后立即假定`begin_cancel`成功。该状态仍可能处于claim到active赋值的合法交接，因此本例暴露了纯计时夹具假设，不由此改生产取消语义。该失败保持独立身份；首完整local中此节点通过。X诊断自然exit0仅表示诊断结束，不把其1失败写成全组通过。

更多对照：D2 runtime／credential／schema前序82通过；snapshot全文件＋目标40通过；其余早期12文件＋目标156通过；全1228 collection仅执行Executor前三个无worker节点及首partial为4通过。所有有界通过仍不等同完整local。

Codex确认周fake worker的反序列化目标为整个service测试模块，加载不必要数据库／API测试依赖；原五个纯协议函数没有这类业务依赖。独立新进程导入原字节模块测得**1.452424秒，863个模块，其中150个SQLAlchemy、38个FastAPI模块**。该测量证明不必要导入成本，尚不是首轮10秒内的完整子进程时序，不把累积负载假设写成已证根因。

据此仅授权X三文件test-only候选：原样移五个纯协议函数到只用标准库的worker模块，父测试引用该入口；独立进程import guard禁止DB／API／测试框架／父测试模块，防止回流。取消夹具使用既有ready事件在mark前双向同步，实际取消提交后才放行，finally释放并确认idle／退出，保持cancelled、候选0和无dispatch标记。不改真实产品worker、执行器、时限、重试或sleep，不串行化并发采用。新source身份、AST一致性、相关定向及完整local／desktop在该候选阶段仍须另验，最终见§5.5。

### 5.4 候选源码审阅与独立定向结果

X自然exit0停写后，Codex以原字节副本逐个AST比较五个迁移函数，全部完全相同；同样独立新进程测得轻量模块**0.005966秒、82个模块、SQLAlchemy 0／FastAPI 0**。旧目标模块在禁重依赖私有负对照中实际exit1，明确被SQLAlchemy导入拒绝；新fresh-process guard通过。此结果验证import隔离，不能单独替代原14节点的完整上下文结果。

取消夹具首版将1.5秒睡眠替换为状态轮询，Codex审核要求去掉新增sleep，最终改为既有`_idle`事件等待；同时补恰好1个attempt、无dispatch标记及真正idle后stop确认退出。READY双向gate与finally释放保留，没有以stop制造取消结论。X最终单节点1通过，Codex回读最终diff并在549文件新freeze后独立运行两完整受影响文件，**68 passed／exit0／77.19秒**，JUnit一致；没有加载observer。

C只读复核worker模块及service测试diff无阻塞项；指出import guard只证导入隔离，完整分支／原14失败仍需独立全套，Codex采纳该边界。正式生产文件仍仅本轮原九文件片中的host／selftest两处；没有修改生产执行器、worker、预算、重试、依赖或迁移。最终取消夹具无新增sleep；并发采用测试未改成串行。

本次实现及验证metadata核至A／B／C／X，原生Flash max、准确session／parent、无fork／子代理／换模均通过；原A只读诊断的主动中断exit1明确单列，所有其它已结束阶段自然CLI0。C写权限拒绝阶段仍保留为未交付实现，不能由exit0冒称写入。

第二次完整local在549文件freeze下执行（1229收集，新增1项隔离guard），没有注入任何私有observer；最终结果见§5.5。前端、观察源码窗口和第一片116项已在最终生产文件相同SHA下通过，后续仅这三个测试夹具文件变化，没有无故重跑无关教师或Word范围。

### 5.5 最终独立源码工程结论

| 范围 | 实际结果 | 证据边界 |
| --- | --- | --- |
| 完整backend local | **1229 passed／0 failed／0 error／0 skipped，exit0，1985.03秒** | JUnit与退出一致，91条既有弃用warning保留；完整前序下视觉deadline和全部22项周执行器均通过，覆盖原14失败节点。 |
| 完整desktop | **628 passed／0 failed／0 error／0 skipped，exit0，115.38秒** | 8条既有warning保留；关闭／恢复／维护／U2／manifest／观察异常回执及真实junction拒绝断言包含其中。本机本轮没有旧验证包缺失skip，测试机历史skip保持原身份。 |
| 受影响定向 | 旧预期／宿主七文件116通过；最终夹具两文件68通过 | 都是独立进程、独立日志与JUnit，不相加冒称完整全套。 |
| 前端与源码窗口 | 14脚本＋typecheck＋D1构建全部exit0；观察窗口17检查全true，验证器与宿主均exit0 | 生产文件SHA与最终源一致；此后仅三个测试夹具文件变化。不是新冻结包或Word视觉页检。 |
| 源码freeze | **549文件前后SHA完全相同** | 包含新未跟踪worker模块，最终独立结果对应这同一源；原首轮548文件／14失败仍私下保留。 |

Codex已独立回读全部本轮diff、比较五函数AST、核两个负对照及import隔离、核模型metadata和测试进程／XML；限定工程审核通过。修复未扩大教师流程，没有产品AI行为／数据权威／依赖或迁移变化。相同预算和原断言下，轻量worker及取消同步后的完整source通过；未取得首轮每个子进程的完整内部时序，不能把负载假设或原自然白屏／Word/r外因写成已证根因。

本轮真实供应商AI调用0，未启动冻结候选／冻结helper、Office注册、WebDAV、签名、安装更新或发行。Python守卫在各主／子进程加载；观察源码窗口启动检查更新的1次非loopback解析被拒保留，不以此声称OS／原生WebView全局隔离。原保护资料及私有首失败不提交。

## 6. 测试机接续决定

本机完整工程验证已通过，**下一步返回原Windows11测试机按新交付身份做限定增量**。理由是原15项整套失败出现于测试机，本机定向通过不能解释其外因；恢复片也尚无本次新交付的目标环境结论。先核拉取后的完整SHA／tree及实际解释器／前端来源，再在新短合成TEMP执行一次目标机完整local，保留首次时序和JUnit；不要只以15个单项通过关闭原整套问题。若复发，按spawn／ready／permit／SEND／结果持久化和子进程退出的实际证据定位，不先增加时限或睡眠。

随后验证手动恢复增量：默认保留、两个选择、保留后再次明确尝试；同根新窗口读回已保存日周稿、确认、历史、照片和任务回执；保存、原生文件／Word导出、维护／更新及AI发送／待落盘／退出未知时拒绝；新旧能力失效、正常保存关闭和独立进程重开。主动故障只用于核明归属的新合成源码窗口／自有Core；不碰已配置AI体验档案。冻结包如何受控触发另核能力，不添加产品调试开关，不用源码结论替代包内结果。

已配置的测试机AI体验档案沿[原配置保留§6.7](desktop-windows11-white-concurrency-review.md#67-后续拉取代码时保留本机ai配置)，同用户原两根显式普通启动，核设置已配置、无新增attempt和正常关闭；无需重新填key或再发付费请求。旧39项教师清单、13份43页Word、IME和跨120秒睡眠不重验。原自然白屏精确触发、Word/r历史差异、Win10／WPS／干净机／其它显示条件／跨用户凭据／长根206等继续保持原未验。

push若自动产生新CI候选，另核本次完整HEAD的可信run／attempt、ZIP与原字节PS1、package-info.source_commit、两个身份文件build_id／revision及source freeze；没有核到新包就只交源码身份。开发机SAC4551不执行受阻冻结EXE／helper；本轮不签名、安装更新、WebDAV、远控或公开发行。

## 7. Git收口与身份边界

本轮用户已明确授权普通merge与审核后提交推送。仅原A按Codex当次18个明确文件（12份源码／测试及6份文档）、Git规范化blob、父提交cb4e7ed9bb76cacee8f37dc4bd9fb9c063e6f222／ead1e99850e4cd4d96f9f53314fbb6a9a750c96c及暂存tree执行；Codex独立核index、实际双parent、提交tree和远端一致。准确新提交以实际分支历史／远端核对为准，不为把自身SHA或tree写入自身文档循环提交。原ead1e99目标失败报告保持其交付字节，不将其覆盖为通过。

不add-all、amend、rebase、force、改main／默认分支／可见性、tag或Release；私有模型原始日志、合成档案／图片／凭据、构建及保护现场不入Git。push自动CI如生成新候选，仍依§6和current另核完整来源及字节；本报告不预先宣布CI制品静态／运行通过。

## 8. 2026-11-05：来源门与受管恢复验证器回修

### 8.1 接收、范围与原生责任

用户明确要求接收`173880de7ac67b8fd847d13281f913f4d282fab3`，仅普通fetch／快进，修两项剩余核验问题并在Codex审核后普通提交推送。本机原分支`codex/desktop-v2-foundation`、HEAD为0e514917、工作树／index干净；远端为指定173880d。实际fetch后确认祖先关系，`merge --ff-only 173880d`成功，接收tree为`674c7ed19735fdde97eef979decb97472c60ce2f`，无新merge／rebase或他方修改覆盖。已读根AGENTS、最新current及[原测试机§7](desktop-windows11-white-concurrency-review.md#7-2026-11-050e51491原测试机增量)。本节接续开发机，不冒用测试机会话或私下副本。

原开发机A `ses_ead8af71dffeJphI1NOWg4jZgI`负责build_e14／verify_e14_package及两份来源测试；B `ses_e72ecd5f9ffeYJaLRNypsdu5Pi`负责受管恢复验证器及新单元测试，精确六文件互斥，均自然停写后独立核查。原Command Go C `8cf528de-8773-4a06-9cc5-31e96fab515f`只读诊断和交叉审阅，未请求写入／扩权／绕过。源码阶段实际assistant／request metadata为A67、B49、C16条，均准确原session、Flash V4.1 max、无parent／fork／子代理／换模，所有阶段自然CLI0；最终Git阶段metadata另随回执核。OpenCode provider为`opencode-go/deepseek-v4.1-flash#max`，Command Go为`deepseek/deepseek-v4.1-flash` effort `max`。

Codex独占正式文档、源码终审、执行复验和Git门禁。codebase-memory Verify查得来源freeze／归档函数；generation为2026-11-05T04:19:34Z，10个证据路径freshness为metadata_changed，已全部回读实际源码，不据图谱作完整性负面结论，不额外重建索引。

### 8.2 两项最小回修与审核

1. 两个生产模块`desktop/renderer_recovery.py`、`desktop/renderer_recovery_native.py`纳入product SOURCE_GROUPS，现有构建前／后同一freeze均覆盖；加入REQUIRED_FREEZE_PATHS、ARCHIVE_REQUIRED_MODULES并明确分类为production。受管`verify_renderer_recovery_window.py`及其新测试只列verification来源；验证器列required freeze，**没有强制打进产品PYZ**。本机实际freeze为289文件（旧285＋四个来源），与全仓非文档550文件freeze不是同一个范围。
2. 受管验证器两处活动host观测改为`_page_lock`内读取当前ticket／bound／page-ready／business-ready／launch／notice等状态，未修改产品`get_bootstrap()`语义。保留真正旧票据提交，accepted必须false且前后全状态一致；新服务port上的只读GET要求旧token401／新token200，取消用旧port拒连替代认证。自有UI Core归属明确后才发送Page.crash／Browser.crash；同根完整fixture、49表／12资源全指纹、旧executor停止、正常关闭及独立进程prepare／完整指纹／dispose均为成功门。

Codex审阅将persist子命令边界、固定副产物覆盖风险及新增60秒等待交原B回修：prepare前须有精确既存kindergarten.db／凭据目录、expected及新输出在数据／凭据外，拒绝raw parent／reparse；主窗口输出目录必须新且空、拒同名副产物。删除新增等待，保留原时限。GuardedHost测试在锁外读字段／event即失败，禁止调用bootstrap，核观测前后无变化。C复审确认主流程阻塞项消除；其进一步限制独立persist输出目录其它文件的建议未新增为规则：该命令只写明确指定的新输出文件，不覆盖或删除相邻文件，主流程固定副产物另由空目录门保护；Codex实际CLI反例及独立冷启动见下。

现有产品bootstrap、恢复协调器、原生提示器、业务、执行器预算／重试、迁移和依赖均未修改。新增源码专用fault选择不是产品调试开关，没有新增sleep、预算、重试或skip，没有削弱旧断言。

### 8.3 Codex独立实际验证

使用现有CPython3.14.10 Windows x64标准GIL及锁定venv，禁dotenv／pyc、SQLAlchemy纯Python、Python loopback守卫；各次短TEMP／TMP独立且basetemp在其内。前端源码相对0e51491未变，复用原已核D1三文件并复核原字节SHA，没有重复无关前端14脚本／构建、完整backend、旧Word／IME清单。

| 范围 | 实际结果与限制 |
| --- | --- |
| 来源／归档及恢复相关四文件 | **119 passed／0 failed／0 error／0 skipped，exit0，6.22秒**。包含两份来源测试及两份现有恢复测试；来源模块／测试规范化后对应最终文件，B后续仅改验证器及其新测试。 |
| 最终受管验证器单元 | **6 passed／0 failed／0 error／0 skipped，exit0，0.68秒**。锁所有权、只读状态、缺根／缺DB、边界、真实junction拒绝及副产物保护。 |
| 受管Page.crash源码窗口 | **exit0，22.97秒**。保留后再次原生关闭再明确重开；旧票据拒绝且状态不变，新port旧401／新200，49表／12资源全指纹、旧executor停止、正常关闭和独立进程完整冷启动均通过。 |
| 受管Browser.crash源码窗口 | **exit0，19.52秒**。独立新根，同上各项通过；两种故障均仅发送给核明归属的自有Core。 |
| 真CLI边界反例 | raw `..`、不存在persist数据根、已有固定副产物三例均**exit2**；没有创建错误档案／凭据根，原副产物SHA保持，未删改未知文件。 |
| 完整指纹负对照 | 在已正常关闭的本轮合成Page根上，只篡改expected combined hash，计数／integrity／FK仍相同，受管冷启动**exit1**且fingerprint_match=false。证明计数通过不会掩盖完整指纹不符。没有复制DPAPI。 |
| 来源门正反例 | 实际289文件product／verification分组正确；两个产品模块各自的缺来源、缺freeze条目、改hash、构建前后变化、真实CArchive/PYZ漏模块／改代码／篡改freeze hash均触发对应拒绝。合成归档测试不是实际新包证据。 |
| 源码稳定 | B最终回修后**550个非Markdown文件前后SHA完全相同**，包含新增测试；119项所测四个关键源码／测试及两份生产恢复模块SHA与最终源相同。 |

Page完整业务／资源combined SHA为`389673642f1663312ccb1c3c28f17e4a542d6fbbab22fbdf38dd0008114c55f8`，Browser为`dc2d3e646dec14e3cbcbedbcb0787ffa48f8c06b530b5e598de506570a15cd41`；各自故障前、后及独立冷启动相同。两根task／execution／attempt各4→4，已有unknown／候选／确认及日周／观察／照片完整fixture保持。受管验证器SHA256为`a99a22c1d0b0907db1a022fea37c7e4ca8a01b3f608a0f41fd872fd5f36f9a7e`，不是测试机私下副本的e1e94cb0。

本机应用真实AI请求0，未读取／复制原档案、照片、配置或DPAPI。守卫在两个窗口及各自冷启动进程加载，各窗口2次非loopback解析被拒保留；这只说明Python守卫，不声称OS／WebView全局隔离。未执行受阻冻结EXE／helper／目标PS1、Office注册、签名、安装更新、WebDAV或发行。私有原始日志、XML、下载字节和合成资料留私下证据索引，不入Git。

### 8.4 收口、自动CI与下一步

两项限定源码核验通过；原0e51491测试机新完整1229通过、桌面627／1skip保留其来源，[§7.2原中断轮](desktop-windows11-white-concurrency-review.md#72-自动回归及中断分别记账)无原详细堆栈／退出的1个失败标记及映射继续保留，**未取得原因，不宣称已定位或修复**。原自然白屏、Word/r历史差异、Windows symlink特权、冻结恢复运行／安装更新、Win10／WPS／其它显示条件／跨用户／长根206等未验保持。

本轮准确六份源码／测试及对应正式文档，由Codex审核明确路径、工作树原字节、Git规范化blob、单父173880de7ac67b8fd847d13281f913f4d282fab3及暂存tree，再交原OpenCode A普通提交／推送；不add-all／amend／rebase／force或改main／tag／Release。最终SHA／tree和远端一致性按实际回执，不循环写入自身提交。

push若自动生成候选，Codex只读核**本提交**可信成功run／attempt、原外ZIP／内ZIP／PS1、package-info.source_commit、build_id／revision、289文件freeze范围及两个实际生产归档模块的修复后来源门。Git core.autocrlf及CI检出字节分别记，不能以本机混合换行的raw digest替代CI freeze，也不制造不存在的构建前时间证据。不dispatch／重跑；没有实际核到制品就只交源码结果。此段不预先声明新CI或冻结运行通过，后续制品身份和实际结果以本提交对应run及最终只读回执为准。

下一步是按新包身份安排原Windows11测试机的恢复限定增量，执行前核本次来源门及自有Core触发能力；本SAC4551开发机不试启动冻结包或helper。已通过完整local无新相关变化不再全跑；原AI配置两根按[§6.7](desktop-windows11-white-concurrency-review.md#67-后续拉取代码时保留本机ai配置)原地保留，不为这两项再调用应用付费AI，不重验旧39项、13份43页Word、IME或W6跨120秒睡眠。

## 9. 2026-11-05：恢复身份、内部退休与真实输入限定核验

**限定源码服务／对象合同核验通过；真实窗口输入能力阻塞，冻结内部项未收口。** 本轮只改源码专用验证器和测试，没有已确证需回修的产品缺陷，没有修改教师流程、产品运行面、构建、迁移、依赖或架构。

### 9.1 接收、方案与原生责任

开工工作树／index干净，HEAD为`a5580b18ae1973100408fd16e4f496c4edd8e0d1`，分支`codex/desktop-v2-foundation`、远端`git@github.com:ywyz/kindergarten-manager-next.git`。核暂存／未暂存及未跟踪资料后普通fetch，确认祖先关系及tree，只快进到用户指定`e42e83010c9fd81bf5788ae392af6123217fba32`，tree `6ddaf0cb76a0a0c9cbba95de6d08ea2695b6736c`。没有接收目标之后提交、覆盖他方修改、stash／reset／clean／merge提交／rebase／force。已读根AGENTS、current、[测试机§8.3–8.5](desktop-windows11-white-concurrency-review.md#83-冻结入口与证据边界)、本记录§8及[恢复合同](../specs/desktop-renderer-recovery.md)。

Codex先裁定最小verification方案；当地原A `ses_ead8af71dffeJphI1NOWg4jZgI`开工idle／succeeded、准确cwd及build／`opencode-go/deepseek-v4.1-flash#max`已核，唯一可写`desktop/verify_renderer_recovery_window.py`及`desktop/tests/test_renderer_recovery_verifier.py`和自有私下辅助。当地原C `8cf528de-8773-4a06-9cc5-31e96fab515f`同项目原transcript及无在途运行已核，固定`deepseek/deepseek-v4.1-flash` effort=max，仅只读诊断／交叉审阅。Codex独占方案、正式文档、独立审核／复验及Git门禁。不冒用测试机会话、不fork／派子代理，不重放旧白名单。

源码阶段实际metadata独立审核为A **466条assistant／六阶段**、C **41次model_request_end／三阶段**，全部准确原session、指定Flash max；无parent／fork／子代理／换模，同模型压缩metadata单列通过；九阶段均自然CLI0。CLI0不替代代码或测试结论，Git阶段仍另核实际metadata与回执。

### 9.2 最小验证代码与审阅裁定

- 活动host观测只在`_page_lock`内读当前ticket／绑定／ready／launch等状态，不调用`get_bootstrap()`充当只读观测。旧票据必须在实际新host提交拒绝且前后全状态相同；故障前真旧token先在旧服务受保护context取得200，随后同一新服务port上旧401／新200，不以随机token、字符串差异、旧port拒连或健康接口替代。
- 私有observer记录精确old/new窗口标签／host／bundle／代际、真实恢复worker线程、严格递增seq和monotonic时间；核真实旧executor原子idle-stop返回、原线程由活到死、完整gate状态、旧服务确认停止、host退休、engine close/reopen、根锁保留、新bundle CAS及新业务ready先于旧destroy／closed。两次真实退休分别记录首次与幂等调用，不删事件凑顺序。新executor须非旧实例且归属新bundle／runtime，退休状态复用锁内快照，旧回调不得改变新host状态／冻结owner。
- 真实旧engine与持有Session须实际只读拒绝并为预期`RuntimeError`；新engine／Session有`SELECT 1`正对照。根锁校验同一有效handle，竞争必须`LOCAL_APP_ALREADY_RUNNING`；周签名身份前有效／后`LocalWeeklyPreviewStale`，daily／weekly采用store前真实issue/get、实际失效后get为None。store层退休不等于完整业务采用端到端；没有真实active worker时明确记absent，不宣称某发送中worker已退出。
- 原生输入门定位唯一owned模态提示、精确PID／owner／线程、非零互异控件句柄、前台及保留焦点，再允许真实SendInput。每提示最多一次普通激活，之后只读轮询；不通过Focus／Select／ActiveControl赋值修默认，不重复发送。Enter／Escape、提示SC_CLOSE、故障owner的SC_CLOSE、最终明确鼠标重开分别记，不用PerformClick／属性冒称按键通过。GUI门仍严格保留，能力不足不改成通过。
- 完整默认业务／资源指纹之外，另核`include_runtime_fields=True`全字段指纹及独立persist child；输出位于数据／凭据外且fresh，保留原raw-parent／reparse／互斥门。C提出输出根可嵌入data的意见经Codex回读被驳回：原函数已有resolved互斥循环；新增负例确认mkdir前拒绝，不新增无关相邻文件规则。

首版未运行窗口即被Codex退回：本机真实interop核到`IntPtr`不能直接`int()`；WinForms属性返回同一.NET对象时Python `is`为false、`Object.ReferenceEquals`为true。原A修ToInt64／managed身份，并补真实Form／Button正反例、提示尚未创建的等待竞态及错误线程／缺UID／重复seq等负对照。实现者初稿单元失败及后续修订日志均保留；这些验证器问题没有被当作产品键盘或恢复缺陷。原无详细堆栈／退出的中断完整轮失败、自然白屏触发及Word/r历史差异仍未知。

### 9.3 Codex独立源码／合成证据

最终受检验证器原字节SHA256为`31d43ac35b0881ec205563b656b4d7da4483b1f7ab941cca51b95293090ff7c6`，测试为`e13d36480956a019ad86a071c84143df38dba85d4842175fbbc70a4b9d30d403`。实际测试HEAD为e42e830工作树，交付时另核这些字节对应Git规范化blob和暂存tree，不把未提交工作树冒称已有新commit。

使用现有CPython3.14.10 x64标准GIL／锁定venv，APP_DISABLE_DOTENV、禁pyc、SQLAlchemy纯Python，各次新短TEMP／TMP及其内basetemp，沿原Python loopback守卫。未重复无关前端构建：前端源码及此前审定三文件原字节均未变。

| 独立范围 | 实际结果／边界 |
| --- | --- |
| 恢复协调器／原生适配／生命周期 | **67 passed，0 failed/error/skipped，exit0，1.87秒**；所涉产品源码前后未变。 |
| 原子idle-stop节点 | **7 passed，0 failed/error/skipped，exit0，4.75秒**，保留真实claim并发及未确认退出拒绝门。 |
| 最终验证器单元／真实服务集成 | **25 passed，0 failed/error/skipped，exit0，5.22秒**；三组独立共99项，不用实现者65项替代。 |
| 真实服务／对象交接 | 真旧ticket在新host拒绝且全状态不变；旧port旧token200、新port旧401／新200。真实coordinator／ReopenSequencer驱动旧线程实际停止、旧service确认死、旧host／engine／Session与签名／store退休、根锁保留及竞争拒绝，fresh executor归属正确。 |
| 顺序及所有权 | 完整21事件seq为1..21，均对应真实恢复worker；代际1→2，首次stop／service stop／retire／engine close/reopen／幂等retire／新bundle安装／service启动／business-ready／old destroy／closed顺序通过。old/new window与native adapter明确为测试替身，业务ready握手在真实context GET后建立；不声称真实WebView加载或像素通过。 |
| 完整持久化 | 49表／12资源，默认与含runtime字段全指纹分别前后一致；task／execution／attempt各4→4，unknown／候选／确认及日周／观察／照片等全表／资源保持。实际`close_latest=True`、服务／executor确认后root handle释放；这是合成合同资源收口，不是GUI正常关闭。 |
| 独立进程冷读 | 受管persist子命令新进程**exit0，4.67秒**；默认／全字段指纹、计数、integrity=ok／FK0均通过，无窗口、无执行器或供应商。 |
| 全字段负对照 | 只在新expected文件篡改runtime combined SHA，数据未动；**预期exit1，4.66秒**，counts/default fingerprint/integrity/FK仍通过而runtime_fingerprint_match=false，证明不靠计数掩盖完整差异。 |
| 来源稳定 | 最终独立执行前后**550份非Markdown受管文件SHA相同**；相对e42e830仅上述两份verification／测试改变。守卫与两份执行runner未被原生实现者改动。 |

独立服务集成默认combined SHA为`08d191942118dc33a452e147c4ba34c50e8e0c88be536489a76a43c897e1d9c5`，全runtime为`8a08d8f6e5e3afbd496bba91d414b3b0ee4679cb87e3429d3827c4c3a1b51d21`；同根交接前／后及独立冷读相同，不与其它随机fixture根比较。492,067字节原始集成报告、XML、事件、日志、合成库／资源和私下索引留当地，不入Git；票据／token／bootstrap／payload不写报告。

### 9.4 实际窗口首失败、能力阻塞与未验

首个Page窗口受检验证器SHA为`f1a50375cbdc65381c1640f1495519db5f8c77cba9470ece8fce548e5da3f1a9`（本节最终回修前身份），先经当时21项独立单元再运行。自有Core Page.crash触发真正owned模态提示，PID／owner／线程、两个按钮、非零句柄和保留焦点均核到；但`foreground=false`，一次`SetForegroundWindow`返回false，严格门**没有发送Enter**，stage=`prompt_enter_foreground`。Enter／Escape／提示X及后续重开运行均未通过，Browser新窗口轮未启动；不自动重试或把此输入路由问题认作产品缺陷。

Computer Use只读owned子树的按钮句柄与上述原生证据相同，但没有独立可操作提示窗身份；截图报`CreateForMonitor 0x80070057`，尝试明确重开收尾时输入报`GetCursorPos 拒绝访问 0x80070005`。拒绝原样保留，未扩权或改用shell／其它输入注入绕过，已请求用户手动对该新合成档案明确重开再正常关闭。提交前未取得该原进程退出回执，不预填exit0；后续手动收尾或较新源码子进程独立记，不能补写此首轮通过。Codex另只读核该首失败根的49表／12资源默认及全runtime指纹均与故障前相同，未prepare、未输入或修改该根。

本片证实并修的是**源码验证器失败收尾**：driver直接destroy故障旧窗会被原生关闭拦截，`webview.start()`可能不返回，外围finally来不及受控退休。最终验证器先持久化首failure，再仅对本验证器自有失败窗按mark_expected_close→精确host retire许可→destroy收尾；顺序及失败负对照通过。该路径不进入产品，也没有把它当作GUI运行已复验。原始首失败资料、当时精确源码字节身份及进程现场保留。

原a5580b1冻结包的[测试机§8](desktop-windows11-white-concurrency-review.md#8-2026-11-05a5580b1新冻结包恢复限定增量)继续保持其原提交／build／run身份：外部故障、点击流程、完整持久化、配置保留及四次宿主exit0结论不重放、不撤销；内部ticket／token、对象退休、精确Core kind、business-ready先于旧destroy及真实键盘仍缺可靠冻结观测，不能用本节源码合同补写通过。真实in-flight worker退休、完整业务采用端到端、真实新WebView业务ready／正常关闭及其它既有未验仍分列。

### 9.5 Git、自动CI及原测试机接续

本轮应用真实AI调用**0次**；仅新合成资料，无真实档案／照片／配置／明文密钥读取或DPAPI复制，不重发unknown。Python守卫不等于OS／WebView全局抓包；原真实配置继续按[§6.7](desktop-windows11-white-concurrency-review.md#67-后续拉取代码时保留本机ai配置)原地保留。本机SAC4551不启动冻结EXE／helper，不改名、换路径、去来源标记或降低保护；不签名、安装更新、WebDAV、远控或发行。不重跑完整backend、旧39项、13份43页Word、IME或W6跨120秒睡眠。

只交付两份受管verification／测试及根AGENTS、本记录、current三份脱敏文档。Codex核准确路径、原字节／Git规范化blob、实际单parent e42e830完整SHA及暂存tree，再交原A普通commit／push原分支，独立核远端、tree、工作区及Git阶段metadata；准确新SHA和回执以实际Git结果为准，不循环写自身SHA。远端不可快进即报告，不接收他方后续提交或自动整合；不add-all／amend／merge／rebase／force，不改main／默认分支／可见性、tag／Release。

push自动生成新CI时只读核本次commit可信run／attempt、artifact digest、原外ZIP／内ZIP／PS1、两身份文件、manifest、实际来源freeze及CArchive/PYZ同源／必要模块门；verification不强行打入产品，不dispatch／重跑或伪造构建前freeze时间。提交前不预填新CI通过；实际候选身份以最终只读回执及本地证据为准，Windows2022静态不等于Windows11运行。

交回原Windows11测试机的最小增量：先核实际交付SHA／tree和新候选完整身份／原字节，在新合成根确认可取得真正owned提示身份、前台／焦点与可靠输入能力；能力不足就停止该分支记未验。可用时各一次自有renderer／browser受控故障，真实Enter保留、再次原生关闭重提示、Escape及提示X保留、再次提示后明确重开，正常关闭及独立新进程冷启动，完整默认／全runtime指纹保持；只按新身份记运行。内部项没有可靠冻结外部观测仍阻塞，不开调试端口、不注入／换模块、不增加公开JS／HTTP身份能力或产品debug开关。首次失败现场及其它历史未知继续保留，本片不是产品整体验收。
