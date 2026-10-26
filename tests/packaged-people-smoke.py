"""Built-executable acceptance, synthetic fixtures and responses only."""
from pathlib import Path
import base64,json,subprocess,sys,tempfile
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/core'))
from local_assistant.service import AssistantService

with tempfile.TemporaryDirectory(prefix='packaged-people-') as temp:
    folder=Path(temp)/'app';app=AssistantService(folder)
    with app.storage.connect() as conn:
        for group,account,kind in [('a','synthetic','group'),('b','synthetic','group'),('other','other','group'),('private','synthetic','c2c')]:
            conn.execute("INSERT INTO conversations(id,kind,title,platform,account_id) VALUES(?,?,?,'qq',?)",(group,kind,'合成验收群',account))
            conn.execute("INSERT INTO messages(id,conversation_id,source_key,sent_at,direction,sender_key,sender_qq,sender_name,text,content_kind,parse_status,platform,account_id) VALUES(?,?,?,1790000000,'incoming','u_synthetic','100001','合成人','短句，先核对，再回复。','文本','partial','qq',?)",('m-'+group,group,'source-'+group,account))
    process=subprocess.Popen(['build/core/qq-insight-core.exe','--data-dir',str(folder)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
    serial=0
    def rpc(method,params=None,error=False):
        global serial
        serial+=1;process.stdin.write(json.dumps({'jsonrpc':'2.0','id':serial,'method':method,'params':params or {}})+'\n');process.stdin.flush()
        while True:
            line=process.stdout.readline()
            if not line:raise RuntimeError('BUILT_CORE_EOF')
            result=json.loads(line)
            if result.get('id')!=serial:continue
            if error:return result.get('error',{})
            assert 'error' not in result,result.get('error',{}).get('code')
            return result['result']
    scope={'conversation_id':'a','account_id':'synthetic'}
    model={'id':'synthetic','provider':'openai-compatible','model':'synthetic','endpoint_hash':'synthetic'}
    try:
        assert rpc('system.health')['version']==json.loads(Path('package.json').read_text(encoding='utf-8'))['version']
        assert len(rpc('ai.catalog')['items'])==8
        rpc('ai.budget.save',{'settings':{'per_run_tokens':500000,'daily_tokens':1000000}})
        job=rpc('ai.prepare',{**scope,'feature':'style','model':model,'options':{'person_id':'100001','cross_group':True,'limit':100}})
        assert job['coverage']['selected']==2 and job['coverage']['source_groups']==2
        while True:
            request=rpc('ai.next',{'job_id':job['job_id']})
            if request['done']:break
            data=json.loads(request['user']);first=data['messages'][0];key=first['id'] if isinstance(first,dict) else first[0]
            if request['stage']=='map':assert data['time_precision']=='minute' and len(first[2])==5
            output={'summary':'合成人物习惯用短句核对。','items':[{'title':'短句与核对倾向','body':'仅基于合成证据。','subject':'100001','evidence_ids':[key],'drafts':['你在做风格模拟，先核对，再简洁回答；不自称本人。']}]}
            if request['stage']=='map':output['people_memory']=[{'title':'表达习惯','body':'短句核对','subject':'100001','evidence_ids':[key]}]
            rpc('ai.commit',{'job_id':job['job_id'],'attempt':request['attempt'],'result':output,'usage':{'input_tokens':20,'output_tokens':10}})
        completed=rpc('ai.finish',{'job_id':job['job_id']});assert completed['coverage']['completed_messages']==2
        history=rpc('ai.history',{**scope,'feature':'style','job_id':job['job_id']});assert history['report']['items'][0]['drafts']
        memory=rpc('ai.memory.list',scope);record=next(item for item in memory['items'] if item['kind']=='person')
        rpc('ai.memory.update',{**scope,'memory_key':record['memory_key'],'action':'correct','correction':'合成用户更正'})
        assert any(item.get('locked') for item in rpc('ai.memory.list',scope)['items'])
        failed=rpc('ai.prepare',{**scope,'feature':'summary','model':model});request=rpc('ai.next',{'job_id':failed['job_id']})
        assert rpc('ai.commit',{'job_id':failed['job_id'],'attempt':request['attempt'],'result':{'summary':'错误证据','items':[{'title':'错误','body':'错误','evidence_ids':['outside']}]},'usage':{'input_tokens':70,'output_tokens':30}},error=True)['code']=='AI_EVIDENCE_INVALID'
        before=rpc('ai.budget.get')['daily_used'];bad=rpc('ai.history',{**scope,'feature':'summary'})['jobs'][0]
        assert bad['coverage']['completed_messages']==0 and bad['coverage']['failed_chunk_messages']==1
        rpc('ai.history.delete',{**scope,'job_id':failed['job_id']})
        assert rpc('ai.history',{**scope,'feature':'summary'})['jobs']==[]
        assert rpc('ai.budget.get')['daily_used']==before
        run=rpc('workspace.begin',{'account_id':'synthetic','question':'全局合成群聊和私聊工作区验收'})
        task={'run_id':run['run_id'],'account_id':'synthetic'}
        raw=rpc('workspace.tool',{**task,'name':'read_context','arguments':{'conversation_ids':['a','b','private'],'prefer_cache':False}})
        assert raw['selected_messages']==3 and raw['time_precision']=='minute'
        ref=raw['messages'][0][0]
        md=rpc('workspace.tool',{**task,'name':'write_markdown','arguments':{'title':'全局报告','content':'# 合成工作报告','evidence_ids':[ref]}})
        excel=rpc('workspace.tool',{**task,'name':'export_order','arguments':{'conversation_ids':['a'],'title':'合成发言顺序'}})
        rpc('workspace.finish',{**task,'result':{'answer':'已完成合成全局任务。','evidence_ids':[ref]}})
        assert rpc('workspace.history',{'account_id':'synthetic'})['items'][0]['status']=='completed'
        follow=rpc('workspace.begin',{'account_id':'synthetic','session_id':run['session_id'],'question':'把它改得更简洁'})
        assert len(follow['previous_turns'])==1 and follow['previous_turns'][0]['answer']=='已完成合成全局任务。'
        rpc('workspace.finish',{'run_id':follow['run_id'],'account_id':'synthetic','result':{'answer':'已简化合成报告。','evidence_ids':[]}})
        edited=rpc('workspace.begin',{'account_id':'synthetic','session_id':run['session_id'],'edit_run_id':run['run_id'],'question':'修改首问'})
        assert edited['previous_turns']==[]
        rpc('workspace.finish',{'run_id':edited['run_id'],'account_id':'synthetic','result':{'answer':'新的合成分支。','evidence_ids':[]}})
        dialog=rpc('workspace.chat.get',{'session_id':run['session_id'],'account_id':'synthetic'})
        assert len(dialog['branches'])==2 and dialog['items'][0]['question']=='修改首问'
        md_path=Path(rpc('workspace.artifact',{'account_id':'synthetic','artifact_id':md['artifact_id']})['path']);assert '合成工作报告' in md_path.read_text(encoding='utf-8')
        xlsx_path=Path(rpc('workspace.artifact',{'account_id':'synthetic','artifact_id':excel['artifact_id']})['path'])
        with zipfile.ZipFile(xlsx_path) as archive:assert 'xl/worksheets/sheet1.xml' in archive.namelist()
        rpc('self.save',{'account_id':'synthetic','settings':{'name':'合成自己','qq':'100001','identity':'合成学生'}})
        rpc('chat.settings.save',{**scope,'settings':{'prompt':'先列结论，再给依据。','self_identity':'本会话记录员'}})
        local=rpc('workspace.begin',{**scope,'question':'分析本群画像并完善Agent'})
        own={'run_id':local['run_id'],'account_id':'synthetic'}
        assert local['conversation_id']=='a' and local['allowed_kinds']==['group']
        assert rpc('workspace.tool',{**own,'name':'read_context','arguments':{'conversation_ids':['b']}},error=True)['code']=='SCOPE_NOT_ALLOWED'
        source=rpc('workspace.tool',{**own,'name':'read_context','arguments':{'conversation_ids':['a']}});reference=source['messages'][0][0]
        rpc('workspace.finish',{**own,'result':{'answer':'合成会话偏简短核对。','evidence_ids':[reference],'group_memory':[{'conversation_id':'a','body':'本会话讨论核对事项。','evidence_ids':[reference]}],'people_memory':[{'subject':'100001','title':'合成本人观察','body':'表达较简洁。','evidence_ids':[reference]}]}})
        assert rpc('chat.memory.coverage',scope)['compressed']==1
        config=rpc('chat.settings.get',scope);assert '本会话讨论核对事项' in config['learned']['prompt'] and config['settings']['prompt']=='先列结论，再给依据。'
        assert any(p['is_self'] for p in rpc('chat.memory.list',{**scope,'kind':'people'})['items'])
        private=rpc('workspace.chat.create',{'account_id':'synthetic','conversation_id':'private'})
        attachment=rpc('workspace.attachment.add',{'account_id':'synthetic','session_id':private['id'],'filename':'合成附件.md','mime':'text/markdown','data_base64':base64.b64encode('合成附件与私聊分开。'.encode()).decode()})
        talk=rpc('workspace.begin',{'account_id':'synthetic','session_id':private['id'],'question':'看看我刚提交的附件','attachment_ids':[attachment['id']]})
        assert talk['allowed_kinds']==['c2c'] and talk['conversation_id']=='private'
        assert rpc('workspace.attachment.data',{'run_id':talk['run_id'],'account_id':'synthetic','attachment_id':attachment['id']})['filename']=='合成附件.md'
        rpc('workspace.finish',{'run_id':talk['run_id'],'account_id':'synthetic','result':{'answer':'可以直接交流并读取本私聊。','evidence_ids':[]}})
        assert len(rpc('workspace.chat.list',{'account_id':'synthetic','conversation_id':'private'})['items'])==1
        context_run=rpc('workspace.begin',{'account_id':'synthetic','conversation_id':'private','question':'整理本私聊上下文'})
        prepared_scope={'run_id':context_run['run_id'],'account_id':'synthetic'}
        original=rpc('workspace.tool',{**prepared_scope,'name':'read_context','arguments':{'conversation_ids':['private'],'prefer_cache':False}})
        refs=original['uncompressed_references']
        saved=rpc('workspace.context.commit',{**prepared_scope,'references':refs,'result':{'summary':'合成可复用私聊上下文。','items':[{'title':'核对表达','body':'私聊使用简短核对表达。','evidence_ids':refs}],
            'people_memory':[{'subject':'999999','title':'无效归因','body':'应跳过而非整块失败。','evidence_ids':refs}]}})
        assert saved['compressed_messages']==1 and len(saved['validation_notes'])==1
        rpc('workspace.finish',{**prepared_scope,'error':'合成最终任务失败，保留压缩'})
        reused=rpc('workspace.begin',{'account_id':'synthetic','conversation_id':'private','question':'改成双方画像总结'})
        read=rpc('workspace.tool',{'run_id':reused['run_id'],'account_id':'synthetic','name':'read_context','arguments':{'conversation_ids':['private']}})
        assert read['reused_messages']==0 and read['raw_messages']==1 and len(read['messages'])==1 and read['short_context']
        assert any(s['name']=='compress_context' for s in next(r for r in rpc('workspace.history',{'account_id':'synthetic'})['items'] if r['id']==context_run['run_id'])['steps'])
        literal=rpc('workspace.begin',{'account_id':'synthetic','conversation_id':'private','question':'提取本私聊原话做成md文件'})
        literal_scope={'run_id':literal['run_id'],'account_id':'synthetic'}
        originals=rpc('workspace.tool',{**literal_scope,'name':'search_messages','arguments':{'kind':'c2c'}})
        assert originals['short_context'] and originals['selected_messages']==1 and originals['reading_mode']=='original'
        reference=originals['messages'][0][0]
        assert rpc('workspace.tool',{**literal_scope,'name':'write_markdown','arguments':{'title':'不能手抄','content':'摘要','evidence_ids':[reference]}},error=True)['code']=='AGENT_TOOL_INVALID'
        exact=rpc('workspace.tool',{**literal_scope,'name':'export_messages','arguments':{'title':'合成原话','sections':[{'heading':'本私聊','references':[reference]}]}})
        actual=Path(rpc('workspace.artifact',{'account_id':'synthetic','artifact_id':exact['artifact_id']})['path']).read_text(encoding='utf-8')
        assert '短句，先核对，再回复。' in actual and exact['verbatim']
        assert rpc('workspace.finish',{**literal_scope,'result':{'answer':'原文文件已生成。','evidence_ids':[reference]}})['status']=='completed'
        print('Packaged people passed: explicit cross-group scope, minute wire, hierarchy Prompt, person memory controls, failure count and retained billing; synthetic only.')
        print('Packaged global agent passed: group+private retrieval, Markdown, real XLSX, account-scoped history and artifact materialization; no model request.')
        print('Packaged conversation chat passed: fixed group/private sessions, three memory stores, self identity, source-backed learned Agent and bound attachments; no model request.')
        print('Packaged context pipeline passed: private commit, person observation skip, failure preserves coverage and short persona question reads original without compression; synthetic only.')
        print('Packaged autonomy passed: scoped bulk search, short direct original, rejected handwritten quotation and source-verified Markdown export; synthetic only.')
    finally:
        process.stdin.close();process.wait(timeout=10)
