# 人物风格、成员记忆与失败历史

版本：0.12.0-rel；Prompt 版本 group-ai-10。继承 ai-v3～v8 的预算、分块、证据、版本与结算规则。真实验收发现模型将 drafts 填成对象数组，已明确要求字符串数组并保留严格拒绝，不自动拼接或修补模型输出。

## 人物范围

`ai.prepare(..., feature="style", options={person_id, cross_group:true, ...})`：人物必须为完整 QQ 或 `u_` 开头 UID。仅查询当前账号、QQ 平台、group 会话及该发送者的消息；排除私聊、其他账号和仅昵称相同的人。未导入历史无法凭空读取。条数上限、时间、关键词和增量游标继续生效；`has_more` 表示尚未全部覆盖。

任务附着于发起群的历史，覆盖记录含 person_id、scope、source_groups。默认并强制分段汇总，最后输出风格说明和 `drafts` 内可复制 Prompt。读取中断不发布分段Prompt；单次最终报告仅收录本次最终产物，旧版仍留在历史中。原文留在本机；完整冻结消息集合按账号重新校验，任何来源变更均拒绝合入。风格 Prompt 属于风格模拟，不是已验证的真实人格或身份。

跨群 style 记忆使用独立 kind，不注入普通群分析。跨群调用仅显式选定人物时读取该账号、该人物的相关记忆；不把整个账号的其他人物资料混入。

## 输入格式

所有模式使用 columns-v1：`messages=[id,day,clock,sender,text,extra]`。时间为 Asia/Shanghai 分钟精度，完整日期在 days 表内只出现一次；people 使用唯一 p0/p1 编号，groups 使用 g0/g1 编号。编号在单次请求内有效，不按昵称前三字合并。原始秒级时间和发送者身份留在本地，证据别名回映后校验。

`compression=off` 完整保留正文和引用，允许元数据规范化；balanced/strong 仍可能截短与折叠，并保留损失说明。重组长消息应核对完整正文和次序，不能把同一来源拆段误计为多条已完成消息。

## 人物记忆

模型可返回 `people_memory`，最多20项：`subject,title,body,uncertainty,evidence_ids`。每项证据必须是该人物本人本段发言，拒绝虚构人物、跨人证据和越界编号。它只是出处与归因校验，不证明语义推断正确。

仅整个任务完成后写入新记忆。每位已读发言者按来源群、QQ/UID记录有限的可追溯发言来源；样本不足时明确尚无稳定画像。模型有有效证据时补充习惯、偏好与职责观察；不保证每次为每个人生成性格推断。同一人物可有不同功能留下的记忆片段，后续相关操作在预算内读取、补充。保留最近12段观察与60条来源索引，长期库是有界摘要，完整证据仍在本地消息表。需要全面历史追踪时再升级为独立事件索引。

`ai.memory.list(conversation_id,account_id)`：最多最近200条本群记忆。

`ai.memory.update(..., memory_key, action, correction)`：correct 更正并锁定；forget 清空此条并暂停更新；unlock 解除锁定/暂停。更正最多6000字。暂停群记忆时普通分析不读写长期记忆；报告历史仍保留。该操作不承诺清除其他历史报告中的全部相关内容。

## 失败与费用

历史覆盖显示 selected、completed_messages、failed_chunk_messages、failed_stage。已完成消息按原始ID去重，失败分块大小不代表该段已被模型完整阅读；汇总失败需区别于读取失败。

`ai.history.delete(conversation_id,account_id,job_id)` 仅允许 failed/cancelled/interrupted。删除报告和分块，清空任务材料及错误，隐藏历史；保留最小任务账本归属和 ai_usage，删除不会退款或抹去花费。已合入群结果保留。运行、已完成任务拒绝该操作；删除任务不可继续。

新增三项只读/本地修改 RPC 由受限 rendererMethods 暴露，准备、提交和结算仍仅主进程可调用。无源 QQ 写入、无自动发送、无新增网络服务。
