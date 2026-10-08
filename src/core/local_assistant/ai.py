"""Group-scoped planning, validated results, durable history and budget ledger.

The only network caller is the desktop model gateway. This module never receives
credentials and the renderer cannot call preparation/settlement RPCs directly.
"""
from datetime import datetime, timezone, timedelta
import hashlib
import json
import math
import re
import time
import uuid

from .errors import CoreError
from .ai_accounting import UsageLedger
from .ai_prompts import FEATURES, VERSION, encode, system_prompt, user_prompt
from .ai_schema import SCHEMA, DEFAULT_GROUP, DEFAULT_BUDGET, BUDGET_LIMITS


def now(): return datetime.now(timezone.utc).isoformat()
def digest(value): return hashlib.sha256(encode(value).encode()).hexdigest()
def identifier(): return uuid.uuid4().hex
def integer(value, low, high): return type(value) is int and low <= value <= high

def projection(row):
    item=dict(row)
    item['media']=json.loads(item.pop('media_json') or '[]')
    item['replies']=json.loads(item.pop('reply_json') or '[]')
    item['local_time']=datetime.fromtimestamp(item['sent_at'],timezone(timedelta(hours=8))).isoformat()
    item['content_hash']=digest(item)
    return item

MESSAGE_COLUMNS='id,sent_at,sender_name,sender_qq,sender_key,text,media_json,reply_json,direction,content_kind'


class GroupAI:
    def __init__(self, service):
        self.service = service
        self.storage = service.storage
        self.ledger = UsageLedger(self)
        with self.storage.connect() as conn:
            conn.executescript(SCHEMA)
            self.storage._ensure_column(conn,'ai_chunks','previous_json',"TEXT NOT NULL DEFAULT '[]'")
            self.storage._ensure_column(conn,'ai_usage','details_json',"TEXT NOT NULL DEFAULT '{}'")
            self.storage._ensure_column(conn,'ai_chunks','watch_target',"TEXT NOT NULL DEFAULT ''")
            self.storage._ensure_column(conn,'ai_chunks','media_results_json',"TEXT NOT NULL DEFAULT '{}'")
            conn.execute("UPDATE ai_jobs SET status='interrupted',error='应用关闭时分析中断，可继续未完成分块' WHERE status IN ('running','queued')")
            conn.execute("UPDATE ai_chunks SET status='failed' WHERE status='running'")
            conn.execute("UPDATE ai_usage SET status='unknown',details_json=json_set(details_json,'$.state','unknown') WHERE status='reserved'")

    def group(self, conversation_id, account_id, platform='qq'):
        group = self.service._conversation(conversation_id, account_id, platform)
        if group['kind'] != 'group': raise CoreError('GROUP_REQUIRED','请先选择一个群聊。')
        return group

    def catalog(self):
        return {'version': VERSION, 'items':[{'id':key,'name':value[0],'requirement':value[1],'prompt':system_prompt(key),'schedulable':key!='identity'} for key,value in FEATURES.items()]}

    def get_group(self, conversation_id, account_id, platform='qq'):
        self.group(conversation_id, account_id, platform)
        with self.storage.connect() as conn:
            row = conn.execute('SELECT settings_json FROM ai_group_settings WHERE conversation_id=?',(conversation_id,)).fetchone()
            memory_rows=conn.execute('SELECT kind,count(*) total,count(DISTINCT CASE WHEN kind=\'person\' THEN subject END) people FROM ai_memories WHERE conversation_id=? GROUP BY kind',(conversation_id,)).fetchall()
        config = {**DEFAULT_GROUP, **(json.loads(row[0]) if row else {})}
        if not row: config['role'] = self.service.get_profile(conversation_id,account_id,platform)['role_text']
        # Roles are deliberately group-scoped.  A role from another group must
        # never leak into this group's prompts or local work digest.
        config['effective_role'] = config['role']
        config['memory_stats']={'items':sum(value['total'] for value in memory_rows),'people':sum(value['people'] or 0 for value in memory_rows)}
        return config

    def save_group(self, conversation_id, account_id, settings, platform='qq'):
        self.group(conversation_id, account_id, platform)
        if not isinstance(settings,dict): raise CoreError('INVALID_PARAMS','群设置格式无效。')
        config = {key:value for key,value in self.get_group(conversation_id,account_id,platform).items() if key in DEFAULT_GROUP}
        for key in ('category','role','self_names','interests','instructions','image_model'):
            if key in settings:
                if not isinstance(settings[key],str) or len(settings[key])>1000: raise CoreError('INVALID_PARAMS','群设置文本过长。')
                config[key]=settings[key].strip()
        for key in ('watch_people','watch_keywords'):
            if key in settings:
                values=settings[key]
                if key=='watch_people':
                    if isinstance(values,str):values=[values]
                    if isinstance(values,list) and all(isinstance(value,str) for value in values):
                        values=[part for value in values for part in re.split(r'[,，;；、\s]+',value.strip()) if part]
                if not isinstance(values,list) or len(values)>50 or any(not isinstance(value,str) or len(value)>100 for value in values):
                    raise CoreError('INVALID_PARAMS','特别关心最多50项，每项100字。')
                config[key]=list(dict.fromkeys(value.strip() for value in values if value.strip()))
        for key in ('remember','images','auto_favorite'):
            if key in settings:
                if type(settings[key]) is not bool: raise CoreError('INVALID_PARAMS','群设置开关无效。')
                config[key]=settings[key]
        for key,low,high in (('favorite_daily_limit',1,100),('favorite_storage_mb',1,10000),('schedule_minutes',0,1440)):
            if key in settings:
                if not integer(settings[key],low,high) or (key=='schedule_minutes' and 0<settings[key]<5): raise CoreError('INVALID_PARAMS','频率至少5分钟，收藏配额应为有效整数。')
                config[key]=settings[key]
        if 'schedule_feature' in settings:
            if settings['schedule_feature'] not in FEATURES or settings['schedule_feature']=='identity': raise CoreError('INVALID_PARAMS','定时分析功能无效。')
            config['schedule_feature']=settings['schedule_feature']
        with self.storage.connect() as conn:
            conn.execute('INSERT INTO ai_group_settings VALUES(?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET settings_json=excluded.settings_json,updated_at=excluded.updated_at',(conversation_id,encode(config),now()))
            conn.execute('INSERT INTO conversation_preferences VALUES(?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET role_text=excluded.role_text,updated_at=excluded.updated_at',(conversation_id,config['role'],now()))
            conn.execute('INSERT INTO ai_schedules VALUES(?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET next_at=excluded.next_at,feature=excluded.feature',(conversation_id,int(time.time())+config['schedule_minutes']*60,config['schedule_feature']))
        return self.get_group(conversation_id,account_id,platform)

    def budget(self):
        local=datetime.now(timezone(timedelta(hours=8)));day=local.strftime('%Y-%m-%d');month=day[:7]
        with self.storage.connect() as conn:
            row=conn.execute('SELECT config_json FROM ai_budget_settings WHERE id=1').fetchone()
            config={**DEFAULT_BUDGET,**(json.loads(row[0]) if row else {})}
            daily=conn.execute('SELECT coalesce(sum(charged),0) FROM ai_usage WHERE day=?',(day,)).fetchone()[0]
            monthly=conn.execute('SELECT coalesce(sum(charged),0),sum(cost),sum(CASE WHEN status=\'unknown\' THEN 1 ELSE 0 END) FROM ai_usage WHERE month=?',(month,)).fetchone()
            totals={};unknown=0
            for value in conn.execute('SELECT cost,charged,prices_json FROM ai_usage WHERE month=?',(month,)):
                if value['cost'] is None and value['charged']>0:unknown+=1
                elif value['cost'] is not None:
                    currency=json.loads(value['prices_json']).get('currency',config['currency']);totals[currency]=totals.get(currency,0)+value['cost']
        return {**config,'limits':BUDGET_LIMITS,'daily_used':daily,'monthly_used':monthly[0],'monthly_cost_used':None if unknown else totals.get(config['currency'],0),'cost_totals':totals,'unknown_price_calls':unknown,'uncertain_requests':monthly[2] or 0}

    def save_budget(self, settings):
        if not isinstance(settings,dict): raise CoreError('INVALID_PARAMS','预算配置无效。')
        config={key:value for key,value in self.budget().items() if key in DEFAULT_BUDGET}
        for key,limit in BUDGET_LIMITS.items():
            if key in settings:
                if not integer(settings[key],limit['min'],limit['max']):
                    raise CoreError('INVALID_PARAMS',f"{limit['label']}须为 {limit['min']:,}–{limit['max']:,} 的整数，本次预算未保存。",{'field':key,**limit})
                config[key]=settings[key]
        for key in ('monthly_cost','input_price','output_price'):
            if key in settings:
                value=settings[key]
                if value is None and key!='monthly_cost': config[key]=None;continue
                if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1000000: raise CoreError('INVALID_PARAMS','价格须为非负数；未知价格留空。')
                config[key]=value
        if 'price_model' in settings:
            if not isinstance(settings['price_model'],str) or len(settings['price_model'])>160: raise CoreError('INVALID_PARAMS','计费模型名称无效。')
            config['price_model']=settings['price_model']
        if settings.get('currency') in ('CNY','USD'): config['currency']=settings['currency']
        with self.storage.connect() as conn: conn.execute('INSERT INTO ai_budget_settings VALUES(1,?) ON CONFLICT(id) DO UPDATE SET config_json=excluded.config_json',(encode(config),))
        return self.budget()

    def _items(self,conn,conversation_id,feature=None):
        where='conversation_id=?';params=[conversation_id]
        if feature: where+=' AND feature=?';params.append(feature)
        rows=conn.execute(f'SELECT * FROM ai_items WHERE {where} ORDER BY updated_at DESC,id',params).fetchall()
        return [{**json.loads(row['data_json']),**json.loads(row['user_json']),'id':row['id'],'feature':row['feature'],'updated_at':row['updated_at']} for row in rows]

    def _memories(self,conn,conversation_id,exclude_feature='',target=''):
        where='conversation_id=?';params=[conversation_id]
        if exclude_feature:
            where+=' AND feature<>?';params.append(exclude_feature)
        if target:
            where+=" AND (kind='group' OR subject=?)";params.append(target)
        rows=conn.execute(f'SELECT memory_key,kind,subject,feature,data_json FROM ai_memories WHERE {where} ORDER BY updated_at DESC LIMIT 80',params).fetchall()
        return [{**json.loads(row['data_json']),'memory_key':row['memory_key'],'kind':row['kind'],'subject':row['subject'],'feature':row['feature']} for row in rows]

    def _save_memory(self,conn,conversation_id,key,kind,subject,feature,data,job_id,stamp):
        conn.execute('''INSERT INTO ai_memories(conversation_id,memory_key,kind,subject,feature,data_json,source_job_id,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(conversation_id,memory_key) DO UPDATE SET
                        kind=excluded.kind,subject=excluded.subject,feature=excluded.feature,data_json=excluded.data_json,
                        source_job_id=excluded.source_job_id,updated_at=excluded.updated_at''',
                     (conversation_id,key,kind,subject,feature,encode(data),job_id,stamp,stamp))

    def _refresh_memories(self,conn,job,items,done,stamp):
        config=json.loads(job['settings_json'])
        if not config.get('remember',True):return
        for item in items:
            if item.get('forgotten'):continue
            subject=item.get('subject') or 'group';kind='person' if subject not in ('','group') else 'group'
            data={key:item.get(key) for key in ('id','title','body','category','evidence_ids','uncertainty','user_status','correction') if item.get(key) not in (None,'',[])}
            self._save_memory(conn,job['conversation_id'],'item:'+item['id'],kind,subject,job['feature'],data,job['id'],stamp)
        grouped={}
        for chunk in done:
            result=json.loads(chunk['result_json']);subject=chunk['watch_target'] or 'group'
            if result.get('summary'):grouped.setdefault(subject,[]).append(result['summary'])
        for subject,summaries in grouped.items():
            kind='person' if subject!='group' else 'group'
            self._save_memory(conn,job['conversation_id'],f"summary:{job['feature']}:{subject}",kind,subject,job['feature'],
                              {'title':FEATURES[job['feature']][0]+'摘要','body':'\n'.join(summaries)[:6000],'evidence_ids':[]},job['id'],stamp)

    def _record_short_job(self,conn,account_id,conversation_id,feature,model,config,options,fingerprint,context_key,coverage,status,summary,items=None):
        job_id=identifier();stamp=now()
        conn.execute('INSERT INTO ai_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(job_id,account_id,conversation_id,feature,status,fingerprint,context_key,encode(model),encode(config),encode(options),encode(coverage),stamp,stamp,''))
        conn.execute('INSERT INTO ai_reports VALUES(?,?,?,?,?,?,?)',(job_id,conversation_id,feature,summary,encode(items or []),encode({key:value for key,value in coverage.items() if key not in ('hashes','previous','memory')}),stamp))
        return job_id

    def prepare(self,conversation_id,account_id,feature,model,options=None,platform='qq'):
        group=self.group(conversation_id,account_id,platform)
        if feature not in FEATURES: raise CoreError('INVALID_PARAMS','分析功能无效。')
        if not isinstance(model,dict) or not model.get('model') or any(key not in ('id','model','provider','endpoint_hash','pricing','routes') for key in model): raise CoreError('MODEL_REQUIRED','请选择并保存一个模型。')
        options=options or {}
        mode=options.get('mode','recent');limit=options.get('limit',500)
        if mode not in ('recent','time','incremental') or not integer(limit,1,10000): raise CoreError('INVALID_PARAMS','分析范围无效，最多10000条。')
        for key in ('goal','tone','length','sender','query'):
            if not isinstance(options.get(key,''),str) or len(options.get(key,''))>1000: raise CoreError('INVALID_PARAMS','分析选项格式无效。')
        current_group=self.get_group(conversation_id,account_id,platform)
        config={key:value for key,value in current_group.items() if key in DEFAULT_GROUP}
        config['effective_role']=current_group['effective_role']
        budget=self.budget()
        with self.storage.connect() as conn:
            previous=self._items(conn,conversation_id,feature)
            confirmed=[item for item in self._items(conn,conversation_id,'profile') if config['remember'] and item.get('user_status')=='confirmed' and not item.get('forgotten')][:15]
            long_term=self._memories(conn,conversation_id,exclude_feature=feature) if config['remember'] else []
            memory=[*confirmed,*long_term]
            previous=[item for item in previous if not item.get('forgotten')][:40]
            context_key=digest([VERSION,feature,config,model,{key:options.get(key,'') for key in ('goal','tone','length','sender','query')},memory,
                                [(item['id'],item.get('user_status'),item.get('correction'),item.get('locked')) for item in previous if item.get('locked') or item.get('user_status')]])
            where='m.conversation_id=? AND m.account_id=? AND m.platform=?';params=[conversation_id,account_id,platform]
            if mode=='time':
                start,end=options.get('start'),options.get('end')
                if not integer(start,0,9999999999) or not integer(end,start+1,9999999999): raise CoreError('INVALID_PARAMS','请选择有效的开始和结束时间。')
                where+=' AND m.sent_at>=? AND m.sent_at<?';params.extend([start,end])
            for key,column in (('sender','m.sender_qq'),('query','m.text')):
                if options.get(key): where+=f" AND {column} LIKE ? ESCAPE '!'";params.append(self.service._like(options[key]))
            # Read compact projections; coverage uses actual content hashes, not send timestamps.
            targets=config['watch_people'] if feature=='watch' else []
            if targets and limit<len(targets):raise CoreError('INVALID_PARAMS','分析条数上限不能少于特别关心人数。')
            covered={row['message_id']:(row['digest'],row['context_key']) for row in conn.execute('SELECT * FROM ai_coverage WHERE conversation_id=? AND feature=?',(conversation_id,feature))} if mode=='incremental' else {}
            selected=[];remaining=False;watch=[]
            quota=max(1,limit//max(1,len(targets)))
            for target in targets or ['']:
                predicate=where+(' AND (m.sender_qq=? OR m.sender_key=?)' if target else '')
                arguments=[*params,*([target,target] if target else [])]
                cursor=conn.execute(f'SELECT {MESSAGE_COLUMNS} FROM messages m WHERE {predicate} ORDER BY m.sent_at '+('DESC,m.id DESC' if mode=='recent' else 'ASC,m.id ASC'),arguments)
                found=[];more=False
                for row in cursor:
                    item=projection(row)
                    if covered.get(item['id'])==(item['content_hash'],context_key):continue
                    if len(found)>=quota:more=True;remaining=True;break
                    found.append(item)
                selected.extend(found)
                if target:watch.append({'target':target,'selected':len(found),'has_more':more,'status':'pending' if found else 'no_messages'})
            selected=list({item['id']:item for item in selected}.values())
            selected.sort(key=lambda item:(item['sent_at'],item['id']))
            fingerprint=digest([context_key,[(item['id'],item['content_hash']) for item in selected]])
            missing=sum(1 for item in selected if item['text'].startswith('[') or item['media'])
            coverage={'selected':len(selected),'sent':len(selected),'folded':0,'media_or_unknown':missing,'images_sent':0,'has_more':remaining,
                      'start':selected[0]['sent_at'] if selected else 0,'end':selected[-1]['sent_at'] if selected else 0,'chunks':0,'watch_people':watch,'per_person_limit':quota,
                      'hashes':{item['id']:item['content_hash'] for item in selected},'previous':previous,'memory':memory}
            cached=conn.execute("SELECT id FROM ai_jobs WHERE fingerprint=? AND conversation_id=? AND feature=? AND status='completed' ORDER BY created_at DESC LIMIT 1",(fingerprint,conversation_id,feature)).fetchone()
            if cached:
                source=conn.execute('SELECT summary,items_json FROM ai_reports WHERE job_id=?',(cached[0],)).fetchone()
                coverage['reused_job_id']=cached[0];coverage['completed_chunks']=0;coverage['completed_messages']=len(selected)
                job_id=self._record_short_job(conn,account_id,conversation_id,feature,model,config,options,fingerprint,context_key,coverage,'cached',source['summary'] if source else '相同输入已分析，已复用历史结果。',json.loads(source['items_json']) if source else [])
                return {'status':'cached','job_id':job_id,'message':'相同输入已分析，已记录本次调用并复用历史结果。'}
            if not selected and not targets:
                coverage.update(completed_chunks=0,completed_messages=0)
                job_id=self._record_short_job(conn,account_id,conversation_id,feature,model,config,options,fingerprint,context_key,coverage,'empty','本次范围没有需要分析的消息。')
                return {'status':'empty','job_id':job_id,'message':'没有需要分析的消息；本次调用已记录。'}
            pending=conn.execute("SELECT id FROM ai_jobs WHERE conversation_id=? AND feature=? AND status IN ('queued','running')",(conversation_id,feature)).fetchone()
            if pending: return {'status':'existing','job_id':pending[0]}
            chunks=[];chunk_targets=[]
            for target in targets or ['']:
                chunk=[];size=0
                material=[item for item in selected if not target or target in (item['sender_qq'],item['sender_key'])]
                for item in material:
                    safe={key:value for key,value in item.items() if key not in ('content_hash','media')}
                    safe['media']=[{'index':i,'type':m.get('type'),'filename':m.get('filename','')} for i,m in enumerate(item['media'])]
                    parts=[item['text'][i:i+5000] for i in range(0,max(len(item['text']),1),5000)]
                    for part_number,text in enumerate(parts):
                        value={**safe,'text':text,'part':part_number+1,'parts':len(parts)};cost=len(encode(value))
                        if chunk and size+cost>budget['chunk_chars']:chunks.append(chunk);chunk_targets.append(target);chunk=[];size=0
                        chunk.append(value);size+=cost
                if chunk:chunks.append(chunk);chunk_targets.append(target)
            job_id=identifier();stamp=now()
            coverage['chunks']=len(chunks)
            conn.execute('INSERT INTO ai_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(job_id,account_id,conversation_id,feature,'queued',fingerprint,context_key,encode(model),encode(config),encode(options),encode(coverage),stamp,stamp,''))
            conn.executemany('INSERT INTO ai_chunks(job_id,idx,status,messages_json,watch_target) VALUES(?,?,?,?,?)',[(job_id,i,'pending',encode(chunk),chunk_targets[i]) for i,chunk in enumerate(chunks)])
        return {'status':'queued','job_id':job_id,'coverage':{k:v for k,v in coverage.items() if k not in ('hashes','previous','memory')}}

    def _job(self,conn,job_id):
        row=conn.execute('SELECT * FROM ai_jobs WHERE id=?',(job_id,)).fetchone()
        if not row: raise CoreError('NOT_FOUND','分析任务不存在。')
        return dict(row)

    def next_chunk(self,job_id):
        budget=self.budget();local=datetime.now(timezone(timedelta(hours=8)));day=local.strftime('%Y-%m-%d')
        with self.storage.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            job=self._job(conn,job_id)
            if job['status'] not in ('queued','running'): return {'done':True,'status':job['status']}
            if conn.execute("SELECT 1 FROM ai_chunks WHERE job_id=? AND status='running'",(job_id,)).fetchone(): raise CoreError('AI_BUSY','此任务已有模型请求在运行。')
            row=conn.execute("SELECT * FROM ai_chunks WHERE job_id=? AND status='pending' ORDER BY idx LIMIT 1",(job_id,)).fetchone()
            if not row:return {'done':True,'status':'ready'}
            config=json.loads(job['settings_json']);coverage=json.loads(job['coverage_json']);messages=json.loads(row['messages_json'])
            previous=list(coverage['previous'])
            for completed in conn.execute("SELECT idx,result_json FROM ai_chunks WHERE job_id=? AND status='completed' ORDER BY idx",(job_id,)):
                for n,item in enumerate(json.loads(completed['result_json']).get('items',[])):
                    previous.append({**item,'id':f"pending:{job_id}:{completed['idx']}:{n}"})
            if row['watch_target']:previous=[item for item in previous if item.get('subject')==row['watch_target']]
            previous=previous[-40:]
            relevant_memory=[item for item in coverage['memory'] if not row['watch_target'] or item.get('kind')!='person' or item.get('subject')==row['watch_target']]
            options={**json.loads(job['options_json']),
                     'confirmed_memory':[item for item in relevant_memory if not item.get('kind')],
                     'long_term_memory':[item for item in relevant_memory if item.get('kind')],
                     'watch_target':row['watch_target']}
            system=system_prompt(job['feature']);user=user_prompt(job['feature'],config,messages,previous,options)
            # UTF-8 byte count is a deliberately conservative bound when no tokenizer is installed.
            has_images=config['images'] and any(media.get('type')=='image' for message in messages for media in message['media'])
            estimated=len(system.encode())+len(user.encode())+512+(50000 if has_images else 0)
            entry=self.ledger.reserve(conn,budget,json.loads(job['model_json']),job_id,row['idx'],estimated,budget['output_tokens'])
            attempt=entry['attempt']
            conn.execute("UPDATE ai_chunks SET status='running',attempt=?,previous_json=? WHERE job_id=? AND idx=?",(attempt,encode(previous),job_id,row['idx']))
            conn.execute("UPDATE ai_jobs SET status='running',updated_at=? WHERE id=?",(now(),job_id))
        images=[]
        if config['images']:
            try:
                for message in messages:
                    for media in message['media']:
                        if media['type']!='image' or len(images)>=2:continue
                        asset=self.service.read_media(message_id=message['id'],media_index=media['index'],account_id=job['account_id'])
                        if asset['available']:images.append({'message_id':message['id'],'media_index':media['index'],'data_url':asset['data_url']})
            except Exception:
                self.fail(job_id,'本地图片读取失败，未发起模型请求。',attempt=attempt,known_not_sent=True)
                raise
        with self.storage.connect() as conn:
            coverage['images_sent']=coverage.get('images_sent',0)+len(images)
            conn.execute('UPDATE ai_jobs SET coverage_json=? WHERE id=?',(encode(coverage),job_id))
        return {'done':False,'job_id':job_id,'index':row['idx'],'total':coverage['chunks'],'attempt':attempt,'system':system,'user':user,'images':images,'max_tokens':budget['output_tokens'],'model':json.loads(job['model_json']),'media_results':json.loads(row['media_results_json'])}

    def _settle(self,conn,attempt,usage=None,known_not_sent=False,state='completed'):
        return self.ledger.settle(conn,attempt,usage,known_not_sent,state)

    def _validate(self,payload,messages,previous,feature,target=''):
        if isinstance(payload,str):
            raw=payload.strip()
            if raw.startswith('```'):raw=re.sub(r'^```(?:json)?\s*|\s*```$','',raw,flags=re.I)
            try:payload=json.loads(raw)
            except (ValueError,TypeError):raise CoreError('AI_OUTPUT_INVALID','模型没有返回有效 JSON，可重试此分块。')
        if not isinstance(payload,dict) or not isinstance(payload.get('summary'),str) or not isinstance(payload.get('items'),list) or len(payload['items'])>30:
            raise CoreError('AI_OUTPUT_INVALID','模型结果结构不符合功能契约。')
        allowed={item['id']:item for item in messages};old={item['id']:item for item in previous};valid=[]
        for value in payload['items']:
            if not isinstance(value,dict):raise CoreError('AI_OUTPUT_INVALID','模型条目格式无效。')
            evidence=value.get('evidence_ids')
            if not isinstance(evidence,list) or not evidence or any(not isinstance(key,str) or key not in allowed for key in evidence):raise CoreError('AI_EVIDENCE_INVALID','模型引用了未提供或跨群的证据，结果未收录。')
            for key in ('title','body'):
                if not isinstance(value.get(key),str) or not value[key].strip():raise CoreError('AI_OUTPUT_INVALID','模型缺少标题或正文。')
            if feature=='work' and all(re.fullmatch(r'.{0,30}?(?:收到|好的|明白)[！!。\s]*',allowed[key]['text']) for key in evidence):continue
            item={key:str(value.get(key) or '')[:limit] for key,limit in (('title',160),('body',4000),('category',100),('owner',160),('due_text',300),('uncertainty',1000),('subject',160))}
            if feature=='identity':
                item['category']='我的角色';item['subject']='group'
            if target:
                if not any(target in (allowed[key]['sender_qq'],allowed[key]['sender_key']) for key in evidence):raise CoreError('AI_EVIDENCE_INVALID','特别关心证据没有覆盖本次指定的人。')
                item['subject']=target
            item['evidence_ids']=list(dict.fromkeys(evidence));item['status']=value.get('status') if value.get('status') in ('proposed','cancelled','completion_candidate') else 'proposed'
            item['priority']=value.get('priority') if value.get('priority') in ('low','normal','high') else 'normal'
            item['due_at']=None
            if value.get('due_at'):
                try:
                    parsed=datetime.fromisoformat(value['due_at'])
                    if parsed.tzinfo and item['due_text']:item['due_at']=parsed.isoformat()
                except (ValueError,TypeError): pass
            drafts=value.get('drafts',[])
            if not isinstance(drafts,list) or any(not isinstance(text,str) for text in drafts):raise CoreError('AI_OUTPUT_INVALID','回复草稿结构无效。')
            item['drafts']=[text[:3000] for text in drafts[:3]]
            update=value.get('update_id') or ''
            if update and update not in old:raise CoreError('AI_OUTPUT_INVALID','模型试图修改未提供的历史条目。')
            item['update_id']=update
            media_index=value.get('media_index',-1)
            if not integer(media_index,-1,1000):raise CoreError('AI_OUTPUT_INVALID','图片索引无效。')
            if media_index>=0 and not any(media['index']==media_index and media['type']=='image' for media in allowed[evidence[0]]['media']):raise CoreError('AI_OUTPUT_INVALID','图片推荐没有有效来源。')
            item['media_index']=media_index
            valid.append(item)
        return {'summary':payload['summary'][:3000],'items':valid}

    def commit_chunk(self,job_id,attempt,result,usage=None):
        error=None
        with self.storage.connect() as conn:
            job=self._job(conn,job_id)
            row=conn.execute("SELECT * FROM ai_chunks WHERE job_id=? AND attempt=? AND status='running'",(job_id,attempt)).fetchone()
            if not row:raise CoreError('AI_STALE','此模型响应已经过期或已提交。')
            self._settle(conn,attempt,usage)
            try:validated=self._validate(result,json.loads(row['messages_json']),json.loads(row['previous_json']),job['feature'],row['watch_target'])
            except CoreError as exc:error=exc
            if error:
                detail=conn.execute('SELECT details_json FROM ai_usage WHERE attempt=?',(attempt,)).fetchone()
                if detail:
                    metadata=json.loads(detail[0]);metadata['state']='invalid_output'
                    conn.execute('UPDATE ai_usage SET details_json=? WHERE attempt=?',(encode(metadata),attempt))
                conn.execute("UPDATE ai_chunks SET status='failed' WHERE job_id=? AND idx=?",(job_id,row['idx']))
                conn.execute("UPDATE ai_jobs SET status='failed',error=?,updated_at=? WHERE id=?",(str(error),now(),job_id))
            else:conn.execute("UPDATE ai_chunks SET status='completed',result_json=? WHERE job_id=? AND idx=?",(encode(validated),job_id,row['idx']))
        if error:raise error
        return {'committed':True}

    def fail(self,job_id,message='分析失败，可重试未完成分块。',attempt='',cancelled=False,known_not_sent=False,usage=None):
        with self.storage.connect() as conn:
            job=self._job(conn,job_id)
            if job['status']=='completed':return {'status':'completed'}
            if attempt:self._settle(conn,attempt,usage,known_not_sent,'cancelled' if cancelled else 'failed')
            conn.execute("UPDATE ai_chunks SET status='failed' WHERE job_id=? AND status='running'",(job_id,))
            conn.execute('UPDATE ai_jobs SET status=?,error=?,updated_at=? WHERE id=?',('cancelled' if cancelled else 'failed',str(message)[:300],now(),job_id))
        return self.finish(job_id,partial=True)

    def finish(self,job_id,partial=False):
        with self.storage.connect() as conn:
            conn.execute('BEGIN IMMEDIATE');job=self._job(conn,job_id)
            if job['status']=='completed':return {'status':'completed','job_id':job_id}
            frozen=json.loads(job['coverage_json'])['hashes']
            keys=list(frozen)
            for offset in range(0,len(keys),400):
                batch=keys[offset:offset+400]
                current=conn.execute(f"SELECT {MESSAGE_COLUMNS} FROM messages WHERE conversation_id=? AND account_id=? AND id IN ({','.join('?' for _ in batch)})",(job['conversation_id'],job['account_id'],*batch)).fetchall()
                if len(current)!=len(batch) or any(projection(row)['content_hash']!=frozen[row['id']] for row in current):
                    raise CoreError('AI_SOURCE_CHANGED','分析期间消息已变化，结果未合入历史。请重新分析最新消息。')
            rows=conn.execute('SELECT * FROM ai_chunks WHERE job_id=? ORDER BY idx',(job_id,)).fetchall()
            done=[row for row in rows if row['status']=='completed']
            if len(done)!=len(rows) and not partial:raise CoreError('AI_INCOMPLETE','尚有未完成分块，不能标记分析成功。')
            stamp=now();results=[json.loads(row['result_json']) for row in done];summaries=[value['summary'] for value in results]
            pending_ids={}
            for chunk,result in zip(done,results):
                for n,item in enumerate(result['items']):
                    temporary_id=f"pending:{job_id}:{chunk['idx']}:{n}"
                    item['update_id']=pending_ids.get(item['update_id'],item['update_id'])
                    key=digest([job['feature'],sorted(item['evidence_ids']),item['title']])
                    previous=conn.execute('SELECT * FROM ai_items WHERE conversation_id=? AND feature=? AND (item_key=? OR id=?)',(job['conversation_id'],job['feature'],key,item['update_id'])).fetchone()
                    if previous:
                        pending_ids[temporary_id]=previous['id']
                        user=json.loads(previous['user_json']);old=json.loads(previous['data_json'])
                        if user.get('locked') or user.get('user_status') in ('confirmed','completed','ignored','rejected') or user.get('forgotten'):continue
                        item['evidence_ids']=list(dict.fromkeys([*old['evidence_ids'],*item['evidence_ids']]))
                        conn.execute('UPDATE ai_items SET data_json=?,updated_at=? WHERE id=?',(encode(item),stamp,previous['id']))
                    else:
                        item_id=identifier();pending_ids[temporary_id]=item_id
                        conn.execute('INSERT INTO ai_items VALUES(?,?,?,?,?,?,?,?)',(item_id,job['conversation_id'],job['feature'],key,encode(item),'{}',stamp,stamp))
            coverage=json.loads(job['coverage_json']);coverage['completed_chunks']=len(done)
            for person in coverage.get('watch_people',[]):
                planned=[chunk for chunk in rows if chunk['watch_target']==person['target']]
                person['completed_chunks']=sum(chunk['status']=='completed' for chunk in planned)
                person['chunks']=len(planned)
                person['status']='no_messages' if not planned else 'completed' if person['completed_chunks']==len(planned) else 'partial'
            coverage['completed_messages']=len({message['id'] for chunk in done for message in json.loads(chunk['messages_json'])})
            public_coverage={k:v for k,v in coverage.items() if k not in ('hashes','previous','memory')}
            merged=self._items(conn,job['conversation_id'],job['feature'])
            conn.execute('INSERT INTO ai_reports VALUES(?,?,?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET summary=excluded.summary,items_json=excluded.items_json,coverage_json=excluded.coverage_json',(job_id,job['conversation_id'],job['feature'],'\n'.join(summaries),encode(merged),encode(public_coverage),stamp))
            self._refresh_memories(conn,job,merged,done,stamp)
            complete=len(done)==len(rows)
            if job['feature']=='identity' and complete and merged:
                inferred=next((item['title'].strip() for item in merged if item.get('category')=='我的角色' and item.get('title','').strip()),'')[:1000]
                if inferred:
                    current=conn.execute('SELECT settings_json FROM ai_group_settings WHERE conversation_id=?',(job['conversation_id'],)).fetchone()
                    stored=json.loads(current[0] if current else job['settings_json'])
                    config={key:stored.get(key,value) for key,value in DEFAULT_GROUP.items()};config['role']=inferred
                    conn.execute('INSERT INTO ai_group_settings VALUES(?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET settings_json=excluded.settings_json,updated_at=excluded.updated_at',(job['conversation_id'],encode(config),stamp))
                    conn.execute('INSERT INTO conversation_preferences VALUES(?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET role_text=excluded.role_text,updated_at=excluded.updated_at',(job['conversation_id'],inferred,stamp))
            if complete:
                conn.executemany('INSERT INTO ai_coverage VALUES(?,?,?,?,?) ON CONFLICT(conversation_id,feature,message_id) DO UPDATE SET digest=excluded.digest,context_key=excluded.context_key',[(job['conversation_id'],job['feature'],key,value,job['context_key']) for key,value in coverage['hashes'].items()])
                conn.execute("UPDATE ai_jobs SET status='completed',updated_at=?,error='' WHERE id=?",(stamp,job_id))
        if complete and not rows:self.ledger.reuse(json.loads(job['model_json']),job_id,'empty')
        if complete and job['feature']=='collection' and json.loads(job['settings_json'])['auto_favorite']:
            for item in merged:
                if item.get('user_status') not in ('saved','rejected'):
                    try:self.update_item(item['id'],job['conversation_id'],job['account_id'],action='save_favorite',automatic=True)
                    except CoreError:break
        return {'status':'completed' if complete else job['status'],'job_id':job_id,'coverage':public_coverage}

    def resume(self,job_id,account_id,conversation_id,model,platform='qq'):
        self.group(conversation_id,account_id,platform)
        with self.storage.connect() as conn:
            job=self._job(conn,job_id)
            if job['account_id']!=account_id or job['conversation_id']!=conversation_id:raise CoreError('NOT_FOUND','本群不存在该分析。')
            if json.loads(job['model_json'])!=model:raise CoreError('MODEL_CHANGED','请选择原模型继续；或用新模型重新分析。')
            if job['status']=='completed':return {'status':'cached','job_id':job_id}
            if job['status']=='running':raise CoreError('AI_BUSY','分析仍在进行。')
            conn.execute("UPDATE ai_chunks SET status='pending' WHERE job_id=? AND status IN ('failed','running')",(job_id,))
            conn.execute("UPDATE ai_jobs SET status='queued',error='',updated_at=? WHERE id=?",(now(),job_id))
        return {'status':'queued','job_id':job_id}

    def history(self,conversation_id,account_id,platform='qq',feature='',job_id='',job_page=1,job_page_size=20,item_page=1,item_page_size=20):
        self.group(conversation_id,account_id,platform)
        if feature and feature not in FEATURES:raise CoreError('INVALID_PARAMS','分析功能无效。')
        if not integer(job_page,1,100000) or not integer(job_page_size,1,50) or not integer(item_page,1,100000) or not integer(item_page_size,1,50):
            raise CoreError('INVALID_PARAMS','历史分页参数无效。')
        with self.storage.connect() as conn:
            job_where='conversation_id=? AND account_id=?';job_params=[conversation_id,account_id]
            if feature:job_where+=' AND feature=?';job_params.append(feature)
            job_total=conn.execute(f'SELECT count(*) FROM ai_jobs WHERE {job_where}',job_params).fetchone()[0]
            jobs=[]
            for row in conn.execute(f'SELECT id,feature,status,model_json,created_at,updated_at,error,coverage_json FROM ai_jobs WHERE {job_where} ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',(*job_params,job_page_size,(job_page-1)*job_page_size)):
                value=dict(row);value['model']=json.loads(value.pop('model_json'))['model'];value['coverage']={k:v for k,v in json.loads(value.pop('coverage_json')).items() if k not in ('hashes','previous','memory')}
                try:value['duration_seconds']=max(0,round((datetime.fromisoformat(value['updated_at'])-datetime.fromisoformat(value['created_at'])).total_seconds(),3))
                except (ValueError,TypeError):value['duration_seconds']=0
                value['feature_name']=FEATURES[value['feature']][0]
                usage=conn.execute('SELECT sum(charged),sum(input_tokens),sum(output_tokens),sum(CASE WHEN status=\'unknown\' THEN 1 ELSE 0 END) FROM ai_usage WHERE job_id=?',(value['id'],)).fetchone()
                page=self.ledger.list(job_id=value['id'],limit=200)
                value['calls']=page['items'];value['calls_has_more']=page['has_more']
                costs={};unknown=0
                for rate in conn.execute("SELECT coalesce(json_extract(prices_json,'$.currency'),'未记录币种') currency,sum(cost) cost,sum(CASE WHEN cost IS NULL THEN 1 ELSE 0 END) unknown FROM ai_usage WHERE job_id=? GROUP BY currency",(value['id'],)):
                    if rate['cost'] is not None:costs[rate['currency']]=rate['cost']
                    unknown+=rate['unknown']
                value['usage']={'charged_tokens':usage[0] or 0,'input_tokens':usage[1],'output_tokens':usage[2],'unknown_calls':usage[3] or 0,'cost_totals':costs,'unknown_price_calls':unknown};jobs.append(value)
            all_items=self._items(conn,conversation_id,feature or None)
            report=None
            if job_id:
                row=conn.execute('SELECT * FROM ai_reports WHERE job_id=? AND conversation_id=? '+('AND feature=?' if feature else ''),(job_id,conversation_id,*([feature] if feature else []))).fetchone()
                if row:
                    report_items=json.loads(row['items_json']);report={'summary':row['summary'],'items':report_items,'coverage':json.loads(row['coverage_json'])}
            else:
                row=conn.execute('SELECT * FROM ai_reports WHERE conversation_id=? '+('AND feature=? ' if feature else '')+'ORDER BY created_at DESC LIMIT 1',[conversation_id,*([feature] if feature else [])]).fetchone()
                if row:report={'summary':row['summary'],'coverage':json.loads(row['coverage_json'])}
                report_items=all_items
            if not report:report_items=all_items if not job_id else []
            item_total=len(report_items);start=(item_page-1)*item_page_size;page_items=report_items[start:start+item_page_size]
            if report:report['items']=page_items
            memories=conn.execute('SELECT kind,count(*) total,count(DISTINCT CASE WHEN kind=\'person\' THEN subject END) people FROM ai_memories WHERE conversation_id=? GROUP BY kind',(conversation_id,)).fetchall()
        return {'jobs':jobs,'items':page_items,'report':report,
                'pagination':{'jobs':{'page':job_page,'page_size':job_page_size,'total':job_total,'has_more':job_page*job_page_size<job_total},
                              'items':{'page':item_page,'page_size':item_page_size,'total':item_total,'has_more':item_page*item_page_size<item_total}},
                'memory':{'items':sum(row['total'] for row in memories),'people':sum(row['people'] or 0 for row in memories)}}

    def update_item(self,item_id,conversation_id,account_id,action,correction='',platform='qq',automatic=False):
        self.group(conversation_id,account_id,platform)
        if action not in ('confirmed','completed','ignored','rejected','lock','unlock','correct','forget','save_favorite','undo_favorite'):raise CoreError('INVALID_PARAMS','结果操作无效。')
        if not isinstance(correction,str) or len(correction)>4000:raise CoreError('INVALID_PARAMS','更正内容过长。')
        with self.storage.connect() as conn:
            row=conn.execute('SELECT * FROM ai_items WHERE id=? AND conversation_id=?',(item_id,conversation_id)).fetchone()
            if not row:raise CoreError('NOT_FOUND','本群不存在该条结果。')
            data=json.loads(row['data_json']);user=json.loads(row['user_json'])
            if action in ('lock','unlock'):user['locked']=action=='lock'
            elif action=='correct':user.update(correction=correction,locked=True)
            elif action=='forget':user.update(forgotten=True,locked=True,user_status='ignored',correction='')
            elif action not in ('save_favorite','undo_favorite'):user['user_status']=action
        if action in ('save_favorite','undo_favorite'):
            config=self.get_group(conversation_id,account_id,platform)
            if row['feature']!='collection':raise CoreError('INVALID_PARAMS','该项不是收藏候选。')
            if action=='save_favorite':
                with self.storage.connect() as conn:
                    today=datetime.now(timezone.utc).strftime('%Y-%m-%d')
                    saved=conn.execute("SELECT count(*) FROM ai_items WHERE conversation_id=? AND feature='collection' AND user_json LIKE ? AND updated_at LIKE ?",(conversation_id,'%"user_status":"saved"%',today+'%')).fetchone()[0]
                    stored=conn.execute('SELECT coalesce(sum(length(data)),0) FROM media_assets WHERE sha256 IN (SELECT asset_id FROM favorites WHERE media_index>=0)').fetchone()[0]
                if saved>=config['favorite_daily_limit'] or stored>=config['favorite_storage_mb']*1048576:raise CoreError('FAVORITE_QUOTA','本群收藏日配额或图片存储配额已达到。')
            self.service.set_favorite(data['evidence_ids'][0],action=='save_favorite',account_id,platform,data.get('media_index',-1))
            user.update(user_status='saved' if action=='save_favorite' else 'rejected',automatic=automatic)
        with self.storage.connect() as conn:
            conn.execute('UPDATE ai_items SET user_json=?,updated_at=? WHERE id=?',(encode(user),now(),item_id))
            if action=='forget':
                # Forget cached copies too: retained accounting contains no chat text.
                setting=conn.execute('SELECT settings_json FROM ai_group_settings WHERE conversation_id=?',(conversation_id,)).fetchone()
                stored=json.loads(setting[0]) if setting else DEFAULT_GROUP
                config={key:stored.get(key,value) for key,value in DEFAULT_GROUP.items()};config['remember']=False
                conn.execute('INSERT INTO ai_group_settings VALUES(?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET settings_json=excluded.settings_json,updated_at=excluded.updated_at',(conversation_id,encode(config),now()))
                conn.execute("UPDATE ai_items SET data_json=? WHERE id=?",(encode({'title':'已忘记','body':'','evidence_ids':[],'category':'','media_index':-1}),item_id))
                for job in conn.execute('SELECT id,feature,coverage_json FROM ai_jobs WHERE conversation_id=?',(conversation_id,)).fetchall():
                    coverage=json.loads(job['coverage_json'])
                    references=[*coverage.get('previous',[]),*coverage.get('memory',[])]
                    if job['feature']=='profile' or any(value.get('id')==item_id for value in references):
                        conn.execute('DELETE FROM ai_reports WHERE job_id=?',(job['id'],))
                        conn.execute('DELETE FROM ai_chunks WHERE job_id=?',(job['id'],))
                        conn.execute('DELETE FROM ai_jobs WHERE id=?',(job['id'],))
                for report in conn.execute('SELECT job_id,items_json FROM ai_reports WHERE conversation_id=?',(conversation_id,)).fetchall():
                    values=[item for item in json.loads(report['items_json']) if item['id']!=item_id]
                    conn.execute('UPDATE ai_reports SET items_json=? WHERE job_id=?',(encode(values),report['job_id']))
                conn.execute("DELETE FROM ai_memories WHERE conversation_id=? AND (memory_key=? OR feature='profile')",(conversation_id,'item:'+item_id))
            else:
                setting=conn.execute('SELECT settings_json FROM ai_group_settings WHERE conversation_id=?',(conversation_id,)).fetchone()
                if not setting or json.loads(setting[0]).get('remember',True):
                    item={**data,**user,'id':item_id};subject=item.get('subject') or 'group';kind='person' if subject not in ('','group') else 'group';stamp=now()
                    material={key:item.get(key) for key in ('id','title','body','category','evidence_ids','uncertainty','user_status','correction') if item.get(key) not in (None,'',[])}
                    self._save_memory(conn,conversation_id,'item:'+item_id,kind,subject,row['feature'],material,'user',stamp)
        return {'updated':True}

    def save_media_result(self,job_id,index,key,text):
        if not isinstance(text,str) or len(text)>12000:raise CoreError('INVALID_PARAMS','媒体识别结果过长。')
        with self.storage.connect() as conn:
            self._job(conn,job_id)
            row=conn.execute('SELECT media_results_json FROM ai_chunks WHERE job_id=? AND idx=?',(job_id,index)).fetchone()
            if not row:raise CoreError('NOT_FOUND','分块不存在。')
            values=json.loads(row[0]);values[str(key)[:200]]=text
            conn.execute('UPDATE ai_chunks SET media_results_json=? WHERE job_id=? AND idx=?',(encode(values),job_id,index))
        return {'saved':True}

    def schedules(self):
        current=int(time.time());due=[]
        with self.storage.connect() as conn:
            for row in conn.execute('SELECT s.*,c.account_id,g.settings_json FROM ai_schedules s JOIN conversations c ON c.id=s.conversation_id JOIN ai_group_settings g ON g.conversation_id=s.conversation_id WHERE s.next_at<=?',(current,)).fetchall():
                config=json.loads(row['settings_json'])
                if not config['schedule_minutes']:continue
                if row['feature']=='identity':continue
                if row['feature']=='profile' and not config['remember']:continue
                due.append({'conversation_id':row['conversation_id'],'account_id':row['account_id'],'feature':row['feature'],'options':{'mode':'incremental','limit':1000}})
                conn.execute('UPDATE ai_schedules SET next_at=? WHERE conversation_id=?',(current+config['schedule_minutes']*60,row['conversation_id']))
        return {'items':due}
