"""Withdraw content first, then remove only unreferenced Moect-owned cloud objects."""
import copy
import re
import uuid
from urllib.parse import unquote,urlsplit

from scripts import publish_channel as channel
from .channel_control import release_key
from .publisher_cloud import CloudflareR2,fetch_public
from .online_protocol import version,web_url


def content_key(kind,item):return release_key(item)


def resource_urls(kind,item):
    if kind=='announcement':return set(item.get('assets',{}))
    return {part['url'] for package in item.get('packages',{}).values() for part in (package.get('parts') or [package])}


def resource_key(url,trust):
    try:
        web_url(url,set(trust['hosts']))
        base=urlsplit(trust['endpoint'].rsplit('/channel/',1)[0])
        actual=urlsplit(url)
        if actual.hostname!=base.hostname:return None
        prefix=base.path.rstrip('/')+'/'
        if not actual.path.startswith(prefix):return None
        key=unquote(actual.path[len(prefix):])
        if not key.startswith(('announcements/','packages/')) or any(p in ('','.','..') for p in key.split('/')) or '\\' in key:return None
        return key
    except (ValueError,KeyError,TypeError):return None


def owned_resources(kind,item,trust):
    if kind=='announcement':
        uid=item.get('id','')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',uid):raise ValueError('公告标识无效。')
        prefix='announcements/'
    else:
        version(item.get('version'));prefix='packages/'
    return sorted({key for url in resource_urls(kind,item) if (key:=resource_key(url,trust)) and key.startswith(prefix)})


class PublicationManagement:
    def _management_state(self):
        retired=self._read('retired.json',[])
        pending=self._read('cleanup-pending.json',[])
        summaries=[]
        for entry in retired:
            item=entry.get('item',{});kind=entry.get('kind')
            summaries.append({k:entry.get(k) for k in ('id','kind','title','at','reason','pending')})
            summaries[-1]['resource_count']=len(resource_urls(kind,item))
        return {'retired':summaries[::-1],'cleanup_pending':[{k:v.get(k) for k in ('id','title','at','last_error')} | {'remaining':len(v.get('keys',[]))} for v in pending]}

    def inspect_retired(self,uid):
        with self.lock:
            found=next((v for v in self._read('retired.json',[]) if v['id']==uid),None)
            if not found:raise ValueError('该记录已不存在，请刷新。')
            return copy.deepcopy(found)

    def _save_management(self,name,value):
        from .publisher_service import atomic
        with self.lock:atomic(self.root/name,value)

    def _stage_retired(self,kind,item,reason):
        entries=self._read('retired.json',[]);key=content_key(kind,item)
        found=next((v for v in entries if v['kind']==kind and content_key(kind,v['item'])==key),None)
        if found:return found
        entry={'id':uuid.uuid4().hex,'kind':kind,'title':item['title'] if kind=='announcement' else 'Moect '+item['version'],
            'item':copy.deepcopy(item),'reason':reason,'pending':True,'at':channel.utc()}
        entries.append(entry);self._save_management('retired.json',entries);return entry

    def _commit_retired(self,entry,sequence):
        entries=self._read('retired.json',[])
        for value in entries:
            if value['id']==entry['id']:value.update(pending=False,sequence=sequence)
        self._save_management('retired.json',entries)

    def _sync_retired(self,feed):
        entries=self._read('retired.json',[]);result=[];had_pending=any(v.get('pending') for v in entries)
        for entry in entries:
            if entry.get('pending'):
                active=feed.get('announcements',[]) if entry['kind']=='announcement' else ([feed['release']] if feed.get('release') else [])
                if any(content_key(entry['kind'],value)==content_key(entry['kind'],entry['item']) for value in active):continue
                entry['pending']=False;entry['sequence']=feed['sequence']
                if entry.get('reason')=='deleting':entry['reason']='delete_pending'
            result.append(entry)
        if had_pending:self._save_management('retired.json',result)

    def _fresh_management_feed(self):
        from .publisher_service import atomic
        feed=fetch_public(self.trust);local=channel.load_draft()
        if feed['sequence']<local.get('sequence',0):raise ValueError('云端状态尚未同步，请稍后刷新，暂不清理资源。')
        if feed['sequence']>local.get('sequence',0):atomic(self.root/'draft.json',feed)
        self._sync_retired(feed);return feed

    def _referenced_resources(self,feed,exclude=''):
        items=[('announcement',n) for n in feed.get('announcements',[])]
        if feed.get('release'):items.append(('release',feed['release']))
        items.extend((v['kind'],v['item']) for v in self._read('retired.json',[]) if v['id']!=exclude)
        return {key for kind,item in items for url in resource_urls(kind,item) if (key:=resource_key(url,self.trust))}

    def _cleanup_resources(self,uid,feed):
        jobs=self._read('cleanup-pending.json',[]);job=next((v for v in jobs if v['id']==uid),None)
        if not job:return {'remaining':0,'protected':0}
        protected=self._referenced_resources(feed);kept=0;client=CloudflareR2(self._read('cloudflare.json',{}))
        total=len(job['keys'])
        for index,key in enumerate(list(job['keys'])):
            self._progress('正在清理未引用的云端资源',index,total)
            if key in protected:kept+=1
            else:
                try:client.delete(key)
                except (ValueError,OSError) as error:
                    job['last_error']=str(error)[:300]
                    self._save_management('cleanup-pending.json',jobs)
                    return {'remaining':len(job['keys']),'protected':kept}
            job['keys'].remove(key);self._save_management('cleanup-pending.json',jobs)
        jobs=[v for v in jobs if v['id']!=uid];self._save_management('cleanup-pending.json',jobs)
        return {'remaining':0,'protected':kept}

    def _delete_retired(self,entry,feed):
        entries=self._read('retired.json',[])
        active=feed.get('announcements',[]) if entry['kind']=='announcement' else ([feed['release']] if feed.get('release') else [])
        if any(content_key(entry['kind'],v)==content_key(entry['kind'],entry['item']) for v in active):raise ValueError('该内容仍在线上，请先从线上内容执行删除。')
        keys=owned_resources(entry['kind'],entry['item'],self.trust)
        jobs=self._read('cleanup-pending.json',[]);uid=entry['id']
        if not any(v['id']==uid for v in jobs):
            jobs.append({'id':uid,'title':entry['title'],'at':channel.utc(),'keys':keys,'last_error':''})
            self._save_management('cleanup-pending.json',jobs)
        # The retry queue is durable before the retained content is removed.
        self._save_management('retired.json',[v for v in entries if v['id']!=uid])
        report=self._cleanup_resources(uid,feed)
        return report

    def manage_content(self,payload):
        kind=payload['kind']
        with channel.publish_lock():
            self._progress('正在核对最新线上内容')
            feed=self._fresh_management_feed();entry=None
            if kind=='retry_cleanup':
                uid=str(payload.get('id',''))
                retained=next((v for v in self._read('retired.json',[]) if v['id']==uid),None)
                report=self._delete_retired(retained,feed) if retained else self._cleanup_resources(uid,feed)
                return {'message':f"仍有{report['remaining']}个资源待清理，可稍后重试。" if report['remaining'] else '云端资源清理完成。',**report}
            if kind=='delete_retired':
                entry=self.inspect_retired(str(payload.get('id','')))
                if entry.get('pending'):raise ValueError('这项操作尚未确认，请先同步云端。')
                report=self._delete_retired(entry,feed)
                result={'sequence':feed['sequence'],'version':(feed.get('release') or {}).get('version','')}
            else:
                target_kind='announcement' if kind.endswith('notice') else 'release'
                if target_kind=='announcement':
                    item=next((v for v in feed['announcements'] if v['id']==payload.get('id')),None)
                    if not item:raise ValueError('公告已不存在，请刷新。')
                else:
                    item=feed.get('release')
                    if not item:raise ValueError('当前没有已发布的更新。')
                    if payload.get('release_key')!=release_key(item):raise ValueError('线上版本已变化，请刷新并重新确认，未操作其他版本。')
                deleting=kind.startswith('delete')
                entry=self._stage_retired(target_kind,item,'deleting' if deleting else 'withdrawn')
                changed=copy.deepcopy(feed)
                if target_kind=='announcement':changed['announcements']=[v for v in changed['announcements'] if v['id']!=item['id']]
                else:changed['release']=None
                try:result=channel._publish(changed,progress=self._progress)
                except Exception:
                    raise ValueError('操作尚未确认，保留了原内容以便恢复；请先同步云端，再决定是否重试。') from None
                self._commit_retired(entry,result['sequence'])
                latest=fetch_public(self.trust)
                if latest['sequence']<result['sequence']:raise ValueError('停止分发请求已提交，公网尚未确认；请先同步，不重复操作。')
                if not deleting:
                    self._record(kind,entry['title'],result,entry['item'].get('id',''))
                    return {**result,'message':'已撤回，作者内容与云端资源已保留；用户下次联网检查后停止展示或使用。'}
                report=self._delete_retired(entry,latest)
            self._record(kind,entry['title'],result,entry['item'].get('id',''))
            message='内容已删除，未引用的云端资源已清理。'
            if report['remaining']:message=f"内容已停止分发并删除，仍有{report['remaining']}个云端资源待清理，可在记录页重试。"
            elif report['protected']:message='内容已删除；其他内容仍在引用的云端资源已保留。'
            return {**result,**report,'message':message}
