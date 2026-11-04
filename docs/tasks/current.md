# 当前：测试机审核收口，交开发机接续源码与白屏复现

更新：2026-11-04。继续`codex/desktop-v2-foundation`，本文件是唯一执行入口。用户最新授权：原OpenCode会话和Command Go继续使用DeepSeek V4.1 Flash max，排查白屏、并发首失败及Word/r影响，保持系统保护不变；处理后继续测试，由Codex独立审核，通过后普通提交推送，交开发机继续实施。此前测试机“不提交推送”的停止条件已被替代，不重放旧Git白名单。

## 1. 先读最新结果，保留各自身份

- [目标机独立核查](../bootstrap/desktop-weekly-ai-windows11-target-review.md)：原CI首次SQLAlchemy扩展策略拦截、两次授权最小修复、三个候选、真实AI／材料／Word／备份及T01–T11分项结论，提示词独有决定已归§11。
- [白屏／并发／Word补核](../bootstrap/desktop-windows11-white-concurrency-review.md)：最新独立审核，后端62／桌面35通过、393文件前后稳定；白屏受控重开与Word注册核验的准确边界。
- 有效[周计划产品](../specs/desktop-weekly-plan.md)、[Q5/Q6工程合同](../specs/desktop-weekly-ai-engineering.md)、[验证矩阵](../specs/desktop-weekly-ai-validation.md)、[完整备份恢复](../specs/desktop-backup-restore.md)及[关闭保存合同](../specs/desktop-manual-daily-plan.md)。旧[开发机核查](../bootstrap/desktop-weekly-ai-review.md)与[39项教师收口](../bootstrap/desktop-weekly-target-test-closeout.md)不迁移为新包整体通过。

测试机开工父提交为`7eb4b5ea859625de83fff073b01c6bb543e5cdf5`。本次收口实现共13文件：原SQLAlchemy构建5文件与T03来源／安全错误7文件（组合补丁c745f3cc…）加并发夹具测试1文件（最终SHA14f3642d…）。没有新增采用／关闭生产行为、依赖或迁移。原OpenCode是实现与最终Git写入者，Codex独占正式文档、验证及最终文件／blob／parent／tree审核；只允许审核后的普通提交推送，不add-all、amend、rebase、force或改main／默认分支／可见性、tag、Release。

本机候选build`32a6d197-03c0-45ec-91fe-0b80d9528189`仍来自7eb4b5e＋原12文件补丁，不因Git收口变为新CI制品。该包三次官方DeepSeek生成／明确采用、新材料Word两份四页、加密备份恢复／保护包再恢复、0007备份UI恢复和正常独立重开已有限定证据；无自动重发。原T09失败是副本携带内部维护回执、丢失私有权限边界导致正确拒绝，未放宽安全检查。完整原件／首失败及所有保护包私下保留。

## 2. 开发机接收与责任

1. 核实际目录、分支、HEAD、工作区及远端；本地修改和未跟踪独有资料先保留，不覆盖或清理。仅普通fetch／`git pull --ff-only origin codex/desktop-v2-foundation`；不能快进就停止同步并报告。记录实际收到的完整提交及tree，不拿父提交或报告里的包身份代替。
2. 继续原生OpenCode／Command Go已有会话，固定DeepSeek V4.1 Flash max，不fork／派子代理。先核本机真正存在的session与实际请求metadata；测试机OpenCode为`ses_e651729c9ffeG6mP7f6K1oat1I`，Command Go为`b5a7810b…`，不要求开发机伪造或拥有这两个本机会话。原会话不可定位时明确报告，不另起实现者冒充。
3. 文件责任按下一项具体分工互斥核定，不还原他方修改。本次Command Go曾因CLI工具权限不能写源码，未放宽权限或以shell绕过；测试文件转原OpenCode实施后，Command Go只读审阅早一版，最终追加数量断言由Codex独立审核验证。不要把这次受拒当作永久产品或系统权限变更。
4. 开发机已知SAC4551主系统保持源码／合成工程验证边界，不启动候选EXE／helper，不用测试机成功结论豁免策略。测试环境使用现有CPython3.14.10 x64标准GIL及锁定依赖，不自动安装／升级；禁dotenv，用独立短合成根，必要Python守卫不外推OS隔离。

## 3. 下一实施片：白屏复现与恢复行为核定

原白屏根进程仍响应但WebView2子进程／渲染窗口已不存在；07:04:41 Winsrv关机否决仅为时间相关线索，精确触发及Word/r因果关系未证实。现关闭协调器在无页面保存ack时拒绝销毁，符合现合同。保全进程／事件和一致性副本后，测试机仅外部终止该明确合成进程（exit0xFFFFFFFF）；同EXE同根普通重开、正常退出exit0，四阶段所有表／34文件／不透明凭据行完全一致，任务及attempt仍3。不能写故障自动恢复、异常页面未保存输入安全或白屏业务已修复。

开发机先回读上述证据及当前保存／关闭合同，用隔离合成环境设计并执行最小可控的渲染器丢失复现，分别区分桌面不可交互、窗口捕获失败、真正WebView2退出和宿主存活。原OpenCode负责必要生命周期代码／桌面测试，Command Go可按不重叠责任只读核查或诊断，Codex审核；不操作原测试机业务根，不通过真实关机／断电、杀未知进程或改系统保护造场景。

有证据且不改变已确认产品行为的最小缺陷修复可沿本轮白屏授权继续实施并回归。若需新增重载、异常退出／恢复入口、处理未保存输入或改变保存ack合同，先提出具体行为、资料风险和可验证方案供用户核定，不能自行选择自动reload、自动关闭、强杀或跳过保存。只有改变系统级架构边界时才按AGENTS提ADR，不为普通故障诊断自动新增架构流程。独立审核应保留首失败、反向对照和最终源身份，不能用重试／sleep／skip把并发测试变成串行；本次已修的共享主Session夹具不再作为生产并发缺陷陈述。

## 4. 不重复与停止条件

Word当前版本／签名、11项注册结构、默认DOCX关联及两页正常打开／关闭已限定通过；/r调用前无基线，历史具体注册差异仍未知。不得再/r、regserver、Office修复／重装、修改关联／注册表来补证或回滚未知差异；不把“未见故障”写成“当时无修改”。

测试机真实AI授权及显式重试费用决定已归目标核查§11；本次补核新增0次，不自动扩为开发机真实发送或跨机凭据许可。不开新付费分支补齐未出现的失败，不在聊天索key、不复制DPAPI。旧39项教师清单、13份43页Word、微软拼音、W6跨120秒睡眠不重验；新32a6…仅本轮矩阵范围通过，MiMo、Win10／WPS／其他DPI／干净机、跨用户凭据、断电、长根206和符号链接特权保持原未验边界。

不启动签名／证书／微软复核、安装更新、WebDAV、远控、公开发行或依赖／工具／Skill／MCP安装；不改保护、执行策略、来源标记。若push自动生成新CI候选，只按本次完整HEAD对应的成功run核制品，核可信日志、ZIP及原字节PS1 SHA、package-info.source_commit、两个身份文件build_id／revision和source freeze；内部AppIdentity没有source_commit，依现格式核。新制品目标运行须有适用机器与明确范围，不继承旧包结论、不自动dispatch／重跑或以旧成功包替代。

发现保存／恢复／关闭缺陷先保留首现场，暂停对应后续写操作，继续独立只读工作；真实原库／照片／凭据、旧合成源、所有Word／备份／保护包保持。只将脱敏结果与审核源码入Git，不提交私有原始证据或制造新提示词归档副本。完成后更新相应结果记录和本入口，再由Codex按当次文件／blob／parent／tree复核普通Git交付；不把工程通过等同完整产品验收。
