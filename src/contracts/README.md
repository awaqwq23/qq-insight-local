# 当前接口说明

- history-v1.md：消息历史、分页与账号范围。
- import-v1.md：增量导入与资料更新。
- transfer-v1.md：手动导入和备份。
- workspace-v2.md：收藏、上下文与群设置。
- ai-v3.md：当前群 AI、调用历史与长期记忆；继承字段参见 ai-v2.md。

入口在 src/core/local_assistant/service.py，配套桌面受限 IPC。修改接口同步消费者与测试。
