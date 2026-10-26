"""Inspect synthetic live-run coverage without copying chat bodies into evidence."""
import json,sqlite3,sys,zipfile
from pathlib import Path
from io import BytesIO
from xml.etree import ElementTree

root=Path(__file__).resolve().parents[1]/'build/live'
directory=Path(sys.argv[1]).resolve()
assert directory.parent==root.resolve() and directory.name.startswith('workspace-')
conn=sqlite3.connect(directory/'assistant.db');conn.row_factory=sqlite3.Row
run=conn.execute("SELECT * FROM workspace_runs WHERE id=? AND account_id='synthetic'",(sys.argv[2],)).fetchone()
assert run
context=json.loads(run['context_json']);ids=list(context.get('hashes',{}))
sources=[dict(r) for r in conn.execute(f"SELECT m.id,m.account_id,m.conversation_id,c.kind FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE m.id IN ({','.join('?' for _ in ids)})",ids)] if ids else []
assert all(r['account_id']=='synthetic' for r in sources)
events=json.loads(run['events_json']);names=[]
for file in conn.execute("SELECT mime,data FROM workspace_artifacts WHERE run_id=?",(run['id'],)):
    if file['mime']=='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
        with zipfile.ZipFile(BytesIO(file['data'])) as archive:
            xml=ElementTree.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            names=[t.text for t in xml.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t')]
print(json.dumps({'source_kinds':sorted({r['kind'] for r in sources}),'source_groups':sorted({r['conversation_id'] for r in sources}),'source_ids':sorted(ids),
                 'allowed_kinds':context.get('allowed_kinds',[]),'reused_messages':sum(e['result'].get('reused_messages',0) for e in events),'excel_names':names},ensure_ascii=True))
