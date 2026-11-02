"""Signed synthetic public feeds, no real account/network/installed-app mutations."""
import copy
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
from Cryptodome.PublicKey import ECC
from core.online import OnlineChannel
from core.online_protocol import sign_feed,verify_feed,version,web_url
from core.service import Service
from core.update_apply import unpack_portable,replace_portable
from tests.test_resources import PNG


def fixture_feed():
    now=datetime.now(timezone.utc)
    return {'schema':1,'channel':'stable','sequence':10,'issued_at':now.isoformat(),'expires_at':(now+timedelta(days=5)).isoformat(),
            'announcements':[{'id':'synthetic-1','title':'Synthetic notice','body':'## Hello\n\n[Link](https://example.com)\n\n![Image](https://updates.example.invalid/image.png)','published_at':now.isoformat(),'assets':{'https://updates.example.invalid/image.png':hashlib.sha256(PNG).hexdigest()}}],
            'release':{'version':'99.0.0','published_at':now.isoformat(),'platform':'windows-x64','notes':'Synthetic release','packages':{'installer':{'url':'https://updates.example.invalid/update.exe','size':20,'sha256':hashlib.sha256(b'MZ'+b'x'*18).hexdigest()}}}}


class OnlineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.key=ECC.generate(curve='Ed25519');self.public=self.key.public_key().export_key(format='PEM')
        self.config={'endpoint':'https://updates.example.invalid/channel/stable.json','public_key':self.public,'hosts':['updates.example.invalid']}
        assets=self.root/'assets';assets.mkdir();(assets/'online-config.json').write_text(json.dumps(self.config))
        self.service=Service(assets,self.root/'state');self.addCleanup(self.service.shutdown);self.online=self.service.online;self.feed=fixture_feed()
        self.accept()

    def accept(self,feed=None):self.online._accept(sign_feed(feed or self.feed,self.key.export_key(format='PEM')))

    def test_signature_rejects_changed_payload_wrong_key_expiry_replay_and_untrusted_url(self):
        good=sign_feed(self.feed,self.key.export_key(format='PEM'));self.assertEqual(verify_feed(good,self.public,set(self.config['hosts']))['sequence'],10)
        invalid=copy.deepcopy(good);invalid['signature']='A'*88
        with self.assertRaises(ValueError):verify_feed(invalid,self.public,set(self.config['hosts']))
        with self.assertRaises(ValueError):verify_feed(good,ECC.generate(curve='Ed25519').public_key().export_key(format='PEM'),set(self.config['hosts']))
        with self.assertRaises(ValueError):verify_feed(good,self.public,set(self.config['hosts']),minimum_sequence=11)
        with self.assertRaises(ValueError):verify_feed(good,self.public,set(self.config['hosts']),now=datetime.now(timezone.utc).timestamp()+10*86400)
        changed=copy.deepcopy(self.feed);changed['release']['packages']['installer']['url']='https://untrusted.invalid/download.exe'
        with self.assertRaises(ValueError):self.accept(changed)
        for value in ('javascript:alert(1)','file:///c:/secret','https://user:pass@example.com/','https://example.com:80/','https://example.com/\n'):
            with self.assertRaises(ValueError):web_url(value)
        self.assertGreater(version('1.10.0'),version('1.2.0'))

    def test_two_seconds_count_only_foreground_and_confirm_persists_across_logout_restart(self):
        clock=[100.]
        with patch('core.online.time.monotonic',side_effect=lambda:clock[0]):
            with self.assertRaises(ValueError):self.online.notice_read({'id':'synthetic-1'})
            self.online.notice_focus({'id':'synthetic-1','active':True});clock[0]+=1
            self.online.notice_focus({'id':'synthetic-1','active':False});clock[0]+=20
            with self.assertRaises(ValueError):self.online.notice_read({'id':'synthetic-1'})
            self.online.notice_focus({'id':'synthetic-1','active':True});clock[0]+=1.1
            self.online.notice_read({'id':'synthetic-1'})
        self.service.logout();self.assertEqual(self.online.status()['unread_count'],0)
        other=OnlineChannel(self.service,self.config)
        try:self.assertEqual(other.status()['unread_count'],0)
        finally:other.close()
        new=copy.deepcopy(self.feed);new['sequence']=11;new['announcements'].append({**new['announcements'][0],'id':'synthetic-2'})
        self.accept(new);self.assertEqual(self.online.status()['unread_count'],1)

    def test_read_save_failure_does_not_consume_notice(self):
        self.online.visible['synthetic-1']=(2.1,None)
        with patch.object(self.online,'_save',side_effect=OSError('Synthetic failure')):
            with self.assertRaises(ValueError):self.online.notice_read({'id':'synthetic-1'})
        self.assertEqual(self.online.status()['unread_count'],1)

    def test_expired_future_and_incompatible_notices_are_not_displayed(self):
        data=copy.deepcopy(self.feed);n=data['announcements'][0];n['expires_at']=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat();self.accept(data);self.assertEqual(self.online.status()['unread_count'],0)
        data=copy.deepcopy(self.feed);data['announcements'][0]['published_at']=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat();self.accept(data);self.assertEqual(self.online.status()['unread_count'],0)
        data=copy.deepcopy(self.feed);data['announcements'][0]['min_version']='99.0.0';self.accept(data);self.assertEqual(self.online.status()['unread_count'],0)

    def test_images_require_signed_hash_are_local_data_and_cache_reused(self):
        with patch.object(self.online,'_bytes',return_value=PNG) as fetch:
            image=self.online.image({'url':'https://updates.example.invalid/image.png'});self.assertTrue(image['url'].startswith('data:image/png;base64,'));self.online.image({'url':'https://updates.example.invalid/image.png'});self.assertEqual(fetch.call_count,1)
        with patch.object(self.online,'_bytes',side_effect=AssertionError('Untrusted images must never fetch')):
            self.assertEqual(self.online.image({'url':'https://tracker.example.invalid/test'}),{'url':''})

    def test_download_bytes_and_hash_are_verified_and_source_cannot_apply(self):
        response=io.BytesIO(b'MZ'+b'x'*18)
        with patch.object(self.online,'_opener') as opener:
            opener.return_value.open.return_value=response
            self.online.download_update();self.online.pool.shutdown(wait=True)
        self.assertEqual(self.online.status()['download']['status'],'ready')
        with self.assertRaisesRegex(ValueError,'源码'):self.online.prepare_apply()

    def test_download_mismatch_never_reaches_ready(self):
        with patch.object(self.online,'_opener') as opener:
            opener.return_value.open.return_value=io.BytesIO(b'wrong')
            self.online.download_update();self.online.pool.shutdown(wait=True)
        self.assertEqual(self.online.status()['download']['status'],'failed')
        self.assertFalse(list((self.online.root/'downloads').glob('*.exe')))

    def test_windows_11_download_ignores_manifest_virtualized_windows_8_build(self):
        from types import SimpleNamespace
        reported=SimpleNamespace(build=9200,platform_version=(10,0,26100))
        with patch('core.windows_version.sys.platform','win32'),patch('core.windows_version._rtl_version',return_value=(10,0,26100)),patch('core.windows_version.sys.getwindowsversion',return_value=reported,create=True),patch.object(self.online,'_opener') as opener:
            opener.return_value.open.return_value=io.BytesIO(b'MZ'+b'x'*18)
            self.online.download_update();self.online.pool.shutdown(wait=True)
        self.assertEqual(self.online.status()['download']['status'],'ready')

    def test_genuinely_unsupported_windows_stops_before_downloading(self):
        self.feed['release']['minimum_windows_build']=26100;self.accept()
        with patch('core.windows_version.sys.platform','win32'),patch('core.windows_version.windows_version',return_value=(10,0,19045)),patch.object(self.online.pool,'submit') as submit:
            with self.assertRaisesRegex(ValueError,'26100.*19045'):self.online.download_update()
        submit.assert_not_called();self.assertFalse(self.online.downloading)

    def test_apply_rechecks_windows_requirement_before_launching_helper(self):
        self.feed['release']['minimum_windows_build']=28000;self.accept()
        app=self.ready_installer()
        with patch.object(self.online,'install_mode',return_value='installer'),patch('core.online.sys.executable',str(app/'Moect.exe')),patch('core.windows_version.sys.platform','win32'),patch('core.windows_version.windows_version',return_value=(10,0,26100)),patch('core.online.subprocess.Popen') as process:
            with self.assertRaisesRegex(ValueError,'28000.*26100'):self.online.prepare_apply()
        process.assert_not_called();self.assertFalse(self.service._updating)

    def test_static_parts_are_individually_verified_and_assembled_to_original_package(self):
        bodies=[b'MZ'+b'x'*7,b'x'*11];data=copy.deepcopy(self.feed);package=data['release']['packages']['installer'];package.pop('url')
        package['parts']=[{'url':f'https://updates.example.invalid/part{i}','size':len(blob),'sha256':hashlib.sha256(blob).hexdigest()} for i,blob in enumerate(bodies)]
        self.accept(data)
        with patch.object(self.online,'_opener') as opener:
            opener.return_value.open.side_effect=[io.BytesIO(blob) for blob in bodies]
            self.online.download_update();self.online.pool.shutdown(wait=True)
        self.assertEqual(self.online.status()['download']['status'],'ready');self.assertEqual(self.online.download_path.read_bytes(),b''.join(bodies))

    def test_part_size_mismatch_in_signed_manifest_is_rejected(self):
        data=copy.deepcopy(self.feed);package=data['release']['packages']['installer'];package.pop('url');package['parts']=[{'url':'https://updates.example.invalid/part','size':1,'sha256':'a'*64}]
        with self.assertRaisesRegex(ValueError,'总大小'):self.accept(data)

    def test_check_uses_independent_pool_and_startup_once(self):
        envelope=sign_feed(self.feed,self.key.export_key(format='PEM'))
        with patch.object(self.online,'_bytes',return_value=json.dumps(envelope).encode()) as fetch:
            self.online.check(True);self.online.pool.shutdown(wait=True);self.online.check(True);self.assertEqual(fetch.call_count,1)
        self.assertFalse(self.online.status()['checking']);self.assertTrue(self.online.status()['checked_at'])

    def test_update_notice_requires_a_strictly_higher_numeric_version(self):
        cases=[('1.2.0','1.1.5',False),('1.2.0','1.2.0',False),('1.2.0','1.2.1',True),
               ('1.2.0','1.3.0',True),('1.2.0','2.0.0',True),('1.9.0','1.10.0',True),('1.10.0','1.9.0',False)]
        for installed,published,expected in cases:
            with self.subTest(installed=installed,published=published),patch('core.online.VERSION',installed):
                data=copy.deepcopy(self.feed);data['release']['version']=published;self.accept(data)
                state=self.online.status(True)
                self.assertEqual(state['has_update'],expected)
                self.assertEqual(state['release'] is not None,expected)
                if not expected:
                    with patch.object(self.online.pool,'submit',side_effect=AssertionError('Equal/older releases must not download')):
                        with self.assertRaisesRegex(ValueError,'暂无可用'):self.online.download_update()

    def test_cached_release_stops_being_an_update_after_the_app_is_upgraded(self):
        data=copy.deepcopy(self.feed);data['release']['version']='1.3.0';self.accept(data)
        with patch('core.online.VERSION','1.3.0'):
            restarted=OnlineChannel(self.service,self.config)
            try:
                self.assertFalse(restarted.status()['has_update'])
                self.assertIsNone(restarted.status(True)['release'])
            finally:restarted.close()

    def ready_installer(self):
        app=self.root/'program';app.mkdir();(app/'Moect.exe').write_bytes(b'old');(app/'MoectUpdater.exe').write_bytes(b'synthetic helper')
        package=self.online.root/'downloads/synthetic.exe';package.parent.mkdir(exist_ok=True);package.write_bytes(b'MZ'+b'x'*18)
        self.online.download={'status':'ready'};self.online.download_path=package;self.online.download_envelope=sign_feed(self.feed,self.key.export_key(format='PEM'))
        current=patch('core.online.current_feed',return_value=(self.online.download_envelope,self.feed));current.start();self.addCleanup(current.stop)
        return app

    def test_apply_waits_for_jobs_and_uses_external_helper_before_rejecting_new_jobs(self):
        app=self.ready_installer();self.service.config['tasks']=[{'status':'running','kind':'export'}]
        with self.assertRaisesRegex(ValueError,'任务结束'):self.online.prepare_apply()
        self.service.config['tasks']=[]
        with patch.object(self.online,'install_mode',return_value='installer'),patch('core.online.sys.executable',str(app/'Moect.exe')),patch('core.online.subprocess.Popen') as process:
            self.assertEqual(self.online.prepare_apply(),{'ready':True})
            helper=Path(process.call_args.args[0][0]);self.assertFalse(helper.is_relative_to(app));self.assertTrue(helper.is_file())
        with self.assertRaisesRegex(ValueError,'更新'):self.service._new_job('export','Synthetic blocked export')

    def test_helper_launch_failure_allows_jobs_again(self):
        app=self.ready_installer()
        with patch.object(self.online,'install_mode',return_value='installer'),patch('core.online.sys.executable',str(app/'Moect.exe')),patch('core.online.subprocess.Popen',side_effect=OSError('Synthetic launch failure')):
            with self.assertRaises(OSError):self.online.prepare_apply()
        self.assertFalse(self.service._updating);self.assertFalse(self.online.apply_pending)


def program(folder,body,obsolete=False):
    (folder/'_internal').mkdir(parents=True);(folder/'Moect.exe').write_bytes(body);(folder/'_internal/runtime').write_bytes(body)
    names=['Moect.exe','_internal/runtime']
    if obsolete:(folder/'_internal/old.dll').write_bytes(b'old');names.append('_internal/old.dll')
    (folder/'program-files.json').write_text(json.dumps({'version':'1.2.0','files':names}))


class ApplyTests(unittest.TestCase):
    def test_portable_update_replaces_only_program_files_and_cleans_managed_old_dependency(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);old=root/'old';new=root/'new';program(old,b'old',True);program(new,b'new')
            (old/'my-exports').mkdir();(old/'my-exports/private.txt').write_text('keep');recovery=root/'backup';recovery.mkdir()
            replace_portable(old,new,recovery)
            self.assertEqual((old/'Moect.exe').read_bytes(),b'new');self.assertFalse((old/'_internal/old.dll').exists());self.assertEqual((old/'my-exports/private.txt').read_text(),'keep')

    def test_failed_replacement_restores_old_program(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);old=root/'old';new=root/'new';program(old,b'old');program(new,b'new');recovery=root/'backup';recovery.mkdir()
            with patch('core.update_apply.os.replace',side_effect=OSError('Synthetic locked file')):
                with self.assertRaises(OSError):replace_portable(old,new,recovery)
            self.assertEqual((old/'Moect.exe').read_bytes(),b'old');self.assertEqual((old/'_internal/runtime').read_bytes(),b'old')

    def test_zip_paths_are_checked_before_extraction(self):
        for name in ('../escape','Moect/../../escape','C:/escape','Moect/CON','Moect/a:stream','Moect/a\\b'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);package=root/'bad.zip'
                with zipfile.ZipFile(package,'w') as archive:archive.writestr(name,b'bad')
                stage=root/'stage';stage.mkdir()
                with self.assertRaises(ValueError):unpack_portable(package,stage)
                self.assertFalse((root/'escape').exists())


if __name__=='__main__':unittest.main()
