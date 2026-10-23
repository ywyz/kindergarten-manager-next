# D2 实时思考与等待反馈实施结果（OpenCode）

后续状态：Codex已完成新包与源码窗口独立核查，限定合成工程通过，详见[核查§11](desktop-d2-streaming-review.md#11-最终交付限定合成工程核查通过)。以下保留实现者自测及交付时状态，真实AI未调用。

日期：2026-10-21。本文原位更新 R01–R08 回修后的实施、测试、普通包构建与合成验证结果，供 Codex 独立复核。不把实现者自测写成产品验收；不调用应用真实 AI。

**边界**：未调用 DeepSeek／MiMo 真实供应商，未发布、未安装升级、未 WebDAV、未 commit／push；未改业务候选 schema、数据库模型／迁移、依赖／锁、无关页面或教师正常流程；默认教师库、所有旧包、human／诊断根、Word 与失败日志未触碰。应用运行时仍只准备 DeepSeek 官方与 MiMo 标准 API（本实现只用标准 OpenAI 兼容 SSE，不接 Go／Token Plan）。

> **独立核查状态（2026-10-21）**：r01 包的实现者自测 141/141 **不是**独立通过。Codex 独立运行 r01 完整包实际 **exit 3、137/141**，失败为 `w5p_exit_zero`、`provider_adapt_once`、`provider_adapt_received`、`w5_close_stop_and_exit`；现场与报告保留，不覆盖。随后本报告追加 R10（人工 retry/resume pending 旧 execution）与 R11（W5 测试 provider 真实 adapt 接收同步）；新包 `desktop-d2-streaming-r10-r11` 交付后已由Codex独立完成源码窗口33项／完整包142项，限定合成工程通过，见核查§11。

## 1. 回修范围（R01–R11）

| 编号 | 修复 |
| --- | --- |
| R01 | `[DONE]` 不再代替 `finish_reason=stop`；始终单一文本 choice，拒绝不同 index 混入；stop 后继续 content／reasoning 拒绝；同一帧 content＋stop 允许；usage-only 空 choices 允许，其他空 choices 拒绝；完整 message 兼容分支对 `tool_calls`／`function_call`／`refusal` 同等拒绝（含 content 非字符串且已有 stop 的情况）。 |
| R02 | 流结束时执行增量 UTF-8 decoder 的 final 检查；stop 后的不完整多字节尾巴、终止事件旁非法 UTF-8 不再被忽略为 success。 |
| R03 | SSE 换行归一化保留跨块 CR／CRLF 语义：尾部 CR 延迟到下一块或 EOF；多 `data:` 行、CRLF 逐字节拆块、单 CR、LF、中文 UTF-8 拆块结果一致。 |
| R04 | worker 按实际 JSON UTF-8 序列化上限切分 progress（2000 字符保守上限，覆盖中文／emoji／引号反斜线／控制字符）；单帧实测不越 16 KiB；超大 progress 帧被丢弃而绝不替换成 `provider_error` result。 |
| R05 | SSE 读取到真实 EOF；校验 Content-Length 精确字节与 chunked 终止；DONE 不再提前绕过 framing。短声明体／缺终止 chunk 按已发送／结果不明（unknown），不补发；完整但语义截断的流仍按 invalid output。 |
| R06 | pending 且 `execution:null` 也有稳定等待区与计时；claimed／dispatching／retry_wait 文案按事实；live→terminal 对已知任务做一次只读收尾快照，失败至少冻结已显示计时，不前跳回退；await 后按最新 task execution＋attempt 复核，迟到旧 attempt 响应不能覆盖新文字；终态不继续 thinking 或累加。 |
| R07 | progress API 以持久任务状态／当前 execution／attempt 收口：schema 失败不投影 completed；终态 elapsed 用实际结束 tick 固定；last_data 只由真实供应商数据／心跳更新，本地 validating 不冒充网络数据。 |
| R08 | 受控 TLS 支持延迟分段；真实冻结窗口的 `w5-ui` 在最终答案前实际断言任务面板思考文字、阶段、默认展开、折叠／展开，并核对每类 provider 请求恰好 1 次；不再只看最终缓存或布尔标志。 |
| R09 | 源码窗口入口 split 改用延迟 SSE，预期登记表加入新 DOM 与每类请求恰一次。 |
| R10 | 人工 retry/resume pending 旧 execution 不再投影旧终态；API/前端立即新排队等待，新 claim 恢复；迟到旧 GET 不恢复旧文字。 |
| R11 | W5 测试 provider adapt 真实返回唯一思考后再保持未完；驱动在关闭前等待真实 DOM，不以 pending/claimed/dispatching 推断已发送；生产关闭逻辑未改。 |

## 2. 实际改动（最终源码 hash）

| SHA256 前 16 | 文件 | 改动 |
| --- | --- | --- |
| `fe5c27f5f98d1c28` | `backend/app/local/ai_transport.py` | 流式请求、SSE 解析、stop/choice/message 拒绝、UTF-8 终态、framing、心跳回调、不重发。 |
| `5f5ee9314a3879c8` | `backend/app/local/ai_worker.py` | 有界 progress 帧、实际序列化上限切分、progress 超限丢弃、真实心跳帧。 |
| `159e58a46c104c79` | `backend/app/local/ai_progress.py` | 当前＋最近完成缓存、seq/attempt 校验、结束 tick、supplier-data 时钟、心跳、文本上限。 |
| `8d7d5ba2ac693de8` | `backend/app/local/ai_executor.py` | 消费 progress／heartbeat、旧 attempt 拒绝、完成收口；原期限／permit／关闭保护保持。 |
| `48f2694f083a2897` | `backend/app/local/api.py` | 只读 progress GET 的持久任务状态／attempt／终态固定投影；R10 pending 立即等待、claimed 旧 ended 不投影旧终态。 |
| `94cf4f4cc18d348d` | `backend/app/local/schemas.py` | `LocalAIProgressOut`。 |
| `06d1c3bce6339468` | `frontend/src/d1/types.ts` | `AiTaskProgress`。 |
| `45bab28b296d9ffd` | `frontend/src/d1/views/AiTaskPanel.vue` | 等待／阶段／计时、pending 无 execution、终态收口／冻结、收尾快照、attempt 身份、折叠／纯文本；R10 pending 旧 execution 立即新排队、迟到旧 GET 不恢复。 |
| `a7ea8c549fae0f22` | `backend/tests/local/test_d2_streaming.py` | 35 项协议／真实 spawn＋TLS／API 投影／worker 帧／store 回归；含 R10 真实 retry→pending→new claim。 |
| `1c23c23ec73949c5` | `backend/tests/local/test_d2_w3_transport.py` | 请求断言 `stream:true`。 |
| `f23fb58212aa0413` | `frontend/src/d1/d1.w5.test.mjs` | 14 项流式组件回归（含 pending、终态冻结、迟到旧 attempt Promise、R10 人工 retry pending／迟到旧 GET）。 |
| `75c1bfc9b56adfe3` | `desktop/d1_main.py` | **仅验证相位**：W5 冻结窗口进度 DOM 断言／收尾；R11 关闭前等待 adapt 真实思考 DOM，不据 pending／claimed 推断。普通入口与注入限制未改。 |
| `56d4eaf609c910be` | `desktop/verify_d2_w5_window.py` | R09/R11：源码窗口 split 延迟 SSE；adapt 真实思考后保持未完；预期登记表含新 DOM、每类请求恰一次及 `w5_live_task_received`。 |
| `eacdd1cb42156d5a` | `desktop/verify_d2_w6_common.py` | 合成 SSE／延迟分段／adapt hold helper；默认非流式兼容不变。 |
| `2ceb34f70fa90d22` | `desktop/verify_d2_w6_package.py` | `--stream` 资源检查、W5 延迟分段 provider、R11 adapt 真实接收后保持未完、DOM 与每类请求计数。 |
| `cee8234308c0ca35` | `backend/tests/local/w3_tls.py` | 受控 TLS 延迟分段 fixture（仅测试/验证）。 |
| `fc91ec08b9843c29` | `desktop/verify_d2_w5_window.py` | R09：源码窗口 split 改用延迟 SSE（复用 `sse_segments`），other JSON／adapt 保持；预期登记表加入新 DOM 与每类请求恰一次。 |

## 3. 实际自测（本机，独立合成根／LOCALAPPDATA，`APP_DISABLE_DOTENV=1`）

| 检查 | 命令 | 实际结果 | 日志 |
| --- | --- | --- | --- |
| 语法 | `python -m py_compile`（后端／桌面／fixture） | exit 0 | 终端 |
| 流式专项（R01–R09） | `python -m unittest tests.local.test_d2_streaming -v` | exit 0，**34 passed**（6.013 秒） | `%TEMP%/opencode/stream_r01_t7.log` |
| 后端 local 全套（R01–R09 基线，干净隔离） | `python -X utf8 -m unittest discover -s tests/local -t .` | exit 0，**511 passed**（423.233 秒）；R10/R11 后未重复全套 | `%TEMP%/opencode/stream_r01_local_final.log` |
| R10/R11 后端流式/API 专项 | `python -m unittest tests.local.test_d2_streaming` | exit 0，**35 passed**（5.842 秒） | `%TEMP%/opencode/stream_r10_t3.log` |
| 桌面全套（R10/R11 后） | `python -X utf8 -m pytest tests -q -p no:cacheprovider` | exit 0，**204 passed**（7.54 秒，2 条既有弃用警告） | `%TEMP%/opencode/stream_r10_r11_desktop.log` |
| 前端 typecheck（R10/R11 后） | `npm run typecheck` | exit 0 | `%TEMP%/opencode/stream_r10_ts2.log` |
| 前端 D1／D2 组件（R10/R11 后） | `npm run test:d1` | exit 0，**OK 94**；含两个 R10 具名 ok | `%TEMP%/opencode/stream_r10_fe2.log` |
| r01 普通包构建（历史） | `python desktop/build_d2.py --build-root build/desktop-d2-streaming-r01 ...` | exit 0 | `%TEMP%/opencode/stream_r01_build.log` |
| r01 实现者包自测（**非独立通过**） | `verify_d2_w6_package.py --stream` | 实现者自测 141/141；Codex 独立 **exit 3、137/141**（4 失败见顶部） | `stream_r01_package_verify.json`；独立证据保留 |
| R09 源码窗口 factory 层 | 直接调用 `make_segment_factory`＋解析分段 SSE | exit 0，`FACTORY_OK`；源码窗口留待 Codex | 终端 |
| R10/R11 最终包构建 | `python desktop/build_d2.py --build-root build/desktop-d2-streaming-r10-r11 --hash-out .../package_hashes.json` | exit 0 | `%TEMP%/opencode/stream_r10_r11_build_final.log` |

### 失败／超时定位

回修中一次 30 分钟 shell 超时的整套运行出现两个 F、无实际 unittest exit；当时与 PyInstaller 构建／多套验证并发，测试进程互相竞争。按 Codex 的证据位置复核：`IpcBlockingTests.test_child_never_reading_bootstrap_terminates_within_budget` 与 `LateAndDegradationTests.test_late_response_after_deadline_rejected` 单独运行均 4.4／5.0 秒 exit 0，且 `test_d2_streaming` 后接 `test_d2_w3_executor` 同一进程 **48 项 OK**（46.169 秒，`stream_r01_cross.log`）。随后在无并发构建／无其他测试进程下干净重跑后端全套，**511 项 exit 0**。未放宽生产 120 秒／退出 5 秒保护，未削弱旧断言；失败材料与旧候选包保留。

## 4. 合成 TLS 请求计数与真实进度证据

- **R08 真实冻结窗口**：最终包 `w5-ui` 使用延迟分段的 split SSE；在最终答案到达前，真实任务面板 DOM 已出现 `W5 合成思考过程`（`w5_stream_progress_visible=true`），默认展开（`default_expanded=true`），折叠后文字元素消失（`collapsed=true`），再展开恢复（`re_expanded=true`），阶段可见（`phase=true`）。Provider 请求：split 1、other 1、adapt 1；折叠／查询未新增请求（`w5p_provider_*_once=true`）。
- 资源相位两次同根启动：均 `succeeded`，`streaming_progress_seen=true`，记录 9 个思考字符，阶段包含 waiting／validating／completed；每次资源任务 1 次请求（共 2）。
- G14：split 1、adapt 1、other 0；W5：split／other／adapt 各 1；G15 网络分支为关闭端口 0。合计合成 TLS 请求 **7**；无真实供应商。
- 源码级真实 spawn＋TLS 测试：最终答案前读到非空 progress，最终 `succeeded`、1 候选、1 次请求；断流／发送后取消各 1 次请求、0 候选、不重发。

## 5. 普通包身份与运行说明

### r01（历史候选，Codex 独立未通过）

- 目录：`build/desktop-d2-streaming-r01/package/KGNext-D2Verify/`
- EXE：`686e6e8b586d96c0d35cbcdccb0c51dc371aefd69f405cad076d343aa7d45429`；182 文件；
  清单 `e1d8f3d7a656403b592cb7a59592dff753206c4efa8edbf97d838d095472193d`。
- 实现者包自测 141/141；Codex 独立 **exit 3、137/141**，失败
  `w5p_exit_zero`／`provider_adapt_once`／`provider_adapt_received`／
  `w5_close_stop_and_exit`。现场与报告保留，不写成通过。

### r10-r11（实施者交付时记录；后续独立通过见核查§11）

- 目录：`build/desktop-d2-streaming-r10-r11/package/KGNext-D2Verify/`（完整 onedir；不能只复制 EXE）。
- 普通入口：`desktop/d1_main.py`；前端随包；未混入合成供应商配置／凭据／数据库／fixture／`.env`；普通交互模式不启用受控传输／私网解析／测试 CA。
- EXE SHA-256：`d0e650e8b572a3a7ca8acf7822a47d1c0eeac607322777a7f79d7492d3cfad14`（15,065,536 字节）
- 包文件：**182**；包清单 SHA-256：`80f15a68f0eedfb82713ae9c74936056f2c8a9314e05afe5d1cc6dd391e0873f`
- 前端：`assets/index-DfrJwZhO.js`／`index-zQ04hEx7.css`／`d1.html` 随包。
- 运行说明：`build/desktop-d2-streaming-r10-r11/RUN.md`；逐文件散列：`package_hashes.json`。
- **本包完整冻结包验证与源码窗口未由 OpenCode 执行**；不沿用 r01 的 141 项自测作为本包通过。待 Codex 独立核查完整包、源码窗口与归档同源。
- 首轮 `build/desktop-d2-streaming/`、`desktop-d2-streaming-r2/`、`desktop-d2-streaming-r3/`、r01 及失败材料全部保留。
- 旧包保留未改：普通 `56346c0a…`、`e843d11b…`；人工 `18915b7b…`、`209dedcd…`（均 182 文件）。旧人工／诊断根未触碰。

## 6. 已覆盖／未覆盖

**已覆盖**：R01 缺 stop／DONE-only／不同 choice／stop 后正文／message 三项禁用字段；R02 UTF-8 尾字节；R03 CRLF 跨块／多 data 行／单 CR／LF／中文拆块；R04 中文／emoji／引号反斜线／控制字符的序列化上限与超限 progress 丢弃；R05 短 Content-Length／缺终止 chunk／断流 unknown 且只发一次；R06 pending 无 execution、终态冻结不回退、收尾 GET 失败、同 execution 新 attempt、迟到旧 attempt Promise；R07 持久终态投影、固定 elapsed、supplier-data／heartbeat 时钟、本地 validating；R08 真实冻结窗口 DOM、默认展开／折叠／展开、请求计数；R09 源码窗口 split SSE 入口；R10 人工 retry/resume pending 旧 execution 隐藏、新 claim 恢复、迟到旧 GET 不恢复；R11 W5 adapt 真实 SSE 思考先于关闭、每类请求恰一次。R10/R11 小专项后端 35、桌面 204、前端 typecheck 0／D2 94；R01–R09 基线全 local 511。

**实施者未覆盖／真实未验**：r10-r11完整包／源码窗口未由OpenCode执行，后续Codex独立142／33项已通过；r01 的独立结果为 137/141，不冒充通过。未调用 DeepSeek／MiMo 真实 API；真实首字延迟、持续心跳、供应商差异与用量未验；未实等 120 秒整段超时（解析层超时与受控断流已测，代码每步复核绝对期限）；1 MiB流式超限未由实施者单独构造，后续Codex独立无长度SSE超限探针已拒绝（核查§8／§11）；R08/R11 DOM 只在 split/adapt 的合成场景；Win10／WPS／其他 DPI／多显示器／干净机器／发行再现性未验。历史 H06-R02 白屏、H06-R03 额外任务、G13 跨 120 秒睡眠仍按 W6 收口保持观察，不因本包写成已修复或已验证。

## 7. R09：源码窗口验证入口修复（2026-10-21 终稿审阅追加）

`desktop/verify_d2_w5_window.py` 的源码窗口入口原先仍用非流式 JSON 回答 split，而
`drive_w5_ui` 已无条件断言新的实时思考 DOM，两者不一致。本次仅改该验证脚本：

- `make_segment_factory` 取代 `make_reply_factory`：split 复用
  `verify_d2_w6_common.sse_segments(SPLIT_OUT, delay=2.5)`（真实延迟分段、含
  `W5 合成思考过程`），other 保持 JSON，adapt 返回 `None` 保持活跃关闭流程。
- `TlsServer(segment_factory=...)` 使用既有延迟分段 fixture；不新增依赖、不改生产期限或断言。
- 固定预期登记表新增 `w5_stream_progress_visible`／`default_expanded`／`collapsed`／
  `re_expanded`／`phase`，以及 `provider_split_once`／`other_once`／`adapt_once`；要求
  每类 provider 恰 1 次，进度轮询／折叠不新增请求。

只做了 factory 层验证，未运行源码窗口（按要求留待 Codex 跑源码窗口）：py_compile exit 0；
直接调用 factory 对 split 得到 2 段 SSE（Content-Length 与正文一致、reasoning 为
`W5 合成思考过程`、最终 content 与 `SPLIT_OUT` 完全一致、含 stop＋DONE），other 为 JSON，
adapt 为“真实思考后保持未完成”的分段 SSE（R11 后），`seen={'split':1,'other':1,'adapt':1}`。
源码窗口运行时须用当前前端构建
（例如 `--frontend build/desktop-d2-streaming-r10-r11/frontend`，或重新 `npm run build:d1`），
否则旧前端不含新的进度 DOM；本次未运行窗口。

生产源码与 r01 包字节未变，因此未重建 `build/desktop-d2-streaming-r01/`；其 182 文件、
EXE `686e6e8b…`、清单 `e1d8f3d7…` 及实现者 141 项自测保持；Codex 独立 r01 结果为
**exit 3、137/141**，不写成通过。旧包与失败材料保留，未 commit／push。

## 8. R10／R11：人工重试旧进度与 W5 adapt 真实接收（2026-10-21 追加）

### R10

`_requeue` 把人工 retry/resume 置回 `pending` 时保留旧 `current_execution_id`／attempt，原
API 与前端会把旧 ended/unknown 快照继续当作当前进度。最小修正：

- API：`pending` 一律返回明确的等待投影（`available:false`、`phase:"waiting"`、空 reasoning、
  零计时），不读取旧 execution 的缓存；`claimed` 遇到旧 ended 快照同样不投影。
- 前端：`progressFor` 对 `pending` 优先显示新的稳定等待区与计时；`pendingSince` 在进入
  pending（含从终态返回）时重置；`fetchProgress` 对 pending 不发进度 GET；同 execution
  进入新 attempt 时按最新 attempt 再复核；迟到旧 GET 不能恢复旧文字。
- 未清空／改变持久 `current_execution_id`、历史 execution、task 状态机或重试协议。

实际回归：后端流式/API 专项 **35 passed**（5.842 秒，含真实 `retry_task` →
pending（旧 execution 保留）→ API 等待 → 新 claim 恢复），前端 typecheck exit 0、
`test:d1` **OK 94**，两个 R10 具名组件测试均实际出现 ok
（`manual retry pending hides the old execution progress`、
`a late old GET during pending cannot restore old text`）；桌面 **204 passed**。

### R11

r01 的 Codex 独立结果 137/141 中 adapt 相关失败，源码定位为 W5 驱动
`start_live_task` 只等待 `liveCount>=1`（pending 也满足）便关闭；受控 provider 实际
`adapt=0`，因此没有在途发送证据，最终 paused/user_stop，`w5_close_stop_and_exit` 随之失败。
未发现另一个宿主关闭事实失败；**生产关闭逻辑未改**，未放宽 5 秒关闭／120 秒尝试／paused
语义，也未削弱 `provider_*_once`／最终 `outcome_unknown` 断言。

测试专用修正：

- `adapt_hold_segments`：真实 TLS 响应的第一段是唯一 reasoning `W5 适配准备` 的 SSE，
  随后保持未完成（声明长度大于已发送、延迟 30 秒），不伪造最终结果。
- 源码与包 W5 驱动在关闭前等待该唯一 DOM 文字（`w5_live_task_received`），证明 provider
  已真实接收，而非从 pending/claimed/dispatching 推断；随后仍走原关闭流程，要求
  `outcome_unknown`。
- 每类 provider 仍恰 1 次；`adapt` 现在真实收到 1 次。源码/包 factory 层均实测
  `{'split':1,'other':1,'adapt':1}`。

### 新包

`build/desktop-d2-streaming-r10-r11` 已串行构建（182 文件；EXE
`d0e650e8…`；清单 `80f15a68…`）。按本轮要求，**未运行**完整冻结包验证与源码窗口，
r01 自测 141 不沿用作新包通过；完整包、源码窗口、归档同源与状态/旧 GET 稳定性待 Codex
独立核查。旧包、r01 及其独立 137/141 失败现场全部保留；未 commit／push。

## 9. G17 教师内容定点整改（2026-10-22）

### 9.1 实现

- `prompt_bundles.py`：冻结契约 v1／默认 r1 的输入输出 schema、字段集、指导文字和 bundle
  hash 完全保留（r1 hash：split `223a77eb9d2f…`、adapt `33dd13f4800a…`、other
  `a952d500a843…`）；新增三类默认 r2（同 contract 1、同 schema、同字段集，仅默认指导
  文字），新档案初始 r2，已有档案 head 推进到 2 但个人版本文字不静默覆盖。
- r2 默认指导：多项内容／步骤真实换行并以 `1. `、`2. `、`3. ` 依次编号，数量按实际；名称／
  主题等短单值不编号；拆分只整理原文已有条目的编号／换行，不扩写。过程适龄调整仍可按
  年级调整表达、步骤和难度，最终过程按实际步骤分行编号；即使无需适龄调整也保留原教学
  内容并整理编号／换行，不编造已发生课堂事实。晨间集体与自选/自主均为户外，不含区域／
  室内／专用室活动；优先 `kind=outdoor` 配置，无户外配置给不冒充已配置的一般建议；其他
  板块仍可使用各自适用地点。教师可见默认文字已移除“删除配置／不改计数／手工保存规则”
  等实现者指令。
- `ai_task_service._render_system_text`：公共与三类任务指令同步上述格式、户外和忠实原文
  底线；实际请求 system 为正确 contract 1 与 r2 指导，不新增参数、依赖、迁移或预算。
- 未改 schema、字段集合、持久状态机、任务协议或前端候选流程。

### 9.2 验证

| 检查 | 实际结果 | 日志 |
| --- | --- | --- |
| G17 新专项 | **5 passed**（r1 hash、新档案 r2、已有 r1 接受／拒绝 r2、system 规则、真实 claim 快照） | `%TEMP%/opencode/g17_content_t5.log`；claim 专项 `t8.log` |
| prompt／contracts／schema | **58 passed** | `%TEMP%/opencode/g17_content_t3.log` |
| 最终受影响合并复跑（上述 58＋G17 5） | **63 passed**（13.718 秒） | `%TEMP%/opencode/g17_content_t12.log` |
| 实际请求 system 解析 | `test_real_tls_persistence_recovery_keeps_single_http` 改为拆 HTTP body→JSON→嵌套 system JSON；contract=1、guidance/规则解析通过，单 HTTP／恢复断言保留 | `%TEMP%/opencode/g17_content_t11.log` |
| 资源 bundle helper | 六条精确集合单测；r1-only／缺一条／未知修订／错 hash／重复均拒绝 | `%TEMP%/opencode/g17_content_r02_test.log` |
| 源码 `w6-resources` 实际相位 | exit 3（唯一 false 为源码 `frozen_entry`）；`prompt_bundles_present=true`、六条 r1+r2 hash 一致、任务 succeeded、其余资源检查 true | `%TEMP%/opencode/g17-r02-resources-source/resources.json` |
| W4 多行其他活动未选板块 | numbered `1. 问题一\n2. 问题二\n3. 问题三` 采用后仅 morning_talk 变化，其他板块保持原状 | `%TEMP%/opencode/g17_content_t9.log` |
| W6 多行编号候选 | preview→adopt→保存→同根重启→DOCX：过程单元格实际 `w:p` 为 `1. 导入\n2. 观察\n3. 比较`（3 段，不是合并一行）；原文与 split baseline／其他字段不变 | `%TEMP%/opencode/g17_content_t10.log` |
| 桌面全套 | **204 passed**（8.76 秒） | `%TEMP%/opencode/g17_content_desktop2.log` |
| 前端 typecheck／D2 | exit 0；**OK 94** | `%TEMP%/opencode/g17_content_ts2.log`／`_fe2.log` |

Codex 独立回归报告为 159 项中 158 通过；唯一失败是上述系统消息 raw-byte 断言（嵌套 JSON
转义），已仅修测试并定点复跑 **exit 0**，未改生产 transport、未删除单 HTTP／恢复／契约
断言。未重复 159 全套；由 Codex 独立定点复跑。

### 9.3 新包

r01 内容整改包保留：`build/desktop-d2-g17-content-r01/`，EXE
`3f6999691efeb71d78da04a4a3d97c39180d4c607abfd9c7d440166a56b69c83`，182 文件；其完整
冻结包实际为 140/142，失败 `res_prompt_bundles_present`／`res_exit_zero`，现场保留，不写成
通过。

资源自检修正后的交付包：

- 目录：`build/desktop-d2-g17-content-r03/package/KGNext-D2Verify/`
- 182 文件；EXE `7f3ebbb53649fefc42df940beea65a76d0db2c53dcac0740c406ee6a9f57a333`
  （15,067,834 字节）；清单
  `f3788ef90ae68a9e9d990c0c8b988c432e815e57b87eb9adfded19627898335c`
- 前端随包：`index-DfrJwZhO.js`／`index-zQ04hEx7.css`／`d1.html`；RUN 与逐文件散列见
  `build/desktop-d2-g17-content-r03/RUN.md`、`package_hashes.json`。
- r02 构建捕获了漏传 manifest 参数的缺陷版本，已保留但不作为交付包；r03 修正调用并在源码
  资源相位验证六条精确 bundle 后再构建。
- 实现者未执行完整冻结包；Codex后续独立r03整包首轮129/142、同包W5定点复跑33/33通过，
  首次窗口波动原因未确认，未取得单轮142全通过。准确证据见[G17结果§6.4](desktop-d2-g17-result.md#64-最终r03定点整改限定离线工程核查完成)。源码窗口未单独复跑、真实修订输出质量未复验；未调用真实
  AI、未发布、未 commit／push。旧包、r01／r02／r10-r11、human／诊断根与失败证据全部保留。

### 9.4 资源自检精确 bundle

`desktop/d1_main.py` 的资源相位不再直接把六条 `task_type` 列表与三任务列表比较，而是查询
`(task_type, contract_version, default_revision, bundle_hash)` 并与
`PROMPT_BUNDLE_MANIFEST` 的**精确集合**比较；缺记录（包括只有 r1）、未知修订、重复
或错 hash 都失败。

r03 当时的**六条源码相位**（r1+r2，exit 3 唯一 false 为源码 `frozen_entry=false`）是历史
证据，保持原样；本轮**未重跑**七条源码相位。本轮仅把资源 helper 的测试从六条更新为七条
（三任务各 r1/r2＋适龄 r3），`_bundle_rows_match_manifest` 的生产逻辑未改；该 helper 单测
通过不冒充完整冻结包或七条源码相位通过。

## 10. G17 适龄教师话语 r3（2026-10-22 最小整改）

只改适龄过程任务，新增默认 r3；拆分／其他仍最新 r2，冻结 r1／r2 文字与 hash 不变。
全局 `PACKAGE_LATEST_DEFAULT_REVISION` 保持 2，适龄使用独立
`PACKAGE_ADAPT_DEFAULT_REVISION=3`；manifest 现为七条：三任务各 r1/r2（六条）＋
adapt r3（第七条）。

- r3 `process`：完整过程按实际步骤真实换行并连续 `1. `、`2. ` 编号；每个环节均有教师可
  直接说的具体话语，关键处包含引导语、提问和**教师的预设回应或支持语**，简短自然、衔接
  操作、适合目标年龄；补充话语时保持目标年级适宜的活动难度，不因话语增加认知或表达
  要求（不把某样本的看／摸／指认写成所有小班通用限制）；即使无需年龄调整，也保留原教学
  内容、整理编号换行并补齐每环节教师话语；可条件式回应，不虚构已发生课堂事实或幼儿实际
  回答，不强制逐字稿。
- 系统指令仅 `daily_process_adapt` 分支同步该要求；拆分忠原文、其他活动户外／多行规则保持。
- 仍只输出 `process`，无 schema／字段／迁移／依赖／预算改动；个人 r2 不被静默覆盖，接受／
  拒绝 r3 与任务版本钉住沿用现有机制。

实际回归（隔离合成库，无真实 AI）：

| 检查 | 实际结果 | 日志 |
| --- | --- | --- |
| G17 内容专项（含 r3） | **8 passed**（r1＋r2 三条 hash、新档案 split/other 2／adapt 3、r1 接受 split r2＋拒绝 adapt r3、r2 查看／接受 r3 后 claim=3、拒绝 r3 后 claim=2、system rules、真实 claim、接受 r3 后受控 HTTP/TLS 单请求） | `%TEMP%/opencode/g17_talk_t6.log`；`t3.log` |
| prompt／contracts／schema＋G17 合并 | **68 passed**（15.677 秒） | `%TEMP%/opencode/g17_talk_t12.log` |
| 适龄教师引语 Word 闭环 | 完整非空未选活动板块（morning_games／talk／post／afternoon）深拷贝；采用后及冷重启后仅 `group_activity.process` 改变，其余五字段与未选板块完整等值，原文／baseline 保持；过程单元格实际 6 段，拼接等于教师引语全文 | `%TEMP%/opencode/g17_talk_t11.log` |
| 资源精确 bundle helper（七条） | **1 passed**，覆盖 r1/r2/r3、缺 r3、缺一条、未知修订、错 hash、重复 | `%TEMP%/opencode/g17_talk_desktop3.log` |

文件 hash：`prompt_bundles.py 6fa9897a…`、`ai_task_service.py 07334e77…`、
`test_d2_g17_content.py efa80c20…`、`test_d2_schema.py d8177a58…`、
`test_d2_w2_contracts.py 6ea309b4…`、`test_d2_w6_export_closure.py 397f3e01…`、
`test_d2_w6_degrade_host.py fe4114b1…`。

本轮已构建适龄教师话语普通包：

- 目录：`build/desktop-d2-g17-teacher-talk-r01/package/KGNext-D2Verify/`
- 182 文件；EXE `cf3d4b4ca3892b838cab305ab91b6cd37686788d89965dcf19ad9120368a262a`
  （15,068,542 字节）
- 包清单映射摘要（排序相对路径→文件 SHA256 映射再 SHA256）：
  `28304d72e41a15cb5dd2268d054438603ee046b9a4628eb3439da475cd1e6d6a`
- `package_hashes.json` 原始 JSON 文件 SHA-256：
  `aaf3495e4047d7a14740a9fbe21c2165cbac1109c93c97028cb801b5530a5f77`
  （与映射摘要不同）
- RUN／逐文件散列：`build/desktop-d2-g17-teacher-talk-r01/RUN.md`、
  `package_hashes.json`。
- 完整冻结包与源码窗口由 Codex 独立执行；r03、r02、r01、r10-r11 及旧包、真实隔离数据、
  窗口、凭据、候选、Word 全部保留。未调用应用真实 AI、未发布、未 commit／push；真实模型
  是否遵循 r3 教师话语仍待质量复验。

## 11. 未覆盖

真实 DeepSeek／MiMo 模型对 r3 教师话语的遵循与质量、真实 B／C 复验、完整冻结包与源码窗口、
Word 新样本逐页／WPS、Win10、其他 DPI／多显示器、干净机器、发行再现性仍未验。G13／R02／
R03 历史观察项不因本包改为已修复。

2026-10-22 Codex后续独立核查：teacher-talk-r01包首次资源相位启动被Windows应用程序控制策略以WinError4551拒绝，实际exit3，已停止。源码检查通过不等于包运行通过；未重试／规避／改安全设置，真实B／C仍暂停。准确证据与保护核对见[G17结果§7.6](desktop-d2-g17-result.md#76-新教师话语包windows策略阻止启动停止)。
