# D2 W6 本机合成 AI 人工验收启动器：实现与自测结果（OpenCode）

更新：2026-10-19。本文件记录 W6 人工验收所需的**独立**本机合成 AI 启动器/控制器/打包支持及 **OpenCode 自测**，供 Codex 独立核查。原 W6 工程结论、用户已通过的人工项与失败证据保持不变；本文件不改 Codex review/current/AGENTS/产品规格。

**尚未启动正式人工会话**；用户与 Codex 核查后再启动。真实 AI、WebDAV、远程修改、发布、commit/push 均未执行。

## 1. 范围与边界

- 只新增独立入口/控制器/构建/测试；**未修改**既有 `backend`、`frontend`、`desktop/d1_main.py`、`d1_server`、`d1_host_api` 及原 `build_d2.py`（字节不变）。
- 复用已核查的 `d1_main.build_runtime`、关闭/释放协调、真实执行器/spawn/Job 与既有前端资源；不调用 `d1_main.run_selftest`。
- 原生产包 `build/desktop-d2/package/KGNext-D2Verify`（EXE `56346c0a…`，182 文件，清单 `84fbb22f…`）只读核对，未覆盖/重建；原人工验收根 `build/desktop-d2/manual-acceptance-20261019-190131` 仅以 SQLite `mode=ro` + backup API 读取，未写入；用户当前窗口未被触碰。
- 所有自动验证只用独立合成根/LOCALAPPDATA 与显式 `APP_DISABLE_DOTENV=1`。

## 2. 新增文件（SHA256 前 16）

| SHA256 | 文件 | 说明 |
| --- | --- | --- |
| `d52707bb9fa90b2e` | `desktop/d2_manual_ai_main.py` | 人工窗口入口：专用 phase 参数复用 `build_runtime`；人类模式无自动操作/无 watchdog；显式合成根/源根/禁止根/loopback provider 校验；统一清理与真实状态报告；有限 smoke 硬边界 |
| `131e18048fc3e095` | `desktop/verify_d2_manual_ai.py` | 控制器：只读 backup 克隆、受控 TLS 供应商与 hold/release、合成配置准备、启动/记录/收口；同源与旧包归档比对 |
| `56016788ecb777dc` | `desktop/build_d2_manual_ai.py` | 独立人工包构建（新目录/work/spec；复用既有前端/模板/迁移；不联网/不安装；拒绝写入原包目录） |
| `ed4c3da99aff4c27` | `desktop/tests/test_d2_manual_ai.py` | 入口/控制器/provider/clone 自测（28 项） |

产物：`build/desktop-d2-manual-ai/package/KGNext-D2ManualAI/`
- EXE SHA-256：`18915b7b7da778a7d467ce03fef08fb89e45b878854f1f714cc126bc1fdc9b75`（15,061,746 字节）
- 包内文件 182；包清单 SHA-256：`2259bc1724efafb0dfc4b128171dc6c67e7750497f703bb8244d82456367813b`

## 3. 工作方式

1. 控制器在新独立会话根（默认 `build/desktop-d2/manual-ai-<UTC>-<rand>`）中，先完成**全部守卫**（既存目录拒绝、教师根/原人工根/克隆源根不重叠），再 `mkdir`。
2. 用 `sqlite3` 只读连接（`readonly_sqlite_uri`，正确处理中文/空格/`#`/`%`）+ `backup` API 制作一致性克隆；断言 `integrity_check`、`foreign_key_check` 与单 head。
3. 启动受控 loopback TLS（本机 CA、`api.example.com`、正常证书/主机名校验），记录三类请求计数/时间/类型；日志只含 `has_authorization` 布尔，不记录头值或密钥。
4. 用正常服务在克隆副本上准备合成 AI 配置（明确是准备，不发起/采用任务），凭据根独立。
5. 启动独立人工入口（源码或新包 EXE）：普通交互窗口，标题 `W6本机合成人工验收`；无自动点按钮/采用/导出/关窗；人类模式无 watchdog。
6. 控制根 `control/next.txt` 写 `hold` 挂起下一次请求、改回 `release` 释放（供后续在途关闭/真实睡眠）；`stop` 会立即解除挂起。
7. 退出时统一清理：仅当 **worker 与本地服务都确认停止** 才释放 runtime 锁；未确认则保留所有权并如实报告；写 `logs/entry-exit.json`、`ready.json`、`result.json`。

安全：入口在任何 `LocalRuntime` 前校验显式 `--manual-root`、`<root>/data`、控制器标记（含 source_root/source_data 且不重叠）、隔离 LOCALAPPDATA、显式 `--forbid-root`、provider 仅 `127.0.0.1` + CA。普通生产入口仍拒绝合成注入。

## 4. 自测命令与实际退出码

日志/报告在 `%TEMP%/opencode/`（OpenCode 自测根）。

| 验证 | 命令 | 实际退出码 | 证据 |
| --- | --- | --- | --- |
| 入口/控制器单测 | `pytest tests/test_d2_manual_ai.py` | 0（28 passed） | `manual_ai_test5.log` |
| 桌面全量 | `pytest tests` | 0（196 passed，2 条既有第三方弃用警告） | `manual_ai_desktop_pytest.log` |
| 独立人工包构建 | `python build_d2_manual_ai.py --hash-out …` | 0 | `kgm-manual-ai-build2.log`、`manual-ai-pkg-hashes.json` |
| 同源/旧包归档核验 | `python verify_d2_manual_ai.py --fingerprint-package --package-dir …` | 0 | `manual_ai_fingerprint2.json`、`manual_ai_fingerprint2.log` |
| 源码 smoke | `--mode smoke --clone-from-data <合成源>` | 0 | `manual_ai_smoke_source.json`、`manual_ai_smoke_source.log` |
| 新包 smoke | 同上 + `--package-dir …KGNext-D2ManualAI` | 0 | `manual_ai_smoke_package.json`、`manual_ai_smoke_package.log` |

## 5. 同源、资源与原包不变

- 从**真实 EXE 归档**（`CArchiveReader` 入口 + PYZ `ZlibArchiveReader`）读取生产模块：旧包 54 项（`app`、`app.*`、`d0_*`、`d1_*`、`d2_same_origin`），新包与源码逐项一致；`old_only=[]`、`old_vs_new` 共享 54 项零差异。
- 新入口 `d2_manual_ai_main` 以 **CArchive 实际 code** 与源码比较一致；旧真正入口 `d1_main` 与新包导入模块、源码三者一致。
- 新包前端 assets、Word 模板、`migrations_local`、`alembic-local.ini` 与既有构建资源逐文件 SHA-256 一致。
- 原生产包只读核对：182 文件、清单 `84fbb22f66f14fbbffc5c6fe4c63810855c0fbbbc68571c608ff902f285b1f1d`、EXE `56346c0ac1d874bbf00e947739a40c005f4a2a611b20d6fabf1a7d35a89fafb2`，与交付基线一致（未改动）。

## 6. Smoke 实测（仅自测，不是人工验收）

- 源码 smoke（根 `%TEMP%/opencode/manual-ai-smoke-source-session`）：受控 provider 收到 split=1、adapt=1、other=1；三类任务均 `succeeded` 且有候选；`worker_exit_confirmed=true`、`server_stopped=true`、`runtime_lock_released=true`、`provider_listener_stopped=true`；耗时约 12.1 秒。
- 新包 smoke（根 `%TEMP%/opencode/manual-ai-smoke-package-session`）：同一克隆源与同一行为；EXE `18915b7b…`；计数 1/1/1、三类候选、worker/服务/锁/监听收口均为 true；约 13.1 秒。
- smoke 只触发三类任务并记录候选，**不采用、不导出、不关窗**（除 smoke 自身退出）；正式人工会话未被消费。

## 7. 未验边界（不得写成通过）

- **正式人工会话尚未启动**；三类触发、候选编辑采用、在途关闭、真实睡眠与“AI 采用后 Word 导出”均由用户后续真实操作，未由本自测代替。
- 未调用真实供应商（G17）；受控 TLS 只证协议/状态与候选可达，不证实际 AI 质量或真实兼容。
- smoke 未执行真实系统睡眠、在途关闭或原生 Word 导出；`control/next.txt` 的 hold/release 仅为后续人工步骤准备。
- 新人工包未在仓外中文/空格/`%`/`#` 路径做专项启动（该证据见原生产包 G16）；干净机器、Win10、WPS、其他 DPI/多显示器及发行再现性仍未验。
- 用户原窗口、原人工验收根、原生产包未被本自测改写；不改写为 G13/G14/G18 或 D2 产品通过。

## 8. 状态声明

实现、测试、构建与验证脚本写入已停止；等待 Codex 独立核查后再由用户启动正式人工会话。若需修复，交回同一 OpenCode 会话定点处理。本文件不代表 Codex 通过、W6 整体通过或真实 AI/发行通过。
