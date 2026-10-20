# W6 H06-R02：重复打开实际白屏核查

最新处理决定（2026-10-20）：用户明确“白屏问题下次出现以后再修复”。据此保留已确认故障及未修复状态，当前停止主动复现／排查／修复，不作为本轮继续人工验收的前置追测；以后实际再出现时先保留同一进程、截图／状态和数据，再交原OpenCode Go Flash定位修复。下面各节保留当时证据，不把后续正常显示或本决定写成问题已修复；真实AI／发布禁止保持。

状态：2026-10-19，用户已确认“窗口白屏”，定位／修复未完成。合并验收暂停于第二份尚未创建，既有v11及单日2页人工结论保留，不宣称W6或产品整体通过。

## 1. 已确认事实与保护边界

- 209dedcd…人工包在同一212522/data／localappdata上，原PID33876正常退出；首次冷启动PID37308实际读回v11，用户明确四行完整、新Word2页逐页正常、标红正确。前后DOCX逐字节一致，SHA-256 c7be6797…。
- PID37308后已正常exit0，worker／服务／锁三项收口true；pywebview临时WebView缓存删除WinError32警告单独留证，不据此直接定根因。
- 22:38:39按同一包、同一CLI和同一数据／凭据根再次启动，PID18540、native窗口13045856，exec session83309；新日志前缀merge-prep-v11-20261019-223839。实际窗口内容持续全白，最大化后仍白；可访问性树却包含工作台、原教师／班级、10月19日v11计划。用户明确真实白屏，故不是只凭截图推断。
- 未自动编辑／保存／生成／导出；当前根任务4、human供应商历史请求3，原受控端口62258无监听。本轮应用真实AI、发布、升级安装、WebDAV及远程更改仍禁止。
- 保留白屏现场进程／窗口、原根、凭据、全部旧包和失败日志，不强杀、清理原profile／缓存或重置数据库；复现与回归只用新合成根／只读一致性backup副本。

独立证据根：`%TEMP%/kgm-d2-w6-h06-r02-codex-20261019-224910`，`source-before.json`为453可见项目文件hash、另有Git状态、截图／树、启动CLI及上次退出报告、preflight用户确认。原始证据仍保留在212522根。当前只有数据与界面树正常的证据，没有可见绘制正常的证据；验收必须增加实际像素／用户画面，不能继续仅凭DOM／HTTP／exit0通过。

## 2. 开工与约束

原OpenCode会话`ses_ead8af71dffeJphI1NOWg4jZgI`，模型只用`opencode-go/deepseek-v4.1-flash`。OpenCode唯一写实现／测试／构建验证脚本，Codex写本核查／任务文档与执行独立检查，不另起实现者或子代理。已读codebase-memory技能，list_projects及check_index_coverage再次Transport closed，按技能直接阅读d1_main.run_interactive、d2_manual_ai_main.main及d1_paths相关源码；不声明图谱完整，不安装新MCP／Skill。

正常入口和人工入口均直接create_window后webview.start(gui=edgechromium)，具体白屏触发点尚待定位。冻结启动、服务／worker／运行锁及关闭协调必须保留。先取证并复现，再最小定点修复；不预设GPU／临时profile为根因，不用清数据、放宽安全守卫或无证据的反复reload掩盖故障。

当前任务提示见`docs/tasks/current.md`。实现者结果、实际模型审计、Codex独立稳定复验与人工复验将按实际取得后补，不预先写通过。

## 3. 原现场恢复绘制的新证据

首次诊断期间，get_window_state报告同一原窗口已最小化，来源未确认。Codex随后仅activate_window、重新get_window并截取状态，同一PID18540／window13045856实际截图已出现完整工作台、已保存v11。没有reload、关闭重开、改数据或AI调用；该事实说明最小化后恢复前台可能使绘制恢复，不能据此宣布根因已确定或问题关闭。已补入当前任务，要求实现者按新事实继续诊断，避免按“永久白屏”假设盲修。

原会话已经独立standalone CLI重新接续；成功导出新增assistant元数据均为opencode-go／deepseek-v4.1-flash／default。当前实施仍在只读定位阶段，详细模型审计待最终导出汇总。

恢复后的只读SQL独立检查`original-window-restored-readback.json`共7项通过：仍仅原计划、v11、原content ID、完整adopted_content、原文、split_baseline及created_at均与人工手改保存后记录一致；未增加第二份计划。旧正常包、初始人工包、R01人工包及R01仓外副本各182文件，manifest与此前证据完全一致，见`old-packages-before.json`。首次分析命令误给只读helper相对路径而停止，修正为绝对路径后通过，未写数据库；原工具错误保留，不记作产品失败。

原PID18540启动时间未变且Responding=true。22:30以后Application日志ID1000／1001／1002中，按KGNext、msedgewebview2、dwm.exe、python筛选无匹配事件；该限定查询不能替代图形系统诊断，也不证明从未发生渲染错误。恢复画面与界面树已保留为`original-window-restored.jpg`／`original-window-restored-ui.txt`，待用户确认当前实际显示。

## 4. 过程退回及三次独立原生对照

实现者一度新增外部ctypes／PrintWindow截图与窗口控制探针，Codex在执行前退回：本轮Windows原生操作／截图应走已加载computer-use的Sky；此外“非白像素”指标还会把全黑错误画面算作通过。实现者已移除本轮自建探针及其集成，未运行该探针，未用它形成通过结论。撤回后控制器只发生全文件LF→CRLF，Codex独立归一化精确恢复开工hash，已再交回实现者恢复原字节，不能冒充仍有必要代码变更。

Codex用既有prepare_session作只读SQLite backup，在独立证据根建立`native-repeat-data/`，仅该副本以既有prepare_ai_config准备独立合成凭据（config v4）；不启动供应商、不调用AI。新仓外完整182文件副本manifest44e58c4e…、EXE209dedcd…与R01完全一致。三次均从相同CLI、相同data／localappdata启动，正常关闭，未编辑／保存／生成／采用任何内容：

| 次数 | PID／窗口 | 独立观察 | 退出 |
| --- | --- | --- | --- |
| 1 | 27264／35259410 | 前置后完整工作台显示v11；打开原计划后编辑页正常，UIA含完整四行过程与已同步 | exit0；worker／服务／锁三项true，工具读取原entry-exit留证 |
| 2 | 21924／7212798 | 最大化后完整工作台和v11正常；最小化再恢复仍正常，保留max／restored截图与树 | exit0；三项true，独立复制entry-exit |
| 3 | 34832／33162096 | 启动后前置显示完整工作台和v11，保留截图与树 | exit0；三项true，独立复制entry-exit |

两次未前置的截图出现裁切／遮挡，不能据它们确认首帧完整绘制；上述有效正常观察均在前置或最大化后，也没有再次复现“前置／最大化后持续白”。三次正常退出后的只读逻辑检查`native-repeat-business-readback.json`5项通过：原库和副本均v11、四个业务表完全相同（计划1／内容11／任务4／候选4）、三次exit0；副本有意不同的合成配置／凭据不混入相等声明。

三次副本窗口均已正常关闭，Codex回到原PID18540／窗口13045856并前置，实际截图仍为完整工作台和v11。原数据和候选均保持；此前用户确认实际白屏的事实不撤销，仍等当前显示反馈，不把有限未复现改写成“已修复”。

## 5. 当前结论及后续

本轮取得恢复及三次限定原生对照证据，**未定根因、未实施产品修复、白屏H06-R02仍开放**。不因临时profile删除警告改持久化profile，不用无证据的GPU开关、循环reload或重建同样代码的新包。实现者诊断候选与待配合协议见[诊断结果](desktop-d2-w6-h06-r02-result.md)，其中自测与本节Codex独立证据分开。

待用户确认唯一原人工窗口的当前实际显示；若再次白屏，先保留同一进程／截图／状态，再交回原OpenCode Go Flash作有证据支持的最小修复。现有v11与H07单日2页人工结论保持；合并第二份、旧年级、在途及跨120秒真实睡眠仍未验，应用真实AI及发布仍禁止。模型最终审计及撤回后的源码字节核对在交付后补，不先写通过。

## 6. 诊断交付核对

实现者已明确停止写入。Codex独立确认控制器恢复原LF、37931字节及开工SHA-256 f60d6453…，453份开工文件中无desktop／backend／frontend代码变化；本轮最终只有规划／核查／结果文档更新，无产品修复、无新构建。原四份完整182文件包再次逐文件manifest核对均不变，见`source-diff-review.json`与`old-packages-after.json`。

`model-audit.json`对照开工与最终会话导出，新增37条assistant元数据全部为`opencode-go/deepseek-v4.1-flash#default`，原会话ses_ead8af71dffeJphI1NOWg4jZgI不变，最终idle/succeeded；原生路径退回轮、诊断交付轮及最终导出均exit0。前两次由Codex主动中断以补恢复事实／纠正探针路径，证据保留，不写成模型故障或验证通过。

实施者28项控制器单元自测及同源命令证据列于其结果§5，只作为实施者自测，不冒充独立或人工通过。由于最终代码精确未变，Codex没有再重复无关全套测试；本轮独立证据为只读数据、包hash和上述真实窗口对照。H06-R02问题结论仍为开放，下一步仅待当前实际显示确认／新的复现事实再定修复，不将诊断交付完成写成问题关闭。

## 7. 2026-10-20未打开反馈后的同根重开

用户反馈“未打开”，进程及Sky窗口枚举均为空；旧observer83309已失效，旧entry-exit无法独立关联最后一次退出，因此不写成该次正常退出已验证。原人工根只读preflight五项通过、182文件manifest44e58c4e…及EXE209dedcd…保持。Codex直接复用既有已验CLI、原data／localappdata及保护根，无供应商监听、无AI操作，以新PID36968／window9376960重开并前置；实际像素及UIA均显示完整工作台、原档案和v11。新observer3816、日志前缀resume-display-20261020-062606，旧启动／退出记录及活动指针副本保留。本次未修改实现、未调用OpenCode或真实AI；仅恢复人工入口，不以再次正常显示关闭H06-R02。用户当前实际显示及后续合并人工步骤仍待反馈。
