import json,sqlite3,unittest
import test_ai as fixtures
from local_assistant.errors import CoreError


class WorkspaceChatsTest(unittest.TestCase):
    setUp=fixtures.AITest.setUp
    add_message=fixtures.AITest.add_message

    def test_recent_chats_combines_scopes_archives_and_latest_turn(self):
        agent=self.app.workspace_agent
        for cid in ('','group-a','private'):
            session=agent.create_session('a',conversation_id=cid)
            value=agent.begin('a','合成问题'+cid,session_id=session['id'],conversation_id=cid)
            agent.finish(value['run_id'],'a',{'answer':'不应出现在列表的完整回答','evidence_ids':[]})
            if cid=='group-a':
                last=agent.begin('a','合成最新追问',session_id=session['id'],conversation_id=cid)
                agent.finish(last['run_id'],'a',error='合成失败')
                with self.app.storage.connect() as conn:conn.execute("UPDATE workspace_sessions SET updated_at='2099-01-01T00:00:00Z' WHERE id=?",(session['id'],))
        agent.create_session('a',title='尚未发送的空对话')
        foreign=agent.create_session('b',conversation_id='group-c')
        run=agent.begin('b','不能泄露',session_id=foreign['id'],conversation_id='group-c');agent.finish(run['run_id'],'b',error='合成失败')
        old=self.ai.prepare('group-a','a','summary',fixtures.MODEL,{'goal':'旧版用户分析'})
        self.ai.prepare('group-a','a','profile',fixtures.MODEL,{'goal':'工作区阶段画像:internal'})
        hidden=self.ai.prepare('group-a','a','work',fixtures.MODEL,{'goal':'内部压缩'})
        with self.app.storage.connect() as conn:conn.execute("UPDATE ai_jobs SET feature='context' WHERE id=?",(hidden['job_id'],))
        items=agent.recent_chats('a')['items']
        self.assertEqual(len(items),4)
        self.assertEqual(items[0]['preview'],'合成最新追问');self.assertEqual(items[0]['status'],'failed')
        self.assertEqual({v['conversation_kind'] for v in items},{'global','group','c2c'})
        self.assertEqual([v['id'] for v in items if v['kind']=='analysis'],[old['job_id']])
        self.assertTrue(all('answer' not in v and len(v['preview'])<=180 for v in items))
        self.assertNotIn('不能泄露',json.dumps(items,ensure_ascii=False))

    def test_recent_chats_paginates_ties_and_rejects_invalid_parameters(self):
        for i in range(3):self.turn('合成历史'+str(i))
        with self.app.storage.connect() as conn:conn.execute("UPDATE workspace_sessions SET updated_at='2026-10-27T00:00:00Z'")
        agent=self.app.workspace_agent;whole=agent.recent_chats('a')['items'];parts=[]
        for offset in range(3):
            page=agent.recent_chats('a',offset=offset,limit=1);parts.extend(page['items']);self.assertEqual(page['has_more'],offset<2)
        self.assertEqual([x['id'] for x in whole],[x['id'] for x in parts])
        self.assertEqual(agent.recent_chats('missing')['items'],[])
        for args in [{'account_id':''},{'account_id':[]},{'account_id':'a','limit':True},{'account_id':'a','limit':101},{'account_id':'a','offset':-1}]:
            with self.assertRaises(CoreError):agent.recent_chats(**args)

    def test_recent_chats_hides_deleted_records(self):
        value=self.app.workspace_agent.begin('a','合成失败问题');self.app.workspace_agent.finish(value['run_id'],'a',error='合成失败')
        old=self.ai.prepare('group-a','a','summary',fixtures.MODEL,{})
        with self.app.storage.connect() as conn:conn.execute("UPDATE ai_jobs SET status='failed' WHERE id=?",(old['job_id'],))
        self.ai.delete_history('group-a','a',old['job_id'])
        self.app.workspace_agent.delete_history(value['run_id'],'a')
        self.assertEqual(self.app.workspace_agent.recent_chats('a')['items'],[])

    def turn(self,question,session='',answer='',edit=''):
        value=self.app.workspace_agent.begin('a',question,session_id=session,edit_run_id=edit)
        self.app.workspace_agent.finish(value['run_id'],'a',{'answer':answer or question+'的回答','evidence_ids':[]})
        return value

    def test_same_chat_keeps_normal_followups_and_separate_chats_do_not_mix(self):
        first=self.turn('总结工作群','',answer='本对话唯一暗号：青柠')
        second=self.turn('请把重点改成三点',first['session_id'])
        self.assertEqual(second['previous_turns'][0]['answer'],'本对话唯一暗号：青柠')
        third=self.turn('再加一段背景',first['session_id']);self.assertEqual(len(third['previous_turns']),2)
        other=self.turn('不相关的新讨论');self.assertEqual(other['previous_turns'],[])
        self.assertNotEqual(other['session_id'],first['session_id'])
        with self.assertRaises(CoreError):self.app.workspace_agent.get_session(first['session_id'],'b')
        with self.assertRaises(CoreError):self.app.workspace_agent.rename_session(first['session_id'],'b','越界')
        with self.assertRaises(CoreError):self.app.workspace_agent.begin('b','越界',session_id=first['session_id'])

    def test_edit_and_regenerate_keep_old_branch_and_billing(self):
        first=self.turn('问题一');second=self.turn('问题二',first['session_id']);third=self.turn('问题三',first['session_id'])
        changed=self.turn('修改后的问题二',first['session_id'],edit=second['run_id'])
        self.assertEqual([p['question'] for p in changed['previous_turns']],['问题一'])
        current=self.app.workspace_agent.get_session(first['session_id'],'a')
        self.assertEqual([p['question'] for p in current['items']],['问题一','修改后的问题二'])
        self.assertEqual({p['id'] for p in current['branches']},{third['run_id'],changed['run_id']})
        self.app.workspace_agent.select_branch(first['session_id'],'a',third['run_id'])
        self.assertEqual(len(self.app.workspace_agent.get_session(first['session_id'],'a')['items']),3)
        regenerated=self.app.workspace_agent.begin('a','问题三',session_id=first['session_id'],edit_run_id=third['run_id'])
        attempt=self.ai.ledger.reserve_call(fixtures.MODEL,'agent',1000,512,job_id=regenerated['run_id'])
        self.ai.ledger.settle_call(attempt['attempt'],{'input_tokens':40,'output_tokens':10})
        self.app.workspace_agent.finish(regenerated['run_id'],'a',{'answer':'重试后的新回答','evidence_ids':[]})
        self.assertEqual([p['question'] for p in regenerated['previous_turns']],['问题一','问题二'])
        self.assertEqual(self.ai.ledger.list(account_id='a')['items'][0]['charged'],50)
        foreign=self.turn('其他对话')
        with self.assertRaises(CoreError):self.app.workspace_agent.select_branch(first['session_id'],'a',foreign['run_id'])
        with self.assertRaises(CoreError):self.app.workspace_agent.begin('a','跨分支修改',session_id=first['session_id'],edit_run_id=changed['run_id'])

    def test_private_context_inherits_within_chat_but_group_scope_filters_it(self):
        first=self.turn('比较群聊和我私聊',answer='私聊独有内容')
        inherited=self.turn('换一种表达',first['session_id'])
        self.assertEqual(inherited['allowed_kinds'],['group','c2c']);self.assertEqual(len(inherited['previous_turns']),1)
        group=self.turn('只看群聊里的工作',first['session_id'])
        self.assertEqual(group['allowed_kinds'],['group']);self.assertEqual(group['previous_turns'],[])
        self.assertEqual(group['context_notice']['scope_filtered'],2)
        read=self.app.workspace_agent.begin('a','再整理一遍',session_id=first['session_id'])
        result=self.app.workspace_agent.tool(read['run_id'],'a','chat_history',{})
        self.assertEqual([p['question'] for p in result['items']],['只看群聊里的工作'])

    def test_full_history_persists_and_can_be_read_when_request_context_is_bounded(self):
        text='合成旧回答需要完整保存。'*3000
        first=self.turn('很长的原问题'*600,answer=text)
        next_turn=self.app.workspace_agent.begin('a','简化这段回答',session_id=first['session_id'],context_bytes=2000)
        self.assertTrue(next_turn['previous_turns'][0]['truncated'])
        self.assertLessEqual(len(json.dumps(next_turn['previous_turns'][0],ensure_ascii=False,separators=(',',':')).encode()),2000)
        rebuilt='';offset=0
        while True:
            page=self.app.workspace_agent.tool(next_turn['run_id'],'a','chat_history',{'turn_id':first['run_id'],'offset':offset})
            rebuilt+=page['answer']
            if not page['has_more']:break
            offset=page['next_offset']
        self.assertEqual(rebuilt,text)
        other=self.turn('其他对话不可读取')
        with self.assertRaises(CoreError):self.app.workspace_agent.tool(next_turn['run_id'],'a','chat_history',{'turn_id':other['run_id']})
        restarted=fixtures.AssistantService(self.app.data_dir)
        detail=restarted.workspace_agent.get_session(first['session_id'],'a')
        self.assertEqual(detail['items'][0]['answer'],text);self.assertEqual(detail['items'][-1]['status'],'interrupted')

    def test_pagination_rename_and_busy_guard(self):
        first=self.turn('第一轮')
        for i in range(6):self.turn(f'追问{i}',first['session_id'])
        detail=self.app.workspace_agent.get_session(first['session_id'],'a',limit=3)
        self.assertTrue(detail['has_more']);self.assertEqual(detail['total_turns'],7)
        earlier=self.app.workspace_agent.get_session(first['session_id'],'a',offset=3,limit=3)
        self.assertNotEqual(earlier['items'][-1]['id'],detail['items'][0]['id'])
        self.app.workspace_agent.rename_session(first['session_id'],'a','课程研究')
        self.assertEqual(self.app.workspace_agent.get_session(first['session_id'],'a')['session']['title'],'课程研究')
        running=self.app.workspace_agent.begin('a','处理中',session_id=first['session_id'])
        with self.assertRaises(CoreError):self.app.workspace_agent.begin('a','不能并发',session_id=first['session_id'])
        with self.assertRaises(CoreError):self.app.workspace_agent.select_branch(first['session_id'],'a',first['run_id'])
        self.app.workspace_agent.finish(running['run_id'],'a',error='合成失败')
        self.app.workspace_agent.delete_history(running['run_id'],'a')
        self.assertEqual(self.app.workspace_agent.get_session(first['session_id'],'a')['total_turns'],7)

    def test_legacy_runs_migrate_individually_and_backup_keeps_branches(self):
        first=self.turn('旧任务一');second=self.turn('旧任务二')
        with self.app.storage.connect() as conn:
            conn.execute('DELETE FROM workspace_turns');conn.execute('DELETE FROM workspace_sessions')
        restarted=fixtures.AssistantService(self.app.data_dir)
        sessions=restarted.workspace_agent.list_sessions('a')['items'];self.assertEqual(len(sessions),2)
        session=next(s for s in sessions if s['head_id']==first['run_id'])
        one=restarted.workspace_agent.begin('a','旧任务续问',session_id=session['id'])
        restarted.workspace_agent.finish(one['run_id'],'a',{'answer':'续问结果','evidence_ids':[]})
        changed=restarted.workspace_agent.begin('a','旧问题修订',session_id=session['id'],edit_run_id=first['run_id'])
        restarted.workspace_agent.finish(changed['run_id'],'a',{'answer':'修订结果','evidence_ids':[]})
        archive=self.root/'session-backup.db';restarted.export_archive(str(archive))
        restored=fixtures.AssistantService(self.root/'session-restored');restored.manual_import(str(archive),'app_db')
        saved=restored.workspace_agent.get_session(session['id'],'a');self.assertEqual(len(saved['branches']),2)
        self.assertEqual(saved['items'][0]['question'],'旧问题修订')
        self.assertEqual(len(restored.workspace_agent.list_sessions('a')['items']),2)

    def test_import_rejects_cycles_and_legacy_backup_needs_no_new_tables(self):
        first=self.turn('备份问题');second=self.turn('备份续问',first['session_id'])
        archive=self.root/'bad-branch.db';self.app.export_archive(str(archive))
        with sqlite3.connect(archive) as conn:conn.execute('UPDATE workspace_turns SET parent_id=? WHERE run_id=?',(second['run_id'],first['run_id']))
        conn.close()
        restored=fixtures.AssistantService(self.root/'rejected')
        with self.assertRaises(CoreError):restored.manual_import(str(archive),'app_db')
        self.assertEqual(restored.workspace_agent.list_sessions('a')['items'],[])
        old=self.root/'old-backup.db';self.app.export_archive(str(old))
        with sqlite3.connect(old) as conn:conn.execute('DROP TABLE workspace_turns');conn.execute('DROP TABLE workspace_sessions')
        conn.close()
        restored.manual_import(str(old),'app_db')
        self.assertEqual(len(restored.workspace_agent.list_sessions('a')['items']),2)
