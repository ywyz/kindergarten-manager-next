# WSL 与 Windows 产品验收能力报告

日期：2026-10-01。范围：更新过时的项目状态文档，核查 WSL 内 OpenCode 的 Windows／Office 版本采集与桌面验收能力，调整 I5 片 4 提示词。没有安装依赖、启动产品服务、连接数据库、修改业务代码、提交或推送 Git；没有执行浏览器下载或 Word 逐页验收。

结论：继续使用 WSL2 内的 OpenCode 做版本采集、项目运行、自动测试和业务修复。无需为读取 Windows／Office 版本另装 Windows 版 OpenCode。真正的缺口是桌面 GUI 操作与观察；优先由人工完成 Windows 浏览器与 Word 验收，已有且具备权限的桌面工具可协助。桌面工具不作为新增必需组件。新版提示词允许先完成独立自动检查与交接，再暂停缺少 GUI 能力的阶段，Word 完成门槛不降低。

## 本轮实际证据

| 项目 | 实测结果 | 证据边界 |
| --- | --- | --- |
| 仓库 | `main` / `3ad97dd`；本地 `origin/main` 同指向 | 未刷新远端；不是远端在线核验 |
| WSL | Ubuntu 26.04.1 LTS；内核 `6.18.33.2-microsoft-standard-WSL2` | 未采集 `wsl --version` 的发行组件版本 |
| Windows | `EditionID=Professional`；25H2；OS version `10.0.26200`；build `26200.9457` | CIM 与命名注册表属性；中文 Caption 编码异常，依据 EditionID 交叉确认 Pro |
| Office | Inventory `OfficePackageVersion=16.0.20326.20158`；`OfficeProductReleaseIds=O365HomePremRetail`；Configuration `Platform=x64` | 安装信息；不证明激活状态或 Word 可交互运行 |
| Word | WINWORD.EXE FileVersion／ProductVersion 均为 `16.0.20326.20158` | 已核验文件版本；没有打开 Word；“关于 Word”的界面显示待确认 |
| 更新渠道 | UpdateChannel 与 CDNBaseUrl 的 GUID 均为 `492350f6-3a01-4f97-b9c0-c7c6ddf67d60` | 对应 Current Channel；记录的是配置值，GUI 渠道显示仍待核对 |
| 命令 | WSL 可找到 `powershell.exe`、`wsl.exe`、`opencode` | 未核验 OpenCode 的实际版本、权限配置或 GUI 插件 |
| 项目依赖 | `backend/.venv` 与 `frontend/node_modules` 缺失 | 本轮未恢复，因此没有复跑历史测试 |
| 模板 | 日模板 `99008f92ae42cc87da7e42e84009ffcd8bbefdf43602f09a59ae4027e5ddc9bd`；周模板 `24ccaa9e557522c40a653643381e31f319ea6ae5e9f3e30e9dfa41da21986aed` | 与受控资产基线相同；不证明版式 |

Windows 查询首次在 Agent 沙箱内返回 WSL vsock socket 错误；请求并获得该只读命令权限后查询成功。没有修改 WSL、Windows、注册表或全局配置，没有读取账户、许可证或设备唯一标识。不能把首次沙箱阻断解释成 OpenCode 或 WSL 无法读取 Windows 信息；OpenCode 的实际权限需执行时另行确认。

Microsoft 明确支持从 WSL 执行 Windows `.exe` 工具，因此 PowerShell 可以作为只读版本采集桥梁。[WSL 互操作官方说明](https://learn.microsoft.com/en-us/windows/wsl/filesystems)

Office 安装版本使用 Click-to-Run Inventory 的 `OfficePackageVersion`，产品标识使用 `OfficeProductReleaseIds`；不使用 `VersionToReport` 作为安装版本权威。[Microsoft 安装版本检测指导](https://learn.microsoft.com/en-us/microsoft-365-apps/updates/microsoft-guidance-on-office-build-install)

渠道 GUID 映射依据 Microsoft 的更新渠道表；配置值不能替代本轮 Word 界面版本采集。[Microsoft 更新渠道表](https://learn.microsoft.com/en-ie/intune/device-configuration/settings-catalog/update-office)

## OpenCode 与桌面端如何分工

| 工作 | WSL OpenCode | Windows 原生 OpenCode | ChatGPT／Codex 桌面端 | 推荐承担者 |
| --- | --- | --- | --- | --- |
| Windows／Office 安装版本 | 可经 PowerShell 互操作查询，受权限限制 | 可通过 Windows shell 查询 | 可通过 Windows 命令查询 | 当前 WSL OpenCode |
| MySQL、迁移、API、Vite、测试 | 当前项目执行环境 | 可调用 WSL，但会增加环境切换 | 可使用 WSL／Windows 命令能力 | 当前 WSL OpenCode |
| 浏览器页面点击及真实下载 | 需实际 GUI／浏览器工具，shell 本身不证明具备 | 安装 Windows 版本本身不证明具备 | 有可用浏览器工具时可协助，须核验真实下载 | 人工或已有可用工具 |
| Word 打开与全部页面观察 | 需桌面观察工具或人工交接 | 安装 Windows 版本本身不证明具备 | 有可用 Computer Use 时可协助 | 人工优先，可用桌面工具辅助 |
| 业务缺陷修复 | 保持唯一写入者 | 不另开第二个实现者 | 只协调、观察和反馈 | 当前 WSL OpenCode |

OpenCode 官方推荐 Windows 上使用 WSL；原生 Windows 或桌面外壳不是当前项目的必要切换。[OpenCode Windows 指导](https://opencode.ai/docs/windows-wsl/)

OpenAI 当前官方文档说明 Windows 桌面端可使用 Windows 原生 Agent 或 WSL2 Agent；命令环境与界面能力需要分别确认。[Windows 桌面端文档](https://learn.chatgpt.com/docs/windows/windows-app)

需要补充上次答复中的能力判断：官方已说明，在支持地区，ChatGPT Work 与 Codex 可通过 Computer Use 插件操作 Windows 桌面；Windows 上运行于前台活动桌面，需对应应用授权。这是产品支持事实，不代表本机、本账户或本会话已经具备该工具。普通聊天界面或仅有内置浏览器不能据此认定可操作 Word。[Computer Use 官方说明](https://learn.chatgpt.com/docs/computer-use)

因此无需立即安装或迁移到 Windows 版 OpenCode，也无需把桌面版 Codex／ChatGPT 设为验收前提。若你已经有可用 Computer Use，可让它只承担 GUI 验收；若没有，人工操作 Word 是更直接的路径。本轮没有安装或启用插件，也没有扩大本项目允许使用的工具范围。

## 文档更新与提示词调整

已更新：

- `AGENTS.md`：阶段改为分片实施与产品验收，更新当前优先级；保留架构、权限与 MCP 审计约束，注明 OpenCode 唯一业务代码写入者。
- `README.md`：修正骨架计数页面、前端不调用 API、DATABASE_URL 仅用于迁移等过时描述；记录 WSL／Windows／Office 安装状态，区分旧工具版本与当前工具版本，新增报告及提示词入口。
- `architecture-v1-readiness.md`：新增当前行动和环境状态，修正过时开篇与“生成库尚未定案”描述；保留原有历史测试和授权记录。
- `word-export-implementation.md`、`word-template-validation.md`：补当前安装环境状态与人工验收证据边界，没有修改业务行为、模板资产或 Word 完成门槛。
- 2026-09-29 提示词：明确标为历史版本，指向新版，保留当日事实。

完整新版见 [I5 片 4 OpenCode 提示词](i5-slice4-opencode-prompt-2026-10-01.md)，保留 W1–W6 全矩阵、权限／409／审计／过期响应检查、隔离规则、修复范围、回归及清理要求。

调整的原因：旧提示词把“Agent 不能观察桌面”与“目标环境不存在”合并成整体停止条件，容易让已能执行的自动检查也停住。新版把版本采集、独立自动检查、GUI 验收拆开推进，并增加人工交接、文件哈希关联和操作者证据来源。只有实际 Windows 浏览器下载和 Word 全部页面证据齐全，才能完成片 4。

等待人工反馈时默认清理临时资源并保留可重建说明；用户明确要求保留时才记录用途和清理责任。不得为等待 GUI 而无期限运行容器或服务，也不能提前删除尚待验收的文件后声称已检查。

## 后续安排与本轮验证

下一步由 OpenCode 核对最新工作区，恢复锁定项目依赖，运行独立检查并准备人工浏览器／Word 验收。I5 完成后，建议编写 AI Service、提示词和持久任务实施规格草案，先列未决行为再决定实现，不自动部署。

codebase-mcp 与 codegraph 继续暂缓：当前缺口是 GUI 验收而非代码检索；名称还存在多个实现，未来应先明确仓库地址并审计，再评估单独试用。此判断是任务适配建议，不是已经完成 MCP 全面审计。

本轮仅做文档一致性、相对链接与差异检查，并进行了 Windows／Office 命名属性的只读采集。没有将历史单测、MySQL 集成或模板原型改写为本轮通过结果。用户原有 `.codex/config.toml` 和备份保持不动；架构、ADR、模块 Contract、业务代码与模板资产未修改。
