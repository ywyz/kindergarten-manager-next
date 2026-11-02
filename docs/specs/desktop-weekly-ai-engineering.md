# 桌面周计划 Q5/Q6 工程合同与文件分工

更新：2026-11-02。状态：**合同准备，未放行业务实现**。产品依据为[周计划§9及Q5/Q6](desktop-weekly-plan.md)，Q1–Q4接口保留于[首片工程](desktop-weekly-plan-engineering.md)。本轮仅原生OpenCode／Command Go并行只读起草、Codex最终审核与文档整理；[假供应商矩阵](desktop-weekly-ai-validation.md)全部未执行。实际会话、审核修正和边界见[准备核查](../bootstrap/desktop-weekly-ai-preparation-review.md)，唯一派发入口为[current](../tasks/current.md)。

2026-11-03接续：已拉取`0285a7c`的另机测试收口与五文件最小修复，[目标结果](../bootstrap/desktop-weekly-target-test-closeout.md)已整体接受；本文仍为准备合同。后续G0以新HEAD复核导出／错误投影接点，0007现有数据及拟议0008迁移身份不因文档合并改变，业务实现仍未放行。

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
