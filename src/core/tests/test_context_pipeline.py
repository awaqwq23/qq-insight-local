import base64,json,hashlib,unittest
import test_ai as fixtures
from local_assistant.errors import CoreError


class ContextPipelineTest(unittest.TestCase):
    def setUp(self):
        fixtures.AITest.setUp(self)
        self.ai.save_budget({'per_run_tokens':1000000})
        with self.app.storage.connect() as conn:conn.execute("UPDATE messages SET text=text||? WHERE conversation_id='group-a'",('合成上下文材料。'*600,))
    add_message=fixtures.AITest.add_message
    prepare=fixtures.AITest.prepare
    output=fixtures.AITest.output

    def start(self,question='总结群聊',cid='group-a'):
        return self.app.workspace_agent.begin('a',question,conversation_id=cid)['run_id']

    def read(self,run,**args):
        return self.app.workspace_agent.tool(run,'a','read_context',{'conversation_ids':['group-a'],**args})

    def compressed(self,run,read,**extra):
        refs=read['uncompressed_references']
        result={'summary':'合成上下文：安排和收到确认。','items':[{'title':'安排','body':'本段围绕课程安排交流。','evidence_ids':refs[:1]}],**extra}
        return self.app.workspace_agent.context_commit(run,'a',refs,result)

    def test_prepare_once_reuse_across_persona_and_presets_only_delta(self):
        run=self.start();read=self.read(run);saved=self.compressed(run,read)
        self.assertEqual(saved['compressed_messages'],2)
        self.app.workspace_agent.finish(run,'a',error='模拟后续任务中断')
        self.assertEqual(self.app.chat_memory.coverage('group-a','a')['compressed'],2)
        run=self.start('总结群成员画像与说话风格');cached=self.read(run)
        self.assertEqual(cached['raw_messages'],0);self.assertEqual(cached['reused_messages'],2)
        self.assertTrue(cached['summaries'][0]['speakers'][0]['reference'])
        with self.app.storage.connect() as conn:self.add_message(conn,'delta','group-a','合成新增安排',200)
        newer=self.read(run);self.assertEqual(newer['raw_messages'],1);self.assertEqual(len(newer['uncompressed_references']),1)
        self.compressed(run,newer)
        self.assertEqual(self.app.chat_memory.coverage('group-a','a')['compressed'],3)
        job=self.prepare('identity',limit=100,goal='不同预设')
        self.assertEqual(job['coverage']['reused_messages'],3);self.assertEqual(job['coverage']['raw_messages'],0)
        self.assertEqual(self.ai.next_chunk(job['job_id'])['stage'],'reduce')

    def test_wrong_person_observation_does_not_abort_valid_reading(self):
        run=self.start();read=self.read(run);ref=read['uncompressed_references'][0]
        saved=self.compressed(run,read,people_memory=[{'subject':'999999','title':'错误归因','body':'不可存入人物画像','evidence_ids':[ref]},
             {'subject':'QQ:100001','title':'表达观察','body':'本段涉及任务确认。','evidence_ids':[ref]}])
        self.assertEqual(len(saved['validation_notes']),1);self.assertEqual(len(saved['context']['people_memory']),1)
        self.assertEqual(saved['context']['people_memory'][0]['subject'],'100001')
        memories=self.ai.memories('group-a','a')['items']
        self.assertFalse(any(m.get('subject')=='999999' for m in memories))
        final=self.app.workspace_agent.finish(run,'a',{'answer':'保留有效回答','evidence_ids':[ref],'people_memory':[{'subject':'wrong','title':'无效','body':'无效','evidence_ids':['r999']} ]})
        self.assertEqual(final['status'],'completed')
        self.assertTrue(any(s['name']=='memory_validation' for s in self.app.workspace_agent.history('a')['items'][0]['steps']))

    def test_explicit_original_read_does_not_silently_reuse_cached_context(self):
        run=self.start();self.compressed(run,self.read(run))
        job=self.prepare('profile',limit=100,goal='直接回源核对',context_reuse=False)
        request=self.ai.next_chunk(job['job_id'])
        result=self.ai.context(job['job_id'],request['attempt'])
        self.assertTrue(result['skip'])
        self.assertEqual(result['reading_mode'],'original')

    def test_partial_cross_group_compression_keeps_uncovered_originals_unread(self):
        agent=self.app.workspace_agent;run=agent.begin('a','总结两个群的发言')['run_id']
        read=agent.tool(run,'a','read_context',{'conversation_ids':['group-a','group-b'],'prefer_cache':False})
        with self.app.storage.connect() as conn:context=json.loads(conn.execute('SELECT context_json FROM workspace_runs WHERE id=?',(run,)).fetchone()[0])
        ref=next(k for k,v in context['refs'].items() if v=='m0');missing=next(k for k,v in context['refs'].items() if v=='m2')
        saved=agent.context_commit(run,'a',read['uncompressed_references'],{'summary':'只整理来源A的合成安排。','items':[{'title':'A安排','body':'来源A在核对安排。','evidence_ids':[ref]}],'group_memory':[{'conversation_id':'group-a','body':'合成安排。','evaluation':'暂定','evidence_ids':[ref]}]})
        self.assertEqual(saved['compressed_messages'],2);self.assertEqual(saved['uncompressed_references'],[missing])
        self.assertEqual(self.app.chat_memory.coverage('group-b','a')['read'],0)
        agent.finish(run,'a',error='模拟后续失败')
        self.assertEqual(self.app.chat_memory.coverage('group-a','a')['read'],2)

    def test_large_supplemental_memory_does_not_block_short_source_records(self):
        with self.app.storage.connect() as conn:
            conn.execute("UPDATE messages SET text='合成短消息' WHERE conversation_id='group-a'")
            for i in range(40):self.ai._save_memory(conn,'group-a','large:'+str(i),'group','group','workspace',{'title':'合成长记忆','body':'合成观察。'*2000},'user','2026-10-26')
        run=self.start();result=self.read(run,prefer_cache=False,_max_bytes=6000)
        self.assertEqual(result['selected_messages'],2);self.assertLessEqual(len(json.dumps(result,ensure_ascii=False).encode()),6000)
        self.assertIn('部分',result['memory_notice'])
        with self.app.storage.connect() as conn:self.assertEqual(conn.execute("SELECT count(*) FROM ai_memories WHERE conversation_id='group-a'").fetchone()[0],40)

    def test_old_unmapped_person_alias_cache_does_not_reuse_semantic_summary(self):
        run=self.start();read=self.read(run);self.compressed(run,read)
        with self.app.storage.connect() as conn:
            row=conn.execute("SELECT id,result_json FROM ai_contexts WHERE conversation_id='group-a'").fetchone();data=json.loads(row['result_json']);data['summary']='p0具有合成偏好';conn.execute('UPDATE ai_contexts SET result_json=? WHERE id=?',(json.dumps(data),row['id']))
        newer=self.start();result=self.read(newer)
        self.assertEqual(result['summaries'],[]);self.assertEqual(result['reused_messages'],result['reused_excerpts'])
        original=self.read(newer,prefer_cache=False);self.assertEqual(original['raw_messages'],2)

    def test_hash_check_and_paused_memory(self):
        run=self.start();read=self.read(run)
        with self.app.storage.connect() as conn:conn.execute("UPDATE messages SET text='来源已改' WHERE id='m0'")
        with self.assertRaises(CoreError):self.compressed(run,read)
        self.assertEqual(self.app.chat_memory.coverage('group-a','a')['compressed'],0)
        self.app.chat_memory.save_settings('group-a','a',{'remember':False})
        run=self.start();read=self.read(run);saved=self.compressed(run,read)
        self.assertEqual(saved['compressed_messages'],0);self.assertEqual(self.app.chat_memory.coverage('group-a','a')['compressed'],0)

    def test_legacy_compression_survives_later_failure_and_reuses(self):
        job=self.prepare();request=self.ai.next_chunk(job['job_id']);context=self.ai.context(job['job_id'],request['attempt'])
        value={'summary':'合成压缩记忆','items':[{'title':'合成安排','body':'任务与收到确认。','evidence_ids':context['references'][:1]}]}
        self.ai.context(job['job_id'],request['attempt'],value,context['references'])
        self.ai.fail(job['job_id'],attempt=request['attempt'],known_not_sent=True)
        self.assertEqual(self.app.chat_memory.coverage('group-a','a')['compressed'],2)
        self.ai.resume(job['job_id'],'a','group-a',fixtures.MODEL)
        next_request=self.ai.next_chunk(job['job_id']);context=self.ai.context(job['job_id'],next_request['attempt'])
        self.assertEqual(context['reused_messages'],2);self.assertEqual(context['material']['messages'],[])

    def test_image_scan_skips_missing_refreshes_index_and_finds_five(self):
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
        root=self.root/'cache';root.mkdir();self.app.media_store.configure('a',str(root))
        # Build an empty index first, then simulate QQ downloading new images.
        self.app.media_store.index('a',[root])
        with self.app.storage.connect() as conn:
            for i in range(7):
                key=f'image-{i}';self.add_message(conn,key,'group-a','[合成图片]',1000+i)
                data=png+bytes([i]);md5=hashlib.md5(data).hexdigest()
                if i<5:(root/(md5+'.png')).write_bytes(data)
                conn.execute('UPDATE messages SET media_json=? WHERE id=?',(json.dumps([{'type':'image','md5':md5,'local_path':'Z:/missing.png'}]),key))
        run=self.start();found=self.app.workspace_agent.tool(run,'a','images',{'conversation_ids':['group-a']})
        self.assertEqual(len(found['items']),5);self.assertEqual(found['missing_images'],2)
        for i,item in enumerate(found['items']):
            ref=item['reference'];self.assertTrue(self.app.workspace_agent.image_data(run,'a',ref,0)['available'])
            self.app.workspace_agent.image_observed(run,'a',ref,0,'合成像素描述')
            self.app.workspace_agent.tool(run,'a','save_image',{'reference':ref,'media_index':0,'title':f'合成图片{i}'})
        self.assertEqual(len(self.app.workspace_agent.artifacts('a',run)),5)
        self.app.workspace_agent.finish(run,'a',{'answer':'已实际保存五张合成图片。','evidence_ids':[i['reference'] for i in found['items']]})
        self.assertEqual(self.app.chat_memory.coverage('group-a','a')['compressed'],0,'image metadata and pixels do not mark unread chat text as analyzed')

    def test_message_marker_changes_when_source_changes(self):
        run=self.start();self.compressed(run,self.read(run))
        self.assertTrue(self.app.message_context('m0','a')['items'][0]['memory']['compressed'])
        with self.app.storage.connect() as conn:conn.execute("UPDATE messages SET text='原文更新' WHERE id='m0'")
        items=self.app.message_context('m0','a')['items'];changed=next(i for i in items if i['id']=='m0')
        self.assertNotIn('memory',changed)

    def test_missing_image_target_is_not_labelled_completed(self):
        run=self.start('帮我找五个合适的表情包、下载')
        with self.assertRaises(CoreError) as raised:self.app.workspace_agent.finish(run,'a',{'answer':'当前未找到可保存的图片。','evidence_ids':[]})
        self.assertEqual(raised.exception.code,'AGENT_TASK_INCOMPLETE');self.assertEqual(raised.exception.data['image_target'],5)
        self.assertEqual(raised.exception.data['saved'],0)
        result=self.app.workspace_agent.finish(run,'a',error='目标保存 5 张，实际保存 0 张')
        self.assertEqual(result['status'],'failed')

    def test_old_partial_job_rebuilds_only_successful_reading_markers(self):
        self.ai.save_budget({'chunk_chars':2000})
        with self.app.storage.connect() as conn:
            for i in range(5):self.add_message(conn,f'partial-{i}','group-a','合成较长记录。'*150,1000+i)
        job=self.prepare(limit=100);request=self.ai.next_chunk(job['job_id'])
        self.ai.commit_chunk(job['job_id'],request['attempt'],self.output(request),{'input_tokens':10,'output_tokens':10})
        self.ai.fail(job['job_id'],known_not_sent=True)
        covered=self.app.chat_memory.coverage('group-a','a')
        self.assertGreater(covered['compressed'],0);self.assertGreater(covered['unread'],0)
        with self.app.storage.connect() as conn:conn.execute("UPDATE messages SET text='旧来源更改' WHERE id='m0'")
        read=self.app.chat_memory.coverage('group-a','a');self.assertLess(read['compressed'],covered['compressed'])

    def test_unread_pagination_keeps_zero_offset_after_compression(self):
        run=self.start();first=self.read(run,unread_only=True,limit=1)
        self.assertTrue(first['has_more']);self.assertEqual(first['next_offset'],0)
        self.compressed(run,first)
        second=self.read(run,unread_only=True,limit=1,offset=first['next_offset'])
        self.assertNotEqual(first['uncompressed_references'],second['uncompressed_references'])
        self.compressed(run,second);self.assertEqual(self.app.chat_memory.coverage('group-a','a')['unread'],0)

    def test_targeted_refinement_keeps_the_other_cached_range(self):
        run=self.start();self.compressed(run,self.read(run))
        original=self.read(run,prefer_cache=False,limit=1)
        self.compressed(run,original)
        cached=self.read(run)
        self.assertEqual(cached['reused_messages'],2);self.assertEqual(cached['raw_messages'],0)
        self.assertEqual(len(cached['summaries']),2)
