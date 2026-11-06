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

## 8. 2026-11-05：a5580b1新冻结包恢复限定增量

### 8.1 同步与唯一候选

原Windows11测试机继续既有桌面工作树和`codex/desktop-v2-foundation`。开工核全部工作树、远端、index、暂存／未暂存及未跟踪差异，桌面树原为干净173880de7ac67b8fd847d13281f913f4d282fab3；普通fetch后只快进到用户指定`a5580b18ae1973100408fd16e4f496c4edd8e0d1`，tree `1d8764849e5164313819dc81ea4b41345cb844f0`，没有接收目标之后提交。旧main工作树、其它工作树、原档案、凭据和全部首失败资料保留；没有stash／reset／clean／merge提交／rebase／force。

独立读取GitHub确认[run41969916766](https://github.com/ywyz/kindergarten-manager-next/actions/runs/41969916766)为本提交push、attempt1、job127055491174成功；artifact13388773258名称、HEAD、大小和GitHub digest匹配。保留原下载字节，在新合法短根解压，未覆盖旧候选。

| 对象 | 本机独立核验 |
| --- | --- |
| 原外ZIP | 44,135,995 bytes；SHA256 `3ac833d27da69874acf2b9b21b93f319ef719af484f03653f65e07d6adc4de08`，与GitHub artifact digest相同。 |
| 原内ZIP | 44,169,982 bytes；SHA256 `cf2d3b4fc24cf172744fea47deab429706ab535d79be8422914ee9d4ef15e22e`。 |
| 原目标PS1 | 62,869 bytes；SHA256 `aef1c2021a0767d66ab4ccf53c72fbb0caa5c00d35910888036fe40539faeefd`。 |
| 两身份文件／manifest | package-info.source_commit为a5580b18完整SHA；build_id均为`887a3d08-d0eb-4461-b1cc-df928d1ca1f4`，revision均为`20261102_0008_local_weekly_ai`；AppIdentity现格式不含source_commit。187产品文件逐个大小／SHA与manifest一致；外5／内190条目未发现重复、越界或link标志。 |
| 来源与真实归档 | 当前289文件原字节digest为`6f81b26d4df80bbcaf9672e79f62fbdaf294079b380c4e7d71712b7a417f4b2a`，与CI相同；LF规范化摘要另计，不与Git blob／CI检出字节混同。真实CArchive入口及PYZ受检123项均同源，production必要模块无缺失，两个renderer恢复模块已纳入production／required来源及归档门；14项verification support分列，源码验证器未强行加入产品。 |

归档读取在禁止进程／网络的Python audit hook内进行，未执行归档code；首次误调用带Git子进程的source_freeze被守卫拒绝，保留拒绝，随后保持同一守卫、仅用无副作用文件枚举读取当前来源。此枚举不是伪造的构建前freeze文件／时间证据；CI before/after稳定声明仍归CI自身。CI的Windows2022静态56/56、60/60保持其身份，不改写为本机冻结运行通过。

原字节PS1通过既有PowerShell7 RemoteSigned执行，只读预检exit0，报告44项required均通过、无required failure／unknown。本机Windows11 build26300、WebView2 156.0.4314.58、SAC enforce；未更改策略、去来源标记、改名或搬移受阻程序重试。此次新EXE正常显示首次设置页并经页面关闭ack退出；首个旁路进程观察器未取得exit code，不能补写为0。

### 8.2 原配置保留与实际授权

本轮用户新授权必要的官方DeepSeek／MiMo付费调用，替代上一入口“不额外应用真AI”的限制；不等于必须发请求。按§6.7本机ignored路径索引找到原体验data／credential两根，核同Windows用户和无reparse后，显式两根用**本次原字节冻结EXE**普通启动。设置页实际显示官方DeepSeek地址、`deepseek-flash`、“地址/模型/密钥已填写且密钥可解密”及“密钥已保存：是”；未重填／保存配置、未触发生成，正常退出**exit0**，整个数据库原字节SHA256前后一致。未读取、展示或导出明文key，未复制DPAPI，原两根未用于故障／自动验证／恢复／清理。本次配置保留无需付费请求；供应商连通未另验。

### 8.3 冻结入口与证据边界

Codex回读实际入口：正常交互及重开路径安装恢复watcher；既有selftest无恢复phase且不安装该watcher，源码专用验证器的进程内CDP／host对象观测不能移作冻结证据。当地原OpenCode与Command Go只读审阅也核此边界，没有开启远程调试端口、注入页面／进程或替换包模块。

原字节冻结包可按精确宿主EXE／SHA／创建时间、显式新合成根、唯一WebView2 browser父链及私有临时user-data-dir限定外部故障目标。外部证据只覆盖真实进程故障后的可见提示／窗口、端口及完整业务／受管资源指纹；精确Core故障kind、真旧票据拒绝且内部状态不变、新port旧token401／新token200、旧executor线程／host／engine／Session退休没有可靠外部观测面，必须分列未验，不能以旧port拒连、字符串比较或源码通过代替。

### 8.4 原字节冻结包实际结果

两个独立新合成根均由已审私下fixture辅助器准备；窗口、恢复和冷启动全部使用上述**同一原字节冻结EXE的正常交互入口**，无`--selftest`／外部前端／源码窗口／模块替换／调试端口。准备fixture的源码服务调用及只读指纹辅助器不冒称冻结窗口；它们没有启动供应商或执行器。仅在精确宿主PID、原EXE路径／SHA、精确data／credential参数、创建时间、唯一直接browser子进程及其私有TEMP目录、唯一renderer子树全部核定后，对已打开并再次复核的单个进程句柄执行一次外部终止。没有终止宿主、其它应用或整个进程树。

| 范围 | 实际结果 |
| --- | --- |
| renderer受控退出 | 宿主28992，renderer20660属于browser22580；句柄／父链／创建时间复核通过，单次终止成功。原生警示和两个按钮可见；点击保留后旧窗5245646、服务61618保持。点击标题栏关闭再次提示，明确点击重开后，新业务窗920306显示完整恢复提示，旧窗消失，服务切为57175。 |
| browser受控退出 | 独立根，宿主18600，browser11876；同样只终止核明目标一次。原生警示／两按钮、保留、标题栏关闭再次提示及明确重开通过；旧窗920486消失，新业务窗7277546显示恢复提示，服务54475→62858。 |
| 已保存业务／资源 | 两根各49张完整业务表、12个受管文件；包括日内容4版、周计划1份／正文2版／确认1份、观察3条／历史8版、照片、设置及AI候选／采用／回执。baseline、故障前、重开后、正常关闭后及独立冷启动关闭后，五阶段完整规范指纹全部相等；额外**包含全部runtime字段**的指纹也相等，不只比较计数。 |
| AI状态保持 | 两根task／execution／attempt各4→4；两成功、一失败、一outcome_unknown的原行、候选和确认均随完整指纹保持；active为0，无新增attempt。未重发历史unknown、自动采用或确认；未发起应用付费AI。 |
| 正常关闭／独立冷启动 | 两个恢复后的最新窗口均按页面close ack正常关闭，宿主exit0、无自有残留进程。随后分别以新进程28296、1324普通冷启动同根，工作台正常读回，再正常关闭exit0、残留0。共四个宿主运行回执均ok、实际exit0；没有以源码prepare子进程替代冻结冷启动。 |
| 稳定与保护 | 10份fixture／快照均integrity=ok、FK0、active0、辅助器Python守卫audit通过且网络尝试0。187产品文件前后大小／SHA相同、无额外产品文件；550个非Markdown受管文件前后SHA相同。原AI体验库最终原字节SHA仍与开工相同，测试宿主全部退出。 |

renderer完整业务／资源combined SHA为`a278856cccd8388280739298afdc5797db8027565c27f1ac179a37513a18b2b8`，browser为`1647b3d87f6d6769417b2b60bd0eba400b829c293c306f584cdd6ea6301002a6`。两根各自五阶段一致，不能跨根比较随机fixture身份。所有窗口截图与UI元数据、原始日志、指纹、数据库／照片、原下载字节及私下索引留当地ignored证据区；其中28幅本轮原JPEG从本地工具原始回执按原字节归档，没有重编码或重放故障补图，不入Git。

**限定外部恢复行为与完整持久化保持通过，冻结恢复整体未收口。** 默认保留按钮的焦点画面可见，但Sky未返回原生owned提示窗的独立可操作身份；向所有者送Return／Enter及Alt+F4时未得到可靠提示动作，画面出现提示失焦。实际保留／再次关闭／重开采用截图定位的鼠标点击并成功；不能把这些按键输入记为通过，也不能仅据此宣布产品键盘缺陷。Enter／Escape／提示X等键盘／取消分支保持未验。失效WebView的UIA曾返回缓存旧业务树，故障状态以原始像素为准，不将缓存当活动页面；新业务页另核新窗口、新URL、可见恢复提示及真实指纹。

旧端口监听撤销和新端口出现只是服务代际外部证据，**不是**新port旧token401／新token200。真旧票据提交拒绝且内部状态不变、旧host／executor线程／engine／Session及采用预览身份退休、精确Core故障kind、新业务ready与旧窗destroy的内部先后，均因冻结外部缺可靠观测能力而未验；未调用活动host.get_bootstrap()，未用字符串比较、旧port拒连或源码结论补齐。忙拒绝与真实供应商发送中／待落盘故障本轮未新增冻结运行，保留既有相应源码证据身份，不扩写为冻结通过。

### 8.5 原生责任、私下验证器与Git收口

当地原OpenCode `ses_e651729c9ffeG6mP7f6K1oat1I`负责两份ignored辅助器及最终Git；Command Go `b5a7810b-c0fc-44fb-8cee-48bb364231f9`只读诊断／交叉审阅；Codex独占正式两文档、源码终审、执行复验与Git门禁。实际cwd、原session／空闲与request metadata均核；验证四阶段OpenCode实际assistant为33／46／48／5，共132条，全部build／`opencode-go/deepseek-v4.1-flash#max`，最终idle/succeeded、parent为空；Command Go两阶段15条全部`deepseek/deepseek-v4.1-flash` effort=max、CLI0。未fork／派子代理、换模、扩工具权限或以shell绕过拒绝；Git阶段另核实际回执。

私下辅助器初稿的语法、路径／句柄与弱成功门未执行即被审查退回；Codex裁定Command Go反馈后交原OpenCode回修，独立PS／Python AST解析通过才执行。首个只读inventory因PowerShell7将JSON时间自动解析为DateTime，而脚本转字符串后与ISO比较，误报宿主时间不同；首日志、精确时间诊断与版本身份保留。实际UTC ticks完全相同；原OpenCode仅改为兼容DateTime／ISO的**精确UTC ticks相等**比较，没有放宽身份断言、增加等待或重试。此前没有施加故障；修正后各角色只故障一次。renderer最初launcher SHA为`d80c9ed25e268c8d393ed85e706b8f7eabbc9d4bf6c52f33022dcae1229878cf`；最终进程辅助器为`2d6999911b7dc406a5de78514426eaccfdb2236e3cd28d097dd7315aa97cc771`，fixture辅助器为`a35607785fdb522a131ddd2800a7f5f0f576c0d0f0a3f1038a2134802d7dc9a8`。这些是私下验证工具，未冒称产品入口／包内功能或受管产品回修。

使用现有CPython3.14.10 x64标准GIL及锁定依赖，禁dotenv／pyc、SQLAlchemy纯Python；各阶段新短TEMP／TMP，无pytest故无新增basetemp用例。辅助器守卫只覆盖其Python准备／读取，未注入冻结EXE／WebView，也不声称OS抓包或所有网络零连接。既有固定fresh KGM_D1_STARTUP_LOG只留关闭ack诊断，未增加产品调试开关。应用真实AI调用**0次**，本轮没有供应商连通验证；开发Go模型调用另列，不当应用接口。

只交付本记录与current.md，Codex核准确文件、原字节／Git规范化blob、实际单parent a5580b18完整SHA及暂存tree后，交当地原OpenCode普通提交／推送原分支，再独立核远端、提交tree和工作区；准确提交SHA及推送回执以本轮实际Git结果为准，不循环写入自身SHA。不同步目标之后的他方提交，远端不可快进则报告；不add-all／amend／merge／rebase／force或改main／默认分支／可见性、tag、Release。

原中断完整轮失败标记无详细堆栈／退出及未知原因、原自然白屏精确触发、Word/r历史差异继续保留。未重跑完整backend、旧39项、13份43页Word、微软拼音或W6跨120秒睡眠；不安装升级、改系统保护、执行受阻4551候选／helper、Office注册修复、签名、安装更新、WebDAV、远控或发行。本结果不等于教师体验或产品整体验收。

## 9. 2026-11-05：6b0a99e接收及3e0e42b候选限定复验

**101项定向源码测试、新冻结候选两类外部故障恢复与完整持久化通过；Enter／Escape和冻结内部对象观测仍未验。** 未发现本轮需回修的产品缺陷，未修改受管实现、测试、构建或迁移。首轮测试结束时按用户当时安排只整理脱敏结果与交接补丁，未暂存、提交或推送；11月6日用户新授权提交推送，接续见§9.5。

### 9.1 接收与候选身份

开工main工作树干净，main仍为e836726；最新修复实际位于桌面分支。在原桌面测试工作树检查干净状态后普通fetch及`pull --ff-only origin codex/desktop-v2-foundation`，从e42e830快进至 **6b0a99e61be7d01f7e045f58f377ba6345f9dbea**，tree **f36e6e7e4dca93628d57df2a25284f32232a2216**。3e0e42b仅改恢复验证器／测试及文档，6b0a99e仅补文档；产品源码及前端未变。已读根AGENTS、current、开发机限定核查§9、本记录§6.7／§8及恢复规格，没有改main或重放旧实现白名单。

使用既有CPython **3.14.10 x64标准GIL** 的真实venv路径；禁dotenv／pyc、SQLAlchemy纯Python，定向pytest各用新短TEMP／TMP且basetemp在其内，继承已有Python loopback守卫。图谱候选路径缺失／陈旧已确认，验证器、测试、协调器及原生适配回读当前磁盘源码，不据旧索引作完整性结论；未安装升级依赖或工具。

通过GitHub连接器只读核[run42010782459](https://github.com/ywyz/kindergarten-manager-next/actions/runs/42010782459) attempt1／job127188965949成功，artifact **13406493851**未过期，head为 **3e0e42b657d24dd040ad26c9e9caabc90b56ebad**。原外ZIP44,135,372字节，SHA256 `4639314af6f9f16e877dcd78d3eb7bfdeb72187b1f126a3b4434c2ae0eb20a59`，与GitHub digest一致；内ZIP44,169,769字节，SHA256 `5354f26cb49d44685550b42d5687864bcf0af57f5b119b0e138af44984ef67be`。原目标PS1摘要与开发机§9.5相同，内包190条路径／重复／重解析标志检查通过。

候选build为 **e12d7af1-d388-4e74-be72-1ba8a6b7cd88**，revision为`20261102_0008_local_weekly_ai`，package-info.source_commit仍为上述3e0e42b，EXE SHA256为 `2d6e8eebecc59472c8006e750cfe27dca51bacbc3810dc8998c28af90b39e363`。本机原字节PS1经既有PowerShell7普通权限只读预检，**46项required通过、0失败／unknown、exit0**。CI的289份freeze及56／56包、60／60归档静态门保持Windows2022身份；本轮没有另重建或冒称本机重跑同源门，也不把候选改称由较新文档HEAD构建。

### 9.2 独立源码与配置复验

| 范围 | 实际结果 |
| --- | --- |
| 恢复协调器、原生适配、维护生命周期及最终验证器四文件 | **92 passed，0 failed/error/skipped，exit0，8.15秒**；包含25项验证器测试及真实服务集成。 |
| 原子idle-stop／owner及app令牌退休 | **9 passed，14 deselected，0 failed/error/skipped，exit0，8.95秒**；7项原子停止、2项app令牌。deselected不是skip。 |
| 真实服务／对象合同 | 真coordinator／ReopenSequencer及service／host／runtime／executor链核到旧ticket拒绝且全状态不变、新服务旧token401／新200、旧线程／服务及对象退出、根锁保持和21事件顺序。窗口与native adapter明确为测试替身。 |
| 独立进程持久化 | 对本轮集成合成根调用受管persist入口，新进程**exit0**；默认／全runtime完整指纹、计数、integrity=ok／FK0通过。仅篡改新expected的runtime combined SHA，反例**按预期exit1**，其余门通过。 |
| 原配置普通源码窗口 | 复用§6.7原data／credential两根，便利入口CheckOnly及普通启动均exit0；Node24.22.1重建当前前端。设置实际显示`deepseek-flash`、密钥已保存且可解密；未重填／保存配置或生成，正常关闭exit0，原数据库原字节SHA前后相同。 |

源码集成默认／全runtime combined SHA分别为 `943fdece88d0478220f98bc3a73c60a3c635bfc87ed3c1738b15f66af0a55b71`／`976afb8a5f6dc114d161171697e97ed254e255feab7c64c87d6bf206328a88cb`，不与下述独立随机fixture根交叉比较。用户真实AI授权有效，但本片无需新供应商请求，应用调用仍为 **0次**；可解密不等于另验供应商连通。没有读取导出明文key或复制原DPAPI，原体验两根未用于故障、自动测试、恢复或清理。

### 9.3 新候选冻结窗口实际结果

原OpenCode `ses_e651729c9ffeG6mP7f6K1oat1I`只准备两份新ignored辅助器：复制§8最终工具，仅改固定新根、EXE摘要、身份说明与旧根保护。独立逐行差分、Python AST／PowerShell解析通过，旧工具SHA保持；新增11条assistant实际均为build／`opencode-go/deepseek-v4.1-flash#max`，自然CLI0、最终succeeded。原Command Go `b5a7810b-c0fc-44fb-8cee-48bb364231f9`按显式`deepseek/deepseek-v4.1-flash` effort=max、plan只读复审，CLI0；首次仅返回旧反馈，随后给精确路径复审当前字节，确认已有startup／active任务／guard／exit0及无残留门，未代作实测或写文件。

两份新合成档案各49表、12个受管资源，涵盖日内容、周稿／确认、观察全部历史／照片及AI回执。全部窗口使用同一原字节EXE正常交互入口，无selftest、外部前端、远程debug、注入或替换包模块。核精确宿主路径／SHA、显式两根、PID／创建时间、唯一直接browser及私有临时目录、唯一renderer子树，复核单个目标句柄身份后每角色只故障一次，不终止宿主或其它应用。所有UI由Codex经Computer Use操作，辅助器不执行输入。

| 分支 | 实际外部结果 |
| --- | --- |
| renderer | 首宿主15992；提示X后保留故障窗2034908，标题栏关闭重新提示；明确保留后仍可再次提示，明确点击重开后新窗44109180显示恢复说明、旧窗消失，URL62332→57020。正常关闭exit0；独立进程29364冷启动读回工作台并正常关闭exit0。 |
| browser | 独立首宿主28256；同样完成提示X保留、标题栏关闭重提示、明确保留、再次提示及明确重开；旧窗396070→新窗592800，URL52318→52425，出现恢复说明。正常关闭exit0；独立进程16752冷启动读回工作台并正常关闭exit0。 |
| 完整持久化 | 两根各baseline／before-fault／after-reopen／after-close／cold-after-close共10份完整默认及全runtime指纹逐项相同，49表／12资源保持；每份integrity=ok、FK0、active0、辅助器网络审计通过。task／execution／attempt各4→4，unknown／候选／确认保持，无自动重发、采用或确认。 |
| 退出与保护 | 四次实际宿主exit0、自有残留0，全部测试窗口退出。187份产品与manifest逐项大小／SHA相同，无额外／缺失路径；原AI体验数据库与旧辅助器原字节保持。 |

renderer默认／全runtime combined SHA为 `4ed2e16cb83565b4cdf833682066d2e5091c40e39127f128f36809ac9ed839ff`／`910953101eaf0a1010637c513d9684086e2eec6c32c9834ff24ef69746ad5d03`；browser为 `b290a7d3d35051fb0fec46aebd702c96666efd4c65b4f8cbcf61c0fcc0dd938f`／`6e7a70b3938a71d8814171544565a8809cba70457322fc899e40de139985ca42`。

### 9.4 能力边界、首失误与后续

**提示X是真实鼠标点击通过；Enter／Escape未发送、仍未验。** 本机现在能截图及操作独立提示图像区域，但窗口清单仍只给owner，没有可独立绑定的owned提示window ID；不向owner发送按键冒称提示键盘通过。源码配置检查首个点击因无截图映射被工具拒绝，取得原生截图后输入正常；没有扩权或其它注入绕过。冻结内部ticket／token、旧host／executor／engine／Session及采用预览退出、精确Core kind、新business-ready先于旧destroy仍无可靠外部观测，不能用源码合同或URL变化补齐。

源字节首清单因Git中文路径加引号漏记一份历史DOCX，开工实际549份，修正枚举后550份；原549份逐项原字节不变，漏入DOCX另与HEAD原始blob相同，不能补称开工已冻结550份。最终包计数命令首个断言误把manifest已含的元数据再加1，实际exit1；实存与manifest均187且无额外／缺失路径，改为精确集合／大小／SHA比较后exit0。两项为本轮验证清单处理失误，原回执保留，未改产品或重放故障凑通过。

Command Go另指出私下launcher在启动后写回执／等待异常时可能保留进程。本轮没有注入该分支，不能声称已验异常自动清理；实际各次正常关闭后均核自有残留0。复用前先评审该辅助器异常收尾，不将其写成产品缺陷或用全局kill处理。固定fresh startup诊断沿既有用法，不是新增产品调试入口。

首轮提出的两文档交回开发机提交安排，已由11月6日用户新授权替代，改为本机按§9.5完成普通提交推送；原始日志、图片、数据库、凭据、下载字节或ignored工具不入Git。Enter默认保留／Escape取消由能可靠聚焦提示的人工或原生能力补最小验收；内部冻结观测若仍要求收口，先提最小verification方案及来源／安全边界，无可靠能力时保留未验，不开产品debug或公开身份接口。没有产品源码回修待合并，不重复已通过切片或启动无关功能。

真实发送中worker、完整业务采用端到端、自然白屏触发、旧中断轮原因及Word/r历史差异没有新增结论。未重跑完整backend、旧39项、43页Word、IME或跨120秒睡眠；Win10／WPS／其它显示／跨用户／长根206、SAC4551、签名／安装更新／WebDAV／发行边界保持。本片不是产品整体验收。私下证据索引别名`target-6b0a99e-94b5`保留XML、首失败、完整指纹、四次宿主回执、模型记录、原字节制品与新合成根，不入Git。

### 9.5 2026-11-06：用户授权提交推送

用户新指令“请提交并推送”已替代首轮停在交接补丁的安排，无需重复确认。开工核当前分支及index，仅本记录与current两份受管文档有改动；普通fetch后，本地HEAD与远端同名分支均为`6b0a99e61be7d01f7e045f58f377ba6345f9dbea`。本机原OpenCode会话、指定模型及已自然停写状态另核，没有冒用开发机会话或重放旧实现权限。

Codex审核两文档的脱敏内容、相对引用、空白差异、准确路径／原字节／Git规范化blob及实际parent后，交原OpenCode仅暂存这两文件；独立核暂存tree及无额外路径，再放行该parent／tree的普通commit／push，最后独立核远端、提交文件／tree和工作区。准确提交SHA与推送回执以实际Git结果为准，不为填写自身SHA追加提交。该提交仅交付已有测试证据与最新授权记录，不重跑业务测试或改变原候选来源／测试结论，不带私有证据、不改main／默认分支／tag／Release。

## 10. 2026-11-06：b657363 原 Windows 11 关闭／恢复增量

### 10.1 测试来源与静态核验

开工主工作树为干净的 `main`（`e836726f008676fc603a7b4cb058e5d96cafe60b`）。先记分支、HEAD、状态，再普通 fetch。原桌面测试工作树干净，分支 `codex/desktop-v2-foundation` 从 `96dc1d7a555a1eec8bd33c2139a74f0a706c0e06` 以 `--ff-only` 快进，测试 HEAD 为 **`b657363c12901d5f559f3ef88e1ff5f0bd7926f0`**，tree 为 **`3b23e76d288083f84e2e0731579f2bec223416f0`**，与 fetch 后远端一致。以下窗口使用原 Windows 11 测试机的本机交互会话。

[push run 42130919515](https://github.com/ywyz/kindergarten-manager-next/actions/runs/42130919515) 的 attempt **1** 成功，artifact **13463875656** 属于该分支及 HEAD。下载保留原 ZIP 字节，先核 GitHub digest，再解包。两层归档均先检查路径、大小写重复与重解析标志，外层 5 项、内层 190 项。

| 核验对象 | 字节数 | SHA-256 |
| --- | ---: | --- |
| 原始 artifact ZIP | 44,142,889 | `534a4c58b4811e92362e5afa6ef3dda13fd5fdf00fa2d04c13bb6e7e1d76416f` |
| 产品 ZIP | 44,177,790 | `a2bab41752013f0759580211682afcf5c0175b5a435f76f52402aace1d92b2e3` |
| KGNext-E14.exe | 17,195,426 | `e75a92fdf1432a8e94f2db7ea184410e78b56cbb7d0fa0a2098c3e0870202077` |

产品目录与 manifest 的 **187 份**文件路径集合、逐项长度与 SHA-256 相符。包内身份、manifest、CI summary 的 build 均为 `223e3bfc-bb2d-456d-b3b7-b4a49c0a9f0e`，数据库 revision 为 `20261102_0008_local_weekly_ai`。package-info 的 source_commit、CI 的 commit/tree、workflow 与构建脚本的 Git blob 和本地字节均已对上。CI 记录 289 份源码 freeze 稳定、package 56/56、archive 60/60，其执行环境为 Windows Server 2022。本机另外只读检查原 EXE 的 CArchive 入口及 123 个项目／验证支持模块，与目标源码指纹一致；本机未重建 CI 的私有构建前清单。原字节预检脚本在本机得到 46 项 required 通过、0 失败／unknown、exit 0。

### 10.2 关闭协议的源码与测试工具证据

在已有 CPython 3.14.10 x64 标准 GIL 环境、新短 TEMP/TMP、禁 dotenv／pyc、SQLAlchemy 纯 Python 与 loopback 守卫下，本机单独复验普通许可不复用、ack／fault 接管及最终关闭分支，**9 passed、45 deselected、exit 0**，守卫尝试数 0。完整开发机源码证据另见[开发机限定核查 §10](desktop-regression-repair-review.md#10-2026-11-06测试机回执接收与关闭交错回修)。

复用前审查了旧 launcher 的 `Invoke-Run`。宿主启动后若写 running 回执异常，旧工具可在宿主仍活着时返回；等待异常后也可能标为 exited 并释放观察句柄。直接复用无法满足本轮收尾门槛。新合成 fixture 分普通、renderer、browser 三个根，各自生成数据库、照片、凭据及导出目录。seed 时各为 49 表、12 个受管文件、活动 AI 任务 0。

本机原 OpenCode 会话 `ses_e651729c9ffeG6mP7f6K1oat1I` 制作新 ignored 工具。新 launcher 持有原进程对象，启动后写回执／等待发生异常时先向 stderr 与独立应急回执记录错误，核归属后在原句柄上有界观察，为操作者正常关闭留出时间。超时或无法证实归属会报失败并保留现场；自动异常路径本轮只做审阅。Codex 在启动前另外安排独立观察进程，按 EXE、显式合成双根与创建时间钉住宿主句柄，记录真实退出。受控故障仍要求复查唯一宿主、WebView2 子树、角色、私有临时目录、创建时间及同一目标句柄。

### 10.3 首失败与证据保全

**F01 为取证工具失败。** 普通首进程（PID 13472、窗口 525768）已显示工作台；首个观察调用中的截图归档函数读取空场景名，写盘返回 ENOENT。此前未发送窗口输入，也未开始有意保存。先原位保留合成根、下载包、基线指纹、startup 日志和进程树，复制当时可读的库、资源和凭据，并在未发送输入前补存原窗口截图／AX。活动根锁持有期间无法复制，原件原位留存。取证复制命令有一项路径转义错误，在同一未操作现场补齐。随后正常关闭，launcher 与独立句柄均记录 exit 0，owned 残留 0。首失败路径索引为 `first-F01` 与 `case-normal`，冻结业务通过数不计这次。另一次前置只读命令使用了旧版 OpenCode 导出语法；改用本机 `session export` 后核实了原会话、目录、模型和停写状态。

F01 后用新建的 `case-normal-r1` 独立生成合成档案，原根原位保留。另有 **F02**：browser 重开窗正常关闭时，观察命令的首次等待尚未返回，调用方提前读取当时尚未生成的 `after-close.json`，报 FileNotFoundError／exit 1。先在 `first-F02` 保存当时已有的截图、指纹、库、日志、包与进程记录，再接收同一宿主的自然退出回执，之后才取关闭后指纹。冷开过程也有一次窗口枚举早于窗口就绪，未发送输入，待同一进程就绪后才绑定。两次故障各仅触发一次。

### 10.4 冻结窗口与持久化实测

三个正式场景各在自己的合成档案创建 11 月 6 日日计划，输入可辨别的合成内容，点击“保存”并看到成功与 v2。普通场景保存晨间谈话话题，故障场景保存各自的合成原始教案。以下基线均取自这次有意保存之后。三次独立冷开都从工作台重新打开该计划，读回了本场景的输入和 v2。

| 场景 | 实际宿主 PID（首次／冷开） | 单次故障目标与窗口实测 | 两次宿主退出／自有残留 |
| --- | --- | --- | --- |
| 普通（F01 后的新根） | 11356／25684 | 保存后标题栏正常关闭；独立冷开读回话题，再次正常关闭 | exit 0／0，残留 0／0 |
| renderer | 9688／19672 | 目标 renderer PID 30700，原句柄实测 exit 1。提示 X 后故障窗保留；点击宿主 X 重新提示，明确保留，再次关闭重提示，点击“重新打开最后保存的档案”。旧窗 591294 消失，新窗 1704142 显示恢复说明、工作台与已存计划。宿主监听端口 63677→65070 | 恢复窗及独立冷开均正常关闭，exit 0／0，残留 0／0 |
| browser | 8364／1948 | 目标 browser PID 27460，原句柄实测 exit 1。同样实际完成提示 X、再次关闭、明确保留、再提示与明确重开。旧窗 1116374 消失，新窗 2162894 显示恢复说明、工作台与已存计划。宿主监听端口 64669→53516 | 恢复窗及独立冷开均正常关闭，exit 0／0，残留 0／0 |

六次正式宿主及 F01 的一次宿主均由 launcher 与第二个持有句柄的观察进程核到真实退出 0；退出取样时，自有临时根／数据根匹配的进程和宿主监听均为 0。末次全机只读清点未发现匹配本轮根的宿主或 WebView2。测试结束复核外／内 ZIP、EXE 和 187 份产品文件一致。

普通场景比对保存后、关闭后、独立冷开再关闭后 3 份快照；两个故障场景各比对保存后、故障前、提示 X 保留后、再次提示并明确保留后、明确重开后、正常关闭后、独立冷开再关闭后 7 份。共 **17 份**，均逐项比对完整默认对象与包含所有 runtime 字段的对象。每阶段 **task／execution／attempt 均为 4／4／4**，integrity=ok、FK 违规 0、活动任务 0、49 张表、12 份受管资源；unknown、候选与确认随完整对象保持。辅助 Python 守卫尝试数 0，仅覆盖该辅助进程。真实应用 AI 请求 0。

| 有意保存后的基线 | 默认 combined SHA-256 | 全 runtime combined SHA-256 |
| --- | --- | --- |
| 普通 | `ca76d72af060b9717e35dca11c568dd7266a0f90b16454ba22cd4d86fe32a4f5` | `2545df0ba234e95432fea1b5ccd3221e2226a6c6b2dbd2347a5817dd0abefd93` |
| renderer | `d282ce4830350ee59b81ba07f25799831fcd6953c6c4dda532f4320b6aa6d767` | `d10164e6c97d950a9ba8f96290b62fd6a4a25ffde80be6ed0bf7da1ddcea3dad` |
| browser | `9063c13c098f7b3c4ef1cc6dad279b4c796efdc9d11528226a9647b049435a9c` | `7615836dcc01c46afee46cb17bca70cb4fb81d3de131a8074ec313661ee926be` |

### 10.5 裁定、边界与证据索引

- **普通关闭许可不复用：源码已验、冻结运行未验。** 实包普通关闭日志确实出现一次许可消耗；从外部无法安全地在同一许可上发起第二次精确探测。
- **关闭确认与故障回调交错：源码已验、冻结运行未验。** 两个 WebView2 故障均在保存完成后触发，无法在未打开调试接口的冻结包上精确暂停 ack／fault 中段。
- **首轮未验证 Enter／Escape；随后人工补验结果见 §10.6。** 鼠标可绑定提示图像，窗口枚举只返回宿主。即使 AX 显示保留按钮获得焦点，也没有可单独绑定的提示窗口 ID；未向 owner 发送按键。
- **冻结内部 ticket／token、host／executor／engine／Session 身份、旧对象退休及新 business-ready 与旧 destroy 精确顺序未验**。本轮观察的是原进程句柄、可见窗口、UI 内容、监听和持久化。真实 vendor 回调阻塞仍沿原边界。
- 本轮产品实测项目通过，工具问题按 F01／F02 留证。未使用真实业务资料，未注入或替换包模块、启用远程调试或全局终止进程；未进行签名、安装更新、WebDAV 或发行。自然白屏与 Word 等历史未验项沿原记录。
- 私有证据索引：`kg6b657` 下的 `first-F01`、`first-F02`、四个 `case-*`、`src/target.xml`、`preflight.json` 和两层解包内容；`kga116` 下的原 artifact ZIP 与 GitHub 元数据；本机 ignored 目录 `private-evidence/b657-1106` 下的 `verified-results.json`、归档同源、逐次日志与 OpenCode 记录。各场景目录保存截图／AX、完整指纹、startup 日志和原进程回执。原始私有文件仅留测试机。
- 会话操作偏差另记：开工时 Codex 曾分出三个辅助会话处理准备工作，读到目标提交的会话限制后立即停止；其中一项已开始下载制品。后续由当前测试机 Codex 独立复核原始下载字节并执行实际窗口操作，私有测试工具与最终 Git 交给测试机原 OpenCode。

### 10.6 原测试机人工键盘补验

**在同一 b657363 冻结包的 renderer 故障提示上，默认 Enter 与 Escape 均通过人工验收。** 用户按约定步骤在 Windows 11 本机键盘操作并反馈“正常”。Codex 另行只读观察提示、焦点与窗口切换；没有发送这两个按键，也没有采集键盘事件。

补验前再次核对 §10.1 的原 artifact、产品 ZIP、EXE、build 与 187 份文件，在新合成根 `case-keyboard-renderer` 启动原包。经自有宿主与目标句柄复核，仅触发一次 renderer 故障（宿主 PID 9016，renderer PID 8180 实际 exit 1）。按键前原窗口为 8585356，两次提示均以该窗为 owner，首次显示时均处于前台，默认焦点文本为“保留当前窗口”。

| 用户获示的操作与反馈 | 原生窗口观察（本机时间） |
| --- | --- |
| 首次提示不点鼠标，直接按 Enter；用户反馈正常 | 22:20:58 提示 330590 消失，同一故障窗恢复可操作，没有新业务窗口出现。 |
| 点击原窗口关闭使提示再次出现，按 Escape；用户反馈正常 | 22:21:27 提示 7212074 消失，同一故障窗再次恢复可操作，没有新业务窗口出现。 |

随后还观察到第三次提示消失并保留原窗，未单独归因其输入方式。第四次提示的焦点转到“重新打开最后保存的档案”后出现新工作台 18745994，随后正常关闭。launcher 与独立进程句柄均记录宿主 exit 0，自有残留 0。seed、故障前、第二次提示消失后、最终关闭后四份完整默认／runtime 指纹逐项相同；各阶段均为 49 表、12 份受管文件，task／execution／attempt 为 4／4／4，活动任务 0，integrity=ok、FK 违规 0。未调用实际 AI。

本次补验关闭这份冻结候选的提示键盘项，覆盖一个 renderer 故障场景。普通许可不复用、ack／fault 精确交错以及冻结内部身份与退休顺序仍按 §10.5 的边界记录。原始只读窗口事件、提示截图、合成数据、完整指纹及两份退出回执留在 `kg6b657/case-keyboard-renderer`，独立核对结果留在本机 ignored 的 `private-evidence/b657-kb1106/independent-result.json`。
