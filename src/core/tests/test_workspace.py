import base64
import hashlib
import json
import sqlite3
import unittest

import test_history
from test_core import field, int_field
import test_core
from local_assistant.protocol import decode_message_details, decode_cached_replies
from local_assistant.service import AssistantService, CoreError


class WorkspaceTest(unittest.TestCase):
    setUp = test_history.HistoryTest.setUp

    def test_sort_filter_cursor_and_recent(self):
        for order in ('asc', 'desc'):
            cursor = None; items = []
            while True:
                page = self.service.search_messages('合成记录', sender='123456', direction='incoming', account_id='synthetic-a', order=order, limit=37, cursor=cursor)
                items.extend(page['items'])
                if not page['has_more']: break
                cursor = page['next_cursor']
            self.assertEqual(len(items), 204)
            keys = [(item['sent_at'], item['id']) for item in items]
            self.assertEqual(keys, sorted(keys, reverse=order=='desc'))
            self.assertEqual(len(set(keys)), 204)
        ascending = self.service.list_messages(self.conversation, account_id='synthetic-a', recent=True, order='asc')['items']
        descending = self.service.list_messages(self.conversation, account_id='synthetic-a', recent=True, order='desc')['items']
        self.assertEqual(ascending, descending[::-1])
        self.assertEqual(len(self.service.list_messages(self.conversation, limit=500)['items']), 205)

    def test_context_favorites_and_account_scope(self):
        oldest = self.service.list_messages(self.conversation, order='asc', limit=1)['items'][0]
        self.service.set_favorite(oldest['id'], True, 'synthetic-a')
        self.assertEqual(self.service.list_favorites('synthetic-a')['items'][0]['id'], oldest['id'])
        self.assertEqual(self.service.list_favorites('synthetic-a', query=oldest['text'])['items'][0]['id'], oldest['id'])
        self.assertTrue(self.service.message_context(oldest['id'], 'synthetic-a')['items'][0]['favorite'])
        self.assertEqual(self.service.message_context(oldest['id'], 'synthetic-a')['target_id'], oldest['id'])
        self.assertEqual(self.service.list_favorites('other')['items'], [])
        for action in (lambda: self.service.message_context(oldest['id'], 'other'), lambda: self.service.set_favorite(oldest['id'], True, 'other')):
            with self.assertRaises(CoreError): action()
        self.service.set_favorite(oldest['id'], False, 'synthetic-a')
        self.assertEqual(self.service.list_favorites('synthetic-a')['items'], [])

    def test_pin_pagination_roles_and_acknowledgements(self):
        with self.service.storage.connect() as conn:
            conn.execute("UPDATE conversations SET kind='group' WHERE id=?", (self.conversation,))
            conn.execute("INSERT INTO conversations(id,kind,title,updated_at,platform,account_id) VALUES('old-group','group','合成旧群',0,'qq','synthetic-a')")
            ids = [row[0] for row in conn.execute('SELECT id FROM messages LIMIT 4')]
            for key, text in zip(ids, ('班长收到', '第一组收到！', '收到，明天请组长提交报告', '请班长明天收集作业')):
                conn.execute('UPDATE messages SET text=? WHERE id=?', (text, key))
        self.service.pin_conversation('old-group', True, 'synthetic-a')
        page = self.service.list_conversations(account_id='synthetic-a', limit=1)
        self.assertEqual(page['items'][0]['id'], 'old-group')
        self.assertEqual(self.service.list_conversations(account_id='synthetic-a', cursor=page['next_cursor'])['items'][0]['id'], self.conversation)
        self.service.save_profile('组长')
        self.service.save_profile('班长', self.conversation, 'synthetic-a')
        digest = self.service.work_digest(conversation_id=self.conversation, account_id='synthetic-a', limit=800)
        self.assertFalse(any(item['text'].endswith('收到') or item['text']=='第一组收到！' for item in digest['items']))
        self.assertTrue(any(item['text']=='收到，明天请组长提交报告' for item in digest['items']))
        self.assertTrue(all(item['role_context']=='班长' for item in digest['items']))
        self.assertEqual(self.service.get_profile(self.conversation, 'synthetic-a')['fallback_role'], '')
        self.assertEqual(self.service.get_profile('old-group', 'synthetic-a')['role_text'], '')

    def test_image_favorite_local_backup_restore(self):
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
        digest = hashlib.md5(png).hexdigest()
        folder = self.root / 'new-cache'; folder.mkdir()
        (folder / (digest + '#中文.png')).write_bytes(png)
        message = self.service.list_messages(self.conversation, limit=1)['items'][0]
        item = {'type':'image','md5':digest,'filename':'old-name.png','local_path':'Z:/other-pc/missing.png'}
        with self.service.storage.connect() as conn:
            conn.execute('UPDATE messages SET media_json=? WHERE id=?', (json.dumps([item]), message['id']))
        self.service.configure_media_roots('synthetic-a',str(folder))
        self.assertTrue(self.service.read_media(message_id=message['id'], media_index=0, account_id='synthetic-a')['available'])
        self.service.set_favorite(message['id'], True, 'synthetic-a', media_index=0)
        self.assertEqual(len(list((self.root/'data'/'favorites'/'media').glob('*.png'))),1)
        self.service.save_profile('此群角色', self.conversation,'synthetic-a')
        self.service.pin_conversation(self.conversation,True,'synthetic-a')
        backup=self.root/'portable.db'
        self.service.export_archive(str(backup))
        other=AssistantService(self.root/'pc2')
        result=other.manual_import(str(backup),'app_db')
        self.assertEqual(result['account_ids'],['synthetic-a'])
        favorite=other.list_favorites('synthetic-a',kind='image')['items'][0]
        self.assertTrue(other.read_media(message_id=favorite['id'],media_index=0,account_id='synthetic-a')['available'])
        self.assertEqual(other.get_profile(favorite['conversation_id'],'synthetic-a')['role_text'],'此群角色')
        self.assertTrue(other.list_conversations(account_id='synthetic-a')['items'][0]['pinned'])
        self.assertEqual(len(list((self.root/'pc2'/'favorites'/'media').glob('*.png'))),1)
        self.assertEqual(other.manual_import(str(backup),'app_db')['added'],0)
        self.assertTrue(other.list_favorites('synthetic-a',kind='image')['items'])

    def test_missing_image_not_faked_and_invalid_asset_rolls_back(self):
        message=self.service.list_messages(self.conversation,limit=1)['items'][0]
        with self.service.storage.connect() as conn:
            conn.execute('UPDATE messages SET media_json=? WHERE id=?',(json.dumps([{'type':'image','filename':'not-downloaded.png'}]),message['id']))
        with self.assertRaises(CoreError) as caught: self.service.set_favorite(message['id'],True,'synthetic-a',media_index=0)
        self.assertEqual(caught.exception.code,'MEDIA_MISSING')
        self.assertEqual(self.service.list_favorites('synthetic-a')['items'],[])
        backup=self.root/'bad.db';self.service.export_archive(str(backup))
        conn=sqlite3.connect(backup)
        conn.execute('INSERT INTO media_assets VALUES(?,?,?)',('bad','image/png',b'not-a-picture'));conn.commit();conn.close()
        other=AssistantService(self.root/'bad-target')
        with self.assertRaises(CoreError): other.manual_import(str(backup),'app_db')
        self.assertEqual(other.overview()['message_count'],0)

    def test_distinct_source_keys_not_merged_by_protocol(self):
        first=self.root/'first.db';second=self.root/'second.db'
        for path,native,body in ((first,900,'请提交合成作业'),(second,800,'请提交合成作业')):
            test_core.CoreTest.make_plain_database(path)
            conn=sqlite3.connect(path)
            conn.execute('ALTER TABLE group_msg_table ADD COLUMN "40002"')
            conn.execute('ALTER TABLE group_msg_table ADD COLUMN "40003"')
            conn.execute('INSERT INTO group_msg_table VALUES(?,2,0,0,"member","group",888888,123456,1700000001,?,NULL,"合成成员",77,99)',(native,field(40800,field(45101,body.encode()))))
            conn.commit();conn.close()
        app=AssistantService(self.root/'merge')
        app.import_snapshot(str(first),'synthetic')
        app.import_snapshot(str(second),'synthetic')
        group=next(item for item in app.list_conversations()['items'] if item['kind']=='group')
        self.assertEqual(len(app.list_messages(group['id'])['items']),2)
        separate=AssistantService(self.root/'separate-pc')
        separate.import_snapshot(str(second),'synthetic')
        backup=self.root/'separate-pc.db';separate.export_archive(str(backup))
        self.assertEqual(app.manual_import(str(backup),'app_db')['added'],0)
        conn=sqlite3.connect(second);conn.execute('UPDATE group_msg_table SET "40800"=NULL');conn.commit();conn.close()
        app.import_snapshot(str(second),'synthetic')
        self.assertEqual(app.list_messages(group['id'])['items'][0]['text'],'请提交合成作业')
        conn=sqlite3.connect(second);conn.execute('UPDATE group_msg_table SET "40800"=?',(field(40800,field(45101,'请提交新版作业'.encode())),));conn.commit();conn.close()
        app.import_snapshot(str(second),'synthetic')
        message=next(item for item in app.list_messages(group['id'])['items'] if item['id'].endswith(':800'))
        self.assertTrue(app.message_context(message['id'],'synthetic')['variants'])

    def test_old_backup_without_workspace_tables_and_fields(self):
        backup=self.root/'legacy-v1.db';self.service.export_archive(str(backup))
        conn=sqlite3.connect(backup)
        for table in ('message_media','media_assets','favorites','conversation_preferences','media_roots','message_aliases','message_variants'):
            conn.execute(f'DROP TABLE {table}')
        conn.execute('DROP INDEX idx_messages_sync')
        conn.execute('DROP INDEX idx_conversations_pinned')
        conn.execute('ALTER TABLE messages DROP COLUMN sync_key')
        conn.execute('ALTER TABLE messages DROP COLUMN reply_json')
        conn.execute('ALTER TABLE conversations DROP COLUMN pinned')
        conn.commit();conn.close()
        other=AssistantService(self.root/'legacy-target')
        self.assertEqual(other.manual_import(str(backup),'app_db')['added'],205)
        self.assertEqual(other.list_favorites('synthetic-a')['items'],[])

    def test_protocol_reply_graytip_and_projection_repair(self):
        quoted=int_field(45002,1)+field(45101,'引用任务正文'.encode())
        reply=int_field(45002,7)+field(47710,quoted)
        details=decode_message_details(field(40800,reply)+field(40800,field(45101,'班长收到'.encode())),2)
        self.assertEqual(details['text'],'班长收到')
        self.assertEqual(details['replies'][0]['text'],'引用任务正文')
        gray=int_field(45002,8)+field(48214,'<msg><item txt="合成群公告"/></msg>'.encode())
        self.assertEqual(decode_message_details(field(40800,gray),2)['text'],'合成群公告')
        self.assertEqual(decode_message_details(quoted,2)['text'],'引用任务正文')
        cached=decode_cached_replies(field(40900,field(40800,quoted)))
        self.assertEqual(cached[0]['text'],'引用任务正文')
        with self.service.storage.connect() as conn: conn.execute("UPDATE messages SET text='[系统/引用]' WHERE id=(SELECT id FROM messages LIMIT 1)")
        self.assertGreater(self.service.repair_messages('synthetic-a')['updated'],0)
        self.assertFalse(any(item['text']=='[系统/引用]' for item in self.service.search_messages(limit=500)['items']))


if __name__ == '__main__': unittest.main()
