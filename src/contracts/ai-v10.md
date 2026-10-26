# 群记忆、可复用上下文与全局工作区 Agent

版本0.13.0-rel，Prompt group-ai-11。继承ai-v9的账号隔离、证据、预算、来源变更与锁定规则。核心只处理本地数据；联网和密钥只在桌面主进程。

## 群与成员记忆

成功完成任务后，按来源群更新`group:<feature>`，包含事实、暂定评价、时间范围、来源及最近12次观察，正文有界6000字。跨群结果不能整段写成单群事实；模型可给出`group_memory=[{conversation_id,body,evaluation,evidence_ids}]`，每条证据必须来自该群。缺少可用评价时只保存已读范围和样本不足，不编造氛围。纯统计/导出保存工具活动与范围，不据此评价群成员。

人物记忆证据须由本人发送。跨会话的综合人物观察只保留在综合回答/报告中，不通过切分来源编号复制到各群记忆；单个来源会话的观察才进入对应会话人物库。`remember=false`群不读写记忆或缓存，更正锁定优先。它不是语义真实性证明。

## 压缩上下文

`ai_contexts`在成功后保存摘要、来源消息ID及规范化内容哈希。读取时要求账号、会话、消息范围、哈希均有效，多个摘要覆盖不重叠，且摘要比原文短；选中范围不足或原文变化即回源。群功能还冻结模型、功能、目标、设置、筛选及锁定状态的reuse_key；小样本节省不足4096字节时不增加汇总开销。

`ai.prepare.options.context_reuse`默认true；复用节点结合新消息进入现有分层汇总，覆盖显示`reused_messages/raw_messages`。style/reply/identity/collection强制回原文。全局Agent的通用事实摘要可服务新问题，但原话、说话方式、精准统计和顺序使用`prefer_cache=false`或SQL工具。字节差不称作计费Token；摘要仍可能遗漏细节。人工更正或忘记使对应群缓存失效。

## 全局工具与范围

主进程私有RPC：`workspace.begin/tool/finish/image.data/image.observed/artifact/tool.error/output.rejected`。界面仅可读取`workspace.history`和删除失败历史；运行/取消/文件另存为使用专用IPC，工具执行及预算结算不可从界面任意调用。

`begin(account_id,question)`固定当前QQ账号、allowed_kinds和北京时间边界。中文问题默认group，明确私聊才开放c2c；明显续问可继承上一轮范围。问题未涵盖的旧私聊任务答案不进入前情。核心对会话列表、人物检索、读取、统计、导出、图片及来源复核再次检查范围，模型不能自行扩大。缺少私聊权限时用户需重新提问明确范围；同名歧义须澄清。

工具为conversations、people、read_context、statistics、export_order、write_markdown、images、inspect_image、save_image。JSON参数带类型与界限；仅当前账号导入记录，无任意SQL、Shell、URL、路径或聊天发送。read_context有分页、来源与旧摘要覆盖提示，原文时间分钟化、姓名编号化；QQ/UID匹配不按昵称合并。每轮最多16次模型调用；所有文字与识图走共享预算、容量、限流与账本。相同失败工具参数两次停止；空结果可重试一次；非法JSON最多两次，最终证据错误最多一次修订，失败费用不抹去。

## 文件、图片与持久化

`export_order`用SQL按sent_at,id排序，生成真正xlsx，只有人名列，一条消息一行；同秒仅稳定排序，不证明更细真实先后。人名写inlineStr，不能变为公式。Markdown须提供已读证据。结果以artifact_id引用，单文件不超过8MB、每任务30份，物化到应用自有目录；打开/另存为使用受控路径和原生对话框。

图片候选不等于内容证据；inspect_image实际发送本地图像到独立识图配置，得到本轮检查标记后才能save_image。最多20张，保存文件并加入本地收藏。缺缓存/识图配置如实失败，不凭文件名判断可爱。

workspace_runs、workspace_artifacts和有效ai_contexts纳入本地备份恢复；中断任务恢复为interrupted，导入不触发网络。失败/取消/中断任务可删除，清除内置材料而保留最小费用归属；用户已另存文件不删除。重启不会自动继续扣费。

验证见test_workspace_agent.py、workspace-agent.test.js、renderer-agent.test.js和packaged-people-smoke.py；真实模型验收脚本仅用合成工作区并另查实际来源种类与文件内容。三角色独立协作仍是课程设计，不能把工具循环称为已实现的三Agent共识系统。
