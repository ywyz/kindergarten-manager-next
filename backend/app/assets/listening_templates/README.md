# 一对一倾听固定 Word 模板资产

这十五个文件是一对一倾听 L1 的受控运行时模板。教师已确认这些空表由本人制作或已取得公开分发及 MIT 许可其版式的权利。原件位于教师本机私有目录，仓库只保存清理后的副本；原件、历史成品和真实幼儿资料均不在仓库内。

## 清理范围

- 只清理个人文档属性、自定义文档属性及其关系：替换 `docProps/core.xml` 为无作者、无最后修改者的固定属性；删除 `docProps/custom.xml` 及其内容类型与包关系。
- `word/document.xml` 与原件逐字节相同，表格结构、合并格、列宽、行高、段落属性、纸型、页边距和全部评价原文均未改动。
- 逐份检查所有 `.rels`，没有外部关系链接。
- 不记录真实幼儿姓名、照片、班级或本机绝对路径；`source_name` 只是教师提供的空表文件名，用于内部对照。

## 版本与评价项

- 当前默认版本为 `v1`；旧版本目录不删除。记录创建时固定模板版本和 SHA-256，读取旧记录时按存储版本取模板，不静默回退最新版本。
- 评价项编号在“年级 × 领域 × 版本”内稳定，例如 `health_1`；`manifest.json` 保存逐项逐档原文。评价项数量以这十五份空表的实际原文为准：
  - 小班：健康 7、语言 6、社会 7、科学 6、艺术 4。
  - 中班：健康 6、语言 6、社会 7、科学 6、艺术 4。
  - 大班：健康 6、语言 6、社会 7、科学 6、艺术 4。
- 表头观察日期和三组作品日期在业务表中保存为可空文本，保留观察时段及“月 日”原文，不强行补年份。

## 受控资产

| 资产 | 年级 | 领域 | 评价项 | SHA-256 |
| --- | --- | --- | --- | --- |
| `v1/small_health.docx` | 小班 | 健康 | 7 | `7aba970b090f00a95b59dab79179d42aad69aff6a5c835e570e286c450953faa` |
| `v1/small_language.docx` | 小班 | 语言 | 6 | `e3aa239a7cdcf16045ca0313d592c317f9ba8a37d371f0106fc8d8b5a37ffbb1` |
| `v1/small_social.docx` | 小班 | 社会 | 7 | `64e99d5120678fc3cd9f075349ae6a2141c5807ab887904ecd4ebb43c7c9b3a1` |
| `v1/small_science.docx` | 小班 | 科学 | 6 | `a66d1ba8f14835928b68de7c222d9964c6adaa7c8e26d8c2a63c8a46a3aed47b` |
| `v1/small_art.docx` | 小班 | 艺术 | 4 | `6d95f65576901de5d749f11ea4d48aa3938367c16308e328c4894beb7ab85283` |
| `v1/middle_health.docx` | 中班 | 健康 | 6 | `0eabb1bf76dd33f2ce90f951c48256ecbad8663d85f5f1a29572621412850428` |
| `v1/middle_language.docx` | 中班 | 语言 | 6 | `8ee8023b9ad0ad829183e02524021d3032c93dabe986f92531ef751dae457008` |
| `v1/middle_social.docx` | 中班 | 社会 | 7 | `76a44d871e3bc052fb93c70430b984bf412e9da9b4958412b373820d9a170ab6` |
| `v1/middle_science.docx` | 中班 | 科学 | 6 | `dff3369273f016a35bdd66fe79348b07ccdff42072244c2f7f7d7ffaa8bdc228` |
| `v1/middle_art.docx` | 中班 | 艺术 | 4 | `790a9f3c922c50d19d803b898aac641646318b51873f419561a7f8f31c74ec19` |
| `v1/large_health.docx` | 大班 | 健康 | 6 | `160a00430b2ae1c207ab977906b579c724d40fb267d98658902c99e9b373b391` |
| `v1/large_language.docx` | 大班 | 语言 | 6 | `9573e8c0476a94de14cef479c36b98e434d7ce0c4c9099148fabcd0ba8c8ca91` |
| `v1/large_social.docx` | 大班 | 社会 | 7 | `2e49dac212d28b7b95ae12a5547c52ccab5f63d3f52425cb524e185fe9042b95` |
| `v1/large_science.docx` | 大班 | 科学 | 6 | `d79bfc4058c3a4b65da76d4793050fe37aeff27bc72f977127c9f89a5ac765ea` |
| `v1/large_art.docx` | 大班 | 艺术 | 4 | `c8d68a0d9cfb582258fd38d9afea7892f47bdd4911b8319a85b71a8449a7fddf` |
