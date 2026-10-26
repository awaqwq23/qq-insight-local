"""Synthetic acceptance of explicit cross-group scope, memory and deletion billing."""
import json
import unittest
import test_ai as fixtures
from local_assistant.errors import CoreError


class PeopleTest(unittest.TestCase):
    setUp=fixtures.AITest.setUp
    add_message=fixtures.AITest.add_message
    prepare=fixtures.AITest.prepare
    output=fixtures.AITest.output
    complete=fixtures.AITest.complete
    def test_style_scope_requires_explicit_identity_and_excludes_other_accounts_and_private(self):
        with self.assertRaises(CoreError):self.prepare('style')
        with self.assertRaises(CoreError):self.prepare('style',person_id='合成人',cross_group=True)
        with self.app.storage.connect() as conn:self.add_message(conn,'private-msg','private','私聊不能混入',200)
        job=self.prepare('style',person_id='100001',cross_group=True,limit=100)
        self.assertEqual(job['coverage']['selected'],3);self.assertEqual(job['coverage']['source_groups'],2)
        request=self.ai.next_chunk(job['job_id']);material=json.loads(request['user'])
        self.assertIn('私有群B内容',request['user']);self.assertNotIn('账号B内容',request['user']);self.assertNotIn('私聊不能混入',request['user'])
        self.assertEqual(material['request']['person_id'],'100001')
        self.assertEqual(material['time_precision'],'minute');self.assertTrue(all(len(row[2])==5 for row in material['messages']))
        output=self.output(request);output['items'][0]['drafts']=['你在进行风格模拟：短句，保留不确定性，不自称本人。']
        self.ai.commit_chunk(job['job_id'],request['attempt'],output,{'input_tokens':30,'output_tokens':20})
        self.complete(job)
        history=self.ai.history('group-a','a',feature='style',job_id=job['job_id'])
        self.assertEqual(history['report']['items'][0]['subject'],'100001');self.assertTrue(history['report']['items'][0]['drafts'])
        ordinary=self.prepare('summary');prompt=self.ai.next_chunk(ordinary['job_id'])
        self.assertNotIn('风格模拟',prompt['user'])

    def test_evidence_backed_person_memory_survives_restart_and_honors_correction(self):
        job=self.prepare('summary');request=self.ai.next_chunk(job['job_id']);output=self.output(request)
        output['people_memory']=[{'subject':'100001','title':'表达习惯','body':'本段常用短句确认任务。','uncertainty':'样本少','evidence_ids':['m0']}]
        self.ai.commit_chunk(job['job_id'],request['attempt'],output,{'input_tokens':20,'output_tokens':20});self.complete(job)
        memory=next(item for item in self.ai.memories('group-a','a')['items'] if item['memory_key']=='auto:summary:100001')
        self.assertEqual(memory['evidence_ids'],['m0'])
        self.ai.update_memory('group-a','a','auto:summary:100001','correct','用户更正：这是任务群里的正式表达。')
        restarted=fixtures.AssistantService(self.root/'app').ai
        request=restarted.next_chunk(restarted.prepare('group-a','a','reply',fixtures.MODEL)['job_id'])
        self.assertIn('用户更正',request['user']);self.assertNotIn('私有群B内容',request['user'])
        self.ai.update_memory('group-a','a','auto:summary:100001','forget')
        self.assertNotIn('用户更正',json.dumps(self.ai.memories('group-a','a'),ensure_ascii=False))
        with self.assertRaises(CoreError):self.ai.update_memory('group-a','b','auto:summary:100001','forget')

    def test_invented_item_evidence_rejected_and_failed_history_deletes_without_refund(self):
        job=self.prepare();request=self.ai.next_chunk(job['job_id']);output=self.output(request)
        output['people_memory']=[{'subject':'999999','title':'不能归因','body':'合成','evidence_ids':['m0']}]
        output['items'][0]['evidence_ids']=['invented']
        with self.assertRaises(CoreError):self.ai.commit_chunk(job['job_id'],request['attempt'],output,{'input_tokens':70,'output_tokens':30})
        failed=self.ai.history('group-a','a')['jobs'][0]
        self.assertEqual(failed['coverage']['completed_messages'],0);self.assertEqual(failed['coverage']['failed_chunk_messages'],2)
        self.ai.delete_history('group-a','a',job['job_id'])
        self.assertEqual(self.ai.history('group-a','a')['jobs'],[]);self.assertEqual(self.ai.budget()['daily_used'],100)
        self.assertEqual(self.ai.ledger.list(account_id='a')['items'][0]['input_tokens'],70)
        with self.assertRaises(CoreError):self.ai.resume(job['job_id'],'a','group-a',fixtures.MODEL)
        with self.app.storage.connect() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM ai_chunks WHERE job_id=?',(job['job_id'],)).fetchone()[0],0)

    def test_style_does_not_publish_partial_drafts_or_mix_previous_final_prompts(self):
        job=self.prepare('style',person_id='100001',cross_group=True,limit=100)
        request=self.ai.next_chunk(job['job_id'])
        self.ai.commit_chunk(job['job_id'],request['attempt'],self.output(request),{'input_tokens':20,'output_tokens':10})
        self.ai.fail(job['job_id'],message='合成汇总前中断')
        self.assertEqual(self.ai.history('group-a','a',feature='style')['items'],[])
        self.ai.resume(job['job_id'],'a','group-a',fixtures.MODEL);self.complete(job)
        newer=self.prepare('style',person_id='100001',cross_group=True,limit=2,goal='生成新的风格版本')
        self.complete(newer,title='新版风格')
        report=self.ai.history('group-a','a',feature='style',job_id=newer['job_id'])['report']
        self.assertTrue(report['items']);self.assertTrue(all(item['title']=='新版风格' for item in report['items']))
