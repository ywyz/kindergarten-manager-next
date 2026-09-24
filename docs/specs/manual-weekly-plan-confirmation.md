# I4 手工周计划创建、编辑与确认实施规格

状态：**I4 规格已确认（本范围内，U1–U5 五项产品决定已于 2026-09-23 确认，见 §1.5）；四片实施与第四片隔离真实验证已于 2026-09-23 完成。** 本规格最初基于 main / 1e6e3a6 的定向只读核对编写（当时只写文档）；此后第一至第四片按第 10 节逐片授权完成：迁移与服务、API 与权限、前端闭环、隔离 MySQL 8.4 / InnoDB 集成（V1–V14，0 skip）与真实浏览器 §8 验收均实际执行并通过，详见 `docs/bootstrap/architecture-v1-readiness.md` 的实施状态段与本节 §12 的执行记录。规格条款本身未因实施改写。

标注约定：

- **已确认**：来自用户在本项目中的明确决定（含交接提示中“不得重问”的固定规则），不得由实现改写。
- **工程方案**：OpenCode 提出的实现推荐（表名、索引、路由、锁实现、错误码细分等），在不改变产品行为的前提下可调整，不作为产品问题提交用户。
- **已决定（2026-09-23）**：U1–U5 五项产品选择，记录于 §1.5；被拒方案仅作决策留痕，不构成待选项。

依据：[ARCHITECTURE.md](../../ARCHITECTURE.md)、[ADR 0002](../adr/0002-background-tasks-and-versions.md)、[周计划 Contract](../modules/weekly-plans.md)、[日计划 Contract](../modules/daily-plans.md)、[用户与班级 Contract](../modules/identity-and-class.md)、[Word 导出 Contract](../modules/word-export.md)、[最小实施规格](manual-plans-and-word-export.md)、[I3 规格](manual-daily-plan-save.md)、[I2 记录](../bootstrap/i2-implementation-status.md)，以及现有代码 `WeeklyPlanSyncState`／`weekly_plan_sync_service`／`daily_plan_service`／`daily_plans` 路由／权限快照／I2 日历读取与锁代码的定向核对。

## 1. 状态与来源

### 1.1 已确认且不得重问的规则

| 规则 | 来源 |
| --- | --- |
| MySQL 8.4 / InnoDB 是业务权威来源；周计划读取 I3 日计划及其当前内容版本，不反向修改日计划 | 架构、各 Contract、I3 决定 |
| 同班、同学期、同周只能有一份有效周计划；重复创建打开已有记录并保留原创建者与负责人 | 周计划 Contract |
| 创建教师是初始负责人；负责人可编辑与确认；同班其他教师只读；管理员可编辑但不能代替负责人确认；管理员编辑后内容继续待负责人确认 | 周计划 Contract、交接规则 |
| 周计划主题由负责人维护，未来 AI 只能建议，不能自动覆盖 | 周计划 Contract、ADR 0002 |
| 晨间谈话与集体活动名称按日期确定性汇集；缺日计划、空字段与休息日必须分别表达，不能自动补写 | 周计划／日计划 Contract |
| 周计划户外游戏为两项集体游戏加一项自选游戏；同类别同名游戏只占一个名额；选择一个日计划来源必须携带该来源的 daily_plan_id、content_id、content_version、group_id、game_id 及整组共用目标／指导，不跨来源拼接（content_id 为评审补充的必带键） | 周计划 Contract、最小实施规格、评审 |
| 负责人可以选择其他真实来源；手工补充不能伪造日计划来源或 AI 来源；材料在纯手工切片允许缺失，不改写为必须手工提供 | 周计划 Contract、最小实施规格 |
| 上一份已确认版本、当前人工草稿、未来 AI 候选是不同对象；I4 不建假候选或空任务表预留 AI | ADR 0002、交接规则 |
| 已确认版本不可原地改写；来源变化、管理员编辑或后续草稿保存不会覆盖上一确认版本 | ADR 0002、周计划 Contract |
| 确认时重新检查负责人权限、草稿版本和所有来源版本；旧来源不能冒充最新；负责人可明确确认当前不完整或未更新内容，但必须记录具体缺失／未更新事实 | ADR 0002、周计划 Contract |
| 任务状态、内容完整性、来源新旧、确认状态是不同维度，不用单一 status 抹平 | ADR 0002、周计划 Contract |
| I3 的 `weekly_plan_sync_states` 是可消费的待确认投影，不是周计划表、不是任务表、不决定负责人 | I3 规格 §5.6、交接规则 |

### 1.2 本轮范围（包含）

- 同班同学期同周有效周计划唯一；创建或打开（含并发）。
- 负责人（创建教师）身份与权限：负责人编辑／确认，同班教师只读，管理员仅可编辑已存在的计划、不可创建、不可代确认，管理员编辑后待负责人确认。
- 手工草稿：主题、确定性栏目（负责人可编辑，见 §2.5 的来源值／人工覆盖／生效值三层）、户外游戏两项集体加一项自选的来源选择、重点区域来源选择、其余手工栏目。
- I3 投影消费：创建时初始化草稿、显式刷新、保存时刷新确定性来源值并保留人工覆盖；普通保存不重盖既有陈旧游戏／重点区域引用。
- 来源版本检查、版本冲突（409）、不完整／未更新的明确确认、不可变确认版本与确认历史。
- 权限矩阵、事务与锁协议、前端闭环、最小验证矩阵、实施切片与资源清单。

### 1.3 不包含项

AI 候选生成、30 秒调度、持久任务工作进程、个人 AI 配置／提示词、Word 导出实现、日计划删除恢复、周计划删除恢复、调班停用、负责人接管、生产部署。不暴露上述能力的半成品入口（无 AI 按钮、无导出按钮、无删除／恢复入口、无任务表或候选表占位）。

### 1.4 排除项硬依赖检查

已按现有 Contract 与代码逐项核对：确认闭环只依赖 I2 持久日历、I3 日计划内容版本与 `weekly_plan_sync_states`、既有权限快照与锁设施；**没有任何排除项成为确认闭环的硬依赖**，因此本轮不需要提出模块边界或权威来源的最小调整。删除／恢复延后但 schema 与 I3 一致地预留 `deleted_at`／`deleted_by`，唯一性用生成列兼容，不需要提前开放入口。若实施中发现相反情况，必须停下提出 ADR 草案，不自行扩边界。

### 1.5 产品决定记录（U1–U5，2026-09-23 已确认）

以下五项已由用户确认；对应规范条款已按选择无条件化，被拒方案仅留作决策记录。

| 编号 | 已确认选择 | 规范落点 | 被拒方案（仅留痕） |
| --- | --- | --- | --- |
| U1 表头 | **A：创建时快照** `school_name`/`class_name`/`grade`/`header_teacher_names`/`caregiver_name` 不可变写入 `weekly_plans` | §2.2、§2.8 | B：读取当前资料（历史表头随管理员修改漂移，与 I3 快照语义不一致） |
| U2 主题 | **B：允许为空**——创建、草稿保存、确认均接受空主题，确认时记入 `facts.missing`（`empty_theme`） | §5.1、§7.3、V4 | A：创建即必填（与“内容允许为空、禁止自动补写”不一致） |
| U3 不完整／未更新确认 | **A：系统事实 + 显式 ack**——`ack_missing`/`ack_stale` 必须按事实置真；`note` 自由文本**可选**、永不必填 | §5.1、§6.3、§7.3、§8 | B：缺失／陈旧时强制必填说明 |
| U4 来源变化双路径 | **按 §1.5 下表原样采纳**：显式刷新（R）与确认当前未更新（C）两条路径及其审计字段与 UI 提示 | §3.3、§7.4、§8 | 确认接口内隐式刷新；无审计的静默确认 |
| U5 手工补充身份 | **A：`source_kind` 判别字段**，`manual_item_id` 服务端生成且草稿内稳定，日计划引用字段全 null；`ai` 留语义位、I4 校验拒绝 | §2.5、§2.6 | B：仅靠 `daily_plan_id` 空值推断（无法拒绝伪造混合结构） |

#### U4 已确认的双路径（规范表）

| 路径 | 行为 | 审计事实 | UI 提示 |
| --- | --- | --- | --- |
| R. 刷新到最新来源 | 负责人显式触发刷新：确定性栏目按当前日计划重算来源值（人工覆盖保留），已选游戏／重点区域按同一 (daily_plan_id, group_id, game_id) 重新解析当前内容（新 content_id、content_version 与整组文本）；主题、人工覆盖与人工栏目不动；追加一个新草稿版本 | 新草稿版本记录 `editor`、`refresh` 动作及各来源 `from (content_id, content_version) → to (content_id, content_version)`；操作记录 `refresh_weekly_sources` | 确认页检测到陈旧来源时显示横幅与“刷新到最新来源”按钮 |
| C. 确认当前未更新内容 | 负责人带着已展示的差异清单显式确认：确认版本按草稿现有内容快照落库，**旧来源引用、旧 content_id／content_version 与旧整组文本原样保留**，事实里逐条并列记录草稿侧与当前侧的 daily_plan_id／content_id／content_version 及 group_id／game_id，**不把陈旧来源标成最新** | 不可变确认版本内的 `stale_sources` 结构化清单（含双侧 content_id／content_version）；操作记录 `confirm_weekly_plan` 带 `ack_stale` | 横幅第二按钮“确认当前未更新内容”，点击前强制展示差异清单并勾选 ack（`note` 可选） |

两条路径都必须显式点击，确认接口绝不隐式刷新来源，刷新接口也绝不改写主题、人工覆盖与人工栏目。

#### U5 已确认的手工补充身份（规范）

户外游戏槽位的每条选择携带 `source_kind ∈ {daily_plan, manual}`（`ai` 保留给未来切片，I4 校验直接拒绝）：`daily_plan` 必填 `daily_plan_id/content_id/content_version/group_id/game_id` 与整组文本；`manual` 必填服务端生成的 `manual_item_id` 与名称／文本，全部日计划引用字段为 null。**手工补充身份仅适用于三个户外游戏槽位；`focus_area` 只允许 `source_kind=daily_plan` 或 `null`（见 §2.5），不接受 `manual`。**

`manual_item_id` 与草稿内 `group_id`/`game_id` 同规则：服务端生成、草稿内稳定、随追加版本保留、拒绝跨周计划引用。名称相近不合并、同类别同名单名额属已确认规则，与身份方案正交。

## 2. 领域模型与完整 schema 草案

### 2.1 对象与身份

| 对象 | 身份与边界 |
| --- | --- |
| WeeklyPlan | 稳定 id；`class_id + term_id + week_number` 有效唯一；`creator_id`（原创建者，不可变）与 `owner_id`（当前负责人；I4 恒等于 creator，接管留待后续切片）分开存；创建时不可变表头快照（U1=A） |
| 周计划草稿版本 | `weekly_plan_contents` 追加写入；`weekly_plans.current_draft_content_id + current_draft_version` 指向当前可编辑草稿（用户视角“可变草稿”，实现为 append-only 版本 + 指针，与 I3 同模式） |
| 确认版本 | `weekly_plan_confirmed_contents` 追加写入、不可原地改写；`weekly_plans.current_confirmed_content_id + current_confirmed_version` 指向最新确认版本，可空（从未确认） |
| 来源 manifest | 内嵌于草稿与确认内容 JSON：每条引用带判别字段、`daily_plan_id + content_id + content_version` 与稳定 `group_id/game_id`；确认版本内是自包含快照 |
| 游戏选择身份 | 户外游戏槽位固定 `collective_1`/`collective_2`/`free_choice_1`，条目身份按 §1.5 U5 的 `source_kind` 判别规则（`daily_plan` 或 `manual`）；`focus_area` 单槽仅 `daily_plan` 或 `null`（§2.5） |

### 2.2 `weekly_plans` 表

```text
id: String(32, utf8mb4_bin) PK
class_id: String(32, utf8mb4_bin) FK classes.id, index
term_id: String(32, utf8mb4_bin) FK terms.id, index
week_number: Int, CHECK week_number >= 1
creator_id: String(32, utf8mb4_bin) FK accounts.id        -- 不可变
owner_id: String(32, utf8mb4_bin) FK accounts.id          -- I4 恒等于 creator_id；接管切片再变

-- 有效唯一性（与 I3 同模式）
effective_week INT GENERATED ALWAYS AS (
    CASE WHEN deleted_at IS NULL THEN week_number END
) STORED
UNIQUE (class_id, term_id, effective_week)

-- 草稿指针：可空仅限创建事务内，提交前应用层断言非空
current_draft_content_id: String(32, utf8mb4_bin) nullable
current_draft_version: Int nullable
-- 复合外键指向 weekly_plan_contents(weekly_plan_id, id, version)

-- 确认指针：可空 = 从未确认
current_confirmed_content_id: String(32, utf8mb4_bin) nullable
current_confirmed_content_version: Int nullable
-- 复合外键指向 weekly_plan_confirmed_contents(weekly_plan_id, id, version)

-- 表头快照（U1=A，2026-09-23 确认）：创建时写入，创建后不可变
school_name: String(120) nullable
class_name: String(80)
grade: String(20)
header_teacher_names: JSON          -- 有序名单快照，与 classes.header_teacher_names 同构
caregiver_name: String(80) nullable

-- 工程方案：粗粒度“日计划侧新于上次消费”提示（横幅用），权威新鲜度仍按来源版本逐条比较
projection_consumed_at: DateTime nullable

deleted_at: DateTime nullable        -- 本轮无入口，仅为与 I3 一致的兼容预留
deleted_by: String(32, utf8mb4_bin) FK accounts.id nullable
created_at, updated_at: DateTime
```

### 2.3 `weekly_plan_contents`（草稿，append-only）

```text
id: String(32, utf8mb4_bin) PK
weekly_plan_id: String(32, utf8mb4_bin) FK weekly_plans.id, index
version: Int, CHECK >= 1            -- 从 1 递增，同一周计划内唯一
content: JSON                       -- 草稿内容，结构见 §2.5；不原地更新
editor_id: String(32, utf8mb4_bin) FK accounts.id
editor_role: String(20) CHECK IN ('owner', 'admin')   -- 快照，回答“是否管理员编辑过”
created_at: DateTime
UNIQUE (weekly_plan_id, id, version)
UNIQUE (weekly_plan_id, version)
```

工程方案：迁移中先建三表，再 `ALTER` 添加两个复合外键（同 I3 `fk_daily_plans_current_content` 模式，避免循环建表顺序问题）。

### 2.4 `weekly_plan_confirmed_contents`（确认版本，append-only、不可变）

```text
id: String(32, utf8mb4_bin) PK
weekly_plan_id: String(32, utf8mb4_bin) FK weekly_plans.id, index
version: Int, CHECK >= 1            -- 确认序号，从 1 递增
draft_version: Int                  -- 确认的是哪个草稿版本
content: JSON                       -- 确认时草稿内容的完整自包含快照（含来源 manifest 与整组文本）
facts: JSON                         -- 结构化确认事实，见 §7.3；note 为可选自由文本（U3=A）
confirmed_by: String(32, utf8mb4_bin) FK accounts.id   -- 必须是当时 owner_id
created_at: DateTime
UNIQUE (weekly_plan_id, id, version)
UNIQUE (weekly_plan_id, version)
```

### 2.5 草稿内容 JSON 结构（`content`）

```json
{
  "theme": "",
  "deterministic": [
    {
      "date": "2026-09-23",
      "day_state": "teaching",
      "plan_state": "saved",
      "source": {
        "daily_plan_id": "...", "content_id": "...", "content_version": 2,
        "morning_talk_topic": "秋天的树", "group_activity_theme": "捡落叶"
      },
      "override": {"morning_talk_topic": null, "group_activity_theme": null},
      "effective": {"morning_talk_topic": "秋天的树", "group_activity_theme": "捡落叶"}
    },
    {"date": "2026-09-24", "day_state": "teaching", "plan_state": "no_plan",
     "source": {"daily_plan_id": null, "content_id": null, "content_version": null,
                "morning_talk_topic": null, "group_activity_theme": null},
     "override": {"morning_talk_topic": "补一个谈话话题", "group_activity_theme": null},
     "effective": {"morning_talk_topic": "补一个谈话话题", "group_activity_theme": null}},
    {"date": "2026-09-26", "day_state": "rest", "plan_state": "none_required",
     "source": {"daily_plan_id": null, "content_id": null, "content_version": null,
                "morning_talk_topic": null, "group_activity_theme": null},
     "override": {"morning_talk_topic": null, "group_activity_theme": null},
     "effective": {"morning_talk_topic": null, "group_activity_theme": null}}
  ],
  "outdoor_game_slots": {
    "collective_1": {
      "source_kind": "daily_plan",
      "daily_plan_id": "...", "content_id": "...", "content_version": 2,
      "group_id": "...", "game_id": "...",
      "name": "跳圈圈",
      "shared_objectives": "...", "guidance_points": "...", "focus_guidance": "..."
    },
    "collective_2": null,
    "free_choice_1": {
      "source_kind": "manual",
      "manual_item_id": "...",
      "name": "滚球",
      "shared_objectives": "...", "guidance_points": "...", "focus_guidance": "..."
    }
  },
  "focus_area": {
    "source_kind": "daily_plan",
    "daily_plan_id": "...", "content_id": "...", "content_version": 3,
    "group_id": "...", "game_id": "...",
    "context_kind": "area", "area": "...",
    "name": "...", "objectives": "...", "guidance": "...", "support_strategy": "..."
  },
  "weekly_columns": {
    "key_week_focus": "",
    "environment_setup": "",
    "habit_culture": "",
    "home_cooperation": ""
  },
  "materials": null
}
```

规则（已确认语义的结构化落点）：

- `deterministic` 每日三层分离（负责人可编辑确定性栏目，已确认）：
  - `source` **服务端拥有**：由该日日计划当前内容重算，客户端不可写。`day_state ∈ {teaching, rest}`；`plan_state ∈ {saved, no_plan, none_required}`（休息日为 `none_required`）；`saved` 且字段空用空字符串 `""`，与 `no_plan` 的 `null` 区分——缺日计划、空字段、休息日三种表达分离，不自动补写。日期枚举为该周周一至周日与学期闭区间的交集；学期外日期不入列。
  - `override` **人工覆盖**：负责人（及管理员，同草稿编辑权限）可按日期写入 `morning_talk_topic` / `group_activity_theme` 覆盖值或清回 null；跨任意投影重算与显式刷新**原样保留**，仅负责人显式改写才变化。
  - `effective` **生效值**：服务端派生，`字段 = override.字段 !== null ? override.字段 : source.字段`；PATCH 响应与展示读该层。缺项判断（空字段类缺失）按 `effective` 计算。
- PATCH 载荷接收 `deterministic_overrides`（按日期键覆盖 `override` 层）；`source` 与 `effective` 层不在载荷中出现，服务端在每次写入时重算 `source` 与 `effective`。
- `outdoor_game_slots` 恰好三个键，槽位可为 `null`（缺项，不伪造凑数）；同类别同名在 UI 层合并为一个名额并提供多来源选择，存储仍是指向具体某条来源的单条选择。
- `focus_area` 可空；来源仅允许 `daily_plan`（重点区域按 Contract 从集体活动后区域／户外／专用室游戏选取；I4 不为其提供手工捏造入口，缺项用 `null` 表达）。
- `weekly_columns` 为手工栏目，人工编辑，刷新与确定性重算不得触碰。
- `materials` I4 恒为 `null`：材料属 AI 提取加负责人确认的后续切片，纯手工切片保留缺项，不提供手工必填，也不暴露“生成材料”入口。
- 判别校验：`source_kind` 只接受 `daily_plan`／`manual`，收到 `ai` 或未知值 422；`daily_plan` 引用缺任一必填字段（`daily_plan_id/content_id/content_version/group_id/game_id`）、`manual` 携带任何日计划引用字段、`manual_item_id` 不属于本草稿当前版本，均 422。
- Pydantic `extra="forbid"`；`group_id`/`game_id`/`manual_item_id` 服务端生成与校验，规则对齐 I3 `daily_plan_content`。

确认版本 `content` 为上述结构的完整快照（含每日 `source`、`override`、`effective` 三层及各引用的 content_id／content_version），不再依赖读取时的实时解析。

### 2.6 游戏与重点区域来源选择的工程行为

- 选择校验（仅发生在**新选取／改选来源**与**显式刷新**时）：`daily_plan_id` 必须是本周该班的有效日计划；`group_id`/`game_id` 必须存在于该计划当前内容中，否则 422（提示重新选择）；`content_id` 与 `content_version` 由服务端盖章为该时刻的当前内容，不信任客户端版本号。
- **普通 PATCH 绝不重盖章**：已存在的 `daily_plan` 引用（含已陈旧的）原样保留其 `content_id`／`content_version` 与整组文本；只有两类动作可以更新它们——显式 `refresh-sources`（同一 group/game 重解析到新 content_id／content_version 与新文本），或负责人显式改选另一条来源（整体替换该槽位引用与文本）。
- 读取新鲜度：草稿记录的 `daily_plan_id + content_id + content_version` 与来源计划当前的 `daily_plan_id + current_content_id + current_content_version` 比较，条目级再核对 `group_id + game_id` 仍在该 content 内 → 陈旧／缺失清单；来源计划缺失（未来删除兼容）→ 缺失清单（见 §7.2）。
- GET 详情响应附带 `source_candidates`（服务端按当前日计划即时计算的本周候选：类别、名称、日期、`daily_plan_id/content_id/content_version/group_id/game_id` 引用与整组文本），只读、不落库，供前端选择器使用。

### 2.7 正交状态维度（禁止单一 status 抹平）

| 维度 | 表达方式 |
| --- | --- |
| 确认状态 | `current_confirmed_*` 指针空否；`confirmed.draft_version` 与 `current_draft_version` 比较 → `never_confirmed` / `draft_ahead`（待负责人确认）/ `draft_current`。不新增单一 `status` 列 |
| 内容完整性 | 缺失清单（槽位 null、空主题、缺日计划日期、`effective` 空字段、材料缺项）——草稿读取时实时计算，确认时固化进 `facts.missing` |
| 来源新旧 | 草稿记录的 `daily_plan_id/content_id/content_version + group_id/game_id` vs 来源当前值 → 实时陈旧清单；确认时固化进 `facts.stale_sources`；确认后同样可对确认快照重算 |
| 管理员编辑痕迹 | 草稿版本行 `editor_role='admin'`；只要存在 `confirmed.draft_version < current_draft_version` 即待确认，与谁编辑无关 |
| 投影消费 | `projection_consumed_at` 与同步行 `updated_at` 的横幅级提示，以及 §3 的消费契约；不与确认状态混用 |

一份周计划可以同时是“已确认 V1 + 草稿 V3 待确认 + 两处来源陈旧 + 一处缺日计划”，各维度并列呈现。

### 2.8 表头策略（U1=A，2026-09-23 已确认）

- §2.2 五个表头列**必须存在**；创建事务内在锁定 `school_settings` 与 `classes` 后取快照，创建后不可变；读取与未来导出只读 `weekly_plans` 自身。管理员改名单／保育员／班名不回填已建周计划。
- 被拒方案 B（读取当前资料合成表头）仅见 §1.5 决策留痕，不再影响 schema、API 或读取组装。

## 3. I3 投影消费契约

`weekly_plan_sync_states` 归 I3 所有：I3 在每次日计划创建／保存的同一事务内按全周有效日计划重算并写回，`status` 的 CHECK 只允许 `pending_projection`。I4 是消费方，不是该表的写方。

### 3.1 创建时初始化

1. 按 §6 锁顺序锁定后，用与 `weekly_plan_sync_service.load_week_entries` 相同的语义以 `FOR UPDATE` 读取本周全部有效日计划及其当前内容（权威来源是日计划本身，不是投影副本）。
2. 依此生成每日 `deterministic.source`（含 `daily_plan_id/content_id/content_version`）与游戏候选所需的整组文本；`override` 全 null，`effective` 按派生规则等于 `source`；三个游戏槽位与 `focus_area` 初始为 `null`（不自动替负责人选游戏）。
3. 同事务读取对应同步行（若存在）：把其 `updated_at` 记入 `projection_consumed_at`；同步行不存在且本周也无日计划 → `projection_consumed_at = now`；同步行不存在但存在日计划 → I3 同事务不变量被破坏 → 503，与 I3 读取语义一致。
4. 插入 `weekly_plans`、草稿版本 1、指针回填、操作记录 `create_weekly_plan`，一次提交。

### 3.2 确定性字段如何进入草稿

- 创建：如上播种（`source` 服务端写入，`override` 为空）。
- 保存（PATCH）：服务端按当前日计划重算每日期的 `source` 与派生 `effective`，并接收载荷中的 `deterministic_overrides` 写入 `override` 层；**已有 `daily_plan` 游戏／重点区域引用不重盖章**（§2.6）。主题、三个户外游戏槽位（可含 `manual` 条目）、`focus_area`（仅 `daily_plan` 或 `null`）、`weekly_columns` 为负责人编辑区，按 §2.6／判别规则校验后原样保留。
- 显式刷新（refresh-sources）：重算 `source`/`effective`（`override` 保留），并把已选 `daily_plan` 引用重解析到当前 content_id／content_version 与新文本；主题、`override`、`weekly_columns` 不动。
- 读取（GET）：只读，不改库；响应中的实时缺失／陈旧清单由比较得出，避免 GET 副作用与双标签互踩。

### 3.3 日计划后续保存如何标记、如何刷新

- I3 保存日计划后，同步行 `updated_at` 刷新、manifest 更新——I4 不介入该事务。
- 周计划侧的“被标记”：下次 GET／写入时发现 `sync.updated_at > projection_consumed_at`（横幅：日计划有新变化），以及逐条来源版本比较得到的陈旧清单（权威）。
- 刷新动作：**仅**显式 `POST .../refresh-sources`（U4 路径 R）会重解析已选来源到新 content_id／content_version；PATCH 只重算确定性 `source`/`effective`（保留 `override` 与既有游戏引用原样）。刷新与 PATCH 都产生新草稿版本、更新 `projection_consumed_at`，都**不覆盖**主题、人工覆盖与 `weekly_columns`。
- 来源在负责人未操作期间变化时，草稿中的旧 `content_id`／`content_version` 与旧整组文本保持原样（陈旧清单增长），普通保存也不改写——符合“新内容不直接覆盖正在编辑的内容”。

### 3.4 消费后 pending 信息是否保留

- **保留**。I4 不删除、不改写、不改状态 `weekly_plan_sync_states` 任何字段：该行继续表达“日计划侧的待确认投影”，其读取路由与 I3 日计划响应中的 `weekly_sync_state` 摘要行为不变。
- “已被周计划消费掉多少”记录在 `weekly_plans.projection_consumed_at` 与草稿／确认内容内的逐条来源版本上；确认不清除同步行，确认后日计划再变化，横幅与陈旧清单重新出现，而确认版本不动。
- **禁止**：复制一份投影 JSON 到周计划表后声称“已同步”、把同步行 status 当周计划确认状态、以同步行决定负责人。新鲜度权威永远是逐条 `daily_plan_id + content_id + content_version`（条目级再加 `group_id + game_id`）比较。

## 4. 数据约束与迁移设计

### 4.1 有效唯一性与并发创建

- 生成列 `effective_week` + `UNIQUE(class_id, term_id, effective_week)`：有效行唯一；软删除行该列为 NULL，MySQL 唯一索引允许多个 NULL，为未来恢复冲突处理留位（本轮无入口）。
- 并发创建：双方锁 `classes` 行串行化；即便时序穿透，IntegrityError(1062) 整事务回滚后新事务读取既有记录返回 200，保留原 creator/owner，不产生第二份有效记录——复用 I3 `is_effective_date_unique_violation` 的识别模式（键名换 `uq_weekly_plans_class_term_effective_week`）。

### 4.2 版本指针与外键

- 草稿指针复合 FK `(id, current_draft_content_id, current_draft_version) → weekly_plan_contents(weekly_plan_id, id, version)`；确认指针同构指向 `weekly_plan_confirmed_contents`。创建事务内先插主表（指针空）→ 插版本 1 → 回填指针 → 应用层断言非空 → 提交。读到空指针 503。
- 确认指针更新与确认版本插入同事务；确认指针可空表示从未确认，不是错误。

### 4.3 迁移链与现有数据保护

- 新迁移 `202609xx_i4_weekly_plans`，`down_revision = 20260923_i3_daily_plans`：创建三表 → 两条 `ALTER ... ADD CONSTRAINT` 复合外键 → 扩展 `operation_records.target_type` CHECK，加入 `'weekly_plan'`（不移除既有值）。
- **`weekly_plan_sync_states` 零改动**：不 ALTER、不回填、不删行；其 CHECK、唯一键与数据保持 I3 原样。
- 不修改 I1/I2/I3 任何既有行；`plans_started_at` 已由 I3 设置，I4 不回写。

### 4.4 删除恢复边界

本轮不实现、不暴露 DELETE／recover／已删除列表；`deleted_at`/`deleted_by` 仅作兼容预留。唯一性设计已为软删除保留语义，未来恢复冲突必须显式处理、不静默覆盖——该规则写入本节备忘，不构成本轮入口。

## 5. API 与权限矩阵

工程方案（路由名与路径可调，语义不可调）；全部挂 `/api`，全部请求后端重新判定权限，Pydantic `extra="forbid"`，教师路径不传 `class_id`，管理员路径必须显式 `class_id`，`term_id` 一律服务端校验存在性。

### 5.1 最小接口集

| 方法／路由 | 权限 | 输入要点 | 成功 |
| --- | --- | --- | --- |
| `GET /weekly-plans` | 同班教师或管理员 | 教师：`term_id?`、`offset`、`limit`；管理员：必须 `class_id` + 同上 | 200 列表（id、term、week、creator、owner、draft_version、confirmed_version、needs_confirm、updated_at） |
| `POST /weekly-plans` | **仅已分配教师**（管理员 403） | 教师：`{term_id, week_number, theme?}` | 新建 201／已存在打开 200（WeeklyPlanDetailOut） |
| `GET /weekly-plans/{id}` | 同班教师或管理员 | 管理员必须 `class_id` 查询参数且与计划一致 | 200 详情：草稿、确认摘要、实时缺失／陈旧清单、`projection_pending`、`source_candidates`、`can_edit`/`can_confirm` |
| `PATCH /weekly-plans/{id}` | 负责人或管理员 | `{expected_draft_version, theme?, deterministic_overrides?, outdoor_game_slots?, focus_area?, weekly_columns?}`；省略字段继承；`source`/`effective` 层不接收 | 200 详情（新草稿版本；不重盖章既有来源引用） |
| `POST /weekly-plans/{id}/refresh-sources` | 负责人或管理员 | `{expected_draft_version}` | 200 详情（新草稿版本 + `refreshed_sources`） |
| `POST /weekly-plans/{id}/confirm` | **仅负责人**（管理员非负责人时 403） | `{expected_draft_version, acknowledge_missing, acknowledge_stale, note?}` | 201 确认版本资源 |
| `GET /weekly-plans/{id}/confirmations` | 同班教师或管理员（只读） | 管理员须 `class_id` 一致 | 200 确认历史列表 |
| `GET /weekly-plans/{id}/confirmations/{version}` | 同上 | 同上 | 200 单个不可变确认版本（未来导出读取面） |

周次合法性：`week_number` 必须在 `1..week_info(term.start_date, term.end_date).week_number`，否则 422；学期不存在 404 `TERM_NOT_FOUND`。有效周包含零上课日的“空周”，允许创建（验证矩阵覆盖）。

**明确不包含**（与 §1.3 一致）：DELETE、recover、AI 触发／立即更新、导出、任务查询、接管接口。

### 5.2 权限矩阵

| 操作 | 访客 | 待分配教师 | 同班其他教师 | 负责人 | 管理员（非负责人） |
| --- | --- | --- | --- | --- | --- |
| 列表／读详情／读确认历史 | 401 | 403 | 200 只读 | 200 | 200（须显式 `class_id`） |
| 创建（不存在时） | 401 | 403 | 允许（成为创建者与负责人） | —（已存在则 200 打开） | **403 FORBIDDEN**（I4 禁止管理员创建；已确认“创建教师是初始负责人”且管理员不可代确认，管理员只能经列表／读取进入并编辑已存在的计划） |
| 保存草稿／刷新 | 401 | 403 | 403 | 允许 | 允许（产生 `editor_role=admin` 版本，确认权仍在负责人） |
| 确认 | 401 | 403 | 403 | 允许 | 403 FORBIDDEN（即便其可编辑） |
| 教师跨班按 id 访问 | — | 403 | 403 | 403 | — |
| 管理员 `class_id` 与计划不符 | — | — | — | — | 404 WEEKLY_PLAN_NOT_FOUND |

### 5.3 状态码语义

| 场景 | 码 / code |
| --- | --- |
| 未登录／会话失效 | 401 AUTH_REQUIRED |
| 无权（非负责人确认、管理员创建、跨班教师、待分配、篡改） | 403 FORBIDDEN |
| 周计划不存在；管理员班级上下文不匹配 | 404 WEEKLY_PLAN_NOT_FOUND |
| 学期不存在 | 404 TERM_NOT_FOUND |
| 草稿版本不符（双标签保存／刷新／确认） | 409 VERSION_CONFLICT |
| 确认时存在缺失或陈旧来源但对应 `ack_missing`／`ack_stale` 未置真 | 409 CONFIRM_ACK_REQUIRED（响应体携带 facts 清单） |
| 结构／判别字段／来源引用非法、周次越界、教师夹带 class_id | 422 VALIDATION_ERROR（等）（空主题**不是**错误，见 U2=B） |
| 指针不一致、同步行不变量破坏、school_settings 缺失 | 503 SERVICE_UNAVAILABLE |
| 创建成功／打开已有；一般写操作 | 201／200；确认 201 |

## 6. 事务与锁协议

### 6.1 锁顺序（在 I3 顺序上扩展，全部 `FOR UPDATE`）

```text
accounts（操作者；多账户按 id 升序） → sessions → teacher_assignments（教师推导班级） →
school_settings → classes（目标班级） → terms → calendar_revisions → calendar_days
（仅当该流程需要日历校验；周计划创建校验周次只需 term 区间） →
weekly_plans → weekly_plan_contents → weekly_plan_confirmations →
daily_plans（本周来源，单条 ORDER BY plan_date, id 的集合 FOR UPDATE，与
weekly_plan_sync_service.load_week_entries 一致；确认流程同序） →
daily_plan_contents（来源当前版本） → weekly_plan_sync_states（仅消费读取时）
```

铁律与既有事实：

- **凡同时涉及两侧的事务，先锁 `weekly_plans` 再锁 `daily_plans`，永不反向。**
- 同班写者的**关键串行点是共享的 `classes` 行**（及其前面的 `school_settings`/`terms`/日历前缀）：I3 日计划保存与 I4 周计划写入都先经过同一前缀，同班并发在进入业务表前已串行。
- **不声称 I3 在全局按 daily id 升序取锁**：I3 更新路径是先锁触发日计划（`_lock_plan`／按日期定位的有效行），再在重算投影时以单条 `ORDER BY plan_date, id` 的 `FOR UPDATE` 集合读取本周其余计划。I4 不依赖“I3 全局 id 升序”这一不存在的保证，两侧交错的防死锁依据是共享班级行串行 + “I4 永远 weekly→daily、同步行永远在日计划之后被取”这两条顺序事实。
- I3 不触碰周计划三表，故与 I3（`... → daily_plans → daily_plan_contents → weekly_plan_sync_states`）无环：I3 持日计划要同步行时，I4 最多持周计划等待日计划；双方对同步行的获取都排在日计划之后。

### 6.2 关键流程与交错结果

| 交错 | 结果 |
| --- | --- |
| 双方并发创建同周 | `classes` 行串行；败者撞唯一键则整事务回滚，重读既有记录 200，创建者不被覆盖 |
| 负责人 PATCH 与另一标签 PATCH | `expected_draft_version` 不符 → 409，本地输入保留，无静默覆盖 |
| 管理员 PATCH 与负责人确认并发 | 双方锁 `weekly_plans` 串行：先确认者成功，管理员后保存产生新草稿版本 → `draft_ahead`，已确认版本不动；先保存者让确认方 409（草稿版本变了），重新读取后再走确认 |
| 确认与日计划保存并发 | 确认持周计划锁后 `FOR UPDATE` 读来源：日计划先提交则确认读到新版本，陈旧清单如实计算；日计划后提交则等待确认提交后再写投影——确认快照是其锁定时刻的真相，不会把旧版本标成最新 |
| 日计划保存与周计划刷新／确认并发 | 共享 `classes` 行先串行化两侧；进入日计划行后，I3 按其既有顺序先锁触发计划再装载本周其余行，I4 以单条 `ORDER BY plan_date, id` 的集合锁读取本周来源——不依赖 I3 全局 id 序；结果反映各自实际读到的已提交版本，无同侧乱序死锁 |
| 任一写入中途失败 | 单事务，草稿版本、指针、确认行、`projection_consumed_at`、操作记录全部回滚，无部分落库 |

### 6.3 确认原子性

确认在一个事务内完成：锁操作者与会话 → 锁周计划 → 锁当前草稿版本并核对 `expected_draft_version` → 以单条 `ORDER BY plan_date, id` 的集合 `FOR UPDATE` 锁全部来源日计划及其当前内容 → 权限（`owner_id`）重验 → 重算缺失与陈旧事实 → 校验确认要件（事实非空时 `ack_missing`／`ack_stale` 必须置真；`note` 可选） → 插入 `weekly_plan_confirmed_contents` → 更新 `current_confirmed_*` 指针 → 操作记录 → 提交。任何一步失败整体回滚；确认版本插入与指针更新不可分离（复合外键 + 同事务保证）。

## 7. 来源变化与确认协议

### 7.1 比较键

- 来源计划级：草稿记录的 `daily_plan_id + content_id + content_version` vs 来源计划当前的 `daily_plan_id + current_content_id + current_content_version`；任一不等即陈旧（`daily_plan_id` 消失或计划不可读 → 缺失）。
- 条目级：`group_id + game_id` 必须仍存在于所记录 `content_id` 对应的内容中（陈旧时同时给出当前 content_id 下是否仍存在）；不存在 → 缺失。
- 重点区域同构（另带 `context_kind`）。
- 确定性栏目：按日期比较 `source.daily_plan_id + source.content_id + source.content_version` 与当前日计划对应值；`override` 不参与来源比较，仅 `effective` 参与空字段缺失判断。

### 7.2 各状态的表示

| 状态 | 草稿读取 | 确认事实 |
| --- | --- | --- |
| 最新 | 记录与当前的 `content_id + content_version` 全等，不出现在清单 | 不入 `stale_sources` |
| 陈旧（content_id／content_version 变化） | 陈旧清单逐条 `{引用, 记录侧与当前侧各自的 content_id/content_version}`；**草稿仍存旧 id／版本／文本** | 入 `facts.stale_sources`，`ack_stale=true` 方可确认 |
| 缺失（来源计划不再可读；为未来删除预留的兼容语义，本轮无删除入口） | 缺失清单 | 入 `facts.missing`（`kind:"source_missing"`） |
| 人工补充 | `source_kind=manual`，日计划引用全空 | 不参与版本比较，永不进入 stale |
| 未填写槽位 | `null` → 槽位缺失 | `facts.missing`（`kind:"outdoor_slot"`） |

### 7.3 不完整／未更新确认

`facts` 固化于确认时刻（U3=A，结构固定）：

```json
{
  "missing": [{"kind": "outdoor_slot|empty_theme|missing_daily_plan_date|empty_field|materials|source_missing", "...": "..."}],
  "stale_sources": [{"slot": "...", "daily_plan_id": "...", "group_id": "...", "game_id": "...",
                     "draft": {"content_id": "...", "content_version": 2},
                     "current": {"content_id": "...", "content_version": 5}}],
  "ack_missing": true,
  "ack_stale": true,
  "note": null
}
```

- 确认接口在锁内**重算**事实，不信任客户端提交的清单；客户端只提交两个 ack 与可选 `note`。
- 路径 C 确认落库的 `content` 快照保留草稿侧旧 `content_id`／`content_version` 与旧整组文本；`facts.stale_sources` 并列记录双侧键——旧来源绝不改写成当前值。
- 事实非空而对应 ack 为 false → 409 `CONFIRM_ACK_REQUIRED` 并回传事实，绝不静默确认、绝不把陈旧来源写成最新。
- 确认后的展示：确认版本旁并列保留“确认时的缺失／陈旧事实”；来源此后再变化产生新的实时清单，与历史事实分列。
- 任务／AI 维度 I4 不存在，UI 不得用一个“状态”标签合并“已确认 + 缺两项 + 来源陈旧”。

### 7.4 双路径落点

确认页检测到陈旧或缺失时，只呈现 U4 定义的 R／C 两按钮；R 走刷新接口回到“可确认”复核态，C 走带 ack 的确认接口。不存在第三条“忽略差异直接确认”路径，也不存在确认接口内的隐式刷新。

## 8. 前端闭环

1. **入口**：教师班级日历／周视图（I2 持久日历）上按周显示“周计划”；点击 `POST /weekly-plans` 创建或打开；列表页作为次入口。仅对属于有效学期的周提供入口，前端不自行推算周次合法性。
2. **详情页分区**：表头（创建时快照）；确认状态区（已确认版本摘要 / 当前草稿版本 / `needs_confirm` / 实时缺失与陈旧清单 / `projection_pending` 横幅）；确定性栏目按日期表格——展示 `effective` 生效值并可编辑写入 `override`（同列显示来源值与是否覆盖标记；缺日计划、空字段、休息日三种显示；重算／刷新不清除覆盖）；三个户外游戏槽位编辑器（选择器按同类别同名聚合、展示多来源与日期，附“手工补充”按钮，来源显示区分日计划／手工）；重点区域选择器；四个手工栏目文本域；材料栏只读显示缺项（无 AI 入口）。
3. **负责人编辑**：PATCH 携带 `expected_draft_version`；409 时本地输入保留、展示服务端版本、仅提供“放弃本地”与“以服务端为基准重提”（再次冲突仍 409），处理期间禁用保存——对齐 I3 已验证交互。
4. **管理员编辑后**：管理员可见保存与刷新、不可见或禁用确认按钮（强发确认 → 403 文案）；保存后 `editor_role=admin`，负责人侧出现“待负责人确认”，已确认版本区仍显示旧版。
5. **同班其他教师**：全页只读，无保存／刷新／确认控件；可查看确认历史与已确认版本（只读，I4 无导出按钮）。
6. **确认前来源变化**：陈旧横幅 + R／C 两按钮（U4 已确认双路径）；C 前强制展示缺失与陈旧清单并逐项勾选 ack，`note` 输入框可选、不阻塞提交。
7. **已确认旧版与新草稿并存**：页面同时呈现已确认版本摘要（可展开只读全文）与当前草稿编辑区，二者版本号分离，刷新草稿不改已确认区。
8. **错误与空态**：401/403/404/409/422/503 中文文案；空周（无日计划）显示全缺项而非报错；加载与提交防重复。不显示删除、恢复、AI、导出、任务入口。

## 9. 最小验证矩阵

| 编号 | 案例 | 通过标准 |
| --- | --- | --- |
| V1 迁移衔接 | 带 I1/I2/I3 数据的隔离库升级；另空库升级 | 三表与两条复合 FK 存在、InnoDB；`operation_records` CHECK 含 `weekly_plan`；I3 同步行零改动；`alembic heads/current` 一致 |
| V2 权限 | 访客、待分配、同班其他教师、负责人、非负责人管理员、跨班、管理员错 class_id 分别打全部 8 条路由 | 状态码与 §5.2 完全一致；管理员创建 403；管理员任何写入后确认仍 403 |
| V3 空周与缺日 | 零日计划的周创建；部分日期缺日计划 | 创建成功；`deterministic` 逐日 `no_plan`/`rest`/`saved` 分立；缺失清单准确；不自动补写 |
| V4 空内容 | 空主题、空栏目、槽位全 null 保存与确认 | 保存成功（主题空不 422）；确认仅在对应 ack 置真后成功；`facts.missing` 含 `empty_theme` 等；内容保持空 |
| V5 重复与并发创建 | 双请求同周创建 | 一份有效记录；一 201 一 200；creator/owner 不被覆盖 |
| V6 同名游戏来源 | 两日同类别同名“跳圈圈”，分别选来源保存与确认 | 单名额；所选 `daily_plan_id/content_id/content_version/group_id/game_id` 与整组文本随来源；改选另一来源后引用与文本整体替换，不混合 |
| V7 草稿版本冲突 | 双标签同时保存／刷新 | 后者 409，本地保留，服务端不被覆盖 |
| V7b 普通保存不重盖章 | 来源已陈旧时仅改主题／手工栏目并 PATCH | 该槽位 `content_id/content_version` 与旧文本不变；仅 refresh 或改选来源才更新；确定性 `override` 在 PATCH／refresh 后保留，`source` 随日计划更新 |
| V8 确认前来源变化 | 打开确认页后另一教师改日计划 | 确认重算出 stale；无 ack → 409 带事实；路径 R 后为最新；路径 C 后 `content` 快照保留旧 content_id／content_version／旧文本，`facts.stale_sources` 记录双侧键且未标最新 |
| V9 管理员编辑后 | 管理员 PATCH 后负责人未确认 | `draft_ahead`；管理员确认 403；原确认版本字节级不变 |
| V10 不完整确认 | 缺一项集体游戏 | 明确确认成功且 `facts.missing` 准确；UI 不显示为“完整” |
| V11 事务回滚 | 确认／创建中注入真实 MySQL 语句错误 | 独立连接验证：确认行、指针、草稿版本、操作记录均无部分写入 |
| V12 重启持久性 | 写入后重建 engine/session | 草稿、指针、确认历史、`projection_consumed_at` 一致可读 |
| V13 上一确认版本不被覆盖 | 确认 V1 后再存草稿、再确认 V2、期间日计划多次变更 | V1、V2 均可按历史接口读取；任何草稿写入不改确认行 |
| V14 投影契约 | 日计划保存后读周计划 | 横幅出现；刷新后消失；同步行仍在且 I3 只读路由与日计划摘要行为不变；I4 全程不写该表 |

## 10. 实施切片与完成条件

按依赖排序；**任何切片都不得自动开始，须用户按片授权**。

| 切片 | 范围 | 完成条件 |
| --- | --- | --- |
| 第一片 数据与事务核心 | 三表模型与迁移、创建／打开（含投影播种）、PATCH、refresh、confirm 服务与锁、事实重算；对应纯单元测试 | 空库与 I3 库 `upgrade head` 成功；服务层单测覆盖 V3–V8、V11 语义（mock 或纯逻辑层），不依赖 HTTP |
| 第二片 API 与权限 | 8 条路由、schema（`extra=forbid`）、错误映射、`source_candidates`；定向路由／权限单测 | 权限矩阵与状态码全绿（mock service）；201/200/403/404/409/422/503 语义固定 |
| 第三片 前端闭环 | §8 全部交互；`npm run typecheck && npm run build` | 构建通过；无 AI／导出／删除入口；409 与双路径交互完整 |
| 第四片 隔离真实验证 | 隔离 MySQL 8.4 / InnoDB 集成测试（V1–V14）+ main 浏览器验证 | 集成零 skip 通过；浏览器按 §8 逐条走通并记录；停止服务与容器 |

## 11. 后续衔接（留接口，不建占位表）

- **Word 导出**：`GET .../confirmations/{version}` 与自包含 `content` 快照即导出读取面；表头直接读创建时快照（U1=A）；不创建导出表或文件表。
- **AI 候选**：草稿人工区与服务端拥有区已分离，候选未来作为独立对象写入“采用流程”，`source_kind` 判别字段预留 `ai` 语义位（I4 校验拒绝）；**不建**候选表、空任务表。
- **持久任务**：ADR 0002 的 30 秒合并触发以后以日计划保存事务登记任务；I4 不建任务表，`weekly_plan_sync_states` 继续作为立即可读的待更新投影被任务切片消费。
- **接管**：`owner_id` 与 `creator_id` 已分列，接管只改 `owner_id` 并暂停自动调用，无需迁移；I4 无接管接口。

## 12. 资源申请清单（第四片已按本清单执行）

第四片（2026-09-23，已授权）实际执行记录；**未沿用 I3 已结束且容器已删除的任何资源**：

1. 隔离 MySQL 8.4 / InnoDB：一次性容器 `kg-next-i4-mysql-20260923-*`，仅 `127.0.0.1` 高位端口，白名单库 `kindergarten_test_i4`／`kindergarten_test_i4_fresh`；独立 guard `backend/tests/integration/i4_guard.py` 拒绝 I1/I2/I3／共享／生产库与非白名单端口；不读 `.env`。凭据仅存在于运行环境，不写入文档或提交。
2. 迁移：`APP_DISABLE_DOTENV=1` + 显式 I4 DSN 下执行 `alembic upgrade head`（空库与带 I1/I2/I3 行的库各一条路径）；`alembic heads` == `alembic current` == `20260924_i4_weekly_plans`。
3. 依赖：无新增 Python／Node 依赖（浏览器验收使用系统已装 Google Chrome + CDP，未安装新包）。
4. 测试：`tests.integration.test_i4_*` 在显式破坏性白名单开关下实际运行，52 项 **0 failure / 0 error / 0 skip**；`skip` 不计通过的规则未被触发。
5. 浏览器：临时 uvicorn + Vite 供 §8 与 R1/R2/R3 验证，结束后停止服务、删除容器。
6. 本清单的“本轮不执行”历史状态自第四片起失效；后续切片仍需按第 10 节逐片授权。

### 12.1 第四片验收后的定向修复（2026-09-24）

第四片最终验收复跑发现并修复一处并发缺陷（post-confirm dirty rebase race）：确认成功后自动读取最新详情并保留本地未保存输入时，若服务端草稿在该读取返回前已被他人推进，旧实现会把 dirty 输入静默重基到新草稿版本，下一次保存可直接以新版本覆盖他人保存而不触发 409。修复仅改 `frontend/src/views/WeeklyPlanView.vue`，区分“服务器展示版本”与“dirty 输入实际基于的 draft version”：确认后状态读取一旦发现版本推进且存在 dirty 输入，即进入显式冲突处理（放弃本地 / 以服务端为基准重提），不再自动重基。未改后端 API、schema、权限、锁协议、U1–U5、迁移与数据库代码；§8.3 冲突语义与本文条款未改。

定向回归（脚本级状态机，复用现有 TypeScript + Vue 运行时，未安装依赖）：Race-R2、R1、R2、R3（仅验证）、OBS-1、OBS-2 共 12 项检查全部通过；`npm run typecheck` 与 `npm run build` 通过。后端 0 修改，故本轮未重跑真实 MySQL V1–V14 与浏览器套件。

## 结束说明

本规格在本范围内**已确认**（U1=A、U2=B、U3=A、U4 双路径、U5=A，2026-09-23）：schema、API、锁协议、确认事实与校验条款可按本文冻结，无遗留待选项（§1.5 表中被拒方案仅作决策留痕）。**四片实施与第四片真实验证已于 2026-09-23 按第 10 节逐片授权完成**：集成 V1–V14 在隔离 MySQL 8.4 / InnoDB 上 0 skip 通过，§8 与 R1/R2/R3 由真实浏览器走通，临时服务与容器已清理；第 10 节第四片完成条件已满足。部署仍未授权；后续切片（Word 导出、AI、提示词、任务队列等）不因本次验证自动开始。
