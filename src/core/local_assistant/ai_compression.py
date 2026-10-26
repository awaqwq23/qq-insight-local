"""Local, explicitly lossy prompt compression; no model call and no source writes."""
import re
from datetime import datetime,timezone,timedelta
from .ai_prompts import encode

MODES=('off','balanced','strong')
def evidence_pack(messages,mode):
    if mode!='off':return pack(messages,mode)
    # Lossless identifier substitution: body, quotes, timestamps and all other fields stay intact.
    rows=[{**message,'id':f'm{i}'} for i,message in enumerate(messages)]
    return {'messages':rows},{f'm{i}':message['id'] for i,message in enumerate(messages)},messages,{}
NOTICE='本次使用本地有损消息压缩：重复确认可能折叠，长正文或引用可能截短。可能遗漏细节或改变语境，请打开原文核实，不能将压缩材料视为完整记录。'
IMPORTANT=re.compile(r'取消|改为|改成|延期|提前|截止|交[作稿付]|提交|负责|组长|通知|分工|撤回|不要|不再|时间|日期|\d|https?://|@')
ACK=re.compile(r'^(?:[\w\u4e00-\u9fff]{1,12}[：:、\s]+)?(?:收到|好的|好|明白|谢谢|感谢|OK|ok|嗯|赞|[👍👌])(?:[!！。,.，\s👍👌]*)$')

def column_wire(wire):
    days={};indices={};rows=[];groups={};group_aliases={}
    for row in wire['messages']:
        date,clock=row['time'].split('T');clock=clock[:5]
        day=indices.setdefault(date,f'd{len(indices)}');days[day]=date
        extra={key:value for key,value in row.items() if key not in ('id','time','sender','text')}
        if 'group' in extra:
            group=extra['group'];alias=group_aliases.setdefault(group,f'g{len(group_aliases)}');groups[alias]=group;extra['group']=alias
        if extra.get('media'):
            images=[item['index'] for item in extra['media'] if item.get('type')=='image']
            other=[item for item in extra['media'] if item.get('type')!='image']
            if images:extra['images']=images
            if other:extra['media']=other
            else:extra.pop('media',None)
        rows.append([row['id'],day,clock,row['sender'],row['text'],extra])
    return {**wire,'message_columns':['id','day','clock','sender','text','extra'],'days':days,'groups':groups,'time_precision':'minute','messages':rows}

def compression_cost(message,mode,seen,byte_bound=False,columns=False):
    wire,_,_,_=pack([message],mode)
    sender=message.get('sender_qq') or message.get('sender_key') or message.get('sender_name','')
    key=(sender,(int(message.get('sent_at',0))+8*3600)//86400,message.get('text',''))
    if 'repeat' in wire['messages'][0]:
        if key in seen:return 0
        seen.add(key)
    if columns:wire=column_wire(wire)
    value=encode(wire['messages'][0])+encode(wire['people'])+(encode(wire['days']) if columns else '')
    return len(value.encode()) if byte_bound else len(value)

def excerpt(text,limit):
    if len(text)<=limit:return text,False
    # Preserve both ends and any high-signal middle sentences when they fit.
    head=limit//3;tail=limit//4
    middle=text[head:-tail]
    candidates=[part for part in re.split(r'(?<=[。！？!?\n])',middle) if IMPORTANT.search(part)]
    room=limit-head-tail-18
    selected=''.join(candidates)[:max(0,room)]
    return text[:head]+'…[省略]…'+selected+'…[省略]…'+text[-tail:],True

def pack(messages,mode,columns=False):
    """Return compact wire rows, local alias mapping, visible originals and loss stats."""
    if mode not in MODES:raise ValueError('invalid compression mode')
    limit=320 if mode=='balanced' else 120 if mode=='strong' else None
    rows=[];mapping={};visible=[];people={};aliases={};folded=shortened=0;repeat={}
    for message in messages:
        text=message.get('text','');sender=message.get('sender_qq') or message.get('sender_key') or message.get('sender_name','')
        timestamp=message.get('sent_at',0)
        local=datetime.fromtimestamp(timestamp,timezone(timedelta(hours=8)))
        media=[{**value,'index':value.get('index',i)} for i,value in enumerate(message.get('media',[]))];replies=message.get('replies',[])
        # Fold only exact low-information acknowledgements by the same sender/day.
        # Replies, pictures and cancellation/deadline messages always remain independent.
        key=(sender,local.strftime('%Y-%m-%d'),text)
        known_sender=bool(message.get('sender_qq') or message.get('sender_key'))
        if mode!='off' and known_sender and not media and not replies and ACK.fullmatch(text.strip()) and not IMPORTANT.search(text) and key in repeat:
            row=rows[repeat[key]];row['repeat']+=1;row['last_time']=local.isoformat(timespec='minutes');folded+=1;continue
        person=aliases.setdefault(sender,f'p{len(aliases)}')
        people[person]={'qq':message.get('sender_qq',''),'uid':message.get('sender_key',''),'name':message.get('sender_name','')}
        alias=f'm{len(rows)}';mapping[alias]=message['id'];visible.append(message)
        reduced,truncated=excerpt(text,limit) if limit else (text,False);shortened+=int(truncated)
        row={'id':alias,'time':local.isoformat(timespec='minutes'),'sender':person,'text':reduced}
        if message.get('conversation_id'):row['group']=message['conversation_id']
        if message.get('direction')=='outgoing':row['self']=True
        if media:row['media']=media
        if replies:
            # Preserve quotation attribution and numbers, but bound large embedded quoted bodies.
            reduced_replies=[]
            for reply in (replies[:4] if limit else replies):
                if isinstance(reply,dict):
                    value={}
                    for key2,item in reply.items():
                        if isinstance(item,str) and limit:item,changed=excerpt(item,limit);shortened+=int(changed)
                        value[key2]=item
                    reduced_replies.append(value)
                else:reduced_replies.append(str(reply)[:limit] if limit else reply)
            row['replies']=reduced_replies
            if limit and len(replies)>4:shortened+=1
        if truncated:row['truncated']=True
        if message.get('parts',1)>1:row['part']=[message.get('part',1),message['parts']]
        if mode!='off' and known_sender and not media and not replies and ACK.fullmatch(text.strip()) and not IMPORTANT.search(text):
            row['repeat']=1;repeat[key]=len(rows)
        rows.append(row)
    wire={'people':people,'messages':rows,'compression':{'mode':mode,'original_messages':len(messages),'sent_messages':len(rows),'folded':folded,'shortened':shortened,'notice':NOTICE if mode!='off' else '仅规范化元数据：时间精确到分钟，日期和姓名使用编号；正文与引用不截短。'}}
    if columns:wire=column_wire(wire)
    stats={**wire['compression'],'original_bytes':len(encode(messages).encode()),'compressed_bytes':len(encode(wire).encode())}
    return wire,mapping,visible,stats
