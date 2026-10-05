# AI 1C 最小补修交接（2026-10-04）

依据：[1C 编码审阅](ai-slice1c-review-2026-10-04.md)。本轮修复 R1–R7，不重做 1C、不修改已收口 backend，不部署。

```text
你是 kindergarten-manager-next 业务代码唯一写入者 OpenCode。先读 AGENTS.md、ai-settings-ui-1c.md、ai-settings-api-1b.md、ai-slice1c-review-2026-10-04.md、原编码交接与实现报告。按审阅 R1–R7 最小修复，不增加产品行为、依赖或架构。既有历史报告保留。

记录 HEAD/status，保留全部工作区修改。允许修改本片三个 AI 卡片、ai-settings-shared.ts、必要的 SettingsView.vue 离开衔接及本片无新依赖定向验证脚本；必要的本片状态辅助文件允许新增。api.ts/types.ts 仅确有本片必要修正。不写 backend/auth.ts业务规则/日周Word页面/依赖锁/App.vue大范围改动。若退出处理需要超出范围的文件，先报告，不扩改。

不读 .env/私人密钥、不安装 Skill/MCP/依赖、不另起代理、不连接数据库或供应商、不启动 API/Vite/worker、不 SSH/部署/迁移/commit/push。

逐项按审阅全文修复：
R1 配置首次只读 GET、卸载失效+清密钥、载入最新真正更新元信息、保留输入动作独立；失败可重试。
R2 保存基线/本地草稿/latest 比较分离。GET与409不得推进 dirty expected，用户比较最新文字后明确选择新基线才允许再次提交。比较 target快照和勾选不能后台替换。
R3 接受/适配等成功回写本次提交的编辑状态，不能把旧框当dirty反向提交；保持未选字段及请求后真正新增修改；刷新失败仍承认本次成功，适配后字段正确。
R4 全部await验证捕获token（禁止alive(token())），先验证再改任何state。任务/面板/账号/卸载使旧success/error/finally失效；切换由新所有者清理旧loading/busy且不解锁新请求；同资源逆序返回要有请求所有权。所有写方法防重入，包括Enter路径。
R5 适配409显式比较/选择最新个人revision和契约快照，保留文字，不能重复旧target或静默rebase；完整字段集合绑定该目标；新增字段预填、移除原文可查。普通dirty指导先保存或明确放弃再适配。
R6 管理员每任务草稿保留或明确确认放弃，同任务再点也不能静默丢失。请求后新增文字保留或请求时锁编辑。离开设置时各卡片dirty草稿需保留或明确确认放弃，退出/401密钥立即清理，不加浏览器存储。
R7 未知/网络/非JSON错误用固定fallback，不返回原err.message；固定状态码提示覆盖，合成标记不进提示或日志。

不能只验证createEpochGuard/dirty helper后宣称组件通过。用现有Node/TypeScript/Vue环境对实际组件或组件真正调用的提取状态模块离线驱动，mock API仅用于前端模拟，写可重复的回归脚本，覆盖：首次读取；卸载与账号切换清密钥；冲突载入/保留的不同效果；个人/配置/管理员409不推进expected直到显式选择；接受成功无伪dirty、适配成功字段及刷新失败；A→B→A旧success/error/finally、无永久busy；同资源逆序、关闭面板、重复提交；适配revision/contract两类409恢复；管理员切换不丢草稿、写后新增输入；离开dirty确认；未知错误合成标记不泄漏。覆盖非法请求路径时不打印合成secret载荷。

执行 npm run typecheck、npm run build、原29项共享函数检查与新增状态回归、git diff --check；不新增框架、不启动浏览器服务器。真实浏览器C1–C7仍未执行，模拟证据明确标记。

新增 docs/bootstrap/ai-slice1c-repair-result-<实际日期>.md，列实际文件、R1–R7到具体函数/回归场景/命令与结果、草稿和版本状态表、生命周期处理、未执行项和偏离；纠正原报告未被组件代码支持的结论，不覆盖旧报告。交付后停止等待协调者复审，不自动部署或启动桌面验收。
```
