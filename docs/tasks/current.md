# 当前任务

## 桌面备份恢复发布前修复

2026-11-10 从 `codex/teaching-documents-design` 的 `bddb21daa3d220dad6b4e0d372b9d81482902405` 接续。教师确认保留桌面 C/S 与可选在线协作，先修复并验收本机备份恢复。Certum 证书已签发，教师另行申请 Microsoft Store 发布者账号。

- OpenCode 原 build 会话负责恢复验证器及直接相关的实现。Command Go 原会话负责备份恢复回归用例和合成夹具。两边使用 DeepSeek V4.1 Flash max，写入责任互斥。Codex 复现、独立复核、执行验收并记录结果。签名、发行和线上部署属于后续步骤。
- 对照开工基线时，备份三文件为 17 项通过、42 项失败。主要失败是既有 SQLite 迁移生成的 `local_listening_assets` 表约束顺序不同，导致与可信建表 SQL 的逐字比较误拒。同批中的陈旧合成夹具及其他失败分别诊断。修复须保留对列、约束内容和字面量、索引、触发器、归档完整性及图片的检查。历史迁移版本及现有备份格式延用。
- 使用全新隔离的合成档案及假凭据。核查旧备份能在副本中升级恢复、当前备份可创建校验恢复、真实图片和已确认版本保留、源包及旧档案指纹保持、篡改或错误密码失败。保持首次失败证据，核对运行后新、旧档案及凭据的各自边界。

本机备份恢复已通过 Windows 11 源码验收，覆盖设置页、首次设置、旧包及恢复前保护副本。原始 0007 的既有 AI 提示词冲突与长路径限制仍需单独跟踪。修复范围和独立验收见[桌面备份恢复发布前核查](../bootstrap/desktop-backup-restore-release-review.md)。

## 一对一倾听与本机周计划的 AI 定向修改

2026-11-10 从 `codex/teaching-documents-design` 的 `f6368c0` 接续。教师授权按[已标定的位置](../specs/desktop-curriculum-deliberation.md#一对一倾听与周计划的定向修改位置)实现选段、输入意见、预览差异和明确采用。课程审议与原有周计划整份重新生成流程沿用。Certum 证书待到位后再接续签名与安装包测试。

本轮功能已通过 Codex 独立核查，含本机接口、前端回归、SQLite 迁移、Windows 11 WebView2 保存重开和原请求恢复。证据与对照确认的既有备份、D2 测试问题见[定向修改核查](../bootstrap/desktop-directional-revision-review.md)。

- OpenCode 续接 `ses_e3f562e7cffe11GIhP5weE4IQu`，使用 build／`opencode-go/deepseek-v4.1-flash#max`，负责本机任务、选区校验、输入投影、候选来源、必要迁移及后端测试。Command Go 续接 `588fd8a9-65b6-4866-9409-a8dfdb1c4459`，使用 `deepseek/deepseek-v4.1-flash`／max，负责两个模块的入口、选区、共用对话框、预览和既有采用或保存接入。两边各自停写后由 Codex 独立复核。通过后普通提交并推送当前分支。
- 本机创建入口为 `POST /api/local/directional-revisions`。请求含 `request_id, scope, field_text, selection, instruction`。`scope` 绑定来源类别、记录、已保存版本和指定栏位，候选、领域或图位按需传入。`selection` 含 UTF-16 的 `start, end` 及逐字一致的 `text`。`GET /api/local/directional-revisions/{task_id}` 查询原任务。生成结果只返回拟替换文字、澄清问题或无需修改的状态。未知受理通过原请求 ID 核对。采用前再次核对身份、版本和当前文本。
- 倾听的选区绑定当前领域、组和正文。核对所见与幼儿原话，照片与身份留在本机。周计划的选区绑定一栏、一个游戏槽字段或一条材料。预览显示对应来源，改写后的文字按建议处理，原证据留作核对。两个模块均先进入已有待保存或待采用状态。用隔离合成档案和假供应商核查迁移、目标绑定、待核对及迟到回包、保存重开和来源一致性。

## 课程审议 AI

2026-11-10 在 `codex/teaching-documents-design` 接续，基线为 `1cc91c1`。教师确认首次生成与局部修改流程，授权两个原生开发会话使用 DeepSeek V4.1 Flash max 实现，通过独立复核后提交并推送本分支。流程与模型指导见[课程审议 AI 提示词](../specs/desktop-curriculum-deliberation.md#课程审议-ai-提示词草案)。

原填写、保存与 Word 版式沿用[产品规格](../specs/desktop-curriculum-deliberation.md)。基线已通过 Windows 11 WebView2 保存重开、剪贴板粘贴、原生另存为及 Word 逐页核查，证据见[上一轮独立核查](../bootstrap/desktop-curriculum-deliberation-review.md)。自制教玩具另按教师资料排期，人脸识别选题已取消。

课程审议 AI 已通过隔离源码、旧库升级、WebView2 和实际 Word 验收。核查及回修见[课程审议 AI 独立核查](../bootstrap/desktop-curriculum-deliberation-review.md#2026-11-10-课程审议-ai-独立核查)。后续在 Certum 证书到位后接续签名、制作 EXE 安装包和安装包测试。

### 当轮分工与验收

- OpenCode 续接原生会话 `ses_e3f562e7cffe11GIhP5weE4IQu`，使用 build／`opencode-go/deepseek-v4.1-flash#max`，负责课程审议本机任务、模型输入输出、候选组装、兼容存储、必要的共用 AI 接入和后端测试。
- Command Go 续接原生会话 `588fd8a9-65b6-4866-9409-a8dfdb1c4459`，使用 `deepseek/deepseek-v4.1-flash`／max，负责课程审议编辑器、候选预览与采用、选段、保存重开和对应前端测试，沿用现有原生 Word 另存为。
- Codex 维护接口及正式文档。用隔离合成数据和假供应商，独立验证原稿覆盖与归属核对、审议建议与二次稿、选段与联动、陈旧候选、保存重开、Word 正文和四种附页组合。问题交原责任会话回修，停写后复验。通过后普通提交并推送当前分支。Certum 证书到位后再签名、制作 EXE 安装包和测试。

### 接口边界

- 课程审议本机前缀为 `/api/local/curriculum-deliberations`。原记录、版本保存、导出预览和 Word 接口继续使用。记录读取和保存增加可选 `document`，用于保存后重开时定位正文对应段。20 个表单字段继续作为 Word 正文来源。
- POST `/{id}/ai/tasks` 接 `request_id, kind, version, content`，按步骤可加 `age_group, instruction, document, split_task_id, resolutions, selection`。`kind` 为 `split, review, edit`。选区含 `field, start, end, text`，按浏览器 UTF-16 偏移绑定原文。原任务 ID 可按 GET `/{id}/ai/tasks/{task_id}` 查询。相同请求 ID 和内容只受理一次。
- 成功候选含 `kind, patch, document, questions, status, reason_suggestion`。拆分待核对项经老师明确归属后才进入审议。采用候选核对记录、档案代次、已保存版本和本次草稿。理由单独采用。导出按明确保存的版本读取，过期预览重新核对。

## 在线协作合成联调

2026-11-08，教师授权在上一轮教师反馈的源码与合成核查通过、实现会话停写后接续。上一轮交接和未验项见 [教师反馈核查](../bootstrap/desktop-teacher-feedback-repair-review.md)。本轮按 [在线协作 ADR](../adr/0005-optional-online-class-collaboration.md)、[教师确认的流程](../specs/desktop-teacher-feedback-repair.md#管理端登录教师发码和桌面升班)执行，证据记入 [联调核查](../bootstrap/online-collaboration-integration-review.md)。

### 当前门槛

**第一至第四阶段均已通过合成联调独立复核。** 开发基线为 `codex/desktop-one-to-one-listening` 的 `c60c5457faf046ea66feb1c8816a8fd1be0db20c`，开工时工作树干净。原实现会话已停写，分工、反例、实测和待补项见 [联调核查](../bootstrap/online-collaboration-integration-review.md)。OpenCode 使用 build／`opencode-go/deepseek-v4.1-flash#max`，Command Go 使用 `deepseek/deepseek-v4.1-flash`／max。线上联调保留隔离测试站点和合成数据，供教师按正常路径复测。

1. **MySQL 8.4、管理员登录与发码。** 上海 ECS 经 VPC 连接现有 RDS，独立测试库和专用账号，迁移与应用权限分别核对。迁移、稳定身份、版本并发、事务及约束在 MySQL 8.4 上实际运行。Command Go 交管理网页登录、发两类一次性码及真实服务端兑换。Codex 从页面给合成教师发码，复核教师和匿名者无发码权限、过期、重复及并发只能成功一次。桌面本地继续使用 SQLite。
2. **选班、换机与升班。** 核实 `manager-next.ywyz.tech` 的 ESA 到独立 Caddy 站点 HTTPS 回源及 API 绕过缓存。两个隔离桌面档案同园同班自动配对，加入码只绑定教师与园所。用新档案兑换恢复码，直接进入原来仍有效的班级。桌面选择目标年级、生效学期并确认升班，两端沿用班级 ID，历史班名、学期及确认版本按原快照显示与导出。
3. **周计划同步。** 按已确认的共享范围、备课活动引用和确认权限实施。双桌面按同周读取、交叉保存、并发冲突保留未提交输入、断线恢复及确认版导出验收。照片和 Word 文件留在本地。
4. **提示词发布。** 用合成发布源和测试签名验证管理端草稿、预览、正式发布和回滚。桌面按渠道拉取并核验签名，下次 AI 执行使用有效新版，离线沿用最近可用版。版本包走独立可缓存静态路径，最新版本清单绕过缓存。

每阶段经 Codex 独立复核通过才开始下一阶段。线上操作限独立测试库、专用账号和测试站点，凭据走受保护配置。每阶段记录实现者、实测、审核及待补项，最后给教师正常使用路径复测清单。

### 第二阶段接口边界

- 复用阶段一 `POST /api/collaboration/redeem` 及既有选班、班友和配置带入入口。桌面本地代理通过同一受限 HTTPS 来源发兑换请求，在同一连接代次校验服务端教师身份后接入现有在线会话。加入不自动选班，恢复直接读取仍有效的原班。两类码及教师 token 只在受控请求和进程会话内使用。
- 升班在 `/api/collaboration/me/class/promotion` 读取当前班级与学期、提交明确确认。读返回 `class_id`、`class_name`、`grade`、`version`、`terms`。学期项含 `term_id`、`name`、`start_date`、`end_date`。提交含 `request_id`、`class_id`、`expected_version`、`target_grade`、`effective_term_id`。回执含 `request_id`、`class_id`、`class_name`、`grade`、`version`、`effective_term_id`、`replayed`，可用 `GET /api/collaboration/me/class/promotion/operations/{request_id}` 查询。失效基准返回明确 409，未知提交只按原请求 ID 查回执。桌面沿用未决和关闭保护。
- 生效学期采用在线园所的稳定学期 ID。班名在上海日期到达该学期时生效，提交回执显示新班名和生效学期。已有班级、老师身份、成员关系和确认快照均按稳定 ID 保留。原本地历史周计划通过现有显示和 Word 路径复核，在线周计划的共享合同和同步留到第三阶段。

### 教师设置简化

教师要求本轮同时简化整个设置页。默认先显示姓名与园所、当前班级和当前学期，其余设置按学期维护、日历、游戏、AI、备份恢复等用途收起。工作台提供明确的在线协作入口，打开后优先呈现当前所需的兑换、选班、班级状态或升班。手工凭据和低频配置按用途收起，保留既有功能。

页面分组保持既有保存、影响预览和未决请求处理。收起的分组保留编辑状态。从关闭／离开提醒回到某个草稿时，先打开所在分组再定位。打开设置或协作入口沿用既有本地状态读取，老师明确操作后才连接在线服务。

### 第三阶段已确认的产品范围

- 同一在线班级的同周共享内容限晨谈、集体活动和游戏。其余栏目由该班一位教师在自己的本地档案填写。照片和 Word 文件保留在本地。
- 老师从本人备课选择活动时，只共享活动名称和日期。备课正文和来源记录留在本地。
- 任一仍有本班权限的老师可明确确认最新已保存的共享版本。

服务端按在线园所、班级、学期及周一日期识别同一周。桌面在现有周计划入口显式进入本班共享周计划。共享稿只传按日期的晨谈、集体活动和现有游戏槽位所需的名称。由本人已保存备课带入时，只投影活动名称及日期。服务端拒绝额外字段，按当前成员关系授权，保存用显式基准版本和原请求 ID。

教师遇到版本冲突或断线时保留本次输入，读取服务端版本后可核对并明确保存。未知写入按原请求查询。确认以具体已保存版本为基准，冻结当时的班名、学期、共享字段和确认版本。桌面在本地导出确认版，班级老师填写的本地栏目可随该本地文件输出。服务器只保存共享快照，桌面本地 SQLite 的原有周计划、历史版本和 Word 路径继续可用。

#### 第三阶段接口

- 共享周路径为 `/api/collaboration/classes/{class_id}/weekly/{term_id}/{week_start}`。桌面受限代理沿用 `/api/local/collaboration` 前缀和相同后缀。班级及学期取在线 ID，`week_start` 是 ISO 周一。共享内容为 `{days, games}`。日项含 `date`、`morning_talk_topic`、`group_activity_theme`。游戏固定槽位 `collective_1`、`collective_2`、`free_choice_1`、`focus_area`，各槽为空或 `{name,date}`，手工项日期可空。服务器以校内学期范围及周校验日期。
- GET 返回 `class_id, term_id, week_start, class_name, term_name, version, content, confirmation`，未创建的周稿版本为 0，`confirmation` 可空。POST `/save` 提交 `request_id, expected_version, content`，回同一读取形状加 `request_id, replayed`。POST `/confirm` 提交 `request_id, expected_version`，回冻结的确认形状加 `request_id, replayed`。确认形状含 `confirmation_id, confirmation_version, version, class_id, term_id, week_start, class_name, grade, term_name, content, confirmed_by, confirmed_at`。确认页可按 `GET /confirmations/{confirmation_id}` 重读，原操作可按 `GET /operations/{request_id}` 读取 `{request_id,kind,result}`。
- 本地 Word 由 `GET /api/local/collaboration/classes/{class_id}/weekly/{term_id}/{week_start}/confirmations/{confirmation_id}/word` 生成，接受可选本地 `weekly_plan_id, local_draft_version` 查询参数作为一对。服务端确认版决定共享字段、班名和确认版本。本地选定的已保存周稿只补主题、栏目和材料。源端不接收本地周稿内容或文件。桌面用既有原生 Word 保存对话框。

### 第四阶段接口

- 管理端沿用管理员登录和 CSRF。基路径 `/api/collaboration/admin/prompt-releases`。GET 返回 `{editable,drafts,releases,latest}`，`editable` 为 `{task_type,fields}` 列表，`fields` 是字段名到当前正式指导文本的映射。草稿项 `{draft_id,notes,base_stable_sequence,changes}`。发布项 `{release_sequence,channel,draft_id,notes,rollback_of}`，可空字段用 `null`。`latest` 为 `{preview,stable}`，值为正整数或 `null`。POST `/drafts` 接 `{changes,notes}`，`changes` 为任务、字段到指导文本的映射。草稿冻结完整有效内容并记录其正式基准。POST `/preview` 接 `{draft_id}`，POST `/stable` 接 `{preview_sequence}`，POST `/rollback` 接 `{target_sequence,expected_stable_sequence}`，均回对应发布项。正式发布复用该预览的确切指导内容，拒绝已落后的草稿基准。回滚使用已发布正式版的指导内容，签出更高发布序号及对应默认修订。发布动作在事务中串行，不重复推进同一草稿或预览。
- 完整包沿用已有 Ed25519 信封和可编辑字段白名单，结构、权限、模型和工具信息由本机程序决定。静态签名包位于 `/prompt-packages/{channel}/v{release_sequence}-{sha256}.json`，`sha256` 为包原始 UTF-8 字节摘要。清单位于同目录的 `latest.json`，严格字段为 `{format_version,channel,release_sequence,package_sha256,key_id,signature}`，格式版本为 `1`。清单签名为 Ed25519，输入 `b"kgm-prompt-manifest-v1\n"` 加不含 `signature` 的规范 JSON UTF-8，签名以标准 base64 表示。包 URL 由受信 HTTPS 源目录及签名字段构造。包字节摘要、信封签名、清单渠道、序号和 key id 全部核对，禁止重定向。`preview` 与 `stable` 是唯一渠道，测试客户端按固定构建信任读取一个渠道。
- 版本包是不可变文件，发布前写入，已有同名文件仅允许同字节，清单在事务提交后才可见。版本文件 `Cache-Control: public, max-age=31536000, immutable`，清单、管理端和错误响应 `Cache-Control: no-store`。既有直链签名包保留兼容，测试信任由隔离运行配置注入。没有远程源的普通源码构建继续使用已有默认提示词。测试私钥仅在受保护测试服务配置，桌面只接收公钥。课堂设置页无需填写地址、密钥或切换渠道。
