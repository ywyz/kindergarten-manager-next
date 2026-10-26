# D4：E01／E02／E04模型、迁移与归属独立核查

更新：2026-10-26。**结论：E01／E02／E04模型、迁移与归属数据基础通过当前Windows 11隔离合成环境的限定工程核查。** 原会话完成R01–R08修订并停写，Codex最终599项全local通过、0失败／错误／跳过，210份后端源码／配置／测试hash前后一致。完整产品A01–A22未验收，停在本片，不启动后续切片、不调用应用真实AI、不提交推送。

## 1. 授权、实现者及范围

用户授权原OpenCode会话使用Go套餐DeepSeek V4.1 Flash，按已核定Contract实施E01／E02／E04，Codex独立核查，问题交回同一会话修复。仅用隔离合成库，不启动后续切片、不调用应用真实AI、不提交推送。分支保持codex/desktop-v2-foundation。

基线为[观察主Contract](../modules/game-observations.md)、五份关联扩展、[E13核定](desktop-game-observation-contract-review.md)、[工程设计](../specs/desktop-game-observation-engineering.md)与[产品C1–C33](../specs/desktop-game-observation.md)。不增加教师操作、业务额度或新依赖。

唯一源码／测试／迁移写入者为原会话ses_ead8af71dffeJphI1NOWg4jZgI，指定opencode-go/deepseek-v4.1-flash#default、build代理；Codex只审阅、执行独立验证、写审阅与接续文档。首次运行在末次工具调用后长期无新输出，Codex保留现场并停止本次启动的私有server进程，再以相同session／model／agent续接，不另建／fork会话或实现者。

按本轮初始user消息msg_177ebc5b9001oZFodP9D9clWLs审计：336条assistant全部为上述模型／build，无模型替换；工具仅edit／grep／read／shell／write，无子代理。首次run因进程恢复exit1，接续r02真实exit0，最后assistant为msg_178421f0e001YlYO8Khl3glX4X、finish stop，完成时间1793018998747、更新后的idle1793018998750，outcome succeeded。不是使用旧outcome推断交付。

已安装codebase-memory按限定结构查询调用，但本轮返回Transport closed；因此回读本片限定源码／迁移及实际SQLite schema，不安装、重建索引或把图谱失败当覆盖证明。

## 2. 实际交付与未实施边界

| 文件 | 实际职责 |
| --- | --- |
| backend/app/local/observation_validation.py | 平铺payload正规化、三层校验、空骨架／空记录、AI就绪纯判定及唯一聚合hash |
| backend/app/local/observation_terms.py | 本份日期与已有学期解析、显式决定、可信快照和取消时保留输入；无观察业务写入 |
| backend/app/local/models.py | 15张观察关联表、四张AI表的完整非空来源链、原daily约束及父键保留 |
| backend/migrations_local/versions/20261025_0006_local_game_observations.py | 真实接0005的单一DDL／新列回填迁移；重建四张AI表及bundle枚举 |
| backend/app/local/prompt_bundles.py、profile_service.py | 两个观察bundle数据契约、守卫后事务幂等补种、无profile／首次建档与降级初始化 |
| backend/app/local/ai_task_service.py | 仅补旧daily写入必需来源字段，并限制旧日计划读写／claim入口的来源 |
| backend/tests/local/test_observation_*.py及四份既有D2／D3测试 | 切片约束、真实旧版本升级／回滚／种子及原日计划回归；旧测试随新增列调整，保留原语义 |

表结构预备不等于服务已实施：E03图片导入／解码／派生、E05／E08草稿保存及完整历史服务、E06／E07视觉执行／候选／采用、E09／E10页面列表、E11／E12 Word／宿主均未启动。未安装Pillow、改依赖锁或构建新包。观察任务数据登记不开放提示词编辑UI、API或旧worker执行。

## 3. 独立发现、退回与关闭条件

| 编号 | 独立发现并交回原会话的问题 | 复核要点 |
| --- | --- | --- |
| R01 | 缺项未覆盖三项表头；未知字段错误回显任意键名 | 表头纳入缺项；错误仅固定字段位置与未知键数，不回显任意敏感键 |
| R02 | 原图manifest缺镜像方向、重复资产／摘要校验及唯一排序权威 | 方向元数据允许空或1–8；重复asset、非法SHA256及数组／sort_order冲突拒绝；hash用规范原图manifest |
| R03 | 日期省略与显式空值混同；未改日期仍重复确认／按新配置重建快照 | 省略默认今天、显式空保持空；不变日期保留既有归属／可信快照，缺失旧快照明确处理 |
| R04 | 观察登记schema缺图及改写来源；评价目标只支持文本或可夹带另一目标 | 完整输入字段与照片事实；四栏五领域输出；改写oneOf互斥两个结构；本片仅数据契约 |
| R05 | SQLite整数列仅检查下界，REAL可绕过；来源索引不全 | 观察revision／version／人数／顺序等加整数类型约束，来源索引及活动观察任务部分唯一键与ORM对应 |
| R06 | preflight内连接遗漏缺失父行 | DDL前检查既存FK与完整父链；缺父、空旧必需字段或链不一致拒绝，无残留迁移表 |
| R07 | 旧D3升级测试来源版本不真实、可能因复制忽略而失真 | 真Alembic构造0004，再真实经过0005至head；升级前核对被测旧列／行及daily bundles；另有直接0005→0006富源 |
| R08 | 迁移／seed失败测试未证明到达关键写入，证据未充分保留 | 旧task／execution重建后定点失败及底层cause；实际flush一对种子后失败；前提交rollback、后提交拒绝启动与备份分开；失败后DB留存 |

R08还要求核对故障命中及前后时点：预置同名_new表／索引属于合成故障输入，需确认底层错误确实命中目标语句，保留副本取自失败与回滚检查后。不能用任意异常或故障前副本冒充中途回滚结果。

R01–R08及R04／R08精确补充均已按上述条件关闭；没有剩余本片编码问题。此处关闭的是限定源码／合成工程问题，不替代后续服务、真实窗口或教师产品验收。

## 4. 独立验证

环境：当前Windows 11、CPython3.14.7标准GIL／AMD64、SQLite3.50.4、SQLAlchemy2.0.54、Alembic1.20.0、pytest8.4.2；复用desktop/.venv-d1，未安装／升级依赖。

所有验证使用本轮独立Temp根及显式隔离data／credential_root，APP_DISABLE_DOTENV=1；未读取真实密钥。测试中的credential BLOB是人为构造数据，仅验证迁移保值，不代表真实凭据／跨机器能力通过。未运行应用真实AI、桌面窗口、Word、构建或发行。

| 独立项目 | 当前证据 |
| --- | --- |
| 先行切片五模块（最后测试证据补强前） | 51 passed，0失败／跳过；本次运行210份后端源码／配置／测试hash前后一致；最终补强测试由下列全local覆盖 |
| 日计划bundle冻结比对 | 从Git HEAD在内存载入旧manifest，与当前7份daily完整结构／指导／摘要逐项相同；daily三任务集合不变 |
| 富0005→0006只读复查 | 26张旧业务表的旧列类型化摘要保持；四张AI表原有FK集合全部保留；新观察15表；integrity_check=ok，foreign_key_check=0 |
| ORM／实际迁移结构只读核对 | 20张相关表列及FK集合相同，全部ORM声明索引存在；实际库另有4个旧daily索引，已与0005源核对确为保留项。初次严格索引集合相等断言因此不成立，未删旧索引或改模型求完全相等 |
| 提交后失败备份 | 失败时库已0006、观察bundle仍0；备份为0005、manifest SHA256相符、完整性及FK通过；不称提交后可ROLLBACK |
| 稳定最终全local回归 | 599 passed，0失败／错误／跳过；463.22秒；2026-10-26 20:50:30–20:58:16；210份后端文件hash前后一致，含最终故障断言／留档修订 |

富源非空包含两版content、input／task／execution／attempt／candidate、两条provenance、AI operation、历史restore、配置／state、个人指导及合成credential BLOB。验证旧列的类型和值，而非仅表数／行数。实际升级经过原迁移事务与guard；未修改migrations_local/env.py、d1_digest.py、migrate.py、旧修订或MySQL链。

四份既有回归文件的测试名称清单与HEAD分别保持43／17／16／25项，未删除测试；D3复制的被测旧行在升级前与源逐项比对。OpenCode最终40项受影响模块通过仅为实现者自测；最终独立结论以Codex全local为准，早期实现者597／599项结果不冒充最终独立证据。

前提交异常应回滚DDL／数据并留在原版本；后提交复核失败只能拒绝本次启动、保留升级前可核实备份。本片测试将备份复制到另一个合成目标验证可重新升级；后续普通启动可按current-head路径补种，不能据此宣称先前失败的复核重新通过或已自动恢复。

最终全local保留17份合成证据。独立只读复查确认：三个中途DDL失败及前提交guard失败均为0005、无观察表；提交后失败库为0006且观察bundle为0、其升级前备份为0005；种子写入后失败库为0006且新增观察bundle／head／version回滚，各有效故障样本integrity=ok／FK=0。故意制造缺父的preflight输入仍保留原违规，不能要求这类输入FK=0或据此修旧数据。

一次只读探针错误地把不同测试分别新建的0005库都与同一源完整摘要比较；逐表／逐列核对后，差异仅为迁移seed的created_at，不是数据丢失。原始失败输出保留；同一成功案例的源→升级库摘要相等、同一提交后失败案例的备份→已提交库旧列摘要相等，各回滚测试另与自身捕获的前态相等。没有忽略摘要列、更改guard或以跨案例相同替代实际回滚断言。

实际最终命令（cwd为backend，TMP／TEMP／data／credential_root及留档均隔离）：

```powershell
../desktop/.venv-d1/Scripts/python.exe -m pytest tests/local -q --basetemp <本轮隔离根>/pytest --junitxml <本轮隔离根>/junit.xml
```

## 5. 接续约束及未验事项

E01纯hash要求照片manifest数组已按业务顺序排好，sort_order为0至N−1且与数组一致；原图事实参与hash，AI工作图不参与。后续材料／保存适配须将数据库关联次序规范化成该manifest；数据库仅要求非负唯一序号，不要求教师补序号或另确认。

E04的snapshot参数只允许由未来服务从当前draft或可信历史加载；没有新增允许页面传快照的观察API。日期解析不读取上课日；同日多份不增加唯一约束。快照与配置互不反写；未来服务必须按本次纯函数返回的明确决定接入，不能把纯规则通过写成整页流程已验。

完整A01–A22尚未验收，已覆盖的基础规则也不代表图片、保存、视觉质量、采用、窗口关闭、Word分页或教师体验通过。Windows10／干净机器／冻结包和发行再现性未测；旧D2／D3未验事项原样保持。完成本片后停止，不自动派发E03或后续切片。

## 6. 证据与最终交接

本机证据根：C:/Users/yw980/AppData/Local/Temp/kgm-observation-e010204-20261026-2a32f2eb/，指针%TEMP%/kgm-observation-e010204-current.txt。临时根非永久归档；需保留的结论与接续约束归并本文及有效规格。

证据包括初始仓库／HEAD／diff基线、原会话各轮request／反馈与steer回执、JSONL／stderr／exit、脱敏session导出／模型审计、独立验证source-before/after、JUnit／stdout／stderr、保留的合成旧库／升级库／故障库／备份manifest及只读inspection。首次run进程恢复单独记录，不记为正常exit0交付。

最终独立全量证据目录为codex-final-full-local-a1aeab7c/，先行51项为codex-final-targeted-014daad8/；各自含verification.json、source-before/after、JUnit及日志。最终保留故障样本使用最后修订后的留档时点；实现者的evidence-final/与早期失败／过程证据继续保留，不覆盖成独立结论。

最终范围审计基于派发前504份可解析非凭据仓库文件：无文件缺失；源码／测试／迁移实际改动仅上述16份backend文件。174份前端／宿主／旧迁移／MySQL链／保护及依赖相关基线文件hash不变，没有新增范围外文件；本轮仅新增一份数据基础报告，原15份设计Markdown与独有决定已保留／接续。该hash结论仅限此基线，不称全盘或真实数据审计。

当前分支codex/desktop-v2-foundation，HEAD仍为d52fa8a73032abbc1b325d218808670bda540e50，暂存区为空；未提交／推送。有效规格、六份Contract、索引与唯一当前入口已同步本片结论及停止边界，旧设计核定报告保留当时身份并链接本轮接续。ARCHITECTURE.md不变。

最终git diff --check通过；16份相关Markdown的276个本地文件链接均可解析。文档收口后210份后端文件与最终独立验证时身份仍相同，无验证后源码变化。

## 7. 用户后续Git授权（同日）

上述“未提交／推送”及HEAD描述为独立核查完成时点记录。用户随后明确要求调用OpenCode Go提交并推送，本次仅将已核定的产品／工程设计、六份Contract、本片源码／测试／迁移及审阅／接续文档归入当前分支；原会话使用opencode-go/deepseek-v4.1-flash#default执行，Codex独立核对提交范围、源码身份及远端ref。不得改源码或测试、重写旧提交、强推、构建、调用应用真实AI或启动E03等后续切片。实际提交身份以Git历史及远端分支为准，推送不代表产品或发行通过。

下一步建议按既定顺序准备E03材料切片：先核定Pillow依赖与合成容量验证计划，再做受管原图／工作图、实际解码／方向／格式、去元数据、顺序／说明与E01规范manifest映射、原子落盘／短DB事务／回执及失败保留。容量数字仍为提案；不擅自新增业务图数限制。这里只记录建议，未派发实施；保存历史、视觉AI、页面及Word／宿主仍按后续授权分片。
