# 左侧导航与工作台日历反馈审核

2026-11-15；起点 `dev/0.1` / `a47cbca933fe8556a45e4b7177a90229d769489a`，工作区干净。此轮接续[截图修复结果](desktop-module-layout-feedback-20261115-review.md)，新教师反馈覆盖此前首页只显示待办及顶部导航要求；既有结果仍是历史证据，不移作本轮通过结论。

## 要求与互斥责任

工作台为日历和未完成待办，个人待办为完整管理；全部模块／页面／栏目导航移左；倾听批量选照片移到 AI 协助填写上方；修复原源码审核入口缺少协作地址。数据选择、业务草稿与所有既有保存、AI、导出规则保留。

| 原生责任 | 可写范围 |
| --- | --- |
| A / OpenCode | `EditorView.vue`、`WeeklyPlanEditorView.vue`、`d1.daily-layout.test.mjs`、`weekly-layout-sections.test.mjs`、新 `sidebar-plans*.test.mjs`；最终 Git 另给具体门禁 |
| B / OpenCode | `WorkbenchView.vue`、新 `WorkbenchHomePanel.vue`、`workbench-calendar*` 数据／helper／测试、`d1.workbench.test.mjs`、新 `workbench-home*.test.mjs`、`frontend/scripts/generate-workbench-calendar.mjs` |
| C / Command Code | `ListeningEditorView.vue`、`d1.listening-layout.test.mjs`、新 `sidebar-listening*.test.mjs` |
| D / Command Code | `App.vue`、`theme.css`、`SettingsView.vue`、`CollaborationPanel.vue`、`d1.shell-*.test.mjs`、`shell-layout-*.test.mjs`、`d1.components.test.mjs`、`d1.w5.test.mjs`、`d1.theme.test.mjs`、`d1.collaboration-stage2.test.mjs`、新 `sidebar-shell*.test.mjs`；ignored 入口候选／验证和新合成 UI helper；构建另给门禁 |
| Codex | 当前任务、正式规格、本结果；独立源码审核、运行检查与 UI 验证，问题退回所属实现者 |

未列文件只读。不得并改、还原他方修改、fork／再派原生实现代理；只用 DeepSeek V4.1 Flash / max。所有相对产品路径在 `frontend/src/d1/` 下（明确 scripts 除外）。新证据根 `local-evidence/sidebar-calendar-feedback-20261115/`，构建／合成根 `build/sidebar-calendar-feedback-20261115/`；不覆盖旧证据。

交界合同：子页面可选 `navigationTarget?: string`，只把现有导航及对应日计划生成按钮 Teleport 到 App 的稳定 `#d1-page-navigation`，独立挂载时本地左栏回退。设置与协作保持挂载，由 D 显式传导航可见性，避免 hidden 祖先失效。Workbench `panel: home|todos|daily`，默认 home，新增 `open-todos` 事件；App 切换各页必须经过原离开保护。

20:01 范围核对发现 A 在原白名单之外临时补写 `daily-layout-ui.test.mjs` 的挂载探针。该文件无人并改，随后 A 自行恢复为 HEAD，将验证放入授权的新 `sidebar-plans-daily.test.mjs`；最终旧文件未变。记录此过程偏差，不将其写成事前批准。B、D 又误用了公共占位名 `OWNER-notes.md`；已保留原运行日志及分别导出的首轮报告，后续明确使用 `B-notes.md`／`D-notes.md`，产品文件未并改。

## 日历与协作依据

工作台日历独立于持久化教学日安排，不改学期日历、开课资格或历史计划。农历与节气离线数据来自[香港天文台 1901–2100 对照表](https://www.hko.gov.hk/tc/gts/time/conversion1_text.htm)，生成过程核对逐日连续性、农历月份边界和每年 24 个节气并留来源摘要；不使用粗略常数公式冒充精确日期。节日名称与年度实际放假／调休分开。已知年度安排按[2026 通知](https://www.beijing.gov.cn/cs/gncs/zcwj/202603/t20260327_4568275.html)及[2027 通知](https://chinajob.mohrss.gov.cn/h5/c/2026-11-09/635850.shtml)；其他年份不推测调休，产品清楚标识未载入。运行时不为日历联网、不升级依赖。

首次实现原拟使用 Intl Chinese。独立只读探针在 Node v26.12.1／ICU 78.3 下发现 2027-02-06 至 03-07 的 30 天农历日序比官方年表晚一天，春节／除夕随之错误；2025、2026 逐日核对无差不代表所有年份准确。现改为官方农历快照，不能只补春节标签；此发现不外推未实测的 WebView2 运行库。另复现首页常驻跨午夜“今天”不刷新、月份输入 null 后无法通过下一月恢复，两项交 B 修复。200 年原文 73049 个连续日期、4800 个节气及 200 份缓存哈希已独立核对一致，待最终农历实现复核。

HKO 1901 文字表起始只有农历日序，不能虚称不存在的 1901 CSV 已核定月份。初始不完整月由[臺北市立天文科學教育館官方年表](https://tam.gov.taipei/News_Content.aspx?n=2D5F18609004C0CE&s=AC19298B0509F078&sms=3AABB000A3E78431)的 1900、1901 年 PDF 连续佐证：庚子年非闰十一月始于 1900-12-22，共 29 天，1901-01-01 为十一月十一，01-20 进入十二月；与 HKO 起始日序一致。记录此来源，后续完整月份由 HKO 年表接续。

协作根因：源码模式代理直接读取 `APP_COLLABORATION_API_ORIGIN`，原 `source_review.py` 未配置；安装包配置路径不适用于源码。公开健康接口 `https://manager-next.ywyz.tech/api/collaboration/health` 于 19:50:17（UTC+8）返回 200，默认 TLS 验证通过；仅证明存活，不代表兑换、数据库或班级联调通过。候选入口仅用 `setdefault` 补公开地址，保留显式空值／空白／自定义／非法值语义，保持 `APP_DISABLE_DOTENV=1`；不改代理全局默认。

## 状态与交付门槛

阶段性状态：A／C 首轮正常退出，日／周 SFC 的业务脚本只加导航目标，原生成链未改；Codex 独立日目录 3、周布局 22、日布局 6 项通过，前后 5 文件哈希一致。倾听 SFC 与原业务脚本（除新增 prop）等价，独立布局 16、AI UI 35、交互 14 项通过。B 首轮退回上述官方日期／时钟／空值／来源元数据问题，原生 B2 继续；D 首轮的设置／协作本地回退实际在正文上方，SSR 断言不足以证明左栏，已交 D2 修布局和动态挂载验证。

协作候选相较原入口 AST 仅增加公开 origin 的 setdefault；独立阻断 socket 的 5 环境矩阵通过，原 argv 和 dotenv=1 保持。代理回归 10 项通过。新 helper AST／编译、Python 9 分派探针、PS 解析及 4 参数探针通过；仅换新根／标题并加 5 条合成待办，父子守卫及原保护保持。

B2/B3 最终官方农历数据由另一 Codex 审核器独立解析：73049 个连续日期、2474 个区间内月首、73 个闰月、4800 个节气、200 份原文哈希一致；重新生成字节一致。权威缓存测试由 `HKO_CALENDAR_SOURCE_DIR` 显式启用，无缓存明确 skip，指定坏缓存失败，不把跳过记作通过。无效月份及年 0000 不改变当前有效月份；今日定时／聚焦刷新并在卸载时清理。D2 的设置和协作本地回退、目标切换、隐藏导航卸载由真实动态组件探针验证，原业务组件不因切页被重新挂载。

自动验证：56 个 D1 测试文件全部退出 0（本轮启用完整 HKO 缓存）、类型检查及 diff-check 通过；前后 180 个源码输入哈希不变，记录在 `final-test-results.json`。D3 使用既有依赖构建首份候选，Vite 大 chunk 警告保留，3 个产物与入口引用独立校验通过；没有重装或升级依赖。

20:50 新合成根准备成功：日计划 1、周计划 2、观察 2、倾听 2／照片 4、审议 1、待办 5（未完成 3、完成 1、归档 1），AI 配置／凭据／任务为 0；`local_ai_state` 的默认单例 1 属正常状态，首次校验误把它列入零计数后修正，未更改 fixture。15 个 fixture 文件均独立校验。20:51 启动合成窗口，实际观察首页摘要与完整待办／归档分离、日周左目录、倾听五领域及批量照片在 AI 上方、设置／协作切页无导航残留，以及观察、审议、备份入口。

实窗发现首候选 1166×813 下日历固定 560px 最小宽度裁切星期日，退回 B4；B4 只改首页包装容器、布局 CSS 及既有布局断言，脚本字节不变，13 项真实组件探针及 8 组首页回归和类型检查通过。采用实际内容宽度容器查询，日格保留完整 7 列。D4 新建 `frontend-final` 候选，180 个输入再次保持冻结；原候选保留。独立产物校验：JS `1526826B…BDD095`、CSS `B3A6A9BA…433D6`、入口 `F581EC68…972A29`（完整值见 `D4-independent-build-check.json`）。

21:04–21:06 第二候选源码 UI：1166×813 默认窗口周日不再裁切；746×813 窄窗明暗主题均保持左侧模块导航和完整七列日历，未完成待办自动落到日历下方。选择 2027-02-06 可见正月初一／春节／年度放假；02-05 除夕、02-04 立春、02-14 调休上班，日期详情完整。窄窗截图及默认窗口截图保存在本轮 ignored 证据根；不是教师实际验收。首次设置另启独立空合成根，首屏阅读表格与两个编辑／完成／恢复入口可见，未提交初始化。两个主窗口及首次设置窗口均正常关闭，无强杀。

原生模型记录最终覆盖 A1/B1/B2/B3/B4/C1/D1/D2/D3/D4：OpenCode 共 388 个当轮 assistant 模型记录，Command Code 共 168 次请求，均指定 DeepSeek V4.1 Flash / max、10/10 退出 0；run 消息无历史混入、无交叉重叠。显式工具错误 4、hook 拒绝 0、参数修复 6 分开记录，不把普通编辑失败当作审批拒绝；元数据审计不冒充逐条工具命令成功。Git 执行另留门禁与结果。

全部复核通过后正常提交推送，之后才更新原隔离前端及经审的单文件入口；原 `open-review.ps1` 字节保持、data／credentials／AI 配置保留，只正常关闭无未保存编辑的窗口。日历、导航仍使用新合成数据与网络守卫检查。

用户随后明确允许本轮使用真实 AI 和教师数据，并愿意提供所需资料；已请用户指定模块、资料及是否保存现有草稿。真实供应商验证走普通原审核 UI，待具体资料／保存范围明确后执行；本轮合成测试不因此改成真实 AI 通过，也不自动兑换或同步在线班级。

自动测试、源码 UI、真实 AI、Word 与教师实际验收分别记。Win10／WPS／干净机及既有未验不扩大结论；不打包、签名、发行或合并 main。
