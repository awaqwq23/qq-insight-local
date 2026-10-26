"""Small synthetic workspace for offline and explicitly opted-in live checks."""
from pathlib import Path
import hashlib,json,struct,sys,zlib,time
from datetime import datetime,timezone,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/core'))
from local_assistant.service import AssistantService
app=AssistantService(Path(sys.argv[1]))
groups=[('work','group','合成工作项目群','synthetic'),('fun','group','合成兴趣群','synthetic'),('stickers','group','合成表情分享群','synthetic'),('private-lin','c2c','合成小林','synthetic'),('foreign','group','其他账号群','other')]
stamp=int(time.time());midnight=int(datetime.now(timezone(timedelta(hours=8))).replace(hour=0,minute=0,second=0,microsecond=0).timestamp());step=max(1,min(60,(stamp-midnight)//30));base=max(midnight,stamp-step*20)
messages=[('work','999001','合成我','我是资料整理人，今天先核对设计稿。','outgoing'),('work','100001','合成小林','先确认范围，再整理。周日18:00前我提交接口清单。','incoming'),('work','100002','合成小周','请资料整理人负责周日晚18:00前整理测试报告。','incoming'),('work','100001','合成小林','刚才接口清单截止改为周一中午，不是周日。','incoming'),('work','100002','合成小周','收到','incoming'),('fun','100001','合成小林','哈哈，好呀，晚点一起玩～','incoming'),('private-lin','100001','合成小林','嗯嗯，没事呀，慢慢来～先确认一下就好。','incoming'),('private-lin','999001','合成我','我整理好后给你核对。','outgoing'),('stickers','100001','合成小林','[图片]','incoming'),('foreign','100001','其他账号人物','禁止混入当前账号','incoming')]
with app.storage.connect() as conn:
    for key,kind,title,account in groups:conn.execute("INSERT INTO conversations(id,kind,title,platform,account_id,peer_qq,peer_uid) VALUES(?,?,?,'qq',?,?,?)",(key,kind,title,account,'100001' if kind=='c2c' else '', 'u_synthetic100001' if kind=='c2c' else ''))
    for i,(group,qq,name,text,direction) in enumerate(messages):
        account='other' if group=='foreign' else 'synthetic'
        conn.execute("INSERT INTO messages(id,conversation_id,source_key,sent_at,direction,sender_key,sender_qq,sender_name,text,content_kind,parse_status,platform,account_id) VALUES(?,?,?,?,?,?,?,?,?,'文本','partial','qq',?)",(f'syn-{i}',group,f'syn-source-{i}',base+i*step,direction,'u_synthetic'+qq,qq,name,text,account))
    pixels=[]
    for y in range(96):
        row=bytearray()
        for x in range(96):
            color=(255,230,242)
            if ((x-32)/10)**2+((y-25)/22)**2<1 or ((x-64)/10)**2+((y-25)/22)**2<1:color=(255,255,255)
            if ((x-48)/32)**2+((y-58)/28)**2<1:color=(255,255,255)
            if ((x-32)/4)**2+((y-53)/5)**2<1 or ((x-64)/4)**2+((y-53)/5)**2<1:color=(55,35,45)
            if ((x-24)/6)**2+((y-65)/3)**2<1 or ((x-72)/6)**2+((y-65)/3)**2<1:color=(255,150,180)
            if abs(y-(71-abs(x-48)*.6))<1.2 and abs(x-48)<9:color=(190,90,130)
            row.extend(color)
        pixels.append(b'\x00'+bytes(row))
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    image=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',96,96,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(pixels)))+chunk(b'IEND',b'')
    conn.execute("INSERT INTO messages(id,conversation_id,source_key,sent_at,direction,sender_key,sender_qq,sender_name,text,content_kind,parse_status,platform,account_id) VALUES('syn-yesterday','work','syn-source-yesterday',?,'incoming','u_synthetic999001','999001','合成我','昨日已取消：无需再做旧海报任务。','文本','partial','qq','synthetic')",(base-86400,))
    key=hashlib.sha256(image).hexdigest();conn.execute('INSERT INTO media_assets VALUES(?,?,?)',(key,'image/png',image));conn.execute('INSERT INTO message_media VALUES(?,?,?)',('syn-8',0,key));conn.execute('UPDATE messages SET media_json=? WHERE id=?',(json.dumps([{'type':'image','filename':'synthetic.png'}]),'syn-8'))
app.ai.save_group('work','synthetic',{'category':'项目','role':'资料整理人','self_names':'合成我','remember':True})

if '--autonomy' in sys.argv:
    with app.storage.connect() as conn:
        conn.execute("INSERT INTO conversations(id,kind,title,platform,account_id) VALUES('long','group','合成长材料群','qq','synthetic')")
        conn.execute("INSERT INTO messages(id,conversation_id,source_key,sent_at,direction,sender_key,sender_qq,sender_name,text,content_kind,parse_status,platform,account_id) VALUES('long-source','long','long-source',?,'incoming','u_long','100005','合成长文成员',?,'文本','partial','qq','synthetic')",(base,'合成背景记录，保留可验证事实。'*1000))
        for i in range(170):conn.execute("INSERT INTO conversations(id,kind,title,platform,account_id) VALUES(?,'c2c','合成历史联系人','qq','synthetic')",(f'inactive-{i}',))
        for n,cid in enumerate(('qa-a','qa-b','qa-noise')):
            conn.execute("INSERT INTO conversations(id,kind,title,platform,account_id) VALUES(?,'c2c',?,'qq','synthetic')",(cid,'合成问答 '+cid))
            entries=[('outgoing','999001','合成我','今天请提一个问题。'),('incoming',f'10010{n}','合成提问者','你想读哪本合成书？'),('outgoing','999001','合成我','答：合成故事集。\n保留空格  🙂\n```原文```'),('outgoing','999001','合成我','补充回答分开发送。')]
            if cid=='qa-noise':entries=[('incoming','100109','合成路人','与邀请问答无关的合成问候。')]
            for k,(direction,qq,name,text) in enumerate(entries):
                key=cid+str(k)
                conn.execute("INSERT INTO messages(id,conversation_id,source_key,sent_at,direction,sender_key,sender_qq,sender_name,text,content_kind,parse_status,platform,account_id) VALUES(?,?,?,?,?,?,?,?,?,'文本','partial','qq','synthetic')",(key,cid,key,base+n*step+k,direction,'u_synthetic'+qq,qq,name,text))
