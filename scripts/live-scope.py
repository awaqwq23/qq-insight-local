"""Read only scope metadata for opt-in acceptance; stdout is consumed privately by the runner."""
import json, sqlite3, sys
from pathlib import Path
db=Path(sys.argv[1])/'assistant.db'
if '--restore' in sys.argv:
    state=json.load(sys.stdin)
    with sqlite3.connect(db) as conn:
        for table,column,value in [('ai_group_settings','conversation_id',state['conversation_id']),('conversation_preferences','conversation_id',state['conversation_id']),('ai_schedules','conversation_id',state['conversation_id']),('ai_budget_settings','id',1)]:
            conn.execute(f'DELETE FROM {table} WHERE {column}=?',(value,))
            row=state['original'][table]
            if row:conn.execute(f"INSERT INTO {table}({','.join(row)}) VALUES({','.join('?' for _ in row)})",tuple(row.values()))
    raise SystemExit(0)
conn=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)
conn.row_factory=sqlite3.Row
query=json.load(sys.stdin)
hint=query.get('scope_hint',{})
if not hint.get('contains'):raise SystemExit(2)
rows=conn.execute("SELECT id,account_id FROM conversations WHERE kind='group' AND title LIKE ? AND title LIKE ?",('%'+hint['contains']+'%','%'+hint.get('secondary','')+'%')).fetchall()
if len(rows)!=1:raise SystemExit(2)
if conn.execute("SELECT count(*) FROM ai_jobs WHERE status IN ('running','queued')").fetchone()[0]:raise SystemExit(3)
scope=dict(rows[0]);scope['conversation_id']=scope.pop('id')
scope['total']=conn.execute('SELECT count(*) FROM messages WHERE conversation_id=? AND account_id=?',(scope['conversation_id'],scope['account_id'])).fetchone()[0]
scope['original']={}
if query.get('resume_profile'):
    job=conn.execute("SELECT id FROM ai_jobs WHERE conversation_id=? AND account_id=? AND feature='summary' AND status IN ('failed','interrupted','cancelled') AND json_extract(model_json,'$.id')=? AND json_extract(options_json,'$.compression')=? ORDER BY created_at DESC LIMIT 1",(scope['conversation_id'],scope['account_id'],query['resume_profile'],query.get('compression','strong'))).fetchone()
    if not job:raise SystemExit(4)
    scope['resume_job']=job[0]
for table,column,value in [('ai_group_settings','conversation_id',scope['conversation_id']),('conversation_preferences','conversation_id',scope['conversation_id']),('ai_schedules','conversation_id',scope['conversation_id']),('ai_budget_settings','id',1)]:
    row=conn.execute(f'SELECT * FROM {table} WHERE {column}=?',(value,)).fetchone()
    scope['original'][table]=dict(row) if row else None
print(json.dumps(scope))
