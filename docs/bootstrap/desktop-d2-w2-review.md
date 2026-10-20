# D2 W2 Codex核查记录

## 1. 授权与开始状态

2026-10-18用户授权直接调用OpenCode，以Go套餐DeepSeek V4.1 Flash实施W2，Codex核查并交回修复；不调用应用真实AI、不发布。范围见[当前任务](../tasks/current.md)及[工程规格](../specs/desktop-ai-engineering.md)。W1限定环境工程通过不变。本记录尚无W2通过结论。

- 分支codex/desktop-v2-foundation，保留已有未提交/未跟踪工作。
- 源快照：%TEMP%/kgm-d2-w2-codex-98lmfxp5/before-sha256.json及before目录，共259文件。
- 图谱现可用：项目C-Users-yw980-code-kindergarten-manager-next，generation 2026-10-18T00:51:58Z。定位config preview/apply及初始化；7相关路径coverage为metadata_changed，采用当前源码阅读，不声称完整结构审计，未重建工具。
- W2仅覆盖G05提示词/游戏版本及G06包内契约/纯校验；任务输入投影、执行钉版本、候选、UI和真实AI留后续。

## 2. 实施及核查

已直接启动OpenCode：session `ses_eb3692a38ffec4RawwCcC70sl2`，模型`opencode-go/deepseek-v4.1-flash`，日志`%TEMP%/kgm-d2-w2-codex-98lmfxp5/opencode-w2-run1.jsonl`。结果和独立证据随后追加。

## 3. 核查场景（待执行）

| 范围 | 核查内容 |
| --- | --- |
| 游戏配置 | 空初版、各类型30个上限、文本空/null及长度、嵌套越权字段；preview无写；apply双版本原子增加；旧计划逐字段不变；no-op只回执；回包丢失后过期token/旧版本同键回读；异体冲突；并发/提交失败 |
| 个人指导 | 三类可读、只读不增版；空文字和8000字界限；完整字段map；默认r2→r3竞争只接受所选r2；拒绝不改文本；重复动作no-op；已有版本和回执不可变 |
| 契约升级 | 包清单同步原子、同键不同hash拒绝、重启不增个人版；只挡变化任务；旧文字可编辑；新增默认预填/删除字段保留；显式adapt后解除；目标required已改变时409；新建档案用有效包内版本 |
| 请求与恢复 | Host/Origin/session/no-store；跨AI配置/指导同键冲突；成功回执先于旧expected/契约检查；提交失败无半版本/半回执；错误不含材料；保护手工读写路径 |
| 三类契约 | 拆分六必需string允许空；适龄只process；其他至少一板块、晨间两种各一组且一game、保留共享文字、额外ID/反思/null拒绝；结构/容量限制和固定bundle一致 |
| 回归与范围 | 相关及全local实际结果；历史迁移/旧纯registry/依赖/架构/已有包与开始前一致；不把未实施的来源投影、调度、候选、UI、真实AI记为通过 |

## 4. 首轮模块审阅

- R01：首版`prompt_bundles.py`容量按字符数判断，且把Pydantic异常全文拼入候选错误；已通过同一OpenCode session交回修复。修正为UTF-8字节上限及安全校验提示。未由Codex改实现。
- Codex独立执行27个断言全部通过：三包与0004冻结hash一致、拆分六字段空字符串保留、逐字段null/数字拒绝、适龄空过程、晨间无序两组及共享文字保留、空板块/显式null/反思/单组拒绝、错误不含合成标记、中文多字节超过1MiB拒绝。
- 证据：`%TEMP%/kgm-d2-w2-codex-98lmfxp5/codex-pure-first.json`（含该次源码hash）。这是首模块检查，不能替代最终W2回归；原始首次错误保留于run1日志。
- R02（待修复）：独立真实SQLite 11项检查有1项失败。字段删除→重加并编辑→再次删除，`orphaned_guidance`因`setdefault`保留第一次旧文字，未呈现最新被移除的个人文字。已交回OpenCode修复显示与adapt合并及补测试。证据`%TEMP%/kgm-d2-w2-codex-prompts-4bwj3945/codex-evidence.json`，10项通过包括r2/r3所选覆盖、reject保留、回执优先、只挡对应任务、提交失败版本/回执回滚。
- R03（待修复）：游戏`_plan_window`缺分支导致KeyError；预览`normalized_change`变成kind+payload封套，不能通过原preview/apply输入schema。独立复现见`%TEMP%/kgm-d2-w2-codex-98lmfxp5/codex-game-first.json`，已要求OpenCode保持平铺接口并补真实HTTP预览返回值直接应用。
- 清单同步补核查：同task/contract不同default只允许指导文字变化，schema/指导字段集合变化必须升级contract，不能绕过适配。已交OpenCode落实验证。
- R03修复后Codex真实HTTP独立15项通过：预览无写、normalized_change直接apply、双版本推进、旧计划逐字段一致、旧版本/失效token同键回读、异体冲突、no-op、地点/文字限额及嵌套越权、Host/Origin/session、并发200/409且仅一新修订。证据`%TEMP%/kgm-d2-w2-codex-games-zwo65ti7/codex-evidence.json`。最终全回归仍待执行。
- Codex另行真实HTTP25项通过：三任务读取、空白精确保留、完整持久回执/后续更新后重放、与AI配置双向键冲突、严格版本和指导校验、请求保护、GET不增版、并发单次提交、no-store。关闭后以冲突包重新启动：prompt受限，手工读取/保存及真实DOCX导出仍成功。证据`%TEMP%/kgm-d2-w2-codex-api-idif2a0y/codex-evidence.json`。
- R04（待修复）：新库坏包同步失败后，初始化仍按未登记的manifest r2建个人版本，导致FK失败、HTTP503，手工首次建档受阻。条件为同键冲突r1＋新增r2，runtime已记录PROMPT_BUNDLE_CONFLICT且登记回滚。证据`%TEMP%/kgm-d2-w2-codex-fresh-degrade-s9e4ho6w/codex-evidence.json`；已要求OpenCode改为成功核验/登记的有效种子并补新库降级、健康新包初版和重启测试。
- R05（待修复）：OTHER输入未落实冻结schema中晨间每kind最多一组，两个collective空games组被纯校验接受。证据`%TEMP%/kgm-d2-w2-codex-98lmfxp5/codex-input-first.json`。已要求补输入0..1计数；null/空列表/单kind仍合法，不能误用输出恰好两组限制。

## 5. 失败场景独立复测

2026-10-18，OpenCode修复后Codex重新创建合成根，20项全部通过：坏包新库HTTP201建档、AI仍阻塞且使用已登记r1、未登记r2不存在；健康新包新库采用r2初版、重启个人版/全局配置不增；游戏只读查询可直接预览且无写；字段再次删除的展示及adapt保存都保留最新文字；晨间输入null/空/单kind/两kind合法、重复kind拒绝。

证据`%TEMP%/kgm-d2-w2-codex-final-cases-kitzp5j4/codex-evidence.json`。R01–R05的已发现失败现均复测通过；最终源码范围检查、全local回归和OpenCode交付文档仍待收口。本记录保留上面的首次失败，不将其删除或改写成原本通过。

## 6. 完整回归与范围核对

Codex独立运行`desktop/.venv-d1/Scripts/python.exe -m unittest discover -s backend/tests/local -t backend`，实际**344项／165.088秒／退出0**。环境为当前Windows 11、CPython3.14.7 x64标准GIL，LOCALAPPDATA也独立隔离。日志`%TEMP%/kgm-d2-w2-codex-regression-c029ab6fb5404144b5a6e09809964212/unittest.log`。OpenCode另跑344项／146.924秒；其专项58项／10.793秒，见[交付结果](desktop-d2-w2-result.md)。

此次全回归有一条未关闭SQLite连接的ResourceWarning：旧`test_dispose_releases_lock_when_engine_dispose_fails`故障夹具mock了Engine.dispose并丢失原engine，W2同步新增真实连接后显现。不是一般成功提示；已交回OpenCode仅修夹具清理并增加定向GC核查，未改变生产dispose行为。其收尾复测结果随后记录，不把344项全回归冒充包含后来新增测试。

源快照比对：生产改动为6个既有本地模块＋2个新模块；新增W2测试3份，另有上述旧测试夹具清理。历史迁移、models、旧云端registry、W1凭据服务、桌面/前端实现、ARCHITECTURE.md保持开始前字节内容。D1包仍为`c6dc19283a24d00a740f2ecbed2cc7159e951f02a37f00636b294b7670369930`，W1探针包仍为`6a283bdfc9954c683ac2e86c75762ed99a0961ff7dde47580a55419a5e91d9f4`。

## 7. 后续接口使用边界

- W5从`GET /api/local/config/class-games`取当前修订与平铺change，再走现有preview/apply；该接口已归并工程规格§5.2。
- PromptOut.fields对应required/latest；普通旧契约编辑应保留guidance原字段集，需要旧默认比较时取明确contract/default端点。适配编辑用目标fields默认预填新增项，已有个人文字优先，显式adapt提交；中文字段标签属于W5常规展示工作，不新增产品决策。
- 当前交付业务契约为v1。契约演进测试证明指导版本/默认同步保护，不代表任意未来输入/输出schema都已有运行校验器。W3/W4必须按执行钉住的契约选择受支持校验，不将当前v1校验器冒充历史/未来契约通用解释器；还须接入runtime.prompt_sync_error与对应任务adaptation_required检查。
- 本轮不包含任务来源投影/日历±7日、调度/transport、候选采用、设置界面或新冻结包；未调用真实应用AI、未发布，不重复输入法人工验收。

## 8. 最终工程结论：W2通过，停在W2

2026-10-18，**W2游戏配置及提示词在当前Windows 11源码/合成环境的工程核查通过**。OpenCode唯一写入实现与测试，模型为用户指定的`opencode-go/deepseek-v4.1-flash`；Codex独立审阅、运行验证并交回R01–R05修复，均已关闭。全量回归显现的旧故障夹具连接清理问题也已修复，生产dispose语义未改。

- OpenCode在最终addCleanup夹具上再次完整回归：**345项／138.144秒／退出0，ResourceWarning为0**，原始日志`%TEMP%/kgm-d2-w2-opencode-final.txt`，已复制留存到本轮证据根`opencode-final-local.log`。addCleanup保证中途失败也执行清理。
- Codex对最终addCleanup版本独立定向复测：**6项／0.848秒／退出0，显式开启ResourceWarning且为0**。证据`%TEMP%/kgm-d2-w2-codex-final-runtime-7d2d39b43c644d91b58f490173b854a0/unittest.log`。结合§6独立344项全量及58项W2专项、27/15/25/20项独立场景证据，覆盖本包要求；这些集合有重叠，不相加为独立用例总数。
- 最终范围为7个既有文件（6生产＋1旧测试夹具）及5个新增文件（2服务＋3测试），无源文件删除。完整SHA-256和相对开始前差异见`%TEMP%/kgm-d2-w2-codex-98lmfxp5/after-sha256.json`、`codex-scope-check.json`。
- 核对确认独立344项全量之后，仅旧测试夹具文件变化，生产源码未再改变。10份相关文档的182个本地链接目标均存在，相关文档与变更/新增源码无尾随空白，`git diff --check`通过；证据`codex-doc-check.json`。
- [OpenCode交付结果](desktop-d2-w2-result.md)包含实现清单、实际测试和W5接口交接；工程规格§5.2已吸收游戏只读接口。当前任务中的独有决定已归并本记录/规格，关闭后不留第二份提示词副本。

此结论仅关闭W2，不代表完整G05/G06、D2产品或发行验收。W3–W6尚未启动；没有真实应用AI调用、打包发布、commit/push、生产凭据改动或教师资料库迁移。W1和D1既有结论、包与人工证据保持，不再要求输入法复验。

最终OpenCode session已正常结束且active为空，未遗留继续写入的实现任务。
