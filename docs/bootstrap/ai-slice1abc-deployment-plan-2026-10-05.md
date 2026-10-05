# AI 1A＋1B＋1C 部署清单与远程验收方案

2026-10-05 用户明确授权：整理完整部署源、连接 `root@bwh.ywyz.tech`、先清理旧测试系统、实际部署、生成桌面 Codex 测试方案、commit／push。业务代码仍由 OpenCode 唯一写入；本轮协调者只写部署配套与文档，不扩业务实现。

## 门槛与部署范围

实现依据：[1A 收口](ai-slice1a-closeout-review-2026-10-04.md)、[1B 收口](ai-slice1b-closeout-review-2026-10-04.md)、[1C 第五轮收口](ai-slice1c-closeout-review-2026-10-05.md)。部署是完整工作区的 backend／frontend，不是只部署 HEAD 或设置组件；包含全部未跟踪实现文件、依赖锁、迁移、受控 Word 模板和本轮构建产物。逐文件 SHA-256 另记机器清单，不包含 .env、私钥、密码、node_modules、.venv 或历史私密材料。

| 切片 | 必需清单 |
| --- | --- |
| 1A | config/main/models/schemas 衔接，ai_config_service、ai_config_url、ai_crypto、ai_locks、ai_prompt_registry、prompt_service；pyproject.toml／uv.lock；20261003_ai1a_config_prompts；1A 单元／真库测试与 guard |
| 1B | routers/ai_settings.py，12 个本人配置／个人指导／管理员默认接口，严格 DTO、权限、Origin、脱敏错误；1B 单元／真库测试 |
| 1C | api.ts／types.ts／SettingsView.vue，三个 AI 卡片和 shared 辅助；29 项检查及 356 项状态回归；完整 frontend/dist |
| 既有链路 | I1–I5 backend／frontend 全部运行源、日周 Word 模板与已实现的手工流程，不导入旧项目数据 |

部署前复跑后端单元、Alembic heads、离线锁核对，前端 typecheck／build／两脚本及 diff check。产品 C1–C7 独立待验收；本轮不执行供应商调用、transport、worker、材料或完整 W6。

## 目标及旧系统清理

继续使用 `https://kg-next-verify.ywyz.tech`、`kg-next-i5-api.service`、`127.0.0.1:18090`、Caddy 现有站点、`/opt/kindergarten-manager-next-i5` 和独立 MySQL 8.4.11。保留内部数据库 `kg_next_i5_acceptance`、低权限 `kg_next_i5_app`、现有五角色账号和 I5 合成数据；不清库重建，历史证据保留。

旧系统限定为 `kg-weekly-staging-app-1`／`kg-weekly-staging-db-1`／`kg-staging-registry`、四个已辨明归属的 kindergarten-staging／weekly 历史目录，以及旧 staging-manager Caddy 路由。先停止旧 app／DB／registry，再归档目录、容器配置与专用 DB 卷，验证归档可读及 SHA-256 后移除旧容器、专用卷及旧运行目录和路由。归档 root-only；不执行全局 docker prune，不动其他应用。新版旧 release 在新环境独立后归档移出运行目录；I5 数据库／凭证／证据仍保留。

## 执行顺序

1. 从本轮构建后的工作区生成运行源＋dist 归档及逐文件哈希，传入独立 incoming；远端校验归档和每个文件。
2. 归档并退役旧 staging。短暂停止新版 API，备份精确验收库、服务单元、app.env、迁移配置及 Caddy；备份权限 0600／目录 0700。记录迁移前 current、旧业务表摘要。
3. 新 release 使用独立 .venv 副本，检查 uv.lock 的 27 项中 26 个可安装依赖版本一致（另 1 项是 virtual 项目自身）；不让新服务引用将退役的旧 release。所有 Python 命令使用该环境的 python -m，避免复制环境中的旧绝对 shebang。
4. 只从 root-only migration.env 读取目标 DSN，在进程内部断言本机 host／13386／精确库名；运行 python -m alembic upgrade head。DDL 使用迁移账号，应用账号继续只有本库 DML。记录目标 current、七个 v1 契约及七个默认 seed、旧业务表摘要不变。
5. 主密钥由服务器安全随机生成 32 字节并 Base64，独立 key ID；只写 root-only app.env，配置、密钥及数据库备份留在服务器私密目录，不进入 Git 或终端输出。检查运行账号、写路径、仅回环监听、HTTPS 同源及 Secure cookie。
6. 原子切换 current；ExecStart 使用 current/backend/.venv/bin/python -m uvicorn；重启精确 API 服务。校验内部／公网 health、首页／静态文件哈希、12 个 OpenAPI 路由、五角色登录和本人只读设置、教师默认权限。检查新环境可独立运行后归档旧 releases。
7. 生成部署结果、源清单、桌面 C1–C7 交接和私密账号交接。git diff --check、排查提交中有无凭证，提交完整本片实现与文档并 push；部署身份以文件哈希为准，文档提交不会改变运行源。

## 回退／恢复

新迁移 downgrade 明确阻断，禁止自动 downgrade。切换／迁移失败先停止 API，保留失败日志于私密 evidence；恢复迁移前整库备份和原 app.env／服务单元，再从归档恢复旧 releases 与 current，重启并核对旧 health。MySQL DDL 不保证事务回滚，不能只回退 current 当作完整恢复。正常成功后不恢复旧 staging。其恢复需独立恢复旧卷及目录、容器配置和对应 Caddy 路由。

本轮备份可读、完整性校验不等于实际恢复演练，正式上线容量与灾备仍另验。

## 桌面交接边界

桌面版使用 Windows native 真实浏览器访问远程站。五账号角色沿用 I5，凭证复制到新的私密交接目录，不写此文。C1–C4、C6 普通冲突及 C7 现有入口可验；C5 真 v2/v3 契约发布、V1 双草稿契约推进场景、缺／错主密钥服务夹具未随普通部署准备，须环境托管者另获具体授权和配方后实施。桌面版不能改 registry／共享库／服务密钥冒充产品通过；可完成其余案例并精确列受阻子例。真实 DOM、输入禁用、双份草稿可见和处置、离开确认仍需浏览器证据，不由 356 项离线回归代替。

实际 release／时间／迁移／检查／清理／偏离以本轮部署结果为准。
