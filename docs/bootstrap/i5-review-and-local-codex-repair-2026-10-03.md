# I5 报告审阅与本机 Codex 修复（2026-10-03）

用户要求审阅 Trae Work 报告，参考另一设备的浏览器修复记录修复本机，并尝试解决桌面版 Codex 无法进入 WSL 项目目录。本轮基线 `14662ef`，开始时工作区干净。仅修改审阅文档与仓库外本机 Codex 资源；未修改业务代码、模板、架构、远程实例或验收数据，未安装 Skill／MCP。

## 报告审阅

依据：[Trae Work 报告](i5-trae-work-validation-2026-10-02.md)、[当前验收口径](../specs/i5-validation-environment.md)、[W1–W6 标准](../specs/word-template-validation.md)。本机是 Windows 用户 `yw980` 的 WSL 环境，不是报告中的 Windows Server 用户 `admin`；不能直接核查另一设备上的完整下载目录和日志。浏览器与 Word 自动化结果为执行者报告，本轮未重复执行。

1. **P1：桌面视觉验收尚不完整。** 报告 R16 及“待执行”章节明确保留 GUI 项，W2 六页只记录首页／末页抽样。报告结尾认为完成所列两周文件步骤即可整体收口，且将其他文件视觉检查写成可选，范围不足。所有必需 W1–W6 案例的实际页面仍需核对；Word 自动化打开、页数、表格数及哈希不能替代裁字、遮挡、越界、缺字、分页和标红视觉检查。2026-10-03 用户答复没有补充报告，不能将缺项补写为通过。
2. **P2：证据追溯仍需逐文件清单。** 报告声明 28 份文件、15 个唯一哈希组，但正文未提供全部案例到文件名、字节、哈希、页数、截图／日志定位的对应表。现有仓库证据清单属于协调者单样例能力检查，不能替代 Trae 的全量证据。补录实际 Chrome 版本、已观察的 Protected View 状态及逐页证据；未出现 Protected View 可以如实记录，不要求所有文件必须出现黄色横幅。

R13 二会话、R14 范围竞态、R15 防重／生命周期及 R08 两周子例的记录与当前边界一致。模拟延迟和真实服务／审计分别声明，不能将旧响应未落盘误解成服务端没有成功审计。后台标签页 overlay 观察已由报告更正，没有依据新增业务修复。

当前结论：**报告所述浏览器／下载与 Word 自动化通过；W1–W6 必需逐页视觉验收待补齐，I5 片 4 未收口。**

## 本机浏览器代理补丁

参考 [另一设备修复记录](browser-repair-and-i5-capabilities-2026-10-02.md)。本机运行时同为 `81ea4d5168ddd0a3`，原启动器 SHA-256 与该记录原件一致。本机 `127.0.0.1:7890` 正在监听，Windows 运行时 Node 为 `v24.21.0`。

文件：

```text
C:\Users\yw980\AppData\Local\OpenAI\Codex\runtimes\cua_node\81ea4d5168ddd0a3\bin\node_modules\@oai\cua-repl\dist\lib\js\oai_js_cua_repl\src\launch.js
```

同目录备份为 `launch.js.bak-proxy-20261003`。在启动子进程的原 env 合并对象中新增 `NODE_USE_ENV_PROXY=1`、大小写 HTTP／HTTPS 代理变量（本机 7890）及大小写 NO_PROXY，保留已有绕过条目并添加 `localhost`、`127.0.0.1`、`::1`。未改 trusted services、扩展权限、浏览器 profile 或全局系统代理。

| 检查 | 实测 |
| --- | --- |
| 原 SHA-256 | `3e52a41f4da41d35be8cc3723fe97251711087a998c1ed7f2cfdf7e20b50fc2b` |
| 补丁 SHA-256 | `481dede49a4d70f714e4bf5eed4140b0891ea52ffa3b03fe4c6283a8a2396511` |
| 仅代理字段改动 | 反向移除新增字段后与备份逐字一致 |
| Windows Node 语法 | `--check` 通过 |
| Windows Node 代理请求 | 当前进程注入同样变量后 fetch example.com 返回 200 |
| 外置 Chrome／Edge 控制 | 本轮未验证：当前会话无浏览器工具，桌面日志记录 `reason=wsl-disabled` |

补丁须完整重启 Codex 才由新父进程加载；Node 网络成功不等于浏览器连接已修复。当前版本的 WSL 模式浏览器禁用与代理问题分别记录；该补丁不解除模式限制。更新可能覆盖运行时，代理端口变化需重新核对。仅当前文件哈希匹配补丁值时可恢复所列备份，不覆盖未知版本。

## WSL 项目目录修复尝试

本机桌面包 `OpenAI.Codex_26.930.2377.0_x64`，配置已有 `runCodexInWindowsSubsystemForLinux=true` 与 WSL 终端；Ubuntu 正在运行、WSL2。Windows `Test-Path` 对以下两路径均为 True：

```text
\\wsl$\Ubuntu\home\ywyz\code\kindergarten-manager-next
\\wsl.localhost\Ubuntu\home\ywyz\code\kindergarten-manager-next
```

桌面日志存在 Windows 路径被拼入 Linux 相对 cwd 的 watcher ENOENT，并多次记录安装包缺少 `resources\codex-resources\bwrap`。这些是已观察的环境缺陷，不足以单独证明项目创建失败的完整根因。原桌面本地项目列表和所用 app-server 项目列表均为空。

### 注册现有项目

核对桌面 app-server 实际使用 `CODEX_HOME=/mnt/c/Users/yw980/.codex`、`CODEX_SQLITE_HOME=/home/ywyz/.codex/sqlite`，使用同一桌面 Codex 二进制的自身 JSON Schema 与 `project/create` API 注册绝对 Linux 路径。未直接写 SQLite，没有迁移或复制项目，也没有修改既有会话 cwd。

- 元数据备份：`C:\Users\yw980\.codex\tmp\wsl-project-repair-20261003\state_5.before.sqlite`。该备份含私人应用状态，仅本机保留，不入库。
- 项目：`kindergarten-manager-next`，根目录 `/home/ywyz/code/kindergarten-manager-next`。
- 返回 ID：`01a0fd99-7d37-7be2-bd28-efe4b4e424db`。
- `project/read` 正确；第二个独立 app-server 进程 `project/list` 读回相同项目与根目录，持久化通过。
- Windows 经 `wsl.exe -d Ubuntu --cd ...` 执行 Git 返回正确根目录，读取 `AGENTS.md` 检查退出码 0。

重启后应用应重新载入项目列表；本轮未观察桌面项目点击、新会话创建或工具 cwd，不将 API 成功写成 GUI 问题已完全解决。回滚注册应使用同版 `project/delete` 删除该精确 ID，不能用整个旧数据库覆盖新会话。

### 补齐同版 bwrap

桌面 Codex 与现有 VS Code 扩展的 Linux Codex 版本均为 `0.159.0-alpha.12.1`，二进制 SHA-256 均为 `7465b9e51a12eaf965afcdd13c57ee95bc1ba2846152ff3143869d751ebfe45b`。从此匹配版本扩展复制其已有 bwrap 到桌面 Codex 的可写运行目录：

```text
来源：/home/ywyz/.vscode-server/extensions/openai.chatgpt-26.930.21537-linux-x64/bin/linux-x86_64/codex-resources/bwrap
目标：/mnt/c/Users/yw980/.codex/bin/wsl/3ac368078cf7546b/codex-resources/bwrap
```

目标原不存在；两份 bwrap SHA-256 均为 `77360cb751ccedc5971391444ac86a8a33c15b04d6b4a6fe45f5d25496e62c4c`。复制的辅助程序在只读根文件系统、独立 PID namespace 下执行 Git 并返回正确项目根目录。首次直接 `codex sandbox` 验证未成功：当前版要求命名权限 profile，而用户配置未提供 `[permissions]` 表；未为测试改写全局权限。直接 bwrap 检查通过不等于桌面全部沙箱路径通过。

未写入只读 WindowsApps 安装包。安装包源文件缺失仍可能在下次启动产生 relocation 警告；本次补齐可执行文件旁的辅助程序，不声称消除打包缺陷。更新可能切换运行目录。回滚只移除本轮新增且哈希匹配的目标 bwrap。

## 待完成复核

完整退出并重新启动桌面 Codex，打开已注册的 `kindergarten-manager-next`，确认新会话命令 cwd。若目录选择器仍失败，按 [官方 Windows 文档](https://learn.chatgpt.com/docs/windows/windows-app)使用上述 `\\wsl$` 路径；WSL agent 与终端分别配置。

本轮保留 WSL agent 设置；其浏览器禁用在日志中明确存在。需要 Windows 外置浏览器控制的会话应在 Windows agent 环境验证补丁，不能据 WSL 模式无浏览器工具断言代理补丁失败。未强制终止当前桌面应用或用户会话。

Trae 的余下视觉验收应覆盖 W1 普通／全空、W2 全六页、W3 合并分页、W4 六／七列及停课调休、W5 单周／两周和 W6 指定版本与材料映射的必需样例，记录文件哈希、实际页数和每页结论；日 31 份／周 8 份的边界文件按既有任务书复核。相同哈希可以复用同一视觉证据，不能用不同文件的结构自动化结果替代。
