# AI 1A 补修复审与下一步（2026-10-04）

结论：**主要修复方向正确，1A仍暂不收口；下一步是小范围补修／补验，不进入1B。** 协调者只读业务代码、执行无数据库测试和合成复现，并更新文档。HEAD为1647fc934d41b29a844a807d454031e66a2b45af；保留全部既有未提交修改。

依据：[v3清单](ai-slice1a-implementation-checklist-2026-10-03.md)、[首轮审阅](ai-slice1a-review-2026-10-04.md)、[补修交接](ai-slice1a-repair-opencode-prompt-2026-10-04.md)、[OpenCode补修报告](ai-slice1a-repair-result-2026-10-04.md)。本记录补充历史审阅，不重写历史结果。

## 1. 已确认的改进与验证边界

- R1的缺失导入已修正，错误的未使用锁helper已删除。
- R2服务按持久contract字段集验证，真实新增assist_notes_v2/v3的夹具已存在；初始化、适配、默认发布实现方向符合v3。
- R3就绪读取认证当前密文，R4内部对象改为slots＋SecretStr并拒绝通用编码；R5必需字段与枚举已进入导出schema，新迁移保留固定字面量。
- R6配置／个人版本写路径已使用current locking read，管理员默认发布也使用排他locking read。代码修复方向正确，但旧快照成功路径的测试证据仍有缺口。
- R7升级前新增周草稿和确认快照，升级前后比较16张旧表完整行／JSON，明显优于首轮的列／计数比较。
- 协调者在backend执行：APP_DISABLE_DOTENV=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests/unit -t . -q；**598项通过**。git diff --check通过。
- OpenCode自报42项真实MySQL通过和一次性资源已清理。协调者本轮未创建容器、连接数据库或独立复跑MySQL；以下是源代码覆盖审阅，不声称其42项运行失败。

## 2. 剩余事项与固定处理方案

### S1：离线URL边界尚未修复（实际缺陷）

位置：backend/app/services/ai_config_url.py:75–85。

urlsplit未包裹typed错误转换，query／fragment只判断解析结果是否非空。协调者无数据库复现：https://api.example.com/v1?及末尾#均被接受；https://[broken/v1抛出原始ValueError，不是AiInputInvalid。补修报告§3的对应“已处理”声明与当前代码不符。

决定：原始输入含?或#分隔符即拒绝（路径中的百分号编码不因此被解码或改写）；URL解析和hostname／port访问的畸形输入异常统一转换为BaseUrlInvalid，错误消息固定且不回显原始地址。补真实边界单元测试，保持纯离线，不扩DNS／transport。

### S2：Alembic异常仍拼接原始stderr（实际泄漏通道）

位置：backend/tests/integration/ai1a_guard.py:211–218。

虽然移除了显式拼接DSN，但仍把stderr末六行直接加入异常。协调者mock子进程返回含合成DSN的stderr，确认合成密码标记进入RuntimeError文本；没有启动Alembic或打开数据库。报告“仅脱敏目标与错误类别”不成立。

决定：公开失败异常只含guard已校验的driver／port／库名、退出码和固定错误类别，不拼任何原始stdout／stderr或解析异常文本；禁止异常链把带凭证的原始错误重新带出。畸形guard URL也包裹为固定拒绝。用合成凭证的无连接单元测试覆盖异常文本、repr及格式化traceback；Alembic子进程仍只获得校验后的测试DATABASE_URL，剔除继承的主密钥环境变量。

### S3：旧快照成功路径测试被前置rollback消解（必补验证）

位置：backend/tests/integration/test_ai1a_config_prompts.py:2101–2275（K1）。

四条测试均先用旧expected触发服务冲突。服务异常处理执行db.rollback()，结束原REPEATABLE READ事务。随后同一Session以正确expected执行成功操作，已不是原来的旧快照。Session对象相同不能证明事务快照仍相同；现有测试可覆盖冲突和新事务成功，不能覆盖R6核心故障。

决定：成功路径和冲突路径分开建立世界／Session。成功路径先普通SELECT建立旧快照，另一连接提交新版本，再在**没有任何commit／rollback**的旧事务里直接以正确新expected调用写入口。分别覆盖配置保留、清除、个人编辑、个人接受和管理员发布。写前用同一旧事务普通读断言仍看到旧版本／旧行集；检查仍处于同一事务，再调用服务。另用独立旧快照Session测旧expected冲突。保存后重连断言版本、head、保留secret认证结果、未选择字段及审计；不能只看返回版本号。

### S4：真实任务列表与新契约个人编辑尚缺测试（必补验证）

位置：backend/tests/unit/test_ai1a_service_inputs.py:51–63及集成E2的test_c_personal_edit_validates_against_based_contract。

任务列表所谓真实入口测试仅构造TaskStatus(task_type="x")，未调用list_tasks；仓库测试中未找到该调用。E2 personal_edit测试也未发布v2，只在v1上拒绝任意未知字段，不能证明v2-based新字段可编辑或发布后v1-based编辑保持待适配。

决定：真MySQL调用list_tasks，覆盖七任务的未初始化／初始化／默认待处理／待适配状态及GET无副作用、本人隔离。E2增加两个场景：发布v2后保留v1-based文字编辑，based不变且仍待适配；初始化或适配到v2后编辑真正新增字段成功，未知字段拒绝且无副作用。不修改运行时registry。

### S5：CHECK负例与迁移来源样本仍未完全隔离（必补验证）

位置：集成I1NullConstraintPaths.test_b_adapt_required_with_null_contract_reference、A1MigrationCompatibility.test_b。

CHECK负例先初始化TEACHER_A，再INSERT同一account/task的head，同时违反head主键唯一性。即使MySQL此次先报目标CHECK，也没有满足上轮要求的“只违反目标CHECK”。迁移样本保存周草稿仅patch主题并确认，未选择真实日计划来源；完整行比较已改进，但非空来源引用／内容仍缺样本。

决定：对已有合法head执行UPDATE，仅把adaptation_state设为adaptation_required且required_contract_version设NULL；其余FK／主键保持合法，断言MySQL CHECK错误码3819及ck_pph_adapt_ref，失败后重连确认原行。配置CHECK同样核对3819和具体约束名。升级前通过既有周服务选择至少一个真实来源，确认草稿／确认JSON确实包含该来源身份及非空文本，再比较升级前后完整行。仅造测试样本，不改日／周业务。

## 3. 下一步

按[第二轮补修提示词](ai-slice1a-repair2-opencode-prompt-2026-10-04.md)完成S1–S5，报告准确证据并停止。保留已修正的R1–R7实现，不重做设计、不新增表／依赖／产品能力。本轮无新产品决定或系统级架构变更，不需要ADR。

复审通过后才定稿并授权1B：配置GET/PATCH/DELETE、个人提示词列表／读取／显式初始化／编辑／接受／拒绝／适配、管理员默认GET/PATCH，以及严格输入、脱敏响应、会话／Origin权限和错误映射。1C界面与浏览器验收、worker／供应商、部署、commit/push和完整W6继续独立；本文件不授权这些步骤。
