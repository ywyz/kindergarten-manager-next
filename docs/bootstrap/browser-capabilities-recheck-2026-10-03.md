# 外置浏览器能力复测（2026-10-03）

状态：**本机外置 Edge 已恢复连接，创建页面、读取、点击和访问 I5 验收站点均通过。未执行本轮产品登录、DOCX 下载与 Word 逐页验收，不宣布 I5 完成。**

用户要求参照 [2026-10-02 修复记录](browser-repair-and-i5-capabilities-2026-10-02.md) 恢复外置浏览器，并告知本机 7890 端口已有代理。本轮由 Codex 协调者执行，不署名为 Trae Work。

## 核对与恢复

- 当前用户为 `yw980`；系统为 Windows 11 专业版，版本 `10.0.26200`、build `26200`、64 位。历史记录的 `admin` 用户与 Windows Server 2025 环境不套用于本机。
- 实际启动器为 `C:\Users\yw980\AppData\Local\OpenAI\Codex\runtimes\cua_node\81ea4d5168ddd0a3\bin\node_modules\@oai\cua-repl\dist\lib\js\oai_js_cua_repl\src\launch.js`。
- 文件已有 `NODE_USE_ENV_PROXY=1`、HTTP/HTTPS 大小写代理变量及保留原条目的回环 NO_PROXY 合并逻辑；SHA-256 为 `481DEDE49A4D70F714E4BF5EED4140B0891EA52FFA3B03FE4C6283A8A2396511`，与历史记录修复后文件一致。运行时 Node `--check` 通过。本轮未重写启动器，未修改系统代理或扩展权限。
- `curl.exe --proxy http://127.0.0.1:7890 --head --max-time 15 https://example.com` 返回 HTTPS 200。
- 初始浏览器清单只有内置浏览器及 MCP Apps，进程清单未发现外置 Chrome/Edge。使用已安装 computer-use 技能的正式 `@oai/sky` 接口启动现有 Edge 后，发现两个 `type=extension` Edge 注册，profile 均为“用户配置 1”；选择 provider `3` 实测。
- Edge EXE 版本 `154.0.4258.48`。Chrome EXE `154.0.8037.98` 已安装，但本轮未启动或复测 Chrome。
- 外置 Edge 新建 `https://example.com`，实际读取正文；点击 “Learn more” 后到达并读取 `https://www.iana.org/help/example-domains`；随后导航到 `https://kg-next-verify.ywyz.tech`，读取到项目登录表单。未发生历史连接错误，无需重启 Codex。

官方 [扩展排障说明](https://learn.chatgpt.com/docs/chrome-extension) 要求检查运行中的浏览器及正确扩展 profile。本次恢复成功的直接操作是启动现有 Edge；不据此证明所有 profile 或 Trae Work 的连接均正常。

## I5 能力与待执行项

| 项目 | 本轮结论 |
| --- | --- |
| 外置浏览器创建／读取／点击／导航 | Edge 实测通过；与内置浏览器分别记录 |
| 远程验收入口 | 外置 Edge 登录页可见；未登录 |
| 测试账号 | 历史 `C:\Users\admin\...\private-acceptance-accounts.json` 在本机不存在；未读取或输出凭据 |
| SSH | 本机有 OpenSSH；严格主机校验的只读连接因缺少 bwh.ywyz.tech 已知 ED25519 主机密钥而停止，未验证私钥认证，未绕过主机校验 |
| 桌面系统／软件 | 系统符合规格；Word EXE 存在，Microsoft Office 版本 `16.0.20430.20092`；仅安装检查，未打开 DOCX |
| 桌面控制 | CUA 原生入口禁用；独立 `@oai/sky` 技能成功启动 Edge 并读取窗口清单，因此不能仅据 CUA 入口判断 Word 不可操作；Word 操作本轮未实测 |
| 请求暂停／释放 | 当前外置 Edge tab capabilities 列出 `pageAssets` 与 `cdp`，已读取正式 CDP 文档；尚未执行命令或验证 Fetch 拦截，不沿用旧报告“无 CDP”的能力清单，也不标 R14 通过 |
| 产品下载／中文落盘／ZIP／SHA-256 | 本轮未执行；历史单样例通过不能移作本机证据 |
| Word 全部页面／关闭后哈希 | 本轮未执行 |

浏览器连接已具备继续产品验收的基础。完整 I5 仍需安全取得合成账号、执行真实 UI 下载与 W1–W6／R01–R16，完成所选 Word/WPS 全部页面及哈希证据，并单独核实请求延迟能力。当前规格仍指定 Trae Work 执行浏览器验收；本轮 Codex 能力检查不替代其执行记录。

本轮未修改业务代码、部署或历史验收结论，未安装 Skill/MCP，未 commit/push。自建测试标签页关闭，保留原有浏览器标签页和进程。
