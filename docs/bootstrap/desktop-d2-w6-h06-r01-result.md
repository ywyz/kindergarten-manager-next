# D2 W6 H06-R01 候选编辑后按钮锁死：定点修复与自测结果（OpenCode）

更新：2026-10-19。本文记录 H06-R01（候选编辑后预览／取消按钮被 dirty 误禁用，导致无法比较、取消或正常退出）的定点修复、失败回归证据、全自动自测、同源与旧包核对，以及新完整人工包的**真实窗口 DOM** 闭环与可退出路径。供 Codex 独立复核。本文不改 Codex review/current/人工记录/AGENTS/规格。

**未启动正式人工会话；原人工窗口 PID19256／controller75749 与根 `build/desktop-d2/manual-ai-human-20261019-200255` 未被触碰。** 未调用真实 AI、未 WebDAV、未安装升级、未发布、未 commit/push。

## 1. 缺陷、根因与修复

- 现象（用户截图＋Codex 实际 UI 复核）：拆分候选中把过程第三行改为“三、比较（教师确认）”后，取消编辑／预览比较／采用按钮全部禁用。
- 根因：`CandidatePreview.vue` 用 `blocking = dirty || adopting || pending adopt` 同时充当“离开保护”和“按钮禁用”，`dirty` 使操作自锁。
- 修复：新增 `operationBlocked = previewing || adopting || pendingAdopt !== null`，仅用于按钮：
  - 取消本次候选编辑：`disabled || operationBlocked`（dirty 时可用；明确恢复原候选）；
  - 预览比较：`disabled || !editable || operationBlocked`（dirty 时可用）；
  - 采用并保存：`disabled || !editable || !preview || operationBlocked`（仍需已查看比较）；
  - `cancelEdit` 内部入口在 `previewing`／`adopting`／`pendingAdopt` 时均拒绝（保留 pending 采用原提示）。
- **未放宽**：`blocking`（dirty → 离开／关窗保护）、精确 preview token、原子采用、失联采用只读查询、未编辑可直接关闭等规则全部保持。

## 2. 失败回归（旧代码真实失败，先于修复）

新增的**按钮层**回归使用 Vue 真实模板 + 内存 renderer + Element Plus stub（脚本 setup 直调测试保留不动）。在旧代码上实际失败：

```
AssertionError [ERR_ASSERTION]: cancel must stay enabled while dirty
  actual true, expected false
  at testCandidateDomDirtyKeepsCompareAndCancelEnabled
```

- 有效产品失败日志：`%TEMP%/opencode/h06_r01_failing_regression_valid.log`（exit 1；同名 `h06_r01_failing_regression.log` 为其副本）。
- **需区分的初次 selector 失败（harness 自身问题，非产品缺陷）**：首跑时 `byD1()` 命中 dialog（与预览按钮同用 `data-d1="candidate-preview"`），断言读到 `undefined` 而非 `false`。这是选择器未限定 `tag=button` 造成的 harness 误失败，之后把按钮选择器限定为 `button[data-d1=...]` 并严格要求 `.disabled is False`；该次异常的 stdout 未单独留存文件（已在同一断言处被后续有效失败替换）。两者不混为一谈：保留的 `_valid.log` 是**旧代码真实按钮禁用**的产品失败。
- 覆盖：拆分编辑→比较→按所见 token 采用；编辑→明确取消恢复原候选且不写正文；适龄过程编辑可比较；其他活动内容＋板块勾选可比较；dirty 仍阻止离开；preview 进行中禁止冲突取消／重复比较（内部入口亦拒绝）；adopt 进行中／结果不明仍保护并保留回执查询。

## 3. 实际文件（SHA256 前 16）

| SHA256 | 文件 | 说明 |
| --- | --- | --- |
| `875f3c1c51e58cbb` | `frontend/src/d1/views/CandidatePreview.vue` | 分离 `operationBlocked`（按钮）与 `blocking`（离开）；`cancelEdit` 也在比较中进行时拒绝 |
| `ce92a37a9e360fcc` | `frontend/src/d1/d1.w5.test.mjs` | 8 项按钮级 DOM 回归（含失败回归） |
| `bf2535349226c7eb` | `desktop/d2_manual_ai_main.py` | 新增 `--dom-check`：仅验证模式，作用域限定可见候选 dialog、原生输入事件、`button.disabled`／`.click`、候选 X 关闭拦截、宿主关闭拦截、原生取消、干净退出 |
| `f60d64534b47eb5f` | `desktop/verify_d2_manual_ai.py` | `--mode dom`（有限等待同 smoke）、`--frontend-dir` 显式核对新前端、回读克隆库核对采用正文／基准 |
| `bfba71c78b87ce7c` | `desktop/build_d2_manual_ai.py` | `--frontend-dir` 显式选择要打包的前端；`--dist-root` 解析为绝对路径；仍拒绝写入原 182 文件包目录 |
| `ed4c3da99aff4c27` | `desktop/tests/test_d2_manual_ai.py` | 28 项入口／控制器自测（未改） |

产物（独立目录，不覆盖原包）：
- 新前端：`build/desktop-d2-manual-ai-h06-r01/frontend`，清单 SHA-256 `396abc67f6f9a5490c402326104ab38de7d71b3a3705015202f11e3d87b9bed9`（3 文件）。
- 新完整包：`build/desktop-d2-manual-ai-h06-r01/package/KGNext-D2ManualAI/`，
  EXE SHA-256 `209dedcd5dfc4c8995478fc36146ae744ee653570ea318a54b25817b73a56c1b`（15,066,101 字节），182 文件，包清单 SHA-256 `44e58c4e0f1635d1d69e530f32bd6e2a4c4be4c301b1393c9c8f8b5a3add6260`。

## 4. 自测命令与退出码

日志在 `%TEMP%/opencode/`。所有自动验证仅独立合成根／LOCALAPPDATA 与 `APP_DISABLE_DOTENV=1`。

| 验证 | 命令 | 实际退出码 | 证据 |
| --- | --- | --- | --- |
| 失败按钮回归（旧码） | `node src/d1/d1.w5.test.mjs` | 1 | `h06_r01_failing_regression.log` |
| 修复后组件回归 | `node src/d1/d1.w5.test.mjs` | 0（`OK 81`，含 8 项新增） | `h06_r01_w5.log` |
| 纯逻辑／D1 组件 | `d1.test.mjs` / `d1.components.test.mjs` | 0 / 0 | `h06_r01_d1.log`、`h06_r01_comp.log` |
| typecheck | `vue-tsc --noEmit` | 0 | `h06_r01_typecheck.log` |
| 桌面全量 | `pytest tests` | 0（196 passed，2 条既有第三方弃用警告） | `h06_r01_desktop_pytest.log` |
| 新前端构建 | 本地 Vite `--outDir .../h06-r01/frontend` | 0 | `h06_r01_frontend_build.log` |
| 新包构建 | `build_d2_manual_ai.py --dist-root … --frontend-dir …` | 0 | `h06_r01_package_build.log` |
| 同源／旧包／新前端资源 | `verify_d2_manual_ai.py --fingerprint-package --frontend-dir …` | 0 | `h06_r01_fingerprint.json` |
| 新包真实窗口 DOM＋退出 | `verify_d2_manual_ai.py --mode dom --package-dir … --dom-date 2026-10-20` | 0（全部检查 True） | `h06_r01_dom.json`、`h06_r01_dom.log` |

第一次包构建因相对 `--dist-root` 被 PyInstaller 解析到仓外而失败，已修复为绝对路径并保留失败日志（`h06_r01_package_build.log` 首次运行）。

## 5. 同源、资源与原包不变

- 真实归档：旧包 54 个生产模块（`app`、`app.*`、`d0_*`、`d1_*`、`d2_same_origin`）与新包逐项一致，`old_only=[]`；新入口与旧真正入口 `d1_main` 均与源码一致。
- 新包前端资源与 `build/desktop-d2-manual-ai-h06-r01/frontend` 逐文件一致；Word 模板、`migrations_local`、`alembic-local.ini` 与源码一致。
- 原生产包只读核对不变：182 文件、清单 `84fbb22f66f14fbbffc5c6fe4c63810855c0fbbbc68571c608ff902f285b1f1d`、EXE `56346c0ac1d874bbf00e947739a40c005f4a2a611b20d6fabf1a7d35a89fafb2`。
- 旧人工包 `build/desktop-d2-manual-ai/package`（EXE `18915b7b…`）与用户原窗口未改动。

## 6. 新包真实窗口 DOM 闭环与可退出路径（仅合成根）

`--mode dom` 在全新克隆根 `%TEMP%/opencode/h06-r01-dom-session` 上运行新 EXE（WebView2、本机 API、受控 loopback TLS、真实 spawn/Job），实际 DOM 事件与原生按钮：

- 新建 2026-10-20 计划并保存原文；真实触发拆分 → 打开该次**新**候选（不复用旧历史候选）。
- 在**可见候选 dialog 内**用真实 textarea 输入事件把过程改为 `一、导入\n二、观察\n三、比较（教师确认）`；断言候选 `dirty` 且正文 `dirty=false`、正文版本不变。
- `button[data-d1="candidate-preview"].disabled is False` → `.click()` → 出现比较；`button[data-d1="candidate-adopt"].disabled is False` → `.click()` → 采用成功。
- 回读克隆 SQLite（`mode=ro`）：正文过程恰为教师修改的三行；`split_baseline.group_activity_process` 恰为**未经修改的原三行**，且与正文不同（标红基准正确）；比较／采用不额外发 AI（provider split=1、adapt=0、other=0）。
- 取消路径：重开候选、原生输入、点取消 → 候选关闭，正文版本不再增加（`version_after_cancel == version_after_adopt`）。
- 退出路径：重开候选、编辑 dirty → 点候选真实 X（`.el-dialog__headerbtn`）被拦截并保留文字；宿主关闭意图 `window.destroy()` 被草稿拦截，窗口仍在、`closeState().locked` 解析后严格为 `false`（无遗留 frozen/locked）；点原生取消关闭候选；随后宿主正常关闭，入口 `worker_exit_confirmed=true`、`server_stopped=true`、`runtime_lock_released=true`、provider 监听收口，实际 exit 0（约 11.4 秒）。

## 7. 未验边界（不得写成通过）

- 正式人工会话未由本次启动；用户后续用新克隆根手动体验（原现场保留）。
- 未调用真实供应商；受控 TLS 只证协议／状态与候选可达；AI 采用后的 Word 导出仍为用户后续人工步骤。
- 未执行真实系统睡眠、真实在途关闭（`control/next.txt` 的 hold/release 已就绪）与 Word 逐页；干净机器、Win10、WPS、其他 DPI/多显示器及发行再现性仍未验。
- 快速组件回归是 Vue 真实模板＋内存 renderer＋Element Plus stub，**不是浏览器 DOM**；浏览器／WebView2 级证据来自第 6 节新包真实窗口。

## 8. 状态声明

实现、测试、构建与验证脚本写入已停止（仅本文档）。原人工现场未被触碰。若需修复，交回同一 OpenCode 会话定点处理。本文件不代表 Codex 通过、W6 整体通过、真实 AI 兼容或发行通过。
