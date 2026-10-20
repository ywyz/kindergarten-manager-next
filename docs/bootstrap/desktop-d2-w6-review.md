# D2 W6 Codex独立工程核查

更新：2026-10-19。用户明确授权OpenCode继续W6，仍使用Go套餐DeepSeek V4.1 Flash；Codex已完成独立核查及交回修复。**W6在当前Windows 11合成环境的导出、无AI降级与完整包工程核查通过，R01–R09关闭，结论及未验边界见§9。** Word新样本逐页、真实睡眠、真实AI及教师确认仍待验，不宣布W6全部验收、D2产品或发行通过。

## 1. 范围与边界

- 有效入口：[当前任务](../tasks/current.md)；依据[工程规格§6–7](../specs/desktop-ai-engineering.md)、[产品规格](../specs/desktop-ai-daily-plan.md)及[W5最终核查§8](desktop-d2-w5-review.md#8-最终工程结论w5限定源码集成通过)。W1–W5既有结论保持。
- 只实施W6必要导出接通、相关测试及构建/验证脚本；OpenCode是唯一实现写入者。Codex负责规划、审阅文档及独立执行验证，不另起实现者或子代理。
- 当前分支`codex/desktop-v2-foundation`，保留既有未提交/未跟踪内容和原教师体验资料；自动验证仅独立合成根及凭据环境，显式`APP_DISABLE_DOTENV=1`。
- 不执行应用真实AI、WebDAV、旧云端/远程修改、发行、commit或push；不安装/升级依赖。G14人工逐页结果、G17真实供应商、G18教师确认及真实睡眠与工程自测分别记录。

## 2. 开工核查

本轮已依`codebase-memory`技能调用`list_projects`、`index_status`与`get_graph_schema`：图谱恢复可用，项目`C-Users-yw980-code-kindergarten-manager-next`，ready、indexed_at=`2026-10-18T23:59:49Z`。后续相关符号和路径覆盖需继续核对，不以图谱ready替代当前未提交源码阅读。

证据根`%TEMP%/kgm-d2-w6-codex-20261019-123909`，436文件开工hash及完整Git状态已保存。OpenCode专用会话`ses_ead8af71dffeJphI1NOWg4jZgI`，CLI运行日志`opencode-run1.jsonl`；脱敏导出`opencode-session-prefix.json`的实际模型元数据为`providerID=opencode-go, id=deepseek-v4.1-flash`，与用户指定一致，不只根据CLI参数推断。

图谱`prepare_export`查询及双向一层trace定位真实API调用和读取适配。`check_index_coverage`返回generation=`2026-10-19T04:39:19Z`，相关7个源码路径均`metadata_changed`，测试范围仅记录`__pycache__`排除。已直接阅读export_service、daily_plan_service、ai_provenance、Word映射、构建及相关宿主路径作补充，不以图谱结果作穷尽声明。该开工核查不作通过结论。

## 3. 实施期间预审发现与交回记录（最终关闭见§9）

- R01／G15：`desktop/d1_main.py::build_runtime`当前将AiExecutor导入、构造和start放在整个宿主启动失败的外层异常路径内；抛错后runtime释放、主窗口不启动，不符合执行器启动失败时手工路径可用。已通过同一OpenCode会话steer交回：必要宿主降级、明确AI不可用、确保旧任务不会重新发送且未确认worker仍不得放行运行锁/关闭。最终须核对真实可达分支与相应测试。
- 构建预防项：旧`build_d1.py::build_frontend`含`npm ci`，本轮不得运行该安装路径。已提醒使用已有依赖及独立W6输出，不覆盖D1/R18包。不是已发生的违规安装。
- R02／R01修复初稿：`_start_ai_executor`的import仍在try外；“start失败”注入在真正start前raise，未覆盖Thread.start赋值后抛错导致未启动thread.join失败；helper未返回时外层拿不到部分executor，dispose未确认后仍可能走无条件runtime.dispose释放锁。已即时交回同会话，要求真实失败注入、清理所有权及锁的证据。此为中途初稿发现，不替代最终核查。
- 独立开工Word基线：`baseline-word/`，109项Word生成/映射/读取测试，9.377秒，实际exit0，完整stdout/stderr保留；不代表W6新增闭环或新包已通过。
- R03／同源验证器初稿：Codex实际执行新`d2_same_origin`对同一份源码与已加载模块指纹比较，`word_export_mapping`两边不同、带future的`export_service`两边相同；证据`same-origin-prefix.json`。比较器自身future annotations被默认compile继承，错误改变了无future源文件。已交回显式`dont_inherit=True`及稳定全元数据比较核查，不能删行号等来掩盖误差。
- R03前缀修复复核：`same-origin-prefix-fixed.json`两个代表模块的源/加载指纹均相同，actual exit0；最终冻结包全范围仍待验。
- R04／验证代码初稿：新闭环测试含nsmap占位断言、将第二计划ID拼入待查文本的恒真断言、无用lambda；所谓restart_api仅重建同runtime上的API。窗口合并setCustom(date2,date)与真实(from,to)签名相反。已交回移除占位、用真实DOCX结构与冷重启证据及正确驱动日期核验，不改生产校验迁就测试。
- R05／G15验证初稿：网络测试先登记后start，冷启动恢复可能在任何网络尝试前直接paused，而测试接受paused/unknown；使用fake_worker且未覆盖该分支HTTP/冷重启/导出。凭据与执行器API分支也缺重启后的闭环；无配置窗口分支直接赋True。已交回要求真正网络故障尝试、reason/发送证据和四分支完整降级证明；不能把缺口写成已通过。
- R06／G16资源探针初稿：同样先登记后start；主入口补流后再以stdout/stderr为None判断无控制台；资源阶段prepare前缺统一入口校验；finally未核对executor退出就释放runtime；Job分配检查把child_started当替代。已交回按实际事件/启动状态和进程收口收紧。最终包尚未生成，不把此源码初稿当包通过。
- R07／窗口验证器初稿：重启common切片替换的是CA值而非out，且不应给普通重启phase注入provider；损坏凭据忽略label并遍历首个文件、第二launch又换凭据根；找不到回执文件时回退第一份DOCX；checks混入状态字符串并有无效占位。已交回显式参数、同根精确故障、严格文件匹配及完整布尔期望集合，避免测试证据误通过。
- R08／首轮真实源码窗口产品失败：`opencode-source-window-prefix1.json/.log`保留实现者首次完整窗口报告（根`%TEMP%/kgm-d2-w6-window-bf1b9b6c`）。执行器明确不可用的结构化503被前端当“提交结果未知”，留下pendingCreates/panelBusy，而后端在回执优先查询后、任务登记前确定拒绝。已交回仅对明确未提交代码收敛、保持普通5xx/丢包/截断202未知保护，并补首次/同键重传及手工离开关闭证明。必要前端改动属于W6 G15。
- R08并发口径补正：首次明确503不得新建pending；已有旧未决时，同键重传503不能单独证明原请求不再并发提交（peek回执无写屏障），旧key/body必须保留，最终由回执恢复。已补正交接，不要求为此改后端事务；不能一概把该错误当作清除历史unknown的依据。
- R09／专用验证入口：源码`_validate_synthetic_entry`在未传port、executor_fail且缺data时直接return，W6 selftest能落到`LocalRuntime(None)`默认教师根。仅源码核查，未向真实根执行反例。已交回：所有W6专用phase及w5-ui无论是否注入都在构造/prepare前要求显式data；w6-ui-verify允许无provider但禁止注入；resources相同校验。以spy/独立环境证明失败前零prepare/零建库，不以用户根验证。
- 首轮窗口也暴露验证器问题：None执行器缺worker-exit记录；credential-setup触发AI后pending卡住关闭；同值输入不变脏；固定期望与实际key前缀不同。全部交回修，不删除检查以求通过。首次G14窗口及重启子检查虽为true，仍不作为整体W6或Codex独立窗口通过。

## 4. 独立后端回归（桌面实施期间冻结后端）

`independent-local-pass1/`：Codex独立运行`python -X utf8 -m unittest discover -s tests/local -t . -v`，**477项／354.265秒／实际exit0**；含新增G14三个及G15四个用例。完整stdout/stderr及实际exit文件保留。显式`APP_DISABLE_DOTENV=1`、独立LOCALAPPDATA与数据根，清除继承KGM变量，不使用原体验数据。

运行前后相关后端源码/本地测试/迁移及`desktop/d1_host_api.py`哈希零变化（`source-before.json`与`source-changes.json`）。OpenCode同时仅推进桌面/构建验证脚本；后端最终交付仍须与此稳定快照逐项比较。该结果不等于桌面、最终包、Word人工、真实AI或D2整体通过。

## 5. Word页面工具边界（尚未通过）

Codex将首轮源码窗口的单日/合并DOCX按原字节复制到`word-prefix/`（仅前缀样本，不作为最终包样本）。使用已安装computer-use技能的`@oai/sky`工具，首次启动Word报`GetCursorPos 0x80070005`，刷新后重试启动成功；仅看到Word起始页。激活并捕获窗口报`IGraphicsCaptureItemInterop.CreateForMonitor 0x80070057`，刷新返回的窗口并按恢复规则重试一次仍失败，遂停止页面输入。

`word-page-ui-attempt.json`记录此次尝试；没有打开或目视接受任何DOCX页面，没有操作原用户文档。不能将OOXML结构检查、Word启动画面或旧D1人工页验冒充W6页面通过。工程验证继续，相关新样本逐页目视与用户确认仍待补。

## 6. 实现者源码窗口及首包前缀（不作最终通过）

实现者`source_window_report_run3.json`的源码窗口自测ok=true、missing/failed/extra均空；根`%TEMP%/kgm-d2-w6-window-be0fd4ca`。G14窗口/重启及四类G15均已跑到，11项宿主/入口自测也通过。仍待Codex最终稳定源码的独立复跑；不得混成独立证据。

第一份完整D2包已构建（日志`%TEMP%/opencode/kgm-d2-w6-opencode/build_d2.log`，约55秒；首包EXE SHA-256 `913452ceb9e946c0123fc21418133783fefa3b7bdb045aecb70367ac71e2f71b`）。首个包验证脚本在执行EXE前即因`exe[0]`为str却取`.parent`而AttributeError，不是冻结应用成功或失败的证据。完整报告/log副本保留为`opencode-package-prefix1.*`，原包复制根`%TEMP%/opencode/kgm-d2-w6-pkg-a999088e`；不得以构建成功当G16通过。

Codex额外直接读取首包CArchive/PYZ，不依赖包内自报：`archive-prefix.json`检查54个归档项目模块与当前源码严格结构等价（仅忽略co_filename，保留行号/常量/全部代码元数据），54个模块一致；实际入口`d1_main`与当前仍在修改的源不一致，符合首包尚未随资源探针修复重建的状态。最终包必须重建并对54模块及真实入口重新检查；不将该前缀当最终同源通过。

## 7. 独立前端核查（桌面实施期间冻结前端）

`independent-frontend/`：Codex独立`npm run typecheck`实际exit0；`npm run test:d1`原D1逻辑＋60项D1组件＋73项D2组件全部通过、实际exit0。包含R08首次明确拒绝不产生pending、旧unknown同key重传拒绝后保留原上下文并通过回执恢复，普通丢响应/服务错误/截断回包保护回归仍通过。

前后源/测试及构建配置hash零变化（`source-before.json`、`source-changes.json`）；完整stdout/stderr与两个实际exit文件保留。最终源码还须与该快照比对；这些是组件/受控API层证据，不冒充最终包窗口或教师确认。

## 8. 最终稳定源码、独立桌面与整包核查

OpenCode交付后停止全部实现、测试、构建及验证器写入，Codex独立执行下列检查；不是重述实现者自测。证据仍位于`%TEMP%/kgm-d2-w6-codex-20261019-123909`。

| 独立检查 | 实际结果与证据 |
| --- | --- |
| 后端全local | §4的477项，354.265秒，exit0；最终132个相关文件与运行前快照仍零差异 |
| 前端 | §7的typecheck、原D1逻辑＋60项D1组件＋73项D2组件，均exit0；最终24文件与快照零差异 |
| 桌面回归 | `independent-desktop/`，`python -X utf8 -m pytest tests -q -p no:cacheprovider`，168项／5.84秒／exit0；2条FastAPI/Starlette测试依赖弃用警告，不改依赖 |
| 最终整包真实窗口 | `independent-package/report.json`，130个固定预登记检查严格为true，missing/failed/extra全空，主进程实际exit0；所有资源、G14、G15和W5子阶段实际exit0 |
| 归档直接读取 | `archive-final.json`及实际exit0文件；Codex以PyInstaller CArchive/PYZ直接读取54个项目模块及真正`d1_main`入口，对照当前源码全一致。仅忽略`co_filename`，保留行号、异常表、flags、常量及全部代码结构，不只比较包内另行import副本 |
| 最终源码稳定性 | `final-scope-and-stability.json`：后端132、前端24、桌面及整包各201文件快照均零变化；开工基线无文件丢失，未改迁移、依赖／锁、Word映射／模板或ARCHITECTURE；既有未提交内容保留 |

最终包为`build/desktop-d2/package/KGNext-D2Verify/`，EXE 15,048,169字节，SHA-256 **`56346c0ac1d874bbf00e947739a40c005f4a2a611b20d6fabf1a7d35a89fafb2`**。完整包182文件，报告清单hash为`84fbb22f66f14fbbffc5c6fe4c63810855c0fbbbc68571c608ff902f285b1f1d`。这是目录式验证包，不能只复制EXE。

独立包复制根`%TEMP%/opencode/kgm-d2-w6-pkg-b5f78c17/Kg 中文 %# 名/KGNext-D2Verify/`；由Codex独立调用验证器创建，路径中的opencode不代表本次独立运行由实现者执行。仓外cwd、清除PYTHONHOME/PYTHONPATH及继承KGM变量、仅系统PATH，不传源码frontend覆盖。包内前端、模板、迁移与Alembic配置均核对；CPython3.14.7／x64／标准GIL、PE GUI子系统2且没有控制台窗口。两次资源启动、单一迁移head、prompt快照、AES-GCM／DPAPI、真实本机TLS、冻结spawn、Job分配与worker确认退出通过。包运行时48模块指纹亦一致；独立归档扫描补足54模块和真正入口。

G14包窗口经过真正受控TLS子进程生成候选、预览修改、采用、适龄采用、教师手改、保存、原生单日及合并导出；该阶段provider split=1、adapt=1、other=0。新进程重启后原模型基准和手改正文保持，原生重导出且provider无新增调用。G15无配置、损坏凭据、真实线程启动失败、关闭端口网络失败均保留手工保存／导出；网络分支实际为failed，不把未发送的paused冒充网络尝试。后端专项还覆盖各分支冷重启后内容与导出。W5在同包再次覆盖三类候选与关闭保护，split/other/adapt各1次，最后在途适龄请求落为`outcome_unknown`，无开放attempt，worker和宿主均确认退出。

Codex另直接检查该独立包新导出的3份G14 DOCX，证据`word-final-inspection.json`，原字节副本位于`build/desktop-d2/acceptance-samples/`。单日／重启单日SHA-256均为`8c40780591c8514ee81ec87aab7ece74afea5f20820d139b6b4bf0d39cd4be82`，合并为`d13052e8972425e94287c8bcf8a5362be6c43491bbc8fe1dc6ed509e3a76af70`。模型未变前缀不红，新增／替换文字红，预览临时文字不泄漏；1／2张表、合并1个显式新页分隔、每块标题居中、署名严格为班级＋教师、39／73个表格文字run的b/bCs均显式false。页数／溢出仍未目视确认；§5的Word工具失败如实保留。

## 9. 最终工程结论：W6限定环境工程核查通过

R01–R09均已修复并关闭：

- R01/R02：执行器导入、构造和真实Thread.start失败安全降级；确认无worker才继续手工窗口。部分启动未确认退出时保留执行器所有权及运行锁，不把不确定清理当成功。
- R03/R06：结构指纹不继承比较器future，不丢行号等元数据；资源探针真实spawn/TLS/Job/DPAPI，正确区分GUI子系统与重定向标准流，逐启动用新请求；另检真正归档入口。
- R04/R05/R07：删除恒真及占位断言，真正冷重启／网络尝试；修正重启参数、精确损坏同根凭据、精确匹配导出回执文件、固定布尔期望集、仓外隔离环境及阶段请求计数。
- R08：首次明确`AI_EXECUTOR_UNAVAILABLE`拒绝不产生新pending；已有丢响应请求的原key/body仍保留，同键503不作为否定原请求的并发屏障。普通5xx／丢包／截断成功响应保护保留。
- R09：所有W5/W6专用验证相位在LocalRuntime构造／prepare前要求显式data，必要provider校验及非provider拒绝注入；反例用spy和独立环境验证，未对默认教师根执行。

本轮授权工程范围完成，当前无剩余W6编码修复。已有W4来源侧表和Word导出路径可正确接通，未为制造改动重构映射／导出服务。OpenCode仍为唯一实现写入者，Codex只写规划／核查文档并执行验证；最终模型与交付元数据见§10。

该结论限定当前Windows 11开发机与合成环境的G14结构/闭环、G15及G16实际覆盖。**W6的Word新样本逐页目视与用户确认、G13真实系统睡眠、G17真实供应商兼容、G18教师体验仍待验。** G12/G13包内已覆盖的窗口交错见§8，不泛化成全部分支通过；干净机器、Win10、WPS、其他DPI／多显示器及发行再现性保持未验。没有应用真实AI、WebDAV、旧云端修改、发布、commit或push；不把工程通过写成D2产品／发行通过。后续从[唯一当前任务](../tasks/current.md)接续，保留原体验数据及全部失败证据，不重验已关闭的微软拼音。

## 10. 实现者交付与模型审计

实现者结果为[W6实现结果](desktop-d2-w6-result.md)，自测及未验项单独记录；最终源码窗口自测75项、包自测130项均通过，不能替代§8的Codex独立复跑。实现者最终明确停止全部实现／测试／构建／验证器写入，只有交付文档新增。

`opencode-session-final.json`为最终脱敏导出，实际export exit0；`opencode-model-audit-final.json`核对会话顶层及**280条assistant消息全部且仅有**`providerID=opencode-go, id=deepseek-v4.1-flash, variant=default`，没有切换模型。最终assistant的finish为stop，`opencode-active-final.json`为`data={}`，已无运行会话。

控制CLI的长驻`run`最终实际exit1，不能写成exit0：`opencode-run1.jsonl`保留一次中途实现模型流错误`provider.internal / model upstream is unavailable`。之后通过同一会话steer继续工作并交付，最终stop及空active已核对；该退出码与各测试／构建／窗口子进程的实际exit0分别记录。未因实现模型上游错误改用其他模型，未调用应用真实供应商来替代合成验证。完整失败与修复日志均保留。

规格、AGENTS、文档索引及唯一当前任务已同步限定工程结论与待验事项；不新增提示词副本，不改写历史D1或W1–W5的当时结论。

最终交接检查：当前包182文件与Codex仓外独立验证副本逐文件hash全相同，整包清单hash仍为上述84fbb22f…；源码稳定快照再次零变化。8份当前相关文档本地链接目标存在、无尾随空白，受跟踪内容`git diff --check`实际exit0（Git提示既有LF/CRLF转换，不是检查失败）。保持当前分支和既有脏工作区，未commit/push。
