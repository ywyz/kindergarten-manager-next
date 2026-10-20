# D2 W1 实现交付结果（OpenCode）

更新：2026-10-18。本文件记录 D2 W1 的实现、测试、构建与冻结探针交付结果，供 Codex 最终核查。**Codex 已完成最终核查，W1 在当前 Windows 11 合成环境工程通过，不代表 D2 整体验收**；G03 完整基准链属 W4，真实供应商与 W2–W6 不启动。

授权与边界：延续 `docs/tasks/current.md`（2026-10-18）与用户“使用 go 套餐模型”指示。仅 W1；不安装、不真实 AI/供应商/旧远程、不运行真实库迁移、不发布、不 commit/push，继续分支 `codex/desktop-v2-foundation`。已验生产模块（`models.py`、`0004` 迁移、`runtime`、`credentials`、`config`、API）在本批保持，未修改。

## 1. 本批改动范围

### 1.1 生产代码
本批（R09 收尾）**未改动任何已验生产模块**。生产侧仍是 R01–R08 分项通过后的版本，关键源 hash：

| 文件 | SHA256（前 16） |
| --- | --- |
| `backend/app/local/runtime.py` | `82b77d420f1dafbd` |
| `backend/app/local/credentials.py` | `d16f7396b83f2371` |
| `backend/app/local/ai_config_service.py` | `f27177ee32fa75fd` |
| `backend/app/local/migrate.py` | `0198182e6663615f` |
| `backend/alembic-local.ini` | `27fd79741812fd79` |
| `backend/migrations_local/versions/20261017_0004_local.py` | `30a31e5f8a5dbc67` |

### 1.2 测试生命周期适配（`backend/tests/local/`）

| 文件 | SHA256（前 16） | 改动 |
| --- | --- | --- |
| `support.py` | `9205bc6ccd07734f` | `make_runtime` 显式注入合成 `credential_root`；`worker_spec` 增加 `credential_root`/`connect_only`；新增 `spawn_worker`/`collect_worker`/`run_worker` 方法与失败路径统一回收 |
| `worker.py` | `c6f88ba5e0b63de9` | 新增 `_AttachedRuntime` 专用连接模式：只连接已准备合成库，不迁移、不取第二运行锁；缺库/缺 owner 锁则报错 |
| `test_concurrency.py` | `8265d6ec06e70d7a` | 两连接改为同一 owner runtime 的独立 session；跨进程事务用 connect-only worker |
| `test_export.py` | `a7415332def69438` | 导出快照 worker 改 connect-only，父保持 owner |
| `test_restart.py` | `17b5da9e08dc517e` | 真重启 worker 显式 `connect_only=False`，顺序完整 runtime 退出再启动 |
| `test_initialize.py` | `30c9ccc3e3e29c98` | 跨进程初始化竞态 worker 改 connect-only |
| `test_paths.py` | `a7392adcb1c2d9a0` | 迁移资源哨兵动态定位当前 head（只改测试副本，不动 0001–0003）；`.app-runtime.lock` 加入精确白名单 |
| `test_migrations.py` | `54a0f211ef524cf0` | 两处直接 `LocalRuntime` 显式注入合成 `credential_root` |
| `test_calendar_dates.py` | `9be510a4baad7609` | 重启前显式 `dispose` 前一 runtime 再 prepare |

### 1.3 冻结探针（`desktop/`，新增）

| 文件 | SHA256（前 16） | 作用 |
| --- | --- | --- |
| `desktop/d2_w1_probe.py` | `000443fa57eba564` | 冻结控制台探针入口：`init` 初始化+保存密钥，`verify` 重启解密比较；secret 只经 stdin |
| `desktop/build_d2_w1_probe.py` | `16fdbc3319fb4ff3` | PyInstaller onedir 控制台包（不跑 npm ci、不覆盖 D0/D1 包） |
| `desktop/verify_d2_w1_probe.py` | `664a68b6ce815c60` | 父验证器：仓外特殊路径复制、双/三进程运行、独立核查与证据 |

> Codex 先复核修复前 `verify` 源 `f988edc2…`；修复后最终 SHA256 为
> `664a68b6ce815c60df418765f6f714319ae810ca779cd366dd3ecb0bca5f9a20`，Codex 已独立复测通过。冻结包本身未重建，hash 不变。

## 2. 命令与实际结果

统一解释器：`desktop/.venv-d1/Scripts/python.exe`（CPython 3.14.7 Windows x64，标准 GIL）。

### 2.1 D1 生命周期与全回归
- Codex 独立全 local：`python -m unittest discover -s backend/tests/local -t backend`，`LOCALAPPDATA` 仅进程级独立合成目录 → **286 项 / 118.079 秒 / 退出 0**（review §10，Codex 证据，不由 OpenCode 覆写）。
- Codex 独立原失败小组 48 项通过。
- Codex 独立 `test_migrations`（两处 credential_root 补齐后）→ **18 项 / 2.652 秒 / 退出 0**。
- OpenCode 定向 `tests.local.test_migrations` → **18 项 / 2.530 秒 / 退出 0**。

### 2.2 冻结探针
- 构建：`python desktop/build_d2_w1_probe.py` → 成功，产物 `build/desktop-d2-w1/package/KGNext-D2W1Probe/`。
- 正向：`python desktop/verify_d2_w1_probe.py` → **29 个布尔检查全部 true / 退出 0**。
  - 包复制前后逐文件一致：**127 文件**，manifest `657b3f01511fc113…`（源=副本）。
  - exe SHA256 `6a283bdfc9954c683ac2e86c75762ed99a0961ff7dde47580a55419a5e91d9f4`（与 Codex 独立值一致）。
  - `init`/`verify` 均 v1、同 `database_uuid`/`key_id`、实际 AES-GCM 解密与 stdin secret 相同；重启不增版。
  - 负例（另一随机 secret 再 verify）`decrypted_matches=false`，证明比较有效。
  - 冻结库 `PRAGMA integrity_check=ok`、`foreign_key_check=0`；配置/凭据/回执各 1。
  - 冻结 head `20261017_0004_local` 与源一致；3 默认 bundle 内容与 hash 与源迁移一致。
  - DPAPI 密钥文件 ACL 通过生产 fail-closed 校验器；整包位于仓外中文/空格/`%`/`#` 路径运行。
  - 全合成根文件与输出按 UTF-8 与 UTF-16LE 扫描，随机 secret 无明文；扫描不可读文件按失败报告。
- Codex 独立冻结终验（证据 `%TEMP%/kgm-d2-w1-codex-frozen-final-66tkpuyw/codex-evidence.json`）：仓外特殊路径 127 文件一致；21 个归档 app/入口模块代码元数据（仅忽略 `co_filename`）与源码一致；7 迁移/INI 资源一致；三次隐藏进程 init/verify/负例；FK/完整性/各一配置凭据回执正确；UTF-8/UTF-16LE 无明文。
- Codex 独立 PowerShell `Get-Acl`：真实凭据 root / UUID 目录 / 密钥文件三处均为仅当前 SID + SYSTEM 保护 DACL。
- Codex 亲自执行最终父验证器 `--keep --out`：所有检查通过 / 退出 0，证据 `%TEMP%/kgm-d2-w1-codex-parent-final-bb3d2d50209c4c68af979a48d895c8f7/codex-parent-evidence.json`；包仍 `6a283bdf…`。

## 3. 首跑失败与修正

### 3.1 D1 回归首跑（Codex 前置证据 `codex-d1-regression-before-r09.txt`：103 项 / 13 failures / 5 errors）
- 运行锁冲突：旧测试在同一数据根建第二个 `LocalRuntime` 或让 worker 自行 `prepare()`，被新整程锁拒绝（`LOCAL_APP_ALREADY_RUNNING`）。→ 改为**一个真实 owner runtime**；跨进程事务用 `worker.py` 专用 `connect_only` 模式（不迁移、不取锁、不开放生产 bypass）；重启用例显式 `connect_only=False` 且前一 runtime 已 `dispose`。
- 目录白名单：`.app-runtime.lock` 出现在数据目录旁。→ 精确加入 `DB_FILE_NAMES`（不做通配）。
- 迁移资源哨兵：硬编码改写 0003，导致 0004 引用缺失。→ 改为**动态定位当前 head**并只改测试副本。
- 管道未回收（ResourceWarning）。→ 测试内 worker 统一登记并在失败路径回收。
- 重启用例未释放前 runtime。→ 重启前显式 `dispose`。

### 3.2 父验证器中途缺口（Codex 反例 `%TEMP%/kgm-d2-w1-review-verifier-faults-9jmtmwfg/codex-evidence.json`）
1. **扫描吞目录错误**：`_scan_tree_for_secret` 用 `os.walk` 未传 `onerror`，`os.scandir` 抛 `PermissionError` 时错误被默认吞掉、`errors` 为空。→ 传入 `onerror` 收集错误；不可读即报告失败，不再当作“无泄漏”。
2. **结果字典残留 secret**：fake child 结果 JSON 含 secret 时，`stdout` 已脱敏但解析后的 `result` 字典仍带 secret，`result_leaked=true` 却会把明文写进证据。→ 解析前先对 `result_raw` 脱敏再 `json.loads`，并对解析结果递归脱敏；`result_leaked` 仍按原文判定为 true（脱敏不改变泄漏判定）。

修复后**有限故障注入**（独立 mock）：
- `os.scandir` 注入 `PermissionError` → `scandir_errors` 非空、`secret_scan_complete` 判 false。
- fake child 结果含 secret → `result_leaked=true`，证据中无明文，嵌套键/值均为 `[REDACTED]`，其它字段保留。
- 结论：`FAULT_INJECTION_OK`。
- 修复后正向父验证器一次：29 个布尔项全 true、退出 0，包 hash 不变。
- Codex 独立复测修复后两缺口：目录 `scandir` 失败记录、JSON 递归脱敏、原 `leak` 标志保留均正确，证据 `%TEMP%/kgm-d2-w1-review-verifier-fixed-bwxz_ele/codex-evidence.json`。

## 4. 既有证据引用
- `docs/bootstrap/desktop-d2-w1-review.md` §9（R01–R08 分项）、§10（全 local 286/退出 0、恢复入口）、§11（go 套餐续做）。
- Codex 冻结终验：`%TEMP%/kgm-d2-w1-codex-frozen-final-66tkpuyw/codex-evidence.json`。
- Codex 验证器反例：`%TEMP%/kgm-d2-w1-review-verifier-faults-9jmtmwfg/codex-evidence.json`。
- OpenCode 探针证据：`build/desktop-d2-w1/verify-evidence.json`。
- 前置首跑：`%TEMP%/kgm-d2-w1-codex-20261017-201057/codex-d1-regression-before-r09.txt`（不修改）。

## 5. 规格偏差与未验
- 冻结探针是**无 UI 验证程序，不是最终发行程序**；不含 GUI/TLS/Job、真实供应商调用。
- 冻结 schema 仍仅结构断言，完整运行时 JSON 校验留 W2/W3。
- DPAPI 为当前 Windows 用户；跨 Windows 账户、干净机器、Win10、WPS、其他 DPI/多显示器、WebDAV 与发行再现性仍未验。
- G04 本片冻结重启证据、G16 资源子项完成；G16 完整 GUI/TLS/Job 未验。
- 供应商调用、真实库迁移、发布均未执行。
- 原教师体验根 `%TEMP%/kgm-d1-teacher-experience-20261017-104847`、`exports`、已验 D1 包 `c6dc1928…` 未改动。

## 6. 状态声明
W1 实现、测试适配与冻结探针已交付并自验；Codex 已独立完成冻结终验、验证器缺口复测与最终父验证器核查（`--keep --out`，所有检查通过 / 退出 0）。本文件据 Codex 已确认的独立证据收齐改动清单与边界；**W1 是否关闭以 Codex 审阅结论为准**。本结果不代表 D2 产品验收，不启动 W2–W6、真实 AI 或发行。本批到此结束，不再新增代码或重复测试。
