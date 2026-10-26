"""Real packaged stdio export, with synthetic group names only."""
import csv
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    source = root / 'synthetic.db'
    conn = sqlite3.connect(source)
    for table in ('c2c_msg_table', 'group_msg_table'):
        conn.execute(f'CREATE TABLE {table}("40001","40011","40012","40013","40020","40021","40030","40033","40050","40800","40090","40093")')
    conn.execute('INSERT INTO group_msg_table VALUES(1,2,0,0,"synthetic-user","synthetic-group",900001,100001,1700000000,NULL,"合成群名片","合成QQ昵称")')
    conn.commit()
    conn.close()
    metadata = root/'group_info.db'
    conn=sqlite3.connect(metadata)
    conn.execute('CREATE TABLE group_detail_info_ver1("60001","60007","60006")')
    conn.execute('INSERT INTO group_detail_info_ver1 VALUES(900001,"合成群",2)')
    conn.execute('CREATE TABLE group_member3("60001","1000","1002","20002","64003")')
    conn.executemany('INSERT INTO group_member3 VALUES(900001,?,?,?,?)',[('synthetic-user',100001,'合成QQ昵称','合成群名片'),('silent',100002,'未发言缓存昵称','未发言缓存群名片')])
    conn.commit();conn.close()
    requests = [
        ('source.import', {'path':str(source),'account_id':'synthetic','companion_paths':{'group_info.db':str(metadata)}}),
        ('roster.export', {'path':str(root/'members.csv'),'account_id':'synthetic','kind':'members','conversation_id':'qq:synthetic:group:synthetic-group'}),
        ('roster.export', {'path':str(root/'groups.csv'),'account_id':'synthetic','kind':'groups'}),
        ('roster.export', {'path':str(root/'blocked.csv'),'account_id':'other','kind':'members','conversation_id':'qq:synthetic:group:synthetic-group'}),
        ('source.import', {'path':str(source),'account_id':'10000001'}),
        ('roster.scope', {'account_id':'10000001','conversation_id':'qq:10000001:group:synthetic-group'}),
        ('roster.export', {'path':str(root/'full.csv'),'account_id':'10000001','kind':'full_members','conversation_id':'qq:10000001:group:synthetic-group',
                          'online':{'account_id':'10000001','group_qq':'900001','count':1,'members':[{'qq':'10000999','nickname':'未发言的合成成员','card':'全体名单群名片'}]}}),
        ('roster.cache_info',{'account_id':'synthetic','conversation_id':'qq:synthetic:group:synthetic-group'}),
        ('roster.export',{'path':str(root/'cache.csv'),'account_id':'synthetic','kind':'cached_members','conversation_id':'qq:synthetic:group:synthetic-group'}),
    ]
    payload = ''.join(json.dumps({'jsonrpc':'2.0','id':i,'method':method,'params':params})+'\n' for i,(method,params) in enumerate(requests))
    run = subprocess.run(['build/core/qq-insight-core.exe','--data-dir',str(root/'app')],input=payload,capture_output=True,encoding='utf-8',timeout=60,check=True)
    responses = {x['id']:x for line in run.stdout.splitlines() if 'id' in (x:=json.loads(line))}
    assert responses[1]['result']['count'] == responses[2]['result']['count'] == 1
    assert 'error' in responses[3] and not (root/'blocked.csv').exists()
    with (root/'members.csv').open(encoding='utf-8-sig',newline='') as stream:
        member = next(csv.DictReader(stream))
    assert member['QQ原昵称'] == '合成QQ昵称'
    assert member['群名片（群内备注）'] == '合成群名片'
    assert responses[5]['result']['group_qq'] == '900001'
    assert responses[6]['result']['count'] == 1
    with (root/'full.csv').open(encoding='utf-8-sig',newline='') as stream:
        silent = next(csv.DictReader(stream))
    assert silent['QQ号'] == '10000999' and silent['QQ原昵称'] == '未发言的合成成员'
    assert silent['群名片（群内备注）'] == '全体名单群名片'
    assert responses[7]['result']['count']==responses[7]['result']['expected_count']==responses[8]['result']['count']==2
    with (root/'cache.csv').open(encoding='utf-8-sig',newline='') as stream: cached=list(csv.DictReader(stream))
    assert any(row['QQ原昵称']=='未发言缓存昵称' and row['群名片（群内备注）']=='未发言缓存群名片' for row in cached)
print('Packaged roster passed: dual names, account isolation, independent native cache including silent members and real CSV.')
