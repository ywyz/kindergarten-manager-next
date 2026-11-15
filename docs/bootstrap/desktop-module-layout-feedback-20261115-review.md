# 2026-11-15 教师截图反馈修复与审核

## 当前状态与依据

四组原生实现、针对性返修和独立复核已完成；本轮基线 `dev/0.1`／`9d8d4669c025ed8896fb98fd402b5592b4e5e299`，起点干净。教师指出首轮工作台、生成按钮位置、列表／编辑页选型和右侧操作栏与样稿不符；首轮自动检查不能替代此项视觉验收。

用户提供 14 张截图，并在澄清中再次确认工作台首页仅显示个人待办。本轮按[页面级规格](../specs/desktop-module-layouts.md)执行；明确文字优先于截图的冲突示意，截图可见结构优先于其中旧“记下选型”状态。原 PNG 按编号和用途复制到 ignored `local-evidence/module-layout-feedback-20261115/references/` 并校验哈希，未编辑原图；同处保留两份原样稿 HTML，只读参照样式，不运行其假业务。

## 互斥责任

全部路径相对 `frontend/src/d1/`。正式文档／Git 归 Codex；实现者不得 fork、另派子代理或改其他组文件。每组原会话同模型续接，不继承已经结束的任务指令。

| 组 | 工具与会话 | 独占写入范围 | 图片 |
| --- | --- | --- | --- |
| A 日计划 | OpenCode `ses_e2214b0d0ffeJ1KQaDLVxEm9M9` | `views/EditorView.vue`、`views/AiTaskPanel.vue`、`views/CandidatePreview.vue`；daily-layout-*、daily-feedback-*；d1.daily-*、d1.day-draft、d1.w5、d1.reflection27、d1.process-compare 测试 | 图 1 仅视觉参考；按钮位置按明确文字 |
| B 周计划／观察 | OpenCode `ses_e22148a13ffeTF7E8EgbDSoyCR` | `views/Weekly*.vue`、`views/Observation*.vue`、`views/ObservationsView.vue`；d1.weekly-*、d1.observation 测试；weekly-layout-*／observation-layout-*／weekly-feedback-*／observation-feedback-* | 图 2–5 |
| C 倾听／课程 | Command Code `b4c81c16-6f9e-4afa-a454-220869bb4d96` | `views/Listening*.vue`、`components/Listening*.vue`、`views/Curriculum*.vue`；d1.listening-*／d1.curriculum* 测试；listening-layout-*／curriculum-layout-*／listening-feedback-*／curriculum-feedback-* | 图 6–8 |
| D 导航／其余页 | Command Code `f4f96da9-4209-4175-b322-5a9bf6f8e855` | App.vue、theme.css、views/Workbench*.vue、views/SettingsView.vue、views/SetupView.vue、views/CollaborationPanel.vue、views/BackupRestorePanel.vue、views/UpdatePanel.vue、views/AiSettingsPanel.vue、views/GameConfigPanel.vue、views/HistoryPanel.vue；原 shell/workbench/todos/theme/backup/update/components/collaboration/game-config/prompt-admin 测试；shell-layout-*／shell-feedback-* | 图 1、9–14 |

A／B 使用 `opencode-go/deepseek-v4.1-flash#max`；C／D 使用 `deepseek/deepseek-v4.1-flash`、effort max。首轮日志已确认 A 读取 1 张、B 读取 4 张 PNG 均返回 Image read successfully；C 用单文件 read_file 读取 3 张，D 读取 7 张，并出现之后的模型响应；A／B／C／D 均已写入逐图可见内容记录。图 1 被 A／D 共用，因此合计 15 次读取覆盖 14 张原图。C／D 首轮完成事件均为指定模型／max，无 hook 阻断；最终全量模型、退出状态和视觉复核见末节。原生工具实际读图不等于最终页面符合，仍由 Codex 逐页审核。

D 另获本轮 ignored 验证辅助文件责任：`local-evidence/module-layout-feedback-20261115/prepare-source-smoke.py` 与 `open-source-smoke.ps1`。仅可为 `build/module-layout-feedback-20261115/synthetic-review` 新根准备合成记录、独立凭据与父／子进程网络守卫；编写完成后由 Codex 审核再运行。原审核环境及旧轮合成根不初始化、不覆盖。共享构建等待四组产品代码停止修改。

## 验收重点

逐页对照主内容与操作栏的真实位置、目录／卡片／表格几何关系、按钮尺寸和间距，而非仅查标签存在。全部正文完整可读，弹窗副本、取消／填回、选段修改、冻结／输入法等待、异步身份保护、保存失败和离开／关闭继续通过。观察选择顺序／合册、倾听图片组及每组记录、周计划游戏／重点区域、课程原稿／调整／二次稿不得遗漏。

实际界面验证将使用合成新根；不从教师真实 AI 发请求，不初始化原审核库。自动、源码 UI、Word、真实 AI 和教师验收分别记录。审核通过后正常推送 dev/0.1，再复用原入口留窗；暂不打包、签名、发行、合并 main。

## 审核中的针对性风险

Codex 基线检查发现：App 在工作台内调用 showDailyPlan 的旧路径未经过 LeaveCoordinator，Workbench.showPanel 只检查冻结，旧 shell-layout-app 用例甚至期待待办脏弹窗期间切到 daily 成功。新导航不能继承此绕过；D 本轮必须覆盖待办脏副本／组合输入时留在原页，取消后才能切日计划。此时实现仍在进行，记录为审核目标，不提前认定最终代码仍有缺陷。

进行中快照的独立审核已得到以下具体反例，写入对应原生会话的第二轮退回文件；等待当前实现自然结束后续接，不打断在途写入。以下尚非修复完成结论：

- B：周计划草稿 v5 首次确认得到确认序号 v1；两者为独立序列，不能用数值大小判断“有更新草稿”。观察候选详情读取失败时新模态框缺少可达关闭入口；未知采用回执／已采用但正文读取失败的恢复按钮仍在遮罩外，导致无法恢复。
- C：健康领域选段可被语言领域右栏沿用；健康图片组 ID 可在切到语言后进入无效请求范围，出现“第 0 组”。此外主阅读区和操作栏的 DOM／网格顺序相反，宽屏会让操作栏占左侧宽列。
- D：日计划“返回月历”仍回到不带 daily 参数的工作台，落入新默认个人待办。在线协作改版删去三处定位标记，但离开保护的聚焦选择器仍指向旧标记。

该阶段真实组件探针已确认待办脏副本／组合输入阻止切到日计划、取消后可以切换；设置 AI／游戏配置使用 v-show 保留实例。当时尚须停写后复核与实窗验证；最终结果见后节。

## 分组复核进度

C 两轮原生实现自然退出 0 后停止写入。独立复跑跨域旧选段、非法旧组、合法当前域／组的整栏和选段修改、取消后的选段失效，均符合保护预期，探针全程 0 PATCH。实际模板节点及网格规则确认主表左列、操作右列，窄窗主表在前；4 个 C SFC 的 parse／script／template 编译通过。独立检查倾听布局 13、课程布局 13、倾听 AI UI 35、多项采用 13、课程 23 项通过，8 份 C 差异的既有保护断言未削弱。此为该阶段源码／自动复核通过；后来实窗发现并返修的卡片内边距另记于后节。

A 第二轮产品返修通过独立复验：4 个回归文件 39 项退出 0，迟到失败在当前栏目不变时仍于左侧可见；未知提交只显示一组查询／同请求重试，查询不发 POST，显式重试保留完整原请求。独立隔离探针的原 8 项拆分自动适龄断言全部通过，但因该探针遗留轮询计时器而主动停止，只记断言通过、不记进程退出 0。W5 全套的实际退出 1 已独立定位到旧 fake DOM 没有 style，不能执行真实 v-show；仅在内存探针补足 style 后，三个原 Settings mounted 用例全部通过，产品未改。第三轮 A 只补 W5 节点 style 和独立克隆支持，原业务断言未改；自然退出 0，并直接跑完整 W5 115 项退出 0。所有产品停写后的 Codex 最终统一检查也包含完整 W5，实际退出 0；该结果不覆盖或抹去上述早期失败和主动停止的探针身份。

D 第二轮自然退出 0 后，已审核产品的 12 个 SHA-256 全部与独立审核时相同。导航 6＋工作台 10 项及真实 LeaveCoordinator 反例通过；设置 7、面板 5、公共组件 88、备份 UI 20、更新 27 项通过。协作三处状态定位和被冻结的来源／目标字段恢复，设置子实例保留；此轮源码审核收口，当时实窗待验；完成结果见后节。

B 第二轮修正了周计划版本序号误比。候选恢复 inline 后，读取失败不锁住主表；真实按钮事件验证未知采用的查询、同请求重试及已提交后正文重读通过。第二轮最终复核仍发现只有一个候选时，重复选择同值不会触发下拉 change，测试直接调用内部函数并不能证明教师可重试，因此第三轮仅退回观察编辑页和相关测试。

B 第三轮已补齐可达的「重试读取」和「关闭候选」入口，详情读取的 loading／error 由同一读取流程管理。新增真实渲染按钮事件用例：单候选详情 GET 500 后点击重试发起第二次 GET，恢复 inline 候选及审阅复选框，主表仍可编辑且无模态遮罩；读取中重复点击禁用，关闭仍可用，迟到响应不能重新打开已关闭候选。重试只读详情，不重发采用或 AI 任务；观察 ID、候选 ID、打开状态、请求序号和组件存活共同约束响应。原未知采用与提交后正文重读恢复用例保留。实现者记录为观察 83、观察布局 20、反馈 3 项及类型检查退出 0；Codex 后续最终 51 文件统一检查亦包含这三份测试，均退出 0，单候选真实控件重试闭环已纳入最终源码验证。证据为 ignored `B-notes.md` 和 `final-test-results.json`，不代替实际窗口验收。

## 统一检查与合成环境

第三轮观察重试入口返修前，Codex 执行全部 51 个前端测试文件，51／51 退出 0；类型检查退出 0。检查前后 169 个前端文件哈希不变，证据为 `unified-test-summary.json` 与 `frontend-source-freeze-before-tests.json`。此身份早于最后一处观察重试修改，最终源码另做核验，不把此记录冒充后续源码的结果。

B 第三轮返修完成、所有产品作者停写后，Codex 对最终源码重新执行全部 51 个前端测试文件，51／51 退出 0，无失败；检查前后 169 个源文件哈希不变。逐文件退出状态见 ignored `local-evidence/module-layout-feedback-20261115/final-test-results.json`，汇总及源文件冻结核对见同目录 `final-test-summary.json`。返修后的类型检查退出 0，确切退出证据为 `typecheck-after-retry-exit.txt`。这轮结果对应最后一处观察详情重试修改后的源码，与前一轮检查明确区分。

D 第四轮在停止产品写入后执行 `npm run build:d1 -- --outDir ../build/module-layout-feedback-20261115/frontend`，退出 0；目标构建目录事前不存在，完成时间为 2026-11-15 18:49:41（UTC+8）。构建前后 169 个源文件不变，共生成 3 个产物文件。Codex 独立复核确认构建源码与最终测试冻结一致、3 个产物哈希与清单一致、入口引用有效，证据为 `build-result.json` 与 `build-independent-check.json`。此为本轮源码构建与静态产物核验，不是安装包、原生窗口或教师验收结果。

合成辅助文件经路径、网络、服务签名／字段和事务审核后，于 2026-11-15 18:32 首次准备成功，未留下失败初始化根：日计划 1、周计划 2、观察 2、倾听 2／照片 4、课程审议 1；15 个合成文件有哈希清单。父／实际 Python 子进程守卫通过，准备阶段 attempts 与 logged_attempts 均 0，audit_ok 为 true；凭据文件 0、供应商配置为空。stderr 为 0 字节。业务运行时构造前已安装守卫，未访问原教师库或凭据。

准备前审核发现倾听月份误用完整日期，实施者改为 YYYY-MM 后纯校验通过；辅助 manifest 原称已种入反思实际实施材料也已改为 false，因为该字段是编辑器会话内存，不能把活动准备冒称反思材料。原 stdout 为本机 GB18030 编码，另存 UTF-8 解析副本，原始证据保留。这不属于数据库准备失败。

上述 D4 产物实际窗口检查发现两处纯样式问题，不能把 D4 自动通过等同于最终视觉通过。B 第四轮为周计划目录按钮增加 `flex: 0 0 auto`，避免列布局在限制高度下压缩按钮、使说明和版本状态越界；删除此唯一 CSS 块后逐字节还原 B3 产品。C 第三轮把倾听外层卡片 body 清零限定到直接子元素，并为内层记录／合册卡片明确恢复背景及 `16px 18px` 内边距，避免父级深度选择器穿透。两组自然退出 0，独立源码复核与相关布局检查通过。D 随后保留首个构建并生成 `frontend-final`，最终自动与实窗证据见后节。

## 合成源码窗口检查

2026-11-15 18:50 起，用经审查的隔离入口打开 D4 构建，标题明确带「截图反馈合成界面验证」。通过 Windows 原生窗口操作核对，未调用真实应用 AI，也未执行导出、备份替换、下载或安装。

- 工作台浅色／暗色均只显示个人待办，顶部单排模块按钮、个人待办选中状态正确。合成新待办填回后跨日计划／待办切换保留，显式保存成功；这不是脏弹窗离开保护的替代证据，后者由真实组件自动检查验证。
- 日计划保留月历／学期／历史；打开 11 月 17 日计划，正文默认阅读，四个生成入口确在左侧「一日反思」下方，滚动可达。反思与实施材料弹窗完整，取消后原文保留；材料为空不冒称已准备。返回日历实际进入日计划页。
- 周计划两张概览卡片可打开左目录编辑页；主题及每日活动弹窗保留日期和覆盖内容。首个构建目录文字越界已退回 B；长弹窗底部按钮在滚动区外时，UI 自动点击失败，改用可见标题关闭按钮正常取消，未记成产品保存失败。
- 观察列表为概览卡片，编辑为主表＋右操作栏；目标、记录、策略及五领域全文换行。实际修改弹窗中的合成正文后取消，阅读区仍为原文。无照片时生成入口依既有规则禁用。
- 倾听列表为记录／合册概览卡片，内边距问题已退回 C。编辑的语言领域为主表＋右栏，照片顺序、作品日期、每组完整记录及「2 张有效照片」范围可见；组弹窗取消保持草稿。
- 课程审议原稿、基本信息、原稿／调整各列与右操作栏可读，基本信息弹窗字段齐全。约 752×813 的较窄窗口中主表先于操作栏，弹窗单列并内部滚动、取消／填回按钮可见。课程列表保留横向表格，不能写成所有表格在窄窗无横向滚动。
- 在线协作仅验证未连接界面的三页按钮、主表和右栏；未连接时升班／同步按规则禁用，已连接的来源／目标与确认状态由合成自动检查覆盖，不记为真实联调。
- 设置的姓名班级、学期日历、AI、游戏、备份更新页面切换正常，默认阅读及资料副本弹窗可用。备份与应用更新弹窗均为状态表＋右操作栏；未执行维护或安装。AI 设置显示空配置／未保存密钥。

该合成窗口已在课程「已保存」且无弹窗状态下通过正常关闭退出，未强杀。

19:15 使用 `-Final` 打开同一合成库，先前保存的待办仍在；实际周计划目录的说明／版本状态全部留在按钮边界内，倾听记录和合册卡片内边距、背景正常。修前与修后实际截图分别保存在 ignored `weekly-nav-overflow-source.png`／`weekly-nav-final-source.png`、`listening-card-padding-source.png`／`listening-cards-final-source.png`。这不是重新种库后的伪保留验证。

19:16 使用 `-Setup -Final` 打开独立空 setup 根，实际检查浅色首次设置的教师班级／学期主表、右侧完成设置／备份恢复入口，以及姓名／园所／年级／班号弹窗。取消后仍未填写，未提交初始化。两个最终合成窗口均正常关闭，重新枚举确认已退出；原教师环境未重建。

三次 UI 的 stderr 均为 0 字节；每次启动各有 1 次 `api.github.com` 域名解析被守卫拦截，共 3 次，不能将准备阶段的 0 尝试沿用到运行阶段。四次实际 Python 子进程守卫自测均有通过证据，无 failure 文件。关闭后未保存内存 audit_ok／计数，不把守卫日志等同于系统抓包。

合成主库和 setup 库的 AI tasks／executions／attempts／inputs／candidates／operations、供应商配置、AI 凭据行及凭据文件均为 0。主库 profile／Todo／Todo operation 各 1；setup 均 0。主库保留合成 AI state 1、daily provenance 1，不误称所有 AI 关联表为空。统计查询前后主 DB 哈希相同；最初只读 schema 查询产生的空 WAL／SHM 协调文件保留，未执行写 SQL，后续用 `mode=ro&immutable=1` 统计。详见 `source-ui-runtime-audit.json`。

## 最终源码验证与交付门禁

- B4／C3 视觉返修后的 51 个 D1 测试各以独立 Node 进程退出 0，失败、超时、重跑均为 0；现有 `npm run typecheck` 退出 0。169 文件／4,836,565 字节前后不变，源码集合 SHA-256 为 `b08fa8b8e4345c9af9d1b711ac7fba2880d37381a3ce43b35fff62be8e00eb66`。证据为 `after-visual-test-summary.json`／`after-visual-test-results.json`；D0 bridge 不在本次 D1 范围。
- D5 正常构建退出 0，目标 `build/module-layout-feedback-20261115/frontend-final` 事前不存在；保留 D4 产物。3 个产物共 2,517,493 字节，入口 SHA-256 `8b65da3223a5bd1f33eb34882adde2b2c73c8976997feb2c6b2955603dc8eec7`，资源为 `index-Cv0i7MwO.css` 与 `index-XQjvkl7F.js`。独立复核源码冻结、每个产物哈希和入口引用均一致，见 `build-final2-independent-check.json`。只有既有 Vite 大 chunk 提示，未为此升级或重构依赖。
- final 辅助入口的默认 prepare 和 marker 仍验证原 `frontend` 身份，final 仅选择固定 `frontend-final`；`--prepare --final` 明确拒绝。旧 helper 副本保留，父子网络守卫、路径与 reparse、空 setup 根等保护经独立差异审核及分派探针通过。
- 原生元数据终审：A 3／3、B 4／4、C 3／3、D 5／5 自然退出 0。A／B 本轮 387 条 assistant 模型记录与 C／D 432 次完成事件全部为指定 DeepSeek V4.1 Flash／max，hook 拒绝 0；9 次普通匹配／陈旧读取／路径工具错误单列保留。B4／C3 实际读取了问题截图。见 `native-model-audit-final.json`。

提交前，原教师窗口已不存在；只读任务状态为 succeeded 8、failed 1、活动任务 0，没有自动恢复真实 AI 的在途任务。教师数据库已在本轮工作期间变化，因此资源更新以新的保护快照比较，未回写开始时的旧库。

## 提交推送与原环境留窗

原 OpenCode A 按 Codex `commit-gate.json` 的 40 个明确文件、Git blob、父提交和 tree 门禁执行普通提交，未 add-all、amend、rebase 或 force：

- 源码提交：`2f68af555ffcd52f4a82269648843d900ea9ec5c`，父为 `9d8d4669c025ed8896fb98fd402b5592b4e5e299`，tree 为 `c97750e9848498f911958eb9fedff4065207e86c`。
- 普通 push 退出 0，Codex 独立读取 `origin/dev/0.1` 确认同一提交，工作区干净。此后才执行原审核资源更新，次序见 `commit-result.json`／`original-review-asset-update.json`。
- 固定目标 `build/daily-split-20261115/frontend`：先复制并核验两个带哈希名的资源，最后替换 `d1.html`。旧资源保留，旧入口和 stdout／stderr 另存 ignored 证据；未递归删除任何目录。资源哈希与 D5 构建清单一致。
- 更新前重新枚举确认无原教师窗口；保护快照包含 data／credentials 的全部文件及原两个 launcher。复制前后全部一致。使用原 `%LOCALAPPDATA%/KindergartenManagerSourceReview/open-review.ps1`、原 Python 3.14.10 环境和 `source_review.py` 启动，未初始化、未强杀窗口、未改 launcher。
- 2026-11-15 19:24 已观察「幼儿园信息管理系统 · 源码隔离审核」新首页，仅个人待办、顶部单排模块按钮，保留原档案。窗口留给教师审核；原环境 stderr 0 字节。启动后主 DB SHA-256 仍为 `25be4f30aaa80645402cfc2a59bd5030cabc09ed610627952e6b2a2dbc2df0aa`，凭据哈希不变；AI 配置版本与凭据行各 1，任务仍为 succeeded 8／failed 1，无新增任务，未点击任何 AI 操作。只查询聚合元数据，不读取密钥或真实正文。详见 `original-review-handoff.json`。

本节为交付后的文档补记，另作普通文档提交推送；不改变已验证的产品源码和构建。

教师验收仍待后续实际使用反馈；本轮未执行真实应用 AI、Word 实际打开或安装包验收。已连接协作的真实网络联调、Win10／WPS／干净机和其它显示条件不以本次合成源码窗口代替。
