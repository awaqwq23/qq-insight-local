"""Large, varied synthetic fixture for explicitly authorized live acceptance."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/core'))
from local_assistant.service import AssistantService
app=AssistantService(Path(sys.argv[1]))
with app.storage.connect() as conn:
    conn.execute("INSERT INTO conversations(id,kind,title,platform,account_id) VALUES('synthetic-group','group','合成大范围讨论群','qq','synthetic')")
    for i in range(5100):
        body=f'合成讨论{i}：项目资料已整理，正在核对任务与安排。' if i%7 else '收到'
        if i in (101,701,2101,4101,5099):body=f'合成任务{i}：资料提交截止改为周五，负责人第{i%8}组；请以更正后的时间为准。'
        if i%97==0:body+='合成背景材料，请结合上下文核实。'*35
        sender=str(100001+i%20)
        conn.execute("INSERT INTO messages(id,conversation_id,source_key,sent_at,direction,sender_key,sender_qq,sender_name,text,content_kind,parse_status,platform,account_id) VALUES(?,'synthetic-group',?,?,'incoming',?,?,?,?,'文本','partial','qq','synthetic')",(f'synthetic-long-message-{i}',f'synthetic-{i}',1790000000+i*10,sender,sender,'合成成员'+str(i%20),body))
app.ai.save_group('synthetic-group','synthetic',{'remember':False,'images':False,'category':'项目'})
