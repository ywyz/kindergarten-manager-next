# AI 1C 夹具第二轮补修复审（2026-10-07）

结论：**S1–S5 已解除，S6 的两个新锁辅助函数仍有确定错误，暂不放行远程使用。** 只需对这两处集中最小补修并补入口验证；工具R1不重做、产品代码不改。随后必须完成真实MySQL验证，不能继续用集成skip收口。

依据：[第二轮交付报告](ai-slice1c-fixture-repair2-result-2026-10-07.md)、[上次复审](ai-slice1c-fixture-repair-review-2026-10-07.md)。本轮本地只读审阅与离线执行；协调者仅写文档，未改工具／测试代码，未创建MySQL资源、未连接远程、未部署或commit／push。

## 成立的修复及独立验证

- S1 create_engine导入、S2教师账号常量、S3 SchoolSettings实体提取修正成立，实际新增离线检查走到了相应函数。
- S4只检验拒绝方码、S5按工具与真实管理员动作区分保护和审计，原相互矛盾的断言已修正。
- 产品竞争会话使用expire_on_commit=False，实际API会话口径及范围外观察已正确补记；没有新增产品缺陷任务。
- SQLite内存离线测试已加入engine.dispose清理，提交边界回归仍保持R1证据身份，不代替MySQL。

协调者在backend清除应用DSN／主密钥、夹具发布与集成变量，APP_DISABLE_DOTENV=1、PYTHONDONTWRITEBYTECODE=1、PYTHONWARNINGS=always：

| 命令 | 独立结果 |
| --- | --- |
| `.venv/bin/python -m unittest discover -s tests/unit -t . -q` | 686项OK，15.935秒，无警告输出 |
| `.venv/bin/python -m unittest tests.integration.test_ai1c_acceptance_fixture -q` | 26项OK，其中12项离线实跑、14项MySQL测试全部skip，0.158秒 |

新增离线检查没有覆盖下面两个辅助函数，因此上述通过不证明它们可运行。

## T1：锁持有函数向事务对象执行SQL（阻塞）

`backend/tests/integration/test_ai1c_acceptance_fixture.py:379–390`：control_connection.begin()返回RootTransaction，随后control_tx.execute(...)。SQLAlchemy 2的RootTransaction只负责事务生命周期，不提供execute；应在control_connection上执行SELECT FOR UPDATE。

独立离线核验实际RootTransaction类无execute属性；用只提供相同连接／事务接口的替身调用现有_hold_anchor_lock，直接AttributeError。异常发生在函数返回前，调用方尚未取得资源三元组，因此它的finally不能清理，辅助函数自己也没有失败清理。两项受控锁测试都到不了真实MySQL锁竞争。

补修：连接执行SQL，事务对象用于rollback；取得资源或执行锁查询失败时，函数内部依次清理已取得的事务／连接／引擎，不漏连接，也不把失败路径当成功返回。离线覆盖成功路径、begin／执行失败的清理次序，再由MySQL验证真实锁。

## T2：发布后的断言误放进释放锁函数（阻塞）

同文件:391–443：_release_anchor_lock的rollback／close／dispose之后包含一大段v2/r2、字段map／head／个人文字断言；其中还读取没有在此函数定义的after。该代码原属test_publish_v2_success_is_atomic。

两个受控锁测试都在“保持v1、竞争方超时拒绝、尚未再次发布”时调用释放辅助函数。因此它会先把合法v1状态错判为应该已v2；即便输入v2快照，后续也NameError(after)。还会在finally里掩盖真实原始错误。

独立离线复现：释放函数收到合法v1数据，在已完成资源释放后AssertionError；改用合法v2数据又在after引用处NameError。探针不创建engine或数据库连接。

补修：_release_anchor_lock只负责事务／连接／引擎释放，不查询数据库、不假定已发布、不执行产品断言。把字段／完整map／created_by／input_vars／output_schema／head／个人保护断言恢复到test_publish_v2_success_is_atomic，使用该测试真实after快照；不能删除必要断言来绕过问题。

## 后续门槛

交OpenCode按[第三轮最小补修提示词](ai-slice1c-fixture-repair3-opencode-prompt-2026-10-07.md)修正T1/T2。集中检查新增锁辅助入口，不再新增产品范围。S6受控锁测试设计方向成立，运行正确性及真实锁等待仍待实测。

修正并复审后，下一步应是**获授权的一次性MySQL8.4资源验证**：127.0.0.1:13387、精确kindergarten_test_ai1c_fixture、仅本库测试／迁移账号。14项真库用例须实际执行且0 failure／error／skip；之后再形成独立远程实例的具体执行清单。当前没有这项资源操作授权，不安装／拉镜像／创建库。

本轮不需要用户重新决定产品规则，方案A保持不变；原部署和Windows缺夹具案例仍保留原状态。
