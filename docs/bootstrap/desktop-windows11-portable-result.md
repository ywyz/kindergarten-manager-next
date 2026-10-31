# Windows 11 内部便携候选：A 实施结果

更新：2026-10-31。状态：**r01 首候选构建成功但静态未通过并保留；r02 已过静态并保留；最终格式收口后的 r03 完整候选与新合成种子已完成，B／Codex 对实际 r03 的目录 54 项、ZIP 59 项静态核查均通过，见 §9。** 未启动候选 EXE／helper，目标机运行、Word、教师体验、签名及发行未验。A 自然停写后，Codex 仅归并本结果的最终审核状态；Git 以独立审核门禁及实际分支回执为准。

## 1. 本轮范围

- 独占文件：`desktop/build_e14.py`、本结果文档。
- 未改 app／core／frontend 生产源码、B／C／D 文件、Codex 文档或 Git。
- 所有临时探针在 `%TEMP%\kgm-win11-portable-20261031-9715e2b5\A-*`，不进入仓库或候选。
- 首次失败与后续通过分开记录；实际构建与合成 seed 均已完成，候选未执行。

最终 `desktop/build_e14.py` SHA-256：

`e3b530085acfe38b858aff4c39020bcb51a237d25636f5f1fd3d5fa45b255330`

## 2. 实际实现

### 2.1 名称与根

- `PRODUCT_NAME`／`APP_NAME`：`KGNext-E14`（保留现有产品名）。
- 新默认 build root：`build/desktop-e14-win11-r01`；旧 `desktop-e14-r03`、`desktop-e14-r03-pre-prune` 加入受保护旧根。
- `--portable-dir`：可选，默认 `build_root/dist`，必须位于本次新 build root 内且与 dist／work／spec／frontend／package root 全部不相交；非空目录拒绝复用。
- `README_NAME`：`README-KGNext-E14-win11-r01.txt`。
- `ARCHIVE_NAME`：`KGNext-E14-win11-r01.zip`。
- `MANIFEST_NAME`：`package-files.json`；`SUMS_NAME`：`SHA256SUMS.txt`；`MANIFEST_SCHEMA_VERSION=1`。

### 2.2 来源补齐

`SOURCE_GROUPS` 已补：

- product：`desktop/maintenance_host.py`、`desktop/maintenance_lifecycle.py`、`frontend/d1.html`、`frontend/tsconfig.json`。
- build：`desktop/requirements-d1.in`。
- verification：C 的 `desktop/tests/test_windows11_portable_static.py`、D 的 `desktop/check_windows11_target.ps1`（当前存在则纳入；缺失记录在私有 freeze 的 `missing_optional`，生产／构建必需路径缺失直接失败）。

`source_freeze()` 现在：

- 使用 POSIX 相对路径；
- 记录 `commit`、`git_status`、`git_diff_names`、`groups`、完整 `files`、`file_count`、`digest`、`missing_optional`；
- `before` 在 Vite 前，`after` 在 PyInstaller／metadata／README／manifest／SHA／ZIP 完成后；
- `stable` 由重算后的完整文件 map／digest 判定，不是只看字符串；
- 必需来源缺失直接 `SystemExit`，不静默通过。

### 2.3 路径防护

`validate_write_plan` 现在额外拒绝：

- 非 `build` 直接子根、非 `desktop-e14-` 名称、受保护旧 r03 根；
- 非空 build root（真实构建 `require_fresh_root=True`）；
- `portable-dir` 与 dist／work／spec／frontend／package root 相交；
- 非空或非目录 `portable-dir`；
- 已存在的 `--hash-out`／`--source-freeze-out`（不覆盖未知输出）；
- hash／freeze 输出别名或互相包含；
- 已有 symlink／junction／Windows reparse 组件；
- 只读 `--frontend-dir` 与任何实际写入目录相交。

`--check-paths` 仍为纯只读，不创建目录、不运行 Vite／PyInstaller。

### 2.4 便携产物

`write_portable_archive(...)` 为可测试的显式输出函数：

- 产品目录：`package/KGNext-E14/`；
- 外层：`dist/README-KGNext-E14-win11-r01.txt`、`package-files.json`、`SHA256SUMS.txt`、`KGNext-E14-win11-r01.zip`；
- ZIP 只含文件条目、排序、固定 `1980-01-01` 时间戳、`ZIP_DEFLATED` level 6，不含目录／链接／加密；
- `package-files.json` 严格 `schema_version=1`、`package`、`build_id`、`database_revision`、`source_freeze_digest`、`generated_at`、`files=[{path,size,sha256}]`；路径相对产品根、POSIX、排序、无重复／`..`／盘符／反斜杠；
- `SHA256SUMS.txt` 严格 `<64hex>  <path>`，覆盖产品文件＋README＋manifest，不含自身；
- `package-info.json` 保留现有字段，并新增 `unsigned_internal_test=true`、`source_commit`、`frontend_digest`、`frontend_file_count`。

前端摘要公式（A/B 共用）：对 `hash_tree(frontend)` 的 path+sha256 对象按 path 排序后，取 compact JSON（`sort_keys=True,separators=(",",":")`）的 SHA-256。`tree_digest()` 已导出；`product_tree_digest()` 现在与 `tree_digest()` 使用同一 canonical JSON 公式（不再使用 TAB 行公式），与 B `_tree_digest` 一致。

### 2.5 兼容性

- 保留 `main() -> int`、现有 builder CLI（`--build-root`／`--frontend-dir`／`--dist-root`／`--hash-out`／`--source-freeze-out`／`--check-paths` 等）、`install_package_metadata` 前 4 个位置参数、`build_package`／`build_frontend` 既有签名。
- 未传 `--portable-dir` 时保持历史 4 参数 metadata／旧 hash 输出行为；实际便携构建必须显式传 `--portable-dir`，才生成 README／manifest／sums／ZIP。
- 保留 `APP_NAME=KGNext-E14`、`hash_tree`、`SOURCE_GROUPS` 等旧名称。

### 2.6 Codex provisional feedback r01 修正

- `validate_write_plan` 现在先检查**原始**输入路径的 `..`、symlink／junction／reparse 和文件／目录角色，再 `.resolve()` 做最终重叠比较；`main` 保留 raw 输入直到 guard 返回，之后才用 plan 的 resolved 路径构建。
- `dist-root`／`work-dir`／`spec-dir`／frontend 输出／`portable-dir` 现在两两检查相交；`package_root` 仍允许位于 `dist-root` 内。
- `write_portable_archive` 在任何 mkdir／README／manifest／sums／ZIP 写入前检查：raw reparse、package／portable 角色与相交、四个输出名必须单层 basename 且互不相同、全部输出已存在即拒绝、非空 portable-dir 拒绝；README／manifest／sums 用 exclusive create，ZIP 用 `x` 模式。
- `product_tree_digest()` 改为与 `tree_digest()` 相同的 canonical JSON（path+sha）公式，避免与 B `_tree_digest` 的 digest 语义不一致。
- 文件／祖先非目录角色、raw 输出别名和 reparse 的正式反例由 C 在自有测试中补齐；A 本轮不写 C 文件、不真实清理任何根。
- 该修正轮当时未构建；后续 C／D 全部停写、Codex prebuild gate 批准后，才用冻结源码执行 §3 的实际构建。

### 2.7 A r02 清理／路径复核修正

独立首失败 `codex-A-prune-alias-r02-first.log`（exit 1，root 见 `codex-A-prune-alias-root.txt`）：合成 `package/__pycache__` 是指向另一自有合成目录的 junction；旧 `prune_package_caches` 进入 `shutil.rmtree`，Codex 在 mutation 前拦截，outside sentinel 与 junction 保持完整。该证据只证明路径检查缺失，不声称实际删除外部文件。

修正：

- 新增 `_safe_walk_entries`：在任何字节读取或删除前检查 raw 根、全部已有祖先和每个嵌套条目的 symlink／junction／reparse／特殊文件，并确认解析后仍在受信根内；遇到 junction 直接拒绝，不进入其内容。
- `prune_package_caches` 先完整遍历并验证所有候选缓存文件／目录，再删除；缓存文件逐个 `unlink`，缓存目录由深到浅 `rmdir`，不再调用 `shutil.rmtree`；每个删除前重新检查受信身份。
- `hash_tree` 改用同一安全遍历，因此 portable writer 的 manifest／sums／ZIP 在读取字节前拒绝嵌套链接。
- 复跑同一只读拦截探针：`rejected_before_cleanup=true`、`cleanup_calls_intercepted=[]`、`outside_sentinel_intact=true`、`junction_preserved=true`；`hash_tree` 同样拒绝。正常自有临时包（真实 `__pycache__`／`.pyc`）清理后仅保留普通文件。
- C r02 的更强反例仍由 C 自有文件维护；A 未改 C 断言或文件。

## 3. 实际构建（Codex prebuild gate approved）

Codex 构建前门禁已批准，源码 freeze 为 243 files、digest `040c49e9a6b68a4d8197a4acbb75b50a18cb2249f4157ad221459721db568b62`；A 只执行一次实际构建，未改源码。

### 3.1 命令与退出

先只读 `--check-paths`（新 root／portable／私有 hash／freeze 输出；RC 0，未创建目录或输出）：

```powershell
$root = "$env:TEMP\kgm-win11-portable-20261031-9715e2b5"
& .\desktop\.venv-d1\Scripts\python.exe .\desktop\build_e14.py `
  --check-paths `
  --build-root .\build\desktop-e14-win11-r01 `
  --portable-dir .\build\desktop-e14-win11-r01\dist `
  --hash-out "$root\A-candidate-r01-package-hash.json" `
  --source-freeze-out "$root\A-candidate-r01-source-freeze.json"
```

实际构建命令（同一新 root；无 `--skip-frontend`、无旧 r03、无安装／升级／签名）：

```powershell
& .\desktop\.venv-d1\Scripts\python.exe .\desktop\build_e14.py `
  --build-root .\build\desktop-e14-win11-r01 `
  --portable-dir .\build\desktop-e14-win11-r01\dist `
  --hash-out "$root\A-candidate-r01-package-hash.json" `
  --source-freeze-out "$root\A-candidate-r01-source-freeze.json"
```

- `A-build-r01-check-paths.stdout.log`／`.stderr.log`：check-paths RC 0，stderr 空。
- `A-build-r01.stdout.log`／`.stderr.log`：实际构建 **RC 0**；Vite 1.17s，PyInstaller 完成 onedir／windowed／COLLECT。
- 未执行候选 EXE／资源探针／helper；B 将另做静态核验。

### 3.2 构建身份与产物

| 项 | 实际值 |
| --- | --- |
| build root | `build/desktop-e14-win11-r01` |
| 产品目录 | `build/desktop-e14-win11-r01/package/KGNext-E14` |
| onedir | **190 files／80,503,817 bytes** |
| 主 EXE | `KGNext-E14.exe`，**16,702,555 bytes**，SHA-256 `8fa0cc706aafe53b6276095ff63873de98fa68f84c706953cf197822b7362af7` |
| build_id | `1b3a4c42-febc-46f8-bac4-4fa23957efc3` |
| version／revision | `0.1.0`／`20261025_0006_local_game_observations` |
| source commit／状态 | `91e6a553db6d25a1603849f139f22e9d9097537b`；**dirty base，不是纯提交** |
| source freeze | 243 files；before／after digest 均 `040c49e9a6b68a4d8197a4acbb75b50a18cb2249f4157ad221459721db568b62`；stable true |
| frontend | 3 files；digest `bf5b29935932d413993600e0e5083df49429b960fd5b2cd7eab814b265c85391` |
| ZIP | `dist/KGNext-E14-win11-r01.zip`，**43,960,853 bytes**，SHA-256 `3f09641aa1645459931556a5dc55205820a42d2efcd2dcde3526d68bb5185943`；193 entries，0 directory entries，deflate |
| manifest | `dist/package-files.json`，190 files，SHA-256 `36b69ff7a9127ebaa7141d695f4a889a307347108a724caa2a01c9428bf33a11` |
| SHA256SUMS | `dist/SHA256SUMS.txt`，192 lines，SHA-256 `d413fd83dca750bb98eef33938411c1f55d66ff030e93e4570f797109ef486d1` |
| README | `dist/README-KGNext-E14-win11-r01.txt`，SHA-256 `42781514698ff2eb5f9c6d277ccf24de4243e1de12d63be9a96fb29572071304` |
| 私有 hash 输出 | `A-candidate-r01-package-hash.json`，SHA-256 `fa080e7d942d2e40c5db0e96e19a8aeb535ef22f0b5920d28a0c66805c5a9ccf` |
| 私有 freeze 输出 | `A-candidate-r01-source-freeze.json`，SHA-256 `9a107ef0276d49964003348b0d71c023e30d8ab7f1e0551c6705239db883ed30` |

`package-info.json` 实际包含 `unsigned_internal_test=true`、`source_commit=91e6a553…`、`source_freeze_digest=040c49e9…`、`frontend_digest=bf5b2993…`、`frontend_file_count=3`、Pillow 许可证／插件／迁移／模板字段。`build_identity.json` 的 app_id／format／platform／arch／python／revision 与现有合同一致。

### 3.3 r01 静态检查结果（NOT PASSED，保留候选）

Codex 实际读取 r01 CArchive／PYZ：103 个 in-scope modules 均与当前代码匹配；但静态检查 **NOT PASSED**：

- **source-gap**：恰好五个当前 desktop 生产源缺少 freeze 条目：
  `desktop/d0_db.py`、`desktop/d0_driver.py`、`desktop/d0_host_api.py`、`desktop/d0_server.py`、`desktop/d0_word.py`。
  本轮只在 `SOURCE_GROUPS["product"]` 增加这五个实际归档输入及注释；未改 d0／产品代码，未把模块降级为 verification，未跳过比较。修复后首次只读为 **248 files／`9a4b7b13…`**；当前重读为 **248 files／`c36eede43b5e7b365d570f4c8014d84930099efed9f4c9b455fabc82d2629077`**（C／D 仍在写，最终以 Codex 新-source gate 重算为准）。
- **隐私误报（B 责任）**：`archive_pyz_matches_freeze` 与 `privacy_no_absolute_paths_in_text`／`no_absolute_paths_in_text` 命中 `cryptography` upstream SBOM 的 `/D:/` 引用和 frontend JS regex literal；B 修 verifier 的区分规则，C 补反例。A 未改 B／C 文件，也未用 blanket exclusion 掩盖。
- **r01 候选保持只读**：root `build/desktop-e14-win11-r01`、ZIP SHA-256 `3f09641aa1645459931556a5dc55205820a42d2efcd2dcde3526d68bb5185943`、build_id `1b3a4c42-febc-46f8-bac4-4fa23957efc3` 均不覆盖、不复用。
- **下一物理 root**：`build/desktop-e14-win11-r02`；逻辑便携 basenames 仍为 `KGNext-E14-win11-r01.zip`／`README-KGNext-E14-win11-r01.txt`，不要求改 D／产品版本。新 build 仅在 Codex 新-source gate 后执行。
- 本轮未构建、未执行候选；r01 静态 NOT PASSED，不能写成 target／frozen／教师体验通过。

### 3.4 r02 新物理 root 实际构建

Codex r02 prebuild gate approved；新 source248 digest `9b36ab682e2740eb0d881d5bb56d9b13d6d351a9e335b2e2deaac9cc613930f5`。新 root `build/desktop-e14-win11-r02`（此前不存在）一次实际构建，r01 root／ZIP 未覆盖。

- 只读 `--check-paths`：**RC 0**，未创建目录／输出；日志 `A-build-r02-check-paths.stdout.log`／`.stderr.log`。
- 实际构建：**RC 0**；日志 `A-build-r02.stdout.log`／`.stderr.log`；Vite 1.02s，PyInstaller 完成 onedir／windowed／COLLECT。
- 未执行候选 EXE／helper／资源探针。

| 项 | r02 实际值 |
| --- | --- |
| build root | `build/desktop-e14-win11-r02` |
| build_id | `b16df7a7-d575-4555-bdee-84e42367a5e9` |
| source commit／状态 | `91e6a553db6d25a1603849f139f22e9d9097537b`；dirty base，不是纯提交 |
| source freeze | 248 files；before／after digest 均 `9b36ab682e2740eb0d881d5bb56d9b13d6d351a9e335b2e2deaac9cc613930f5`；stable true |
| onedir | 190 files／80,503,817 bytes |
| EXE | 16,702,555 bytes；SHA-256 `814c7c0d1015319fea8d9f25c35fcf6704db5ef8835494c1dd6d99a7ff8074f8` |
| ZIP | `dist/KGNext-E14-win11-r01.zip`；43,963,375 bytes；SHA-256 `63bd8f79c549223d0bc19d06b9773a99efd9b06d00e7de60cacf1975ac21dc35`；193 entries／0 dirs／deflate |
| manifest | 190 files；SHA-256 `88f9cb357694d22df756bf3a752d8231c6dafcebb3e02f6b7cfcab555aafc6e4` |
| SHA256SUMS | 192 lines；SHA-256 `e6a9c5ed569098bf984e6b8fdd9d0c8159b3faea985365e6b998e1a56dee61a6` |
| README | SHA-256 `6c90b294ab748b4cc0bc83accae2a036527c6ea9301e86827c47cb540425d8c1` |
| frontend | 3 files；digest `bf5b29935932d413993600e0e5083df49429b960fd5b2cd7eab814b265c85391` |
| 私有 hash 输出 | `A-candidate-r02-package-hash.json`，SHA-256 `c74ffe52cf4fa236f99acf30ea24424db3e71f127702080d078ec818313e277b` |
| 私有 freeze 输出 | `A-candidate-r02-source-freeze.json`，SHA-256 `efa38b6a8884586ab177e61516ea00782f107341ef07a1dacefb72fba894124b` |

逻辑 portable basenames 仍为 r01（`KGNext-E14-win11-r01.zip`／`README-KGNext-E14-win11-r01.txt`）；物理 root／build_id／hash 区分 r01 与 r02。

## 4. 独立合成 seed 备份交接

使用现有冻结 `backend/tests/local/backup_fixture_support.seed_existing_runtime`＋`LocalRuntime`＋`SnapshotService`，无新 tracked 代码、无应用执行器／HTTP 服务／窗口、无供应商调用、无真实 secret。私有 TEMP fixture root 保留，不在结果文档公开绝对路径；原始 DB／凭据／DPAPI／work／日志／guard 报告只留在私有根。

- 私有执行脚本：`A-build-r01-seed.py`；stdout／stderr：`A-build-r01-seed.stdout.log`／`.stderr.log`；实际 **RC 0**。
- Guard：`maintenance_source_guard.NetworkGuard` 在 Runtime／fixture 前安装，child guard 先于任何 child；child selftest true；主 guard attempts before／after 均 **0**，`audit_ok=true`，主 log attempts 0；child selftest log 1（独立 selftest，不计入主 guard）。
- Fixture：4 AI tasks 全终态（`failed=1`、`outcome_unknown=1`、`succeeded=2`），无 pending／claimed／dispatching／retry_wait／paused；无自动重发。合成记录／照片／加密 AI 记录均为现有 fixture 生成。
- 两份备份均通过实际 `SnapshotService.create`＋`verify`；数据库 full／business 与资源指纹均等于 seed 前 fixture；资源 **12**。
- 明文：`synthetic-plain.kgmbackup`，**1,408,604 bytes**，SHA-256 `cf0369afc5fe91e08b2c0ae03dad7db569b9a182942c6f28d955881027f9d6b5`。
- 加密：`synthetic-encrypted.kgmbackup`，**1,408,620 bytes**，SHA-256 `339efe603123678310024331131046f633541b2628d97712c616bac21e7724b2`；密码 `KGM-W11-Synthetic-Only`（合成测试密码，不是真实 secret）；无密码 verify 被拒绝。
- Source identity（两份 manifest 均记录）：`kind=synthetic_source_service`、`source_freeze_digest=040c49e9…`、`app_version=0.1.0`；明确是 **synthetic SOURCE SERVICE**，不是新冻结程序创建。Seed 证据只保留 SOURCE SERVICE 身份，不声称 r01 候选或新 r02 创建。
- Handoff：`build/desktop-e14-win11-r01/handoff-synthetic/`，位于 build root 内、product／ZIP 之外；严格 4 个文件：
  - `synthetic-plain.kgmbackup`
  - `synthetic-encrypted.kgmbackup`
  - `README-synthetic-handoff.txt`，SHA-256 `a7c41713e8a14a30135fb9fe1baadb6b2a6e4d95fe307f45ca978bd02fc6c19d`
  - `SHA256SUMS.txt`，SHA-256 `36ad2e0145d1a165bc3b8d1a95dbb79b87dde4ead05759facbcc5437b7f59673`
- Handoff 写入前验证 build root／product／dist／handoff 解析边界、freshness 与无 reparse；复制后逐文件 SHA 一致。未把 raw DB／DPAPI／work／日志／guard 报告复制到 handoff；未修改 product／ZIP。

### 4.2 r02 fresh SOURCE-SERVICE seed handoff

使用新的私有 TEMP fixture root 和新的 `build/desktop-e14-win11-r02/handoff-synthetic`；未复用 r01 fixture、未写 r01。私有执行脚本 `A-build-r02-seed.py`（由 r01 orchestration 仅改路径／digest 的私有副本），实际 **RC 0**；日志 `A-build-r02-seed.stdout.log`／`.stderr.log`。

- Guard：child selftest true；主 guard attempts before／after **0**，audit true，主 log 0；child selftest log 1（独立）。
- Fixture：4 AI tasks 全终态（`failed=1`、`outcome_unknown=1`、`succeeded=2`），无 live；合成记录／照片／加密 AI 记录。
- 两份包通过实际 `SnapshotService.create`＋`verify`；DB full／business＋12 resources 与 seed 前一致。
- 明文：`synthetic-plain.kgmbackup`，1,408,604 bytes，SHA-256 `f652d8fac9a99c65433922d17f09eed037b5cc678bf3dbac485d887ef4b2541d`。
- 加密：`synthetic-encrypted.kgmbackup`，1,408,620 bytes，SHA-256 `48c598d6f5dc87c7a4fec95d4ca220d9604619dfd50ed199de99d21e89be64fa`；密码 `KGM-W11-Synthetic-Only`；无密码 verify 被拒绝。
- Source identity：`kind=synthetic_source_service`、`source_freeze_digest=9b36ab682e2740eb0d881d5bb56d9b13d6d351a9e335b2e2deaac9cc613930f5`、`app_version=0.1.0`；只代表 SOURCE SERVICE 生成，不代表 r02 冻结程序 UI 备份。
- Handoff 严格 4 文件：两包＋`README-synthetic-handoff.txt`（SHA-256 `445a0cc03e74d62a39adfbf924c903dc0803fbfd45b3325bb6f414df7ccfedd1`）＋`SHA256SUMS.txt`（SHA-256 `b1bd963eece33b13b62d7f749f3dc48dea19ef4f8f5cf59aaec07154b406b8da`）；位于 product／ZIP 外，未复制 raw DB／DPAPI／work／日志／guard 报告。

## 5. 检查与首失败

r01 实际构建与 seed 成功但静态 NOT PASSED（§3.3，保留）；r02 实际构建与 fresh seed 成功（§3.4／§4.2），r02 静态已独立通过（目录 54 项／ZIP 59 项，均 exit 0）。此前保留的首失败／修正：

- 初次现有 `test_e14_build_guard.py`：2 failed（fake metadata 参数、fake digest 稳定判定）；修正后 32 passed。
- Codex r02 prune-alias 首失败：junction `__pycache__` 在 mutation 前被拦截；修正后 `rejected_before_cleanup=true`、`cleanup_calls_intercepted=[]`、sentinel／junction 完整；正常临时包 prune 通过。
- r01 check-paths RC 0／build RC 0／seed RC 0；r02 check-paths RC 0／build RC 0／seed RC 0；均未执行候选。
- Codex actual r01 source-gap：五个 D0 生产源未入 freeze；builder source list 修正后 r02 freeze 为 248 files／`9b36ab682e2740eb0d881d5bb56d9b13d6d351a9e335b2e2deaac9cc613930f5`；r01 自身仍为 243 files／`040c49e9…`，不混写。

构建后只读复核：r01 ZIP `3f09641a…` 与 build_id `1b3a4c42…` 未变；r02 ZIP `63bd8f79…`、EXE `814c7c0d…`、manifest `88f9cb35…`、SUMS `e6a9c5ed…`、README `6c90b294…` 与 §3.4 一致；r02 `source_freeze()` 仍为 248 files／`9b36ab68…`；两份 handoff 两包 hash 与 §4.1／§4.2 一致，seed 未改变 product／ZIP。

## 6. 仍未验证

- r01 静态检查 **NOT PASSED** 已保留；r02 静态已独立通过（目录 54 项／ZIP 59 项，均 exit 0）。二者都不能写成 frozen／target／教师体验通过。
- r01 的 `archive_pyz_matches_freeze` 是五个 D0 来源未入 freeze 的真实缺口，已由 A 补齐；`no_absolute_paths_in_text` 的 upstream SBOM／JS regex 命中经判别属于误报，由 B 修 verifier、C 补真实泄漏与合法文本反例。二者不是同一问题。
- 未执行候选 EXE／helper、资源探针、GUI；未做目标 Windows 11 实际运行、Word 逐页、教师体验。
- 未签名、未发行、未 WebDAV、未真实 AI、未目标机远控；Git 普通提交推送须遵守 Codex 的具体清单门禁。
- r01／r02 source 均为 dirty base `91e6a553`，不是纯提交；实际构建身份以各自 build_id／freeze 为准。
- r02 物理 root 为 `build/desktop-e14-win11-r02`；逻辑 basenames 仍为 r01，不修改 D／产品版本。
- 合成 handoff 只用于目标测试，不是教师真实档案；其 source identity 仅为 synthetic SOURCE SERVICE，不代表 r01／r02 冻结程序 UI 备份。目标机仍需按手动清单独立验收。

## 7. 停写

A r01 失败静态候选与 r02 实际构建／fresh seed 均保留；**未执行候选、未 Git、未改源码**。r01 root／ZIP 保持只读；r02 product／ZIP／handoff 已完成并经 B／Codex 实际静态核查。A 当前停止实施；后续仅执行 Codex 独立审核批准的 exact Git manifest，不追加源码或文档改动。


## 8. r02 独立审核归并（最终 r03 见 §9）

Codex 在各实施会话停写后独立完成：完整 desktop **493 passed／exit 0**；实际目录 **54 checks**、实际 ZIP **59 checks**，固定必需项全部为 true，failed／missing／non_bool／unknown 均空。两个全新源码 Python 进程在导入检查器前装外层启动守卫，process events 均为 0。实际归档 1840 模块中比对 89 个生产与 14 个验证辅助模块，103 个全匹配，生产来源全入 248 项 freeze；必需 53 项齐全。ZIP／manifest／sums 与实际 190 文件逐字节对应。

现有 PS7 对本机新解压副本只读预检 **49 checks／exit 0**；107 个 PE 中 76 Valid、31 NotSigned，主 EXE NotSigned，不代表 SAC／WDAC 放行。系统 PS5.1 parser 0 errors；其文件执行被 Restricted 阻止，不绕过。没有执行新包或操作另一台电脑。

Codex 在另一个全新隔离源码 Runtime 独立验证 §4.2 实际两份 handoff：SHA、解密后 DB、41 表业务指纹、12 资源和终态任务一致，无密码拒绝加密包；主网络守卫 attempts／log 为 0、audit true。handoff 的 sums 覆盖两份备份，README 自身 SHA 另核；全部四文件与 A 交付一致。这是源码服务验证，不是冻结包 UI 的备份／恢复证据。详细首失败、范围、证据及 Git 门禁见[独立核查](desktop-windows11-portable-review.md)，后续按[目标手册](desktop-windows11-portable-manual.md)和[唯一当前提示词](../tasks/current.md)执行。


## 9. 最终 r03：EOF 格式收口后的独立身份

最终 Git 卫生核查发现 C 维护的测试末尾多一个空行；C 同一原生会话仅删除末尾 `CRLF`，Codex 用“补回该 CRLF 后 SHA 恢复旧值”证明其余字节相同。新 test SHA `16f2c4fb92a46d822d62f3a54698f0f368636d885a7872baa42f83553b663334`。248 项 freeze 中仅该验证测试变化，生产／检查器源码不变。Codex 新短 TEMP 完整回归 **493 passed，78.30s，exit 0**，2 条既有警告；diff --check 已通过。由于测试也在 freeze 中，未挪用 r02 清单，A 按 Codex 明确请求在全新 r03 根重建，r01／r02 不覆盖。A 此轮未写任何 tracked 源码／文档，结果由 Codex 归并。

### 9.1 实际构建与静态

| 项目 | 最终实际值 |
| --- | --- |
| root／产品 | `build/desktop-e14-win11-r03`／`package/KGNext-E14` |
| build_id | `5babc817-5b2a-466b-b382-36cffa02cace` |
| source freeze | 248 files，before／after `e1bbc5b01a1b55efece4a45089dc22f9e34fc872908bbb9c261aea85d0c03208`，stable true；带变更的基线 `91e6a553…` |
| ZIP | `dist/KGNext-E14-win11-r01.zip`，43,963,980 bytes，193 entries；SHA `0a1b9c0b55612de889e621f70ed1374d8e792d3755d9fce1eadf17b7b6532470` |
| 产品 | 190 files／80,503,817 bytes，tree SHA `57a87507140130c41431cdfbc876e9d5b8347d43be321db752a8b47f21554761` |
| 主 EXE | 16,702,555 bytes，SHA `bb9214c2976aba96393740eee1aacb7727487aa294529849e4fe6a1cd989e9c3` |
| manifest／SUMS | SHA `7f8ad612d7d45ace16a3215a2c36827b6496d1afd7bf36a7f73e64cbb366e027`／`b522d73268fb31b888049de82ea3e4b917d44a6142780a2c2f63e12d8510bbce` |
| README | SHA `1edb72fa06d4f687e048be807279005c4854cd9936f76a0818327ad408b55fc6` |
| frontend | 新构建 3 files，digest `bf5b29935932d413993600e0e5083df49429b960fd5b2cd7eab814b265c85391` |
| version／schema | `0.1.0`／`20261025_0006_local_game_observations` |

A 的 check-paths、实际完整构建和 fresh seed 均 exit 0；无 skip-frontend、安装、签名或候选执行。B 同原生会话静态检查实际 r03 全部通过。Codex 在两个全新源码 Python 进程、导入前外层启动守卫下独立实际目录 **54**／ZIP **59** 检查全部 true，失败／缺项／非布尔／未知及 process events 均空。再直接比 CArchive／PYZ、190 实际文件、ZIP／manifest／sums 每字节，89 生产＋14 验证辅助共 103 个非入口模块匹配，CArchive 主入口及 PYZ 重复入口另外均匹配，53 必需齐全；生产全入 freeze。

现有 PS7 对本机另一个全新解压副本只读预检 **49 checks／exit 0**；107 PE 仍为 76 Valid／31 NotSigned，主 EXE NotSigned。PS5.1 的解析／受阻边界及目标未验保持。本轮最终交接只使用此 r03 身份，r02 已过静态事实保留，不改写为失败，也不与 r03 混用。

### 9.2 新 r03 合成 seed handoff

A 用新的私有 fixture root 和现有源码 SnapshotService／fixture，生成 `build/desktop-e14-win11-r03/handoff-synthetic/`：

- 明文 `synthetic-plain.kgmbackup`，1,408,604 bytes，SHA `c3c2e4c029d9b6eade6c363a9f758ecf4b70c89e2e8d3466d753d2be15331a2f`。
- 加密 `synthetic-encrypted.kgmbackup`，1,408,620 bytes，SHA `3423fe50bf1e88e1c6eeb97bbd57ce7a5bd7e2e6fb3f38a46b4346d341f0ff67`；测试口令 `KGM-W11-Synthetic-Only`。
- `README-synthetic-handoff.txt` SHA `a575fb53aea0d238d3d3fb57104dccd7eea0f0a24ab0847be04840d0c1f218c3`，`SHA256SUMS.txt` SHA `29f404a43ec94dcbe7815f3db0c361c5c14bf17ebf13f9f66e4a444c30e4df9b`；严格四文件，SUMS 覆盖两份备份，README 自身 SHA 单独核对。

两 manifest 均为 `synthetic_source_service`／新 freeze／app 0.1.0；新 UI 尚未执行。Codex 在又一个隔离源码 Runtime 独立验证实际交接：明文／解密 DB raw SHA `cccf98828f0e47e99fc62b658c14a7e9a6a87b3103228e8b1c89b9e850b48184` 相同，完整／业务和 12 资源指纹匹配；任务 succeeded 2／failed 1／outcome_unknown 1，无 live；缺口令明确拒绝。网络守卫 attempts／主 log 为 0、audit true；A 的 child selftest 单列 1 次刻意拦截。未把 DPAPI／raw DB 放入程序或交接目录。私有证据 `A-build-r03-*`、`B-actual-r03-*`、`codex-actual-r03-*`、`codex-r03-independent-*` 分别保留，不覆盖前轮。

目标运行、冻结 UI 备份／恢复与保护包接续、W1–W8 Word、教师本人确认仍未验；按[唯一下一步入口](../tasks/current.md)和[手册](desktop-windows11-portable-manual.md)继续。
