# AI 1B 最小补修编码交接（2026-10-04）

交给 OpenCode 执行；协调者只读复审，不能用当前 634／13 的结果宣布收口。本文件不自动启动执行器、不授权部署。补修后复审通过，再执行独立 1C 交接。

```text
你是 kindergarten-manager-next 业务代码唯一写入者 OpenCode。本轮只补修 1B R1–R4，不重新规划、不进入 1C。先读 AGENTS.md、1B 定稿 ai-settings-api-1b.md、ai-slice1b-review-2026-10-04.md 和本片既有编码提示词／实现报告，沿用最新 1A 收口及 R1–R7、S1–S5。

记录 HEAD／status／既有修改，保留所有未提交内容。只改 schemas.py 的 1B 响应区域、两份 test_ai1b_* 测试；如 HTTP 输出安全确有缺陷，可最小修本片 router/main.py 安全分支并报告。不得改服务／models／迁移／依赖锁／auth_service／frontend／日周 Word；超范围缺陷先报告。不要读 .env 或私人密钥、安装依赖／Skill／MCP、另起编码代理、启动 API/Vite/worker、SSH／部署／commit/push。

R1：真 cookie 逐项验证过期、已撤销、停用、auth_version 不符。管理员实际保存本人配置，再验证教师与管理员本人互相隔离。真实 snapshot 已形成后、原 lock_self 被调用前，用另一连接提交撤销或停用，然后继续原身份复核和锁服务；夹具只控制时序，不能 mock 业务服务／身份结果。不得在 account 锁已经取得后同步等待另一连接停用造成死锁。请求应 401，重连对账版本/head/事件/审计无本次请求增量；外部身份变化自有增量独立记账。按配置、个人指导、管理员默认写入口覆盖事务身份复核。

R2：先改一个不会被选中的个人字段，再按字段接受，断言未选文字完整保留。重复 reject 重连核对事件数量、seen/rejected 标记和个人版本；之后再接受。v2 实际发布后实际发送 reject 并断言 409。所有旧 expected、非法结构、缺/未知适配字段失败，重连核对完整 head/版本/事件/审计/处理标记及 accounts.version 不变。配置保留／轮换／清除重连检查实际版本及密文认证结果，合成明文只断言、不打印。建立含密文配置后分别移除主密钥／换错误主密钥：GET 200 DECRYPT_UNAVAILABLE、DELETE 成功、需加密／保留密文 PATCH 503 AI_CONFIG_UNAVAILABLE 且全部写集合无增量；清除后的无密文元信息保存成功独立测试。

R3：按 B1–B3 做表驱动标准库 ASGI 测试。每种输入 DTO 独立必填/extra/type/null，所有版本字段拒 bool/浮点/字符串；每个写接口验证缺/错 Origin、非 JSON 及 no-store；12 条接口验证合法响应。8000 边界 mock 服务合法成功结果并断言 200，8001 422。应用日志使用临时 handler 采集并完整恢复，成功/错误 HTTP body 和应用日志都检查合成 secret/主密钥/DSN 标记不出现；分别构造非法 URL userinfo/query（无 extra 干扰）、恶意未知键、嵌套 guidance 键值、含标记非法 JSON、validator ctx 和 typed 服务异常，不打印标记。保留原有路由回归、清理所有 overrides/mock/handler。

R4：AiConfigOut.protocol_id 约束为 chat_completions_v1 或 null，ready_reason 约束定稿五个值或 null，TaskStatusOut 的两个 latest 版本为正整数；保持字段名/正常响应不变。新增合法／非法 DTO 边界验证，不能靠 mock 返回异常数据而让测试得到未经处理的 traceback。不要将建议 SecretStr 扩成其他服务重构。

真实 MySQL 资源权限沿用原 1B：仅本轮新建 mysql:8.4.11、127.0.0.1:13387、两白名单测试库；不复用任何预存容器/卷，不连接远程库。guard 每次连接与 Alembic 子进程前校验，AI1A_TEST_ALLOW_DESTRUCTIVE=yes 和 AI1A_TEST_DATABASE_URL；APP_DISABLE_DOTENV=1，导入前清除继承 DATABASE_URL/AI_MASTER_KEY/AI_MASTER_KEY_ID，只用本轮合成材料，不打印或报告凭证/DSN。允许拉取已授权镜像，不安装 Docker/依赖、不改宿主服务。资源不可用则独立检查继续，真库标受阻，不换库、不虚称通过。

复跑新增 1B／全量 backend unit／原 50 项 1A 与全部新 1B MySQL，执行缺/错主密钥手工日周/Word定向回归；核对两库真实 current、repository heads、uv lock --check --offline、git diff --check。报告实际新数量/失败/skip与 R1–R4 到测试名、命令、重连断言的对应表。列完整本轮容器/卷 ID、精确清理命令和清理核查，只删除本轮资源。第一轮历史截断 ID 无法恢复则如实写未能恢复，不臆造。

新增 docs/bootstrap/ai-slice1b-repair-result-2026-10-04.md，保留原报告，明确本次实现/自动验证/产品验收状态和未执行项。交付后停止等待协调者复审，不直接转 1C 或部署。
```
