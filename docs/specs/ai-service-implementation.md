# AI Service 实施规格

状态：2026-10-03规格收敛；管理员本人配置入口已获本轮用户确认。工程参数为本规格方案，不代表已实现、真实供应商兼容或代码／部署授权。依据：[AI Contract](../modules/ai-service.md)、[提示词Contract](../modules/prompts.md)、[ADR 0002](../adr/0002-background-tasks-and-versions.md)、[协同实施索引](ai-capabilities-implementation.md)。不改变Architecture v1。

## 1. 范围与身份

统一处理个人配置、受控调用、结构校验、失败分类和元信息；业务模块保存候选并决定采用，AI Service不写正式计划、不确认周计划。

教师与管理员均有“本人AI配置＋个人指导”入口；只可读写本人配置。管理员发起日计划AI使用管理员本人配置和提示词，不能借用创建教师密钥。待分配教师可以维护本人设置，发起计划任务仍要求有效班级和编辑权限。管理员日志查询不含完整密钥或他人的可编辑指导。

周自动调用使用当前负责人配置，允许离线产生用量；无有效负责人、停用／调班／接管待接受则暂停，不回退到管理员或前负责人密钥。手工保存、确认、已有版本导出不依赖AI配置。

## 2. 个人配置与版本

工程数据方案：`ai_config_versions`按account＋version追加，存协议标识、规范化base_url、model、加密secret、key_id、创建者／时间；`ai_config_heads`每账号唯一当前指针＋版本（复合FK约束归属）。配置修改用`expected_version`防丢失更新；历史行不原地改写，任务启动记录实际版本。

密钥字段输入仅写；GET只返回`has_secret`及固定遮罩，不返回尾码或可逆编码。PATCH未传secret保留旧密钥，传新非空值轮换，null／空串拒绝；清除密钥用明确DELETE操作并产生新“未配置”版本。首次有效配置必须有URL／model／secret，缺配置显示未就绪。

密钥采用成熟认证加密库（工程方案AES-GCM、随机nonce、绑定account／config version作AAD）；不自行写密码算法。当前`uv.lock`已通过`pymysql[rsa]`间接锁定`cryptography`，尚未在项目中声明为直接依赖；OpenCode实施前列出直接依赖声明及实际锁文件变更供对应实现授权核对，本轮不安装。应用解密材料与DB分开，部署时由受保护配置注入；不写仓库或业务表。启动不能解密时AI暂停，手工链路仍可用。

待执行任务启动时读取最新有效版本；已钉住且执行中的任务保留旧版本完成。清除或轮换配置不把旧请求换为新secret。仅保留有执行引用的旧加密secret；执行结束、无未决调用引用后允许清除旧secret而保留无密钥元信息。结果不明任务不会再自动使用旧secret；手动重试创建新执行并用当时最新有效版本。应用加密主密钥轮换须先验证双key_id解密与重加密回滚，不自动随个人配置操作轮换。

## 3. 最小兼容协议

工程方案固定`chat_completions_v1`适配器：用户填写带供应商API前缀的HTTPS base_url（可含`/v1`），规范化后仅追加`/chat/completions`，不重复追加`/v1`；禁止query、fragment、userinfo。使用Bearer认证、JSON POST，请求含model、system／user messages、`stream=false`；user内容包含序列化输入快照，系统协议与个人字段指导由提示词模块组装。

只接受非流式文本回复中的一个JSON对象，读取`choices[0].message.content`；不启用tools、浏览器搜索、附件、Responses API或供应商私有协议。不把OpenAI官方能力外推为所有兼容供应商均支持；最小协议供应商须实测。请求不默认要求`response_format`、temperature等可选参数，未来适配须在协议版本中明确。禁止SDK／HTTP库隐式重试。

参考为[OpenAI Chat API官方文档](https://developers.openai.com/api/reference/resources/chat)，本项目仅选取上述文本调用子集，不承诺通用OpenAI API覆盖。真实接入前记录供应商、完整endpoint形态和可用model，不在公开文档写真实key。

工程限额：连接10秒、整次调用120秒、响应正文最多1MiB、序列化请求最多1MiB。超过限额明确失败，不截断教案后偷偷生成；模型上下文限制由供应商错误明确显示。测试用固定响应不计作真实AI质量验收。

## 4. 公网HTTPS与网络校验

仅允许公网HTTPS／有效TLS验证；每次连接验证域名的全部A／AAAA，拒绝loopback、private、link-local、保留／非公网地址及IPv4映射IPv6绕过。实际连接必须使用已验证地址集合且保持原域名TLS SNI／证书验证，验证解析和连接不能各自重新解析造成DNS重绑定窗口。

首版工程方案拒绝全部HTTP重定向，不转发认证头；禁止自动跟随。DNS／网络故障不得降级放行；配置保存的校验不替代每次调用校验。显式受控出站，禁止继承未知环境代理形成绕过。实现需用网络夹具验证真实连接目标，不能只mock字符串检测就宣布防护完成。

## 5. 输入输出与调用接口

内部`invoke`输入：task_type、execution_id、operator_id、billing_account_id、config_version、prompt_contract_version／personal_revision、input_snapshot_ref／hash、output_schema_version。工作进程启动时钉住；网络调用不持有DB事务。无cookie依赖的自动任务凭有效负责人授权运行，不能伪造登录会话。

输出为校验后JSON候选＋调用元信息，或分类错误。任务字段结构由系统registry提供，`extra=forbid`、类型／必需字段／长度／枚举全部验证；JSON markdown围栏、自由文字、字段改名、未知来源id均拒绝，不自动调用“修复JSON”。空候选与缺项可按具体任务schema表达，不伪造足额结果。

业务校验是第二层：周游戏引用须在启动候选集合中，完整目标指导从该来源读取而不是信任模型重写；材料明确提取须有真实输入片段；生成的group／game／candidate id由服务端分配。网络成功不等于业务候选有效。

## 6. 分类与重试

| 类别 | 行为 |
| --- | --- |
| 未配置、地址阻止、模型／协议错误、401／403、明确额度不足 | 暂停对应任务，提示修改本人配置；不自动调用别人配置 |
| 可证明请求尚未发出的连接临时失败 | 有限重试，首次加最多2次，间隔5／30秒 |
| 供应商明确拒绝处理的临时限流 | 同上；安全可解析Retry-After不超过300秒；不能仅凭任意429认定无处理／无费用 |
| 发送后超时、连接中断、5xx且无“未处理”证明、进程在发送窗口崩溃 | `outcome_unknown`，不自动重发；显示可能重复计费，明确手动重试 |
| 响应可解析但字段／JSON／业务来源错误 | `output_invalid`终止此次执行，不自动纠错调用；保留原内容，手动重试是新执行 |
| 来源或权限已变化 | 不写最新候选，按持久任务规格过期／暂停处理 |

限额耗尽进入`failed`，无无限重试、无自动供应商切换。是否已发送必须由transport给出证据，无法确定一律按可能发送处理。重试状态与候选／确认状态分开。

## 7. API、界面与日志

拟定`GET/PATCH/DELETE /api/settings/ai-config`；PATCH携带expected_version，GET含版本、URL、model、has_secret、ready／reason。沿用现有同源会话／Origin防护；无权限403、旧版本409、参数422、AI运行不可用503。保存配置只做结构与安全验证，不偷偷进行付费测试；首个用户明确发起的AI任务验证真实连通性。

任务提交／状态／手动重试归持久任务API，不为AI Service增加直接写计划的接口。设置页显示配置未就绪及针对性处理；不提供全园密钥面板。secret只在用户本次输入状态短暂存在，提交后清空，不进入localStorage或错误遥测。

`ai_call_records`按execution＋attempt唯一关联任务、发起者／计费者、实际配置／提示词版本、状态、错误分类、耗时、可选供应商request_id／usage（无返回则null）；不推算费用。请求原文、完整回复、认证头不进入日志，错误文本白名单脱敏。任务成功与候选提交记录须真实一致。

沿用现有`operation_records`的target_type白名单：个人配置操作以account为目标，配置版本行保存该次operation_record_id以关联实际版本；不向现有表偷偷写`ai_config`等不被CHECK允许的新target_type。新增调用记录单独建表并同执行结果提交，不假定现有日志表已有payload／版本列。

## 8. 验证与完成条件

- 配置本人隔离、管理员本人调用、无借用密钥、版本冲突、旧密钥执行引用及清理；日志／API／前端无secret泄漏。
- HTTPS、IPv4／IPv6、DNS重绑定、重定向、TLS失败、代理绕过、响应限额；地址阻止确实不发送。
- 非流式成功、JSON／字段错误、额度／鉴权／限流、发前失败与发后不明；自动重试次数及“库不暗中重试”。
- 按[持久任务](persistent-ai-tasks-implementation.md)验证断电窗口、版本保护和候选落库；真实供应商用专用合成输入且由用户明确授权费用。

完成须分别记录实现、自动测试和实际供应商调用结果。真实地址／模型／凭证和付费操作授权属于接入资源，待实施验收提供，不能从现有私人浏览器页或旧系统提取。

## 9. 1B API 定稿接续（2026-10-04）

1A 已通过[阶段收口复审](../bootstrap/ai-slice1a-closeout-review-2026-10-04.md)。用户本轮要求定稿并交 OpenCode 实施 1B；设置接口的精确输入输出、本人权限、密钥省略／清除、错误脱敏与验证以[1B API／权限定稿](ai-settings-api-1b.md)为准，编码交接见[1B 提示词](../bootstrap/ai-slice1b-opencode-coding-prompt-2026-10-04.md)。此前 §7 拟定接口由该工程细化落实，不表示 API 已通过验证、真实调用或部署完成。
