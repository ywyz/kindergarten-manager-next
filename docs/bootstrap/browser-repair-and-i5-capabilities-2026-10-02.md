# 外置浏览器修复与 I5 剩余能力复测（2026-10-02）

状态：**外置 Chrome／Edge 的连接、读页和点击已通过；外置 Edge 的真实产品下载、Word 打开／缩放／翻页／关闭及原件哈希复核已通过单样例能力检查。请求暂停／拦截仍受阻，I5 全套产品验收仍待 Trae 记录收口。** 本文不将能力检查等同于 R01–R16 或 W1–W6 全部通过。

用户授权按 GitHub issue 尝试修复、继续复测，并将修复过程记录在仓库；本文与证据先保留未提交，待 Trae 验证记录一并 commit／push。未修改业务代码、架构、验收规格或远程部署。本轮为 Codex 协调者实测，不能署名为 Trae Work 的执行结果。

## 连接对象与问题来源

本轮明确区分 `type=extension` 的外置浏览器与 `type=iab` 的内置浏览器。早先内置浏览器成功不能证明外置浏览器正常；Windows 浏览器进程存在或扩展已被发现，也不能证明读页／点击成功。

用户提供 [openai/codex #44383](https://github.com/openai/codex/issues/44383)。已阅读 issue 及评论，采用其中[代理环境注入的社区绕行方法](https://github.com/openai/codex/issues/44383#issuecomment-5690733392)，相关报告为 [#44364](https://github.com/openai/codex/issues/44364)。这不是已发布官方修复的证明，也没有替换评论提供的整份旧版运行时文件。

[OpenAI 官方浏览器扩展排障说明](https://learn.chatgpt.com/docs/chrome-extension)要求核对已安装扩展的 profile、连接状态、浏览器／桌面应用重启等。以下运行时代理补丁来自社区 issue；成功结论来自本机实际操作。

## 修复过程

| 阶段 | 本机观察与处理 |
| --- | --- |
| 修复前 | 外置 Chrome 与两份 Edge 扩展注册可发现，但列标签页／创建页面失败，错误为 `nodeRepl.fetch request failed`，约 21 秒后返回。内置浏览器另行可用 |
| 代理核对 | 现存本地代理为 `127.0.0.1:7890`，FlClashCore 正在监听；普通 curl 与启用环境代理的 Node 请求 example.com 返回 200 |
| 最小补丁 | 在当前 CUA 启动器实际创建子进程的 `env` 合并对象中加入代理变量，保留原 `i.env` 与其他配置；先备份，再修改并检查语法 |
| 仅重置会话 | `js_reset` 未重启承载启动器的父进程，原错误仍存在，不能当作补丁已重新加载 |
| 完全重启 Codex | 用户完成重启。只读检查确认新的 node_repl 和 trusted-worker 进程包含代理变量；原应用／启动器自身与 untrusted kernel 没有被统一注入代理 |
| 首次重启后 | Chrome 一度报 `Unable to load browser request-header policy. Retry the browser command.`，关联策略初始化请求超时；Edge 当时未列出，用户随后打开已安装扩展的 Edge profile |
| 最终连接复测 | 外置 Edge 和 Chrome 均完成列标签页、新建页面、读取、点击链接及目标页读取；这一轮无上述两类错误。完全重启后没有再次修改补丁 |

匿名访问 ab.chatgpt.com 的诊断请求曾返回 403／挑战页；它没有携带运行时的认证上下文，不能据此判定认证策略请求的根因。策略初始化错误后来消失的直接原因尚未确定，也没有证据证明“打开 Edge 修复了 Chrome”。

### 实际修改位置与内容

当前运行时标识：`81ea4d5168ddd0a3`。修改文件：

```text
C:\Users\admin\AppData\Local\OpenAI\Codex\runtimes\cua_node\81ea4d5168ddd0a3\bin\node_modules\@oai\cua-repl\dist\lib\js\oai_js_cua_repl\src\launch.js
```

在已有 `env:Object.assign(Object.assign({},i.env),{...})` 对象内新增以下字段；后续原有 `CUA_REPL_ENABLED_SURFACES` 等字段原样保留：

```js
NODE_USE_ENV_PROXY: "1",
HTTP_PROXY: "http://127.0.0.1:7890",
HTTPS_PROXY: "http://127.0.0.1:7890",
http_proxy: "http://127.0.0.1:7890",
https_proxy: "http://127.0.0.1:7890",
NO_PROXY: [i.env.NO_PROXY || i.env.no_proxy, "localhost", "127.0.0.1", "::1"].filter(Boolean).join(","),
no_proxy: [i.env.no_proxy || i.env.NO_PROXY, "localhost", "127.0.0.1", "::1"].filter(Boolean).join(","),
```

保留已有 NO_PROXY 条目并补充回环地址。本次没有改系统代理、浏览器 profile、扩展权限、服务信任配置或隔离配置，也没有安装 Skill／MCP。

| 检查 | 结果 |
| --- | --- |
| 备份 | 同目录 `launch.js.bak-proxy-20261002-161908` |
| 原文件 SHA-256 | `3E52A41F4DA41D35BE8CC3723FE97251711087A998C1ED7F2CFDF7E20B50FC2B` |
| 修改后 SHA-256 | `481DEDE49A4D70F714E4BF5EED4140B0891EA52FFA3B03FE4C6283A8A2396511` |
| 语法 | 使用该运行时 Node 执行 `--check`，通过 |
| 修改范围 | 反向移除新增代理字段后与备份逐字一致；原 services／trusted-service 等配置保留 |
| 收口复核 | 2026-10-02 17:13（UTC+8）再次核对当前文件与备份，哈希仍与上表一致 |

补丁在仓库外的已安装应用运行时中；Git 只记录本文及脱敏能力证据，不追踪应用运行时或私密账号。它属于临时绕行：应用更新可能覆盖文件或切换运行时目录。再次故障时应先核对实际启动路径与补丁是否仍存在，不能机械覆盖新版本文件。

回滚仅适用于上表这一运行时及匹配的当前哈希：退出 Codex，将同目录匹配备份恢复为 `launch.js`，核对恢复后哈希等于原文件哈希，再完整启动 Codex。如果应用已更新或文件哈希不同，先重新审查，不覆盖未知版本。原备份与本地非凭据诊断记录 `C:\Users\admin\.codex\tmp\cua-browser-proxy-repair-20261002.json` 均保留；该旧诊断记录的下载状态仅截至连接复测，本轮下载／桌面状态以本文为准。

## 外置浏览器实际控制

| 对象 | 实测结果 |
| --- | --- |
| Chrome | provider `3`，`type=extension`，profile `ywyz.tech`；程序版本 `154.0.8037.98` |
| Edge | provider `4`，`type=extension`，profile `Profile 1`；程序版本 `154.0.4258.48`；重复注册 provider `5` 未作为本轮控制对象 |
| 内置浏览器 | provider `2`／`iab`，与以上外置扩展对象分别记录；本轮外置结论不来自它 |
| Chrome 实际操作 | 新建 https://example.com，读取标题／正文，点击 “Learn more”，到达并读取 https://www.iana.org/help/example-domains；测试页关闭且确认不存在 |
| Edge 实际操作 | 同样完成 example.com → 点击 → IANA 读页，并关闭测试页且确认不存在 |

这些是本机这一轮成功操作的结论，不证明所有 profile、所有工具或另一应用 Trae 的连接状态永久正常。

## 剩余任务能力矩阵

| 能力 | 本轮状态 | 对 I5 的实际边界 |
| --- | --- | --- |
| 外置浏览器连接／导航／读取／点击 | 通过 | Chrome／Edge 均已实际完成 |
| 产品登录、打开日计划与选择导出范围 | 通过 | 外置 Edge 使用隔离合成账号进入远程验收产品；没有保存／确认计划 |
| 真实产品下载及中文落盘文件 | 通过单样例 | 日计划 2026-09-01 当前日期，文件实际进入 Windows Downloads；不是 API 直调生成的样例 |
| 工具的 download 事件捕获 | 本轮失败：超时 | 点击前注册的 `waitForEvent("download", {timeoutMs:15000})` 未完成。事件接口失败与真实文件已落盘分开记录 |
| 下载字节／SHA-256／ZIP | 通过单样例 | 14,490 字节，13 个 ZIP 条目，CRC 完整；XML 读取只作文件检查 |
| 桌面 Word 启动／打开 | 通过单样例 | 已安装 Word 实际打开原下载文件，进入 Protected View，未见修复／转换提示 |
| Word 缩放／页面滚动／翻页 | 通过单样例 | 单页 35% 与 75% 缩放可操作，页面可滚到第二页，状态栏确实显示“第 2 页，共 2 页” |
| Word 打印预览 | 受阻于 Protected View | UI 显示预览不可用并要求“启用打印”；未代操作该安全权限入口。可继续使用规格允许的页面视图 |
| Word 关闭／不保存／原件哈希 | 通过单样例 | 窗口关闭后 Word 窗口列表为空，未出现保存提示；下载原件哈希前后相同 |
| R13 多会话冲突 | 未执行 | 两个外置浏览器可用；尚未验证具体会话隔离及版本冲突流程，不能据连接结果标 R13 通过 |
| R14 请求暂停／拦截／按顺序释放 | 工具受阻 | 正式 API 无 route／请求暂停／响应释放接口；browser capabilities 仅 viewport，tab capabilities 仅 pageAssets |
| R15 双击／生命周期 | 未执行；延迟子例受阻 | locator 有 dblclick 方法，但请求计数与受控延迟释放未实测；需 Trae 工具或人工补充 |
| W1–W6 全部样例逐页版式 | 未执行 | 本轮仅证明一个普通日计划的操作链路；未验收长过程、标红、假期动态列、版本、31／8 份合并等全集 |

没有通过未文档化 API、页面 fetch 猴子补丁或另装 CDP／MCP 来模拟“工具已支持请求拦截”。R14 的既有 18 项自动行为检查仍在[修复与部署记录](i5-remote-validation-2026-10-02.md)中单列，不能替代浏览器受控延迟证据。

### 下载与桌面样例证据

- 服务器：[独立 I5 验收实例](https://kg-next-verify.ywyz.tech)，使用既有合成夹具；页面选择小班甲、2026-09-01、内容 v1、导出范围“当前日期”。
- 原文件：`C:\Users\admin\Downloads\小班甲_日计划_2026-09-01_2026-09-01 (2).docx`；落盘修改时间 `2026-10-02T16:46:28.2421982+08:00`。`(2)` 为本机同名下载后缀，不是产品版本号。
- 下载及关闭后 SHA-256：`C06E1A15AC1C9442A1EA4582C92105A870871DA1391E5FBC3543A6EE938B00CA`，14,490 字节。副本与原文件一致。
- Word 实际环境：Windows Server 2025 Datacenter `10.0.26100`／build `26100`／x64；软件 UI 为 Word，EXE ProductName 为 Microsoft Office，ProductVersion／FileVersion 为 `16.0.20430.20092`；PE machine `0x8664`，x64。
- 样例声明字体包含仿宋、仿宋_GB2312、宋体、楷体、Times New Roman、Liberation Sans、Noto Sans CJK SC。系统字体注册及文件核对见宋体、仿宋、楷体、Times New Roman、Liberation Sans；本轮未确认 Noto Sans CJK SC／仿宋_GB2312 的实际替代关系，不宣称字体兼容验收完成。
- 桌面输入使用已安装 `computer-use` 技能的正式 `@oai/sky` API。CUA 的原生应用入口不可用，不等于独立桌面技能不可用；此前“无法操作 Word”的判断已纠正。
- 原生控件树曾与前台截图不同步，部分索引操作报 `element ... is not available in cached app state`。重新激活／刷新，并依据匹配的截图定位文件名、缩放和关闭控件后成功。快捷键 Ctrl+F12、Ctrl+Home、Ctrl+W 未得到相应完成证据，改用可见控件／滚动完成；不将快捷键发送成功当作动作完成。

Protected View 的打印入口未执行，依据已读 [computer-use SKILL.md](../../../../.codex/plugins/cache/openai-bundled/computer-use/26.930.21537/skills/computer-use/SKILL.md) 所要求读取的 [guidance.md](../../../../.codex/plugins/cache/openai-bundled/computer-use/26.930.21537/docs/guidance.md) 明文约束：**“Do not act on security or privacy permission requests.”** 将本文件的“启用打印”视为此类安全权限入口是本轮解释；页面查看、缩放、滚动与关闭已经完成，不要求用户解除全局 Protected View。

本轮产生的文件与截图副本见 [证据清单](evidence/browser-capabilities-2026-10-02/manifest.json)。截图仅包含合成产品数据，保存为能力证据；35% 整页图用于确认页面整体可见，75% 图用于文字及第二页状态，不能以低倍率截图证明所有文字无缺字。浏览器产品页截图在收尾时采集，期间其他验收操作可能已改变夹具，不能拿它重建 16:46 的完整数据库快照。

记录收口检查通过：清单内 5 个证据文件的字节与 SHA-256 全部匹配，DOCX ZIP CRC 通过，本文本机相对链接均存在，下载原件前后及证据副本哈希一致；已跟踪文档的 `git diff --check` 通过。截图页码可能跟随光标所在页，单纯滚动后不立即更新；第二页 75% 图已经明确显示“第 2 页，共 2 页”。

## 收尾与后续提交

本轮已退出测试登录、关闭自建 Edge 产品页与通用连接测试页，关闭仅本轮启动的 Word 文档；保留下载原件、证据副本和运行时备份。未操作其他人的下载或标签页，未新增／确认计划。真实导出可能按服务设计新增成功审计，这与计划业务内容写入分开。

待 Trae 提供逐项 R01–R16／W1–W6 记录、实际下载、所选桌面环境全部页面证据及未完成项后，统一审阅并将本文与其记录一并 commit／push。通过、失败、受阻与未执行分别记录；存在 R14 或其他未完成项时仍不能宣布 I5 片4完成。
