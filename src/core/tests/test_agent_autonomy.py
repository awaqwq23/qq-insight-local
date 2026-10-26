import json,unittest
from datetime import datetime,timezone,timedelta
import test_ai as fixtures
from local_assistant.errors import CoreError


QUESTION='给我提取今天我请别人提问后，私聊中对方的问题和我的回答，原封不动做成md文件'


class AgentAutonomyTest(unittest.TestCase):
    add_message=fixtures.AITest.add_message
    def setUp(self):
        fixtures.AITest.setUp(self)
        self.app.chat_memory.save_self('a',{'qq':'999001','name':'合成自己'})
        local=datetime.now(timezone(timedelta(hours=8)));midnight=int(local.replace(hour=0,minute=0,second=0,microsecond=0).timestamp())
        base=max(midnight,int(local.timestamp())-120)
        self.originals={}
        with self.app.storage.connect() as conn:
            for i in range(170):conn.execute("INSERT INTO conversations(id,kind,title,platform,account_id) VALUES(?,'c2c','合成历史联系人','qq','a')",(f'inactive-{i}',))
            for index,cid in enumerate(('qa-a','qa-b','noise')):
                conn.execute("INSERT INTO conversations(id,kind,title,platform,account_id) VALUES(?,'c2c',?,'qq','a')",(cid,'合成问答'+cid))
                entries=[('outgoing','999001','合成自己','今天请提一个问题。'),('incoming',f'10010{index}','合成对方','你最想读的合成书是什么？'),
                         ('outgoing','999001','合成自己','答：合成故事集。\n保留两个空格  🙂\n```原文围栏```'),('outgoing','999001','合成自己','这是分开发出的补充回答。')]
                if cid=='noise':entries=[('incoming','100109','合成路人','没有邀请的普通问候。')]
                for i,(direction,qq,name,text) in enumerate(entries):
                    key=f'{cid}-{i}';self.originals[key]=text
                    conn.execute("INSERT INTO messages(id,conversation_id,source_key,sent_at,direction,sender_key,sender_qq,sender_name,text,content_kind,parse_status,platform,account_id) VALUES(?,?,?,?,?,?,?,?,?,'文本','partial','qq','a')",(key,cid,key,base+index*10+i,direction,'u_'+qq,qq,name,text))
        self.agent=self.app.workspace_agent

    def start(self,question=QUESTION,**kwargs):return self.agent.begin('a',question,**kwargs)
    def search(self,run,**kwargs):
        scope=run['source_scope'] or run['time_boundaries']
        return self.agent.tool(run['run_id'],'a','search_messages',{'kind':'c2c','start':scope.get('start',scope.get('today_start')),'end':scope.get('end',scope.get('now')),**kwargs})

    def test_continue_and_today_all_keep_original_user_task_not_assistant_questions(self):
        first=self.start();self.assertEqual(first['source_scope']['conversations'],3);self.assertEqual(first['source_scope']['messages'],9)
        self.assertEqual(first['allowed_kinds'],['c2c'])
        current=first
        for question in ('继续','今天所有的','今天所有私聊消息的这个问答类内容'):
            # Reproduce older saved clarification answers without allowing the new finish guard to accept them.
            with self.app.storage.connect() as conn:conn.execute("UPDATE workspace_runs SET status='completed',answer_json=? WHERE id=?",(json.dumps({'answer':'请确认一人还是所有私聊。'}),current['run_id']))
            current=self.start(question,session_id=first['session_id'])
            self.assertEqual(current['task']['request'],QUESTION);self.assertTrue(current['task']['verbatim']);self.assertTrue(current['task']['markdown'])
            self.assertTrue(current['task']['continuation']);self.assertEqual(current['source_scope']['conversations'],3)
        self.agent.finish(current['run_id'],'a',error='合成中止')
        group=self.start('总结今天所有群聊',session_id=first['session_id'])
        self.assertEqual(group['allowed_kinds'],['group']);self.assertEqual(group['previous_turns'],[])
        self.assertFalse(group['task']['verbatim']);self.assertIsNone(group['source_scope'])

    def test_failed_task_continue_keeps_scope_and_fresh_chat_does_not(self):
        first=self.start();self.agent.finish(first['run_id'],'a',error='合成服务中断')
        follow=self.start('继续',session_id=first['session_id'])
        self.assertEqual(follow['allowed_kinds'],['c2c']);self.assertEqual(follow['task']['request'],QUESTION)
        fresh=self.start('继续');self.assertEqual(fresh['allowed_kinds'],['group']);self.assertIsNone(fresh['source_scope'])

    def test_bulk_time_search_reads_active_private_only_and_pages_without_opening_170_contacts(self):
        run=self.start();first=self.search(run,limit=4)
        self.assertTrue(first['short_context']);self.assertEqual(first['reading_mode'],'original');self.assertEqual(first['reused_messages'],0)
        seen=[r[0] for r in first['messages']];offset=first['next_offset']
        while first['has_more']:
            first=self.search(run,limit=4,offset=offset);seen.extend(r[0] for r in first['messages']);offset=first['next_offset']
        self.assertEqual(len(set(seen)),9)
        all_text=json.dumps(first,ensure_ascii=False);self.assertNotIn('账号B内容',all_text)
        with self.assertRaises(CoreError):self.agent.tool(run['run_id'],'a','search_messages',{'kind':'group'})
        own=self.search(run,direction='outgoing',queries=['提一个问题','补充回答'])
        self.assertEqual(own['selected_messages'],4)
        self.assertEqual(self.search(run,queries=['_%'])['selected_messages'],0)

    def test_finish_rejects_partial_scope_and_requires_source_backed_file(self):
        run=self.start();scope=run['source_scope']
        raw=self.agent.tool(run['run_id'],'a','read_context',{'conversation_ids':['qa-a'],'start':scope['start'],'end':scope['end']})
        with self.assertRaises(CoreError) as error:self.agent.finish(run['run_id'],'a',{'answer':'请确认是否继续其他私聊。','evidence_ids':[raw['messages'][0][0]]})
        self.assertEqual(error.exception.code,'AGENT_TASK_INCOMPLETE')
        raw=self.search(run);refs=[r[0] for r in raw['messages']]
        with self.assertRaises(CoreError):self.agent.tool(run['run_id'],'a','write_markdown',{'title':'模型重写的摘要','content':'摘要不能冒充原话。','evidence_ids':refs[:1]})
        with self.assertRaises(CoreError) as error:self.agent.finish(run['run_id'],'a',{'answer':'文字说明已完成。','evidence_ids':refs[:1]})
        self.assertEqual(error.exception.code,'AGENT_TASK_INCOMPLETE')
        with self.app.storage.connect() as conn:context=json.loads(conn.execute('SELECT context_json FROM workspace_runs WHERE id=?',(run['run_id'],)).fetchone()[0])
        sections=[{'heading':'合成问答 '+cid,'references':[ref for ref,key in context['refs'].items() if key.startswith(cid)]} for cid in ('qa-a','qa-b')]
        artifact=self.agent.tool(run['run_id'],'a','export_messages',{'title':'合成问答原文','sections':sections})
        self.assertEqual(artifact['messages'],8);self.assertTrue(artifact['verbatim'])
        path=self.agent.materialize('a',artifact['artifact_id'])['path']
        from pathlib import Path
        content=Path(path).read_text(encoding='utf-8')
        for key,text in self.originals.items():
            if key.startswith('qa-'):self.assertIn(text,content)
        self.assertNotIn(self.originals['noise-0'],content);self.assertIn('````',content)
        self.assertEqual(self.agent.finish(run['run_id'],'a',{'answer':'已生成两位合成对象的原文问答。','evidence_ids':refs[:2]})['status'],'completed')

    def test_export_rechecks_original_hash(self):
        run=self.start();raw=self.search(run);ref=raw['messages'][0][0]
        with self.app.storage.connect() as conn:conn.execute("UPDATE messages SET text='合成来源已变化' WHERE id='qa-a-0'")
        with self.assertRaises(CoreError) as error:self.agent.tool(run['run_id'],'a','export_messages',{'title':'不能导出旧版本','sections':[{'heading':'合成','references':[ref]}]})
        self.assertEqual(error.exception.code,'AI_SOURCE_CHANGED')

    def test_short_context_ignores_old_lossy_summary(self):
        run=self.start();raw=self.search(run);refs=[r[0] for r in raw['messages']]
        self.agent.context_commit(run['run_id'],'a',refs,{'summary':'有损旧摘要','items':[{'title':'合成记录','body':'旧摘要省略了原话。','evidence_ids':refs[:1]}],
            'group_memory':[{'conversation_id':cid,'body':'合成旧摘要','evidence_ids':[next(row[0] for row in raw['messages'] if raw['groups'][row[5]['group']]==cid)]} for cid in ('qa-a','qa-b','noise')]})
        again=self.search(run);self.assertEqual(again['reused_messages'],0);self.assertEqual(again['raw_messages'],9)
        self.assertIn('保留两个空格  🙂',json.dumps(again,ensure_ascii=False))

    def test_short_unread_pages_exclude_this_run_without_claiming_success_early(self):
        run=self.start('总结本私聊',conversation_id='qa-a')
        params={'conversation_ids':['qa-a'],'unread_only':True,'limit':2}
        first=self.agent.tool(run['run_id'],'a','read_context',params)
        second=self.agent.tool(run['run_id'],'a','read_context',{**params,'offset':first['next_offset']})
        self.assertTrue(first['short_context']);self.assertEqual(first['next_offset'],0)
        self.assertTrue(set(r[0] for r in first['messages']).isdisjoint(r[0] for r in second['messages']))
        self.assertEqual(self.app.chat_memory.coverage('qa-a','a')['read'],0)
        self.agent.finish(run['run_id'],'a',{'answer':'合成原文已读取，无额外压缩调用。','evidence_ids':[first['messages'][0][0]]})
        self.assertEqual(self.app.chat_memory.coverage('qa-a','a')['read'],4)

    def test_task_metadata_cannot_replace_visible_user_requests(self):
        first=self.start('你好，介绍一下本地聊天工具')
        with self.app.storage.connect() as conn:
            row=conn.execute('SELECT context_json FROM workspace_runs WHERE id=?',(first['run_id'],)).fetchone();context=json.loads(row[0])
            context['task']={'request':QUESTION,'refinements':['隐藏的非用户请求']}
            conn.execute("UPDATE workspace_runs SET status='completed',answer_json='{}',context_json=? WHERE id=?",(json.dumps(context),first['run_id']))
        follow=self.start('继续',session_id=first['session_id'])
        self.assertEqual(follow['task']['request'],'你好，介绍一下本地聊天工具');self.assertFalse(follow['task']['verbatim']);self.assertIsNone(follow['source_scope'])

    def test_explicit_previous_date_bulk_scope_uses_native_timestamps(self):
        yesterday=(datetime.now(timezone(timedelta(hours=8)))-timedelta(days=1)).strftime('%Y-%m-%d')
        with self.app.storage.connect() as conn:conn.execute("UPDATE messages SET sent_at=sent_at-86400 WHERE id LIKE 'qa-%' OR id LIKE 'noise-%'")
        run=self.start(f'提取{yesterday}全部私聊中的邀请问答，原封不动做成md文件')
        self.assertEqual(run['source_scope']['messages'],9)
        self.assertEqual(run['time_boundaries']['requested']['date'],yesterday)
        self.assertEqual(run['source_scope']['end']-run['source_scope']['start'],86400)
        self.assertEqual(self.search(run)['selected_messages'],9)

    def test_empty_range_still_requires_requested_file(self):
        run=self.start('请把1999-01-01全部私聊问答原封不动做成md文件')
        self.assertEqual(run['source_scope']['messages'],0)
        with self.assertRaises(CoreError) as raised:self.agent.finish(run['run_id'],'a',{'answer':'没有记录','evidence_ids':[]})
        self.assertEqual(raised.exception.code,'AGENT_TASK_INCOMPLETE')
        self.agent.tool(run['run_id'],'a','export_messages',{'title':'空范围说明','sections':[]})
        self.assertEqual(self.agent.finish(run['run_id'],'a',{'answer':'已生成空范围说明','evidence_ids':[]})['status'],'completed')

    def test_missing_evidence_returns_real_available_aliases(self):
        run=self.start('总结本私聊',conversation_id='qa-a')
        read=self.agent.tool(run['run_id'],'a','read_context',{'conversation_ids':['qa-a']})
        with self.assertRaises(CoreError) as raised:self.agent.finish(run['run_id'],'a',{'answer':'合成总结','evidence_ids':[]})
        self.assertEqual(raised.exception.code,'AI_EVIDENCE_INVALID')
        self.assertEqual(set(raised.exception.data['available_references']),{r[0] for r in read['messages']})
