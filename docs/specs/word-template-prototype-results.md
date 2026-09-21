# Word 模板隔离原型结果

2026-09-20。依据：[验证计划](word-template-validation.md)、[实施规格](manual-plans-and-word-export.md)。当前验收基准为 Ubuntu + LibreOffice；Microsoft Word 留待正式使用后反馈，不阻塞当前阶段。

## 结果与证据范围

11 份 DOCX、31 页已通过本次固定夹具的内容、标红、分页和合并检查；最终页面已逐页查看。LibreOffice 无界面加载并渲染成功，未执行桌面 GUI 的修复提示检查，也未验证 Microsoft Word、WPS 或实体打印。这是模板原型结果，不代表产品导出功能或全部业务流程验收。

执行环境为 Ubuntu 26.04.1 LTS，已有运行时的 LibreOfficeDev 26.8.0.0.alpha0（构建 `2c87e51eeaa2b413ff4ae097b2705eea1995d8e5`），Python 3.12.14。开发版结果不能直接外推至用户其他 LibreOffice 版本。渲染采用 NotoSerifCJKsc、NotoSansCJKsc、NotoSerif 等字体，存在原模板字体替代；未发现缺字或内容裁切，但不承诺与原字体像素一致。

原型使用 ZIP／lxml 定点修改 OOXML，只改变 `word/document.xml`，其他包部件保持字节一致。此方式只作为本次试验，不据此确定生产生成库。未安装依赖，未创建产品代码、数据库或项目骨架，未连接服务器或真实 AI。

## 案例结果

| 案例 | 输出及页数 | 本次通过的检查 |
| --- | --- | --- |
| W1 普通与空内容日计划 | W1-daily：2；W1-empty：2 | 栏目、主题、表头；日计划一项集体加一项自选；无基准不标红；空栏目不补写 |
| W2 长过程 | W2-long-redline：4 | 长过程跨页；新增与替换标红；删除不输出；纯移动、格式变化不标红 |
| W3 多日合并 | W3-daily-merged：8 | 日期升序，范围外排除；每份从新页开始；两份单独文件与合并对应页面逐像素一致 |
| W4 调休、假期及特殊周 | W4-holiday-sunday、W4-six-days、W4-seven-days：各 2 | 固定日历夹具中周日归实际周；假期与缺计划分开；六、七上课日列完整；首末上课日表头 |
| W5 跨月及单日选整周 | W5-cross-month：4；W5-single-day-whole-week：2 | 整周选择、去重、排序；单份与合并对应页面一致；无交集不生成文件 |
| W6 已确认与不完整版本 | W6-confirmed-v1：2；W6-confirmed-incomplete：1 | 固定 V1 内容不混入候选；完整版本两项集体加一项自选；不完整版本不凑数；材料、目标、指导映射 |

机器检查包括 OOXML 与渲染 PDF 字符多重集一致、红字内容准确、文字不越页、没有空白页、三组单份与合并页面一致，以及原文件哈希不变。字符检查不独立证明语序，结合夹具结构及逐页检查判断。

W2 预期红字为“缓慢”及“新增提醒：先检查纸杯边缘，再开始探索。”；其余最终过程文字不标红。测试夹具中的日期与调休均为显式配置，不推定真实法定日历。

## 发现与处理

原模板“本周重点”可编辑段落携带自动编号，合并第二周时发生编号续接。原型仅移除该内容槽继承的段落编号；保留模板其他包部件，重新生成并渲染受影响的七份周计划，单份与合并一致性检查通过。日计划未受影响，复用有效结果。

部分周计划自然续页后，末页仅包含生活习惯培养与家园共育内容，保留较多页尾空白；没有额外空白页，未为压缩页数缩字或删栏目。表格中的栏目名称允许随自然分页拆到下一页，当前证据不承诺每份周计划固定一页。

## 未执行及后续边界

- 权限、重复创建、数据库事务、任务状态、来源变化和确认流程尚无产品实现；固定夹具不能证明这些行为通过。
- 缺项及无基准提示仅有模拟数据，未验证真实界面；材料是模拟 AI 文本，未验证 AI 提取与补充质量。
- 未安装或调用 `chinese_calendar`，年份覆盖和管理员例外须在日期功能实现时验证。
- 差异算法仅验证本次夹具，重复段落、多重移动等更复杂歧义需随实现补充必要用例。
- 当前结果不包含桌面 GUI 打开检查。Microsoft Word 明确延期反馈，不作为本阶段阻塞项。

## 本地证据与交付位置

原型目录：`/home/ywyz/code/kindergarten-word-prototype-20260920-4A2LoW`，位于产品仓库之外。

- [11 份 Word 测试样例压缩包](/home/ywyz/code/kindergarten-word-prototype-20260920-4A2LoW/word-prototype-samples.zip)。
- [夹具及来源记录](/home/ywyz/code/kindergarten-word-prototype-20260920-4A2LoW/fixtures.json)。
- [输出清单及哈希](/home/ywyz/code/kindergarten-word-prototype-20260920-4A2LoW/manifest.json)。
- [机器检查结果](/home/ywyz/code/kindergarten-word-prototype-20260920-4A2LoW/verification-results.json)。

日计划最终渲染在 `rendered/`，周计划最终渲染在 `rendered-final/`；具体路径见机器检查结果。原始 Word 哈希与验证计划记录一致，原文件未变。以上为本机证据路径，不是可跨机器使用的仓库附件。

下一项建议任务：明确授权后建立 Architecture v1 技术栈的最小前后端骨架及本地启动检查，为手工保存主链路提供基础。本报告不自动授权实现、生产数据库、部署或 Git 提交。
