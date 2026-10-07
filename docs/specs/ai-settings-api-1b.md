# 基础配置与提示词 1B：API／权限设计定稿

状态更新：2026-10-07。本文为 1B 的有效工程规格，1B 已实现并完成阶段审阅，1A／1B／1C 已部署。实际部署见 [部署结果](../bootstrap/ai-slice1abc-deployment-result-2026-10-05.md)；产品结论见 [Windows 验收报告](../bootstrap/ai-slice1c-desktop-validation-2026-10-05.md)，相关夹具子例仍受阻，尚未全通过。业务代码由 OpenCode 唯一写入，本文不自动授权重做或部署。

依据：[1A 阶段收口](../bootstrap/ai-slice1a-closeout-review-2026-10-04.md)、[1A v3](../bootstrap/ai-slice1a-implementation-checklist-2026-10-03.md)、[AI Service 规格](ai-service-implementation.md)、[提示词规格](prompts-implementation.md)、AI Service／提示词／操作日志 Contract、ADR 0002。本文细化既有设置行为，不改变 Architecture v1。此前规格的“拟定”接口在本片按本文落实。

## 1. 范围和实现位置

1B 只实现设置 API、严格输入输出、会话权限、错误映射和测试。没有前端、AI 提交／连通性测试、worker、网络 transport、供应商请求、任务／调用日志表、候选采用、材料或历史 secret 清理。保存设置不调用 AI，不登记任务，不修改日／周／确认／Word 数据。

建议新增 `backend/app/routers/ai_settings.py`（本人设置与管理员默认的两个 APIRouter），schema 在已有 `backend/app/schemas.py` 中新增独立区域，`main.py` 仅注册路由和新增接口的安全校验错误分支；正常命名可由 OpenCode 落实。复用 1A 服务，必要时仅在 `prompt_service.py` 增加只读详情／管理员默认读取。禁止路由直接写 ORM、重新实现版本事务，禁止改 models、迁移、依赖及锁、auth_service、旧业务或 frontend。

## 2. 身份与权限

| 身份 | 本人配置／个人指导（全部 7 任务） | 管理员默认 GET／PATCH |
| --- | --- | --- |
| 有效班级教师 | 允许 | 403 |
| 待分配教师 | 允许；不要求班级或 can_prepare | 403 |
| 有效管理员 | 允许；身份始终为管理员本人 | 允许 |
| 未登录、过期／撤销会话、停用账号、auth_version 不符 | 401 | 401 |

所有接口使用既有 cookie 会话和 `get_auth_snapshot`。个人 target 始终取 snapshot.account_id；不接收 account_id、teacher_id、billing_account_id 或客户端 role，也不提供他人配置／个人指导 URL。写入口继续由服务在事务内 account→session→本人 head→contract 锁序复核账号、角色及会话。管理员路由先基于有效 snapshot 拒绝非管理员，服务写入仍二次核验真实管理员；GET 新服务使用 `verify_self_read` 后核验管理员。不得只依赖客户端身份或只做路由一次权限判断。

沿用全局 JSON Content-Type 与精确 Origin 防护：POST/PATCH/DELETE 缺失／错误 Origin 为 403；非 JSON 为 422。包括 DELETE 和空初始化请求都发送 JSON。GET 不要求 Origin，但要求有效会话。响应和错误均 `Cache-Control: no-store`。身份测试使用合法请求体验证 401／403；不要求同时非法 body 与非法身份时固定某一种错误优先级。管理员有效请求先校验角色再检查 task_type，教师不能借未知任务绕过 403。

## 3. 通用输入与响应规则

请求对象均 `extra=forbid`，禁止隐式转换：整数不接受 bool、字符串数字或浮点数；文字不接受数字、数组或对象；所有版本字段必填。提示词文字允许空串和换行，不裁剪内容，单字段最多 8000 字符；map 的键、accepted_fields 项均为严格字符串。字段合法性由服务按数据库中对应 contract 检查，不把首版 registry 字段集写死在 schema。PATCH map 非空；接受列表非空且无重复。未知任务使用显式白名单判断，不用 Literal 路径参数把 404 改成 422。

成功均 200 JSON（包括初始化／清除），不返回裸 ORM、内部解密对象或审计对象。配置及默认响应固定白名单；个人响应按下述 DTO 显式组装，不能用任意 dict 掩盖缺项。新增响应模型应约束枚举和必需字段。不得将服务异常文本、输入 body、凭证或 traceback 放入 API 返回或应用日志。

## 4. 配置接口

| 方法／路径 | JSON 请求 | 调用 |
| --- | --- | --- |
| GET `/api/settings/ai-config` | 无 | `get_config(db, snapshot, snapshot.account_id)` |
| PATCH 同路径 | `expected_version` 非负整数；`protocol_id` 固定 `chat_completions_v1`；`base_url` 字符串；`model` 字符串；可省略 `secret` | `save_config` |
| DELETE 同路径 | 仅 `expected_version` 非负整数 | `clear_secret` |

PATCH 必须提交完整非密钥元信息 protocol_id/base_url/model，表示保存当前设置；本片不增加 metadata 省略后合并的行为。URL 最多 500 字符，沿用 1A HTTPS 离线规范化及供应商前缀；model 去首尾空白后非空且最多 200 字符。非法协议／URL／model 为 422。

secret 未传时必须传服务的 `SECRET_UNSET`（或不传该参数）；通过 `model_fields_set` 判定，不能用默认 null 冒充未传。显式 null、空串或非字符串为 422；非空字符串原样作为密钥，不 strip。建议输入持有 `SecretStr`，严格原始类型检查后包裹，仅在调用服务时取明文；禁止对含密钥 DTO 做日志或普通 model_dump。密钥轮换不改变全局主密钥。首次 expected=0 保存缺 secret 为 422；已有清除版本省略 secret 可继续保存无密钥元信息。

统一 `AiConfigOut`：`version` 非负整数、`protocol_id/base_url/model` 可 null、`has_secret` bool、`secret_mask` 可 null、`ready` bool、`ready_reason` 可 null。无 head 的 service.version=null 在边界转换为 0，元信息 null、has_secret=false、ready=false、reason=NOT_CONFIGURED。has_secret=true 时固定遮罩 `********`，否则 null；不返回 account_id、head_exists、key_id、ciphertext、nonce、secret、密钥尾码或内部解密对象。ready_reason 白名单为 NOT_CONFIGURED、MISSING_URL、MISSING_MODEL、MISSING_SECRET、DECRYPT_UNAVAILABLE；ready=true 时 reason=null。ready 仅表示 1A 本地配置完整且认证解密可用，不声称供应商已连通或 transport 已实现。

DELETE 仅清当前密钥，保留元信息和历史版本；带当前 expected 产生新版本。无 head 且 expected=0 幂等 200／version=0；旧 expected 为 409。已有 head 即使当前已清除仍沿用 1A 新版本规则，不另加幂等。缺失／错误主密钥时 GET 返回 200、ready=false，已有密文显示 DECRYPT_UNAVAILABLE；DELETE 无需解密可成功。PATCH 需要加密／保留旧 secret 且加密材料不可用为 503；无密文的元信息保存不依赖主密钥。不能把缺密钥 GET 或手工路径统一变为 503。

## 5. 个人提示词接口

路径前缀 `/api/settings/prompts`；task_type 为 1A 的全部 7 项。

| 方法／后缀 | 严格 JSON 请求 | 服务／成功响应 |
| --- | --- | --- |
| GET 空后缀 | 无 | `list_tasks`；`{items: TaskStatusOut[]}`，固定 registry 顺序、全部 7 项 |
| GET `/{task_type}` | 无 | `read_task`；`PromptDetailOut` |
| POST `/{task_type}/initialize` | 空对象 `{}` | `initialize_task`；`PersonalInitOut` |
| PATCH `/{task_type}` | `expected_personal_revision` 正整数、`guidance_map` 非空局部 map | `save_guidance(..., patch=guidance_map)`；`PersonalWriteOut` |
| POST `/{task_type}/accept-default` | `expected_personal_revision` 正整数、`target_default_revision` 正整数、`accepted_fields` 非空无重复列表 | `accept_default`；`PersonalWriteOut` |
| POST `/{task_type}/reject-default` | `expected_personal_revision` 正整数、`target_default_revision` 正整数 | `reject_default`；`PersonalRejectOut` |
| POST `/{task_type}/adapt` | `expected_personal_revision` 正整数、`target_contract_version` 正整数、`guidance_map` 完整 map | `adapt(..., full_guidance_map=guidance_map)`；`PersonalWriteOut` |

`TaskStatusOut` 固定字段：task_type、initialized、adaptation_state（current/adaptation_required）、required_contract_version（正整数或 null）、pending_default_update、latest_default_revision、latest_contract_version。未初始化不表示已就绪。列表不初始化、清拒绝标记、推进已处理默认或写审计。缺已知任务契约／匹配默认为 503，不返回假 version=0 的可用任务列表。

`PromptDetailOut` 固定字段：

- task_type、state（not_initialized/initialized）、latest_contract_version、latest_default_revision、guidance_fields（最新 contract 字段列表）。
- latest_default：`{default_revision, contract_version, guidance_map}`，来自最新 contract 下最新默认；已初始化也必须提供，支持比较和新字段预填。该读接口只提供当前默认，不新增历史默认查询入口。
- personal_revision、guidance_map、based_contract_version、accepted_default_revision：未初始化均 null；已初始化为本人当前版本数据。
- based_guidance_fields：未初始化为 []；已初始化从其 based contract 行读取。普通编辑使用此字段集，不能在待适配时套用最新字段集。
- adaptation_state、required_contract_version、pending_default_update、last_rejected_default_revision：未初始化分别 current/null/false/null；已初始化沿用 1A 派生状态与本人标记。不向 API 输出内部 head_adaptation_state。

只读服务扩充上述缺失字段，并校验已知任务契约／默认存在；所有字段同一请求数据库快照读取，不能跨事务拼接。最新默认与本人指导分列，不能把默认或新字段自动 merge 到个人版本、写 head 或标为已适配。未初始化详情展示默认，不创建版本；显式 initialize 才建立初版。缺 based contract 等数据库不一致为 503。字段结构展示无需公开可写系统 schema，也不新增任意 schema 编辑器。

`PersonalInitOut`：state 固定 initialized、idempotent bool、task_type、personal_revision、guidance_map、based_contract_version、accepted_default_revision。首次建立 revision=1；重复初始化返回现存版本、不新增事件、不解除待适配状态（客户端后续 GET 派生状态）。不增加 expected=0 初始化与读取最新默认的竞争语义；继续使用现有显式、幂等服务。

`PersonalWriteOut`：state 固定 initialized、task_type、personal_revision、guidance_map、based_contract_version、accepted_default_revision、adaptation_state。PATCH／accept／adapt 返回该次服务已提交版本，不在返回前重新读最新 head 冒充本次版本。

`PersonalRejectOut`：state 固定 unchanged、idempotent bool、task_type、personal_revision、last_rejected_default_revision。拒绝不增加个人版本；同有效状态重复拒绝不增加事件。之后主动接受同默认仍可成功。写响应不隐含更晚默认已被处理，客户端可 GET 刷新状态。

普通编辑保留其 based contract；待适配仍可编辑旧字段且保持待适配。accept／reject 在待适配时 409；accept 只改选定字段、保留未选字段；目标默认必须存在且与本人 based 和当前 contract 兼容，不能跨结构接受。adapt 必须完整当前字段集，旧 target contract 为 409，缺字段／未知字段为 422，不替客户端补齐；普通编辑／拒绝不能代替完成适配。

2026-10-07 用户确认方案 A：接受绑定教师实际查看并勾选的默认修订；比较期间管理员仅发布更新的默认文字，不使同契约的旧目标失效，也不自动替换教师所见内容。目标仍须存在且与本人 based／当前 contract 兼容，个人 expected 仍须有效。成功只记录所接受修订，更晚默认仍作为未处理更新展示，不视为一并接受。 因此 target_default_revision 不要求等于最新 default revision；仅默认文字推进不返回冲突，个人版本冲突及契约不兼容仍按既有规则拒绝。

## 6. 管理员默认接口

| 方法／路径 | 请求 | 服务／响应 |
| --- | --- | --- |
| GET `/api/admin/prompt-defaults/{task_type}` | 无 | 新增只读 `read_default`；`PromptDefaultOut` |
| PATCH 同路径 | `expected_default_revision` 正整数、`guidance_map` 非空局部 map | `update_default(..., patch=guidance_map)`；`PromptDefaultOut` |

`PromptDefaultOut`：task_type、default_revision、contract_version、guidance_fields、guidance_map。GET 为当前 contract 下最新默认，PATCH 为本次提交的默认及其 contract 字段集（必要时在服务返回增加该字段）；不额外读取较新默认覆盖本次返回。不接收 schema、contract_version、guidance_fields、created_by 等字段。发布按最新数据库 contract 验字段，保留未选文字，新增默认 revision，不覆盖个人版本、不触发任务、不推进 accounts.version 或 school_settings.version。

## 7. 固定错误契约及防泄漏

沿用 `{error:{code,message}}`；message 取现有中文固定状态消息。1B 的校验错误不返回 fields；不能透传异常字符串。

| 情况／typed exception | HTTP／code |
| --- | --- |
| AuthRequired、有效会话失效 | 401 AUTH_REQUIRED |
| Forbidden、非管理员、跨本人 | 403 FORBIDDEN |
| 不在 7 项白名单的 task_type（已认证且通过路由角色检查） | 404 TASK_TYPE_NOT_FOUND |
| VersionConflict | 409 VERSION_CONFLICT |
| PromptNotInitialized（编辑／接受／拒绝／适配） | 409 PROMPT_NOT_INITIALIZED |
| PromptAdaptationRequired | 409 PROMPT_ADAPTATION_REQUIRED |
| ContractAdvanced | 409 PROMPT_CONTRACT_CHANGED |
| DefaultContractMismatch（含不存在目标 revision） | 409 PROMPT_DEFAULT_CONTRACT_MISMATCH |
| 请求 schema、FieldViolation、AiConfigValidationError、BaseUrlInvalid | 422 VALIDATION_ERROR |
| KeyMaterialMissing／Invalid、DecryptUnavailable（写配置需要密钥时） | 503 AI_CONFIG_UNAVAILABLE |
| 已知任务种子缺失／数据库不一致、SQLAlchemyError、服务基础不可用 | 503 SERVICE_UNAVAILABLE |

未知任务先显式识别为 404；已知任务服务因缺行抛 UnknownTaskType 不得误报 404。不要将所有 ValueError／IntegrityError 统一伪装成 409；未预期完整性故障为 503。仅捕获具体已知类型并固定映射；保留服务完整回滚，路由不提交或重试。配置 GET 的认证解密失败已由服务降级，不走上述写入 503。

安全边界包括 secret 本身、非法 URL 中的 userinfo／query、恶意未知字段名、嵌套 map 键／值、非法 JSON、类型错误和 validator ctx。现有全局 RequestValidationError handler 会返回 loc 最后一项和原 msg；对 1B 路径（包括操作后缀）新增明确匹配分支，固定 422 VALIDATION_ERROR，不输出 errors/input/ctx/loc/body。既有路由保持现有处理。服务异常映射 `raise ... from None`，不记录 exc_info 或原异常 repr。测试用合成标记，验证实际 HTTP body／应用日志无标记，不打印标记；不承诺框架外调试器的 locals dump 安全。

## 8. 验证矩阵与交付门槛

| 编号 | 必须验证的实际边界 |
| --- | --- |
| B1 路由与身份 | 12 条接口真实 ASGI 注册／响应；教师、待分配、管理员本人；teacher→admin 403；未登录及无效会话 401；无他人入口／请求 identity 字段 422。每个写接口 Origin／Content-Type 拒绝，GET 无 Origin 可读，成功／错误 no-store |
| B2 严格输入 | 每种请求必填／extra/type/null；版本 bool／字符串／浮点拒绝；secret 未传与 null/空串区分；指导 8000 接受、8001 拒绝；空 patch／接受列表、重复／未知字段／缺适配字段；未知 task 404 |
| B3 安全输出 | GET/PATCH/DELETE 配置白名单及固定遮罩；合成 secret／密钥／DSN 标记不出现在 HTTP 和应用日志；构造 validator、非法 URL、非法 JSON、恶意字段名及嵌套键值／服务异常；原有路由错误和手工接口直接回归 |
| B4 版本和指导 | API 覆盖未初始化→显式初始化／重复；按字段编辑／接受保留未选字段；拒绝版本不变、幂等及再接受；旧 expected 409；最新默认对比、普通编辑旧 based 字段、待适配 accept/reject 409、旧 contract 409、v2 完整适配后新字段可编辑；不改运行时 registry 冒充发布 |
| B5 真库权限／事务 | 无业务服务或 AuthSnapshot mock 的真实 ASGI＋隔离 MySQL，合成 cookie 经过真实 get_auth_snapshot；跨本人隔离、teacher/default 403、管理员本人配置独立；撤销／过期／停用／auth_version 失效；依赖形成 snapshot 后、写服务锁前真实另一连接撤销会话／停用，写入 401 且无版本/审计增量 |
| B6 真库只读／失败 | 各 GET 前后 head、版本、处理标记、事件/审计和 accounts.version 不变；配置清除／保留/轮换重连确认；旧 expected／非法结构/适配失败全部无增量；默认发布未自动改个人；缺失/错误密钥配置 GET 200、清除成功、需要密钥的 PATCH 503/回滚；手工日周与 Word 定向回归 |

无数据库 ASGI 测试可 override 依赖、mock 服务，只证明 HTTP 边界；真实 MySQL 测试必须经过路由、middleware、真实 cookie 依赖和业务服务，重连检查数据，不能用 mock 权限断言替代。使用既有标准库 ASGI 驱动，不新增 httpx／pytest。不启动 API/Vite/worker 网络服务器。

环境授权在编码提示词中限定为本次新建一次性 mysql:8.4.11、127.0.0.1:13387、kindergarten_test_ai1a 与 kindergarten_test_ai1a_fresh；复用已审阅 AI1A guard 开关，所有连接与 Alembic 前校验。只使用本轮合成凭证及密钥，全程 APP_DISABLE_DOTENV=1，模块导入前清除继承私人 DATABASE_URL／AI_MASTER_KEY／AI_MASTER_KEY_ID。不新增依赖、不下载 Python、不换库。

执行新 B1–B6、全量 backend/tests/unit、既有 50 项 1A MySQL 测试及新增 1B 真库测试；报告实际数量／skip，不把 607／50 的历史结果当本轮证据。核对两库实际 current、repository 唯一 head 20261003_ai1a_config_prompts、uv lock --check --offline、git diff --check。资源不可用则完成独立工作并明确阻塞，不宣称真库通过。清理仅本次容器／专用卷，列确切 ID 与清理命令及检查结果，不清理其他资源或镜像。

交付结果写独立报告，OpenCode 停止等待协调者只读复审。API 自动验证不替代 1C 浏览器产品验收、transport／真实 AI、worker 或完整 W6 材料产品验收；不授权部署、SSH、commit/push。
