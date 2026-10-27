# D4：E06／E07 图文执行、视觉候选与原子采用独立核查

更新：2026-10-27。状态：E06／E07服务层限定工程核查通过，R01–R12关闭；R13误判撤回。

## 1. 授权、实现身份与范围

用户授权原OpenCode会话以Go套餐DeepSeek V4.1 Flash max实施E06／E07，Codex独立审核、交回修复直到通过，最后正常提交推送；必要真实AI测试及既有配置检查已允许。基线541bc82，开工前干净，分支codex/desktop-v2-foundation。

唯一实现会话ses_ead8af71dffeJphI1NOWg4jZgI，CLI2.1.4，build，opencode-go/deepseek-v4.1-flash#max；三次CLI运行均接续同一session，后两次用于已撤回R13及恢复，无fork／子代理／新分支。OpenCode写实现、测试与验证脚本；Codex写规格／核查、执行独立验证和Git。Go只用于实现者套餐，应用仅接DeepSeek官方与MiMo标准API。

交付限服务层：固定图文input／claim／worker协议、候选持久化及审核metadata、来源复核、整份／按栏原子采用。未实施E09／E10观察HTTP会话与页面、E11／E12 Word／宿主或E14整包；不把本片写成完整A01–A22、教师产品或发行验收。

依据：[产品C1–C33](../specs/desktop-game-observation.md)、[工程§7–§8](../specs/desktop-game-observation-engineering.md)、[观察Contract§6](../modules/game-observations.md#6-ai-投影候选与采用)。[实现者结果](desktop-game-observation-ai-result.md)是停写交接窗口，本报告记录其后的独立结论。

## 2. 冻结身份与核查方法

证据根：C:/Users/yw980/AppData/Local/Temp/kgm-observation-e0607-20261027-aa633c2e，指针为%TEMP%/kgm-observation-e0607-current.txt。OpenCode使用opencode-evidence，独立证据在codex-independent；TEMP／pytest cache／pycache与持久证据分开。统一desktop/.venv-d1/Scripts/python.exe：CPython3.14.7、Windows x64、标准GIL；旧3.12保留。

原会话基线4321消息／max seq37240，旧idle成功不算本片完成。最终本片新消息807／max seq44203，766条assistant全部为opencode-go/deepseek-v4.1-flash、max、build；三次CLI exit均0，最新finish=stop／idle=succeeded，child／fork0、inbox0、pending0，详见session-final.json。codebase-memory按项目身份、index_status、search_graph／trace_path及15路径coverage定位；metadata_changed时回读源码与diff，图谱不作为完整性证明，别名连边亦以实际import为准。

源码manifest：基线351份，加入5份新源码／测试后356份；改动为10份生产文件与6份测试／夹具，其余原值。未改迁移、依赖锁、ARCHITECTURE.md、前端、宿主或打包脚本。source-final-before.json记录R12最终状态；R13撤回后全部356份再次匹配，再执行最终冻结回归，结束须仍无变化。

| 生产文件（backend/app/local/） | 当前磁盘SHA256前16 |
| --- | --- |
| observation_ai_inputs.py | cbcc14e333132077 |
| observation_ai_service.py | c4da3138dafd5910 |
| ai_executor.py | 5fc43f167c33b9ab |
| ai_task_service.py | c364f0a1e5a2bf32 |
| ai_transport.py | 3bafc79058264f41 |
| ai_worker.py | 01aff7c868d25949 |
| prompt_bundles.py | 4e3a325dcafe868b |
| observation_assets.py | 0664ac293d7031fe |
| observation_service.py | a3211225cd50c2b9 |
| observation_history_service.py | e6fb4aa43be48895 |

新增测试／夹具为obs_ai_workers.py、test_observation_ai.py、test_observation_ai_contracts.py；调整原观察prompt测试、w3_tls.py及worker.py。完整hash在manifest，表内是Windows工作区字节摘要，不是Git归一化blob摘要。

## 3. 回修与独立结论

| 项 | 最终行为及证据 |
| --- | --- |
| R01 视觉授权／旧文本保护 | 父claim核来源、任务、schema、contract、模型能力；worker先用原1MiB上限接小header，非法daily视觉头不等body即拒绝；旧文本仍单帧1MiB。初次1.515秒未拒绝的反例保留r01-invalid-header-inflight-probe.json，修后实际spawn专项通过。 |
| R02 有界材料与完整预检 | 原图／工作图hash及解码核验在写锁外；工作图同句柄stat／有界读取，图数与增量预算先拒绝；共享编码器计UTF-8／JSON／Base64／HTTP及两帧完整字节。 |
| R03 官方视觉能力 | 精确官方host／HTTPS／端口／prefix和已适配模型；错域、Token Plan路径、未知模型拒绝，生产DNS／peer／TLS／重定向政策保持。MiMo真实账号未验。 |
| R04 固定input与执行版本 | 成功保存draft冻结wire与内部context、warnings／缺项及有序照片／派生引用／参数；FK指稳定record。claim取最新有效配置，execution固定实际config/default/personal/contract及模型；retry_wait沿旧execution，schema不兼容暂停，旧工作图不重建。 |
| R05 同候选来源证明 | operation只作失效／顺序链，按rowid提交顺序并结合version provenance、完整candidate输出及每目标hash；人工／他候选同文不冒充，手改／auto往返／恢复清除受信。 |
| R06 强回执／完整绑定 | 采用读写观察域operation；回执优先token／材料／当前配置。token原子reservation、包括BEGIN失败在内均释放、提交消费；写锁内重新核完整candidate/input绑定。另一session在外检与BEGIN之间改未选候选栏的反例已修，见r06-candidate-gap-probe及专项。 |
| R07 采用材料并集 | 核冻结input与当前稿照片并集；新增当前照片缺原图／工作图、外检后替换均不可review覆盖。r07-current-photo-probe原反例保留，最终专项拒绝。 |
| R08 持久审核定位 | metadata v1绑定candidate／schema／contract／目标hash，保留前缀cr:；偏移／领域／hash错误降级总体提示。64片段／每片200字符／片段JSON64KiB预算；20,000片段／3,152,597字节放大反例已收敛，完整正文保持。 |
| R09 上下文准入 | 实际工作图尺寸、实际发送文本及保守预留进入准入；600张高分辨率MiMo图即使字节很小也因上下文拒绝，不静默删图。 |
| R10 保存与历史分判 | draft变化才增revision；最终aggregate相对最近保留节点有变才留节点，无首节点则首次留。auto待保留内容已等于候选也须留历史；同candidate/version无变部分采用只合并新目标证明。已采用目标手改后旧候选仍不得迟到覆盖，即使latest仍等于旧输出。r10-adopt-pending-history-probe及正反例通过。 |
| R11 旧daily响应回归 | 首次自测实际1 failed／710 passed；旧HTTP因额外source字段触发strict响应失败。修为仅观察来源返回扩展字段，不放宽旧schema；最终全local及桌面复核旧链。 |
| R12 真实候选质量 | 首份真实结果擅自按姓名分台词，并把审核包装写入正文，未采用。仅强化观察运行时协议：subjects姓名不构成行为对应，未知时写共同情境／匿名对话，审核说明只由独立metadata提供，不把补写当事实；保留C11补写。旧bundle／schema／hash未改。修后生成及评价重写已审阅并采用，见§6。 |

R13是Codex误判，未作为交付功能保留：把诊断JSON嵌套转义误读为正文literal换行。直接只读SQLite逐字符计数，首候选goal/process/support实际LF=4/2/5，修后support=4，literal反斜杠n均0。原OpenCode已撤回该轮normalizer、接入、夹具及测试，5文件恢复R12精确hash，356份manifest全部匹配。其间中间稿的literal误改／二次扫描只属于已撤回试验，不能写成应用原缺陷或修复成果；临时证据保留，不重写旧候选。

## 4. 独立验证窗口与保留库

| 窗口 | 结果 | 独立证据 |
| --- | --- | --- |
| 最终冻结全local | 718 passed／693.61秒／exit0，356份前后无变化 | local-all-frozen/pytest.log、run.json；356文件前后摘要 |
| 冻结相关桌面6文件 | 85 passed／6.26秒／exit0 | desktop-frozen/pytest.log、run.json |
| 首次观察专项＋既有prompt | 58 passed／41.49秒／exit0，R12前窗口 | targeted/pytest.log、run.json |
| 完整图文容量 | exit0／67.92秒，两个受控TLS请求均success | capacity/result.json、run.json；脚本d7faf88fd7377903… |
| 分阶段入口干跑 | prepare/generate/status/review/adopt/rewrite/adopt-rewrite／重复generate均exit0；重复只读回原任务 | dryrun-1至9日志、staged-dryrun |

此前独立717项窗口在R12修正期间、718项窗口在已撤回R13试验期间存在磁盘改动，保留其结果和source_changed，不作为最终冻结证据。OpenCode的714项全量、59项R12专项及142项daily自测按其窗口记录，不能冒充Codex最终结果。R13试验的61／62项自测不列入交付通过计数。

V01–V05均核到实际边界：真实子进程提交采用后os._exit(17)，父进程重新prepare并按同请求回执重放；实际ai_worker＋受控TLS验证发送；完整父／worker／解码峰值及字节边界；真实SQLite末阶段全部flush后触发失败；真实入口先全合成干跑，再由Codex分阶段控制真实调用。

targeted/retained保留4份一致库／照片：r09-adopt-late-fault、r09-adopt-retry、v01-cold-restart-after-commit、v01-cold-restart-replay。Codex重新只读检查均integrity=ok／FK错误0，每份3个材料文件全部hash匹配。晚阶段hook已见revision4／history2／provenance1／operations4／audits4，故障后全部回到revision3／history1／provenance0／operations3／audits3；同token重试再一次完整提交。冷重启前后revision4／history2、task1／attempt1及材料保持，未增加AI调用。证据retained-independent-check.json及各summary／marker；不能把同进程dispose重开当冷进程证据。

## 5. 容量与参数

仅现有两家官方标准API适配，不新增图床、Files API、服务、依赖或发行组件。2026-10-27核对[DeepSeek视觉](https://api-docs.deepseek.com/zh-cn/guides/vision/)、[DeepSeek模型](https://api-docs.deepseek.com/quick_start/pricing/)、[MiMo图像规则](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/multimodal-understanding/image-understanding)及[MiMo模型](https://mimo.mi.com/docs/en-US/quick-start/model)。文档核对不等于MiMo账号实测通过。

视觉协议chat_completions_vision_v1：小header＋body两帧合计36MiB，完整HTTP40MiB（body上限再扣8192字节头部预留），最多600图，attempt180秒，连接仍10秒；旧文本1MiB／120秒不变。预检保守计4096字节认证头及deadline位数，实际发送再核。上下文按DeepSeek每图1024 tokens保守上界、MiMo实际工作图尺寸公式、实际UTF-8文本字节上界及8192输出／协议预留，对照1,000,000上下文；不是实际token／费用预算，不设计预算UI。

原256MiB组合候选失败：父229371904＋子193331200=422703104字节，约403MiB，保留capacity-evidence4.json。中间窗口unknown/provider_error、0请求、只见progress、缩图导入路径、脚本错误均不计容量成功。已修HTTP上传仍继承连接timeout的问题，发送前改用剩余attempt期限；受控接收fixture改线性有界接收，生产TLS政策保持。

独立成功容量：600张不同256×256 JPEG，原字节合计26622306，600条独立Base64。实际两帧35527170字节、HTTP请求35550280、body35550063；主请求及与完整解码并发的第二请求均success／四栏，两个请求各一次、hash相同。IPC精确37748736通过、+1拒绝；601图及MiMo估算2465795超1M拒绝。

用8000×5000、40MP受管JPEG调用本片实际inspect_managed_asset完整解码，未用会draft缩图的导入路径。父／worker／解码者独立峰值302194688／191791104／241020928；受控重叠保守和391114752＋192065536＋241319936=824500224字节，约786MiB，低于核定的1024MiB组合验证阈值。解码进程是临时测量工具；不是新增产品组件。该阈值不是硬RSS、整个应用或任意并发承诺，不改变E03照片策略。

采用内部参数64 token／600秒TTL；metadata v1的64片段／200字符／64KiB为定位预算，不裁正文。这些实际参数已归并[工程§7–§8](../specs/desktop-game-observation-engineering.md)。

## 6. 真实DeepSeek闭环与保护数据

既有G17隔离DeepSeek配置v1、https://api.deepseek.com、deepseek-flash、has_secret/configured/ready=true；默认教师根无库，MiMo根v0无密钥。只读读取配置／密文，在受保护通道中内存解密并注册到全新合成根，不复制原业务库，不回显明文，不上传真实儿童照片。原DB与凭据共5个文件前后hash相同，见existing-config-readiness.json、protected-real-source-before.json及live-closure-independent.json。

本片真实供应商请求共4次（与G17历史调用分开统计），均明确由Codex控制；不是“每次都成功”。

| 请求 | 结果与处理 | 实际attempt耗时／已报告tokens |
| --- | --- | --- |
| 首generate | HTTP200／succeeded；质量R12未通过，candidate jfwKGHyzIvh1sUC1uVgZ2A／ce4e52d4…保留、未采用 | 15078ms／2712 |
| 修后generate | HTTP200后未取到完整结果，outcome_unknown／provider_error；重开executor后仍1 attempt，未自动重放；具体上游／网络原因未定 | 28641ms／未报告，不能记0 |
| 显式retry | ack_duplicate_cost=true，经既有retry服务单次重试成功；5wTzMdK89pESunHc0GQqAA／f5dbff11…，姓名／审核包装核对通过 | 20766ms／4385 |
| analysis_evaluation重写 | HTTP200／succeeded，仅五领域目标，oFkTyA7KqQUpaIc3uml9lw／dab8f6de…；人工核对后仅采用评价 | 7656ms／2605 |

真实闭环为生成→审阅→四栏preview eligible、无需额外review_decision→采用revision5／history2→评价重写→审阅→单目标采用revision6／history3→重开status。最终aggregate223a234fa3f2fa3d879077a3e79f2b69ebc27b92b6ef97b3074608b2c9aec3f3；重新从draft＋有序原图manifest计算匹配，最新history相同。未选三栏及所有其他资料逐值保持，照片集合／顺序／说明完全不变，六个原图／派生文件hash匹配，provenance2、task2、candidate2、attempt3（另初始根1次），integrity=ok／FK0。读取／采用／重开未额外调用AI。

素材只有两张48×36纯色合成JPEG及少量共同搭建文字，验证真实协议、保守共同情境、五领域结构与采用闭环；不足以代表真实儿童照片效果、多人物复杂对应、丰富补写质量、任意供应商限额或教师体验全部通过。MiMo缺凭据，仅官方资料与合成适配／边界核查，真实调用0次；本片不需要重新询问已存在的DeepSeek配置。

## 7. 结论与后续边界

最终冻结718项全local、85项相关桌面、容量与保留库复核、真实DeepSeek闭环均通过，最终356份源码／测试摘要前后无变化。R01–R12按上述证据收口，R13撤回，无保留格式清洗。

后续E09／E10页面／列表、E11／E12 Word逐页／WebView2／宿主、E14冻结资源／许可／新包未启动；完整A01–A22、教师体验、Win10／WPS／干净机器、其他DPI／显示器、跨设备、真实更新安装／发行源／4551、签名、WebDAV及D2／D3既有未验保持。不恢复微软提交、不动旧体验库／OneDrive原件／旧包／远程资源。

本轮正常提交推送仅包括相关源码、测试与归并文档，不amend／强推／重写历史，不上传合成库、照片、日志、密钥或安装包。唯一接续入口仍为[当前任务](../tasks/current.md)，完成后缩为结果与边界，不新增旧提示词归档副本。
