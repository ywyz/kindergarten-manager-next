# AI 1A＋1B＋1C 桌面远程产品验收（2026-10-05）

**2026-10-07 补验及收尾完成：密码恢复、返回确认、退出与账号隔离均已通过。旧默认 accept target 与本轮验收预期不符仍保留失败；C5／V1 发布夹具及真实主密钥降级夹具仍受阻，不宣布全通过。**

## 环境与证据边界

- 仓库 `git pull --ff-only` 成功，HEAD `7d91383ff02f2fa71c6e5591907ddbeb7e736a57`；已有未跟踪 `browser-capabilities-recheck-2026-10-03.md` 保留，未改业务代码、registry、数据库、部署或主密钥，未安装依赖／Skill／MCP，未 commit/push。
- Windows 11 专业版，10.0.26200／build 26200／64 位；外置 Edge EXE `154.0.4258.53`。工具为现有 `mcp__cua_repl` 真实 DOM／浏览器与其 CDP；已安装 computer-use 技能仅用于核对桌面浏览器进程。日期／时间按 Asia/Shanghai；私密事件以 ISO UTC 保留，可加 8 小时对应本地时间。
- 真实入口 https://kg-next-verify.ywyz.tech 。部署交接标称 release `ai1abc-20261005-b08234d51044`、迁移 `20261003_ai1a_config_prompts`；未为本轮浏览器验收 SSH 重读运行指针／库 migration，因此不声称本轮独立复核服务器文件哈希。已读部署结果、1C、1B、第五轮收口与源清单交接。
- 初始外置 Edge 因 request-header policy 初始化失败；内置真实浏览器先执行首存／清除与七任务只读。用户随后明确要求修复代理；发现运行时更新覆盖旧补丁，按 [修复记录](browser-proxy-repair-2026-10-05.md)恢复最小补丁并重置会话，外置 Edge 真实新建／登录／点击／读页恢复。之后主要使用外置 Edge。两层分别记录，未使用本机 WSL/Vite/mock 或 requests 代替 DOM。
- Edge 两普通页面用于同身份独立编辑基线；Edge 与内置浏览器是独立 cookie 会话，管理员退出后内置旧页得到 401，Edge 教师会话仍有效。未把两个普通标签称为隔离 cookie profile。
- 私密根目录：`C:\Users\yw980\.codex\tmp\ai1abc-desktop-acceptance-20261005`；报告／备份／下载／截图均在 `logs`。只保留请求方法、路径、状态、版本、变更字段名与 secret 是否存在，不导出 Network 原始载荷／cookie。密码和临时交接仅私密文件。
- 未调用供应商、未测试连接、未启动 worker／材料／完整 W6；历史 648 后端、29＋356 离线脚本及部署 HTTP 冒烟保持其他证据层，本轮未重跑或拿来代替 DOM。

## 真实案例与实际结果

截图路径下列均相对于私密 `logs/screenshots`，不进入 Git。每个事件时间见 `logs/evidence.private.json`，其他动作有相应独立私密记录。部分按钮后 Vue 尚未完成刷新，首次即时查询可能读到上一帧；最终结果均再观察，未把即时帧误报产品失败。

| 编号／子例 | 状态 | 预期、实际动作与结果 | 证据 |
| --- | --- | --- | --- |
| C1 五账号本人入口 | 真实通过 | tow／tsw／tcr／tfr／adm 逐一真实登录进入设置，本人配置和指导可读。待分配页面有“暂不能备课”，仍可读本人设置；四教师均无系统默认面板 | tow-initial-settings.png、unassigned-settings.png、tsw_i5-settings.png、tcr_i5-settings.png；roles.private.json |
| C1 管理员独立面板 | 真实通过 | 默认和本人指导同时显示。管理员本人教案拆分显式建立 revision=1；默认发布未改本人 map／revision | default-v5-before-old-accept.png；default-original.private.json |
| C1 loading／失败重试 | 前端模拟通过 | 实际进入设置显示配置／列表 loading；任务真实响应在浏览器强制网络失败，出现固定“任务详情读取失败”及“重新读取该任务详情”，点击后从真实服务器恢复；不是服务器故障夹具 | current-detail-read-failure.png；CDP 动作记录 |
| C1 文字布局 | 已实际查看 | 待分配全页、默认比较、旧目标失败、写后刷新失败截图已视觉检查；文字、字段、状态与按钮可见。长页面一度 captureScreenshot 超时，改用视口截图，失败保留 | 上述去敏截图；evidence 中 screenshot-error |
| C2 初始与首次保存 | 真实通过 | tow 初始 version=0、无密钥；填 HTTPS／模型但空密钥时保存禁用。合成密钥 UI 首存 PATCH 200 到 v1，输入清空，固定遮罩，显示“本地配置可用，尚未验证供应商连接” | config-first-save.png；请求 secret_present=true |
| C2 重载／元信息／轮换 | 真实通过 | 重载再进设置地址模型仍在、无密钥回填；空密钥改模型到 v2，PATCH 省略 secret 且 has_secret；新合成密钥轮换到 v3 | evidence.private.json；清空输入布尔断言 |
| C2 清除取消／确认／持久化 | 真实通过 | v3 先取消，未 DELETE／版本不变；确认 DELETE 200 到 v4，地址模型保留；外置恢复登录重读仍 v4、无密钥。已存在清除 head，仅元信息保存到 v5 | clear-cancel-v3.png、cleared-v4.png、edge-repaired-settings.png |
| C2 失败输入保留 | 真实409／前端模拟通过 | 真实配置 409 本页合成密钥／元信息保留，比较独立、未选前写按钮禁用；另以 CDP 在真实配置请求送达前模拟网络失败，输入仍非空、模型保留，服务器仍v8。密码型DOM被工具遮蔽，直接值相等断言不可用；不把该遮蔽误报清空 | C6 配置分流记录 |
| C2 成功／载入／401 清空 | 真实通过 | 成功后空输入；显式载入最新清空输入；内置管理员旧页真实 401 后回登录页，密钥控件消失，另一账号登录不继承 | C6／C7、unassigned-settings.png |
| C2 卸载清空 | 真实DOM通过 | 网络失败后仍有未保存合成密钥，重载回首页再进入设置，密钥输入长度0、服务器v8、原模型不变 | config-unloaded-v8.png；config-failure-unload.private.json |
| C2 持久存储／URL | 现场检查通过 | 浏览器 localStorage／sessionStorage 及 URL 无 `synthetic-no-value-` 标记；保存后的页面固定遮罩，未回显完整 secret。仅检查现场状态，不声称证明所有历史时刻 | CDP 布尔读数，未输出存储值 |
| C3 七任务只读 | 真实通过 | 七任务逐一 GET，全部未初始化、latest contract=1／default=1，只读无自动初始化。只有按钮“建立我的指导”才写 | initial-task-1…7.png；tasks-initial.private.json |
| C3 七任务全字段保存 | 真实通过 | 七项分别 6／1／4／4／4／1／2 字段，全字段实际填写并保存，个人 revision 1→2，重载逐项重读保留。周栏目字段顺序变化，按字段名复核四份文字都在；不是丢失 | task-persistent-1…7.png；tasks-results／persistence／weekly-columns.private.json |
| C3 重复初始化 | 真实同源补充通过 | 周材料 UI 首次建立后，浏览器同源再次 POST initialize 得 200、idempotent=true、personal_revision=2，未新增个人版本。不是重复点击已消失的 UI 初始化按钮 | CDP 只输出 status／idempotent／revision |
| C3 无变化／局部 patch | 真实通过 | 无变化时保存禁用；普通单字段修改请求 guidance_map 只包含该字段，未重发其他文字 | evidence changedFields；DOM 禁用断言 |
| C3 空串／换行／空白 | 真实通过 | 教案拆分 theme 保存空串到 r3，再保存首尾空白与换行到 r4，离开任务重读严格相等，未 trim | 原样布尔断言，私密备份 |
| C3 8000／8001 | 真实 HTTP 通过 | 8000 字符 PATCH 200 到 r5；现有 fill 输入 8001 后点击保存，服务器 422 固定“保存未通过校验”，输入保留。明确是 HTTP 422，不能称 UI 阻断也执行了 | evidence 中 422；非原始 payload |
| C3 HTML 样文字 | 真实通过 | theme 保存 HTML 样合成文字到 r6，默认比较中按字面文字显示，未形成粗体 HTML | html-text-comparison.png |
| C4 默认发布不改个人 | 真实通过 | 教案拆分 theme/objectives 有可区分个人文字；管理员备份原默认并发布两字段到 default r2；管理员个人不变，教师重读出现更新／两列比较 | default-original.private.json；比较截图 |
| C4 只接受一字段 | 真实通过 | 只勾 theme，页面说明覆盖所选／保留未选；accept-default 200，个人 r6→r7，theme 变默认 D2，objectives 原样 | accept-one-field-before.png；真实请求版本 |
| C4 拒绝／重复／再接受 | 真实通过 | 默认 r3 后两次拒绝，个人仍 r7；可主动再打开比较并接受 r3到 r8。重复拒绝服务幂等字段尚未单独从响应体提取，UI／版本不变已验证 | reject-default 请求／状态／版本 |
| C4 dirty 比较写入 | 真实通过 | 普通草稿 dirty 时接受／拒绝禁用，提示先保存或明确放弃；原文字保留，随后明确放弃 | DOM 按钮断言 |
| C4 默认恢复 | 真实通过 | 多轮发布和冲突后，通过 UI 追加 default r8 恢复原 map；管理员本人 r1 不自动更新；未回退数据库指针 | 默认恢复记录 |
| C5 v2/v3 真发布及适配 | 受阻 | 缺经单独授权的真实发布夹具；没有改 registry、写库或导入测试模块，不执行待适配／完整适配／收缩契约案例 | 交接夹具限制 |
| V1/U3 子例 1–4 | 全部受阻 | 同／异字段双草稿、远端 current／仍待适配、收缩契约移除字段、参考槽可见及明确处置都依赖未提供发布夹具；不以脚本／绑定声称 DOM 通过 | 同 C5 |
| C6 配置双页面冲突 | 真实通过 | 两页面从 v5，A 保存 v6，B 旧保存 UI 冲突并保留输入；保留选择无请求，另点保存到 v7。A 旧 v6再写得到 409、companion GET 200，载入最新替换模型清密钥，随后清除到 v8 | config-load-latest-v7.png；两页面请求元数据 |
| C6 个人双页面冲突 | 真实通过 | 两页面个人 r9，A 到 r10，B 旧写409文字保留；明确保留操作请求数0，另点保存到r11；A旧r10写409，再显式载入r11，文字正确 | evidence.private.json page B；真实 expected |
| C6 管理员默认冲突 | 真实通过 | 两页面 default r5，A发布r6，B旧写冲突；保留选择无请求，另点发布到r7；A旧r6写真实409／GET200后载入r7 | admin-network-metadata.private.json |
| C6 比较期间默认推进／旧 accept target | **真实失败** | 比较捕获 target r4；管理员页面先确认发布 r5；教师再 accept 旧r4得到200，个人r8→r9，已处理默认4、最新默认5。预期旧 target 应失效并重新勾选 | default-v5-before-old-accept.png、old-target-accepted-failure.png；accept-default HTTP200 |
| C6 旧 success/error/finally 切换任务 | 前端模拟通过 | 暂停真实周材料200响应、切到周游戏后释放；另一轮切周栏目后强制旧网络失败，新任务内容提示不污染。新旧响应都暂停时先释放旧响应，新任务仍显示 loading，最后释放新响应 | delayed-old-success-released.png、old-error-isolated.png；CDP 控制 |
| C6 默认面板／离开旧响应 | 前端模拟通过 | 暂停默认教案响应，切默认周材料后释放，字段仍 extraction/supplement；再暂停默认请求、返回首页后强制旧失败，首页保持，无旧面板回写。没有强行 mutate disabled 输入 | CDP 控制及 DOM 断言 |
| C6 写成功后刷新失败 | 前端模拟通过 | 周栏目 PATCH真实200到r3，再只强制后续GET响应交付失败；UI明确已保存成功，仅刷新失败，保存禁用，不诱导重复写 | saved-refresh-failed.png |
| C6 返回确认／取消 | 补验真实通过 | 纠正先前观察位置：实际为页面内alert而非JS对话框。普通process草稿返回时显示确认；点击“留在此页继续编辑”文字严格保留；明确放弃后返回首页无确认。未提交草稿 | return-confirm-dom.png；retry-leave-logout.private.json |
| C6 参考区／适配返回确认 | 受阻 | 当前契约无适配／参考草稿，依赖C5；未制造虚假草稿 | 同C5 |
| C6 账号切换清草稿密钥 | 补验真实通过 | 普通process草稿加未保存合成密钥，退出显示页面内确认且密钥立即清空；取消后个人草稿保留；再次退出并确认不保存，回登录页。真实登录tsw_i5，设置密钥为空且无上一账号草稿，随后UI退出。未保存指导或计划 | logout-confirm-dom.png、account-switch-no-draft.png；retry-leave-logout.private.json |
| C7 教师403／无密钥422 | 真实同源补充通过 | 已登录教师 GET管理员默认403 FORBIDDEN固定“没有权限”；不含secret的非法配置PATCH422 VALIDATION_ERROR固定中文，未输出payload | 浏览器同源结果 |
| C7 无会话401／旧页清空 | 真实通过 | 真实UI退出后设置GET401 AUTH_REQUIRED；旧管理员页带未保存合成密钥触发GET后退出，输入卸载，外置教师独立会话仍登录 | 401结果与DOM布尔值 |
| C7 修改密码撤销／改回 | 补验真实通过（2026-10-07） | 用户手工原密码→临时→原密码。首次旧独立会话读取401、回登录且密钥输入卸载；临时密码独立登录200。改回后临时会话读取401，临时密码登录401、原密码登录200。私密accounts恢复原密码；测试登录已退出。密码修改提交本身未捕获响应，不捏造其HTTP状态 | password-complete-20261007.private.json；password-complete-logged-out-20261007.png |
| C7 缺／错主密钥503／DECRYPT_UNAVAILABLE | 受阻 | 缺单独授权真实服务夹具，正常环境没有503不能记为降级通过；未改变主密钥 | 交接限制 |
| C7 原姓名 | 真实通过 | 原设置UI修改合成姓名，重新进设置重读已保存，再UI恢复原名；保存后回首页，按实际导航接续 | name-backup.private.json；请求元数据 |
| C7 日计划保存恢复 | 真实通过 | 既有2026-09-01，现场内容v3；普通重点指导UI保存v4，现场读数后UI追加恢复v5。未改不可变原基准 | day-before／day-fields-original.private.json |
| C7 周草稿保存恢复 | 真实通过 | 既有第1周草稿v2／确认V1，普通本周重点UI保存v3，再恢复v4；仍确认V1对应v2，当前v4待确认，未直接改／重建确认快照 | weekly-before／weekly-field-original.private.json |
| C7 日／已确认周Word | 真实通过 | DOM分别下载，Windows中文落盘、非空、ZIP CRC与SHA-256通过。下载事件接口两次超时，实际落盘独立成功；未打开Office／WPS，不替代历史逐页或完整W6 | downloads-manifest.private.json、保留原件与私密副本 |

## 失败最短复现

1. 教师教案拆分详情载入 default r4，打开比较并只勾 theme，捕获 target_default_revision=4。
2. 独立管理员默认面板发布 theme 新文字，并现场确认“当前默认版本：5”。
3. 教师点击“接受所选字段”，实际 POST accept-default 200，个人 revision=9，theme 接受旧默认4，已处理默认4／最新默认5；提示成功。

此失败仅记录本轮给定预期与真实行为，不修改业务实现，不自行裁定是否改产品规则；交协调者确认预期后安排修复。第一次相同路径已得到200，第二次在明确确认管理员r5完成后确定性重现。

## 下载与副作用

| 文件 | 字节 | ZIP条目／CRC | SHA-256 |
| --- | ---: | --- | --- |
| 小班甲_日计划_2026-09-01_2026-09-01 (6).docx | 14489 | 13／通过 | A51BA8D2F3971E813559CB0A982E807A272C4DB9B5B3EF5E0261A9567EC62974 |
| 小班甲_周计划_1周_2026-08-03_2026-08-07.docx | 19084 | 14／通过 | 0E8C69A9B70C8AE01D43643F85BD1CFE462219FEFCC11881728A30C69180BD67 |

文件留Windows Downloads与私密logs/downloads；同名数字后缀为浏览器落盘后缀，不是业务版本。日导出第一次使用默认“所在周”，得到真实缺项提示且未确认下载；切换“当前日期”后成功。下载事件超时不能代替检查真实落盘。

合法UI写入保留追加历史：tow 配置head v8、密钥已清除、合成地址／模型保留；七个人任务已初始化，教案拆分恢复r12、过程适龄调整r3、日其他活动r3、周游戏r3、周栏目r4、周主题建议r3、周材料r3。初版文字恢复，但不删除初始化／版本／拒绝／接受历史。管理员本人教案拆分r1保持原map，系统默认恢复r8；其他账号仅登录读取。姓名已恢复；日内容恢复v5，周草稿恢复v4且仍待确认、V1不可变。登录／退出／导出可能产生正常session／审计副作用，未写库回退。

最终账号状态（2026-10-07）：tow_i5 原密码已恢复并真实登录200，临时密码登录401；两次密码修改均撤销前一独立会话。私密accounts已恢复原密码。受控Edge与内置浏览器测试登录均退出，自建两页已关闭，用户其他页面未关闭。下载、截图及备份保留，manifest已更新。仍保留失败和受阻案例，不能宣布本片全通过。

## 后续自主补验（2026-10-05）

返回确认和带dirty草稿退出／账号隔离两组已补验通过。此前错误地只检查JS对话框，遗漏页面内alert，现已纠正，撤销这两组的受阻／未执行结论。本次没有写入指导、日计划或周计划正文。

最小契约夹具设计已写私密fixture-preparation-plan.private.json：教案拆分v1真实六字段；v2保留theme/process等同名字段，移除preparation、增加合成acceptance_support；v3再移除已编辑process，各版本配完整合成默认map。只完成设计，未改registry／库或部署。当前公开UI只能发布指导文字，不能发布新契约字段；仓库现有运维脚本未提供可直接执行的真实v2/v3发布夹具。缺／错主密钥仍需要独立远程服务状态。

## 密码补验进展（2026-10-07）

用户完成本轮新临时密码修改并反馈成功。修改前保留的独立内置浏览器会话携带未保存合成密钥，点击过程适龄调整触发真实GET /api/settings/prompts/daily_process_adapt，HTTP401，退回登录页、密钥控件卸载。随后使用交接临时密码在该无会话页面真实登录，POST /api/auth/login HTTP200，当前账号tow_i5。当时私密accounts文件同步了实际验证有效的临时密码（下述恢复完成后已改回原密码）。本轮修改密码提交的响应没有在受控Edge页捕获，因此不捏造其HTTP状态。此段为首次修改后的阶段记录；原密码恢复已在下述收尾完成。

## 密码恢复与最终收尾（2026-10-07）

用户手工改回并反馈成功。此前临时密码登录的独立会话，真实GET /api/settings/prompts/daily_process_adapt返回401、回登录页；在无会话登录表单使用临时密码，POST /api/auth/login返回401；随后改用原密码，POST /api/auth/login返回200，页面确认tow_i5。私密accounts及交接phase同步原密码／已完成。独立会话经UI退出，Edge页处于登录页并显示“密码已修改，请重新登录”；保存去敏截图后关闭两自建页。没有打开下载文档或关闭用户其他窗口。

目前剩余按原因合并三组：旧默认目标接受的已记录行为差异；C5/V1/U3及适配参考区依赖真实契约发布夹具；C7真实缺／错主密钥降级依赖独立服务夹具。原三组重试／补验均已完成。日周正文在2026-10-07补验中未写入，未commit/push。

## 文档交接（2026-10-07）

用户在补验收尾后授权提交并推送本轮去敏文档，供 WSL 环境审阅。提交范围仅为本报告及 browser-proxy-repair-2026-10-05.md；前述“未 commit/push”描述验收操作阶段。私密凭证、请求正文、截图、下载和备份均不进入 Git；会话开始前已有的 browser-capabilities-recheck-2026-10-03.md 保留未跟踪，不纳入本轮提交。仍未改业务代码、部署或测试夹具。
