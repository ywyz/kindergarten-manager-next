# D4：批选／排序、Word 导出与宿主交付独立核查

> 公开版隐私处理（2026-10-30）：本机用户路径、私有部署地址或联系标识已替换为占位符；原始记录由维护者私下保留，历史日期、结论和产物哈希不因此改变。

更新：2026-10-28。状态：**本片限定工程核查通过，R01–R13关闭；按用户授权由原OpenCode正常提交推送后停在本片。** 最终范围见§6，不宣布完整A01–A22、教师体验或发行通过。

## 1. 授权与基线

用户要求按计划开始批选／排序、Word导出及宿主交付，原OpenCode使用Go套餐DeepSeek V4.1 Flash max实施，Codex独立审核，不通过交回修复直至通过，最后OpenCode提交推送。旧停点被本次授权替代，不扩大应用真实AI、冻结新包、安装更新或发行。

开工工作区干净，分支`codex/desktop-v2-foundation`，HEAD与origin均为`b4b2f7706d681975e92131d388c6e277fa1cfe84`。原会话`ses_ead8af71dffeJphI1NOWg4jZgI`、build、`opencode-go/deepseek-v4.1-flash#max`；OpenCode是实现／测试／验证脚本唯一写入者，Codex维护计划及独立记录。不另起实现者、子代理或分支。

本机CLI 2.1.4 standalone续跑；证据根`<LOCAL_USERPROFILE>/AppData/Local/Temp/kgm-observation-export-20261028-7e7fb3c6`，指针`%TEMP%/kgm-observation-export-current.txt`。派发前脱敏会话5800条消息，529个已跟踪相关文件SHA256基线；不宣称覆盖全盘或用户私有数据。实现者使用`opencode-evidence`／`opencode-temp`，独立执行使用`codex-independent`。

范围及通过条件见[当前任务](../tasks/current.md)、[工程E10–E12／E14](../specs/desktop-game-observation-engineering.md#11-e10列表同日多份与选择)及[Contract§7](../modules/game-observations.md#7-导出与-word)。旧日计划语义及前片工程结果保持。

## 2. 图谱证据边界

开工已调用codebase-memory项目／状态／schema、列表与导出符号查询及旧宿主save_docx双向一层追踪，generation为`2026-10-27T22:53:53Z`。11路径coverage为no_recorded_issue，freshness为metadata_changed或missing，具体结论须直接回读当前源码；不宣称完整或当前同源。首次误用正则形file_pattern的空查询不作不存在证据，后续glob查询已取得符号。未安装或调整工具。

## 3. 实施、回修与独立验证

待原会话停写后逐项记录。实现者自测另存`desktop-game-observation-export-result.md`，独立结果以本记录为准；失败、中断和未验保留，不将打印断言或旧状态当本轮exit 0。

实施中首稿问题R01：纯渲染器＋一张内存合成JPEG独立探针发现`//w:p/w:p=1`，`_append_photos`将返回整段的`_image_paragraph`嵌入另一个段落。此OOXML结构不合规，不能以可解析XML替代Word有效显示。已按已发现prompt API以steer／resume=false交回原会话，要求合法单组段落／直接drawing run及重复图docPr唯一性；私有端点因认证拒绝的首次尝试exit 1保留，随后使用CLI正常背景连接，不提取或输出密码。完整停写复审仍待交付。证据`codex-independent/r01-renderer-structure.json`及`r01-r01-steer-*`保留。

R01中间回修探针自然exit 0：1／2／3张重复合成图各合并两份，嵌套段落均0，drawing数2／4／6及docPr唯一数一致，组序分别`[1,1]`／`[2,2]`／`[2,1,2,1]`。证据`r01-renderer-interim-after.json`，仅为实施期间结构结果，真实Word显示／分页及最终停写验证尚待，不据此提前关闭整个R01。

继续静态审核交回R02／R03（steer证据`r01-r02-r03-*`）：首稿create_export在生成前预检，真正写锁内未复核draft／照片／缺项绑定，须补写锁内短复查及确定性屏障反例；同时整份bytes的8项内存缓存／缓存缺失重生成未满足既定受管临时产物及固定hash／在途生命周期，须完成文件／分块／容量与终态处理。以上是实施中源审发现，尚非最终停写反例结论，后续按实际代码与独立执行核对，不重复已关闭问题。

R04：新preview schema出现`max_length=500`固定份数门槛，已交回移除，不转移到另一层。技术保护应按累计字节／内存／文件与超时实证核定，并在全量分配前有界处理；不能以未经核定的数量限制替代。证据`r01-r04-steer-*`，待最终代码及独立容量验证。

R05独立反例：新宿主`urllib.request.urlopen`默认跟随重定向。两个本机合成HTTP服务＋假凭据的探针自然exit 0，观测为followed／第二服务收到1请求且携带假会话头，故行为不通过；没有使用真实凭据或外网。已交回两条通道固定host／port、不跟随3xx、禁环境／系统代理，并补相应故障验证。证据`codex-independent/r01-host-redirect.json`及`r01-r05-steer-*`。探针exit 0只代表完成观测，不代表产品通过。

R06前端源审交回：preview／create临时生成request_id、未知回包未查询已有导出回执；异步代次／选集顺序变化后确认隔离须补。空记录／坏图不能只显示通用错误，应以安全record／asset标识在UI指具体记录／图片；选集须可区分同日同名多份。空日期sentinel与合法`9999-12-31`冲突，须显式null-last及同ID比较0。要求故障、晚到和排序反例验证，证据`r01-r06-steer-*`，待停写后独立核查，不据静态首稿提前定最终结果。

R05回修中间独立执行：`desktop/.venv-d1/Scripts/python.exe -m pytest desktop/tests/test_d1_observation_export_host.py -k 'redirect or proxy' -q --basetemp <本片独立目录>`，3 passed／3.62秒／自然exit 0；宿主SHA256前后一致。日志及身份见`codex-independent/r01-host-boundary*`。仅该边界已有回修运行证据，完整宿主／全量与最终同源仍待。

R07独立反例：受管export-temp内的sidecar硬链接到根外合成JSON，`st_nlink=2`仍被`_read_artifact_meta`接受。证据`codex-independent/r01-metadata-hardlink.json`；仅操作本片独立合成目录。已交回metadata／DOCX同句柄有界与路径／硬链接／父目录竞态检查，并核清到期DB临时manifest释放、在途保护及重开生命周期，不删业务／历史／AI材料或必要回执锚点。steer证据`r01-r07-*`，待独立复核。

R08独立反例：本机合成服务每32字节间隔40ms传428字节有效最小DOCX，在独立子进程把下载timeout暂设0.15秒，实际0.536秒仍accepted，证明现实现仅socket等待而非完整传输deadline。真实配置未变。已交回JSON及下载总时限／剩余预算、慢响应头／滴流、清理与结果状态；教师原生对话框等待不纳入网络期限。证据`codex-independent/r01-host-trickle-timeout.json`及`r01-r08-steer-*`，待独立复核。

R09完整性源审交回：首稿只接列表导出，缺实际编辑页pre_export闭环和所选现稿的应留历史步骤。按C28、工程§6/E11及Contract§5.1先settle／保存当前UI及应留节点，再固定预览，auto后待留节点不能因isDirty=false跳过；失败／冲突／未知留页，最后输入及晚到响应隔离。只读preview不偷做业务保存，旧daily保持。要求组件和真实产品入口反例，证据`r01-r09-*`，待交付后独立核查。

实施中独立专项中间执行：新合成目录并行执行`backend/tests/local/test_observation_export.py`与`desktop/tests/test_d1_observation_export_host.py`，分别23 passed／19.43秒／exit 0、11 passed／9.01秒／exit 0；日志、命令与相关源码前后hash见`codex-independent/r01-backend-export/`及`r01-host-export/`。本次为仍在实施期间的专项结果，不替代最终停写同源／完整回归／页面／Word证据。

R06／R09接入补充：新编辑页预选将created_at赋为updated_at，后续加入同日同时段记录会错误使用修改先后；已交回读取真实服务端创建键，补“早创建／晚编辑的预选记录＋后创建同值记录”排序反例。不新增业务必填项，证据`r01-r06-r09-created-key-*`。

R03容量补充：首稿累计1亿像素保护不能直接代表串行解码峰值；例如11份各3张2048×1536导出图即超过，可能远未达照片字节保护。已要求移除无依据累计像素门槛或以实测在途／峰值边界替代，并提供代表性多份／横竖图及600图既有边界的实际字节、耗时、RSS和失败完整性探针。64MiB照片／8MiB正文／128MiB文件等须有实证及影响，不把patch阈值测试等同容量核定；必要新增产品限制须交具体证据，不代用户决定。证据`r01-r03-capacity-*`。

R09真实窗口收尾补充：实现者两次窗口动作全部true但实际exit 3，不能记通过。源审发现新导出切页仅清observationsBusy，编辑器exportBusy已上报App.editorBusy，而卸载没有发busy=false，finally的watch可能因父更新卸载被停止，留下page／host busy。已交原会话按当前页身份修正交接，补成功／取消后busy归零及正常关窗；观察值不能只写summary而不判失败，不放宽退出条件或页票据。证据`opencode-evidence/obs-window*`及`r01-r09-busy-*`，待独立实际复核。

交付矩阵补齐已明确原会话：真实WebView2至少跨两页实际勾选／筛选保持／手调／混合合并及文件内容顺序，不仅单份编辑路径；原生保存人工验证与verify-dir自测分别记录。Word服务生成／HTTP／窗口证据不混用，纯renderer容量单列并补真实材料化／读取链实证。脚本不硬编码本次用户Temp目录；相关自测记录真实退出码，停写后由Codex执行全量，避免双方重复同一耗时套件。证据`r01-delivery-matrix-*`。

验证入口补充（`r01-verifier-details-*`）：移除Word helper的`ExecutionPolicy Bypass`，普通调用受控脚本，不改／绕过系统保护；空页辅助判定须分开可见文字与图片，不能把段落／单元格标记当正文，也不能把图片-only页误判空白；记录Word版本／Build。多份文件顺序须比较唯一合成姓名／正文标识，不能只比较重复的类型标题。以上均为证据有效性，不增加产品流程。

独立Word中间执行：新目录`codex-independent/w01-word`经产品导出服务生成7份样本exit 0，11相关来源前后hash一致；XML检查7份exit 0。普通`powershell -NoProfile -File`实际被本机执行策略拒绝，Word自动检查exit 1，不记通过，不使用Bypass或改策略。证据`generation-result.json`、`generate.log`、`xml-check.*`及`word-inspection.*`。桌面venv已有clr／pythonnet，两个Python环境均无win32com／comtypes；已交实现者考虑现有文档COM API，或明确自动受限，Codex继续真实Word UI逐页验证。不得将实现者此前Bypass自测混作本次独立通过，steer证据`r01-word-policy-*`。


独立原生Word逐页中间核查：`w01-word/native-ui-notes.json`记录7样本；01／02／03／04／05／07共1／2／2／6／3／1页已逐页查看，三类型合并起始1／3／5，标题、八行结构、正文、五领域及策略无截断；单图／横竖图、长标题及缺项空日期保持所存事实。06五图为3页，发现R10：第二图片组虽XML内含2个inline，Word实际上下换行；已以`r01-r10-word-pair-steer-*`交回从真实合并单元格可用宽度及margin计算预算并补Word几何验证，不能以XML计数或放宽预期吞掉。旧样本及失败保留，修图宽后按影响重验，尚不关闭R01／R10。此次Word仅打开独立合成文件、未编辑保存，工具modal索引不可用后改用刚取得的有界截图定位；查看缩放变化不算正文修改。

R08响应头残余独立反例：原始HTTP状态行／头每4字节40ms滴流，总deadline设0.15秒后实际0.6907秒才返回timeout；`getresponse()`内部的多次接收未被总时限中断。来源前后SHA一致，见`r01-host-header-trickle.json`。已交回请求／状态行／头／正文完整期限及真实滴头测试，教师原生对话框等待仍不能算网络超时。

R11独立反例：terminal过期快照第一次释放1，下一秒第二次仍释放1、tombstone时间／hash再次改变（`r01-expired-tombstone-repeat.json`，前后来源一致）。最老200行反复入选会制造audit并饿死后续完整manifest；已交回在候选查询中排除已释放锚点、超过一批仍能进展、重复不变。还须处理旧launch已无host可回报的in_progress为未知终态后到期释放，不能永久保留完整临时payload；同一活跃launch的教师保存对话框及真实在途仍保护，不猜测saved，不删业务／历史／照片。证据`r01-r08-r11-steer-*`，待回修复核。

R12固定产物hash独立反例：仅在合成受管目录同时替换DOCX及sidecar大小／摘要，不改DB snapshot/token/operation，同token读取仍200，创建摘要`55d379e3…`被服务头及字节摘要`7384bdef…`替代。见`r01-artifact-rebinding.json`，来源前后一致。已交回以持久化创建事实核sidecar的snapshot／manifest及固定DOCX大小／hash，不以当前可变sidecar自证，拒绝协同替换，不重建或改已发布迁移；证据`r01-r12-steer-*`。

前端独立中间执行`i01-frontend`：83前端路径前后一致，typecheck与独立build均exit 0；完整test:d1在既有W5 pending计时断言失败（1100ms后实际等待0秒，exit 1），核心逻辑及60组件已完成，后续尚未运行。保留日志并单独复核W5、接续历史／更新／观察，未把失败的总命令写成通过，也未删断言或修改产品时钟。

R08 timer初次回修后仍有独立关闭连接反例（`r01-host-closed-connection-body-deadline.json`）：HTTP/1.0响应头／首字节立即，120ms第二字节后静默，150ms总期限实际274.5ms才timeout。`getresponse`已从connection脱离response所持socket，已交回同时中断实际response读取；两通道覆盖且不计教师原生对话框等待。R12回修的200条回执扫描也已交回改为确切回执定位，不能使仍有效的早token因后续创建失效。600各异图完整服务／HTTP／宿主容量链与实际大于旧30MiB的成功样本须补，纯renderer边界与技术阈值patch测试分别记录，不代替真实链。

`i01-frontend`接续独立执行：同源码W5单独重跑94项exit 0，历史22／更新13／观察53项自然exit 0；核心逻辑及60组件来自首轮已完成部分。83前端路径前后全部一致，记录见`result.json`、各log／stderr／exit及`source-before/after.json`。首轮总命令exit 1保留，不写成该命令通过。最终若来源保持，可保留这些完整分套件结果；仍须停止实施后核对整体同源。

Word回修中间独立执行`w02-word`：产品服务生成7份exit 0，11来源前后一致；已改用既有Python.NET／Office文档COM API，7份Word检查自然exit 0，Word16.0／Build16.0.20527，无ExecutionPolicy绕过或新增依赖。首次COM执行尚未加入后续几何断言，不冒称该断言已独立通过。原生UI按影响重新逐页查看03／04／05／06（2／6／3／3页），R10第二图组实际并排、顺序／比例／单图居中及全部正文末页完整；三类型起始1／3／5。01／02／07与w01逐字节完全相同，保留其已完成逐页证据；差异仅03–06的`word/document.xml`。`native-ui-notes.json`与`w01-source-impact.json`保存复看和影响依据，未改／保存DOCX。最终来源与补强COM几何断言仍待停写核对。

最终独立执行已启动：`f01/source-before.json`冻结全部backend／desktop／frontend共413路径的SHA256、Git blob OID、大小与mtime；基线HEAD保持b4b2f77。原会话最后只归并结果，r01实际自然exit 0、metadata outcome=succeeded并明确停写，私有CLI／服务已结束，原桌面后台34156保持。开始回归后的413来源中间复核0变化；最终源同一性仍待收取全部结果后核对。

`f01`已收取：全桌面**298 passed／80.04秒／exit 0**，受保护真实HTTP37项exit 0，真实WebView2全部检查true、实际exit 0（跨两页16份混合、唯一姓名／顺序、照片、编辑导出／取消及page／host busy清除）。完整service／HTTP／host容量入口亦自然exit 0，具体大小／耗时／RSS以该独立report收取为准；当时全local仍在运行，未预先写通过。

原生另存为独立实机：用`kox-7e7f/window1-data`及独立凭据／i01前端启动正常应用，启动前AI任务0。实际UI勾选三类型，默认排序后将第一份下移，固定预览顺序为室内22／公共21／户外23，改名“独立批选观察.docx”。第一次真实系统对话框点取消，UI显示取消、目标目录0文件且DB latest=cancelled（`native-cancel.json`）；点击明确“按同一固定预览重试”，新系统对话框保存到本片独立native目录，UI显示11828字节。只读DOCX／SQLite核对：saved与cancelled两个attempt同snapshot，saved字节及摘要匹配实际文件，SHA256=`80312869914c54d630d32c32a22542a5c1a885b3d83eb35baab43feffb5b6fc1`；三表／三类型标题及姓名22、21、23顺序正确，AI任务仍0，无遗留tmp。关闭弹窗后点系统关窗，窗口及启动进程均已消失；本次Start-Process未保留exit句柄，故不虚报该手动进程exit 0，独立自测窗口实际exit 0另存。启动身份见`native-process.json`，源未因实机取证而改动。

最终回归收取：全local **758 passed／817.01秒／exit 0**；最终7份产品服务Word样本生成、Word16.0 Build16.0.20527 COM几何检查与XML全部exit 0。独立容量链实际：11×3图／103,809,024像素保存246,044字节；16图保存33,877,533字节（大于旧30MiB）；600张各异图材料化／HTTP／宿主保存2,462,995字节、media=600、130.0895秒、进程峰值RSS284,971,008字节；超64MiB照片preview返回413、产物前后均0。这些为本机合成实测，非运行时承诺。

R13新增独立反例（本片编号，与历史已撤回R13不同）：合成fixture在真实宿主取消后只丢失一次终态回报，恢复服务连接，再只读查询与明确固定快照重试。宿主／查询都返回canceled，但DB仍in_progress，新create返回409 `OBS_EXPORT_ATTEMPT_IN_PROGRESS`。`f01/r13-terminal-report.log`／stderr，探针自然exit 0代表完成反例；故尚不通过。已交回原会话修复真实IO终态的待回报识别及安全恢复，查询保持只读、不自动重弹对话框，不猜测saved。需覆盖取消／失败／未知／成功与回包丢失，明确重试先完成必要幂等回报再新token；后台已通过代码若不变保留回归证据，变更按影响复验。

停写同源核对：`f01/source-after.json`与before的413路径SHA256、大小及mtime均一致；随后r02才允许局部回修，不能把其变化冒充f01已执行。最终7份Word与w02逐字节相同（`f01/word-source-impact.json`），沿用已完成的全部原生逐页证据。真实另存为文件又以既有COM入口只读核对3页／3表、标题起始1／2／3、A4、72／90磅页边距、16／11／12字号；实际Word UI逐页确认室内22、公共21、户外23，五领域及策略完整、无额外空末页，查看后正常关闭且未保存文档修改。

## 4. 独立证据汇总（R13回修前）

证据以下列独立目录为准；自测数字不混入本表。全部自动执行使用独立合成资料、既有Python3.14.7标准GIL与依赖，无应用真实AI调用。

| 检查 | 实际结果及证据 |
| --- | --- |
| 全local | `f01/backend.log`：758 passed，817.01秒，exit 0；独立短Temp／basetemp，非原体验库 |
| 全desktop | `f01/desktop.log`：298 passed，80.04秒，exit 0；2项既有warning保留 |
| 前端 | `i01-frontend`：typecheck／独立build exit 0；核心逻辑、60组件、W5 94、历史22、更新13、观察53均通过。首轮总命令因既有计时断言exit 1，原日志保留；W5同源码单独重跑exit 0，83来源完全相同 |
| 受保护HTTP | `f01/http/report.json`：37项通过，进程exit 0；会话／来源、手工保存、材料、历史、合成候选闭环 |
| 真实WebView2 | `f01/window/report.json`：16检查均true，实际窗口exit 0；16份跨两页、筛选保留／手调混合导出、唯一姓名／正文及照片顺序、编辑导出／取消、busy归零／正常关窗 |
| 容量 | `f01/capacity-service/service-capacity.json`：11×3、600张各异图、33,877,533字节DOCX成功；超64MiB照片413且无产物；实测大小／耗时／RSS见§3 |
| Word | `f01/word.log`及`word-xml.log`：产品服务7份生成、Word COM含同行／同页几何、XML均exit 0；Word16.0 Build16.0.20527。全7文件与w02同字节，沿用全部原生UI逐页：1／2／2／6／3／3／1页，混合份起始1／3／5，R10图组实际并排，无遮字／裁切／多余空末页 |
| 真实另存为 | 独立正常应用真实系统对话框取消、同snapshot明确重试、中文文件名保存11828字节；DB／文件hash一致，三类型手调顺序22／21／23；Word3页逐页及COM起始1／2／3通过。手动进程exit未留句柄，不虚报exit 0 |
| 源同一性 | `f01/source-before/after.json`：413文件SHA256／大小／mtime无变化。R13之后按变化路径补复验，未变的后台／模板证据保留 |

最终图谱覆盖已按27个实际引用路径分20＋7分页查询，generation=`2026-10-28T01:17:34Z`，均no_recorded_issue但24源码metadata_changed、3模板not_tracked；`f01/graph-coverage.json`保存原结果。其余索引有既有`.env.example`局部解析与旧MySQL脚本unusable诊断，不据此否定或声称全库完整。所有本片结论仍以定向源读、真实执行及来源hash为依据，二进制模板以ZIP／XML／实际Word验证。

## 5. 保留边界

仅独立合成库／图片／假供应商或已授权副本。原配置／凭据／体验库／OneDrive原件／旧包／远程资源保持。不调用应用真实AI，不冻结新包、安装更新、发行、WebDAV或跨设备。Win10、WPS、干净机器、其他DPI／显示器及D2／D3原未验保持。Word逐页来自本次产品实际导出，源码／HTTP／窗口／Word／包证据分别记录，完整A01–A22及教师产品体验不预先宣布通过。

## 6. 最终独立结论：本片限定工程核查通过

原OpenCode r02于2026-10-28自然exit 0并明确停写，未自行Git。R13局部回修后再次冻结413路径，`f02/source-before/after.json`的SHA256／大小／mtime全程0变化；与f01相比只有模板README、后台导出测试、宿主实现／专项、前端bridge／观察列表／专项共7路径变化。后端产品服务、渲染器、三模板、下载与原子IO实现保持，按影响保留f01全local／HTTP／容量／Word／实际原生保存证据，未重复无变化的耗时套件。

| 最终影响复验 | 独立实际结果 |
| --- | --- |
| 全desktop | `f02/desktop.log`：**302 passed，66.47秒，exit 0**，2项既有warning保留 |
| 后端导出及API | `f02/backend-target.log`：**41 passed，38.00秒，exit 0**，包含新增终态幂等测试；前轮完整local为758，不将未执行的新全量虚报759 |
| 前端全套／新构建 | `f02/frontend`：typecheck、完整test:d1、build:d1均exit 0；核心逻辑＋60组件／W5 94／历史22／更新13／观察54通过。f01之前首轮计时失败仍保留，最终完整命令已实际通过 |
| 真实WebView2 | 新f02前端＋独立`window2-data`，`f02/window/report.json` **16项全true、actual exit_code=0、wrapper exit 0、notes空**；16份跨页混合／手调／照片顺序、编辑导出／取消及busy／正常关闭均通过 |
| R13真实本机API恢复 | `f02/r13-recovery.log`：取消／实际保存各覆盖落账前丢失、落账后回包丢失共4场景，exit 0。查询与同token重入POST=0、仅下载1次；显式补报POST=1、再次补报不写，DB分别cancelled／saved，同snapshot明确新token均201，busy=false；已保存文件hash及mtime不变，取消无文件 |

R01–R13全部关闭：合法Word图片结构／实际同行排版、锁内绑定／固定产物摘要、受管文件和到期生命周期、有界字节保护无业务份数门槛、固定loopback／无重定向代理及完整网络期限、前端幂等／旧响应隔离／排序、编辑pre_export与busy交接、真实IO终态恢复均有源读及独立执行证据。原AI服务片撤回的R13与本片回报恢复R13是不同问题，历史身份不变。

通过范围为当前Windows 11、CPython3.14.7标准GIL、既有依赖、合成资料的源码工程与本片宿主交付；7份Word和原生另存为文件已在Word16.0 Build16.0.20527实际逐页核查。本片应用真实AI调用0次；完整A01–A22、教师体验、复杂真实照片、MiMo、Win10／WPS／干净机器／其他DPI与显示器、冻结新包／安装更新／发行仍未整体验收。当前没有剩余本片编码或回修任务。

## 7. Git收口

用户授权原会话最终正常提交推送，Codex已批准本片相关源码、测试、三份空白模板、验证入口与归并文档；以提交前生成的`approved-git-manifest.json`逐文件Git blob OID为白名单。父提交保持`b4b2f7706d681975e92131d388c6e277fa1cfe84`，分支`codex/desktop-v2-foundation`。不得夹带证据／合成库／凭据／日志／build，不能amend／强推／空提交或另开分支、PR、发行。

Git由原OpenCode／build／`opencode-go/deepseek-v4.1-flash#max`执行；Codex在其自然结束后独立核对批准树、父提交、HEAD与远端、clean工作区及最终脱敏会话模型／代理连续性。实际Git回执保存本片证据根`git-final-check.json`并在本会话末报告，不为回填自身提交hash制造后续空提交。之后停在本片，唯一入口已更新，不自动启动后续工作。

Git前脱敏会话审计：开工5800消息，当前6433；新增602条assistant均build／`opencode-go/deepseek-v4.1-flash#max`，2条agent-switched均build→build，无task／子代理工具。1条自动compaction同模型max，脱敏元数据无agent字段，单列而不冒称实现者切换；初始严格审计把该空字段算异常的失败记录另存，按消息类型核清后通过。源码／测试／验证脚本由原OpenCode写入；Codex仅维护计划及审阅，并校正结果文档的命令相对路径、R项标题和交付时态，不改自测数值。
