import base64,hashlib,json,unittest,zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
import test_ai as fixtures
from local_assistant.errors import CoreError
from local_assistant.workspace_agent import names_xlsx


class WorkspaceAgentTest(unittest.TestCase):
    setUp=fixtures.AITest.setUp
    add_message=fixtures.AITest.add_message
    prepare=fixtures.AITest.prepare
    output=fixtures.AITest.output
    complete=fixtures.AITest.complete

    def begin(self):return self.app.workspace_agent.begin('a','整理本地合成群聊及私聊')['run_id']
    def tool(self,run,name,**arguments):return self.app.workspace_agent.tool(run,'a',name,arguments)

    def test_question_scope_blocks_private_and_prior_private_answers(self):
        private=self.app.workspace_agent.begin('a','分析群聊和我私聊')['run_id']
        self.app.workspace_agent.finish(private,'a',{'answer':'私聊独有结果','evidence_ids':[]})
        group=self.app.workspace_agent.begin('a','统计某人在群聊里的发言')
        self.assertEqual(group['allowed_kinds'],['group']);self.assertEqual(group['previous_turns'],[])
        self.assertTrue(all(c['kind']=='group' for c in self.tool(group['run_id'],'conversations')['items']))
        for name in ('read_context','statistics','export_order','images'):
            with self.assertRaises(CoreError) as error:self.tool(group['run_id'],name,conversation_ids=['private'])
            self.assertEqual(error.exception.code,'SCOPE_NOT_ALLOWED')
        only_private=self.app.workspace_agent.begin('a','只看我和他私聊')
        self.assertEqual(only_private['allowed_kinds'],['c2c'])
        with self.assertRaises(CoreError):self.tool(only_private['run_id'],'read_context',conversation_ids=['group-a'])
        explicit=self.app.workspace_agent.begin('a','比较群聊和私聊，但不要读取私聊')
        self.assertEqual(explicit['allowed_kinds'],['group'])

    def test_followup_scope_is_bound_to_explicit_session(self):
        first=self.app.workspace_agent.begin('a','分析群聊和我私聊')
        self.app.workspace_agent.finish(first['run_id'],'a',{'answer':'不同场景表达不同','evidence_ids':[]})
        follow=self.app.workspace_agent.begin('a','把这个做成md',session_id=first['session_id'])
        self.assertEqual(follow['allowed_kinds'],['group','c2c'])
        self.assertEqual(len(follow['previous_turns']),1)
        self.assertEqual(self.app.workspace_agent.begin('a','统计另一个人的发言')['allowed_kinds'],['group'])
        self.assertEqual(self.app.workspace_agent.begin('a','统计某人在所有群的发言')['previous_turns'],[])

    def test_mixed_scene_person_inference_does_not_leak_into_group_memory(self):
        with self.app.storage.connect() as conn:self.add_message(conn,'private-secret','private','私聊表达',400)
        run=self.begin();raw=self.tool(run,'read_context',conversation_ids=['group-a','private'],sender='100001',prefer_cache=False)
        refs=[m[0] for m in raw['messages']]
        self.app.workspace_agent.finish(run,'a',{'answer':'多场景综合分析','evidence_ids':refs,'people_memory':[{'subject':'100001','title':'综合表达','body':'私聊独有的推断不应注入群记忆','uncertainty':'合成样本','evidence_ids':refs}]})
        memory=self.ai.memories('group-a','a')['items']
        self.assertNotIn('私聊独有的推断',json.dumps(memory,ensure_ascii=False))

    def test_group_memory_every_task_and_user_correction(self):
        job=self.prepare();request=self.ai.next_chunk(job['job_id']);out=self.output(request)
        out['group_memory']=[{'conversation_id':'g0','body':'本群正在讨论任务提交。','evaluation':'沟通围绕课程安排，样本有限。','evidence_ids':['m0']}]
        self.ai.commit_chunk(job['job_id'],request['attempt'],out,{'input_tokens':20,'output_tokens':10});self.complete(job)
        record=next(m for m in self.ai.memories('group-a','a')['items'] if m['memory_key']=='group:work')
        self.assertIn('课程安排',record['body'])
        self.ai.update_memory('group-a','a','group:work','correct','人工更正：这是项目任务群。')
        with self.app.storage.connect() as conn:self.add_message(conn,'new','group-a','补充一个任务',300)
        self.complete(self.prepare(limit=100))
        self.assertEqual(next(m for m in self.ai.memories('group-a','a')['items'] if m['memory_key']=='group:work')['body'],'人工更正：这是项目任务群。')

    def test_reuse_old_chunks_reads_only_delta_and_rejects_changed_or_new_goal(self):
        with self.app.storage.connect() as conn:conn.execute("UPDATE messages SET text=? WHERE conversation_id='group-a'",('合成材料。'*600,))
        self.complete(self.prepare())
        with self.app.storage.connect() as conn:self.add_message(conn,'new','group-a','新任务：请核对周五安排',300)
        job=self.prepare(limit=100)
        self.assertEqual(job['coverage']['reused_messages'],2);self.assertEqual(job['coverage']['raw_messages'],1)
        request=self.ai.next_chunk(job['job_id']);self.assertEqual(request['stage'],'map')
        self.assertEqual(request['evidence_aliases'],{'new':'m0'})
        self.ai.commit_chunk(job['job_id'],request['attempt'],self.output(request),{'input_tokens':20,'output_tokens':10});self.complete(job)
        self.assertEqual(self.ai.history('group-a','a',job_id=job['job_id'])['report']['coverage']['completed_messages'],3)
        different=self.prepare(limit=100,goal='换一个任务目标');self.assertEqual(different['coverage']['reused_messages'],0)
        self.ai.fail(different['job_id'],known_not_sent=True)
        with self.app.storage.connect() as conn:conn.execute("UPDATE messages SET text='原记录已更正' WHERE id='m0'")
        changed=self.prepare(limit=100);self.assertLess(changed['coverage']['reused_messages'],3)

    def test_global_private_and_group_scope_exact_person_and_cache_bypass(self):
        self.ai.save_budget({'per_run_tokens':1000000})
        with self.app.storage.connect() as conn:conn.execute("UPDATE messages SET text=text||? WHERE conversation_id='group-a'",('合成上下文材料。'*600,))
        self.complete(self.prepare('summary'))
        with self.app.storage.connect() as conn:self.add_message(conn,'private-message','private','私聊说话风格',400)
        run=self.begin()
        cached=self.tool(run,'read_context',conversation_ids=['group-a'],limit=100)
        self.assertEqual(cached['reused_messages'],2);self.assertEqual(cached['messages'],[])
        raw=self.tool(run,'read_context',conversation_ids=['group-a','group-b','private'],sender='100001',prefer_cache=False,limit=100)
        self.assertEqual(raw['raw_messages'],4);self.assertIn('私聊说话风格',json.dumps(raw,ensure_ascii=False));self.assertNotIn('账号B内容',json.dumps(raw,ensure_ascii=False))
        with self.assertRaises(CoreError):self.tool(run,'read_context',conversation_ids=['group-c'])
        with self.assertRaises(CoreError):self.tool(run,'execute_sql',sql='DELETE FROM messages')
        result=self.app.workspace_agent.finish(run,'a',{'answer':'群聊和私聊表达须按场景区分。','evidence_ids':[raw['messages'][0][0]]})
        self.assertEqual(result['status'],'completed')
        self.assertTrue(any(m['kind']=='group' for m in self.ai.memories('group-b','a')['items']))

    def test_group_memory_rejects_cross_group_evidence(self):
        job=self.prepare();request=self.ai.next_chunk(job['job_id']);out=self.output(request)
        out['group_memory']=[{'conversation_id':'group-b','body':'不应接受','evaluation':'','evidence_ids':['m0']}]
        self.ai.commit_chunk(job['job_id'],request['attempt'],out,{'input_tokens':10,'output_tokens':10})
        self.ai.finish(job['job_id'])
        self.assertEqual(self.ai.memories('group-b','a')['items'],[])
        self.assertTrue(self.ai.history('group-a','a',job_id=job['job_id'])['report']['coverage']['validation_notes'])

    def test_3000_message_context_reuse_reduces_model_material(self):
        with self.app.storage.connect() as conn:
            for i in range(3000):self.add_message(conn,f'context-volume-{i}','group-a',f'合成事项{i}：核对任务、来源和安排。'+'背景资料需要在讨论中核对。'*15,200+i)
        self.ai.save_budget({'per_run_tokens':5000000,'daily_tokens':10000000})
        original=self.prepare('summary',limit=3000);before_bytes=0;before_calls=0
        while True:
            request=self.ai.next_chunk(original['job_id'])
            if request['done']:break
            before_calls+=1;before_bytes+=len((request['system']+request['user']).encode())
            self.ai.commit_chunk(original['job_id'],request['attempt'],self.output(request),{'input_tokens':20,'output_tokens':10})
        self.ai.finish(original['job_id'])
        with self.app.storage.connect() as conn:self.add_message(conn,'context-new','group-a','新消息：提交时间更正为下周一。',4000)
        updated=self.prepare('summary',limit=3001);coverage=updated['coverage']
        self.assertGreater(coverage['reused_messages'],2800);self.assertLess(coverage['raw_messages'],201)
        after_bytes=0;after_calls=0
        while True:
            request=self.ai.next_chunk(updated['job_id'])
            if request['done']:break
            after_calls+=1;after_bytes+=len((request['system']+request['user']).encode())
            self.ai.commit_chunk(updated['job_id'],request['attempt'],self.output(request),{'input_tokens':20,'output_tokens':10})
        self.ai.finish(updated['job_id']);self.assertLess(after_bytes,before_bytes*.4)
        print(f'Context synthetic 3000+1: reused={coverage["reused_messages"]}, raw={coverage["raw_messages"]}; request material {before_bytes}->{after_bytes} bytes, calls {before_calls}->{after_calls}; not billed tokens.')

    def test_excel_order_is_original_data_with_only_names_and_safe_strings(self):
        with self.app.storage.connect() as conn:
            conn.execute("UPDATE messages SET sender_name='=SUM(1,2)' WHERE id='m0'")
            conn.execute("UPDATE messages SET sender_name='乙&丙' WHERE id='m1'")
        run=self.begin();file=self.tool(run,'export_order',conversation_ids=['group-a'],start=100,end=102,title='../发言顺序')
        path=Path(self.app.workspace_agent.materialize('a',file['artifact_id'])['path'])
        self.assertTrue(path.is_relative_to(self.app.data_dir));self.assertEqual(file['rows'],2)
        with zipfile.ZipFile(path) as archive:
            sheet=ElementTree.fromstring(archive.read('xl/worksheets/sheet1.xml'));ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            self.assertEqual([t.text for t in sheet.findall('.//s:t',ns)],['人名','=SUM(1,2)','乙&丙']);self.assertEqual(sheet.findall('.//s:f',ns),[])
        stats=self.tool(run,'statistics',conversation_ids=['group-a'],start=100,end=102)
        self.assertEqual(stats['totals']['messages'],2)
        self.app.workspace_agent.finish(run,'a',{'answer':'已按原记录导出2行人名。','evidence_ids':[]})
        self.assertTrue(any(m['memory_key']=='group:workspace-tools' for m in self.ai.memories('group-a','a')['items']))
        with self.assertRaises(CoreError):self.app.workspace_agent.materialize('b',file['artifact_id'])

    def test_markdown_provenance_history_and_restart(self):
        run=self.begin();raw=self.tool(run,'read_context',conversation_ids=['group-a'],prefer_cache=False)
        ref=raw['messages'][0][0]
        with self.assertRaises(CoreError):self.tool(run,'write_markdown',title='错误',content='无来源',evidence_ids=['r999'])
        file=self.tool(run,'write_markdown',title='工作清单',content='# 工作\n\n- 核对提交安排',evidence_ids=[ref])
        self.app.workspace_agent.finish(run,'a',{'answer':'已生成工作清单。','evidence_ids':[ref],
            'group_memory':[{'conversation_id':'group-a','body':'关注提交安排。','evaluation':'本段为任务讨论。','evidence_ids':[ref]}]})
        restarted=fixtures.AssistantService(self.root/'app')
        history=restarted.workspace_agent.history('a')['items'];self.assertEqual(history[0]['artifacts'][0]['artifact_id'],file['artifact_id'])
        self.assertEqual(restarted.workspace_agent.history('b')['items'],[])
        self.assertTrue(Path(restarted.workspace_agent.materialize('a',file['artifact_id'])['path']).exists())

    def test_source_changed_blocks_final_memory_and_uncertain_images_are_not_saved(self):
        run=self.begin();raw=self.tool(run,'read_context',conversation_ids=['group-a'],prefer_cache=False);ref=raw['messages'][0][0]
        with self.assertRaises(CoreError):self.tool(run,'save_image',reference=ref,media_index=0,title='未识图')
        with self.app.storage.connect() as conn:conn.execute("UPDATE messages SET text='已改动' WHERE id='m0'")
        with self.assertRaises(CoreError):self.app.workspace_agent.finish(run,'a',{'answer':'旧结果','evidence_ids':[ref]})

    def test_real_pixel_gate_and_image_file_and_favorite(self):
        data=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a52kAAAAASUVORK5CYII=');asset=hashlib.sha256(data).hexdigest()
        with self.app.storage.connect() as conn:
            conn.execute('INSERT INTO media_assets VALUES(?,?,?)',(asset,'image/png',data));conn.execute('INSERT INTO message_media VALUES(?,?,?)',('m0',0,asset));conn.execute('UPDATE messages SET media_json=? WHERE id=?',(json.dumps([{'type':'image','filename':'synthetic.png'}]),'m0'))
        run=self.begin();candidates=self.tool(run,'images',conversation_ids=['group-a']);ref=candidates['items'][0]['reference']
        raw=self.tool(run,'read_context',conversation_ids=['group-a'],prefer_cache=False)
        self.assertEqual(raw['messages'][0][5]['images'],[0]);self.assertNotIn('data:image',json.dumps(raw))
        self.assertTrue(self.app.workspace_agent.image_data(run,'a',ref,0)['available'])
        self.app.workspace_agent.image_observed(run,'a',ref,0,'合成像素描述，不是真实模型识图。')
        file=self.tool(run,'save_image',reference=ref,media_index=0,title='合成图片')
        self.assertEqual(Path(self.app.workspace_agent.materialize('a',file['artifact_id'])['path']).read_bytes(),data)
        self.assertEqual(len(self.app.list_favorites('a')['items']),1)

    def test_global_usage_account_filter_and_budget(self):
        run=self.begin();self.ai.save_budget({'daily_tokens':1000})
        with self.assertRaises(CoreError):self.ai.ledger.reserve_call(fixtures.MODEL,'agent',1000,512,job_id=run)
        self.ai.save_budget({'daily_tokens':100000})
        attempt=self.ai.ledger.reserve_call(fixtures.MODEL,'agent',1000,512,job_id=run)
        self.ai.ledger.settle_call(attempt['attempt'],{'input_tokens':40,'output_tokens':30})
        self.assertEqual(self.ai.ledger.list(account_id='a')['items'][0]['feature'],'workspace')
        self.assertEqual(self.ai.ledger.list(account_id='b')['items'],[])

    def test_backup_preserves_global_files_memory_context_and_style_scope(self):
        self.complete(self.prepare('summary'))
        self.complete(self.prepare('style',person_id='100001',cross_group=True))
        run=self.begin();raw=self.tool(run,'read_context',conversation_ids=['group-a'],prefer_cache=False);ref=raw['messages'][0][0]
        file=self.tool(run,'write_markdown',title='备份测试',content='# 合成文件',evidence_ids=[ref])
        attempt=self.ai.ledger.reserve_call(fixtures.MODEL,'agent',1000,512,job_id=run);self.ai.ledger.settle_call(attempt['attempt'],{'input_tokens':40,'output_tokens':10})
        self.app.workspace_agent.finish(run,'a',{'answer':'合成完成','evidence_ids':[ref]})
        backup=self.root/'agent-backup.db';self.app.export_archive(str(backup));restored=fixtures.AssistantService(self.root/'restored')
        restored.manual_import(str(backup),'app_db')
        self.assertEqual(restored.workspace_agent.history('a')['items'][0]['artifacts'][0]['artifact_id'],file['artifact_id'])
        self.assertIn('合成文件',Path(restored.workspace_agent.materialize('a',file['artifact_id'])['path']).read_text(encoding='utf-8'))
        self.assertTrue(any(v['feature']=='workspace' for v in restored.ai.ledger.list(account_id='a')['items']))
        with restored.storage.connect() as conn:self.assertGreater(conn.execute('SELECT count(*) FROM ai_contexts').fetchone()[0],0)

    def test_private_uid_pair_and_paused_memory(self):
        self.complete(self.prepare('summary'))
        with self.app.storage.connect() as conn:
            conn.execute("UPDATE messages SET sender_key='u_shared_identity' WHERE sender_qq='100001' AND account_id='a'")
            self.add_message(conn,'private-message','private','私聊只有UID',400)
            conn.execute("UPDATE messages SET sender_qq='',sender_key='u_shared_identity' WHERE id='private-message'")
        run=self.begin();result=self.tool(run,'read_context',conversation_ids=['group-a','group-b','private'],sender='100001',prefer_cache=False)
        self.assertEqual(result['selected_messages'],4)
        self.ai.save_group('group-a','a',{'remember':False})
        paused=self.tool(run,'read_context',conversation_ids=['group-a'],prefer_cache=True)
        self.assertEqual(paused['reused_messages'],0);self.assertEqual(paused['memory'],[])

    def test_failed_global_history_delete_retains_ledger(self):
        run=self.begin();attempt=self.ai.ledger.reserve_call(fixtures.MODEL,'agent',1000,512,job_id=run)
        self.ai.ledger.settle_call(attempt['attempt'],{'input_tokens':40,'output_tokens':10})
        self.app.workspace_agent.tool_error(run,'a','read_context','合成工具失败')
        self.app.workspace_agent.finish(run,'a',error='合成失败')
        self.assertEqual(self.app.workspace_agent.history('a')['items'][0]['steps'][0]['error'],'合成工具失败')
        self.app.workspace_agent.delete_history(run,'a')
        self.assertEqual(self.app.workspace_agent.history('a')['items'],[])
        self.assertEqual(self.ai.ledger.list(account_id='a')['items'][0]['charged'],50)
