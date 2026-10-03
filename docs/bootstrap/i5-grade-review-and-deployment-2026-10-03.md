# I5 年级修复只读审阅与验收实例更新（2026-10-03）

用户本轮授权只读审阅 OpenCode 修复，无阻塞问题后更新既有验收实例并记录实际源／模板哈希，检查桌面 Codex 提示词。协调者未修改业务代码、测试或模板，未 commit／push。原工作区修改及未跟踪交接文件保留。

## 审阅结论

未发现阻塞部署的代码问题。三个代码／测试文件的差异符合窄修复边界：`grade_display()` 在映射层共享转换 small／middle／large 为小班／中班／大班，日／周只读各自创建时快照；中文／未知文本原样保留，空值不补填。不改保存值、API、确认版本、标红算法、模板或分页生成器。

复核新增13项测试及现有生成测试，覆盖真实枚举到最终OOXML、日／周混合年级合并、输入未修改、中文／空值兼容、模板与其他ZIP成员保真。本机重新执行全部纯单元测试：546项通过，7.903秒，退出码0；远程候选release重新执行映射／生成定向测试：61项通过，8.557秒，退出码0。OpenCode修复前日志仍为13项中7失败，是其执行证据，本轮未重新执行修复前版本。

交接配方需要澄清，属于验收输入准备问题，不阻塞代码部署：W2必须从现场不可变基准构造纯移动／纯空白输入，不能沿用已有改写的活动过程而预期全文原色；W6可区分来源应在确认A之前准备，来源改写后同身份PATCH不会刷新旧版本，需要现有refresh-sources流程；不保证重新确认后其他投影字段全等。已在[桌面接续提示词](i5-desktop-followup-codex-prompt-2026-10-03.md)补充权威执行说明，OpenCode结果报告保留历史身份。

## 实际部署源

部署完成时间：2026-10-03 10:26:46（Asia/Shanghai，UTC+8）。SSH目标 `root@bwh.ywyz.tech`；入口 https://kg-next-verify.ywyz.tech。

- 新release：`i5-grade-20261003-e6c15eaa0350`；`current`已指向 `/opt/kindergarten-manager-next-i5/releases/i5-grade-20261003-e6c15eaa0350`。
- 源为Git基线 `2c44ac2b01af14d02f94c0f2cbcbcc9af49ab089` 的归档，覆盖OpenCode三份**未提交**修复文件。HEAD本身不含修复，不能将其单独当作运行版本。未把用户其他未提交文档混入源归档。
- 源归档SHA-256：`efe5b92aed81f6e9a9bb0ae8a49cf26fdffff67955ef20faaeb1142fb0d83825`。完整145份backend／frontend源文件、三份覆盖文件及模板SHA-256见[机器可读部署清单](i5-grade-deployment-source-2026-10-03.json)。服务器候选目录逐文件验证通过。
- 映射文件SHA-256：`e6c15eaa03505b70cb7278f3fb1994b8712a45c96e4c93bb7bb551b993f72625`。
- 前端源没有变化，静态dist复制自原 `2cb8d81556f47936e236dadedcb37bf3cec5b3c8` release；既有前端typecheck/build证据保留，未重新构建。Python环境通过新backend/.venv符号链接复用旧release环境，旧release需保留。锁文件与项目依赖声明仅CRLF／LF不同，规范化后内容相同，不重装依赖。
- 旧release保留，可通过原子恢复current并重启准确的 `kg-next-i5-api`回退。没有改Caddy、数据库配置、schema、迁移、账号或验收夹具。

模板在本机和新远程release实测一致：

| 模板 | SHA-256 |
| --- | --- |
| 日 | `99008f92ae42cc87da7e42e84009ffcd8bbefdf43602f09a59ae4027e5ddc9bd` |
| 周 | `24ccaa9e557522c40a653643381e31f319ea6ae5e9f3e30e9dfa41da21986aed` |

## 部署与数据验证

`kg-next-i5-api.service`重启后active，实测MainPID 275351。服务账号可读新映射文件并可执行uvicorn；从新backend工作目录载入映射，三个枚举输出小班／中班／大班。内部 `/health`、远程公网 `/health`、本机公网 `/health`及公网首页成功；重启初期内部探测有3次连接未就绪，重试后正常。首次预检因旧源CRLF差异停止，未切换current；核实仅换行符后继续，无依赖变更。

部署前后对以下六表所有行作排序规范化SHA-256比较，完全一致：daily_plans、daily_plan_contents、weekly_plans、weekly_plan_contents、weekly_plan_confirmed_contents、weekly_plan_sync_states。行数分别32／35／10／22／11／7，实际export_word审计72条前后相同。这里72是本轮数据库实测，不是由历史下载数量推算；尚未逐事件核对历史审计与证据清单。读表不回写、不运行集成／seed／迁移。完整脱敏哈希见部署清单。

服务器证据目录：`/opt/kindergarten-manager-next-i5/evidence/i5-grade-20261003-e6c15eaa0350/`，含源归档哈希、定向测试日志、前后DB摘要、模板／dist哈希、内部／公网health、首页及部署UTC时间；新release含DEPLOYMENT-SOURCE.json，incoming保留精确源归档及部署脚本。

## 桌面交接与状态

请使用更新后的[定向补验提示词](i5-desktop-followup-codex-prompt-2026-10-03.md)，原完整提示词继续提供工具、账号和历史案例背景。本轮已同步Windows私密交接目录的接续提示词和参考文档，旧文件／manifest不覆盖；夹具清单仍是先前采集快照，实时版本必须重读。

| 层 | 本轮状态 |
| --- | --- |
| 只读审阅 | 无代码阻塞问题；配方澄清已写入交接 |
| 自动测试 | 本机546项、远程61项通过 |
| 远程实例更新／health | 完成／通过 |
| 新版真实浏览器下载 | 未执行，桌面Codex接续 |
| 新版Word／WPS逐页 | 未执行，桌面Codex接续 |
| W6非空材料产品链路 | 继续受阻，未改变验收口径 |

I5／片4尚未完成。新版需定向复验年级、W2、可执行W6与证据补录；历史14份／103页保留历史版本身份。非空材料没有合法I4输入路径，需用户确认口径或后续材料能力切片，不能用自动测试代替产品下载证据。
