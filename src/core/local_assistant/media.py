"""Local image resolution and portable, content-addressed image storage."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re

from .errors import CoreError

MAX_IMAGE = 32 << 20


def image_type(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png', '.png'
    if data.startswith(b'\xff\xd8\xff'): return 'image/jpeg', '.jpg'
    if data.startswith((b'GIF87a', b'GIF89a')): return 'image/gif', '.gif'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP': return 'image/webp', '.webp'
    if data.startswith(b'BM'): return 'image/bmp', '.bmp'
    return None


def media_identity(item):
    return ('md5', item['md5'].lower()) if item.get('md5') else ('name', item.get('filename'), item.get('width'), item.get('height'), item.get('local_path'))


def merge_media(old, new):
    result = [dict(item) for item in old if isinstance(item, dict)]
    for item in new:
        if not isinstance(item, dict): continue
        previous = next((value for value in result if media_identity(value) == media_identity(item)), None)
        if previous is None:
            result.append(dict(item))
        else:
            paths = list(dict.fromkeys(filter(None, [previous.get('local_path'), item.get('local_path'), *previous.get('local_paths', []), *item.get('local_paths', [])])))
            previous.update({key: value for key, value in item.items() if value and key not in ('asset_id',)})
            previous['local_paths'] = paths
    return result


class MediaStore:
    def __init__(self, service):
        self.service = service
        self.indices = {}

    def roots(self, account):
        with self.service.storage.connect() as conn:
            paths = [Path(row[0]) for row in conn.execute('SELECT path FROM media_roots WHERE account_id=?', (account,))]
            for row in conn.execute("SELECT DISTINCT source_path FROM imports WHERE platform='qq' AND account_id=?", (account,)):
                parent = Path(row[0]).parent
                paths.append(parent)
                if parent.name.lower() in ('nt_db', 'db', 'database'):
                    paths.append(parent.parent)
        return list(dict.fromkeys(path.resolve() for path in paths if path.is_dir()))

    def configure(self, account_id, path):
        if not account_id or not isinstance(path, str): raise CoreError('INVALID_PARAMS', '请先选择账号。')
        root = Path(path).expanduser().resolve()
        if not root.is_dir(): raise CoreError('SOURCE_NOT_FOUND', '图片缓存目录不存在。')
        with self.service.storage.connect() as conn:
            conn.execute('INSERT OR IGNORE INTO media_roots VALUES(?,?)', (account_id, str(root)))
        self.indices.pop(account_id, None)
        return {'configured': True}

    def index(self, account, roots):
        signature = tuple(str(root) for root in roots)
        cached = self.indices.get(account)
        if cached and cached[0] == signature: return cached[1]
        names = {}
        count = 0
        for root in roots:
            for current, directories, files in os.walk(root, followlinks=False):
                directories[:] = [name for name in directories if not (Path(current) / name).is_symlink()
                                    and not (Path(current) / name).is_junction() and name not in ('node_modules', '.git')]
                for name in files:
                    count += 1
                    if count > 100000: break
                    file = Path(current) / name
                    if file.is_symlink(): continue
                    names.setdefault(name.lower(), []).append(file)
                    for digest in re.findall(r'[0-9a-fA-F]{32}', name):
                        names.setdefault(digest.lower(), []).append(file)
                if count > 100000: break
            if count > 100000: break
        self.indices[account] = signature, names
        return names

    def resolve(self, message, item):
        roots = self.roots(message['account_id'])
        candidates = []
        for raw in [item.get('local_path'), *item.get('local_paths', [])]:
            if not raw or not isinstance(raw, str): continue
            file = Path(raw)
            if file.is_absolute(): candidates.append(file)
            normalized = raw.replace('\\', '/')
            for anchor in ('nt_data/', 'Pic/', 'Image/'):
                position = normalized.lower().find(anchor.lower())
                if position >= 0:
                    relative = normalized[position:]
                    candidates.extend(root / relative for root in roots)
        names = None
        for pass_number in (0, 1):
            if pass_number:
                names = self.index(message['account_id'], roots)
                for key in (item.get('md5', '').lower(), str(item.get('filename', '')).replace('\\', '/').rsplit('/', 1)[-1].lower()):
                    if key: candidates.extend(names.get(key, []))
            for file in dict.fromkeys(candidates):
                try:
                    resolved = file.resolve()
                    if not any(resolved.is_relative_to(root) for root in roots): continue
                    if not resolved.is_file() or resolved.stat().st_size > MAX_IMAGE: continue
                    data = resolved.read_bytes()
                    detected = image_type(data)
                    if detected: return data, detected[0]
                except OSError:
                    continue
        return None

    def get(self, message_id, media_index, account_id, platform='qq'):
        message = self.service._message(message_id, account_id, platform)
        media = json.loads(message['media_json'] or '[]')
        if type(media_index) is not int or not 0 <= media_index < len(media) or media[media_index].get('type') != 'image':
            raise CoreError('INVALID_PARAMS', '请选择消息中的图片。')
        with self.service.storage.connect() as conn:
            asset = conn.execute('SELECT a.sha256,a.mime,a.data FROM message_media r JOIN media_assets a ON a.sha256=r.sha256 WHERE r.message_id=? AND r.media_index=?', (message_id, media_index)).fetchone()
        if asset:
            return asset['sha256'], asset['mime'], asset['data']
        found = self.resolve(message, media[media_index])
        if not found: return None
        data, mime = found
        digest = hashlib.sha256(data).hexdigest()
        with self.service.storage.connect() as conn:
            conn.execute('INSERT OR IGNORE INTO media_assets VALUES(?,?,?)', (digest, mime, data))
            conn.execute('INSERT INTO message_media VALUES(?,?,?) ON CONFLICT(message_id,media_index) DO UPDATE SET sha256=excluded.sha256', (message_id, media_index, digest))
        return digest, mime, data

    def read(self, message_id, media_index, account_id, platform='qq'):
        asset = self.get(message_id, media_index, account_id, platform)
        if not asset: return {'available': False, 'message': '本机未找到可读取的图片，请在 QQ 中查看并下载后刷新缓存。'}
        return {'available': True, 'data_url': f'data:{asset[1]};base64,' + base64.b64encode(asset[2]).decode('ascii')}

    def save_favorite(self, asset):
        directory = self.service.data_dir / 'favorites' / 'media'
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (asset[0] + image_type(asset[2])[1])
        if not path.exists():
            temporary = path.with_suffix('.tmp')
            temporary.write_bytes(asset[2])
            os.replace(temporary, path)
        return path

