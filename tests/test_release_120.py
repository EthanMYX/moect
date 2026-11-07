"""Regression coverage for SNS identity/DAT decoding and reversible demo state."""
import hashlib
import json
import sqlite3
import struct
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import pad
from core.account_exporting import export_moments,local_moments_previews
from core.data import Archive
from core.service import Service
from tests.test_account_assets import asset_fixture,FAVORITE
from tests.test_core import USER
from tests.test_resources import ASSETS,PNG,MP4
from wx4.media import SIG_V2


class SnsCacheIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.library,_=asset_fixture(self.root)
        self.archive=Archive(self.library);self.addCleanup(self.archive.close)
        p=patch('core.media_codec.app_data_root',return_value=self.root/'private');p.start();self.addCleanup(p.stop)
        p=patch('core.media_codec.find_dat_aes_key',side_effect=AssertionError('Synthetic test must not scan a process'));p.start();self.addCleanup(p.stop)

    def prepare(self,cache_type=1,blob=PNG):
        post_id='18446744073709551601';media_id='18446744073709551602'
        with closing(sqlite3.connect(Path(self.library['root'])/'sns/sns.db')) as con,con:
            xml=con.execute('SELECT content FROM SnsTimeLine WHERE tid=100').fetchone()[0]
            xml=xml.replace('<id>100</id>',f'<id>{post_id}</id>').replace('<media><type>',f'<media><id>{media_id}</id><type>')
            con.execute('UPDATE SnsTimeLine SET content=? WHERE tid=100',(xml,))
        base=Path(self.library['account_dir'])/'cache/2026-11/Sns/Img'
        (base/FAVORITE[:2]/FAVORITE).unlink()
        digest=hashlib.md5(f'{post_id}_{media_id}_{cache_type}'.encode()).hexdigest()
        path=base/digest[:2]/digest[2:];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(blob)
        return path

    def export(self):
        destination=self.root/'export';destination.mkdir()
        export_moments(self.archive,self.library,{},destination,ASSETS,lambda *a:None,lambda:None,lambda _:None)
        data=json.loads((destination/'data.json').read_text(encoding='utf-8'))
        return destination,next(p for p in data['items'] if p['id']=='18446744073709551601')

    def test_split_identity_cached_thumbnail_is_used_for_preview_and_export_without_network(self):
        self.prepare()
        with patch('core.resources.ResourceStore._download',side_effect=AssertionError('No SNS downloads')):
            previews=local_moments_previews(self.archive,self.library,{'scope':'self','author_id':USER})
            self.assertEqual(len(next(p for p in previews if p['id']!='103')['thumbnails']),1)
            destination,post=self.export()
        resource=post['resources'][0]
        self.assertEqual(resource['role'],'thumbnail');self.assertEqual((destination/resource['path']).read_bytes(),PNG)

    def test_split_v2_cache_uses_existing_account_image_credentials(self):
        key=b'0123456789abcdef'
        raw=SIG_V2+struct.pack('<LL',len(PNG),0)+b'\x00'+AES.new(key,AES.MODE_ECB).encrypt(pad(PNG,16))
        self.prepare(cache_type=2,blob=raw)
        # Existing image credential storage follows the same account identity
        # as chat exports. No synthetic fixture contains a real account secret.
        identity=hashlib.sha256((str(Path(self.library['account_dir']).resolve())+'\0'+USER).encode()).hexdigest()
        cache=self.root/'private/media-cache'/identity/'image-keys.json';cache.parent.mkdir(parents=True)
        cache.write_text(json.dumps({'keys':[key.hex()]}))
        with patch('core.resources.ResourceStore._download',side_effect=AssertionError('No SNS downloads')):
            previews=local_moments_previews(self.archive,self.library,{'scope':'self','author_id':USER})
            destination,post=self.export()
        self.assertEqual(len(next(p for p in previews if p['id']!='103')['thumbnails']),1)
        self.assertEqual((destination/post['resources'][0]['path']).read_bytes(),PNG)
        self.assertEqual(post['resources'][0]['role'],'main')
        self.assertNotIn(key.hex(),(destination/'data.json').read_text(encoding='utf-8'))

    def test_incomplete_tmp_cache_is_rejected_by_decoder(self):
        path=self.prepare(blob=b'incomplete synthetic download');path.rename(path.with_suffix('.tmp'))
        destination,post=self.export()
        self.assertEqual(post['resources'],[]);self.assertIn('corrupt',post['media_status'])
        self.assertEqual(post['media_diagnostics'][0]['reason'],'image_decode_failed')

    def test_completed_tmp_cache_remains_usable_after_image_validation(self):
        path=self.prepare();path.rename(path.with_suffix('.tmp'))
        destination,post=self.export()
        self.assertEqual((destination/post['resources'][0]['path']).read_bytes(),PNG)

    def test_split_local_sns_video_is_exported_by_default_with_portable_playback(self):
        path=self.prepare(cache_type=3,blob=MP4)
        video=path.parent.parent.parent/'Video'/path.parent.name/(path.name+'.mp4')
        video.parent.mkdir(parents=True,exist_ok=True);path.rename(video)
        database=Path(self.library['root'])/'sns/sns.db'
        with closing(sqlite3.connect(database)) as con,con:
            xml=con.execute('SELECT content FROM SnsTimeLine WHERE tid=100').fetchone()[0]
            xml=xml.replace('<media><id>18446744073709551602</id><type>2</type>','<media><id>18446744073709551602</id><type>6</type>')
            con.execute('UPDATE SnsTimeLine SET content=? WHERE tid=100',(xml,))
        with patch('core.resources.ResourceStore._download',side_effect=AssertionError('No remote SNS video fetch')):
            destination,post=self.export()
        resource=post['resources'][0];self.assertEqual(resource['kind'],'video');self.assertEqual((destination/resource['path']).read_bytes(),MP4)
        self.assertIn("el.controls=true",(destination/'index.html').read_text(encoding='utf-8'))


class DemoAndOnboardingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.service=Service(ASSETS,self.temp.name);self.addCleanup(self.service.shutdown)

    def test_demo_returns_exact_snapshot_without_connecting_or_changing_tasks(self):
        original={'name':'Synthetic original','root':'synthetic-root','account_dir':'synthetic-account','wxid':USER,'profile':{'name':'Original','wxid':USER}}
        self.service.library=self.service.config['library']=original
        job={'id':'old','kind':'export','status':'completed','title':'Synthetic task'};self.service.config['tasks']=[job]
        with patch.object(self.service,'detect',side_effect=AssertionError('No detection')),patch.object(self.service,'connect',side_effect=AssertionError('No reconnection')):
            self.service.demo();self.service.demo()
            self.assertIs(self.service.config['library'],original)
            self.assertTrue(self.service.state()['library']['demo'])
            self.service.call('return_from_demo',{})
        self.assertIs(self.service.library,original);self.assertEqual(self.service.config['tasks'],[job])
        self.service.return_from_demo();self.assertIs(self.service.library,original)

    def test_empty_state_and_logout_cannot_restore_a_signed_out_account(self):
        self.service.demo();self.service.return_from_demo();self.assertIsNone(self.service.library)
        self.service.library={'name':'Backup','root':'synthetic-root'}
        self.service.demo();self.service.logout();self.service.return_from_demo();self.assertIsNone(self.service.library)
        self.service.demo();self.service.return_from_demo();self.assertIsNone(self.service.library)

    def test_first_launch_tutorial_is_independent_durable_and_replay_idempotent(self):
        self.assertFalse(self.service.call('tutorial_status',{'kind':'app'})['seen'])
        self.assertFalse(self.service.config_path.exists())
        with patch.object(self.service,'save',wraps=self.service.save) as save:
            self.service.call('tutorial_seen',{'kind':'app'});self.service.call('tutorial_seen',{'kind':'app'})
            self.assertEqual(save.call_count,1)
        reloaded=Service(ASSETS,self.temp.name)
        try:
            self.assertTrue(reloaded.call('tutorial_status',{'kind':'app'})['seen'])
            self.assertFalse(reloaded.call('tutorial_status',{'kind':'moments'})['seen'])
            self.assertFalse(reloaded.call('tutorial_status',{'kind':'stickers'})['seen'])
        finally:reloaded.shutdown()

    def test_failed_tutorial_save_can_retry_and_does_not_change_theme(self):
        self.service.settings({'theme':'dark','accent':'green'})
        with patch.object(self.service,'save',side_effect=OSError('Synthetic storage failure')):
            with self.assertRaises(ValueError):self.service.call('tutorial_seen',{'kind':'app'})
        self.assertFalse(self.service.call('tutorial_status',{'kind':'app'})['seen'])
        self.assertEqual(self.service.config['accent'],'green');self.assertEqual(self.service.config['theme'],'dark')


if __name__=='__main__':unittest.main()
