# D4 E14：整包、集成验证及教师体验包结果

更新：2026-10-28。**原OpenCode r03停写交接时：E14-R01–R06剩余可修项已修复；新候选及精简归档完成自测，等待Codex审核，尚未提交／推送／发布。** 本文保留实现者自测窗口；最终独立范围及Git收口见[核查§6–§7](desktop-game-observation-e14-review.md#6-最终独立结论源码与静态工程通过冻结整体验证受阻)。冻结运行仍受SAC4551阻止，不能由自测／源码／静态结果替代。

证据根：`C:/Users/yw980/AppData/Local/Temp/kgm-observation-e14-20261028-2f5a8ac1`。本片只写 `opencode-evidence/`；`codex-evidence/` 未改写。r01、r02 的包/证据及 r03 首次预构建保留；最终 r03 在独立 `build/desktop-e14-r03`。

## 1. 最新剩余点与修复对照

| 编号 | 修复 | 自测证据 |
| --- | --- | --- |
| E14-R01 | 在原有源码/旧包保护上补充：只读 `--frontend-dir` 不得与 dist/work/spec/package-root 任一实际写入根相交；实际构建前拒绝覆盖已存在的候选包；默认及本轮使用 `build/desktop-e14-r03`，r01/r02 根及包保持。 | `desktop/tests/test_e14_build_guard.py` 25 项通过：仓库根/祖先、r01/r02/manual-ai、源码根、仓库内 hash/freeze、只读前端与 dist/work/spec/package-root 相交、既有候选包，均在 build 调用前拒绝且无写入；`--check-paths` 可无写入探针。 |
| E14-R02 | 第一次 `source_freeze` 移到 Vite 之前，覆盖完整前端构建 → PyInstaller → metadata 链；第二次仍在 metadata 之后。新增调用顺序与“中途源码变化”拒绝回归。 | `r03/build/source-freeze.json`：219 文件，before/after digest 均 `6852ce252ef5c4242478b5a0f0ac539d6517cb2b5793cdfd5bb9e3e8da2fabfb`，`stable=true`；构建后 219/219 当前源仍匹配。顺序测试断言 `freeze_before → frontend → package → metadata → freeze_after`；中途变化测试确认 `stable=false` 且 hash-out 不写。 |
| E14-R03 | r03 包写入真实 UUID `_internal/build_identity.json`（0.1.0、0006），回读校验；`package-info.json` 的 `package` 改为相对值 `KGNext-E14`；Pillow 许可证/插件缺失仍直接失败；打包后清理迁移 `__pycache__`/`.pyc`，避免构建机路径进入便携包。 | build id `0d7e5bef-b44d-4e9b-b593-2d27a9cc1817`；static report 26 项全 true；`no_package_cache_files=true`、`package_info_portable=true`；package-info 记录 `cache_files_pruned=10`。 |
| E14-R04 | r02 已完成的真实 DeepSeek 源码闭环按产品源 hash 不变复用；本轮**不新增真实调用、不重发 unknown**。仅 process 单栏 rewrite 已验，generate 仍为 unknown/无候选。 | r02 `real-ai/summary.json`、`source-hash-comparison.json`、`reopen-check.json`：2 次请求（1 unknown + 1 rewrite succeeded/采用/重开）；5/5 源文件 hash 前后一致；MiMo 未验。 |
| E14-R05 | r02 已通过的迁移专用逐字段/备份/FK/重开及不同园所/空园所窗口证据按产品源 hash 不变复用；本轮不重跑旧库窗口。 | r02 `old-upgrade/out/report.json` 22 项全 true：迁移专用 25 行 0 差异；`source-e14-window/report.json` 17 项全 true，含 `obs_multi_export_schools=true`。 |
| E14-R06 | 结果如实记录 `old-upgrade-probe` 失败根被清理重用偏差；生成 r03 精简便携归档，产品目录仅包文件，README/相对路径清单在外层，不含原路径清单、完整日志、AI/数据库/凭据等私有审计材料；r02 ZIP 不再分发。 | `r03/archive-verify.json` 15 项全 true：解包 190 个产品文件、80,158,627 字节与 manifest 完全一致；`r03/portable-path-scan.json` 35 个文本条目 0 命中、0 缓存条目。 |

## 2. r03 新包与静态同源

构建命令（实际使用）：

```text
desktop/.venv-d1/Scripts/python.exe desktop/build_e14.py \
  --build-root build/desktop-e14-r03 \
  --hash-out .../opencode-evidence/r03/build/package-files.json \
  --source-freeze-out .../opencode-evidence/r03/build/source-freeze.json
```

- 包：`build/desktop-e14-r03/package/KGNext-E14`，190 文件，80,158,627 字节。
- EXE：`KGNext-E14.exe`，16,313,212 字节，SHA-256 `524f9787d1dc8e455e73fdcd88621fa950ac0783fe36bef0d82b94e75b318b28`。
- build id：`0d7e5bef-b44d-4e9b-b593-2d27a9cc1817`；版本 `0.1.0`；数据库 revision `20261025_0006_local_game_observations`。
- 源码冻结：219 文件，before/after 均 `6852ce25...`，`stable=true`；含 builder、宿主、全部 `update_*`、验证脚本、前端源码/配置；不含 `__pycache__`/`.pyc`；构建后 219/219 当前源匹配。
- 包内 `package-files.json` 190/190 匹配，无缺失/多余/不符。
- 静态核验 `r03/package/static-report.json`：26 项全 true。关键项：
  - 仓外中文/空格/`%`/`#` 路径复制；
  - 前端、模板、迁移（排除缓存）、Alembic 与源码一致；
  - 0006、三份观察模板、Pillow 插件/许可证；
  - CArchive `d1_main` 入口结构摘要与源码一致；
  - PYZ 76 个 app/host/update 模块结构摘要全部一致；
  - build identity 存在、可回读、UUID、非源码 ID、版本/0006 正确、与 package-info 一致；
  - `package-info.package="KGNext-E14"`（相对值），包内无 `__pycache__`/`.pyc`。
- 首次 r03 预构建发现迁移 `__pycache__` 会把构建机路径带入包，已保留在 `build/desktop-e14-r03-pre-prune` 与 `opencode-evidence/r03/pre-prune/`；最终 r03 在清理缓存后重建，未覆盖 r01/r02 及其证据。
- r01 包/归档保持：`build/desktop-e14/package/KGNext-E14`（199 文件，EXE `64ef4ad3...`）、`opencode-evidence/dist/KGNext-E14.zip`（`cde01247...`）。r02 包/证据保持：`build/desktop-e14-r02/package/KGNext-E14`（200 文件，EXE `dfcc3850...`）、`opencode-evidence/r02/`。

冻结运行：r01 的 `package/run-report.json` 已记录 `winerror=4551`、`frozen_execution_blocked_4551=true`。r03 按“不再次执行受阻冻结 EXE、不以改名/换目录/新 hash 重试”的要求未启动；因此 r03 冻结冷启动、冻结旧库升级、冻结 WebView2/原生保存、包内真实 AI 仍未验，不能由静态报告或源码窗口代替。

## 3. 源码真实窗口与旧库保持（复用 r02）

r03 未重跑源码窗口/旧库/真实 AI；复用条件已核对：

- r02 source freeze 中 product/resources 组 209 个产品源文件与当前源逐文件 hash 一致（0 变更）。
- r02 与 r03 的前端构建树均为 3 文件且逐字节一致。
- 因此 r02 的源码真实窗口、旧库升级/重开、真实 AI 证据仍适用；不新增真实 AI 调用，不重发 unknown。

### 3.1 空库 E14 窗口（r02）

`r02/source-e14-window/report.json`：exit 0，`ok=true`，17 项检查全 true。包括新建/编辑/保存、历史恢复、冲突后离开、编辑页导出/取消、busy 归零、跨页选集/筛选/手调/混合导出；`obs_multi_export_schools=true`：非空园所 `OBS园所/甲园/乙园` 3 个、空园所 4 份、默认园所 5 份，每份标题按自身已保存字段生成。

### 3.2 旧 0005 合成库升级/重开（r02）

`r02/old-upgrade/out/report.json`：22 项全 true。

- 迁移专用：真实 Alembic 0006（不经应用启动/prompt sync）按主键比较 25 行，0 差异；仅允许 0006 文档化 source 列回填（`profile_id`/`source_kind`/`source_id`/`observation_id`/`source_revision`）。
- 真实窗口冷升级：`window_1` exit 0、`ok=true`；升级到 0006；旧日计划 1、内容 2、AI 任务 1 等旧行逐字段保持；FK 空。
- 备份：`migration-backups/pre-D2-*.sqlite` 1 份，manifest version/sha256 一致；备份逻辑内容与 before 一致。
- runtime 重开：状态 current、revision 0006；计数稳定（计划 1、内容 2、任务 1、观察 26、prompt bundles 9、personal versions 3、heads 3），单条 migration、1 份备份，无重放/重复种子。
- 允许的运行时 prompt sync：现有 D2 行为补齐 observation prompt bundles/heads 并推进 daily head 的 `latest_default_revision`/`updated_at`；旧 daily prompt version 行、旧 bundle 行本身逐字段保持，报告以 `runtime_prompt_sync=true` 明列，与 0006 迁移回填分开。

### 3.3 `old-upgrade-probe` 现场偏差（R06 如实保留）

r02 修正独立旧库探针的 `DatabaseInspection.head_revision` 属性错误后，曾用 `rm -rf` 清理并重用 `opencode-evidence/r02/old-upgrade-probe`。CLI JSONL 中的原失败命令/输出保留，但该目录的首次现场不完整；**不能声称完整保留首次现场，也不能由后续成功倒推恢复**。后续 r02 `old-upgrade` 使用新命名根；r03 未重跑旧库、仅复用 r02 结果；未再删除/覆盖失败材料；本偏差不涉及原体验库、配置或凭据；结构化记录见 `r03/old-upgrade-probe-bias.json`。

## 4. 真实 AI（源码闭环，复用 r02）

使用 R04 指定的只读 G17 DeepSeek 源和 e0607 既有脚本；源路径/凭据路径不进入便携归档，明文不复制、不写日志/包。独立合成根：`opencode-evidence/real-ai/root`。

| 项目 | 结果 |
| --- | --- |
| 源配置 | DeepSeek `deepseek-flash`，config version 1；源 DB hash before/after 均 `d8e87fe2ca84418f607598aa580877df29c1e6ac285c55b19fdf1b85ab3b584c` |
| generate | 1 次 attempt，HTTP 200，`outcome_unknown`/`provider_error`，无候选；**未自动重发** |
| rewrite | 1 次 attempt，HTTP 200，`succeeded`；仅 process 单栏候选 `Wk_yC8E7IL1PHVCi7KRbbA` |
| 采用 | `adopt-rewrite` 成功：`changed=true`、`history_created=true`、target `observation_process`、revision 5、current_version 2 |
| 重开 | `status` 再读：generate `outcome_unknown`、rewrite `succeeded`；`reopen-check.json` 14 项全 true：版本 1 manual / 版本 2 adopt、provenance 指向候选、正文变化且非空、2 次 attempt 均 HTTP 200、0006 单行 |
| 源保护 | 5/5 源文件（DB、WAL、SHM、锁、凭据 blob）大小与 SHA-256 与 Codex 基线一致；`source-hash-comparison.json` 全 match |
| MiMo | 未发现可读 MiMo 应用凭据；真实调用 0 次，未验；未编造账号 |

边界：generate 的 unknown 使生成候选审阅/采用没有真实生成候选；`review` 阶段如实返回 `candidate=null`。真实闭环由 **process 单栏 rewrite** 候选的预览/采用/重开完成；**不能写成 generate 已验**。以上均为源码真实闭环；冻结包内真实 AI 因 4551 未验。本轮未新增调用。

## 5. Word 与容量：明确复用前片

以下证据**复用前片**，r02/r03 均未重新导出、未重新运行 Word COM、未重新跑容量；仅包内模板/源码 hash 与 r03 一致，故可作为同源码/同模板的前片证据，不是 r03 冻结包运行结果。

- Word：`opencode-evidence/word-samples/`（复制自前片 `kgm-observation-export-20261028-7e7fb3c6/opencode-evidence/word-samples-4`），7 份样本覆盖 0/1/2/3/5 图、横竖图、长文、混合类型、缺项/无日期；前片 XML/COM 几何检查与 Word 16.0（16.0.20527）逐页结果保持。
- 容量：`opencode-evidence/capacity/service-capacity.json`、`renderer-capacity.json`（复制自前片），包括 11×3 成功、**16 张 noise 成功产物 33,878,576 字节（>30MiB）**、600 张各异图成功、**33 张 noise 累计 76,599,628 字节触发 413（>64MiB）拒绝**；数字为前片当前开发机合成数据，不是 r02/r03 重跑或运行时承诺。

## 6. A01–A22 证据矩阵（r03 视角）

| A | 结论/证据 |
| --- | --- |
| A01 | r02 空库真实窗口通过新建/资料带入；r03 包静态含当前前端/入口。 |
| A02 | 前片服务/组件边界保持；r02 窗口缺项草稿/保存通过。 |
| A03 | 前片人数/年龄与 Word 字段检查复用；r02 窗口多人字段保存通过。 |
| A04 | r02 窗口同日多份/重开通过；前片 API/并发证据复用。 |
| A05 | r02 旧 0005 合成库升级到 0006，旧日计划/内容/任务逐字段保持；学期/日期窗口流程通过。 |
| A06 | r02 窗口图片上传/重开/历史通过；r03 包内 Pillow 插件/许可静态核验；前片 E03 格式/损坏/容量复用。 |
| A07 | 真实 DeepSeek rewrite 仅 process 单栏候选输出/采用已验（源码）；generate unknown 未生成候选；冻结包真实 AI 未验。 |
| A08 | 前片 E06 图文/IPC/边界/未知不重放证据复用；r03 包静态含 AI 模块；冻结运行未验。 |
| A09 | r02 真实 rewrite 单栏候选预览/采用/原子版本 2 通过；generate 候选未生成。 |
| A10 | 前片组件/DOCX 补写提示检查复用；r02 窗口导出正文无提示/标签。 |
| A11 | r02 窗口保存/冲突/离开/busy 归零通过；前片 IME/故障证据复用。 |
| A12 | r02 窗口历史恢复/旧库重开通过；前片历史节点证据复用。 |
| A13 | r02 旧库升级/重开与 runtime 重开通过；前片整份恢复事务/材料证据复用。 |
| A14 | 真实 process 单栏 rewrite 在途/采用/重开已验（源码）；generate unknown 保留；冻结包 AI 未验。 |
| A15 | 前片服务／组件的空记录与坏图拒绝证据、7份可导出Word的缺项／无图等样本分别复用；r03包模板静态同源，不把拒绝导出的场景写成已经生成Word。 |
| A16 | r02 窗口固定导出/取消/busy 通过；冻结包原生导出未验。 |
| A17 | r02 窗口跨页选集/筛选/手调/混合导出通过；不同园所/空园所标题独立核对通过。 |
| A18 | 前片 7 份 Word A4/8 行/字体/五领域/Word COM 逐页复用；r03 未重跑 Word。 |
| A19 | 前片 0/1/2/3/5 图、横竖、长文、混合分页复用；r03 未重跑 Word。 |
| A20 | 前片 Windows 原生取消/失败/重试/成功复用；r03 冻结包原生保存未验。 |
| A21 | r02 旧库迁移专用 25 行逐字段 0 差异、备份/FK/重开通过；r02 A21 诊断限定扫描 41 文件/0 命中；r03 包内 0006 静态同源、便携归档路径扫描 0 命中。 |
| A22 | 前片独立全 local/桌面/HTTP/窗口证据复用；r03 包静态同源；冻结包全回归未执行。 |

## 7. r03 精简便携归档

`opencode-evidence/r03/dist/KGNext-E14-r03.zip`：**43,645,128 字节，SHA-256 `d603aec85c391765c6a4907ce9392712cc57444578a09849a81e2dd4cf57cdf6`**。

归档布局：

```text
KGNext-E14/                产品目录，仅包文件（190 个）
README-E14-r03.txt         便携说明（外层）
package-files.json         产品文件相对路径/字节/SHA-256（外层）
SHA256SUMS.txt             产品文件/README/manifest 相对校验和（外层）
```

- 产品目录不含 `EVIDENCE/`、原路径清单、完整日志、AI/数据库/凭据等私有审计材料。
- `package-info.json` 的 `package` 为相对值 `KGNext-E14`；包内无 `__pycache__`/`.pyc`。
- `r03/archive-verify.json` 15 项全 true：解包产品文件集/字节与 `package-files.json` 完全一致（190 文件、80,158,627 字节），无缺失/多余/不符；校验和覆盖产品文件、README、manifest。
- `r03/portable-path-scan.json`：35 个文本条目、0 路径/私有材料命中、0 缓存条目。
- **r02 ZIP 保留但不再分发**：其 `EVIDENCE/real-ai-source-hash-comparison.json` 含原 G17 受保护文件绝对路径；该私有审计材料留在本机 `r02/real-ai/`，不进入 r03 便携归档。r02 归档未上传、未修改；结构化记录见 `r03/r02-zip-private-path-defect.json`。
- r01 归档 `opencode-evidence/dist/KGNext-E14.zip` 保持，不覆盖。
- 未上传、未签名、未进入公共发行源、未创建更新计划。

## 8. A21 扫描范围与 Bypass 事实

A21 限定扫描（r02，`r02/a21-diagnostic-scan.json`）：

- 范围：`r02/package/`、`r02/build/`、`r02/source-e14-window/`、`r02/old-upgrade/out/`、`r02/real-ai/` 下的 `.json/.log/.txt/.err`（单文件 ≤5MiB），加 r02 `package-info.json`、`build_identity.json`、`dist/README-E14-r02.txt`；排除刻意记录受保护路径 hash 的 `source-hash-comparison.json`/`source-hashes-after*.json`。
- 模式：`KGNext-G17-20261022`、`KindergartenManager\credentials`、`KindergartenManager/credentials`、`.dpapi`、`sk-`、`Bearer `、`Authorization`、`api_key`、`ciphertext`。
- 结果：41 文件、292,960 字节、0 命中。该结果是**限定诊断扫描**，不是通用秘密/个人信息审计。

r03 便携归档另做 `portable-path-scan.json`：35 个文本条目，检查 `C:\Users`/`yw980`/`KGNext-G17`/`.dpapi`/`EVIDENCE/`/`source-hash`/`real-ai/`/`old-upgrade/`/`source-freeze` 等，0 命中；无 `__pycache__`/`.pyc` 条目。

Bypass 事实：

- r01 阶段曾调用 PowerShell Bypass 进行 Word 辅助自测；该事实保留，相关结果不作为独立通过。
- r02/r03 未再调用 Bypass、未修改执行策略；Word 证据为前片复用，未重新运行。当前普通 PowerShell 受 Restricted 策略拒绝，未用绕过方式继续。

## 9. 未验边界与交接

- 冻结包冷启动、冻结旧库升级、冻结 WebView2/原生保存、包内真实 AI：本机 4551 未验；r03 未重试。若需在正常执行策略环境运行，应由 Codex/授权环境完成，不修改系统策略、不伪造签名。
- 真实 AI：复用 r02 源码 DeepSeek 2 次（1 unknown 不重发 + 1 process 单栏 rewrite 成功/采用/重开）；本轮 0 次新调用；MiMo 无凭据未验；generate 候选未生成。
- Word/容量为前片复用，r03 未重跑；冻结包 Word/原生 Save As 未验。
- 教师体验、完整 A01–A22 整体、签名、公共发行、安装更新、WebDAV、跨设备、Win10/WPS/干净机器/其他 DPI 未验。
- 未改 `ARCHITECTURE.md`、旧远程资源、原体验库、配置/凭据、OneDrive 原件、旧包；未安装/升级依赖、Skill/MCP；未扩修 D3/U2。
- 未提交 Git；等待 Codex 独立审核。通过及逐文件 Git 白名单前不提交、不发布。

已停写，等待 Codex 独立审核。
