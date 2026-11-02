"""Cached timeline/account/date selections and recall metadata, using fake data."""
import hashlib
import json
import re
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch

from core.account_assets import MomentsCatalog,moment_selection
from core.account_exporting import export_moments
from core.data import Archive
from core.service import Service
from wx4.reader import Wx4Data
from tests.test_account_assets import asset_fixture
from tests.test_core import USER,SESSION
from tests.test_resources import ASSETS


class MomentsScopeTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.library,_=asset_fixture(self.root)
        self.archive=Archive(self.library);self.addCleanup(self.archive.close)
        cache=patch('core.media_codec.app_data_root',return_value=self.root/'private-state')
        cache.start();self.addCleanup(cache.stop)

    def test_self_timeline_and_specified_scopes_do_not_mix_authors(self):
        def ids(scope,author=''):
            return {p['id'] for p in MomentsCatalog(self.library,USER,scope,author).posts()}
        self.assertEqual(ids('self'),{'100','103'})
        self.assertEqual(ids('timeline'),{'100','101','103'})
        self.assertEqual(ids('account','friend'),{'101'})
        self.assertEqual(ids('account','unknown-account'),set())
        self.assertEqual(ids('account',"' OR 1=1 --"),set())
        self.assertEqual(ids('account',''),set())

    def test_account_resolution_uses_exact_uid_alias_or_unambiguous_name(self):
        contacts=self.archive.data.contacts
        for value in ('friend','同事','朋友'):
            self.assertEqual(moment_selection({'scope':'account','authorId':value},USER,contacts)['author_id'],'friend')
        duplicate={**contacts,'second':{'username':'second','nick_name':'朋友','remark':'同事'}}
        with self.assertRaisesRegex(ValueError,'多个账号'):
            moment_selection({'scope':'account','authorId':'同事'},USER,duplicate)
        for payload in ({'scope':'invalid'},{'scope':[]},{'scope':'account'},{'scope':'account','authorId':[]}):
            with self.subTest(payload=payload),self.assertRaises(ValueError):moment_selection(payload,USER,contacts)

    def add_date_boundaries(self):
        start=int(datetime(2026,11,1,tzinfo=timezone(timedelta(hours=8))).timestamp());end=start+86399
        database=Path(self.library['root'])/'sns/sns.db'
        with closing(sqlite3.connect(database)) as con,con:
            source=con.execute('SELECT content FROM SnsTimeLine WHERE tid=100').fetchone()[0]
            for ident,author,stamp in [(200,USER,start-1),(201,'friend',start),(202,USER,end),(203,'friend',end+1),(204,'friend',start+43200)]:
                content=source.replace('<id>100</id>','<id>'+str(ident)+'</id>').replace(USER,author).replace('<createTime>1800000000</createTime>','<createTime>'+str(stamp)+'</createTime>')
                con.execute('INSERT INTO SnsTimeLine VALUES (?,?,?,?)',(ident,author,content,''))
        return start,end

    def test_summary_and_bridge_export_honor_inclusive_beijing_date_boundaries(self):
        start,end=self.add_date_boundaries()
        catalog=MomentsCatalog(self.library,USER,'timeline')
        self.assertEqual(catalog.summary(start,end,self.archive.data.name_of)['count'],3)
        service=Service(ASSETS,self.root/'state');service.library=self.library;service.config['export_dir']=str(self.root/'exports')
        try:
            payload={'kind':'moments','scope':'account','authorId':'同事','start':'2026-11-01','end':'2026-11-01','includeImages':False,'includeVideos':False}
            preview=service.account_assets(payload)
            self.assertEqual(preview['count'],2);self.assertTrue(all(p['author']=='friend' for p in preview['posts']))
            self.assertEqual({a['uid'] for a in preview['authors']},{USER,'friend'})
            with patch('core.resources.ResourceStore._download',side_effect=AssertionError('Skipped media downloaded')):
                job=service.export_account(payload);service.pool.shutdown(wait=True)
            self.assertEqual(service.state()['tasks'][0]['status'],'completed')
            folder=service.task_folder(job['job']);data=json.loads((folder/'data.json').read_text(encoding='utf-8'))
            self.assertEqual(data['scope']['scope'],'account');self.assertEqual(data['scope']['author_id'],'friend')
            self.assertEqual({p['id'] for p in data['items']},{'201','204'})
            self.assertEqual(data['filters'],{'start':'2026-11-01','end':'2026-11-01'})
            self.assertTrue(all(p['author']=='friend' and start<=p['create_time']<=end for p in data['items']))
            self.assertIn('friend',folder.name)
        finally:service.shutdown()

    def test_public_export_retains_per_post_author_and_scope(self):
        destination=self.root/'timeline';destination.mkdir()
        with patch('core.resources.ResourceStore._download',side_effect=AssertionError('Skipped media downloaded')):
            result=export_moments(self.archive,self.library,{'scope':'timeline','includeImages':False,'includeVideos':False},destination,ASSETS,lambda *a:None,lambda:None,lambda _:None)
        data=json.loads((destination/'data.json').read_text(encoding='utf-8'))
        self.assertEqual(result['count'],3);self.assertEqual(data['scope']['scope'],'timeline')
        self.assertEqual({p['author'] for p in data['items']},{USER,'friend'})
        self.assertEqual(next(p for p in data['items'] if p['author']=='friend')['author_name'],'同事')
        self.assertNotIn('secret-token',json.dumps(data,ensure_ascii=False))

    def test_invalid_or_missing_account_and_reversed_dates_never_create_a_job(self):
        service=Service(ASSETS,self.root/'invalid-state');service.library=self.library
        try:
            for payload in ({'kind':'moments','scope':'account'},{'kind':'moments','scope':'all-unknown'},{'kind':'moments','scope':'timeline','start':'2026-11-02','end':'2026-11-01'}):
                with self.subTest(payload=payload),self.assertRaises(ValueError):service.export_account(payload)
            self.assertEqual(service.state()['tasks'],[])
        finally:service.shutdown()

    def test_recall_xml_and_preview_flag_are_separate_from_ordinary_text(self):
        xml='<sysmsg type="revokemsg"><revokemsg><newmsgid>123456</newmsgid><replacemsg><![CDATA[<a href="weixin://test">合成用户</a>撤回了一条消息]]></replacemsg></revokemsg></sysmsg>'
        self.assertEqual(Wx4Data._system_text(xml),'合成用户撤回了一条消息')
        table='Msg_'+hashlib.md5(SESSION.encode()).hexdigest()
        database=Path(self.library['root'])/'message/message_0.db'
        with closing(sqlite3.connect(database)) as con,con:
            for ident,typ,content in [(1000,10002,xml),(1001,1,'这是一条关于撤回消息的普通文本')]:
                con.execute('INSERT INTO "'+table+'" VALUES (?,?,?,?,?,?,?,?,?)',(ident,str(ident),typ,ident,2,1800000200+ident,content,None,None))
        service=Service(ASSETS,self.root/'preview-state');service.library=self.library
        try:
            messages=service.qce_preview({'peer':{'peerUid':SESSION},'limit':200})['messages']
            recall=next(m for m in messages if m['elements'][0]['textElement']['content']=='合成用户撤回了一条消息')
            ordinary=next(m for m in messages if m['elements'][0]['textElement']['content']=='这是一条关于撤回消息的普通文本')
            self.assertTrue(recall['isSystem']);self.assertFalse(ordinary['isSystem'])
        finally:service.shutdown()

    def test_html_filters_enforce_author_and_time_without_expanding_exported_data(self):
        collection=(ASSETS/'collection.html').read_text(encoding='utf-8')
        viewer=(ASSETS/'viewer.html').read_text(encoding='utf-8')
        helpers='\n'.join(re.search(r'^function '+name+r'\([^\n]+',source,re.M).group(0)
                          for source,name in [(collection,'matchesCollectionItem'),(viewer,'isSystemMessage')])
        script=helpers+'''
const assert=require('node:assert/strict');
const first=Date.parse('2026-11-01T00:00:00+08:00')/1000,last=Date.parse('2026-11-01T23:59:59+08:00')/1000;
const f={sticker:false,group:'friend',q:'',from:first,to:last};
for(const time of [first,last])assert.equal(matchesCollectionItem({author:'friend',create_time:time},f),true);
for(const time of [first-1,last+1])assert.equal(matchesCollectionItem({author:'friend',create_time:time},f),false);
assert.equal(matchesCollectionItem({author:'other',create_time:first},f),false);
assert.equal(isSystemMessage({kind:'system'}),true);assert.equal(isSystemMessage({type:10002}),true);
assert.equal(isSystemMessage({kind:'text',type:1,text:'a message about recall'}),false);
'''
        subprocess.run(['node'],input=script,text=True,encoding='utf-8',capture_output=True,check=True)


if __name__=='__main__':unittest.main()
