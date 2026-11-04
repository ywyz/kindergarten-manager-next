# 当前：回归修复交付与原测试机增量

更新：2026-11-04。继续`codex/desktop-v2-foundation`；本文件是唯一执行入口。用户本轮要求拉取ead1e99，使用OpenCode／Command Go DeepSeek V4.1 Flash max实施，由Codex独立审核至修复完成，判断下一步，最后普通提交推送。本机与远端不能快进后，用户已明确允许普通merge保留cb4e7ed恢复片与ead1e99测试交接两个父历史。最终交付身份按实际分支和远端核对，不为回填自身SHA循环改文档。

## 1. 开发机工程已完成

[回归修复核查](../bootstrap/desktop-regression-repair-review.md)归本轮接收、互斥责任、模型metadata、所有首失败／负对照及最终身份：独立完整local **1229通过**、desktop **628通过**，均0失败／0error／0skip；前端14份脚本、typecheck、D1构建及观察源码窗口17检查通过，549个非文档文件前后相同。原首轮1214通过／14周执行器失败及D2取消夹具竞态保留，不将诊断单项通过冒称全套。

本轮修复旧revision／manifest／表及注册集合预期、失败dispose、selftest精确窗口绑定、观察导出非预期异常终态。周fake worker原样移到只用标准库的轻量模块，独立进程禁止重依赖回流；取消用例在实际READY到mark前双向同步，保持一次attempt／无SEND／候选0／退出确认。未改生产AI执行器／worker、预算、重试、依赖或迁移，不加sleep／skip或串行化并发采用。

用户已确认的[异常页面手动重开](../specs/desktop-renderer-recovery.md)继续有效，[生命周期核查](../bootstrap/desktop-renderer-lifecycle-review.md)的238项及真实Page／Browser故障业务窗口、独立进程指纹保持其cb4e7ed源码身份。测试机旧报告中“恢复待核定”不是撤销该产品决定；原白屏自然触发、Word/r历史差异仍未知。新构建不继承旧包／Word／教师结论，不作产品整体验收。

## 2. 下一步：返回原Windows11测试机

应回原测试机复核，因为原15项失败发生在该环境，恢复片也需要新交付的目标证据。

1. 先正常关闭原体验应用并确认宿主退出，保留原资料和工作区差异。核目录／分支／HEAD／远端，普通fetch及`git pull --ff-only origin codex/desktop-v2-foundation`；不能快进则停止同步并报告，不重放本轮仅针对两已知提交的merge授权。记录实际收到的完整SHA／tree及运行源，重建同源D1前端。
2. 使用现有CPython3.14.10 x64标准GIL与锁定依赖，在新短合成TEMP／TMP内独立跑一次完整`backend/tests/local`并保留日志／JUnit。APP_DISABLE_DOTENV=1、SQLAlchemy纯Python、禁pyc及适用Python网络守卫，实际解释器路径须核；B3根在TEMP内且满足120字符限制。不要只以15个单项通过关闭原完整上下文问题。复发先保留进程／ready／permit／SEND／落盘时序与首失败，不以增加sleep／预算／重试消除。
3. 验证恢复限定增量：原生确认后默认保留／两个选择／保留后再次明确尝试；同根新窗口读回已保存日周稿、确认、历史、照片和任务回执；保存、原生文件／Word、维护／更新和AI发送／待落盘／退出未知时拒绝；旧能力失效、正常保存关闭及独立进程重开。主动故障只用于核明归属的新合成源码窗口／自有Core，不碰已配置AI体验档案。冻结包受控触发能力另核，不加产品调试开关，不以源码注入替代包内证据。
4. 保留测试机已配置AI的原数据根及独立凭据根，按[配置保留§6.7](../bootstrap/desktop-windows11-white-concurrency-review.md#67-后续拉取代码时保留本机ai配置)，同机同用户显式`--data`／`--credential-root`普通启动，仅核设置已配置、无新增attempt和正常关闭，无须重新填写或为此再发付费请求。两根不用于自动测试、故障注入、备份恢复或清理，不复制DPAPI，不在聊天索key。
5. 若push自动产生新CI候选，先核本次完整HEAD的可信run／attempt、ZIP与原字节PS1、package-info.source_commit、两个身份文件build_id／revision及source freeze。工作流是Windows2022构建／静态检查，不是Windows11运行通过。未取得新包字节核验就只交源码身份，不dispatch／重跑或以旧成功包替代。

## 3. 已结束责任与后续回修

本机原A／B及新原生X的实施已停写，Command Go因写工具拒绝转只读复核；具体身份、X新对话决定及A只读阶段主动中断见结果，不冒称自然完成或跨机会话。均固定Flash max、无fork／子代理，不重放已结束文件白名单。后续首失败沿新精确文件责任交原生实现者，Codex独占正式文档、独立验证和最终审核；不还原他方修改，不放宽权限或以shell绕过拒绝。

本轮已明确授权普通提交推送，由原A按Codex当次准确文件、规范化blob、双parent及index tree执行，Codex独立核提交与远端；不add-all／amend／rebase／force、改main／默认分支／可见性、tag或Release。不提交私有原始日志／数据／凭据／构建目录。

## 4. 保持边界

[周AI工程](../specs/desktop-weekly-ai-engineering.md)、[验证矩阵](../specs/desktop-weekly-ai-validation.md)、[正常保存关闭](../specs/desktop-manual-daily-plan.md)及[完整备份恢复](../specs/desktop-backup-restore.md)保持。写入／递归清理前核绝对路径／源目标／旧根和reparse边界，不删未知文件、不全局kill、不重发未知AI任务；守卫不证明原生WebView／OS全局隔离。真实原库／照片／凭据、旧包／Word／备份／保护包和首失败保留。

不重跑旧39项教师清单、13份43页Word、微软拼音或W6跨120秒睡眠，不/r／regserver／Office修复，不真实关机断电。SAC4551不启动受阻冻结EXE／helper、不换名换根／改来源标记或保护重试。不安装升级工具／Skill／MCP／依赖，不启动WebDAV、签名、安装更新、远控或公开发行。Win10／WPS／干净机／其它显示条件／跨用户凭据／长根206及Windows符号链接特权等原未验保持；本轮真实junction通过不冒称symlink特权通过。保存／恢复／关闭失败先保留现场并停对应写操作，继续独立只读工作。
