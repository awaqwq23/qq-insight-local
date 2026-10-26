import json
import unittest
import test_ai as fixtures
from local_assistant.ai_prompts import FEATURES
from local_assistant.errors import CoreError

class HierarchyTest(unittest.TestCase):
    setUp=fixtures.AITest.setUp
    add_message=fixtures.AITest.add_message
    output=fixtures.AITest.output
    def test_reduce_does_not_duplicate_internal_memory_observations(self):
        with self.app.storage.connect() as conn:
            self.ai._save_memory(conn,'group-a','test:memory','group','group','work',{'body':'合成短观察','observations':['INTERNAL_NOT_FOR_PROMPT'*10000],'observed_messages':{'internal':'x'*10000}},'user','2026-10-26')
        model={**fixtures.MODEL,'limits':{'context_tokens':32768,'output_tokens':4096}}
        job=self.ai.prepare('group-a','a','summary',model,{'hierarchical':True,'context_reuse':False})
        first=self.ai.next_chunk(job['job_id']);self.ai.commit_chunk(job['job_id'],first['attempt'],self.output(first),{'input_tokens':10,'output_tokens':20})
        reduced=self.ai.next_chunk(job['job_id']);self.assertEqual(reduced['stage'],'reduce')
        self.assertNotIn('INTERNAL_NOT_FOR_PROMPT',reduced['user'])
        material=json.loads(reduced['user']);self.assertNotIn('long_term_memory',material['request'])
        self.assertEqual(material['long_term_memory'][0]['body'],'合成短观察')
    def test_all_features_and_watch_targets_preserve_scope(self):
        self.ai.save_budget({'per_run_tokens':5000000,'daily_tokens':10000000})
        self.ai.save_group('group-a','a',{'watch_people':['100001','missing']})
        for feature in (key for key in FEATURES if key!='style'):
            job=self.ai.prepare('group-a','a',feature,fixtures.MODEL,{'hierarchical':True,'compression':'balanced','output_chars':700})
            while True:
                request=self.ai.next_chunk(job['job_id'])
                if request['done']:break
                self.ai.commit_chunk(job['job_id'],request['attempt'],self.output(request),{'input_tokens':20,'output_tokens':10})
            self.ai.finish(job['job_id']);history=self.ai.history('group-a','a',feature=feature,job_id=job['job_id'])
            self.assertEqual(history['report']['coverage']['completed_messages'],2)
            self.assertIn('分段汇总',history['report']['summary'])
            if feature=='watch':self.assertEqual(history['report']['coverage']['watch_people'][1]['status'],'no_messages')

    def test_multiple_layers_and_final_word_target_evidence(self):
        self.ai.save_budget({'per_run_tokens':5000000,'daily_tokens':10000000})
        with self.app.storage.connect() as conn:
            for i in range(450):self.add_message(conn,f'synthetic-hierarchy-{i}','group-a',f'事项{i}，周五提交。'+'合成语境。'*35,200+i)
        job=self.ai.prepare('group-a','a','summary',fixtures.MODEL,{'limit':1000,'compression':'strong','hierarchical':True,'output_chars':1234})
        map_calls=merge_calls=0;max_level=0;final_chars=None
        while True:
            request=self.ai.next_chunk(job['job_id'])
            if request['done']:break
            material=json.loads(request['user'])
            if request['stage']=='map':
                map_calls+=1;self.assertEqual(material['request']['output_chars'],200)
            else:
                merge_calls+=1;max_level=max(max_level,request['level']);final_chars=material['request']['output_chars']
                self.assertIn('partial_reports',material);self.assertNotIn('text',material['messages'][0])
            self.ai.commit_chunk(job['job_id'],request['attempt'],self.output(request,title=f"合成阶段{request['index']}"),{'input_tokens':50,'output_tokens':20})
        self.ai.finish(job['job_id']);history=self.ai.history('group-a','a',feature='summary',job_id=job['job_id'])
        self.assertEqual(history['report']['coverage']['completed_messages'],452)
        self.assertGreater(map_calls,4);self.assertGreater(merge_calls,1);self.assertGreater(max_level,1);self.assertEqual(final_chars,1234)
        self.assertIn('分段汇总',history['report']['summary']);self.assertEqual(history['report']['summary'].count('合成摘要'),1)
        self.assertTrue(all(not key.startswith('m') or key in ('m0','m1') for item in history['report']['items'] for key in item['evidence_ids']))
        self.assertEqual(history['report']['coverage']['hierarchical']['merge_calls'],merge_calls)
        self.assertEqual(len(history['report']['stages']),map_calls+merge_calls)

    def test_reduce_failure_resume_preserves_maps_and_illegal_evidence_rejected(self):
        job=self.ai.prepare('group-a','a','summary',fixtures.MODEL,{'hierarchical':True})
        request=self.ai.next_chunk(job['job_id']);self.ai.commit_chunk(job['job_id'],request['attempt'],self.output(request),{'input_tokens':10,'output_tokens':10})
        merge=self.ai.next_chunk(job['job_id']);self.assertEqual(merge['stage'],'reduce')
        bad=self.output(merge);bad['items'][0]['evidence_ids']=['m999']
        with self.assertRaises(CoreError):self.ai.commit_chunk(job['job_id'],merge['attempt'],bad,{'input_tokens':10,'output_tokens':10})
        self.ai.resume(job['job_id'],'a','group-a',fixtures.MODEL)
        again=self.ai.next_chunk(job['job_id']);self.assertEqual(again['stage'],'reduce');self.assertEqual(again['index'],merge['index'])
        self.ai.commit_chunk(job['job_id'],again['attempt'],self.output(again),{'input_tokens':10,'output_tokens':10})
        self.assertTrue(self.ai.next_chunk(job['job_id'])['done']);self.ai.finish(job['job_id'])
        with self.app.storage.connect() as conn:self.assertEqual(conn.execute("SELECT count(*) FROM ai_usage WHERE job_id=?",(job['job_id'],)).fetchone()[0],3)
        with self.assertRaises(CoreError):self.ai.history('group-a','b',job_id=job['job_id'])

    def test_defaults_cache_and_budget_apply_to_merge(self):
        self.ai.save_group('group-a','a',{'hierarchical':True,'output_chars':777})
        job=self.ai.prepare('group-a','a','summary',fixtures.MODEL)
        request=self.ai.next_chunk(job['job_id']);self.ai.commit_chunk(job['job_id'],request['attempt'],self.output(request),{'input_tokens':10,'output_tokens':10})
        self.ai.save_budget({'per_run_tokens':1000})
        with self.assertRaises(CoreError):self.ai.next_chunk(job['job_id'])
        self.ai.fail(job['job_id'],known_not_sent=True)
        self.assertEqual(self.ai.history('group-a','a',job_id=job['job_id'])['jobs'][0]['status'],'failed')
        self.ai.save_budget({'per_run_tokens':1000000})
        self.ai.resume(job['job_id'],'a','group-a',fixtures.MODEL)
        merge=self.ai.next_chunk(job['job_id']);self.assertEqual(merge['stage'],'reduce')
        self.ai.commit_chunk(job['job_id'],merge['attempt'],self.output(merge),{'input_tokens':10,'output_tokens':10})
        self.assertTrue(self.ai.next_chunk(job['job_id'])['done']);self.ai.finish(job['job_id'])
        with self.assertRaises(CoreError):self.ai.prepare('group-a','a','summary',fixtures.MODEL,{'hierarchical':1})
