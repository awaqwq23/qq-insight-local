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
from .ai_compression import MODES, NOTICE, pack, compression_cost, evidence_pack
from . import ai_hierarchy as hierarchy
from . import ai_context


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

MESSAGE_COLUMNS='id,conversation_id,sent_at,sender_name,sender_qq,sender_key,text,media_json,reply_json,direction,content_kind'


class GroupAI:
    def __init__(self, service):
        self.service = service
        self.storage = service.storage
        self.ledger = UsageLedger(self)
        with self.storage.connect() as conn:
            conn.executescript(SCHEMA)
            self.storage._ensure_column(conn,'workspace_sessions','conversation_id',"TEXT NOT NULL DEFAULT ''")
            conn.execute('CREATE INDEX IF NOT EXISTS idx_workspace_sessions_conversation ON workspace_sessions(account_id,conversation_id,updated_at DESC)')
            self.storage._ensure_column(conn,'ai_chunks','previous_json',"TEXT NOT NULL DEFAULT '[]'")
            self.storage._ensure_column(conn,'ai_usage','details_json',"TEXT NOT NULL DEFAULT '{}'")
            self.storage._ensure_column(conn,'ai_chunks','watch_target',"TEXT NOT NULL DEFAULT ''")
            self.storage._ensure_column(conn,'ai_chunks','media_results_json',"TEXT NOT NULL DEFAULT '{}'")
            self.storage._ensure_column(conn,'ai_chunks','stage',"TEXT NOT NULL DEFAULT 'map'")
            self.storage._ensure_column(conn,'ai_chunks','level',"INTEGER NOT NULL DEFAULT 0")
            self.storage._ensure_column(conn,'ai_chunks','children_json',"TEXT NOT NULL DEFAULT '[]'")
            conn.execute("UPDATE ai_jobs SET status='interrupted',error='应用关闭时分析中断，可继续未完成分块' WHERE status IN ('running','queued')")
            conn.execute("UPDATE ai_chunks SET status='failed' WHERE status='running'")
            conn.execute("UPDATE ai_usage SET status='unknown',details_json=json_set(details_json,'$.state','unknown') WHERE status='reserved'")

    def group(self, conversation_id, account_id, platform='qq'):
        group = self.service._conversation(conversation_id, account_id, platform)
        if group['kind'] != 'group': raise CoreError('GROUP_REQUIRED','请先选择一个群聊。')
        return group

    def catalog(self):
        return {'version': VERSION, 'items':[{'id':key,'name':value[0],'requirement':value[1],'prompt':system_prompt(key),'schedulable':key not in ('identity','style')} for key,value in FEATURES.items()]}

    def get_group(self, conversation_id, account_id, platform='qq'):
        self.group(conversation_id, account_id, platform)
        with self.storage.connect() as conn:
            row = conn.execute('SELECT settings_json FROM ai_group_settings WHERE conversation_id=?',(conversation_id,)).fetchone()
            memory_rows=conn.execute('SELECT kind,count(*) total,count(DISTINCT CASE WHEN kind=\'person\' THEN subject END) people FROM ai_memories WHERE conversation_id=? GROUP BY kind',(conversation_id,)).fetchall()
        config = {**DEFAULT_GROUP, **(json.loads(row[0]) if row else {})}
        if hasattr(self.service,'chat_memory'):
            with self.storage.connect() as conn:config['remember']=config['remember'] and self.service.chat_memory.enabled(conn,conversation_id)
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
        if 'role' in settings:config['role_source']='manual'
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
        for key in ('remember','images','auto_favorite','hierarchical'):
            if key in settings:
                if type(settings[key]) is not bool: raise CoreError('INVALID_PARAMS','群设置开关无效。')
                config[key]=settings[key]
        if 'compression' in settings:
            if settings['compression'] not in MODES:raise CoreError('INVALID_PARAMS','消息压缩模式无效。')
            config['compression']=settings['compression']
        if 'output_chars' in settings:
            if not integer(settings['output_chars'],1,20000):raise CoreError('INVALID_PARAMS','输出字数须为1–20000的整数。')
            config['output_chars']=settings['output_chars']
        for key,low,high in (('favorite_daily_limit',1,100),('favorite_storage_mb',1,10000),('schedule_minutes',0,1440)):
            if key in settings:
                if not integer(settings[key],low,high) or (key=='schedule_minutes' and 0<settings[key]<5): raise CoreError('INVALID_PARAMS','频率至少5分钟，收藏配额应为有效整数。')
                config[key]=settings[key]
        if 'schedule_feature' in settings:
            if settings['schedule_feature'] not in FEATURES or settings['schedule_feature'] in ('identity','style'): raise CoreError('INVALID_PARAMS','定时分析功能无效。')
            config['schedule_feature']=settings['schedule_feature']
        with self.storage.connect() as conn:
            conn.execute('INSERT INTO ai_group_settings VALUES(?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET settings_json=excluded.settings_json,updated_at=excluded.updated_at',(conversation_id,encode(config),now()))
            if 'remember' in settings:
                agent=conn.execute('SELECT settings_json FROM conversation_agents WHERE conversation_id=?',(conversation_id,)).fetchone()
                if agent:
                    values=json.loads(agent[0]);values['remember']=config['remember']
                    conn.execute('UPDATE conversation_agents SET settings_json=?,updated_at=? WHERE conversation_id=?',(encode(values),now(),conversation_id))
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
        if hasattr(self.service,'chat_memory') and not self.service.chat_memory.enabled(conn,conversation_id):return []
        where="conversation_id=? AND kind<>'style'";params=[conversation_id]
        if exclude_feature:
            where+=' AND feature<>?';params.append(exclude_feature)
        if target:
            where+=" AND (kind='group' OR subject=?)";params.append(target)
        rows=conn.execute(f'SELECT memory_key,kind,subject,feature,data_json,source_job_id FROM ai_memories WHERE {where} ORDER BY updated_at DESC LIMIT 80',params).fetchall()
        result=[]
        for row in rows:
            value=json.loads(row['data_json'])
            if value.get('forgotten') or not (value.get('evidence_ids') or value.get('locked') or value.get('correction') or row['source_job_id']=='user'):continue
            result.append({**value,'memory_key':row['memory_key'],'kind':row['kind'],'subject':row['subject'],'feature':row['feature'],'from_user':row['source_job_id']=='user','origin_notice':'用户主动补充' if row['source_job_id']=='user' else '有来源的历史观察；当前未证实的旧经历不可当作本段事实。'})
        for item in result:
            if re.search(r'(?<![A-Za-z0-9_])p\d+(?![A-Za-z0-9_])',item.get('body','')):item['origin_notice']='旧记忆含未还原的局部人物编号，不能套用本轮people表；只作回源线索。'
        return result

    def _restore_people_labels(self,payload,people,messages):
        labels={key:(p.get('name') or p.get('qq') or p.get('uid')) for key,p in people.items() if (p.get('name') or p.get('qq') or p.get('uid')) and not any(re.search(r'(?<![A-Za-z0-9_])'+re.escape(key)+r'(?![A-Za-z0-9_])',m.get('text','')) for m in messages)}
        if not labels:return
        pattern=re.compile(r'(?<![A-Za-z0-9_])(?:'+'|'.join(sorted(map(re.escape,labels),key=len,reverse=True))+r')(?![A-Za-z0-9_])')
        def visit(value):
            if isinstance(value,dict):
                for key in ('summary','title','body','uncertainty','evaluation'):
                    if isinstance(value.get(key),str):value[key]=pattern.sub(lambda match:labels[match[0]],value[key])
                for key in ('items','people_memory','group_memory'):
                    if isinstance(value.get(key),list):
                        for child in value[key]:visit(child)
        visit(payload)

    def _save_memory(self,conn,conversation_id,key,kind,subject,feature,data,job_id,stamp):
        if job_id!='user' and not self.service.chat_memory.enabled(conn,conversation_id):return
        old=conn.execute('SELECT data_json FROM ai_memories WHERE conversation_id=? AND memory_key=?',(conversation_id,key)).fetchone()
        if job_id!='user' and old and (json.loads(old[0]).get('locked') or json.loads(old[0]).get('forgotten')):return
        conn.execute('''INSERT INTO ai_memories(conversation_id,memory_key,kind,subject,feature,data_json,source_job_id,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(conversation_id,memory_key) DO UPDATE SET
                        kind=excluded.kind,subject=excluded.subject,feature=excluded.feature,data_json=excluded.data_json,
                        source_job_id=excluded.source_job_id,updated_at=excluded.updated_at''',
                     (conversation_id,key,kind,subject,feature,encode(data),job_id,stamp,stamp))

    def _remember_people(self,conn,job,chunks,stamp):
        if not json.loads(job['settings_json']).get('remember',True):return
        grouped={};observed={}
        for chunk in chunks:
            if chunk['stage']!='map':continue
            messages={message['id']:message for message in json.loads(chunk['messages_json'])}
            for message in messages.values():
                subject=message.get('sender_qq') or message.get('sender_key')
                if not subject:continue
                group=message['conversation_id'];setting=conn.execute('SELECT settings_json FROM ai_group_settings WHERE conversation_id=?',(group,)).fetchone()
                if not self.service.chat_memory.enabled(conn,group):continue
                key=(group,subject);grouped.setdefault(key,[])
                observed.setdefault(key,{})[message['id']]={'name':message.get('sender_name',''),'sent_at':message['sent_at']}
            for person in json.loads(chunk['result_json']).get('people_memory',[]):
                # A mixed-scene inference cannot become a source-group fact just by slicing its citations.
                if len({messages[key]['conversation_id'] for key in person['evidence_ids']})!=1:continue
                for group in {messages[key]['conversation_id'] for key in person['evidence_ids']}:
                    # Cross-group extraction must still respect each source group's paused memory switch.
                    setting=conn.execute('SELECT settings_json FROM ai_group_settings WHERE conversation_id=?',(group,)).fetchone()
                    if not self.service.chat_memory.enabled(conn,group):continue
                    value={key:person[key] for key in ('title','body','uncertainty')}
                    value['evidence_ids']=[key for key in person['evidence_ids'] if messages[key]['conversation_id']==group]
                    value['source_job_id']=job['id'];value['at']=stamp
                    grouped.setdefault((group,person['subject']),[]).append(value)
        for (group,subject),values in grouped.items():
            key='auto:'+job['feature']+':'+subject
            old=conn.execute('SELECT data_json FROM ai_memories WHERE conversation_id=? AND memory_key=?',(group,key)).fetchone()
            data=json.loads(old[0]) if old else {}
            observations=list({digest([value['body'],value['evidence_ids']]):value for value in [*data.get('observations',[]),*values]}.values())[-12:]
            samples={**data.get('observed_messages',{}),**observed.get((group,subject),{})}
            samples=dict(sorted(samples.items(),key=lambda pair:pair[1]['sent_at'])[-60:])
            data.update(title='成员阶段画像 · 可继续完善',body='\n'.join(value['body']+('（待核实：'+value['uncertainty']+'）' if value.get('uncertainty') else '') for value in observations)[-6000:] or '已记录部分本人发言，可先查看来源；语气、兴趣、性格倾向和习惯尚待补充。',observations=observations,observed_messages=samples,stage='partial',last_analyzed_messages=len(observed.get((group,subject),{})),
                        evidence_ids=list(dict.fromkeys(key for value in observations for key in value['evidence_ids']))[-60:],
                        uncertainty='仅为聊天中可观察的表现；新旧说法可能因场景不同。请结合分段证据核实。')
            self._save_memory(conn,group,key,'person',subject,job['feature'],data,job['id'],stamp)

    def _remember_groups(self,conn,job,chunks,stamp):
        if not json.loads(job['settings_json']).get('remember',True):return
        grouped={}
        for chunk in chunks:
            if chunk['stage']!='map':continue
            messages={m['id']:m for m in json.loads(chunk['messages_json'])}
            groups={m['conversation_id'] for m in messages.values()}
            result=json.loads(chunk['result_json'])
            for group in groups:
                own=[m for m in messages.values() if m['conversation_id']==group]
                grouped.setdefault(group,{'messages':{},'observations':[]})['messages'].update({m['id']:m for m in own})
                observations=[value for value in result.get('group_memory',[]) if value['conversation_id']==group]
                if not observations and len(groups)==1 and result.get('summary'):
                    observations=[{'body':result['summary'],'evaluation':'仅为本段内容归纳，尚未独立核实。','evidence_ids':list(messages)[:10]}]
                grouped[group]['observations'].extend(observations)
        for group,values in grouped.items():
            conversation=conn.execute('SELECT kind FROM conversations WHERE id=?',(group,)).fetchone()
            if not conversation or conversation[0] not in ('group','c2c'):continue
            setting=conn.execute('SELECT settings_json FROM ai_group_settings WHERE conversation_id=?',(group,)).fetchone()
            if not self.service.chat_memory.enabled(conn,group):continue
            key='group:'+job['feature'];old=conn.execute('SELECT data_json FROM ai_memories WHERE conversation_id=? AND memory_key=?',(group,key)).fetchone()
            data=json.loads(old[0]) if old else {}
            observations=list({digest([v['body'],v.get('evaluation',''),v['evidence_ids']]):v for v in [*data.get('observations',[]),*values['observations']]}.values())[-12:]
            messages=list(values['messages'].values())
            data.update(title='群聊记忆与评价' if conversation[0]=='group' else '私聊关系与上下文记忆',body='\n'.join(value['body']+(' 评价：'+value['evaluation'] if value.get('evaluation') else '') for value in observations)[-6000:] or '已读取本会话记录；尚无足够证据评价关系和交流背景。',
                        observations=observations,last_analyzed_messages=len(messages),last_start=min(m['sent_at'] for m in messages),last_end=max(m['sent_at'] for m in messages),
                        evidence_ids=list(dict.fromkeys(key for value in observations for key in value['evidence_ids']))[-60:],uncertainty='群用途和氛围评价是有来源的暂定判断，不是群成员人格评价。')
            self._save_memory(conn,group,key,'group','group',job['feature'],data,job['id'],stamp)

    def memories(self,conversation_id,account_id,platform='qq'):
        self.service._conversation(conversation_id,account_id,platform)
        with self.storage.connect() as conn:
            rows=conn.execute('SELECT * FROM ai_memories WHERE conversation_id=? ORDER BY updated_at DESC LIMIT 200',(conversation_id,)).fetchall()
        return {'items':[{**json.loads(row['data_json']),'memory_key':row['memory_key'],'kind':row['kind'],'subject':row['subject'],'updated_at':row['updated_at']} for row in rows], 'limit':200}

    def update_memory(self,conversation_id,account_id,memory_key='',action='',correction='',platform='qq',kind='group',subject='group'):
        self.service._conversation(conversation_id,account_id,platform)
        if action not in ('correct','forget','unlock','remember') or not isinstance(correction,str) or len(correction)>6000 or (action in ('correct','remember') and not correction.strip()):raise CoreError('INVALID_PARAMS','记忆操作或更正内容无效。')
        with self.storage.connect() as conn:
            if action=='remember':
                if kind not in ('group','person') or not isinstance(subject,str) or not 1<=len(subject)<=120:raise CoreError('INVALID_PARAMS','记忆种类或人物标识无效。')
                if kind=='person' and not conn.execute('SELECT 1 FROM messages WHERE conversation_id=? AND account_id=? AND (sender_qq=? OR sender_key=?) LIMIT 1',(conversation_id,account_id,subject,subject)).fetchone():raise CoreError('NOT_FOUND','成员补充记忆请使用本会话已有成员的QQ或UID。')
                key='user:'+digest([kind,subject,correction])[:32]
                self._save_memory(conn,conversation_id,key,kind,subject if kind=='person' else 'group','user',{'title':'用户主动补充的记忆','body':correction.strip(),'locked':True,'evidence_ids':[],'provenance':'用户在当前问题主动补充；尚非聊天记录核验的事实。'},'user',now())
                conn.execute('DELETE FROM ai_contexts WHERE conversation_id=?',(conversation_id,))
                conn.execute("UPDATE conversation_agents SET learned_json='{}' WHERE conversation_id=?",(conversation_id,))
                return {'updated':True,'memory_key':key,'source':'user'}
            row=conn.execute('SELECT data_json FROM ai_memories WHERE conversation_id=? AND memory_key=?',(conversation_id,memory_key)).fetchone()
            if not row:raise CoreError('NOT_FOUND','本群不存在此记忆。')
            data=json.loads(row[0])
            if action=='correct':data.update(body=correction.strip(),correction=correction.strip(),locked=True,forgotten=False)
            elif action=='forget':data={'title':'已忘记并暂停此条记忆','body':'','locked':True,'forgotten':True}
            else:data.update(locked=False,forgotten=False)
            conn.execute('UPDATE ai_memories SET data_json=?,updated_at=? WHERE conversation_id=? AND memory_key=?',(encode(data),now(),conversation_id,memory_key))
            if action in ('correct','forget'):conn.execute('DELETE FROM ai_contexts WHERE conversation_id=?',(conversation_id,))
            if action in ('correct','forget'):conn.execute("UPDATE conversation_agents SET learned_json='{}' WHERE conversation_id=?",(conversation_id,))
        return {'updated':True}

    def delete_history(self,conversation_id,account_id,job_id,platform='qq'):
        self.group(conversation_id,account_id,platform)
        with self.storage.connect() as conn:
            job=self._job(conn,job_id)
            if job['conversation_id']!=conversation_id or job['account_id']!=account_id:raise CoreError('NOT_FOUND','本群不存在此分析。')
            if job['status'] not in ('failed','cancelled','interrupted'):raise CoreError('INVALID_PARAMS','只能删除失败、取消或中断的分析。')
            conn.execute('DELETE FROM ai_reports WHERE job_id=?',(job_id,));conn.execute('DELETE FROM ai_chunks WHERE job_id=?',(job_id,))
            # Keep only a ledger tombstone: deleting billing attribution would make spent tokens disappear.
            conn.execute("UPDATE ai_jobs SET status='deleted',coverage_json='{}',settings_json='{}',options_json='{}',error='',updated_at=? WHERE id=?",(now(),job_id))
        return {'deleted':True,'billing_retained':True}

    def _refresh_memories(self,conn,job,items,done,stamp):
        if not self.service.chat_memory.enabled(conn,job['conversation_id']):return
        config=json.loads(job['settings_json'])
        compressed=json.loads(job['options_json']).get('compression','off')!='off'
        if not config.get('remember',True):return
        for item in items:
            if item.get('forgotten'):continue
            subject=item.get('subject') or 'group';kind='style' if job['feature']=='style' else 'person' if subject not in ('','group') else 'group'
            if kind=='person':
                sources=[conn.execute('SELECT sender_qq,sender_key,conversation_id FROM messages WHERE id=?',(key,)).fetchone() for key in item.get('evidence_ids',[])]
                if not sources or any(not r or r['conversation_id']!=job['conversation_id'] or subject not in (r['sender_qq'],r['sender_key']) for r in sources):continue
            data={key:item.get(key) for key in ('id','title','body','category','evidence_ids','uncertainty','user_status','correction','drafts','locked') if item.get(key) not in (None,'',[])}
            self._save_memory(conn,job['conversation_id'],'item:'+item['id'],kind,subject,job['feature'],data,job['id'],stamp)
        grouped={}
        for chunk in done:
            result=json.loads(chunk['result_json']);subject=chunk['watch_target'] or 'group'
            if result.get('summary'):grouped.setdefault(subject,[]).append(result['summary'])
        for subject,summaries in grouped.items():
            kind='style' if job['feature']=='style' else 'person' if subject!='group' else 'group'
            data={'title':FEATURES[job['feature']][0]+'摘要','body':'\n'.join(summaries)[:6000],'evidence_ids':[]}
            if compressed:data['uncertainty']=NOTICE
            if json.loads(job['options_json']).get('hierarchical'):data['uncertainty']=(data.get('uncertainty','')+' '+hierarchy.NOTICE).strip()
            self._save_memory(conn,job['conversation_id'],f"summary:{job['feature']}:{subject}",kind,subject,job['feature'],data,job['id'],stamp)

    def _record_short_job(self,conn,account_id,conversation_id,feature,model,config,options,fingerprint,context_key,coverage,status,summary,items=None):
        job_id=identifier();stamp=now()
        conn.execute('INSERT INTO ai_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(job_id,account_id,conversation_id,feature,status,fingerprint,context_key,encode(model),encode(config),encode(options),encode(coverage),stamp,stamp,''))
        conn.execute('INSERT INTO ai_reports VALUES(?,?,?,?,?,?,?)',(job_id,conversation_id,feature,summary,encode(items or []),encode({key:value for key,value in coverage.items() if key not in ('hashes','previous','memory')}),stamp))
        return job_id

    def prepare(self,conversation_id,account_id,feature,model,options=None,platform='qq'):
        group=self.group(conversation_id,account_id,platform)
        if feature not in FEATURES: raise CoreError('INVALID_PARAMS','分析功能无效。')
        if not isinstance(model,dict) or not model.get('model') or any(key not in ('id','model','provider','endpoint_hash','pricing','routes','limits') for key in model): raise CoreError('MODEL_REQUIRED','请选择并保存一个模型。')
        self._model_limits(model)
        if options is not None and not isinstance(options,dict):raise CoreError('INVALID_PARAMS','分析选项格式无效。')
        options=dict(options or {})
        if feature=='profile' and options.get('person_id'):
            person=options['person_id']
            if not isinstance(person,str) or not re.fullmatch(r'(?:[0-9]{5,20}|u_[A-Za-z0-9_-]{3,100})',person):raise CoreError('INVALID_PARAMS','成员画像须选择完整QQ或UID。')
        if feature=='style':
            person=options.get('person_id','')
            if not isinstance(person,str) or not re.fullmatch(r'(?:[0-9]{5,20}|u_[A-Za-z0-9_-]{3,100})',person):raise CoreError('INVALID_PARAMS','人物风格须填写完整 QQ 号或 u_ 开头的 UID，不按昵称合并。')
            if options.get('cross_group') is not True:raise CoreError('INVALID_PARAMS','请明确选择当前账号的跨群人物分析范围。')
            options['scope']='account_groups_person'
            options['hierarchical']=True
        options['evidence_format']='aliases-v1'
        options['wire_format']='columns-v1'
        mode=options.get('mode','recent');limit=options.get('limit',500)
        if mode not in ('recent','time','incremental') or not integer(limit,1,10000): raise CoreError('INVALID_PARAMS','分析范围无效，最多10000条。')
        for key in ('goal','tone','length','sender','query'):
            if not isinstance(options.get(key,''),str) or len(options.get(key,''))>1000: raise CoreError('INVALID_PARAMS','分析选项格式无效。')
        current_group=self.get_group(conversation_id,account_id,platform)
        options.setdefault('compression',current_group['compression'])
        options.setdefault('output_chars',current_group['output_chars'])
        options.setdefault('hierarchical',current_group['hierarchical'])
        options.setdefault('context_reuse',True)
        if type(options['context_reuse']) is not bool:raise CoreError('INVALID_PARAMS','压缩上下文开关无效。')
        if type(options['hierarchical']) is not bool:raise CoreError('INVALID_PARAMS','分段汇总开关无效。')
        if options['compression'] not in MODES or not integer(options['output_chars'],1,20000):raise CoreError('INVALID_PARAMS','压缩模式或输出字数无效；字数须为1–20000的整数。')
        config={key:value for key,value in current_group.items() if key in DEFAULT_GROUP}
        config['effective_role']=current_group['effective_role']
        budget=self.budget()
        limits=self._model_limits(model)
        # A saved/verified large context can hold substantially more than the legacy 10k-character chunks.
        adaptive=limits.get('context_tokens',0)>32768 and limits.get('basis') in ('manual','official','metadata','reported')
        chunk_limit=budget['chunk_chars']
        if adaptive:
            output=min(budget['output_tokens'],limits.get('output_limit_tokens',limits.get('output_tokens',budget['output_tokens'])),limits.get('context_tokens',10000000)-1024)
            available=min(limits['context_tokens']-output-8192,limits.get('input_tokens',10000000)-8192,budget['per_run_tokens']-output-8192,180000)
            if limits.get('tpm_tokens'):available=min(available,int(limits['tpm_tokens']*.8)-output-8192)
            chunk_limit=max(2000,int(available*.7))
        with self.storage.connect() as conn:
            previous=self._items(conn,conversation_id,feature)
            confirmed=[item for item in self._items(conn,conversation_id,'profile') if config['remember'] and item.get('user_status')=='confirmed' and not item.get('forgotten')][:15]
            long_term=self._memories(conn,conversation_id,exclude_feature=feature) if config['remember'] else []
            memory=[*confirmed,*long_term]
            if config.get('role_source')!='manual':
                config['role_candidate']=config['role'];config['role']='';config['effective_role']=''
            if feature=='identity':
                previous=[p for p in previous if p.get('locked') or p.get('correction') or p.get('user_status')=='confirmed']
                memory=[m for m in memory if m.get('locked') or m.get('correction')]
                config.pop('role_candidate',None)
            if feature=='style':
                previous=[item for item in previous if item.get('subject')==options['person_id']]
                rows=conn.execute("SELECT m.* FROM ai_memories m JOIN conversations c ON c.id=m.conversation_id WHERE c.account_id=? AND c.platform=? AND c.kind='group' AND m.subject=? AND m.kind IN ('person','style') ORDER BY m.updated_at DESC LIMIT 60",(account_id,platform,options['person_id'])).fetchall() if config['remember'] else []
                memory=[{**json.loads(row['data_json']),'kind':row['kind'],'subject':row['subject'],'source_group':row['conversation_id']} for row in rows if not json.loads(row['data_json']).get('forgotten')]
                config.update(role='',effective_role='',self_names='',watch_people=[],watch_keywords=[],instructions='',interests='',category='其他',images=False)
            if feature=='profile' and options.get('person_id'):
                previous=[item for item in previous if item.get('subject')==options['person_id']]
                memory=[item for item in memory if item.get('subject') in ('group',options['person_id'])]
            previous=[item for item in previous if not item.get('forgotten')][:40]
            reuse_key=digest([VERSION,feature,config,model,{key:options.get(key,'') for key in ('goal','tone','sender','query','compression','output_chars','person_id','scope')},
                              [m for m in memory if m.get('locked') or m.get('correction')],[(v['id'],v.get('correction'),v.get('locked'),v.get('user_status')) for v in previous if v.get('locked') or v.get('user_status')]])
            options['reuse_key']=reuse_key
            context_key=digest([VERSION,feature,config,model,{key:options.get(key,'') for key in ('goal','tone','sender','query','compression','output_chars','hierarchical','person_id','scope','context_reuse')},memory,
                                [(item['id'],item.get('user_status'),item.get('correction'),item.get('locked')) for item in previous if item.get('locked') or item.get('user_status')]])
            where='m.conversation_id=? AND m.account_id=? AND m.platform=?';params=[conversation_id,account_id,platform]
            if feature=='style':
                where="m.account_id=? AND m.platform=? AND m.conversation_id IN (SELECT id FROM conversations WHERE kind='group' AND account_id=? AND platform=?) AND (m.sender_qq=? OR m.sender_key=?)"
                params=[account_id,platform,account_id,platform,options['person_id'],options['person_id']]
            if feature=='profile':
                where+=" AND m.direction<>'system' AND (m.sender_qq<>'' OR m.sender_key<>'')"
                if options.get('person_id'):
                    where+=' AND (m.sender_qq=? OR m.sender_key=?)';params.extend([options['person_id'],options['person_id']])
            if mode=='time':
                start,end=options.get('start'),options.get('end')
                if not integer(start,0,9999999999) or not integer(end,start+1,9999999999): raise CoreError('INVALID_PARAMS','请选择有效的开始和结束时间。')
                where+=' AND m.sent_at>=? AND m.sent_at<?';params.extend([start,end])
            for key,column in (('sender','m.sender_qq'),('query','m.text')):
                if options.get(key): where+=f" AND {column} LIKE ? ESCAPE '!'";params.append(self.service._like(options[key]))
            # Read compact projections; coverage uses actual content hashes, not send timestamps.
            targets=[options['person_id']] if feature=='style' else config['watch_people'] if feature=='watch' else []
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
            coverage={'selected':len(selected),'sent':len(selected),'folded':0,'media_or_unknown':missing,'images_sent':0,'has_more':remaining,'output_chars':options['output_chars'],
                      'start':selected[0]['sent_at'] if selected else 0,'end':selected[-1]['sent_at'] if selected else 0,'chunks':0,'watch_people':watch,'per_person_limit':quota,
                      'hashes':{item['id']:item['content_hash'] for item in selected},'previous':previous,'memory':memory}
            if feature=='style':coverage.update(scope='account_groups_person',person_id=options['person_id'],source_groups=len({item['conversation_id'] for item in selected}))
            if feature=='profile':coverage.update(scope='conversation_person' if options.get('person_id') else 'conversation_speakers',person_id=options.get('person_id',''),selected_people=len({m['sender_qq'] or m['sender_key'] for m in selected}))
            cached=conn.execute("SELECT id FROM ai_jobs WHERE fingerprint=? AND conversation_id=? AND feature=? AND status='completed' ORDER BY created_at DESC LIMIT 1",(fingerprint,conversation_id,feature)).fetchone()
            if cached:
                source=conn.execute('SELECT summary,items_json,coverage_json FROM ai_reports WHERE job_id=?',(cached[0],)).fetchone()
                if source and json.loads(source['coverage_json']).get('compression'):coverage['compression']=json.loads(source['coverage_json'])['compression']
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
            # A new merge call has overhead: do not turn a few short messages into two calls.
            memory_groups={cid for cid in {m['conversation_id'] for m in selected} if self.service.chat_memory.enabled(conn,cid)}
            reusable,_=ai_context.candidates(conn,account_id,[m for m in selected if m['conversation_id'] in memory_groups],min_savings=0) if options['context_reuse'] and config['remember'] and not config['images'] and len(encode(pack(selected,'off',True)[0]).encode())>ai_context.SMALL_CONTEXT_BYTES else ([],set())
            reused=set()
            cached_results={}
            # A neutral topic summary is not a completed portrait of every speaker.
            if feature=='profile':reusable=[]
            for cached in reusable:
                # Only neutral source summaries can be shared across tasks; task-specific results keep their own key.
                if cached['feature']!='context' and cached['reuse_key']!=reuse_key:continue
                chunk=[{**m,'media':[{'index':i,'type':media.get('type'),'filename':media.get('filename','')} for i,media in enumerate(m['media'])]} for m in selected if m['id'] in cached['hashes']]
                target=cached['result'].get('_watch_target','')
                if targets:
                    matching=[t for t in targets if all(t in (m['sender_qq'],m['sender_key']) for m in chunk)]
                    if len(matching)!=1:continue
                    target=matching[0]
                try:validated=self._validate(cached['result'],chunk,previous,'context' if cached['feature']=='context' else feature,target)
                except CoreError:continue
                cached_results[len(chunks)]=validated;chunks.append(chunk);chunk_targets.append(target);reused.update(cached['hashes'])
            if reused:options['hierarchical']=True
            coverage.update(reused_messages=len(reused),raw_messages=len(selected)-len(reused),context_notice='复用已分析且来源未变化的摘要，再结合新材料汇总；细节可回看原文。' if reused else '')
            for target in targets or ['']:
                chunk=[];size=0;seen=set();members=set()
                material=[item for item in selected if item['id'] not in reused and (not target or target in (item['sender_qq'],item['sender_key']))]
                if feature=='profile':material.sort(key=lambda m:(m['sender_qq'] or m['sender_key'],m['sent_at'],m['id']))
                for item in material:
                    safe={key:value for key,value in item.items() if key not in ('content_hash','media')}
                    safe['media']=[{'index':i,'type':m.get('type'),'filename':m.get('filename','')} for i,m in enumerate(item['media'])]
                    parts=[item['text'][i:i+5000] for i in range(0,max(len(item['text']),1),5000)]
                    for part_number,text in enumerate(parts):
                        value={**safe,'text':text,'part':part_number+1,'parts':len(parts)}
                        cost=compression_cost(value,options['compression'],seen,adaptive,True)
                        member=item['sender_qq'] or item['sender_key']
                        if chunk and (size+cost>chunk_limit or feature=='profile' and member not in members and len(members)>=8):
                            chunks.append(chunk);chunk_targets.append(target);chunk=[];size=0;seen=set();members=set()
                            cost=compression_cost(value,options['compression'],seen,adaptive,True)
                        chunk.append(value);size+=cost;members.add(member)
                if chunk:chunks.append(chunk);chunk_targets.append(target)
            job_id=identifier();stamp=now()
            coverage['chunks']=len(chunks)
            if options['hierarchical']:coverage['hierarchical']={'enabled':True,'map_chunks':len(chunks),'merge_calls':0,'levels':0,'notice':hierarchy.NOTICE}
            coverage['output_chars']=options['output_chars']
            if options['compression']!='off':
                coverage['compression']=self._compression_stats(chunks,options['compression'],True)
                coverage['sent']=coverage['compression']['sent_messages'];coverage['folded']=coverage['compression']['folded']
            conn.execute('INSERT INTO ai_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(job_id,account_id,conversation_id,feature,'queued',fingerprint,context_key,encode(model),encode(config),encode(options),encode(coverage),stamp,stamp,''))
            conn.executemany('INSERT INTO ai_chunks(job_id,idx,status,messages_json,watch_target) VALUES(?,?,?,?,?)',[(job_id,i,'pending',encode(chunk),chunk_targets[i]) for i,chunk in enumerate(chunks)])
            for index,result in cached_results.items():conn.execute("UPDATE ai_chunks SET status='completed',result_json=? WHERE job_id=? AND idx=?",(encode(result),job_id,index))
        return {'status':'queued','job_id':job_id,'coverage':{k:v for k,v in coverage.items() if k not in ('hashes','previous','memory')}}

    def _job(self,conn,job_id):
        row=conn.execute('SELECT * FROM ai_jobs WHERE id=?',(job_id,)).fetchone()
        if not row or row['status']=='deleted': raise CoreError('NOT_FOUND','分析任务不存在。')
        return dict(row)

    def _model_limits(self,model):
        limits=model.get('limits') or {}
        if not isinstance(limits,dict):raise CoreError('INVALID_PARAMS','模型容量格式无效。')
        for key,low,high in [('context_tokens',2048,10000000),('tpm_tokens',0,10000000),('output_tokens',512,1000000),('output_limit_tokens',512,1000000),('input_tokens',0,10000000)]:
            if key in limits and not integer(limits[key],low,high):raise CoreError('INVALID_PARAMS','模型容量额度无效。')
        return limits

    def _compression_stats(self,chunks,mode,columns=False):
        result={'mode':mode,'notice':NOTICE,'original_messages':0,'sent_messages':0,'folded':0,'shortened':0,'original_bytes':0,'compressed_bytes':0}
        for chunk in chunks:
            stats=pack(chunk,mode,columns)[3]
            for key in ('original_messages','sent_messages','folded','shortened','original_bytes','compressed_bytes'):result[key]+=stats[key]
        return result

    def _hierarchy_messages(self,children):
        lookup={message['id']:message for child in children for message in json.loads(child['messages_json'])}
        return [lookup[key] for key in hierarchy.references(children) if key in lookup]

    def _plan_hierarchy(self,conn,job):
        if not json.loads(job['options_json']).get('hierarchical'):return False
        rows=conn.execute('SELECT * FROM ai_chunks WHERE job_id=? ORDER BY idx',(job['id'],)).fetchall()
        if any(row['status']!='completed' for row in rows):return False
        index=max((row['idx'] for row in rows),default=-1)+1;created=0
        for target in dict.fromkeys(row['watch_target'] for row in rows):
            scoped=[row for row in rows if row['watch_target']==target];level=max(row['level'] for row in scoped)
            children=[row for row in scoped if row['level']==level]
            if level and len(children)==1:continue
            if level>=8:raise CoreError('MODEL_CONTEXT_LIMIT','汇总层数达到安全上限，请提高单段容量或缩小范围。')
            for offset in range(0,len(children),4):
                batch=children[offset:offset+4];messages=self._hierarchy_messages(batch)
                conn.execute("INSERT INTO ai_chunks(job_id,idx,status,messages_json,watch_target,stage,level,children_json) VALUES(?,?,'pending',?,?,'reduce',?,?)",(job['id'],index,encode(messages),target,level+1,encode([child['idx'] for child in batch])))
                index+=1;created+=1
        if created:
            coverage=json.loads(job['coverage_json']);coverage['chunks']+=created
            coverage['hierarchical'].update(merge_calls=sum(row['stage']=='reduce' for row in rows)+created,levels=max(row['level'] for row in rows)+1)
            conn.execute('UPDATE ai_jobs SET coverage_json=? WHERE id=?',(encode(coverage),job['id']))
        return bool(created)

    def next_chunk(self,job_id):
        budget=self.budget();local=datetime.now(timezone(timedelta(hours=8)));day=local.strftime('%Y-%m-%d')
        with self.storage.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            job=self._job(conn,job_id)
            if job['status'] not in ('queued','running'): return {'done':True,'status':job['status']}
            if conn.execute("SELECT 1 FROM ai_chunks WHERE job_id=? AND status='running'",(job_id,)).fetchone(): raise CoreError('AI_BUSY','此任务已有模型请求在运行。')
            row=conn.execute("SELECT * FROM ai_chunks WHERE job_id=? AND status='pending' ORDER BY idx LIMIT 1",(job_id,)).fetchone()
            if not row and self._plan_hierarchy(conn,job):
                job=self._job(conn,job_id);row=conn.execute("SELECT * FROM ai_chunks WHERE job_id=? AND status='pending' ORDER BY idx LIMIT 1",(job_id,)).fetchone()
            if not row:return {'done':True,'status':'ready'}
            config=json.loads(job['settings_json']);coverage=json.loads(job['coverage_json']);messages=json.loads(row['messages_json'])
            previous=list(coverage['previous'])
            if json.loads(job['options_json']).get('hierarchical'):
                previous=[item for item in previous if item.get('locked') or item.get('user_status') in ('confirmed','completed') or item.get('correction')]
            else:
                for completed in conn.execute("SELECT idx,result_json FROM ai_chunks WHERE job_id=? AND status='completed' ORDER BY idx",(job_id,)):
                    for n,item in enumerate(json.loads(completed['result_json']).get('items',[])):
                        previous.append({**item,'id':f"pending:{job_id}:{completed['idx']}:{n}"})
            if row['watch_target']:previous=[item for item in previous if item.get('subject')==row['watch_target']]
            previous=previous[-40:]
            relevant_memory=[item for item in coverage['memory'] if not row['watch_target'] or item.get('kind')!='person' or item.get('subject')==row['watch_target']]
            if job['feature']=='profile':
                actors={m['sender_qq'] or m['sender_key'] for m in messages}
                previous=[p for p in previous if p.get('subject') in actors or p.get('locked') or p.get('correction') or p.get('user_status') in ('confirmed','completed')]
                relevant_memory=[m for m in relevant_memory if m.get('subject') in actors or m.get('kind')=='group' and (m.get('locked') or m.get('from_user'))]
            options={**json.loads(job['options_json']),
                     'confirmed_memory':[item for item in relevant_memory if not item.get('kind')],
                     'long_term_memory':[item for item in relevant_memory if item.get('kind')],
                     'watch_target':row['watch_target']}
            options.pop('reuse_key',None)
            reduction=row['stage']=='reduce'
            children=[conn.execute('SELECT * FROM ai_chunks WHERE job_id=? AND idx=?',(job_id,index)).fetchone() for index in json.loads(row['children_json'])] if reduction else []
            requested_chars=options.get('output_chars',500)
            def update_stage_chars():
                siblings=conn.execute('SELECT count(*) FROM ai_chunks WHERE job_id=? AND level=? AND watch_target=?',(job_id,row['level'],row['watch_target'])).fetchone()[0]
                options['output_chars']=requested_chars if reduction and siblings==1 else min(200,requested_chars) if options.get('hierarchical') else requested_chars
            update_stage_chars()
            model=json.loads(job['model_json']);limits=self._model_limits(model)
            output=min(budget['output_tokens'],limits.get('output_limit_tokens',limits.get('output_tokens',budget['output_tokens'])),limits.get('context_tokens',10000000)-1024)
            cap=min(limits.get('context_tokens',10000000)-output-1024,limits.get('input_tokens',10000000))
            if limits.get('tpm_tokens'):cap=min(cap,int(limits['tpm_tokens']*.8)-output-512)
            if config['images'] and not reduction:cap-=14000  # Reserve room for two bounded OCR descriptions.
            def stage_system():
                if reduction:return hierarchy.system(job['feature'],options['output_chars'])
                if options.get('hierarchical'):
                    value=hierarchy.system(job['feature'],options['output_chars']).replace('你是本群分段摘要的汇总助手','你是本群原消息分段读取助手').replace(hierarchy.NOTICE,'先把本段原消息整理成带当前证据的短摘要，供后续汇总；不推断未读的其他分段。')
                    if config.get('remember'):value+='\n可在顶层返回people_memory数组（最多20人），每项subject为本段发言者真实QQ/UID、title、body、uncertainty、evidence_ids。仅归纳有本人发言证据的表达习惯或明确偏好，不做人格诊断。同时返回group_memory数组，每个已读群一项：conversation_id须为群实际ID或输入groups中别名，body总结群主题与变化，evaluation给有证据的暂定交流评价，evidence_ids只来自该群。'
                    return value.replace('最多6项','最多3项') if output<1024 else value
                return system_prompt(job['feature'],options.get('output_chars'))
            system=stage_system()
            def prompt():return hierarchy.material(job['feature'],config,options,children,messages,previous)[0] if reduction else user_prompt(job['feature'],config,messages,previous,options)
            # History and memory are supplemental. Bound them before splitting current evidence.
            while len((system+user_prompt(job['feature'],config,[],previous,options)).encode())+512>cap*.6:
                if previous:previous.pop(0)
                elif options['long_term_memory']:options['long_term_memory']=options['long_term_memory'][1:]
                elif options['confirmed_memory']:options['confirmed_memory']=options['confirmed_memory'][1:]
                else:break
            user=prompt()
            while len((system+user).encode())+512>cap:
                if reduction and len(children)>1:
                    split=max(1,len(children)//2);rest_children=children[split:];children=children[:split]
                    messages=self._hierarchy_messages(children);rest=self._hierarchy_messages(rest_children)
                elif not reduction and len(messages)>1:
                    split=max(1,len(messages)//2);rest=messages[split:];messages=messages[:split]
                elif not reduction and len(messages[0]['text'])>128:
                    first=dict(messages[0]);second=dict(first);cut=len(first['text'])//2
                    first['text']=first['text'][:cut];second['text']=second['text'][cut:]
                    messages=[first];rest=[second]
                else:raise CoreError('MODEL_CONTEXT_LIMIT','Prompt、群设置和输出预留已超过容量，请提高上下文/TPM 或降低输出额度。')
                # Insert immediately after the current chunk, preserving evidence chronology.
                for pending in conn.execute('SELECT idx FROM ai_chunks WHERE job_id=? AND idx>? ORDER BY idx DESC',(job_id,row['idx'])).fetchall():
                    conn.execute('UPDATE ai_chunks SET idx=? WHERE job_id=? AND idx=?',(pending['idx']+1,job_id,pending['idx']))
                conn.execute("INSERT INTO ai_chunks(job_id,idx,status,messages_json,watch_target,stage,level,children_json) VALUES(?,?,'pending',?,?,?,?,?)",(job_id,row['idx']+1,encode(rest),row['watch_target'],row['stage'],row['level'],encode([child['idx'] for child in rest_children]) if reduction else '[]'))
                conn.execute('UPDATE ai_chunks SET messages_json=? WHERE job_id=? AND idx=?',(encode(messages),job_id,row['idx']))
                if reduction:conn.execute('UPDATE ai_chunks SET children_json=? WHERE job_id=? AND idx=?',(encode([child['idx'] for child in children]),job_id,row['idx']))
                coverage['chunks']+=1
                conn.execute('UPDATE ai_jobs SET coverage_json=? WHERE id=?',(encode(coverage),job_id))
                update_stage_chars();system=stage_system();user=prompt()
            # UTF-8 byte count is a deliberately conservative bound when no tokenizer is installed.
            has_images=config['images'] and not reduction and any(media.get('type')=='image' for message in messages for media in message['media'])
            estimated=len(system.encode())+len(user.encode())+512+(50000 if has_images else 0)
            entry=self.ledger.reserve(conn,budget,model,job_id,row['idx'],estimated,output)
            attempt=entry['attempt']
            conn.execute("UPDATE ai_chunks SET status='running',attempt=?,previous_json=? WHERE job_id=? AND idx=?",(attempt,encode(previous),job_id,row['idx']))
            conn.execute("UPDATE ai_jobs SET status='running',updated_at=? WHERE id=?",(now(),job_id))
        images=[]
        if config['images'] and not reduction:
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
        aliases={message['id']:f'm{i}' for i,message in enumerate(messages)} if reduction else {value:key for key,value in evidence_pack(messages,options.get('compression','off'))[1].items()} if options.get('compression','off')!='off' or options.get('evidence_format')=='aliases-v1' else {}
        return {'done':False,'job_id':job_id,'index':row['idx'],'total':coverage['chunks'],'attempt':attempt,'system':system,'user':user,'images':images,'max_tokens':output,'model':model,'media_results':json.loads(row['media_results_json']),'evidence_aliases':aliases,'stage':row['stage'],'level':row['level']}

    def _settle(self,conn,attempt,usage=None,known_not_sent=False,state='completed'):
        return self.ledger.settle(conn,attempt,usage,known_not_sent,state)

    def context(self,job_id,attempt,result=None,references=None):
        """Private desktop preparation: reusable source context before feature-specific analysis."""
        with self.storage.connect() as conn:
            job=self._job(conn,job_id)
            row=conn.execute("SELECT * FROM ai_chunks WHERE job_id=? AND attempt=? AND status='running'",(job_id,attempt)).fetchone()
            if not row:raise CoreError('AI_STALE','读取分块已失效。')
            if row['stage']!='map':return {'skip':True}
            original=json.loads(row['messages_json']);full=[];frozen=json.loads(job['coverage_json'])['hashes']
            counts=dict(conn.execute("SELECT json_extract(m.value,'$.id'),count(*) FROM ai_chunks ch,json_each(ch.messages_json) m WHERE ch.job_id=? AND ch.stage='map' GROUP BY json_extract(m.value,'$.id')",(job_id,)))
            for message in original:
                source=conn.execute(f'SELECT {MESSAGE_COLUMNS} FROM messages WHERE id=? AND account_id=?',(message['id'],job['account_id'])).fetchone()
                if not source or projection(source)['content_hash']!=frozen.get(message['id']):raise CoreError('AI_SOURCE_CHANGED','压缩期间来源变化，请重新读取。')
                full.append({**message,'content_hash':frozen[message['id']]})
                if counts.get(message['id'],0)>1:full[-1]['parts']=max(2,full[-1].get('parts',1))
            options=json.loads(job['options_json'])
            if not options.get('context_reuse',True):return {'skip':True,'reading_mode':'original','reason':'本次已选择直接读取原文。'}
            wire,mapping,visible,_=pack(full,options.get('compression','off'),True)
            if result is None and len(encode(wire).encode())<=ai_context.SMALL_CONTEXT_BYTES:return {'skip':True,'reading_mode':'original','reason':'短记录直接读取，不额外调用压缩模型。'}
            if result is None:
                eligible=[m for m in full if self.service.chat_memory.enabled(conn,m['conversation_id']) and m.get('parts',1)==1]
                caches,used=ai_context.candidates(conn,job['account_id'],eligible,min_savings=0)
                used={key for c in caches for key in c['hashes']}
                reverse={v:k for k,v in mapping.items()}
                reports=[]
                for c in caches:
                    value=json.loads(encode(c['result']))
                    value['origin_notice']=value.get('origin_notice','通用来源摘要' if c['feature']=='context' else '旧任务摘要，可能遗漏本次关注点，必要时回源。')
                    for field in ('items','people_memory','group_memory'):
                        for item in value.get(field,[]):item['evidence_ids']=[reverse[k] for k in item['evidence_ids'] if k in reverse]
                    reports.append(value)
                wire['messages']=[r for r in wire['messages'] if mapping[r[0]] not in used]
                return {'material':wire,'summaries':reports,'references':[r[0] for r in wire['messages']],'reused_messages':len(used)}
            if not isinstance(result,dict):raise CoreError('AI_OUTPUT_INVALID','压缩结果无效。')
            if not isinstance(references,list) or not references or any(not isinstance(r,str) or r not in mapping for r in references):raise CoreError('AI_EVIDENCE_INVALID','压缩来源必须来自本段实际提供的编号。')
            selected_keys={mapping[r] for r in references};full=[m for m in full if m['id'] in selected_keys]
            value=json.loads(encode(result))
            self._restore_people_labels(value,wire.get('people',{}),full)
            for field in ('items','people_memory','group_memory'):
                if not isinstance(value.get(field,[]),list):raise CoreError('AI_OUTPUT_INVALID','压缩记忆字段须为数组。')
                for item in value.get(field,[]):
                    if isinstance(item,dict) and isinstance(item.get('evidence_ids'),list):
                        item['evidence_ids']=[mapping.get(k,k) if isinstance(k,str) else k for k in item['evidence_ids']]
                        if isinstance(item.get('conversation_id'),str):item['conversation_id']=wire.get('groups',{}).get(item['conversation_id'],item['conversation_id'])
            # A partial long message cannot establish coverage of the whole original message.
            if any(m.get('parts',1)>1 for m in full):saved={'compressed_messages':0,'context':self._validate(value,full,[],'context'),'notice':'长消息分段摘录暂用于本轮，全部分段成功前不标记完整覆盖。'}
            else:saved=self.service.chat_memory.store_context(conn,job['account_id'],full,value,job_id)
            reverse={v:k for k,v in mapping.items()}
            saved['uncompressed_references']=[reverse[k] for k in saved.pop('uncompressed_message_ids',[]) if k in reverse]
            for field in ('items','people_memory','group_memory'):
                for item in saved['context'].get(field,[]):item['evidence_ids']=[reverse[k] for k in item['evidence_ids'] if k in reverse]
            return saved

    def _validate(self,payload,messages,previous,feature,target=''):
        if isinstance(payload,str):
            raw=payload.strip()
            if raw.startswith('```'):raw=re.sub(r'^```(?:json)?\s*|\s*```$','',raw,flags=re.I)
            try:payload=json.loads(raw)
            except (ValueError,TypeError):raise CoreError('AI_OUTPUT_INVALID','模型没有返回有效 JSON，可重试此分块。')
        if not isinstance(payload,dict) or not isinstance(payload.get('summary'),str) or not isinstance(payload.get('items'),list) or len(payload['items'])>30:
            raise CoreError('AI_OUTPUT_INVALID','模型结果结构不符合功能契约。')
        allowed={item['id']:item for item in messages};old={item['id']:item for item in previous};valid=[];notes=[]
        for value in payload['items']:
            if not isinstance(value,dict):raise CoreError('AI_OUTPUT_INVALID','模型条目格式无效。')
            evidence=value.get('evidence_ids')
            if not isinstance(evidence,list) or not evidence or any(not isinstance(key,str) or key not in allowed for key in evidence):
                if feature=='profile':notes.append('跳过一条画像：缺少当前有效来源；其余阶段画像保留。');continue
                raise CoreError('AI_EVIDENCE_INVALID','模型引用了未提供或跨群的证据，结果未收录。')
            for key in ('title','body'):
                if not isinstance(value.get(key),str) or not value[key].strip():raise CoreError('AI_OUTPUT_INVALID','模型缺少标题或正文。')
            if feature=='work' and all(re.fullmatch(r'.{0,30}?(?:收到|好的|明白)[！!。\s]*',allowed[key]['text']) for key in evidence):continue
            item={key:str(value.get(key) or '')[:limit] for key,limit in (('title',160),('body',20000),('category',100),('owner',160),('due_text',300),('uncertainty',1000),('subject',160))}
            if feature=='profile' and item['subject'] not in ('','group') and any(item['subject'] not in (allowed[k]['sender_qq'],allowed[k]['sender_key']) for k in evidence):
                notes.append('跳过一条画像：引用不是该成员的本人发言；其余阶段画像保留。');continue
            if feature=='profile' and item['subject'] not in ('','group'):
                own=next(m for m in reversed(messages) if item['subject'] in (m['sender_qq'],m['sender_key']))
                item['title']='阶段画像 · '+(own.get('sender_name') or item['subject']);item['stage']='partial'
                item['uncertainty']=item['uncertainty'] or '当前样本的暂定观察，尚不完善，可继续补充或纠正。'
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
            item['drafts']=[text[:20000] for text in drafts[:3]]
            update=value.get('update_id') or ''
            if update and update not in old:raise CoreError('AI_OUTPUT_INVALID','模型试图修改未提供的历史条目。')
            item['update_id']=update
            media_index=value.get('media_index',-1) if feature=='collection' else -1
            if not integer(media_index,-1,1000):raise CoreError('AI_OUTPUT_INVALID','图片索引无效。')
            if media_index>=0 and not any(media['index']==media_index and media['type']=='image' for media in allowed[evidence[0]]['media']):raise CoreError('AI_OUTPUT_INVALID','图片推荐没有有效来源。')
            item['media_index']=media_index
            valid.append(item)
        if feature=='profile':
            subjects={m['sender_qq'] or m['sender_key'] for m in messages}-{''}
            for subject in subjects-{v.get('subject') for v in valid}:
                own=[m for m in messages if subject in (m['sender_qq'],m['sender_key'])]
                valid.append({'title':'阶段画像 · '+(own[-1].get('sender_name') or subject),'subject':subject,'body':'当前已读取本人文本并保留来源。发言节选：'+own[0]['text'][:80]+'；语气、近期兴趣、性格倾向与习惯仍待补充。','category':'成员阶段画像','stage':'partial','statistics_only':True,'uncertainty':'本条由程序保存已有发言片段，未取得足够AI观察，不将未知内容补造成确定画像。','evidence_ids':list(dict.fromkeys(m['id'] for m in own))[:3],'drafts':[],'status':'proposed','priority':'normal','media_index':-1,'update_id':'','owner':'','due_text':'','due_at':None})
                notes.append('一名成员的AI观察尚待补充，已先保存本人发言节选和阶段条目。')
        people=[]
        if feature!='memory_validation':
            raw_people=payload.get('people_memory',[])
            if feature=='profile' and isinstance(raw_people,list):
                raw_people=[*raw_people,*[v for v in valid if v.get('subject') not in ('','group')]]
            if not isinstance(raw_people,list):notes.append('人物观察格式无效，已跳过；有效分析保留。');raw_people=[]
            if len(raw_people)>200:notes.append('本次人物观察超过200项，仅保留前200项；其他成员仍保留来源占位，可继续分批完善。')
            for value in raw_people[:200]:
                if not isinstance(value,dict):notes.append('跳过一条格式无效的人物观察，其他结果保留。');continue
                subject=value.get('subject','');evidence=value.get('evidence_ids',[])
                if isinstance(subject,str):subject=re.sub(r'^(?:QQ|UID)\s*[:：]\s*','',subject.strip(),flags=re.I)
                if not isinstance(subject,str) or not subject or not isinstance(evidence,list) or not evidence or any(not isinstance(key,str) or key not in allowed or subject not in (allowed[key]['sender_qq'],allowed[key]['sender_key']) for key in evidence):
                    notes.append('跳过一条人物观察：引用未对应此人的本人发言；不影响其他成员和本段分析。');continue
                try:checked=self._validate({'summary':'','items':[{**value,'subject':subject}]},messages,[],'memory_validation')['items'][0]
                except CoreError:notes.append('跳过一条缺少有效标题或正文的人物观察。');continue
                checked['subject']=next((allowed[key]['sender_qq'] or allowed[key]['sender_key'] for key in evidence),subject)
                people.append(checked)
        groups=[];raw_groups=payload.get('group_memory',[])
        if not isinstance(raw_groups,list):notes.append('群记忆格式无效，已跳过；有效分析保留。');raw_groups=[]
        if len(raw_groups)>50:notes.append('群记忆超过50项，保留前50项；其他来源以后继续完善。')
        for value in raw_groups[:50]:
            if not isinstance(value,dict) or not isinstance(value.get('body'),str) or not value['body'].strip():notes.append('跳过一条缺少正文的群记忆；有效分析保留。');continue
            group=value.get('conversation_id');evidence=value.get('evidence_ids',[])
            if not isinstance(group,str) or not isinstance(evidence,list) or not evidence or any(not isinstance(key,str) or key not in allowed or allowed[key]['conversation_id']!=group for key in evidence):
                notes.append('跳过一条群记忆：证据未对应此来源群；保留有效回答与其他记忆。');continue
            groups.append({'conversation_id':group,'body':value['body'][:2000],'evaluation':str(value.get('evaluation') or '')[:1000],'evidence_ids':list(dict.fromkeys(evidence))})
        return {'summary':payload['summary'][:20000],'items':valid,'people_memory':people,'group_memory':groups,'validation_notes':notes}

    def commit_chunk(self,job_id,attempt,result,usage=None):
        error=None
        with self.storage.connect() as conn:
            job=self._job(conn,job_id)
            row=conn.execute("SELECT * FROM ai_chunks WHERE job_id=? AND attempt=? AND status='running'",(job_id,attempt)).fetchone()
            if not row:raise CoreError('AI_STALE','此模型响应已经过期或已提交。')
            self._settle(conn,attempt,usage)
            try:
                messages=json.loads(row['messages_json']);options=json.loads(job['options_json'])
                compressed=options.get('compression','off')!='off'
                if compressed or options.get('evidence_format')=='aliases-v1' or row['stage']=='reduce':
                    if row['stage']=='reduce':aliases={f'm{i}':message['id'] for i,message in enumerate(messages)}
                    else:_,aliases,messages,_=evidence_pack(messages,options.get('compression','off'))
                    if isinstance(result,str):
                        raw=re.sub(r'^```(?:json)?\s*|\s*```$','',result.strip(),flags=re.I)
                        try:result=json.loads(raw)
                        except (ValueError,TypeError):raise CoreError('AI_OUTPUT_INVALID','模型没有返回有效JSON，可重试此分块。')
                    if isinstance(result,dict) and isinstance(result.get('items'),list):
                        result=json.loads(encode(result))
                        group_aliases=pack(messages,options.get('compression','off'),True)[0].get('groups',{}) if row['stage']!='reduce' else {}
                        people_aliases=pack(messages,options.get('compression','off'),True)[0].get('people',{}) if row['stage']!='reduce' else {}
                        self._restore_people_labels(result,people_aliases,messages)
                        people_values=result.get('people_memory',[]) if isinstance(result.get('people_memory',[]),list) else []
                        group_values=result.get('group_memory',[]) if isinstance(result.get('group_memory',[]),list) else []
                        for item in [*result['items'],*people_values,*group_values]:
                            if isinstance(item,dict) and isinstance(item.get('evidence_ids'),list):
                                if any(not isinstance(key,str) or key not in aliases for key in item['evidence_ids']) and item not in people_values and item not in group_values and job['feature']!='profile':raise CoreError('AI_EVIDENCE_INVALID','模型引用了未提供的证据编号，结果未收录。')
                                item['evidence_ids']=[aliases.get(key,key) if isinstance(key,str) else key for key in item['evidence_ids']]
                                if isinstance(item.get('conversation_id'),str):item['conversation_id']=group_aliases.get(item['conversation_id'],item['conversation_id'])
                                if isinstance(item.get('subject'),str) and item['subject'] in people_aliases:
                                    person=people_aliases[item['subject']];item['subject']=person['qq'] or person['uid']
                validated=self._validate(result,messages,json.loads(row['previous_json']),job['feature'],row['watch_target'])
                if job['feature']=='profile' and row['stage']=='map':
                    frozen=json.loads(job['coverage_json'])['hashes']
                    for m in messages:
                        current=conn.execute(f'SELECT {MESSAGE_COLUMNS} FROM messages WHERE id=? AND account_id=?',(m['id'],job['account_id'])).fetchone()
                        if not current or projection(current)['content_hash']!=frozen.get(m['id']):raise CoreError('AI_SOURCE_CHANGED','画像来源在分析期间改变，未保存此批。')
                if compressed:
                    for item in validated['items']:item['uncertainty']=(item['uncertainty'][:850]+' '+NOTICE).strip()
                if row['stage']=='reduce':
                    for item in validated['items']:item['uncertainty']=(item['uncertainty'][:750]+' '+hierarchy.NOTICE).strip()
            except CoreError as exc:error=exc
            if error:
                detail=conn.execute('SELECT details_json FROM ai_usage WHERE attempt=?',(attempt,)).fetchone()
                if detail:
                    metadata=json.loads(detail[0]);metadata['state']='invalid_output'
                    conn.execute('UPDATE ai_usage SET details_json=? WHERE attempt=?',(encode(metadata),attempt))
                conn.execute("UPDATE ai_chunks SET status='failed' WHERE job_id=? AND idx=?",(job_id,row['idx']))
                conn.execute("UPDATE ai_jobs SET status='failed',error=?,updated_at=? WHERE id=?",(str(error),now(),job_id))
            else:
                conn.execute("UPDATE ai_chunks SET status='completed',result_json=? WHERE job_id=? AND idx=?",(encode(validated),job_id,row['idx']))
                if job['feature']=='profile' and row['stage']=='map':self._remember_people(conn,job,[{**dict(row),'result_json':encode(validated)}],now())
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
                scope='' if job['feature']=='style' else 'conversation_id=? AND '
                current=conn.execute(f"SELECT {MESSAGE_COLUMNS} FROM messages WHERE {scope}account_id=? AND id IN ({','.join('?' for _ in batch)})",(*([] if job['feature']=='style' else [job['conversation_id']]),job['account_id'],*batch)).fetchall()
                if len(current)!=len(batch) or any(projection(row)['content_hash']!=frozen[row['id']] for row in current):
                    raise CoreError('AI_SOURCE_CHANGED','分析期间消息已变化，结果未合入历史。请重新分析最新消息。')
            rows=conn.execute('SELECT * FROM ai_chunks WHERE job_id=? ORDER BY idx',(job_id,)).fetchall()
            done=[row for row in rows if row['status']=='completed']
            hierarchical=json.loads(job['options_json']).get('hierarchical',False)
            displayed=hierarchy.frontier(rows) if hierarchical else done
            complete=len(done)==len(rows) and (not hierarchical or not rows or all(row['stage']=='reduce' for row in displayed) and len(displayed)==len({row['watch_target'] for row in rows}))
            if not complete and not partial:raise CoreError('AI_INCOMPLETE','尚有未完成读取或汇总，不能标记分析成功。')
            stamp=now();results=[json.loads(row['result_json']) for row in displayed];summaries=[value['summary'] for value in results]
            pending_ids={}
            for chunk,result in zip(displayed,results):
                if job['feature']=='style' and not complete:continue
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
            options=json.loads(job['options_json'])
            if options.get('compression','off')!='off':
                coverage['compression']=self._compression_stats([json.loads(chunk['messages_json']) for chunk in rows if chunk['stage']=='map'],options['compression'],options.get('wire_format')=='columns-v1')
                coverage['sent']=coverage['compression']['sent_messages'];coverage['folded']=coverage['compression']['folded']
            for person in coverage.get('watch_people',[]):
                planned=[chunk for chunk in rows if chunk['watch_target']==person['target']]
                person['completed_chunks']=sum(chunk['status']=='completed' for chunk in planned)
                person['chunks']=len(planned)
                person['status']='no_messages' if not planned else 'completed' if person['completed_chunks']==len(planned) else 'partial'
            unfinished={m['id'] for chunk in rows if chunk['stage']=='map' and chunk['status']!='completed' for m in json.loads(chunk['messages_json'])}
            coverage['completed_messages']=len({message['id'] for chunk in done if chunk['stage']=='map' for message in json.loads(chunk['messages_json'])}-unfinished)
            if job['feature']=='profile':
                coverage['profiled_people']=len({p['subject'] for chunk in done if chunk['stage']=='map' for p in json.loads(chunk['result_json']).get('people_memory',[])})
                coverage['profile_pending_people']=max(0,coverage.get('selected_people',0)-coverage['profiled_people'])
            coverage['validation_notes']=[note for chunk in done for note in json.loads(chunk['result_json']).get('validation_notes',[])][:100]
            failed=[chunk for chunk in rows if chunk['status']=='failed']
            coverage['failed_chunk_messages']=len({message['id'] for chunk in failed if chunk['stage']=='map' for message in json.loads(chunk['messages_json'])})
            coverage['failed_stage']='reduce' if any(chunk['stage']=='reduce' for chunk in failed) else 'map' if failed else ''
            if hierarchical:coverage['hierarchical'].update(map_chunks=sum(chunk['stage']=='map' for chunk in rows),merge_calls=sum(chunk['stage']=='reduce' for chunk in rows),levels=max((chunk['level'] for chunk in rows),default=0))
            public_coverage={k:v for k,v in coverage.items() if k not in ('hashes','previous','memory')}
            conn.execute('UPDATE ai_jobs SET coverage_json=? WHERE id=?',(encode(coverage),job_id))
            merged=[item for item in self._items(conn,job['conversation_id'],job['feature']) if item['id'] in set(pending_ids.values())]
            if job['feature']=='style':merged=[item for item in merged if item.get('subject')==options['person_id'] and item['id'] in set(pending_ids.values())]
            summary=('【分段汇总】'+hierarchy.NOTICE+'\n' if hierarchical else '')+('【有损压缩分析】'+NOTICE+'\n' if coverage.get('compression') else '')+'\n'.join(summaries)
            conn.execute('INSERT INTO ai_reports VALUES(?,?,?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET summary=excluded.summary,items_json=excluded.items_json,coverage_json=excluded.coverage_json',(job_id,job['conversation_id'],job['feature'],summary,encode(merged),encode(public_coverage),stamp))
            if complete:
                self._refresh_memories(conn,job,merged,displayed,stamp)
            if done:
                self._remember_people(conn,job,done,stamp)
                self._remember_groups(conn,job,done,stamp)
                if json.loads(job['settings_json']).get('remember',True):
                    unfinished={m['id'] for chunk in rows if chunk['stage']=='map' and chunk['status']!='completed' for m in json.loads(chunk['messages_json'])}
                    self.service.chat_memory.record(conn,[m for chunk in done if chunk['stage']=='map' for m in json.loads(chunk['messages_json']) if m['id'] not in unfinished],job_id,job['feature'])
                if json.loads(job['settings_json']).get('remember',True):
                    maps=[chunk for chunk in done if chunk['stage']=='map']
                    counts={}
                    for chunk in maps:
                        for key in {m['id'] for m in json.loads(chunk['messages_json'])}:counts[key]=counts.get(key,0)+1
                    for chunk in maps:
                        messages=json.loads(chunk['messages_json']);groups={m['conversation_id'] for m in messages}
                        if len(groups)!=1 or any(m.get('parts',1)>1 or counts[m['id']]!=1 for m in messages):continue
                        if not self.service.chat_memory.enabled(conn,next(iter(groups))):continue
                        messages=[{**m,'content_hash':frozen[m['id']]} for m in messages]
                        result={**json.loads(chunk['result_json']),'_watch_target':chunk['watch_target']}
                        ai_context.save(conn,job['account_id'],next(iter(groups)),job['feature'],options.get('reuse_key',''),messages,result,stamp,digest)
            if job['feature']=='identity' and complete and merged and self.get_group(job['conversation_id'],job['account_id']).get('role_source')!='manual':
                inferred=next((item['title'].strip() for item in merged if item.get('category')=='我的角色' and item.get('title','').strip()),'')[:1000]
                if inferred:
                    current=conn.execute('SELECT settings_json FROM ai_group_settings WHERE conversation_id=?',(job['conversation_id'],)).fetchone()
                    stored=json.loads(current[0] if current else job['settings_json'])
                    config={key:stored.get(key,value) for key,value in DEFAULT_GROUP.items()};config.update(role=inferred,role_source='inferred')
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
            original=json.loads(job['model_json'])
            if any(original.get(key)!=model.get(key) for key in ('id','provider','model','endpoint_hash','routes')):raise CoreError('MODEL_CHANGED','请选择原模型继续；或用新模型重新分析。')
            self._model_limits(model)
            conn.execute('UPDATE ai_jobs SET model_json=? WHERE id=?',(encode(model),job_id))
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
            job_where="conversation_id=? AND account_id=? AND status<>'deleted'";job_params=[conversation_id,account_id]
            if feature:job_where+=' AND feature=?';job_params.append(feature)
            job_total=conn.execute(f'SELECT count(*) FROM ai_jobs WHERE {job_where}',job_params).fetchone()[0]
            jobs=[]
            for row in conn.execute(f'SELECT id,feature,status,model_json,created_at,updated_at,error,coverage_json FROM ai_jobs WHERE {job_where} ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',(*job_params,job_page_size,(job_page-1)*job_page_size)):
                value=dict(row);value['model']=json.loads(value.pop('model_json'))['model'];value['coverage']={k:v for k,v in json.loads(value.pop('coverage_json')).items() if k not in ('hashes','previous','memory')}
                chunks=conn.execute('SELECT status,stage,messages_json,result_json FROM ai_chunks WHERE job_id=?',(value['id'],)).fetchall()
                if chunks:
                    value['coverage']['validation_notes']=[note for chunk in chunks for note in json.loads(chunk['result_json']).get('validation_notes',[])][:100]
                    value['coverage']['completed_messages']=len({message['id'] for chunk in chunks if chunk['status']=='completed' and chunk['stage']=='map' for message in json.loads(chunk['messages_json'])})
                    value['coverage']['failed_chunk_messages']=len({message['id'] for chunk in chunks if chunk['status']=='failed' and chunk['stage']=='map' for message in json.loads(chunk['messages_json'])})
                    value['coverage']['failed_stage']='reduce' if any(chunk['status']=='failed' and chunk['stage']=='reduce' for chunk in chunks) else 'map' if any(chunk['status']=='failed' for chunk in chunks) else ''
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
            if report:
                report_job=report['coverage'].get('reused_job_id') or row['job_id']
                stages=conn.execute('SELECT ch.idx,ch.stage,ch.level,ch.status,ch.result_json FROM ai_chunks ch JOIN ai_jobs j ON j.id=ch.job_id WHERE j.id=? AND j.conversation_id=? AND j.account_id=? ORDER BY ch.idx LIMIT 100',(report_job,conversation_id,account_id)).fetchall()
                report['stages']=[{'index':stage['idx'],'stage':stage['stage'],'level':stage['level'],'status':stage['status'],'summary':json.loads(stage['result_json']).get('summary','')[:2000]} for stage in stages]
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
                    item={**data,**user,'id':item_id};subject=item.get('subject') or 'group';kind='style' if row['feature']=='style' else 'person' if subject not in ('','group') else 'group';stamp=now()
                    material={key:item.get(key) for key in ('id','title','body','category','evidence_ids','uncertainty','user_status','correction','drafts','locked') if item.get(key) not in (None,'',[])}
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
