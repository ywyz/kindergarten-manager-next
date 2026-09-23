# I3 手工日计划保存实施规格

状态：**已确认，I3 实施中（第一片“数据与事务核心”已完成；第二片“API 与权限”实施完成；第三片“前端闭环”（切片 4）已实施；切片 5 真实 MySQL 集成验证已完成——27 项 / 0 skip 通过；main 浏览器验证已完成，未发现新缺陷）**。本规格基于 I1、I2 已确认事实和 Architecture v1 编写。文档中标注“已确认”的条目来自用户在本项目中的明确决定；标注“工程方案”的条目为实施约定，可在不改变产品行为的前提下调整。

**三项范围决定（2026-09-23 用户已确认，阻塞解除）**：

1. **周计划同步范围：选项 A** —— I3 最小扩入真实 `weekly_plan_sync_states`（待确认投影），保存响应/只读接口可立即消费；不扩入完整编辑确认、AI、导出或工作进程。历史讨论：按最初“仅保存日计划并登记未来任务”的边界无法满足 [ADR 0002](../adr/0002-background-tasks-and-versions.md) 对“同事务登记、周计划立即显示待更新、确定性字段进入待确认内容”的要求，选项 B（暂停保存入口）在空表时没有独立产品价值；用户选择 A。
2. **历史表头规则：选项 A** —— 创建日计划时将 `school_name`/`class_name`/`grade`/`creator_display_name` 不可变快照到 `daily_plans` 顶层。
3. **删除/恢复：选项 B** —— 本次延后；I3 不暴露 DELETE/recover/已删除列表入口，schema 仍兼容 `deleted_at`/`deleted_by` 软删除字段。

以下保留原阻塞期讨论作为历史记录；阻塞状态已解除，I3 代码（含 schema/迁移）已获授权实施。

<details>
<summary>历史阻塞声明（已解除）</summary>

1. 按最初“仅保存日计划并登记未来任务”的边界，无法满足 ADR 0002 对“同事务登记、周计划立即显示待更新、确定性字段进入待确认内容”的要求。必须二选一：选项 A（推荐）最小扩入真实 `weekly_plan_sync_states`；选项 B（备选）I3 不开放保存入口。
2. 历史表头姓名/班级资料变更规则为产品未决，需确认快照字段范围。
3. 删除/恢复是否纳入本次 I3 需确认；推荐本次延后，两种入口都不暴露。

在三项决定作出前，整个 I3 代码实现均不可开工，包括 schema/迁移，因为表结构取决于范围 A/B、表头字段及删除恢复决策。

</details>

依据：[ARCHITECTURE.md](../../ARCHITECTURE.md)、[用户与班级 Contract](../modules/identity-and-class.md)、[日计划 Contract](../modules/daily-plans.md)、[周计划 Contract](../modules/weekly-plans.md)、[ADR 0002](../adr/0002-background-tasks-and-versions.md)、[I2 规格](class-assignment-and-calendar.md)、[手工日计划到周计划确认与 Word 导出最小实施规格](manual-plans-and-word-export.md)、[I2 实施与验证记录](../bootstrap/i2-implementation-status.md)。

## 1. 已确认规则

| 规则 | 来源 | 说明 |
| --- | --- | --- |
| 学期不重叠且不共用端点 | [I2 规格](class-assignment-and-calendar.md) P1 | 日计划创建只能发生在唯一学期闭区间内 |
| 年级仅小班、中班、大班 | [I2 规格](class-assignment-and-calendar.md) P2 | 班级 `grade` 值域固定 |
| 班级名称全园唯一，升班保留 ID | [I2 规格](class-assignment-and-calendar.md) P3 | 日计划按班级 ID 归属 |
| 同班同日仅一份有效日计划；重复创建打开已有记录，保留创建者与权限 | [日计划 Contract](../modules/daily-plans.md) | 并发创建也不得产生第二份有效记录 |
| 创建者及管理员可编辑，同班其他教师只读并可导出 | [ARCHITECTURE.md](../../ARCHITECTURE.md)、[日计划 Contract](../modules/daily-plans.md) | 权限在后端重新判定 |
| 内容允许为空，禁止自动补写 | [手工日计划规格](manual-plans-and-word-export.md) | 空内容可保存；导出前提示缺项，确认后保留空栏目 |
| 使用持久化有效日历；管理员明确例外优先于库默认；库未覆盖年份提示就绪后再用 | [身份 Contract](../modules/identity-and-class.md) | 日计划请求不得重新调用库覆盖或改写日历 |
| 普通非上课日及学期外日期不允许直接创建日计划 | [身份 Contract](../modules/identity-and-class.md) | 确需备课由管理员先调整学期或上课日 |
| 保存及受影响周计划更新登记同事务 | [ADR 0002](../adr/0002-background-tasks-and-versions.md) | 不得以内存事件、TODO、空 API 或无效果成功响应代替 |
| 第一次成功创建计划必须同事务设置 `school_settings.plans_started_at` | [I2 规格](class-assignment-and-calendar.md) | 删除全部计划不能清空标记 |
| 保留活动主题、游戏组与游戏标识、原始教案与拆分基准等字段语义 | [手工日计划规格](manual-plans-and-word-export.md) | 不凭模板样例新增必填要求 |
| 周计划不反向改写日计划；AI 候选不覆盖已确认/正在编辑内容 | [周计划 Contract](../modules/weekly-plans.md) | 日计划保存负责同步周计划投影，不执行周计划生成 |
| 删除可恢复；恢复冲突须先处理，不静默覆盖 | [ARCHITECTURE.md](../../ARCHITECTURE.md)、[日计划 Contract](../modules/daily-plans.md) | 产品语义已确认，本次 I3 是否实现见第 4 节 |

## 2. 本轮范围与边界不足

### 2.1 为什么原边界不可作为完成态

- ADR 0002 要求“周计划立即显示待更新，确定性字段同步到待确认内容”。一张未来才消费的 pending 任务表无法让任何接口立即返回待更新状态。
- 占位表合并时若只保留最新来源，会丢失同周其他来源，违反来源保留规则。
- 占位表无法区分“无周计划需新建”与“已有周计划需更新”，也无法判断来源是否过期。
- 因此必须扩入可被当前读取的真实同步状态/投影，或暂停保存入口。

### 2.2 选项 A（推荐）：最小扩入周计划同步投影

I3 交付：

1. 按 I2 持久化有效日历判定日期归属与创建资格。
2. 同班同日唯一的手工日计划创建、读取、保存；重复创建打开已有记录，不改变创建者或内容。
3. 不可变内容版本：`daily_plan_contents` 追加写入，`daily_plans.current_content_id` + `current_content_version` 指向当前版本。
4. 创建者和管理员编辑；同班其他教师只读。
5. 内容版本冲突检测：同一份日计划的并发编辑以版本检测冲突，不静默覆盖。
6. **真实周计划同步投影**：创建/保存日计划时，在同一事务内更新对应班级/学期/周的 `weekly_plan_sync_states` 行；保存响应和只读接口可立即读取“本周待更新/待确认”及来源摘要。
7. 首次成功创建日计划同事务设置 `plans_started_at` 阶段标记。
8. 操作记录写入（`target_type='daily_plan'`）。

### 2.3 选项 B（备选）：暂停保存入口

I3 不开放保存入口，仅完成经用户决定后的 schema/迁移准备。该选项在空表时没有独立产品价值，不等于可交付 I3，只是避免在边界不清时强行实现保存。待周计划最小边界批准后再实施完整保存。

## 3. 不包含项

- 周计划完整编辑、确认、版本替换、AI 生成、材料补充。
- AI 拆分、年龄适宜性调整、其他活动生成。
- Word 导出（单日、范围、合并、标红）。
- 个人 AI 配置、个人提示词编辑器、提示词适配。
- 持久任务工作进程、任务领取与执行、重启恢复。
- 调班、停用/启用、接管、班级/学期配置变更及其影响处理。
- 账号管理、班级/学期维护（已在 I1/I2 交付）。

## 4. 范围调整选项与真正未决项（三项均已决定，表格保留为历史讨论）

2026-09-23 用户确认：范围选 **A**；历史表头选 **A**；删除/恢复选 **B**。以下表格保留原选项与推荐，供追溯，不再阻塞实施。

### 4.1 范围调整选项 1：周计划同步状态（已决定：A）

| 选项 | 说明 | 影响 | 推荐 |
| --- | --- | --- | --- |
| A. 最小扩入周计划同步投影 | I3 创建 `weekly_plan_sync_states` 表，保存班级+学期+周的待确认投影、完整来源清单、状态标记；保存/删除日计划时同事务更新 | 增加 1 张表和 1 个服务方法，不实现 AI/确认/导出；I3 保存接口可开放 | **推荐** |
| B. 暂停保存入口 | I3 只准备 schema/迁移，不开放写入口，不设置 `plans_started_at`，不联动周计划 | 无产品功能；必须等待后续切片批准 | 备选 |

### 4.2 范围调整选项 2：删除/恢复是否纳入本次 I3（已决定：B）

| 选项 | 说明 | 影响 | 推荐 |
| --- | --- | --- | --- |
| A. 纳入 I3 | 提供软删除、恢复及恢复冲突处理闭环 | 增加 DELETE/recover API、冲突交互、测试 | 备选 |
| B. 本次延后 | I3 不暴露 DELETE/recover/list-deleted 入口；schema 兼容软删除 | 保存接口可先行；删除恢复留到后续切片 | **推荐** |

### 4.3 历史表头规则（已决定：A）

| 项 | 选项 | 结果 |
| --- | --- | --- |
| 历史表头姓名/班级资料变更规则 | A. 创建日计划时快照班级资料到计划身份；B. 读取/导出时按当前班级资料；C. 引入独立表头版本表 | **A（已确认）**：在 `daily_plans` 创建时记录不可变快照（school_name、class_name、grade、creator_display_name），满足“历史计划保留原班级”语义，schema 影响最小。后续如需版本化可迁移而不破坏数据。 |

## 5. 完整字段映射及 Schema 草案

### 5.1 字段映射

| 业务栏目 | Schema 位置 | 可空 |
| --- | --- | --- |
| 日期、周次、星期、学期、班级、创建教师 | `daily_plans` 顶层 | 否 |
| 原始教案（完整文本） | `daily_plan_contents.raw_lesson_plan` | 是；手工可输入 |
| 拆分基准（AI 拆分后的结构化基准） | `daily_plan_contents.split_baseline` | 是；无 AI 拆分时为 `null`；I3 服务端写入 |
| 最终采用结构化内容 | `daily_plan_contents.adopted_content` | 可空整体及各字段 |
| 当前内容指针 | `daily_plans.current_content_id` + `current_content_version` | 非空（提交后） |
| 班级/园所资料快照 | `daily_plans` 顶层（创建时不可变） | 否 |
| 删除状态 | `daily_plans.deleted_at` / `deleted_by` | 可空 |

### 5.2 `daily_plans` 表

```text
id: String(32, utf8mb4_bin) PK
class_id: String(32, utf8mb4_bin) FK classes.id, index
term_id: String(32, utf8mb4_bin) FK terms.id, index
plan_date: Date, index
creator_id: String(32, utf8mb4_bin) FK accounts.id
week_number: Int
weekday: Int

-- 当前内容指针：必须指向本计划的 daily_plan_contents 行
current_content_id: String(32, utf8mb4_bin) FK daily_plan_contents.id
current_content_version: Int

-- 创建时不可变资料快照
creator_display_name: String(80) nullable   -- 创建时教师 display_name
school_name: String(120) nullable          -- 创建时园所名称
class_name: String(80)                     -- 创建时班级名称
grade: String(20)                          -- 创建时班级 grade

-- 删除状态（若本次纳入）
deleted_at: DateTime nullable
deleted_by: String(32, utf8mb4_bin) FK accounts.id nullable

created_at: DateTime
updated_at: DateTime
```

唯一性：

```sql
effective_date DATE GENERATED ALWAYS AS (
    CASE WHEN deleted_at IS NULL THEN plan_date END
) STORED
UNIQUE KEY uq_daily_plans_class_effective_date (class_id, effective_date)
```

- 有效记录 `effective_date = plan_date`；已删除记录为 `NULL`。
- MySQL 唯一索引允许多个 `NULL`，因此同一日期可存在多条删除历史，但仅一条有效记录。

当前内容指针约束：

```sql
-- daily_plan_contents 表
UNIQUE KEY uq_daily_plan_contents_plan_id_version (
    daily_plan_id, id, version
)

-- 迁移中先建两表，再用 ALTER 添加复合外键，避免循环建表顺序问题
ALTER TABLE daily_plans
ADD CONSTRAINT fk_daily_plans_current_content
FOREIGN KEY (id, current_content_id, current_content_version)
REFERENCES daily_plan_contents (daily_plan_id, id, version);
```

说明：

- `daily_plan_contents` 使用全局唯一的 `id` 作为主键，同时建立 `(daily_plan_id, id, version)` 的唯一索引，供 `daily_plans` 的复合外键引用。
- `daily_plans.current_content_id` 和 `current_content_version` 在创建事务中可暂空（nullable），以便先插入 `daily_plans`、再插入第一个内容版本、最后更新指针。
- 指针更新后、提交前，应用层断言 `current_content_id` 与 `current_content_version` 非空，且指向刚刚插入的内容版本行。
- 数据库复合外键保证：任何非空指针必须对应 `(daily_plan_id, id, version)` 存在的行，即指针一定属于本计划。
- 公开读取到空指针视为数据不完整错误（503 SERVICE_UNAVAILABLE）。

创建事务流程：

1. 插入 `daily_plans`，此时 `current_content_id` 和 `current_content_version` 暂空。
2. 插入 `daily_plan_contents` 版本 1。
3. 更新 `daily_plans.current_content_id` 和 `current_content_version` 为新插入行的 `id` 和 `version`。
4. 应用层断言指针非空且匹配；提交事务。

### 5.3 `daily_plan_contents` 表

```text
id: String(32, utf8mb4_bin) PK
daily_plan_id: String(32, utf8mb4_bin) FK daily_plans.id, index
version: Int           -- 从 1 递增，同一 daily_plan 内唯一
raw_lesson_plan: Text nullable   -- 可手工输入；I3 PATCH 可修改
split_baseline: JSON nullable    -- AI 拆分基准；I3 不接受客户端写入；无 AI 时为 null
adopted_content: JSON            -- 最终采用结构化内容，允许空对象
editor_id: String(32, utf8mb4_bin) FK accounts.id
created_at: DateTime

UNIQUE KEY (daily_plan_id, id, version)
UNIQUE KEY (daily_plan_id, version)
```

追加写入，不原地更新。来源引用精确路径：`daily_plan_id + content_version + adopted_content.group_id + adopted_content.game_id`。

### 5.4 内容 JSON 结构（`adopted_content`）与校验

```json
{
  "morning_exercise_label": "体能大循环",
  "morning_games": [
    {
      "group_id": "<server-generated>",
      "group_kind": "collective",
      "games": [{"game_id": "<server-generated>", "name": ""}],
      "focus_guidance": "",
      "shared_objectives": "",
      "guidance_points": ""
    }
  ],
  "morning_talk": {"topic": "", "questions": ""},
  "group_activity": {"theme": "", "objectives": "", "preparation": "", "key_points": "", "difficult_points": "", "process": ""},
  "post_group_games": [
    {
      "group_id": "<server-generated>",
      "context_kind": "area",
      "area": "",
      "games": [{"game_id": "<server-generated>", "name": ""}],
      "focus_guidance": "", "objectives": "", "guidance": "", "support_strategy": ""
    }
  ],
  "afternoon_outdoor": {
    "group_id": "<server-generated>",
    "area": "",
    "games": [{"game_id": "<server-generated>", "name": ""}],
    "observation_focus": "", "objectives": "", "guidance": "", "support_strategy": ""
  },
  "reflection": ""
}
```

校验规则：

- `morning_games` 中 `group_kind` 仅允许 `collective` 或 `free_choice`。
- **晨间最多一个 `collective` 组和一个 `free_choice` 组**；可零个、一个或两个，不可超过。
- `post_group_games` 每组在对象出现时必须提供 `context_kind`（上下文类型），仅允许 `area`/`outdoor`/`special_room`（室内区域／户外／专用室），与已确认字段映射“集体活动后游戏类型”对应；缺失或取值域外即校验失败，不静默兼容。
- 下午户外的“重点观察”字段为 `observation_focus`，不使用 `focus_guidance`；`focus_guidance` 仅属于晨间组与集体活动后各组。
- `group_id`、`game_id` 由服务端为新对象生成；更新时保留未替换对象的原有 ID；拒绝客户端传入不存在的 ID、重复 ID、跨计划引用 ID 或擅自修改已有 ID。
- 允许整份 `adopted_content` 为空对象 `{}`，允许任何数组为空、任何文本字段为空字符串；不自动补写默认值。
- “自主游戏”与“自选游戏”统一为 `free_choice`，导出时保留模板名称。
- 多个游戏共用目标/指导时存为同一 `group`。
- Pydantic schema 使用 `extra="forbid"`，拒绝未知字段。

### 5.5 `split_baseline` 结构

```json
{
  "generated_at": "2026-09-22T10:00:00Z",
  "group_activity_process": "...",
  "compared_fields": ["group_activity.process"]
}
```

- I3 不接受客户端写入 `split_baseline`；仅在未来 AI 拆分服务生成后由服务端写入。
- 无 AI 拆分时为 `null`；导出标红以 `split_baseline` 与最终内容差异为依据；无基准时不标红并提示无法比较。

### 5.6 推荐方案：周计划同步投影表 `weekly_plan_sync_states`

**重要**：该表不是正式周计划表，不决定未来正式周计划的创建者/负责人。它仅保存“某班级某学期某周的待确认投影”，供 I3 保存响应和只读接口立即消费。

```text
id: String(32, utf8mb4_bin) PK
class_id: String(32, utf8mb4_bin) FK classes.id, index
term_id: String(32, utf8mb4_bin) FK terms.id, index
week_number: Int
status: String(20) CHECK IN ('pending_projection')  -- I3 仅 pending_projection
-- 确定性待确认投影
deterministic_themes: JSON      -- [{date, morning_talk_topic, group_activity_theme}]
game_source_manifest: JSON      -- [{daily_plan_id, content_version, date, group_id, game_id, context_kind}]
                                 -- context_kind 取 post_group_games 组的 area/outdoor/special_room；晨间组与下午户外为 null
-- 本周完整来源清单，重算后不丢失
current_week_source_manifest: JSON  -- [{daily_plan_id, current_content_id, current_content_version, date}]
-- 最后触发来源（仅审计元数据）
last_trigger_daily_plan_id: String(32) FK daily_plans.id nullable
last_trigger_content_version: Int nullable
last_trigger_event: String(20) CHECK IN ('create', 'update', 'delete') nullable
updated_at: DateTime
created_at: DateTime
```

唯一性：`UNIQUE(class_id, term_id, week_number)`。

**无正式周计划时**：保存日计划后插入/更新该行，前端读取到 `pending_projection`，显示“本周待更新/待确认”及已保存日期来源摘要。

**已有正式周计划时（选项 A 的范围代价）**：`weekly_plan_sync_states` 仍只保存确定性待确认投影和来源清单，标记正式周计划内容已 stale；不保存也不覆盖正式周计划的确认内容/人工内容。若需要支撑“已有周计划”语义，最小字段为 `confirmed_exists BOOL` 和 `confirmed_snapshot JSON`（上一确认版本快照），明确这是选项 A 为兼容已有周计划而增加的代价，仍不开放编辑/确认入口。

**不保留**：指向不存在周内容版本表的 `current_confirmed_content_version` 或 FK 到不存在的 `weekly_plans` 表。

### 5.7 资料快照字段边界

`daily_plans` 创建时记录：

- `creator_display_name`：创建教师当时姓名（日计划表头显示用）。
- `school_name`：当时园所名称。
- `class_name`：当时班级名称。
- `grade`：当时班级年级。

**不纳入**：`header_teacher_names`、`caregiver_name`。这些属于周计划表头来源，是否需要在日计划快照中保留为产品未决；当前推荐不纳入，避免自行扩大范围。

快照在创建后不可变；内容版本只保存内容，不重复保存资料快照。

## 6. 数据约束、迁移设计及现有数据保护

### 6.1 数据约束

| 约束 | 实现方式 |
| --- | --- |
| 同班同日最多一条有效日计划 | 生成列 `effective_date` + 唯一索引 `(class_id, effective_date)` |
| 日期必须在学期范围内且为上课日 | 锁内重验 `calendar_days` 当前修订的 `effective_state='teaching'` |
| 内容版本追加、指针可执行 | `daily_plan_contents` 有 `UNIQUE(daily_plan_id, id, version)`；`daily_plans` 有复合 FK `(id, current_content_id, current_content_version)` 指向该三列；应用层提交前断言指针非空 |
| 班级/学期/账号存在 | 外键约束；锁内重验启用状态与角色 |
| 删除后保留记录 | `deleted_at` 可空；删除更新 `deleted_at` 和 `deleted_by` |
| 拒绝未知结构 | Pydantic `extra="forbid"` |

### 6.2 迁移设计

新增迁移文件，置于 I2 日历迁移之后：

1. 创建 `daily_plans` 表（含 `effective_date` 生成列、资料快照字段、当前内容指针；`current_content_id`/`current_content_version` 先 nullable）。
2. 创建 `daily_plan_contents` 表（含 `(daily_plan_id, id, version)` 唯一索引）。
3. `ALTER TABLE daily_plans ADD CONSTRAINT fk_daily_plans_current_content FOREIGN KEY (id, current_content_id, current_content_version) REFERENCES daily_plan_contents(daily_plan_id, id, version)`，避免两表循环建表顺序问题。
4. 若选项 A：创建 `weekly_plan_sync_states` 表。
5. 扩展 `operation_records.target_type` CHECK 值域，加入 `'daily_plan'`。
6. 不修改 I1/I2 已有表数据；`school_settings.plans_started_at` 保持 nullable。

### 6.3 现有数据保护

- 不删除、不截断 I1/I2 表。
- 不修改账号、班级、学期、日历修订数据。
- `plans_started_at` 仅由 I3 保存服务在第一次成功创建日计划时设置；删除全部计划不清空。

### 6.4 删除/恢复边界（已决定：B，本次延后）

- **已确认延后（选项 B）**：I3 不暴露 `DELETE /daily-plans/{id}`、`POST /daily-plans/{id}/recover`、已删除列表等入口。`deleted_at`/`deleted_by` 字段预留，schema 兼容软删除，但 API/权限/事务/验证完成条件中不包含删除，服务层也不实现 DELETE/recover。
- **历史讨论（选项 A，未采纳）**：若纳入 I3，需补全软删除、恢复及恢复冲突交互，并在保存/删除事务中同步 `weekly_plan_sync_states`。恢复时若同班同日已存在有效记录，返回 `DAILY_PLAN_RECOVER_CONFLICT`，要求显式处理。留待后续切片。

## 7. API 与权限矩阵

### 7.1 路由与输入

| 方法/路由 | 权限 | 输入 | 成功输出 |
| --- | --- | --- | --- |
| `GET /daily-plans` | 同班教师或管理员 | 教师：仅 `from`, `to`, `offset`, `limit`；管理员：必须 `class_id` + 同上 | DailyPlanListOut |
| `GET /daily-plans/by-date` | 同班教师或管理员 | 教师：仅 `plan_date`；管理员：必须 `class_id` + `plan_date` | 200 DailyPlanOut 或 404 |
| `POST /daily-plans` | 已分配本班教师或管理员 | 教师：仅 `{plan_date, raw_lesson_plan?, adopted_content?}`；管理员：必须 `class_id` + 同上 | 201/200 DailyPlanOut |
| `GET /daily-plans/{id}` | 同班教师或管理员 | 教师：无（不得传 `class_id`/`term_id`）；管理员：必须 `class_id` 查询参数且与计划班级一致 | 200 DailyPlanOut |
| `PATCH /daily-plans/{id}` | 创建者或管理员 | `{raw_lesson_plan?, adopted_content?, expected_content_version}`；`split_baseline` 不接受 | 200 DailyPlanOut |
| `GET /weekly-plan-sync-states/{class_id}/{term_id}/{week_number}` | 同班教师或管理员 | 路径参数 | WeeklyPlanSyncStateOut（仅选项 A） |

**教师请求不传 `class_id`/`term_id`**；服务端从 `teacher_assignments` 和持久日历推导。

**管理员请求必须传 `class_id`**；`term_id` 仍由服务端根据 `plan_date` 推导。管理员 `GET /daily-plans/{id}` 同样必须携带 `class_id` 查询参数：与计划实际班级不一致时返回 404 `DAILY_PLAN_NOT_FOUND`，不得仅凭 ID 跨班读取（第二片实施语义，教师跨班按 403 `FORBIDDEN`）。

**同步投影读取不到时**（`GET /weekly-plan-sync-states/...` 无对应行）返回 404 `WEEKLY_PLAN_SYNC_NOT_FOUND`——第二片选择的一致工程语义为明确 404，而非可解释空态；日计划自身的 `weekly_sync_state` 摘要在计划存在但投影行缺失时按 503 `SERVICE_UNAVAILABLE` 处理（同事务不变量被破坏）。

**暂不包含**（除非用户明确纳入删除恢复）：

- `DELETE /daily-plans/{id}`
- `POST /daily-plans/{id}/recover`
- 已删除列表接口

### 7.2 PATCH 版本继承规则

- `raw_lesson_plan` 可选：提供则更新；不提供则继承当前版本值。
- `adopted_content` 可选：提供则整体验证并替换；不提供则继承当前版本值。
- `split_baseline` 不接受客户端写入；继承当前版本值或保持 `null`。
- 无论是否变化，保存操作追加新版本，刷新 `updated_at`。

### 7.3 响应模型

```text
DailyPlanOut:
  id, class_id, term_id, plan_date, week_number, weekday,
  creator_id, creator_display_name,
  current_content_id, current_content_version,
  content: {
    id, version, raw_lesson_plan?, split_baseline?, adopted_content,
    editor_id, created_at
  },
  school_name, class_name, grade,
  weekly_sync_state: {           -- 仅选项 A，当前周待确认投影摘要
    status,
    has_pending_projection,
    saved_dates: [date],
    missing_dates: [date]
  },
  created_at, updated_at

DailyPlanListItemOut:
  id, plan_date, week_number, weekday,
  creator_id, creator_display_name,
  current_content_version, created_at, updated_at

DailyPlanListOut:
  items, total, offset, limit
```

### 7.4 权限矩阵

| 操作 | 访客/待分配 | 同班其他教师 | 创建者 | 管理员 |
| --- | --- | --- | --- | --- |
| 创建某日计划 | 401/403 | 允许 | 允许 | 允许（需指定 class_id） |
| 读取某日计划/列表/by-date | 401/403 | 只读 | 只读 | 只读 |
| 编辑内容 | 403 | 403 | 允许 | 允许 |
| 删除/恢复 | 无入口 | 无入口 | 无入口 | 本次 I3 不开放 |

### 7.5 错误响应

| 场景 | 状态码 | code |
| --- | --- | --- |
| 未登录/会话失效 | 401 | AUTH_REQUIRED |
| 非本班教师/非管理员 | 403 | FORBIDDEN |
| 教师传入 class_id/term_id | 422 | VALIDATION_ERROR |
| 日期在学期外 | 422 | OUTSIDE_TERM |
| 日期非上课日 | 422 | DATE_NOT_ELIGIBLE |
| 日期日历数据未就绪 | 422 | YEAR_NOT_COVERED |
| 同班同日并发创建唯一冲突 | 事务回滚后读取已有记录返回 200，不覆盖 |
| 内容版本冲突 | 409 | VERSION_CONFLICT |
| 日计划不存在 | 404 | DAILY_PLAN_NOT_FOUND |
| 当前内容指针为空 | 503 | SERVICE_UNAVAILABLE |
| 数据库/迁移未就绪 | 503 | SERVICE_UNAVAILABLE |

## 8. 事务协议

### 8.1 锁顺序

```text
accounts（操作者，按 ID 升序；如需锁创建者则一并加入） →
sessions（操作者） →
school_settings →
classes（目标班级） →
terms（目标学期） →
calendar_revisions（目标学期当前修订） →
calendar_days（目标日期） →
daily_plans（目标记录，若存在） →
daily_plan_contents（追加新版本） →
weekly_plan_sync_states（同班级学期周，仅选项 A）
```

### 8.2 创建流程

1. 输入校验：`plan_date` 为 `YYYY-MM-DD`；教师请求不得含 `class_id`/`term_id`；管理员请求必须含 `class_id`。
2. 鉴权并推导 `class_id`：
   - 教师：从 `teacher_assignments` 读取当前归属；无归属则 403。
   - 管理员：校验其为管理员，使用请求中的 `class_id`。
3. 开启事务，按锁顺序锁定。
4. 重验班级/学期存在、账号启用、管理员身份。
5. 日期资格校验（锁内）：
   - 锁 `school_settings`、`classes`、`terms`、`calendar_revisions`、`calendar_days`。
   - 确认目标日期 `effective_state='teaching'`。
   - 同时校验 `term.version`、`calendar_revision_id` 未变。
6. 检查 `daily_plans` 是否已存在 `(class_id, plan_date)` 有效记录：
   - 存在：回滚事务，返回该记录 200。
   - 不存在：继续创建。
7. 首次创建阶段标记：若 `plans_started_at` 为 `null`，设置为当前 UTC 时间。
8. 读取当前资料快照：`school_name`、`class_name`、`grade`、`creator_display_name`。
9. 插入 `daily_plans`，`current_content_id` 暂空。
10. 插入 `daily_plan_contents` 版本 1：
    - `raw_lesson_plan` 来自请求或 `null`。
    - `split_baseline` 为 `null`（I3 无 AI 拆分）。
    - `adopted_content` 来自请求或空对象。
11. 更新 `daily_plans.current_content_id` 和 `current_content_version`。
12. 若选项 A：更新 `weekly_plan_sync_states` 待确认投影和完整来源清单。
13. 写入操作记录：`target_type='daily_plan'`，`action='create_daily_plan'`。
14. 提交前断言 `current_content_id` 非空。
15. 提交事务。

### 8.3 保存（更新）流程

1. 鉴权：创建者或管理员。
2. 按锁顺序锁定日计划及相关对象。
3. 校验日计划存在且未删除；`expected_content_version` 必须等于 `current_content_version`，否则 409。
4. 确定新版本字段：
   - `raw_lesson_plan`：请求提供则用，否则继承当前版本。
   - `adopted_content`：请求提供则用并校验，否则继承当前版本。
   - `split_baseline`：继承当前版本（I3 不接受客户端写入）。
5. 追加写入 `daily_plan_contents` 新版本，`version = current_content_version + 1`。
6. 更新 `daily_plans.current_content_id` 和 `current_content_version`、`updated_at`。
7. 若选项 A：更新 `weekly_plan_sync_states`。
8. 写入操作记录：`action='update_daily_plan'`。
9. 提交事务。

### 8.4 首次计划与配置确认的竞争

| 顺序 | 结果 |
| --- | --- |
| 日计划创建事务先获得 `school_settings` 锁 | 配置确认事务随后获得锁，读取到 `plans_started_at IS NOT NULL`，受影响的非 `class_create`/`term_create` 操作返回 `DEPENDENCY_NOT_READY` |
| 配置确认事务先获得 `school_settings` 锁并提交 | 日计划创建事务随后获得锁，可能发现 `term.version`、`calendar_revision_id` 或 `calendar_days.effective_state` 已改变；保存服务锁内重验，若日期不再 eligible 则返回对应错误并回滚 |

### 8.5 失败回滚

所有写入必须在同一事务。任何失败全部回滚，不得部分落库。

## 9. 前端闭环

### 9.1 教师路径

1. 选择日期：从日历视图选择 `date_eligible=true` 的日期。
2. 打开：`POST /daily-plans` 仅携带 `plan_date`。
3. 编辑：创建者或管理员可编辑；同班其他教师只读。
4. 保存：`PATCH /daily-plans/{id}` 携带 `expected_content_version`。
5. 冲突 409：保留本地输入，展示服务端最新版本，用户手动合并/替换后携带最新 `expected_content_version` 再提交；再次冲突仍 409，不提供无条件覆盖。
6. 保存响应/列表响应中（选项 A）显示“本周待更新/待确认”及已保存/缺日摘要。

### 9.2 管理员路径

- 管理员选择班级后，按班级/日期定位日计划。
- 管理员保存同样触发内容版本追加和周计划投影更新。

## 10. 最小验证矩阵

| 编号 | 案例 | 通过标准 |
| --- | --- | --- |
| V1 迁移衔接 | 带 I1/I2 数据的隔离库升级到 I3；另空库建立 | 新增表存在；旧数据保留；InnoDB、FK、唯一索引可查 |
| V2 权限 | 访客、待分配教师、同班其他教师、创建者、管理员分别尝试创建/读取/编辑 | 状态码与权限矩阵一致；教师不得传入 class_id/term_id |
| V3 空内容保存 | 创建时 `adopted_content={}`；保存后读取 | 保存成功；内容为空；不自动补写 |
| V4 日期限制 | 学期外、非上课日、未知年份日期尝试创建 | 返回对应错误码；不写记录 |
| V5 同班同日唯一性 | 两个教师并发创建同班同日 | 仅一条有效记录；失败事务回滚后返回已有；不覆盖创建者/内容 |
| V6 日历竞态 | 保存事务执行期间，另一事务修改学期/日历 | 保存事务锁内重验失败，回滚；无部分写入 |
| V7 内容版本冲突 | 双标签页同时编辑同一份日计划 | 后保存者 409；服务端数据不被覆盖；前端保留本地输入并需用户合并后重提 |
| V8 事务回滚 | 保存后注入真实 MySQL 语句错误 | 独立连接验证：日计划、内容版本、周计划投影、操作记录、plans_started_at 均无部分写入 |
| V9 重启持久性 | 保存后停止并重新启动 API/数据库 | 数据完整；内容版本可回溯 |
| V10 周计划同步投影 | 若选项 A：保存日计划后立即读取同步状态 | 同班级学期周存在 pending_projection；来源清单完整；多次保存不丢失各日来源 |

若删除恢复纳入 I3，再补充 V11 删除/恢复验证。

**V9 与 §8.4 两种提交顺序的集成用例已在真实 MySQL 8.4 / InnoDB 上运行并通过**（`backend/tests/integration/test_i3_daily_plan.py`，切片 5，2026-09-23）：

- V9 重启持久性：创建+保存后处置当前 engine/session 单例，用全新 engine/session factory 模拟重启读取，断言计划、当前内容版本、周计划同步投影、`plans_started_at` 持久且读取不重算/覆盖 I2 日历。
- §8.4 顺序 1：创建先取得 `school_settings` 锁并提交后，已存在的 `school_update` 确认按既有门槛以 `DEPENDENCY_NOT_READY` 拒绝，计划与 marker 保留、配置不应用。
- §8.4 顺序 2：`calendar_override`（将计划日改为非上课日）确认先取得锁并提交后，创建锁内读取已提交新日历并以 `DATE_NOT_ELIGIBLE` 明确业务拒绝，无死锁、无部分写。

三例均调用真实服务入口与 `FOR UPDATE` 锁（线程独立 session；对竞争方所调用模块的 `lock_school` 包一层 wrapper，在进入真实 `lock_school` 前设置 `attempting`、真实 `lock_school` 返回后设置 `acquired`，主线程在持锁方 release 前断言 `attempting` 已发生且 `acquired` 在短超时内未发生，release 后再断言 `acquired` 与最终服务结果；不查询 `information_schema`、不要求额外 `PROCESS` 权限；超时/错误证据保留 `events`/`results`），**已随切片 5 授权在隔离 MySQL 上执行并通过**。

**main 浏览器验证（2026-09-23，本地隔离 MySQL 8.4.11）已完成**，覆盖第 9 节前端闭环的浏览器侧通过标准：

- UI 建立 2026-09 学期日历。
- 教师 2026-09-23 创建空计划为内容版本 v1，详情显示当前周 `pending_projection`。
- 完整代表性栏目保存为 v2，刷新并重新打开后全部内容持久，重开后的服务端内容中稳定 `group_id`/`game_id` 也保留。
- 外部会话将内容更新至 v3 后，浏览器持有旧 v2 的保存真实触发 409：本地输入保留并展示服务端内容，显式重提交成功至 v4。
- 同班非创建者打开该计划：全字段 disabled，页面无保存/删除入口。
- 浏览器验证未发现新缺陷。集成测试结束时曾保留一次性容器 `kg-next-i3-mysql-20260923` 供 main 浏览器验证，此为历史事实；main 完成浏览器验证并停止 API/Vite 后，该容器已删除，容器内测试数据不可恢复。账号密码、DSN、cookie、容器密码均不写入本文档；本补记不改写上述集成验证的历史范围。

## 11. 实施切片及完成条件

三项范围决定已于 2026-09-23 由用户确认（周计划同步 A、历史表头 A、删除/恢复 B），阻塞解除；I3 代码实现（含 schema/迁移）已获授权。当前第一片“数据与事务核心”（切片 1 + 切片 2）已完成（OpenCode 实施、main 定点修复，48 项 I3 纯单元测试通过）；第二片“API 与权限”（切片 3）已实施并通过定向纯单元测试；第三片“前端闭环”（切片 4）已实施（`npm run typecheck`、`npm run build` 通过；无现有前端测试设施，未安装新依赖；未启动 Vite/浏览器，真实 MySQL 集成与浏览器点击验证仍归切片 5）。

### 切片 1：Schema 与迁移（第一片，已完成）

- 创建 `daily_plans`（含 `effective_date` 生成列、资料快照、当前内容指针；`current_content_id`/`current_content_version` 先 nullable）。
- 创建 `daily_plan_contents`（含 `UNIQUE(daily_plan_id, id, version)` 和 `UNIQUE(daily_plan_id, version)`）。
- `ALTER TABLE daily_plans ADD CONSTRAINT fk_daily_plans_current_content FOREIGN KEY (id, current_content_id, current_content_version) REFERENCES daily_plan_contents(daily_plan_id, id, version)`。
- 若选项 A：创建 `weekly_plan_sync_states`。
- 扩展 `operation_records.target_type` CHECK，仅加入 `'daily_plan'`。
- 更新 `models.py`。
- 完成条件：迁移在空库和 I2 数据上均可 `alembic upgrade head` 成功，表引擎 InnoDB。

### 切片 2：服务与事务核心（选项 A，第一片，已完成）

- 实现日计划创建/读取/保存服务。
- 锁内重验日历行。
- 实现锁顺序、阶段标记、周计划投影同步、操作记录。
- 完成条件：服务层单元测试覆盖正常路径、版本冲突、日期限制、日历竞态、周计划投影；不依赖 HTTP。

### 切片 3：API 与权限（第二片，已实施）

- 新增 `routers/daily_plans.py`；若选项 A，新增 `routers/weekly_plan_sync_states.py` 只读路由。
- 新增 Pydantic schemas（`extra="forbid"`）。
- 在 `main.py` 注册路由。
- 完成条件：接口测试验证权限矩阵和错误码；重复创建返回已有；版本冲突返回 409。
- **第二片交付事实（2026-09-23）**：五条日计划路由（列表、by-date、创建/打开、by-id、PATCH，无 DELETE/recover/已删除列表）与同步投影只读路由已注册；请求/响应 schema 全部 `extra="forbid"`；每个请求后端重新判定权限（访客 401、待分配 403、教师仅本班、创建者与管理员可 PATCH、管理员读取/创建/列表必须显式 `class_id`）；错误码按第 7.5 节映射，新建 201 / 重复创建 200 / 版本冲突 409；创建、保存与读取响应均包含当前周 `weekly_sync_state` 摘要（`saved_dates` 来自投影 manifest，`missing_dates` 为该周上课日缺日）以及完整同步投影字段（`pending_projection`、确定性主题、完整游戏来源、完整 current-week source manifest、最后触发摘要）。定向纯单元测试 `tests/unit/test_i3_api_schemas.py`、`tests/unit/test_i3_api_routes.py` 及投影摘要用例通过（mock service/依赖，不连接数据库）；真实 MySQL 接口集成验证归切片 5，本片未执行。

### 切片 4：前端闭环（第三片，已实施；浏览器验证已由 main 完成，见切片 5 补记）

- 教师日历页面增加“创建日计划”入口。
- 日计划编辑/只读页面。
- 版本冲突保留本地输入、展示服务端版本、用户合并后重提交。
- 若选项 A：显示本周待更新/待确认及来源摘要。
- 完成条件：浏览器可完成选日期→打开/创建→编辑→保存→读取的流程。
- **第三片交付事实（2026-09-23）**：教师日历（`TeacherView.vue`）仅对 I2 持久日历返回 `date_eligible=true` 的日期提供“打开日计划”入口，前端不调用日历库、不推断日期资格；`DailyPlanView.vue` 先 `GET /daily-plans/by-date`，404 时展示明确创建确认，`POST`（仅 `plan_date`，教师路径不传 `class_id`/`term_id`）后打开详情，重复创建的 200 直接打开已有记录。手工表单覆盖已确认栏目：固定显示“体能大循环”（仅界面固定展示，不向 `adopted_content` 自动写默认值；表单模型不新增编辑控件，`serverToForm` 只带入服务端已有的 `morning_exercise_label` 并在保存时原样回写，`emptyContentForm` 不持有该值，空表单 `buildAdoptedContent` 返回 `{}`）；晨间最多一个 collective 组与一个 free_choice 组（组内游戏、重点指导、共用目标、指导要点）；晨间谈话（话题/问题设计）；集体活动（主题/目标/准备/重点/难点/过程）；集体活动后 area/outdoor/special_room 游戏组；下午户外（区域、游戏、重点观察/目标/指导/支持策略）；反思；可选 `raw_lesson_plan`。所有栏目允许留空，载荷不为未触碰的空白栏目自动补写结构；`group_id`/`game_id` 由服务端生成，保存后采用响应内容保留返回 ID。权限：创建者与管理员可编辑，同班其他教师只读且页面不显示保存控件；无删除/恢复入口。详情显示 `weekly_sync_state`（pending 状态、`saved_dates`、`missing_dates`），文案明确其为待确认投影而非正式周计划确认、本环节未运行 AI。`PATCH` 携带 `expected_content_version`；409 时保留本地 `raw_lesson_plan`/`adopted_content`，读取服务端最新版本并展示版本差异与服务端内容，仅提供“放弃本地并载入服务端”与用户明确点击后的“保留本地、以最新服务端版本为基准重新提交”（再次冲突仍回到 409），无无条件覆盖按钮，冲突处理期间主保存按钮禁用。错误提示覆盖 401/403/404/409/422/503 中文文案，加载与保存防重复提交。`types.ts`/`api.ts` 严格对应后端字段，不暴露 `deleted` 字段。管理员经现有管理导航新增“日计划”最小入口（选班级 + 持久日历定位日期），不扩大班级分配工作流。检查：`npm run typecheck`、`npm run build` 通过；无现有前端测试设施，未安装新依赖；本片未启动 Vite/浏览器，真实 MySQL 与浏览器端到端验证归切片 5。

### 切片 5：真实 MySQL 集成验证

- 在隔离 MySQL 8.4 / InnoDB 上运行验证矩阵。
- 完成条件：对应编号的通过标准全部满足。
- **执行事实（2026-09-23）**：
  - 环境：本机一次性 Docker 容器 `kg-next-i3-mysql-20260923`，镜像 `mysql:8.4.11`，仅绑定 `127.0.0.1:13384`；`SELECT VERSION()` 为 8.4.11，`default_storage_engine=InnoDB`；仅使用白名单库 `kindergarten_test_i3_fresh`（utf8mb4 / utf8mb4_unicode_ci）。未读取 `.env` 或私有环境文件，未连接 I1/I2、共享或生产库。
  - 命令类别：`APP_DISABLE_DOTENV=1` + 显式本地 I3 DSN 下的 `alembic upgrade head`；`APP_DISABLE_DOTENV=1 I3_TEST_ALLOW_DESTRUCTIVE=yes I3_TEST_DATABASE_URL=… unittest tests.integration.test_i3_daily_plan -v`；集成后的 `DROP/CREATE kindergarten_test_i3_fresh` + 再次 `upgrade head`。未安装依赖，未启动 API/Vite/浏览器，未暂存/提交/推送。
  - 迁移：`alembic current` = `alembic heads` = `20260923_i3_daily_plans (head)`；I3/I1/I2 表全部 InnoDB。
  - 集成结果：**实际运行 27 项，通过 27 项，失败 0，错误 0，跳过 0**（原命令退出码 0）。覆盖权限、空内容、日期限制、并发唯一、内容版本冲突、事务回滚（V8）、重启持久性（V9）、周计划同步投影（V10）、schema 约束，以及 §8.4 两种提交顺序（锁序 1/2）。服务层集成不走 HTTP；该步骤完成时浏览器端到端点击验证尚未执行，后由 main 完成，见本节下方浏览器验证补记。
  - 定点修复（仅 I3 直接相关测试/guard）：`test_i3_daily_plan.py` 在导入 `i3_guard` 前不得加载 `app.config`（否则 `DATABASE_URL` 未注入）；种子数据须绕开 `terms`↔`calendar_revisions` 循环外键（先插 terms 指针 NULL、再插 revision、再回填指针）；`_change_row` 按 JSON `null` 与 SQL NULL 区分“未写入 result_versions”；V8 注入语句改为合法 MySQL 失败语句并断言 `SQLAlchemyError`。`i3_guard.py` 在 `app.config` 已被提前导入且 DSN 为空时回填授权 DSN。未放宽业务断言，未跳过用例。
  - 集成测试会清理白名单 I3 库；执行后已重建 `kindergarten_test_i3_fresh` 并再次 `upgrade head`，核心业务表为空、`alembic` head 正确，容器保持运行供 main 启动 API/Vite 做浏览器验证。
  - 定向复核：I3 纯单元测试 132 项通过；`py_compile` I3 集成文件通过；`alembic heads`/`current` 一致；`git diff --check` 与 untracked 尾随空白检查通过。前端代码本轮未改，typecheck/build 复用已通过结果，未重跑。
  - **浏览器验证执行事实（2026-09-23，main 完成，本地隔离 MySQL 8.4.11）**：
    - UI 建立 2026-09 学期日历。
    - 教师 2026-09-23 创建空计划为 v1，显示 `pending_projection`。
    - 完整代表性栏目保存为 v2，刷新重开全部持久。
    - 外部会话更新为 v3 后，浏览器旧 v2 保存真实触发 409：本地输入保留并展示服务端内容，显式重提交至 v4。
    - 同班非创建者打开为全字段 disabled，无保存/删除入口。
    - 浏览器未发现新缺陷；未写入账号密码、DSN/cookie/容器密码。集成测试结束时曾保留容器 `kg-next-i3-mysql-20260923` 供 main 浏览器验证，此为历史事实；main 完成浏览器验证并停止 API/Vite 后，该容器已删除，容器内测试数据不可恢复。本补记不改写上述集成验证范围。

## 12. 后续资源申请清单（本轮不执行）

1. 隔离 MySQL 8.4 / InnoDB 数据库：必须使用 I3 专用隔离库之一——`kindergarten_test_i3` 或 `kindergarten_test_i3_fresh`（仅限 `localhost:13384`，由 `tests/integration/i3_guard.py` 白名单强制）。**不得复用 I2 的 `kindergarten_test_i2`**：`i3_guard` 在任何连接建立前即拒绝 I1/I2 库。
2. 运行迁移：必须显式携带 `APP_DISABLE_DOTENV=1`，且 `DATABASE_URL` 指向第 1 项的 I3 隔离库（`mysql+pymysql://…@127.0.0.1:13384/kindergarten_test_i3` 或 `…/kindergarten_test_i3_fresh`）；凭据不写入本文档：

   ```bash
   cd backend
   APP_DISABLE_DOTENV=1 DATABASE_URL="$I3_DATABASE_URL" .venv/bin/alembic upgrade head
   ```

3. 安装依赖：当前无新增 Python/Node 依赖预期。
4. 临时启动 API（`uvicorn`）与 Vite 开发服务器用于浏览器验证。
5. 运行单元测试与集成测试：使用 `unittest`（与 I2 一致）。I3 集成套件准确命令：

   ```bash
   cd backend
   APP_DISABLE_DOTENV=1 I3_TEST_ALLOW_DESTRUCTIVE=yes I3_TEST_DATABASE_URL="$I3_DATABASE_URL" .venv/bin/python -m unittest tests.integration.test_i3_daily_plan -v
   ```

   该命令仅在授权后运行；执行会清理白名单 I3 隔离库（`kindergarten_test_i3` / `kindergarten_test_i3_fresh`）中的数据；环境未满足时用例会 skip，跳过不算通过。

以上资源需求仅作清单，本轮不启动服务、不执行迁移、不安装依赖、不开展测试。

## 13. 结束说明

本规格已由二次修订草案转为已确认实施规格。已修正的问题包括：

- `raw_lesson_plan` 可作为手工输入；`split_baseline` 仅在无 AI 拆分时为 `null`，且 I3 不接受客户端写入。
- 资料快照绑定稳定计划身份且创建后不可变；内容版本只存内容。
- 当前内容指针使用 `current_content_id` + `current_content_version` 并保证属于本计划。
- 内容结构增加晨间组数量校验与 group_id/game_id 服务端生成规则。
- API 表格明确教师/管理员的输入差异；PATCH 支持可选字段继承。
- 周计划对象重命名为 `weekly_plan_sync_states`，给出当前只读消费方式，不侵入负责人规则。
- 删除/恢复作为第三项明确范围决定。
- 明确 schema/迁移也需在决定后开工。

**三项决定（2026-09-23 已确认，不再阻塞）**：

1. 范围选项 **A**：I3 最小扩入真实 `weekly_plan_sync_states` 待确认投影。
2. 历史表头规则 **A**：创建日计划时不可变快照班级/园所/创建者资料。
3. 删除/恢复 **B**：本次延后，两种入口都不暴露，schema 兼容软删除字段。

I3 第一片（切片 1 Schema 与迁移 + 切片 2 服务与事务核心）已完成；第二片“API 与权限”（切片 3）已实施并通过定向纯单元测试；第三片“前端闭环”（切片 4）已实施并通过 `npm run typecheck` 与 `npm run build`。切片 5 真实 MySQL 集成验证已于 2026-09-23 在隔离容器 `kg-next-i3-mysql-20260923`（`mysql:8.4.11`，`127.0.0.1:13384`，库 `kindergarten_test_i3_fresh`）完成：`unittest tests.integration.test_i3_daily_plan` 实际 27 项通过、0 skip、退出码 0，覆盖 V9 重启持久性与 §8.4 两种锁序；集成后已重建该库并 `upgrade head`；集成测试结束时保留该干净已迁移容器 `kg-next-i3-mysql-20260923` 供 main 浏览器验证，此为历史事实。main 完成浏览器验证并停止 API/Vite 后，该容器已删除，容器内测试数据不可恢复。main 浏览器验证已于 2026-09-23 在本地隔离 MySQL 8.4.11 上完成：UI 建立 2026-09 学期日历，教师创建空计划 v1（显示 `pending_projection`），完整代表性栏目保存 v2 并刷新重开全部持久，外部会话更新 v3 后浏览器旧 v2 保存真实触发 409（保留本地输入、展示服务端内容、显式重提交至 v4），同班非创建者打开为全字段 disabled 且无保存/删除入口，浏览器未发现新缺陷。历史验证范围保持不变，凭据类信息不写入本文档。
