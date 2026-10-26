# 游戏观察记录 Contract

状态：Architecture v2有效业务Contract；E13设计扩展于2026-10-26经Codex独立核定。同日用户另行授权的E01／E02／E04模型、迁移与归属切片已由原OpenCode会话实施，独立结果见[E01／E02／E04独立核查](../bootstrap/desktop-game-observation-foundation-review.md)。其余服务／页面／材料／AI／Word仍为设计，未取得后续实施或产品验收结论。

产品依据为[游戏观察C1–C33](../specs/desktop-game-observation.md)，工程依据为[E01–E14](../specs/desktop-game-observation-engineering.md)。本文同时记录已实施数据基础与尚待实施的完整Contract；各项实际范围以独立核查报告为准，日计划原Contract及既有验收身份保持。

原OpenCode会话已提交草案并按独立意见修订，最终V01–V08及必要澄清已归并；过程、证据及未验范围见[E13核定记录](../bootstrap/desktop-game-observation-contract-review.md)。旧轮次相反表述不作为另一套协议。

## 1. 职责、权威与依赖

### 1.1 职责

本模块拥有：观察记录稳定身份、本份资料、当前草稿及有序照片关联；不可变历史版本、历史照片引用、恢复回执；受管原图／AI 工作图／导出派生图的业务归属；观察 AI 输入投影、候选业务意义、采用决定及采用账本；创建／保存／导入／采用／恢复／导出的操作回执；导出快照、受限 `export_id` 及 manifest。

### 1.2 数据权威

- 当前内容唯一权威：`draft.payload` ＋ `draft_photos` 有序关联。
- `record` 的日期、姓名、类型、学期等字段只是列表／检索投影；投影与草稿不一致时明确存储错误，不用投影覆盖草稿。
- 历史版本不可变；恢复生成新版本，不覆写旧版本。
- 原图、工作图、导出图均为受管文件；外部原路径、浏览器存储、Word 文件不是业务权威。
- 导出 DOCX 是时点副本；后续修改或恢复须重新导出。

### 1.3 依赖方向

```text
Vue → 本机 FastAPI（观察 API）→ 观察服务 → SQLite／受管文件
观察 → 身份与班级：读取当前档案／班级／学期及服务端快照
观察 → 提示词：读取固定字段契约及内部版本
观察 → AI Service：提交冻结业务输入，接收校验候选与状态
AI Service → 提示词：读取契约与版本
Word 导出 → 观察：读取固定导出快照
审计 ← 观察／AI／Word：接收非敏感元信息
```

依赖不可反向：身份、提示词、AI、Word、审计不得直接改写观察草稿、历史、采用决定或材料归属。

### 1.4 非职责

不拥有：教师档案／班级／学期配置；AI 地址、模型、密钥、网络、失败分类；提示词字段结构与默认模板最终定义；Word 模板编辑；跨设备同步、备份、删除／回收站；AI 预算或 AI 选图子集 UI；真实 AI 调用授权。

## 2. Canonical payload 与校验

E01纯校验与hash函数已实施。canonical原图manifest按业务顺序排列，sort_order必须为0至N−1并等于数组下标；后续材料／保存服务须从数据库关联次序生成此规范形式，不新增教师操作。当前数据库仅要求非负、唯一次序；E03映射及完整业务保存未实施。

| 字段 | 类型／可空 | 语义 |
| --- | --- | --- |
| `record_type` | 非空枚举 | `public/indoor/outdoor` |
| `observation_date` | 可空 ISO 日期 | 任意有效日期，不受上课日限制 |
| `start_time`、`end_time` | 可空 `HH:mm` | 结束早于开始只提示复核 |
| `term_id` | 可空 | 已有学期归属；不自动新建学期 |
| `term_snapshot` | 服务端只读 | 学期名称／起止快照；客户端不可伪造 |
| `school_name`、`class_name`、`observer_name` | 可空文字 | 本份文字；仅新建时带入当前档案 |
| `adult_count`、`child_count` | 可空非负整数 | 儿童数为总参与人数，不从照片或目标数推算 |
| `age_years` | 可空非负整数 | 本份统一年龄；不加年龄上限，不逐人异龄 |
| `subjects` | 有序数组 | `[{name:string}]`；去空项，保留顺序，不擅自合并同名 |
| `environment` | 可空文字 | 观察环境 |
| `observation_goal` | 可空文字 | 观察目标 |
| `observation_process` | 可空文字 | 观察记录 |
| `support_strategy` | 可空文字 | 支持策略 |
| `analysis_evaluation` | 固定五键 | `health/language/social/science/arts`，值可空文字 |

照片不进入 payload；以有序 manifest 参与聚合 hash。

规范化：统一换行、处理首尾空白；不截断、不改写、不自动补写。五领域空骨架不是实际正文；“证据不足”是有效正文。非法日期／时间、负数／非整数、未知类型／资产、跨记录材料拒绝并解释。总人数少于重点人数、结束早于开始等只提示复核，不硬阻断保存。草稿可缺项；AI 最少姓名、统一年龄、环境及一张有效照片；无图仍可手写、保存、导出。

新建仅带入当前园所、班级、观察者和今天日期，不猜年龄、人数、时段或环境。新建按日期唯一匹配已有学期，无匹配或无日期先未归属，多匹配明确选择；无日期也可显式选择已有学期。已有稿清空日期默认保留既有归属；跨学期更正明确确认，可保留当前、选择已有学期或未归属，取消不丢UI输入。旧学期按存储归属查询，不随班级改名、升班或范围调整改写／隐藏。

## 3. 对象所有权、来源链与迁移

### 3.1 观察对象与稳定关联

| 对象 | 存储／所有者 | 权威与生命周期 | 稳定关联／约束 |
| --- | --- | --- | --- |
| 记录 `record` | `local_observation_records`／观察 | 身份与投影；ID 不变 | `id` PK；`creator_profile_id` FK；`UNIQUE(creator_profile_id,id)`；`current_draft_revision`；可空 `current_version`（历史序号）；无日期／姓名／类型唯一键 |
| 草稿 `draft` | `local_observation_drafts`／观察 | 当前内容权威；可反复保存 | `observation_id` PK/FK；`revision>=1`；`payload_json`、聚合 `payload_hash` |
| 历史版本 `version` | `local_observation_versions`／观察 | 不可变；保留节点追加 | `id` PK；`observation_id`；`version>=1`；`UNIQUE(observation_id,version)`、`UNIQUE(observation_id,id)` |
| 原图资产 `asset` | `local_observation_assets`／观察 | 不可变受管副本；不存外部路径 | `id` PK；`observation_id`；相对路径、真实 MIME、原字节 SHA256／大小／尺寸／方向；`UNIQUE(observation_id,id)` |
| 派生图 `derivative` | `local_observation_asset_derivatives`／观察 | AI／导出工作副本；追加不覆盖 | record／asset、用途、参数版本、hash、尺寸／MIME、受管路径；`UNIQUE(observation_id,id)`、`UNIQUE(observation_id,asset_id,id)` |
| 当前照片 `draft_photo` | `local_observation_draft_photos`／观察 | 当前顺序／说明；移除只解除当前关联 | `(observation_id,asset_id)` PK；`UNIQUE(observation_id,sort_order)`；同记录 FK 到 assets |
| 历史照片 `version_photo` | `local_observation_version_photos`／观察 | 历史引用；首期不自动清理 | `(version_id,asset_id)` PK；`UNIQUE(version_id,sort_order)`；同记录 FK 到 versions／assets |
| AI 输入 `input` | `local_ai_inputs`／AI 持久化，观察定义投影 | 成功保存 draft 后冻结；不可变 | 仅 FK 稳定 record；自身冻结 payload／来源／照片 manifest；`source_revision` 仅元信息 |
| 输入照片 `input_photo` | `local_observation_ai_input_photos`／观察 | 固定 input 的资产／派生／顺序／说明／hash | 同 record 复合 FK 连 input、asset、derivative；`UNIQUE(input_id,sort_order)` |
| 候选 `candidate` | `local_ai_candidates`／AI 持久化，观察拥有业务意义 | 校验后持久化；不自动采用 | profile／kind／source／input／execution 同源链 |
| 采用账本 `provenance` | `local_observation_ai_provenance`／观察 | 证明某候选某栏已采用 | 同 record／profile／kind 连 version 与 candidate；targets、input／output hash |
| 操作回执 `operation` | `local_observation_operations`／观察 | 业务幂等主回执 | `id` PK；`UNIQUE(profile_id,request_id)`；operation kind、record、fingerprint、status、result |
| 恢复细节 | `local_observation_restores`／观察 | 主回执在 operations，细节不另成幂等权威 | `operation_id` 唯一FK；record、source/result version、before draft、effective hash／归属决定；source/result分别同record复合FK到versions |
| 恢复预览 | `local_observation_restore_previews`／观察 | 一次性预览绑定；创建预览不等于业务提交 | token摘要、profile/record、source/base/effective/材料hash、request、期限／消费；不要求未提交预览已有成功operation |
| 导出快照／token | `local_observation_export_snapshots`、`export_tokens`／观察 | 固定快照；token 只引用快照 | `snapshot_id` 非 bearer；`export_id` bearer；期限／消费 |

记录计数指针：`draft.revision`与`versions.version`分离；`record.current_draft_revision`与单行draft的revision同事务一致，`record.(id,current_version)`以deferred复合FK指向`versions.(observation_id,version)`；尚无保留节点时current_version可空。照片数量由关联表计数，不另设可独立漂移的计数权威。

### 3.2 共用 AI 四表：非空同源复合链

四表统一非空`profile_id/source_kind/source_id`及各级input/task/type锚点，`source_kind='daily_plan'|'game_observation'`，`observation_id`可空。观察任务固定 `game_observation_generate`、`game_observation_rewrite`；旧三个日计划任务名保持。`inputs`／`candidates` 新增非空 `profile_id` 及 FK；`tasks`／`executions` 保留既有 `profile_id`及FK。

**可空分支**：

- `inputs`：旧 `daily_plan_id/content_id/content_version/target_grade` 改为可空；仅观察分支为空。观察分支额外 `observation_id`、`source_revision` 非空。
- `tasks/executions/candidates`：仅各自既有 `daily_plan_id` 改为可空；不新增 content/version/grade 列。
- 所有分支 CHECK 显式写 `IS NOT NULL`／`IS NULL`，不得依赖 SQLite NULL 比较通过。

**分支 CHECK（四表同构）**：

```text
daily:
  source_kind='daily_plan'
  AND source_id=daily_plan_id
  AND daily_plan_id IS NOT NULL
  AND observation_id IS NULL
  AND task_type IN ('daily_lesson_split','daily_process_adapt','daily_other_activities')

game_observation:
  source_kind='game_observation'
  AND source_id=observation_id
  AND daily_plan_id IS NULL
  AND observation_id IS NOT NULL
  AND task_type IN ('game_observation_generate','game_observation_rewrite')
```

`inputs` 的 daily 分支另须 `content_id IS NOT NULL AND content_version IS NOT NULL AND target_grade IS NOT NULL AND target_grade IN ('small','middle','large')`；observation 分支三者全为 NULL。

**完整父 UNIQUE 与同序子 FK**：

| 父表 UNIQUE（列顺序固定） | 子表同序复合 FK |
| --- | --- |
| inputs `(profile_id,source_kind,source_id,id,task_type)` | tasks `(profile_id,source_kind,source_id,input_id,task_type)` |
| inputs `(profile_id,source_kind,source_id,id)` | input_photos `(profile_id,source_kind,source_id,input_id)` |
| tasks `(profile_id,source_kind,source_id,id,input_id,task_type)` | executions `(profile_id,source_kind,source_id,task_id,input_id,task_type)` |
| executions `(profile_id,source_kind,source_id,id,task_id,input_id,task_type)` | candidates `(profile_id,source_kind,source_id,execution_id,task_id,input_id,task_type)` |
| candidates `(profile_id,source_kind,source_id,id)` | observation provenance 同记录／profile／kind 的 candidate 引用 |

**必须保留的旧 daily 链／父键**：

- inputs `(daily_plan_id,content_id,content_version)` → `local_daily_plan_contents(daily_plan_id,id,version)`。
- tasks 旧 `(daily_plan_id,input_id,task_type)` → inputs 旧 `UNIQUE(daily_plan_id,id,task_type)`。
- executions 旧 `(daily_plan_id,task_id,input_id,task_type)` → tasks 旧 `UNIQUE(daily_plan_id,id,input_id,task_type)`。
- candidates旧FK为`(execution_id,task_id,daily_plan_id,input_id,task_type)`→executions的`(id,task_id,daily_plan_id,input_id,task_type)`；保留源码实际父`UNIQUE(daily_plan_id,task_id,input_id,task_type,id)`，不把父唯一键声明顺序冒充FK引用列顺序。
- execution `UNIQUE(task_id,id)`，供 tasks `(id,current_execution_id)` deferred FK。
- execution `UNIQUE(task_id,generation)`；candidate `UNIQUE(execution_id)`。
- candidate `UNIQUE(daily_plan_id,id)`，供旧 `local_daily_plan_ai_provenance`。
- execution 的 config、personal prompt、default bundle 复合 FK 全部保留；tasks／executions 的 profile FK 保留。

**观察输入来源**：

- inputs 以 `(profile_id,observation_id)` → records `(creator_profile_id,id)`；`source_id=observation_id`。
- `source_revision` 是成功保存 draft 的 revision 元信息，**不 FK** `versions.revision`；input 自身冻结业务 payload、资料、照片 manifest、实际发送四栏及依赖。
- 不因自动保存强制创建历史节点。

**同记录材料／派生引用**：

各观察材料关联行中实际存在的record、asset、version/input、derivative锚点、sort_order及引用hash均非空；FK不能因任一可空锚点被跳过。四AI表的daily/observation分支可空规则仍按上文分别约束。

- `draft_photos`：`(observation_id,asset_id)` → assets `(observation_id,id)`；`UNIQUE(observation_id,sort_order)`。
- `version_photos`：`(observation_id,version_id)` → versions `(observation_id,id)`；`(observation_id,asset_id)` → assets；`UNIQUE(version_id,sort_order)`。
- `asset_derivatives`：`(observation_id,asset_id)`→assets；`UNIQUE(observation_id,id)`及`UNIQUE(observation_id,asset_id,id)`；用途＋参数版本可追加，不覆盖旧派生。
- `ai_input_photos`：非空`(profile_id,source_kind,source_id,input_id)`→inputs；`(observation_id,asset_id)`→assets；`(observation_id,asset_id,derivative_id)`同序FK→derivatives的`(observation_id,asset_id,id)`，防同记录内错配原图与派生；显式`CHECK(source_kind='game_observation' AND observation_id IS NOT NULL AND source_id=observation_id)`；`UNIQUE(input_id,sort_order)`。服务另核原图／派生hash及用途。
- 恢复细节的`(observation_id,source_version)`与`(observation_id,result_version)`分别FK→versions的`(observation_id,version)`；采用账本同record连接历史及带profile/kind/source的candidate，不用短链省略来源。

### 3.3 迁移与种子

- 单一 `0006` DDL 修订：创建观察核心及关联，重建受影响 AI 四表和 `local_prompt_bundles` 任务枚举；允许五种任务。**不设 0007 种子修订**。
- 只做 DDL／新列回填；旧列、旧行、旧列顺序保留；不插入观察 prompt 行。
- 预检旧来源链：input 能找到日计划创建者；task→input、execution→task/input、candidate→execution 完整且 profile 一致；缺失／不一致失败回滚，不猜关联。
- 回填：`source_kind=daily_plan`、`source_id=daily_plan_id`、input profile 取计划创建者、candidate profile 取 execution；观察列为空。
- 精确顺序：预检 → 观察基础表 → inputs → tasks → executions → candidates → prompt bundles → 观察采用等剩余关联。每表“建最终结构 `_new` → `INSERT SELECT` 旧列原值＋回填 → drop 旧 → rename `_new` 回原名 → 恢复索引”；不得先 rename 旧父表。
- 沿 `env.py`：事务前 FK OFF、`BEGIN IMMEDIATE`、迁移及 guard、`foreign_key_check`、COMMIT、恢复 FK；revision 不内部提交、不切 PRAGMA、不关闭摘要保护。
- **两个 personal prompt 表没有 task_type CHECK，不重建**；只保留其 bundle FK 与 revision／action 约束。
- 迁移不向已有 prompt 表插观察种子。只有迁移 `guard.after_migrations` 与 runtime 提交后 `_verify_committed_upgrade` **两次 guard 都成功**，才在启动同步注册观察 bundle／heads：
  1. 无 profile：只注册 bundle；首次建档用 `effective_prompt_seed` 动态初始化。
  2. 已有 profile：幂等补齐观察 head／初版 personal version，只增观察，不改日计划指导。
  3. 种子后全表摘要可因合法新增行变化；验旧 daily 行子集原值不变，以及第二次启动相对第一次成功 seed 状态不再增行。
- 不关闭、不泛化放宽 `d1_digest`；不修改旧迁移或 MySQL 链。

## 4. 接口、幂等与回执

### 4.1 请求／返回关键字段

| 操作 | 请求关键字段 | 返回关键字段 |
| --- | --- | --- |
| 创建 | `request_id`、`record_type`、可选初始资料 | `observation_id`、`current_draft_revision`、`payload_hash` |
| 列表／详情 | 日期范围、term／未归属、类型、姓名、分页 | 列表投影／详情权威draft、opaque ID、排序键 |
| 保存 | `request_id`、`observation_id`、`expected_revision`、payload、照片 ids／顺序／说明、`save_reason` | 新 revision、payload_hash、changed、saved_at |
| 保留历史（保存内部步骤） | 同保存请求，不另开放绕过保存的写入口 | changed、current_version、draft revision、hash |
| 历史预览 | `observation_id`、`version` | 完整 payload、照片 manifest、term_snapshot、hash |
| 恢复预览 | `source_version`、`base_draft_revision/hash`、`term_decision`、`request_id` | `restore_token`、effective hash、材料 hash、warnings、期限 |
| 恢复提交 | `request_id`、`restore_token`、base revision/hash、term_decision、selected term | changed／unchanged、result_version、draft revision、hash |
| 图片导入／排序／移除 | multipart、`request_id`、`expected_revision`、顺序／说明 | asset_id、hash、尺寸、新 revision／hash |
| AI 生成／重写 | `request_id`、observation_id、base revision/hash、task_type、target | task_id／candidate_id、状态 |
| 候选预览 | candidate_id、targets、当前draft revision/hash | `adoption_token`、依赖／目标hash、source_state、差异摘要、允许的复核决定、期限 |
| 候选采用 | `request_id`、`adoption_token`、targets、review_decision | changed、draft revision、version、provenance |
| 导出预览 | 有序observation选集、`request_id` | `snapshot_id`、manifest hash、完整缺项事实、确认上下文、期限 |
| 导出创建 | `request_id`、snapshot_id、确认上下文 | `export_id`、状态、期限 |
| 宿主保存 | `export_id`、filename | `saved/cancelled/failed/indeterminate` |
| 业务／AI回执查询 | 对应命名域的request_id及本机会话 | 原状态、changed/unchanged、结果revision/history/hash、request_id |
| 宿主结果查询 | 受限`get_observation_export_save_result(export_id)`或等价桥 | 原结果或in_progress/indeterminate，不打开对话框 |

### 4.2 服务端 fingerprint 与回执分域

- `profile_id` 从本机会话取，客户端不得指定。
- 客户端提供request_id与业务字段，不提供可信fingerprint。服务端对operation kind、profile、record/source及规范请求（expected revision/hash、payload、照片hash/顺序/说明、targets、term decision、snapshot_id、token摘要等）计算fingerprint。计算不依赖后来变化的当前内容或过期token是否仍可读。
- 观察业务回执：`local_observation_operations`，`UNIQUE(profile_id,request_id)`，保存 operation_kind、record、fingerprint、status、result；恢复主回执也在此，`local_observation_restores` 以 `operation_id` 唯一关联细节，不另设 request_id 权威。
- 共享 AI 回执：`local_ai_operations`，`UNIQUE(profile_id,request_id)`；AI 提交 fingerprint 必须含 `source_kind`、`source_id`。任务／执行状态仍以 AI 四表为准，operation 只作幂等信封，不双重权威。
- 宿主保存尝试：后端`local_observation_export_attempts`以`(profile_id,export_id_hash)`唯一，保存宿主报告回执；宿主不直接打开SQLite，不把结果并入观察内容operation。外部文件写入结果以宿主实际IO证据为来源；生成或下载完成不等于saved。
- 只读查询：按 `request_id` 返回 status、changed／unchanged、result draft revision／history version、payload_hash、request_id；无副作用。
- 只读预览不是业务版本更新；预览 token 创建／消费不等于业务成功。

所有业务写统一顺序：会话／profile及请求基本语法→稳定fingerprint与本域回执查询→匹配直接返回原结果→无回执才做token有效性、当前版本、材料、AI就绪等前置工作→短写事务内再次查回执并复核全部绑定。同ID异operation/fingerprint拒绝。已提交回包丢失不能被已消费token、后来配置变化或新revision挡住读回；只读查询不触发业务、AI或原生对话框。

## 5. 保存、历史、恢复与离开

### 5.1 保存原因与事务写集合

通用保存API的`save_reason`限定`auto/manual/leave/pre_restore/pre_export`。adopt和restore是独立受校验业务操作，不能由客户端填写保存原因绕过采用token或恢复协议。

| 原因 | 同一事务写集合 | 历史节点 |
| --- | --- | --- |
| auto | draft、draft_photos（有变）、record 投影、operation | 不造 |
| manual／leave／pre_restore／pre_export | 同上；若 aggregate 与最近保留节点不同，加 version／version_photos | 有实际变化才造 |
| adopt | draft、record 投影、version／version_photos（有变）、provenance、operation | 有实际变化才造 |
| restore | versions／version_photos、draft／draft_photos、record 投影、restore 细节、operation、token 消费 | 有变才新 version |

- 唯一聚合算法：`payload_hash = SHA256(canonical_json([canonical_payload, ordered_photo_manifest]))`。规范JSON使用确定键序／UTF-8，换行与首尾空白按§2规范；term_snapshot只在平铺payload中出现一次。manifest含asset_id、原hash、真实格式／尺寸／方向、顺序／说明。时间戳、revision、投影不进入业务hash；AI工作图及实际发送依赖另算hash。
- **auto 已保存但 aggregate 与最近保留节点不同，manual／leave 仍须留节点**；不得因 `isDirty=false` 跳过。
- 同编辑会话串行保存，`BEGIN IMMEDIATE` 与 expected revision；409 保留输入。
- IME composition settle后再保存；导入busy时不放行离开；保存完成后、执行原离开动作前重核identity／epoch／最后输入，不能以旧保存成功放行新输入。

### 5.2 历史

- `versions.version` 单调递增；旧版本不可改、不可覆盖。
- 历史照片引用 `version_photos`；当前移除不删 asset、不改历史。
- 无全局内容 hash 去重；只与最近保留节点判无变化。
- 投影与 draft revision／hash 不一致时明确存储错误。

### 5.3 恢复

固定顺序：settle／完成导入 → 成功保存 UI 现稿并留下应留节点 → 预览历史 → 明确 `term_decision` → 提交。

- 默认有效恢复 payload＝完整历史 canonical payload＋历史照片／顺序／说明＋**历史 term_snapshot**（有效时 `keep_history`，不覆盖）。
- 只有明确 `term_decision` 才替换：`keep_current`（当前归属）、`assign_selected`（指定已有学期）、`unassigned`（未归属）。不得强制默认 `keep_current`。
- 历史归属失效或与日期冲突：必须选择有效方案并**重新绑定预览**；不照抄无效 FK、不静默改配置。
- 预览绑定 profile／record／source version／source hash／base draft revision／hash、照片 hash、有效学期快照、effective hash、request id、期限。
- 提交**先查匹配业务回执**：若同 request id 同 fingerprint 已有成功回执，直接返回原结果，即使 token 已消费／过期；成功回包丢失不得错误要求重新预览。
- 无回执时才在短写事务内复查token、当前revision、有效payload/hash、材料及归属绑定，按有变／无变规则写version／version_photos、draft／draft_photos、record投影、restore细节、operation并消费token。恢复完全不依赖AI配置、候选、执行器或网络。
- 无业务变化返回 `unchanged`，不增加 draft revision 或 history 节点；有变才 `revision+1` 及新 version。
- 材料真实解码／hash 在事务外完成；锁内只做短检查。恢复不调用 AI、不自动采用、不改在途任务。
- 晚到编辑用旧 revision 失败；损坏／缺失历史拒绝，不拿当前资料补洞。

### 5.4 编辑 adapter 与离开

- 观察编辑 adapter 同时处理“待保存输入”和“待保留节点”，不能只看 `isDirty`。
- 未采用候选可持久保留，不强迫采用才能离开；不继承日计划“候选未采用不准离开”的规则。
- 离开／切记录／学期／设置／关窗前：settle IME、等待导入完成、保存当前输入；若 aggregate 与最近保留节点不同，按 `leave` 留节点；失败留页。
- 不增加产品额外确认。

## 6. AI 投影、候选与采用

### 6.1 输入冻结与执行版本时点

- 提交时冻结**业务input及schema**：canonical payload、资料、有序照片／工作图／说明／hash、任务实际发送正文、warnings、输入schema及工作图派生参数；工作图与参数不可变。
- 尚未开始的任务在**claim／开始执行时**取最新有效配置与已适配提示词；execution钉住实际`config/default/personal/contract`并记录该input的实际派生参数。不能用后来新参数重建已冻结工作图，随后配置变化不追溯污染该execution／candidate。
- 若 schema／合同已不兼容，暂停对应任务；不偷改已冻结业务 input。
- `source_revision` 仅来源元信息；input 只 FK 稳定 record，不 FK `versions.revision`，不强制制造历史。
- 材料层在写事务外完成解码／派生／hash；AI worker 只读取已验证图文与传输。

### 6.2 发送与产品边界

| 任务 | 实际发送正文依赖 |
| --- | --- |
| `game_observation_generate` | 教师已有四栏全部（可全空）；基础资料／全部照片共同项见下 |
| 重写观察目标 | 当前目标为 rewrite source；观察记录为上下文 |
| 重写观察记录 | 当前记录为 rewrite source；观察目标为上下文 |
| 重写评价分析 | 当前评价为 rewrite source；观察目标、观察记录为上下文 |
| 重写支持策略 | 当前策略为 rewrite source；观察目标、观察记录、评价分析为上下文 |

- 依赖 hash 精确覆盖实际发送字段；未发送字段不误算依赖。
- 共同基础业务字段固定为`record_type/observation_date/start_time/end_time/adult_count/child_count/age_years/subjects/environment`；每类任务另含全部已关联照片、顺序、说明及工作图hash。学校／班级／观察者文字、term_id／term_snapshot及内部record/profile ID不发送给供应商，不算正文依赖；仍按服务端身份／来源隔离。执行器另加固定协议、实际提示词和模型并记录版本。
- 完整生成不得删掉教师已有正文。
- 所有已关联照片参与明确 AI 操作；不静默选子集、不新增 AI 选图 UI；超预算整体拒绝并说明。
- 应用固定观察 bundle／输出 schema；保留内部 default／personal／contract 版本机制，但**不承诺新增观察个人指导输入框或提示词编辑器**。教师已确认的是照片可选简短说明（其中可含观察意图），不是新增观察指导 UI；既有日计划个人指导规则不改。
- C11／C32：允许补对话／情境动作衔接；不能造未提供的精确分钟／持续时长或完整新事件；多人无法对应姓名时写共同情境并提示补充，不猜姓名动作。
- 保留 HTTPS／DNS／peer／TLS 校验、dispatch 标记、未知结果不重放；视觉帧独立版本化，不全局放宽旧 1MiB；完整字节预检，实际内存／复制后续容量冻结。

### 6.3 候选与采用

- 候选持久化内容、hash、schema、执行来源、各输出 hash、补写提示／定位；提示只在审核区，不进入正文／Word／后续提示词。
- 预览返回一次性adoption_token，绑定candidate/hash、profile/record、targets、当前实际依赖／target hashes、draft revision/hash、source_state、差异摘要、允许的复核决定及期限。来源变化时，提交的`review_decision='adopt_reviewed'`必须对应该预览差异，并纳入服务端fingerprint；不是要求预览创建前已有教师决定。
- 正常采用不需要review_decision或额外审批；来源变化先明确展示当前差异，教师可对该预览确认采用、取消或重新生成；取消／重新生成不走采用提交。不能用裸bool全局绕过核对，不兼容契约或坏图不能以复核覆盖。任何晚到编辑／候选／目标变化使预览失效。
- 已采用目标不得重复覆写；同候选剩余栏仅凭 provenance＋当前值等于该候选输出 hash 作受信替换；人工／其他候选碰巧同文字不算。
- 多目标一次事务写 draft／历史（有变）／provenance／投影／operation；无变化重复请求不再造节点；复核 token 丢回包先读回执。
- 后改个人指导／配置不否定已按 pinned 版本完成的兼容候选；契约不兼容另处理。
- 补写片段按目标／领域、偏移和匹配hash定位；越界或不匹配只降级总体审核提示，不让有效正文失败，不把提示拼入采用、Word或后续提示词。

## 7. 导出与 Word

### 7.1 固定快照 manifest

快照至少含：

- snapshot_id（非bearer）、profile_id、launch_id及session_scope_hash（内部会话绑定，不保存原始会话）；
- 有序 record 集合及每份 draft revision／aggregate hash；
- 冻结 canonical payload；
- 有序 asset／导出 derivative 不可变引用及 hash；
- 完整缺项事实／确认上下文；
- 模板／渲染／参数版本；
- snapshot hash、创建时间、期限。

导出创建在短事务内复核选集／顺序／各draft revision及aggregate hash／缺项事实与确认上下文；变化则重新预览。物化后只按固定snapshot生成，不回读当前draft混版本；token／临时产物只引用快照，不是另一内容权威。有效snapshot只用于用户明确的同快照重试，新鲜导出仍须重新核对变化。

### 7.2 `snapshot_id`、`export_id` 与宿主

- snapshot_id本身不是读取凭证，任何查询仍需应用会话及归属校验；export_id为受限bearer token，绑定snapshot、profile、launch/session scope、期限及使用状态。
- 宿主签名固定 `save_observation_export(export_id, filename)`；只从固定本机端点按会话取本次产物，流式原子另存为。
- export_id作为单次宿主尝试键；同token同filename指纹重入只读原结果或in_progress，异指纹拒绝，不再次打开对话框。受限结果查询不放宽旧get_save_result。
- 结果分 `saved`、`cancelled`、`failed`、`indeterminate`；未知消费／重开缺回执不能自动当失败重开对话框，用户明确重试才新尝试。
- 成功／取消／失败／过期释放本尝试临时DOCX；未完成另存为流时以受控在途引用保护，过期停止／结果明确后释放，不删除正被读取的产物。固定snapshot在有效期保留以重建，到期释放临时快照；不删业务材料及历史/input/派生引用。
- 产物释放后重试按冻结 snapshot 新建 token；snapshot 过期须重新预览，不能暗用新版本。
- 不宣称外部保存“恰好一次”。旧 `save_docx` 及 30MiB 不变；观察不复用旧 Base64 桥。文件大小／分块／超时／占用／磁盘／关闭协同参数待验证。

拟后端attempt回执至少含profile、snapshot_id、export_id_hash、filename指纹、started/终态、status/result hash／字节数／时间；由宿主经固定受限本机API报告，宿主不直连SQLite。宿主实际写入成功才可报告saved；若文件已写但回执丢失且无可核实证据，保持indeterminate，不自动再保存，不把下载完成当保存成功。文件名、token及真实保存路径不入诊断日志。

### 7.3 Word

- 标题在表外：`{园所}游戏观察记录（公共/室内/户外）`；宋体 16 磅加粗居中；园所空不放样例占位。
- A4 纵向、原六列网格、8 行业务表：第 1／2 行各 6 独立格；第 3 行姓名 2–4 `gridSpan=3`；第 4–8 行值 2–6 `gridSpan=5`。
- 固定标签保留模板原文（含“幼儿年龄”）；基本资料含环境 11 磅，四栏正文值 12 磅，固定标签沿模板；允许标签 11／正文值 12 并存。
- 第 6 行正文后每组 1 或 2 张 `wp:inline`，单张居中、等比不裁切、无浮动遮字；默认不印照片说明；每份新页，份内自然分页，无额外空白末页。
- 缺项可确认后留空栏；只有表头资料、四栏均无实际正文且无有效照片才为空记录；有正文无图、只有有效图均非空可导出；任一坏图须处理，不静默跳过问题记录或漏图。
- 混合公共／室内／户外选择；跨页勾选维护明确 ID 集合；默认日期升序、空日期末尾、同日时段升序、空时段当日末尾、同值创建先后；无日期用“未填日期”，不伪造今天。
- 不新增任意业务份数额度；技术容量仍须验证。观察 Word 不使用日计划标红、AI 提示、候选标签或脚注。
- 真实 Word 逐页仍未验；XML／PDF 不能替代。

8行逐格标签、手选排序、默认文件名／长姓名安全转义及分页细节以[工程设计E10–E12](../specs/desktop-game-observation-engineering.md#12-e11三模板及固定导出)为准。单份与合并均可改建议文件名，正文姓名不截断；不新增必填内部标题、封面或目录。

## 8. 材料、事务、会话、审计与脱敏

- 支持 JPEG、PNG、WebP、静态 GIF、BMP；按真实内容识别，不信扩展名／MIME；动画明确拒绝，不偷取首帧。
- EXIF 方向在派生时纠正；透明转 JPEG 用白底；派生去除元数据；原字节不可改。
- 原图／工作图／导出图分离；历史／input 引用持久；临时导出清理不删资产。
- 图片导入：staging → 事务外受控串行验证／解码／方向／派生／hash → 同卷原子落受管不可变文件 → 短 DB 事务写 asset／derivative、draft photos、draft revision／hash、投影、operation。
- 文件先成功、DB 失败可留孤儿；明确失败并保留现场，不报成功；首期不自动清理。
- 路径：只接受 opaque ID；拒绝遍历、链接／junction、越界硬链接、ADS、设备名、尾点；不传任意磁盘路径／URL。
- 会话：沿用回环、应用会话、Origin／Host 校验；跨 profile 拒绝。
- 审计只记非敏感元信息：profile／record／version／draft revision、candidate／input、`snapshot_id`／operation_id／非敏感 export reference 或 token 摘要、状态、错误码、耗时、大小／hash、request_id。
- **不记**原始 `export_id`／preview／adoption token／应用会话／认证材料；`filename` 可能含幼儿姓名，不入日志；业务 token 只在受限服务／回执，前端／宿主仅必要时持有，不作遥测。
- 不记儿童姓名、照片／Base64、完整正文、提示词、密钥、认证头或真实路径。业务回执／审计同事务成功或回滚，不留下假成功；不新增日志服务／队列／遥测／查看界面。
- 全局关闭／在途统计包含两类任务；旧日计划接口只返回 `daily_plan` 及原字段语义。

## 9. 错误分类

以下为拟定观察接口错误类别，沿既有`{"error":{"code","message","details"?}}`信封；不改变日计划原错误码。details只含允许的字段／ID／hash／差异事实，不含密钥、token、照片、完整正文或真实路径；来源不适用的语义`SOURCE_CHANGED`在观察接口对应`OBS_AI_SOURCE_CHANGED`。已提交回执优先于下列token失效或当前状态错误。

| 类别 | 代表错误 | 行为 |
| --- | --- | --- |
| 校验 | `OBS_VALIDATION_INVALID`、`OBS_VALIDATION_INCOMPLETE` | 指出字段／原因；草稿可缺项，AI 门槛单列 |
| 身份／来源 | `OBS_NOT_FOUND`、`OBS_CROSS_PROFILE`、`OBS_CROSS_RECORD` | 拒绝，不泄露其他记录 |
| 并发 | `OBS_REVISION_CONFLICT` | 409，保留输入 |
| 幂等 | `OBS_IDEMPOTENCY_CONFLICT` | 同 request id 异 fingerprint 拒绝 |
| 材料 | `OBS_MATERIAL_INVALID/MISSING/CORRUPT/LIMIT` | 指出记录与图片；不静默漏图／换图 |
| 历史 | `OBS_HISTORY_CORRUPT/MISSING` | 拒绝恢复，不用当前资料补洞 |
| 恢复 | `OBS_RESTORE_TOKEN_EXPIRED/CONSUMED`、`OBS_RESTORE_TERM_CHANGED`、`OBS_RESTORE_MATERIAL_CHANGED` | 不写业务内容，要求重新预览 |
| AI | `OBS_AI_SOURCE_CHANGED`、`OBS_AI_CONTRACT_INCOMPATIBLE`、`OBS_AI_CANDIDATE_STALE` | 默认不采用；显示差异；复核或重新生成 |
| 导出 | `OBS_EXPORT_EMPTY`、`OBS_EXPORT_MISSING_UNCONFIRMED`、`OBS_EXPORT_BAD_MATERIAL`、`OBS_EXPORT_TOKEN_*`、`OBS_EXPORT_SAVE_*` | 分开报告；不交付残缺文件；释放临时产物 |
| 存储 | `OBS_STORAGE_PROJECTION_MISMATCH`、`OBS_STORAGE_IO` | 明确失败，不静默覆盖权威 |

## 10. 跨模块责任

| 事项 | 生产者 | 消费者 | 失败责任 |
| --- | --- | --- | --- |
| 档案／班级／学期及快照 | 身份与班级 | 观察 | 配置错误归身份；快照错误归观察 |
| 提示词字段／默认／内部版本 | 提示词 | AI、观察 | 契约／版本归提示词；投影归观察；执行校验归 AI |
| AI 配置／网络／候选校验／状态 | AI Service | 观察 | 网络／校验／状态归 AI；采用归观察 |
| 记录／草稿／历史／材料／候选意义／采用 | 观察 | Word、审计 | 观察 |
| Word 渲染 | Word | 宿主 | 模板／渲染归 Word；快照归观察；保存归宿主 |
| 审计元信息 | 观察／AI／Word／宿主 | 审计 | 各生产者保证脱敏；审计不驱动业务 |
| 会话／关闭／原生保存 | 宿主 | 观察／Word | 宿主 |

## 11. E01–E14 与 A/R 门槛

| 工程项 | 落点 | A／R 关键门槛 |
| --- | --- | --- |
| E01 | §2 | A01–A03、A07、A15；R01–R05 |
| E02 | §3 | A04、A12、A21–A22；R06–R07、R09–R10、R14 |
| E03 | §3、§8 | A06、A08、A12、A19、A21；R04、R10 |
| E04 | §2、§5 | A01、A05、A13；R06–R08 |
| E05 | §5 | A04、A11–A12、A16；R09 |
| E06 | §6 | A07–A08、A14、A21–A22；R02–R04、R14 |
| E07 | §6 | A07、A09–A10、A14；R02–R05、R12、R14 |
| E08 | §5.3 | A06、A11–A14；R07–R10 |
| E09 | §5.4、§8＋宿主 | A01、A11、A14、A20、A22；R09、R11 |
| E10 | §4、§7 | A04–A05、A17；R06–R07、R11 |
| E11 | §7 | A03、A10、A15–A20；R01、R05、R11–R13 |
| E12 | §8 | A06、A16、A20–A22；R10–R11、R14 |
| E13 | 本 Contract＋五份扩展 | A21–A22 及全部职责前提；R01–R14 |
| E14 | §12 | A01–A22；R01–R14；全部未验 |

## 12. 参数、ADR 与未验

待容量验证后冻结：canonical payload 字节；原图大小／像素／单边；AI 工作图长边／质量／目标字节；视觉请求体／IPC 帧／超时／工作集；导出图长边、DOCX 大小／分块／超时；`export_id`／恢复 token 期限；导入／派生并发与磁盘余量。均为提案，不在本 Contract 冻结。

预计不需 ADR：技术栈、依赖方向、SQLite／受管文件权威、本机 API 与 worker 通信未变；观察是 Feature 模块，`export_id` 是现有宿主保存桥的受限扩展。若改为新服务／新进程、外部网络交付、浏览器或远端成为内容权威、改变模块所有权或通信机制，先提 ADR，不暗改 `ARCHITECTURE.md`。

未验：本Contract完整A01–A22尚未验收；E01／E02／E04基础规则、模型、迁移与守卫后种子的实际独立结果见[本片报告](../bootstrap/desktop-game-observation-foundation-review.md)，其余服务及完整产品流程仍未实施／未验。本轮未启动桌面应用、构建或调用应用真实AI／WebDAV。Pillow 13.0.0仅依赖提案，未安装；Word逐页、WebView2、宿主保存、文件路径边界、容量参数均未验。Win10、WPS、干净机器、其他DPI／显示器、签名发行及D2／D3既有未验项保持未验。停在本片，后续实施须另授权，唯一入口见[当前任务](../tasks/current.md)。

