# AI 1B 补修复审（2026-10-04）

结论：**本轮仍未通过阶段收口。R2、R4 的主要补修成立，R1、R3 尚有两处测试夹具导致的验证缺口。未发现本轮新增的正常业务路径错误，但不能用 647／23 项通过代替必需边界验证。下一轮只修测试夹具与报告，不重做 1B、不扩业务范围。1C 设计继续保留，编码门槛尚未解除。**

依据：[首次审阅](ai-slice1b-review-2026-10-04.md)、[补修结果](ai-slice1b-repair-result-2026-10-04.md)、[1B 定稿](../specs/ai-settings-api-1b.md)。HEAD 仍为 `1647fc934d41b29a844a807d454031e66a2b45af`；审阅实际未提交工作区，全部历史和既有修改保留。

## 1. 剩余阻塞项

### S1（P2，原 R1）：身份失效矩阵被第一项过期状态遮蔽

位置：`backend/tests/integration/test_ai1b_settings_api.py:261`，尤其 `:282` 的循环。

第一项把同一 session.expires_at 改为 2020；后续没有恢复到有效状态，又依次设置 revoked_at、is_active、auth_version。真实 `get_auth_snapshot` 先检查会话过期，因此后续 401 都能仅由第一项过期产生。第三、四项还叠加撤销状态；即使去掉停用或 auth_version 检查，该矩阵仍会通过。

需逐例恢复完整有效账号／会话，或拆为各自 setUp 的独立用例。每例先用相同 cookie 确认 GET 200，再只改变该例目标条件；核对其他身份条件仍有效，执行合法 GET／PATCH 得 401，并逐例重连核对无请求写增量。不能只在整个循环最后核查总量。

本轮 snapshot 后／取锁前时序夹具本身成立：先调用真实 get_auth_snapshot，另一连接提交变化，再返回真实 snapshot 给原服务；未伪造身份、未在 account 锁后等待停用。配置撤销、个人停用和管理员 auth_version 改变的三条入口得到实质补验。停用测试读取了 accounts.version 但只断言 row[1]/row[2]，没有断言 row[0]；应补明确外部增量后的版本基线（管理员版本变化同理），使报告的“只含外部 +1”有实际断言。

### S2（P2，原 R3）：DELETE／管理员严格输入夹具没有合法基线

位置：`backend/tests/unit/test_ai1b_api.py:627`、`:651`、`:658`、`:712`。

- DELETE 使用 config_payload，携带 protocol_id/base_url/model 三个不允许的字段。版本即使正确也返回 422，不能证明 bool／浮点／字符串是被版本类型校验拒绝。
- admin_case 使用 edit_payload，含 expected_personal_revision，缺 expected_default_revision；补入后仍保留多余个人版本键。管理员身份下正确目标版本仍 422。该基类默认身份还是 teacher，若仅修 body 还须设置管理员身份，避免角色 403 干扰。
- admin_case 的字段名是内部别名 `default`，VERSION_FIELDS 按 `expected_default_revision` 查找；`get(field, ())` 返回空列表，管理员版本的严格类型负例实际 **0 次**。管理员 guidance_map 也没有对应 case，相关负例 **0 次**。

协调者一次性内存 ASGI 脚本复现（无数据库，无业务文件改动）：

| 检查 | 实际结果 |
| --- | --- |
| DELETE 原夹具，正确 expected_version | 422；多余 protocol_id/base_url/model |
| 管理员真实角色 mock，原夹具补正确 expected_default_revision | 422；多余 expected_personal_revision |
| 管理员版本负例枚举数量 | 0 |
| 管理员 guidance_map case 数量 | 0 |

修正为各 DTO 独立合法 builder／真实字段名，每个请求先 mock 合法服务结果并确认 200，然后一次只破坏目标字段；删除内部 `default` 别名或在枚举前正确统一映射。补齐管理员两个字段、DELETE 版本及所有 DTO extra 拒绝（现在 extra 主要在 initialize／配置中覆盖），使用正确身份、逐 case 清理 mocks／overrides。不要只增加测试方法数量而继续让别的校验代替目标断言。

## 2. 本轮已补齐的部分

| 原问题 | 本轮核对 |
| --- | --- |
| R1 时序与隔离 | snapshot 形成后／锁前真实另一连接改变身份；管理员真实写本人配置并与教师双向隔离成立。失效矩阵独立性仍待 S1 |
| R2 指导与回滚 | 未选字段先编辑再接受并重读对账；重复拒绝事件／标记、再接受；实际 v2 reject；10 个失败请求逐次核对 head、版本、审计／事件／处理标记、账号版本；密文版本 pinned 解密、缺材料 GET／PATCH／DELETE 及清除后元信息保存已补。接受实现者真库执行报告，协调者未重跑 |
| R3 HTTP／安全 | 12 路由合法响应表、全部写方法 Origin／Content-Type、8000 成功／8001 不调用服务、临时应用日志采集恢复、嵌套／恶意键／JSON／typed 错误测试已补。部分 DTO 夹具仍待 S2 |
| R4 输出契约 | protocol_id／ready_reason 白名单、latest 正版本已收紧；所有响应 DTO 在 try 内构建，ValidationError 固定 503 且 from None，避免不受控异常文本。合法／非法响应自动验证通过，属于允许的最小 HTTP 安全修复 |

没有要求新增产品决定、改服务／模型／迁移／依赖或架构。错误密钥现有测试明确使用格式非法材料及不同 key_id；报告不应把它们描述成所有合法长度错密钥场景均已验证。

## 3. 独立检查与限度

backend 命令导入前清除继承 DATABASE_URL／AI_MASTER_KEY／AI_MASTER_KEY_ID，设置 APP_DISABLE_DOTENV=1、PYTHONDONTWRITEBYTECODE=1：

- `.venv/bin/python -m unittest discover -s tests/unit -t . -q`：**647 tests OK**（含 40 项 1B）。
- `.venv/bin/alembic heads`：repository 唯一 `20261003_ai1a_config_prompts`。
- `/home/ywyz/.local/bin/uv lock --check --offline`：通过，27 packages。
- `git diff --check`：通过。
- 一次性内存 ASGI 检查：S2 的有效基线仍 422、管理员两类负例数为零已复现；仅输出状态／字段名／计数，无敏感材料。

实现者报告原 50 项 1A、新 23 项 1B、同进程 73 项 MySQL 通过及两库 current 正确。协调者本轮没有创建容器、连接数据库、独立复跑真库或检查资源清理；这些仍是实现者执行证据。S1／S2 来自可审阅源码和内存复现，不因 MySQL 测试通过报告而消失。

补修报告第一轮历史 ID 说明有轻微记录错误：旧容器 ID 截断，但原报告匿名卷 ID 已是完整值，不应一并说无法恢复完整卷 ID；下一报告纠正即可，不影响本轮资源清理判断。本轮资源完整 ID 作为实现者报告保留，未独立核验。

本轮未改业务代码、读 .env／私密密钥、安装依赖／Skill／MCP、启动网络服务器、SSH／部署／commit/push；只新增复审与下一轮最小交接文档。

## 4. 后续

交 OpenCode 执行[第二轮最小补修提示词](ai-slice1b-repair2-opencode-prompt-2026-10-04.md)，仅修上述测试夹具和证据报告。通过下一次复审后，才解除已定稿 [1C 编码交接](ai-slice1c-opencode-coding-prompt-2026-10-04.md)的前提。产品验收仍须完成 UI 和获授权远程部署后由桌面版进行，不用单元／集成替代。
