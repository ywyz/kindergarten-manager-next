# 桌面周计划 Q5/Q6 工程合同与文件分工

2026-11-03最终状态：实现及限定审核cd88d9d已提交，源码回归、提示2／旧1兼容、真实游戏／材料生成采用、新候选独立54／59静态通过；本地桌面已补过材料源码闭环、无执行器手工保存／确认／重进及正常退出，新包目标运行未验。接口和追加责任见§9，来源／异常恢复／包身份及最新补验见[实施核查§12–16](../bootstrap/desktop-weekly-ai-review.md)；不将局部证据外推为全矩阵或发行通过。

2026-11-03本轮状态：9份准备文档已整合提交51ec4d3，用户已明确授权业务实现、构建和真实应用AI。四原生新HEAD G0已自然CLI0／metadata核查通过，Codex按§9冻结实际接口和精确责任并放行A/B/D的G1，旧档案保留及备份兼容先于页面。以下11月2日准备范围与拟议表保留历史身份，实际授权／门状态只以[current](../tasks/current.md)为准，不要求用户重复确认已接受教师清单。

原准备轮（2026-11-02）状态：**合同准备，未放行业务实现**。产品依据为[周计划§9及Q5/Q6](desktop-weekly-plan.md)，Q1–Q4接口保留于[首片工程](desktop-weekly-plan-engineering.md)。本轮仅原生OpenCode／Command Go并行只读起草、Codex最终审核与文档整理；[假供应商矩阵](desktop-weekly-ai-validation.md)全部未执行。实际会话、审核修正和边界见[准备核查](../bootstrap/desktop-weekly-ai-preparation-review.md)，唯一派发入口为[current](../tasks/current.md)。

2026-11-03拉取时的历史状态：已拉取`0285a7c`的另机测试收口与五文件最小修复，[目标结果](../bootstrap/desktop-weekly-target-test-closeout.md)已整体接受；当时本文仍为准备合同，尚待后续G0以新HEAD复核导出／错误投影接点，0007现有数据及拟议0008迁移身份不因文档合并改变，当时业务实现尚未放行；之后的新授权与实际门按§9及current。

> §1–8保留2026-11-02准备轮合同及当时责任提案；“本轮未放行”仅指该准备轮。当前实际接口、责任与追加审核裁定统一见§9和执行入口。

## 1. 范围和源码接点

三个独立明确操作：选择周游戏、生成所选周栏目、生成材料。保存、日来源变化、游戏改选和候选采用均不自动连发。先成功保存用户提交的稿，再从服务端已存版本构造输入；生成只产生候选，采用只写新草稿，确认仍是独立明确操作。

不增加供应商、教师流程、同班同步、自动任务链或中间件；应用继续使用已有DeepSeek官方／MiMo标准API配置与凭据通道。开发CLI的Go套餐模型不是应用endpoint或模型ID。本轮不改ARCHITECTURE.md、依赖、模板、真实库或受阻EXE，不启动真实应用AI、新构建或Git。

| 当前源码 | 可审查复用及必须扩展处 |
| --- | --- |
| `backend/app/local/ai_task_service.py`的`create_task`、领取／finalize／恢复 | 创建及多处加载仍区分日计划／观察；不能把周ID塞进daily_plan_id。保留回执优先、permit、发送确定性和原子成功提交。 |
| `ai_inputs.py`、`ai_candidates.py`、`ai_adoption.py` | 现有投影／目标／provenance为日计划专用。周输入、候选适用性和采用由独立周服务承载，不调用日合并函数写周稿。 |
| `models.py`的LocalAIInput／Task／Execution／Candidate | CHECK仅允许daily_plan／game_observation及已有task_type；必须迁移扩展来源分支、FK、唯一索引后才能注册周任务。 |
| `weekly_plan_content.py`、`weekly_plan_service.py` | schema1仅接受日／手工户外、日重点区域，材料强制null；普通PATCH不能建立AI身份或材料依据。 |
| `weekly_plan_snapshot.py`、`backup_validate.py` | 现有确认与逻辑校验固定schema1；schema2、材料依据、采用链和历史共存须同步覆盖。 |
| `frontend/src/d1/weekly-editor.ts`及现有周页面 | 复用实际提交投影／较晚输入保留、未知票据、统一leave与宿主busy/epoch；AI面板不得另造关闭或保存通路。 |

以上是有界接点核对，不声称全仓影响闭包。业务实现前仍须对实际新HEAD及各共享函数复核；现有日／观察测试不转成周AI通过。

## 2. 操作、任务和提交边界

### 2.1 任务拆分

| 教师操作 | 持久task_type | 生成目标 |
| --- | --- | --- |
| 选择周游戏 | `weekly_games_select` | `games`：两个集体槽、一个自选槽及重点区域组成的完整组合，允许真实缺项为null。 |
| 生成所选周栏目 | `weekly_key_week_focus`、`weekly_environment_setup`、`weekly_habit_culture`、`weekly_home_cooperation` | 每个勾选栏目一个独立子任务／候选，模型只收到该栏白名单输入。教师仍只做一次勾选提交，不选择技术拆分。 |
| 生成材料 | `weekly_materials_generate` | `materials`：绑定当前已保存、已明确选择的游戏与重点区域组合。 |

周任务统一`source_kind=weekly_plan`、`source_id=weekly_plan_id`。同次多栏提交在一个短事务读取同一稿／来源快照、验证所有字段和活跃冲突、创建n个input/task并写一个`local_ai_operations`回执，映射`field→task_id`；任一失败整体回滚。不增任务组表或后台依赖任务链，组状态由回执中的子任务实时派生。

组摘要返回各子状态计数，显示状态依次为：任一活跃→running；否则任一outcome_unknown→outcome_unknown；全成功→succeeded；部分成功→partial；全取消→cancelled；仍有paused→paused；其余→failed。始终展示逐栏实际状态／动作，running不能隐藏已发生的unknown，partial不显示为全部成功；摘要不单独持久化。

每个子任务独立成功／失败／取消／unknown；成功候选保留，失败项无候选，不宣称整组成功、不自动补发。可预览并明确采用已有合法候选的子集，一次采用仍须全有或全无。游戏候选以整个组合为一个目标，材料为一个目标；不同操作不混作一次采用。

### 2.2 创建与回执

创建DTO只有`request_id:UUID`、`expected_draft_version:positive_int`；周栏目操作另带`selected_fields`，为四栏键的非空无重复子集。服务端规范化字段顺序用于指纹，不能偷偷补选字段。周归属取路径和会话；不接收客户端profile、来源正文、输入manifest、配置版本或“最新”标记。保存与创建各自有回执，创建失败不回滚已经成功保存的人工稿。

创建结果为`{request_id,operation_kind,weekly_plan_id,draft:{id,version},tasks:[{target,task_id}],replayed}`；重复同键同规范请求先返回原映射，先于当前版本／配置／执行器检查，0新任务。`operation_kind`分别为`weekly_ai_games_create`、`weekly_ai_columns_create`、`weekly_ai_materials_create`；采用为`weekly_ai_adopt`。同键异操作／异体409，不覆盖原回执。AI回执不扩写首片`local_weekly_plan_operations`的固定metadata schema。

所有写操作保留原key／body直至结果可确定；GET404、连接失败、截断回包和执行器不可用并发回包均不能证明原提交不存在，不自动换键。已提交回执只存安全ID／版本／映射，不存prompt、正文、凭据、绝对路径或token明文；采用指纹含原preview_token，回执不需保存该token。

## 3. 输入、依据和失效判定

### 3.1 一致投影

每份input冻结周稿ID／版本／hash、实际来源与配置manifest、task_type、input_schema_version=1、contract_version=1、各目标hash和dependency_hash。业务payload与服务端manifest分开：模型只接业务文本与本次输入内的opaque source_handle；真实profile／plan／content／group／game身份、运行路径、哈希和凭据不发给模型。handle语法`[a-z][0-9]{1,5}`、最长6字符，input内唯一且不使用真实ID／稳定hash；一个handle对应一个冻结游戏源或配置上下文，字段位置另用field_path指定，不跨input复用。返回时反查该input的typed manifest，game句柄与config句柄不可混用。

来源只取制作者当周已存日内容、已选周游戏／人工稿及相关配置；年级沿该周已保存表头grade，同班升班不重算旧周表头。搭班两类名称仅是周稿里手填的背景，不成为搭班日计划或真实游戏来源。未保存文本、未采用候选、别人的日计划、观察照片、家庭信息和上周计划不进入输入。AI配置／提示词实际版本在领取execution时钉住，业务输入不随领取而换稿。

| 任务 | 严格业务输入 | 不进入该任务的输入 |
| --- | --- | --- |
| 游戏选择 | 年级、本人当周晨间户外游戏与整组目标／指导，集体后区域／户外／专用室游戏上下文及目标／指导／支持策略，对应班级游戏配置 | 搭班手填名称、其它教师日计划、四栏全文、材料、主题及未经确认的新增要求；不以同名替换具体来源。 |
| 本周重点 | 年级、主题；本人当周集体活动主题／目标／过程、晨谈话题；手填搭班晨谈／活动名称；本栏教师文字 | 照片／家庭资料、未填搭班教案、其他栏教师文字。 |
| 环境创设 | 年级、主题；已选重点区域／户外游戏整组目标／指导／支持策略及相应区域／专用室配置；本栏教师文字 | 搭班名称、未选游戏、园所现有器材猜测、其他栏要求。 |
| 习惯文化 | 年级、主题；本人当周晨谈、晨间游戏指导、集体后游戏支持策略；本栏教师文字 | 搭班名称、儿童习惯／行为／家庭事实、其他栏要求。 |
| 家园合作 | 年级、主题；本人活动主题／目标概览；手填搭班晨谈／活动名称；有效日历节假日上下文；本栏教师文字 | 观察照片、儿童家庭信息、上周计划、集体活动过程全文及其他栏要求。 |
| 材料 | 年级、明确重点区域及所选游戏名称／目标／指导／支持策略与实际引用版本 | 主题、四栏、搭班名称、未选游戏和未采用候选；当前材料正文不自动成为新的生成要求。 |

四栏缺输入时如实给出缺项与可编辑一般建议，不伪造教案／已开展事实；不额外增加必须有本人日计划的门槛。日历按目标周相关日期±7日含边界、受支持节名和有效日历去重；未覆盖为unknown，不猜节日、不联网补齐，不强制节日活动。

材料用于重点区域既有材料栏，须有明确重点区域；缺失返回`MATERIAL_CONTEXT_REQUIRED`且不排队／不发送，保留原值。这继承[材料规格§2](weekly-materials-implementation.md)的非冲突边界，不阻断手工保存或明确缺项确认。其余所选游戏可补充上下文，每项提取标明实际依据；不把晨间与重点区域用品混称同一来源。

这是创建前422，0 input/task/创建回执；旧材料规格的“任务暂停”措辞不照搬为本片先建paused任务。既有已提交同键回执仍优先读回。

### 3.2 依赖、目标与版本分开

同一纯投影在创建、发送前、候选查看与采用前复用。创建稿身份用于追溯；dependency_hash只纳入该任务实际依据，target_hash只纳入拟替换字段及其当前采用身份；整稿expected_draft_version用于CAS，三者不能合并。

现有`weekly_plan_sources.load_source_snapshot`没有完整AI配置：game_context只含修订身份，原_game_projection只带日来源已引用地点。后续A的`weekly_ai_sources.py`须独立读取当前班级配置manifest `{revision_id,revision_no,locations:[{kind,name,guidance}],game_scope,guidance}`，即便无本人日来源也取得完整配置，不修改旧确认manifest／hash含义。当前配置没有具名游戏目录／整组目标，不能当作完整户外游戏源；仅为地点与AI补充的真实上下文依据。

A只负责DB一致读取和原始trusted manifest；B的`project_weekly_input(task_type,raw_manifest,saved_content)`为纯函数，返回payload、handle_manifest、dependencies、dependency_hash、target_hashes，B不再读DB。A存入该输出并负责实际归属／采用事件校验；D的备份校验复用纯validator并核数据库链。相关配置项按(kind,name,同名出现序号)及快照定位，保留revision作追溯，不虚构稳定游戏项ID；新修订中的业务依赖仍按实际相关上下文内容比较。

引用具体日游戏须保存完整plan/content ID＋version／section／group／game和整组文本，相关引用版本变化不得按同名重新盖章。配置manifest保留实际使用revision与具体项，依赖比较对应项身份／内容；无关配置项、园名／教师名单或全局修订变化不单独使所有候选过期。四栏使用各自Q6投影和相关来源，不能因未参与该栏的输入改变而误判。

材料basis包括年级、已选三个槽／重点区域的完整内容与稳定身份、日引用版本或真实手工／配置／AI依据及相关支持策略。选择、相关文本、引用版本、年级改变或来源缺失时保留旧正文与旧basis并派生stale／missing；主题、四栏和无关配置项不参与basis。手改材料不改原basis。即便候选依赖仍适用，整稿版本变化也要求重新预览；不能自动重基覆盖人工稿。

## 4. 输出、游戏身份和材料证据

原始模型输出与API候选详情分开；模型不能决定candidate_id、版本、来源“最新”、采用者或状态。严格JSON对象，拒绝重复键、NaN、额外字段、围栏／自由文本、错误枚举、错误类型及超限；超限整次失败、不截断。复用现有1MiB整体防护、100000字符一般文本限额和100项数组上限；最终草稿还须满足原周字段限额。

游戏输出为`{outdoor_game_slots:{collective_1,collective_2,free_choice_1},focus_area}`。每项为null或`{kind:"source",source_handle}`，或`{kind:"ai_supplement",name,...对应类别完整文本,basis_handles:[]}`。source句柄只映射本人晨间户外／集体后具体游戏，服务端按冻结整组原文物化，模型不能拼A目标／B指导。配置只有地点／范围／指导，基于它生成游戏名称或目标指导的整项均标AI补充；basis_handles只允许本次相关config句柄或空数组，不把配置句柄当游戏源。户外两集体／一自选、同类别同名单名额，重点区域类别与上下文独立校验；空项作为真实缺项，不编造来源。明确采用整个组合时null表示清空相应旧槽／重点区域，before/after必须显示；生成和预览本身不清空人工项。

四栏每个子任务只返回`{text:string}`，空白无效；字段身份由task_type决定，不接受额外栏目。候选详情将其投影为目标名，不从模型文本猜栏目。游戏组合和材料候选也只开放各自目标。

材料输出为`{items:[{text,origin,evidence_refs}]}`。origin为extracted或suggested：提取项至少一份`{source_handle,field_path,start,end,quote}`；建议项证据数组必须为空。位置按冻结字段原文的Unicode code point、0起点、左闭右开计数，要求`original[start:end]==quote`且quote非空；服务端同时核对句柄、字段允许集、实际版本和用品文字依据。同一quote多次出现时由合法位置消歧，不要求原文只能出现一次。来源本身为已保存AI游戏时仍明确标AI依据，不能冒充日计划原文。位置相等只证明可追溯，不证明语义质量。具体用品不足可仅有建议，不设强制最少条数；items为空如实预览为空与缺项，不自动清空旧材料，不把“工具／材料”泛称猜成具体用品。

沿已确认材料边界：最多100项，单项text≤300字符、quote≤2000字符，按候选顺序合成的材料正文≤20000字符，整体仍≤1MiB；项空白／位置越界／伪证据整候选拒绝。预览区分提取与建议，供Word仍是既有材料栏多行文本，不新增证据正文或模板列。

存储游戏source_kind为daily_plan／manual／ai_supplement：日来源保持原完整引用，manual仅限既有户外；配置只存为依据，不新增config游戏来源枚举或游戏目录。AI项由服务端分配稳定周内ai_item_id并保留candidate／input及basis_keys，日引用全部null，不能冒认本人日记录。重点区域可日来源或依本人集体后游戏／对应配置形成的AI补充，不因本片开放任意手填。普通保存仅可原样保留可信既有AI项或提交既有允许的改选；不能由客户端创建provenance。

## 5. 候选、采用和内容schema

候选append-only、一个execution最多一个；详情返回来源、实际配置／提示词版本、目标、内容、依据、相关缺项及`eligible|source_changed|contract_obsolete`。生成成功与采用／确认分列；候选迟到不更新编辑正文。候选链损坏为存储错误，不静默忽略；外计划／档案返回统一不存在。

采用预览DTO为`{expected_draft_version,selections:[{candidate_id,target}]}`；同操作合法目标非空、无重复，只允许候选已提供目标。四栏多份子候选必须同周、同一次创建回执、同一冻结draft与原始读取快照；跨批次集合409，不自动混合重基，可分别重新预览合法批次。候选详情附create_operation_id，前端按批次显示而不要求教师选择技术任务类型。候选预览只读，明确采用后沿既有编辑／保存入口修改，不新增采用前编辑流程；普通保存仍不得伪造日引用或AI身份。主题、搭班信息不是AI采用目标。

预览返回`{preview_token,expires_at,weekly_plan_id,draft:{id,version},selections,before,after,warnings}`。token沿既有600秒／最多64项有界内存，绑定launch／会话／profile／周／当前稿ID＋版本／全部candidate ID及hash和目标／各dependency与target hash／contract。预览只读，token不进日志／备份；恢复或重启使其失效。

采用DTO为`{request_id,expected_draft_version,preview_token}`，以预览固定选择为准，预览不接受编辑值。先查持久回执，再查token，token缺失时再次查回执以消除并发成功窗口。在单个BEGIN IMMEDIATE中重核归属、候选全链／contract／依赖／目标／版本，只合并明确目标、追加一个周草稿、采用事件及回执、CAS当前指针并提交；任一变化／失败全回滚。成功后耗用token。丢响应同键同体返回原版本；已经提交的同键换新token属于异体冲突。空items候选明确采用后正文为""并建立该次真实basis；预览显示将清空，未明确采用保持旧正文，不自动当无操作。

周内容新增schema2，保留schema1按原键集合严格读取；不通过放宽schema1或批量重写旧JSON接新功能。schema2保留原主题／确定性栏目／四栏／表头日历语义，扩游戏身份和只读`ai_provenance`目标映射，以及`materials:null|string`、`materials_provenance:null|object`。无材料采用历史时二者均null；采用时建立可信candidate、有界实际basis快照及hash、原items与证据、原合成文字、采用者／时间／版本，不复制完整AI input／未选来源池；手改或清空只更新正文和edited标记，原依据不变。两类provenance合计序列化≤512KiB、完整草稿仍≤1MiB；预览先验证容量，超限拒绝且保留原稿，不截断证据。

ai_provenance逐目标保留candidate／input／execution／contract／dependency、原采用draft ID＋版本、原采用值与hash；普通保存继承真实采用起点，由服务端按当前值与原采用值比较派生manual_edited，不能把新人工文字登记成模型原输出。旧采用事件关联的是当时产生的draft，不要求每次普通保存额外造采用事件；新的明确采用才替换对应目标映射并追加事件。材料provenance另保留完整basis与证据，后续手改或清空同样不改原采用起点。两类只读依据均随新确认自包含冻结。

schema2精确键集合如下；同一tag下递归拒绝额外键，null与明确清空不能合并。函数参数的具体语言类型在后续G0核对，不再由各会话另定JSON形状。

| 对象 | 固定键与规则 |
| --- | --- |
| content2 | 原9键`schema_version,theme,deterministic,outdoor_game_slots,focus_area,weekly_columns,materials,source_manifest,calendar_basis`加`ai_provenance,materials_provenance`；原字段结构保持，schema_version=2。 |
| ai_provenance | 固定`games,key_week_focus,environment_setup,habit_culture,home_cooperation`五键，各为null或采用对象；材料使用独立materials_provenance。 |
| 四栏／游戏采用对象 | `candidate_id,candidate_hash,input_id,execution_id,contract_version,dependency_hash,adopted_draft_id,adopted_draft_version,adopter_profile_id,adopted_at,adopted_value,adopted_value_hash,manual_edited,basis`；basis仅保留实际该目标依据、真实来源身份／版本／文本与配置项快照，manual_edited为服务端布尔值。 |
| materials_provenance | null或`candidate_id,candidate_hash,input_id,execution_id,contract_version,dependency_hash,basis,basis_hash,items,original_text,edited,adopter_profile_id,adopted_draft_id,adopted_draft_version,adopted_at`；basis为实际所选游戏／重点区域及年级、引用身份版本和相关配置快照；items为原候选证据经服务端补入可信映射，edited为当前正文与original_text的差异。 |
| AI户外／重点区域 | 相应原SLOT_KEYS／FOCUS_KEYS加`ai_item_id,candidate_id,input_id,basis_keys`；source_kind=ai_supplement，manual_item_id及所有daily/content/section/group/game引用均null；名称／目标指导字段为生成文本，重点区域保留context_kind/area；basis_keys仅引用该input配置上下文，实际依据在采用对象basis中自包含。 |
| 日／手工条目 | 分别按原严格SLOT_KEYS／FOCUS_KEYS校验，不接AI扩展键；手工只在户外，client_key仍只用于PATCH关联，不入存储。 |
| 材料PATCH | PATCH_KEYS在schema2加入materials，值null或string；有可信provenance才能改写，null／""均为清空且保留provenance，无provenance只允许仍为null。省略不变。 |

所有身份沿既有opaque ID限额、hash为64位十六进制、版本为非布尔正整数、时间为UTC；stale/missing是当前依据比较的派生事实，不接受客户端提交“最新”或直接改旧basis。普通保存的业务no-op在格式提升前判定；refresh_content保留AI身份／四栏／材料，日引用只按既有明确刷新规则处理，实际AI/config依据变化只派生旧状态，不伪造刷新为新来源。

schema1按旧规则读取；后续首次实际业务变更或明确采用时在内存提升为schema2、追加新稿，不改旧稿／旧确认。无修改保存不因升级格式额外造版本，新建周稿在新实现中使用schema2。普通PATCH仅在已有可信materials_provenance时允许编辑／清空materials，不允许写provenance、basis、stale或AI身份；空白材料仍是缺项。普通保存不归零材料，刷新来源保留四栏和材料。无采用事件的非空材料或伪provenance拒绝。

自包含确认快照的外层envelope保持schema1和原键集合，嵌套content分别严格接受schema1／schema2；新确认包含精确草稿、材料全文及原依据、身份、日期／列、缺项／stale事实，旧确认原JSON／hash不变。导出manifest按项目逐项验证嵌套内容版本，可包含合法旧／新确认；现有manifest顶层和宿主DTO不为AI改形。指定旧确认仍只读旧快照，当前dirty和未采用候选不进入导出。缺项／旧材料经明确预览确认可形成新版本，ack不把旧依据标新。

## 6. 数据迁移、备份与执行器

### 6.1 后续唯一迁移

拟议下一revision为`20261102_0008_local_weekly_ai`，文件`backend/migrations_local/versions/20261102_0008_local_weekly_ai.py`，down_revision为现有`20261101_0007_local_weekly`；**本轮不创建文件**。实施G0若head已变先重新核定，禁止第二head／stamp／downgrade。SQLite CHECK扩展需要受控批量重建相关AI表，不能用应用条件代替约束或丢弃旧触发器／索引。

LocalAIInput增加nullable weekly_plan_id、weekly_draft_id、create_operation_id，周分支三者非空，source_revision为冻结draft_version，旧daily content_id/content_version、daily_plan_id、observation_id及target_grade均null；周年级在业务payload和manifest。LocalAITask／Execution／Candidate增加nullable weekly_plan_id。四表source_kind/task_type CHECK允许上述周组合，source_id=weekly_plan_id；旧分支所有新增周列必须null。input以(weekly_plan_id,weekly_draft_id,source_revision)外键绑定具体草稿，(profile_id,create_operation_id)绑定AI创建回执，LocalAIOperation补UNIQUE(profile_id,id)作为复合FK目标。各子input共同保存同一批raw_manifest的batch_snapshot_hash作追溯，不纳入不相关字段的实时dependency比较。profile＋weekly归属以及input→task→execution→candidate复合来源链均须SQLite约束，不接受跨计划拼链。

同档案／周／task_type在source_kind=weekly_plan且活跃状态pending／claimed／dispatching／retry_wait时建立部分唯一索引；paused／unknown保留历史，恢复排队仍检查活跃冲突。新增LocalWeeklyPlanAIAdoption表：`id`为32字符opaque主键，全部非空列`profile_id,source_kind,weekly_plan_id,draft_id,draft_version,candidate_id,target_key,before_hash,after_hash,operation_id,created_at`；source_kind CHECK固定weekly_plan，target_key为games／四栏键／materials之一，draft_version严格正整数，hash长度64。UNIQUE(draft_id,target_key)；复合FK分别绑定(profile,周)、(周,draft,version)、(profile,source_kind,周,candidate_id)候选来源链和(profile,operation_id)采用回执；profile_id即本地采用者。内容里的provenance与事件／input须能交叉校验。ID保持opaque，不引入owner_epoch权限模型。任务组映射使用既有AI回执，不增第二任务执行器或业务权威。

迁移还须将LocalWeeklyPlanContent现有`schema_version = 1`的CHECK扩为严格整数1／2，保留表的复合FK目标键和全部旧行；内容schema2因此也受数据库迁移门槛约束。写入与备份校验要求行schema_version等于JSON内容版本，不能继续在service中硬编码1。确认表envelope仍固定1，不放宽未知版本。LocalPromptBundle的task_type CHECK在既有5种后追加6种周任务（共11种），迁移内冻结对应input/output schema、默认prompt及revision，不能导入会随源码变化的registry；既有个人指导不覆盖。本片不新增周AI指导设置入口。

迁移保留所有旧日／观察／周行值、旧JSON与hash、配置和凭据；新增引用列null、新采用表空，不自动造候选、确认、配置修订或审计历史。新bundle／必要个人head按既有初始化规则登记，旧head／version不改写。旧程序见0008须拒绝，不能覆盖新库。保留冷升级摘要与旧schema拒绝守卫，实际迁移／约束／损坏反例另验。

### 6.2 备份／恢复

完整快照将新增表和修改表纳入一致性读取、来源freeze、备份逻辑检查与恢复前验证；逐项校验schema1/2、指针、完整候选链、采用事件、input/basis hash、材料证据、回执映射以及旧确认。必须以真实SQLite合成副本测试0007升级、明文／加密恢复、新进程继续及恢复保护包，不能只测JSON序列化。备份格式及加密通道沿现有合同；如实际外层格式需改变，先列明兼容理由重新核定，不直接升号。

维护先阻止新周AI创建／采用，再沿既有屏障冻结领取、排空或撤销permit、确认worker退出，最后快照／替库。替换恢复与保护包恢复后均创建新launch／会话代；旧预览token和运行permit无效，未完成任务按已发证据归paused／unknown，成功候选保持但不自动采用。恢复不自动重放任务、不扩大跨Windows用户凭据能力。

### 6.3 任务状态与重试

沿现有pending→claimed→dispatching→succeeded／failed／paused／outcome_unknown／cancelled及retry_wait状态机。只在明确未发字节的暂时连接错误上最多3次attempt、5／30秒等待；证书／目标策略失败不重试。完整429暂停但processing_certainty=unknown；401／403配置拒绝暂停；普通5xx、可能已发送的超时／失联按unknown，均零自动重发。完整结构错误为failed/output_invalid，不自动再问模型修复。

每次状态推进验证task↔execution、permit、launch、generation；发送标记先持久化，mark后即使尚未观察SEND也保守unknown。收到结果后只重试本地提交；候选与成功状态同事务，不能因DB故障重新联网。取消先提交则迟到帧不写候选，成功先提交则返回实际成功。手动retry明确提示新请求；无法证明未处理须ack_duplicate_cost。启动只归并旧状态，不联网；新旧任务不复活旧执行。

## 7. API与页面／宿主合同

周AI路由前缀`/api/weekly-plans/{plan_id}/ai`，沿现有周路由命名。所有请求沿现有会话／Origin／本地归属与维护屏障；GET无写入、无AI和自动刷新。创建后调度只能消费提交后的task；事务内不做HTTP、DPAPI或文件IO。

| 方法／相对路径 | 请求／结果 |
| --- | --- |
| POST `/games`、`/columns`、`/materials` | §2创建DTO／结果；新建202、回执重放200，校验／上下文不足422，版本／活跃／幂等冲突409，执行器不可用503。 |
| GET `/operations/{request_id}` | 当前归属AI操作安全回执与原映射；未找到404不能推断提交失败。 |
| GET `/tasks`、`/tasks/{task_id}` | 周范围任务、状态、processing_certainty、retry_requires_ack、允许动作、input摘要和安全execution版本，不返回key或完整HTTP响应。 |
| POST `/tasks/{task_id}/cancel`、`/resume`、`/retry` | request_id、expected_execution_id，retry另带ack_duplicate_cost；沿现有状态与显式动作，不自动排队兄弟任务。 |
| GET `/candidates`、`/candidates/{candidate_id}` | 列表省略正文；详情包含可信来源／内容／适用性与可采用目标，损坏503、越界404。 |
| POST `/adoption-preview`、`/adopt` | §5 DTO及完整before/after；采用结果返回新草稿版本／操作回执，不确认、不发材料。 |

列表沿现有limit默认20、范围1–100及不透明cursor，错误沿`{error:{code,message,...安全details}}`。TaskOut在周路径必须明确source_kind/source_id/weekly_plan_id、目标和冻结稿身份；不得对周任务返回伪daily plan_id。新错误区分WEEKLY_AI_SOURCE_CHANGED、TARGET_CHANGED、PREVIEW_EXPIRED、CONTRACT_OBSOLETE、REQUEST_CONFLICT、TASK_ACTIVE、MATERIAL_CONTEXT_REQUIRED；最终代码映射在G0逐项核对已有错误类型后冻结，不能由前端猜reason字符串。

页面仅增加三个明确操作与四栏勾选、候选全文预览／明确采用及可恢复状态，未配置AI时手工闭环继续。输入/任务/完整性/来源/采用/确认分别显示；不暴露迁移号、token、hash或技术分片给教师。游戏预览展示同名具体来源及整组文本；材料提取／建议和旧basis可辨。

写入串行协调现有周编辑器；保存中继续输入只更新实际提交基线。创建／采用回包仅在profile／周／launch／editor epoch相符时更新当前页，否则保留当前输入并提示有已保存结果可查。切页停止轮询不等于取消任务；候选返回不自动写表单。dirty／未知票据／候选预览离开和关闭沿现有统一协调，旧确认导出仍可保留dirty稿。

关闭及维护使用既有freeze/drain/停止等待和宿主最终ack，不加绕过入口；DB失败或worker退出未证实拒绝正常关闭／替库。取消关闭不能新建generation或复活已退役任务。周AI初始化失败仅在证实无残留worker后降级为不可用，人工保存／确认／导出继续；不能吞掉部分启动失败。

## 8. 拟议文件责任与阶段门

**下表是后续实施分工方案，不是本轮写权限。** 本轮仅A／C私有准备，B／D未启动；Codex独占正式文档。后续明确放行后，仍须核对原会话自然停写、当前HEAD／dirty和G0接口，固定模型、不fork／另派子代理。你不是唯一写入者，不还原他方修改；没有归属的文件先停依赖方，由Codex划定。

| 会话 | 后续拟议唯一文件责任（路径均相对仓库） |
| --- | --- |
| A 原OpenCode `ses_ead8af71dffeJphI1NOWg4jZgI` | 新`backend/app/local/weekly_ai_service.py`、`weekly_ai_sources.py`、`weekly_ai_candidates.py`、`weekly_ai_adoption.py`、`weekly_ai_api.py`；共享`models.py`、`schemas.py`、`api.py`、`app.py`、`runtime.py`、`errors.py`、`ai_task_service.py`、`ai_executor.py`、`ai_worker.py`、`ai_spawn.py`、`ai_transport.py`、`ai_candidates.py`、`ai_adoption.py`、`ai_inputs.py`、`ai_provenance.py`、`prompt_bundles.py`、`ai_config_service.py`、`weekly_plan_service.py`、`weekly_plan_sources.py`、`weekly_plan_operations.py`及唯一0008迁移；仅实际影响处最小修改。新`backend/tests/local/test_weekly_ai_service.py`、`test_weekly_ai_api.py`、`test_weekly_ai_adoption.py`、`test_weekly_ai_migration.py`及受影响既有AI整合测试。前端共享`App.vue`、`main.ts`、`types.ts`、`client.ts`、`bridge.ts`、`leave.ts`、`ai.ts`与Settings／Workbench接线若必要也仅A。 |
| B 辅助OpenCode `ses_e72ecd5f9ffeYJaLRNypsdu5Pi` | 新`backend/app/local/weekly_ai_contracts.py`、`weekly_ai_inputs.py`、`weekly_materials.py`：纯结构／业务投影／basis／证据／合成文字；维护`weekly_plan_content.py`的schema1/2、身份、PATCH与facts纯函数。新`backend/tests/local/test_weekly_ai_contracts.py`、`test_weekly_ai_inputs.py`、`test_weekly_materials.py`、`weekly_ai_fake_transport.py`，既有`test_weekly_plan_content.py`。不得读DB／runtime／网络，不改A共享文件；fake仅测试可注入，不注册真实供应商。 |
| C Command Go `8cf528de-8773-4a06-9cc5-31e96fab515f` | 新`frontend/src/d1/weekly-ai.ts`、`views/WeeklyAiPanel.vue`、`d1.weekly-ai-core.test.mjs`、`d1.weekly-ai-ui.test.mjs`；维护`weekly.ts`、`weekly-editor.ts`、`views/WeeklyPlanEditorView.vue`、`WeeklyPlansView.vue`、`WeeklyHistoryPanel.vue`、`WeeklyExportDialog.vue`及既有`d1.weekly*.test.mjs`／`d1.shell-weekly.test.mjs`。只消费冻结DTO／纯函数，不改A共享TS／App或D宿主。 |
| D Command Go `16cf76b5-ea0b-47f5-bc94-26147c9d3689` | `backend/app/local/weekly_plan_snapshot.py`、`weekly_plan_export_service.py`、`weekly_plan_export_api.py`、`backup_validate.py`、`backup_snapshot.py`、`backup_fs.py`、`backup_format.py`、`restore_service.py`、`restore_group.py`、`restore_recovery.py`；`desktop/d1_host_api.py`、`maintenance_host.py`、`maintenance_lifecycle.py`、`build_e14.py`、`verify_e14_package.py`、`verify_e14_portable_archive.py`的必要维护／冻结适配。新`backend/tests/local/test_weekly_ai_backup.py`、`desktop/tests/test_weekly_ai_lifecycle.py`，既有weekly backup/snapshot/export、backup／restore及宿主整合测试。受控模板不改，备份／宿主／构建支持仅实际需要且另经对应阶段放行。 |
| Codex | 工程／产品／模块文档、唯一任务入口、审核结果、独立执行验证和后续精确Git门禁；不成为业务实现者。 |

A所有backend路径均以`backend/app/local/`为根；A前端共享路径均以`frontend/src/d1/`为根。D既有测试责任精确为`backend/tests/local/test_weekly_plan_backup.py`、`test_weekly_plan_snapshot.py`、`test_weekly_plan_export.py`、`backup_fixture_support.py`、`test_backup_fixture_support.py`、`test_backup_snapshot.py`、`test_restore_core.py`、`test_restore_crash_recovery.py`，以及`desktop/tests/test_d1_weekly_export_host.py`、`test_maintenance_lifecycle.py`、`test_maintenance_host.py`。未列共享测试及任何conftest／锁定文件不自动获权；G0列实际变更清单再纳入。

| 阶段门 | 后续允许范围和完成条件 |
| --- | --- |
| P0 本轮准备 | 合同／矩阵／文件分工由A/C起草、Codex审核归正式文档；不写业务或测试，不运行矩阵。本轮止于此。 |
| G0 后续准入 | 评估当前Windows候选目标反馈，通用保存／恢复／关闭缺陷优先；用户明确放行实现后，四原生按新HEAD确认实际文件表、DB head、错误映射、schema2精确嵌套键、DTO和纯函数签名。冻结后才写代码，禁止各自另造协议。 |
| G1 数据／纯合同 | A与B并行自有文件；A唯一共享AI／迁移，B只纯函数／合成反例。D先做自有备份schema／历史兼容；接点须已冻结。真SQLite／迁移／假transport通过后再接页面。 |
| G2 页面／宿主配套 | C只接已冻结后端，D自有维护／快照／导出，A自有App／运行时接线；不并行改同文件。接口变化先停依赖方，Codex更新合同后续接。 |
| G3 独立整合 | 所有会话自然停写，Codex核来源、实际差异、矩阵、受影响回归及保存／恢复／关闭。失败交原owner最小修复；自动、源码窗口、Word分别结论。 |
| G4 交付分项 | 新构建／静态／目标／Word／教师、真实应用供应商、签名／发行和Git各按当时明确范围；不能从合同准备推导授权，不复用旧parent/tree批准。 |

OpenCode固定build／`opencode-go/deepseek-v4.1-flash#max`，Command Go固定`deepseek/deepseek-v4.1-flash`／effort max；原生metadata和自然exit要核实，参数不是模型使用证明。最终Git仍按当轮精确文件/blob/parent/tree由原A普通提交推送；本轮不提交／推送。

## 9. 2026-11-03 G0核定合同

本节为51ec4d3上的实际核定，覆盖前文准备态及A/B/C/D提案中相异之处。用户已授权实施、构建和真实应用AI；Codex以本节明确放行G1：仅A共享数据／任务／唯一迁移、B纯合同、D备份与旧档案兼容；C页面等待G1真SQLite、假供应商、旧档案完整保留和备份恢复证据通过。原生自然停写及metadata见[实施核查](../bootstrap/desktop-weekly-ai-review.md)，不据提案自报测试通过。

### 9.1 唯一迁移与事务

- 当前唯一head为`20261101_0007_local_weekly`，实际文件`20261101_0007_local_weekly_plans.py`；新增唯一`20261102_0008_local_weekly_ai.py`，revision `20261102_0008_local_weekly_ai`、down_revision为0007，不stamp／downgrade／另建head。
- 新表SQL名固定`local_weekly_plan_ai_adoption`，类`LocalWeeklyPlanAIAdoption`，列／复合FK／UNIQUE按§6.1；旧48张业务表旧列原值保留，新周引用列全null，新表初始为空。内容CHECK为`typeof(schema_version)='integer' AND schema_version IN (1,2)`，确认外层仍1。
- `local_ai_operations`新增UNIQUE(profile_id,id)；input的create_operation_id及采用事件operation_id使用立即复合FK。创建先预分配全部ID和安全回执映射，再在同一事务插operation→input→task；采用在新draft存在后插安全operation→全部event，CAS指针及所有行同一事务提交。不得先flush引用不存在operation的event，不提交占位回执。
- 周活跃唯一索引精确为profile_id＋weekly_plan_id＋task_type，where source_kind=weekly_plan且status在pending／claimed／dispatching／retry_wait。旧daily／observation约束、索引和来源链保留。
- 0008仅扩prompt task CHECK至既有5种加周6种，不在迁移事务往旧提示词表插行，不导入可变registry。六种v1／r1 schema与默认指导在本包纯manifest冻结，守卫及提交后旧摘要检查通过后由runtime sync补缺失bundle／周head，旧个人指导／head／version不改。`TASK_TYPES`仍daily-only，周类型单列，运行时不导入迁移。

### 9.2 B纯函数签名

B模块无DB／runtime／网络依赖。`WeeklyAIContractError(ValueError)`提供安全`code,field_path,details`，不含原文；既有`WeeklyContentError`保留。类型为Mapping[str,Any]／dict；以下签名固定，省略类型仅表示已有函数签名保留。

```python
# weekly_ai_inputs.py
@dataclass(frozen=True)
class ProjectedWeeklyInput:
    task_type: str
    target: str
    payload: dict[str, Any]
    dependencies: dict[str, Any]
    dependency_hash: str
    target_hashes: dict[str, str]
    server_manifest: dict[str, Any]
    def as_row_kwargs(self) -> dict: ...

def validate_raw_manifest(raw: object) -> dict: ...
def project_weekly_input(task_type: object, raw_manifest: Mapping[str, Any],
                         saved_content: Mapping[str, Any]) -> ProjectedWeeklyInput: ...
def build_business_dependency_view(dependencies: Mapping[str, Any]) -> dict: ...
def dependency_hash(dependencies: Mapping[str, Any]) -> str: ...
def server_manifest_from_dependencies(dependencies: Mapping[str, Any]) -> dict: ...
def target_projection(content: Mapping[str, Any], target: object) -> dict: ...
def target_hash(content: Mapping[str, Any], target: object) -> str: ...
def build_ai_facts(content: Mapping[str, Any], raw_manifest: Mapping[str, Any]) -> dict: ...

# weekly_ai_contracts.py
def normalize_selected_fields(value: object) -> tuple[str, ...]: ...
def task_types_for_columns(value: object) -> tuple[tuple[str, str], ...]: ...
def target_for_task(task_type: object) -> str: ...
def strict_json_object(raw: str | bytes, *, max_bytes: int = 1_048_576) -> dict: ...
def validate_handle_manifest(value: object) -> dict: ...
def parse_games_candidate(raw: str | bytes, *, server_manifest: Mapping[str, Any]) -> dict: ...
def parse_column_candidate(raw: str | bytes, *, task_type: str) -> dict: ...
def parse_materials_candidate(raw: str | bytes, *, server_manifest: Mapping[str, Any]) -> dict: ...
def finalize_games_value(value: Mapping[str, Any], *, candidate_id: str,
                         input_id: str, ai_item_ids: Mapping[str, str]) -> dict: ...
def candidate_hash(value: Mapping[str, Any]) -> str: ...
def weekly_bundle_definitions() -> tuple[dict[str, Any], ...]: ...

# weekly_materials.py
def build_selected_basis(*, grade: str, content: Mapping[str, Any]) -> dict: ...
def build_materials_basis(*, grade: str, content: Mapping[str, Any]) -> dict: ...
def materialize_materials_items(items: object, *, server_manifest: Mapping[str, Any]) -> list[dict]: ...
def synthesize_materials_text(items: Sequence[Mapping[str, Any]]) -> str: ...
def build_materials_provenance(*, candidate_id: str, candidate_hash: str,
    input_id: str, execution_id: str, contract_version: int, dependency_hash: str,
    basis: Mapping[str, Any], items: Sequence[Mapping[str, Any]], original_text: str,
    adopter_profile_id: str, adopted_draft_id: str, adopted_draft_version: int,
    adopted_at: str) -> dict: ...
def validate_materials_provenance(value: object, *, materials: object,
                                  content: Mapping[str, Any]) -> dict: ...

# weekly_plan_content.py
# validate_content增加可选expected_schema，其余原有调用保持兼容。
def validate_content(content, *, snapshot=None, expected_schema=None) -> dict: ...
def content_schema_version(value: object) -> int: ...
def promote_to_schema2(content: Mapping[str, Any]) -> dict: ...
def apply_weekly_ai_adoption(previous: Mapping[str, Any], *, target: str,
    candidate_value: Mapping[str, Any], adoption: Mapping[str, Any],
    basis: Mapping[str, Any], server_manifest: Mapping[str, Any] | None = None,
    ai_item_ids: Mapping[str, str] | None = None) -> dict: ...
```

`as_row_kwargs`仅返回payload_json／dependencies_json／dependency_hash／target_hashes_json。`weekly_bundle_definitions`按六种task固定顺序返回精确键`task_type,contract_version,default_revision,input_schema_json,output_schema_json,guidance_defaults_json`；A用既有bundle_hash算法包装，不循环导入。纯validator内部错误为WEEKLY_AI_INPUT_INVALID／OUTPUT_INVALID／CONTRACT_OBSOLETE／SOURCE_CHANGED／TARGET_CHANGED、MATERIAL_CONTEXT_REQUIRED和既有content错误；A在边界映射HTTP，不给模型自由文本自动修复机会。

### 9.3 trusted manifest、payload与依据精确键

raw_manifest顶层精确：`schema_version,contract_version,source_kind,profile_id,class_id,term_id,weekly_plan_id,draft_id,draft_version,content_hash,week_anchor_date,week_number,term_start,term_end,calendar_revision_id,config_version,header,source_context_hash,days,calendar_window,game_config`。版本均1，source_kind=weekly_plan，header沿原五键，年级取该周冻结header。7天连续，只有本人已存日来源；A独立补齐Q6的目标／过程及完整配置，不修改旧source_manifest／确认hash含义。

| 对象 | 精确键与约束 |
| --- | --- |
| raw.days[] | `date,day_state,source_state,source,morning_groups,post_group_groups`；非教学日不带游戏，saved必须有source，其余source=null。 |
| raw.days[].source | `daily_plan_id,content_id,content_version,content_hash,morning_talk_topic,group_activity_theme,group_activity_objectives,group_activity_process`；内容hash为实际完整已存正文hash。 |
| morning group | `group_id,group_kind,games,shared_objectives,guidance_points,focus_guidance`；games项`game_id,name`。 |
| post group | `group_id,context_kind,area,games,objectives,guidance,support_strategy`；games项同上。 |
| calendar_window | `start,end,days`；anchor−7至anchor＋13含边界共21天；days项`date,day_state,holiday_names,coverage`。有效日历状态与节名覆盖分开，unsupported为unknown，包括学期外窗口；普通周末不冒充节日。受支持的真实节名不因教师把该日设为教学日而抹去。沿既有离线holiday_context，不联网补查；本片保留库实际节名，不新增翻译需求。 |
| game_config | `revision_id,revision_no,locations,game_scope,guidance`；location项`kind,name,occurrence,guidance`，occurrence为同(kind,name)原顺序1起点序号，投影按三元组排序。配置只是上下文。 |
| server_manifest | `schema_version,task_type,plan,source_context_hash,handles`；plan精确`weekly_plan_id,draft_id,draft_version,content_hash,profile_id,class_id,term_id,week_anchor_date,week_number`。 |
| dependencies | `schema_version,task_type,target,grade,theme,manual_text,daily_sources,selected,config,calendar,_server_manifest`；A另加`_batch_snapshot_hash`。下划线审计键不入业务hash或模型payload。 |
| BasisV1 | `schema_version,target,grade,theme,manual_text,daily_sources,selected,config,calendar`，版本1；未用字段null／空数组，逐目标按§3白名单。 |
| DailyBasisV1 | `date,day_state,source_state,daily_plan_id,content_id,content_version,content_hash,morning_talk_topic,group_activity_theme,group_activity_objectives,group_activity_process,teacher_entered,morning_groups,post_group_groups`；teacher_entered只有`morning_talk_topic,group_activity_theme`两键，未用文本null。 |
| SelectedBasisV1 | `outdoor_game_slots,focus_area`；每个非空item为`value,ai_basis`，value为完整可信选中值；非AI的ai_basis=null。 |
| AISelectedBasisV1 | `candidate_id,candidate_hash,input_id,execution_id,contract_version,dependency_hash,adopted_value_hash,ai_item_id,source_ref,config_refs`；source_ref为完整日引用或null；config_refs项`revision_id,revision_no,kind,name,occurrence`。 |
| ConfigBasisV1 | `revision_id,revision_no,game_scope,guidance,locations`，location四键同上。 |
| CalendarBasisV1 | `window_start,window_end,days`，day四键同calendar_window。 |

handle仅在本input内解析：m/p为本人晨间／集体后具体游戏，c为配置地点，h为已选手工户外，a/f为已选AI户外／重点区域；按稳定输入顺序分配，不用真实ID或hash。TypedHandle键集：

- morning_game：`kind,date,daily_plan_id,content_id,content_version,content_hash,group_id,group_kind,game_id,name,shared_objectives,guidance_points,focus_guidance`。
- post_group_game：`kind,date,daily_plan_id,content_id,content_version,content_hash,group_id,context_kind,area,game_id,name,objectives,guidance,support_strategy`。
- config_location：`kind,revision_id,revision_no,location_kind,name,occurrence,guidance,game_scope,config_guidance`。
- manual_outdoor：`kind,manual_item_id,slot_key,name,shared_objectives,guidance_points,focus_guidance`。
- ai_outdoor：`kind,ai_item_id,candidate_id,input_id,slot_key,name,shared_objectives,guidance_points,focus_guidance`。
- ai_focus：`kind,ai_item_id,candidate_id,input_id,context_kind,area,name,objectives,guidance,support_strategy`。

payload只含§3各任务允许业务字段及source_handle，不含上述真实ID／hash／档案姓名。server manifest／raw manifest各限1MiB，dependencies_json含manifest限2MiB；模型payload／实际HTTP仍沿既有1MiB限额，超限拒绝且0新回执／任务，不截断。

依赖比较只含真实参与字段。配置revision_id／revision_no留作追溯，**不单独进入导致过期的业务比较**；比较相关(kind,name,occurrence)和实际采用的文本／范围／指导，无关配置修订不过期。日引用的具体content身份／版本仍参与，不能同名替源。材料旧依据需解析当前raw中的日／配置状态，不能把旧basis复制一遍当成“仍有效”。候选采用前可比较完整输入要求；已采用内容的source stale比较排除原manual_text与新输出的必然差异，人工改目标只派生manual_edited／edited，不能采用后立即自标过期。

### 9.4 内容／材料具体化

schema2顶层及provenance精确键沿§5.1；Basis及TypedHandle按本节。source_kind只允许daily_plan／manual（仅户外）／ai_supplement，不新增config来源。AI项原键加四键，所有日／手工引用null；candidate/input/ai_item_id与games provenance一致。AI项的opaque ID由A一次分配并在已存稿内保持，候选本身不被后续采用改写。

schema1读取原样、no-op不提升／不增版本；新建及首次实际写入／明确采用产schema2。普通PATCH不能制造AI身份，但可原样回传**与可信旧值逐键相同**的既有AI项；也可省略、清空或用允许日／手工选择替换，改变AI字段／ID或新增AI项拒绝。refresh保留AI身份、四栏、材料正文和原basis。

有可信materials_provenance时，PATCH按提交值保存null或string，**空字符串仍是空字符串**，不把无修改的`""`变成null／edited=true／新版本；两者都按缺项处理。无provenance仅允许维持null，不能PATCH非空或空串制造材料。空items明确采用写`""`及该次真实basis；手改／清空不漂移依据。材料items stored evidence为wire五键再加可信`source`，仅补实际TypedHandle；正文按项顺序以单个换行连接，无尾换行，不输出证据列。证据只接受§4允许字段、code point位置及真实quote，不能把可追溯性冒充语义质量。

采用元数据入纯合并函数精确十键：`candidate_id,candidate_hash,input_id,execution_id,contract_version,dependency_hash,adopter_profile_id,adopted_draft_id,adopted_draft_version,adopted_at`。candidate_hash对应解析后候选值；games最终adopted_value再补AI身份，二者hash不混用。多栏同一新draft身份逐目标纯合并，最后容量／整体校验通过才持久化。

### 9.5 A服务签名和DTO冻结

```python
# weekly_ai_sources.py
def load_class_game_config(session: Session, *, class_id: str) -> dict: ...
def load_calendar_window(session: Session, *, plan: LocalWeeklyPlan,
                         holiday_provider=None) -> dict: ...
def load_raw_manifest(session: Session, *, plan: LocalWeeklyPlan,
                       content: LocalWeeklyPlanContent, holiday_provider=None) -> dict: ...
def raw_manifest_hash(raw: Mapping[str, Any]) -> str: ...

# weekly_ai_service.py
@dataclass(frozen=True)
class WeeklyTaskSpec:
    task_type: str
    target: str

def create_weekly_tasks(session: Session, *, runtime: Any | None, profile_id: str,
    plan_id: str, request_id: object, expected_draft_version: object,
    operation_kind: str, task_specs: Sequence[WeeklyTaskSpec]) -> tuple[dict, bool]: ...
def peek_create_operation(session: Session, *, profile_id: str, plan_id: str,
    request_id: object, operation_kind: str, payload: dict) -> dict | None: ...
def get_operation(session: Session, *, profile_id: str, plan_id: str,
                   request_id: str) -> dict: ...

# weekly_ai_candidates.py
def list_candidates(session: Session, *, profile_id: str, plan_id: str,
    create_operation_id: str | None = None, task_id: str | None = None,
    limit: int = 20, cursor: str | None = None) -> dict: ...
def get_candidate(session: Session, *, profile_id: str, plan_id: str,
                    candidate_id: str) -> dict: ...
def require_chain(session: Session, *, plan: LocalWeeklyPlan,
    candidate: LocalAICandidate) -> tuple[dict, LocalAIExecution, LocalAIInput]: ...
def eligibility(session: Session, *, plan: LocalWeeklyPlan,
    content: LocalWeeklyPlanContent, candidate: LocalAICandidate,
    input_row: LocalAIInput) -> str: ...
def materialized_candidate(candidate: LocalAICandidate, input_row: LocalAIInput) -> dict: ...

# weekly_ai_adoption.py
def preview_adoption(session: Session, *, runtime: Any, profile_id: str, plan_id: str,
    expected_draft_version: object, selections: object,
    launch_id: str, session_scope_hash: str) -> dict: ...
def adopt(session: Session, *, runtime: Any, profile_id: str, plan_id: str,
    request_id: object, expected_draft_version: object, preview_token: object,
    launch_id: str, session_scope_hash: str) -> dict: ...
def reset_tokens() -> None: ...
```

内部task_specs也须核operation_kind对应的精确类型／target，不能混游戏／栏／材料。peek/get只接受四种精确operation_kind，不用startswith；profile和plan同时绑定，跨周／档案统一404。AI回执先于版本／token／executor／freeze检查；无回执的失效token不能授权新采用。create_operation_id为AI回执内部ID，不与request_id混用。

创建／preview／adopt DTO沿§2／§5／§7。补充冻结：

| DTO | 精确业务字段 |
| --- | --- |
| TaskOut | `task_id,source_kind,source_id,weekly_plan_id,target,task_type,status,reason,processing_certainty,user_stop_requested,draft,input_summary,execution,candidate_id,allowed_actions,retry_requires_ack,created_at,updated_at`；draft为id/version，不返回伪daily plan_id。 |
| input_summary | `content_version,draft_version,content_hash,dependency_hash,target_hashes,batch_snapshot_hash,create_operation_id,targets`。 |
| list | `items,next_cursor`；limit默认20、1–100，cursor不透明。 |
| operation | `request_id,operation_kind,status,result,created_at`，status固定committed，result为原安全回执。 |
| candidate list item | `candidate_id,task_id,target,candidate_hash,eligibility,available_targets,create_operation_id,created_at`。 |
| candidate detail | list item加`data,basis,warnings,unavailable_inputs`；仅认证本地来源／日期／版本／opaque身份和内容，不含secret／绝对路径／原HTTP／思考正文。模型不得收到真实身份。 |
| adoption result | `operation_id,request_id,status,weekly_plan_id,draft,selections,changed,replayed`；draft为id/version/content_hash；不确认、不发材料。 |

Task action精确`request_id,expected_execution_id`，retry另带ack_duplicate_cost；progress复用已有安全LocalAIProgressOut及只读`/tasks/{task_id}/progress`，不新增执行器。组摘要由同回执items派生，状态优先级沿§2，始终显示逐项unknown／部分成功。

错误固定`WEEKLY_AI_SOURCE_CHANGED`、`WEEKLY_AI_TARGET_CHANGED`、`WEEKLY_AI_PREVIEW_EXPIRED`、`WEEKLY_AI_CONTRACT_OBSOLETE`、`WEEKLY_AI_REQUEST_CONFLICT`、`WEEKLY_AI_TASK_ACTIVE`，均409；`MATERIAL_CONTEXT_REQUIRED`422；expected version沿`WEEKLY_VERSION_CONFLICT`；通用AI配置／executor／状态／重复成本ack错误继续已有代码。纯input/output错误安全映射至422／任务output_invalid，不回显正文；存储损坏503，越界404。前端只按code和白名单details映射。

所有新写使用现有tx.begin_immediate／backup_barrier，不能进入executor专用ai_write_scope绕过。真正新create/adopt在实际close／executor冻结时拒绝，回执重放优先；adopt在无executor且无冻结／维护时仍可用。已接受在途事务按屏障完成，维护／关闭必须等待其退出。只扩weekly文本bootstrap；observation vision授权不放宽。

### 9.6 精确G1文件责任

以下替代§8拟议表的G1激活范围；未列文件无写权。你不是唯一写入者，不还原他方改动，不fork／派子代理。正式文档由Codex独占；接口更改先由Codex核定，依赖方不自行做兼容别名。

- A新增：`backend/app/local/weekly_ai_service.py`、`weekly_ai_sources.py`、`weekly_ai_candidates.py`、`weekly_ai_adoption.py`、`weekly_ai_api.py`；唯一0008迁移；`backend/tests/local/test_weekly_ai_service.py`、`test_weekly_ai_api.py`、`test_weekly_ai_adoption.py`、`test_weekly_ai_migration.py`。
- A既有：`backend/app/local/models.py`、`schemas.py`、`errors.py`、`app.py`、`ai_task_service.py`、`ai_executor.py`、`prompt_bundles.py`、`weekly_plan_service.py`、`api.py`、`runtime.py`，仅实际接点；测试`test_d2_schema.py`、`test_d2_migration_safety.py`、`test_d2_w3_tasks.py`、`test_d2_w3_executor.py`、`test_d2_w4_api.py`、`test_d2_w4_candidates.py`、`test_d2_runtime.py`、`test_weekly_plan_service.py`。本条既有测试均以`backend/tests/local/`为根，未列共享文件不自动获权。
- B新增及既有：按§8 B完整精确路径激活，即四个纯模块（包含既有weekly_plan_content.py），三个新纯测试、weekly_ai_fake_transport.py及既有test_weekly_plan_content.py；不读DB／网络，不注册供应商。
- D G1：`backend/app/local/backup_validate.py`、`weekly_plan_snapshot.py`、`restore_service.py`（仅公开reset hook），`backup_snapshot.py`仅必要兼容；新增`backend/tests/local/test_weekly_ai_backup.py`；既有`test_weekly_plan_backup.py`、`test_weekly_plan_snapshot.py`、`test_weekly_plan_export.py`、`backup_fixture_support.py`、`test_backup_fixture_support.py`、`test_backup_snapshot.py`、`test_restore_core.py`、`test_restore_crash_recovery.py`。既有测试以`backend/tests/local/`为根。
- C本门只读，页面／测试尚无写权。A前端共享、D宿主／构建／Word／导出API／恢复组／格式／文件系统模块均未在G1激活；需要时按下一门准确列入。模板、锁文件、conftest及依赖不改。

### 9.7 G1旧档案与备份完成门

D冻结0007真实48表旧列profile；SQLite原TEXT（含JSON）、BLOB、整数／浮点／null及行集逐主键比较，不能用新metadata表集或解析重排JSON替代。迁移事务前后所有旧行／旧列相同，新引用null、新采用表空；runtime sync后仅允许新增六种周bundle／周head，旧键行不改。待恢复的进程状态只按既有明确恢复规则改变，不能删除历史或复活permit。原图／派生图及当前／历史专有照片逐文件路径、大小、SHA-256和关联／顺序均保留。

覆盖本人日全部版本／恢复与AI来源、观察草稿／全部历史／照片、周草稿／确认／导出／回执、配置／日历／凭据。旧确认外层1、嵌套1与新嵌套2混存；旧JSON／hash不改，新确认才冻结新basis。旧备份先按原revision／manifest／资源校验，再隔离副本升级，Format 1保持；明文／加密、替换恢复、保护包再恢复、新进程继续及不自动联网分别取得证据。

D只用B纯validator和真实SQLite交叉核完整input→task→execution→candidate→adoption、回执、basis／hash／证据；跨周／档案／坏指针／未知schema反例同时核约束和逻辑校验。reset只调A公开`weekly_ai_adoption.reset_tokens()`，不用私有dict。A／B／D自然停写后Codex独立复核；全部满足才接C页面，不借旧日／观察、旧Word或教师接受结论。

原采用起点还须与该candidate的实际input_id／execution_id／task／contract及原候选值对应，不能仅要求后继provenance等于原稿自身。使用同周、同文、同dependency hash的两个合法批次替换起点指针，或改原采用值并重算content／事件／回执引用hash，均须拒绝。可复用B纯采用函数以原前稿、实际候选／input依据和原AI身份重建并核对应目标，不复制协议；原采用稿该目标是未人工改动的采用结果，后继手改另增版本。恢复后的旧permit／generation还须在实际恢复库中失效，旧worker或新启动均不自动发送。

### 9.8 G1独立审核补充：已存候选纯校验

B首轮67项纯测试及自然CLI0后，Codex独立审核补充以下只读校验接口，既有签名／DTO／来源白名单不变；A/D在各自下一接续段消费，不接管在途共享文件。责任仍为B的weekly_ai_contracts.py及其纯测试。

```python
def validate_stored_candidate(task_type: object, value: object, *,
    server_manifest: Mapping[str, Any]) -> dict: ...
```

value为已通过parse后的实际存储形状，返回严格深拷贝，不静默修复／规范化坏数据。games为已物化日来源／未补ai_item_id的AI候选：日身份和整组文本必须与本input typed manifest同一源完全一致，AI候选只接受parse既有规范键及config basis；可重建wire后调用同一parser并逐值比较，不复制另一套协议。四栏和材料沿既有规范候选形状，材料此处仍是wire evidence五键，不接受采用后才补入的source。task_type与manifest相符，限额及类别／同名／证据限制保持。

非法存储值由纯函数返回安全WEEKLY_AI_OUTPUT_INVALID；A读取／采用映射存储503，D映射BACKUP_DB_LOGICAL_INVALID，不伪装为普通来源变化。错误的message／field_path／details只含固定schema字段、索引、原因与计数，不回显模型任意extra／duplicate key或正文。原候选hash、input业务hash及SQLite链仍由A/D各自核对，纯结构校验不能替代数据库归属。

### 9.9 Q6习惯输入与材料证据绑定裁定

独立审核确认习惯payload不得扩入游戏名称、目标、地点或集体后游戏名单。`days[]`保留`date,morning_talk_topic,morning_groups,post_support`；morning_groups项只有`guidance_points,focus_guidance`，post_support项只有`support_strategy`。相应目标basis未使用字段置null／空数组，服务端追溯身份与模型payload分开；不把“指导”扩大解释为整份游戏上下文。已有Q6决定无需用户重新选择。

材料生成manifest只能包含明确选中的日／手工／AI游戏和实际相关配置，正常入口猜测未分配handle须拒绝。`materialize_materials_items`的trusted manifest参数不是客户端可替换资料；向其副本强加同一已选源的新别名，只能证明故障注入条件下的行为，不作为正常未选来源可访问的证据。已存材料provenance还须独立证明每条stored evidence的typed source属于其**冻结basis.selected**或实际相关config，而非当前已改选组合；build／validate均拒绝不同来源／拼接字段／伪config，保留旧basis可追溯。A/D负责冻结input manifest与payload／dependencies／候选的真实归属及hash；纯校验不代替数据库链。原纯函数签名不变。

### 9.10 已存输入一致性审核补充

Codex合成SQLite探针确认：仅重算dependency_hash、核target_hash及payload为dict，仍会接受被改写的payload。原B只读审核及D接口缺项报告一致；本项是G1完成条件，不按已通过处理。B在自有weekly_ai_inputs.py及test_weekly_ai_inputs.py补唯一纯接口，A/D在各自停写后的接续段消费：

```python
def validate_stored_weekly_input(
    task_type: object, payload: object, dependencies: Mapping[str, Any],
    frozen_content: Mapping[str, Any], *, plan_identity: Mapping[str, Any],
) -> ProjectedWeeklyInput: ...
```

plan_identity为manifest.plan的精确九键，由A/D用真实plan、input、冻结draft行提供。校验payload、业务十键、允许的两个下划线审计键、manifest任务／plan及typed handles与依据的一一对应；按任务复用同一投影构造规则，不复制第二套协议。四栏／材料／游戏的payload逐键逐值比较，不修复、截断或接受额外字段；grade、主题、人工要求及所选项与该任务冻结稿按既有投影规则对应。返回既有ProjectedWeeklyInput深拷贝，保留_batch_snapshot_hash；A/D另比较行中dependency_hash、target_hashes、input schema及SQLite归属。失败为安全WEEKLY_AI_INPUT_INVALID，读取／采用映射503，备份映射BACKUP_DB_LOGICAL_INVALID。

原payload及业务hash规则不变，配置修订仍仅追溯。source_context_hash无法仅由已裁剪依据和冻结稿重算，保留合法审计值；不借本补充假造完整raw快照或把生成时当前日来源强制等同更早周稿的旧来源快照。纯校验补结构和相互一致性，数据库历史来源、任务／执行／候选／采用与回执完整链仍为A/D责任。

审核裁定：payload中game_scope／guidance是实际业务文字，不能因过滤后locations为空而归作“不可比较的审计值”。environment／materials若发送该配置结构，dependencies.config保留该条ConfigBasisV1，即使locations为空；范围／指导参与业务hash，revision身份仍只追溯。已存校验逐值核这些文字，不接受自行复制待验payload来充当expected。对应B纯投影／材料依据及测试仍由B自有文件修正，不变更外层DTO或迁移。

### 9.11 G2页面接线合同（预核后由§9.12激活）

C已对实际API作只读预核；以下先冻结接点，G1完成回执核定后才激活相应文件。采用回执仅有draft身份，必须GET同一草稿并核id／version／hash，不能将身份当正文或接受已被其它操作推进的不同稿。

C自有WeeklyEditorController拟增：`savedDraftRef(): {id:string;version:number;content_hash:string}`、`beginExternalBusy(reason:string): () => void`，以及`reconcileExternalDraft(detail, guard, submitted, acceptedDraft): 'applied'|'stale'|'conflict'`。guard精确identity／input_revision／sequence，acceptedDraft为采用回执的三字段稿身份；沿既有baseline／loadedVersion／applyLaterInput／manual身份合并。旧profile／周／editor或session代回包不改当前页；同一页请求发出后的较晚输入必须保留，不能仅因input_revision变化就丢掉已提交结果或整稿覆盖表单。

创建前沿现有saveCurrent明确保存，失败／冲突／不明为0任务。保存回执确定v8后，即使请求期间又输入而dirty，也仅以该已存v8生成，较晚文字不进入payload、不被回包抹去；不能把确认导出的“必须仍clean”门照搬到该情形。preview／adopt只读已存稿并核实际预览意图，未提交意图变化需重新预览；采用在途之后的新输入沿上述合并保留。

A拟在自有client.ts提供不泄露token的`getSessionEpoch(): number`，setSessionToken实际变化时单调递增；C在每次异步接续核该代及既有profileEpoch／editor身份，不添加宿主AI方法或伪launch ID。普通AI生成等待不持续锁住人工编辑；仅请求协调、明确采用／回执不明及主动打开的预览沿现有统一leave／busy，预览可正常关闭，不因库中存在未采用候选而长期阻塞离开。切页停止轮询不取消任务。

三个明确操作互不连发；四栏按同回执逐项显示部分成功／unknown，候选显示可信具体来源／材料证据及before／after，明示采用。保留schema1 no-op、可信AI原值PATCH、materials null与空串区别及旧确认独立导出；不复验已接受教师清单。本节不激活页面、宿主或构建写权限，下一门另记精确责任。

### 9.12 G1通过与G2精确责任激活

2026-11-03 Codex核定ROOT-G1-gate.json pass=true：四原生最新段自然CLI0；metadata-g1-final.json pass=true，D历史exit8接续及重复进程非自然退出分别保留。327个Python文件在独立验证前后SHA-256不变；独立后端249项、备份／恢复41项、B纯层94项分别通过，原payload／后继provenance／原点换批与改值／行schema和target hashes探针全部拒绝。合成0007的48旧表原值、全部既有历史及5照片文件已核保留。具体证据归[实施核查](../bootstrap/desktop-weekly-ai-review.md)。本节明确放行G2，§9.11接点现在生效。

互斥写权如下，未列路径只读；不fork／另派子代理，不还原他方修改，正式文档与最终审核仍Codex独占：

- A：`frontend/src/d1/client.ts`（getSessionEpoch）、`frontend/src/d1/d1.test.mjs`（会话代验证）、`frontend/package.json`（只补两个新测试入口）；另`backend/tests/local/test_weekly_ai_adoption.py`仅清除已定位行尾空白并核AST未变。其余G1后端本门冻结，实际缺陷另交原A小补丁。
- C新增：`frontend/src/d1/weekly-ai.ts`、`frontend/src/d1/views/WeeklyAiPanel.vue`、`frontend/src/d1/d1.weekly-ai-core.test.mjs`、`frontend/src/d1/d1.weekly-ai-ui.test.mjs`。C维护：`frontend/src/d1/weekly.ts`、`weekly-editor.ts`，`views/WeeklyPlanEditorView.vue`、`WeeklyPlansView.vue`、`WeeklyHistoryPanel.vue`、`WeeklyExportDialog.vue`，既有`d1.weekly-core.test.mjs`、`d1.weekly-ui.test.mjs`、`d1.shell-weekly.test.mjs`。均以前述frontend/src/d1为根，仅实际接点。
- D：`desktop/build_e14.py`、`verify_e14_package.py`、`verify_e14_portable_archive.py`、`desktop/tests/test_e14_build_guard.py`；必要时`desktop/d1_host_api.py`、`maintenance_host.py`、`maintenance_lifecycle.py`及新`desktop/tests/test_weekly_ai_lifecycle.py`、既有`test_d1_weekly_export_host.py`、`test_maintenance_lifecycle.py`、`test_maintenance_host.py`。后端仅必要的`backend/app/local/weekly_plan_snapshot.py`、`weekly_plan_export_service.py`、`weekly_plan_export_api.py`及既有`backend/tests/local/test_weekly_plan_snapshot.py`、`test_weekly_plan_export.py`。备份起点逻辑不在本门重构；模板、Word通用布局、锁文件和依赖不改。
- D追加精确静态测试接点：`desktop/tests/test_windows11_portable_static.py`，只更新与本轮0008及8模块来源相符的tiny-package正向夹具；保留旧revision／错来源拒绝反例，不放宽生产验证器。
- B此门只读审核，不写代码。C不改A共享TS／App／leave，A不改C周编辑器，D不改A/B/C文件；无归属文件先给Codex精确接点，不自行加兼容别名。

G2可验证源码／自动与新材料Word数据输出；冻结构建须待页面与共享接线停写、Codex来源审核后另发具体新根／freeze执行指令。已授权真实应用AI只在新合成副本、既有标准API正常凭据通道中按明确操作进行，不使用Go开发凭据、不自动重发unknown。已知SAC机器不运行新旧EXE/helper；本轮构建只作静态／归档核验，不继承旧包运行或教师结论。

### 9.13 G2独立审核接点澄清

候选的raw存储、模型wire及candidate_hash输入继续保持材料证据五键。既有`materialized_candidate()`向已认证candidate detail提供的`data`是只读展示投影：材料证据另有经本input typed manifest核定的`source`第六键；它不是raw候选或重新计算candidate_hash的输入。沿此现有接口，不新增第二套handle分配规则或回传manifest。页面按实际source显示日来源日期／内容版本、手工或AI游戏名称、配置版本／名称及对应原文字段；精确原文仍为quote，身份／hash不显示。采用前后按games／columns／materials具体目标格式化，游戏保留日来源与AI补充的区别，不以通用过滤丢失来源类别。相应测试须使用真实API形状，不以假标量或mock格式化器替代。

独立SFC探针复现的材料编辑区非响应、采用GET及候选刷新漏核会话代，属于§9.11既有要求的实现缺陷，由原C在自有G2文件修复。所有异步续接绑定发起时的controller／plan／profile／session及组件生命周期，每次await后先核有效性再更新本页；旧请求不能改发新周。重进页面应可读取已存任务与候选，分页不漏项。未知创建／采用保留原ticket、请求及载荷，不被新动作覆盖；预览还须核实际选中候选集合，选择变化不允许采用旧预览。任务动作按allowed_actions与对应未知任务的明确费用确认执行，不把先前勾选扩为其他任务授权。材料首次采用立即出现编辑区，晚输入与冲突恢复沿同一编辑器合同。

材料用户输入立即进入同一编辑器的dirty／统一保存与leave协调，不能只存在面板局部textarea中，等专用按钮才登记。专用保存按钮调用同一saveCurrent；保存／采用回包后的重显仍按实际提交投影保留较晚材料输入，不由detail watcher无条件覆盖。未触碰的null和明确清空的空串继续区别，可信provenance由服务端维护。

创建／预览的面板请求协调在等待saveCurrent之前占位；保存等待期间再次点击不能开出第二个请求、替换前个未知ticket或复用Set busy reason提前解除保护。该占位不阻止同一编辑器完成自身保存，也不覆盖较晚人工输入；保存失败／冲突／不明或上下文失效须正确释放对应占位。后台任务普通等待仍按§9.11允许手工编辑。

同一有效上下文内，候选刷新也以本面板最新读取代次发布；旧批迟到读取不能覆盖已显示的新批。保存于Vue票据中的controller可能被ref包装，身份比较须识别同一raw对象及其Proxy，仍拒绝真正更换的controller；测试使用真实shallow props／实际控制器，先证明正常预览采用可成功，再证明失效回包被拒。

任务／候选读取失败在面板内部映射安全提示，保留原未知票据并允许只读刷新；挂载的void读取不产生未处理拒绝。旧上下文／旧读取代次的失败不得改新页。已接受新批而尚未读到状态时显示待核对，不把空读取误作任务failed，也不把旧批候选留在新批标签下。

### 9.14 G3纯边界验证补充责任

Codex覆盖核对后，原B可仅在`backend/tests/local/test_weekly_ai_contracts.py`、`test_weekly_ai_inputs.py`、`test_weekly_materials.py`、`test_weekly_plan_content.py`补现有合同的边界证据：材料项数／文字／quote／合成正文／provenance及整稿大小，严格JSON，以及家园日历±7日／去重／覆盖不足。测试必须先有合法基线，再单独越界；不以另一个坏字段提前拒绝冒充所验限制。B生产纯模块和A/D接点保持冻结；发现实现缺陷先交Codex定位，不自行扩写。其余G2互斥责任不变，不改依赖／conftest或新建共享夹具。

### 9.15 G2任务动作回执读取接点

实际loopback HTTP复核确认：周作用域`/api/weekly-plans/{plan}/ai/operations/{request}`只读四种创建／采用回执，任务cancel／resume／retry回执不属此入口，404不代表未提交。任务动作沿既有`GET /api/local/ai/operations/{request}`，响应精确`request_id,operation_kind,result,committed_at`，result为既有TaskOut；不为前端错误接线放宽周回执白名单或新增后端路由。

C仅在自有weekly-ai.ts补`taskOperation(requestId)`只读适配，面板queryAction使用该适配；续接先核原session／profile／controller／plan，再核request_id、`ai_task_cancel/resume/retry`对应原动作、result.task_id、source_kind=weekly_plan及source_id／weekly_plan_id均为原周。核对失败保留原ticket，不按其他任务／周的回执解除保护。原create／adopt查询仍用周作用域入口，动作同键重送仍用原URL、request_id、expected_execution_id及ack，不重建请求。


### 9.16 真实周请求的有界流式响应修复

用户已明确允许多次显式重试并接受重复计费，接口明确余额不足时告知；该授权不启动自动重试或真实业务资料发送。两次同一合成task的显式重试安全detail均为`body_too_large`，后次实际进度计数为121帧、13,104思考字符、答案0字符；不保留思考正文。原1MiB限制计入HTTP chunk／SSE事件开销，不能据此声称最终候选超过1MiB。原未知尝试和草稿v2保留。

本段Codex明确激活原A独占的最小补丁：`backend/app/local/ai_transport.py`、`ai_executor.py`、`ai_worker.py`、新增`backend/tests/local/test_weekly_ai_transport_bounds.py`，必要时仅其原有`test_weekly_ai_service.py`／`test_d2_w3_executor.py`／`test_d2_w3_transport.py`同步断言。B/C/D生产代码冻结，Codex仍仅文档／审核／独立验证。无迁移、DTO、依赖或页面改动。

只对六种周文本task引入固定16,384输出token预算与16MiB流式wire预算，最终候选content仍最多1MiB，HTTP头与单事件／未完成缓冲须有独立有限上限；不得把wire上限当最终内容／IPC上限。非SSE响应、普通日文本和观察vision保持既有1MiB响应及请求行为。预检与实际worker必须使用同一请求参数，未知／伪造周预算值在发送前拒绝，不能让一般调用任意放宽预算。不改变thinking开关、reasoning effort或供应商配置；沿标准Chat Completions的`max_tokens`约束，保持stop／DONE／完整UTF8／长度／chunk终止和严格JSON全部成功条件，length结束仍失败，不返回部分候选。

先用真实transport的合成合法SSE证明：small final JSON、较多reasoning／事件使wire超过旧1MiB但小于新预算时能完整成功；相同默认日路径仍拒绝。另证新wire／content／单事件上限各有合法基线及越界反例、缺stop／截断／未知预算发送前拒绝、worker实际请求与预检一致、0自动重发及0自动采用。不得只测request字典而冒充实际传输。若16MiB与单事件限制无法保持独立语义，先报告Codex裁定。

官方依据（2026-11-03核）：[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)定义`max_tokens`及`length`结束，[Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)定义默认思考与独立开关；本段不改变模式。预算是本地有界工程策略，不宣称官方保证每个答案在此预算内成功。补丁自然停写后须Codex独立回归和合成真实请求复核，再冻结新包；不把此前G1或285文件freeze倒填为新补丁证据。

### 9.17 页面预保存与任务动作互斥

Codex继续反例`ROOT-G2-presave-action-probe-r01`确认：create等待同一慢保存时，action(cancel)仍进入发送，最终为cancel／games两个并行操作。延续§9.13的同一面板协调要求，原C仅在`WeeklyAiPanel.vue`及`d1.weekly-ai-ui.test.mjs`修复：任务动作须服从预保存阶段的panelRequestFlight，预览采用同样核对，读状态不计写操作。补慢保存期间cancel／retry及预览期间动作负例，保存释放后正常动作须仍可进入；原票据／逐任务ack不丢失，不把全部动作误拒当通过。原C同会话停写后Codex独立复核。


9.16补充裁定（原B只读审核后）：原A可追加原自有`ai_task_service.py`的serialized_request_bytes／周预检参数一致性，仍不得修改任务业务状态机。周单事件／未完成事件缓冲上限固定为`2 * 1MiB + 16KiB`（允许1MiB content的JSON转义开销），周result IPC单独固定为`6 * 1MiB + 16KiB`、parent／worker一致，默认日／vision IPC不变。只在周SSE路径强制stop与DONE及完整EOF，拒绝非空未结束事件／DONE后非空data，不能因先遇stop而忽略截断尾。header／Content-Length校验必须按已认证周SSE分支选择wire预算，周非SSE继续1MiB。预算只由精确六task_type／weekly source映射，不从用户payload自由读取；请求预算、wire预算、content预算、事件预算和IPC预算分开验证。Root最终只接受真正通过send／worker通道的合法对照及越界证据。

### 9.18 真实应用提示合同的完整说明

本节原default_revision=2初案在真实sync结构守卫核对后已被§9.19取代；原始诊断与B首段结果保留，实际版本只能按§9.19。

修复后真实响应已完整通过transport，但游戏业务parser拒绝；不能把应用没有向模型说明的格式要求归为供应商质量。Codex源码核定：游戏output_schema只列槽名、未说明source／ai_supplement对象；材料items只写object，未列text／origin／evidence_refs及codepoint证据。明确交原B独占`weekly_ai_contracts.py`及原`test_weekly_ai_contracts.py`／`test_weekly_materials.py`补完整schema与中文默认guidance，严格对应现有parser，不改变raw输出合同／CONTRACT_VERSION、handle规则、解析器或采用行为，不为模型放宽校验。其他源码冻结。

游戏说明必须覆盖三个槽及focus的null／source／ai_supplement、全部精确键与必需nullable键、m/p来源类别、c类basis_handles、同名集体限制及不伪造来源；材料说明须覆盖text300／origin两类／extracted需准确证据而suggested必须空证据、source_handle／field_path／start／end／quote、Unicode codepoint且end-exclusive及空items语义。schema应完整给出每层properties／required／additionalProperties，不让模型猜内部字段。

只把实际变更的默认定义升到default_revision=2，保留contract_version=1及数据库旧default_revision=1行、已存个人head与任务冻结输入。runtime按既有注册逻辑新增修订，不能原地重写旧bundle／旧任务；旧failed/unknown尝试保持历史。新验证用明确新操作取得新默认head，不能重试旧冻结task而冒称使用新提示。补真实输出各合法形状与schema说明一致、非法键仍拒绝及修订身份的合成回归；B停写后Root独立纯层、周服务／API／采用／备份受影响验证，再做新合成请求。现有真实AI多次显式操作授权适用，不要求重复确认。

### 9.19 提示契约v2与历史v1的精确兼容核定

实际`prompt_bundles._contract_shape`按输入／输出schema及guidance键集合冻结同一契约，故不能用默认修订绕过结构变化。Codex核定：仅`weekly_games_select`及`weekly_materials_generate`的**提示契约**current=2/default_revision=1；四栏目继续1/1。既有raw输出、input_schema_version=1、周content schema2、迁移0008及解析规则不变；`CONTRACT_VERSION=1`仅保留既有raw定义身份，不用它推导所有提示任务的当前版本。

原B独占`weekly_ai_contracts.py`及其两份自有测试，提供纯接口`prompt_contract_version(task_type: str) -> int`及`supports_prompt_contract(task_type: str, contract_version: object) -> bool`：游戏／材料支持历史1和当前2，栏目仅1，未知task或bool／非正整型版本不得被接受；current helper未知task抛既有安全合同错误。bundle仅发布各自当前版本，完整嵌套schema／中文说明延续§9.18；不修改任何旧DB行／head／冻结任务。

原A独占`weekly_ai_candidates.py`及原`test_weekly_ai_service.py`／`test_weekly_ai_api.py`／`test_weekly_ai_adoption.py`：候选eligibility按该task当前提示契约判断，当前2候选可用、旧1游戏／材料为contract_obsolete但详情／历史链保留；栏目1仍可用。沿既有prompt sync新增2/1行，原`prompt_bundles.py`不放宽结构守卫、不自动覆盖个人文本或当前head。旧个人head按既有契约适配流程处理，新0007档案首建周head按2/1。若实际注册还需改A文件，先报Codex，不扩大责任。

原D独占`backup_validate.py`及`test_weekly_ai_backup.py`：完整链先按既有身份／hash／原点验证，再调用B支持谓词；只允许该task已知1／2组合，不接受任意正整数。旧v1候选／采用／确认／回执在备份和恢复中保持，新2及四栏目1混存同样完整通过；不把旧候选过期视为坏历史。补v1/v2真实SQLite、未知版本／栏目2拒绝及明文恢复证据；0007日计划／观察／照片及历史保留测试不得弱化。

Root最终审核新helper／原生互斥范围、纯层、真实创建／采用／历史与备份，并用已准备的新合成原G17副本取得真实`contract_version=2/default_revision=1`执行证据；旧合成task的5次尝试及旧提示1保持。B先交纯接口，A／D读取该实际接口后在互斥文件内并行，任何缺口交Root。仍无新迁移／DTO／依赖／教师流程／签名或远程操作。旧首段“布尔guidance不合法”不是阻断：实际A `_weekly_bundle_manifest`已将布尔转为字符串；不因此改同步层。

9.19接线补充：实际`ai_task_service.SUPPORTED_CONTRACT_VERSIONS=(1,)`还控制创建／pending复核／领取，原A已报超出本段责任。Codex追加原A独占`ai_task_service.py`，仅用task_type感知支持谓词替换`_require_ai_ready`、`_verify_pending_preconditions`、`_pick_candidate`的版本门：周六任务调用B支持谓词，日／观察继续只支持1，不把全局SUPPORTED改为(1,2)。既有head适配、版本pin、permit／generation／状态机／发送与重试规则保持。可补原`test_d2_w3_tasks.py`对照周2可建／领、日与观察2拒绝及旧head保留；相关函数精确核定后受影响回归须通过。
