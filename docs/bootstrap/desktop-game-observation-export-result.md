# 游戏观察批选／排序、Word 导出与宿主交付结果（D4 E10–E12／E14）

更新：2026-10-28。**原OpenCode停写交付时：本片实施与自测完成，等待Codex独立核查，尚未提交／推送／发布。** 本文保留实现者当时的自测与失败回修，不替代最终独立结论；接续核查及Git收口以[独立审阅§6–§7](desktop-game-observation-export-review.md#6-最终独立结论本片限定工程核查通过)为准，不把教师体验、整包、安装、发行或真实AI记为通过。

## 1. 范围与边界

按产品 C1–C33、工程 E10–E12／E14、`docs/modules/game-observations.md` §7 与 Word／审计扩展完成：

- 列表跨页明确 ID 勾选、实际选集、默认稳定排序、手调顺序；筛选／分页不扩大或静默缩小选集；不新增业务份数额度。
- 编辑页导出入口：先 settle IME／材料在途，成功保存当前 UI 编辑并以 `pre_export` 留应留历史节点，再进入固定预览；失败／冲突／未知停留当前页。列表导出增加独立的 `prepare` 保存步骤，再走只读预览，不把 preview 偷改成业务保存。
- 三模板 Word：A4 纵向、原六列网格／八行业务表、固定五领域、照片正文后 inline、每组最多两张、等比不裁切、不印 caption、每份新页、无额外空白末页。
- 固定 snapshot／export token／host attempt：创建时写锁内最小绑定复核，固定快照可明确新 token 重试；产物写入受管临时目录，sidecar 仅作缓存，交付前同时核对创建回执、snapshot/manifest、DOCX 摘要／大小。
- 受限宿主流式下载与同目录临时文件原子替换；固定 loopback、无重定向、无环境代理；总 deadline 覆盖状态行／headers／body，包括 `will_close`／`Connection: close`；宿主不直连 SQLite，不沿用旧 daily `save_docx`／30MiB Base64 通道。
- 过期 snapshot 清理有界、幂等；排除已释放 tombstone；旧 launch 的 in-progress attempt 记 `indeterminate` 并释放，当前活跃 launch 的在途 attempt 保留。

未调用应用真实 AI；未改原体验库、配置／凭据、OneDrive 原件、旧包或远程资源；未安装依赖／Skill／MCP，未改 `ARCHITECTURE.md`；未提交 Git。

## 2. 实施摘要

### 2.1 后端

- `backend/app/local/observation_export_service.py`
  - `prepare_export`：显式 `pre_export` 保存，确定性逐记录 request id，回执幂等；不创建 snapshot。
  - `preview_export`：冻结有序 draft revision／aggregate hash／导出派生 ID、hash、尺寸、缺项／警告、模板／渲染版本、profile／launch／session scope、期限；只读，不做业务保存。
  - `create_export`：短事务外物化；真正 `BEGIN IMMEDIATE` 内复核有序 ID、draft revision／aggregate、照片绑定、缺项 hash 与 snapshot 期限；变化拒绝并清理本次临时产物。`retry_existing` 只对已存在 token 的有效固定 snapshot 新建 token。
  - 受管临时 DOCX＋sidecar；文件写入同句柄／父目录持有、nlink／reparse／最终路径校验；refcount 保护在途流；终态／过期释放。
  - 交付前 `_create_receipt_facts` 用持久化 create operation 的精确 `export_id` JSON 键定位创建回执，核对 export_id hash、snapshot_id、manifest_hash、content_hash、byte_size；sidecar／DOCX 协同改写或 snapshot 换绑均拒绝，不重建。
  - 过期 snapshot 清理：排除已 released tombstone；keyset 分批，超过 200 条可继续释放；旧 launch／旧 session scope 的 in-progress attempt 记 `indeterminate`、消费 token、释放临时产物，保留 attempt／token 回执锚点；当前活跃 launch 的在途 attempt 不清理。
- `backend/app/services/word_export_observation.py`：三模板哈希校验；表外标题 16pt 宋体加粗居中；基本资料／环境 11pt，四栏正文 12pt；五领域固定；照片组从模板 `tcW`／gridSpan／cell margins／paragraph indents 计算可用宽度，双图预留间距；inline run，唯一 `wp:docPr`；每份 `pageBreakBefore`；确定性 ZIP 时间戳。
- `backend/app/local/observation_export_api.py`：`prepare`／`preview`／create／content 流式响应／attempt start／latest／result／operation receipt；全部走本机 session／Origin／Host 保护。
- `backend/app/local/observation_service.py`：`read_current` 增加真实 `created_at`；schema 同步。
- `backend/app/assets/word_templates/observation_{public,indoor,outdoor}.docx`：用户空白模板清理动态样例值／标题后的受控资产；SHA-256 见 §4.3；README 登记来源映射、空白化与无媒体／无外链事实。

### 2.2 宿主

- `desktop/d1_host_api.py`
  - `save_observation_export(export_id, filename)`、`get_observation_export_result`；只从固定 `127.0.0.1:service_port` 读取，`http.client` 直连，无环境代理、无重定向。
  - `_DeadlineGuard` 对 connect／状态行／headers／body 使用单调总 deadline；定时 shutdown／close 当前响应底层 socket，覆盖 `will_close`；不覆盖教师原生 Save As 对话框。
  - 下载临时文件有上限、hash／长度校验、结构校验；同目录流式临时文件＋`os.replace`；只有实际 IO 成功才报 saved；unknown／failed／cancelled 分开；宿主经受限 API 回报 attempt。
  - 同一 export_id＋filename 重入只读原结果／在途；异文件名拒绝；不重复打开对话框；临时文件／busy 在超时、取消、失败后释放。
- `desktop/d1_main.py`：真实窗口 `obs-ui` 增加编辑页导出、取消导出、busy 归零、正常关窗，以及跨页多选／筛选保留／手调／混合导出步骤；`verify_observation_multi.py` 使用实际 checkbox／按钮 DOM。

### 2.3 前端

- `ObservationsView`：显式 ID 选集（Map＋order）、真实 `created_at` 稳定排序、手调、筛选／分页保留、缺失确认、preview／prepare／create／host 状态、未知回执、异步 epoch／alive／selection fingerprint 隔离、错误详情定位具体记录／照片、无 500 数量上限。
- `ObservationEditorView`：导出按钮先 `settleComposition`、`saveCurrent('pre_export')`，auto 后 aggregate 与最近保留节点不同仍会保存；冲突／未知／失败停留；晚到输入不导出；真实 `created_at` 传给列表预选。
- `App.vue`：编辑→列表导出前清除 editor busy；busy 回调按当前 editor 页面身份接收，旧组件晚到回调不能污染新页；host busy／page busy 归零后正常关窗。

## 3. 自测证据与命令

证据根：`C:/Users/yw980/AppData/Local/Temp/kgm-observation-export-20261028-7e7fb3c6/opencode-evidence`。本片自测子目录：`r02/logs`、`r02/obs-window-24`、`word-samples-4`、`capacity-2`、`capacity-service-3`。Codex 独立证据子目录未改动。

| 项目 | 命令／入口 | 实际结果 |
| --- | --- | --- |
| 后端专项 | `../desktop/.venv-d1/Scripts/python.exe -m pytest tests/local/test_observation_export.py tests/local/test_observation_api.py -q`（在 `backend` 目录） | exit 0；41 passed（日志 `opencode-evidence/r02/logs/backend-r02.log`） |
| 宿主专项 | `./.venv-d1/Scripts/python.exe -m pytest tests/test_d1_observation_export_host.py tests/test_d1_host_save.py -q`（在 `desktop` 目录） | exit 0；46 passed（日志 `opencode-evidence/r02/logs/desktop-r02.log`） |
| 前端类型／构建 | `npm run typecheck`、`npm run build:d1` | 均 exit 0 |
| 前端完整套件 | `npm run test:d1` | exit 0；观察页 54 checks passed；其他既有套件同命令通过（日志 `opencode-evidence/r02/logs/frontend-r02.log`） |
| 真实 WebView2 窗口 | `python desktop/verify_observation_window.py --output-dir .../r02/obs-window-24 --timeout 1200` | exit 0；`report.json.ok=true`；`obs_ok=true` |
| Word XML 辅助 | `python desktop/verify_observation_export_word_xml.py --input-dir .../word-samples-4` | exit 0；7 samples passed |
| Word COM 辅助 | `python desktop/verify_observation_export_word.py --word --output-dir .../word-samples-4` | exit 0；7 samples passed；Word 16.0，build 16.0.20527 |
| 纯渲染容量 | `python desktop/verify_observation_export_capacity.py --output-dir .../capacity-2` | exit 0 |
| 服务／HTTP／宿主容量 | `python desktop/verify_observation_export_capacity_service.py --output-dir .../capacity-service-3` | exit 0 |

R13 专项覆盖在宿主 46 项内：saved／canceled／failed／indeterminate 终态的回报失败均保留 `receipt_pending`；同一 token 重入不重新下载／弹窗／新建 attempt；只读查询不 POST；显式 `reconcile_observation_export_result` 只补报已知终态；补报成功后明确“同一固定预览重试”才按固定 snapshot 新建 token；回报在服务端提交前／后丢失与重复回报均按幂等终态处理；busy 归零。

### 3.1 真实窗口检查（r02/obs-window-24）

`report.json`：exit 0，`ok=true`；`checks` 全部 true：

- `obs_initialized`、`obs_create_and_edit`、`obs_history_restore`、`obs_conflict_and_leave`
- `obs_export_from_editor`、`obs_export_cancel_from_editor`
- `obs_export_host_busy_cleared`、`obs_export_app_busy_cleared`、`obs_export_cancel_busy_cleared`
- `obs_multi_page_mixed_export`、`obs_multi_export_busy_cleared`
- `window_exit_zero`、`window_summary_ok`；无 driver errors／notes。

多页步骤实际通过真实渲染 checkbox／按钮：第一页勾选 10 份；等待第二页稳定身份（首 ID 改变且与第一页无交集）后勾选第二页；加入带照片记录；切换真实“本月”日期筛选后选集保留；恢复全部日期；点击真实“下移”手调；点击真实导出按钮；实际保存 DOCX 后关闭弹窗，pageBusy／host busy 归零，正常关窗。结果：selected=16，titles=16，photos=1；DOCX 中每份唯一合成姓名／正文标识与选中顺序一致，无漏选、扩大或串份。取消路径使用受控 `create_file_dialog` 返回 None 的合成取消，不是教师原生 Save As 实机操作。

## 4. Word 样本与版面

### 4.1 样本（word-samples-4，产品导出服务生成）

| 样本 | 记录 | 照片 | 分组 | Word 页 | Inline | 末页可见正文／图 |
| --- | ---: | ---: | --- | ---: | ---: | --- |
| `01_public_zero_photo.docx` | 1 | 0 | — | 1 | 0 | 231／0 |
| `02_indoor_one_portrait.docx` | 1 | 1 竖 | [1] | 2 | 1 | 108／0 |
| `03_outdoor_two_mixed.docx` | 1 | 2 横＋竖 | [2] | 2 | 2 | 108／0 |
| `04_mixed_three.docx` | 3 混合 | 3 | [1,1,1] | 6 | 3 | 108／0 |
| `05_long_text_three_photos.docx` | 1 长园所／长文 | 3 | [2,1] | 3 | 3 | 109／1 |
| `06_five_photos.docx` | 1 | 5 | [2,2,1] | 3 | 5 | 108／0 |
| `07_missing_no_date.docx` | 1 缺项／无日期 | 0 | — | 1 | 0 | 104／0 |

Word 逐页核对：标题 16pt 宋体加粗居中；基本资料／环境 11pt，四栏正文 12pt；8 行 6 列表格；五领域固定；A4 纵向及原页边距；每份新页；末页无空白；caption 未打印。

### 4.2 照片几何（COM 辅助，非教师体验替代）

- `03` 横图＋竖图：同页、同一行（top 均 374.5），左图 196.2×98.1、右图 162.5×325，左起点 137.5／333.5，水平不重叠、垂直重叠充分。
- `06` 五图：第 1 组横＋竖同页同行；第 2 组第三／第四图同页、top 均 73.0、左 137.5／333.5、宽均 196.2，Word 实际并排（不是上下堆叠）；末单图对齐 `wdAlignParagraphCenter`。
- 所有组等比不裁切；`wp:inline`，无浮动 anchor、无嵌套 `w:p`；`docPr` 唯一。
- 模板实际 `tcW=8184`、gridSpan 5、默认 cell margins 与 paragraph indent 计算双图预算；不再硬编码 8184twips 作为图片总宽。
- COM 可见正文剔除 `\s` 及控制符（含图片占位 `\x01`），图片另以 shape counts 计；图片-only 页由 shape 计数判定有效。

### 4.3 模板资产

| 资产 | SHA-256 |
| --- | --- |
| `observation_public.docx` | `f3893b7427f7aac6b40706c7326ba8b1fce0104d8126a0c970c0fa98e6c04339` |
| `observation_indoor.docx` | `2295e7e1778e697221f06642c60df5424f51c994a6fefd1dd0e52fb2718d4a0c` |
| `observation_outdoor.docx` | `fb37741ddbf1dd3a1f37f2196b13536026614161741d04427124d459659eef83` |

来源为用户此前空白公共／室内／户外观察模板；构建时仅清空动态样例值／标题后缀，保留固定标签与结构；README 已登记映射与空白化。三份包内无 `word/media`、无 `TargetMode="External"` 外链；不记录原件真实路径或儿童资料。

### 4.4 Word 执行限制

普通 `powershell -NoProfile -File` 在本机 Restricted 执行策略下被拒绝（Codex 证据 `codex-independent/w01-word/word-inspection.log`）。需要如实说明：本片早期自测曾使用过 `-ExecutionPolicy Bypass`；Codex 指出后已移除，最终入口不再使用 Bypass、`Invoke-Expression`，也未修改系统执行策略；早期 Bypass 自测不作为独立通过，普通 PS 被拒绝的事实保留。最终 Word 自动入口改用桌面 venv 既有 Python.NET／Office COM 文档 API（`verify_observation_export_word_com.py`），仅文档 API，不新增依赖。XML／COM 只是辅助；最终教师逐页仍以真实 Word UI 为准，Codex 已提供两轮 Word 实际逐页证据，但最终全量核查未由本片自测替代。

## 5. 容量证据

技术保护按实际累计字节／资源，不设业务份数／照片数门槛；累计像素仅诊断，不作为硬门槛。当前常量：照片 64MiB、正文 8MiB、DOCX 128MiB。

### 5.1 纯渲染探针（capacity-2）

| 场景 | 照片 | 照片字节 | 像素 | DOCX 字节 | 耗时 | 峰值 RSS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 11 份×3 张 2048×1536 | 33 | 3,167,890 | 103,809,024 | 289,937 | 0.111s | 93,188,096 |
| 600 张各异 800×600 | 600 | 13,865,526 | 288,000,000 | 2,886,809 | 0.741s | 107,044,864 |
| 超 64MiB 照片 | 29 张噪声 | 67,321,828 | — | 拒绝 | 4.846s | 107,044,864 |

说明：11×3 超过旧 100M 像素但仅约 3.2MB 照片、DOCX 约 0.29MB，故移除累计像素硬门槛；600 张各异小图通过。

### 5.2 真实 service→固定 snapshot→HTTP→宿主链（capacity-service-3）

| 场景 | 照片 | 源照片字节 | 派生字节 | DOCX 字节 | media | 宿主／回执 | 耗时 | 峰值 RSS |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| 11 份×3 张 2048×1536 | 33 | 3,167,890 | — | 246,044 | — | saved／saved | 0.064s host | 164,225,024 |
| 16 张 2048×1536 noise，DOCX>30MiB | 16 | 37,142,511 | — | 33,878,576 | 16 | saved／saved | 9.343s 全链／0.579s host | 234,295,296 |
| 600 张各异 800×600 | 600 | 13,865,526 | 8,612,517 | 2,462,995 | 600 | saved／saved | 106.830s 全链／0.108s host | 281,587,712 |
| 33 张 noise，累计 76,599,628 字节 | 33 | 76,599,628 | — | 拒绝 | — | 413 `OBS_EXPORT_CONTENT_TOO_LARGE` | 14.7s | 306,556,928 |

- 600 张场景真实经过材料导入、固定 snapshot、HTTP preview／create、宿主受限下载与原子保存；DOCX media=600，无漏图／扩图；未触发 64MiB 照片或 128MiB 文件上限，也无业务照片数门槛。
- >30MiB 场景 DOCX 33,878,576 字节，经新受限通道成功保存；旧 daily `save_docx`／30MiB Base64 上限测试仍保持，未被放宽。
- 超 64MiB 场景在 preview 阶段明确 413，`artifacts_before=0`、`artifacts_after=0`，无残缺 token／产物。
- 上述耗时为当前开发机合成数据实测，不是运行时承诺；未验证所有磁盘／内存／并发组合。

## 6. 失败回修记录（R01–R13）

| 项 | 回修与自测 |
| --- | --- |
| R01 | 照片 run 直接附入一个 `w:p`，每组 1–2 个 inline run；唯一 docPr；单／双／三／五图结构测试；Word 几何复验并排。 |
| R02 | 创建写锁内复核有序 ID、draft revision／aggregate、照片绑定、缺项 hash；同步屏障反例拒绝且无 token／产物；固定 snapshot 明确 `retry_existing` 新 token 与新鲜导出区分。 |
| R03 | 受管 DOCX＋sidecar、hash／size／refcount、终态／过期清理；移除无依据累计像素门槛；600 张、11×3、>30MiB、超 64MiB 服务链探针。 |
| R04 | 移除 500 ID 上限；选集按序列化字节限界；>31 份不截断、501 合法 ID 不因份数拒绝。 |
| R05 | 宿主固定 loopback、`http.client` 直连；无代理、无重定向；重定向／环境代理反例均不访问第二服务。 |
| R06 | 保留 preview／create request id 与 body；未知先查同域只读回执；异步 epoch／alive／selection fingerprint 隔离；变选／排序清确认并重新预览；错误详情给记录／照片 ID；稳定排序显式 null-last；列表显示起始时间／创建时间。 |
| R07 | metadata／DOCX 同句柄受管校验，拒绝 hardlink／junction／reparse；真实 Windows hardlink／junction 反例不读／不清根外对象；snapshot 到期释放有界、幂等，保留 attempt 回执锚点。 |
| R08 | 总 deadline 覆盖 connect／状态行／headers／body；定时 shutdown 当前响应 socket，覆盖 `will_close`；JSON／DOCX 均匀滴流、滴头、关闭连接后静默均有反例；超时清理临时文件、host busy 归零、回执 failed。 |
| R09 | 编辑页 `pre_export` 保存、IME settle、auto 后待留节点、丢响应／冲突停留；列表独立 prepare；真实窗口编辑→列表导出、取消、busy 归零、正常关窗。 |
| R10 | 按模板实际值列宽度／cell margins／indent 计算双图预算；Word COM 几何判同页同行／不重叠；末单图对齐居中；可见正文剔除控制符；多页真实勾选、筛选保留、手调、混合导出以唯一姓名／正文核对顺序。 |
| R11 | tombstone 排除；重复清理 released=0、hash／audit 不变；205 条跨批全部释放；旧 launch in-progress 记 indeterminate、消费 token、释放产物；当前活跃 launch 在途保留。 |
| R12 | 交付前按精确 export_id 持久化 create 回执核对 snapshot／manifest／content hash／byte size；DOCX＋sidecar 协同改写、snapshot 换绑均 409 拒绝；>200 后续 create 后旧有效 token 仍读原内容；重开 session 读取原产物。 |
| R13 | 所有 host 终态（saved／canceled／failed／unknown）保留 `receipt_pending`，不再只对 saved 设置；新增只补报已知终态的 `reconcile_observation_export_result`，不下载／不弹窗／不新建 attempt；只读查询保持只读；明确“同一固定预览重试”先补报，再按固定 snapshot 新建 token；cancel／failed／indeterminate／saved、回报前后丢失、重复回报、重入不重弹及 busy 归零均有专项。 |

## 7. 未验与保留边界

- 本文不是 Codex 最终独立全量核查结论；全 local／desktop／HTTP／真实窗口／容量／最终 Word／原生另存为仍由 Codex 接管。
- 教师原生 Save As 实机对话框未在本片自测中操作；取消路径使用受控对话框返回 None；真实 Word UI 逐页由 Codex／教师体验确认，COM／XML 仅辅助。
- 完整 A01–A22、教师体验、整包、安装／更新、发行源、WebDAV／跨设备、Win10、WPS、干净机器、其他 DPI／多显示器未整体通过。
- 真实 AI 调用为 0；MiMo 真实、复杂真实照片、真实凭据／配置未验证。
- 8MiB 正文与 128MiB DOCX 上限未在全部极端组合达到；64MiB 照片上限有真实拒绝证据。容量数字是当前开发机合成数据，不是运行时硬 RSS／整应用承诺。
- PowerShell 普通调用受执行策略限制的事实保留；最终入口未使用绕过，早期 Bypass 自测不作为独立通过。Word COM 入口依赖既有 Python.NET／Office，不替代教师真实 UI。
- 原失败、旧证据和 Codex 独立目录未覆盖；旧 daily 30MiB 上限与 `save_docx` 未修改。

原会话交付时已停写等待独立核查；接续最终状态见独立审阅§6–§7。
