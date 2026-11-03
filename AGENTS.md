<!-- codebase-memory-mcp:start -->
For structural codebase exploration, use the installed `codebase-memory` skill.
<!-- codebase-memory-mcp:end -->

# kindergarten-manager-next

## 当前阶段与入口

2026-11-03：另机测试及指定Word／39项教师清单整体接受已[收口](docs/bootstrap/desktop-weekly-target-test-closeout.md)，不重复追验。文档先提交51ec4d3，Q5/Q6实现及限定审核已提交cd88d9d；旧档案／备份先行、真实游戏／材料生成采用、新候选54／59静态通过。本地桌面恢复后已补过材料采用／手改／保存／重进／确认、无执行器手工闭环及两次正常源码退出，见[实施结果§16](docs/bootstrap/desktop-weekly-ai-review.md)。下一步新包增量目标运行；本轮普通提交，不自动推送、签名或发行。

继续 `codex/desktop-v2-foundation`，业务源码基线0285a7c。唯一执行入口 [docs/tasks/current.md](docs/tasks/current.md)；Q5/Q6见[工程合同](docs/specs/desktop-weekly-ai-engineering.md)及[矩阵](docs/specs/desktop-weekly-ai-validation.md)，产品见[周计划](docs/specs/desktop-weekly-plan.md)，状态见[v2入口](docs/bootstrap/architecture-v2-readiness.md)。原包保持各自身份，新构建不继承旧运行／Word结论。

本轮原生A/B/C/D固定Flash max，按当前门及精确文件责任并行；Codex独占正式文档和最终审核。旧Git门禁／白名单不重放，通用保存、恢复、关闭缺陷优先；真实原库／照片／凭据与首失败现场保留，验证用合成资料。不启动WebDAV、签名、安装更新或发行。

## 产品与架构原则

这是clean-slate实现，旧kindergartenManager只作业务、模板、规则和历史经验参考，不因旧代码存在就复制迁移；复用须审查。产品行为由用户决定，不擅加需求、改教师流程、为技术方便扩大范围或重构无关功能。

当前架构以 [ARCHITECTURE.md](ARCHITECTURE.md)、[ADR](docs/adr/)及[模块Contract](docs/modules/)为准：Vue3／TypeScript／Vite／Element Plus；Python／FastAPI；SQLAlchemy2／Alembic＋SQLite；pywebview／WebView2与PyInstaller当前桌面路径。WebDAV保留为后续一致性快照接续方向；数据库业务版本及确认快照为历史权威，Git不作业务存储。

面向教师个人，先Windows11、Win10后验；一个本地档案，无旧注册／管理员分班／同班查看／手机或同时编辑。首版全新本地数据，不安排旧业务数据导入，也不清理旧远程资源。班级维护／同班升班、多学期及旧计划编辑已确认；多班新增／切换后置。

日计划、观察既有规则保持；周计划先手工／本人来源／保存／确认／Word及备份配套，后按已决Q5/Q6做AI／材料。搭班两类信息手填，不读取对方日计划；一对一倾听、人数、缺勤／退费、拍照点名等另定。应用供应商是DeepSeek官方与MiMo标准API，不能把开发Go套餐当应用接口。AI失败是可恢复结果，但不免除应用缺陷。

## 权限与文件责任

OpenCode是实现、测试、迁移及构建脚本写入者；Command Code仅在当轮明确授权和互斥文件责任内参与。Codex负责规划／规格、技术审核、执行验证、文档及Git／发布管理，不另起业务实现者。已有授权内持续推进，不重复索要确认；历史某轮的修复、真AI、部署或签名授权不自动延续。

原生会话的当轮A/B/C/D互斥白名单及G0–G4门槛按相应结果记录保留，固定DeepSeek V4.1 Flash max；不fork／另派子代理，不并行改同一文件，不接管在途任务或还原他方修改。已完成责任归结果记录，不重放旧在途白名单。原OpenCode负责共享整合和最终Git；按Codex具体文件/blob/parent/tree门禁普通提交推送，不add-all、amend、rebase／force或改main／默认分支／可见性、tag、Release。

代码与迁移／候选构建、付费AI、远程操作、签名、发行各按当前实际范围，不从架构确认、提示词准备或历史结论推导自动启动。

## 环境、数据与验证

Windows11原生开发；当前基线为CPython3.14.10／Windows x64／标准GIL，锁定依赖保持。本轮另机按用户明确授权补齐3.14.10并使用独立环境构建，原3.14.7环境及临时构建链接已复位；旧3.14.7证据保留其身份，不迁移通过结论。WSL只作独立辅助，不共享venv、node_modules或运行库。不擅装新工具／Skill／MCP，不升级依赖或做无关全面环境审计。Skills/MCP先审计再决定KEEP／DISABLE／REMOVE-CANDIDATE；不因全局存在某Skill/MCP就认定项目必须使用，普通Git、文件搜索、测试不要求图谱。

验证使用新合成库／图片／凭据／导出根或授权副本；真实原业务库、密钥／DPAPI、原件、旧包与首失败现场保留，只复核已有保护指纹。写入／递归清理前验证绝对路径及源／目标／旧根边界，不删未知文件、不全局kill。网络守卫与APP_DISABLE_DOTENV按相应验证合同执行，不读真实secret或自动重发未知AI任务。

已知SAC4551电脑不执行受阻新旧EXE／helper，不改名、换路径、降低保护、去来源标记重试；不自动签名、真AI、WebDAV、安装更新、远控或公开发行。新包必须新来源freeze、合法新根、实际静态／运行证据，旧源码／包／Word结果不跨身份复用。源码、自动、静态、目标、Word与教师体验分别记。

微软拼音已通过，不重测或穷举输入法。W6跨120秒睡眠不再追测，白屏／额外任务按同类复发处理；不把不追测写成已修复。原无guard历史缺口、长根WinError206、Win10／WPS／干净机及其它显示条件未验保持；详见维护核查归并原文和所指实际报告。

仓库MIT、已公开；受控模板授权按开源准备记录。当前文件清理不等于Git历史安全，不重写历史／强推或改可见性。旧远程资源及v1失败／未验保留，不自动续跑云端任务，不作为桌面全部阻塞。

## 架构与文档治理

ARCHITECTURE.md只写当前系统级架构事实。单一Feature不得自行修改；改变一级技术栈、依赖方向、模块边界、数据权威或通信机制，先提ADR并获确认后再实施。

- `docs/adr/`：架构决定和原因；`docs/modules/`：模块Contract。
- `docs/specs/`：产品／工程规格与范围；`docs/bootstrap/`：入口、审计与结果。
- `docs/tasks/current.md`：唯一当前执行提示词；最新状态不散落在旧提示词中。

任务完成或替代时，先把独有决定／未验归规格或结果，再删除已跟踪旧提示词并修引用，由Git留历史；不新增prompt-final-v2/v3或归档副本堆积。未跟踪独有资料不直接删。日期旧的规格／失败证据不等于无用，应标适用范围和历史身份。AGENTS保持简短，旧轮次计数／哈希移结果，不当项目百科。
