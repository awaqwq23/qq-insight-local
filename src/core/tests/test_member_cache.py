import csv
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from local_assistant.service import AssistantService, CoreError
import test_core


class MemberCacheTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'plain.db'
        self.metadata = self.root/'group_info.db'
        test_core.CoreTest.make_plain_database(self.source)
        with closing(sqlite3.connect(self.source)) as c, c:
            c.execute('INSERT INTO group_msg_table VALUES(1,2,0,0,"u1","g",900001,100001,1700000000,NULL,"旧群名片","旧昵称")')
        with closing(sqlite3.connect(self.metadata)) as c, c:
            c.execute('CREATE TABLE group_detail_info_ver1("60001","60007","60006")')
            c.execute('INSERT INTO group_detail_info_ver1 VALUES(900001,"合成群",2)')
            c.execute('CREATE TABLE group_member3("60001","1000","1002","20002","64003")')
            c.executemany('INSERT INTO group_member3 VALUES(900001,?,?,?,?)', [('u1',100001,' 原昵称 ',' 群名片 '),('u2',100002,'未发言合成成员','未发言群名片')])
        self.service = AssistantService(self.root/'app')
        self.load()
        self.group = 'qq:synthetic:group:g'

    def load(self):
        return self.service.import_snapshot(str(self.source),'synthetic',companion_paths={'group_info.db':self.metadata})

    def test_silent_member_dual_names_counts_and_no_source_write(self):
        before = self.metadata.read_bytes()
        info = self.service.member_cache_info('synthetic', self.group)
        self.assertEqual((info['count'],info['expected_count'],info['count_matches']),(2,2,True))
        output=self.root/'members.csv'
        self.service.export_roster(str(output),'synthetic','cached_members',self.group,cache_stamp=info['imported_at'])
        with output.open(encoding='utf-8-sig',newline='') as stream: rows=list(csv.DictReader(stream))
        silent=next(row for row in rows if row['QQ号']=='100002')
        self.assertEqual(rows[0]['QQ原昵称'],' 原昵称 ')
        self.assertEqual(rows[0]['群名片（群内备注）'],' 群名片 ')
        self.assertEqual(silent['QQ原昵称'],'未发言合成成员')
        self.assertEqual(silent['群名片（群内备注）'],'未发言群名片')
        self.assertIn('无法证明',silent['完整性说明'])
        self.assertEqual(before,self.metadata.read_bytes())

    def test_incremental_replaces_snapshot_and_preserves_other_account(self):
        self.service.import_snapshot(str(self.source),'other',companion_paths={'group_info.db':self.metadata})
        with closing(sqlite3.connect(self.metadata)) as c, c:
            c.execute('DELETE FROM group_member3 WHERE "1002"=100002')
            c.execute('INSERT INTO group_member3 VALUES(900001,"u3",100003,"新成员","新群名片")')
        self.load()
        with self.service.storage.connect() as c:
            self.assertEqual([r[0] for r in c.execute("SELECT qq FROM qq_group_members WHERE account_id='synthetic' ORDER BY qq")],['100001','100003'])
            self.assertEqual([r[0] for r in c.execute("SELECT qq FROM qq_group_members WHERE account_id='other' ORDER BY qq")],['100001','100002'])

    def test_partial_unknown_empty_and_stale_stamp(self):
        with closing(sqlite3.connect(self.metadata)) as c, c:
            c.execute('UPDATE group_detail_info_ver1 SET "60006"=3')
        self.load()
        info=self.service.member_cache_info('synthetic',self.group)
        self.assertFalse(info['count_matches']);self.assertIn('不能作为完整',info['note'])
        with self.assertRaises(CoreError): self.service.export_roster(str(self.root/'stale.csv'),'synthetic','cached_members',self.group,cache_stamp='old')
        self.assertFalse((self.root/'stale.csv').exists())
        with self.service.storage.connect() as c: c.execute('DELETE FROM qq_group_members')
        with self.assertRaises(CoreError) as error:self.service.member_cache_info('synthetic',self.group)
        self.assertEqual(error.exception.code,'MEMBER_CACHE_MISSING')

    def test_scope_and_archive_roundtrip(self):
        with self.assertRaises(CoreError):self.service.member_cache_info('different',self.group)
        path=self.root/'backup.db'
        self.service.export_archive(str(path))
        other=AssistantService(self.root/'new')
        other.manual_import(str(path),'app_db')
        self.assertEqual(other.member_cache_info('synthetic',self.group)['count'],2)

    def test_unsupported_fields_roll_back(self):
        with closing(sqlite3.connect(self.metadata)) as c, c:c.execute('ALTER TABLE group_member3 RENAME COLUMN "64003" TO unknown')
        with self.assertRaises(CoreError):self.load()
        self.assertEqual(self.service.member_cache_info('synthetic',self.group)['count'],2)

    def test_unexpected_member_value_types_roll_back(self):
        with closing(sqlite3.connect(self.metadata)) as c, c:c.execute('UPDATE group_member3 SET "64003"=?', (b'invalid-card',))
        with self.assertRaises(CoreError):self.load()
        self.assertEqual(self.service.member_cache_info('synthetic',self.group)['count'],2)
