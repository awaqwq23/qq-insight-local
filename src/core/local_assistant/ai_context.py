"""Verified local summaries. Exact queries always use the original message index."""
import json,re
from .ai_prompts import encode
from .ai_compression import pack
SMALL_CONTEXT_BYTES=16000


def candidates(conn,account_id,selected,reuse_key=None,min_savings=0):
    hashes={m['id']:m['content_hash'] for m in selected};used=set();found=[]
    # shortcut: newest 300 summaries per lookup; add a coverage index if large histories require it.
    for row in conn.execute("SELECT * FROM ai_contexts WHERE account_id=? ORDER BY (feature='context') DESC,updated_at DESC LIMIT 300",(account_id,)):
        if reuse_key is not None and row['reuse_key']!=reuse_key:continue
        covered=json.loads(row['hashes_json'])
        if not covered or set(covered).issubset(used) or any(hashes.get(key)!=value for key,value in covered.items()):continue
        result=json.loads(row['result_json'])
        if not isinstance(result,dict) or not isinstance(result.get('summary'),str) or not isinstance(result.get('items'),list):continue
        texts=[result['summary'],*[str(v.get('body','')) for field in ('items','people_memory','group_memory') for v in (result.get(field,[]) if isinstance(result.get(field,[]),list) else []) if isinstance(v,dict)]]
        opaque=set(re.findall(r'(?<![A-Za-z0-9_])p\d+(?![A-Za-z0-9_])','\n'.join(texts)))
        if any(not any(m.get('sender_name')==alias or re.search(r'(?<![A-Za-z0-9_])'+re.escape(alias)+r'(?![A-Za-z0-9_])',m.get('text','')) for m in selected if m['id'] in covered) for alias in opaque):continue
        safe=True
        for field in ('items','people_memory','group_memory'):
            values=result.get(field,[])
            if not isinstance(values,list):safe=False;break
            for value in values:
                if not isinstance(value,dict) or not isinstance(value.get('evidence_ids'),list) or any(not isinstance(key,str) or key not in covered for key in value['evidence_ids']):safe=False;break
        if not safe:continue
        original=pack([m for m in selected if m['id'] in covered and m['id'] not in used],'off',True)[0]
        saved=len(encode(original).encode())-len(encode(result).encode())
        if min_savings is not None and saved<=min_savings:continue
        found.append({**dict(row),'hashes':covered,'result':result,'estimated_saved_bytes':saved});used.update(covered)
    return found,used


def save(conn,account_id,conversation_id,feature,reuse_key,messages,result,stamp,digest):
    if not messages:return
    hashes={m['id']:m['content_hash'] for m in messages}
    key=digest([account_id,feature,reuse_key,hashes])
    conn.execute('''INSERT INTO ai_contexts VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    result_json=excluded.result_json,updated_at=excluded.updated_at''',
                 (key,account_id,conversation_id,feature,reuse_key,encode(hashes),encode(result),stamp,stamp))
