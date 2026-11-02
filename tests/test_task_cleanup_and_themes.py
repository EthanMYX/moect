"""Synthetic task history, group sender framing and portable palette snapshots."""
import json
import re
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from core.service import Service,task_category
from core.data import Archive
from core.exporting import export_session,materialize_forward
from core.account_exporting import export_moments
from core.themes import ACCENT_IDS,palette,theme_archive
from tests.test_core import fixture,USER,SESSION
from tests.test_account_assets import asset_fixture
from tests.test_resources import ASSETS


class TaskCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.service=Service(ASSETS,self.root/'state');self.addCleanup(self.service.shutdown)
        self.file=self.root/'export'/'index.html';self.file.parent.mkdir();self.file.write_text('saved archive')
        self.tasks=[]
        for kind,category,status in [('export',None,'completed'),('export','moments','completed'),('export','stickers','failed'),('connect',None,'running'),('export','moments','queued')]:
            task=self.service._new_job(kind,'Synthetic task');task.update(status=status,folder=str(self.file.parent))
            if category:task['category']=category
            self.tasks.append(task)

    def test_category_clear_keeps_other_history_active_jobs_and_files(self):
        result=self.service.delete_tasks({'clear':True,'category':'moments'})
        self.assertEqual(result['deleted'],1);self.assertEqual(len(result['state']['tasks']),4)
        self.assertTrue(any(t['id']==self.tasks[4]['id'] for t in result['state']['tasks']))
        self.assertEqual(self.file.read_text(),'saved archive')
        result=self.service.delete_tasks({'clear':True})
        self.assertEqual(result['deleted'],2);self.assertTrue(all(t['status'] in ('queued','running') for t in result['state']['tasks']))

    def test_explicit_multi_delete_is_atomic_when_an_active_job_is_selected(self):
        with self.assertRaises(ValueError):self.service.delete_tasks({'ids':[self.tasks[0]['id'],self.tasks[3]['id']]})
        self.assertEqual(len(self.service.config['tasks']),5)
        result=self.service.delete_tasks({'ids':[self.tasks[0]['id'],self.tasks[2]['id']]})
        self.assertEqual(result['deleted'],2);self.assertTrue(self.file.is_file())
        self.assertNotIn(self.tasks[0]['id'],self.service.events)

    def test_legacy_categories_and_invalid_requests(self):
        for task,category in [({'kind':'export','format':'html'},'sessions'),({'kind':'export','format':'moments'},'moments'),({'kind':'refresh_assets','category':'stickers'},'stickers'),({'kind':'refresh_assets'},'other')]:
            self.assertEqual(task_category(task),category)
        for payload in ({'ids':[]},{'clear':'yes'},{'clear':True,'ids':['id']},{'clear':True,'category':'unknown'}):
            with self.assertRaises(ValueError):self.service.delete_tasks(payload)
        self.assertEqual(len(self.service.config['tasks']),5)


class SenderAndThemeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.library=fixture(self.root/'db',count=2)
        self.archive=Archive(self.library);self.addCleanup(self.archive.close)

    def message(self,body,sender='legacy_demo_42',session=SESSION):
        row=dict(local_id=1,server_id='1',local_type=1,sort_seq=1,real_sender_id=1,create_time=1800000000,
                 message_content=body,compress_content=None,packed_info_data=None)
        return self.archive.data._build_msg(row,{1:sender},session,0)

    def test_group_legacy_wechat_id_prefix_is_removed_and_message_is_intact(self):
        for prefix in ('legacy_demo_42','wxid_synthetic','987654321','synthetic@openim'):
            message=self.message(prefix+':\r\n这是一条合成测试消息。',prefix)
            self.assertEqual(message['text'],'这是一条合成测试消息。')
            self.assertEqual(message['sender_wxid'],prefix)
        self.archive.data.contacts['wxid_test']={'username':'wxid_test','alias':'old_custom_id'}
        self.assertEqual(self.message('old_custom_id:\nbody','wxid_test')['text'],'body')

    def test_private_text_and_unverified_colon_lines_are_preserved(self):
        for body in ('Note:\nkeep this','注意：\n保留正文','legacy_demo_42:\nquoted account','https://example.com:\nURL'):
            self.assertEqual(self.message(body,'friend')['text'],body)
        body='wxid_synthetic:\nthis is ordinary private text'
        self.assertEqual(self.message(body,'wxid_synthetic','friend')['text'],body)

    def test_all_palettes_apply_to_css_without_rewriting_content_or_transfer_colors(self):
        template='<style>body{background:#f7f5fb;color:#292137}button{background:white;color:#7056c4}.me{background:#e9defd}.transfer{background:#f0a547}</style><p>#7056c4</p>'
        for mode in ('light','dark'):
            for accent in ACCENT_IDS:
                themed=theme_archive(template,{'mode':mode,'accent':accent});colors=palette(mode,accent)
                self.assertIn('--primary:'+colors['primary']+';',themed)
                self.assertIn('color-scheme:'+mode,themed)
                self.assertIn('button{background:var(--card);color:var(--primary)}',themed)
                self.assertIn('background:#f0a547',themed);self.assertIn('<p>#7056c4</p>',themed)

    def test_queued_chat_export_keeps_theme_at_creation_and_forward_inherits_it(self):
        service=Service(ASSETS,self.root/'state');service.library=self.library;service.config['export_dir']=str(self.root/'exports')
        service.settings({'theme':'dark','accent':'orange'})
        try:
            with patch.object(service.pool,'submit') as submit:
                job=service.export({'sessions':[SESSION],'format':'html','quickExport':True})
            service.settings({'theme':'light','accent':'blue'})
            fn,*args=submit.call_args.args;fn(*args)
            self.assertEqual(service.state()['tasks'][0]['status'],'completed')
            viewer=service.task_file(job['job']).read_text(encoding='utf-8')
            self.assertIn('--primary:'+palette('dark','orange')['primary']+';',viewer)
            folder=self.root/'forward';folder.mkdir()
            template=theme_archive((ASSETS/'viewer.html').read_text(encoding='utf-8'),{'mode':'dark','accent':'green'})
            message={'forward':{'title':'Synthetic forward','messages':[{'text':'hello','sender':'person','kind':'text','create_time':1800000000}]}}
            materialize_forward(message,folder,template,'synthetic',lambda:None)
            html=next(folder.glob('*.html')).read_text(encoding='utf-8')
            self.assertIn('--primary:'+palette('dark','green')['primary']+';',html)
        finally:service.shutdown()

    def test_moments_collection_carries_selected_dark_palette(self):
        library,_=asset_fixture(self.root/'assets');archive=Archive(library);folder=self.root/'moments';folder.mkdir()
        try:
            with patch('core.resources.ResourceStore._download',side_effect=AssertionError('Moments are local-only')):
                export_moments(archive,library,{'_theme':{'mode':'dark','accent':'red'}},folder,ASSETS,lambda *a:None,lambda:None,lambda _:None)
            data=json.loads((folder/'data.json').read_text(encoding='utf-8'));html=(folder/'index.html').read_text(encoding='utf-8')
            self.assertEqual(data['theme'],{'mode':'dark','accent':'red'})
            self.assertIn('--primary:'+palette('dark','red')['primary']+';',html)
            self.assertNotIn('background:white',html.split('</style>')[0])
        finally:archive.close()


if __name__=='__main__':unittest.main()
