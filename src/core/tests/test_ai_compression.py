import json
import unittest
import test_ai as fixtures
from local_assistant.errors import CoreError
from local_assistant.ai_prompts import FEATURES

class CompressionTest(unittest.TestCase):
    setUp=fixtures.AITest.setUp
    add_message=fixtures.AITest.add_message
    prepare=fixtures.AITest.prepare
    output=fixtures.AITest.output
    complete=fixtures.AITest.complete

    def test_all_seven_features_aliases_and_custom_length(self):
        self.ai.save_group('group-a','a',{'watch_people':['100001']})
        for feature in (key for key in FEATURES if key!='style'):
            job=self.prepare(feature,compression='balanced',output_chars=1234)
            request=self.ai.next_chunk(job['job_id']);material=json.loads(request['user'])
            self.assertEqual(material['request']['output_chars'],1234)
            self.assertIn('1234',request['system']);self.assertNotIn('body不超过200字',request['system'])
            self.assertEqual(material['compression']['mode'],'balanced')
            first=fixtures.wire_message(material,material['messages'][0])
            self.assertTrue(first['id'].startswith('m'))
            self.assertEqual(first['time'],'1970-01-01T08:01+08:00')
            self.assertEqual(material['people']['p0']['qq'],'100001')
            self.ai.commit_chunk(job['job_id'],request['attempt'],self.output(request),{'input_tokens':20,'output_tokens':10})
            self.ai.finish(job['job_id']);history=self.ai.history('group-a','a',feature=feature,job_id=job['job_id'])
            item=history['report']['items'][0]
            self.assertIn(item['evidence_ids'][0],('m0','m1'))
            self.assertIn('有损',item['uncertainty']);self.assertIn('有损',history['report']['summary'])
            with self.assertRaises(CoreError):self.ai.history('group-a','b',job_id=job['job_id'])

    def test_3000_messages_reduce_material_and_chunks(self):
        with self.app.storage.connect() as conn:
            for i in range(3000):
                self.add_message(conn,f'synthetic-large-{i}-long-source-identifier','group-a','收到',200+i)
                conn.execute('UPDATE messages SET sender_key=?,sender_qq=? WHERE id=?',(f'synthetic-{i%8}',str(100010+i%8),f'synthetic-large-{i}-long-source-identifier'))
        full=self.prepare('summary',limit=10000,compression='off',output_chars=800)
        self.ai.fail(full['job_id'],known_not_sent=True)
        compact=self.prepare('summary',limit=10000,compression='strong',output_chars=800)
        stats=compact['coverage']['compression']
        self.assertEqual(compact['coverage']['selected'],3002)
        self.assertGreater(stats['folded'],2900)
        self.assertLess(stats['compressed_bytes'],stats['original_bytes']*.1)
        self.assertLess(compact['coverage']['chunks'],full['coverage']['chunks'])
        request=self.ai.next_chunk(compact['job_id'])
        self.assertLess(len(json.loads(request['user'])['messages']),20)
        print(f"Synthetic 3002 messages: full chunks={full['coverage']['chunks']}, compressed chunks={compact['coverage']['chunks']}; material bytes={stats['original_bytes']}->{stats['compressed_bytes']} (not billed tokens)")

    def test_long_text_keeps_end_corrections_and_picture_reference(self):
        with self.app.storage.connect() as conn:
            conn.execute('UPDATE messages SET text=?,media_json=? WHERE id=?',('提交日期：周五。'+'合成长正文。'*300+'取消周五，改为下周一提交。',json.dumps([{'type':'image','filename':'synthetic.png'}]),'m0'))
        job=self.prepare('collection',compression='strong',output_chars=700)
        request=self.ai.next_chunk(job['job_id']);material=json.loads(request['user']);first=fixtures.wire_message(material,material['messages'][0])
        self.assertIn('下周一',first['text']);self.assertTrue(first['truncated']);self.assertEqual(first['media'][0]['index'],0)
        self.assertEqual(material['messages'][0][5]['images'],[0]);self.assertNotIn('synthetic.png',request['user'])
        payload=self.output(request);payload['items'][0]['media_index']=0
        self.ai.commit_chunk(job['job_id'],request['attempt'],payload,{'input_tokens':20,'output_tokens':10});self.ai.finish(job['job_id'])
        self.assertEqual(self.ai.history('group-a','a',feature='collection')['items'][0]['evidence_ids'],['m0'])

    def test_2000_distinct_messages_reduce_without_folding_events(self):
        with self.app.storage.connect() as conn:
            for i in range(2000):self.add_message(conn,f'synthetic-distinct-{i}','group-a',f'事项{i}：'+'合成讨论材料。'*45+f'截止周五，负责人{i%8}。',200+i)
        full=self.prepare('work',limit=10000,compression='off');self.ai.fail(full['job_id'],known_not_sent=True)
        compressed=self.prepare('work',limit=10000,compression='strong');stats=compressed['coverage']['compression']
        self.assertEqual(stats['folded'],0);self.assertEqual(stats['sent_messages'],2002)
        self.assertGreaterEqual(stats['shortened'],2000)
        self.assertLess(stats['compressed_bytes'],stats['original_bytes']*.6)
        self.assertLess(compressed['coverage']['chunks'],full['coverage']['chunks'])
        print(f"Synthetic 2002 distinct events: full chunks={full['coverage']['chunks']}, compressed chunks={compressed['coverage']['chunks']}; material bytes={stats['original_bytes']}->{stats['compressed_bytes']} (not billed tokens)")

    def test_unprovided_compressed_alias_rejected_and_charged(self):
        job=self.prepare('summary',compression='strong',output_chars=400)
        request=self.ai.next_chunk(job['job_id']);payload=self.output(request);payload['items'][0]['evidence_ids']=['m999']
        with self.assertRaises(CoreError) as raised:self.ai.commit_chunk(job['job_id'],request['attempt'],payload,{'input_tokens':20,'output_tokens':10})
        self.assertEqual(raised.exception.code,'AI_EVIDENCE_INVALID');self.assertEqual(self.ai.budget()['daily_used'],30)

    def test_off_preserves_long_text_and_large_output(self):
        with self.app.storage.connect() as conn:conn.execute('UPDATE messages SET text=? WHERE id=?',('合成未压缩正文'*400,'m0'))
        job=self.prepare('summary',compression='off',output_chars=6000)
        request=self.ai.next_chunk(job['job_id']);material=json.loads(request['user'])
        self.assertEqual(material['compression']['mode'],'off');self.assertEqual(fixtures.wire_message(material,material['messages'][0])['text'],'合成未压缩正文'*400)
        payload=self.output(request);payload['summary']='合成摘要'*1300;payload['items'][0]['body']='合成正文'*1300
        self.ai.commit_chunk(job['job_id'],request['attempt'],payload,{'input_tokens':20,'output_tokens':10});self.ai.finish(job['job_id'])
        history=self.ai.history('group-a','a',feature='summary',job_id=job['job_id'])
        self.assertEqual(len(history['report']['summary']),5200);self.assertEqual(len(history['items'][0]['body']),5200)

    def test_options_defaults_cache_and_validation(self):
        self.ai.save_group('group-a','a',{'compression':'balanced','output_chars':777})
        job=self.prepare();request=self.ai.next_chunk(job['job_id'])
        self.assertEqual(json.loads(request['user'])['request']['output_chars'],777)
        self.ai.fail(job['job_id'],attempt=request['attempt'],known_not_sent=True)
        for options in [{'compression':'bad'},{'output_chars':0},{'output_chars':20001},{'output_chars':True},{'output_chars':1.5}]:
            with self.assertRaises(CoreError):self.prepare(**options)
        self.ai.save_group('group-a','a',{'compression':'off','output_chars':500})
        first=self.prepare('summary',compression='off',output_chars=100);self.complete(first)
        self.assertEqual(self.prepare('summary',compression='off',output_chars=100)['status'],'cached')
        self.assertEqual(self.prepare('summary',compression='balanced',output_chars=100)['status'],'queued')
