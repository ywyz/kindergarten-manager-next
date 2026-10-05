# AI 1C 前端编码交接（2026-10-04）

用户要求提前实施 UI，之后调用桌面版验收。**1B 已通过[第二轮补修复审与阶段收口](ai-slice1b-closeout-review-2026-10-04.md)，本提示词的编码前提已满足，可以交 OpenCode 执行。** 本轮审阅未启动编码或部署。

```text
你是 kindergarten-manager-next 业务代码唯一写入者 OpenCode。协调者负责设计、文档和只读审阅。本轮实施 1C 设置前端，使桌面版之后可直接真实浏览器验收；不只交预检清单，不在编码阶段宣称产品验收通过。

先读 AGENTS.md、ARCHITECTURE.md、AI/提示词 Contract、ai-settings-api-1b.md、ai-settings-ui-1c.md、ai-slice1b-closeout-review-2026-10-04.md 与 ai-slice1b-repair2-result-2026-10-04.md。1B 最新复审已通过；旧审阅中的未通过状态保留为历史。若开工时有更新的阻塞结论，停止本片编码并报告，不自行收口或改 backend。此前 1B “禁止 1C”仅是旧授权边界，本提示词专门交接 1C。

记录开工 HEAD/status 与既有修改，全部保留，不回退/覆盖/清理/提交他人内容。不读 .env/现有私密密钥、不复制旧项目、不安装 Skill/MCP 或依赖、不另起编码代理。不得 SSH、部署、commit/push、启动 API/Vite/worker 服务器、连接数据库或供应商。

允许修改 frontend/src/api.ts、types.ts 的独立本片区域、views/SettingsView.vue，增加本片必要 components/composable/纯状态辅助文件及无新依赖的定向验证脚本；App.vue 仅必要设置导航衔接。不得写 backend/models/迁移/依赖锁/auth.ts业务规则/日周Word页面或扩展其他功能。正常组件命名自行决定，不重构整份 api/types，不引入新状态库/路由器/HTTP库。需要额外范围先报告协调者。

严格按 ai-settings-ui-1c.md 全文实施：
1. 教师、待分配、管理员均可维护本人配置和七任务指导；管理员系统默认独立编辑面，不能借用教师配置。沿用现有入口和账号密码功能。
2. typed API覆盖 12 条接口，与 1B DTO字段和固定错误码一致；写 JSON，DELETE 带 expected_version，initialize 发 {}，cookie沿用现有 request()，不手工设置 Origin，不把账号 version当设置版本。
3. 配置 PATCH完整元信息。空密钥输入只表示省略，不发送 null/空串/遮罩；新密钥原样发送。独立清除动作和版本保护；成功清空密钥输入，失败仅本页内存保留，卸载/退出/401清除，不持久化/日志/回显。ready只称本地可用，禁止连接成功、测试连接或AI调用按钮。
4. GET仅展示，显式初始化。字段由 API based/latest 集合驱动，七任务完整；不写死 v1字段。普通编辑可存旧based；默认比较、非空按字段接受、拒绝幂等且之后再接受；待适配禁止 accept/reject，完整适配独立编辑，保留原文字、新字段默认预填、移除原文可见，显式完成才提交当前完整集合。
5. 保存基线、本地草稿、最新比较数据分开。所有409保留输入，刷新不覆盖dirty/静默推进expected，不自动重发；用户明确选择最新基线后再次点击提交。接受/拒绝前处理未保存编辑；初始化/写成功后GET刷新失败不得误称写失败。任务切换、面板关闭、退出使旧success/error/finally失效，不能覆盖新任务内容或loading。dirty输入离开时保留页内草稿或明确放弃。
6. 管理员默认只改文字，expected_default_revision保护，不改系统字段/协议。所有文案用教师可理解的中文，提示词作为纯文本，不用v-html执行用户文字。

执行现有 npm run typecheck 和 npm run build（使用已安装环境，不安装依赖、不改锁）；定向验证密钥省略/原样新值/清除JSON、dirty基线和旧响应忽略等实际风险，使用现有运行机制不新增测试框架。没有浏览器工具或远程资源时如实列未验，不启动本机服务器替代。保留静态检查和产品验收区别。

新增 docs/bootstrap/ai-slice1c-implementation-result-2026-10-04.md：实际文件、12调用/DTO对应、入口/七任务字段、默认比较/拒绝/部分接受/完整适配、409输入保持及过期响应处理、密钥内存清理和无泄漏依据、typecheck/build与定向检查实际命令结果、C1–C7验证映射、偏离/未执行项。若实际跨日期，报告注明执行日期。不得含真实凭证/密钥/DSN。

交付后停止等待协调者只读复审。下一阶段是单独授权远程部署后，由桌面版按C1–C7真实验收；本轮不做浏览器产品验收、付费调用、transport/worker/候选/材料/完整W6，不自动开启部署或commit/push。
```
