# 当前架构

0.18.2-rel增加MIT自有代码许可和第三方声明。scripts/prepare-license-bundle.cjs在predist按manifest验证原文SHA256并生成build/legal，作为extraResources进入便携包；Electron原有完整Chromium声明保留。设置通过专用licenses:open IPC打开固定本地说明，不给模型或渲染层任意文件路径权限；包内实际IPC及文件一致性验证覆盖此入口。

0.18.1-rel增加workspace.chat.recent，复用workspace_sessions/runs与ai_jobs按账号联表汇总主题及旧分析，过滤内部压缩和分批任务；无新表。renderer/ai-history负责分页、迟到响应防护及原session/job导航，主进程只增加此只读RPC白名单。AI聊天收紧三级导航，主题列表改为原生details菜单，正文及输入16px、减少留白；契约见src/contracts/ai-history-v1.md。

Electron 主进程管理窗口、授权、模型 API、加密设置与 QQ 进程协作；界面通过受限 IPC 调用。
Python 核心通过标准输入输出 JSON-RPC 负责导入、SQLite 索引、搜索、收藏、备份及群 AI 状态。

src/core/local_assistant 按存储、导入、协议解析、媒体、工作台、AI、预算和备份划分模块。
群角色只取对应群设置，不继承全局角色。每次分析独立任务、分块和历史快照。
AI 请求包含本群长期记忆；完成后更新群和成员记忆，多目标特别关注逐人隔离消息和总结。
AI 推断不能提升为已确认事实，证据、账号范围和预算仍须验证。

桌面的 model-limits 管理主模型上下文、输出和 TPM 配置；model-capacity-test 使用受限合成样本探测成功下限，所有请求进入核心用量账本。核心 ai.next 在预算预占前检查完整请求并继续拆分，桌面 model-rate-limit 在已配置 TPM 时等待安全额度恢复。接口元数据、官方快照、手动额度和实测下限分别标注来源，容量契约见 src/contracts/ai-v4.md。

ai_compression 在本地生成可选有损压缩材料，保留本段别名到原消息的映射；发送压缩后的Prompt但保存原始分块，提交时只接受已提供的别名，恢复为原消息后进行原有证据校验。输出字数和压缩模式随任务冻结，计入缓存指纹。压缩统计和损失说明保留到历史及长期记忆，契约见 src/contracts/ai-v5.md。

应用仍使用原 Windows userData，data 只是整理前已有源库与备份。
文字模型按配置走 Chat Completions、Anthropic Messages 或 Responses。Responses 解析有界 SSE，仅以完整终态结算；原文与压缩模式均通过任务冻结的证据编号映射验证来源。已标明容量来源的大上下文可扩大计划分块，完整请求、预算及TPM检查仍在每次调用前执行，见 src/contracts/ai-v6.md。
可选分段汇总在ai_chunks内保存带层数和子节点的摘要树，每个节点独立预算、验证和结算；最终使用已完成树的最上层结果，未完成汇总不能标记成功。各分析功能和关注对象隔离共享此流程，契约见 src/contracts/ai-v7.md。
official-pricing按准确模型名称匹配发布方官方价，所有端点共用参考快照；ai_accounting按请求开始时间、输入门槛、缓存读取/写入结算。启动时由主进程私有RPC补算以前没有定价的历史，不改已存在定价或用量。月费用预算只约束估算金额，契约见 src/contracts/ai-v8.md。
自动取钥查找 tools/qq-win-db-key-master，同时兼容程序旁旧位置和环境变量。
源码仓库不含个人数据、第三方助手、依赖和构建缓存。

roster.export 通过专用名单导出 IPC 与原生保存对话框访问，核心以账号／群为边界生成 UTF-8 CSV；群成员仅指历史发言者。新投影分别保存原昵称与群名片，旧数据需重导入补齐，见 src/contracts/roster-v1.md。

用户明确授权的 roster:export-full 在独立临时官网窗口只读获取成员，不复用或保存网页登录凭据；主进程核对账号、群号、完整分页，核心二次校验后复用CSV写入。远端窗口无Node和preload、管理写请求拦截；不把名单发给模型或写回源库，见 src/contracts/roster-v2.md。

member_cache导入群资料库group_member3，按账号/群保存独立成员快照。roster.cache_info通过名单专用IPC核对数量与导入版本；缓存导出包含未发言者，无需管理员/官网，完整性未知或数量不一致明确标注，见src/contracts/roster-v3.md。

0.12.0-rel 在原分块调度器内新增 style 任务：明确账号与QQ/UID跨已导入群采样，分段汇总为可复制风格Prompt；跨群风格记忆与普通群记忆分开。所有模型输入采用分钟时间与短编号表，off仍完整保留正文/引用。结果中的 people_memory 校验本人发言来源后写入来源群记忆，观察不足只保存出处；锁定纠正优先。失败历史删除保留最小账本归属，避免费用消失。详见 src/contracts/ai-v9.md。

0.13.0-rel 增加workspace_agent受控本地工具、持久任务和文件表，全局入口直接按自然语言选工具，主进程独立负责联网和识图；核心固定账号及群聊/私聊范围，默认群聊，旧私聊答案不进入新的群聊问题。每次成功分析更新来源群事实与暂定评价；跨会话人物综合观察不复制到单群记忆。ai_context保存带来源哈希的摘要，命中后只读增量并汇总，来源改变回源，精确任务仍读取原文/SQL。缓存、历史、文件加入备份，账本支持全局任务。契约见src/contracts/ai-v10.md，完整需求见docs/requirements.md。

0.13.1-rel将设置按模型、预算/用量、数据/账号分组，settings.js控制分组与单项编辑呈现，renderer.js沿用配置保存和模型发现接口；媒体仍独立配置。协议和容量仅折叠展示，不修改原数据格式，见src/contracts/settings-v1.md。

0.14.0-rel新增workspace_sessions与workspace_turns，将既有任务关联为账号内独立对话及不可变分支。前情只取当前对话当前分支，受本轮群聊/私聊范围和请求容量约束；chat_history可回读当前分支旧回答。编辑/重生成不覆盖旧run、附件或账本，新增表纳入备份与归属/无环校验。界面按对话展示并屏蔽切换后的迟到响应，详见src/contracts/ai-v11.md。

0.14.1-rel由attachConversationActions统一构建消息页操作区，以原生details收纳辅助功能，保留一个常用AI入口。未选群、私聊及全账号范围不绑定成员操作；菜单绑定时冻结账号/会话并在执行前复核。导出IPC、核心格式和权限契约不变。

0.15.0-rel复用workspace_sessions/turns，将conversation_id固定到群或私聊，界面workspace-agent与chat-memory共用聊天与设置；全局conversation_id为空。chat_memory负责三类逻辑记忆、来源哈希摘录、精确覆盖区间、人工与学习背景分离、本人资料和私聊身份。模型先选择工具、纯回复不读取原库；画像必须原文、普通任务按需复用、修改仅经受控方法。附件由原生文件选择器进入应用自有表，按当前分支读取，识图/语音经独立计量调用。所有新增数据随备份验证归属及内容，契约ai-v12.md。

0.16.0-rel增加共用context-memory压缩调度，workspace.context.commit/ai.context按冻结哈希独立保存feature=context的任务无关摘要。先复用、再压缩增量、最后执行目标；直接聊天不必读库，SQL统计/顺序保持精确。ChatMemory.record维护来源痕迹，workspace消息投影与任务历史显示压缩进度；人物可选观察逐条拒绝且不牵连合法结果。MediaStore索引有时效，images先探测本机像素、近期优先及去重，保存数量未达标不冒充完成。见ai-v13.md。

0.17.0-rel在run.context_json持久化task及source_scope，用户补充绑定当前分支的原始请求。search_messages复用受控投影按账号/类型/时间跨会话批量检索，今日私聊文件任务预载活跃记录；finish核验覆盖及文件目标。短材料直接原文，长材料按需复用/压缩；export_messages通过已核验来源生成逐字正文，禁止write_markdown替代原话导出。覆盖含原文与摘要，UI统一标已处理；短未读页排除本轮read_ids。见ai-v14.md。

0.17.1-rel使用当前Electron原生dialog的closedby=any处理背景取消，保持真实打开顺序、焦点和顶层隔离。chat-memory将全局本人设置记作会话设置的一级子页，返回恢复上级表单快照；强制导航仍完整关闭并使迟到响应失效。读取确认的自定义遮罩校验按下/抬起都在背景，调用原取消按钮，遵守写入不可取消状态。无新依赖或数据接口，见ui-overlays-v1.md。

0.17.2-rel移除预算/模型容量/核心投影的16384输出硬上限，配置边界100万不代表模型可用上限。model-limits合并已知接口和元数据输出上限，初始推荐min(65536,context/4)，保留人工小值；核心再次核对输出及上下文。大于8192的模型请求采用30分钟可取消时限；压缩上限16384与最终报告分开。见output-limits-v1.md。

0.17.3-rel以output-settings协调主进程两处输出保存，共用串行队列和运行错误回滚，保留加密密钥及其他预算。renderer容量查询核对请求号、编辑版本和模型归属；保存直接读取当前表单，保护保存中的新输入。核心与全局Agent以新预算及模型实际output_limit_tokens约束后续请求，旧无能力字段的描述保持兼容回退。见output-save-v1.md。


0.17.4-rel在workspace.begin返回requested日期的原生时间边界和image_target，指定日全部私聊任务预载准确范围。finish拒绝无文件及图片目标不足并反馈实际缺口，桌面用具体证据错误引导一次修订。图片任务64步、其他32步；图片候选默认20条。旧分块ai.context尊重context_reuse=false回读原文，默认仍先核验缓存。group-ai-14强化逐条事实与引用对齐。私人验收脚本独立副本、累计5元硬上限与4.75元预占保护；不打进应用。真实测试仍有失败，不能把合成通过当语义正确。

0.18.0-rel在既有profile调度中加入精确单成员过滤、按人分块和逐块阶段保存，全体仅覆盖所选发言者。workspace.profile.request/result把画像及全局指定人物跨群风格接入受控工具，不增加任意SQL或命令。画像结果按本人证据生成，缺口保留待补；当前报告只取本轮触及项。人物临时编号恢复、手动身份保护、去除内部记忆重复、过大缓存回源及部分分群压缩容错修复真实任务失败。识图适合性在有明确保存目标时直接驱动去重保存，目标达到后本地结束。官方DeepSeek JSON请求显式设置JSON模式。真实测试使用副本及独立预算/订阅额度保护，具体边界见src/contracts/ai-v15.md和docs/verification.md。
