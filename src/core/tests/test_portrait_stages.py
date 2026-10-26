"""Synthetic checks for scoped, incremental portraits and source-safe partial success."""
import hashlib,json,unittest
from pathlib import Path
import test_ai as fixtures
from local_assistant.errors import CoreError


class PortraitStagesTest(unittest.TestCase):
    setUp=fixtures.AITest.setUp
    add_message=fixtures.AITest.add_message
    prepare=fixtures.AITest.prepare
    output=fixtures.AITest.output
    complete=fixtures.AITest.complete

    def people(self,count=19):
        with self.app.storage.connect() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id='group-a'")
            for i in range(count):
                self.add_message(conn,'p'+str(i),'group-a','合成：最近在玩游戏A，哈哈。',100+i)
                conn.execute('UPDATE messages SET sender_qq=?,sender_key=? WHERE id=?',(str(200001+i),'u_member'+str(i),'p'+str(i)))

    def portrait(self,request):
        material=json.loads(request['user']);items=[]
        for row in material['messages']:
            m=fixtures.wire_message(material,row)
            items.append({'subject':m['sender_qq'],'title':'阶段画像','body':'语气：口语短句；兴趣：近期可能关注游戏A；性格倾向与习惯：待补充。','uncertainty':'仅为当前少量发言的暂定推测。','evidence_ids':[m['id']]})
        return {'summary':'本段成员的阶段画像，不代表完整人格。','items':items}

    def test_single_member_is_exact_and_keeps_only_the_selected_source(self):
        self.people(12)
        job=self.prepare('profile',person_id='200002',limit=100,context_reuse=False)
        self.assertEqual(job['coverage']['selected'],1)
        request=self.ai.next_chunk(job['job_id']);material=json.loads(request['user'])
        self.assertEqual(material['request']['profile_people'],['200002'])
        self.assertNotIn('u_member11',request['user'])
        self.ai.commit_chunk(job['job_id'],request['attempt'],self.portrait(request),{'input_tokens':10,'output_tokens':20})
        self.complete(job)
        result=self.app.chat_memory.view('group-a','a','people',query='200002')
        self.assertTrue(any(m.get('stage')=='partial' and '游戏A' in m['body'] for p in result['items'] for m in p['memories']))

    def test_all_speakers_are_partitioned_into_small_complete_batches(self):
        self.people(25);job=self.prepare('profile',limit=100,context_reuse=False)
        with self.app.storage.connect() as conn:chunks=[json.loads(r[0]) for r in conn.execute('SELECT messages_json FROM ai_chunks WHERE job_id=?',(job['job_id'],))]
        self.assertEqual(job['coverage']['selected_people'],25)
        self.assertEqual({m['id'] for chunk in chunks for m in chunk},{'p'+str(i) for i in range(25)})
        self.assertTrue(all(len({m['sender_qq'] for m in chunk})<=8 for chunk in chunks))

    def test_successful_batch_survives_later_failure_as_viewable_partial_memory(self):
        self.people(18);job=self.prepare('profile',limit=100,context_reuse=False)
        request=self.ai.next_chunk(job['job_id']);payload=self.portrait(request)
        self.ai.commit_chunk(job['job_id'],request['attempt'],payload,{'input_tokens':10,'output_tokens':20})
        with self.app.storage.connect() as conn:self.assertTrue(conn.execute("SELECT 1 FROM ai_memories WHERE conversation_id='group-a' AND kind='person'").fetchone(),'successful portraits are viewable before the rest of the job finishes')
        failed=self.ai.fail(job['job_id'],message='合成第二批失败')
        self.assertNotEqual(failed['status'],'completed')
        with self.app.storage.connect() as conn:
            memories=[json.loads(r[0]) for r in conn.execute("SELECT data_json FROM ai_memories WHERE conversation_id='group-a' AND kind='person'")]
            read=conn.execute("SELECT count(*) FROM ai_message_memory WHERE conversation_id='group-a'").fetchone()[0]
        self.assertTrue(any(m.get('stage')=='partial' and '游戏A' in m['body'] for m in memories))
        self.assertEqual(read,len(payload['items']));self.assertLess(read,18)

    def test_old_report_items_do_not_leak_into_current_report(self):
        with self.app.storage.connect() as conn:conn.execute("UPDATE messages SET text='合成第二项：请整理另一份报告。' WHERE id='m1'")
        first=self.prepare('work',mode='time',start=100,end=101);self.complete(first,'较早事项')
        second=self.prepare('work',mode='time',start=101,end=102);self.complete(second,'本轮事项')
        report=self.ai.history('group-a','a',job_id=second['job_id'])['report']
        self.assertEqual([i['title'] for i in report['items']],['本轮事项'])
        with self.app.storage.connect() as conn:self.assertEqual(conn.execute("SELECT count(*) FROM ai_items WHERE conversation_id='group-a'").fetchone()[0],2)

    def test_local_person_labels_are_restored_without_changing_literal_code(self):
        job=self.prepare('profile',limit=100,context_reuse=False);request=self.ai.next_chunk(job['job_id']);payload=self.portrait(request)
        payload['items'][0]['body']='p0使用短句；兴趣待补。'
        self.ai.commit_chunk(job['job_id'],request['attempt'],payload,{'input_tokens':10,'output_tokens':20});self.complete(job)
        bodies=[i['body'] for i in self.ai.history('group-a','a',job_id=job['job_id'])['report']['items']]
        self.assertTrue(any('合成人' in body for body in bodies));self.assertTrue(all('p0' not in body for body in bodies))
        code={'summary':'代码 p0 不能改写'};self.ai._restore_people_labels(code,{'p0':{'name':'合成人'}},[{'text':'代码变量 p0'}]);self.assertEqual(code['summary'],'代码 p0 不能改写')

    def test_identity_does_not_recycle_unverified_role_or_overwrite_manual_role(self):
        self.ai.save_group('group-a','a',{'role':'合成旧推断'})
        with self.app.storage.connect() as conn:
            data=json.loads(conn.execute("SELECT settings_json FROM ai_group_settings WHERE conversation_id='group-a'").fetchone()[0]);data['role_source']='inferred';conn.execute("UPDATE ai_group_settings SET settings_json=? WHERE conversation_id='group-a'",(json.dumps(data),))
        old=self.prepare('identity',context_reuse=False);request=self.ai.next_chunk(old['job_id']);self.assertNotIn('合成旧推断',request['user']);self.ai.fail(old['job_id'],attempt=request['attempt'],known_not_sent=True)
        self.app.save_profile('用户确认角色','group-a','a')
        job=self.prepare('identity',context_reuse=False);request=self.ai.next_chunk(job['job_id']);payload=self.output(request);payload['items'][0]['title']='模型不同候选'
        self.ai.commit_chunk(job['job_id'],request['attempt'],payload,{'input_tokens':10,'output_tokens':20});self.complete(job)
        self.assertEqual(self.ai.get_group('group-a','a')['role'],'用户确认角色');self.assertEqual(self.ai.get_group('group-a','a')['role_source'],'manual')

    def test_only_part_of_a_long_message_is_not_marked_fully_read(self):
        with self.app.storage.connect() as conn:self.add_message(conn,'long-part','group-a','合成短句。'*2500,2000)
        job=self.prepare('profile',limit=1,context_reuse=False);request=self.ai.next_chunk(job['job_id']);payload=self.portrait(request)
        for item in payload['items']:item['body']='语气：重复短句；其他维度待补充。'
        self.ai.commit_chunk(job['job_id'],request['attempt'],payload,{'input_tokens':10,'output_tokens':20});self.ai.fail(job['job_id'],message='合成剩余长消息分段失败')
        report=self.ai.history('group-a','a',job_id=job['job_id'])['report'];self.assertEqual(report['coverage']['completed_messages'],0)
        with self.app.storage.connect() as conn:self.assertFalse(conn.execute("SELECT 1 FROM ai_message_memory WHERE message_id='long-part'").fetchone())

    def test_changed_source_cannot_enter_immediate_partial_portraits(self):
        job=self.prepare('profile',limit=100,context_reuse=False);request=self.ai.next_chunk(job['job_id'])
        with self.app.storage.connect() as conn:conn.execute("UPDATE messages SET text='合成改动后的消息' WHERE id='m0'")
        with self.assertRaises(CoreError) as error:self.ai.commit_chunk(job['job_id'],request['attempt'],self.portrait(request),{'input_tokens':10,'output_tokens':20})
        self.assertEqual(error.exception.code,'AI_SOURCE_CHANGED')
        with self.app.storage.connect() as conn:self.assertFalse(conn.execute("SELECT 1 FROM ai_memories WHERE conversation_id='group-a' AND kind='person'").fetchone())

    def test_invalid_optional_group_and_person_observations_do_not_destroy_valid_items(self):
        self.people(2);job=self.prepare('profile',limit=100,context_reuse=False);request=self.ai.next_chunk(job['job_id']);payload=self.portrait(request)
        payload['items'].append({'subject':'999999','title':'错误人物','body':'不能收录','evidence_ids':payload['items'][0]['evidence_ids']})
        payload['group_memory']=[{'conversation_id':'group-b','body':'错误来源','evidence_ids':payload['items'][0]['evidence_ids']}]
        self.ai.commit_chunk(job['job_id'],request['attempt'],payload,{'input_tokens':10,'output_tokens':20});self.complete(job)
        report=self.ai.history('group-a','a',job_id=job['job_id'])['report']
        self.assertEqual(len(report['items']),2)
        self.assertGreaterEqual(len(report['coverage']['validation_notes']),2)
        self.assertEqual(self.ai.memories('group-b','a')['items'],[])

    def test_native_portrait_tool_checks_scope_and_imports_validated_sources(self):
        self.people(2);agent=self.app.workspace_agent;run=agent.begin('a','分析本群成员阶段画像',conversation_id='group-a')['run_id']
        with self.assertRaises(CoreError):agent.profile_request(run,'a',{'conversation_id':'group-b'})
        plan=agent.profile_request(run,'a',{'conversation_id':'group-a','person_id':'200002','limit':20})
        job=self.ai.prepare(model=fixtures.MODEL,**plan)
        request=self.ai.next_chunk(job['job_id']);self.ai.commit_chunk(job['job_id'],request['attempt'],self.portrait(request),{'input_tokens':10,'output_tokens':20});self.complete(job)
        result=agent.profile_result(run,'a',job['job_id'])
        self.assertEqual(result['profiled_people'],1);self.assertTrue(result['evidence_ids'])
        cached=self.ai.prepare(model=fixtures.MODEL,**plan)
        self.assertEqual(cached['status'],'cached')
        self.assertEqual(agent.profile_result(run,'a',cached['job_id'])['profiled_people'],1)
        self.assertEqual(agent.finish(run,'a',{'answer':'先保存部分画像，继续补充。','evidence_ids':result['evidence_ids']})['status'],'completed')
        other=agent.begin('a','分析本群画像',conversation_id='group-a')['run_id']
        with self.assertRaises(CoreError):agent.profile_result(other,'a',job['job_id'])

    def test_zero_source_portrait_is_honest_empty_only_after_scoped_lookup(self):
        agent=self.app.workspace_agent;run=agent.begin('a','分析本群成员画像',conversation_id='group-a')['run_id']
        with self.assertRaises(CoreError):agent.finish(run,'a',{'answer':'未读不能猜测。','evidence_ids':[]})
        plan=agent.profile_request(run,'a',{'conversation_id':'group-a','person_id':'999999','limit':20})
        job=self.ai.prepare(model=fixtures.MODEL,**plan);self.assertEqual(job['status'],'empty')
        result=agent.profile_result(run,'a',job['job_id']);self.assertEqual(result['processed_messages'],0)
        self.assertEqual(agent.finish(run,'a',{'answer':'当前范围没有此人的本人发言，未知内容待补充。','evidence_ids':[]})['status'],'completed')

    def test_cross_group_style_tool_is_global_only_and_keeps_final_prompt(self):
        agent=self.app.workspace_agent;run=agent.begin('a','跨群分析人物100001的风格')['run_id']
        plan=agent.profile_request(run,'a',{'conversation_id':'group-a','person_id':'100001','cross_group':True,'limit':100})
        self.assertEqual(plan['feature'],'style');job=self.ai.prepare(model=fixtures.MODEL,**plan);self.complete(job)
        result=agent.profile_result(run,'a',job['job_id']);self.assertEqual(result['source_groups'],2);self.assertTrue(any(i.get('drafts') for i in result['items']))
        fixed=agent.begin('a','分析本群人物风格',conversation_id='group-a')['run_id']
        with self.assertRaises(CoreError):agent.profile_request(fixed,'a',{'conversation_id':'group-a','person_id':'100001','cross_group':True})

    def test_style_phrase_statistics_use_only_actual_input(self):
        with self.app.storage.connect() as conn:conn.execute("UPDATE messages SET text='哈哈，明天试试。' WHERE conversation_id='group-a'")
        job=self.prepare('style',person_id='100001',cross_group=True,context_reuse=False,limit=100)
        request=self.ai.next_chunk(job['job_id']);statistics=json.loads(request['user'])['style_statistics'];phrase=next(p for p in statistics['phrases'] if p['text']=='哈哈')
        self.assertEqual(phrase['message_hits'],2);self.assertEqual(len(phrase['evidence_ids']),2)

    def test_visual_matches_save_immediately_only_when_user_requested_saving(self):
        png=(Path(__file__).resolve().parents[2]/'desktop/main/test-assets/vision.png').read_bytes()
        with self.app.storage.connect() as conn:
            for i in range(5):
                key='img'+str(i);self.add_message(conn,key,'group-a','[合成图片]',500+i);data=png+bytes([i]);sha=hashlib.sha256(data).hexdigest()
                conn.execute('INSERT INTO media_assets VALUES(?,?,?)',(sha,'image/png',data));conn.execute('INSERT INTO message_media VALUES(?,?,?)',(key,0,sha));conn.execute('UPDATE messages SET media_json=? WHERE id=?',(json.dumps([{'type':'image'}]),key))
        agent=self.app.workspace_agent;run=agent.begin('a','找5张可爱表情并保存',conversation_id='group-a')['run_id']
        images=agent.tool(run,'a','images',{'conversation_ids':['group-a']})['items']
        for item in images:result=agent.image_observed(run,'a',item['reference'],0,'实际合成像素，有可爱元素。',suitable=True)
        self.assertTrue(result['target_reached']);self.assertEqual(len(result['saved_references']),5);self.assertEqual(len(agent.artifacts('a',run)),5)
        agent.finish(run,'a',{'answer':'保存五张。','evidence_ids':result['saved_references']})
        look=agent.begin('a','只看图判断是否可爱',conversation_id='group-a')['run_id'];ref=agent.tool(look,'a','images',{'conversation_ids':['group-a']})['items'][0]['reference']
        self.assertEqual(agent.image_observed(look,'a',ref,0,'合成可爱图案',suitable=True)['saved_count'],0)


if __name__=='__main__':unittest.main()
