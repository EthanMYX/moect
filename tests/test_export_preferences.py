"""Synthetic regression cases; never reads a real WeChat account."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack,closing
from pathlib import Path
from unittest.mock import patch

from core.data import Archive
from core.export_options import export_preferences
from core.exporting import export_session
from core.resources import ResourceStore
from core.service import Service,options_from
from tests.test_core import USER,SESSION
from tests.test_resources import media_fixture,PNG,ASSETS


def json_rows(result):
    return json.loads(Path(result['path']).read_text(encoding='utf-8'))['messages']


class DatabaseTextTests(unittest.TestCase):
    def test_binary_text_digest_does_not_break_contacts_or_avatar_loading(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);lib=media_fixture(root)
            digest=b'\xff\x80\x00\xf0'+bytes(range(12))
            contact=root/'db/contact/contact.db'
            with closing(sqlite3.connect(contact)) as con,con:
                con.execute('ALTER TABLE contact ADD COLUMN head_img_md5 TEXT')
                con.execute('UPDATE contact SET head_img_md5=CAST(? AS TEXT)',(digest,))
                with self.assertRaisesRegex(sqlite3.OperationalError,'Could not decode to UTF-8'):
                    con.execute('SELECT head_img_md5 FROM contact').fetchone()
            with closing(sqlite3.connect(root/'db/contact/head_image.db')) as con,con:
                con.execute('ALTER TABLE ContactHeadImg1 ADD COLUMN head_img_md5 TEXT')
                con.execute('UPDATE ContactHeadImg1 SET head_img_md5=CAST(? AS TEXT)',(digest,))
            archive=Archive(lib)
            try:
                self.assertEqual(archive.data.contacts[USER]['head_img_md5'],digest)
                self.assertEqual(archive.profile()['name'],'合成昵称')
                self.assertEqual(archive.profile()['alias'],'synthetic_alias')
                self.assertTrue(archive.profile()['avatar_url'].startswith('data:image/png'))
                self.assertEqual(len(archive.sessions()),1)
                json.dumps(archive.profile())
                self.assertEqual(archive.avatars.blob(USER),PNG)
            finally:archive.close()


class ExportPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        cache_patch=patch('core.media_codec.app_data_root',return_value=self.root/'app-state')
        cache_patch.start();self.addCleanup(cache_patch.stop)
        self.lib=media_fixture(self.root)
        self.archive=Archive(self.lib)
        self.session=self.archive.sessions()[0]

    def tearDown(self):
        self.archive.close();self.temporary.cleanup()

    def export(self,options,name='out'):
        folder=self.root/name;folder.mkdir()
        return export_session(self.archive,self.session,{'format':'json',**options},folder,ASSETS,lambda _:None,lambda:None)

    def test_skipped_video_is_kept_as_a_message_without_reading_or_transcoding_it(self):
        original=ResourceStore._candidates
        def candidates(store,message):
            self.assertNotEqual(message['kind'],'video')
            return original(store,message)
        with patch.object(ResourceStore,'_candidates',candidates),patch('core.media_codec.MediaCodec.video',side_effect=AssertionError('Skipped video must not be read/transcoded')):
            rows=json_rows(self.export({'skipDownloadResourceTypes':['video']}))
        by_id={row['server_id']:row for row in rows}
        self.assertEqual(by_id['11']['kind'],'video')
        self.assertEqual(by_id['11']['resource_status'],'skipped')
        self.assertEqual(by_id['11']['resources'],[])
        self.assertEqual(by_id['10']['resources'][0]['status'],'available')
        self.assertEqual(by_id['14']['resources'][0]['kind'],'file')
        self.assertFalse(list((self.root/'out').rglob('*.mp4')))

    def test_skipped_images_include_emoji_and_card_thumbnails_without_network_access(self):
        original=self.archive.messages
        image=next(row for row in original(SESSION) if row['server_id']=='10')
        emoji=dict(image,server_id='emoji',kind='emoji')
        card=dict(image,server_id='card',kind='link',text='共享链接',extra={'title':'示例','url':'https://example.com'},
                  _media={'urls':[{'url':'https://mmbiz.qpic.cn/fictional','role':'thumbnail'}]})
        with patch.object(self.archive,'messages',side_effect=lambda *a,**k:iter([image,emoji,card])),patch.object(ResourceStore,'_candidates',side_effect=AssertionError('Image lookup must be skipped')),patch.object(ResourceStore,'_download',side_effect=AssertionError('Image download must be skipped')):
            rows=json_rows(self.export({'skipDownloadResourceTypes':['image']}))
        self.assertEqual(len(rows),3)
        self.assertTrue(all(row['resource_status']=='skipped' and row['resources']==[] for row in rows))
        self.assertTrue(all(row['avatar'] for row in rows))

    def test_skip_voice_and_file_metadata_leave_no_binary_attachments(self):
        original=list(self.archive.messages(SESSION))
        voice=dict(original[0],server_id='voice',kind='voice',text='[语音]')
        file=next(row for row in original if row['server_id']=='14')
        with patch.object(self.archive,'messages',side_effect=lambda *a,**k:iter([voice,file])),patch.object(self.archive.data,'voice_blob',side_effect=AssertionError('Voice blob must not be read')),patch.object(ResourceStore,'_candidates',side_effect=AssertionError('File lookup must be skipped')):
            rows=json_rows(self.export({'skipDownloadResourceTypes':['audio','file'],'includeAvatars':False}))
        self.assertEqual(rows[1]['extra']['filename'],'fixture.pdf')
        self.assertTrue(all(row['resource_status']=='skipped' and row['resources']==[] and not row['avatar'] for row in rows))
        self.assertFalse(list((self.root/'out').rglob('resources')))

    def test_quick_export_avoids_all_media_operations_in_every_format(self):
        with ExitStack() as stack:
            for target in ['core.resources.ResourceStore._candidates','core.resources.ResourceStore._network',
                           'core.resources.ResourceStore._index_forward_media','core.avatars.AvatarStore.export',
                           'core.media_codec.ImageKeys.decode','core.media_codec.MediaCodec.video']:
                stack.enter_context(patch(target,side_effect=AssertionError('Quick export touched media: '+target)))
            for fmt in ('html','json','jsonl','txt','csv','md'):
                with self.subTest(format=fmt):
                    result=self.export({'format':fmt,'quickExport':True},fmt)
                    self.assertEqual(result['count'],8)
                    self.assertEqual(result['resource_summary']['missing'],0)
                    self.assertEqual(result['resource_summary']['available'],0)
                    self.assertGreaterEqual(result['resource_summary']['skipped'],4)
                    self.assertFalse(list((self.root/fmt).rglob('resources')))
                    self.assertFalse(list((self.root/fmt).rglob('avatars')))

    def test_forwards_and_replies_follow_resource_and_system_message_preferences(self):
        original=list(self.archive.messages(SESSION))
        video=next(row for row in original if row['server_id']=='11')
        image=next(row for row in original if row['server_id']=='10')
        system=dict(original[0],server_id='system',kind='system',type=10002,text='合成系统通知')
        forward=dict(original[0],server_id='forward',kind='chatrecord',forward={'title':'合成转发','messages':[video,system,image]})
        reply=dict(original[0],server_id='reply',kind='quote',_quote={'server_id':'11'})
        with patch.object(self.archive,'messages',side_effect=lambda *a,**k:iter([forward,reply,system])),patch.object(ResourceStore,'_candidates',side_effect=AssertionError('Nested media must be skipped')),patch.object(ResourceStore,'_network',side_effect=AssertionError('Nested network must be skipped')),patch.object(ResourceStore,'_index_forward_media',side_effect=AssertionError('Quick export must not index attachments')):
            rows=json_rows(self.export({'quickExport':True,'includeSystemMessages':False}))
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['forward']['count'],2)
        self.assertTrue(all(row['resource_status']=='skipped' and not row['resources'] for row in rows[0]['forward']['messages']))
        self.assertEqual(rows[1]['quote']['resource_status'],'skipped')
        self.assertFalse(rows[1]['quote']['resources'])

    def test_system_message_types_are_filtered_before_exporting(self):
        self.archive.close()
        table='Msg_'+hashlib.md5(SESSION.encode()).hexdigest()
        with closing(sqlite3.connect(self.root/'db/message/message_0.db')) as con,con:
            for i,kind in enumerate((10000,10002),30):
                con.execute('INSERT INTO "'+table+'" VALUES (?,?,?,?,?,?,?,?,?)',(i,str(i),kind,i,0,1800000100+i,'合成系统通知',None,None))
        self.archive=Archive(self.lib)
        all_rows=json_rows(self.export({'quickExport':True},'with-system'))
        filtered=json_rows(self.export({'quickExport':True,'includeSystemMessages':False},'without-system'))
        self.assertEqual(len(all_rows)-len(filtered),2)
        self.assertFalse(any(row['kind']=='system' for row in filtered))

    def test_bridge_options_reach_the_export_job(self):
        service=Service(ASSETS,self.root/'service-state');service.library=self.lib
        service.config['export_dir']=str(self.root/'service-out')
        try:
            job=service.export({'sessions':[SESSION],'format':'json','skipDownloadResourceTypes':['video'],'includeAvatars':False})
            service.pool.shutdown(wait=True)
            task=next(task for task in service.state()['tasks'] if task['id']==job['job'])
            self.assertEqual(task['status'],'completed')
            rows=json.loads(service.task_file(job['job']).read_text(encoding='utf-8'))['messages']
            self.assertEqual(next(row for row in rows if row['server_id']=='11')['resource_status'],'skipped')
            self.assertTrue(all(not row['avatar'] for row in rows))
        finally:service.shutdown()

    def test_preferences_are_validated_and_quick_export_has_priority(self):
        result=options_from({'quickExport':True,'includeAvatars':True,'skipDownloadResourceTypes':['video','video']})
        self.assertFalse(result['include_avatars'])
        self.assertEqual(result['skip_resource_types'],['image','video','audio','file'])
        for payload in [{'quickExport':'false'},{'skipDownloadResourceTypes':'video'},{'skipDownloadResourceTypes':['unknown']}]:
            with self.assertRaises(ValueError):export_preferences(payload)


if __name__=='__main__':unittest.main()
