# D1 本地手工日计划技术核查

> 公开版隐私处理（2026-10-30）：本机用户路径、私有部署地址或联系标识已替换为占位符；原始记录由维护者私下保留，历史日期、结论和产物哈希不因此改变。

初次核查：2026-10-11；版本核查更新：2026-10-13；运行时准备方案更新：2026-10-14（§8）。核查者：Codex。基线为 `codex/desktop-v2-foundation`、HEAD `b3c5bbf` 及当前未提交工作区。D0 结论沿用[第三轮复审](desktop-d0-review.md)；初次完成 D1 五项工程契约核查，随后补充 §7 版本决定与 §8 准备方案，均没有写入实现、测试、迁移或构建脚本。

§1–8保留设计、版本选择及运行时准备历史。2026-10-17当前状态：CPython3.14.7标准Windows x64环境／锁及28e3e60e…包已核对，业务26包保持；[最新审阅§17](desktop-d1-review.md#17-d1b-第八轮修复复审与工程收口2026-10-17)关闭R17，累计17项全部关闭，**D1B在当前Windows 11开发机工程复审通过**。独立133／108／146项、纯逻辑＋60组件及前端检查通过，真实设置窗口9/9；137文件包同源，55个二进制／扩展条目与来源相符。实际IME／教师体验、干净构建和发行再现性等仍未验。[实施结果](desktop-d1-result.md)§19及§19.12保留实施、首次失败和工程收口结论。规格见[本地手工日计划](../specs/desktop-manual-daily-plan.md)，[当前任务](../tasks/current.md)为教师流程与实际IME体验清单；其后准备D2规格。OpenCode唯一写实现／测试／迁移／构建，Codex核查、设计与验证。

## 1. 核查依据与边界

按已安装的 codebase-memory 技能处理结构查询；本次没有可调用的图查询工具，使用限定源码读取，不声称全仓库图覆盖。沿用既有 v2 Contract 及非冲突业务规则，未读取真实密钥、旧数据库或远程环境，也未安装依赖。

2026-10-11 用户补充确认：

- 关闭窗口、切换日期、离开编辑页时，未保存内容**自动保存后离开；保存失败则留在当前页**。不扩为定时自动保存或崩溃草稿恢复。
- 首次一起填写姓名、班级名称及年级、学期名称及起止日期；园所名称可以留空后补。
- 技术核查由 Codex 完成，OpenCode 只负责按定稿任务编码，包括实现所需的测试、迁移及脚本。

历史表头已有决定：创建时保存园所、班级、年级、创建教师姓名的不可变快照，见[原手工保存规格的已确认决定](../specs/manual-daily-plan-save.md)。不将其再次列为产品未决项。

## 2. 五项核查结果

| 契约 | 具体源码事实 | 已确定的适配方向 |
| --- | --- | --- |
| 本地身份与初始化 | [deps.py](../../backend/app/deps.py) 的 `get_current_account/get_auth_snapshot` 读取账号会话；[context.py](../../backend/app/routers/context.py) 与 [class_scope.py](../../backend/app/routers/class_scope.py) 依赖角色及分班；[config_service.py](../../backend/app/services/config_service.py) 依赖管理员、账号／配置锁 | 独立本地上下文、单档案稳定 ID、一次原子初始化；不创建假管理员／旧会话，不以隐藏登录页代替替换权限依赖 |
| SQLite／Alembic 基线 | [database.py](../../backend/app/database.py)、[migrations/env.py](../../backend/migrations/env.py) 只接受 MySQL；[models.py](../../backend/app/models.py) 使用 `utf8mb4_bin`、`CHAR_LENGTH`、`use_alter` 及有效日期生成列 | 独立本地 metadata 与迁移链；内联复合延迟外键、有效记录局部唯一索引；保留旧迁移，不把旧 revision stamp 到新库 |
| 保存事务与错误 | [daily_plan_service.py](../../backend/app/services/daily_plan_service.py) 的 `_resolve_date_locked/_lock_plan/is_effective_date_unique_violation` 依赖 `FOR UPDATE`、MySQL 错误；创建／保存／审计须一致 | 显式短写事务 `BEGIN IMMEDIATE`、提交后成功、严格预期版本、按 SQLite 错误分类；读取显式 `BEGIN`，不依靠 SELECT 隐式开启快照 |
| 日计划、周来源与文件 | 同一服务创建／保存调用 `_recompute_sync`，读取 `weekly_sync_summary`；[schemas.py](../../backend/app/schemas.py) 的 `DailyPlanOut` 强制周摘要；[DailyPlanView.vue](../../frontend/src/views/DailyPlanView.vue) 直接展示旧周投影 | 写入、读取 DTO 与页面同时解除旧全班周投影依赖；保留真实内容版本和作者，不增加空周表、假同步成功或新消息组件 |
| 关闭与未保存内容 | `DailyPlanView.vue` 返回事件、[TeacherView.vue](../../frontend/src/views/TeacherView.vue) 的 `planDate=null`、[App.vue](../../frontend/src/App.vue) 设置切页会卸载编辑器；没有日计划 dirty 守卫；`usePendingChange` 只保存配置预览 ID | D1B 增加统一离开协调；数据库提交成功才放行关闭／切日期／切页，失败与 409 保留页和输入；宿主不能直接销毁窗口 |

### 2.1 可复用部分与导入陷阱

- [calendar_service.py](../../backend/app/services/calendar_service.py) 的默认日历与周次算法、[config_normalize.py](../../backend/app/services/config_normalize.py) 的字段正规化可以保留。未知年份与库故障必须区分；日历日缺失是数据错误，不实时补算掩盖。
- [daily_plan_content.py](../../backend/app/services/daily_plan_content.py) 的真实内容结构、组／游戏 ID 验证有复用价值，但它导入 `app.security`，后者加载 `app.config.settings`。D1A 必须先把其所需的 ID 工具抽到不读配置的纯模块，再保留原行为；不能以设置空环境变量假装已消除旧配置依赖。
- [daily-plan-content.ts](../../frontend/src/daily-plan-content.ts) 和真实表单可在 D1B 复用；身份、API 错误、日期入口须适配。旧月历仅用 `date_eligible` 开放日期，未来日历变化后仍须单独提供已有计划打开入口。
- [word_export_mapping.py](../../backend/app/services/word_export_mapping.py) 和 [word_export_docx.py](../../backend/app/services/word_export_docx.py) 可保留映射与 DOCX 生成。D1B 替换身份和数据库读取适配，不重写模板生成器。
- [main.py](../../backend/app/main.py) 会加载旧配置并挂载旧路由；D1 本地 app factory 不导入它。[d0_server.py](../../desktop/d0_server.py) 的回环、会话及精确来源校验可作为依据，探针本身不成为正式业务。

旧 `plans_started_at` 冻结配置是 I2 暂时实施边界，不是桌面永久规则。D1A 不提供配置修改 API；后续维护必须有真实影响预览与版本复核，不能用“影响 0 条”占位，不能因第一份计划出现永久封锁配置。

## 3. SQLite 原语实验

在当前 `desktop/.venv` 的 SQLite **3.49.1** 中，以内存数据库、`foreign_keys=ON` 做了独立实验：

| 实验 | 结果 |
| --- | --- |
| 计划头与内容表的内联循环外键；当前内容 ID／版本非空，复合 FK `DEFERRABLE INITIALLY DEFERRED`；头→内容→提交 | 成功，`foreign_key_check=[]` |
| `(class_id, plan_date) WHERE deleted_at IS NULL` 唯一索引 | 拒绝第二份有效记录；软删后可建立同日新记录 |
| 当前指针跨计划、版本不匹配或内容缺失 | 提交被 FK 拒绝，原状态保留 |
| 新增内容／更新指针后，操作记录 CHECK 失败 | 整个事务回滚，内容、指针与日志一致 |
| MySQL `utf8mb4_bin`／`CHAR_LENGTH` | 当前 SQLite 不可用，应原生适配 |
| STORED 生成列 | 当前 SQLite 可执行；不声称生成列本身不兼容。选择局部唯一索引是为了减少冗余 |
| 学期／计划按 `(term_id,revision_id)` 引用日历修订 | 被引用表须有 `UNIQUE(term_id,id)`；补齐后提交成功、`foreign_key_check=[]`，已纳入规格 |

这是存储原语证据，**不是 SQLAlchemy 模型、Alembic 或真实文件竞态已通过**。D1A 编码后还须验证真实迁移、连接设置、故障提交、两个连接／进程竞争及重启持久化。

官方依据：SQLite 支持[局部唯一索引](https://www.sqlite.org/partialindex.html)和[复合／延迟外键](https://www.sqlite.org/foreignkeys.html)；驱动默认事务模式对 SELECT 的行为须按 [SQLAlchemy SQLite 文档](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html)处理。WAL 的读快照升级写入可能失败，见 [SQLite 隔离说明](https://www.sqlite.org/isolation.html)。具体工程选择固定在规格中，不交回 OpenCode 重新选型。

## 4. Word 与保存的一致性结论

[exports.py](../../backend/app/routers/exports.py) 当前在同一 Session 中先读范围、生成 DOCX，再写成功审计。SQLite WAL 下，生成期间另一个保存提交后，旧读快照升级写事务可能失败。D1B 改为：显式短读事务物化版本与确认事实 → 结束事务 → 生成 DOCX → 如保留生成审计，另开短写事务。原生保存对话框不占数据库事务。

[export_read_service.py](../../backend/app/services/export_read_service.py) 的 `daily_ack_context` 已绑定范围、计划／内容版本及完整缺项事实，继续保留。确认后版本或事实变化，即使缺项减少，也重新返回冲突，不能放宽确认。

导出来源已确定为数据库中的已保存版本，见[Word 实施规格](../specs/word-export-implementation.md)。用户确认的离开自动保存不扩为点击导出也自动保存。服务端生成成功与宿主文件保存成功分别表达；取消或文件占用失败不报已保存。

## 5. 后续切片与剩余事项

D1A 先落实本地数据／API 核心及必要自动验证，Codex 复审实际实现和证据后再交付 D1B。D1B 使用真实页面、已确认的离开自动保存和受限宿主 Word 保存，完成教师可操作闭环。二者共同构成 D1，单独通过 D1A 不代表日计划产品交付。

尚待 D1B 配置维护规格收敛：资料／班级／学期维护的具体交互、已有计划后的修改与切换范围。已有的日历例外优先、影响预览、历史表头快照不重问；不得实现阶段性冻结来代替后续维护。AI、WebDAV、历史恢复界面、删除／恢复入口和发行工作仍按后续切片安排。

原“D1 只读技术核查”提示词的五项问题、继承决定、拟改范围和验证要求已归并到本文与新规格；替换当前提示词，不另存旧提示词副本。

## 6. D1A 验证环境补充（2026-10-12）

用户反馈现有 D0 环境缺少 Alembic，与任务中“不主动安装依赖”发生冲突。Codex 定点核对：`backend/.venv` 不存在；`desktop/.venv` 的 Python 为 3.12.10、未安装 Alembic，基解释器为本机 `Python312/python.exe`；`backend/pyproject.toml` 与 `uv.lock` 已声明并锁定 Alembic 1.20.0、chinesecalendar 1.11.0。

确定采用独立 `backend/.venv`，同步已有锁内依赖，不往 D0 环境追加包，不修改依赖版本或重新选型。`backend/.python-version` 为 3.14，项目最低要求为 3.12；显式指定已有的 3.12.10 并禁用 Python 下载，不修改版本文件。此前笼统禁止安装的提示词已收窄为禁止新增／升级依赖；本片允许下载并安装现有锁定包，仍不安装 Skill／MCP／新解释器。

Codex 在 `backend` 目录执行 `uv sync --locked --dry-run --offline --python <已核实的本机 Python312/python.exe> --no-python-downloads --no-managed-python`，exit 0：预演创建 `.venv`、解析 27 个项目／包条目、下载并安装 26 个包。未实际创建环境或安装包；离线预演不证明下载成功、迁移通过或测试通过。`--locked` 在锁与声明不一致时拒绝修改，依据[uv 官方同步说明](https://docs.astral.sh/uv/concepts/projects/sync/)。

当时的具体命令、目标环境及文件散列要求已归并到[审阅 §3](desktop-d1-review.md)，实际执行见[D1 结果](desktop-d1-result.md)。本节是历史环境准备方案，不是永久锁定 Python 3.12 的架构决定；后续版本选择以 §7 为准。

## 7. Python 版本统一核查（2026-10-13）

用户要求核查 Python 3.15 与现有依赖、桌面运行及打包方案的兼容性，确定统一版本后重新判断 D1B 准入。核查范围为普通 CPython、Windows x64；不把 free-threaded、ARM64、Windows 10 或新打包器纳入本轮。以下区分版本声明、制品可得、上游测试和本项目实测，不以 `Requires-Python` 下界代表全部未来版本兼容。

### 7.1 当前状态与版本决定

**D1 后续开发、桌面宿主和打包统一采用 CPython 3.14.7、Windows x64、标准 GIL 构建。** 这是本阶段明确的工程基线，不承诺永久冻结补丁版本；以后升级补丁或 minor 版本时明确变更并补相应验证，不由工具自动漂移。一级技术栈与架构边界不变。

- Python 3.15.0 已于 2026-10-09 正式发布，不能以“尚未正式发布”排除。[Python 官方发布页](https://www.python.org/downloads/release/python-3150/)
- `backend/.python-version` 已指定 3.14，`requires-python=">=3.12"` 只是安装范围；本机 `backend/.venv` 实际为 3.14.7／SQLite 3.50.4、`Py_GIL_DISABLED=0`，基解释器为 `C:\Python314\python.exe`。本轮 `py -0p` 只列出 3.14 与 3.12，没有现成的 3.15。
- `desktop/.venv` 仍为 3.12.10，D0 包的真实运行证据也基于 3.12；**选定 3.14.7 不等于桌面环境已经切换或新包已经通过**。本轮未改版本文件、声明／锁、解释器或环境。
- 选择 3.14.7 的依据是后端现有锁有完整制品路径且已有完整项目验证；桌面核心工具支持该版本。3.15 需要先处理下述 Pydantic 依赖升级与组合验证，当前没有升级必要性可抵消新增验证范围。3.12 作为历史证据和未解环境问题保留，不再是 D1B 唯一前置门槛。

### 7.2 后端锁定依赖

逐项读取 `backend/uv.lock`、本机发行元数据和 26 个锁定发行版的官方 PyPI 元数据。所有 `Requires-Python` 均允许 3.14／3.15，但制品与支持状态有差异。

| 当前锁 | Python 3.14 | Python 3.15 核查结论 |
| --- | --- | --- |
| Pydantic 2.13.5／pydantic-core 2.46.5 | core 有普通 cp314 Windows x64 wheel，当前已安装 | **core 没有 cp315 或 abi3 适用 wheel**；Pydantic 2.14.0 才正式新增 3.15 支持。当前版本精确绑定 core，不能单独换 core 绕过。[发行制品](https://pypi.org/project/pydantic-core/2.46.5/)、[官方变更记录](https://pydantic.dev/docs/validation/latest/get-started/changelog/#v2140-2026-10-08) |
| SQLAlchemy 2.0.54／greenlet 3.5.6 | 均有 cp314 wheel | SQLAlchemy 官方支持 3.15，锁中可用通用纯 Python wheel；greenlet 有 cp315 wheel。不能把 SQLAlchemy 无 cp315 编译轮说成完全不能安装。[SQLAlchemy 支持说明](https://www.sqlalchemy.org/blog/2026/08/11/sqlalchemy-2.0.52-released/)、[greenlet 制品](https://pypi.org/project/greenlet/3.5.6/) |
| lxml 6.1.3／cffi 2.1.1 | 均有 cp314 wheel | 均有 cp315 Windows x64 wheel；CFFI 2.1.0 已新增 3.15 支持。[lxml](https://pypi.org/project/lxml/6.1.3/)、[CFFI 变更](https://cffi.readthedocs.io/en/latest/whatsnew.html) |
| cryptography 50.0.1 | 当前使用 cp311-abi3 wheel | wheel 标签适用于普通 CPython 3.15；该发行版分类仍只列到 3.14。制品适用不等于本项目已验。[制品与元数据](https://pypi.org/project/cryptography/50.0.1/) |
| FastAPI 0.141.1／Uvicorn 0.53.0／Alembic 1.20.0 | 通用 wheel，已有业务测试 | 通用 wheel 可用；Alembic 分类包含 3.15，前两版分类到 3.14。FastAPI 的实际使用仍受当前 Pydantic 锁限制。[FastAPI](https://pypi.org/project/fastapi/0.141.1/)、[Uvicorn](https://pypi.org/project/uvicorn/0.53.0/)、[Alembic](https://pypi.org/project/alembic/1.20.0/) |
| MarkupSafe 3.0.3 | 有 cp314 wheel | 无 cp315 wheel；其源码允许构建失败后回退纯 Python，性质不同于必需的 Pydantic Rust 核心。[官方构建源码](https://github.com/pallets/markupsafe/blob/3.0.3/setup.py) |

没有断言 pydantic-core 2.46.5 在 3.15 上源码构建必定失败。当前缺的是已支持、可复现的标准制品路径，本轮没有安装编译工具或尝试源码构建。未来若选 3.15，至少要整体审查 Pydantic 2.14 系列及其匹配 core、重新锁定和回归，不能只修改 `.python-version` 后沿用旧验证结论。

### 7.3 桌面与打包链

| 当前桌面锁 | 兼容依据及限制 |
| --- | --- |
| pywebview 6.2.1 | 通用 wheel；Windows 经 pythonnet／WinForms 加载 WebView2。发布分类到 3.13，该标签 CI 的 Windows EdgeChromium 使用 3.8，不能据此宣称 3.14／3.15 已专项通过，也不能据分类缺失判定不兼容。[制品](https://pypi.org/project/pywebview/6.2.1/)、[该版 CI](https://github.com/r0x0r/pywebview/blob/6.2.1/.github/workflows/ci.yml) |
| pythonnet 3.2.1 | 已明确覆盖 3.14／3.15；3.2.0 加入 3.15，当前 wheel 标签包含 cp314／cp315。不能沿用旧版不支持的判断。[发布说明](https://github.com/pythonnet/pythonnet/releases/tag/v3.2.0)、[3.2.1 制品](https://pypi.org/project/pythonnet/3.2.1/) |
| clr-loader 0.3.1 | 通用 wheel，依赖 CFFI；发布 CI 包含 Windows x64 × 3.14，未列 3.15。当前锁的 CFFI 两版均有制品。[该版 CI](https://github.com/pythonnet/clr-loader/blob/v0.3.1/.github/workflows/ci.yml) |
| PyInstaller 6.22.3 | 6.15 已支持 3.14，6.21 加入 3.15；当前有 Windows x64 wheel。PyInstaller 本身不是本轮拒绝直接切 3.15 的原因。[变更记录](https://pyinstaller.org/en/stable/CHANGES.html)、[制品](https://pypi.org/project/pyinstaller/6.22.3/) |
| hooks-contrib 2026.8 | 满足当前 PyInstaller 的 `>=2026.7` 要求；该版 CI 到 3.14。webview／clr／clr_loader hooks 已收集对应数据和动态 DLL，但不代表最终包已运行。[该版 CI](https://github.com/pyinstaller/pyinstaller-hooks-contrib/blob/v2026.8/.github/workflows/pr-test.yml)、[hook 源码目录](https://github.com/pyinstaller/pyinstaller-hooks-contrib/tree/v2026.8/_pyinstaller_hooks_contrib/stdhooks) |

结构核查沿用 codebase-memory 图覆盖检查和针对性源码回读。`d0_main.py` 强制 `edgechromium`；`build_d0.py` 用调用它的 `sys.executable` 打包。修改 backend 版本文件不会自动改变 D0 打包解释器。现有安装中虽有 Python.Runtime、ClrLoader 与 WebView2 动态库，仍须以选定环境实测窗口、JS／Python 回调、对话框、关闭和冻结包，不能只测 `import webview`。

**两套锁不能直接拼接。** 后端／D0 分别锁定 FastAPI 0.141.1／0.143.0、Pydantic 2.13.5／2.14.0、core 2.46.5／2.50.0、Starlette 1.6.0／1.7.0、Uvicorn 0.53.0／0.54.0、pycparser 3.0／3.1；D0 锁没有 D1 的 Alembic／chinesecalendar。D1 准备方案以已通过的 backend 业务锁为基线，补齐已选桌面及构建依赖并解析成一致集合，由 OpenCode 在相应实现任务中维护；不套用 D0 全锁而静默升级业务依赖。

### 7.4 本轮直接验证与未执行事项

仓库根执行 `uv pip check --python backend/.venv/Scripts/python.exe`：exit 0，26 个已安装包声明相容。它只检查安装元数据，不替代业务测试。

另向 `uv pip compile -` 的 stdin 输入 `pydantic-core==2.46.5`，参数为 `--python-version <3.14或3.15> --python-platform x86_64-pc-windows-msvc --only-binary :all: --no-deps --no-python-downloads --no-managed-python --no-cache --no-header --no-annotate`，未指定输出文件：

| 目标 | 结果 |
| --- | --- |
| 3.14 | exit 0，解析得到 pydantic-core 2.46.5 |
| 3.15 | exit 1，`has no usable wheels`；这是禁止源码构建条件下的解析失败，不是 3.15 运行崩溃 |

3.15 命令提示本机缺少该解释器、若构建将用 3.14.7，但本命令禁止源码构建，未安装或启动 3.15；不能称作 3.15 实机测试。没有写 requirements 文件、改锁或安装包。

对照[审阅 §6](desktop-d1-review.md#6-r3r4-收口复审与运行时验证阻塞2026-10-13)的 38 项源码／测试／迁移／依赖散列，全部一致。因此沿用同日 3.14.7 的 87 项本地测试、108 项回归通过证据，本轮不虚报重新执行，也不为文档更新重复跑全套。后端 PyPI 原始证据在 `%TEMP%\kgm-backend-python-compat-20261013\`；本轮解析与版本核查记录在 `%TEMP%\kgm-python-version-review-20261013\`，核心事实以本文为准。

本轮没有执行环境切换、依赖升级、D0 GUI 或新包构建。3.14 桌面实测待后续环境落实；3.15 在本机完全未运行。3.12 的原生异常、失败日志和未知根因继续保留，不宣称已修复。

### 7.5 D1B 准入与统一方案落实

**D1A 本地数据／API 在 3.14.7 基线上工程通过，可以进入 D1B 规格收敛；还不能直接交付完整 D1B 编码。** 3.12 排障不再是唯一准入门槛，这是本次经用户要求开展版本核查后的决定，不是删除失败用例或把旧环境失败改写为通过。正式审阅结论见[审阅 §7](desktop-d1-review.md#7-版本统一与-d1a-放行2026-10-13)。

后续须分别完成：

1. **规格**：明确资料与班级／学期修改、切换及已有计划访问编辑范围；落实多学期上下文、按日期解析、日历新修订／例外、影响预览与确认版本，以及离开协调／关闭握手和 Word 保存接口。必要产品选择交用户，已确认行为不重问。
2. **环境落实**：使用同一 3.14.7 标准 x64 解释器，在独立 D1 桌面环境中形成一致业务／桌面／打包依赖集合，明确解释器约束及可复现命令。保留 D0 环境与旧包，不就地覆盖；不能把 D0 的 3.12 成功证据重新标作 3.14。
3. **验证**：环境对齐后先做依赖导入与完整 D1A 测试，若共同依赖改变则重跑相关回归；用真实 WebView2 窗口验证回调、关闭与原生保存／取消／占用重试，再以同一解释器构建目录包、复制仓外运行。此为后续环境和桌面集成的验证任务，不要求本轮改实现。

后续由 OpenCode 写入版本／依赖／测试／构建改动，Codex 审阅和执行验证。当前只完成兼容核查、版本决定与文档更新，不启动 D1B 编码、安装、发行或远程操作。完整 D1 的真实业务、Word 全页、用户体验，以及干净机器／Win10／WPS／其他 DPI 仍保留各自未验身份。

## 8. D1 统一运行时准备方案（2026-10-14）

本节是后续 OpenCode 的环境、依赖及构建实施设计；**方案已确定，环境未切换，组合锁未生成，3.14 桌面及新包未验证**。§1–7 的结论、3.12 失败及 D0 证据全部保留。本轮只读声明、锁、相关源码、本机工具帮助及官方发行元数据；没有安装、重新解析依赖、运行测试、启动 GUI 或构建包。

### 8.1 核查事实与环境归属

- 现成解释器 `C:\Python314\python.exe` 的直接输出为 CPython **3.14.7 / MSC v.1944 / AMD64 / 64bit / win32**，`Py_GIL_DISABLED=0`、SQLite **3.50.4**。`uv --version` 为 **0.13.1**。使用这一基解释器，不下载 Python，不选择 `3.14t`、ARM64 或 PATH 中的其他 Python。
- 新 D1 环境固定为仓库内 **`desktop/.venv-d1`**，当前不存在；其运行／测试／构建解释器统一为 `desktop/.venv-d1/Scripts/python.exe`。保留 `backend/.venv`、`desktop/.venv`、`build/desktop-d0` 及已有仓外 D0 包。不从 D0 环境复制包，不对其 `pip install`／`uv pip sync`，不使用 `--clear` 重建既有目录。
- 当前 backend 以 `pyproject.toml + uv.lock` 声明／锁定业务依赖，`requires-python=">=3.12"`，`.python-version` 为 `3.14`。这是依赖声明范围，不能替代 D1 的精确运行时检查。后续将 backend 和 desktop 的 `.python-version` 固定为 `3.14.7`，不为此修改 backend 的 `requires-python` 或重新求解其锁；既有 v1 范围与失败证据不随版本文件变更消失。
- 当前 desktop 使用 `requirements-d0.txt`、`requirements-d0-dev.txt` 及安装后 freeze 的 `requirements-d0.lock.txt`，没有 desktop `pyproject.toml/uv.lock/.python-version`。选择新增 D1 requirements 输入和一份完整安装锁，不新增一套会漂移的业务项目声明。D1 安装锁由 backend 的声明和锁共同派生，不能脱离业务基线维护。
- [D0 构建器](../../desktop/build_d0.py) 使用调用它的 `sys.executable`，但入口、前端输出及包名都固定为 D0。D1 必须新增独立构建入口／输出，不能把调用旧构建器或修改版本文件记为 D1 包完成。[本地路径](../../backend/app/local/sqlite.py) 使用 `KGM_LOCAL_DATA_DIR`／`KGM_LOCAL_DB_PATH`；[运行时](../../backend/app/local/runtime.py) 接受显式数据目录；[迁移加载](../../backend/app/local/migrate.py) 仍依赖 `alembic-local.ini` 和 `migrations_local` 的资源位置，冻结包必须带入并按冻结资源定位验证。

本节结构核查采用 codebase-memory Verify，项目 `C-Users-yw980-code-kindergarten-manager-next`，图 generation `2026-10-13T11:42:36Z`。相关源文件 coverage 为 `metadata_changed`，声明／锁部分为 `not_tracked`，缺失路径不当作结构结论；已按真实路径回读上述源文件、依赖声明和锁。不声称图覆盖完整，也不扩大为全仓审计。

### 8.2 声明、锁及拟改文件

| 文件／位置 | 后续 OpenCode 改动与责任 |
| --- | --- |
| `backend/.python-version`；新增 `desktop/.python-version` | 均为 `3.14.7`；运行／构建入口另核对实现、补丁、架构及 GIL，禁止只依靠版本文件 |
| `backend/pyproject.toml`、`backend/uv.lock` | 业务依赖权威基线；本环境准备不改内容，前后 SHA-256 必须一致 |
| 新增 `desktop/requirements-d1.in` | 仅声明已选桌面／测试／打包依赖，见下文；业务直接依赖从 backend 的 pyproject 输入，不复制手写业务依赖列表 |
| 新增 `desktop/requirements-d1-build-constraints.txt` | 隔离源码构建工具固定为 `setuptools==84.0.0`；不得让临时构建环境自行取最新 setuptools |
| 新增 `desktop/requirements-d1.lock.txt` | 面向 Windows x64／普通 CPython 3.14.7 的完整、含 hash 安装集合；由单次依赖求解生成，人工不得拼接／删冲突行 |
| `.gitignore` | 增加 `.venv-d1/`（当前 `.venv/` 不覆盖该目录）；沿用已有 `build/` 忽略规则 |
| 新增 `desktop/build_d1.py`、D1 宿主入口及资源定位；前端 D1 构建入口／配置 | 使用同一解释器产出 `build/desktop-d1/package/KGNext-D1Verify` 的 onedir 验证包；带入真实 D1 前端、本地迁移及受控 Word 模板；不重写 D0 构建器。具体宿主／页面责任见 D1 规格 |
| D1 实施结果及审阅记录 | 记录基线散列、求解差异、命令、版本、日志、自动测试与人工验收，不将准备方案当执行结果 |

`requirements-d1.in` 的初始明确输入为 `pywebview==6.2.1`、`pythonnet==3.2.1`、`clr-loader==0.3.1`、`pyinstaller==6.22.3`、`pyinstaller-hooks-contrib==2026.8`、`pytest==8.4.2`、`httpx==0.28.1`、`proxy-tools==0.1.0`。pytest／httpx 仅用于测试，PyInstaller／hooks 仅用于构建，不增加教师功能。其他传递依赖由求解器判断并写入锁；首次与 D0 相比的新增／版本差异须逐项记录，后续重生成不传 `--upgrade`，依赖变更须有明确任务。

**业务 26 包必须逐个等于 backend 锁。** 当前基线为：Alembic 1.20.0、annotated-doc 0.0.5、annotated-types 0.8.0、AnyIO 4.15.1、CFFI 2.1.1、chinesecalendar 1.11.0、Click 8.5.0、cryptography 50.0.1、FastAPI 0.141.1、greenlet 3.5.6、h11 0.16.0、idna 3.20、lxml 6.1.3、Mako 1.4.1、MarkupSafe 3.0.3、pycparser 3.0、Pydantic 2.13.5、pydantic-core 2.46.5、pydantic-settings 2.15.0、PyMySQL 1.2.3、python-dotenv 1.2.3、SQLAlchemy 2.0.54、Starlette 1.6.0、typing-extensions 4.16.0、typing-inspection 0.4.4、Uvicorn 0.53.0。项目条目 `kindergarten-manager-backend` 不属于安装发行包。

因此，相对 D0 锁的 FastAPI 0.143.0、Pydantic 2.14.0、core 2.50.0、Starlette 1.7.0、Uvicorn 0.54.0、pycparser 3.1，D1 均取上述已通过业务版本；同时补上 D0 缺少的 Alembic、chinesecalendar、Mako、MarkupSafe、pydantic-settings、python-dotenv、PyMySQL、cryptography。保留后两项在完整业务环境中不表示本地应用导入旧 MySQL 配置或连接远程；本轮不顺带裁剪 backend 的 v1 依赖。

**一个已知源码制品例外：** [proxy-tools 0.1.0 官方发行页](https://pypi.org/project/proxy-tools/0.1.0/#files)只有 `proxy_tools-0.1.0.tar.gz`，无 wheel，SHA-256 为 `ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010`。本轮仅在内存读取官方 sdist 的 `setup.py`，其用 setuptools 打包纯 Python 包、无 `install_requires`，未执行源码。后续允许这一精确制品在隔离构建环境中以固定 setuptools 构建；保存构建日志及产物 hash。不能给完整集合写 `--only-binary :all:` 后声称方案可安装；其他包必须使用普通 Windows x64／通用 wheel，出现其他源码构建、额外编译器或新依赖要求则先停下审查，不静默换包。源码安装例外不等于已验证其在 3.14 上运行。

### 8.3 后续执行命令与中止条件

以下为 **OpenCode 获得实施任务后** 执行的 PowerShell 7 命令；本轮没有执行。要求从新建、专用 PowerShell 进程执行，结束即退出该进程，避免把隔离环境变量留给日常应用；不输出全量环境变量或读取 `.env`。不得继承会重定向解释器、安装目标、依赖覆盖或额外索引的 `UV_*`／`PIP_*` 设置；如存在，先仅在该专用进程消除重定向并记录变量名，不输出可能带凭据的值。使用 `uv 0.13.1` 已核对的本机帮助；换 uv 版本须重新核对参数。`$ErrorActionPreference` 不保证原生命令失败即停止，故每个原生命令均检查退出码。

准备记录及隔离路径：

```powershell
$ErrorActionPreference = 'Stop'
$d1Repo = '<LOCAL_USERPROFILE>\code\kindergarten-manager-next'
$d1BasePython = 'C:\Python314\python.exe'
$d1Env = Join-Path $d1Repo 'desktop\.venv-d1'
$d1Python = Join-Path $d1Env 'Scripts\python.exe'
$d1Evidence = Join-Path $env:TEMP ('kgm-d1-runtime-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $d1Evidence | Out-Null
Start-Transcript -Path (Join-Path $d1Evidence 'commands.log') | Out-Null
Set-Location -LiteralPath $d1Repo
$env:APP_DISABLE_DOTENV = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:KGM_LOCAL_DATA_DIR = Join-Path $d1Evidence 'data'
$env:KGM_LOCAL_DB_PATH = Join-Path $env:KGM_LOCAL_DATA_DIR 'kindergarten.db'
$d1Baseline = Join-Path $d1Evidence 'backend-baseline.txt'
$d1BaselineHashes = Get-FileHash backend/pyproject.toml, backend/uv.lock -Algorithm SHA256
$d1BaselineHashes | Format-List | Out-File (Join-Path $d1Evidence 'business-before.txt')
& $d1BasePython -X utf8 -c 'import sys,sysconfig,struct; assert sys.implementation.name == "cpython" and sys.version_info[:3] == (3,14,7); assert sys.platform == "win32" and struct.calcsize("P") == 8 and sysconfig.get_platform() == "win-amd64"; assert sysconfig.get_config_var("Py_GIL_DISABLED") == 0; print(sys.version,sys.executable,sys._base_executable)'
if ($LASTEXITCODE -ne 0) { throw '目标解释器核对失败' }
```

导出**不带 hash 的临时版本约束**；此文件仅供求解约束，不是第二份安装源。`--locked` 必须成功，不使用跳过声明一致性检查的 `--frozen`。再将 backend 声明与桌面输入一起重新解析，生成唯一完整 D1 锁：

```powershell
uv export --project backend --locked --no-dev --no-emit-project --no-hashes --format requirements.txt --output-file $d1Baseline --python $d1BasePython --no-python-downloads --no-managed-python
if ($LASTEXITCODE -ne 0) { throw '业务锁与声明不一致或导出失败；不重锁业务基线' }
uv pip compile backend/pyproject.toml desktop/requirements-d1.in --constraints $d1Baseline --build-constraints desktop/requirements-d1-build-constraints.txt --python $d1BasePython --python-version 3.14.7 --python-platform x86_64-pc-windows-msvc --generate-hashes --output-file desktop/requirements-d1.lock.txt --default-index https://pypi.org/simple --no-python-downloads --no-managed-python
if ($LASTEXITCODE -ne 0) { throw 'D1 统一集合不可解；保存冲突，不删除约束或升级业务包' }
```

此命令不承诺已经可解。解析失败须记录冲突链、Python／uv 版本及输入 hash；禁止为求解成功放宽业务版本。求解成功后，以下命令核对 `uv.lock` 的 26 个 registry 发行项与 D1 锁，并检查业务文件未变。要求报告 `missing=[]`、`changed={}` 和完整 `added` 集合；对照本节已选依赖说明每项新增的依赖来源，另检查源制品仅有上述 proxy-tools 例外。**这些核对完成前不安装。** 不把 “47 个旧锁包的并集” 当作预期依赖数；解析结果才决定实际必要集合。

```powershell
@'
import json, pathlib, re, tomllib
norm = lambda s: re.sub(r"[-_.]+", "-", s).lower()
backend = tomllib.loads(pathlib.Path("backend/uv.lock").read_text(encoding="utf-8"))
expected = {norm(p["name"]): p["version"] for p in backend["package"] if "registry" in p["source"]}
locked = pathlib.Path("desktop/requirements-d1.lock.txt").read_text(encoding="utf-8")
actual = {norm(n): v for n, v in re.findall(r"(?m)^([A-Za-z0-9][A-Za-z0-9_.-]*)==([^\s;\\]+)", locked)}
missing = sorted(expected.keys() - actual.keys())
changed = {n: [v, actual[n]] for n, v in expected.items() if n in actual and v != actual[n]}
added = {n: actual[n] for n in sorted(actual.keys() - expected.keys())}
print(json.dumps(dict(business_count=len(expected), missing=missing, changed=changed, added=added), ensure_ascii=False))
assert len(expected) == 26 and not missing and not changed
'@ | & $d1BasePython -X utf8 -
if ($LASTEXITCODE -ne 0) { throw 'D1 锁偏离已通过业务基线' }
$d1AfterHashes = Get-FileHash backend/pyproject.toml, backend/uv.lock -Algorithm SHA256
if (Compare-Object $d1BaselineHashes $d1AfterHashes -Property Path,Hash) { throw '业务声明或锁被改变' }
```

随后创建并同步独立环境。首次若目标存在即停止，核对所有者与已有内容；不得自动覆盖。后续同一已核实 D1 环境只执行锁内 sync。

```powershell
if (Test-Path -LiteralPath $d1Env) { throw 'D1 环境路径已存在；先检查，禁止覆盖' }
uv venv $d1Env --python $d1BasePython --no-project --no-python-downloads --no-managed-python
if ($LASTEXITCODE -ne 0) { throw 'D1 环境创建失败' }
$d1WheelOnly = ((Get-Content desktop/requirements-d1.lock.txt | Select-String '^([A-Za-z0-9][A-Za-z0-9_.-]*)==') | ForEach-Object { $_.Matches[0].Groups[1].Value } | Where-Object { $_ -notin @('proxy-tools', 'proxy_tools') }) -join ','
if (-not $d1WheelOnly) { throw 'D1 锁包名读取失败，禁止无约束安装' }
uv pip sync desktop/requirements-d1.lock.txt --python $d1Python --require-hashes --build-constraints desktop/requirements-d1-build-constraints.txt --only-binary $d1WheelOnly --strict --default-index https://pypi.org/simple --no-python-downloads --no-managed-python
if ($LASTEXITCODE -ne 0) { throw 'D1 安装失败；保留日志和环境，不绕过 hash/版本/源码制品限制' }
uv pip check --python $d1Python
if ($LASTEXITCODE -ne 0) { throw 'D1 依赖不相容' }
```

安装后重复精确解释器／架构／GIL 核查，增加 `sys._base_executable`、SQLite 版本、`importlib.metadata` 发行版本与本地实际包清单的记录；确认基解释器为 `C:\Python314\python.exe`，26 项业务发行版仍相等。构建隔离环境的 setuptools 也须固定为 84.0.0，不能只检查最终环境中恰好存在的版本。保存声明／锁／受控模板 hash、pip check 输出、源码构建日志与完整安装日志；出错不改写为“环境准备完成”。

### 8.4 验证顺序、命令与通过门槛

顺序是依赖与导入 → D1A 完整回归 → D1B 新增测试及前端检查 → 源码真实宿主 → 同解释器构建 → 仓外真实包。前一层失败时保留证据并修复，不继续把下层结果计为通过。以下 Python 命令统一使用 `$d1Python -X utf8`；每个命令均独立记录开始／结束时间、退出码和日志。不得使用旧环境测试结果代替新组合验证。

```powershell
& $d1Python -X utf8 -c 'import sys,sysconfig,struct,sqlite3; assert sys.implementation.name == "cpython" and sys.version_info[:3] == (3,14,7) and sys.platform == "win32" and struct.calcsize("P") == 8 and sysconfig.get_platform() == "win-amd64" and sysconfig.get_config_var("Py_GIL_DISABLED") == 0; import fastapi,uvicorn,sqlalchemy,alembic,pydantic,lxml,chinese_calendar,webview,clr,clr_loader,PyInstaller; print(sys.executable,sys._base_executable,sqlite3.sqlite_version)'
if ($LASTEXITCODE -ne 0) { throw '解释器或依赖导入失败' }
Push-Location backend
try {
    & $d1Python -X utf8 -m unittest discover -s tests/local -t . -v
    if ($LASTEXITCODE -ne 0) { throw '完整 D1A 套件失败' }
    & $d1Python -X utf8 -m unittest tests.unit.test_i3_content_validation tests.unit.test_security tests.unit.test_calendar_boundaries tests.unit.test_i3_api_schemas tests.unit.test_i5_export_read_service -v
    if ($LASTEXITCODE -ne 0) { throw '业务相关回归失败' }
} finally { Pop-Location }
```

当前 D1A 基线是 **87 项、0 skip**，相关回归 **108 项、0 skip**；D1B 添加测试后按实际增长记录，不把数目写死为只运行旧用例。环境首次统一后上面两组均执行，即使 26 项业务版本不变，也验证桌面组合未破坏它们。若共同依赖发生经审查的变更，按真实影响补回归，不仅跑导入；不能禁用异常进程用例。D1B 新增配置／日历／Word API、离开协调与宿主用例按规格的验收表执行，必须独立记录，不能计入旧 D1A 已通过的证据。

| 后续阶段 | 具体执行及通过条件 |
| --- | --- |
| 前端与宿主自动检查 | OpenCode 完成 D1 前端入口和测试后，仓库根运行 `npm --prefix frontend ci --no-audit --no-fund`、`npm --prefix frontend run typecheck`；各检查退出码。D1 构建脚本需调用 D1 Vite 配置并使用已锁 `package-lock.json`，不得退回旧云端入口。宿主 pytest 用新解释器运行其实际测试目录，记录实际用例与结果 |
| 源码真实 Windows／WebView2 | 在 `$d1Evidence` 内独立合成数据库运行正式 D1 宿主；填写首次设置、建立真实日计划、手工保存、切日期／返回日历／进设置／关闭窗口，检查实际 JS↔Python 回调与服务关闭。覆盖保存失败留页、409 保留输入、保存中再输入、重复离开；不能用 D0 自检替代这些 D1 行为 |
| Word 原生结果 | 同一合成数据覆盖单日／范围及缺项确认后对象变化；确认数据库已保存版本导出且不加版本。分别记录生成失败、原生取消、文件占用失败、释放占用后重试、实际保存成功；成功必须有真实文件。真实 Word 全页查看每页（含分页、表头与末页），WPS 不可用则记录未验 |
| 构建 | 后续新增 `desktop/build_d1.py` 的契约为以 `sys.executable -m PyInstaller` 构建、输出 `build/desktop-d1/package/KGNext-D1Verify`。命令 `& $d1Python -X utf8 desktop/build_d1.py`；入口尚未存在，本轮不可执行。记录解释器与依赖锁 hash，收集 WebView2／pythonnet 资源、前端、Word 模板、本地 Alembic ini／迁移。`--windowed` 的无标准流处理须保留；完成后对包逐文件 hash |
| 仓外目录包 | 将上述整个 onedir 目录复制到新的 `$d1Evidence\package-outside\KGNext-D1Verify`，不只复制 exe。使用新的 `$d1Evidence\packaged-data` 并同步更新 `KGM_LOCAL_DATA_DIR`／`KGM_LOCAL_DB_PATH`，从不同 cwd 启动 exe，记录前后 PID、进程退出与端口释放。至少三个独立进程完成首次写入、重启读取与继续修改、再次重启核对；库必须留在指定合成目录，迁移及模板必须从包内定位 |

包复制与启动命令在后续包存在、源目录和目标绝对路径核对后使用：

```powershell
$d1Package = Join-Path $d1Repo 'build\desktop-d1\package\KGNext-D1Verify'
$d1OutsideParent = Join-Path $d1Evidence 'package-outside'
if (-not (Test-Path -LiteralPath (Join-Path $d1Package 'KGNext-D1Verify.exe'))) { throw 'D1 包缺失' }
New-Item -ItemType Directory -Path $d1OutsideParent | Out-Null
Copy-Item -LiteralPath $d1Package -Destination $d1OutsideParent -Recurse
$env:KGM_LOCAL_DATA_DIR = Join-Path $d1Evidence 'packaged-data'
$env:KGM_LOCAL_DB_PATH = Join-Path $env:KGM_LOCAL_DATA_DIR 'kindergarten.db'
$d1OutsideExe = Join-Path $d1OutsideParent 'KGNext-D1Verify\KGNext-D1Verify.exe'
$d1Process = Start-Process -FilePath $d1OutsideExe -WorkingDirectory $d1Evidence -WindowStyle Normal -PassThru
# 完成对应人工步骤后检查进程退出；后续进程继续使用同一 packaged-data。
```

此命令用于后续明确安排的人工 GUI 验证，故展示可操作的产品 WebView2 窗口；后台辅助进程另用隐藏窗口，不能把隐藏启动当作真实交互验收。D1 宿主必须沿用明确的数据目录注入，并在验证日志中输出实际解析的数据目录，核对其位于本次 `$d1Evidence` 内后才进入业务步骤；若未实现或未采纳隔离变量，停止运行，不能回退默认教师库。迁移 CLI 使用 `KGM_LOCAL_DB_PATH`，宿主使用 `KGM_LOCAL_DATA_DIR`，二者始终指向同一合成目录。测试通过不授权访问 `%LOCALAPPDATA%\KindergartenManager\data`、旧 MySQL、远程资源或真实 AI。

### 8.5 结果分类与交接边界

每个阶段结果分别标为 **通过／失败／未执行／受阻**，附实际命令、退出码、环境身份、输入与产物 hash、日志路径、自动测试数量／skip 及人工逐项证据。上面的 transcript 记录专用命令会话，执行结束后 `Stop-Transcript`；另保留各测试／GUI／构建的结构化结果及截图，不能只给一段总日志。原生异常要同时保留 Windows 退出码、空日志事实和发生阶段；不得反复重试至偶然通过后抹掉失败。安装／构建中途失败保留 D1 新目录供定位，不删除 D0 环境或旧证据；修复后记录新一次验证，并指向原失败。

目前可交给 OpenCode 的是本节已经明确的统一运行时准备设计和 D1 规格所列实现工作项，**不是已经完成环境切换或验证的承诺**。开始实施须使用更新后的唯一任务入口；本轮用户授权仍只覆盖文档与只读核查。完整 D1B 编码准入还以本轮规格及审阅结论为准。本节不新增发行授权；干净机器、Win10、WPS、其他 DPI 与用户体验继续按对应证据分别列为未验。
