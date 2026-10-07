# 给 OpenCode：AI 1C 夹具工具最小补修（2026-10-07）

请阅读 AGENTS.md、[复审报告](ai-slice1c-fixture-tool-review-2026-10-07.md)、[原提示词](ai-slice1c-fixture-opencode-prompt-2026-10-07.md)和[夹具方案](ai-slice1c-fixture-plan-2026-10-07.md)，修正 R1／R2 与已要求的验证缺口，交协调者复审。保持原“本地工具／测试交付”停止点；保留所有协调者与用户已有文档修改，不 reset／stash，不改 app/、registry、迁移、前端、锁、依赖或产品规则。不得连接远程、部署、操作主密钥、调用供应商、commit／push。

## 必修项

1. **R1 提交结果**：run_publish 提交前捕获结果需要的全部标量和容器，commit 成功后无 ORM 属性读取／隐式 SELECT。补有效离线回归，证明 expire_on_commit=True 不触发提交后刷新。不得以 commit 后 rollback 声称撤销已经提交的发布。区分提交前确定回滚与 COMMIT结果不确定的异常；不确定时只提示先 inspect 核对，不能自动重试。保留固定去敏输出，无SQL参数／原始异常。
2. **R2a／b／c／d／e／f**：改合法 v2→v3 被放入拒绝矩阵；定义 BACKEND_ROOT；真实 MySQL JSON 结果正确解码、map 不依赖键序；head 查询列与断言一致；SQL 写失败错误契约和超长ID故障测试一致；v1个人种子是完整六字段合成 map。不得通过跳过、删除必要测试或改配方规避。核心异常与CLI应按各自边界测试，不将原始DataError宣称已经转换为固定码。
3. **生命周期与竞争**：seed连接使用上下文关闭；所有工作线程有限超时、确认退出、异常收集，清理在退出后进行。覆盖工具发布与既有 prompt_service.update_default 同任务争用锚点的真实并发，给合法身份／会话准备及版本基线，不改产品服务。线程同时启动不等于已证明等待同一锁，需记录或用明确屏障建立实际争用。
4. **不变式和编号**：比较真实合法个人完整文字／head、accounts.version、school_settings、operation_records、prompt_change_records、其他任务与合成业务记录的前后规范化快照。构造已有较高默认revision，再发布v2/v3，确认从全历史MAX+1延续；不以简单1→2→3替代。保留第二份真实写失败、后置失败与旧expected拒绝的零增量断言。
5. **inspect／文档**：最少列查询避免读取默认指导全文；使用方法明确 cwd 和真实路径；另写 `docs/bootstrap/ai-slice1c-fixture-repair-result-2026-10-07.md`，保留原报告历史，不把未执行的真库改成通过。

文件范围：现有工具及其单元／集成／guard四文件，必要的本片测试辅助及新补修报告。开始前列实际范围，其他问题只报告。

## 验证和停止点

清除继承的应用 DSN、主密钥、发布开关及集成变量，APP_DISABLE_DOTENV=1，以现有 backend/.venv 执行适当后端单元回归，git diff --check。报告实际命令、计数、skip、受阻及敏感输出检查。

真实 MySQL 仍需独立受控资源：已获授权的一次性 MySQL 8.4／InnoDB、127.0.0.1:13387、精确 kindergarten_test_ai1c_fixture、独立测试账号及迁移准备权限，只有 AI1C_TEST_ALLOW_PREPARE=yes 与专用 DSN 具备时才执行。没有资源就明确“真库受阻”，不安装、拉镜像、创建库、借其他套件库或用 SQLite 替代。协调者随后准备具体资源清单；未0 failure／0 error／0 skip前不声称远程可用。

请交付补修文件与新报告，并停止于协调者复审；不自行进入远程发布或Windows验收。方案 A 无须再确认，也不增加“默认目标必须最新”检查。
