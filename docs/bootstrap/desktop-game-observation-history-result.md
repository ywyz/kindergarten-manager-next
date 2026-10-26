# D4：E05／E08 保存、历史留存与恢复实现交付结果（OpenCode）

更新：2026-10-27。本文件记录 E05／E08 服务层实现、测试、故障与证据交付结果，供 Codex 冻结源码后独立核查。**尚未提交／推送，也不代表本片已通过或完整 A01–A22、产品验收完成。** 授权、基线及独立核查门槛见 [独立核查](desktop-game-observation-history-review.md) 与 [当前任务](../tasks/current.md)。

Codex收口接续：下文保留实现者交付时点的自测与停写记录；最终冻结源码独立663项全local／85项相关桌面、竞态与保留库复核已通过，见上述独立核查。第三个后台全local窗口未取得完成／exit证据，按未完成记录，不计通过；最终结论不混用这些自测窗口。

授权与边界：延续 2026-10-27 用户授权，仅 E05／E08 服务层；继续分支 `codex/desktop-v2-foundation`，基线 `5e3e46f`。未修改 `ARCHITECTURE.md`、迁移、依赖锁、生产宿主、Codex 的 review／current／AGENTS 文档；未调用真实 AI、WebDAV，未构建、安装、发布或执行 Git 操作。E03 既有材料行为及迁移保持不变。

## 1. 本批改动范围

### 1.1 生产代码

| 文件 | SHA256（前 16） | 改动 |
| --- | --- | --- |
| `backend/app/local/observation_service.py` | `26e0b8fade8ef737` | 新增创建／读取／整份保存服务：canonical 请求、照片 manifest、save reason、历史节点、学期决定、投影／计数、回执与审计 |
| `backend/app/local/observation_history_service.py` | `556569ec0b9945bb` | 新增历史列表／读取、恢复预览／提交、一次性 token、绑定复核、材料核验、期限与无变化结果 |
| `backend/app/local/observation_assets.py` | `b240623c502b9483` | 新增 `inspect_managed_asset`、`managed_asset_path`、`verify_managed_asset_identity`；复用 E03 同一受管句柄与 `_IMAGE_LOCK`，不重建派生图 |

### 1.2 测试与验证脚本

| 文件 | SHA256（前 16） | 改动 |
| --- | --- | --- |
| `backend/tests/local/test_observation_history.py` | `ff78421644d31041` | 新增 33 项 E05／E08 服务回归、并发／跨进程、真实 SQLite 故障及证据保留 |
| `backend/tests/local/worker.py` | `0b868796b4c4d7fe` | 新增 `observation_service_save`／`observation_service_read`／`observation_service_restore` 三类跨进程动作 |

工作区另有 Codex 维护的 `AGENTS.md`、`docs/bootstrap/README.md`、`docs/bootstrap/architecture-v2-readiness.md`、`docs/modules/game-observations.md`、`docs/specs/desktop-game-observation*.md`、`docs/tasks/current.md` 及 review 文件改动，均非本实现写入，不在本文件声明范围内。

## 2. 实现要点

### 2.1 E05：创建、整份保存、历史与回执

- 创建与保存均以 E01／E03 既有 `normalize_payload`、`aggregate_hash([canonical_payload, ordered_photo_manifest])` 为唯一业务 hash；照片 manifest 含 asset id、原图 hash、格式／尺寸／方向、顺序与说明，时间戳、revision、投影不入 hash。
- `auto` 只更新 draft／照片／投影／回执，不造历史；`manual`／`leave`／`pre_restore`／`pre_export` 相对**最近保留节点**判断：有变化才追加 version／version_photos；没有任何保留节点时 manual 即使内容未变也建立首个节点；无变化保存不增加 draft revision。
- 保存使用 `BEGIN IMMEDIATE`、`expected_revision` 与稳定服务端 fingerprint；先读本域 operation 回执，同 request 同 fingerprint 直接返回，异内容拒绝。所有业务写、operation、审计同事务提交或回滚；投影与 draft revision／hash 不一致时明确存储错误。
- A→B→A 不作全局 hash 去重，只与最近保留节点比较；当前照片移除不删除 asset 或历史。
- R02 收口：`create_observation` 显式选择已有学期、日期在该学期范围外时，成功保存并返回非阻断 `term_warnings=["date_outside_selected_term"]`，不自动改日期／学期；无日期或日期在范围内无 warning；同 request 回执保持原 warning。
- 学期决定：`keep_current`／`assign_selected`／`unassigned` 与保存一致；显式归属与日期范围不符仅提示，不静默纠正。

### 2.2 E08：预览与恢复

- 预览绑定 `profile/record/source_version/source_hash/base_draft_revision/base_draft_hash`、历史照片 manifest／材料 hash、有效 payload hash、学期决定及源／当前／所选学期实时配置 hash、request id 和 15 分钟期限。数据库只存 token 的 SHA-256 摘要，不存原 token。
- `keep_history` 以历史完整 payload 和 `term_snapshot` 为底；历史学期缺失、历史日期不在历史快照内、或预览后实时源学期范围变化均拒绝。`keep_current`／`assign_selected` 日期不在范围内返回 warning，不阻断。
- 材料核验在 DB 写事务外：`inspect_managed_asset` 通过**同一已核验句柄**流式 hash 并在 E03 `_IMAGE_LOCK` 内真实 `Image.open/load`，单图读取以 25 MiB 为界，不二次按路径打开、不重建 AI／导出派生图；进入短写事务后用严格受管布局与 `verify_managed_asset_identity` 复核路径／父目录／文件身份，不长时间持锁解码。
- 恢复先匹配主 operation 回执；无回执时在短事务重新核 token 未消费／未过期、request／base、source hash、最新保留节点、effective hash、material hash、学期绑定和材料身份。当前 draft 必须仍等于预览 base 且已有同 hash 保留节点，晚到编辑拒绝。
- 有变化：替换 draft／draft_photos，revision+1，追加 version／version_photos，更新投影与两个计数，写 restore 细节、主回执、审计并消费 token，同一事务成功或回滚。无变化：返回 unchanged，不增 revision 或 history，仍写恢复细节／回执并消费 token。
- 恢复不修改学期／班级／档案配置，不读取或改变 AI 配置、候选、执行器及网络状态。

### 2.3 R08：晚阶段真实 SQLite 故障

`test_restore_late_all_flush_fault_and_evidence` 不再依赖早期 flush 或不存在 ID：

1. 预览并保存故障前 draft revision／hash／current_version、version／version_photos／restore／operation／audit 计数。
2. 拦截业务最后一次 `session.commit`；在 hook 内先真实 `session.flush()`，在同一事务查询确认新 draft revision／hash／current_version、新 version 与 version_photos、restore 细节、operation、audit、preview `consumed_at` 均已出现／变化，写脱敏 stage marker（不含 token）。
3. 通过独立合成 `e0508_fault` 表的 `BEFORE INSERT ... RAISE(ABORT)` 触发器产生真实 SQLite 错误，由服务回滚。
4. 故障后逐集合与故障前 snapshot 比较：draft revision／hash／current_version、version、version_photos、restore、operation、audit 全部恢复；token 未消费；随后同 token 重试成功。
5. 用例包含真实合成 JPEG 关联，并记录原图文件 SHA-256 与 asset `content_hash` 一致。

### 2.4 R05：解码串行与锁边界

`inspect_managed_asset` 的 hash 为有界流式读取；实际 `Image.open/load` 复用 E03 `_IMAGE_LOCK`，与既有材料解码串行。解码／hash 全部在 DB 写事务之外；最终短事务内仅做路径、父目录、句柄与文件身份／大小／链接检查。未引入新队列、进程、容量或业务限额。

## 3. 命令与实际结果

统一解释器：`desktop/.venv-d1/Scripts/python.exe`（CPython 3.14.7 Windows x64，标准 GIL）。

### 3.1 本批定向回归

- R08 晚阶段全 flush + R02 创建 warning 两项：
  `python -m pytest tests/local/test_observation_history.py::ObservationHistoryServiceTests::test_restore_late_all_flush_fault_and_evidence tests/local/test_observation_history.py::ObservationHistoryServiceTests::test_create_explicit_term_outside_range_warns_without_blocking -q`
  → **2 passed / 1.93 秒 / 退出 0**（`r08-r02-focused.log`）。
- E05／E08 全文件：
  `E0508_EVIDENCE_ROOT=<evidence-root> python -m pytest tests/local/test_observation_history.py -q`
  → **33 passed / 20.54 秒 / 退出 0**（`history-final.log`）。

### 3.2 全 local 自测窗口（不得混为单一最终结果）

| 窗口 | 证据 | 结果 | 身份说明 |
| --- | --- | --- | --- |
| 早期源码窗口 | `local-all.log` | **656 passed / 572.97 秒 / 退出 0** | 更早实现窗口，早于后续小收尾，不用于最终源码身份 |
| 后续源码窗口 | `local-all-final.log` | **661 passed / 573.18 秒 / 退出 0** | 已包含多数 E05／E08 实现，但仍早于 R05／R02／R08 最后收尾，不等于冻结源码结果 |
| 当前生产源码窗口 | `local-all-delivery.log` | 未完成：仅保留进度，无完成／exit证据，不计通过 | 启动于最终测试证据断言补充前；生产源码与本次冻结身份一致，测试文件为补充断言前版本；最终测试文件由下述33项全文件回归及Codex独立663项覆盖 |

最终测试文件身份为 `backend/tests/local/test_observation_history.py` SHA256 `ff78421644d31041…`，其全文件回归 **33 passed / 20.54 秒 / 退出 0**（`history-final.log`）。上述 656／661 及当前后台窗口均不是 Codex 在冻结源码后执行的最终独立全 local；Codex 最终结果尚未产生，不把任一旧窗口写成最终通过。

## 4. 失败与修正

- 恢复 token 曾只绑定当前学期而漏掉源历史学期配置变化（R06 反例）：改为同时绑定源／当前／所选学期实时快照，并在预览与提交短事务内复核；源学期范围缩小后旧 token 及重新预览均拒绝，现稿不变。
- 恢复预览后晚到编辑曾可能以新稿作为 before 基线：改为预览绑定实际 base draft revision／hash，提交时直接复核当前 draft 仍等于该 base，且最新保留节点与当前 hash 一致。
- 材料核验曾只 hash 未真实解码、或按路径二次打开：改为同一受管句柄 hash + 解码，真实解码置于 E03 `_IMAGE_LOCK`，最终短事务仅做身份复核；增加替换、junction、超 25 MiB 文件的拒绝回归。
- R08 初版只在早期 trigger 失败并用不存在 ID 断言恢复行，不能证明全写集合回滚：改为上述最后一次 commit hook、真实 flush、真实 SQLite trigger 与逐集合比较。
- 测试清理曾对 junction 使用递归删除：改为 `os.rmdir` 解除 junction；证据 helper 对缺失 `observations` 目录做存在性判断；跨进程恢复在 reopen 后保留故障后 SQLite 一致备份。

## 5. 证据

证据根：`C:/Users/yw980/AppData/Local/Temp/kgm-observation-e0508-20261027-5135336c/opencode-evidence`。

| 证据 | 内容 |
| --- | --- |
| `history-final.log` | E05／E08 全文件 33 passed |
| `r08-r02-focused.log` | R08 晚阶段 + R02 创建 warning 2 passed |
| `r08-late-stage-marker.json` | 故障触发前同事务已 flush 的 draft／version／photos／restore／operation／audit／token 状态，不含 token |
| `r08-late-stage-fault/` | 故障回滚后 SQLite 一致备份、受管照片副本、前后计数／hash／原图 SHA-256 summary |
| `r08-late-stage-retry/` | 同 token 重试成功后 SQLite 一致备份与结果 summary |
| `r08-cross-process-restore/` | commit 后崩溃与 commit 前崩溃冷重启后的 SQLite 一致备份、历史／回执 summary |
| `local-all.log`／`local-all-final.log`／`local-all-delivery.log` | 三个不同源码窗口的全 local 日志；不合并为单一最终结果 |

已实际复核三份保留库：`PRAGMA integrity_check=ok`、`PRAGMA foreign_key_check` 0 行；summary 未保存原始 token。原图文件 SHA-256 与 asset `content_hash` 一致（`a955477ba6488487…`）。

## 6. 未验与阶段边界

- 本片仅服务层；E09／E10 页面与入口、E06／E07 视觉候选／采用、E11／E12 Word／宿主、E14 集成未实施，未调用真实 AI 或 WebDAV。
- 未构建或验证新冻结包、真实安装更新、发行源、干净机器、Windows 10／WPS、其他 DPI／多显示器及跨设备。
- 完整 A01–A22、教师体验、Word 逐页、真实库／照片与远程资源均未验；D2／D3 既有未验和 4551 后置保持。
- 上述为OpenCode交付时点；后续Codex独立最终结果及Git收口见独立核查，不把OpenCode自测写成独立通过。

## 7. 停写交接

OpenCode 已完成本批源码、测试、证据及本结果文件写入，现停止源码／测试／验证脚本写入。等待 Codex 冻结最终源码／测试，在独立 TEMP 及证据根执行最终全 local 与身份审计，并按授权完成提交推送。未执行 Git 操作。
