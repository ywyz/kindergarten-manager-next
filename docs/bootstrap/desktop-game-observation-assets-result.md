# D4：E03 图片材料切片实施结果

更新：2026-10-26。状态：OpenCode 实施及自测完成，**停写待 Codex 独立核查**；尚未提交、推送或合并。本记录不代表完整 A01–A22、真实教师图片、真实 AI、Word／宿主／页面、安装发行或桌面产品验收。

接续（2026-10-27）：Codex最终独立630项全local、新统一hash锁环境31项材料及85项相关宿主通过；R01–R11与本次Git收口以[独立核查](desktop-game-observation-assets-review.md)为准。下文保留OpenCode实施／自测交付时点，不把当时未提交或待审表述当作当前结论。

## 1. 范围与结论边界

本轮只实施 E03：依赖与合成容量证据、受管原图、方向校正、去元数据 AI／导出派生、排序／说明、回执、路径安全、故障保持及重启保持。没有启动 E05／E08 历史服务、E06／E07 视觉 AI、E09／E10 页面、E11／E12 Word／宿主或 E14；没有调用真实 AI、WebDAV、构建或真实教师数据。

E03 源码和测试为未提交工作区改动；`docs/tasks/current.md` 与 Codex 的 `docs/bootstrap/desktop-game-observation-assets-review.md` 保持原状，未由本实现改写。

## 2. 改动文件

| 文件 | 内容 |
| --- | --- |
| `backend/app/local/observation_assets.py` | E03 材料服务：流式 staging、完整解码、方向、去元数据派生、受管文件、回执、排序／说明／移除、路径和句柄保护、容量参数 |
| `backend/tests/local/test_observation_assets.py` | E03 合成回归：格式、EXIF／ICC、限制、回执、磁盘／SQLite 故障、真实 NTFS 路径、跨进程冷重启、R07 多图移除 |
| `backend/tests/local/worker.py` | 仅测试的隔离 worker：冷启动导入、精确派生读取、分阶段退出与 stage marker |
| `backend/scripts/observation_capacity_actual.py` | 最终实际管线容量矩阵与真实断言；生成、单图解码、长进程串行和字节门禁分离 |
| `backend/scripts/observation_capacity_probe.py` | 候选参数探索探针，保留候选身份，不冒充最终 actual 证据 |
| `backend/pyproject.toml` | 业务依赖新增 `Pillow==13.0.0` |
| `backend/uv.lock` | 单一业务解析更新；仅新增 Pillow 及其锁数据 |
| `desktop/requirements-d1.lock.txt` | 单一统一解析更新；仅新增 Pillow 及其 hash，不升级其他包 |
| `docs/bootstrap/desktop-game-observation-assets-result.md` | 本结果记录 |

## 3. 技术参数（本片证据阈值，不是教师业务额度）

| 参数 | 当前值 | 证据含义 |
| --- | --- | --- |
| 单图源字节 | 25 MiB | staging 写入超过即 `OBS_MATERIAL_LIMIT`；actual 矩阵字节门禁命中 |
| 源像素总数 | 40,000,000 | 7000×6000 反例在解码前拒绝 |
| 源单边 | 8192 | 8193×1000 反例在解码前拒绝 |
| AI 派生 | 最长边 2048，JPEG q85，目标 2 MiB；超过目标按 0.85 逐次缩放，6 次仍不满足则失败 | 不再返回超额 data；`AI_PARAMS_VERSION=ai-v2-2048-q85-target2mib-scale085` |
| 导出派生 | 最长边 2400，JPEG q90 | `EXPORT_PARAMS_VERSION=export-v1-2400-q90` |
| 工作集审查阈值 | 1024 MiB | 最终实际矩阵最高 734.24 MiB（WebP RGBA 40MP＋EXIF6）；长进程六张大图 734.96 MiB。约 290 MiB 只是该阈值与 codec 实测峰值的差额；未实测完整本机 API／WebView2／宿主工作集，不能承诺这些组件一定装得下，也**不是运行时硬 RSS 限额或产品总内存承诺** |

原始 40MP／8192／25MiB 提案现由本片实际管线证据支持；AI 2MiB／缩放策略已写入参数版本。E06 请求／Base64／IPC 和 E11 DOCX 参数仍未验，不能引用本片为已验。

## 4. 容量证据（实际交付入口）

命令（生成与测量分离；每张图在新进程执行；长进程另行串行）：

```text
cd backend
../desktop/.venv-d1/Scripts/python.exe scripts/observation_capacity_actual.py \
  --output <evidence-root>/capacity-final-r10.json
```

证据根：`C:/Users/yw980/AppData/Local/Temp/kgm-observation-e03-20261026-2f7e5331`。实际入口为 `app.local.observation_assets._prepare_asset`；字节上限使用实际 `_write_staging`。生成进程不计入峰值。

| 用例 | 结果 | 峰值 MiB | 说明 |
| --- | --- | ---: | --- |
| PNG 40MP RGBA | 接受 | 428.71 | 8000×5000 |
| PNG 40MP RGBA＋EXIF6 | 接受 | 428.86 | Codex R05 组合，修复后 |
| WebP 40MP RGBA＋EXIF6 | 接受 | 734.24 | R05 最高峰；解码器自身内存 |
| JPEG 40MP RGB＋EXIF6 | 接受 | 138.43 | JPEG draft |
| GIF 40MP 透明 | 接受 | 104.68 | 静态 GIF |
| BMP 40MP RGB（纯 codec 压力） | 接受 | 275.88 | 120,000,054 B 源；**不是可导入案例**，真正 import 会在 staging 按 25 MiB 先拒绝 |
| 5500×3600 高熵 JPEG | 接受 | 186.54 | 源 23,236,976 B＝22.16 MiB（23.24 MB），接近但低于 25 MiB |
| 8192×1953 JPEG | 接受 | 147.78 | 单边边界内 |
| 7000×6000 JPEG | 拒绝 | 62.67 | `OBS_MATERIAL_LIMIT`（像素） |
| 8193×1000 JPEG | 拒绝 | 62.69 | `OBS_MATERIAL_LIMIT`（单边） |
| 25 MiB＋1 字节 JPEG | 拒绝 | 89.71 | staging 门禁 `OBS_MATERIAL_LIMIT` |
| 串行六张大图 | 全部接受 | 734.96 | 同进程 PNG/WebP/JPEG/GIF/BMP，无累积增长 |
| 串行十六张小图 | 全部接受 | 187.69 | EXIF 1–8、ICC、CMYK、GIF、BMP、WebP 等 |

40MP BMP 行只是纯 codec 的额外压力用例；实际 import 对 JPEG／PNG／WebP／GIF／BMP 五种格式都必须同时满足 25 MiB 源字节、40MP 像素和 8192 单边限制，不能把 120 MB BMP 当成可导入样本。

R05 修复前独立实测 PNG 581.70 MiB、WebP 886.73 MiB；本次将方向旋转前的源图先缩到派生所需 master 后，分别降至约 428.86／734.24 MiB。候选探针只保留参数探索身份，不作为最终通过证据。

实际探针的预期接受／拒绝、错误码、AI 2MiB、2048／2400 最长边和预算均有断言；`--budget-mb 512` 对照运行返回 1（WebP 与大图串行超预算），默认 1024 运行返回 0。证据文件：`capacity-final-r10.json`、`capacity-low-budget.json`、`capacity-matrix-1024.json`。

BMP 40MP 行是纯 codec 压力用例；真正 import 必须同时满足 25 MiB 源字节、40MP 像素和 8192 单边，因此 120 MB BMP 不会被导入接受。五种格式均受同一组限制约束。

## 5. 功能与故障修复

- **R01／R03／R04**：原图读取按复合归属、实际句柄最终路径、最终路径身份、fstat／lstat 和硬链接／reparse 检查；所有 relative 组件（含叶子）拒绝 ADS、尾点／尾空格、设备名、反斜杠、绝对／遍历。读、staging、派生写入、rename 均使用句柄和父目录句柄保护；最终路径 API 不可验证时安全拒绝，不再 fail-open。
- **R02**：EXIF TIFF 校验覆盖 IFD0、Exif／GPS／Interop／SubIFD 指针、next-IFD，含越界、截断、循环和条目值范围；DFS 使用 `visiting` 出栈和 `validated` 缓存，同一合法 IFD 被重复引用不再误报循环，真循环仍拒绝。合法嵌套 GPS、缩略图和无 EXIF 照片保持接受。JPEG／PNG／WebP 派生为新建 RGB 容器，清除 EXIF／GPS／ICC／XMP／comment；原字节按原 hash 保留。
- **R05**：实际容量矩阵与 1024 MiB 证据阈值；AI 目标不足时明确失败；参数版本包含 `target2mib`／`scale085`。
- **R06**：staging／派生 fsync／最终 replace／mkdir 各阶段 ENOSPC 均脱敏为 `OBS_STORAGE_IO`，已有照片、说明、草稿、receipt／audit 不变且失败 staging 保留；真实 SQLite 触发器 `RAISE(ABORT)` 证明文件已落盘、DB／receipt／audit 整体回滚、孤儿保留、旧稿可读；跨进程冷重启测试由父进程释放 runtime，worker 以 `connect_only=False` 走 `LocalRuntime.prepare`／锁／恢复，覆盖 after_commit、after_files、partial（先执行真实 flush 再退出）、before_commit，验证 stage marker、孤儿、旧数据和无残留。
- **R07**：`remove_photo` 在当前事务内 delete／reinsert 当前 draft photos，避免 ORM 按主键更新造成中间顺序唯一冲突；确定性覆盖 3／4 图移除首／中／末、资产 ID 次序与展示次序不同、dense 0..N−1、说明保持、重复回执、E01 aggregate_hash、历史与 AI input 引用仍可读。
- **R08**：worker 按精确 derivative_id 读取并核对 DB hash／尺寸／参数／字节；读取错误直接使 worker 失败，不再以 error key 伪装成功。跨进程测试使用冷启动、阶段 marker、实际部分行、独立孤儿目录、原 request 回执重放和 SQLite backup 后的 `integrity_check`／`foreign_key_check`。
- **R09**：`_discard_attempt` 已改为明确的 no-op；成功空 staging、回执重放孤儿和失败现场均暂留，不执行无保护的递归删除，也不删历史／资产。确定性反例在 staging 祖先替换为 junction 后调用清理，受管根外 `keep.txt` 保持；同一 request／expected_revision 仍返回原回执。该保留策略是首期边界，后续若做清理必须另行设计并审查句柄绑定删除。
- **R10**：`import_asset` 不再在 `_write_staging` 后按路径重新 `Image.open`；`_prepare_staged_asset` 在父目录句柄保持打开、staging 文件句柄经最终路径／身份检查后，用同一句柄的 dup 执行 codec 和 `image.info` EXIF 校验，解码后再核 fstat／lstat 身份。容量脚本仍可对任意合成路径调用纯 `_prepare_asset`，不改变产品 service 入口。确定性反例在写完后、解码前把 staging 祖先换成指向根外的 junction；断言 `_prepare_asset` 未调用、根外文件未解码、无 DB／成功回执／audit、旧稿保持。

## 6. 已执行验证

| 命令 | 结果 |
| --- | --- |
| `pytest tests/local/test_observation_assets.py -q` | 31 passed（R09／R10／R02 收口后） |
| `pytest tests/local/test_observation_assets.py tests/local/test_observation_migration.py tests/local/test_observation_models.py tests/local/test_observation_prompt_contracts.py tests/local/test_observation_terms.py tests/local/test_observation_validation.py -q` | 82 passed（R09／R10／R02 收口后） |
| `pytest tests/local -q` | 626 passed（**R09／R10／R02 修订前**自测；不冒充最终源码全 local，最终由 Codex 独立执行） |
| `observation_capacity_actual.py`（默认 1024） | exit 0；矩阵无失败 |
| 同上 `--budget-mb 512` | exit 1；WebP 与 serial large 超预算被真实报告 |
| `uv lock --check` | 28 packages，通过 |
| `E03_EVIDENCE_ROOT=... pytest ...::test_cross_process_commit_crash_and_restart` | 1 passed；SQLite `integrity_check=ok`、`foreign_key_check=[]`、receipt replay 相等 |

跨进程证据保存在 `r08-evidence-latest/r06-cross-process/`：一致性 SQLite backup、受管 `observations/`（含失败孤儿）及脱敏 `summary.json`。stage marker 为 after_commit／after_files／partial／before_commit；partial 与 before_commit marker 显示事务内已写入行，最终 DB 无对应残留。

依赖锁只新增 `pillow==13.0.0`；`backend/uv.lock` 与 `desktop/requirements-d1.lock.txt` 均由单一解析流程更新，未升级无关包。锁生成后未执行干净环境全量 `uv pip sync`，本机验证使用已装 Pillow 的隔离桌面 venv。

## 7. 未验项与停止边界

- 本实现与自测只使用隔离合成图，未解码或上传真实教师照片、真实数据库或真实凭据。Codex 另在授权范围内只读检查了 6 份用户 DOCX 中 17 张 JPEG 的头信息（最大 1440×1080／0.72 MiB，原件 hash 不变，未读正文、未解码真实图、未上传）；该独立检查归 Codex review，不把本结果写成“从未访问任何真实材料”，也不替代真实照片视觉质量验收。
- 未验 E05／E08 历史服务、E06／E07 视觉 AI、E09／E10 页面、E11／E12 Word／宿主、E14 打包、真实 AI／WebDAV／签名发行。
- 未验 Windows 10、WPS、其他 DPI／多显示器、干净机器、真实安装／升级、其他文件系统或非本机硬件容量。
- 容量是 Python／Pillow 实际管线进程峰值，不是整机总内存或产品预算；1024 MiB 为审查阈值。
- 未执行 Codex 独立复核；本记录不把自测写成独立通过。
- 未提交、未推送；等待 Codex 审核后再由 Codex 执行已授权 Git 操作。

停止边界：本片实现、测试和证据到此为止，不启动后续切片、不应用真实 AI、不发布。
