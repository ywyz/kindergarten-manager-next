# D1 独立审阅与接续

> 公开版隐私处理（2026-10-30）：本机用户路径、私有部署地址或联系标识已替换为占位符；原始记录由维护者私下保留，历史日期、结论和产物哈希不因此改变。

首轮：2026-10-12；最新实施复审：2026-10-17。审阅者：Codex。基线：`codex/desktop-v2-foundation`、HEAD `b3c5bbf` 及当前未提交工作区。依据 [D1 规格](../specs/desktop-manual-daily-plan.md)、[实施结果](desktop-d1-result.md) 与 [技术核查](desktop-d1-technical-review.md)。

**最新第八轮修复复审结论（2026-10-17，§17）：D1B在当前Windows 11开发机工程复审通过。** R17设置残留关闭，累计17项全部关闭；独立原组件反例及真实WebView2窗口验证草稿保留、显式取消后重试关闭。133本地／108回归／146桌面、纯逻辑＋60组件、类型检查与构建通过；28e3e60e…包137文件与源码／资产一致，真实对话框与同字节Word证据有效。下一步教师流程与实际IME体验；D1产品、干净机器及发行兼容性仍未验。D0／D1A、3.12异常与旧失败保留历史身份。

§1–7保留D1A历史，§8为D1B准备，§9为首次实施复审，§10–16保留前七轮修复复审；**§17为最新第八轮修复复审与工程收口依据**，后续见[唯一当前清单](../tasks/current.md)。

## 1. 范围与方法

- 限定审阅 `backend/app/local/`、独立本地 Alembic、`backend/tests/local/`，以及公共 ID 解耦的两个既有文件；没有把整个未提交工作区当作本轮新增改动。
- 已读 codebase-memory 技能；当前工具目录没有图查询或 `check_index_coverage`，不能取得 generation／覆盖信息，使用有边界的源码读取及独立交叉审阅，不声称全仓图覆盖。
- 使用现有解释器、临时真实 SQLite 文件、真实 Uvicorn HTTP、独立连接／进程及合成数据。未修改实现、测试、迁移或构建脚本，未安装依赖，未读旧 `.env`／密钥，未连接 MySQL、远程业务或真实 AI。
- D0 已有工程结论沿用；没有重复 GUI、Word 或发行验收，没有提交、推送或更改分支。

## 2. 需修复问题

### R1（P2）：版本检查遗漏额外的未知 revision

位置：[migrate.py](../../backend/app/local/migrate.py) 的 `inspect_database`，审阅时第 95–103 行。

版本表查询使用 `LIMIT 1`。真实迁移后的数据库同时保留 `20261012_0001_local` 和插入的 `20990101_9999_future` 时，`ensure_local_schema()` 返回 `state=current`，没有拒绝启动。当前单线迁移链不能把多行状态当作已经兼容，更不能忽略其中的未知／较新 revision 后开放写入，违反规格 §2。

修复要求：检查完整版本记录，拒绝未知、较新及本迁移链不支持的多行／歧义状态；保留原库，不清理、降级或 stamp。补充已知＋未知两种插入顺序、异常多行及正常单 head 重启测试。

### R2（P2）：学期日历指针可空，数据库不能保证首修订存在

位置：[初始迁移](../../backend/migrations_local/versions/20261012_0001_local_baseline.py) 第 66 行、[models.py](../../backend/app/local/models.py) 第 103–105 行，以及 `profile_service._create_initialized`。

`current_calendar_revision_id` 被声明为 nullable。真实 Alembic 文件库且 `foreign_keys=ON` 时，可以插入 NULL 指针学期并成功 COMMIT，此时日历修订数量为 0，`foreign_key_check=[]`。正常初始化会随后补指针，但数据库没有实现规格 §3.3 所需的非空首修订保证，NULL 绕过了复合 FK。

修复要求：模型和实际 schema 均保证指针非空，初始化预分配修订 ID，依靠复合延迟 FK 完成学期与首修订的原子建立。已有本地 head 库也必须获得约束，不能只改初始迁移／模型而让旧 head 直接跳过；用后续本地 revision 保留有效数据升级。对已有缺指针等异常状态明确拒绝并保留原库，不能伪造修订或清库。补空库、旧 head 升级、缺首修订／NULL／错学期修订拒绝和迁移失败回滚证据；不要假定循环 FK 的 batch 重建天然安全。

### R3（P2）：合法 Windows 路径中的 `%`／`#` 破坏启动和检查路径

位置：[migrate.py](../../backend/app/local/migrate.py) 的 `alembic_config` 第 48–53 行、`inspect_database` 第 72–74 行。

- 数据目录为 `teacher%name` 时，未转义的数据库 URL 进入 ConfigParser，抛出 `ValueError: invalid interpolation syntax`，无法启动。
- 数据目录为 `teacher#name` 时，手拼 `file:` URI 将 `#` 后路径及 `mode=ro` 当作 fragment；检查误打开并创建旁边的零字节文件 `teacher`。正确目录的数据库实际已迁移到 head，启动仍报 `LOCAL_DB_MIGRATION_FAILED`。

用户目录或注入数据目录可以合法包含这些字符。修复须分别处理 Alembic 配置插值和 SQLite file URI 编码，保证检查始终只读目标文件，不写旁路文件。对数据路径及相关迁移资源配置路径验证中文、空格、`%`、`#`，至少覆盖初始化、再次启动、未知版本拒绝及无额外文件。

### R4（P2）：损坏的持久内容未按存储错误处理，可能被继续追加

位置：[daily_plan_service.py](../../backend/app/local/daily_plan_service.py) 的 `_load_content` 第 126–136 行和 `save` 第 406–422 行；关联 JSON 反序列化错误边界。

在合成数据库正常创建计划后，经 SQL 注入故障并使用真实 HTTP 验证：

| 故障 | 实际响应 | 应有边界 |
| --- | --- | --- |
| `adopted_content` 原始值为 `not-json` | GET 500 `INTERNAL_ERROR` | 持久数据错误 503 `LOCAL_STORAGE_ERROR` |
| JSON 对象为 `{"bogus":"stored-invalid-content"}` | GET 200 返回非法结构 | 不将损坏内容作为合法详情 |
| 上述非法对象存在，PATCH 仅修改原文 | 200，追加 v2 并复制非法对象 | 503，内容／指针／日志不变 |

当前只核对内容指针归属与版本，没有校验持久内容结构；遗漏字段继承路径直接复制旧对象。修复须验证读出的持久结构与已有 ID 完整性，并将读取解码／持久结构损坏映射为存储错误。校验不能生成新 ID、正规化后自动修复或默默丢掉数据；客户端非法输入仍为 422。错误响应及诊断不得泄漏教案正文、路径或认证材料。

### R5（P2）：PATCH 在写锁内才校验与数据库无关的内容结构

位置：[daily_plan_service.py](../../backend/app/local/daily_plan_service.py) 第 395 行先执行 `BEGIN IMMEDIATE`，第 406–422 行才进行原文正规化及内容结构解析。

真实临时文件由独立连接占写锁时，PATCH `expected_content_version=1`、`adopted_content={"unsupported_field":"x"}` 等待 5.56 秒后返回 503 `LOCAL_DATABASE_BUSY`；释放锁后相同非法请求才返回 422。这不符合规格 §6“参数结构校验在锁外”，并让不依赖数据库的解析占用写锁。

修复要求：纯输入正规化／结构解析在加锁前完成；锁内保留上下文重读、expected version 和当前版本 ID 归属核验。不得通过锁外缓存旧版本或取消锁内版本检查来缩短事务。补持锁条件下非法结构仍直接 422 的验证。

### R6（P2，验证缺口）：两项测试不能识别所声称的回归

1. [worker.py](../../backend/tests/local/worker.py) 第 129–152 行自行发出 `BEGIN` 并两次查询 `count(*)`；[test_concurrency.py](../../backend/tests/local/test_concurrency.py) 的快照测试未经过业务 `read_scope`／关联读取服务。它证明 SQLite 文件快照原语有效，不能保证生产详情、列表不会混读。须用同步屏障验证真实关联读取链路，确保并发提交后的响应为完整旧版或完整新版；测试应能发现业务显式读事务被删除的回归。
2. [test_transactions.py](../../backend/tests/local/test_transactions.py) 第 161–194 行在同一个 `assertRaises(IntegrityError)` 内执行 INSERT 和 COMMIT，新头却引用另一个计划的内容指针。额外反证：仅在临时测试库删除 `uq_local_daily_plans_effective_class_date` 后，直接执行原用例仍通过；提交被跨计划延迟 FK 拒绝，掩盖了索引缺失。须精确断言有效日期唯一约束的失败阶段／SQLite 错误码，或构造其余约束完全合法的头和首版；并检查实际索引列恰为 `(class_id, plan_date)`、局部条件正确。

这些是确定的回归漏检，不单独证明当前显式事务或局部索引实现错误。修复后保留真实文件／独立进程验证，不以增加测试数量代替有效断言。

## 3. 已通过的独立验证及证据

命令工作目录为 `backend`；设置 `APP_DISABLE_DOTENV=1`、`PYTHONIOENCODING=utf-8`，Python 使用 `-X utf8`。下表解释器路径相对于仓库根；执行时使用其绝对路径。

| 验证 | 解释器／命令 | 本轮结果 |
| --- | --- | --- |
| D1A 全套 | `backend/.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests/local -t . -v` | Python 3.14.7／SQLite 3.50.4；67 项，0 skip，exit 0，41.610s |
| D1A 桌面解释器复跑 | `%TEMP%/kgm-d1a-py312-venv/Scripts/python.exe`，相同命令参数 | Python 3.12.10／SQLite 3.49.1；67 项，0 skip，exit 0，39.367s |
| 受影响既有测试 | 主环境 `python -X utf8 -m unittest tests.unit.test_i3_content_validation tests.unit.test_security tests.unit.test_calendar_boundaries tests.unit.test_i3_api_schemas` | 66 项，0 skip，exit 0，0.395s |

主环境实际依赖：SQLAlchemy 2.0.54、Alembic 1.20.0、FastAPI 0.141.1、Pydantic 2.13.5、chinesecalendar 1.11.0。初始化重试、同日并发、过期版本、故障提交回滚、重启持久化及入口防护的已有通过结论保留；不能覆盖本轮反例及 R6 缺口。

本机证据（临时路径不保证长期留存，关键结论已写入本文）：

- `%TEMP%\kgm-d1a-codex-review-20261012\`：`local-py314.log`、`local-py312.log`、`regression.log`、`unique-test-false-positive.json`（删除唯一索引后原用例仍通过）、合成损坏数据错误日志。
- `%TEMP%\kgm-d1a-codex-corrupt-e7asaegq\summary.json` 及 `data\kindergarten.db`：R4 完整 HTTP 响应与合成故障库。
- `%TEMP%\kgm-d1a-storage-review-evidence-030f0748cfa54e5e93179a958d6cb912\storage-review.txt`：R1–R3 复现步骤和输出；对应 TemporaryDirectory 数据库已自动清理。
- R5 真库 HTTP 结果见 §2；其临时数据库已自动清理。

环境记录需要纠正表述：原任务明确选用已存在的 Python 3.12.10，使用 `uv sync --locked` 且禁止下载新解释器；实际 `backend/.venv/pyvenv.cfg` 和实施报告是 3.14.7、`uv sync --frozen`。本次没有核实该解释器来源或额外授权，不能据报告将其描述成完全遵循原环境命令。3.12.10 本轮复跑已补独立兼容性证据；无需为审阅而销毁或重建环境，修复阶段继续使用已存在的 3.12 环境。原预演与锁内依赖下载授权记录保留在[技术核查 §6](desktop-d1-technical-review.md#6-d1a-验证环境补充2026-10-12)。

原编码提示词的环境步骤在此保留为约定记录（不是本轮重新执行命令）：仓库根读取 `desktop/.venv/Scripts/python.exe` 的 `sys._base_executable`，随后 `uv sync --project ./backend --locked --python <该已存在的3.12.10解释器> --no-python-downloads --no-managed-python`；先检查 `UV_PROJECT_ENVIRONMENT`，若存在重定向则仅对该命令固定为 `backend/.venv` 后恢复，不使用 `--active`。安装前后核对声明／锁散列，不裸跑触发 3.14 下载、不重建锁。原允许的是已有锁内依赖恢复，不是安装新 Skill／MCP 或解释器。

依赖声明／锁文件本轮核对的 SHA256：

- `backend/pyproject.toml`：`E5F948D2ACD54D38E45639B0A8DDD3E804DABE1A5C525F8565486F16A6428961`
- `backend/uv.lock`：`CC589C0A4135C4615E95F7EC5F049ECD45AD4D3FA3C2EF93445803EB757D5495`

## 4. 低优先级边界及 D1B 接续

- 日期上限：正常初始化后 `calendar?from=9999-12-31&to=9999-12-31` 返回 500。本地 `calendar_read` 复用的 `calendar_service.daterange` 在最后一天后继续加一天溢出；属于既有算法被新入口暴露的 P3 边界。D1A 修复可定点补齐终止行为及相关日期测试，不增加推测的学期年限或改变 unknown 年份规则。
- 学期外已有计划入口：合成 SQL 将学期起始日移到已有计划之后，日历固定返回 `existing_plan_id=None`，但 by-date 仍可读取。D1A 没有维护 API，本轮不将其列作当前正常流程阻塞；D1B 开放学期范围修改前，必须保证已有计划入口与新建资格分开。
- `calendar_revision_id` 详情字段、重复创建先打开已有、不接受显式 `adopted_content:null`、403 代码、仅返回状态的 health 路径均与当前契约相容。D1A 恰好单学期限制可以保留，但不能直接作为 D1B 多学期维护方案。

下一步顺序：

1. **OpenCode 修复 D1A R1–R6，并更新同一实施结果。** 唯一交接见[当前任务](../tasks/current.md)。只做必要实现与有效测试，Codex 再独立复审；不重开无关 D0、旧云端或发行工作。
2. **Codex 收敛 D1B 配置维护规格。** 整理个人资料、班级改名／升班、学期新增／修改／切换，以及已有计划访问／编辑范围；只对真正未确认的产品选择向用户提问。稳定 ID、历史表头快照不静默改写、真实影响预览、确认版本复核已经确定，不重复确认。
3. **确定 D1B 工程接口后交 OpenCode 实现。** 重点是多学期上下文与按日期解析、持久日历新修订和例外、统一离开保存协调，以及数据库已保存版本的 Word 导出。关闭／切日期／进设置保存失败留页、409 保留输入、导出不自动保存、原生取消／失败／实际成功分开，均沿用已有决定。
4. **D1B 另做真实 Windows 业务验收。** 覆盖页面初始化、手工编辑、离开与关闭、保存冲突和失败、范围／缺项确认变化、原生保存取消／占用重试、真实 Word 全页。D1A 自动测试通过、D0 合成 Word 或本次审阅都不替代该验收。

旧 D1A 编码提示词中的契约已在 D1 规格、技术核查及实施结果中保留；环境差异、审阅反例和未验事项归并到本文。更新同一个 `docs/tasks/current.md`，不另存多轮提示词副本。

## 5. R1–R6 修复后独立复审（2026-10-13）

### 5.1 范围与逐项结论

审阅 [实施结果 §9](desktop-d1-result.md#9-r1r6-定点修复2026-10-12-第二轮) 所述修复，以及实际本地服务、迁移、测试和必要共享规则。复用现有 Python 环境，在临时真实 SQLite 文件和合成数据上运行 HTTP、并发、故障注入及内存变异验证；没有修改实现、测试、迁移或构建脚本，没有安装依赖、访问真实教师库／旧 `.env`／远程业务或启动 D1B。

本轮 codebase-memory 工具可用：索引项目 `C-Users-yw980-code-kindergarten-manager-next`，generation `2026-10-13T11:19:36Z`，状态 ready。按 Verify 层级进行限定图查询及精确文件覆盖检查；相关文件返回 `metadata_changed`，目录 scope 的已记录排除为 `__pycache__`，均以实际源码回读补证。不据此声称全仓无缺陷。三个独立只读子审阅分别核查存储迁移、内容边界及测试有效性。

| 项目 | 本轮结论 | 依据与边界 |
| --- | --- | --- |
| R1 完整版本保护 | 关闭 | 查询全部 revision，拒绝多行／未知状态；两套完整测试中的顺序、重启和拒绝回归通过 |
| R2 学期首修订非空 | 关闭 | 0002 为新旧库补 NOT NULL，首修订预分配且延迟 FK 原子提交；独立旧 head 库含 1 计划、3 内容版本，升级后全部业务行保持、`foreign_key_check=[]`；末期 FK 检查失败时 schema、版本和全部行回滚 |
| R3 路径编码 | 部分修复，仍阻塞 | 数据目录 `%`／`#`／中文／空格通过；迁移 INI 所在目录含 `%` 仍失败，见 §5.2 |
| R4 持久内容损坏 | 部分修复，仍阻塞 | 已有 `adopted_content` 损坏用例通过；合法 JSON 但非法结构的 `split_baseline` 未检查，导致提交后返回 500 或直接返回／复制非法对象，见 §5.3 |
| R5 锁外结构校验 | 关闭 | 结构解析在加锁前，锁内仍核对当前版本和 ID；额外四类非法结构在独立连接持写锁时均以 422 返回，耗时 0–0.016 秒，版本不变 |
| R6 关键测试漏检 | 关闭 | 内存变异移除 reader 的真实 `BEGIN` 后，列表原用例正确失败；临时库删除唯一索引后，INSERT 原用例正确失败，不再被延迟 FK 掩盖 |
| `date.max` 溢出 | 关闭 | 闭区间末日不再递增越界，单日／两日范围及列表边界测试通过；未添加新的日期范围限制 |

R6 的证据范围：详情用例在移除 `BEGIN` 后仍可通过，因为已读旧指针引用的旧内容不可变；该用例只证明输出版本一致，不能单独证明事务存在。列表用例会出现 `total=1`、`items=2` 并失败，已经提供有效的生产事务回归保护。唯一约束反证会在 INSERT 的 `assertRaises` 处失败；schema 测试同时验证 unique、partial、精确 `(class_id, plan_date)` 列及 `WHERE deleted_at IS NULL`。

### 5.2 R3 遗留（P2）：迁移资源目录中的 `%` 仍破坏启动

位置：[migrate.py](../../backend/app/local/migrate.py) 第 53–56 行，关联 [alembic-local.ini](../../backend/alembic-local.ini) 第 3 行。

`alembic_config()` 仅转义 `script_location` 和数据库 URL。INI 仍有 `prepend_sys_path = %(here)s`，而 `Config` 注入的 `here` 是未转义的 INI 所在路径。Alembic 读取该项时对路径中的 `%` 再次插值，触发 `InterpolationSyntaxError`。Windows 用户名或安装／检出目录合法含 `%` 时，即使数据目录正常也不能启动。

独立补证将原 INI 原样复制到临时特殊目录，仅在验证进程内替换 `ALEMBIC_INI_PATH`，调用实际 `ensure_local_schema()`；不修改迁移源码：

| INI 所在目录 | 空库首次迁移 | 已有 current head 重启 |
| --- | --- | --- |
| `teacher%name` | `LOCAL_DB_MIGRATION_FAILED`，cause 为 `InterpolationSyntaxError` | 直接抛 `InterpolationSyntaxError` |
| `中文 空格%号#目录` | 同上 | 同上 |
| `teacher#name` | 成功，current | 成功，current |

失败前后目录清单相同，未产生旁路文件。本轮没有将此问题描述成数据路径 URI 再次损坏。现有 `test_paths.py` 的三个测试只移动数据目录，包括 CLI 的 `KGM_LOCAL_DATA_DIR`；没有覆盖 INI／迁移资源所在路径。这是首轮 R3 明确要求的未闭合项。

修复要求：补齐实际消费到的配置／资源路径插值边界；以资源配置路径和数据路径分别覆盖首次迁移、正常重启、未知版本拒绝，保留中文／空格／`%`／`#` 与无旁路文件要求。不得只扩大数据目录测试或绕过真实迁移。

### 5.3 R4 遗留（P2）：损坏基准在提交后才触发响应失败

位置：[daily_plan_service.py](../../backend/app/local/daily_plan_service.py) 第 165–176 行的 `_validate_stored_content`，以及第 509 行继承 `current.split_baseline`；响应 [schemas.py](../../backend/app/local/schemas.py) 要求基准为 `dict | None`。

当前共享读取边界只校验 `adopted_content`。读取数据库 JSON 时虽能捕获非法 JSON，但合法 JSON 的基准结构未经校验。D1A 手工内容基准按规格 §5 应为 null；不能将损坏值作为服务器基准继续使用。

在真实临时文件中正常创建 v1，再用 SQL 注入合成故障，通过真实 HTTP 得到：

| 持久 `split_baseline` | GET | PATCH 只修改原文 | PATCH 后实际数据库 |
| --- | --- | --- | --- |
| JSON 数组，含合成正文标记 | 500 `INTERNAL_ERROR` | 500 `INTERNAL_ERROR` | v1→v2，指针改变，内容和该计划审计各 +1，数组复制到新版本 |
| JSON 字符串 | 500 `INTERNAL_ERROR` | 500 `INTERNAL_ERROR` | 同上 |
| `{"bogus":"synthetic-teaching-marker"}` | 200，返回非法对象 | 200 | 同样新增版本并复制非法对象 |

数组／字符串是在 `session.commit()` 之后，FastAPI 校验响应时才失败。调用者收到保存失败，但数据库已经改变，不满足首轮 R4 的“失败保持版本、指针和审计不变”。Uvicorn 的 `ResponseValidationError` 日志还包含完整合成基准原值；只脱敏 HTTP 错误体不足以满足诊断边界。

修复要求：在返回详情及追加版本之前统一检查持久基准，按当前 D1A 契约拒绝损坏值并返回 503 `LOCAL_STORAGE_ERROR`；不得静默清空／修复、依赖响应模型兜底或在提交后改错误码。补 GET、by-date、重复创建打开，以及 PATCH 遗漏内容／只改原文／显式提供合法内容的故障矩阵；逐次验证版本、指针、内容历史和审计均不变，同时检查响应与日志没有合成正文、路径或认证材料。客户端非法输入仍为 422，正常 null 基准继续通过。

本轮还观察到 SQL 注入空白 group/game ID 可被读回和复制，作为持久 ID 校验的补充现象保留在证据中；不把未单独定稿的完整 ID 语法扩为新增阻塞或顺带改变 v1 ID 规则。

### 5.4 独立验证与环境

工作目录 `backend`；设置 `APP_DISABLE_DOTENV=1`、`PYTHONIOENCODING=utf-8`，解释器使用 `-X utf8`。下列为 Codex 实际复跑，不是转述 OpenCode 自测：

| 命令 | 环境 | 结果 |
| --- | --- | --- |
| `%TEMP%/kgm-d1a-py312-venv/Scripts/python.exe -X utf8 -m unittest discover -s tests/local -t . -v` | Python 3.12.10／SQLite 3.49.1 | 84 项，0 skip，exit 0，47.892s |
| `backend/.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests/local -t . -v`（解释器按仓库根定位） | Python 3.14.7／SQLite 3.50.4 | 84 项，0 skip，exit 0，49.520s |
| 主环境 `python -X utf8 -m unittest tests.unit.test_i3_content_validation tests.unit.test_security tests.unit.test_calendar_boundaries tests.unit.test_i3_api_schemas tests.unit.test_i5_export_read_service -v` | Python 3.14.7 | 108 项，0 skip，exit 0，0.467s |

两环境依赖均为 SQLAlchemy 2.0.54、Alembic 1.20.0、FastAPI 0.141.1、Pydantic 2.13.5、chinesecalendar 1.11.0、Uvicorn 0.53.0、Starlette 1.6.0。依赖声明与锁文件 SHA256 和 §3 完全相同；未安装／升级包、下载解释器或重建环境。首轮 3.14／`--frozen` 与原要求的差异仍按历史记录保留。

临时证据目录 `%TEMP%\kgm-d1a-codex-review-20261013\`：

- `local-py312.log`、`local-py314.log`、`regression-v1.log`：完整复跑日志。
- `source-hashes.json`：本轮核查源码／测试／迁移及依赖文件的 SHA256。
- `storage-review.json`：R3 配置路径反例、含历史版本旧库升级、末期 FK 失败回滚及 Windows WAL 竞争补证。WAL 竞争中另一连接提交后，删除受 WinError 32 阻止且数据完整；未据跨平台推测另列当前阻塞。
- `r4-content-summary.json`、`r4-uvicorn-error.log`：R4 HTTP、提交前后实际状态及诊断反例；合成数据库保留于 `%TEMP%\kgm-d1a-codex-r4-recheck-20261013-j71x43_t\data\kindergarten.db`。
- `r5-lock-free-additional.json`：独立写锁下四类非法结构的 422 与版本不变。
- `r6-independent-mutation-summary.json`：仅验证进程内禁用读事务、仅临时库删除索引后的原用例反证及详情测试局限。

临时文件不保证长期留存，关键复现、结果和修复要求已归并到本文。D0、旧 MySQL 集成、GUI／Word／WPS／发行验收未重跑，不用本轮通过数量替代这些边界。

### 5.5 能否进入 D1B

**不能进入 D1B 编码。** 先由 OpenCode 定点修复 R3／R4 并更新同一实施结果，再由 Codex 复审；当前提示词已收敛为这两项，不重做已通过项目。

D1B 配置维护规格整理可以继续，但这不是技术放行或实现授权。即使后续 D1A 通过，仍须先收敛资料与班级／学期维护、已有计划访问编辑范围、多学期上下文和按日期解析、日历修订／例外及宿主接口，再交 OpenCode 编码；必要产品选择由用户决定。离开自动保存、失败留页、409 保留输入、导出数据库已保存版本及原生保存结果区分均已确认，不重复询问。之后另做真实 Windows 业务验收，D1A 通过不等于完整 D1 或发行完成。

## 6. R3／R4 收口复审与运行时验证阻塞（2026-10-13）

本节记录版本统一核查前的复审；测试通过／失败和原生异常事实继续有效，原先将 3.12 恢复设为唯一准入门槛的结论由 §7 替代。

### 6.1 代码审阅结论

依据 [实施结果 §10](desktop-d1-result.md#10-r3r4-第三轮定点修复2026-10-13) 及实际工作区，**R3、R4 可以关闭，没有发现本轮新增的阻塞性代码问题**。R1／R2／R5／R6 与日期边界的上轮结论保留。对照 §5 的源码散列，变化为 `migrate.py`、`daily_plan_service.py`、`test_paths.py`、`test_daily_plans.py`、`support.py`，另核对 `alembic-local.ini`；没有把整个既有未提交工作区当成本轮改动。

使用 codebase-memory Verify 层级，项目同 §5，generation `2026-10-13T11:42:36Z`、ready。相关精确路径覆盖仍提示 `metadata_changed`，已回读实际源码与测试；不声称全仓图覆盖。两项独立只读子审阅及根侧复跑均不修改实现、测试、迁移或构建脚本。

| 项目 | 独立复核结果 |
| --- | --- |
| R3 迁移配置／资源路径 | INI 不再依赖 `%(here)s`；程序入口对 `script_location`、`prepend_sys_path` 使用绝对转义路径。3 类特殊资源目录 × 2 类数据目录 × 程序／CLI，共 12 个组合通过首次迁移、重启和未知版本拒绝 |
| R3 资源来源与文件保留 | 程序探针从无关 cwd 的独立子进程实际导入复制资源中的 `migrate`，以模块路径与哨兵 head 双重确认资源来源；未知版本拒绝前后数据库 SHA256 和目录条目完全一致 |
| R4 基准读取与保存 | 非法 JSON、数组、字符串、非法对象、`false`、`0`、`{}` 共 7 类故障 × GET／by-date／重复打开／三类 PATCH，共 42 次请求均为 503 `LOCAL_STORAGE_ERROR`；每次比较计划头、内容历史和审计完整行，全部不变 |
| R4 输入与正常流程 | 7 次非法客户端输入仍为 422；合法 null 基准计划可读取、重复打开及保存 v1→v2，损坏邻接记录没有被修复或复制 |
| R4 诊断 | 捕获器自检有效；独立请求的日志中无合成正文、路径、token 或 `ResponseValidationError`，原提交后 500 及日志泄漏反例不再出现 |

CLI 的当前支持方式为在 `backend` 目录执行 `python -m alembic -c alembic-local.ini upgrade head`。现有契约没有任意 cwd 的 CLI 承诺，故不据此新增阻塞；程序入口已在无关 cwd 验证。打包后的资源定位仍需在对应桌面阶段实测，本次不以源码目录验证替代发行验证。严格 null 基准只适用于当前 D1A 手工契约，未来 AI 基准须按后续规格实施。

### 6.2 实际测试结果：保留失败，不能写成两套均通过

工作目录 `backend`；`APP_DISABLE_DOTENV=1`、`PYTHONIOENCODING=utf-8`、解释器 `-X utf8`。所有环境沿用现有安装，未重建、安装或修改配置。

| 验证 | 命令／方式 | 结果 |
| --- | --- | --- |
| Python 3.14.7／SQLite 3.50.4 全套 | `backend/.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests/local -t . -v`（解释器按仓库根定位） | 87 项，0 skip，exit 0，66.041s |
| 相关既有回归，Python 3.14.7 | `python -X utf8 -m unittest tests.unit.test_i3_content_validation tests.unit.test_security tests.unit.test_calendar_boundaries tests.unit.test_i3_api_schemas tests.unit.test_i5_export_read_service -v` | 108 项，0 skip，exit 0，0.781s |
| Python 3.12.10／SQLite 3.49.1 全套 | `%TEMP%/kgm-d1a-py312-venv/Scripts/python.exe -X utf8 -m unittest discover -s tests/local -t . -v` | 87 项，0 skip，3 failures，exit 1，145.119s |
| 3.12 CLI 单项串行重跑 | 原 `test_cli_migration_from_special_resource_path` 用例 | 主进程未输出 unittest 信息即原生退出 `-1073740022`，日志为空，不能记作测试通过 |
| 3.12 三项串行重跑 | 详情快照、CLI 特殊资源路径、进程重启三个原用例 | 3 tests／4 failures（CLI 三个子用例及重启），exit 1，26.959s；详情快照此轮通过 |

3.12 全套失败细节：详情快照等待 `detail-first.json` 超时；CLI 中文特殊路径子进程与重启 worker 均返回 `3221227274`，stdout／stderr 为空。后续串行重跑同样失败，不能归因于并行运行，也不是原 `InterpolationSyntaxError` 的再次出现。

两环境依赖仍为 SQLAlchemy 2.0.54、Alembic 1.20.0、FastAPI 0.141.1、Pydantic 2.13.5、chinesecalendar 1.11.0、Uvicorn 0.53.0、Starlette 1.6.0；`pyproject.toml`／`uv.lock` SHA256 与 §3 相同。初次实施 3.14／`--frozen` 的历史差异继续保留，不因本轮验证改变记录。

### 6.3 原生异常的已知事实与未定位部分

本机 `certutil -error 0xc000070a` 将退出码识别为 `STATUS_THREADPOOL_HANDLE_EXCEPTION`；`3221227274` 和有符号 `-1073740022` 均是该码。Windows Application 日志记录了 Python 3.12.10／`ntdll.dll` 的匹配崩溃。具体根因尚未确定，不据异常模块名断言 Windows、某个依赖或并行负载有缺陷。

为区分项目逻辑与运行时问题，执行了两组限定探针，均由 Python 3.14 父进程在 TEMP 目录串行启动子进程，不导入本仓库模块：

- 3.12 虚拟环境与其基解释器分别执行 `-I -S -c 'print(...)'`，共 8 次均成功；此前三次普通版本／SQLite 启动检查也成功。解释器文件存在，不是缺少环境。
- 3.12 虚拟环境执行 `-I -c 'import sqlalchemy,alembic,fastapi; print(...)'`，6 次中 **5 次以相同原生码退出且无 stdout／stderr**，1 次成功。`-I` 隔离环境路径与用户 site，探针没有业务请求、迁移、数据库或项目代码。
- 随后分别单独导入三者各 2 次：SQLAlchemy 为 1 成功／1 次同码失败，Alembic 两次同码失败，FastAPI 两次成功。这只缩小复现路径，不能据此确定哪个依赖或底层组件是根因。

这说明同类失败可以独立于 D1A 实现复现；当前应处理目标解释器／已安装依赖／本机运行环境的验证问题，不再要求 OpenCode 重写已关闭的 R3／R4。最小启动成功不等于依赖加载或真实进程测试通过。未修改依赖、系统配置、安全设置，未安装替代解释器，也未通过跳过失败用例或更换目标版本消除门槛。

### 6.4 证据与接续

本轮证据目录 `%TEMP%\kgm-d1a-codex-review-20261013-r3r4\`，与 §5 目录分开保存，未覆盖前轮失败证据：

- `source-hashes.json`：本轮源码、迁移、测试、INI 和依赖文件散列。
- `local-py314.log`、`regression-v1.log`：通过日志；`local-py312.log`、`r3-cli-single-rerun.log`、`py312-targeted-rerun.log`：失败及重跑日志。
- `r3-independent.json`：12 个独立资源／数据／入口组合、模块来源、哨兵 head、拒绝前后文件散列与目录。
- `r4-independent-matrix.json`、`r4-independent-server.log`：42 次故障请求、7 次非法输入、完整业务行比对、正常 null 流程与诊断结果；合成库位于 `%TEMP%\kgm-d1a-codex-r4-final-wxwks_ky\data\kindergarten.db`。
- `python312-native-crashes.json`、`python312-minimal-startup.json`、`python312-dependency-startup.json`：匹配原生崩溃事件及不导入项目代码的启动／依赖探针。
- `python312-individual-imports.json`：三种依赖分别导入的有界定位结果。

临时证据不保证长期留存，核心事实已归并到本文。当时的提示词已停止派发 R3／R4 修复，改为 Python 3.12 验证问题定点核查；现在的[当前任务](../tasks/current.md)已按 §7 接续。原分工及诊断边界保留：Codex 负责技术核查和执行验证；若定位出需要修改项目代码／测试／脚本的具体问题，再形成有证据的任务交 OpenCode。任何环境变更须匹配有效授权，不先重建环境或改锁掩盖问题。

**当时的 D1B 判断（已由 §7 调整）：代码审阅条件已满足，但 D1A 最终工程验证尚未放行，暂不进入 D1B 编码。** 待目标解释器恢复稳定后，先重跑失败用例，再完整复跑本地套件；得到有效通过证据后关闭该验证阻塞。D1B 配置维护和工程接口规格可以整理，仍需按 §5.5 收敛后交实现；不自动启动 D1B、GUI／Word／WPS 或发行验收。

## 7. 版本统一与 D1A 放行（2026-10-13）

用户要求先核查 Python 3.15、确定统一版本后重新判断 D1B。官方兼容矩阵、本机元数据及解析结果见[技术核查 §7](desktop-d1-technical-review.md#7-python-版本统一核查2026-10-13)。本节调整当前准入条件，不改写 §6 的失败记录和最初 3.14／`--frozen` 与旧环境约定不一致的事实。

### 7.1 版本决定及证据

- **D1 统一目标为 CPython 3.14.7、Windows x64、标准 GIL**，覆盖后端开发、桌面宿主与打包。后端已在此环境，桌面仍为 3.12，环境落实与新包验证尚未完成。
- Python 3.15 已正式发布，现有 pythonnet 3.2.1 与 PyInstaller 6.22.3 也支持它。未选 3.15 的具体原因是后端锁定 Pydantic 2.13.5／core 2.46.5 缺少受支持的 3.15 制品路径，切换需要升级并重新验证，不能直接沿用现有锁的通过结论。
- 本轮只做元数据核查及依赖解析。`uv pip check` 在 3.14.7 环境检查 26 包，exit 0；固定 core 2.46.5、Windows x64 且只允许 wheel 的解析，3.14 exit 0、3.15 exit 1。没有安装或启动 3.15、编译源码、重建环境或打包。
- 与 §6 的 38 项源码／测试／迁移／依赖散列相比无变化。沿用 §6 的 3.14.7 全套 87 项本地测试与 108 项相关回归通过；本轮没有重新运行全套，不把历史通过虚报为新增测试。

### 7.2 当前准入结论

| 范围 | 结论 |
| --- | --- |
| D1A 本地数据与手工日计划 API | **工程通过**。R1–R6 全部关闭，所选 3.14.7 基线的完整验证已通过 |
| D1B 规格收敛 | **可以进入**。不要求先修复历史 3.12 环境，也不重复派发 R3／R4 |
| D1B 完整编码 | **尚不能直接开始**。配置维护产品范围和工程接口尚未定稿，见 D1 规格 §7；须形成明确实现任务再交 OpenCode |
| 统一桌面环境与打包 | 版本方向已定，实际落实待执行；两份旧锁有业务依赖版本差异，不能拼接或把 D0 锁直接用于 D1 |
| D1 产品／发行 | 未验收；真实业务页面、离开保存、原生保存、Word 全页与目标环境验证仍需对应证据 |

3.12 的 `0xC000070A`、无项目代码依赖导入复现和未知根因继续保留。原定点诊断的非破坏性边界也保留：不得由异常模块名推定根因，不通过跳过进程用例、重试至偶然通过或改锁掩盖失败。今后若再把 3.12 列入支持范围，必须另行解决并复验；本轮不再把它列为 D1 的统一目标。

后续由 Codex 收敛 D1B 规格及 3.14.7 环境落实方案，必要产品选择由用户决定；OpenCode 唯一写入实现、依赖／版本配置、测试、迁移与构建脚本。环境切换后须实测真实 WebView2、回调、关闭、原生保存及仓外目录包，不以 D1A 通过替代。当前任务中的旧诊断独有事实与限制已归并 §6–7，提示词更新为 D1B 准备，保持单一入口。

## 8. D1B 规格准备核查（2026-10-14）

本轮按当时 `docs/tasks/current.md` 执行设计文档与必要只读核查，未写入实现代码、测试、迁移、依赖／版本文件或构建脚本。没有安装、切换环境、构建、运行业务测试／GUI、访问教师库、读取真实 `.env`／密钥、连接旧 MySQL／远程环境或调用 AI。保留原分支及全部既有未提交／未跟踪资料，不暂存、提交、推送或派发其他聊天的实现任务。

### 8.1 产品决定与已有规则

先核对 D1 规格、三个模块 Contract、ADR 0004 及 I2／I3 的非冲突决定。稳定 ID、年级集合、学期不重叠、创建时四项快照、园所后补、例外优先、影响预览及离开保存等均有依据，未重复提问。只集中询问两项范围，用户明确选择：

1. D1B 维护当前班级名称和年级，支持同班升班；新增班级及多班切换后置。
2. D1B 支持学期新增、修改和切换；旧学期、调整后移出范围或改为停课日的已有计划继续编辑、导出。

决定归入 [D1 规格 §9](../specs/desktop-manual-daily-plan.md#9-d1b-产品范围收敛2026-10-14)，并同步身份、日计划及 Word Contract。没有剩余产品问题。学期切换确定为视图筛选；计划原归属、周次、创建日历修订及四项表头保护继续生效。旧学期当前内容访问不等于内容版本浏览／恢复能力开放。没有引入多班、周业务、AI、WebDAV 或发行范围。

### 8.2 源码依据与限定覆盖

使用已安装的 codebase-memory Verify 层级；project=`C-Users-yw980-code-kindergarten-manager-next`，generation=`2026-10-13T11:42:36Z`，ready。已完成相关 search_graph 分页、`load_context` 双向直接调用查询及 `_resolve_create_date` 片段核对。候选路径检查 `check_index_coverage`，源文件普遍 `metadata_changed`，声明／锁部分 not_tracked，不能把无记录解析错误当作实时完整覆盖；已针对引用文件回读源码。图范围只限本地上下文／日计划、真实表单、Word 与桌面宿主／构建；已知 .venv／__pycache__ 排除不用于项目完整性判断。未重建索引或重做全仓审计。

| 具体证据 | D1B 必须落实的增量 |
| --- | --- |
| [profile_service.load_context](../../backend/app/local/profile_service.py) 明确拒绝多学期；`_resolve_create_date` 还与 context.term 比较 | context 可含多个学期、按目标日期解析，学期外 ready 不丢档案；不得用浏览选中的学期限制保存 |
| [calendar_read.explain_range](../../backend/app/local/calendar_read.py) 的学期外分支固定 existing_plan_id=None；[日计划服务](../../backend/app/local/daily_plan_service.py) 按当前班级取已有记录 | 学期外也返回已有入口，旧学期列表按持久 term_id，不按新范围隐藏；新建仍先打开同班同日记录 |
| [local models](../../backend/app/local/models.py) 已有日历 override 字段及复合 FK，但无配置版本／成功回执；[api/schemas](../../backend/app/local/api.py) 为 D1A 契约 | 新增配置预览／应用及回执、全局配置版本、局部迁移；按短读候选／短写重查原子提交，旧计划不重写 |
| [DailyPlanView.vue](../../frontend/src/views/DailyPlanView.vue) 的 applyPlan 全量覆盖，save 返回 void；[内容映射](../../frontend/src/daily-plan-content.ts) 已有真实栏目和 ID 映射 | 独立 D1 入口、明确 save 结果、正规化 dirty 基线和晚到输入保护；剥离旧账号／管理员／周摘要 |
| [d0_main.py](../../desktop/d0_main.py) 当前没有日计划离开握手；已安装 pywebview closing 是可取消的同步回调 | 先否决关闭，异步页面保存，带请求 ID 的完成／取消／查询协议；超时和销毁失败不能锁死页面或留下旧关闭许可 |
| [export_read_service.py](../../backend/app/services/export_read_service.py) 已有完整确认事实算法但导入旧模型；[exports.py](../../backend/app/routers/exports.py) 旧流程读后生成再同 Session 写审计 | 本地读取适配，显式短读事务物化 DTO；生成和对话框在事务外，审计另短写；确认对象任何变化重新确认 |
| [d0_host_api.py](../../desktop/d0_host_api.py) 已有受限保存、临时写／替换和 30MiB 校验 | 保留原生能力，增加操作 ID／载荷绑定与只读结果查询；取消／失败／结果不明／真实成功分开，不暴露夹具任意路径接口 |

源码观察证明需要适配，不证明适配已完成。D0 已安装 pywebview 的事件语义只用于协议设计，不能替代 3.14.7 真实窗口测试。配置扩围沿用原 I2 的“当前范围交集保留、新纳入日期重新取库默认”规则，未把保留历史修订解释为自动恢复旧例外。

### 8.3 工程方案、交叉审阅与未执行项

- [规格 §10–12](../specs/desktop-manual-daily-plan.md) 已给出 context／旧学期列表、配置请求响应／版本／幂等／事务／错误、日历修订、页面状态、dirty 与重复离开、关闭握手、Word 范围／完整确认／原生结果。
- 交叉审阅修正了无变化预览令牌与回执的不一致、关闭超时后冻结、显式冲突重提的失效组 ID、扩围旧例外误恢复、错误 details 穿透、原生保存同 key 异载荷及原子替换提交点表述；这些均属工程补全，无需重新询问产品。
- [技术核查 §8](desktop-d1-technical-review.md#8-d1-统一运行时准备方案2026-10-14) 固定现成 `C:\Python314\python.exe`、独立 `desktop/.venv-d1`、backend 26 包版本约束、单一 D1 安装锁及具体命令。保留 D0 环境／旧包，不直接拼锁或升级业务包。proxy-tools 唯一源码制品例外及固定构建工具已明确，仍未实装验证。
- 本轮核对了解释器／工具元数据与命令帮助；运行时文档 6 个 PowerShell 代码块及 Python 比对片段做了静态语法检查；10 份本轮涉及文档的相对链接／标题锚点和代码围栏直接检查通过（包含尚未跟踪文件，不以 git diff 检查代替）。未求解 D1 新锁、安装、测试、启动 GUI 或构建；87／108 项通过属于 §6–7 的原证据，未重复声称新增通过。
- [规格 §13](../specs/desktop-manual-daily-plan.md#13-opencode-工作项验证与准入) 划分 B0–B5 文件、前置、接口及验证矩阵；原 D1A 回归与 D1B 新验证分别记录。真实 Windows 关闭／保存、目录包仓外运行和 Word 全页为后续门槛，不以静态方案替代。

### 8.4 准入判断与交接

| 范围 | 当前结论 |
| --- | --- |
| D1B 产品与工程规格 | **准备完成，可交 OpenCode 形成明确实施任务**；无未答产品问题，已知工程边界见规格 §9–13 |
| 运行时准备设计 | **方案完成、执行未开始**；新组合是否可解、是否稳定运行仍须执行命令和门槛后判断 |
| OpenCode 实施授权 | 本轮用户授权止于设计和只读核查；本次不开始或派发编码／安装。后续明确实施任务后由 OpenCode 唯一写入实现 |
| D1A | 3.14.7 基线工程通过不变，3.12 原生异常保留，不重新派发已关闭 R1–R6 |
| D1B、D1 产品与发行 | 未实施／未验收；干净机器、Win10、WPS、其他 DPI 及用户体验各自未验身份保留 |

原准备提示词中的独有决定、未验项与约束已归并规格 §9–13、技术核查 §8 及本节；[current.md](../tasks/current.md)更新为单一接续入口，不另留提示词版本副本。后续实施顺序为 B0 环境与 B1 配置核心，继而 B2 页面、B3 离开宿主、B4 Word、B5 新包；任何一步失败按原事实记录，不扩大到远程操作或发行。

## 9. D1B 实施复审（2026-10-15）

### 9.1 结论、范围与证据方法

**不放行 D1B。** B0 统一环境已有实际证据，B1–B5 已有实现、自测与仓外包运行记录，但下列正常交互和错误状态仍违反已确认契约，不能仅凭现有测试通过进入 D2。修复项均是现有规格落实问题，本轮没有新增产品决定，也无需重问班级／学期范围。

- 审阅范围：本地配置／多学期／迁移与导出服务、D1 Vue 页面及保存／关闭协调器、D1 宿主／原生保存、D1 依赖与构建产物；保留工作区既有修改和未跟踪文件，没有把整个工作区当作本轮差异。
- 读取 codebase-memory 技能后确认图工具当前不可用，采用限定源码读取和独立交叉审阅；不声称图覆盖或全仓审计。
- 后端反例使用真实 Uvicorn HTTP、临时文件 SQLite 与现有确定性日历夹具。前端反例在内存转译实际组件脚本，使用真实 Vue refs/watch 和受控 API／桥接；不是 DOM 或真实 WebView2 操作。宿主反例使用真实桥接分派、线程屏障、受控窗口／计时器及临时落盘，不销毁真实窗口。
- Codex 仅执行核查、现有测试和临时探针，更新文档；未改实现、测试、迁移、构建脚本，未安装、重建包、提交或推送。未使用真实教师数据、旧远程资源或付费 AI。
- 临时证据根：`%TEMP%\kgm-d1b-codex-review-20261015-503e4977`。包含源码散列、测试日志，以及 `backend-review-probes.py/.json`、`frontend-review-probes.cjs/.json`、`host-review-probes.json/.txt`。临时文件不保证长期留存，复现和结论如下保留。
- 收尾核对：11份本轮相关文档的214个相对链接／锚点与代码围栏检查通过；90个实现／测试／构建及依赖文件复核散列均未变化。`git diff --check`无空白错误（仅既有换行转换提示），同时直接检查未跟踪文档，不以Git可见范围代替完整检查。

### 9.2 自动检查及包身份

检查使用 `desktop/.venv-d1/Scripts/python.exe`（CPython 3.14.7／Windows x64／标准 GIL，SQLite 3.50.4）；Python 带 `-X utf8`，禁用 `.env`、设置 UTF-8 输出。数据库由每个现有测试显式指向其临时目录；定点探针使用独立临时合成库。

| 项目 | 本轮独立结果 |
| --- | --- |
| 完整本地套件，cwd backend，`-m unittest discover -s tests/local -t . -v` | 修正测试启动环境后 129 项，0 skip，exit 0（117.607s）；首次调用问题单独保留 |
| 指定回归，`tests.unit.test_i3_content_validation`、`test_security`、`test_calendar_boundaries`、`test_i3_api_schemas`、`test_i5_export_read_service` | 108 项，0 skip，exit 0 |
| `-m pytest desktop/tests -q -p no:cacheprovider` | 116 passed，exit 0；2 项依赖弃用警告，无失败 |
| `npm.cmd run typecheck`、`npm.cmd run test:d1` | 均 exit 0；后者为纯逻辑检查，不能替代组件异步状态验证 |
| 后端／前端反例探针 | 各 exit 0，成功复现下列缺陷；此处 exit 0 表示探针完成，不表示产品通过 |
| D1 运行时、业务锁 | backend 声明／锁散列与实施记录一致；26 项业务依赖和 46 项已安装依赖无版本差异；`uv pip check` 通过 |
| 包清单与宿主源码身份 | 仓内外各 137 文件均匹配原 `package-hashes.json`，无缺失、修改或额外文件；归档中 d1_main／d1_host_api／d1_paths／d1_server 与当前源码编译结果等价 |

包 EXE SHA-256 为 `5ad0dd1dff1f12d30faf34e43eca77c18198fb918554c7457ad26980711a9427`。本轮未重建或启动包，不将包身份一致解释为本轮重新通过 GUI；也未将四个宿主模块的一致性扩大成所有前端源文件与构建资产的独立对应证明。

首次完整本地测试运行了 129 项，exit 1，报告 5 处失败（含同一用例的子场景）。原因是 Codex 父会话额外注入 `KGM_LOCAL_DB_PATH`，覆盖 CLI 迁移测试自身设置的 `KGM_LOCAL_DATA_DIR`，指向尚不存在的审阅子目录，报 `unable to open database file`。核对 `test_migrations.py:666`、`test_paths.py:273` 后，取消这个父级 DB 路径覆盖，仍由测试自身强制临时路径并保留临时数据根兜底；不修改代码、不禁用用例。原失败日志 `local-tests.log` 保留，修正调用环境后的日志为 `local-tests-isolated.log`。不把该调用失误计为产品缺陷，也不隐去首次失败。

### 9.3 必须修复的发现

以下行号对应本次源码快照。D1B-R 编号独立于已关闭的 D1A R1–R6。P1 优先保护输入／在途文件操作，P2 为功能或协议错误，P3 为非法输入错误分类；全部进入此次定点修复，不通过改规格适配现状。

| 编号／级别 | 位置与确定的触发条件 | 后果与修复验收 |
| --- | --- | --- |
| **D1B-R1 / P1** 关闭冻结过晚、未知状态误解锁 | `frontend/src/d1/App.vue:180` 在等待 `complete_close(allow:true)` 后才冻结；`bridge.ts:152` 查询失败按 stay 处理。探针经过 Vue nextTick 仍 `locked=false`；宿主为 closing、回包及三次查询失败时得到 stay | 宿主先销毁再回包，许可发出后仍可输入，存在最后输入丢失窗口。完成 IME／保存及 clean 复核后，**发许可前冻结**；查询失败、未收到答复或仍 pending 时保留冻结和 ID；宿主对该 ID 明确返回 canceled/unknown 时按 §11.3 留页解锁，不能把通信失败等同于明确 unknown，也不能用迟到响应覆盖已确认 closing；补失联、迟到取消与最终 closing 测试 |
| **D1B-R2 / P2** 未决内容保存被离开操作重发 | `views/EditorView.vue:241` 的 saveCurrent 未检查 indeterminate。手动 PATCH 传输失败后请求关闭，探针 `patchCalls=2` | 与“结果待核对”承诺不符。未决状态普通离开不得发新 PATCH；只核对原提交，或经现有显式重试入口处理。保留版本冲突保护，不以无条件重发代替结果核对 |
| **D1B-R3 / P1** 配置应用丢弃其他草稿 | `views/SettingsView.vue:269` 设置全量重置标记，`:135` context 更新覆盖全部表单。同时改姓名和班名、仅应用姓名后，班名恢复旧值且 draftActive=false | 未确认内容静默丢失。仅合并本次已应用字段的基线，保留其他草稿及应用期间的新输入；或在提交期间正确限制受影响输入，但不能清掉已有无关草稿。补多区草稿与迟到 context 用例 |
| **D1B-R4 / P2** 迟到预览恢复旧确认 | `views/SettingsView.vue:175` 异步响应无输入版本／请求序号复核。请求 A 的预览时改成 B，返回后 `form=B, preview=A, token=old-token` | 仍可应用旧 A。预览必须绑定当前规范化输入和配置版本；改变输入、取消、context 变化或离开使旧响应失效；确认前再次校验绑定 |
| **D1B-R5 / P2** 设置页返回按钮路由错误 | `App.vue:353` 将 SettingsView 的 leave 固定绑定为 settings；`:145` 再次进入设置。无草稿触发“返回工作台”仍 `view=settings` | 正常返回不可用。绑定到工作台导航，同时保留未确认草稿阻止离开的规则；用实际组件事件验证 |
| **D1B-R6 / P1** 导出 busy 未覆盖原生未决操作 | `views/ExportDialog.vue:269` 在 pending/unknown 后清 busy；`:517` 可用新 ID 重试。反例 `phase=save_result_unknown,busy=false`。另在生成中切范围后旧响应失效，却留下 `busy=true` | 在途保存可失去跟踪、允许再保存或关窗；反向分支则卡住后续导出。区分 HTTP 生成与原生保存状态，pending/unknown 保留 ID 与互斥，只读核对，unknown 经明确文件核对后才允许新操作；范围改变应安全结束旧生成，不得开旧对话框。冻结原生阶段的范围／导航，处理 base64 转换等异步边界 |
| **D1B-R7 / P2** 有计划学期改名／无变化预览 500 | `backend/app/local/config_service.py:718` 对 rename-only/no-op 的 revision=None 断言失败。9 月学期创建 9/1 计划后，仅改名称或原值预览均 500 INTERNAL_ERROR | 受支持的普通维护被阻断。无新修订时以现有解释计算影响，改名不生成日历修订；无变化回执语义保持。现有改名测试只覆盖无计划情况，需补有计划场景 |
| **D1B-R8 / P2** 合法跨学期范围调整误报损坏 | `config_service.py:862` 遍历旧新范围包围区间，`:316` 只载入目标学期日期。已有 9 月、10 月学期，将 9 月整体移至不重叠的 11 月，即使无计划也 503 | 不应把中间另一个合法学期误当缺行。按实际影响日期／所属修订完整加载，或缩小比较集合；保留闭区间不重叠规则，补中间学期与旧归属计划的组合；中间未改变的学期不得产生虚假日期差异或计划影响 |
| **D1B-R9 / P2** 发布不完整日历修订 | `config_service.py:566` 例外候选直接克隆现存行，不检查范围完整。临时库删除当前修订 9/10，给 9/5 配例外，preview/apply 均 200，新修订仍 29 行，读取 9/10 才 503 | 损坏快照被继续发布。缺行应在预览／应用复核时作为存储错误拒绝，配置版本、指针、修订、日志和成功回执均不得新增；新修订必须完整，不能以库默认值静默补损坏交集 |
| **D1B-R10 / P3** Unicode 非法令牌返回内部错误 | `backend/app/local/config_tokens.py:103` ASCII 编码／摘要比较未转换异常。`中文.abcd`、`e30.中文` 为 500；ASCII 非法对照为 422 | 对非法令牌统一可预期校验错误，覆盖 body、signature 与格式，不泄漏异常，不放宽有效令牌检查 |
| **D1B-R11 / P2** 宿主不同 ID 可同时保存 | `desktop/d1_host_api.py:425` 在进入原生保存前释放 ID 表锁，没有全局单操作保护。两个不同 ID 的线程屏障证明同时两次 create_file_dialog | 与 R6 组合可打开第二个保存对话框；宿主关闭也不检查在途保存。保证跨 ID 全局互斥和在途操作的关闭保护，同 ID 继续共用原结果；不能只修前端按钮 |
| **D1B-R12 / P2** 受限桥暴露内部对象且绕过握手 | `d1_host_api.py:287` 的公开 close_coordinator 被真实 pywebview 递归暴露；实际 js_bridge_call 在未 ready 时调用 `.complete(id,true)`，绕过正常 complete_close 的拒绝并触发模拟 destroy。`:341` 的 save_docx 同样未检查 ready | 暴露的业务桥必须只含约定入口；内部协调器／通知函数不能递归暴露，保存等业务入口必须验证有效握手。补实际桥导出清单和分派测试；这是边界缺口，不声称已发现 XSS |
| **D1B-R13 / P2** 非 DOCX 被报告保存成功 | `d1_host_api.py:387` 仅检查 PK 前缀。20 字节 `PK-not-a-zip-or-docx` 实际写盘且返回 saved；现有单测也使用假 PK 数据 | 按 §12.3 在替换提交点前校验有效非空 DOCX／字节，拒绝损坏 ZIP 或缺必要 Word 部件；使用真实最小 DOCX 作为成功样本。非法输入不得覆盖旧目标；保留 30 MiB、严格 base64 与提交后 unknown 语义 |
| **D1B-R14 / P2** 旧关闭定时器取消新请求 | `d1_host_api.py:119` 的超时回调没有绑定请求 ID。A 被否决后建立 B，再运行已开始但滞后的 A 回调，B 立即 canceled | timer.cancel 不能阻止已开始回调。回调持锁复核所绑定 ID／状态，只取消自身尚未放行的请求；补 A/B 交错、迟到 ack 和最终 closing 不超时解锁场景 |

本地导出的实际选取、完整确认上下文及显式读事务物化链路未发现本轮可确定的新阻塞，相关 11 项现有导出测试仍纳入完整套件；这不替代上述前端／宿主修复或真实 Word 版式验证。

### 9.4 已有证据的通过范围与未验

| 层次 | 当前可确认的范围 | 尚不能宣称通过的范围 |
| --- | --- | --- |
| B0／依赖 | 3.14.7 统一环境、业务锁保持及依赖检查 | 不需要重开选型、安装另一套环境或切 3.15 |
| B1–B4 实现与自动检查 | 有实际实现与自动检查，本轮定点反例有直接证据 | R1–R14 未关闭，工程未放行；纯 helper 通过不代表页面异步行为正确 |
| B5 包 | 原实施记录有 4 个真实 WebView2 进程及持久化，当前包身份核对一致 | 本轮未重新启动；原流程用了预授权保存目录，不能作为原生另存为手动输入、取消、占用／解除后重试通过证据 |
| Word | 原实施记录中 4 份实际样本被 Word 16 打开并计为 2／2／5／3 页 | 页数／文字数不是页面视图逐页检查；全页版式仍未验 |
| GUI 矩阵 | 原包正常路径与 dirty close 有部分记录 | 完整离开动作、写锁／409、IME／晚到输入、关闭失联及原生未决保存等不能用模拟探针替代真实 WebView2 补验 |
| 产品／发行 | D0 和 D1A 的历史范围保持 | D1 产品未验收；干净机器、Win10、WPS、其他 DPI、多显示器及用户体验仍各自未验，未获发行结论 |

### 9.5 下一步与任务归并

1. **先由 OpenCode 定点修复 R1–R14。** 优先关闭／草稿／导出数据保护，其次配置与日历功能、受限桥和错误分类。每个反例转成能覆盖实际协调器或组件异步状态的回归，不只重复实现断言；不得把取消所有编辑、冻结历史维护、导出前强制保存等当修复。
2. **自动检查通过后补当前开发机真实交互。** 用合成库完成完整表单、正常离开、写锁失败、409 显式重提、IME／晚到输入、关闭超时和失联、原生保存／取消／占用后重试；结果分自动与真实 GUI 记录。
3. **修复后的源码重新形成 D1 目录包并核对身份。** 沿用同一 3.14.7 环境，保留旧包与原失败证据，仓外不同 cwd 三进程持久化和退出检查；实际导出的空／代表性／长内容／多份 Word 在 Word 页面视图逐页补验。没有完成的项目明确列出，不用旧包或页数充当通过。
4. **复审收口后再进行教师本人体验，继而准备 D2 AI 闭环规格。** D2 要落实本地 AI 设置／凭据、任务状态、失败和结果不明、关闭／休眠与内容保护，再授权实施及实际供应商验证。当前不启动 AI、观察记录、WebDAV 或发行工作。

原 B0–B5 提示词的产品决定与工程契约已由规格 §9–13、技术核查 §8、实施结果 §11及本节承接；安装历史、首次失败、包样本与未验边界保持可追溯。[current.md](../tasks/current.md)替换为单一修复／补验任务，不新增旧提示词副本。Codex 本轮准备交接文档，不代写修复、不跨聊天派发。


## 10. D1B 修复后复审（2026-10-15）

### 10.1 结论与本轮边界

**仍不放行 D1B。** 对照实施结果 §12复审后，原14项中10项关闭，4项保留；另新增D1B-R15。下一轮只修复剩余范围并补验，不重开已关闭问题、运行时选型或已确认产品决定。

本轮读写边界：Codex只读取实现、执行既有测试／临时探针和更新文档；未写实现、测试、迁移或构建脚本，未安装依赖、重建桌面包或操作真实教师数据。为核对当前源码与包内资产，前端构建输出到独立临时目录，未覆盖原构建或包。图工具仍不可用，依据已读codebase-memory技能做限定源码回读和交叉审阅，不声称全仓覆盖。

相较上轮留存源码散列，本轮范围内15个实现／测试文件新增或变化（含新增组件回归脚本）；原导出读取服务、迁移、D1构建脚本和依赖锁未变化。当前分支仍为 `codex/desktop-v2-foundation`，HEAD仍为 `b3c5bbf`，未提交工作区和未跟踪资料均保留。

证据根：`%TEMP%\kgm-d1b-review2-20261015-0aaebddb`。后台测试日志、`backend-review2-probes.*`、`frontend-review-probes.*`、`host-review2-probes.json`、`host-review2-package.json`、`host-review2-ui-close-source.txt`和`existing-evidence-check.json`分别记录复跑、反例、包及原始交付证据核对。临时路径不保证长期留存，关键触发与结论保留如下。

收尾检查：11份相关文档的216个相对链接／锚点和代码围栏有效，91个实现／测试／构建／依赖文件本轮前后散列不变。按仓库现有换行配置执行`git diff --check`为exit 0，仅有换行转换提示；未将未跟踪文档排除在直接检查之外。

### 10.2 原问题关闭矩阵

“关闭”仅指该问题的实现与直接相关回归已满足，不等于整个模块、真实GUI矩阵或产品验收通过。

| 原项 | 结论 | 本轮直接依据 |
| --- | --- | --- |
| R1 关闭冻结／未决状态 | **部分修复，未关闭** | 发许可前已冻结；pending／查询失联不再直接解锁，明确canceled/unknown分开处理。但取消通知先到、迟到closing回包仍可污染终态，且关闭冻结未覆盖设置／工作台，见§10.3 |
| R2 未决PATCH重发 | **关闭** | `EditorView.vue:241`保存入口新增indeterminate守卫；组件回归确认普通离开不增加PATCH，仍通过明确核对／冲突流程继续 |
| R3 配置草稿丢失 | **关闭** | 按pendingAppliedMerge逐字段更新已提交基线，保留其他区域草稿和应用期间的新输入；实际组件回归和原包回归记录支持 |
| R4 迟到配置预览 | **关闭** | 输入序号、配置版本、changeStillBound同时约束响应与提交，输入／context／取消／卸载使旧确认失效；组件乱序回归通过 |
| R5 设置返回路由 | **关闭** | 设置leave映射calendar，实际组件事件检查返回工作台，未确认草稿守卫保留 |
| R6 原生保存互斥 | **部分修复，未关闭** | 生成／原生阶段已分离、范围过时响应不再卡住；但pending仍可通过“已核对文件”解除互斥并再次保存，见§10.3 |
| R7 有计划改名／noop | **关闭** | `config_service.py:754`无新修订时用现有解释；真HTTP/文件SQLite验证noop只增回执、改名不增修订／不改历史计划，旧noop回执跨配置变化重放正确 |
| R8 跨中间学期调整 | **关闭** | `:341`完整加载相交修订、`:901`比较完整前后解释；九月→十一月→九月均无中间十月虚假差异／影响，十月修订和日期行不变；旧计划仍可按原学期找到、打开、保存且归属周次不变 |
| R9 不完整日历修订 | **关闭** | `:274`校验精确日期集合，`:1208`最终写锁内再查；缺行、同30行但错日期、候选构建后至写锁前被另一连接删行均拒绝，故障注入后的所有local表逐行保持不变 |
| R10 Unicode令牌 | **关闭** | `config_tokens.py:103`将ASCII编码失败转校验错误；独立探针8类非法／签名篡改均422、过期409、随后合法200，拒绝无副作用 |
| R11 宿主保存／关闭互斥 | **部分修复，未关闭** | 不同ID现串行（最大同时1个对话框、两项在途、结束归零），正常busy拒绝有效；关闭重入撤销后回执仍假报closing，并在同步关闭回调通知JS，见§10.3 |
| R12 受限桥与握手 | **关闭** | 实际pywebview注入仅6个约定入口；未ready的save_docx/get_save_result均拒绝，无内部协调器／通知函数递归暴露 |
| R13 非DOCX保存 | **部分修复，未关闭** | 假PK、缺部件、截断ZIP已拒绝；空XML部件ZIP仍可覆盖旧文件并返回saved，见§10.3 |
| R14 旧关闭计时器 | **关闭** | 回调绑定请求ID；A取消、B开始后执行A迟到回调，B保持pending，最终closing不被旧超时取消 |

后端独立探针6组全部完成、exit 0、stderr空。R9为受控损坏／并发注入，不解释为用户正常操作会产生损坏。前端21项新增检查执行真实SFC脚本和Vue状态，但使用受控API／桥，不是DOM或真实Windows交互。

### 10.3 剩余缺陷及新增项

以下精确位置对应本轮源码快照。R1/R11属于跨层关闭问题，修复须联合验证，不能各自用独立模拟的成功响应宣称收口。

| 编号／优先级 | 确定触发与证据 | 必须满足的修复条件 |
| --- | --- | --- |
| **R1 / P1** 迟到关闭回包及冻结覆盖不全 | `frontend/src/d1/App.vue:213`等待complete之后未复核当前请求／取消状态。先收到A的save_in_flight撤销会清ID并解锁，随后A回复closing又设closeFinalAllowed=true；探针最终为ID=null、锁=false、final=true，新B请求不再调用宿主。另`:410`只将冻结传给Editor，设置页及工作台入口仍可操作（源码证据） | 回包必须绑定仍有效的ID／状态；真实撤销不得被迟到“closing”恢复，旧回包不得改新请求。最终关闭已放行仍保持冻结规则，但必须以宿主真实状态为准。关闭未决冻结覆盖全部页面输入、配置提交和导航；仅明确同ID取消／unknown等已有协议结果才恢复 |
| **R6 / P1** pending可被当成unknown手工解除 | `views/ExportDialog.vue:397`将pending/unknown合为同一phase，`:442`的confirmFileChecked仅检查nativeBusy。宿主持续pending，查询仍pending，点击当前可见“我已核对目标文件”后nativeBusy和busy事件都false；再试产生第二次fetch/save_docx和新UUID | 分别保存权威pending、unknown和终态；pending只允许只读查询，不能通过文件核对取消仍在途的操作。unknown才进入既定明确文件核对恢复流程；不同ID宿主串行不能替代前端保留原操作。补pending→query pending→点击核对／重试／离开的真实组件序列 |
| **R11 / P1** 关闭撤销后的假回执及同步JS等待 | `desktop/d1_host_api.py:234`在_destroy返回后固定accepted=true/closing。首次busy=false、destroy重入busy=true时，handle_closing已返回False、实际canceled并通知save_in_flight，回执却仍closing，触发R1。另`:158`在同步FormClosing回调内通知，沿`:655`调用evaluate_js；安装的pywebview/Edge实现会等待UI调度器，形成同UI线程等待风险。前者有确定性探针，后者为实际依赖源码调用链，未真实GUI触发 | 重入取消后如实返回最终状态并复核ID，不能返回预设成功；保存忙碌等拦截／撤销分支在同步closing回调立即返回False，仍有效的最终许可重入按协议返回True；通知JS放到回调外异步执行。补“保存恰在许可与重入之间开始”、通知／回执交错及真实WebView2不挂起验证 |
| **R13 / P2** ZIP成员存在不等于有效DOCX | `d1_host_api.py:298`只读取两个entry；含空 `[Content_Types].xml` 和 `word/document.xml` 的250字节ZIP被saved且覆盖已有临时目标（探针含old_target_overwritten=true） | 替换前至少确认必要XML非空、可解析并具有必要根／部件语义；无需引入完整OOXML schema或重写生成器。保留30MiB、base64、CRC和原子替换提交点；空XML、坏XML、错误根、真实产品样本分别验，非法内容不得开框或改旧文件 |
| **新增 R15 / P1** clean时IME输入被跳过 | `frontend/src/d1/leave.ts:100`在isDirty=false时直接离开；`views/EditorView.vue:254`同样在组合结束等待前返回unchanged，桥`:519`只暴露dirty。Element Plus组合期间尚未更新v-model时，探针composing=true/dirty=false；close仍发allow=true，PATCH=0、final=true，手动保存也返回unchanged。原真实驱动`desktop/d1_main.py:525`先制造已有dirty后才组合，未覆盖该场景 | 在判断无修改／冻结／导航前完成活跃组合输入及Vue最终值提交，然后重算dirty。覆盖初始clean→compositionstart→最终输入尚未入模型→手动保存／关窗／切日期／返回的路径；期间不要禁用活跃输入控件。不得仅在测试前人为制造dirty来避开边界，补真实WebView2场景 |

R15不新增产品行为，落实规格§11已有的“输入法最终输入先接收，再捕获payload与离开”要求；此前绕过等待的clean分支本轮才被明确复现。上述受控探针不得写成已实测真实输入法按键或原生UI死锁。

### 10.4 独立验证与交付证据核对

| 项目 | 本轮结果 |
| --- | --- |
| 完整本地，cwd backend，D1解释器 `-X utf8 -m unittest discover -s tests/local -t . -v` | **133项，0 skip，exit 0**（92.346s），未强加父级KGM_LOCAL_DB_PATH，沿用测试显式临时隔离 |
| 指定5组相关回归 | **108项，0 skip，exit 0** |
| `-m pytest desktop/tests -q -p no:cacheprovider` | **129 passed，exit 0**；2项依赖弃用警告 |
| `npm.cmd run typecheck`、`npm.cmd run test:d1` | 均exit 0；纯逻辑套件＋**21项组件异步检查**（不是把一套纯逻辑检查计作一个等价用例后宣称22项） |
| `npm.cmd run build:d1 -- --outDir <本轮证据>/frontend-build` | exit 0；独立临时输出3个文件，与最终包内前端资产逐一hash一致。保留大于500kB分块提示，不为此扩大重构 |
| 运行时／业务锁 | CPython3.14.7、win-amd64、标准GIL、SQLite3.50.4；业务26包不变，D1锁46包与安装版本一致；backend声明／锁及D1锁散列保持 |
| 最新包身份 | 仓内及仓外最终包各137文件与package-hashes-final.json全部匹配；6个关键归档模块与当前源码编译结果一致：4个D1宿主模块及config_service/config_tokens |
| 原包运行记录 | 只读复核final下5阶段JSON，checks均true；原临时库head=0003、2计划、12内容版本、14审计、外键检查为空，与实施记录相符。本轮未重新启动包 |
| Word样本 | 4份文件的字节／hash与§12.5一致，ZIP CRC及必要XML解析通过；未使用Word页面视图逐页查看，不能写成版式通过 |

最终EXE SHA-256：`f7c1a14f20eaf2d02b82483cdee2c950888b40f14d56c1965f481e0d970b3176`。原实施证据位于 `%TEMP%\kgm-d1b-fix-20261015`，前一个包和失败记录继续保留。源码/包身份一致意味着本轮发现适用于当前交付包，不能用构建成功跳过缺陷。

真实补验记录中的Element Plus入口注册修复已有DOM计数支持（419元素、19 textarea、8 el-input），当前入口也已注册；不将DOM存在或脚本钩子填值扩大为所有控件与教师流程已人工验收。原生另存为人工文件名／取消／真实占用重试、Word全页、关闭失联／超时的真实窗口注入、预览乱序真实时序，以及干净机器／Win10／WPS／其他DPI／教师体验均保留未验。

### 10.5 下一步与交接

1. OpenCode只继续R1、R6、R11、R13及新增R15；R2–R5、R7–R10、R12、R14不重复派发，但保留其回归。
2. 先修复跨层关闭状态／同步通知、pending保存和clean-IME，再补文档载荷校验；以确定反例建立必要回归，禁止为技术方便改变教师流程或以简化夹具掩盖边界。
3. 自动检查后，用合成数据完成真实WebView2故障与IME、原生保存操作；修复后再形成与源码一致的新包，仓外重启持久化并实际导出Word全页查看。确实无法完成的项目说明原因、步骤与未验状态。
4. 再次独立复审确认缺陷关闭及当前片必要证据后，安排教师体验，再准备D2。当前不开始AI、WebDAV、观察记录或发行。

已执行提示词的决定、原始修复与验证事实由规格§9–13、实施结果§12及本节承接；[current.md](../tasks/current.md)只保留剩余修复／补验任务，不新增提示词副本。Codex本轮未派发实现任务。

## 11. D1B 第二轮修复复审（2026-10-15）

### 11.1 结论与边界

**D1B仍不放行。** 对照[实施结果 §13](desktop-d1-result.md#13-d1b-剩余修复与补验2026-10-15-第二轮r1r6r11r13r15)，本轮五项中R11、R13、R15关闭，R1、R6部分修复但仍有确定反例。加上§10已关闭10项，累计15项中13项关闭、2项保留。本轮不新增编号，不重派已经关闭的13项。

代码缺陷关闭、当前Windows 11开发机工程验收、教师产品验收分别判断。即使后续关闭R1/R6，规格§13.2规定的原生人工保存、Word全页和剩余真实窗口路径仍须收口，不能仅以自动检查通过放行。干净机器、Win10、WPS、其他DPI、多显示器及教师体验保留后续边界，不擅自扩大为本轮发行门槛。

Codex仅做限定源码回读、独立交叉审阅、既有测试与仓外临时探针、文档更新。已读codebase-memory技能，但图工具不可用，未安装替代工具、不声称全仓图覆盖；未写入实现、测试、迁移或构建脚本，未重建桌面包、运行真实AI或操作教师数据。前端独立构建输出到临时目录。本轮未重新启动GUI／桌面包或打开Word，GUI结论来自对OpenCode原始记录的核查，明确区别于本轮独立执行的检查。

分支仍为 codex/desktop-v2-foundation，HEAD b3c5bbf，保留全部现有未提交及未跟踪资料。与§10留存的91文件快照相比，仅12个预期文件变化：8个前端文件、d1_host_api.py、d1_main.py及2个桌面测试文件；本地后端、迁移、构建脚本及锁未变化。证据根：%TEMP%/kgm-d1b-review3-20261015-a13797a2；原实施证据根：%TEMP%/opencode/kgm-d1b-fix2-20261015。临时证据可能清理，关键触发和结果归档如下。

### 11.2 五项修复关闭矩阵

| 原项 | 结论 | 本轮直接依据 |
| --- | --- | --- |
| R1 / P2 关闭冻结与请求隔离 | **部分修复，未关闭** | 迟到A回复不再复活终态或覆盖B，Workbench／Settings冻结已补；剩余问题为已确认撤销A只清UI锁，未释放协调器的悬挂等待，新导航／新关闭仍被拒绝，见§11.3。按剩余影响从原P1调整为P2 |
| R6 / P1 原生保存互斥 | **部分修复，未关闭** | pending只查询，unknown才允许文件核对，通信失败保留互斥；但结果查询无ID／代际复核，旧A查询迟到可把新B的pending改成saved并解锁，见§11.3 |
| R11 宿主保存／关闭互斥 | **关闭** | d1_host_api.py:173撤销通知转独立线程，:260在destroy重入后按真实状态及ID返回。独立探针中保存恰在许可后开始，回执为accepted=false/canceled；通知线程阻塞不阻塞closing回调；后续新ID正常关闭，A迟到返回不改B |
| R13 非DOCX保存 | **关闭** | d1_host_api.py:312校验必要XML非空、可解析及根元素。8类非法载荷全部INVALID_PAYLOAD、零对话框、旧目标字节保持；4份最终产品样本均可保存且字节一致。不扩大为完整OOXML校验或Word版式通过 |
| R15 clean状态IME遗漏 | **关闭** | leave先settle再判dirty，手动保存先占inFlight再等待组合结束。实际Editor＋App受控组件探针：dirty=false/composing=true时PATCH和allow均0；组合结束后最终文字只PATCH一次，再allow。真实WebView2原记录覆盖clean手动保存／切日期；实际中文输入法按键和其他离开方式的GUI证据仍未齐 |

R2–R5、R7–R10、R12、R14沿用§10关闭结论并保留相关回归。真实窗口未验本身不被改写为新的代码缺陷。

### 11.3 两项仍需修复的确定反例

**R1 / P2：已撤销关闭仍占用离开协调器。** [App.vue](../../frontend/src/d1/App.vue)第339–347行的onCloseAborted仅releaseCloseFreeze；[leave.ts](../../frontend/src/d1/leave.ts)第93–102行仅在原Promise完成后清active。[bridge.ts](../../frontend/src/d1/bridge.ts)第154、179行直接等待桥接调用，查询次数有界不代表每次调用有超时。

复现顺序：A进入finishClose，complete_close的Promise仍未返回；收到A的权威timeout撤销通知后，activeCloseId=null、closeLocked=false、final=false，但coordinatorBusy=true。此时分别请求设置／日历均返回busy、不执行导航；再次关窗B／C均发送allow:false。只有A旧Promise终于返回才恢复；如果桥接Promise始终不完成，阻塞将持续。提示“可以继续编辑”并不意味着可以正常保存后离开。探针没有把网络失败当作权威取消，而是明确注入同ID宿主撤销。

修复条件：对已确认撤销的对应close ID，结束或失效其协调器等待，使新导航／新关闭可立即正常处理；旧任务以后完成也不能执行旧动作、清除新任务或重新冻结。既有最终closing冻结、真实在途保存互斥及按ID的终态保护必须保留。回归必须在A旧Promise仍未完成时验证B／导航成功接续，另覆盖A永不完成和后来迟到，不得先resolve A再测B。

**R6 / P1：旧查询结果解除新保存的互斥。** [ExportDialog.vue](../../frontend/src/d1/views/ExportDialog.vue)第448–451行的queryLastResult在await后直接applySaveResult，未捕获并复核请求ID／操作代际；第617行查询按钮无在途禁用，可连续发起两次查询。

复现顺序：A结果未决，点击查询Q1（回复延迟）和Q2；Q2先返回saved，A解锁。用户再次导出B，B权威状态为pending，nativeBusy=true；随后Q1返回A的saved，页面错误显示A.docx保存成功、nativeBusy=false并发出busy=false。此时取消能发出update:open=false，再点导出可产生uuid-3，尽管B仍在途。探针记录uuid-1／2／3与完整状态变化。宿主串行保护仍在，但不能替代页面保留正确操作、阻止额外操作及避免错误成功提示。

修复条件：所有save／query异步结果仅能应用到仍有效的原操作；捕获request_id与操作代际，并在await后复核，旧结果不得更新新操作的状态／文件名／busy。查询应有明确的在途或序号策略，终态后同操作的旧pending／失败回复也不能回退状态；重试、文件核对、关闭／重开及新操作使旧结果失效。保持pending只读、unknown显式核对和同ID幂等。补Q1延迟／Q2终态／B pending／Q1迟到，以及同ID乱序和查询失败回归，不能仅依赖按钮文字或宿主排队。

原始证据：interface/frontend-review3-probes.mjs及.json，执行真实SFC脚本与已安装Vue，受控API／桥时序，exit 0；该exit表示反例探针完成，并不表示被测行为正确。另保留6项直接相关既有组件检查。本轮不是DOM点击或真实Windows竞态复现。

### 11.4 独立自动检查与交付身份

解释器沿用desktop/.venv-d1：CPython3.14.7、Windows x64、标准GIL、SQLite3.50.4；APP_DISABLE_DOTENV=1、PYTHONIOENCODING=utf-8、Python -X utf8。数据全部为显式临时合成目录；通用套件不继承KGM_LOCAL_DB_PATH覆盖。逐命令检查exit code。

| 检查 | 本轮结果 |
| --- | --- |
| backend下 unittest discover -s tests/local -t . -v | **133项，0 skip，exit 0**，106.857秒 |
| 指定内容校验／安全／日历／API schema／导出读取5组回归 | **108项，0 skip，exit 0** |
| pytest desktop/tests -q -p no:cacheprovider | **136 passed，exit 0**，8.71秒，保留2项依赖弃用警告 |
| npm.cmd run typecheck、npm.cmd run test:d1 | exit 0；纯逻辑套件＋**29项组件异步检查**，不把纯逻辑套件混算为单个等价用例 |
| npm.cmd run build:d1 -- --outDir 本轮临时目录/frontend-build | exit 0，3文件与最终包前端资产逐字节一致；保留超过500kB的分块提示，不扩大重构 |
| 宿主独立反例 | R11真实状态／独立通知线程通过；R13的8类非法载荷拒绝、4份真实样本保存通过，见runtime/host-fix2-probes.json |
| 包与源码 | 仓内／仓外各137文件均与清单相符；8个关键归档模块与当前源码编译对象一致，独立比较补齐原脚本遗漏的异常表等字段，仅忽略co_filename |
| 环境与锁 | 26个业务包、46个D1锁包版本核对无偏差；backend声明／锁和D1锁与§10散列一致，旧两代包保留 |

当前EXE SHA-256：61aba4eb8c58ec830f75071de987393f362a9360e24eade93c59c2f64ab87755，14,691,692字节。包身份一致也意味着§11.3两项反例适用于当前交付资产。身份结果见runtime/package-runtime-review.json及source-snapshot-comparison.json；根目录保留全部测试／构建日志及前后源码快照。

### 11.5 补验证据核对与未验矩阵

| 项目 | 已核实证据与实际边界 |
| --- | --- |
| clean-IME | 源码与最终包fix-regression记录全true；使用真实WebView2 DOM、程序化CompositionEvent及textarea setter，经生产保存／切日期链路，从dirty=false开始。覆盖clean手动保存和切日期，不等于真实中文输入法按键、clean-IME关窗／返日历／进设置均已实测 |
| 正常dirty-close与重启 | 源码和最终包均有正常保存／销毁记录；最终包v11→v12，verify2读回内容一致。并非R1悬挂回包或R11许可后保存开始的真实窗口注入 |
| 仓外阶段与首次失败 | 5个逻辑阶段最终通过；实际包启动6次：verify首次仅版本断言失败exit 3，随后verify2按v12通过。首次expect-version=10来自实施记录，原argv未留存；读回v12和原文相符有原始JSON支持。结果§13.4原“5个进程全部exit 0”已据此澄清，不能抹掉首次失败 |
| 源码首次clean-IME失败 | source-run库已保存两条最终文本，随后日志在误用JS in的等待条件超时；source-run2修正为includes后通过，支持此次驱动条件错误归因。§12曾用先dirty掩盖clean分支是另一个历史事实，R15修复后关闭，不混为同一次失败 |
| 最终合成数据库 | head=20261014_0003_local；2计划、14内容、16审计；09-15为v12、09-16为v2；外键为空、integrity_check=ok、WAL。只读检查原证据库，不使用教师库 |
| 最终DOCX | 4文件hash／字节与结果§13.4及final/saves完全一致，CRC／必要XML通过；A 14021、B 14450、C 14193、D 14044字节。未在Word页面视图逐页查看 |
| **仍缺：真实窗口故障路径** | 关闭悬挂／丢回复、30秒超时后恢复、关闭许可与保存交错、导出pending／迟到查询、配置预览乱序实际窗口证据未齐；组件与线程探针不能替代。相关IME离开路径也须按原矩阵补齐 |
| **仍缺：原生人工保存** | 自选中文文件名、取消、实际占用失败及解除后新ID重试、旧文件保护；预授权目录写入不能替代原生对话框操作 |
| **仍缺：Word全页** | 对空／代表性／长内容／多份实际产品导出，在Windows Word页面视图或打印预览逐页检查分页、表头、末页，记录版本／字体／页数；XML或页数不能替代 |

证据细项见evidence/evidence-check.json。当前工具条件下本轮未执行原生GUI或Word操作；不能以无操作能力作为验收通过理由。无新增产品问题，不重问班级／多学期范围，不启动D2、AI、WebDAV、观察记录或发行。

### 11.6 下一步与文档归并

1. OpenCode只继续R1和R6的异步生命周期修复，先补上述反例，再执行受影响回归；已关闭13项保留保护，不泛化重构。
2. 修复后沿用既有环境，形成与源码一致的新包并核对身份；当前61aba4eb包和失败证据保留。补真实窗口、原生保存与Word全页。无法执行的项目记录原因及最短操作步骤，继续标未验。
3. Codex再审两项关闭和当前片证据，满足后才宣布D1B工程放行；教师体验／产品验收另记，之后准备D2规格。

原任务独有修复规则、运行约束和结果已归入规格§9–13、实施结果§13和本节；[current.md](../tasks/current.md)替换为仅R1/R6及补验的唯一接续任务，不保留已执行提示词堆叠。本轮只做审阅和交接文档，不派发或代写实现。

收尾检查：11份相关文档的219个相对链接／锚点与代码围栏通过，91个实现／测试／构建／依赖文件的本轮前后散列不变；git diff --check为exit 0，仅保留仓库既有换行转换提示。记录见本轮证据根review-final-check.json及git-diff-check.log。

## 12. D1B 第三轮修复复审（2026-10-15）

### 12.1 结论、范围与方法

**D1B 仍不放行。** [实施结果 §14](desktop-d1-result.md#14-d1b-剩余修复与补验2026-10-15-第三轮r1r6)确实修复了 §11.3 两条原反例；但修复未覆盖关闭请求进入协调器前的等待阶段，以及导出查询按钮自身的跨操作生命周期。R1／R6 均未完全关闭，当前残留均为 P2；R6 原 P1“旧结果误解锁新保存”已修复，不将本轮锁死问题称为仍有相同的数据保护漏洞。累计15项中13项关闭，沿用原编号和历史，不重开已关闭项目。

审阅限定于本次 R1／R6、必要相邻路径、第三轮补验驱动和交付证据。先读取 codebase-memory 技能；当前工具清单无图查询／覆盖接口，采用限定源码读取和独立交叉审阅，不声称图覆盖或全仓审计。保留工作区既有修改及未跟踪文件；继续原分支，未暂存、提交、推送、安装或重建桌面包。Codex 仅执行现有检查、临时反例／身份核验和文档更新，没有改实现、测试、迁移或构建脚本。

临时证据根：`%TEMP%\kgm-d1b-codex-review4-20261015\`。`r1/`、`r6/` 为实际 SFC setup＋真实 Vue refs/watch＋受控桥时序探针，`runtime/` 为包／锁／合成库／窗口日志独立核验，根目录保存检查日志、前端临时构建、源码散列和 Word 身份核对。探针不冒充 DOM 点击或真实宿主故障注入；临时文件不保证长期保留，关键复现与判据如下持久记录。本次未启动 GUI 或 Word，检查的是 OpenCode 保留的原始记录和页面截图；不访问真实教师库、`.env`／密钥、旧远程或 AI。

### 12.2 原反例修复核对

| 项目 | 已核实通过的路径 | 尚未关闭的原因 |
| --- | --- | --- |
| R1 | 已进入协调器的 A 撤销后，即使 A 回包永不完成也可接续 B／导航；保存中撤销仍消费原保存；A 迟到不干扰 B；IME settle 中撤销也未补发旧许可。7项直接相关既有组件检查及独立扩展检查通过 | `waitForExportIdle` 在协调器登记前；这个阶段的撤销没有保留，见 §12.3 |
| R6 | Q1迟到／Q2终态／B pending 后旧A结果不再解锁B；同ID终态后迟到pending／通信失败不回退；操作ID与代际复核有效 | `queriesInFlight`仍跨操作共用；旧查询永不完成可禁用B唯一恢复按钮，见 §12.3 |

不以“所有已有测试通过”替代遗漏路径的正向验收。两份独立正向预期探针均 exit 1，保留在证据目录；另外的反例记录器 exit 0 仅表示成功捕获缺陷。

### 12.3 必须修复的残留

**R1 / P2：原生保存等待期间的关闭撤销被遗忘。** [App.vue](../../frontend/src/d1/App.vue)第299–315行先等待 `waitForExportIdle`，随后才进入 `requestLeave`；第356–361行只在 `coordinator.cancelClose(id)` 返回 true 时写 canceled。A 尚在等待原生保存时没有协调器条目或 activeCloseId，宿主的权威撤销因而被丢掉。

复现：原生保存仍在途→请求关闭A→宿主30秒超时并通知A canceled→保存稍后结束→旧A恢复，重新发 `allow:true` 并冻结。若A此时回包悬挂，新B被协调器判busy并发 `allow:false`，导航也留页。独立探针得到 `A allow=true / B allow=false / activeId=A / locked=true / coordinatorBusy=true / navigation=stayed`。宿主 `d1_host_api.py:181–211` 对请求立即启动30秒计时器，原生保存不会暂停该计时器；这是一条协议允许的时序，不依赖强行调用非法接口。

`node <证据>/r1/r1-expected-behavior.mjs` **exit 1**，4项正向预期失败（旧A不得发许可、B应放行、旧A不占用、B最终关闭）；`r1-probes.mjs` 的 JSON 和日志保留实际事件。修复要求：关闭生命周期从 `onRequestClose` 入口覆盖原生保存等待；权威撤销按ID留存，在每个相关 await 后复核。已撤销A不得补发allow／deny、重新冻结、占用B或执行旧动作；真实在途保存继续正常消费结果，通信失败与最终closing保护不放宽。回归必须在保存尚未结束时撤销A，再结束保存并验证A零许可、B／导航接续；旧桥Promise继续未完成。

**R6 / P2：旧查询的 loading 锁死新操作的查询入口。** [ExportDialog.vue](../../frontend/src/d1/views/ExportDialog.vue)第512–520行对全局 `queriesInFlight` 加减；第120–125行结束操作只使结果代际失效，没有退役旧查询loading；第691行把该计数绑定查询按钮。已安装Element Plus会在loading时设置disabled并阻止click。`EditorView.vue:903–910`持续挂载该组件，普通关闭／重开只改变open，不能重置计数。

复现：A返回显式unknown→点击查询Q1且回包不完成→用户按现有允许流程核对目标文件→关闭／重开导出→新B返回pending。此时B仍正确保持互斥，但 `queriesInFlight=1`，查询按钮持续禁用；B即使已能查询为saved，用户也无法查询，关闭／重新保存／离开同样被互斥阻止。独立探针没有强制改内部状态；直接脚本调用B查询可成功，恰好说明绕过按钮的测试会漏掉此缺陷。

`node <证据>/r6/r6-recovery-regression.mjs` **exit 1**：`new B must not inherit query loading from retired A`，actual 1／expected 0。修复要求：查询loading／在途状态归属于操作代际；核对、终结、关闭／重开及新操作退役旧等待，旧finally也不得递减新代际计数。保留pending只读与unknown显式核对。补“旧Q1永不完成→合法核对→B pending→从实际按钮查询B”的回归，并覆盖旧Q1后来返回／抛错不干扰B计数；不能只直接调用 `queryLastResult()`。

### 12.4 独立自动检查与包身份

沿用 `desktop/.venv-d1`，CPython3.14.7／Windows x64／标准GIL／SQLite3.50.4；Python `-X utf8`，`APP_DISABLE_DOTENV=1`、`PYTHONIOENCODING=utf-8`。测试清除继承的KGM变量；完整本地套件由用例指定临时库，仅设临时数据根兜底，没有注入父级DB路径。

| 检查 | 本轮独立结果 |
| --- | --- |
| backend下 `-m unittest discover -s tests/local -t . -v` | **133项，0 skip，exit 0，93.294s** |
| 五组内容校验／安全／日历／API schema／导出读取回归 | **108项，0 skip，exit 0，0.650s** |
| `-m pytest desktop/tests -q -p no:cacheprovider` | **136 passed，exit 0，6.25s**；2项既有依赖弃用警告 |
| `npm.cmd run test:d1`、`npm.cmd run typecheck` | 纯逻辑套件＋**36项组件检查**及类型检查通过，exit 0 |
| `npm.cmd run build:d1 -- --outDir <证据>/frontend-build` | exit 0；3文件与包内前端资产逐字节一致，保留500kB分块提示 |
| 包清单／模块／资源 | 仓内、仓外各137/137文件，无额外或差异；8关键归档模块递归比较全部代码元数据，仅忽略co_filename，包括行表／异常表，均与源码一致；迁移配置、revision和模板相符 |
| 运行时与锁 | backend26包、desktop46包实际版本与锁一致、无额外包，业务26包跨环境一致；两套 `uv pip check` exit 0；声明／锁散列未变 |

EXE为14,699,752字节，SHA-256 `caa7a12725051066f223bcc9c67c014ad2fad81134c02d80c31f9e2cf37435de`。这也说明两条残留适用于当前交付资产。未将本次前端临时构建说成重新构建或重新实跑桌面包。

### 12.5 补验证据的实际含义

| 项目 | 独立核对及边界 |
| --- | --- |
| 包与源码窗口记录 | 包6份JSON分别6／6／28／19／5／4项全true，日志6次start／6次正常returned；源码4份JSON全true、4次正常returned。未保留外层进程returncode行；历史“全exit 0”由驱动返回路径与日志旁证，本轮未独立重跑GUI |
| R1真实30秒超时 | 包日志21:03:45开始、21:04:15超时并通知；源码也有完整30秒链。包装complete_close使宿主未收到allow，旧Promise未完成时恢复导航有证据；不覆盖§12.3的原生保存等待阶段撤销 |
| R6窗口场景 | `d1_main.py:1066–1098`完整替换save_docx／get_save_result并构造pending／saved，是**真实WebView2页面＋受控桥状态注入**，不是宿主真实pending；通过驱动直接调用查询也不能证明实际按钮可用。原“仅丢失／推迟回包”口径须收窄 |
| 配置预览乱序 | `d1_main.py:1164–1199`在release时才realFetch，延迟的是请求发出；之后固定sleep 1秒，没有等待响应与组件处理完成。三个UI断言在响应尚未回来时也能通过，不能独立证明迟到响应已丢弃；需补完成信号和处理后的断言。已关闭R4的组件证据保留，不据此重开代码问题 |
| clean-IME与真实保存等待 | 返回日历／进设置／关窗程序化CompositionEvent与真实HTTP保存有记录；最终库v14原文为“关窗前组合最终文字”。慢真实保存先completed、再allow、再closing的日志有效；不等于实际输入法按键或宿主内部许可／保存交错已注入 |
| 最终合成库 | head=20261014_0003_local；2计划v14／v2、16内容、18审计、1日历修订；integrity_check=ok、FK空、WAL。verify阶段v13是读取值，原文有断言，未传expect-version，不能称为v13预期断言 |
| 原生人工交付 | **仍未执行**中文名另存为、取消、真实占用失败及解除后新ID重试、旧文件保护的人工对话框流程。预授权目录写入与单测不能替代规格§13.2实测门槛 |

**Word核对：** 4份样本与`package-saves`对应文件及清单散列完全一致，字节数14,021／14,165／14,443／14,038。核对Word16.0页面记录和全部11张截图，逻辑页数2／2／5／2，字体Times New Roman／仿宋／楷体、10.5／12／16pt。A、B、D首页表头／栏目及反思末页可见；C的长反思跨第2–3页，第二份计划从第4页新页开始，第5页反思可见，未发现正文或表格裁切、重叠、缺字等确定问题。截图使用双页视图，部分相邻截图显示相同两页；C第3–5页截图未显示完整物理页下方空白边缘，不能称为11份独立整页图，但正文、表格及分页区域可目视核对。现有Word页面证据已从上轮“未逐页查看”推进为本轮截图目视复核，不冒充本轮重新打开Word或教师审美验收；WPS未验。

尚未补齐的真实窗口分支、原生人工交付与实际IME按键仍如实列示；干净机器、Win10、其他DPI／多显示器、教师体验属于保留边界。本轮不以环境未验扩大实现范围，也不把它们混作已确认代码缺陷。

### 12.6 接续与文档归并

1. OpenCode只修§12.3两条遗漏生命周期路径，补能实际失败的回归；已修复的旧反例及13项已关闭保护保留，不扩大重构。
2. 补R6实际按钮、预览响应确已处理和原生人工保存证据；按原矩阵保留并补齐真实窗口必要分支。修复后更新同环境包与身份，保留caa7a127…包和首次失败证据，记录实际命令／返回码，不以固定等待代替结果完成。
3. Codex再核两项关闭及本片必要证据后才工程放行；教师体验／产品验收另列。没有自动派发实现、启动D2／AI／WebDAV或发行。

当前任务的第三轮独有决定、验证边界已归并至实施结果§14及本节；[current.md](../tasks/current.md)替换为两条残留与补验的唯一接续入口，相关状态索引同步，不增加多轮提示词副本。

收尾检查：本轮9份相关文档的206个相对链接／锚点、代码围栏及行尾空白检查通过；快照范围88个实现／测试／构建及桌面依赖文件前后散列不变。`git diff --check` exit 0，未跟踪文档亦直接检查，不以Git可见差异替代完整文档检查。证据为`review-final-check.json`和`git-diff-check.log`。

## 13. D1B 第四轮修复复审（2026-10-16）

### 13.1 结论与范围

**R6关闭，R1仍有P2残留；D1B仍不放行，累计15项中14项关闭。** [实施结果§15](desktop-d1-result.md#15-d1b-r1r6-残留修复与补验2026-10-15-第四轮)对应2026-10-15第四轮实施，本节为次日独立复审。上一轮§12.3的两条具体反例均已通过，但R1尚未覆盖“新宿主关闭ID先于旧撤销通知送达”的合法时序。既有13项及本轮R6关闭事实保留；不另增问题编号，不扩大产品需求或重构范围。

本轮与前轮快照比较，限定范围内变化为App.vue、ExportDialog.vue、SettingsView.vue的只读验证钩子、组件测试、d1_main.py，共5文件。依codebase-memory技能再次检查工具清单，图查询／覆盖接口仍不可用，使用限定源码与独立探针，不声称图覆盖。继续原分支，保留工作区既有修改及未跟踪文件；仅改审阅／接续文档，未改实现、测试、迁移、构建脚本，未安装、重建桌面包、提交或推送。没有访问教师库、密钥、旧远程或AI。

临时证据根：`%TEMP%\kgm-d1b-codex-review5-20261016\`，含`r1/`、`r6/`、`evidence/`，测试日志、独立前端构建与源码快照。复审未启动真实GUI；窗口判断来自原始日志、JSON与当前包内驱动核对，独立探针的SFC／宿主线程与真实窗口证据明确区分。临时证据不保证长期留存，关键触发、判断与未验边界保留如下。

### 13.2 修复核对与关闭结论

| 项目 | 独立结果 | 状态 |
| --- | --- | --- |
| R1 上轮保存等待期间撤销 | 原正向探针原样复跑exit 0、4/4 PASS；9项相关组件回归以及错误ID撤销、native wait后IME settle中撤销通过；已收到撤销的A不会再补许可 | 原具体反例已修复；新通知顺序反例使R1继续保留 |
| R6 查询loading归属 | 原正向探针exit 0；独立11条扩展时序通过，终态／核对／关闭／新操作退役旧计数，旧finally仅修改所属代际；真实DOM查询按钮证据相符 | **关闭** |

R6扩展检查覆盖：unknown显式核对、saved／canceled／failed终态、关闭重开、新导出与显式重试；B自己的查询仍在途时旧A返回或抛错，B计数仍为1，B完成后归零；同ID终态后迟到pending／failed不回退；pending拒绝核对／关闭／重试，通信失败保留互斥。仅在内存删除finally的代际条件后，变异探针按预期exit 1（B计数误为0，应为1），证明检查能识别保护缺失；没有改仓库测试或实现。原探针历史快照名中的`disabled-FAIL`是旧标签，本轮实际字段与断言均通过。

关键源码为`ExportDialog.vue:108–137`的代际退役、`:517–538`的await后绑定及finally复核。当前组件SHA-256为`576b35a585bbcd3bf49e58d23dc410e0150514afffce44bfedd118a341201503`。本轮限定范围未发现R6新的确定阻塞。

### 13.3 R1 / P2 残留：新关闭先于旧撤销通知到达

[App.vue](../../frontend/src/d1/App.vue)第299行登记新关闭ID，第301–305行面对另一ID只释放UI冻结，没有让仍开放的旧handler／协调器等待失效；第320行的原生保存等待后复核只依赖已经收到的`abortedCloseIds`。新的宿主请求B本身已说明A在宿主结束，但页面没有用这个事实退休旧A。

确定反例：

1. A正等待原生保存。宿主超时A、将其置canceled，但撤销通知延迟。
2. 宿主创建新B，`request_close(B)`先到页面；A／B仍等待同一原生保存结束。
3. 保存结束时旧A先恢复，发`allow:true`并等待悬挂回包；B被旧A的协调器条目判busy，发`allow:false`。
4. 迟到的A撤销到达后可以解冻，却不能挽回已经错误否决的B；若该通知丢失且A回包仍不完成，旧阻塞继续存在。

实际SFC＋Vue探针`node <证据>/r1/r1-delayed-abort-probe.mjs` **exit 1**，正向期望“B应发送allow=true”实际false；记录为`A allow=true / B allow=false / activeId=A / locked=true / coordinatorBusy=true`。随后放行A撤销，页面恢复但B许可仍缺失，见`r1-delayed-abort-results.json`。没有依赖最终窗口销毁后页面继续运行的假设。

实际宿主`CloseCoordinator`的线程探针`python -X utf8 <证据>/r1/host-notification-order.py` exit 0，证明此顺序合法：timeout先在锁内把A置canceled；撤销通知回调尚未完成，B已可创建并由另一线程送达；随后才送达abort(A)。宿主此时A查询为unknown，B为pending，见`host-notification-order.json`。两项分别为真实组件脚本与真实宿主类的受控时序验证，不声称在真实WebView2已复现完整反例。

**修复验收：** 新宿主关闭ID到达时，使它所替代的旧开放handler及旧协调器等待失效，覆盖尚未冻结、正在等原生保存／IME／数据库保存以及已在等旧桥回包的阶段；保留同ID幂等和最终closing保护，不把通信失败当作权威取消，不丢弃真实在途保存结果。新B不能依赖旧abort(A)或旧回包先返回。补“宿主A已超时、B先送达、A撤销延迟／丢失、保存结束”的正向回归，要求A零补发许可、B／导航不被旧A占用，再补A迟到通知与回包不影响B；不得先resolve A再测试B。

### 13.4 独立检查与交付身份

沿用CPython3.14.7／Windows x64／标准GIL／SQLite3.50.4。Python使用`-X utf8`、`APP_DISABLE_DOTENV=1`、`PYTHONIOENCODING=utf-8`；清除继承KGM变量，测试由用例指定临时库，仅完整本地套件设临时数据根兜底，不注入父级DB路径。

| 检查 | 本轮独立结果 |
| --- | --- |
| backend下`-m unittest discover -s tests/local -t . -v` | **133项，0 skip，exit 0，93.522s** |
| 内容校验／安全／日历／API schema／导出读取五组回归 | **108项，0 skip，exit 0，0.940s** |
| `-m pytest desktop/tests -q -p no:cacheprovider` | **136 passed，exit 0，10.17s**；保留2项依赖弃用警告 |
| `npm.cmd run test:d1`、`npm.cmd run typecheck` | 纯逻辑套件＋**40项组件**及类型检查，均exit 0 |
| `npm.cmd run build:d1 -- --outDir <证据>/frontend-build` | exit 0；独立构建3文件与当前包逐字节一致 |
| 仓内／仓外包与源码 | 各137/137文件，无缺失／额外／差异；8关键归档模块递归比较完整元数据，仅忽略co_filename，均匹配；迁移INI／revision／模板相符 |
| 环境／依赖 | backend26、desktop46实际版本精确匹配锁，业务版本一致；4份声明／锁散列与上轮一致，两套`uv pip check`独立exit 0 |

当前EXE为14,704,113字节，SHA-256 `9a8e90c854ed45cd2b31b447176f441c7be8c03f72fc58de5f2c93b6e2fec1e0`。源码／资产身份一致支持上述审阅适用于该交付；不等于整体放行。

### 13.5 补验证据与未验边界

| 项目 | 核实结果与边界 |
| --- | --- |
| 仓外6进程 | `pkg-phases-result.json`由驱动直接保存subprocess返回码，6项均0；各阶段6／6／28／31／5／4项检查全true；日志6次启动及正常返回。本轮检查记录，未独立重跑GUI |
| R1原生保存等待撤销 | 真实`_perform_save`延迟＋宿主同一超时路径临时缩至5秒，日志保存开始→关闭→超时→撤销通知→保存完成；A零许可、busy清除和导航成功有记录，覆盖上轮反例。未覆盖本轮B先于A撤销通知到达 |
| R6实际按钮 | 源码和包内`fix2b_*`检查全true；真实DOM点击查询、核对、取消／重开、缺项确认与B查询，读取实际disabled；A/B的pending／unknown／saved来自受控桥，文档本轮已准确区分 |
| 预览完成 | 已等待inputVersion失效、真实fetch settle及预览按钮结束loading，补上上轮固定sleep的缺口；served在成功和reject时均设置，未保存HTTP状态／有效正文，只能证明请求已settle并完成组件处理后无旧预览，不能独立声称HTTP200有效预览正文曾返回。不作为新产品缺陷 |
| 源码首次失败 | 源码日志实际6次启动、4次正常完成；22:14:47与22:18:57两次尝试在点击导出后等待unknown约60秒，未点击ack，后续补ack后通过。现存说明JSON是事后解释＋诊断摘录，原始失败完整JSON／返回码未留存；支持漏确认的驱动步骤解释，不能确认两次失败全部根因或称只有4次启动 |
| 最终合成库 | head=20261014_0003_local；2计划v14／v2、16内容、18审计、1日历修订；integrity_check=ok、FK空、WAL；v14原文为关窗前组合最终文字。verify阶段原文断言有效，v13仍是观察值，非expect-version断言 |
| Word | 4份新包样本与当前package-saves及§12.5已目视复核样本逐字节一致，字节数14,021／14,165／14,443／14,038。沿用2／2／5／2页和既有目视范围，不重复相同文件的视觉检查，不声称本轮重新打开Word |
| **原生人工保存** | **仍未执行**中文名另存为、取消、真实占用失败／解除后新ID重试、旧目标保护的人工对话框流程，仍属规格§13.2必要实测门槛 |

实际IME按键、宿主内部许可／保存交错的真实窗口注入仍未验；现有程序化CompositionEvent与R11线程证据保持其原边界。WPS、干净机器、Win10、其他DPI／多显示器和教师体验继续按阶段保留，不能由自动检查代替，也不因此启动无关环境审计。

### 13.6 接续

OpenCode后续只修§13.3的R1通知乱序／替代生命周期，保留R6及其他已关闭14项回归；不再把R6当作待修复代码项。补既定原生人工交付和必要窗口证据；修复后形成对应源码的新包，保留9a8e90c8…包、历史失败和不完整证据说明。无法执行的项目仍记录未验及最短步骤。Codex确认R1关闭并核齐本片必要证据后才工程放行；产品体验另记，不自动启动D2、AI、WebDAV或发行。

第四轮任务中的独有决定和未验事项已归并至实施结果§15与本节；[current.md](../tasks/current.md)更新为仅R1和补验的唯一接续入口，不新增提示词副本。本轮没有派发实现或代写代码。

收尾检查：9份相关文档的213个相对链接／锚点、围栏及行尾空白检查通过；本轮快照范围88个实现／测试／构建及桌面依赖文件前后散列不变。`git diff --check` exit 0；未跟踪文档亦直接检查。结果见证据根`review-final-check.json`及`git-diff-check.log`。

## 14. D1B 第五轮修复复审（2026-10-16）

### 14.1 结论与范围

**D1B仍不放行。R1保留P2，新增R16/P2；累计16项中14项关闭。** [实施结果§16](desktop-d1-result.md#16-d1b-r1-通知乱序残留修复与补验2026-10-16-第五轮)修复了§13.3的具体反例，R6及另外13项关闭事实保留。本轮不是以“缺人工点击”拒绝有效的原生保存补验，而是发现两条有直接证据的契约缺陷：旧request_close通知迟到会错误退役当前请求；原生保存错误把完整路径透传给页面。

与上一轮88文件快照比较，本轮实现／测试变化仅为App.vue、d1.components.test.mjs、d1_main.py。继续原分支及既有未提交工作区；Codex只执行验证并更新审阅／接续文档，未改实现、测试、迁移或构建脚本，未安装、重建桌面包、提交或推送。未访问教师库、密钥、旧云端或真实AI。

按codebase-memory技能进行有界Verify查询：项目`C-Users-yw980-code-kindergarten-manager-next`，generation `2026-10-15T23:16:51Z`，ready；父查询相关关闭符号、双向调用和源码片段，结果无遗漏分页。关键路径覆盖没有已记录解析问题，但freshness为metadata_changed；因此所有重要结论回到当前源码和独立探针验证，不声称图谱完整。图中的同名set误解析边没有作为证据。

独立证据根为`%TEMP%\kgm-d1b-codex-review6-20261016\`，含`r1/`、`native/`、`evidence/`、全套日志、独立前端构建与源码快照。OpenCode原始证据为`%TEMP%\opencode\kgm-d1b-fix5-20261016\`。本轮Codex没有启动真实GUI；窗口结论来自原始阶段JSON／日志、当前驱动及包内源码交叉核对。受控宿主线程、实际SFC、真实文件占用与真实窗口证据分别标明，临时文件不保证长期保留。

### 14.2 原反例与回归

| 范围 | 独立核对 | 结论 |
| --- | --- | --- |
| R1：A等待原生保存，先收到撤销，再结束保存 | 上两轮原正向探针原样复跑均exit 0 | 该反例已修复 |
| R1：A已送达且超时，B先于abort(A)到达 | 原§13.3正向探针exit 0；相关14项组件与三代替换／旧A查询unknown不干扰pending B检查通过 | 上轮具体残留已修复；不能覆盖旧request_close(A)本身迟到 |
| R6及其他已关闭项 | R6代码未变化；完整纯逻辑＋45项组件、136项桌面、133项本地及108项回归通过 | 保持关闭，不再派发R6修复 |

`retireReplacedClose`能按ID释放旧协调器等待，保留保存响应消费和各await后的静默检查。问题不在这项能力缺失，而在入口直接把抵达顺序当作请求的新旧顺序。

### 14.3 R1 / P2：迟到的旧请求通知退役当前请求

[App.vue](../../frontend/src/d1/App.vue)第323–329行把每个新收到的不同ID当作替代者，无条件退役其他开放handler。[d1_host_api.py](../../desktop/d1_host_api.py)第197–199行每次独立启动通知线程，第282–288行发送request_close前不复核当前ID，未提供通知抵达顺序保证。

确定时序：

1. 宿主建立A，但A的request_close通知暂未送达；宿主超时A，abort(A)先到页面。此时页面尚无A的handler，撤销不会留下后续拒绝A的标记。
2. 用户再次关闭，宿主建立B，request_close(B)先到；B正等真实在途保存结束。
3. 旧request_close(A)随后到达。页面把它当作更新的请求，退役当前B。
4. 保存结束后，A发allow、B静默。宿主拒绝过期A，返回accepted=false/state=pending；查询A为unknown。页面解锁，真正的B仍pending，只能继续等宿主超时，当前关闭操作未执行。

独立`r1/delayed-request-host-trace.py`使用实际CloseCoordinator及其通知线程，以屏障暂扣A的通知回调，显式执行生产`_on_timeout(A)`加速计时，得到`abort(A) → request(B) → request(A)`及真实宿主回执，exit 0。没有墙钟等待30秒，也没有声称真实WebView2重现。`delayed-request-sfc-probe.mjs`将该JSON及回执直接送给实际SFC＋Vue；结果`A_allow_count=1、B_allow_count=0、hostBState=pending、locked=false`，正向预期“B应放行／A应静默”两项失败，**exit 1**。不依赖旧桥回包永不完成，也不依赖窗口最终销毁后页面仍运行。

**修复验收：** 只有宿主当前有效的关闭请求可以退役前序请求，不能以不同ID通知的到达顺序代替权威新旧关系。覆盖旧request_close延迟／重复、abort先于request到达、B处理期间旧A到达，以及既有“B先于abort(A)”反例；A不得补许可、取消B或重设B冻结。保留同ID幂等、最终closing、通信失败冻结和在途保存正常消费。不能仅靠扩大撤销集合处理某一送达顺序，遗漏撤销丢失的同类路径。

因果对照`delayed-request-counterfactual.mjs`仅在内存去除新加的开放ID无条件退役循环，B许可从0恢复为1，exit 0；观察时B回包仍pending，不依赖真实销毁后的页面状态。这个对照会重新打开原来的问题，不是可提交的修复方案；仓库实现未改。

### 14.4 R16 / P2：保存异常未脱敏即返回桥与页面

规格[§12.3](../specs/desktop-manual-daily-plan.md#123-原生交付和过时响应)要求失败显示占用／权限／I/O等**脱敏原因**。当前[d1_host_api.py](../../desktop/d1_host_api.py)第399–400行直接返回`str(exc)`；第396行、499行、611行及选择器异常包装亦拼接原异常。结果被缓存供get_save_result再次返回；[ExportDialog.vue](../../frontend/src/d1/views/ExportDialog.vue)第461行将message直接展示。

OpenCode真实窗口`source-run/save-dialog4.json`及`package-logs/save-dialog.json`的`save_dialog.locked.info.result_text`已经记录页面显示完整用户目录、目标绝对路径和随机临时文件名。这不是仅诊断日志含路径，也不需要假设远程攻击；它违反已确认的页面错误契约。

独立`native/save-error-sanitization.py`经实际D1HostApi.save_docx/get_save_result、真实Windows文件占用复现（文件选择器受控，未开GUI）：首次与缓存结果均泄露绝对路径，正向脱敏断言**exit 1**；同时确认旧目标保持、临时文件清理。`save-exception-matrix.py`再核提交后stat故障仍为unknown但桥／缓存包含路径、选择器与最外层异常透传，exit 0为现状确认，不是修复通过。

**修复验收：** 在宿主对外错误边界给出稳定、可理解的占用／权限／I/O／对话框失败原因，不直接传递原异常、绝对路径、临时名或内部细节；首次响应和缓存查询保持一致。覆盖提交前真实占用、选择器异常、外层兜底及提交后核验失败；后者仍须unknown，不得为了脱敏改成failed或误报旧文件未变。保留取消、成功、真实占用后新ID重试与旧文件保护，不扩大为错误体系重构。

### 14.5 独立检查与交付身份

环境仍为CPython3.14.7／Windows x64／标准GIL。Python使用`-X utf8`、`APP_DISABLE_DOTENV=1`及UTF-8输出，清除继承KGM变量；仅完整本地套件设置临时数据根兜底，不向测试强塞父级DB路径。

| 检查 | 独立结果 |
| --- | --- |
| backend下`-m unittest discover -s tests/local -t . -v` | **133项、0 skip、exit 0，99.687s** |
| 内容校验／安全／日历／API schema／导出读取五组回归 | **108项、0 skip、exit 0，0.818s** |
| `-m pytest desktop/tests -q -p no:cacheprovider` | **136 passed、exit 0，11.46s**；保留2项依赖弃用警告 |
| `npm.cmd run test:d1`、`npm.cmd run typecheck` | 纯逻辑套件＋**45项组件**、类型检查均exit 0 |
| `npm.cmd run build:d1 -- --outDir <证据>/frontend-build` | exit 0；3个构建文件与当前包逐字节一致，保留大分块提示 |
| 仓内／仓外目录包 | 各**180/180**文件与清单一致，无缺失／额外／差异；8关键归档模块完整代码元数据比较仅忽略co_filename，均同源；迁移INI／revision／模板一致 |
| 依赖 | backend26／desktop46实际版本精确匹配锁，两套pip check独立exit 0；4份声明／锁散列不变 |

EXE为14,721,796字节，SHA-256 `167b352b9465a546f0a0c8ee964bb4996bae1b147d01058161eacde638ba5385`。身份相符说明审阅适用于该包，不代表没有上述缺陷。

**包来源更正：** 增加的42个api-ms-win-*.dll及ucrtbase.dll共43文件，COLLECT-00.toc实际指向`<LOCAL_USERPROFILE>\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\libheif\libheif\bin\`，并非直接从System32或D1解释器目录取得。逐一与该来源散列一致，均AMD64、版本10.0.26100.4654。当前PyInstaller解析库名亦按PATH选择此目录；旧／新d1_main的ctypes扫描均无直接DLL结果，不能把“新增ctypes必然导致43文件”写成已证实因果。记录实际来源及PATH选择，保留为干净构建／发行可再现性边界；仅凭外部来源不新增本轮运行缺陷或阻塞，不据此清理环境或自行重建包。

### 14.6 补验证据的通过范围

| 项目 | 核实结果与边界 |
| --- | --- |
| 仓外9进程 | 逐进程returncode均0，9份startup日志各有启动与正常返回；阶段检查为6／6／28／32／13／13／8／5／4，全true；不同cwd及临时合成库路径有记录 |
| R1 close-order | 源码／包的delayed与lost各13/13；真实宿主超时路径临时缩至5秒、真实保存延迟、真实evaluate_js通知，A已先收到request后，B先于abort(A)到达，A零许可、B单许可且save_done≤allow。修复前窗口反例exit 3、A静默／B单许可两项false保留。它不覆盖§14.3的旧request_close本身迟到 |
| 原生保存 | save-dialog未注入预授权目录，Win32自动化操作真实另存为／取消／覆盖确认；包的中文名文件为14,165字节，源码样本为14,021字节，均有效DOCX；取消不写、真实句柄占用失败保留旧目标、解除后新ID成功，8/8检查有效。取消JSON的dialog_count=2未记录HWND，可能重复枚举同窗，不能称两次独立保存。错误文案缺陷另列R16，不能据此否定已执行的文件操作 |
| 驱动首次失败 | close-order摘要写入竞态及save-dialog前三次失败原始记录保留。独立实际SFC对照证实旧ack上下文下验证hook runConfirmed会多触发一次原生调用，而真实按钮runExport只触发一次，支持前两次属于驱动步骤问题；第三次日志停于占用目标的保存按钮附近，源码支持同步SendMessage等待嵌套确认的解释，不能精确断定哪个确认按钮首先阻塞。最终逐用例重开及PostMessage修正，不把首次失败改写为成功 |
| 预览 | 最终源码证据为source-run/fix-regression2b.json（32项），不是仍保留的旧fix-regression2.json（31项）；包同为32项。真实fetch status=200且组件按钮结束loading后核对旧预览未恢复、草稿保留，补上上轮只证明settle的缺口 |
| 合成库 | head=20261014_0003_local；2计划v14／v2、16内容、18操作、1日历修订、1配置操作；integrity_check=ok、FK空、WAL；最终原文“关窗前组合最终文字”。verify只显式断言原文，v13仍为观察值 |
| Word | 4份样本与已目视复核样本及本轮package-saves逐字节一致，14,021／14,165／14,443／14,038字节；沿用2／2／5／2页及既有目视范围，不声称本轮重新打开Word或11张截图均为独立全页 |

**门槛解释：** 规格§13.2要求真实WebView2、关闭、原生保存实测，没有规定每一步必须由人手动点击。本轮真实对话框自动化已经补上此前预授权目录不能证明的交付路径；因此“没有手动点击”不再单独作为工程阻塞，历史§11–13所称“原生人工保存未验”应结合这项新增证据读取。实际IME按键、宿主内部许可／保存交错的真实窗口注入仍未执行，程序化CompositionEvent和线程测试不能改称该场景已实测；保留原验证矩阵，不据此发明新产品要求。手动教师体验、WPS、干净机器、Win10、其他DPI／多显示器仍未验，D1产品及发行没有通过。

### 14.7 接续与文档归并

OpenCode下一轮只处理§14.3的R1旧请求通知生命周期与§14.4的R16错误脱敏，先补能失败的正向回归，再修复；保留含R6的已关闭14项保护。补与两条修复直接相关的窗口证据、更新同环境包与真实来源记录，保留167b352b…包及首次失败。Word样本或渲染链未变时复核身份即可，不重复相同页；其他未验保持明确边界。

本轮任务独有要求、首次失败和未验事项已归并实施结果§16及本节，[current.md](../tasks/current.md)更新为R1／R16唯一接续入口。没有代写实现或向其他任务派发消息；不自动启动D2、AI、WebDAV、发行或远程操作。两项关闭并核齐本片证据后再独立判断工程放行，教师产品验收另记。

收尾检查：9份相关文档的225个相对链接／锚点、围栏及行尾空白检查通过；88个实现／测试／构建及桌面依赖文件前后散列不变。`git diff --check` exit 0（既有换行转换提示保留）；未跟踪文档亦直接检查。结果见证据根`review-final-check.json`及`git-diff-check.log`。

## 15. D1B 第六轮修复复审（2026-10-16）

### 15.1 结论与范围

**R16关闭，R1保留P2，新增R17/P1；D1B仍不放行，累计17项中15项关闭。** [实施结果§17](desktop-d1-result.md#17-d1b-r1-旧-request-通知生命周期与-r16-保存错误脱敏2026-10-16-第六轮)已修复§14两条原反例，但新增的异步确认同时留下回包新鲜度问题，并在最终clean检查与冻结之间重新打开输入窗口。R6及其他既有关闭事实保留；R17单独记录本次引入的等待窗口，不把历史R15的组合输入修复改写为未完成。

与第五轮88文件快照比较，变化为App.vue、bridge.ts、d1.components.test.mjs、d1_host_api.py、d1_main.py及两个桌面测试，共7文件。按codebase-memory技能检查当前工具清单，无图查询／覆盖接口，采用限定源码、实际SFC和宿主线程验证，不声称图覆盖。保留原分支及既有未提交工作区；Codex只执行验证并更新审阅／接续文档，没有改仓库实现、测试、迁移或构建脚本，没有安装、重建桌面包、提交、推送或派发实现。

独立临时证据根：`%TEMP%\kgm-d1b-codex-review7-20261016\`。本轮没有启动真实GUI；窗口结论来自OpenCode保留的原始JSON／日志及同源驱动核对。SFC探针执行实际App／Editor／bridge／LeaveCoordinator和Vue，宿主探针使用实际D1HostApi／CloseCoordinator及已安装pywebview的桥调用线程；受控回包、真实文件占用、历史真实窗口分别记录。未读取真实教师库、密钥、旧远程或AI。临时文件不保证长期保留，下面保留最小复现和验收判据。

### 15.2 R17 / P1：最终检查后的等待允许新输入，却仍放行关闭

[App.vue](../../frontend/src/d1/App.vue)第282行在`finishClose`中新增`await waitForCloseVerifications()`，此时[leave.ts](../../frontend/src/d1/leave.ts)已完成IME settle、dirty／identity检查；第290–291行等待结束直接冻结并发送allow，没有重新核对编辑器。等待期间`closeLocked=false`，页面传给Editor的frozen也为false，ready表单仍可输入。其他待确认ID的查询可以持续数秒，因此不只是同一微任务内的理论间隙。

独立`close-gate-late-input.mjs`使用实际App与Editor组件、真实dirty／editEpoch和保存桥：

1. 宿主当前请求为B；一个迟到旧A的查询已产生unknown，但暂扣回包。
2. B两次确认pending，协调器看到Editor为clean，进入finishClose；由于A仍在确认，B等待。断言此时`closeLocked=false / editDisabled=false / phase=ready / dirty=false / B许可数=0`。
3. 在这个可编辑窗口向真实Editor模型输入“等待关闭确认时新输入，必须保存或留页”，递增editEpoch并等待Vue更新。
4. 释放A的unknown回包；A静默退出，B不再检查dirty，发送allow=true。

实际结果：`dirty=true / current_content_version=1 / PATCH调用数=0 / B allow=true / hostState=closing / closeFinalAllowed=true`。正向断言“存在未保存新输入时不得最终放行”**exit 1**。这是实际组件逻辑与受控桥验证，不冒充真实键盘输入、实际数据库写入或真实窗口销毁；但真实宿主对当前pending B、无原生保存时确会接受该许可，明确违反规格§11.3。

**修复验收：** 所有异步等待结束后，最终许可必须仍对应当前编辑器的IME已落定、dirty=false及有效identity；最后的输入核对与冻结之间不得再出现可编辑等待窗口。等待期间出现新输入时，按已确认保存／留页规则处理，不能丢字关窗。覆盖初始clean、刚保存成功、等待中新增普通输入／组合输入、等待超时／失败及请求替代。不得通过禁止正常编辑流程或强制丢弃草稿修改产品行为。优先修复本P1，再核R1，保留R15旧保护。

### 15.3 R1 / P2：第二次确认回包也会迟到并退役当前B

[bridge.ts](../../frontend/src/d1/bridge.ts)第199–203行连续两次pending便返回true；[App.vue](../../frontend/src/d1/App.vue)第369–389行在await后直接把它当作当前权威、退役其他开放请求，没有校验确认期间已接受的新代际。两次查询只防住第一份旧回答；第二份回答也有“宿主已生成、页面尚未收到”的窗口。

确定时序：A第一问pending已到；第二问也在A有效时产生pending但暂未回到页面；A随后超时，B建立并完成两次确认，正在等待原生保存；最后交付A第二问的旧pending。A会被登记并把B加入aborted集合。保存结束后A发送allow，B零许可；真实宿主拒绝A并保持B pending，页面随后查询A unknown而解锁，用户这次关闭没有执行。

`r1-second-confirmation.mjs`对abort(A)先到、abort(A)丢失两变体均得到`A allow次数=1 / B allow次数=0 / hostCurrentId=B / hostState=pending / locked=false`，正向断言**exit 1**。第一变体的撤销发生在A仍属verifying集合时；当前onCloseAborted未记录这个阶段，因此收到撤销也不能阻止旧确认复活。第二变体证明仅补撤销集合仍不够。

`host-second-confirmation.py`独立使用实际CloseCoordinator、D1HostApi和pywebview `js_bridge_call`的工作线程，暂扣第二问的evaluate_js交付，执行生产`_on_timeout(A)`，再创建B并交付B两问，最后交付旧A回答，**exit 0**。实际宿主回执为旧A `accepted=false/state=pending`、查询A unknown、查询B pending。这里显式触发超时回调以加速，没有墙钟等待30秒或实跑WebView2；它验证上述回包顺序并不受宿主锁和线程机制禁止。源码中的“第二次查询后即可确认当前”说明须随修复更正。

**修复验收：** 确认结果必须绑定宿主权威的新旧关系，并在每个await后拒绝已过期的确认；已经接受B后，A的任何迟到确认／request／abort／回包都不能撤销B或改变其冻结。建议由宿主在锁内分配可比较的递增请求代际，与通知／查询结果一并绑定，页面保留已接受代际与本次确认令牌；具体实现由OpenCode完成，不增加组件或改变产品行为。单纯增加第三次查询或延长等待不能消除最后一次回包的相同窗口。覆盖最后一问迟到、重复通知、撤销先到／丢失、三代替换、确认失败及既有原生保存／IME／数据库保存／旧桥Promise等待。保留同ID幂等、最终closing、通信失败冻结和真实在途保存消费。

### 15.4 R16关闭与已修复范围

| 检查 | 独立结论 |
| --- | --- |
| 上轮R1旧request通知本身迟到 | 新增组件正向回归通过；源码与包内真实窗口delayed／lost分别16／15项全true。当前残留在确认回包阶段，不能混作旧反例未修复 |
| R16真实占用 | 原第五轮脱敏探针仅调整输出目录后通过；实际Win32句柄占用、实际save_docx／缓存，首答与缓存为相同固定SAVE_TARGET_IN_USE文案，无路径／临时名／WinError。旧目标保持、临时文件清理；同ID返回原失败，解除后新ID写入成功 |
| R16异常边界 | 实际替换后注入stat失败仍unknown且缓存一致，目标确已替换；选择器异常为固定SAVE_DIALOG_FAILED，最外层异常为固定SAVE_FAILED。独立异常矩阵exit 0；既有内层兜底／XML解析回归也通过 |
| R16真实页面 | 源码与包内save-dialog各9/9；原生对话框占用用例的首答、缓存及DOM result_text均为固定占用文案。首跑错误分类为权限的失败记录保留；最终分类已更正 |
| 其他关闭项 | R6等既有14项保持关闭；本轮R16关闭后共15项关闭。R17是新增等待窗口导致的回归 |

R16限定范围没有新的确定阻塞。真实原生对话框由Win32消息自动化操作的证据有效，不要求重复相同人工点击来替代已有证据；也不把该证据写成教师体验或实际输入法按键验收。

### 15.5 独立自动检查与交付证据

使用现有CPython3.14.7／Windows x64／标准GIL／SQLite3.50.4，`APP_DISABLE_DOTENV=1`、UTF-8输出，清除继承KGM变量。本地套件仅设置临时数据根兜底，不注入父级DB路径。

| 检查 | 本轮独立结果 |
| --- | --- |
| backend下`python -X utf8 -m unittest discover -s tests/local -t . -v` | **133项、0 skip、exit 0，142.908s** |
| 内容校验／安全／日历／API schema／导出读取五组回归 | **108项、0 skip、exit 0，0.723s** |
| `python -X utf8 -m pytest desktop/tests -q -p no:cacheprovider` | **142 passed、exit 0，4.29s**；2项既有依赖弃用警告 |
| `npm.cmd run test:d1`、`npm.cmd run typecheck` | 纯逻辑套件＋**49项组件**、类型检查均exit 0 |
| `npm.cmd run build:d1 -- --outDir <证据>/frontend-build` | exit 0；3个独立构建资产与包逐字节一致；保留500kB分块提示 |
| 包／源码／资源 | 仓内、仓外各**137/137**文件与manifest一致，无额外／缺失／差异；8关键归档模块递归比较所有代码元数据，仅忽略co_filename，均相符；迁移配置／revision／模板一致 |
| 环境与锁 | backend26、desktop46实际版本精确匹配锁、无额外包；业务26包跨环境一致；两套`uv pip check`均exit 0，4份声明／锁保持上轮散列 |

新EXE为14,726,530字节，SHA-256 `8d1a4dbb3a97987552c16b0e7a5d2122d50da27c72e4df9afc1a12aee4a59199`。TOC中18个BINARY的来源文件逐字节匹配，来自`C:\Python314`及D1虚拟环境；上一轮来自Codex缓存的43个DLL本包未再收集，另一个移除文件为旧JS资产。167b352b…及更早包保留。干净构建／发行再现性仍未验证，不推断未证明的ctypes因果，不据此安装、清理或重开选型。

OpenCode仓外11进程逐项returncode=0；阶段检查6／6／28／32／13／13／16／15／9／5／4全true，启动日志和正常返回相符。本轮核对记录与驱动，没有再次启动GUI。新增request变体暂扣的是宿主通知，使用真实超时状态与保存；没有覆盖§15.2–15.3的查询回包等待。所有首次失败记录继续保留。

合成库只读核对：head=`20261014_0003_local`、2计划v14／v2、16内容、18操作记录、1日历修订和1配置操作；integrity_check=ok、foreign_key_check空、WAL；最终原文“关窗前组合最终文字”。Word四样本与本轮`package-compare-saves`及已目视复核样本逐字节一致，14,021／14,165／14,443／14,038字节。普通`package-saves`使用FIX6，与同tag比较运行FIX3不是同一组内容；不能混用。沿用2／2／5／2页及既有目视边界，本轮没有重开Word。

### 15.6 下一步与文档归并

1. **先修R17/P1，再一起收束R1/P2。** 把确认中、已确认、等待保存／IME、发许可、最终closing和撤销统一按请求代际约束；先加入本节两个会失败的正向回归，再修实现。R16／R6保持关闭，不扩大到错误体系、其他业务或全仓重构。
2. **补验并更新同环境包。** 在真实窗口覆盖最后一次确认回包迟到，以及确认等待期间真实表单输入后不得漏存关窗；区分DOM／程序化CompositionEvent／实际IME。保留8d1a4dbb…包、首次失败，记录源码／资产／manifest、仓外临时合成库进程返回码。样本及渲染链未变时继续只核Word身份。
3. **工程放行后安排一次教师流程体验。** 用合成数据走首次设置→写日计划→切日／返回／关闭→重启读取→导出Word，并补实际中文输入法按键。体验问题单独记录；手动体验、宿主内部许可／保存交错真实窗口注入、干净机器、Win10、WPS、其他DPI／多显示器仍明确未验。当前不以这些边界掩盖两条已确认代码问题，也不把自动测试通过写成产品验收。
4. **之后再准备D2规格。** 本轮不启动D2实现、真实AI、WebDAV、发行或远程操作。用户本次要求是审阅和下一步判断，没有自动向其他聊天派发任务。

上一版current中的独有要求已归并至实施结果§17及本节；[current.md](../tasks/current.md)替换为R17／R1与相关补验的唯一接续入口，相关状态索引同步，不新增多轮提示词副本。D0／D1A工程历史与3.12异常保持原结论。

收尾检查：9份相关文档的237个相对链接／锚点、围栏及行尾空白检查通过；本轮快照范围96个实现／测试／构建及依赖文件前后散列不变。git diff --check为exit 0，保留既有换行转换提示；未跟踪文档亦直接检查。结果见证据根review-final-check.json与git-diff-check.log。

## 16. D1B 第七轮修复复审（2026-10-17）

### 16.1 结论与范围

**R1关闭；R17原日计划P1反例已修复，但设置草稿仍可在同一等待窗口丢失，按P2保留R17。累计17项中16项关闭，D1B仍不放行。** R16／R6及其他关闭事实保持。本轮不新增R18：设置残留仍属于R17的“最终检查之后等待、等待中新输入未再检查”问题，收窄缺陷和优先级，不把已通过的日计划修复写成失败。

依据[实施结果§18](desktop-d1-result.md#18-d1b-r17-最终核对窗口与-r1-代际绑定修复2026-10-17-第七轮)、[规格§11.3](../specs/desktop-manual-daily-plan.md#113-离开协调与关闭协议)和上轮§15。对照上轮96文件快照，本轮8文件变化：App.vue、bridge.ts、两个前端测试文件、d1_host_api.py、d1_main.py及两个宿主测试；backend、Editor／Settings／Export、leave.ts与依赖锁保持。保留当前分支及原有未提交工作区；Codex没有修改仓库实现、测试、迁移或构建脚本，没有安装、重建桌面包、提交／推送或派发实现。

按codebase-memory技能完成限定结构核查：索引generation=`2026-10-17T01:34:53Z`，19个证据路径的覆盖查询无记录问题，但freshness为`metadata_changed`，因此以当前源码和散列兜底。查询无未消费分页，不将图中的框架同名边或回调定位当作完整调用证明，不声称全仓覆盖。

独立证据根：`%TEMP%\kgm-d1b-codex-review8-20261017\`；OpenCode根：`%TEMP%\opencode\kgm-d1b-fix7-20261017\`。本轮Codex独立执行SFC反例、自动检查、包身份核对，并启动一次真实WebView2源码窗口验证设置残留；其余源码／包窗口阶段核对OpenCode原始JSON、日志和同源驱动。所有运行只使用临时合成数据，未读取真实.env／密钥／教师库或连接远程、AI。临时资料不保证长期留存，以下记录最小复现和判据。

### 16.2 R1关闭与R17日计划修复通过

| 项目 | 核实结论 |
| --- | --- |
| R1最后一问迟到 | 宿主在锁内分配请求代际，通知及状态回答绑定同一代际；页面确认后再次比较已接受代际，旧回答不能退役已确认的新请求。确认中撤销也被记录。独立`r1-second-confirmation.mjs`对撤销先到／丢失均exit 0：A零complete_close、B单次allow、宿主closing |
| R1既有保护 | 纯逻辑／55组件及146桌面测试通过；含旧request、三代替换、缺代际、同ID幂等、确认失败、IME／保存／旧Promise等待与最终冻结。源码／包lastack两变体各13/13、实际进程returncode 0，A静默、B单一许可与代际1／2有记录 |
| R17日计划原反例 | finishClose等待后再次settle，核对dirty／identity后同步冻结。独立`close-gate-late-input.mjs` exit 0：新输入保留、dirty=true、零PATCH、B显式deny、宿主canceled、finalAllowed=false |
| 日计划窗口补验 | 源码／包late-input-close撤销送达／丢失各16/16、returncode 0；真实DOM输入进入Editor，B deny且内容保留，下一次关窗通过真实PATCH保存，版本+1。组合输入等待与验证门10秒期限有组件回归。此处不等于实际输入法按键 |
| R16与其他项 | R16真实占用脱敏的源码／包save-dialog各9/9证据有效，既有宿主回归通过；R6等保持关闭，不重复派发旧问题 |

### 16.3 R17 / P2：设置页等待期间的新草稿仍被关闭丢弃

[App.vue](../../frontend/src/d1/App.vue)第470行只在进入关闭处理时检查`isSettingsDraftBlocking()`；第296行随后等待其他请求确认。第321–329行最终检查只有`editorBridge.isDirty()`和编辑器identity，设置页的editorBridge为空，因此设置姓名／班级／学期等新草稿不会阻止第330行冻结和随后的allow。SettingsView通过`draft-active`已经正确上报草稿；问题是最终关闭判据没有再次检查它。

**独立组件反例：** 实际App＋SettingsView＋Vue中，宿主当前B；旧A的unknown回答暂扣，B确认并通过初始“无设置草稿”检查，在finishClose等待。此时locked／frozen均false。修改实际profileName模型、等待Vue发出draft-active=true，再释放A；结果`settingsDraftActive=true / configVersion=1 / preview或apply POST=0 / B allow=true / hostState=closing`。正向断言“设置新草稿不得关窗”实际**exit 1**（`settings-close-wait.mjs`、结果JSON及日志）。

**独立真实窗口反例：** `settings-window-probe.py`仅在临时文件中替换验证驱动，加载当前生产源码、独立构建且与包同字节的前端、真实WebView2及真实CloseCoordinator／本机API，使用全新合成库：

1. 首次设置后进入无草稿的设置页。A第一问pending/generation=1在真实宿主产生并暂扣；真实超时路径（验证时缩为1.2秒）撤销A，撤销通知实际送达。
2. 第二次真实关闭创建B，两次pending/generation=2确认；页面open包含B、verifying包含A、locked=false，尚无complete_close。
3. 在实际姓名输入框写入“关闭等待期间修改姓名 REVIEW8”，派发真实DOM input事件；输入框disabled=false，等待实际SettingsView的draftActive=true。此时仍无POST或关闭许可。
4. 释放A回答；A后续查询unknown并静默，B单次allow=true。真实宿主答`accepted=true/state=closing`，窗口closed事件发生，WebView2正常返回、服务停止。正向断言“不得allow／窗口应保留”两项false，进程实际**exit 3**，不是watchdog或驱动超时。
5. 关闭后只读核对该合成库：姓名仍为“验证教师”、config_version=1、配置操作数0，新增姓名没有应用也已随关窗消失。

窗口证据见`settings-window-result.json`、`settings-window-startup.log`、`evidence/evidence-completion.json`。受控部分为暂扣查询回答、缩短真实超时及审计记录；输入经过真实DOM，不声称人工按键／实际IME。该反例直接违反现有§11.3“未确认设置草稿时关闭留页、提示确认或取消”，无须新增产品决定。

**修复判据：** 最终许可之前，在所有等待结束后再次核对当前设置草稿／确认状态，检查与冻结之间不可再留可编辑等待；有草稿则保留设置和全部输入、释放本次pending并提示预览确认或取消。不得通过关窗自动应用或丢弃设置草稿规避问题。补实际App＋SettingsView回归（初始clean、等待中新输入、仍在预览／应用流程、等待失败／超时、请求替代）；保留日计划IME／dirty／identity保护及R1代际保护。真实窗口补同一反例，确认草稿保留后显式取消或完成既有预览／应用，再重新关闭可正常退出。

### 16.4 独立检查与包身份

仍为CPython3.14.7／Windows x64／标准GIL、SQLite3.50.4；Python使用`-X utf8`、`APP_DISABLE_DOTENV=1`、UTF-8输出，清除继承KGM变量，完整本地测试仅设置临时数据根兜底。

| 检查 | 独立结果 |
| --- | --- |
| backend下`-m unittest discover -s tests/local -t . -v` | **133项、0 skip、exit 0，97.030s** |
| 内容校验／安全／日历／API schema／导出读取五组回归 | **108项、0 skip、exit 0，0.644s** |
| `-m pytest desktop/tests -q -p no:cacheprovider` | **146 passed、exit 0，5.15s**；2项既有依赖弃用警告 |
| `npm.cmd run test:d1`、`npm.cmd run typecheck` | 纯逻辑套件＋**55项组件**、类型检查均exit 0 |
| `npm.cmd run build:d1 -- --outDir <证据>/frontend-build` | exit 0；d1.html及2资产与包逐字节一致，保留500kB分块提示 |
| 仓内／仓外包 | 各**137/137**文件与manifest一致，无缺失／额外／差异；8关键归档模块递归比较完整代码元数据，仅忽略co_filename，全部与当前源码相符；迁移INI／revision／模板一致 |
| 依赖 | backend26／desktop46实际版本精确匹配锁、无额外包，业务26包跨环境一致；两套uv pip check均exit 0，声明及锁未变 |

EXE 14,734,848字节，SHA-256 `f243b4473cf5f9d13fcdf9f3b5b2ad2309a0a8fddab92f6be34ae4650db0a2dd`。COLLECT中55个BINARY／EXTENSION条目全部与来源文件一致（18＋37），来源为C:\Python314及D1虚拟环境；旧缓存来源43个DLL仍未收集。与8d1a4dbb…包比，文件名增删仅为新旧JS替换，源码归档／EXE内容另有更新。干净构建／发行再现性继续未验，不据此重开环境选型。

### 16.5 交付证据核对与口径修正

OpenCode最终源码15进程、仓外包15进程逐项实际returncode=0，阶段JSON的checks数量分别为6／6／28／32／5／13／13／16／15／13／13／16／16／9／4，全部true。记录与同源驱动一致；旧request-lost首跑因包装漏代际参数失败的事实保留。R1最后回包、R17日计划新输入与原生保存证据有效，但不覆盖§16.3设置反例。Codex本轮没有再次跑这30个GUI进程，只独立运行了上述设置窗口。

合成包库只读检查：head=`20261014_0003_local`，2计划v16／v2、18内容、20操作记录、1日历修订、1配置操作，integrity_check=ok、FK空、WAL。**§18.7关于最终原文的表述需按阶段区分：** late-input的中间核验确实保存了新输入，但最后又执行clean-ime-close，最终09-15原文为“关窗前组合最终文字”，不是late-input文本。**§18.6／§18.10称clean-ime-close本轮未重复／仅沿用也不准确：** 最终源码及包各有本轮4/4记录；其程序化CompositionEvent仍不等于实际IME按键。此处更正报告口径，不否定对应已执行检查。

Word核对对象为本轮`package-compare-saves`的4份文件，分别与fix6的同名业务样本逐字节一致：14,021／14,165／14,443／14,038字节，SHA前16位`1b3d4e21da0d7a7b`／`05bff8c24cd77d7c`／`6313a2c17b9a7006`／`2d1adb2e4e56975a`。不是普通FIX7的package-saves；沿用既有2／2／5／2页及目视边界，本轮没有重开Word。

### 16.6 下一步与文档归并

1. **OpenCode只收束R17设置页残留。** 先保留会失败的组件与窗口正向反例，再修最终关闭判据，保留R1／R16／R6等16项关闭事实，不扩大为配置体系或关闭协议重构。
2. **补相关验证后更新同环境包。** 保留f243b447…及旧包、首次失败；核对源码／前端／manifest与实际来源，仓外合成库运行并记录进程返回码。样本或渲染链不变时只复核Word身份。Codex复审该残留及必要证据后再判断D1B工程放行。
3. **工程收口后做教师流程体验。** 合成数据走首次设置→写日计划→切日／返回／关闭→重启读回→导出Word，重点补实际中文输入法按键。实际IME、宿主内部许可／保存交错真实窗口注入、人手动保存／教师体验、干净机器、Win10、WPS、其他DPI／多显示器、干净构建与发行再现性仍分开记录，不能把自动检查写成产品验收。
4. **之后再准备D2规格。** 不自动启动D2实现、真实AI、WebDAV、发行或远程作业；也不自动向其他聊天发送任务。

上一版current的R1／R17独有判据已归并§15、本节与实施结果§18；[唯一当前任务](../tasks/current.md)改为R17设置残留及相关补验。同步状态索引，不新增提示词副本；D0／D1A和3.12异常历史保持。

收尾检查：9份相关文档的246个相对链接／锚点、围栏与行尾空白检查通过；快照范围96个实现／测试／构建及依赖文件前后散列不变。git diff --check为exit 0，既有换行转换提示保留；未跟踪文档亦直接检查。结果见证据根review-final-check.json与git-diff-check.log。

## 17. D1B 第八轮修复复审与工程收口（2026-10-17）

### 17.1 结论与适用范围

**R17设置草稿残留关闭，累计17项全部关闭；D1B在当前Windows 11开发机上的工程复审通过。** R1／R16／R6等既有关闭事实不变。D0、D1A工程历史保持。本轮限定审阅没有发现新的阻塞问题，可以结束R17修复循环，进入教师流程体验与实际IME验证准备；不等于D1产品验收、兼容性或发行通过。

依据[实施结果§19](desktop-d1-result.md#19-d1b-r17-设置草稿关闭保护2026-10-17-第八轮)、本报告§16.3及[规格§11.3](../specs/desktop-manual-daily-plan.md#113-离开协调与关闭协议)。与上轮96文件快照相比，仅App.vue、d1.components.test.mjs、d1_main.py共3文件变化。独立从当前App剔除新增最终设置检查和只读settingsDraft验证字段后，散列精确恢复为上轮`39e5b2b1bf13a464…`；生产页面变更限定于这两处。backend、Settings／Editor／Export、leave／bridge、宿主状态机和依赖锁均未变。

按codebase-memory技能执行限定结构核查：generation=`2026-10-17T01:59:07Z`，search／trace／snippet无未消费分页，finishClose确认调用最终设置检查。19个实际证据路径均无记录覆盖问题，但freshness为metadata_changed，使用当前源码及散列兜底；首次误填components/ExportDialog.vue产生missing，已按实际views/ExportDialog.vue更正核对，不将其当产品缺失。图中异模块get／set同名边不作调用证明，也不声称全仓审计。

独立证据根为`%TEMP%\kgm-d1b-codex-review9-20261017\`，OpenCode交付根为`%TEMP%\opencode\kgm-d1b-fix8-20261017\`。Codex只运行独立验证及更新文档；临时探针在证据目录，不改仓库实现、测试、迁移或构建脚本。未安装依赖、重建桌面包、提交／推送、派发其他聊天或连接真实.env／密钥／教师库、旧远程及AI。临时文件不保证长期保留，核心结论与判据记于本节。

### 17.2 R17关闭证据

最终`finishClose`在验证门、IME settle等全部等待后重新读取`isSettingsDraftBlocking()`，有草稿则提示并返回stayed，由既有路径向宿主单次deny；设置检查、日计划dirty／identity检查和freeze之间无await。SettingsView的真实draftActive仍涵盖未确认字段和已打开预览，关闭不会代替用户应用或取消设置。

| 验证 | 独立结果与证据范围 |
| --- | --- |
| 上轮原组件反例 | 原`settings-close-wait.mjs`使用当前实际App／SettingsView／Vue重新执行，**exit 0**：新姓名保留、draftActive及shellDraftActive均true、零配置POST、配置版本1、B单次allow=false、宿主canceled、finalAllowed=false |
| 已确认应用仍在途中 | 补充临时`settings-apply-wait.mjs`：等待中由真实设置组件预览并显式提交，apply回答暂扣；B拒绝关闭，applying=true、预览及输入保留。提交成功且确认上下文更新后draft=false，下次C允许关闭；配置POST始终仅用户发起的预览／应用两次，关闭没有额外提交。**exit 0**，此项为受控API组件证据，不冒充真实数据库 |
| 独立真实WebView2窗口 | 上轮窗口探针加载当前源码、独立构建前端和新合成库，真实A超时撤销／B代际2确认，等待中通过实际DOM input修改姓名。释放A后B deny，真实窗口保持；读取实际输入框值未丢、设置草稿true、locked／finalAllowed=false、POST为空。显式取消后C allow、closed事件发生、服务停止，**9/9、进程exit 0** |
| 窗口后只读库核对 | 姓名仍为“验证教师”、config_version=1、配置操作0；草稿没有被关闭流程自动应用。该库不同于OpenCode已有回归阶段的版本2／操作1合成库 |
| OpenCode新增保护 | 60项组件完整通过；新增普通草稿、打开预览、查询失败、请求替代、10秒验证门超时五组。源码与包内settings-draft-close撤销送达／丢失两变体各22/22；A静默、B单deny、输入保留、显式取消后C单allow且真实关闭、库内配置不变 |

独立窗口文件为`settings-window-probe-final.py`、`settings-window-final-result.json`及对应启动日志；输入沿用探针合成标记REVIEW8，不表示运行了旧前端。受控部分为暂扣回答、缩短真实超时及审计包装，DOM输入不等于人工按键／实际IME。

**首次验证失败保留：** Codex首跑在B已正确deny后，新增取值断言错把data-d1节点始终当作输入框容器，querySelector返回null；驱动异常后尝试关闭再次被草稿保护拒绝，watchdog最终退出3。原`settings-window-result.json`、探针及日志保留；仅修正临时探针的输入框选择方式，在另一个新合成库重跑，得到上述9/9通过。不是产品回归，不将首跑改写为通过。OpenCode原组件exit 1及预修复窗口exit 3也核实保留；其更早HTTP元组未解包失败的stdout被重跑覆盖限制，按§19.2原记录保留，不能宣称该次stdout仍存在。

### 17.3 独立自动检查与交付身份

CPython3.14.7／Windows x64／标准GIL、SQLite3.50.4保持；`APP_DISABLE_DOTENV=1`、UTF-8输出、清除继承KGM变量。本地测试只注入临时数据根兜底。

| 检查 | 本轮独立结果 |
| --- | --- |
| backend下`-m unittest discover -s tests/local -t . -v` | **133项、0 skip、exit 0，83.239s** |
| 内容校验／安全／日历／API schema／导出读取五组回归 | **108项、0 skip、exit 0，0.399s** |
| `-m pytest desktop/tests -q -p no:cacheprovider` | **146 passed、exit 0，4.28s**；2项既有依赖弃用警告 |
| `npm.cmd run test:d1`、`npm.cmd run typecheck` | 纯逻辑套件＋**60项组件**、类型检查均exit 0 |
| `npm.cmd run build:d1 -- --outDir <证据>/frontend-build` | exit 0；d1.html、index-DHhfIjJV.js及index-ILAyuRJW.css与包逐字节一致，保留500kB分块提示 |
| 目录包与源码资源 | 仓内／仓外各**137/137**文件与manifest相符，无缺失／额外／差异；8关键归档模块递归比较完整代码元数据，仅忽略co_filename，全与当前源码相符；迁移INI／revision／模板一致 |
| 依赖与来源 | backend26／desktop46版本精确匹配锁、无额外包，业务26包跨环境一致，两套uv pip check exit 0；55个二进制／扩展条目（18＋37）与C:\Python314及D1虚拟环境实际来源逐字节一致 |

本轮工程通过身份：`KGNext-D1Verify.exe` **14,741,133字节**，SHA-256 **`28e3e60e31615fde859526447b47e0bdbf3f51a56719429a2008510d4c5822a3`**，目录包137文件。与f243b447…包比，文件名增删仅替换JS资产，归档／EXE内容另有更新；旧包仍保留。此前43个缓存来源DLL仍未收集。干净构建／发行再现性没有因此完成，不安装或清理环境。

### 17.4 窗口记录、Word与未验边界

核对OpenCode最终源码`final8-source-phases-result.json`和仓外包`pkg-phases-result.json`：各17进程returncode全0，逐阶段实际JSON分别为6／6／28／32／5／13／13／16／15／13／13／16／16／22／22／9／4，checks全true；包17份startup日志各有一次启动及正常返回。源码设置变体实际使用默认标记D1验证，包使用FIX8，分别对应记录中的输入值；不是两份完全相同字符串，但保护判据一致。Codex核对这些34进程记录，没有声称独立重跑全部窗口；本轮另执行了§17.2的独立设置窗口。

包合成库只读核对：head=`20261014_0003_local`，2计划v16／v2、18内容、20操作记录、1日历修订、1配置操作，姓名“验证教师”、config_version=2，integrity_check=ok、FK空、WAL。最终09-15原文“关窗前组合最终文字”；late-input为此前阶段内容。§18的最终库原文及本轮clean-ime-close执行口径已更正，原失败与历史身份不变。

四份本轮package-compare-saves与fix6已目视复核样本逐字节一致，14,021／14,165／14,443／14,038字节，SHA前16位`1b3d4e21da0d7a7b`／`05bff8c24cd77d7c`／`6313a2c17b9a7006`／`2d1adb2e4e56975a`；沿用2／2／5／2页及已有目视范围，本轮未重新打开Word。真实原生对话框中文名／取消／占用失败／解除重试及R16脱敏自动化证据有效。

工程通过限定于当前Windows 11开发环境、此包及已执行路径。**仍未验：** 教师本人完整体验、实际中文输入法按键、人手动另存为、宿主内部许可／保存交错的真实窗口注入、干净机器、Windows 10、WPS、其他DPI／多显示器、干净构建和发行再现性。程序化CompositionEvent、组件／线程探针、真实对话框自动化与人工体验分别记账；不以工程通过写成D1产品或发行验收。

### 17.5 下一步与接续

1. **结束R17修复循环，先做D1教师流程体验。** 使用28e3e60e…同源包和独立合成数据，按首次设置→日计划输入→切日期／返回／关闭自动保存→重启读取→设置预览／取消／应用→Word导出的顺序执行。重点使用实际中文输入法候选词、未提交组合及快速离开／关窗，不再用程序化事件代替这一项。
2. **分别记录工程问题和产品体验意见。** 体验需用户实际操作与判断；Codex协助记录操作、预期／实际、截图或日志和数据版本。遇到丢字、误关窗、保存或文件交付失败先停止该路径并保留合成库，交OpenCode定点修复；流程／措辞偏好由用户决定，不顺带重构。
3. **体验结论明确后再准备D2规格。** 先限定每日活动计划所需AI触发、输入、任务状态、取消／超时、结果保留与保存边界，再形成实现任务；本次不启动D2实现或真实付费AI调用。WebDAV、发行与远程操作继续后置。当前未提交工作区保留，未自动提交／推送。

上一版current的独有R17验收要求已归并实施结果§19及本节；[唯一当前任务](../tasks/current.md)改为教师流程体验与实际IME验证清单，不新增提示词副本，也不把“下一步建议”写成已执行体验。相关状态入口同步为当前开发机D1B工程通过，D1产品待验。

收尾检查：9份相关文档的252个相对链接／锚点、围栏和行尾空白检查通过；96个实现／测试／构建及依赖文件前后散列不变。git diff --check exit 0，保留既有换行转换提示；未跟踪文档亦直接检查。证据见review-final-check.json和git-diff-check.log。没有KGNext-D1Verify残留进程。

## 18. 教师体验启动核查（2026-10-17，人工验证待执行）

用户明确要求启动最新包后，Codex再次核对28e3e60e…包137文件与fix8 manifest全部一致，以全新合成目录启动交互窗口，未开启selftest或预授权另存为。computer-use确认窗口当前显示首次设置页，尚未填写／提交。启动身份、数据根、环境原值及T1–T7人工清单见[结果§20](desktop-d1-result.md#20-d1-教师流程与实际-ime-体验2026-10-17)。

本次只确认包身份、数据隔离及首次页面可见；真实按键、教师流程、人工另存为和本次新Word样本均待用户操作／反馈。实际备课文档未读取，先用合成文本。§17工程通过结论保持，不能由“窗口已启动”推出D1产品体验或实际IME通过。需要关闭／重启时沿用此次合成库；不自动强关，不启动D2实现或真实AI调用。

**11:03接续：** 用户概括反馈此前步骤均成功并已关闭，现开始重启读回。独立只读核对同一合成库完整性通过，10-19=v3且主题／过程／反思已存，10-20=v1空内容；当前姓名“教师”，既有计划创建姓名“体验教师”。同包同数据根重启后工作台显示两个日期和原版本，没有重新初始化。正文是否符合关闭前实际输入、无修改往返及旧日期修改仍待用户确认；不把概括反馈扩为所有实际IME分支、设置和Word已验。启动与基线见结果§20.3。

## 19. R18 日计划 Word 格式调整（2026-10-17，待实施）

**结论：** 用户确认重启读回一致、修改后v4，并明确使用Windows自带微软拼音；只读库确认v4和实际追加句。该体验结果通过，原R1–R17关闭及§17工程通过历史保持。用户新确认的三项日计划格式要求尚未满足，新增**R18／P2（产品体验格式调整）**；Word格式验收待修复与用户复看，D1产品仍未整体验收。

### 19.1 实际证据与原因

用户指定桌面导出文件“日计划_体验中四班_2026-10-19_2026-10-25.docx”，14,911字节、SHA-256 `6359e832530fc7c378e76a5c19300987e39649da5f5f8cc4f4df10b229d59720`。包含两份日计划，原件未修改，副本及核对JSON见[结果§20.4](desktop-d1-result.md#204-重启读回确认微软拼音与word格式反馈)。Codex本轮为结构核查，用户提供目视反馈，不声称Codex新做Word全页检查。

1. **R18-A 标题居中：** 标题未直接设置jc，默认Normal段落样式jc=both；`word_export_docx.py:753–760`复制模板并仅替换正文，因此仍两端对齐。应对每份标题显式设置center，含空／长园所情况。
2. **R18-B 署名只含班级、教师：** 同文件761–768将grade纳入parts，实际样本为“中班 体验中四班 体验教师”。移除日计划输出中的额外grade部分，保留年级存储、创建快照和班级原名，周计划不受影响。
3. **R18-C 表格全部不加粗：** 实际71个含文字run中54个显式bold=true，过程正文也为true。`_capture_templates`／`_CellWriter`复制单元格首个rPr，导致模板标签加粗传播。需在日计划表格范围覆盖动态文字和固定栏目，并处理继承加粗及bCs，不破坏过程标红、字体字号、结构和分页。

codebase-memory采用Verify级限定追踪：当前图generation `2026-10-17T01:59:07Z`，查到本地 `export_service.generate_docx`和旧入口／D0夹具共用日计划生成器；coverage对5个源码／测试路径报告metadata_changed、模板not_tracked，均回读相关源码或直接解析模板补核。当前源确认本地API→export_service.generate_docx→map_daily_plan→generate_daily_export_docx；不据图作完整无影响声明。共享 `_CellWriter`也用于周计划，定点修改必须限定日计划，旧日计划年级断言需按新规格调整，周计划年级与格式回归保留。

### 19.2 实施与复审边界

用户决定已写入[D1规格§12.4](../specs/desktop-manual-daily-plan.md#124-日计划-word-格式2026-10-17-用户确认r18)及Word Contract，OpenCode按[唯一当前任务](../tasks/current.md)实施生成器／相关输出测试／新包。优先保留受控模板字节，在日计划生成输出定点正规化；如必须修改资产，哈希和包内来源必须同步，不能放宽完整性校验。旧样本、旧包和体验库保留，原文件不覆盖。

复审要求输出级检查单份／多份、空／长园所、快照署名、固定及动态文字、红色run仍非粗体、周计划不变；新包同源并实际生成新Word，逐页核对内容与分页，再由用户确认三项格式。生成链已变，不能再沿用原四份同字节样本直接给出Word通过。已有教案保存和IME反馈保持独立记录，不让格式修改回写计划或增加业务内容版本。

本轮仅记录、核查及更新文档，没有修改实现／模板／测试／构建，没有重建包或向其他聊天派发任务。下一步先处理R18及必要体验接续，不启动D2或发行。

## 20. R18 独立复审（2026-10-17）

**最新结论（含§20.9教师体验收口）：R18三项格式修复的代码、自动检查和新验证包核对通过；用户逐页确认长园所2页、长内容合并7页及起始页1／4／6、署名与表格粗细正常，R18关闭。T6-A／T6-B／T7本轮人工验证通过，当前Windows 11＋Word下本轮教师体验收口。** T6-B配置v4、新旧表头、两份单日文件及退出已核对；微软拼音按用户反馈正常，不再复验或要求覆盖所有输入法。原R1–R17及D0／D1A工程通过历史保持。下一步为D2规格准备，无新增代码修复任务，未启动D2实现；产品与发行未整体验收。本节较早“待补／下一步”记载保留当时状态，以§20.9为准。

### 20.1 代码和回归

- 标题显式 `w:jc=center`、署名只用创建快照的班级与教师、每份日计划表格全部run显式 `w:b=false`／`w:bCs=false`，均符合规格§12.4。按OOXML属性顺序插入，不改字体字号、标红、映射与每份新页规则。共享写入器和周计划路径未改；同一周计划view经旧包生成器与新源码生成的DOCX逐字节一致（SHA-256 `6b479484a53ed57ee0f14b52240864f994204f1fb634cc75fb28493e0e62b288`）。模板字节未改。
- `d1_main.py`增加的 `word-r18`／园所参数属于验证驱动；`build_d1.py`增加独立输出位置。旧包／新包应用PYZ模块对比仅生成器有语义差异；原生对话框类的额外常量差异为Python生成的 `__firstlineno__` 1735→1782，非对话框行为修改。
- codebase-memory限定查询generation `2026-10-17T03:26:52Z`；5个路径coverage有metadata_changed，已以实际源码／diff补核，未依赖图作完整性保证。
- **Codex独立重跑：121项导出相关unittest通过**（生成器、映射、导出读取及本地HTTP导出），**146项桌面pytest通过**；APP_DISABLE_DOTENV=1，独立临时数据，不读真实环境配置。没有为无关前端／关闭链重复全套窗口回归。
- OpenCode的134本地／108回归等日志核对保留；补充692项全量unit中1项错误仍如实保留：既有 `test_disabled_guard_never_connects` 使用 `.venv/bin/python`。该测试在HEAD中已是此写法，工作区未改该文件；是Windows路径适配缺口，不属于R18回归，也不能写成692项全通过。

### 20.2 新包与独立运行

包目录 `build/desktop-d1/package-r18/KGNext-D1Verify`；EXE 14,743,868字节，SHA-256 **`c6dc19283a24d00a740f2ecbed2cc7159e951f02a37f00636b294b7670369930`**。

1. 仓内及OpenCode仓外副本各137/137文件与manifest一致，无缺失／额外／大小或散列差异。12个关键归档模块与当前源码递归代码比较一致（只忽略co_filename，保留行号表、异常表等元数据）；前端入口与2资产、模板及迁移资源逐字节一致。
2. 相比旧28e3e60e…包仅EXE和base_library.zip不同；后者全部成员内容逐字节相同，差异为归档顺序。旧包未被覆盖，干净构建／发行再现性仍不由此证明。
3. 核对OpenCode7次仓外运行逐阶段JSON与返回码：6／6／7／9／6／7／6项全部通过，均独立合成数据，含中文名原生另存为、取消、占用失败保护／脱敏和新ID重试。本轮Codex没有重新独立执行原生对话框自动化。
4. Codex另跑新包3个真实窗口进程：新合成库first **6/6**，长过程保存与单日／范围导出 **7/7**，人工体验库的独立SQLite备份副本读v4并导出 **5/5**；全部exit 0、服务停止。采用验证驱动的预授权保存目录，不声称这些是人工另存为或实际IME按键。

### 20.3 Word文件核对与目视边界

独立解析OpenCode13份DOCX：17份计划表格、582个run，所有标题居中、署名“验证中一班 验证教师”、全部表格run显式关闭两类粗体，0问题。Word对象模型记录共38页、表格非空文字粗体问题0；独立新导出5份DOCX亦通过上述结构检查，长过程在单日和合并文件均完整出现120次。

**体验v4的新文件：** `%TEMP%/kgm-d1b-codex-r18-review-20261017/experience-saves/日计划_体验中四班_2026-10-19_2026-10-19.docx`，14,608字节，SHA-256 `c99b9cb75ab3e858ea042c0a7ce39392a151c875228b856054cfdba69bd9802d`。标题“一日活动计划”居中，署名“体验中四班 体验教师”，38个表格run全部非粗体，含“重启后验证通过。”。园所为空是原创建快照，无需补入当前设置；导出没有增加原计划版本。

目视证据按来源分开记录：

- Codex查看OpenCode保存的非空园所／长园所首页、长过程续页和三计划合并第二／三份首页截图，可见范围内标题与署名正确、文字非粗体、长过程自然续页。**这些100%缩放截图没有显示完整页面，38张逐页位置截图不能等同38页全页目视完成。** 页数和标题页1／4／6来自Word对象模型记录。
- 证据目录实际已有一份由Microsoft Word生成的93,481字节、2页PDF（`word-pdf/日计划_验证中一班_2026-09-14_2026-09-20.pdf`；SHA-256 `fccc61df8440cfe94e1c752840eb0fa9a11de70658eef099d4e6fa6cd8cdb263`）。文字正规化后与A空内容样本完全一致；Codex使用现有Poppler渲染并目视两张完整页，标题／署名／非粗体和两页表格未见截断、重叠。此证据只覆盖该样本，不能代替长内容／长园所全页检查。
- Codex尝试打开新v4 DOCX继续Word整页查看，窗口已打开，但computer-use首次返回 `GetCursorPos failed: 拒绝访问 (0x80070005)`，刷新选择重试后捕获返回 `IGraphicsCaptureItemInterop.CreateForMonitor failed: Could not capture the given monitor (0x80070057)`。按工具恢复规则停止窗口输入；未改Word文件，不把工具失败归为产品缺陷。**本轮没有完成v4和所有长内容样本的独立完整页面查看。**

因此代码修复已得到支持，但全页目视与用户最终格式认可仍是明确剩余项；补验后再最终关闭R18。结构检查／对象模型属性不替代该验收。

### 20.4 数据保护、文档收口与下一步

原体验库只读备份后，仅对副本启动验证包。收尾只读核对原库与此前 `restart-after-user-db.json` 内容一致：10-19仍v4、10-20仍v1，integrity_check=ok、foreign_key_check为空；桌面旧DOCX SHA仍为6359e832…，10个受检实现／测试／模板／构建文件散列未变。实际备课文件未读取；未改实现／测试／构建、未重建包、未提交或推送。

独立证据根 `%TEMP%/kgm-d1b-codex-r18-review-20261017/`：`export-tests.log`、`desktop-tests.log`、`package-independent.json`、`samples-independent.json`、`independent-window-runs.json`、`final-evidence-audit.json`、新样本及PDF渲染图。临时目录不保证长期保留，关键身份与结论已写入本文。

旧current的三项决定、验收门槛与独有证据已归并规格§12.4、结果§20–21及本节；[唯一当前任务](../tasks/current.md)改为新Word复看和剩余体验，依次补：v4及长内容／长园所／合并样本完整页面、T7人工取消后重试、T6设置草稿保护与快照、微软拼音候选词分支及缩放记录。用户已明确的读回一致／v4／微软拼音反馈保持有效，不重新写成“实际IME完全未测”。这些结论明确后再准备D2规格；宿主内部交错注入、WPS、干净机器、Win10、其他DPI／多显示器及发行再现性继续保留边界，不自动启动D2／真实AI／WebDAV／发行。

收尾检查：9份相关文档245个相对链接／锚点、围栏及行尾空白检查通过，git diff --check exit 0；10个受检实现／测试／模板／构建文件散列无变化。没有KGNext-D1Verify残留进程。Word已打开新v4文件，因捕获失败未继续操作或关闭；未保存文档改动。检查记录见 `review-final-check.json` 与 `git-diff-check.log`。

### 20.5 用户确认与Word捕获重试

用户随后说明之前正在使用电脑、关闭了Word窗口，请求重试，并明确“我也看了word，是正常的”。按本轮上下文记为对所交付新Word的用户格式确认；不扩写为已逐页验证长园所和七页合并样本，也不将“可能与使用电脑有关”写成已查明的故障原因。

Codex通过computer-use重新枚举时没有Word窗口，重新打开同一c99b9cb7… v4文件后捕获成功（Word窗口15796846）。切换最大化、打印布局单页47%及白色页面，实际查看第1页完整表格／活动过程与第2页户外游戏／反思及页底；共2页、433字。未见截断、重叠或异常分页，标题与署名位置正常，反思包含此前核实的“重启后验证通过。”。整页图用于布局核对，粗体／完整文字的精确判定结合§20.3的文件结构证据；没有把低缩放截图称为逐字校对。截图在本聊天工具记录中，未另行调用非computer-use截图接口。此项补足v4样本完整页面缺口，与用户正常反馈一致。

随后打开长园所样本（窗口17171470），捕获返回 `IGraphicsCaptureItemInterop.CreateForMonitor failed: Could not capture the given monitor (0x80070057)`；刷新窗口选择后激活重试返回 `failed to activate captured window`。按computer-use恢复规则停止输入，未继续尝试长园所与七页合并样本。重试过程只能证明v4查看阶段恢复可用，不能断定之后失败原因。未修改文档内容或保存；收尾v4、长园所和合并DOCX的SHA仍分别为c99b9cb7…、d72c57f3…、8a0fe5dd…。

**当时剩余：** 30字长园所2页、长内容三计划合并7页的完整页面；T6／T7剩余人工分支、微软拼音候选细分动作与缩放记录保持。用户格式确认与v4两页不再列作待验；当时R18最终关闭仍等待上述长样本页面补齐。仅更新文档和验证记录，未改实现、重建包、改体验库或启动D2。后续用户逐页验收及关闭结论见§20.6。

### 20.6 用户逐页验收与R18关闭（2026-10-17）

用户明确反馈：“两份文件都已逐页检查，长园所2页、合并7页均正常，三天计划分别从第1、4、6页开始，署名和表格粗细也正常。请记录结果，继续下一步验证。”此反馈针对本聊天交付的两份原文件及逐页标准：长园所标题自然换行并居中；长过程／反思自然续页，页底与末尾无截断、重叠或异常空白；署名不额外添加年级，表格内所有文字不加粗。

| 人工验收对象（Microsoft Word） | 文件身份（交付前只读核对） | 用户实际结果 |
| --- | --- | --- |
| `%TEMP%/opencode/kgm-d1b-r18-20261017/package-saves-long-school/日计划_验证中一班_2026-09-15_2026-09-15.docx` | 14,127字节；SHA-256 `d72c57f35c785584527f5d5c83bff0a2fe48072770dfa59822429253f6f28cef` | 完整2页已逐页检查，均正常；署名、表格粗细正常 |
| `%TEMP%/opencode/kgm-d1b-r18-20261017/package-saves/日计划_验证中一班_2026-09-15_2026-09-17.docx` | 14,779字节；SHA-256 `8a0fe5dd2133f7e31ac4c5b522bdfb1df26af471ad60d2dddbbfcaea9c7afbcb` | 完整7页已逐页检查，均正常；9月15／16／17日分别从第1／4／6页开始，署名、表格粗细正常 |

证据来源是用户本人逐页检查及明确反馈，不写成Codex独立看完9页。交付时Codex已在Word显示长园所首页；后续`get_window_state`超时，重新定位后重试仍超时，已停止桌面操作并提供文件链接及人工标准。该工具故障不归为产品缺陷；38张旧位置截图也不改称完整页面截图。

**R18-A／B／C关闭：** 代码、相关自动检查、新包身份／来源、新样本结构、此前v4与空内容样本完整页面以及本次长样本人工逐页反馈共同满足本项收口条件。不重跑已通过且无相关变更的测试，不改实现、测试、模板或构建。T7人工另存为取消／重试、T6设置、微软拼音候选细分动作与缩放仍待逐项验证；产品与发行未整体验收，D2／真实AI／WebDAV／发行未启动。

### 20.7 T7人工反馈与下一步（2026-10-17）

用户针对明确交付的T7取消／重试保存／Word打开标准反馈“验证正常”，本轮人工路径按用户反馈通过；不伪造Codex逐点击旁观。首次检查建议文件不存在，用户随后说明文件已存在并要求复查；现已在同一`exports/另存为验证_2026-10-19.docx`核对14,965字节、SHA-256 `2b2b7f26ae9313ae31fd1fb079134b0d42c2e523140348f8b1e315fbf041fce2`，反思追加句、旧快照署名及72个表格run非粗体正确，文件位置缺口已补齐。实际是10-19／10-20两份计划，不记为单日输出，也不在未知用户范围选择时判定产品缺陷；T6-B导出旧计划时核对单日范围。本次不要求重复取消／重试。完整接续和17:01原库重启见[结果§20.6](desktop-d1-result.md#206-t7人工反馈与t6接续2026-10-17)。

当前先T6姓名／园所预览取消、未应用草稿关窗保护、显式取消编辑后正常关闭；随后沿原合成库重开，验证确认应用与班级／新旧计划表头，再补微软拼音细分动作与缩放。T6及后续项保持待执行／反馈，无新实现／测试／构建变更，不重跑既有通过测试或启动D2。R18关闭及历史工程结论保持，完整产品和发行未验。

### 20.8 T6-A人工通过与T6-B接续（2026-10-17）

用户逐项确认预览取消后草稿保留并阻止关闭、取消编辑恢复原值且配置版本不变、最后正常关闭，T6-A按人工反馈通过。独立日志17:05:28为deny、17:05:42为allow，进程已退出；退出后只读合成库显示配置v2、原姓名／园所／班级，计划10-19 v4和10-20 v1及旧表头保持，完整性通过。配置“未增版本”按用户前后观察记账，不把完成后只读值当作独立前后比较。详情及证据见[结果§20.7](desktop-d1-result.md#207-t6-a通过与t6-b人工验证接续2026-10-17)。

17:07沿同一合成数据根启动新包PID 32032，交付T6-B两次分别预览／确认姓名园所及班级、旧10-19当前日期单份导出、新10-21计划采用新表头及正常关闭标准。当时T6-B、实际IME细分动作与缩放仍待反馈；最新收口及范围决定见§20.9。T7已验保存路径和R18关闭保持，不重复测试、改实现或启动D2。

### 20.9 T6-B复核与本轮人工验证收口（2026-10-17）

用户明确T6-B正常、配置v4、旧表头不变、新表头正确、两份文件各含对应日期一份计划且正常关闭；同时明确微软拼音验证正常、不需要复验、不需要覆盖所有输入法。按此反馈收口，详见[结果§20.8](desktop-d1-result.md#208-t6-b核对与本轮教师体验收口2026-10-17)与[规格§13.4](../specs/desktop-manual-daily-plan.md#134-本轮人工验证范围与收口2026-10-17)。

- 原合成库只读核对：当前姓名／园所／班级为“设置验证教师／设置验证园所／设置验证中四班”，配置v4，配置操作版本2／3／4；旧10-19 v4、10-20 v1的快照与已采纳内容均与已存基线一致；新10-21 v3使用新快照，反思“新设置验证。”。完整性ok、外键检查为空。
- `exports/设置后旧计划_2026-10-19.docx`为14,608字节、SHA-256 `c99b9cb75ab3e858ea042c0a7ce39392a151c875228b856054cfdba69bd9802d`；`设置后新计划_2026-10-21.docx`为14,056字节、SHA-256 `606b7881fe45436cd464a2bb0f3fab85e02910df4cab3f6dfdbd4b295615a579`。各一个计划表格、仅对应日期，新旧标题／署名／反思正确，38／34个文字run非粗体，补齐T7单日文件实证。
- `manual-t6b-startup.log`17:22:12正常allow并消费关闭许可，核对时无应用进程，与用户反馈一致。完整核对保存在原体验根`manual-t6b-final-check.json`；没有采集退出码，不凭日志虚构该值。
- 微软拼音按用户反馈通过；撤销候选词细分与缩放补录待办，不安排复验或穷举其他输入法，也不把未采集动作写为独立实测。后续有具体故障时按实际问题核查。

**T6-A／T6-B／T7与本轮教师体验收口，R18关闭保持。** 下一步可准备D2每日活动计划AI规格；本轮没有更改实现／测试／迁移／构建，没有修改原体验库或导出文件，没有重跑无相关变更的已通过测试，未启动D2实现／真实AI／WebDAV／发行。干净机器、Win10、WPS、其他DPI／多显示器、宿主内部交错注入及发行再现性保留未验边界；不宣称整体产品与发行通过。
