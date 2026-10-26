"""Import QQ's independent member cache, including people with no messages."""
from datetime import datetime, timezone
from contextlib import closing

from .errors import CoreError

SCHEMA = '''
CREATE TABLE IF NOT EXISTS qq_member_caches (
 account_id TEXT NOT NULL, group_qq TEXT NOT NULL, expected_count INTEGER NOT NULL,
 imported_at TEXT NOT NULL, PRIMARY KEY(account_id,group_qq));
CREATE TABLE IF NOT EXISTS qq_group_members (
 account_id TEXT NOT NULL, group_qq TEXT NOT NULL, identity_key TEXT NOT NULL,
 uid TEXT NOT NULL, qq TEXT NOT NULL, nickname TEXT NOT NULL, card TEXT NOT NULL,
 PRIMARY KEY(account_id,group_qq,identity_key));
'''


def import_cache(source, target, account_id):
    tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'group_member3' not in tables:
        return
    columns = {r[1] for r in source.execute('PRAGMA table_info(group_member3)')}
    if not {'60001', '1000', '1002', '20002', '64003'}.issubset(columns):
        raise CoreError('SOURCE_UNSUPPORTED', 'QQ成员缓存字段不受支持，本次导入已回滚。')
    groups = {}
    with closing(source.execute('SELECT "60001","1000","1002","20002","64003" FROM group_member3 ORDER BY "60001","1000","1002"')) as cursor:
        for row in cursor:
            if any(v is not None and not isinstance(v, (str, int)) for v in row[:3]) or any(v is not None and not isinstance(v, str) for v in row[3:]):
                raise CoreError('SOURCE_UNSUPPORTED', 'QQ成员缓存数据类型不受支持，本次导入已回滚。')
            group, uid, qq = (str(v or '').strip() for v in row[:3])
            nickname, card = (v or '' for v in row[3:])
            if not group or not (uid or qq):
                continue
            groups.setdefault(group, {})[qq or uid] = (uid, qq, nickname, card)
    expected = {}
    if 'group_detail_info_ver1' in tables and '60006' in {r[1] for r in source.execute('PRAGMA table_info(group_detail_info_ver1)')}:
        for group, count in source.execute('SELECT "60001","60006" FROM group_detail_info_ver1'):
            expected[str(group)] = count if type(count) is int and count > 0 else 0
    stamp = datetime.now(timezone.utc).isoformat()
    # Replace each observed group snapshot, rather than retaining departed members.
    for group in groups.keys() | expected.keys():
        target.execute('DELETE FROM qq_group_members WHERE account_id=? AND group_qq=?', (account_id, group))
        target.executemany('INSERT INTO qq_group_members VALUES(?,?,?,?,?,?,?)',
                           [(account_id, group, key, *value) for key, value in groups.get(group, {}).items()])
        target.execute('INSERT INTO qq_member_caches VALUES(?,?,?,?) ON CONFLICT(account_id,group_qq) DO UPDATE SET expected_count=excluded.expected_count,imported_at=excluded.imported_at',
                       (account_id, group, expected.get(group, 0), stamp))


def cache_info(service, account_id, conversation_id, platform='qq', conn=None):
    group = service._conversation(conversation_id, account_id, platform)
    if platform != 'qq' or group['kind'] != 'group':
        raise CoreError('GROUP_REQUIRED', '请选择QQ群聊。')
    if conn is None:
        with service.storage.connect() as connection:
            return cache_info(service, account_id, conversation_id, platform, connection)
    snapshot = conn.execute('SELECT * FROM qq_member_caches WHERE account_id=? AND group_qq=?', (account_id, group['peer_qq'])).fetchone()
    count = conn.execute('SELECT count(*) FROM qq_group_members WHERE account_id=? AND group_qq=?', (account_id, group['peer_qq'])).fetchone()[0]
    if not snapshot or not count:
        raise CoreError('MEMBER_CACHE_MISSING', '本群没有可导出的成员缓存。请在QQ客户端打开本群完整成员列表并滚动加载，然后完全退出QQ，在本软件更新记录。仅导入聊天库或旧版备份不能补齐成员缓存。')
    expected = snapshot['expected_count']
    note = ('缓存条数与群资料人数一致，但无法证明名单最新。' if count == expected else
            '缓存条数与群资料人数不一致，不能作为完整名单。' if expected else '群资料未提供可核对人数，完整性未核实。')
    return {'count': count, 'expected_count': expected, 'count_matches': count == expected,
            'imported_at': snapshot['imported_at'], 'group_qq': group['peer_qq'], 'note': note}


def merge_backup(target):
    for row in target.execute('SELECT * FROM incoming.qq_member_caches'):
        if not all(isinstance(row[k], str) and row[k] for k in ('account_id', 'group_qq', 'imported_at')) or type(row['expected_count']) is not int or row['expected_count'] < 0:
            raise ValueError('Invalid member cache')
        scope = (row['account_id'], row['group_qq'])
        old = target.execute('SELECT imported_at FROM qq_member_caches WHERE account_id=? AND group_qq=?', scope).fetchone()
        if old and old[0] >= row['imported_at']: continue
        target.execute('DELETE FROM qq_group_members WHERE account_id=? AND group_qq=?', scope)
        for member in target.execute('SELECT account_id,group_qq,identity_key,uid,qq,nickname,card FROM incoming.qq_group_members WHERE account_id=? AND group_qq=?', scope):
            if any(not isinstance(v, str) for v in member) or not member[2]: raise ValueError('Invalid member field')
            target.execute('INSERT INTO qq_group_members VALUES(?,?,?,?,?,?,?)', tuple(member))
        target.execute('INSERT OR REPLACE INTO qq_member_caches VALUES(?,?,?,?)', (*scope, row['expected_count'], row['imported_at']))
