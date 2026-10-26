# 全局Agent：独立对话与修改分支

版本0.14.0-rel，继承ai-v10的来源、范围、预算和受控工具约束。

## 保存与数据关系

`workspace_sessions(id,account_id,title,head_id,created_at,updated_at)`保存对话；`workspace_turns(run_id,session_id,parent_id)`关联既有workspace_runs。问答、步骤、附件和账本继续绑定原run，不复制或覆盖旧任务。对话ID与QQ群会话ID不同。

同一对话当前分支的成功轮次构成本轮前情；新对话不读取同账号其他对话的问答，不再按“最近几次任务”或续问关键词猜上下文。旧版独立任务各迁移为一个独立对话，不推测合并关系。已发送问答自动保存在本机，空对话与名称也保存；未发送草稿仅在本次窗口的对话切换间暂存，不承诺重启恢复。

## 接口

- `workspace.chat.create(account_id,title="新对话")`：当前账号已有QQ本地记录时可创建。首问自动作默认标题；用户重命名后保留人工名称。
- `workspace.chat.list(account_id,offset=0,limit=50)`：按更新时间返回当前账号的对话，带has_more/next_offset。
- `workspace.chat.get(session_id,account_id,offset=0,limit=50)`：当前分支的问答与附件；默认最近50轮，offset向更早轮次翻页，返回分支末端与当前head。
- `workspace.chat.rename(session_id,account_id,title)`：1–80字。
- `workspace.chat.select(session_id,account_id,head_id)`：选择本对话已有分支后继续；运行中不能切换分支。
- 主进程私有`workspace.begin(account_id,question,session_id="",edit_run_id="",context_bytes=40000)`：省略session_id则创建独立新对话；指定edit_run_id时从被编辑轮次的父节点继续，仅可编辑本对话当前分支。每个对话同时只准一个运行任务。

上述chat管理接口列入受限界面RPC；begin/tool/finish和预算结算仍只在主进程。运行、进度与结果携带session_id。账号及对话选择变化后的迟到结果不能渲染到新对话。

## 连续上下文与容量

本轮按模型容量选择可放入的最近成功问答，不截断本机保存的原答。context_notice说明已保存、已提供、被范围过滤和较旧轮次；单轮过长时提供明确truncated片段。`chat_history`仅能回读本对话本轮之前当前分支、当前允许群聊/私聊种类内的成功问答，不能访问其他对话或被改写分支。

`chat_history(offset,limit)`正序分页返回旧问答；回答有截断时可使用`chat_history(turn_id,offset)`按字符偏移回读完整回答，每段6000字。旧轮次r编号只属于当时，不能直接作为新来源证据；精确事实、文件证据与记忆更新需用已有聊天工具重新核验。历史问答也属于不可信材料。

未明确群聊/私聊的新追问可继承本对话上一个成功轮次的种类范围；明确群聊时收窄并过滤带私聊的历史，私聊仍须明确授权。对话问答隔离；群与人物长期记忆、来源哈希摘要仍按原账号和来源会话规则共享，不改成每个对话一份人物库。

## 修改、保留与恢复

修改问题或重新生成创建新run及新分支，不把被替换问答或其后续回复放入新前情。旧分支、内置附件和已发生费用保留，可选择旧分支查看或继续。它不撤销已经保存的来源群/人物长期记忆，不删除用户另存文件。

失败记录删除仍保留最小账本归属，删除当前末端失败任务后head退到其父节点。失败发送前的输入保留，方便配置完成后重试。

sessions/turns随原应用数据库备份；恢复核验账号、父子归属、head与无环性，禁止同run迁入另一个对话。旧备份缺少新表时逐任务迁移。恢复的运行任务为interrupted，不自动发起模型调用。

验证：test_workspace_chats.py、test_workspace_agent.py、workspace-agent.test.js、renderer-agent.test.js、packaged-people-smoke.py。合成测试验证上下文载荷与持久化，不代表真实模型理解或语义效果已验收。
