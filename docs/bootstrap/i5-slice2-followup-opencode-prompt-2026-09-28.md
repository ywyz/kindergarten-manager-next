# 给 OpenCode：I5 片 2 审阅后窄修复

以下正文可直接交给 OpenCode。范围只包括 I5 片 2 固定模板 DOCX 生成的三处已复现缺陷、对应测试补强及直接相关状态文档收敛；不授权 I5 片 3/4、路由、前端、数据库/schema/迁移、审计、LibreOffice/浏览器验收、部署或其他功能。

---

请在仓库 `/home/ywyz/code/kindergarten-manager-next` 完成 I5 片 2 的审阅后窄修复。

先读取并遵守：

- `AGENTS.md`
- `docs/specs/word-export-implementation.md`，重点 §5.1–§5.5、§10.2、§12 片 2
- `docs/bootstrap/i5-slice2-opencode-prompt-2026-09-28.md`
- `backend/app/services/word_export_mapping.py`
- `backend/app/services/word_export_docx.py`
- `backend/tests/unit/test_i5_word_export_docx.py`

开始先核对实际 HEAD、最近提交和工作区。审阅基线是提交 `a9db25f`；如已有后续提交，只核对与本任务相关的差异。保留用户已有 `.codex/config.toml`、`docs/bootstrap/current-review-opencode-prompt-2026-09-28.md` 及其他未提交修改，不覆盖、不回退、不顺手整理。不要启用或安装 MCP/Skill，不要修改或重新生成两份模板资产。

## 已确认缺陷

以下问题已通过当前代码和最小复现确认，不需要重新讨论产品语义。

### F1（P1）：合并日计划只输出第一份计划的表头

`generate_daily_export_docx()` 在循环外只读取 `views[0]` 的 `header`，仅生成一次标题和副标题；第二份及后续计划只有分页符和表格。范围导出可能包含不同创建教师，因此后续计划会丢失自己的 `school_name/grade/class_name/creator_display_name`，并被首份表头错误代表。

修复要求：

- 每一份日计划都必须形成完整计划块：自己的标题、自己的副标题、自己的表格。
- 第一份之前不增加分页符；第二份及后续计划前各有且仅有一个分页符。
- 每份表头只使用该份 view model 的 `header`，不得复用首份值，也不得在生成层重新查询或推导。
- 保持输入顺序；不改变表格字段映射、模板格式、标红算法或 view model。
- “单份与合并中同份内容语义一致”的断言必须覆盖完整计划块，不能继续只比较表格正文。

至少新增回归测试：构造两份 `school_name/grade/class_name/creator_display_name` 均不同的日计划，断言两组表头各出现一次、顺序正确、表格日期正确、只有一个份间分页符，第二份不被第一份表头替代。

### F2（P1）：周计划表头遗漏 `grade`

片 1 映射层已经在 `view["header"]` 中携带 `grade`，规格 §5.2/§5.3 要求周计划表头输出创建时快照的 `grade` 与 `class_name`；当前生成器的“班级”字段只输出 `class_name`，`grade` 完全未消费。

修复要求：

- 周计划班级表头同时输出 `grade` 与 `class_name`。
- 沿用日计划表头的空值过滤方式，以清晰空格连接非空字符串；不得发明新默认值，也不得从当前班级资料回填。
- 补充断言，使用可区分的年级与班名，分别确认二者存在；不要仅用本身已经包含年级字样的班名掩盖缺陷。

### F3（P2）：日计划反思栏重复栏目名

受控日模板反思行左侧单元格已经固定包含“一日活动反思：”；当前生成器又在右侧业务内容单元格添加同一标签，生成文本出现两次栏目名。

修复要求：

- 保留模板左侧固定栏目名。
- 右侧单元格只写 `reflection` 值；空值保持为空，不重复标签、不回填模板样例。
- 测试需同时断言：栏目名在该计划表格中恰好出现一次，反思正文存在；空内容时也只有左侧固定栏目名。

## 测试补强与回归边界

在 `backend/tests/unit/test_i5_word_export_docx.py` 做最小补强，优先复用现有 mapping view model 夹具和 OOXML 检查 helper，不复制业务映射规则。除上述三项外，既有 W1–W6、ZIP member 保留、模板哈希、动态列、标红与编号断言必须继续通过。

不要通过放宽断言、删除字段、把完整计划语义再次缩小为“仅表格相等”来使测试通过。不要更改片 1 映射行为来迁就生成器。

## 状态文档收敛

代码和测试通过后，最小修正下列当前状态矛盾：

- `docs/specs/word-export-implementation.md` §14 仍称片 2 生成器、`lxml` 尚未实施；改为准确反映片 2 已实施并完成本轮 F1–F3 修复，片 3/4 未开始。
- `README.md` 开头仍称 I5 片 2 未开始、模板/依赖/生成器未实施；更新为 I5 片 1–2 已实现，片 3–4 未开始，并更新当前后端纯单元测试实际数量。
- `docs/bootstrap/architecture-v1-readiness.md` 的 I5 标题仍写“片 2 已授权待实施”；改为片 2 已实施并完成审阅后收敛，片 3 待决定/授权。保留后文已有片 2 实施证据，并补记本轮修复和实际测试结果。

文档只记录可验证事实。不得声称 LibreOffice、Microsoft Word、API、权限、下载、MySQL 或浏览器已经通过。不得改写历史审核报告，不修改 `ARCHITECTURE.md`、模块 Contract 或 ADR。

## 明确不做

- 不进入 I5 片 3，不新增 schema、路由、响应头、文件名、前端导出入口、409 HTTP 流或审计记录。
- 不决定 §11.1 导出上限、§11.5 导出审计、§11.6 下载形态；它们仍须在片 3 前由用户确认。
- 不运行 MySQL、API、Vite、浏览器、LibreOffice 或 Microsoft Word。
- 不新增或升级依赖，不修改 `backend/pyproject.toml`、`backend/uv.lock`。
- 不修改模板 docx、模板哈希、片 1 读取/映射语义、数据库模型或迁移。
- 不重构无关 helper，不处理前端包体积告警，不部署。

## 验证与交付

至少运行：

```bash
cd backend
UV_PYTHON_DOWNLOADS=never uv sync --locked
APP_DISABLE_DOTENV=1 .venv/bin/python -m unittest tests.unit.test_i5_word_export_docx -v
APP_DISABLE_DOTENV=1 .venv/bin/python -m unittest discover -s tests/unit -q

cd ..
git diff --check
git status --short
```

另外用测试或一次不写仓库文件的最小复现明确证明：

1. 两份不同日计划的两组表头均保留且各自归属正确；
2. 周计划表头同时包含独立的 `grade` 和 `class_name`；
3. 日计划反思栏目名不再重复。

完成后检查 diff，确认没有纳入 `.codex/config.toml`、`docs/bootstrap/current-review-opencode-prompt-2026-09-28.md` 或其他用户既有修改。按当前仓库既有交付流程提交并 push 当前分支；不要部署，不要自动进入片 3。

结束报告必须包含：实际基线、F1–F3 根因与修复方式、修改文件、每项新增回归断言、定向及全量测试精确数量、`uv sync --locked`/`git diff --check` 结果、提交与 push 结果、未执行项，以及片 3 前仍待用户确认的 §11.1/§11.5/§11.6。提供最终 diff 摘要供审阅。

---
