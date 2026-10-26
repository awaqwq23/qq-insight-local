import csv
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from local_assistant.service import AssistantService, CoreError
import test_core
from test_core import field


class RosterTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'plain.db'
        test_core.CoreTest.make_plain_database(self.source)
        with closing(sqlite3.connect(self.source)) as conn, conn:
            conn.executemany('INSERT INTO group_msg_table VALUES(?,2,0,0,?,"group",900001,?,?,?, ?,?)', [
                (1, 'u1', 100001, 10, field(40800, field(45101, b'one')), '群名片旧', '昵称旧'),
                (2, 'u1', 100001, 20, field(40800, field(45101, b'two')), '=SUM(1,2)', '昵称新,"换行\n名字'),
                (3, 'u1', '', 5, field(40800, field(45101, b'three')), '', ''),
                (4, 'u2', 100002, 30, field(40800, field(45101, b'four')), '', ''),
            ])
        self.app = AssistantService(self.root / 'app')
        self.app.import_snapshot(str(self.source), 'synthetic-a')
        self.group = next(x['id'] for x in self.app.list_conversations(account_id='synthetic-a')['items'] if x['kind'] == 'group')

    def export(self, kind='members', name='out.csv', account='synthetic-a', conversation=None):
        p = self.root / name
        result = self.app.export_roster(str(p), account, kind, self.group if conversation is None else conversation)
        self.assertTrue(p.read_bytes().startswith(b'\xef\xbb\xbf'))
        with p.open(encoding='utf-8-sig', newline='') as stream:
            return result, list(csv.DictReader(stream))

    def test_dual_names_latest_identity_and_formula(self):
        with self.app.storage.connect() as conn:
            conn.execute("INSERT INTO qq_profiles(account_id,identity_key,uid,qq,nickname,remark) VALUES('synthetic-a','u2','u2','100002','资料昵称','私人备注不得当原昵称')")
        result, rows = self.export()
        self.assertEqual(result['count'], 2)
        first = next(row for row in rows if row['QQ号'] == '100001')
        self.assertEqual(first['QQ原昵称'], '昵称新,"换行\n名字')
        self.assertEqual(first['群名片（群内备注）'], "'=SUM(1,2)")
        second = next(row for row in rows if row['QQ号'] == '100002')
        self.assertEqual(second['QQ原昵称'], '资料昵称')
        self.assertEqual(second['群名片（群内备注）'], '')
        self.assertIn('非完整', first['数据范围'])

    def test_group_original_remark_and_metadata_only_group(self):
        with self.app.storage.connect() as conn:
            conn.executemany('INSERT INTO qq_groups(account_id,identity_key,group_qq,name,remark) VALUES(?,?,?,?,?)', [
                ('synthetic-a','900001','900001','原群名','我的备注'),
                ('synthetic-a','900002','900002','未发言群',''),
                ('synthetic-b','900003','900003','别账号群','不可导出')])
        result, rows = self.export('groups')
        self.assertEqual(result['count'], 2)
        self.assertEqual(rows[0]['群原名称'], '原群名')
        self.assertEqual(rows[0]['群备注名称'], '我的备注')

    def test_missing_names_never_use_display_name(self):
        with self.app.storage.connect() as conn:
            conn.execute("UPDATE messages SET sender_nickname='',sender_card='',sender_name='合并显示名'")
        _, rows = self.export()
        self.assertTrue(all(row['QQ原昵称'] == row['群名片（群内备注）'] == '' for row in rows))
        self.assertTrue(all(row['历史显示名称'] == '合并显示名' for row in rows))

    def test_scope_type_and_destination_guards(self):
        for kwargs in [dict(account_id='synthetic-b'), dict(account_id=''), dict(account_id='synthetic-a', platform='wechat'), dict(account_id='synthetic-a', kind='invalid'), dict(account_id='synthetic-a', conversation_id='missing')]:
            args = dict(path=str(self.root/'fail.csv'), account_id='synthetic-a', kind='members', conversation_id=self.group)
            args.update(kwargs)
            with self.assertRaises(CoreError): self.app.export_roster(**args)
            self.assertFalse((self.root/'fail.csv').exists())
        self.export()
        before = (self.root/'out.csv').read_bytes()
        with self.assertRaises(CoreError): self.export()
        self.assertEqual((self.root/'out.csv').read_bytes(), before)
        with self.assertRaises(CoreError): self.export(name='out.db')

    def test_system_and_unknown_identity_not_exported(self):
        with self.app.storage.connect() as conn:
            conn.execute("UPDATE messages SET direction='system' WHERE sender_key='u2'")
            conn.execute("UPDATE messages SET sender_key='',sender_qq='' WHERE sender_key='u1'")
        result, rows = self.export()
        self.assertEqual(result['count'], 0)
        self.assertEqual(rows, [])

    def test_projection_upgrade_recovers_two_names(self):
        with self.app.storage.connect() as conn:
            conn.execute("UPDATE messages SET sender_nickname='',sender_card=''")
            conn.execute('UPDATE imports SET projection_version=5')
        self.app.import_snapshot(str(self.source), 'synthetic-a')
        _, rows = self.export()
        self.assertTrue(any(row['QQ原昵称'].startswith('昵称新') for row in rows))

    def test_archive_roundtrip_and_old_archive(self):
        archive = self.root/'archive.db'
        self.app.export_archive(str(archive))
        other = AssistantService(self.root/'other')
        other.manual_import(str(archive), 'app_db')
        with other.storage.connect() as conn:
            self.assertEqual(conn.execute("SELECT sender_card FROM messages WHERE sender_card<>'' ORDER BY sent_at DESC LIMIT 1").fetchone()[0], '=SUM(1,2)')
        with closing(sqlite3.connect(archive)) as conn, conn:
            conn.execute('ALTER TABLE messages DROP COLUMN sender_nickname')
            conn.execute('ALTER TABLE messages DROP COLUMN sender_card')
        old = AssistantService(self.root/'old')
        old.manual_import(str(archive), 'app_db')
        with old.storage.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM messages WHERE sender_card<>\'\'').fetchone()[0], 0)

    def test_online_members_include_silent_member_and_validate_snapshot(self):
        self.app.import_snapshot(str(self.source), '10000001')
        group = next(x['id'] for x in self.app.list_conversations(account_id='10000001')['items'] if x['kind'] == 'group')
        scope = self.app.roster_scope('10000001', group)
        self.assertEqual(scope['group_qq'], '900001')
        online = {'account_id':'10000001', 'group_qq':'900001', 'count':1,
                  'members':[{'qq':'10000999','nickname':'未发言的合成成员','card':'合成群名片'}]}
        path = self.root/'online.csv'
        result = self.app.export_roster(str(path),'10000001','full_members',group,online=online)
        self.assertEqual(result['count'],1)
        with path.open(encoding='utf-8-sig',newline='') as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(row['QQ号'],'10000999')
        self.assertEqual(row['QQ原昵称'],'未发言的合成成员')
        self.assertEqual(row['群名片（群内备注）'],'合成群名片')
        for invalid in [None,{**online,'account_id':'10000002'},{**online,'group_qq':'900002'},
                        {**online,'count':2},{**online,'count':True},
                        {**online,'count':2,'members':online['members']*2},
                        {**online,'members':[{'qq':'bad','nickname':'x','card':''}]}]:
            target=self.root/'invalid.csv'
            with self.assertRaises(CoreError):
                self.app.export_roster(str(target),'10000001','full_members',group,online=invalid)
            self.assertFalse(target.exists())
        with self.assertRaises(CoreError): self.app.roster_scope('10000002',group)


if __name__ == '__main__':
    unittest.main()
