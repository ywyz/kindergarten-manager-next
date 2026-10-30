# AI 手动重试与 GitHub Releases 更新实施结果

更新：2026-10-30（r04 定点回修）。状态：RG-R01–R10 必要实现与自测完成，停写等待 Codex 独立复验。
r01 完成 GitHub／观察页面主体；r02 完成 RG-R01–R07；r03 修复 RG-R08 helper 返回值接续与 RG-R09 暂停文案并完整运行 U2；r04 修复 RG-R10 普通配置不得启用测试网络覆盖。未 commit／push，未发行，未调用真实 AI，未执行冻结 EXE，未改 SAC／架构，未接 WebDAV。

基线：`e94ed688dd6e38f908644692339ffa76e523e28c`，分支 `codex/desktop-v2-foundation`。产品决定见 [desktop-retry-github-review.md](desktop-retry-github-review.md)、[更新规格 §10](../specs/desktop-application-update.md#10-2026-10-30采用github-releases检查新版) 及 [观察记录 §5.1](../specs/desktop-game-observation.md#51-生成与单栏重写)。

## 1. 边界与结论

- 继续使用原 OpenCode 会话、build、`opencode-go/deepseek-v4.1-flash#max`；未另起实现者、分支或子代理。
- 只使用独立合成数据、合成 worker、受控 TLS／loopback 服务与固定 HTTPS 测试；未访问真实 GitHub API／Release／CDN，未读取原业务库／凭据／模板，未生成正式私钥或 Release。
- 本记录只说明源码／合成／受控 TLS 范围结果，不代表冻结更新、真实供应商 AI、教师体验、Win10／WPS／签名或发行通过。
- 未修改 Codex 的 review、规格、`docs/tasks/current.md`、`AGENTS.md` 等文档；工作区中这些文件的既有修改保持原样。

## 2. RG-R01：真实 GitHub CDN 路径

`desktop/update_github.py`：

- 固定 CDN 主机仍为 `release-assets.githubusercontent.com`；路径校验改为接受真实形状
  `/github-production-release-asset/93446099/<uuid>`，并保留严格的旧
  `github-production-release-asset-<tenant>/<id>/<id>` 兼容形状。
- 不再以造出的 `-2e65be/123/456` 夹具作为兼容证据；回归使用真实 `github-cdn-head-readonly.json`
  的 slash 形状。
- API-only 来源（`allowed_redirect_hosts=()`）不能借通用 validator 接受 CDN 资源；只有签名清单来源可跳转。

## 3. RG-R02：pending 不消费旧 execution 进度

`frontend/src/d1/views/ObservationEditorView.vue`：

- 重试成功后进入 `aiAwaitingNewExecution`，记住旧 `execution_id`；pending 即使后端仍返回旧 execution id，也不绑定、不读取、不显示旧进度。
- 只有出现不同的新 execution id 后才解除等待并绑定；绑定变化时清空 thinking、elapsed、phase、seq。
- 进度读取只允许 `claimed`／`dispatching`／`retry_wait` 且已绑定 execution；`progress.execution_id` 必须严格等于当前绑定，attempt 变化、seq 回退、旧 execution 均拒收。
- 持久 `reason` 与思考文字仍分离；终态清空等待状态，重开 pending 时按旧 execution 历史处理。

## 4. RG-R03：检查全过程 busy 与去重

`desktop/update_service.py`：

- GitHub 检查在 API latest + 签名清单验证完成前始终保持 `checking`，不再在 API 解析后提前发布 `available`。
- `check()` 在 `checking`／`downloading`／`verifying` 期间去重；阻塞 manifest 时第二次检查不会发第二个 latest。
- 最终状态只通过 generation-aware 发布；关闭／旧 generation／迟到错误不会改写新状态。检查路径不再写任何信任配置。
- 缺资产／缺公钥／清单 404 仍作为“发现新版但暂不可用”发布，且 `download_available=false`。

## 5. RG-R04：helper 信任配置不被检查覆盖

- 删除 `UpdateManager` 的 `release_config_path` 与检查阶段写配置逻辑；主程序不再向业务数据根或更新器目录覆盖信任材料。
- 主程序与 helper 各自读取构建嵌入的固定配置；helper 继续从自身受信任位置读取，不采用可变 plan 中的公钥。
- `update_helper._load_manifest(verification_context=False)` 对 GitHub 来源从签名清单版本派生允许的 tag／固定包地址（`version` 或 `v` + `version`），不信任 plan 提供的 tag。
- 新增 `_verify_saved_package()`，helper 主流程复用它完成 ZIP 大小／SHA／包内清单复核。
- 合成测试实际调用产品 helper 的 `_load_manifest(False)` 与 `_verify_saved_package()`，覆盖同一签名／身份／完整 ZIP；坏 key、坏签名、错误包路径、坏 hash 均拒绝。

## 6. RG-R05：受控 TLS 与完整下载

- `update_trust` 仅增加 test-only `connect_port` 映射；产品仍固定 HTTPS 443、公网 DNS、证书校验，测试参数不能进入产品来源。
- `desktop/tests/test_update_github.py` 新增真实 loopback TLS 服务，证书 SAN 覆盖 `api.github.com`、`github.com`、`release-assets.githubusercontent.com`，完成：
  latest → `github.com` 302 → CDN 真实形状 302 → 签名清单 → 完整 ZIP → SHA／包内清单校验 → `ready`；
  请求无 Authorization，Host 逐跳正确。
- 同一受控 TLS 覆盖坏签名、坏 hash、错误 tag／包地址、缺资产、禁止跳转；错误消息不含 CDN 时效 query。
- 覆盖真实下载取消与总 deadline；产品校验未因测试 adapter 放宽。
- `draft`／`prerelease` 必须是严格布尔值，非布尔值按格式错误拒绝。

## 7. RG-R06：AI 闭环与页面竞争

- 新增合成 worker 模式 `fail_once`：第一次发送前失败、重试后成功，不访问真实供应商。
- 后端 API 闭环测试：失败任务保留旧 execution；手动 retry 保留旧失败执行并创建新 generation；新执行成功生成候选；预览／采用只改变选中目标，原正文其他字段、照片顺序／说明、既有历史保持；旧失败执行仍为 failed。
- 前端新增：
  - R19 pending 旧执行进度、claimed 新执行收到旧进度、seq 回退、attempt 变化、新进度正常显示；
  - R20 单栏重写失败一次重试、成功候选加载、正文／照片保持；
  - R21 卸载后迟到 retry 响应不写页面；
  - R22 保护性保存期间重复确认只发一次 retry；
  - R08 重开记录发现最近失败／unknown 并恢复确认状态。
- 既有 R16／R17／R18 保留：unknown 无确认零 POST、双击一次、source_changed 拒绝旧输入、丢回执同键重交。

## 8. RG-R07：E14 构建／归档覆盖

- `desktop/build_e14.py` 的 `SOURCE_GROUPS["product"]` 增加 `desktop/update_github.py`。
- `desktop/verify_e14_package.py` 的 `ARCHIVE_REQUIRED_MODULES` 增加 `update_github`。
- `desktop/tests/test_e14_build_guard.py` 实际调用 `source_freeze()`，规范化路径后断言包含该模块，并断言归档关键模块列表包含 `update_github`。
- 未运行新冻结构建，未修改旧候选／包。

## 9. RG-R08：U2 helper 返回值接续

`desktop/update_helper.py`：

- 修复 `run()` 中 `_verify_saved_package(plan, manifest)` 返回值未接住的问题，改为 `verified = _verify_saved_package(...)`；后续 `_rename_with_retry(verified.root, app)` 使用实际校验根，不再 NameError。
- 保留 ZIP 大小／SHA／包内清单复核、安装计划绑定、授权复核、旧目录备份与新目录切换保护；未放宽安全校验。
- 完整运行 `desktop/tests/test_update_u2.py`（真实独立进程、真实 LocalRuntime／SQLite、真实 helper 切换目录），30 passed；目标用例 1 passed。
- r01／r02 的 55／81 项命令只含 GitHub／U1／U3／E14 guard，未含 U2，不能作为安装回归证据；本轮 U2 为真实自测。

## 10. RG-R09：暂停状态文案

`frontend/src/d1/views/ObservationEditorView.vue`：

- `pollTask` 终态 toast 按 `failed`／`outcome_unknown`／`paused` 分开：暂停显示“AI 任务已暂停：请查看原因后再决定是否重试”，不再伪称结果不明。
- 重试提示标题按状态区分：`AI 任务失败`／`AI 结果不明`／`AI 任务已暂停`；原因行暂停显示“暂停原因”。
- 只有 `requires_ack`（unknown／可能已处理）显示重复处理／计费风险；已知暂停显示“通常尚未发送或等待配置处理”，不制造 unknown 费用风险。
- 新增 R23 页面回归：暂停任务显示暂停标题与 toast，且不出现“结果不明”。

## 11. RG-R10：普通配置不得启用测试网络覆盖

- `desktop/update_github.py` 的普通产品入口 `load_github_source()` 不再从 `update_release.json` 读取任何测试专用字段；`test_only`、`ca_pem`、`connect_host`、`connect_port`、`server_hostname` 任一出现即 `ReleaseConfigError`，即使值为 `false`／`null` 也拒绝。
- `desktop/update_trust.py` 的普通 `load_release_source()` 同样拒绝上述字段，文件不能启用 test transport。
- 受控 TLS 测试仍通过显式内存构造 `api_source(test_only=True, ...)`／`manifest_source(...)` 使用；没有新增产品 CLI／env 覆盖，也未改正式密钥、固定 repo／URL 或用户行为。
- 新增测试：普通 loader 逐字段拒绝、正常仅公钥配置仍可 GitHub 发现、缺配置仍返回可发现但无公钥来源、非测试 `ReleaseSource` 拒绝连接覆盖、显式内存 test 来源仍可 validate。
- Codex 探针 `codex/product-loader-probe-r03-result.json`／`codex/product-test-override-probe-r03.json` 保留为外部反例；本轮修复后普通 loader 不再接受该配置。

## 12. 自测命令与结果

所有命令使用既有 `desktop/.venv-d1`，未安装依赖。日志保存在私有证据根下 `opencode/logs/`（相对文件名）。

| 命令 | 结果 | 日志 |
| --- | --- | --- |
| `python -m py_compile` 本轮改动 Python 文件 | RC 0 | 终端 `PY_COMPILE_OK` |
| `pytest desktop/tests/test_update_u2.py -q`（r03，本轮未重复全量） | 30 passed | `test-update-u2-r01.log` |
| `pytest desktop/tests/test_update_u2.py::test_helper_reverifies_original_zip_and_switches_directory -q` | 1 passed | `test-update-u2-target-r01.log` |
| `pytest desktop/tests/test_update_github.py test_update_u1.py test_update_u3.py test_e14_build_guard.py -q` | 81 passed（r02 基线，不含 U2） | `update-e14-final-r03.log` |
| `pytest desktop/tests/test_update_github.py -q` | 40 passed | `test-update-github-r18.log` |
| `pytest desktop/tests/test_update_u1.py test_update_u3.py test_update_u2.py::test_helper_reverifies_original_zip_and_switches_directory -q` | 33 passed | `update-loader-r01.log` |
| 用 Codex 反例配置分别调用 `load_github_source`／`load_release_source` | 两者均 `ReleaseConfigError` 拒绝 | `product-loader-probe-r04.log` |
| `pytest backend tests/local/test_observation_api.py test_observation_ai.py -q` | 54 passed | `observation-backend-final-r02.log` |
| `frontend npm run typecheck` | RC 0 | `typecheck-final-r04.log` |
| `node src/d1/d1.observation.test.mjs` | 62 observation page checks passed | `d1-observation-r14.log` |
| `git diff --check` | RC 0（仅 Git CRLF 提示） | 终端 |

r02 的完整 `npm run test:d1` 已独立通过（D1 60、W5 94、历史 22、更新 14、观察 61，`frontend-test-d1-final-r03.log`）；r03 只改了暂停文案，按交接要求未重复全量前端，只跑观察页面 62 项与 typecheck。

## 13. 失败记录（保留，不覆盖 r01）

- `test-update-github-r01.log`：r01 首失败（测试 fake 把相对路径当 API），保留。
- `test-update-github-r08.log`：r02 删除旧 `release_config_path` 后旧测试未同步；属测试夹具。
- `test-update-github-r09.log`：helper 完整 ZIP 测试未把 package `build_id` 写入签名清单；属测试夹具。
- `test-update-github-r11.log`：下载等待辅助函数把 `downloading` 当作终态提前断言；属测试夹具。
- Codex 独立 U2 失败证据 `codex/u2-real-switch-r02.log`／`.exit` 及临时根由 Codex 保留；该失败不是本轮自测结果。r03 修复后目标用例与完整 U2 均通过。
- Codex 的 `product-loader-probe-r03-result.json`／`product-test-override-probe-r03.json` 是 RG-R10 外部反例，不是本轮自测；r04 修复后普通 loader 拒绝这些字段。
- 以上自测夹具失败未放宽产品校验；修正后通过。

## 14. 未验事实

- 未访问真实 GitHub API／Release／资产／CDN；真实 404／403／429、真实重定向、真实 DNS／TLS 与限流未验（Codex 只读 HEAD 证据另记）。
- 未生成正式发行公钥／私钥，未构建或上传正式清单／完整包，未创建 Release；未执行冻结 EXE 或真实用户安装／升级／回滚。U2 使用真实独立 helper 进程与合成受管目录完成目录切换验证，不等于真实发行安装。
- 未调用真实 DeepSeek／MiMo；AI 闭环仅合成 worker 与页面 fake。
- 未执行冻结 EXE，未验证 Win10、WPS、签名、其他 DPI／多显示器或发行再现性。
- 未改 SAC／架构／WebDAV，未做教师体验或整包验收。

## 15. 本轮改动文件

r02／r03／r04 修改：

- `desktop/update_github.py`
- `desktop/update_trust.py`
- `desktop/update_service.py`
- `desktop/update_helper.py`
- `desktop/d1_main.py`
- `desktop/build_e14.py`
- `desktop/verify_e14_package.py`
- `desktop/tests/test_update_github.py`
- `desktop/tests/test_e14_build_guard.py`
- `backend/tests/local/w3_tls.py`（仅测试证书多 SAN）
- `backend/tests/local/obs_ai_workers.py`（仅合成 `fail_once`）
- `backend/tests/local/test_observation_api.py`
- `frontend/src/d1/views/ObservationEditorView.vue`
- `frontend/src/d1/d1.observation.test.mjs`
- `docs/bootstrap/desktop-retry-github-result.md`（本文件）

r01 已保留的更新页面／测试改动：

- `frontend/src/d1/update.ts`
- `frontend/src/d1/views/UpdatePanel.vue`
- `frontend/src/d1/d1.update.test.mjs`

未修改：`backend/app/local/observation_api.py`、`backend/app/local/observation_ai_service.py`、`desktop/update_install.py`、`desktop/update_manifest.py`、`ARCHITECTURE.md` 及 Codex 的 review／规格／任务文档。
