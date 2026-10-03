# 本机桌面验收准备（2026-10-03）

用户授权准备服务器、账号并撰写本机桌面 Codex 提示词。沿用已部署实例，不新增服务或子域名、不改旧应用；本轮无业务代码修改。上轮未提交文档保留。

## 服务与本机

SSH 密钥已连接 `root@bwh.ywyz.tech`。本机此前尚无该主机名的 known_hosts 条目，首次使用 `StrictHostKeyChecking=accept-new` 加入新主机记录，未忽略已存在的变更警告。Caddy、`kg-next-i5-api` active；MySQL容器 `kg-next-i5-mysql-20261002` 运行，监听仅 `127.0.0.1:13386`。current 仍指向 `2cb8d81556f47936e236dadedcb37bf3cec5b3c8`，API内部端口18090。

本机验证 https://kg-next-verify.ywyz.tech/health 返回200与ok，现存Caddy同源静态／API路由无需更改。只读资源观察：根盘可用6.0GB、内存available约553MB；不作为容量验收。

Windows 11 Pro `10.0.26200`，Word安装文件版本 `16.0.20430.20092`，Chrome `154.0.8037.98`、Edge `154.0.4258.48`。尚未执行本轮GUI或Word页面检查。

## 私密交接

目录 `C:\Users\yw980\.codex\tmp\i5-desktop-acceptance-20261003`；Windows ACL去除父目录继承，仅当前用户 `yw980` 和 SYSTEM拥有访问权限，文件继承此受限ACL。复制现存服务器 `/etc/kindergarten-manager-next-i5/acceptance-accounts.json` 为 `private-acceptance-accounts.json`，不重置口令。创建downloads／screenshots／logs；凭据不进入仓库或工具输出。

五个账号 `adm_i5`、`tow_i5`、`tsw_i5`、`tcr_i5`、`tfr_i5` 的Windows Node HTTPS登录与身份查询全部200，Secure／HttpOnly cookie检查通过。教师班级分别为clsi5／clsi5／clsi5b／未分配，管理员与未分配账号class-context为预期403。最终登出全部204。首次预检的登出请求遗漏JSON Content-Type而返回422，修正并重跑通过；已在精确时间窗口及五账户匹配断言后仅撤销首轮五个临时session，未改auth_version或其他session。

这是账号API准备，不替代浏览器登录。当前WSL agent的浏览器禁用仍需桌面验收前按提示词切换Windows native并完整重启。

## 夹具与变化

只读检查确认Trae修改保留：09-02当前v3非空，第10周已确认v1；初始清单不再代表当前状态。为全空版式验收，负责人经现有HTTP PATCH和expected_content_version=3追加09-02全空v4，未修改历史行、周确认或日历。v3原内容备份保存在私密交接目录，准备结果摘要为 `empty-day-preparation.json`；关闭准备会话已登出204。操作产生恰一次额外 `update_daily_plan`，原32份计划不增加。

当前：[脱敏夹具快照](i5-desktop-fixtures-2026-10-03.json)，32份日计划／35个日版本、10份周计划／22个草稿版本／11个确认快照，成功导出审计仍58条。本轮未调用成功导出、不产生DOCX，也未执行浏览器验收。09-02全空v4、09-03长过程v1、第2周确认v1／v2及未确认草稿4、第9／10周确认v1已就绪。日31／32与周8／9份边界范围保持不变。

所有材料仍为空，I4规则不接受非空materials。W6非空模拟材料／改选来源及W2纯移动／格式定向子例不能据现存夹具宣称就绪；提示词明确先完成其余已就绪下载和全页检查，再单列缺项，不绕过产品规则。没有重新播种或删除确认记录。

## 桌面交接

[提示词](i5-desktop-codex-prompt-2026-10-03.md)覆盖能力预检、Windows工作方式、五角色、当前版本、D01–D13全页检查、失败路径、哈希／截图清单、审计基线与收尾。Windows交接目录另存 `desktop-codex-prompt.md`、`fixture-state.json`、参考文档副本，桌面无需安装工具或重新部署。

验收结束前保留服务器与私密交接；不停止远程服务、不删除库／volume。I5产品验收状态仍待本机实际结果，准备完成不代表桌面验收通过。
