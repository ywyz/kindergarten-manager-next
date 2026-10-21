# D2流式思考已工程通过；下一步仅准备G17

2026-10-21用户已确认：应用直接使用DeepSeek官方API与MiMo标准API，不接Token Plan／OpenCode Go；思考默认展开、可折叠，显示真实阶段及已等待时间。开发工具继续沿用OpenCode Go套餐DeepSeek V4.1 Flash。不设计预算限额，不调用应用真实AI或发布。

## 当前基线

- [流式规格](../specs/desktop-ai-streaming-progress.md)已由OpenCode实现，Codex[独立核查§11](../bootstrap/desktop-d2-streaming-review.md#11-最终交付限定合成工程核查通过)通过，R01–R11关闭；[实现者记录](../bootstrap/desktop-d2-streaming-result.md)保留回修、自测和交付时状态。
- 独立证据：完整local511项为R10前基线；末轮35项流式/API、204桌面、前端typecheck／D1逻辑／60组件／D2具名94项及新前端构建通过；真实源码窗口33项、新完整冻结包142项通过。16源码hash稳定，完整归档与真实入口同源；不虚称末轮512全套、真实供应商或产品验收完成。
- 普通入口完整包：`build/desktop-d2-streaming-r10-r11/package/KGNext-D2Verify/`，182文件，EXE SHA-256 `d0e650e8b572a3a7ca8acf7822a47d1c0eeac607322777a7f79d7492d3cfad14`，清单 `80f15a68f0eedfb82713ae9c74936056f2c8a9314e05afe5d1cc6dd391e0873f`；同根RUN.md／package_hashes.json。不能只复制EXE。
- r01独立137/141失败及更早候选／超时证据保留；旧normal-r01、W6／human包、全部人工与诊断现场保持。未将历史失败改写为当时通过。

## 后续允许范围与停止点

1. 依据[G17方案](../bootstrap/desktop-d2-g17-acceptance-plan.md)与[官方文档核对](../bootstrap/desktop-d2-g17-provider-compatibility-review.md)，后续确定两家标准API的准确型号、实际测试顺序与授权范围；尚无实际调用授权，不发连通／模型／余额API、不购买开通充值。密钥只由用户在应用填写，不在聊天／日志／文档传递。
2. 本轮没有token／费用预算设计，不追加预算功能或输出token上限参数。原10秒连接／120秒尝试／1MiB工程保护保持；只对明确未发送的暂时错误有限重试，结果不明不自动重发。每家三类样本是后续验收范围，不是产品配额；具体实际调用另获授权。
3. 当前无剩余流式编码／构建任务，不重复实施R01–R11，不自动开跑G17。后续出现具体新缺陷才交原OpenCode／同一指定配置最小修复，Codex独立核查；OpenCode唯一写实现／测试／迁移／构建脚本，Codex负责设计／审阅／验证与Git管理。
4. 当前分支保持`codex/desktop-v2-foundation`。不自动上传包、发行、安装升级、WebDAV、修改旧远程，或启动D3／观察记录等后置功能。所有验证继续使用独立合成根／LOCALAPPDATA与APP_DISABLE_DOTENV=1，不用默认教师库／原human现场。
5. G13跨120秒睡眠、R02白屏、R03额外任务仍按[W6收口](../bootstrap/desktop-d2-w6-closeout.md)保持观察，不主动追测或改记为已修复。真实供应商时延／兼容／质量／usage、G18教师流程、Word新样本逐页／WPS、Win10、其他DPI／多显示器、干净机器／发行再现性仍未验。

本提示词替代本轮已完成的实施与回修交接；所有独有决定、失败、未验事项已归并到上述规格／实现／独立核查，不另存旧提示词副本。
