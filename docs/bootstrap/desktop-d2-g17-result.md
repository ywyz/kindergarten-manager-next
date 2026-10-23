# G17真实AI验收结果

日期：2026-10-22。最新状态：旧DeepSeek A／B／C及v5、本地导出／冷重启的技术证据保持。r03真实复验中，**新A已审阅采用保存v6；新B成功返回且技术审阅完成，教师确认小班难度适合，但反馈“缺少教师的话”，本轮按质量停止规则停在B，未采用B或发起新C，G17质量未整体通过**，接续见§7。教师话语r3源码整改及限定离线检查通过；新teacher-talk-r01包启动遭Windows策略拦截（4551），已停止，见§7.6。MiMo本轮不测。旧Word两页由用户确认正常，仅关闭该文件逐页子项；不代表新样本、完整G18或发行通过。方案与停止规则见[验收方案](desktop-d2-g17-acceptance-plan.md)。

## 1. 授权与配置

用户原话：“允许，从现在开始允许调用真实AI进行验收”。按既定DeepSeek官方`https://api.deepseek.com`／`deepseek-flash`，再MiMo标准`https://api.xiaomimimo.com/v1`／`mimo-v2.6-flash`，每家A拆分→B目标小班适龄→C其他活动串行；每步审阅／采用／保存后才继续。每家3次业务触发是验收范围，不是预算或HTTP发送保证。失败或结果不明按方案§6停止，不自动补发或换型号。

隔离总根`C:\Users\yw980\AppData\Local\KGNext-G17-20261022`，两家各用自己的data／LocalAppData。普通完整包182文件、EXE `d0e650e8…`沿原就绪记录，未重建；真实样本只用已保存的虚构材料。DeepSeek配置v1／凭据记录1，MiMo尚未配置；Codex不读取密钥内容。2026-10-22实际发起前重新读取DeepSeek官方首次调用与Chat Completions公开文档，地址、模型ID及流式子集未发现变更，不发探测API。

## 2. 逐项结果

| 服务／样本 | 状态 | 候选／采用／保存 | 模型／耗时／usage | 教师质量意见 |
| --- | --- | --- | --- | --- |
| DeepSeek A拆分 | succeeded；1 execution、1 attempt、HTTP 200 | 六字段忠于原文；预览过程追加约定编辑语句，比较／采用保存v3；模型基准未编辑 | deepseek-flash；3500ms；prompt 683／completion 312／total 995 tokens；费用不可得 | 整体反馈为格式需整改，见§5 |
| DeepSeek B适龄 | succeeded；1 execution、1 attempt、HTTP 200 | 目标小班，用v3正式过程；比较／采用保存v4，只替换过程 | deepseek-flash；5485ms；381／510／891 tokens；费用不可得 | 格式需整改；难度未单独定论，见§5 |
| DeepSeek C其他活动 | succeeded；1 execution、1 attempt、HTTP 200 | 目标恢复中班，四板块齐全；仅采用晨间两项，保存v5，未选两板块逐字段及ID保持 | deepseek-flash；17954ms；1567／3423／4990 tokens；费用不可得 | 格式、晨间户外范围需整改，见§5 |
| MiMo A／B／C | 未执行；用户已明确本轮不测 | 未执行 | 无记录 | 不作本轮缺项 |

DeepSeek A发起前记录为隔离总根`real-deepseek-A-preflight.json`：plan `EeumwERsSC8iBadfQilVMg`、内容v2、游戏#2、三类指导r1／契约v1；原文SHA-256 `4fa2dff58b273f33ec3c5724da2be9287d8a5cb26af010e95608852756204a08`。实际结果只读证据为同根`real-deepseek-A-result.json`，不含密钥或供应商思考正文。

### 2.1 DeepSeek A首次返回证据（采用前）

- 本机2026-10-22约19:45发起一次“发起教案拆分”。数据库UTC时间：创建11:45:02.806143，execution 11:45:02.815024–11:45:06.315256；attempt dispatch标记11:45:04.078609，记录duration_ms=3500。该耗时采用应用记录口径，不另估供应商生成时长。
- task `UgizOWh8LVlmpzgS4FG6mw`；input `XV0xfkfPgkZlzC8IRsRSEw`；execution `TQhkrdv4Cwd22anaSJtHUg`；attempt `b8roKsO3-B24lYu1Ek7vwA`（#1）；candidate `eI8gHiwcT2r1d3367SdI_g`，hash `3d4a2e4d7462ae87ca2f2c61600386adc1fc50825c6cca22b584a89a12963389`。provider_request_id不可得，不把本地ID冒充供应商ID。
- task／execution／attempt均succeeded，evidence_code=success、HTTP 200；返回模型与配置均deepseek-flash。真实返回通过当前流式解析、严格JSON及拆分业务schema，1条候选；没有后续重发或探测API。
- 六字段分别与原文“活动名称／目标／准备／重点／难点／过程”去标签后的段落逐字相同，未增加教学事实。原文hash未变；正式正文仍内容v2 `BlheICiSiew7vIfYlu742Q`，split_baseline为空、六字段仍空，两份保留游戏仍在，尚未写入AI结果。拆分候选工程核对通过不等于A采用闭环或教师质量通过。
- 观察到终态“已收到结果”、计时4秒，再次观察仍4秒，默认按钮“折叠思考”；没有捕获到短任务终结前的等待／增量阶段。折叠操作遇控件点击超时，未证实折叠／展开成功；不把按钮存在写成已验证真实思考增量。未持久保存思考正文。

### 2.2 首次控制中断（后续已恢复）

候选成功后，两次按最新访问树点“折叠思考”均报`computer-use request timed out: click_element`，未继续点付费触发。随后截图报`FrameArrived timed out: timed out waiting on channel`；重新枚举唯一隔离工作台窗口47581682后，激活报`computer-use request timed out: activate_window`。重建node_repl会话并重新导入既有sky、重新选择窗口后，截图仍报`IGraphicsCaptureItemInterop.CreateForMonitor failed: Could not capture the given monitor. (0x80070057)`。

只读系统核对：PID5964仍Responding=True，用户会话2为Active／rdp-tcp#0。该证据不能确认桌面是否锁定、RDP是否最小化／断开，或helper／捕获组件是否异常；不能据此判定应用白屏或复开R02。未修改Windows安全／权限、安装工具、结束应用或改业务库。已请用户恢复解锁且可见的Windows／远程桌面后告知，再重新选择窗口恢复控制。

恢复后先打开现有A候选，按方案追加过程编辑语句、比较／采用／保存并只读核对基准与来源；**不得重发A**。A闭环后才发B→C；DeepSeek完成后再让用户在MiMo专用应用内填写其标准密钥。当前MiMo配置／凭据、任务／execution／attempt均0；DeepSeek任务／execution／attempt／candidate各1，内容版本仍2。

### 2.3 可见桌面恢复后：A采用及B／C闭环

用户答复“已恢复，隔离工作台可见”后，同一PID5964／窗口47581682重新选择及截图／输入成功，A已有候选正常打开；没有重发A、改Windows权限或应用实现。可见桌面恢复与工具恢复先后相随，但不足以确认此前捕获错误唯一根因或永久修复。

- A在预览过程末尾追加`教师验收编辑：先观察，再操作。`，比较后“采用并保存”，落库v3 `5W7NXFVIF1ZXlVBhBaLxng`。原始拆分基准仍为未经编辑的模型过程，候选hash未改，原文／其他五字段及两份保留对照保持；baseline与adopted candidate均为A的`eI8gHiwcT2r1d3367SdI_g`。证据`real-deepseek-A-adopted.json`的具名核对均通过。
- B明确选目标小班，输入v3当前正式过程（含验收编辑语句），未把原始基准替代为输入。task `X0beZxJFlXIErWQZVyP6uA`、input `3jMU9LDhNmutCQpzv6I9qg`、execution `pMBivv6opUxLB0m9Ni5vKQ`、attempt `gorGnB00RrimOediBEuRqQ`（#1）、candidate `zwQFuZHqNOOVifa33O6p0w`。比较后保存v4 `CQ5iJaLsR3Ucyo8dgN-uFg`；只替换过程，原文／基准、其余五字段、所有其他板块及中班表头保持。provenance的baseline仍指A，adopted指B。证据`real-deepseek-B-pre-adoption.json`／`real-deepseek-B-adopted.json`具名核对均通过。
- C发起前将本次目标恢复为计划表头中班，两家后续均采用这一相同输入口径；小班仅用于B。输入确为v4正式正文，日期2026-10-22／第8周／周四、teaching及完整节假日窗口、游戏#2与原payload hash；发送快照去除本地group_id／game_id，不含原文／基准或反思。task `gSNgdgQySeRbAq803ta2RA`、input `ysj5SxLEj-tG2SM3J_vosA`、execution `pPXzS2xI9NO8ZAZuNIOoWQ`、attempt `TiVBnmT9az2eMWNKA7Enmg`（#1）、candidate `TGHMCaf1g8SmhElbqT3AsQ`。
- C四板块都有候选，含一集体一自主晨间游戏。预览默认四项均勾选，访问树未暴露勾选状态；以截图核准后最终只选晨间游戏／晨间谈话，再比较／采用保存v5 `riAf6qqdm7qnJl6oaB5PZw`。未选的post_group_games／afternoon_outdoor全部字段及ID与v4逐项相同；集体活动六字段、原文／基准未变、反思仍空。selected_targets_json只存两项true键，省略未选键；早期证据检查器错误要求显式false已修正，应用数据正确，无实现问题。证据`real-deepseek-C-pre-adoption.json`／`real-deepseek-C-adopted.json`具名核对均通过。

B／C均通过当前包流式解析、严格JSON及各自schema，配置／返回模型均deepseek-flash；三类各一个execution及attempt，没有额外任务／重试／探测API。三条provider_request_id均不可得；各自原始usage见表，不由字数估算或推导费用。

### 2.4 流式观察及教育内容局限

B观察到真实“正在思考”，默认展开，折叠成功；终态6秒后不再走时。C观察到排队等待0秒、尚未收到思考文字提示，随后思考6／10／14秒、可折叠并重新展开，终态18秒，后续审阅时仍18秒；运行中仅有取消操作，没有可采用半成品。未捕获短暂的“正在生成结果／正在校验结果”瞬间，不把缺少截图补为已观察，也不额外发请求补镜头。思考正文未写入证据文件；冷启动后进度／思考区域不再出现，三份已落库候选仍可查看。

B输出仍有2—3种图形及“数一数角”，没有完全采用方案建议的两类渐进；已降低语言要求为短问句／指认，不要求完整说明理由，并增加个别提示。这是工程内容观察，教师是否认为适合小班仍待评阅，不能以schema或本次工程采用代替教师认可。C结合四个既有地点，保留慢走／无追逐和大件材料限制；没有写实际发生的幼儿表现或反思。未选的另外两板块建议只保留为候选，不作为正式教学安排。

### 2.5 D本地导出、正常退出与冷重启

首次导出选择“当前日期”2026-10-22，缺项提示9项（保留对照的8个文字空项与反思），按授权材料现状确认导出，未自动补写。原生另存为窗口的UIA元素缓存不可用、focused_element误报搜索框；一次取消保存未写文件，重开后以最新截图确认文件名焦点／全选，键入普通绝对文件路径并回读一致，再回车保存成功。该本地导出重开未新增AI请求。另遇滚动后控件点位超出窗口、过期screenshotId，均刷新截图／访问树后才继续，没有盲点生成或重复采用。

文件位于隔离总根`deepseek/exports/`：

- `G17-DeepSeek-v5-before-restart.docx`
- `G17-DeepSeek-v5-after-restart.docx`

两份均15793字节，SHA-256均`047fd2dadb82d89e3a8cc3a63f3407ea4196dae13587cb1423c1ac98da11f474`，所有ZIP part及document.xml均完全相同。XML核对六字段、晨间游戏／谈话、保留游戏、表头均与v5对应，过程有202个红色文本字符；完整字段文本与来源比较均在本地证据中，未把原始教案或思考另行导出。

PID5964通过正常窗口关闭后退出，同根／独立LOCALAPPDATA冷启动PID25464，正常打开计划读回v5；正文、原文／基准及provenance未变，三任务／三执行／三attempt／三候选均保留、凭据记录1（仅核对数量）。再次导出后仍3次attempt。随后PID25464正常关闭退出，没有强杀。证据为`real-deepseek-D-before-restart.json`、`real-deepseek-D-cold-restart.json`、`real-deepseek-D-export-compare.json`。

Microsoft Word实际打开第二份文件，显示2页；Codex以47%视图查看首尾页，表格在过程处续至第2页，末尾保留游戏及空反思行可见，未见明显截断、重叠或多余空白页，过程红字可见。这是当前窗口的工程目视观察，教师逐页确认／G18和其他Word环境仍未完成；不把低缩放观察写成精细排版或用户验收通过。文件留在Word供用户评阅。

### 2.6 MiMo填钥前准备（最新取舍见§2.7）

DeepSeek已正常关闭；MiMo独立根以同一普通包启动PID31296、窗口52694074，已保存材料仍v2。设置页已通过普通UI预填`https://api.xiaomimimo.com/v1`与`mimo-v2.6-flash`，尚未保存AI配置／密钥，停在可见AI配置卡片。已请用户仅在该应用内填写MiMo标准密钥并点“保存配置”，保存后告知；不读取或复制DeepSeek密钥。用户先前真实AI验收授权仍有效，不再索要同范围调用授权。

本次重新读取MiMo官方Chat Completions页，地址、Flash模型ID、Bearer选项及stream子集仍列出；模型选型页这次工具返回不可访问，不声称该页再次核对通过。尚未访问MiMo推理或探测API。用户保存后先核对非秘密配置／任务0，再沿A→B小班→C恢复中班及D串行完成；遇方案§6问题立即停后续样本。

### 2.7 用户最新要求：先比较标准API性价比

用户在填钥询问中答复：“请对比一下mimo和deepseek标准api的性价比，如果性价比没有deepseek高，就不测试了，deepseek现在也是多模态的模型”。据此暂停MiMo发起，先给公开资料比较；未将“如果”改记为已决定取消，也不以已有真实验收授权绕过本次取舍。

Codex于2026-10-22读取[DeepSeek官方人民币价格表](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)、[官方图像理解指南](https://api-docs.deepseek.com/zh-cn/guides/vision/)、[MiMo-V2.6-Flash官方型号及标准按量价格](https://mimo.mi.com/models/zh-CN/mimo-v2.6-flash)，并用[MiMo批量文档中的实时API列](https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/text-generation/batch-api)交叉核对；以下只比较实时标准API人民币标价，不使用Batch折扣、Token Plan、Go、赠金或汇率换算。

| 元／百万tokens | DeepSeek deepseek-flash闲时 | DeepSeek高峰 | MiMo mimo-v2.6-flash |
| --- | --- | --- | --- |
| 输入缓存命中 | 0.02 | 0.04 | 0.02 |
| 输入未命中 | 1 | 2 | 1 |
| 输出 | 4 | 8 | 2 |

DeepSeek高峰为北京时间周一至周五（不含中国法定节假日）9:00–12:00、14:00–18:00，其余闲时。**按相同tokens比较，MiMo输出单价比DeepSeek闲时低50%、比高峰低75%；不能说MiMo标准API更贵。** 缓存命中／未命中和生成长度会影响实际费用。

本轮DeepSeek实际usage合计prompt=2631、completion=4245、total=6876。仅作同用量算术示例，假设输入全部未命中：DeepSeek闲时`(2631×1+4245×4)/1e6=0.019611元`，高峰0.039222元；MiMo同tokens为0.011121元，比DeepSeek闲时少0.00849元（约43.29%）。**这是标价重算，不是已查到账单，也不是MiMo实测成本**；两家分词、思考及输出长度、缓存、质量和重做率可能不同，实际账单仍不可得。本轮DeepSeek调用发生在闲时，但未取得缓存细分，不能将该估算写成实际扣费。没有引入预算或限额功能。

用户指出DeepSeek已多模态是正确的：当前deepseek-flash／DeepSeek-V4.1-Flash-1017官方支持文本加图像理解；不能再以DeepSeek不支持图片作为选择MiMo的理由。MiMo官方列文本／图像／视频／音频输入、文本输出。当前应用三类任务仍只发送文本，均未接入或验收多模态；供应商能力不等于本应用已具备该功能，本次不启动图片、视频、语音或后置观察记录实现／试验。

工程判断：DeepSeek本项目已完成三类及本地闭环，MiMo本项目质量、速度和实际用量未测，不能只凭标价或供应商宣传证明整体性价比更高。对当前教师个人的少量日计划，示例每轮节省不足0.01元；**建议先收口DeepSeek教师质量与Word验收，MiMo暂缓，资料保留**，而不是宣称MiMo已被证明更差／不划算。若用户以后选择继续，再沿原三类范围填其标准密钥及验收，不新增比较轮次。本次仅完成比较建议，未触发MiMo或任何新增DeepSeek请求，未发布。

### 2.8 最新取舍与只读技术终验

用户已明确：“MiMo本轮不测，继续完成DeepSeek的G17剩余验收，暂不发布”。MiMo为0调用，本轮不判通过／失败，也不作为DeepSeek收口缺项，独立根与草稿保留。2026-10-22只读终验结果为隔离总根`real-deepseek-G17-closeout.json`，14项具名技术核对均true：准确三类成功及各一次execution／attempt、配置、执行修订、模型／usage、候选来源、输入版本／年级、已有采用证据、当前v5、v3–v5来源、冷重启、Word内容／身份及MiMo零调用。仅3次DeepSeek attempt，不为观察短暂阶段补发请求。教师随后反馈见§5，技术通过不消除内容缺陷。

## 3. 验收边界

当前DeepSeek三类协议／候选／采用／保存及本地D核对通过，教师已指出内容问题，未判完整G17／G18通过。MiMo本轮不测；本次两页Word已获用户确认正常，其他Word样本／WPS、Win10、其他DPI／多显示器、干净机器及发行仍未验。供应商缺失元数据记不可得，不按字数估算；旧G13／R02／R03按原收口观察，不自动复开。后续源码整改与新包核查另记，不改写旧包／原样候选的结果；不设计预算、不发布。

## 4. 教师评阅材料

以下原样摘录已返回的教学文本，未为了评阅改写或再次生成。A按中班原文拆分，B仅本次目标为小班，C恢复中班；保存的计划表头始终为中班。完整采用结果及两页排版见[DeepSeek日计划Word](C:/Users/yw980/AppData/Local/KGNext-G17-20261022/deepseek/exports/G17-DeepSeek-v5-after-restart.docx)。

### A：拆分六字段

| 字段 | 模型拆分结果 |
| --- | --- |
| 活动主题 | 找朋友——按形状分类 |
| 目标 | 能分辨圆形、三角形、正方形，并尝试按形状分类；能用“它是……形，所以放在这里”说明自己的选择。 |
| 准备 | 大幅圆形、三角形、正方形图形卡各若干；三个分类垫；玩具小熊一只。图形卡颜色和大小可以不同，材料不放入口中。 |
| 重点 | 观察图形的外形特征，并按形状找到相同类别。 |
| 难点 | 在颜色、大小不同的情况下，仍能按形状分类。 |

过程：一、看一看。小熊带来不同图形，请幼儿说出看见的形状，教师用实物引导观察边和角。二、分一分。教师示范把一张卡放到相应分类垫上，幼儿分组轮流摆放，每人说明一次选择理由，教师对犹豫的幼儿提供比较提示。三、找一找。共同检查三个分类垫，把放错的卡重新分类，再从活动室中寻找相似形状的物品。最后共同整理材料。

预览采用时另加的“教师验收编辑：先观察，再操作。”是本地验收编辑，未混入原始拆分基准；最终Word过程已由B候选替换。

### B：小班适龄过程

一、看一看。教师出示小熊和2—3种基本图形（如圆形、正方形、三角形），请幼儿看一看、摸一摸，说一说“这是什么形状”。教师引导幼儿摸一摸边、数一数角，感知图形的主要特征。二、分一分。教师先示范把一张图形卡放到对应的分类垫上，边说“这是圆形，放到圆形垫上”。幼儿分组轮流摆放，每人放一张，教师用简短提问提示：“它是什么形状？应该放哪里？”对犹豫的幼儿，教师拿相似图形进行比较提示，不要求幼儿完整说明理由。三、找一找。教师和幼儿一起检查分类垫，把放错的图形卡重新放一放，再请幼儿在活动室里找一找与圆形、正方形、三角形相似的物品，找到后指一指、说一说。最后共同整理材料。教师注意先让幼儿观察、触摸，再动手操作，步骤简短，多给予个别提示。

评阅时曾提醒这里仍有2—3种图形和“数一数角”。用户本次反馈集中在换行、编号与晨间户外范围，未逐项认可该小班数学难度；不额外推断为已通过或已否决，后续仍以实际质量反馈为准。

### C：已采用的晨间两项

集体游戏：**图形找朋友（晨间集体）**。

- 重点指导：关注犹豫的幼儿，用“它有没有角？边是弯的还是直的？”进行个别提示。
- 共用目标：能观察圆形、三角形、正方形的主要特征，尝试按形状匹配；在轮流游戏中听清指令。
- 指导要点：使用大幅图形卡和三个分类垫，每次请一名幼儿上前摆放；提示先看外形，再找相同形状，不比较颜色和大小。

自主游戏：**图形区域自选（建构区/美工区/阅读室）**。

- 重点指导：重点指导美工区：鼓励幼儿用大幅圆形、三角形、正方形拼出简单图案，并说一说是哪几种形状。
- 共用目标：在自选区域中继续观察和摆弄图形，愿意与同伴轮流使用材料。
- 指导要点：开放建构区、美工区、阅读室；每个区域控制人数，提醒轮流取放。建构区用大块积木，美工区用大幅图形卡拼贴，阅读室轮流看图讲述。

晨间谈话话题：**生活中的形状朋友**。

问题设计：今天来园的路上，你看到了什么形状？圆形、三角形、正方形分别像什么？如果颜色不一样、大小不一样，但形状一样，它们能不能做朋友？

另外两板块保持“验收保留：搭建桥梁”和“验收保留：沿线慢走”，未采用C对它们的扩写，不要求评阅者把空项当作AI生成缺失。教师反馈和Word逐页意见分别记录，不用“继续验收”或“暂不发布”的指令代替质量认可。

## 5. DeepSeek G17终验矩阵与剩余反馈

| 验收维度 | 实际结果／边界 |
| --- | --- |
| 三类真实兼容与本地闭环 | 当前旧包、Windows 11、既定合成样本技术核查通过；A／B／C各一execution及attempt，采用至v5，导出／冷重启证据保持 |
| 用户教学内容反馈 | **未通过，需整改**。用户原话：“1.内容缺少换行 2.晨间活动均为户外活动，不含区域游戏和室内活动。3.没有1.2.3的列表” |
| 本次Word逐页反馈 | 用户确认“两页均正常”。对应`G17-DeepSeek-v5-after-restart.docx`，15793字节，SHA256 `047fd2dadb82d89e3a8cc3a63f3407ea4196dae13587cb1423c1ac98da11f474`；只关闭此文件的Word逐页反馈，不扩大为全部G18／其他环境通过 |
| MiMo | 用户明确本轮不测；0调用，不记失败／通过、不作为本轮缺项 |
| 新规则和默认指导整改 | 已由原OpenCode交付、Codex独立核查；三类r2、任务指令及版本／保存／Word保护通过，最终r03包身份与窗口波动边界见§6.4。修订指导不能代替真实模型遵循证据 |
| G17整体／G18／发行 | G17保留内容质量未通过；完整G18及发行未验，不发布 |

## 6. 教师反馈定点整改（2026-10-22）

### 6.1 定位与最小范围

codebase-memory项目及两个证据路径覆盖调用均`Transport closed`，限定直接读取当前源码。`backend/app/local/prompt_bundles.py`冻结默认r1仅对拆分目标提到多条换行，过程／适龄缺少列表和分段要求，其他活动晨间指导未限定户外；`backend/app/local/ai_task_service.py::_render_system_text`也无这些底线。原样B／C文本本身缺少真实换行，C自主游戏明确采用建构区／美工区／阅读室。前端候选／正文相关只读展示已有`white-space: pre-wrap`，本次不据模型未换行就认定CSS或Word丢失换行。

已将明确产品要求归并到[D2产品规格§2补充](../specs/desktop-ai-daily-plan.md#2026-10-22-g17教师反馈补充当前有效)：多项／步骤真实分行并以`1. `、`2. `等编号，不强凑三项；拆分只整理原文已有条目格式，不扩写原文；晨间一集体一自主均户外，保留其余板块可用的室内／专用室配置。原文、旧候选、基准、v5与两份Word不得自动重写。

OpenCode仍为唯一实现／测试／构建写入者，沿用原会话`ses_ead8af71dffeJphI1NOWg4jZgI`及`opencode-go/deepseek-v4.1-flash`，不另起实现者。最小交付为三类新默认r2及明确任务指令、对应版本／请求快照／格式保持的合成回归；保持契约v1及输入输出schema、冻结r1哈希和接受／拒绝个人指导保护。无新增依赖、迁移、预算、自动模型重试或新教师流程。

旧普通包182文件及本次G17根完整保留。若交付运行包，使用未占用的独立`build/desktop-d2-g17-content-r01/`，不得覆盖旧包；源码与新包结果分别核查。只使用新的无真实凭据合成根，不读取或迁移默认教师库／当前DeepSeek、MiMo根。整改阶段不重发应用真实AI、不发布；新模型质量证据待具体修订通过离线核查后接续，不能以合成回复代替。

### 6.2 实施与复核状态

原OpenCode同会话已交付两处生产小改、三类r2及相关合成回归和完整r01包，CLI 2.1.2（本机已有版本）exit0。独立源码AST核对11项表明旧schema／冻结r1文字与常量保持；归档直接核对两处生产模块及真实入口同源。独立后端159项中158通过，唯一失败是新增测试在原始HTTP body匹配嵌套JSON未转义字节；已交回仅修测试为两层JSON解析，独立定点复跑1项／1.806秒／exit0，单HTTP和恢复断言保留。没有生产transport问题或改动。Word闭环4项／4.576秒、桌面204项／9.08秒独立通过，含实际Word段落边界、原文／基准与未选板块保护。实现者其他自测见[流式实现结果追加§9](desktop-d2-streaming-result.md#9-g17-教师内容定点整改2026-10-22)，不能代替独立结论。

### 6.3 r01冻结包失败及定点回修

r01目录`build/desktop-d2-g17-content-r01/package/KGNext-D2Verify/`完整182文件，EXE SHA256 `3f6999691efeb71d78da04a4a3d97c39180d4c607abfd9c7d440166a56b69c83`（15067150字节）。Codex独立完整冻结验证实际exit3，**140/142通过**，missing／extra空；仅`res_prompt_bundles_present`及连带`res_exit_zero`失败。其余49模块运行同源、真实入口归档同源、G14／G15与W5合成业务窗口／进度／关闭检查通过，仍仅为此r01包事实。

资源phase实际schema／完整性／FK／prompt sync、凭据、TLS、executor等均true；直接定位`desktop/d1_main.py`约4073行：只查task_type的六条列表与TASK_TYPES的三项列表直接比较，旧自检不支持同任务r1+r2。这是验证入口缺口，不把它写成普通生成或教师数据损坏。回原OpenCode按manifest精确比较task／contract／default／hash，不去重掩盖缺修订；仅改对应自检，必要专项后另建r02。失败包／现场`%TEMP%/opencode/kgm-d2-w6-pkg-63450e1d/`和全部原证据保持，最终新包另核查。

本轮Codex证据根`%TEMP%/kgm-d2-g17-content-codex-20261022-205200/`；`independent-backend.log`保留159项首轮失败，`independent-http-assert.log`为修后定点通过，`independent-word.log`／`independent-desktop.log`／`independent-content-archive.json`／`independent-package.json`分列上述证据。不用修后测试掩盖旧失败，不自动收费重做或发布。

### 6.4 最终r03：定点整改限定离线工程核查完成

资源自检现按manifest精确比较六条`(task_type,contract_version,default_revision,bundle_hash)`；独立`independent-resource-unit.log` **12项／1.84秒／exit0**，含只有r1、缺记录、未知修订、重复和错hash的拒绝。预审另发现helper调用漏传manifest，已交回原OpenCode补齐；r02已捕获漏参版本，归档入口与修后源不一致的证据为`independent-r02-entry-superseded.json`，不作为最终包、不覆盖。实现者实际源码资源相位除预期`frozen_entry=false`外均true，证明调用链可执行；冻结结果另记如下。

| 最终独立证据 | 实际结果 |
| --- | --- |
| 后端和Word | §6.2的159项首轮158通过＋唯一错误断言修后定点通过；Word闭环4项通过，含实际三个Word段落、原文／基准和未选内容保持。后续仅修改资源自检与其专项，两个已核查backend生产模块未再改动，不虚称重跑159全套。 |
| 桌面 | 初轮完整204项通过；资源自检最小修改后仅补相关12项通过，不虚称末轮重新跑205全套。 |
| r03整包首轮 | `independent-r03-package.json`／实际exit3：**129/142通过**，missing／extra空；两次资源、凭据／TLS／spawn、49运行模块同源、真实入口归档、G14采用／保存／Word／重启及全部G15降级通过。W5在设置草稿步骤等待超时，随后`__d1Ai.trigger`对象不可用，后续在途关闭无法完成，共13个关联键false。现场`%TEMP%/opencode/kgm-d2-w6-pkg-ea3274b7/`保留，不能将其写成当时整包通过。 |
| 同包W5定点复跑 | 未改源码／包／校验，调用既有`_run_w5_in_package`，使用全新合成根；`independent-r03-w5-rerun.json` **33/33 true、exit0**，split／other／adapt各1次，适龄已真实到达受控TLS服务，最终outcome_unknown，无开放attempt，worker／服务退出。与首轮合并可覆盖同包142键，但**没有单轮142/142通过**。首轮波动未再现、原因未确认，不称已修复，不复开旧G13／R02／R03或据此宣布完整G18通过。 |
| 归档 | `independent-r03-archive.json`直接读取CArchive／PYZ，**49个归档模块及真实入口，合计50项全部同源**；其中包括两处新指导生产模块。前端3文件与独立构建逐字节一致。 |
| 模型／交付 | `model-audit-complete.json`核对本轮新增**116条assistant全部且仅opencode-go/deepseek-v4.1-flash#default**，末条finish=stop、outcome=succeeded；两轮有效CLI均exit0。本机CLI 2.1.2已存在，未安装升级；首次缺message的CLI在启动模型前exit1，未形成实现轮次。 |
| 原样材料保护 | `final-protection.json`：旧streaming-r10-r11完整包182文件集合／hash保持，原DeepSeek隔离数据库、两份原Word哈希保持，已核查的两个backend生产模块稳定；不扩写成所有历史目录全树审计。 |

最终交付为完整目录`build/desktop-d2-g17-content-r03/package/KGNext-D2Verify/`，**182文件**，不能只复制EXE。EXE SHA256 **`7f3ebbb53649fefc42df940beea65a76d0db2c53dcac0740c406ee6a9f57a333`**（15067834字节）；排序Windows相对路径→文件hash映射摘要 **`f3788ef90ae68a9e9d990c0c8b988c432e815e57b87eb9adfded19627898335c`**。RUN／逐文件hash在同根；r01、r02及原失败证据均保留。包核查使用仓外中文／空格／百分号／井号路径副本，显式合成数据／凭据根、禁dotenv及受控TLS；普通运行不启用这些注入。

本轮仅完成三项指导整改、默认修订保护和相关离线核查；没有用人工编辑的旧样本冒充新模型结果。**DeepSeek仍3次真实attempt，MiMo仍0；未新增真实AI或探测API。** 后续如决定用修正版复验，应使用已核对r03包、先保留原隔离库快照，再经正常应用入口查看／明确接受三类r2，核对实际执行修订；密钥继续只在应用内，不读取、复制或要求重新发送。原授权记录保持，质量问题后停止自动收费重做的规则保持，新增复验轮次由用户决定。真实新输出的教学适用性、完整G18／新Word逐页／WPS、Win10等仍未验，未commit／push／发布。

## 7. r03真实质量复验（2026-10-22）

### 7.1 新授权与复验起点

用户明确同意：“用r03包进行DeepSeek三类各一次的真实复验，逐项审阅、采用并保存后再继续；遇到质量问题、失败或结果不明就停。”本节为新增轮次，旧三次结果保持；不重发已成功的新A／B，不探测API或换型号。

- 只读核对r03清单182文件，缺失／额外／大小或hash不符均0；EXE与§6.4一致。清单原始JSON SHA256为`590cdc127bee92c351b8b43242521d47b7c73c1c472e0a7122ad89a20dc586ee`，路径→hash映射摘要仍`f3788ef9…`。
- 本轮证据根为隔离总根下`recheck-r03-20261022-214516/`。普通应用启动前通过SQLite只读连接的backup建立`deepseek-before-r03.db`，完整性检查ok，SHA256 `f8d91d017b9ee4a06b993c1445d62db39bfc780f064d79985f3c90475d04783b`。起点内容v5，任务／执行／attempt／候选各3，凭据记录1。没有读取密钥或复制凭据文件。
- r03普通入口PID7876，显式原DeepSeek data、原独立LOCALAPPDATA及`APP_DISABLE_DOTENV=1`。DeepSeek配置仍官方前缀／`deepseek-flash`／`chat_completions_v1`；调用前重新读取[官方首次调用](https://api-docs.deepseek.com/)与[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)，未发现当前地址、型号及流式子集的变更。
- 经正常设置界面逐类查看、勾选全部相应字段并接受默认r2；只读落库核对三类个人修订2、based default2、契约1，guidance与对应默认逐项一致。接受设置后真实任务仍3。证据`preflight.json`／`r2-accepted.json`。

### 7.2 新A拆分：已审阅、采用并保存v6

task `UwPh2Kb-jUQtO3wUOrMs9w`；execution `gpkpe_pNVnjTY20C0uviAQ`；attempt `o0l2rycWV4poR8OTC3gQ3w`（#1）；candidate `UOo4ACSodtJOtJVWYLyEZw`。任务／执行／attempt均succeeded，HTTP200，个人修订2／默认2／契约1，返回`deepseek-flash`，duration_ms=7562；usage prompt1009／completion1076／total2085，provider request ID及费用不可得。

候选六字段保持原文内容与顺序；目标2条、准备4条、过程3步，真实换行分别1／3／2个，均连续阿拉伯数字编号，无字面反斜杠n。名称不编号，重点／难点单项保持单段。准备限制及过程末尾整理材料均保留；条目分隔标点变化属于格式整理，没有补写教学事实。Codex与独立只读审阅均未发现需停止的明确内容缺陷，此判断不冒充完整教师验收。

正常界面查看候选、预览比较、采用并保存为v6 `j56SnR6iX06JesFYsMfZXA`；未编辑候选。只读核对六字段等于原候选，原文与全部其他板块保持，拆分基准为新A原始过程，baseline／adopted来源均指新A。证据`A-candidate.json`／`A-adopted.json`。观察到排队、真实思考、终态8秒及折叠；没有为补进度镜头增加请求。

### 7.3 新B小班适龄：成功返回，教师反馈见§7.4

task `UZhX5bhJpRi4jL-4Nzn9xw`；input `UJN8nFC5VE2bNtWt2eP1kw`；execution `PCX0EgM8YmyykX0PPINFeg`；attempt `3NjOs3fe2qdg-C0vofgRRQ`（#1）；candidate `7CWO8RF2aN4zt3SsTCpqNQ`。任务／执行／attempt均succeeded，HTTP200，个人修订2／默认2／契约1，返回`deepseek-flash`，duration_ms=8734；usage prompt545／completion1214／total1759，provider request ID及费用不可得。

输入明确为目标小班、v6当前正式过程；候选只返回完整process，三步真实分行、连续1／2／3编号，保持观察、分类、寻找和整理主题，无已发生课堂事实或反思。它仍保留三种图形，取消说边角及完整解释理由要求，改为看摸、简单命名、每人摆放一张卡；增加小熊礼物盒和整理提示等实施细节。已在普通界面打开候选并预览比较，尚未采用。按此前约定，已向用户呈现三步摘要并请求判断小班教学难度；这不是重复请求真实调用授权。

证据`B-candidate.json`／`B-review.json`记录教师反馈前的技术审阅状态。正文v6，累计DeepSeek任务／执行／attempt／候选各5（旧3＋新A／B各1），新C尚未发起。原拟教师确认后采用并继续，随后因§7.4内容反馈按规则停止。本次尚未生成新Word或作新冷重启验收，MiMo保持本轮不测；未commit／push／发布。

### 7.4 教师反馈：难度适合，教师话语不足，停止本轮

用户对B答复：“适合，但是缺少教师的话”。据此仅确认该样本的小班教学难度适合；教师引导话语的充分性尚不符合要求，不能把有条件反馈记为完整内容通过或采用许可。

原候选实际含“圆形回圆形的家”“看看它圆圆的还是尖尖的”等少量短语，但大部分以教师动作描述呈现，缺少用户期望的教师话语；不将反馈误写为完全没有任何引语。随后用户明确“关键环节补可直接说的引导语、提问和回应”，并补充“以及每个环节教师应当说的话”。据此要求适龄过程的每个环节都有教师可直接说的话，关键处包含上述三类话语，保持已认可的小班难度；不扩大为全程逐字稿或编造幼儿实际回答。已归并[产品规格§2](../specs/desktop-ai-daily-plan.md#2026-10-22-g17教师反馈补充当前有效)。

按本轮约定，真实验收停在B：未采用或手工补写原候选、未发新C、未重新调用A／B。只读核对正文仍v6，B采用来源记录0，其他活动任务总数仍1（旧轮C），任务／执行／attempt／候选各5。原候选、A已保存结果及复验前快照保持，证据`B-teacher-feedback.json`。下一步由原OpenCode会话按已明确要求作最小整改，Codex独立核查，不把整改或再次收费复验视作已完成。

### 7.5 教师话语最小整改：实施入口

仅调整适龄任务指导和系统指令，以新默认修订交付；已发行r1／r2冻结，拆分与其他活动不增修订，schema和契约v1保持。实现／测试／构建仍由原OpenCode会话和既定Go模型负责；Codex文档、审阅及独立验证。新证据根`%TEMP%/kgm-d2-g17-teacher-talk-codex-20261022-222331/`已保留工作区hash、Git状态、r03包／真实数据库／Word保护基线。真实验收保持停止，旧包与数据不覆盖。

本次codebase-memory可用：project `C-Users-yw980-code-kindergarten-manager-next`、generation `2026-10-22T13:33:09Z`；五个定点路径coverage均为metadata_changed，结构查询后按技能读源码核对，不声称图谱完整或重新索引。

OpenCode两处生产变更为适龄专属r3默认及system指令，保持每环节教师具体话语、关键引导／提问／教师回应、按年龄表达且不额外增加要求；无需年龄调整时仍补齐话语。Codex审阅纠正了将本次“看、摸、简单命名”误用为所有小班活动限制的措辞。三任务各r1／r2共六条tuple与存量库hash、重新计算hash逐项一致，仅追加适龄contract1/default3，hash为`f2c4a308db6d74b0754ce1c9370d5d551f867ad91ca1e0bcb3e39ef713353e4e`。输入输出schema不变，拆分与其他活动仍r2且无话语扩展；个人接受／拒绝机制保持。

独立源码审阅与验证已通过：`independent-version.log` **58项／10.766秒／exit0**；`independent-behavior.log` **63项／51.705秒／exit0**，涵盖受控TLS适龄单HTTP实际请求、r2接受／拒绝r3及版本钉住、适龄候选经HTTP预览／采用／保存／冷重启／Word；四个非空其他活动板块、反思及其余五字段采用后／重启后整对象等值，原文／基准保持，Word六个段落与教师引语全文等值。`independent-resource.log` **12项／1.84秒／exit0**，七条manifest精确集合及缺失／重复／错hash拒绝。总计后端121项和桌面12项，未重复跑无关全套。行为验证前后六个关键源／测试hash稳定，完整已审阅11文件hash见`reviewed-source-hashes.json`。

实现者曾修正排序预期与两次错误的preview字段断言（正确键为`group_activity.process`）；首次日志保留，不记为生产API缺陷。采用／Word测试已按Codex要求补齐非空未选板块对照。原桌面资源helper生产代码未改，仅测试随七条manifest更新。完整包已在独立新目录`build/desktop-d2-g17-teacher-talk-r01/`构建；冻结验证失败并停止，见§7.6，未新增真实AI调用。

### 7.6 新教师话语包：Windows策略阻止启动，停止

新完整目录`build/desktop-d2-g17-teacher-talk-r01/package/KGNext-D2Verify/`共182文件；EXE SHA256 `cf3d4b4ca3892b838cab305ab91b6cd37686788d89965dcf19ad9120368a262a`，15068542字节。Windows相对路径→hash映射摘要`28304d72e41a15cb5dd2268d054438603ee046b9a4628eb3439da475cd1e6d6a`；原始`package_hashes.json`文件SHA256 `aaf3495e4047d7a14740a9fbe21c2165cbac1109c93c97028cb801b5530a5f77`。逐文件独立核对缺失／额外／hash／大小差异均0，已审阅11文件hash保持。此清单核对不代表包运行通过。

Codex执行现有`verify_d2_w6_package.py --stream`，保留仓外中文／空格／百分号／井号路径和独立合成数据根。**实际exit3，在首资源相位CreateProcess返回WinError4551“应用程序控制策略已阻止此文件”**，应用尚未启动。报告仅记录6项静态复制／资源核对true，未到142项运行检查，不计算通过率、不宣称归档50模块同源或窗口通过。证据`independent-package.json`／`.log`／`.exit.txt`，现场`%TEMP%/opencode/kgm-d2-w6-pkg-2b5224b6/`全部保留。

只读查询同一时刻的Windows CodeIntegrity事件：2026-10-22 22:41:28，3033／3077均指向同一复制EXE，说明未满足Enterprise signing level或违反代码完整性策略，Policy ID `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`；证据`codeintegrity-events.json`。该证据不等于已经确定具体签名／信誉判定原因，未将其记为业务逻辑缺陷。**立即停止新包运行验证与后续真实复验；未重试、换路径规避、修改安全设置或重建试错。** 已通知原OpenCode停止后续执行；该会话已完成构建并idle/succeeded，无继续运行。

`model-audit-final.json`：本轮新增67条assistant全部为原会话的`opencode-go/deepseek-v4.1-flash#default`，最后finish=stop／outcome=succeeded，CLI实际exit0；这是实现交付状态，不抵消Codex冻结验证exit3。`final-protection-package.json`：r03 EXE及清单、原真实数据库和旧Wordhash保持；DeepSeek任务／执行／attempt／候选仍各5，正式正文v6，B采用记录0；MiMo任务0。原B、A已保存结果和旧包保留。未commit／push／发布。

结论：每环节教师话语的源码整改和限定离线验证通过；新完整包被本机Windows策略阻止启动，**包运行验收及真实教学质量均未通过，当前停止**。不自动重发B或发起C；先处理已查明的本机启动阻塞，再决定后续复验。

## 8. 4551定因与设置窗口关闭（2026-10-23）

用户授权“查明并解决新包被Windows错误4551拦截的问题，保留原数据”，并追加处理已取消编辑仍无法关闭的窗口。本节取代此前仅定位到策略阻止而未定策略类型的状态；不恢复真实B／C、不改原包或数据。

### 8.1 已定因：Smart App Control强制策略

新证据根`%TEMP%/kgm-d2-g17-4551-close-codex-20261023-173909/`。只读`Get-MpComputerStatus`返回SmartAppControlState=On，防病毒／实时防护均开启；CI注册表VerifiedAndReputablePolicyState=1。系统版本25H2、build26200.9711。普通权限`CiTool --list-policies -json`返回0x80070005，未提权；不据此假称取得完整策略清单。

旧拦截事件XML的3077明确给出PolicyName=`VerifiedAndReputableDesktop`，PolicyGUID=`{0283ac0f-fff1-49ae-ada1-8a933130cad6}`，status=`0xc0e90002`，flat SHA256精确匹配新包`cf3d4b4c…`。同一ActivityID的3089给出TotalSignatureCount=0、Publisher/Issuer=Unknown；3033为同一EXE签名等级拒绝。结合本机SAC On，确认是**Smart App Control的执行拦截**，不是设置草稿、数据库、换行内容或应用启动后异常。

`Get-AuthenticodeSignature`新EXE和旧r03均为NotSigned，两个EXE均只有默认数据流，没有Zone.Identifier；因此不把问题归因下载封锁标记、不运行Unblock-File。旧unsigned包曾运行不代表新文件也一定获云端信任。现有本地事件不足以区分云端判定为未知还是负面，不把未签名直接写成恶意软件。CurrentUser/My及LocalMachine/My两个证书存储中代码签名证书数0；未读取私钥或搜索秘密文件。

根据[微软SAC FAQ](https://support.microsoft.com/en-us/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions)，SAC没有逐应用允许入口；[官方签名说明](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control)要求可信提供者证书。当前没有可直接使用的签名身份，未申请／购买证书、改全机防护或套用测试策略。官方[文件复核入口](https://www.microsoft.com/en-us/wdsi/filesubmission)提供Software developer／Smart App Control类别、50MB上限；已准备仅单独15,068,542字节EXE的`submission-manifest.json`和`microsoft-smart-app-control-submission.txt`，不包含数据库／凭据／Word目录。因外发程序代码，当时已请求用户明确上传授权；后续授权及取消见§8.3。尚未上传、未获微软复核结论，**4551尚未解除**。正式签名可作为后续稳定交付方案，不承诺复核立即放行或覆盖新hash。

### 8.2 无法关闭的设置窗口：当前会话已解决

Computer Use发现唯一KGNext窗口为旧`desktop-d2-streaming-r10-r11`的MiMo隔离应用，窗口52694074，端口61710；不是被阻止启动的新teacher-talk包。页面显示通用设置v2、AI配置v0/尚未配置/没有密钥，但AI地址和模型框仍有`https://api.xiaomimimo.com/v1`、`mimo-v2.6-flash`未保存草稿。用户所述底部取消后状态并未清除这一独立AI草稿。

通过正常界面点击**AI配置区域的“取消编辑（还原）”**，观察“已取消AI设置编辑”且地址／模型字段还原为空、仍v0；随后点击窗口关闭按钮。重新枚举窗口确认KGNext窗口为0，正常关闭成功；没有强制结束进程、应用任何设置修改、清密钥、触发AI或写数据库。

`data-before.json`与`data-after-close.json`逐项一致，包含两库文件SHA256及只读元数据：DeepSeek正文v6、任务／attempt各5、AI配置版本记录1；MiMo正文v2、任务／attempt0、AI配置版本记录0。两份原库字节完全保持。此次仅解决该现有会话残留草稿的关闭问题，不冒充修复代码或认定所有关闭分支通过；未重开历史事件全面测试。未启动OpenCode、未改实现／测试／构建，未commit／push／发布。

### 8.3 微软文件提交取消，转向代码签名研究

用户曾明确同意“仅上传这个EXE和说明”。2026-10-23 Codex核对原EXE仍为15,068,542字节、SHA256 cf3d4b4c…；浏览器打开微软官方文件提交入口并选择Software developer后，页面要求登录Microsoft账号。没有输入账号或身份材料，没有上传EXE或说明，没有形成回执。用户先选择“暂不登录，保留待提交材料”，随后明确“我们不再提交，因为新应用还需要验证，思考我们如何获取代码签名证书”。据此取消后续上传，之前的单EXE外发授权不再执行；本地材料和原包保留。

用户明确申请主体为中国大陆个人。当前仅进行官方资料研究，不注册账号、提交证件、购买证书、签名或改构建；未改安全设置／真实库或调用AI。签名能力、包运行验证及真实教学质量分别记录，研究或取得证书都不等于4551已解除或产品已验收。
### 8.4 中国大陆个人代码签名：官方资料研究与建议

核对日期2026-10-23，申请主体由用户明确为中国大陆个人；以下为研究结论及建议，不是供应商受理或购买决定。

- [Azure Artifact Signing申请条件](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart)的Public Trust个人仅限美国／加拿大，大陆个人目前不适用；选择海外机房不改变身份资格。
- [SSL.com IV个人证书](https://www.ssl.com/products/software-integrity/code-signing/iv/)明确不要求企业主体、验证后显示个人实名，公开一年证书价US$129。[国家代码页](https://www.ssl.com/country-codes/)接受China/CN，但这是通用CSR国家表，不能当作已确认大陆IV证件和eSigner开户一定通过。列为优先向官方核实的候选，未联系供应商。
- [eSigner官方价目](https://www.ssl.com/guide/esigner-pricing-for-code-signing/)的IV最低档为US$20/月含20次，或US$180/年含240次，另加证书；常规年付基础预算US$309，不含税及超额。240次为签名次数，不能当作240次整包发布；须先清点需签二进制与每轮变化量。私钥保管在云HSM，是否接受大陆个人、网络可用性、具体工具的数据传输范围仍应确认。
- IV专页token为US$379，连同一年证书首年基础预算US$508，未含运费／税。eSigner营销页另显示US$249，官网存在价差，应索取明确的IV报价及续期复用规则，不能采用较低数字作承诺。现行IV私钥需要合规硬件token或云HSM，不能按普通可导出PFX交付假设。
- [Certum Standard](https://www.certum.eu/en/code-signing-certificates/)也明确可用于个人；[云版产品页](https://shop.certum.eu/standard-code-signing-in-the-cloud.html)公开起价€209，需SimplySign手机与桌面客户端，限5000次/月。大陆身份验证、实际可购套餐与税费尚未确认，仅作备选；不把€139电子激活码当作包含云签或新硬件的全价，也不采用未经确认的代理价格。
- [微软SAC签名要求](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control)要求受信任提供商签发的有效签名，不要求普通桌面应用一定使用EV。签名并非产品质量认证；[微软签名选项](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options)明确EV也不再即时跳过SmartScreen信誉判断。当前4551是SAC拦截，不混写成SmartScreen警告。

建议路径：先取得官方对大陆无公司个人IV受理、可用中国证件／姓名格式／回拨要求、证书链及SAC用途、云签或token含税总价的书面确认，再决定是否申请。可供用户发送的询问要点为：“我是居住在中国大陆、没有注册公司的个人开发者，需要为Windows 11普通桌面应用取得公开受信任的Authenticode代码签名证书。请确认是否受理IV、接受哪些中国证件和姓名格式、是否可使用eSigner及其网络／签名次数／超额计费规则，并分别报价一年云签和token方案（含大陆配送、税费和续期成本）。”当前未发送此询问或任何身份材料。

申请核验的是发布者身份，可在产品尚待验证时规划办理；取得签名能力后，建议由原OpenCode在独立新包加入签名和时间戳步骤，保留旧包。Codex独立检查签名链、时间戳和实际加载的EXE／DLL／PYD，再在SAC保持开启的原机用独立合成数据验证启动、保存、导出和关闭。通过后才按原规则决定真实B／C接续。申请、签名、运行验收、真实AI质量和发布分别记录；原数据库与凭据根不动。
## 9. 国内签名渠道与下一步提示词（2026-10-23）

用户要求研究中国大陆代码签名机构（如阿里云、腾讯云），思考项目下一步并撰写提示词。主体仍为中国大陆自然人、无公司；本轮只研究公开资料、读取包元数据和写文档，未联系供应商、注册／申请／付费／上传身份或程序材料、启动OpenCode、签名／重建／启动应用或真实AI。先前微软文件提交取消决定保持。

### 9.1 国内渠道核对

渠道与实际CA需要分开记录。云平台账号可以个人实名，不代表其中代码签名商品接受自然人；网站TLS证书、合同电子签名、软著及驱动WHQL也不等同本项目所需Windows Authenticode代码签名。

| 渠道及来源 | 已核实的公开信息 | 对本次个人申请的判断 |
| --- | --- | --- |
| [阿里云云市场cmfw00068619](https://market.aliyun.com/detail/cmfw00068619) | 服务商为上海环度信息科技有限公司，内容由服务商提供。Certum OV云签新购880元/年、续费800元/年；EV2300元/年。实际签发CA为所选品牌，不能称阿里云自行签发。 | 值得优先核实的国内渠道；当前商品未明确承诺接受大陆无公司自然人，项目用途限制待确认。价格仅为展示值，完整费用及具体SKU待书面确认。 |
| 环度[个人版商品](https://www.ihuandu.com/product/109.html)与[型号说明](https://www.ihuandu.com/pr/codesigning/974.html) | 商家个人版600元/年页面明确涉及开源许可、Open Source Developer；型号说明又泛称个人工具／客户端。 | 不能把600元开源产品与880元Standard/OV套餐混用。本轮未授权改变项目公开状态或许可，不为购买低价证书改变许可或公开代码。 |
| [腾讯云自营CSC购买指南](https://cloud.tencent.com/document/product/1369/51170)（2025-07-01更新）及[产品页](https://cloud.tencent.com/product/csc) | 明确只有企业用户可申请；基础版6800元/年、EV9800元/年，线下购买；产品页称DigiCert根签发。 | 本次纯个人身份不适用。申请表的“个人姓名”是联系人，不抵消企业资格。腾讯云市场第三方商品须另核，不能继承自营资格承诺。 |
| [沃通当前标准Pre](https://www.wosign.com/Products/ov_codesigning_pre.htm) | 当前页面展示GlobalSign代码签名链、硬件介质、3588元/年，以及单位／营业执照要求。 | 未证实当前纯个人受理，暂不列可购买个人方案。不能采用仍含旧WoSign根、SHA1、可导出PFX的旧个人页面作为现行证据。 |
| [CFCA原代码签名页](https://www.cfca.com.cn/20150916/101253434.html)及[现行CP/CPS索引](https://www.cfca.com.cn/cfcacps/cfcaglobaltrustcpcps/) | 旧页提到个人／企业但还保留1–5年等旧信息；现行索引列2026-10-16 V4.16，PDF抓取未完成。 | 本轮未确认个人现行资格、实际链、硬件／云签及费用，不能据旧页承诺SAC适用或可购买。 |

[Certum官方Standard说明](https://www.certum.eu/en/code-signing-certificates/)允许个人或公司，说明Standard品牌本身并非仅企业，但不证明每个国内销售SKU均受理自然人；需对上述880元套餐逐项确认。国外SSL.com IV仍保留为备选，事实及待确认项见§8.4。公开网页没有闭合的资格问题，不能用推断补成已获准签发。

以下为待用户使用或明确授权后发送的咨询文案，本轮没有发送：

> 我是居住在中国大陆的自然人，没有公司或个体工商户，需要给本人开发、目前仍在验证阶段的Windows 11桌面程序签名。请分别说明Standard与开源专用套餐的用途和许可限制。请确认贵司阿里云商品cmfw00068619中880元/年的Certum OV云签，实际对应CA哪款Standard产品，能否以个人实名申请，对非公开或非开源软件是否存在限制？请提供CA资格及用途依据、发布者显示名称、可接受的中国证件与验证步骤、是否需翻译或公证、完整首年和续费含税报价、云签次数与超额规则、核验失败退款条款。另请确认是Windows Authenticode公开信任证书，提供根与中间链名称、代码签名用途及时间戳说明，用于SAC开启的Windows 11；是否需要上传完整EXE还是只传摘要，私钥由谁保管、如何撤销，是否可以本地使用SignTool签EXE、DLL和Python扩展PE文件。签名责任归本人、需自行授权操作；请明确是否涉及第三方代签。本阶段仅咨询，不提交证件或程序文件。

### 9.2 当前包的签名前只读清单

本轮对teacher-talk-r01现存包逐项读取文件hash和Get-AuthenticodeSignature，未执行二进制、未改包。结束时主EXE及DeepSeek／MiMo两库SHA256与§8前后证据一致。证据根`%TEMP%/kgm-signing-readiness-20261023-175905/`，本地持久副本为`build/desktop-d2-g17-teacher-talk-r01/signing-readiness/package-binary-signatures.json`。

| 文件类型 | Valid | NotSigned | 合计 |
| --- | ---: | ---: | ---: |
| EXE | 0 | 1 | 1 |
| DLL | 56 | 5 | 61 |
| PYD | 20 | 17 | 37 |
| 合计 | 76 | 23 | 99 |

现有Valid签名主体包括Python Software Foundation、Microsoft Corporation、Microsoft Windows Software Compatibility Publisher。这里的Valid是本机Authenticode读取结果，不等于全部SAC加载路径已验证，也不代表已完成时间戳／撤销检查。现有供应商有效签名应保留。

23个NotSigned文件包括主EXE、cffi／cryptography／greenlet／lxml／markupsafe／pydantic_core／SQLAlchemy扩展，以及ClrLoader、Python.Runtime和WebBrowserInterop。清单含x86/x64分支，不能推断都在本机实际加载；也不能为减少签名费用直接删除或替换依赖。它们是待分析的签名候选集合，不是已经批准全部用个人证书重新签发的名单。第三方归属、许可证、上游签名可能性及加载范围需在签名方案中逐项说明。

20次/月云签套餐不能当作20次发包。若某轮23文件均需签，已超过20次；若240次年档每轮都重签23文件，仅约10轮。此为条件估算，不是实际用量：稳定依赖可在确认内容hash不变时复用已签文件，最终以待签名单、工具计费定义和供应商报价决定。

### 9.3 当前应做与后续条件

当前优先级是签名资格／套餐确认和签名前工程准备，不追加产品功能。适龄r3源码及121后端／12资源检查已经通过，没有新变更或具体缺口不重复全套；静态签名清点不补成冻结包验收。由Codex把现有证据、待确认项和咨询文案准备好；联系供应商、上传身份材料、付费采购均尚未授权，证据不足处标待答即可，不反复泛搜或假称已解决。

取得可用签名身份且用户决定实施后，仍由原OpenCode会话与既定Go Flash写最小构建签名／验证改动；独立目录产出新包，原包及首次4551证据保留。先核查自有及第三方待签PE、有效供应商签名保留、工具传输范围和密钥保护，再安排SHA256 Authenticode、可信时间戳、签后完整性验证和签后清单。不得以更换hash、移路径或降低防护试错；不提前选定安装器、云CI或另换打包技术。

Codex随后独立验证签名／时间戳／链及源码同源，再保持SAC开启、用独立无真实凭据合成根执行既有冻结包验收（含资源、保存、Word、重启和窗口关闭等相关检查）。新失败／结果不明立即保留现场并停止，不循环重签／重建／重试。包通过后再提出具体真实复验安排：新A已保存v6不重做，B沿r3要求审阅每环节教师话语和小班难度，采用保存后才继续新C；当前不预先发任何真实请求。未签名包运行、真实AI质量、完整G18及发行状态都不因规划而改为通过。

唯一执行提示词已原位更新为`docs/tasks/current.md`。未另建提示词版本、未启动OpenCode、未commit／push／发布；所有现有未提交改动和未跟踪独有材料保留。

## 10. 暂停签名，转入D3-A设计（2026-10-23）

用户最新决定“暂时不做签名，我们往后推进项目”，取代§9.3的当前优先级及旧提示词中“无签名身份时不推进D3”的限制。代码签名资格、供应商咨询、采购和构建签名工作均暂挂；微软文件提交继续取消。既有国内渠道研究、咨询文案、99个PE清单及首次4551证据保留，不重复搜索或执行。以后恢复签名准备时，仍需核实23个NotSigned候选的归属／许可／实际加载与上游签名、保留76个现有有效签名、明确工具传输范围和次数，不能直接把清单变成全量重签指令。

按已确认阶段顺序，D3是保存保障与发行配套，D4才是游戏观察记录。现在先推进不依赖签名的D3-A本机日计划历史查阅、比较与整份恢复；不启动WebDAV、安装升级、游戏观察或其他后置业务。用户已确认两项产品选择：

1. 第一版整份日计划恢复，预览差异后生成新版本，恢复前的内容仍保留历史。
2. 打开历史记录时有未保存正文，先保存当前修改，再查看历史；无修改不额外保存，失败或结果不明留页。

规格见[本机日计划历史恢复](../specs/desktop-daily-plan-history.md)，唯一提示词原位改为D3-A接续。恢复需保留原文、完整正文、历史组／游戏身份与合法拆分基准，独立记录恢复来源，不伪造新的AI采用；已有任务和候选继续按原依赖及版本保护处理，不自动调用AI。源码依据来自限定只读核查：codebase-memory项目列表及覆盖查询均Transport closed，未取得图谱覆盖，不把缺失图谱当作不存在代码。

本轮交付规格和下一步实施提示词，尚未派发OpenCode或修改实现／测试／迁移／构建。后续由原OpenCode会话和指定模型先做H1数据／本机API，Codex核查后再做H2界面；H3新包运行仍受4551阻塞，源码验证不能替代包运行。D2保持新A已采用保存v6、B未采用、新C未发起、累计DeepSeek5次attempt及MiMo0次；不因推进D3改变G17/G18或产品发行状态。

原真实数据／凭据、旧包、teacher-talk-r01及Word保持，本轮没有运行应用、迁移真实库、发真实AI、修改安全设置、commit／push或发布。后续隔离验证只用独立无真实凭据的合成根，不把源码启动作为被拦包已通过或规避SAC的替代结论。
