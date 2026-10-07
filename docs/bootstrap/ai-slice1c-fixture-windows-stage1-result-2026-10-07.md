# AI 1C 独立夹具 Windows 首阶段结果（2026-10-07）

结论：**C5-v1 已就绪，等待托管者发布 v2。** 本轮只完成 v1 个人状态准备，不宣称 C5 产品验收通过。v2/v3 发布、契约适配及缺／错主密钥案例尚未执行。

## 执行范围与实际状态

按用户指定的 Windows 首阶段提示词及同目录最新交接执行，仅使用 https://kg-next-ai-fixture.ywyz.tech。账号为待分配合成教师 `tfr_i5`，任务为 `daily_lesson_split`。没有写业务代码、安装工具、发布契约、切换密钥或调用供应商。

首次真实详情 GET200，个人 head 未初始化：`state=not_initialized`、`personal_revision=null`、`based_contract_version=null`、最新契约 v1、最新默认 r8。服务端字段顺序精确为 theme、objectives、preparation、key_points、difficult_points、process。

通过真实 UI 点击“建立我的指导”，初始化 HTTP200，个人版本成为1、基于契约1、已处理默认8。逐字段输入公开合成标记 `AI1C-C5-v1-<字段名>` 并点击“保存修改”；页面显示“指导已保存（版本2）”，六字段齐全、保存／放弃按钮禁用。

保存后工具超时，未捕获原保存请求的真实 HTTP 数字；该缺口保留，不以 UI 成功推定200，也未为补证据重复保存或制造个人版本。

2026-10-07 **20:18:33（Asia/Shanghai）** 外置 Edge重新登录、显式刷新并重进详情成功。刷新后的真实详情 GET200，响应和 DOM 一致：

| 项目 | 实际值 |
| --- | --- |
| state | initialized |
| personal_revision | 2 |
| based_contract_version | 1 |
| latest_contract_version | 1 |
| latest_default_revision | 8 |
| accepted_default_revision | 8 |
| adaptation_state | current |
| 六字段内容 | 分别精确为 `AI1C-C5-v1-theme`、`AI1C-C5-v1-objectives`、`AI1C-C5-v1-preparation`、`AI1C-C5-v1-key_points`、`AI1C-C5-v1-difficult_points`、`AI1C-C5-v1-process` |

重启后登录200、刷新页面200、auth/me200、配置GET200、任务列表GET200、教案拆分详情GET200。请求由真实 UI 产生，CDP仅被动观察并提取状态与指定版本字段；没有 API 直调、WSL 或模拟页面替代 DOM 验收。

## 浏览器连接修复与证据边界

参考 [10月5日修复记录](browser-proxy-repair-2026-10-05.md)与[10月2日修复记录](browser-repair-and-i5-capabilities-2026-10-02.md)。首次两份 Edge 扩展均报 `nodeRepl.fetch request failed`；内置浏览器先完成初始化与保存，随后读页／刷新／重新绑定连续超时。

本机用户级代理已启用 `127.0.0.1:7890`，端口正常监听，curl经该代理访问example.com200；WinHTTP为direct，当前shell没有代理环境变量。实际CUA运行时已换为 `71e3f41277f96d73`，启动器无历史代理补丁，SHA-256与历史未补丁原件一致。未仅凭路径变化推定具体更新过程。

用户授权检查并修复后，先备份当前launch.js，再在唯一原子进程env合并点恢复历史最小注入：NODE_USE_ENV_PROXY=1、HTTP/HTTPS大小写变量指向既有回环代理，NO_PROXY大小写保留已有条目并合并localhost、127.0.0.1、::1。反向移除新增字段逐字等于原件，运行时Node语法检查通过，启用环境代理的Node fetch200。未改系统代理、扩展权限或安全策略；这是历史临时绕行，不声称官方修复。

| 项目 | 结果 |
| --- | --- |
| 原启动器SHA-256 | `3E52A41F4DA41D35BE8CC3723FE97251711087A998C1ED7F2CFDF7E20B50FC2B` |
| 补丁后SHA-256 | `481DEDE49A4D70F714E4BF5EED4140B0891EA52FFA3B03FE4C6283A8A2396511` |
| 同目录备份后缀 | `.bak-proxy-20261007-200858` |
| 仅js_reset | Edge仍连接失败；内置页面绑定仍超时 |
| 用户完整重启Codex后 | Edge extension browser4真实新建页面、登录、点击设置、显式刷新及重读全部成功 |

不把Node网络成功、浏览器库存或内置成功当作外置恢复证明。实际恢复结论来自重启后的DOM动作。其他用户窗口和标签未操作。原内置tab在重启后已不在库存；本轮新建外置tab `1378631857` 已markHandoff保留，等待真实发布成功manifest后接续。

## 私密交接与下一阶段

完整就绪报告与去敏DOM／HTTP／截图保留在仓库外既有受限目录，不提交凭证、cookie、token、DSN、secret、完整请求正文或敏感响应：

- `C:\Users\yw980\.codex\tmp\ai1abc-desktop-acceptance-20261005\logs\ai1c-c5-v1-ready-20261007.md`
- 同目录 `ai1c-c5-v1-refreshed-dom-20261007.txt`、`ai1c-c5-v1-refreshed-http-20261007.json`、`ai1c-c5-v1-refreshed-20261007.png`
- 同目录 `browser-proxy-repair-2026-10-07.md`

初始化、保存UI成功与刷新持久化证明分别记录；原保存HTTP缺失由托管者知悉，不抹去失败历史。托管者核对真实个人版本2／v1／r8后准备并发布v2；Windows仅在收到真实成功manifest后进入适配验证，本轮未自行发布。C5通过判定仍待后续案例完成。

用户随后明确授权提交、推送本轮去敏文档。提交仅含本报告；会话开始前已有的 `browser-capabilities-recheck-2026-10-03.md` 未跟踪文件不纳入。部署、实现、自动证据与产品验收状态不互相替代。
