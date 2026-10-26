import json
from test_ai import AITest,MODEL,wire_message
from local_assistant.errors import CoreError

class ModelLimitsTest(AITest):
    def test_new_output_budget_applies_after_current_chunk_without_frozen_preference(self):
        self.ai.save_budget({'output_tokens':65536,'per_run_tokens':1000000,'daily_tokens':1000000,'chunk_chars':2000})
        with self.app.storage.connect() as conn:
            for i in range(3):self.add_message(conn,f'live-output-{i}','group-a','合成详细消息。'*400,300+i)
        model={**MODEL,'limits':{'context_tokens':1000000,'output_tokens':65536,'output_limit_tokens':393216}}
        job=self.ai.prepare('group-a','a','summary',model,{'limit':100})
        first=self.ai.next_chunk(job['job_id']);self.assertEqual(first['max_tokens'],65536)
        self.ai.commit_chunk(job['job_id'],first['attempt'],self.output(first),{'input_tokens':10,'output_tokens':10})
        self.ai.save_budget({'output_tokens':131072})
        second=self.ai.next_chunk(job['job_id']);self.assertFalse(second['done']);self.assertEqual(second['max_tokens'],131072)
        self.ai.fail(job['job_id'],attempt=second['attempt'],known_not_sent=True)
        self.assertEqual(self.ai.budget()['daily_used'],20)

    def test_long_output_passes_core_budget_and_request_without_old_16k_clamp(self):
        self.ai.save_budget({'output_tokens':65536,'per_run_tokens':1000000,'daily_tokens':1000000})
        model={**MODEL,'limits':{'context_tokens':1000000,'output_tokens':65536,'output_limit_tokens':393216,'basis':'official'}}
        job=self.ai.prepare('group-a','a','profile',model,{'limit':100})
        request=self.ai.next_chunk(job['job_id'])
        self.assertEqual(request['max_tokens'],65536)
        self.assertGreater(self.ai.budget()['daily_used'],65536)
        self.ai.fail(job['job_id'],attempt=request['attempt'],known_not_sent=True)
        self.assertEqual(self.ai.budget()['daily_used'],0)

    def test_large_output_setting_persists_and_boundaries_are_validated(self):
        self.assertEqual(self.ai.budget()['output_tokens'],65536)
        self.ai.save_budget({'output_tokens':393216})
        self.assertEqual(self.ai.budget()['output_tokens'],393216)
        with self.assertRaises(CoreError):self.ai.save_budget({'output_tokens':1000001})
        self.assertEqual(self.ai.budget()['output_tokens'],393216)

    def test_verified_large_context_reduces_chunks_and_keeps_every_message(self):
        with self.app.storage.connect() as conn:
            for i in range(1001):self.add_message(conn,f'synthetic-capacity-long-id-{i}','group-a',f'合成事项{i}：截止周五，完整正文不可压缩。',200+i)
        self.ai.save_budget({'per_run_tokens':5000000,'daily_tokens':10000000})
        small=self.ai.prepare('group-a','a','summary',MODEL,{'limit':1001,'compression':'off'})
        self.ai.fail(small['job_id'],known_not_sent=True)
        model={**MODEL,'limits':{'context_tokens':262144,'basis':'manual','output_tokens':4096}}
        large=self.ai.prepare('group-a','a','summary',model,{'limit':1001,'compression':'off'})
        self.assertLess(large['coverage']['chunks'],small['coverage']['chunks'])
        seen=[]
        while True:
            request=self.ai.next_chunk(large['job_id'])
            if request['done']:break
            material=json.loads(request['user']);self.assertEqual(material['compression']['mode'],'off')
            originals={alias:key for key,alias in request['evidence_aliases'].items()}
            seen.extend(originals[row['id']] for row in [wire_message(material,row) for row in material['messages']])
            self.assertTrue(all('完整正文不可压缩' in row['text'] for row in [wire_message(material,row) for row in material['messages']]))
            self.ai.commit_chunk(large['job_id'],request['attempt'],{'summary':'合成摘要','items':[]},{'input_tokens':100,'output_tokens':10})
        self.ai.finish(large['job_id']);self.assertEqual(len(seen),1001);self.assertEqual(len(set(seen)),1001)

    def test_complete_prompt_splits_without_losing_chronology(self):
        with self.app.storage.connect() as conn:
            for i in range(12):self.add_message(conn,f'capacity-{i}','group-a','合成消息'*250,200+i)
        model={**MODEL,'limits':{'context_tokens':14000,'input_tokens':8000,'output_tokens':512,'tpm_tokens':0}}
        self.ai.save_budget({'per_run_tokens':1000000,'daily_tokens':1000000})
        prepared=self.ai.prepare('group-a','a','summary',model,{'limit':100})
        seen=[];previous_index=-1;assembled={}
        while True:
            request=self.ai.next_chunk(prepared['job_id'])
            if request['done']:break
            self.assertGreater(request['index'],previous_index);previous_index=request['index']
            self.assertLessEqual(len((request['system']+request['user']).encode())+512,8000)
            self.assertEqual(request['max_tokens'],512)
            originals={value:key for key,value in request['evidence_aliases'].items()}
            seen.extend(originals[message[0]] for message in json.loads(request['user'])['messages'])
            for row in json.loads(request['user'])['messages']:
                key=originals[row[0]];assembled[key]=assembled.get(key,'')+row[4]
            self.ai.commit_chunk(prepared['job_id'],request['attempt'],{'summary':'合成摘要','items':[]},{'input_tokens':100,'output_tokens':10})
        self.assertEqual(list(dict.fromkeys(seen)),['m0','m1']+[f'capacity-{i}' for i in range(12)])
        self.assertTrue(all(assembled[f'capacity-{i}']=='合成消息'*250 for i in range(12)))
        self.ai.finish(prepared['job_id'])

    def test_non_collection_ignores_irrelevant_picture_index(self):
        request=self.ai.next_chunk(self.prepare('summary')['job_id'])
        material=json.loads(request['user']);messages=[wire_message(material,row) for row in material['messages']];payload=self.output(request)
        payload['items'][0]['media_index']=0
        self.assertEqual(self.ai._validate(payload,messages,[],'summary')['items'][0]['media_index'],-1)
        with self.assertRaises(CoreError):self.ai._validate(payload,messages,[],'collection')

    def test_resume_old_jobs_with_updated_capacity(self):
        prepared=self.prepare();request=self.ai.next_chunk(prepared['job_id'])
        self.ai.fail(prepared['job_id'],attempt=request['attempt'],known_not_sent=True)
        model={**MODEL,'limits':{'context_tokens':32000,'tpm_tokens':0,'output_tokens':1024,'input_tokens':20000}}
        self.ai.resume(prepared['job_id'],'a','group-a',model)
        self.assertEqual(self.ai.next_chunk(prepared['job_id'])['max_tokens'],1024)

    def test_capacity_test_ledger_obeys_shared_budget(self):
        self.ai.save_budget({'daily_tokens':1000})
        with self.assertRaises(CoreError):self.ai.ledger.reserve_call(MODEL,'test_capacity',1000,512)
        self.ai.save_budget({'daily_tokens':100000})
        entry=self.ai.ledger.reserve_call(MODEL,'test_capacity',1000,512)
        self.ai.ledger.settle_call(entry['attempt'],{'input_tokens':30,'output_tokens':10})
        self.assertEqual(self.ai.ledger.list()['items'][0]['kind'],'test_capacity')
