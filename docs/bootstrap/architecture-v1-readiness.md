# Architecture v1 实施准备清单

本文保留启动阶段清单与历史实施证据，不是新增产品需求或实现授权。2026-10-02 用户授权修复、远程验收部署、commit/push并更改验证口径。当前优先 I5 片4的Trae Work浏览器下载与Office／WPS逐页验收；自动测试、部署和产品验收分别记录，AI、容量、备份恢复仍待验证。

## 依据与状态

需求来源为本会话的明确回答及用户提供的两份 Word。未读取历史记忆或旧会话，未将旧系统功能推定为新版需求。已有环境审计报告保留，不在本次重复全面审计。

- 系统级已确认事实：[ARCHITECTURE.md](../../ARCHITECTURE.md)。
- 已接受决策：[技术栈与数据库](../adr/0001-stack-and-database.md)、[任务与版本](../adr/0002-background-tasks-and-versions.md)、[部署安全与恢复](../adr/0003-deployment-security-and-recovery.md)。
- 模块 Contract 已建立；I1 账号业务 API、schema 与迁移已实现。验证以 [I1 MySQL 记录](i1-mysql-validation.md) 为准。
- I2 班级、教师首次分配、学期与持久有效日历已实现并完成隔离真实 MySQL 8.4 / InnoDB 验证，事实以 [I2 实施与验证记录](i2-implementation-status.md) 为准。

## 当前行动与环境状态（2026-10-02）

- 当前验收服务为 SSH 密钥连接 `root@bwh.ywyz.tech`，独立实例入口 [kg-next-verify.ywyz.tech](https://kg-next-verify.ywyz.tech)，不再以本机 WSL 运行服务。目标修订已按用户明确指令同步 ADR 0003 与架构事实，技术栈与模块边界不变。
- 允许 Windows 10／11／Server 2022／Server 2025 与 Office 2010 以上桌面 Word／WPS 文字任一组合完成全部必需案例。权威口径见 [当前验收环境](../specs/i5-validation-environment.md)；历史安装或 LibreOffice 原型不追溯变为验收通过。
- 范围竞态本轮获用户明确例外由协调者最小修复，源提交 `2cb8d81`；18 项延迟检查、前端 typecheck/build、Windows与服务器533项单测、服务器I5集成30项0skip通过。实例已部署，真实下载和桌面验收待 [Trae Work 提示词](i5-trae-work-prompt-2026-10-02.md)执行；本轮证据见 [结果记录](i5-remote-validation-2026-10-02.md)。
- 服务器保留独立验收库和合成夹具供Trae Work使用。I5之后先收口AI Service、提示词与持久任务规格，不自动开始下一实现；正式上线容量与备份恢复另列。

## 历史环境与执行状态（2026-10-01）

- 当前仓库已在 WSL2 Ubuntu 26.04.1；Windows 11 Pro 25H2、build 26200.9457；Office x64 与 Word 文件版本 16.0.20326.20158 已经只读查询确认。Word 的实际可用性、浏览器下载及逐页版式尚未验证。
- 当前检查时项目 `.venv`／`node_modules` 曾缺失；已由 OpenCode 按锁文件恢复（本轮自动检查完成），未安装系统工具或新增依赖。
- 按 [新版完整提示词](i5-slice4-opencode-prompt-2026-10-01.md)分层推进；结果见[片 4 验证记录](i5-slice4-validation-2026-10-01.md)：自动检查层（170+533 项单测、30 项集成 0 skip、typecheck/build、隔离服务与代理启动验证）已完成并记录；Windows 浏览器下载与 Word 逐页验收按交接表待人工，不宣称片 4 完成。
- 安装 Windows 版 OpenCode 不是版本采集前提；桌面端自动操作须核查真实工具与权限。见[能力报告](wsl-windows-validation-review-2026-10-01.md)。不主动安装 MCP／Skill。
- I5 验收后建议先编写 AI Service、提示词与持久任务实施规格草案，未决行为列出供确认，不自动实施或部署。

## 历史服务器观察及限制（原 aliyun 目标）

以下为本会话只读 SSH 检查快照，不代表长期可用资源或容量验收：

| 项目 | `ssh aliyun` 检查结果 |
| --- | --- |
| 系统 | 阿里云 ECS，Ubuntu 24.04.5 LTS，x86-64 |
| CPU | 2 个逻辑核心 |
| 内存 | 约 1.6 GiB，检查时可用约 841 MiB |
| Swap | 2 GiB，约 586 MiB 已使用 |
| 根磁盘 | 40 GiB，约 17 GiB 可用 |
| Caddy | 运行中、开机启动、80/443 监听 |
| MySQL | `mysql-server` 容器，镜像标签 `mysql:8.4`，状态 healthy |
| 其他应用 | `kindergarten-manager`、`sonovel` 已运行 |

普通账号无 Docker 查询权限；经只读 `sudo -n docker ps` 获取上述容器清单。未读取容器环境变量、凭证或旧业务数据。镜像标签不是精确补丁版本；具体域名、证书与 HTTPS 链路未在本次验证。

当时用户先前提供的 `bwh` 被更正为错误目标；这是历史决定。2026-10-02 用户重新明确指定 `root@bwh.ywyz.tech` 并授权验收部署，当前状态以上文与本轮记录为准。既有应用与 MySQL 不构成复用旧代码或业务表的依据。

## 待定实施事项

主要业务与系统架构已收口，以下细节须在对应 Feature 启动前明确，不要求一次解决所有问题：

| 事项 | 需要明确的内容 | 最晚时点 |
| --- | --- | --- |
| 日期与计划身份 | 已确认周一至周日、首个不足周计第 1 周、假期连续计周及调休按实际日期归属、跨年不重置；同班同日仅一份有效日计划。已确认以 `chinese_calendar` 判断学期内调休补课日并允许教师自行创建；已确认管理员明确配置优先，库未覆盖年份时提示并允许管理员配置后继续使用、已有计划查看导出不受阻；普通非上课日及学期外日期不得直接创建，需管理员先调整配置 | 日计划 schema 与日期功能前 |
| 活动字段映射 | 已确认自主与自选同义、游戏组保存共用目标指导；同类别同名只占一额，AI 选一个完整来源且负责人可改选；材料按游戏上下文及年级优先提取、不足补充，只存周计划。已确认保留“体能大循环”字样，日计划一项集体加一项自选，周计划两项集体加一项自选；表头园所和班级人员由管理员维护、日计划显示创建者、周计划显示教师名单及保育员已确认，表头起止日期显示该周第一个至最后一个上课日已确认 | 日计划和周计划 AI Contract 前 |
| AI 接入 | OpenAI 兼容协议范围、请求格式、超时、失败分类、有限重试次数 | AI Service 实现前 |
| 任务实现 | 领取、执行标识、合并、防旧结果覆盖、异常重启；运行中配置轮换处理 | 持久任务实现前 |
| 账号细节 | 已确认用户名注册登录、教师姓名在系统设置填写、首个成功注册账号成为管理员；教师密码由管理员重置，管理员密码在服务器恢复。已实现 I1 的字段、API、并发及权限见[账号规格](../specs/identity-registration-and-access.md)；管理员 AI 操作配置入口仍待对应能力细化 | I1 产品前置已收口；AI 配置入口在管理员 AI 操作实现前 |
| 提示词适配 | 更新通知、拒绝/接受、必需字段适配界面及版本留存 | 提示词编辑器实现前 |
| 导出细节 | 已确认无基准不标红并提示、新增替换标红、纯删除不显示、纯移动及格式变化不标红；已确认允许同班导出日计划及已确认周计划、缺项日计划提示确认后导出；已确认周一至周五保留、周末上课增列并按日期排序及假期注明；表头起止日期显示首末上课日已确认；已确认无匹配时提示且不生成空文件、不扩大范围，日计划按日期及周计划按周起始日升序合并，每份新页起、份内自然分页；文件上限及清理待导出实现前细化 | 导出实现前 |
| 运行资源 | MySQL 精确版本、参数、现有负载、连接预算、任务并发、数据增长 | 共存部署前 |
| 备份恢复 | S3 兼容性、凭证和密钥保管、上传完成判断、失败可见性、恢复手册 | 上线前 |
| 安全与日志 | 网络目标校验、密钥轮换、日志留存、敏感错误脱敏 | 对应安全能力上线前 |

没有确认的行为不得由旧系统、工具默认值或实现便利替代产品判断。

## 必须保留的验证目标

1. 约 30 人编辑保存和同时提交 AI 任务时的响应、队列状态、锁等待、资源占用；AI 允许排队。
2. 固定 Word 模板的栏目、活动主题、自然分页、合并导出和标红兼容性。2026-10-02 当前目标为远程服务、Trae Work真实下载与任一允许Windows／Office或WPS组合的逐页检查；历史Ubuntu／LibreOffice渲染结果仅为补充证据，实体打印不要求。
3. 保存与任务登记一致，连续修改合并，旧结果不能覆盖新版本，重启不会盲目重复已发出的请求。
4. 同班周计划唯一性、软删除恢复冲突、管理员修改、调班停用、维护交接与确认权限。
5. S3 备份解密与完整恢复；目标最多丢失 24 小时数据、一个工作日内具备恢复服务流程。

文档审阅本身不启动应用验收，也不把未来需做的验证写成已通过；已有授权的实施／验收任务按其明确范围运行测试。后续每项实现仅做直接相关的基本检查；容量与上线恢复属于明确的后续验证任务，不默认每次改动跑全套。

## 建议下一步与完成条件

### 历史成果：最小实施规格与 Word 模板验证计划

已在 [最小实施规格](../specs/manual-plans-and-word-export.md) 和 [Word 模板验证计划](../specs/word-template-validation.md) 形成文档，覆盖“手工保存日计划 → 汇集周计划 → 确认 → Word 导出”的最小实施规格，复用已有 Contract。这个顺序是实现建议，不改变用户必须交付的全部首版范围，也不将 AI 排除出首版。

日期／周次算法、日计划唯一性、游戏类别及共用目标已获用户确认并同步 Contract；标红及兼容打开环境也已确认。材料生成依据、提取与补充规则，以及同类别同名游戏单名额和完整来源选择已获确认；其余未决项按规格列出的最晚时点收口。

验证计划已列出最小案例与通过标准；隔离原型已生成 11 份样例并检查 31 页，详见[结果记录](../specs/word-template-prototype-results.md)。2026-09-29 用户已将开发与验收基线改为 Windows 11 Pro 主机 + WSL2 Ubuntu + Office 365／Microsoft 365 随附的 Windows 桌面版 Microsoft Word：WSL2 承载服务、数据库和自动测试，Windows 浏览器执行真实下载，Word 桌面端执行 W1–W6 打开与逐页版式验收。Microsoft Word 已是 I5 片 4 完成门槛；旧 Ubuntu／LibreOffice 原型不替代产品验收。业务权限和产品导出代码已由片 3 实现，真实 AI 与片 4 当前目标环境验收仍未完成。

本轮文档已完成：身份与日期、字段映射、表头人员及首末上课日、特殊周增列、游戏数量、缺项保存、同班导出、无匹配行为、合并顺序及份间分页等关键规则已确认，并有正常和异常例子及验证标准。软件具体版本、差异算法验证、文件上限和清理等后续实施事项仍单列，不声称全部技术细节已确定。

原型阶段曾待定生成库；I5 片 2 后已采用 ZIP + lxml 定点修改受控模板的生成路径。原型字体替代及开发版引擎限制保留为历史证据。最小项目骨架和后续 I1–I4／I5 片 1–3 已分步实施，结果见下文；不据此自动实施未授权业务。

### 当前成果：最小项目骨架（2026-09-21）

已建立 `frontend/`（Vue 3、TypeScript、Vite、Element Plus）及 `backend/`（FastAPI、SQLAlchemy 2.x、Alembic），使用 npm 锁文件和 uv 锁文件、项目 `.venv`。配置示例不含真实凭证；数据库地址缺省为空。启动说明见 [README](../../README.md)。

以下保留骨架阶段检查快照，不代表 I1 完成后的当前状态。

Alembic 配置、revision 模板及 `migrations/versions/` 路径已建立，无 revision、业务表或数据库；未运行迁移。MySQL 8.4 / InnoDB 边界保持不变，未引入 SQLite。未批量建立业务模块占位目录。

本次基本检查：前端 `npm run typecheck` 和 `npm run build` 通过；回环地址开发服务器首页及编译后的入口/组件 HTTP 200。后端无数据库配置启动成功，`/health` 返回 HTTP 200 与 `{"status":"ok"}`；示例配置读取及环境变量覆盖检查通过。`alembic heads` 成功且无 revision 输出，不代表迁移执行已验证。两个临时应用进程均已停止。

当前无可用浏览器连接，未进行实际点击及视觉检查；没有业务、真实 AI、权限、数据库或产品 Word 导出验收。依赖安装仅在项目目录，前端因现有代理 503 对安装进程使用官方仓库直连，未修改全局配置。未读取密钥、旧系统源码、历史记忆或旧会话，未连接服务器、提交或推送 Git。

### 当前成果：I1 已实现与真实 MySQL 验证

基线为 `main` / `5efe5d3`。I1 已交付注册、登录退出、本人姓名和密码设置、待分配限制、管理员教师列表与密码重置、服务器管理员恢复命令。真实 MySQL 8.4 / InnoDB 的 24 项通过，加强证据后定向 5 项通过，其余结果复用，具体事实以 [I1 验证记录](i1-mysql-validation.md) 为准。浏览器密码变更提交和真实人工 CLI 输入尚未验证；不能写成完整端到端已通过。上面的骨架和原型记录保留各自历史范围，不改写为后续检查结果。

### 当前成果：I2 已实现与真实 MySQL 验证

I2 已交付园所配置、班级创建与维护、教师首次真实分配、学期创建、持久有效日历、管理员例外/重新导入、配置变更预览与确认、阶段门槛 `plans_started_at` 及教师只读上下文。真实 MySQL 8.4 / InnoDB 集成测试 56 项通过，无跳过；前端 `npm run typecheck` 与 `npm run build` 通过；main 浏览器验证通过。具体事实、命令、环境及限制以 [I2 实施与验证记录](i2-implementation-status.md) 为准。

### 当前成果：I3 手工日计划保存（已完成）

[I3 手工日计划保存实施规格](../specs/manual-daily-plan-save.md) 已由二次修订草案转为已确认实施规格。原先阻塞开工的三项范围决定已于 2026-09-23 由用户确认：

1. **周计划同步范围：选项 A** —— I3 最小扩入真实 `weekly_plan_sync_states`（待确认投影），保存响应/只读接口可立即消费；不扩入完整编辑确认、AI、导出或工作进程。历史讨论中的选项 B（不开放保存入口）在空表时没有独立产品价值，未采纳；规格保留原二选一论述供追溯。
2. **历史表头规则：选项 A** —— 创建日计划时不可变快照 `school_name`/`class_name`/`grade`/`creator_display_name`；读取时按快照而非当前班级资料。
3. **删除/恢复：选项 B** —— 本次延后，I3 不暴露 DELETE/recover/已删除列表入口；schema 兼容 `deleted_at`/`deleted_by` 软删除字段。

**当前状态：I3 代码实现（含 schema/迁移）已获授权。第一片“数据与事务核心”（规格切片 1 Schema 与迁移 + 切片 2 服务与事务核心）已由 OpenCode 完成并经 main 定点修复，48 项 I3 纯单元测试通过；第二片“API 与权限”（规格切片 3，日计划五条路由、周计划同步只读路由、extra=forbid schema、按请求后端重判权限与错误映射、创建/保存响应携带当前周同步摘要）已由 OpenCode 实施并通过定向纯路由/序列化/权限单元测试（mock service/依赖，不连接数据库）；第三片“前端闭环”（规格切片 4，教师日历 date_eligible 打开入口、先查后明确创建、完整手工表单、创建者/管理员可编辑与同班只读、周计划同步摘要、409 冲突保留本地与双路径处理、中文错误提示、管理员最小日计划入口）已由 OpenCode 实施，前端 `npm run typecheck` 与 `npm run build` 通过，仓库无现有前端测试设施故未新增前端测试且未安装新依赖。**

**切片 5 真实 MySQL 集成验证已于 2026-09-23 由 OpenCode 在授权边界内完成（详见 [I3 规格](../specs/manual-daily-plan-save.md) 第 10/11 节）**：

- 环境：一次性 Docker 容器 `kg-next-i3-mysql-20260923`，镜像 `mysql:8.4.11`，仅 `127.0.0.1:13384`；`SELECT VERSION()` 为 8.4.11，`default_storage_engine=InnoDB`；仅库 `kindergarten_test_i3_fresh`（utf8mb4 / utf8mb4_unicode_ci）。未读 `.env`，未碰 I1/I2/共享/生产库。
- 命令类别：`APP_DISABLE_DOTENV=1` + 显式本地 I3 DSN 的 `alembic upgrade head`；`APP_DISABLE_DOTENV=1 I3_TEST_ALLOW_DESTRUCTIVE=yes I3_TEST_DATABASE_URL=…` 下 `unittest tests.integration.test_i3_daily_plan -v`；测试后 `DROP/CREATE` 该库并再次 `upgrade head`。未装依赖、未启 API/Vite/浏览器、未 git 操作。
- 结果：迁移 head = `20260923_i3_daily_plans`；集成测试 **27 项实际运行 / 通过 27 / 失败 0 / 错误 0 / skip 0**（原命令退出码 0），含 V9 重启持久性与 §8.4 两种锁序。定向复核：I3 纯单元 132 项通过；I3 集成文件 `py_compile` 通过；`alembic heads`/`current` 一致；`git diff --check` 与 untracked 尾随空白检查通过。前端本轮未改，typecheck/build 复用已通过结果。
- 定点修复文件（仅 I3 测试/guard）：`backend/tests/integration/test_i3_daily_plan.py`（guard 导入顺序、种子循环外键、JSON null 与 SQL NULL 区分、V8 注入语句与异常类型）、`backend/tests/integration/i3_guard.py`（DSN 回填）。未改 ARCHITECTURE.md，未放宽断言。
- **集成后已重建干净 `kindergarten_test_i3_fresh` 并 upgrade head（核心业务表空、head 正确），容器保持运行，供 main 启动 API/Vite 做浏览器验证。该集成步骤完成时尚未执行浏览器验证；main 浏览器验证随后已完成，见下一小节补记。**

**main 浏览器验证补记（2026-09-23，本地隔离 MySQL 8.4.11，详见 [I3 规格](../specs/manual-daily-plan-save.md) 第 10/11 节）**：

- UI 建立 2026-09 学期日历；教师 2026-09-23 创建空计划 v1 并显示 `pending_projection`。
- 完整代表性栏目保存 v2，刷新重开全部持久。
- 外部会话更新 v3 后浏览器旧 v2 保存真实触发 409：本地输入保留且展示服务端内容，显式重提交至 v4。
- 同班非创建者打开为全字段 disabled、无保存/删除入口。
- 浏览器未发现新缺陷。集成测试结束时曾保留一次性容器 `kg-next-i3-mysql-20260923` 供 main 浏览器验证，此为历史事实；main 完成浏览器验证并停止 API/Vite 后，该容器已删除，容器内测试数据不可恢复。保留上述历史验证范围；不写账号密码、DSN/cookie/容器密码。

### 下一项：I4 手工周计划创建、编辑与确认（四片已实施并完成第四片真实验证）

[I4 手工周计划创建、编辑与确认实施规格](../specs/manual-weekly-plan-confirmation.md) 已覆盖领域模型与 schema、I3 `weekly_plan_sync_states` 投影消费契约、数据约束与迁移、API 与权限矩阵、事务与锁协议、来源变化与确认协议、前端闭环、验证矩阵与实施切片。

**2026-09-23 用户确认五项产品决定，I4 规格在本范围内已确认（见规格 §1.5 决策记录）**：

1. **U1=A**：周计划表头创建时不可变快照（园所、班级、年级、教师名单、保育员）。
2. **U2=B**：主题在创建／保存／确认均允许为空，确认时记入 `facts.missing`。
3. **U3=A**：不完整／未更新确认以系统生成的缺失与陈旧事实加显式 ack 为准，`note` 可选。
4. **U4**：确认前来源变化保留显式刷新与确认当前未更新两条路径，按规格既定审计字段与 UI 行为执行。
5. **U5=A**：`source_kind` 判别字段；手工补充使用服务端生成的稳定 `manual_item_id`，日计划引用字段为 null。

**I4 实施状态（2026-09-23 更新）**：第一片（三表模型与迁移、创建／打开／PATCH／refresh／confirm 事务与锁、事实重算）、第二片（8 条路由、`extra="forbid"` schema、错误映射、`source_candidates`）、第三片（§8 前端闭环，`npm run typecheck` 与 `npm run build` 通过）与第四片（隔离真实验证）均按第 10 节逐片授权完成。第四片实际结果：隔离一次性 MySQL 8.4 / InnoDB 容器与白名单库（`kg-next-i4-mysql-*`，仅 `127.0.0.1` 高位端口，独立 `i4_guard`）；空库与带 I1/I2/I3 行的库均 `alembic upgrade head` 成功，`heads == current == 20260924_i4_weekly_plans`；`tests.integration.test_i4_*` 52 项实际运行 **0 failure / 0 error / 0 skip**（V1–V14 全覆盖，含真实 SIGNAL 触发器回滚、真实线程并发与 FOR UPDATE 锁序、dispose 后重建 engine 的重启持久性）；I4 单测 186 项、I3 单测 132 项回归通过；真实浏览器（系统已装 Chrome + CDP，未新增依赖）按 §8 与 R1/R2/R3 走通并记录 54 项通过；临时 uvicorn／Vite 已停止、I4 容器已删除。验收期间发现并按最小范围修复两处前端缺陷（409 `CONFIRM_ACK_REQUIRED` 后重开确认弹窗丢失最新 facts；确认历史乱序响应覆盖新历史），均只改 `WeeklyPlanView.vue`、不改 API／权限／锁协议／U1–U5，并以同一浏览器套件复跑通过。仓库无前端测试设施，故回归以该浏览器套件与 `typecheck`/`build` 承担。部署与后续切片仍未授权。

**第四片验收后的定向修复（2026-09-24）**：第四片最终验收复跑发现并修复“确认成功后自动刷新导致 dirty 输入被静默重基到更新草稿”的并发缺陷（post-confirm dirty rebase race）。仅改 `frontend/src/views/WeeklyPlanView.vue`：区分服务器展示版本与 dirty 输入实际基于的 draft version；确认后状态读取发现版本推进且存在 dirty 输入时进入显式冲突处理，不再自动重基。定向回归 Race-R2、R1、R2、R3（仅验证）、OBS-1、OBS-2 共 12 项检查通过，`npm run typecheck` 与 `npm run build` 通过；后端 0 修改，故未重跑真实 MySQL V1–V14 与浏览器套件。规格与本节为最小补充，规格条款未改。

**I4 最终窄修复（2026-09-24，见规格 §12.2）**：上述修复复审后确认“确认冲突复核”仍会把 dirty 输入的保存基线隐式重基到服务端新版本（绕过保存侧 409），且用户无法查看确认目标在重叠 dirty 字段上的已保存内容。最终窄修复仍仅改 `frontend/src/views/WeeklyPlanView.vue`，引入独立 confirmation target（版本 + 内容快照）与 `editBaseVersion` 分离：确认冲突复核只推进确认目标与展示、不重基编辑基线；确认目标推进到新版本不绕过保存侧版本冲突；确认对话框在存在本地未保存修改时预览确认目标真实内容并声明其不参与确认；ack/note/无自动请求/`CONFIRM_ACK_REQUIRED` 语义不变，R1/R2/Race-R2/R3/OBS-1/OBS-2 不回归。实际执行：新增 A–D 脚本级状态机 43 项通过，复跑既有 12 项与详细 75 项通过，`npm run typecheck` 与 `npm run build` 通过，定向真实浏览器 A+B 18 项通过（一次性隔离 MySQL 8.4.11 / InnoDB、`127.0.0.1:13385`、白名单库、现有 guard、不读 `.env`，Chrome + CDP 无新依赖，结束已停止服务并删除容器）；§8 54 项浏览器矩阵与 MySQL V1–V14 未重跑——后端 0 修改且未触及它们覆盖的服务、锁与 API 层。后端无修改，未提交、未推送；I4 不需要新一轮全面验收。

**I4 复审后的两处窄修复（F1/F2，2026-09-24，见规格 §12.3）**：§12.2 修复的复审又发现两处残留——确认冲突复核取消后，普通“刷新到最新来源”成功仍会无条件把 dirty 输入的保存基线推进到刷新后的新版本（刷新只按请求版本校验、不提交本地输入，成功不代表旧编辑冲突已解决），本地旧输入随后可无 409 覆盖他人编辑；确认目标预览对户外游戏/重点区域只显示名称，重叠 dirty 字段的真实已保存文本与来源区别不可见。窄修复仅改 `frontend/src/views/WeeklyPlanView.vue` 与 `frontend/src/weekly-plan-content.ts`（新增 `outdoorSlotSnapshotPreview`/`focusAreaSnapshotPreview` 两个纯展示 helper）：刷新成功后仅在无 dirty 或同基线时推进 `editBaseVersion`，否则保留真实基线并进入既有显式冲突处理（新 reason `refresh_kept_baseline`，两种处理方式不变），同基线/无 dirty 刷新不受影响；确认预览改为读取 `confirmTarget.content` 渲染游戏名称/来源类型/共用目标/指导要点/重点指导与重点区域名称/上下文/目标/指导/支持策略，空值显示“（空）”，来源行含可靠映射日期（映射不上省略、不虚构）+内容版本+来源标识，快照不被最新来源替换。实际执行：F1 脚本级回归 29 项通过（同一断言在修复前组件上 11 项失败，确认非空转）、F2 helper 夹具与模板结构 22 项通过、F2 真实模板编译渲染至 vnode 文本层 18 项通过（已安装 vue/compiler-sfc + vue 运行时，无服务/浏览器/新依赖）、`npm run typecheck` 与 `npm run build` 通过。未执行真实浏览器 DOM/交互验证（留给 main 定向验证），§8 54 项矩阵与 MySQL V1–V14 未重跑（后端 0 修改）。后端、schema、迁移、API、权限、锁协议、U1–U5 均 0 修改，未提交、未推送。

后续逐步交付周计划确认、导出、个人 AI、提示词、持久任务执行与交接恢复。AI、个人提示词与持久任务继续属于首版。

### 下一项：I5 Word 导出（片 1–3 已实施，片 4 已授权、待 Windows／WSL2 环境迁移后执行）

**2026-09-25 规格准备历史状态**：[I5 Word 导出实施规格](../specs/word-export-implementation.md) 基于既有 Contract、最小实施规格、Word 验证计划/原型结果与 I3/I4 读取面，收敛了 API、映射、生成、下载、错误、审计与分层验证边界，并给出四片实施切片。该日仅完成规格、不构成实现授权；后续实际状态以下列片 1/片 2 段落为准。

**2026-09-25 定向修订（规格层面，未实施）**：修正 `no_plan` 清空已确认人工内容、跨学期周号排序/去重、服务端“未包含最新变化”判定与提示承载三处缺陷。**2026-09-25 用户已决定两项片 1 依赖语义**：§11.7 零上课日周取方案①（仍可单份导出，表头=学期∩该周区间、整周注明假期、范围模式不选中）、§11.8 缺项确认取方案 B（确认绑定首次 409 已展示的版本/事实，变化则再次 409；服务端重算 facts、不信任客户端 facts）；确认后日历变化的导出布局 §11.9 仍待用户决定（当前 `plans_started_at` 门槛下不可发生，不阻塞片 1–4）。

**I5 片 1 实施状态（2026-09-25 至 2026-09-28）**：读取/映射纯逻辑、R1–R3 与完整 facts/I1 回归收敛均已完成；2026-09-28 main 独立复验后端单测 425 项、I1/I2/I3/I4 MySQL 24/56/27/52 项及前端 typecheck/build 全部通过。

**I5 片 2 准备状态（2026-09-28）**：用户授权进入“固定模板 docx 生成”，确认内存生成不落盘、ZIP + lxml 定点修改 OOXML并允许新增锁定依赖、两份模板副本入库。资产位于 `backend/app/assets/word_templates/`；日模板哈希与旧验证记录一致，当前周模板为用户本次提供的新字节版本，须在片 2 重新建立结构机检基线，旧周模板原型证据不直接外推。

**I5 片 2 实施状态（2026-09-28）**：已按授权实施纯生成层——新增 `backend/app/services/word_export_docx.py`（受控模板 ZIP + view model → 完整 docx bytes，只修改 `word/document.xml`、其余 ZIP member 逐字节保留，模板 SHA-256 校验）与 `backend/tests/unit/test_i5_word_export_docx.py`（24 项结构机检通过；全量后端单测 449 项通过）。依赖 `lxml>=6.1,<7` 锁定为 6.1.3；资产 `daily_plan.docx` SHA-256 `99008f92…`、`weekly_plan.docx` SHA-256 `24ccaa9e…`（当前周模板新字节版本已建立结构基线：5 张表、9 行块、合并跨度 `[1,1,5]`/`[1,6]`）。日/周计划覆盖范围见[规格 §12 片 2 实施状态](../specs/word-export-implementation.md)。**截至该次交付未执行**：LibreOffice/Microsoft Word 渲染、API/权限/下载、MySQL/浏览器；当时片 3/4 尚未授权，后续状态见下文。

**I5 片 2 审阅后窄修复（2026-09-28，F1–F3）**：审阅基线 `a9db25f` 上的三处已复现缺陷已最小修复——F1 合并日计划每份输出自身完整计划块（标题/副标题/表格）；F2 周计划班级表头补输出创建时快照 `grade`（与 `class_name` 空格连接、空值过滤）；F3 日计划反思右侧单元格只写 `reflection` 值、不重复模板左侧固定栏目名。修复未改片 1 映射语义、模板资产/哈希、依赖、数据库或迁移。实际执行：定向结构机检 28 项通过（原 24 项 + 本轮新增/加强 4 项断言，其中新增/加强的 5 项断言在修复前基线 `a9db25f` 生成器上 5 失败、确认非空转）；全量后端纯单元测试 453 项通过；`uv sync --locked` 与 `git diff --check` 通过。**截至该次交付未执行**：LibreOffice/Microsoft Word 渲染、API/权限/下载、MySQL/浏览器；当时片 3/4 尚未授权，§11.1、§11.5、§11.6 尚待确认。后续状态见下文；§11.9 仍按其时点待定。

**I5 片 3 实施状态（2026-09-29）**：用户确认三项片 3 前决定（§11.1 取②日 ≤31/周 ≤8 按实选份数、§11.5 取 A 记成功导出 `operation_records` class 级 `export_word`、§11.6 取①同步内存下载）并授权实施片 3。已落地：`routers/exports.py` 两条路由 + `class_scope.py` 唯一共享角色判断（I3/I4 行为不变、导出 body 按 `model_fields_set` 存在语义）+ `DailyExportIn`/`WeeklyExportIn` 严格 schema（extra=forbid 双模式互斥）+ 片 1 `prepare_daily_export()` 消费的 409 facts/expected_context/reason 闭环 + §8 全表错误映射（含 503 `EXPORT_UNAVAILABLE`/`SERVICE_UNAVAILABLE`、500 `EXPORT_FAILED`）+ 完整生成→审计→提交→响应顺序与 RFC 5987 文件名、`X-Export-Warnings` 警示头；前端 `api.ts` 二进制下载 helper 保留 409 所需字段并新增 `word-export.ts`（错误/警示文案与一次性 object URL 下载），`DailyPlanView`（日/周/月/自选范围 + 缺项确认 + “无拆分基准”提示）、`WeeklyPlanView`（当前确认版本 + 确认历史显式版本导出 + `confirmed_not_latest` 提示）、`WeeklyPlanListView` 范围合并导出，管理员复用入口自动携带显式 `class_id`。实际执行：定向 I5 单测 170 项、全量后端单测 533 项通过；I5 集成 30 项通过 0 skip（专用 guard 端口 13386 白名单库 `kindergarten_test_i5`，head `20260924_i4_weekly_plans`，含真实现场并发提交下文件=钉住版本、成功恰一条审计且业务表零写入、31/32 与 8/9 实选上限、ZIP 合法性字节级检查）；`npm run typecheck`/`build` 通过（主包 1.13 MB 既有非阻断告警）。模板资产、片 1/2 语义、依赖、数据库 schema/迁移零修改。一次性容器 `kg-next-i5-mysql-20260929` 及其数据卷在验证后已停止并删除（只读验证数据不可恢复，符合一次性隔离要求）。**未执行**：Windows／WSL2／Microsoft Word 与真实浏览器片 4 验收，未声称通过；片 4 现已授权，待环境迁移完成后执行。

**I5 片 4 环境与授权更新（2026-09-29）**：用户已授权进入片 4，并把开发／验收环境改为 Windows 11 Pro + WSL2 Ubuntu + Office 365／Microsoft 365 随附的 Windows 桌面版 Microsoft Word。片 4 待环境迁移完成后执行：WSL2 内启动一次性 MySQL、API、Vite 和自动测试，Windows 浏览器完成真实下载，Windows Word 完成 W1–W6 无修复提示、逐页内容／分页／表格／字体／红字／五至七列版式检查。旧 Omarchy 或 Ubuntu／LibreOffice 结果只能单列为历史／补充证据，不得代替 Word 门槛；Office 其他应用、实体打印、部署仍不在本片范围。

### OpenCode 执行安排

2026-09-22 用户已确认 pi 套餐到期并要求不再切回 pi。未来本项目业务代码（含 I3 及后续切片）由本地 OpenCode 唯一写入；main 负责协调、规格审阅、产品问题汇总、授权边界、资源准备、浏览器验证及记录整合。main 不并行安排其他业务代码执行者，不另起业务实现。2026-09-23 用户确认 I3 三项范围决定，并按推荐项授权在整个已确定边界内实施 I3；main 按切片组织交付（第一片“数据与事务核心”、第二片“API 与权限”），均由 OpenCode 唯一写入、main 只读审查，未对单个切片另行单独授权；本轮不执行数据库、迁移、依赖安装，不自动开始前端切片。其后用户按推荐项授权整个已确定边界内 I3（含前端闭环切片），第三片“前端闭环”已由 OpenCode 实施。切片 5 真实 MySQL 集成验证已按用户授权由 OpenCode 完成（27 项 / 0 skip）；浏览器验证仍归 main，本任务（OpenCode 切片 5）停止于集成与文档更新，不启动 API/Vite/浏览器——此为该切片结束时的历史范围，非待执行事项；后续 main 已启动本地 API/Vite 并完成浏览器验证，结果见上文“main 浏览器验证补记”；main 随后停止 API/Vite 并删除一次性容器 `kg-next-i3-mysql-20260923`，容器内测试数据不可恢复（集成测试结束时保留该容器供 main 浏览器验证为历史事实）。
