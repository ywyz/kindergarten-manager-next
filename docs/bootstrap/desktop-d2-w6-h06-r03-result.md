# D2 W6 H06-R03：19日一次触发却出现20日新任务——诊断结果（OpenCode）

更新：2026-10-20。本文记录 H06-R03 的**只读诊断**。**未定位到应用侧根因、未复现、未实施任何代码／测试／构建修改。** 不把第二任务记为用户误操作、自动重发或外部自动化。本文不改 Codex 核查文件、`docs/tasks/current.md`、`AGENTS.md`、规格或人工记录。

**未触碰当前 human 现场（PID39652／窗口33490664／controller39088／observer15128／根 `build/desktop-d2/manual-ai-sleep-human-20261020-192237`）、其他 human／体验根、当前控制文件或 API；未调用真实 AI、未发布、未 commit/push。**

## 1. 现场事实（独立证据，只读）

证据根 `%TEMP%/kgm-d2-w6-sleep-human-20261020-192237/`（SQLite 仅 `mode=ro`）：

| 事实 | 值 |
| --- | --- |
| 19日任务 | `rwlN3diXZNL9Ivnodxyg4Q`，plan `KIukEWstt2Ib-gxSaDeYWw`，`daily_process_adapt`，input `8jnkjatmd9Um-MTakCmZsw`（v11），创建 `11:26:34.805870Z` |
| 19日回执 | `ai_task_create`，request_id `c54c0106-1483-442e-91f9-bf7bcdc2923b`，结果明确 plan19/v11 |
| 20日任务 | `IrypyV2j9Icgnvm5GYsjRA`，plan `CwwsZ-emVqP6UPTvJTMJZA`，`daily_process_adapt`，input `8zUMGVvhJy1xOlMh8C1RhA`（v2），创建 `11:26:51.598641Z`（距首项 **16.793s**，早于首睡 `11:26:56.925Z`） |
| 20日回执 | `ai_task_create`，request_id `d804ffca-6e9f-4985-a081-17c8da6c1698`，结果明确 plan20/v2 |
| 执行 | 两项各 generation 1、各 1 execution／1 attempt；无 retry／resume／cancel 回执；均 `timeout_after_dispatch`／`outcome_unknown` |
| 20日计划 | 创建于 `2026-10-19 23:02:25`、v2 保存于 `23:02:46`，正文为“W6合并第二份／合并第二份：检查新页起始与内容完整。”——即第二项输入的真实来源 |
| 启动配置 | `launch-plan.json`：`mode=human`、`auto_trigger=false` |

用户明确“没有，我只点了19日一次”。两个 create 分别对应 19日 v11／20日 v2，request_id 不同，且都发生在睡前；这些事实成立。**两个不同 request_id 只能说明这不是同一 key 的回执重放，不能排除客户端以新 key 再次创建任务的任何缺陷。**

## 2. 已检查源码范围（只读；codebase-memory 仍 Transport closed，按技能直接读源码）

以下只是**已检查范围**的观察，不是对原现场全部执行路径的穷尽证明：

- 客户端唯一 `POST /api/daily-plans/{plan}/ai-tasks` 站点为 `frontend/src/d1/views/AiTaskPanel.vue::submitCreate()`；调用者是 `trigger()`（按钮 `@click` 与验证钩子 `__d1AiTasks.trigger`）与 `resubmitCreate()`（显式同 key）。`resubmitCreate` 复用原 request_id；本次两项 request_id 不同，不能据此解释来源。
- `trigger()` 每次生成一个 `crypto.randomUUID()`，并在 `saveCurrent()`／`nextTick()` 后复核 `props.planId === planAtStart`（及 `createSeq`、`frozen`）；任一不符即 return。
- `App.vue` 以 `${planDate}:${mode}:${planId}` 为 key 挂载 `EditorView`；`AiTaskPanel` 无自动触发 watcher/timer（仅轮询 `refresh()` GET）。
- 生产 API 路由之外：`desktop/d1_main.py` 的限定自检与 `desktop/d2_w3_probe.py` 也会直接调用 `ai_task_service.create_task`；**本次实际 human CLI 未启用这些自检／探针参数**。不能用 `grep`/`head` 的输出冒充全仓穷尽证明（`recover_on_start` 只做冷启动分类、不创建任务，这一点按其函数体确认）。
- 人工入口 `d2_manual_ai_main.py` human 模式无 driver／func／watchdog；`verify_d2_manual_ai.py --mode human` 只准备克隆与配置并等待。

**已检查范围内未发现**：一次 19日页面点击直接创建 20日任务的路径；也**未发现**自动重试或服务端自动新建任务的路径。但**源码静态检查不能证明原现场绝无应用路径**；根因仍未定位。

## 3. 已检查范围与未知边界

**已检查范围（未发现，不等于排除）**：

- 服务端生产 API 之外的自动创建：`recover_on_start` 只分类；但 `d1_main.py` 自检与 `d2_w3_probe.py` 的直接调用说明“全仓只有 API 调用”的说法不成立；本次 human CLI 未启用它们。
- 同 key 回执重放：两个 request_id 不同，说明不是同一 key 的重复提交；不能说明没有以新 key 的第二次创建。
- `EditorView` 按日期/计划重建、`trigger` 内复核 `planId`：这是已读代码的现状，但原现场的实际组件轨迹、DOM 事件与 actor 未记录。

**未知／不能排除**：

- 是否存在第二次 UI 触发（新 key），其来源可能是真实点击、验证钩子、其他进程/自动化，或当时页面处于 20日计划；**没有 actor／DOM 事件关联记录**，无法区分，也不归因给用户或外部自动化。
- 第二项输入是 20日计划真实 v2 内容（该计划 10-19 23:02 已存在），不是伪造或跨计划错配。

因此：**尚无根因、未修复、未复现**；不猜测性改代码，不新增教师确认，不改变流程。

## 4. 下一步：Codex 零代码独立诊断（本会话不执行）

由 Codex 执行，OpenCode 不运行该场景、不操作任何 human 根／API／控制文件／窗口：

1. 当前现场已留证；Codex 正常关闭当前窗口（已无活动任务、已同步），保存 exit 报告，不强杀、不清库。
2. 用现有 `desktop/verify_d2_manual_ai.py --mode human`，从受保护原 `build/desktop-d2/manual-ai-h06-r01-human-20261019-212522` 根作**只读一致性 backup** 到新的独立合成根，仍用 R01 完整包（`209dedcd…`）。
3. Codex 仅用 Sky 记录**一次 19日适龄按钮点击**的 UTC 时间、当前窗口与日期；随后分两段观察：
   - 不切日，等待原页；
   - 仅切换到 20日、**不再点击任何任务按钮**；
   核对是否出现第二个 `ai_task_create`、request 计数、attempt 及内容。
4. 此诊断是 Codex 工程诊断，不是教师人工验收；**单次未复现也不能关闭 R03**。若出现“无对应点击的第二次 create”，再按可复现缺陷交回本会话做最小修复与针对性验证。

**不采用**为本次定位修改业务数据库 schema（如新增页面 ID 列／迁移）：不为该问题扩大 schema，随机页面 ID 也不能证明教师动作。

## 5. 本轮实际改动与验证

- **无代码／测试／构建改动**；未运行产品测试或重建包（无缺陷可修）。
- 只读分析脚本与输出在 `%TEMP%/opencode/`（`h06_r03_analyze.py`／`h06_r03_analyze.out`），不在仓库；未写 human 根／控制文件／API。
- 归档包仍为 EXE `209dedcd5dfc4c8995478fc36146ae744ee653570ea318a54b25817b73a56c1b`；源码 `AiTaskPanel.vue c2ced7205cdf0ee2`／`EditorView.vue 0d8e727948332acc`／`App.vue 0613248bc8977222` 与证据基线一致（`h06-r03-source-before.json` 206 文件保留）。

## 6. 状态

- H06-R03：**根因未知／未修复／未复现**；等待 Codex 第 4 节零代码独立诊断，或新的可复现现场。
- H06-R02 白屏仍开放；G13 跨期限睡眠未覆盖；G17 真实 AI／D2 整体／发行未通过；已通过的人工项保持。
- 停止实现／测试／构建写入，供 Codex 核查。
