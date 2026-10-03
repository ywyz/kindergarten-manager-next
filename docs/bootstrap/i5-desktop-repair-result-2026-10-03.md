# I5 年级显示修复结果与剩余子例配方（OpenCode，2026-10-03）

依据：[桌面验收记录](i5-desktop-validation-2026-10-03.md)、[审阅与修复分工](i5-desktop-review-and-repair-plan-2026-10-03.md)、[验收环境口径](../specs/i5-validation-environment.md)、[W1–W6 标准](../specs/word-template-validation.md)、[I4 规格](../specs/manual-weekly-plan-confirmation.md)（来源选择 / 材料恒 null / 版本规则）、[Word 导出实施规格](../specs/word-export-implementation.md) §5。

## 0. 工作区与基线

- 实际 HEAD：`2c44ac2`（`docs(i5): record desktop Word acceptance and remaining gaps`）。提示词基线 2c44ac2 与实际代码一致，未漂移。
- 会话开始时工作区已有三份被修改文档（`architecture-v1-readiness.md`、`i5-trae-work-validation-2026-10-02.md`、`i5-validation-environment.md`）和七份未跟踪文档／夹具（含桌面 Codex 提示词与夹具清单 `i5-desktop-fixtures-2026-10-03.json`），全部未覆盖、未清理、未暂存。
- 夹具快照 `source_commit` 为交接值 `2cb8d81`（远程部署源，未在本轮重新核定）；仓库代码基线与夹具记录均保留原执行身份。

## 1. 根因与最小变更

### 根因

I2 规定并落库班级年级为枚举 `small/middle/large`（`backend/app/models.py` `ck_classes_grade`，API 校验 `config_normalize.normalize_grade` 同口径），前端全部视图有中文标签映射，因此浏览器显示中文。而 Word 导出读取面（`export_read_service.py`）把创建时快照 `grade` 原样传入映射层，`word_export_mapping.map_daily_plan()` 与 `map_weekly_plan()` 直接放入 `header.grade`，`word_export_docx.py` 在日计划副标题与周计划“班级：”行直接拼接输出——所以 DOCX 表头出现英文代码。映射／生成单测夹具多用 `grade="中班"`，没有断言真实持久化枚举值到最终 OOXML 表头，缺陷因此漏测。

### 最小变更（仅 3 个文件，纯展示层）

- `backend/app/services/word_export_mapping.py`：新增模块级共享转换 `grade_display()`（`small→小班、middle→中班、large→大班`），分别在 `map_daily_plan()` 与 `map_weekly_plan()` 的 header 组装处替换原样透传，共两处调用、一个定义点。日／周复用同一位置，映射与生成层（`word_export_docx.py` 零修改）不重复转换。
- `backend/tests/unit/test_i5_export_mapping.py`：新增 `GradeDisplayTests`（6 项）。
- `backend/tests/unit/test_i5_word_export_docx.py`：新增 `GradeHeaderDocxTests`（7 项），断言最终 OOXML。

### 语义边界（按任务约束逐条落实）

- 只消费所选计划创建时快照 `record.grade` / `item.grade`；不查询当前班级资料，不改保存值、API 字段或快照。
- 已有中文值（小班/中班/大班）原样输出，既有夹具零改动兼容。
- 空值输出空字符串，生成层既有“过滤空片段”行为不变，空栏不补填。
- 未知值原样透传，不猜测为已知年级；合法持久化值只有三枚举，透传仅为防御性保持。
- 班级名、创建者／教师名单、保育员、日期、周次、动态列与分页逻辑零修改。

## 2. 修复前／后证据

- 修复前：新测试先行提交后运行，`/tmp/opencode/i5-grade-prefix-failures.txt`：`Ran 13 tests … FAILED (failures=7)`。失败断言实测输出即缺陷原文，如日计划副标题 `'small 小一 甲老师'`、周计划 `'班级：small 中一 第（一）周…'`。失败仅因英文枚举值进入表头。
- 修复后定向：`Ran 61 tests in 3.899s … OK`（测试 I5 映射＋生成全部，`/tmp/opencode/i5-grade-postfix-ok.txt`）。
- 关键断言覆盖：三个真实枚举值经 `map_daily_plan`／`map_weekly_plan` 到日计划副标题与周计划“班级：”行的中文表头；混合年级多份合并时逐份携带各自年级且不串染（日／周分别断言）；空值、已有中文值兼容；原输入（记录对象与视图模型）`grade` 未被修改；`small/middle/large` 不出现在最终文本。
- 后端纯单元回归：`Ran 546 tests in 7.866s … OK`，退出码 0（`APP_DISABLE_DOTENV=1`，隔离无 DB）。`git diff --check` 干净（退出码 0）。未新增包／框架／Skill／MCP；使用既有 `.venv` 与 `uv.lock` 锁定依赖。
- 模板资产与保真：`daily_plan.docx` SHA-256 `99008f92ae42cc87da7e42e84009ffcd8bbefdf43602f09a59ae4027e5ddc9bd`、`weekly_plan.docx` SHA-256 `24ccaa9e557522c40a653643381e31f319ea6ae5e9f3e30e9dfa41da21986aed` 前后一致、被 `TemplateAssetTests` 断言；`test_output_zip_preserves_other_members_and_template_hash`（日／周）证明 `word/document.xml` 之外全部 ZIP 成员逐字节保真。业务快照语义未改：映射只读 `split_baseline`／确认快照，标红算法（含纯移动、仅空白、纯删除）既有单测全部通过。

## 3. 验收层分层记录（本轮实际状态）

| 层 | 状态 |
| --- | --- |
| 自动测试（映射纯逻辑 + OOXML 结构 + 后端单元回归） | 本轮通过（546 项 0 失败） |
| 远程部署 | 未执行（本轮未授权部署；`kg-next-verify.ywyz.tech` 仍是 `2cb8d81`） |
| 真实浏览器下载 | 未执行 |
| Office／WPS 桌面逐页 | 未执行 |

本轮未执行层不写为通过，不宣布 I5 或片 4 完成。

## 4. 桌面 Codex 补验配方（只走现有产品链路）

通用前提（沿用 followup 提示词）：现场读取实际数据版本，先私密备份；剪贴板只传完整合法载荷；出现 409 `VERSION_CONFLICT` 就重读最新版本重试；出现 409 确认门就按服务端 `facts` 重新 ack；不直接写数据库、不 PATCH `split_baseline`（schema `extra="forbid"` 会 422，且服务端永不接受）、不回退版本指针、不删历史记录、不运行 seed／清库脚本。

### 4.1 W2-A 纯移动（计划 `smveKp-SqCpbhhBq8KwvEQ`，09-03，保留基准）

先决：该计划当前 `split_baseline` 存在（夹具清单记录，版本与 SHA 以现场读取为准）。

1. **读取与备份**：`GET /api/daily-plans/smveKp-SqCpbhhBq8KwvEQ`（9-03 创建教师账号，`Content-Type: application/json` + 同源 `Origin`）。记录 `content.id`、`content.version`（夹具基线 v1）、把 `adopted_content` 全文与 `split_baseline.group_activity_process` 原文逐段落（按 `\n` 拆分）私密存档。读取 `split_baseline.group_activity_process` 与 `adopted_content.group_activity.process` 作对照。
2. **选择移动段落**：从基准段落表按 `strip()` 后互不相同、非空的完整段落选两段 P1／P2（优先首段与末段以外的两段，减少与其他子例字符串重叠）。若实际基准不足两个可区分非空段落，重新计算配方：改选“单段移动到末尾”形态，规则不变。若实际布尔 `split_baseline_present` 与清单不符（例如该内容版本基准已被清空），停下来列出实际状态并回报，不重写拆分基准。
3. **纯书写移动**（只换段序、一个字不改）：`PATCH /api/daily-plans/smveKp-SqCpbhhBq8KwvEQ`，体：`{"expected_content_version": <步骤1读到的v>, "adopted_content": <备份的 adopted_content，仅把 group_activity.process 中 P1 与 P2 的**完整段落**位置互换，其余键逐字节保持>}`。省略 `raw_lesson_plan`（继承）。除段序外不得碰 theme／目标／指导等任何字段。
4. **下载与逐页预期**：经真实 UI 触发 09-03 单日导出（`POST /api/exports/daily-plans {"from":"2026-09-03","to":"2026-09-03"}`；无缺项时直接 200）。Word 预期：活动过程按**最终顺序**（已互换）完整连续，段落内文字全部为模板原色（`red` 零出现）；无删除线；不因换段引入新增页或空白页；表头年级显示中文（见 §4.4 年级入口）。依据：映射段级纯移动匹配按 `strip()` 后全文相等判等，单测 `test_pure_move_is_not_red` 已证明。
5. **同步副作用记录**：该保存追加日计划内容版本 v+1；`weekly_plan_sync_states.updated_at` 刷新（本班同周周计划出现待更新横幅／`projection_pending` 增加）；审计新增 `update_daily_plan` 一条。`split_baseline` 不变、`raw_lesson_plan` 不变。
6. **恢复**：用当前最新 `expected_content_version` 重新 `PATCH`，`adopted_content` 回填步骤 1 的完整备份；然后 `GET` 复核 `adopted_content` 与备份逐键一致、`split_baseline` 与步骤 1 一致。恢复同样追加版本（v+2）并再次刷新同步状态，属预期成本；不回退指针、不删除历史版本。

### 4.2 W2-B 仅格式（首尾空白，同一计划续接）

紧接 4.1 之后同一守卫链路：

1. `GET` 取最新版本与备份（4.1 步骤 6 恢复后状态）。
2. `PATCH`：`adopted_content` 中仅把 `group_activity.process` 的某一段（建议与 4.1 相同基准段之一）加**前导两空格或末尾空格**，其余全部内容（含其余段）逐字节保持；`expected_content_version` 用最新值。
3. 预期：Word 中该段文字仍为原色（映射 `strip()` 判等，单测 `test_format_only_whitespace_change_is_not_red` 已证明），文本含首尾空白（最终输入为准）；无删除线。
4. **边界声明**：当前内容模型是纯文本，没有富文本字体／加粗字段的存储或编辑器；本子例只验证‘文本相同仅首尾空白变化 → 不标红’，**不**把这个案例写成已验证富文本格式（字体／加粗）编辑。若现行必需标准对“仅格式”另有所指，记录实际覆盖差异并回报待确认解释，不新建格式功能。
5. **恢复**与副作用同 4.1（再追加版本；`weekly_plan_sync_state` 再刷新；审计再增 1 条）。完成后核对内容哈希与不变 `split_baseline`。
6. 下载副产物同理经 09-03 UI 出口真实下载并逐页检查后完成。旧 D03/D04/D12 的字节证据是历史版本证据，不覆盖、不重署。

### 4.3 W6 同类别同名来源 A/B 与版本隔离

先决（夹具清单）：验收库每日计划 32 份、周计划 10 份、已确认快照 11 份；目标周计划建议第 9 周 `sH63BsGRi2rPSDJBvGQo5g`（当前已确认 v1、草稿 v2）或现场确认可用者。

1. **探明既有来源**：负责人（9 周负责人）账号 `GET /api/weekly-plans/sH63BsGRi2rPSDJBvGQo5g`。检查响应 `source_candidates` 中 `collective` 类候选：目标形态 = 两个不同 `daily_plan_id`（不同日期）的候选，`name` 完全相同（同类别同名），`shared_objectives`／`guidance_points`（必要时 `focus_guidance`）文字可区分（若本身无区别，按步骤 4 补标记）。逐条记录候选 `daily_plan_id/content_id/content_version/group_id/game_id/名称/目标/指导/来源日期`。
2. **两集体加一项自选的占位约束**：准备阶段不得把同名候选放两个槽位占名额。若 `collective_2`／`free_choice_1` 尚为 null，先按现有 UI 从候选补足（名称应明显不同于 A/B 名称，以免混淆检查），保存一次记录版本。
3. **选 A → 保存 → 显式确认 → 得 C_A**：
   - `PATCH /api/weekly-plans/{id}`：`{"expected_draft_version": <当前草稿v>, "outdoor_game_slots": {"collective_1": {A 的完整引用（source_kind="daily_plan"、daily_plan_id、content_id、content_version、group_id、game_id、name、shared_objectives、guidance_points、focus_guidance）}, "collective_2": <现有值原样>, "free_choice_1": <现有值原样>}}`。草稿 v=v+1。
   - `POST .../confirm`：`{"expected_draft_version": <v+1>, "acknowledge_missing": true/false 按 409 facts, "acknowledge_stale": true/false 按 facts, "note": "I5 合成夹具验证同名来源选A"}`。facts 非空则先 409 再带 ack 重发。→ C_A（记版本号）。
4. **来源可区分化（如需）**：若 A/B 目标／指导不可区分，用现有 I3 链路给其中一个日计划来源的 `morning_games` 集体组改写目标／指导加合成标记（如“【A来源-09-03】…”），`PATCH /api/daily-plans/{source_plan_id}`（守卫其 `expected_content_version`），并记录：日计划 v+1、周计划同步状态刷新、审计 `update_daily_plan`。改后 `GET /weekly-plans/{id}` 会出现真实 `stale_sources`/横幅，这正是交替验证素材：用 C_A 前先按 UI 走“刷新到最新来源”（U4 R 路径）或直接选 A 并带 `acknowledge_stale`。
5. **改选 B → 保存 → 确认 → 得 C_B**：同步骤 3，把 `collective_1` 改成 B 的完整引用（target_objectives/指导为 B 标记文本），再次确认（新 facts 按现状给 ack）→ C_B，`current_confirmed_content_version` 推进至 C_B 版本号。
6. **导出与逐字段预期**：
   - 最新确认 C_B：`POST /api/exports/weekly-plans {"plan_id": "sH63BsGRi2rPSDJBvGQo5g"}`（省略 `confirmed_version` = 当前确认指针）。
   - 历史 C_A：同体加 `"confirmed_version": <C_A 版本>`。
   - C_A 文件预期：`户外游戏` 栏 `集体游戏：1.《同名游戏》（目标：<A 标记目标>）`、`指导要点/重点指导` 取 A 整组文本；响应头 `X-Export-Warnings` 含 `confirmed_not_latest`（原因 `superseded`，纯历史导出）。C_B 文件预期：目标／指导为 B 的整组文本；两集体 + 一项自选齐全；同名只占 `collective_1` 一个名额；不跨日混用 A/B 内容；`材料` 栏保持空；年级／班级／教师名单取创建时快照。
   - C_A 与 C_B 逐字段等于各自确认快照（I4 语义），两文件除目标／指导标记外其内容应一致。不是“同名来源占两个名额”的形态：整组自始至终只有一个同名槽位。
7. **副作用与约束**：两次选择 + 至少一次确认造成草稿 / 确认 / 审计（`save_weekly_plan`×2、`confirm_weekly_plan`×2）/ 同步行多条变化，逐项记录。历史确认行不可变，只能通过复制导出；不执行恢复／重置。**若既有来源不足（找不到两个同类别同名可区分候选且无法按步骤 4 合成），列出所需的精确合成输入（目标周工作日、日计划日期、名称／目标／指导文本、涉及 API 与守卫值），经授权后由桌面 Codex 通过现有 API 准备——本轮 OpenCode 未执行任何远程写入。**

### 4.4 年级显示复验入口（前提：修复已部署）

旧部署源 `2cb8d81` 不含本修复；年级断言在部署新源后才可执行。部署后经实时 UI 下载普通日 / 单周 / 三日日范围 / 六七列周范围代表文件，检查日计划副标题与周计划“班级：”行显示 `小班`（验收库 `clsi5` 实际年级以现场读取为准；中班／大班先引用本文 §2 自动回归，如需产品实测优先单独准备合成班级，不改现有班级或历史快照年级）；逐页要求沿 [W1–W6 标准](../specs/word-template-validation.md) 通用检查标准。

### 4.5 W6 材料恒 null 的链路缺口（保持阻塞，不解除）

- **既有单测证明的范围**：`test_i5_word_export_docx.py::test_w6_confirmed_snapshot_fields`、`test_w6_header_includes_grade_and_class` 及映射层的夹具检查用固定文本 `materials="纸杯、托盘"`（标为“模拟 AI 材料”的生成层夹具）证明：**若**确认快照带材料文本，生成层会把材料写入周计划“材料：”栏、且“目标/指导/支持策略”各栏互不混用、材料值不从导入部件冒充。这是 OOXML 生成层和 I5 映射层证据，不是产品链路证据。
- **产品链路缺口**：I4 `materials` 恒 null（服务端写入，客户端不可写非空）；无 AI 材料提取／生成切片；确认快照因此实际不存在非空材料。没有合法产品输入路径能产出“真实材料可下载”的导出。
- **不采取的措施**：不新增手工材料入口、不放宽 I4 校验、不改确认快照、不伪造 AI 依据或自动修改验收必需标准。非空材料导出及“改选后旧材料依据保留/陈旧”子例保持受阻，待材料能力切片或用户确认新的 W6 口径后再通过产品链路补验。

## 5. 阻塞与移交

1. 年级修复需要部署到验收实例后方可进入 §4.4 产品复验；部署按届时明确授权另行执行。
2. W2 依赖 09-03 实际基准段落结构与可区分性；不符时按 §4.1 第 2 步规则回报重算。
3. W6 来源可区分合成输入（§4.3 步骤 4）涉及远程日计划写入，须由桌面 Codex 在其授权内执行，OpenCode 本轮未做任何远程写入。
4. W6 非空材料按 §4.5 继续阻塞，属切片边界与验收要求冲突，需用户口径决定。
5. 证据补录项（HTTP 记录、打开前哈希、About／字体核定、审计对账等）保持 followup 提示词的分工，不因本修复重置。

## 6. 本轮交付清单

- 实际 HEAD：`2c44ac2`。
- 改动文件：
  - `backend/app/services/word_export_mapping.py`（+21/-2，`grade_display` 与两处 header 调用）
  - `backend/tests/unit/test_i5_export_mapping.py`（+55，`GradeDisplayTests`）
  - `backend/tests/unit/test_i5_word_export_docx.py`（+103，`GradeHeaderDocxTests`）
- 验证结果：定向 61 项 OK；后端纯单元 546 项 0 失败 0 错误（退出码 0）；`git diff --check` 干净；模板哈希与 ZIP 成员保真断言通过。修复前失败证据 `/tmp/opencode/i5-grade-prefix-failures.txt`、修复后 `/tmp/opencode/i5-grade-postfix-ok.txt`、回归 `/tmp/opencode/i5-unit-regression.txt`。
- 未改动：`word_export_docx.py`、`export_read_service.py`、`models.py`、schemas、前端、模板资产、数据库 schema／迁移、验收数据；未 commit／push、未部署、未安装新包／Skill／MCP。
- 桌面补验入口：新增 [followup Codex 提示词](i5-desktop-followup-codex-prompt-2026-10-03.md) §2（年级、W2、W6 源）＋本文 §4 三份配方与逐字段预期；年级产品复验仅在修复部署后生效（§4.4）。
- 本文件为可审查的代码与文档交付，不宣布 I5／片 4 完成，不自动开启下一切片。
