# 当前：新候选关闭／恢复限定增量

更新：2026-11-06。继续 `codex/desktop-v2-foundation`，唯一执行入口。用户本轮拉取、调用原生OpenCode／Command Go、审核／本机测试、必要测试环境及审核后普通提交推送授权已落实到限定修复；结果归[开发机§10](../bootstrap/desktop-regression-repair-review.md#10-2026-11-06测试机回执接收与关闭交错回修)。原实现责任已结束，不重放旧白名单。

## 1. 已接收与已验证

已快进接收用户指定 `96dc1d7a555a1eec8bd33c2139a74f0a706c0e06`（parent6b0a99e，tree6133b1e7d9f1b4ecdd0d62c4cff4cf1cf9a2bedf），测试机原文见[目标§9](../bootstrap/desktop-windows11-white-concurrency-review.md#9-2026-11-056b0a99e接收及3e0e42b候选限定复验)。其101项源码及source3e0e42b／build e12d7af1／run42010782459／artifact13406493851的冻结外部恢复、提示X、退出与完整指纹通过保留原身份，未迁移为本轮补丁的冻结结论。

本轮已修复故障与close协议交接、一次性许可语义、owner／安装撤销失败和并发唤醒、清理失败被误报成功退出，以及验证器首失败／精确新旧窗口所有权／watchdog收尾。Codex独立216项相关测试及8个反例复测通过，最后550份非Markdown源码指纹稳定；实际真实服务／内部对象合同通过，窗口与adapter为替身。首失败、中间回归、原生metadata及边界均归§10。未新增依赖、迁移、教师流程或改后端runtime终结合同。

原A `ses_ead8af71dffeJphI1NOWg4jZgI` 固定build／opencode-go/deepseek-v4.1-flash#max；原C `8cf528de-8773-4a06-9cc5-31e96fab515f` 固定deepseek/deepseek-v4.1-flash／max，只读交叉审阅。Codex负责正式文档、独立审核验证与Git门禁。后续修复须按新证据重新明确互斥文件责任，不fork／子代理、不冒用测试机会话、不接管在途修改；C权限拒绝保留，不放宽或绕过。

## 2. Git与候选身份门

本轮普通提交推送按准确13份变更文件、raw SHA／Git blob、parent96dc1d7、staged tree由Codex核后交原A执行，最终SHA／tree以实际Git回执为准。远端变化就重新核父提交与差异；不用add-all、amend、rebase／force、merge提交，不改main／可见性／tag／Release。不要为了补写本提交SHA循环提交。

仅接收**包含开发机§10修复的实际提交**触发的自动CI候选。先核该commit／tree、run／attempt／artifact与build身份、外内ZIP、EXE、manifest和源字节／包内代码；CI只是Windows2022构建及静态验证，不是Windows11运行。没有同源产物不运行，旧包通过不可代替；不主动dispatch或重跑旧CI。

## 3. 下一步：原测试机最小运行增量

原Windows11测试机在新合法短根、独立合成库／图片／凭据／导出根，使用已核新来源候选：

1. 普通保存／关闭及一次性许可不复用，退出后独立冷开；核服务退出和完整默认／runtime指纹。
2. 各一次renderer／browser受控故障，保留、再次关闭提示、明确重开、恢复后正常关闭和独立冷开，记录各进程真实退出、owned残留及完整指纹。只在可安全精确控制ack／fault时补真实交错；不能控制则明确保留源码反例，不注入／替换包模块或打开debug接口。
3. 私下launcher复用前先审启动后receipt/write/wait异常收尾；这是原目标工具责任，不复用其未知异常清理结论。新失败保留第一现场、身份和指纹，按证据回修再验；能力不足保持未验，不推导新产品功能。

提示X旧目标通过保持旧包身份；Enter／Escape、冻结私有ticket/token/host/executor/engine/session/order和真实vendor回调阻塞边界仍未验，没有可靠观测不强行收口。源码、自动、静态、目标、Word与教师体验分别记录。

## 4. 持续边界

开发机SAC4551不启动受阻新旧EXE／helper，不改名、换路径、去来源标记或降低保护重试。既有输入能力拒绝不绕过。仍用CPython3.14.10 x64标准GIL／锁定依赖，禁dotenv／pyc、SQLAlchemy纯Python、Python loopback守卫；守卫不外推OS／WebView隔离。合成根与源／目标边界先核；真实原库／照片／key／DPAPI、旧包及首失败保留，应用真实AI0，不重发unknown。

旧失败原因、自然白屏、Word/r差异、长根206、Win10／WPS／干净机／其它显示条件保持原未验。不重跑整套backend、旧39项、13份43页Word、微软拼音或W6跨120秒睡眠。不启动签名、安装更新、真AI、WebDAV、Office注册修复、远控或发行。
