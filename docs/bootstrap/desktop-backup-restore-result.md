# 完整本地备份／恢复：B1 实施记录

更新：2026-10-31。状态：**B1、B2（共享捕获／恢复核心／宿主）与 B3 真实源码窗口已在当前 Windows 11 合成环境按 Codex 独立核查 §38 通过；全 local 848、最终完整桌面 469、完整前端类型／测试／构建；B3 覆盖首次页 setup、保护包再恢复、新进程工作、权限／故障／取消边界。最终冻结复核 actual `session.active={}`；desktop 469 passed（2 existing deprecation warnings，79.36s）；461 code/resource hash stable、app 439 stable；final pure 25/25 PATH probes（path+roles/unknown outputs）＋独立 composite/calendar multiplicity 矩阵＋2/2 watchdog probes（97cd2/2 blocking destroy both done flags force mock exit without await）；restart 066+97cd actual new Python on same own post root `kgm-b3-cdx-post-r05-2be4bf`，UI new body 6/6、full41/all resources unchanged、guard0/latestclosed。教师人工体验、冻结包与发行未通过；不发行、不启动 WebDAV、不自动重写公开历史。本报告是 pre-Git handoff；最终 Git 身份以桌面分支历史／最终 review §39 为准。**

基线：默认 `main`／桌面分支 `e836726f008676fc603a7b4cb058e5d96cafe60b`，业务 tree `5ab0c581985fb9f6fe229ed10dadf7b809ca81ec`，文档收口 tree `c6a139c619f696765d128fefbcb4970cff2af973`。B1 已提交为 `7d2759b76a16528e3e42d720a9203be40b6383a1`（tree `b89cda2846a78f64859760bbb30934a24fd8e86b`，parent `e836726f008676fc603a7b4cb058e5d96cafe60b`）；B2-S1 及后续源码改动未由本报告提交，最终 Git 身份以桌面分支历史／review §39 为准。产品决定 P01–P06 见[备份规格](../specs/desktop-backup-restore.md)（P06 首次启动与设置页均提供恢复入口）；Codex 最终独立结论见[独立核查 §38](desktop-backup-restore-review.md)。

**最终交接（pre-Git）**：本报告记录 pre-Git handoff；最终独立冻结复核见 review §38，Git 身份见 §39。实际独立回执为 `b3-final-full-desktop-independent-receipt.json`／对应 log（desktop 469 passed，2 existing deprecation warnings，79.36s；461 code/resource hash stable，app 439 stable；actual `session.active={}`）与 `b3-final-restart-independent-receipt.json`（restart 066+97cd actual new Python on `kgm-b3-cdx-post-r05-2be4bf`，UI new body 6/6、full41/all resources unchanged、guard0/latestclosed）。final pure 25/25 PATH probes（path+roles/unknown outputs）＋独立 composite/calendar multiplicity 矩阵＋2/2 watchdog probes（97cd2/2 blocking destroy both done flags force mock exit without await）。B1／B2／B3 为当前 Windows 11 合成环境限定源码通过；教师人工体验、冻结包与发行仍未通过。未 Git commit／push；不发行、不启动 WebDAV、不重写历史。

> §1–§7 为 r02 记录、§8 为 r03 记录、§9 为 r04 回修记录、§10 为 B1 最终独立结论；本轮 B2-S1 共享接口见 §11。

## 1. r02 实际改动

新增 local 层：

- `backend/app/local/backup_format.py`：Format 1 头、magic、模式、固定 Scrypt 参数、流式加解密／hash；没有 `maxmem` 参数。
- `backend/app/local/backup_zip.py`：在 `ZipFile` 构造前有界解析中央目录，限制成员数、中央目录字节、名称长度、展开体积；拒绝加密／压缩／数据描述符／重复／大小写冲突／文件目录冲突／本地头不一致。
- `backend/app/local/backup_fs.py`：Windows 目录链／文件句柄 lease、受限私有工作区、受控清理、输出临时文件与 no-replace 发布；目录句柄用 `GENERIC_READ` 且不共享 delete，实际阻止父目录改名／junction 替换。
- `backend/app/local/backup_barrier.py`：按数据根隔离的两阶段维护屏障；intent／exclusive、DB writer／文件操作计数、AI 内部写 scope、lease token。
- `backend/app/local/backup_validate.py`：按 Alembic revision 构建规范 schema 并比较真实结构；严格 manifest JSON；资源图片真实解码；旧库先验源结构再隔离迁移。
- `backend/app/local/backup_snapshot.py`：SQLite 在线 backup（分页进度／取消）、全部登记原图／衍生图、确定性 STORED ZIP、明文／密码容器、校验、发布终态、隔离 verify。

必要接入修改：

- `backend/app/local/tx.py`：`begin_immediate` 在 SQLite 写锁前登记 barrier writer；嵌套 BEGIN 不重复计数，rollback／commit／close 通过 transaction-end 配对释放。
- `backend/app/local/ai_executor.py`：freeze owner 独立（close／snapshot 不互相清除）；claim／dispatch mark／finalize／pending flush 使用 AI 内部写 scope；新增 `is_snapshot_idle`；未改变 close 的 revoke／drain 语义。
- `backend/app/local/observation_assets.py`：`import_asset` 整个 staging→文件搬移→DB 提交阶段持有文件 scope；`inspect_managed_asset` 增加可选字节上限参数，供 B1 以 64 MiB 资源上限复用 E03 解码校验。
- `backend/app/local/observation_export_service.py`：导出临时 artifact 写入／删除持有文件 scope。
- `backend/tests/local/test_backup_snapshot.py`：26 个真实 SQLite／文件系统／Windows 句柄测试。
- `.gitignore`：增加 `*.[kK][gG][mM][bB][aA][cC][kK][uU][pP]` 及私有工作目录／临时文件的逐字符大小写规则；`git -c core.ignorecase=false check-ignore --no-index examples/backup.KgmBackup` 命中，exit 0，模板仍可跟踪。

未修改 `ARCHITECTURE.md`、迁移、依赖、构建、前端、desktop UI 或 B2 恢复代码。

## 2. r02 协议与安全边界

- 文件：`.kgmbackup`，128 字节头 + 载荷 + 可选 16 字节 GCM tag；magic `KGMBKP1\0`，版本 1。
- 明文：KDF／盐／nonce／tag 为 0；头 SHA-256 仅损坏检测，不是来源认证。
- 密码：Scrypt 固定 `N=2^17,r=8,p=1`、随机 32-byte salt、随机 12-byte nonce、AES-256-GCM；完整头为 AAD；认证通过前不解析载荷；未使用不存在的 `maxmem`。
- 载荷：确定性 ZIP_STORED，顺序 `manifest.json`、`db/kindergarten.db`、按路径排序的资源；无压缩炸弹、无 ZIP 加密成员、无符号链接。
- manifest：64 MiB 上限；严格字段集合／类型／范围；快照 ID、UTC 时间、应用版本、源 DB revision、AI contract 列表、DB/资源路径／大小／SHA-256、计数、源身份。
- 技术上限：总包／展开 64 GiB、DB 8 GiB、单资源 64 MiB、成员 250,000；超限完整失败，不截断、不静默漏图。r02 用故障注入常量验证拒绝路径，未真实填满这些上限。
- 资源仅来自数据库登记的 `LocalObservationAsset`／`LocalObservationAssetDerivative`，包括已移出当前稿但历史／AI 引用的图；`observations/staging`、`export-temp`、磁盘 orphan、旧备份、`migration-backups`、程序、模板、Word、凭据根不纳入也不删除。
- DB 全快照保留 `local_ai_credentials` 的 key_id／nonce／ciphertext／state 与 `local_ai_state.database_uuid`；不读取、不导出 `credential_root/<database_uuid>/<key_id>.dpapi`，不解密 secret。

## 3. r02 一致性、屏障与私有工作区

- `SnapshotService.create()` 顺序：维护 intent（拒绝新外部 DB／文件／AI 提交，已接受操作可完成）→ 等待 DB／文件计数归零 → 等待 live AI task 终态 → 以 snapshot owner freeze AI → 等待 active／pending result 静止（仍可穿 intent 持久化）→ 原子 `acquire_exclusive` 并二次核对 → 可选宿主 `external_quiesce` → SQLite backup／资源复制。
- `ai_write_scope` 只允许穿过 intent，绝不穿过 exclusive；`file_scope` 同样。exclusive 内任何 writer 登记被拒。
- writer 计数与 lease token 在同一条件锁内配对；嵌套 BEGIN 失败不重复计数，rollback／close 释放外层；旧 lease 即使 owner 名相同也不能清除新 owner。
- 快照明文工作区：`credential_root.parent/backup-work`（现用数据根与独立凭据根之外），目录与文件用当前用户受限 DACL；verify 使用同一工作根下的 `verify-*`。输出父目录从卷根到目标父目录全部持 `GENERIC_READ`、不共享 delete 的目录句柄；源图片和输入包用真实文件句柄读取，禁止链接／重解析点／多硬链接。
- 密码模式目标卷只接收最终容器的密文字节；明文 DB／资源／ZIP／解密载荷只在受限私有工作区。verify 成功后 `VerifiedSnapshot.staging_root` 仍在私有工作区，`discard_verified` 只清理该 `verify-*` 对象。
- 最终发布使用同卷 `os.link` 原子 no-replace；目标已存在或最后阶段并发创建目标时保留原字节并失败，不先 `exists()` 再 `os.replace`。发布前可取消；发布后不再响应取消／进度回调，结果单调。
- B1 不接 UI，也不把宿主测试替身说成已接通。B2 接点：`VerifiedSnapshot.manifest`、`database_path`（迁移后目标）、`source_database_path`（原始隔离副本）、`resources_root`、`staging_root`、`source_sha256`、`target_sha256`、`source_revision`、`target_revision`；B2 负责 native save／页面关闭／保护副本／成组切换。

## 4. r02 校验器

- SQLite：在线 backup（含已提交 WAL）；`integrity_check`、`foreign_key_check`、`local_alembic_version` 唯一已知 revision。
- 可信 schema：按 revision 在隔离空库运行同一 Alembic 链，比较规范化 `CREATE` 文本、`table_info`／`table_xinfo`、FK、index 列表与索引列；只跳过 `sqlite_sequence` 和真实 `sqlite_autoindex_*`，`sqliteXprobe` 等未知内部／trigger／view／virtual object 拒绝。旧库迁移前先验源 revision 结构，迁移后再验 head 结构。
- 业务校验：当前稿／历史版本／当前指针、照片归属与连续顺序、AI input→execution→attempt→candidate、日计划当前内容、term calendar、class game head、personal prompt head、AI config、恢复／导出回执。
- 资源：数据库登记路径必须等于 manifest；逐文件大小／SHA-256／DB hash；再调用 E03 `inspect_managed_asset` 真实解码、格式／尺寸／EXIF／ICC 校验；拒绝坏图、缺图、额外资源、路径穿越、链接／重解析点。合法历史图只复制字节，不重编码。
- 旧库：manifest 先对原始 DB 字节／hash／源 AI contract／源资源校验，再在隔离副本迁移；保留源与目标各自 revision／hash。迁移后物理 hash 不用于否定原包。
- 严格 manifest：重复键、未知字段、NaN／Infinity、bool 伪整数、错误类型／范围、未排序／重复路径均拒绝；ZIP 成员、manifest 资源、DB 登记精确一一对应，额外成员拒绝。

## 5. r02 自测与独立证据

命令均在 `backend` 下使用既有 `desktop/.venv-d1`，未安装依赖；日志为私有证据根下相对文件名。

| 命令／探针 | 结果 | 日志 |
| --- | --- | --- |
| `python -m py_compile` B1 改动文件 | RC 0 | 终端 |
| `pytest tests/local/test_backup_snapshot.py -q` | 26 passed，16 warnings（SQLAlchemy datetime deprecation） | `opencode-b1-r02-tests-r22.log` |
| Codex `codex_b1_probes_r02.py`（独立，11 反例） | 11 passed / 0 failed | `opencode-b1-r02-codex-r02-probes-r10.log` |
| 观察／日计划／配置／并发／迁移／W3 执行器回归 | 144 passed | `opencode-b1-r02-regression-r05.log` |
| 导出／历史／流式 AI 回归 | 99 passed | `opencode-b1-r02-regression-r06.log` |
| 600 原图＋600 衍生图、>30 MiB、Windows working set | 包 53,465,784 bytes；1200 资源；working set baseline 128,319,488 / peak 147,353,600 / delta 19,034,112 bytes；tracemalloc peak 7,393,982 bytes | `opencode-b1-r02-memory-r04.log` |
| `git check-ignore --no-index` 包名与私有目录 | RC 0 | 终端 |

B1 测试覆盖：明文／密码、正确／错误密码、截断、头／载荷篡改、目标碰撞 no-replace、发布后取消单调、DB 复制中取消、未知触发器／`sqliteXprobe`／无约束伪 schema、已知旧 DB 完整容器、WAL、当前稿移除但历史保留、全部登记衍生图、600 真实 JPEG／31 MiB＋、屏障 exclusive 内 AI scope 拒绝、嵌套 BEGIN 计数、旧 lease token、HTTP 维护 409、设备路径拒绝、私有 DACL、junction 清理拒绝、坏图拒绝且不改原字节、日计划＋多观察＋AI 成功／失败／unknown＋合成密文。

首失败保留（r02 过程）：

- `opencode-b1-r02-tests-r01.log`：`BackupPathError` 构造参数错误、旧 `_publish_no_replace` 接口缺失；修正后继续。
- `opencode-b1-r02-tests-r02.log`／`r03.log`：旧测试仍用 `x`／`y` 伪 JPEG，被真实解码校验拒绝；改为真实 JPEG 并修正期望。
- `opencode-b1-r02-tests-r04.log`：测试内 SQLite 连接未关闭，清理报 WinError 32；改为显式关闭连接，不用产品吞错。
- `opencode-b1-r02-tests-r06.log`：私有工作区构造参数与旧路径假设不一致；修正测试根。
- `opencode-b1-r02-r02-r01.log`：`DirectoryGuard` 只用 `FILE_READ_ATTRIBUTES` 时父目录仍可改名；改为 `GENERIC_READ` 且不共享 delete 后通过。
- `opencode-b1-r02-codex-probes-r01.log`：独立脚本路径缺少 `PYTHONPATH`；修正执行方式后重跑，不改脚本。
- 测试编辑时把 `b"SQLite format 3\x00"` 写成实际 NUL 字节，`py_compile` 报 `SyntaxError: source code string cannot contain null bytes`；改为 `b"SQLite format 3" + bytes([0])` 后通过，未进入产品代码。
- r01 独立脚本的 `cleanup_verified` 假定 verify staging 在系统临时目录且名为 `kgm-backup-verify-*`；r02 按 Codex r02 夹具把 staging 放到 `credential_root.parent/backup-work/verify-*`，旧 cleanup 断言不再适用。未修改任何独立脚本；当前 `codex_b1_probes_r02.py` 的 11 项反例通过，且使用 `SnapshotService.discard_verified` 清理。

## 6. r02 当时未验事实（历史；最终见 §10）

- 未测真实磁盘不足、权限拒绝、文件占用、进程崩溃／真实断电；只做受控取消、目标碰撞、junction 父目录替换和故障注入。
- Windows working set 只测本机合成 600 图进程；不能外推到所有机型、Scrypt 峰值或真实教师照片库。
- B1 未接宿主 native save／页面关闭；`external_quiesce` 只有接口与测试替身，不能声称宿主已接通。
- 64 MiB manifest 填满、250,000 成员、64 GiB 总包／展开上限只用常量故障注入验证拒绝路径，未真实填满磁盘。
- 旧库完整容器为合成空 0005；真实非空旧库迁移、旧 AI 历史 contract 全量组合未验。
- 未测真实 DPAPI 跨用户／换机；只按规格排除材料，不读真实密钥。
- 未执行 B2 恢复、成组切换、保护副本、阶段日志、重启恢复；未做 B3 源码窗口闭环。
- 未调用真实 AI、未连接 WebDAV、未构建／执行冻结包、未 Git。

## 7. B2 交接

`VerifiedSnapshot` 提供迁移后隔离数据库、原始隔离副本、资源根、manifest、源／目标 revision 与 hash、私有 staging。B2 必须自行实现恢复预览、保护副本、运行锁／引擎排空、DB 家族与 assets 成组切换、持久阶段日志、启动前核对、AI 不重放及失败回退。B1 不把 `staging_root` 当作已恢复数据，也不把 `external_quiesce` 测试替身当作宿主接续。B2 不得假定 `staging_root` 在系统临时目录；它在 `credential_root.parent/backup-work/verify-*`，清理须用 `SnapshotService.discard_verified`。

## 8. r03 最小回修（2026-10-31，实现者自测）

本轮只回修 Codex §6 的三个实际失败，不扩展 B2／窗口／冻结／发行。

### 8.1 B1-R02 detached cleanup swap

- `backup_fs.remove_tree()` 改为逐层目录守卫：每个目录先打开 `DirectoryGuard`（真实目录句柄、无 delete share、核验最终路径），再 `lstat`／`scandir`；该层所有子项删除完成前一直持有句柄，之后才释放并只做一次非递归 `rmdir`。
- 根目录期望身份来自 `PrivateWorkArea.path_identity`／`VerifiedSnapshot.staging_identity`；子目录身份由父目录 `DirEntry.inode()` 与父 `st_dev` 绑定；文件删除前用 `FileLease` 核对身份。异常路径在 `finally` 释放所有句柄。
- `detach` 后清理不再只靠一次 `lstat` 拒绝预先存在的 junction；遍历期间目录改名／junction 替换被真实句柄阻止，失败不会静默跳过或记作清理成功。

### 8.2 B1-R04 schema literal semantics

- `_normalize_sql()` 不再对完整 SQL `casefold()`／`split()`；改为 SQL 词法扫描，只规范化引号外的关键字／空白，单引号字符串、双引号／反引号／方括号标识符逐字节保留，包括大小写、空白和转义。
- 因此 `state <> 'active'` 与 `state <> 'ACTIVE'` 不再等价；正常当前库和原完整 0005 容器继续通过。

### 8.3 B1-R10 忽略规则

- `.gitignore` 用逐字符字符类覆盖任意扩展名大小写：`*.[kK][gG][mM][bB][aA][cC][kK][uU][pP]`；私有工作目录、`verify` 目录、私有临时文件同样使用逐字符规则。
- `git -c core.ignorecase=false check-ignore --no-index examples/backup.KgmBackup`：命中，exit 0；`nested/BACKUP-WORK/x`、`.KGM-BACKUP-x.tmp` 亦命中；模板 `backend/app/assets/word_templates/daily_plan.docx` 不被忽略（exit 1）。

### 8.4 自测证据（实现者自测，不是 Codex 独立通过）

| 命令／探针 | 结果 | 日志 |
| --- | --- | --- |
| `pytest tests/local/test_backup_snapshot.py -q` | 28 passed，16 warnings | `opencode-b1-r03-tests-r02.log` |
| `pytest tests/local/test_backup_snapshot.py tests/local/test_backup_fixture_support.py -q` | 32 passed，16 warnings（含辅助夹具只读使用） | `opencode-b1-r03-tests-r03.log` |
| Codex `codex_b1_r02_extra_probes.py`（4 项） | 4 passed / 0 failed | `opencode-b1-r03-extra-r04.log` |
| Codex `codex_b1_probes_r02.py`（原 11 反例复跑） | 11 passed / 0 failed | `opencode-b1-r03-probes11-r01.log` |
| `py_compile` B1 改动文件 | RC 0 | 终端 |
| R10 混合大小写 `check-ignore` | exit 0；公开模板 exit 1 | 终端 |

新增测试：`test_schema_check_literal_case_is_rejected`、`test_detached_cleanup_swap_keeps_outside_marker`。原有 600 真实 JPEG 测试保留。

首失败保留：

- Codex 原始独立结果 `codex-b1-r02-extra-a13dda19`：detached cleanup 返回 success 并删除对照 marker；本轮复跑 `opencode-b1-r03-extra-r01.log` 时 schema 字面量大小写仍被接受，detached cleanup 已改为身份不符报错而非静默成功。
- `opencode-b1-r03-extra-r02.log`：清理已阻止根目录改名，但子目录身份用 `DirEntry.stat().st_ino`（Windows 为 0）导致误报；改用 `DirEntry.inode()` 后通过。
- 上述失败均在自建临时根内，未触碰真实业务或外部文件；独立脚本未修改。

### 8.5 r03 当时未验边界（历史；最终见 §10）

- 仍是实现者自测；Codex §6 的 30 项、原 11 反例、完整 1.4MB 夹具和 600 图大包／密码模式 Windows 整体内存由 Codex 独立复验，本记录不宣称通过。
- 真实磁盘不足、权限拒绝、文件占用、进程崩溃／断电、真实非空旧库、DPAPI 跨用户／换机、64 GiB／250,000 成员真实填满、宿主 native save／页面关闭、B2／B3 仍未验。
- D3 长根 WinError206 仍是已知独立问题；本轮只用短合成根，不宣称修复。
- 未 Git、未开始 B2／B3、未调用真实 AI、未连接 WebDAV、未构建／执行冻结包、未发行。

## 9. r04 两个边界失败最小回修（2026-10-31，实现者自测）

本轮只修 Codex §7 的 B1-R02 canonical schema 清理和 B1-R03 工作根 fallback，不扩大功能。

源码身份：基线 `e836726f008676fc603a7b4cb058e5d96cafe60b`；本轮实际变更 `backend/app/local/backup_validate.py`、`backend/app/local/backup_snapshot.py`、`backend/tests/local/test_backup_snapshot.py` 与本结果记录，当前未提交。

### 9.1 B1-R02 canonical schema 清理

- `backup_validate._canonical_schema()` 不再使用 `shutil.rmtree(base, ignore_errors=True)`；改为复用 `backup_fs.remove_tree(base)`，对 schema 临时目录同样执行逐层真实目录句柄、身份绑定、非递归 `rmdir` 和异常释放。
- 清理失败不再吞掉：无主异常时向调用方抛出；已有主异常时附加 note 并保留主异常。`_SCHEMA_CACHE` 只在清理成功后缓存。
- 已审计 B1 清理入口：`PrivateWorkArea.cleanup()`、`SnapshotService.discard_verified()` 与 canonical schema 清理均走安全 `remove_tree`；未被产品调用的旧 `_cleanup_own()` 兼容入口已移除，不再有 `shutil.rmtree(..., ignore_errors=True)`。

### 9.2 B1-R03 工作根候选与 fallback

- `_snapshot_work_root()` 现在枚举候选：凭据根同级的 `backup-work`、系统临时根下的固定 fallback、以及带数据根摘要的隔离 fallback；每个候选都先 `resolve(strict=False)`，再分别与现用数据根、独立凭据根检查相等／祖先／后代／别名重合。
- 只有通过全部检查的候选才返回；若全部候选均与数据根或凭据根重合，则在任何创建、ACL 修改或写文件之前抛出受控 `BACKUP_WORK_ROOT_UNSAFE`，不默认写入冲突根，也不把注入根强制映射到未经检查的全局根。
- 新增测试覆盖：数据根为 `tempdir/KindergartenManager-backup-work`、凭据根位于其下时 fallback 选择不重合；数据根为 `tempdir`、凭据根位于其下时所有候选重合并受控拒绝。

### 9.3 自测证据（实现者自测，不是 Codex 独立通过）

| 命令／探针 | 结果 | 日志 |
| --- | --- | --- |
| `pytest tests/local/test_backup_snapshot.py -q` | 31 passed，16 warnings，exit 0 | `opencode-b1-r04-tests-r03.log` |
| `pytest tests/local/test_backup_snapshot.py tests/local/test_backup_fixture_support.py -q` | 35 passed，16 warnings，exit 0（辅助夹具只读使用） | `opencode-b1-r04-tests-r04.log` |
| Codex `codex_b1_r03_boundaries.py`（2 项） | 2 passed / 0 failed，exit 0 | `opencode-b1-r04-boundaries-r03.log` |
| Codex `codex_b1_r02_extra_probes.py`（4 项） | 4 passed / 0 failed，exit 0 | `opencode-b1-r04-extra-r02.log` |
| Codex `codex_b1_probes_r02.py`（原 11 反例） | 11 passed / 0 failed，exit 0 | `opencode-b1-r04-probes11-r02.log` |
| `py_compile` B1 改动文件 | RC 0 | 终端 |
| R10 混合大小写／嵌套／公开对照 | 包与私有目录命中 exit 0；模板不命中 exit 1 | 终端 |

新增测试：`test_snapshot_work_root_checks_every_fallback_candidate`、`test_snapshot_work_root_rejects_when_all_candidates_overlap`、`test_canonical_schema_cleanup_swap_keeps_outside_marker`。原有 600 真实 JPEG 测试保留；未修改辅助拥有的两个夹具文件。

注：未被产品调用的旧 `_cleanup_own()` 兼容方法在上述行为测试后移除；随后仅执行 `py_compile` RC 0，按本轮协调未再重复同源专项测试。

最后一处工作根拒绝测试的合成配置改为 `data_dir=tempdir`、`credential_root=tempdir/backup-work` 后，仅单独复跑该测试：1 passed，exit 0（`opencode-b1-r04-rootreject-r02.log`）；未重复同源全套。

**r04 回退根忽略对齐（2026-10-31，仅 `.gitignore` 与记录，无 Python 测试）：**

- 新增实际回退根 `KindergartenManager-backup-work-<16hex>` 的逐字符大小写规则（`[kK]...[rR]-[wW][oO][rR][kK]-` 加 16 个 `[0-9a-fA-F]`），覆盖嵌套路径。
- `git -c core.ignorecase=false check-ignore --no-index nested/KindergartenManager-backup-work-0123456789abcdef/verify-abc/manifest.json`：命中，exit 0。
- 混合大小写 `nested/kInDeRgArTeNmAnAgEr-BACKUP-WORK-0123456789ABCDEF/verify-abc/manifest.json`：命中，exit 0。
- `backend/app/assets/word_templates/daily_plan.docx`、`LICENSE`、`frontend/package-lock.json`：不命中，exit 1；`examples/backup.KgmBackup`：命中，exit 0。
- 本轮未运行 pytest／构建，未修改任何 Python／前端／测试源或辅助夹具。


首失败保留：

- `opencode-b1-r04-rootreject-r01.log`：拒绝测试初次用 `credential_root=tempdir`，主候选落在 tempdir 之外而未触发拒绝；这是测试合成配置错误，改为 `credential_root=tempdir/backup-work` 后单测 1 passed。
- Codex 原始独立 `codex-b1-r03-boundaries-r02.log` / `codex-r03-boundaries-4309038c`：canonical schema 的 `shutil.rmtree` 在 lstat 后 swap 下删除对照 marker；`fallback_overlap` 返回与数据根相同的 fallback。两项实际完成 exit 1。
- 本轮修复后 `opencode-b1-r04-boundaries-r01.log`／`r02.log`／`r03.log`：2/2 通过；未修改任何 Codex 独立脚本。

### 9.4 当时未验边界（Codex §10 已复验 B1 范围）

- 当时仍是实现者自测；Codex §10 已独立复验原 11 项、新增 4 项、§7 两项、完整夹具及 600 图密码包／Windows 整体内存。
- 真实磁盘不足、权限拒绝、文件占用、进程崩溃／断电、真实非空旧库、DPAPI 跨用户／换机、64 GiB／250,000 成员真实填满、宿主 native save／页面关闭、B2／B3 未验。
- D3 长根 WinError206 仍是已知独立问题；本轮只用短合成根。
- 未 Git、未开始 B2／B3、未调用真实 AI、未连接 WebDAV、未构建／执行冻结包、未发行。

## 10. Codex B1 最终独立结论（2026-10-31）

以下为 Codex 独立审核结果，不是本记录的实现者自测；实现者 r01–r04 自测、首失败和未验范围保留在 §1–§9 与附录。

- Codex 固定 **430 个 backend／desktop／frontend 源码及资源路径**；最终独立 `pytest tests/local -q --durations=5`：**796 passed，904.05 秒，exit 0**，包含本片 35 项。
- 首轮 11＋补充 4＋同链边界 2 个反例：**17 项全部通过**；冷 schema／detach 清理替换被阻止，对照字节保持；旧完整包、AI／事务计数、真实在途图片、严格清单、坏图与取消终态复验通过。
- 完整合成档案密码大包：**157,647,029 bytes**；**604 张真实原图、1,812 个资源文件**；41 张业务表全部字段规范化指纹一致，全部图片路径／大小／字节 hash 一致；仅历史引用照片保留；原合成库与合成 DPAPI 材料保持，网络连接尝试 **0**。
- 真正非空 0005 完整容器：源 DB **446,464 bytes**，完整包 **447,595 bytes**；隔离升级至 0006 后 **26 张原业务表原有字段／行保持**，15 张新增表为空，日计划版本 1–4 及恢复收据保持；源 revision／hash 单独保留，原文件与现用合成库未改，网络连接尝试 **0**。
- Windows 大包进程峰值：`PeakWorkingSetSize` **489,267,200 bytes**，`PeakPagefileUsage` **533,716,992 bytes**；基线 116,482,048／96,514,048 bytes；校验约 139 秒。该实测不外推到全部硬件或上限填满。
- 大小写敏感 Git 忽略：10 个包／嵌套／混合大小写／新摘要后缀样例命中；模板、前端锁文件、LICENSE 三个公开对照未忽略。
- 测试前后 **430 路径集合与 hash 零变化**，5 个原业务／配置／凭据保护源、2 个旧包 hash 保持。

**限定结论：BC-R01–R04、B1-R01–R10 在本节实际后端源码／合成工程范围关闭，B1 通过；可按 Codex 批准清单由原 OpenCode 普通提交推送，再接 B2。** P06 已由用户确认首次启动与设置页都提供恢复入口；不改变本限定 B1 结论，具体 B2 宿主／UI 未实现。不把隔离副本称为已恢复当前档案；B2 保护副本／同一维护 lease／成组切换／启动接续／旧身份退役及宿主 UI，B3 源码窗口、教师实际体验、冻结包、Win10、跨机器／用户、真实断电、真实磁盘不足／权限故障与技术上限填满仍未验。D3 长根 WinError206、SAC4551 等既有边界保持；未真实调用供应商、未 WebDAV、未发行。

该段为 B1 当时状态；B1 后续已按批准清单提交推送 `7d2759b`。B2／B3 当时未开始。

## 11. B2-S1 共享维护 lease 捕获接口（2026-10-31）

源码身份：B1 已提交 `7d2759b76a16528e3e42d720a9203be40b6383a1`（tree `b89cda2846a78f64859760bbb30934a24fd8e86b`，parent `e836726f008676fc603a7b4cb058e5d96cafe60b`）；本轮 B2-S1 修改未提交，涉及 `backend/app/local/backup_barrier.py`、`backend/app/local/backup_snapshot.py`、`backend/app/local/backup_fs.py`、`backend/tests/local/test_backup_snapshot.py` 与本记录。

### 11.1 接口与行为

- `backup_barrier.MaintenanceLeaseError`：`LOCAL_BACKUP_MAINTENANCE_LEASE`，409。
- `SnapshotBarrier.validate_exclusive_lease(lease)`：只读检查实际 `SnapshotLease` 类型、`lease.barrier is self`、owner/token 与当前 intent/exclusive 一致、`exclusive=True`、未 released、DB/file counts `(0,0)`；不修改、不释放。
- `SnapshotService.capture_maintenance_protection(*, lease, output, cancel, progress=None) -> SnapshotResult`：只接受同数据根、当前有效 exclusive lease；不调用 `begin_intent`／`acquire_exclusive`／`lease.release`／`freeze`／`unfreeze`。
- 入口只读核对执行器已冻结、`is_snapshot_idle()`、数据库 `active_task_snapshot().live == 0`；遇到未冻结／有活动／pending／queued 时受控拒绝，不在 exclusive 内等待 AI 写库。
- 输出必须是绝对 `.kgmbackup`；父目录由 `backup_fs.PrivateDirectoryGuard` 以实际目录句柄验证当前用户+SYSTEM 受限 DACL，并检查位于数据根、凭据根、B1 工作根之外。普通 `create()` 的教师选目标不增加该 DACL 要求。
- 保护包固定 Format 1 明文；复用从 `create()` 提取的同一 `_capture_container` 引擎（DB／资源／manifest／STORED ZIP／container／verify／no-replace 发布），不复制第二套引擎。
- 捕获入口和发布前再次核对 lease；失败／取消只清理自身 staging，不释放调用者 lease、不清除其他 freeze owner、不改变已有目标字节；发布前取消无最终文件，发布后完成终态单调。
- 调用者顺序按规格 §10.1：页面保存 → intent → 已接受 DB／文件／AI 工作排空 → live／queued AI 终结 → 本轮唯一 owner（如 `restore:<operation_id>`）freeze 并确认 idle → exclusive → 同一 lease 捕获保护包并切换。本接口不实现调用者、恢复切换或 UI。
- P06 已确认首次启动和设置页都提供恢复入口；本轮只提供共享捕获接口，不实现 P06 宿主／页面。

### 11.2 自测证据（实现者自测，不是 Codex 独立通过）

| 命令／探针 | 结果 | 日志 |
| --- | --- | --- |
| `pytest tests/local/test_backup_snapshot.py -q -k capture_maintenance` | 8 passed，17 warnings，exit 0 | `opencode-b2s1-tests-r08.log` |
| `pytest tests/local/test_backup_snapshot.py -q` | 39 passed，33 warnings，exit 0 | `opencode-b2s1-tests-r09.log` |
| 加辅助夹具只读运行 | 43 passed，33 warnings，exit 0 | `opencode-b2s1-tests-r10.log` |
| Codex `codex_b1_probes_r02.py` 原 11 反例复跑 | 11 passed / 0 failed，exit 0 | `opencode-b2s1-probes11-r01.log` |
| Codex `codex_b1_r02_extra_probes.py` 4 项复跑 | 4 passed / 0 failed，exit 0 | `opencode-b2s1-extra-r01.log` |
| Codex `codex_b1_r03_boundaries.py` 2 项复跑 | 2 passed / 0 failed，exit 0 | `opencode-b2s1-boundaries-r01.log` |
| `py_compile` B2-S1 改动文件 | RC 0 | 终端 |

新增 capture 测试覆盖：同 lease 捕获后 writer／file／新 intent 仍拒且 lease/freeze owner 不变；错误根、失效、未 exclusive、错误类型 lease 拒绝；执行器 idle 但 DB queued 拒绝且不等待；非私有／数据根内／相对输出拒绝；缺图、坏图、已有目标、取消、进度异常均不释放 caller／其他 owner；成功包可由普通 `verify(path,password=None)` 验证。

首失败：新接口测试未出现产品失败；一次测试文件追加被 shell 截断，`py_compile` 发现后修复，未作为产品通过。既有 B1 r01–r04 首失败保留在 §1–§9 与附录。

### 11.3 未验边界

- 恢复核心调用方、成组切换、保护副本再恢复、P06 首次／设置页 UI、B3 源码窗口、教师体验、冻结包、Win10／跨机器／用户、真实断电／磁盘不足／权限故障及技术上限填满均未验。
- 未实现或宣称 B2 恢复成功；未调用真实 AI、未连接 WebDAV、未发行、未 Git 本轮修改。
- 真实非空业务根、DPAPI 跨用户／换机、真实供应商请求仍禁止或未验；原有保护源和 B1 提交保持不变。

### 11.4 Codex B2-S1 独立结论（2026-10-31）

以下为 Codex 独立结果，不是 §11.2 的实现者自测；详见[独立核查 §10](desktop-backup-restore-review.md#10-b2-s1-独立结论共享维护捕获接口通过)。

- `pytest tests/local/test_backup_snapshot.py -q --durations=3`：**39 passed，89.60 秒，exit 0**，含真实 600 图与密码模式回归。
- 既有 11＋4＋2 反例：**17 项全部通过**；冷 schema／detach 清理替换被阻止，对照字节保持。
- 新增六组合成 S1 审计：**6/6 通过**；41 业务表全部字段与 12 资源字节一致，保护包 1,408,493 bytes；成功后 DB／file／新 intent 仍受阻，调用者 lease 与其他 freeze owner 保持；错误根／类型／token、发布前失效、排队 AI、非私有目标、同名目标、取消与回调异常受控拒绝。
- 首次空档案：无教师资料的 head 库可捕获并正常校验完整保护包，无需临时档案（仅后端接缝实证）。
- 非空 0005 完整包：26 张原业务表字段／行、日计划版本 1–4 及回执保持，隔离升级至 0006，原包／现用合成库不改，网络连接 0。
- 测试前后 **430 路径集合和 hash 不变，5 个原保护源及 2 个旧包保持**。

**结论：B2-S1 共享接口在本节源码／合成范围独立通过，可交恢复核心调用。** 固定接口与调用顺序为 `capture_maintenance_protection(*, lease, output, cancel, progress=None)`／`validate_exclusive_lease(lease)`；B2 成组切换、启动接续、旧身份退役、宿主与首次／设置页入口、B3 窗口与教师体验仍未通过，不发行。宿主整合合同已私有成稿，仅设计，未实现／未测试。

## 12. B2 宿主／API／现有前端整合（2026-10-31，实现者自测，未独立通过）

源码身份：B1 已提交 `7d2759b76a16528e3e42d720a9203be40b6383a1`（tree `b89cda2846a78f64859760bbb30934a24fd8e86b`，parent `e836726f008676fc603a7b4cb058e5d96cafe60b`）；B2-S1、恢复核心、独立 UI 与本轮宿主整合修改均未提交。恢复核心仍由辅助会话实施／自测、未独立通过；独立 UI r02 已通过（review §13），三份 UI 文件保持冻结只读。本轮不 Git、不启动完整 B3／全 local／全前端／整包。

### 12.1 文件责任与实际改动

本轮只写：

- `desktop/maintenance_host.py`（新增）：宿主维护操作注册表、`requestId` 幂等／冲突指纹、opaque target／selection、备份／预览／确认／取消／查询、退休、错误 DTO、保护位置文案、`REOPEN_FAILED` 终态、终态单调与切换后取消 `too_late`。
- `desktop/maintenance_lifecycle.py`（新增）：`LifecycleBundle`／`LifecycleManager`（最新 bundle 关闭、`stop_and_confirm` 确认线程死亡后才释放 runtime）、`ReopenSequencer`（旧 host 先退休→新 app／token／executor／service→安装新 bundle→新 Window／host→等待新页业务就绪→销毁旧窗）、`HostMaintenanceHooks`（`wait_host_idle`／`stop_transport`，不等待面板自身 busy）。
- `desktop/d1_host_api.py`：维护端点、opaque 选择、`page_business_ready`／`document_generation`、`_bind_window`／`_bind_maintenance`／`_retire`、退休后 bootstrap／副作用拒绝但旧操作只读查询保留、原生对话框返回后退休检查、关闭路径维护 busy 探针、`BRIDGE_ALLOWED_ENDPOINTS` 只增维护端点。
- `desktop/d0_main.py`：`ServiceRun.stop_and_confirm(timeout) -> bool`，以 join 后 `is_alive` 为准；超时不是成功。
- `desktop/d1_main.py`：初始 lifecycle bundle、窗口显式绑定、维护宿主接线、重开序列、最终只关闭最新 bundle；旧 `load_url`／`webview.windows[0]` 猜测不再作为生产路径。
- `frontend/src/d1/bridge.ts`：`createBackupRestoreHost()` snake_case↔camelCase 适配、错误码抛出、`page_business_ready` 与 bootstrap 新字段类型。
- `frontend/src/d1/App.vue`：面板接入、独立 `maintenanceLocked`、业务加载后 `page_business_ready`；`SetupView.vue` 只加恢复入口，`SettingsView.vue` 加备份／恢复入口。
- `backend/tests/local/test_local_app_retirement.py`（新增）：同一合成 runtime 两个真实 loopback app，旧 token 对新 app 401、新 token 对旧 app 401、旧服务停止不影响新服务。
- `desktop/tests/test_maintenance_host.py`、`test_maintenance_lifecycle.py`、`test_d1_maintenance_api.py`（新增）；`frontend/src/d1/d1.backup-integration.test.mjs`（新增）；`frontend/package.json` 的 `test:d1` 只登记新 Node 测试；`.gitignore` 新恢复私有目录规则。

未修改：`restore_*.py`、`test_restore_*.py`、`restore_worker.py`、`runtime.py`、`config_tokens.py`、`BackupRestorePanel.vue`、`backupMaintenance.ts`、`d1.backup-ui.test.mjs`、S1／fixture 支持文件、`backend/app/local/app.py`（旧 token 401 由每 app 新 token／session_scope 天然满足，无需新增 API）。未改依赖／锁、构建、迁移、发行或真实数据。

### 12.2 关键行为

- 每 Window 绑定独立 `D1HostApi`／`CloseCoordinator`／document generation；`_default_window()` 返回 `None`，不再 fallback `webview.windows[0]`。新 window 创建后立即 `_bind_window`。
- 旧 host 在新 engine 开放前 `_retire()`：`get_bootstrap` 只返回 `retired: true` 且无 launch token；`page_ready`／维护 start／dialog 拒绝；旧维护操作 `query_maintenance` 仍可读进度；退休后 `cancel_maintenance` 返回 unknown，不新发副作用。
- `MaintenanceHost` 按 `requestId` 指纹幂等；同 request 不同 payload 返回 `REQUEST_CONFLICT`；confirm 只接受本 op 的 operation/generation/preview token，外来 request/op 返回 `PREVIEW_STALE`；confirm 的 requestId 成为 op 的公开 requestId，丢回包可按同一 requestId 查询，不重发安装。首确认把 phase 从 `preview` 置为 `waiting` 后才启动安装；任何新 requestId 的重复确认在安装中或完成后都只得到 `PREVIEW_STALE`，不会第二次调用 core install（fake core 测试固定 `install_calls == 1`）。
- start／verify／confirm 在创建副作用前被拒绝（如 `PASSWORD_REQUIRED`、`PREVIEW_STALE`、`RECOVERY_REQUIRED`）时，宿主按同一 `requestId` 登记只读终态错误；页面丢回包后查询同一 requestId 可得到该错误，不会重发第二个副作用，也不会覆盖原预览。
- core 返回 `recovery_required`、`failed_keep_old` 且 `reopen_required=true`、`REOPEN_FAILED` 或 install 启动后未知异常时，宿主设置内部 `_recovery_required`：旧 op 仍可只读查询，但新的备份／校验／确认返回 `RECOVERY_REQUIRED`，直到重启由 core journal 处理；宿主不自行 terminalize、不改写 active journal、不自动 rollback。
- 备份／预览／安装均在宿主后台线程；进度回调只更新安全 stage／计数，不含路径／SQL／正文／密码。保护位置固定文案：“恢复前保护副本：<显示位置>。自动保留，不会自动删除。”；重开失败固定“资料已恢复，重新打开失败，请重启应用”，`committed=true`，不自动回滚。
- `failed_keep_old` 若 core 报告 `reopen_required=true`，宿主返回 `RESTORE_RESTART_REQUIRED`／“恢复未完成，请重启应用核对当前档案”并 `committed=true`，不声称“当前档案未更改”；未进入 live 变更时才用 `RESTORE_FAILED`／“当前档案未更改”。
- `wait_host_idle` 只等原生保存、页面写屏障、更新检查／下载；不含面板 `maintenanceBusy`。关闭路径另含维护 active 探针，恢复／备份运行中拒绝销毁窗口。
- 打开维护面板前复用 `currentBlockingDraft()`：设置草稿、观察提交或编辑器阻塞草稿未完成时拒绝打开并提示先完成／取消；取消面板保持首次设置表单，不创建临时 profile。
- `ServiceRun.stop_and_confirm` 未确认线程死亡时，`LifecycleManager.dispose_bundle` 不释放 runtime lock；主流程最终只 `close_latest` 最新 bundle，不关闭旧 server 后释放新 runtime。
- `stop_transport` 确认旧服务线程死亡后立即设置 native-IO switch guard；此后新 Word／观察导出入口与对话框返回都不再写入。原生对话框返回后再次检查退休／switch guard；退休后不提交新的 Word／观察导出写入。
- 新 app 使用新 token／新 port／新 `session_scope`／新 executor；新 host 的 `document_generation` 递增；新页 `get_bootstrap` 清空业务就绪事件，`page_ready` 不再被当作业务已加载；只有 `reloadContext` 成功后的 `page_business_ready` 才允许销毁旧窗。

### 12.3 自测证据（实现者自测，不是 Codex 独立通过）

命令均使用既有 `desktop/.venv-d1`，未安装依赖；日志为私有证据根下相对文件名。

| 命令／探针 | 结果 | 日志 |
| --- | --- | --- |
| `py_compile` `maintenance_host.py`／`maintenance_lifecycle.py`／`d1_host_api.py`／`d1_main.py`／`d0_main.py` | RC 0 | 终端 |
| `pytest desktop/tests/test_maintenance_host.py test_maintenance_lifecycle.py test_d1_maintenance_api.py -q` | 46 passed，exit 0 | `opencode-b2host-unit-r11.log` |
| 既有 host 回归 `test_d1_host_save`／`test_d1_close`／`test_d2_close_barrier`／`test_d1_observation_export_host`／`test_update_u1` ＋本轮三项 | 157 passed，exit 0 | `opencode-b2host-regression-r11.log` |
| `pytest tests/local/test_local_app_retirement.py -q`（backend） | 2 passed，exit 0 | `opencode-b2host-backend-r02.log` |
| `npm run test:d1`（含新 `d1.backup-integration.test.mjs` 8 组） | exit 0；既有 6 个 Node 测试全部通过 | `opencode-b2host-frontend-r04.log` |
| `npx vue-tsc --noEmit` | RC 0 | 终端 |
| 只读复跑 UI 责任会话 `node src/d1/d1.backup-ui.test.mjs` | 20 passed，exit 0 | `opencode-b2host-ui-readonly-r01.log` |
| `git check-ignore --no-index` 8 个正例／8 个反例；`-c core.ignorecase=false` 大写样例 | 8 命中／8 未命中；5 个大写正例命中、4 个公开对照未命中 | `opencode-b2host-gitignore-r01.log` |

新增测试覆盖：requestId 幂等／冲突、空密码不降级、明文需显式确认、预览确认幂等、外来 request/op 拒绝、错误密码回 password、取消终态单调、预览取消使确认失效、切换后取消 `too_late`、退休后旧查询保留／新 start 拒绝、保护与重开文案、`reopen_required` 诚实提示、关闭路径维护探针、每 host 精确 window 绑定、无 `webview.windows[0]` 猜测、opaque 选择与加密提示、`page_business_ready` 票根绑定、原生对话框返回后退休不写入、`stop_and_confirm` 活线程返回 False、未确认停止／执行器不释放 runtime、重开序列顺序与失败保留旧窗、`wait_host_idle` 不自等、旧 token 401。

### 12.4 首失败与当前限制

首失败（均已保留，未修改冻结文件）：

- `py_compile desktop/d1_host_api.py`：一次脚本写入含实际 NUL 字节，`SyntaxError: source code string cannot contain null bytes`；改为 `bytes([92]) + b"0"` 后通过，未进入产品逻辑。
- 早期 Node 适配测试在无 host 时 `getStartupMaintenanceState`／`queryMaintenance`／`cancelMaintenance` 直接抛 `HOST_UNAVAILABLE`；改为缺失 host 时分别返回 ready／unavailable／unknown，避免把“宿主不存在”伪造成维护成功。
- `test_maintenance_host.py` 最初把退休后仍在运行的旧备份预期为 cancelled；实际退休不取消已接受操作，改为预期 completed，并在实现中保留只读查询。
- 首次新增 `save_docx` 退休回归放在既有 `test_d1_host_save.py`，超出本轮新测试文件责任；已撤回并把等价测试放入 `test_d1_maintenance_api.py`。
- `test_d1_host_save.py::TestBridgeSurface` 首跑失败：新增维护端点未在 `BRIDGE_ALLOWED_ENDPOINTS`；补齐后通过，且 `_bind_window`／`_retire` 等宿主内部方法改为下划线，不暴露给页面。
- 复查 review §14 B2-R02 时发现：start／verify／confirm 在创建副作用前被拒绝（如 `PREVIEW_STALE`／`RECOVERY_REQUIRED`）若页面丢回包，panel 按 requestId 查询没有记录会一直等待；新增只读终态拒绝记录，同 requestId 可查询且不重发安装，原预览不被覆盖。

当前限制／待 Codex 协调：

- 恢复核心仍未独立通过；review §14 的 B2-R01–R03 由核心会话 r02 回修。本轮只在 fake core 上验证宿主合同，未跑真实恢复包、真实 engine 关闭／成组切换／journal／reopen。
- 宿主依赖 core `InstallResult.state` 的 `installed_retired`／`canceled`／`failed_keep_old`／`recovery_required` 与 `reopen_required` 字段；若 r02 改这些接口，需同步核定。B2-R01 的嵌套凭据根拒绝属 core 路径校验，宿主不重复实现；B2-R03 的实际组件身份／回滚判定也由 core 负责，宿主只拒绝在未知状态下继续新维护操作。
- 独立 UI r02 已通过，但真实 DOM、真实入口、宿主窗口与新进程仍未整合验证；完整 B3 未开始。
- `failed_keep_old` 且 `reopen_required=true` 的新错误码／文案是本轮宿主诚实性裁决，规格尚未单列；请 Codex 核定是否保留，不把它当作已验收产品行为。
- （历史，已在 §12.6 修复）恢复后新页曾未展示“最近一次保护副本位置”的完成 DTO；旧窗在 `reopening` 期间显示保护位置，销毁后新页不显示。
- 恢复成功后新 host 复用旧 `UpdateManager` 但 `install_coordinator=None`：源码只 check 更新，不新增下载／安装；冻结包安装计划在恢复后的处置未验，旧 coordinator 未由 `close_latest` 关闭，B3／冻结范围需补。
- `ReopenSequencer` 的新窗口创建／旧窗口销毁只由 fake window 测试；真实 pywebview 6.2.1 双窗口、`create_window` 后台线程、旧排队 bridge 调用、旧 close ack／native 回包未验。
- `.gitignore` 规则按 core 实际命名 `*.restore-work/`／`*.restore-guard/`、`.restore-journal.json`、`..restore-journal.json.tmp-*`、`.restore-receipts/`；8 正例（含大小写／嵌套）命中，README／LICENSE／`package-lock.json`／模板／规格未命中。未提交，未做真实仓库暂存验证。
- 未调用真实 AI／WebDAV、未构建／执行冻结 EXE、未使用真实业务数据、未发行、未 Git。

### 12.5 宿主 r02：B2-H-R01–R03 与重开次序（2026-10-31，实现者自测，未独立通过）

Codex review §15 的私有反例在回修前为 **0/3**；本轮只改宿主接缝，不改核心、独立面板或 Command Code 测试。回修后只读复跑 `codex_b2_host_probes.py`：**3/3 passed，exit 0**；日志 `opencode-b2host-r05-codex_b2_host_probes.log`。

- **B2-H-R01 预览取消交 core 生命周期**：`MaintenanceHost.cancel` 对 restore 操作调用 `restore_core.cancel(operation_id)`，只有 core 返回 `state=canceled, accepted=true` 才把宿主 op 置 `cancelled` 并清空 preview／preview_obj。预览在取消后才返回时，宿主再次调用 core.cancel 释放 detached verify staging；`_cancelling` 阻止晚 confirm。`requested`／`unknown`／异常不假定取消成功，页面继续查询真实终态。不删除保护包／旧组。
- **B2-H-R02 发布成功事实优先**：`_run_backup` 中 `create()` 正常返回即置 `completed`，即使取消 Event 已置真；取消请求对 backup 返回 `unknown` 并等待实际终态。只有 core 明确 `LOCAL_BACKUP_CANCELLED`／`SnapshotCancelled` 才置 `cancelled`；宿主不删除已发布文件。
- **B2-H-R03 只认 installed_retired**：install 返回 `installed_retired` 才进入 `reopening`／`reopen()`；`canceled`／`failed_keep_old`／`recovery_required` 按状态处理；未知、None、malformed 或未来状态返回 `RESTORE_STATE_UNKNOWN`／“恢复状态无法确认，请重启应用核查”，设置 `_recovery_required`，**不调用 reopen**。
- **重开次序**：`MaintenanceHost` 新增 `before_reopen` 回调；`d1_main` 传入 `bundle.host_api._retire()`。顺序为：install 成功 → 旧 host 退休（`get_bootstrap`／新副作用／native IO／close 新请求封死，旧 op 只读 query 保留）→ `core.reopen()` 打开新 engine → `ReopenSequencer` 建新 app／token／executor／service／Window／host → 新页业务就绪 → 销毁旧窗。Sequencer 的退休保留为幂等安全网；`before_reopen` 失败则不调用 core.reopen，报 `RESTORE_RESTART_REQUIRED`。
- **停止 transport 后的回滚诚实性**：`HostMaintenanceHooks.stop_transport` 确认旧服务线程死亡后记录 `_transport_stopped` 并设置 switch guard。若 core 随后返回 `canceled` 或 `failed_keep_old`，旧 page 的 HTTP server 已死，宿主不再报告“已取消／当前档案未更改可继续”，而是 `RESTORE_RESTART_REQUIRED`／“恢复未完成，请重启应用核对当前档案”并设置 `_recovery_required`；只有 transport 未停止时才保留 cancelled／未更改结论。宿主不自动 rollback，也不假装旧 server 仍可用。
- **本地工具缓存**：只新增 `/.commandcode/taste/` 精准忽略规则；`git check-ignore` 命中 `.commandcode/taste/taste.md`，`.commandcode/config.json` 仍可跟踪。未读取缓存内容，未提交工具状态。

自测证据（实现者自测，不是 Codex 独立通过）：

| 命令／探针 | 结果 | 日志 |
| --- | --- | --- |
| 三项宿主单测 | 62 passed，exit 0 | `opencode-b2host-r05-unit-r01.log` |
| 既有 host 回归 + 本轮三项 | 173 passed，exit 0 | `opencode-b2host-r05-regression-r01.log` |
| Codex `codex_b2_host_probes.py`（只读运行，未修改脚本） | 3/3 passed，exit 0 | `opencode-b2host-r05-codex_b2_host_probes.log` |
| `py_compile` 宿主改动 | RC 0 | 终端 |
| `npx vue-tsc --noEmit` | RC 0 | 终端 |
| `npm run test:d1`（9 组适配器 + 既有 Node + UI 20 项） | exit 0 | `opencode-b2host-r03-frontend-final.log` |
| `.commandcode/taste` 忽略 | 命中；其他 `.commandcode` 路径未忽略 | 终端 |

首失败：Codex 私有反例回修前 0/3；本轮首轮修复后先解决预览取消未调 core.cancel、backup 成功被 Event 改 cancelled、未知 install state 仍 reopen 三项，再补 before_reopen 次序与 transport 停止后的诚实终态。测试中也修正了 FakeCore 缺少 `cancel`、FakeBackup 不响应取消导致的本地预期偏差；未改独立探针。

仍未验：真实 core r02 接口若改变 `CancelResult`／`InstallResult.state`／`reopen_required`，宿主需同步；真实 WebView2 双窗口、旧排队 bridge／close ack／native 回包、真实恢复包与 B3 均未验。核心 r02 与互补故障 16 项矩阵已按当前阶段记录（review §14–§17）独立通过（核心及测试 62 hash 一致）；不因此把 B2／B3 整体写成通过。未 Git、未发行、未调用真实 AI／WebDAV。

最终宿主源码 SHA-256（本轮停写候选）：

- `desktop/maintenance_host.py`：`52ab912e1d30891c6d2d4e08cfb76743da8344f8d40be672da05a6da91e27b5e`
- `desktop/maintenance_lifecycle.py`：`87e415a47d6c1abad9144dd4ffe324e891ef68105b7b341e921e81cd7390dad5`
- `desktop/d1_host_api.py`：`f3d2921f87fb2900281cacce8293aa203eb1c838edee4bc522560d2781cab580`
- `desktop/d1_main.py`：`c5fd5008cbe0d5ae108352652cbe72dd20c5b4944b0724fd4133ffd9cd91be77`

### 12.6 最终整合备注：UI 测试登记、新页保护位置通知、密码重试清理（2026-10-31）

本轮只补现有已确认显示／清理要求，不新增产品流程，不改三份冻结 UI 文件、核心或 Command Code 测试。

- **`test:d1` 登记独立 UI 测试**：`frontend/package.json` 的 `test:d1` 末尾加入 `node src/d1/d1.backup-ui.test.mjs`；依赖／锁未改。`npm run test:d1` 现同时执行既有 Node、9 组宿主适配器和该 UI 的 20 项测试；日志 `opencode-b2host-r03-frontend-final.log`，exit 0。
- **新页保护位置通知**：`MaintenanceHost.completion_notice()` 返回成功恢复时生成的安全文本；`d1_main._run_reopen_sequence` 把它传给新 `D1HostApi(maintenance_notice=...)`；新 host `get_bootstrap` 增加 `maintenance_notice`。新页 `App.vue` 在 `reloadContext()` 成功后、`page_business_ready` 之前显示 `data-d1="restore-notice"` 的持久提示，文案即“恢复前保护副本：<显示位置>。自动保留，不会自动删除。”。它只是可复制显示文本，不是路径能力、命令或凭据；不含密码。旧窗仍在新页业务就绪后才销毁。
- **密码重试遗留清理**：错误密码的旧 verify 保持 `phase=password` 供页面重试和 requestId 只读回查，但其 core 生命周期在错误密码返回时调用 `restore_core.cancel(operation_id)` 退休，并标记 `_core_retired`；新的 verify 启动前也会清理更早的 `password` 记录。`has_active_operation` 只跳过已由 core 确认退休的 password 记录，不全局忽略 password／preview；preview／install 仍参与关闭安全。对应私有探针 `codex_b2_host_password_retry_probe.py` 只读复跑 **passed，exit 0**，日志 `opencode-b2host-r05-codex_b2_host_password_retry_probe.log`；自有回归固定旧 requestId 可查、新 preview 取消后 `has_active_operation == False`。
- **范围**：核心 r02 与互补故障 16 项矩阵已独立通过（核心及测试 62 hash 一致）；本轮仍不启动真实 B3、真实 WebView2 双窗口或 Git，等待 Codex 独立宿主审计。

最终源码 SHA-256（宿主／前端整合停写候选）：

- `desktop/maintenance_host.py`：`52ab912e1d30891c6d2d4e08cfb76743da8344f8d40be672da05a6da91e27b5e`
- `desktop/maintenance_lifecycle.py`：`87e415a47d6c1abad9144dd4ffe324e891ef68105b7b341e921e81cd7390dad5`
- `desktop/d1_host_api.py`：`f3d2921f87fb2900281cacce8293aa203eb1c838edee4bc522560d2781cab580`
- `desktop/d1_main.py`：`c5fd5008cbe0d5ae108352652cbe72dd20c5b4944b0724fd4133ffd9cd91be77`
- `frontend/src/d1/App.vue`：`424b50d178fe2f62fb4ce2745922999b84db132221087c9af8908efdf3c206a6`
- `frontend/src/d1/bridge.ts`：`1d088ebfe4d097290dad0841b6200076a2885d8786756a08431ff0273af5c3c9`
- `frontend/package.json`：`b93f82e650610acfc0d22133ccda5b12b07430cf34e06c04497085c8c07f3312`

### 12.7 B2-H-R05：嵌套校验取消与进度文案（2026-10-31）

Codex 私有反例 `codex_b2_host_protection_cancel_probe.py` 回修前失败：core 在 `hooks.stop_transport` 之前转发保护副本的 `stage=verify`，宿主把任意 verify 当成 switching，取消被错误拒绝为 `too_late`，随后继续 reopen。回修后只读复跑 **passed，exit 0**，日志 `opencode-b2host-r05-codex_b2_host_protection_cancel_probe.log`。

- **不可逆边界只来自确认的 transport／switch**：`_progress` 不再把通用 `verify` 映射为 switching；`protection` 只进入 protection。只有 `_MaintenanceHooks.stop_transport` 确认旧服务线程死亡后调用 `_mark_switching`，以及 `_transport_stopped` 为真时的 `switch`／`installed` 进度，才进入 switching。保护副本校验／嵌套 verify 在 live 未动、旧服务仍运行时保持可取消；真实切换后的 `too_late` 保护保留。
- **进度文案受控映射**：`_STAGE_TEXT`／`_MESSAGE_TEXT` 把 core 的 `barrier`／`db`／`resources`／`verify`／`commit`／`prepare`／`install`／`protection`／`switch`／`installed` 及 `copy_database`／`copy_resources` 等键映射为教师可见中文；未知英文键回退“维护操作进行中”／“正在处理”，未知中文原样保留。原始 stage／message_key 只保存在宿主 op 的 `_progress_stage`／`_progress_message_key` 用于状态判断，不进入页面 DTO；计数与 indeterminate 保留。
- **回归**：新增 `test_protection_verify_progress_stays_cancellable`、`test_progress_keys_are_mapped_to_teacher_text`、`test_unknown_progress_keys_get_neutral_chinese`；私有 protection probe 只读运行通过。未改 core／UI3。
- **停写范围**：仍不启动真实 B3、真实 WebView2 双窗口或 Git；等待 Codex 独立宿主审计。


### 12.8 B2-H-R06：新页通知不得替代业务页面（2026-10-31）

Codex 以实际 Vue compiler-dom 对 App.vue template AST 复现：通知 `el-alert` 被插在 connecting `v-if` 与 error `v-else-if` 之间，成为整条页面分支的 if 头；通知存在时只渲染 alert，工作台／首次设置／编辑器／设置均被 else 排除。私有 `codex_b2_notice_template_probe.mjs` 回修前 exit 1。

- 将通知移到 `.d1-page` 内、connecting 分支之前，作为独立兄弟节点；原有 connecting → error → uninitialized → normal 的连续互斥链保持不变。通知与实际页面同时可见，不覆盖工作台；连接／错误分支不显示陈旧通知。
- 新页仍在 `reloadContext()` 成功后设置 notice，再 `page_business_ready`；旧窗销毁次序与原生对象绑定不变。
- 回归不再只搜字符串：`d1.backup-integration.test.mjs` 用实际 `@vue/compiler-sfc` 编译 App.vue template、TypeScript 转译后执行 render，检查 VNode 树：通知存在的正常工作台同时含 `el-alert`＋`WorkbenchView`；无通知只含工作台；首次设置含 `el-alert`＋`SetupView`；connecting／error 各自分支且不含 alert／工作台。私有 notice probe 回修后 **passed**，日志 `opencode-b2host-r05-notice-template.log`；`npm run test:d1` 9 组适配器＋UI 20 项 exit 0。

### 12.9 B2-H-R07/R08：失败新 bundle 所有权与退休错误窗关闭（2026-10-31）

私有 `codex_b2_host_lifecycle_failure_probes.py` 回修前 **0/2**；回修后只读复跑 **2/2 passed**，日志 `opencode-b2host-r05-codex_b2_host_lifecycle_failure_probes.log`。

- **R07 新 bundle 生命周期所有权**：`ReopenSequencer` 现在在 `start_and_wait()` **之前**把新 bundle 安装为最新 bundle。新服务启动失败（或 stop_and_confirm 未确认）时，`close_latest` 仍以该新 bundle 为最新 owner，停止未确认则返回 False、保留共享 runtime lock；不再回退到旧 generation 后误 dispose。旧窗保留，错误按终态报告。
- **R08 退休终态错误窗安全退出**：`_install_close_handlers` 的 `on_closing` 在旧 host 已退休且 `_maintenance_busy_probe()` 为假时允许原生关闭；这覆盖 `REOPEN_FAILED` 后“请重启应用”的旧窗。切换／重开 active 时 probe 为真，仍走 CloseCoordinator 拒绝；回调绑定旧 host/window，不会关闭新窗。关闭后由进程级 `close_latest` 处理最新 bundle，不释放未确认服务的 runtime。
- 新增回归：失败 start＋未确认 stop 保持新 bundle／runtime lock；退休终态窗原生关闭允许；退休但维护 active 仍拒绝。未改 core／UI3／Command Code。


### 12.10 B2-H-R09：recovery_required／engine 关闭窗口可安全退出（2026-10-31）

核心返回 `recovery_required` 且已确认 `stop_transport`、旧 executor dispose、`close_engine_keep_lock`，但无法核定完整回滚时，core 保持 engine 关闭、active journal／屏障；宿主 op 已 terminal、`_recovery_required=True`，但尚未走 `before_reopen`，`D1HostApi._retired=False`、`_native_io_blocked=True`。旧 close handler 的 task_snapshot 会读已 dispose executor 和已关闭 engine 的 `runtime.session()`，异常被当成 AI in-flight，即使 `stop_and_exit` 也无法关闭。

- `D1HostApi._recovery_required_probe()` 只读查询维护宿主的 `recovery_required()`／`_recovery_required`；`d1_main.on_closing` 只在“旧 host 已退休 **或**（core recovery_required **且** `_native_io_blocked` 已由确认的 `stop_transport` 设置）”且 `_maintenance_busy_probe()` 为假时允许原生关闭。仅 recovery_required 旗标不够：engine 仍 open、transport 未停、真实 AI `attempt_in_flight` 时继续走普通关闭选择／拒绝。
- 仍保留普通 AI in-flight／dirty close：没有 recovery_required、没有退休的窗口继续走 CloseCoordinator；active switch／reopen 时 `_maintenance_busy_probe()` 为真，仍拒绝关闭。旧回调只绑定自己的 window；process `close_latest` 继续确认最新 server／executor，未确认时保留 runtime lock。不释放 core lease、不改 journal、不杀进程、不暗回滚。
- 新增回归：`recovery_required_closed_engine_window_can_close_natively`、`recovery_required_with_active_maintenance_still_refuses_close`、`recovery_required_open_engine_with_real_inflight_keeps_close_guard`、`closed_engine_without_recovery_required_keeps_normal_ai_close_guard`。私有四组 lifecycle probe 只读复跑 **4/4 passed**，日志 `opencode-b2host-r05-codex_b2_host_lifecycle_failure_probes.log`。


## 13. B3 源码窗口验证入口与安全守卫（2026-10-31，停写待 Codex preflight）

本轮只新增源码验证入口／守卫／测试和 d1_main 最小派发；核心、shared backup、UI3、Command Code、backend 均未改。**没有新的 B3 GUI 通过结论；未 Git、未发行、未启动真实 B3。**

### 13.1 已实现入口

- `desktop/maintenance_source_verify.py`：专用 `--selftest --phase b3-source-window --data <合成> --credential-root <合成> --b3-config <JSON>`。配置显式给出 source/target 数据根、凭据根、evidence、旧包输出、目标备份输出、容量计数、前端构建；入口在任何 Runtime／锁／prepare／AI／fixture 前校验 selftest、相位、显式根、root 在系统临时根内、短路径、源／目标独立、包不在目标数据／凭据根内。
- `desktop/maintenance_source_guard.py`：父进程在 Runtime／executor／fixture 之前安装 loopback-only socket guard（`getaddrinfo`／`connect`／`connect_ex`），非 loopback 直接 `B3_NETWORK_BLOCKED` 并写 evidence 日志；同时写临时 `sitecustomize.py` 并通过 PYTHONPATH 交给 spawn worker，子进程同样阻断并记录。该日志是受控守卫证据，不冒称 OS 抓包。
- `d1_main.py`：新增 `--b3-config`、相位选择与最小派发；`_DEDICATED_SYNTHETIC_PHASES` 含 `b3-source-window`，`_validate_synthetic_entry` 要求显式 `--data`／`--credential-root`／`--b3-config`。未把驱动脚本塞回主入口。
- 环境隔离：在 build_runtime 前设置独立 `LOCALAPPDATA`、`APP_DISABLE_DOTENV=1`、清除 `KGM_LOCAL_DATA_DIR`；目标 fixture 在真实 executor 启动前用独立临时 Runtime 种入后释放，避免 queued task 与 executor claim 竞态；window host 的 `_update_manager=None`，页面启动更新检查不访问 GitHub。
- 原生对话框只由 `window.create_file_dialog` 替身返回配置的合成 backup target／source package；真实 Window、D1HostApi、MaintenanceHost、RestoreCore、SnapshotService、ServiceRun、Vue 页面均保留。驱动走真实 DOM 按钮／输入／预览确认，不直接调 core 当 UI 通过。
- 严格证据：源包 verify 后比较数据库全字段（include_runtime_fields=True）与资源清单；目标备份 verify 后与 target pre 数据库／资源清单比较；恢复后同时记录 full 与 business fingerprint、资源 fingerprint 及差异表；不再以 `bool(verified)` 代替完整比较。未知/已存在包拒绝覆盖，不 unlink；不清理未知目录。
- 失败持久化：driver 异常立即写 evidence JSON；watchdog 写 `watchdog_terminated` 后退出，不把超时当成功；必需 checks 缺失或非 true 均失败。cleanup 只在 `close_latest` 确认成功时 dispose runtime；未知 service/worker stop 保留运行锁，不 fallback dispose。

### 13.2 已发生的未隔离首跑（必须保留的事实）

- 在守卫实现前，本会话曾启动过一次未隔离 source-window smoke。Codex 已按实际 worker 身份／句柄／镜像／创建时间停止 own worker 12812，父 venv 26112 自然退出，receipt `b3-own-unisolated-process-stop.json`。
- 该次现场在 SQLite 检查前被复制为 `b3-unisolated-preserved-8c8251d9`（44 files，含 hash）。只读审计 source／target 各 **4** 条 task／execution／attempt，状态为 fixture 的 `failed`／`outcome_unknown`／`succeeded`，未见额外行；但**没有 guard／计数器，不能声称该次网络请求为 0，也不能声称没有实际 AI 请求**。
- 更早首失败的部分现场曾被 `rm -rf` 删除，已明确记录为证据损失，不能重建为“保留完整首失败”。后续唯一 root 不删除。
- 首跑实际 startup failure 为凭据根预创建导致 DACL 未受限；已改为由 LocalRuntime 创建受限凭据根。随后把 target seed 从 build_runtime 之后移到 executor 之前；把 `bool(verified)` 改为数据库／资源完整比较。
- **本文件不把该次 smoke 计为 B3 通过或 network0 证据。**

### 13.3 当前验证状态

| 命令／检查 | 结果 |
| --- | --- |
| `py_compile` source verify／guard／d1_main／宿主文件 | RC 0 |
| `pytest desktop/tests/test_maintenance_source_entry.py -q` | 9 passed |
| 守卫反例：非 loopback 阻断、loopback 可用、child sitecustomize 写入 | 通过 |
| 入口反例：缺 selftest／相位／显式 data／credential／config 拒绝；重叠／root 外／包已存在拒绝且不删除 | 通过 |
| 真实 B3 GUI 运行 | **未在守卫实现后重跑；等待 Codex preflight** |

最终本轮文件 SHA-256：

- `desktop/maintenance_source_verify.py`：`521c3d00d1837b8a878eac13e81a55c1da2f1b235137dddca84a100cc89c4d70`
- `desktop/maintenance_source_guard.py`：`93675b9a30e6c293b8a24af033097cf89190ac3b138578eadb90c9788f386905`
- `desktop/d1_main.py`：`3e6ad1614951370d2b0a976b9ec17b6c7b4e9aaa9bb6d6bff7142a69fa5324c5`
- `desktop/tests/test_maintenance_source_entry.py`：`cc6092e2ade6b505ae2943d17d02bede0f2a5e9fe484dc6188a3be45b122bf58`

### 13.4 仍需在 preflight 后完成

全部 9 个 B3 源码窗口范围仍未执行／未通过：首次未提交表单与错误包／错口令／取消；真实明文／密码备份与空密码不降级；预览确认／新 app／token／scope／Window／host 与通知；old/new 41 表差异与逐字段／资源字节；恢复后编辑／保存／历史／图片／Word；保护包再恢复；旧 token／旧 host／迟到回包／H-R07/H-R08；>30MiB／600 图容量；AI／更新受控隔离与 cold-start 分类。当前只完成入口、守卫、严格证据骨架和单元守卫；不得写成 B3 或教师体验通过。


### 13.5 B3 preflight r02：五项守卫／严格成功回修（2026-10-31）

Codex 私有 `codex_b3_preflight_probes.py` r01 为 **0/5**；本轮只改 source verify／guard／entry test／d1main 最小接缝，未创建任何 GUI／Runtime／service／executor。回修后只读复跑：**5/5 passed，exit 0**，日志 `opencode-b3-preflight-r03-five-final2.log`；追加两反例回修后 **2/2 passed**，日志 `opencode-b3-preflight-r03-extra-final2.log`；自有 entry／guard 单测 **13 passed**（含真实 spawned Python guard 自检、日志不可读计数、早期 driver 留窗反例）。

- **P01 全字段不能由 business 摘要豁免**：`required` 增加 `database_equal_full`；summary 不再只看 `database_equal_business`。目标备份仍保留完整数据库＋资源清单比较；源包 verify 也先比较数据库与资源清单再接受。small fixture 若全字段不等即失败；后续如出现合法 auth／启动增量，必须做精确行／列对比并仍要求允许增量外全等，不能整表排除。
- **P02 业务 DOM 不能由状态变量冒充**：新页等待实际 `[data-d1="calendar"]` 或 `[data-d1="setup"]` DOM；`new_page_business_visible` 改为 DOM 布尔，`new_page_has_calendar` 进入 required；不再以 `__d1App.view()==workbench` 单独判成功。
- **P03 预览文本不是布尔**：新增 `restore_preview_ready` 布尔，`restore_preview` 仅保存描述文本；required 使用布尔，正常预览不会因字符串被 `is True` 误判失败。
- **P04 审计失效不能报 0**：`NetworkGuard` 在内存中累计 blocked attempt；日志写入失败设置 `audit_ok=False`，`attempts()` 不再因文件不可读返回 0。初始化时预创建空日志并追踪 `_log_initialized`；已知有 attempt／已初始化后文件缺失或读取失败时 `log_attempts()` 返回 `None`（未知），不再一概返回 0。子 sitecustomize 的 `_record` 写日志失败会写 `KGM_B3_GUARD_FAILURE` 标记并抛出 `B3_GUARD_AUDIT_FAILED`，子进程异常退出；`verify_child_guard()` 校验子进程 0 退出、无 failure 标记、ready／blocked 标记及 `B3_NETWORK_BLOCKED`。run 的 required 增加 `child_guard_verified`、`network_guard_audit_ok`、`network_guard_zero`，父/子日志不可读或未知审计状态均失败。
- **P05 早期 driver 错误不能留窗**：driver 异常先写 partial evidence，再尝试销毁自己的旧／新 window；`_destroy_owned_windows` 把 destroy 抛错、closing 拒绝或 window 仍在 `webview.windows` 都视为未确认。只有全部自有窗确认消失才设置 driver 完成信号；失败保持 watchdog 兜底，避免 `finished` 提前退出导致 `webview.start` 永久挂住。未知 service/worker stop 仍不 fallback 释放 Runtime。
- **静态接线**：backup-close 后从设置入口重新 `open-backup-restore` 再点 `backup-restore`；旧窗销毁和新 DOM 实际等待；新窗口绑定自己的 dialog stub，不能走真实对话框卡住。
- **范围**：当前驱动仅 plaintext smoke 骨架，不是全部 9 项；密码、首次未提交表单、坏包、保护包再恢复、新进程、Word、600 图 UI 等仍未完成。未启动实际 GUI，等待 preflight 放行。

最终文件 SHA-256：

- `desktop/maintenance_source_verify.py`：`5bfb694cd30a9c6e558ee05ae9c69a618374f492fcbfaca79d0e432973a4c1ff`
- `desktop/maintenance_source_guard.py`：`e71f870799849076cc598d54b7109d0eec3733f78066d6807e014a97d54acaa3`
- `desktop/d1_main.py`：`3e6ad1614951370d2b0a976b9ec17b6c7b4e9aaa9bb6d6bff7142a69fa5324c5`
- `desktop/tests/test_maintenance_source_entry.py`：`3195f106df04cf3b954badec3acbaa422c1e23e5e0e84f39fd48c59d34c393ff`

Command Code 的 `desktop/tests/test_maintenance_source_guard.py` 未由本会话创建或修改；guard API 保持 `install/uninstall/attempts/install_child_guard/log_path` 稳定，新增 `audit_ok/log_attempts/verify_child_guard` 为附加能力。

### 13.6 B3 r04：小容量校准与已完成源码窗口场景（2026-10-31，实现者自测）

Codex 独立复验 c4 小容量（私有 root `kgm-b3-cdx-r04-7942f5d`）通过；本会话后续实际源码窗口自测如下。所有运行均使用同一已验 guard、executor 前播种、隔离 LOCALAPPDATA／credential／update；未调用真实供应商。每个 root 均保留，未删除或覆盖。

| 场景 | 结果 | 关键证据 |
| --- | --- | --- |
| c4 plaintext 校准（新 unique root `kgm-b3-r04-c4`） | **exit0** | 真实备份 1,408,772 bytes；target backup 全 DB＋12 资源；恢复后 new window generation 2、calendar＋notice 可见、旧窗销毁；full41＋resources 全等；guard0/audit healthy；latest closed；无残留进程 |
| setup 负向（`kgm-b3-r04-setup4`） | **exit0** | setup 表单先填四值；native cancel 静默；bad package 错误；encrypted wrong password 错误后取消；四值逐字保持；profile count 0；无 calendar；无临时 profile |
| post-restore（`kgm-b3-r04-post6`） | **exit0** | 恢复后真实编辑＋手工保存、历史详情、观察照片 naturalWidth>0、Word 导出有效 DOCX（14,077 bytes）；source/target 均通过正常 save 写入不同 body marker；恢复后 full41＋resources 对 source 全等 |
| new process restart（post6 target，新进程 `restart-evidence`） | **exit0** | 全新进程打开同一合成 target，真实 term/plan/editor 可见；body marker `B3 POST RESTORE SAVED BODY 2026-10-31` 保留；latest closed、guard0 |

源码新增 `maintenance_source_setup.py`、`maintenance_source_post.py`、`maintenance_source_restart.py`；`maintenance_source_verify.py` 增加 case/word_dir/out/artifact 校验、normal-save body marker、dialog queue/count、visible/enabled click、失败 DOM/按钮/阶段证据、maintenance cleanup、destroy watchdog。`maintenance_source_setup` 的 setup 负向与 `maintenance_source_post` 的 editor/history/photos/Word 已实际跑通。

当前仍未完成：setup 正向空档案恢复及空保护包再恢复；protection package 再恢复找回旧工作；>30MiB／600 图真实窗口；旧 host/token/preview/HMAC/native late callback 与真实重开失败；显式 AI cold-start claim/SEND/provider 计数。不得把 c4/setup/post/restart 的自测写成 all9 或教师体验通过。

最终源码 SHA-256：

- `desktop/maintenance_source_verify.py`：`2a310b0c4bfee3d50c5de4c56ba7292dad42eac856cfae6be2d46890895497d9`
- `desktop/maintenance_source_setup.py`：`6f4e1acaa5978105d009c6a6423ff605db2cd11e3ae426f9f4dd389bf97817da`
- `desktop/maintenance_source_post.py`：`271e008a9ee1155d8acc97846bb3c268e1e1b0cd5ff2650dc82dcdf9e1ae07a7`
- `desktop/maintenance_source_restart.py`：`fbfb874810f29a51741b2bab250481b13b1473b5124a6c67df1ed129ed7c0bfd`
- `desktop/tests/test_maintenance_source_entry.py`：`780001df6d445229d48228059f0c780dc38277ba5780beb068766c85d798177b`

首失败保留：setup1 ImportError `_js_visible`、setup2 input selector、setup3 password input、post1 plan-list 未选 term、post2 FixtureEvidence `.get`、post3 editor 未就绪、post4 plan-list after return、post5 new host verify save dir、c1 JS 括号／selector collision、c2/c3 panel/draft、c4 前的所有现场均未删除。未 Git、未发行。

### 13.7 B3 r04 追加：历史来源／历史照片与加密备份（2026-10-31，实现者自测）

- **post7**（`kgm-b3-r04-post7`，exit0）：在 post6 的编辑保存／历史详情／当前观察照片／Word 基础上，实际打开观察历史 v1，验证 `[data-d1="obs-history-photos"]` 图片 `naturalWidth>0`，并记录 `[data-d1="history-panel"]` 的“保存记录／从 vN 恢复”来源文案；恢复后 full41＋resources 仍对 source 全等，Word 有效 DOCX。
- **enc1**（`kgm-b3-r04-enc1`，exit0）：真实设置页创建加密完整备份；密码模式空密码时 submit disabled，且无 `backup-close`／`backup-error`（不降级明文）；填入合成密码后真实完成，独立 `SnapshotService.verify(password)` 与 target pre 全 DB 比较通过；密码不进入报告。
- 新增 `maintenance_source_encrypted.py`；`maintenance_source_post.py` 增加历史来源文案与历史照片实际解码检查；`maintenance_source_verify.py` 增加 encrypted-backup case、artifact 输出边界（bad/encrypted/out/word_dir 必须在合成 root，禁止别名输入／配置／包／数据根，已有 out／包拒绝覆盖），以及 dialog queue/count、visible/enabled click、失败 DOM/按钮证据。

仍缺：setup 正向空档案恢复／空保护包再恢复、protection package 再恢复、>30MiB／600 图真实窗口、旧 host/token/preview/HMAC/native late callback 与真实重开失败、显式 AI cold-start claim/SEND/provider 计数。不得写成 all9 或教师体验通过。

最终新增源码 SHA-256：

- `desktop/maintenance_source_verify.py`：`d4d852c7fdb2aaf213cff924ba89da2f58d4b77073070e2a81da38d6f23b83ac`
- `desktop/maintenance_source_setup.py`：`6f4e1acaa5978105d009c6a6423ff605db2cd11e3ae426f9f4dd389bf97817da`
- `desktop/maintenance_source_post.py`：`4ad942fd2a8cfd0e8ee4e87f5b8038e77114a62fa0c2eb9fef0eecaaa966cb36`
- `desktop/maintenance_source_restart.py`：`fbfb874810f29a51741b2bab250481b13b1473b5124a6c67df1ed129ed7c0bfd`
- `desktop/maintenance_source_encrypted.py`：`b1b8d195e544ef76b010558ac95708cb0c0ffd6d7b2a8ac1f0a7d670aa5c98b0`
- `desktop/tests/test_maintenance_source_entry.py`：`780001df6d445229d48228059f0c780dc38277ba5780beb068766c85d798177b`

首失败保留：setup1–4、post1–5、c1–c3、post7 前均未删除；未 Git、未发行。

### 13.8 B3 r05：剩余源码窗口场景与最终源码身份（2026-10-31，实现者自测）

本段只记录实际源码窗口结果及独立回执。应用主树、439 文件闭包、backend/core/restore/guard/frontend/build 未由本段改写；未 Git、未发行、未调用真实 DeepSeek／MiMo、未 WebDAV、未冻结 EXE。以下每个 root 均保留，未覆盖首失败。

通用实际命令（root／config 各自独立；未使用真实供应商）：

```powershell
cd desktop
.venv-d1/Scripts/python.exe d1_main.py --selftest --phase b3-source-window `
  --data <root>/target/data --credential-root <root>/target/cred `
  --b3-config <root>/b3.json --out <root>/evidence/result.json
```

| 场景 | root（节选） | 退出 | 本场景实际范围 |
| --- | --- | --- | --- |
| setup 正向：空档案保护→首次恢复→settings 再恢复空保护→generation3 | `kgm-b3-r04-setup5` | 0 | 9 个新增 bool 全 true；初始 full41/profile0，负向前后 full41＋资源不变，首次恢复 generation2 calendar＋notice，空保护包 verify full41/profile0，第二次 UI 恢复 generation3 setup＋profile0，最终 full41＋资源回到初始；保护包／旧组保留。独立 P06 root `kgm-b3-cdx-setup-r05-b70f33` exit0，22.24s。 |
| capacity 真实 157,647,029-byte 加密包 | `kgm-b3-r04-cap3` | 0 | 真实 UI 恢复；source/target full41 与全部 1812 resources 相等；SQL 604 asset rows／604 actual original files；1208 derivative rows/files；threshold 使用 originals 而非全部图片扩展名；calendar＋notice／新窗／guard0。独立 `kgm-b3-cdx-cap-16aed6` PASS；旧 `628442` body-prefix failure 保留不计通过。 |
| protection package 再恢复（旧工作） | `kgm-b3-r04-prot3` evidence1/2 | 0 | 第一次恢复 post 保护包后，第二次恢复其自动保护包回到 TARGET body；restored body 精确等于 source oracle，保护副本 body 精确等于 pre-restore target；新旧 body 不同；full41＋资源对各自 oracle 全等；新保护包 21 resources、旧工作 12 resources。独立 protection r05 PASS。 |
| late capabilities／旧 token／旧 preview／旧 config HMAC | `kgm-b3-r04-late4` | 0 | 实际切换后旧 host bootstrap retired、page ticket／busy／business-ready／native save／observation save／close／backup／restore／confirm／cancel 均拒绝；旧 token 在新端口 401，新 token GET context 200、config preview POST 200（preview 不是持久保存）；旧 config preview token 用**旧 preview 的 normalized_change＋config_version** 与 fresh UUID 提交，精确 422 `VALIDATION_ERROR`／`预览令牌无效`；新窗口 full41＋资源不变。独立 corrected late58a PASS 19.81s。 |
| encrypted backup 严格校验＋明文未 ack | `kgm-b3-r04-enc4` | 0 | 明文模式未勾选 ack 时 submit disabled、无文件；切回密码模式空密码不降级、无终态；填入合成密码后真实完成；无密码 verify 被拒绝；manifest 路径／bytes／SHA 对 target pre 12 resources 全等；DB 全等。独立 encrypted small PASS 41＋12 resources。 |
| committed 后可控 reopen 失败（host 模式） | `kgm-b3-r04-reopen1` evidence/evidence2 | 0 | 真实 UI committed 后注入 reopen_host 失败；错误视图显示“资料已恢复，重新打开失败，请重启应用”＋保护位置；保护包 verify 等于 pre-restore full41/资源；旧窗保留、可正常关闭；新进程 restart 打开 source body 且版本数稳定。独立 reopenfe0 PASS。 |
| committed 后未知新服务退出（service 模式） | `kgm-b3-r04-reopen-svc4` | 0 | 新 ServiceRun 启动失败且退出未确认；同样显示 REOPEN_FAILED／保护位置；`latest_bundle_closed=false`、`runtime_lock_retained=true`，未假称 clean cleanup。独立 reopen-service PASS，明确保留锁。 |
| AI 冷启动 queued 任务 | `kgm-b3-r04-aicold4` | 0 | 目标来自真实恢复后的 `late4` 数据副本；实际 `AiExecutor` 冷启动，事件仅 `before_claim:5`，`claimed/sent/child_started/ready/marked/result_received` 全 0，provider 外发 0／guard0；task 由 pending→paused/restart，`processing_certainty=not_sent`、`permit_revoked_at` 非空、`next_attempt_at=null`、generation0、无 execution；DB diff 为空（仅四列允许变化），资源不变。独立 cold47a receipt＋semantic PASS。 |
| preview 取消＋实际 switching 后 cancel | `kgm-b3-r04-cancel7` | 0 | 第一段实际 preview 后点击取消：`backup-cancelled`、同 generation、full41／资源不变、无 transport stop；第二段实际 confirm 后轮询到 phase `switching`，host cancel 返回 `accepted:false,state:too_late`，不显示 cancelled，随后真实新窗／calendar／notice，full41＋资源等于 source。 |
| verify 返回边界 gate：selection verify＋automatic protection verify | `kgm-b3-r04-cancelg3` | 0 | 两段都包住**真实 SnapshotService.verify 已返回、caller phase transition 之前**的边界（不是资源字节 I/O）；UI cancel 点击后 gate 见真实 op cancel，terminal `backup-cancelled`；同 generation、full41／资源不变、transport 未停、旧窗保留。protection gate 使用精确 `data.restore-guard/<operation>/pre-restore.kgmbackup`，不使用 generic contains。 |

**取消边界诚实范围**：`cancel-gates` 证明的是 verify 返回后、调用方阶段推进前的真实 UI 取消；不声称在资源字节复制 I/O 中间取消。`cancel-window` 证明 preview 取消和 switching 后 too_late。产品/core/host 未改。

**新增纯校验与反例修复**：

- `desktop/tests/test_maintenance_source_entry.py`：30 passed。新增 pairwise file-artifact alias（bad=encrypted、out=bad、out=encrypted、out=source、out=target、bad=config）与 file/directory role 反例；新增 AI cold diff composite-PK 反例：`local_calendar_days(revision_id,date)` 两行同 date、仅 r1.base_state 变化必须被检出，猜测 `date` 单键会静默丢行。
- `maintenance_source_ai_cold._db_dump` 现在读取 SQLite 实际 PK；非 AI 表比较完整 row multiplicity，`local_ai_tasks` 只允许指定 task 的 `status/reason/runtime_meta_json/updated_at` 四列变化，并精确验证 paused/restart/not_sent/permit_revoked_at/next_attempt_at/generation0/no execution。
- `_validate_config` 在 mkdir／Runtime 前拒绝所有 file-artifact 两两别名、目录角色重叠、文件/目录角色错用；`out` 不再可能等于 bad/encrypted/source/target/config。
- watchdog：失败路径使用 `cleanup_done` 与所有 owned current/new windows 共同判定；超时只异步 best-effort destroy，随后无条件 `os._exit(3)`，不等待可能阻塞的原生 destroy。正常路径仍要求 `latest_bundle_closed` 确认。
- 失败保留：`kgm-b3-r04-cancelg2` 因 protection matcher 使用 `"restore-guard" in parts` 未命中 `data.restore-guard`，restore 继续并留下新窗；Codex 已按精确 PID 只停止本会话 2 个进程并保留完整 post-stop 副本（`b3-cancelg2-precise-process-stop.json`）。`cancel6` 因 required 包含 DTO dict `cancel_too_late_ack` 导致 summary false，已保留；`cancel7` 修复后通过。`cancel1`–`cancel5`、`cap1`、`cap2`、`cap628442`、`reopen-svc1`–`svc3`、`aicold1`、`aicold2`、`late1`–`late3` 首失败/中间现场均保留。

**最终源码 SHA-256（本会话最终树）**：

- `desktop/maintenance_source_verify.py`：`97cd96a1f3bff48e611258fc90497dd85f57927180548b4c0d2b2b2247f7f870`
- `desktop/maintenance_source_setup.py`：`91e13027cd1a3dab9f1f9ff6a0c42d03b309b796eb22d9eb094f6cb0968bb1b8`
- `desktop/maintenance_source_post.py`：`4ad942fd2a8cfd0e8ee4e87f5b8038e77114a62fa0c2eb9fef0eecaaa966cb36`
- `desktop/maintenance_source_restart.py`：`0661ea11da195eab2c473e4fa62078748a988ebff31f105caea5a98bad136b66`
- `desktop/maintenance_source_encrypted.py`：`1bdb66384079c1b6a6c402e48cdbe4b093eeb4e9ea605270952cc1ef85b2afd4`
- `desktop/maintenance_source_protection.py`：`e6cc7ba40101393405a84ef3f751850a0265b01ad424a89be2ecbbce2b11f622`
- `desktop/maintenance_source_late.py`：`58a10836402b73544f62ab8e7a1dafc36ecea2db5e5f6eaa9783e2f2dde5632b`
- `desktop/maintenance_source_reopen.py`：`fe0cae9f64a11d78c8acb499a6649abb6d70e9ec2d3f108f327b15f21ea6e0ab`
- `desktop/maintenance_source_ai_cold.py`：`47aaf82d3ef7a75819da881619d05e10f72144686b69f5db5bb1686f471a2b0e`
- `desktop/maintenance_source_cancel.py`：`ae2ee993a3061e3a62005039abb8f44c4572bb7a157f204863a513c0d7d69d1e`
- `desktop/maintenance_source_cancel_gates.py`：`af7ca8c526acc15df274a994b0aa6cbd37b48e511a978085a038595bdae4296a`
- `desktop/tests/test_maintenance_source_entry.py`：`a6f30c7a81240b3226e1d500c2e75786554bf650ce16d76426a1588d87d2a1dc`

**build 未重建**，仍为冻结前端的 3 个文件：`d1.html` `366a015d1f19b28ccd95e2c9a8a23c14fe16b16b3ea2a7ef73dd9c896a7fed8e`；`index-BFn3o4JJ.js` `6d4e5195da5edd8c722f8627cec9be10d204bd3ddd1699e3cbd379a42ca444ec`；`index-CuIYwak5.css` `08e7fa0c7c166fec4a20352c4d56274e3ff161be05d45a6aada04de91dd47c64`。`py_compile` RC0，`git diff --check` RC0；未 Git commit／push。

**仍未整体验收**：未做完整 desktop／核心回归、真实教师体验、真实供应商、WebDAV、签名、发行、冻结 EXE、跨机器／Win10／WPS／DPI；cancel-gates 仅覆盖 verify 返回边界；capacity 仅限该合成 604 原图／1208 衍生／1812 资源包；setup 独立通过不等于教师体验整体通过。最终独立复验须使用本段最终源码 hash；此前独立回执使用 archived verify80b746a 及匹配的 setup91e/post4ad/protectione6cc7ba4/late58a/reopenfe0/cold47a，不替代最终 verify97cd96a1 的独立复验。

**最终边界独立回执（本段源码已冻结）**：

- `kgm-b3-cdx-cancel-gates-r05-226b9a`：verify `97cd96a1`＋`maintenance_source_cancel_gates.py` `af7ca8c5`，实际 exit0／19.01s；verify-return／protection-return 的 UI cancel、Event 命中、generation 未切换、service alive、full41＋资源不变、guard0、latest closed。回执 `b3-cancel-gates-r05-independent-receipt.json`。
- `kgm-b3-cdx-cancel-window-r05-f9a00a`：verify `97cd96a1`＋`maintenance_source_cancel.py` `ae2ee993`，实际 157,647,029-byte 输入，exit0／111.20s；preview cancel 后档案不变；实际 switching 阶段 raw ack 为 `too_late`；随后实际完整 604 原图恢复／新窗／full41＋资源 exact／guard0／latest closed。回执 `b3-cancel-window-r05-independent-receipt.json`。
- 两份独立回执均记录 439 app／build／archive 稳定，并遵守本段范围守卫。到此本会话实现源码冻结，只保留本结果文档收口；未 stage／commit／push，等待 Codex exact manifest。
- 现场保留更正：`cancelg2` 首次 post-stop PowerShell 副本漏了 8 个深层文件；原始／私有 partial 副本保留，另在短 own root 用 extended-path 副本补齐全部 96 文件并逐文件 SHA 核对一致，回执已更新。不得把最初副本写成完整，也不据此启动或修复 D3。

---


## 附录：r01 首轮记录（历史，不再作为当前证据）

更新：2026-10-30。状态：B1 快照与检查源码实现、合成自测完成，停写等待 Codex 独立审核；未 Git、未开始 B2／B3、未发行。

基线：默认 `main`／桌面分支 `e836726f008676fc603a7b4cb058e5d96cafe60b`，业务 tree `5ab0c581985fb9f6fe229ed10dadf7b809ca81ec`，文档收口 tree `c6a139c619f696765d128fefbcb4970cff2af973`。B1 修改当前未提交。产品决定 P01–P05 见[备份规格](../specs/desktop-backup-restore.md)；Codex 独立记录见[独立核查](desktop-backup-restore-review.md)。

### 1. 实际改动

新增 local 层：

- `backend/app/local/backup_format.py`：Format 1 头、magic、模式、KDF、manifest 常量、流式加解密与 hash。
- `backend/app/local/backup_barrier.py`：按 data 根隔离的两阶段维护屏障；DB writer／文件操作计数、AI 内部写 scope、lease owner。
- `backend/app/local/backup_validate.py`：SQLite 完整性／FK／revision、schema 可信性、业务指针／来源／回执／照片顺序、manifest 与资源 hash 校验；旧已知 DB 只在隔离副本迁移。
- `backend/app/local/backup_snapshot.py`：SQLite 在线 backup、全部登记 asset／derivative 复制、确定性 STORED ZIP、明文／密码容器、进度／取消、最终 no-replace 发布、只读 verify。

必要接入修改：

- `backend/app/local/tx.py`：`begin_immediate` 进入 barrier writer 计数；rollback／commit／close 通过 SQLAlchemy transaction-end 事件配对释放。
- `backend/app/local/ai_executor.py`：冻结 owner 独立（close／snapshot 不互相清除）；claim／dispatch mark／finalize／pending flush 使用 AI 内部写 scope；新增 `is_snapshot_idle`；未改变 close 的 revoke／drain 语义。
- `backend/app/local/observation_assets.py`：`import_asset` 整个 staging→文件搬移→DB 提交阶段持有文件 scope；已开始导入在维护意图后仍可完成。
- `backend/app/local/observation_export_service.py`：导出临时 artifact 写入／删除持有文件 scope。
- `backend/tests/local/test_backup_snapshot.py`：B1 真实 SQLite／文件系统测试。

未修改 `ARCHITECTURE.md`、迁移、依赖、构建、前端、desktop UI 或 B2 恢复代码。

### 2. Format 1 与安全边界

- 文件：`.kgmbackup`，128 字节头 + 载荷 + 可选 16 字节 GCM tag；magic `KGMBKP1\0`，版本 1。
- 明文：KDF／盐／nonce／tag 为 0；头 SHA-256 仅损坏检测，不是来源认证。
- 密码：Scrypt 固定 `N=2^17,r=8,p=1`、随机 32-byte salt、随机 12-byte nonce、AES-256-GCM；完整头为 AAD；认证通过前不解析载荷；未使用不存在的 `maxmem` 参数，实际内存峰值见 §5。
- 载荷：确定性 ZIP_STORED，顺序 `manifest.json`、`db/kindergarten.db`、按路径排序的资源；无压缩炸弹、无 ZIP 加密成员、无符号链接。
- manifest：64 MiB 上限；快照 ID、UTC 时间、应用版本、DB revision、AI contract 列表、DB/资源路径／大小／SHA-256、计数、源身份。
- 技术上限：总包／展开 64 GiB、DB 8 GiB、单资源 64 MiB、成员 250,000；超限完整失败，不截断、不静默漏图；600 图与 1 GiB 工作集未被写成业务存储配额。
- 资源仅来自数据库登记的 `LocalObservationAsset`／`LocalObservationAssetDerivative`，包括已移出当前稿但历史／AI 引用的图；`observations/staging`、`export-temp`、磁盘 orphan、旧备份、`migration-backups`、程序、模板、Word、凭据根不纳入也不删除。
- DB 全快照保留 `local_ai_credentials` 的 key_id／nonce／ciphertext／state 与 `local_ai_state.database_uuid`；不读取、不导出 `credential_root/<database_uuid>/<key_id>.dpapi`，不解密 secret。

### 3. 一致性、屏障与 B2 接点

- `SnapshotService.create()` 顺序：维护意图 → 阻止新外部 DB／文件／AI 提交 → 等待已接受 DB／文件操作完成 → 等待所有 live AI task 终态及 pending result 持久化 → 原子取得 DB＋文件独占 → 才 freeze AI 调度 → 二次核对无 active／pending → 可选宿主 `external_quiesce` → SQLite backup／资源复制。
- 已开始的 `import_asset` 文件阶段和 AI finalize 在 intent 后仍可完成；新外部写被 `SnapshotBusy` 拒绝。现有 AI close freeze owner 与 snapshot owner 独立，snapshot 释放不会清除 close／恢复意图。
- `SnapshotLease` 只能由 owner 释放；取消／异常／重入释放自己的 lease；同根第二个快照返回 busy。
- B1 不接 UI，也不把宿主测试替身说成已接通。B2 接点：`VerifiedSnapshot.manifest/database_path/resources_root/staging_root`、barrier lease、`external_quiesce`；B2 负责 native save／页面关闭／保护副本／成组切换。
- 最终发布使用同卷 `os.link` 原子 no-replace；目标已存在或最后阶段并发创建目标时保留原字节并失败，不先 `exists()` 再 `os.replace`。

### 4. 校验器

- SQLite：在线 backup（含已提交 WAL）；`integrity_check`、`foreign_key_check`、`local_alembic_version` 唯一已知 revision。
- 可信 schema：41 张业务表＋版本表；拒绝未知表、view、trigger、virtual table、列集合不匹配；不 stamp、不清空。
- 业务校验：当前稿／历史版本／当前指针、照片归属与连续顺序、AI input→execution→attempt→candidate、日计划当前内容、term calendar、class game head、personal prompt head、AI config、恢复／导出回执。
- 资源：数据库登记路径必须等于 manifest；逐文件大小／SHA-256／DB hash；拒绝缺图、额外资源、路径穿越、链接／重解析点。
- 已知旧 DB 只在隔离副本升级；未知／过新 revision 拒绝；AI contract 是历史契约，不当作 DB revision，合法旧记录不删除。

### 5. 自测

命令均在 `backend` 下使用既有 `desktop/.venv-d1`，未安装依赖；日志为私有证据根下相对文件名。

| 命令 | 结果 | 日志 |
| --- | --- | --- |
| `python -m py_compile` B1 改动文件 | RC 0 | 终端 |
| `pytest tests/local/test_backup_snapshot.py -q` | 14 passed | `opencode-b1-tests-r13.log` |
| `pytest tests/local/test_observation_api.py test_observation_ai.py test_daily_plans.py test_config.py test_concurrency.py test_migrations.py test_d2_w3_executor.py -q` | 144 passed | `opencode-b1-regression-r03.log` |
| `pytest tests/local/test_observation_export.py test_observation_history.py test_d2_streaming.py -q` | 99 passed | `opencode-b1-regression-r04.log` |
| 31 MiB＋600 图 tracemalloc 探针 | Python peak 4,491,658 bytes；包 34,366,705 bytes | `opencode-b1-memory-r02.log` |

B1 测试覆盖：明文／密码两种模式、正确／错误密码、截断、头/载荷篡改、目标碰撞 no-replace、取消、未知触发器／未知 revision、已知旧 DB 隔离迁移、WAL 快照、当前稿移除但历史保留的图、全部登记衍生图、600 图／31 MiB、屏障重入与在途文件 scope、AI owner 不 revoke。

首失败保留：

- `opencode-b1-tests-r01.log`：manifest 缺 `database_revision` 字段；修正生成器后通过。
- `opencode-b1-tests-r02.log`：测试期望资源数 4，实际 8（两个导入各含原图＋AI＋export 衍生图）；修正期望。
- `opencode-b1-tests-r05.log`：最终发布竞态测试目标已预先存在，及明文 ZIP 篡改抛出未包装 `BadZipFile`；修正测试与错误映射。
- `opencode-b1-tests-r07.log`：尝试 downgrade 0006 被迁移明确拒绝（0006 不支持降级）；改为从空库升级到 0005 的隔离旧库。
- `opencode-b1-regression-r01.log`／`r02.log`：早期回归；最终 r03／r04 为上述通过结果。

### 6. r01 当时未验事实（历史）

- 未测真实磁盘不足、权限拒绝、文件占用、进程崩溃／真实断电；只做了受控取消、目标碰撞和合成路径。
- 未测实际 Windows RSS；只测 Python tracemalloc 峰值，不能外推全机型内存。
- B1 未接宿主 native save／页面关闭；`external_quiesce` 只有接口与测试替身，不能声称宿主已接通。
- 未测 64 MiB manifest 上限填满、250,000 成员上限、64 GiB 总包上限。
- 未测真实 DPAPI 跨用户／换机；只按规格排除材料，不读真实密钥。
- 未执行 B2 恢复、成组切换、保护副本、阶段日志、重启恢复；未做 B3 源码窗口闭环。
- 未调用真实 AI、未连接 WebDAV、未构建／执行冻结包、未 Git。

### 7. B2 交接

`VerifiedSnapshot` 提供隔离数据库、资源根、manifest 和 staging；B2 必须自行实现恢复预览、保护副本、运行锁／引擎排空、DB 家族与 assets 成组切换、持久阶段日志、启动前核对、AI 不重放及失败回退。B1 不把 `staging_root` 当作已恢复数据，也不把 `external_quiesce` 测试替身当作宿主接续。
