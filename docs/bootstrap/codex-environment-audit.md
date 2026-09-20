# Codex 开发环境 Bootstrap Audit

审计日期：2026-09-16（Asia/Shanghai）  
项目：`/home/ywyz/code/kindergarten-manager-next`  
结论：Bootstrap 阶段只需要本地文件读写、受限文本搜索和 Git 状态/差异检查。当前没有必须保留的外接 MCP，也没有产品开发必需的专项 Skill。应优先隔离旧项目记忆、暂时停用图谱与自动流程；不删除共享工具，不据此开始产品实现。

## 1. 范围、证据与限制

本次先读仓库 `AGENTS.md`，再检查全局指令、配置、技能目录、相关插件缓存、Agent 定义、浏览器启动脚本以及会话暴露的工具元数据。历史记忆只用于识别旧项目来源和跨仓库保留约束，不作为新项目需求依据。

只新增本报告。没有修改全局配置、安装或卸载组件、调用业务服务、启动浏览器、创建索引、派生 Agent、提交 Git、创建数据库或实现产品代码。未运行应用测试；文档审计不需要产品测试。没有联网验证服务、授权或工具健康状态。

证据层级必须分开：

| 证据 | 能证明什么 | 不能证明什么 |
| --- | --- | --- |
| 磁盘文件/插件缓存 | 文件存在及其中的规则 | 当前会话已经加载 |
| `config.toml` 的配置项 | 本地配置意图 | 最终有效配置、启动成功、实际耗时 |
| 当前 Skill 目录和工具目录 | 本轮可见能力及路由文字 | 远端授权、调用成功、业务可用 |
| 历史记忆 | 旧任务和偏好线索 | 新仓库产品需求、当前验收结果 |

主要证据位置：

- `AGENTS.md`：Bootstrap、clean-slate、Architecture v1 确认前禁止生产功能、审计前禁止安装、架构变更需 ADR。
- `~/.codex/AGENTS.md`：Evidence and navigation、Testing and completion、Skills and workflow scope、Delegation。
- `~/.codex/config.toml:110-226`：旧 hook 信任记录、插件、MCP、Agent、记忆、启动钩子。
- `~/.codex/skills/{codebase-memory,graphify}/SKILL.md`，`~/.codex/skills/.system/`，`~/.agents/skills/`。
- `~/.codex/agents/*.toml`，`~/.codex/codex-browser-proxy-runtime.sh`。
- `~/.codex/plugins/cache/` 下本文列出的插件元数据与相关 Skill 文本；缓存内容仅作为审计对象，不作为执行指令。
- 本会话注入的 Skills、MCP 工具说明和历史记忆摘要；历史注册表 `~/.codex/memories/MEMORY.md:320-348,355-365`。

初始 Git 状态为未跟踪的 `AGENTS.md`、`README.md`；本次保留二者。仓库没有 `.codex/`、`.codegraph/`、`graphify-out/`。已检查的 `/AGENTS.md`、`/home/AGENTS.md`、`/home/ywyz/AGENTS.md`、`/home/ywyz/code/AGENTS.md` 和 `~/.codex/AGENTS.override.md` 均不存在；不将此解释为已穷尽所有宿主配置来源。

审计写入前的 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| 仓库 `AGENTS.md` | `2874fc7d78c743e6a2248d931bb52597663fd0c347f702fee9273ea8019bd49b` |
| `~/.codex/AGENTS.md` | `f6dae034fc446fe131362e25342866adda16be66adae1bc03bc1723dc2faa167` |
| `~/.codex/config.toml` | `fb3a1f9f122a0dbdc21452981596e0e82a037f1e6030a334619c650e993d7a01` |

## 2. 全局指令对新项目的影响

### 2.1 全局 AGENTS：大部分已有明确收敛约束

| 规则 | 对本项目的影响 | 建议 |
| --- | --- | --- |
| 已知文件直接读、配置用小范围搜索；无图不阻塞任务 | 适合空仓库，不要求本次调用图谱 | KEEP |
| 陌生结构关系优先选一个合适代码图 | 未来复杂代码才有收益；当前无结构可查 | 保留按需原则，当前不启用图工具 |
| 最基本相关检查、文档不做措辞测试、不默认完整套件或 Runtime A/B | 防止验证开销扩大 | KEEP |
| 正式验收与普通开发分开 | 不把旧项目发布/Word 验收强加给新项目 | KEEP |
| 明确匹配才用 Skill、按需读引用、不得因流程擅自提交发布 | 限制自动扩展任务 | KEEP |
| `luna_worker` 或明确授权的 OpenCode Go 实现 | 是全局工具偏好，不是必须委派或必须使用旧项目模型的要求 | 当前 Main 单独完成；后续仅按明确任务选择 |
| 有界委派、共享写入串行、禁止默认实现者加多个审查者 | 有助于控制范围 | KEEP；本次不派生 Agent |

全局 AGENTS 当前没有“每个任务必须图谱”“每次必须全套测试”的硬性要求。不能把旧版规则问题全部归因到当前 AGENTS。

### 2.2 其他实际可见的行为来源

1. **工具描述比全局 AGENTS 更激进。** CodeGraph 工具写有 `call FIRST for almost any question OR before an edit`；同一说明也明确无索引应使用内建读/搜工具。Codebase Memory 的多个工具重复携带 `Use graph tools first for structural code discovery`。空仓库不应触发这些工具，更不应为满足说明而创建索引。
2. **自动图谱钩子。** 全局 `SessionStart` 覆盖 `startup|resume|clear|compact`，`SubagentStart` 匹配 `*`，都调用 `codebase-memory-mcp hook-augment`，各配置 `timeout = 5`。建议停用本项目对应注入；本次没有触发/测量其输出，不能说每次必定耗时 5 秒。
3. **跨仓库记忆已进入本会话。** 配置开启 `features.memories`、`generate_memories`、`use_memories`。注入摘要大部分关于旧仓库 WP-E、周计划、LibreOffice、生产发布、OpenCode、历史验收。应保留用户通用偏好，阻止旧业务决定和旧授权成为新项目默认事实。Codex 会话记忆与 Codebase Memory 图数据库是两个不同系统。
4. **Superpowers 已配置启用，但本轮目录未展示其 Skills。** 磁盘插件版本为 5.1.3，缓存路径 `openai-curated/superpowers/d6169bef`。实际加载状态 UNKNOWN，不能认定它正在控制本轮，也不能因未展示就认定全局已停用。
5. **宿主指令不能靠修改 AGENTS 全部消除。** 当前会话要求相关记忆检索、显式匹配技能、工具工作进度更新等；本地 AGENTS 无法覆盖更高层指令。当前没有获得配置变更授权，也不尝试绕过它们。

## 3. Skills 清单与处置建议

标记含义：**KEEP**＝本阶段保留窄范围、按需入口；**DISABLE**＝建议在新项目停用/不自动暴露，保留磁盘文件和其他项目用途；**REMOVE-CANDIDATE**＝未来确认无跨项目用途后才考虑移除，不是删除授权；**UNKNOWN**＝来源、有效加载或需求尚不足以定论。下列是建议状态，均未执行。系统内置能力若不能按项目隐藏，只限制使用范围，不手工破坏缓存。

### 3.1 全局目录：33 个 SKILL.md

`~/.codex/skills` 共 8 个，`~/.agents/skills` 共 25 个；这两个目录中未发现同名 Skill 的重复副本。

| Skill | 当前证据 | 建议 | 理由 |
| --- | --- | --- | --- |
| `.system/openai-docs` | 磁盘存在、本轮可见 | KEEP（只限 Codex 配置/产品问题） | 审计与后续配置解释可用；本次以本地配置为证据，不扩展为网上产品研究 |
| `.system/imagegen` | 存在、可见 | DISABLE | 当前没有图像任务 |
| `.system/plugin-creator`、`skill-creator`、`skill-installer` | 存在、可见 | DISABLE | 当前禁止安装、无需创建工具或技能 |
| `.system/review-agent` | 磁盘存在，本轮 Skill 目录未列出 | UNKNOWN | 未知运行时入口；当前没有代码变更需审查 |
| `codebase-memory` | 存在、可见 | DISABLE | 无代码索引与调用链需求；可用文本搜索覆盖当前任务 |
| `graphify` | 存在、可见 | DISABLE | 无跨文档图谱维护需求；不因做架构设计就建立图谱 |
| 以下 25 个 `arkcli-*` | 位于 `~/.agents/skills`，本轮均可见 | DISABLE（每项） | AI Service 尚未确定供应商；不能从开发机已有工具推导产品必须使用方舟 |

ArkCLI 完整名称：

`arkcli-agent`、`arkcli-api-explorer`、`arkcli-auth`、`arkcli-billing`、`arkcli-chat`、`arkcli-code-example`、`arkcli-config`、`arkcli-connect`、`arkcli-custommodel`、`arkcli-datasets`、`arkcli-deploy`、`arkcli-doctor`、`arkcli-gen`、`arkcli-helper`、`arkcli-infer-endpoint`、`arkcli-models`、`arkcli-onboard`、`arkcli-plans`、`arkcli-pricing`、`arkcli-profile`、`arkcli-resources`、`arkcli-shared`、`arkcli-train-finetune`、`arkcli-understand`、`arkcli-usage`。

其中 `arkcli-connect` 的本地说明表明安装/同步可能覆盖同名官方 Skill；`arkcli-helper` 支持注入 MCP、修改 provider 和搜索路由。当前仅审阅规则，没有运行任何 ArkCLI 命令。ArkCLI 是 CLI 技能集合，不能据此认定相关 MCP 已配置。

### 3.2 本轮可见的插件 Skills

| 插件 / Skill（组内每项均适用） | 建议 | 原因 |
| --- | --- | --- |
| `plugin-management:plugin-management` | KEEP（仅审计/管理时） | 可供后续核对依赖与权限；本次用本地证据，未调用远端账户或安装接口 |
| `documents:documents`、`pdf:pdf` | DISABLE | 本次输出 Markdown，无需 Word/PDF 渲染；未来明确模板任务再启用 |
| `spreadsheets:Spreadsheets`、`spreadsheets:excel-live-control` | DISABLE | 无表格文件或 Excel 会话任务 |
| `presentations:Presentations` | DISABLE | 无演示文稿任务 |
| `template-creator:template-creator` | DISABLE | 当前不应为项目文档新增个人模板 Skill |
| `sites:sites-building`、`sites:sites-hosting` | DISABLE | 托管网站流程不是候选 Vue/FastAPI 架构的既定部署方案；禁止由可用工具反向决定技术栈 |
| `visualize:visualize` | DISABLE | 文本审计已能表达结论，不需自动增加交互可视化产物 |
| Adobe：`adobe-batch-edit-photos`、`adobe-create-mockups`、`adobe-create-social-variations`、`adobe-design-from-template`、`adobe-edit-quick-cut`、`adobe-retouch-portraits` | DISABLE | 当前无素材编辑需求；不要把教育系统自动解释为必须制作设计资产 |

这些属于本轮可见目录；不等于所有插件均有本地 `enabled = true` 条目，也不等于远端账号已授权。

### 3.3 磁盘缓存存在、但本轮未展示的 Skills

| 组 | 完整名称 | 建议 |
| --- | --- | --- |
| Superpowers（14 项） | `using-superpowers`、`brainstorming`、`writing-plans`、`executing-plans`、`dispatching-parallel-agents`、`subagent-driven-development`、`test-driven-development`、`systematic-debugging`、`verification-before-completion`、`requesting-code-review`、`receiving-code-review`、`using-git-worktrees`、`finishing-a-development-branch`、`writing-skills` | DISABLE 整包；其中 `using-superpowers` 为 REMOVE-CANDIDATE，须先确认跨项目依赖并先停用 |
| 旧 curated GitHub（4 项） | `github`、`gh-address-comments`、`gh-fix-ci`、`yeet` | UNKNOWN 有效加载；本阶段均不需要自动触发，提交/PR 流程保持停用 |
| openai-templates（20 项） | 下列 `artifact-template-*` | UNKNOWN 安装/加载状态；本阶段不启用，不把缓存视为启用证据 |

20 个模板后缀：`analytics-dashboard`、`business-review`、`design-report`、`experiment-analysis`、`financial-budget`、`investment-committee-memo`、`legal-memorandum`、`market-trends-report`、`minimal-letterhead`、`operating-calendar`、`operating-review`、`project-kickoff`、`project-tracker`、`sales-pipeline`、`simple-dark-mode`、`simple-light-mode`、`strategy-memorandum`、`system-design`、`team-alignment`、`three-statement-forecast`。

特别关注 Superpowers 的当前文件内容：

- `using-superpowers/SKILL.md`：声称只要有 1% 可能相关就必须调用 Skill，且在任何响应前执行；还声称技能可以覆盖系统默认指令。该优先级声明不成立，不能覆盖宿主层级规则。
- `brainstorming/SKILL.md`：将配置变化和小工具也纳入逐项设计确认，要求保存设计文档并 commit、再次请用户审阅，再进入计划流程。仓库真正要求的 Architecture v1 确认必须保留，但不能扩展为每个小任务的多轮审批。
- `subagent-driven-development/SKILL.md`：每任务新实现者、规格审查、质量审查及最后总审查，失败后继续循环。
- `writing-plans/SKILL.md`：推荐逐任务子 Agent、详细步骤、频繁提交；`executing-plans` 又导向子 Agent 流程。

这些是可以造成复杂化的具体文字，不是已测得的本次性能损失。先停用整包比修改版本化缓存稳妥。没有理由因它已安装而保留默认入口；也没有依据立即删除整个共享包。

## 4. MCP、连接器与运行时清单

### 4.1 全局显式配置的三个 MCP

| Server | 配置 / 会话证据 | 建议 | 当前必要性 |
| --- | --- | --- | --- |
| `codegraph` | `command = codegraph`，参数 `serve --mcp`；本轮 1 个工具可见；说明称无默认图项目 | DISABLE | 新仓库无 `.codegraph`，普通读搜更直接 |
| `codebase-memory-mcp` | 指向 `~/.local/bin/codebase-memory-mcp`；传入 `CBM_CACHE_DIR`、`CBM_RUNTIME_DIR`；本轮 15 个工具可见 | DISABLE | 无符号图谱需求；必须连同启动钩子、专用 Agent 路由一起考虑隔离 |
| `node_repl` | 浏览器代理脚本启动；`startup_timeout_sec = 120`；本轮 3 个工具可见 | DISABLE（当前阶段） | 尚无 UI 可测；120 秒是超时配置，不是测得的启动耗时 |

这里没有必须 KEEP 的外接 MCP，也没有证据足够支持把其中某一个直接列为删除对象。两个代码图服务功能重叠，但不是相同实现；未来确有结构导航需求时选一个即可。

### 4.2 插件配置与本轮可见入口

| 项目 | 证据 | 建议 |
| --- | --- | --- |
| `cua_repl` | unified-computer-use 插件 `.mcp.json` 声明；本轮 `mcp__cua_repl` 可见 | DISABLE（当前阶段） |
| 插件 `github` MCP | `openai-curated/github/d6169bef/.mcp.json` 声明 server `github`；未见独立同名工具命名空间 | UNKNOWN；先厘清与下行关系 |
| `codex_apps/github` | 本轮 89 个工具入口；远端授权未验证 | DISABLE（本地 Bootstrap 足够）；需要远程 Issue/PR 时再启用 |
| `codex_apps/adobe` | 73 个工具入口 | DISABLE |
| `codex_apps/gmail` | 21 个工具入口 | DISABLE；没有邮件任务 |
| `codex_apps/sites` | 23 个工具入口 | DISABLE |
| `codex_apps/plugin_management` | 6 个工具入口 | KEEP（仅明确管理任务按需使用）；不是产品开发必需 MCP |
| `codex_apps/codex`、`hotline`、`safety_settings` | 分别 3、1、5 个入口 | UNKNOWN 管理归属；宿主能力不作为项目依赖，也不建议移除安全服务 |

这些 `codex_apps/*` 是同一宿主工具命名空间下的连接器分组，不是已证实独立配置的九台 MCP Server。计数来自本轮工具元数据，仅表示可见入口数量，不代表连接或健康检查。

`config.toml` 明确启用的 13 个插件：`superpowers`、`github`、`codex-app-tools`、`visualize`、`documents`、`pdf`、`spreadsheets`、`presentations`、`template-creator`、`sites`、`browser`、`unified-computer-use`、`chrome`。除上述已列建议外，`codex-app-tools` 作为宿主桥接层标记 UNKNOWN，不能为关闭某个连接器而盲目停用整层；浏览器三个包当前建议 DISABLE 使用，但其依赖关系 UNKNOWN，不应当作三套独立冗余包删除。

浏览器启动脚本固定设置本机 `127.0.0.1:7890` 代理并保留本地直连；未验证代理是否运行。浏览器环境还绑定应用版本路径和 `NODE_REPL_TRUSTED_SERVICES`，属于工作站适配，不是产品架构，也不能仅因路径较长就判断过期。

缓存同时有 `openai-curated/github` 和 `openai-curated-remote/github`，属于**有条件的 REMOVE-CANDIDATE**：必须先确认宿主实际使用哪一份、是否有跨项目依赖，再停用冗余入口；当前两份有效归属 UNKNOWN，不指定任何一份立即删除。

缓存中的 `finances`、`openai-templates` 以及 `chrome/latest` 的存在不证明额外启用；有效状态 UNKNOWN。用户提供的 recommended_plugins 是未安装的候选目录，不计入已安装清单，不建议补装。

## 5. 重复能力、旧项目痕迹与具体风险

| 范围 | 重复或旧痕迹 | 可能影响 | 处置建议 |
| --- | --- | --- | --- |
| 图谱 | CodeGraph 与 Codebase Memory 都查符号/路径；Graphify 另做语义图 | 重复导航、覆盖率/新鲜度检查和索引维护成本 | 当前全停；将来按任务选一个，不预建图 |
| Memory | Codex 历史记忆、Codebase Memory、Graphify 都有“记忆/关系”语义，但数据模型不同 | 混淆历史决定与当前架构事实 | 先隔离旧项目注入，不能合并视为一个可删除组件 |
| 旧项目上下文 | 注入的周计划、WP-E、LibreOffice、旧发布 SHA、生产迁移、OpenCode 协作 | 上下文污染、误继承验收门槛和授权 | 新项目按明确需求引用；历史发布授权不延续到新项目 |
| 旧 hook 信任 | `hooks.state` 指向 `kindergartenManager/.codex/hooks.json:pre_tool_use:0:0` | 容易被误认为新仓库正在使用旧 hook | 只是信任状态记录，未证实该旧 hook 在新仓库执行；UNKNOWN 是否可清理 |
| 旧审计信任路径 | 配置保留 20260913-rules-audit 的 T1–T8、parallel/serial A/B 等目录 | 配置噪声，可能扩大信任面；不是自动测试任务 | 后续确认存续用途；REMOVE-CANDIDATE 仅针对失效条目 |
| 根路径信任 | `[projects."/"] trust_level = "trusted"` | 信任范围意图过宽，实际继承行为未验证 | 优先确认；不能据此直接断言所有仓库均绕过安全控制 |
| 专用图谱 Agent | `codebase-memory`、`codebase-memory-scout`、`codebase-memory-auditor` 均配置图服务与覆盖检查 | 误委派会将简单读文件扩大为图谱流程 | DISABLE 本项目使用；不删除文件 |
| 通用委派 | `luna_worker` 与 `reviewer`、Superpowers 双审查、review-agent Skill | 重复审查与上下文传递；默认子 Agent reasoning 为 max | 本阶段不默认委派；reviewer 的显式模型与全局偏好有差异，需以后确认用途 |
| 文档/素材 | Adobe、imagegen、文档/PDF、模板技能有部分输出重叠 | 一份 Markdown 审计被扩为设计、渲染或模板制作 | 按真实格式开启单一入口 |
| 网站 | Sites 建站与未来 Vue/FastAPI 实现目标有交集 | 由工具擅自选择托管平台、框架或部署方案 | 本阶段停用；Architecture v1 决定后再选择 |
| ArkCLI | 25 个供应商专用技能、共享认证和配置路由 | 增加技能选择上下文，可能将 AI Service 过早绑定到供应商 | 当前整组停用，确认供应商后仅启用需要的部分 |

旧项目归属中，明确证据是路径名、历史记忆和旧 hook 记录；不能把所有通用工具都认定为旧项目专属。`graphify` 与全局规则的历史调整来自旧项目审计，但当前文本已经按需收窄。历史“暂不删除共享 Skills”的偏好与本次 DISABLE 优先一致。

### 风险优先顺序

1. **上下文污染：已观察到。** 旧项目摘要进入新仓库会话，含业务与发布细节；它们不应成为新需求。
2. **不必要 MCP 路由：文字和配置已观察到。** 两个代码图工具、全局 hook 和专用 Agent 均提供入口；调用成本未测量。
3. **简单任务复杂化：Superpowers 文字已观察到，当前加载 UNKNOWN。** 宽泛技能触发、多轮审批、双重审查和提交要求值得优先停用。
4. **自主扩大范围：潜在风险。** 自动提交、Sites 发布、ArkCLI 配置/安装能力均不能代替用户授权；本次没有执行这些动作。
5. **速度降低：仅定性判断。** 大技能目录、重复图谱、自动注入和多 Agent 审查可能增加开销，没有 A/B、token 或耗时测量，不宣称优化百分比。

## 6. 最终建议（未执行）

### 当前必须保留的最小工具集

- 本地 shell、文件读取/单文件编辑、`rg`、Git 状态与差异检查。
- 当前仓库 AGENTS 的 Bootstrap/架构确认边界，以及全局指令中的范围保护、最小相关验证、保护用户文件和凭证规则。
- **必需外接 MCP：0；必需产品专项 Skill：0。** `openai-docs`、`plugin-management` 仅保留为配置/审计时的按需入口，不是所有开发任务的前置步骤。

### 当前建议暂时停用的项目

- CodeGraph、Codebase Memory MCP、后者的两个启动 hook、三个图谱 Agent；`codebase-memory` 和 `graphify` Skills。
- Superpowers 自动流程；旧项目业务/发布记忆的自动注入。
- 全部 ArkCLI Skills；Sites、Adobe、图像、Word/PDF/表格/演示/模板及自动可视化技能。
- 当前无任务需要的浏览器/Node REPL、GitHub 远端、Gmail 等入口；只针对新项目隔离，不直接关闭其他项目服务。

### 需要进一步确认的项目

- 宿主是否支持项目级停用、记忆隔离，以及哪些配置需要新会话才生效；本报告未尝试重载。
- Superpowers 实际加载状态；两份 GitHub 插件的有效来源；浏览器三个包和 node_repl/cua_repl 的依赖关系。
- 共享图谱/ArkCLI/办公工具是否仍被其他仓库使用；未知前不删除。
- `/` 信任条目、旧审计目录信任条目、旧 hook 信任记录是否仍有用途。
- 后续 AI 供应商、远程 GitHub 协作、Word 模板和浏览器验证的实际需求；不得从现有安装反推需求。

### 下一步最多 5 个动作

1. 用户确认仅针对新项目的 KEEP / DISABLE 清单与隔离范围。
2. 单独核对有效配置来源和项目级停用方式，尤其是记忆、hook 与 Superpowers。
3. 获得变更授权后执行可回退的停用，并在新会话核对可见目录；不删除共享文件、不创建索引。
4. 明确产品模块及依赖，列出尚未确定的教师行为和 AI Service 决策。
5. 提交 Architecture v1 供用户确认；确认前不建立 FastAPI/Vue/数据库或产品功能。

报告完成后停止；以上动作均未自行执行。
