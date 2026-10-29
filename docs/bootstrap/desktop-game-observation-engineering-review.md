# D4-E：游戏观察记录工程方案独立核定

> 公开版隐私处理（2026-10-30）：本机用户路径、私有部署地址或联系标识已替换为占位符；原始记录由维护者私下保留，历史日期、结论和产物哈希不因此改变。

更新：2026-10-25。**最终结论：E01–E14工程设计核定通过，附实施准入与运行验证条件。** 有效方案为[工程设计](../specs/desktop-game-observation-engineering.md)，产品基线为[完整规格C1–C33](../specs/desktop-game-observation.md)。本结论仅批准设计方向及明确的协议约束；观察功能未实现，A01–A22没有新增通过结论，本轮未运行应用测试／迁移／探针／构建。

后续接续（2026-10-26）：用户另行授权的E01／E02／E04已进入实施与独立核查，见[数据基础核查](desktop-game-observation-foundation-review.md)。本文“仅设计／暂不实施”为本轮设计核定时点结论；后续授权仅覆盖上述切片，其余范围不变。

2026-10-26接续：用户授权E13草案与独立核定，原会话修订后六份Contract设计已通过并归并，见[E13核定记录](desktop-game-observation-contract-review.md)及[观察Contract](../modules/game-observations.md)；工程正文已同步精确协议。本报告下文保留2026-10-25的过程及当时停止点，不能将当时“Contract待交”当成当前剩余任务；也不将后续设计通过写成运行通过。

## 1. 授权及审阅范围

用户要求原OpenCode会话先交E01–E14工程方案，明确文件、模型／迁移、图片生命周期、AI契约及验收，由Codex独立核定，暂不实现。原会话`ses_ead8af71dffeJphI1NOWg4jZgI`，历史标题“D2 W6 导出打包工程实施”；标题不改变本轮只读设计边界。CLI 2.1.2，固定`opencode-go/deepseek-v4.1-flash#default`、`plan`代理；未另建／fork会话或实现者。

Codex派发只读任务、限定源码核对并退回方案；未代写实现。审阅应用已安装的codebase-memory规则，但图谱调用`Transport closed`，回退限定源码，**没有全仓库图谱覆盖证明**。没有因此安装／重建Skill或MCP。

限定源码覆盖：models/schemas、AI输入／任务／执行器／worker／transport／候选／采用、日计划历史服务、runtime/profile/prompt种子、local迁移env和digest、Word导出、实际宿主保存／构建路径、前端编辑／leave／close／更新入口。读取只用于设计一致性核对，不是运行验证或全仓库安全审计。

## 2. 原会话交付及独立审计

证据根：`<LOCAL_USERPROFILE>/AppData/Local/Temp/kgm-observation-plan-20261025-04aabfa4/`。本机指针为`%TEMP%/kgm-observation-plan-current.txt`；temp并非永久交付仓库。可复用的结论／纠正已归并到本报告和唯一工程文档，原回复、失败证据及JSONL保留，不自动删除。

| 轮次 | 交付及本轮实际结果 | Codex处理 |
| --- | --- | --- |
| r01 | 完整方案；CLI exit0；31条assistant均指定Go Flash/plan，finish stop；505份非凭据基线文件hash零变化 | 不通过，F01–F10交回同一会话 |
| r02 | 修订完整方案；exit0；9条assistant同模型/plan；505份hash零变化 | 改进但不通过，S01–S06退回 |
| r03 | 六个完整替换章节；exit0；按初始user消息边界审计43条assistant同模型/plan，包含S07 steer前后；505份hash零变化 | 修复来源／依赖／种子等，但命名和上下文仍冲突，形成K01–K08 |
| r04 | 仅确认K01–K08；exit0；1条assistant同模型/plan，0 tool calls；finish stop、session idle/succeeded；505份hash零变化 | 原会话逐项接受，明确旧别名／错误作废；按修正后的唯一文档核定 |

模型审计按实际该轮初始user消息界定，不误用第一个CLI事件；r03不以最后的steer消息截掉前半轮。r03初始消息`msg_1730b0a94001QjssRBUhbWQvCc`，S07 receipt `msg_173167913001NRDNPuUN25Xb4k`；r04初始消息`msg_17325ce800015Bmw8bCQypLWND`。最终session元数据仅辅助，结合CLI真实退出、finish及idle判断，不用旧outcome猜已完成。

证据文件包括各轮`opencode-plan-r0N.jsonl/.stderr/.exit`、`plan-r0N.md`、脱敏session导出、`r0N-model-audit.json`、`repository-r0N-before/check.json`及反馈。505份快照排除凭据类文件；每轮派发前刷新的是Codex已改任务文档后的基线，OpenCode未修改这些文件。最终仓库只有Codex规划Markdown变化，没有新增实现／测试／迁移／构建代码，未提交／推送。

## 3. F01–F10：首轮退回及关闭依据

| 编号 | 首轮缺陷 | 最终有效纠正 |
| --- | --- | --- |
| F01 | 园所入表、8行映射错误，分页属性混淆 | E11表外原文标题；6网格、姓名span3及正文span5；自然分页、固定标签11/正文值12；真实Word另验 |
| F02 | AI通用化没闭合旧非空列、复合FK、CHECK及回填 | E02逐表可空分支、非空来源链、同序父UNIQUE、保留旧daily依赖，迁移预检与回滚 |
| F03 | record/draft/照片双重权威，hash和跨记录约束不清 | draft+关联是当前权威，record仅投影；aggregate hash含照片；版本/资产/input同record复合约束 |
| F04 | 恢复漏当前draft及照片，UI未先保存，锁内材料IO | E08先成功保护UI，再绑定预览；整份事务写集合，材料解码在锁外 |
| F05 | 采用一栏使剩余全过期，配置变化混同来源变化 | E07逐目标/实际上下文依赖及本候选provenance受信替换；手改/他候选复核；固定配置版本 |
| F06 | 30图/30姓名/200份/500MiB/80MiB等任意额度，内存预算不完整 | 移除任意业务额度；供应商/字节/像素/IPC/工作集分层；候选参数待容量测量 |
| F07 | 空日期强制无学期违背显式选择 | E04无日期可显式归属，已有稿清空日期默认保留，跨学期明确决定 |
| F08 | 漏executor、实际宿主/构建影响路径 | 工程§1列完整链；旧text及save_docx保持，新视觉合同/受限export_id单独核定 |
| F09 | 图像库版本/轮子/许可缺失，Contract放到最后 | Pillow提案及公开元数据；E13为实施前门槛，系统边界变化先ADR |
| F10 | 未确认年龄/字段/人数上限和矛盾硬阻断，未来命令含糊 | E01三类校验分开，不替教师改资料；E14给目标解释器/cwd/拟测试/独立证据 |

## 4. S01–S07：二、三轮问题及关闭依据

| 编号 | 独立发现 | 最终处理 |
| --- | --- | --- |
| S01 | 第一行单元格跨度仍矛盾，残留占位标签 | 第1/2行各6个独立格；第3行姓名2–4；第4–8行值2–6；固定原标签 |
| S02 | SQLite NULL可绕CHECK；task没有独立scalar input FK，旧来源链不能自动保护观察 | 每分支显式IS NULL/IS NOT NULL；input→task→execution→candidate全非空复合链及父UNIQUE；不声称旧约束已覆盖 |
| S03 | 重写支持策略发送过程，但共享hash不含过程 | E07依赖等于实际发送矩阵；过程变化使策略候选SOURCE_CHANGED；同候选连用有账本证明 |
| S04 | term_decision仅写回执，实际恢复仍盲拷历史 | 有效payload先完整历史，再仅覆盖明确归属/快照，token、hash及所有写集合用同一有效值 |
| S05 | MiMo正文证据不足、漏DeepSeek图数、擅增AI照片子集、工作集不实 | 找到并独立读到精确MiMo官方路径；保留官方图数防护；所有照片参与，不增子集UI；全程内存/参数待测 |
| S06 | 把设计细节写成通过，失败用例/命令/依赖位置不足 | E14全部标未来；业务依赖只backend权威声明；分离合成、真实窗口、Word、真实AI和包 |
| S07 | 迁移直接向已有prompt表插观察种子会改变guard旧表摘要，冷升级被自己拒绝 | 迁移仅DDL/新列回填；两次guard完成后启动同步种子；旧daily行子集不变，重复seed相对首轮成功状态幂等 |

S07是Codex直接读取`d1_digest.capture_schema`、`migrations_local/env.py`及`runtime.py`发现，并用`delivery=steer,resume=false`交同一会话处理。未运行迁移证明；设计关闭不代表冷升级已通过。没有放宽guard、提前提交或修改旧迁移。

## 5. K01–K08：最终有效条款及原会话确认

第三轮替换稿仍混用草稿/历史计数、任务名称、模板原文，并为简化依赖去掉完整生成的已有正文。Codex没有把“补了章节”当通过；以以下条款收敛，r04明确接受。有效工程文档已吸收，旧回复相反表述作废。

| 条款 | 必须遵守的设计 |
| --- | --- |
| K01 | source_kind仅daily_plan/game_observation，观察任务game_observation_generate/rewrite；draft.revision与versions.version分离；record.current_version/current_draft_revision不换别名；flat canonical及聚合hash唯一 |
| K02 | AI从成功保存draft冻结不可变input；source_revision是元信息，只FK稳定record，不FK不存在versions.revision或强制制造历史；照片/工作图持久引用 |
| K03 | 四表新增非空来源链及完整同序UNIQUE/FK，candidate不能只写省略profile/kind/source的短链；保留旧daily FK/所有被引用父UNIQUE，尤其candidate(daily_plan_id,id)、execution(task_id,id)；CHECK防NULL绕过 |
| K04 | 四栏生成仍发送教师已有四栏；上下文hash覆盖实际发送；同候选已采用输出凭账本及当前值受信替换；人工/他候选变化必须复核；固定提示词配置不因后来修改而误过期 |
| K05 | Word原后缀公共/室内/户外，原标签幼儿年龄；8行6网格；基本含环境11、四栏正文值12，固定标签沿模板；每组1或2个inline图，不同时要求每张独段又同段双图 |
| K06 | 种子在两次guard后；seed合法增行后不能要求全表摘要仍等于迁移前，改验旧daily行子集及重复启动；无profile先bundle、建档动态种子；personal表没有task_type CHECK，不误重建 |
| K07 | 精确MiMo官方正文可引用，应用兼容未验；全部记录照片参与AI；所有容量数值是提案；材料层锁外串行派生，worker只读已验图文；预算覆盖实际处理/复制，不拿RGB算式当RSS证据；新export_id不放宽旧桥 |
| K08 | 观察业务拥有资料/材料/候选意义/采用决定，AI只管基础设施；旧daily API隔离，新adapter/global close覆盖两类；恢复有效payload统一写draft/history/photos/projection/receipt；Contract先行、ADR边界不变，所有运行项未验 |

不以r01/r02/r03原文直接作为实施依据；唯一有效正文已规范化，避免“旧段落保留＋补丁附录”留下两种协议。

## 6. 独立源码与公开资料核对

设计核对得到的关键事实：

- 旧AI inputs绑定日计划内容三元组，旧task仅有复合input FK，不能靠想象中的scalar FK闭合观察链；executions(task_id,id)和candidates(daily_plan_id,id)受其他表依赖，重建不能漏掉。
- personal prompt两表用bundle FK及revision/action约束；只有bundle存在需扩的任务类型CHECK。首次档案通过`effective_prompt_seed`动态遍历，已有runtime在升级guard后同步提示词，故可沿用而不绕保护。
- 现有executor构造文本`user_text`、1MiB及帧校验，drive有既有超时；视觉必须覆盖executor/worker/transport整体，不能只改页面或worker。现有宿主`save_docx`30MiB应保持，新受限产物交接另核。
- 实际模板目录为`backend/app/assets/word_templates/`，构建入口为`desktop/build_d2.py`，当前本地迁移头0005。Pillow是业务依赖，不能在requirements-d1.in重复声明。

公开资料于2026-10-25只读查阅，未调用推理API：

| 来源 | 本轮核实及其限度 |
| --- | --- |
| [DeepSeek图像理解](https://api-docs.deepseek.com/zh-cn/guides/vision/) | 标准图文/Base64及请求/单图/图数约束有官方依据；不代表应用兼容、实际工作集或真实质量通过 |
| [MiMo图像理解](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/multimodal-understanding/image-understanding) | 初始不含quick-start的路径无可读正文，后来找到此精确路径并独立读到正文；支持相关图文/Base64等约束可用于适配方案。不能保留“所有详情都不可读”的旧结论，也不能据此称实际调用已验 |
| [Pillow 13.0.0](https://pypi.org/project/pillow/13.0.0/)及PyPI JSON | 独立核对Python>=3.11、MIT-CMU、标准GIL cp314 Windows x64 wheel及SHA256，与提案一致；未下载/安装/运行，打包/内存/解码仍未验 |

公开页面元数据核对证据为`independent-pillow-metadata.json`等；具体轮子hash见工程§14。没有以搜索摘要替代MiMo正文核定，没有安装依赖或变更运行环境。

## 7. E01–E14结论及实施准入

| 范围 | 设计结论 | 尚需的后续条件 |
| --- | --- | --- |
| E01–E05 | 字段、模型/来源约束、材料权威、学期、草稿/历史协议核定 | Contract细化后，独立合成迁移与故障证据；容量参数验证；不是库已升级 |
| E06–E08 | 视觉执行、实际依赖/部分采用、整份恢复协议核定 | 假供应商/IPC/来源FK/时序/幂等运行验证；真实效果另授权 |
| E09–E12 | 工作台/leave/更新、列表选择、Word映射、受限交付设计核定 | 实际组件及Windows窗口/原生保存，产品导出Word逐页；资源/路径/token边界验证 |
| E13 | 职责/治理及Pillow依赖方向核定 | 实施前先交Contract草案；锁/插件/许可/打包实证后续；触系统级变更先ADR |
| E14 | A01–A22、R01–R14映射、未来命令及证据分层完整 | 所有执行尚未开始，不能写任一运行验收通过 |

没有新增必须重问用户的主流程产品问题；C1–C33不变。**以下为准入条件，不是已通过能力，也不要求当前自动开工：**

1. 先核定观察、材料、提示词/AI、Word、身份/审计的Contract草案；不直接改系统架构。
2. 获授权后用隔离合成库/图片完成迁移、材料、容量及故障验证，冻结请求/IPC/超时/工作集/文件交接参数；显著影响教师流程的保护上限另交用户决定。
3. 分片实现仍由原OpenCode唯一写入，Codex独立核查并交回同一会话修复；本轮设计授权不延续成实施授权。
4. 真实AI、冻结包、签名/发行及其环境验证仍按后续明确授权，不与源码/合成结果混记。

本轮文档变化限定产品/工程规格、独立核定报告、当前入口及状态链接；未改实现、测试、迁移、构建、现有模块Contract或ARCHITECTURE.md。未动旧数据/凭据/儿童原件/旧包/旧远程资源，未真实AI/WebDAV、未提交/推送。D2及D3-U既有通过/未验身份不改写，跨设备继续后置。当前停在工程设计核定完成。
