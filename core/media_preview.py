"""Resolve one verified message's local media, with bounded browser responses."""
import base64
import hashlib
import io
import json
from pathlib import Path
from PIL import Image

from .data import FIELDS
from .resources import ResourceStore
from .avatars import image_type


def preview(archive, library, payload, destination, cancel):
    session = payload.get('session')
    if session not in {row['username'] for row in archive.sessions()}:
        raise ValueError('会话不存在。')
    shard, local_id = payload.get('shard'), payload.get('local_id')
    if not isinstance(shard, int) or not 0 <= shard < len(archive.data.msg_dbs) or not isinstance(local_id, int):
        raise ValueError('消息定位信息无效。')
    connection = archive.data.msg_dbs[shard]
    table = archive.data.msg_table_for(session)
    if table not in archive.data.tables_of(connection):
        raise ValueError('消息不存在。')
    columns = {row[1] for row in connection.execute('PRAGMA table_info("' + table + '")')}
    select = ','.join('"' + name + '"' if name in columns else 'NULL AS "' + name + '"' for name in FIELDS)
    row = connection.execute('SELECT ' + select + ' FROM "' + table + '" WHERE local_id=? LIMIT 1', (local_id,)).fetchone()
    if row is None or str(row['server_id'] or '') != str(payload.get('server_id') or ''):
        raise ValueError('消息已变化，请刷新预览。')
    message = archive.data._build_msg(row, archive.data._name2id(connection), session, shard)
    if message['kind'] not in ('image', 'emoji', 'voice'):
        raise ValueError('此类消息没有可预览媒体。')
    identity = hashlib.sha256(json.dumps([library['root'],session,shard,local_id,str(message['server_id'])]).encode()).hexdigest()
    folder = Path(destination)/identity
    folder.mkdir(parents=True, exist_ok=True)
    cache = folder/'preview.json'
    result = None
    retry = payload.get('retry') is True
    if cache.is_file() and not retry:
        try:
            result = json.loads(cache.read_text(encoding='utf-8'))
            if not isinstance(result, dict) or not isinstance(result.get('path'), str) or result.get('kind') not in ('image', 'audio'):
                result = None
        except (OSError, ValueError):
            pass
    if not result:
        store = ResourceStore(archive.data, session, folder, cancel, options={'includeAvatars': False}, preview=True)
        try:
            if retry and message['kind'] in ('image', 'emoji'):
                store.retry = True
                store.keys.scan_remaining = 8
            enriched = store.enrich(message)
        finally:
            store.close()
        candidates = [item for item in enriched.get('resources', []) if item['status'] == 'available' and item['kind'] in ('image', 'audio')]
        candidates.sort(key=lambda item: item.get('role') != 'main')
        if not candidates:
            notice = enriched.get('resource_notice') or '本机尚无可预览资源，请在微信打开后刷新，或导出查看。'
            if enriched.get('resource_status') == 'encrypted' and not retry:
                notice = '图片已缓存，但尚无可用解密材料。请保持微信登录并打开一张图片，再点击“重试读取”获取。'
            return {'notice': notice}
        result = candidates[0]
        cache.write_text(json.dumps(result), encoding='utf-8')
    path = (folder/result['path']).resolve()
    if not path.is_relative_to(folder.resolve()) or not path.is_file():
        cache.unlink(missing_ok=True)
        return {'notice': '预览缓存已清理，请重试。'}
    cancel()
    if path.stat().st_size > 32 * 1024 * 1024:
        return {'notice': '该资源较大，请导出后查看。'}
    blob = path.read_bytes()
    notice = ''
    if result['kind'] == 'image':
        kind = image_type(blob)
        if not kind:
            return {'notice': '该图片暂时无法预览。'}
        mime = kind[1]
        with Image.open(io.BytesIO(blob)) as image:
            animated = getattr(image, 'is_animated', False)
            if (not animated and (image.width > 1200 or image.height > 1200)) or len(blob) > 8 * 1024 * 1024:
                image.seek(0)
                image.thumbnail((1200, 1200))
                output = io.BytesIO()
                image.convert('RGB').save(output, format='JPEG', quality=85)
                blob, mime = output.getvalue(), 'image/jpeg'
                if animated:
                    notice = '动画较大，预览显示首帧。'
    else:
        mime = 'audio/wav'
    if len(blob) > 8 * 1024 * 1024:
        return {'notice': '该资源较大，请导出后查看。'}
    return {'url': 'data:' + mime + ';base64,' + base64.b64encode(blob).decode('ascii'),
            'kind': result['kind'], 'notice': notice}
