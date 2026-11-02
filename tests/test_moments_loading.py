"""Synthetic social data, local previews, manual snapshots and offline media."""
import json
import hashlib
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from core.account_assets import MomentsCatalog,moment_from_row
from core.account_exporting import export_moments,local_moments_previews,MomentResources
from core.data import Archive
from core.service import Service
from core.resources import ResourceStore
from core.sticker_cache import StickerCache
from tests.test_account_assets import asset_fixture
from tests.test_core import USER
from tests.test_resources import ASSETS,PNG


class SocialExportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.library,_=asset_fixture(self.root)
        self.archive=Archive(self.library);self.addCleanup(self.archive.close)
        cache=patch('core.media_codec.app_data_root',return_value=self.root/'private-state');cache.start();self.addCleanup(cache.stop)

    def social(self):
        return '''<LocalExtraInfo><like_user_list><user_comment><username>friend</username><nickname>Stored friend</nickname></user_comment></like_user_list><comment_user_list>
        <user_comment><username>friend</username><nickname>Stored friend</nickname><comment_id>0</comment_id><comment_64id>123</comment_64id><content>hello &lt;script&gt;</content><create_time>1800000001</create_time></user_comment>
        <user_comment><username>other</username><nickname>Other</nickname><comment_id>0</comment_id><comment_64id>124</comment_64id><ref_comment_64id>123</ref_comment_64id><content>reply</content></user_comment>
        <user_comment><username>deleted</username><content>must not export</content><b_deleted>1</b_deleted></user_comment>
        </comment_user_list></LocalExtraInfo>'''

    def test_social_xml_pack_dedup_replies_deleted_rows_and_portable_avatars(self):
        database=Path(self.library['root'])/'sns/sns.db'
        with closing(sqlite3.connect(database)) as con,con:
            content=con.execute('SELECT content FROM SnsTimeLine WHERE tid=100').fetchone()[0]
            content=content.replace('</SnsDataItem>',self.social()+'</SnsDataItem>')
            con.execute('UPDATE SnsTimeLine SET content=?,pack_info_buf=? WHERE tid=100',(content,self.social()))
        post=next(p for p in MomentsCatalog(self.library,USER).posts() if p['id']=='100')
        self.assertEqual(len(post['likes']),1);self.assertEqual(len(post['comments']),2)
        self.assertEqual(post['comments'][1]['reply_uid'],'friend');self.assertEqual(post['comments'][1]['reply_name'],'Stored friend')
        folder=self.root/'social';folder.mkdir()
        with patch('core.resources.ResourceStore._download',side_effect=AssertionError('Cached media only')):
            export_moments(self.archive,self.library,{},folder,ASSETS,lambda *a:None,lambda:None,lambda _:None)
        data=json.loads((folder/'data.json').read_text(encoding='utf-8'));item=next(p for p in data['items'] if p['id']=='100')
        for person in [*item['likes'],*item['comments']]:
            if person['avatar']:self.assertTrue((folder/person['avatar']).is_file())
        self.assertNotIn('must not export',json.dumps(data));html=(folder/'index.html').read_text(encoding='utf-8')
        self.assertNotIn('__DATE_RANGE_PICKER__',html);self.assertIn('customElements.define',html)
        self.assertIn('repeat(3,minmax(0,1fr))',html);self.assertNotIn('hello <script>',html)

    def test_legacy_software_cache_is_reused_offline_and_skip_is_respected(self):
        folder=Path(self.library['root'])/'preview'
        folder.mkdir();(folder/'cached.png').write_bytes(PNG)
        post=next(p for p in MomentsCatalog(self.library,USER).posts() if p['id']=='100')
        cache={MomentResources.media_key(post['media'][0]):{'kind':'image','status':'available','resources':[{'kind':'image','path':'cached.png','status':'available'}]}}
        (folder/'media.json').write_text(json.dumps(cache))
        shutil.rmtree(Path(self.library['account_dir'])/'cache')
        destination=self.root/'cached-export';destination.mkdir()
        with patch('core.account_exporting.MomentResources.local_candidates',side_effect=AssertionError('Must reuse prepared cache')),patch('core.resources.ResourceStore._download',side_effect=AssertionError('Offline')):
            export_moments(self.archive,self.library,{},destination,ASSETS,lambda *a:None,lambda:None,lambda _:None)
        data=json.loads((destination/'data.json').read_text(encoding='utf-8'));item=next(p for p in data['items'] if p['id']=='100')
        self.assertEqual((destination/item['resources'][0]['path']).read_bytes(),PNG)
        no_images=self.root/'skipped';no_images.mkdir()
        with patch('core.resources.ResourceStore._copy',side_effect=AssertionError('Skip must precede cache lookup')):
            export_moments(self.archive,self.library,{'includeImages':False},no_images,ASSETS,lambda *a:None,lambda:None,lambda _:None)

    def test_moments_preview_and_export_without_dates_are_local_and_do_not_enqueue_refresh(self):
        service=Service(ASSETS,self.root/'local-state');service.library=service.config['library']=self.library;service.config['export_dir']=str(self.root/'exports')
        try:
            with patch('core.resources.ResourceStore._download',side_effect=AssertionError('Local Moments must not download')):
                preview=service.account_assets({'kind':'moments'})
                self.assertEqual(preview['count'],2);self.assertEqual(service.state()['tasks'],[])
                self.assertTrue(next(p for p in preview['posts'] if p['id']=='100')['thumbnails'][0].startswith('data:image/jpeg;base64,'))
                service.export_account({'kind':'moments'});service.pool.shutdown(wait=True)
            self.assertEqual(service.state()['tasks'][0]['status'],'completed')
        finally:service.shutdown()

    def test_manual_refresh_updates_snapshot_without_dates_or_automation(self):
        service=Service(ASSETS,self.root/'manual');service.library=service.config['library']=self.library
        (Path(self.library['root']).parent/'keys.json').write_text('{}')
        def decrypt(keys,source,destination,**kwargs):
            target=Path(destination)/'sns/sns.db';target.parent.mkdir(parents=True)
            shutil.copy2(Path(self.library['root'])/'sns/sns.db',target)
            return {'ok':['sns/sns.db'],'failed':[]}
        try:
            with patch('wx4.key.load_keys',return_value={'sns/sns.db':{}}),patch('wx4.decrypt.decrypt_all',side_effect=decrypt),patch('core.resources.ResourceStore._download',side_effect=AssertionError('Snapshot refresh is local')):
                service.refresh_assets();service.pool.shutdown(wait=True)
                preview=service.account_assets({'kind':'moments'})
            self.assertEqual(service.state()['tasks'][0]['status'],'completed');self.assertEqual(preview['count'],2)
            self.assertNotIn('prepared',preview)
        finally:service.shutdown()

    def test_sticker_previously_downloaded_source_is_reused_in_local_only_mode(self):
        folder=self.root/'sticker-cache';folder.mkdir();store=ResourceStore(self.archive.data,'',folder)
        try:
            url='https://emoji.qpic.cn/synthetic-sticker';path=store.keys.path.parent/'downloads'/(hashlib.sha256(url.encode()).hexdigest()+'.media')
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(PNG)
            decoder=StickerCache(self.archive.data,store.codec,lambda:None,lambda _:None)
            member={'md5':'e'*32,'metadata':{'cdn_url':url}}
            with patch.object(decoder,'local',return_value=None),patch.object(store,'_download',side_effect=AssertionError('Local-only must never request a URL')):
                image,quality=decoder.resolve(member,store,download=False)
            self.assertEqual(image,PNG);self.assertEqual(quality,'original')
        finally:store.close()

    def test_explicit_reconnect_is_repeatable_and_targets_current_account(self):
        service=Service(ASSETS,self.root/'reconnect');service.library=self.library
        def detect():
            service.accounts={'wanted':{'path':self.library['account_dir']},'other':{'path':str(self.root/'other')}}
            return {'running':True}
        try:
            with patch.object(service,'detect',side_effect=detect),patch.object(service,'connect',return_value={'job':'id'}) as connect:
                service.reconnect();service.reconnect()
                self.assertEqual(connect.call_count,2);connect.assert_called_with('wanted')
        finally:service.shutdown()

    def test_shared_picker_uses_draft_until_commit_and_validates_minute_order(self):
        script='''const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');let Picker;
class Base{constructor(){this.attrs={};this.events=[];this.isConnected=false;}attachShadow(){return {}}setAttribute(k,v){this.attrs[k]=v;}dispatchEvent(e){this.events.push(e);}}
vm.runInNewContext(fs.readFileSync('ui/date-range-picker.js','utf8'),{HTMLElement:Base,customElements:{get:()=>null,define:(name,type)=>Picker=type},CustomEvent:class{constructor(name,options){this.name=name;Object.assign(this,options);}}});
const p=new Picker();let closed=0;p.q=()=>({close:()=>closed++});p.s='2026-11-01T12:00';p.e='2026-11-01T12:01';assert.equal(p.valid(),true);assert.equal(p.events.length,0);p.e='2026-11-01T11:59';assert.equal(p.valid(),false);p.e='2026-11-01T12:01';p.commit(p.s,p.e);assert.equal(p.events.length,1);assert.equal(closed,1);assert.deepEqual(JSON.parse(JSON.stringify(p.events[0].detail)),{start:'2026-11-01T12:00',end:'2026-11-01T12:01'});'''
        result=subprocess.run(['node'],input=script,text=True,encoding='utf-8',capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
