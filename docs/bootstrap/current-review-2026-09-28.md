# 本机环境与当前代码复核（2026-09-28）

## 结论

本机已满足当前仓库的本地开发与 I1-I4 验证需求：Python、uv、Node、npm、Docker、MySQL 8.4 隔离容器、后端虚拟环境和前端锁定依赖均可用。无需安装系统级 MySQL 客户端；项目通过 PyMySQL 连接数据库，容器内已有 MySQL 客户端可用于管理。

当前 HEAD 为 `b7ade4f`。I5 片 1 的主逻辑和 419 项后端单测通过，但仍有一处规格—实现偏差、一个集成测试兼容性问题及两项仓库文档/卫生问题。建议先做一次小范围收敛，再决定和授权 I5 片 2；本报告不授权片 2、提交、推送或部署。

`codebase-memory` MCP 在项目级 `.codex/config.toml` 中被显式禁用，且该文件已有用户未提交修改，因此本次没有擅自启用或重写配置。结构审阅改用源码、测试、Git 历史及现有 `.codegraph` 痕迹定向核验；不能声称已完成图谱覆盖率验证。

## 实际环境与验证

- Linux / x86_64；Python 3.14.7；uv 0.12.19。
- Node 26.8.2；npm 11.19.1，满足 `frontend/package.json` 的 engines。
- Docker 29.8.1；两个 MySQL 8.4.11 / InnoDB 容器分别监听回环地址 13384、13385。
- `UV_PYTHON_DOWNLOADS=never uv sync --locked`：通过，25 个后端包已校验。
- `npm ci --registry=https://registry.npmjs.org`：通过，69 个包审计为 0 个已知漏洞。
- 后端单测：`419 tests`，全部通过。
- 前端 `npm run typecheck`、`npm run build`：通过；主 JS 约 1.12 MB，Vite 给出大于 500 KB 的非阻断警告。
- API 以禁用 dotenv、空数据库地址启动，`GET /health` 返回 200 与 `{"status":"ok"}`，随后已停止。
- 真实 MySQL：I2 56 项、I3 27 项、I4 52 项集成测试全部通过。
- I1 集成测试在当前迁移 head 上运行 24 项，其中 20 项通过、3 项错误、1 项失败；原因见 F2。
- `git diff --check`：通过。原有工作区状态得到保留：`.codex/config.toml` 已修改，`.codegraph/` 未跟踪。

本次把 VS Code 用户设置 `http.proxyStrictSSL` 从 `false` 改为 `true`。在保持现有代理且显式恢复 Node TLS 校验后，npm registry 查询成功；当前已运行的 IDE/扩展进程仍需 Reload Window 或重启后才会丢弃继承的 `NODE_TLS_REJECT_UNAUTHORIZED=0`。

## Findings

### F1（P1）日计划 409 缺项对象丢失规格要求的稳定定位信息

`collect_daily_missing_facts()` 已生成包含 `section/group_kind/group_index/group_id/game_index/game_id` 的事实，但 `prepare_daily_export()` 组装 `DailyExportBundle.missing` 时只保留 `fact["field"]` 字符串。结果与 I5 §4.1“每个事实携带稳定定位标识”不一致，未来 API 也无法把完整事实返回给前端。

位置：`backend/app/services/export_read_service.py:500-509`；对应规格：`docs/specs/word-export-implementation.md:201`。现有测试只断言简化后的 `fields`，没有覆盖完整 facts 从采集层到 bundle 的贯通。

修复应保留服务端生成的完整事实对象，并让 expected context 的 missing 指纹基于实际下发对象。由于 API 尚未实现，可在片 1 内收敛内部结构；不要新增 schema、迁移或路由。

### F2（P1）I1 真实 MySQL 回归测试与当前审计接口/schema 漂移

`tests/integration/test_identity.py` 的故障注入 helper 仍只接受旧的 `target_account_id/account_version_after` 参数，而当前 `record_operation()` 调用使用 `target_type/target_id/target_version_after`，导致三个事务回滚用例在进入真实 MySQL 故障点前即 `TypeError`。同文件还精确断言 I1 时代 `operation_records` 的列集合，当前 I2+ 通用目标列存在时必然失败。

这不是 I1 历史验证记录失真；历史记录明确基于 `20260921_i1_identity_reg`。问题是当前 HEAD 的回归入口不能在当前迁移 head 上重跑。应让测试兼容当前签名与当前 schema，并继续验证所有实际列不含原始密码/token，而不是删除安全断言。

此外 I1 guard 只限制 host 和数据库名，没有像 I2-I4 guard 一样限制专用端口。当前环境历史约定为 13384，建议同步收紧，避免误连本机其他 MySQL 实例。

### F3（P2）文档引用了仓库中不存在的 I5 片 1 审核报告

`docs/specs/word-export-implementation.md` 与 `docs/bootstrap/architecture-v1-readiness.md` 均引用 `docs/bootstrap/i5-slice1-review-2026-09-25.md`，但该文件不在 HEAD，Git 历史中也没有对应路径。`b7ade4f` 的提交说明包含 R1-R3 摘要，但不能替代一个可点击的仓库文档。

不要伪造 2026-09-25 的原始报告。可将现状引用改到本报告并明确“依据提交说明与当前代码复核”，或补一份明确标注为“事后重建摘要”的文档。

### F4（P2）README 的当前状态已明显过期

README 开头仍称业务功能和数据库尚未实现，后文“下一步”仍停在 I1 前，且多处“当前”说明其实是 2026-09-21 骨架历史。实际仓库已完成 I1-I4 和 I5 片 1。应做最小状态校正，并把历史启动记录清楚标成历史；不要重写架构或扩大产品范围。

### F5（P3）本地生成目录未忽略，前端存在体积警告

`.codegraph/` 当前未跟踪且不应作为产品源码提交；在确认它只是本地索引后应加入 `.gitignore`，不要删除用户本地索引。前端主包体积警告可在未来前端性能切片通过路由懒加载处理，不应夹带进本轮 I5 收敛。

## 建议顺序

1. 修复 F1 和相应单测，重跑 419 项后端单测。
2. 修复 F2，使用当前迁移 head 重跑 I1 24 项，并复跑 I2-I4 真实 MySQL套件。
3. 修复 F3/F4，并只在确认 `.codegraph/` 为本地生成物后处理 F5 的 ignore。
4. `git diff --check`，报告工作区原有修改与新增修改，不提交、不推送。
5. 上述收敛通过后，再向用户提交 I5 §11.1-§11.6 中片 2 真正依赖的最小决策，并请求片 2 授权；不要自动开始 docx 生成。

配套可执行提示词见 [给 OpenCode 的提示词](current-review-opencode-prompt-2026-09-28.md)。
