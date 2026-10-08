# 本地 MVP 消息浏览契约 v1（兼容扩展）

既有 RPC 方法及 `items` 保持兼容；本契约先于本次实现定义，完整领域 M01 仍以 README 任务卡为准。

- `conversation.list`：原有 query/limit/account_id/platform；新增可选 `cursor: {updated_at: integer, id: string}`。返回 `items, has_more, next_cursor`，按更新时间、ID 倒序。query 匹配会话名、联系人名、QQ/群号。
- `message.list`：conversation_id、limit（1–300，默认100）；新增 account_id/platform、query、sender、direction、cursor。query 字面包含匹配正文、发送者名/QQ、会话名/QQ；sender 匹配发送者名、QQ、UID；direction 为 incoming/outgoing/system/unknown 或空串。
- `message.search`：query，可带同上筛选、可选 conversation_id，默认80条。空 query 可浏览当前账号全部已导入消息。
- 消息 cursor 为 `{sent_at: integer, id: string}`；按时间、ID 倒序选取下一批，`message.list.items` 在每页内正序，`message.search.items` 倒序（保持旧行为）。返回 `has_more, next_cursor`；耗尽为 false/null。游标不改变账号、会话及筛选范围；无 OFFSET。无效参数返回 INVALID_PARAMS。
- 桌面 `prepareSource` 新增 `syncOnline: boolean`（默认 false），关闭 QQ 后读取本地已有记录；true 才启动 QQ 等待联网同步。数据库静止不代表服务端历史已完整下载。
- 核心通知 `source.progress`：params 只含 message（阶段、计数，不含正文、账号、路径或密钥）。主进程向当前操作转发进度；进入核心解密/导入阶段标记 cancellable=false。

验收：合成数据跨越100条、同时间多页无遗漏重复；筛选在分页前执行；账号隔离；无结果/末页；无效游标；快速本地模式不启动 QQ；SHM变化不延长消息同步；首次导入全文索引无需逐行扫描。
