# AI 1B 第二轮最小补修交接（2026-10-04）

本轮仅修测试夹具及报告。依据 [补修复审](ai-slice1b-re-review-2026-10-04.md)，不修改已经收紧的业务实现，不进入 1C。

```text
你是 kindergarten-manager-next 业务代码唯一写入者 OpenCode。本轮完成 AI 1B 复审 S1/S2 的最小测试补修。先读 AGENTS.md、ai-settings-api-1b.md、ai-slice1b-re-review-2026-10-04.md、补修结果和既有编码/补修提示词。沿用最新 1A 收口；不重新规划或扩展业务行为。

记录 HEAD/status/既有修改，全部保留。不读 .env/私人密钥、不安装 Skill/MCP/依赖、不另起代理、不启动 API/Vite/worker、不 SSH/部署/commit/push。本轮只写 backend/tests/unit/test_ai1b_api.py、backend/tests/integration/test_ai1b_settings_api.py 与新补修结果文档；不得改 router/schema/services/models/迁移/依赖锁/frontend/旧业务。发现实现缺陷先报告，不自行修超范围文件。

S1：test_identity_failure_matrix_401 当前身份变化连续累积，第一项过期会遮蔽其余三项。每一 case 恢复完整有效账号/会话（或拆独立 setUp 用例），先同 cookie GET 200，再只改变该 case 的身份条件；重连确认除目标条件外其他身份条件有效，再发合法 GET/PATCH 得401。逐例核对版本/head/事件/审计/accounts.version 无请求增量，不能只检查循环末尾总量。保留真实 snapshot 后/锁前夹具；停用和管理员 auth_version 时序测试补 accounts.version 精确断言，外部 UPDATE 的 +1 单列基线，不能只读取却不检查。不得伪造 AuthSnapshot 或 mock 业务服务/身份结果，时序夹具仍调用真实依赖和服务。

S2：DELETE builder 只含 expected_version；管理员 builder 只含 expected_default_revision/guidance_map，设置 admin 身份。每 DTO 每个 case 先用合法输入、真实路由和合法服务 mock 确认200，再单独制造 missing/null/type/extra 目标错误。case field 使用真实 expected_default_revision，避免 default 别名使 VERSION_FIELDS 空迭代；管理员 guidance_map 必须列入矩阵。版本字段逐一拒bool/浮点/字符串（含DELETE/admin），map/accepted_fields结构逐一拒非法值；所有DTO extra单独构造。每个身份/DTO builder必须有有效200基线，不能让多余字段、缺另一必填字段或teacher权限拒绝掩盖目标验证。清理所有 mock/override/日志handler，避免污染全量测试。保留R2/R4及应用日志安全测试，不回退。

复跑新1B单元、全量backend unit、原50项1A和全部1B真MySQL，含手工日周/Word缺/错密钥定向回归、两库真实current、repository heads、uv lock --check --offline、git diff --check。MySQL资源沿用原授权但必须本轮新建mysql:8.4.11、仅127.0.0.1:13387、仅kindergarten_test_ai1a及kindergarten_test_ai1a_fresh，不复用任何预存容器/卷，不连远程库。AI1A guard每次连接/Alembic前校验，AI1A_TEST_ALLOW_DESTRUCTIVE=yes和AI1A_TEST_DATABASE_URL；导入前清继承DATABASE_URL/AI_MASTER_KEY/AI_MASTER_KEY_ID，全程APP_DISABLE_DOTENV=1，只用本轮合成材料，禁止输出凭证/DSN/密钥。允许拉取既有授权镜像，不安装Docker/依赖、不改宿主服务。资源不可用则继续独立工作，真库标受阻，不换库或虚称通过。

新增 docs/bootstrap/ai-slice1b-repair2-result-2026-10-04.md，列实际文件、S1/S2到测试名/合法基线/负例数量/命令/实际结果对应，明确逐例独立身份变化及完整无增量。列确切本轮容器与所有卷ID、清理命令/核查，只删本轮资源。纠正上一报告的历史ID说明：第一轮旧容器ID截断，但原报告已有完整匿名卷ID；不臆造容器ID，不覆盖旧报告。区分实现/自动验证/产品验收，保留历史记录。实际跨日期则报告真实执行日期。

交付后停止等待协调者只读复审。禁止自动进入1C、浏览器产品验收、真实AI、worker/transport/候选/材料/W6/secret清理/部署/commit/push。
```
