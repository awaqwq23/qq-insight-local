"""Synthetic data only. Never reads the user's QQ database."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/core'))
from local_assistant.service import AssistantService
app=AssistantService(Path(sys.argv[1]))
with app.storage.connect() as conn:
    for group,account,kind in [('volume-main','volume','group'),('volume-extra-a','volume','group'),('volume-extra-b','volume','group'),('other-account','other','group'),('private','volume','c2c')]:
        conn.execute("INSERT INTO conversations(id,kind,title,platform,account_id) VALUES(?,?,?,'qq',?)",(group,kind,'合成验收群',account))
    topics=['先确认范围，再动手吧。','我倾向于把结果列清楚，别急。','哈哈，这个可以，稍后一起核实。','这个说法需要原文支持，我还不确定。','周五前提交材料，负责人请回复。','刚才的安排取消，改为下周一上午。','收到，谢谢，晚点反馈。','请保留不同意见，先核对版本。']
    for i in range(3600):
        group='volume-main' if i<3000 else 'volume-extra-a' if i<3300 else 'volume-extra-b'
        sender=str(100001+i%20) if i<3000 else '100001'
        text=f'合成讨论 {i}：'+topics[i%len(topics)]
        if i%79==0:text+='背景：正在整理一份课程项目报告，需要分工、来源核对与测试记录。'
        conn.execute("INSERT INTO messages(id,conversation_id,source_key,sent_at,direction,sender_key,sender_qq,sender_name,text,content_kind,parse_status,platform,account_id) VALUES(?,?,?,?,'incoming',?,?,?,?,'文本','partial','qq','volume')",(f'volume-{i}',group,f'volume-source-{i}',1790000000+i*37,'u_synthetic'+sender,sender,'合成成员'+str(i%20),text))
for group in ('volume-main','volume-extra-a','volume-extra-b'):app.ai.save_group(group,'volume',{'remember':True,'images':False,'category':'项目'})
