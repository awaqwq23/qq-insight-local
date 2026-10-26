# 第三方组件、许可证与致谢

本清单针对 QQ Insight 0.18.2-rel 的实际构建，核查日期为2026-10-27。本项目自有代码采用 [MIT](LICENSE)，第三方的版权、许可、例外及商标权仍分别保留，不因本项目采用MIT而改变。

## 程序与发行包中的组件

| 项目及来源 | 本次版本 | 用途与分发范围 | 许可证与原文 |
| --- | --- | --- | --- |
| [Electron](https://github.com/electron/electron/tree/v37.10.3)，Electron贡献者/GitHub | 37.10.3 | 桌面运行时，包含Chromium、Node.js、V8等组件 | [MIT原文](licenses/Electron-37.10.3.txt)；子组件原文见同版本运行时的`LICENSES.chromium.html` |
| [CPython](https://www.python.org/downloads/release/python-3140/)，Python Software Foundation及历史贡献者 | 3.14.0 | 核心解释器、标准库及Windows二进制依赖 | [Python许可和随包声明](licenses/CPython-3.14.0.txt)，包括历史许可及Windows附加条件 |
| [sqlcipher3](https://github.com/coleifer/sqlcipher3/tree/0.6.2)，Gerhard Häring、Charles Leifer及贡献者 | 0.6.2 | Python SQLCipher绑定 | [安装包实际许可正文](licenses/sqlcipher3-0.6.2.txt)为zlib风格；该版本元数据另标MIT，本清单保留原文并明确此差异 |
| [SQLCipher Community](https://github.com/sqlcipher/sqlcipher/tree/v4.12.0)，ZETETIC LLC | 4.12.0 | 加密SQLite支持，包含在绑定二进制中 | [BSD-style原文](licenses/SQLCipher-4.12.0.txt)；This product includes software developed by ZETETIC LLC |
| [SQLite](https://www.sqlite.org/copyright.html)，SQLite项目 | CPython: 3.50.4；SQLCipher底层: 3.51.1 | 本地查询、索引与备份 | 上游声明Public Domain；This product includes software developed by the SQLite Project |
| [OpenSSL](https://github.com/openssl/openssl/tree/openssl-3.0.18)，OpenSSL Project及贡献者 | 3.0.18 | CPython构建中的libssl/libcrypto | [Apache-2.0原文](licenses/OpenSSL-3.0.18.txt)；This product includes software developed by the OpenSSL Project |
| [NSIS](https://nsis.sourceforge.io/)，NSIS贡献者 | 构建工具包3.0.4.1 | 便携EXE的解包启动封装 | [随工具分发的COPYING](licenses/NSIS-3.0.4.1.txt)：核心zlib/libpng，压缩模块另含bzip2/CPL条款；源码见[NSIS源代码入口](https://nsis.sourceforge.io/Development_Files)及[electron-builder工具集](https://github.com/electron-userland/electron-builder-binaries) |
| [StdUtils](https://github.com/lordmulder/stdutils)，LoRd_MuldeR | 随nsis-resources 3.4.1提供 | NSIS独立插件，未修改其DLL | [LGPL-2.1-or-later](licenses/StdUtils-LGPL-2.1.txt)及[作者关于安装器的澄清](licenses/StdUtils-LGPL-clarification.txt)；插件源码在上游仓库 |
| [Nsis7z](https://nsis.sourceforge.io/Nsis7z_plug-in)，Nik Medved、Igor Pavlov等 | 随nsis-resources 3.4.1提供 | 解包插件，未修改；缓存包版本不等于插件独立版本 | 上游说明遵循7-Zip许可，保留[LGPL文本](licenses/7-Zip-LGPL.txt)和[7-Zip许可说明](licenses/7-Zip-toolset-1.0.0.txt)；源码下载见项目页面 |

Electron内的Chromium、Node.js、V8、FFmpeg、ICU、BoringSSL等各自许可，不统一标作MIT。发行程序保留完整`LICENSES.chromium.html`和`LICENSE.electron.txt`；前者来自[Electron 37.10.3官方分发](https://github.com/electron/electron/releases/tag/v37.10.3)。Python附带的libffi、bzip2、zstd等声明及Microsoft运行库条件保留在CPython原文中；Microsoft组件与第三方商标不属于本项目MIT授权。

在程序“设置 → 许可证与致谢”打开离线说明。便携运行目录中，本文位于`resources/legal/THIRD_PARTY_NOTICES.txt`，完整许可在同目录的`licenses/`，Electron完整声明在运行目录的`LICENSES.chromium.html`。发行页另附独立许可ZIP，包含本文、本项目LICENSE、许可原文和完整Electron声明。

## 构建工具与开发依赖

| 项目 | 本次版本/范围 | 用途 | 许可 |
| --- | --- | --- | --- |
| [electron-builder](https://github.com/electron-userland/electron-builder) | 26.15.3 | 生成Windows便携发行包 | [MIT](licenses/electron-builder-26.15.3.txt)；其NSIS/插件分别见上表 |
| [PyInstaller](https://github.com/pyinstaller/pyinstaller/tree/v6.22.3) | 6.22.3 | 生成单文件Python核心 | [GPL-2.0-or-later及bootloader例外/部分Apache-2.0](licenses/PyInstaller-6.22.3.txt)；[官方说明](https://pyinstaller.org/en/stable/license.html)允许产物遵循其自身及依赖许可，不能省略依赖许可 |
| [pyinstaller-hooks-contrib](https://github.com/pyinstaller/pyinstaller-hooks-contrib) | 2026.7 | 构建时依赖分析 | [标准hooks GPL-2.0-or-later；runtime hooks Apache-2.0](licenses/PyInstaller-hooks-contrib-2026.7.txt) |
| [7-Zip](https://www.7-zip.org/)，Igor Pavlov及贡献者 | electron-builder工具包1.0.0 | 构建归档工具，非完整7-Zip程序的应用运行依赖 | [原始说明](licenses/7-Zip-toolset-1.0.0.txt)及[LGPL正文](licenses/7-Zip-LGPL.txt)，部分文件有单独条款 |

[依赖版本清单](licenses/dependency-inventory.json)列出package-lock中的320个npm开发依赖和Python构建包的许可元数据，包含版本与来源；它不表示这些包全部进入运行程序。冻结核心的第三方Python模块为sqlcipher3和PyInstaller runtime hook，其他主要为标准库。元数据不能代替许可原文：sqlcipher3的差异已单独说明，其他组件以随包原文为准。

## 可选外部工具与技术参考

| 项目及作者 | 本项目借助的内容 | 分发与许可边界 |
| --- | --- | --- |
| [qq-win-db-key](https://github.com/QQBackup/qq-win-db-key)，LY/Young-Lord及QQBackup贡献者 | 自动读取功能调用用户另行准备的NTQQ密钥助手 | **不进入源码仓库或便携包**。采用[自定义非商用许可第1版](https://github.com/QQBackup/qq-win-db-key/blob/master/LICENSE)，不是MIT；使用和修改须独立遵守其原文及文件声明 |
| [QQDecrypt](https://github.com/QQBackup/QQDecrypt)，LY/Young-Lord及QQBackup贡献者 | QQ数据库解密与格式研究资料入口 | 通过链接引用，不捆绑文档；[上游自定义非商用许可](https://github.com/QQBackup/QQDecrypt/blob/main/LICENSE)独立保留 |
| [CC Switch](https://github.com/farion1231/cc-switch)，Jason Young | API设置界面的集中配置管理思路参考 | 当前是独立界面实现，不是运行依赖；致谢并保留[上游MIT声明](licenses/CC-Switch-MIT.txt) |

本项目自有代码的MIT授权不替代取钥助手的非商用限制，也不暗示第三方作者为本项目背书。QQ、微信等名称和标识归相应权利人；本项目不是腾讯官方产品。

## 维护方式

许可原文保持原样，来源及SHA256保存在[manifest.json](licenses/manifest.json)。更新依赖时核对实际安装版本、冻结核心和发行资源，再更新清单及许可原文；不能只更改表格标签。构建脚本验证内容哈希并打入发行包，发布检查再次核对包内文件，不能把“源码公开”当作已经有开源许可证。
