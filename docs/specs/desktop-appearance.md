# 桌面明暗模式切换规格与工程合同

更新：2026-11-01。明暗模式已确认并实施；独立主题／偏好／共享接线、完整回归、真实源码重开和备份恢复已核：明文恢复light，保护包及加密恢复dark，最后正常重开偏好保持。具体身份与未验见[实施核查](../bootstrap/desktop-weekly-plan-review.md)；新候选／目标条件／教师体验另验。唯一入口[current](../tasks/current.md)，责任与接口仍按[周计划工程](desktop-weekly-plan-engineering.md)。

## 1. 功能与默认选择

提供亮色／暗色两态手动切换，全局入口在应用壳中可见（有可读文字与键盘操作），首次页面及工作台／设置均可使用。沿用现有亮色作为初始默认；本次不扩展跟随系统、定时、多套自定义配色。

已建档时记住选择，完整退出后重开按档案内已保存主题恢复。尚未建档时仅当前窗口生效；完成初始化后可保存本窗口最后明确选择，不改变初始化业务参数／身份或制造未完成档案。初始化前关闭不会声称主题已持久化。

主题立即生效；保存失败保留本次视觉，给简短“选择未保存”提示和明确重试，不阻塞正文保存／关闭、不把主题变动标为业务dirty。不开AI请求、不写计划／观察版本或班级配置版本，不触发刷新／确认／导出。

仅网页界面换色，保持照片原色、编辑文字和Word／图片导出内容。Windows原生文件对话框、窗口标题栏和Word自身主题由系统／相应应用决定，不用关闭保护或改变系统主题实现本功能。

## 2. 持久化与API

实际桌面启动会选择空闲回环端口，不能把origin相关localStorage当跨重启权威。主题偏好放既有 `LocalSettings`，由A在**同一计划0007迁移**中加：`ui_theme` 非空light/dark、默认light及CHECK；`ui_theme_version` 严格正整数、默认1。外观更新只改这两个偏好列，不改config_version及业务settings更新时间；业务配置preview和周source hash也须排除主题字段。它不增加周计划工程的七张新表，也不额外产生0008迁移。迁移不改旧列、config_version／日历／游戏修订或旧行集。

A新增 `backend/app/local/appearance_service.py`，在现有 local_router 注册：

| 接口 | 合同 |
| --- | --- |
| GET `/api/local/appearance` | 已初始化、已鉴权会话；只读返回 `{mode:'light'|'dark',version:positive_int}`。 |
| PATCH `/api/local/appearance` | `{mode,expected_version}`，extra=forbid；短写事务／条件更新独立ui_theme_version，成功返回实际mode/version；旧version返回409及重新读取指引，不覆盖新选择。 |

未建档仍按既有规则返回LOCAL_PROFILE_REQUIRED，前端在context确认已建档后才读取／保存；首次页只在内存切换。新初始化context返回默认light也不能覆盖刚才的明确dark意图，先读取持久版本再保存该最后选择；不把偏好写失败报成档案初始化失败。网络／结果不明先GET核实真实值；相同目标已保存可据GET结束，不为主题增持久操作表，也不拿GET当原请求回执。

前端立即应用最后一次点击；同一profile/editor生命周期最多一个偏好写在途，合并等待中的后续选择。响应只更新对应持久版本，不把迟到响应的mode套回界面；冲突先GET，再仅为仍属同一profile/epoch的最新明确意图写入。档案恢复、初始化／context切换、退役后丢弃旧队列，读取新档案偏好，不能把旧请求写入新档案。

偏好API遵守现有维护／恢复拒写屏障；备份／恢复在途时可只做本窗口视觉切换并提示尚未保存，不绕过写屏障。恢复完成重读新context；不能自动把恢复前待保存偏好补写到恢复后的档案。偏好随全库备份／恢复保留，源0006副本向前升级默认light/1；新字段纳入backup schema／逻辑检查，不影响Word内容hash、周来源freshness或配置preview。

## 3. 界面实现边界

沿现有 Element Plus 2.14.6，实际安装存在 `element-plus/theme-chalk/dark/css-vars.css`。A在main.ts按原light CSS、官方dark变量、应用theme.css顺序接入；只切 `document.documentElement` 的dark class／color-scheme，用CSS变量覆盖应用色值，不安装VueUse、Sass或其它依赖。

新 `theme.ts` 提供纯mode状态／DOM应用及受控持久化controller，新 `theme.css` 定义应用背景、文字、边框、遮罩、状态／diff色；`components/ThemeToggle.vue` 只发明确切换事件。A在App.vue接全局入口、context生命周期，在设置中显示当前值；C不直接改这些共享文件。

Element Plus弹窗／下拉常teleport到body，因此用html.dark级变量，不能只在某个scoped容器变色。只改颜色token，不用整页filter/invert，不用theme作为Vue根key重建编辑器。保存、光标、选区、IME组合输入、展开折叠与任务状态应保持；启动态尽早读取偏好，避免稳定页面反复白闪，读取失败不阻断现有启动／业务。

覆盖首次页、工作台、日计划／观察／周计划编辑、设置、AI思考／候选／任务、历史／diff、Word选择、更新及备份恢复弹窗。文字、禁用态、选中态、错误／警告、红色差异在两态都需可辨；照片、画布／Word纸张预览保留本色，不把所有白色强制反转。

## 4. 四会话责任与阶段

仍使用既定A/B/C/D四个原生会话，不增第五实现者、不并行改同一文件。

- **A**：唯一models／0007／api／schemas／新appearance_service.py、backend/tests/local/test_appearance.py、备份配置整合；前端main.ts、App.vue、SettingsView.vue、WorkbenchView.vue接线及其色值替换；维护／恢复和context刷新。业务与主题共用文件均由A提交。
- **C**：在G1可独立实施新theme.ts、theme.css、components/ThemeToggle.vue、d1.theme.test.mjs。另独占以下既有views的**颜色样式修改**，不改业务逻辑／模板流程：EditorView.vue、ObservationEditorView.vue、ObservationsView.vue、CandidatePreview.vue、AiTaskPanel.vue、AiSettingsPanel.vue、GameConfigPanel.vue、HistoryPanel.vue、ExportDialog.vue、BackupRestorePanel.vue、UpdatePanel.vue。A不同时改这些文件；遇真实缺陷须暂停并重新明确唯一责任。
- **B**：周计划纯内容合同及反例不变，不接主题。
- **D**：周Word／宿主合同不变，G1仍只准备不冲突材料，不接主题或提前改模型。

G0四方核定新增appearance DTO／表字段、色值token和唯一责任后，G1为A数据／偏好、B纯内容、C独立主题前端并行；A等C模块冻结再接main／App／Settings等共享入口。G1主题接线可独立验证，周页面／Word仍须G1核心核查通过才G2；C完成主题停写交审核后转周专属页面。不能以主题为理由提前接未冻结的周API。

## 5. 验收与交回

| 场景 | 必须结果 |
| --- | --- |
| 两态切换 | 全局按钮可读、键盘可操作，弹窗／teleport与页面一致，状态和diff可辨；不反转照片或更改导出。 |
| 既有dirty稿与IME | 切换不重挂载、不清稿、不新增业务版本／确认／AI；既有离开／关闭规则不变。 |
| 快速切换／迟到响应／冲突 | 最后意图胜出，单请求队列，无旧mode回盖；版本冲突读取真实状态，不盲重试旧期望版本。 |
| 初始页／重启 | 未建档仅窗口状态，初始化后保存最后选择；已建档在不同回环端口重开仍读回正确偏好。 |
| 偏好写失败／不明 | 保留本次显示并告知未保存；不阻止正文保存或关闭；GET核实，不伪称原请求成功。 |
| 备份／恢复／维护 | 新字段往返保留，恢复／retire丢弃旧队列，维护拒写不绕过；旧0006升级默认light，不改旧值摘要。 |
| 回归 | 实际源码窗口覆盖日／观察／周、AI进度、历史、原生另存为与恢复弹窗；自动断言不能代替视觉检查。新包实证另按当时范围，r03不改。 |

上表是验收要求，实际通过范围另见实施核查。设计依据：[Element Plus Dark Mode](https://element-plus.org/en-US/guide/dark-mode.html)说明html.dark与CSS变量入口；锁定依赖已源读核对，未安装／升级。原设计codebase-memory代次2026-11-01T01:59:32Z，六路径metadata_changed并作源fallback；不据图谱无缺口断言完整兼容。
