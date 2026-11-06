# 桌面周计划工程设计与实施合同

本文件保留 Q1–Q4 已执行的接口和分工。开工文档提交 d6de14c，业务源码基线 2a469489。首片结果见[实施核查](../bootstrap/desktop-weekly-plan-review.md)与[另机收口](../bootstrap/desktop-weekly-target-test-closeout.md)。

§8／§11 的文件责任仅适用于当时实施。Q5/Q6 另见[工程合同](desktop-weekly-ai-engineering.md)、[验证矩阵](desktop-weekly-ai-validation.md)和[Q5/Q6 目标机核查](../bootstrap/desktop-weekly-ai-windows11-target-review.md)。

## 1. 基线、范围与准入

沿 `codex/desktop-v2-foundation`，原业务源码基线 `2a4694893a083e32ba6203bfee6dbd83f890f02e`；本轮开工HEAD为 `d6de14cb85040e5e68e3eab36b6d34fd5c927f8b`，开工前迁移head为 `20261025_0006_local_game_observations`。当前实施状态见核查；既有规划／规格文档保留整合。各阶段核对实际head、文件变化及在途会话，不能reset或沿旧指纹自报同源。

首片落实手工周计划闭环、Q1–Q4与配套回归，另按用户新增[明暗模式](desktop-appearance.md)并行交付；Q5–Q6 是后续有效产品规则，本片不注册周 AI 任务、不做真调用、不新增材料候选入口。材料保持 null，不绕开 P2／P3。继续单本地档案、SQLite／Alembic、本机 FastAPI、Vue／Element Plus 和既有宿主；无新一级技术栈或中间件，不修改 ARCHITECTURE.md。

## 2. 数据模型与迁移

### 2.1 表头配置

主题持久化同时在LocalSettings加入ui_theme／ui_theme_version，由A写入同一个0007；外观改动不增config_version，详细合同以明暗模式规格为准，七张新表数量不变。

`LocalClass` 新增 `header_teacher_names`：有序 JSON 字符串列表，NOT NULL、默认 `[]`；`caregiver_name`：可空字符串80，空白归 null。逐项去首尾空白、非空、最多80字符，保留同名项及顺序，不把姓名当身份或从个人档案自动填充。工程输入上限100项且规范 JSON UTF-8 ≤32KiB，超限明确拒绝、不截断；不是班级教师人数业务规则。园所120、班名80、年级枚举沿现有值。

扩现有 `current_class` 配置变更的两个可选字段及 DTO：遗漏保持原值，显式 []／null 清空。旧客户端和五种既有变更语义不变。所有修改走现有 preview/apply、request receipt、config_version；只改名单／保育员不新增日历或游戏修订，不改已有周表头。SettingsView 提供维护；创建周计划前展示实际快照及空项，明确提醒创建后不会被补录回填，允许继续。

### 2.2 首片七张新表（逻辑名固定，SQLAlchemy 类前缀 LocalWeekly）

| 表 | 必需字段与约束 |
| --- | --- |
| `local_weekly_plans` | id；profile_id FK；class_id FK；term_id FK；不可变 `week_anchor_date`（周一）、`week_number_snapshot`、创建学期起止／calendar_revision／header_json；current_draft_id/version 非空；current_confirmed_id/version 同空或同非空；created_at/updated_at。有效唯一 `(class_id,term_id,week_anchor_date)`；首片无删除入口，不加假删除状态。 |
| `local_weekly_plan_contents` | id、weekly_plan_id FK、version正整数、schema_version=1、content_json、content_hash(hex64)、editor_profile_id、created_at；同计划版本唯一、同计划id/version复合唯一，追加写。 |
| `local_weekly_plan_confirmations` | id、weekly_plan_id、version、draft_id/draft_version、schema_version=1、snapshot_json/hash、facts_json、note可空、confirmed_by/time；复合 FK 指同一计划确切草稿；确认序号唯一、同计划id/version复合唯一，追加写。 |
| `local_weekly_plan_operations` | id、profile_id、request_id≤36、weekly_plan_id、action=create/save/refresh/confirm/export_create/export_retry、input_fingerprint、result_draft_id/version、result_confirmed_id/version、result_snapshot_id/token_id、导出用launch_id/session_scope_hash、最小result_json、created_at；`UNIQUE(profile_id,request_id)`。业务动作必须有计划及相应版本结果；导出范围动作可无单个计划，必须有传输结果。无假 pending 业务提交。 |
| `local_weekly_export_snapshots` | id、profile_id、launch_id、session_scope_hash、manifest_json/hash、created_at、expires_at；snapshot ID 不是读取凭据。 |
| `local_weekly_export_tokens` | id、snapshot_id、profile_id、token_hash UNIQUE、expires_at、consumed_at可空、parent_attempt_id可空、created_at；同一失败／取消attempt最多产生一个retry token（parent非空时唯一），不持久化明文export_id。 |
| `local_weekly_export_attempts` | id、profile_id、snapshot_id、token_id、export_id_hash、filename_fingerprint、status、result_hash、byte_size非负、started_at/ended_at；`UNIQUE(profile_id,export_id_hash)`；状态 in_progress/saved/cancelled/failed/indeterminate。 |

计划指针采用与既有 SQLite 模式一致的**同计划复合延迟外键**；初始计划和首稿在同一事务成环插入后提交，不以 nullable 指针绕过提交时完整性。confirmed 指针对应确认表，确认表再钉住其原草稿。所有版本／week_number_snapshot为正整数；每对receipt结果必须全空或全非空CHECK，不能借SQLite任一NULL就跳过复合FK；result_json中的ID／版本必须等于结果列。snapshot增加(id,profile_id)唯一键，token／attempt以复合FK绑定同profile的snapshot；attempt同时绑定同snapshot/profile的token，retry token绑定同scope的parent attempt；operations传输结果也须同profile/snapshot。A按这些关系声明相应复合唯一键。所有受信JSON有版本、严格键、规范hash；时间和实际长度类型按既有约束处理。单一SQL FK不覆盖的JSON引用须服务端／备份验证补齐。

建议迁移文件 `backend/migrations_local/versions/20261101_0007_local_weekly_plans.py`，revision=`20261101_0007_local_weekly`，down_revision=`20261025_0006_local_game_observations`。若开工迁移 head 已变化，先交 Codex 重新核定，不做第二 head 或 stamp。迁移只加列／表，新列默认空、周表空；不改旧行旧列值、不补造旧确认、不增加既有 config_version／审计／AI 行。保留 d1_digest 冷升级守卫；旧字段／行集摘要需一致。旧程序见新 revision 应拒绝，不能 downgrade／清库。

## 3. 内容、来源与事实合同

### 3.1 草稿 schema_version=1

```text
theme: string（可空）
deterministic: 日期升序；每日期一项
  date, day_state(teaching/rest/outside_term), source_state(saved/no_plan/none_required), source{daily_plan_id,content_id,content_version,
       morning_talk_topic,group_activity_theme} | null
  override{morning_talk_topic:null|string,group_activity_theme:null|string}
  effective{morning_talk_topic:string,group_activity_theme:string}（服务端派生）
outdoor_game_slots: collective_1 / collective_2 / free_choice_1（每项可空）
  daily_plan: plan/content/version/section/group/game + 名称及整组目标指导快照
  manual: manual_item_id + 名称及目标指导；全部日引用为空
focus_area: null 或日来源 + context_kind/area/name/objectives/guidance/support_strategy
weekly_columns: key_week_focus/environment_setup/habit_culture/home_cooperation
materials: null；首片不接受非空材料或 AI kind
source_manifest: 服务端拥有的实际来源／相关配置／日历依据及 hash
calendar_basis: 固定week_anchor_date、实际term_start/end、calendar_revision_id、该周逐日有效日历
```

来源值、effective、历史来源快照、真实 profile、最新标识及事实均不可由客户端直接写。PATCH 白名单仅 theme、日期人工覆盖、户外选择／手工条目、重点区域选择和四栏。首片材料始终 null，不接收材料依据。null 人工覆盖表示跟随日值；显式 `""` 表示留空。手工填写可覆盖本人值，也可直接补搭班日，界面显示人工覆盖，不伪造另一位教师日记录。

B 内容模块保持纯函数，不导入 Session/models/runtime；输入为 A 已授权读取的快照、相关日历和现有稿，输出规范内容／hash／facts／差异。A 独占来源授权和事务，不能让纯 helper 再读另一轮数据库。hash 用规范 JSON（固定空值、键排序、紧凑分隔、UTF-8），数组顺序有语义。

技术正文限额复用旧周 content 校验中与当前字段一致的限额，经 A/B 门禁逐项列明；新 DTO 总正文先用既有1MiB序列化防护，超限整体拒绝、不截断。不得新增“必须5条”等业务额度。材料后片另定字段合同，不在本片预留假任务／候选表。

### 3.2 来源读取与更新

来源池按固定 week_anchor_date～+6日、存储 term/class/creator 及归属读取，不按可能已改变的 daily.week_number 或当前 term.start_date 反推；来源是已保存采用内容。新建先查稳定唯一键，已有记录先打开，再判断当前新建资格。新周须与所选学期相交，教学日／假期／未覆盖日历按现有持久日历处理，不猜测。已有周不因学期收缩被拒绝访问。

选取候选携带 plan/group/game 及预览时 content_id/version/hash 作为**预期上下文**；保存时服务端核当前来源仍相同，再物化全文。若变了返回409，不把用户未看过的新来源盖章。已有稿未改选的日引用则保留原 content/version/全文，不因普通保存自动更新。新手工条目可带客户端临时 key 供同次对应，真正 manual_item_id 由 A 分配并在成功响应返回；已有手工 ID 只可属于该计划，回执重放不得再生成 ID。

source_context_hash 覆盖本周完整本人来源集合及内容版本、相关游戏配置、实际日期／日历和被使用依据。发现新日计划也能改变上下文。表头名单更改或无关 config_version 变化不单独使游戏陈旧；创建用全局 config_version 防表头预览竞争，后续比较相关依赖。计划年龄基准用创建 grade 快照，不能因当前升班把旧周的年级或旧 Word 改掉。

calendar_basis创建时固定，普通保存不更新；明确刷新可把同一固定自然周内的新学期边界／有效日期纳入新稿，但不改变计划创建周锚点／显示周次和表头。确认同时保留创建上下文和该保存稿calendar_basis。日历变更后的预览必须列出上课／停课／学期外变化，保留原人工正文；列投影按所确认basis表达，不能偷偷重排到另一自然周。

### 3.3 刷新、确认与事实

refresh-preview 返回完整目标草稿及差异：能解析的具体 ref 刷到新版本；当前 group/game 消失的项保留旧**真实历史快照**并明确列为保留／缺失，绝不按同名换源。apply 钉住预览、旧稿与完整 source context，一次事务追加整个目标；期间任何依赖变更整笔409，不默默部分提交。人工覆盖、搭班手填、主题、四栏、材料不变。

确认预览固定确切保存稿、表头／日期／有效列、所有来源和缺项／陈旧事实；token hash绑定目标。日期／day_state／列必须来自该已存草稿的日历依据（或此前明确刷新后的依据），实时日历仅用于比较stale，不能在confirm偷偷替换。confirm在短写事务重读全部前提，变化后旧ack失效，即使缺项减少。确认快照复制header、创建学期／实际周、草稿日历列、最终内容、来源及事实，历史读取不能实时重新拼装。保留旧内容确认不刷新、不把旧源标新。

Q1 的缺项依据是教学日两个最终格；手填有效时不因本人日计划缺失追加内容缺项。源状态仍单列。Q4 空名单／保育员列 header missing；三个游戏、重点区域、主题、四栏、材料按产品列缺项。区分纯手工、旧来源、缺当前项；休息／学期外占位不伪造教学缺项。

## 4. API、事务与回执

新模块路由 `/api/weekly-plans`；A 注册到现有 local app，不接旧 weekly 路由。全部沿现有启动会话、Host／Origin 和本地 profile 检查，Pydantic extra=forbid，版本严格正整数，日期严格 ISO。下面为首片固定语义；错误走现有 LocalError 映射，新增码带 `WEEKLY_` 前缀。

响应直接返回对象，不再发明一层data envelope。固定DTO：`WeeklyPlanSummary={id,term_id,week_anchor_date,week_number_snapshot,header,current_draft_version,current_confirmed_version|null}`；`Draft={id,version,content_hash,content}`；`ConfirmationSummary={id,version,draft_version,snapshot_hash}`。详情为 `{plan,draft,confirmed|null,source_candidates,source_context_hash,facts:{missing,stale_sources,warnings}}`，列表为 `{items,next_cursor|null}`。来源候选必须含确切日版本／section/group/game及全文；事实每项带稳定code、field_path、实际旧／新引用，不能只发拼好的提示字符串。

写结果为 `{operation_id,request_id,status:'committed',weekly_plan_id,draft|null,confirmation|null,replayed}`，draft内容从回执指定的不可变版本读取，不读取后来最新稿；confirmation至少含确切id/version/draft_version/hash。回执DB只存结果标识，响应可按这些标识还原原内容。前端旧sequence或已换editor的回执不能覆盖现在的稿；需要当前head时另读详情，不能把最新详情称原提交结果。导出create/retry结果为 `{operation_id,request_id,generation_status:'generated',snapshot_id,manifest_hash,export_id,expires_at}`；原生保存状态另查attempt。跨launch／过期返回同一operation的 `generation_status:'transfer_expired'` 和结果标识，不含可用export_id。

| 接口 | 输入／返回要点 |
| --- | --- |
| POST `/create-preview` | term_id、周一日期；只读返回存在计划或创建 header/calendar/source 预览、缺项及 context token。 |
| POST `/` | request_id、term_id、week_anchor_date、expected_config_version、create context；201新建／200已有，已有不重播种来源。 |
| GET `/` | term_id、日期过滤、游标；默认50／最大200，返回草稿版本、确认版本、实际周／表头与分列事实。 |
| GET `/{id}` | 当前已存稿、确认摘要、只读候选／实时事实与 source context；无写副作用。 |
| PATCH `/{id}` | request_id、expected_draft_version、字段白名单；只存本次人工变更，不刷新、确认或发 AI。 |
| POST `/{id}/refresh-preview` | expected_draft_version；返回完整新目标、保留旧项、差异、context token。 |
| POST `/{id}/refresh-sources` | request_id、expected_draft_version、preview token；按整个目标原子追加稿。 |
| POST `/{id}/confirmation-preview` | expected_draft_version；返回确切目标／hash、facts、context token，不能读 live 表单。 |
| POST `/{id}/confirm` | request_id、expected_draft_version、context token、ack_missing/ack_stale、note可选；返回确切 confirmation_id/version/draft_version/hash。 |
| GET `/{id}/confirmations`、`/{id}/confirmations/{confirmation_id}` | 所属计划的历史确认清单／自包含正文，不替换成当前内容。 |
| GET `/operations/{request_id}` | 本 profile 已提交最小结果；未找到仅表示未查到，不能推断尚在处理的写入一定失败。静态路径注册在动态 id 前。 |

每次写先规范输入／校验结构，再 BEGIN IMMEDIATE 内读回执、归属、预期版本及来源前提，写业务版本／指针／回执／审计后一次 commit。网络／Word 不在该锁中。**同键同载荷优先回放旧提交结果**，再考虑过期版本和 token；同键异 action/target/body→409。回放旧提交 ID／版本，不取后来最新稿冒充原结果。审计 LocalOperationRecord 不足以替代请求唯一性和结果回执。

A另提供新 `weekly_plan_operations.py` 作为业务／导出共用的持久回执helper：调用者传入受信session/profile/action/规范指纹，helper不自行commit。D在导出元数据事务内使用同一规则；并发同请求即使锁外各自生成了临时DOCX，锁内也只提交一个结果，输者仅清自己的工作文件，返回胜者的确切结果，不发第二token。跨动作重用同request_id仍409。

preview token TTL10分钟，绑定 profile、launch/session、用途、对象／版本／source hash／目标 hash／facts hash；不能跨 create/refresh/confirm/export 使用，不带正文或密钥进日志。A 可新建 `weekly_plan_tokens.py` 按现有 HMAC 机制做独立 audience；不改密码或凭据方案。上下文丢失／变更返回409或明确过期，输入仍留页。

## 5. 页面、自动保存和确认状态机

新增周列表、周编辑、确认历史和导出对话框。C 使用独立 `weekly.ts`（DTO／client）与 `weekly-editor.ts`（正规化／dirty／异步投影）及现有 EditorBridge 形状；A 独占 App.vue、leave.ts、bridge.ts 和工作台／设置接线。

稳定编辑身份 `identity={weekly_plan_id,editor_epoch}`，**不能把 loaded_draft_version 放进 identity**：一次成功保存本来就会追加版本，若沿现有 leave 的保存前／后身份比较会误判为换页。loaded_draft_version 单独存基线，作为请求 expected version，保存后比对实际返回版本；每个请求另带递增 sequence，响应只更新自己的提交投影。提交后新输入仍 dirty，不用 `form=current_response` 清掉后续文字。日 source 值／只读候选／事实变化不单独制造 dirty；null 与明确空、数组顺序须保持语义。

导航 stable key 必须含周 ID／周锚点，不把两个不同周的切换当同一个 in-flight 动作。IME settle 后有修改→保存→核 identity/仍 clean 才离开；失败／版本冲突／不明留页。周 save／refresh／confirm／export 即使正文 clean 也产生 blockingDraft/busy 屏障，接入 close 最后复核及备份维护入口，不绕过已有日／观察保护。

**Q3 两条分支不可共用“导出前一律保存” helper：**

- 当前稿：settle→明确保存→核同一 identity 且仍 clean→预览返回的确切保存稿→教师明确确认→用返回的 confirmation ID/version/hash 导出。任一步新输入、切周或迟到响应，终止后续链并保留稿；不交旧版代替。
- 上一确认：先把选中的确认解析为确切 ID/version/hash，显示未含当前修改；**不保存、不清空 dirty 稿**，直接对该不可变确认做导出预览。没有旧确认时不展示可用旧版动作。

确认预览对象、导出选择对象和编辑表单必须独立。缺项/来源新旧/确认版本/进行中状态分列。首片没有周 AI 按钮，不以空控件宣称实现；后续按已确认三个明确操作接入。

## 6. Word 固定快照与受限宿主

### 6.1 导出身份与 API

独立 `/api/weekly-exports`，D 新 export API/service，A 注册 router。预览不调用观察的“准备导出自动存稿”流程。single 模式输入计划＋明确 confirmation ID 或 latest；latest／范围在预览时解析成具体清单，显示每份 ID/version/hash。range 按确认钉住的教学日与范围相交、整周去重／升序、最多8份；零教学日只单份，跨学期不合并同周号。

manifest schema_version=1 包含 profile、模式／范围、实际选集顺序、每份 plan/confirmation/draft版本／hash、完整 header／term bounds／anchor／week／date_range／columns／最终正文／missing 和比较时点 warnings。确认后改日历／新草稿／新确认**不能改变所选旧确认的内容或禁止明确的旧版导出**。不复用观察 `_binding_matches_locked` 的“当前草稿仍相同”条件；确认对象自身、选择或静态缺项变化才使上下文失效，实时新变化单列为时点提示，不偷换旧版本。

| 接口 | 合同 |
| --- | --- |
| POST `/preview` | 只读解析／物化确切确认清单，返回完整预览、静态 facts、warnings_as_of、export context。 |
| POST `/` | request_id＋context＋缺项ack；校验相同确认/选择/hash后从已物化数据生成完整DOCX（写锁外），再原子登记snapshot/token及export_create回执；失败不留可用token。 |
| GET `/{export_id}/content` | 会话／profile／launch/token 全校验后有界流式返回固定 DOCX，页面不能传自选 URL。 |
| POST `/{export_id}/attempts`，GET `/{export_id}/attempts/latest`，POST `/{export_id}/attempts/result` | 宿主在途／回执；同 token+filename幂等查询，异名冲突；HTTP生成或下载不代表已原生保存。 |
| POST `/snapshots/{snapshot_id}/retry` | request_id、old_export_id、attempt_id；锁内重查同profile/launch/snapshot且旧attempt为failed或cancelled，snapshot未过期，才登记唯一后继token及export_retry回执；in_progress/indeterminate不发新token。snapshot_id本身不授权。 |
| GET `/operations/{request_id}` | 返回本profile的确切已提交导出结果；同launch/scope且未失效可重放同一token，跨launch只返回已过期传输元数据，不能暗中重生成。静态路径先注册。 |

DOCX生成优先审查复用固定模板／纯mapper，以确认中冻结的 `week_anchor_date/date_range/columns` 为权威；不能仅把刷新后的term_start与旧week_number再喂给旧week_start_for，二者可能不再得到原自然周。adapter直接提供冻结列／日期，或验证计算确切等于固定anchor，否则拒绝，不用当前配置重算。原模板SHA保持产品记录，任何修改先列影响，不套用日计划格式。新生成器无需增加新依赖。锁外生成完成后，最终元数据事务还须核runtime未retire／未进入拒写维护、launch/scope及context仍有效，再登记结果；不让迟到生成发布新token。

### 6.2 原生协议与寿命

增加 `save_weekly_export({export_id,filename})`、`get_weekly_export_result({export_id,filename})`，独立固定路径。D 仅复用低层 loopback 校验、对话框与原子 stream writer，不能扩大已有 save_docx／观察入口。周通道独立工程上限128MiB、preview/snapshot/token TTL10分钟；旧30MiB base64及观察128MiB不变，超限拒绝整次，不减份或截断。

共享宿主 `_save_mutex`，计入 `_save_inflight`，调用前／原生对话框返回后均执行 `_native_io_refusal`。close/restore/retire／会话替换后迟到 IO 不得写文件；跨通道原生另存为串行。新 API 名和请求类型由 A 在 bridge.ts 声明并接 C，D 不改该共享 TS。

token明文只给受限请求，不存DB／日志。为解决create/retry响应丢失，export_id以私有launch HMAC密钥、独立audience、session scope hash、已提交snapshot_id/token_id/request_id确定性生成（base64url，≤128字符），DB仅存其SHA-256。不能把页面已知的启动会话token当HMAC密钥。同launch同请求重放从结果标识计算**同一个**export_id，并核token_hash；scope变更／过期只返回失效结果，不mint新token或再生成DOCX。该机制使用已有HMAC库，不引入新密码组件。

文件名仅单层合法basename，fingerprint绑定token和本次命名。查询只补回执，绝不发起新对话框或重写文件。in_progress返回在途；saved/cancelled/failed不重复写；indeterminate先查询／核实际文件，不能当安全重试。明确失败／取消重试才新token，过期重预览。retry按旧attempt唯一后继防并发双击；同request回放原结果，不同request重复针对同attempt返回409，不再建token。新token到期不晚于min(snapshot.expires_at,now+10分钟)，不能延长snapshot；后继再次失败才可针对那个新attempt明确重试。

临时文件放自有 `.weekly-export-work`，跟踪读取引用再释放；A 纳入备份排除、维护屏障和恢复／退出清理。恢复或新 launch 后旧 token一律失效，旧在途标 indeterminate，不恢复原生对话框。只能清本轮受信 work，不删业务正文、确认历史或原资料。

## 7. 备份、恢复与兼容

不因加表自动升级 `.kgmbackup` format1；源 schema revision 仍记录实际版本。先以**源 revision** 校验 canonical schema、manifest、源DB hash及资源，再只升级独立副本，后验当前业务结构。源 revision/hash 与升级后 revision/hash 分列，不拿升级后文件匹配原 sealed manifest。

检查全部周草稿及确认，不能只查 current 指针：严格 schema/hash，ID/版本/归属关系、最终值派生、真实历史日内容中相应 group/game 与完整文本匹配。旧日内容版本、当前游戏已移除或当前指针变化是合法陈旧；历史 content 根本不存在、跨计划／班级／学期、伪造同名／文本或错指针是损坏，应拒绝。历史确认不能要求等于实时日历／配置／当前稿。

新名单／保育员和七表进入快照／逻辑校验／测试夹具指纹；临时Word排除。导出持久元数据可随DB保留但不恢复执行权限；launch/scope失效，未决attempt变不明。首片只释放过期工作文件、使token失效，不删除被回执／attempt引用的持久snapshot/token等元数据。旧token_hash只能校验格式及关系，不伪称无私钥也可重算旧HMAC。0006合成库／备份向前升级后周表空、旧资料不变；007往返恢复保留全部稿／确认／来源／请求回执及保护包再恢复。新程序升级旧库、旧程序拒绝新库、恢复后新进程接续均要真验证，不能只比较表名。

全部历史export snapshot/token/attempt/operation也验同profile归属、hash、token与attempt关系、receipt成对结果及result_json一致性；不能只验活跃token，不能因旧scope失效而跳过结构校验。失效只影响执行权限，不把历史结构损坏当正常。

## 8. 责任、依赖与分片门槛

全部原生实施者固定 DeepSeek V4.1 Flash max，不 fork／另派子代理；你不是唯一写入者，不还原他方修改。下表是本轮派发合同，阶段放行由 Codex 核定。无归属文件先交 Codex 划定，不自己扩范围。

| 会话 | 唯一写入责任 |
| --- | --- |
| A 原 OpenCode | `backend/app/local/`内 models.py、schemas.py、api.py、app.py、config_service.py、profile_service.py、runtime.py、backup_validate.py、backup_snapshot.py、backup_fs.py、restore_service.py、restore_group.py、restore_recovery.py；新 appearance_service.py、weekly_plan_service.py、weekly_plan_sources.py、weekly_plan_tokens.py、weekly_plan_operations.py、weekly_plan_api.py；唯一上述0007迁移。`frontend/src/d1/`内 main.ts、App.vue、leave.ts、bridge.ts、client.ts、types.ts、views/WorkbenchView.vue、views/SettingsView.vue。`desktop/maintenance_host.py`、maintenance_lifecycle.py、build_e14.py、verify_e14_package.py、verify_e14_portable_archive.py；`.gitignore`。新 backend/tests/local/test_appearance.py、test_weekly_plan_service.py、test_weekly_plan_config.py、test_weekly_plan_backup.py；既有 backup_fixture_support.py、test_backup_fixture_support.py、test_backup_snapshot.py、test_restore_core.py、test_config.py及维护整合测试desktop/tests/test_maintenance_lifecycle.py、test_maintenance_host.py。现有文件仅在有实际影响时最小修改；七表均A声明，D不改models／迁移。最终Git整合归A。 |
| B 辅助 OpenCode | 新 `backend/app/local/weekly_plan_content.py`、`backend/tests/local/test_weekly_plan_content.py`：纯结构／派生／来源差异／facts／canonical hash；不读 DB，不改旧 services 同名模块或 A 文件。 |
| C Command Code | 新 `frontend/src/d1/` 下 weekly.ts、weekly-editor.ts、d1.weekly*.test.mjs；其 `views/` 下 WeeklyPlansView.vue、WeeklyPlanEditorView.vue、WeeklyHistoryPanel.vue、WeeklyExportDialog.vue；另拥有[明暗模式§4](desktop-appearance.md)的theme新文件和11个既有view的颜色样式，不改业务逻辑；不改App/main/Settings/Workbench/shared types／bridge。 |
| D Command Code | 新 `backend/app/local/weekly_plan_export_service.py`、`weekly_plan_export_api.py`、`backend/tests/local/test_weekly_plan_export.py`；`desktop/d1_host_api.py`、新 `desktop/tests/test_d1_weekly_export_host.py`；不改 A 的模型／迁移／router挂载／shared TS，不重构观察导出。 |

原生会话 A 续 `ses_ead8af71dffeJphI1NOWg4jZgI`，B 续 `ses_e72ecd5f9ffeYJaLRNypsdu5Pi`，均 build／`opencode-go/deepseek-v4.1-flash#max`。C 续 `8cf528de-8773-4a06-9cc5-31e96fab515f`，D 续 `16cf76b5-ea0b-47f5-bc94-26147c9d3689`，均 `deepseek/deepseek-v4.1-flash`／effort max。会话不可用先交实际错误，不悄悄新建替换／改模型；CLI 参数与实际 metadata 一起记录。

| 门槛 | 允许的工作与完成条件 |
| --- | --- |
| G0 合同核对 | 后续正式派发时四方先只读确认DTO／七表／facts／token／busy／职责清单及源身份。Codex 核对后才能编码；接口矛盾在此解决，不能四方各造一套。 |
| G1 数据与纯内容 | A 实施数据／来源／配置／回执／备份，B 实施纯内容／独立反例；C可独立实现主题前端并交A做自有共享接线，D仅准备不冲突材料；周UI／导出不接未冻结接口。A/B停写后 Codex 真SQLite／迁移／恢复／内容核查。 |
| G2 页面与导出 | G1通过、结合目标启动／保存重开／备份恢复反馈评估后，钉住模型／DTO再 C/D 并行自有文件；A做自有共享接线，不与其同改。响应形状需变先停依赖方、交 Codex 更新合同。 |
| G3 独立整合 | 全部停写；Codex 核源码、反例、必要全local／desktop／前端；真实源码窗口、原生保存与新 Word 各记实证。失败交原责任人，不用改断言掩盖缺陷。 |
| G4 交付 | 新迁移／模板／模块补来源冻结和归档必需集。新构建须当时明确范围、新根／完整静态／真实目标边界；不执行已知4551候选。Git仅在 Codex精确文件/blob/parent/tree门禁后由A正常提交推送，不把此设计当已授权立刻构建或Git。 |

## 9. 独立验证与未验

产品 WP01–WP15 为主矩阵。至少补：复合FK真失败／整笔回滚、同周并发唯一、同键异载荷／丢响应后冷重启查回执、旧确认后继续编辑、来源集合新增／日历史恢复、当前游戏移除而历史仍真、伪造跨计划来源、0006升级及旧值摘要、007备份保护包接续、名单空值／同名顺序／个人更名隔离。

页面必须覆盖 dirty旧确认导出不保存、不清稿；当前保存后新输入／切周不继续确认；两个切周目标不合并；clean但confirm/export在途仍拦关闭／维护。导出须验猜ID、跨用途／session／launch／profile token、同token异文件名、并发跨通道、写成后回执丢失不重写、恢复／retire后的迟到对话框不落盘、历史日期不漂移。

执行检查沿用现有Windows原生环境，不装新依赖；短TEMP只配置给独立验证进程，不改系统。先专项再受影响全回归，代码不变不机械重跑。真实AI、目标机器、Word逐页、静态、源码窗口分开结论；未得到用户目标回执不填通过。原设计阶段未运行上述测试；本轮实际验证及未覆盖项见实施核查。

## 10. 设计依据与审阅边界

使用 codebase-memory Verify，父代次 `2026-11-01T01:16:17Z`，11相关证据路径均 metadata_changed，local仅已知 `__pycache__` 排除，d1无已记录缺口；已作定向回读。两个 Codex 只读分析分别核数据／备份与页面／原生导出，未改文件、未充当实现者。额外 d1_digest、migrations_local/env.py 等按源码补查，不据此声称全依赖闭包。

关键依据为 LocalClass／LocalConfigOperation、config_service.preview/apply、migrate.head_revision、backup_validate源schema顺序；EditorBridge/leave/App关闭、观察原生原子stream及拒绝机制；既有周 mapper日期重算。复用以本文件明确边界为准，不把旧测试数字作为新模块通过。若开工发现不满足合同或需要系统级边界改变，先停相关实现、交明确影响／ADR草案。

本轮复核修正：stable identity移除可变draft version；确认日历来自保存稿；导出同profile复合关系与receipt结果成对CHECK；create/retry持久回执及同launch可重放token、跨launch失效；retry旧attempt唯一后继。导出HMAC使用规范编码和独立用途，不用JS可见的launch_token/page_ticket作私钥；明文token不进通用result_json／日志。retry完整核对旧token/attempt/profile/snapshot/scope，不同request抢同parent返回409。跨launch或过期只返 `transfer_expired` 元数据，不续期、不重生成；`generated` 与原生 `saved` 独立。以上为设计修正，不是运行测试结果。

## 11. 本轮 G0 接口核定补充

本节解决四方草案的接口差异；不改变已决教师流程。A/B/C/D 各自消费同一合同，不照各自 G0 建议另造一套。实际开工 HEAD 为 `d6de14cb85040e5e68e3eab36b6d34fd5c927f8b`；Codex 的 AGENTS/current 文档改动不属于实施者文件。

### 11.1 命名、空值与限额

- 表头 DTO 与创建快照统一为 `{school_name,class_name,grade,header_teacher_names,caregiver_name}`；不添加自动填入的个人姓名。旧 Word mapper 若用 `teacher_names`，仅由 D 的纯 adapter 映射。
- 统一 `source_kind`、`group_id`、`section`，不用 `kind/group_key/source_section` 的第二套别名；日期 PATCH 为 `deterministic_overrides`（日期到两个覆盖字段的映射），不接收客户端 deterministic/source/effective 全文。
- 周 `theme` 持久值为字符串，空为 `""`。PATCH 遗漏保持；显式 null 在输入边界归一为 `""`，不可将默认 null 当作显式清空。两日期覆盖的 null 仍表示跟随日值，`""` 为明确空。
- 名单按本轮已定的 100 项／每项80字符／规范 JSON 32KiB，旧 helper 的20项不能直接沿用。ID 为32字符以内，request_id 为36以内，client_key 为64以内；版本严格正整数、拒绝 bool。
- 旧周 DTO 的 theme/note/四栏及对应正文没有统一的单字段 max_length；维持严格类型和总正文1MiB防护，不新加100,000字、100个正文数组项或200字备注等限制。所有限额整体拒绝，不截断。固定7日／3户外槽／4周栏目及既有明确配置限额保持。

### 11.2 A/B 纯内容接口

采用 B 的受信 `WeeklySourceSnapshot` 形状：profile_id/class_id/term_id、固定 week_anchor_date/week_number、term_start/term_end、calendar_revision_id、创建 header、config_version、game_context、source_context_hash、按日期升序的7个 days。每个 day 包含 date/day_state/source_state/source、morning_groups 和 post_group_groups；A 从授权日内容构造，B 不查库、不鉴权。source 增加 canonical 日采用内容的 `content_hash`。

```python
validate_source_snapshot(snapshot) -> dict
new_content(snapshot, *, theme="") -> dict
apply_patch(previous, patch, snapshot, *, manual_ids=None) -> dict
refresh_content(previous, snapshot) -> dict  # content/differences/preserved
build_facts(content, snapshot) -> dict       # missing/stale_sources/warnings
build_source_candidates(snapshot) -> list[dict]
canonical_json(value) -> str
content_hash(content) -> str
validate_content(content, *, snapshot=None) -> dict
```

草稿严格固定 schema_version/theme/deterministic/outdoor_game_slots/focus_area/weekly_columns/materials/source_manifest/calendar_basis；calendar_basis 使用 term_start/term_end。户外保留 shared_objectives/guidance_points/focus_guidance，重点区域保留 context_kind/area/objectives/guidance/support_strategy，不把两类正文强行转成相同文本字段。

新选／明确改选日引用只提交 `{source_kind:'daily_plan',daily_plan_id,content_id,content_version,content_hash,section,group_id,game_id}`；户外 section 仅 morning_games，重点区域仅 post_group_games。候选携带这些定位字段、日期、category/group_kind及同一来源的完整正文；客户端不提供可信来源正文。A 在事务内核对预期来源，B 从受信快照物化。存储引用也保留 hash/section；手工引用全部日定位字段为 null。新 manual 用 client_key，A 注入 manual_ids；已有 manual_item_id 必须属于该计划，回放不得重生ID。

普通保存对未提交字段及未改选的完整历史引用逐字保留，不刷新 deterministic 来源、source_manifest 或 calendar_basis，也不因 live 来源已变化而拒绝合法旧引用。明确重新选择必须按完整引用校验。不同同名来源可分别成为候选，但同类别同名不能占两个槽（含日来源与手工混选）；按去首尾空白后的名称比较，不能混用两来源的整组文本。

source_manifest 保存创建身份／header／周次及该稿使用依据；其 config_version/header 不能整体成为 freshness 比较输入。A 计算 source_context_hash 时覆盖本周完整本人来源集合（含新增日计划）、相关游戏配置及实际日历，排除主题偏好、无关配置版本、后补名单／保育员。game_context 可记录实际 revision_id/revision_no 及相关依据摘要，但不能仅因无关配置头变化标旧。

刷新保留创建 header/grade、周锚点／显示周次及人工正文，只更新允许变化的来源和该固定自然周的 calendar_basis；消失项保留真实历史引用／全文并标缺失。`build_facts(content, snapshot)` 的 content 决定固定目标、header/calendar及 missing，snapshot 是 A 当前一致读取的比较来源，计算 stale/warnings；不能以保存稿旧来源替代确认时实时比较。确认 token 绑定目标及当时事实；历史确认读取／导出直接使用已存 facts。

facts 每项使用稳定 code/field_path，引用统一 old_ref/new_ref（含确切版本/hash/section/group/game），其它实际信息放 details；可带供显示的 message，不以拼好的文字代替结构。禁止 Q1 的“有效手填仍缺本人日计划”旧口径。B 的错误由 `WeeklyContentError`（code/field_path/details）交 A 映射 LocalError。

### 11.3 A/C 主题与共享接线

不修改 LocalInitializeIn、初始化参数、retry fingerprint 或 normalize.py；采用明暗规格既定的“完成初始化后先 GET 偏好版本，再单独 PATCH 本窗口最后明确选择”。context 不增加 appearance 字段；初始化成功与偏好保存结果分开。

AppearanceDTO 固定 `{mode:'light'|'dark',version:number}`，PATCH `{mode,expected_version}`；409 为 APPEARANCE_VERSION_CONFLICT，details 含实际 mode/version。C 的 controller 采用以下唯一接口，A 按此接线：

```ts
createThemeController({ api: { get, patch }, apply, notify? })
// 返回 mode/version/status 的 Vue refs（version 初始 null）及：
initialize({context:'uninitialized'|'ready', profileEpoch:number}): Promise<void>
setMode(mode): void
retry(): Promise<void>
reset({reason:'restore'|'profile-replace'|'retire', profileEpoch:number}): void
dispose(): void
applyThemeMode(root: HTMLElement, mode: ThemeMode): void
```

ThemeStatus 为 idle/saving/saved/unsaved/conflict/unknown。initialize 的首次页→ready 保留最后意图，同一 epoch 重复 context 更新不重置；reset 明确丢弃旧意图和队列，含相同profile ID的恢复也用新epoch。维护期间仅视觉切换并标未存，恢复后不得补写旧队列。ThemeToggle props 为 mode/disabled?/pending?，只发 change(mode)。CSS token 统一 --kgm-bg/surface/text/muted/border/overlay/accent/success/warning/danger/diff-add/diff-remove/disabled/focus；A 的自有文件也使用这些 token。

EditorBridge 维持现有方法形状；A 为 BlockingDraft.kind 增 weekly、LeaveAction 增 target_key，并令 actionKey 包含具体周目标。C 的 identity 仅 plan_id:editor_epoch；版本单独存基线。A 把周 busy 接 close／维护最终复核，不能只看 dirty。Q3 当前链每个 await 后检查 identity、输入修订及请求 sequence；旧确认链不经过 saveCurrent 或离开保存 helper。

### 11.4 模型、回执与文件归属补充

七表类名采用 A 的 LocalWeeklyPlan/Content/Confirmation/Operation 及 LocalWeeklyExportSnapshot/Token/Attempt，字段／同profile复合关系仍严格按 §2；note 使用可空正文，不加200字限制。CHECK／FK 的命名由 A 选择既有风格，具体真约束交独立 SQLite 验证，不把约束名字当需用户决定事项。

A 的 weekly_plan_operations 提供 fingerprint(action,payload)、find_receipt(session,*,profile_id,request_id,action?,fingerprint?)、store_receipt(session,*,profile_id,request_id,action,fingerprint,result,**result_fields)，查找／写入返回 operation 对象且均不自行 commit。D 在同一元数据事务调用；相同键优先核 action/fingerprint并回放原结果。

weekly_plan_tokens 的 issue/verify/derive_export_id 接收所归属 runtime，私有随机 HMAC 密钥归该 runtime 生命周期、用途独立，不用页面可见token；derive_export_id还绑定profile/snapshot/token/request/launch/scope。不能用一个模块全局可变key让无关Runtime互相退役。A/D 冻结实际函数签名后共用。

在 §8 A 白名单外，另明确 **desktop/d1_main.py 仅归A**（仅在周通道宿主／维护生命周期确需时最小接线）；**frontend/package.json 仅归A**（将C新测试接入 test:d1，不改依赖或锁）；**backend/app/local/errors.py 仅归A**（仅注册本片外观／周计划所需的LocalError类型，不改旧错误语义；该必要映射已在范围核查中归A）。normalize.py/SetupView.vue 不扩入；D 不接管d1_main。`.weekly-export-work` 仍归受信data根及runtime生命周期，宿主通过固定受限内容接口流式读取，不另造绕过备份维护的任意TEMP业务缓存。

B纯内容r03停写且独立专项通过后，另授 **新 backend/tests/local/test_weekly_plan_integrity.py 仅归B**，用于不相交的数据库／来源／备份反例；A不得修改其断言或夹具，失败交B核定测试本身或交A修实现。B原两个纯内容文件保持已核身份，不为新增反例改业务实现；新测试可用合成SQLite／现有服务，但不改变纯内容模块的无DB边界、不改共享fixture。这是独立测试责任扩充，不增加第五实现者或提前G2。

A的G1返修另授 `backend/tests/local/test_daily_plans.py` 与 `backend/tests/local/test_observation_migration.py`，仅最小更新本片必要的schema／head断言：日计划仍禁止旧云端周投影及响应中的weekly_sync字段，允许本片准确七表；观察E02保留真实0005→0006专项，只有最新Runtime阶段采用当前head，不能全局替换0006或删断言。必要时A可新增 `backend/app/local/weekly_plan_snapshot.py` 及对应独立测试，统一下述严格确认schema，避免service／backup／D各建弱副本；仍不改B模块或其独立反例。

A G1 r04另授新 `backend/tests/local/test_weekly_plan_api.py`，仅真实回环HTTP的列表注册、筛选／分页、已提交operation原结果投影及预览前提合同；不改共享support或B测试，不以service直调替代HTTP注册证据。创建预览的新建分支明确返回所捕获的expected_config_version与expires_at，刷新预览也返回与确认预览同型的expires_at；客户端复制明确前提，不解析token或借用后来更新的context版本。

所有新日志／合成库／报告用本轮新根。G0 B把一份报告新写入旧便携验证临时根，现场保留且不再续写；A两次只读模型metadata导入未先装guard，仅为G0源核对，不计受控Runtime或网络验证。G1起任何app import／Runtime／子进程均按合同先安装guard并设APP_DISABLE_DOTENV，不沿用上述调用方式。

### 11.5 D 导出合同核定

预览只物化 manifest及限时受信内存上下文，不登记DB snapshot/token/operation、不生成DOCX或写work文件；返回 context_token/manifest_hash/expires_at/selection/items/missing/warnings/warnings_as_of/suggested_filename。create 只从该上下文的固定确认生成，最终事务才登记持久snapshot/token/operation；缓存丢失明确要求重预览，不猜测重建旧提示。旧确认不受当前draft/head/warnings变化拒绝。

manifest固定为schema_version=1、profile_id、mode、requested_range（start/end或null）、selection、warnings_as_of、missing、warnings、items。selection按实际周升序，含weekly_plan_id/confirmation_id/confirmation_version/draft_id/draft_version/content_hash/confirmation_hash/week_anchor_date/week_number/date_range；items严格按§11.7承载完整确认快照及确认身份，anchor/week只经creation_context映射，不再平铺别名。warnings_as_of记录比较时点，warnings保存该次预览的实际结构化提示；items.facts只复制确认已存facts，顶层missing只汇总静态缺项。汇总项details标明weekly_plan_id／confirmation_id。create消费已物化manifest，不重新汇总实时变化而偷换对象；不把顶层实时warnings回写历史facts。theme只在content，不向header增个人姓名或主题。

create/retry/operations查询统一返回§4的 `{operation_id,request_id,generation_status,snapshot_id,manifest_hash,export_id?,expires_at}`；未失效 generated 重放同一export_id，跨launch/scope或过期 transfer_expired 只返原结果身份，不生成新token/DOCX。token_id为内部字段；固定DOCX的SHA称artifact_hash，不与草稿content_hash混名。request_id复用A的共同规则，不另加仅导出适用的UUID限制。

attempt start/latest/result均携带filename，result另带attempt_id；服务核对同profile/snapshot/token及filename fingerprint。byte_size在DB与DTO均为非负整数：saved>0且result_hash等于固定DOCX；in_progress/cancelled/failed/indeterminate为0且result_hash=null。0仅是未证实成功的记账值，不能断言目标文件不存在，不能删除用户既有目标。

start在短事务内唯一登记并绑定filename；同token同名先回原attempt状态，异名409，不再开对话框。新attempt与下载须在token有效期内；token于终态提交时消费，已有attempt唯一约束阻止终态前双重执行。已在有效期内登记并完整下载的attempt可完成已打开的原生对话框，但TTL不延长；原生返回后仍核retire/维护/launch/scope，失效不落盘。过期后只允许补记／查询同一已登记attempt的终态，不获得新下载／对话框／写入权；回执丢失只补回执，不重写。仅failed/cancelled可在snapshot未过期时retry，旧attempt唯一后继，不延长snapshot寿命。

关闭读取handle／释放引用与删除artifact区分；失败／取消后，固定DOCX保留供合法retry，直至过期或受控生命周期清理。backend work归runtime受信根；host只保留本次合法下载的自有临时副本，finally仅清自己的文件，不需要由页面传入缓存路径。

D直接使用§11.4的find_receipt/store_receipt及runtime私有token helper，不另造replay/record/mint_context别名；preview/create/retry/operation投影均接所属runtime。宿主对外可沿既有 saved/canceled/failed/pending/unknown 形状，DB cancelled→canceled、indeterminate→unknown，带attempt_id供查询；unknown不得显示明确重试。A/C/D在G2前以G1实际冻结源码再次核精确签名，不能以草案代实际接口。

### 11.6 G1审核后冻结的确认与回执schema

严格 `ConfirmationSnapshotV1` 仅含 `schema_version=1,weekly_plan_id,profile_id,class_id,term_id,draft_id,draft_version,content_hash,header,creation_context,content,date_range,columns,facts`。creation_context严格为 `week_anchor_date,week_number_snapshot,term_start,term_end,calendar_revision_id`，来自计划创建时，刷新不改；header保持五键。content为确切保存稿，包含该稿自己的calendar_basis；content_hash为该content规范hash，snapshot_hash为整个snapshot规范hash。确认表facts_json必须与snapshot.facts一致；确认ID／版本／备注／确认者／时间由不可变确认记录承载。

columns按日期升序，每项严格为 `{date,day_state}`：固定周一至周五，加该保存稿calendar_basis中确为教学日的周末，不按创建日历或实时日历重算。date_range严格为 `{start,end}`：优先该稿basis首末教学日；零教学日采用该稿学期与固定自然周交集。**2026-11-01用户补充确认：若明确刷新后新学期与固定周完全不相交，沿用计划创建时学期与该周交集日期**，不移周、不以当前日期补齐。创建时必有交集，故date_range仍为有效升序日期。

确认预览返回完整target及target_hash／token／expires_at，提交重核来源及facts后持久化教师已见的同一target；不得先预览一种结构、确认时另拼一种。历史详情统一返回 `{confirmation,snapshot,note,confirmed_by,confirmed_at}`；confirmation为 `{id,version,draft_version,snapshot_hash}`。D只有一个adapter：confirmation.id/version/snapshot_hash映射confirmation_id/confirmation_version/confirmation_hash；snapshot.draft_id/draft_version/content_hash照取，creation_context.week_number_snapshot映射week_number。header/content/date_range/columns/facts直接取冻结值，header_teacher_names仅此adapter映射旧Word的teacher_names。缺失字段拒绝，不用实时plan／term／grade填补。

operations的result_json采用严格版本化metadata，唯一键为 `schema_version=1,weekly_plan_id,draft_id,draft_version,confirmation_id,confirmation_version,snapshot_id,token_id`；不适用引用为null，适用引用须成对完整，且与operation结果列及归属完全一致。不得存正文、snapshot全文、header／facts／路径／DOCX、context_token或明文export_id，也不复制operation自身已有ID。业务响应按确切draft／confirmation引用投影；导出响应按确切snapshot／token及runtime推导同一export_id。先查已提交回执再核临时预览资格，不能因token过期或缓存丢失抹掉已提交结果；不得读取最新head冒充原结果。

### 11.7 导出manifest严格嵌套结构

manifest顶层严格为 `schema_version,profile_id,mode,requested_range,selection,warnings_as_of,missing,warnings,items`。每个item严格为完整ConfirmationSnapshotV1的14键，另加 `confirmation_id,confirmation_version,confirmation_hash` 三键；不另增term、week_anchor_date、week_number等重复字段。先核17键集合，再提取14键投影调用统一确认validator；confirmation_hash等于该14键投影的canonical hash，不对含自身hash的17键对象算确认hash。manifest_hash覆盖完整manifest。

item的确认ID／版本对应真实不可变确认行，14键投影与该行snapshot_json的完整规范内容相等，confirmation_hash等于该行snapshot_hash，并核同plan/profile及草稿归属。不能只验item自算hash，不能用当前plan/head、日历或配置重建历史快照。A在共享snapshot模块提供纯结构校验，备份外层负责真实DB关系；D消费同一校验与形状，不另建弱副本。

selection每项严格为 `weekly_plan_id,confirmation_id,confirmation_version,draft_id,draft_version,content_hash,confirmation_hash,week_anchor_date,week_number,date_range`，序列逐项等于items的确定性投影；anchor及week_number取creation_context。single恰一项且requested_range为null；range范围合法，各项冻结教学日须与范围相交，同一计划不重复、最多8项，按anchor／term_id／weekly_plan_id升序确定顺序。跨学期不能仅凭同周号或同anchor合并。

顶层missing等于各item已存facts.missing的静态汇总，按items及原事实顺序，复制原事实并在details加入所属weekly_plan_id／confirmation_id；其余原details保留。warnings_as_of为此次预览时点；warnings只按统一事实结构及所选归属检查，不与恢复时live来源重比，不回写items.facts。

备份验证全部历史选集的结构、引用、顺序及范围关系，不要求它仍等于当前latest或当前全部范围候选；后来新确认／新计划不使旧合法manifest损坏。内存preview与create登记的持久manifest使用同一schema。

### 11.8 G2分片与共享执行合同（已核定）

本节细化已定产品行为，不增加教师步骤或产品限制。G1已完成独立整合及最终配置复验，来源已固定；G2b按实际依赖分批放行：C core及DTO独立通过后可先写C界面，D host须等D backend通过，A共享接线须消费已冻结SFC合同；实际G3仍等全部停写整合。下述manager字段和方法是确定的待实现合同，不声称当前已经提供。

#### 11.8.1 分片与唯一责任

| 阶段 | 唯一写入范围 |
| --- | --- |
| G2a C core | frontend/src/d1/weekly.ts、weekly-editor.ts、d1.weekly-core.test.mjs；不写SFC、package或共享接线，不改冻结15个主题文件。 |
| G2a D backend | backend/app/local/weekly_plan_export_service.py、weekly_plan_export_api.py、backend/tests/local/test_weekly_plan_export.py；manager类放自有export service，不新增另一manager模块或修改runtime／models。 |
| G2a A backend与来源登记 | app.py、runtime.py及确受影响的backup_snapshot.py、backup_fs.py、restore_service.py、restore_group.py、restore_recovery.py；desktop/maintenance_host.py、maintenance_lifecycle.py，d1_main.py仅必要生命周期绑定；errors.py仅追加本节三类；构建／静态来源登记按本节末尾。其余G1冻结文件不顺手修改。 |
| G2b C views | 四个专属WeeklyPlansView／WeeklyPlanEditorView／WeeklyHistoryPanel／WeeklyExportDialog.vue；消费已冻结core与协议，不接管A共享文件。 |
| G2b D host | desktop/d1_host_api.py、desktop/tests/test_d1_weekly_export_host.py；两个真实周host方法与原生IO。 |
| G2b A frontend | 按原A白名单接App/main/leave/bridge/client/types、Workbench/Settings及package测试入口，不改C文件或B冻结模块；确需增量先核准确责任。 |

A已有desktop维护整合测试仍只改真实受影响断言。所有参与者不fork／另派子代理，不覆盖他方修改；缺接口由Codex给唯一责任方，禁止静默可选导入、成功替身或第二套协议。G2a不提前打通页面、原生窗口或Word验收。

#### 11.8.2 A4实际业务HTTP衔接

业务前缀/api/weekly-plans，无data envelope。GET列表实际绑定weekly_list；query为term_id?／from?／to?／cursor?／limit?，from/to筛周锚点。完整学期取GET /api/local/context的terms，不能仅用可能为null的context.term或按新建资格隐藏旧周。

| 对象／动作 | 精确键及映射 |
| --- | --- |
| create-preview new | status:"new"、header、week_number、calendar、source_candidates、source_context_hash、facts、create_token、expected_config_version、expires_at；calendar含week_anchor_date/term_start/term_end/calendar_revision_id/days。 |
| create-preview existing | status:"existing"、plan、draft、confirmed、source_candidates、source_context_hash、facts，以及create_token:null、expected_config_version:null、expires_at:null；直接打开已有记录，不提交三个null创建新稿。 |
| POST创建 | request_id、term_id、week_anchor_date、expected_config_version、context_token；取本次new预览版本，context_token=preview.create_token。 |
| PATCH保存 | request_id、expected_draft_version、patch；只提交真实变化字段，未改选历史引用不重发为明确选择。 |
| refresh-preview | target_draft_version、content、content_hash、differences、preserved、source_candidates、source_context_hash、facts、preview_token、expires_at。refresh-sources提交request_id／expected_draft_version／preview_token。 |
| confirmation-preview／confirm | 预览返回target／target_hash／preview_token／expires_at，正文是target.content；confirm提交request_id／expected_draft_version／context_token=preview.preview_token／ack_missing／ack_stale／note?。 |
| history | {confirmation,snapshot,note,confirmed_by,confirmed_at}，正文是snapshot.content；确认摘要为{id,version,draft_version,snapshot_hash}。 |
| 公共操作回执 | GET /operations/{request_id}调用get_business_operation，返回WriteResult；get_operation与operations.replay仍仅给内部／B返回8键metadata，不作为公共HTTP。 |

WriteResult={operation_id,request_id,status:"committed",weekly_plan_id,draft|null,confirmation|null,replayed}；Draft={id,version,content_hash,content}。查询replayed当前为false也可以证明已找到原提交；不能用该flag代替提交身份核验。save结果confirmation=null不清除旧确认。回执按原不可变版本投影，即使head已到v3也不能把v2原结果替换成v3。

C保持plan_id:editor_epoch身份，版本另存；不同目标周使用不同target_key。保存响应只推进提交投影，手工client_key与返回槽位manual_item_id按原提交对应，不覆盖在途新输入或复活已删除项。Q3当前链每个await核身份／输入修订／sequence；旧确认链零save、不清dirty。unknown沿既有观察的可恢复语义：可查询原request_id回执，也须保留由用户明确“再次提交”原请求的入口；GET404不证明失败，不自动重发。明确再次提交仍用原request_id／原payload／原expected version，不将较晚输入混进原请求，不自动续跑旧确认／另存为链；clean但操作在途仍提供busy及blockingDraft供A接关闭／维护。

#### 11.8.3 周导出HTTP唯一DTO

前缀/api/weekly-exports；全部JSON请求extra=forbid、严格bool／int，日期为规范YYYY-MM-DD字符串。ID沿既有限额，request_id沿共同规范化且不额外限UUID；单份／范围均最多8份，范围无额外天数或term_id过滤。只有请求到manifest的start_date/end_date→requested_range.start/end一次映射，不接受其它日期别名。

| 方法／路径 | 精确请求 | 精确响应 |
| --- | --- | --- |
| POST /preview | single={mode:"single",weekly_plan_id,confirmation_id:ID\|null}；range={mode:"range",start_date,end_date}。null明确latest；无request_id、ack、snapshot_id或正文。 | {context_token,manifest_hash,expires_at,selection,items,missing,warnings,warnings_as_of,suggested_filename} |
| POST空路径 | {request_id,context_token,ack_missing}，三键必填，不复制manifest正文。 | ExportOperationResponse；首次201／同请求回放200。 |
| POST /snapshots/{snapshot_id}/retry | {request_id,old_export_id,attempt_id}，snapshot_id仅路径；无新manifest或retry_existing。 | ExportOperationResponse；首次201／同请求回放200。 |
| GET /operations/{request_id} | 无body；仅export_create／export_retry结果。 | ExportOperationResponse；未查到404不能证明原操作失败。 |
| POST /{export_id}/attempts | {filename} | AttemptResponse；HTTP200，仅新建attempt的should_prompt=true。 |
| GET /{export_id}/attempts/latest | 唯一必需query为filename，无body。 | AttemptResponse；should_prompt=false；无记录404，不新建。 |
| POST /{export_id}/attempts/result | {attempt_id,filename,status,byte_size,result_hash}，五键必填。 | AttemptResponse；HTTP200，同一终态补回执不重写。 |
| GET /{export_id}/content | 无body／任意地址参数，固定token通道。 | 固定DOCX二进制及下述headers。 |

ExportOperationResponse为判别联合：
- generated={operation_id,request_id,generation_status:"generated",snapshot_id,manifest_hash,export_id,expires_at}。
- transfer_expired={operation_id,request_id,generation_status:"transfer_expired",snapshot_id,manifest_hash,expires_at}，必须省略export_id，不返null或另造token。

AttemptResponse={attempt_id,status,filename,should_prompt,byte_size,result_hash,started_at,ended_at}。
DB状态为in_progress／saved／cancelled／failed／indeterminate；result请求只接受后四种。
saved的byte_size>0且等于固定artifact字节数，result_hash=artifact_hash；其余byte_size=0、result_hash=null。0不证明用户目标不存在。in_progress的ended_at=null；终态有记录时间。不同终态／hash／size不得覆盖已提交终态。

filename是本次host调用的规范化逻辑basename，后续start/latest/result/query必须相同，不用原生实际target basename替换。沿既有合法.docx basename、长度、控制字符／路径／保留名规则，API与host同一规范化；不上传目标路径。suggested_filename仅为合法建议，不能将非法用户输入静默清洗成另一名称。

content响应固定：
```http
Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document
Cache-Control: no-store
Content-Length: 固定字节数十进制，>0且<=134217728
X-Content-SHA256: artifact_hash，小写64位十六进制
X-Export-Expires-At: 本次token与snapshot较早到期时间，带Z的UTC ISO8601
Content-Disposition: attachment
```
不另造hash header别名，不回显用户目标路径。host拒绝重定向、类型／长度／hash不符及超限，完整校验后才进入原子保存。

preview只物化限时内存上下文；不登记DB snapshot/token/operation、不生成DOCX或写work。selection／items／manifest完全沿§11.7的10／17／9键。single=null及range的latest在预览时解析；range以确认冻结的实际teaching日期相交，同计划去重、按anchor/term_id/plan_id升序。零教学日只single，旧确认不被当前draft/head或新warning拒绝。

missing静态汇总须带选中归属，warnings只作该比较时点提示，不回写历史facts；create只有ack_missing，不增加ack_stale或理由。先查已提交回执再核临时预览资格；同键异载荷409。同键并发只提交一个snapshot/token/operation，失败方仅清自己的临时文件。

preview/snapshot/token各自TTL600秒；retry不延长原snapshot，只有failed/cancelled可明确重试且每旧attempt唯一后继。in_progress/saved/indeterminate不发新token。有效期内已登记且完整下载的原生attempt可完成已打开对话框，但返回后仍核生命周期／publish；超期不授新下载／对话框／写入权。回执丢失只补回执；generated不是原生saved。

纯metadata查询与执行权限分开：operations及已登记attempt只读查询按当前API鉴权、profile归属、原filename和可读DB投影，不进入manager.activity/publish，不要求有效预览或开放manager。manager缺失／closed、跨launch/scope或过期时，导出操作仍返原身份及transfer_expired，已存attempt状态照实返回，不抹掉saved。DB不可读就明确报错，不猜造或重建记录。终态补记是写操作，不享受该只读例外。

#### 11.8.4 Manager公开合同与固定绑定

D在weekly_plan_export_service.py内实现下列类，A在绑定处局部import，D不import runtime.py／app工厂／router，不建立全局多manager registry，不创建Session／执行启动SQL／轮换key。

```python
class WeeklyExportManager:
    def __init__(self, runtime: Any, *, launch_id: str, session_scope: str) -> None: ...
    @property
    def is_closed(self) -> bool: ...
    def pause(self, *, owner: str) -> None: ...
    def resume(self, *, owner: str) -> None: ...
    def wait_idle(self, *, timeout: float = 60.0,
                  cancel: threading.Event | None = None) -> bool: ...
    def close(self) -> None: ...
    def activity(self, *, kind: Literal["preview","generate","download","native","receipt"],
                 launch_id: str, session_scope: str) -> ContextManager[int]: ...
    def publish(self, *, epoch: int, launch_id: str,
                session_scope: str) -> ContextManager[None]: ...
```

本节session_scope均为app内部随机scope原值；HMAC参数session_scope_hash=scope_hash(session_scope)，不得把原值／hash混绑定。

A在LocalRuntime增加weekly_export_manager:Any|None、_weekly_export_binding:(launch_id,session_scope)|None、专用_weekly_export_bind_lock:RLock，以及仅计算绝对data根下.weekly-export-work的weekly_export_work_root；prepare／preview不创建work目录。

```text
LocalRuntime.bind_weekly_exports(self, *, launch_id: str, session_scope: str) -> Any
```
仅prepared且A启动／恢复SQL完成后调用。相同binding的开放实例复用；关闭实例不复开。不同binding只有旧实例closed且wait_idle(0.0)=true才替换；A用自己保存的binding及公开is_closed，不窥读D私有字段。新构造成功后一起更新实例与binding。

create_local_app在生成本次session_scope后、任何API可服务前确保runtime.launch_id非空：保留已有值；缺失时由A创建一次UUID，不依赖AI executor成功。工厂完成handover/bind，将实例固定保存app.state.weekly_export_manager。首次及恢复重开均走同一工厂；D API使用request.app.state固定实例，不逐次从runtime当前字段取manager。

G2b的D1HostApi新增可选weekly_export_manager:Any=None，A将该app实例传入首次与恢复后的两个host构造；host保存固定引用。未注入时仅新增周save返回failed／WEEKLY_EXPORT_UNAVAILABLE，query返回unknown／同码，不创建attempt、下载或开框；旧日／观察构造和行为保持。
MaintenanceHost同样新增可选weekly_export_manager:Any=None，由A注入该app固定实例，维护worker／finally使用该固定引用，不通过runtime当前字段取得后来manager。

同Runtime不同scope的显式handover由A绑定锁串行：
1. 旧实例不idle则立即拒绝，不close旧manager或启动新server。
2. idle开放旧实例先pause独占factory owner，再wait_idle(0.0)复核；竞态出现活动则仅resume该owner并拒绝，已清preview不恢复。
3. 确认idle后close旧实例，再确认closed且idle，才bind新scope实例。
4. 新构造／工厂后续失败不复活旧weekly manager。旧app非周接口、server、runtime/executor、adoption key／receipt不借此退役或失效；旧transport关闭只清自己的固定manager，不能误关新实例。

#### 11.8.5 暂停owner、活动与最终发布

manager以同一Condition/RLock保护closed、owner集合、epoch、preview及活动／读取引用。pause(owner)同步短执行；同owner幂等，新owner加入递增epoch并清旧preview。resume只移除本owner；closed不复活，其余owner或barrier intent/exclusive仍在时不接新活动。wait_idle只等实际活动／引用归零，cancel只接受threading.Event或None，超时／取消／未知返回false。

activity核固定绑定、开放状态、owner及barrier实际intent/exclusive，返回epoch并在finally释放计数。generate/download/native以既有backup_barrier.file_scope覆盖完整寿命。preview只读也计数，发布到缓存前须经publish；receipt只补同一已登记attempt，不授新IO。

publish是短临界区，核epoch、固定绑定、closed／owner以及barrier实际intent_owner/exclusive_owner；不能只调用可被file_scope continuation穿过的assert_writes_allowed。检查与最终metadata事务commit／目标原子writer不可分隔；pause与publish在同锁下线性化。生成DOCX、下载、等待原生对话框不持publish锁。原生返回先核_native_io_refusal，再由旧host固定manager.publish包住writer；共享_save_mutex/_save_inflight涵盖日／观察／周。

A调用点：
- MaintenanceHost接纳backup／restore后、启动worker前pause("host:"+operation_id)；worker最外finally在本次lease释放后resume同owner。
- SnapshotService.create在begin_intent前pause("snapshot:"+id)，RestoreCore.install同理pause("restore:"+operation_id)；finally先释放自己的barrier lease再resume自己的owner。保护包捕获复用外层维护，不另抢冲突lease。
- 保持begin_intent→wait_idle→acquire_exclusive及原host保存／transport停止确认；未确认静止不得切DB、删work或释放runtime锁。
- 正常close沿当前request身份保护的on_close_intent/on_close_canceled暂停／恢复该bundle owner；busy加入manager.wait_idle(0.0)为false的活动／引用，不改教师关闭流程。
- LocalRuntime.close_engine_keep_lock／dispose新增weekly pause→bounded wait的前置阶段，必须在旧dispose清factory/engine/inspection、rotate、_retire_engine及其finally之前。weekly等待失败仅resume本owner，保留原engine/factory/rootlock并明确拒绝本次切换。确认idle后close manager，才进入原方法的engine退役／错误收尾；closed manager不复活。进入旧dispose后_retire_engine抛错时既有finally释放自己锁的语义保持，不扩成“所有engine异常保锁”；close_engine_keep_lock原有保锁语义保持。
- A唯一执行冷启动／恢复SQL失效和key轮换；旧in_progress→indeterminate并消费token，不删持久历史。D不另造reconcile。恢复SQL／launch准备完成后由新工厂绑定新scope manager；旧bundle永不重指向新实例。

流式content在首字节／交StreamingResponse前结束read_scope并释放业务Session，仅物化标量授权、manager登记handle及读取引用；不能让ORM／DB读事务随下载生成器存活。完成、断流、异常、取消均finally释放handle/ref/file_scope。读取引用与删除artifact分开；失败／取消的固定DOCX保留供合法retry。

work只在受信绝对data/work边界、reparse与owner/文件身份校验后创建本generation独占文件；constructor/preview不建目录。host临时副本也登记本次owner；新manager不接管相似旧目录或未知文件，不盲目rmtree，不删用户目标或持久metadata。备份不采集work。close短且幂等：封入口、增epoch、清preview、通知取消；只清无引用的本代已知文件，其余交最后活动finally。

#### 11.8.6 A新增错误与共享helper

G2a仅A可在errors.py追加下列三类，D直接import；不改既有错误语义或另建同义类：

| Class | code / HTTP | 默认中文message |
| --- | --- | --- |
| LocalWeeklyExportNotFound | WEEKLY_EXPORT_NOT_FOUND / 404 | 未找到该周计划导出记录 |
| LocalWeeklyExportUnavailable | WEEKLY_EXPORT_UNAVAILABLE / 503 | 周计划导出暂时不可用，请稍后重试 |
| LocalWeeklyExportConflict | WEEKLY_EXPORT_CONFLICT / 409 | 周计划导出状态已变化，请重新核对 |

其余复用VALIDATION_ERROR、WEEKLY_INVALID、WEEKLY_PREVIEW_STALE／EXPIRED、WEEKLY_ACK_REQUIRED、WEEKLY_OPERATION_CONFLICT／NOT_FOUND及既有DB错误。统一{error:{code,message,details?}}，中文message及details不得泄露路径、token、SQL或密钥。不存在／不属的传输记录用NotFound；服务／work不可用用Unavailable；绑定、命名、attempt状态或唯一后继冲突用Conflict。纯metadata只读不得因manager closed被误报不存在。

A4实际helper名保持：
```text
issue_token(runtime, *, purpose,profile_id,launch_id,session_scope_hash,object_id,
            expected_version=None,source_context_hash=None,facts_hash=None,target_hash=None,ttl=600) -> str
verify_token(runtime, token, *, purpose,profile_id,launch_id,session_scope_hash,
             object_id=None,expected_version=None,source_context_hash=None,facts_hash=None,target_hash=None) -> dict
derive_export_id(runtime, *, profile_id,snapshot_id,token_id,request_id,launch_id,session_scope_hash) -> str
fingerprint(action, payload) -> str
find_receipt(session, *, profile_id,request_id,action=None,fingerprint=None) -> operation|None
store_receipt(session, *, profile_id,request_id,action,fingerprint,result,**result_fields) -> operation
```

purpose只有create/refresh/confirm/export，导出preview使用export而非export_preview；opaque export_id另用derive。store_receipt的result必需且仅为§11.6八键metadata，add/flush但不commit；结果列仍为result_draft_*、result_confirmed_*、result_snapshot_id/result_token_id。HMAC私钥归runtime；header不是key，scope/token/export_id的hash沿原helper域前缀。D不复制观察通道旧算法，不造replay/record/mint_context接口别名。

#### 11.8.7 来源登记与验证边界

用户本轮确认沿本机现有CPython 3.14.10（Windows x64、标准GIL），不执行解释器升级或依赖变更。A在G2a新增下列精确记录责任：
```text
backend/.python-version: 3.14.10
desktop/.python-version: 3.14.10
desktop/verify_e14_package.py: PYTHON_VERSION = "3.14.10"
```
将现行版本声明及verify_e14_package.PYTHON_VERSION从3.14.7更新为3.14.10，核对并最小更新相应当前fixture；新增测试写入路径仍先核唯一责任。不改依赖／锁文件、venv配置或解释器安装，不改固定r03受测身份、旧结果和旧0006纯协议fixtures，不全局替换历史3.14.7。实际解释器事实与旧venv配置文字分开记录，不把此次记录更新写成由本轮执行了升级。

A可在desktop/build_e14.py、verify_e14_package.py、verify_e14_portable_archive.py更新真实来源登记：
revision=20261101_0007_local_weekly；实际迁移filename为20261101_0007_local_weekly_plans.py，保留0001–0006全链及既有模板／资源，不能按短revision拼错filename或全局替换旧协议fixture。
required modules纳入app.local.appearance_service、weekly_plan_api/service/sources/content/tokens/operations/snapshot及weekly_plan_export_service/api的实际模块；SOURCE_GROUPS已递归覆盖的文件不机械新增hidden import，不升级依赖或锁。另授A仅最小更新desktop/update_identity.py的PYTHON_VERSION为3.14.10，使source identity与当前基线一致；不更改APP_VERSION、版本比较、默认仓库、旧发布或其它身份规则。

额外新增A责任白名单是三个既有desktop测试：
```text
desktop/tests/test_e14_build_guard.py
desktop/tests/test_update_u2.py
desktop/tests/test_windows11_portable_static.py
```
仅最小更新真实受当前head／来源登记影响的断言；test_update_github.py旧0006纯协议fixture保持。既有test_maintenance_host.py／test_maintenance_lifecycle.py仅受影响整合修改，不擅加其它测试文件或改B/C/D断言。

登记不授权candidate build、freeze归档、PyInstaller、整包校验执行或受阻EXE/helper。G2a专项须覆盖原回执v2/headv3、严格DTO、manager暂停／发布竞态、同Runtime双app的idle handover及活动拒绝、旧finally不影响新manager、weekly等待失败前置保原资源、流式引用释放与未知work保留；通过不等于页面／原生／Word或教师体验通过。G2b再独立核真实窗口、两个host方法、原生取消／保存／占用重试及本轮新Word。各片停写由Codex复核；最终Git仍待准确files/blob/parent/tree门禁。

### 11.9 G2b A/C 共享视图合同

本节固定A直接消费的两个C-owned SFC边界。C core已独立通过，当前放行C界面片；A/D后端返修及D host仍分别核查，不以C可开工冒称G2整体通过。History/Export由C在编辑器内部管理，A不另挂其路由。

#### 11.9.1 精确 SFC 接口

| SFC | props及默认值 | emits | defineExpose |
| --- | --- | --- | --- |
| WeeklyPlansView.vue | disabled?: boolean = false | open(planId: string)；busy(value: boolean) | 无 A 必需方法 |
| WeeklyPlanEditorView.vue | planId: string（必需）；disabled?: boolean = false；profileEpoch?: number = 0；host?: HostApi \| null = null | register-editor(bridge: LeaveEditor \| null)；busy(payload: {identity: string; busy: boolean})；back() | resetForContext(): void |

列表 busy(boolean) 是相对最初候选的唯一必要补充：列表完成真实创建后才发 open(planId)，create 在途和 unknown 也必须进入页面屏障。列表自己用 alive/epoch 拒绝卸载后的迟到 emit；A 再只接收当前列表实例的事件。不得用 open 表示未创建的虚拟 ID，不额外发 create/term/anchor 导航协议。

C 实际提供的 LeaveEditor 必须实现 isDirty、identity、settle、saveCurrent、blockingDraft；复用 leave.ts 的类型与 SaveOutcome，不另造一套 EditorBridge。A 当前 App 本地 EditorBridge 把 settle 写成必填，而 leave.ts 类型为可选；A 接线时统一接收 LeaveEditor，并沿已有可选调用形状处理，不能让 C 用 any/类型断言掩盖差异。

#### 11.9.2 A 最小接线与 busy/epoch

- open(planId) 进入既有统一 leave 协调器，具体目标 key 包含 planId；不同周不能合并。back() 同样经 leave/Q2 返回周列表，不直接改 view 绕过保存或 blockingDraft。不新增教师选择步骤。
- C identity 为稳定 planId:editor_epoch；普通保存/刷新不含 draft version、不改 identity。重新载入、切计划、restore/profile-replace/retire 换不复用 epoch。profileEpoch 是 A 传入的响应式生命周期数值；普通 context reload 不递增，同 profile restore 也递增。当前 App 的普通 let 不能成为唯一 props 更新通知源，A 在自有接线处提供响应式值即可，不重写主题控制器。
- resetForContext() 同步失效旧 epoch、请求/预览/未知提交绑定，不自动保存、确认或导出；退役时不向旧运行时重发读取。正常装载/新的有效 profileEpoch 驱动重读。A 对同一次切换只安排一次重载，不把 prop 更新和显式 reset 叠成两次加载；新窗口恢复按新 JS realm/epoch处理。
- 编辑器先 register-editor 当前 bridge，再发带该 bridge.identity() 的 busy。A 仅在当前周编辑器且 payload.identity === 当前 bridge.identity() 时更新 busy，丢弃旧身份 true/false；卸载注销也绑定原实例，迟到 null 不清掉新 bridge。
- editor busy 包含 save/refresh/confirm/export/unknown；只读loading另作界面状态，不单独冒充写入屏障；clean 也由 blockingDraft 返回 weekly 阻塞。列表 busy 与编辑器 busy 都纳入 A 的 pageBusy、关闭、维护、导航最终复核。
- disabled 只表示 A 的全局维护/关闭冻结/恢复/退役等外部限制。A 不把列表或编辑器自身 busy 回灌为 disabled，C 不因一次提交禁掉在途新输入；原提交投影与较晚输入按既有基线规则区分。
- A 独占宿主页面 busy 同步，复用现有 set_page_busy({busy, seq, page_ticket}) 及已有 accepted/seq 重试逻辑。没有 set_editor_busy 新宿主协议，C 不自行发送 page_ticket 或并行维护另一条 busy 通道。既有观察 boolean busy 接线保持，周编辑器另用 identity-tagged handler。
- 列表 create unknown 与编辑器 save/confirm unknown 都沿工程11.8.2：查原 request 回执，404不证明失败；由用户明确再次提交原 request_id/原 payload/原 expected version；不自动重发、不混入较晚输入、不自动续 Q3。

#### 11.9.3 HostApi 与内部面板

A 在 bridge.ts 声明、D 在 d1_host_api.py 实现两个周方法；C 只通过传入的同代 host 调用，不抓取后来全局 host 替换：

- save_weekly_export?: (payload: {export_id: string; filename: string}) => Promise<SaveWeeklyExportResult>
- get_weekly_export_result?: (payload: {export_id: string; filename: string}) => Promise<SaveWeeklyExportResult>

SaveWeeklyExportResult 使用明确类型：status 为 saved/canceled/failed/pending/unknown；code/message/filename/export_id/attempt_id 为可选 string，bytes 为可选 number，receipt_pending 为可选 boolean。由 A/D 按已定周 host 合同一致声明/实现，不使用 any、观察的宽松 status:string 或假成功。filename 为合法单层 basename，query 不下载、开框或重写。没有另一个 reconcile 周宿主方法。

host 为 null 或方法缺失时，C 保留正常查看/编辑/确认，仅明确显示原生交付尚未就绪，不制造 saved/unknown 假回执或静默吞依赖。生产代码不能用测试 mock 当宿主。History/Export 接受 C 内部精确 DTO/host，由 C 管理；旧确认分支零 save、不清 dirty，当前分支每次 await 核身份/输入修订/sequence。

页面显示面向教师的表头、日历、正文、来源全文、缺项/变化及可恢复状态，不 JSON dump、不增加 AI/材料入口，不为了开发接线新增教师流程。

#### 11.9.4 分阶段责任

1. C2 core 独立通过后，冻结 DTO/LeaveEditor/unknown/manual/Q3 行为，C 即可写自有两个入口 SFC及 History/Export 内部组件，不等待 D 内部修复结束。
2. C G2b 如需在自己拥有的 weekly.ts、weekly-editor.ts、d1.weekly-core.test.mjs 增加 refresh 等内部支持，须父明确赋予本片范围；只能增量兼容现有公开接口，保留原 unknown/manual/Q3 测试和独立 probe，不能改断言绕过。
3. A 只写共享 App/leave/bridge/types 等自有接线，不代写 C SFC/core；C 不接管 A 文件。D host 必须等 D backend 独立通过后另行放行，A 的类型声明不代表 D host 已可执行。
4. 实际源码窗口/native保存/Word的 G3 仍等 A/C/D 全部停写及整合冻结，不以 C UI 可开工或前端编译通过冒称全链路通过。

C本界面片另明确拥有新frontend/src/d1/d1.weekly-ui.test.mjs，并可在原weekly.ts／weekly-editor.ts／d1.weekly-core.test.mjs中做refresh等界面所需的兼容增量；既有DTO和LeaveEditor公开接口不破坏，原unknown／manual／Q3测试及独立探针保留复验。A不代写这些文件。

A共享接线的行为专项另授新frontend/src/d1/d1.shell-weekly.test.mjs，仅核实际App的busy身份过滤及必要周入口接线，A将其接入package.json既有test:d1；不接管C的d1.weekly*.test.mjs。只有匹配当前已注册bridge identity的busy事件才可更新当前周屏障；不存在bridge时，迟到的任意identity不能创建永久busy。

C页面r05另仅在weekly-editor.ts及其core测试收口完整保存flight、unknown早退与旧finally归属；原十一色值视图仅规范末尾换行与空行，最后正文字符及之前原字节不变，不改颜色或业务。两类变更分别交raw身份与验证，不接管A文件。

页面只调用导出preview/create/operations/retry及只读attempt查询；start/result、实际下载、原生对话框、原子writer和终态补记由固定同代host独占。页面不预先start导致host失去should_prompt，也不编造saved的hash或把补记失败当成功。请求未明时保留原request_id与原载荷，查询入口不依赖已收到operation；显式原请求重提和failed/cancelled后的新后继retry分别命名，均不自动重开保存框。unknown/pending在核对清楚前保持写屏障。

G2导出源审补核发现共享weekly_plan_operations.validate_metadata仍以Python等值比较schema_version；A仅在该自有helper补严格整数1并在自有test_weekly_plan_service.py增加反例，不改其它G1冻结模块／迁移。D新事务／投影继续消费统一helper；在A停写且Codex独立元数据反例通过后，D才冻结共同依赖执行最终验证，不以此前已绿的旧helper身份代新身份。download也必须持完整file_scope；artifact释放绑定取得时的entry而非可被删alias重新查找；response自身调用finally覆盖尚未迭代即失败。work可消费既有backup_fs.DirectoryGuard/FileLease，不改A文件或清未知根；D须在自有service落实按身份的句柄读／删除及host临时文件的已验证读取句柄交接。

范围导出可由C编辑页提供独立“按日期范围导出已确认周”入口，内部复用ExportDialog并显示范围内固定确认，不保存本页dirty稿，不新增A路由/props。外部disabled与固定host在C内部继续传递。当前稿导出仍须Q3保存→完整目标预览→教师明确确认→固定导出；旧确认/范围已确认分支不触发保存。日期或编辑revision变化使相应旧预览失效，未知原请求作为独立固定对象保留。

宿主开框前的TTL核查消费上述固定loopback下载响应的X-Export-Expires-At，来源为服务已在同一read_scope核实并物化的min(token.expires_at,snapshot.expires_at)，不读取页面日期或按started_at推算。host须校验该UTC格式；完整下载后取得共享_save_mutex，再在调用SaveDialog前立即核到期与生命周期，排队跨TTL不得新开框。只有有效期内已完整下载并已打开的原对话框允许返回后完成，仍须publish与retire／维护复核；不延长token，不授新下载、另开对话框或重写权。D的host片可在其自有service/API中仅补该期限物化与header及相应原backend专项，其他已冻结核心不重构，A不接管D文件。

### 11.10 G2b宿主消费的已冻结临时文件接口

backend工程门槛通过后，D宿主片只消费固定manager.create_owned_temp(owner=...,suffix=".docx")返回的OwnedTemp（handle/path/token/owner）。须处于该manager的native activity；finish()刷新／同步并关闭writer，交接同一已核身份的OwnedTempRead，其read(size=-1)、seek(offset,whence)、tell()、fileno()、seekable()与close()均围绕同一FileLease描述符。path只作内部诊断，不重新按路径打开以替代已验证句柄。host finally先释放借出的reader，再abort自己的临时资源。

close／idle将writer、交接、reader和真实引用计入寿命；close只退役并禁止新增，借出reader由持有人最后释放。flush／fsync或close失败不能先丢登记再声称idle；持续close失败保留真实owner／根guard并明确失败，故障解除后owner.abort可实际收口且幂等。元数据本身不算活跃IO，未知／替换文件不接管。根guard在最后真实活动／句柄与已知清理完成后释放。host实现不接管这些backend或A共享文件；A的两个host构造明确传本次app.state.weekly_export_manager。

### 11.11 冻结目标的来源日期显示

确认、历史及导出预览显示完整冻结正文、五项表头、中文年级／日状态／来源／区域类型及来源日期与版本；范围逐份显示preview.items原有内容，不以当前稿补造。source ref与snapshot／manifest schema不增加显示字段；先从同一冻结content.deterministic按确切daily_plan_id取得唯一日期。缺日期时仅用既有GET /api/daily-plans/{id}读取日期，核返回id、class_id、creator_id与目标归属及有效ISO日期，忽略当前正文、版本、名称与日历；不能机械要求日来源term等于周term。

该GET仍验证当前日内容，并非独立metadata接口；缺失／软删／非当前班可能404，未初始化409，当前损坏可能503。失败显示来源日期不可用或暂不可核对，不猜日期、不更改冻结正文、不阻断合法旧确认导出，也不新增确认步骤。读取去重且只在当前组件／目标／档案代内有效，切换或关闭使迟到结果失效；只读loading不产生写屏障、不保存、不确认或调用host，不清未知提交票据。界面空材料／区域用教师中文，不展示实现null字样。

### 11.12 实际线格式与页面入口核定

写请求的request_id沿既有normalize_request_id使用UUID；前端默认由crypto.randomUUID生成，创建票据时只生成一次，查询／明确重提复用原票据，不因重试换标识。刷新预览的target_draft_version是将新增的下一稿；提交expected_draft_version绑定预览对应的当前已存稿，二者不能混用。普通“确认”只预览已保存稿，未保存时明确提示先保存；Q3当前稿导出仍先走既有保存成功／版本及输入复核，再展示明确确认目标，不自动确认。

source_candidates直接消费B的20键平铺投影，不另假设slot/source外壳。morning_games的collective候选用于两个集体槽，free_choice用于自选槽，post_group_games的focus候选只用于重点区域；按具体日／稿／组／游戏身份带入整组正文。界面投影必须去掉候选专用字段，日来源PATCH严格为source_kind、daily_plan_id、content_id、content_version、content_hash、section、group_id、game_id八键。

手工游戏PATCH严格包含source_kind、manual_item_id、client_key、name、shared_objectives、guidance_points、focus_guidance七键。新项明确manual_item_id:null及非空client_key；已有项明确原manual_item_id及client_key:null，不能用undefined省略必需null键。server分配身份后保持原ID，不重造手工项。JSON序列化后的真实正文须验证此合同，不能仅据类型或模拟API断言。刷新preserved统计暂不可用的旧来源，不称为手工输入数量。对应实际首失败和修复范围见实施核查。
