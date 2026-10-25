# D3-U 应用更新：开工工程方案（Codex 核定后 U1 实施版）

更新：2026-10-25。状态：**U1–U3在当前Windows 11限定源码／合成工程核查通过；真实冻结更新、发行源／安装和4551仍未验。** 最新证据见§19及独立核查§20；此前各节保留原轮次历史，不代表当前状态。
未构建或运行新冻结包，未修改真实数据／凭据，未调用应用真实AI、未使用WebDAV、签名或发布；Git由Codex按既有授权收口，提交身份以Git历史与最终交接为准。

依据：[当前任务](../tasks/current.md)、[应用更新规格 §8](../specs/desktop-application-update.md#8-2026-10-24开工方案核定限定源码合成工程)、
[Codex 核定 §3](desktop-update-review.md#3-当前结论)、[ARCHITECTURE.md](../../ARCHITECTURE.md)、
[ADR 0004](../adr/0004-local-desktop-architecture-proposal.md)、
[AI 工程规格 §2–4](../specs/desktop-ai-engineering.md#2-e1持久数据约束和升级)、
[D3-A 最终核查 §9](desktop-d3-history-review.md#9-最终独立核查通过)、
[G17 结果 §7–10](desktop-d2-g17-result.md#7-r03真实质量复验2026-10-22)。

## 1. 本轮只读核对与边界

已读：

- `docs/specs/desktop-application-update.md` 的教师流程、U1–U3、来源／包校验、数据保护与验收边界。
- `desktop-ai-engineering.md` 的冷升级、SQLite backup、运行锁、DPAPI 凭据、AI 退出与恢复规则。
- `desktop-d3-history-review.md` §9 的 H1／H2 通过范围、R01–R11 关闭及未验边界。
- `desktop-d2-g17-result.md` §7–10 的真实数据保护、4551／SAC、签名暂停及原包保留事实。
- 限定源码：`desktop/build_d2.py`、`desktop/d1_main.py`、`desktop/d1_host_api.py`、
  `desktop/d1_paths.py`、`backend/app/local/runtime.py`、`backend/app/local/sqlite.py`，
  以及现有 `App.vue`／`leave.ts`／`bridge.ts` 的关闭与导航边界。

已有事实：

- 当前包是 PyInstaller **onedir** 完整目录包；`build_d2.py::build_package` 打包前端、
  `migrations_local`、Word 模板和运行资源，但不包含应用版本／构建身份，也没有更新客户端。
- 宿主已有 `CloseCoordinator`、保存／IME／草稿／AI 任务退出握手、`_dispose_executor` 和
  `LocalRuntime` 数据根独占锁、旧库冷升级备份及 revision／完整性检查。
- 当前应用没有固定发行 URL、版本元数据、更新签名或更新暂存目录；这些不能从现有包内
  SHA 清单推断为可信来源。
- teacher-talk-r01 仍受 SAC 4551 拦截；真实新包安装／启动和教师发行体验仍未验。

本轮不把“已有冷升级”写成“已有应用更新”，也不把合成安装验证写成冻结包或教师产品通过。

## 1.1 Codex 核定后的强制修订

以下取代本文件原初稿中与之冲突的表述：

- 小更新器属于现有桌面宿主维护实现细化，不另立 ADR；本轮只实现 U1，不实现小更新器运行／安装。
- 稳定应用 ID `kindergarten-manager-next`、渠道 `stable`、当前源码基线 `0.1.0`；严格三段数值
  SemVer；构建 ID 使用 UUID；版本、构建 ID、数据库 revision、日计划内容版本分开。
- 固定 HTTPS 源 + 嵌入 Ed25519 公钥验签元数据；合成测试可注入独立临时 TLS／Ed25519 身份，
  不得创建或读取正式发行私钥。Windows Authenticode／SAC 签名仍暂停。
- 真实发行 URL／公钥／发布流程未选定。构建配置缺失时返回“渠道尚未配置”，**不联网、不猜地址、
  不回退任意 URL**；产品入口不接受运行时 URL／公钥覆盖。测试注入只进入测试构造器。
- 源运行默认禁用产品更新；测试挂接必须有专用验证入口和严格合成根，不能把仓库或旧验证包目录
  当正式安装目标。
- 安装计划须绑定旧进程身份＋创建时间／句柄、独立安装锁、随机 nonce 与新版 ready 回执；
  U2 实施，U1 只定义边界，不伪造安装成功。
- 下载／ZIP／清单校验拒绝 Windows ADS、设备名、尾点／尾空格、大小写冲突、链接／重解析／
  硬链接绕过；暂存与程序路径必须同卷且分离于数据／凭据。
- 取消只清本次未完成下载；故障材料和未知安装状态不自动清理；U1 不实现安装阶段记录。
- 桥接沿用 `page_ready`／同源／应用会话保护；页面不传 URL、路径、PID、命令、摘要。U1 不提供
  安装按钮或安装端点。

## 2. 总体方案

沿用现有技术栈和桌面宿主职责，不新增安装框架、常驻服务、数据库或全局管理员权限。
更新分为：

1. **宿主内 UpdateManager**：固定发行源、检查、下载、完整包校验、暂存和状态查询。
2. **受限桥接接口**：页面只拿状态／操作结果，不接收任意 URL、文件路径或命令。
3. **独立小更新器**：仅用于旧进程退出后的目录切换和新版启动；不承担业务、数据库迁移或网络下载。
4. **既有冷升级**：新版首次启动仍由 `LocalRuntime.prepare` 取得数据根锁、按已知旧 revision
   创建一致性备份并迁移；更新器不直接改数据库。
5. **既有退出握手**：安装确认复用正文／IME／设置／候选草稿／AI 任务退出保护，不另造强杀通道。

**需要 Codex 先确认的架构点**：独立小更新器是一个新的运行时组件。若 Codex 认为它改变模块边界或
通信机制，应先形成 ADR 草案再实施；本轮不实现。若不接受独立更新器，则不能安全地在旧进程退出后
替换完整目录包，U2 不能以“脚本直接覆盖”替代。

发行 URL 仍未定案：方案中的 `UPDATE_ORIGIN` 是**构建时配置占位**，不是已选服务。
在 Codex 给出固定可信来源前，U1 不得连真实发行源；合成测试只能使用测试注入的本地 HTTPS 服务。

## 3. 应用版本身份

### 3.1 身份字段

建议新增构建／运行时共用的身份对象，字段固定：

| 字段 | 含义 |
| --- | --- |
| `app_id` | 稳定应用标识，例如 `kindergarten-manager-next`；不是计划／班级 ID |
| `app_name` | 稳定安装目录名，例如 `KindergartenManager`；不沿用验证包名 `KGNext-D2Verify` |
| `channel` | `stable`（首版只支持一个渠道；其他渠道未确认） |
| `version` | 严格 SemVer；当前源码基线 `0.1.0`；教师可见的应用版本 |
| `build_id` | 构建产生的不可猜、不可复用 UUID；不是计划内容版本，也不要求 Git 可用 |
| `package_format` | `pyinstaller-onedir-zip-v1` |
| `platform` / `arch` | `windows` / `x64` |
| `python` | `3.14.7`（当前基线；不据此承诺其他 Python） |
| `database_revision` | 本包迁移链 head |
| `supported_source_revisions` | 本包可从哪些旧 DB revision 冷升级 |
| `built_at` | 构建 UTC 时间，仅展示／审计，不替代版本比较 |

版本、构建身份、数据库 migration revision、日计划内容版本四者分开。当前日计划 `v6` 不是应用版本，
不能用于更新判断。

### 3.2 身份来源与校验

- `desktop/update_identity.py` 作为源码身份定义；构建脚本生成包根
  `build_identity.json` 和 `package_manifest.json`，两者写入同一 `app_id/version/build_id`。
- 运行时只从包内 `build_identity.json` 读取；源运行（未 frozen）默认禁用真实更新，避免把开发目录当安装。
- 包内 `build_identity.json` 必须与已签名发行元数据一致；不一致拒绝进入可安装状态。
- `database_revision` 由构建时的本地 Alembic head 生成，不能由页面或下载元数据随意指定。
- 更新只接受 `version` 严格大于当前版本；相同或更低版本拒绝，避免回放／降级。`build_id` 仅用于
  显示、去重和审计；不能把 `build_id` 大小当作版本顺序。

## 4. 固定发行源、元数据认证与下载

### 4.1 固定来源

建议的构建时配置（值待 Codex 提供，不在本轮选择）：

```text
UPDATE_ORIGIN = https://<approved-origin>   # 构建时固定，运行时不接受用户输入
UPDATE_CHANNEL = stable
UPDATE_METADATA_PATH = /<channel>/windows-x64/manifest.json
```

- 页面、命令行、环境变量和更新元数据都不能改变 `UPDATE_ORIGIN`；测试只能通过构造器注入
  `https://127.0.0.1:<controlled-port>` 的合成服务，产品路径不读取该注入。
- 元数据和包 URL 必须同源；包 URL 只接受相对路径。拒绝 userinfo、非 HTTPS、私网／回环、
  任意 host、跨源重定向和任意远端 URL。
- 不使用系统代理环境变量；不自动跟随重定向；只接受 HTTP 200，明确拒绝 3xx、4xx、5xx。
- 连接 10 秒、单次读取 30 秒、总下载有上限并可取消；下载线程不占数据库事务，不阻塞手工功能。

### 4.2 元数据格式与认证

建议的签名信封（示意，不是最终 JSON 文本）：

```text
{
  "schema_version": 1,
  "key_id": "<trusted-key-id>",
  "payload": {
    "app_id": "kindergarten-manager-next",
    "channel": "stable",
    "version": "1.2.0",
    "build_id": "<opaque>",
    "platform": "windows",
    "arch": "x64",
    "package_format": "pyinstaller-onedir-zip-v1",
    "package_root": "KindergartenManager",
    "package_url": "/releases/.../KindergartenManager-1.2.0.zip",
    "package_size": 123456789,
    "package_sha256": "<64 lowercase hex>",
    "database_revision": "<target head>",
    "supported_source_revisions": ["<old head>", "..."],
    "release_notes": "纯文本，有界长度",
    "published_at": "2026-10-24T00:00:00Z"
  },
  "signature": "<base64 detached signature over canonical payload>"
}
```

- 规范 JSON：排序键、UTF-8、无多余空白、禁止 NaN／重复键；签名覆盖规范 `payload` 字节。
- 公钥只以 `key_id -> Ed25519 public key` 的信任表嵌入应用；私钥不进入仓库、包、数据根或日志。
  现有 `cryptography==50.0.1` 已包含 Ed25519，不新增依赖。
- **这不是 Windows Authenticode 代码签名**，不改变 4551／SAC 状态；但它是发行元数据真实性的必要条件。
  本轮不生成密钥、不签名、不申请证书。若 Codex 将“任何签名”都排除在本阶段外，则 U1 不能宣称
  来源可信，不能用未签名元数据上线；需要另定可审计的发布审批方案。
- 签名验证通过后才解析版本、URL、大小、摘要、DB revision 和说明；失败不提示“更新失败”，
  而是明确“发行信息不可验证”，不进入下载。
- 包内自带 SHA 清单只用于解包完整性；**不能**作为发行来源证明。来源证明是上述签名元数据
  加固定 HTTPS 源。

### 4.3 下载与暂存

- 暂存根：`%LOCALAPPDATA%\KindergartenManager\updates\`；与程序目录、数据根、凭据根分离。
- 每次下载使用新的 `download_id`：`staging/<id>/package.zip.part`；独占创建，流式写并计算
  SHA-256／大小，完成后 fsync 并原子改名为 `package.zip`。
- 取消、网络中断、大小／摘要不符、空间不足都删除 `.part` 并保持旧程序／旧数据；不把半包标成可用。
- 成功下载后进入 `verifying`，完整校验通过才进入 `ready`；U1 不显示“已更新”，只显示“已下载并校验”。
- 重启不恢复未完成下载；启动时清理非 `installing` 的旧暂存（失败现场另存日志摘要，不删用户数据）。
- 失败状态区分：网络不可用／超时、元数据不可验证、平台或版本不符、摘要／大小不符、空间不足、
  取消、暂存被占用、包结构不合法。每种状态有明确重试／关闭动作，不自动并行重试。

## 5. 完整包校验

下载完成后按顺序：

1. **外层身份**：验签元数据；核对 `app_id/channel/platform/arch/package_format`；核对版本严格
   大于当前；核对当前 DB revision 在 `supported_source_revisions` 内。
2. **外层摘要**：ZIP 字节大小等于 `package_size`，SHA-256 等于 `package_sha256`；只接受非空 ZIP。
3. **ZIP 结构**：拒绝绝对路径、盘符、`..`、NUL、反斜线越界、加密项、符号链接／重解析项、
   重复名、大小写折叠冲突、压缩比异常、条目数／总解压大小超限；所有条目必须位于唯一
   `package_root/` 下。
4. **受管解包**：解包到 `staging/<id>/package/`，逐项检查路径仍在根内；不执行包内任何内容，
   不把 ZIP 内路径当命令或 URL。
5. **包内清单**：`package_manifest.json` 必须是严格 schema；列出除自身外全部文件及
   `size/sha256`；逐文件核对，拒绝缺失、额外、大小／hash 不符、重复或链接。
6. **包内身份**：`build_identity.json` 的 `app_id/version/build_id/package_format/database_revision`
   必须等于外层签名元数据；主 EXE、前端入口、迁移、模板和运行资源必须在清单中。
7. **可安装性**：EXE 是普通文件、路径稳定、暂存与安装根同卷、磁盘余量足够、目标目录未被占用；
   任一项失败保留旧程序／数据并报告实际阶段。

外层签名摘要和内部清单职责分开：外层证明“这个 ZIP 是批准的发行包”，内部清单证明“解包后没有
缺文件／多文件／被替换”。仅凭包内清单不能证明来源。

## 6. 安装进程与文件交接

### 6.1 目录布局（建议）

```text
%LOCALAPPDATA%\Programs\KindergartenManager\
  app\                        当前运行目录
  app.previous-<build_id>\    旧完整包，失败保留
  updater\KGNext-Updater.exe  稳定小更新器
  install-state.json          阶段与恢复信息

%LOCALAPPDATA%\KindergartenManager\
  data\                       现有数据根（不动）
  credentials\                现有同机凭据根（不复制）
  updates\
    staging\<download_id>\
    plans\<plan_id>.json
    results\<plan_id>.json
```

程序目录、数据根、凭据根、更新暂存严格分离。更新器不读取／复制凭据，不写业务数据库。

### 6.2 小更新器

建议新增一个无 GUI、无管理员权限、单文件的 `KGNext-Updater.exe`，由现有 PyInstaller 构建，
只接受受管目录内的 `--plan <plan.json>`，不接受 URL、任意目标路径、任意命令或页面参数。
其职责仅：

- 等待旧进程 PID 退出，并确认数据根 `.app-runtime.lock`／数据库不再被占用；不杀进程、不超时后强换。
- 再次核对暂存包的签名元数据、摘要、包内清单和目标版本；不重新下载。
- 将 `app` 重命名为 `app.previous-<build_id>`，将暂存 `package_root` 重命名为 `app`；同卷、独占、
  不覆盖已有备份；写入并 fsync `install-state.json`。
- 启动新 `app` 的主 EXE，等待受管 `results/<plan_id>.json` 的 `ready` 或 `failed`；不直接迁移数据库。
- 失败时保留旧包、新包、暂存和结果；按 §6.4 决定是否可安全恢复旧目录。

小更新器自身也是未签名 EXE，可能同样受 SAC 4551 影响；本轮不构建、不运行、不绕过。真实新包
安装仍单列待验。若 Codex 不接受新增小更新器，U2 需另定等价的安全交接方案，不能用页面直接执行
文件替换。

### 6.3 交接顺序

1. 页面在 U2 显示已校验版本和“安装并重启”，教师明确确认。
2. 页面调用受限桥接 `request_update_install(download_id)`；宿主确认状态为 `ready`、包未过期、
   无并行安装，生成 `plans/<plan_id>.json`（旧 PID、安装根、暂存、目标身份、当前 DB revision、
   结果路径、包摘要）。
3. 宿主把待安装意图交给既有 `CloseCoordinator`，走同一 `closing` → 页面保存／IME／草稿／AI 任务
   选择 → `complete_close(allow)` 流程。保存失败、结果不明、草稿未处理、继续等待或退出取消时，
   关闭不成立，更新意图清除，旧程序和数据不动。
4. 最终 allow 后，宿主从已校验包复制并校验小更新器到稳定 `updater\` 路径；启动更新器并立即销毁
   窗口。启动更新器失败则拒绝最终关闭，保留旧页面。
5. 更新器等待旧 PID／锁／DB 释放；超时即失败，保留旧程序，不杀旧进程。
6. 更新器完成目录切换并启动新 EXE；新 EXE 在受管结果路径写入 `ready`（版本、build、DB revision）
   或 `failed`（阶段、脱敏错误码）。更新器等待有界时间；只有 `ready` 且版本／身份匹配才记安装完成。
7. 新 EXE 首次启动仍由 `LocalRuntime.prepare` 取得数据根锁，按已知旧 revision 做一致性备份、
   integrity／FK／revision 检查并迁移；迁移失败不 stamp、不自动 downgrade，更新器保留旧包与备份。

### 6.4 失败与恢复

- 旧进程未退出、锁／DB 占用、更新器启动失败：不切换文件，旧程序继续。
- 旧包已改名、新包改名失败：同卷回滚旧目录；`install-state` 记录实际阶段。
- 新包已切换但新 EXE 未写 `ready`：保留旧包、新包和暂存；若 DB revision 未改变且新进程未迁移，
  可按状态恢复旧目录；若 DB revision 已改变，禁止自动回退旧程序，只保留备份和恢复说明。
- 迁移失败／新格式未知：新程序按既有规则拒绝写入；不自动恢复旧数据库，不把程序回退当数据库恢复。
- 更新器崩溃后再次启动：先读 `install-state`，只做一次有界恢复，不并行安装、不重复下载、不覆盖
  用户数据库；无法判定时保留现场并提示人工处理。
- 安装命令发出不等于成功；只有新版本 `ready` 且身份／DB revision 核对通过才写“已更新”。

## 7. 数据保护

- 更新器不打开业务数据库写事务；旧程序在退出前继续持有现有运行锁。当前 DB revision 通过
  `LocalRuntime` 的只读 inspection 读取，不新增业务表。
- 只有目标 `database_revision` 与当前不同且属于 `supported_source_revisions` 时才进入迁移；
  迁移前复用 `LocalRuntime.backup_before_migration` 的 SQLite backup、integrity／FK／revision
  校验与清单，不复制正在运行的 `.db` 文件。
- 迁移失败保留原库、备份和旧包；不自动恢复、不 stamp、不 downgrade。数据库已升级时旧程序不能
  无条件回退。
- 同机凭据根保持原路径，不复制、不迁移、不读取真实密钥；新包使用同一凭据根。合成验证使用
  独立凭据根。
- 更新不启动、停止、重发或改写 AI 任务；关闭握手沿用既有任务选择与 drain，不把更新当新的 AI 操作。
- 更新不改变 Word 模板、业务内容版本、历史、基准来源或恢复回执；U3 逐项读回验证。
- 真实 `KGNext-G17-20261022` 两库、凭据、r03／teacher-talk-r01 旧包、Word 和首次失败材料
  不在测试、备份、安装或清理路径内。

## 8. 界面与桥接边界

### 8.1 前端

建议新增：

- `frontend/src/d1/update.ts`：更新状态机、版本／说明展示、进度轮询、取消／重试、错误分类；
  不直接访问文件系统、不执行命令。
- `frontend/src/d1/views/UpdatePanel.vue`：启动提示、版本说明、下载进度、失败／重试、安装确认；
  说明为纯文本，不渲染远端 HTML。
- `frontend/src/d1/update.test.mjs`：纯状态机与真实 SFC setup 测试（U1/U2 实施时补）。

修改：

- `frontend/src/d1/App.vue`：启动检查、手动检查入口、更新面板挂载、把安装确认交给既有
  `LeaveCoordinator`；更新安装不是新的草稿类型，不绕过既有退出。
- `frontend/src/d1/views/WorkbenchView.vue`（或现有工作台工具栏）：手动“检查更新”入口。
- `frontend/src/d1/types.ts`、`frontend/src/d1/bridge.ts`：受限更新状态 DTO／桥接调用类型。

页面只接收 `available/none/checking/downloading/verifying/ready/failed/cancelled/installing` 等状态，
不接收绝对路径、URL、PID、包内清单或凭据；不把“下载完成”显示成“已安装”。

### 8.2 宿主桥接

在 `desktop/d1_host_api.py` 增加受限端点，并加入 `BRIDGE_ALLOWED_ENDPOINTS`：

| 端点 | 作用 |
| --- | --- |
| `get_app_identity` | 当前应用 ID／版本／build／DB revision；不含路径 |
| `check_for_update` | 去重启动／手动检查，返回可用／无更新／不可验证／网络错误 |
| `start_update_download` | 只接受宿主已知的 available 版本，返回 `download_id` |
| `cancel_update_download` | 只取消本宿主当前下载，不删用户数据 |
| `get_update_state` | 有界状态／进度；页面轮询，不新增推送机制 |
| `request_update_install` | 只接受 `download_id`；生成受管计划并进入既有关闭握手 |

所有端点要求 `page_ready` 和现有同源／应用会话保护；页面不能传 URL、路径、PID、命令、版本摘要
或任意包身份。宿主只在 frozen 产品运行启用真实更新；源运行只允许测试注入。

## 9. 原计划文件清单（U2／U3及后续；U1 实际见 §10.1）

### 9.1 新增

| 文件 | 工作包 | 用途 |
| --- | --- | --- |
| `desktop/update_identity.py` | U1/U2 | 应用 ID、SemVer、build、平台、DB revision 身份定义／读取 |
| `desktop/update_manifest.py` | U1 | 元数据规范 JSON、签名信封、版本／平台／DB 兼容校验 |
| `desktop/update_trust.py` | U1 | 固定来源、公钥信任表、TLS／重定向／大小策略；无运行时可改 URL |
| `desktop/update_service.py` | U1 | 检查、下载、取消、暂存、进度、失败状态、完整包校验 |
| `desktop/update_install.py` | U2 | 受管安装计划、稳定更新器路径、交接状态与恢复 |
| `desktop/update_apply.py` | U2 | 无 GUI 小更新器入口；只读 plan，等待退出并切换目录／启动新版 |
| `desktop/update_paths.py` | U1/U2 | 安装根、暂存、计划、结果、数据／凭据分离路径 |
| `desktop/tests/test_update_manifest.py` | U1 | 元数据签名、错误字段、重放／降级、URL 策略 |
| `desktop/tests/test_update_service.py` | U1 | 下载中断、摘要／大小、ZIP 越界、取消、重试、手工不受阻 |
| `desktop/tests/test_update_install.py` | U2 | 旧进程未退、目录切换、启动／迁移失败、未知阶段、恢复 |
| `desktop/verify_update_window.py` | U3 | 合成源码窗口更新链验证；不替代冻结包 |
| `frontend/src/d1/update.ts` | U1/U2 | 更新状态机与 DTO |
| `frontend/src/d1/views/UpdatePanel.vue` | U1/U2 | 检查／说明／下载／安装确认／错误 |
| `frontend/src/d1/update.test.mjs` | U1/U2 | 状态机与 SFC 交互测试 |

### 9.2 修改

| 文件 | 工作包 | 最小改动 |
| --- | --- | --- |
| `desktop/d1_main.py` | U1/U2 | 启动检查挂接、更新器交接、结果 marker、frozen 判定；不改业务启动 |
| `desktop/d1_host_api.py` | U1/U2 | 受限更新端点、bootstrap 身份、安装意图与关闭协调 |
| `desktop/d1_paths.py` | U1/U2 | 安装根／更新暂存／结果路径；不改变现有数据根 |
| `desktop/build_d2.py` 或新增 `desktop/build_d3u.py` | U2 | 生成 `build_identity.json`／`package_manifest.json`、打包小更新器；不覆盖旧构建根 |
| `backend/app/local/runtime.py` | U2 | 只读暴露当前 DB revision／复用既有备份入口；不改迁移规则 |
| `frontend/src/d1/App.vue` | U1/U2 | 启动检查、更新面板、手动入口、安装确认接入既有 leave |
| `frontend/src/d1/views/WorkbenchView.vue` | U1 | 手动检查入口（位置沿用现有工具栏，不新增页面） |
| `frontend/src/d1/types.ts` | U1/U2 | 更新状态／身份 DTO |
| `frontend/src/d1/bridge.ts` | U1/U2 | 受限桥接类型／协议版本兼容 |
| `desktop/requirements-d1.*` | U1/U2 | 预计不改；若签名／HTTPS 需要新依赖先单独说明，不自行安装 |

不修改 `ARCHITECTURE.md`；若独立更新器被认定为模块边界／通信机制变化，先按 §2 提 ADR 草案。

## 10. 分片验收方案（待实施，不预填通过）

### U1 检查与下载

- 合成固定 HTTPS 服务：无新版、有新版、元数据签名错误、错误 app_id／平台／版本、重放旧版本、
  包大小／摘要错误、3xx／超时、下载中断、取消、重试、暂存被占用。
- ZIP 安全：绝对路径、`..`、盘符、反斜线、符号链接、重复名、大小写冲突、条目数／解压大小超限。
- 实际文件：真实临时目录、真实下载字节、真实 SHA-256；不以字符串 mock 证明包完整。
- 启动检查不阻塞日计划打开／保存／Word；检查／下载失败仍可手工使用；启动／手动检查去重。
- 手工入口与页面状态显示真实进度；不显示“更新成功”直到 U2 完成。

### U2 确认、退出与安装交接

- 真实独立旧进程／新更新器／合成安装根；旧 PID 未退、锁／DB 占用、超时、取消、目标占用、
  目录改名失败、新版启动失败、迁移失败、未知阶段。
- 保存／IME／设置／候选草稿／AI 在途／退出取消均保持原页，不杀旧进程、不强换文件。
- 同机合成数据：旧库先备份再迁移；档案、配置、全部历史／来源／回执逐字段保留；凭据根可用；
  AI 请求不重发；Word 读取正确已保存内容。
- 程序回退与数据库恢复分开；数据库已升级时禁止自动旧程序覆盖。

### U3 完整链路与边界

- 旧版运行→发现→下载→校验→确认→退出→新版 ready→版本／DB revision 核对；手工、历史、配置、
  AI 状态和 Word 回归。
- 源码、合成安装、新冻结包、教师体验分别记录。SAC 4551 未解除前，新冻结包安装／启动和
  教师体验仍为待验，不以源码窗口或合成更新器通过替代。
- 不因更新验证恢复真实 AI、WebDAV、签名、系统防护修改或发布。

## 10.1 U1 源码实现与自测（2026-10-24，待 Codex 审核）

本轮只完成 U1 源码；**U1 未通过 Codex 审核，U2／U3 未实施**。未构建或运行新冻结包，未启动真实源码窗口；
前端只构建到独立临时根。真实发行 URL／公钥仍未配置，因此产品状态明确为“渠道尚未配置”，不联网。

### 10.1.1 实际实现文件

| 文件 | 状态 | 内容 |
| --- | --- | --- |
| `desktop/update_identity.py` | 新增 | `kindergarten-manager-next`、`0.1.0`、UUID source build、平台／包格式／DB revision；可选 `build_identity.json`。 |
| `desktop/update_trust.py` | 新增 | 固定 HTTPS 源、`update_release.json` 构建配置、内嵌 Ed25519 公钥表、产品源拒绝私网／回环／运行覆盖。 |
| `desktop/update_manifest.py` | 新增 | 规范 JSON、签名信封、严格 SemVer、平台／DB revision、完整包 ZIP／清单校验；拒绝 ADS、设备名、尾点／尾空格、大小写冲突、链接、越界和压缩异常。 |
| `desktop/update_service.py` | 新增 | 后台检查、真实 TLS 流式下载、进度、取消、重试状态、暂存、失败现场保留；无安装动作。 |
| `desktop/update_paths.py` | 新增 | 更新暂存／安装路径与数据／凭据根分离；U1 只使用暂存。 |
| `desktop/d1_host_api.py` | 修改 | `get_app_identity`、`check_for_update`、`start_update_download`、`cancel_update_download`、`get_update_state`；加入受限端点表；无安装端点。 |
| `desktop/d1_main.py` | 修改 | 构建运行时创建更新管理器；源运行禁用；关闭时停止下载线程。 |
| `backend/app/local/runtime.py` | 修改 | 只读 `current_revision` 属性，供应用身份使用；迁移规则不变。 |
| `frontend/src/d1/update.ts` | 新增 | U1 状态、目标／进度／错误文案、按钮可用性；`install_available` 固定 false。 |
| `frontend/src/d1/views/UpdatePanel.vue` | 新增 | 启动／手动检查、版本说明、下载进度、取消／重试、明确失败；**无安装按钮**。 |
| `frontend/src/d1/App.vue` | 修改 | 启动后非阻塞检查、手动入口、轮询状态、更新面板；不接入安装意图。 |
| `frontend/src/d1/views/WorkbenchView.vue` | 修改 | 工作台“检查更新”入口。 |
| `frontend/src/d1/bridge.ts` | 修改 | 受限更新桥接类型。 |
| `frontend/package.json` | 修改 | `test:d1` 纳入 U1 SFC 测试。 |
| `frontend/src/d1/d1.update.test.mjs` | 新增 | 8 项真实 SFC／内存渲染检查（含 App 启动、关闭轮询、迟到/卸载回包）。 |
| `desktop/tests/test_update_u1.py` | 新增 | 26 项真实受控 TLS／临时文件／ZIP／桥接／生命周期／隔离测试。 |

### 10.1.2 实际行为

- 启动：App 在本地上下文读取完成后调用一次 `check_for_update`，不阻塞工作台；同一 manager 的启动／手动
  检查在 `checking` 时去重，不并发请求。手动入口在工作台。
- 来源：`update_release.json` 缺失或 origin／公钥为空时状态 `unconfigured`，`check()` 不联网；源运行状态
  `disabled`。产品路径不读取环境变量或页面 URL；测试构造器可注入受控 HTTPS／TLS CA／Ed25519 测试公钥。
- 元数据：签名信封验证通过后才接受版本、平台、包大小／SHA-256、DB revision 和说明；版本相同为
  `up_to_date`；签名／字段错误为明确失败。
- 下载：真实 HTTPS 流式写入独立暂存，显示字节进度；取消会关闭当前连接、清除本次 `.part` 并显示
  `cancelled`；失败保留 `package.zip`／`failure.json`，不自动清理首次现场。成功后校验并进入 `ready`，
  但仍 `install_available=false`。
- 完整包：外层签名摘要、ZIP 路径／链接／Windows 名称规则、包内清单、构建身份、必需资源全部通过才 ready；
  包内 SHA 不作为来源证明。元数据／包内 JSON 严格拒绝重复键、NaN/Infinity 和 bool schema。
- 路径：暂存原始路径及全部祖先拒绝 junction/符号链接；ZIP 每个条目（含目录）在唯一包根内；解包后拒绝
  链接／重解析／硬链接。
- 下载：实际 `read1` 超时、总期限和末块取消均在 ready 发布前复核；关闭时确认线程退出。
- 身份：frozen 包缺失/损坏 `build_identity.json` 不静默回退 source；包内 app_name/channel/platform/arch 必须匹配
  外层；主 EXE 与 `_internal` 资源按真实 onedir 布局检查。
- 桥接：全部要求 `page_ready`；页面不传 URL／路径／PID／命令／摘要。`BRIDGE_ALLOWED_ENDPOINTS` 无安装端点；
  `UpdatePanel` 无安装按钮；ready 文案明确“本次没有安装”。

### 10.1.3 实际命令与结果

| 检查 | 命令 | 实际结果 |
| --- | --- | --- |
| U1 Python | `desktop/.venv-d1/Scripts/python.exe -m pytest tests/test_update_u1.py -q --basetemp=C:/Users/yw980/AppData/Local/Temp/kgmu-...` | exit 0，**26 passed**（13.47 秒，无 skip） |
| U1 SFC | `node src/d1/d1.update.test.mjs` | exit 0，**8 passed** |
| TypeScript | `npm run typecheck` | exit 0 |
| 既有 D2 组件（App 集成定向） | `node src/d1/d1.w5.test.mjs` | exit 0，**94 passed** |
| 独立前端构建 | `node node_modules/vite/bin/vite.js build --config vite.d1.config.ts --outDir %TEMP%/opencode/d3-u1-r04-fix-frontend-... --emptyOutDir` | exit 0，1622 modules；未打包 |

合成根／证据：

- Python 临时根：`C:/Users/yw980/AppData/Local/Temp/kgmu-...`；每次测试使用独立短根数据／凭据／暂存根；未删除
  Codex 首轮反例根。
- 前端构建：`%TEMP%/opencode/d3-u1-r04-fix-frontend-1792816522-9094/`；`d1.html`
  `5b822641a78a027a…`，`assets/index-B_7nL31g.css` `3105483303fa88a6…`，
  `assets/index-Cvvd1iFB.js` `64c8ee176c064aba…`。
- 日志：`C:/Users/yw980/AppData/Local/Temp/kgm-update-codex-20261024-103957/u1-r04-fix2-pytest.log`、
  `d3_u1_r04_fix_update.log`、`d3_u1_r04_fix_w5.log`、`d3_u1_r04_fix_typecheck.log`、
  `d3_u1_r04_fix_build.log`。
- 受控 TLS 服务只使用临时 CA／leaf 和测试 Ed25519 身份；无真实发行源、正式公钥、教师数据或凭据。

### 10.1.4 R01／R02／R04–R07 回修

- **R01 严格 JSON**：元数据、包内清单、构建身份统一使用拒绝重复键、NaN/Infinity 和 bool schema 的严格解析；
  `schema_version=True` 不再通过；测试覆盖重复信封字段、bool schema、包内清单重复/bool。
- **R02 路径安全**：新增 `update_fs.py`，在创建暂存目录前检查原始路径和全部祖先的 junction/符号链接，解包每个
  条目（含目录）都在唯一包根内，拒绝 ADS、设备名、尾点/尾空格、大小写冲突、链接和硬链接；真实 junction
  不再写出 outside 根；嵌套未列清单保护保持。
- **R04 超时/取消/关闭**：检查与下载持有实际连接及响应 socket（Connection: close 时 `conn.sock` 可为 None，
  改为 `response.fp.raw._sock`），在连接、响应头、正文每次读取前按剩余总期限收紧 socket；完整元数据迟到也不
  进入 available。末块、摘要、切换、校验及 ready 发布前复核 cancel；关闭/取消同时关闭实际响应 socket；检查
  连接纳入关闭代次，`shutdown()` 后不再发布 available、不再接受新 check/download；返回线程退出确认。真实 TLS
  keep-alive／Connection: close、分段滴流、read/总期限、末块取消及 shutdown-during-check 测试通过。
- **R05 配置/暂存/隔离**：非法源保持 `unconfigured` 且实际网络请求计数为 0；暂存目录创建失败明确
  `UPDATE_STAGING_UNAVAILABLE`，junction 明确 `UPDATE_STAGING_UNSAFE`；Manager 绑定 runtime 实际 data_dir／
  credential_root，暂存与其相同、祖先/后代或解析别名重叠时 `UPDATE_STAGING_OVERLAP`，不创建暂存、不发包请求；
  合成 sentinel 文件 hash 不变。
- **R06 身份/包布局**：frozen 身份缺失或损坏不再静默回退 source；当前身份严格核对固定 app_id/app_name/channel/
  platform/arch/package_format、三段 SemVer、UUID build、Python 与 DB revision；无效身份只禁用更新，手工可用。
  包内清单/构建身份同样核对；主 EXE 固定 `KindergartenManager.exe`，资源按真实 `_internal/frontend`、
  `_internal/migrations_local`、`_internal/app/assets/word_templates` 布局；内部 arm64 拒绝。
- **R07 App 启动**：启动 check 返回 `checking` 时轮询不再依赖面板打开；后台发现 available 自动打开提示；
  关闭面板后仍在途轮询；请求代次拒绝迟到 refresh；卸载后回包不应用。App SFC 新增 4 项异步启动/关闭/迟到/卸载
  检查（总计 8 项）。

### 10.1.5 首次失败与修复

1. ZIP 含 ADS 成员时，路径组件校验复用了元数据错误码，首次得到 `UPDATE_METADATA_INVALID`；改为在 ZIP 路径
   层统一抛出 `UPDATE_PACKAGE_INVALID`。
2. 取消下载测试首次进度一直为 0：`HTTPResponse.read(n)` 等待完整分片；改用 `read1` 并让 `cancel()` 关闭当前
   连接，真实 TLS 取消测试通过。
3. 私有产品源测试首次仍进入 `checking`：`check()` 未在 `unconfigured` 状态短路；已加入状态守卫，配置错误时
   不联网。
4. 测试文件一次编辑把函数定义与首行合并，pytest 收集报 `IndentationError`；修正测试缩进后继续。
5. UpdatePanel DOM 测试首次未渲染 alert 的默认 slot／title，导致 ready／unconfigured 文案断言失败；修正测试
   stub 后通过，产品模板未因此改变。
6. 总期限测试首次得到 `UPDATE_DOWNLOAD_INVALID`：短读发生在期限之后；已在短读/读取后按实际 deadline 分类
   `UPDATE_DOWNLOAD_TIMEOUT`。
7. 真实 junction 反例首次写出 outside 根：增加原始路径/全部祖先检查后才进入暂存创建；修复后 outside 无
   `KindergartenManager` 写入。
8. App 启动测试首次只看到 `checking`：轮询被 `updateOpen` 条件阻断；改为在途始终轮询，后台 available 打开
   提示，并增加迟到/卸载代次断言。
9. shutdown-during-check 首测在请求到达 TLS 服务前就关闭，`requests==0`；测试改为先等待真实检查请求到达再关闭。
   取消用例按 Codex 指出的合法即时 `cancelled` 时序，改为断言最终只能 cancelled、无文件、无活线程，不接受
   ready/failed。
10. Connection: close 元数据首测得到 `UPDATE_CHECK_FAILED` 而非超时：实际读取 socket 不再是 `conn.sock`，且
    检查异常未按 deadline 分类；已改为持有 `response.fp.raw._sock`、按剩余总期限设超时，并将超时/迟到完整
    响应归为 `UPDATE_DOWNLOAD_TIMEOUT`。真实 close 头元数据/包、分段滴流与取消/关闭交错回归通过。

### 10.1.6 源码身份（sha256 前 16 位）

- `desktop/update_identity.py` `c9cbf9276e262c6d…`
- `desktop/update_trust.py` `2993f212ce9c3c27…`
- `desktop/update_manifest.py` `bf7ad8f59df914d6…`
- `desktop/update_service.py` `cb0d6de9bfc947e1…`
- `desktop/update_paths.py` `c0ad8243b10c2936…`
- `desktop/update_fs.py` `1bab7b18e68adc8d…`
- `desktop/d1_host_api.py` `8f8e767198fd2766…`
- `desktop/d1_main.py` `e40a6112e37e094a…`
- `backend/app/local/runtime.py` `8206c265c7458066…`
- `frontend/src/d1/update.ts` `29bcb95af0ede8d0…`
- `frontend/src/d1/views/UpdatePanel.vue` `dbcf039ecd6d8b43…`
- `frontend/src/d1/App.vue` `aefd9209dfece994…`
- `frontend/src/d1/views/WorkbenchView.vue` `cb1727bde983a010…`
- `frontend/src/d1/bridge.ts` `3980883f2b4af90d…`
- `frontend/package.json` `66edb7df7efd48d0…`
- `frontend/src/d1/d1.update.test.mjs` `be9388f9848e8aa2…`
- `desktop/tests/test_update_u1.py` `c07f1bf04f074540…`

### 10.1.7 U1 未验边界

- 未获 Codex 独立审核；未运行真实源码窗口或冻结包。
- 真实发行 URL、正式 Ed25519 公钥、发布服务和真实包下载均未配置；在线发行未验。
- U2 安装确认／PID／nonce／ready 回执／目录切换／冷升级未实现；U3 完整链路未验。
- SAC 4551、签名、教师体验、Word／WPS、Win10／DPI 保持未验；合成 TLS 成功不代表可在线发行。

## 11. Codex 已核定事项与 U2 边界

1. 固定发行源／渠道／元数据路径契约已核定；真实 URL、正式公钥和发布流程仍未选定，U1 保持
   `unconfigured`，不部署服务。
2. Ed25519 签名元数据 + 固定 HTTPS + 完整包校验已核定；正式密钥未生成，合成测试只使用临时身份。
3. 小更新器属于现有宿主维护实现细化，不另立 ADR；U2 实施。
4. 当前用户 `LocalAppData/Programs/KindergartenManager/app` 及相邻更新器路径可作为 U2 起点；
   首次安装／快捷方式另行待验。
5. 应用 ID／渠道／`0.1.0`／UUID build id 已核定；DB revision 兼容范围和小更新器 ready 回执协议
   在 U2 实现时核对。
6. 新包／更新器仍受 SAC 4551 影响；真实安装与教师体验不因合成 U1 通过而解除。

## 12. 当前状态

- U1 源码、测试和独立临时前端构建已完成自测；**U1 未获 Codex 审核，未通过，U2／U3 未实施。**
- 未构建、未运行应用或冻结包，未访问真实数据／凭据，未调用真实 AI／WebDAV，未签名、未发布、
  未 commit／push。
- 真实发行 URL／正式公钥／在线下载未配置；合成受控 TLS 只证明工程路径，不证明可在线发行。
- D3-A H1／H2 与 R01–R11 限定工程通过保持；H3／4551／D2 未验边界保持。
- 停在这里等待 Codex 审核 U1；通过后同一 OpenCode 会话接续 U2，不自行扩大范围。

## 13. Codex归并：U1最终核查及接续状态

以上§10–12是原轮次自测和当时状态，不能覆盖后来反例。U1第六轮新增两项测试曾将API继续阻塞写成通过预期；30项自测因此不能证明主动中断，Codex已交回。第七轮先纠正断言实际复现2 failed／2.80秒（`u1-r06-corrected-first-red.log`），再修复真实socket关闭路径，定点2 passed／0.82秒、完整30 passed／9.89秒、exit0，无skip，日志`u1-r06-fix2-barrier.log`和`u1-r06-full-pytest.log`，均保留在开工证据根。

2026-10-24 Codex最终独立30 passed／9.76秒、实际TLS正文阻塞中shutdown／cancel与正常下载均通过，17份源码前后hash一致；完整导出累计400条新增assistant全部为指定Go Flash default。完整范围、历轮失败及未验项见[核查§12](desktop-update-review.md#12-u1最终限定工程结论通过接续u2)。U1仅限定工程通过，按用户授权接续U2；U2／U3尚未实现，不等于更新整体验收。正式发行渠道、公钥、新冻结包、真实安装及4551保持未验；不删除首次失败根。

## 14. 2026-10-25 Codex归并：U2首轮交付未通过

§10–13按当时状态保留，最新状态以本节和[独立核查§14](desktop-update-review.md#14-2026-10-25-u2首轮正式交付独立核查不通过)为准：U1限定工程通过，U2已有正式交付但独立核查不通过，U3未启动。

原OpenCode会话idle／succeeded，实际模型保持Go Flash default，最终明确停止写入。实现者自报U2 15项、U1／关闭／保存88项、前端13项更新SFC／60项组件及typecheck通过；不能覆盖Codex反例。24份源码与上轮正式快照零变化；本日独立U2为14 passed／1 failed（空ready JSON时序）、26.02秒、exit1，三个定点反例再次复现。撤销后仍安装、普通helper命令执行、阶段并发丢失证据保持有效；具体U2-R01–R07和首次失败根已归入独立记录。

按用户本日授权交回同一OpenCode修复，不进入U3；报告由Codex依据真实日志归并，OpenCode仅写实现／测试／必要构建支持。真实数据、凭据、旧包和首次失败材料保持；未调用真实AI／WebDAV、未构建运行冻结包、未签名或发布。

## 15. U2第二轮归并

原会话exit0、停止写入；本轮83条新增assistant均为指定Go Flash default，finish=stop。实现者最终24项U2／88项U1与关闭保存／13项更新SFC／60项组件及typecheck通过。Codex独立U2为24 passed／32.70秒、13项SFC及typecheck通过，24文件前后hash零变化。R01／R02／R03／R04／R07及R05单对象busy、R06并发追加在限定源码／合成范围通过；R05重启后遗忘持久化unknown、R06坏阶段在main异常出口被清空并降为failed仍失败。真实命令、探针分层与根见[独立核查§15](desktop-update-review.md#15-u2第二轮独立复核原主要反例已修r05r06剩余分支不通过)。仅这两点交回同一会话，不提前U3，正式发行与冻结包等未验边界保持。

## 16. U2第三轮归并

原会话exit0／停止写入，以本轮user消息为边界复核36条新增assistant均为指定Go Flash default，finish=stop；独立29 passed／27.19秒、无skip、24份源码前后零变化。R06损坏阶段main异常出口已unknown并保留材料，在限定合成范围关闭；R05重启unknown阻断已修，但真实成功后同Coordinator仍缓存HELPER_ALIVE、错nonce且无有效receipt的success被接受，独立两反例exit1。证据与首次根见[独立核查§16](desktop-update-review.md#16-u2第三轮独立复核r06关闭r05刷新及终态绑定仍未通过)。仅R05这两点继续同会话修复，U3尚未启动。

## 17. U2最终归并与接续U3

第四轮exit0、停止写入，以本轮user消息为边界复核13条新增assistant均为指定Go Flash default，finish=stop。实现者30项U2／88项相关回归通过；Codex独立30 passed／30.11秒，无skip，实际helper成功后同实例刷新及错nonce／缺receipt拒绝探针exit0，24份源码验证前后零变化。详见[独立核查§17](desktop-update-review.md#17-u2最终限定工程结论通过接续u3)。U2-R01–R07限定工程关闭，按用户授权同一会话接续U3；真实冻结包、发行源、4551及教师发行体验仍未验，不自动构建或发布。

## 18. U3首轮交付归并

原会话exit0、停止写入，113条新增assistant均为指定Go Flash default，finish=stop；实现者最终完整链32项及相关Python118项自测通过。Codex独立实际源码窗口链32项全部true、exit0，新根`%TEMP%/kgmu-u3-chain-f04973ec/`，26份源码前后零变化。真实build_runtime对普通／模拟冻结U3参数拒绝探针通过，先前只测内部校验函数的输出不能证明完整入口缺失，已更正。

当前U3仍未整体通过：ready验证环境上下文未限定、缺实际关闭取消／保存失败集成、持续AI计数／旧归因及计划字段／新进程凭据可用性证据不足，U3-R01–R03见[独立核查§19](desktop-update-review.md#19-u3首轮独立复核正向源码链通过整体尚未通过)，同一会话修复。正向测试使用合成形状目录包＋当前仓库源码和独立前端；不证明冻结载荷执行、真实安装／4551或教师逐页Word验收。首次及后续所有失败根保持，不构建冻结包、不调用真实AI、不发布。

## 19. U3最终归并：限定源码／合成工程通过

原OpenCode U3第二轮修复exit0／停止写入，46条新增assistant全部为指定Go Flash default、finish=stop。实现者42项完整链及120项相关Python回归通过。Codex独立完整源码窗口42／42、Python120 passed／46.14秒、更新SFC13项、typecheck全部exit0／无skip；27份源码前后零变化，453份非凭据保护文件hash保持。新根`%TEMP%/kgmu-u3-chain-d2774482/`与`%TEMP%/kgmu-u3ind-867655de/`，命令、结果和全部范围见[最终独立核查§20](desktop-update-review.md#20-最终独立核查u1u3限定源码合成工程通过)。

实际保存失败留页后可再次通过UI安装，撤销plan与最终success plan分别绑定nonce；真实helper及新源码窗口page_ready／PID核对通过。旧内容／归因／操作、计划固定字段、AI表保持，仅精确保存新版本；受控provider从seed到新版退出总计1次，新增0；新版退出后独立真实Runtime的合成凭据get_config.ready通过实际AES-GCM／AAD解密。Word200／14286字节，当前保存反思及历史来源通过。7张U3截图及5张H2 seed截图保留，Codex已查看失败留页与新版就绪截图。

U3-R01–R03关闭；U1／U2关闭项保持。source形状包＋仓库源码不冒称冻结载荷运行；发行源／正式公钥、真实安装／首次安装／快捷方式、4551、教师逐页Word、活动AI退出UI等未验边界保持。所有失败根保留，不自动构建冻结包、不调用真实AI／WebDAV、不签名发布。按授权由Codex继续Git管理并准备下一步待审提示词。
