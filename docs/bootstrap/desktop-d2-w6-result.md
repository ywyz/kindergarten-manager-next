# D2 W6 导出、打包及验收交接实现结果（OpenCode）

更新：2026-10-19。本文件记录 D2 W6「导出、打包及验收交接」在 **OpenCode 自测**范围内的实现、偏差、命令、完整日志与实际退出码，以及最终 D2 冻结包的身份和未验边界，供 Codex 独立核查。W1–W5 既有工程结论保持。

**本文件不代表 Codex 核查通过、W6 整体通过或 D2 产品/发行验收。** 独立核查与通过结论见 Codex 的 `desktop-d2-w6-review.md`（本文件不改动该 review，也不改动 `docs/tasks/current.md`、`AGENTS.md`、规格或 README）。

## 1. 授权、范围与边界

- 用户明确授权继续 W6，由 OpenCode 使用 Go 套餐 DeepSeek V4.1 Flash 实现，Codex 独立核查并交回修复；本轮仅 W6。
- 当前分支 `codex/desktop-v2-foundation`，未 commit/push；保留全部既有未提交/未跟踪内容、原教师体验库、原包与历史失败证据。
- 未调用应用真实 AI/供应商、未 WebDAV、未发布、未安装或升级依赖、未改 `0001–0004` 历史迁移、未改 `ARCHITECTURE.md`。
- 自动验证仅使用独立合成数据根与独立凭据根，显式 `APP_DISABLE_DOTENV=1`；未对默认教师数据根执行任何自动迁移或写入。
- 未创建其他实现者或子代理。
- 源码写入已停止（本文件除外）；之后不再改实现、测试、构建或验证脚本。

## 2. 实际改动文件（SHA256 前 16，最终值）

桌面宿主与验证：

| SHA256 | 文件 | 说明 |
| --- | --- | --- |
| `87e39a3e917a880a` | `desktop/d1_main.py` | G15 执行器启动失败降级、未确认 worker 不释放运行锁；`w6-ui`/`w6-ui-verify`/`g15-noexec`/`w6-resources` 专用相位；专用入口校验；资源探针（DPAPI/TLS/Job/spawn/同源/PE 子系统） |
| `c05a5e7560453b01` | `desktop/d2_same_origin.py` | 同源结构指纹：仅忽略 `co_filename`，行号/常量/元数据全保留；`dont_inherit` 编译；集合常量顺序无关 |
| `a44dbfe09eedad92` | `desktop/build_d2.py` | 完整 D2 onedir 包构建；**不执行 npm ci/npx**，直接调用本地 Vite；旧 D0/D1/W3 包输出不覆盖 |
| `8fff8df80188655a` | `desktop/verify_d2_w6_common.py` | G14/G15 可复用窗口驱动、固定期望集合、凭据精确损坏、包环境清理 |
| `a403cb1b75c093a4` | `desktop/verify_d2_w6_window.py` | 源码窗口验证器（G14 闭环/重启 + G15 四分支） |
| `6c11d24a6b06d5d4` | `desktop/verify_d2_w6_package.py` | 完整包验证器（特殊路径、同源、资源、G14/G15、w5-ui、包清单） |
| `d5416e3de8e8a40a` | `desktop/tests/test_d2_w6_degrade_host.py` | 宿主降级与专用入口 spy 单元测试（11 项） |

后端（本轮唯一后端改动，已在 Codex 后端 477 项独立回归前完成）：

| SHA256 | 文件 | 说明 |
| --- | --- | --- |
| `2e04c0be4e28a94a` | `backend/app/local/ai_executor.py` | 验证专用 `thread_factory` 缝；`_thread` 改为 `Thread.start()` 成功后才赋值，真实 `Thread.start` 失败可安全确认零 worker |
| `abf8721c8c5fcfc8` | `backend/tests/local/test_d2_w6_export_closure.py` | G14 闭环、冷重启、单日/合并 DOCX 红线断言 |
| `0ba59dd919309bb7` | `backend/tests/local/test_d2_w6_degrade.py` | G15 四分支（真实闭端口连接失败、冷重启读回/导出） |

前端（R08 定点修复，已在 Codex 前端独立回归前完成）：

| SHA256 | 文件 | 说明 |
| --- | --- | --- |
| `7d9bb4ad05310454` | `frontend/src/d1/operations.ts` | `AI_EXECUTOR_UNAVAILABLE` 为确定的前置拒绝；普通 503/丢包/截断 202 仍为未知 |
| `c2ced7205cdf0ee2` | `frontend/src/d1/views/AiTaskPanel.vue` | 首次拒绝不建 pending；旧 unknown 同 key 重传拒绝仍保留原 key/body 并提示原结果待核对 |
| `3c28c724cdd7e45b` | `frontend/src/d1/d1.w5.test.mjs` | 首次拒绝、旧 pending 保留、回执恢复等组件断言（D2 组件增至 73 项） |

## 3. 对照规格的偏差与实现说明

1. **G15 执行器降级（必要宿主修复）**：`AiExecutor` 导入/构造/启动失败不再杀整应用；手工读/编辑/保存/重启/原生导出保持可用，AI 端点返回 503 `AI_EXECUTOR_UNAVAILABLE`。仅当**确认零 worker** 时才降级；未确认退出的 worker 保留执行器与运行锁并拒绝启动（不吞异常、不释放锁）。`start()` 返回 False（冷启动恢复失败）时保留执行器（`is_runnable()` False），关闭协调仍持有它。
2. **真实 `Thread.start` 失败**：`task._thread` 在 `start()` 成功后才赋值；验证用工厂构造真实 `threading.Thread`（二次启动抛标准库 `RuntimeError`）证明该分支可安全降级。
3. **R08 前端语义**：带明确 `AI_EXECUTOR_UNAVAILABLE` 的 503 首次出现按确定未登记显示并解除 busy；已存在未决的同 key 重传即使被确定拒绝也不清除原 pending（peek 非写屏障），保留原 key/body 并提示待核对；回执 200 后恢复。普通 5xx/网络丢包/截断 202 仍未知。
4. **R09 专用入口**：所有 W6 专用相位（含 `w5-ui`、`w6-ui-verify`、`w6-resources`）在任何 `LocalRuntime` 构造/prepare 前强制要求显式 `--data`；provider-required 相位还须提供端口；`w6-ui-verify` 不接受私网解析注入；执行器失败注入仅限 `g15-noexec`。普通启动带注入一律拒绝。
5. **G14 判定性样本**：拆分模型过程 `一、导入/二、观察/三、比较`；适龄 `…（适龄版）`；教师最终过程保留未改段落并含替换与新增（`…（教师改为细致观察）` + `四、教师新增段落`）。Word 输出可区分“未改段落不红 / 替换与新增红”，且预览/适龄中间值不得泄漏。
6. **构建不联网**：`build_d2.py` 直接调用 `frontend/node_modules/vite` 的本地 CLI；缺失即失败，不执行 `npm ci`/`npx` 网络回退。本轮最终包前端为重建产物。
7. **同源比较**：结构签名（仅忽略 `co_filename`）；源码编译 `dont_inherit=True` 且用当前优化级别；集合常量规范化避免哈希随机误报；冻结入口通过 PyInstaller `CArchiveReader` 提取真实入口 code 与源码严格比较，不用“额外副本/`__main__` 读取器”冒充。
8. **无控制台证据**：以 PE OptionalHeader `Subsystem==2`（GUI）与真实 `GetConsoleWindow()==0` 证明；启动期 stdio 原值仅作元数据，不因其被重定向而改写为“无控制台”。
9. **资源相位重跑**：每次启动使用新的 `request_id`，因此第二次资源启动确实新建任务并再次 spawn/Job，不复用原成功回执；两次 migration 仍单 head。
10. **G14 provider 计数取阶段增量**：G14 阶段 split=1、adapt=1、other=0；资源探针发送单列。

## 4. 验证环境与命令（OpenCode 自测）

- 解释器：`desktop/.venv-d1/Scripts/python.exe`（CPython 3.14.7，Windows x64，标准 GIL）；Node v26.10.0，沿用既有 `frontend/node_modules`。
- 证据目录：`%TEMP%/opencode/kgm-d2-w6-opencode`（含完整日志与报告，未覆盖旧失败材料）。Codex 独立证据根另为 `%TEMP%/kgm-d2-w6-codex-20261019-123909` 与最终包 `%TEMP%/opencode/kgm-d2-w6-pkg-b5f78c17`。
- 所有命令显式 `APP_DISABLE_DOTENV=1`；前端/后端/桌面/包验证均用独立 `LOCALAPPDATA` 与合成根。

| 验证 | 命令 | 实际退出码 | 日志/报告 |
| --- | --- | --- | --- |
| G14 闭环（服务层） | `python -m unittest tests.local.test_d2_w6_export_closure` | 0（3 项） | `backend_w6_final.log` |
| G15 四分支（服务层） | `python -m unittest tests.local.test_d2_w6_degrade` | 0（4 项，含真实闭端口失败；合计 7 项/50.504 秒） | `backend_w6_final.log` |
| 桌面宿主单元 | `python -m pytest tests -q` | 0（168 passed，2 条既有第三方弃用警告） | `desktop_pytest.log` |
| 前端 typecheck | `vue-tsc --noEmit` | 0 | `typecheck2.log` |
| 前端回归 | `d1.test.mjs` / `d1.components.test.mjs` / `d1.w5.test.mjs` | 均 0（D2 组件 73 项） | `fe_d1.log`、`fe_comp.log`、`fe_w5_run3.log` |
| D2 前端重建 | 本地 Vite `build --config vite.d1.config.ts` | 0 | `w6_frontend_build3.log` |
| 完整包构建 | `python build_d2.py --hash-out …` | 0 | `build_d2_final.log`、`package_hashes_final.json` |
| 源码窗口验证 | `python verify_d2_w6_window.py --out …` | 0（75/75，missing/failed/extra 空） | `source_window_report_final.json`、`source_window_final.log` |
| 完整包验证 | `python verify_d2_w6_package.py --out …` | 0（130/130，missing/failed/extra 空） | `package_report_final.json`、`package_final.log` |

## 5. G14：拆分→预览改过程→采用→适龄→教师手改→保存→重启→单日/合并 DOCX

源码窗口（最终源码，根 `%TEMP%/kgm-d2-w6-window-54e32afc`，75 项全为严格 True）：

- 触发拆分先保存正文；候选预览改过程后采用；`split_baseline` 为**模型**过程，不是预览改后值。
- 适龄采用后仅过程变化、基准不变；教师经真实表单再改过程并保存后基准仍不变。
- 第二进程 `w6-ui-verify` 冷启动读回保存的过程与基准并再次原生导出。
- 受控 provider 阶段增量：split=1、adapt=1、other=0；重启阶段无新增 provider 请求。
- 单日 DOCX（真实原生另存为到合成目录）：未改段落 `一、导入`、`三、比较` 非红；`教师改为细致观察`、`教师新增段落` 红；`（预览版）`/`（适龄版）` 未泄漏。
- 合并 DOCX：两份标题、`9 月 15 日`/`9 月 16 日`、正文两份、页分隔均断言通过。
- 无基准的手工计划导出带 `no_split_baseline` 警告；纯删除不显示、纯移动与格式变化不红、替换与新增红（服务层 `test_redline_rules_pure_delete_move_format`）。

完整包内（EXE，根 `%TEMP%/opencode/kgm-d2-w6-pkg-6de383db`，Codex 独立最终包 `kgm-d2-w6-pkg-b5f78c17`）：同一 `w6-ui` + `w6-ui-verify` 流程在冻结包中全部通过，包内前端资源（未传 `--frontend`）。

## 6. G15：四类无 AI 降级

服务层（真实 HTTP，含冷重启读回与导出）：

1. 未配置 AI：`AI_NOT_CONFIGURED`，零任务；读/编辑/保存/冷重启/导出可用；配置可读。
2. 凭据不可解密：真实 DPAPI 写入后损坏该分支密文，GET `ready=false / CREDENTIAL_UNAVAILABLE`，无任务；手工路径可用。
3. 执行器不可用：`executor=None` 时任务创建 503 `AI_EXECUTOR_UNAVAILABLE`、零任务；手工路径可用。
4. 网络不可用：真实 spawn worker+Job 连接**关闭端口**（真实连接失败），在真实 attempt/退避窗口内完成手工保存；任务最终 `failed / connection_unavailable`，attempt 存在且 `dispatch_marked_at` 全为 NULL（零 provider 发送）、零候选；冷重启读回并导出。

源码窗口/冻结包窗口：四分支均实跑 `g15-noexec`（未配置、执行器启动失败注入、真实闭端口网络失败、凭据损坏），每分支真实手工保存 + 原生导出成功、配置可读、`server_stopped` 与 worker 退出检查为真；执行器失败分支显示可读“执行器不可用”且零任务。调试期间发现并修复的真实产品问题见 §3 第 2–3 条。

## 7. G16：完整 D2 冻结包与资源证明

- 产物：`build/desktop-d2/package/KGNext-D2Verify/`（旧 D0/D1/W3 包未改动）。
- **EXE SHA-256**：`56346c0ac1d874bbf00e947739a40c005f4a2a611b20d6fabf1a7d35a89fafb2`（15,048,169 字节）。
- 包内文件数 182；整包清单 SHA-256：`84fbb22f66f14fbbffc5c6fe4c63810855c0fbbbc68571c608ff902f285b1f1d`。
- 仓外特殊路径实测：`%TEMP%/opencode/kgm-d2-w6-pkg-6de383db/Kg 中文 %# 名/KGNext-D2Verify`（含空格、中文、`%`、`#`，cwd 为该仓外目录，`PATH` 限系统目录，清除 `PYTHONPATH/PYTHONHOME/KGM_*`）。
- 资源相位（同一 EXE，两次启动，均 exit 0）：PE 子系统=2（GUI）且无控制台窗口；migration 单 head `20261017_0004_local` 且两次一致；完整性/外键通过；三类 prompt bundle 存在且同步成功；AES-GCM 可用；真实 DPAPI 保存并读回 `ready`；对受控 TLS 真实握手；真实 spawn 子进程 + `job_assigned` 事件 + 成功候选 + worker 退出确认。
- 同源：源码侧 48 个可达生产模块与冻结包逐项结构指纹一致（不可用 0、仅冻结侧 0）；**另用 `CArchiveReader` 提取 EXE 内真实入口 `d1_main` code**（`5247a08f…`）与源码严格一致。
- 资源捆绑一致性：包内前端 assets、Word 模板、`migrations_local` 0001–0004、`alembic-local.ini` 与源码逐文件 SHA-256 完全一致。

## 8. 包内既有 w5-ui 在途关闭闭环

在同一最终 EXE、包内前端、仓外 cwd、受控 TLS 下复用既有 `w5-ui` 自检（未重写教师流程），全部通过：正文保存冲突拒绝退出、候选/设置草稿门控、在途任务继续等待、旧 close 中止、显式停止退出；受控 provider 收到 split=1/other=1/adapt=1，已发送适龄任务最终 `outcome_unknown`，与 provider 实际接收交叉断言，worker 退出、服务收口。三类任务与候选在新包中可达（G14 拆分/适龄采用已在新包闭环；其他活动由 w5-ui 触发到达候选）。

## 9. 未验边界（不得写成通过）

- **G14 人工逐页 Word**：本轮 Word 页面工具实测只能看到起始页，`CreateForMonitor` 连续失败（`0x80070057`），未打开 DOCX，不能写逐页目视通过；新增 DOCX 样本的逐页人工查看与用户确认仍待验。
- **G13 真实系统睡眠恢复**：未执行，未以测试时钟或暂停进程冒充。
- **G17 真实供应商**：未获真实调用授权，未调用应用真实 AI；受控 TLS 仅证协议/状态，不证真实兼容。
- **G18 教师流程确认**：待工程复审后由用户确认。
- 干净机器、Win10、WPS、其他 DPI/多显示器、发行再现性、原生对话框 busy 等未覆盖分支保持待验。
- 本文件所有结论限当前 Windows 11 开发机、独立合成环境；源码窗口与冻结包的工程证据分别记录，均不替代产品验收。

## 10. 与 Codex 独立结果的区分

本文件 §4–§8 为 **OpenCode 自测**。Codex 独立核查已另行完成并通过（引用其 review，不在此复述为自测）：后端 477 项、前端 typecheck 与 60 项 D1 + 73 项 D2 组件、桌面 168 项、最终整包 130/130 严格 true 且 missing/failed/extra 为空、相关源 hash 前后零变化、独立直接 `CArchiveReader` 54 个归档模块及真实入口同源通过，最终包根 `%TEMP%/opencode/kgm-d2-w6-pkg-b5f78c17`，EXE 同为 `56346c0a…`。自测与独立结果不相互替代；W6 整体与 D2 产品/发行未据此宣告通过。

## 11. 状态声明

实现、测试、构建与验证脚本写入已停止（仅本结果文档为交付说明）。等待 Codex 最终独立核查记录与后续安排；若需修复，交回同一 OpenCode 会话定点处理。本文件不代表 Codex 通过、W6 整体通过、真实 AI 兼容或发行通过。
