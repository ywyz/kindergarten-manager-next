# 给 OpenCode：AI 1C 夹具锁辅助函数最小补修（2026-10-07）

请读AGENTS.md、[本轮复审](ai-slice1c-fixture-repair2-review-2026-10-07.md)及前两轮提示词。工具R1与集成S1–S5已确认成立，不重做；只修T1/T2并覆盖新锁辅助入口。保留所有既有文档改动，不reset／stash。本轮不改产品代码，不创建数据库／容器，不安装／拉镜像，不连接远程、部署、操作主密钥、供应商调用或commit／push。

文件范围：`backend/tests/integration/test_ai1c_acceptance_fixture.py`、必要的本片离线检查及新 `docs/bootstrap/ai-slice1c-fixture-repair3-result-2026-10-07.md`。无须改app/、发布工具、registry、迁移、前端或依赖。

1. **T1**：_hold_anchor_lock中用control_connection.execute查询；begin返回的RootTransaction仅负责rollback。持有查询仍必须执行真实SELECT FOR UPDATE，不以事件或替身代替MySQL锁。取得连接／begin／查询失败时函数内部清理已取得的资源，再原样抛出测试错误，避免调用方尚未拿到返回值而漏连接。离线使用与实际Connection／RootTransaction职责一致的替身，测试成功返回三元组，以及begin／查询失败的资源释放；替身不要提供真实事务对象不存在的execute以掩盖缺陷。
2. **T2**：_release_anchor_lock只负责rollback、close、dispose；清理辅助函数不能读业务数据、假定发布成功或引用after。v2/r2、map值、created_by、复制的input_vars／output_schema、head／个人完整文字断言移回test_publish_v2_success_is_atomic，以该测试实际after快照核对。保留全部必要断言，不通过删除它们让测试通过。离线验证释放函数在未发布／失败路径也能单独运行，且不会访问业务数据库或执行发布断言。
3. 核对两个受控锁测试的调用顺序：持有v1锚点→竞争方真实等待超时／零增量→纯资源释放→再次发布成功→测试内断言。首次异常不能被finally里的无关断言掩盖。沿用有限等待与已确认的线程退出保护。
4. 离线检查须运行上述真实辅助函数路径，另用合成合法发布结果走test_publish_v2_success_is_atomic的实际断言，确保断言恢复位置正确且能拒绝不完整map／改变个人文字。不要新增源字符串检查，不制造“所有检查通过就是MySQL通过”的口径。

用现有backend/.venv、清除继承应用DSN／主密钥、发布开关与集成变量，APP_DISABLE_DOTENV=1、PYTHONDONTWRITEBYTECODE=1、PYTHONWARNINGS=always运行适当单元与本片离线检查，git diff --check；记录实际执行／skip／警告。本轮不新增资源授权，真库资源仍缺时保留14项真库受阻，SQLite或替身不能替代。交新报告后停止于协调者复审，不自动进入远程发布。
