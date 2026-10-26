SCHEMA = '''
CREATE TABLE IF NOT EXISTS ai_contexts (
 id TEXT PRIMARY KEY, account_id TEXT NOT NULL, conversation_id TEXT NOT NULL REFERENCES conversations(id),
 feature TEXT NOT NULL, reuse_key TEXT NOT NULL, hashes_json TEXT NOT NULL, result_json TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_ai_contexts_scope ON ai_contexts(account_id,conversation_id,updated_at DESC);
CREATE TABLE IF NOT EXISTS workspace_runs (
 id TEXT PRIMARY KEY, account_id TEXT NOT NULL, question TEXT NOT NULL, status TEXT NOT NULL,
 events_json TEXT NOT NULL, context_json TEXT NOT NULL, answer_json TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS workspace_artifacts (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES workspace_runs(id), account_id TEXT NOT NULL,
 filename TEXT NOT NULL, mime TEXT NOT NULL, data BLOB NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workspace_sessions (
 id TEXT PRIMARY KEY, account_id TEXT NOT NULL, title TEXT NOT NULL, head_id TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_workspace_sessions_account ON workspace_sessions(account_id,updated_at DESC);
CREATE TABLE IF NOT EXISTS workspace_turns (
 run_id TEXT PRIMARY KEY REFERENCES workspace_runs(id), session_id TEXT NOT NULL REFERENCES workspace_sessions(id),
 parent_id TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_workspace_turns_session ON workspace_turns(session_id);
CREATE TABLE IF NOT EXISTS account_self_profiles (
 account_id TEXT PRIMARY KEY, settings_json TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conversation_agents (
 conversation_id TEXT PRIMARY KEY REFERENCES conversations(id), settings_json TEXT NOT NULL DEFAULT '{}',
 learned_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ai_message_memory (
 message_id TEXT PRIMARY KEY REFERENCES messages(id), account_id TEXT NOT NULL,
 conversation_id TEXT NOT NULL REFERENCES conversations(id), content_hash TEXT NOT NULL,
 compact_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_message_memory_scope ON ai_message_memory(account_id,conversation_id);
CREATE TRIGGER IF NOT EXISTS invalidate_message_memory AFTER UPDATE OF
 sent_at,sender_name,sender_qq,sender_key,text,media_json,reply_json,direction,content_kind,conversation_id,account_id ON messages
 WHEN OLD.sent_at IS NOT NEW.sent_at OR OLD.sender_name IS NOT NEW.sender_name OR OLD.sender_qq IS NOT NEW.sender_qq
 OR OLD.sender_key IS NOT NEW.sender_key OR OLD.text IS NOT NEW.text OR OLD.media_json IS NOT NEW.media_json
 OR OLD.reply_json IS NOT NEW.reply_json OR OLD.direction IS NOT NEW.direction OR OLD.content_kind IS NOT NEW.content_kind
 OR OLD.conversation_id IS NOT NEW.conversation_id OR OLD.account_id IS NOT NEW.account_id
 BEGIN
 DELETE FROM ai_message_memory WHERE message_id=NEW.id;
 UPDATE conversation_agents SET learned_json='{}' WHERE conversation_id=NEW.conversation_id OR conversation_id=OLD.conversation_id;
 END;
CREATE TABLE IF NOT EXISTS workspace_attachments (
 id TEXT PRIMARY KEY, account_id TEXT NOT NULL, session_id TEXT NOT NULL REFERENCES workspace_sessions(id),
 filename TEXT NOT NULL, mime TEXT NOT NULL, data BLOB NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workspace_run_attachments (
 run_id TEXT NOT NULL REFERENCES workspace_runs(id), attachment_id TEXT NOT NULL REFERENCES workspace_attachments(id),
 PRIMARY KEY(run_id,attachment_id));
CREATE TABLE IF NOT EXISTS ai_group_settings (
 conversation_id TEXT PRIMARY KEY REFERENCES conversations(id), settings_json TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ai_jobs (
 id TEXT PRIMARY KEY, account_id TEXT NOT NULL, conversation_id TEXT NOT NULL REFERENCES conversations(id), feature TEXT NOT NULL,
 status TEXT NOT NULL, fingerprint TEXT NOT NULL, context_key TEXT NOT NULL, model_json TEXT NOT NULL, settings_json TEXT NOT NULL,
 options_json TEXT NOT NULL, coverage_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_ai_jobs_scope ON ai_jobs(account_id,conversation_id,feature,created_at DESC);
CREATE TABLE IF NOT EXISTS ai_chunks (
 job_id TEXT NOT NULL REFERENCES ai_jobs(id), idx INTEGER NOT NULL, status TEXT NOT NULL, messages_json TEXT NOT NULL,
 result_json TEXT NOT NULL DEFAULT '{}', attempt TEXT NOT NULL DEFAULT '', PRIMARY KEY(job_id,idx));
CREATE TABLE IF NOT EXISTS ai_coverage (
 conversation_id TEXT NOT NULL, feature TEXT NOT NULL, message_id TEXT NOT NULL, digest TEXT NOT NULL, context_key TEXT NOT NULL,
 PRIMARY KEY(conversation_id,feature,message_id));
CREATE TABLE IF NOT EXISTS ai_items (
 id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id), feature TEXT NOT NULL, item_key TEXT NOT NULL,
 data_json TEXT NOT NULL, user_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(conversation_id,feature,item_key));
CREATE INDEX IF NOT EXISTS idx_ai_items_group ON ai_items(conversation_id,feature,updated_at DESC);
CREATE TABLE IF NOT EXISTS ai_reports (
 job_id TEXT PRIMARY KEY REFERENCES ai_jobs(id), conversation_id TEXT NOT NULL, feature TEXT NOT NULL, summary TEXT NOT NULL,
 items_json TEXT NOT NULL, coverage_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ai_memories (
 conversation_id TEXT NOT NULL REFERENCES conversations(id), memory_key TEXT NOT NULL, kind TEXT NOT NULL,
 subject TEXT NOT NULL DEFAULT 'group', feature TEXT NOT NULL, data_json TEXT NOT NULL,
 source_job_id TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(conversation_id,memory_key));
CREATE INDEX IF NOT EXISTS idx_ai_memories_scope ON ai_memories(conversation_id,kind,subject,updated_at DESC);
CREATE TABLE IF NOT EXISTS ai_budget_settings (id INTEGER PRIMARY KEY CHECK(id=1), config_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ai_usage (
 attempt TEXT PRIMARY KEY, job_id TEXT NOT NULL, chunk_idx INTEGER NOT NULL, day TEXT NOT NULL, month TEXT NOT NULL,
 reserved INTEGER NOT NULL, charged INTEGER NOT NULL, cost REAL, status TEXT NOT NULL,
 input_tokens INTEGER, output_tokens INTEGER, request_id TEXT NOT NULL DEFAULT '', prices_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_ai_usage_day ON ai_usage(day);
CREATE TABLE IF NOT EXISTS ai_schedules (
 conversation_id TEXT PRIMARY KEY, next_at INTEGER NOT NULL DEFAULT 0, feature TEXT NOT NULL DEFAULT 'work');
'''

DEFAULT_GROUP = {'category':'未分类','role':'','role_source':'legacy','self_names':'','watch_people':[], 'watch_keywords':[],
                 'interests':'','instructions':'','remember':True,'images':False,'image_model':'','auto_favorite':False,
                 'favorite_daily_limit':10,'favorite_storage_mb':200,'schedule_minutes':0,'schedule_feature':'work',
                 'compression':'off','output_chars':500,'hierarchical':False}
DEFAULT_BUDGET = {'per_run_tokens':100000,'daily_tokens':300000,'monthly_tokens':3000000,
                  'output_tokens':65536,'chunk_chars':10000,'monthly_cost':0,'input_price':None,'output_price':None,'currency':'CNY','price_model':''}
BUDGET_LIMITS = {
    'per_run_tokens':{'min':1000,'max':10000000,'label':'单次分析 Token 上限'},
    'daily_tokens':{'min':1000,'max':100000000,'label':'每日 Token 上限'},
    'monthly_tokens':{'min':1000,'max':1000000000,'label':'每月 Token 上限'},
    'output_tokens':{'min':512,'max':1000000,'label':'单段最大输出 Token'},
    'chunk_chars':{'min':2000,'max':20000,'label':'分块字符数'},
}
