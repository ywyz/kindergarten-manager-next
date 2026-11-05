# Windows 11 白屏、并发首失败与 Word 注册调用补核

更新：2026-11-05。**0e51491测试机增量已完成，见§7：后端新完整轮1229通过、桌面627通过／1旧包缺失skip，前端、观察窗口、手动重开及配置保留通过；来源门及受管验证器观测问题交回开发机。** 原中断轮失败标记、§6完整回归失败及§1–5限定通过保持各自身份，不写原失败根因已修复。原自然白屏最初触发、Word/r历史差异仍未知。前轮包与真实AI／Word／备份结果见[目标机核查](desktop-weekly-ai-windows11-target-review.md)，不跨身份作完整产品验收。

## 1. 授权、来源与责任

新增本机验证见§6：已提交61ef9f9上的完整回归未通过，真实AI源码样本通过，并取得人工浏览器丢失后的纯白状态对照。下文§1–5保留原限定审核身份，不以其通过结论代替新增全套结果。

用户明确授权原OpenCode会话和Command Go继续使用DeepSeek V4.1 Flash max，排查白屏及并发首失败、核查Word/r影响，保持系统保护不变；处理后继续测试，由Codex审核，通过后提交推送，交开发机接续。沿用`codex/desktop-v2-foundation`，开工HEAD与远端均为`7eb4b5ea859625de83fff073b01c6bb543e5cdf5`；开工12文件未提交补丁`c745f3cc…`及两份正式文档差异已保留，不覆盖原件。

原OpenCode`ses_e651729c9ffeG6mP7f6K1oat1I`／build／`opencode-go/deepseek-v4.1-flash#max`负责白屏生命周期诊断及必要修复。Command Go复用本机既有`b5a7810b…`会话，实际请求metadata为`deepseek/deepseek-v4.1-flash`／max，负责并发限定诊断。历史开发机C／D会话在本机不存在，没有假称恢复它们或fork。双方不派子代理，不改依赖／迁移／保护／Office注册，不签名或发行。

Command Go首试读取外部任务文件被工具权限拒绝，未执行源码改动；内联任务后仓库只读核查及隔离单项1/1通过，但源码`edit_file`与Git只读shell被其CLI权限拒绝。保留两个拒绝现场，不用CLI退出0冒称完成，也未以shell写源码绕过。Codex核定其自然停写后，将唯一`backend/tests/local/test_weekly_ai_adoption.py`写权转交原OpenCode；Command Go继续只读复核。未启用其要求的更宽CLI权限。Codex独占正式文档、Word影响独立核验及最终门禁，Git执行须后续具体文件／blob／parent／tree核准。

## 2. 白屏证据与受控重开

原候选仍为build`32a6d197-03c0-45ec-91fe-0b80d9528189`，EXE SHA `596f617ea9f3f40a952e3fb1dc7015509be5a85d4366efffd72ff3324cd7b2ef`。原进程身份／启动时间与前轮回执相同，消息泵仍响应，窗口只剩原生WindowsForms空子窗；没有关联WebView2浏览器／渲染子进程及其原生渲染窗口。Sky首次列窗超时、按规则2秒重试成功；遮挡状态截图一度捕获前台内容，重新选择并激活原窗后确认纯白与缺失WebView树，未把单幅截图当作全部证据。

限定事件回执记录07:04:41的Winsrv 10001：该应用试图否决关机。周边注销／关机失败是时间相关线索；未取得足以确定WebView2丢失的精确外因或与Word/r因果关系的证据。不以T09私有目录安全拒绝、分辨率变化或聊天中断直接解释外部进程消失。没有采集凭据内存dump、浏览器profile或无关资料。

现有[关闭协调器](../../desktop/d1_host_api.py)在页面通知失败后保持pending，30秒后取消并释放本次冻结；没有页面最终保存ack便不会销毁。原OpenCode私有反例核到pending→canceled、destroyed=0，重试生成新请求且仍不隐式允许；既有32项关闭及3项AI关闭屏障通过。Codex回读实际实现，认定这是当前保存保护合同内的拒绝，未发现独立可证的协调器缺陷；没有新增自动reload／自动退出／强杀或绕过保存保护的产品行为。渲染器丢失的产品恢复交互仍须另行核定，不写白屏已修复。

原白屏实例全部表和34受管文件在首失败后保持一致，3个task／execution／attempt均已成功。Codex保留一致性副本和进程／窗口证据，再核PID、启动时间、实际EXE路径及SHA，**仅外部终止该合成测试进程**；实得退出码`4294967295`（`0xFFFFFFFF`），不记正常关闭。没有全局kill、删锁、改保护或动原始合成源。

随后用同一EXE、原档案及同机凭据根普通启动，工作台正常显示；外部终止前／终止后／重开后／正常关闭后四阶段全部表及34受管文件完全相同，凭据密文行仅作不透明比较、未解密，任务与attempt仍3、无新增发送。该新进程正常关闭exit0。此为外部中止后已保存资料的恢复验证，不等于原故障自然恢复或异常页面的保存能力通过。

## 3. 并发测试首失败及最小修复

原60项首轮59通过／1失败、`ObjectDeletedError(LocalProfile)`及隔离复跑通过保持[原证据](desktop-weekly-ai-windows11-target-review.md#7-已授权t03来源修复与第二新候选)。`preview_adoption`的只读作用域最终rollback，使主Session里的`self.profile`过期；旧用例两个worker虽然各建Session，却在调用采用前读取`self.profile.id`，可能在工作线程通过主Session懒加载。

本轮只改上述测试文件：线程启动前捕获所需标识／版本／token；保留双线程Barrier和各自Session。增加线程确实终结、主Session在worker中没有ORM／事务活动、profile仍过期未加载、两结果相同且一新建一重放、一采用／一新稿及旧稿保留等断言。反向对照故意在worker读过期对象，实际观测主Session在该线程开始事务；这证明旧夹具危险路径，不宣称重现了最初ObjectDeletedError的精确概率交错。没有修改采用业务或用重试、串行化、sleep、skip消除失败。

实现者首轮追加断言误用了不存在的`current_content_id`，1失败／1通过，首日志保留；更正为真实`current_draft_id`后两个针对项通过。原OpenCode在文件SHA `11fe34e0…`下采用／备份33项、service46项通过，保留双线程的5次有界复跑均通过。Command Go同会话只读审核该快照无阻塞项，建议补充新稿总数断言。Codex核定原OpenCode追加“原数量＋1”，最终文件SHA `14f3642da02bfba4a247b00ad5153c2a2d7961818994d01c33776fff08a6ac92`，针对两项再通过。Codex独立回读最终diff并执行§5的完整相关范围；不把Command Go的早一版审阅或实现者33／46项冒称最终文件的独立验证。

## 4. Word /r 影响核验

微软明确说明`/r`会重新注册Word，并通过Office Setup更新注册表后退出。[官方参数说明](https://support.microsoft.com/en-us/office/lifecycle/command-line-switches-for-microsoft-office-products)。前轮一次误用/r是实际额外调用，不能当普通打开或声称无副作用。

没有调用前注册表基线，本轮未再次/r、regserver、Office修复／重装，也未改注册表、文件关联或Office安全配置。只读核当前Word为`16.0.20527.20112`，与前轮页检记录相同，签名Valid；App Paths、`.docx`／`.doc`、Word.Document打开命令、Word.Application.16／CLSID／LocalServer32共11个明确注册项结构与现安装路径一致。调用附近限定时间窗的相关事件查询成功、结果0；这不证明当时未修改注册表。

使用前轮合成Word的独立副本，通过明确`/n /q`普通打开，实际查看两页并正常退出exit0；又由现有默认DOCX关联正常打开Word并关闭。原文件及副本SHA保持`b8f41b8a…`，11个当前注册项跨本次功能复验不变。**当前注册结构、关联打开与文档功能限定通过；/r具体历史增删项仍不可判定，未回滚未知变化，也不宣称所有用户偏好保持原值。**

## 5. Codex独立验证与Git门禁

原OpenCode自然停写后，Codex固定393个源／资源／锁文件并独立执行相关范围，最终前后SHA一致；原12文件与构建批准逐文件SHA完全一致，组合补丁仍`c745f3cc7d6e52b9b5c986d8ee9ba7ecd767951e96b859ff9714dba078b9765d`。新增实现范围仅上述第13个测试文件，不改生产采用／关闭行为、迁移或依赖。原源码首轮59／1的失败记录保留，未覆盖旧日志。

| 独立核查 | 最终结果 |
| --- | --- |
| 后端相关范围 | **62通过，exit0，192.90秒**：来源变化service3、API14、采用17、周AI备份16、材料12。包含原失败用例和新增反向对照，保留52条既有弃用警告。 |
| 桌面关闭／AI屏障 | **35通过，exit0，3.62秒**：关闭32、屏障3。 |
| 源身份 | 393文件前后稳定；原12文件批准SHA保持；最终并发文件为上述14f3642d…。 |
| 验证环境 | 现有CPython3.14.10／Windows x64／标准GIL，独立短合成根，禁dotenv及外网，源码测试显式使用SQLAlchemy纯Python模式；冻结普通入口未使用该调试开关。 |
| Python守卫 | 两套日志均仅含atexit的`exit unknown`，无越界／网络记录；实际pytest退出0由独立进程回执及XML共同确认。该日志字段不作为退出成功证据，也不外推OS／原生进程隔离。 |
| 实际模型 | OpenCode导出核为原session／build／opencode-go Flash max、末次finish=stop；Command Go三次原生任务共14次model_request_end全部为Flash／max，首任务permission_denied、后两任务end_turn。 |
| 系统保护 | 09:46本机时区只读复核：SAC=1，8个策略名称／SHA与修复前完全一致；CI日志查询成功，当前候选路径事件0。未更改保护／注册／文件关联。 |

私有原始证据留测试机：两套独立日志／XML／源码前后清单，双方原生模型metadata与首拒绝，原白屏进程／事件／退出及四阶段一致性副本，Word当前注册／功能回执。公开仓库只收脱敏结论和审定源码，不收原日志、用户名路径、凭据／口令、SQLite、截图、Word或备份。原真实AI仍累计3次成功，本次补核新增0次；现有32a6d197…候选保持原“7eb4b5e＋12文件补丁”的构建身份，不因本次源码提交变成新CI包，未重建。

Codex结论：上述源码修复及限定验证**通过，无阻塞代码问题**。保留白屏精确触发原因、异常页面未保存资料及恢复交互设计、/r历史差异与前轮未验边界；这些均不写已修复或完整验收。通过后由原OpenCode按具体文件／Git规范化blob／parent核准清单只stage；Codex独立比对index后再核定tree及普通commit／push。禁止add-all、amend、rebase、force、改main／tag／Release或纳入私有证据；Git实际提交身份以分支历史及最终远端核对为准。

开发机接续见[唯一入口](../tasks/current.md)：先保留本地修改再快进核源；4551主系统保持源码验证边界，不启动冻结候选及冻结helper。白屏后续以受控合成复现和保存合同为起点，有证据的最小修复仍由原生指定模型实施、Codex独立审核；新增渲染恢复交互须先核定产品行为，不默认reload／退出或强杀。没有新增发行／签名／WebDAV／安装更新授权。

## 6. 2026-11-04本机完整回归、真实AI与渲染器丢失对照

本节是对已提交源码`61ef9f9ee54724e8c9a03e95f5e303ae0ba970da`的新增独立验证，tree为`7146737f7475cd7ab1d7a22b327cfea75749efb1`。此前§5的62／35项限定结论保持原范围；**本次完整回归未通过**，不能用单项复验或一次真实AI成功覆盖首失败。

### 6.1 来源、环境与授权

用户要求拉取最新代码、按当前提示词本机测试，并明确允许应用真实AI；配置缺失时由用户在应用中填写。最初指定工作树在main／`e836726`，其提示词仍为旧备份阶段；按项目规定使用已有`kindergarten-manager-target-handoff`工作树的`codex/desktop-v2-foundation`。普通fetch及快进拉取均核为上述61ef9f9，测试收尾fetch仍相同；测试阶段没有改main、另建分支、提交或推送。其后用户授权交回开发机时提交推送，接续门禁见§6.6。

复用既有CPython3.14.10／Windows x64／标准GIL环境，47个锁定包版本与现有lock一致；源码测试设置`APP_DISABLE_DOTENV=1`、`DISABLE_SQLALCHEMY_CEXT_RUNTIME=1`，使用新短合成数据、凭据、临时及证据根。没有安装或升级依赖／工具、执行冻结候选及冻结helper、改系统保护、调用Word注册、启动WebDAV或发行；U2仅运行合成源码helper。环境开关和测试守卫不等于OS隔离。最终前端由既有Node24.22.1直接执行14份脚本、typecheck及构建。

复用实际存在的原OpenCode会话`ses_e651729c9ffeG6mP7f6K1oat1I`仅作只读诊断。按两次CLI实际message ID核脱敏export，21条assistant消息均为build／`opencode-go/deepseek-v4.1-flash#max`，末次finish为stop，两次CLI退出0；未另起实现会话或让Codex写实现。本节及当前入口由Codex记录，日志／XML／过程证据及合成库索引私下保存在`kgm-20261104-151044`；保留的合成库位于各自新测试根，不含原业务资料。

### 6.2 自动回归及首失败

| 范围 | 实际结果 | 限制与身份 |
| --- | --- | --- |
| 后端全local，1221个收集用例 | **1201 passed、20 failed、1 error，exit1，4515.34秒** | error是同一失败用例的清理阶段，不额外算一个业务用例；91条warning保留。 |
| 桌面全套首轮，561项 | **543 passed、17 failed、1 skipped，exit1，183.50秒** | 首轮经过既有venv junction，且B3合成根位于TEMP兄弟目录；首失败不删除。 |
| 桌面U2／B3定向复验，60项 | **57 passed、3 failed，exit1，54.43秒** | 改用解释器实际路径，并令合成根位于TEMP内；未改生产路径保护。与首轮按用例身份合并为555通过／5失败／1跳过，**不是一次新的完整全套**。 |
| 已包含的限定桌面范围 | 关闭／AI屏障35、周AI生命周期2、构建guard36均通过 | 不作为冻结候选或整体验收。 |
| 前端 | **14份脚本、typecheck、build均exit0** | 最终直接Node24运行；此前npm由系统Node27启动的提示保留。首次Vite误用`--root`是调用参数错误，改用正确工作目录后构建成功；未改构建器。 |
| 观察记录真实源码窗口 | 验证器exit1、窗口子进程exit3 | 创建／编辑、历史恢复、冲突离开、首次Word保存通过；取消导出超时，后续多页检查失败并出现destroy_timeout。不能记窗口整体通过。 |

已核实的过期预期及环境问题：

- 后端5个失败来自旧预期：`test_daily_plans.py`周表集合遗漏已批准的`local_weekly_plan_ai_adoption`；`test_observation_migration.py`三个用例仍把当前head写为0007，实际0008；`test_observation_prompt_contracts.py`注册集合仍为旧5种，遗漏周6种。runtime guard用例在旧revision断言失败后未到dispose，另出现`.app-runtime.lock`的WinError32清理错误。需要保留旧行摘要、FK、源保护包及daily执行集合隔离等原断言，不能批量替换特定历史0005／0006目标或弱化检查。
- 桌面剩余5个失败为：资源manifest旧9条预期未纳入周6条；U2三个成功路径仍以0007作为当前target，而实际runtime迁至0008，真实回执返回`READY_MIGRATION_MISMATCH`，新进程无成功回执而退出；静态重解析点用例因WinError1314无法创建符号链接。未修改系统权限或把该项改记通过。另1项跳过原因为旧验证包不存在。
- 观察窗口直接原因经原OpenCode诊断及Codex回读确认：`run_selftest`创建窗口后未像普通入口那样调用`host_api._bind_window(window)`；取消用例清空验证保存目录后，其文件对话框替身没有被宿主使用，转为“无活动窗口”异常。普通入口有绑定，不能据此宣布生产取消逻辑已坏。异常外层返回失败时，该合成现场已有attempt仍为`in_progress`；宿主异常终态补报的健壮性须另核。本次没有修复入口或重跑成通过。

后端其余15个失败是1个观察视觉deadline用例和14个`WeeklyAIExecutorTests`：整套中出现claimed／retry_wait未到期望终态、trace计数0等。两个不同用例在独立新进程单项复验通过：视觉deadline为8.49秒，周部分成功为15.48秒。后者另用原venv junction路径的新进程对照也通过，9.24秒；因此**不能仅归因junction，也不能由代表用例通过关闭全部15项**。最初入口对照在会话中断时未形成XML／退出回执，按未完成保留，不算通过；随后对照使用新根及独立证据名。整套影响、执行时序及夹具隔离的根因仍待定位，不用追加sleep、串行化或skip代替修复。

### 6.3 本次真实DeepSeek源码闭环

新合成档案最初未配置AI；用户在源码窗口自行填写并保存官方标准API配置后，Codex只点击一次“生成所选周栏目”，仅勾选家园合作。实际为**1任务／1execution／1attempt／1candidate**，HTTP200、返回模型`deepseek-flash`、attempt时长12453ms。未在聊天索取密钥、复制DPAPI材料或真实儿童资料，未为模拟失败另发付费请求。

生成前后周头、草稿、确认和采用记录散列相同。完整只读预览列出人工输入和候选，明确采用后才v2→v3并新增1采用事件；内容变化仅为`weekly_columns.home_cooperation`及对应`ai_provenance.home_cooperation`。旧v1／v2行逐值保持，确认仍0；任务、attempt仍各1，无自动连发或确认。

普通关闭取得launcher和宿主实际exit0；同根同凭据根重开，八组业务／AI表散列一致，工作台及重进编辑器实际显示v3、原主题和已采用内容。再次普通关闭仍exit0。本次只有这一条周栏目真实成功样本，不覆盖真实unknown／付费重试、游戏／材料、视觉照片、MiMo或教师质量；前轮候选的三次真实调用保持其自身来源身份。

一次初始内容核对未解码SQLite中的JSON文本，导致中文子串检查false；解码后两字段均已保存，首次误判及更正文件保留，不作为产品保存失败。

### 6.4 真实源码进程级故障对照

使用另一新空合成根，档案0、凭据0、AI任务0；首次设置页面正常，先固定宿主、浏览器及其renderer的PID、父子关系、启动时间和实际路径。每次终止前重新核同一身份，只操作该明确测试实例，不做真实关机／注销，不杀未知进程。

1. 仅外部终止该renderer，实际显示WebView2的`RESULT_CODE_KILLED`错误页；宿主和浏览器仍存活，宿主响应。此状态与原纯白屏不同，未点击刷新或新增自动恢复行为。
2. 再外部终止该浏览器进程，实际为纯白窗口，Web内容树和所属WebView2子进程消失，原生窗口及响应宿主仍在；这取得了与原记录相似的状态复现。
3. 对该窗口发出一次普通Alt+F4，超过30秒后窗口和宿主仍在；50张SQLite表的行数／散列全部不变。没有对该存活进程内部的pending／canceled状态作直接观测，不能用单位测试推定本次内部状态回执。
4. 保存现场和逻辑快照后，仅外部结束已核身份的空合成宿主用于清理；宿主及launcher均exit-1（0xFFFFFFFF），明确不是正常关闭。真实AI档案此前已两次正常关闭，未用于本次故障注入。

**结论只覆盖人工造成浏览器丢失后的状态及关闭表现，不证明原自然触发原因、Word/r因果关系、异常页面未保存资料安全或自动恢复能力。** 当前保存ack合同未改变；若新增重载／恢复／异常退出交互，仍须按当前入口先核定具体行为。

### 6.5 当前结论与接续

本次源码完整回归**未通过**，首次失败、清理错误、隔离通过和中断的无结果对照分别记账。原§5已通过的限定修复及各候选身份不重写；测试阶段无实现／测试／迁移／构建脚本修改，仅更新独立结果与执行入口，未提交推送。后续文档交付及本机私下配置保留安排见§6.6–6.7，不作为失败已修复。

后续先由原OpenCode按具体文件责任核修旧预期、清理及源码验证入口，并定位整套执行器失败的时序／隔离原因；Codex保留原失败并独立复验。渲染恢复产品行为仍待核定。不重做已收口Word／IME／旧教师清单，不扩为安装、冻结入口、Win10／WPS／其它DPI、签名、WebDAV或发行通过。

### 6.6 返回开发机的决定与最小回修清单

用户随后要求判断“返回开发机修复还是重新测试”，并明确授权选择前者时提交推送。决定**返回开发机修复**：已知9项旧预期、清理及源码窗口入口有具体回修对象，另外15项整套执行器失败尚未定位；同源再盲跑75分钟不能代替修复。此次交付只提交本报告与唯一入口两份脱敏文档，不把失败状态写成通过。Codex审核准确文件／blob／父提交／暂存tree，原OpenCode在同一指定模型会话执行普通提交及推送；最终是否成功以实际Git回执核定。

开发机先保留本地差异、普通快进核源，再按以下互斥责任由原实现者实施，Codex独立核查：

| 对象 | 已定位用例／入口 | 必须保留的约束 |
| --- | --- | --- |
| 后端旧预期5项及清理 | `test_daily_plans.py::DailyPlanApiTests::test_no_weekly_projection_tables_or_fields`；`test_observation_migration.py::ObservationMigrationTests`下`test_empty_database_registers_only_bundles_and_new_profile_seeds_all`、`test_post_commit_verify_failure_refuses_startup_and_does_not_seed`、`test_runtime_guard_then_seed_is_idempotent_and_keeps_daily_rows`；`test_observation_prompt_contracts.py::ObservationBundleContractTests::test_daily_executable_and_registered_sets_are_separate` | 当前head为0008，注册为日3＋观察2＋周6；daily可执行集合仍仅3种。清理须在断言失败时也dispose；原历史迁移目标、旧行摘要、FK和保护包断言不能弱化。 |
| 桌面旧预期4项 | `test_d2_w6_degrade_host.py::test_resource_bundle_check_requires_exact_daily_and_observation_rows`；`test_update_u2.py`下`test_helper_reverifies_original_zip_and_switches_directory`、`test_real_0004_to_0006_cold_migration_after_old_handles_release`、`test_ready_receipt_requires_real_identity_service_and_page` | manifest当前15条；区分当前runtime head、历史源0004及显式历史0005／0006目标。不能全局替换revision或豁免回执身份／来源核验。 |
| 源码窗口验证入口 | `desktop/d1_main.py::run_selftest`的窗口绑定；观察导出异常终态补报另核 | 对照普通入口绑定，保留取消、不覆盖、历史／冲突和多页断言；先分清夹具问题与产品异常路径，不凭验证入口失败改生产取消行为。 |
| 待定位15项 | `test_observation_ai.py::ObservationAiRealTransportTests::test_observation_attempt_uses_vision_budget_and_unknown_after_deadline`；`test_weekly_ai_service.py::WeeklyAIExecutorTests`的14个失败，见下文 | 保留首轮时序及trace；检查spawn／ready／permit／发送／终态持久化和夹具收尾。独立单项通过及junction对照只用于缩小原因，不算关闭。 |
| 环境未验 | `test_windows11_portable_static.py::test_report_path_guard_rejects_raw_parent_and_reparse` | 本机WinError1314；不提权、不改保护、不以skip记通过。移交有现成适用权限的环境时另记身份；旧包缺失的1个skip也单列。 |

上表后端文件均在`backend/tests/local/`，桌面文件均在`desktop/tests/`。周执行器14个失败的完整方法名为：

```text
test_wai21_partial_success_keeps_success_and_never_resends_invalid
test_wai22_truncated_success_response_is_unknown_not_candidate
test_wai23_pre_send_connection_failures_retry_exactly_three_times
test_wai23_retry_revalidates_source_before_second_attempt
test_wai23_tls_and_policy_refusals_fail_without_retry_or_send
test_wai24_auth_401_pauses_without_candidate
test_wai24_auth_403_pauses_without_candidate
test_wai24_invalid_output_fails_without_auto_repair
test_wai24_provider_5xx_is_outcome_unknown
test_wai24_rate_limit_pauses_unknown_and_never_resends
test_wai24_timeout_after_send_is_unknown_with_one_send
test_wai25_retry_requires_ack_and_creates_new_generation_only
test_wai27_local_commit_failure_retries_only_the_commit
test_wai27_unpersistable_result_keeps_unknown_without_resend
```

复验先跑上述受影响文件／节点及关联迁移、AI、关闭屏障；修复和定向通过后，再独立执行一次`python -m pytest backend/tests/local`及`python -m pytest desktop/tests`，输出新的日志与JUnit XML并记录完整source commit／tree。用实际解释器路径、现有锁定依赖，`PYTHONPATH=<repo>/backend`、`APP_DISABLE_DOTENV=1`、`DISABLE_SQLALCHEMY_CEXT_RUNTIME=1`、`PYTHONIOENCODING=utf-8`、`PYTHONDONTWRITEBYTECODE=1`；每次新短TEMP／TMP，B3根必须在TEMP内且满足120字符限制。前端直接用现有Node24运行`frontend/package.json`列出的14份脚本、typecheck和D1构建。源码窗口单独回归取消／多页／正常退出；不以新增sleep、重试、串行或删断言消除首失败。需要改动时再复验相关范围，不无故重复全套。

### 6.7 后续拉取代码时保留本机AI配置

用户希望后续修复拉取后不用重新填写。当前实现的供应商配置／凭据密文随档案数据库保存，DPAPI保护的主密钥位于独立凭据根的`<database_uuid>/<key_id>.dpapi`。单纯`git pull`只更新仓库文件，不清理仓库外两根；**同一测试机、同一Windows用户、同一档案数据根及凭据根、保留库身份与key标识时，可以沿用已保存配置**。本次普通关闭／同根重开已成功；修复后新源码仍须按下述方式核验，不能预先宣称未来版本已验。

本机保留本次真实AI合成体验档案及原凭据根，私下索引固定指向两根；公开仓库不记录个人绝对路径。使用普通源码入口时始终显式传入`--data`及`--credential-root`：漏掉后者会转用系统默认凭据目录，可能出现“未配置／不可用”。不要新建空档案代替原体验档案后再次要求用户填key；不要将这两根用于自动化测试、故障注入、备份恢复或临时清理。应用普通启动可读取自身已存配置，测试工具不得读取／解密／导出密钥或自动发起付费请求。

先正常关闭应用并确认宿主退出，再拉取并重建当前源码前端。私下固定启动说明、原OpenCode编写的本机便利入口及无密钥路径配置放在已有Git ignored的`private-evidence/`，不进入提交或作为产品安装功能。Windows PowerShell 5曾拒绝PS1，原拒绝保留；已安装PowerShell 7的既有RemoteSigned策略允许该本地文件，未修改策略、未使用Bypass。原OpenCode的`-CheckOnly`退出0；Codex另用该入口完成当前同源前端重建、普通源码启动、设置状态核对和正常关闭，入口退出0，实际显示“地址/模型/密钥已填写且密钥可解密”及“密钥已保存：是”，没有重新填写或保存配置。前后八组业务／AI表散列相同，task／execution／attempt／candidate仍各1，SQLite完整性与FK通过，新增真实请求0。该检查证明本机当前源码可以继续沿用配置，不预先证明未来修复版本已验。

后续拉取修复版本仍用原两根普通启动，设置显示已配置、不再输入，正常退出且无新增AI attempt，即可验证配置保留，无需为此再发真实AI请求。换机／换Windows用户、新建档案、丢失凭据材料或恢复不含DPAPI的备份不承诺免填；不复制DPAPI、不把密钥写入`.env`／启动命令，不改变现有加密与备份合同。

## 7. 2026-11-05：0e51491原测试机增量

### 7.1 接收、环境与责任

用户要求拉取`0e51491`、阅读最新入口并在本机测试，允许应用真实AI；若缺配置，先找隔离环境既有配置，不存在再由用户填写。原指定工作树仍在旧main，本轮继续已有桌面工作树，普通快进到`0e514917db3998adea1acbb59922fdb59be2bca4`，tree `c7ecd84bc08c4647c6378587c253ca50a5b86f8c`，不改main或另建分支。用户此前“返回开发机时提交推送”的授权继续用于本次两份脱敏交接文档，Git仍须当次准确文件／blob／parent／tree审核，不能重放旧merge或文件白名单。

实际CPython3.14.10／AMD64／标准GIL，`Py_GIL_DISABLED=0`，47个锁定包版本一致；现有Node24.22.1直接运行前端脚本。禁dotenv、SQLAlchemy纯Python、禁pyc，生成并核实子进程加载Python loopback-only守卫，使用新短合成根。开工、中断恢复及全部测试后549个非Markdown已跟踪文件的路径／SHA全部相同，无guard audit失败文件。没有升级依赖／工具、改系统保护、Office注册、WebDAV、签名或发行。

原OpenCode测试机会话`ses_e651729c9ffeG6mP7f6K1oat1I`只写Git ignored的私下恢复验证器及说明；三阶段91条实际assistant metadata均为build／`opencode-go/deepseek-v4.1-flash#max`，无parent／fork，均自然CLI0。Codex独立审阅后才执行；受管实现、测试、迁移及构建源码未修改。原始日志／XML／图片／合成档案及下载字节私下保留于本轮`kgm-20261105-0e51491-a54c`索引，不入Git。

### 7.2 自动回归及中断分别记账

| 范围 | 实际结果 | 身份与限制 |
| --- | --- | --- |
| 后端首次完整轮 | 日志至70%，已出现1个失败标记，**中断未完成** | 对话中断后进程已不存在；无JUnit XML、无实际退出回执，不能推算完整通过数或记完成。 |
| 后端新根完整重启轮 | **1229 passed、0 failed、0 error、0 skipped，exit0，2579.52秒** | JUnit与实际退出一致，91条既有warning；新TEMP／TMP及其内basetemp，标准`-vv`逐节点记录，未注入observer、改断言／时限／重试或skip。 |
| 桌面首完整轮 | **623 passed、4 failed、1 skipped，exit1，162.52秒** | 原日志和XML保留，调用环境问题见下文。 |
| 桌面修正环境后的完整轮 | **627 passed、0 failed、0 error、1 skipped，exit0，204.13秒** | 独立新根和完整628项，非按身份合并数；8条既有warning。 |
| 前端 | **14份脚本、typecheck、D1构建全部exit0** | 新同源前端3个文件与本次CI内ZIP逐文件原字节一致；Node24与CI Node26的环境身份仍分开。 |
| 观察源码窗口 | **17检查全true，验证器与宿主exit0** | 覆盖创建编辑、历史／冲突、取消导出、busy清除及16份混合导出；只核页面及DOCX结构，未重新做Office视觉页检。 |

桌面首轮两项B3失败来自Codex调用把basetemp设在TEMP的兄弟目录；修正父子关系后复验。另两项U2已切换目录并启动新源码fixture后提前退出；两个保留库、target及包身份均为0008，旧0007预期未复发。独立回读确认fixture未显式传前端，默认构建目录不存在；指定本轮已建同源`KGM_D1_FRONTEND_DIR`后完整复验通过。原新进程stdout／stderr为DEVNULL，不能冒称已取回首轮具体异常；不改revision、ready身份门、预算或保护来消除失败。唯一skip仍是`test_archive_module_scope_covers_host_and_same_origin`缺原验证包，不算通过。真实junction拒绝测试通过不等于Windows symlink特权已验。

对原中断轮做同源1229项collection，按日志进度字符位置映射，第628个零基节点为`backend/tests/local/test_observation_ai.py::ObservationAiRealTransportTests::test_observation_attempt_uses_vision_budget_and_unknown_after_deadline`。这是顺序映射，不是原轮详细失败堆栈或退出回执。该节点及全部22项周执行器在新完整轮均通过，覆盖原14个周执行器节点；这不是代表单项的相加数。原中断失败原因仍未取得详细时序，不能写其根因已定位／已修复，也不再于同源无变化时盲目重复全套。

### 7.3 异常页面手动重开的本机源码证据

沿已确认[恢复规格](../specs/desktop-renderer-recovery.md)，不用旧§6“待核定”撤销用户决定。私下验证器基于当前源码入口，最终SHA256 `e1e94cb035b8f45e67b87a925ee386a03c4bed07941c4370122ff4a4e73a967a`。执行前独立审核并回修原始根／reparse与persist边界、bootstrap观测及退化的字符串票据比较；原版与回修记录保留。越界`..`及不存在persist根的独立CLI反例均exit2且未创建目标根。只对新合成窗口UI线程内核明归属的Core发送`Page.crash`／`Browser.crash`，不按PID杀未知进程，不触已配置AI档案。

Page及Browser两个独立根均实际exit0：先选择保留，旧窗仍在；旧窗原生关闭再次提示，只有明确选择后同根建立新业务窗口，旧窗才退休。原生warning和两按钮文本可读，实际AcceptButton／CancelButton／ActiveControl与保留按钮的managed身份相同；这是默认属性和选择流程证据，不冒称另行手按全部键盘分支。新Core真实截图及DOM均呈现“已重新打开最后保存的档案。未保存的输入可能已丢失。”，未用WinForms空白子控件图代替WebView像素。

两根分别验证完整fixture：日内容4、周稿／确认、观察记录3／全部历史、照片及12个受管资源文件、设置与AI回执保持；task／execution／attempt各4→4，已有unknown及候选／确认不变。旧执行器退出，旧host退休，页票据和launch更新；向新host实际提交旧票据被拒，调用前后票据／bound／business-ready不变。在**新服务port**上，旧token为401，新token为200，不能拿旧port连接拒绝代替此证据。

fixture完整业务数据库／资源指纹故障前后相同，独立只读子进程重新计算同样通过；再分别用原受管持久化入口在另一真实进程中`LocalRuntime.prepare`冷启动、检查counts／integrity／FK、dispose，后测业务指纹仍与故障前相同。两次新窗正常关闭、`close_latest=true`。忙拒绝、owner／lease、并发及失败清理由完整自动测试提供相应证据；未对真实供应商发送中／待落盘故障作付费注入，也不证明原自然白屏触发或丢失的未保存输入可恢复。

同时确认受管`verify_renderer_recovery_window.py`两处活动host的`get_bootstrap()`调用（当前302、411行）会把页面身份创建接口当作观测。`d1_host_api.py`1495–1499正常创建新票据、清bound／business-ready；不是产品bootstrap缺陷。私下副本改为锁内读当前状态并保留真正旧票据拒绝；原受管验证器仍须由实现者回修，不能把受污染的握手证据当成普通已加载页面的只读结果。对退休old_host的调用会直接返回，不具有上述重置副作用。

### 7.4 同提交CI制品字节与来源门缺口

可信[run 41855931829](https://github.com/ywyz/kindergarten-manager-next/actions/runs/41855931829)／attempt1／job126664416969全部步骤成功，HEAD及tree与本轮一致。它是Windows Server2022构建／静态核验，不是Windows11运行通过。实际保留外ZIP、内ZIP和原字节目标PS1，未执行EXE／冻结helper／PS1。

| 对象 | 实际核验 |
| --- | --- |
| artifact13338315845外ZIP | 44,134,647 bytes，SHA256 `a3280f23e3455dcb651eca1fa7c33e0e8bbbb06b2543c5ca5d0f1e11cd0eb5c4`，与GitHub digest相同。 |
| 内ZIP | 44,169,173 bytes，SHA256 `88295fc66c4d5983d42e02ea737e1179d06a2481535ddc0b076be0d9be54548c`。 |
| 原目标PS1 | 62,869 bytes，SHA256 `aef1c2021a0767d66ab4ccf53c72fbb0caa5c00d35910888036fe40539faeefd`，与可信日志及本机原字节相同。 |
| 包内身份 | `package-info.source_commit`为本轮0e514917；package-info及`_internal/build_identity.json`的build为`a3344c50-2116-4138-bdde-adb13ca5b014`、revision为`20261102_0008_local_weekly_ai`，与manifest／CI摘要一致；AppIdentity按现格式没有source_commit。 |
| 文件与来源清单 | 外5／内190条路径、重复、CRC及link／reparse标志无异常；内190＝187产品文件＋3根部元数据。187文件逐个大小／SHA与manifest相同。现有285文件freeze重算为`b3b6e60ea351290581fc0b3e0ff637cdba10c37d2371fe2e682d7dcbe8cb253d`，匹配CI。 |

**新包来源门有覆盖缺口，须回修后再称恢复生产代码完整同源。** `build_e14.py`的SOURCE_GROUPS、`verify_e14_package.py`的REQUIRED_FREEZE_PATHS／ARCHIVE_REQUIRED_MODULES漏两个新增生产模块`renderer_recovery.py`、`renderer_recovery_native.py`，且`renderer_*`被分类为other，未受生产模块必要性约束。既有E14来源合同要求冻结产品／构建／验证来源并核真实生产模块；285匹配结论不包含这两个文件。只读目录核实二者确在1859项PYZ中，仅证明存在，不证明其源码hash已由旧门覆盖；未反序列化模块code或执行bundle。

源码验证器`verify_renderer_recovery_window.py`也未列该freeze；它未打入产品包本身不是缺陷，不能为补证将它强行列为产品归档必需模块。若以它支撑新包恢复能力，应补相应verification来源范围。本轮未跑新冻结包恢复窗口，CI56包／60归档项保持CI自身身份，不以本机源码结果或旧包替代。

### 7.5 原AI配置保留与接续

按§6.7私下索引找到原隔离体验档案和原凭据根，同机同Windows用户显式两根普通启动本轮源码，设置实际显示官方DeepSeek地址、`deepseek-flash`、已保存且可解密，无需重填。Codex未读取／展示明文key或复制DPAPI，没有点击保存配置／生成；正常退出exit0，八组业务／AI表散列不变，task／execution／attempt／candidate仍各1，integrity及FK通过，**本轮应用真实AI请求0**。该状态不代表本轮另验供应商连通。后续继续保留两根原地，不因拉取源码新建空档案或拿它做故障／恢复／清理目标。

本机本次源码增量验证及新完整回归已完成，**下一步交回开发机补修两个生产恢复模块的包级来源门，以及受管验证器的bootstrap观测用法**。不把私下验证器已通过写成受管入口已修，不因全部新完整用例通过删除中断首现场或宣布所有工程门／产品通过；回修范围见[唯一入口](../tasks/current.md)。只交付两份脱敏文档，原始证据、私下验证器、下载字节及档案／凭据不入Git。原自然白屏、Word/r历史差异、冻结运行／安装更新、Win10／WPS／其它显示条件／跨用户／长根206等原边界保持；不重跑旧39项、43页Word或微软拼音，不签名、WebDAV或发行。
