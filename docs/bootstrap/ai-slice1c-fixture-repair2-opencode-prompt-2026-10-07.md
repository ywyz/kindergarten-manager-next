# 给 OpenCode：AI 1C 夹具第二轮集中补修（2026-10-07）

请读取 AGENTS.md、[补修复审](ai-slice1c-fixture-repair-review-2026-10-07.md)、[上轮提示词](ai-slice1c-fixture-repair-opencode-prompt-2026-10-07.md)及夹具方案。协调者已确认工具R1修复成立，不重做发布结果逻辑。集中修复S1–S6及测试／报告问题，交复审；本轮仍不授权远程、创建库／容器、安装／拉镜像、改主密钥、供应商调用、commit／push。保留所有协调者和用户已有改动。

文件范围以现有 integration guard、integration tests、必要单元回归及 `docs/bootstrap/ai-slice1c-fixture-repair2-result-2026-10-07.md` 为主。单元测试内引擎清理也在范围。不改app/、API、产品会话配置、registry、models、迁移、前端、依赖或产品规则；工具若仍有确定问题先报告，不扩大重构。

## 必须完成

1. **S1**：正确导入create_engine；保留连接前目标拒绝。用离线替身证明make_engine在正确目标下到达engine创建、非法目标没有创建调用，不实际连库。
2. **S2**：统一TEACHER_ACCOUNT与所有个人版本／head种子引用，消除未定义FIXTURE_TEACHER_ID；检查所有新增帮助函数的未定义名字，不能只用import成功当作函数路径验证。
3. **S3**：world_state的SchoolSettings查询正确提取ORM实体，不将Row当实体；离线覆盖实际SQLAlchemy Row/标量结果形状和无行分支。保留规范化不变式证据。
4. **S4／S5**：同expected竞争仅校验拒绝方错误码；成功方单独验证。个人／账号／学校等保护与审计断言分开：工具发布成功不写审计；真实管理员发布成功合法追加审计。给两种合法胜负以及不合法额外写入做有效离线回归，不删除真实竞争或保护断言。
5. **S6**：不用屏障间隔或函数返回时间推定锁竞争。构造受控锁持有／释放与阶段事件，实际MySQL锁仍须执行；待释放前另一方不能进入受保护临界区。用合法账号／会话，产品服务测试会话设置expire_on_commit=False匹配真实API；分别确定性覆盖工具胜出与产品胜出，核对提交／拒绝码、MAX+1及审计。有限锁等待、事件等待与线程join；在线程确实退出后再恢复库／清理引擎，不能以assert线程未退出后直接tearDown删除其数据。
6. **清理与报告**：离线测试的SQLite内存engine在finally或addCleanup中dispose，消除未关闭连接ResourceWarning；如继续使用，报告明确“SQLite内存离线单元证据”，不泛称oracle以掩盖方言，不宣称MySQL验证。原报告§9条件性产品观察另在新报告修正：app/database.py实际API使用expire_on_commit=False，不据此新增线上缺陷或编码任务。原报告保留历史。

本轮请在全量单元之外，增加足以发现上述集成函数运行错误的离线检查；这些检查不需要连接数据库，也不能代替真库锁／回滚验证。不要写只比对源代码字符串的检查，不通过移除保护或宽泛忽略异常让测试通过。

## 验证和交付

清除继承应用DSN／主密钥、发布开关、集成环境变量，APP_DISABLE_DOTENV=1、PYTHONDONTWRITEBYTECODE=1，现有backend/.venv跑适当单元回归；独立记录新增离线检查、警告与git diff --check。真库资源未获授权／未具备时仍如实登记skip，不创建库、不借其他环境、不安装依赖。

资源具备后必须实际执行MySQL8.4、127.0.0.1:13387、精确kindergarten_test_ai1c_fixture的隔离集成，零failure／error／skip后才放行远程准备。交付新报告，按S1–S6逐项列修改、实际验证／未执行，并停止于协调者复审。方案A已确认，本轮无产品决定待补充。
