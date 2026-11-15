# 2026-11-15 全模块界面版式初次实施与审核

> 后续教师反馈实际页面与样稿不一致，已进入[反馈修复轮](desktop-module-layout-feedback-20261115-review.md)。本页自动与源码检查保留原身份，不构成教师视觉验收通过；当前页面级要求以新版规格及当前任务为准。

## 结论与范围

已按[确认规格](../specs/desktop-module-layouts.md)完成全部十项模块版式、按钮导航和正文弹窗编辑。独立源码审核无剩余本轮阻断项，前端回归、类型／模板编译、独立 D1 构建及合成源码窗口抽查通过。教师实际验收待进行；源码 UI 抽查不等于全部业务组合、真实 AI 或 Word 的实测。

本轮从 `dev/0.1` 已推送基线 `26fa104013521c22b2194c0e5129d41b5560f85f` 开始，起点工作区干净，远端一致；日计划修复已经合并，没有重复合并。只调整桌面界面组织和直接相关交互，没有修改后端、迁移、公共 API／控制器、依赖或 Word 模板。源码已普通提交并推送，随后已更新原源码审核产物并留窗给教师；交付回执见末节。

不打包安装包、不签名、不上传发行、不合并 main；未自动发送应用真实 AI 请求。原隔离审核的 data、credentials 和 AI 配置保留。

## 互斥文件责任

各实现会话被告知不是唯一工作者，不还原他方修改，不 fork 或再派子代理。只可写下列范围；需扩围先向 Codex 说明。所有正式文档与 Git 由 Codex 负责。

| 责任 | 实现工具／选定模型 | 独占源码与测试范围 |
| --- | --- | --- |
| A 日计划 | OpenCode／`opencode-go/deepseek-v4.1-flash#max` | `views/EditorView.vue`、`views/AiTaskPanel.vue`、`views/CandidatePreview.vue`；`d1.daily-*.test.mjs`、`d1.w5.test.mjs`、`d1.reflection27.test.mjs`、`d1.process-compare.test.mjs`；新增 `daily-layout-*` 文件；复核轮补入唯一归 A 的 `d1.day-draft.test.mjs` 加载器维护 |
| B 周计划与观察 | OpenCode／`opencode-go/deepseek-v4.1-flash#max` | `views/Weekly*.vue`、`views/Observation*.vue`、`views/ObservationsView.vue`；`d1.weekly-*.test.mjs`、`d1.observation.test.mjs`；新增 `weekly-layout-*`／`observation-layout-*` 文件 |
| C 倾听与课程 | Command Code／`deepseek/deepseek-v4.1-flash` | `views/Listening*.vue`、`components/Listening*.vue`、`views/Curriculum*.vue`；`d1.listening-*.test.mjs`、`d1.curriculum*.test.mjs`；新增 `listening-layout-*`／`curriculum-layout-*` 文件 |
| D 公共导航与其余模块 | Command Code／`deepseek/deepseek-v4.1-flash` | `App.vue`、`theme.css`、`views/Workbench*.vue`、`views/SettingsView.vue`、`views/SetupView.vue`、`views/CollaborationPanel.vue`、`views/BackupRestorePanel.vue`、`views/UpdatePanel.vue`、`views/AiSettingsPanel.vue`、`views/GameConfigPanel.vue`、`views/HistoryPanel.vue`；对应 shell、workbench、todos、theme、backup、update、components、collaboration、game-config、prompt-admin 测试；新增 `shell-layout-*` 文件 |

表中路径均相对 `frontend/src/d1/`。公共 types、API、控制器与依赖默认只读，模块各用局部样式，不并行创建同一公共组件。D 是 App／共享样式唯一写入者。源码构建在实现停写后统一执行，构建输出用独立新根。

## 实现会话与实际模型

| 责任 | 原生会话 | 最终模型证据 | 轮次与结果 |
| --- | --- | --- | --- |
| A | `ses_e2214b0d0ffeJ1KQaDLVxEm9M9` | 导出 257 条 assistant metadata，全部 `opencode-go/deepseek-v4.1-flash`、variant `max`、agent `build` | 两轮退出 0，最终 `stop` |
| B | `ses_e22148a13ffeTF7E8EgbDSoyCR` | 导出 470 条 assistant metadata，全部同 A | 共四轮；第二轮 CLI 虽退出 0，实际尾部 `Transport: ECONNRESET`；同会话续接，第三／四轮退出 0、`stop` |
| C | `b4c81c16-6f9e-4afa-a454-220869bb4d96` | 四轮 180+88+18+4=290 条 `model_request_end`，全部 `deepseek/deepseek-v4.1-flash`／`max` | 首轮触及 180 回合上限退出 8；后三轮 `success/end_turn`、退出 0 |
| D | `f4f96da9-4209-4175-b322-5a9bf6f8e855` | 七轮 220+91+22+43+49+24+15=464 条 `model_request_end`，全部同 C | 首轮触及 220 回合上限退出 8；其余均 `success/end_turn`、退出 0；末轮只做 EOF 机械修正及最终构建 |

C／D 共 754 次模型完成事件，模型／effort 缺失或不符、start/end 数量差及非空模型错误字段均为 0。未调用 GLM 或其他开发模型。原生实现者未 fork／再派子代理；Codex 并行只读审核不写产品代码。全部首失败与续接日志保留在 ignored `local-evidence/module-layout-20261115/`，不提交原始会话或运行资料。

Command Code 首轮的 `--permission-mode yolo` 没有使 print 模式写文件／shell hook 生效，C／D 各保留 3 条 hook blocked；当时执行者用了仍可用的 PowerShell 工具。Codex 查阅本机帮助后续轮使用 `--yolo`，明确遇到 hook 阻断须报告、不得换工具绕行；后续 hook blocked 为 0。这是已授权写入的 CLI 调用兼容记录，不是追加产品权限。首轮各有 max_turns warning，非 JSON CLI banner 未误算为损坏的模型事件。

## 独立审核及交回修复

| 责任 | 独立发现、原实现者修正及复核结论 |
| --- | --- |
| A 日计划 | 修复未变化弹窗的组合输入未参与离开保护、等待后冻结仍填回、晨间非重点组展示目标／指导。真实组件 58 项及 3 个时序探针通过；历史非重点字段保留。反思候选读取前后均保护新输入，拆分后自动适龄和反思直接回填规则保留。`d1.day-draft` 只修测试加载器，原断言未改。 |
| B 周计划 | 恢复跟随晨谈／集体活动的手工修改；顶部三个 AI 入口可见原任务状态且不重复挂载；弹窗校验真实 `props.sessionEpoch`、记录／版本与精确正文签名，等待组合输入后重查冻结、身份及取消。21 项布局用例及额外交错探针通过。 |
| B 游戏观察 | 修复锁定／自动保存／待采用期间的弹窗填回及重点区域环境标签；五领域独立保留。19 项布局用例及 13 个交错探针通过。最终又修复“弹窗暂停自动保存→冻结时取消→解冻”未恢复计时；实际定时器探针证明解冻只恢复一次，弹窗仍开、仍冻结、卸载或锁定时不保存，取消副本文字不被保存。旧离开协调器已有组合输入等待，不把 `blockingDraft=null` 单独认定为离开丢字。 |
| C 倾听／课程 | 修复课程选段使用旧正文和失败提前填回、倾听等待期间冻结、课程冻结后错误关闭副本；补齐弹窗内明确填回后再修改入口、窄窗限制和原稿／调整／二次稿全文阅读。冻结、取消、版本变化、重复确定探针通过。课程布局 13 项、倾听布局 8 项、倾听多采用 13 项通过；过期栏目测试由无效 `goals` 改为真实 `goals_original`，没有削弱断言。 |
| D 公共及其余模块 | 修复 App 工作台 ref、待办跨档案填回、设置定位重置副本及冻结／组合输入保护，真实组件 16 项通过。独立模板编译另发现 Settings 多余闭合标签，即使类型检查已绿仍退回；已修复并增加模板回归。 |

B 首轮自测曾报告一次并发运行时 W5 时序断言失败；首失败保留，后续单独及统一运行均通过，W5 断言未修改。不将其未经独立证明地写为“既有问题”。最后 Git 空白检查发现 WorkbenchTodoPanel 多一空行，交 D 删除一个最终 CRLF（2 字节），没有业务改动；166 份其余前端文件哈希不变。

## 自动验证与构建

- Codex 顺序独立运行 `frontend/src/d1/*.test.mjs`：**50 个测试文件全部退出 0**，包括新增但未列入旧主脚本的布局测试。逐文件日志、耗时、哈希及退出码在 `independent-tests-1/results.json`。
- B 最终修正后再独立执行 **9 个受影响测试文件，全部退出 0**：components、observation、weekly-ui、weekly-ai-ui、weekly-core、weekly-ai-core、shell-weekly、weekly-layout-sections、observation-layout-sections；证据为 `independent-tests-final/results.json`。其中 observation 79 项、weekly-layout 21 项、observation-layout 19 项。
- 最终 `npm run typecheck` 退出 0；19 个修改过的 Vue SFC `parse`、`compileScript`、`compileTemplate` 无错误。最后 EOF 两字节修正仅为空白，由字节及哈希差异单独核实，无需重跑全部语义测试。`git diff --check` 通过。
- 本机现有 Node 26.12.1／npm 11.20.0／`desktop/.venv-d1` CPython 3.14.10；最终实际构建日志为 Vite 8.3.0。未安装或升级依赖。
- D 停写后独立执行 `npm run build:d1 -- --outDir ../build/module-layout-20261115/frontend-final`，退出 0。167 份前端源文件构建前后哈希相同，交付前再核对；产物 3 份、合计 2,475,279 字节。仅保留大于 500 kB 分块体积提示，不借机调整架构或依赖。

| 最终产物 | SHA-256 |
| --- | --- |
| `d1.html` | `08e010875126336bd8d33d0616a1b7702f793085605b0d54583f1f2a2ed0b969` |
| `assets/index-BKq-Z3s0.js` | `f0b85dedff5b91ca7f4ca2eb42823eeda31539f708c8a65ce883573f2a5cc5a8` |
| `assets/index-Cf7_k_7Q.css` | `759dabda58a6e7b7b8751af00c8276ea2733b1dcdc418332fa93f2a73b425070` |

首轮构建及其入口保留，最终产物另建新根。Codex 同步合成环境时最初把 `/assets/...` 当作磁盘绝对路径而拒绝，在任何复制前失败；修正 URL 路径解释后逐项核对产物哈希，先资源后入口更新，未删除首失败或旧资源。此为验证脚本首失败，不是产品运行故障。

## 合成源码界面抽查

D 独占编写 ignored 准备／启动 helper，Codex 审核 D1 入口、凭据目录创建、路径重解析边界及逐次 guard 后执行。新根 `build/module-layout-20261115/synthetic-review` 只含构造档案、长文本日计划及 UI 新建的周计划／观察／倾听记录；首次设置另用 `setup-data`、`setup-credentials`、`setup-localappdata`。没有使用教师业务库或凭据。父进程及实际子 Python 的网络守卫自检通过。

2026-11-15 16:39–17:03 通过本机 WebView2 源码窗口检查，日计划还覆盖亮／暗主题与应用最小外窗 760×560（截图客户区 746×553）。其余模块在常规或最大化窗口抽查，不宣称每个模块和每个显示条件的笛卡尔积均已检查。

| 模块 | 源码窗口实际观察 |
| --- | --- |
| 工作台 | 模块选中按钮、月份日历、日计划历史表格、个人待办表格；新建待办输入合成文字后取消，列表仍为空。 |
| 日计划 | 已存合成 2026-11-17 v1、七项目录、六字段阅读、原始长文本换行；暗色和最小尺寸下导航换行、正文可滚动、弹窗取消／确定均可达；取消不改原文。 |
| 周计划 | 预览后本地创建合成第 1 周 v1；九项目录、只读正文、独立游戏／栏目／材料 AI 按钮、来源／保存／历史／Word 入口。未点击生成。 |
| 游戏观察 | 创建公共区域合成 v1；七项目录、资料阅读、健康／语言／社会／科学／艺术五栏全部显示。 |
| 一对一倾听 | 合成姓名记录、五领域按钮、照片与倾听记录表格、星级／评价阅读；第一组弹窗、日期与正文及取消／填入草稿可见，取消后返回阅读。 |
| 课程审议 | 新草稿中的原稿／当前内容与调整结果表格、基本信息、活动目标／准备／过程、调整理由、二次稿均显示；生成入口醒目，空原稿时禁用。没有提交课程业务版本。 |
| 在线协作 | 未连接状态下四项左侧目录与清晰选中状态；未兑换、登录或创建远端资料。已连接状态仍由组件／源码复核覆盖，本轮未重跑远程联调。 |
| 设置 | 概览卡片、资料弹窗打开／取消，AI 与游戏配置只读摘要；未保存或清除教师配置。 |
| 备份恢复与更新 | 设置内状态表格和备份恢复维护弹窗表格可读；未创建备份、恢复、下载或安装。更新在守卫拦截既有检查后显示失败状态；未点击再次检查。 |
| 首次设置 | 独立空根的姓名班级／学期／准备卡片、姓名班级弹窗、年级班号数据选择保留；取消后仍为空，未完成初始化或恢复。 |

两个合成窗口均经标题栏正常关闭，没有强杀未保存窗口。常规窗口与首次设置窗口各在启动约 6 秒后，既有更新检查对 `api.github.com` 的一次 DNS 尝试被 guard 拦截，共两次；不能写成窗口期间外网尝试为零。无应用真实 AI 生成、候选请求或未知任务重发。两个启动的子进程自检均为 ready／blocked.invalid／B3_NETWORK_BLOCKED，stderr 均为 0 字节；guard 无其他 Python 业务外网尝试。只读 SQLite 聚合核对：常规档案 1，AI tasks／attempts／executions／inputs／candidates／operations／config_versions／credentials 均为 0；保留构造日计划 provenance 1、AI state 1，不能笼统称所有 AI 相关表为空。首次设置档案与上述任务／操作计数均为 0。读取前后两库 SHA-256 不变。

## Git 与原隔离审核交付

2026-11-15 17:07，42 个明确文件通过 parent／index blob／tree 门禁后普通提交并推送 `origin/dev/0.1`：

- 源码提交：`3804581227084807e0605519e8c8bd5a920974fc`。
- parent：`26fa104013521c22b2194c0e5129d41b5560f85f`；tree：`45267be141354d95ed82409de27350e2ad3ab602`。
- 每份暂存 blob 与对应工作区规范化内容一致，暂存路径精确为 39 份前端文件及 3 份正式文档；没有 add-all、amend、rebase 或 force。提交后远端同 SHA，工作区干净。逐文件 blob／SHA-256 在 ignored `git-staged-gate.json`。

17:08，在确认原审核窗口未运行、远端提交一致、167 份源文件及三份产物哈希再次通过后，更新固定 `build/daily-split-20261115/frontend`。先复制两个哈希资源，再替换 `d1.html`；旧资源保留，旧入口和原 stdout／stderr 复制到独立私有证据目录，无删除。最终入口及资源哈希与上表相同。

直接执行原 `%LOCALAPPDATA%/KindergartenManagerSourceReview/open-review.ps1`，启动器与 `source_review.py` 的 SHA-256 保持不变。继续原 `desktop/.venv-d1` Python、data、credentials、AI 配置与 `APP_DISABLE_DOTENV=1`；没有重新初始化或改用安装版业务库。

17:08–17:10，实际观察“幼儿园信息管理系统 · 源码隔离审核”窗口：新版八项模块按钮加载，原日计划历史表含 2026-11-13 v1 与 2026-11-17 v8。打开后者，左侧七项目录、集体活动六字段正文、生成／历史／Word 入口存在；打开“编辑本栏”后取消，无正文修改。最终保持该窗口打开，页面显示 v8、已同步，交由教师审核。

保护复核：启动前 data／credentials 的三份保护文件全部与开工指纹一致；运行后数据库和 DPAPI 凭据两份 SHA-256 仍一致。空的 `.app-runtime.lock` 正被运行进程独占，重新读取哈希触发 PermissionError 13；保留此验证失败记录，只核对其长度仍为 0，没有关闭程序或绕过锁。没有读取密钥正文。只读任务聚合仍为成功 8、失败 1，无新增、未知或待执行 AI 任务；原启动 stderr 为 0 字节。

本次交付回执以正常文档提交接续，不再改动已经冻结、构建并交付的产品源码。教师实际验收待反馈，不把留窗或源码抽查记为教师通过。

## 未验与验收边界

本轮不重新生成真实 AI、不重跑 Word 导出；日计划修复轮 Word 106 项及最近生成／提示 60 项只保留其历史身份，详见[日计划修复记录](daily-lesson-split-20261115-review.md)。本轮修改没有触碰 Word 导出实现或模板。

教师实际操作、真实 AI 质量及真实 Word 内容仍由教师审核；Win10／WPS／干净机、其他显示条件、历史睡眠／白屏、在线协作远程复测与发行相关未验不因本轮源码通过而消失。微软拼音与 W6 跨 120 秒睡眠未重新穷举或追测。没有把不追测写为修复，没有打包、签名、上传发行或合并 main。
