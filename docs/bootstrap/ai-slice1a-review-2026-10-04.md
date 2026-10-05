# AI 1A代码审阅与下一步（2026-10-04）

结论：**1A暂不收口，先交OpenCode定向补修及补验，不进入1B。** 业务代码继续由OpenCode唯一写入；协调者本轮只读业务代码、复跑无数据库单元测试并编写审阅／交接文档，没有安装、创建数据库、启动服务或部署。

依据：[v3设计](ai-slice1a-implementation-checklist-2026-10-03.md)、[编码交接](ai-slice1a-opencode-coding-prompt-2026-10-03.md)、[OpenCode原始交付](ai-slice1a-implementation-result-2026-10-03.md)。原始报告保留，不把实现者自报替换成协调者验收结论。

## 1. 本轮证据

- 在backend执行：APP_DISABLE_DOTENV=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests/unit -t . -q；**578项通过**。
- git diff --check通过。当前业务修改为1A新增服务／迁移／测试与models/config／依赖变化，未观察到API、前端或既有迁移改动。
- 用进程内合成身份／密文／密钥和未入库ORM对象复现下列问题；未读取.env、现有密钥或连接任何数据库。仅打印异常类型和布尔结果。
- OpenCode报告26项真实MySQL测试通过；容器报告已删除。本轮未重新建立MySQL资源，**未独立复跑这26项**，不宣称其失败；测试源文件中覆盖缺口另列。

## 2. 需补修事项

| 编号 | 级别／位置 | 发现与影响 | 定向处理 |
| --- | --- | --- | --- |
| R1 | 阻塞；prompt_service.py:38、164、590；ai_locks.py:161 | get_task_types引用未导入的ai_prompt_registry，任务列表无法工作；服务多处FieldViolation未导入，空patch等非法输入变NameError；未使用的latest_default_row_locked也引用未导入的PromptDefaultVersion。本轮均复现 | 补齐有效依赖；删除无调用的错误helper或使其符合命名锁语义。补任务列表真实入口及服务非法输入测试，不仅测试registry |
| R2 | 阻塞；prompt_service.py:528、614、909、1043 | 指导字段校验始终使用固定v1 registry。新增必需字段的合成v2映射在adapt进入数据库前即被FieldViolation拒绝；initialize／accept／update_default也存在同类版本错配。现有v2夹具所谓新增字段使用v1已有preparation，guidance_fields未改变，未验证真正适配 | 提示词设置以已发布的目标contract.guidance_fields做字段校验：init／adapt／default_update用最新目标契约；普通accept用已核对兼容的契约；personal_edit用当前个人based契约。保留8000字符、严格字符串和未知字段拒绝；固定v1输出registry与历史种子不被合成测试改写 |
| R3 | 阻塞；ai_config_service.py:122 | ready只验证主密钥格式，未认证当前密文，也未比较row.key_id。损坏密文＋不同key_id仍返回(True,None)，设置与执行就绪不一致。本轮复现 | 当前有secret时用行自身account/version/key_id完成认证解密校验；失败返回DECRYPT_UNAVAILABLE，返回视图不含解密结果、不持久缓存明文；缺secret仍MISSING_SECRET |
| R4 | 阻塞；ai_config_service.py:73 | DecryptedConfig是含明文secret的dataclass。repr／pickle防线不能阻止dataclasses.asdict和FastAPI jsonable_encoder，二者均产生明文secret。本轮已用合成secret复现；当前无API，未观察到实际对外泄漏，但不满足1A内部对象防误序列化要求 | 使用非dataclass、无__dict__/迭代字段出口的内部类型，secret以已有SecretStr封装，仅显式取值；通用序列化应拒绝或仅输出遮罩。未来API仍只用AiConfigView，不能以“尚无API”跳过本项 |
| R5 | 阻塞；ai_prompt_registry.py:105、238及枚举AfterValidator | 运行时before校验要求六个拆分字段、五个周游戏字段，而model_json_schema的required均缺失；group_kind等枚举也无enum，Optional字段的schema允许null但运行时拒绝显式null。本轮检查导出schema确认。字段协议种子因此与实际验证器不同，后续组装协议会误导模型 | 必填字段无默认；枚举用Literal或等价可导出声明；可省略但不可null的schema准确表达。测试导出schema的required、enum、null和extra边界；修正尚未部署的本轮1A固定种子，不改I1–I4迁移 |
| R6 | 阻塞；ai_config_service.py:111、prompt_service.py:118、183 | head使用locking read，但写路径读取其指向的版本仍是普通读。若Session先建立旧REPEATABLE READ快照、另一连接推进版本，之后锁到新head可能读不到新版本，触发断言／NoResultFound。管理员发布的_latest_default_row(share=False)也是普通快照读，可能计算重复修订并泄出IntegrityError。这是静态路径确认，本轮未在MySQL复现 | 写路径读取head指向的immutable版本也须current locking read＋populate_existing；默认发布无论共享／排他分支均locking read。纯展示读保持只读；在真MySQL以预先建立普通快照的Session补验配置保留／清除、个人编辑／接受和管理员发布 |
| R7 | 必补验证；test_ai1a_config_prompts.py:278、874、1553 | 迁移代表数据仅建日计划，比较三个plan列及content／audit计数，无I4草稿、确认／来源正文；v2字段集未新增；required_contract_version=NULL负例账号nacc2不存在，可因FK而非目标CHECK失败。578／26通过不足以证明这些门槛 | 升级前通过既有服务创建I4草稿及确认，比较旧表完整行／JSON和来源；真实新增字段及v2→v3竞争；CHECK负例先满足其余FK／唯一键，断言具体约束错误 |

补修同时按原设计完成两项局部一致性处理：reject幂等返回须放在目标修订存在及契约兼容核对之后（现有实现顺序与报告“完整校验先行”不符）；畸形URL解析异常映射为既有typed输入错误，空query／fragment分隔符也拒绝，不扩大DNS／网络实现。测试guard的Alembic失败异常不得拼入完整DSN；测试先导入AI1A guard，避免通过带I5 guard的support模块先加载其他测试环境。

## 3. 设计决定与实施边界

上述处理是对v3既定契约的落实，不新增教师流程或系统级架构。本轮没有产品决定缺项，不需要ADR。

1. contract_versions为受审阅迁移发布的持久协议；指导文字字段校验读取相应版本的guidance_fields。任务白名单及当前输出结构仍来自系统registry，不能由用户编辑协议。验证不能为通过测试删除新增字段或修改TASK_REGISTRY。
2. 维持固定contract v1行锚点及account→session→head→contract锁序。获取新指针后读取关联immutable版本也使用locking read，不能用“版本不可变”推导“新版本在旧快照中可见”。
3. 保留reject不推进个人版本、reject先／accept先两种提交语义；不新增另一套版本机制。
4. R5只是纠正首版导出schema，当前1A迁移仅在报告中的一次性库执行且未部署，可修正该新增迁移种子。不得连接远程检查或改写既有迁移；若发现本片已进入持久共享环境，应回报协调者安排追加迁移。
5. 不提前完善周游戏／材料业务来源选择、worker、transport或API。已新增的动态来源helper仅作局部能力，不计为业务第二层校验已收口，分类／去重等完整规则在业务片落实。

## 4. 下一步顺序

现在交[OpenCode补修提示词](ai-slice1a-repair-opencode-prompt-2026-10-04.md)，按R1–R7编码、补测、交付并停止。协调者复审通过后，1A才记为实现与自动验证收口。

之后由协调者定稿1B API／权限：本人配置GET/PATCH/DELETE、提示词列表／读取／显式初始化／编辑／接受／拒绝／适配、管理员默认GET/PATCH、严格输入／脱敏响应、Origin／会话权限与409/422/503映射。届时发单独1B编码提示词；本轮不同时授权或自动启动1B。1C浏览器产品验收、供应商、worker、部署、commit/push及完整W6仍独立。
