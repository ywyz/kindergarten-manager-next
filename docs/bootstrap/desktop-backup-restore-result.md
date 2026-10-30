# 完整本地备份／恢复：B1 实施记录

更新：2026-10-31。状态：**B1 r04 已在限定后端源码／合成工程范围由 Codex 独立审核通过（review §8：BC-R01–R04、B1-R01–R10 关闭）；本记录仅对齐该当前状态。** 当前未 Git（等待 Codex 批准清单）、未开始 B2／B3、未发行。

基线：默认 `main`／桌面分支 `e836726f008676fc603a7b4cb058e5d96cafe60b`，业务 tree `5ab0c581985fb9f6fe229ed10dadf7b809ca81ec`，文档收口 tree `c6a139c619f696765d128fefbcb4970cff2af973`。B1 r02／r03／r04 修改当前未提交，等待 Codex 最终 blob／提交清单。产品决定 P01–P05 见[备份规格](../specs/desktop-backup-restore.md)；Codex 最终独立结论见[独立核查 §8](desktop-backup-restore-review.md#8-b1-r04-最终独立结论限定后端源码工程通过)。

> §1–§7 为 r02 记录、§8 为 r03 记录、§9 为 r04 回修记录，均保留为历史；Codex 最终独立结论见 §10。

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

**限定结论：BC-R01–R04、B1-R01–R10 在本节实际后端源码／合成工程范围关闭，B1 通过；可按 Codex 批准清单由原 OpenCode 普通提交推送，再接 B2。** P06 首次启动恢复入口仍待用户答复，不默认其产品行为，也不影响本限定 B1 结论。不把隔离副本称为已恢复当前档案；B2 保护副本／同一维护 lease／成组切换／启动接续／旧身份退役及宿主 UI，B3 源码窗口、教师实际体验、冻结包、Win10、跨机器／用户、真实断电、真实磁盘不足／权限故障与技术上限填满仍未验。D3 长根 WinError206、SAC4551 等既有边界保持；未真实调用供应商、未 WebDAV、未发行。

本记录当前仍未 Git（等待批准清单）、未开始 B2／B3；Codex 最终 blob／提交清单确认后另行提交。

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
