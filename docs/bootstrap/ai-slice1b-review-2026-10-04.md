# AI 1B 实现审阅（2026-10-04）

结论：**暂不收口。12 条 API 的主体实现已具备，独立执行 634 项单元测试通过，但定稿 B1–B6 的必需验证仍有缺口，响应 DTO 也有契约约束遗漏。先由 OpenCode 最小补修，再复审；1C 规格和编码交接可以提前准备，不能据当前报告宣布设置产品验收完成。**

依据：[1B 定稿](../specs/ai-settings-api-1b.md)、[实现报告](ai-slice1b-implementation-result-2026-10-04.md)、最新 1A 收口、AI／提示词／日志 Contract。审阅 HEAD 为 `1647fc934d41b29a844a807d454031e66a2b45af`；实际审阅对象是含未提交 1A／1B 的工作区，HEAD 不能代表完整实现。保留全部既有修改和历史报告。

## 1. 需补修的发现

### R1（P2）：B5 真实身份失效矩阵及撤销时序不完整

位置：`backend/tests/integration/test_ai1b_settings_api.py:105`、`:181`。

当前覆盖匿名／不存在 cookie 和一次真实会话撤销，但没有 1B ASGI 的过期、已撤销、账号停用、auth_version 不符矩阵。管理员本人配置测试只 GET 未配置状态，没有管理员实际写入后与教师配置隔离的证据。

`revoke_then_validate` 挂在 `validate_locked_session` 上；`ai_locks.lock_self` 此时已经取得 account 锁，因此测试并非报告所称的“服务锁前”。它确实验证了会话锁复核拒绝撤销，不能据此证明账号锁之前被停用的边界。需在真实 snapshot 已形成、调用原 `lock_self` 之前控制时序，另一连接提交撤销／停用，再继续真实服务。不能在已持 account 锁后等待另一连接停用账号，也不能返回伪造 snapshot 或 mock 身份判定。

补验真实 401；重连确认配置／个人／默认 head、版本、事件、审计与账号版本没有本次请求增量。外部停用事务自身的变化应单独作为基线，不误算为请求写增量。

### R2（P2）：B4／B6 报告宣称的行为缺少对应断言或实际场景

位置：上述集成文件 `:375`、`:430`、`:548`、`:580`。

- “未选字段保留”只有注释，未先改未选个人字段并在接受后断言；重复拒绝只断言版本／幂等标志，没有事件和处理标记对账。
- “待适配 accept/reject 阻断”实际只发 accept，没有 reject 请求。
- 旧 expected、缺字段／未知字段适配失败只检查 HTTP 状态，未重连证明版本／head／事件／审计及处理标记全部不变。
- 缺主密钥测试发生在 secret 已清除之后；末尾重新设置了主密钥再 GET 无密文配置，并不是“已有密文＋缺主密钥 GET 降级”的实际验证。DELETE 也未在“已有密文＋缺／错主密钥”状态执行。错误密钥测试只有省略 secret 的 PATCH，未对失败的全部写集合核查回滚。
- 清除／保留／轮换主要断言响应，不足以证明重连后的密文仍对应预期合成 secret、旧版本保留及 head／审计真实一致。可调用既有内部版本读取验证，但只能断言，不能输出明文。

这些不是已经证实的业务实现错误，而是定稿要求的验证缺口。不能由旧 1A 服务测试替代新增 HTTP 边界，也不能用“13 tests OK”推导 B1–B6 已全覆盖。

### R3（P2）：B1–B3 的安全和严格输入覆盖不足

位置：`backend/tests/unit/test_ai1b_api.py:210`、`:269`、`:343`、`:415`。

Origin／Content-Type 测试仅发配置 PATCH；版本严格类型仅发配置 DELETE；各请求 DTO 的必填／extra／type／null 没有逐项覆盖。8000 字符用例仅断言不是 422，服务未 mock 成功，503 也能让它通过。

没有采集应用日志的断言。名为 `test_unknown_keys_and_nested_values_do_not_leak` 的测试实际只包含非法 URL 和 extra key，没有 guidance 的嵌套键值；extra 又会先挡住请求，不能独立证明服务 URL 错误映射安全。非法 JSON 未带合成敏感标记。需分别测试实际 URL 校验、嵌套 guidance、恶意字段名、非法 JSON、validator／typed 服务异常，并在成功和错误路径采集应用日志与 HTTP body，断言合成 secret／主密钥／DSN 标记不出现。不能只凭“未见日志调用”宣称动态无泄漏验证完成。

### R4（P2）：响应 DTO 未完整约束定稿白名单枚举与正版本

位置：`backend/app/schemas.py:980`、`:991`。

`AiConfigOut.protocol_id`、`ready_reason` 是任意字符串；`TaskStatusOut.latest_default_revision/latest_contract_version` 允许 0。定稿明确要求响应约束枚举、ready_reason 固定五种原因，已知种子缺失 503、不伪造零版本可用状态。

协调者用一次性内存脚本复现：DTO 接受未知协议／未知 reason 及零 latest 版本；mock 脱敏服务返回未知 reason 时真实 ASGI GET 返回 200 并透传该值。该复现不表明正常服务当前会产生未知 reason，也没有发现真实 secret 泄漏；它证明边界约束未落实。最小收紧该响应区域并增加负例即可，不需要修改服务／模型／迁移或架构。

## 2. 已核对成立的实现

- 12 条路由已注册，个人 target 取真实会话 account_id；管理员路由先检查角色，管理员服务读取／写入继续复核身份。
- 配置省略 secret 映射 `SECRET_UNSET`，显式 null／空串被拒；成功配置输出显式脱敏且遮罩固定。
- 详情同时读最新默认、个人文字与两套字段；GET 不主动初始化，写响应使用服务返回的本次结果。
- 动态字段由库内 contract 检查，普通旧 based 编辑、完整适配及版本事务复用 1A；路由没有直接 ORM 写入／额外 commit。
- 新 RequestValidationError 分支固定错误体，typed 服务异常固定映射且 `raise ... from None`；已有路由错误处理保留。

## 3. 本轮独立验证与证据限度

在 backend，导入前移除继承 `DATABASE_URL`／`AI_MASTER_KEY`／`AI_MASTER_KEY_ID`，设置 `APP_DISABLE_DOTENV=1`、`PYTHONDONTWRITEBYTECODE=1`：

- `.venv/bin/python -m unittest discover -s tests/unit -t . -q`：**634 tests，OK**，含 27 项 1B。
- `.venv/bin/alembic heads`：唯一 `20261003_ai1a_config_prompts`，仅 repository head，不是数据库 current。
- `/home/ywyz/.local/bin/uv lock --check --offline`：通过，27 packages。
- 仓库 `git diff --check`：通过。
- 一次性 DTO／ASGI 内存复现：R4 成立；脚本未落入业务文件。

实现报告记载 50 项 1A 和 13 项 1B MySQL 通过。协调者本轮只读审阅这些源码，**没有创建容器、连接数据库、独立复跑 MySQL、核验数据库 current 或资源清理**。测试通过报告不能补足不存在的场景。第一轮容器 ID 仍为截断值，后续若无法恢复完整 ID 应如实标为记录缺口，不能臆造；第二轮报告完整 ID 和卷 ID 保留为实现者证据。

本轮未改业务代码、读 .env／私人密钥、安装依赖／Skill／MCP、启动服务器、SSH、部署、commit/push。实现／自动测试／产品验收分别记录。

## 4. 1C 与桌面验收顺序

**1C 有明确编码工作，必须在桌面浏览器验收前完成。** 当前 `SettingsView.vue` 只有姓名／密码；`api.ts`、`types.ts` 无 1B 设置接口与 DTO，现有教师、待分配和管理员已能进入本人设置。

顺序为：本记录 → [1B 补修交接](ai-slice1b-repair-opencode-prompt-2026-10-04.md) → 协调者复审 → [1C UI 规格](../specs/ai-settings-ui-1c.md)／[1C 编码交接](ai-slice1c-opencode-coding-prompt-2026-10-04.md) → 前端 typecheck/build 与协调者审阅 → 单独授权的远程验收部署 → 桌面版真实浏览器验收。

1C 提前实施的是设置 UI，不包含 AI 调用。真实供应商／worker／候选／材料／完整 W6 不依赖本次桌面设置验收，也不因它通过而完成。2026-10-02 的 I5 部署例外不是本轮 AI 部署授权；桌面接续仍使用既定远程实例口径。
