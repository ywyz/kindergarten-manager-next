# 提示词与字段适配实施规格

状态：2026-10-03规格收敛；继承已确认的接受／拒绝与适配规则，以下存储、API和界面为工程方案。本轮只交付规格，不授权实现。依据：[提示词Contract](../modules/prompts.md)、[AI Service规格](ai-service-implementation.md)、[实施索引](ai-capabilities-implementation.md)。

## 1. 系统协议与个人指导

系统维护task_type、输入变量、输出schema、字段名称／类型及默认指导；个人只编辑允许的字段生成指导文字。字段集合、JSON结构、来源身份、权限、版本及确认逻辑均不能由个人文字改写。系统组装顺序为字段协议、个人指导、业务输入数据；原始教案与参考材料只是输入，不执行其中的指令。

每个任务拥有`contract_version`（字段协议）、`default_revision`（默认指导）、`personal_revision`（个人指导）三个独立版本。仅指导文字变动不升级字段结构，也不强制阻塞。必需字段变化升级contract，保留个人文字，适配完成前只暂停该task_type的AI；手工保存／导出继续可用。

个人未修改的字段采用其当前个人版本中已接受的默认指导快照，不能每次运行动态偷换成系统最新文本。首次使用明确显示默认指导并建立个人初版；不强迫教师先写完全部首版任务指导。

## 2. 首版任务registry

任务粒度为工程方案，不减少首版能力。字段详细类型复用当前业务模型，不能让模型返回客户端可写的来源版本或系统ID。

| task_type | 输入与系统输出边界 | 候选采用位置 |
| --- | --- | --- |
| `daily_lesson_split` | 原始教案、年级；输出group_activity的theme／objectives／preparation／key_points／difficult_points／process | 日计划候选；采用拆分时保留原文、未经适龄调整的拆分基准 |
| `daily_process_adapt` | 明确拆分基准或已保存过程、班级年级；仅返回process候选 | 教师比较后采用最终过程；不改原基准 |
| `daily_other_activities` | 日期／周次／有效日历、班级游戏配置及日计划快照；返回morning_games／morning_talk／post_group_games／afternoon_outdoor对应字段 | 预览和选择采用；不替教师编写真实活动反思 |
| `weekly_games` | 全班本周日计划候选集合、当前草稿和班级配置；返回两集体一自选、重点区域的具体来源选取与不足补充 | 周游戏候选；来源校验后采用，补充标AI，不伪造日来源 |
| `weekly_columns` | 本周日计划、有效日期上下文；返回key_week_focus／environment_setup／habit_culture／home_cooperation | 负责人按字段选择替换，未选字段保留人工内容 |
| `weekly_theme_suggestion` | 本周日计划及已有主题上下文；返回主题建议 | 只显示建议，负责人明确采用，不自动覆盖theme |
| `weekly_materials` | 确切游戏／区域选择、整组文本、年级及依据标识；返回提取／补充材料项 | [材料规格](weekly-materials-implementation.md)候选、编辑、确认 |

所有首版任务均有个人字段指导编辑面，不只提供材料或周计划提示词。日计划其他活动涉及“周边节假日”的语义尚未确认，见索引P4；对应功能实施前收口，不能从日期邻近任意猜测节日或新增外部服务。

## 3. 存储和不可变引用

工程方案：`prompt_contract_versions`保存registry schema和输入变量声明，`prompt_default_versions`保存各字段默认指导，`personal_prompt_versions`保存account／task_type／revision／guidance_map／基于的contract与default版本，均append-only；`personal_prompt_heads`唯一(account,task_type)指针、adaptation_state、seen_default_revision／rejected_default_revision。

用户不能PATCH系统schema；管理员默认指导修改产生新revision，不原地覆盖。系统字段变化由经过审阅的schema registry／迁移发布，管理员日常编辑器只修改默认指导；避免把任意schema设计器加到首版。

schema版本及实际个人版本被执行／候选引用后不删除；未引用版本本阶段也不自动清理，未来保留策略单独确定。存储为模块配置数据，不在AI日志重复全文，不缓存到外部写作工具。

## 4. 更新、拒绝与适配流程

普通默认文字更新：个人任务卡显示“系统指导已更新”，展示自己的当前指导与新默认，允许“保留当前”或“接受新默认”。保留记录拒绝的revision，避免同一更新反复强制弹窗；以后可主动再接受。接受页面列明会覆盖哪些个人字段，按字段选择；提交expected_personal_revision，变动则409保留输入，不静默合并。

必需字段变化：显示字段增删／类型变化及原个人文字；缺的新字段预填对应默认，原字段文字保留。教师逐字段查看并显式“完成适配”，服务端验证完整guidance_map和当前contract；成功建立新个人revision和适配状态。未保存、关闭窗口或只点普通“保留当前”均不能标为适配完成。其他任务不受阻。

更新期间worker读取已适配且仍与当前required contract兼容的版本。排队任务启动用最新有效个人版本；已启动请求用启动时版本。旧结构结果只能留作旧候选，不能在不兼容字段协议下作为当前候选采用；指导文字变动本身不使已有内容自动陈旧或重生成。

## 5. API与权限

拟定：`GET /api/settings/prompts`返回task_type列表与状态；`GET/PATCH /api/settings/prompts/{task_type}`读取／保存本人文字，PATCH携带expected_personal_revision；`POST .../{task_type}/accept-default`携带expected版本和选定字段；`POST .../{task_type}/adapt`携带目标contract、expected版本及完整字段指导。

管理员默认入口`GET/PATCH /api/admin/prompt-defaults/{task_type}`以expected_default_revision防冲突。教师访问admin端403；不存在task_type为404，未知字段／缺适配字段／禁止改结构为422，版本或schema推进为409，未适配AI提交为409 `PROMPT_ADAPTATION_REQUIRED`。API、worker调用同一适配判定函数。

输入指导单字段最多8000字符；输出字段名由服务器提供，UI无删字段／改字段名控件。用户输入不通过HTML执行。本人日计划AI和周负责人AI所用提示词身份与配置计费身份一致，不使用任务发起者随意指定的另一个account_id。

## 6. UI与审计

本人设置中按任务展示指导、当前版本、系统更新通知和适配原因；管理员也有本人页面，默认管理页独立。页面显示普通文字更新可拒绝、必需字段适配须完成，AI操作入口说明阻塞原因和设置入口，手工按钮仍可用。

新候选展示实际配置／提示词版本可追溯信息；不因提示词更新刷新掉未保存的个人编辑。管理员对默认指导操作记录实际提交revision；个人编辑／接受／拒绝／适配记录操作者、task_type及前后版本，不把全文写operation_records。

当前`operation_records`无payload／版本列，target_type有固定CHECK；个人事件以account、默认指导事件以school为目标。同事务追加`prompt_change_records`关联operation_record_id、task_type、事件种类和前后版本（拒绝时版本可相同、记录拒绝default_revision），不伪造现有表能存这些字段，不扩大其target_type。正文仍只存提示词版本表。

## 7. 验证矩阵与完成条件

| 案例 | 必须结果 |
| --- | --- |
| 教师改字段名／增加结构／读写他人指导 | 拒绝，系统结构及他人版本不变 |
| 普通默认更新，拒绝／按字段接受 | 当前个人文字不被静默改写；接受只改选定字段，拒绝不会阻止AI |
| 必需字段更新 | 个人文字保留、只阻塞对应任务；API与worker一致，手工保存和导出可用 |
| 两设备同时编辑或适配时contract再次推进 | 旧提交409，输入保留，不虚标适配完成 |
| 排队／运行期间修改个人指导 | 排队用启动时最新有效版本；运行记录保持旧版本，候选不自动采用 |
| 接管负责人、管理员个人操作 | 用实际负责人与管理员本人的个人版本，不继承他人可编辑指导 |
| 日／周全部registry任务 | 每种任务有字段编辑面和输出校验，非空主题不遗漏 |

完成记录分别说明schema／API／UI、自动验证、真实任务调用。个人提示词编辑通过不等于全部AI业务候选或材料产品验收完成。
