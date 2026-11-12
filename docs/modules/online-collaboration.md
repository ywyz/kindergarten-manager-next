# 在线协作 Contract

本模块记录同班在线协作的当前实现边界。产品决定见 [ADR 0005](../adr/0005-optional-online-class-collaboration.md)，实施与联调证据见 [在线协作合成联调](../bootstrap/online-collaboration-integration-review.md)。本文件是模块合同，不是历史执行提示词。

## 职责与数据归属

- 桌面个人业务仍以本地 SQLite 和受管业务文件为权威；在线服务只保存同班共享的身份、班级关系、班级游戏配置、共享周计划及提示词发布记录。
- 幼儿档案、照片、个人记录、个人 AI 指导、日计划正文和 Word 文件留在本地。共享周计划只投影晨谈、集体活动及游戏槽位所需的名称和日期；本地 Word 由桌面按已确认共享快照组装。
- 教师明确选择在线模式后才连接协作服务；离线或断网不自动把同一份在线周计划改写为本地继续编辑。换机和模式切换分别操作。
- 服务端数据库在私有网络内由服务端连接，桌面不持有数据库账号。当前联调环境使用 MySQL 8.4；早期 PostgreSQL 首段仅为历史提议。

## 身份、加入与选班

- `POST /api/collaboration/redeem` 兑换管理员签发的 `join` 或 `recovery` 一次性码。兑换只绑定教师与园所身份，不自动选班；恢复码直接读取仍然有效的原班。
- 教师身份来自已认证会话。`GET /api/collaboration/me`、`GET /api/collaboration/classes`、`GET /api/collaboration/me/class`、`PUT /api/collaboration/me/class` 和 `DELETE /api/collaboration/me/class` 用于读取身份、列出班级、读取当前成员关系、自主选班和退出当前班。
- 同园同班按稳定班级 ID 自动配对；`GET /api/collaboration/classmates` 只返回同一班级的可见搭班信息。不得通过同名班级跨班取配置。
- 两类码、教师 token 和管理员会话只在受控 HTTPS 请求和进程会话内使用；页面不保存真实凭据。

## 班级游戏配置

- `GET /api/collaboration/game-config` **只读取本人已保存配置**，不返回搭班教师配置正文；搭班配置版本通过 `GET /api/collaboration/classmates` 读取。`PUT /api/collaboration/game-config` 保存本人配置。
- `POST /api/collaboration/game-config/preview` 预览另一教师配置的带入差异；教师明确确认后 `POST /api/collaboration/game-config/confirm` 才写入本人保存版本。来源版本变化时重新预览，取消不改变本人配置。原操作可用 `GET /api/collaboration/game-config/operations/{request_id}` 查询。

## 升班与学期名称

- `GET /api/collaboration/me/class/promotion` 返回当前班级、年级、版本和可选学期项。学期项含 `term_id`、`name`、`start_date`、`end_date`。
- `POST /api/collaboration/me/class/promotion` 提交 `request_id`、`class_id`、`expected_version`、`target_grade`、`effective_term_id`；回执保留稳定班级 ID、班名、年级、版本和生效学期。
- `GET /api/collaboration/me/class/promotion/operations/{request_id}` 按原请求读取升班回执。失效基准返回 409，未知提交只按原请求查询。桌面沿用未决和关闭保护。按上海日期到达生效学期后使用升班后的班名，班级 ID 保持稳定。
- 管理员通过 `GET /api/collaboration/admin/schools/{school_id}/terms` 读取学期，通过 `PATCH /api/collaboration/admin/schools/{school_id}/terms/{term_id}` 提交 `expected_name` 和 `new_name` 更新园所学期名称。更新要求 CSRF 管理员会话；陈旧 `expected_name` 返回 409，学期 ID 和日期保持不变。
- 已连接在线班级的教师可在设置页点击“读取园所学期名称”。起止日期唯一匹配时可预填本机表单，已有自定义名称保留。教师可编辑名称，再按本机预览和确认流程保存。
- 游戏观察和本机周计划可从指定历史版本预览并另存为当前本机学期名的确认版本。旧确认保留自己的名称、内容和日期，本机周计划工作草稿保留。一对一倾听沿用记录创建时的学期名称。在线共享周使用园所学期名称，确认时冻结该名称。

## 共享周计划

共享周路径为 `/api/collaboration/classes/{class_id}/weekly/{term_id}/{week_start}`，`week_start` 为 ISO 周一，服务端按园所学期范围和成员关系授权。

- `GET` 返回 `class_id, term_id, week_start, class_name, term_name, version, content, confirmation`。共享内容为 `{days, games}`；日项含 `date`、`morning_talk_topic`、`group_activity_theme`；游戏槽位固定为 `collective_1`、`collective_2`、`free_choice_1`、`focus_area`，各项为空或 `{name,date}`。
- `POST /save` 接受 `request_id`、`expected_version`、`content`，返回同一读取形状加 `request_id, replayed`。保存用显式基准版本和原请求 ID；冲突或断线保留教师输入，读取服务端版本后再明确保存。
- `POST /confirm` 接受 `request_id`、`expected_version`，冻结当时的班名、学期、共享字段和确认版本。返回形状含 `confirmation_id, confirmation_version, version, class_id, term_id, week_start, class_name, grade, term_name, content, confirmed_by, confirmed_at`。
- `GET /confirmations/{confirmation_id}` 重读确认快照；`GET /operations/{request_id}` 读取原操作回执。任一仍有本班权限的教师可确认最新已保存共享版本。
- 桌面通过本地受限代理 `/api/local/collaboration` 的同后缀访问上述服务端路径；不得把本地周计划正文、照片或 Word 文件上传到共享服务。
- 本地 Word 路径为 `GET /api/local/collaboration/classes/{class_id}/weekly/{term_id}/{week_start}/confirmations/{confirmation_id}/word`；可选查询参数 `weekly_plan_id` 与 `local_draft_version` 必须成对传入。服务端只返回确认版共享字段、班名、学期和确认版本；本地主题、栏目和材料只由桌面 Word 组装，不上传本地正文或文件。共享周计划的服务端确认不改变本地 SQLite 中原有周计划、历史版本或教师本地栏目。

## 提示词发布与客户端信任

- 管理端基路径为 `/api/collaboration/admin/prompt-releases`。`GET` 返回 `{editable,drafts,releases,latest}`；`POST /drafts` 接收 `{changes,notes}`；`POST /preview` 接收 `{draft_id}` 生成预览；`POST /stable` 接收 `{preview_sequence}` 将指定预览转为正式；`POST /rollback` 接收 `{target_sequence,expected_stable_sequence}`，使用目标正式版内容签出更高发布序号。写操作要求管理员 CSRF。
- 草稿冻结完整有效内容并记录正式基准；正式发布复用预览的确切指导内容，拒绝落后基准；回滚不重放旧序号。每个发布项的 `release_sequence`、渠道、默认修订和内容身份必须一致。
- 静态签名包路径为 `/prompt-packages/{channel}/v{release_sequence}-{sha256}.json`，清单为同目录 `latest.json`；`preview` 和 `stable` 是唯一渠道。清单签名为 Ed25519，签名域为 `b"kgm-prompt-manifest-v1\n"` 加不含 `signature` 的规范 UTF-8 JSON，签名为标准 base64；字段严格为 `format_version,channel,release_sequence,package_sha256,key_id,signature`，包按原始字节 SHA-256 和签名验证。
- 版本包是不可变文件，缓存策略为 `public, max-age=31536000, immutable`；清单和管理响应为 `no-store`，成功发布后才更新清单。客户端只从固定受信任 HTTPS 来源读取一个渠道，禁止重定向；渠道、序号、key id、包摘要或签名不符均拒绝。
- 本次待发草稿覆盖 7 项任务、19 个字段，已通过线上允许列表校验；模块目录不止该草稿，测试渠道现存预览 v9 和正式 v11，草稿尚未发布。普通签名 `20261114` 构建尚未嵌入提示词包来源及验签公钥，后续自动接收前必须配置发行信任；现有 v9/v11 的签名与包摘要已在真实 HTTPS 上核对。

## 数据、失败与验证边界

- 本地 SQLite 仍保存个人档案、班级/学期设置、日计划、周计划本地栏目、观察、照片、AI 任务、历史和导出记录。在线服务保存同班共享内容、稳定身份、班名/学期快照、管理员记录和提示词发布记录。
- 网络失败、版本冲突、未知回执和关闭中断分别处理；未知写入只按原请求 ID 查询，不自动重复保存、确认、升班或兑换。在线失败不删除本地原文。
- 现有证据为隔离 RDS MySQL 8.4、独立 HTTPS 站点、两个独立 WebView2 档案和合成数据；实际第二台物理设备、安装包跨设备和正式生产数据迁移仍需单独验收。详细首失败、回执和测试数字见 [联调核查](../bootstrap/online-collaboration-integration-review.md)。
