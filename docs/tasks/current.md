# AI手动重试与GitHub更新：工程通过，继续源码体验

更新：2026-10-30。用户接受AI生成可能不稳定，要求失败／结果不明时提供主动重试；更新采用检查本项目GitHub有无最新正式版本。产品决定已归入[观察记录§5.1](../specs/desktop-game-observation.md#51-生成与单栏重写)、[日计划C15](../specs/desktop-ai-daily-plan.md#1-已经确认不再重复询问)及[更新§10](../specs/desktop-application-update.md#10-2026-10-30采用github-releases检查新版)，实际结果见[独立核查§4](../bootstrap/desktop-retry-github-review.md#4-最终独立结论与源码交付)。

## 本轮已完成的范围

- 原OpenCode会话`ses_ead8af71dffeJphI1NOWg4jZgI`、build、`opencode-go/deepseek-v4.1-flash#max`为唯一实现者，r01–r04均自然退出，Codex独立回读／反例／回归后RG-R01–R10关闭。Codex未写实现、测试、迁移或构建脚本。
- 观察记录生成／单栏重写失败后有明确重试入口，保留正文／照片／历史／失败执行；结果不明须确认可能重复处理／计费，不自动重发。操作回执未知保留同请求幂等重交，暂停与结果不明分别提示。日计划既有重试保持。
- 固定GitHub公开仓库`ywyz/kindergarten-manager-next`，latest正式Release按数字SemVer判断，不以main提交或普通tag当新版。保留用户主动下载／确认安装、签名元数据／完整包／平台／schema／build校验；产品文件不能启用测试网络覆盖。
- 独立全local761、最终桌面368、完整前端与最终观察62／typecheck、新源码构建／真实WebView2 report17及反例复验通过；source/test/resource403路径在最终桌面测试前后保持。受控TLS、合成完整ZIP与真实独立helper进程已验，不冒充真实冻结发行安装。

## 当前交付与接续

1. 27个已核对文件的Git收口由原OpenCode按批准blob清单普通提交推送；实际身份保存在Git和最终回执，不为回填自身SHA制造额外提交。禁止amend／强推、Release、默认分支／可见性变更或夹带私有证据。
2. 当前无本轮剩余编码事项。继续按[README源码方式](../../README.md#从源码运行)体验；`build/source-preview/frontend`已更新，原3文件私下保留。保留原数据根；测试使用独立合成数据／凭据目录，不自动复制旧密钥或搬迁业务库。
3. 实际产品代码读取GitHub返回`no_release`，目前尚无正式版本；源码允许只读检查，不下载／安装或替换仓库程序。正式发行公钥、签名清单／完整程序资产及真实冻结更新另行落实，不将检查可用写成整项在线发行已验。
4. 若体验发现具体问题，继续同一OpenCode会话／指定模型修复，Codex独立审核；不另起／fork实现会话或子代理。AI偶发失败本身按可恢复结果验证，不抹去原unknown，不承诺每次重试成功，不把已证应用缺陷归因于供应商波动。

## 保持的边界

同一分支`codex/desktop-v2-foundation`。OpenCode唯一写实现／测试／迁移／构建脚本，Codex负责规划／审阅／验证与Git协调。当前不执行受阻冻结EXE、不签名／发行，不改Windows保护、不启动WebDAV／跨设备、不安装升级依赖／Skill／MCP、不改ARCHITECTURE.md。本轮应用真实AI调用0次；原E14授权及历史真实请求保持各自范围，不自动追加本轮调用。

原业务库、配置／凭据、OneDrive原件、模板原件、旧包及私有审计保持；5个原源和旧E14 EXE／ZIP hash保持。MIT准备见[开源核查](../bootstrap/open-source-readiness-review.md)，公开历史个人信息问题仍开放，默认main仍旧版；不自动重写历史／强推。首次失败日志、独立安装失败现场及各轮源码快照私下保留。

原E14源码／静态结果及r03候选见[E14核查](../bootstrap/desktop-game-observation-e14-review.md)，不替代最新源码对应冻结入口／图片解码／空旧库／AI／Word／原生保存／关闭与更新验证。SAC4551、D3长根WinError206、首次安装／快捷方式、真实发行身份与资产、MiMo／复杂照片／教师质量、Win10／WPS／干净机器／其他DPI及D2／D3既有未验继续分列。尚未整体产品／教师体验验收，不发行。
