"""Every model attempt is budgeted and recorded, including media and capability tests."""
from datetime import datetime,timezone,timedelta
import json,math,uuid
from .errors import CoreError

def encode(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def valid_number(value):return type(value) in (int,float) and math.isfinite(value) and value>=0

def price_at(price,stamp):
    if not price:return None
    result=dict(price)
    if result.get('time_schedule')=='beijing_08_22':
        result['peak_rates']=result.get('peak_rates') or {key:result[key] for key in ('input_price','output_price','cached_input_price')}
        result.update(result['peak_rates'])
        local=stamp.astimezone(timezone(timedelta(hours=8)))
        off_peak=local.hour<8 or local.hour>=22
        if off_peak:result.update(result['off_peak'])
        result.update(time_band='闲时' if off_peak else '忙时',rated_at=local.isoformat())
    return result

def calculate(price,incoming,outgoing,cached=0,seconds=None):
    if not price:return None
    if price.get('unit')=='second':
        return seconds*price['second_price'] if valid_number(seconds) else None
    if type(incoming) is not int or type(outgoing) is not int:return None
    if incoming<0 or outgoing<0:return None
    cached=min(max(cached or 0,0),incoming)
    if cached and price.get('cached_input_price') is None:return None
    if not all(valid_number(price.get(k)) for k in ('input_price','output_price')):return None
    return ((incoming-cached)*price['input_price']+cached*price.get('cached_input_price',0)+outgoing*price['output_price'])/1000000

class UsageLedger:
    def __init__(self,ai):self.ai=ai;self.storage=ai.storage

    def reserve(self,conn,budget,model,job_id,idx,incoming,outgoing,kind='analysis',seconds=None):
        local=datetime.now(timezone(timedelta(hours=8)));day=local.strftime('%Y-%m-%d')
        price=price_at(model.get('pricing'),local);reserved=incoming+outgoing
        costs={};unknown_cost=False
        used_day=used_month=used_run=0
        for row in conn.execute('SELECT * FROM ai_usage WHERE month=? OR job_id=?',(day[:7],job_id)):
            if row['day']==day:used_day+=row['charged']
            if row['month']==day[:7]:
                used_month+=row['charged'];previous=json.loads(row['prices_json']);currency=previous.get('currency','CNY')
                if row['cost'] is None and row['charged']>0:unknown_cost=True
                elif row['cost'] is not None:costs[currency]=costs.get(currency,0)+row['cost']
            if row['job_id']==job_id:used_run+=row['charged']
        blocked=[]
        for used,key,label in ((used_run,'per_run_tokens','本次分析'),(used_day,'daily_tokens','今日'),(used_month,'monthly_tokens','本月')):
            if used+reserved>budget[key]:
                blocked.append({'field':key,'label':label,'used':used,'limit':budget[key],'remaining':max(0,budget[key]-used),'required':reserved})
        if blocked:
            details='；'.join(f"{value['label']}已用/预占 {value['used']:,}，上限 {value['limit']:,}，剩余 {value['remaining']:,}" for value in blocked)
            raise CoreError('BUDGET_EXCEEDED',f'Token预算不足：{details}；下一段需预占 {reserved:,}（输入预估 {incoming:,} + 最大输出 {outgoing:,}）。请到“设置 → AI预算”提高对应上限并保存；提高最大输出会增加预占。',{'blocked':blocked,'required':reserved,'input_estimate':incoming,'output_limit':outgoing})
        # Reserve the highest rate so a long request crossing a time boundary stays within budget.
        cost=calculate(model.get('pricing'),incoming,outgoing,seconds=seconds)
        if budget['monthly_cost']:
            if cost is None or price['currency']!=budget['currency']:raise CoreError('PRICE_REQUIRED','当前模型缺少匹配币种的官方定价，不能应用费用上限。')
            if unknown_cost:raise CoreError('PRICE_REQUIRED','本月存在费用未知的历史调用，不能保证月费用上限；可使用 Token 预算继续。')
            if costs.get(price['currency'],0)+cost>budget['monthly_cost']:raise CoreError('BUDGET_EXCEEDED','月度费用预算不足。')
        attempt=uuid.uuid4().hex
        metadata={'created_at':datetime.now(timezone.utc).isoformat(),'model':model.get('model',''),'provider':model.get('provider',''),'endpoint_hash':model.get('endpoint_hash',''),'kind':kind,'state':'reserved','cached_tokens':None,'seconds':None,'cost_state':'reserved' if cost is not None else 'unknown'}
        conn.execute('INSERT INTO ai_usage(attempt,job_id,chunk_idx,day,month,reserved,charged,cost,status,input_tokens,output_tokens,request_id,prices_json,details_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                     (attempt,job_id,idx,day,day[:7],reserved,reserved,cost,'reserved',None,None,'',encode(price or {}),encode(metadata)))
        return {'attempt':attempt,'reserved_tokens':reserved,'estimated_cost':cost,'pricing':price}

    def settle(self,conn,attempt,usage=None,known_not_sent=False,state='completed'):
        row=conn.execute('SELECT * FROM ai_usage WHERE attempt=?',(attempt,)).fetchone()
        if not row or row['status']!='reserved':return
        usage=usage or {};incoming=usage.get('input_tokens');outgoing=usage.get('output_tokens');cached=usage.get('cached_tokens',0)
        known=type(incoming) is int and type(outgoing) is int and 0<=incoming<=100000000 and 0<=outgoing<=100000000
        seconds=usage.get('seconds');seconds=seconds if valid_number(seconds) else None
        price=json.loads(row['prices_json']);metadata=json.loads(row['details_json'])
        if price.get('time_schedule') and usage.get('request_started_at'):
            try:
                price=price_at(price,datetime.fromisoformat(usage['request_started_at']))
            except (ValueError,TypeError):pass
        cost=calculate(price,incoming,outgoing,cached if type(cached) is int else 0,seconds)
        if known_not_sent:incoming=outgoing=0;known=True;cost=0;seconds=0
        # Duration APIs may legitimately omit tokens. Keep tokens NULL, never fabricate zero.
        measured=known or (price.get('unit')=='second' and seconds is not None)
        metadata.update(state=state,cached_tokens=cached if known else None,seconds=seconds,cost_state='official_estimate' if cost is not None else 'unknown')
        if known_not_sent:metadata['cost_state']='not_sent'
        if cost is None and not measured:cost=row['cost'];metadata['cost_state']='reserved' if cost is not None else 'unknown'
        conn.execute('UPDATE ai_usage SET status=?,charged=?,cost=?,input_tokens=?,output_tokens=?,request_id=?,details_json=?,prices_json=? WHERE attempt=?',
          ('settled' if measured or known_not_sent else 'unknown',incoming+outgoing if known else row['reserved'],cost,incoming if known else None,outgoing if known else None,str(usage.get('request_id',''))[:160],encode(metadata),encode(price),attempt))

    def reserve_call(self,model,kind,input_tokens=1000,output_tokens=512,seconds=None,job_id='',chunk_idx=-1):
        if not isinstance(model,dict) or kind not in ('vision','speech','test_vision','test_speech'):raise CoreError('INVALID_PARAMS','调用类型无效。')
        if any(type(n) is not int or not 0<=n<=1000000 for n in (input_tokens,output_tokens)):raise CoreError('INVALID_PARAMS','用量预估无效。')
        budget=self.ai.budget()
        with self.storage.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if job_id:self.ai._job(conn,job_id)
            return self.reserve(conn,budget,model,job_id or 'test:'+uuid.uuid4().hex,chunk_idx,input_tokens,output_tokens,kind,seconds)

    def settle_call(self,attempt,usage=None,known_not_sent=False,state='completed'):
        with self.storage.connect() as conn:self.settle(conn,attempt,usage,known_not_sent,state)
        return {'recorded':True}

    def reuse(self,model,job_id,state='cached'):
        stamp=datetime.now(timezone.utc).isoformat();local=datetime.now(timezone(timedelta(hours=8)));day=local.strftime('%Y-%m-%d')
        metadata={'created_at':stamp,'model':model.get('model',''),'kind':'cache','state':state,'cost_state':'not_sent','cached_tokens':0}
        with self.storage.connect() as conn:
            conn.execute('INSERT INTO ai_usage(attempt,job_id,chunk_idx,day,month,reserved,charged,cost,status,input_tokens,output_tokens,request_id,prices_json,details_json) VALUES(?,?,?,?,?,0,0,0,\'settled\',0,0,\'\',?,?)',
                         (uuid.uuid4().hex,job_id,-1,day,day[:7],encode(model.get('pricing') or {}),encode(metadata)))
        return {'recorded':True}

    def list(self,account_id='',conversation_id='',job_id='',offset=0,limit=50):
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=200:raise CoreError('INVALID_PARAMS','用量分页无效。')
        where=[];params=[]
        if conversation_id:self.ai.group(conversation_id,account_id)
        for field,value in (('j.account_id',account_id),('j.conversation_id',conversation_id),('u.job_id',job_id)):
            if value:where.append(field+'=?');params.append(value)
        clause=' WHERE '+' AND '.join(where) if where else ''
        with self.storage.connect() as conn:
            rows=conn.execute('SELECT u.*,j.feature,j.conversation_id FROM ai_usage u LEFT JOIN ai_jobs j ON j.id=u.job_id'+clause+' ORDER BY u.rowid DESC LIMIT ? OFFSET ?',(*params,limit+1,offset)).fetchall()
        items=[]
        for row in rows[:limit]:
            value=dict(row);value['pricing']=json.loads(value.pop('prices_json'));value.update(json.loads(value.pop('details_json')))
            if not value.get('model'):value['model']='旧版调用（未记录模型）'
            items.append(value)
        return {'items':items,'has_more':len(rows)>limit,'offset':offset}
