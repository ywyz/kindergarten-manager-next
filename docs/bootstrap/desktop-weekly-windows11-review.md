# 周计划 Windows 11 新候选与 GitHub 构建核查

更新：2026-11-02。本轮用户授权新 Windows 11 周计划验证包，原生 OpenCode／Command Go 的 DeepSeek V4.1 Flash max可并行，Codex最终审核，构建及静态核查后提交推送；随后追加“在GitHub上生成exe供测试”和更新文档。目标电脑实际操作由用户执行，[测试手册](desktop-weekly-windows11-manual.md)列步骤和空白回执。

## 范围、来源与责任

开工 `codex/desktop-v2-foundation`／`796028b5dd90e53ce49fc9a0086bf464678789a0`，工作区干净。沿用本机 CPython3.14.10／Windows x64／标准GIL、Node26.12.1和既有锁定依赖；不修改业务实现或Q5/Q6。Q1–Q4及外观／备份源码的既有回归和GUI结果保留[原身份](desktop-weekly-plan-review.md)，不倒填成本次冻结包结果。

| 原生会话 | 本轮唯一责任 |
| --- | --- |
| OpenCode A，`ses_ead8af71dffeJphI1NOWg4jZgI` | 现有脚本新根构建及最终精确Git；不获其他源码写权。 |
| OpenCode B，`ses_e72ecd5f9ffeYJaLRNypsdu5Pi` | 新 `.github/workflows/windows11-weekly-validation.yml`及必要的单独CI脚本。 |
| Command Go C，`8cf528de-8773-4a06-9cc5-31e96fab515f` | 只读静态反例／校验器／目标交接审阅。 |
| Command Go D，`16cf76b5-ea0b-47f5-bc94-26147c9d3689` | 仅目标预检PS1当前Python正向值修正。 |

OpenCode固定build／opencode-go/deepseek-v4.1-flash／max；Command Go固定deepseek/deepseek-v4.1-flash／max。各原生会话不fork或另派子代理，不接管在途或还原他方修改。Codex负责文档、独立执行验证与最终审核；辅助审阅仅做只读／私有核验，不成为业务实现者。实际metadata与自然退出另核，不单用派发参数作证明。

提交前源码阶段实际metadata已分页覆盖本轮起点：A50／B161条assistant均为指定OpenCode Go Flash/max，C23／D15次model_request_end均为指定Command Go Flash/max；没有本轮model switch／compaction／parent／fork或子代理工具，agent switch均build→build。四原生均自然CLI0，A／B实际idle晚于busy；C首轮工具拒绝也包含在统计中，不以CLI0代替交付。后续Git新增metadata留独立回执，不冒充本时点计数。

本轮图谱服务list_projects返回Transport closed；按codebase-memory规则回读限定构建／校验源码，实际归档和来源以静态证据为准，不声称图谱证明闭包。

## 已发现问题及定点修正

目标预检PS1的build_identity.python仍要求3.14.7，而当前身份合同及本机已为3.14.10。D仅将该正向值改为3.14.10：61902→61903 bytes，raw SHA从`d7cdb39576a83ad76c71490b7416fa47e41f312acd8b7f1d8ca67bbc5ed1caaf`变为`d4a1cfc403a2cf161da74a6806bde95ac0fb3379255c353a2320d8b156c75761`。Codex独立反向单次替换完全还原开工原字节／SHA，其余不变；历史／负例／锁未改。D解析0错误，既有来源覆盖定向1项exit0，不称实际预检已执行。

C首轮dont-ask工具策略拒绝shell和写报告，exit0不代表测试通过。续同会话后，首次用了无pytest的系统Python（exit1），第二次测试相对路径错误（exit4）；均保留首失败。改用已有desktop venv和准确tests路径后，两份既有构建guard／静态反例测试**53 passed／3.38s／exit0**。该组是源码合成反例，不能代替实际候选归档；其合成Python子进程也不称候选运行或OS级网络0。

## 本机构建与静态核查

本轮唯一新根为`build/desktop-e14-weekly-win11-r01`；完整Vite→PyInstaller onedir/windowed→便携ZIP。freeze／hash／原始日志在独立TEMP，不入分发。逻辑ZIP仍名`KGNext-E14-win11-r01.zip`，以新物理根／build_id／SHA识别，不与旧r03混用。

完整构建exit0，未改hidden-import或其他业务／构建Python源码；实际静态证明新周模块已收集。272文件freeze在Vite前与完整ZIP后逐路径／size／SHA相同，缺失optional为空。来源为带已批准PS1单值改动及本轮文档／CI文件的`796028b5`，不冒称纯该提交构建。

| 项目 | 本机新候选实际值 |
| --- | --- |
| build_id | `eed767d9-64f1-4027-9137-f5646cff5633` |
| 版本／数据库 | `0.1.0`／`20261101_0007_local_weekly` |
| freeze digest | `a8d64c8cdd06eff26a26ed514f8282f9bae3f6c80c99996a897ea0d4bb312878`，272 files |
| ZIP | `build/desktop-e14-weekly-win11-r01/dist/KGNext-E14-win11-r01.zip`，44,130,507 bytes／194 entries |
| ZIP SHA-256 | `713c5cf17168851f8f1296be1dd9b4173cf931fb1f540a292dd3c9cce77ca516` |
| EXE SHA-256 | `26e79e6ccdc49f45e66a022dca03ccb487e7afa25bb5fcd1ec9397c628a6cd4a` |
| 产品 | 191 files／80,612,134 bytes；tree `b3f0db560ffc8dc70506f38a6a142364626dec79670729490cbae90000fa8042` |
| manifest SHA | `be8ccd784d9ec2c22d622bb6d716e65c8251ee1dc95ac448d481766128c5ceae` |
| SUMS SHA | `8d8e95d991ea28f4b856e10320758b2e60519ef7eb24e86af4338c33de4ec702` |
| 前端 | 3 files，digest `1c56cb73af6de65036d424e1b79068f6e490915daa04a783ce138e39b461f250` |

Codex在两个全新源码进程、导入校验器前安装外层启动／socket拒绝守卫，实际目录**54项**、ZIP**59项**均明确true；缺项／非布尔／unknown／failed、guard attempts及app imports均空，两个exit0。实际前端／模板／0001–0007迁移、清单／SUMS／ZIP每字节与当前来源核对，不运行候选。

另一个独立只读探针不复用原fingerprint helper，按全部代码字段／递归常量逐项比较，只忽略filename，float按位核对：PYZ1850模块中，78个app（含根）、23个生产desktop（含PYZ重复d1_main）、14个验证辅助，共115个项目模块均匹配；101个生产模块全部绑定freeze。全部12个CArchive代码入口亦匹配stdlib／实际PyInstaller6.22.3／hooks-contrib2026.8来源，包括bootstrap、4个pyimod、5个runtime hooks及主入口，无未知入口。身份commit／build_id／版本／schema／freeze／前端数量／产品tree／manifest／ZIP全字段交叉一致，**49/49／exit0**，errors／unknown／guard attempts0。

独立探针首结果只有一项失败：把12个`maintenance_source_*`验证辅助误按前缀分类为生产。首报告保持，私有分类最小修正后新编号复验通过；这些辅助代码仍逐字段匹配，但不伪称入既定生产freeze。最终私有报告SHA `203d88621c9224bc9701e563ef3207da740d381a4084f36c78fdd4308961fc66`；未改仓库以凑检查。

Codex按实际MZ枚举107个PE，只读签名为76 Valid／31 NotSigned，主EXE NotSigned；未签名或改策略。另在开发机新解压副本、PS7普通权限运行原字节新预检PS1，**49 checks／exit0**、失败／未知0，scope=self_current_machine_only；未创建业务data／credential根或启动候选。该结果不记作另一台电脑回执，也不改写旧PS5.1受阻历史。

既有五份受保护源仅核原保护指纹，均保持；旧E14四根873文件、旧win11-r01／r02各198文件原清单，以及本轮开工固定的旧r03产品／ZIP／合成种子198文件均保持。开工非docs／AGENTS跟踪集合中的变化只有根README文档和已批准的PS1单值；业务源码未改。私有保护探针最初把根README归进源码并触发严格断言，原结果保留，逐项核明确是授权文档变化后另出接受记录，未放宽旧制品或真实数据指纹。

## GitHub构建与下载

用户追加授权的GitHub Actions在现有桌面分支生成独立候选，使用固定CPython3.14.10 x64标准GIL、Node26.12.1、哈希锁及构建约束；只在临时runner安装锁定依赖，不升级本机／锁。运行环境的静态结果不等于Windows11目标运行。只在构建及静态全部成功后上传完整程序ZIP、原字节预检脚本、最小身份／SHA和手册；不上传业务资料、凭据、私有freeze／完整原始报告。

已新增工作流和单独CI PowerShell脚本：仅现有桌面分支push的产品／构建／手册／CI路径及workflow_dispatch触发，固定官方action SHA、contents:read、checkout不保留凭据、14天制品保留；不从PR执行不受信代码。初次工作流不在默认分支，采用本轮桌面分支push实际触发，不要求先改main。

首次代码审阅发现需修正的具体问题：runpy未将desktop放入导入路径、外层守卫只抛错未持久记录attempt、重复摘要的嵌套build_id读取不符，以及手册可静默缺省。原B在自有两CI文件内定点修正，并增加CI入口workflow／script的Git blob／tree与raw SHA前后补充身份（它们不在原272来源合同中），实际绑定commit／schema／build_id／前端数量；不为此改业务或原builder。pip显式使用现有build-constraint，未升级工具或依赖。

B从最终脚本提取真实守卫，读取本次真实本机目录及ZIP：54／59全部通过，两个实际attempt报告均0且completed；PowerShell报告读取器也实际读取这两份结果exit0，并拒绝非布尔／缺数组和被阻止的合成进程／socket反例。未执行整套CI脚本或在本机安装依赖。YAML及既有PS5.1／PS7解析通过仅作为语法证据，不冒称远端运行。

首次推送`47e408f7bbecd1f9bbbdae9228ccc4050fe140d7`触发[运行41359835746](https://github.com/ywyz/kindergarten-manager-next/actions/runs/41359835746)，平台在创建runner前判工作流无效，jobs为空、无制品：第35行第22列job env使用了此处不可用的`runner.temp`。普通YAML解析没有证明GitHub表达式上下文有效；首失败保持，不填作安装或构建失败，也不重跑旧包。后续仅由B移动该变量到允许runner上下文的构建step env，经新提交实际验证。

B r03实际仅移动上述定义，workflow为2增／1删；原CI helper raw SHA仍为`1bdb342c7dbffaa88049d940024b0fdf9cdaf163d17b2ab87b3c63018e97929a`，其余源码保持。语法／位置核查exit0，原54／59未机械重跑；新平台运行另记。

修正提交`57806b2a8d23639fdb7e371b7928d948c82a96ea`触发[成功运行41360367631／attempt1](https://github.com/ywyz/kindergarten-manager-next/actions/runs/41360367631)，job `125009248013`的工具链、锁定安装、完整构建、静态核查及上传全部success。实际CPython3.14.10／pip26.2.2／Node26.12.1／npm11.20.0；Windows Server 2022 x64仅作构建／静态runner。原始日志私有保留，非Windows11目标运行。

### 本轮交给用户测试的GitHub制品

[直接下载制品13104229266](https://github.com/ywyz/kindergarten-manager-next/actions/runs/41360367631/artifacts/13104229266)。制品名为`windows11-weekly-validation-57806b2a8d23639fdb7e371b7928d948c82a96ea-41360367631-1`，保留14天；API当前到期时间折合Asia/Shanghai为2026-11-16 07:08。登录GitHub后下载，先解外层，再按[手册](desktop-weekly-windows11-manual.md)核内层程序ZIP和PS1。

| 项目 | GitHub本次实际值；不得替换成本机值 |
| --- | --- |
| source commit／tree | `57806b2a8d23639fdb7e371b7928d948c82a96ea`／`de4279f8abb5d87869445930c7b133b610af979a` |
| build_id／数据库 | `0b56217d-026a-428e-a5d8-1b9f36960326`／`20261101_0007_local_weekly` |
| 外层制品 | 44,053,546 bytes；SHA `0509c25903d8687286d31cb04be5fef30c5322f44045b63a22562e809a35afa8` |
| 内层程序ZIP | `KGNext-E14-win11-r01.zip`，44,088,552 bytes／194 entries |
| 内层ZIP SHA | `5a8fea89cc8b61ffa70477acc13e9c76d166b07f2b1116cf58544a248d835c06` |
| 原字节预检PS1 SHA | `aef1c2021a0767d66ab4ccf53c72fbb0caa5c00d35910888036fe40539faeefd` |
| 手册SHA | `692132d29bf6a2a76125b6875b31eeb5a7d8b4e259aa70f7c22abbaabf9175ab` |
| EXE SHA | `d87db18f36ffd5b7517a096d670df3e173f30891d2e7a16bf8f178bb1724d9c5` |
| 产品 | 191 files／80,592,426 bytes；tree `ab3df4147c3a9165226234b07bcfa21d3296e9f3da50d73f1408ea538452f4a5` |
| CI freeze摘要 | 272 files，stable true，digest `d21fab4cf86fc4c14cba861c1bb562efa2a6bc066173402270150a185849e635` |
| 前端 | 3 files，digest `56bb8530008a03db2faa8711bddae7a9b877681805a9e46612e0bae526ff6dd8` |
| manifest／内层SUMS SHA | `a2703205209fb70dd140a3a31305c3bca372bd8c169ac71095db43ced6b7093b`／`6669dcb5fc5f50add8cdfd8f9c442ffd85aaf211d4c209d77d34c56fb06000fe` |

远端真实目录54／ZIP59均通过，两个Python外层守卫完成且attempt0；107个PE为76 Valid／31 NotSigned，主EXE NotSigned，未签名或改策略。workflow／CI script另以本次Git blob／tree及raw前后稳定摘要绑定。GitHub包和本机包分别保留身份，不要求字节相同。

Codex实际下载外层，SHA与GitHub插件API及上传日志一致；先核五文件安全清单再解包。下载侧独立受限核验**50/50／exit0**，errors／unknown／进程与socket attempts0：内层每成员实际字节、manifest／SUMS、身份、PS1／手册原字节、CI入口的Git规范blob与CI raw摘要均核对；115个项目PYZ模块及全部12个CArchive代码入口逐字段匹配当前源码／参考来源。未运行候选或应用代码。最终私有报告SHA `1c7a16bbc7c04f70982c60ce4b89132ff284717020cb6887399e1e81d95f1231`。

两份私有探针首失败保持：迁移目录8个raw差异逐文件证实仅CRLF/LF，7个Python文件编译全部字段相等，mako仅文本行尾；另一次把Git规范LF blob与CI CRLF raw误当同一字节身份，现分别核对。PS1和手册与本机也仅行尾等价，但交接SHA必须使用上表CI原字节值。未改交付制品来通过检查。

下载核验结论为PASS_LIMITED_SCOPE：CI原始freeze／完整报告未上传，未在下载侧独立重算其272文件digest；CI来源冻结证明仍来自成功job及其记录。前端只核本次CI身份／包内自洽，不借本机bundle。最小摘要的pip描述含公开GitHub runner安装位置，不声称完全没有绝对路径。静态、目标运行、Word、教师确认分栏；此工作不改main、默认分支、可见性、tag或Release，不签名、不作稳定发行。

## Git与未验

原A仅按Codex具体路径／raw SHA／规范blob／parent清单暂存；Codex核cached集合和tree后，才批准该parent／tree普通提交推送。候选及私有数据不入Git，不add-all、amend、rebase／force；提交身份以包含本文件的提交及远端为准，不为回填自身SHA循环提交。

首次11路径实际提交`47e408f7bbecd1f9bbbdae9228ccc4050fe140d7`，唯一parent为`796028b5dd90e53ce49fc9a0086bf464678789a0`，tree为`4f94c54b3e300ed74cecfd204bb470cf651a1a3b`；Codex独立核索引每项blob／raw SHA及cached --check0后才放行，实际远端相同、当时clean。后续工作流修正及最终文档继续按新parent／精确路径／tree门禁，不amend首提交掩盖失败。

第二次精确两路径提交`57806b2a8d23639fdb7e371b7928d948c82a96ea`，parent为首次提交，tree为`de4279f8abb5d87869445930c7b133b610af979a`；同样经独立cached blob／raw SHA／tree及--check0门禁后，由原A普通推送，远端相同、clean。最终只收口文档，包及工作流／CI helper／目标PS1／随包手册不变；可下载制品仍绑定该构建提交，不为最终文档提交重新造包或回填自身SHA。

另一台电脑预检／普通启动、保存重开、周旧确认保稿导出、完整备份接续、新周Word逐页及教师反馈尚未执行。当前4551机不启动候选EXE/helper，不改名／换路径或降低系统保护。微软拼音不重测，跨120秒睡眠不追测；旧无guard缺口、长根206、Win10／WPS／其它显示／干净机保持原未验。真实应用AI、WebDAV、签名、安装更新、远控和正式发行不在本轮；跨Windows用户凭据恢复不自动扩大。
