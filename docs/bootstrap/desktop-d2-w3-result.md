# D2 W3 实现交付结果（OpenCode）

更新：2026-10-18。本文件记录 D2 W3「持久任务、受控 transport 与生命周期」的实现、测试、冻结探针与两条跨轮缺陷修复，供 Codex 最终核查。**W1/W2 限定环境工程通过保持不变；W3 代码、自动测试与本轮最小冻结探针矩阵已交付并自验；本文件不代表 D2 产品验收、真实供应商兼容或发行通过。**

授权与边界：延续 `docs/tasks/current.md`（2026-10-18）与用户「Go 套餐 DeepSeek V4.1 Flash」指示；Codex 独立核查并交回定点修复（R01–R09 系列）。仅 W3；未启动 W4–W6、未调用应用真实 AI／供应商、未发布／安装，未改 `0001–0004` 历史迁移、旧云端 registry 与 `ARCHITECTURE.md`，未 commit。原教师体验根与 D1／W1 包未改动。

## 1. 本批改动范围

### 1.1 生产代码（新增）

| 文件 | SHA256（前 16） | 作用 |
| --- | --- | --- |
| `backend/app/local/ai_endpoint.py` | `2f95c6b585c6c8de` | 从 W1 `ai_config_service` 抽出的纯标准库 HTTPS 端点规范化（R08 规则逐字不变），使网络 worker 不再拉入 ORM／DPAPI 层 |
| `backend/app/local/ai_inputs.py` | `0098ca2d126ac649` | 三类任务业务输入投影：依赖哈希／目标哈希、日历 ±7 日与覆盖诊断、班级游戏修订、来源基准**身份**（`baseline_candidate_id`）；其他活动出站投影排除姓名／反思／整段原文／ID |
| `backend/app/local/ai_spawn.py` | `6cd3a98e7a9e8d2b` | 共享的冻结 spawn 子进程 bootstrap 守卫（`d1_main` 与探针共用）；仅对 `sys.frozen` 且 `multiprocessing.spawn.is_forking` 的子进程生效 |
| `backend/app/local/ai_transport.py` | `2c623d7d7a28b625` | 标准库 DNS 钉住／TLS／`HTTPResponse` 严格客户端：32 地址全公网单播、numeric sockaddr＋peer 核验、无代理／重定向／压缩、头 64 KiB／正文 1 MiB／连接 10 s／attempt 120 s、严格 JSON（重复键／NaN 拒绝）、封套与 framing 校验、供应商元数据白名单 |
| `backend/app/local/ai_worker.py` | `ad3dc0703480524b` | 每次 attempt 一个 spawn worker：Job 前不联网、READY 前零 HTTP、只收 SEND 才发送；有界 JSON bytes 帧（`send_bytes`/`recv_bytes`＋上限）；父进程退出即可自退（`_parent_alive`） |
| `backend/app/local/ai_executor.py` | `ba94b8283b92bf74` | 单协调线程＋每 attempt 一个 spawn＋Windows Job Object（`KILL_ON_JOB_CLOSE`、不允许 breakaway）；FIFO 单在途；claim／freeze／SEND 短内存闸门；有界 IPC（不阻塞协调线程）；本地提交失败仅本地重试并停新调度；有界 teardown 与未确认资源槽 |
| `backend/app/local/ai_task_service.py` | `6c92433c829a7900` | 任务／输入／执行／attempt 服务与状态机：提交／列表／详情／cancel／resume／retry、域内幂等回执先于版本校验、三阶段领取（决策→物料→提交）、许可复验、结束/暂停/取消同事务收口 attempt、凭据收口、冷启动分类、stop-and-exit 撤销事务 |

### 1.2 生产代码（修改）

| 文件 | SHA256（前 16） | 改动 |
| --- | --- | --- |
| `backend/app/local/ai_config_service.py` | `f760b800c46bc2ce` | 端点纯函数改从 `ai_endpoint` 导入（行为不变，W1 名称仍可访问）；`_validate_secret` 保留在本模块 |
| `backend/app/local/api.py` | `903a10d8a5a2fdec` | 任务提交／列表／详情／cancel／resume／retry 路由；回执优先于执行器可用性检查；cancel 使用“取消待提交”冻结协议 |
| `backend/app/local/app.py` | `5b21b7de8a194902` | 工厂接受可选 executor 并挂到 `app.state` |
| `backend/app/local/errors.py` | `14b22716c3b5ce3a` | 新增 W3 错误码（AI_INPUT_*、AI_TASK_*、AI_SOURCE_CHANGED、AI_CONTRACT_UNSUPPORTED 等） |
| `backend/app/local/schemas.py` | `fae32ce5539e745d` | 任务请求／响应模型与 `extra=forbid`、严格整数 |
| `desktop/d1_main.py` | `33ea64d751382c7c` | 先 `runtime.prepare()` 再启动执行器；接入 AI 关闭屏障；`_dispose_executor` 未确认即不释放运行锁；共享 `freeze_support_guarded()` |
| `desktop/d1_host_api.py` | `8600afd64f6b2779` | `CloseCoordinator` 扩展：close 意图同步冻结、`task_choice`（继续等待／停止等待并退出）、任务屏障、所有取消分支原子解冻、防旧回调释放新冻结 |
| `desktop/d1_server.py` | `a54d75d418b72e41` | 传入 executor |

### 1.3 冻结探针（`build/desktop-d2-w3/`，新增）

| 文件 | SHA256（前 16） | 作用 |
| --- | --- | --- |
| `desktop/d2_w3_probe.py` | `83757249bc2b258e` | 无窗口（noconsole）冻结探针：`setup`／`run`（`--kill-at` 崩溃点）／`recover`（只做冷启动分类）；证据只经 `--out`；异常落固定失败码并非 0 退出 |
| `desktop/build_d2_w3_probe.py` | `e3f57e54cb4a37bb` | PyInstaller onedir **noconsole** 包（不跑 npm、不覆盖 D0/D1/W1 包） |
| `desktop/verify_d2_w3_probe.py` | `7768467c8fdfa2b4` | 12 场景崩溃矩阵驱动：复制整包到仓外中文/空格/`%`/`#` 路径、清 `PYTHONPATH/PYTHONHOME` 并收紧 `PATH`、受控 TLS、PE Subsystem 与子进程退出确认 |

### 1.4 测试（`backend/tests/local/`）

| 文件 | SHA256（前 16） | 覆盖 |
| --- | --- | --- |
| `test_d2_w3_transport.py` | `9d9c3adb4a523dc7` | G07 帧/策略/严格 JSON（fake socket）＋**真实受控 TLS**（合成 CA/leaf、真实 `prepare`→READY 零字节→`send` 一次、错误 CA fail-closed） |
| `test_d2_w3_tasks.py` | `1c431fb7be59e7e5` | 投影/依赖与目标哈希、基准身份与损坏组合、日历覆盖诊断、回执与跨域冲突、领取/许可复验、分类映射、重试耗尽、取消历史保留、凭据生命周期、恢复分类、resume/retry 预检、序列化超限零写入、`ai_spawn` 分支 |
| `test_d2_w3_executor.py` | `0314ab600621b97c` | 真实 spawn 进程：分类落地、freeze 保钉版本与单次 SEND、stop-and-exit、cancel 阻 SEND、IPC 阻塞（不读大帧／无效完整帧）、迟到响应拒收、持久化失败仅本地恢复、真实 TLS 单请求与本地提交恢复、手工/G15 路径 |
| `test_d2_w3_host.py` | `7b02676fc83d106e` | CloseCoordinator 全取消分支解冻、任务选择屏障、有界反压（线程 barrier 交错）、DB 锁阻塞撤销失败后 worker 存活且同代继续 |
| `w3_tls.py` / `w3_workers.py` / `support.py` | `f1b9c780dc892dda` / `b14e1b3c7aa7290d` / `3f1bf905b925464c` | 合成 CA/leaf（补 AKI/SKI/KeyUsage/EKU 以满足 CPython 3.14 严格校验）、fake/never-read worker、测试夹具 executor 注入 |

## 2. 命令与实际结果

统一解释器：`desktop/.venv-d1/Scripts/python.exe`（CPython 3.14.7 Windows x64，标准 GIL）。自动验证仅使用独立合成根，凭据根显式注入子目录，隔离 `LOCALAPPDATA`，未打开原教师体验库。

- W3 专项（OpenCode 自验）：
  `python -m unittest tests.local.test_d2_w3_tasks tests.local.test_d2_w3_transport tests.local.test_d2_w3_executor tests.local.test_d2_w3_host`
  → **78 项 / 36.4 秒 / 退出 0**。
- 全 local 回归（Codex 独立执行，本文件不改写其结论）：
  `python -m unittest discover -s backend/tests/local -t backend` → **420 项 / 233.105 秒 / 退出 0**，
  日志 `%TEMP%/kgm-d2-w3-codex-full-83a54633ad5341bc96834d472fcc15c6/unittest.log`。
- W3 定向（Codex 最终）：**78 项 / 35.704 秒 / 退出 0**，
  根 `%TEMP%/kgm-d2-w3-codex-final-targeted-fb74bd849e1c47f49b5b30b297601342`。
- 桌面回归（Codex）：**146 项 / 4.11 秒 / 退出 0**，
  根 `%TEMP%/kgm-d2-w3-codex-desktop-spawn-74a13bfbe44a4d54b52347c86bdad470`；
  关闭竞态修复后 **146 项 / 4.23 秒 / 退出 0**，根 `%TEMP%/kgm-d2-w3-codex-desktop-final-ef115e0b28aa4dd194772a3b8a171859`。
- 冻结探针构建：`python desktop/build_d2_w3_probe.py` → 成功（onedir noconsole）。
- 冻结探针验证（OpenCode 自验）：`python desktop/verify_d2_w3_probe.py --out <证据>` → **159 项布尔检查全 true / 12 场景 / 退出 0**
  （证据 `%TEMP%/kgm-d2-w3-probe-verify-run6.json`）。
- 冻结探针矩阵（Codex 独立）：**12 场景 / 159 断言 / 退出 0**，证据
  `%TEMP%/kgm-d2-w3-codex-frozen-matrix-6d0fd8325062413aa3e0b783301ea7ba/evidence.json`，
  实际运行根 `%TEMP%/kgm-d2-w3-frozen-3acd61b2-中文 空格%#`；同一 `babc…` 包 134 文件复制一致。
- 历史失败根清理记录（Codex 核实后停止残留 `KGNext-D2W3Probe.exe` PID 3576，保留证据，当前成功根无残留）：
  Codex 的 `old-failed-probe-cleanup.json`。

## 3. 冻结探针身份与矩阵

- 包身份：`KGNext-D2W3Probe.exe` SHA256 `babc502994331ac24665837dce6d91fc2020025ac23dcecc1dc5c3d917f162a3`；
  包内 134 文件、24 个 app/入口模块与 7 个迁移/INI 资源与当前源码一致（Codex 独立归档同源比对通过）。
- 运行方式：整包复制到 `%TEMP%/kgm-d2-w3-frozen-<随机>-中文 空格%#/package/` 后执行；清空 `PYTHONPATH`／`PYTHONHOME`，`PATH` 仅保留 Windows 系统目录（证明不依赖开发 Python）；PE Subsystem = 2（GUI／无控制台）。
- 崩溃窗口矩阵（父进程在指定事件点 `os._exit(9)`，随后只做冷启动分类）：

| kill 点 | 恢复后状态 | 已标记 attempt（不等于确证已发） | 外发请求 |
| --- | --- | --- | --- |
| `before_claim` | paused/restart，无执行 | 0 | 0 |
| `claimed` | paused/restart | 0 | 0 |
| `child_started`（Job 分配前） | paused/restart | 0 | 0 |
| `job_assigned` | paused/restart | 0 | 0 |
| `ready`（握手后、标记前） | paused/restart | 0 | 0 |
| `marked`（标记后、SEND 前） | outcome_unknown/restart | 1 | 0 |
| `sent`（SEND 后） | outcome_unknown/restart | 1 | 0–1 |
| `http_sent`（TLS 服务已见请求后） | outcome_unknown/restart | 1 | 1 |
| `result_received`（结果到达、未提交） | outcome_unknown/restart | 1 | 1 |
| `persisted`（候选已提交） | succeeded | 1 | 1 |
| `normal`（无崩溃） | succeeded | 1 | 1 |
| `no_stdout`（无控制台输出启动） | succeeded | 1 | 1 |

所有场景记录`open_attempts = 0`、`integrity_check=ok`、`foreign_key_check=0`，重启后外发计数不增。正常运行以dispose确认退出，父死场景由验证器等待Windows进程句柄确认退出；claim前后尚未创建worker。Job前子进程退出等待实测401 ms，其余已记录崩溃窗口0 ms。

## 4. 两条跨轮缺陷与修复

1. **父死遗留 spawn 子进程（Job 分配前）**：冻结 noconsole 下，父进程在 `child_started`（Job 分配前）被终止时子进程残留，并可能因 PyInstaller bootloader 弹框而不退出。
   修复：新增共享 `app.local.ai_spawn.freeze_support_guarded()`（`d1_main` 与探针共用），只对真实冻结 spawn 子进程包裹 `freeze_support()`；识别到 bootstrap 失败（如父进程已死导致管道句柄复制失败）时以固定码 `SystemExit(7)` 退出，主进程与其它异常路径处理不变；`ai_worker` 增加父进程存活检查（`_parent_alive`），管道 EOF／5 秒握手超时之外再以约 0.25 秒粒度自退。
   证据：矩阵 `child_started_child_gone` 通过，Codex最终实测退出等待401 ms（修复前 >30 秒残留；已核实身份后清理，失败证据保留）。
2. **结果已返回但本地提交失败**：此前只把结果留在内存并停止调度，无法在不重发的前提下补齐落库。
   修复：`_finalize` 本地重试 3 次后把 `(claim, result)` 存入 `_pending_results`，协调线程在**不发新请求**的前提下持续只重试本地提交／读回；成功即清除并恢复调度；期间 `is_runnable()` 为 false 阻止新任务；关闭/停止屏障另行检查未保存结果并拒绝放行。
   证据：真实 TLS 测试 `test_real_tls_persistence_recovery_keeps_single_http` 与 fake 版 `test_result_persistence_failure_then_local_recovery`：故障期外发恰 1 次、`pending_persist=1`、调度关闭；解除故障后本地提交成功、候选 1、`pending_persist=0`、恢复调度，外发仍 1。

## 5. 规格对照与已确认边界

- §2.2：依赖指纹仅取实际发送业务值；适龄依赖含**基准来源身份**（`baseline_candidate_id`），旧 D1 `null`＋无来源合法，损坏组合一律存储错误；日历 ±7 日仅收录库确认的节日名称，超出覆盖写入依赖`_diagnostics`（服务端事实）；TaskOut只返回脱敏的`input_summary.calendar_coverage_warning`，payload 保持冻结契约。
- §4.1／4.3：单协调线程、FIFO 单在途、领取才钉版本、发送标记与 freeze 同短闸门、`_permit_ok` 复核 task generation／状态／permit／launch／ended_at／撤销标记／attempt 归属、结束/暂停/取消/恢复同事务收口未终结 attempt、冷启动只分类不出站、stop-and-exit 先提交撤销事务再协作 2 秒＋强制 3 秒（Job 确认退出）。
- §4.2：连接 10 秒（含 DNS）与 attempt 120 秒含启动/退出硬边界；实际序列化请求与 IPC 帧均按 1 MiB＋16 KiB 校验；供应商 usage 仅保留有限白名单数值。
- §4.3／Q6：close 意图同步冻结；`task_choice` 未给定时旧页面不放行（不静默取消在途任务）；继续等待解冻并保持已钉版本（不新建 generation），停止等待才退役并留手动恢复。
- G15：无 AI／执行器不可用时手工保存与导出仍可用（`test_manual_save_and_export_work_without_ai`）。

## 6. 未验范围与偏差

- **真实供应商调用（G17）未执行**：无真实凭据／调用授权；transport 的目标策略和DNS地址集合用确定性用例验证，真实TLS使用合成CA及显式固定解析的本机受控服务，不代表任一供应商兼容。
- **完整 D2 窗口、教师任务选择 UI、候选比较/采用（W4）、设置页（W5）、导出接通与打包（W6）未实现**；本轮任务详情已返回 `allowed_actions` 与日历覆盖诊断供 W5 绑定。
- 干净机器、Win10、WPS、其他 DPI／多显示器、发行再现性仍未验；部分窗口分支与一次真实休眠未验（休眠/恢复按绝对 deadline 与发送证据分类，未做真实睡眠案例）。
- `d2_w3_probe.py` 存在一个无功能影响的重复 `_bootstrap_backend` 定义（同体、后面定义覆盖前面）；为保持当前已验包同源暂不修改，后续重建时清理。
- `build_d2_w3_probe.py` 的 `--disable-windowed-traceback` 仅抑制 traceback 转储，PyInstaller 仍以禁用消息报告；子进程退出保障来自 `ai_spawn`，已在本文件与脚本 docstring 更正。

## 7. 状态声明

W3 生产代码、自动测试、宿主关闭挂接与最小冻结探针矩阵已交付并自验；Codex 已独立执行 420 项全 local、146 项桌面回归、78 项 W3 定向、12 场景 159 断言冻结矩阵与冻结包同源比对（均退出 0）。**Codex最终核查已通过，见[W3核查§7](desktop-d2-w3-review.md#7-最终工程结论w3通过停在w3)**；本文件不代表 D2 产品验收、真实 AI 兼容或发行通过，不启动 W4–W6。Codex已按职责更新本记录中的证据表述、hash及当前任务入口。本批到此停止代码、测试、包与文档的进一步修改。
