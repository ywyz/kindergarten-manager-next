# 给 OpenCode：AI 设置剩余验收夹具工具（2026-10-07）

请在 `/home/ywyz/code/kindergarten-manager-next` 完成本地夹具工具和必要验证，业务及配套工具代码由你唯一写入。用户要求继续准备剩余验收并提供本提示词。此次任务到“工具可复审”为止，不部署、不连接验收服务器、不读取私密凭证或项目 .env、不创建远程资源、不发布真实远程契约、不修改服务主密钥、不 commit／push。

先读 AGENTS.md、ARCHITECTURE.md、ADR 0003、[夹具方案](ai-slice1c-fixture-plan-2026-10-07.md)、[Windows 报告](ai-slice1c-desktop-validation-2026-10-05.md)、提示词规格、1B／1C 规格。检查 git status，保留协调者所有文档修改及用户其他改动；不要 reset、stash、覆盖或替用户提交。

## 1. 明确范围

只做验收专用固定配方发布工具、目标保护和必要测试，不新增产品功能。用户已选方案 A：同契约旧默认可接受，不增加“target 必须最新”的后端检查。不实现 transport／worker／候选／材料／W6，不改运行时 registry、models、迁移、产品 API 或前端，不新增依赖、测试框架、Skill、MCP。

建议新增（开工先列最终清单，等价组织可以自行选择）：

- `backend/scripts/ai1c_acceptance_fixture.py`：只提供 inspect、publish-v2、publish-v3，不提供 reset/drop/truncate 或任意 map/schema 编辑功能。
- `backend/tests/unit/test_ai1c_acceptance_fixture.py`：目标校验、固定配方、预期状态及拒绝路径、输出去敏。
- `backend/tests/integration/test_ai1c_acceptance_fixture.py` 和独立 guard（需要时）：真实事务、回滚、锁与并发，只用一次性测试库。
- `docs/bootstrap/ai-slice1c-fixture-tool-result-2026-10-07.md`：实际修改文件、命令、结果和未执行范围。

协调者负责远程部署、备份恢复、密钥状态切换；本工具不读取 AI_MASTER_KEY，不负责启动服务或替 Windows 执行 DOM。测试模块可做测试，但运维工具不能导入 tests、借用破坏性 `_world`／reset 函数，也不能复制旧项目业务代码。

## 2. 连接前目标保护

仅从显式专用环境变量 `AI1C_FIXTURE_DATABASE_URL` 获取 DSN。先设置 APP_DISABLE_DOTENV=1，排除继承 DATABASE_URL／AI_MASTER_KEY／AI_MASTER_KEY_ID 对工具与子进程的影响；不要修改父 shell。模块 import 和 --help 不连库、不写库、不加载私密配置。

两种固定模式：

| mode | 允许目标 |
| --- | --- |
| acceptance | mysql+pymysql、127.0.0.1／localhost、13386、精确 `kg_next_ai1c_fixture` |
| integration | mysql+pymysql、127.0.0.1／localhost、13387、精确 `kindergarten_test_ai1c_fixture` |

任何其他 schema（特别是 `kg_next_i5_acceptance`）、host、port、driver、空目标、意外 URL query 路由参数，一律在建 engine／连接前拒绝。使用健壮解析，不把密码放命令行，不输出输入的 URL、查询参数、原始异常或 exception repr。inspect 也要 guard，不接受任意白名单参数覆盖。发布另需专用 `AI1C_FIXTURE_ALLOW_PUBLISH=yes`，缺开关不连接写入口；integration 破坏性准备使用独立开关，不能沿用其他切片开关。

连接后只读核对实际 DATABASE()、MySQL 8.4／InnoDB、唯一 migration `20261003_ai1a_config_prompts`、目标 task 和 v1 固定锚点存在。模型 import 不得触发 .env。应用／数据库权限最终由托管者核验；工具不能申请 GRANT、迁移或自动建库。

inspect 输出去敏 target 身份、迁移、最新契约／默认版本和字段名，不读／输出配置密文、密码哈希、指导全文。它只报告，无需 --allow-publish。

## 3. 固定发布与事务

只针对 daily_lesson_split，固定 v1 六字段顺序：theme、objectives、preparation、key_points、difficult_points、process。v2 移除 preparation，保留其余五字段并末尾新增 acceptance_support；v3 在 v2 基础上移除 process。每版默认全文是固定、无价值合成文字，完整 map 与字段集一致、每字段不超过8000。input_vars／output_schema 使用数据库上一契约快照原样复制，不改代码 registry。

publish-v2／v3 必须传入 `--expected-contract-version` 和 `--expected-default-revision`（严格正整数）。在单一事务内按既有协议取 v1 锚点 FOR UPDATE，再 locking read 最新 contract 与最新默认；校验上一契约字段和该契约最新默认 map 完整性、预期版本、允许的 v1→v2／v2→v3 顺序。默认 revision 使用该任务全部默认历史 MAX+1，不能按新 contract 从1重新编号。

原子追加一份 PromptContractVersion 和一份完整 PromptDefaultVersion；既有合法随机 ID、created_by=NULL、UTC时间。不得写 personal head／versions、accounts.version、school_settings 或其他任务；不得伪造 default_update 管理员事件。不得先提交 contract 再单独提交 default。后置验证失败也须 rollback，记录固定错误码。重复调用或旧 expected 全部拒绝且零增量，不做 UPDATE 覆盖、upsert 或“已存在就成功”的模糊幂等。

成功输出仅 task_type、旧／新 contract、旧／新 default revision、字段名及状态，可重定向到私密 manifest；版本全部取实际结果。SQLAlchemy engine echo=False，任何失败不能 traceback 输出 SQL参数／DSN／指导正文；exit非0，固定简短提示，私密诊断也不要包含 secret。不得通过临时改变日志级别导出原始SQL。

## 4. 有意义的验证

使用现有 Python unittest、SQLAlchemy和已装依赖。必要单元覆盖：错误目标在 engine 创建前拒绝；缺开关／非法 expected；import／--help无连接；配方完整性；固定错误输出不含合成敏感标记或 DSN。不要用纯 mock 事务测试宣称真库通过。

真库验证需独立受控资源：既有可用的一次性 MySQL 8.4、127.0.0.1:13387、精确 integration 库，绝不指向远程验收库。guard在任何测试及迁移连接前生效。若没有符合条件且已获资源授权的现成实例，先完成编码与离线测试，明确报告真库受阻和准确所需资源，不安装、拉镜像或创建数据库来绕过资源授权。

真实 MySQL 必须覆盖：v2/v3原子成功；个人文字／head和其他任务／业务表不变；重复与旧expected零增量；在第二份插入失败时contract/default一起回滚；与同任务默认发布争用固定锚点时正确顺序化，两个发布者持相同expected至多一个成功；两个场景不以改registry冒充。使用独立测试数据构造和故障注入，不把它带进运维工具。测试恢复只能作用于一次性精确integration库。

运行适当的后端单元回归（现有基线648项，但以实际发现及执行计数为准），不连其他库、不输出密钥；不因工具改动重跑无关前端全套。git diff --check必须通过。报告包含真正执行的命令／结果／计数、skip与受阻，不重复引用历史结果充当本轮通过。

## 5. 交付停止点

交付工具、测试、报告与不含凭证的具体使用方法（仅变量名／固定参数，不含DSN密码示例），说明下一次发布应使用现场inspect的expected。不要自动publish或串联多个阶段；Windows每阶段准备完成后由托管者单次发布并交回manifest。

报告须单列：编码／离线验证完成；真库执行或受阻；远程实例未准备；真实C5/V1/U3/C7仍待补验。发现现有产品代码问题只报告最短复现和文件位置，不越界修复。协调者收到报告后只读复审并完成远程执行清单；用户对具体远程资源操作的授权另记。
