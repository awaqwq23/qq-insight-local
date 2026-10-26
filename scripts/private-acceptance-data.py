"""Explicit local acceptance support. Private rows stay under ignored data/, never stdout logs."""
from pathlib import Path
from contextlib import closing
from datetime import datetime,timezone,timedelta
import json,os,re,sqlite3,sys,zipfile
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/private-acceptance'
TZ=timezone(timedelta(hours=8))

def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def prepare():
    actual=Path(os.environ['APPDATA'])/'qq-insight-local'
    settings=json.loads((actual/'settings.json').read_text(encoding='utf-8'));account=settings['activeAccountId']
    folder=BASE/datetime.now(TZ).strftime('%Y-%m-%d_%H%M%S');folder.mkdir(parents=True)
    work=folder/'workspace';work.mkdir()
    with closing(sqlite3.connect((actual/'data/assistant.db').as_uri()+'?mode=ro',uri=True)) as source,closing(sqlite3.connect(work/'assistant.db')) as target:
        source.backup(target,pages=4096,sleep=.05)
    with closing(sqlite3.connect(work/'assistant.db')) as conn:
        conn.row_factory=sqlite3.Row
        groups=[dict(r) for r in conn.execute("SELECT c.id,c.title,c.peer_qq,count(*) messages,sum(length(m.text)>0) texts,max(m.sent_at) last FROM conversations c JOIN messages m ON m.conversation_id=c.id WHERE c.account_id=? AND c.kind='group' AND c.platform='qq' GROUP BY c.id ORDER BY messages DESC",(account,))]
        assert groups and groups[0]['messages']>=3000
        newest=conn.execute('SELECT max(sent_at) FROM messages WHERE account_id=?',(account,)).fetchone()[0]
        day=datetime.fromtimestamp(newest,TZ).replace(hour=0,minute=0,second=0,microsecond=0)
        start,end=int(day.timestamp()),int(day.timestamp())+86400
        scored=[]
        for group in groups:
            score=conn.execute("SELECT count(*) FROM messages WHERE conversation_id=? AND sent_at>=? AND (text LIKE '%作业%' OR text LIKE '%提交%' OR text LIKE '%截止%' OR text LIKE '%实验%' OR text LIKE '%会议%' OR text LIKE '%任务%')",(group['id'],newest-30*86400)).fetchone()[0]
            scored.append((score,group))
        work_group=max(scored,key=lambda x:x[0])[1]
        large=groups[0]
        people=[dict(r) for r in conn.execute("SELECT coalesce(nullif(sender_qq,''),sender_key) person,count(*) messages,count(DISTINCT conversation_id) conversations FROM messages WHERE account_id=? AND text<>'' AND coalesce(nullif(sender_qq,''),sender_key)<>'' AND coalesce(nullif(sender_qq,''),sender_key)<>? AND conversation_id IN (SELECT id FROM conversations WHERE account_id=? AND kind='group') GROUP BY person HAVING conversations>=2 AND messages>=30 ORDER BY messages DESC LIMIT 30",(account,account,account))]
        assert people;person=people[0]['person']
        private=conn.execute("SELECT c.id,c.title,c.peer_qq,count(*) messages,max(m.sent_at) last FROM conversations c JOIN messages m ON m.conversation_id=c.id WHERE c.account_id=? AND c.kind='c2c' AND m.text<>'' GROUP BY c.id ORDER BY last DESC,messages DESC LIMIT 1",(account,)).fetchone()
        assert private;private=dict(private)
        watch=conn.execute("SELECT coalesce(nullif(sender_qq,''),sender_key) FROM messages WHERE conversation_id=? AND text<>'' AND coalesce(nullif(sender_qq,''),sender_key)<>'' AND coalesce(nullif(sender_qq,''),sender_key)<>? GROUP BY 1 ORDER BY count(*) DESC LIMIT 1",(work_group['id'],account)).fetchone()[0]
        order_group=next((g for g in groups if conn.execute('SELECT count(*) FROM messages WHERE conversation_id=? AND sent_at>=? AND sent_at<?',(g['id'],start,end)).fetchone()[0]>=5),large)
        order=[r[0] for r in conn.execute("SELECT coalesce(nullif(sender_name,''),nullif(sender_qq,''),nullif(sender_key,''),'未知') FROM messages WHERE account_id=? AND conversation_id=? AND sent_at>=? AND sent_at<? ORDER BY sent_at,id",(account,order_group['id'],start,end))]
        counts={r[0]:r[1] for r in conn.execute("SELECT kind,count(*) FROM conversations WHERE account_id=? AND platform='qq' GROUP BY kind",(account,))}
        manifest={'account_id':account,'group':large,'work_group':work_group,'private':private,'person':person,'watch':watch,'day':day.strftime('%Y-%m-%d'),'start':start,'end':end,'latest':newest,'order_group':order_group,'expected_order':order,'counts':counts}
    write(folder/'范围与校验基准_个人资料.json',manifest)
    write(BASE/'latest.json',{'directory':str(folder)})
    (folder/'说明.txt').write_text('此目录含你已有聊天记录的只读副本及真实API分析结果，仅供本人查看。不要上传到仓库或作业。原软件记录和记忆未修改。\n',encoding='utf-8')
    print(json.dumps({'prepared':True,'group_messages':large['messages'],'order_rows':len(order),'day':manifest['day']}))

def inspect():
    arg=json.load(sys.stdin);folder=Path(arg['directory']).resolve();assert folder.is_relative_to(BASE.resolve())
    manifest=json.loads((folder/'范围与校验基准_个人资料.json').read_text(encoding='utf-8'))
    with closing(sqlite3.connect(folder/'workspace/assistant.db')) as c:
        c.row_factory=sqlite3.Row
        out={}
        if arg.get('case_job'):
            case=arg['case_job'];row=c.execute("SELECT id,status FROM ai_jobs WHERE account_id=? AND conversation_id=? AND feature=? AND json_extract(options_json,'$.goal') LIKE ? ORDER BY created_at DESC LIMIT 1",(manifest['account_id'],case['conversation_id'],case['feature'],'真实记录验收：'+case['name']+' %')).fetchone();out=dict(row) if row else {}
        if arg.get('recovery_run'):
            row=c.execute("SELECT r.id run_id,t.session_id,r.status FROM workspace_runs r JOIN workspace_turns t ON t.run_id=r.id WHERE r.id=? AND r.account_id=? AND r.status='completed'",(arg['recovery_run'],manifest['account_id'])).fetchone();out=dict(row) if row else {}
        if arg.get('failed_feature'):
            row=c.execute("SELECT id FROM ai_jobs WHERE account_id=? AND feature=? AND status='failed' ORDER BY updated_at DESC LIMIT 1",(manifest['account_id'],arg['failed_feature'])).fetchone()
            out={'job_id':row[0] if row else ''}
        if arg.get('run_id'):
            row=c.execute('SELECT * FROM workspace_runs WHERE id=?',(arg['run_id'],)).fetchone();context=json.loads(row['context_json']);answer=json.loads(row['answer_json']);refs=list(context.get('refs',{}).values())
            sources=[dict(r) for r in c.execute('SELECT id,conversation_id,sender_name,sender_qq,sender_key,text,sent_at,direction FROM messages WHERE id IN (SELECT value FROM json_each(?))',(json.dumps(refs),))]
            events=json.loads(row['events_json']);out={'status':row['status'],'answer':answer,'sources':sources,'events':events,'source_count':len(sources),'source_groups':list({r['conversation_id'] for r in sources})}
        if arg.get('job_id'):
            row=c.execute('SELECT * FROM ai_reports WHERE job_id=?',(arg['job_id'],)).fetchone()
            if row:
                items=json.loads(row['items_json']);ids=list({key for item in items for key in item.get('evidence_ids',[])})
                sources=[dict(r) for r in c.execute('SELECT id,conversation_id,sender_name,text,sent_at FROM messages WHERE id IN (SELECT value FROM json_each(?))',(json.dumps(ids),))]
                out={'summary':row['summary'],'items':items,'coverage':json.loads(row['coverage_json']),'sources':sources}
        if arg.get('review_job_id'):
            job=c.execute('SELECT settings_json,coverage_json FROM ai_jobs WHERE id=? AND account_id=?',(arg['review_job_id'],manifest['account_id'])).fetchone()
            report=c.execute('SELECT summary,items_json FROM ai_reports WHERE job_id=?',(arg['review_job_id'],)).fetchone();coverage=json.loads(job['coverage_json'])
            ids=list(coverage['hashes']);rows=[dict(r) for r in c.execute('SELECT id,sender_qq,sender_key,sender_name,text,direction FROM messages WHERE id IN (SELECT value FROM json_each(?)) ORDER BY sent_at,id',(json.dumps(ids),))]
            aliases={r['id']:'s'+str(i) for i,r in enumerate(rows)};items=json.loads(report['items_json']);used={k for item in items for k in item['evidence_ids']}
            for item in items:item['evidence_ids']=[aliases[k] for k in item['evidence_ids'] if k in aliases]
            settings=json.loads(job['settings_json']);out={'job_id':arg['review_job_id'],'summary':report['summary'],'items':items,'manual_corrections':[{k:m[k] for k in ('subject','body','correction') if k in m} for m in coverage.get('memory',[]) if m.get('locked') or m.get('correction') or m.get('from_user')],'user_settings':{k:settings[k] for k in ['role','role_source','effective_role','category','self_names','instructions','interests'] if k in settings},'sources':[{**r,'id':aliases[r['id']]} for r in rows if r['id'] in used],
                'all_scope_sources':[[aliases[r['id']],r['sender_qq'] or r['sender_key'],r['text'],r['direction']=='outgoing'] for r in rows],'scope_messages':len(rows),'all_scope_columns':['id','sender','text','is_self'],'notice':'sources为引用条目的完整原文，all_scope_sources补充整个分析范围的材料。草稿及原创示例不是原话；暂定推测不等于已确认事实。用户手动设定也可能不是聊天正文。'}
            for size in [1000,500,200,80]:
                if len(json.dumps(out,ensure_ascii=False).encode())<=750000:break
                out['all_scope_sources']=[[aliases[r['id']],r['sender_qq'] or r['sender_key'],r['text'][:size],r['direction']=='outgoing'] for r in rows];out['notice']+=' 汇总材料有节选，节选未出现不能证明不存在；sources仍为完整原文。'
        if arg.get('memory'):
            cid=arg['memory'];out={'contexts':c.execute('SELECT count(*) FROM ai_contexts WHERE account_id=? AND conversation_id=?',(manifest['account_id'],cid)).fetchone()[0],
                'message_memory':c.execute('SELECT count(*) FROM ai_message_memory WHERE account_id=? AND conversation_id=?',(manifest['account_id'],cid)).fetchone()[0],
                'people_memory':c.execute("SELECT count(*) FROM ai_memories WHERE conversation_id=? AND kind='person'",(cid,)).fetchone()[0],
                'group_memory':c.execute("SELECT count(*) FROM ai_memories WHERE conversation_id=? AND kind='group'",(cid,)).fetchone()[0],
                'learned':bool(c.execute('SELECT learned_json FROM conversation_agents WHERE conversation_id=?',(cid,)).fetchone())}
        if arg.get('xlsx'):
            file=Path(arg['xlsx']);assert file.resolve().is_relative_to(folder)
            with zipfile.ZipFile(file) as z:
                doc=ET.fromstring(z.read('xl/worksheets/sheet1.xml'));names=[''.join(n.itertext()) for n in doc.findall('.//{*}t')]
            expected=[r[0] for r in c.execute("SELECT coalesce(nullif(sender_name,''),nullif(sender_qq,''),nullif(sender_key,''),'未知') FROM messages WHERE account_id=? AND conversation_id=? AND sent_at>=? AND sent_at<? ORDER BY sent_at,id",(manifest['account_id'],manifest['order_group']['id'],manifest['start'],manifest['end']))]
            out={'ok':names==['人名',*expected],'rows':len(names)-1,'expected':len(expected)}
        if arg.get('quote_file'):
            file=Path(arg['quote_file']);assert file.resolve().is_relative_to(folder)
            text=file.read_text(encoding='utf-8');blocks=[m[1] for m in re.findall(r'^(`{3,})\n(.*?)\n\1(?:\n|$)',text,re.M|re.S)]
            rows=[dict(r) for r in c.execute("SELECT m.id,m.text,m.direction,m.sender_qq,m.sender_key,m.conversation_id,m.sent_at FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE m.account_id=? AND c.kind='c2c' AND m.sent_at>=? AND m.sent_at<? ORDER BY m.conversation_id,m.sent_at,m.id",(manifest['account_id'],manifest['start'],manifest['end']))]
            texts={r['text'] for r in rows};own={manifest['account_id']};profile=c.execute('SELECT settings_json FROM account_self_profiles WHERE account_id=?',(manifest['account_id'],)).fetchone()
            if profile:own.update(v for k,v in json.loads(profile[0]).items() if k in ('qq','uid') and v)
            is_self=lambda r:r['direction']=='outgoing' or r['sender_qq'] in own or r['sender_key'] in own
            expected=[]
            for i,r in enumerate(rows):
                if not is_self(r) or not re.search(r'互问|提.{0,3}问|问我|想问|一个问题',r['text']):continue
                following=[s for s in rows[i+1:] if s['conversation_id']==r['conversation_id']]
                for j,q in enumerate(following):
                    if is_self(q) or not re.search(r'[？?]|什么|哪|怎么|为什么|是否|能不能',q['text']):continue
                    answers=[]
                    for a in following[j+1:]:
                        if not is_self(a):break
                        if a['text']:answers.append(a['text'])
                    if answers:expected.append([q['text'],*answers])
                    break
            out={'blocks':len(blocks),'all_verbatim':bool(blocks) and all(b in texts for b in blocks),'expected_pairs':len(expected),'covered_pairs':sum(all(t in blocks for t in pair) for pair in expected)}
    print(json.dumps(out,ensure_ascii=False))

def finalize():
    folder=Path(json.loads((BASE/'latest.json').read_text(encoding='utf-8'))['directory']).resolve()
    assert folder.is_relative_to(BASE.resolve())
    report=json.loads((folder/'测试汇总.json').read_text(encoding='utf-8'))
    spend=json.loads((folder/'费用保护与用量.json').read_text(encoding='utf-8'))
    assert all(r['state']!='reserved' for r in spend['requests'])
    cost=sum(r['cost_upper'] for r in spend['requests']);assert cost<5
    latest={o['name']:o for o in report['outcomes']};passed=sum(o['ok'] for o in latest.values())
    total=len(latest)
    with closing(sqlite3.connect(folder/'workspace/assistant.db')) as conn:
        for name,outcome in latest.items():
            key=outcome.get('job_id') or outcome.get('run_id')
            models=sorted({json.loads(r[0]).get('model','') for r in conn.execute('SELECT details_json FROM ai_usage WHERE job_id=?',(key,))}-{''}) if key else []
            if not models and outcome.get('job_id'):
                row=conn.execute('SELECT model_json FROM ai_jobs WHERE id=?',(key,)).fetchone()
                if row:models=[json.loads(row[0]).get('model','未记录')]
            outcome['generation_models']=models or [outcome.get('model','未记录')]
            outcome['verification_model']=outcome.get('model') if name.startswith('预设_') else None
    subscription_file=folder/'订阅额度与用量.json'
    subscription=json.loads(subscription_file.read_text(encoding='utf-8')) if subscription_file.exists() else {'requests':[]}
    assert not any(r['state']=='reserved' for r in subscription['requests'])
    lines=['# QQ Insight 真实聊天记录测试报告','',f'2026-10-26；{report["version"]}候选修复版，使用官方deepseek-flash及国内MiniMax-M3订阅。',
        f'共{total}项，{passed}项程序验收通过，{total-passed}项未通过。逐项以最近一次结果为准，不能说两个模型各自全部通过。',
        f'本轮DeepSeek累计{len(spend["requests"])}次推理尝试；费用保守上界 **{cost:.6f}元**，低于用户本轮另行授权的5元上限。预占保护线4.75元，未知用量仍按原预占保留。此前另一轮4.475644元单独保留，未清零或合并冒充5元内。',
        f'MiniMax订阅共{len(subscription["requests"])}次推理尝试，用量及窗口/周额度见订阅额度与用量.json。仅用订阅密钥，不切换余额密钥；订阅不等于无限资源。',
        f'期间账户余额累计下降{spend["account_decrease"]:.6f}元；余额可能延迟，不能据此声称免费，最终扣费以服务商账单为准。',
        '', '真实导入数据库的独立副本用于测试，原软件记录、记忆及设置未修改。此目录包含私人结果、来源和工作数据库，请勿上传。',
        '', '生成模型按本地任务计量确认；复核重用既有结果时，不能把复核模型记作生成模型。画像的MiniMax复核曾给出失败，但理由未指出明确矛盾；随后DeepSeek对同一结果交叉复核通过，两份意见均保留。',
        '', '| 用例 | 最新状态 | 生成／复核模型 | 最近一次实际失败 | 可用结果 |','| --- | --- | --- | --- | --- |']
    for name,o in latest.items():
        failures=[a.get('code','未知') for a in report['outcomes'] if a['name']==name and not a['ok'] and a.get('code')!='NOT_RUN_BUDGET']
        result=folder/(name+'_分析结果_个人.json');link='无'
        if result.exists():
            data=json.loads(result.read_text(encoding='utf-8'));body=data.get('summary') or data.get('answer',{}).get('answer','')
            text=['# '+name,'','此为最近一次可用模型结果，不代表该用例已通过；状态请看总报告。','',str(body)]
            for item in data.get('items',[]):text.extend(['','## '+item.get('title','条目'),item.get('body','')]);text.extend(item.get('drafts',[]))
            md=folder/(name+'_可读结果.md');md.write_text('\n'.join(text)+'\n',encoding='utf-8');link=f'[查看]({md.name})'
        state='通过程序校验' if o['ok'] else '复测因预算停止' if o.get('code')=='NOT_RUN_BUDGET' else '未通过：'+o.get('code','未知')
        model='/'.join(o['generation_models'])+('；复核'+o['verification_model'] if o['verification_model'] else '；程序核验')
        lines.append(f'| {name} | {state} | {model} | {failures[-1] if failures else "无"} | {link} |')
    qa_file=folder/'私聊问答逐字与覆盖核对.json'
    qa=json.loads(qa_file.read_text(encoding='utf-8')) if qa_file.exists() else {'blocks':0}
    lines.extend(['','## 已核对的具体结果','',
        '- 画像用例选取3000条真实消息，包含27位在范围内发言的人；逐人阶段画像、已有内容持续完善、证据范围及模型复核以该项最新状态为准。证据不足只记录待补或发言节选，不编造稳定人格，模型复核不等于真人验证。',
        '- 发言顺序Excel共197行，与原记录按时间及本地ID排序逐行一致。同秒真实细序仍受原数据精度限制。',
        f'- 私聊原话MD的{qa["blocks"]}段正文均与源库逐字吻合。本地启发式没有找到可用基准问答，不能证明全部应选问答均被找到或所有段落均相关。',
        '- 三类记忆在测试副本中存在，会话概括、人物观察、消息记忆及压缩复用有实际记录；未修改日常软件记忆。',
        '- 五张表情包用例'+('已完成实际像素判断、保存和去重核验，达到明确数量。' if latest.get('全局_保存五张真实表情',{}).get('ok') else '尚未通过，不能标完成。'),
        '- 指定日期重点改用该日实际有记录的群，日期范围由程序生成；'+('实际复测通过。' if latest.get('群聊_历史日期重点',{}).get('ok') else '复测尚未通过。'),
        '', '## 免费回归与修复','',
        '0.18.0补充单成员/全体阶段画像、成功分块立即保存、历史报告混入修复、人物短编号恢复、手动身份保护、去除内存内部字段膨胀、分群压缩容错、图片适合时受控保存、跨群风格受控工具及官方DeepSeek JSON模式。',
        '免费回归及最终发布验证见项目docs/verification.md；它们不冒充真实模型语义通过。',
        '', '## 完整尝试记录','', '| 序号 | 用例 | 状态 | 调用次数 |','| --- | --- | --- | --- |'])
    for i,o in enumerate(report['outcomes'],1):lines.append(f'| {i} | {o["name"]} | {"通过" if o["ok"] else o.get("code","未通过")} | {o.get("calls",0)} |')
    lines.extend(['','JSON原结果、复核意见、失败原因、费用保护与独立数据库均保留在此目录。初期JSON结果部分被后续同名结果替换，原分析任务仍保留在workspace数据库；后期另存历史JSON。不要将一次有限测试解读为所有模型回复永远正确。'])
    (folder/'测试结果报告.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    usage={name:{'attempts':len(ledger['requests']),'measured_tokens':sum(r.get('input_tokens',0)+r.get('output_tokens',0) for r in ledger['requests']),'unknown_attempts':sum(r['state']=='unknown' for r in ledger['requests'])} for name,ledger in [('deepseek',spend),('minimax_subscription',subscription)]}
    report.update(cost_upper_cny=cost,passed_cases=passed,total_cases=total,all_passed=passed==total,deepseek_attempts=len(spend['requests']),subscription_attempts=len(subscription['requests']),provider_usage=usage,calls=sum(v['attempts'] for v in usage.values()),tokens=sum(v['measured_tokens'] for v in usage.values()),models=sorted({o.get('model','未记录') for o in latest.values()}),latest_cases=list(latest.values()))
    write(folder/'测试汇总.json',report)
    auth=folder/'.auth/Local State'
    if auth.exists():auth.unlink()
    print(json.dumps({'passed':passed,'total':total,'cost_upper_cny':round(cost,6),'requests':len(spend['requests']),'subscription_requests':len(subscription['requests'])}))


try:
    if '--prepare' in sys.argv:prepare()
    elif '--report' in sys.argv:finalize()
    else:inspect()
except Exception as error:
    print(json.dumps({'error':type(error).__name__}));sys.exit(1)
