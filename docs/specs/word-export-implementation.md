# I5 Word 导出实施规格

状态：**规格准备完成，未实施、未授权实施。** 本文把既有已确认的“手工日计划 / 已确认周计划 → 固定 Word 模板导出”规则收敛为可逐片授权实施的 I5 规格；只做规格、现状核对与实施切片设计，不含任何业务代码、schema/迁移、依赖安装或服务启动。

标注约定（沿用 I4 规格）：

- **已确认**：来自 Contract 或既有已确认规格，本文只继承不改写。
- **工程方案**：可在不改变产品行为前提下调整的技术设计，不作为产品问题提交用户。
- **提案 / 待用户确认**：有产品或运行影响的未决项，见 §11；未确认前不得写成事实。

依据：[Word 导出 Contract](../modules/word-export.md)、[日计划 Contract](../modules/daily-plans.md)、[周计划 Contract](../modules/weekly-plans.md)、[操作日志 Contract](../modules/audit-log.md)、[最小实施规格](manual-plans-and-word-export.md)、[模板验证计划](word-template-validation.md)、[原型结果](word-template-prototype-results.md)、[I3 规格](manual-daily-plan-save.md)、[I4 规格](manual-weekly-plan-confirmation.md)（§11 导出读取面、§2.8 表头快照）、[ARCHITECTURE.md](../../ARCHITECTURE.md)，以及现有 `backend/app` 读取面、权限与审计代码的定向只读核对（2026-09-25，基线 `3120a2c` + I4 F1/F2 工作区改动）。

## 1. 继承的已确认产品事实（冻结，不重开讨论）

### 1.1 数据与版本

| 规则 | 来源 |
| --- | --- |
| MySQL 8.4 / InnoDB 是业务权威来源；Word 文件只是所选内容版本的时间点副本，不回写计划、不改变确认状态、不作为业务主数据 | 架构、[word-export](../modules/word-export.md) |
| 日计划导出最终采用的明确内容版本 | [word-export](../modules/word-export.md)、[最小实施规格](manual-plans-and-word-export.md) §步骤 7 |
| 周计划只允许导出已确认版本；未确认候选不得导出 | [weekly-plans](../modules/weekly-plans.md)、[word-export](../modules/word-export.md) |
| 当前有新草稿时，上一份已确认周计划仍可导出，但必须提示未包含最新变化 | [weekly-plans](../modules/weekly-plans.md) 状态表 |
| 已下载文件随后续修改只能通过重新导出体现 | [word-export](../modules/word-export.md) |

### 1.2 权限

| 规则 | 来源 |
| --- | --- |
| 导出入口和文件下载都必须重新校验权限 | [word-export](../modules/word-export.md)、[最小实施规格](manual-plans-and-word-export.md) 已确认使用者与前置条件 |
| 同班教师可导出同班他人的日计划及已确认周计划，不因此获得编辑/确认权限；导出缺项确认不提升权限 | [daily-plans](../modules/daily-plans.md)、[最小实施规格](manual-plans-and-word-export.md) 例子表 |
| 调班后的历史访问边界沿用既有 contract：本人原班计划可查看导出不可修改，不再查看原班他人计划 | ARCHITECTURE、[最小实施规格](manual-plans-and-word-export.md) |

### 1.3 范围选择与排序

| 规则 | 来源 |
| --- | --- |
| 日计划：单日、按周、按月、自选日期范围，严格只取范围内日计划 | [word-export](../modules/word-export.md) |
| 周计划：单份或日期范围；按该周实际上课日期是否与范围相交选择**整份**周计划 | [word-export](../modules/word-export.md) |
| 单日命中周计划时导出整份周计划，不裁切周内栏目；跨周/月同一周计划只出现一次 | [word-export](../modules/word-export.md)、验证计划 W5 |
| 无匹配时提示，不生成空文件、不自动扩大范围 | [word-export](../modules/word-export.md) |
| 日计划按日期升序；周计划按周起始日升序；多份导出每份从新页开始，份内自然分页 | [word-export](../modules/word-export.md)、验证计划 通用检查标准 |

### 1.4 模板与日历

| 规则 | 来源 |
| --- | --- |
| 保留既有固定模板的主要表格结构、栏目和主要格式；首版不提供模板上传编辑、不引入 Typst | [word-export](../modules/word-export.md)、ARCHITECTURE 首版范围 |
| 周计划默认保留周一至周五列；周末实际上课时增加对应日期列并按日期排序；假期注明，不截掉第六、第七个上课日 | [word-export](../modules/word-export.md) |
| 表头起止日期 = 该周第一个至最后一个实际上课日，依据有效日历，不因某天缺计划而缩短 | [word-export](../modules/word-export.md)、验证计划 W4 |
| 周次沿用学期周次算法（`M` 为学期开始日所在周的周一，`floor((D-M)/7)+1`），不能从导出列数重新计算 | [最小实施规格](manual-plans-and-word-export.md) 日期算法 |
| 日计划表头显示创建教师，周计划显示班级教师名单与保育员；园所/班级/人员由管理员维护 | [word-export](../modules/word-export.md) |
| 样例含周日上课与假期合并单元格，不能把周计划固定解释为每周一至周五必有五份日计划 | [word-export](../modules/word-export.md) |

### 1.5 日计划缺项确认

| 规则 | 来源 |
| --- | --- |
| 内容缺项时先提示；有权限的教师明确确认后仍可导出，缺项保持为空，不由系统或 AI 补写 | [daily-plans](../modules/daily-plans.md) 保存与删除契约 |
| 该“导出缺项确认”不是周计划负责人确认，也不提升任何权限 | [daily-plans](../modules/daily-plans.md) |

### 1.6 标红（已确认，不新增规则）

- 无原始拆分基准（`split_baseline` 为 null）：按最终内容导出，不标红，并提示无法比较。
- 有基准：新增/替换文字标红；纯删除不输出已删除文字；纯移动和仅格式变化不标红；不新增删除线。
- 提示不写入 Word 正文（验证计划 W1 通过标准：“不擅自把提示插入 Word 正文”）。

## 2. 实现现状核对（2026-09-25，只读）

### 2.1 已存在、可复用的读取面与权限

| 现状 | 位置 | 对 I5 的意义 |
| --- | --- | --- |
| 教师读取班级 = 当前 `teacher_assignments`；管理员必须显式 `class_id`；教师夹带 `class_id` → 422（日计划路由同时拒绝 `term_id`；周计划列表的 `term_id` 是合法筛选项） | `routers/daily_plans.py::_resolve_read_class_id`、`routers/weekly_plans.py::_resolve_read_class_id` | 导出权限推导直接复用同一语义，不新造规则 |
| 按 id 读取：教师跨班 → 403 `FORBIDDEN`；管理员 `class_id` 与对象不符 → 404 | `daily_plans.py::get_daily_plan`、`weekly_plan_read_service::_assert_class_access` | 导出 `plan_id` 模式的越权语义与之完全一致 |
| 日计划列表已支持 `from`/`to` 范围、升序、软删除排除 | `daily_plan_service::list_plans` | 日计划范围查询直接复用 |
| 周计划确认版本读取：`GET /weekly-plans/{id}/confirmations[/{version}]`，自包含 `content` 快照 | I4 §5.1、`weekly_plan_read_service::get_confirmation`；I4 §11 已声明其为“导出读取面” | 周计划导出读取面已就位，无须新读取协议 |
| 表头快照：日计划 `school_name/class_name/grade/creator_display_name`（I3 创建时不可变）；周计划 `school_name/class_name/grade/header_teacher_names/caregiver_name`（U1=A 创建时不可变） | I3 §5.2、I4 §2.2/§2.8 | 导出表头只读快照列，不读当前班级资料 |
| 周日历读取（当前修订、plain read）：`_read_week_days`；周次 `cal.week_info(term.start_date, day)` | `weekly_plan_read_service`、`calendar_service` | 动态列、表头起止、周次复用现有函数 |
| 教师/管理员解析与会话校验 | `deps.py`、`auth_service` | 导出路由沿用 `get_current_account`/`get_auth_snapshot` |

### 2.2 版本与内容存储现状

- `daily_plans` 当前指针复合 FK → `daily_plan_contents(daily_plan_id, id, version)`；内容表 append-only、`UNIQUE(daily_plan_id, version)`，历史版本可按 `(plan_id, version)` 精确回读；`split_baseline` 存在内容行、客户端不可写（I3 §5.3–5.5）。
- `weekly_plans.current_confirmed_content_id/version` 指向 append-only 不可变的 `weekly_plan_confirmed_contents`；确认内容是**自包含快照**（含每日三层、游戏来源整组文本与 `facts`），确认后日计划再变化不影响该快照（I4 §2.4/§2.5）。
- 草稿（`weekly_plan_contents`）、投影（`weekly_plan_sync_states`）、实时读取辅助（`source_candidates`）均为可变/即时数据，**不属于导出读取面**。

### 2.3 审计现状

- `operation_records`：`action` 为自由字符串（String(50)），`target_type` CHECK 当前允许 `'account','class','school','term','calendar','daily_plan','weekly_plan'`，**无明细/payload 列**；I3/I4 已分别以 `create/update_daily_plan`、`create/refresh/confirm_weekly_plan` 记录业务操作。
- [操作日志 Contract](../modules/audit-log.md) 的已确认范围是“修改、删除、恢复、维护交接等关键操作 + AI 调用”，**未列举导出**；导出是否记录见 §9 提案。

### 2.4 尚不存在的能力（本规格对应的新建面）

- 无任何导出/下载/docx 相关路由、服务、前端入口；`test_i4_api_routes.py` 甚至断言不存在 `/export` 路由。
- `backend/pyproject.toml` 无任何 Word/docx/zip 生成库依赖；前端 `api.ts` 无二进制下载处理。
- 无文件存储、临时目录、导出任务或导出表（本轮也**不新增**）。

### 2.5 与契约相关的现状边界

- **调班尚未实现**（I2 明确不交付调班）：现有读取面只覆盖“当前分配班级”。调班历史访问边界是 Contract 级规则，落地归未来调班切片；I5 不提前实现也不扩大它，届时导出必须与调用时的既有读取边界一致。
- 隔离原型（11 份 docx / 31 页）使用系统 Python 的 ZIP/lxml 定点修改 `word/document.xml`，证据环境为 LibreOfficeDev 26.8 alpha + Noto 字体替代；原型结论仅适用于已执行案例，不构成生产生成库决定（见 §11.3）。

## 3. 导出请求 API 边界（工程方案）

### 3.1 入口：日计划与周计划**明确分开**（推荐）

- `POST /api/exports/daily-plans`
- `POST /api/exports/weekly-plans`

理由：两者输入形状（日期范围 vs 范围/单份双模式）、阻断语义（仅日计划有缺项 ack 门）、模板与错误细节均不同；分开后 Pydantic `extra="forbid"` schema 各自干净。被拒方案：单一 `POST /api/exports` + `kind` 判别字段——分支与错误码混杂，仅省一条路由，收益不足。路由名/路径可调，语义不可调。

选 POST 而非 GET：请求含体、语义是“生成文件”、响应不可缓存。

### 3.2 请求结构

日计划：

```json
{ "from": "2026-09-01", "to": "2026-09-30", "ack_missing": false, "class_id": "…(仅管理员)" }
```

- `from`/`to` 必填，覆盖单日（相等）、按周、按月、自选范围全部形态；日计划不做按 id 导出（契约的单日形态即日期表达）。
- `ack_missing`：缺项确认门，见 §3.5。
- 教师传 `class_id` → 422（沿用现有约定）；管理员必须传。

周计划：

```json
{ "from": "2026-09-30", "to": "2026-10-06", "class_id": "…(仅管理员)" }
```

或单份模式：

```json
{ "plan_id": "…", "confirmed_version": 3, "class_id": "…" }
```

- 两模式互斥，同时出现或都缺 → 422。
- 范围模式：按 §1.3 相交规则服务端选择整份。
- 单份模式：`plan_id` 即契约的“单份”形态（也是零上课日周唯一可行的导出方式，见 §11.7）；`confirmed_version` 可省略，省略 = 当前确认指针版本。
- 教师跨班 `plan_id` → 403；管理员 `class_id` 不符 → 404（与现有 GET by id 完全一致）。

### 3.3 版本表达与钉住

- **日计划**：客户端**不提交**内容版本——导出的“明确版本”由服务端在该请求的只读事务内读取每份计划的 `current_content_id/version` 并钉住，生成与读取同请求完成，无预检-下载竞态，也就不存在伪造 daily 版本的通道。响应头 `X-Export-Daily-Plan-Versions`（工程方案，可省略）可回传钉住结果。
- **周计划**：范围模式钉 `weekly_plans.current_confirmed_content_id/version`；单份模式钉显式 `confirmed_version` 或当前确认指针。请求**永远不接受**草稿版本、草稿 content id 或 `source_candidates` 引用。
- 钉住的历史行 append-only 不可变，因此导出中途回读旧版本不会 409；显式 `confirmed_version` 不存在或该计划从未确认 → 404（见 §8）。

### 3.4 防伪造/越权读取

1. 班级范围由服务端推导（复用 `_resolve_read_class_id` 语义），客户端不能自选 class 上下文（教师传入即 422）。
2. 范围模式完全由服务端按日期筛选：**客户端提供的 id 不参与选择**，无从夹带他班/他周资源。
3. `plan_id` 模式按现有 GET by id 语义校验归属：教师跨班 403，管理员上下文不符 404。
4. `confirmed_version` 必须解析为该计划 `weekly_plan_confirmed_contents` 中真实存在的确认行；草稿/伪造值不可达（404 `CONFIRMATION_NOT_FOUND`）。
5. 导出是只读操作：不写计划、不写版本、不写确认；“导出缺项确认”仅是本次请求的 ack 参数，不改变任何权限或状态。

### 3.5 缺项确认门（仅日计划）

- 服务端按导出范围计算缺项清单（判定口径见 §4.1），存在缺项且 `ack_missing` 未置真 → **409 `EXPORT_ACK_REQUIRED`**，响应体携带 `facts`（逐日期、逐空栏目），语义对齐 I4 `CONFIRM_ACK_REQUIRED`：客户端只提交 ack，不提交清单。
- 教师重发 `ack_missing: true` 后导出，缺项保持为空。
- 该门**只**作用于日计划；周计划的缺项在负责人确认时已固化进 `facts.missing`，导出不再要求新的确认。

### 3.6 非阻断提示的承载（工程方案）

“无法比较（无基准）”“未包含最新变化（已确认版本非最新）”是**必须提示**的产品行为，但不阻断导出。承载方式推荐：服务端在成功响应上附 `X-Export-Warnings`（如 `no_split_baseline`、`confirmed_not_latest`），其判定基于本次实际导出的钉住集合；前端同时可据既有读取面（`split_baseline` 是否为空、`needs_confirm`）在触发导出前先行提示。任何提示都**不写入 Word 正文**。

## 4. 导出读取面

### 4.1 日计划

- 读取：`daily_plans` 行（身份、`plan_date/week_number/weekday`、快照列）+ 其当前指针指向的 `daily_plan_contents` 行（`adopted_content`、`split_baseline`、`raw_lesson_plan`）。
- 版本：请求内只读事务一次性读取全部计划与内容（MySQL 默认 REPEATABLE READ 一致快照），导出结果即该快照的“明确内容版本”；期间他人保存不影响本次文件，文件也不回写。
- **禁止**读取：前端 form/draft 状态、周计划投影、任何非当前指针的草稿式数据。
- 缺项判定（工程方案，对齐 I4 `empty_field` 口径）：按固定模板栏目逐字段检查 `adopted_content`——空字符串/空数组/缺失键即列入缺项清单；`adopted_content` 为 `{}` 时全部栏目缺项。判定只决定 409 提示内容，不改变“确认后可导出、保持为空”。
- 无 `split_baseline` 的计划正常导出，仅经 §3.6 提示“无法比较”。

### 4.2 周计划（消费 I4 confirmed content）

- 读取：`weekly_plans` 行（身份、`week_number`、U1=A 表头快照、确认指针）+ `weekly_plan_confirmed_contents` 指定确认行的自包含 `content` 快照 + `facts`。
- **禁止**作为导出内容来源：`weekly_plan_contents` 草稿、`weekly_plan_sync_states`、`source_candidates`、前端 `form`/dirty 状态、任何确认后的实时来源重解析。确认快照不因日计划后续保存而变化（I4 语义，W6 逐字段等于 V1）。
- 动态列与表头日期读**当前有效日历**（复用 `_read_week_days` 语义：学期当前修订、plain read），内容读快照——两者分工与现有详情读取一致；日历变更的既有“影响预览 + 管理员确认 + 版本保护”规则不在导出侧重解释。
- 范围模式选择：候选 = 该班（教师当前分配班 / 管理员显式班）未删除周计划；对每个候选取该周教学日集合（周一至周日 ∩ 学期闭区间，`teaching` 日），与 `[from, to]` 相交则入选；`current_confirmed_*` 为空的计划**整体排除**（未确认候选不导出）；按 `week_number`（= 周起始日）升序，天然跨月/跨周去重（每周一份有效记录）。
- 单份模式：跳过相交规则，但仍要求存在确认版本，否则 404。

### 4.3 读取不加锁

导出是只读流程，不取 `FOR UPDATE`、不写任何表（审计记录除外，见 §9），与现有 GET 路由一致；不参与 I3/I4 写锁顺序，无死锁面。

## 5. 模板映射

### 5.1 日计划字段 → 固定模板（两列表格）

| 来源（I3 `adopted_content`/计划行） | 模板栏位 |
| --- | --- |
| `plan_date`、`week_number`、`weekday` | 日期行、第几周 |
| 固定字样“体能大循环”（不改写） | 晨间固定标题 |
| `morning_games` 中 `collective` 组名称 | 集体游戏 |
| `morning_games` 中 `free_choice` 组名称 | 自主游戏（保留模板名，不写“自选”） |
| 组的 `focus_guidance` / `shared_objectives` / `guidance_points` | 重点指导 / 活动目标 / 指导要点（整组共用，不按游戏拆分） |
| `morning_talk.topic` / `questions` | 话题 / 问题设计 |
| `group_activity.theme` | 活动主题（必填输出，不得丢失） |
| `group_activity.objectives/preparation/key_points/difficult_points` | 各同名栏位 |
| `group_activity.process` | 活动过程（**唯一标红对象**，见 §5.5） |
| `post_group_games` 按 `context_kind`（`area`/`outdoor`/`special_room`） | 室内区域游戏 / 户外或专用室对应位置（区域、重点指导、目标、指导、支持策略） |
| `afternoon_outdoor`（`observation_focus` 等） | 下午户外游戏各子栏 |
| `reflection` | 一日活动反思 |
| 快照 `school_name/class_name/grade` + `creator_display_name` | 表头园所/班级/年级/教师 |

- 一加一数量规则（一项集体 + 一项自选）仅适用于日计划模板。
- 空字段输出为空，不补样例、不补 AI 内容。

### 5.2 周计划字段 → 固定模板

| 来源（确认快照 `content`） | 模板栏位 |
| --- | --- |
| `theme` | 表头主题名称（确认时可为空 → 空输出） |
| 快照 `class_name/grade`、`week_number`、表头日期 | 班级 / 周次 / 日期表头 |
| `deterministic[date].effective.morning_talk_topic` / `group_activity_theme` | 该日期列的晨间谈话 / 集体活动（按日期对位，不按固定五条错位）；`day_state=rest` 列注明假期，`plan_state=no_plan` 列空且不伪装成假期 |
| `outdoor_game_slots.collective_1/collective_2/free_choice_1`（名称 + 整组共用目标/指导/重点指导；`source_kind=manual` 输出手工文本、不伪造来源） | 户外游戏栏（两项集体 + 一项自选） |
| `focus_area`（名称、上下文、目标、指导、支持策略） | 重点区域栏 |
| `weekly_columns.key_week_focus/environment_setup/habit_culture/home_cooperation` | 本周重点 / 环境创设 / 生活习惯培养 / 家园共育 |
| `materials` | 材料栏（I4 恒 null → 空，不自动补写） |
| 快照 `school_name/header_teacher_names/caregiver_name` | 表头园所、教师名单、保育员 |

- 数量规则：周计划恒为两项集体 + 一项自选，缺项按确认时 `facts.missing` 保留为空，不凑数。

### 5.3 动态列、表头与周次

- 教学日集合 = 该周周一至周日 ∩ 学期闭区间中 `effective_state=teaching` 的日期（当前有效日历）。
- 列集合 = **固定周一至周五列**（非教学日注明假期）∪ 该周其他教学日（周六/周日等）列，全部按日期升序；不截掉第六、第七个上课日；缺日计划的上课日仍保留其列。
- 表头起止 = 教学日集合的 min/max（零教学日周的表头见 §11.7）；**不因某天缺日计划缩短**。
- 周次 = `cal.week_info(term.start_date, 该周任一实际日期)` 的学期周号；**禁止**从列数、表头跨度或上课天数重新推算。
- 人员：周计划表头 = 创建时快照（U1=A），日计划表头 = 创建时 `creator_display_name`；不读当前班级资料、不写样例人名。

### 5.4 长文本与分页

- 每份计划前插入分页符（每份从新页开始）；份内表格行允许自然跨页拆分，行内长文本自然换行；不缩字号、不删栏目凑页数。
- 单份与合并输出的同份内容必须一致（验证计划“合并”标准）；“本周重点”等可编辑段落的自动编号续接问题按原型已处理方式对待（见原型结果“发现与处理”）。

### 5.5 标红处理

- 仅日计划 `group_activity.process` 参与比较：基准 = `split_baseline.group_activity_process`，输出 = 最终 `process`。
- 结果为“带 run 级颜色的最终文本”：新增/替换 run 红色，未变 run 保持模板原色；纯删除不出现、纯移动与仅格式变化不标红、不使用删除线（复用原型已验证的差异口径，具体算法实现见 §10.2 单元夹具）。
- `split_baseline` 为 null → 全文不标红，提示经 §3.6 在导出流程呈现。

### 5.6 模板资产

两份用户指定参考文件（`中四班 备课.docx`、`周计划.docx`）是**规格参考来源，不是运行时必须存在的路径**（Contract 明示）。生产生成必须以受控模板资产为输入；资产如何进入仓库/部署见 §11.4（提案，需用户授权后片 2 才能进行）。

## 6. Word 生成层边界（工程方案）

建议新增文件（不建表、不建占位目录以外的结构）：

```text
backend/app/routers/exports.py               # HTTP：鉴权、schema、错误映射、响应头、触发生成
backend/app/services/export_read_service.py  # 只读查询：范围解析、权限重判、版本钉住、缺项/警示事实
backend/app/services/word_export_mapping.py  # 纯函数：内容 JSON → 模板视图模型 + 标红 diff（无 DB、无权限）
backend/app/services/word_export_docx.py     # 纯生成：模板包 + 视图模型 → docx bytes（无 DB、无权限、无业务规则）
```

依赖方向：`router → export_read_service → 既有 models/日历/权限 helper`；`router → word_export_docx ← word_export_mapping`。

边界规则：

1. 生成层不 import 路由、不碰 Session、不做权限判断——权限与版本全部在 `export_read_service` 完成后以**已钉住的视图模型**传入。
2. **不为导出重新复制计划业务规则**：班级范围推导、`from/to` 列表语义、周次计算、教学日判定、确认版本语义全部调用既有函数；若需触碰现有私有 helper（如 `_read_week_days`），做最小提取共享并在切片报告中列明，禁止复制一份开始分叉。
3. 映射层只做“已确认内容 JSON → 模板栏位”的搬运与缺空表达，不发明字段、不补默认值。
4. 模块归属仍是同一 FastAPI 进程内的职责划分，不引入新进程、新中间件（ARCHITECTURE 模块边界不变，无需 ADR）。

## 7. 文件返回与下载边界

| 候选 | 利弊 | 结论 |
| --- | --- | --- |
| A. 同步内存生成 + 一次性 `Response`（docx 字节） | 优点：无落盘、无清理、权限校验与发文件同请求天然闭环、实现最小；缺点：生成期间占内存，超大导出不适用 | **推荐**，受 §11.1 上限约束 |
| B. `StreamingResponse` 伪流式 | docx 是 zip，必须完整生成才能发出；与 A 等价，不降内存峰值 | 不采用 |
| C. 临时文件 + 独立下载链接 | 优点：大文件低内存；缺点：落盘与清理、链接绑定与短时效、下载处需**再次**权限校验、引入文件存储决策 | 仅当上限验证显示必要时启用 → §11.2 提案 |

- **权限二次校验**：A 方案下“导出入口”是前端可见性控制（非权威），生成文件的 POST 请求内服务端完整重判权限（§3.4），409 ack 流的两次请求同样各自重判——满足“导出入口及文件下载处权限生效”。若启用 C，下载 URL 必须一次性、短时效、绑定操作者，且下载请求重新校验权限。
- **文件名**（工程方案）：`{班级名}_{日计划|周计划}_{from}_{to}.docx`；单份周计划 `{班级名}_周计划_{week_number}周_{start}_{end}.docx`；空格/中文按 RFC 5987 `filename*=UTF-8''…` 提供并带 ASCII 回退名。
- **响应头**：`Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document`；`Content-Disposition: attachment`；`Cache-Control: no-store`；`X-Content-Type-Options: nosniff`；（可选）`X-Export-Warnings` / `X-Export-Daily-Plan-Versions`。
- 错误响应永远是 JSON 错误体，**绝不发出半截文件**：先完整生成成功再写响应（A 方案天然满足）。

## 8. 错误语义（4xx = 输入/权限/状态可解释；5xx = 服务端资产或内部失败）

| 场景 | 码 / code | 层 |
| --- | --- | --- |
| 未登录/会话失效 | 401 `AUTH_REQUIRED` | 既有约定 |
| 教师跨班 `plan_id`、待分配教师、非本人班级范围 | 403 `FORBIDDEN` | 既有约定 |
| 管理员缺 `class_id`；教师夹带 `class_id`；请求含未知字段（`extra="forbid"`，含导出体不需要的 `term_id` 等） | 422 `VALIDATION_ERROR` | 既有约定 + 输入 |
| `from > to`、日期格式非法、未知字段（`extra=forbid`）、单份/范围模式冲突 | 422 `VALIDATION_ERROR` | 输入 |
| 单份模式 `plan_id` 不存在；管理员 `class_id` 与计划不符 | 404 `WEEKLY_PLAN_NOT_FOUND` | 既有 GET by id 语义 |
| `confirmed_version` 不存在或该计划无任何确认版本 | 404 `CONFIRMATION_NOT_FOUND` | 输入+状态 |
| 范围无匹配计划（含全部候选因未确认被排除后为空） | 404 `EXPORT_NO_MATCH`（工程方案；语义为“选择结果集为空”，供前端提示、不生成空文件） | 输入+状态 |
| 日计划缺项且 `ack_missing=false` | 409 `EXPORT_ACK_REQUIRED`（回传 `facts`） | 阻断门 |
| 模板资产缺失/不可读/哈希不符 | 503 `EXPORT_UNAVAILABLE`（对齐既有 503=服务资产/不变量语义） | 服务端 |
| 生成过程异常 | 500 `EXPORT_FAILED`（JSON 错误，不发文件；日志按 audit-log Contract 脱敏） | 服务端 |
| 单次导出超上限 | 待 §11.1 确认后定义（建议 422 `EXPORT_RANGE_TOO_LARGE`）；上限未确认前**不实现**该错误 | 待确认 |

## 9. 审计（提案，待用户确认）

核对结论：[操作日志 Contract](../modules/audit-log.md) 只确认记录“修改、删除、恢复、维护交接等关键操作 + AI 调用”，未列举导出；`operation_records` 无明细列，增列属 schema 变更（本轮禁止）。可选方案：

- **提案 A（推荐）**：每次**成功**导出记一条操作记录——`action="export_word"`、`target_type="class"`（CHECK 已含，无需迁移）、`target_id=class_id`、`target_version_after=null`、`operator_id=操作者`。不含范围/版本明细（无列可用）。记录写入失败则不发放文件，保证“记录 ⇔ 发放”一致；生成失败不记录（不留虚假成功）。
- **提案 B**：不记录导出——导出是只读，与 Contract 现有列举一致；代价是文件外发不可追溯。

无论 A/B 都**不新增**导出表、任务表或文件表。选择影响管理员可见日志范围 → **待用户确认**（时点：片 3 前）。

## 10. 验证矩阵

### 10.1 已由隔离原型验证的模板事实（冻结引用，不重跑、不冒充产品验收）

以下事实以[原型结果](word-template-prototype-results.md)为准：11 份 docx / 31 页通过 W1–W6 固定夹具的栏目、标红、分页、合并与机器检查（字符多重集、红字内容、无空白页、单份与合并页面一致、原文件哈希不变）；“本周重点”编号续接已定点处理；环境为 LibreOfficeDev 26.8 alpha + Noto 字体替代、无 GUI 检查、未验证 Microsoft Word。**这些是模板结构与渲染证据，不等于产品导出功能验收。**

### 10.2 未来产品验收（按层级分开执行，任一层通过不等于整体验收）

| 层 | 覆盖内容 |
| --- | --- |
| 纯单元测试（无 DB、无 HTTP、无外部进程） | 单日/按周/按月/自选范围筛选与严格边界；周相交（周末上课、六/七教学日、假期、单日选整周、跨月跨学期、零教学日周、范围仅命中非上课日）；去重与升序（日期 / 周起始日）；无匹配判定；版本钉住与模式互斥；防伪造（伪造 `plan_id`/`confirmed_version`/夹带 `class_id` 的分支）；权限矩阵（mock 依赖）；409 ack 门与 `facts` 计算；缺项判定口径；表头起止与周次（**断言不从列数推算**）；字段映射 fixtures（W1/W6 型数据）；标红 diff 文字预期表（W2 型夹具：新增/替换/纯删除/纯移动/仅格式/无基准）；文件名生成 |
| 后端集成测试（隔离 MySQL 8.4/InnoDB，需授权） | 真实 schema 上的导出查询与确认快照读取；角色 × 路由权限全矩阵；导出期间并发保存的一致快照（文件内容 = 钉住版本）；审计记录写入（若确认提案 A）；只读流程不产生任何业务表写入 |
| 实际生成 docx 结构检查（无 LibreOffice） | zip/OOXML 完整；固定表格结构与栏目存在；红 run 内容与位置；份间分页符；渲染前字符多重集与夹具一致；单份 vs 合并同份内容一致 |
| LibreOffice 打开/渲染检查（机器已有 LibreOfficeDev，执行需授权） | 产品生成文件按 W1–W6 场景逐页检查（分页、越界、缺字、假期/增列版式）；无界面与桌面 GUI 分开记录；记录实际版本与字体；不安装任何软件 |
| 浏览器下载流程检查（API + Vite + MySQL + Chrome，需授权） | 导出按钮可见性与权限（同班只读教师可用、跨班不可见/报错）；缺项 409 提示 → 明确确认 → 下载成功；无匹配提示且无文件；“未包含最新变化”与“无法比较”提示可见；下载文件名/类型正确 |
| Microsoft Word | **既有 contract：正式使用后反馈项**，不列入当前完成门槛，不声称已验收 |

### 10.3 记录要求

每层独立记录“未执行/通过/失败/受阻”+ 环境（软件版本、夹具、生成方式）；原型结论只被引用不被扩写；失败只定向修复并复核受影响案例。

## 11. 提案与未决项（**待用户确认**，不得写成事实）

| # | 未决项 | 候选与优缺点 | 建议 | 最晚确认时点 |
| --- | --- | --- | --- | --- |
| 1 | 单次导出数量/大小上限 | ① 不设上限：实现最简，超大范围可占内存/拖慢请求；② 按计划份数上限（如日计划 ≤31 天、周计划 ≤8 份）：可预期、易提示；③ 按字节/生成时长上限：最准但难预先提示 | 建议 ②（数值为占位，属产品可见提示行为） | 片 3 API 实现前 |
| 2 | 临时文件是否落盘、保存时长、清理 | ① 不落盘（推荐 §7-A）：无清理问题、无残留文件；② 临时目录 + 发送后立即 unlink + 启动清扫：省内存但引入落盘与清理策略 | 建议 ①；若 ① 被上限验证否定再回到 ② | 片 2 生成层接口定型前 |
| 3 | 生产 Word 生成库/方案 | ① `python-docx`：API 友好，但是新依赖，表头/动态列/分页与原型证据路径不同；② ZIP+lxml 定点修改 OOXML（原型同款）：与既有 31 页证据同路径、格式保真度已验证，需引入 `lxml` 依赖；③ 标准库 zipfile+xml.etree 零新依赖：命名空间保真风险高 | 建议以 ② 为首选评估；**任何选择都需用户批准新增依赖** | 片 2 前 |
| 4 | 模板资产来源 | ① 两份 docx 副本入库（记录 SHA-256，部署可重复、可核对）；② 服务器本地路径配置：不入库但环境耦合、难以审计 | 建议 ①，但**提交用户 Word 文件副本入库需用户明确授权** | 片 2 前 |
| 5 | 导出审计（§9 A/B） | A 记录一条 class 级操作：可追溯文件外发，管理员日志多一类记录；B 不记录：与现列举一致但不可追溯 | 建议 A | 片 3 前 |
| 6 | 生成变慢/上限放大时的下载形态 | ① 同步下载（推荐起点，交互即时）；② 生成任务 + 下载页：适合大文件，但需任务持久化设计，涉及 ADR 0002 任务语义且本轮禁建任务表 | 先 ①，被验证需要时再提设计 | 片 3 前（若 ① 成立则不需确认） |
| 7 | 零上课日周的单份导出表头（契约未覆盖的边角） | 该周无“第一个/最后一个上课日”；① 显示学期∩该周区间并整周注明假期；② 不允许导出该周 | 建议 ①（与“空周允许创建”一致） | 片 1 规格复核时 |

以上均未确认；实施切片中涉及对应项时必须先取得用户决定。技术上可由既有架构直接推出、且不改变产品行为的部分已按“工程方案”给出，不列为产品问题。

## 12. 实施切片（每片独立审阅，**不得自动开始，须用户逐片授权**）

### 片 1：导出读取、版本与映射纯逻辑

- **允许修改范围**：新增 `export_read_service.py`、`word_export_mapping.py` 及其单元测试；如需复用现有私有 helper，做最小提取共享并在报告中列明。
- **不包含**：路由、docx 生成、模板资产、依赖安装、schema/迁移、前端、审计写入、上限实现。
- **完成条件**：§10.2 纯单元行全绿；权限、版本钉住、相交/去重/排序、缺项与 409 facts、表头/周次、映射与标红 diff 均有断言；现有 I3/I4 单测回归通过。
- **最小测试**：新单测 + 既有后端单测回归（本地 Python，无 DB、无服务）。
- **外部资源**：无。
- **需再次授权**：本切片的启动本身；任何对现有 service 函数可见性的提取改动需在切片报告中单独列明。

### 片 2：固定模板 docx 生成

- **允许修改范围**：新增 `word_export_docx.py` 与 docx 结构机检测试；接入模板资产；按 §11.3 决策安装生成依赖。
- **不包含**：路由/权限/错误映射、前端、LibreOffice 正式验收（冒烟可选、需授权）、上限/审计。
- **完成条件**：固定夹具 → 完整 docx 字节；§10.2 “docx 结构检查”行通过；模板资产与生成库两项已获用户确认（§11.3/11.4）。
- **最小测试**：结构机检单测（zip/OOXML 断言，无 LibreOffice）。
- **外部资源**：**新增 Python 依赖安装授权**、**模板 Word 副本入库授权**。
- **需再次授权**：依赖安装、复制用户 Word 文件、任何 LibreOffice 调用。

### 片 3：API 与下载闭环

- **允许修改范围**：新增 `routers/exports.py` + schema（`extra=forbid`）+ 错误映射（§8）+ 409 ack 流 + 响应头/文件名（§7）+ 审计记录（若 §11.5 确认 A）+ 前端导出入口与三类提示（日计划视图、周计划视图/列表）；`npm run typecheck` / `npm run build`。
- **不包含**：LibreOffice 与浏览器正式验收（片 4）、异步任务、上限之外的容量优化、删除/恢复等任何其他功能。
- **完成条件**：路由/权限单测（mock）覆盖 §8 全表；隔离 MySQL 集成测试通过（权限矩阵、并发一致快照、审计记录、零业务写入）；前端 typecheck/build 通过；无匹配/缺项/警示交互闭环。
- **最小测试**：定向路由单测 + 隔离 MySQL 集成测试。
- **外部资源**：一次性隔离 MySQL 容器与白名单库（沿用 I3/I4 guard 模式）。
- **需再次授权**：数据库容器启动、迁移执行、运行集成测试；本片若涉及 §11 提案项须先有用户决定。

### 片 4：隔离真实 Word/浏览器验收

- **允许修改范围**：启动临时 API/Vite/MySQL/浏览器；用产品生成文件执行 §10.2 LibreOffice 与浏览器两行检查；写结果记录文档；失败时按最小范围回到对应切片修复并复核。
- **不包含**：Microsoft Word 验收（后续反馈项）、环境全面审计、无关重构。
- **完成条件**：两行检查逐项记录“通过/失败/受阻”+ 环境信息；失败项定向修复后复核通过；服务与容器清理。
- **最小测试**：W1–W6 场景的产品级复跑 + 浏览器下载流程走查。
- **外部资源**：已安装的 LibreOfficeDev（**只使用、不安装**）、系统 Chrome、MySQL 容器、临时服务进程。
- **需再次授权**：全部启动类操作（服务、数据库、浏览器、LibreOffice）与任何修复实施。

## 13. 契约一致性核对

- **未发现需要 ADR 的架构级冲突**：导出按 ARCHITECTURE“读取业务数据和指定版本、Word 不是数据权威”只读消费，不改一级技术栈、依赖方向、模块边界、数据权威或通信机制。
- 表述精度差异 1（非矛盾）：[word-export](../modules/word-export.md) 写“表头中的园所名称、班级教师名单及保育员姓名由管理员维护”，而 I3/U1=A 已确认为**创建时不可变快照**。二者不冲突——快照取自管理员维护的配置，创建后不回填；I4 §2.8 已明确“读取与未来导出只读 `weekly_plans` 自身”。是否在 Contract 补一句“导出读创建时快照”由用户决定，**本轮不改 Contract**。
- 表述精度差异 2（契约空白）：零上课日周的单份导出表头起止无既定规则 → §11.7 提案。
- 其余核对项（文件上限与清理“导出实现前细化”、Microsoft Word 反馈项、原型证据边界）与本文 §11/§10 完全一致，无矛盾。

## 14. 结束说明

本文完成的是 **I5 规格准备**：既有已确认规则被逐条继承并冻结（§1），技术边界基于现有代码真实能力建立（§2–§10），所有有产品/运行影响的选项保持为提案（§11），实施被切成四片且每片完成条件明确（§12）。

- **规格已写 ≠ 功能已实现**：当前无任何导出代码、依赖、模板资产或导出入口。
- 本文件不构成任何切片授权；片 1 亦不得自动开始。
- 本任务未运行数据库/API/Vite/浏览器、未安装依赖、未读取密钥、未访问生产。
