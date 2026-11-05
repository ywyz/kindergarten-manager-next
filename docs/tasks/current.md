# 当前：0e51491测试机收口与来源核验回修

更新：2026-11-05。继续`codex/desktop-v2-foundation`，本文件是唯一执行入口。用户本轮要求拉取0e51491、按最新提示词在本机测试，并允许真实AI；缺配置先寻找隔离环境既有配置，再由用户填写。本机已普通快进到`0e514917db3998adea1acbb59922fdb59be2bca4`，tree `c7ecd84bc08c4647c6378587c253ca50a5b86f8c`；未改main。本机增量与后端新完整轮已完成，549个非Markdown文件前后相同。下一步交回开发机补修包级来源门及受管验证器观测问题，不把完整用例通过写成所有工程门或产品通过。

最新测试机结果与全部首现场归[独立核查§7](../bootstrap/desktop-windows11-white-concurrency-review.md#7-2026-11-050e51491原测试机增量)。开发机修复、两已知父历史普通merge及原1229／628结论保留[开发机核查](../bootstrap/desktop-regression-repair-review.md)自身身份；[恢复规格](../specs/desktop-renderer-recovery.md)已获用户明确确认，[生命周期核查](../bootstrap/desktop-renderer-lifecycle-review.md)保留cb4e7ed来源。旧测试机§6的“恢复待核定”不能撤销该决定，不重复询问同一手动重开行为。

## 1. 已完成的本机结果

- 前端14脚本／typecheck／D1构建、观察源码窗口17检查通过；桌面修正环境后的完整628项为627通过／1缺旧验证包skip、exit0。首轮623通过／4失败／1skip保留，B3 TEMP父子关系及U2同源前端的调用问题不误报生产缺陷。
- Page／Browser自有Core的两个新合成源码窗口完成保留后再次明确重开、票据与新port token拒绝、完整业务／资源指纹保持、正常退出及独立进程冷启动。原AI体验档案同机同用户可解密、无需重填，八组表散列不变、attempt仍1；本轮应用真实请求0。
- 后端新完整轮**1229通过、0失败／错误／跳过，exit0，2579.52秒**，包含视觉deadline及全部22项周执行器，JUnit与退出一致；549文件前后SHA相同。原首次完整轮在日志70%后中断，无JUnit／实际退出回执，1个失败标记及同源顺序映射单列，不写其根因已定位／已修复。新完整轮使用新TEMP内basetemp及标准`-vv`记录，无observer或断言／时限修改。
- 同HEAD自动CI run41855931829／attempt1的原ZIP、PS1、187产品文件及身份已核，前端3文件与本机原字节相同；这是Windows2022构建／静态证据。新包的两个生产恢复模块来源门有覆盖缺口，未执行新冻结EXE／helper／PS1，不能以源码窗口替代包内恢复通过。

## 2. 返回开发机后的最小回修范围

用户此前“返回开发机时提交推送”的授权继续用于本轮脱敏结果与唯一入口；结果已收口，由Codex审核准确文件／blob／parent／tree，再交原OpenCode普通提交推送。测试身份保持0e51491，本轮交付只改两份Markdown，不回填自身提交SHA循环改文档。不重放旧Git白名单、原双父merge授权或跨机session身份。

开发机先核实际目录、分支、HEAD／远端及本地差异，保留独有资料，再普通fetch与`git pull --ff-only origin codex/desktop-v2-foundation`。不能快进即停止同步报告，不能自动merge／rebase／force。读取§7后由原生OpenCode／Command Go固定DeepSeek V4.1 Flash max核精确互斥责任；Codex独占正式文档、独立验证及最终审核，不另起业务实现者、不覆盖他方修改。原生工具权限拒绝时保持原拒绝，不放宽或以shell绕过。

1. **包级来源门**：将`renderer_recovery.py`及`renderer_recovery_native.py`纳入构建前后source freeze、必要归档模块与production分类，保留现有来源及归档约束，验证缺失／改hash／漏模块会被拒绝。当前PYZ中存在二者仅证明存在，285文件匹配不覆盖二者源码。源码验证器未打包本身不是产品缺陷；若用于新包恢复证据，补相应verification来源，不强行变为产品归档模块，不添加产品调试开关。
2. **受管源码验证器**：修正`desktop/verify_renderer_recovery_window.py`两处活动host的`get_bootstrap()`观测调用。该产品接口正常创建新页面身份，不改其生产语义；验证器应锁内读取当前已绑定状态，保留真实旧票据拒绝与前后状态不变、新port旧401／新200、真实自有Core、完整指纹、独立进程及正常冷启动检查。不能把已完成私下副本当作受管入口已经修复。
3. **保留原中断失败的证据限制**：新完整1229项已通过，不在同源上无故反复全跑；原1个标记映射到视觉deadline节点，但无原轮详细堆栈／退出，不能写已修复。若同类再现，保留准确节点、stdout／JUnit及spawn／ready／permit／SEND／落盘时序，先定位最小前序影响再核最小回修；不以增加sleep／预算／重试／skip或串行化并发采用掩盖问题。

修复先按受影响节点和来源／归档反例独立复验，再按变更需要做相关全套与目标增量；新的代码／包分别记录完整SHA、tree、build_id／revision、原字节ZIP／PS1和来源范围。只认新HEAD对应可信成功run，不能以旧成功包替代、不自动dispatch／重跑或发行。

## 3. 配置保留、数据与验证边界

保留测试机原AI体验档案及独立凭据根，私下索引见已有ignored `private-evidence/`启动说明／路径配置。普通源码启动同机同Windows用户始终显式`--data`／`--credential-root`，不因pull新建空档案再索key。两根不作自动测试、主动故障、备份恢复或临时清理目标，不复制DPAPI、不读取／展示明文key。真实AI授权保持用户本轮明确范围；复验配置本身无需付费调用，不自动重发历史unknown。自动验证另用新合成根和适用守卫，守卫不证明原生WebView／OS全局隔离。

原生故障只用于核明归属的新合成源码窗口／Core，不全局kill、不真实关机／断电、不强杀绕过保存ack。正常保存关闭、忙拒绝、备份恢复、任务回执按[恢复规格](../specs/desktop-renderer-recovery.md)、[保存关闭合同](../specs/desktop-manual-daily-plan.md)、[备份规格](../specs/desktop-backup-restore.md)、[周AI工程](../specs/desktop-weekly-ai-engineering.md)及[矩阵](../specs/desktop-weekly-ai-validation.md)保持；新增产品行为仍须用户决定，不能以修验证器改教师流程。

使用现有CPython3.14.10 x64标准GIL与锁定依赖、禁dotenv／SQLAlchemy纯Python／禁pyc和新短TEMP，B3合成根必须在TEMP内且满足120字符限制；启动前先正常关原应用。源码U2合成helper不与冻结helper混称。SAC4551不执行受阻冻结包／helper，不换名换路径、修改来源标记、降低保护或执行策略来重试。不安装升级工具／Skill／MCP／依赖，不启动签名、安装更新、WebDAV、远控、tag／Release或公开发行。

真实原库／照片／凭据、旧包／Word／备份／保护包和原始首失败保留；只提交脱敏结果，不提交私下验证器、原始日志／数据／下载字节。原自然白屏触发、Word/r历史差异、Win10／WPS／其它显示条件／跨用户／长根206／symlink特权等未验保持；不重跑旧39项、13份43页Word、微软拼音或W6跨120秒睡眠，不/r／regserver／Office修复。不把工程或源码增量等同教师体验、冻结运行或产品整体验收。
