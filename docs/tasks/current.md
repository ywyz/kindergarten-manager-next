# 当前：恢复片Git收口与测试机增量

更新：2026-11-04。继续`codex/desktop-v2-foundation`；本文件是唯一执行入口。用户要求拉取测试结果、实施下一步、审核后提交，并已选择“采用此手动恢复方案”。本轮源码工作已完成，不重派历史实施白名单；真实AI授权未用于本片付费调用，不自动延续至未知历史任务。

## 1. 已完成与必读依据

开发机普通`pull --ff-only`接收61ef9f9，完整接收身份见[生命周期核查](../bootstrap/desktop-renderer-lifecycle-review.md)。原OpenCode A／B以DeepSeek V4.1 Flash max互斥实现，原Command Go同模型max只读审核；无fork／子代理。Codex独占正式文档、独立验证与最终审核。

- [手动恢复规格](../specs/desktop-renderer-recovery.md)：只认当前Core原生确认的renderer／browser异常退出；默认保留，明确选择才重开最后保存的档案。未保存输入可能丢失，不自动重发AI、采用或确认。保存／维护／任务不能安全收束就保留现场。
- [最终源码结果§10–§12](../bootstrap/desktop-renderer-lifecycle-review.md#10-恢复实现审核与首失败)：独立238项通过；实际Page／Browser故障、两个按钮、保留后再次明确重开、正常关闭、旧engine／Session／HTTP token／真实采用预览失效与独立进程完整指纹通过；548个非文档文件前后相同。原通知累积、空闲worker保留、auxiliary先释放根锁以及早期验证器缺口均留首失败。
- [测试机Q5/Q6目标](../bootstrap/desktop-weekly-ai-windows11-target-review.md)、[白屏／并发／Word补核](../bootstrap/desktop-windows11-white-concurrency-review.md)保持各自身份，不由本片替代。原白屏精确触发和Word/r历史差异仍未知。
- [正常保存关闭](../specs/desktop-manual-daily-plan.md)、[完整备份恢复](../specs/desktop-backup-restore.md)、[周AI工程](../specs/desktop-weekly-ai-engineering.md)保持。ARCHITECTURE及ADR未改。

## 2. 本轮Git收口

原A的实现／测试与原B适配片已自然CLI0停写，模型metadata审核通过。仅由原A按Codex当次完整文件清单、Git规范化blob、parent及index tree普通提交当前分支；Codex独立核index与提交结果。不得add-all、amend、rebase、force、改main／默认分支／可见性、tag或Release，不提交私有原始日志、图片、数据、凭据及构建目录。

本次用户要求为提交，当前不自动推送、触发新CI构建或发行。提交身份以实际分支历史为准，不为把提交SHA写进自身文档而循环改动。后续推送／新制品另核实际范围和身份；61ef9f9的成功CI运行41757564487不含本片改动。

## 3. 下一步：测试机按新身份做限定增量

优先交Windows11测试机验证本片，先核新提交及实际运行源；若使用新CI候选，须另核完整SHA、可信run／attempt、原字节PS1、ZIP／内层来源及来源freeze。源码结果不能迁移成新包静态或运行通过，旧包也不能继承本片修复。当前不在开发机SAC4551启动受阻EXE／helper，不换名／换根／改来源标记或系统保护重试。

增量只围绕本片：原生确认后的两个选择／默认保留／再次明确尝试；同根新窗口读取已保存日周稿、确认、历史、照片及任务回执；保存、原生文件、Word导出、维护／更新和AI发送／待落盘／退出未知时的拒绝；新旧能力失效、正常保存关闭与独立进程重开。主动故障注入只可针对核明归属的新合成源码窗口，沿已审核source-only验证器／自有Core操作，不杀未知进程或把验证开关加入产品。冻结包如何受控触发须先核实际工具能力，不以源码注入代替包内结论。

新的首失败保留，不自动重发未知AI任务、不用连续重开掩盖问题；回修沿原生互斥文件责任，由Codex具体授权并最终审阅。无需重跑旧39项教师清单、13份43页Word、微软拼音或W6跨120秒睡眠，也不新增教师流程或无关业务。

## 4. 数据、环境与未验边界

保持现有CPython3.14.10／Windows x64／标准GIL及锁定依赖，不安装／升级工具、Skill、MCP或依赖。验证使用新短合成根、独立合成凭据、APP_DISABLE_DOTENV=1及适用Python网络守卫；写入前核绝对路径／reparse边界。守卫不证明原生WebView／OS全局隔离，既有启动检查更新被拒记录不删。

真实原库、照片、密钥／DPAPI、旧包、Word／备份／保护包及首失败保持，不删锁、不全局kill、不真实关机／断电、不运行Office/r／regserver／修复。Win10／WPS／其它显示条件／干净机／跨用户凭据／长根206等原未验保持。本片不启动WebDAV、签名、安装更新、远控或公开发行；源码、静态、目标、Word与教师体验分别记。
