# D3-A H1／H2 结果：本机日计划历史读取与整份恢复（R07／R08／R09／R10／R11 回修）

更新：2026-10-23。范围包含 **H1 数据与本机 API** 和 **H2 桌面交互／源码窗口工程验证**；
H3 冻结包与教师包体验仍未开始。未修改教师话语 r3、普通 save、D2 原历史读取、AI 生命周期、
Word 模板或旧提示词 hash。

## 1. 受影响文件与迁移

| 文件 | 内容 |
| --- | --- |
| `backend/app/local/models.py` | 新增 `LocalDailyPlanRestore`；旧模型不改。 |
| `backend/app/local/daily_plan_history_service.py` | 历史列表／详情、预览凭证、整份恢复、回执；独立于普通 `save`。 |
| `backend/app/local/api.py` | 五个历史恢复接口；沿用应用会话／Host／Origin／档案／班级门槛。 |
| `backend/app/local/schemas.py` | 历史列表／详情／预览／恢复／回执严格响应模型。 |
| `backend/app/local/errors.py` | 新增 HISTORY_NOT_FOUND／PREVIEW_EXPIRED／REQUEST_CONFLICT／OPERATION_NOT_FOUND。 |
| `backend/migrations_local/versions/20261023_0005_local_history.py` | 0004→0005，只新建恢复表；旧表与旧行不改、不回填。 |
| `backend/tests/local/test_d3_history.py` | H1 真 SQLite／真 HTTP 专项 25 项。 |
| `backend/tests/local/test_d2_schema.py` | 期望表集合加入新表。 |

新表以同计划复合外键绑定来源／恢复前／结果三个内容三元组；`(profile_id,request_id)` 唯一，
结果内容唯一；降级仍拒绝。

## 2. R02 回修要点

- **R01**：`restore` 的普通回执优先路径和 token 缺失后的回执路径都先校验 URL 计划有效、
  当前档案／班级；软删除或错班时 POST 重放与 GET 回执均 404。合法计划在 token 过期／进程
  重启后仍可凭同一请求读回执。
- **R02**：只有可证明的 `(profile_id,request_id)` UNIQUE 竞争才读回原回执；FK／CHECK／
  审计触发器／COMMIT 等失败完整回滚并归类 `LOCAL_STORAGE_ERROR`，不再统一误报
  `HISTORY_REQUEST_CONFLICT`。
- **R03**：列表与详情先验证当前指针／当前内容，并校验本页结构、身份与来源；畸形 JSON、
  合法 JSON 错误结构、缺失当前内容均为 `LOCAL_STORAGE_ERROR`，不返回 500 或空历史。分页
  仍 limit 50／上限 200、版本游标。
- **R04**：预览摘要绑定 `baseline_candidate_id` 及完整引用链事实，不只 hash 基准文字；预览后
  换成相同正文的另一条合法候选链会拒绝。来源 ID 从不由客户端决定。
- **R05**：历史入口独立校验基准候选 contract／schema 为当前支持的 v1；未知格式明确 503，
  不沿用 `resolve_baseline` 对未知契约的跳过。r1／r2／r3 指导修订均为 v1，仍可恢复。
- **R06**：新增并发、各写点／COMMIT 回滚（按表逐字段快照）、三组跨计划 FK、真实 D2 数据迁移（内容／来源／AI 表逐行一致）、旧学期／校历、空／长文本换行、严格请求保护、旧采用预览失效及候选重新预览、AI 计数不变等测试。
- **R07**：历史列表／详情／预览及新恢复入口按 plan+version 索引做有界 `max(version)==当前指针` 检查；孤立未来内容明确 503，不清理／不重编号。已提交回执读取保持只读幂等。

恢复仍完整复制原文、全部正文、历史组／游戏身份及合法基准；新版本追加，旧行与表头保留；
新 AI provenance 只继承 baseline，不伪造新的 AI 采用。

## 3. 实际验证

每个 `LocalTestCase` 在系统临时目录创建 `TemporaryDirectory(prefix="kgm-d1a-test-")`，
实际数据根／凭据根为其中的 `data/`、`credentials/`；进程 `LOCALAPPDATA` 仅为子进程隔离，
不等于测试数据根。迁移用例另用 `tmp_root/migration-old.db` 副本。未使用真实教师根。

| 检查 | 命令 | 实际结果 | 日志 |
| --- | --- | --- | --- |
| 语法 | `python -m py_compile`（模型／服务／API／schema／迁移／测试） | exit 0 | 终端 |
| H1 专项（R07 最终） | `python -m unittest -v tests.local.test_d3_history` | exit 0，**25 passed**（16.043 秒） | `%TEMP%/opencode/d3_h1_r2_t17.log` |
| 相关回归（R02 独立，R07 前） | `test_d3_history + test_migrations + test_d2_schema + test_daily_plans + test_d2_w4_api + test_concurrency` | exit 0，**93 passed**（55.376 秒）；R07 仅影响历史入口，未全量重跑 | `%TEMP%/opencode/d3_h1_r2_t16.log` |
| 严格 HTTP 单测 | 历史 preview-restore 的未知字段／无 session／错 Origin／错 Host | exit 0，422／401／403／4xx | `%TEMP%/opencode/d3_h1_r2_t11.log` |

**首次失败**：实施中 `models.py` 曾出现 class 与 docstring 合为一行的 `IndentationError`，
`py_compile` 首次失败；修复后继续。首轮 H1 的 7／77 通过不覆盖 Codex 独立复现的 R01／R02／
R03；本回修不以“首轮测试通过”写成没有首次失败。

### 已覆盖

- 列表分页／当前标记／缺失版本／非法 limit；详情完整原文与正文。
- 当前版本拒绝来源；预览后保存、跨计划、过期／重启、来源基线身份变化均拒绝。
- 恢复追加版本、旧行保留、指针／审计／来源记录；同请求回执重放、异请求同键冲突、旧回执
  不覆盖后续保存。
- 并发同键只增一版；不同键竞争仅一成功；内容／provenance／restore／指针／审计写点及
  COMMIT 失败全部回滚；三组复合 FK 跨计划拒绝。
- 恢复不增加 AI task／attempt／AI 操作计数；旧采用预览失效，候选可按当前依赖重新预览。
- R07：孤立未来版本／当前指针落后时 list／detail／preview／新 restore 均 503；预览后插入孤立未来行的 restore 拒绝且全部相关表与指针前后一致。正常回执读取保持幂等。
- 真实 0004 D2 内容／provenance／候选／AI task／execution／attempt／operation 在升级后逐行逐字段一致；恢复表为 0。

### 未覆盖

- H3 冻结包运行、教师包体验及真实 Word 逐页验收。
- 真实 AI、真实教师数据、签名／冻结包运行、Word 人工逐页、WPS／Win10／DPI 未验。
- 源码窗口不能替代冻结包；teacher-talk-r01 仍为 SAC 4551 未运行验收状态。

## 4. 源码身份

- `models.py` `7d6f4a2d5cd4cab9…`
- `daily_plan_history_service.py` `6b3defdd01df9fc1…`
- `api.py` `0205f49fde9276f2…`
- `schemas.py` `e95bbf1739ac6f3e…`
- `errors.py` `4b71cfd198f39761…`
- `20261023_0005_local_history.py` `b3451f4e6788e8fa…`
- `test_d3_history.py` `eb47467982c4b69e…`

teacher-talk-r01 的 EXE `cf3d4b4ca3892b838cab305ab91b6cd37686788d89965dcf19ad9120368a262a`
仍为 SAC 4551 未运行验收状态；未重试、未重建、未改安全设置。H1 当时停等 Codex 独立核查；
H2 经放行后另行实施，见 §5。未 commit／push、未调用真实 AI、未发布。

## 5. H2 桌面交互与源码窗口工程结果

H2 由同一会话、同一指定模型实施；未重新执行 H1。首轮 Codex 审核 R08／R09、末轮 R10 及
R11 已修复，以下为修复后的实际结果。H2 只覆盖 `frontend/src/d1/`、直接相关测试／验证脚本及
独立前端输出，不改变后端历史服务。

### 5.1 H2 实现

| 文件 | 内容 |
| --- | --- |
| `frontend/src/d1/views/HistoryPanel.vue` | 有界历史列表、完整只读内容、当前/历史比较、真实拆分基准比较（可展开、含版本/换行/无基准与空过程区分）、恢复确认、结果核对与回执查询。 |
| `frontend/src/d1/history.ts` | 历史 DTO 路径、人类可读分区/字段投影、比较差异、真实 `split_baseline.group_activity_process` 投影、naive UTC 历史时间显示、时间/来源文案、错误脱敏。 |
| `frontend/src/d1/views/EditorView.vue` | 历史入口“先保存再查看”；`editDisabled` 在恢复提交、结果不明及回执后 GET 期间禁用表单/结构；删除游戏改为受保护函数；恢复完成回父编辑器。 |
| `frontend/src/d1/types.ts` | H1 历史列表/详情/预览/恢复/回执 DTO。 |
| `frontend/src/d1/leave.ts` | `BlockingDraft` 增加 `history`。 |
| `frontend/src/d1/d1.history.test.mjs` | 21 项真实 SFC setup 回归（EditorView + HistoryPanel，含真实基准对象）。 |
| `frontend/vite.d3-h2.config.ts` | 独立输出 `build/desktop-d3-h2/frontend`，不覆盖旧包/前端。 |
| `frontend/package.json` | 新增 `build:d3-h2`，`test:d1` 纳入 H2 测试。 |
| `desktop/d1_main.py` | 新增 `d3-h2-ui`／`d3-h2-verify` 专用合成相位、延迟 GET 验证、截图、DOCX 导出；步骤首错即停；延迟 GET 用 try/finally 释放并恢复 fetch。 |
| `desktop/verify_d3_h2_window.py` | `main` 使用同一 `run_chain` 门禁；首错优先、provider 次数/截图/第二相位失败停链；DOCX XML 检查。 |
| `desktop/tests/test_d3_h2_guard.py` | 15 项门禁/失败注入/下游 spy/cleanup 测试。 |
| `desktop/tests/h2_cleanup_probe.mjs` | 用 Node 执行 d1_main 原始安装/cleanup JS；ordinary/fallback/cleanup-throws 三例验证挂起 promise、真实 fetch 次数与恢复。 |

R08 修复：`editDisabled` 现包含 `historyRestoreBlocked`（`historyBusy || historySettling`），
覆盖恢复 POST 在途、结果不明、回执查询及恢复后父层 GET 整个窗口；晨间/后游戏/下午游戏
删除改为 `removeMorningGame`／`removePostGame`／`removeAfternoonGame` 受保护函数，模板不再
直接 `splice`。R09 修复：`_h2_step` 记录首错后抛 `_H2StepFailed` 停止后续依赖；AI 配置失败
也走同一停止路径；`verify_d3_h2_window.main` 现在真实调用 `run_chain`，首错优先于缺截图的
泛化错误，provider split 次数不为 1 不进入第二相位，第二相位失败不检查 DOCX。R10 修复：
历史面板独立可展开区域显示当前/历史的真实 `split_baseline.group_activity_process`，保留版本
与换行；无基准显示“无基准”，有基准但过程为空显示“（基准存在，过程为空）”；正文 0 处差异
但基准变化仍明确提示；只读详情也显示所选版本基准。R09 cleanup 修复：移除
`__h2CleanupFetch`／fallback 在调用 release 前预置 `__h2ReleaseCalled=true` 的错误；cleanup
始终调用幂等 release，再恢复真实 fetch；`H2_DELAYED_GET_INSTALL_JS`／`H2_CLEANUP_JS` 提为
模块常量，由 Node 探针执行原始 JS（非简化复制），覆盖普通、缺失 cleanup hook 的 fallback、
cleanup 抛错三种情况。R11 修复：`historyTimeText` 对无时区的本地 API 时间按 UTC 解析，已有
`Z`/offset 保持原 instant；显示使用本机时区，不固定加 8 小时；测试显式使用
`Asia/Shanghai`。

### 5.2 实际命令与结果

| 检查 | 命令 | 实际结果 |
| --- | --- | --- |
| TypeScript | `npm run typecheck` | exit 0 |
| H2 SFC | `node src/d1/d1.history.test.mjs` | exit 0，**22 passed** |
| D2 组件回归（R08 后定向） | `node src/d1/d1.w5.test.mjs` | exit 0，**94 passed** |
| H2 门禁/失败注入/cleanup | `desktop/.venv-d1/Scripts/python.exe -m pytest tests/test_d3_h2_guard.py -q` | exit 0，**15 passed** |
| R09 原始 JS 探针 | Node 执行 `desktop/tests/h2_cleanup_probe.mjs`（环境变量注入 d1_main 常量） | exit 0；三例 `settled=true,calls=1,released=true,fetchRestored=true`；cleanup-throws 保留 `cleanup boom` |
| 独立前端构建（上一轮） | `npm run build:d3-h2` | 上一轮 exit 0；R10/R11 源码改动后未重建，待 Codex 最终构建 |
| 源码窗口＋冷重启＋Word（上一轮） | `desktop/.venv-d1/Scripts/python.exe desktop/verify_d3_h2_window.py --out %TEMP%/opencode/d3_h2_verify_report_r10d.json` | 上一轮 exit 0，report `ok:true`；本轮 cleanup 修复后未重跑窗口，按要求由 Codex 最终执行 |

未重跑 D1 纯逻辑／60 组件全套；R08 只影响 EditorView 模板与结构删除，已定向复跑 94 项 D2
组件；R10／R11 只影响 HistoryPanel/history 展示，复跑 22 项 H2。没有 skip。

日志：`%TEMP%/opencode/d3_h2_history_r11.log`（22 项）、
`%TEMP%/opencode/d3_h2_w5_after_r08.log`（94 项）、
`%TEMP%/opencode/h2_cleanup_probe_r09.json`（R09 原始 JS 探针）、
`%TEMP%/opencode/d3_h2_verify_run_r10d.log` 与 `d3_h2_verify_report_r10d.json`（上一轮源码窗口）。
最终根内另有 `first.json`、`verify.json`、`first-window.log`、`verify-window.log`、`startup.log`。

最终合成根：`C:\Users\yw980\AppData\Local\Temp\kgm-d3-h2-window-a48e856b`。两相位均使用
`APP_DISABLE_DOTENV=1`、独立 `LOCALAPPDATA`、显式 `--data` 合成根；真实 KGNext-G17 两库、
凭据根、旧包和 Word 未触碰。受控本机 TLS provider 只收到 1 次 split 请求，无外部网络或真实
AI 凭据。

### 5.3 窗口、冷重启与 Word

- 首相位 `d3-h2-ui`：合成根内创建 v1 空计划、v2 全栏目、v3 真实拆分基准（过程 X）、
  v4 历史手工版（过程 Y）、v5 当前版（过程 Z，使用新的组身份）。历史列表为 v5..v1；
  选择 v1 时展开“拆分基准变化”区域，实际显示当前 v5 的过程 X 与历史 v1“无基准”，并保留
  版本和换行；选择 v4 时显示 26 处完整差异；确认“恢复并保存”后恢复为 v6，历史来源为 v4，
  恢复的组/游戏 ID 与“历史v1”文字均回来。
- 延迟 GET 注入：恢复 POST 成功、父编辑器读取当前计划被页面级 fetch 挂起时，
  `historyBusy()===true`、`editDisabled()===true`；28 个内容控件中可编辑控件全部 disabled，
  晨间/后游戏/下午三个删除按钮均 disabled；点击后结构计数仍为
  `morningGroups=1, morningGames=1, postGroups=1, postGames=1, afternoonGames=1`。释放 GET
  后编辑器 ready、v6、dirty=false、editDisabled=false；清理记录
  `release_called=true, fetch_restored=true`。该注入由 try/finally 释放，只用于验证，不改产品
  流程。**注意：上述源码窗口运行在 R09 cleanup 预置 flag 缺陷修复前；正常成功路径的手动
  release 遮住了该缺陷。最终 cleanup 逻辑由本轮 Node 原始 JS 探针验证（ordinary/fallback/
  cleanup-throws 均 settled、calls=1、fetchRestored），最终窗口由 Codex 执行。**
- 冷重启 `d3-h2-verify`：同一合成根重新启动真实窗口，读回 v6、原文 `H2 历史原文\n第二行`、
  历史组身份和来源 v4；历史列表为 v6..v1，v6 为当前且 `restored_from_version=4`。
- Word：通过真实本地导出 API 从持久 v6 生成 DOCX（14278 bytes）。首次无确认返回
  `409 EXPORT_ACK_REQUIRED`（合成夹具故意有空栏目），随后按真实确认路径带
  `ack_missing=true` 与 `expected_context` 重试得到 200。DOCX 检查到历史反思/历史组文字；
  `w:color=FF0000` 标红包含“历史版/历史新增”，不含“当前版”，证明恢复后的 Word 标红按
  保留的历史拆分基准 X，而不是后来当前版 Z。**产品 Word 导出不打印 `raw_lesson_plan`**；
  `observed_historical_raw_in_docx=false` 只是观测，原文由冷重启读回验证，不作为 Word 失败
  条件。
- 截图（BMP，供 Codex 人工视觉核查，未做像素自动判定）：
  `h2-history-list.bmp`、`h2-history-baseline-warning.bmp`、`h2-history-compare.bmp`、
  `h2-history-confirm.bmp`、`h2-history-restored.bmp`、`h2-history-cold-restart.bmp`，均位于
  上述最终合成根 `screenshots/`。截图显示列表当前/来源标记、完整比较、单独基准提示、
  恢复确认及恢复后当前版本。

### 5.4 首错与修复记录

1. **首轮源码窗口日期越界**：验证脚本默认 `2026-10-19`，合成学期止于 `2026-09-30`；
   `confirmCreate` 等待超时，根 `...kgm-d3-h2-window-0c1aed99`。改为 `2026-09-15` 后继续。
2. **Word 首次 409**：根 `...05ea7d49` 的首次导出为 `EXPORT_ACK_REQUIRED`（空栏目）；验证
   脚本改为走真实 `ack_missing + expected_context` 确认路径，之后 200。没有绕过确认。
3. **R08 首轮延迟 GET 断言**：根 `...19bfa0fe` 把 Element Plus 只读 `el-select__input`
   误计为可编辑控件；过滤 `readonly` 后继续。随后根 `...be03dfe7` 因当前 v5 已清除全部组，
   三个删除按钮不存在；改为当前 v5 使用新的组身份（历史 v4 的旧身份仍不在 v5），既保留
   “历史身份重新出现”语义，又让三类删除 DOM 在延迟窗口存在。最终根 `...8e7328d5` 通过。
4. **R08 代码缺陷**：首轮 `editDisabled` 未包含 `historyRestoreBlocked`，模板直接
   `group.games.splice` 可绕过保护；已按 5.1 修复并加 SFC/源码窗口断言。
5. **R09 代码缺陷**：首轮 `step` 捕获失败后继续、验证脚本首相位失败但有版本时仍进入冷重启/
   Word；已改为首错即停并加门禁/spy 测试。失败注入测试确认首相位失败时第二相位与 DOCX
   检查均未调用。
6. **H2 前端首轮语法错误**：`history.ts` 首次写入多了一个引号，`npm run typecheck` 报
   `TS1002`；修正后通过。H2 组件首轮另有一处测试断言把“历史游戏名”错误地期望出现在分组
   标题中；改为检查分组行值后通过，产品代码未因此改变。
7. **R09 provider 计数竞态**：根 `...b4519c3d` 首相位本身成功，但验证脚本在首相位进程退出
   前读取 `seen["split"]` 得到 0，`run_chain` 以 `provider split count 0 != 1` 停链。改为
   `first_runner` 在 `_run` 返回后写入 `first["provider_split_count"] = seen.get("split", 0)`，
   门禁读取该事实；上一轮窗口报告 `provider_requests.split=1`、`first_provider_split_once=true`。
   严格 provider fact 门禁后的最终根为 `...a48e856b`。
8. **R10 截图未滚到展开区**：根 `...6561739c` 已展开基准但截图仍在详情顶部；增加滚动到
   `history-baseline-warning` 后重跑，最终根 `...a48e856b` 的截图显示当前 v5 过程与历史 v1
   “无基准”两侧实际内容。R10 组件首轮断言“正文 0 差异”时夹具两侧原文不同导致 1 处差异，
   改为夹具两侧原文相同；产品代码未改。
9. **R09 cleanup 故障注入**：新增 15 项门禁测试，覆盖首相位非零但有版本、首相位必要 check
   缺失、provider 次数缺失/非 1、第二相位失败、首错优先于缺截图、`_cleanup_h2_fetch` 释放/
   恢复及清理异常不替换首错。源码窗口同时记录 `release_called=true, fetch_restored=true`。
10. **R09 cleanup 预置 flag 缺陷**：`__h2CleanupFetch` 与 fallback 在调用 `__h2ReleaseGet`
   前先设 `__h2ReleaseCalled=true`，release 首句检查后直接 return，故障 finally 实际没有释放
   挂起 GET；正常成功路径先手动 release，遮住了问题。已移除预置，cleanup 始终调用幂等
   release 并恢复 fetch。Node 原始 JS 探针首次因 `//` 注释与后续字符串无换行拼接报
   `Unexpected end of input`；删除该注释后 15 项 guard 测试通过，三例结果均为
   `settled=true,calls=1,released=true,fetchRestored=true`，cleanup-throws 保留
   `cleanup boom` 且原始 `DOM assertion failed` 不被覆盖。

### 5.5 源码身份（sha256 前 16 位）

- `frontend/src/d1/views/EditorView.vue` `5a4938164fe08007…`
- `frontend/src/d1/views/HistoryPanel.vue` `785f5ab07a952f69…`
- `frontend/src/d1/history.ts` `0d3d97e66cb467d9…`
- `frontend/src/d1/types.ts` `be941d1ddee3a272…`
- `frontend/src/d1/leave.ts` `e2817f10ea686588…`
- `frontend/src/d1/d1.history.test.mjs` `41db2dec21b31799…`
- `frontend/vite.d3-h2.config.ts` `3a7b5fdad597ce34…`
- `frontend/package.json` `f64473171a5381fc…`
- `desktop/d1_main.py` `31e60491dfab2eda…`
- `desktop/verify_d3_h2_window.py` `a42a21989fec2464…`
- `desktop/tests/test_d3_h2_guard.py` `e6e935586c6ba520…`
- `desktop/tests/h2_cleanup_probe.mjs` `dbb788eac00ad72b…`
- 上一轮独立前端（R10/R11 源码改动后未重建，待 Codex 最终构建）：
  `d1.html` `ce4c21be6ee6537d…`；`assets/index-DyqM_lly.css` `467df4cdc8facd07…`；
  `assets/index-CH0WLbl6.js` `86b7903a4802c8e0…`

### 5.6 R11 历史保存时间显示

- **原因**：本地 API 的 `base.utc_now` 是 naive UTC，模型列 `DateTime(timezone=False)`，
  history service/DTO 直接返回 `"2026-10-23T12:39:00"`，没有 `Z`。旧
  `historyTimeText(new Date(value))` 在 `Asia/Shanghai` 把它当本地 12:39，实际应为 20:39。
- **实测**：Codex 源码窗口截图与 Pydantic DTO／本机 Node 独立复现；不是数据库或 DTO 时间值
  本身错误，而是教师界面显示解释错误。
- **修复**：仅 `frontend/src/d1/history.ts` 的 `historyTimeText`：无显式时区的 API 时间补
  `Z` 后解析；已有 `Z`/offset 保持原 instant；显示仍用本机时区，不固定加 8 小时。未改数据库、
  全局 DTO 或其它时间处理。
- **测试**：显式 `Asia/Shanghai` 覆盖 naive UTC、`Z`、`+08:00` 不双加、跨日期、微秒、非法值
  fallback；不依赖运行机器时区。H2 SFC 22 项通过。

### 5.7 仍未验范围

- H3 冻结包运行、teacher-talk-r01 的 SAC 4551、真实包教师流程、人工逐页 Word／版式验收。
- 真实 AI／真实供应商、真实 KGNext-G17 数据、WebDAV、签名、发布、Win10／WPS／其他 DPI。
- 源码窗口截图、自动 DOCX XML 检查和冷重启读回均不能替代冻结包或人工 Word 验收。
- 本轮按要求未重跑真实窗口；上一轮源码窗口不能证明本轮 cleanup 缺陷修复，cleanup 由原始 JS
  Node 探针证明，最终独立前端构建、完整新增路径窗口、冷重启与 Word 由 Codex 执行。
- **H1 持久回执可在重启后按 request_id 查询；这不等于 H2 前端 unknown 请求能跨崩溃自动找回。**
  当前 H2 只在组件内保留原请求；崩溃/刷新后的前端自动恢复未实现，本片不扩大持久层。
- 本次未 commit／push、未构建发行包、未改 Codex review 文档；停等 Codex H2 审核。
