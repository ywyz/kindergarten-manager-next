# AI 1C 编码审阅与部署门槛（2026-10-04）

结论：**本轮审阅未通过，当前不能进入远程验收实例部署。** 12 条 typed API、三角色入口、动态字段和设置界面的基础范围成立，但组件存在初始化、保存基线、草稿回写和竞态缺陷，直接影响 C2／C4／C5／C6。先由 OpenCode 最小修复并经复审，再准备远程部署与桌面 C1–C7 验收。

依据：[1C 规格](../specs/ai-settings-ui-1c.md)、[编码交接](ai-slice1c-opencode-coding-prompt-2026-10-04.md)、[实现结果](ai-slice1c-implementation-result-2026-10-04.md)、[1B 收口](ai-slice1b-closeout-review-2026-10-04.md)。审阅实际未提交工作区，HEAD 为 `1647fc934d41b29a844a807d454031e66a2b45af`。保留全部既有修改；协调者未修改业务代码、读 .env／私密密钥、安装依赖、启动服务器、连接数据库、SSH／部署或 commit/push。

## 1. 必须修复的问题

### R1（P1）：配置卡首次不读取，生命周期和载入动作缺实现

位置：`frontend/src/components/ai/AiConfigCard.vue:39`、`:59`、`:153`。

配置 GET 只在非 immediate 的账号变化 watch 或“重新读取”按钮触发。进入设置时 trackedAccount 已等于当前账号，没有 mounted／setup 首次 load；baseline 始终 null，页面显示“正在读取配置”却没有请求。离线执行 setup 后 GET 调用计数为 **0**。这是常规入口缺陷，不应留到部署后验收发现。

同卡没有注册 onBeforeUnmount（离线 hook 计数 **0**），因此卸载不使 epoch 失效，也没有约定的密钥清空；defineExpose 的清理仅供 401 事件调用。`loadLatestIntoInputs` 只更新 baseline，不写 baseUrlInput/modelInput，点“载入最新配置”仍保持旧输入。复现旧地址／模型→点击载入最新后仍为旧值。

修复首次只读读取、卸载失效与密钥清理；载入最新与保留输入两动作必须有不同效果，明确处理未提交密钥，不回填遮罩或从服务端取明文。失败显示可重试状态，不能永久显示正在读取。

### R2（P1）：个人指导 409／后台刷新静默推进编辑基线

位置：`PromptGuidanceCard.vue:173`、`:188`、`:241`、`:350`。

`applyFreshDetail` 直接 `d.detail = fresh`，而 saveNormal 直接用该 detail.personal_revision。409 后仅 refreshDetail，无独立 latest 比较和用户选择；切回已有任务也 quiet refresh。草稿虽然保留，下一次保存已悄悄使用新 revision。复现：编辑基线 1、草稿 local；另一会话版本 2 remote；第一次保存 409 后，尚未选择任何新基线，detail.personal_revision 已为 **2**。

必须区分编辑时保存基线、草稿、latest 比较。GET 不推进 dirty 草稿的 expected；让用户看到本人最新文字及版本并明确选择载入或保留后采用新基线，再点击保存。不把“再次点击保存”本身当作隐式冲突确认。比较快照也不能在后台刷新时更换 target_default_revision 并沿用旧勾选。

### R3（P1）：接受／适配成功后旧编辑框被当成新草稿

位置：`PromptGuidanceCard.vue:308`、`:406`、`:564`、`:173`。

mergeWriteOut 只改 guidance_map／revision，未同步 normalDraft。接受前 old 已保存且草稿干净；接受默认 new-default 成功后，服务器基线变 new-default，编辑框仍 old。后续 refresh 的 dirty 判断拿新基线比较旧框，错误保护 old。离线复现最终为 **saved=new-default、draft=old、dirty=1**。用户再点保存会撤回刚接受的文字。适配成功后同名字段存在相同风险；若状态刷新失败，based 字段集合还可能继续停留在旧集合。

写成功必须按本次请求／响应更新编辑基线和已经提交的草稿，区分请求发出之后用户真正新增的修改。接受只改变选定字段，完整适配成功形成最新字段编辑面；刷新失败仍保留确实成功的结果，不制造旧文字反向提交。

### R4（P1）：epoch 使用与 loading 所有权不完整

位置：`AiConfigCard.vue:133`、`:141`、清除冲突 GET；`AdminPromptDefaultsCard.vue:79`；`PromptGuidanceCard.vue:241`、各写方法 finally。

- 配置冲突 GET 用 `guard.alive(guard.token())`，永远检查当前 token 对自己，不是 await 前 token。模拟 bump 失效后旧 GET 返回，仍将 version=9 写入 conflictLatest。
- 管理员 selectTask 的 catch 在检查 token **之前**清空 detail 并设置 detailError。模拟 A 请求晚失败、B 已成功显示，最后 B detail 被清为 null、error=true。
- 个人卡切换任务 bump 后，旧写 finally 不删除 busy，切回已有任务也不重置。模拟 A 写中→B→A，A 的 busy 永久为 true。detailLoading／refreshing 也有同类风险；管理员全局 saving 在切换后旧 finally 被跳过，可永久锁住新面板。
- 同一 epoch 的多个刷新／同任务请求没有请求序号，逆序返回仍会覆盖；关闭比较／适配没有使相关请求失效。配置 form submit 方法本身也没有 canSave／写锁防重入检查，禁用按钮不能覆盖 Enter 提交路径。

需要每个异步 await 使用捕获的所有者 token；所有状态写入在检查之后；切换时由新状态所有者重置相应 loading，不能让旧 finally 解锁新请求，也不能残留旧 busy。同资源请求用序号或等效机制保证最新意图生效。补验证旧 success／error／finally、A→B→A、面板关闭、退出／账号切换及重复提交。

### R5（P2）：适配 revision 冲突没有可用的恢复路径

位置：`PromptGuidanceCard.vue:504`、`:547`、`:608`。

普通 VERSION_CONFLICT 仅刷新 detail，adaptTarget.personalRevision 仍为旧值；再次 openAdapt 在契约相同时刻意保留旧 target。复现服务端已为 revision=2，两次适配提交 expected 都是 **[1,1]**，不断冲突。

契约变更路径虽更新 target，却自动推进 personalRevision；也应遵守 R2 的显式选择。target 所对应的完整字段集须与编辑面快照绑定，不能从后来刷新后的 detail 取另一套字段。409 后保留适配文字，呈现最新个人／契约目标，让用户明确重新选择基线；重复操作不得重发旧 target，不丢被新契约移除的未保存原文。普通编辑 dirty 时打开／提交适配也须先保存或明确放弃，避免以已保存原文替换正在编辑的文字。

### R6（P2）：管理员草稿丢失，等待响应时的新输入被覆盖

位置：`AdminPromptDefaultsCard.vue:63`、`:119`；设置页退出／组件卸载路径。

selectTask 无确认地清空 draft。复现 A 填 unsaved→B→A，A 变 old，草稿丢失；点击当前任务同样会重置。默认保存响应直接把 buildDraft(out) 全部铺到正在编辑的 draft，文本域未禁用。复现发送 submitted 后继续输入 newer-typing，响应到达将输入覆盖回 submitted。

任务切换保留本页每任务内存草稿或明确确认放弃；写成功仅清理本次已提交修改，保留之后新增文字，或在请求期间明确锁定编辑。配置和个人／管理员指导离开设置页时也需处理 dirty 文字：当前卸载清空草稿但没有放弃确认，不满足规格的离开约束。退出／401 清理密钥仍需立即完成，不持久化浏览器草稿。

### R7（P2）：未知错误仍显示原始异常 message

位置：`frontend/src/components/ai/ai-settings-shared.ts:138`（default 返回 err.message）。

现有脚本只测试未知 code **没有 message** 时的 fallback；实际未知 code／网络异常带 message 时原样显示。离线用合成 raw-error 标记证实 helper 返回原 message。这与 1C 固定安全提示要求及实现报告的“原始异常文本不进入提示”不一致。

未知错误、网络错误、非 JSON 返回使用固定 fallback；HTTP 401／403／422／503 按固定文案处理，不拼原 message/body。补带合成标记的实际 helper／组件错误路径，检查提示不含标记，不打印模拟密钥或载荷。

## 2. 独立验证与证据限度

- frontend `npm run typecheck`：通过，退出 0。
- `npm run build`：通过，退出 0；保留 >500kB chunk 警告，不要求本轮拆包。
- `node scripts/ai-settings-1c-check.mjs`：**29 项通过**。范围仅真实共享模块，不能证明组件的调用时机、版本恢复或过期请求行为。
- `git diff --check`：通过。
- 两次一次性离线 Node 检查：使用已安装 TypeScript transpileModule 编译实际 Vue 文件的 script setup，vm 执行；实际 Vue ref/reactive/computed/watch 在 effectScope 中运行，mock API 控制成功／409／延迟顺序，拦截 lifecycle 注册。没有 DOM、网络服务器、数据库或浏览器，不计作产品验收。

离线组件逻辑检查得到的实际值：首次配置 GET=0、卸载 hook=0；载入最新仍旧输入；个人 409 自动 revision=2；接受后 saved/new-default 与 draft/old 不同且 dirty=1；A→B→A 后 busy=true；管理员任务切换草稿消失、旧 A error 清空 B detail；适配 expected 重复 [1,1]；失效配置 GET 仍写 version=9；管理员响应覆盖 newer-typing；未知错误 raw message 原样显示。所有输入均合成，未使用真实凭证或业务材料。

这些结果证明前端逻辑缺陷，不把模拟当作服务端真实冲突或持久化证据。本轮不重跑已收口 1B 的 MySQL、不修改 backend，1A／1B 阶段判断保持有效。

## 3. 部署判断与后续

本次“检查是否能够部署测试服务端”按部署就绪审阅执行；当前存在明确代码阻塞，不进入 SSH／迁移／服务切换。先使用[最小补修交接](ai-slice1c-repair-opencode-prompt-2026-10-04.md)修复 R1–R7，补组件真实状态路径的离线验证，再复审。

复审通过后部署内容是 **1A＋1B 后端与 1C 前端的完整工作区源**，不能只升级 UI 或把当前 HEAD 当作完整实现。须形成实际文件与哈希清单，重建 frontend dist，按锁文件准备新增 cryptography 依赖，受控执行 `20261003_ai1a_config_prompts` 迁移并确认目标库 current，保护既有 I5 日周与导出数据。历史远程 I5 release 曾复用旧 .venv 和 dist，本次不能照搬该假设。

远程部署、目标库迁移、AI_MASTER_KEY／AI_MASTER_KEY_ID 准备与低权限服务账号、发布 v2／切换密钥夹具按 1C §7 单独授权后执行，密钥不写文档。部署后真实账号设置保存和手工日周／Word 冒烟与桌面 C1–C7 分别记录；health 或静态构建不能替代产品验收。继续使用既定远程 HTTPS 实例，不启动本机 WSL 验收服务器。
