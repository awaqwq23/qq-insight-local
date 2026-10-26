"""CSV exports; network access and website credentials stay in Electron."""
import csv
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import tempfile
import re

from .errors import CoreError
from .member_cache import cache_info


def _cell(value):
    value = str(value or '')
    # CSV quoting alone does not prevent spreadsheet formula execution.
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')) else value


def roster_scope(service, account_id, conversation_id, platform='qq'):
    if platform != 'qq' or not isinstance(account_id, str) or not re.fullmatch(r'[1-9][0-9]{4,19}', account_id):
        raise CoreError('INVALID_PARAMS', '全体成员导出需要选择真实 QQ 号对应的账号。')
    group = service._conversation(conversation_id, account_id, platform)
    if group['kind'] != 'group' or not re.fullmatch(r'[1-9][0-9]{4,19}', group['peer_qq']):
        raise CoreError('GROUP_REQUIRED', '该会话缺少有效群号，请先更新 QQ 记录。')
    return {'account_id': account_id, 'group_qq': group['peer_qq'], 'title': group['display_name'] or group['title']}


def export_roster(service, path, account_id, kind, conversation_id, platform, online=None, cache_stamp=None):
    if platform != 'qq' or not isinstance(account_id, str) or not account_id.strip() or kind not in ('groups', 'members', 'full_members', 'cached_members'):
        raise CoreError('INVALID_PARAMS', '请选择 QQ 账号和有效的名单类型。')
    if not isinstance(path, str) or not path or Path(path).suffix.lower() != '.csv':
        raise CoreError('INVALID_PARAMS', '名单导出请使用 .csv 扩展名。')
    if kind in ('members', 'full_members', 'cached_members'):
        group = service._conversation(conversation_id, account_id, platform)
        if group['kind'] != 'group':
            raise CoreError('GROUP_REQUIRED', '请选择一个群聊。')
    destination = Path(path).expanduser().resolve()
    if destination.exists():
        raise CoreError('DESTINATION_EXISTS', '请使用新文件名，名单导出不会覆盖已有文件。')
    try:
        with service.storage.connect() as conn:
            conn.execute('BEGIN')
            if kind == 'groups':
                header = ['群号', '群原名称', '群备注名称', '历史显示名称', '数据范围']
                groups = {}
                for row in conn.execute("SELECT * FROM qq_groups WHERE account_id=? ORDER BY identity_key", (account_id,)):
                    key = row['group_qq'] or row['group_uid'] or row['identity_key']
                    groups[key] = [row['group_qq'], row['name'], row['remark'], '', '本地群资料']
                for row in conn.execute("SELECT * FROM conversations WHERE account_id=? AND platform=? AND kind='group' ORDER BY id", (account_id, platform)):
                    key = row['peer_qq'] or row['peer_uid'] or row['id']
                    if key in groups:
                        groups[key][3] = row['display_name'] or row['title']
                    else:
                        groups[key] = [row['peer_qq'], '', '', row['display_name'] or row['title'], '本地会话；未缓存群原名和备注']
                rows = list(groups.values())
                note = '仅导出当前账号本地已导入的群，不代表 QQ 全部群。'
            elif kind == 'cached_members':
                info = cache_info(service, account_id, conversation_id, platform, conn)
                if cache_stamp is not None and cache_stamp != info['imported_at']:
                    raise CoreError('MEMBER_CACHE_CHANGED', '成员缓存刚刚更新，请重新导出并核对人数。')
                header = ['群号', '群显示名称', 'QQ号', 'UID', 'QQ原昵称', '群名片（群内备注）', '缓存条数', '群资料人数', '缓存导入时间', '完整性说明']
                rows = [[info['group_qq'], group['display_name'] or group['title'], r['qq'], r['uid'], r['nickname'], r['card'], info['count'], info['expected_count'], info['imported_at'], info['note']]
                        for r in conn.execute('SELECT * FROM qq_group_members WHERE account_id=? AND group_qq=? ORDER BY identity_key', (account_id, info['group_qq']))]
                note = info['note'] + ' 已导出独立成员缓存，包含未发言者；不与历史发言名单混合。'
            elif kind == 'full_members':
                scope = roster_scope(service, account_id, conversation_id, platform)
                if not isinstance(online, dict) or online.get('account_id') != account_id or online.get('group_qq') != scope['group_qq']:
                    raise CoreError('ROSTER_SCOPE_INVALID', '官网名单与当前账号或群不一致，未导出。')
                items, count = online.get('members'), online.get('count')
                if type(count) is not int or not 1 <= count <= 100000 or not isinstance(items, list) or len(items) != count:
                    raise CoreError('ROSTER_INCOMPLETE', '官网成员数量未核对一致，未导出不完整名单。')
                rows, seen = [], set()
                stamp = datetime.now(timezone.utc).isoformat()
                for member in items:
                    if (not isinstance(member, dict) or not isinstance(member.get('qq'), str)
                            or not re.fullmatch(r'[1-9][0-9]{4,19}', member['qq']) or member['qq'] in seen
                            or any(not isinstance(member.get(key), str) or len(member[key]) > 1000 for key in ('nickname', 'card'))):
                        raise CoreError('ROSTER_INCOMPLETE', '官网名单含重复身份或无效姓名字段，未导出。')
                    seen.add(member['qq'])
                    rows.append([scope['group_qq'], scope['title'], member['qq'], '', member['nickname'], member['card'], '', 'QQ群官网：本次分页人数核对一致', stamp])
                header = ['群号', '群显示名称', 'QQ号', 'UID', 'QQ原昵称', '群名片（群内备注）', '历史显示名称', '数据范围', '导出时间（UTC）']
                note = '已从QQ群官网读取并核对全部分页，包含未发言成员；名单可能随成员进退变化。'
            else:
                header = ['群号', '群显示名称', 'QQ号', 'UID', 'QQ原昵称', '群名片（群内备注）', '历史显示名称', '数据范围']
                profiles = {}
                for row in conn.execute('SELECT * FROM qq_profiles WHERE account_id=? ORDER BY identity_key', (account_id,)):
                    for key in (row['uid'], row['qq']):
                        if key:
                            profiles[key] = row
                members = {}
                uid_numbers = {}
                for row in conn.execute("SELECT DISTINCT sender_key,sender_qq FROM messages WHERE account_id=? AND platform=? AND conversation_id=? AND sender_key<>'' AND sender_qq<>''", (account_id, platform, conversation_id)):
                    uid_numbers.setdefault(row['sender_key'], set()).add(row['sender_qq'])
                # Old rows without separated names stay unknown until source reimport.
                for row in conn.execute("SELECT sender_key,sender_qq,sender_name,sender_nickname,sender_card FROM messages WHERE account_id=? AND platform=? AND conversation_id=? AND direction<>'system' ORDER BY sent_at DESC,id DESC", (account_id, platform, conversation_id)):
                    uid, qq = row['sender_key'] or '', row['sender_qq']
                    profile = profiles.get(uid) or profiles.get(qq)
                    qq = qq or (profile['qq'] if profile else '')
                    numbers = uid_numbers.get(uid, set())
                    if not qq and len(numbers) == 1: qq = next(iter(numbers))
                    if not uid and not qq:
                        continue
                    key = ('qq', qq) if qq else ('uid', uid)
                    member = members.setdefault(key, [group['peer_qq'], group['display_name'] or group['title'], qq, uid, '', '', '', '已导入聊天中的发言成员，非完整／实时群成员名单'])
                    if not member[4]: member[4] = row['sender_nickname']
                    if not member[5]: member[5] = row['sender_card']
                    if not member[6]: member[6] = row['sender_name']
                for member in members.values():
                    profile = profiles.get(member[3]) or profiles.get(member[2])
                    if not member[4] and profile:
                        member[4] = profile['nickname']
                rows = list(members.values())
                note = '仅含已导入聊天中的发言成员，可能含已退群成员；昵称和群名片取最近非空缓存，不代表实时状态。缺失字段留空；旧数据请先重新导入或更新 QQ 记录。'
        with tempfile.TemporaryDirectory(prefix='roster-', dir=destination.parent) as folder:
            staged = Path(folder) / 'roster.csv'
            with staged.open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(header)
                writer.writerows([_cell(cell) for cell in row] for row in rows)
            if os.name == 'nt':
                os.rename(staged, destination)
            else:
                os.link(staged, destination)
        return {'status': 'exported', 'count': len(rows), 'kind': kind, 'note': note}
    except FileExistsError as exc:
        raise CoreError('DESTINATION_EXISTS', '目标文件已存在，请使用新文件名。') from exc
    except (OSError, sqlite3.Error) as exc:
        raise CoreError('EXPORT_FAILED', '名单导出失败，请检查目标目录权限和空间。') from exc
