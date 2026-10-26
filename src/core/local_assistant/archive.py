"""Consistent local SQLite archives. Never executes DDL from an imported file."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from .member_cache import merge_backup


class TransferError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def fingerprint(source):
    result = []
    for path in (source, Path(str(source) + "-wal")):
        if path.is_file():
            with path.open("rb") as stream:
                result.append(hashlib.file_digest(stream, "sha256").digest())
        else:
            result.append(None)
    return result


@contextmanager
def private_snapshot(source, data_dir):
    if not source.is_file():
        raise TransferError("SOURCE_NOT_FOUND", "所选数据库不存在。")
    if Path(str(source) + "-journal").exists():
        raise TransferError("SOURCE_BUSY", "源数据库正在写入，请关闭使用该库的程序后重试。")
    with tempfile.TemporaryDirectory(prefix="archive-", dir=data_dir) as folder:
        before = fingerprint(source)
        copied = Path(folder) / "snapshot.db"
        shutil.copyfile(source, copied)
        wal = Path(str(source) + "-wal")
        if wal.is_file():
            shutil.copyfile(wal, Path(str(copied) + "-wal"))
        if before != fingerprint(source) or Path(str(source) + "-journal").exists():
            raise TransferError("SOURCE_BUSY", "复制期间数据库发生变化，请关闭源程序后重试。")
        connection = sqlite3.connect(copied)
        try:
            connection.execute("PRAGMA trusted_schema=OFF")
            if connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
                raise TransferError("SOURCE_BUSY", "无法固定数据库快照。")
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise TransferError("ARCHIVE_INVALID", "数据库未通过完整性检查。")
        finally:
            connection.close()
        yield copied


def export_database(storage, path, progress):
    destination = Path(path).expanduser().resolve()
    if destination.exists() or any(Path(str(destination) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise TransferError("DESTINATION_EXISTS", "请使用新的文件名，导出不会覆盖已有数据库。")
    if destination.suffix.lower() != ".db":
        raise TransferError("INVALID_PARAMS", "导出文件请使用 .db 扩展名。")
    progress("正在生成包含所有账号的一致性数据库备份…")
    with tempfile.TemporaryDirectory(prefix="qq-export-", dir=destination.parent) as folder:
        output = Path(folder) / "archive.db"
        backup = sqlite3.connect(output)
        try:
            with storage.connect() as source:
                source.backup(backup, pages=2048)
            backup.execute("PRAGMA journal_mode=DELETE")
            backup.execute("CREATE TABLE IF NOT EXISTS archive_manifest(format_version INTEGER NOT NULL, exported_at TEXT NOT NULL)")
            backup.execute("DELETE FROM archive_manifest")
            backup.execute("INSERT INTO archive_manifest VALUES(1,?)", (datetime.now(timezone.utc).isoformat(),))
            backup.commit()
            count = backup.execute("SELECT count(*) FROM messages").fetchone()[0]
            if backup.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise TransferError("ARCHIVE_INVALID", "导出数据库未通过完整性检查。")
        finally:
            backup.close()
        # Windows rename and POSIX link both refuse to overwrite an existing file.
        if os.name == "nt":
            os.rename(output, destination)
        else:
            os.link(output, destination)
    return {"status": "exported", "format_version": 1, "message_count": count}


def import_database(storage, path, progress):
    from .media import media_identity, merge_media, image_type, MAX_IMAGE
    import json
    import re
    source = Path(path).expanduser().resolve()
    if source == storage.path.resolve():
        raise TransferError("SOURCE_INVALID", "该文件是当前正在使用的应用数据库，无需重复导入。")
    progress("正在固定并校验应用数据库快照…")
    with private_snapshot(source, storage.path.parent) as copied:
        with storage.connect() as target:
            target.execute("PRAGMA trusted_schema=OFF")
            target.execute("ATTACH DATABASE ? AS incoming", (str(copied),))
            tables = {row[0]: row[1] for row in target.execute("SELECT name,type FROM incoming.sqlite_master")}
            required = ("conversations", "messages", "qq_profiles", "qq_groups", "profile")
            if any(tables.get(name) != "table" for name in required):
                raise TransferError("ARCHIVE_INVALID", "该文件不是兼容的 QQ Insight 应用数据库，请选择正确的导入类型。")
            if "archive_manifest" in tables:
                versions = target.execute("SELECT format_version FROM incoming.archive_manifest").fetchall()
                if tables['archive_manifest'] != 'table' or len(versions) != 1 or versions[0][0] != 1:
                    raise TransferError("ARCHIVE_VERSION_UNSUPPORTED", "该备份格式版本不受支持。")
            defaults = {'source_digest':'', 'sync_key':'', 'reply_json':'[]', 'pinned':0, 'sender_nickname':'', 'sender_card':''}
            columns = {}
            for table in required:
                own = [row[1] for row in target.execute(f'PRAGMA main.table_info("{table}")')]
                incoming = {row[1] for row in target.execute(f'PRAGMA incoming.table_info("{table}")')}
                if set(own) - incoming - defaults.keys():
                    raise TransferError("ARCHIVE_INVALID", "应用数据库结构不兼容，未修改现有记录。")
                columns[table] = own
            optional = {'media_assets':{'sha256','mime','data'}, 'message_media':{'message_id','media_index','sha256'},
                        'favorites':{'message_id','media_index','created_at','asset_id'},
                        'conversation_preferences':{'conversation_id','role_text','updated_at'},
                        'message_variants':{'message_id','digest','text','media_json'},
                        'qq_member_caches':{'account_id','group_qq','expected_count','imported_at'},
                        'qq_group_members':{'account_id','group_qq','identity_key','uid','qq','nickname','card'}}
            for table, expected in optional.items():
                if table in tables and (tables[table] != 'table' or not expected.issubset({row[1] for row in target.execute(f'PRAGMA incoming.table_info("{table}")')})):
                    raise TransferError('ARCHIVE_INVALID','备份附加表结构无效。')
            invalid = target.execute("SELECT 1 FROM incoming.messages m LEFT JOIN incoming.conversations c ON c.id=m.conversation_id "
                "WHERE c.id IS NULL OR m.platform IS NOT c.platform OR m.account_id IS NOT c.account_id "
                "OR m.platform IS NOT 'qq' OR typeof(m.account_id)<>'text' OR m.account_id='' "
                "OR m.id IS NULL OR m.source_key IS NULL LIMIT 1").fetchone()
            if invalid or target.execute("SELECT 1 FROM incoming.conversations WHERE platform IS NOT 'qq' OR typeof(account_id)<>'text' OR account_id='' OR id IS NULL LIMIT 1").fetchone():
                raise TransferError("ARCHIVE_INVALID", "备份中的消息与账号归属不一致。")
            accounts = [row[0] for row in target.execute('SELECT DISTINCT account_id FROM incoming.conversations')]
            if ('qq_member_caches' in tables) != ('qq_group_members' in tables):
                raise TransferError('ARCHIVE_INVALID', '成员缓存备份不完整。')
            target.execute('BEGIN IMMEDIATE')
            conv_map={}
            for source_row in target.execute('SELECT * FROM incoming.conversations'):
                row=dict(source_row);old_id=row['id']
                existing=target.execute('SELECT * FROM conversations WHERE id=?',(row['id'],)).fetchone()
                if existing and (existing['account_id']!=row['account_id'] or existing['platform']!=row['platform']):
                    raise TransferError('ARCHIVE_CONFLICT','备份中的会话标识与现有账号冲突。')
                if existing: row['id']=existing['id']
                conv_map[old_id]=row['id']
                names=columns['conversations'];quoted=','.join(names)
                target.execute(f"INSERT INTO conversations({quoted}) VALUES({','.join('?' for _ in names)}) ON CONFLICT(id) DO UPDATE SET updated_at=max(conversations.updated_at,excluded.updated_at)",tuple(row.get(name,defaults.get(name)) for name in names))
            progress('正在合并消息、补齐正文和图片引用…')
            added=skipped=enriched=conflicts=0
            mappings={};media_maps={}
            names=columns['messages'];insert_sql=f"INSERT INTO messages({','.join(names)}) VALUES({','.join('?' for _ in names)})"
            cursor=target.execute('SELECT * FROM incoming.messages')
            timestamp=datetime.now(timezone.utc).isoformat()
            while batch:=cursor.fetchmany(400):
                fts=[]
                for source_row in batch:
                    row={**defaults,**dict(source_row)};old_id=row['id'];old_account=row['account_id']
                    row['conversation_id']=conv_map[row['conversation_id']]
                    existing=target.execute('SELECT * FROM messages WHERE id=? OR source_key=?',(row['id'],row['source_key'])).fetchone()
                    if existing and (existing['account_id']!=row['account_id'] or existing['platform']!=row['platform']):
                        raise TransferError('ARCHIVE_CONFLICT','备份中的消息标识与现有账号冲突。')
                    incoming_media=json.loads(row['media_json'] or '[]')
                    if not isinstance(incoming_media,list) or any(not isinstance(item,dict) for item in incoming_media): raise TransferError('ARCHIVE_INVALID','图片引用格式无效。')
                    if existing:
                        skipped+=1;message_id=existing['id']
                        merged=merge_media(json.loads(existing['media_json'] or '[]'),incoming_media)
                        changed=False
                        for name in ('sender_nickname', 'sender_card'):
                            if not existing[name] and row[name]:
                                target.execute(f'UPDATE messages SET {name}=? WHERE id=?', (row[name], message_id))
                                changed=True
                        if (not existing['text'] or existing['text'].startswith('[')) and row['text'] and not row['text'].startswith('['):
                            target.execute('UPDATE messages SET text=?,content_kind=?,parse_status=?,raw_blob=?,reply_json=? WHERE id=?',(row['text'],row['content_kind'],row['parse_status'],row['raw_blob'],row['reply_json'],message_id))
                            fts.append((message_id,row['text']));changed=True
                        elif row['text'] and not row['text'].startswith('[') and row['text']!=existing['text']:
                            digest=hashlib.sha256((row['text']+row['media_json']).encode()).hexdigest()
                            target.execute('INSERT OR IGNORE INTO message_variants VALUES(?,?,?,?)',(message_id,digest,row['text'],row['media_json']));conflicts+=1
                        if merged!=json.loads(existing['media_json'] or '[]'):
                            target.execute('UPDATE messages SET media_json=? WHERE id=?',(json.dumps(merged,ensure_ascii=False),message_id));changed=True
                        if changed:
                            enriched+=1
                            target.execute('INSERT INTO message_changes(platform,account_id,message_id,change_kind,imported_at) VALUES(?,?,?,?,?)',(row['platform'],row['account_id'],message_id,'updated',timestamp))
                    else:
                        message_id=row['id'];merged=incoming_media
                        target.execute(insert_sql,tuple(row[name] for name in names));added+=1;fts.append((message_id,row['text']))
                        target.execute('INSERT INTO message_changes(platform,account_id,message_id,change_kind,imported_at) VALUES(?,?,?,?,?)',(row['platform'],row['account_id'],message_id,'added',timestamp))
                    mappings[old_id]=message_id
                    indices={}
                    for index,item in enumerate(incoming_media):
                        match=next((i for i,value in enumerate(merged) if media_identity(value)==media_identity(item)),None)
                        if match is not None: indices[index]=match
                    media_maps[old_id]=indices
                storage.index_messages(target,fts)
            if 'qq_member_caches' in tables:
                merge_backup(target)
            for table in ('qq_profiles','qq_groups'):
                names=columns[table]
                for source_row in target.execute(f'SELECT * FROM incoming.{table}'):
                    row=dict(source_row)
                    target.execute(f"INSERT INTO {table}({','.join(names)}) VALUES({','.join('?' for _ in names)}) ON CONFLICT(account_id,identity_key) DO NOTHING",tuple(row[name] for name in names))
            target.execute("INSERT INTO main.profile(id,role_text,updated_at) SELECT id,role_text,updated_at FROM incoming.profile WHERE id=1 ON CONFLICT(id) DO UPDATE SET role_text=excluded.role_text,updated_at=excluded.updated_at WHERE profile.role_text=''")
            if 'conversation_preferences' in tables:
                for row in target.execute('SELECT * FROM incoming.conversation_preferences'):
                    if row['conversation_id'] in conv_map:
                        target.execute("INSERT INTO conversation_preferences VALUES(?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET role_text=excluded.role_text,updated_at=excluded.updated_at WHERE conversation_preferences.role_text=''",(conv_map[row['conversation_id']],row['role_text'],row['updated_at']))
            progress('正在合并收藏与可携带的图片…')
            if 'media_assets' in tables:
                for row in target.execute('SELECT * FROM incoming.media_assets'):
                    data=row['data'];detected=image_type(data) if isinstance(data,bytes) else None
                    if not detected or len(data)>MAX_IMAGE or hashlib.sha256(data).hexdigest()!=row['sha256'] or detected[0]!=row['mime']:
                        raise TransferError('ARCHIVE_INVALID','备份图片未通过类型或内容校验，本次合并已回滚。')
                    target.execute('INSERT OR IGNORE INTO media_assets VALUES(?,?,?)',(row['sha256'],row['mime'],data))
            if 'message_media' in tables:
                for row in target.execute('SELECT * FROM incoming.message_media'):
                    mapped=media_maps.get(row['message_id'],{}).get(row['media_index'])
                    if mapped is not None:
                        target.execute('INSERT OR IGNORE INTO message_media VALUES(?,?,?)',(mappings[row['message_id']],mapped,row['sha256']))
            if 'favorites' in tables:
                for row in target.execute('SELECT * FROM incoming.favorites'):
                    if row['message_id'] not in mappings: continue
                    index=-1 if row['media_index']==-1 else media_maps.get(row['message_id'],{}).get(row['media_index'])
                    if index is None: continue
                    if index>=0 and not target.execute('SELECT 1 FROM media_assets WHERE sha256=?',(row['asset_id'],)).fetchone():
                        raise TransferError('ARCHIVE_INVALID','图片收藏缺少图片数据，未宣称保存成功。')
                    target.execute('INSERT OR IGNORE INTO favorites VALUES(?,?,?,?)',(mappings[row['message_id']],index,row['created_at'],row['asset_id']))
            if 'message_variants' in tables:
                for row in target.execute('SELECT * FROM incoming.message_variants'):
                    if row['message_id'] in mappings:
                        target.execute('INSERT OR IGNORE INTO message_variants VALUES(?,?,?,?)',(mappings[row['message_id']],row['digest'],row['text'],row['media_json']))
            # Local backup restore: preserve existing state; never revive scheduled
            # network jobs merely because a database file was imported.
            def ai_evidence(value, conversation_id, cross_group=False):
                if not isinstance(value,dict):raise TransferError('ARCHIVE_INVALID','AI 结果格式无效。')
                ids=value.get('evidence_ids',[])
                if not isinstance(ids,list):raise TransferError('ARCHIVE_INVALID','AI 证据格式无效。')
                mapped=[]
                for key in ids:
                    message_id=mappings.get(key,key)
                    owner=target.execute('SELECT m.conversation_id,m.account_id,c.kind FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE m.id=?',(message_id,)).fetchone()
                    account=target.execute('SELECT account_id FROM conversations WHERE id=?',(conversation_id,)).fetchone()
                    if not owner or not account or (owner[0]!=conversation_id and not (cross_group and owner[1]==account[0] and owner[2]=='group')):raise TransferError('ARCHIVE_INVALID','AI 历史引用了其他群或不存在的消息。')
                    mapped.append(message_id)
                value['evidence_ids']=mapped
                return value

            ai_tables=('ai_group_settings','ai_jobs','ai_chunks','ai_items','ai_reports','ai_memories','ai_coverage','ai_budget_settings','ai_usage','ai_schedules')
            for table in ai_tables:
                if table not in tables: continue
                own=[row[1] for row in target.execute(f'PRAGMA main.table_info("{table}")')]
                incoming={row[1] for row in target.execute(f'PRAGMA incoming.table_info("{table}")')}
                optional_ai={'details_json':'{}','watch_target':'','media_results_json':'{}'}
                if tables[table]!='table' or not own or not set(own).issubset(incoming | optional_ai.keys()):
                    raise TransferError('ARCHIVE_INVALID','AI 历史表结构不兼容，未完成恢复。')
                for source_row in target.execute(f'SELECT * FROM incoming.{table}'):
                    row={**optional_ai,**dict(source_row)}
                    if 'conversation_id' in row:
                        if row['conversation_id'] not in conv_map: raise TransferError('ARCHIVE_INVALID','AI 历史引用了不存在的群。')
                        row['conversation_id']=conv_map[row['conversation_id']]
                    if table=='ai_jobs':
                        account=target.execute('SELECT account_id FROM conversations WHERE id=?',(row['conversation_id'],)).fetchone()[0]
                        if account!=row['account_id']:raise TransferError('ARCHIVE_INVALID','AI 任务账号范围无效。')
                        if row['status'] in ('running','queued'):row['status']='interrupted'
                    if table in ('ai_jobs','ai_items'):
                        existing=target.execute(f"SELECT conversation_id,feature FROM {table} WHERE id=?",(row['id'],)).fetchone()
                        if existing and (existing['conversation_id']!=row['conversation_id'] or existing['feature']!=row['feature']):
                            raise TransferError('ARCHIVE_CONFLICT','AI 历史标识与现有群或功能冲突。')
                    if table in ('ai_chunks','ai_reports'):
                        job=target.execute('SELECT conversation_id,feature FROM ai_jobs WHERE id=?',(row['job_id'],)).fetchone()
                        if not job:raise TransferError('ARCHIVE_INVALID','AI 历史缺少所属任务。')
                        if table=='ai_reports' and (row['conversation_id']!=job['conversation_id'] or row['feature']!=job['feature']):
                            raise TransferError('ARCHIVE_INVALID','AI 报告所属群或功能无效。')
                    if table=='ai_items':row['data_json']=json.dumps(ai_evidence(json.loads(row['data_json']),row['conversation_id'],row['feature']=='style'),ensure_ascii=False)
                    if table=='ai_memories':row['data_json']=json.dumps(ai_evidence(json.loads(row['data_json']),row['conversation_id'],row['kind']=='style'),ensure_ascii=False)
                    if table=='ai_reports':row['items_json']=json.dumps([ai_evidence(value,job['conversation_id'],job['feature']=='style') for value in json.loads(row['items_json'])],ensure_ascii=False)
                    if table=='ai_chunks':
                        messages=json.loads(row['messages_json'])
                        for value in messages:
                            key=value['id'];mapped=mappings.get(key,key)
                            ai_evidence({'evidence_ids':[mapped]},job['conversation_id'],job['feature']=='style');value['id']=mapped
                            value['conversation_id']=target.execute('SELECT conversation_id FROM messages WHERE id=?',(mapped,)).fetchone()[0]
                        row['messages_json']=json.dumps(messages,ensure_ascii=False)
                        result=json.loads(row['result_json'])
                        result['items']=[ai_evidence(value,job['conversation_id'],job['feature']=='style') for value in result.get('items',[])]
                        result['people_memory']=[ai_evidence(value,job['conversation_id'],job['feature']=='style') for value in result.get('people_memory',[])]
                        for memory in result.get('group_memory',[]):
                            if memory.get('conversation_id') not in conv_map:raise TransferError('ARCHIVE_INVALID','群记忆来源会话缺失。')
                            memory['conversation_id']=conv_map[memory['conversation_id']];ai_evidence(memory,memory['conversation_id'])
                        row['result_json']=json.dumps(result,ensure_ascii=False)
                        row['previous_json']=json.dumps([ai_evidence(value,job['conversation_id'],job['feature']=='style') for value in json.loads(row['previous_json'])],ensure_ascii=False)
                    if table=='ai_jobs':
                        coverage=json.loads(row['coverage_json'])
                        for name in ('previous','memory'):coverage[name]=[ai_evidence(value,row['conversation_id'],row['feature']=='style') for value in coverage.get(name,[])]
                        hashes={}
                        for key,value in coverage.get('hashes',{}).items():
                            mapped=mappings.get(key,key);ai_evidence({'evidence_ids':[mapped]},row['conversation_id'],row['feature']=='style');hashes[mapped]=value
                        coverage['hashes']=hashes;row['coverage_json']=json.dumps(coverage,ensure_ascii=False)
                    if table=='ai_coverage':
                        row['message_id']=mappings.get(row['message_id'],row['message_id'])
                        ai_evidence({'evidence_ids':[row['message_id']]},row['conversation_id'],row['feature']=='style')
                    if table=='ai_chunks' and row['status']=='running':row['status']='failed'
                    if table=='ai_usage' and row['status']=='reserved':row['status']='unknown'
                    if table=='ai_group_settings':
                        config=json.loads(row['settings_json']);config['schedule_minutes']=0;config['auto_favorite']=False
                        row['settings_json']=json.dumps(config,ensure_ascii=False)
                    target.execute(f"INSERT OR IGNORE INTO {table}({','.join(own)}) VALUES({','.join('?' for _ in own)})",tuple(row[name] for name in own))
            for table in ('workspace_runs','workspace_artifacts','ai_contexts'):
                if table not in tables:continue
                names=[r[1] for r in target.execute(f'PRAGMA main.table_info("{table}")')]
                incoming={r[1] for r in target.execute(f'PRAGMA incoming.table_info("{table}")')}
                if tables[table]!='table' or not set(names).issubset(incoming):raise TransferError('ARCHIVE_INVALID','工作区附加表不兼容。')
                for source_row in target.execute(f'SELECT * FROM incoming.{table}'):
                    row=dict(source_row)
                    if row['account_id'] not in accounts:raise TransferError('ARCHIVE_INVALID','工作区任务账号不存在。')
                    existing=target.execute(f'SELECT account_id FROM {table} WHERE id=?',(row['id'],)).fetchone()
                    if existing and existing[0]!=row['account_id']:raise TransferError('ARCHIVE_CONFLICT','工作区任务标识跨账号冲突。')
                    if table=='workspace_runs':
                        context=json.loads(row['context_json']);refs={};hashes={}
                        if not isinstance(context,dict):raise TransferError('ARCHIVE_INVALID','工作区上下文无效。')
                        fixed=context.get('conversation_id','')
                        if fixed:
                            mapped=conv_map.get(fixed,fixed);owner=target.execute('SELECT account_id FROM conversations WHERE id=?',(mapped,)).fetchone()
                            if not owner or owner[0]!=row['account_id']:raise TransferError('ARCHIVE_INVALID','工作区固定会话越出账号。')
                            context['conversation_id']=mapped
                        for key,value in context.get('hashes',{}).items():
                            mapped=mappings.get(key,key);owner=target.execute('SELECT account_id,conversation_id FROM messages WHERE id=?',(mapped,)).fetchone()
                            if not owner or owner[0]!=row['account_id']:raise TransferError('ARCHIVE_INVALID','工作区上下文越出账号。')
                            if fixed and owner[1]!=context['conversation_id']:raise TransferError('ARCHIVE_INVALID','工作区来源越出固定会话。')
                            hashes[mapped]=value
                        for alias,key in context.get('refs',{}).items():
                            mapped=mappings.get(key,key)
                            if mapped not in hashes:raise TransferError('ARCHIVE_INVALID','工作区来源编号缺少原记录。')
                            refs[alias]=mapped
                        context.update(refs=refs,hashes=hashes);row['context_json']=json.dumps(context,ensure_ascii=False)
                        if row['status']=='running':row['status']='interrupted'
                    elif table=='workspace_artifacts':
                        run=target.execute('SELECT account_id FROM workspace_runs WHERE id=?',(row['run_id'],)).fetchone()
                        if not run or run[0]!=row['account_id'] or len(row['data'])>8<<20:raise TransferError('ARCHIVE_INVALID','工作区文件归属或大小无效。')
                        from .workspace_agent import safe_name
                        row['filename']=safe_name(row['filename'])
                    else:
                        from .ai import MESSAGE_COLUMNS,projection
                        hashes=json.loads(row['hashes_json']);valid=True
                        for key,value in hashes.items():
                            current=target.execute(f'SELECT {MESSAGE_COLUMNS},account_id FROM messages WHERE id=?',(mappings.get(key,key),)).fetchone()
                            if not current or current['account_id']!=row['account_id'] or current['conversation_id']!=row['conversation_id'] or mappings.get(key,key)!=key:
                                valid=False;break
                            compact={k:current[k] for k in MESSAGE_COLUMNS.split(',')}
                            if projection(compact)['content_hash']!=value:valid=False;break
                        # Restored stale summaries are a cache miss, never rebound to changed content.
                        if not valid:continue
                        if row['conversation_id'] not in conv_map:raise TransferError('ARCHIVE_INVALID','压缩上下文来源群不存在。')
                        row['conversation_id']=conv_map[row['conversation_id']]
                    target.execute(f"INSERT OR IGNORE INTO {table}({','.join(names)}) VALUES({','.join('?' for _ in names)})",tuple(row[n] for n in names))
            for table in ('workspace_sessions','workspace_turns'):
                if table not in tables:continue
                names=[r[1] for r in target.execute(f'PRAGMA main.table_info("{table}")')]
                incoming={r[1] for r in target.execute(f'PRAGMA incoming.table_info("{table}")')}
                optional={'conversation_id'} if table=='workspace_sessions' else set()
                if tables[table]!='table' or not (set(names)-optional).issubset(incoming):raise TransferError('ARCHIVE_INVALID','对话表不兼容。')
                for source_row in target.execute(f'SELECT * FROM incoming.{table}'):
                    row=dict(source_row)
                    if table=='workspace_sessions':
                        row.setdefault('conversation_id','')
                        if row['conversation_id']:
                            row['conversation_id']=conv_map.get(row['conversation_id'],row['conversation_id'])
                            owner=target.execute('SELECT account_id FROM conversations WHERE id=?',(row['conversation_id'],)).fetchone()
                            if not owner or owner[0]!=row['account_id']:raise TransferError('ARCHIVE_INVALID','固定聊天会话越出账号。')
                        if row['account_id'] not in accounts or not isinstance(row['title'],str) or not 1<=len(row['title'])<=80:raise TransferError('ARCHIVE_INVALID','对话名称或账号无效。')
                        old=target.execute('SELECT account_id FROM workspace_sessions WHERE id=?',(row['id'],)).fetchone()
                        if old and old[0]!=row['account_id']:raise TransferError('ARCHIVE_CONFLICT','对话标识跨账号冲突。')
                    else:
                        owner=target.execute('SELECT account_id FROM workspace_sessions WHERE id=?',(row['session_id'],)).fetchone()
                        run=target.execute('SELECT account_id FROM workspace_runs WHERE id=?',(row['run_id'],)).fetchone()
                        old=target.execute('SELECT session_id,parent_id FROM workspace_turns WHERE run_id=?',(row['run_id'],)).fetchone()
                        if not owner or not run or owner[0]!=run[0] or row['parent_id']==row['run_id']:raise TransferError('ARCHIVE_INVALID','对话轮次归属无效。')
                        if old and tuple(old)!=(row['session_id'],row['parent_id']):raise TransferError('ARCHIVE_CONFLICT','同一任务不能属于另一个对话或分支。')
                    target.execute(f"INSERT OR IGNORE INTO {table}({','.join(names)}) VALUES({','.join('?' for _ in names)})",tuple(row[n] for n in names))
            from .workspace_agent import WorkspaceAgent,safe_name
            for row in target.execute('SELECT * FROM workspace_sessions'):
                links={turn['run_id']:dict(turn) for turn in target.execute('SELECT t.*,r.account_id,r.context_json,r.status FROM workspace_turns t JOIN workspace_runs r ON r.id=t.run_id WHERE t.session_id=?',(row['id'],))}
                if any(turn['status']!='deleted' and json.loads(turn['context_json']).get('conversation_id','')!=row['conversation_id'] for turn in links.values()):raise TransferError('ARCHIVE_INVALID','对话轮次与固定会话不一致。')
                if row['head_id'] and row['head_id'] not in links:raise TransferError('ARCHIVE_INVALID','对话当前分支不存在。')
                done=set()
                for key in links:
                    path=set()
                    while key and key not in done:
                        if key in path or key not in links or links[key]['account_id']!=row['account_id']:raise TransferError('ARCHIVE_INVALID','对话分支循环或越出账号。')
                        path.add(key);key=links[key]['parent_id']
                    done.update(path)
            from .chat_memory import SELF_DEFAULT,AGENT_DEFAULT,ChatMemory
            from .ai import MESSAGE_COLUMNS,projection,encode
            for table in ('account_self_profiles','conversation_agents','ai_message_memory','workspace_attachments','workspace_run_attachments'):
                if table not in tables:continue
                names=[r[1] for r in target.execute(f'PRAGMA main.table_info("{table}")')]
                incoming={r[1] for r in target.execute(f'PRAGMA incoming.table_info("{table}")')}
                if tables[table]!='table' or not set(names).issubset(incoming):raise TransferError('ARCHIVE_INVALID','会话记忆或附件表不兼容。')
                for source_row in target.execute(f'SELECT * FROM incoming.{table}'):
                    item=dict(source_row)
                    if table=='account_self_profiles' and isinstance(item.get('account_id'),str) and 1<=len(item['account_id'])<=128 and item['account_id'] not in accounts:accounts.append(item['account_id'])
                    if 'account_id' in item and item['account_id'] not in accounts:raise TransferError('ARCHIVE_INVALID','记忆或附件账号不存在。')
                    if table in ('account_self_profiles','conversation_agents'):
                        config=json.loads(item['settings_json']);allowed=SELF_DEFAULT if table=='account_self_profiles' else AGENT_DEFAULT
                        if not isinstance(config,dict) or set(config)-set(allowed) or any(type(value) is not bool if key=='remember' else not isinstance(value,str) or len(value)>6000 for key,value in config.items()):raise TransferError('ARCHIVE_INVALID','身份或Agent设置无效。')
                        if table=='conversation_agents':
                            item['conversation_id']=conv_map.get(item['conversation_id'],item['conversation_id'])
                            own=target.execute('SELECT account_id FROM conversations WHERE id=?',(item['conversation_id'],)).fetchone()
                            if not own:raise TransferError('ARCHIVE_INVALID','Agent来源会话不存在。')
                            learned=json.loads(item['learned_json'])
                            if not isinstance(learned,dict) or not isinstance(learned.get('prompt',''),str) or len(learned.get('prompt',''))>8000 or not isinstance(learned.get('evidence_ids',[]),list):raise TransferError('ARCHIVE_INVALID','Agent背景无效。')
                            valid=True
                            for key in learned.get('evidence_ids',[]):
                                owner=target.execute('SELECT account_id,conversation_id FROM messages WHERE id=?',(mappings.get(key,key),)).fetchone()
                                if not owner or tuple(owner)!=(own[0],item['conversation_id']):raise TransferError('ARCHIVE_INVALID','Agent背景来源越界。')
                                if mappings.get(key,key)!=key:valid=False
                            if not valid:item['learned_json']='{}'
                    elif table=='ai_message_memory':
                        mapped=mappings.get(item['message_id'],item['message_id'])
                        current=target.execute(f'SELECT {MESSAGE_COLUMNS},account_id FROM messages WHERE id=?',(mapped,)).fetchone()
                        if not current or current['account_id']!=item['account_id'] or current['conversation_id']!=conv_map.get(item['conversation_id'],item['conversation_id']):raise TransferError('ARCHIVE_INVALID','消息记忆来源越界。')
                        message=projection({k:current[k] for k in MESSAGE_COLUMNS.split(',')})
                        if message['content_hash']!=item['content_hash']:continue
                        item.update(message_id=mapped,conversation_id=current['conversation_id'],compact_json=encode(ChatMemory.compact(message)))
                    elif table=='workspace_attachments':
                        owner=target.execute('SELECT account_id FROM workspace_sessions WHERE id=?',(item['session_id'],)).fetchone()
                        if not owner or owner[0]!=item['account_id']:raise TransferError('ARCHIVE_INVALID','附件会话归属无效。')
                        old=target.execute('SELECT account_id,session_id FROM workspace_attachments WHERE id=?',(item['id'],)).fetchone()
                        if old and tuple(old)!=(item['account_id'],item['session_id']):raise TransferError('ARCHIVE_CONFLICT','附件标识归属冲突。')
                        try:WorkspaceAgent.validate_attachment(item['filename'],item['mime'],item['data'])
                        except Exception:raise TransferError('ARCHIVE_INVALID','附件内容或类型无效。')
                        item['filename']=safe_name(item['filename'])
                    else:
                        owner=target.execute('SELECT r.account_id,t.session_id FROM workspace_runs r JOIN workspace_turns t ON t.run_id=r.id WHERE r.id=?',(item['run_id'],)).fetchone()
                        attachment=target.execute('SELECT account_id,session_id FROM workspace_attachments WHERE id=?',(item['attachment_id'],)).fetchone()
                        if not owner or not attachment or tuple(owner)!=tuple(attachment):raise TransferError('ARCHIVE_INVALID','附件绑定越出当前对话。')
                    target.execute(f"INSERT OR IGNORE INTO {table}({','.join(names)}) VALUES({','.join('?' for _ in names)})",tuple(item[name] for name in names))
            WorkspaceAgent.migrate_sessions(target)
            return {'status':'merged','added':added,'skipped':skipped,'enriched':enriched,'conflicts':conflicts,'account_ids':sorted(set(accounts))}
