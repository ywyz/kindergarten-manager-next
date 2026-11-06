# Windows 11 内部便携候选独立核查

更新：2026-10-31。状态：**本轮互斥实施与返修已完成，Codex 独立源码／实际静态审核通过；最终 r03 完整内部候选及合成交接可用（§12），r02 通过事实保留。未启动候选、未操作目标机，Word／教师体验／签名／发行未验。** 本文提交内记录为精确 Git 门禁，实际提交推送以分支历史和提交后独立回执为准。

## 1. 授权、基线与责任

用户授权阅读并执行 [current.md](../tasks/current.md)，分别交 Command Go 与 OpenCode 完成，Codex 独立审核，通过后提交推送，并思考下一步、撰写提示词。沿用 `codex/desktop-v2-foundation`，开工 HEAD 为 `91e6a553db6d25a1603849f139f22e9d9097537b`。既有 AGENTS、索引、备份核查、任务入口及未跟踪便携计划为已授权文档改动，已保存开工差异，保留整合。

按[计划责任表](desktop-windows11-portable-plan.md#3-本轮已执行的并行责任和依赖顺序)派发 A／B／C／D。A 续原 OpenCode `ses_ead8af71dffeJphI1NOWg4jZgI`；B 复用空闲辅助 `ses_e72ecd5f9ffeYJaLRNypsdu5Pi`；C 续 Command Code `8cf528de-8773-4a06-9cc5-31e96fab515f`；D 为独立原生 Command Code 会话。固定 Go DeepSeek V4.1 Flash max，不 fork、另派子代理、安装工具或升级依赖。A 为最终 Git 执行者，须等待具体文件及 blob／tree 批准。

## 2. 开工证据与边界

私有证据根标识 `kgm-win11-portable-20261031-9715e2b5`，保留会话起点、CLI JSONL／stderr／实际退出码、源码指纹与受保护数据指纹，不提交原始诊断。当前机器的已知 SAC4551 边界保持，不运行候选 EXE／helper，不降低保护。没有目标机访问，目标预检、普通运行、Word 与教师体验不能预填通过。未签名内部候选不等于公开发行。

结构探索使用 `codebase-memory`：项目代次 `2026-10-31T13:25:44Z`。builder、两个 verifier、maintenance host／lifecycle 的覆盖无已记录问题，但 freshness 均为 `metadata_changed`；local 范围已记录 `__pycache__` 排除。已回读相关源码，图谱结果仅辅助定位，不据此证明完整依赖闭包。后续判断以实际源与产物为准。

## 3. 开工与接口核定

独立开工构建守卫回归为 **26 passed，exit 0**；旧 E14 四根共 **873 文件**另存完整指纹，原五保护源另存指纹。环境只读核对为 CPython 3.14.7／AMD64／标准 GIL、PyInstaller 6.22.3、pywebview 6.2.1、pythonnet 3.2.1、Pillow 13.0.0，均沿用既有安装。开工本地和远端桌面分支均为上述基线，远端 main 为 `e836726f008676fc603a7b4cb058e5d96cafe60b`，无远端 tag。

A／B 的只读合同交回并自然停写后，Codex 核定共同合同：保留 `KGNext-E14` 产品名，采用新 `win11-r01` 根与说明文件；新 manifest 使用 version 1，绑定 build_id、schema 和 source freeze；保留完整 before／after，来源路径使用 POSIX。新静态命令显式传入实际 package／frontend／freeze／out，不使用旧 r03 默认值。原冻结执行流程保持兼容入口，不将旧调用静默降为静态成功。

ZIP 仅有界流式读取，先验全部路径再读成员，禁止 extractall；明确 Windows 路径、链接、碰撞、重复键／行、压缩资源上限与私钥内容检查，合法公开 CA 和许可证保留。新输出拒绝覆盖或与输入／保护根相交。必需结果使用固定布尔集，缺项、非布尔、未知均不得通过。既有 d1_main 自检分支引入的验证辅助单列，不因其存在自动判失败，也不算作生产功能。

Command Code 首轮 C 为正常 exit 0；D 首轮只读准备触及 60 回合限制，实际 **exit 8**，未产出已完成预检或目标运行证据；已保留该轮并续同一原生会话进入已核定职责，不 fork／换模型。首轮 C 的 35 次与 D 的 60 次 model_request_end 均为 `deepseek/deepseek-v4.1-flash`／effort max，不能用派发参数单独代替此元数据。C 的大段中文私有说明写入遭遇工具编码／长度问题，最终以小段英文私有说明保留；仓库交付另须 UTF-8／替换字符核对。

## 4. 构建前返修与首失败

| 项目 | 实际问题、证据与当前状态 |
| --- | --- |
| 构建与核验接口 | Codex 源读发现 A 的产品树 TAB 行摘要与 B 的 JSON 摘要不同；已统一 JSON path＋sha 公式。B 原实现把 readable 置 true 的顺序、目录／ZIP 比较对象形状、外层 README／manifest 的 SHA、公共 CA 的 64KiB 读取限制及文本私钥检查有缺口，交原 B 最小修正，保留其自检首失败。 |
| 原始路径检查 | 两 verifier 的调用者先 abspath 再检查，原始 `..`／junction 痕迹丢失。Codex 真实合成 junction 探针首轮 exit 1，两个 guard 都返回 accepted=true；没有写报告。在本 Windows 上 resolve 结果仍在 allowed 内，不能据此声称写入保护目录。B r02 后同现场独立复跑 exit 0，两者均在写入前拒绝。 |
| 缓存清理与哈希读取 | Codex 在合成包里创建指向另一个自有合成目录的 `__pycache__` junction。旧 prune 进入 rmtree，探针在 mutation 前拦截，首轮 exit 1；哨兵及 junction 完整。A r02 后安全遍历先验全部目录／文件，改用 unlink／rmdir；同一拦截探针独立复跑 exit 0，清理调用 0，hash_tree 也在读取前拒绝，哨兵与现场保持。未声称实际删过外部文件。 |
| 测试有效性 | C 初稿吞 BaseException、限额用例重复路径掩盖真正拒绝原因、微型 ZIP 只验名称，未获批准。C r02 改用独立冷 Python 源码 harness、完整一致的小目录／ZIP／freeze、指定失败字段、唯一文件名限额及资源负例。其 freeze 夹具误把 deliberate changed 的 changes_ok 期望为 true，按该函数的“稳定且变化声明一致”含义修正，仍要求 digest／stable 为 false，不放宽坏来源的拒绝条件。 |
| 文件充当父目录 | C r02 完整 portable 为 13 passed／1 failed：两个 report guard 仍接受 existing-file/report.json。没有实际写入。B 修正父组件角色，保留 archive／freeze 合法文件叶子。随后暴露 C 对“新报告与输入共享父目录”错误要求拒绝；Codex 按文件本身相交的原合同明确更正该断言，并撤销 B r03 为其新增的 strict_parent helper／CLI 两套语义。最终 B r04 与 C r03 保留同一 guard 规则，不迁就错误断言。 |
| 首轮进程边界事件 | C 首轮曾 8 passed／2 failed，记录到两次 process 入口；同一 B 源身份后续未重现，无首轮堆栈可定因。保留原日志，不反写已修复。新的冷 harness 在导入 verifier／PyInstaller 前拦截启动，明确断言返回／报告／新增模块；只证明其各自源身份。最终实际候选仍须另记零启动证据。 |
| 目标预检 | D 首轮 PS5.1 parser 0 errors，行为在既有 PS7／自有微型合成夹具核对。当前 PS5.1 -File 被 CurrentUser Restricted 阻止，实际 exit 1，未 Bypass 或改策略；PS5.1 运行保持未验。PV 零／非法版本、原生架构而非环境变量、报告祖先别名和全部 PE 签名清点已交 D r02。 |

D 第一轮停写后，Codex 接管交接手册中文审校，D r02 仅写 PS1，责任互斥。英文初稿 SHA `cbf35146a710628a874c606a89af96dc22ba9beadc7cc36ddf5e3f594f0ee4ae` 私下保留，独有事实归本报告及中文手册，不新增跟踪的提示词副本。中文手册按日计划／观察各自保存和导出契约写预期，目标回执仍为空。

## 5. 构建前统一独立门槛

四原生会话均实际结束／停写；两 OpenCode API 时间为 idle 晚于 busy，C／D 有自然结果及退出回执。最后 source freeze 为 **243 文件**，digest `040c49e9a6b68a4d8197a4acbb75b50a18cb2249f4157ad221459721db568b62`，missing_optional 为空。全回归前后逐项一致。开工原源清单仅四个已分配原文件变化（builder、两 verifier、旧 guard test），另有指定的新 portable test／PS1；app／维护宿主／后端／前端生产源码未改。原五保护源和旧 E14 四根 **873 文件**全部保持。

统一 desktop 首次为 **487 passed／2 failed，80.06s，exit 1**：Codex 的短 basetemp 在该进程 TEMP 外，两个既有 B3 入口用例先被“必须在系统临时根下”正确拒绝，未跑到各自预期分支。首根、输出与失败保留，未改源码或断言。随后只给新的独立验证进程配置全新短 TEMP／TMP，再于其子目录跑完整套件：**489 passed，80.68s，exit 0**，2 条原有 Starlette／anyio 弃用警告保留；不是把两轮数字拼成单轮通过，不改变系统全局 TEMP 或长路径／防护设置。既有后端 848 与前端检查只按生产源码不变引用，不冒称本轮重跑。

系统 Windows PowerShell **5.1.26100.9711** 独立 parser：**0 errors，27 functions，exit 0**；只是解析，没有绕过其 Restricted 文件执行策略。D r02 的现有 PS7 微型夹具为 49 checks／exit 0，PV 与原生架构纯反例各 7 项；真正 PS5.1 脚本运行及目标电脑仍未验。

构建前模型审计覆盖本轮起点：A 新增 **151** 条、B **221** 条 assistant 均为 build／opencode-go／deepseek-v4.1-flash／max；各自 3／5 次 agent-switched 都是 build→build，没有本轮 model-switched 或 compaction。C **200**、D **306** 次 model_request_end 都是 deepseek/deepseek-v4.1-flash／max，原生 ID 未变；包含 D 首轮 exit 8，不删掉该失败来美化统计。未发现子代理工具，后续构建／Git 的新增元数据另记。

Codex 据此仅放行 A 在全新 `build/desktop-e14-win11-r01` 构建完整 onedir／ZIP；源、测试、PS1 保持冻结，不启动候选。合成种子备份若生成，另放 handoff 目录、由当前源码服务创建，不能记作新冻结包 UI 导出的证据。

## 6. 首次实际候选 r01：构建成功，静态未通过

A 实际在新根 `build/desktop-e14-win11-r01` 完成 Vite／PyInstaller／ZIP，未执行产物。build_id 为 `1b3a4c42-febc-46f8-bac4-4fa23957efc3`，ZIP **43,960,853 bytes**，SHA `3f09641aa1645459931556a5dc55205820a42d2efcd2dcde3526d68bb5185943`。243 项 before／after 与构建前批准 digest 相同，版本 0.1.0／schema 0006；带本轮改动的基线 91e6a553，不冒称纯基线构建。

Codex 在全新 Python 进程、导入 verifier／PyInstaller 前安装拒绝子进程的外层 audit hook，独立实际运行两个静态命令：包 **54 checks／exit 1**，失败 `archive_pyz_matches_freeze`、`privacy_no_absolute_paths_in_text`；ZIP **59 checks／exit 1**，失败 `no_absolute_paths_in_text`。缺项／非布尔／未知列表为空，两个外层 process_events 均为 0。不是运行期失败，也不把构建 exit 0 写成静态通过。

实际 CArchive／PYZ 共 1840 模块，103 个核对范围内模块与当前源全部匹配，必需／维护／备份恢复模块均在；但五个实际归档 D0 来源未在 freeze：`d0_db`、`d0_driver`、`d0_host_api`、`d0_server`、`d0_word`。交 A 补来源，不通过改分类或跳过模块掩盖缺口。该例说明仅已知必需列表／模块数量不能证明来源闭包。

两处文本命中经直接回读辨明：前端 Vue 正则字面量被当作 UNC；cryptography SBOM 的上游 `file:///D:/a/cryptography/...` 引用与已安装依赖来源逐字节相同（来源 SHA `ca81fd6162fbb9c39d1c4530c4beb49dd3f938a77cb867f82ce788def949e3ce`），不是本机构建用户路径。交 B 作可判别扫描，C 补真实个人路径、修改 SBOM 与正则／原始依赖正控制；不删 SBOM／许可证、不改前端、不整文件跳过扫描，metadata／代码文件名仍严格检查。

r01 产品、ZIP、外层和当时的独立合成种子共 **198 文件**另存保护指纹；不覆盖／改写／复用首失败根。种子仅为源码服务生成，不能作为新冻结包 UI 备份证明。后续使用新的物理构建根 `desktop-e14-win11-r02`，保持既定便携文件名合同，由实际路径、build_id 和 SHA 分开；未为绕过 SAC 运行或改名任何 EXE。

## 7. r02 构建前复验

A 仅补五个实际 D0 来源，不改其代码或降低模块分类；B 的指定 SBOM 引用只在对应文件与已安装来源 SHA 一致时允许，返回单列 allowed_build_references，不整文件跳过；C 新增真实归档的前端／SBOM／普通文本／metadata 泄漏负例、原始依赖与正则正控制。两种扫描路径共用相同判别含义，未知／非布尔／固定必需集及进程守卫保持。

所有相应原生会话自然停写后，Codex 新短 TEMP 单轮完整 desktop：**493 passed，78.22s，exit 0**，2 条既有警告；248 项 before／after 完全一致，digest `9b36ab682e2740eb0d881d5bb56d9b13d6d351a9e335b2e2deaac9cc613930f5`。r01 的 198 项产物指纹保持。只据此放行新的 r02 物理根；不复跑／覆盖 r01 来改写首失败，也不改变产品版本、签名或发行边界。

## 8. 最终 r02 实际候选：独立静态通过

A 在全新 `build/desktop-e14-win11-r02` 完成 check-paths／Vite／PyInstaller／完整 ZIP，均 exit 0；B 只读检查实际 r02 亦全部通过，两会话随后自然结束。逻辑文件名仍为 `KGNext-E14-win11-r01.zip`，物理 root、build_id、SHA 与首失败 r01 分开。源冻结 248 项 before／after 均为 §7 的 `9b36ab68…`，生产源码未另改，构建来自带本轮改动的 `91e6a553…`，不是纯基线。

| 实际身份 | 值 |
| --- | --- |
| build_id | `b16df7a7-d575-4555-bdee-84e42367a5e9` |
| version／schema | `0.1.0`／`20261025_0006_local_game_observations` |
| 产品目录 | `build/desktop-e14-win11-r02/package/KGNext-E14`，190 files／80,503,817 bytes |
| 产品树 SHA | `4e9892e5cc39df8823eff5db09b42523d430c2875e1289daa20af1e9746e3389` |
| 主 EXE SHA | `814c7c0d1015319fea8d9f25c35fcf6704db5ef8835494c1dd6d99a7ff8074f8` |
| ZIP | 43,963,375 bytes／193 entries，SHA `63bd8f79c549223d0bc19d06b9773a99efd9b06d00e7de60cacf1975ac21dc35` |
| manifest SHA | `88f9cb357694d22df756bf3a752d8231c6dafcebb3e02f6b7cfcab555aafc6e4` |
| SUMS SHA | `e6a9c5ed569098bf984e6b8fdd9d0c8159b3faea985365e6b998e1a56dee61a6` |
| frontend | 新构建 3 files，digest `bf5b29935932d413993600e0e5083df49429b960fd5b2cd7eab814b265c85391` |

Codex 用两个全新源码 Python 进程，在导入 verifier／PyInstaller **之前**安装外层 audit hook，拒绝 subprocess／system／startfile／exec／spawn。显式实际目录静态命令 **54 checks／exit 0**，ZIP 静态命令 **59 checks／exit 0**；所有固定必需项明确为 true，failed／missing／non_bool／unknown 均空。两个外层 `process_events=[]`，不是仅相信检查器自己打印 static。原始报告及外层守卫分别为私有 `codex-actual-r02-package*`／`codex-actual-r02-archive*`。

另用 PyInstaller CArchiveReader／PYZ 和 ZIP 实际字节直接交叉核对，而非仅汇总 A／B 布尔：1840 模块中 89 production、14 verification_support 共 **103** 项编译结构指纹全部匹配；89 个实际生产来源全入 freeze，missing 0；53 个必需模块齐全，真实入口同源。ZIP 文件集、实际 190 文件、每项大小／SHA、manifest 和 SUMS 完全对应，192 条 SUMS 覆盖除自身外全部成员；产品无硬链接。证据 `codex-r02-independent-artifact-linkage.json`。190 是本轮实际枚举，不借用旧包同数量结论。

隐私扫描的私有路径、私钥、metadata／code／text 绝对路径均空；8 个已知上游 SBOM 引用仅在来源原字节 SHA 相同时允许。目录／ZIP 均有界读取，无解包或候选运行。受控模板、前端、全部迁移、许可证、Pillow 插件和备份维护链按实际产物通过；静态匹配不替代目标可运行性。

### 8.1 本机只读预检与签名清点

只在新自有 TEMP 目录核定 ZIP SHA 后解压已通过静态安全检查的候选副本；用**既有 PS7.6.5** 普通权限执行审核后的 PS1，显式传入预期 ZIP／build_id／schema 和未创建的合成 data／credential 根。**49 checks／exit 0，失败 0、未知 0**。环境为当前开发机 Windows 11／原生 AMD64，有实际 WebView2 Runtime，SAC／WDAC 状态只读记录，不改系统设置，不执行候选。原始 `codex-r02-self-preflight/report.json` 私下保留；`scope=self_current_machine_only` 不能被解释为已操作另一台电脑。

全部 **107 PE**：**76 Valid、31 NotSigned**，其它／坏签名／未知 0，主 EXE **NotSigned**。文件完整性通过不代表信任或运行许可；当前已知 SAC4551 继续保持。PS5.1 独立 parser **0 errors／27 functions**；其 `-File` 已被 Restricted 阻止的 exit 1 仍保留，PS7 通过不替代 PS5.1 实际运行，也不通过 Bypass／粘贴脚本变相执行。

## 9. 实际合成备份交接与保护源

A 在全新私有根，用冻结的现有源码 fixture／SnapshotService 生成两份合成包；仅四文件放在 `build/desktop-e14-win11-r02/handoff-synthetic`，不进入产品或 ZIP。明文 SHA `f652d8fac9a99c65433922d17f09eed037b5cc678bf3dbac485d887ef4b2541d`，加密 SHA `48c598d6f5dc87c7a4fec95d4ca220d9604619dfd50ed199de99d21e89be64fa`；口令 `KGM-W11-Synthetic-Only` 仅为合成测试。两 manifest 身份为 `synthetic_source_service`／本轮 freeze，不能记作冻结 UI 创建。

Codex 在另一个全新隔离源码 Runtime 中独立验证**实际交接文件**：两备份 SHA、解密后数据库 raw SHA `901afa1332ab9f9393e9ad884017644ec4b7aded579c38e4627288de78284b61`、41 表完整／业务指纹及 12 个资源与原种子一致；AI 任务为 succeeded 2／failed 1／outcome_unknown 1，无 live 或自动重发；缺口令明确报 `BACKUP_PASSWORD_REQUIRED`。两包 SUMS 与 README 自身 SHA 分别核对，handoff 恰好四文件，无 raw DB／DPAPI／工作目录。网络守卫在 Runtime 前安装，attempts before／after、log 均 0，audit true。A 的独立 child guard 自检刻意拦截 1 次，另记，不混入种子生成网络 0 或冒称 OS 级抓包。

独立验证脚本首两次因 Codex 自己漏传 SnapshotService 必需 `source_identity`、误以为 handoff SUMS 也覆盖 README 而 exit 1，均保留原日志与独立私有根；未修改源码、断言合同或交接文件。正确按既有 API 与两备份 SUMS 合同运行后 exit 0，证据 `codex-r02-independent-seed-verify.json`。以上只是源码服务校验，目标 UI 创建、完整恢复和保护包接续仍需手册实证。

最终复核原 **5** 项保护源、旧 E14 **873** 文件、首失败 r01 **198** 项产物指纹均保持；当前 248 源文件与已测 freeze 逐项相同。真实 secret、原业务库／凭据与旧包只复核已有指纹；原始证据、备份和候选不入 Git。

## 10. r02 范围结论与下一步（最终 r03 见 §12）

| 范围 | 最终结论 |
| --- | --- |
| 本轮源码／守卫／反例 | 493 desktop 单轮通过；生产后端／前端未改，848 与前端旧结果仅按身份引用 |
| r02 实际完整候选 | 目录 54／ZIP 59 静态通过，103 模块和字节完整性已独立比对，未执行候选 |
| 本开发机预检 | PS7 49 项通过；签名清点完成，主 EXE 未签名；PS5.1 实际文件执行受阻未验 |
| 合成种子 | 源码服务生成及实际交接独立校验通过，不是冻结 UI 备份／恢复 |
| 另一台 Windows 11 | 尚未操作；原生架构、预检、普通入口、备份恢复、原生文件保存均未验 |
| 新 Word／教师体验 | W1–W8 新包逐页与教师本人确认未验；不以旧 Word／XML 代验 |
| 真实 AI／WebDAV／签名／公开发行 | 本轮未执行，未获本轮自动启动范围 |

下一步先取另一台 Win11 的**实际只读预检**，再按普通入口、合成资料、备份／保护包接续和 W1–W8 Word 收证。此时再继续扩功能或重复构建不能解决目标运行证据缺口；若首次被策略阻止，记录并停止，等签名／环境条件明确后另安排，不降低保护。本轮没有目标机访问，不代填通过或等待无变化条件。独有合同已归计划、结果、本报告及手册，原实施提示词已替换为[唯一下一步入口](../tasks/current.md)，不留 prompt-final-v2/v3 副本。

## 11. 模型、文档与 Git 门禁

实施／静态阶段的原生会话 ID、实际模型 metadata、自然退出和 idle 另存私有审核；A／B 均为 build／opencode-go／deepseek-v4.1-flash／max，C／D 均为 deepseek/deepseek-v4.1-flash／effort max，无 fork／子代理。D 初轮 exit 8 保留，后续同会话续跑；不把指定命令参数当实际模型证据。Git 阶段原会话新增 metadata 由提交后独立回执另审。

最终文档整合由 Codex 完成，包括 A 停写后结果最终状态、D 停写后中文手册、当前提示词与索引。源／测试／PS1 在 §7 后保持冻结，文档修改不重建候选，不冒称候选来自最终纯提交。卫生核查包括 diff --check、UTF-8／替换字符／私有路径、本地文档链接、忽略规则及真实候选／保护源指纹。

仅批准本轮 **14** 个具体路径：`AGENTS.md`；builder、两 verifier、两测试、PS1 六文件；bootstrap 索引、原备份核查、本计划／结果／本报告／手册、唯一任务入口共七文档。Codex 在私有精确清单固定每项 Git blob／mode、父提交 `91e6a553db6d25a1603849f139f22e9d9097537b` 和预期 tree 后，原 OpenCode 才能逐项暂存，核真实索引 tree，再普通 commit／push 到 `codex/desktop-v2-foundation`。不 add-all、改文件、amend／rebase／force、不改 main／默认分支／可见性、不创建 tag／Release。实际提交后 Codex 再核 parent／tree／14 blobs、远端、clean、源及保护指纹；不把提交前合同写成已推送，不为回填自身 SHA 造成循环提交。


## 12. 最终卫生收口与 r03 复验

Git diff --check 最后发现测试 `test_e14_build_guard.py` 新增 EOF 空行；这不是应用失败，也不改写 r02 的 493／54／59 通过事实。C 原生同会话仅删末尾一个 CRLF，保留旧字节；Codex 独立证明补回该 CRLF 即恢复旧 SHA `d12036e0…`，当前 SHA `16f2c4fb92a46d822d62f3a54698f0f368636d885a7872baa42f83553b663334`。248 来源仅此项改变，生产代码／两个检查器／PS1 均不变。既然验证测试也在 freeze，选择全新 r03，未事后改 r02 metadata 或冒称它与当前原字节一致。

C 停写后 Codex 完整单轮 **493 passed，78.30s，exit 0**，2 条既有警告。前后 248 原字节一致，新 digest `e1bbc5b01a1b55efece4a45089dc22f9e34fc872908bbb9c261aea85d0c03208`。A 在全新 `build/desktop-e14-win11-r03` 完成实际 Vite／PyInstaller／ZIP 及 fresh SOURCE-SERVICE seed，均 exit 0，未写 tracked 源／文档；r01、r02 各 198 产物另存指纹保持。

最终 build_id `5babc817-5b2a-466b-b382-36cffa02cace`；ZIP 43,963,980 bytes，SHA `0a1b9c0b55612de889e621f70ed1374d8e792d3755d9fce1eadf17b7b6532470`；190 产品文件／80,503,817 bytes、193 ZIP entries，实际 EXE SHA `bb9214c2976aba96393740eee1aacb7727487aa294529849e4fe6a1cd989e9c3`。完整 manifest／SUMS／frontend／种子身份见[结果 §9](desktop-windows11-portable-result.md#9-最终-r03eof-格式收口后的独立身份)。逻辑 ZIP 名仍含 r01；不得按 basename 或旧 190 数量替换实际身份。

B 对实际 r03 静态正常结束并通过。Codex 两个独立冷进程、导入前外层启动守卫：**目录 54 checks／ZIP 59 checks，exit 0**；固定必需项 true，failed／missing／non_bool／unknown 和 outer process events 均空。直接字节／CArchive／PYZ 交叉核对：89 production＋14 support 非入口模块全部同源、全生产入 freeze、53 必需齐全；CArchive 入口及 PYZ 重复的 d1_main 也另外匹配。独立补充脚本首次把 PYZ 重复入口计作第 90 个生产项而触发预期计数失败；保留首轮输出，之后分列入口并仍实际比对其指纹，未跳过或修改产物／检查器。

本机新解压副本 PS7 只读预检再次 **49 checks／exit 0**，失败／未知 0；107 PE 为76 Valid／31 NotSigned，主 EXE NotSigned。PS5.1 仅解析通过、文件执行受 Restricted 阻止的历史边界不变；没有运行候选或访问目标机。新 r03 两份合成交接又由 Codex 新隔离源码 Runtime 独立校验，DB／41表业务／12资源／两备份 SHA 相符，加密缺口令拒绝，主网络守卫 0、audit true；只是源码服务身份。

当前唯一交接已改为 r03，目标手册与下一步提示词中的 ZIP SHA／build_id／freeze／script SHA 已填实际值。r01 首失败、r02 通过及所有私有原始日志保持；目标普通运行、原生保存、冻结 UI 备份恢复／保护包再恢复、新 Word／教师确认、签名及发行仍未验。提交放行继续按 §11 的14路径、父提交与私有精确 blob／tree 清单，Git实际回执在提交后独立核对，不自填推送。

提交前全轮实际模型审计：A **237**、B **276** 条 assistant 均为 build／opencode-go／deepseek-v4.1-flash／max，已分页覆盖本轮起点；C **241**、D **306** 次 model_request_end 均为 deepseek/deepseek-v4.1-flash／effort max。同一原生 ID，无 parent／fork／子代理，没有本轮 model switch 或 compaction；两 OpenCode 均 idle 晚于 busy。C 包含 EOF 修正，D 初轮 exit 8 保留；各后续请求自然结束。Git 新增 metadata 留提交后独立回执。
