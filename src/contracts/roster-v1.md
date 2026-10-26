# 本地名单导出 v1（0.9.0-rel）

- UI：会话列表上方“导出群列表（原名／备注）”；当前群消息顶部“导出发言成员”。
- preload `exportRoster({account_id,platform:'qq',kind:'groups'|'members',conversation_id})` → 专用 `roster:export` IPC → 主进程原生保存对话框 → 私有核心 RPC `roster.export`。
- 路径仅接受主进程保存对话框的选择，不接收渲染器路径；`roster.export` 不在通用 renderer RPC 白名单。
- 核心参数增加 `path`，只允许 `.csv`，不覆盖已有文件；临时文件写完再无覆盖发布。返回 `{status:'exported',count,kind,note}`；原生对话框取消返回 `null`。
- CSV：UTF-8 BOM，标准 CSV 引号／换行转义，可能被表格执行的公式前缀加单引号；中文可直接由 Excel 打开。QQ号与UID保留字符串，表格软件若自动转数字可按文本导入。
- groups：当前账号 qq_groups 与已导入 group 会话的并集，群号去重；列为群号、群原名称、群备注名称、历史显示名称、数据范围。无资料时原名称／备注留空，显示名不得冒充原名。
- members：仅当前账号当前群历史发言者，不是完整或实时成员表，可能含已退群成员，不含无发言记录者。QQ号优先去重，无QQ号用UID；同群UID到QQ号唯一映射可补齐，不按昵称合并。系统方向和没有身份标识的消息不作成员。
- 成员列：群号、群显示名称、QQ号、UID、QQ原昵称、群名片（群内备注）、历史显示名称、数据范围。按消息时间倒序取最近非空昵称／群名片，原昵称缺失可用本账号 qq_profiles.nickname；私人备注 remark 与合并显示名不冒充原昵称或群名片。各列历史观测时间可能不同，不声称当前有效。
- 新增 messages.sender_nickname / sender_card，分别独立保存群消息 40093 / 40090。字段依据为上游数据库分析文档，版本可能存在差异：[QQBackup 群消息字段说明](https://github.com/QQBackup/nt_msg_db_util/blob/master/db_docs/group_msg_table/summary.md)。私聊字段不按群语义解释。
- PROJECTION_VERSION=6：下次导入原始 QQ 库触发全量投影重建，恢复旧版合并丢失的双名称。升级不会自行读取原QQ库；旧版仅有显示名时导出两列留空，提示先更新或重新导入。
- 备份新字段随整库导出；合并时支持旧备份缺列默认空，新备份可为已存在消息补齐缺失名称。
- 测试仅合成资料；不联网、不发消息、不写源QQ库，不在提交或日志中包含真实名单。
