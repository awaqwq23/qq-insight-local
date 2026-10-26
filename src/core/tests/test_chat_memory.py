import base64,json,sqlite3,unittest
import test_ai as fixtures
from local_assistant.errors import CoreError


class ChatMemoryTest(unittest.TestCase):
    setUp=fixtures.AITest.setUp
    add_message=fixtures.AITest.add_message
    output=fixtures.AITest.output

    def start(self,cid='group-a',question='总结本会话',session_id=''):
        return self.app.workspace_agent.begin('a',question,session_id=session_id,conversation_id=cid)

    def read(self,run,cid='group-a',**args):
        return self.app.workspace_agent.tool(run['run_id'],'a','read_context',{'conversation_ids':[cid],**args})

    def finish(self,run,raw,**extra):
        refs=[row[0] for row in raw['messages']]
        if not refs:refs=[ref for summary in raw['summaries'] for ref in summary['evidence_ids']]
        return self.app.workspace_agent.finish(run['run_id'],'a',{'answer':'本会话围绕作业与提交进行协调。','evidence_ids':refs[:2],**extra})

    def test_scoped_sessions_are_persistent_and_never_expand_by_model_question(self):
        first=self.start();raw=self.read(first);self.finish(first,raw)
        again=self.start(session_id=first['session_id'],question='再分析所有群和私聊')
        self.assertEqual(again['allowed_kinds'],['group']);self.assertEqual(len(again['previous_turns']),1)
        for cid in ('group-b','private','group-c'):
            with self.assertRaises(CoreError):self.read(again,cid)
        people=self.app.workspace_agent.tool(again['run_id'],'a','conversations',{})
        self.assertEqual([c['id'] for c in people['items']],['group-a'])
        self.assertEqual(self.app.workspace_agent.list_sessions('a')['items'],[])
        self.assertEqual(self.app.workspace_agent.list_sessions('a',conversation_id='group-a')['items'][0]['id'],first['session_id'])
        with self.assertRaises(CoreError):self.start('group-b',session_id=first['session_id'])
        restarted=fixtures.AssistantService(self.app.data_dir)
        self.assertEqual(restarted.workspace_agent.get_session(first['session_id'],'a')['session']['conversation_id'],'group-a')

    def test_three_memory_categories_include_self_and_learned_agent_keeps_manual_prompt(self):
        self.app.chat_memory.save_self('a',{'qq':'100001','name':'合成自己','identity':'课程项目学生'})
        self.app.chat_memory.save_settings('group-a','a',{'prompt':'始终先列待办，不猜测事实。','self_identity':'本群组长'})
        run=self.start(question='根据群聊画像完善本群Agent');raw=self.read(run)
        ref=raw['messages'][0][0]
        self.finish(run,raw,people_memory=[{'subject':'100001','title':'本人观察','body':'经常明确提交安排。','evidence_ids':[ref]}],group_memory=[{'conversation_id':'group-a','body':'本群协调课程作业。','evaluation':'本段偏任务沟通。','evidence_ids':[ref]}])
        coverage=self.app.chat_memory.coverage('group-a','a')
        self.assertEqual((coverage['unread'],coverage['compressed'],coverage['ranges']),(0,2,[{'start':1,'end':2}]))
        self.assertTrue(self.app.chat_memory.view('group-a','a')['items'])
        people=self.app.chat_memory.view('group-a','a','people')['items']
        own=next(p for p in people if p['is_self']);self.assertTrue(own['memories']);self.assertEqual(own['qq'],'100001')
        self.assertEqual(len(self.app.chat_memory.view('group-a','a','messages')['items']),2)
        config=self.app.chat_memory.settings('group-a','a')
        self.assertIn('本群协调课程作业',config['learned']['prompt']);self.assertEqual(config['settings']['prompt'],'始终先列待办，不猜测事实。')
        self.assertEqual(config['settings']['self_identity'],'本群组长')

    def test_private_chat_reads_without_repeating_permission_and_keeps_two_identities(self):
        self.app.chat_memory.save_self('a',{'qq':'200001','uid':'u_self','identity':'全局学生身份'})
        with self.app.storage.connect() as conn:
            self.add_message(conn,'private-self','private','我明天会提交，仅限私聊背景',300)
            conn.execute("UPDATE messages SET sender_qq='200001',sender_key='u_self',direction='outgoing' WHERE id='private-self'")
            self.add_message(conn,'private-peer','private','慢慢来，仅限私聊语气',301)
        self.app.chat_memory.save_settings('private','a',{'self_identity':'本次合作的学生','peer_identity':'我的项目搭档'})
        run=self.start('private',question='帮我理一下我们最近说了什么');self.assertEqual(run['allowed_kinds'],['c2c'])
        raw=self.read(run,'private');refs=[r[0] for r in raw['messages']]
        self.finish(run,raw,people_memory=[{'subject':'200001','title':'私聊本人观察','body':'私聊独有的本人观察。','evidence_ids':[refs[0]]},{'subject':'100001','title':'对方观察','body':'在此私聊中安抚语气。','evidence_ids':[refs[1]]}])
        self.assertTrue(self.app.chat_memory.view('private','a')['items'])
        people=self.app.chat_memory.view('private','a','people')['items'];self.assertTrue(any(p['is_self'] and p['memories'] for p in people));self.assertTrue(any(not p['is_self'] and p['memories'] for p in people))
        group=self.start();self.assertNotIn('私聊独有',json.dumps(group['memory_context'],ensure_ascii=False));self.assertNotIn('私聊独有',json.dumps(group['previous_turns'],ensure_ascii=False))
        global_run=self.app.workspace_agent.begin('a','总结群聊中的我')
        self.assertNotIn('私聊独有',json.dumps(global_run['memory_context'],ensure_ascii=False))
        self.assertTrue(self.app.chat_memory.self_memories('a')['items'])

    def test_message_changes_invalidate_exact_coverage_and_noncontiguous_ranges(self):
        with self.app.storage.connect() as conn:
            conn.execute("UPDATE messages SET text='目标一' WHERE id='m0'")
            self.add_message(conn,'middle','group-a','不在本次目标',100)
            self.add_message(conn,'late','group-a','目标二',105)
        run=self.start();raw=self.read(run,query='目标一');self.finish(run,raw)
        run=self.start();raw=self.read(run,query='目标二');self.finish(run,raw)
        before=self.app.chat_memory.coverage('group-a','a');self.assertEqual(before['compressed'],2);self.assertEqual(len(before['ranges']),2)
        with self.app.storage.connect() as conn:conn.execute("UPDATE messages SET text='来源已经变化' WHERE id='m0'")
        after=self.app.chat_memory.coverage('group-a','a');self.assertEqual(after['compressed'],1);self.assertEqual(after['unread'],3)
        with self.app.storage.connect() as conn:self.assertIsNone(conn.execute("SELECT 1 FROM ai_message_memory WHERE message_id='m0'").fetchone())

    def test_persona_questions_reuse_first_then_selectively_read_original(self):
        with self.app.storage.connect() as conn:conn.execute("UPDATE messages SET text=? WHERE id='m0'",('原话与语气不能截短。'*700,))
        first=self.start();raw=self.read(first,prefer_cache=False);self.finish(first,raw)
        cached=self.start(question='概括已经读过的内容');read=self.read(cached)
        self.assertGreater(read['reused_messages'],0);self.finish(cached,read)
        exact=self.start(question='分析人物画像与说话风格');original=self.read(exact)
        self.assertEqual(original['reused_messages'],2)
        original=self.read(exact,prefer_cache=False,sender='100001')
        self.assertEqual(original['reused_messages'],0);self.assertIn('原话与语气不能截短。'*700,json.dumps(original,ensure_ascii=False))

    def test_paused_memory_neither_reads_nor_writes_and_legacy_analysis_updates_agent(self):
        self.app.chat_memory.save_settings('group-a','a',{'remember':False})
        run=self.start();raw=self.read(run);self.assertEqual(raw['memory'],[]);self.finish(run,raw)
        stats=self.start(question='统计本会话的发言数量')
        self.app.workspace_agent.tool(stats['run_id'],'a','statistics',{'conversation_ids':['group-a']})
        self.app.workspace_agent.finish(stats['run_id'],'a',{'answer':'已统计原库。','evidence_ids':[]})
        with self.app.storage.connect() as conn:
            for table in ('ai_memories','ai_contexts','ai_message_memory'):self.assertEqual(conn.execute(f'SELECT count(*) FROM {table} WHERE conversation_id=?',('group-a',)).fetchone()[0],0,table)
        self.assertEqual(self.app.chat_memory.coverage('group-a','a')['compressed'],0)
        self.assertTrue(self.app.chat_memory.view('group-a','a')['paused'])
        self.app.chat_memory.save_settings('group-a','a',{'remember':True})
        prepared=self.ai.prepare('group-a','a','profile',fixtures.MODEL,{'mode':'recent','limit':100})
        fixtures.AITest.complete(self,prepared)
        learned=self.app.chat_memory.settings('group-a','a')['learned']
        self.assertEqual(learned['feature'],'profile');self.assertEqual(self.app.chat_memory.coverage('group-a','a')['compressed'],2)

    def test_pausing_while_legacy_job_runs_blocks_frozen_settings_memory_writes(self):
        prepared=self.ai.prepare('group-a','a','summary',fixtures.MODEL,{'mode':'recent','limit':100})
        self.app.chat_memory.save_settings('group-a','a',{'remember':False})
        fixtures.AITest.complete(self,prepared)
        with self.app.storage.connect() as conn:
            for table in ('ai_memories','ai_contexts','ai_message_memory'):self.assertEqual(conn.execute(f'SELECT count(*) FROM {table} WHERE conversation_id=?',('group-a',)).fetchone()[0],0,table)
        self.ai.save_group('group-a','a',{'remember':True})
        self.assertTrue(self.app.chat_memory.settings('group-a','a')['remember_enabled'])

    def test_controlled_changes_require_current_user_request_and_preserve_corrections(self):
        run=self.start();raw=self.read(run);self.finish(run,raw)
        key=self.app.chat_memory.view('group-a','a')['items'][0]['memory_key']
        ordinary=self.start(question='总结聊天里的通知')
        with self.assertRaises(CoreError):self.app.workspace_agent.tool(ordinary['run_id'],'a','update_memory',{'conversation_id':'group-a','memory_key':key,'action':'correct','correction':'未经请求的修改'})
        edit=self.start(question='纠正本群记忆：目前主要讨论课程')
        self.app.workspace_agent.tool(edit['run_id'],'a','update_memory',{'conversation_id':'group-a','memory_key':key,'action':'correct','correction':'用户确认：仅讨论课程。'})
        raw=self.read(edit);self.finish(edit,raw)
        item=next(m for m in self.app.chat_memory.view('group-a','a')['items'] if m['memory_key']==key)
        self.assertTrue(item['locked']);self.assertEqual(item['body'],'用户确认：仅讨论课程。')
        own=self.app.workspace_agent.begin('a','记住我的身份是课程学生')
        self.app.workspace_agent.tool(own['run_id'],'a','update_self',{'settings':{'identity':'课程学生'}})
        self.assertEqual(self.app.chat_memory.self_profile('a')['identity'],'课程学生')
        with self.assertRaises(CoreError):self.app.workspace_agent.tool(edit['run_id'],'a','update_agent',{'conversation_id':'group-b','settings':{'prompt':'越界'}})

    def test_attachments_are_bound_to_account_session_branch_and_persist_with_backup(self):
        chat=self.app.workspace_agent.create_session('a',conversation_id='group-a')
        attached=self.app.workspace_agent.add_attachment('a',chat['id'],'合成说明.md','text/markdown',base64.b64encode('# 用户附件\n请核对图表。'.encode()).decode())
        first=self.app.workspace_agent.begin('a','看看这个附件',session_id=chat['id'],attachment_ids=[attached['id']])
        data=self.app.workspace_agent.attachment_data(first['run_id'],'a',attached['id']);self.assertEqual(data['mime'],'text/markdown')
        self.app.workspace_agent.attachment_observed(first['run_id'],'a',attached['id'],'仅为附件，不是QQ消息。')
        self.app.workspace_agent.finish(first['run_id'],'a',{'answer':'附件已读','evidence_ids':[]})
        follow=self.start(session_id=chat['id']);self.assertEqual(follow['previous_turns'][0]['attachments'][0]['attachment_id'],attached['id'])
        self.app.workspace_agent.finish(follow['run_id'],'a',{'answer':'继续','evidence_ids':[]})
        edited=self.app.workspace_agent.begin('a','修改首问，不使用旧附件',session_id=chat['id'],edit_run_id=first['run_id'])
        with self.assertRaises(CoreError):self.app.workspace_agent.attachment_data(edited['run_id'],'a',attached['id'])
        self.app.workspace_agent.finish(edited['run_id'],'a',{'answer':'新分支','evidence_ids':[]})
        other=self.app.workspace_agent.create_session('a',conversation_id='group-b')
        with self.assertRaises(CoreError):self.app.workspace_agent.begin('a','越界附件',session_id=other['id'],attachment_ids=[attached['id']])
        with self.assertRaises(CoreError):self.app.workspace_agent.add_attachment('b',chat['id'],'a.txt','text/plain','YQ==')
        with self.assertRaises(CoreError):self.app.workspace_agent.add_attachment('a',chat['id'],'a.png','image/png','YQ==')
        run=self.start();raw=self.read(run);self.finish(run,raw);self.app.chat_memory.save_self('a',{'identity':'合成全局身份'})
        backup=self.root/'conversation.db';self.app.export_archive(str(backup))
        restored=fixtures.AssistantService(self.root/'restored');restored.manual_import(str(backup),'app_db')
        self.assertEqual(restored.chat_memory.self_profile('a')['identity'],'合成全局身份');self.assertEqual(restored.chat_memory.coverage('group-a','a')['compressed'],2)
        self.assertEqual(restored.workspace_agent.get_session(chat['id'],'a')['session']['conversation_id'],'group-a')
        restored.workspace_agent.select_branch(chat['id'],'a',follow['run_id'])
        resumed=restored.workspace_agent.begin('a','回读附件',session_id=chat['id'])
        self.assertEqual(restored.workspace_agent.attachment_data(resumed['run_id'],'a',attached['id'])['filename'],'合成说明.md')

    def test_self_message_direction_uses_explicit_uid_even_when_raw_direction_is_incoming(self):
        self.app.chat_memory.save_self('a',{'qq':'200001','uid':'u_self'})
        with self.app.storage.connect() as conn:conn.execute("UPDATE messages SET sender_qq='',sender_key='u_self',direction='incoming' WHERE id='m0'")
        rows=self.app.list_messages('group-a',account_id='a')['items'];own=next(r for r in rows if r['id']=='m0');peer=next(r for r in rows if r['id']=='m1')
        self.assertTrue(own['is_self']);self.assertEqual(own['direction'],'outgoing');self.assertFalse(peer['is_self'])
        self.assertEqual([r['id'] for r in self.app.list_messages('group-a',account_id='a',direction='outgoing')['items']],['m0'])
        self.assertEqual([r['id'] for r in self.app.list_messages('group-a',account_id='a',direction='incoming')['items']],['m1'])

    def test_portrait_cannot_finish_without_source_and_unread_tool_selects_only_uncovered(self):
        portrait=self.start(question='分析本群成员画像并完善Agent')
        with self.assertRaises(CoreError) as error:self.app.workspace_agent.finish(portrait['run_id'],'a',{'answer':'无源画像不能保存','evidence_ids':[]})
        self.assertEqual(error.exception.code,'AI_EVIDENCE_INVALID')
        raw=self.read(portrait,query='请组长');self.finish(portrait,raw)
        next_run=self.start(question='只读剩下尚未分析的消息')
        unread=self.read(next_run,unread_only=True)
        self.assertEqual(unread['selected_messages'],1);self.assertIn('组长收到',json.dumps(unread,ensure_ascii=False))
        self.finish(next_run,unread);self.assertEqual(self.app.chat_memory.coverage('group-a','a')['unread'],0)

    def test_user_supplement_is_locked_and_marked_as_user_statement_without_claiming_corpus_coverage(self):
        run=self.start(question='记住本群周日需要检查一次进度')
        result=self.app.workspace_agent.tool(run['run_id'],'a','update_memory',{'conversation_id':'group-a','action':'remember','correction':'周日需要检查一次进度。'})
        self.app.workspace_agent.finish(run['run_id'],'a',{'answer':'已保存你补充的安排。','evidence_ids':[]})
        saved=next(m for m in self.app.chat_memory.view('group-a','a')['items'] if m['memory_key']==result['memory_key'])
        self.assertTrue(saved['locked']);self.assertIn('用户',saved['provenance']);self.assertEqual(saved['evidence_ids'],[])
        self.assertEqual(self.app.chat_memory.coverage('group-a','a')['read'],0)

    def test_plain_reply_leaves_chat_source_unread_and_backup_rejects_scope_tampering(self):
        run=self.start(question='你好')
        self.app.workspace_agent.finish(run['run_id'],'a',{'answer':'你好，可以直接聊天。','evidence_ids':[]})
        self.assertEqual(self.app.chat_memory.coverage('group-a','a')['read'],0)
        backup=self.root/'tampered.db';self.app.export_archive(str(backup))
        conn=sqlite3.connect(backup);conn.execute("UPDATE workspace_sessions SET conversation_id='group-b' WHERE id=?",(run['session_id'],));conn.commit();conn.close()
        other=fixtures.AssistantService(self.root/'tampered-target')
        with self.assertRaises(CoreError):other.manual_import(str(backup),'app_db')
        with other.storage.connect() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM workspace_sessions').fetchone()[0],0)


if __name__=='__main__':unittest.main()
