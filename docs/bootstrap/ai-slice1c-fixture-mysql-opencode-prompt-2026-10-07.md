# 给 OpenCode：AI 1C 隔离真库验证与两项测试加固（2026-10-07）

用户已在第三轮复审后明确回复“授权”，批准[一次性 MySQL 清单](ai-slice1c-fixture-mysql-plan-2026-10-07.md)范围。请先读 AGENTS.md、[第三轮复审](ai-slice1c-fixture-repair3-review-2026-10-07.md)、资源清单及既有三轮要求。协调者已准备专用本机容器与精确测试库，测试环境在启动时注入；不得创建／停止／删除资源、访问远程、安装依赖／镜像、读取其他凭证或改全局配置。

仅允许写 `backend/tests/integration/test_ai1c_acceptance_fixture.py`、必要的本片离线测试及新 `docs/bootstrap/ai-slice1c-fixture-mysql-result-2026-10-07.md`。不改 app/、发布工具、registry、迁移、前端、依赖或其他文档；保留全部既有工作区改动，不 reset／stash／commit／push。

1. v2 成功测试直接比较完整 guidance_map dict 与 recipe_guidance_map(2)，不依赖键序；增加字段间值互换会被实际测试断言拒绝的离线变体。
2. 锁辅助各步清理都应尝试。持有函数的 connect／begin／execute 失败须保留原错，不被 dispose 等清理错误替换。释放函数要保留测试体的已有失败，同时让单独清理失败可诊断；补 connect／close／dispose 失败入口验证。不得用宽泛吞错让真库失败变成通过，主锁查询仍是真实 SELECT FOR UPDATE。
3. 用现有 backend/.venv，APP_DISABLE_DOTENV=1、PYTHONDONTWRITEBYTECODE=1、PYTHONWARNINGS=always。已注入 AI1C_TEST_ALLOW_PREPARE=yes 与精确 AI1C_TEST_DATABASE_URL，不能打印 DSN、凭证或原始数据库异常。清除应用 DATABASE_URL／AI_MASTER_KEY／AI_MASTER_KEY_ID 及其他夹具变量；真库运行保留这两个专用集成变量。离线 unit 运行须另清这两个变量，防止扩展到无关套件。
4. 跑直接相关离线检查，随后 `cd backend && .venv/bin/python -m unittest tests.integration.test_ai1c_acceptance_fixture -v`，14 项 MySQL 案例全部实际执行，0 failure／error／skip。不要跑其他启用真库套件。记录 MySQL／InnoDB、迁移、真实锁／1205、竞争胜负、MAX+1、回滚及保护／审计结果。
5. 真库出现错误时，仅在允许文件范围定位最小测试修正；若必须修改发布工具或产品代码，停止对应修改并报告最短复现及建议，协调者先审阅。不得改产品行为来迎合测试。

报告分别登记测试加固、离线证据、14 项真库实际结果、失败／警告／skip、远程与 Windows 尚未进入。完成后停止于协调者只读复审；不自行准备远程清单或结束资源。
