# G17 候选服务官方文档兼容性核对

核对日期：2026-10-21。依据用户指令：预计使用DeepSeek、MiMo及OpenCode Go，先查官方文档，不设计预算限额，不实际调用真实AI或发布。

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
