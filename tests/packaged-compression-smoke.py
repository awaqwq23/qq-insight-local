"""Exercise all seven compression paths in the built executable, without network."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

with tempfile.TemporaryDirectory(prefix='packaged-compression-') as directory:
    folder=Path(directory)
    subprocess.run([sys.executable,'tests/ai-fixture.py',str(folder/'app')],check=True,capture_output=True)
    process=subprocess.Popen(['build/core/qq-insight-core.exe','--data-dir',str(folder/'app')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
    sequence=0
    def rpc(method,params):
        global sequence
        sequence+=1
        process.stdin.write(json.dumps({'jsonrpc':'2.0','id':sequence,'method':method,'params':params},ensure_ascii=False)+'\n');process.stdin.flush()
        while True:
            line=process.stdout.readline()
            if not line:raise RuntimeError('PACKAGED_CORE_EOF')
            value=json.loads(line)
            if value.get('id')!=sequence:continue
            if 'error' in value:raise RuntimeError('PACKAGED_RPC_FAILED: '+str(value['error'].get('code')))
            return value['result']
    try:
        catalog=rpc('ai.catalog',{})
        model={'id':'synthetic','provider':'openai-compatible','model':'synthetic-model','endpoint_hash':'synthetic'}
        for feature in (item for item in catalog['items'] if item['id']!='style'):
            job=rpc('ai.prepare',{'conversation_id':'synthetic-group','account_id':'synthetic','feature':feature['id'],'model':model,'options':{'compression':'strong','output_chars':1234}})
            request=rpc('ai.next',{'job_id':job['job_id']})
            material=json.loads(request['user'])
            assert material['compression']['mode']=='strong'
            assert material['request']['output_chars']==1234 and '1234' in request['system']
            assert material['messages'][0][0]=='m0'
            assert material['message_columns']==['id','day','clock','sender','text','extra']
            output={'summary':'合成压缩摘要','items':[{'title':'合成事项','body':'合成结果仅用于测试','evidence_ids':['m0']}]}
            rpc('ai.commit',{'job_id':job['job_id'],'attempt':request['attempt'],'result':output,'usage':{'input_tokens':20,'output_tokens':10}})
            assert rpc('ai.next',{'job_id':job['job_id']})['done']
            rpc('ai.finish',{'job_id':job['job_id']})
            history=rpc('ai.history',{'conversation_id':'synthetic-group','account_id':'synthetic','feature':feature['id'],'job_id':job['job_id']})
            assert history['report']['items'][0]['evidence_ids'][0].startswith('synthetic-')
            assert '有损' in history['report']['summary']
        job=rpc('ai.prepare',{'conversation_id':'synthetic-group','account_id':'synthetic','feature':'summary','model':model,'options':{'compression':'strong','hierarchical':True,'output_chars':1234}})
        stages=[]
        while True:
            request=rpc('ai.next',{'job_id':job['job_id']})
            if request['done']:break
            stages.append(request['stage'])
            material=json.loads(request['user'])
            if request['stage']=='reduce':
                assert material['request']['output_chars']==1234
                assert 'partial_reports' in material and 'text' not in material['messages'][0]
            output={'summary':'合成分层摘要','items':[{'title':'合成事项','body':'合成结果仅用于测试','evidence_ids':['m0']}]}
            rpc('ai.commit',{'job_id':job['job_id'],'attempt':request['attempt'],'result':output,'usage':{'input_tokens':20,'output_tokens':10}})
        assert stages==['map','reduce']
        rpc('ai.finish',{'job_id':job['job_id']})
        history=rpc('ai.history',{'conversation_id':'synthetic-group','account_id':'synthetic','feature':'summary','job_id':job['job_id']})
        assert history['report']['coverage']['completed_messages']==8
        assert history['report']['coverage']['hierarchical']['merge_calls']==1
        assert len(history['report']['stages'])==2 and '分段汇总' in history['report']['summary']
        price={'basis':'official','unit':'token','currency':'CNY','input_price':9,'output_price':27,'cached_input_price':0.3,'time_schedule':'deepseek_beijing','off_peak':{'input_price':4.5,'output_price':13.5,'cached_input_price':0.15}}
        entry=rpc('ai.call.reserve',{'model':{**model,'pricing':price},'kind':'test_capacity','input_tokens':1000,'output_tokens':1000})
        rpc('ai.call.settle',{'attempt':entry['attempt'],'usage':{'input_tokens':1000,'output_tokens':100,'cached_tokens':500,'request_started_at':'2026-10-13T18:00:00+08:00'}})
        ledger=rpc('ai.usage.list',{})
        row=next(value for value in ledger['items'] if value['attempt']==entry['attempt'])
        assert abs(row['cost']-0.003675)<1e-10 and row['pricing']['time_band']=='闲时'
        entry=rpc('ai.call.reserve',{'model':model,'kind':'test_capacity','input_tokens':100,'output_tokens':100})
        rpc('ai.call.settle',{'attempt':entry['attempt'],'usage':{'input_tokens':100,'output_tokens':50}})
        assert rpc('ai.pricing.apply',{'catalog':{'synthetic-model':price}})['updated']>=1
        row=next(value for value in rpc('ai.usage.list',{})['items'] if value['attempt']==entry['attempt'])
        assert row['cost'] is not None and row['input_tokens']==100 and row['pricing']['reestimated_at']
    finally:
        process.stdin.close()
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
print('Packaged compression passed: seven functions, hierarchy, official pricing and history re-estimates; no model request.')
