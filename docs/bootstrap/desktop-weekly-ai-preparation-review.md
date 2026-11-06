# 桌面周计划 Q5/Q6 文档准备核查

2026-11-03适用范围更新：以下保留11月2日准备轮的基线、metadata、检查数字和当时“目标未验”身份。开发机现已快进至`0285a7c`并合并本地文档；[另机测试收口](desktop-weekly-target-test-closeout.md)新增限定目标／指定Word及教师整体接受，两项实现修复属于远端提交，不是本次本地实现。下文旧候选未验与HEAD未变结论只指准备轮，不覆盖本次拉取；本准备轮止于文档。Q5/Q6 随后的实现和实际验证分别见[开发机核查](desktop-weekly-ai-review.md)及[目标机核查](desktop-weekly-ai-windows11-target-review.md)。

更新：2026-11-02。范围：用户明确要求并行准备工程合同、假供应商验证矩阵和文件分工，继续原生OpenCode／Command Go的DeepSeek V4.1 Flash max，由Codex最终审核更新文档，暂不业务实现和真实应用AI。[工程合同与分工](../specs/desktop-weekly-ai-engineering.md)、[验证矩阵](../specs/desktop-weekly-ai-validation.md)为本轮交付，执行入口仅[current](../tasks/current.md)。

## 1. 基线与原生责任

开工分支`codex/desktop-v2-foundation`，HEAD `d6ff4b753e3facdd440edf5cd9d179e9b36542ed`，开始时工作树干净。Codex先将current切为本轮准备范围，再冻结681条已跟踪文件的SHA-256基线；开发与依赖保持现有CPython3.14.10／Windows x64／标准GIL及锁定版本，不装工具或升级依赖。

| 原生会话 | 本轮责任与边界 |
| --- | --- |
| OpenCode A `ses_ead8af71dffeJphI1NOWg4jZgI` | build／`opencode-go/deepseek-v4.1-flash#max`；只读核对现有AI、周计划与备份接点，起草私有工程提案，再审正式合同；不获源码／测试／迁移／构建脚本或正式文档写权。 |
| Command Go C `8cf528de-8773-4a06-9cc5-31e96fab515f` | `deepseek/deepseek-v4.1-flash`／effort max；独立起草私有假供应商矩阵及分工建议，再核对正式矩阵；同样只读源码与自有私有报告。 |
| B／D | 本轮未启动。工程§8是拟议后续分工，不是当前白名单。 |
| Codex | 独占正式文档，核对产品与源码、裁定合同分歧、维护矩阵／入口及执行文件／模型metadata审计；未成为业务实现者。 |

A/C原生初稿实际并行，A初稿／正式审阅两轮、C初稿／差异复核／正式稿复核三轮均自然CLI0；未fork、另派子代理、换模型或接管对方文件。最终metadata完整覆盖本轮起点：A新增72条assistant均build／OpenCode Go Flash max；C累计26次model_request_end均Command Go Flash max。A一次原生自动上下文压缩也为同一Flash max，agent空字段按压缩消息单列，不冒充实现者切换；两次agent-switch均build→build。旧轮审计器“零compaction”的严格规则在interim命中，保留原结果；按本轮未禁止同模型压缩的实际合同另核后通过，不隐去事件或换模型。

所有task／report／原始stdout、stderr、exit及脱敏metadata留在新私有根`%TEMP%/kgm-weekly-q56-prep-20261102-r01/`，最终回执`metadata-final.json`。消息数与model_request_end数不是供应商请求／计费次数，二者也不直接比较。旧实施／Git／构建白名单未重放，开发CLI调用与应用真实AI严格区分。

## 2. Codex审核后的合同结论

| 项目 | 最终落点及修正理由 |
| --- | --- |
| Q5三个明确操作 | 游戏组合、所选栏目、材料互不连发；生成候选、采用草稿、明确确认分开。 |
| Q6输入隔离与部分成功 | 未采用A初稿单个多栏task方案：每栏独立子任务，一次勾选请求以原子回执映射n份冻结input/task；避免重点／家园搭班输入出现在环境／习惯模型调用。子任务成功候选保留，失败不自动补发；明确所选候选的采用仍一次事务全有或全无。C初稿的整组输出全失败假设据此调整，正式矩阵WAI03／21／29／31分别覆盖。 |
| 来源身份与重点区域 | 后片按已决Q5及模块Contract处理本人日来源与不足的AI补充，配置只作地点／范围／指导依据，绝不伪造完整游戏目录或日引用；没有把首片重点区域只接受日引用永久沿用为AI片限制。模型仅拿本次input的opaque句柄，真实ID／版本在服务端manifest。 |
| 材料上下文与证据 | 继承旧材料规格§2的非冲突“明确focus”门槛，无focus为MATERIAL_CONTEXT_REQUIRED、0排队／发送且保留原文；旧自动链、账号／owner_epoch不继承。提取／建议按真实位置区分，Unicode位置消歧，非凭差集猜测；无最少条数要求。 |
| 内容schema与迁移 | 内容schema1原样保留，真实新写入使用schema2，无修改不造版本。直接源码发现LocalWeeklyPlanContent实际为schema_version=1 CHECK，纠正A初稿“内容schema2无需DB迁移”的说法；0008必须同时扩周内容CHECK、AI来源／任务及prompt bundle约束，保留旧值和复合键。 |
| 确认与Word | 采纳最小兼容方案：确认外层envelope1及宿主／manifest保持，嵌套content严格分schema1/2。旧确认JSON／hash不变；材料正文及依据冻结进新确认，Word只输出既有材料栏。未要求重复新生成DOCX的ZIP字节恒等。 |
| 页面与文件责任 | 预览只读，采用后沿既有编辑保存；不新增指导设置。A共享数据／任务／API／迁移，B纯合同／内容，C周页面，D后续备份／快照／宿主配套各自唯一责任；共享接线串行，未列文件不自动获权。 |
| 失败／恢复 | 沿既有发送确定性、有限未发送重试、unknown不自动重发、回执优先、关闭／维护permit与新launch失效规则；按新周身份补矩阵，不借日／观察旧结论。 |

原生提案与二次审阅均是建议，Codex按实际产品／源码归并成一份正式合同。技术分片、preview只读、位置单位和迁移细节属于本轮工程裁定，不把已决Q1–Q6转交用户重复选择。下一阶段G0还须在实际新HEAD核定嵌套schema键／函数签名与精确文件表；本轮不放行实现。

C首次复核主要比较其私有旧矩阵与正式稿，作用仅为差异说明，未当作对正式46项的完整复核；原报告保留。续同会话改为只审正式稿后，五项具体意见已归WAI06／11／19／36／41：缺输入一般建议、缺键与显式null、回执恢复与token失效分开、no-op及混合确认、内容表CHECK升级。Codex核对修订，不将同一旧稿意见反复计为新缺陷。

A正式审阅提出的两个高项已回写：现有配置没有具名游戏目录，故删除config直接游戏来源，仅作为AI补充依据；旧来源快照只含已引用地点，新增任务级完整配置manifest责任。其余准备细节也已补齐：schema2精确键、句柄约束、组摘要规则、普通PATCH／刷新保留、只读预览、basis容量、D阶段一致、A读DB/B纯投影、null及空items明确采用才清空、同批次多候选、旧5种加新6种prompt类型，以及采用事件列／复合FK。所有意见止于合同修订，没有实施代码或伪造测试通过。

## 3. 结构核对与验证边界

使用已安装codebase-memory的Verify流程：项目`C-Users-yw980-code-kindergarten-manager-next`，ready；前14路径在generation `2026-11-01T23:19:39Z`有界核对，含create_task双向一跳追踪。追加config_service／weekly_plan_sources两路径时索引已自动刷新为`2026-11-02T04:42:52Z`；共16路径均无已记录gap，但freshness为metadata_changed，已回读对应声明／约束／关键分支并检索后备。未手动reindex、不声称完整影响闭包；图谱只作导航，源码为事实依据。

准备核查只做Markdown引用、矩阵编号／NOT RUN标识、文件责任表、源码基线与原生metadata复核。**没有执行假供应商矩阵、业务回归、应用窗口、迁移、构建、EXE/helper、真实应用AI或远端操作。** 原生CLI0和文档检查不代表Q5/Q6实现／自动／目标／Word／教师通过。

最终metadata和工作树复核回执在本轮私有根记录；正式文件结果收口后不为回填本文件自身hash循环写入。未提交或推送，未改分支／HEAD／Git index。

最终文档核查通过：681条已跟踪基线对比只有本轮6份既有文档变化，另新增3份规格／核查文档，合计9份；无业务／测试／迁移／构建文件变化或删除。Markdown目标引用、空白检查及WAI01–WAI46连续唯一编号／NOT RUN标记通过；HEAD不变、暂存区空。闭合后的来源SHA回执为`document-audit-closed.json`，仅证明本轮文档和源码范围，不证明矩阵或产品运行。

## 4. 保留的候选与下一步

现交用户验证的Windows候选仍是[原GitHub制品](desktop-weekly-windows11-review.md)，来源`57806b2a8d23639fdb7e371b7928d948c82a96ea`、run41360367631／attempt1、build_id `0b56217d-026a-428e-a5d8-1b9f36960326`、schema0007。本轮文档不会改变已下载字节或成为该包的新来源；目标机运行与新Word教师体验仍待实际回执。固定r03目标1及八份指定Word教师确认继续保留原身份。

用户按现有另机手册测试；本轮停在Q5/Q6文档准备。实现先评估目标反馈，通用保存／恢复／关闭缺陷优先，再按明确授权与新G0放行。真实应用AI、候选构建、Git、签名、WebDAV、安装更新和发行各按当时实际范围，不从准备工作推导启动权限。
