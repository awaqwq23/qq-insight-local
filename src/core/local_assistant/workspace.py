from datetime import datetime, timezone
import json

from .errors import CoreError


class WorkspaceFeatures:
    def _self_ids(self, conn, account):
        profile=self.chat_memory.self_profile(account)
        values={account,profile['qq'],profile['uid']}-{''}
        pairs=conn.execute('SELECT qq,uid FROM qq_profiles WHERE account_id=? AND (qq=? OR uid=?)',(account,profile['qq'] or account,profile['uid'] or account)).fetchall()
        values.update(v for pair in pairs for v in pair if v)
        return values

    def _message(self, message_id, account_id, platform='qq'):
        if not account_id: raise CoreError('INVALID_PARAMS', '请先选择账号。')
        with self.storage.connect() as conn:
            row = conn.execute('SELECT * FROM messages WHERE id=? AND account_id=? AND platform=?', (message_id, account_id, platform)).fetchone()
        if not row: raise CoreError('NOT_FOUND', '当前账号中找不到这条消息。')
        return dict(row)

    def _conversation(self, conversation_id, account_id, platform='qq'):
        if not account_id: raise CoreError('INVALID_PARAMS', '请先选择账号。')
        with self.storage.connect() as conn:
            row = conn.execute('SELECT * FROM conversations WHERE id=? AND account_id=? AND platform=?', (conversation_id, account_id, platform)).fetchone()
        if not row: raise CoreError('NOT_FOUND', '当前账号中找不到这个会话。')
        return dict(row)

    def _message_items(self, conn, rows):
        rows = list(rows)
        if not rows: return []
        ids = [row['id'] for row in rows]
        favorites = {(row[0], row[1]) for row in conn.execute(f"SELECT message_id,media_index FROM favorites WHERE message_id IN ({','.join('?' for _ in ids)})", ids)}
        compressed={r['message_id']:r for r in conn.execute(f"SELECT message_id,content_hash,updated_at FROM ai_message_memory WHERE message_id IN ({','.join('?' for _ in ids)})",ids)}
        items = []
        identities={}
        for row in rows:
            item = {key: row[key] for key in ('id','conversation_id','sent_at','direction','sender_key','sender_qq','sender_name','text','content_kind','parse_status','title')}
            account=row['account_id']
            if account not in identities:identities[account]=self._self_ids(conn,account)
            item['is_self']=item['direction']!='system' and (item['direction']=='outgoing' or bool({item['sender_qq'],item['sender_key']}&identities[account]))
            if item['is_self'] and item['direction']!='system':item['direction']='outgoing'
            try: item['media'] = json.loads(row['media_json'] or '[]')
            except (ValueError, TypeError): item['media'] = []
            try: item['replies'] = json.loads(row['reply_json'] or '[]')
            except (ValueError, TypeError, IndexError): item['replies'] = []
            item['favorite'] = (item['id'], -1) in favorites
            saved=compressed.get(item['id'])
            if saved and self.chat_memory.enabled(conn,item['conversation_id']):
                from .ai import projection,MESSAGE_COLUMNS
                if projection({k:row[k] for k in MESSAGE_COLUMNS.split(',')})['content_hash']==saved['content_hash']:item['memory']={'compressed':True,'updated_at':saved['updated_at']}
            for index, media in enumerate(item['media']): media['favorite'] = (item['id'], index) in favorites
            items.append(item)
        return items

    def message_context(self, message_id, account_id, platform='qq', limit=50, order='asc'):
        if type(limit) is not int or not 10 <= limit <= 500 or order not in ('asc','desc'):
            raise CoreError('INVALID_PARAMS', '上下文参数无效。')
        message = self._message(message_id, account_id, platform)
        conversation = self._conversation(message['conversation_id'], account_id, platform)
        with self.storage.connect() as conn:
            select = 'SELECT m.*,c.title FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE m.conversation_id=? AND m.account_id=? AND m.platform=? '
            params = (conversation['id'], account_id, platform, message['sent_at'], message_id)
            before = conn.execute(select + 'AND (m.sent_at,m.id)<(?,?) ORDER BY m.sent_at DESC,m.id DESC LIMIT ?', (*params,limit//2)).fetchall()
            after = conn.execute(select + 'AND (m.sent_at,m.id)>=(?,?) ORDER BY m.sent_at,m.id LIMIT ?', (*params,limit-limit//2)).fetchall()
            rows = sorted([*before,*after],key=lambda row:(row['sent_at'],row['id']),reverse=order=='desc')
            return {'items': self._message_items(conn, rows), 'target_id':message_id, 'conversation':conversation, 'variants':[dict(row) for row in conn.execute('SELECT text FROM message_variants WHERE message_id=?', (message_id,))]}

    def pin_conversation(self, conversation_id, pinned, account_id, platform='qq'):
        self._conversation(conversation_id, account_id, platform)
        if type(pinned) is not bool: raise CoreError('INVALID_PARAMS', '置顶参数无效。')
        with self.storage.connect() as conn: conn.execute('UPDATE conversations SET pinned=? WHERE id=?', (int(pinned),conversation_id))
        return {'pinned':pinned}

    def set_favorite(self, message_id, enabled, account_id, platform='qq', media_index=-1):
        self._message(message_id, account_id, platform)
        if type(enabled) is not bool or type(media_index) is not int or media_index < -1:
            raise CoreError('INVALID_PARAMS', '收藏参数无效。')
        asset_id = ''
        if enabled and media_index >= 0:
            asset = self.media_store.get(message_id, media_index, account_id, platform)
            if not asset: raise CoreError('MEDIA_MISSING', '图片在本机不可用，未加入图片收藏。请先在 QQ 中下载图片后刷新缓存。')
            self.media_store.save_favorite(asset)
            asset_id = asset[0]
        with self.storage.connect() as conn:
            if enabled:
                conn.execute('INSERT INTO favorites VALUES(?,?,?,?) ON CONFLICT(message_id,media_index) DO NOTHING',
                             (message_id,media_index,datetime.now(timezone.utc).isoformat(),asset_id))
            else:
                conn.execute('DELETE FROM favorites WHERE message_id=? AND media_index=?', (message_id,media_index))
        return {'favorite':enabled, 'media_index':media_index, 'saved_image': bool(asset_id)}

    def list_favorites(self, account_id, platform='qq', query='', kind='', limit=100, offset=0, order='desc'):
        if not account_id or type(limit) is not int or not 1<=limit<=500 or type(offset) is not int or offset<0 or kind not in ('','message','image') or order not in ('asc','desc'):
            raise CoreError('INVALID_PARAMS','收藏查询参数无效。')
        where = 'm.platform=? AND m.account_id=?'
        params = [platform,account_id]
        if kind: where += ' AND f.media_index' + ('=-1' if kind=='message' else '>=0')
        pattern = self._like(query)
        if query.strip():
            where += " AND (m.text LIKE ? ESCAPE '!' OR c.title LIKE ? ESCAPE '!' OR m.sender_name LIKE ? ESCAPE '!' OR m.sender_qq LIKE ? ESCAPE '!')"
            params.extend([pattern]*4)
        sort = 'ASC' if order == 'asc' else 'DESC'
        with self.storage.connect() as conn:
            rows = conn.execute(f'SELECT m.*,c.title,f.media_index AS favorite_media_index,f.created_at FROM favorites f JOIN messages m ON m.id=f.message_id JOIN conversations c ON c.id=m.conversation_id WHERE {where} ORDER BY m.sent_at {sort},m.id {sort},f.media_index LIMIT ? OFFSET ?', (*params,limit+1,offset)).fetchall()
            items = self._message_items(conn,rows[:limit])
            for item,row in zip(items,rows): item.update(favorite_media_index=row['favorite_media_index'],created_at=row['created_at'])
        return {'items':items,'has_more':len(rows)>limit,'next_offset':offset+limit if len(rows)>limit else None}

    def read_media(self, **params): return self.media_store.read(**params)

    def configure_media_roots(self, account_id, path): return self.media_store.configure(account_id,path)

    def refresh_media(self, account_id):
        self.media_store.indices.pop(account_id,None)
        return {'refreshed':True}

    def repair_messages(self, account_id, platform='qq'):
        from .protocol import decode_message_details
        from .media import merge_media
        if not account_id: raise CoreError('INVALID_PARAMS','请先选择账号。')
        changed = 0
        with self.storage.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            cursor = conn.execute('SELECT id,text,outer_type,raw_blob,media_json,reply_json FROM messages WHERE account_id=? AND platform=?', (account_id,platform))
            while rows := cursor.fetchmany(400):
                updates=[];fts=[]
                for row in rows:
                    if not row['raw_blob']: continue
                    details=decode_message_details(row['raw_blob'],int(row['outer_type'] or 0))
                    text=details['text']
                    if row['text'] and not row['text'].startswith('[') and text.startswith('['): text=row['text']
                    media=json.dumps(merge_media(json.loads(row['media_json'] or '[]'),details['media']),ensure_ascii=False)
                    replies=json.dumps(details.get('replies') or json.loads(row['reply_json'] or '[]'),ensure_ascii=False)
                    if (text,media,replies)==(row['text'],row['media_json'],row['reply_json']): continue
                    updates.append((text,details['content_kind'],media,replies,row['id']))
                    fts.append((row['id'],text))
                conn.executemany('UPDATE messages SET text=?,content_kind=?,media_json=?,reply_json=? WHERE id=?',updates)
                self.storage.index_messages(conn,fts)
                changed+=len(updates)
        return {'updated':changed}
