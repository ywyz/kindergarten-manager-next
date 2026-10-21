# 普通运行验证包整合结果（desktop-d2-normal-r01，OpenCode）

更新：2026-10-20（N01／N02 收口修订）。本文记录把当前已验源码与 H06-R01 前端修复整合进**普通运行** `KGNext-D2Verify` 完整目录包的实施、自测与证据，供 Codex 独立核查。不修改 Codex review/current/AGENTS/规格／架构。

**未调用应用真实 AI／供应商；未发布、未安装升级、未 WebDAV、未 commit/push；未触碰任何人工／诊断根或其数据。新包字节未因本轮脚本修复而改变，未重建、未重跑完整包。**

## 1. 范围与边界

- 独立输出根 `build/desktop-d2-normal-r01/`；普通入口仍 `desktop/d1_main.py`，未使用 `d2_manual_ai_main` 人工壳，未混入合成供应商配置／凭据／数据库／fixture（包内扫描无 `.db`／credential／fixture／`.env`／secret）。
- 未改业务代码、schema／迁移、前端已验行为、架构或依赖；`d1_main.py`（`87e39a3e917a880a`）与 R01 组件（`CandidatePreview.vue 875f3c1c51e58cbb`）未动。
- 普通交互入口的受控传输／私网解析／测试 CA／执行器故障注入仍只限既有专用 `--selftest` 相位与显式合成根；本次未改该规则。
- 仅修改构建／验证脚本、单一构建路径测试、运行说明与本文档；未写回旧 frontend／work／spec／包。

## 2. 实际改动

| SHA256 前 16 | 文件 | 改动 |
| --- | --- | --- |
| `dd8232ecf3f7172c` | `desktop/build_d2.py` | N01：删除 `--allow-legacy-root`；在任何构建／文件写入前 `resolve` 并检查**实际写入**的 build-root、frontend（仅重建时）、work、spec、package、hash-out；任一与受保护旧根 `build/desktop-d2`、`build/desktop-d2-manual-ai`、`build/desktop-d2-manual-ai-h06-r01`（含人工／诊断子根）相等、祖先或子路径即拒绝。显式 `--frontend-dir` 是只读输入，允许复用旧前端且不纳入写入检查；独立同级 `build/desktop-d2-normal-r01` 允许。仍直接调用本地 Vite，不执行 npm ci／安装。 |
| `8bb7e4e54fca154d` | `desktop/verify_d2_w6_package.py` | 新增 `--frontend-dir`，用于包内前端逐文件核对（默认仍旧前端，本次显式指向新前端，避免误核对）。 |
| `8a9e24db74c4ab0a` | `desktop/tests/test_d2_build_paths.py` | 新增 N01 针对性测试：临时合成目录＋monkeypatch，不运行 Vite/PyInstaller；8 项覆盖旧根／子路径／祖先、换 dist-root 仍写旧 work/spec、旧 hash-out、合法同级根、显式只读旧前端，以及“只读前端不豁免旧 hash 写入”。 |
| — | `build/desktop-d2-normal-r01/RUN.md` | N02：按真实行为改写运行说明（见 §5）；不改产品。 |

**偏差**：`--add-data migrations_local` 仍原样包含源目录既有 `__pycache__`（与既往包一致），未为本次整合单独清理，避免改变已验证包布局。

## 3. 新包身份（本轮未重建，字节不变）

- 目录：`build/desktop-d2-normal-r01/package/KGNext-D2Verify/`（完整 onedir，不能只复制 EXE）
- EXE SHA-256：`e843d11b38ff87fc4876313aad8a20cb60912ff73c61b1f35d908dae81a6ba5c`（15,048,169 字节）
- 包内文件：**182**；包清单 SHA-256：`99ae429a998fdae01a187bf9c62a8ebedf718525b3c4b1ce3c612f72f0fdfbd2`
- 新前端：`build/desktop-d2-normal-r01/frontend`，清单 SHA-256 `396abc67f6f9a5490c402326104ab38de7d71b3a3705015202f11e3d87b9bed9`
- 逐文件散列与普通运行说明：`build/desktop-d2-normal-r01/package_hashes.json`、`RUN.md`

## 4. 已完成的完整包验证（首轮，包字节未变）

以下为 N01/N02 修订前、同一包字节（`e843d11b…`／`99ae429a…`）的真实冻结验证，仍适用；本轮未重跑整包：

| 检查 | 实际结果 | 日志 |
| --- | --- | --- |
| 前端 typecheck | exit 0 | `%TEMP%/opencode/normal_r01_typecheck.log` |
| D1 纯逻辑／组件 | exit 0／exit 0 | `normal_r01_d1.log`、`normal_r01_comp.log` |
| D2 组件（含 R01 8 项） | exit 0，`OK 81` | `normal_r01_w5.log` |
| 桌面全量 | exit 0，196 passed | `normal_r01_desktop.log` |
| 普通包构建 | exit 0 | `normal_r01_build.log` |
| 完整包验证（仓外特殊路径、包内前端、资源／同源／G14／G15／W5） | exit 0，**130/130**，missing/failed/extra 空 | `normal_r01_verify.json`、`normal_r01_verify.log` |

完整包验证要点：48 个生产模块 + 真实 `d1_main` 归档入口同源；前端／模板／迁移／Alembic 一致；DPAPI／TLS／Job／spawn／worker 收口；G14 单日/合并 Word + 重启；G15 四分支；w5-ui 关闭闭环；各阶段 exit 0。

## 5. N01／N02 针对性命令与结果

| 检查 | 命令 | 实际结果 | 日志 |
| --- | --- | --- | --- |
| 语法 | `python -m py_compile desktop/build_d2.py desktop/tests/test_d2_build_paths.py` | exit 0 | 终端 |
| 参数面 | `python build_d2.py --help` | exit 0，无 `--allow-legacy-root` | 终端 |
| N01 路径保护测试 | `pytest tests/test_d2_build_paths.py -q` | exit 0，**8 passed** | `%TEMP%/opencode/normal_r01_n01_test.log` |

N01 测试覆盖：旧普通根／R01 根／其子路径、受保护根的祖先作为 build-root、换 `--dist-root` 仍写旧 work/spec、旧 `--hash-out`，均在构建前拒绝；合法同级 `desktop-d2-normal-r01` 与显式只读旧前端允许；只读旧前端不会豁免旧 hash 写入。测试只用临时目录，未对真实旧包／前端／人工根执行反例。

N02 运行说明（`RUN.md`）现写明：普通入口支持 `--data` 选择数据根并沿用既有环境路径覆盖；已有档案直接读回，仅首次无档案填写；普通交互模式不启用受控传输／私网解析／测试 CA／执行器故障注入（仅专用 `--selftest` 与显式合成根）；不自动配置／调用供应商；不把人工合成根当普通教师根。未为说明改动产品行为。

## 6. H06-R01 前端证据的整合方式

- 新普通包前端清单与已独立核查的 R01 前端（`build/desktop-d2-manual-ai-h06-r01/frontend`）**逐字节一致**（同为 `396abc67…`，3 文件）；`d1.w5.test.mjs` 81 项（含 8 项 R01 按钮级检查）exit 0。
- 普通包 G14 覆盖候选编辑→比较→采用；取消／dirty 退出路径未在本普通包重新驱动，证据由“新前端与 R01 前端逐字节一致 + 81 项组件检查 + 既有 R01 冻结包真实窗口 DOM 证据”组合支持；不写成普通包已重新人工验证。

## 7. 旧包、旧构建与原数据保护

只读核对（未修改；N01/N02 后再次核对）：

| 产物 | 文件数 | 清单 SHA-256 | EXE SHA-256 |
| --- | --- | --- | --- |
| 原普通包 `build/desktop-d2/package/KGNext-D2Verify` | 182 | `84fbb22f66f14fbbffc5c6fe4c63810855c0fbbbc68571c608ff902f285b1f1d` | `56346c0ac1d874bbf00e947739a40c005f4a2a611b20d6fabf1a7d35a89fafb2` |
| 人工包 `build/desktop-d2-manual-ai/package/KGNext-D2ManualAI` | 182 | `2259bc1724efafb0dfc4b128171dc6c67e7750497f703bb8244d82456367813b` | `18915b7b7da778a7d467ce03fef08fb89e45b878854f1f714cc126bc1fdc9b75` |
| R01 人工包 `build/desktop-d2-manual-ai-h06-r01/package/KGNext-D2ManualAI` | 182 | `44e58c4e0f1635d1d69e530f32bd6e2a4c4be4c301b1393c9c8f8b5a3add6260` | `209dedcd5dfc4c8995478fc36146ae744ee653570ea318a54b25817b73a56c1b` |

- 旧 `build/desktop-d2/frontend`、work／spec 未被写入；新构建根独立。
- 所有人工／诊断根、Word、失败日志未触碰；未启动任何人工窗口或应用真实 AI。

## 8. 未验边界

- 真实供应商兼容与 AI 质量（G17）未验证；未调用真实 AI。
- 普通包人工 Word 逐页（新样本）、WPS、Win10、干净机器、其他 DPI／多显示器、安装器／发行再现性未验。
- H06-R02 白屏、H06-R03 额外任务按 2026-10-20 用户决定记录并保留观察，未修复／未关闭；G13 跨 120 秒睡眠不再验证（不写成通过）。
- 本包是普通运行验证包，不是发布安装版，也不等于 D2 完整产品或教师整体验收。

## 9. 状态

实现、测试、构建与验证脚本写入已停止（本文件与 RUN.md 除外）。新包与证据冻结（字节未变），等待 Codex 独立核查；旧包、原数据与全部既有证据保留。
