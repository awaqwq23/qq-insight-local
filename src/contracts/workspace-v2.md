# 本地工作台契约 v2（0.2.0-rel）

涉及 M02/M03/M04/M07/M08/M09/M10/M11：排序、定位、QQ 解码、媒体收藏和跨设备合并需要共享消息标识、账号范围及备份格式。先冻结本扩展，再同步实现与验收。旧接口省略新增参数时保持 v1 行为。

- message.list/search 新增 `order=asc|desc`，显式指定后返回及游标均遵循该顺序；limit 上限 500。recent=true 先取筛选后最新 limit 条再按所选顺序显示，不改变全历史查询语义。桌面设置 `messagePageSize` 为 20–500 的整数，默认 100，只影响全部分页。
- message.context(message_id,account_id,platform,limit=50,order=asc)：返回目标所属会话及前后记录，明确 target_id。必须校验账号范围；桌面清除旧筛选并高亮、滚动到目标，不仅打开会话。
- message.repair(account_id,platform)：批量重新解析应用库保存的 raw_blob，更新投影与全文索引，不写源 QQ 库；不把缺失正文覆盖到现有完整正文。
- conversation.pin(conversation_id,pinned,account_id,platform)：只更新应用库。conversation.list 按 pinned、updated_at、id 倒序；游标新增 pinned（旧游标按 0 处理）。
- profile.get/save 新增可选 conversation_id、account_id/platform：群角色单独保存，未设置时回退全局角色。工作线索逐会话使用有效角色并排除单纯“姓名+收到/好的”等确认回复；引用文本不作为发送者自己的任务承诺。
- favorite.set(message_id,enabled,account_id,platform,media_index=-1)：-1 为消息收藏；非负为图片收藏，必须成功读取并保存图片才报告成功。favorite.list 按当前账号分页，order=asc|desc 按消息时间排序（默认 desc），支持正文/人名/QQ/会话筛选；消息 DTO 附 favorite 与每张图片的收藏状态。图片以内容 SHA-256 去重，保存在应用数据目录 favorites/media；可打开该目录。
- media.read(message_id,media_index,account_id,platform)：只能按已导入消息取图片，返回经过文件类型/大小校验的 data URL 或明确缺失结果，不能按 renderer 任意路径读文件。media.configure_roots 为主进程文件夹选择器授权入口；按账号保存目录，按原路径、缓存相对路径、MD5/文件名恢复，限制扫描数量并跳过链接。不自动请求带令牌的外网 CDN。
- SQLite 备份新增可选 media_assets/message_media/favorites/conversation_preferences 表；可携带本机可读取的图片，报告实际打包与缺失数量。旧格式无新增表仍能导入；媒体随 DB 合并后无需依赖旧电脑绝对路径。源库、凭据不写入。
- 跨电脑合并使用账号+会话+协议序号/随机数/时间的保守复合标识；缺少足够依据不按相同文本合并。原消息 ID 保持可定位；别名映射到同一记录。不让缺失正文覆盖已有正文，媒体引用取并集。不同非空正文保留冲突副本。备份可显式指定来源账号与目标账号进行绑定，不按昵称猜测同一账号。
- QQ 解析修正段类型，读取嵌套引用、灰条 XML、兼容直接消息段，显示内容来源；读取不到正文时明确提示本地未缓存，不能伪造正文。提高投影版本，重解析已导入原始消息体，并在后续源库更新读取更多可用缓存字段。

验收：双向排序含筛选及同时间分页、设置持久化、跨页上下文/账号隔离、收藏取消与图片落盘、群置顶分页、每群角色、确认回复过滤、引用/灰条结构、路径特殊字符与移机图片恢复、双设备重叠/冲突/缺媒体/旧备份兼容、原子回滚。真实未下载的历史及失效缓存无法由应用凭空恢复。
