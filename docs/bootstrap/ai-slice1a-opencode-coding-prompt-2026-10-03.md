# 基础配置与提示词1A：OpenCode编码交接（2026-10-03）

状态：用户要求协调者完成规划／设计、OpenCode只负责编码；设计已收敛为[实施清单v3](ai-slice1a-implementation-checklist-2026-10-03.md)。本文件是下一步交接提示词；协调者本轮没有启动OpenCode、写业务代码、安装或创建数据库。用户将以下提示词交给OpenCode执行时，授权范围以正文为准。

2026-10-04后续状态：本提示词已由OpenCode执行，协调者首轮代码审阅未通过。当前下一步改用[1A补修提示词](ai-slice1a-repair-opencode-prompt-2026-10-04.md)，依据[审阅报告](ai-slice1a-review-2026-10-04.md)补修；以下保留原编码授权记录。

## 可直接复制的提示词

~~~text
你是kindergarten-manager-next业务代码唯一写入者OpenCode。协调者负责规划、设计及审阅；本次按已定稿的“基础配置与提示词1A”编码并验证，不再开展新一轮设计或只交预检清单。

本次授权：
1. 实施docs/bootstrap/ai-slice1a-implementation-checklist-2026-10-03.md的v3：7张表、固定快照种子迁移、7类registry及22条默认正文、个人配置加密／版本服务、默认和个人提示词版本／适配服务、本人隔离及设置变更审计、离线URL校验、最新与钉住版本解析。
2. 将既有锁定cryptography==50.0.1声明为直接依赖，更新所需项目锁元数据，在backend/.venv按锁同步依赖。沿用已有Python、uv和unittest，不引入SDK、HTTP客户端、pytest、jsonschema或其他组件，不下载新的Python解释器，不升级其他依赖。
3. 建立专用guard，创建并运行一次性本地MySQL 8.4/InnoDB自动测试资源，完成单元和定向真实MySQL验证。容器仅loopback 127.0.0.1:13387；数据库白名单kindergarten_test_ai1a、kindergarten_test_ai1a_fresh；独立AI1A_TEST_ALLOW_DESTRUCTIVE=yes、AI1A_TEST_DATABASE_URL；全程APP_DISABLE_DOTENV=1。允许在专用隔离库内建表、迁移、造合成数据及测试清理，不连接远程验收、共享或生产库。mysql:8.4.11镜像可拉取用于该一次性测试；不得安装Docker或修改宿主服务配置。

先读AGENTS.md、ARCHITECTURE.md、ADR 0002、AI Service／提示词／日志Contract、1A准备文件、清单v3，再读AI Service／提示词／持久任务／材料四份规格。准备文件的只读预检提示词是历史阶段记录，本提示词取代该阶段限制；产品规则和架构约束仍有效。清单v3是本片具体工程细化，不得沿用v1/v2冲突规则。

开工记录HEAD、git状态和既有修改；保留当前所有未提交文档，不恢复、不覆盖、不打包提交他人修改。不得读取.env或现有私密密钥，不复制旧项目，不新增Skill／MCP或业务实现者，不启动额外编码代理。

执行要点：
- 仅修改清单§1列出的本片文件；可增加同范围单元测试及backend/app/services/内必要的纯内部类型／锁帮助文件，报告原因。不改已有业务模型、迁移或routers/schemas/frontend。服务身份校验使用现有安全规则，不为便利重构auth_service。需要偏离设计时先停下回报协调者，正常命名和代码组织可自行落实。
- 新配置版本保留secret时，先解密旧版本，再以新nonce及新版本AAD重新加密；旧行不变。缺失或格式错误的主密钥只暂停AI，不阻断启动／手工路径。清除无需解密；已清除版本的非密钥更新仍无密钥。设置视图和内部解密对象分型，异常／repr／测试输出不泄漏secret。
- registry严格类型、递归extra=forbid；下午户外为单对象；节日输入为明确列表；周游戏可引用输入已有身份但不得生成新身份；材料extracted要求非空证据及quote。结构验证与动态来源核对分开，不能把模拟引用声明为真实业务来源已验。
- 固定contract v1行作为锁锚点：个人写FOR SHARE，默认／测试契约发布FOR UPDATE。锁内当前契约使用locking read及populate_existing，不能依赖REPEATABLE READ普通快照。保持account→交互session→自身head→契约锁顺序，不反向拿业务锁。
- contract发布测试夹具采用独立DML事务，在DDL完成后拿排他锚点锁；不增加产品schema编辑入口。分别验证发布先／适配先两种合法提交顺序，不能用“之后读取发现过期”替代发布先提交时拒绝旧适配。
- reject不创建新个人版本。reject先提交时同expected的accept可随后成功；accept先提交时旧expected的reject冲突。重复拒绝先校验身份、expected及目标契约，再幂等返回。不要写“二者竞争恰一成功”的错误测试。
- 普通接受默认必须契约兼容，非空选定字段列表只替换选定文字；changed_fields只记录字段名。GET不推进已处理修订；初始化、接受／拒绝／适配按v3推进处理状态，不隐藏更晚默认更新。
- 版本/head/审计/事件同事务提交，实际失败全部回滚；账号审计记录真实accounts.version，不推进账号版本；school目标版本为NULL，种子created_by为NULL。不在operation_records写提示词全文。
- 历史迁移种子为固定字面量，不import运行时registry；JSON内容比较不依赖数据库键顺序。指定旧配置／提示词读取不更换版本，不清理secret，不登记任务。

验证：
1. 定向新单元测试通过，再跑全量backend/tests/unit作为集中models/config的直接回归；所有进程在导入配置前禁用dotenv。沿用unittest，不启动API／Vite／worker。
2. guard必须在任何测试或迁移连接前校验host、端口、driver、库白名单。为Alembic子进程只注入经guard校验的测试DATABASE_URL，禁止继承现有连接地址；迁移也必须受guard保护。
3. 空库及含I1–I4代表行库均upgrade至20261003_ai1a_config_prompts，比较原业务行／确认快照，验证复合FK／CHECK／唯一键。
4. 真实MySQL多连接验证初始化、同expected双写、两管理员默认发布、拒绝／接受两顺序、适配／契约发布两顺序、预先建立旧快照、版本/head/审计注入失败回滚及重连持久。按清单§9记录通过／失败／skip，不用mock数据库代替。
5. 无主密钥及错误主密钥下，对既有手工日／周计划服务和Word导出提供实际定向回归证据，不只检查import。无前端改动不跑前端；I1–I5无关集成套件不重复执行。
6. 核对uv锁定状态、实际迁移head、git diff --check。仅本片新增资源测试完清理：删除本次创建的容器及其专用卷，报告资源身份和清理结果，不删除预存容器、卷、镜像或其他库。

Docker／隔离端口／既有工具不可用时，不自行改装环境或换库；完成不依赖资源的编码和单元验证，明确报告真实MySQL验证阻塞及未执行项，不宣称1A完成。

禁止进入1B/1C或后续片；不实现API/UI、worker、transport、真实DNS／供应商调用、任务／调用日志表、候选采用、材料业务或secret清理。不启动产品验收服务器、不SSH、不部署、不commit／push。不把schema测试记为完整SSRF、真实AI、worker恢复或W6产品验收。

完成后新增docs/bootstrap/ai-slice1a-implementation-result-2026-10-03.md，报告实际文件、表与迁移、依赖及锁变化、命令和测试结果、并发/回滚证据、资源清理、未执行项及设计偏离。正文不得含测试凭证、密钥或数据库连接串。区分实现、自动测试和产品验收状态。

交付报告后停止，等待协调者只读审阅。缺产品决定回报；涉及系统级架构改变先停并提ADR草案，不自行扩展。
~~~
