# D4：E09／E10 本机 API、观察编辑与查阅列表独立核查

> 公开版隐私处理（2026-10-30）：本机用户路径、私有部署地址或联系标识已替换为占位符；原始记录由维护者私下保留，历史日期、结论和产物哈希不因此改变。

更新：2026-10-28。状态：**E09／E10 本机 API、观察编辑与查阅列表限定工程核查通过，R01–R15 关闭；按用户授权由原 OpenCode 正常提交推送后停在本片。** 最终结论见 §6。本文件由 Codex 维护；实现者自测与独立执行结果分开记录。

## 1. 授权与基线

用户明确授权开始 E09／E10 本机 API、观察编辑和查阅列表，批选／排序及 Word 导出后置。继续由原 OpenCode 使用 Go 套餐 DeepSeek V4.1 Flash max 实施，Codex 独立审核，问题交回修复直至通过，最后由 OpenCode 提交推送。此授权替代前轮仅规划边界，不扩展真实应用 AI、冻结包、安装更新或发行。

分支 `codex/desktop-v2-foundation`，基线 `62f1fc6f4a442e1fdc3038b52cb7203e796636dc`，开工前工作区干净。Codex 先更新唯一任务入口及工程 §10.1，再交原会话实施。原会话 `ses_ead8af71dffeJphI1NOWg4jZgI`，本机 CLI 2.1.4，standalone、build、显式 `opencode-go/deepseek-v4.1-flash#max`；未另建／fork 会话、实现者、子代理或分支。

证据根：`<LOCAL_USERPROFILE>/AppData/Local/Temp/kgm-observation-e0910-20261027-a5fc7fa5`，指针 `%TEMP%/kgm-observation-e0910-current.txt`。派发前保存脱敏 session 导出（5142 条消息）和 517 个已跟踪文本路径 SHA256 基线。该 manifest 不含凭据路径，不宣称覆盖全盘／用户数据。OpenCode 使用 `opencode-evidence`／`opencode-temp`，独立审核使用 `codex-independent`；不将自测身份与独立证据混用。

## 2. 本片审核范围

- 本机路由的 Host／Origin／Session、服务端 profile、错误信封、来源隔离、业务与 AI 回执域、材料受控读取及诊断脱敏。
- 实际工作台入口、三类型创建、资料／四栏／固定五领域、自动／手动保存、同日多份与重新打开；无 AI 配置及失败下的手工闭环。
- 当前材料顺序／说明／移除、认证二进制 Blob、有界加载与 URL 回收；不修改 600 图技术上限。
- 合成任务／候选审核、单栏重写、按栏／整份采用、来源变化决定、历史同版预览与整份恢复，明确 revision／hash／token 绑定。
- 观察 adapter 同时处理待保存输入与待保留节点；IME settle、串行保存、丢回包读回、冲突／unknown 留页、晚到输入与旧响应隔离。
- 未采用观察候选允许保留离开；导入／采用／恢复忙状态与现有 close 代次、busy_probe、更新退出协调。旧日计划查询保持来源契约，全局关闭统计覆盖两类任务。
- 日期范围、学期／未归属、类型、姓名与分页查阅；筛选不改归属，同日多份可区分，旧学期可查改。

## 3. 图谱与源码证据边界

按仓库要求使用 `codebase-memory`，项目 `C-Users-yw980-code-kindergarten-manager-next`。初始索引为 `2026-10-27T08:15:52Z`，后自动刷新为 `2026-10-27T10:03:50Z`。已查询观察保存／恢复、离开及任务列表符号，并读取 `save_observation`、`list_tasks` 片段及 `probeLiveTasks` 的双向一跳关系；该探针由 `finishClose` 调用。

已对 app、api、观察 service/assets/history/AI、App.vue、leave.ts、WorkbenchView.vue、client.ts、ai_task_service.py、ai.ts、d1_host_api.py 共 13 路径检查 coverage，均无记录缺口，但 freshness 为 `metadata_changed`。已定向回读上述相关源码，不能据图谱结果声称完整影响分析。初始泛化符号搜索未穷尽分页，不用其作否定性结论。

第二轮针对 24 个相关路径完成 coverage 两页（20＋4，generation `2026-10-27T11:43:41Z`），均为 no_recorded_issue／metadata_changed，继续直接回读源码而非把索引当作最终版本。r02 完成后脱敏会话审计，从开工前 5142 条到 5518 条消息：带模型元信息的新增消息均为 `opencode-go/deepseek-v4.1-flash`、variant max；代理均 build；工具仅 edit／shell／write。消息数不等于供应商请求次数；最终仍需覆盖后续回修及 Git 阶段审计。

## 4. 回修与独立执行

首轮初审不通过。OpenCode 实现后在下一次模型响应等待中停留，尚未自然交付结果文件；Codex 对当前落盘代码保存 378 路径来源指纹并独立执行观察接口 6 项、组件 10 项、typecheck 及独立前端构建／真实 WebView2 基本手工窗口（9 个驱动检查），均 exit 0，378 路径前后 hash 全部一致。该窗口只证基本创建、编辑、材料、恢复、冲突与离开路径，不覆盖下列全部时序或完整 A 项；最终冻结及全量检查仍待回修后执行。

18:41:50 后原 run 连续 620 秒无新增事件／文件变更，末次为已完成的只读报告检查。Codex 核对本次 CLI 13580 及其私有服务 20804 的路径／父子身份后，仅停止私有服务，原桌面后台 34156 保留；原 CLI 实际 exit 1。`r01-interruption-recovery.json`、JSONL、stderr 和 exit 保留。随后同一 session、同一指定模型／build 接续 r02 并正常产生新事件，不把旧 `info.outcome=succeeded` 当作本轮完成，也未另起会话或实现者。

初审问题按实际代码与既定 Contract 归组，未修复前不得提交推送；同组的失败／重试与回归验证须一并补足。

| 编号 | 初审问题与要求 | 主要路径 |
| --- | --- | --- |
| R01 | 列表 query 始终带当前月 from/to，导致无日期记录永不可见、选择旧学期仍被当前月裁切。接通明确日期范围／不限定日期；学期及未归属完整可查，筛选不改归属。 | ObservationsView.vue |
| R02 | 创建失败后重新点击即新 UUID，无未知提交读回；创建在途也未纳入离开／关闭保护。保留原请求及 request id，按创建回执核对再决定重试，禁止一次创建因丢回包意外多建。 | ObservationsView.vue、observation_api.py |
| R03 | bridge.isDirty 只看表单，auto 成功后离开会漏留历史；manual／leave 加入 auto 在途也只分享 auto 结果。观察 adapter 同时追踪待保存输入和待保留节点，串行提升保存原因，identity 含模块／record／epoch。 | ObservationEditorView.vue、observation.ts |
| R04 | 采用预览及提交未先 settle／保存 UI 当前稿；预览后勾选目标或切候选不使预览失效，来源变化也未展示实际 diff／before／after。保存当前稿并绑定候选／targets／epoch，明确呈现所复核差异，防止采用覆盖未保存手写稿或应用旧目标集。 | ObservationEditorView.vue |
| R05 | 保存未知状态未保留原 epoch、归属决定及完整请求；读回却传当前 epoch，可能覆盖晚到输入。材料／采用／AI 提交／恢复的未知结果也缺少统一的待核对请求与正确域回执，busy 清除后可离开。按不可变原请求读回／重试，保留新输入并如实阻止未核实放行，不重放 AI。 | ObservationEditorView.vue、ObservationsView.vue、observation_api.py |
| R06 | caption／顺序／移除绕过保存队列，photoBusy 未进入 writeBlocked／bridge，caption 本地输入也不参与 dirty／完整保存。材料操作先保护当前稿并串行，说明失败留稿、正确更新 revision/hash，协调离开与关窗。 | ObservationEditorView.vue |
| R07 | 保存后异步 readback 未确认当前 revision 仍对应请求；历史详情选择无代次；部分旧请求及重新载入可覆盖更晚内容。所有实质回写按身份／revision／hash／epoch／请求代次复核，旧结果只读保留或拒绝回写。 | ObservationEditorView.vue |
| R08 | mount 只 load 当前稿，不加载持久候选／任务；候选列表 oldest-first、限 20／50／100 且 next_cursor=null，超页新候选在重开后不可达。补可分页或明确完整查阅，并恢复持久任务／unknown 状态；普通重开不触发 AI。 | ObservationEditorView.vue、observation_ai_service.py、observation_api.py |
| R09 | candidateTargetText 按 raw[target] 读取单栏文本重写，但既定服务返回 raw.text。三类文本重写显示为空。严格按四种 target 的真实生成／重写 schema 渲染，测试显示及采用一致。 | observation.ts |
| R10 | 历史界面只显示过程、日期和照片数量，缺本版基本资料／类型／年龄、其余正文及本版照片／顺序／说明。补整份可见预览和有效日期／归属，不能以当前照片代替历史照片。 | ObservationEditorView.vue |
| R11 | 现有无日期／未归属记录没有明确选择已有学期的入口，只能等日期变化触发对话框。补既定归属操作；本份日期／归属决定、取消／失败及保存后 UI 均保持一致，不修改档案配置。 | ObservationEditorView.vue |
| R12 | App 的关闭 probe 仍只读 daily 任务，未覆盖观察来源；观察创建／照片等写忙状态也需进入 busy_probe 和既有更新退出协调。保持旧 daily 响应，补全局两来源检查与真实关闭／忙状态回归。 | App.vue、observation_api.py、既有宿主协调 |
| R13 | 新 multipart 解析按原始 delimiter 字节直接 split，未要求终止边界；async 上传路由内直接做同步解码／SQLite；retry 的 bool(data.get(...)) 把字符串 false 当确认。补严格有界字节保持解析／截断拒绝、执行时服务响应性、类型化变更协议及观察来源错误映射，旧 daily 不变。 | observation_api.py、schemas.py |
| R14 | 照片 chunk 读取无代次／错误处理，pending 不因切组失效，旧请求可重新占缓存及覆盖当前 URLs；坏图会停在加载中。补有界在途请求、旧响应回收／取消与可见错误／重试，600 图仍可逐组访问。 | observation-photos.ts、ObservationEditorView.vue |
| R15 | 数字字符串直接 Number 可无声取整或 Infinity→null；自动保存／epoch 只靠根 DOM input/change，日期／时间等组件选择未可靠覆盖。明确技术数值错误并保留输入，所有实际模型修改均纳入保存及代次测试，不增加年龄业务上限。 | observation.ts、ObservationEditorView.vue |

恢复预览先设置自身 busy 再调用 saveCurrent 的初稿阻塞已被 OpenCode 在自测中调整，不再作为未解决项重复交回；其完整未知／晚到输入保护仍包含于 R05–R07。旧历史跨进程测试两处固定预览时间过期已改用 utc_now，崩溃／回执／回滚断言保留；旧前端计时分支曾一轮失败，单独及第二轮全 d1 自测通过，最终独立全量窗口仍须记录实际结果。

R07／R08 的任务进度复用核对同时依据工程 §1“保留思考／阶段反馈”及[既有流式规格](../specs/desktop-ai-streaming-progress.md)的用户已确认规则：思考默认展开、可折叠，阶段／已等待时间如实显示，execution／attempt／seq 及旧响应隔离。此为接入既有反馈机制的核对，不另发 AI 请求，不添加预算或新产品确认步骤。

### 4.1 第二轮停写复审：仍未通过

原会话 r02 正常完成，实际 exit 0，最后答复明确停写、未提交推送。日期范围、创建原请求／回执、caption 聚合、候选分页／文本重写、完整历史预览、归属入口、严格 multipart 等已取得进展，但以下原问题尚未关闭，不以自测绿灯替代实际反例。

- **R01／R02**：列表仍不显示创建先后或稳定标识，同日同字段同版本的多份无法辨识，须按工程 §11 给出可用区分。创建遇重叠学期 `OBS_TERM_DECISION_REQUIRED` 仅显示错误，没有明确选择／归属提交分支；须保留创建原请求与幂等保护并完成既定学期决定。
- **R03／R06**：`applyCurrent` 无历史时用 Word 的 `observationHasContent` 判断待留节点，漏掉只有基本资料的实际聚合；服务原规则为最近节点不存在或 hash 不同，不以导出空记录门槛限制保存历史。`applyPhotoResult` 改 revision/hash 却未同步待保留节点；导入／排序／移除后无正文编辑就离开可能漏历史。`applySaveResult(auto)` 以本次 `changed` 覆盖标志，重复无变 auto 可抹掉之前仍应保留的节点。须按当前 aggregate 对最近节点一致判断，并补这三类反例。
- **R04／R15 实际窗口反例**：Codex 使用独立 HTTP 合成库／假 worker 候选及独立源码构建，在真实 WebView2 将环境改为“积木区复核”、保存、预览已有候选；source_changed 差异正常出现，但点击“已核对差异，确认按此预览采用”后，整块采用预览和提交按钮立即消失。根节点 `@input/@change=onUserInput` 把审核控件的事件当作正文修改并清掉预览。须只对实际草稿模型变更提升 epoch，真实 DOM 勾选能确认并提交，不能用直接调用方法的测试绕过冒泡。差异区目前为英文 target／source_changed、JSON 五领域及 changed_fields 字段名，须转成教师可读标签和可复核的来源差异事实，不用原始 JSON 代替。
- **R05**：restore retry 仍读取可变的 `restoreTermDecision/restoreTermId`，同 request id 的重试并非原 fingerprint；归属变化还须使旧恢复预览失效／重新绑定，unknown 时冻结或保留独立不可变原请求。`abandonAiUnknown` 直接清掉待核对请求和离开保护，不能把未知提交当作已核实，随后以新 UUID 触发另一调用；保留原回执恢复能力及既有未知／重复费用协议，不新增自行解释的放行步骤。
- **R07／R08**：重开只读 ascending 的 `ai-tasks?limit=20`，未读 next_cursor，超页最新／live／unknown 任务不可达。任务轮询无任务代次／execution／attempt／seq 校验；展示仍只有一段 phase/reasoning，缺已确认的默认展开可折叠思考及阶段／已等待时间。复用已核定机制并以合成进度／超页任务核对，不调用真实 AI。
- **R12**：旧 `/api/local/ai/tasks` 新增任意 source_kind 并移除 `LocalAITaskListOut`，违背本片明确“不放宽旧 daily 响应”的边界。恢复旧接口固定 daily 与原 schema，以独立观察／全局受保护端点提供关闭统计。`externalBusy` 包含整个 AI 运行期 `aiBusy`，宿主 busy_probe 会在出现正常的 live-task 关闭选择前拒绝退出；写提交 busy 与已持久化 AI 执行须区分。新 `set_page_busy` 仅传未版本化布尔、忽略接受结果，须处理乱序／迟到 busy 通知、page_ready 前初态及最终解除，不破坏既有 close generation。精确桥面白名单测试已因新方法失败，须同步审核 Contract 与准确集合，不能放宽为任意方法。
- **R14**：URL 缓存代次已补，但 invalidate 清 pending 并不取消 fetch，也没有在途上限；快速多次切组仍可积累旧请求。须有实际 cancellation／有界调度并覆盖迟到、错误及卸载，业务 600 图上限不变。

R12 回修的时序验点包括：最后一条 busy=false 若桥调用失败／回包丢失，应独立重试当前状态，不能等下一次页面变更才能解除；已接收较新序号后，缺失／零／负序号不得回退状态；重复或迟到的 page_ready 不能重置正处于写入的忙状态及其序号。若支持页面重载，须明确新页面身份／重新握手与旧通知的隔离，不以未绑定的 reset 绕过顺序。以上均沿用本组“乱序／迟到、page_ready 初态及最终解除”要求，以合成桥故障验证，不启真实安装。

R07 的保存回读须同时验证**本地当前 revision/hash**仍是该保存结果，仅检查回读响应 revision、save generation 和文本 epoch 不够：材料操作可以在同一文本 epoch 改变聚合，迟到的旧保存 GET 不能回退已完成的照片操作。R03 的最近节点 hash 也须在 manual 留史成功后立即更新，不能依赖可失败／迟到的异步 GET 才变得正确。

R07／R08 拒绝旧 execution／attempt／seq 的**进度响应**时，应继续当前任务的持久状态轮询，而非 return 整个 `pollTask` 并遗留 `aiBusy=true`；进度暂不可用／seq=0 时，也不能吞掉本次已读到的 succeeded 等终态。重开任务列表及轮询的成功、失败回调均须复核页面／任务代次，迟到的旧列表不能把用户刚提交的新任务切回旧任务，旧任务失败也不能清掉新任务的 busy。

R15 的字段反馈还须接通既定产品 C19／§2：园所、班级、观察者、日期／时段、人数等缺项在 AI 前提示而不阻止；姓名数大于儿童总数、结束早于开始等矛盾提示复核而不猜改。已有服务 `missing_fields`／`warnings` 与候选 source.internal_context 事实不能只持久化不向教师显示。现有页面仅处理恢复 warnings，AI 提交／普通资料区没有这些缺项及矛盾反馈；补非阻断可读提示，不增加额外审批，不将 AI 最低门槛或 Word 空记录规则套给保存。

r03 中间检查另发现验证入口不能自然退出：`node src/d1/d1.observation.test.mjs` 打印 31 项断言通过后，新增 claimed 任务的只读轮询仍存活；Codex 独立执行同样复现（`r03-components-interim.log`），不能把打印通过当作 exit 0。OpenCode 的该脚本子进程及 Codex 独立子进程均已通过路径／完整父链识别，原 OpenCode 桌面后台不在处置范围。须在测试结束正确卸载／停止轮询并等待收尾，验证真实自然退出；不要用 `process.exit(0)`、管道 tail/grep 的退出码或删去进度断言掩盖未清理任务。先前将等待解释为下一次模型响应，已由本次进程及独立复现证据纠正。

### 4.2 第三轮中断与剩余交接

r03 尚未自然交付。首次只停止 OpenCode 挂住的合成测试 Node 3280，原会话恢复后又启动同一未收尾入口，新的 Node 32352 再次持续轮询。Codex 独立 Node 38144 同样打印 31 项后不退出，人工终止实际 **exit -1**，不记通过。核对完整父链后仅停止 r03 私有服务 36412（父 CLI 19136）及其合成 Node 32352，CLI 实际 **exit 1**；桌面后台 34156 保留。证据 `r03-test-hang-recovery.json`、`r03-interruption-recovery.json`、脱敏导出及 `codex-independent/r03-interrupted-source.json`（378 路径）均保留。不是丢弃代码，也不是已完成交付。

停下时仍需同会话优先修复测试卸载并自然退出，接续 §4.1 后补验点：R07 当前 revision/hash 读回保护、任务恢复与轮询代次及“进度不可用仍处理终态”；R12 最终 busy 解除重试、拒绝无效序号、page_ready 重复幂等／页面身份与 0006 合成 U2 fixture；R15 已核定的非阻断字段反馈。R14 已加入 AbortController／maxPending，但排队 ensure 在 await 后才捕获 generation，且没有再次复核 disposed／原代次及同 asset pending，旧队列仍可在切组／卸载后新起读取；须补等待期间切组／卸载及并发同 asset 的反例。其他已修路径保持，最终全量和真实窗口仍等实际停写后执行。

R05 的 AI 提交互斥应覆盖第一次 await（settle／保护性保存）之前：`createAiTask` 当前先检查 aiBusy，再 await manual save，之后才置 busy 并创建 UUID；快速两次触发可共同等待同一个保存 Promise 后各造 UUID／发两份任务。须先占用提交意图、保护性保存不与自己的 busy 互阻，并以延迟保存＋两次真实触发验证只创建一份；已持久化 AI 的等待仍不阻断正常离开／关闭选择。

r04 中间独立宿主诊断（仅合成内存对象、指定临时根，无窗口／业务库写入）已复现 R12 跨页面缺陷：A ready 后 busy seq20，B ready 后 busy seq1，迟到 A 的 false seq21 被接受并将 B 的 busy 清为 false；迟到 A 的 page_ready 也被当新页面接受并再次清 busy。`page_instance` 只传 ready、未绑定 busy，不能形成旧通知隔离；证据 `codex-independent/r04-busy-page-diagnostic.json`。须明确拒绝旧页面的通知／握手，状态比较与写入在宿主并发桥调用间原子执行。还须覆盖 retry A 尚在排队时新状态 B 发送失败：当前 timer 仅在捕获 seq 等于最新 seq 时重发，而 B 看到旧 timer 不建新 timer，旧 timer 到期又因过时退出，会漏掉最终 B。替换／合并时保证最新末态仍有重试责任，不依赖教师再产生一次编辑。

### 4.3 第四轮实际停写复审：仅剩 R05／R12 阻断

r04 实际自然完成 exit 0 后，Codex 保存最终 378 路径快照 `r04-completed-source.json`；HEAD 仍为基线 62f1fc6，未提交推送。R07 读回／终态、R14 等待队列、R15 反馈及测试自然退出已取得相应回修和实现者反例；r04 的 HTTP 37／窗口 9 及观察 34 项为实现者结果，最终独立全量仍未开始。停写后的源码仍存在上文 R05“第一次 await 前未占用 AI 意图”、R12“旧页面解除／握手被接受”及“旧 retry timer 吞掉最新末态”三项阻断，不能因现有自测通过而关闭。

R12 本轮技术收敛保持原桥接机制与 close generations：以已有 get_bootstrap 签发的宿主页面代次／不透明票据绑定 ready 与 busy（或等价可证明顺序且不能被旧页面重新激活的方案），busy 同时绑定已接受页面及正序号；同页重复 ready 幂等，旧页 ready／busy 拒绝且不清状态。宿主线程间验证及更新原子；新页面握手前不随意清当前屏障。可保持旧 D1 不使用新 busy API 的握手兼容，但新 busy 不接受无绑定的变更。此为现有页桥内的参数／时序补全，不引入组件、架构或教师确认步骤。最新状态须接管／替换旧 retry 的责任，卸载丢弃迟到重试。只回修这些剩余问题及直接相关验证，保留其余已修路径，停写后由 Codex 执行最终全量。

独立执行 r02 HTTP 37/37、观察组件 24 项、typecheck、独立前端构建均 exit 0；这些执行开始时的 378 路径 manifest 后，编辑页仍被 OpenCode 修改，故只记中间结果，不是最终冻结通过。上述手动 UI 另以停写后的 `r02-ui-frontend` 构建进行，未生成／采用新的 AI 请求；窗口已正常关闭。

宿主回归不得笼统排除：实现者报告的 20 个失败中包含新增桥面集合失败，另有深 TEMP 引发的 Windows 长路径异常。Codex 用独立短根 `kgcx-e0910-68201dbd` 与显式 `--basetemp` 重跑 U2，实际 **26 passed／4 failed，exit 1**，证据 `codex-independent/r02-u2-short.log`。残余四项涉及真实合成进程 ready／身份链；测试 `HEAD_REV` 仍固定 0005，当前 runtime 已升级到前片已核定的 0006，需对齐合成 fixture 的目标 revision 并保留原身份／nonce／service／page／rollback 否定断言。只修相关合成验证，不改 OS 长路径策略、不启真实冻结安装／发行，不用 skip 或削弱断言接受失败。

### 4.4 第五轮停写：票据隔离已复核，R12 两处待修

r05 自然完成 exit 0。Codex 用真实宿主及合法签发 A／B 票据重做相同序列，A 的迟到 false／ready 均拒绝，B busy 始终 true；票据隔离已得到独立正反例证据。AI 第一次 await 前互斥及最新 retry 接管也已落盘。实现者专项为观察 36、宿主相关 93、U3 2 及窗口 9，仍不替代最终独立全量。

但 `aiIntent` 的 finally 包在 `await pollTask()` 外，且 externalBusy 包含 aiIntent：POST 已确认后的整个 AI 运行期仍被算作页面写 busy，R12 原关闭选择问题换了标志名后仍存在。准备意图只覆盖保护性保存／提交，持久化确认后应释放准备屏障再只读轮询，不能让旧轮询的 finally 清掉另一份新意图；新增 claimed／dispatching 仍在运行而 page write busy=false、正常 close 任务选择可达的回归。

同一次独立内存诊断又验证：无效 page_ticket 的 page_ready 返回 accepted=false，但 `ready_receipt.confirm` 已先被调用一次（使用 spy，无真实安装或就绪文件写入）。票据／legacy 资格须在任何更新就绪副作用之前校验；有等待则再核当前票据后提交宿主状态。已接受票据页面后，下一次 bootstrap 待绑定期间也不能因 `_page_ticket_bound=false` 又放行无票据旧 ready。证据 `codex-independent/r05-busy-page-diagnostic.json`；该证据只证明回调调用顺序，不宣称发生真实安装。其余已修保持，仅接续这两处 R12 验证。

### 4.5 第六轮实际停写与最终独立执行

r06 自然完成 exit 0，明确停写，未 Git。准备意图的 finally 已在只读轮询之前结束；宿主先校验票据／永久 legacy 资格，再进行就绪确认，整个状态转换在线程锁下完成。Codex 再用合法 A／B 票据及 ready spy 独立执行：旧 false／ready 拒绝且 B busy 保持 true；无效票据 confirm 次数 0；合法首次次数 1、重复仍为 1；新 bootstrap 待绑定期间无票据 ready 拒绝且次数不增。证据 `f01-host-page-diagnostic.json`，无真实就绪文件／安装副作用。

最终来源扩展覆盖 backend、desktop、frontend、六份模块 Contract 与宿主握手规格，共 **407 路径**；`f01-source-expanded-before.json` 同时记录文件 SHA256 与按 Git 规则计算的 blob OID，`f01-expanded-freeze.json` 记录时点及基线 HEAD。此前 280 路径初始 scope 另存，不冒称全量覆盖。独立 TEMP 为 `k9f-426d1ff3`，日志及环境参数见 `codex-independent/f01-*`。最终独立全前端、全 local、桌面与 HTTP／窗口检查正在执行；未完成前仍不提交推送。

### 4.6 收取全 local 与实际采用确认（2026-10-28）

用户说明前次 Esc 为误按，明确授权继续收取结果、手动确认、修复及通过后由 OpenCode Git。全 local 已自然完成 **728 passed／724.30 秒／exit 0**；独立桌面 **285 passed／52.74 秒／exit 0**；全前端自然退出（核心逻辑、组件 60、W5 94、历史 22、更新 13、观察 37）、typecheck、独立构建、本机 HTTP 37 及 WebView2 9 项均 exit 0。恢复前 407 路径 SHA256 全部一致；不因隔夜误停而重复已通过且来源不变的套件。

Codex 使用独立 HTTP 合成库、合成凭据与已持久化假 worker 候选，启动前只读确认 live task=0。真实窗口将环境改为“积木区手动复核”，保存后预览来源变化候选；实际点击 UIA 复选框后预览未消失，点击“采用并保存”提示已采用四目标并保存 v14，返回列表显示 v14 及新环境，随后正常关闭 exit 0。没有生成／重写 AI 调用。只读数据库核对见 `f01-interactive-result-utf8.json`，启动／退出及源码构建身份另存。初次诊断 stdout 编码未固定，已以 ASCII JSON／明确 UTF-8 重新只读取证；未因日志显示差异改动业务数据。

实际窗口仍发现原 R04／R15 的显示遗漏：比较区评价分析 before／after 仍以 JSON 输出 health／language／social／science／arts；候选缺项将五个领域路径降级为五次“来源资料”，并用“候选仅可查看或复核”暗示缺项限制，实际缺项并不禁止正常采用。主采用／持久化逻辑已通过，本次仅交回显示 formatter／字段标签及提示文案，须保留五领域标签、空值与原文；不改服务、写状态机或门槛。回修后重跑受影响前端与实际窗口，未变化的后端／桌面以指纹及已通过结果保留，不重复全量。

### 4.7 R07 显示回修与最终实际采用（2026-10-28）

r07 自然完成 exit 0 后停写。与 f01 的 407 路径逐项比较，仅 `frontend/src/d1/views/ObservationEditorView.vue` 及 `frontend/src/d1/d1.observation.test.mjs` 变化：评价分析比较按健康、语言、社会、科学、艺术显示，空项标“（空）”并保持多行原文；候选缺项映射具体领域，提示改为“生成时未填写的内容（供核对）”。未改 payload、hash、token、targets、采用协议、后台或宿主。差异证据 `f02-source-delta.json`，最终窗口退出后的 `f02-source-after-comparison.json` 为 **407 路径全部一致**。

Codex 对最终前端独立执行全 d1（观察增为 **38 项**）、typecheck、构建，再用新合成库执行真实 HTTP **37/37** 和实际 WebView2 **9/9**，全部自然 exit 0。后台／桌面来源与 f01 完全一致，因此保留已通过的全 local 728／桌面 285，不重复无变更套件。最终前端产物位于独立证据 `f02-frontend`，验证参数及日志见 `f02-*`。

Codex 另启动此最终构建的真实窗口（合成数据 `k9f-426d1ff3/http2`、独立凭据，启动前 live task=0），将环境改为“积木区显示复核”。预览已有假 worker 候选时，实际看到中性缺项提示、五个具体领域标签，以及比较区当前／候选的五领域中文值与空项；来源变化明确列出观察环境／观察目标。实际点击 UIA 复选框后预览保留，再点“采用并保存”，提示四目标采用并保存 v14；返回列表为新环境及 v14，正常关窗实际 exit 0。只读 SQLite 确认 draft revision 14、最近历史 version 8／source adopt、两者 hash 相同，假任务仍仅一份 succeeded。见 `f02-interactive-result-utf8.json`、进程／启动／退出记录；不生成或重写 AI，不触碰原库。

最终实施会话脱敏审计 `f02-session-audit.json`：开工前 5142 条到 r07 完成 5779 条，新增 637 条；611 条带模型元信息的消息均为 `opencode-go/deepseek-v4.1-flash`／max，代理均 build，工具仅 shell／edit／write。消息数不等于供应商请求次数。r01／r03 实际中断 exit 1 保留；r02／r04／r05／r06／r07 均自然 exit 0，不将 r04／r05 误记为中断。

## 5. 保留边界

本片仅覆盖 E09 与 E10 创建／编辑／查阅部分及支撑页面的 E12 本机 API；批选、跨页选集、列表手调排序、E11／E12 Word／另存为、E14 整包仍后置。完整 A01–A22、教师产品体验、复杂真实照片效果及 MiMo 真实调用未整体通过。

Windows 10、WPS、干净机器、其他 DPI／显示器、跨设备、真实冻结更新／安装、发行源／4551、签名／WebDAV／发行及 D2／D3 原未验保持。原业务库、配置／凭据、OneDrive 原件、旧包和远程资源保留；本片不调用应用真实 AI，不安装依赖、Skill 或 MCP，不改系统架构。

## 6. 最终独立结论：本片限定工程核查通过

本片 **R01–R15 全部关闭**。审核以最终落盘源码、独立执行及真实窗口手动采用为依据，不以实现者自测替代。原失败／中断及回修历程保留在 §4，不代表当前仍有对应阻断。

| 独立执行 | 最终结果 | 证据（均在 codex-independent） |
| --- | --- | --- |
| 全 backend local | **728 passed，724.30 秒，exit 0** | `f01-backend.log`／`.exit` |
| 全桌面回归，含关闭、更新合成 fixture | **285 passed，52.74 秒，exit 0** | `f01-desktop.log`／`.exit` |
| 最终全前端 | 核心逻辑、组件 60、W5 94、历史 22、更新 13、观察 **38**，自然 exit 0 | `f02-frontend.log`／`.exit` |
| 最终类型检查与独立前端构建 | **均 exit 0** | `f02-typecheck`、`f02-build` |
| 最终真实受保护 HTTP | **37/37，exit 0** | `f02-http/report.json`／`.exit` |
| 最终源码实际 WebView2 基本闭环 | **9/9，exit 0** | `f02-window/report.json`／`.exit` |
| 实际中文预览、勾选与采用保存、列表、正常关闭 | **四目标 v14、历史 adopt／hash 一致、exit 0** | `f02-interactive-result-utf8.json`、`f02-interactive.exit` |
| 页票据与就绪副作用独立反例 | 旧页拒绝、B busy 保留、无效 confirm=0、合法／重复=1 | `f01-host-page-diagnostic.json` |
| 来源一致性 | f01→f02 仅两前端文件变化；最终 **407 路径无变化** | `f02-source-delta.json`、`f02-source-after-comparison.json` |

允许交由原会话、同一指定模型／build 将本片相关源码、测试及已归并文档正常提交并推送当前分支；不 amend、强推或夹带临时证据／凭据／数据。OpenCode 只补正自身结果的最终状态与实际中断轮次，不再改已验源码／测试。Git 后独立核对工作区、提交树与来源 OID、远端分支一致，随后停在本片。

本结论仅为 **E09 与 E10 创建／编辑／查阅部分及其 E12 支撑 API** 在当前 Windows 11 源码环境的工程通过。批选／跨页选集／手调排序、Word／原生另存为、整包及完整 A01–A22／教师产品体验仍按 §5 后置或未验；本片应用真实 AI 调用 **0 次**。
