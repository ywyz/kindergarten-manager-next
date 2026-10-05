# AI 1A 第二轮定向补修交接（2026-10-04）

直接交给OpenCode执行以下提示词。当前步骤是1A补修／补验，不是1B。

~~~text
你是kindergarten-manager-next业务代码唯一写入者OpenCode。协调者负责规划、设计和审阅。本次按已定稿方案完成1A剩余S1–S5；不重新规划、不进入1B、不仅交预检清单。

先读AGENTS.md、1A清单v3、首轮审阅和补修提示词、原始交付／补修报告，再读docs/bootstrap/ai-slice1a-re-review-2026-10-04.md。复审§2给出本次固定方案，沿用v3及R1–R7已完成修复；正常命名与组织自行落实，偏离规则先回报协调者。

记录开工HEAD和git状态，保留全部既有未提交代码／文档。不得回退、覆盖他人修改、读.env或现有私密密钥、复制旧项目、安装Skill/MCP、启动额外编码代理。不得commit/push、SSH、部署或启动产品服务器。

本次仅授权：修正ai_config_url、ai1a_guard及1A单元／集成测试；确有必要时在1A新增services内最小修复并报告原因。不要改models、迁移、依赖、已有日／周／Word业务、routers/schemas/frontend。本次不新增表或组件，不改产品Contract。

S1 URL：原始输入带?或#分隔符即BaseUrlInvalid；百分号编码路径保持原样。urlsplit及hostname/port访问的畸形解析异常也转为固定消息的BaseUrlInvalid，不回显原URL。新增末尾?、末尾#、空query后fragment、畸形括号／IPv6／端口测试；合法供应商前缀及路径保留仍通过。先在当前代码证明这些定向用例失败，再修复转绿。纯离线，不实现DNS／连接／transport。

S2 guard：Alembic失败的公开异常只保留已校验driver/port/库名、returncode及固定错误类别，移除原始stdout/stderr拼接，不把凭证原异常串或异常链带到traceback。畸形URL拒绝也使用固定安全消息。添加无连接单元测试：mock子进程返回含合成DSN、密码及密钥标记的stdout/stderr，断言str/repr/格式化traceback均不包含标记；测试合法与非法host/端口/driver/白名单、未启用时不连接。仅使用合成数据且不打印标记。guard模块加载前禁用dotenv并清除继承连接／主密钥环境；mock仅验证异常边界，不能替代真实MySQL业务测试。

S3 旧快照：重做K1成功场景，成功写之前不能先触发冲突。每条成功测试独立：普通SELECT建立REPEATABLE READ快照→另一连接提交新配置／个人版本／默认→旧事务普通读仍看见旧数据，确认事务未结束→直接用正确的新expected调用写入口。不得中间commit/rollback/关闭Session。分别验证配置保留secret、清除、个人编辑、个人接受、管理员默认发布。旧expected冲突另建独立Session与快照，不能借该rollback给成功场景刷新视图。用重连读检查版本/head、保留secret认证后的合成值、未选字段保留、事件／审计增量和真实accounts.version；不得仅断言返回值。若暴露实现缺陷，按v3 current locking read原则仅修本片服务，不变锁序、不重构auth_service。

S4 真实入口：删除或改名仅构造TaskStatus却声称真实list_tasks的测试，并在真库直接调用list_tasks，覆盖七类状态、本人隔离及GET前后head/版本/事件/审计无变化。E2必须实际发布v2：v1-based个人编辑仍按v1字段集且不解除待适配；另一场景初始化／适配到v2后，新字段assist_notes_v2可编辑成功，未知字段typed拒绝且全回滚。不修改运行时TASK_REGISTRY来冒充协议发布。

S5 约束与迁移样本：CHECK负例对已有合法head做UPDATE，仅破坏adaptation_state/required_contract_version关系，不再INSERT重复主键。断言错误码3819和ck_pph_adapt_ref，配置CHECK同样核对3819及具体约束名；失败后原行不变。迁移兼容样本升级前通过既有日／周服务选择至少一个真实来源并确认，断言草稿和确认JSON里真实引用与非空文本存在，再比较原16表整行及规范化JSON。不要为了造样本改业务服务；保留空库升级、固定种子比较、复合FK与唯一键验证。

环境授权沿用上一轮：允许新建一次性mysql:8.4.11容器，仅127.0.0.1:13387；白名单kindergarten_test_ai1a、kindergarten_test_ai1a_fresh。AI1A_TEST_ALLOW_DESTRUCTIVE=yes＋AI1A_TEST_DATABASE_URL，全程APP_DISABLE_DOTENV=1；guard在所有连接及Alembic子进程之前验证。仅用本次合成凭证／密钥，不继承私人DATABASE_URL或主密钥。镜像可拉取，不安装Docker、不改宿主服务配置、不复用预存容器／卷。专用资源内允许迁移／造数／清理；结束删除本次容器和专用卷，记录确切资源身份及清理检查结果，不删除其他容器／卷／镜像。资源不可用时完成独立工作、报告阻塞，不换库或宣称收口。

验证：先S1/S2定向失败转绿和S3–S5真库补验；再跑全量backend/tests/unit以及原／新增1A MySQL测试（无API/Vite/worker）。保留并执行密钥缺失／错误下手工日周与Word定向回归。核对两库实际迁移current及repository heads、uv lock --check、git diff --check；不安装新依赖、不下载Python、不升级锁。不要把598旧单元或42旧集成通过替代新增边界证据。

新增docs/bootstrap/ai-slice1a-repair2-result-2026-10-04.md，逐S记录实际文件、命令、测试数量、失败转绿或新增覆盖的真实证据、事务旧快照连续性、迁移head和资源清理／阻塞。明确上一轮URL/guard/list_tasks/R6覆盖声明存在缺口，并引用复审记录；保留旧报告历史，不重写为此前就正确。报告不含密钥、凭证、DSN，不虚称未实际执行的红绿复现。

禁止1B/1C、API/UI、worker、transport、供应商调用、任务／调用日志表、候选采用、材料闭环、secret清理、产品验收及完整W6。交付后停止等待协调者复审；涉及架构改变先停并提ADR草案，产品不确定事项回报。
~~~
