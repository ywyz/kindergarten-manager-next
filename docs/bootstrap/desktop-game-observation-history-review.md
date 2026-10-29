# D4：E05／E08 保存、历史留存与恢复独立核查

> 公开版隐私处理（2026-10-30）：本机用户路径、私有部署地址或联系标识已替换为占位符；原始记录由维护者私下保留，历史日期、结论和产物哈希不因此改变。

更新：2026-10-27。**E05／E08在当前Windows 11源码／隔离合成环境的限定工程核查通过：独立663项全local、85项相关桌面回归、保留库复核及关键竞态探针全部通过，R01–R08关闭。** 本结论只覆盖保存、历史与恢复服务层，不代表完整A01–A22、页面教师体验或产品发行通过。

## 1. 授权、基线与实现身份

用户明确要求推进E05／E08，由OpenCode Go套餐DeepSeek V4.1 Flash max实施，Codex独立审核，交回修复直至通过，再提交推送。该授权替代原“停在E03”，不扩展其他切片。基线5e3e46f，分支codex/desktop-v2-foundation，开工前工作区干净。

本机CLI 2.1.4接续唯一原会话ses_ead8af71dffeJphI1NOWg4jZgI，build代理，明确opencode-go/deepseek-v4.1-flash#max；未另建／fork会话、子代理或分支。run使用standalone，JSONL、stderr、实际exit分开保留。OpenCode唯一写实现、测试及验证脚本；Codex写规划／核查文档，读源码、执行独立验证与Git管理。

本轮CLI实际exit0。最后assistant为msg_17a8519c4001H9jnpYiMahGajt，finish=stop，完成1793056911482、idle1793056911486、outcome=succeeded；不是据旧outcome推断完成。相对4034条基线消息新增270条assistant，全部为指定Go Flash max／build；工具仅edit/read/shell/write。证据为final-model-session-audit.json及session-final-sanitized.json。

本机证据根：<LOCAL_USERPROFILE>/AppData/Local/Temp/kgm-observation-e0508-20261027-5135336c；指针%TEMP%/kgm-observation-e0508-current.txt。实现者使用opencode-evidence；Codex使用codex-independent，TEMP、pycache、合成库及持久证据分别隔离。必要结论归并本文，不把临时根当永久归档。

统一解释器为desktop/.venv-d1/Scripts/python.exe，实核CPython3.14.7 x64、Py_GIL_DISABLED=0。最初任务误写desktop/.venv已纠正；该目录是保留的3.12.10旧环境，不用于本片通过门槛。未安装新解释器、依赖、Skill或MCP。

codebase-memory已用于模型／材料服务定位、双向调用链与coverage。初始generation为2026-10-26T16:13:07Z；最终13份相关路径的自动索引generation为2026-10-26T23:20:40Z，均仍提示metadata_changed。因此准确结论以回读源码／测试、Git差异及实际运行证据为准，图谱不作完整或新鲜性证明。

## 2. 最终文件与源码身份

| 文件 | SHA256前16位 | 本片职责 |
| --- | --- | --- |
| backend/app/local/observation_service.py | 26e0b8fade8ef737 | 内部创建／当前稿读取、整份保存、规范请求、明确归属、保留历史、投影、回执／审计 |
| backend/app/local/observation_history_service.py | 556569ec0b9945bb | 历史元信息／整份读取、一次性预览绑定、恢复／幂等与材料复核 |
| backend/app/local/observation_assets.py | b240623c502b9483 | 增加严格受管路径、同句柄有界核验及短文件身份检查；既有导入管线保持 |
| backend/tests/local/test_observation_history.py | ff78421644d31041 | 33项本片服务／故障／竞态回归与关键合成证据保留 |
| backend/tests/local/worker.py | 0b868796b4c4d7fe | 新增保存／读取／恢复三类合成跨进程动作 |

source-before-full.json固定384份backend／desktop／frontend源码、配置与测试；source-after-full.json及final-source-audit.json确认最终全local前后384份均无变化、无新增或缺失。生产源码、测试及上述实现者交付身份一致。迁移、依赖锁、前端与生产宿主未修改；未构建新包。相关规划／规格／Contract及结果文档另行归并，不混入源码身份计数。

表中SHA256为已测Windows工作副本原字节。Git按既有换行规则将CRLF规范为LF；五份变更源码／测试的staged blob均与已测字节仅做CRLF→LF后的结果完全一致，无内容差异，见staged-source-audit.json。不把工作副本hash误作Git blob原字节hash。

## 3. 独立发现及回修

以下问题均交回同一Go Flash max会话。初版失败、反馈和合成库保留，最终通过不抹去失败。

| 编号 | 初版问题与最终处理 | 结论 |
| --- | --- | --- |
| R01 | 只校revision／hash，遗漏完整资料投影、canonical字段／值、历史指针及归属；查询加载全部历史正文。补全权威校验，损坏明确拒绝；最新查询显式SQL LIMIT，历史列表只选元信息 | 关闭 |
| R02 | 默认空草稿参数失败；重复term_id绕过跨学期决定，未归属改日期未走E04；请求未规范。改为明确term_decision／selected_term_id、可信snapshot与稳定规范请求；显式新建归属范围不符返回非阻断warning，回执保持原warning | 关闭 |
| R03 | 预览后先编辑，恢复把新稿当作before基线而覆盖。提交直接复核实际draft仍等于预览base，且当前稿已对应最近保留节点；晚到auto／manual编辑均拒绝 | 关闭 |
| R04 | 漏request、source hash、实际base及决定绑定；空学期决定hash相同；缓存核验前时间导致跨期限仍提交。绑定完整上下文，最终锁内重新取时及复核；同指纹已提交回执优先 | 关闭 |
| R05 | 只hash不解码、二次打开核错图；缺文件变化检查、祖先junction／固定布局检查、元数据新鲜性和有界读取。新增同受管句柄hash／真实解码，25MiB门禁与E03解码锁保持；写锁内只查严格路径／父目录／文件身份，重新加载绑定 | 关闭 |
| R06 | 缺归属方案／warning／只读回执；只绑定当前学期，遗漏源历史学期配置变化。改为源／当前／所选学期上下文绑定，保存历史原snapshot；无效keep_history要求重新选择，明确keep_current／assign_selected仍可带warning保存 | 关闭 |
| R07 | 分离receipt首查与token前检，可能错过刚并发提交的匹配回执。前检失败优先重新读匹配回执，写锁内仍先查；双请求只产生一个结果 | 关闭 |
| R08 | 早期trigger及不存在ID断言不能证明全写集合回滚。新增最后commit hook内真实flush、完整阶段marker及真实SQLite触发器故障；逐集合回滚、同token重试、恢复提交前后冷重启并保留一致备份 | 关闭 |

Codex实际独立反例曾复现R06：历史属于学期A、当前稿未归属，预览后将A范围缩至不含历史日期，旧token仍accepted并恢复。初次失败保留于inflight-probes/findings.json及source-term-change.sqlite3；修后r06-recheck证实旧token及冲突keep_history重新预览均拒绝，current_preserved=true。

## 4. 最终独立验证

所有自动验证均使用独立合成数据；未读教师真实库、密钥、照片或OneDrive原件，未调用应用真实AI／WebDAV，未启动教师窗口或构建。

| 检查 | Codex实际结果 | 独立证据 |
| --- | --- | --- |
| python -m pytest tests/local -q | exit0，663 passed，559.26s；无失败／错误／跳过 | full-local.stdout／stderr／exit／xml |
| 六个相关desktop测试文件 | 最终源码exit0，85 passed，6.50s | desktop-related-final.stdout／stderr／exit／xml |
| 384份源码／配置／测试前后身份 | 零变化、无新增／缺失 | source-before-full.json、source-after-full.json、final-source-audit.json |
| R06原反例复测 | exit0，旧token／冲突重新预览均为OBS_RESTORE_SOURCE_INVALID，现稿未变 | r06-recheck/result.json及一致备份 |
| 解码串行／写锁／强回执优先 | exit0，四项均true；token过期＋照片缺失＋后续新revision仍返回原成功回执，未再解码 | locking-replay-probe/result.json |
| 保留历史与重复恢复竞态 | exit0；已保留A→B→A为三个节点，无变化不增revision／history；确定性交错双请求返回同一回执，只加一个恢复节点 | retention-race-final.json |
| 三份故障／重启保留库只读复核 | integrity_check=ok、foreign_key_check零错误；全部draft、三份快照中共8行历史hash及6份材料文件hash匹配，投影和两个指针一致 | retained-evidence-audit.json |

663项在backend执行，使用full-local-temp、pycache-final、独立pytest cache，注入E0508_EVIDENCE_ROOT、E03_EVIDENCE_ROOT及KGM_OBSERVATION_EVIDENCE_ROOT到各自子根。桌面选取test_d1_paths、test_d1_host_save、test_d1_close、test_d2_build_paths、test_d2_close_barrier、test_d2_w6_degrade_host；测试内构建路径为模拟，不实际构建。

OpenCode自测另有656项、661项及最终33项本片测试通过，具体窗口见[实现结果](desktop-game-observation-history-result.md)。第三个后台全local窗口仅保留进度，未取得完成／exit证据，不计通过；上述Codex冻结源码663项才是最终独立全local结果，不混用窗口或自测身份。

### 4.1 晚阶段故障与冷重启复核

独立service-evidence/r08-late-stage-marker.json证明触发故障前，在同一真实事务中draft、current_version、version／version_photos、restore细节、operation、audit及token消费都已flush。随后独立fault表的RAISE(ABORT)产生真实SQLite错误，服务整体回滚。

| 状态 | versions | version_photos | restores | operations | 观察audits | 已消费preview |
| --- | --- | --- | --- | --- | --- | --- |
| 故障前／回滚后 | 2 | 2 | 0 | 4 | 4 | 0 |
| 故障前已flush的暂态 | 3 | 3 | 1 | 5 | 5 | 1 |
| 同token重试成功后 | 3 | 3 | 1 | 5 | 5 | 1 |

r08-late-stage-fault和r08-late-stage-retry的一致备份分别独立重算全部业务hash，并核对原图／两个派生副本的文件hash；失败不留下成功回执或已消费token，重试成功不改旧版本。

r08-cross-process-restore由父进程释放runtime，worker以connect_only=False走LocalRuntime.prepare／锁／冷启动；提交后退出而未回包，可按原请求读回；提交前真实flush后退出，冷重启仍保留原提交状态。保留库中有3个历史版本、1个已成功restore及正确回执，下一未提交恢复不新增节点。本片不以同进程session重开或connect_only连接冒充冷重启；有图整事务故障与无图跨进程恢复分别留证。

## 5. 核定协议与边界

- 通用save_reason仅auto/manual/leave/pre_restore/pre_export；adopt／restore独立，不能借保存原因绕过。auto不留历史；其余相对最近节点判变更，首个保留节点可在draft未再变时建立。无全局hash去重。
- 当前稿由draft＋有序draft_photos权威；history不可变。恢复先保护现稿，再完整预览及明确归属；服务拒绝未保护的base，不在恢复事务内伪造UI前置保存。无变恢复不增revision／history，result_version指实际当前保留节点。
- 15分钟preview TTL为内部技术参数，不是历史保留期；token只存摘要。term_snapshot_hash是有效snapshot、明确决定及源／当前／所选学期配置上下文的绑定摘要，即使未归属也不能跨决定复用。历史原snapshot不因改名自动重填。
- 受管原图／历史／input引用保持；首期不自动清理。新增核验复用E03的25MiB／40MP／单边8192及串行解码约束，不重建AI／导出派生，不改既有参数或依赖。

## 6. 未验及Git收口

本片限定服务层。E06／E07视觉候选及采用、E09／E10页面／列表／IME／离开协调、E11／E12 Word／宿主、E14整合仍未实施／未验，不自动启动。恢复不调用AI的证明不等于迟到候选采用门禁已实现。完整A01–A22不整项关闭；教师体验、真实Word逐页、新冻结包／许可、干净机器、Win10／WPS、其他DPI／多显示器、真实安装更新及发行仍未验。canonical总容量、视觉请求／IPC、Word总容量和组合工作集仍按后续切片验证；D2／D3既有边界、4551和跨设备后置保持。

用户已授权本片审核通过后提交推送。Codex按最终384份身份正常收口本片源码／测试及必要文档；不amend、强推、重写历史或夹带合成库／照片／后续功能。实际commit及远端ref以Git历史和本机git-final-audit.json为准；Git推送不代表产品或发行验收。
