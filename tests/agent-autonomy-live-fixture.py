"""Synthetic old clarification history; never reads the user's QQ workspace."""
from pathlib import Path
import json,runpy,sys
root=Path(__file__).resolve().parents[1];directory=sys.argv[1]
sys.argv=[str(root/'tests/workspace-fixture.py'),directory,'--autonomy']
runpy.run_path(sys.argv[0],run_name='__main__')
sys.path.insert(0,str(root/'src/core'))
from local_assistant.service import AssistantService
app=AssistantService(Path(directory));session=''
for question in ('给我提取今天我请别人提问后，私聊中对方的问题和我的回答，原封不动做成md文件','继续'):
    turn=app.workspace_agent.begin('synthetic',question,session_id=session);session=turn['session_id']
    with app.storage.connect() as conn:conn.execute("UPDATE workspace_runs SET status='completed',answer_json=? WHERE id=?",(json.dumps({'answer':'合成旧回答：联系人很多，请确认只要一人还是今天所有的。'}),turn['run_id']))
(Path(directory)/'synthetic-session.json').write_text(json.dumps({'session_id':session}),encoding='utf-8')
