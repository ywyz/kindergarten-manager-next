# G17 候选服务官方文档兼容性核对

核对日期：2026-10-21。依据用户指令：预计使用DeepSeek、MiMo及OpenCode Go，先查官方文档，不设计预算限额，不实际调用真实AI或发布。

**2026-10-22补充见§7：DeepSeek三类真实成功及采用／保存／本地导出与重启核对通过，终验14项技术核对全true。用户已明确MiMo本轮不测，仅收口DeepSeek G17，教师质量意见待回、暂不发布；最新状态见§7.10及[G17结果](desktop-d2-g17-result.md)。§1–6及§7早期状态保留为当时事实，不以新结论覆盖旧证据。**

后续用户决定应用仅使用DeepSeek官方API及MiMo标准API，不使用Token Plan或Go，并确认实时思考展示；规格见[流式思考与等待反馈](../specs/desktop-ai-streaming-progress.md)，实现后的独立结果见[核查记录](desktop-d2-streaming-review.md)。以下保留31a3c9a非流式基线与当时三项候选的官方核对证据，不冒充新流式或真实供应商验收。开发工具OpenCode的Go套餐DeepSeek V4.1 Flash已明确可继续使用。

结论：**DeepSeek官方API与MiMo标准API符合核对时的非流式最小请求／响应形状，可进入后续G17配置准备；尚未验证真实兼容。MiMo Token Plan不适用于本应用后端；OpenCode Go有公开API，但用途与客户端要求尚未满足，暂不列为当前包可直接接入的服务。** 这是针对现有应用的技术核对，不新增供应商白名单或改变Q7产品决定。

## 1. 文档核对时的应用基线（31a3c9a）

依据当时的[产品规格§11](../specs/desktop-ai-daily-plan.md#11-openai兼容接入边界)及31a3c9a源码；当前协议以该规格及流式核查为准：

| 项目 | 核对时行为与证据 |
| --- | --- |
| 地址／鉴权 | HTTPS API前缀追加一次`/chat/completions`；`Authorization: Bearer`、JSON POST；不跟随重定向，不继承未知代理 |
| 请求体 | `ai_transport.py`的`build_request`（320行起）只发`model`、system／user文本`messages`、`stream:false`；不发tools、`response_format`或thinking参数 |
| 请求头 | 同文件`_http_request_bytes`（332行起）自行序列化HTTP，不经SDK；没有`User-Agent`或`x-opencode-session` |
| 响应 | 同文件`_parse_success`（665行起）要求一个choice、`finish_reason=stop`、字符串`message.content`中的单个严格JSON对象；非空工具调用／拒答不通过；之后另做任务schema／业务校验 |
| 元数据 | 可得返回模型／request ID／usage脱敏记录；不读取`reasoning_content`作为候选，不把它写入正文 |
| 工程保护 | 原有连接10秒、单次尝试120秒、请求／响应各1MiB及有限安全重试保持；不增加token或费用预算设计 |

本轮按已读codebase-memory技能尝试项目查询及上述证据路径覆盖核对，工具均返回`Transport closed`；已回到已知路径直接读源码、检索请求头及调用位置。没有重建索引、安装工具或声称完成全仓结构审计。

## 2. 候选配置与文档级结论

下列API前缀均为资料记录，**未写入应用或发送请求**。模型是候选标识，用户尚未确定最终测试型号；不把同名模型在不同服务上的表现视为相同证据。

| 服务 | 应用API前缀 | 本轮相关模型候选 | 文档级结论 |
| --- | --- | --- | --- |
| DeepSeek官方API | `https://api.deepseek.com` | `deepseek-flash`；另有`deepseek-v4-pro` | Bearer、文本消息、非流式Chat Completions和正常文本结果形状匹配；可准备G17。`deepseek-flash`当前由DeepSeek-V4.1-Flash-1017提供服务。[D1]、[D2] |
| 小米MiMo标准API | `https://api.xiaomimimo.com/v1` | `mimo-v2.6-flash`、`mimo-v2.6-pro`；文档另列`mimo-v2.6-pro-ultraspeed` | 支持Bearer，并非只能用`api-key`头；标准请求／正常响应形状匹配，可准备G17。[M1]、[M2] |
| OpenCode Go | `https://opencode.ai/inference/go/openai/v1` | `deepseek-v4.1-flash`；亦列`mimo-v2.6-flash`／`mimo-v2.6-pro` | 上述模型有Chat Completions端点；协议端点存在不等于当前客户端与用途符合要求，见§4。[G1] |

实现工具中的`opencode-go/deepseek-v4.1-flash`包含OpenCode供应商前缀；不能原样当作DeepSeek官方API模型ID。Go的API模型ID也不含`opencode-go/`。[D1]、[G1]

## 3. DeepSeek与MiMo仍需实测的部分

- 两份Chat Completions参考均允许当前必需字段，支持非流式正文与`choices[].message.content`，正常完成可为`stop`；额外能力无需启用。[D2]、[M1]
- 当前相关型号默认启用thinking，DeepSeek默认思考强度为high；这些默认值没有被应用覆盖。返回独立推理字段并不替代最终正文，也不能证明能在现有120秒内完成。[D2]、[M1]
- 两者提供可选JSON输出模式，但当前应用没有发送`response_format`，不能称已启用供应商JSON模式。现有提示词要求JSON，应用再严格校验；是否稳定得到完整任务JSON、是否适龄、能否采用／保存，均待真实G17。[D2]、[M1]
- 本轮不据此自动新增thinking／JSON参数、调整超时或扩大协议。若将来实测发现明确问题，先保留错误和发送证据，再交OpenCode做最小修复。

MiMo必须分清标准API与Token Plan：官方说明两者凭据及入口独立、不能混用；Token Plan的Package Usage明确排除明显非编码场景的自动脚本和自建应用后端。**据此判断，本教育应用使用MiMo时应准备标准API，不能复用编程套餐凭据。** 尚未确认用户现有凭据属于哪类；本轮不读取密钥、登录账户或购买服务。[M2]、[M3]

## 4. OpenCode Go的明确缺口

Go官方提供API端点，不能写成“只有CLI、没有API”。但同页说明面向OpenCode及类似编码代理，客户端应发送典型编码代理流量、自有可识别User-Agent及每会话稳定的`x-opencode-session`。[G1]

当前教育任务不属于典型编码代理流量，现有原始HTTP请求也缺少上述两个头。**技术判断：当前包不能仅填Go地址／密钥就宣布适配完成。** 官方这段说明不等于明确禁止一切非编码调用；若仍希望应用使用Go，应先澄清此用途是否受支持，再决定是否需要客户端适配。只补请求头不足以解决用途问题，本轮不伪装编码流量或新增代理。

Console通用Inference参考提供Bearer鉴权，但通用地址与带`/go/`的套餐地址须分别识别；不自动切换到另一项服务。Go并非所有模型都走Chat Completions，不能将表中其他协议族一并判为兼容。[G1]、[G2]

OpenCode继续作为已有授权的编码实现工具，与把Go作为教育应用AI供应商是两件独立操作；本轮没有调用OpenCode或应用AI。

## 5. 下一步与保留边界

1. 优先准备DeepSeek官方API、MiMo标准API的准确模型和配置；尚待确定实际测试顺序、型号与标准API账户可用性。密钥只在后续应用内填写，不在聊天或文档发送。
2. [G17方案](desktop-d2-g17-acceptance-plan.md)一次固定一个服务／模型，三类样本串行检查；另一服务分别记录，不把三项候选自动扩为九次调用。实际范围在后续调用授权时明确。
3. 没有真实调用授权前，停在资料／配置准备。真实调用、模型列表／余额／连通探测API均未执行；没有填写配置、启动业务任务、修改代码、重建包或发布。当前G17仍为未执行。
4. 后续根据实际响应记录协议、最终内容、候选／采用／保存、Word／重启结果；文档兼容不代替账户可达性、供应商处理行为或教师质量验收。失败／结果不明依原方案停止，不自动收费纠错。

## 6. 官方来源

均为2026-10-21读取的公开文档；接口、型号和套餐说明以后可能更新，执行前针对最终配置复核变更，不以第三方教程或模型名称推定能力。

- [D1：DeepSeek首次调用／当前地址与型号](https://api-docs.deepseek.com/)
- [D2：DeepSeek Chat Completions参考](https://api-docs.deepseek.com/api/create-chat-completion/)
- [M1：MiMo OpenAI Chat Completions参考](https://mimo.mi.com/docs/en-US/api/chat/openai-api)（页面更新2026-10-20）
- [M2：MiMo API接入／Bearer与凭据区分](https://mimo.mi.com/docs/en-US/quick-start/faq/api-integration)
- [M3：MiMo Token Plan／Package Usage](https://mimo.mi.com/docs/en-US/tokenplan/Token%20Plan/subscription)（页面更新2026-10-21）
- [G1：OpenCode Go／用途、客户端要求与Endpoints](https://opencode.ai/v2/docs/console/go/)
- [G2：OpenCode Console Inference／鉴权及协议族](https://opencode.ai/v2/docs/console/api/inference/)

[D1]: https://api-docs.deepseek.com/
[D2]: https://api-docs.deepseek.com/api/create-chat-completion/
[M1]: https://mimo.mi.com/docs/en-US/api/chat/openai-api
[M2]: https://mimo.mi.com/docs/en-US/quick-start/faq/api-integration
[M3]: https://mimo.mi.com/docs/en-US/tokenplan/Token%20Plan/subscription
[G1]: https://opencode.ai/v2/docs/console/go/
[G2]: https://opencode.ai/v2/docs/console/api/inference/

## 7. 2026-10-22流式配置复核

本次只读取官方公开网页，未访问供应商推理、连通、模型列表、余额API或账户。依据当前HEAD `3e1870036c5bda257e41fceaedd489968c2846a4`的`backend/app/local/ai_transport.py`及流式[独立核查§11](desktop-d2-streaming-review.md#11-最终交付限定合成工程核查通过)。不再把§1的`stream:false`当当前行为。

### 7.1 准确配置与建议顺序

| 顺序／服务 | API前缀 → 最终POST地址 | 建议模型ID | 标准凭据／鉴权 | 状态 |
| --- | --- | --- | --- | --- |
| 1 DeepSeek官方 | `https://api.deepseek.com` → `https://api.deepseek.com/chat/completions` | `deepseek-flash` | DeepSeek开放平台API Key，`Authorization: Bearer` | 官方文档支持；未写入应用、未发请求，待用户确认 |
| 2 MiMo标准 | `https://api.xiaomimimo.com/v1` → `https://api.xiaomimimo.com/v1/chat/completions` | `mimo-v2.6-flash` | MiMo标准按量API Key，`Authorization: Bearer`；官方区分标准`sk-…`与Token Plan `tp-…`，不能混用 | 官方文档支持；未写入应用、未发请求，待用户确认 |

DeepSeek官方明确要求使用`deepseek-flash`，核对日由DeepSeek-V4.1-Flash-1017提供服务；这是API ID与当日服务版本的对应关系，不保证未来别名固定，也不是OpenCode的`opencode-go/deepseek-v4.1-flash`配置。MiMo模型页将`mimo-v2.6-flash`列为办公场景选项，适合用现有三类短材料开始验收。**先DeepSeek建立完整闭环记录，再用相同起始材料测MiMo**是执行建议，不是速度／质量实测排名；没有明确首选缺口，本次不增加其他型号比较。[D1]、[M4]

### 7.2 文档字段与当前包的对应关系

| 核对项 | DeepSeek官方文档 | MiMo标准API文档 | 本地已核查／真实未验 |
| --- | --- | --- | --- |
| 文本最小请求 | `model`、system／user字符串`messages`，`stream:true`；其余相关控制可选 [D2] | Chat参考列出首选模型，支持system／user文本及`stream:true` [M1] | `build_request` 325–336行只序列化这三项，默认stream=True；不依赖SDK或私有字段 |
| Bearer | 首次调用示例为Bearer [D1] | Chat参考及API Integration明确允许Bearer [M1]、[M2] | `_http_request_bytes` 339–351行使用Bearer、JSON POST；未读取／填写任何真实密钥 |
| 默认思考 | enabled，默认effort high [D3] | 所列V2.6模型默认enabled [M1]、[M5] | 不发thinking／reasoning_effort，沿用服务默认；收到真实reasoning前仅显示等待，不承诺立即到达 |
| SSE内容 | `delta.reasoning_content`与`delta.content` [D3] | 同样定义两个delta字段；指南先思考后正文 [M1]、[M5] | 当前解析器705–708、814–829行分离两者，null不作正文；思考仅展示，最终content才进入严格JSON校验 |
| 完成及usage | 正常`finish_reason=stop`；末终态choice携usage，之后`data: [DONE]`；文档说明不单发usage-only帧 [D2] | Chat参考定义stop；深度思考示例（示例模型为Pro）展示stop后可有`choices:[]`的usage-only帧，再`data: [DONE]` [M1]、[M5] | 当前746–786行接受usage-only对象，924–947行要求正常stop及最终JSON；已有包工程结论见§11。本次没有用Pro示例冒充Flash实际响应，未运行新的真实或合成推理 |
| 最终任务结果 | 可选JSON模式；本请求未启用 [D2] | 可选结构化输出；本请求未启用 [M1] | 仅靠提示词要求JSON，再严格解析及任务schema校验；文档不保证每次生成完整业务JSON、能在120秒内完成或教学质量合适 |

DeepSeek无tools时不要求把思考回传；MiMo指南中思考回传的要求针对含历史工具调用的多轮场景。本应用当前是独立的system／user文本任务，不发tools或历史工具消息，不因此添加思考上下文或工具协议。[D3]、[M5]

两家公开文档均未显示当前最小请求必须增加SDK、thinking、response_format、stream_options或输出token参数的缺口，因此**本次不安排代码／参数修改或重建包**。这是文档与本地实现的对应核对，不能证明账户有权使用首选模型、真实服务遵守所有字段、网络时延、真实usage或最终业务质量。出现具体错误按G17停止规则保留证据，不自动换协议／型号／重发。

结构核查按codebase-memory执行：项目索引generation `2026-10-21T22:31:56Z`可读，查到`build_runtime`／`run_interactive`；`desktop/d1_main.py`与`backend/app/local/ai_transport.py`覆盖结果均为no_recorded_issue但freshness为metadata_changed，已限定直接读源码核对相关行，没有重建索引或扩大到全仓审计。

### 7.3 本地准备及剩余事实

完整182文件包身份已核对；报告`80f15a68…`指排序相对路径→文件哈希映射摘要，不是原始JSON文件哈希，准确计算口径见[G17方案§3.1](desktop-d2-g17-acceptance-plan.md#31-2026-10-22已完成的本机证据)。DeepSeek全新独立库已初始化，三类bundle契约／默认指导均1；Windows自动化在首次表单恢复焦点时遇`GetCursorPos (0x80070005)`，正常表单提交／保存未完成。MiMo仅建立独立目录。详细根路径、人工补齐步骤、原文与对照见[G17方案§3–4](desktop-d2-g17-acceptance-plan.md#3-实际执行前的就绪表)。不把本地初始化写成材料已保存、连通或G17通过。

| 证据层 | 2026-10-22结果 |
| --- | --- |
| 官方文档 | 两家首选ID、前缀／最终路径、标准凭据Bearer、请求子集、思考增量及正常完成文档已复核 |
| 本地 | 包182/182、EXE／路径映射hash吻合；源码请求／流式形状已对应核对；DeepSeek库初始化，正常材料保存未完成，MiMo尚未启动 |
| DeepSeek真实A／B／C | **未执行**；无request ID／模型返回／耗时／usage／候选记录 |
| MiMo真实A／B／C | **未执行**；无request ID／模型返回／耗时／usage／候选记录 |

下一轮建议两家各3次业务触发、合计6次，逐家按A拆分→B适龄→C其他活动串行；数量是待确认验收范围，不是预算／配额或6次HTTP保证。型号／顺序待用户确认，先补正常表单并读回，再由用户在应用内填钥且另行允许真实调用。原10秒连接／120秒尝试／请求响应各1MiB工程保护和不明请求不自动重发保持。**本轮实际应用AI调用0次、供应商探测API 0次，未发布；不设计预算。**

### 7.4 本次官方来源（查阅2026-10-22）

- [D1：DeepSeek首次调用／正式模型ID与当日服务版本](https://api-docs.deepseek.com/)
- [D2：DeepSeek Chat Completions／SSE终态和usage](https://api-docs.deepseek.com/api/create-chat-completion/)
- [D3：DeepSeek默认思考与流式字段](https://api-docs.deepseek.com/guides/thinking_mode/)
- [M1：MiMo Chat Completions／模型、请求、流式delta及stop](https://mimo.mi.com/docs/en-US/api/chat/openai-api)
- [M2：MiMo标准API Key及Bearer鉴权](https://mimo.mi.com/docs/en-US/quick-start/faq/api-integration)
- [M4：MiMo当前模型与场景选型](https://mimo.mi.com/docs/en-US/quick-start/summary/model)（页标更新2026-10-21）
- [M5：MiMo深度思考／默认行为及SSE结束示例](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/text-generation/deep-thinking)；此前历史链接的`other/deep-thinking`本次读取无正文，改由官方导航进入此页，不将旧空页当本次证据。

[D3]: https://api-docs.deepseek.com/guides/thinking_mode/
[M4]: https://mimo.mi.com/docs/en-US/quick-start/summary/model
[M5]: https://mimo.mi.com/docs/en-US/quick-start/usage-guide/text-generation/deep-thinking

### 7.5 同日后续用户确认

用户已确认按上述型号和顺序执行：先DeepSeek官方`deepseek-flash`，再MiMo标准`mimo-v2.6-flash`；本节前面的“待用户确认”保留为资料核对当时的状态，由本条更新。用户同时明确密钥以后仅在应用内填写，暂不调用真实AI或发布。各3次／共6次业务触发仍是待真实调用授权的建议范围。正常表单补齐步骤已细化于G17方案§3.2；尚未收到用户已保存／读回的结果，不改记已就绪。

### 7.6 同日电脑控制恢复与离线材料完成

后续用户要求自动控制电脑完成，并授权失败时查因与恢复控制。Codex通过既有computer-use正常表单完成两家独立根的虚构档案、完整原文、固定游戏配置和两份保留对照，正常保存／重新打开读回均通过；两家内容v2、游戏修订#2／全局配置v2、三类个人指导r1／契约v1／默认r1，起点材料去生成ID后完全一致。DeepSeek另完成正常关闭后的同根冷重启读回，MiMo正常关闭。详细ID、根路径、hash及控制故障的判定见[G17方案§3.3](desktop-d2-g17-acceptance-plan.md#33-电脑控制恢复后两家离线材料已就绪)。§7.3和§7.5的未完成状态保留为当时事实，由本条更新。

本次控制恢复没有修改应用实现、Windows安全／权限或安装工具；此前拒绝访问未再现，根因未证实。滚动后索引几何与截图不一致时，用最新截图ID对应坐标完成保存，不据此宣称应用白屏或原控制故障已永久修复。两家只读核对配置版本／凭据／AI输入／任务／执行／attempt／候选均0；各有2条空候选引用的手工内容provenance，不算外部请求。当前离线材料已就绪，密钥以后应用内填写，**真实调用0次、G17仍未执行、未发布**。

### 7.7 同日授权后首个真实样本

用户先在DeepSeek专用应用保存配置／密钥，随后另行明确“允许，从现在开始允许调用真实AI进行验收”。Codex按已确认范围，通过普通UI发起DeepSeek A拆分一次：1 execution／1 attempt、HTTP 200、succeeded；返回模型deepseek-flash、duration_ms=3500，usage prompt=683／completion=312／total=995，provider request ID不可得。当前包流式解析、严格JSON与拆分schema通过；六字段与原文对应段落逐字相同。没有更换模型、探测API或重发。

候选成功后computer-use点击／激活超时；重新选择窗口及重建会话后截图仍报CreateForMonitor 0x80070057。应用PID5964仍响应、会话2 Active，控制根因未证实；未改权限或强杀。尚未预览编辑／采用／保存，正文仍v2，B／C及MiMo未发起，MiMo仍缺配置／密钥。等待恢复可见桌面后接续**现有A候选**，不重发；详细证据和未验边界见[G17结果](desktop-d2-g17-result.md)。这只证明首个真实拆分样本返回成功，不是G17／G18或所有供应商兼容通过；未发布。

### 7.8 同日桌面恢复后的DeepSeek闭环及MiMo接续

用户确认桌面恢复可见后，Codex恢复窗口截图／输入，直接采用已有A候选，没有重发A。B目标小班、C目标恢复计划中班分别一次真实成功，三任务／execution／attempt／candidate各3，均HTTP 200及deepseek-flash；实际耗时3500／5485／17954ms、usage分别683/312/995、381/510/891、1567/3423/4990（prompt/completion/total），provider request ID均不可得。候选比较／采用保存至v3／v4／v5；原始拆分基准、原文、未选板块及中班表头按预期保持。DeepSeek当前三类真实请求子集及本地闭环工程核对通过，教师教育适用性仍待评阅，不推及所有输入／未来服务表现。

正常退出／冷重启及再次导出未新增任务或attempt，两份Word所有字节相同，实际Word显示2页；准确ID、hash、流式观察及未捕获阶段见[G17结果§2.3–2.5](desktop-d2-g17-result.md#23-可见桌面恢复后a采用及bc闭环)。没有代码／参数修改、重建包或预算设计；未发布。

MiMo独立根已打开并通过普通UI预填`https://api.xiaomimimo.com/v1`／`mimo-v2.6-flash`，等待用户应用内填标准密钥并保存，尚未访问推理或探测API。执行前本次再次读取[官方Chat Completions参考](https://mimo.mi.com/docs/en-US/api/chat/openai-api)，仍列上述地址／型号、Bearer选项、stream与默认thinking；原模型选型页这次工具不可访问，不声称重新核对该页。MiMo真实兼容及完整G17／G18仍待验。

### 7.9 用户要求先比较标准API性价比

用户最新要求先比较，若MiMo无性价比优势则不测试，MiMo据此保持未执行。2026-10-22已读取双方官方人民币实时API价：MiMo Flash输出2元／百万tokens，DeepSeek Flash闲时4元、高峰8元；DeepSeek官方也已支持图像理解。单价较低不能代替本项目真实质量与总用量比较，当前应用仍只发文本；不新增多模态调用、代码或预算设计。详细官方来源、同用量算术示例及Codex建议先收口DeepSeek教师评阅／暂缓MiMo见[G17结果§2.7](desktop-d2-g17-result.md#27-用户最新要求先比较标准api性价比)。建议未冒充用户已取消或MiMo质量更差，原独立材料保留；没有新增供应商请求或发布。

### 7.10 MiMo本轮不测，DeepSeek终验工程证据齐备

用户已明确采纳建议：“MiMo本轮不测，继续完成DeepSeek的G17剩余验收，暂不发布”。据此只收口DeepSeek官方deepseek-flash，MiMo0调用且不记失败／通过、不作为本轮缺项，不改变既有可配置OpenAI兼容产品方向。只读终验14项全true，配置／模型／版本、三类闭环、来源与v5及Word身份齐备；DeepSeek实际兼容工程核查通过，方案要求的教师质量意见仍待回。完整矩阵及评阅材料见[G17结果§5／§4](desktop-d2-g17-result.md#5-deepseek-g17终验矩阵与剩余反馈)。没有新增供应商请求、实现／构建或发布。

### 7.11 教师反馈：内容整改，Word本样本正常

用户随后指出内容缺少换行、缺少1.2.3列表，晨间活动应均为户外、不含区域或室内；另确认本次Word“两页均正常”。因此内容质量未通过，不能以§7.10技术结果收口完整G17；本文件不把提示词质量问题冒充供应商协议不兼容。新产品规则、定点修改范围及实际整改状态见[G17结果§5–6](desktop-d2-g17-result.md#5-deepseek-g17终验矩阵与剩余反馈)。MiMo本轮不测、旧证据保留；整改阶段不重发应用真实AI或发布。

### 7.12 修订指导离线就绪，真实质量尚未复验

三项反馈已由原OpenCode落实到默认r2及任务指令，冻结r1／schema和个人指导保护保持，Codex限定离线核查完成。最终content-r03完整包与50项归档同源；整包首轮129/142、同包W5定点复跑33/33，首次窗口波动保留、原因未确认，不称单轮全通过或已修复。准确证据及包身份见[G17结果§6.4](desktop-d2-g17-result.md#64-最终r03定点整改限定离线工程核查完成)。没有新增DeepSeek或MiMo真实请求，指导合成证据不能证明模型已遵循；原方案质量问题停止规则保持，新轮次待用户决定，不发布。
