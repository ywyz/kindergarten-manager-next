# kindergarten-manager-next

面向幼儿园教师的本地教育工作支持应用。先做好每日活动计划，再逐步完善游戏观察记录。项目目前由个人维护，原创内容采用 MIT 许可，暂无商业发行计划。

**当前桌面版在 [`codex/desktop-v2-foundation`](https://github.com/ywyz/kindergarten-manager-next/tree/codex/desktop-v2-foundation) 分支开发。默认 `main` 保留旧版云端实现，不能按旧版部署说明启动当前桌面应用。**

English: A locally run Windows desktop application for kindergarten teachers, covering daily activity plans and game observation records. Maintained by [ywyz](https://github.com/ywyz). Original project code and documentation are MIT licensed. The desktop version is under active development and is currently verified from source; a stable signed desktop release is not available yet.

## 当前可以做什么

- 编写、保存和查阅每日活动计划，比较历史内容，导出 Word。
- 按教师主动发起的操作，使用 AI 生成候选内容、重写并选择采用；生成失败或结果不明时可手动重试。
- 整理游戏观察记录的文字、照片、保存历史和 Word 导出；这些能力仍在开发验证。
- 使用本地教师档案、班级及学期配置，无需旧版账号注册和管理员分班。

首发面向 Windows 11。当前采用 Vue 3、TypeScript、Element Plus，Python/FastAPI、SQLAlchemy/Alembic、SQLite，以及 pywebview/WebView2。系统架构见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 开发状态

目前继续使用源码桌面环境验证。E14 已完成相应源码、构建和静态检查，最近一次新生成的未签名冻结包执行被 Windows Smart App Control 阻止，尚未完成后续整包运行验证。因此，源码验证通过不代表安装包、完整产品或教师体验已经验收通过。

完整状态、已知限制及后续工作见 [当前任务](docs/tasks/current.md) 和 [E14 独立核查](docs/bootstrap/desktop-game-observation-e14-review.md)。Windows 10、WPS、其他显示配置、干净机器及正式发行更新仍有未验范围。

应用更新通过本项目 GitHub Releases 的最新正式版本判断，普通代码提交不会触发更新提示。源码运行可检查版本，禁止下载／安装替换仓库程序；当前尚无正式 Release。AI 失败时保留原内容，结果不明的重试须确认可能重复处理／计费。两项实现及验证范围见 [本轮核查](docs/bootstrap/desktop-retry-github-review.md)。

## 数据和 AI

业务数据保存在使用者电脑上。启用 AI 后，应用会按使用者发起的操作，将相应文字和照片发送到其配置的供应商；AI 不是完全离线能力。当前应用供应商范围是 DeepSeek 官方 API 与 MiMo 标准 API。开发工具使用的 OpenCode 套餐不是应用内供应商接口。

不要将真实儿童资料、业务数据库、导出文件、API 密钥、证件或账单提交到仓库和 Issue。反馈问题时请使用合成资料，先删除个人信息。

## 从源码运行

以下命令用于 **Windows PowerShell 下的新克隆目录**。当前已验证的解释器是 **CPython 3.14.7、Windows x64、标准 GIL**；不要把版本声明理解为所有 Python 版本均已验证。需准备 WebView2 Runtime、满足 [frontend/package.json](frontend/package.json) 引擎要求的 Node.js，以及 uv。已有开发环境应复用原环境，避免覆盖既有验证包或数据目录。

```powershell
git clone --branch codex/desktop-v2-foundation --single-branch https://github.com/ywyz/kindergarten-manager-next.git
Set-Location kindergarten-manager-next

# 先确认所选解释器为 CPython 3.14.7 x64 标准 GIL，再创建新环境。
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
