# 一对一倾听 L1–L4 核查

2026-11-07，L1 已通过限定源码／合成资料技术核查，直接接续 L2；L2–L4 尚未通过，教师验收统一在四段接通后进行。唯一执行入口为[当前任务](../tasks/current.md)，产品及工程范围分别见[产品规格](../specs/desktop-one-to-one-listening.md)和[工程设计](../specs/desktop-one-to-one-listening-engineering.md)。

## 开工身份与责任

- 分支 `codex/desktop-one-to-one-listening`，HEAD `a160b321ddbe1d101f42109c3f40a2f47e97eaa4`。开工暂存区为空，工作区已有 `AGENTS.md`、两份倾听规格及 `docs/tasks/current.md` 改动，全部保留。
- 原生 OpenCode 会话已由本机 CLI API 核实为空闲、succeeded，代理 build，`opencode-go/deepseek-v4.1-flash#max`。会话标识留在私有证据中。OpenCode 独占实现、迁移、模板和测试；Codex 独占正式规格、审核记录及独立验证。本轮用户同时允许调用 Command Go。不 fork、不另派子代理。
- 本机原 Command Go 会话 `8cf528de-8773-4a06-9cc5-31e96fab515f` 的 transcript 首行 id／cwd、末次 assistant 的 `deepseek/deepseek-v4.1-flash`／max 已核实，派发前无 Command Code 在途 node 进程。以同一模型／effort、只读 plan 权限交叉审阅 L1 备份归属及兼容方案，只有读取责任，不写计划、实现或文档，不运行测试、应用或 Git。没有使用 fork、tools-all、自动更新或放宽权限；受拒读取不得绕过。反馈不替代最终字节及 Codex 独立验证，日志在私有 `commandgo-l1-review.*`。
- 实际运行 `desktop/.venv-d1/Scripts/python.exe` 为 CPython 3.14.10、Windows x64、标准 GIL，Pillow 13.0.0、SQLAlchemy 2.0.54；沿用该锁定环境，不安装或升级。两个 venv 的 `pyvenv.cfg` 旧 3.14.7 标记与实际二进制身份分开。Alembic 实际 `heads` 为 `20261102_0008_local_weekly_ai`。
- 私有证据根 `C:/kgm-lsn-1107`。开工 Git 状态、既有文档 diff、跟踪文件散列已留存。15 份空表源已定位为小／中／大班各五份上学期空表；原件只读。教师已验收的两份常规字重样稿仍在私有原目录，不覆盖。
- codebase-memory 索引代次 `2026-11-06T23:19:27Z`。本轮相关路径覆盖结果均为 `metadata_changed`，图谱用于定位，材料依赖回读实际源码。

## 本轮追加授权与配置核查

教师明确授权连续实施 L1–L4、必要付费 AI 验证及从指定“游戏计划书”目录取照片副本。该目录有 34 张 JPG、2 个 PDF；照片只进入私有合成资料及授权应用 AI 验证，不进入仓库或公开夹具。Windows 便携包全程排除，不构建、下载、解压或启动冻结 helper，不触发打包 CI，也不列入本轮验收条件。

历史记录指出的本机 DeepSeek 标准 API 配置仍存在。通过只读 SQLite 连接及既有 `get_config` 服务核实：`https://api.deepseek.com`、`deepseek-flash`、`chat_completions_v1`、配置版本 1，`has_secret/configured/ready` 均为 true。不回显或导出明文密钥，原数据库／WAL／SHM／DPAPI 共四个文件核查前后散列保持。配置就绪不等于本轮已经完成网络请求或视觉实测。该持久源保留；L4 的独立资料及配置接续结果后补。

首个配置探针错误地对 dataclass 调用 `model_dump`，在取得只读配置后报 `AttributeError`；改用其公开 `to_dict` 读取成功。此为验证调用错误，未改产品或配置，不记为产品通过或失败。证据见私有 `ai-config-readonly.json`。

## L1

原会话只读核对后，Codex 已核定本片文件及技术方案并派发实施；尚未放行 L1。当前重点是新增倾听归属、三个稳定图文位置、修订回执与完整备份资源兼容。15 份原空表 ZIP 关系检查无外链，源文件及 `word/document.xml` 散列记录在私有 `template-source-before.json`。两份已通过样稿的 SHA-256 与规格相同。

本片以下文件的唯一写入者为原 OpenCode 会话，Codex 不写业务实现／测试。实施请求与实际 CLI 日志在私有 `l1-implementation-request.md`、`opencode-l1-r01.*`，没有扩大到 L2 页面、L3 Word 或 L4 AI。倾听 manifest 联合类型、物理资产位置、日期文本及部分 patch 的核定已归[工程规格](../specs/desktop-one-to-one-listening-engineering.md#2026-11-07-l1-实施核定)。

```text
backend/app/local/models.py
backend/app/local/schemas.py
backend/app/local/app.py
backend/app/local/backup_validate.py
backend/app/local/backup_snapshot.py
backend/app/local/restore_service.py
backend/migrations_local/versions/20261107_0009_local_listening.py
backend/app/local/listening_templates.py
backend/app/local/listening_service.py
backend/app/local/listening_assets.py
backend/app/local/listening_api.py
backend/app/assets/listening_templates/README.md
backend/app/assets/listening_templates/manifest.json
backend/app/assets/listening_templates/v1/small_health.docx
backend/app/assets/listening_templates/v1/small_language.docx
backend/app/assets/listening_templates/v1/small_social.docx
backend/app/assets/listening_templates/v1/small_science.docx
backend/app/assets/listening_templates/v1/small_art.docx
backend/app/assets/listening_templates/v1/middle_health.docx
backend/app/assets/listening_templates/v1/middle_language.docx
backend/app/assets/listening_templates/v1/middle_social.docx
backend/app/assets/listening_templates/v1/middle_science.docx
backend/app/assets/listening_templates/v1/middle_art.docx
backend/app/assets/listening_templates/v1/large_health.docx
backend/app/assets/listening_templates/v1/large_language.docx
backend/app/assets/listening_templates/v1/large_social.docx
backend/app/assets/listening_templates/v1/large_science.docx
backend/app/assets/listening_templates/v1/large_art.docx
backend/tests/local/test_listening_templates.py
backend/tests/local/test_listening_migration.py
backend/tests/local/test_listening_service.py
backend/tests/local/test_listening_assets.py
backend/tests/local/test_listening_api.py
backend/tests/local/test_listening_backup.py
backend/tests/local/listening_fixture_support.py
backend/tests/local/test_backup_fixture_support.py
desktop/tests/test_renderer_recovery_verifier.py
```

Codex 开工迁移基线 18 项全部通过，日志 `baseline-migrations-r02.*`；使用新短临时根、禁 dotenv／pyc、SQLAlchemy 纯 Python和 Python socket loopback 守卫。首次选用精简 backend venv，因缺 Pillow 导入失败，日志 `baseline-migrations.*` 保留；其后确认并改用项目既有 desktop venv。附加环境探针曾导入项目不使用的 `docx` 包而报缺包，移除该无关导入后身份核实成功，未安装依赖。以上均不替代 L1 改动后的验证。实现、自测及 Codex 独立核查结果后补。

实施中模板初核（不是最终停写字节）：15 份副本的 `word/document.xml` 与原件逐份一致，manifest 散列匹配；352 条评价要求／逐档标准逐格精确匹配。层级标签的原单元格分行在 manifest 中合并，忽略分行空白后均匹配；首个探针把这类标签差异误计为“标准不匹配”，原结果保留为 `codex-template-provisional.json`，分开核对后的结果为 `codex-template-provisional-r02.json`。其余版式部件原字节保持；改变部件仅 `[Content_Types].xml`、`_rels/.rels`、`docProps/core.xml`，移除 `docProps/custom.xml`；未发现剩余 creator／lastModifiedBy／Company／Manager／HyperlinkBase 属性或外链。详见私有 `codex-template-parts-provisional.json`，交付后仍须核对最终散列。

Command Go 只读交叉审阅 exit0，原 session／模型／max 不变，无 hash/Git 权限时未绕过。其读取时新文件尚未出现，因此列出的资源枚举、manifest 四处接入、新表逻辑校验、路径归属、旧 0008 备份、图片元数据与模板身份均是本片验收门槛，不作为已完成代码的缺陷或通过结论。相关门槛已包含在核定实施请求；最终停写源码仍由 Codex 独立核查。

### R01 文件屏障首次失败

实现中 Codex 从另一份新合成资料经真实 loopback HTTP 完成了两名同名记录、每人五表的创建、同请求创建／保存重试、五领域部分保存、他人资料保持、遗漏栏目／空星级保持。此为阶段探针，不是 L1 整体通过。

随后取得同根备份独占 lease，向第一领域第一组上传 137×89 合成 JPEG。返回 HTTP409 `LOCAL_BACKUP_BUSY`，但受管资源清单已从空变为有新图；数据库修订仍为 7。源码 `listening_assets.import_group_photo` 未取得覆盖 staging、发布及登记全过程的 `backup_barrier.file_scope`；底层观察图片 I/O helper 不会自动取得此屏障。**L1 暂不放行，须原实现者回修。** 首失败根 `C:/kgm-lsn-1107/codex-l1-provisional-api`、`report.json` 及同前缀 stdout／stderr／exit 保留，不能以拒绝响应代替零文件写入。读取时 assets／api／backup_validate 散列及待核回执逻辑问题保存在私有 `codex-l1-provisional-findings.md`。

已通过本机 CLI 所给 OpenAPI 核实 `session.prompt` 的持久 steer 及 `resume=false` 语义，向原会话投递 R01 和回执校验待核项，receipt `msg_1b349244f001lh5HVglkib2Agp`，CLI exit0。没有另起 agent loop 或实现者；投递回执不等于修复通过。实现中的最新 assistant 元数据另核实为原会话 build／`opencode-go/deepseek-v4.1-flash#max`。私有 active server 需要密码，未读取或绕过其认证；使用已有 CLI 的独立持久投递能力。

### R01 修补后独立探针及回执负例

原实现者已加入覆盖完整导入操作的 `backup_barrier.file_scope`。Codex 新根 `codex-l1-barrier-clean-r03` 的真实 HTTP 探针 exit0：备份独占期间返回409，文件和目录清单均零变化；释放后同请求可导入，同请求再次提交回执完全相同，修订2、屏障活动计数回到 `(0,0)`。这是 R01 对应分支的修补后证据，L1 整体仍待全部门槛及停写字节核查。

倾听操作回执逻辑校验也已接入。Codex 在合成数据库副本中把一次创建回执的 `result_json.record_id` 改成另一个同名记录的标识，当前 `validate_database` 以 `BACKUP_DB_LOGICAL_INVALID` 拒绝，独立 `codex-l1-receipt-check.*` exit0。前两次组合探针分别因把 `active_counts` 属性当函数、未建立 canonical scratch 父目录而中止，日志和各自根保持；这些是验证装配错误，不能写成产品失败或整组通过。

### 0008 升级与旧备份阶段核对

Codex 以开工提交 `a160b321` 的 229 份只读源码／资源副本，在另一份合成根用旧 `LocalRuntime`、既有业务夹具及旧 `SnapshotService` 实际生成 0008 备份。该源码副本无 EXE、DLL、业务数据库或凭据；实际 Python 及依赖仍用既有 desktop venv。源身份在私有 `old-source-identity.json`。旧备份 `de9effcf458169fb7a8a660b36f6df89255bf576b0bafa6075f993ea53277439`，1,613,816 字节，49 张业务表、12 个资源。

- 独立 SQLite 一致性副本经当前 `LocalRuntime.prepare` 冷升级至0009／55表，原49表的 schema、字段和行指纹全部一致，六张倾听表均为空；原源库和旧备份散列保持。首次探针忘记显式关闭 SQLite backup 连接，产品正确拒绝“数据库被占用”；新根关闭连接后重跑 exit0，`codex-old-upgrade-r01/r02` 均保留。
- 另一新根通过当前 `RestoreCore.preview/prepare/install/reopen` 恢复该旧备份，hooks 实际停止原 loopback 服务线程，再启动新服务读取；原49表逐字段无差异、12资源指纹完全一致、倾听列表为空。退出后另启新源码进程及新 loopback 服务冷开，仍为0009且空倾听列表。源库、旧备份与合成 DPAPI 散列保持；`codex-old-restore-r01` exit0。

以上为实施中实际字节的阶段结果，停写交付仍按最终改动核查，不外推 L2 页面、L3 Word 或 L4 AI。已用第二条持久 steer `msg_1b351fb9d001RJ1aijkndRRbas` 告知原实现者这些事实，并要求后续测试直接使用新唯一根，现有失败根保持，不再先递归删除固定临时目录。

### 第一轮停写交付与独立完整联测

原会话第一轮 CLI exit0，最新 assistant 为原会话 build／Flash max、`finish=stop`，明确停止写入。私有交付 `opencode/l1_evidence.md` 记录新增 L1 32 项、合并迁移／夹具 54 项、观察／恢复 174 项、D2 schema 17 项及受影响 desktop verifier 单项通过；也保留了白名单外旧测试迁移头常量失败，未冒称全套通过。

Codex 独立完整资料根 `codex-l1-full-http-r02` exit0：通过真实 HTTP 保存两名同名幼儿各五个领域、30个稳定图文位置、全部表头／倾听／评价／策略与可空星级；使用30张不同的合成照片，换序后图、日期、文字仍跟随稳定组，替换后原图仍可读取，共31张倾听资源。创建／保存／导入／换序／更名的同请求重试、同键异内容、旧修订、非法／布尔星级、跨记录组／读图及第四组均按实际 API 拒绝或复用回执。更名后恢复同名，仍是两条独立记录。

完整备份同时含31个倾听和12个旧观察资源；新旧 manifest 身份字段分别核对。恢复到另一新根，实际停止并重开 loopback 服务后，55表的规范化字段指纹、43个资源指纹、两套记录 DTO、31张图片字节均一致。再由新源码进程冷开，2记录／10领域／58评价项／30组／31资源／46回执全部读回；空值、模板版本及照片散列保持。源合成根散列保持。备份 SHA-256 `7c80ea17ac364134cbd356091565f20b8e3b33d817c7002d6ef36902c3705282`。

首次完整探针 `r01` 读取图片时沿用计划中的路由、漏了实际 API 的 `/content` 后缀而中止；其数据库、31张已登记图及日志保留。r02 在一致性副本中按实际 API 复核所有原始像素字节和填写控制值并继续完成恢复／冷开，未覆盖首失败。之后 API 的改动仅为 multipart 过大错误保持正确错误类型，独立最终 API 套件覆盖该分支。

Codex 独立六个新模块、旧迁移、备份夹具、D2 schema 和受影响 desktop verifier 共72项 pytest 全部通过（65.27秒）。收尾报告误把 `NetworkGuard.attempts` 等方法当属性序列化，harness exit1；首日志 `codex-L1-suite-r01.*` 保留，不能将其写成整组 exit0。R03修复后用正确收尾重跑最终独立套件。

### 旧测试责任补充

Codex 回读失败点后，核定以下六份测试由原 OpenCode 唯一写入，修正“当前 head”断言为实际迁移头；旧库身份、字段／资源／失败保护断言保留。`test_weekly_ai_migration.py` 原本明示0007→0008专项，升级目标固定0008，保留原48表加单一AI采用表的断言。没有全局替换所有0008常量，也不修改便携包／构建链旧测试。派发为 `l1-legacy-test-repair-request.md`、`opencode-l1-r02.*`。

```text
backend/tests/local/test_backup_snapshot.py
backend/tests/local/test_weekly_ai_backup.py
backend/tests/local/test_observation_migration.py
backend/tests/local/test_weekly_plan_backup.py
backend/tests/local/test_weekly_plan_service.py
backend/tests/local/test_weekly_ai_migration.py
```

### R03 创建回执运行态重放

Command Go 对实际候选代码的第二轮只读审阅未发现正常 L1 写入路径上的 P1，提出三个 P2。Codex 对其中创建回执问题作了真实 HTTP 反例：operation 行归属记录A，`result_json.record_id` 指向同档案另一同名记录B，重放创建请求仍返回 HTTP201和B。原因是 `_replay` 的 create 分支只验证结果记录存在／同档案，没有将其与操作行的记录绑定。首失败 `codex-l1-create-receipt-negative-r01` 及 `report.json` 保留；备份侧已拒绝并不能替代运行态防护。

已通过持久 steer `msg_1b366c7e4001VPEV7XEhZeeIXk` 交回同一实现者，追加唯一写入 `backend/app/local/listening_service.py`、`backend/tests/local/test_listening_service.py`。原实现者修补后停写。Codex 新根 `codex-l1-create-receipt-fix-r03` exit0：创建重放409幂等冲突，回执查询404不返回伪造结果，记录数及修订保持，原首失败根散列保持，网络尝试0。先前r02探针误要求查询也返回409，实际404同样是按合同拒绝，装配错误日志保留。新增升班回归也确认旧 middle 记录仍可读／保存、新记录使用 large 模板。

其余两项由 Codex 按既有合同裁定：年级是建档快照，同班升班后旧资料须继续使用原标准，因此不增加与当前班级年级相等的守卫；失败后未登记材料沿用既有观察资产的保留策略，原关联和字节须保持，不因提交可能结果不明而直接删除新目标，不扩大到孤儿清理或共享 I/O 重构。交叉审阅存在进行中读取身份限制，结论不代签最终字节或教师意见。

### R04 按记录快照取标准

Codex 准备 L2 时发现只读接口缺口，并作真实 API 反例：班级 middle→large 后，旧记录和存储模板仍为 middle，原 `GET /api/listening/templates` 却仅按当前班级返回 large，无法供旧记录编辑器取得原标准。`codex-L1-template-binding-negative-r01` 保留首失败。

核定原实现者只修改 `listening_service.py`、`listening_api.py` 及两个对应测试，给现有模板查询增加可选 `record_id`：绑定时验证档案／班级／学期归属，并按记录的年级、每领域版本／SHA 返回标准；未绑定保持当前班级目录。显式不符或缺失版本拒绝，无 domain 的查询也不再忽略 version。无数据、迁移、记录 DTO 或模板字节改动。

实现者 service/API 13项及 L1 六文件36项通过并停写。Codex 新根 `codex-L1-template-binding-fix-r02` 真实 API exit0：旧记录五领域及单领域仍为 middle v1，hash及逐档原文精确匹配；新记录与未绑定查询为 large；无效记录404，显式版本不符／缺失422；原失败根散列保持，网络尝试0。

### L1 最终结论

**L1 限定技术核查通过，直接进入 L2。** 最终新增 L1 六模块独立36项 exit0，源码／测试字节前后相同；R03后主套件74项与六个修补旧模块91项也各自 exit0，parent／child Python loopback守卫自检通过，实际测试出站尝试0、审计正常。R04只读接口增量后针对全部六个 L1 模块重跑36项，没有无关重复重跑91项。

另有 Codex 独立真实 API、旧源0008备份／冷升级、两名同名幼儿10表30组31图与12旧资源的完整备份恢复及新进程冷开证据；R01/R03/R04首次失败和修补后分支分别保留。最终 `git diff --check` 通过，暂存区为空；分支及 HEAD 仍为开工身份，无提交／推送。原15份空表、授权照片原件、两份已验收常规字重样稿、真实AI配置源四文件均再次核指纹保持，见私有 `L1-protected-originals-final.json`。原会话最终 idle／succeeded、build／Flash max 已核实。

该结论不含 L2 实际手工页面、L3 应用导出／Word页检、L4 候选／付费AI或教师体验；Windows便携包全程排除。

## L2

L1放行后按实际前端源码核定下列唯一 OpenCode 写入责任。Codex继续独占正式文档、独立验证与放行；既有后端／模板／迁移不纳入本片初始写入。允许同一实现者在私有证据根新建源码窗口driver及启动辅助；如发现必须更改其它路径，先由Codex核定。

```text
frontend/src/d1/App.vue
frontend/src/d1/leave.ts
frontend/src/d1/views/WorkbenchView.vue
frontend/package.json
frontend/src/d1/listening.ts
frontend/src/d1/views/ListeningRecordsView.vue
frontend/src/d1/views/ListeningEditorView.vue
frontend/src/d1/d1.listening-core.test.mjs
frontend/src/d1/d1.listening-ui.test.mjs
frontend/src/d1/d1.shell-listening.test.mjs
```

当前正在实施，尚未通过。Codex 对进行中 core 字节独立执行 `setDomain/saveCurrent/reset` 探针，首失败保留在私有 `codex-L2-provisional-core-r01`：等待保存时新输入仍切领域，旧领域有稿而当前 `isDirty=false`；重置后旧保存回执改动修订号；普通保存对 unknown 隐式重发原请求。已通过持久 steer 交同一实现者在原责任内修补，最终字节仍须独立复验。

另回读列表发现创建结果未知后可以经关闭弹窗／换学期／返回丢失原请求，且晚到创建回调缺少捕获的生命周期校验，已交回一并收口。Command Go 此片只读检查前端保存、创建、编辑器归属及迟到响应；其进行中意见不代签最终结果。

Codex 另根 `codex-L2-core-fix-r02` 在修订后 core SHA-256 `825a1ba9f89bc8da9a73bd4f56589da2bfef66b0f70afdd9bfeedb97bc6d13d6` 上独立重放上述三反例，三项断言均通过：保存期间新输入留原表且仍 dirty，reset 后 revision 保持0，普通 unknown 保存仍仅发送1次。源码仍须与最终交付字节比对。实现者另补列表未知结果阻挡／原键查询、组合输入 settle 及变更动作互斥；新9项 core、8项实际SFC、7项应用壳检查和类型检查自测通过。

独立 `codex-L2-final-frontend-r01` 完整 `npm run test:d1` exit0（87.595秒）、typecheck exit0、新唯一目录 Vite源码前端构建 exit0。62份源码／测试／包配置散列在三项检查前后相同。当前构建主 JS SHA-256 `d47b47042e9ef414b1b697ea1b9aed02df764eb5c33ba1c77fd079a8ea3bf22a`；未构建便携包。

独立 `codex-L2-independent-core-r03` exit0，另用五领域假名资料通过8项行为检查：显式空值只清目标／空星不误改；整组换序保留日期、正文和图片；dirty时空文件仍零请求；正文冲突零照片发送；姓名已确认部分不因领域冲突回退；reset中断姓名后的旧保存链、不再向恢复后的根续发领域请求；显式重试原key仅确认原载荷并保留之后新输入；两条同名记录晚到保存仍按id隔离。使用同一最终core散列。

原实现会话随后明确停止写入，实际build／Flash max、idle／succeeded及CLI exit0已核实。交付时重新比对62份文件，独立验证后无变动；HEAD仍为开工身份、index为空。原实现者的私有正常main窗口driver仅完成静态准备、未执行；其报告中的组合输入／动作问题属于源码回读和自动测试范围，不能以未操作的 `codex-L2-ui-r01` 窗口根冒充运行态反例。后续调用该driver须由Codex外层安装parent／child loopback守卫并固定短新根，单靠原driver不具备网络守卫证据。

Codex 正常源码入口窗口已在独立无AI配置的新根 `codex-L2-ui-r01` 启动；使用实际参数 `--data`（先前派工误写 `--data-dir` 已纠正，未改正式入口）。窗口可读取完整工作台 UIA 内容，但 computer-use 截图全黑，第一次点击倾听入口返回 `GetCursorPos failed: 拒绝访问 (0x80070005)`。已停止 Windows 输入并请求教师解锁／恢复可交互桌面，不以此推断应用白屏，不绕过登录／安全界面。原生选图取消、填写、正常关闭及冷开尚未完成，窗口保持；当前不能放行 L2。

### 验证方式调整及 L2 回修

教师确认解锁后，Codex重新识别窗口、重置computer-use会话并仅重试一次，仍同样拒绝访问／黑截图，已停止该控制路径。教师随后明确“先继续实施与自动验证”，受阻的原生对话框和Word目视检查留待控制恢复后补齐，再统一验收；本机再次受阻可交Windows测试机验证，便携包排除保持。后续L2限定自动技术核查依正常源码应用及独立测试判定，不能将延后的目视项目代签通过。

Codex使用外层parent／child loopback守卫运行原私有正常main driver，新根 `codex-L2-native-window-r01` 实际完成页面建档、五领域填写、健康照片导入、艺术未保存输入经真实宿主关闭协调保存，main exit0、任务／执行数均0。driver总体exit1：验证器误从领域行读取本属图文组的 `listening_text`；实际art position0组已存最终正文，目标也已保存。首根、原driver和报告保留；只对私有driver修正取值、准确命名覆盖项并增加关闭前后数据证据。另有1次正常源码启动的 `api.github.com` 版本发现DNS被守卫拦截，未成功出站，不是AI发送；后续仅在验证caller中将无关更新源工厂设None，不改生产入口或release配置。

Command Go最终只读报告实际Flash max、exit0；读取期间源码有变化、无hash/Git权限，其意见不代替最终冻结验证。Codex采纳P2-A：`ensurePhoto`未捕获cache读取拒绝，404／取消时会产生未处理Promise且停留加载提示。追加原实现者唯一修改 `ListeningEditorView.vue`、`d1.listening-ui.test.mjs`，补当前图片失败／重试及旧generation拒绝的隔离；其余已验证前端文件冻结。独立SFC首个404探针在修补落盘后执行，实际通过，无未处理拒绝且可见失败态，不能冒称修前运行态失败；新全部测试／构建待最终字节重跑。未采纳其未提交新建弹窗输入的推断扩展；普通取消不自动建档，另两条报告自身判无现存数据丢失／当前key接线下不可达，按约束记录。

### L2 最终限定结论

**L2按教师调整后的源码自动技术范围通过，直接进入L3。** P2-A最终SFC SHA-256 `41862249ac59ad3a98a737264f7e24e4a98c9c6fe800a83d251af1a888fe9c30`；独立实际SFC两项探针 exit0，404可见失败并仅GET重试成功，旧拒绝不清新generation loading／error／URL，未处理拒绝为0。最终完整前端回归 exit0（89.845秒，新增core9／SFC11／shell7），typecheck及新源码构建exit0，62份文件前后及交付后均相同。新构建主JS SHA-256 `2a5dbb6f23aa4dcb86f640178a1f0730d8dc573198897aa79f317ed35df2730a`。

正常源码 `codex-L2-native-window-r02/run.json` exit0：真实页面两同名记录不同id、五表填写、健康一图导入、dirty时空FileList零修订／回执／资源写入；关闭前DB尚无最终艺术目标／正文，经宿主实际关闭协调后均保存。仅健康一张图，不外推五域都有图。独立新源码进程 `verify-r03.json` exit0：按原稳定id重开、五领域所有控制字段及空星回读、健康Blob图片naturalWidth、艺术目标／正文实际DOM及存储一致。两次正常流程均main exit0，Python父／子守卫就绪、实际出站尝试0、审计正常、AI任务／执行0；仅验证caller禁无关GitHub发现，正式应用未改。

首次冷开调用漏传新driver必需的 `--record-id`，验证体前即失败，窗口尚未业务就绪时关闭未完成；保留报告后仅终止经PID／创建时间／父子链和精确命令核定的本次自建失败验证进程，没有全局kill或终止原窗口。第二次全部产品断言通过，但driver后台在关闭后才置完成标记，主线程先读标记导致总体exit1；该报告保留。独立caller随后仅等待验证线程完成再作报告，不改产品关闭结论或断言，第三次全部通过。run使用私有driver `576060…`，最终cold使用已停写的 `b0051b…`，各次原文件hash／前后稳定分别记录，不混为同一验证器版本；业务源码为同一最终62文件。

实现者修补后实际build／Flash max、idle／succeeded、exit0及停写已核实。15空表、3授权照片原件、2已验收Word、真实配置四文件指纹再次全保持（`L2-protected-originals-final.json`）；index空、HEAD未变、diff检查通过。原生FileDialog Cancel、鼠标／键盘关闭、可见WebView布局及Word目视按教师明确决定待补，不是已通过项目。

## L3

L2限定放行后，唯一OpenCode按当前源码负责以下确切文件；Codex独占正式规格、结果及独立核查。允许私有新唯一L3 driver／合成资料／源码构建；不先改模型、schema、迁移或备份，不重构共享I/O，不构建便携包；确需其它路径先报具体必要性由Codex核定。

```text
修改：
backend/app/local/app.py
backend/app/local/runtime.py
frontend/src/d1/App.vue
frontend/src/d1/bridge.ts
frontend/src/d1/views/ListeningRecordsView.vue
frontend/src/d1/views/ListeningEditorView.vue
frontend/package.json
desktop/d1_host_api.py
desktop/d1_main.py
desktop/tests/test_d1_observation_export_host.py（仅既有bridge端点精确集合如需同步）
新增：
backend/app/local/listening_export_service.py
backend/app/local/listening_export_api.py
backend/app/services/word_export_listening.py
backend/tests/local/test_listening_word.py
backend/tests/local/test_listening_export.py
backend/tests/local/test_listening_export_api.py
frontend/src/d1/listening-export.ts
frontend/src/d1/components/ListeningExportDialog.vue
frontend/src/d1/d1.listening-export.test.mjs
desktop/tests/test_d1_listening_export_host.py
```

本片的首次失败、回修及最终源码放行见下文。原生另存为／实际Word页检按教师已明确的自动验证优先调整待补。已对受控样稿运行打包的render_docx预检，Windows缺少soffice.exe而明确失败，日志保留；未装LibreOffice，不将该环境失败记为新Word产品缺陷。

### L3 进行中首失败

Codex纯生成器探针 `codex-L3-provisional-generator-r01` 使用真实受控small_health DOCX字节，源SHA `303669eb…` 前后稳定，exit1：`_fill_unit`将整个ZIP直接解析XML而失败。已交原实现者在原责任内修正，须校整个DOCX包hash后读包内document.xml，不能改传裸XML绕过受控包身份。

Command Go只读service交叉审阅后，Codex另份真实合成库 `codex-L3-provisional-manager-r02` 独立exit1，service SHA `203ddf89…` 稳定，四反例均保留：成功生成后同请求同载荷重放404；并发同键实际调用两次生成得到两个id；声明MAX_EXPORTS32却保留36对象；content过期而receipt仍ready。此探针刻意stub生成器，仅证明manager协议，不作Word内容或页面导出证据；原r01初始化少传关键字解包是Codex harness错误。已交同一原实现者修幂等／预占／过期／实际资源字节与容量边界，不加业务人数配额。未放行本片。

生成器修补后的独立 `codex-L3-word-structure-r02` exit0：15张真实受控单表和小／中／大班各一合册共18项全部通过；逐表网格／宽度／合并／行高、固定评价原文、选中／空星、右栏及段落标记宋体12常规字重、黑色文字／连续标题填空、合册图片字节及docPr唯一均核对。含长文、横竖合成图和艺术第三图留空。生成器源SHA `fc8674f3…` 前后相同、出站0；该项仅纯生成器内存字节，不作页面实际导出／Word目视证明。后续图片方向处理等若改变生成器须对应复验。

独立 `codex-L3-old-term-negative-r01` 又复现：仅3–6月旧学期，11月context.term为空，但已有term／记录均合法；同记录个人preview成功，领域preview明确选该记录仍报“当前学期不可用”。当时API无所选term_id，service绑today term。源SHA `a29cdbea…` 稳定、出站0；已交原实现者将领域导出绑定列表所选已有学期，并保留跨term拒绝及严格确认载荷，不按今天日期裁剪旧资料。

### L3 服务复测与后续回修

独立 `codex-L3-manager-recheck-r01` 对 service `e9c57092…` 执行 7 项探针，全部通过、源码稳定、出站 0：没有今日学期时仍可按所选历史学期默认／显式选集，顺序和并发同键只生成一个结果、改文件名冲突，驻留缓存 32、过期回执与内容一致。此处仍刻意 stub 生成器。更新后的纯生成器 `debb066c…` 在新根 `codex-L3-word-structure-r03` 再核全部 18 项，exit 0。

另份独立合成旧学期，`codex-L3-http-artifacts-r01` 走真实 loopback HTTP、实际受控 Word 生成器。22 项中 21 项通过：按个人实际生成五个可编辑表、按科学选择并调序生成两个表；EXIF 6／8 图按正确宽高处理、工作图与 Word 媒体散列一致；缺项确认、严格布尔与额外字段、过期修订、重复回执和注册图片损坏均正确。失败一项：合法建档姓名含斜线时默认文件名使个人预览 422。首失败和生成字节保留，已交原实现者仅修默认文件名安全片段及前后端文件名一致性，教师姓名和正文不改。这个 HTTP 证据不代替页面／宿主另存为和 Word 页检。

Codex 源码审阅另交同一实现者修选择表取消后行消失、忙时 X／Escape 绕过关闭守卫、旧异步回执跨对话框、未知生成重试确认值未冻结；同时保留生成阶段维护／关闭屏障和旧管理器退休的核查。上述对话框行为当前是源审发现，独立窗口回证待正式版本。

实际文件名修复后在新根 `codex-L3-http-artifacts-r02` 对同一 22 项全数通过；真实 HTTP 姓名带斜线 preview 200，记录和正文仍保留原值。另以阻塞生成器挂接真实 SnapshotBarrier 的 `codex-L3-maintenance-overlap-r01` 保留两个反例：在途生成时计数 0／0 可取得独占、独占期间新预览成功。此处只证明当时 manager 及真实屏障的接线缺口，不代替后续实际 app 复测。

Codex 独立正常入口 `codex-L3-window-r01` 已实际保存个人 Word；私有 driver 误以为默认记录排序一定使丙可上移而总体 exit 1。新根 r02 明确重选甲、丙后再上移，另复现“预览缺项”点击无反应：Vue 将 MouseEvent 传给形参 epoch，判断错误；同类重试读取一并反馈。前两根及结果保留，实际主程序均 exit 0、出站 0。修后新源码构建 `codex-L3-window-build-r02`、新根 `codex-L3-window-r03` 真实页面 8 项全通过，普通关闭 exit 0、出站 0。实际生成个人 5 表、科学丙甲 2 表；默认三人勾选、取消后可再勾回、手动丙上移，个人包含预览前实际保存的页面改动。两份可编辑 Word SHA `559a4a6c…`、`328d3466…`。本次仅注入验证另存为目录，实际宿主负责下载核对与原子保存；未替代 Word 页检或真实对话框操作。由于当前仍有维护及最终验收回归在途，不能把这次阶段字节的证据冒作最终冻结核验。

### L3 最终限定结论

**L3 按教师调整的源码自动范围通过，直接进入 L4。** 实现者原会话实际 build／OpenCode Go DeepSeek V4.1 Flash max，最后 finish stop、CLI exit 0、idle 晚于 busy。原白名单外只追加旧 `frontend/src/d1/d1.listening-ui.test.mjs` 的确切夹具补修：完整前端首次不认识新增子组件，保留首失败；实现者先补了 mock，Codex 按实际失败核定该路径，只读核既有断言保留并增实际忙屏障检查。短测试根后端 51 项通过；默认长临时根首失败是 CreateFileW 未建临时文件，同一用例在短根通过，不推断 WinError 编号或更改生产路径策略。

最终 Codex 独立 `codex-f3b1` 74 项通过。关闭接线补修后 `codex-f3b3` 151 项通过，577 份源码／测试在测试前后字节相同、父子守卫出站 0；停写复核仅最终宿主测试夹具在其后变化，单独重跑 `codex-f3h4` 7 项通过且整份源码稳定。之前 f3b2 虽 150 项 pytest 全绿，因测试期间 main 和宿主测试变动，冻结核查 exit 1，原报告保留。完整前端回归 exit 0（91.584 秒）、typecheck 和 Vite 新源码构建 exit 0；其后只有旧 SFC 夹具增加忙态断言，最终独立 12 项通过。构建主 JS SHA `e2c126ba20cdc6c63bd3824b5fc7eea8d03f0d2da35e79ef1c62ebb1de63de86`。

`codex-L3-close-overlap-r01` 复现后端开始生成但页面忙通知未到达时，实际宿主关闭／维护探针误判为空闲。修后最终 `codex-L3-close-overlap-r03` 七项通过：两个探针均看见在途生成，旧窗口捕获旧管理器而不读 runtime 新引用，工作结束恢复空闲。service SHA `b9a68773…`、main `5eaceeeb…`。另核 SnapshotBarrier 生成计数 0／1 并拒绝独占、结束后释放，已有独占拒绝新预览；旧管理器退休／重新绑定七项通过。最终真实 HTTP `codex-L3-http-artifacts-r03` 22／22；纯生成器 `debb066c…` 18／18。

停写后正常 `d1_main` 源码窗口 `codex-L3-window-r07` 8 项通过，主程序 exit 0、出站 0。页面保存后实际生成个人 5 表和科学丙甲 2 表，经真实宿主校长度／散列及原子写，实际保存状态可见。两份 SHA `559a4a6c…`、`328d3466…`。r04 已实际写个人文件，但私有验证器仍查旧成功提示节点而总体失败，保留后仅修检测实际可见新提示；r05–r07 通过。实际 FileDialog 操作和 Microsoft Word 渲染按教师决定待补，不用源码 DOM 或 OOXML 替代。最终两份教师文件仍待 L4 同一份资料联测。15 空表、3 照片原件及副本、2 样稿、原配置四文件指纹全保持，HEAD 未变、index 空、未构建便携包。

## L4 与最终验收

L3 限定放行后，继续原 OpenCode 唯一实施会话。实际迁移头复核为 `20261107_0009_local_listening`；L4 的独立回归已留真实 0009 合成备份两份，一份含既有周计划成功候选及采用记录和倾听记录（55 表），另一份含既有日计划／观察 AI 记录及倾听图片。开始前精确核定文件责任，未授权外的源码、旧断言、宿主和 L3 导出冻结。

修改：`backend/app/local/{models,schemas,ai_task_service,ai_executor,ai_worker,ai_transport,prompt_bundles,backup_validate,app,api}.py`（共享 API 仅必要读取与分派）、`frontend/src/d1/{types.ts,ai.ts,App.vue,listening.ts,views/ListeningEditorView.vue}`、`frontend/package.json`。新增：`backend/migrations_local/versions/20261107_0010_local_listening_ai.py`、`backend/app/local/listening_ai_{contracts,inputs,service,adoption,api}.py`、`backend/tests/local/listening_ai_{fixture_support,workers,fake_transport}.py`、`backend/tests/local/test_listening_ai_{contracts,inputs,service,adoption,api,migration,backup,executor}.py`、`frontend/src/d1/listening-ai.ts`、`frontend/src/d1/components/ListeningAiPanel.vue`、`frontend/src/d1/d1.listening-ai-{core,ui}.test.mjs`。允许私有新 L4 合成根和验证器；若需增加写入路径须以实际必要性核定，原 OpenCode 不修改正式规格或记录。

先核假供应商、迁移、采用和恢复。付费验证尚未发送；Codex 已只读确认本机原标准供应商配置可用，假门通过后才向独立长期保留的合成验收档案配置并作必要的真实文本／视觉验证。受阻目视及 Windows 测试机源码接续按教师最新授权另记。最后一次交教师短清单、同一份资料生成的两份可编辑 Word 和可取得的实际代表页，标明未执行项。Windows 便携包排除。

### L4 进行中首失败

Codex 独立 `codex-L4-provisional-contract-r01` 在合同源 `ac6449d5…` 上复现输入接受额外姓名、布尔版本／位置和非文本正文，领域候选接受缺字段空对象及省略星级。合法文本与拒绝布尔星的对照通过；源码稳定、出站 0，总体 exit 1。已反馈实际输入／嵌套结构及候选须严格吻合声明，显式空建议合法，字段遗漏不能伪造成功；领域 item_id 集合由冻结模板验证。实际发送固定配置、来源／图片链和不可识别投影仍待后续验证。

`codex-L4-transaction-boundary-r01` 使用合成真实 SQLite：独立投影成功；在当前任务服务读事务及写事务入口各复现重复 BEGIN，SQLite 均拒绝，出站 0。实现源码另见采用先调用会独立提交的 save_domain、之后才写采用表；以及预览对所有目标原值一并拒绝。上述服务在实施中，未放行。基于这个确切证据，Codex 追加唯一允许 `backend/app/local/listening_service.py`，只提取不自启事务的 DTO／单域写入内核，保留原 L1 保存契约。最终同一次提交中核归属、修订、目标原值并写指定一项、修订、消费和回执；转换图像仍在写锁外。需以注入失败、重复请求、先采用策略后改一颗星证明完整性；不能放宽通用 tx 或把某项被采用误作全部候选过期。

### L4 独立链路增量

严格合同 r02 八项及文本事务边界 r02 三项通过；图片事务 r01 保留实际带 PNG 的嵌套 BEGIN，随后改为隔离只读取图／转换、写事务仅核冻结登记。原配置与模型钉住、ORM 凭据标量冻结等已反馈，不能把过程中的源码审阅当最终付费门。

真实 0009 历史备份恢复：`wr01` 周计划成功候选及采用记录失败，0010 首版将已有 weekly_plan_id／draft_id／create_operation_id 复制为空；互补含 daily／observation 任务、两套倾听及 43 资源的 `fr01` 通过。修后 `wr02/fr02` 全通过，逐列保留 55 个旧业务表、外键／integrity 正常、43 资源一致、两个原包散列不变，均未启动执行器且出站 0。四张旧来源 AI 表可混填倾听列的内存反例 r01，修后 r02 四表均拒绝；DDL 对照未丢旧表／列类型／命名索引／FK／约束名，只新增倾听采用表。初次迁移 SHA `95a31a15…`、修后 `008d46fb…`，后续变更仍须对应复验。

独立假供应商 `codex-L4-fake-text-r01` 真实队列、子进程及 worker 的两个纯文本任务成功，实际请求零图；完整 `fake-r01` 在视觉取图代码仍在途时任务一直 pending，执行／发送均 0，保留超时现场。修后 `fake-r02` 17 项通过，`fake-r03` 扩充至 22 项通过：实际 worker 本组一图、同领域三图、无姓名／文件名／opaque ids／其它领域或同名记录材料，候选未自动写正文，教师改写采用幂等；插入采用表时注入失败使正文／修订／回执一起回滚；只采用策略并改一颗星，其余保持。实际更改另一颗星只使该目标无效，未改评价仍可核对；模板外项目导致 failed 且无候选；换图使旧候选不可采用，旧资源仍保留。unknown 仿真无自动重发；最后生成完整备份。均为假传输、父子守卫出站 0，未使用真实密钥。

`codex-L4-api-binding-r01` 实际 loopback 复现预览 body 候选错仍 200、采用 URL 候选错仍 201、已提交采用 GET 回执 404；修后 r02 四项通过。Command Go 对进行中字节的只读交叉审查指出同组链缺口，Codex `candidate-group-r01` 在另一份合法合成库只改候选到同记录另一组，GET／预览均 200；修后 r02 两者均明确拒绝（503 本地存储错误），原 fixture 不变、出站 0。

备份反例 `backup-adversarial-r03` 使用完整校验与合法正对照：改候选 domain 拒绝；但改照片依赖组、伪造采用前后散列、采用指向同档案无关配置操作、raw 外域 item 重算 candidate hash，四副本被接受，已交回修。r01/r02 验证器未关闭自建 SQLite 连接，导致文件租约无法读取，全体同样被拒，不算产品逻辑证明；r03 修夹具后才为有效反例，所有源库／包保留。

源码窗口 `codex-L4-window-r01` 私有 driver 漏传 AI 配置协议常量，初始化后即 422，总体失败；补正确合同后 r02 实际页面已通过保存 422 不建任务不发送且留稿、仅图候选不写正文、教师改写采用，以及刻意丢失策略采用响应后 GET 核回执且 POST 只有一次。下一颗星确认失败：页面用旧修订号冲突，实际星仍 2，ledger 只有 note14→15、support15→16。该首次失败及合成 DOM 保留；已交原实现者核未知查询成功后的父记录／预览及冻结修订推进和异步串行。未将失败窗口记作正常关闭或 L4 通过。

### L4 恢复与完整源码窗口

`backup-adversarial-r04` 在含真实手工改星和换图历史的 fake-r03 库上，合法对照接受，五类损坏副本均拒绝为 `BACKUP_DB_LOGICAL_INVALID`，源库及原包不变、出站 0。`current-restore-r01` 将该份完整备份恢复到新根，56 表逐列一致、4 资源一致；独立冷开后 succeeded／outcome_unknown／failed 分别 2／1／1，候选与三项采用记录分开保留，执行器启动不重发。新根未携原密钥，测试只重新配置自己的假凭据。

Command Go 本片仍只读原会话交叉审查，已完成并 exit 0；URL 候选绑定和 group 链意见均由 Codex 用真实合成库另行复现，不将只读意见代替回证。采用事务内核检查未发现正文先提交问题，Codex 的故障注入已证实整体回滚。原实现者在最终旧测试同步时先修改 `test_listening_migration.py`；Codex 根据当前头确已增加一表的实际证据追加该文件、`test_listening_backup.py`、`d1.listening-ui.test.mjs` 的限定责任，只许同步 56 表／0010 和新增子组件夹具，保留旧 0008／0009 身份及原断言。这个先写后核定的过程偏差保留。公开迁移回归初版引用私有备份并 skip，已要求改为仓内可独立生成的真实 0009 合成 fixture；原私有旧包对照继续留在 Codex 独立验证。

实际 SFC 延迟响应探针 `panel-behavior-r01` 三项通过：重置领域时清理忙阶段，旧候选到达不覆盖新领域，旧 finally 不解除新操作的忙态。`window-r07` 实际完成个人 Word 后不能正常回列表，保留忙阶段首失败；修后最终窗口继续验证。r03–r06／r08 另有私有 driver 过早读取、误用本地化状态及 Element Plus select 外层节点的失败，均保留并只改私有验证器，未把它们当产品回归。

正常 `d1_main`／WebView2／实际宿主 `codex-L4-window-r09` 19 项通过、main exit 0、父子守卫出站 0。同一套三名虚构幼儿资料贯通：保存明确失败时零任务／零发送且留稿；本组仅图草案标示来源且不自动写入；教师改写后采用正文；只采用支持策略及一颗改为 1 的星，其余综合评价／空星保持；故意丢失已经提交的采用响应后，只 GET 查原回执，POST 计数仍 1。预览前自动保存 dirty 内容，经缺项明确确认后，实际保存个人五表和科学丙甲两表 Word，均只含教师已保存选择；Word 生成没有 AI 请求。宿主仅注入验证保存目录，不能据此签真实原生对话框。

该根另一个正常源码进程冷开五项通过，任务／执行／候选／采用数量仍为 2／2／2／3，无新 provider 调用、main exit 0。实际完整备份含 3 记录、9 图，SHA `ba6e0219c3a10e8d5fe25e7dd5f23fbddb6d5c45838b07ac033e5368a615126b`；恢复到 `current-restore-r02` 后 56 表和 9 资源逐项一致，原包不变。独立执行器冷开不重发，随后再次正常源码窗口读到同一改写正文、支持和单项星级，任务与采用数量保持、正常关闭、出站 0。其原始候选、教师修改和采用回执仍可区分。

独立后端广回归首轮 `codex-f4b1` 的 12 个失败均在 Windows spawn 子进程重复执行未加 main guard 的 Codex 私有 wrapper，产生 `FileExistsError`，并非产品断言。原 wrapper 和 stderr 保留；修验证器的 main／freeze_support 后，单独旧观察模块 42 项及新增倾听 AI 六模块 10 项均通过、源码稳定、出站 0。该首轮期间还有测试夹具变更，不能作最终冻结通过。最终稳定字节的相关完整后端及前端回归另记。

### L4 最终字节与假供应商门

原 OpenCode 最后明确停写，CLI exit 0，session 的 idle 晚于 busy；最后 assistant 为 finish stop、build／`opencode-go/deepseek-v4.1-flash#max`，身份与原会话相同。最终源码／测试冻结 595 文件，私有 `L4-final-source.json`。Codex 对照 L3 冻结发现额外 `desktop/d1_main.py`：实现者通过 shell 先改了 `_maintenance_busy`，没有先报白名单。独立去除这一个 AI 忙态块后重构 CRLF 字节 SHA 恰为 L3 `5eaceeeb…`，证明其它宿主代码未变。该块在维护切换前纳入 live／in_flight 任务，未知读取失败保守阻挡并关闭 session，属于 L4 共享队列维护完整性；Codex 现仅核定此确切增量并保留先写后核定的过程偏差。`maintenance-ai-r01` 七项及原维护／关闭／倾听宿主 105 项独立通过，最终宿主 SHA `e28283ec4b54279639d6dd0411fc96074b15d9fcb1fa27227130817c4f7e42b4`，不再把 L3 的宿主身份冒作最终字节。

最终 `codex-f4-final-b1` 14 个相关后端模块 **190 passed**（237.05 秒），包括六个倾听 AI 模块、原倾听保存／备份、观察和周计划 AI、共享任务／执行器；`codex-f4-final-host1` **105 passed**。595 文件前后完全相同，Python 3.14.10，父子守卫就绪、实际出站尝试 0、审计正常。完整前端 `test:d1` exit 0（93.211 秒），typecheck exit 0（10.954 秒），构建 exit 0，三者前后源码稳定。最终 Vite JS SHA `b40e087f7b3d898c63a67faa1b1b4cec5cabc66395b605687482850a9c0c398f`。

最终字节 `fake-r04` 22 项重放通过；最终构建的正常源码窗口 `window-r10` 19 项全部通过、正常关闭、出站 0。同一资料的两份 Word 与 r09 完全同散列：个人五表 `63d639c4b87fcab436e9951d44a4c8e186d9515bae18696bbd722d28126f0b12`；科学丙甲两表 `47a9e586b0b0d609915651544619d396695419f962083b585976f38564520547`。备份恢复／冷开仍是上述 r09 同内容资料的独立证据，未跨名假称 r10 已再恢复。私有 `L4-fake-gate.json` 核验最终 595 个散列及 12 份相关通过报告后才放行真实供应商；保护指纹 `L4-protected-originals-pre-paid.json` 中 15 原空表、3 照片原件／副本、2 已验收样稿及原配置四文件均保持。

### 授权真实 AI 与持久配置

仅在上述假门通过且原实现者停写后执行。原标准配置 `https://api.deepseek.com`／`deepseek-flash`／`chat_completions_v1` 已存在且 DPAPI 可解密，无需教师再次提供密钥。只读打开原库，不对其迁移；只在当前进程内通过既有服务解密，并为新的独立合成档案用系统 DPAPI 重新加密，不回显、不写 `.env`、不进入 Git 或测试机源码材料。

初次选 AppData 根配置成功，但独立冷开前的路径边界检查发现 Codex MSIX 将该新目录重定向到包的 LocalCache，验证器明确停止，付费发送仍为 0；首配置和冷开失败日志保留。为让普通 PowerShell 使用同一实际根，改用已核实不重定向的 `%USERPROFILE%\KGNext-Listening-Acceptance-20261107`，数据与独立凭据分别在 `data`／`credentials`。第二次配置和独立进程冷开均 ready、可解密，原配置四文件散列保持、出站 0。初次 AppData 副本留作首现场。

`codex-L4-paid-r01` 实际应用队列／执行器／worker 只主动创建 **2 个**任务，均 succeeded：健康领域一组虚构观察文字 → 综合评价、支持策略、6 项星级建议；科学本组只有教师授权作品副本一张 → 右栏草案及待核实问题。原始候选保留在独立验收档案，未自动采用。文本结果指出材料不足，6 项均 null，不拿单一慢走片段推断整体健康表现；图片结果只描述可见线条／形状，提出待询问事项，没有编造幼儿引语。此为一次实际响应核查，不保证后续每次生成的内容质量。

真实 worker 网络仅允许 `api.deepseek.com` 的官方 DNS 与其本次解析所得公网 IP 的 443，沿用生产 TLS／CA／主机校验；离线 guard 自测 10 项通过后才使用。实际日志恰为 2 次官方 DNS、2 次官方 443 连接、2 个子守卫启动，无拒绝／审计失败，父进程出站 0、执行器正常排空退出。未再提交、重试或使用 Go 开发套餐作应用供应商；不报告未取得的实际计费金额。私有候选内容、请求及审计日志不进入公共仓库。

长期根保留最终源码前端静态文件及 `启动源码验收.ps1`，启动参数固定本根 `data` 和 `credentials`，使用现有 3.14.10 venv 与仓库源码；它不依赖临时目录或本次进程环境，也不是便携／冻结包。后续修改仓库源码会改变其后端身份，需按下一轮责任核查。

### L4 限定结论与统一交验

**L4 按教师调整的源码自动技术范围通过，L1–L4 统一交教师验收。** 最终独立真实源码设置页 `durable-window-r02` 四项通过：官方地址／模型保持，配置 ready／密钥可解密且密码输入框为空，2 个真实成功任务与 2 原始候选保留且未采用。主程序正常关闭 exit 0，任务／执行／候选／采用计数前后为 2／2／2／0，父子守卫出站 0。r01 因私有 driver 把 `data-d1` 误当 Element Plus 外层容器，定位空节点失败；已保留，r02 只修选择器。独立原配置及全部授权输入最终指纹仍保持（`L4-protected-originals-final.json`）；最终 595 文件均与假门相同，`git diff --check` 通过，index 空，HEAD 仍 `a160b321ddbe1d101f42109c3f40a2f47e97eaa4`，没有提交／推送。

教师短清单见[统一验收](desktop-one-to-one-listening-acceptance.md)。两份本轮源码应用实际生成的可编辑 Word 以易读文件名集中到私有 `C:\kgm-lsn-1107\teacher-acceptance-20261107`，复制后核 SHA 与 window-r10 一致。Windows 测试机接续目录为 `C:\kgm-lsn-1107\windows-source-handoff-r01`：源码快照、相同最终前端静态文件、逐文件清单与散列、隔离根启动器和人工核查说明；不含 Python／EXE／DLL、密钥、数据库、真实照片或便携构建。授权作品只留在另行提供的私有合成 Word 中，不混入源码。

本机 computer-use 拒绝访问及缺少 soffice 的原因未变，仍未执行真实原生对话框 Cancel／Save As 的人工操作和 Microsoft Word 逐页目视，未取得实际代表页预览。当前会话没有 Windows 测试机连接／共享目的地，交接材料准备完毕不等于该机已验证。源码自动、Word 结构、真实 AI、原生目视与教师体验分开记录；便携包排除，未启动安装、更新、签名、公开发行或其它环境补验。后续拿到可用测试机通道，仅按本份同源清单接续上述受阻人工项目，不重放真实 AI 请求。

### 2026-11-07 提交前补核与测试机授权

教师随后授权提交并推送一对一倾听分支，以及测试机调用应用的真实 AI 和 OpenCode DeepSeek。独立 `codex-prepush-renderer-r01` 复现旧 renderer 恢复夹具仍断言 55 表，实际迁移头 0010 为 56 表。原 OpenCode 只同步这一个断言，Codex 逐字节比对其余 594 个源码与测试文件。`codex-prepush-renderer-r02` 整个恢复验证模块 38 项通过，父子守卫出站 0。先前真实 AI 结果仍归原验证根，本次补核为测试夹具改动。

最终普通提交仅含本轮源码、测试、15 份授权空表和正式文档。Codex 用独立预览 index 确定逐文件 blob、父提交和整树，原 OpenCode 按该清单提交并向同名远端分支推送。测试机私有交接钉住实际提交和源码散列。先完成假供应商，再用该机独立合成根和本地加密凭据，主动执行纯文本和仅图任务各一次。应用的官方 DeepSeek 连接与 OpenCode 的辅助调用分开记录。测试机 Word 和原生对话框回执仍待实际操作。
