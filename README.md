# kindergarten-manager-next

面向幼儿园教师的本地教育工作支持应用，支持每日活动计划、游戏观察记录和周计划。项目由个人维护，原创内容采用 MIT 许可，暂无商业发行计划。

默认 [`main`](https://github.com/ywyz/kindergarten-manager-next/tree/main) 保留已合并的桌面源码基线；一对一倾听开发在 [`codex/desktop-one-to-one-listening`](https://github.com/ywyz/kindergarten-manager-next/tree/codex/desktop-one-to-one-listening)。当前尚无稳定签名发行包。

English: A locally run Windows desktop application for kindergarten teachers, covering daily activity plans, game observation records, and weekly plans. Maintained by [ywyz](https://github.com/ywyz). Original project code and documentation are MIT licensed. The default [`main`](https://github.com/ywyz/kindergarten-manager-next/tree/main) branch contains the merged desktop baseline; one-to-one listening development continues on [`codex/desktop-one-to-one-listening`](https://github.com/ywyz/kindergarten-manager-next/tree/codex/desktop-one-to-one-listening). A stable signed desktop release is not available yet.

## 当前可以做什么

- 编写、保存和查阅每日活动计划，比较历史内容，导出 Word。
- 使用本人的日计划和手填内容制作周计划，分别选择生成游戏、栏目或材料候选，预览后决定是否采用；保存并确认后可导出指定版本的 Word。详见[周计划规格](docs/specs/desktop-weekly-plan.md)。
- 按教师主动发起的操作，使用 AI 生成候选内容、重写并选择采用；生成失败或结果不明时可手动重试。
- 整理游戏观察记录的文字、照片、保存历史和 Word 导出；指定观察 Word 的工程页检与教师回执见[另机测试收口](docs/bootstrap/desktop-weekly-target-test-closeout.md)。
- 使用本地教师档案、班级及学期配置，无需旧版账号注册和管理员分班。
- 从应用创建完整本地备份、校验预览并明确恢复；源码验证、内部包静态与目标机实际恢复的结果分别记录。

首发面向 Windows 11。当前采用 Vue 3、TypeScript、Element Plus，Python/FastAPI、SQLAlchemy/Alembic、SQLite，以及 pywebview/WebView2。系统架构见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 开发状态

当前桌面分支的关闭／恢复修复已在原 Windows 11 测试机用 `b657363` 同源候选验证。普通保存关闭、渲染器与浏览器故障后明确重开、独立冷启动读回已保存内容均通过。同一候选的渲染器故障提示也通过了 Enter／Escape 人工补验。具体制品、退出回执及仍待观测的内部行为见[测试机报告 §10](docs/bootstrap/desktop-windows11-white-concurrency-review.md#10-2026-11-06b657363-原-windows-11-关闭恢复增量)。

周计划首片的指定 Word 和教师确认、后续周 AI 与材料的实际操作各有独立记录。旧候选的结果按各自来源保存；Windows 10、WPS、其它显示配置及干净机仍待验证。见[周计划目标机收口](docs/bootstrap/desktop-weekly-target-test-closeout.md)和[周 AI 目标机报告](docs/bootstrap/desktop-weekly-ai-windows11-target-review.md)。

一对一倾听记录已完成中班 Word 样稿的排版核查，正在细化记录、照片、备份、两种合册与 AI 整理的接入方式。见[产品规格](docs/specs/desktop-one-to-one-listening.md)、[工程设计](docs/specs/desktop-one-to-one-listening-engineering.md)及[当前任务](docs/tasks/current.md)。

应用更新通过本项目 GitHub Releases 的最新正式版本判断，普通代码提交不会触发更新提示。源码运行可检查版本，禁止下载／安装替换仓库程序；当前尚无正式 Release。AI 失败时保留原内容，结果不明的重试须确认可能重复处理／计费。两项实现及验证范围见 [本轮核查](docs/bootstrap/desktop-retry-github-review.md)。

## 数据和 AI

业务数据保存在使用者电脑上。启用 AI 后，应用会按使用者发起的操作，将相应文字和照片发送到其配置的供应商；AI 不是完全离线能力。当前应用供应商范围是 DeepSeek 官方 API 与 MiMo 标准 API。开发工具使用的 OpenCode 套餐不是应用内供应商接口。

不要将真实儿童资料、业务数据库、导出文件、API 密钥、证件或账单提交到仓库和 Issue。反馈问题时请使用合成资料，先删除个人信息。

## 从源码运行

以下命令用于 **Windows PowerShell 下的新克隆目录**。本轮经用户确认沿用 **CPython 3.14.10、Windows x64、标准 GIL**，依赖锁保持不变；旧3.14.7结果保留原身份，不代表所有Python版本均已验证。需准备 WebView2 Runtime、满足 [frontend/package.json](frontend/package.json) 引擎要求的 Node.js，以及 uv。已有开发环境应复用原环境，避免覆盖既有验证包或数据目录。

```powershell
git clone --branch codex/desktop-one-to-one-listening --single-branch https://github.com/ywyz/kindergarten-manager-next.git
Set-Location kindergarten-manager-next

# 先确认所选解释器为 CPython 3.14.10 x64 标准 GIL，再创建新环境。
py -3.14 --version
py -3.14 -m venv desktop/.venv-d1
$sourcePython = Join-Path $PWD 'desktop/.venv-d1/Scripts/python.exe'

# 安装现有锁定集合；不重新求解或升级依赖。
$wheelOnly = ((Get-Content desktop/requirements-d1.lock.txt |
    Select-String '^([A-Za-z0-9][A-Za-z0-9_.-]*)==') |
    ForEach-Object { $_.Matches[0].Groups[1].Value } |
    Where-Object { $_ -notin @('proxy-tools', 'proxy_tools') }) -join ','
if (-not $wheelOnly) { throw '未读到锁定包名，停止安装' }
uv pip sync desktop/requirements-d1.lock.txt --python $sourcePython --require-hashes --build-constraints desktop/requirements-d1-build-constraints.txt --only-binary $wheelOnly --strict --default-index https://pypi.org/simple --no-python-downloads --no-managed-python
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，保留环境和日志，不跳过校验' }

npm --prefix frontend ci
if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
npm --prefix frontend run build:d1 -- --outDir ../build/source-preview/frontend --emptyOutDir
if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }

# 独立体验目录；不要指向原有业务库或旧包的数据目录。
$previewData = Join-Path $env:LOCALAPPDATA 'KGNext-Source-Preview'
& $sourcePython -X utf8 desktop/d1_main.py --frontend build/source-preview/frontend --data $previewData
```

首次启动填写本地教师档案。AI 密钥在应用设置中输入，先不配置 AI 也可以验证手工编写、保存和导出。源码更新后应先查看迁移说明，并继续使用明确指定的数据目录；不要同时开启多个实例操作同一份数据。

以上是源码运行方式，不是已完成签名的发行包安装说明。当前开发机无需为了源码体验关闭 Windows 安全保护。

## 维护、许可和项目资料

- [维护者说明 / Maintainer statement](MAINTAINERS.md)
- [MIT 许可证](LICENSE)
- [第三方依赖与资源说明](THIRD_PARTY_NOTICES.md)
- [Certum 开源证书申请资料](docs/opensource/certum-application.md)
- [开源准备检查记录](docs/bootstrap/open-source-readiness-review.md)
- [项目规格与阶段证据](docs/bootstrap/README.md)

MIT 许可适用于本项目有权授权的原创内容；第三方依赖、运行时、商标及其他来源材料保留各自权利和许可。Word 模板的授权范围以资源说明及开源准备检查记录为准。未来若提供商业版本，需要分别处理源码许可、第三方许可及代码签名证书用途。
