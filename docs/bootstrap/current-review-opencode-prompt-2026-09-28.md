# 给 OpenCode：当前 HEAD 定向收敛

以下正文可直接交给 OpenCode。范围只包括 I5 片 1 内部结构、当前 HEAD 的 I1 集成回归兼容性及直接相关文档卫生；不授权 I5 片 2、docx、路由、前端功能、schema/迁移、产品行为变更、提交、推送或部署。

---

请在仓库 `/home/ywyz/code/kindergarten-manager-next` 完成一次定向收敛。

开始先读取并遵守 `AGENTS.md`，核对实际 HEAD、Git 状态和本报告：

- `docs/bootstrap/current-review-2026-09-28.md`
- `docs/specs/word-export-implementation.md`
- `backend/app/services/export_read_service.py`
- `backend/tests/unit/test_i5_export_read_service.py`
- `backend/tests/integration/test_identity.py`
- `backend/app/services/auth_service.py`
- `backend/app/models.py`

基线审阅时 HEAD 为 `b7ade4f`。保留用户已有 `.codex/config.toml` 修改和未跟踪 `.codegraph/`；不要启用/安装 Skill 或 MCP，不要删除本地索引。若 HEAD 已变化，只核对受影响范围，不重做全仓审计。

## 任务 1：贯通日计划缺项的完整稳定定位 facts

当前 `collect_daily_missing_facts()` 会生成含 `section/group_kind/group_index/group_id/game_index/game_id` 的事实，但 `prepare_daily_export()` 只把 `field` 字符串放入 bundle，违反 I5 §4.1。

- 让 `DailyExportBundle.missing` 保留并下发每个完整事实对象；按日计划/日期分组仍可保留。
- expected context 的 `missing_fingerprint` 必须基于实际返回给调用方的完整 missing 对象，不能对一个对象展示、对另一个简化对象签名。
- 保持 §11.8 方案 B：版本、对象或 facts 变化时旧 ack 失效；对象未变才继续。
- API 尚未实现，不新增路由/schema/迁移。可直接收敛内部结构，无需维持尚未发布的错误结构兼容层。
- 增加贯通测试：同类多组、同组多游戏的 `group_id/game_id/index` 不丢；任一完整 fact 变化都会改变指纹并触发 `context_changed`；空缺项及正常 ack 语义不回归。

## 任务 2：恢复 I1 集成回归在当前迁移 head 的可执行性

真实 MySQL 复现结果：I1 24 项中 3 个错误、1 个失败。错误来自 `_fail_with_real_mysql_error()` 不接受当前 `record_operation()` 的通用目标参数；失败来自对 I1 时代物理列集合的精确等值断言。

- 更新故障注入 helper，使其接受并原样转发当前调用实际传入的目标参数，再执行真实 `record_operation`、`flush`、不存在表 INSERT，保留“真实 MySQL 报错后整事务回滚”的证据强度。
- 更新持久化脱敏测试以适配当前 `operation_records` schema：继续读取并扫描所有实际列；断言当前必须列存在、账号目标的 legacy/generic 列一致；继续证明不存原始密码、原始 session token 或账号 password hash。不要通过缩小查询列或删除断言来让测试变绿。
- 将 I1 URL guard 收紧到 `mysql+pymysql`、`127.0.0.1/localhost`、端口 `13384`、数据库 `kindergarten_test_i1`；保持 destructive switch。
- 不改业务实现、模型或迁移，除非测试证明存在独立业务缺陷；若发现，停止扩大范围并报告。

## 任务 3：最小修正文档和仓库卫生

- `docs/specs/word-export-implementation.md` 与 `docs/bootstrap/architecture-v1-readiness.md` 引用了不存在且 Git 历史中也没有的 `i5-slice1-review-2026-09-25.md`。不要伪造历史原文；改为引用 `current-review-2026-09-28.md`，并把措辞调整为“根据提交说明与当前代码复核”之类的可验证事实。
- 最小更新 `README.md` 的当前状态和下一步：准确反映 I1-I4 已实现、I5 片 1 已实现，片 2-4 未开始；保留历史验证段，但明确标成历史。不要改 `ARCHITECTURE.md` 或 Contract。
- 核实 `.codegraph/` 只含本地生成索引后，把 `.codegraph/` 加入 `.gitignore`；不要删除目录、不要提交其内容、不要改 `.codex/config.toml`。
- 不处理前端 bundle 体积警告，本轮仅在结束报告列为后续性能项。

## 验证

先运行无需数据库的检查：

```bash
cd backend
APP_DISABLE_DOTENV=1 .venv/bin/python -m unittest discover -s tests/unit -q

cd ../frontend
npm run typecheck
npm run build
```

然后只使用既有回环地址、白名单测试库和 destructive guard，运行当前迁移 head 上的 I1-I4 集成套件。不得使用生产/共享库，不输出数据库凭据。最低结果：I1 24 项全绿；I2 56、I3 27、I4 52 项继续全绿。若本机隔离容器不可用，报告阻塞，不自行创建新服务器资源或改端口。

最后运行：

```bash
git diff --check
git status --short
```

结束报告必须包含：实际基线、修改文件、F1 facts 结构及 ack 指纹如何修正、I1 四个失败如何修复、文档断链/README 如何处理、各组测试精确结果、仍保留的未决项和前端 bundle 警告。提供 diff 供审阅，**不要 commit、push、部署，也不要自动进入 I5 片 2**。

---
