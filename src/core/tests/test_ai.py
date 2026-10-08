import json
from pathlib import Path
import tempfile
import unittest

from local_assistant.service import AssistantService, CoreError
from local_assistant.ai_prompts import FEATURES


MODEL={'id':'synthetic','provider':'openai-compatible','model':'synthetic-model','endpoint_hash':'local'}


class AITest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.app=AssistantService(self.root/'app');self.ai=self.app.ai
        with self.app.storage.connect() as conn:
            for group,account,kind in [('group-a','a','group'),('group-b','a','group'),('group-c','b','group'),('private','a','c2c')]:
                conn.execute('INSERT INTO conversations(id,kind,title,platform,account_id) VALUES(?,?,?,\'qq\',?)',(group,kind,group,account))
            for index,group in enumerate(('group-a','group-a','group-b','group-c')):
                self.add_message(conn,f'm{index}',group,('请组长明天下午交作业','组长收到','私有群B内容','账号B内容')[index],100+index)

    def add_message(self,conn,key,group,text,timestamp):
        account=conn.execute('SELECT account_id FROM conversations WHERE id=?',(group,)).fetchone()[0]
        conn.execute("INSERT INTO messages(id,conversation_id,source_key,sent_at,direction,sender_key,sender_qq,sender_name,text,content_kind,parse_status,platform,account_id) VALUES(?,?,?,?,'incoming','synthetic','100001','合成人',?,'文本','partial','qq',?)",(key,group,key,timestamp,text,account))

    def prepare(self,feature='work',**options):
        return self.ai.prepare('group-a','a',feature,MODEL,options or {'mode':'recent','limit':100})

    def output(self,request,title='合成任务',update_id=''):
        data=json.loads(request['user']);message=data['messages'][0]
        if data['feature']=='identity':title=data['group_settings']['role'] or '第一组组长'
        return {'summary':'合成摘要','items':[{'title':title,'body':'需要核实的合成工作','evidence_ids':[message['id']],'category':'我的角色' if data['feature']=='identity' else '待核实','update_id':update_id}]}

    def complete(self,prepared,title='合成任务',update_id=''):
        while True:
            request=self.ai.next_chunk(prepared['job_id'])
            if request['done']:break
            self.ai.commit_chunk(prepared['job_id'],request['attempt'],self.output(request,title,update_id),{'input_tokens':100,'output_tokens':50})
        return self.ai.finish(prepared['job_id'])

    def test_all_features_prompts_scope_cache_and_invocation_history(self):
        self.ai.save_group('group-a','a',{'category':'项目','role':'第一组组长','watch_people':['100001'],'watch_keywords':['作业']})
        for feature in FEATURES:
            prepared=self.prepare(feature);request=self.ai.next_chunk(prepared['job_id'])
            material=json.loads(request['user'])
            self.assertEqual(material['group_settings']['effective_role'],'第一组组长')
            self.assertEqual({item['id'] for item in material['messages']},{'m0','m1'})
            self.assertNotIn('私有群B内容',request['user'])
            self.ai.commit_chunk(prepared['job_id'],request['attempt'],self.output(request),{'input_tokens':10,'output_tokens':20})
            self.ai.finish(prepared['job_id'])
            self.assertEqual(self.prepare(feature)['status'],'cached')
        history=self.ai.history('group-a','a',job_page_size=50);self.assertEqual(len(history['jobs']),len(FEATURES)*2)
        self.assertEqual({job['status'] for job in history['jobs']},{'completed','cached'})
        self.assertEqual(self.ai.history('group-b','a')['items'],[])
        with self.assertRaises(CoreError):self.ai.history('group-a','b')
        with self.assertRaises(CoreError):self.ai.prepare('private','a','work',MODEL)
        with self.assertRaises(CoreError):self.app.work_digest(account_id='a')

    def test_invalid_evidence_and_json_settle_no_history(self):
        for payload in ('not-json',{'summary':'bad','items':[{'title':'bad','body':'bad','evidence_ids':['m2']}]}, {'summary':'bad','items':[{'title':'bad','body':'bad','evidence_ids':['m0'],'update_id':'unknown'}]}):
            prepared=self.prepare();request=self.ai.next_chunk(prepared['job_id'])
            with self.assertRaises(CoreError):self.ai.commit_chunk(prepared['job_id'],request['attempt'],payload,{'input_tokens':100,'output_tokens':50})
            self.assertEqual(self.ai.history('group-a','a')['items'],[])
        self.assertEqual(self.ai.budget()['daily_used'],450)

    def test_budget_is_reserved_before_requests_and_unknown_not_free(self):
        self.ai.save_budget({'daily_tokens':1000})
        prepared=self.prepare()
        with self.assertRaises(CoreError) as raised:self.ai.next_chunk(prepared['job_id'])
        self.assertEqual(raised.exception.code,'BUDGET_EXCEEDED')
        self.assertEqual(self.ai.budget()['daily_used'],0)
        self.ai.save_budget({'daily_tokens':100000})
        request=self.ai.next_chunk(prepared['job_id']);reserved=self.ai.budget()['daily_used']
        self.assertGreater(reserved,0)
        with self.assertRaises(CoreError):self.ai.next_chunk(prepared['job_id'])
        self.ai.fail(prepared['job_id'],attempt=request['attempt'],cancelled=True)
        self.assertEqual(self.ai.budget()['daily_used'],reserved)
        self.assertEqual(self.ai.budget()['uncertain_requests'],1)
        self.assertEqual(self.ai.history('group-a','a')['jobs'][0]['status'],'cancelled')

    def test_incremental_late_revision_and_separate_feature(self):
        self.complete(self.prepare(mode='incremental'))
        self.assertEqual(self.prepare(mode='incremental')['status'],'empty')
        self.assertEqual(self.prepare('summary',mode='incremental')['status'],'queued')
        with self.app.storage.connect() as conn:self.add_message(conn,'late','group-a','晚到的旧消息',10)
        prepared=self.prepare(mode='incremental');request=self.ai.next_chunk(prepared['job_id'])
        self.assertEqual([row['id'] for row in json.loads(request['user'])['messages']],['late'])
        self.ai.commit_chunk(prepared['job_id'],request['attempt'],self.output(request),{'input_tokens':1,'output_tokens':1});self.ai.finish(prepared['job_id'])
        with self.app.storage.connect() as conn:conn.execute("UPDATE messages SET text='改为下周一交' WHERE id='m0'")
        request=self.ai.next_chunk(self.prepare(mode='incremental')['job_id'])
        self.assertEqual([row['id'] for row in json.loads(request['user'])['messages']],['m0'])

    def test_merge_versions_explicit_update_and_user_lock(self):
        self.complete(self.prepare());item=self.ai.history('group-a','a')['items'][0]
        with self.app.storage.connect() as conn:self.add_message(conn,'change','group-a','刚才作业改为周五提交',110)
        self.complete(self.prepare(mode='incremental'),title='更新截止时间',update_id=item['id'])
        history=self.ai.history('group-a','a');self.assertEqual(len(history['items']),1);self.assertEqual(len(history['jobs']),2)
        self.assertEqual(history['items'][0]['title'],'更新截止时间')
        self.ai.update_item(item['id'],'group-a','a','completed')
        self.ai.update_item(item['id'],'group-a','a','correct',correction='用户确认的内容')
        with self.app.storage.connect() as conn:self.add_message(conn,'change2','group-a','再次补充任务',120)
        self.complete(self.prepare(mode='incremental'),title='不能覆盖',update_id=item['id'])
        item=self.ai.history('group-a','a')['items'][0]
        self.assertEqual(item['title'],'更新截止时间');self.assertEqual(item['user_status'],'completed');self.assertEqual(item['correction'],'用户确认的内容')

    def test_confirmed_result_is_not_overwritten(self):
        self.complete(self.prepare('profile'));item=self.ai.history('group-a','a')['items'][0]
        self.ai.update_item(item['id'],'group-a','a','confirmed')
        with self.app.storage.connect() as conn:self.add_message(conn,'new','group-a','新的推测不能覆盖已确认内容',120)
        self.complete(self.prepare('profile',mode='incremental'),title='不应覆盖',update_id=item['id'])
        current=self.ai.history('group-a','a')['items'][0]
        self.assertEqual(current['title'],item['title']);self.assertEqual(current['user_status'],'confirmed')

    def test_partial_resume_keeps_successful_chunks_and_restart(self):
        with self.app.storage.connect() as conn:
            for i in range(6):self.add_message(conn,f'long{i}','group-a','合成材料'*500,120+i)
        self.ai.save_budget({'chunk_chars':2000,'per_run_tokens':1000000,'daily_tokens':1000000})
        prepared=self.prepare();request=self.ai.next_chunk(prepared['job_id']);first=request['index']
        self.ai.commit_chunk(prepared['job_id'],request['attempt'],self.output(request),{'input_tokens':10,'output_tokens':20})
        second=self.ai.next_chunk(prepared['job_id'])
        restarted=AssistantService(self.root/'app').ai
        self.assertEqual(restarted.history('group-a','a')['jobs'][0]['status'],'interrupted')
        restarted.resume(prepared['job_id'],'a','group-a',MODEL)
        retry=restarted.next_chunk(prepared['job_id'])
        self.assertEqual(retry['index'],second['index']);self.assertNotEqual(retry['index'],first)
        self.assertEqual(restarted.budget()['uncertain_requests'],1)

    def test_cross_chunk_explicit_update_merges_one_item(self):
        with self.app.storage.connect() as conn:
            self.add_message(conn,'long','group-a','合成补充材料'*500,120)
        self.ai.save_budget({'chunk_chars':2000})
        prepared=self.prepare();request=self.ai.next_chunk(prepared['job_id'])
        self.ai.commit_chunk(prepared['job_id'],request['attempt'],self.output(request),{'input_tokens':10,'output_tokens':20})
        request=self.ai.next_chunk(prepared['job_id'])
        previous=json.loads(request['user'])['previous_items']
        self.assertTrue(previous[-1]['id'].startswith('pending:'))
        self.ai.commit_chunk(prepared['job_id'],request['attempt'],self.output(request,'截止时间已更新',previous[-1]['id']),{'input_tokens':10,'output_tokens':20})
        self.ai.finish(prepared['job_id'])
        items=self.ai.history('group-a','a')['items']
        self.assertEqual(len(items),1);self.assertEqual(items[0]['title'],'截止时间已更新')
        self.assertEqual(set(items[0]['evidence_ids']),{'m0','long'})

    def test_evidence_changed_during_request_not_committed(self):
        prepared=self.prepare();request=self.ai.next_chunk(prepared['job_id'])
        self.ai.commit_chunk(prepared['job_id'],request['attempt'],self.output(request),{'input_tokens':10,'output_tokens':20})
        with self.app.storage.connect() as conn:conn.execute("UPDATE messages SET text='修改后的内容' WHERE id='m0'")
        with self.assertRaises(CoreError) as raised:self.ai.finish(prepared['job_id'])
        self.assertEqual(raised.exception.code,'AI_SOURCE_CHANGED');self.assertEqual(self.ai.history('group-a','a')['items'],[])

    def test_history_local_backup_restore_and_schedule_stays_off(self):
        self.ai.save_group('group-a','a',{'schedule_minutes':5,'auto_favorite':True})
        self.complete(self.prepare())
        backup=self.root/'backup.db';self.app.export_archive(str(backup))
        restored=AssistantService(self.root/'restore');restored.manual_import(str(backup),'app_db')
        self.assertEqual(len(restored.ai.history('group-a','a')['items']),1)
        self.assertGreater(restored.ai.history('group-a','a')['memory']['items'],0)
        self.assertEqual(restored.ai.get_group('group-a','a')['schedule_minutes'],0)
        self.assertFalse(restored.ai.get_group('group-a','a')['auto_favorite'])
        self.assertEqual(restored.ai.budget()['daily_used'],150)

    def test_backup_rejects_cross_group_evidence_atomically(self):
        import sqlite3
        self.complete(self.prepare())
        backup=self.root/'bad.db';self.app.export_archive(str(backup))
        with sqlite3.connect(backup) as conn:
            row=conn.execute('SELECT id,data_json FROM ai_items').fetchone()
            value=json.loads(row[1]);value['evidence_ids']=['m2']
            conn.execute('UPDATE ai_items SET data_json=? WHERE id=?',(json.dumps(value),row[0]))
        conn.close()
        restored=AssistantService(self.root/'restore-bad')
        with self.assertRaises(CoreError):restored.manual_import(str(backup),'app_db')
        with restored.storage.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM messages').fetchone()[0],0)

    def test_schedule_disabled_and_confirmed_memory(self):
        self.ai.save_group('group-a','a',{'schedule_minutes':5,'schedule_feature':'profile'})
        with self.app.storage.connect() as conn:conn.execute('UPDATE ai_schedules SET next_at=0')
        self.assertEqual(len(self.ai.schedules()['items']),1)
        self.assertEqual(self.ai.schedules()['items'],[])
        self.complete(self.prepare('profile'))
        item=self.ai.history('group-a','a')['items'][0]
        self.ai.update_item(item['id'],'group-a','a','confirmed')
        request=self.ai.next_chunk(self.prepare('work')['job_id'])
        self.assertTrue(json.loads(request['user'])['request']['confirmed_memory'])
        self.ai.update_item(item['id'],'group-a','a','forget')
        self.assertFalse(self.ai.get_group('group-a','a')['remember'])
        with self.app.storage.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM ai_jobs').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM ai_chunks').fetchone()[0],0)
            self.assertGreater(conn.execute('SELECT count(*) FROM ai_usage').fetchone()[0],0)
        with self.app.storage.connect() as conn:conn.execute('UPDATE ai_schedules SET next_at=0')
        self.assertEqual(self.ai.schedules()['items'],[])

    def test_group_role_inference_history_pagination_and_long_term_memory(self):
        self.app.save_profile('不应跨群继承的全局角色')
        self.assertEqual(self.ai.get_group('group-a','a')['role'],'')
        inferred=self.prepare('identity');self.complete(inferred)
        self.assertEqual(self.ai.get_group('group-a','a')['role'],'第一组组长')
        self.assertEqual(self.ai.get_group('group-b','a')['role'],'')

        self.complete(self.prepare('work'))
        summary=self.ai.next_chunk(self.prepare('summary')['job_id'])
        material=json.loads(summary['user'])
        self.assertTrue(any(item.get('feature') in ('identity','work') for item in material['long_term_memory']))

        empty=self.ai.prepare('group-b','a','work',MODEL,{'mode':'time','limit':100,'start':1000,'end':2000})
        self.assertEqual(empty['status'],'empty')
        page=self.ai.history('group-a','a',feature='work',job_page=1,job_page_size=1,item_page=1,item_page_size=1)
        self.assertEqual(len(page['jobs']),1);self.assertGreaterEqual(page['pagination']['jobs']['total'],1)
        self.assertLessEqual(len(page['items']),1);self.assertGreater(page['memory']['items'],0)


if __name__=='__main__':unittest.main()
