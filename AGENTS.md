# 开发规则

当前项目已实现，不再使用历史骨架任务卡。先读 README.md 与 docs/architecture.md。

1. 范围限于 QQ 本地记录，不扩展自动发消息。
2. 不写源 QQ 数据库。真实数据库、密钥、正文、账号、媒体及 API Key 不进入提交、夹具或日志。
3. 核心在 src/core/local_assistant，桌面在 src/desktop；跨边界修改同步契约与测试。
4. 群角色、历史和长期记忆按账号、会话隔离；模型输出须校验证据、范围和预算。
5. 版本同步 package.json、锁文件、核心 health、界面页脚。当前 0.5.0-rel。
6. 发布须通过合成核心、桌面、界面和打包测试，不能宣称真实模型效果或在线 QQ 已验收。
7. tools、data、build、release、node_modules 不提交；第三方助手遵守原许可证，不打入便携包。
