# 完整本地备份／恢复：Codex 独立核查

更新：2026-10-31。状态：源码整合已完成，用户 P01–P05 已确认；**B1 r04 在当前 Windows 11 后端源码／合成工程范围独立通过**，最终证据见 §8，首失败及回修见 §5–§7。恢复核心 r02 限定源码／合成工程及最终 16 项故障矩阵已独立通过（§17）；宿主回修及 B3 源码窗口仍待独立通过；P06已由用户确认首次启动与设置页都提供恢复入口，不重复已确认决定。继续由指定 Go 模型实施、Codex 独立审核回修，通过后原 OpenCode 正常提交推送；不发行。有效规格见[备份与恢复](../specs/desktop-backup-restore.md)，任务入口见[current.md](../tasks/current.md)。

## 1. 起始与授权

源码整理先行完成，原 OpenCode 已普通提交推送 `b0cc53b02c0c3f04e026ab683541a4c25c3a318a` 并快进 main，见[整合核查](desktop-source-integration-review.md)。业务源码与 `0e45f076…` 一致；备份部分尚未写实现。

用户已授权继续原会话 `ses_ead8af71dffeJphI1NOWg4jZgI`、build、`opencode-go/deepseek-v4.1-flash#max` 实施，Codex 独立审核，不通过交回修复，通过后由 OpenCode 正常提交推送。随后用户进一步允许多个 OpenCode 会话并行；以明确文件责任分工，原会话仍负责共享核心和最终 Git，辅助会话先准备 B2 合同及不冲突的完整合成夹具。所有会话同一指定模型，不 fork 原会话、不另派子代理；不调用应用真实 AI、WebDAV、发行或受阻 EXE。此前单会话核查保留各自当时范围。

## 2. 已独立执行的设计核对

- Graph-first 查询运行时、模型、凭据和图片导入；18 个候选路径在 coverage 中均为 metadata_changed，已针对材料依赖的函数／字段回读源码，范围缓存排除保持。不能把索引的未报告问题当成完整性证明。
- AST 盘点当前 41 个本地业务模型表，另有 `local_alembic_version`；head 为 `20261025_0006_local_game_observations`。这不是从真实业务库导出的数据，不读取原库内容。
- 直接确认 SQLite WAL／backup、全生命周期运行锁、图片先准备后事务登记、原图与两种衍生图路径、DPAPI 独立主密钥与数据库密文关系，以及启动恢复不自动发送的分类代码。现有迁移备份只有数据库，不能称完整备份。
- 复用已安装 `cryptography==50.0.1` 做一次合成原语探针：Scrypt `N=2^17,r=8,p=1` 约 0.352 秒，流式 GCM 合成往返成功。未新增／升级包，未写备份实现，未使用真实密码或凭据，不据此宣称协议或数据安全已验收。
- 开工前 5 个原业务／配置／凭据源 hash 与前轮私有记录一致，并保存本轮保护基线。后续验证只使用显式独立合成源和目标。

私有证据保存在 `kgm-source-backup-20261030`；只公开范围与结果，不提交原始路径、密钥、日志或业务数据。PowerShell 的一次未引用 Git tree 表达式造成只读命令解析失败，已改为引号包围后重跑，得到正确 tree；不是产品失败。文档搜索的不存在路径及 Windows glob 误用也已收敛为现有文件及 `rg -g`，不将无结果当成能力不存在。

## 3. 待核定与后续门槛

用户已逐项确认 P01–P05：手动完整受管业务备份；预览确认后替换当前档案、保留恢复前完整保护副本；每次可选择是否密码加密；保留加密凭据行而排除 DPAPI 材料；先保护当前工作、等待生成／导入完成，再在备份期间暂停写入。已归入规格，不重复询问，P03 不能改写为强制加密。

详细容器、KDF 参数／容量和全部写入口的屏障覆盖、成组切换／启动恢复均尚待工程合同及真实合成验证。B1、B2、B3 各自通过后更新本报告；保留首失败和回修过程，不以实现者摘要替代独立证据。

原业务与凭据、旧包及私有证据保留；源码、窗口、教师体验与冻结发行分开记结论。D3 长根206、SAC4551、跨机／用户、Win10及其他原未验范围保持。

## 4. B1 工程合同首轮审阅

源码与产品说明收口的 10 份文档、140 个相对链接及敏感定点检查独立通过，原 OpenCode 正常提交推送 `e836726f008676fc603a7b4cb058e5d96cafe60b`，桌面分支和 main 均普通快进至该提交；tree=`c6a139c619f696765d128fefbcb4970cff2af973`，与批准清单逐 blob 一致，无业务代码变化。此为 B1 编码前基线。

原私有 B1 合同首轮不能直接通过，Codex 核定修正见[规格 §9](../specs/desktop-backup-restore.md#9-b1-开工合同核定)：

| 编号 | 独立发现 | 处理与通过条件 |
| --- | --- | --- |
| BC-R01 | 顺序先阻止 DB 写、再等待 AI 最终提交，会互相等待；先 freeze 新 claim／SEND 还可能让旧排队任务停住。属于设计静态发现，尚非已运行产品失败。 | 两阶段维护意图／排空／独占；已接受工作可完成，新外部请求不能进入；必须以真实并发验证，取消不撤销／重发 AI。待实现独立复验。 |
| BC-R02 | 先判断目标不存在再 `os.replace`，会覆盖最后提交前并发创建的同名文件，与合同“已有目标不覆盖”冲突。 | 最后提交使用原子 no-replace，增加最后阶段创建目标的反例，原文件字节保持。待实现独立复验。 |
| BC-R03 | 声称 cryptography Scrypt 配置 maxmem=256MiB；本机安装 API 签名只有 salt、length、n、r、p、backend。 | 去掉不存在的参数／保证；固定并预检 KDF 参数，实测有界内存。待实现核对。 |
| BC-R04 | 清单允许 256MiB，配合 Python 对象及多份中间表示缺少可信内存边界。 | 上限收敛为 64MiB，流式大包／资源处理，避免无界 read_bytes／全包堆积；按实际容量与峰值验证，不能仅以常量宣称通过。 |

这些是工程方案修正，不新增用户决策或改变 P01–P05。继续由原 OpenCode 按核定合同实施 B1，Codex 随后审实际代码、反例及必要回归；尚无 B1 通过结论。

## 5. B1 r01 独立审核：未通过，交回原实现者

原 B1 CLI 自然 exit 0、停写后，Codex 私下保存全部 9 个实现／测试改动文件，固定 426 个 backend／desktop／frontend 源码及资源路径。专项测试由 Codex 独立执行 **14 passed，17.49 秒，exit 0**；这不关闭下列反例。实现者另报的 144＋99 回归保持实现者证据，不混称 Codex 已独立执行。

11 个不同独立反例最终取得实际结果：真实图片导入在搬移后、DB 提交前遇备份，仍成功完成，备份包含全部 3 个资源，此项通过；其余 10 个反例暴露以下问题。它们来自固定 r01 源身份，不能因后续回修改写为首次即通过。

| 编号 | 独立复现／源读 | 必须修复及通过条件 |
| --- | --- | --- |
| B1-R01 屏障与计数 | 独占 lease 内进入 AI 内部写 scope，仍成功取得 writer slot；重复 BEGIN 报 OperationalError、rollback／close 后 active_counts 仍为 `[1,0]`。 | AI／旧操作的延续权限只允许穿过 intent，绝不能穿过 exclusive；原子登记及配对释放支持失败、rollback、close、嵌套及跨线程。lease/token 绑定正确，保留已通过的真实在途导入行为。实际 HTTP 变更在维护期应有可理解的受控拒绝，不能泄漏普通 RuntimeError 为无解释 500。 |
| B1-R02 目录替换与清理 | 在独立私有目录内，DB 阶段将输出父目录移到同一探针根下，再建立受控 junction。备份报 `BACKUP_DB_UNREADABLE`，路径式 `shutil.rmtree` 随后误删“外部”对照目录里的 keep marker；全部对象均为本次探针自建。 | 输出、资源来源、隔离区及清理须受实际目录／文件句柄和身份约束，不靠先 lstat 后路径重开。父目录改名／链接替换要被锁住或拒绝，清理不能跟随替换后的祖先。不使用不可信路径上的通用递归删除；失败保留对照文件全部字节。 |
| B1-R03 加密明文暂存 | 选择密码加密，在 DB 阶段仍于用户选择的目标目录下发现带 SQLite 文件头的完整明文数据库。 | 明文 DB／资源／ZIP 和解密载荷进入应用管理、受当前用户权限保护的隔离区；加密交付目标卷上的临时输出只能是加密模式。临时材料清理同样满足 R02。 |
| B1-R04 不可信 schema | 合法合成库添加名为 `sqliteXprobe` 的未知无害 trigger，校验接受；另以相同表／列及合法行重建但移除全部 PK/FK/CHECK/unique 保护，仍接受。源中 `NOT LIKE 'sqlite_%'` 将 `_` 当通配符；只比列名不能验证 schema。 | 精确排除 SQLite 内部对象，核对该 revision 的可信结构／列型／键／约束／索引等；迁移前先验证旧已知 schema，迁移后再核对目标。不能只凭 revision、列名和无 FK 错误信任缺失 FK 的库。未知 trigger／view／virtual object 均拒绝。 |
| B1-R05 严格清单与成员 | 同一合法包改为重复 JSON key、未知字段、NaN、bool 格式版本，以及添加未列入清单的额外资源，5 种均被接受。 | 严格 JSON／字段／类型／范围，拒绝重复键和非有限数；成员、manifest 和 DB 登记项精确一一对应。静态补充：在 ZipFile 构造／infolist 分配大量对象前也须预检中央目录字节／成员预算，不能仅事后检查 len。 |
| B1-R06 旧库包 | 真实从空库升级至已知 0005，制作包含原 DB 字节／hash 的完整格式 1 包；verify 在隔离迁移后报 `BACKUP_MANIFEST_INVALID`，原 0005 文件保持。 | 原始清单先对原始 DB／资源／AI 契约校验，再隔离迁移并保留源／目标各自 revision、hash／逻辑证据；迁移后的物理 DB hash 不应拿来否定原包 hash。整包验证必须通过，不仅直接调用 validate_database 的旧库单测。 |
| B1-R07 取消和提交终态 | 最终 no-replace 发布刚完成即发取消信号，create 返回 `BACKUP_CANCELLED`，最终文件仍存在。源读还发现 SQLite backup 及加解密内部缺少分块取消回调。 | 发布前可取消，提交后完成状态单调且与实际文件一致；预先计算必要信息，不能在已提交后因取消／进度回调报假失败。实际 DB／加解密大包能有界响应取消，不假称 KDF 可即时中断。 |
| B1-R08 容量与证据 | “600 图／31MiB”夹具直接写 `x`／`y` 字节、登记为 JPEG，并非可解码照片；tracemalloc 不涵盖 native Scrypt／SQLite／Pillow 内存。 | 用真实可解码的至少 600 张原图及必要衍生图、大于 30MiB 的完整包，检查实际内容／引用／字节、整体工作内存及边界。补日计划＋多观察＋留存历史／来源、AI 成功／失败／unknown／合法旧契约和合成密文等非空材料；如实分列实测／故障注入／未验。 |
| B1-R09 坏图 | 将已被当前稿引用的原图替换为无效 JPEG 内容，同时在合成库更新对应大小／hash 及草稿聚合 hash，仍成功交付 verified 包。 | 不能仅用与包一起可篡改的元数据证明图片有效；结合现有 E03 格式／尺寸／解码／引用边界校验，拒绝坏图并保护原数据。保留合法历史参数和原始图字节，不擅自重编码或删历史。 |
| B1-R10 私有产物忽略 | 新格式确定后，`git check-ignore --no-index example.kgmbackup examples/backup.KGMBACKUP` 实际无命中、exit 1；当前规则不排除此类完整业务包。 | 由原 OpenCode 最小更新 .gitignore，覆盖新包与实际私有工作目录及嵌套／大小写，并保持模板、公开资源和锁文件可跟踪；提交白名单不能代替长期忽略规则。 |

私有反例分别保存在 `codex-b1-probes-574d0f35`、`codex-b1-probes-0d30f290`、`codex-b1-probes-6182c5af`。首轮路径夹具尝试以文件方式运行 PowerShell，被本机执行策略阻止，**当时未执行的路径项不能计为产品通过**；原日志和夹具已保留。只改为同等原生内联命令后才取得 R02 的实际复现，没有修改执行策略、SAC 或其他系统保护。

专项与反例执行前后 **426 路径零变化、5 个原业务／配置／凭据源和 2 个旧包 hash 均保持**。回读会话元数据：从本轮开始至 r01 交接的新 165 条 assistant 均为原会话 build／`opencode-go/deepseek-v4.1-flash#max`、无 parent；skill／execute 实际仅为已装 codebase-memory 与工具检索，无子代理或另起实现运行。当前不 Git、不接 B2，全部问题交回同一原实现者修复，再由 Codex 独立复验。

## 6. B1 r02 独立复验：原反例通过，补充反例仍未通过

2026-10-31，原 r02 与两个辅助会话均已自然 exit 0、停写。Codex 保存实际改动源副本，固定 **430 个 backend／desktop／frontend 源码及资源路径**。辅助夹具只新增 `backup_fixture_support.py` 与 `test_backup_fixture_support.py`；恢复合同只写私有文件，未提前接入 B2。

Codex 独立执行：

- `pytest tests/local/test_backup_snapshot.py tests/local/test_backup_fixture_support.py -q -s`：**30 passed，82.32 秒，exit 0**；16 条既有 SQLite datetime adapter 弃用提示。实现者的其他回归不混称独立执行。
- 首轮 **11 个反例复跑全部通过，exit 0**，包括真实在途导入、旧版完整容器、坏图拒绝、严格清单、事务计数和发布后取消。输出父目录替换实际被句柄阻止，自建对照文件保持。
- 使用辅助完整夹具实际生成密码备份并校验：包 **1,408,541 bytes**；41 张业务表全部字段（包括运行字段）规范化指纹相等，12 个图片资源文件字节集合相等，原合成库保持。包含非空日计划、多类型观察、8 份历史、仅历史引用照片、AI 成功／failed／unknown 和合成密文；不宣称所有 41 表都非空，不等于 B2 已恢复或真实窗口已验。
- 失败进入目录守卫的句柄全部释放、凭据根名为 `backup-work` 时工作根避让，两项新增反例通过。

下列实际反例仍失败，**B1 不通过、不 Git、不接 B2**：

| 既有编号 | r02 实际失败 | 必须修复及通过条件 |
| --- | --- | --- |
| B1-R02 | 对真实 `verify()` 返回、已 detach 的隔离区，在清理 `lstat` 后、`scandir` 前注入受控改名及 junction 替换。`discard_verified()` 返回 success，却删除同一私有合成根内“外部”对照目录的 keep marker。只拒绝预先存在的链接未覆盖该竞态。 | 清理实际遍历的目录身份和祖先须持续受句柄约束，不能检查一次后用可替换路径递归；逐层异常及 detach 后清理同样满足要求。对照对象全部保持，不能静默跳过或把失败记作清理成功。 |
| B1-R04 | 合成库仅将凭据材料约束中的 `state <> 'active'` 改为 `state <> 'ACTIVE'`，其语义已变，当前校验仍接受。`_normalize_sql()` 对完整 SQL `casefold()` 会混同字符串常量，PRAGMA 也不反映 CHECK 文本语义。 | 可信结构比较须保留引号内的值、大小写、空白与转义语义；不能以破坏常量的文本归一化当作可信等价。既有完整旧库包仍须接受。 |
| B1-R10 | `git -c core.ignorecase=false check-ignore --no-index examples/backup.KgmBackup`：无命中，exit 1；lower／UPPER 两条规则遗漏大小写敏感环境下的混合扩展名。 | 最小规则覆盖任意扩展名大小写和嵌套工作目录，保持正常公开资源可跟踪。 |

新增安全反例属于可控时序注入，使用本轮自建临时根、无真实业务或外部文件。私有结果分别为 `codex-b1-r02-probes-9af7b449`、`codex-b1-r02-extra-a13dda19`、`codex-b1-r02-full-small-76740504`；原始失败及命令退出码保留。此次 coverage 工具连接返回 `Transport closed`，已直接回读相关实际源码；不以图谱未报问题推断完整性，不安装工具。

上述测试、反例和完整夹具往返前后 **430 路径零变化，5 个原保护源及 2 个旧包 hash 保持**。600 图专项已在该次独立 30 项中运行；完整夹具的 600 图大包、密码模式 Windows 整体内存测量留待最终修复源复验，不能由 1.4MB 小包外推。恢复合同提出的外部维护 lease 接缝归 B2 工程整合，不借此提前实现恢复。

## 7. B1 r03 独立复验：继续修复同一清理与隔离边界

原 r03 自然 exit 0 后，Codex 固定同一 430 路径，确认相对 r02 仅 4 个实现／测试源及忽略规则变化。独立重跑原 **11 个反例与新增 4 个反例全部通过**，schema 常量语义和 detach 隔离区清理已取得修复证据。另以 `core.ignorecase=false` 核对 7 个大小写／嵌套包和私有目录样例全部命中，模板、前端锁文件及 LICENSE 三个公开对照均未忽略。未在已知失败源重复执行全量专项或容量。

继续沿同一安全边界检查，实际仍发现：

| 既有编号 | r03 独立实际结果 | 回修要求 |
| --- | --- | --- |
| B1-R02 | 冷缓存构建可信 schema 后的 `_canonical_schema()` 仍以 `shutil.rmtree(..., ignore_errors=True)` 清理临时目录。在其检查后、遍历前注入同样的自建目录／junction 替换，备份返回 success，自建对照 marker 被删除。 | 此处也必须使用持续绑定目录身份的安全清理，覆盖 B1 的全部清理入口及异常路径，不把 schema 临时区视为天然安全。 |
| B1-R03 | 只计算路径的合成配置将数据根设为固定 fallback 目录，凭据根置于其下；首次候选冲突后，`_snapshot_work_root()` 直接返回与现用数据根相同的 fallback。该探针不创建目录、不写默认根。 | 每个候选及 fallback 均重新检查与数据根、凭据根的重合／包含及别名；无安全候选则在创建工作区之前受控拒绝，不能只检查第一个候选。 |

私有结果 `codex-r03-boundaries-4309038c` 的两项均实际完成、exit 1。首版审计脚本因 r03 删除未使用的 `backup_validate.os` 导入而未进入 schema 清理注入；只改为直接钩住 Python `os.lstat` 后，才取得上述实际失败。首版脚本／日志保留，未执行的项不计为产品失败或通过。

原 11 项结果 `codex-b1-r02-probes-7f060951`，4 项结果 `codex-b1-r02-extra-c51df051`；全部独立执行前后 **430 路径零变化，5 个原保护源及 2 个旧包 hash 保持**。继续交回原会话 r04，不 Git、不接 B2。辅助恢复合同已收敛；其中“与更新互斥”按既有单一维护操作落实，本轮不启用源码下载／安装，无需重复产品确认。

## 8. B1 r04 最终独立结论：限定后端源码工程通过

2026-10-31，原 r04 自然 exit 0、停写后，Codex 固定 **430 个 backend／desktop／frontend 源码及资源路径**。后续仅由原 OpenCode 对齐新增带摘要后缀的工作目录忽略规则及其结果记录，没有改动这 430 路径；后端测试与该配置修正的证据分别核对。

| Codex 独立执行 | 实际结果 |
| --- | --- |
| `pytest tests/local -q --durations=5` | **796 passed，904.05 秒，exit 0**，包含本片 35 项与既有全部 local 回归；16 条 SQLite datetime adapter 弃用提示。 |
| 首轮 11＋补充 4＋同链边界 2 个反例 | **17 项全部通过**；冷 schema 与 detach 清理的实际替换均被阻止，自建对照字节保持；旧完整包、AI／事务计数、真实在途图片、严格清单、坏图与取消终态均复验。 |
| 完整合成档案的密码大包 | **157,647,029 bytes（约 150 MiB）**；604 张真实原图、1,812 个资源文件。41 张业务表全部字段（含运行字段）的规范化指纹一致，全部图片路径／大小／字节 hash 一致；仅历史引用照片保留。原合成库与合成 DPAPI 材料保持，网络连接尝试 **0**。 |
| 真正非空 0005 完整容器 | 源 DB **446,464 bytes**，由空库真实升级到 `20261023_0005_local_history` 后经服务建立资料；完整包 **447,595 bytes**。隔离升级至 0006，26 张原业务表的原有字段／行全部保持，15 张新增表为空，日计划版本 1–4 及恢复收据保持；源 revision/hash 单独保留，原文件及现用合成库未改，网络连接尝试 **0**。 |
| 大小写敏感 Git 忽略检查 | 10 个包／嵌套／混合大小写／新摘要后缀目录样例均命中；模板、前端锁文件、LICENSE 三个公开对照未忽略。新后缀最初漏匹配清单文件（exit 1）已由原 OpenCode 最小对齐；没有为此重复后端测试。 |

大包探针测量整个夹具建立、加密和两次校验进程：Windows `PeakWorkingSetSize` 为 **489,267,200 bytes**，`PeakPagefileUsage`（commit charge）为 **533,716,992 bytes**；基线分别为 116,482,048／96,514,048 bytes。使用原生进程计数器的峰值，包含 native 分配，不以 tracemalloc 或仅定时采样替代；校验完成约 139 秒。该实测不外推到全部硬件、上限填满或其他系统。

完整夹具含非空日计划、多类型观察、历史／来源／恢复回执、AI 成功／failed／unknown、合法旧参数及合成密文；不宣称全部 41 表都非空。非空旧库材料准备时自行加入的 `PRAGMA optimize` 产生非应用 schema 的统计表，已从材料脚本移除、按真实 0005 规范重新生成对照并保留首次记录；另有未关闭合成连接的清理失败也已保留。以上为夹具构造过程，不混称 B1 产品失败；Codex 对最终源文件的独立整包验证如表所列。

最终测试前后 **430 路径的集合与 hash 零变化，5 个原业务／配置／凭据保护源、2 个旧包 hash 均保持**。私有最终回执 `b1-r04-independent-final-receipt.json`；大包 `codex-complete-capacity-4dcb925b`，非空旧库 `codex-known0005-598abbba`，反例分别为 `codex-r03-boundaries-273e6c84`、`codex-b1-r02-extra-24df5812`、`codex-b1-r02-probes-c75d1562`。不提交原始日志、图片、DB、备份或个人路径。

核对会话元数据：原会话相对本任务基线新增 **562** 条 assistant、合同会话 **98** 条、夹具会话 **293** 条，均为 build／`opencode-go/deepseek-v4.1-flash#max`，无 parent／fork；历史会话更早的默认 variant 不混入本轮统计。没有另派子代理或安装工具。

**结论：BC-R01–R04、B1-R01–R10 在本节实际后端源码／合成范围关闭，B1 通过，可按批准清单由原 OpenCode 普通提交推送，再接 B2。** 不把验证展开的隔离副本称为“已恢复当前档案”。B2 保护副本／同一维护 lease／成组切换／启动接续、旧身份退役及宿主 UI，B3 源码窗口、教师实际体验、冻结包、Win10、跨机器／用户、真实断电、真实磁盘不足／权限故障与技术上限填满仍未验。D3 长根206、SAC4551 等既有边界保持；未真实调用供应商、未 WebDAV、未发行。

B1 Git 收口：原会话按 Codex 批准的 **20 个文件／逐 blob** 正常提交推送 **`7d2759b76a16528e3e42d720a9203be40b6383a1`**，parent=`e836726f008676fc603a7b4cb058e5d96cafe60b`，tree=`b89cda2846a78f64859760bbb30934a24fd8e86b`。Codex 独立核对完整树、所有批准 blob、远端桌面分支一致、工作区 clean、430 源 hash 保持；main 仍为整合基线 `e836726`、远端 tag 数 0。未 force／amend／rebase／改默认分支或可见性，未发行。私有回执 `b1-independent-git-receipt.json`。

## 9. B2-S1 共享接口设计首审（尚未编码）

原会话仅设计的 67 行共享捕获合同可采用现有 `SnapshotResult` 和独占 lease 的接口边界；独立源读发现调用者顺序尚不充分：先排空／freeze、再建立 intent，仍会给新外部 AI 提交留空隙，也可能把已排队任务冻住。另需用本轮唯一 freeze owner，不能重复字面量 `restore` 让旧释放命中新操作。

核定修正已归入[规格 §10.1](../specs/desktop-backup-restore.md#101-b2-s1-共享捕获接口核定待实施及独立验证)：intent 先行、已接受工作先排空、AI live／queued 终结后 freeze／exclusive；捕获还须只读拒绝“执行器看似 idle 但 DB 仍有 queued”的错误调用，不在 exclusive 内等待写库。以上为设计发现，不能称 B2 已运行失败或接口已通过。B1 结论保持，待 B1 Git 后由原会话实施此接缝，再独立审核。

2026-10-31 产品入口补充：用户直接确认 P06，首次启动与设置页都提供恢复入口，仍预览确认及保留恢复前空业务档案完整保护副本。已归入规格 §1；不影响 B1 已核定源身份，B2／B3 须验证两个入口。

## 10. B2-S1 独立结论：共享维护捕获接口通过

2026-10-31，原会话按明确冻结指令停止实现写入并自然 exit 0；Codex 固定 **430 个源码／资源路径**，相对 B1 仅 `backup_barrier.py`、`backup_fs.py`、`backup_snapshot.py`、`test_backup_snapshot.py` 四个路径变化。结构工具再次返回 `Transport closed`，本片按实际源码逐段核对，不将图谱缺失当作代码缺失。

| 独立执行 | 实际结果 |
| --- | --- |
| `pytest tests/local/test_backup_snapshot.py -q --durations=3` | **39 passed，89.60 秒，exit 0**；33 条既有 SQLite datetime adapter 弃用提示，含真实 600 图与密码模式回归。 |
| 既有 11＋4＋2 反例 | **17 项全部通过**，包括实际目录替换拒绝、受控外部 marker 保持、在途真实图片与取消终态。 |
| 新增六组合成 S1 审计 | **6/6，通过**；完整 41 业务表全部字段与 12 资源字节一致，保护包 1,408,493 bytes；成功后 DB/file/新 intent 仍受阻，调用者 lease、其他 freeze owner 均保持。错误根／类型／token、发布前失效、排队 AI、非私有目标、同名目标、取消与回调异常受控拒绝；普通 create 仍允许普通目标目录，发布后取消仍返回完成。 |
| 首次空档案 | 没有教师资料的 head 库可捕获并正常校验完整保护包，无需先建临时档案；仅为 P06 后端接缝实证，未验页面入口。 |
| 非空 0005 完整包复验 | 原库 26 张业务表原有字段／行、日计划版本 1–4 及回执保持，隔离升级至 0006；原包／现用合成库不改，网络连接尝试 0。 |

测试前后 **430 路径集合和 hash 不变，5 个原保护源及 2 个旧包保持**。新审计结果 `codex-b2-s1-2f0f98f4`，反例 `codex-b1-r02-probes-b3132f10`／`codex-b1-r02-extra-e775237f`／`codex-r03-boundaries-7d9dcd02`，旧库 `codex-known0005-81fa5c08`；私有回执 `b2-s1-r01-independent-receipt.json`。不把实现者自行运行这些脚本计为独立证据，不重复累加 B1 的 796 项。

**结论：B2-S1 共享接口在本节源码／合成范围独立通过，可交恢复核心调用。** 固定 `capture_maintenance_protection(*, lease, output, cancel, progress=None)`／`validate_exclusive_lease(lease)` 能力与调用顺序；本轮尚未 Git。B2 成组切换、启动接续、旧身份退役、宿主和首次／设置页入口、B3 窗口与教师体验仍未通过，其他未验与不发行边界保持。

## 11. B2 恢复核心实施合同核定

辅助合同已收敛，先交 `restore_*.py`／对应测试、Runtime 保锁关闭／重开及启动接续、配置 HMAC 轮换给辅助原会话；共享快照文件和宿主／API／既有前端仍归原会话，不并行写共同文件。第三会话的纯面板合同已核定，另行明确授权仅新增 `BackupRestorePanel.vue`／`backupMaintenance.ts`／`d1.backup-ui.test.mjs`，可与核心并行，不接真实宿主。面板维护锁不能直接混入其自身等待排空的旧 pageBusy；丢回包按同一 requestId 查询、提交前可退出预览，setup 仅恢复。尚无组件或窗口通过结论。

工程裁决已归入规格 §10：旧组物理身份在关闭／检查点稳定后固定；新组核对后在开放新写之前持久退役 active journal，receipt 归档失败可凭已落盘 terminal 继续、启动重试归档，但 terminal 失败不重开。正常后续编辑不得因安装时 hash 改变被回滚；同操作旧 journal 重放也不得覆盖新工作。目录身份加完整常规文件清单／hash、opaque 链接身份共同证明旧组，未知则保留并拒绝写入。prepared 仅失效观察恢复临时预览，正常提示词同步／AI 分类另列。旧 engine／Session 须真正退役，不能仅 dispose 后允许重连；恢复成功与 UI 重开失败分别呈现。这些为工程边界，不新增待用户决定的产品问题，尚无恢复核心通过结论。

宿主只读合同核定：已装 pywebview 的 `load_url()` 不替换旧 Window 的 `js_api`；旧桥排队调用仍可能执行。原会话按明确文件责任并行实施新 Window＋新 Host／关闭／IO 代次，旧实例先退役，新窗存在后才销毁旧窗，避免瞬间无窗口结束 GUI。当前 lifecycle bundle 的最终清理须指向最新服务，不能只停旧 server 后释放新服务仍使用的运行锁；页面 `page_ready` 早于实际 context 读取，恢复完成另以新业务读取后的 UI ack 判断。失败保留“已安装但重开失败”的真实状态和保护位置。具体实现与窗口仍待独立验证，不因合同通过就称恢复完成。

## 12. 独立面板 r01：不通过，交原责任会话回修

2026-10-31，三份面板源／测试按冻结指令停写后，Codex 独立执行原组件测试 **17 passed**；复用其通用 SFC 加载器只读载入真实 `<script setup>`，另外加入不同的异步交错反例。三个实际反例 **0/3 通过，exit 1**，不是 DOM／原生窗口测试；组件责任会话随后自然 exit 0。测试前后该三份文件 hash 完全一致，原源及首次失败私下保留。

| 编号 | 独立实际失败 | 回修要求 |
| --- | --- | --- |
| B2-UI-R01 | 同一旧操作连续请求取消，一份回执先到后允许关闭／重开面板并开始新操作；第二份旧取消回执迟到，把新操作 `verifying` 改成 `cancelled` 并丢掉新 operation。 | 取消回包也绑定本次 epoch／请求／operation，退休或重复回执不能修改下一次操作；不能显示假的“当前档案未更改”。 |
| B2-UI-R02 | 同一 operation／generation 已进入 `reopening` 后，迟到的 `switching` 进度仍将界面退回切换阶段。 | 同一操作的不可逆阶段保持顺序；合法错误密码新尝试另按新请求处理，不用通用状态覆盖倒退。 |
| B2-UI-R03 | 确认恢复返回了不同 requestId 和 operationId，组件仍采用该外来 ref，开始追踪错误操作。 | 与 start 一样核对确认回复的本次请求和原预览操作；不匹配先查自己的同一 requestId，不能采纳外来操作或再发第二份确认。 |

私有回执 `b2-ui-r01-independent-receipt.json`，实际脚本与首次输出为 `run_codex_b2_ui_probes.py`／`codex_b2_ui_cases.js`／`codex-b2-ui-r01-probes.first.log`，源副本 `b2-ui-r01-source/`。组件会话自跑前已另存首次日志，后续独立运行也改为唯一结果目录，避免自跑覆盖首失败。归为面板源码行为失败，不能用其 17 项通过或 typecheck 覆盖；只交原组件会话回修三份文件，不改 App／宿主／恢复核心。B1、S1 限定通过保持，恢复核心／宿主／B3 仍未通过，不 Git、不发行。

## 13. 独立面板 r02：限定组件源码通过

同责任会话回修、停写并自然 exit 0 后，Codex 重新固定三份文件：独立执行组件 **20 passed**，原三个异步反例 **3/3 通过**；另用私有临时 tsconfig 仅纳入真实面板／类型文件、复用既有依赖，Vue 类型检查 exit 0，避开其他会话正在改的 App。未改测试行为期待，未增加依赖，三份源测试前后 hash 相同。

源码核对：取消回包绑定 epoch／ref，重复取消复用本轮等待；阶段不可退回；确认回复绑定本次 requestId 及原预览 operation，不符先查自己的请求。**B2-UI-R01–R03 在实际组件／合成 host 范围关闭，三份面板可冻结供原会话整合。** 实际结果 `codex-b2-ui-independent-f9a87b03`，回执 `b2-ui-r02-independent-receipt.json`。不把组件 setup／fake host 或局部类型检查当作 DOM、真实入口、宿主、恢复核心、窗口、教师体验或发行通过；B2 核心与 B3 继续独立核查。

## 14. B2 恢复核心 r01：独立不通过，三项回修

2026-10-31，核心会话申报停写后，Codex 记录恢复模块／Runtime／配置签名及稳定依赖 **60 路径**（其中核心所有权 10 文件），排除仍由宿主会话修改的 app/api 和新 Command Code 测试文件；不能写成整个仓库冻结。后检发现实现者仍追加六处源码／测试整理，故下表保留各次真实执行与首失败，**不将其核定为同一个最终冻结候选通过**；重新停写、固定候选后复验，原 source snapshot 保留。原保护源／旧包最终 hash 仍待该轮回执核对。

| 独立执行 | 实际结果 |
| --- | --- |
| 恢复核心＋Runtime／迁移／配置回归 | **99 passed，113.73 秒，exit 0**。 |
| 旧 Session／Engine／factory 与缺库重开 | **4/4 通过**；旧代次在 DBAPI 打开前受拒，不创建空 DB，运行锁保留；缺失安装库重开受控拒绝。 |
| 六组新恢复反例 | **3/6 通过**：journal/receipt 写后重读、完整密码包／41 表全字段／12 资源／完整保护副本再恢复、恢复后新写及两次新进程启动保持、提交后回调失败终态均通过；下面三项实际失败。网络连接尝试 0。 |
| 实际 Windows 子进程终止＋新进程 | **5/5 通过**：旧主库移走、旧 assets 移走、新 assets 放入、新 DB 放入及 terminal 落盘后；每次核对实际工作进程的父进程／命令／创建时间，持有其句柄 `TerminateProcess`，新进程核对完整旧／新组。旧组 15 资源、新组 12 资源，逐字节与全字段比较，不是同一空夹具；不是实际断电。 |

| 编号 | 实际独立失败 | 回修门槛 |
| --- | --- | --- |
| B2-R01 | 合成凭据根显式设在 `observations/assets` 内，普通启动及预览时同用户材料可用；恢复仍成功提交，将该材料随旧 assets 整组移走，配置位置剩 0 份。旧组里找到 1 份且字节与独立对照相同，说明没有保留在原凭据位置。 | 首次改现用组前以实际路径／身份拒绝会包含或移动凭据根的配置；不能因嵌套就移动／复制／清空 DPAPI。无 journal 的普通手工启动仍可用，不能将凭据不可用变成应用整体无法启动。 |
| B2-R02 | 同一 `PreparedDTO`／operation 首次返回 `installed_retired`，再次调用却重新开始维护并返回 `failed_keep_old`、无 receipt、`RESTORE_SWITCH_FAILED`。 | 查原操作结果，重复确认不能重新捕获、改写 active journal 或执行第二次恢复；重开且产生新工作后重放旧操作也不得覆盖新写。 |
| B2-R03 | 在实际旧主库改名成功、返回上层更新 `first_change` 前注入异常；错误分支仍把日志退役。全新进程随后建立空业务库：profile=0、plan=0；旧／prepared 两库各仍有 1 份档案及计划，完整保护包保留。 | 依据实际组件身份判断是否改过现用组，不能只信内存 flag；完整回滚并核对后才报告保旧，否则明确 `recovery_required`、保留日志与写屏障。未知／缺库不能退役后落入普通首次建库。terminal 只表示退役，须保留真实 installed／rolled_back／failed_keep_old 结果，不能统称已恢复成功；重开须遵守 lease 释放次序。 |

私有源副本 `b2-core-r01-source/`，完整反例 `codex-b2-core-3d6d3112`，凭据实际移动补证 `codex-b2-core-7ef9e00d/credential-move-independent-evidence.json`，真实终止 `codex-b2-process-crash-4abee16f`。冻结完整性后检未通过，因此不预填最终独立回执；重新核定时记录各源码身份。所有现场均为本轮独立合成根，原业务／原凭据未触碰。

独立夹具首版误取日计划 `content_version`，五组核心及五个终止案例未进入恢复；仅改私有夹具为实际接口 `current_content_version` 后才计上表。初版 PID 同一性检查识别到 Windows venv 启动器与实际 worker PID 不同，未完成接续验证；改为验证实际子进程身份／句柄后得到 5/5，旧五个 worker 已逐一核实退出。首版脚本和日志保留，以上夹具问题不混称产品失败。

最终核心会话实际 idle 后重新记录候选 C 的 60 路径，再跑完整六组反例仍 **3/6 通过、同三项失败，网络尝试 0**；本次前后 60 hash 相同，7 原保护源／旧包核对保持。候选 C 结果 `codex-b2-core-d8669f1f`，新源副本 `b2-core-r01c-source/`，回执 `b2-core-r01-independent-receipt.json` 分别记录先前候选 A 的 99 项与 C 的反例，未冒称已在 C 重跑全部回归。实现者“已停写”的早期申报不能替代实际停写及 hash 后检。

**结论：B2 核心 r01 不通过，B2-R01–R03 交同一核心会话／指定模型回修；不推进实际 B3，不 Git、不发行。** B1、S1 和面板 §13 限定通过保持。Command Code 只补充自己两份互补故障测试，宿主会话继续其独立接缝，不能代改恢复核心；600 图恢复容量、实际入口、全库端到端、教师体验及其他未验范围保持。


## 15. B2 宿主 r01：独立不通过，三项回修

原会话实际 idle 后，Codex 固定桌面／前端 175 路径，独立运行三份宿主单测 **46 passed，0.68 秒，exit 0**。另以实际 `MaintenanceHost` 配受控核心／备份替身构造三个异步边界，**0/3 通过**：

| 编号 | 独立反例 | 回修门槛 |
| --- | --- | --- |
| B2-H-R01 | 已完成预览后取消返回 cancelled，但核心 `cancel` 调用 0 次，核心仍持有校验暂存。 | 将取消交由对应核心生命周期收口；预览／准备／在途取消只释放本次自有暂存，不能删除保护包或旧组，不得晚确认安装。 |
| B2-H-R02 | 备份替身已发布文件，在成功返回前收到取消；宿主最终显示 cancelled，完整文件仍存在。 | 成功发布结果为最终事实；取消请求等待实际结果，不得把已完成备份报成已取消或自动删除成功文件。 |
| B2-H-R03 | 注入未识别的 install state，宿主仍调用 reopen 并显示 completed。 | 仅明确 installed_retired 才进入成功重开；未知状态保持维护拒绝并提示核查，不假定成功。 |

私有结果 `codex-b2-host-probes-v04hw7hc`、`codex-b2-host-r01-unit46.log`、`codex-b2-host-r01-probes.log`，保留首失败及对应 hash；这些是宿主替身边界，不冒称真实备份文件／WebView2／进程恢复验证。原会话同模型回修，不代写核心和独立面板。另须核对旧宿主退役应在核心 reopen 暴露新 engine 之前；当前 Sequencer 退役发生于核心 reopen 之后，作为明确合同次序交回核对。

回修期间追加 **B2-H-R04**：受控 host／core 中，错误密码请求到达 password；新 request 正确校验后取消新预览，旧 password 请求仍被 `has_active_operation()` 计为 active，导致原生关闭一直受拒。当前开发源码身份 `c3823933…`、合成现场 `codex-b2-host-probes-e67werp5`、私有 `codex_b2_host_password_retry_probe.py`／`extra-result.json` 保留。此为开发候选中的实际反例，尚非最终宿主候选验收；交原会话收口被替代请求及核心暂存，保持旧 request 可查询，不能为避开失败而忽略所有密码／预览阶段的关闭保护。日志读取首次遇 UTF-8／GBK 驱动编码差异，仅调整私有读取方式；UTF-8 现场 JSON 的 active=true 与旧 password／新 cancelled 状态一致。

同轮追加 **B2-H-R05**：核心捕获／校验保护副本会先于 stop_transport 透传快照进度 `stage=verify`；宿主却把所有 verify 当切换阶段。受控现场尚未关闭旧服务、未改 live 时，状态已变 switching，取消返回 too_late，随后继续完成并 reopen。开发源码 `7ef98c4a…`、合成现场 `codex-b2-host-probes-l95iok6w/protection-result.json`、私有 `codex_b2_host_protection_cancel_probe.py` 保留。须按实际 transport／switch 边界收口不可取消状态，保留真切换后的安全门；内部进度 key 同时应在宿主适配为教师可读中文，不改变核心／冻结面板合同。

## 16. 互补故障测试：回执状态问题，尚未独立通过

Command Code 按用户授权以 DeepSeek V4.1 Flash／max 只写两份新故障测试。最终自测为 **15 passed、1 failed，60.11 秒，exit 1**，不将早期中途 16 项通过作为最终结果。唯一失败为 terminal 成功、receipt 写入失败后重启归档，把真实 `result_state=installed` 覆盖成 `terminal`；源码 `write_receipt` 从 phase 重新取结果与该现象一致。现有合成现场新编辑、旧组、保护包及凭据均保留，未证明数据丢失。交核心同会话回修并检查其他失败结果退役后的准确性；Codex 待最终停写独立复验。测试中个人绝对证据路径交测试责任方改为可移植临时根，不能提交个人路径或现场。


## 17. B2 核心 r02：限定后端源码独立复核

核心会话完成全部回修、原生 session 实际 idle 后，Codex 重新固定同一 **60 路径**并归档核心 10 文件，独立执行：

| 项目 | 实际结果 |
| --- | --- |
| 恢复核心／Runtime／迁移／配置 | **105 passed，125.21 秒，exit 0**。 |
| 旧代次连接、缺库重开 | **4/4**；DBAPI 打开前拒绝旧代次，不在切换空档建空 DB。 |
| 原六个独立反例 | **6/6**；B2-R01 凭据嵌套拒绝、B2-R02 幂等、B2-R03 实际改名后异常均关闭；密码完整恢复、保护副本正常再恢复和两次新进程继续新工作保持。 |
| Windows 实际 worker 终止／全新进程 | **5/5**；固定父子 PID／命令／创建时间及句柄，恢复完整旧组或新组，15 旧资源／12 新资源全字节及业务全字段一致；不等于实际断电。 |
| 取消、迟到重复、新写与回执结果 | **5/5**；校验／prepared 暂存取消后释放、晚调用拒绝；重开新写后旧 DTO 返回原结果，无新维护 hook；installed／rolled_back／failed_keep_old／canceled 两次退役和归档保持真实结果。 |
| 改名瞬间真实 WAL／SHM | 上项含两个独立案例：用当前 SQLite 支持的 NO_CKPT_ON_CLOSE 保留真实业务写入，切换时 WAL **2,776,912 bytes**、SHM **32,768 bytes** 实际存在。成功时旧文件族逐字节保留；主库改名后抛异常时完整回滚，WAL 中业务逐字段保持，未伪造 sidecar。 |
| 大容量完整恢复 | 已有密码包 **157,647,029 bytes**，实际 **604 原图／1,812 资源／41 表全字段**恢复通过；精确授权 delta 为 0，完整旧保护副本验证通过，重开后保存新版本并重启保持，88.259 秒。 |
| 真实非空 0005 完整恢复 | **447,595 bytes** 包实际安装为当前 head；26 原业务表按独立原始行 oracle 保留、版本 1–4 保持，完整旧保护副本与重开后保存／重启通过，3.316 秒。普通启动提示词同步另列为 bundles 3→9、personal heads／versions 各 3→5；安装前严格对照与启动后常规增量分列，无整表豁免。 |

结果分别保留于 `codex-b2-core-665bafb7`、`codex-b2-process-crash-e86fb229`、`codex-b2-extra-ac6c8c7e`、`codex-b2-capacity-oldschema-4764981f`；已执行部分前后 **60 hash 一致**，5 原保护源和 2 旧包 hash 保持。各独立进程禁止并计数网络连接，尝试 0；未启动应用 AI 执行器。额外私有驱动首次遗漏 SnapshotService 必填 source_identity、runpy 首次遗漏私有辅助模块搜索路径，均在恢复／终止前失败，仅修正私有驱动后取得表中实际结果，原日志／脚本保留，不记为产品失败。

**当前核心限定工程独立通过。** Command Code 最终可移植两份测试已停写，Codex 独立运行 **16 passed，60.69 秒，exit 0**，包含 terminal 成功／receipt 失败后的正常接续和新编辑保留；核心及测试 **62 路径前后 hash 一致**。`b2-core-r02-independent-receipt.json` 记录最终同源证据，§16 原 15／1 首失败不覆盖。 宿主 §15 仍由原会话回修，未通过前不接实际 B3，不 Git／发行；面板 §13、B1 和 S1 既有范围保持。实际窗口、宿主端到端、教师体验、冻结包、跨机／用户、真实断电和原 D3／SAC 边界分别保留。


## 18. B2 宿主 r02：原五项关闭，新增三项仍不通过

原会话实际 idle 后 Codex 固定桌面／前端 **175 路径**，保留 11 份关键源文件副本。独立宿主及相关既有回归 **166 passed，27.66 秒，exit 0**；原三组反例 **3/3**、密码重试残留与保护校验取消各 **1/1** 通过，B2-H-R01–R05 在受控 host 边界关闭。完整前端类型检查、统一 test:d1（含面板 20 项及宿主适配器）、D1 Vite 构建实际均 exit 0；构建驱动在保存 exit 0 后打印 Unicode 勾号遇 GBK 错误，仅为驱动输出错误，不作构建失败。

| 编号 | 独立失败 | 必须回修 |
| --- | --- | --- |
| B2-H-R06 | 用真正 Vue compiler-dom 编译实际 App SFC 模板，发现新通知的 v-if 成为 error／setup／normal 既有分支的 if 头；通知存在时工作台、编辑器、设置与首次页全在 else 内被排除。 | 通知独立于完整连接／错误／首次／正常页面条件链，恢复后通知与业务页面同时显示；类型检查／script setup 单测不能代替模板结果。 |
| B2-H-R07 | 新服务 start_and_wait=False、stop_and_confirm=False 时，Sequencer 未把新 bundle 交给 manager；close_latest 仍关闭旧 bundle 并调用同一个 Runtime.dispose，返回 True，新服务退出仍未确认。 | 任一新服务／执行器在失败分支也有明确生命周期所有权；只有全部已确认停止才可释放原运行锁，不凭旧 bundle 已停推断新服务已退出。 |
| B2-H-R08 | 旧 host 已退役、维护已终结且无在途操作时，原生关闭仍发旧页面握手，但 page_ready 已永久为 False；真实 CloseCoordinator 的 current request 即使收到 allow=True，host 仍拒绝 unknown，窗口不能正常结束以重启。 | 退役终态错误窗口可安全退出，收口本进程实际最新服务／执行器；切换／重开在途仍拒绝关闭，迟到旧关闭不能销毁新窗口。 |

模板反例 `codex_b2_notice_template_probe.mjs`／`codex-b2-host-r02-notice-template.log`（实际 SFC AST，非 DOM）；生命周期反例 `codex_b2_host_lifecycle_failure_probes.py`／`codex-b2-lifecycle-56zq3v6h` **0/2**（真实协调类加受控服务／窗口替身，非实际服务器故障）。关闭首版只断言第一次 native close 为 False，此本身可属于正常异步握手；后版放宽为安全即时关闭或成功握手均可，并确认 retired host 对真实 current request 的 allow ack 仍永久拒绝，才计 H-R08。原脚本／日志保留。

回执 `b2-host-r02-independent-receipt.json`、源副本 `b2-host-r02-source/`；五个通过边界来源 `codex-b2-host-probes-89zh9i9j`／`gnlyww3c`／`x9qn72hq`。本轮整体 **不通过**，交原会话继续 App／生命周期最小回修；不修改已独立通过核心、共享快照、冻结面板或 Command Code 测试。263 路径绑定的全 local 后端回归正在并行执行；不提前实际 B3、不 Git／发行。


## 19. 后端全量通过与宿主重启终态补例

Codex 独立全 `tests/local` 已完成 **848 passed，33 warnings，1241.33 秒，exit 0**，绑定 **263 个后端路径前后 hash 一致**。33 项均为现有 SQLite datetime adapter DeprecationWarning，无线程未处理异常或失败；不为本 Feature 扩大依赖／迁移范围。回执 `b2-full-local-independent-receipt.json`，也归入核心 r02 回执；不替代窗口、前端或教师体验。

原会话 r03 停写后，H-R07／R08 原两组实际独立复跑 **2/2**，但追加同类 **B2-H-R09** 仍失败：核心在 transport 停止、旧 AI 执行器已确认 dispose、engine 关闭后返回 recovery_required，尚未进入 before_reopen，故 host 未 retired；关闭握手查询已关闭 Runtime 失败，被旧 close handler 当作 AI 在途，即使 stop_and_exit 也得到 accepted=false／canceled，窗口无法按提示正常结束以重启。受控验证使用真实 Host API／关闭 handler／CloseCoordinator，加已确认停止的执行器与关闭 Runtime 替身，未真实故障停止服务器；现场 `codex-b2-lifecycle-gchneide`、`codex-b2-host-r03-lifecycle-extra3.log` **2/3**，旧两组期待不变。

交原会话只修这条“已返回需重启终态且 engine 已关闭”的退出接缝及相称测试，继续由进程最新 bundle 确认服务／执行器并管理运行锁；不能全局忽略普通 AI 在途、未保存工作或活动切换，不释放核心 lease／改 journal／暗中回滚。当前实际 B3 与 Git 仍等待最终宿主独立通过，后端／面板／共享快照／互补测试保持冻结。


R09 r04 回修后，原三组生命周期反例独立 **3/3**；反向守卫新增后为 **3/4**：engine 仍打开、transport 未停，执行器替身明确给出 `attempt_in_flight=True` 时，仅因 host `recovery_required` 旗标就直接允许原生关闭，绕过原 AI 关闭选择／拒绝。现场 `codex-b2-lifecycle-po2t5ako`、`codex-b2-host-r04-lifecycle-extra4.log` 保留；没有发真实 AI 请求。交同会话 r05 仅将特殊退出收紧到原要求的已停止 transport／engine 退役等实际安全状态，原 closed-engine 正向与三组旧期待均保持，不全局放宽关闭。

前端 r03 已另外固定 **83 路径**，独立实际 SFC 模板 AST、完整类型检查、统一 `test:d1` 及 D1 Vite 构建全部 exit 0，83 hash 前后一致，三个前端构建文件身份另存 `b2-frontend-r03-independent-receipt.json`。H-R06 模板问题关闭；VNode／源码构建不等于真实 WebView2／DOM 或教师体验。后端与前端通过均保持，宿主最终条件仍待 r05 停写复验。


## 20. 宿主 r05：限定源码独立通过，可接 B3

原会话完成收紧、原生 session 实际 idle 后，Codex 固定 **175 个桌面／前端路径**并保留七份关键宿主源副本。独立完整 `desktop/tests` **430 passed，2 warnings，64.40 秒，exit 0**；独立原三组、密码重试、保护校验取消、实际 SFC 模板 AST、四组生命周期正／反向守卫共 **10/10 通过**。H-R01–R09 在这些明确范围关闭，首失败／逐轮回修保持 §15–§19。

已核对：特殊原生退出依赖已退役 host 或 core 需重启且 transport 确认停止，无维护在途；仅 recovery_required 旗标、engine 打开且 AI 在途时保留普通关闭选择／拒绝。失败启动的新 bundle 在服务 ready 前已纳入最终清理，未确认停机不释放运行锁；新页通知与正常页面条件分支独立；成功发布备份不被迟到取消改终态；预览／错误口令生命周期有收口。旧 host 在新 engine 重开前退役，进度中文和保护位置保持显示文本用途。

前后 **175 hash 一致**，前端 §19 的 **83 hash**、后端全量的 **263 hash** 继续保持；5 原保护源和 2 旧包 hash 一致。回执 `b2-host-r05-independent-receipt.json`；独立结果 `codex-b2-host-probes-an19scme`／`o7d6deyj`／`5f1uiv3n`、`codex-b2-lifecycle-jishdma8` 及模板日志保留。完整前端类型／Node／Vite 构建仍以自己的 83 路径回执为准。

**限定 B2 后端与宿主源码工程通过，允许原 OpenCode 继续 B3 真实源码窗口闭环；尚未 Git／发行。** 受控 host／VNode／AST、单独数据恢复和进程中断不是已验证真实 Window／DOM／原生实际点选或教师体验；B3 必须走真实前端入口、核心、全新窗口／宿主、保护包再恢复、重启、编辑保存／历史／图片／Word 并独立复验。真实供应商、WebDAV、冻结包、SAC／签名和原未验边界保持。


## 21. B3 验证驱动预检：首轮隔离不足，停跑回修

B3 开发中的驱动首轮未进入独立验收。Codex 读到实际驱动先调用 build_runtime 启动 AI 执行器、再播种会短暂创建排队任务的完整夹具，且未设置供应商替身／禁止子进程发送或外发连接计数。这形成被执行器接走的竞态，不能以“只点击备份按钮”推定不会请求供应商。Codex 发回修指令，并核对明确的自有合成 data／credential／config 命令、父进程、实际 executable 与句柄创建时间，停止该自有源码工作进程；未按进程名批量停止，不涉及教师窗口／原业务。

当前合成现场在读取 SQLite 前完整复制到 `b3-unisolated-preserved-8c8251d9`，44 文件及物理 hash 保留。安全执行记录审计显示 source／target 各 4 条 task／execution／attempt，状态均为夹具成功／失败／unknown，未见多余执行记录；**该轮没有连接拦截／计数，不能补证真实供应商请求为 0，也不能据此宣称已发生真实请求。** 停止回执 `b3-own-unisolated-process-stop.json`，原业务五源与两旧包 hash 复核保持。

工具历史还显示实现者为重试删除过本次合成 r01 的 source／target／evidence／包，导致更早失败现场不完整；只保留现有工具日志及上述后续副本，不能写成更早现场已完整保留。后续一律新唯一根、保留首失败，不覆盖／删除既有包。驱动其他待修点包括：完整指纹须 include_runtime_fields=True、备份后比较真实 DB／资源而非 bool(verified)、正常启动授权增量精确分列；未知服务／执行器退出时不 fallback 释放 Runtime 锁；driver 错误及 watchdog 先持久记录、缺失必需检查或超时不能标成功，错误窗口有受控结束路径。

已要求原会话只完成驱动隔离／顺序／清理与入口单元回归，**停写给 Codex 预检后才允许下一次实际 GUI／服务／执行器试跑**。父进程在任何 Runtime／夹具之前强制阻断外发，子 worker 也须禁止供应商发送或限制到明确本机替身；先播种再启动执行器；LOCALAPPDATA／更新缓存／凭据显式隔离。既有后端／宿主／组件通过各自保持，B3、源码窗口与最终 Git 仍未通过；不发行。


## 22. B3 预检 r01：五项驱动反例不通过

原会话停写且原生 session idle 后，Codex 固定 source verify／source guard／d1_main／入口测试四文件并保留副本。独立五组纯内存／受控 Socket 与假窗口检查 **0/5**，未创建 GUI、Runtime、应用服务或 AI 执行器：

| 项目 | 观察到的驱动问题 |
| --- | --- |
| 完整字段 | 真实 success predicate 对 `database_equal_full=False` 仍可给 ok=True，只依赖排除了 runtime 字段的 business 指纹。 |
| 业务 DOM | 只用 view=workbench／setup 状态推定可见，实际 calendar DOM=False 仍可成功，不能覆盖曾发生的页面被通知遮挡。 |
| 预览判定 | 驱动给 restore_preview 写描述字符串，required 却要求它 is True，正常预览永远不满足最终条件。 |
| 守卫审计 | 日志写／读受控失败时，已被硬阻断的一次解析仍报告 attempts=0；未知审计状态须失败，不能当零。 |
| 早期驱动错误 | 第一次页面等待失败虽写了部分证据，但初始自有窗口未结束，finished 却使 watchdog 不再触发，主 GUI 可能永久等待。 |

私有 `codex_b3_preflight_probes.py`／`codex-b3-preflight-r01-probes5.log`，现场 `codex-b3-preflight-zfixwjrz`；其中直接编译执行实际源码中的成功判定，未重写一套实现。后续表示／精确增量接口如合法改变，私有驱动只随实际生产字段调整取值，不改变这些行为期待。还交回检查关闭备份面板后须重新打开才能点击恢复、异步窗口退出需等待、新窗口选择替身归属等测试驱动接缝。

继续原会话预检 r02 修复，不允许实际 GUI／服务／执行器。用户已授权的 Command Code 另获互斥的新增 `desktop/tests/test_maintenance_source_guard.py`，仅补父进程阻断／审计失效／实际普通 Python spawn 的纯守卫测试，不写实现、旧两份互补测试或其它文件。固定同一 DeepSeek V4.1 Flash max、无子代理、无 Git；Codex 仍独立审核与运行。全部真实 B3 范围待预检通过后逐项完成。


## 23. B3 预检 r02：原五组通过，追加两项未通过

原会话 r02 实际停写后，Codex 固定四源，独立原五组 **5/5**、入口 **12 passed，2.27 秒**；分别保留 `b3-preflight-r02-source-before.json`、`codex-b3-preflight-r02-probes5.log`、`codex-b3-preflight-r02-entry.log`。完整字段和真实业务 DOM 已加入必需条件，预览描述与就绪布尔已分开，父进程内存计数与实际普通 Python guard 装入检查已成立。

追加纯 Python 子解释器与假窗口两组 **0/2**，仍无 GUI／Runtime／服务／执行器：子进程已经证明 sitecustomize 装入并阻断受控 lookup，但仅记录期间注入审计写失败，子仍正常退出，父得到 memory=0／log=0／audit_ok=True；驱动在自有 destroy 抛错后仍无条件 finished.set，关闭 watchdog，部分证据已写也不能保证 GUI 退出。私有 `codex_b3_preflight_extra_probes.py`、现场 `codex-b3-preflight-extra-_1becfbr` 与日志保留。

两项交原会话 r03 最小回修，Command Code 继续只写自己的新纯守卫测试。预检未放行实际窗口；单次小容量校准与全部 B3 九项范围均待后续真实完成。


## 24. B3 预检 r03 通过，首个受控窗口校准未通过

Codex 固定五份源（含 Command Code 最终测试），原生实现会话 idle 后独立原五组 **5/5**、追加两组 **2/2**，入口与互补守卫共 **19 passed，0.46 秒，exit 0**；前后五 hash 一致。子审计失效有独立低层标记与非零结束，调用方捕获普通传输错误也不静默变零；父日志初始化后缺失为未知。销毁失败保留有效 watchdog，loopback 测试使用自有监听端口。Command Code 只适配本次新空日志的布置，六项行为期待保持；历史 5／1 不覆盖。回执 `b3-preflight-r03-independent-receipt.json`。预检仅放行一次隔离的小容量源码窗口，不等于 B3 完成。

首个 Codex 实际受控窗口 `kgm-b3-cdx-e76dc796` 已完成首次工作台、设置入口、实际明文备份：**1,408,772 bytes**，数据库 **827,392 bytes／41 表全字段**及全部 **12 资源**与 target_pre 完全相等。恢复预览等待表达式多一个右括号，实际 WebView2 报 SyntaxError 后等待超时；独立 Node 只解析 23 个实际 JS literal，发现同一 1 处错误。未记恢复／新窗口通过。预览仍在途使正常 destroy 受拒，watchdog 保持并实际在约 270 秒结束自有进程，exit 3；CIM 精确本 root 无残留 worker，未全局终止进程。

首失败完整现场与物理 hash 保留，停止后 target **41 表 full／12 资源仍等于运行前**，task 状态保持 failed 1／unknown 1／succeeded 2；实际 guard 日志 0 bytes、子自检成功且无 failure 标记，不能冒称 OS 抓包。五原保护源、两旧包 hash 保持，五桌面源前后一致。回执 `b3-small-r03-independent-failure-receipt.json`；语法解析 `b3-small-r03-js-literal-parse.json`。此为实际验证驱动失败，备份已验范围与未完成恢复分列。

真实手动备份终态还把“备份文件”误标“恢复前保护副本”；已交三 UI 的唯一所有者最小修正四个显示标题。Codex 核对新源逆变换仅四处标题且可重建原 hash，独立实际 SFC 模板、完整类型、全部 test:d1 和 Vite 构建均 exit 0，**83 路径前后一致**、三构建文件身份另存 `b3-ui-title-r01-frontend-independent-receipt.json`。该新前端取代旧构建作为后续窗口输入，真实修正文案仍待实际窗口复验。

原会话 r04 继续修 JS／异常取消清理，守卫与后端／核心保持冻结；允许其在新前端回执通过后新唯一根做受控校准，成功且确认收口才连续推进全部九项 B3。两辅助 OpenCode 只读私有 DOM／精确启动 delta 合同已完成，不把合同建议当新增产品要求或已验事实；最终仍需 Codex 独立实际复验与明确 Git 清单，不发行。


## 25. B3 r04 小容量真实源码窗口：独立通过

实现者 r04 保留了 c1–c3 首失败：c1 的全局 `backup-restore` 选择器命中设置卡片；c2 初始维护面板超时且当时未记录足够 DOM，不能补定其具体原因；c3 已实际出现正常预览，但驱动误要求描述必须含“备份”两字。驱动随后将按钮限制在维护面板、等待可用性、补对话框调用／页面证据并按实际预览元素判断。c4 自测通过后继续其它场景；未删除或覆盖旧现场。

Codex 固定当时驱动副本 `ca42d376…`，用同一应用代码及新前端，在另一唯一合成根独立实际运行，**exit 0、全部必需检查通过**。原会话并行开发后续场景，仅使用专用源码验证文件；本次执行的驱动副本 hash、**439 个应用路径及三构建文件前后一致**，不同源身份不混记。回执 `b3-small-r04-independent-receipt.json`，现场 `kgm-b3-cdx-r04-7942f5d`。

| 已实际核对的小容量路径 | 结果 |
| --- | --- |
| 设置页实际明文备份 | **1,408,772 bytes**；数据库全 41 表与全部 12 资源等于 target_pre，真实面板标题正确显示备份文件。 |
| 选择、预览、确认、保护和恢复 | 正常实际面板／原生桥／核心；对话框替身实际两次调用（保存、单选打开），没有页面传文件字节。 |
| 新窗口与可见页面 | 实际新 Window generation 2，真实 calendar 与保护位置通知同时存在，旧 Window 实际退出。 |
| 恢复数据 | **41 表全字段、7 原图／21 资源**完全等于源完整包；原目标为 4 原图／12 资源，身份分列；无 runtime 字段或整表豁免。 |
| 最终清理与网络 | 自有 Window 实际销毁、最新服务／执行器确认关闭；父计数／日志计数均 0，审计健康、子 guard 自检通过，不冒称 OS 抓包。 |

**当前只核定这条小容量明文备份／恢复源码窗口闭环。** 首次未提交表单、密码／坏包与取消、实际新工作保存／历史／图片解码／Word、新进程接续、通过 UI 再恢复保护副本、旧能力迟到隔离、重开失败终态与 600 图窗口等完整九项仍由原会话连续补齐，并需 Codex 在最终停写后独立实际复验；不将本条替代全部 B3、教师体验、实际原生点选或发行通过。


## 26. 首次设置取消路径：限定独立通过，完整恢复仍待补齐

原会话保留 setup1 helper 导入线程失败／watchdog、setup2 输入属性定位失败和 setup3 交互等待失败，再取得 setup4 自测。Codex 固定主驱动 `510e87df…`／setup 驱动 `6f4e1aca…`，在另一合成根实际独立复跑 **exit 0**，两驱动副本、**439 应用路径及三构建文件身份保持**。真实首次页填写四项未提交文字后，选择文件取消、损坏包错误、加密包一次错误密码反馈后取消，三次单选对话框替身调用；四项文字保持、profile 行数 0、首次页仍在／无 calendar。最终自有窗口销毁及最新服务／执行器关闭，guard 计数／日志均 0 且审计健康。回执 `b3-setup-r04-independent-receipt.json`，现场 `kgm-b3-cdx-setup-28dd44`。

该候选还未记录全部 41 表／资源的首次页前后基线，故这里只核定文字保留和无临时 profile，不能推定其它表从未变化；当前交互是一次错密码后取消，不是正确密码重试成功。已交原会话继续补严格全表基线、错后正确重试到预览再取消，以及首次页真正确认恢复、完整空业务保护包和正常 UI 恢复保护包返回首次页。正向完整恢复、正常新工作／新进程和其它九项范围未被本条替代；不发行。


## 27. 恢复后正常工作：限定独立通过

Codex 固定主驱动 `2a310b0c…`／post `271e008a…`，显式开启 `post:true`，另一现场 `kgm-b3-cdx-post-de24a6` 实际 **exit 0**；439 应用路径、三构建和两驱动副本身份保持。正常 UI 打开恢复的计划、填写、点击保存、打开 v1 历史详情、进入观察记录并等待当前照片 naturalWidth>0，再回计划通过真实导出／原生保存替身取得 **14,077 bytes DOCX**。最新服务／执行器关闭、guard 0 且审计健康。

停止后独立 SQL 核对：源当前版本 5，正常保存后当前版本 **6**，只增加一版；新原文位于当前 head，成文反思是新值，其余全部 adopted_content 字段与源一致。DOCX 独立 ZIP CRC、Content Types 与 Word XML 解析通过，包含本次保存的新反思。原文与成文是既有独立字段，Word 按已保存 adopted_content 导出；新原文单独持久化，不能误要求它未经采用就直接进入 Word。依据手工日计划规格 §12 与 export_service 的既有 DTO，不修改产品行为。回执 `b3-post-r04b-independent-semantic.json`。

同轮 Codex 首次配置遗漏 post 旗标，所得 `kgm-b3-cdx-post-57d1e1` 仅按普通备份恢复保留，不计作后续工作证据；纠正后使用上述新现场重跑，未覆盖原现场。实现者 post7 后补历史来源文案和历史照片解码，还需独立按其对应新身份复验；本条不冒称已验 AI 来源全部弹窗、Office 逐页、真实原生点选或全部 B3。


## 28. 全新进程继续新工作：独立通过

上条真实窗口关闭／实际 Python 进程结束后，Codex 用固定 r04 handoff 驱动另起 Python 与真实源码窗口，沿用同一合成 data／credential，使用**独立的新 evidence 目录和输出**，未重新播种或 load_url。实际工作台、学期、已有计划和编辑器打开，新保存原文 marker 可见，**exit 0**。

以启动前独立 full oracle 核对停止后的 **41 表全字段与全部 21 资源完全一致**，未制造下一正文版本。驱动副本、439 应用路径及三构建身份保持，最新服务／执行器正常关闭、guard 0。回执 `b3-restart-r04-independent-receipt.json`，现场仍为 `kgm-b3-cdx-post-de24a6` 的同一数据、独立 `evidence-restart`；原 post 证据保留。

原会话 r04 实际停写时仍有明确未完项，不能把“等待最终复验”当全部目标已完成。r05 继续原主会话，首次页正向模块独占交原组件会话，主会话不并改；其余保护再恢复、大容量、迟到能力、重开故障及显式 AI 冷启动计数等继续。开发候选中发现的加密驱动资源相等标志为常量 True，已交主会话改成真实清单比较；这不是加密备份资源已独立通过或已损坏的结论。新增产物路径也须在任何 Runtime 前统一限定到合成 root、拒绝别名和覆盖未知文件，先前纯校验探针只操作自有 marker，未触及保护源。


## 29. 密码备份与空密码拒绝：独立通过

原加密驱动的资源相等常量已由主会话改成真实 manifest path／bytes／SHA 比较，并加入空密码阶段无输出文件、无密码不能校验的检查。Codex 固定主驱动 `89e3b670…`／加密驱动 `929479eb…`，新合成现场 `kgm-b3-cdx-enc-798a8b` 通过真实设置页创建 **1,408,788 bytes** 加密完整备份，**exit 0**。

实测空密码时提交禁用、无完成／错误终态且未生成文件；填非空合成密码后实际完成。文件不提供密码时拒绝校验，正确密码校验后的 **41 表全字段及全部 12 资源的路径／字节／SHA**等于 target_pre，未用常量或 bool(verified) 替代。最终窗口销毁、最新服务／执行器关闭，guard 0 且审计健康；两驱动副本、439 应用路径和三构建文件身份保持。回执 `b3-encrypted-r05-independent-receipt.json`。原未测资源的 r04 自测与本次真实资源比较分别记录，未覆盖旧结论；不作为全部 B3 或密码遗失找回能力的证明。


## 30. 600 图真实源码窗口：回修后独立通过

首个独立大包现场 `kgm-b3-cdx-cap-628442` 实际已完成 UI 选择／密码／预览确认／成组恢复／新窗口，41 表全字段与资源比较均一致；但驱动错误要求恢复正文也有 B3 测试前缀，面对原始正常合成教案误断言失败，exit 3。停止后独立计数为 **604 个 asset 行、604 原图文件、1,812 全资源**，输入包未变、guard 0、最新服务已关闭；该首失败保留，未把数据还原成功冒作整条验收通过。还发现资源图像数 1,812 混作原图量级阈值，交主会话按原始 asset／original path 实测，分开衍生物。

原会话修正为与真实源 oracle 精确比较正文、测量独立原图和资源后，Codex 在新根 `kgm-b3-cdx-cap-16aed6` 重新实际复跑，**exit 0**。真实 UI 选择密码包 **157,647,029 bytes**，SHA `cc64f56288459cfb653a573a510d84d8ed2cb396faeeec70c608bd17358f6f55`，实际密码输入、预览确认、完整保护、安装、新窗口与 calendar／保护通知通过。**41 表 full 及全部资源字节一致**，独立 SQL／磁盘再次核对 **604 原图／1,812 资源**；不是以衍生图数或核心旧容量结果代替窗口通过。guard 0 且审计健康、最新服务／执行器关闭。

固定主驱动 `d40225bb…`／保护驱动 `e6cc7ba4…` 副本，以及 439 应用路径和三构建身份均保持；大包与小数据各自身份分列。回执 `b3-capacity-r05b-independent-receipt.json`，首失败 `b3-capacity-r05-first-driver-failure-receipt.json`；不覆盖未验真实原生点选／跨机器／发行。


## 31. 同目录正常 UI 再恢复保护副本：独立通过

Codex 使用自己的 post 场景同一合成 data／credential：第一次备份恢复后真实编辑保存为版本 6，正常关闭并全新进程接续已通过；再另起实际窗口，从正常恢复面板选择**第一次自动保护包**、预览确认，找回第一次恢复前完整旧工作。未复制 DB 或换一个数据根代替恢复，**exit 0**，最新服务／执行器关闭、guard 0。

停止后的独立全表／文件 oracle：当前 **41 表 full＋12 资源**精确等于第一次的 target_pre；原自动保护包 SHA 保持。现保留 **2 个完整保护包、2 组旧数据**。第二次自动生成的保护包由独立隔离 Runtime 的普通 verify 实测，**41 表 full＋21 资源**精确等于第二次替换前的新工作（当前版本 6）；同一新工作 full 指纹也在第二组 old group 中找到。旧工作找回，新工作保留在新保护包和旧组中，无自动删除或暗中回滚。

现场 `kgm-b3-cdx-post-de24a6`，独立 `evidence-protection`；固定主驱动 `5b4aced7…`／保护驱动 `e6cc7ba4…`、439 应用路径和三构建身份保持。回执 `b3-protection-r05-independent-semantic.json`。离线保护包 oracle 使用另一自有合成 Runtime，不启动服务／AI 执行器，网络尝试 0；原 post／restart 证据未覆盖。首次页的空保护包完整正向仍由专属 UI 会话补齐并实际复验，迟到能力／故障／显式冷启动计数及 P05 窗口边界仍待完成，不发行。


## 32. 首次设置完整恢复及空保护再恢复：独立通过

组件原会话独占 setup 驱动，交付 `91e13027…` 后停写；主会话将九个正向必需条件接入汇总并取得 setup5 自测。Codex 固定 setup／主驱动 `80b746a0…` 等专用验证模块副本，在另一新根 `kgm-b3-cdx-setup-r05-b70f33` 实际运行 **exit 0，22.24 秒**；439 应用路径、三构建及本次全部专用模块副本保持。该回执只执行 setup 模式，不把同目录归档的其它未执行模块计作通过。

首次页四项未提交文字经文件取消、坏包、错密码后正确重试到真实预览再取消，仍保持原文字、profile 0，**41 表 full／全部资源基线不变**。随后真正从首次页选择完整包、确认替换，generation 2 的真实 calendar 和保护位置可见；自动空业务保护包由正常 verify 实测为初始 41 表、profile 0、资源 0。

再从正常设置页选择该空保护包，预览确认后 generation 3 返回真实首次设置页，保护通知仍可见。停止后的独立只读 SQL／全表指纹复核：当前 **41 表全字段等于初始空业务，profile 0**；第一组 old DB 等于初始基线，第二组 old DB 等于第一次已恢复的完整源。第一保护包 SHA 保持，**两个保护包、两组旧数据均保留**。最新服务／执行器和自有窗口关闭，guard 0、审计健康。回执 `b3-setup-r05-independent-receipt.json`／`b3-setup-r05-independent-semantic.json`。独立补核最初两次误猜只读 DB 路径／表名报错已记录并按实际位置纠正，未写数据库或改变实际窗口结果。

另外两项纯验证反例交主会话回修，尚不计关闭：冷启动比较器用 date 作为日历行键，实际复合主键 `(revision_id,date)` 的同日不同修订被折叠，改第一行仍返回无差异；三个产物别名（坏包＝加密包、out＝坏包、out＝加密包）被入口接受。均只在自有临时根运行纯 Python，无 Runtime／服务／GUI，原反例保留。源码窗口其它迟到权限、冷启动、故障终态、P05 取消边界与最终统一停写核对继续，不发行。


## 33. AI 执行器普通冷启动分类：限定独立通过

主会话修正复合行比较为普通表完整行 multiset、AI 表实际主键，只允许指定任务四列启动变化，并新增复合日历行及非许可任务字段回归。Codex 在自己的已停止恢复数据副本中，通过正常 create_task 创建一个未领取 pending 任务；准备阶段先装禁止外发守卫，不启动执行器，单独保存初始全部 41 表和资源。随后运行固定冷启动驱动 `47aaf82d…`／主入口 `970c5158…` 的真实源码窗口，正常页面就绪后启动一个真实 AiExecutor，**exit 0，9.64 秒**。

实际事件仅 `before_claim:5`，无成功 claimed／sent／child_started／ready／marked／result_received，未为该任务增加 execution。停止后 Codex 使用独立逐行 multiset 再比全部 41 表：只有该任务的 **status、reason、runtime_meta_json、updated_at** 改变，pending→paused、reason restart；meta 精确仅补 permit_revoked_at，且与 updated_at 相同时间，其余字段、所有其它行和资源保持。generation 0／current_execution_id null；guard 0、审计健康、最新服务／执行器关闭，439 应用路径、三构建和归档源保持。

现场 `kgm-b3-cdx-cold-r05-2c4a09`，回执 `b3-cold-r05-independent-receipt.json`／`b3-cold-r05-independent-semantic.json`。本条是**普通真实冷启动的未领取任务分类**，不是制作并恢复含在途任务的备份包；先前 aicold1 因无执行器又有待处理任务而被 SnapshotBusy 安全拒绝，不改写为包已创建或恢复通过。正常完整恢复各场景使用已终结 AI 任务夹具，full41 完全相等的证据另列，不整表豁免。


## 34. 已提交恢复后的重开失败：两类源码窗口独立通过

固定重开驱动 `fe0cae9f…`／主入口 `970c5158…`，Codex 在两个独立新根分别运行真实面板选择、预览确认、完整保护和恢复，再作受控 source-only 故障注入，均 **exit 0，约 20 秒**。两条都实际显示“资料已恢复，重新打开失败，请重启应用”及完整保护位置，status 为 REOPEN_FAILED／committed true／restart_app；**当前 full41／资源精确等于源包，保护包 full41／资源精确等于替换前**，旧窗口保留到错误视图关闭并正常退出，不暗中回滚。

| 故障注入 | 实际结论 |
| --- | --- |
| 重开宿主返回明确 reopen_failed | recovery_required 有效；正常关闭旧窗口后最新服务／执行器确认关闭。 |
| 新 ServiceRun 启动失败且 stop_and_confirm 始终无法确认 | 在实际新容器拥有 runtime 后发生故障；界面终态可退出，但 **latest_bundle_closed=false、runtime_lock_retained=true**。该未知退出分支按设计保留锁，不把它记成已确认清理。进程自然结束释放 OS 资源，与运行期间主动释放锁分开。 |

现场 `kgm-b3-cdx-reopen-r05-cb3039`／`kgm-b3-cdx-reopen-service-r05-dd7ff1`，回执 `b3-reopen-r05-independent-receipt.json`／`b3-reopen-service-r05-independent-receipt.json`。两条 guard 0、审计健康，439 应用路径、三构建及本次归档源保持；受控服务替身不等于真实操作系统挂死或真实断电。实现者 reopen1／svc1–4 首轮缺旗标、面板超时、错误 mode 等现场保留，svc4 自测与上述独立根不混记。


## 35. 迟到旧权限与真实 HMAC 失效：回修后独立通过

首轮独立 `kgm-b3-cdx-late-r05-166e78` 的旧宿主／token 等探针与 full41／资源通过，但 config apply 的 422 实际是“request_id 必须是 UUID”，尚未进入 HMAC。即使驱动 summary 为 true／exit 0，也**未核定 HMAC 通过**；语义反例保留于 `b3-late-r05-independent-HMAC-failure.json`。主会话改用新合法 UUID、原预览的相同规范化 change／config version，并严格要求“预览令牌无效”，不把任意 422 或服务 500 算令牌失效。

Codex 固定新迟到驱动 `58a10836…`／入口 `970c5158…`，另一根 `kgm-b3-cdx-late-r05b-8a02b4` 真实 UI 恢复后独立复跑 **exit 0，19.81 秒**。旧 bootstrap 退役；旧 page ready／busy／business、close 回包、Word／观察导出 native 保存、备份／恢复／confirm／cancel 被拒；新宿主拒旧 page ticket、旧 preview、旧原生 selection，未再创建额外窗口代次。旧 token 请求新本机端口返回 **401**，新 token 正常 context 及 config **预览**为 200；后者未持久化配置，不冒称已正常提交新配置。

旧配置 HMAC 在合法 UUID 及相同参数下实际返回 **422／VALIDATION_ERROR／预览令牌无效**。所有迟到调用后，41 表 full／全部资源仍精确等于已恢复源，新页面继续 ready；最新服务／执行器关闭、guard 0、审计健康，439 应用路径、三构建及归档源保持。回执 `b3-late-r05b-independent-receipt.json`，具体返回值在该根的 evidence/result.json；不是仅靠字符串 retired 或旧端口失联推定权限失效。


## 36. 最新后续工作驱动补证：历史来源与历史照片独立通过

§27 的旧驱动未包含后来补的历史来源文案／历史照片。Codex 固定当前 post `4ad942fd…`／入口 `970c5158…`，新根 `kgm-b3-cdx-post-r05-2be4bf` 显式 `post:true` 实际重跑完整明文备份／恢复和后续工作，**exit 0，22.80 秒**。正常保存后历史列表实际显示当前 v6、只读 v1 和“保存记录／从 v2 恢复”等来源；观察当前及历史版照片实际等待 naturalWidth>0，未用文件存在或缩略计数代替解码。

停止后独立 SQL 再核：版本 5→6，只增一版，新原文为当前 head，adopted_content 仅 reflection 改为新值。正常 UI 导出的 **14,077 bytes DOCX** 独立 ZIP CRC、Content Types／Word XML 解析通过，含新反思；原文／成文导出规则仍按 §27 分列。最新容器关闭、guard 0、审计健康，439 应用路径、三构建与归档源保持。回执 `b3-post-r05-independent-receipt.json`／`b3-post-r05-independent-semantic.json`。早先同目录阶段证据与本次不同源身份保持，不把实际 Office 逐页或教师体验写成通过。


## 37. 校验／保护阶段取消及失败清理：回修后限定独立通过

最初 cancel 驱动只在预览后取消，不能当作校验进行中或保护校验可取消。主会话另补 cancel-gates：**调用实际 verify 完成、尚未返回核心前**设受控闸门，正常面板仍处校验／保护阶段，由真实 UI 点击取消触发同一 cancel Event；返回真实校验结果后由正常核心处理取消。没有替换校验结果，也不是在实际资源字节读取的任意时刻注入。底层逐块取消另见 B1／核心已验范围。

首轮保护路径误匹配独立的 restore-guard component，实际为 data.restore-guard，导致未命中闸门并继续到新窗口。cancelg2 异常清理只跟踪旧窗口且可能 eval 已销毁旧页；硬 watchdog 又同步等待 native destroy，**超过 420 秒仍未退出**。Codex 保留现场，核对 PID／父子关系／启动时间／exe／完整合成命令并持有进程 handle，只停止自有 worker 与 venv launcher 两个 Python 进程，未全局终止或动真实业务。停止前运行锁不能复制；停止后首次 PowerShell 复制漏八个深层衍生图，保留该不完整副本，再用短自有临时目标及标准 Windows 扩展路径复制，**最终 96 文件逐个 SHA 全部一致**。未改变系统保护，也不把此复制处理写成 D3 长根问题已修复。完整回执 `b3-cancelg2-precise-process-stop.json`，首失败和全部部分副本均保留。

主会话修正精确保护根、失败时纳入 lifecycle 当前窗口、避免 eval 已毁旧页；watchdog 把 native destroy 交后台线程，硬超时不再同步等待，并在 cleanup 完成且实际自有窗口均不在时才停止。Codex 提取实际 watchdog 代码，以阻塞 native destroy 的纯替身独立验证 **2/2**：即使完成事件提前置位，仍在约 0.2 秒调用模拟 exit 3；无真实 GUI／Runtime 或 os._exit。私有探针首次遗漏新增 closure cleanup_done 的 NameError 属审计脚本适配，已保留并纠正，不当产品缺陷。

固定 cancel-gates `af7ca8c5…`／主入口 `97cd96a1…`，Codex 新根 `kgm-b3-cdx-cancel-gates-r05-226b9a` 实际复跑 **exit 0，19.01 秒**。两次真实面板取消均看到 cancel Event、闸门释放和取消终态，**41 表 full／全部资源未变、未停 transport、未退役宿主、窗口代次未变、本机服务继续 alive**。最新容器正常关闭、guard 0、审计健康，439 应用路径、三构建和归档源保持。回执 `b3-cancel-gates-r05-independent-receipt.json`／`b3-watchdog-independent-pass.json`。

另外 cancel6 已到实际 switching 并正确返回 too_late，但必需条件误列原始 ack DTO 而非布尔，最终 summary false；首失败保持，不将缺失列表为空当作通过。主会话改为保留原始返回并只核定明确布尔，增加 failed_checks；大包切换后边界仍待独立结束，未以本节替代全部 B3 收口。


## 38. B3 最终限定源码结论：完整本地备份／恢复通过

原会话完成 r05、结果 §13.8 后，经原生 session.active 与实际最终答复确认**三个 OpenCode 均 idle、Command Code 已停写**；没有把 run CLI 因 steer 提前结束当作停写。最终主驱动 `97cd96a1…`、guard `e71f8707…`、入口 d1_main `3e6ad161…`；每个实际场景保留其专用模块及主驱动副本身份，不把早轮旧驱动的未执行分支计入当前通过。生产应用 **439 路径及三前端构建文件在全部本轮独立窗口中保持**，最终完整桌面回归另固定 **461 源码／资源路径**。

最后大包取消场景 `kgm-b3-cdx-cancel-window-r05-f9a00a`，固定 cancel `ae2ee993…`／最终主驱动，**exit 0，111.20 秒**：第一次实际密码校验到预览后取消，当前 full41／资源及窗口不变；再次选择／预览确认，在真实 switching 阶段请求取消，返回 **accepted false／state too_late**，并实际完成新窗口、完整保护和恢复。157,647,029-byte 原始包 SHA 保持，当前 41 表 full 与全部 1,812 资源等于原源包；最新容器关闭、guard 0、审计健康。回执 `b3-cancel-window-r05-independent-receipt.json`。cancel6 原失败不覆盖。

最新 restart `0661ea11…`／最终主驱动另起真实 Python 进程，沿用 §36 的同一 data／credential、新 evidence，未重播种。恢复后保存的新正文在工作台／编辑器继续可见；版本指针 6／6 不变，独立启动前后 **41 表 full 及全部资源完全相等**，实际容器关闭、guard 0。回执 `b3-final-restart-independent-receipt.json`。此前同目录保护再恢复及其完整保护新工作见 §31，不改其现场。

| 最终核定的实际源码范围 | 独立证据 |
| --- | --- |
| 小容量完整明文备份及完整预览恢复 | §25；当前应用身份保持，后续 §36 亦实际重复该路径。 |
| 可选密码备份、空密码拒绝、真实全表／资源校验 | §29；无口令校验拒绝；坏包／错后正确重试及取消见 §32。 |
| 首次页完整恢复、空保护包与正常 UI 再恢复回首次页 | §32；两次新窗口、无临时 profile，两个保护包／旧组保留。 |
| 恢复后编辑、正常保存、历史／来源、当前及历史照片解码、Word、新进程 | §27–§28、§36 及本节；新正文仅正常用户保存增加版本。 |
| 同一目录正常 UI 再恢复保护包找回旧工作，另保留新工作 | §31；完整旧工作恢复及新保护包／old group 两份来源分别核对。 |
| 旧 host／ticket／selection／token／HMAC／迟到保存关闭失效 | §35；真正抵达 HMAC 的 422 明确为预览令牌无效。 |
| 已恢复但重开失败、未知服务停止保留锁 | §34；未知分支不冒称 latest_bundle_closed。 |
| 604 原图、1,812 资源、约 150MiB 密码包实际窗口恢复 | §30 及本节；原图和衍生数分列，full41／全部字节保持。 |
| 校验／保护阶段 UI 取消及实际切换后的 too_late | §37 及本节；verify 返回边界闸门的限定范围明确。 |
| AI 不自动重放及普通冷启动精确分类 | 默认终结任务完整恢复 full41 零差异；§33 的额外未领取任务只变化明确四列。 |

最终独立回归：**469 passed、2 项既有 Starlette／anyio deprecation warning，79.36 秒，exit 0**；461 源码／资源路径前后 hash 完全一致。Command Code 的跨全部专用模块 JS literal 解析／helper 实际导入三项、守卫六项及原会话入口三十项均包含在该完整桌面回归中。路径／角色／未知输出保护纯反例 **25/25**，复合行及无主键重复行变化检测通过；实际提取 watchdog 的阻塞 destroy 反例 **2/2**，源身份均为最终主驱动。后端此前 **848 passed／33 项既有 datetime warning** 的 263 路径全部保持，前端此前完整类型／测试／构建的 83 路径及三构建保持，未因纯验证模块／文档收口而重做相同后端长测或升级依赖。

本结论仅为 **Windows 11 当前开发机、标准 GIL CPython 3.14.7、实际源码窗口、独立合成数据**的备份恢复工程通过。真实教师资料、原生对话框人工点选、Word／WPS 逐页、Win10／跨用户／机器、真实断电、冻结包／4551／签名与发行均不因此通过；WebDAV 未启动。§21 最早无守卫轮次的历史网络行为仍无法补证，后续 guard 0 只适用于各自受控运行，不逆改该缺口。原五保护源与两旧包七项指纹保持，私有现场和首失败不入 Git。


## 39. 最终来源、文档与 Git 放行合同

Codex 统一固定本轮相对 B1 `7d2759b76a16528e3e42d720a9203be40b6383a1` 的 **56 个文件**：后端 17、桌面 23、前端 9，另有 .gitignore 与六份治理／规格／结果／核查／入口文档。生产代码、测试和专用验证模块均在独立核查后冻结，结果文档最后只作状态／计数归并；不夹带数据库、备份包、DPAPI、照片、日志、构建产物、私有提示词或失败现场。规格 §11 提供普通源码手动体验入口，但没有记作人工体验通过。

本轮三原生 OpenCode 会话按各自原 ID 使用 **build／opencode-go／deepseek-v4.1-flash／max**；按会话起始基线排除旧历史轮次后逐条核对模型元数据，未发现模型替换、fork parent 或另派子代理工具。Command Code 同会话的既有互补故障、守卫及 source-cases 日志共 **188 个模型请求**，均为 deepseek/deepseek-v4.1-flash／max；直接写入目标与限定四份互补测试／私有结果一致，不代替独立核查。完整导出和写入范围回执私下保留，不公开原始模型内容。

最终卫生核查：候选文件 UTF-8、无 trailing whitespace／替换字符／个人绝对路径，文档本地链接目标有效，git diff --check 通过。实际 ignore 探针八项保护备份／恢复暂存、保护包、journal／receipt 及本地工具缓存；七个源码／LICENSE／依赖锁／公开模板控制项未被忽略。原五保护源及两旧包仅复核已有指纹且保持，不读取真实 secret。最后完整代码／资源 461 路径与已测身份保持。

原 OpenCode 最后只按 Codex 固定的路径、Git blob、父提交和预期 tree 清单暂存，普通提交推送 **codex/desktop-v2-foundation**；提交后、推送前再次核对实际 tree／父提交及工作区，Codex 再独立核对本地与远端实际身份。不得 add-all、夹带其它改动、amend／rebase／force、改 main／默认分支或创建 tag／Release。此记录是提交内放行合同；实际提交身份以桌面分支 Git 历史及最终独立 Git 回执为准，不把“已授权”写成“已核对推送”。
