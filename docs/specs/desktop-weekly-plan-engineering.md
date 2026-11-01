# 桌面周计划工程设计与实施合同

更新：2026-11-01。状态：产品 [Q1–Q6 全部确认](desktop-weekly-plan.md)，本文件给出首片数据／接口／页面／导出／备份合同和实施分工，已完成本轮定向设计复核。**当前为设计与提示词交付，未启动实现，未运行迁移或新构建。** 既有 r03 目标测试继续独立进行，尚无实际回执。唯一派发入口 [current.md](../tasks/current.md)；本文件不建立另一份提示词。

## 1. 基线、范围与准入

沿 `codex/desktop-v2-foundation`，当前源码 HEAD `2a4694893a083e32ba6203bfee6dbd83f890f02e`；已有未提交规划／规格文档须保留整合。实际迁移 head 为 `20261025_0006_local_game_observations`。开工先核对 head、文件变化及在途会话，有差异按实际重新核定，不能 reset 或沿旧指纹自报同源。

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

全部原生实施者固定 DeepSeek V4.1 Flash max，不 fork／另派子代理；你不是唯一写入者，不还原他方修改。下表是**后续派发合同，当前会话只准备文档**。无归属文件先交 Codex 划定，不自己扩范围。

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

后续执行检查沿用现有 Windows原生环境，不装新依赖；短 TEMP 只配置给独立验证进程，不改系统。先专项再受影响全回归，代码不变不机械重跑。真实AI、目标机器、Word逐页、静态、源码窗口分开结论；未得到用户目标回执不填通过。本轮没有运行上述新测试，只核设计与文档一致性。

## 10. 设计依据与审阅边界

使用 codebase-memory Verify，父代次 `2026-11-01T01:16:17Z`，11相关证据路径均 metadata_changed，local仅已知 `__pycache__` 排除，d1无已记录缺口；已作定向回读。两个 Codex 只读分析分别核数据／备份与页面／原生导出，未改文件、未充当实现者。额外 d1_digest、migrations_local/env.py 等按源码补查，不据此声称全依赖闭包。

关键依据为 LocalClass／LocalConfigOperation、config_service.preview/apply、migrate.head_revision、backup_validate源schema顺序；EditorBridge/leave/App关闭、观察原生原子stream及拒绝机制；既有周 mapper日期重算。复用以本文件明确边界为准，不把旧测试数字作为新模块通过。若开工发现不满足合同或需要系统级边界改变，先停相关实现、交明确影响／ADR草案。

本轮复核修正：stable identity移除可变draft version；确认日历来自保存稿；导出同profile复合关系与receipt结果成对CHECK；create/retry持久回执及同launch可重放token、跨launch失效；retry旧attempt唯一后继。导出HMAC使用规范编码和独立用途，不用JS可见的launch_token/page_ticket作私钥；明文token不进通用result_json／日志。retry完整核对旧token/attempt/profile/snapshot/scope，不同request抢同parent返回409。跨launch或过期只返 `transfer_expired` 元数据，不续期、不重生成；`generated` 与原生 `saved` 独立。以上为设计修正，不是运行测试结果。
