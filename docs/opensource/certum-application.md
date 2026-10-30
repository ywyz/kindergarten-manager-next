# Certum Open Source 申请资料

核对日期：2026-10-30。项目维护者已决定先以 MIT 开源版本推进，当前继续源码验证。本文只整理申请资料，不表示证书已购买、签发，或新包已获 Windows 放行。

## 项目公开资料

以下链接须在相关文件经审阅并提交推送、网页确认可见后才作为申请证据使用，不能以本地草稿替代公开页面。

| 用途 | 链接 |
| --- | --- |
| 项目仓库与所有者 | [ywyz/kindergarten-manager-next](https://github.com/ywyz/kindergarten-manager-next) |
| 当前桌面版及 README | 默认分支 [main](https://github.com/ywyz/kindergarten-manager-next/tree/main) |
| 开源许可 | [MIT LICENSE](https://github.com/ywyz/kindergarten-manager-next/blob/main/LICENSE) |
| 维护者与项目关系 | [MAINTAINERS.md](https://github.com/ywyz/kindergarten-manager-next/blob/main/MAINTAINERS.md) |
| 维护者 GitHub 账号 | [ywyz](https://github.com/ywyz) |

本页公开证据链接指向默认 `main`；后续桌面开发继续在 [`codex/desktop-v2-foundation`](https://github.com/ywyz/kindergarten-manager-next/tree/codex/desktop-v2-foundation) 分支进行。公开账号不等于已核验实名；若申请姓名与公开账号不同，向 Certum 确认还需何种署名或项目关系证明，再由申请人提供适当信息。

## 申请人私下准备

按 [Certum 官方材料清单](https://support.certum.eu/en/code-signing-required-documents/)，开源款面向个人，要求身份核验、本人抬头的水电燃气或电话等账单，以及公开可核验的开源项目和申请人与项目的关系。使用所选核验途径提交材料，不是默认同时要求所有途径或公证。

付款前向官方确认：中国大陆自然人及所持证件是否受理；中文账单的格式、时效、姓名／住址要求及可接受替代材料；是否需要翻译或公证；核验失败的处理和退款条款。证件、账单、手机验证码、签名私钥和激活信息不得进入仓库或 Issue。

## 产品和签名安排

当前优先研究 [Open Source Code Signing in the Cloud](https://shop.certum.eu/open-source-code-signing-on-simplysign.html)。官网起价 €49，使用 SimplySign 手机及桌面客户端、云端密钥和网络，标明每月最多 5000 次签名。不是每月 5000 个完整发行包的承诺；申请前确认实际可购套餐、税费、大陆网络可用性及计次规则。

官网的 €25 电子激活码适用于已有兼容卡和读卡器的客户，不是新用户云签全套价格。相关商品见 [官方列表](https://shop.certum.eu/code-signing.html)。本轮不安装签名工具、购买或提交材料。

MIT 允许商业用途，与 Certum 开源证书的用途限制分别处理。Certum 规定将该证书用于商业分发可能撤销证书；未来商业版本应另用适当证书，不能仅通过 fork 改变证书用途限制。

证书具备后，还须核查签名文件范围、第三方二进制许可、有效供应商签名及时间戳，再补冻结入口、图片、AI、Word／原生保存、重启和关闭等整包验证。当前源码验证或申请资料齐备均不等于新冻结包验收通过。

## 可用于申请表的项目简介

> kindergarten-manager-next is a personal open-source Windows desktop project maintained by the GitHub account ywyz. It helps kindergarten teachers prepare daily activity plans and game observation records, with local storage, version history, Word export and optional user-configured AI services. Original project content is licensed under MIT. The current desktop source is on the default main branch and is currently verified from source; a stable signed desktop release is not available yet. The project has no commercial distribution plan at this stage.

用户已确认清理后的受控模板具备公开分发及 MIT 授权。提交前仍以 [开源准备检查记录](../bootstrap/open-source-readiness-review.md) 中当前文件验证、公开 Git 历史和维护者实名关联的实际状态为准。
