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
