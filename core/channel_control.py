"""Public release identity and last-moment checks, shared with the isolated updater."""
import hashlib
import json
import urllib.request
from .online_protocol import MAX_FEED,verify_feed,web_url


def release_key(release):
    if not release:return ''
    return hashlib.sha256(json.dumps(release,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()


class ChannelRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self,hosts):self.hosts=hosts
    def redirect_request(self,request,fp,code,msg,headers,newurl):
        web_url(newurl,self.hosts)
        return super().redirect_request(request,fp,code,msg,headers,newurl)


def current_feed(config,minimum_sequence=0):
    hosts=set(config.get('hosts',[]));url=web_url(config.get('endpoint'),hosts)
    request=urllib.request.Request(url,headers={'User-Agent':'MoectUpdater/1.2.0','Cache-Control':'no-cache','Accept-Encoding':'identity'})
    try:
        with urllib.request.build_opener(ChannelRedirect(hosts)).open(request,timeout=8) as response:
            blob=response.read(MAX_FEED*2+1)
        if len(blob)>MAX_FEED*2:raise ValueError('发布清单过大')
        envelope=json.loads(blob)
        return envelope,verify_feed(envelope,config['public_key'],hosts,minimum_sequence=minimum_sequence)
    except (OSError,ValueError,KeyError):
        raise ValueError('无法联网确认当前更新是否仍有效，已停止安装，请检查网络后重试。') from None


def require_current_release(expected,actual):
    if not expected or release_key(expected)!=release_key(actual):
        raise ValueError('该更新已被撤回、删除或替换，已停止安装，请重新检查更新。')
