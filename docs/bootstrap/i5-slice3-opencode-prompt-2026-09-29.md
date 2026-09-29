# 给 OpenCode：I5 片 3 API 与下载闭环

以下正文可直接交给 OpenCode。用户已于 2026-09-29 确认 I5 §11.1、§11.5、§11.6 的推荐方案并授权进入片 3：日计划单次最多 31 份、周计划单次最多 8 份；成功导出记录一条 class 级操作日志；同步内存生成并在当前请求直接下载。本任务授权片 3 代码、定向单元测试、隔离 MySQL 集成测试、前端 typecheck/build、直接相关文档更新、提交与 push；不授权片 4、LibreOffice/浏览器正式验收、Microsoft Word 验收、部署或其他功能。

---

请在仓库 `/home/ywyz/code/kindergarten-manager-next` 实施 I5 片 3“API 与下载闭环”。

先读取并遵守：

- `AGENTS.md`
- `ARCHITECTURE.md`（只读，不修改）
- `docs/specs/word-export-implementation.md`，重点 §1、§3–§11、§12 片 3
- `docs/modules/word-export.md`
- `docs/modules/audit-log.md`
- `docs/bootstrap/i5-slice2-opencode-prompt-2026-09-28.md`
- `docs/bootstrap/i5-slice2-followup-opencode-prompt-2026-09-28.md`
- `backend/app/services/export_read_service.py`
- `backend/app/services/word_export_mapping.py`
- `backend/app/services/word_export_docx.py`
- `backend/app/routers/daily_plans.py`、`weekly_plans.py`
- `backend/app/schemas.py`、`backend/app/main.py`、`backend/app/deps.py`
- `backend/app/services/auth_service.py::record_operation`
- `frontend/src/api.ts`、`types.ts`
- `frontend/src/views/DailyPlanView.vue`、`WeeklyPlanView.vue`、`WeeklyPlanListView.vue`
- 管理员复用入口 `AdminDailyPlansView.vue`、`AdminWeeklyPlansView.vue`

开始先核对实际 HEAD、最近提交和工作区。当前审阅通过基线为 `6b4c6c7`；如已有后续提交，只核对与本任务相关的差异。保留用户已有 `.codex/config.toml`、`docs/bootstrap/current-review-opencode-prompt-2026-09-28.md` 及其他未提交修改，不覆盖、不回退、不顺手整理。不要启用或安装新的 MCP/Skill，不要修改模板资产或重新生成模板。

## 2026-09-29 已确认决定

先最小更新 `docs/specs/word-export-implementation.md` 的 §11 决定汇总、§7–§9、错误表和片 3 状态边界，随后按同一决定实施；这些不是待 OpenCode 选择的提案：

1. **§11.1 方案②，按实际入选计划份数设上限**：日计划 `<= 31` 份，周计划 `<= 8` 份。服务端完成鉴权、范围选择和去重后，以实际将写入文件的计划数判断；无匹配先返回 `404 EXPORT_NO_MATCH`，非空结果超限再返回 `422 EXPORT_RANGE_TOO_LARGE`，不得开始映射、生成或审计。范围跨度本身不是计数依据。
2. **§11.5 方案 A，记录成功导出**：复用现有 `operation_records` 和 `auth_service.record_operation()`，写 `action="export_word"`、`target_type="class"`、`target_id=resolved_class_id`、`target_version_after=null`、当前操作者；不保存范围、版本、文件内容或缺项明细。不新增表、列或迁移。只有完整 DOCX 已生成且审计提交成功才返回文件；任何鉴权、校验、无匹配、超限、409、读取、模板、生成或审计失败均不得留下成功导出记录。审计提交失败不发文件。
3. **§11.6 方案①，同步内存下载**：同一 POST 请求内完成重新鉴权、同一一致性视图读取与版本钉住、映射、完整 DOCX 内存生成、成功审计提交和文件响应。不落盘、不建任务、不建下载页、不返回临时链接、不使用伪流式规避完整生成。先完整生成成功，再构造二进制响应，绝不发送半截文件。

§11.9 仍留到日历/学期影响处理能力开放前决定；当前 `plans_started_at` 门槛下不可达，不阻塞片 3，也不得在本片自行选择或扩展日历业务。

## 后端 API

新增 `backend/app/routers/exports.py` 并在 `app/main.py` 注册，入口固定为：

- `POST /api/exports/daily-plans`
- `POST /api/exports/weekly-plans`

沿用当前全局 JSON Content-Type、Origin、会话和 `Cache-Control: no-store` 规则。两条路由每次请求都在后端重新鉴权；前端按钮可见性不是权限依据。

### 请求 schema

在现有 schema 体系中新增 `extra="forbid"` 的严格模型，不接受未知字段，不接受布尔值冒充整数，不把教师显式传入的 `class_id: null` 当成“未传”。

日计划请求：

```json
{
  "from": "2026-09-01",
  "to": "2026-09-30",
  "ack_missing": false,
  "expected_context": null,
  "class_id": "仅管理员传"
}
```

- `from`、`to` 必填且 `from <= to`；支持相等日期、按周、按月和自选范围。
- 教师必须完全省略 `class_id`；管理员必须显式传非空 `class_id`。
- `ack_missing` 为严格布尔值，默认 false。
- 首次请求省略或传 null `expected_context`；409 后客户端只回传服务端原样下发的 expected context，不提交或修改 facts。
- 不接受 plan id、term id、内容版本或客户端 facts。

周计划请求为互斥双模式：

```json
{ "from": "2026-09-30", "to": "2026-10-06", "class_id": "仅管理员传" }
```

或：

```json
{ "plan_id": "…", "confirmed_version": 3, "class_id": "仅管理员传" }
```

- 范围模式必须同时有 `from/to`，不得带 `plan_id/confirmed_version`。
- 单份模式必须有 `plan_id`，`confirmed_version` 可省略，省略时钉当前确认指针；不得带 `from/to`。
- 两模式同时出现、都缺、范围只给一端、单份模式伪造草稿/content/source 字段均为 422。
- 教师/管理员 `class_id` 规则与日计划相同。

如为复用权限语义需要提取现有 `_resolve_read_class_id`，只做最小共享提取并保持 I3/I4 原路由行为和测试不变；不要复制出第三套会分叉的角色判断。待分配教师为 403；同班非创建者/非负责人教师允许导出，但不因此获得编辑或确认权。

### 日计划 409 确认闭环

路由必须消费片 1 已实现的 `prepare_daily_export()`，不得另写缺项或指纹算法：

- 首次存在缺项：返回 `409 EXPORT_ACK_REQUIRED`，JSON `error` 中携带完整 `facts`、服务端 `expected_context` 和原因 `missing`。
- 用户确认后重试：`ack_missing=true` 且原样回传 `expected_context`；每次重试重新鉴权、重新读取当前版本、重新计算 facts。
- 版本、事实集合、班级或范围任何确认对象变化：旧确认失效，再次返回 409，原因 `context_changed`；即使最新缺项减少或归零也不得直接放行。
- 对象未变且确认有效：继续导出，缺项保持为空，不补模板样例、不补 AI 内容。
- 首次请求本来没有缺项：无需确认，直接继续。

409 必须用能够保留扩展字段的 JSON 响应；不得把 `facts/expected_context/reason` 丢给只保留 code/message 的通用异常处理器。

### 选择、限制、映射和生成

- 日计划严格复用 `prepare_daily_export()` 的已钉住 items；周计划范围复用 `select_weekly_plans_range()`，单份复用 `load_weekly_single()`。
- 空 items 返回 `404 EXPORT_NO_MATCH`，不生成空文件、不扩大范围、不写审计。
- 对非空选择结果应用已确认份数上限：日计划 31、周计划 8。超限返回 `422 EXPORT_RANGE_TOO_LARGE`，错误体提供稳定、非敏感的字段（至少可让前端说明 limit 和实际 selected count），不生成、不审计。
- 上限通过后，逐项调用现有 mapping 层，再调用片 2 generator；不得从实时草稿、投影、前端 form 或 `source_candidates` 重建 Word 内容。
- 同一次请求内的范围、版本、日历修订、动态列与表头必须来自同一 Session/一致性视图；不取 `FOR UPDATE`，不修改计划、内容、确认或指针。唯一允许的写入是最后的成功导出操作记录。

### 错误映射

覆盖并定向测试规格 §8 全表，至少包括：

- 401 `AUTH_REQUIRED`
- 403 `FORBIDDEN`
- 404 `WEEKLY_PLAN_NOT_FOUND`
- 404 `CONFIRMATION_NOT_FOUND`
- 404 `EXPORT_NO_MATCH`
- 409 `EXPORT_ACK_REQUIRED`，保留 facts/context/reason
- 422 `VALIDATION_ERROR`
- 422 `EXPORT_RANGE_TOO_LARGE`
- 503 `EXPORT_UNAVAILABLE`：模板资产缺失、不可读、哈希不符、非法模板
- 503 `SERVICE_UNAVAILABLE`：持久化指针/数据库/审计提交等服务不变量失败
- 500 `EXPORT_FAILED`：生成层其他内部失败

错误响应必须是 JSON，不得带 DOCX 内容或成功审计。日志和错误消息不得包含 cookie、认证头、数据库凭据、完整计划内容或文件字节。

### 成功响应

成功后使用一次性 `Response` 返回完整 bytes，至少包含：

- `Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document`
- `Content-Disposition: attachment`，同时提供无注入风险的 ASCII fallback 与 RFC 5987 `filename*=UTF-8''...`
- `Cache-Control: no-store`
- `X-Content-Type-Options: nosniff`
- `X-Export-Warnings`：确定性、紧凑、去重后的 ASCII/JSON 编码警示集合，至少能表达 `no_split_baseline` 与 `confirmed_not_latest` 及原因；不得把中文、完整 facts 或计划内容直接塞入 header，不得因同类多份计划造成无界重复。

文件名遵守规格 §7：范围导出含班级名、计划类型、from/to；单份周计划含班级名、周次和表头起止日期。对 CR/LF、路径分隔符、引号及其他危险字符做确定性清理；中文只进入正确编码的 `filename*`，ASCII fallback 稳定可测试。

先生成完整 bytes，再调用 `record_operation()` 并提交；提交成功后才构造/返回响应。不要依赖 `get_db()` 自动提交——当前依赖不会自动 commit。提交失败必须 rollback/交由既有异常路径处理且不返回文件。

## 前端下载闭环

在 `frontend/src/api.ts` 新增专用二进制下载 helper，不要把 DOCX 强行塞进现有只读 JSON 的 `request<T>()`：

- 请求仍带 `credentials: include`、JSON Content-Type、同源 Origin，并复用 401 清会话/跳登录行为。
- 成功读取 Blob、`Content-Disposition` 文件名和 `X-Export-Warnings`。
- 失败时读取 JSON error，完整保留 `facts/expected_context/reason/fields/limit/selected_count` 等片 3 所需字段，不能把 409 当 Blob 下载。
- 下载使用临时 object URL + `<a download>`，触发后及时 revoke，不把文件内容放入状态、日志或 localStorage。
- 为日/周请求和响应补充明确 TypeScript 类型，不使用无边界 `any` 绕过检查。

### 日计划入口与交互

在现有日计划上下文中提供最小导出入口，不新增顶级导航、不改变创建/保存流程。共享 `DailyPlanView.vue` 同时服务教师和管理员，因此入口必须保持教师省略 `class_id`、管理员携带当前显式班级上下文。

- 支持单日、所在周、所在月和自选日期范围；默认围绕当前 `planDate` 计算，日期算法复用现有 `date-utils`，不要自行引入第三方日期库。
- 即使当前日期没有已创建计划，范围导出仍由服务端决定是否命中；前端不得自动扩大范围。
- 首次 `EXPORT_ACK_REQUIRED`：展示逐日期、逐栏目缺项，要求用户明确确认；确认重试只回传服务端 expected context。
- `context_changed`：明确告诉用户导出对象已变化，展示最新 facts，再次确认后才重试。
- `EXPORT_NO_MATCH`：提示范围内没有可导出的日计划，不产生空下载。
- `EXPORT_RANGE_TOO_LARGE`：显示 31 份上限并要求缩小范围。
- 成功下载后展示 `no_split_baseline`：“部分日计划没有拆分基准，已按最终内容导出且未标红”。该提示来自本次成功响应 header，不能只根据页面当前计划预判。

导出按钮对同班只读教师同样可用；是否可编辑计划不决定是否可导出。

### 周计划入口与交互

- `WeeklyPlanView.vue` 提供单份导出：默认当前确认版本；在既有确认历史/查看确认版本交互中允许导出显式 `confirmed_version`，不得导出草稿。
- `WeeklyPlanListView.vue` 提供日期范围合并导出，仍由服务端按教学日相交选择整份、去重并排序；管理员复用时带当前 `classId`，教师路径完全省略。
- 未确认计划不伪装成可下载草稿；单份导出时由服务端返回 `CONFIRMATION_NOT_FOUND`，前端给出清晰中文提示。
- `EXPORT_NO_MATCH` 提示范围内没有已确认周计划；`EXPORT_RANGE_TOO_LARGE` 显示 8 份上限。
- 成功下载后若 header 含 `confirmed_not_latest`，必须提示“导出的是已确认版本，但未包含最新变化”；可按原因细分 `draft_ahead/stale_sources/superseded/recorded_stale`，但不得阻断已经成功的下载。

按钮 loading、防重复点击和对话框关闭后的过期响应保护沿用现有页面 request id/状态模式。不要引入新前端依赖或新测试框架；仓库当前没有前端测试设施，使用 TypeScript 检查、构建及片 4 浏览器验收承接真实交互。

## 后端测试

新增片 3 定向 schema/路由/下载单元测试，建议独立为：

- `backend/tests/unit/test_i5_export_api_schemas.py`
- `backend/tests/unit/test_i5_export_api_routes.py`

mock 测试不得冒充数据库一致性验证。至少覆盖：

1. 两类 schema 的 `extra=forbid`、严格类型、日期顺序、周计划模式互斥、教师/管理员 class_id presence 语义。
2. 完整权限矩阵：未登录、待分配教师、教师本班/跨班、同班非创建者、管理员缺 class、管理员正确/错误 class；单份周计划 id 不因可猜测而越权。
3. 日计划首次缺项 409、匹配 context 成功、版本/缺项/对象变化再次 409、最新缺项归零仍需再次确认、客户端伪造 facts 不被信任。
4. 无匹配 404；31/32 日计划、8/9 周计划边界；超限不调用 generator、不写审计。
5. 当前/显式历史确认版本、未确认、伪造版本、范围只导出确认计划。
6. `WordTemplateError`、其他生成错误、读取/指针错误、审计提交错误的状态/code；所有失败均无成功文件、无成功审计。
7. 成功响应 bytes 与 generator 结果一致，MIME、Content-Disposition、no-store、nosniff、警示 header 正确；中文/空格/危险班名文件名安全。
8. 成功审计恰一条且字段正确；生成成功但 commit 失败不返回文件；重复请求各自独立鉴权和记录。
9. main 已注册两条路由；删除 I4 时代“导出路由不存在”的过时断言，只改为片 3 的正向契约断言，不放宽其他路由边界。

## 隔离 MySQL 8.4 集成验证

用户已授权本片使用一次性隔离 MySQL 容器、对白名单测试库执行现有迁移并运行 I5 集成测试。沿用 I3/I4 guard 思路，新增 I5 专用 guard/support/test，绝不连接或清理非白名单数据库；先打印并断言 host、port、database、MySQL 版本和 Alembic head，再运行测试。

使用独立容器/端口/数据库名，避免复用或污染历史环境。至少验证：

- 真实 schema 上教师本班、同班非创建者、跨班、待分配教师和管理员显式 class 权限。
- 日计划范围、完整 facts + expected context、409 两请求间并发保存导致 context 变化。
- 周计划范围/单份读取不可变确认版本，未确认排除，显式历史版本与警示。
- 31/32、8/9 真实选择结果上限边界。
- 一次导出期间并发保存：生成内容等于请求内钉住版本，范围、版本、日历修订、动态列与表头来自同一一致性视图；不得仅用 mock 声称验证 REPEATABLE READ。
- 成功导出只新增一条 `operation_records` class 级 `export_word`；计划、内容、确认、指针、同步状态等业务表零写入。
- 生成/审计失败不留下成功记录；审计记录与文件发放的事务顺序符合本片决定。
- 返回 DOCX 是合法 ZIP 且包含预期钉住内容；本层只做 OOXML/字节检查，不启动 LibreOffice。

测试完成后停止并删除本片一次性容器/测试库；在报告中准确写明可恢复性。不要触碰用户其他容器、数据库或服务。

## 文档更新

完成并验证后最小更新：

- `docs/specs/word-export-implementation.md`：记录 2026-09-29 三项已决方案、错误语义、片 3 实施状态、精确测试数量和未执行项；修正“尚无路由/前端/审计”等已过时现状句。
- `docs/bootstrap/architecture-v1-readiness.md`：记录片 3 实施与隔离验证结果，下一步改为片 4 待授权。
- `README.md`：当前状态更新为 I5 片 1–3 已实现、片 4 未开始；更新实际后端单测、I5 集成、前端 typecheck/build结果。

不要修改 `ARCHITECTURE.md`、ADR 或模块 Contract；本片沿用已确认模块边界，不构成架构变更。不要把片 4 未执行的 LibreOffice、浏览器或 Microsoft Word 验收写成通过。

## 明确不做

- 不进入片 4，不启动 API、Vite、Chrome、LibreOffice 或 Microsoft Word 做正式验收。
- 不部署，不创建 PR，不安装系统软件。
- 不新增迁移、导出表、任务表、文件表、临时目录、对象存储、后台 worker、下载链接或清理任务。
- 不修改模板资产、模板哈希、片 1 选择/映射语义或片 2 OOXML 生成语义来迁就 HTTP/UI。
- 不实现调班、日历影响处理、删除/恢复、AI、提示词、持久任务或前端包体积优化。
- 不记录完整计划、facts、文件名、范围或版本明细到 `operation_records`，不扩大审计 schema。
- 不自行决定 §11.9。

## 验证与交付

至少运行并记录精确结果：

```bash
cd backend
UV_PYTHON_DOWNLOADS=never uv sync --locked
APP_DISABLE_DOTENV=1 .venv/bin/python -m unittest \
  tests.unit.test_i5_export_read_service \
  tests.unit.test_i5_export_mapping \
  tests.unit.test_i5_word_export_docx \
  tests.unit.test_i5_export_api_schemas \
  tests.unit.test_i5_export_api_routes -v
APP_DISABLE_DOTENV=1 .venv/bin/python -m unittest discover -s tests/unit -q

# 使用本片专用 guard 和隔离 MySQL 连接串运行新增 I5 integration；
# 命令与实际容器/端口/数据库名写入结束报告，不把凭据写入仓库。

cd ../frontend
npm run typecheck
npm run build

cd ..
git diff --check
git status --short
```

如前端构建继续出现既有主包体积警告，准确记录为非阻断既有项，不在本片顺手做路由拆包。

全部检查通过后检查最终 diff，确认没有纳入 `.codex/config.toml`、`docs/bootstrap/current-review-opencode-prompt-2026-09-28.md` 或其他用户既有修改。应提交本提示词、片 3 代码/测试和直接相关文档，按当前仓库既有流程 commit 并 push 当前分支；不要部署，不要自动进入片 4。

结束报告必须包含：实际基线、三项已确认决定的落地方式、修改文件、两条 API 与 schema、权限/409/警示/上限/文件名/审计实现、前端入口、定向与全量单测精确数量、隔离 MySQL 环境及各案例结果、前端 typecheck/build、容器清理结果、commit/push 结果、未执行项和剩余风险。提供最终 diff 摘要供审阅。

---
