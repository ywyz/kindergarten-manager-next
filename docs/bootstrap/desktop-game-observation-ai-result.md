# D4：E06／E07 图文执行、视觉候选与原子采用实现结果（OpenCode）

更新：2026-10-27。本文件保留OpenCode停写时的E06／E07服务层实现、测试、容量／故障及真实AI入口交接窗口；正文中的调用数、未验与待办以当时为准，不作为最终验收结论。Codex接续已完成冻结718项全local、85项相关桌面、容量及真实DeepSeek四次请求中的生成／重写／采用闭环，最终范围与失败／撤回记录见[独立核查](desktop-game-observation-ai-review.md)。这不等于完整A01–A22或教师产品验收。有效依据仍为[当前任务](../tasks/current.md)、[工程规格](../specs/desktop-game-observation-engineering.md)及[观察Contract](../modules/game-observations.md)。

## 1. 身份、基线与边界

- 基线 `541bc82`，分支 `codex/desktop-v2-foundation`；继续原会话、Go 套餐 DeepSeek V4.1 Flash max／build，无子代理、fork、新分支或 Git 操作。
- 只实现 E06／E07 服务层及必要的共享 AI 执行／传输扩展；未启动 E09／E10 页面、E11／E12 Word／宿主、E14 整包、真实 AI（OpenCode 未执行）、WebDAV、构建、安装或发布。
- 未修改迁移、依赖锁、`ARCHITECTURE.md`、Codex 的 current／review／AGENTS 文档。旧观察 v1 bundle/schema/hash 未就地修改。

### 1.1 生产源码（SHA256 前 16）

| 文件 | SHA256 | 作用 |
| --- | --- | --- |
| `backend/app/local/observation_ai_inputs.py` | `cbcc14e333132077` | 实际发送投影、内部冻结上下文、工作图材料、上下文／容量预检、视觉能力 |
| `backend/app/local/observation_ai_service.py` | `c4da3138dafd5910` | 观察任务提交／材料 claim、候选读取、review metadata、preview／adopt、token 与 provenance |
| `backend/app/local/ai_transport.py` | `3bafc79058264f41` | 独立视觉协议、40MiB HTTP／36MiB IPC／180秒候选、上下文预留、能力边界 |
| `backend/app/local/ai_worker.py` | `01aff7c868d25949` | 小头帧先核合同、旧文本单帧 1MiB 接收保护、视觉大帧、能力复核 |
| `backend/app/local/ai_executor.py` | `5fc43f167c33b9ab` | 视觉 claim 授权、精确 bootstrap、预算、旧文本路径保持 |
| `backend/app/local/ai_task_service.py` | `c364f0a1e5a2bf32` | 观察任务纳入共享 claim／finalize、固定配置／prompt、source 复核、候选 metadata 写入 |
| `backend/app/local/prompt_bundles.py` | `4e3a325dcafe868b` | 观察运行时输入／输出校验；旧 bundle 清单未改 |
| `backend/app/local/observation_assets.py` | `0664ac293d7031fe` | 派生图严格路径、有界读取、恢复／采用材料身份检查 |
| `backend/app/local/observation_service.py` | `a3211225cd50c2b9` | E05 保存结果 target hashes、供 AI provenance 失效链 |
| `backend/app/local/observation_history_service.py` | `e6fb4aa43be48895` | 恢复结果 target hashes，供 AI provenance 失效链 |

### 1.2 测试与验证脚本（SHA256 前 16）

| 文件 | SHA256 | 作用 |
| --- | --- | --- |
| `backend/tests/local/test_observation_ai.py` | `707ee6d2fc68b745` | E06／E07 提交、执行、候选、preview／adopt、材料、R05／R06／R07／R08／R09、冷重启与晚阶段 SQL 故障 |
| `backend/tests/local/test_observation_ai_contracts.py` | `31f7476c836c2f40` | 视觉头授权、能力、600／601、上下文、36MiB 边界、旧文本 IPC |
| `backend/tests/local/test_observation_prompt_contracts.py` | `1219c2d83c470af2` | 观察运行时协议 R12：姓名对应、审核标记隔离 |
| `backend/tests/local/obs_ai_workers.py` | `f9146725a8e8412c` | 观察 fake spawn worker（成功、未发送、发送后静默／退出） |
| `backend/tests/local/worker.py` | `5b95fc2795010eac` | 子进程真实 `LocalRuntime.prepare` 后采用并退出 |
| `backend/tests/local/w3_tls.py` | `35943a4642db2a6a` | 受控 TLS 接收改为有界线性读取，保留完整请求与旧测试行为 |

临时证据脚本（不进入生产入口、未提交）：

- `%TEMP%/kgm-observation-e0607-20261027-aa633c2e/opencode-evidence/verify_observation_ai_real.py`
- `.../verify_observation_ai_capacity.py`（v1，保留失败现场）
- `.../verify_observation_ai_capacity_v2.py`（v2，真实 JPEG／解码者／最终结果／边界）

## 2. 实现口径

### 2.1 内部冻结 input 与 wire projection

- `LocalAIInput.payload_json` 是**实际 wire projection**：只含 `record_type/observation_date/start_time/end_time/adult_count/child_count/age_years/subjects/environment`、四栏正文、有序照片事实（原 hash、work hash、格式、尺寸、方向、顺序、说明）及 rewrite target/source。**不含 asset_id、derivative_id、record/profile/term/学校/班级/观察者/内部身份**。
- `LocalAIInput.dependencies_json` 为 `{"wire": <实际发送依赖>, "internal": <内部冻结上下文>}`；`dependency_hash` 只对 `wire` 计算。`internal` 保存 `internal_schema_version=1`、`wire_schema_version=1`、`wire_projection=observation_wire_v1`、提交时 missing/warnings、每张照片的 asset/derivative/params_version/实际工作尺寸/hash。
- `LocalAIInput.input_schema_version=1` 指内部冻结 schema；旧注册 bundle 的 v1 输入 schema（含 `asset_id` required）未改、未重算 hash。运行时 wire validator 明确区分，不声称与旧 required schema 完全相同。
- 实际发送不拼接审核提示、review metadata、内部 asset id 或未发送 canonical 字段；依赖 hash 不覆盖未发送字段。

### 2.2 执行、固定版本与视觉授权

- 观察任务与 daily 共用同一配置／凭据／调度／执行／进度／未知状态机；daily API 仍显式限定 daily，观察任务通过服务层提交。
- 提交冻结 wire input、全部有序照片、work hash、内部派生参数与 warnings；claim 使用 `pick.config_version` 对应不可变 config／credential 和 pinned prompt／bundle；最终短事务复核；未知 input schema 暂停为 `schema_unsupported`，不硬填。
- 视觉 claim 使用独立 `chat_completions_vision_v1`：父端先核 `game_observation` 来源、两类任务、schema／contract、官方 host/model 能力、图数、工作尺寸、上下文；再发送小头帧。worker 先核完整 header（来源／任务／schema／contract／图数／frame_size），无效立即拒绝，不等待 body；合法头后才读有界大帧并核实际原始字节数。旧文本仍是单帧 1MiB 接收，不因视觉放宽。
- 仅允许 `api.deepseek.com`（root 或 `/v1`，HTTPS/443，`deepseek-flash`／旧别名）与 `api.xiaomimimo.com`（root 或 `/v1`，三款 2.6 模型）；拒绝任意子域、Token Plan 前缀、非 HTTPS、非 443 与路径变体。
- 上下文准入：MiMo 按官方 16 patch／2 merge／32 对齐／8192–8388608 像素公式，DeepSeek 按每图 1024 token 上限；文本用实际 UTF-8 字节 + 8192 token 预留；1,000,000 上限。超限整份拒绝，不静默减图。

### 2.3 候选、审核 metadata 与采用

- 候选持久化总 hash、执行链、schema／contract、每目标 hash；review metadata 以独立 `LocalAIOperation`（`cr:<candidate_id>`）持久化，含版本、candidate hash、target hashes、固定总体提示与可选片段；与四栏正文、采用、Word、后续 prompt 分离。
- 详情／preview 重新读取 metadata 并核 target/domain/offset/hash；坏片段只降级为总体提示，不破坏有效正文；重写候选不继承旧候选片段；重开不调用 AI。
- preview 一次性 token 绑定 candidate/hash、profile/record、targets、draft revision/hash、当前实际依赖、before/after target hashes、source_state、差异 hash、材料 identities/sources、期限；正常 eligible 不需额外复核；source_changed 必须显式 `adopt_reviewed`，不默认代教师批准。
- adopt 先读本域 `local_observation_operations` 回执；token 用内存有限 store 原子 reservation，失败释放、提交后消费；锁内重新读取 candidate/input/draft，复核完整 candidate_hash、input_dependency_hash、schema／source、target hash、材料来源清单与身份，再允许写。
- 多目标采用在一个短事务写 draft／version／version_photos／provenance／operation／audit；draft 是否改动与是否留历史分开：revision 只在当前 aggregate 变化时 +1，history 按最终 aggregate 与最近保留节点比较（无节点时首次留节点）；auto 后内容与候选相同也补节点，最终等于最近节点不重复造节点；无变化采用仍写 provenance／operation，不增 revision。照片不变。
- provenance 以 SQLite `rowid` 的提交顺序为业务顺序；adoption 必须同时有匹配 version 的 provenance（candidate、input hash、固定完整 candidate hash、每目标 output hash）。同一 candidate/version 的后续无变采用只合并新目标证据，不替换旧目标；采用回执只作顺序／失效脊柱。保存操作记录 target hashes：无关栏变化保留目标所有权；目标改走再 auto 保存回原字样会清除所有权；**任何已采用目标被 manual／auto／restore／他 candidate 改过后，旧 candidate 均不得迟到覆盖，即使最近保留节点仍等于旧输出**；返回最近保留内容须使用尚未采用过该目标的新 candidate 并重新走来源复核；他候选同文不算旧候选受信；恢复清除所有权。

## 3. 自测与证据

统一解释器：`desktop/.venv-d1/Scripts/python.exe`（CPython 3.14.7 Windows x64，标准 GIL）。

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| E06／E07 自测专项 | **54 passed / 39.46 秒 / exit 0** | `obs-ai-final5.log` |
| R12 观察协议 + 观察专项 | **59 passed / 39.73 秒 / exit 0** | `r12-final.log` |
| Codex 独立观察专项 | **58 passed** | Codex 独立根 |
| Codex 独立相关桌面 | **85 passed** | Codex 独立根 |
| 旧 daily 相关回归（含观察 prompt 契约、W6 降级） | **142 passed / 120.92 秒 / exit 0** | `daily-regression-final.log` |
| 观察 prompt 契约单文件 | 5 passed / 0.63 秒 | `r12-prompt2.log` |
| 全 local 自测窗口 | **714 passed / 664.85 秒**（更早自测窗口，不是最终独立结果） | `local-all-e0607-final.log`；另有旧窗口 `local-all-e0607.log` 1 failed/710 passed，因 daily 响应新增字段，已修 |
| Codex 原全 local 窗口 | **718 passed**（对应 R12 manifest；Codex 记录） | Codex 独立根 |

### 3.1 关键正向／反例（均实际运行）

- 提交 wire payload 无 asset_id／derivative_id；内部上下文保存 warnings／missing／params／工作尺寸；`input_schema_version=1`。
- 真实 `ai_worker` + 受控 TLS 供应商：检查 text/image_url 顺序、实际工作图 Base64 解码 hash、所有关联图、无内部身份／审核 metadata；成功候选。
- 600／601、MiMo 600×2048 上下文超限、36MiB IPC 精确边界（frame 37,748,736 通过，+1 为 37,748,737 拒绝）、601 拒绝、旧文本 >1MiB 不接收。
- 伪造 daily 视觉 header、无 header 视觉 bootstrap、伪 daily header + body、未知 schema／protocol：worker 在 header 阶段立即拒绝，不等待 body；旧文本单帧路径保持。
- R04：pinned config/secret 重试；pending claim 取最新 config；未知 schema 暂停；新 derivative params 不破坏旧 candidate 读取／采用。
- R05：先目标后评价／策略；auto 改走再回原字样清除信任；手改已采用目标再试旧 candidate 拒绝；他候选同文不受信；ledger 缺失清除信任；评价空领域采用后继续策略。
- R06：adopt 写本域回执；同 request 回放跨消费 token／坏材料／新 revision；同 token 双 request 只一成功；candidate hash 外检后另一 session 改写、写锁内复核拒绝；`BEGIN IMMEDIATE` 失败释放 reservation、无行写入、恢复后同 token 重试成功；真实子进程 `LocalRuntime.prepare` commit 后丢回包冷重启回放（`v01-cold-restart-after-commit`、`v01-cold-restart-replay`，库 integrity_check=ok、foreign_key_check=0）。
- R07：新增有效图 source_changed 可显式 review 采用；新增工作图／原图删除在 preview／adopt 拒绝；claim 时原图缺失暂停；inspection 与 commit 间替换拒绝。
- R08：候选详情持久 review metadata；坏片段降级总体提示；重写不串旧片段；100,166 字节合法正文含 20,000 段短引号时片段/总字节有界（64 条／64KiB），正文、采用内容不丢，超界只降级提示。
- R09：600 张高分辨率 MiMo 超上下文拒绝；同数量 DeepSeek 每图 1024 上限通过；文本边界拒绝；HTTP 首次写入前按剩余 attempt deadline 设置发送超时（text 120 秒／vision 180 秒，connect 仍 10 秒），慢上传/期限反例通过。
- R10：auto 后内容与候选相同仍留应留节点、revision 不增、同 ID 重放不增；无首节点首次无变采用建首节点；auto 走后由**新 candidate** 采用回最近保留内容不重复造节点；旧已采用 candidate 在 auto／manual／restore／他 candidate 改过后即使 latest 仍等于旧输出也拒绝；同一 candidate/同一 version 无变采用不同目标只合并目标证据；手改／他 candidate 同文仍不冒充。
- R12（真实 DeepSeek 首样本失败后协议修正）：Codex 实际 1 次 HTTP200／succeeded（16.69 秒，2 张 48×36 合成图，subjects 甲／乙，无姓名-动作对应）返回 process 自行分配“甲说…乙回应…”并在正文写“候选补写，需教师核实”等审核包装；样本 candidate/hash 保留于 Codex 独立根，未采用。仅修改 `_render_system_text` 观察规则：仅教师明确姓名-行为／原话对应才映射具体姓名，subjects 姓名本身不构成对应；无对应只写共同情境或不归属姓名的对话／动作；审核／候选／AI补写／待核实标记只由独立 metadata 提供，不写进四栏；不得把补写写成“记录显示／只能确定”的已证实事实；四栏／目标正文多条多段在 JSON 解码后必须为真实换行，JSON 只转义一层，不得输出字面反斜杠+n／双重转义；保留 C11 允许的对话与动作衔接及 C32 必要的人物对应缺口简短说明。未改旧 bundle/schema/hash，无后处理删句或猜人名过滤器。
- R13（Codex 误判，已撤回）：Codex 只读 SQLite 逐字符核对确认首候选 `jfwKG…` goal/process/support 实际 LF=4/2/5、字面反斜杠+n 全为 0；`5wTz…` support 实际 LF=4、literal=0；`live-r12-explicit-retry.json` 直接 `json.loads` 后同样 LF4/literal0。**不存在真实换行缺陷**。已撤回本 R13 轮新增的 normalizer／`_list_item_number`／`_NUMBERED…`／finalize 调用／`ESCAPED_GENERATE`／worker 模式／R13 测试与导入；五文件已按 `codex-independent/source-final-before.json` 恢复精确字节/hash（`ai_task_service.py c364f0a1e5a2bf32…`、`observation_ai_service.py c4da3138dafd5910…`、`obs_ai_workers.py f9146725a8e8412c…`、`test_observation_ai.py 707ee6d2fc68b745…`、`test_observation_prompt_contracts.py 1219c2d83c470af2…`）。未保留格式清洗，不声称真实换行有缺陷；R12 姓名对应／审核包装修正及 common 换行规则保持。
- V04：多目标采用所有写 flush 后真实 SQLite trigger 故障；draft／version／version_photos／provenance／operation／audit 全回滚，token reservation 释放，同 token 重试成功；失败库／照片／marker 保留（`r09-adopt-late-fault`、`r09-adopt-retry`、`r09-adopt-late-marker.json`，integrity_check=ok、foreign_key_check=0）。
- 提交 fingerprint 显式纳入 `source_kind=game_observation`、`source_id=observation_id`；旧 daily 不变。

### 3.2 真实 AI 分阶段入口（OpenCode 未执行真实调用）

`verify_observation_ai_real.py` 已用全合成 config／secret + fake worker 干跑：

- `prepare` → `generate` → `status` → `review` → `adopt` → `rewrite` → `adopt-rewrite` 均 exit 0（`real-ai-dryrun-1-*.log`）；生成／采用／单栏重写各阶段使用持久 request/task id，重复 `generate` 返回 `reused=true`，未增加任务／尝试；`prepare` 先启动/确认恢复，再提交本次任务；无候选失败保留 status/reason/attempt 而不 `.one()` 丢失。
- 初始生成首跑 candidate state 未写回、review 返回 no_candidate；修正 candidate id 持久化后重跑通过；失败现场保留。
- 真实阶段尚未由 OpenCode 执行；`prepare` 才只读源 DB／凭据，`review`／`adopt`／`adopt-rewrite` 不依赖源配置；`source_changed` 默认停止并打印差异，只有显式 `--review-decision adopt_reviewed` 才提交。

### 3.3 容量证据（1024MiB 临时工程阈值已独立验证；256MiB 不成立）

- 256MiB 候选：v1 真实父子（600 条数据 URL）parent 229,371,904 + child 193,331,200 = **422,703,104（约403MiB）**，`passed_processing_budget=false`；保留失败现场 `capacity-evidence4.json`。**256MiB 不成立，不写成通过。**
- Codex 同意的 1024MiB 组合验证阈值：Codex 独立执行当前 capacity 脚本（d7faf88f）**exit 0**，主请求／overlap 均 `success`，受控 TLS 共 2 次请求，完整 `inspect_managed_asset` 原图解码（40MP，非导入缩图路径），组合峰值 **824,500,224 字节（约786MiB）< 1,073,741,824**。OpenCode 自己最终同脚本窗口为 817,045,504 字节；旧 158,183,424 是 `_prepare_asset` 缩图导入路径，已由完整解码 240,050,176 取代。**1024MiB 是该组合管线待实测验证阈值，不是运行时硬 RSS 上限或整应用内存承诺。**
- 精确边界：v2 `frame_bytes=37,748,736` 通过，`+1=37,748,737` 被 `AI_INPUT_TOO_LARGE` 拒绝；600／601、MiMo 600×2048 上下文拒绝均有记录。预检使用 4096 字节认证头预留与保守 deadline，实际生产头更短；synthetic CA 帧额外开销已单独保留，不能把预留值称为当前实际 HTTP 字节。
- 主请求 600 张独立 256×256 JPEG（raw 26,622,306 字节；600 条独立 Base64），最终 result 为 `success` 且四栏键齐全；HTTP body 35,550,063、frame 35,527,170、预检保守 HTTP 35,554,375／frame 35,530,079。OpenCode 最终证据：`capacity-v2-inspect-final3.json`／`.log`；Codex 独立证据在其独立根。

## 4. 失败与修正

- 视觉 claim 曾只凭 `image_urls`／`protocol` 选择大帧；改为父端来源／任务／schema／contract／能力授权 + worker 小头帧先核，伪 daily／无 header 立即拒绝。
- worker 曾在收完 36MiB 后才用重编码检查旧文本；改为旧文本单帧 1MiB 接收、视觉头先核后才读大帧，并核实际原始 frame_size。
- 采用回执曾误查 `local_ai_operations`；改为 `local_observation_operations` 本域回执；token 改为原子 reservation／失败释放／提交消费。
- 采用锁内曾只比 selected target hash；补完整 candidate_hash／input_dependency_hash／schema／材料来源清单／身份复核，覆盖另一 session 在 inspection 与 BEGIN 之间改写候选。
- 工作图查找曾固定当前全局 `AI_PARAMS_VERSION`；改为按 asset 最新 AI derivative 读取，冻结 input 按 input photo 的 derivative_id，参数版本变化不破坏旧 candidate。
- 采用材料曾只核冻结 input；改为冻结 input + 当前 draft 照片并集，新增图缺失／损坏不可 review 覆盖。
- review 提示曾只在 preview 临时正则；改为候选持久 metadata，坏偏移／hash 降级总体提示。
- provenance 曾只用 operation 重建 owner；改为 operation 失效链 + 版本 provenance + target output hash，并用 rowid 业务顺序；评价 None／空串 hash 口径统一。

## 5. 未验与停写交接

- OpenCode 未执行真实 AI。Codex 真实 DeepSeek 共 3 次：一次首样本质量不通过、一次 unknown、一次显式 retry 成功；修后候选 `5wTzMdK89pESunHc0GQqAA` 已通过姓名／审核包装及实际换行核对，将直接用于 Codex 采用／评价重写，不再额外生成。600 图完整成功容量与 1024MiB 组合阈值已由 Codex 独立执行通过（约786MiB）。
- 未验 E09／E10 页面／列表、E11／E12 Word／宿主、E14 整包、干净机器、Win10／WPS、其他 DPI／多显示器、跨设备及发行；完整 A01–A22、教师体验、真实库／照片未验。
- 当前结果不把 256MiB 写成通过；1024MiB 是 Codex 同意的临时工程验证阈值，不是运行时硬上限。
- Codex 已独立执行观察 58 项、相关桌面 85 项及 capacity（exit 0，主/overlap success，2 次受控 TLS，组合约786MiB）；R13 撤回后五文件已精确匹配 R12 manifest，原 718 全 local 窗口可对应。OpenCode 不再修改源码／测试／验证脚本，等待 Codex 直接使用已通过候选完成采用／评价重写并收口。未执行 Git 操作。
