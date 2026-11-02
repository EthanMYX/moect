"""Author console tests use temporary keys and mocked transport; no real publication."""
import hashlib
import io
import json
import tempfile
import threading
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch

from Cryptodome.PublicKey import ECC
from scripts import publish_channel as channel
from core.publisher_cloud import CloudflareR2,NoRedirect
from core.publisher_service import PublisherService
from core.online_protocol import verify_feed
from core.publisher_paths import migrate_author_data,legacy_author_roots,oauth_path,physical_path
from tests.test_resources import PNG


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source';(self.source/'ui').mkdir(parents=True)
        self.author=self.root/'author';self.author.mkdir()
        self.key=ECC.generate(curve='Ed25519');self.public=self.key.public_key().export_key(format='PEM')
        self.config={'endpoint':'https://updates.example.invalid/channel/stable.json','hosts':['updates.example.invalid'],'public_key':self.public}
        (self.source/'ui/online-config.json').write_text(json.dumps(self.config),encoding='utf-8')
        (self.author/'signing-key.pem').write_text(self.key.export_key(format='PEM'),encoding='utf-8')
        self.cloud={'account_id':'0'*32,'bucket':'moect-test','control_backend':'r2'}
        (self.author/'cloudflare.json').write_text(json.dumps(self.cloud),encoding='utf-8')
        self.draft={'schema':1,'channel':'stable','sequence':0,'announcements':[],'release':None}
        (self.author/'draft.json').write_text(json.dumps(self.draft),encoding='utf-8')
        for name,value in [('ROOT',self.author),('SOURCE',self.source)]:
            p=patch.object(channel,name,value);p.start();self.addCleanup(p.stop)

    def service(self):
        service=PublisherService();self.addCleanup(service.close);return service

    def notice(self):
        (self.author/'picture.png').write_bytes(PNG)
        body=self.author/'notice.md';body.write_text('## Synthetic\n\n![image](picture.png)\n\n[Link](https://example.com)',encoding='utf-8')
        return channel.prepare_announcement(channel.load_draft(),'Synthetic notice',body,uid='synthetic-notice')

    def test_missing_original_key_never_generates_a_replacement(self):
        (self.author/'signing-key.pem').unlink()
        with self.assertRaisesRegex(ValueError,'原发布签名私钥'):channel.initialize('example.invalid')
        self.assertFalse((self.author/'signing-key.pem').exists())
        service=self.service();self.assertTrue(service.setup_error)
        with self.assertRaises(ValueError):service.start({'kind':'announcement','title':'x','body':'x'})

    def test_recheck_recovers_after_the_original_key_is_restored_without_restart(self):
        path=self.author/'signing-key.pem';original=path.read_bytes();path.unlink()
        service=self.service();self.assertEqual(service.setup_error_code,'missing_key')
        self.assertEqual(service.status()['author_dir'],str(self.author))
        path.write_bytes(original)
        with patch('core.publisher_service.CloudflareR2') as cloud,patch('core.publisher_service.fetch_public',return_value=self.draft):
            service.check_sync();cloud.return_value.info.assert_called_once()
        self.assertFalse(service.setup_error);self.assertEqual(service.setup_error_code,'')
        self.assertEqual(path.read_bytes(),original)

    def test_recheck_recovers_from_a_transient_bundled_config_read_failure(self):
        read=Path.read_text;path=self.source/'ui/online-config.json';attempts=[]
        def transient(current,*args,**kwargs):
            if current==path and not attempts:attempts.append(True);raise PermissionError('Synthetic temporary file lock')
            return read(current,*args,**kwargs)
        with patch.object(Path,'read_text',transient):
            service=self.service();self.assertEqual(service.setup_error_code,'unreadable_trust')
            self.assertTrue(service.refresh_setup())
        self.assertFalse(service.setup_error)

    def test_key_errors_are_distinct_and_never_overwrite_the_key(self):
        path=self.author/'signing-key.pem'
        cases=[('invalid_key','not a key'),('invalid_key',self.public),('key_mismatch',ECC.generate(curve='Ed25519').export_key(format='PEM'))]
        for code,content in cases:
            with self.subTest(code=code,public_only=content==self.public):
                path.write_text(content,encoding='utf-8');original=path.read_bytes();service=self.service()
                self.assertEqual(service.setup_error_code,code)
                with self.assertRaises(ValueError):service.start({'kind':'announcement','title':'x','body':'x'})
                self.assertEqual(path.read_bytes(),original)

    def test_equivalent_pem_line_endings_and_utf8_bom_do_not_look_like_a_key_mismatch(self):
        trust={**self.config,'public_key':self.public.replace('\n','\r\n')}
        (self.source/'ui/online-config.json').write_text(json.dumps(trust),encoding='utf-8-sig')
        (self.author/'signing-key.pem').write_text(self.key.export_key(format='PEM'),encoding='utf-8-sig')
        service=self.service();self.assertFalse(service.setup_error)

    def test_malformed_trust_is_not_reported_as_a_lost_author_key(self):
        path=self.source/'ui/online-config.json';key=(self.author/'signing-key.pem').read_bytes()
        for content in ('[]','not json',json.dumps({**self.config,'public_key':'bad key'}),json.dumps({**self.config,'public_key':self.key.export_key(format='PEM')})):
            with self.subTest(config=content[:8]):
                path.write_text(content,encoding='utf-8');service=self.service()
                self.assertEqual(service.setup_error_code,'invalid_trust')
                self.assertEqual((self.author/'signing-key.pem').read_bytes(),key)

    def test_frozen_start_does_not_rewrite_bundled_trust(self):
        path=self.source/'ui/online-config.json';original=path.read_bytes()
        with patch.object(channel.sys,'frozen',True,create=True):channel.initialize('example.invalid')
        self.assertEqual(path.read_bytes(),original)

    def test_images_are_uploaded_before_signed_index_with_correct_hashes(self):
        draft,uploads=self.notice();seen=[]
        def put(path,key,index=False,progress=None,expected=None):
            self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(),expected)
            if index:
                parsed=verify_feed(json.loads(Path(path).read_text()),self.public,set(self.config['hosts']))
                self.assertEqual(parsed['announcements'][0]['id'],'synthetic-notice')
            seen.append(key)
            if progress:progress(Path(path).stat().st_size,Path(path).stat().st_size)
        with patch('core.publisher_cloud.CloudflareR2') as client:
            client.return_value.put.side_effect=put
            result=channel.publish(draft,uploads)
        self.assertTrue(result['published']);self.assertEqual(seen[-1],'channel/stable.json');self.assertEqual(len(seen),2)
        self.assertEqual(channel.load_draft()['sequence'],result['sequence'])

    def test_resource_failure_and_modified_files_do_not_advance_index_or_local_state(self):
        for changed in (False,True):
            with self.subTest(changed=changed):
                draft,uploads=self.notice()
                if changed:uploads[0][0].write_bytes(PNG+b'changed')
                with patch('core.publisher_cloud.CloudflareR2') as client:
                    client.return_value.put.side_effect=ValueError('Synthetic network failure')
                    with self.assertRaises(ValueError):channel.publish(draft,uploads)
                    self.assertFalse(any(c.args[1]=='channel/stable.json' for c in client.return_value.put.call_args_list))
                self.assertEqual(channel.load_draft()['sequence'],0)

    def test_dry_run_does_not_connect_and_stale_draft_cannot_overwrite(self):
        draft,uploads=self.notice()
        with patch('core.publisher_cloud.CloudflareR2',side_effect=AssertionError('Dry run must not connect')):
            self.assertTrue(channel.publish(draft,uploads,dry_run=True)['prepared'])
        stale={**draft,'sequence':999}
        with self.assertRaisesRegex(ValueError,'记录已发生变化'):channel.publish(stale,uploads)

    def test_publication_lock_rejects_another_process_style_lock(self):
        with channel.publish_lock():
            with self.assertRaisesRegex(ValueError,'另一个发布任务'):channel.publish(self.draft,dry_run=True)

    def test_editor_persists_without_touching_the_published_feed(self):
        service=self.service();original=(self.author/'draft.json').read_bytes()
        service.save_editor({'title':'Unpublished','body':'draft','days':30,'tab':'announcement'})
        other=self.service();self.assertEqual(other.editor['title'],'Unpublished')
        self.assertEqual((self.author/'draft.json').read_bytes(),original)
        with self.assertRaises(ValueError):service.save_editor({'days':-1})

    def test_local_images_preview_and_import_are_bounded_to_editor_assets(self):
        service=self.service();file=self.root/'picture with space.png';file.write_bytes(PNG)
        cached=service.add_image(file);self.assertTrue(cached['source'].startswith('editor-images/'))
        self.assertTrue(service.preview_image(cached['source'])['url'].startswith('data:image/png;base64,'))
        self.assertEqual(service.preview_image('../signing-key.pem'),{'url':''})
        self.assertEqual(service.preview_image('https://tracker.invalid/pixel'),{'url':''})
        body=self.root/'body.md';body.write_text('![x](picture%20with%20space.png)',encoding='utf-8')
        imported=service.import_markdown(body)['body'];self.assertIn('editor-images/',imported);self.assertNotIn(str(self.root),imported)

    def test_import_cannot_implicitly_attach_images_outside_the_document_folder(self):
        service=self.service();folder=self.root/'document';folder.mkdir()
        (self.root/'private.png').write_bytes(PNG)
        document=folder/'untrusted.md';document.write_text('![image](../private.png)',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'所在文件夹'):service.import_markdown(document)
        self.assertFalse((self.author/'editor-images').exists())

    def test_published_image_preview_requires_an_approved_url_and_matching_hash(self):
        service=self.service();draft,uploads=self.notice()
        (self.author/'draft.json').write_text(json.dumps(draft),encoding='utf-8')
        url=next(iter(draft['announcements'][0]['assets']))
        with patch('core.publisher_service.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=io.BytesIO(PNG)
            self.assertTrue(service.preview_image(url)['url'].startswith('data:image/png;base64,'))
            self.assertEqual(service.preview_image('https://untrusted.invalid/image.png'),{'url':''})
            self.assertEqual(opener.return_value.open.call_count,1)

    def test_malformed_editor_state_falls_back_without_changing_signing_identity(self):
        (self.author/'editor-state.json').write_text('[]',encoding='utf-8')
        (self.author/'publisher-ui.json').write_text('[]',encoding='utf-8')
        service=self.service();self.assertFalse(service.setup_error);self.assertEqual(service.editor,{})
        self.assertIsInstance(service.config,dict)

    def test_release_does_not_silently_publish_unsupported_local_images(self):
        with self.assertRaisesRegex(ValueError,'更新说明请使用文字'):channel.prepare_release(self.draft,'1.2.1',notes='![private](image.png)')

    def test_announcement_job_captures_input_and_retains_release_and_history(self):
        service=self.service();captured=[]
        def publish(draft,uploads,progress=None):
            captured.append(draft);draft={**draft,'sequence':10}
            (self.author/'draft.json').write_text(json.dumps(draft),encoding='utf-8')
            return {'published':True,'sequence':10,'version':'','announcements':1}
        payload={'kind':'announcement','title':'Original','body':'Original body','days':30}
        with patch.object(channel,'publish',side_effect=publish),patch('core.publisher_service.fetch_public',return_value={'sequence':10}):
            service.start(payload);payload['title']='changed after starting';service.pool.shutdown(wait=True)
        self.assertEqual(captured[0]['announcements'][0]['title'],'Original')
        self.assertEqual(service.status()['job']['status'],'done');self.assertEqual(len(service.history),1)
        self.assertEqual(self.service().history[0]['title'],'Original')

    def test_busy_job_blocks_duplicate_publication(self):
        service=self.service();started=threading.Event();finish=threading.Event()
        def work():started.set();finish.wait(3);return {'message':'done'}
        try:
            service._run('synthetic',work);self.assertTrue(started.wait(2))
            with self.assertRaisesRegex(ValueError,'已有任务'):service.start({'kind':'withdraw_release'})
        finally:finish.set();service.pool.shutdown(wait=True)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.auth=self.root/'default.toml'
        self.auth.write_text('oauth_token = "synthetic-token"\nrefresh_token = "synthetic-refresh"\nexpiration_time = "2000-01-01T00:00:00Z"\nscopes = ["workers:write"]\n',encoding='utf-8')
        self.client=CloudflareR2({'account_id':'0'*32,'bucket':'moect-test'},self.auth)
        self.env=patch.dict('os.environ',{'CLOUDFLARE_API_TOKEN':''});self.env.start();self.addCleanup(self.env.stop)

    def test_oauth_refresh_is_local_atomic_and_preserves_scopes(self):
        result={'access_token':'synthetic-new-token','refresh_token':'synthetic-new-refresh','expires_in':3600}
        with patch.object(self.client.opener,'open',return_value=io.BytesIO(json.dumps(result).encode())) as opened:
            self.assertEqual(self.client.token(),'synthetic-new-token')
            self.assertEqual(self.client.token(),'synthetic-new-token');self.assertEqual(opened.call_count,1)
        saved=self.client._credentials();self.assertEqual(saved['refresh_token'],'synthetic-new-refresh');self.assertEqual(saved['scopes'],['workers:write'])
        self.assertFalse(self.auth.with_suffix('.moect.tmp').exists())

    def test_native_upload_stream_is_scoped_to_bucket_and_checks_sent_digest(self):
        path=self.root/'public.png';path.write_bytes(PNG);progress=[]
        def upload(request,timeout):
            self.assertEqual(request.full_url,'https://api.cloudflare.com/client/v4/accounts/'+'0'*32+'/r2/buckets/moect-test/objects/assets/public.png')
            self.assertEqual(request.get_method(),'PUT');self.assertEqual(b''.join(request.data),PNG)
            self.assertEqual(request.get_header('Authorization'),'Bearer synthetic-token')
            return io.BytesIO(b'{}')
        with patch.object(self.client,'token',return_value='synthetic-token'),patch.object(self.client.opener,'open',side_effect=upload):
            self.client.put(path,'assets/public.png',expected=hashlib.sha256(PNG).hexdigest(),progress=lambda a,b:progress.append((a,b)))
            with self.assertRaisesRegex(ValueError,'资源发生变化'):self.client.put(path,'assets/public.png',expected='0'*64)
        self.assertEqual(progress[-1],(len(PNG),len(PNG)))
        with self.assertRaises(ValueError):self.client.put(path,'../private.pem')

    def test_redirects_never_forward_authorization(self):
        with self.assertRaisesRegex(ValueError,'重定向'):NoRedirect().redirect_request(None,None,302,'',{},'https://other.invalid')


class PublisherStorageTests(unittest.TestCase):
    def setUp(self):
        support=Path(__file__).resolve().parents[1]/'build-support';support.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=support);self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.key=ECC.generate(curve='Ed25519');self.public=self.key.public_key().export_key(format='PEM')
        self.legacy=self.root/'legacy';self.legacy.mkdir();(self.legacy/'signing-key.pem').write_text(self.key.export_key(format='PEM'))
        self.target=self.root/'stable'

    def test_matching_original_identity_and_drafts_migrate_without_deleting_the_source(self):
        (self.legacy/'draft.json').write_text('{"sequence":42}')
        (self.legacy/'cloudflare.json').write_text('{"bucket":"synthetic"}')
        images=self.legacy/'editor-images';images.mkdir();(images/'synthetic.png').write_bytes(PNG)
        unrelated=self.legacy/'webview2';unrelated.mkdir();(unrelated/'cache').write_text('cache')
        original=(self.legacy/'signing-key.pem').read_bytes()
        self.assertEqual(migrate_author_data(self.target,[self.legacy],self.public),self.legacy)
        self.assertEqual((self.target/'signing-key.pem').read_bytes(),original)
        self.assertEqual((self.legacy/'signing-key.pem').read_bytes(),original)
        self.assertEqual((self.target/'editor-images/synthetic.png').read_bytes(),PNG)
        self.assertEqual(json.loads((self.target/'draft.json').read_text())['sequence'],42)
        self.assertFalse((self.target/'webview2').exists());self.assertEqual(physical_path(self.target),self.target)

    def test_wrong_identity_is_not_migrated_and_existing_destination_files_are_preserved(self):
        other=ECC.generate(curve='Ed25519').public_key().export_key(format='PEM')
        self.assertIsNone(migrate_author_data(self.target,[self.legacy],other));self.assertFalse(self.target.exists())
        self.target.mkdir();(self.target/'editor-state.json').write_text('Existing draft')
        (self.legacy/'editor-state.json').write_text('Old draft')
        migrate_author_data(self.target,[self.legacy],self.public)
        self.assertEqual((self.target/'editor-state.json').read_text(),'Existing draft')
        (self.target/'signing-key.pem').write_text('Existing protected file')
        self.assertIsNone(migrate_author_data(self.target,[self.legacy],self.public))
        self.assertEqual((self.target/'signing-key.pem').read_text(),'Existing protected file')

    def test_unpacked_launch_discovers_legacy_msix_author_and_shared_oauth(self):
        profile=self.root/'profile';cache=profile/'AppData/Local/Packages/OpenAI.Codex_synthetic/LocalCache'
        author=cache/'Local/MoectPublisher';author.mkdir(parents=True)
        (author/'signing-key.pem').write_text(self.key.export_key(format='PEM'))
        auth=cache/'Roaming/xdg.config/.wrangler/config/default.toml';auth.parent.mkdir(parents=True);auth.write_text('synthetic')
        with patch.dict('os.environ',{'USERPROFILE':str(profile),'LOCALAPPDATA':str(profile/'AppData/Local'),'APPDATA':str(profile/'AppData/Roaming')}):
            self.assertIn(author,legacy_author_roots());self.assertEqual(oauth_path(),auth)
        migrate_author_data(self.target,[author],self.public)
        self.assertTrue((self.target/'signing-key.pem').is_file())


if __name__=='__main__':unittest.main()
