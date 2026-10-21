# G17准备：候选服务官方文档已核对，待确定具体配置

2026-10-21用户最新指令：预计使用DeepSeek、MiMo及OpenCode Go，先查官方文档核对兼容性；不设计预算限额，暂不实际调用真实AI或发布。此前token／费用数字及供应商硬预算前置要求已撤回；不新增测试或生产预算功能。

## 当前入口与下一步

- [官方文档兼容性核对](../bootstrap/desktop-d2-g17-provider-compatibility-review.md)已完成：DeepSeek官方API与MiMo标准API符合当前最小请求／正常响应形状，可准备G17；真实输出、账户可达性和教师质量均未验。MiMo Token Plan不适用于本应用后端；Go虽有API，但用途与客户端要求尚未满足，暂不能认定当前包可直接接入。
- [G17验收方案](../bootstrap/desktop-d2-g17-acceptance-plan.md)已同步候选服务及上述边界，保留虚构材料、串行样本、停止条件及结果表；没有预算设计。前版由Git保留，不另存副本。
- 下一步确定准确模型、标准API账户类型和测试顺序，API前缀及型号候选见兼容性记录。若仍拟让教育应用使用Go，先澄清用途是否受支持，再决定是否需要客户端适配；不补头伪装编码流量。密钥只在后续应用填写，不在聊天发送。
- 后续另获实际调用授权后，一次固定一个服务／模型，用独立普通包数据／凭据根，依次完成拆分、适龄、其他活动各一个真实样本，审阅／采用／保存后再做下一类，随后Word／重启读回。首轮预期三个业务触发是验收范围，不是生产配额；不由三项候选自动扩为九次。失败／结果不明先停，不自动补发；usage可得则记录、缺失记不可得。

## 已有交付与权限

普通包相关修改2cafa4962c9cf132ce584c2ad96a96191d653713、前版G17文档a3e7062均已推送origin/codex/desktop-v2-foundation。[普通包独立核查§6–7](../bootstrap/desktop-d2-normal-package-review.md#6-最终独立核查与交付结论)及[实现结果](../bootstrap/desktop-d2-normal-package-result.md)保持；包仍为build/desktop-d2-normal-r01/package/KGNext-D2Verify/完整182文件、EXE e843d11b…，不重建或上传包。方案修正归入同一已授权文档交接，实际Git状态以记录为准。

当前仅查询公开官方文档并修正规划，不打开应用、填写配置、登录账户或发供应商API请求；不调用应用真实AI或发布。已有连接／120秒／1MiB工程限制、状态保护和明确未发送时的有限重试保持；不以缺少预算功能作为G17前置阻塞，也不擅自更改工程限制。

保持codex/desktop-v2-foundation；OpenCode唯一写实现、测试、迁移与构建，Codex规划／核查／验证／Git。保护默认教师库、全部旧包、human／诊断根、Word和失败日志；自动验证只用独立合成根并禁dotenv。当前无新增编码任务。[W6收口三项事件](../bootstrap/desktop-d2-w6-closeout.md)继续按用户决定保留；G17／G18及完整产品／发行未通过，不启动D3／WebDAV或观察记录。
