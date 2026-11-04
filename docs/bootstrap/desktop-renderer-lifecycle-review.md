# 桌面渲染器丢失：开发机复现与生命周期核查

更新：2026-11-04。本片通知有界调度与用户已确认的异常页面手动重开，完成Codex限定源码审核：最终238项相关测试、真实renderer／browser故障业务窗口及独立进程完整指纹通过，详见§10–§12；不作冻结包或产品整体验收。接收的测试机提交为`61ef9f9ee54724e8c9a03e95f5e303ae0ba970da`，tree为`7146737f7475cd7ab1d7a22b327cfea75749efb1`；接收时工作区干净，普通`pull --ff-only`完成。前轮[目标验证](desktop-weekly-ai-windows11-target-review.md)和[白屏／并发／Word补核](desktop-windows11-white-concurrency-review.md)保持各自源、包和执行身份。

GitHub只读API核到该完整SHA的[push CI运行41757564487](https://github.com/ywyz/kindergarten-manager-next/actions/runs/41757564487)／attempt1为completed／success。本轮未下载或运行其制品，不能把API状态当包字节、静态或目标运行复验；它不含本片改动。

## 1. 本轮授权与责任

用户要求拉取最新仓库、审阅测试结果、安排下一步，可调用原生OpenCode和Command Go的DeepSeek V4.1 Flash max并行完成，Codex最终审核后提交；本轮另明确允许真实应用AI及业务实现。优先接续当前入口的渲染器丢失问题，不据此新增无关业务。真实AI仅在任务需要且有合成输入和正常应用配置时显式调用，不自动续发历史任务，不读聊天密钥或复制跨机DPAPI。

开发机实际存在的原会话已核：OpenCode A `ses_ead8af71dffeJphI1NOWg4jZgI`负责原生最小窗口复现及必要实现；Command Go C `8cf528de-8773-4a06-9cc5-31e96fab515f`只读核查保存／关闭合同和风险；Codex独占正式文档、独立验证和最终审核。测试机session不移植、不伪造。双方固定Flash max，不fork或派子代理，不重放旧写入或Git白名单。

第一阶段双方均无仓库写权：A只写本轮自有私有复现文件和报告，C只读回复。任何源码实施先核具体文件责任。私有证据根为`%TEMP%/kgm-renderer-20261104-r01/`，保留实际CLI输出、退出、模型metadata、首失败及合成现场；不提交原始证据。

## 2. 当前事实与诊断边界

测试机原实例的WebView2子进程与渲染窗口消失、宿主仍响应；已保存资料受控重开保持一致。关闭未取得页面保存ack时拒绝销毁，符合[保存关闭合同](../specs/desktop-manual-daily-plan.md)。原白屏精确触发、Winsrv时间线的因果关系和异常页面未保存输入仍未知，不回写为已修复。

本机现有解释器实际为CPython3.14.10／AMD64／标准GIL，pywebview6.2.1、pythonnet3.2.1，使用现有锁定依赖；venv配置文件的旧版本文字不替代实际运行身份。SAC4551主系统只做源码／合成验证，不启动受阻候选EXE或helper，不改系统保护。

已安装pywebview的`edgechromium.py`与`winforms.py`源码核查未接入`ProcessFailed`或`BrowserProcessExited`。WebView2将进程异常／不响应与浏览器正常退出分成不同事件，浏览器崩溃可能同时触发两种事件且顺序不保证；仅有退出事件不能推定故障。[Microsoft官方说明](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/process-related-events)。本轮不选择自动reload、自动关闭、强杀或跳过保存ack。需要新增恢复交互时先提出明确行为及资料风险供用户核定。

结构导航使用已安装codebase-memory技能的Verify范围：项目ready，generation `2026-11-04T03:56:40Z`；`_install_close_handlers`的调用方包含普通入口与selftest，动态内层回调不能据图谱声称完整闭包。`d1_main.py`、`d1_host_api.py`及两份关闭测试路径无记录gap但freshness为metadata_changed，已回读关闭安装、普通入口、协调器及通知实现；图谱只作导航，不手动重建索引。

## 3. Codex独立基线

实施前冻结713个已跟踪文件SHA。独立执行关闭协调器、AI关闭屏障及维护生命周期，共**56通过，exit0，3.07秒**，XML与进程回执一致。禁dotenv、独立短合成临时根、Python层外网守卫与SQLAlchemy纯Python模式；守卫加载且无外网拒绝记录。不外推原生WebView／OS网络隔离，也不把源码测试代替目标包或教师验收。

本节基线不作为后续改动的最终验证。

## 4. 独立审阅发现与最小修复范围

Command Go首段只读审阅自然exit0，提出关机原因丢失、页面通知阻塞和最终关闭未获closed确认三项。Codex核定：当前封装未透传CloseReason是能力边界，最终放行后不因超时解锁是已确认保存合同；这两项不能直接列为生产缺陷，更不能据此改变关机／保存策略。可单独实施的是阻塞通知导致的线程资源累积。

Codex在原源身份上用可释放的阻塞回调独立复现：三轮关闭／手动触发对应定时器，每轮均进入canceled，等待中的通知回调线程依次为**2、4、6**；intent／cancel各3，destroy为0，三轮请求身份互异。最后释放全部回调，所有探针线程均join完成，exit0。此证据证明重复关闭的资源边界缺陷，不证明测试机白屏由它触发，也不声称损坏了数据。

本次实现责任仅授予原OpenCode A：`desktop/d1_host_api.py`的关闭通知调度与`desktop/tests/test_d1_close.py`的对应回归；实际AI屏障测试暴露同步断言后，明确追加`desktop/tests/test_d2_close_barrier.py`，再由图谱／源码核到`backend/tests/local/test_d2_w3_host.py`的同类断言，仅授权对应关闭测试异步通知等待适配。采用每协调器有界通知调度，外部桥接调用不得持协调器锁或阻塞同步UI／超时取消；旧ID／generation消息不得覆盖新请求。保存ack、30秒取消、AI冻结／解冻、任务处理和最终一次性放行保持合同。真实卡住的第三方调用不能靠Python超时杀掉，目标是限制同一协调器的等待资源，不声称消除原生故障或恢复丢失输入。

首版把每个协调器的通知worker永久留在空闲Condition等待；这会在正常关闭／恢复替换后仍保留旧协调器，不能只凭“每个最多一个线程”放行。Codex对当时稳定源码SHA `e3e423d8…`独立注入一次正常通知并拒绝关闭，回调已返回、状态canceled，但join后worker仍存活，断言实际失败exit1。已要求空队列时在同一锁内原子释放worker、覆盖重新入队竞态，并在测试finally释放与join明确线程；保留首失败，不用扩大允许线程数的断言掩盖问题。

## 5. 原生最小窗口与独立复核

原OpenCode使用本轮独有的内嵌合成HTML／WebView2私有目录，通过当前Form与WebView2对象归属核验后，仅向本控件发`Page.crash`；没有终止未知进程或真实关机。首轮Microsoft程序集尚未加载、下一轮跨线程访问CoreWebView2失败均留在原始输出／首现场；后续所有CoreWebView2访问改为UI线程Invoke，未改安装包或系统保护。

Codex回读最终私有harness后，将相同SHA `eeae5740…`复制到独立自有根，重新运行三个模式并核结果，而非只采信CLI0：

| 模式 | 实际观察 |
| --- | --- |
| 正常负对照 | ProcessFailed为0；Form可见且未disposed、browser process存活，后续JS任务在1秒内完成。 |
| 本控件Page.crash | 收到1个`RenderProcessExited / Crashed`，退出码`-2147483645`；Form／CoreWebView2对象及browser process仍存在，后续JS任务在1秒内未完成。 |
| 本控件JS死循环 | 约3秒观察窗内ProcessFailed为0，Form／browser process存活，后续JS任务在1秒内未完成。短窗0事件不证明长期不会收到`RenderProcessUnresponsive`。 |

三次独立进程均通过harness的自有Form正常关闭并自然exit0；没有业务服务、档案、凭据或应用AI。使用禁dotenv、独立临时根与Python外网守卫；内嵌HTML不请求外网，但不据Python守卫证明原生WebView／OS全局隔离。

这证明renderer退出后宿主可存活且JS不可用，不能从窗口无响应直接推定故障种类。没有采集像素，不能冒称已视觉复现原白屏；本控件browser process仍存活，与测试机原实例所有相关WebView2子进程均已消失也不完全相同。浏览器进程退出、原精确触发和恢复行为仍未证实。新增恢复交互的具体行为另向用户核定，不用本复现授权自动重载或关闭。

## 6. 已确认接续：明确确认后的异常页面重开

用户已明确答复“采用此手动恢复方案”，本轮继续实施，合同归[手动重开规格](../specs/desktop-renderer-recovery.md)，不再重复索取同一产品确认。仅在原生事件确认主renderer或browser异常退出后，提供不依赖JS的提示及“重新打开最后保存的档案／保留当前窗口”选择，明确未保存输入可能丢失。GPU自动恢复或短时不响应不直接归入主页面已退出，也不因单次JS超时或截图失败启动重开。

只有用户明确选择重开且当前保存、原生文件操作、备份恢复与任务状态可安全收束后，才退休旧窗口／桥接并从同一档案的已保存状态建立新窗口身份；保存原始任务与回执，结果unknown不自动重发，候选不自动采用或确认。无法确认收束时保留故障窗口与证据，不强杀、不通过超时跳过保存ack，也不承诺找回渲染器内存中的未保存文本。该异常确认是独立入口，不能放宽正常关窗保护。

实施前须将确认后的交互、窗口／会话代际和回执边界归规格。验收至少覆盖：已保存稿／全部确认／照片保持；未保存输入风险文案；生成中／unknown及执行器未确认退出时拒绝不安全重开；维护／Word保存进行中不能越过；事件去重、旧桥接和旧采用票据失效；新窗口读取任务不发送；正常关窗回归。该工作不自动扩为关机策略或原白屏精确触发已定位。

## 7. 通知修复片的Codex独立结论

原OpenCode自然停写／CLI0后，Codex冻结543个已跟踪非Markdown路径，独立执行关闭、AI屏障、维护／恢复生命周期、原生保存宿主、真实周AI claim与两个更新关闭钩子及后端关闭状态机，共**121通过、6条既有弃用警告、exit0，5.55秒**。XML与进程回执一致，验证前后543路径SHA完全相同。生产文件当时SHA为`14b012828ad4c220236d0f022a607701432f55401639cd1a520b3c758ad80ab5`；该结论只覆盖通知片，不提前覆盖手动重开实现。

Codex另将提交61ef9f9的原字节host源码导出到私有负对照目录：同一可释放阻塞探针实际exit1，出现两个活动callback且timeout调用方不能返回。最终新源码独立执行同控制exit0：三轮intent／cancel各3、destroy0、活动callback最大1，最后当前abort送达且全部探针线程join。原2→4→6累积及首版idleworker失败均保留，不因最终通过覆盖。

Command Go只读核对生产SHA一致，认可通知泵的有界结构；其P1把“阻塞JS桥接回调不能持锁”扩大到既有短内存freeze／unfreeze owner钩子，Codex未采纳这项无实际宿主阻塞证据的范围扩大。owner原子检查继续避免旧cancel解除新freeze。其排队后deny／final allow、worker退出与入队并发的两项测试建议，归后续最终测试加固；不冒称已由顺序idle测试覆盖全部交错。

手动重开片按用户新决定继续实施与审核，最终统一交付尚未完成。本片未新增应用真实AI调用、冻结包、签名、安装更新或发行。

## 8. 恢复片技术裁定与并行责任

用户确认后，Codex写入恢复规格，A／C并行交技术提案，原B明确核到既有idle会话后仅承担原生适配两文件。原B接口见规格§3；A不得改其文件，B不得改main／host／业务协调器／生命周期或正式文档。仍固定原生Flash max、无fork／子代理。

Codex未采纳C首稿的同service／token／executor换窗口方案：`create_local_app`的HTTP token与session_scope属于app，周AI预览同时绑定launch与scope；仅退休native host不撤销这些能力。必须新app／服务／token／scope／launch，并在同根锁内让旧engine／Session和预览失效，不能靠隐藏新窗口冒称旧能力已失效。重用close／reopen原语不等于执行备份恢复，不运行RestoreCore或替换业务文件。

C修订认可新代际，但认为只读snapshot后直接stop已足够。Codex再回读实际执行器发现：`_claim_and_run`在同gate中先清`_idle`再离开gate做claim，`_active`可能尚未赋值；`is_snapshot_idle`没有检查这段交接。若据此stop，后台仍可能进入现有取消／终止路径。因此恢复片须增加同gate原子核定完整idle并停止的最小原语；不通过active只读快照、drain／dispose或清busy跨过在途任务。对应规格§2已明确，必要后端文件及回归由A唯一负责，具体实施门另列current。

为后续真实业务源码窗口，Codex已使用现有Node26.12.1／锁定Vite8.3.0构建独立前端根，Vite子进程exit0、三份产物摘要已复核；首次包装器在构建成功后打印Unicode时因控制台GBK退出1，该错误与原构建日志保留，后续UTF8只读核验exit0，未覆盖或重建。未安装／升级Node或依赖；未改前端源码，也未生成冻结包。

## 9. 原生适配片独立核查

原B按两文件责任完成后自然停写。Codex先独立执行24项单测、实际自有最小控件的Page.crash／Browser.crash和原生选择，机械结果均通过；但实际DrawToBitmap图像中重开按钮缺少末尾“档案”，固定250px的测试未能保证字体下完整可读。因此本片首审未放行，原图SHA `0bc663a1…`及回执保持。

回修改用当前字体的TextRenderer／PreferredSize计算文字、按钮与对话框尺寸，没有缩短已确认文案或改变系统字体／DPI。保留为默认焦点、默认Enter及Escape／X动作；只有主动选择重开才返回true。原B再次自然停写，最终native模块SHA `5788c468a9c70639a0ffabf43adfe9455a8fbd9b5bdba465e57a5a5e28b98779`、测试SHA `ac1b3bb2146f8589d0bf69633479b86787aaf5d3c240a7ba2853b89575adcfb1`。

Codex按该新身份重新独立执行：24项通过／进程exit0／XML一致；实际Page.crash收到RenderProcessExited、实际Browser.crash收到BrowserProcessExited；实际keep／X／Enter均false、明确重开true，默认保留的managed对象身份成立。两文件前后SHA稳定。新原生图SHA `87667f8d…`已由Codex实际查看：完整警告与两个按钮均可读；当前控件报告宋体9pt、DeviceDpi96，不外推其它字体／显示条件。

首次独立复制新版UI探针时，其固定CAPTURE仍指向B原图，安全断言实际exit1并拒绝覆盖；改为另一独立自有根后再执行成功，原回执与图片均保持。Browser.crash后pywebview私有清理打印无法读取已消失Core的BrowserProcessId警告，三次探针进程均正常exit0；没有修改依赖或将此警告记为完整业务重开已验。该片只证明原生事件／提示，完整业务窗口、保存／维护／任务阻塞和新代际仍由恢复协调片另验。

## 10. 恢复实现审核与首失败

A完成协调器、main接线、生命周期所有权和最小原子idle-stop；B两文件保持§9最终SHA，双方自然CLI0停写。C只读复核，不写代码或正式文档。Codex回读当前源码，对C建议逐项裁定，未扩大普通关闭或恢复默认语义。

审核回修包括：旧窗口观察器缓存确切执行器，防止迟到事件冻结新代际；提示worker启动／完成保留单一预约；原子idle拒绝不提前封死旧host；旧服务／engine停止未确认时保留独占lease；新执行器启动及app／host构造失败须保留部分资源；CAS失败只作freeze＋idle-stop，不能以stop／dispose间接终止在途worker；新业务窗口已可用而仅旧窗销毁失败时保留新窗口并准确返回旧窗保留状态。

Codex另实际否决过一版auxiliary清理：`close_latest`返回false前已经调用runtime.dispose。私有`root-auxiliary-negative`实际exit1，记录`root_disposed`；不能只断言返回false就宣布锁保留。回修后同控制`root-auxiliary-final`为exit0、dispose调用0；另外注入CAS交接失败及非idle新执行器，确认新current不被覆盖、未知部分资源被持有、只发生freeze／quiet-refused，根锁未释放。首失败回执保留。

A早期源码窗口分别因native尚未建立和指纹key错误失败；首批core测试也有实际失败，均在私有根保留。Codex又发现旧验证器漏绑初始bundle.executor、seed freeze掩盖真实停止，以及把同进程LocalRuntime重建写作新进程；这些早期通过不计最终证明。最终验证器显式绑定旧执行器、种子完成即解冻、断言旧线程停止，并实际启动子进程检查。旧port拒绝只能证明旧服务不可用；Codex另用新port核旧token，不混同两种证据。

最终生产源码SHA：协调器`c3a794bf0e367aaa3820cab117ee739608799b0133f317a593434c8085b83093`，main `8e4bd9ed181528c44fc0029996fb9767b0517d9c025eaf35b86996a8369c3e28`，生命周期`2e2580908a3cdf7fde1ff99b53c15e9381f9da61394ba6991e4dc7dafc766d22`，执行器`c4a6d9117ec39a82007a5eec06d78d1b1ea59aaf34994c2c1de2a1abc6d58577`。源码验证器为`cf55f72fbcc2d053e97aff60b22619c47f50ae7b6101ac4af411a6aff1de2e19`。其余文件身份见私有完整manifest与Git规范化blob门。

## 11. Codex最终独立源码与业务窗口结论

冻结全部已跟踪及新增、未忽略的非Markdown文件，共548条；独立执行关闭、AI屏障、维护／恢复生命周期、原生保存、周AI生命周期、更新关闭钩子、native适配、完整执行器文件及两个旧engine保护测试，**238通过、0失败／错误／跳过，6条既有弃用警告，pytest31.17秒，进程exit0**；XML与进程回执一致。验证后548条路径／SHA完全一致。通知排队后deny／最终allow、空闲退出后的重启及并发入队压力均有回归；不声称穷尽全部调度交错。

独立源码窗口使用新合成库、凭据根、同一已审核前端及真实main／服务／WebView2／B提示。Page模式使用验证器原SHA，Browser模式仅在私有字节副本中将唯一`Page.crash`替换为本自有Core的`Browser.crash`；产品源码未改，两次均自然exit0。实际先点击保留，再由旧窗X重新选择明确重开，旧窗仅在新窗业务ready后退休，新窗正常关闭成功。

| 实际检查 | 独立结果 |
| --- | --- |
| 完整档案 | 日计划四个版本、周稿／确认、观察／全部历史及照片、AI回执和合成凭据的独立fixture验证通过；tasks／executions／attempts各4→4，日内容4→4、观察3→3、assets4→4。unknown保持，没有新任务／attempt、自动采用或确认。 |
| 新旧资源 | 新engine／session_scope／launch／HTTP token成立；旧服务停止、旧执行器线程退出；重开期间根锁保持；旧engine及已持Session再次访问均被拒。 |
| 旧能力 | 故障前用普通业务服务生成真实采用预览，重开后提交该旧预览得到LocalAiPreviewExpired；旧页面ticket拒绝。在新服务port上旧X-App-Session实际401、新token实际200；不以旧port连接失败代替。 |
| 独立进程 | 验证器子进程计数、integrity及外键检查通过；Codex另起无窗口／无执行器进程，重新计算整个database＋resources指纹，与故障前完整指纹相同，exit0。Page与Browser分别有独立根及回执。 |
| 可见页面 | WinForms DrawToBitmap首图只画出空白子控件，不能据此判断WebView像素。Codex保留首图，另用自有新Core的Page.captureScreenshot取得实际renderer像素，SHA `716848eb…`，已实际查看：工作台正常显示，顶部完整呈现“已重新打开最后保存的档案。未保存的输入可能已丢失。”；DOM独立核到同文案。该次源码窗口及独立进程检查也为exit0。 |

各次禁dotenv、使用独立短根及Python网络守卫。源码窗口原有自动检查更新尝试解析api.github.com，被Python守卫拒绝，保留实际记录；不是0次外网意图，也不作为更新检查可用证明。无真实供应商AI调用；任务／发送结论来自合成终态fixture、执行器静止门及计数／完整指纹，不外推OS全局网络隔离或抓包证明。原白屏最初触发仍未知，不能因主动故障恢复成功宣布已定位根因。

结构导航复查generation `2026-11-04T05:19:22Z`，七条当前main／生命周期／协调器／验证器／执行器及相关测试路径无记录gap但metadata_changed，均回读实际源码；不把图谱当完整动态影响闭包，不重建索引。A自测198项及完整执行器21、恢复27、快照39另有回执，不能与独立238重复相加。

## 12. 交付边界与下一步

源码阶段模型metadata审计通过：A／B为原OpenCode build／DeepSeek V4.1 Flash max，C为原Command Go Flash max；本轮所有阶段自然CLI0，无parent／fork／子代理或换模证据，同模型压缩保留。Codex独占正式文档与最终审核，Git另按准确文件／规范化blob／parent／index tree普通提交当前分支，不提交原始私有日志、数据或凭据，不改main／tag／Release。

下一步是测试机针对本片新提交做增量验证：先核源及实际新制品身份，再核手动恢复、保存／维护／AI忙拒绝、正常关闭和回执保持。新包不继承本轮源码或旧包运行结论；开发机SAC4551仍不启动受阻EXE／helper。本轮未构建冻结包、签名、安装更新、WebDAV或发行，旧39项／13份43页不重跑；Win10／WPS／其它显示条件／干净机等原未验保持。具体接续只见[current](../tasks/current.md)。
