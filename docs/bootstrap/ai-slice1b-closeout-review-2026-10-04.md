# AI 1B 第二轮补修复审与阶段收口（2026-10-04）

结论：**本轮复审通过，S1／S2 已解除，未发现阻塞进入 1C 编码的问题。** 1B 已提供设置前端所需的 12 条接口，精确行为见 [API 规格](../specs/ai-settings-api-1b.md)。本记录确认实现审阅与自动验证证据达到 1B 门槛，不表示浏览器产品验收完成，也不自动启动编码或部署。

依据：本片有效规格、交付代码及下述最终复核证据。重复的旧结果／审阅与已执行提示词已于 2026-10-07 清理，历史版本可从 Git 查询。

审阅对象为未提交工作区，HEAD 仍为 `1647fc934d41b29a844a807d454031e66a2b45af`；既有修改全部保留。协调者只读业务代码、执行无数据库检查、只读核查临时资源并更新审阅与交接文档，没有修改业务代码、读取 .env／私人密钥、安装依赖／Skill／MCP、创建容器、连接数据库、启动服务器、SSH／部署或 commit/push。

## 1. 阻塞项复核

| 项目 | 源码与验证结论 |
| --- | --- |
| S1 身份矩阵独立性 | `backend/tests/integration/test_ai1b_settings_api.py:291` 恢复有效账号和会话；`:353` 四例均先以同 cookie GET 200，再只改变过期／撤销／停用／auth_version 中一个条件。另一连接确认目标失效及其他三个条件有效，合法 GET／PATCH 均要求 401 AUTH_REQUIRED。逐例重连比较审计、事件、配置版本、个人版本、默认修订及 accounts.version，配置 head 仍不存在；前一例不再遮蔽后一例 |
| S1 锁前身份变化的版本基线 | 真实 snapshot 后、服务取锁前的外部提交夹具保留。停用测试 `:568`、管理员 auth_version 测试 `:623` 均在外部 UPDATE 前读取 accounts.version，401 后精确断言只有外部 +1；请求产生的版本／事件／审计变化继续被拒绝 |
| S2 DELETE 合法基线 | `backend/tests/unit/test_ai1b_api.py:589` builder 仅含 expected_version；严格输入负例不再被配置元信息 extra 掩盖。每例先用真实 ASGI 路由与合法服务 mock 得 200，再只破坏目标字段 |
| S2 管理员版本与 map | `:675` 使用真实 expected_default_revision，`:682` 将管理员 guidance_map 纳入矩阵；`:696` 根据路由设置真实对应角色的依赖夹具。管理员版本类型负例 4 次、map 负例 7 次，均有 200 基线，不再是空循环或 teacher 403 |
| S2 每 DTO extra | `:816` 覆盖全部 8 种请求 DTO：复制合法 payload 后只增加未知顶层键，逐例要求 422 VALIDATION_ERROR；包括 initialize、DELETE 和管理员 PATCH |

矩阵实际枚举为 missing 17、null 17、版本负例 40、字符串类型 9、map／列表 27、extra 8。它们是测试方法内部负例次数，不与 41 个 1B 测试方法相加。合法服务 mock 只用于无库 HTTP 边界；真库身份测试仍调用真实 cookie 依赖和业务服务。

R2 已核对未选字段保留、重复拒绝／再接受、v2 拒绝、10 个失败请求零增量、密文版本钉住解密及降级元信息保存；R4 已收紧协议／就绪枚举和最新正版本，响应 DTO 验证失败转固定 503 且不带异常链。上述证据继续保留，全量单元检查通过。本轮未发现新增产品决定或系统级架构变更，不需要 ADR。

## 2. 本轮独立证据与限度

backend 检查在导入前清除继承 DATABASE_URL／AI_MASTER_KEY／AI_MASTER_KEY_ID，设置 APP_DISABLE_DOTENV=1、PYTHONDONTWRITEBYTECODE=1：

- `.venv/bin/python -m unittest discover -s tests/unit -t . -q`：**648 tests OK**，9.451s，无 skip，含 41 项 1B。
- `.venv/bin/alembic heads`：唯一 `20261003_ai1a_config_prompts (head)`，不连接数据库。
- `/home/ywyz/.local/bin/uv lock --check --offline`：通过，27 packages。
- `git diff --check`：通过。
- `docker ps -a --no-trunc`／`docker volume ls`：仅有预存 I5 容器及专用卷；实现者报告的本轮两个容器和两个匿名卷均不在当前列表。`ss -ltn 'sport = :13387'`：无监听。以上只证明当前资源不存在，不独立证明创建时镜像／端口／库范围或历史删除过程。

实现者报告本轮原 50 项 1A、23 项 1B、同进程 73 项 MySQL 和手工日周／Word 缺错密钥回归通过，两库 migration current 正确，并如实记录错误测试库指向与 URL 解析失败后的环境重置及重跑。协调者接受该执行报告与可审阅测试作为本片真库证据，**本轮未独立复跑 MySQL 或读取两库 current**。不把 repository heads 当成数据库已迁移证据。

本轮报告已纠正历史匿名卷完整 ID 的说明。报告 §1 将两个已存在的未跟踪测试文件称为“新增文件”不够精确，§2 已明确它们是本轮修改文件；按修改既有两个测试文件、新增结果报告理解，不影响修复或收口结论。合法长度但错误主密钥的所有变体未被本轮额外证明，仍沿用既有测试实际边界。

## 后续状态（2026-10-07 更新）

1A／1B／1C 均已实现并部署，见 [实际部署结果](ai-slice1abc-deployment-result-2026-10-05.md)。本文的测试数量、HEAD 与环境说明是原审阅时的证据，不代表当前工作区的新执行结果。

产品状态以 [Windows 验收报告](ai-slice1c-desktop-validation-2026-10-05.md)为准。剩余契约演进及缺／错主密钥子例仍受阻，当前先完成夹具工具补修与隔离真库验证，再按具体授权准备远程补验。真实 AI、worker、材料及完整 W6 不由本阶段收口替代；当前操作入口见 [文档索引](README.md)。
