# Windows Codex 首阶段提示词：C5 v1 就绪

用户已授权本轮独立夹具的契约发布、主密钥故障切换和 Windows 补验。当前只执行下面第一阶段，发布和远程配置切换由 WSL 协调者完成；不用再次申请同项授权。

读取同目录的 `ai-slice1c-fixture-windows-handoff-2026-10-07.md`、`ai-slice1c-fixture-remote-preparation-result-2026-10-07.md`、`ai-slice1c-fixture-plan-2026-10-07.md`。最新交接中的 URL／版本／授权优先于旧桌面提示词中的历史受阻描述。遵守项目 AGENTS.md；不写业务代码，不安装技能或工具。

1. 使用本 Windows 会话已有浏览器工具，先按对应技能初始化并确认实际页面操作可用；工具不可用则报告准确原因，不用 API、WSL 或模拟页面替代 Windows DOM 验收。
2. 只打开 `https://kg-next-ai-fixture.ywyz.tech`。从既有受限目录 `C:\Users\yw980\.codex\tmp\ai1abc-desktop-acceptance-20261005\accounts.private.json` 私密读取 `tfr_i5` 凭证，按文件实际结构使用，不输出凭证。若登录失败或文件缺少该账号，停下报告，不自行重置密码。
3. 登录待分配教师 `tfr_i5`，进入个人指导的 `daily_lesson_split`（教案拆分）。核对契约 v1、默认 r8、六字段 theme/objectives/preparation/key_points/difficult_points/process；个人 head 应尚未初始化。若不符，保留证据交协调者，不删除历史或创建替代数据。
4. 通过真实 UI 显式“建立我的指导”，把全部六字段分别写入公开合成文字 `AI1C-C5-v1-<字段名>` 并保存。刷新重读，确认六份文字持久。记录初始化、保存及重读的真实 HTTP 状态和 personal_revision、based/latest contract/default；不硬编码个人版本，不记录完整请求正文或敏感响应。
5. 在既有私密目录 logs 写 `ai1c-c5-v1-ready-20261007.md`。包含时间、URL、账号名、浏览器工具可用情况、字段名与合成标记、真实版本和 HTTP 状态、截图或 DOM 证据路径；不要包含密码、cookie、token、DSN 或 secret。报告明确写“C5-v1 已就绪，等待托管者发布 v2”，此阶段不能宣称 C5 通过。
6. 保留本轮页面，等待协调者的真实发布成功 manifest 后才进入适配验证。此阶段不发布 v2/v3，不切换密钥，不调用供应商，不启动其他案例。

请向用户交回报告的绝对路径和简短就绪状态，供 WSL 协调者核对后接续。其他用户窗口保持原状。
