"""Author-side R2 HTTPS transport. Credentials stay in the existing local OAuth store."""
import hashlib
import json
import os
import re
import threading
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .online_protocol import MAX_FEED, file_hash, verify_feed, web_url
from .publisher_paths import oauth_path

CLIENT_ID = '54d11594-84e4-41aa-b438-e81b8fa78ee7'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('发布接口发生重定向，已停止以保护本机授权。')


class CloudflareR2:
    _auth_lock = threading.RLock()

    def __init__(self, cloud, auth_path=None):
        self.cloud = cloud
        self.account = str(cloud.get('account_id', ''))
        self.bucket = str(cloud.get('bucket', ''))
        if not re.fullmatch(r'[a-f0-9]{32}', self.account):
            raise ValueError('Cloudflare 账户配置无效。')
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', self.bucket):
            raise ValueError('R2 存储桶配置无效。')
        self.auth_path = Path(auth_path) if auth_path else oauth_path()
        self.opener = urllib.request.build_opener(NoRedirect())

    def _credentials(self):
        try:
            return tomllib.loads(self.auth_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise ValueError('未找到本机 Cloudflare 授权。请在原电脑使用，或重新完成官方授权。') from None

    def token(self, force=False):
        external = os.environ.get('CLOUDFLARE_API_TOKEN')
        if external:
            return external
        with self._auth_lock:
            saved = self._credentials()
            token = saved.get('oauth_token')
            try:
                expires = datetime.fromisoformat(saved.get('expiration_time', '').replace('Z', '+00:00')).timestamp()
            except (ValueError, TypeError):
                expires = 0
            if token and not force and expires > time.time() + 60:
                return token
            refresh = saved.get('refresh_token')
            if not refresh:
                if token and not force:
                    return token
                raise ValueError('Cloudflare 授权已失效，请重新完成官方授权。')
            body = urllib.parse.urlencode({'grant_type': 'refresh_token', 'refresh_token': refresh, 'client_id': CLIENT_ID}).encode()
            request = urllib.request.Request('https://dash.cloudflare.com/oauth2/token', data=body,
                headers={'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': 'MoectPublisher/1.0.0'})
            try:
                with self.opener.open(request, timeout=20) as response:
                    result = json.loads(response.read(100000))
                if not isinstance(result.get('access_token'), str) or not result['access_token']:
                    raise ValueError('invalid OAuth response')
                updates = {'oauth_token': result['access_token'], 'refresh_token': result.get('refresh_token') or refresh,
                    'expiration_time': (datetime.now(timezone.utc) + timedelta(seconds=int(result.get('expires_in', 3600)))).isoformat()}
                if result.get('scope'):
                    updates['scopes'] = result['scope'].split()
                text = self.auth_path.read_text(encoding='utf-8')
                for key, value in updates.items():
                    line = key + ' = ' + json.dumps(value, ensure_ascii=True)
                    pattern = r'(?m)^' + re.escape(key) + r'\s*=.*$'
                    text = re.sub(pattern, lambda _: line, text) if re.search(pattern, text) else text + '\n' + line + '\n'
                temporary = self.auth_path.with_suffix('.moect.tmp')
                temporary.write_text(text, encoding='utf-8')
                os.replace(temporary, self.auth_path)
                return updates['oauth_token']
            except (OSError, ValueError, KeyError):
                raise ValueError('无法续期 Cloudflare 授权。请检查网络；仍失败时需重新完成官方授权。') from None

    def _path(self, suffix=''):
        return f'https://api.cloudflare.com/client/v4/accounts/{self.account}/r2/buckets/{self.bucket}' + suffix

    @staticmethod
    def _error(error):
        try:
            data = json.loads(error.read(16000))
            codes = ', '.join(str(e.get('code', '')) for e in data.get('errors', [])[:3])
        except (OSError, ValueError):
            codes = ''
        if error.code in (401, 403):
            return ValueError('Cloudflare 授权或权限不足，请在“设置与连接”检查。' + (f'（{codes}）' if codes else ''))
        return ValueError(f'R2 请求未成功（HTTP {error.code}' + (f' / {codes}' if codes else '') + '），请稍后重试。')

    def info(self):
        for attempt in range(2):
            request = urllib.request.Request(self._path(), headers={'Authorization': 'Bearer ' + self.token(force=bool(attempt)),
                'User-Agent': 'MoectPublisher/1.0.0', 'Accept': 'application/json'})
            try:
                with self.opener.open(request, timeout=15) as response:
                    data = json.loads(response.read(100000))
                if not data.get('success'):
                    raise ValueError('R2 存储桶未通过账户验证。')
                return data.get('result', {})
            except urllib.error.HTTPError as error:
                if error.code == 401 and attempt == 0:
                    continue
                raise self._error(error) from None
            except OSError:
                raise ValueError('无法连接 R2，请检查网络后重试。') from None

    def put(self, path, key, index=False, progress=None, expected=None):
        path = Path(path)
        if not key or any(p in ('', '.', '..') for p in key.split('/')) or '\\' in key:
            raise ValueError('发布资源路径无效。')
        size = path.stat().st_size
        if size > 25 * 1024 * 1024:
            raise ValueError('资源未正确分片，请重新检查软件包。')
        if expected and file_hash(path)!=expected:
            raise ValueError('上传前资源发生变化，请重新选择文件。')
        import mimetypes
        for attempt in range(2):
            digest = hashlib.sha256()
            headers = {'Authorization': 'Bearer ' + self.token(force=bool(attempt)), 'User-Agent': 'MoectPublisher/1.0.0',
                'Content-Type': 'application/json' if index else (mimetypes.guess_type(path.name)[0] or 'application/octet-stream'),
                'Cache-Control': 'no-cache, max-age=0, must-revalidate' if index else 'public, max-age=31536000, immutable',
                'Content-Length': str(size)}
            def chunks(stream):
                sent = 0
                while True:
                    blob = stream.read(256 * 1024)
                    if not blob:
                        return
                    digest.update(blob)
                    sent += len(blob)
                    if progress:
                        progress(sent, size)
                    yield blob
            try:
                with path.open('rb') as stream:
                    request = urllib.request.Request(self._path('/objects/' + urllib.parse.quote(key, safe='/')),
                        data=chunks(stream), headers=headers, method='PUT')
                    with self.opener.open(request, timeout=120) as response:
                        response.read(100000)
                if expected and digest.hexdigest() != expected:
                    raise ValueError('上传过程中资源发生变化，未发布正式索引，请重新选择文件。')
                return
            except urllib.error.HTTPError as error:
                if error.code == 401 and attempt == 0:
                    continue
                raise self._error(error) from None
            except OSError:
                raise ValueError('上传未完成，正式发布记录尚未提交，请检查网络后重试。') from None

    def delete(self,key):
        if not isinstance(key,str) or not key.startswith(('announcements/','packages/')) or any(p in ('','.','..') for p in key.split('/')) or '\\' in key:
            raise ValueError('只能清理本项目公告或更新的具体资源，不能删除清单或其他文件。')
        for attempt in range(2):
            request=urllib.request.Request(self._path('/objects/'+urllib.parse.quote(key,safe='/')),
                headers={'Authorization':'Bearer '+self.token(force=bool(attempt)),'User-Agent':'MoectPublisher/1.0.0'},method='DELETE')
            try:
                with self.opener.open(request,timeout=20) as response:response.read(100000)
                return
            except urllib.error.HTTPError as error:
                if error.code==404:return
                if error.code==401 and attempt==0:continue
                raise self._error(error) from None
            except OSError:
                raise ValueError('云端资源清理未完成，可稍后重试；内容已停止分发。') from None


def fetch_public(config, opener=None):
    endpoint = web_url(config['endpoint'], set(config['hosts']))
    request = urllib.request.Request(endpoint, headers={'User-Agent': 'MoectPublisher/1.0.0', 'Cache-Control': 'no-cache', 'Accept-Encoding': 'identity'})
    client = opener or urllib.request.build_opener(NoRedirect())
    try:
        with client.open(request, timeout=15) as response:
            blob = response.read(MAX_FEED * 2 + 1)
        if len(blob) > MAX_FEED * 2:
            raise ValueError('云端清单过大。')
        return verify_feed(json.loads(blob), config['public_key'], set(config['hosts']))
    except (OSError, ValueError):
        raise ValueError('无法读取或验证正式公告清单，请检查连接后重试。') from None
