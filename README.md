# kindergarten-manager-next

面向幼儿园教师的本地教育工作支持应用。先完成每日活动计划，再做游戏观察记录。项目为全新设计，旧 kindergartenManager 仅作为行为、模板与历史经验参考。

## 当前状态（2026-10-20）

Architecture v2 已确认：保留 Vue 3／TypeScript／Vite／Element Plus 界面，本地业务使用 Python／FastAPI／SQLAlchemy 2.x／Alembic，数据改为 SQLite。优先验证 pywebview＋WebView2，PyInstaller 为打包候选。AI 从教师电脑调用；WebDAV 接续与备份在后续切片落实。

首发保证 Windows 11。一个本地教师档案，首次填写姓名、班级和学期，之后进入工作台；首版不导入旧云端业务数据。

**D0、D1A工程通过；D1B原R1–R17在当前Windows 11开发机工程复审通过。R18日计划Word格式修复的代码、新包及页面验收通过；用户逐页确认长园所2页、合并7页正常，R18已关闭。** 当前分支 `codex/desktop-v2-foundation`，CPython3.14.7标准Windows x64环境／锁保持。[第八轮审阅§17](docs/bootstrap/desktop-d1-review.md#17-d1b-第八轮修复复审与工程收口2026-10-17)及28e3e60e…包历史保留；[R18独立复审§20.6](docs/bootstrap/desktop-d1-review.md#206-用户逐页验收与r18关闭2026-10-17)汇总独立121导出相关／146桌面检查、新c6dc1928…包137文件／12模块一致、3次真实窗口与人工页面验收。本轮教师体验已收口，产品与发行未整体验收，3.12异常保留。

D0的92项测试、仓外三进程、原生保存／取消／占用重试和Word两页查看已有历史证据。D1B真实原生对话框自动化证据保持；用户确认同库读回一致、修改v4及微软拼音，详见[体验结果§20](docs/bootstrap/desktop-d1-result.md#20-d1-教师流程与实际-ime-体验2026-10-17)。R18新DOCX结构和Word属性已核对，新样本两页PDF完整目视通过；用户已确认新Word正常，Codex已补看v4完整两页；用户又逐页确认长园所2页、合并7页、三计划起始页1／4／6及署名和表格粗细正常。完整页面补验按用户人工反馈记录，不把38张局部截图写成38页完整目视通过。T7本轮人工取消／重试／Word打开已由用户反馈正常，实际两日导出文件已核对；T6-A／T6-B已通过，配置v4、新旧表头、两份单日文件和正常退出均已核对；微软拼音按用户反馈正常，不再复验或要求覆盖所有输入法，见[体验收口§20.8](docs/bootstrap/desktop-d1-result.md#208-t6-b核对与本轮教师体验收口2026-10-17)。干净机器、Win10、WPS、其他DPI和部分窗口分支仍未验。此前43个缓存来源DLL未再收集，55个二进制／扩展条目来源证据保持，干净构建／发行再现性仍未验。D1产品未整体验收。

## 当前入口

- [当前任务](docs/tasks/current.md)：W1–W6已完成当前Windows 11合成环境工程核查；[W6指定人工验收与三项后续事件](docs/bootstrap/desktop-d2-w6-closeout.md)按2026-10-20用户决定收口，Word单日2页／合并4页、候选采用／手改／重启与在途关闭等子项通过。跨120秒睡眠不再验证，白屏等复发，额外任务用户倾向误点、保留观察；真实AI与完整产品／发行仍未通过。下一步建议先把R01修复整合进新的普通运行验证包，再准备另获授权的G17真实AI验收；本次只提交／推送，不启动后续构建或调用。
- [D1 实施规格](docs/specs/desktop-manual-daily-plan.md)、[Codex 技术核查](docs/bootstrap/desktop-d1-technical-review.md)。
- [D0 独立审阅](docs/bootstrap/desktop-d0-review.md)、[实施结果](docs/bootstrap/desktop-d0-result.md)：缺陷、实际证据与未验边界。
- [D0 规格与后续顺序](docs/specs/desktop-foundation-plan.md)：验证内容、验收门槛及 D1–D4 边界。
- [实施状态与待办](docs/bootstrap/architecture-v2-readiness.md)、[文档与证据索引](docs/bootstrap/README.md)。
- [有效架构](ARCHITECTURE.md)、[本地应用决策 ADR 0004](docs/adr/0004-local-desktop-architecture-proposal.md)。
- [协作约束](AGENTS.md)：产品决定、角色分工、环境与文档规则。

## 开发与协作

以 Windows 11 原生开发为主，在 Windows 本机 VS Code／终端运行 OpenCode，桌面 Codex 负责技术核查、规划设计、审阅、相关验证与 Git／发布管理；实现代码、测试、迁移和构建打包脚本由 OpenCode 唯一写入。操作范围以用户当前授权为准。

WSL 可作独立辅助；不与 Windows 共用 `.venv`、`node_modules` 或运行中的数据库。`frontend/` 使用 npm 与 `package-lock.json`；D1采用独立 `desktop/.venv-d1` 和 `desktop/requirements-d1.lock.txt`，backend业务声明／锁保持，运行时记录见[实施结果 §11](docs/bootstrap/desktop-d1-result.md#11-d1b-实施记录2026-10-14-开始)。不能把 `requires-python>=3.12` 解释为任意较新版本均已通过。

桌面验证命令见 [D0 实施结果](docs/bootstrap/desktop-d0-result.md)，须同时读取最新独立审阅：第三轮最新包已有当前开发机仓外运行证据，早期包策略拦截保留为历史；这些不是 D1 新包或已验收产品的运行说明。现有 v1 MySQL 连接、迁移、登录与远程服务器步骤不能直接作为本地版启动说明；不得仅更换连接串便宣称 SQLite 适配完成。

## 验收与历史证据

实现、自动测试与产品验收分开记录。D0 必须取得真实 Windows 窗口、关闭退出、SQLite 重启持久化、保存对话框及测试包运行证据；Word／WPS 实际打开和逐页检查不能由编译、单元测试或 OOXML 检查替代。

v1 的 I1–I4、I5 已实现 Word 链路与 AI 1A–1C 记录继续保留。[I5 收口](docs/bootstrap/i5-final-closeout-2026-10-03.md)不包含完整 W6 非空材料；[AI 1C C5 v2](docs/bootstrap/ai-slice1c-fixture-c5-windows-result-2026-10-07.md)于 2026-10-07 20:50 通过主流程和真实提交窗口检查，V1/U3、v3 与 C7 密钥故障场景仍未验。这些结果不等于桌面版通过，旧远程任务不自动续跑。

任务完成或被替代后，将独有决定和剩余事项归并到规格或结果记录，清理旧提示词并修复引用，历史由 Git 保留。当前执行提示词只维护 `docs/tasks/current.md`。
