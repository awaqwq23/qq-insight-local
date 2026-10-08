# QQ Insight

当前版本：**0.5.0-rel**，Windows x64 便携版，默认普通用户权限。

运行 `release/QQ-Insight-0.5.0-rel-portable.exe`，无需安装 Python 或 Node.js。
支持 QQ 本地记录导入、增量更新、搜索、收藏、备份及群 AI 分析。

- “我的角色”位于群设置，按群独立保存，可让 AI 分析消息并回填。
- 每次分析保留独立历史卡片，显示时间、范围、数量、耗时和分块，点击查看分页详情。
- 特别关注可用逗号填写多个 QQ，逐人分析和总结；群与成员长期记忆供后续分析读取、完善。

## 目录

- src/core：Python 核心，local_assistant 为实际业务，tests 为合成测试。
- src/desktop：Electron 主进程、预加载及界面。
- src/contracts：当前接口说明。
- tests：桌面、界面、打包验证及可复用合成基准。
- scripts：可复用构建与验证脚本。
- docs：当前架构和发布验证。
- release：仅当前便携包与 SHA256，不提交源码仓库。
- tools：本机 Node 与 QQ 密钥助手，不上传。
- data：原始聊天库、备份和个人文件，不上传。
- build、node_modules：可重新生成的构建输出及依赖，不上传。

## 使用安全

自动取钥需要用户已有的 qq-win-db-key-master，放入 tools 或便携程序旁，也可用 QQ_INSIGHT_KEY_HELPER 指定脚本。
该助手遵守原许可证，不复制进便携包或上传仓库。操作前备份源记录，只处理获授权的数据。
应用不写源 QQ 数据库；整理项目不删除 Windows 用户应用数据目录中的已导入记录、API 设置。
AI 操作将选定消息发送至用户配置的模型服务，请检查授权、消息范围和预算。

## 开发与构建

使用 Node.js 24、Python 3.14：

```powershell
npm ci
python -m pip install -r src/core/requirements-build.txt
$env:QQ_INSIGHT_PYTHON = (Get-Command python).Source
npm start
$env:PYTHONPATH = "$PWD/src/core"
python -m unittest discover -s src/core/tests -v
npm run test:desktop
./scripts/build_core.ps1 -Python python
npm run dist
python tests/packaged-core-smoke.py
```

package.json 中的 test:*ui 为界面测试。live 测试可能产生 API 费用，不默认运行。
版本规则：小修递增第三位，大功能递增第二位并清零第三位；同步包、锁文件、核心 health、界面页脚。
