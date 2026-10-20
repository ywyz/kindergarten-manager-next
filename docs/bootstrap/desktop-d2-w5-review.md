# D2 W5 Codex独立核查

更新：2026-10-19。用户授权继续W5，由OpenCode使用Go套餐DeepSeek V4.1 Flash实现，Codex核查并继续交回修复；不调用应用真实AI或发布。本文独立于实施者结果记录，不代表D2产品或发行通过。

## 1. 开工范围与证据

- 当前分支`codex/desktop-v2-foundation`，保留全部既有未提交/未跟踪内容。W1–W4已有工程结论保持，W6未授权、未启动。
- 唯一执行入口为[当前任务](../tasks/current.md)，规格依据[工程规格§4.3/§5–§7](../specs/desktop-ai-engineering.md)及[产品规格](../specs/desktop-ai-daily-plan.md)。OpenCode唯一写实现、测试和构建脚本；Codex只写规划/核查文档与执行独立验证，不另起实现者或子代理。
- Codex证据根：`%TEMP%/kgm-d2-w5-codex-20261019-062748`。`baseline.json`记录开工424个非忽略文件的SHA256，供最终范围比对。
- OpenCode专用会话`ses_eaedea340ffenVKeSGOhD8Qoq8`，CLI显式`--model opencode-go/deepseek-v4.1-flash --agent build`；`opencode-run1.jsonl`与stderr、实际退出码保留。最终还需核实会话实际模型与完整自测证据。
- 前缀会话脱敏导出`opencode-session-prefix.json`已独立核对实际模型元数据：`providerID=opencode-go`、`id=deepseek-v4.1-flash`，与用户指定一致；最终仍需保存结束会话证据。
- 图谱查得D1统一离开协调、App/Editor及宿主CloseCoordinator入口；覆盖检查为2026-10-18图谱，相关文件`metadata_changed`，因此已按具体路径读取当前源码，不把图谱当完整当前源码证明。

## 2. 核查重点与当前状态

最终已通过限定源码集成工程核查，结论和未验边界见§8；§3–§7保留当时失败与修复证据，不代表当前仍有同项编码缺陷。核查覆盖：三类独立触发与先保存、密钥与指导/游戏设置、任务查询及风险确认、候选字段编辑与来源复核、丢回包回执、采用迟到和新输入、设置/候选草稿离开保护，以及关闭冻结/任务收口/旧ack/原生保存busy。

组件、真实本机HTTP、宿主/子进程与真实Windows窗口证据分开记录；模拟时钟不替代真实睡眠，源码窗口不替代最终D2包。只有最终稳定源码的实际测试退出码可用于最终结论。测试隔离`LOCALAPPDATA`和凭据根，设置`APP_DISABLE_DOTENV=1`，不触及原教师体验库和真实凭据。

## 3. 实施中前缀核对（待最终源码复核）

`codex-prefix-source-display.json`为独立加载当前`ai.ts`的执行证据：

- R01（待交回）：适龄来源读取`source_excerpt.process_source`，但现有后端`ai_inputs.source_excerpt`实际返回`process`，因此真实冻结来源过程未显示（探针返回null）。须按真实API字段显示，而不是只用前端自造fixture。
- R02（待交回）：其他活动来源只以`'game_config' in excerpt`判断已结合配置；后端即使无修订/全空配置仍返回该键，探针把空配置显示为“已结合当前班级游戏配置修订”。须根据真实冻结配置内容判断并按产品规格说明“一般建议”，保留可核对的来源事实。
- R03（待交回）：`codex-prefix-task-races.json`独立执行真实`AiTaskPanel.vue`setup，挂起正文save后将`props.frozen=true`再放行save，仍POST登记任务（1次，预期0）。每个await后须复核原plan、输入身份及关闭冻结；新输入/新日期不能被旧操作当成当前来源，关闭冻结后不得继续登记任务。
- R04（待交回）：同一组件，首个任务POST模拟服务器已收而响应丢失，教师再次点击会直接换`uuid-2`再次POST，回执查询0次；不符合D2回执和未知结果规则。须在任务提交/恢复/重试/取消等写入中保留原request_id与请求体，丢回包先只读查回执，未知仍保留待核对状态，不改key再做。相关动作还需同一操作并发互斥、服务端allowed_actions及frozen复核。
- R05（首轮自测已修复，待最终复核）：`codex-prefix-candidate-races.json`实际CandidatePreview setup最初拆分load后`selected=[]`；resetForms仅其他活动分支初始化selected。OpenCode随后自测发现并把selected初始化移到公共分支，独立真实窗口前缀已确认拆分`[group_activity]`及preview/adopt可达；适龄和最终三类闭环仍待最终复核。早期失败证据保留。
- R06（待交回）：同一探针挂起preview POST，修改候选过程为“教师后来输入”并等Vue watcher，再返回旧编辑token；组件仍恢复旧preview，可把与当前编辑不同的旧内容采用。需要绑定plan/candidate/selection/edit signature/content version/关闭身份，旧响应不得恢复预览；load/切候选迟到亦须保护。
- R07（待交回）：同一探针在adopt原始epoch=0时丢回包，挂起GET receipt，再令正文epoch=9后返回成功回执，组件emit adopted携带9而非0。父组件会误判仍为本次输入，可能覆盖新正文。pending须保存完整原请求/原plan/candidate/expected/epoch，首次查询、重查和同键重传都沿原身份；不得在恢复时重新captureEpoch。
  - 候选busy/unknown同样须阻止离开/关闭及取消丢弃。首轮后期dirty改为仅比较编辑文本后，未编辑候选也可在adopt POST仍在途或结果未知时关闭/卸载，丢失待核对操作。允许只查看且未修改的预览关闭，但不能把仍在写入或unknown当成干净；“查询”应先只读GET，不是按钮名叫查询而直接POST。
- R08（待交回）：`codex-prefix-settings-races.json`实际AiSettingsPanel setup证实三项丢稿：保存拆分指导会把尚未保存的适龄指导恢复成旧值；AI配置save期间输入新model，成功响应会覆盖新输入；PROMPT_VERSION_CONFLICT会自动loadPrompts清空冲突前草稿。保存只归并实际提交且仍匹配的字段，其他任务/后来输入保持；冲突重读比较但不reset。GameConfigPanel成功/冲突后直接load也有同类风险，须统一覆盖验证。所有指导accept/reject/adapt、清除等丢回包也须沿R04回执规则。
- R09（待交回）：SettingsView的D1字段沿frozen禁用，但新增AiSettingsPanel/GameConfigPanel未传入或定义frozen，两子组件所有输入/变更方法均无关闭保护。最终关闭锁定后仍能编辑/保存或新增草稿；须真正接通输入及方法guard、busy/unknown阻离开与取消后恢复，不能只在父页面保留旧布尔。
- R10（待交回）：`codex-prefix-editor-races.json`证实采用前已有正文草稿时，EditorView.openCandidate直接开窗、CandidatePreview直接preview/adopt，没有调用统一save；随后onCandidateAdopted以相同epoch读取服务端并applyPlan，未保存原文被旧原文替换（patchCount=0）。必须在预览/采用前完成D1正文保存、复核plan/epoch/dirty/关闭身份；失败不提交采用。不能只把“采用开始后又输入”当作唯一草稿风险。
  - 真实Windows窗口补证：`native-prefix/result.json`、`native-prefix.log`、实际exit1。独立构建到`native-prefix-frontend/`，真实WebView2窗口＋本机HTTP＋SQLite，候选由正常W3服务链及合成响应产生（无外部调用）。原文为“教师尚未保存的原文-必须保留”、dirty=true、v1；打开候选→真实preview→adopt后变成旧“原始教案正文”、dirty=false、v2，候选关闭，数据库仍为旧原文。两个检查均失败，确认R10可在当前真实页面流程到达，不只是组件状态模拟。所用前端源hash保存在`native-prefix/source-hashes.json`，合成库/凭据根与LOCALAPPDATA隔离，结束正常关窗，原体验库未触及。
- R11（待交回）：同探针将采用后GET挂起，期间把编辑器换到pOther，GET返回后又变回p1。onCandidateAdopted在await前捕获current，之后不检查实时plan；else还无条件applyServerBaselineKeepingInput(server)，可污染其他计划指针/基线。须在每个await后复核实时plan及组件代次；外计划响应完全不更新任何当前plan/form/baseline状态，同计划新输入也不得默默重置。
- R12（待交回）：`codex-prefix-close-races.json`证实hasLiveTasks只读首100项且忽略next_cursor，第二页有活跃任务仍返回false。任务API按created_at/id升序；AiTaskPanel同样只读首50项，且按task_type折叠为一条，无候选历史列表，后续任务/旧候选/多条paused或unknown无法正常处理。应有真实分页/按状态查询及可达的历史候选入口，不能因使用次数增加丢可见性；关闭是否有活跃任务不能依据截断列表或把读取失败当无任务。
- R13（待交回）：同close探针打开A任务选择后收到宿主timeout/abort，选择弹窗仍在；随后点击“停止等待并退出”还给已经取消的A发送allow=true。closeChoice未绑定id/generation且未在abort/replacement时取消，须按请求身份收口弹窗/promise，旧选择或查询回包不得向旧请求发allow、影响新请求或重新冻结。
- 验证补充：新增`d1.w5.test.mjs`中的TaskPanel测试启动轮询但未逐项unmount/清理timer（如首个任务测试保留pending，refresh空列表仍合并保留它），Node进程不会自然退出；初期`tail/grep`命令仅作诊断，不可据管道退出码写通过。最终须清理全部组件/计时器并自然退出，保存完整日志及Node真实退出码；不能加process.exit强制掩盖泄漏。
  - OpenCode首轮自测已补逐项unmount并自然退出31项/exit0；最终仍须按最终源码完整日志独立复跑。

附带规格核对：适龄预览当前把**适龄候选输出**标为“本次适龄调整所用过程”，应与真实输入过程分开标明（归R01）；required新字段应以所查看目标默认预填，而非`guidance[field] ?? ''`全部置空，旧文字及orphaned保持；AI入口应明确当前使用默认指导并可查看/编辑。班级游戏预览应可核对实际before/after，而不只显示“有实际修改”。这些按既有规格落实，不新增产品流程。

以上是实施中已写出的辅助函数前缀证据，尚未将未完成组件评为最终缺陷；待实施者完成后复核，仍存在则交回同一会话修复。

## 4. 独立回归（进行中）

`independent-desktop/test.log`及`result.json`：Codex独立桌面146项/4.07秒/实际exit0；APP_DISABLE_DOTENV=1、LOCALAPPDATA隔离，86个相关Python生产/本地测试文件执行前后hash一致。两项警告为既有Starlette/httpx及AnyIO弃用警告，没有安装/调整依赖。该回归不包含W5新增真实窗口或最终包，也不关闭§3问题。

`independent-local/test.log`及`result.json`：Codex独立全local **470项/275.494秒/实际exit0**（包装总耗时278.654秒），同样隔离环境，86个相关Python文件执行前后hash一致；没有ResourceWarning。最终仍须比对这些Python文件与交付源码，若有相关修改再定向或完整复验。前端处于写入中，尚未执行最终独立前端回归。

## 5. 首轮交付后核对与交回

OpenCode首轮CLI实际exit0后明确停止写入，交付36项W5组件自测、157项桌面自测及470项local自测；只代表实施者自测。交付时完整文件hash见`run1-delivery-hashes.json`。

Codex在停止写入后独立复跑六组反例，结果分别保存到`review-after-run1/`，未覆盖早期失败文件。R01/R02、R03/R04、R06/R07、R08、R10/R11、R12/R13仍与§3相同；R05的拆分目标初始化已修好。R09根据当前父子组件绑定和方法源码仍未接通冻结。真实窗口R10已另有失败证据。本轮**不通过**，继续交回同一OpenCode会话修复。

实施者测试日志路径须按实际目录核对（CLI命令实际写到`%TEMP%/opencode/kgm-d2-w5-opencode`及`%TEMP%/opencode/kgm-d2-w5-local-1792363816`，结果文档省略了中间`opencode/`）；早期未显式隔离的桌面测试或只留管道尾部的命令不得冒充最终完整隔离证据。最终result须记录真实路径、完整日志和实际进程退出码。

## 6. 修复轮前缀核对（进行中）

同会话继续使用指定模型修复。`repair-prefix/`为实施中的定向结果，不能代替最终稳定源码复核：

`repair-prefix3/`补证（仍在修复中）：任务历史初读只取最早300项，第400项真实状态`dispatching`不可见；点继续加载后liveCount=1，但下一次refresh又回300项/liveCount=0，导致后续活跃任务和成功回包不能持续轮询显示。须保持已加载历史，并保证新近活跃任务不会被早期历史挡住。游戏配置apply后后来输入虽保留，`confirmed=snapshot()`却把这段未提交输入也当服务器基线，draftActive=false；须以实际服务器change作confirmed、后来输入仍脏。另有确定409 VERSION_CONFLICT后pendingAdopt不清、取消永久被挡，以及clear-secret成功清空后来新输入；详见`codex-repair-history-game.json`及`codex-repair-final-guards.json`。这四项须加入最终回归。

同目录`codex-repair-game-recovery.json`再现修复轮的恢复入口问题：resubmitApply复用包含pending禁用条件的guard，始终无法同键重传（实测POST1次，预期显式重试后2次）；queryApply确认成功后组件dirty=false，但最后父级draft-active事件仍true，阻止正常离开。已通过同会话steer继续交回，需分离输入与恢复方法guard，并统一busy/pending/draft事件时序。原失败JSON均保留。

- R01/R02来源字段及空配置提示已定向修正；R03关闭冻结后POST从1变0，其他身份/新输入情况仍待复核。
- R04仍可复现：`codex-prefix-task-races.json`在响应丢失后再次trigger仍发`uuid-2`，查询0次。新TaskPanel虽显示“查询提交结果”，原发起按钮和trigger方法仍未因pendingCreates阻止重做；pendingActions也须在方法层阻止重入。未决登记/操作若允许离开卸载，不能丢失原request_id（应阻离开或在相应存活作用域保留，不能以停止轮询代替）。
- R04还涉及共享client的真实解析分支：`codex-repair-truncated-response.json`没有替换API模块，实际client.ts面对已收到202但body/JSON读取失败时用catch(()=>null)吞掉错误；当前TaskPanel将null放进tasks后报普通TypeError，pending为空，下一次trigger又在blockedReason读null时抛错。首跑脚本实际exit1，随后增加异常捕获保存结构证据；这与另一组网络status0后new key的反例分开。HTTP成功状态不等于拿到可信提交结果；这类响应体失败必须走未决/回执恢复，不能污染任务列表。5xx也不能仅凭HTTP状态断定从未提交，须按实际错误码/回执保守核对。修改共享client后须保持D1保存/导出相关回归。
- R06/R10新增反例`codex-repair-unreviewed-token.json`：教师查看token-1/v1比较后点击采用，saveBody使正文v2，adopt内部再次preview拿token-2/v2后立即POST adopt到v3。第二次比较的before已经是“教师新修改的过程”，但没有等待教师查看/再次确认。不得用自动刷新token绕过“目标变化须重新比较确认”；应在展示前先保存正文，或保存使事实变化时只重新展示比较并等待再次明确采用。采用应使用**实际查看的凭证**，不能自动刷新后直接保存；fresh preview等待期间也须绑定原候选编辑/选择/正文epoch，而非在响应后重新捕获代次。
- R12当前TaskPanel用`MAX_REFRESH_PAGES=20`且无继续加载状态，会在2000项静默截断，仍不能保证后续/历史可达。可以有分批加载保护，但必须提供明确的继续加载，不能以技术方便增加历史数量产品上限。
- R11同计划的晚回包仍有问题，`codex-repair-late-baseline.json`：采用期间新写反思导致epoch不匹配，父组件却推进baseline到v2且保持phase=ready；随后普通save带expected=2把已采用过程“候选采用过程”写回成旧“人工原过程”。工程§5.4明确只有planId/editEpoch匹配才更新正文基线；不匹配应保留原输入和基线并进入待核对/既有版本冲突处理，不能先推进版本绕过冲突。否则还会因旧组/游戏ID与新采用版本不符而使正常保存422。
- R04/R08/R09设置未决反例`codex-repair-settings-pending.json`：配置首次PATCH响应丢失，改model后再次保存会用同key的新body再次PATCH；保存secret期间后来输入的合成secret被成功回包无条件清空；清除密钥在busy及unknown时draftActive均false，再点清除生成新key。所有写入必须保留完整原上下文并让busy/unknown阻离开；未知时只读查询，不能重建请求体或另造key；成功仅清空本次已提交且未再修改的secret输入。只补frozen布尔或只缓存request_id不等于完成这些要求。
- R08首次读取也有丢稿，`codex-repair-settings-initial-load.json`：AI设置输入在首次GET未完成时可编辑（只按frozen禁用），此时新model/secret不算draft，GET回来又被旧model覆盖且清空secret。初读未完成时须禁用并守护相关未加载字段，或按输入代次保留用户文字并计入草稿；GameConfig初读同样应核对，不能让迟到的初读重置刚新增的地点。
- R08同一指导中的未选字段仍丢稿，`codex-repair-guidance-selection.json`：过程指导有未保存草稿时，仅接受theme默认会把process草稿重置为旧值；拒绝默认也会重置它。mergeSavedPrompt不能把完整beforeMap等同于实际提交字段：普通保存/adapt可归并实际提交的完整字段，accept只归并明确选中字段，reject只更新拒绝状态并保留全部输入。其他字段和后续输入保持，confirmed基线独立更新。
- R12合法未建档状态不能误报任务：`codex-repair-no-profile-close.json`在bootState=uninitialized、任务API返回LOCAL_PROFILE_REQUIRED时仍显示“有AI任务正在进行”选择。该状态本来不可能有任务，后端宿主快照已明确定义no_profile=0；须沿用首次建档前正常关闭流程。真实存储/通信失败仍不能当成无任务。

最终还需核对既有规格中的普通failed重试“新请求可能计费”提示、缺失活动板块明确显示“未生成”、required新字段按所查看默认预填，以及真实窗口/子进程证据；不是新增需求。

回执语义澄清：以上“只读查询”是指先查回执及标为“查询”的动作，**不否定**工程§5.1已允许的显式“重试原提交”（同key、完整同body，沿原上下文，先读已提交回执）。若404持续未知，可提供该既有协议的明确恢复动作；它不能重建为当前新草稿、不能自动改key，也不能把新任务execution重试与传输层同键重传混为一谈。不得因只缓存id或没有恢复入口而把未提交操作永久卡住。

验证入口前缀核对：新增`d1_main._synthetic_transport_from_args`只看port，普通`selftest=false/phase=first/data=None`仍返回127.0.0.1解析注入（`codex-repair-verification-entry.json`，没有实际连接）。按工程§6“专用合成验证入口”边界，应仅允许专用w5-ui自检且显式独立合成根/凭据环境，普通运行不得接受测试解析/CA注入；校验应在runtime.prepare前。也可把受控provider注入全部留在独立验证驱动，不暴露给普通启动入口。新增源码窗口驱动尚在写入中，最终需复核是否已加限制。

实施者真实窗口首跑`%TEMP%/kgm-d2-w5-window-c007b176/verify-report.json`实际exit3，provider_requests为空，AI配置和多个后续步骤失败。驱动的配置request_id用了非UUID `w5ui-config-0001`，现有合法API必须拒绝；这是夹具问题，不能为通过修改后端校验。启动日志还有关闭步骤失败，但主线程先写summary导致报告中缺少这几项：最终须等待窗口驱动收口再写结果，并要求预期检查集合全部存在且为true，不能只用当前字典的all判断子集。停止退出须用宿主/进程/落库状态确认，不能依赖销毁后的页面JS还能回复；若声称已发送分支，应证明受控TLS服务实际收到该请求并核对最终unknown/paused分类及worker退出。该首跑只属于OpenCode自测，Codex独立真实窗口证据仍是§3的R10失败。

## 7. 收口前独立复核记录（历史进行中状态）

截至当前，`independent-final-probes/assertions.json`的**42项独立断言全部通过**（实际进程exit0）。使用真实Vue SFC setup与受控API层，重放来源字段、空游戏配置、关闭期间发起、丢回包/截断202、同键完整请求体恢复、冻结下阻重传、陈旧预览、原采用epoch、外计划晚回包、同计划新输入保持旧基线并进入冲突、设置字段合并、密钥后来输入、默认接受/拒绝掩码、无档案关闭、分页与历史、游戏草稿基线及恢复事件。不是DOM/真实窗口证明。旧初读探针直接修改禁用字段的内部ref不再视为可达输入；最终用实际setConfigDraft入口与模板disabled检查证明初读期间输入被禁用。旧Editor回调探针仅保留外计划迟到检查；原先未保存正文丢失由下述真实流程复核，不以绕过新预览前置条件直接调用回调冒充可达缺陷。

- `native-final/result.json`、完整log、实际exit0及页面截图/可访问树：真实WebView2＋本机HTTP＋SQLite，原未保存原文/反思在打开候选时先保存到v2；旧来源候选为只读、预览及采用禁用，数据库保留新原文且split_baseline仍null，5项通过。原失败`native-prefix/`保留。截图尚有内部英文type/grade，已交回改为中文，最终源码/构建仍待对齐；这次不冒充最终中文页面截图。
- `independent-frontend-pass1/`：`npm run test:d1`实际exit0，原纯逻辑＋60项D1组件＋69项W5组件通过；`independent-typecheck-pass1/`类型检查exit0。期间只改了桌面窗口驱动，前端源及测试前后hash一致。随后中文/缺板块展示修改须另行复跑受影响的前端检查。
- `independent-build-pass1/`：`npm run build:d1`实际exit0、184个源码/测试文件前后hash一致；仅现有chunk体积提示。不是最终安装包，不启动W6。
- `independent-local-final/`：全local **470项/293.201秒/实际exit0**，包装296.03秒，未见ResourceWarning。执行前后后端生产/本地测试（含新增TLS夹具能力）hash一致；变化仅桌面窗口验证入口/驱动和前端展示文件，不被该local套件导入。最终还需比对当前相关源码。
- `independent-desktop-pass1/`：桌面157项/5.39秒/实际exit0；期间d1_main.py因窗口驱动修正有变化，故不能作为稳定桌面最终结论，需复跑。

全部独立运行显式APP_DISABLE_DOTENV=1、独立LOCALAPPDATA/合成数据与凭据环境；无真实应用AI调用、无发布。OpenCode最终result、最终源码哈希、三类候选真实采用窗口与完整退出窗口仍待收口，当前尚不宣告W5工程通过。

## 8. 最终工程结论：W5限定源码集成通过

2026-10-19，OpenCode使用用户指定Go套餐DeepSeek V4.1 Flash完成W5；Codex独立核查后经同一会话交回修复。**当前Windows 11开发机、源码前端＋本机API＋独立合成库环境的W5界面与宿主集成工程通过；R01–R13及本轮恢复入口/展示缺项关闭。** 本结论不等于完整G12/G13、D2产品、真实供应商或发行通过。真实系统睡眠、最终包及教师确认仍按后续范围记录。

### 8.1 最终稳定源码的独立证据

证据根仍为`%TEMP%/kgm-d2-w5-codex-20261019-062748`。以下均保存完整日志与进程实际退出码：

| 验证 | 最终独立结果 | 证据 |
| --- | --- | --- |
| 类型检查 | exit0；184个相关源码/测试文件前后hash一致 | `independent-typecheck-final/` |
| 前端完整回归 | 原D1纯逻辑＋60项D1组件＋71项W5组件，exit0；184文件一致 | `independent-frontend-final/`，43.545秒 |
| 桌面完整回归 | 157项/6.61秒/exit0；184文件一致 | `independent-desktop-final/`；仅两项既有弃用警告 |
| 后端完整local | 470项/293.201秒/exit0 | `independent-local-final/`；66个后端生产/本地测试文件从运行前到最终源码一致；期间变化仅未被该套件导入的桌面窗口驱动及前端展示 |
| 最终前端构建 | `npm run build:d1 -- --outDir <证据根>/final-native-frontend`，exit0 | `final-native-build.log`及实际exit文件；沿既有依赖，无安装；仅chunk体积提示 |
| 独立反例重放 | 42项断言/exit0，最终中文及缺板块展示源码上再次通过 | `independent-final-probes2/assertions.json`；组件/受控API层，不冒充DOM |
| 三类候选真实采用 | 11项/exit0；前端源码hash前后一致；保存版本v2/v3/v4 | `native-roundtrip/result.json`及完整log；真实WebView2、本机HTTP、SQLite，候选由正常服务链输入合成成功响应，无外部调用 |
| 完整真实退出窗口 | 23项全部true、无缺项、child及父驱动exit0 | `independent-window-report.json`；原根`%TEMP%/kgm-d2-w5-window-25f4aa9c`完整保留 |
| 专用验证入口边界 | 5项/exit0：普通启动、错误phase、缺合成根拒绝，且prepare前无建库；专用模式允许 | `entry-final/result.json` |

真实三类采用证明：拆分保存教师预览修改的过程并建立原始基准；适龄仅改过程、保留其余字段/原文/原始基准；其他活动仅替换所选晨谈板块，未选板块与基准保持。候选由真实服务生成，采用走页面实际preview/adopt及父编辑器回包，不是直接调用后端adopt冒充前端闭环。

完整退出窗口使用真实AiExecutor＋Windows spawn/Job＋受控TLS。provider实际收到split=1/other=1/adapt=1；继续等待取消关闭、旧请求中止无旧allow、保存冲突拒绝退出、最终显式停止退出均通过。已发送适龄任务最终`outcome_unknown`，与provider收到请求交叉匹配；没有open attempt，worker确认退出，宿主closing、窗口及服务收口。没有依赖销毁后页面还能返回JS；所有预期检查齐备才算通过。失败窗口根和早期错误报告继续保留。

### 8.2 缺陷关闭映射

| 问题 | 最终修复与复核 |
| --- | --- |
| R01–R02 | 真实冻结来源process与候选输出分开；空游戏配置明确一般建议；中文标签及真实日历warning |
| R03 | save/nextTick后复核计划与关闭冻结，冻结后零新登记 |
| R04 | 完整不可变原操作；unknown阻重入/离开；GET查询与显式同key同body重传分开；截断202不污染列表；冻结下不重传 |
| R05 | 三类默认目标有效，真实窗口三类preview/adopt均到达并成功 |
| R06 | 陈旧编辑/版本/选择预览不能恢复；采用仅用实际查看token，变化后必须重新比较确认 |
| R07 | 回执沿原epoch恢复，busy/unknown阻关闭及丢弃；确定冲突解除未决、保留编辑 |
| R08 | 保存/接受/拒绝按实际字段掩码归并，其他及后来输入保持；初读禁用；secret仅清除未再变的已提交输入；游戏confirmed是真服务器状态 |
| R09 | 子设置接入frozen和统一草稿门控；busy/unknown阻离开；游戏恢复成功同步释放父级草稿 |
| R10 | 打开/预览前先保存正文；原真实失败场景已在`native-final/`复验，原文保留且旧候选只读；最终三类采用另有稳定源码真实窗口证据 |
| R11 | 外计划迟到不碰当前状态；同计划新输入不推进旧基线，转既有冲突保护，普通save不能默默覆盖已采用内容 |
| R12 | 全历史分页可达且轮询不缩回；关闭查询不把失败/截断当零任务；无档案正常关闭；缺板块显示未生成并禁选 |
| R13 | 选择绑定close id/generation，abort/replacement取消旧弹窗与承诺，旧选择不发送allow |

### 8.3 保留边界与接续

- 本轮仅W5源码集成；W6导出/完整打包、真实AI（G17）、WebDAV和发行未启动。没有commit/push或改远程资源。
- 真实系统睡眠恢复未验，未以测试时钟或进程暂停冒充；完整G13仍待补。最终D2包真实窗口、G14新增Word闭环与人工逐页检查、G16完整包、G18教师流程确认也未验。
- 干净机器、Win10、WPS、其他DPI/多显示器及发行再现性保持后续；不重开已确认微软拼音与D1/R18人工验收。
- 原体验库、原包与历史证据保留；自动检查仅独立合成根/凭据环境。当前无剩余W5编码任务；唯一接续入口为[当前任务](../tasks/current.md)。


### 8.4 最终范围、会话与文档核对

`final-audit.json`与`scope-final.json`：相对开工424文件快照，本轮19个既有文件变更、11个新增、零删除；只涉及W5前端/配套测试、桌面专用验证入口/驱动、TLS测试夹具及本轮状态/结果/核查文档。原有脏工作区保留；ARCHITECTURE、冻结迁移、依赖/锁、项目配置与旧包/体验证据均未被本轮改变。最终184个相关源码/测试与独立完整前端/桌面检查时逐项相同；实现结果列的21个SHA256前缀全部匹配。9份相关文档的197个本地链接目标存在，变更/新增文本无尾随空白，git diff --check实际exit0；继续当前分支，无commit/push。

实际模型以最终脱敏会话导出`opencode-session-final.json`复核：只有`providerID=opencode-go, id=deepseek-v4.1-flash`，不只依据CLI参数推断。最后assistant消息`finish=stop`且有completed时间，会话active为空，已明确停止源码写入。第二轮原CLI跟随进程因中途interrupt退出1；后续修复通过同一会话的本机session.prompt/steer继续，不能把该CLI退出码当整体成功。最终实现交付、会话完成与本节全部独立实际exit0证据分别核对，未另起实现者或更换模型。
