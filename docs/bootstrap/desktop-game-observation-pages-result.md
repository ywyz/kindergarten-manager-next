# D4：E09／E10 本机 API、观察编辑与查阅列表实现结果（最终）

更新：2026-10-28。状态：**Codex 最终独立审核已通过（review §6，R01–R15 全部关闭）；按用户授权由本会话正常提交推送后停在本片。** 本文件前四节保留 OpenCode 实现与自测身份，Codex 独立结果另列；先前中断不记为通过。

基线 `62f1fc6`，分支 `codex/desktop-v2-foundation`。本轮按 `docs/bootstrap/desktop-game-observation-pages-review.md` §4–§4.7 R01–R15 回修；独立审核意见及窗口证据由 Codex 维护，本文前四节只记录 OpenCode 实际实现、自测与未验范围，§5 引用 Codex 最终独立结论。未调用应用真实 AI，未构建冻结包，未修改凭据／体验库／OneDrive 原件／旧包，未新增依赖／Skill／MCP／架构。

## 1. 实际文件与行为

| 文件 | 本轮行为 |
| --- | --- |
| `backend/app/local/observation_api.py` | 受保护观察 HTTP：创建／列表／当前稿／保存／回执、照片 multipart 导入／说明／顺序／移除／认证二进制、历史／恢复／回执、AI 任务／候选／预览／采用；严格单文件 multipart（终止边界必需、行首分隔、拒绝尾随字节）、线程池执行导入解码／SQLite、观察域 AI 错误映射（`OBS_AI_SOURCE_CHANGED`／`OBS_AI_CONTRACT_INCOMPATIBLE`／`OBS_AI_CANDIDATE_STALE`）、`ack_duplicate_cost` 仅接受真布尔。 |
| `backend/app/local/observation_service.py` | 列表投影：日期范围可省略（无日期记录可见）、学期／未归属／类型／姓名（JSON1 `json_each`）筛选、分页；不读 draft、不迁移归属。 |
| `backend/app/local/observation_ai_service.py` | 候选按 `created_at DESC, id DESC` 返回并支持 cursor 分页；新增只读 AI 提交回执读取；不重发 AI。 |
| `backend/app/local/ai_task_service.py` | `list_tasks` 增加 `observation_id` 过滤，保留 `source_kind` 默认 `daily_plan`；全局两来源任务可查。 |
| `backend/app/local/api.py` | 恢复 `/api/local/ai/tasks` 固定 daily 与 `LocalAITaskListOut`；新增受保护 `/api/local/ai/observation-tasks` 供观察／全局关闭统计，不放宽旧 daily 响应。 |
| `backend/app/local/schemas.py` | 观察创建／保存／材料／历史恢复／AI 任务／候选请求模型；观察响应模型。 |
| `frontend/src/d1/views/ObservationsView.vue` | 默认全部日期；显式日期范围、学期／未归属、类型、姓名、分页；创建保留原 request id，未知结果先查创建回执、同请求重试；创建在途／未知时禁止离开并上报页面 busy。 |
| `frontend/src/d1/views/ObservationEditorView.vue` | 手工资料／四栏／五领域编辑；共享保存队列；auto 后待保留节点在 leave 提升；caption 纳入 dirty 与保存；材料串行、先保护正文；保存／材料／采用／恢复／AI 未知状态保留原请求并阻止离开；AI 提交意图在保护性保存前占用；采用预览绑定候选／targets／epoch，失效即清；历史整份预览（基本资料、类型、年龄、四栏、五领域、本版照片顺序／说明）；显式学期归属调整；照片 Blob 分代、取消、错误重试、URL 回收。 |
| `frontend/src/d1/observation.ts` | 表单／canonical payload 适配；安全整数（拒绝精度丢失／溢出，不新增业务上限）；重写候选 `raw.text` 显示；目标／学期选择 helper。 |
| `frontend/src/d1/observation-photos.ts` | 有界对象 URL 缓存；`invalidate` 使在途读取失效；pending token 防止旧请求删除新请求；释放／回收。 |
| `frontend/src/d1/App.vue` | 关闭任务探测分页读取旧 daily 与独立观察端点；写提交 busy 与持久 AI 运行分开；页面 busy 绑定宿主页票据与正 seq，处理乱序／旧页迟到／重复 ready／失败重试与最新末态接管；列表／编辑器切换复位陈旧 busy。 |
| `frontend/src/d1/bridge.ts`、`desktop/d1_host_api.py`、`desktop/d1_main.py` | `get_bootstrap` 签发页票据；`page_ready`／`set_page_busy` 绑定当前票据与正 seq，旧页拒绝、同页幂等、宿主加锁原子；`busy_probe` 合并原生保存与页面写 busy；新增 `obs-ui` 真实 WebView2 验证相位。 |
| `desktop/verify_observation_pages.py` | 可独立 `--data-dir`／`--output-dir` 的真实本机 HTTP 验证入口（合成库／图片、假 worker，无真实 AI）。 |
| `desktop/verify_observation_window.py` | 可独立 `--data-dir`／`--output-dir` 的真实 WebView2 验证入口（真实工作台按钮／列表／编辑器／文件输入上传／历史／冲突／离开）。 |

## 2. R01–R15 回修对应

- **R01** 列表不再默认带当前月 from/to；默认全部日期，显式范围才传 from/to；学期／未归属筛选不受月份裁切；无日期记录可见；列表增加创建时间列，同日同字段多份可按创建先后与稳定 ID 辨识。新增 `test_list_without_range_keeps_no_date_and_old_term_records` 与组件 R01/R02 检查。
- **R02** 创建保留 `request_id`、类型、日期；网络未知先 `GET /api/observations/operations/{request_id}` 读回，不新造 UUID；同请求重试由服务端幂等读回；重叠学期 `OBS_TERM_DECISION_REQUIRED` 显示明确学期选择并以同一 request id 提交 `term_id`。列表创建在途／未知通过 `busy` 上报 App，纳入关闭／离开保护。新增创建回执、重叠学期 HTTP／组件检查。
- **R03/R06** 观察 adapter 的 `isDirty` 改为 `needsSave = 表单 dirty || caption dirty || 待保留节点`；无历史时按“最近节点不存在”即待留，只有基本资料也留史，不用 Word 空记录门槛；`applyPhotoResult` 改 revision/hash 时同步待留；重复 unchanged auto 不抹掉先前待留；manual／leave 与 auto 共享 in-flight 时先等 auto 再以更强原因重存；identity 含模块／record／epoch；当前稿读回 `latest_version_hash`。新增 auto→leave、auto in-flight→leave、基础资料留史、caption-only 待留检查。
- **R04/R15** 预览采用前先 `settle`／保存当前稿并确认 `needsSave` 为空；预览记录候选、targets、epoch；切目标、切候选、任何晚到正文编辑立即清预览；根节点只对实际草稿模型事件提升 epoch，审核 checkbox 的 DOM change 不再清预览；提交前再次校验候选／targets／epoch／revision／hash；差异区显示教师可读的 before／after 与“来源已变化的资料”中文标签，不显示原始 JSON／英文 enum。**评价分析比较按固定健康、语言、社会、科学、艺术逐项中文显示原值，空项保留标签，多行原文不改；候选缺项把 `analysis_evaluation.<领域>` 映射为“评价分析·健康”等，候选缺项标题改为中性“生成时未填写的内容（供核对）”，不暗示禁止采用、不增加确认或教师补全步骤。** 新增真实 DOM checkbox、五领域比较渲染、缺项标签、目标切换／晚到编辑失效检查。
- **R05** 保存未知保留 `request_id`、原 expected revision、payload、photos、save_reason、term_decision／selected term 与提交时 epoch；读回用原 epoch，不用当前 epoch 覆盖晚到输入；重试发送完整原请求。材料／采用／恢复／AI 提交未知分别保留待核对请求与正确回执域；未知期间 `blockingDraft` 阻止离开／关闭；恢复预览冻结完整 term／token／base 请求，改选学期立即失效并需重新预览；AI unknown 不再提供清除 guard 后新 UUID 重发的“放弃”路径，只能查回执。**AI 提交意图在第一次保护性保存 await 之前占用**：快速两次生成／重写触发共享一次保存但只创建一个任务；保存失败／取消／晚到输入释放意图；准备意图只覆盖保护性保存＋POST 确认／未知，POST 确认后即释放，只读 poll 只保留 `aiBusy`，不跨整个 AI 运行期阻断关闭；已持久化 AI 运行不计入页面写 busy，正常关闭任务选择仍可达。新增晚到输入读回、原请求重试、采用／恢复未知读回、恢复改选失效、快速双击只 POST 一次、claimed 运行期 page-write busy=false 检查。
- **R06** caption 纳入 `captionDirty`／`needsSave` 并由共享保存队列携带 `photos` 保存；排序／移除／导入先保存正文，再经单一 `photoBusy` 串行；`photoBusy` 进入 `writeBlocked`／`blockingDraft`；失败／未知保留本地稿与待核对请求。新增 caption 共享保存检查。
- **R07** 初始 load、保存回读、候选详情、候选列表、历史详情、照片分组均带请求代次；保存回读同时核本地当前 revision/hash、响应 revision/hash、observation id、epoch、save generation，材料操作后旧保存 GET 不能回退；旧候选／旧历史／旧照片响应只读丢弃。新增旧候选／旧历史、材料后迟到回读检查。
- **R08** 页面 mount 分页读取全部持久任务（含超页 latest／live／unknown），只读轮询在途任务，不触发 AI；任务列表／轮询带页面与任务代次，旧列表不切回旧任务、旧失败不清新 busy；进度按 execution／attempt／seq 丢弃旧响应但始终处理本次已读到的 succeeded／failed 等终态，available=false／seq0 不吞终态；默认展开可折叠思考、阶段与已等待时间。候选最新优先、cursor 分页。新增超页任务、迟到进度、终态无进度检查。
- **R09** `candidateTargetText` 对 rewrite 使用 `raw.text`，generate 使用四栏／五领域真实 schema；采用路径沿用服务端 `_candidate_value`。新增 rewrite text 检查。
- **R10** 历史详情显示类型、日期／时段、园所／班级／观察者、人数／统一年龄／环境、重点幼儿、观察目标、观察记录、五领域、支持策略，以及本版照片顺序／说明和受控缩略图分组；不使用当前照片代替历史照片。历史详情请求带代次。
- **R11** 本份资料区新增“调整学期归属”，无日期／未归属记录可直接选择 keep_current／assign_selected／unassigned，保存后刷新归属；不修改档案配置。
- **R12** 旧 `/api/local/ai/tasks` 固定 daily 与原 `LocalAITaskListOut`，另设 `/api/local/ai/observation-tasks`；App 关闭 probe 分别读取两来源。页面 busy 只包含提交／写操作在途与未知，不包含已持久化 AI 执行；`get_bootstrap` 签发宿主页票据，`page_ready`／`set_page_busy` 均绑定当前票据与正 seq，旧页面 ready／busy 拒绝且不清当前屏障，同页重复 ready 幂等，宿主校验与更新加锁原子；新握手前不清屏障。`page_ready` 先校验票据／legacy 资格，再调用 `ready_receipt.confirm`，无效／旧／缺失票据不产生就绪副作用；已进入票据页面模式后，下一次 bootstrap 待绑定期间无票据 legacy ready 也被拒绝。失败／拒绝的最终状态由最新 seq 接管重试责任，旧 timer 不吞最新末态，卸载后不重启。桥白名单精确加入 `set_page_busy`。新增 A/B 迟到旧 ready／false、重复当前 ready、无效票据／seq、并发通知、连续丢包最终 false、无效票据不触发 confirm 检查。
- **R13** multipart 严格解析（终止边界必需、行首分隔、拒绝尾随字节／重复字段／多文件／非 binary 编码）；上传路由用 `run_in_threadpool` 执行同步解码与 SQLite；`ack_duplicate_cost` 字符串 `"false"` 不再被当作确认；观察 AI 来源错误映射为观察域错误码。新增缺终止边界／尾随字节／分隔子串保留／字符串 false HTTP 检查。
- **R14** 照片缓存加 generation、pending token、AbortController 与有界 pending；等待队列前绑定 generation，等待后复核 disposed／generation／同 asset pending；切组／卸载 abort 在途 fetch 并丢弃迟到结果；组件按 chunk 代次只应用当前结果；坏图显示错误与重试；仍按 8 张分组，600 图上限不变。新增在途取消、队列等待切组、同 asset 并发检查。
- **R15** 数字字段只接受 `^\d+$` 且 `Number.isSafeInteger`，拒绝溢出／精度丢失；日期／时间组件显式触发编辑代次与自动保存；不增加年龄业务上限；页面显示 AI 前非阻断资料缺项、重点幼儿／年龄／环境／照片最低门槛、姓名数大于儿童总数、结束早于开始等可读提示，并显示候选来源缺项／warning 事实；保存／手写不被这些提示阻断。新增溢出、字段反馈、矛盾提示检查。

## 3. 自测命令与实际退出码

统一解释器：`desktop/.venv-d1/Scripts/python.exe`（CPython 3.14.7 Windows x64）。

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 前端类型检查 | **exit 0** | `r07-typecheck.log` |
| 前端全 d1（自然退出） | **exit 0；观察专项 38 项** | `r07-frontend-d1.log` |
| 观察专项单跑（自然退出） | **38 项 / exit 0** | `r07-obs.log` |
| 后端／桌面／HTTP／窗口 | R06 已绿；本轮仅改前端显示 formatter／标签／文案，未重复全量 | `r06-*`（保留） |

真实 HTTP 验证入口：

```powershell
desktop/.venv-d1/Scripts/python.exe desktop/verify_observation_pages.py `
  --data-dir <独立合成数据目录> --output-dir <独立证据目录>
```

真实 WebView2 入口：

```powershell
desktop/.venv-d1/Scripts/python.exe desktop/verify_observation_window.py `
  --data-dir <独立合成数据目录> --output-dir <独立证据目录>
```

两者均支持独立 `--data-dir`／`--output-dir`；窗口入口需已构建 `build/desktop-d1/frontend`，不调用真实 AI，不触碰原凭据／体验库。

## 4. 合成隔离与未验

- 自动验证使用独立临时数据根、合成凭据根、合成 JPEG；真实 HTTP 用合成 profile；AI 使用假 spawn worker／合成 provider 路径，无外部网络。未读取或改变原教师数据、原配置／凭据、OneDrive 原件、旧包。
- 本片验证的是 E09／E10 创建／编辑／查阅及支撑 E12 本机 API；批选、跨页选集、列表手调排序、E11／E12 Word／另存为、E14 整包后置。
- 完整 A01–A22、教师产品体验、复杂真实照片效果、MiMo 真实调用、Win10／WPS／干净机器／其他 DPI／显示器、跨设备、真实冻结更新／安装、发行源／4551、签名／WebDAV／发行均未验。
- 桌面 update U2 fixture 已对齐合成目标 revision 0006；短 basetemp 下 30 项 U2 全通过，身份／nonce／service／page／rollback 负断言保留。未启真实更新安装或发行。旧 daily 响应保持来源边界，真实窗口基本闭环不替代完整 E10／产品验收。
- 真实 WebView2 9 项只覆盖 r06 合成基本路径；实际轮次为 **r01／r03 中断 exit 1**，**r02／r04／r05／r06／r07 自然 exit 0**；中断轮次不记为通过。r04 的 HTTP 37／后端 160／daily 81、r06 的宿主 94／窗口 9 为实现者前轮结果；R01–R15 的逐项反例见第 2 节及测试文件，不能据此宣称完整 E09／E10 或 A 项通过。

## 5. 最终独立结论与交接

- **Codex 最终独立审核通过**：见 `docs/bootstrap/desktop-game-observation-pages-review.md` §6，R01–R15 全部关闭。独立执行全 backend local **728 passed／724.30 秒／exit 0**、全桌面 **285 passed／52.74 秒／exit 0**、最终全前端自然 exit 0（观察 38）、typecheck／独立构建 exit 0、真实 HTTP **37/37**、源码 WebView2 **9/9**；实际窗口中文五领域预览、勾选保留、四目标采用保存 v14、列表新环境及正常关闭 exit 0；本片应用真实 AI **0 次**；407 来源路径最终一致，f01→f02 仅两前端文件变化。
- **证据身份区分**：本文前四节为 OpenCode 实现、自测及故障反例；§6 的 728／285／HTTP／窗口与人工采用结果为 Codex 独立执行，不以本文件自测替代独立结论。
- **中断事实更正**：实际 **r01／r03 中断 exit 1**；**r02／r04／r05／r06／r07 自然 exit 0**。先前中断轮次不记为通过，r03 测试入口挂起已修复为自然退出。
- **历史未验保持**：完整 A01–A22、教师产品体验、复杂真实照片、MiMo 真实、Win10／WPS／干净机器／其他 DPI／多显示器、跨设备、真实更新安装／发行源／4551、签名／WebDAV／发行未验；批选／跨页选集／手调排序、E11／E12 Word／另存为、E14 整包后置。
- **交接**：本片限定工程通过；按用户授权由 OpenCode 正常提交并推送当前分支，不 amend／强推／空提交；提交后停在本片。本文件不填写提交自身 hash，避免为补 hash 产生第二次提交。
