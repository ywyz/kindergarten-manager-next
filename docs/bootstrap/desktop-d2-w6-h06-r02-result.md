# D2 W6 H06-R02 实际重开白屏：诊断进度、撤回与状态（OpenCode）

更新：2026-10-19。本文为 H06-R02「重复打开实际白屏」的**诊断中**记录。**根因未定位、未修复**；等待用户对当前实际显示的确认与后续白屏复现，再按证据做最小产品自有修复。本文不改 Codex 核查文件（`desktop-d2-w6-h06-r02-review.md`）、`docs/tasks/current.md`、`AGENTS.md`、规格或人工记录。

**未启动正式人工会话；未触碰原白屏窗口 PID18540／窗口13045856／原根 `build/desktop-d2/manual-ai-h06-r01-human-20261019-212522`；未调用真实 AI、未发布、未安装升级、未改 profile/GPU/数据、未 commit/push。**

## 1. 本轮撤回与逐字节恢复

- 已删除本轮自建的外部窗口探针 `desktop/d1_paint_probe.py`，并从 `desktop/verify_d2_manual_ai.py` 撤回仅服务它的 `probe` 模式与 `--probe-*`／`WINDOW_TITLE`；未运行该探针，未使用外部 ctypes／`ShowWindow`／`PrintWindow`／`PostMessage` 通道。
- 撤回后 `verify_d2_manual_ai.py` 因写入被转成 CRLF；Codex 独立归一化确认“38897 字节减去 966 个 CR 精确恢复 37931 字节与开工 SHA-256 `f60d64534b47eb5fa2366cfe56cfe7b5a8de61d8ef780e9d7177d79557b7d704`”。
- 本轮仅由 OpenCode 恢复该文件原 LF：`crlf=966 → 0`，字节 `38897 → 37931`，SHA-256 精确等于 `f60d64534b47eb5fa2366cfe56cfe7b5a8de61d8ef780e9d7177d79557b7d704`。**未改其他代码**；`py_compile` 通过。既有控制器逻辑与 H06-R01 结果／失败证据未动。

## 2. 现有证据与候选方向（A/B/C 尚未区分）

现场事实：首次同根冷启动 PID37308 正常显示 v11；22:38:39 同包同 CLI 同数据／凭据根再开 PID18540 白屏、最大化仍白、可访问性树却完整；Codex 仅恢复同一窗口（未 reload／未改数据）后同一 PID 正常绘制；上次退出 stderr 有 pywebview 删除临时 WebView2 用户数据目录 `WinError32`。

候选方向（现无证据可区分）：

- (A) 宿主/WebView2 首帧合成竞态：pywebview 在 `CoreWebView2` 就绪前 `form.Show()`，某些启动首帧未被合成，需一次窗口状态变化才重绘。
- (B) 上一进程遗留 `msedgewebview2.exe`／临时 profile（删除失败）干扰本次呈现。
- (C) 启动上下文/遮挡：窗口非前台启动，Windows 未为其合成，激活后才绘制。

三者都可能“DOM 正常、像素白、激活后恢复”。**不据 DOM/HTTP/exit0 判定通过，也不盲修。**

## 3. Codex 三次独立原生对照（Codex 证据，非本实现者自测）

以下为 **Codex 独立取得**，记录于 Codex 证据根及其核查；本实现者未执行原生 UI／截图：

- `native-repeat-data/` 由既有 `prepare_session` 只读 backup 原人工 v11 形成；独立凭据仅在该副本准备合成 config v4；包为独立仓外完整 182 文件副本（EXE `209dedcd…`、manifest `44e58c4e…` 与 R01 一致）。无供应商监听、无 AI 点击、无候选消费。
- 三次同根进程 27264／21924／34832 均正常 exit0；清理 worker／服务／锁三项均 true；日志／截图／树在独立证据根。
- 有效正常画面：第一次前置后完整工作台及打开 v11 后四行／已同步可读；第二次最大化、最小化恢复均实际正常；第三次先前置后完整工作台及 v11 正常。
- **重要限制**：两次未前置时 Sky 画面有裁切／遮挡，不能当“首帧完整可见”的证据；有效正常画面均出现在前置／最大化之后。此次**未复现**“前置或最大化后持续白”，因此**仍不能区分 (A)／(B)／(C)**，也不据本轮实现盲修。原窗口 PID18540 保持，三次测试窗口均已正常关闭，Codex 已返回并前置原窗口，仍正常显示工作台及 v11。
- 原用户“白屏”结论保持；当前实际显示的**用户确认仍待答复**。

## 4. 本实现者自测（OpenCode，仅限既有脚本）

| 命令 | 实际结果 | 日志 |
| --- | --- | --- |
| `desktop/.venv-d1/Scripts/python.exe -m pytest tests/test_d2_manual_ai.py -q` | exit 0，**28 passed**（入口校验、控制器守卫、provider、克隆、生命周期 fake） | `%TEMP%/opencode/h06_r02_manual_tests.log` |
| `verify_d2_manual_ai.py --help` | exit 0，模式为 `{human,smoke,dom}`（probe 已撤回） | 终端 |
| `verify_d2_manual_ai.py --fingerprint-package --package-dir <209dedcd 目录> --frontend-dir <R01 前端>` | exit 0（撤回后控制器未回归） | `%TEMP%/opencode/h06_r02_fingerprint_check.log` |
| `py_compile desktop/verify_d2_manual_ai.py` | exit 0，恢复 LF 后字节 `37931`、SHA `f60d6453…` | 终端 |

未执行：原生窗口／截图、AI 触发、采用、导出、真实供应商。快速 28 项为 Python 单元级（无窗口），不替代 Codex 原生可见证据。

## 5. 待证据后评估的最小产品自有修复（尚未实施）

仅当有新白屏现场复现且指向宿主生命周期时，才考虑在**产品自有 GUI 线程**做最小改动（不新增技术组件、不碰数据/安全/关闭守卫；同时覆盖正常生产入口与人工入口）：

- 候选1（呈现生命周期）：在窗口 `events.loaded` 后做一次有界、非破坏性的“呈现”动作（不 reload、不改 GPU、不删缓存）。
- 候选2（稳定 profile）：`webview.start(gui="edgechromium", private_mode=False, storage_path=<应用数据>/webview-profile)`，避免每次临时 profile 与其退出删除失败；属行为取舍，须技术审阅。

证据不足前不实施；本轮未改产品宿主、未改持久化 profile、未为未实施的修复重建包。

## 6. 状态与边界

- **H06-R02 根因未定、未修复**；等待用户对当前显示的确认与后续（尤其“前置或最大化后仍白”）的复现，再按证据交回本会话做最小修复。
- 未调用真实 AI／WebDAV／发布；合并在途／真实睡眠／G17／G18／干净机／Win10／WPS／其他 DPI 与发行再现性边界不变，不将本轮写成 W6 或产品通过。
- 原窗口、原根、全部旧包与日志保留；本轮删除仅限自建探针文件。

## 7. 停止写入声明

实现、测试、构建与验证脚本写入到此停止（仅本结果文档为交付说明），等待 Codex 最后核对与新证据。若需修复，交回同一 OpenCode 会话定点处理。
