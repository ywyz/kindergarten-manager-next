# 给 OpenCode：I5 片 2 固定模板 DOCX 生成

以下正文可直接交给 OpenCode。用户已授权 I5 片 2、模板副本入库和新增锁定 `lxml` 依赖；本任务不授权片 3/4、路由、前端、数据库/schema/迁移、审计、LibreOffice 正式验收、部署或其他功能。

---

请在仓库 `/home/ywyz/code/kindergarten-manager-next` 实施 I5 片 2“固定模板 docx 生成”。

先读取并遵守：

- `AGENTS.md`
- `docs/specs/word-export-implementation.md`，重点 §5、§6、§10.2、§11.2–§11.4、§12 片 2
- `docs/specs/word-template-validation.md`
- `docs/specs/word-template-prototype-results.md`（仅作旧模板历史证据）
- `backend/app/services/word_export_mapping.py`
- `backend/tests/unit/test_i5_export_mapping.py`
- `backend/app/assets/word_templates/README.md`

开始核对 HEAD 和工作区，保留用户已有 `.codex/config.toml`、旧提示词等未提交修改，不覆盖或回退他人工作。审阅时已提交基线为 `22b41bd`；模板资产与本提示词可能处于未提交工作区。不要启用或安装 MCP/Skill，不要删除 Downloads 原件。

## 已确认决策和资产

- 生成形态：内存生成完整 docx bytes，不写临时文件。
- 生成方案：标准库 `zipfile` + `lxml` 定点修改 OOXML；不要改用 `python-docx`。
- 依赖：在 `backend/pyproject.toml` 增加稳定版 `lxml>=6.1,<7`，用 uv 更新 `uv.lock`，随后 `UV_PYTHON_DOWNLOADS=never uv sync --locked`。不得安装预发布 7.x。
- 日模板：`backend/app/assets/word_templates/daily_plan.docx`，SHA-256 `99008f92ae42cc87da7e42e84009ffcd8bbefdf43602f09a59ae4027e5ddc9bd`。
- 周模板：`backend/app/assets/word_templates/weekly_plan.docx`，SHA-256 `24ccaa9e557522c40a653643381e31f319ea6ae5e9f3e30e9dfa41da21986aed`。
- 周模板哈希不同于 2026-09-20 原型记录的旧版本；必须以当前资产重新分析锚点、表格、合并单元格和动态列，不能照抄旧原型偏移或声称旧 31 页证据已覆盖当前模板。
- 运行时只读取仓库受控资产，不依赖 Downloads/桌面绝对路径。缺失、不可读、非合法 docx 或哈希不符须抛出生成层明确异常，供未来片 3 映射为 `EXPORT_UNAVAILABLE`；不得自动寻找替代模板。

## 实现范围

新增 `backend/app/services/word_export_docx.py` 和定向单元测试（建议 `backend/tests/unit/test_i5_word_export_docx.py`）。生成层：

1. 只接收片 1 映射层已经产生的日/周 view model，返回完整 docx `bytes`；不接触 Session、权限、HTTP、业务查询或版本选择。
2. 以受控模板 ZIP 为基础，主要定点修改 `word/document.xml`。未修改的 ZIP member 内容必须原样保留；不要解压到磁盘。
3. 使用安全、确定性的 XML parser 配置，不解析外部实体、不访问网络。不要对不受信任 XML 启用 DTD/实体解析。
4. 将模板示例内容全部替换为 view model 值；空值保持栏目结构但内容为空，不回填模板示例，不发明默认业务数据。
5. 日计划覆盖固定栏目、活动主题、过程 run 级红色、无基准不标红、游戏/目标/指导/支持策略和表头；每份计划从新页开始，合并按输入顺序，不引入额外空白页。
6. 周计划覆盖表头、主题、日期列、晨谈/集体活动、两项集体游戏+一项自选、重点区域、材料与周栏目。固定周一至周五，周末仅 teaching 时增列；支持五、六、七列及零教学日周；假期/缺计划/学期外占位不得混淆。
7. 处理模板“本周重点”内容槽的自动编号继承，避免多周合并时编号续接；只移除业务内容槽不应继承的编号，不破坏其他模板格式。
8. 生成结果必须是合法 OOXML ZIP；不得修改输入 view model、模板文件或任何数据库状态。

若当前模板结构无法在不改变既有产品行为的前提下唯一映射，停止该分支并报告具体表格/单元格证据；不要猜测教师工作流，也不要修改 Contract、ARCHITECTURE 或片 1 映射语义来迁就模板。

## 结构机检测试

测试不得依赖 MySQL、HTTP、LibreOffice 或浏览器。至少覆盖：

- 模板存在、哈希匹配、ZIP/关键 member 完整；错误资产分支确定失败。
- 当前两份模板的结构基线（表格数、关键标签/锚点、必要合并结构），尤其为新周模板建立显式断言。
- W1 型单日日计划、全空内容、无基准过程。
- W2 型 run 标红：新增/替换为红色，未改文字保持模板颜色；纯删除不输出，不增加删除线。
- W3 型多日日计划：顺序、分页符、无样例残留、单份与合并中同份内容语义一致。
- W4 型周计划：普通五列、教学周末增列、六/七教学日、假期、缺计划、零教学日周。
- W5 型多周合并：输入顺序保持片 1 已排序结果，每份从新页开始，无额外空白计划块；“本周重点”编号不跨周续接。
- W6 型确认快照：两集体+一自选、重点区域、材料和周栏目逐字段映射，不混入样例或重新推导来源。
- XML/文字检查：关键文字及字符多重集、红色 `w:r`、分页符、动态列数、合并关系、无模板示例人名/正文残留。
- 除明确允许修改的 OOXML member 外，其余 member 字节与模板一致；生成不改原模板哈希。

测试夹具直接构造或复用 `word_export_mapping` 的 view model；不要为了测试复制第二套业务映射规则。可以增加只服务于 OOXML 结构的测试 helper，但不要创建文字镜像实现。

## 明确不做

- 不新增导出 API、schema、路由、响应头、文件名或前端入口。
- 不实现范围上限、审计记录、同步下载 HTTP 流程或后台任务。
- 不运行 MySQL、API、Vite、浏览器或 LibreOffice；LibreOffice 产品验收属于片 4。
- 不修改迁移、模型、片 1 读取/映射行为、ARCHITECTURE.md 或 Contract。
- 不自动进入片 3。

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

完成后更新 `docs/specs/word-export-implementation.md` 和 `docs/bootstrap/architecture-v1-readiness.md` 的片 2 实施状态，准确记录依赖版本、资产哈希、结构机检数量和未执行项。报告当前模板与旧原型的证据边界，不声称 LibreOffice、Microsoft Word、API、权限或下载流程通过。

全部检查通过后，按用户要求提交并 push 当前分支；提交前确认不包含 `.codex/config.toml` 和 `docs/bootstrap/current-review-opencode-prompt-2026-09-28.md` 的既有用户修改，也不提交 Downloads 原件或 `.codegraph/`。应提交本次已经准备的两份受控模板、模板 README、片 2 提示词及直接相关规格/readiness 更新。结束时报告 commit、push 结果、修改文件、生成策略、模板结构差异、测试精确结果及仍待片 3 决定的 §11.1/§11.5/§11.6。不要部署，不要进入片 3。

---
