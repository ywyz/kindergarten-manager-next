# 第三方依赖与资源说明

核对日期：2026-10-30。根目录 [MIT 许可证](LICENSE) 适用于本项目有权授权的原创内容，不替换第三方许可、版权或商标。

## 记录范围

Python 表来自当前已安装桌面验证环境的 47 个分发包及包内许可元数据；前端表来自 `frontend/package-lock.json` 的 93 个依赖项，含开发工具和不同平台的可选项。这里记录源码开发所用依赖，不表示这些包全部进入教师运行包，也不表示后续二进制发行的逐文件许可核查已经完成。

依赖权威文件为 `backend/pyproject.toml`、`backend/uv.lock`、`desktop/requirements-d1.in`、`desktop/requirements-d1.lock.txt` 及前端 package / lock。复用或分发依赖时仍须保留对应版本的完整许可证、版权与适用 NOTICE。下表不能替代这些原文。

## Word、截图和运行时

- 五份受控 Word 模板位于 `backend/app/assets/word_templates/`。用户于 2026-10-30 明确确认模板由本人制作，或已取得可公开分发及采用 MIT 的授权；本轮清理后的模板按该授权纳入 MIT。清理内容与当前 hash 见资源 README，独立核查见 [开源准备检查](docs/bootstrap/open-source-readiness-review.md)。原始未清理文件及历史证据不因此变成可推荐公开的样例。
- 仓库中的历史界面截图是合成验证资料，不包含真实儿童照片；其中展示的 Microsoft 等产品界面、名称和商标仍归原权利人。
- Windows、Microsoft Word、WebView2、.NET 以及系统字体不因项目采用 MIT 而取得额外分发授权；本源码仓库不提供这些产品的安装包或嵌入字体文件。
- CPython 及其运行时组件遵守 Python Software Foundation 及所附许可。后续冻结包需保留实际随包组件的许可文件。

[PyInstaller 官方说明](https://pyinstaller.org/en/stable/license.html)包含打包例外，允许在符合依赖许可的前提下选择所打包应用的许可证；不能仅因构建工具使用 GPL 就改变本项目许可，也不能据此忽略其他依赖条件。

## Python 分发包

版本和许可字段取自本轮本地安装元数据；包含测试／打包工具。lxml、Pillow、cryptography 等二进制 wheel 还可能带有其他组件的许可证，应查看完整随包文件。

| 分发包 | 版本 | 许可标识或随包说明 |
| --- | --- | --- |
| `alembic` | 1.20.0 | MIT |
| `altgraph` | 0.17.5 | MIT |
| `annotated-doc` | 0.0.5 | MIT |
| `annotated-types` | 0.8.0 | MIT |
| `anyio` | 4.15.1 | MIT |
| `bottle` | 0.13.4 | MIT |
| `certifi` | 2026.7.22 | MPL-2.0 |
| `cffi` | 2.1.1 | MIT-0 |
| `chinesecalendar` | 1.11.0 | MIT |
| `click` | 8.5.0 | BSD-3-Clause |
| `clr_loader` | 0.3.1 | MIT |
| `colorama` | 0.4.6 | BSD-3-Clause |
| `cryptography` | 50.0.1 | Apache-2.0 OR BSD-3-Clause |
| `fastapi` | 0.141.1 | MIT |
| `greenlet` | 3.5.6 | MIT AND PSF-2.0 |
| `h11` | 0.16.0 | MIT |
| `httpcore` | 1.0.9 | BSD-3-Clause |
| `httpx` | 0.28.1 | BSD-3-Clause |
| `idna` | 3.20 | BSD-3-Clause |
| `iniconfig` | 2.3.1 | MIT |
| `lxml` | 6.1.3 | BSD-3-Clause；另见包内 LICENSES.txt |
| `Mako` | 1.4.1 | MIT |
| `MarkupSafe` | 3.0.3 | BSD-3-Clause |
| `packaging` | 26.3 | Apache-2.0 OR BSD-2-Clause |
| `pefile` | 2024.8.26 | MIT |
| `pillow` | 13.0.0 | MIT-CMU |
| `pluggy` | 1.6.0 | MIT |
| `proxy_tools` | 0.1.0 | MIT |
| `pycparser` | 3.0 | BSD-3-Clause |
| `pydantic` | 2.13.5 | MIT |
| `pydantic-settings` | 2.15.0 | MIT |
| `pydantic_core` | 2.46.5 | MIT |
| `Pygments` | 2.21.0 | BSD-2-Clause |
| `pyinstaller` | 6.22.3 | GPL-2.0 + 打包例外；部分文件 Apache-2.0 |
| `pyinstaller-hooks-contrib` | 2026.8 | 按模块适用 Apache / GPL，见包内许可 |
| `PyMySQL` | 1.2.3 | MIT |
| `pytest` | 8.4.2 | MIT |
| `python-dotenv` | 1.2.3 | BSD-3-Clause |
| `pythonnet` | 3.2.1 | MIT |
| `pywebview` | 6.2.1 | BSD-3-Clause |
| `pywin32-ctypes` | 0.2.3 | BSD-3-Clause |
| `setuptools` | 84.0.0 | MIT |
| `SQLAlchemy` | 2.0.54 | MIT |
| `starlette` | 1.6.0 | BSD-3-Clause |
| `typing-inspection` | 0.4.4 | MIT |
| `typing_extensions` | 4.16.0 | PSF-2.0 |
| `uvicorn` | 0.53.0 | BSD-3-Clause |

Python 包内许可通常位于对应 `*.dist-info/licenses/` 或 `*.dist-info/`，不能仅保留包名而遗漏相关权利声明。

## 前端锁定依赖

许可字段来自当前 lock；同一上游库按不同平台或安装路径可能出现多项。`dev` 及可选依赖标签不等于最终打包内容清单。

| 锁定依赖 | 版本 | lock 中许可 |
| --- | --- | --- |
| `@babel/helper-string-parser` | 7.29.7 | MIT |
| `@babel/helper-validator-identifier` | 7.29.7 | MIT |
| `@babel/parser` | 7.29.9 | MIT |
| `@babel/types` | 7.29.8 | MIT |
| `@ctrl/tinycolor` | 4.2.1 | MIT |
| `@element-plus/icons-vue` | 2.3.2 | MIT |
| `@floating-ui/core` | 1.8.0 | MIT |
| `@floating-ui/dom` | 1.8.0 | MIT |
| `@floating-ui/utils` | 0.2.12 | MIT |
| `@jridgewell/sourcemap-codec` | 1.6.0 | MIT |
| `@oxc-project/types` | 0.150.0 | MIT |
| `@popperjs/core` | 2.11.8 | MIT |
| `@rolldown/binding-android-arm-eabi` | 1.2.9 | MIT |
| `@rolldown/binding-android-arm64` | 1.2.9 | MIT |
| `@rolldown/binding-darwin-arm64` | 1.2.9 | MIT |
| `@rolldown/binding-darwin-x64` | 1.2.9 | MIT |
| `@rolldown/binding-freebsd-x64` | 1.2.9 | MIT |
| `@rolldown/binding-linux-arm-gnueabihf` | 1.2.9 | MIT |
| `@rolldown/binding-linux-arm64-gnu` | 1.2.9 | MIT |
| `@rolldown/binding-linux-arm64-musl` | 1.2.9 | MIT |
| `@rolldown/binding-linux-ppc64-gnu` | 1.2.9 | MIT |
| `@rolldown/binding-linux-s390x-gnu` | 1.2.9 | MIT |
| `@rolldown/binding-linux-x64-gnu` | 1.2.9 | MIT |
| `@rolldown/binding-linux-x64-musl` | 1.2.9 | MIT |
| `@rolldown/binding-openharmony-arm64` | 1.2.9 | MIT |
| `@rolldown/binding-win32-arm64-msvc` | 1.2.9 | MIT |
| `@rolldown/binding-win32-x64-msvc` | 1.2.9 | MIT |
| `@rolldown/pluginutils` | 1.0.1 | MIT |
| `@types/lodash` | 4.17.25 | MIT |
| `@types/lodash-es` | 4.17.12 | MIT |
| `@types/node` | 22.20.4 | MIT |
| `@types/web-bluetooth` | 0.0.21 | MIT |
| `@vitejs/plugin-vue` | 6.0.9 | MIT |
| `@volar/language-core` | 2.4.28 | MIT |
| `@volar/source-map` | 2.4.28 | MIT |
| `@volar/typescript` | 2.4.28 | MIT |
| `@vue/compiler-core` | 3.5.43 | MIT |
| `@vue/compiler-dom` | 3.5.43 | MIT |
| `@vue/compiler-sfc` | 3.5.43 | MIT |
| `@vue/compiler-ssr` | 3.5.43 | MIT |
| `@vue/language-core` | 3.3.11 | MIT |
| `@vue/reactivity` | 3.5.43 | MIT |
| `@vue/runtime-core` | 3.5.43 | MIT |
| `@vue/runtime-dom` | 3.5.43 | MIT |
| `@vue/server-renderer` | 3.5.43 | MIT |
| `@vue/shared` | 3.5.43 | MIT |
| `@vueuse/core` | 15.0.0 | MIT |
| `@vueuse/metadata` | 15.0.0 | MIT |
| `@vueuse/shared` | 15.0.0 | MIT |
| `alien-signals` | 3.2.1 | MIT |
| `async-validator` | 4.2.5 | MIT |
| `csstype` | 3.2.3 | MIT |
| `dayjs` | 1.11.23 | MIT |
| `detect-libc` | 2.1.2 | Apache-2.0 |
| `element-plus` | 2.14.6 | MIT |
| `entities` | 7.0.1 | BSD-2-Clause |
| `estree-walker` | 2.0.2 | MIT |
| `fdir` | 6.5.0 | MIT |
| `fsevents` | 2.3.3 | MIT |
| `lightningcss` | 1.33.0 | MPL-2.0 |
| `lightningcss-android-arm64` | 1.33.0 | MPL-2.0 |
| `lightningcss-darwin-arm64` | 1.33.0 | MPL-2.0 |
| `lightningcss-darwin-x64` | 1.33.0 | MPL-2.0 |
| `lightningcss-freebsd-x64` | 1.33.0 | MPL-2.0 |
| `lightningcss-linux-arm-gnueabihf` | 1.33.0 | MPL-2.0 |
| `lightningcss-linux-arm64-gnu` | 1.33.0 | MPL-2.0 |
| `lightningcss-linux-arm64-musl` | 1.33.0 | MPL-2.0 |
| `lightningcss-linux-x64-gnu` | 1.33.0 | MPL-2.0 |
| `lightningcss-linux-x64-musl` | 1.33.0 | MPL-2.0 |
| `lightningcss-win32-arm64-msvc` | 1.33.0 | MPL-2.0 |
| `lightningcss-win32-x64-msvc` | 1.33.0 | MPL-2.0 |
| `lodash` | 4.18.1 | MIT |
| `lodash-es` | 4.18.1 | MIT |
| `lodash-unified` | 1.0.3 | MIT |
| `magic-string` | 0.30.21 | MIT |
| `memoize-one` | 6.0.0 | MIT |
| `muggle-string` | 0.4.1 | MIT |
| `nanoid` | 3.3.19 | MIT |
| `normalize-wheel-es` | 1.2.0 | BSD-3-Clause |
| `path-browserify` | 1.0.1 | MIT |
| `picocolors` | 1.1.1 | ISC |
| `picomatch` | 4.0.7 | MIT |
| `postcss` | 8.5.28 | MIT |
| `rolldown` | 1.2.9 | MIT |
| `source-map-js` | 1.2.1 | BSD-3-Clause |
| `tinyglobby` | 0.2.17 | MIT |
| `typescript` | 5.9.3 | Apache-2.0 |
| `undici-types` | 6.21.0 | MIT |
| `vite` | 8.3.0 | MIT |
| `vscode-uri` | 3.2.0 | MIT |
| `vue` | 3.5.43 | MIT |
| `vue-component-type-helpers` | 3.3.11 | MIT |
| `vue-tsc` | 3.3.11 | MIT |

前端各包的完整许可见对应上游版本及安装包内 LICENSE / NOTICE；如实际分发构建产物，须按最终包含的代码保留所需声明。
