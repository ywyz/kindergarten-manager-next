# 基础配置与提示词：第一片实施准备（2026-10-03）

状态：用户已要求进入实施准备。本轮完成只读核对与文档交接，尚未授权业务编码、依赖安装、数据库操作、真实AI调用、部署或commit／push。业务代码继续由OpenCode唯一写入。以下子片安排为实施建议，不新增产品决定，也不改变Architecture v1。

## 1. 依据与当前基线

- [协同规格索引](../specs/ai-capabilities-implementation.md)：P1–P4已确认。
- [AI Service规格](../specs/ai-service-implementation.md)、[提示词规格](../specs/prompts-implementation.md)、[持久任务规格](../specs/persistent-ai-tasks-implementation.md)、[材料规格](../specs/weekly-materials-implementation.md)。
- `ARCHITECTURE.md`、ADR 0002及AI Service／提示词／日志Contract继续有效。
- [I5正式收口](i5-final-closeout-2026-10-03.md)：已实现手工链路通过；完整W6非空材料仍交材料片必需补验。

本轮观察：HEAD为`1647fc9`；开始时已有7份文档未提交修改（AGENTS、协同交接、readiness、日计划Contract及AI索引／提示词／材料规格）。实施者须重新记录开工时git状态并保留既有修改，不能把HEAD视为完整规格基线。

代码依据：`backend/app/models.py`和`schemas.py`为现有集中模型入口；服务在`backend/app/services/`，迁移当前文件链终点为`20260924_i4_weekly_plans`。这是文件观察，未连接数据库核对current。前端现有本人设置与管理员视图可供下一子片接入，不据此声称已有AI设置。

## 2. 本片目标与分步交付

完成后，教师、待分配教师和管理员可维护本人AI配置及全部7类任务的个人指导，管理员可维护默认指导；普通文字更新可接受／拒绝，必需字段变化须显式适配。保存设置不产生付费测试或计划生成任务。

| 子片 | 交付范围 | 完成门槛 |
| --- | --- | --- |
| 1A 数据、迁移与纯服务核心（建议首个编码授权范围） | 配置版本／加密、7类registry、默认与个人版本／head、更新接受拒绝／适配、配置及提示词变更审计；供后续执行器调用的版本解析接口 | 定向单元验证＋隔离真实MySQL迁移、事务、并发验证；协调者只读审阅 |
| 1B API与权限 | 本人配置和提示词接口、管理员默认指导接口、严格schema、身份／Origin防护、409／422／503映射 | 路由与权限、序列化脱敏、冲突及错误回归 |
| 1C 前端与设置产品验收 | 教师／管理员本人入口、默认管理、全部任务字段编辑、更新比较、拒绝／按字段接受、适配及冲突保留输入 | typecheck／build及授权验收环境中的真实浏览器验证 |

1A完成不表示整片完成。1B／1C分别交付；无新授权不自动进入下一子片。真实任务执行、transport、候选采用与材料不在本片实现范围。

## 3. 1A存储和服务契约

按既有规格建表：`ai_config_versions`／`ai_config_heads`；`prompt_contract_versions`／`prompt_default_versions`／`personal_prompt_versions`／`personal_prompt_heads`；`prompt_change_records`。OpenCode开工报告须列具体列、索引、FK、CHECK、迁移名及文件，不只列概念表名。

必须落实：

1. 配置head不能指向他人版本；配置与提示词版本追加保存，expected版本冲突不丢失更新。个人head唯一(account,task_type)，初次并发建立也不能生成两个当前版本。
2. 配置secret仅写；未传保留、非空新值轮换、null／空串拒绝、明确清除产生新版本。加密随机nonce、绑定account及配置版本作AAD；改密文／nonce／所属身份／版本时认证失败。加密材料缺失或错误只影响AI相关能力，既有手工路径及迁移导入不依赖它。
3. 7类registry全部覆盖：`daily_lesson_split`、`daily_process_adapt`、`daily_other_activities`、`weekly_games`、`weekly_columns`、`weekly_theme_suggestion`、`weekly_materials`。协议和个人指导分开；未知任务／字段、非法结构、单字段超过8000字符拒绝。输出候选schema与业务保存schema明确区分，系统身份字段不能作为模型自由输出。
4. 默认指导发布追加revision；个人已接受默认为快照。普通更新不静默覆盖，拒绝记录对应default revision，按字段接受只替换选定字段。必需字段推进保留原文字、仅阻塞对应任务，完成适配须对当前contract和expected个人版本再次检查。
5. 提供供API／未来worker共同使用的配置及提示词就绪判定和指定版本读取接口。测试仅验证“读取最新有效版本”和“指定旧版本保持不变”，不冒充真实worker领取／运行验收。
6. 变更版本、head和审计同事务提交，失败全部回滚。版本变化不登记AI任务、不写日／周计划、不同步修改历史确认或导出内容。

默认指导正文及精确字段表已由协调者在[1A设计定稿v3](ai-slice1a-implementation-checklist-2026-10-03.md)收敛，OpenCode按定稿编码并报告对应实现，不重新设计教师规则；协调者负责审阅。默认文案不表述为用户逐条确认的教学规则。材料registry可建立契约，但不提前扩入材料正文、采用或确认实现。

## 4. 本轮发现的工程衔接项

| 项目 | 观察与处理建议 |
| --- | --- |
| 加密依赖 | `backend/uv.lock`已有间接依赖`cryptography==50.0.1`，`pyproject.toml`未直接声明。实施时直接声明所用库并核对锁文件，不能依赖偶然传递依赖；本轮已修正AI规格相关事实。1A无需HTTP客户端；transport子片再报告客户端及DNS／实际连接验证方案 |
| 首次个人指导 | 需有明确初始化服务；首次页面显示默认与建立个人初版在1B／1C落实。1A不得因worker读取而静默初始化全部任务；初版并发、所接受默认版本须可追溯 |
| 拒绝默认更新 | 规格已要求持久拒绝但API清单漏列入口。1A实现拒绝服务；建议1B补`POST /api/settings/prompts/{task_type}/reject-default`，携带expected个人版本及目标default revision，并允许之后主动接受。API定稿在1B前列清，不假装已有端点 |
| 配置清除及空head | 建议未建立head的expected版本为0；已有head严格比较。DELETE亦携带expected版本，避免旧页面清除新密钥；具体输入schema在1B交付。清除后secret缺失、ready=false，已有非密钥元信息可保留 |
| 账号审计CHECK | `operation_records`对account目标要求旧列与通用列一致。记录真实账号版本，不能用配置或个人提示词revision冒充账号版本，不能仅为设置审计推进账号版本。实际设置版本分别由配置行关联operation_record_id、`prompt_change_records`承载；默认指导以school为目标 |
| AI调用日志依赖 | `ai_call_records`依赖execution／attempt，随持久执行核心落地FK、唯一键及结果同事务关联。本片实现设置变更审计及准备调用元信息接口契约，不建无真实execution的成功日志，不为日志提前引入任务表 |
| 历史secret清理 | 指定旧版本读取及清除／轮换不替换已启动版本的规则先具备；依赖execution引用的实际清理随持久任务接入，须在真实调用启动前完成。1A不猜测引用状态、不删除可能仍被使用的旧secret，不运行清理作业 |
| URL校验范围 | 1A完成HTTPS、URL规范化、query／fragment／userinfo及明显非公网目标拒绝等离线验证。DNS解析到实际连接钉住、TLS／重定向／代理和无隐式重试属于transport交付；纯字符串测试不能记为完整SSRF防护通过，未完成前不开放真实调用 |

这些是工程拆分和补齐建议；如影响已确认教师行为或模块边界，应回报而非自行改变。

## 5. 1A验证与迁移要求

| 验证 | 必须证据 |
| --- | --- |
| 加密与脱敏 | 随机nonce、AAD、篡改失败、轮换／保留／清除、无主密钥降级；错误／日志／返回对象无明文密钥或认证头 |
| 个人隔离与结构 | 不能读写他人配置／指导；所有7类协议覆盖、结构不可改、版本FK归属一致 |
| 默认与适配 | 拒绝不改个人文字且可再接受；按字段接受；必需字段推进保留文字、完成适配冲突、只阻塞对应任务 |
| 真MySQL事务与并发 | 初建并发、同版本双更新仅一成功、适配时contract推进拒绝旧提交；实际注入失败后版本／head／审计全部回滚，重连数据持久 |
| 迁移兼容 | 空库和有I1–I4代表行的库都upgrade新head；原计划、确认、来源及审计约束保持；唯一head及current一致；如提供降级说明其数据删除边界，不对共享库执行 |
| 直接回归 | 触及账号审计／配置加载／集中模型时跑相关既有单测；含手工日／周计划及导出无AI主密钥仍可用。无前端变更不重跑前端，有明确风险才扩大测试 |

真实MySQL为1A必要验证，但本轮未启动。后续授权须明确包含一次性本地隔离MySQL 8.4／InnoDB、专用新guard、独立端口／库白名单、仅loopback及`APP_DISABLE_DOTENV=1`；实施者报告资源和清理。不得复用I1–I5破坏开关，测试不得连接远程验收库／共享库／生产库。这里的自动测试数据库不是本机WSL产品验收服务器；1C产品验收仍按现有远程实例口径，部署须单独授权。

实施交付逐项记录通过／失败／skip、实际命令、迁移head、依赖锁及未执行事项。排队／claimed运行、网络目标防护、真实供应商、任务恢复、业务采用及W6均留给对应后续切片，不以本片测试替代。

## 6. OpenCode只读预检交接

下列提示词可直接用于实施准备；它不启动业务写入。用户授权1A后，另将授权行改为明确范围及资源授权，不沿用模糊“按索引全部实施”。

> 你是kindergarten-manager-next业务代码唯一写入者OpenCode。本次只读预检“基础配置与提示词1A”，不得修改业务代码、安装依赖、连接数据库、启动服务、调用供应商、部署、commit／push或进入下一片。
>
> 先读AGENTS.md、ARCHITECTURE.md、ADR 0002、AI Service／提示词／日志Contract及本准备文件，再读四份协同规格。保留当前未提交文档；不读取.env或现有私密密钥，不复制旧项目，不新增Skill／MCP或业务实现者。
>
> 输出可审阅的1A实施清单：实际修改文件；各表列／FK／CHECK／唯一键与迁移；7类任务输入变量／输出schema／指导字段及默认正文；服务输入输出和冲突规则；加密材料加载与手工链路降级；账号审计真实版本与设置版本关联；最小直接依赖及锁文件影响；单元与独立guard隔离MySQL验证计划。
>
> 明确reject-default、首次初始化、DELETE expected版本、执行引用和调用日志后续落地边界。1A不实现API／UI、worker、transport、候选、材料业务；不把未来能力记为已验。缺产品决定回报；涉及架构改变先停并提ADR草案。交清单后停止，等待具体编码授权。

## 7. 准备结论

P1–P4不再阻塞1A。当前可将上述只读预检交给OpenCode；建议下一次编码授权仅涵盖1A、加密直接依赖及其隔离验证。供应商model／凭证／用量、远程部署和桌面W6资源当前均不需要提供。

本轮仅准备文档及纠正依赖事实，未启动OpenCode、安装、迁移、测试、API／UI、供应商调用或部署。后续以实际预检清单和用户授权推进。

## 8. 后续状态：设计已收敛

2026-10-03用户要求协调者直接修正规划／设计并撰写编码交接；已形成[1A定稿v3](ai-slice1a-implementation-checklist-2026-10-03.md)和[下一步编码提示词](ai-slice1a-opencode-coding-prompt-2026-10-03.md)。§6只读预检为历史阶段提示词，不再作为下一步指令。

下一步仅交OpenCode实施1A、最小直接依赖和专用一次性MySQL验证。协调者本轮未写业务代码、未安装或创建测试资源；不自动启动OpenCode、部署或commit/push。
