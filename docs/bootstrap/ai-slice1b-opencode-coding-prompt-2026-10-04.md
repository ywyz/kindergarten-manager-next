# 基础配置与提示词 1B：OpenCode 编码交接（2026-10-04）

用户本轮要求先定稿 1B API／权限设计与编码提示词，再交 OpenCode 实施。[1B 定稿规格](../specs/ai-settings-api-1b.md)为固定方案，[1A 收口](ai-slice1a-closeout-review-2026-10-04.md)为进入本片依据。本文仅授权 1B，不沿用历史提示词的“不进入 1B”，也不扩展到 1C 或后续切片。

## 执行提示词

~~~text
你是 kindergarten-manager-next 业务代码唯一写入者 OpenCode。协调者负责规划、设计和只读审阅。用户已要求先定稿 1B API／权限设计与编码提示词，再交你实施；本次完成已定稿 1B，不重新规划、不仅交预检清单、不进入 1C。

先读 AGENTS.md、ARCHITECTURE.md、ADR 0002、AI Service／提示词／日志 Contract、docs/specs/ai-settings-api-1b.md，再读 AI Service／提示词实施规格、1A v3、最新 ai-slice1a-closeout-review-2026-10-04.md 及第二轮补修结果。1A 历史未通过审阅保留，最新收口允许进入 1B；过去提示词禁止 1B 是旧片范围。本轮唯一 API 工程定稿以 ai-settings-api-1b.md 为准，沿用 1A 完成的 R1–R7、S1–S5，不回退它们。

记录开工 HEAD、git status 和既有修改；保留全部未提交代码／文档，不回退、不覆盖、不清理或提交他人修改。不读 .env 或现有私密密钥，不复制旧项目，不安装 Skill/MCP，不启动额外编码代理。不得 SSH、部署、commit/push 或启动产品 API/Vite/worker 服务器。

本次授权：
1. 新增本人 AI 配置 GET/PATCH/DELETE、个人提示词列表／详情／显式 initialize／编辑／accept-default／reject-default／adapt、管理员默认 GET/PATCH，共 12 条接口；实现严格请求、白名单响应及固定错误映射。
2. 仅写本片 router（建议 app/routers/ai_settings.py）、schemas.py 的独立新区域、main.py 的路由注册及 1B 安全校验异常分支，以及本片 unit/integration 测试。可在 prompt_service.py 最小增加只读详情字段、管理员 read_default 和默认写结果 guidance_fields，以支撑定稿 DTO，报告原因。不得改 models、迁移、依赖/锁、auth_service、日周/Word 业务或 frontend。其他服务若暴露缺陷先回报协调者，不自行扩展修复范围。
3. 允许新建一次性 mysql:8.4.11 容器，仅 127.0.0.1:13387；仅 kindergarten_test_ai1a、kindergarten_test_ai1a_fresh。沿用已审阅 tests/integration/ai1a_guard.py，AI1A_TEST_ALLOW_DESTRUCTIVE=yes＋AI1A_TEST_DATABASE_URL，全程 APP_DISABLE_DOTENV=1。允许该专用资源内迁移／造数／清理，允许拉取该镜像；不安装 Docker、不改宿主服务、不复用预存容器／卷、不连接远程验收／共享／生产库。仅本轮合成凭证及主密钥，导入配置前清除继承的 DATABASE_URL／AI_MASTER_KEY／AI_MASTER_KEY_ID，guard 在每次连接及 Alembic 子进程之前验证。连接字符串、密码和主密钥不写报告或打印。

严格落实定稿规格，不自行改变 API 字段或产品行为：
- 所有接口从现有 cookie get_auth_snapshot 构建身份，个人 target 固定为 snapshot.account_id；待分配教师与管理员也能维护本人设置。无他人查询入口、无客户端 account_id/role。管理员入口路由先拒绝 teacher，服务写事务仍二次核验真实角色与会话。复用 1A 锁序与事务，不在路由直接写 ORM 或额外 commit/retry。
- 所有新请求 extra=forbid、严格类型，整数拒绝 bool/浮点/字符串。GET 无写入。写方法沿用 JSON＋精确 Origin；DELETE 携带 JSON expected_version，initialize 携带空 JSON 对象。所有成功及失败 no-store。
- 配置 PATCH 完整提交 protocol_id/base_url/model 和 expected_version，secret 可省略。用 model_fields_set 保持省略与显式 null 的区别；省略映射 SECRET_UNSET，null/空串/错误类型 422，新非空字符串原样轮换。输出只用脱敏 AiConfigView 显式 DTO，无 head 对外 version=0；固定遮罩 ********，无尾码、key_id、密文、内部解密对象。ready 仅本地认证状态，不声称连通供应商。缺/错主密钥 GET 200 降级；DELETE 不依赖解密；需要加密/保留密文的 PATCH 固定 503 AI_CONFIG_UNAVAILABLE 且无写增量。
- 详情必须同时提供最新默认文字与本人当前文字、latest guidance_fields 与 based_guidance_fields、版本与派生适配/更新状态。新只读方法在同一 DB 快照内取得；已知任务缺契约/默认为 503，不返回假可用状态。不要只序列化目前 read_task 不完整 dict，也不要把默认自动合并到个人版本。管理员 GET 必须走验证权限的只读服务。
- 动态字段校验使用已发布数据库 contract；普通 PATCH 按本人 based contract，待适配仍允许旧字段编辑但不能解除适配；accept/reject 待适配 409。adapt 完整当前字段集、旧 contract 409、未知/缺字段 422。不得把固定 v1 字段写进 API schema，不能改运行时 TASK_REGISTRY 冒充 v2 发布。
- reject 不推进 personal_revision，重复有效拒绝幂等且可之后接受；accept 仅替换所选非空无重复字段。initialize 显式且幂等，不因 GET 初始化。成功写响应取本次已提交服务结果，不再读更晚 head 冒充本次版本；管理员发布只改文字，不提供 schema 编辑入口。
- 1B RequestValidationError 路径分支统一固定 422 VALIDATION_ERROR，无 fields/原 msg/loc/input/ctx/body；包括 secret、非法 URL userinfo/query、未知恶意键、嵌套 guidance 键值、非法 JSON 的安全边界。既有路由处理保留。所有 typed 服务错误只映射固定 code/message，raise from None，不日志原始异常/含输入的 DTO。未知任务 404 TASK_TYPE_NOT_FOUND；已知任务缺库内种子 503。不要 catch 所有 ValueError/IntegrityError 后冒充 409。具体映射表逐项执行。

验证按规格 B1–B6 执行，不能用旧 607 单元／50 集成结果代替本轮：
1. 新增纯 ASGI 注册/序列化/权限/schema/middleware/错误测试，沿用标准库 ASGI 驱动，不新增 httpx/pytest 或依赖，不启动网络服务器。测试 12 条接口与所有输入 DTO；密钥合成标记在成功和所有错误 HTTP body/应用日志中均不可见，测试不打印标记。清理 dependency override/mock，不污染全量测试。
2. 新增真 MySQL ASGI 集成，经过真实 cookie、get_auth_snapshot、服务和数据库（不 mock 业务服务或身份依赖）。覆盖本人隔离、管理员本人独立配置、teacher 默认 403、待分配本人设置、失效会话；真实另一连接在 snapshot 后/服务锁前撤销或停用，必须 401 且无版本/审计增量。测试夹具只可控制请求时序，不能伪造已复核身份。
3. 真库覆盖所有 GET 无副作用，版本冲突和非法结构全回滚；默认更新/部分接受/拒绝/再接受/幂等；实际发布 v2 后普通编辑旧字段保持待适配、accept/reject 阻断、旧 contract 拒绝、完整适配后新字段可编辑；重连核对真实 head/版本/事件/审计/处理标记及 accounts.version。缺/错主密钥 API 降级和清除/保存边界实际执行。
4. 全量 backend/tests/unit，原 50 项 1A MySQL 测试及新增 1B MySQL 测试；保留并执行缺/错密钥下手工日周与 Word 定向回归。检查两库实际 Alembic current 及 repository heads=20261003_ai1a_config_prompts、uv lock --check --offline、git diff --check。不能安装新依赖、下载 Python 或更新锁。
5. 仅删除本次容器及专用卷；必须记录确切容器和所有卷 ID、清理命令与检查结果，不删其他容器/卷/镜像。资源不可用先完成独立工作并报告真库阻塞，不换数据库、不虚称通过或收口。

新增 docs/bootstrap/ai-slice1b-implementation-result-2026-10-04.md：列实际 HEAD/文件、12 条路径与 DTO、B1–B6 对应测试名/命令/实际数量/失败或 skip、无 secret 证据、真 cookie 与撤销时序、GET 无写与事务持久/回滚、迁移 head、依赖锁、确切资源身份和清理结果、偏离及未执行项。不得含密钥、凭证、DSN；区分实现/自动测试/产品验收。保留 1A 所有历史报告，不改写历史覆盖缺口。

禁止 1C 前端/浏览器产品验收、worker、transport/DNS/供应商调用、AI测试调用端点、任务/调用日志表、候选采用、材料闭环、secret 清理、完整 W6、部署、commit/push。正常命名组织自行落实；偏离定稿接口/行为或额外文件范围先回报协调者。产品不确定事项回报，系统架构变更先停并提 ADR 草案。交付报告后停止等待协调者只读复审。
~~~

## 本轮交接记录

2026-10-04 协调者完成定稿和文档 `git diff --check` 后，以本文件附件启动本地 OpenCode v2.0.21；会话 `ses_efb0f9c59ffeB20oUSDWOMrfbQ`，标题 `kindergarten-manager-next 1B API 权限 2026-10-04`，工作目录为本仓库。已观察 OpenCode 读取 1B 定稿规格、1A 收口记录并记录 git 状态／HEAD（1647fc934d41b29a844a807d454031e66a2b45af），确认交接已开始执行。

启动环境禁用 dotenv，移除继承的 DATABASE_URL／AI_MASTER_KEY／AI_MASTER_KEY_ID 及 AI1A 测试开关／连接串；后续仅允许按上述提示词建立本次合成测试资源。协调者仅写设计／交接和规格接续文档，未写业务代码。此记录仅确认已交接、实施进行中，尚无 1B 交付报告、测试通过或复审收口结论；完成状态以独立结果报告和后续协调者复审为准。
