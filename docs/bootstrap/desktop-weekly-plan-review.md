# 桌面周计划与明暗模式实施核查

更新：2026-11-01。用户已授权按 [current](../tasks/current.md)实施、Codex审核后提交推送。开工分支 `codex/desktop-v2-foundation`，HEAD `d6de14cb85040e5e68e3eab36b6d34fd5c927f8b`，641个跟踪文件已固定开工指纹，工作区原为干净。产品Q1–Q6不重问；本片范围为手工周计划闭环与明暗模式，不启动周AI／材料。

## 当前结论

本片实现与Codex最终限定源码工程核查完成，原生均自然停写。完整backend1006、desktop553、C17完整前端typecheck／test:d1／unknown3均exit0；C16另有35组独立交互／竞态／显示／真实DTO合同通过。C18仅两处历史文案，独立typecheck／UI13及最后正常重开通过。真实保存确认、旧确认导出保留dirty、原生取消／占用失败／明确重试、两份Word全部8页、明文／加密备份及自动保护包恢复通过下述实际范围。按G4精确Git门禁普通提交推送；新候选、目标运行及新周教师体验未验。旧轮次“待修／未放行”按当时时点解释，首失败保留。

四个指定原生会话已实际续接；OpenCode使用build／`opencode-go/deepseek-v4.1-flash#max`，Command Code使用`deepseek/deepseek-v4.1-flash`／effort max。已抽核本轮实际消息metadata，最终停写metadata已复核，C18实际消息仍为deepseek/deepseek-v4.1-flash／effort max；Git续接另核。Codex只做合同、审核、独立执行验证与文档；实现仍归各原生唯一责任人。G0差异已归 [工程§11](../specs/desktop-weekly-plan-engineering.md#11-本轮-g0-接口核定补充)。

## B 纯内容专项

| 身份 | 实际结果 |
| --- | --- |
| r01 | 实现者27项与Codex独立27项通过；源码专项发现刷新重复／分类、日历差异、内部派生、显式重选、测试共存及空白缺项问题，未放行。 |
| r02 | 修复主要问题；Codex独立33项通过，但同步修改教学日无来源状态及manifest后仍被接受，独立探针exit1。三份日期同时伪造重复值已正确拒绝。首失败保留。 |
| r03 | Codex独立35项及两条补充篡改反例通过，exit0；源hash前后保持。父guard次数／日志均0、健康true，实际Python child guard自检通过。纯内容片放行，不替代A真历史／归属／备份校验。 |

r03源码SHA-256：`weekly_plan_content.py`为`f9fde90736aa50fa3b1522a22427b76cd9477417974d0e1d9c5f4d3a9666f7e7`，其测试为`e46096ab3ebc0f1820e6c4ae7e195f905ed524a3472834554a76326efdbe8c28`。接口与snapshot／selector schema不变。审核用codebase-memory Auditor及完整源fallback；metadata_changed不据为完整性证明。

独立命令为既有venv下的`pytest tests/local/test_weekly_plan_content.py -q -p no:cacheprovider`，由外层先安装NetworkGuard与child guard、设置APP_DISABLE_DOTENV，并使用新合成验证根执行；补充探针分别检查教学日无source的错误none_required状态、三层同步伪造重复日期。此前据环境配置称3.14.7，实际解释器纠正及本轮3.14.10基线决定见下文，不据配置文字认定实际版本。私有证据别名为`codex-b-content-r01`、`codex-b-content-r02`、`codex-b-content-r03`及各轮原生delivery／contract；原始日志和私有路径不入Git。

## C 主题专项

r01的11项与r02的17项均经Codex独立复跑，但源码审核分别发现未先GET核实、冲突状态未收敛、pending误禁用、并发初始化读取及GET/PATCH反序竞态、初始GET失败后的重试问题，未放行。r03的20项及两条原失败探针通过后，又独立复现“失败核实GET在途时点击retry，明确重试被旧pump丢弃”。首失败及各轮来源hash／回执均保留。

r04独立Node **21项＋3条原失败探针全部通过，exit0**，15个文件与交付hash一致且前后保持；只读专项确认T1–T4、U1/U2及retry队列缺陷闭环。最终`theme.ts` SHA-256为`5018997ae898e029b83702cf2bcbe848e2740b347906bc1b0bc717a3e18910d1`，测试为`9b0bdd5a069eeb88b358bc3ba7f235a606536118764db68721d31afee24a292f`；CSS／十一既有view仅颜色修改，未改业务流程。

独立命令为`node src/d1/d1.theme.test.mjs`，另在三个独立Node进程复验GET先于PATCH、初始读失败重试、reconcile GET中明确retry的原失败顺序。纯Node／Vue／mock API未启动应用Runtime或发送网络请求。证据别名`codex-theme-r01`至`codex-theme-r04`及r02/r03原失败日志保留；A接线、真实窗口、不同端口重开、实际可读性与照片／Word呈现仍待整合验收。

## A首轮与独立完整性反例

A首轮CLI正常结束，实际session已idle，29个交付文件hash全部匹配。其部分专项通过；所谓全local实际排除了日计划及观察迁移两个旧断言文件，另有1次负载下AI transport超时（隔离复跑通过），故不计完整回归通过。新的B完整性文件未被这组旧命令覆盖。

Codex在真实Alembic新库复现mode／正version／caregiver长度三项CHECK未生效，并复现首次并发token一真一假、非ISO日期与隐式bool被接受。原首次响应ID空／回放不同及缓存正文问题也有独立失败证据；A首轮末已补IDs和最小投影，B r02相应两项转绿，不将旧失败继续写成当前状态。

B新独立反例r02静态质量核查通过，源码SHA-256 `8ca942d88d86f53cecc380d0275d21fe292150b718ee7b486b63539e6918c38b`；原生实际17项为13失败／4通过。失败涉及真实迁移CHECK、同profile但错snapshot的token关系、NULL scope／byte_size、并发key、输入强制转换、实时日历比较、create上下文指纹及全历史真实性。该运行发生在A在途期间，只作分项反例，不作停写后完整源身份回归。跨term当时未覆盖，后续r03单独补。

历史篡改用非当前v2稿、当前v3：正常副本先验通过，再构造source与effective同值，B内部校验／规范content hash／生产source hash／已有receipt字段均自洽，真实日历史保持原文、FK为空；当前validator仍接受。effective-only另测内部派生损坏。两者不得合并成“只验hash即可”的结论。留库已改为显式环境变量opt-in、随机独占文件名，不把本机私有路径写入源码或覆盖首失败。

返修已明确唯一A责任，B测试文件不得由A削弱；新确认／回执strict schema及用户补充的零教学日日期规则归工程§11.6。各轮原始日志／合成库保留在私有证据别名 `codex-a-schema-pre-r01`、`codex-a-pure-pre-r01`、`codex-a-response-pre-r01`、`B-integrity-r01/r02`、`A-g1`。最后仍须停写后独立整合及完整备份恢复。

A r02在途新增的snapshot helper又经独立窄审及纯函数执行：基准合法快照通过，但11条变体未正确拒绝／日期不符，exit1。涉及bool／float schema版本、class／term／header／周次与manifest不一致、创建学期无交集、非结构化facts、未规范正文，以及零教学日仍与保存稿basis学期相交却错误回退创建日期。该helper SHA-256 `bc1da43a22abab52de45a95051d0fda50a752b1abfb09fd189c4c83a99c3d56e`，四依赖前后稳定，父／真实child guard通过且attempt／log0、audit健康。证据别名 `codex-a-snapshot-pre-r01`；这是在途限定身份预审，须与r02最终交付重核，不是整片通过。

A r03的helper SHA-256 `4243cb16d0730bd3a24fcc6262584770598bc840a0061f0752c778a8e725f89a`下，上述11条由Codex独立复验全部通过，exit0；非法值必须抛明确LocalWeeklyInvalid，意外异常不算拒绝通过。合法基准仍通过，四依赖前后稳定，父／真实child guard自检通过、attempt／log0、audit健康。证据 `codex-a-snapshot-r03`。该组已在此身份闭环；A3整片仍在途，若helper后来改变须重核，不替代manifest／备份及整合门槛。

同一helper身份下，新manifest validator另有9条独立反例错误接受，exit1（4个合法正对照均通过）：顶层profile与item不一致；selection确认／稿／周次为等值float及确认版本为bool；warnings缺归属ID；空range选集；仅周一／周五教学却选入周三；零教学日仅靠回退date_range入选range。须按冻结教学日期相交、严格类型／规范比较及完整归属校验，不能只比较首末区间或Python相等。证据 `codex-a-manifest-pre-r01`，四依赖稳定、父／真实child guard通过且attempt／log0、audit健康。该项是A3在途限定身份新预审，不抹去已闭环的11条确认快照反例，也不算G1通过。

## A r02交回与剩余门槛

A r02的原生专项34项、配置／初始化／schema／日计划／观察迁移等110项、备份快照／恢复核心65项、B内容与完整性54项各自通过，前端typecheck／test:d1通过。35份源码交付hash均匹配，CLI exit0及session idle已核。上述分组有重跑／覆盖重叠，不合计为全量单轮通过；恢复崩溃专项首失败及隔离复验仍保留。

B integrity r03最终SHA-256为 `7f7ca6014dc92a819815a7e7c7428896527959e55db6e47dd6a89175383a2b5d`。新增正常配置移动旧学期、创建新学期的跨term反例；flat receipt、确认target与生产新source_context_hash／真实相关配置投影也已独立源审。r03原生8项专项通过；A随后完整跑35内容＋19完整性共54项通过。J2补充日志明确拒绝原因为真实日来源文字不符，未被旧hash算法或回执形状错误掩盖。Codex停写后整合执行仍待后续统一完成。

G1仍未放行：A3已闭环上述11条纯helper反例；backup刷新依据、导出manifest嵌套与真实确认关系、仅手工周的配置影响，以及cold prepare／同Runtime退役处理仍须按最终身份专项核。work生产／清理和D manager依赖在G2后另核，不冒称已有。精确确认及manifest统一结构已归工程§11.6／§11.7，返修仍由A唯一负责，不改B断言。

## A r03独立HTTP／DB核查

实际回环HTTP正对照完成建档、外观200、周新建v1、保存v2／v3及详情v3。列表GET却为422：路由装饰器错挂日期helper；operation GET虽200，却只有8键内部metadata，没有operation/request ID或原v2正文投影。五依赖hash前后稳定，父／真实child守卫通过、attempt／log0、audit健康，exit1；证据 `codex-weekly-api-pre-r01`。这两项没有被service直调或原回放测试覆盖，必须补真实HTTP测试。

真实生产确认记录上构造完整合成snapshot/token/export_create receipt，created早于expires，校验时已过期，正常副本先验证通过。只把manifest item及selection中的确认版本1改999，保留真实ID、14键正文及确认hash，并重算manifest hash，纯结构仍合法、FK空，备份却接受错误版本。五依赖稳定、父／真实child guard0且健康，exit1；两份DB及原合成根保留于证据 `codex-export-version-pre-r01`。外层须核真实确认行版本，不能仅核正文hash。

配置影响已补周计数、相关周premise及日／周分列，正常保存／确认会使旧相关预览失效；源码仍将包络内其他term的周与本次term变更范围混用，缺所属term的新建资格字段；展示的全局周总数也未入写锁内premise，包络外周在锁前间隙新增／删除可漏过。此两项为稳定源预审，动态专项由A补。R2合法刷新与R5 cold prepare／同对象退役接入点已源核闭环，D manager／work仍待G2。

## A r04交回与最后窄修

A r04已CLI exit0、session真idle，38文件交付hash匹配，HEAD保持c78ccc4、index干净。定向整合204项通过（287.85秒），含真实HTTP新测试、配置、备份／恢复及冻结B内容与完整性；前端typecheck／test:d1通过。这是原生定向组，Codex最终停写独立整合仍待执行，不与前轮数字相加为单轮全量。

原四组复现均在A4新子根转绿：原9个manifest反例、11个确认快照反例、真实HTTP列表200及原v2回执投影、真实过期导出metadata的确认版本999篡改拒绝。HTTP调用新get_business_operation投影WriteResult，原service get_operation保留内部flat metadata合同；两者不得混为公共协议。预览明确返回创建时配置前提及有效期；配置影响增加所属term的新建资格及锁内总数前提，独立源核与锁间隙probe随后复核。

同helper稳定身份下，Codex额外4例仍失败：warnings归属ID值为数组／对象时抛TypeError；顶层missing中原details整数1被bool／float替换，Python相等仍接受。原9例已拒绝，合法marker正对照通过，四依赖前后稳定，父／实际child守卫attempt／log0、audit健康。证据 `codex-a-manifest-extra-pre-r01`，返修r05只允许helper及其自有测试，不动已闭环API／配置／备份或B/C身份。

A4曾误调用A3的guard runner一次，旧guard-run摘要被复写；A3原始JSONL及交付中的guard结果仍保留，不以被复写摘要新增A3覆盖范围。随后A4使用新根runner；最后窄修及Codex验证全部另建新根和独立receipt，保留首失败。

r05仅修改统一helper及其测试，原生15项通过、CLI0／session真idle；相对A4其余36份交付文件原字节保持。helper最终SHA-256 `d1f07fa2da09e6fc173b08800804d75f435b3fa589abf935fc5b0cac15428bfa`，测试 `e804b019b91a13a74454491dfd442f7c438518710de778bc0ea41231ba1b31e8`。Codex在全部会话停写后独立执行manifest13例、snapshot11例、真实HTTP及真实DB确认版本篡改四组，全部exit0，各组源前后稳定、真实child自检通过、guard attempt／log0且audit健康。证据分别为 `codex-a-manifest-extra-r05`、`codex-a-snapshot-r05`、`codex-weekly-api-r04`、`codex-export-version-r04`。

R4独立真实HTTP进一步完成A九月周→A移十一月→B九月同锚点新周，再预览修改B日历，证实A仍误带calendar override原因，首失败 `codex-config-impact-r01` 保留。另一次独立锁前hook仅命中一次，用不同HTTP请求正常新增包络外周，总数1→2、相关周集合不变，旧apply返回409 CONFIG_PREVIEW_STALE且未写配置回执；`codex-config-impact-prelock-r01` exit0。两组488源前后保持、child／guard健康。原term资格与总数锁内前提已闭环，r06只修剩余日历归属，不重复重做它们。

## 远端回执与文档整合

用户通知后已读取远端 `f7986f0` 的目标1实测、`c78ccc4` 的W1–W8逐项教师确认；两提交均只改五份Markdown，无源码差异。A r02停写后，本地普通快进至c78ccc4；只暂存本会话负责的两个文档到自有stash，使用已核合并稿保留本轮开发授权与远端独有结论，其他59个在途改动文件原字节全部保持，index干净。两次远端提交保留为祖先，未rebase／amend／force；本轮实施尚未提交推送。证据别名 `docs-integration-c78`。

## 持续边界

固定r03目标1的启动、保存重开、完整备份／恢复／保护包及指定八份Word教师确认已归[目标记录](desktop-windows11-target-review.md)。该反馈已评估，无需因等待旧回执阻挡G2，但不能替代新周核心门槛或迁移为新包通过。未运行已知4551机受阻EXE／helper，不安装升级、不改系统保护，不调用应用真实AI／WebDAV、签名、远控或公开发行。本轮新源码窗口、原生保存、Word、目标机和冻结包仍各按实际证据另记。

## G1最终独立结论与当前环境

A r06修正跨term日历原因后，Codex再复现影响总数仍按展示两行计为2；原A测试只核单个reason计数1，未证明affected总数。首失败 `codex-config-impact-r06` 保留，r07只修config service及其测试，交付hash匹配／CLI0／真idle。最终config SHA-256 `a68efcfd68d4b7821bee56642cd20a7c69b63361fb8ac056ef7ae199b0dacb83`，其测试 `fc80e15a3968cb2039eb71b28bf835b33000d8d86eccc3ad42e27dc98899d86f`。

Codex九文件整合为149 passed／62.75秒，含外观、既有配置及全部周计划测试；frontend typecheck与test:d1均exit0。最后两文件统计增量后，其余486份源原字节保持，再独立跑两个config文件50 passed／26.60秒，以及正常跨term查看／编辑／确认与真正读取后锁前新增周的完整HTTP probe，全部通过。149与50有重叠，不合计为199项单轮。两轮均488源前后稳定、APP_DISABLE_DOTENV前置、实际child守卫自检通过、attempt／log0且audit健康；证据为 `codex-g1-integration-r01`、`codex-g1-config-r07`、`codex-config-impact-r07`。结合已闭环的四组独立探针与源核，G1放行；本结论不替代G3全量／GUI／Word。

独立回执实际CPython为3.14.10。本轮使用的backend/.venv与desktop/.venv-d1均指向同一Python安装，配置创建信息仍为3.14.7，而实际均为3.14.10／Windows x64／标准GIL（Py_GIL_DISABLED=0）；已安装launcher未列3.14.7。用户于本轮明确选择沿用现有3.14.10、更新当前基线且不改依赖。本会话没有安装／升级／降级解释器或重建venv；此前仅据文档称3.14.7的表述以实际回执纠正，不把本轮测试冒称3.14.7通过。A在G2a只更新两个.python-version及新来源校验期望，历史r03身份、旧证据和锁定依赖不改。

## G2a首轮交回与返修

A首轮15文件hash匹配，原生32项source registry及44项维护专项通过；D文件在途时app整合未运行，static／U2相交失败保留，不视为整片通过。独立源核发现SnapshotService构造缺参数却读未定义名、正常关闭及clean busy未接manager、handover在拒active前先pause、同binding closed重建、preview ready与同owner install竞争、Thread.start失败遗留pause六项。A在r02内唯一返修；另按用户新Python基线明确授update_identity.py常量最小更新。其它正确的app固定引用、retire前置等待与旧dispose错误收尾保持。

D首轮真实CLI exit8／stopReason=max_turns（90），只有在途service且纯compile在1512行报粘连换行SyntaxError，没有完整API／测试交付。保持原D会话／固定模型，r02延长180回合续接；首轮日志、退出及源码失败保留，不把回合上限停点写成完成。源码结构验证不等同Windows Word页检。

C首轮三文件hash匹配，原生18 checks与typecheck通过；Codex独立复跑18 checks，94份frontend源前后保持。第一次父runner误用Git子目录相对路径而选中0文件的receipt不计来源证据，已在全新r02以--full-name及必需路径断言纠正。随后独立3条unknown反例全部失败：manual保存不明后新输入，query原v2不推进baseline／serverID；confirm未留原ticket，query错查旧save；没有明确再次提交原请求的方法。GET404不自动重发及Q3不明后停止的正向均成立。四依赖前后保持、mock network attempts0；`codex-C-unknown-r01`首失败保留，C r02只修原三文件并补公开retryOriginalOperation，不接页面或共享文件。

## G2a追加核查与G2b页面首轮

C core r02经独立23项、typecheck及原3条unknown探针通过，94份前端源保持，纯mock network0；随后放行四页面。A生命周期r02的11文件指纹匹配，源核六项遗漏均已闭环，原生维护、备份及registry专项通过；原U2两节点仍用3.14.7构建夹具造成INSTALL_PROCESS_EXITED，A页面片仅更新三个实际当前Python字段到3.14.10，旧0006协议与revision不改，完整process测试另待G3。

A/C页面首轮14个交付文件指纹全部匹配。Codex独立frontend typecheck和完整test:d1均exit0、99份前端源前后保持；该命令中的unknown探针先因父误给嵌套证据根被harness拒绝，不计应用失败。使用全新直接子根`codex-C-unknown-g2b-r02`后原三条控制器恢复探针全部通过，四依赖保持、mock network0。UI原五项主要为编译与字符串检查，不能证明教师行为。

页面源审仍不通过：四个周栏目绕过controller而不dirty／不保存；unknown恢复函数未挂按钮；refresh缺原请求恢复及dirty保护；异步写开始未及时上报busy；当前稿导出未接Q3；页面重复登记native attempt且伪补saved hash；创建／导出unknown票据可被清掉；确认／历史目标展示不全；缺范围导出入口；面板迟到响应及IME settle保护不全。均交原C唯一返修，范围仍为自有八文件。A仅修无当前bridge仍接受旧busy=true的身份漏洞，并补独立shell行为测试，不接管C实现。已保存C旧交付十一份源副本作独立反例身份；G2b仍未放行。

上述C固定旧源另经真实Vue inline-template／内存renderer及实际controller的独立行为probe执行，五例全部按预期暴露缺陷、exit1：四栏输入不dirty且保存0 PATCH、clean确认在途busy=false／blocking=null、unknown创建重开丢原票据、refresh查询找到回执却不推进v1基线、refresh明确重提没有第二次POST。无框架／component／unmapped错误，十一份源及清单前后保持；真实网络／子进程尝试0，合成fetch14。证据`codex-C-ui-pre-r01`。这不是浏览器／IME／原生或Word结果，C返修后另以新身份复跑。

A窄修r02三文件交付hash匹配；Codex独立执行实际App setup中的身份过滤五例通过，十份相关源前后保持。无bridge、错误identity及reset／切周后的旧消息不再改变当前busy；正确identity的true/false均有效。证据`codex-A-shell-r02`；完整前端待C停写后另跑，不与这五例重复合计。

D backend r02三文件指纹匹配，原生12项及26项定向组通过，但独立真实HTTP／work专项仍失败。`codex_weekly_export_api_probe_r02`的首个manifest失败是父harness误写profile字段，生产profile_id正确；纠正后r03保持原协议，不要求生产迁就错误断言。`codex-C`等前端证据与D无关，不混计。

D实际首失败：`kgm-we-work-pre-r02`中manager构造删掉两份本合成根的未知文件；`kgm-we-api-pre-r03`中取消后新retry虽登记成功、start返回200，固定DOCX下载仍404。此前预览零DB／work写、旧确认跨新head仍生成原内容、同请求回放、最小八键回执及原token下载等已通过。两组284份后端及guard源稳定、实际child自检通过、attempt／log0且audit健康。另源核发现下载引用／publish时序、关闭后回放、路径指纹／receipt真实性、锁内TTL、实时来源提示及Word学期外／年级显示遗漏；原D在r03统一返修，host尚未放行。未知删除仅发生在新合成根，原数据与旧现场未触及。

D r03再次达到180回合上限，真实exit8、无完整delivery，固定三源副本及日志保留；续原会话r04完成交付，真实exit0。三源hash及284份freeze `ed22654fe58922b1fa03ec1cd736fb63f4a0dadd3fb3eb3853afe0e53edcbcdf`匹配；原生21项export与47项export／snapshot／backup定向组均过，21已含于47，不合计。父同一脚本由D在新根`kgm-we-d-r04-http-b`（含自动备份创建／校验）和`kgm-we-d-r04-work-b`执行均exit0，284来源完整且保持、真实child／attempt0／log0／audit健康。此前18／48文件窄freeze漏导入闭包的失败保留，不据HTTP自身已完就计完整源验证。

固定D3／D4源核仍发现：删除alias后既有流释放按旧hash找不到entry；response首发失败尚未迭代时generator／background均不能保证释放；download漏完整file_scope；work junction与检查后替换删除窗口；OwnedTemp尚仅交路径而非已验证读取句柄；HTTP层manager缺失仍挡原receipt。交原D r05在三文件修正，复用既有DirectoryGuard／FileLease的能力，不改通用backup_fs／credentials、不重构日／观察。host保持未放行。

固定D4镜像另由Codex独立真实执行三条生命周期反例，全部暴露缺陷exit1：原alias退休后的既有ref不能归零、download活动未阻塞真实SnapshotBarrier、实际响应在首http.response.start发送抛错且尚未迭代时未close真实Artifact。generate文件屏障正对照通过；无框架错误。三份镜像及263份A／guard依赖前后保持，原字节直接编译未读D在途源；真实child自检、parent／log0／audit健康、SQLite连接0、额外子进程0。ASGI例仅认证／Session／内容选择边界fake，实际执行固定API返回response及Artifact／manager释放；无Runtime、真实DB／服务器、native或Word。证据`codex-D-manager-pre-r01`，D r05后按新接口身份另复验。

共享metadata validator另有独立实测首失败：整数1正常，bool true／float 1.0也被接受，0／2／字符串／null均正确拒绝；`codex-metadata-schema-pre-r01`exit1，281份非D后端及guard源稳定，实际child自检、parent／log0且audit健康，未运行Runtime／DB。A仅解冻operations helper与自有service测试两文件修正；两hash匹配且其余279份源保持。Codex同一七例在新根`codex-metadata-schema-r01`全部通过exit0、相同守卫与闭包条件。最终helper SHA `ac1317754e84f87e00607e3e09a58afb91c2d2563d59cf234887eba518689bbc`、测试 `3cde202b68ab9274baccc5aca0ada2bfc3ca6d5ed10abf673f2a2ac8a22d1cad`。D最终共同来源冻结须包含此新身份，不以D4旧helper结果代替。

## G2b追加独立行为与导出生命周期复验

C r02的十一份固定源在Codex真实Vue模板／实际controller探针中五例全部通过；后续九条竞态反例中，稳定同代host正对照通过，八条暴露真实遗漏：创建在途修改输入丢原票据、未知导出重复生成换key、迟到范围预览、disabled或host切换后仍开native、composition reset后旧保存、过期未发native仍永久busy、未知retry重提走错create路径。证据`codex-C-ui-r02`与`codex-C-ui-races-pre-r01`，均无框架错误、真实network／child0、十一源保持。

C r03自然停写，八交付hash匹配；Codex重新复制十一源（manifest SHA `ea3d18f49169f44270c1ee18eb8cb157004fdb265da5124a76dfbcbe5b8b1607`），原五例与九条竞态全部通过，证据`codex-C-ui-r03`、`codex-C-ui-races-r03`。前者合成fetch16、后者17，均无框架／真实network／child错误且十一源前后保持；五与九为独立分组，不代表浏览器或原生验证。C原生core31、UI7及typecheck通过，原未知恢复三例亦通过。来源facts／候选与接受的draft版本绑定、其他未覆盖乱序和实际GUI仍须另核，未据交付声明直接放行。

D r05三交付hash匹配；原生27项导出包含于53项定向组，两组通过；同父HTTP＋备份及work专项由D在新根执行通过。Codex固定三源（manifest SHA `44c0c97eb2cc0077c699311e95a54493157aece697ca493c05893acf997d5ce2`）独立四例实测：alias退休后按entry ID释放和真实download文件屏障通过；实际content route仍返回普通StreamingResponse，新增finally包装未接线，首start发送失败仍泄漏；OwnedTempRead的无参数read与fileno不可用，存活读取lease未阻wait_idle。真实ZIP读取正对照通过，不能将两个接口缺陷扩大为所有ZIP失败。证据`codex-D-manager-r05`，receipt SHA `3f6652829e3634164a5292a6001d68494ea1c086dae62ce385b87207735c9be5`；四例均执行、无框架错误、三镜像及263依赖保持、实际child自检／attempt0／log0／audit健康，SQLite连接和额外子进程0。源核还发现存活writer、finish交接和close的窗口，交原D r06在同三文件收口，host仍未放行。
C固定r03另执行四条deferred恢复反例，三条失败、确认同步双击一条通过：曾native unknown后metadata过期无法查询原回执，props切H2仍无法回原H1查询，以及query已确认commit后迟到retry错误复活busy。均真实SFC事件／实际controller、无框架错误、十一源保持、真实network／child0、合成fetch13；证据`codex-C-ui-deferred-pre-r01`，脚本SHA `0bdced707296dde9f5944eca6a5dd67ed3f36883e306db1b5b45352d0090b3d5`。结合源核的facts／候选旧投影、refresh等待后旧发送、save单飞遗漏settle窗口及History日来源重点指导遗漏，交原C r04修正。确认双击、Q3最终sequence复核、完整候选key和刷新正文展示已闭环，不因新增返修抹去对应通过结论。
C固定r03的实际controller补充三组探针均暴露缺陷exit1：v2精确tuple正对照仍不更新facts／候选；settle期间reset后仍发旧refresh、settle拒绝遗留busy；两次save共享待结束输入仍各发PATCH。逐项draft id/version/hash不符及GET v3／晚输入的正反向也在同组执行，不把组数当单条断言总数。十一源保持、无框架／真实network／child错误、合成fetch8；证据`codex-C-ui-core-pre-r01`，脚本SHA `470616e5aff0f831892524464d81b72c5879c59e8b62ec5134279f7ea7feb8a2`，receipt SHA `bd4cac569dbe6ede8966cd53c8145013b4d7d7200572c44c7008d58d2b750ba1`。均已包含在C r04的原合同返修，不新增产品行为。

D r06三hash匹配、原生30项包含于56项相关组；Codex固定三源manifest SHA `7c286721ec112a154a1fae6b30c21d7ed50edf70e9a107ab7600e52978a2913c`，原四条独立manager反例全部通过，receipt SHA `d3f3159790fa1ea2df50127757ba5572082de59d686de5bc43357db02c0613c9`。三镜像及263依赖保持、实际child／attempt0／log0／audit健康、SQLite与额外child0。另源核确认create登记、finish交接、release清计数先于真实关fd和close过早释放根guard的窗口仍未闭环，交原D r07精确收口；不以四例已过扩大为全部生命周期通过。宿主预审同时补工程合同的可信到期header，服务物化token／snapshot较早期限，host在完整下载并取得共享mutex后、开框前立即核期；页面不提供期限，不改变既有原生对话框可完成的产品规则。
C r04八hash匹配，原生35 core／8 UI／typecheck及unknown三例通过。Codex固定十一源manifest SHA `2898917259967c77a9e1f91ffb353483d03291ae21305ba974222fd5e40c6e62`，九竞态及四deferred恢复均全过，tuple五矩阵／settle reset与reject组通过，真实network／child0、来源保持。原五UI的refresh两例先被父harness未登记新增安全detail GET拒绝，均无断言失败；新私有adapter仅补这一个精确GET fixture，不改原脚本或行为断言，同五例全过。adapter SHA `1961a2ebac485047aee6a7d6092a1baf75977986879b917c3fd7e2a604a0bae2`，证据`codex-C-ui-r04-adapter-r02`；初次框架记录保留，不计应用缺陷。

core第3组实际已只有一个PATCH并保存最终IME模型输入，首caller成功且最终clean；重复caller却提前返回indeterminate。源核另发现unknown早退遗留saveEntry及旧finally无所属flight／epoch约束，交原C r05在core及其测试最小修复，前面已闭环页面保持。该片另只对原十一色值视图去多余EOF空行，保留此前字节，避免将格式清理混入业务修改。actual browser／IME／native／Word仍未执行。
D固定r06另经六条私有manager探针执行，前五例通过，第六例以真实FileLease打开后、另一线程close的确定性交错暴露孤立reader：发布后的reader未被计busy，reader.close后实际fd仍开，known临时文件仍在。无sleep猜测或同线程RLock重入，线程均正常结束，finally独立关闭本探针捕获的自有lease，未清未知文件。三镜像／263依赖稳定、无框架错误、实际child／parent0／log0／audit健康、SQLite及额外child0。证据`codex-D-manager-handoff-pre-r01`，released脚本SHA `3343f1c8fcaba6151f7c424c11d0c34a6fa4d13d0d567fb8c6ed7ae2aec40a02`；D r07已按同窗口修复，后另以新身份复跑。

C固定r04的扩展flight探针确认：unknown核实为v2后，期间一次saveCurrent调用遗留entry latch，之后新输入仍不能保存；reset后同controller新epoch也被旧entry拦住，因而旧／新flight重叠后的finally断言明确记为未执行，未造私有state假覆盖。五组中tuple／settle两组通过，其余三组失败，无框架／真实network／child错误、十一源保持。证据`codex-C-ui-flight-pre-r01`，脚本SHA `1c699f43a635d2adcabeeb58ff6db0f36d2e73f900b58c5be97a626ab0445bb7`。C r05后须实际执行原完整重叠路径，不据早期失败推定后段通过。
C页面r05仍有query busy reason起止不一致：精确query已推进v2并清unknown，唯一reason未删除，busy永久残留；独立flight恢复例暴露该点，交r06仅两文件修正及补断言。r06两hash匹配，Codex十一源manifest SHA `71afbbc7c01982411391e94e9385c158e123f41b234092da2a0b81129902b22b`，五组件行为、九竞态、四deferred恢复和五核心flight共23组全过（矩阵内另含多项断言），真实network／child0、十一源保持，无框架错误。最终core SHA `dd44f245c3b126f6e4bbd0633f7986655909a930c95ddd9b11ce5ac09b9e35d0`，测试 `f3d05ec4d85f81175492588e9ff815e26c04602f9f3a93c8e0ef4e9d6bc011d7`。另独立typecheck、core38／UI8及原unknown三例均过，100份前端源保持；r05完整test:d1已过，r06只两core文件变化按影响定向复验，未把两身份混计单轮。证据`codex-C-ui-r06`、`codex-C-ui-races-r06`、`codex-C-ui-deferred-r06`、`codex-C-ui-flight-r06`、`codex-front-g2b-r06`。C工程片放行并冻结，实际GUI／原生／Word另待G3。

十一旧主题视图只改末尾换行／空行；Codex重建原尾字节验证正文最后字符之前原字节不变，before SHA与G1冻结11／11匹配。部分原LF尾规范为单CRLF，不能称所有原尾换行保持；逻辑与色值未动。证据`codex-C-eof-r05.json`，git diff --check exit0。

冻结C前端在全新合成UI根构建成功，Node v26.12.1、100源前后保持、三个产物；根及frontend均首次创建、八个env文件仅查存在且全无，子环境移除继承VITE变量名而不读其值。证据`codex-front-build-r01`及源数量字段的私有metadata纠正，不涉及解释器／依赖变更或候选EXE。该构建尚未运行应用，不能冒称GUI通过。

D r07完整独立HTTP＋自动备份、work未知文件保留、学期外Word空白／中文年级、8周窄范围与第9周整体拒绝、旧8周预览固定生成均过；容量DOCX机器结构为8表／7页间break，不是实际Word页检。四组284源及freeze前后保持，actual child／attempt0／log0／audit健康。manager首并行运行被标准SQLAlchemy import的platform.machine→Windows版本fallback尝试cmd ver触发私有额外child审计拒绝，0例，不计应用失败；未放宽守卫，同一脚本串行新根六例全部通过，source稳定、DB0／额外child0，证据`codex-D-manager-r07-serial-r02`。各首失败保留。

D r08两源/API不变hash匹配，原生38包含于64相关组；Codex同一第7条fsync故障探针在固定D7前六例过、第七真实暴露未关writer，在固定D8七例全过，3镜像／263依赖保持、实际child／attempt0／log0／audit健康／DB0／额外child0。probe SHA `2b819d7072021b30906d329275c17d4b6787a2709c3efc2095aeafc0256463ee`，证据`codex-D-manager-fsync-pre-r01`与`codex-D-manager-r08`。末次源核仍发现abort恢复期间持续close失败会被先pop后吞异常而丢真实writer；r08自测只在故障解除后abort，未覆盖此点。交原D r09仅两文件修复同一恢复链，API冻结；host继续待核心门禁。

D r09两hash匹配、API未变；原生38项包含于64相关组。Codex在固定D8镜像实测第8条“close故障持续→owner.abort→retire”反例，前七过、第八失败；同一released probe SHA `525101be6f892954f0dc9dd1eac5256207b7c614fbdbE60df0d41b6dd3bbca19`在固定D9八例全部通过，含真实root guard句柄／原writer fd保持与最终释放，3镜像／263依赖前后稳定、实际child自检／attempt0／log0／audit健康／DB0／额外child0。源审确认仅同一恢复链差异，持续故障不再先pop丢owner，解除后实际清理且幂等；D backend工程片放行。

最终service SHA `4b1a5bdc80be87237ecefac086eb09c62ee0ab4bef9726fb2ad2f72b03e1e529`、API `b8647e8ca3bd3ec134ae66ebc2f6ab2283b8a0adcee78d0f1a830fec5165aa0c`、测试 `a850c5cf8e4238e0eb4bc52b939aa06d1a267ce5d02451c48e8d6a0a0e5125f4`。父284源freeze SHA `20a97d141029fe0109b5b6e335da9af592d9959fef9240cf47b46fa786c66766`；独立真实HTTP＋备份、work未知文件保留、Word学期外空白／中文年级、容量8／9及旧预览固定8四组在新D9身份均全过，源／freeze保持，实际child／attempt0／log0／audit健康。Word结果限机器结构，不移作原生保存或实际页检。证据`codex-D-manager-r09`及`kgm-we-p-d9-http-r01`／`work-r01`／`bound-r01`／`cap-r01`。

随后只放行D的host及独立host测试两文件，backend冻结。A另仅在d1_main两个构造注入当次app.state固定manager；终点SHA `ff2f95ee19de1c3231d443a2c66f5ad007fe84ad817ea1530a75e239ad07f3db`。Codex独立按原副本逐字节去除两段keyword，完全还原起点，并核AST除两keyword完全相同、两值均为getattr(app.state, weekly_export_manager, None)、compile通过；无app imports／runtime声明。该片实际OpenCode assistant metadata为opencode-go／deepseek-v4.1-flash／variant max。A已停写，D最终共同freeze须含此身份；真实整合另待D host停写与G3。
G2b显示补核：C r07固定十一源manifest SHA `10bdb714ba331f20695fc50b1fe9263658ecfa97a9dbb2ae9818b89eb18b9d48`；独立实际Vue SFC显示探针在C6对照确认完整范围正文／中文／来源日期遗漏，C7已通过冻结正文全字段／中文／冻结day来源日期版本，但仍漏历史及导出缺日期查询的入口接线，并有教师文案null。C8仅原五显示文件收口；原core两hash不变。日期补读用既有完整日GET，其当前内容验证失败的局限已归工程§11.11，不将显示查询变成历史有效性门禁。首证据`codex-C-ui-display-pre-r01`、`codex-C-ui-display-r07`均保留，不记为通过。

D host r01 Codex实际Runtime＋loopback＋原atomic writer五组通过：真实另存改名、重复与查询零重写、已提交回执丢响应核原attempt、维护／退役拒绝写、取消；401源保持，actual child／network0及自有DB审计健康。只有选择路径边界为计数替身，不能称原生GUI或Word页检。证据`C:/kgm-wh-d1-r01`。随后源核明确清理掩盖结果、manager已知attempt错误、indeterminate原五键补记、Windows basename、规范UTC、开框前epoch及退出后缓存七处问题，交D原责任收口。r02四文件hash及401源freeze `88c12508cd03ec1f8be0ba08f081a2ff07c5bd4d318b4c380458fd1d1c207e3a`已核；新basename helper变化使D9旧backend门槛成为历史身份，最终再按新身份核查。r02独立源审仍发现真实_retire会清page_ready而挡缓存、尾空格被strip静默改名及零微秒UTC非规范，D r03定点修复，API/main保持。

私有host异常探针首执行误选非本轮desktop/.venv的3.12.10，被前置基线拒绝且未创建应用根；随后正确desktop/.venv-d1（3.14.10）执行在`C:/kgm-wh-d2-adv-r02`，守卫／自有DB／401源保持，但探针自身漏export:哈希域及误用LocalClient调用形状，未取得六组有效结论。原首现场保留；新私有r03修harness并隔离非法名与合法正控token，不弱化断言。该失败不算应用缺陷或六组通过。

C r08交付五hash匹配，固定十一源manifest `a81a27a542d081aa6d4cf8b1d707039f37575a03b0f8b99811febafa3327623c`。Root原23交互组＋4冻结显示组全部通过，network／child0；完整前端typecheck、test:d1及原unknown3过，100源保持。末次单独新增入口反例在同一C8镜像保留原4显示组通过，仅initialPreview直入缺date的3断言失败（正常API入口和迟到确认A→B已过）；C9只ExportDialog及自有UI测试两文件补齐。证据`codex-C-ui-display-initial-pre-r01`，脚本released SHA `9063b360fc33330533ef9d58310b6816b93cd0fbfe181c4524d3e5aec404f9e4`；不把完整套件绿误作全部入口已覆盖。

D host r03四hash与401源freeze `73047e1879a0e6b204a8f8798e0e5457b0b50746a66692877c7c901622885d94`匹配。Root真实host原5组及新异常6组全过；原atomic writer与真实HTTP／manager执行，选择边界仍为替身。异常覆盖真实清理故障、create／finish已知attempt失败、replace后indeterminate与未发HTTP回执补记、完整下载后pause、非法名零attempt与规范UTC、真实_retire后已知saved回放；source401保持，actual child／attempt0／log0／audit健康，自有DB外0。原manager8及HTTP＋备份／未知work／Word学期外／8与9容量4组也在最终backend新身份通过，284源（283 backend＋守卫）保持；不冒称原生或实际Word全页。证据`kgm-wh-d3-base-r01`、`kgm-wh-d3-adv-r01`、`codex-D-manager-host-r03`、`kgm-we-d3-*-r01`。

D r03最终只读又发现pending元数据回放遗漏：本地已有合法in_progress attempt使host start返回should_prompt=false，产生in_flight=false的pending；真实_retire后query仍落BRIDGE_NOT_READY。Root在真实API／host第7组复现，仅该断言失败，其余6组保持通过，source／guard／自有DB健康；交D r04仅host与测试两文件最小修复。证据`kgm-wh-d3-pending-pre-r01`，released probe SHA `e73ea8280bc6420c4b3405aa0b84b1f051808a7bfe97063604117b2dce388d8b`。

完整backend首轮`kgm-g3-local-r01`：145过后在既有凭据ACL测试失败，原因是私有包装器未允许对本轮合成.dpapi文件执行系统icacls /grant Everyone，执行前被拒，pytest未到凭据行为断言；最终包装器exit98。401源保持，首现场保留，不算应用缺陷／不跳测。只在私有新runner补可信系统icacls与新run root内、无reparse、精确参数的最小许可，再新根全量复验；不更改真实凭据或系统策略。
## G3实际窗口首失败与验证器收口

D host r04只改host及其测试，最终401源freeze SHA `a0284cabf156b65a62514a0bd76726eaa6405344157a426503bcf4d52e943c90`。Codex同一七组异常反例在新根 `C:/kgm-wh-d4-adv-r02` 全过，含真实_retire后pending只读回放；实际child自检、网络attempt／log均0、audit健康、自有DB外0及401源保持。第一次r01因SQLAlchemy import中的Windows版本探测尝试额外cmd子进程，被验证器拒绝，0例；未放宽守卫，保留现场后串行新根通过。选择路径仍为替身，不称原生窗口通过。

C r09交付误沿用r08私有结果名，Codex按真实文件重建十一源镜像，入口显示五组及原23组均过；该结果与r08历史身份分开。实际窗口预览进一步暴露facts原始代码／字段路径，交原C r10在六份自有显示文件中文投影，未改facts／ack／DTO。r10十一源manifest SHA `e63d2e70706e42a1d27a1f56e5ed1c3046cd6e8d302edaa246589fae13962053`，独立28交互／显示组、完整前端typecheck／test:d1和原unknown3例均过，100前端源保持。该结论未覆盖默认request ID与真实backend交接，后续实际首失败如下。

全量后端包装器r02窄放行本轮合成ACL夹具后，183过、既有G17受控任务未达succeeded。精确源码显示Windows multiprocessing spawn直接调用_winapi.CreateProcess，绕过原Popen子守卫传递；不据此声称旧worker实际exit72（未测得）。r03–r06私有尝试均保留；r04–r06在原生audit事件的命令参数与实际标准spawn命令不一致时严格拒绝、未启动应用，不把本机观察写成已确认CPython缺陷。r07仅在已验证标准spawn命令／exe／独立env后，以同线程、同frame／code及唯一CALL9调用点绑定实际builtin参数，并保留未知native调用创建前拒绝，未放宽网络或任意子进程权限。另经独立只读审核，无阻断发现。

Codex实际r07自检 `C:/kgm-g3-st-r07` 和原固定G17用例 `C:/kgm-g3-g17-r01` 均最终exit0、来源保持、audit健康、parent／默认网络log0；G17为真实spawn任务、1项通过。完整local与desktop仍另记实际终态，不由此推算全过。

源码窗口使用普通现有Python、全新合成根 `C:/kgm-ui-wp-20261101-r02`，非候选EXE。source-gui-r01正常AltF4关闭、返回0，数据／暗色偏好在不同新端口的source-gui-r02实际重开保留。实际UI已初始化表头（含120字校名、教师同名顺序和保育员）、四个日历例外、保存本人5月11日日计划v2及集体／重点区域完整内容。未注入业务fixture，未调用付费AI。两次启动各有被守卫挡住的GitHub更新尝试，不能写成零网络尝试；Python守卫不覆盖WebView／OS网络。

source-gui-r02的C10预览实际显示中文缺项，首次“创建”却被VALIDATION_ERROR拒绝。窗口正常关闭、现场保留、尚无新周记录或Word。Root精确源核：backend normalize_request_id只接受UUID；C列表、controller默认及导出分别生成weekly-create-／weekly-／weekly-export-时间戳ID。原stub交互测试未覆盖该真实协议，不能称全链路通过。仅解冻原C六份自有文件修复所有默认UUID生成与错误中文投影并补真实合同反例；不弱化backend验证，不改请求重放／unknown恢复语义。首失败证据归私有 `g3-source-word-actual.md` 及source-gui-r02，复验另用新frontend身份。

## G3完整验证与最终窄修

本节取代上文旧轮次的进行中状态，不抹去原失败。完整backend证据别名`g3-local-r09`：1006 passed、39 warnings，pytest与外层最终exit0，149个Python子进程分别为119正常退出、9受控停止、16显式退出、5原生Job停止，均有对应真实启动、PID／创建时间与退出证明。父及默认网络日志0、audit健康，401源闭包前后保持。后续只改前端及桌面测试／静态工具；已重新逐项核对该轮283个backend源文件未变，不将旧401整体hash冒充最终源。

完整desktop曾出现三类独立问题：私有TEMP与basetemp不包含、当前U1正向fixture仍写3.14.7、短命U2辅助进程被测试立即停止而来不及生成真实guard ready。前者在私有runner中仅对齐根关系；U1由原A只改当前正向值为用户已接受的3.14.10，历史／负例未改。U2未获豁免：新私有runner只对准确冻结测试函数、argv、标准流及自有fixture，在真实Popen注册后等实际guard ready再交回原测试，未等业务ready，超时仍失败；所有原守卫和终态判定保持。旧550 passed／final98的缺证根原样保留。

新根`g3-desktop-r12`为544 passed后，原静态验包零进程断言失败：被测路径实际触发一次forbidden subprocess调用，32个child证明均通过，guard及来源健康。读源表明普通导入PyInstaller reader会执行compat中的系统探测，本机CPython WMI失败分支可调用shell ver；因原栈中段截断，具体ver命令只记源码推断。原A修复静态工具：经安装分发元数据加载锁定依赖的两个真实纯reader叶模块，局部绑定明确依赖，避开顶层初始化，不全局伪造模块、不补平台缓存、不复制解析器。新增确定性禁止平台／进程探测、真实合成CArchive／PYZ正例、MZ拒绝及缺分发／不兼容反例；原calls==[]、历史夹具和守卫未弱化。

最终`g3-desktop-r13`：**553 passed、2 warnings，pytest0／final0**；401源保持，32个Python child为31正常退出和1有真实ready的受控停止，全部终态通过；parent/default网络0且audit健康。runner released SHA-256 `09c11ef9a2387109202ff0092115c19ee32917765b1383485de36c995f393b1b`。最终静态工具SHA-256 `df0a03aae1a4a6e41627866410736e4abf168febccf689767df778eba563974d`，其测试`dfb52ce81db6615b0365df247d1f86e3df52a9effed31465b4af63aef26f089c`。这是源码测试及合成归档解析，不是新EXE执行或新候选静态验收。

C12关闭默认非UUID请求与刷新当前／目标版本混用；C13关闭平铺真实来源DTO与嵌套页面类型错配；C14限定“保留旧来源”只用于真实保留分支；C15恢复人工selector严格七键中的显式null。此前私有假API六键断言不是真实B合同通过，首失败保留；修正后实际Node编码body交真实B纯函数验证，4正例＋2缺null反例通过，SQL0、额外child0、来源401与guard健康。实际GUI随后混合本人来源／手工游戏保存成功。C16只将已知“请先保存当前周计划再确认”本地前提投影为明确中文，任意Error仍泛化，未增加确认自动保存。

C16最终11源镜像SHA-256 `256102e88b11f62fbc5046317f815930f848bc0d688ab1df81df2291ebead68e`：Root独立35组为行为5、竞态9、deferred4、flight5、显示5、默认请求及版本4、平铺候选与严格手工3，全部通过，源保持，network／child均0。最终C17仅改WeeklyExportDialog显示：完整映射5种宿主状态为中文、未知值安全回退、保留待补记提示、隐藏opaque export ID。Root逐块核对差异，没有改原请求键、token、缓存、TTL、重试或dirty行为。A的设置影响原因也改为明确中文，独立审核纠正所属学期“当前范围”与“创建范围”的文案差异；DTO及日历规则未改。

最终前端证据`codex-front-g3-r17`：`npm run typecheck`、`npm run test:d1`及独立unknown3全部exit0，100源前后保持。C15早先完整轮次曾在未改的W5 1100ms计时边界失败；原测试脚本与c78逻辑一致，未记录实际失败时间戳，不能断言具体负载原因；保留首失败，不改断言。C16与最终C17新根串行完整通过。

C17时点501文件源freeze别名`codex-final-source-r08`，SHA-256 `1ed91ee8364bce80939a0c5f638a55e18d60ec4f22b5e7ef17686810320e9720`；相对r07恰为静态工具／测试、设置页及C导出页／UI测试五文件。Vite仅构建到新的自有frontend-r08目录：build0、100源保持、3产物，8个相关dotenv文件均不存在，未装依赖／升级锁／运行PyInstaller。所有原生均自然CLI结束0，实际metadata核实OpenCode Go与Command Go的Flash／max；Codex未另起业务实现者。

## G3真实源码窗口及新周Word

所有业务记录均在自有新合成档案，经正常界面创建、保存和确认，没有API／SQL种入业务或确认。教师、班级、表头均为合成值：长园名120字、重复教师顺序王老师／李老师／王老师、保育员张阿姨；一份本人日计划5月11日v2，含晨谈／集体、完整来源集体游戏与重点区域。配置学期原为4月28日至6月30日，明确5月1日停课及5月2／23／24日补课。

P5为5月11日五日周，人工覆盖晨谈、本人集体活动、本人集体游戏、另一项完整手工集体游戏及重点区域，刷新后人工保护并保存v5、确认K1。P6固定锚点4月27日、第1周，跨月六列，四栏各有六段长文和独立BEGIN／END标记，保存v2并确认K1；显示教学日期4月28日至5月2日。P7为5月18日至24日七列，周日两项人工末列标记，保存v2并确认K1。各样例未填的其它格、游戏或材料均明确知悉缺项后确认，不冒称所有2＋1游戏或所有栏目实际填满。

真实范围4月29日至5月20日预览固定选入P6／P5／P7三份确认，末周保留到24日。首次原生另存为实际取消，目标目录无文件；明确重试生成子attempt后另存为W01成功（22126 bytes，SHA-256 `d3aea88449454c1e1709fbbb3544a1b8b93fcfc2eea166e30576bae9a3911df8`）。在已安装Microsoft Word实际打开并逐页检查全部5页：P6三页长文续排，四个BEGIN／END及段落完整；P5单页本人／人工各字段和区域完整；P7单页七列及周日末列完整，三周按序分隔，无观察到裁切、重叠或越界。另有纯ZIP/XML只读结构核查，不能代替上述页检。

随后正常配置预览／应用把合成学期移至7月1日至31日，保留旧创建表头与第1周。P6明确刷新为v3，七天均为学期外／无需日来源，四栏手工长文保留；确认K2的预览真实日期为**4月28日至5月3日**，符合用户明确的创建交集回退，而非旧教学末日5月2日。单独“仍与保存basis相交的全停课零周”没有再造GUI样例；该分支以纯内容／快照测试为证，不扩大本次实际窗口覆盖。

最终frontend-r08／源freeze r08由普通源码入口在新端口65050重开，亮色偏好及既有周历史保留。后续完整备份／恢复、旧确认导出与最终正常重开已完成，见下节；此句仅标识r08首次重开时点。旧r03的W1–W8教师确认不迁移为本节新周教师验收。

## G3完整备份、旧确认及最终重开收口

B0明文完整备份经正常原生另存为及应用校验成功，1140516 bytes，SHA-256 `bc9d1b173a68c0b93cbda9c5541d29bd12b7b464110d3d7893ed3085fea60632`。其后正常保存P6为v4／K2的新主题标记，并切暗色；B1加密完整备份经合成密码生成校验成功，1165108 bytes，SHA-256 `8991953bb6861356e2a63670738791bf42fb27bcb99b0ce2551186f9d389edb4`。未配置或读取真实AI凭据。

依次经正常Open／校验预览／明确替换执行三次恢复：B0恢复为亮色、P6 v3／K2及原主题；应用实际提供的首次自动保护包再恢复为暗色、v4／K2与新主题；B1经合成密码解密校验再恢复，同样暗色／v4／K2。三个自动保护包均保留。独立标准库只读观察器在固定自有SQLite上使用URI mode=ro、query_only、单读事务与SELECT白名单；保护包与B1恢复的十张受核表按完整类型化行规范hash逐一相同。观察器没有种入或修改业务，也不替代上述真实界面步骤。样例无观察照片，不声称完整照片矩阵／跨机／跨Windows用户凭据恢复通过。

随后正常保存P6新主题为v5，并确认K3，再在主题输入未保存标记。明确选旧K2（草稿v3）导出：先选择仍被Word占用的W01并确认替换，原生保存失败，界面保留稿及重试入口；明确重试子attempt另存W02成功。失败与成功两个时点，周计划／周内容／周确认／日计划／日内容／settings六张核心表完整hash均保持v5／K3和已保存新主题，未保存标记仍在真实编辑界面；仅导出操作／快照／token／attempt表发生预期变化。W01关闭Word后原22126 bytes及SHA仍保持，未被占用失败损坏。

W02为19102 bytes，SHA-256 `9c4b25b2557d071aedea8fd7d447f857d1c8fb6f7ce05b34699f89414f9294ed`。已安装Word实际逐页核完全部3页：旧主题、创建交集日期4月28日至5月3日、第1周、长表头、四栏BEGIN／END与六段续排完整；零教学日只留周一至周五五列，十个教学格全空，不伪写假期；不含新确认或未保存主题标记，无观察到裁切／重叠／越界。另有纯ZIP/XML核验，但不据此代替真实页检。与W01合为两份共8页本机工程检查，不称本轮新Word教师确认。

导出完成后正常关闭窗口按Q2自动保存为v6／K3；这是之后的关闭协调行为，不倒算为旧确认导出的隐式保存。最终C18只改WeeklyHistoryPanel两处template：确认人显示“本档案教师”，去除技术hash；日期／确认时间／确认及草稿版本保持。独立逐字节撤销两处替换精确还原r08 SHA，当前文件SHA-256 `897ac7530f5ef2d6105c6af5eb5e169b7c5503a4df9841ee1253be4094f5f9ba`。原生及Codex定向typecheck／UI13均exit0；行为源码其余500文件相对r08不变，不声称C18又重跑完整Python或整套前端。

最终501源freeze别名`codex-final-source-r09`，SHA-256 `b09e2514a5472295a434178f7184bd450972dc72ab182f32a7431b92facd8d9d`。新自有frontend-r09 Vite build0，100前端源保持、8相关dotenv不存在、三产物；普通源码入口在新端口60492正常重开，真实暗色偏好、P6已存v6／已确认v3和关闭自动保存标记均保留；旧K2历史显示“本档案教师”、正确日期／版本与原主题长文，不再显示opaque ID/hash。正常关闭main_returned true／exit0，501源、frontend及control指纹保持。

source-gui-r08含三次恢复的全过程正常exit0，Python守卫记录4次被拒启动更新网络尝试；最终source-gui-r09为1次。两轮counts一致、audit健康、failure marker无，真实child guard自检通过；覆盖仅Python getaddrinfo/connect/connect_ex，不冒称WebView2／OS全局网络0。完整自动Python套件的parent／default网络0及各child终态另按前节各自receipt记录。

## G4文件与后续范围

r03目标测试与教师确认两提交`f7986f033821cdf0a1ea3a6ac0c814685b9384bd`、`c78ccc4669cbd9447ed74244aa370b6a7c05f45b`已普通快进整合；最终fetch仍为c78ccc4。原生A按Codex精确文件raw SHA／规范Git blob／parent核定清单stage后停下，Codex独立核cached集合与tree后才允许该parent／tree普通commit及既有分支push。门禁与实际外部回执私有保留；本报告随本片提交，最终身份以包含本文件的提交及远端为准，不回填自身SHA。只处理本轮已核自有临时stash，不动未知项。

下一步建议先准备包含周计划的新身份候选，并在合法可运行目标核启动、保存重开、备份接续、新周Word和教师反馈，评估后再Q5/Q6周AI／材料。当前未构建／运行新候选EXE，未做新目标／新Word教师体验、Win10／WPS／其它显示／干净机、签名或正式发行；不执行4551受阻EXE/helper、不换路径绕过，不自动真实AI／WebDAV／签名／安装更新／远控／Release。旧失败、旧制品及未验分别保留，未升级依赖或重写Git历史。

G4首次完整cached --check补查出9个新增源文件的多余尾空行（此前未暂存的新文件不在普通diff检查中）。原A仅修weekly_plan_sources，原C仅修八个自有前端文件，均自然exit0；没有Git写入或正文变更。Codex对私有before原字节独立核验：九文件只删除共78 bytes冗余CRLF，保留各自单个原CRLF及全部正文前缀；501源其余492文件保持。最终提交源freeze-r10 SHA-256为 701b95314cedea632ad61b831cae8fa14a4fc0a3c927ee7921ba68bd397e99d8。此为纯末尾空行规范，未重跑行为测试、构建或GUI；前述实际测试与GUI保留各自raw身份，以精确字节等价说明本次无行为变化，不混称又执行整套。更新精确blob清单后重新暂存检查，不放宽空白检查。
