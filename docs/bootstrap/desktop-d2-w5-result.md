# D2 W5 界面与宿主整合实现结果（OpenCode）

更新：2026-10-19（第二轮修复轮）。本文件记录 D2 W5「界面与完整流程」的实现、首轮交付、Codex 独立核查（[review §3/§6](../bootstrap/desktop-d2-w5-review.md)）后的逐项修复与本轮自测，供 Codex 独立核查。**W1–W4 限定环境工程通过保持不变；本文件不代表 D2 产品验收、真实供应商兼容或发行通过，也不自行宣告 Codex 验收通过。**

授权与边界：延续 `docs/tasks/current.md` 与用户「Go 套餐 DeepSeek V4.1 Flash（`opencode-go/deepseek-v4.1-flash`）」指示；仅 W5。未启动 W6、未调用应用真实 AI／供应商、未发布／安装，未改 `0001–0004` 历史迁移、旧云端 registry、`ARCHITECTURE.md`、依赖或锁文件，未 commit/push；原教师体验根、D1/W1/W3/W4 证据未改动。未创建子代理。既有未提交/未跟踪内容全部保留。

## 1. 首轮交付（背景）

首轮交付了 W5 前端界面与宿主整合、候选编辑采用、AI 设置/指导/游戏配置、关闭任务选择及组件/宿主测试（首轮自测记录见 Codex 证据根的 opencode-run1.jsonl 与 review §5）。Codex 在 §3/§6 逐项记录了 R01–R13 及附加规格缺项，本轮全部逐项修复。首轮真实窗口自测的成功运行起初存在夹具与驱动缺陷（配置 `request_id` 非 UUID、主线程先写 summary、销毁后仍轮询页面 JS），均已修复并以本轮可重跑驱动复验，见 §4。

## 2. 第二轮修复内容（对照 review §3/§6）

### 2.1 R01/R02 来源字段与空配置提示
- 适龄来源按真实后端字段 `source_excerpt.process` 显示「本次适龄调整所用过程（真实输入，只读）」，与候选输出（`raw_candidate.process`）分开标注；错误字段名不再显示空来源。
- 其他活动来源按真实冻结 `game_config` **内容**判断是否已结合配置，空/无修订显示「未结合班级游戏配置：本次为一般建议」；节假日上下文按实际对象列出。`calendar_coverage_warning` 按真实**对象**类型渲染文本（不再 `[object Object]`）。

### 2.2 R03 关闭冻结与身份复核
- 任务触发在每个 `await`（含 `saveCurrent`、`nextTick`）后复核原 `planId` 与 `frozen`；关闭冻结后不再登记任务。

### 2.3 R04/R12 未决写入的完整上下文、历史与无档案关闭
- 任务提交/动作的丢响应保留**完整原操作上下文**（`request_id` + 完整 body + 计划/任务身份），未决期间：正常触发/动作被**方法层**阻止重入（不再产生新 key）；「查询提交结果」为**只读 GET 回执**；「重试原提交」为显式同 key 同 body 重传。未决写入阻止离开/关闭（父组件 draft 门控）。
- 查询回包应用前复核原 pending 仍是本项（直接执行实际 `client.ts`，不是 API 模块 stub：2xx 响应体截断/解析失败经 `UNKNOWN` 哨兵转为不确定（status 0），不返回 null 污染业务状态；5xx 亦按不确定处理，按实际错误码与回执保守核对）。
- 任务面板**逐页遍历全部任务**（无静默上限），刷新失败保留既有列表与活跃任务可见；不再以 300/2000 上限截断。
- 关闭是否有活跃任务：`probeLiveTasks` 逐页遍历，读取失败/截断按「未知=可能活跃」保守；`LOCAL_PROFILE_REQUIRED` 与未建档状态视为无任务，沿原 D1 关闭。

### 2.4 R06/R10 采用使用教师实际查看的凭证
- 「预览比较」先完成正文保存，再用**真实版本/epoch**构造并绑定比较；采用**只使用该次实际查看的 token**，绝不自动 fresh preview 后直接采用。
- 采用前复核 plan/candidate/选择/编辑签名/正文版本/epoch；任一事实变化即作废旧比较、保留编辑并要求重新比较后再次明确采用（不自动刷 token 写正文）。
- 编辑器 `openCandidate` 先保存正文，失败不打开；`onCandidateAdopted` 每个 `await` 后复核实时计划；外计划响应完全不更新当前 plan/form/baseline。

### 2.5 R07/R11 未决采用与晚回包
- 采用丢响应保留完整原请求（request id/token/plan/candidate/expected/epoch/编辑），恢复时沿用**原 epoch**（不重新 capture）；只读查询或显式同 key 重传可恢复。
- 采用进行/未知未决阻止离开/关闭/取消丢弃。
- **确定 409/422** 表示未提交：解除未决、保留编辑并要求重新比较（不再永久卡住）；仅不确定（status 0/5xx）保留原请求。
- R11：同计划 epoch 不匹配时**不推进 baseline/version**，转入既有版本冲突保护（保留原输入与基线），不再先 rebase 使后续普通保存把已采用过程写回旧值。

### 2.6 R08/R09 设置字段掩码归并、初读与冻结
- 设置写入统一为「完整原上下文 + 只读回执查询 + 显式同 key 重传」；busy/unknown 计入 `draftActive` 并阻离开。
- 归并按**实际提交字段掩码**：保存/adapt 归并所提交字段；accept 只归并明确选中字段；reject 只更新拒绝状态——其他字段/任务与后续输入保留，`confirmed` 独立更新为真实服务器值。
- 密钥：配置保存成功只在 secret 仍等于本次提交值时清空；清除密钥只在 secret 未在途变化时清空（沿原字段代次）。
- 初次读取未完成时禁用并守护字段（迟到的初读不覆盖输入）；班级游戏 `confirmed` 始终为**真实服务器修订**（非实时草稿快照），否则会把未提交文字标为已保存。
- 班级游戏应用未决保留完整原提交、阻止预览/取消/离开，只读查询或显式同 key 重传恢复；「重试原提交」使用恢复守卫（不被 pending 守卫永久拦住）。
- 子组件关闭冻结经 `frozen` 传入并守护全部输入与方法；GameConfig 初读守卫同设置。

### 2.7 R13 关闭选择的请求代次绑定
- 关闭任务选择弹窗绑定 `closeRequestId`+generation；宿主中止/新请求替换时取消旧选择，旧选择回包不向旧请求发 allow、不影响新代次、不重新冻结。继续等待以本次 deny 取消关窗；停止等待并退出传 `task_choice=stop_and_exit`。

### 2.8 附加规格与展示收尾
- 缺板块：其他活动**四类板块全部显示**，未提供的标「未生成」且禁选；协议不变（只序列化已提供且勾选的子集）。
- AI 入口明确「使用默认指导/使用个人指导」并可查看/编辑；指导 `field.label` 为内部 key 时用已有中文字段映射，未知契约保留可读 fallback。
- 教师可见文案不再暴露内部 `task_type`/`grade`：显示「教案拆分…」「中班」等，保留内容版本等可核对信息。
- 普通 `failed` 重试也先提示「新请求可能计费」；unknown 另需确认可能重复处理/计费。

## 3. 本批实际文件（SHA256 前 16，本轮修复后最终值）

前端生产：`types.ts b701ccb58ec0bceb`、`ai.ts 35e5e42c55e378e2`、`client.ts 133249728ed32667`、`operations.ts b1cfad7d3db047cd`、`leave.ts 4e3a6855b2fe33cc`、`bridge.ts 06b81c2c2280aaff`、`App.vue 0613248bc8977222`、`EditorView.vue 0d8e727948332acc`、`SettingsView.vue 87ad8a9634a1f5ca`、`AiTaskPanel.vue 1e8560e3afc8e68f`、`CandidatePreview.vue 518187dc00d54521`、`AiSettingsPanel.vue f3dabcde1e5109bd`、`GameConfigPanel.vue cff832cb1c3289c1`、`d1.w5.test.mjs 8fceb03700e8df6a`、`d1.components.test.mjs b4e3009d5d40f0b9`、`package.json aca3898b2a52c8c9`。

验证/宿主：`desktop/d1_main.py c31603c90029857f`（新增 `w5-ui` 专用自检相位、受控 provider 仅限该模式且 `prepare` 前校验、主线程等驱动收口、关窗后按宿主/进程/落库确认）、`desktop/verify_d2_w5_window.py 90b0af6015ba6d09`（可重跑真实窗口驱动 + 期望检查集合齐备）、`desktop/tests/test_d1_close.py efd3c81f784e2e4f`、`desktop/tests/test_d2_close_barrier.py 069a141de6445174`、`backend/tests/local/w3_tls.py 2474b5e0843e7ea7`（可控 TLS 服务器新增按请求应答，仅测试支持；生产传输未改）。

## 4. 命令、环境与实际结果（完整日志与实际退出码）

统一解释器 `desktop/.venv-d1/Scripts/python.exe`（CPython 3.14.7 Windows x64，标准 GIL）；Node v26.10.0，沿用既有 `frontend/node_modules`。证据目录 `%TEMP%/opencode/kgm-d2-w5-opencode`（含中间 `opencode/`）。

- 前端 typecheck：`npm run typecheck` → **退出码 0**，`%TEMP%/opencode/kgm-d2-w5-opencode/typecheck.log`。
- 前端回归：`npm run test:d1` → d1.test（纯逻辑）+ d1.components **60 项** + **d1.w5 71 项**，**均退出码 0**，`.../test_d1.log`。
- 前端构建：`npm run build:d1` → **退出码 0**，`.../build_d1.log`。
- 桌面宿主回归：`desktop> ./.venv-d1/Scripts/python.exe -m pytest tests -q` → **157 passed / 退出码 0**，`.../desktop_pytest.log`。
- 后端定向回归（仅本轮改动的测试支持 `w3_tls.py`）：`LOCALAPPDATA=<run>/localappdata APP_DISABLE_DOTENV=1 ... -m unittest tests.local.test_d2_w3_transport tests.local.test_d2_w3_executor` → **35 项 / 退出码 0**，`.../w3_repair_unittest.log`。未改后端生产代码，故未重复全 local（首轮 470 项通过记录保留）。

### 4.1 真实 Windows 源码 WebView2 窗口证据（可重跑驱动）

命令：`desktop> ./.venv-d1/Scripts/python.exe verify_d2_w5_window.py` → **退出码 0**。证据根 `%TEMP%/kgm-d2-w5-window-6fa8f8ad/`（`verify-report.json`、`summary.json`、`window-run.log`、`startup.log`）。受控合成 TLS provider 实际收到 split=1、other=1、adapt=1（真实 `AiExecutor` + Windows spawn/Job，无外部网络）；窗口全部检查为 true 且期望集合齐备：

`w5_initialized, w5_ai_configured, w5_close_save_conflict_stays, w5_trigger_split_saved, w5_split_edit_adopt, w5_candidate_draft_blocks_leave, w5_trigger_other_activities, w5_settings_draft_blocks_leave, w5_live_task, w5_close_keep_waiting, w5_close_old_request_aborted, w5_close_stop_and_exit_choice, w5_adapt_final_unknown_or_paused, w5_no_open_attempt, w5_window_closed, w5_host_close_state, w5_close_stop_and_exit, ai_worker_confirmed_exit, server_stopped, provider_split_received, provider_other_received, provider_adapt_received, w5_adapt_final_matches_provider`。

关键事实：正文先保存（v2→v3 由触发产生）；采用后 v4；适龄任务最终 `outcome_unknown / user_stop`，宿主关闭状态 `closing`，worker 确认退出、无 open attempt；`provider_adapt_received=true` 与 `w5_adapt_final_matches_provider=true` 交叉断言（已发送分支不接受 paused）。运行使用独立 `data`/`credential_root`/`LOCALAPPDATA` 与 `APP_DISABLE_DOTENV=1`；受控 provider 注入仅在 `--selftest --phase w5-ui` 且显式合成数据根时允许，且在 `LocalRuntime.prepare` 之前校验。

## 5. 偏差与实现说明

1. 任务面板历史改为逐页遍历（无产品历史上限）；刷新中途失败保留既有列表与活跃任务可见。
2. 关闭「继续等待」以本次 `allow=false` 取消关窗；「停止等待并退出」以 `task_choice=stop_and_exit` 触发宿主 drain。前端活跃任务探测在无档案时跳过、读取失败按未知保守处理（宿主屏障仍为权威）。
3. 其他活动四类板块全部渲染，「未生成」禁选；协议仍只序列化已提供且勾选的子集。
4. `desktop/d1_main.py` 仅新增 `w5-ui` 专用验证相位与受控 provider 选择（受模式/数据根约束）；未改生产运行路径与 W3 屏障接线；`d1_host_api.py` 未改。
5. 设置/游戏配置/候选的写入统一为「完整原上下文 + 只读回执查询 + 显式同 key 重传」。

## 6. 未验范围

- **真实供应商（G17）与真实 AI 调用未执行**：无凭据/授权；受控 provider 为合成 TLS 服务，非真实供应商兼容验证。
- **真实系统睡眠恢复未执行**（不以模拟时钟替代）。
- 本实现者驱动覆盖其他活动生成、适龄发送后停止退出。Codex随后已以独立真实源码窗口完成拆分、适龄、其他活动的真实本机API预览编辑/采用复核，见[review §8](desktop-d2-w5-review.md#8-最终工程结论w5限定源码集成通过)；该证据仍不等于最终包或教师验收。
- **W6 导出/打包/人工 Word 页验未启动**：最终包同源、DOCX 逐页人工查看、干净机器、Win10、WPS、其他 DPI/多显示器、发行再现性仍未验；微软拼音已验，不复验、不重开 D1 人工 Word 验收。
- 组件测试为内存 VM + 受控 API；真实窗口为源码（非最终包）。

## 7. 状态声明

第二轮已按 review §3/§6 逐项修复 R01–R04、R06–R09、R11–R13 与附加规格（R05 与 R10 首轮/复核已修保持），并通过本实现者自测（typecheck 0、test:d1（60+71）0、build:d1 0、桌面 157 项 0、后端定向 35 项 0、真实源码窗口全项 0）。**已停止源码写入，可开始 Codex 独立核查**；后续问题请交回同一 OpenCode 会话定点修复。本文件不代表 Codex 通过、D2 产品验收、真实 AI 兼容或发行通过。
