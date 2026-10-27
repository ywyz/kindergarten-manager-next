# D4-E：游戏观察记录工程设计

更新：2026-10-28。**E01–E14及E13六份Contract设计保持；基础、材料、保存历史及图文服务层的前片结果保持，E09／E10本机API、观察编辑与查阅列表限定工程核查通过。** 最新[独立核查 §6](../bootstrap/desktop-game-observation-pages-review.md#6-最终独立结论本片限定工程核查通过)为全local728、桌面285、最终全前端（观察38）、HTTP37／WebView2 9项及实际勾选采用v14通过。按授权由原OpenCode正常提交推送后停在本片；批选／排序、Word／原生另存为、整包、完整A01–A22及发行仍后置或未验，不自动启动后续切片。

原OpenCode会话`ses_ead8af71dffeJphI1NOWg4jZgI`使用`opencode-go/deepseek-v4.1-flash#default`、`plan`代理交付方案。Codex退回两轮问题、补充冷迁移问题，并核定K01–K08修正；原会话最终逐项接受。本文由Codex归并为唯一有效工程方案，取代各轮回复中的冲突表述。原始回复及审计证据保留位置见核定记录，不另存提示词副本。

2026-10-26同一会话提交E13草案、按D01–D09修订并接受V01–V08及必要澄清；Codex核定后归并[观察主Contract](../modules/game-observations.md)与五扩展，同步本文的hash、来源／材料关联、回执及导出协议。旧草案相反句作废；设计归并不等于实现或运行通过。

## 1. 文件范围及依赖顺序

下表为完整工程计划路径，包含本片已实施与其余尚未实施项目；不作为已修改文件清单。实际E01／E02／E04文件（含observation_terms.py）、测试与范围以独立核查报告为准，不扩张后续职责。

| 范围 | 拟新增／改造路径 | 职责 |
| --- | --- | --- |
| 观察业务新增 | `backend/app/local/observation_validation.py`、`observation_service.py`、`observation_assets.py`、`observation_history_service.py`、`observation_ai_service.py`、`observation_api.py` | 字段、资料／草稿、受管材料、历史、业务AI投影与采用、本机路由 |
| 数据及接入 | `backend/app/local/models.py`、`schemas.py`、`api.py`、`app.py`、`runtime.py`、`profile_service.py` | 新模型／协议、应用接入、守卫后提示词同步、首次档案种子；不改旧数据含义 |
| 本地迁移新增 | `backend/migrations_local/versions/20261025_0006_local_game_observations.py`（拟名） | 同一DDL修订创建观察表、扩AI来源及bundle任务枚举；接当前`20261023_0005_local_history.py`，不另设0007种子修订，不改旧迁移或MySQL链 |
| 共用AI基础设施 | `backend/app/local/ai_inputs.py`、`ai_task_service.py`、`ai_executor.py`、`ai_worker.py`、`ai_transport.py`、`ai_candidates.py`、`ai_adoption.py`、`prompt_bundles.py`、`prompt_service.py` | 来源适配、不可变输入、claim／dispatch／worker视觉协议、验证与保存候选、提示词；业务采用归观察模块 |
| 进度与关闭 | `backend/app/local/ai_progress.py`（若来源展示需要）、现有本机关闭任务快照路径 | 保留思考／阶段反馈；全局关闭统计两类任务，旧日计划查询只返回日计划 |
| Word | 新`backend/app/services/word_export_observation.py`；改`backend/app/local/export_service.py`、`backend/app/services/word_export_docx.py`、`word_export_mapping.py` | 三模板渲染、固定导出快照、受限临时文件交接；日计划导出语义保持 |
| 模板新增 | `backend/app/assets/word_templates/observation_public.docx`、`observation_indoor.docx`、`observation_outdoor.docx` | 经审查纳入用户三模板的结构与样式，不自动带入成品儿童内容 |
| 前端新增 | `frontend/src/d1/observation.ts`；`frontend/src/d1/views/ObservationListView.vue`、`ObservationEditorView.vue`、`ObservationHistoryPanel.vue`、`ObservationExportDialog.vue`、`ObservationPhotoGrid.vue` | 接口、列表、编辑／候选、历史、选集／缺项确认、图片排序说明 |
| 前端接入 | `frontend/src/d1/App.vue`、`views/WorkbenchView.vue`、`types.ts`、`bridge.ts`、必要的`leave.ts`；`frontend/package.json`仅必要测试接入 | 实际工作台入口、编辑桥、离开／更新握手，复用已选技术栈 |
| 宿主／依赖／打包 | `desktop/d1_host_api.py`、`d1_main.py`、`build_d2.py`；`backend/pyproject.toml`、`backend/uv.lock`、`desktop/requirements-d1.lock.txt` | 新受限导出桥、关闭协调、图片插件／模板／许可打包；业务依赖仅在backend声明 |
| 验证新增 | `backend/tests/local/test_observation_*.py`、`desktop/tests/test_observation_*.py`、`frontend/src/d1/d1.observation*.test.mjs`（拟名） | 分阶段合成／故障／回归，不表示这些文件已存在 |

`desktop/requirements-d1.in`只声明桌面／测试／打包依赖，不重复加入Pillow业务依赖；若不需调整现有打包工具，该文件不变。锁定更新使用既有单一解析流程，不`--upgrade`无关包。现有`migrations_local/env.py`、`d1_digest.py`的事务／保护机制是复用及验证对象，不预设需要修改。

准入顺序：E13设计核定 → E01／E02／E04基础通过 → E03材料通过 → E05／E08保存历史通过 → **E06／E07视觉候选服务层已通过限定工程核查** → E09／E10入口列表 → E11／E12导出宿主 → E14集成。本轮必要真实AI测试已按独立合成资料完成DeepSeek闭环，MiMo仅合成；后续不自动启动，系统边界改变先ADR。最新范围见[当前任务](../tasks/current.md)及[本片核查](../bootstrap/desktop-game-observation-ai-review.md)。

## 2. E01：字段、权威及校验

Canonical payload使用下列平铺名称，服务保存规范JSON；不使用不同章节的`record/content`嵌套别名：

| 字段 | 类型及含义 |
| --- | --- |
| `record_type` | `public/indoor/outdoor` |
| `observation_date`、`start_time`、`end_time` | 可空ISO日期、`HH:mm`；不限制上课日 |
| `term_id`、服务端`term_snapshot` | 可空已有学期及其名称／范围快照；不能由页面伪造快照 |
| `school_name`、`class_name`、`observer_name` | 可空本份文字，只有新建时带入当前档案 |
| `adult_count`、`child_count` | 可空非负整数；儿童数为总参与人数，不从图或目标数推算 |
| `age_years` | 本份单一可空非负整数，Word如“5岁”；不加年龄上限、不逐人异龄 |
| `subjects` | 有序`[{name: string}]`；去空项，保留姓名顺序，不擅自合并同名 |
| `environment` | 可空文字 |
| `observation_goal`、`observation_process`、`support_strategy` | 可空文字，分别为观察目标／观察记录／支持策略 |
| `analysis_evaluation` | 固定`health/language/social/science/arts`五键，值可空；对应健康／语言／社会／科学／艺术 |

照片独立关联，manifest参与聚合hash，不在payload与另一套照片JSON间形成双重权威。文本统一换行并处理首尾空白，不截断正文、不改写措辞。固定五领域空骨架不是实际正文；“证据不足”是有效正文。

缺项、非法值、矛盾值分别处理：

- 草稿可缺项；非法日期／时间语法、负数／非整数、未知类型／资产、跨记录材料及协议超限拒绝并解释，不静默改值。
- 总人数少于重点人数、结束早于开始等语义矛盾提示复核，不自行加保存／导出硬阻断；AI携带相关警告，不替教师改资料。
- AI最少姓名、统一年龄、环境及一张有效照片；其他资料缺项只提示。无图仍可手写、保存和导出。
- 导出独立判断：任一栏有实际正文或有有效照片即非空；只有表头资料、四栏均无实际正文且无有效照片才为空。缺项确认后留空栏；完全空记录／坏图先处理，不静默删记录或漏图。

Canonical总字节使用单独技术保护参数，约1MiB仅是现有文本边界的设计参考；最终值须容量核查，不新增200字、姓名数等业务额度，不放宽旧文本AI保护。

## 3. E02：模型、约束及迁移

### 3.1 观察业务表

| 拟表 | 关键字段／约束与权威 |
| --- | --- |
| `local_observation_records` | `id`稳定PK、`creator_profile_id`→`local_profile.id`；本份表头／学期／姓名检索投影；`current_draft_revision>=1`、可空`current_version>=1`、创建／更新时间。`UNIQUE(creator_profile_id,id)`；无日期／对象／时段业务唯一键 |
| `local_observation_drafts` | `observation_id` PK/FK、`revision>=1`、`payload_json`、`payload_hash`、更新时间；与draft照片一起是当前权威。record中的revision及检索投影同事务更新 |
| `local_observation_versions` | `id`PK、`observation_id` FK、`version>=1`、payload/hash、source、创建者／时间；`UNIQUE(observation_id,version)`及`UNIQUE(observation_id,id)`；不可变历史 |
| `local_observation_assets` | `id`PK、`observation_id` FK、服务生成相对路径、显示名、真实MIME、原字节SHA256／大小／尺寸／方向；`UNIQUE(observation_id,id)`，不保存外部原路径 |
| `local_observation_draft_photos` | `observation_id,asset_id` PK、`sort_order>=0`、可空`caption`；`UNIQUE(observation_id,sort_order)`；FK `(observation_id,asset_id)`→assets同序唯一键，防跨记录 |
| `local_observation_version_photos` | `version_id,asset_id` PK，加`observation_id,sort_order,caption`；唯一`(version_id,sort_order)`；FK `(observation_id,version_id)`→versions及`(observation_id,asset_id)`→assets同序唯一键 |
| `local_observation_operations` | `id` PK、`profile_id,request_id`唯一、operation kind、record、服务端稳定fingerprint、status/result、时间；含恢复的观察业务主回执，同ID异内容拒绝 |
| `local_observation_restores` | `operation_id`唯一FK关联主回执，record、source/before/result版本、changed、term decision／有效hash；source/result分别同record复合FK→versions(observation_id,version)，不另设request_id权威 |
| `local_observation_restore_previews` | token摘要、profile/record、source/base/effective/材料hash、request id、期限／消费；独立预览，未提交不要求成功operation；不存页面路径 |
| `local_observation_ai_provenance` | 新版本、record、candidate及source kind/profile、所采用targets、输入／输出hash、时间；同记录复合FK连版本与candidate，作为本候选已采用输出的账本 |

`record.(id,current_version)`以deferred复合FK指向`versions.(observation_id,version)`，新记录尚无保留节点可为NULL。历史不设全局内容hash唯一键：回到过去内容可建立新节点，只与**最近保留节点**判无变化。

拟local_observation_asset_derivatives保存record/asset、用途／参数版本、hash、尺寸/MIME及受管路径，追加不覆盖；除UNIQUE(observation_id,id)，增加UNIQUE(observation_id,asset_id,id)。拟local_observation_ai_input_photos以非空profile/kind/source/input链连input，(observation_id,asset_id,derivative_id)同序FK连该派生三元键，并连同record原asset，固定顺序／说明／hash及UNIQUE(input_id,sort_order)；显式observation_id非空、kind为game_observation且source_id=observation_id。不能仅用两个同record FK而把A图挂到B图派生，不能只用JSON丢持久引用。

拟local_observation_export_snapshots、export_tokens保存固定临时manifest及受限token，local_observation_export_attempts保存宿主报告回执；不是第二内容权威。最小字段、会话／归属、资源生命周期及外部结果来源见[Contract§7](../modules/game-observations.md#7-导出与-word)，宿主不直连SQLite。

列表索引覆盖`(creator_profile_id,observation_date,id)`、`(term_id,observation_date,id)`、`(record_type,observation_date,id)`、更新时间及历史`(observation_id,version)`；照片／input关联索引覆盖其FK及顺序。业务读取如发现draft与投影revision/hash不一致，明确存储错误，不静默用投影覆盖权威。

### 3.2 共用AI来源：非空复合链

复用一套AI状态机，**不复制观察专用调度／执行状态机，也不伪造日计划**。四个AI表统一`source_kind='daily_plan'|'game_observation'`、非空`source_id`、可空`observation_id`；inputs/candidates新增非空`profile_id`及到`local_profile.id`的FK，tasks/executions保留已有profile及FK。观察任务固定为`game_observation_generate`、`game_observation_rewrite`，旧三个日计划任务名保持。

- inputs的旧`daily_plan_id/content_id/content_version/target_grade`改可空；仅在观察分支为空。其余三个表仅把各自已有`daily_plan_id`改可空，不凭空新增content/version/grade列。
- 每表分支CHECK显式要求来源ID、关联ID和任务名匹配；输入额外校验content/grade。例如日计划分支`daily_plan_id IS NOT NULL AND source_id=daily_plan_id AND observation_id IS NULL`，观察分支反之；绝不依赖SQLite允许NULL通过的比较表达式。inputs日计划分支显式要求content/version/grade非空且grade在原三值中，观察全部为空。
- input保存`source_revision`与源aggregate hash作为来源元信息；观察revision来自成功保存的draft。input自身冻结payload、资料、照片manifest及依赖。**只FK稳定record，不把草稿revision外键指向历史version或不存在的versions.revision。** 其他表通过input读取该来源，不维护另一套revision权威。
- input观察来源以`(profile_id,observation_id)` FK到records的`(creator_profile_id,id)`。新增来源链如下，所有profile/kind/source/input/task/type锚点非空；旧daily分支FK及其父唯一键全部保留。

| 父表必须保留／新增的UNIQUE，列顺序固定 | 子表复合FK，同序 |
| --- | --- |
| inputs `(profile_id,source_kind,source_id,id,task_type)` | tasks `(profile_id,source_kind,source_id,input_id,task_type)` |
| inputs `(profile_id,source_kind,source_id,id)` | input_photos `(profile_id,source_kind,source_id,input_id)` |
| tasks `(profile_id,source_kind,source_id,id,input_id,task_type)` | executions `(profile_id,source_kind,source_id,task_id,input_id,task_type)` |
| executions `(profile_id,source_kind,source_id,id,task_id,input_id,task_type)` | candidates `(profile_id,source_kind,source_id,execution_id,task_id,input_id,task_type)` |
| executions旧`(task_id,id)` | tasks旧`(id,current_execution_id)`，deferred；未开始可NULL |
| candidates新增`(profile_id,source_kind,source_id,id)` | 观察provenance同记录／profile／kind的candidate引用 |

保留旧input内容三元FK、task/input及execution/task和candidate/execution复合FK、所有配置／提示词FK、candidate旧`UNIQUE(daily_plan_id,id)`及其日计划provenance依赖、execution`UNIQUE(task_id,generation)`、candidate`UNIQUE(execution_id)`。新观察分支的旧daily FK因NULL跳过，由新增**非空**来源链保证隔离，不能只靠服务校验。

旧candidate FK引用列为(execution_id,task_id,daily_plan_id,input_id,task_type)→executions的(id,task_id,daily_plan_id,input_id,task_type)，同时保留源码既有父UNIQUE(daily_plan_id,task_id,input_id,task_type,id)，不混淆引用列与父键声明顺序。完整来源／材料键见[Contract§3](../modules/game-observations.md#3-对象所有权来源链与迁移)。

同record/type活动任务检查沿既有调度语义适配；不能覆盖在途／未知结果或因新来源误复用旧task。调度检索索引覆盖profile/source/type/status，所有旧日计划API显式限制`daily_plan`并保留原响应，不把通用来源结果送给旧页面。

### 3.3 冷升级、回填及种子

单一0006 DDL修订先创建观察核心及关联，再重建受影响AI四表和`local_prompt_bundles`任务枚举约束，允许五种任务；不保留旧稿的0007种子修订。两个personal prompt表没有task_type CHECK，不能因误判而重建；保留其bundle FK和原revision/action约束。

迁移预检完整旧来源链：input能找到日计划创建者，task→input、execution→task/input、candidate→execution完整且profile一致。旧行新增列回填`source_kind=daily_plan,source_id=daily_plan_id`；input profile从计划创建者取，candidate profile从execution取；各自旧列保持字节／规范值及行数，观察列为空。缺失／不一致就失败回滚，不猜关联、不修旧数据。

SQLite精确顺序为预检→观察基础表→inputs→tasks→executions→candidates→prompt bundles→观察采用等剩余关联。每个重建采用“建最终结构的`_new`表→`INSERT SELECT`复制旧列原值并回填新增列→drop旧表→将`_new`改回原名→恢复索引”；FK使用最终表名。不得先把旧父表rename成临时名，以免SQLite改写其他表的引用；实际版本行为必须用含旧provenance的合成库验证。任务／execution循环FK仍deferred；每个被引用复合键建立同序UNIQUE，保留所有旧索引／约束及旧列顺序。沿现有`env.py`在事务前关闭FK、`BEGIN IMMEDIATE`、迁移及guard、`foreign_key_check`、COMMIT、恢复FK；revision不得内部提交、切pragma或关闭摘要保护。提交前任一步失败须整体事务回滚，不留半套`_new`表；COMMIT后仍由runtime既有guard复核，失败只能拒绝本次启动并保留可核实的升级前备份，不能声称已经回滚或自动恢复。后续current-head启动也不等于先前失败的复核已重新通过。

**迁移不向已有prompt表插入新观察种子。** `d1_digest`摘要覆盖升级前全部业务表；提前插行会破坏保护。只有迁移及提交后guard都成功，才在既有启动同步注册观察bundle及heads：

1. 无profile：注册bundle即可；首次建档通过现有`effective_prompt_seed`动态初始化。
2. 已有profile：幂等补齐新任务个人版本／heads，同事务，不覆盖旧日计划指导。
3. 种子后全表摘要可因合法新增行变化；检查的是原daily行子集原值不变，以及第二次启动相对第一次成功seed状态不再增行。不能要求seed后完整摘要仍等于迁移前。

迁移与种子沿现有升级副本／guard机制处理，实际前提交回滚、提交后拒绝启动／备份及独立合成验证见E01／E02／E04报告；不修改真实体验库，不改保护求绿。空库、真0005富源、含候选／历史、重建中断、guard前后失败及无profile／已有profile／重启均有本片范围内证据；不是完整材料／保存／AI流程验收。

## 4. E03：图片生命周期与资源

拟支持JPEG、PNG、WebP、静态GIF、BMP，按真实内容识别并解码，不信扩展名/MIME；动画明确拒绝，不偷偷取首帧。EXIF方向在派生时纠正，原字节不改；透明转JPEG使用白底。编码器／图像异常、像素炸弹、ICC/EXIF损坏、扩展名伪装均有明确失败。

原图是应用管理的不可变副本，根为`runtime.data_dir/observations/assets/<record>/<asset>/`；不依赖用户外部路径。AI图为去元数据工作副本，导出图独立按版面派生，均与原图分离；已经被input或历史引用的原图／工作图保留。当前移除只解除当前关联，首期不自动清理历史、资产或失败现场。

导入顺序：流式staging→事务外受控串行验证/解码/方向/派生/hash→同卷原子落受管不可变文件→短DB事务同时写资产、照片顺序/说明、draft revision/hash、record投影和操作回执。文件先成功DB失败可能留下孤儿，明确失败并保留现场；绝不报导入成功或把未提交照片算入稿。DB成功响应丢失按request id读回。磁盘满／进程中断／重开均不得丢失其他已提交资料。

材料层承担实际解码与派生，发生在写事务外；AI网络worker只读取已验证图文，不混用“只有worker解码”与“父进程提前建图”两套假设。冻结input前工作图必须完成且hash固定。导出也逐图处理，生成过程不占长DB事务。

**E03当前参数及独立复核：** 源文件同时满足25MiB、40,000,000像素及单边8192；AI派生长边2048／JPEG q85／目标2MiB，超额按0.85缩放，最多6次编码，未满足明确失败；导出预派生长边2400／q90。原字节不改、透明白底、元数据清除；参数版本分别为ai-v2-2048-q85-target2mib-scale085、export-v1-2400-q90。解码串行，先缩至master再方向校正，1024MiB为实际管线工作集验证阈值，不是运行时硬RSS上限或完整应用内存承诺。依赖Pillow13.0.0已锁定，原包版本保持，源码／依赖／容量证据见[E03核查](../bootstrap/desktop-game-observation-assets-review.md)；最终630项全local已通过。E06请求／IPC、E11版面／Word清晰度与总文件容量另验。

不设未经确认的30图、30姓名、200份等业务额度，也不以样例2/3图作限额。所有已保存照片参与明确AI生成；超预算说明具体原因，不静默选子集、不新增独立AI选图流程。请求大小、供应商图数、内存、磁盘空间、导出体积各自校验；若最终保护参数显著影响教师流程，交用户决定，不自行降低产品要求。

## 5. E04：日期、归属与快照

新建默认今天，可任意有效日期；匹配唯一已有学期，否则未归属。无日期可后续显式选择已有学期；多个匹配不猜，明确选择。已有稿清空日期默认保留既有term及快照；只有明确选未归属才清空。

改日期跨学期返回确认需求，允许保留当前、选择匹配／其他已有学期、未归属；取消不提交该变更并保留UI输入。日期与明确学期范围不符提示，不静默纠正。旧范围缩小／班级改名／升班不改旧资料或隐藏记录，列表按存储归属查。

恢复完整历史日期与学期快照一并展示；以历史完整payload为底，只有用户明确`term_decision`才覆盖归属／服务端快照。不存在／失效目标学期须重新选择或保留可用历史归属，不改学期配置、不凭日期自动挪动。

## 6. E05：自动保存、历史节点与并发

`draft.revision`是每次当前稿变更的单调计数，`versions.version`是保留历史序号；`record.current_version`指后者，`current_draft_revision`指前者。禁止`current_version_id/current_draft_id/H.revision`等混用。

payload_hash唯一为SHA256(canonical_json([平铺canonical_payload,ordered_photo_manifest]))，使用确定键序／UTF-8，换行及空白按E01规范；term_snapshot只在payload出现一次。manifest含asset_id、原hash／真实格式／尺寸／方向／顺序／说明，时间戳、revision及投影不入业务hash；AI工作图及实际发送依赖另hash。

auto只更新draft/照片/投影/回执，不造history。手动保存、采用、离开、恢复前／导出前保存相对**最近保留节点**判aggregate hash：有变才追加节点，无变不造；auto已成功、isDirty=false也不能跳过待留节点。通用save_reason仅auto/manual/leave/pre_restore/pre_export，adopt/restore独立受校验，不能改保存原因绕过token／账本。恢复有变才新version，无变不增draft revision或history；不按全库hash去重。

同编辑会话串行保存、服务expected revision及短`BEGIN IMMEDIATE`；409冲突保留输入，不覆盖。IME composition settle后再flush；离开请求在save成功后重核identity/edit epoch与最后输入。超时／回包丢失按同request id回执和draft revision/hash读回，不能把旧保存成功当新输入成功。不承诺崩溃时内存输入零丢失。

所有写先在会话／基本语法后按稳定服务端fingerprint读本域回执，匹配直接返回；才对无回执请求做token／当前版本／材料／适用AI就绪等预检，写事务内再查回执和复核绑定。fingerprint不依赖后来变化的当前内容或过期token可读性。观察operations、共享AI operations、宿主报告分域，旧daily不重构，见[Contract§4](../modules/game-observations.md#4-接口幂等与回执)。

## 7. E06：图文执行契约

只接DeepSeek官方与MiMo标准API，能力来自固定合同／适配，不由页面vision_mode打开。提交时冻结input业务资料／实际正文／warning／schema及全部照片、原图／工作图hash、顺序／说明／派生参数，引用稳定record，不强造历史。claim／开始执行取最新有效配置及已适配提示词，execution记录实际config/default/personal/contract、模型和该input已冻结参数；不重建工作图。schema不兼容暂停，不暗改input，后续配置变化不追溯污染执行／兼容候选。

基础发送字段固定为record_type、observation_date、start_time、end_time、adult_count、child_count、age_years、subjects、environment，另含全部已关联照片／顺序／说明／工作图hash。学校／班级／观察者文字、term_id/term_snapshot及内部record/profile ID不发送、不算正文依赖，身份／来源隔离仍检查。完整生成另含已有四栏（可全空），重写按E07矩阵，不为简化hash去掉实际发送正文。执行器另加固定协议、实际提示词及模型；标准content文本／image_url data URL序列与既有凭据通道保持。

2026-10-25独立核对官方资料：[DeepSeek图像理解](https://api-docs.deepseek.com/zh-cn/guides/vision/)给出48MiB请求、32MiB内联图及最多600图；[MiMo图像理解](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/multimodal-understanding/image-understanding)给出Base64字符串50MB等约束，未给可直接当应用额度的固定图数。格式／型号按各适配器检查。公开事实不能证明当前账号、应用兼容或真实质量通过。

视觉帧单独版本化并由claim合同授权；保留旧text消息、1MiB保护、现有HTTPS/目标校验、密钥脱敏及dispatch标记。逐层预检原图→实际工作图字节→Base64精确长度`4*ceil(n/3)`→UTF8文字/JSON/data URL→完整请求／IPC帧；同时校验供应商图数、单图、上下文。不得只把旧常量全局调大。

2026-10-27本片参数核定：独立`chat_completions_vision_v1`，小header先核来源／任务／schema／contract／图数与实际body帧长度，再接视觉大帧；两帧合计36MiB，完整HTTP40MiB（body另预留8192字节头部）、最多600图、attempt180秒，连接仍10秒。旧text保持1MiB／120秒。预检以4096字节认证头和保守deadline计完整帧，实际claim再次编码核对；工作图逐张有界读取与增量预算，不能先积累全部超限输入。

原256MiB组合候选实测失败，失败窗口保留。Codex核定1024MiB为本片父／worker／完整原图解码者组合验证阈值，独立600张真实JPEG及40MP原图完整`inspect_managed_asset`解码的保守峰值和为824500224字节；主请求及解码并发请求均成功，见[容量核查](../bootstrap/desktop-game-observation-ai-review.md)。该值不是运行时硬RSS、整应用或任意并发承诺，不改变E03图片策略。上下文准入按冻结工作图尺寸：DeepSeek每图保守1024 tokens、MiMo官方尺寸公式，加实际UTF-8文本字节上界和8192输出／协议预留，对照1000000上下文；这是保守估算，不是实际token或费用预算，不静默减图。

内部input schema v1与`observation_wire_v1`分别冻结：业务发送投影／dependency hash与内部缺项／warnings／派生引用及参数分开保存，不将旧登记bundle schema冒称完全等于wire。claim取固定input照片引用；旧bundle字面值保持。dispatch前失败不记已发送；发送标记后崩溃／超时维持`outcome_unknown`，不自动重放。恢复／导出／重开不发AI。既有重试、取消和关闭不能误称撤回供应商请求。

## 8. E07：提示词、输出、候选与采用

两类观察bundle与输出schema独立版本化，prompt默认协议与照片简短说明分层，不增加完整提示词编辑器。执行固定config/default/personal/contract版本；后续配置或个人指导修改不否定已按旧版本完成的兼容候选。

完整输出恰为四栏，评价固定五领域；单栏重写只输出目标栏，评价作为一个含五领域的完整目标。允许情境对话／动作衔接，不能造精确分钟／时长或未提供完整新事件；无法对应多人姓名时写共同情境并提示补充，不猜姓名动作。不把AI补写再当作已核实证据。

候选持久化内容及hash、执行来源、schema、各输出hash、补写提示／定位。片段以目标/领域、文本偏移和匹配hash定位；越界／不匹配时降级总体提示，不把坏定位当正文失败，不把提示拼进采用或Word。候选区总体提示并可展开片段，无逐句确认。

本片审核metadata v1与candidate总hash／目标hash绑定，持久记录在保留前缀`cr:<candidate_id>`的AI operation；提取最多64片段、每片段200字符、片段JSON64KiB预算，超额保留完整正文并标记截断，读取时重新核偏移／目标／领域／hash。这些参数只限制审核定位，不截短正文，不扩大教师确认步骤。

| 任务／目标 | 实际发送的正文依赖（资料／环境／照片另计） |
| --- | --- |
| 四栏生成 | 原有四栏全部；逐目标基线及各栏作为上下文的hash |
| 重写观察目标 | 当前目标作为rewrite source；观察记录作上下文 |
| 重写观察记录 | 当前记录作为rewrite source；观察目标作上下文 |
| 重写评价分析 | 当前评价作为rewrite source；观察目标、观察记录作上下文 |
| 重写支持策略 | 当前策略作为rewrite source；观察目标、观察记录、评价分析作上下文 |

采用检查profile/record/source、input、合同兼容、资料/照片及实际正文依赖、各目标基线。任一实际依赖手改／他候选改动产生`SOURCE_CHANGED`，明确复核或重新生成，不静默通过；不要用整份draft revision一变就让所有候选失效。

采用preview返回一次性token，绑定candidate/hash、profile/record、targets、当前实际依赖／目标／draft hash、source_state、差异及期限。正常采用不多审批、不要求review_decision；来源变化明确展示当前差异后，提交adopt_reviewed决定并绑定预览／fingerprint，或取消／重新生成；不用裸bool绕过，坏图／不兼容合同不能复核覆盖。晚到编辑／候选／目标变化失效，无变重复不造节点，回包丢失先读回执而非已消费token。详见[Contract§6.3](../modules/game-observations.md#63-候选与采用)。

**同候选部分采用例外必须有账本证据：** 先采用该候选目标，当前值仍等于该输出且provenance证实，可在其余栏上下文比较中作为受信替换。因此可先目标再评价。人工/其他候选改成相同字样不能仅凭文本相等冒充本候选已采用。已采用目标不重复覆写，目标被手改亦不得晚到覆盖。整份／多目标一次采用在单事务写draft/照片不变/投影、应留版本、provenance和回执；不产生半份采用。重写后展示片段属于新候选，不串旧结果。

采用token内部上限64个／TTL600秒；原子reservation先于写入，事务进入／写入失败释放，提交后消费。观察域强回执先于token／材料／当前配置，提交后崩溃重开按同fingerprint回放，不重发AI。事务外核冻结及当前照片并集，写锁内刷新并核完整candidate/input绑定和材料身份。`changed`与`history_created`分别判断：draft变化才增revision，最终aggregate相对最近保留节点有变才留history，无首节点则首次留节点；auto后的待保留内容即使已等于候选也须留节点。无变采用仍记provenance／operation，同candidate/version只合并新目标证据；已采用目标经手改／auto／恢复／他候选改动后，旧候选不能因最近历史还等于旧输出而迟到覆写。

## 9. E08：整份历史恢复

流程固定：settle/完成导入→成功保存UI现稿并留下应留节点→预览历史→明确日期归属决定→提交恢复。保存失败／未知结果不进入预览；不能在恢复事务内插一个pre_restore节点冒充已保护UI。取消预览不再写业务内容。

预览绑定`profile/record/source_version/source_hash/base_draft_revision/base_draft_hash`、历史照片hash、有效学期快照与`effective_payload_hash`、request id及期限。`source_version`始终历史序号，不是draft revision。材料真实hash/解码验证在事务外，固定不可变文件与manifest；锁内复核身份／文件存在及大小等短检查，发现改变拒绝，不在写锁里解码多图。

有效恢复资料=完整历史canonical payload＋历史照片／顺序／说明，只按明确term decision覆盖归属／快照。提交先匹配主operation回执，无回执时在短事务再核token／base revision／source及effective hash／材料／学期；有变追加version/photos、替换draft/photos并revision+1，同步投影及两个计数；写operations主回执、关联restore细节并消费token。无变返回unchanged，不增draft revision或history。记录ID／创建者／创建时间及档案／班级／学期配置不改；恢复完全不依赖AI配置、候选、执行器或网络。

同request id同fingerprint读回原结果，异内容拒绝；响应丢失不再追加版本。晚到编辑用旧expected revision失败；先发生新编辑则预览失效。损坏／缺失历史拒绝，不拿当前资料补洞。恢复不改在途AI任务、不重跑、不自动采用，迟到候选仍经E07来源核对。

本片已核定并验证：preview TTL为15分钟内部参数，不是历史保留期；token只存摘要。既有term_snapshot_hash列存有效snapshot、明确term_decision／selected_term_id与源／当前／所选学期实时配置上下文的绑定摘要，未归属时仍绑定决定。配置使原方案无效时重新选择／预览，历史原snapshot不自动重填。真实hash／解码复用E03受管句柄及串行解码锁，最终写锁内只做严格布局／父目录／文件身份短检查。完整证据见本片独立核查。

## 10. E09：入口、离开与更新

工作台接实际列表／编辑视图，编辑页复用`EditorBridge`的identity/isDirty/settle/saveCurrent及现有`LeaveCoordinator`，覆盖切记录／学期、返回、设置、关窗和安装更新退出。未采用候选可保留，不强迫采用才能离开。导入、恢复、导出等真实在途写操作有明确busy状态，结束后重新核对epoch；失败留页。

宿主继续现有close代次、`complete_close`、`busy_probe`、任务快照及更新握手；通用执行器统计两类任务，日计划页面查询仍限定旧来源。原生另存为期间协调关闭，不绕过宿主直接销毁窗口，不把旧详情／保存响应写回新页。

### 10.1 E09／E10接续范围（2026-10-27，已授权实施）

E06／E07已在644ed68提交推送，接续计划已在62f1fc6提交。用户现明确授权开始E09／E10本机API、观察编辑及查阅列表，由原OpenCode使用Go套餐DeepSeek V4.1 Flash max实施，Codex独立审核并交回修复直至通过，最后由OpenCode提交推送。本片先推进创建／编辑／查阅部分；E10批选／手调排序跟E11真实导出接通时一起完成，不提前宣布完整E10通过。

建议实施顺序：

1. **先补受保护本机API。** 将E12既定范围中支撑页面的观察创建／列表／draft／保存、材料导入及受控读取、历史／恢复／回执、AI任务／候选／采用接口前置接通；DOCX导出、export_id及原生另存为仍留E11／E12。沿用现有session／Origin／Host与错误模型，profile由服务端确定；严格适配已有服务返回值，不另起业务状态机，不让前端传路径／任意URL，不放宽旧daily响应。
2. **先形成手工创建、编辑、保存与重新打开闭环，再接材料／候选／历史。** 工作台新增观察入口，三种类型、本份资料、四栏与固定五领域均按产品C1–C33；不增加必填内部标题。复用EditorBridge／LeaveCoordinator，但观察identity须区分模块、record及编辑代次，切记录／学期、返回、设置、关窗与更新退出都先settle和成功保存，失败或未知结果留页。保留未采用候选不能套用日计划的candidate阻塞离开规则；不强迫采用／取消候选才能离开。
3. **按真实当前稿接通材料、AI与整份恢复。** 先保存UI编辑，再用服务端revision/hash发起明确操作；采用按当前预览与明确targets提交，来源变化按已核定review_decision流程处理；恢复先保护当前稿再预览／整份恢复。导入、保存、恢复及采用的在途状态、丢回包查询、旧响应隔离必须覆盖；AI未配置或失败仍能手工编辑／保存。照片读取走认证二进制请求及受控Blob显示，不能为img标签免除会话保护；按需有界加载并回收对象URL，不一次常驻600张原图，不改600图上限或静默漏图。
4. **完成E10可用查阅列表。** 日期范围、学期／未归属、类型、姓名和分页使用服务端投影；同日多份以稳定ID区分，旧学期可查改，切筛选不改归属，旧列表／详情响应不回写新选择。批选、跨页明确选集、手动排序与导出确认仍保留原设计，待E11能实际消费选集时一起交付，不留无可执行用途的导出按钮或假成功路径。

接入核对依据：现有backend/app/local/app.py接入本机路由；frontend/src/d1/App.vue注册EditorBridge，d1/leave.ts拥有共享离开协调，d1/views/WorkbenchView.vue已有请求代次保护，d1/client.ts提供本机客户端。日计划EditorView.vue只作已核定机制的复用参考，不能整页复制其候选阻塞流程。未来实现须明确观察与daily两类任务查询／全局关闭统计的边界，保持旧日计划、设置和更新行为。

验证先覆盖真实本机HTTP／会话保护、无AI手工闭环、照片与候选／恢复闭环，再覆盖编辑期间切换、IME settle、旧响应、保存丢回包、关窗／更新及旧daily回归；视觉和教师体验另以当前Windows 11实际开发窗口逐项记录，不以服务层718项或静态页面代替。沿用原OpenCode会话与当前分支，完成后停写待Codex独立核查，通过后由OpenCode正常提交推送。本轮不运行应用真实AI、不构建冻结包或发行，不新增依赖、Skill／MCP或修改ARCHITECTURE.md。当前授权与操作入口见[当前任务](../tasks/current.md)。

本轮规划核对尝试codebase-memory的项目、状态及10路径coverage，均Transport closed；已按现有规格及上述文件定向回读核对，不据此宣称完整影响分析，也未安装或调整工具。Git前置核对工作区干净、HEAD与origin均644ed68；本轮新增变更仅为下一步计划文档，由用户明确委托原OpenCode执行正常提交／推送。

2026-10-28实施收口：本节限定部分由原会话／build／Go套餐DeepSeek V4.1 Flash max实施及回修，Codex独立审核通过，R01–R15关闭，见[最终证据](../bootstrap/desktop-game-observation-pages-review.md#6-最终独立结论本片限定工程核查通过)。页票据与busy序号、ready资格先于就绪副作用的协议已归并[宿主握手规格 §11.4](desktop-manual-daily-plan.md)；旧daily任务响应固定来源，观察查询使用独立端点。完整E10及E11／E12导出交付不在本片通过范围。用户已授权最后由原OpenCode正常提交推送，之后停在本片；本片应用真实AI调用0次。

## 11. E10：列表、同日多份与选择

`GET /api/observations`按日期范围／term／未归属／类型／姓名query分页；当前投影显示日期、时段、类型、重点姓名、创建顺序等以区分同日多份。记录opaque ID独立，创建request id幂等，不以相同日期/姓名/类型覆盖。

旧学期按存储term查，未归属可查改导出；切筛选不改归属，列表迟到响应按请求序号拒绝。跨页勾选维护明确ID集合，导出清单显示实际记录，不能隐式全选或漏页。合并默认日期升序、空日期末尾；同日起始时间升序、空时段当日末尾；同值创建先后再稳定ID，允许手动排序。不新增内部必填标题／31份限制／班级切换。

## 12. E11：三模板及固定导出

先保存本次编辑，再建立固定draft revision/hash/payload/照片manifest的snapshot，不只读最近history；含有序record集、资料／导出派生引用及hash、完整缺项事实／确认上下文、模板／渲染／参数版本、hash／期限和profile/launch/session_scope_hash。创建导出在短事务复核选集／顺序／各draft/hash／缺项事实，变化重新预览；物化后仅按固定快照生成，不回读当前稿混版本。空记录／坏图阻止整次、不静默跳过；缺项可确认留空、保留五领域，生成／原生保存不占长事务、不触发AI。

标题为表外`{园所}游戏观察记录（公共/室内/户外）`，三选一原模板后缀，园所空不放样例占位。A4纵向、原页边距／六列网格及8行：

| 行 | 原标签与值，按六个网格位置 |
| --- | --- |
| 1 | 1班级、2值；3日期、4值；5起止时间、6值 |
| 2 | 1成人数目、2值；3儿童数目、4值；5观察者、6值 |
| 3 | 1幼儿姓名；2–4姓名值合并`gridSpan=3`；5幼儿年龄、6统一年龄 |
| 4 | 1观察环境；2–6值合并`gridSpan=5` |
| 5 | 1观察目标；2–6正文值合并`gridSpan=5` |
| 6 | 1观察记录；2–6正文后全部照片合并`gridSpan=5` |
| 7 | 1评价分析；2–6固定五领域正文合并`gridSpan=5` |
| 8 | 1支持策略；2–6正文值合并`gridSpan=5` |

固定标签保留原字样与模板样式；标题宋体16磅加粗居中，基本资料含环境11磅，四栏**正文值**12磅。允许固定标签11磅与正文值12磅并存。多姓名按保存顺序顿号连接；空值不补猜。标题长时自然换行，行高最小值不设exact，不强制整行不跨页；`keepNext`不能当`cantSplit`，正文自然分页。

第6行正文后，每个图片组段落1或2个`wp:inline`，最多两张并排，单张居中，按保存顺序等比不裁切，按可用页高/宽度缩放；无`wp:anchor`浮动遮字、不新增外部业务行、不打印caption。每份从新页开始，份内自然分页，无额外空白末页；XML合规不能代替真实Word逐页检查。

单份默认`日期或未填日期＋类型观察记录＋重点姓名.docx`；合并`游戏观察记录＋有效日期范围＋份数.docx`，缺日期标明含未填日期，全无日期用未填日期。展示名超长／非法文件字符仅在建议文件名转义并截短加稳定后缀，正文姓名不变；同名由原生另存为明确选择，不静默覆盖。教师可改文件名。生成失败、取消、文件占用/失败、成功分开报告。

## 13. E12：本机材料及宿主交付

沿用本机session/Origin/Host与既有请求保护。观察新增创建／列表／draft／save、材料multipart导入及按record/asset受控读取、历史preview/restore/receipt、AI候选/采用、export preview/create/读取接口；不启动删除／回收站能力。页面只传opaque IDs，不传磁盘路径、任意URL或可扩大根目录的文件名。

受管根解析后检查路径边界，拒绝遍历、链接/junction/越界硬链接、ADS/设备名/尾点等，实际Windows重开和竞态需验证。材料只用于教师明确AI操作，不上传图床/遥测。日志仅ID/hash/状态/错误码/耗时/大小，不含儿童姓名、照片/Base64、正文/提示词、密钥或真实路径。

观察DOCX在后端受管临时目录完成文件／manifest后返回不可猜export_id；宿主save_observation_export(export_id,filename)仅从固定本机端点按会话取产物、流式原子另存为。token绑定profile/launch/session scope、固定snapshot／选集hash、期限／状态；snapshot_id不是读取凭证，查询仍验会话及归属，不返回任意路径／URL。宿主实际IO为保存结果来源，经固定API向后端报告，宿主不直连SQLite；同token同filename指纹只读原结果／在途，异指纹拒绝，不重复开对话框。saved/cancelled/failed/indeterminate分开，生成／下载完成不等于saved，未知不自动再保存。

成功／取消／失败／过期释放本尝试临时DOCX，保护正被读取产物，流结束／明确失败后释放；有效snapshot按期限保留供教师明确新token重试，过期重新预览。只清临时对象，不删业务材料及历史/input/派生引用，不调用AI。重开不复用未知已消费token，不宣称外部保存恰好一次；字段及受限结果查询见[Contract§7](../modules/game-observations.md#7-导出与-word)。

新通道须核定文件大小、分块、超时、磁盘和关闭协同并真实宿主验证。旧日计划`save_docx`及30MiB上限不变；不能为图片整体放宽旧桥接Base64入口。

## 14. E13：Contract与依赖准入

2026-10-26原会话已提交并修订，Codex独立核定后归并[观察主Contract](../modules/game-observations.md)及[身份／班级](../modules/identity-and-class.md)、[AI](../modules/ai-service.md)、[提示词](../modules/prompts.md)、[Word](../modules/word-export.md)、[审计](../modules/audit-log.md)五扩展，明确字段／表／接口／error／幂等／权威／资源边界。过程及最终修订见[E13记录](../bootstrap/desktop-game-observation-contract-review.md)；门槛仅设计完成，未实施／执行应用验证，不自动派发下一片。

观察业务拥有记录、材料、候选业务意义与采用决定；AI基础设施拥有配置、执行、格式校验和状态，不取得业务确认权；Word模块只按固定观察投影渲染。保持Vue→本机FastAPI→SQLite/受管文件与既有worker方向。此设计预计不需ADR；若改一级栈、所有权、数据权威或通信机制，先ADR草案，不能Feature直接改`ARCHITECTURE.md`。

图像库Pillow==13.0.0已加入backend业务声明、uv.lock和桌面统一锁；原26个业务包及桌面旧46包版本／锁hash集合不变。当前CPython3.14.7 Windows x64标准GIL的新建venv已按统一hash锁离线安装47包、通过依赖检查和31项材料测试；JPEG／PNG／WebP／GIF／BMP与LCMS能力已验证，MIT-CMU元数据见[PyPI](https://pypi.org/project/pillow/13.0.0/)及[E03核查](../bootstrap/desktop-game-observation-assets-review.md)。PyInstaller插件／许可收集、模板资源和冻结新包仍后续另验；不安装Skill／MCP，不引入图床或新服务。

## 15. E14：验收矩阵与分阶段交付

以下是**未来通过条件**。产品A/R全文保持在[完整规格§7–§8](desktop-game-observation.md#7-验收条件与证据矩阵)，不能以方案核定代替任何A项通过。

| 工程项 | 对应A验收 | 对应R冲突 | 必须补齐的运行证据 |
| --- | --- | --- | --- |
| E01 | A01–A03、A07、A15 | R01–R05 | 字段/五领域、三门槛、矛盾不改写、空骨架 |
| E02 | A04、A12、A21–A22 | R06–R07、R09–R10、R14 | 完整FK链/NULL绕过、旧行hash、回填/失败回滚、两次guard后种子幂等 |
| E03 | A06、A08、A12、A19、A21 | R04、R10 | 合成各格式/方向/损坏/极限、磁盘满、中断、文件-DB失败、历史引用、RSS/并发 |
| E04 | A01、A05、A13 | R06–R08 | 任意日期、空日期显式学期、旧范围缩小、跨学期取消/恢复决定 |
| E05 | A04、A11–A12、A16 | R09 | 自动后手动仍留节点、无变化去重、冲突/丢回包/最后IME输入 |
| E06 | A07–A08、A14、A21–A22 | R02–R04、R14 | 假供应商精确图文/字节/600边界、IPC合同、发送前后故障、未知不重放、旧文本防护 |
| E07 | A07、A09–A10、A14 | R02–R05、R12、R14 | 四栏输入/输出、单栏依赖、同候选连用、手改/他候选过期、坏片段降级、原子采用 |
| E08 | A06、A11–A14 | R07–R10 | 全资料/照片恢复、先保护现稿、归属覆盖、坏历史、幂等/晚到编辑/在途结果 |
| E09 | A01、A11、A14、A20、A22 | R09、R11 | WebView2真实入口、切页/关窗/更新、原生对话框及busy协调 |
| E10 | A04–A05、A17 | R06–R07、R11 | 同日多份/未归属、跨页选集、手调/稳定排序、旧响应隔离 |
| E11 | A03、A10、A15–A20 | R01、R05、R11–R13 | 三模板8行/字体、固定快照/缺项确认、0/1/2/3/多图、长文与混合Word逐页 |
| E12 | A06、A16、A20–A22 | R10–R11、R14 | 来源/路径/链接拒绝、token隔离/消费/过期、保存取消失败、诊断脱敏 |
| E13 | A21–A22及全部职责前提 | R01–R14 | 六份Contract设计已核定；依赖/许可/资源实证及未来ADR边界仍须核对 |
| E14 | A01–A22 | R01–R14 | 合成、组件、真实窗口、Word、后续包及真实AI各有独立结果，不互相替代 |

失败注入至少包括：重建各表中断、原数据异常、seed前后失败、错profile/record/task/input/candidate链、NULL CHECK绕过、文件落盘后DB失败、原图/工作图缺失损坏、并发排序、导入磁盘满、采用/恢复响应丢失与同ID异请求、先目标后评价、策略依赖的过程被改、恢复时term变化、未知AI重开、导出确认后变更、宿主占用/取消、超大图请求/IPC/RSS和旧日计划回归。

完整后续矩阵命令示例（不作本轮执行清单；本轮实际命令、隔离目录、真实调用与结果见核查报告；导出专项由后续E11补充）：

```powershell
# cwd: C:/Users/yw980/code/kindergarten-manager-next/backend
../desktop/.venv-d1/Scripts/python.exe -m pytest tests/local/test_migrations.py tests/local/test_d2_schema.py tests/local/test_d2_migration_safety.py tests/local/test_d3_history.py -q
../desktop/.venv-d1/Scripts/python.exe -m pytest tests/local/test_observation_models.py tests/local/test_observation_assets.py tests/local/test_observation_ai.py tests/local/test_observation_history.py tests/local/test_observation_ai_contracts.py tests/local/test_observation_prompt_contracts.py -q
../desktop/.venv-d1/Scripts/python.exe -m pytest tests/local -q
# cwd: C:/Users/yw980/code/kindergarten-manager-next
desktop/.venv-d1/Scripts/python.exe -m pytest desktop/tests -q
# cwd: C:/Users/yw980/code/kindergarten-manager-next/frontend
npm run typecheck
npm run test:d1
```

真实WebView2验证需记录源码／进程／数据身份，Word页面必须来自新版实际产品导出，记录Windows／Word／字体及每份起始页；XML／PNG／PDF仅辅助。后续构建／包验证另按授权，检查模板、PIL插件／许可、前端及入口同源与冷启动。前片E06／E07已按当时授权完成独立合成资料DeepSeek真实闭环；当前页面片只使用合成任务／候选，不调用应用真实AI。复杂照片／多人对应／补写质量及教师体验仍待后续，假响应不能替代真实效果。

目前无新增待用户决定的主流程问题。E03材料、E05／E08历史及E06／E07服务层结果保持；页面／IME／离开及宿主关闭协调按本片限定范围通过，证据见[本片核查](../bootstrap/desktop-game-observation-pages-review.md)。Word／原生另存为、冻结包、完整A01–A22与教师产品未整体验收。首期保留成功staging空目录及未引用孤儿，不递归自动清理；维护须保护历史／input引用并另审。Win10、WPS、干净机器、其他DPI／显示器及D2／D3未验保持。自动验证使用独立合成资料；原业务库／凭据／OneDrive原件／旧包保持。本轮Git授权覆盖E09／E10限定片审核通过后由原OpenCode正常提交推送，停在本片。
