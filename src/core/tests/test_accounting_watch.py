import json
import unittest
import test_ai
MODEL=test_ai.MODEL

PRICE={'basis':'official','unit':'token','currency':'CNY','input_price':2,'output_price':8,'cached_input_price':0.4,'source':'https://example.test/official','verified_at':'2026-10-01'}

class AccountingWatchTest(unittest.TestCase):
    setUp=test_ai.AITest.setUp
    add_message=test_ai.AITest.add_message
    prepare=test_ai.AITest.prepare
    output=test_ai.AITest.output
    complete=test_ai.AITest.complete
    # Shared fixtures, new behavior assertions below.
    def test_history_totals_include_calls_beyond_preview(self):
        prepared=self.prepare('work')
        for _ in range(201):
            entry=self.ai.ledger.reserve_call({**MODEL,'pricing':PRICE},'vision',1,1,job_id=prepared['job_id'])
            self.ai.ledger.settle_call(entry['attempt'],{'input_tokens':1,'output_tokens':1})
        job=self.ai.history('group-a','a')['jobs'][0]
        self.assertEqual(len(job['calls']),200);self.assertTrue(job['calls_has_more'])
        self.assertAlmostEqual(job['usage']['cost_totals']['CNY'],201*10/1000000)

    def test_official_time_bands_and_frozen_request_start(self):
        from datetime import datetime
        from local_assistant.ai_accounting import price_at
        price={**PRICE,'input_price':9,'output_price':27,'cached_input_price':0.9,'time_schedule':'beijing_08_22','off_peak':{'input_price':4.5,'output_price':13.5,'cached_input_price':0.45}}
        for hour,expected in ((7,4.5),(8,9),(21,9),(22,4.5)):
            rated=price_at(price,datetime.fromisoformat(f'2026-10-01T{hour:02}:00:00+08:00'))
            self.assertEqual(rated['input_price'],expected)
        entry=self.ai.ledger.reserve_call({**MODEL,'pricing':price},'test_vision',1000,1000)
        self.assertAlmostEqual(entry['estimated_cost'],0.036)
        self.ai.ledger.settle_call(entry['attempt'],{'input_tokens':1000,'output_tokens':1000,'request_started_at':'2026-10-01T23:00:00+08:00'})
        row=self.ai.ledger.list()['items'][0]
        self.assertAlmostEqual(row['cost'],0.018);self.assertEqual(row['pricing']['time_band'],'闲时')

    def test_every_watch_target_and_no_messages_coverage(self):
        self.ai.save_group('group-a','a',{'watch_people':['100001,200002; 300003\n100001']})
        with self.app.storage.connect() as conn:
            self.add_message(conn,'second','group-a','第二位关注人发布新任务',130)
            conn.execute("UPDATE messages SET sender_qq='200002',sender_key='200002' WHERE id='second'")
        prepared=self.prepare('watch');targets=[]
        while True:
            request=self.ai.next_chunk(prepared['job_id'])
            if request['done']:break
            material=json.loads(request['user']);target=material['request']['watch_target'];targets.append(target)
            self.assertTrue(all(target in (message['sender_qq'],message['sender_key']) for message in material['messages']))
            self.ai.commit_chunk(prepared['job_id'],request['attempt'],self.output(request,target),{'input_tokens':10,'output_tokens':20})
        self.ai.finish(prepared['job_id'])
        history=self.ai.history('group-a','a',feature='watch')
        self.assertEqual(targets,['100001','200002'])
        self.assertEqual({item['subject'] for item in history['items']},{'100001','200002'})
        self.assertEqual([p['status'] for p in history['report']['coverage']['watch_people']],['completed','completed','no_messages'])
        with self.app.storage.connect() as conn:
            remembered={row[0] for row in conn.execute("SELECT subject FROM ai_memories WHERE conversation_id='group-a' AND kind='person'")}
        self.assertEqual(remembered,{'100001','200002'})

    def test_official_snapshot_cache_discount_and_currency(self):
        model={**MODEL,'pricing':PRICE}
        entry=self.ai.ledger.reserve_call(model,'test_vision',input_tokens=2000,output_tokens=1000)
        self.ai.ledger.settle_call(entry['attempt'],{'input_tokens':1000,'output_tokens':100,'cached_tokens':800})
        record=self.ai.ledger.list()['items'][0]
        self.assertAlmostEqual(record['cost'],(200*2+800*0.4+100*8)/1000000)
        self.assertEqual(record['pricing']['verified_at'],'2026-10-01')
        self.assertEqual(record['input_tokens'],1000);self.assertEqual(record['cached_tokens'],800)
        other={**MODEL,'pricing':{**PRICE,'currency':'USD'}}
        entry=self.ai.ledger.reserve_call(other,'test_vision',input_tokens=1000,output_tokens=100)
        self.ai.ledger.settle_call(entry['attempt'],{'input_tokens':1000,'output_tokens':100})
        self.assertEqual(set(self.ai.budget()['cost_totals']),{'CNY','USD'})

    def test_duration_billing_does_not_fabricate_tokens(self):
        model={**MODEL,'pricing':{'basis':'official','unit':'second','currency':'CNY','second_price':0.00022}}
        entry=self.ai.ledger.reserve_call(model,'test_speech',seconds=10)
        self.ai.ledger.settle_call(entry['attempt'],{'seconds':3})
        record=self.ai.ledger.list()['items'][0]
        self.assertIsNone(record['input_tokens']);self.assertIsNone(record['output_tokens'])
        self.assertAlmostEqual(record['cost'],0.00066)

    def test_unknown_price_failed_attempt_cache_and_atomic_budget(self):
        entry=self.ai.ledger.reserve_call(MODEL,'test_vision')
        self.ai.ledger.settle_call(entry['attempt'],state='failed')
        record=self.ai.ledger.list()['items'][0]
        self.assertEqual(record['status'],'unknown');self.assertEqual(record['state'],'failed');self.assertIsNone(record['cost'])
        self.ai.ledger.reuse(MODEL,'','cached')
        cached=self.ai.ledger.list()['items'][0]
        self.assertEqual(cached['cost'],0);self.assertEqual(cached['charged'],0)
        self.ai.save_budget({'daily_tokens':2000})
        from local_assistant.errors import CoreError
        with self.assertRaises(CoreError):self.ai.ledger.reserve_call(MODEL,'test_vision')

if __name__=='__main__':unittest.main()
