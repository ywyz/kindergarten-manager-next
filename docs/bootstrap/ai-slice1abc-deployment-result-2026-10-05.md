# AI 1A＋1B＋1C 实际部署结果（2026-10-05）

结论：**完整 1A＋1B＋1C 已部署，旧测试运行实例已备份归档后清理，远程 HTTPS 与角色冒烟通过。真实浏览器 C1–C7 尚未执行，等待桌面版 Codex。** 用户本轮明确授权 SSH、旧测试清理、目标库迁移、部署与 commit/push；此前各阶段报告中的“未部署／未提交”保持历史身份，不追溯改写。

## 运行身份与清单

| 项目 | 实际值 |
| --- | --- |
| SSH／HTTPS | `root@bwh.ywyz.tech`／https://kg-next-verify.ywyz.tech |
| release／current | `ai1abc-20261005-b08234d51044`／`/opt/kindergarten-manager-next-i5/current` 指向该 releases 子目录 |
| 源基线 | `1647fc934d41b29a844a807d454031e66a2b45af`＋OpenCode 全部未提交 1A／1B／1C 实现及既有运行源＋本轮 frontend/dist |
| 精确运行文件 | 170 份；路径、字节、SHA-256 见[机器清单](ai-slice1abc-deployment-source-2026-10-05.json)；含未跟踪业务文件、两套锁、迁移及 Word 模板 |
| 归档 SHA-256 | `54d6d419acb5f578e78afaba200d3f7d6c59b5f47f6009f05752a05455da387a` |
| 服务／监听 | `kg-next-i5-api.service` active，`kg-next-i5` 低权限系统账号，API 仅 `127.0.0.1:18090`，Caddy active／现有同源代理 |
| 数据库 | 既有 MySQL 8.4.11，`127.0.0.1:13386`，`kg_next_i5_acceptance` |
| migration current | 从 `20260924_i4_weekly_plans` 升到唯一 head `20261003_ai1a_config_prompts` |
| 正常主密钥 | 服务器安全随机生成 32 字节、标准 Base64；key ID `ai1abc-acceptance-20261005`；root-only app.env；不输出材料 |
| 完成后核验时间 | 2026-10-05 12:51:14（Asia/Shanghai，UTC 原始证据 `2026-10-05T04:51:14Z`）；此时退役旧 releases 后重启及第二次五角色冒烟已通过 |

新 backend/.venv 为独立目录副本，不再符号链接旧 release。逐一核对锁的 27 项中的 26 个可安装依赖，版本全匹配；第 27 项为 virtual 项目，无 distribution。未安装／升级依赖，未安装 Skill／MCP，未另起代理。ExecStart 改用 `.venv/bin/python -m uvicorn`，迁移用 `python -m alembic`，避免旧 shebang。没有修改业务代码、模板、架构或 registry。

## 旧测试清理与备份

已停止并移除 `kg-weekly-staging-app-1`、`kg-weekly-staging-db-1`、`kg-staging-registry`；归档专用 `kg-weekly-staging_db_data` 后移除卷。四个历史 `/opt/kindergarten-staging-20260908`、`kindergarten-weekly-20260914`、`kindergarten-weekly-autofill-20260914`、`kindergarten-weekly-complete-20260915` 已归档后移除运行目录。原 `staging-manager.ywyz.tech → 18089` Caddy 段删除，caddy validate 成功并 reload；最终无 18089 监听。

归档在 `/opt/kindergarten-test-archives/20261005/`（0700），含目录／专用 DB 卷 tar.gz、容器原配置、旧 Caddyfile 和哈希。旧 Next releases 同样归档后移除，新服务不依赖它们；I5 evidence、incoming 历史交付、当前 MySQL、账号及合成数据保留。未执行 docker prune、未动其他同机应用／容器。

迁移前停 API，精确库 mysqldump 备份、原 current、服务单元、root-only 配置和账号文件留在本 release evidence/backup。备份具备完成标志、非空和 SHA-256，归档目录可列举；**没有实际恢复演练**。成功后另作 postdeploy-backup，保存当前库与匹配的新主密钥配置，SQL 416752 字节。所有凭证／备份均留私密目录，未进 Git。回退需恢复迁移前整库和原配置／release；新迁移 downgrade 阻断，不能只切 current 冒充完整回退，具体见[方案](ai-slice1abc-deployment-plan-2026-10-05.md)。

## 数据与部署后验证

在同一精确验收库迁移前后，对全部 17 张既有表作排序规范化行 SHA-256 比较，完全相同；读取时 API 已停止，没有清库或 seed 既有业务数据。关键行数：日计划 32／内容 42，周计划 10／草稿 26／确认 13／同步状态 7。迁移新增 7 张 AI 表；七个 v1 契约、七个默认指导，个人 head 和配置 head 均为空。此摘要是迁移完成、HTTP 冒烟前状态；登录／登出会合法改变 sessions，不声称后续所有表永不变化。

- 内部和公网 `/health` 成功；本机另以 `curl --fail --silent --show-error https://kg-next-verify.ywyz.tech/health` 得 `{"status":"ok"}`。
- 公网 index.html 和两份 CSS／JS 字节 SHA-256 与本 release 构建产物相同；内部 OpenAPI 核验本片 12 个 operation。
- 五账号均实际 HTTPS 登录、me、本人 AI 配置、七任务列表和七详情读取、登出成功；Secure／HttpOnly cookie 已核对。管理员默认 GET 200，四教师均 403，待分配本人设置可读。旧 releases 移除后重启再跑一轮，继续通过。
- 读取前后配置／个人 head 仍为 0，GET 未初始化。未为了冒烟给所有账号建立指导或保存供应商配置；实际 UI 保存与持久化交给桌面验收。
- 主密钥进程内 AES-GCM 合成文字加／解密 roundtrip 成功，无密钥／文字／载荷输出；应用数据库账号只有 SELECT／INSERT／UPDATE／DELETE，无 DDL／GRANT OPTION。迁移独立账号用于 DDL。

## 本轮实际命令与结果

| 层／命令 | 结果 |
| --- | --- |
| 本机 backend：清除继承 DSN／AI key，APP_DISABLE_DOTENV=1、PYTHONDONTWRITEBYTECODE=1，`.venv/bin/python -m unittest discover -s tests/unit -t . -q` | 648 tests OK，9.955s，无 skip |
| 同样无连接环境 `python -m alembic heads` | 唯一 `20261003_ai1a_config_prompts` |
| `/home/ywyz/.local/bin/uv lock --check --offline` | 27 lock entries，通过 |
| frontend `npm run typecheck`、`npm run build` | 均退出 0；既有 >500kB chunk 警告保留 |
| `node scripts/ai-settings-1c-check.mjs` | 29/29 |
| `node scripts/ai-settings-1c-state-regression.mjs` | 356/356；实际输出捕获的合成 secret/raw 标记检查通过 |
| 远端候选 backend：相同隔离环境和单元命令 | 648 tests OK，38.556s，无 skip |
| 远端 `deploy.py prepare / cleanup / deploy / retire-releases`（逐阶段） | 精确源校验／旧环境归档清理／备份迁移切换／旧 release 清理，全部完成 |
| 远端 `smoke.py`（切换后与旧 release 清理后） | 两轮全部通过，HTTP／权限／静态文件／主密钥／DML 权限，非浏览器产品验收 |
| 远端 `post-backup.py` | 成功，迁移后库与主密钥配置匹配保存 |
| 仓库 `git diff --check` | 通过；提交前再核对 staged diff |

脚本与归档保留在 `/opt/kindergarten-manager-next-i5/incoming/ai1abc-20261005/`；证据在 `/opt/kindergarten-manager-next-i5/evidence/ai1abc-20261005-b08234d51044/`，含 before/after 摘要、smoke.json、迁移前及成功后备份。脚本按部署授权在进程中读取既有服务器 env／凭证，不打印值；与历史 OpenCode 离线轮次的“未读 env”是不同执行范围。

预检有一次可避免的错误：把 uv.lock 的 virtual 项目当已安装 distribution，出现 PackageNotFoundError；发生于旧环境清理／停 API／迁移前。修正为只核对 26 个 registry 包后通过，未安装依赖。预检中的旧 revision 字符串也按 migration down_revision 修正，真正连接库前已改正确。记录保留，不把失败尝试计为成功。

## 桌面交接／未执行

[完整桌面测试方案](ai-slice1abc-desktop-codex-prompt-2026-10-05.md)已生成。新的 Windows 私密交接目录 `C:\Users\yw980\.codex\tmp\ai1abc-desktop-acceptance-20261005` 含原五账号 credentials 的 accounts.private.json、references 和 logs；旧 I5 私密目录不覆盖。

**真实浏览器 C1–C7 未执行；真实 v2/v3 发布、V1 双草稿契约推进与缺／错主密钥服务夹具未准备，相关子例仍受阻。** 没有改 registry／共享库来冒充真实发布，也没有为普通部署临时改正常主密钥来凑降级验收。1A＋1B 真库 50＋23 项仍引用既有实现者报告，本轮未另跑破坏性集成测试。未执行供应商调用、transport、worker、材料、完整 W6、Office/WPS 逐页、容量或灾备恢复；不启动其他切片。

代码和历史报告一并按本轮授权提交／推送；具体提交身份以 Git 记录为准，运行文件身份始终由机器源清单确认，不因补写报告改变。
