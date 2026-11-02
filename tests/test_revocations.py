"""Synthetic withdrawal/deletion transactions and client cache/installation revocation."""
import copy
import hashlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch

from tests import test_publisher as publishers
from tests import test_online as online_fixtures
from scripts import publish_channel as channel
from core.publisher_service import PublisherService
from core.channel_control import release_key,require_current_release,current_feed
from core.online_protocol import sign_feed,verify_feed
from core.publisher_cloud import CloudflareR2


class ManagementTests(unittest.TestCase):
    setUp=publishers.PublisherTests.setUp
    service=publishers.PublisherTests.service
    notice=publishers.PublisherTests.notice

    def fake_cloud(self,draft,uploads=()):
        draft=copy.deepcopy(draft);draft.update(sequence=10,issued_at=channel.utc(),expires_at=online_fixtures.fixture_feed()['expires_at'])
        self.remote=draft;self.objects={key:Path(path).read_bytes() for path,key in uploads};self.operations=[]
        (self.author/'draft.json').write_text(json.dumps(draft),encoding='utf-8')
        client=MagicMock()
        def put(path,key,index=False,progress=None,expected=None):
            self.operations.append(('put',key));blob=Path(path).read_bytes();self.objects[key]=blob
            self.assertEqual(hashlib.sha256(blob).hexdigest(),expected)
            if index:self.remote=verify_feed(json.loads(blob),self.public,set(self.config['hosts']))
        def delete(key):self.operations.append(('delete',key));self.objects.pop(key,None)
        client.put.side_effect=put;client.delete.side_effect=delete
        for target in ('core.publisher_cloud.CloudflareR2','core.publisher_management.CloudflareR2','core.publisher_service.CloudflareR2'):
            p=patch(target,return_value=client);p.start();self.addCleanup(p.stop)
        for target in ('core.publisher_management.fetch_public','core.publisher_service.fetch_public'):
            p=patch(target,side_effect=lambda *_:copy.deepcopy(self.remote));p.start();self.addCleanup(p.stop)
        return client

    def release(self):
        release=online_fixtures.fixture_feed()['release'];release['id']='synthetic-release'
        release['packages']['installer']['url']='https://updates.example.invalid/packages/99.0.0/update.exe'
        return release

    def test_withdraw_keeps_author_snapshot_and_resources_then_delete_removes_them(self):
        draft,uploads=self.notice();client=self.fake_cloud(draft,uploads);service=self.service()
        service.manage_content({'kind':'withdraw_notice','id':'synthetic-notice'})
        self.assertEqual(self.remote['announcements'],[]);client.delete.assert_not_called()
        retired=service.status()['retired'];self.assertEqual(len(retired),1);self.assertEqual(retired[0]['reason'],'withdrawn')
        self.assertIn('Synthetic',service.inspect_retired(retired[0]['id'])['item']['body'])
        service.manage_content({'kind':'delete_retired','id':retired[0]['id']})
        self.assertEqual(service.status()['retired'],[]);self.assertEqual(service.status()['cleanup_pending'],[])
        self.assertEqual(client.delete.call_count,1)

    def test_delete_live_content_commits_new_signed_index_before_deleting_any_object(self):
        draft,uploads=self.notice();self.fake_cloud(draft,uploads);service=self.service()
        result=service.manage_content({'kind':'delete_notice','id':'synthetic-notice'})
        self.assertEqual(self.remote['announcements'],[]);self.assertEqual(result['remaining'],0)
        self.assertEqual(self.operations[0],('put','channel/stable.json'));self.assertEqual(self.operations[1][0],'delete')
        self.assertEqual(service.status()['retired'],[])

    def test_shared_assets_referenced_by_another_announcement_are_never_deleted(self):
        draft,uploads=self.notice();draft['announcements'].append({**draft['announcements'][0],'id':'synthetic-shared','title':'Other notice'})
        client=self.fake_cloud(draft,uploads);service=self.service()
        result=service.manage_content({'kind':'delete_notice','id':'synthetic-notice'})
        self.assertEqual([n['id'] for n in self.remote['announcements']],['synthetic-shared']);self.assertEqual(result['protected'],1)
        client.delete.assert_not_called()

    def test_failed_resource_cleanup_is_durable_and_can_be_retried_without_republishing(self):
        draft,uploads=self.notice();client=self.fake_cloud(draft,uploads);service=self.service()
        client.delete.side_effect=ValueError('Synthetic network outage')
        result=service.manage_content({'kind':'delete_notice','id':'synthetic-notice'})
        self.assertEqual(result['remaining'],1);self.assertEqual(self.remote['announcements'],[])
        pending=service.status()['cleanup_pending'];self.assertEqual(pending[0]['remaining'],1)
        sequence=self.remote['sequence'];client.delete.side_effect=lambda key:self.objects.pop(key,None)
        service.manage_content({'kind':'retry_cleanup','id':pending[0]['id']})
        self.assertEqual(service.status()['cleanup_pending'],[]);self.assertEqual(self.remote['sequence'],sequence)

    def test_last_reference_cleans_shared_asset_even_if_its_original_notice_was_deleted(self):
        draft,uploads=self.notice();draft['announcements'].append({**draft['announcements'][0],'id':'synthetic-shared','title':'Other notice'})
        client=self.fake_cloud(draft,uploads);service=self.service()
        service.manage_content({'kind':'delete_notice','id':'synthetic-notice'});client.delete.assert_not_called()
        service.manage_content({'kind':'delete_notice','id':'synthetic-shared'})
        self.assertEqual(client.delete.call_count,1);self.assertEqual(self.remote['announcements'],[])

    def test_reused_legacy_notice_id_does_not_merge_distinct_retained_content(self):
        draft,uploads=self.notice();self.fake_cloud(draft,uploads);service=self.service();original=draft['announcements'][0]
        old=service._stage_retired('announcement',original,'withdrawn');service._commit_retired(old,10)
        changed={**original,'body':'A different synthetic notice with the same legacy ID'}
        new=service._stage_retired('announcement',changed,'deleting')
        self.assertNotEqual(old['id'],new['id']);self.assertEqual(len(service.status()['retired']),2)
        service._sync_retired({**self.remote,'announcements':[changed]})
        self.assertEqual([v['id'] for v in service.status()['retired']],[old['id']])

    def test_interrupted_delete_recovers_retained_removal_from_the_durable_cleanup_queue(self):
        draft,uploads=self.notice();client=self.fake_cloud(draft,uploads);service=self.service()
        service.manage_content({'kind':'withdraw_notice','id':'synthetic-notice'})
        entry=service.inspect_retired(service.status()['retired'][0]['id']);save=service._save_management
        def interrupted(name,value):
            if name=='retired.json':raise OSError('Synthetic interrupted local write')
            return save(name,value)
        with patch.object(service,'_save_management',side_effect=interrupted),self.assertRaises(OSError):service._delete_retired(entry,self.remote)
        client.delete.assert_not_called();self.assertTrue(service.status()['cleanup_pending'])
        service.manage_content({'kind':'retry_cleanup','id':entry['id']})
        self.assertFalse(service.status()['retired']);self.assertFalse(service.status()['cleanup_pending']);self.assertEqual(client.delete.call_count,1)

    def test_failed_withdraw_does_not_delete_cloud_files_or_lose_the_live_content(self):
        draft,uploads=self.notice();client=self.fake_cloud(draft,uploads);service=self.service()
        client.put.side_effect=ValueError('Synthetic index upload failure')
        with self.assertRaisesRegex(ValueError,'尚未确认'):service.manage_content({'kind':'delete_notice','id':'synthetic-notice'})
        client.delete.assert_not_called();self.assertEqual(len(self.remote['announcements']),1)
        self.assertTrue(service.status()['retired'][0]['pending'])
        service._sync_retired(self.remote);self.assertEqual(service.status()['retired'],[])

    def test_release_withdrawal_checks_the_exact_confirmed_release(self):
        draft,uploads=self.notice();draft['release']=self.release();client=self.fake_cloud(draft,uploads);service=self.service()
        with self.assertRaisesRegex(ValueError,'版本已变化'):service.manage_content({'kind':'withdraw_release','release_key':'stale'})
        client.put.assert_not_called();client.delete.assert_not_called()
        service.manage_content({'kind':'withdraw_release','release_key':release_key(draft['release'])})
        self.assertIsNone(self.remote['release']);self.assertEqual(len(self.remote['announcements']),1)
        client.delete.assert_not_called();self.assertEqual(service.status()['retired'][0]['kind'],'release')

    def test_deleting_an_old_release_does_not_delete_identical_resources_of_a_current_release(self):
        draft,_=self.notice();old=self.release();draft['release']={**old,'id':'new-publication'}
        client=self.fake_cloud(draft);service=self.service()
        entry=service._stage_retired('release',old,'withdrawn');service._commit_retired(entry,10)
        result=service.manage_content({'kind':'delete_retired','id':entry['id']})
        self.assertEqual(result['protected'],1);client.delete.assert_not_called();self.assertIsNotNone(self.remote['release'])

    def test_stale_public_feed_blocks_deletion(self):
        draft,uploads=self.notice();client=self.fake_cloud(draft,uploads);service=self.service();self.remote['sequence']=9
        with self.assertRaisesRegex(ValueError,'尚未同步'):service.manage_content({'kind':'delete_notice','id':'synthetic-notice'})
        client.delete.assert_not_called();client.put.assert_not_called()

    def test_r2_delete_cannot_target_the_feed_brand_assets_or_other_namespaces(self):
        client=CloudflareR2(self.cloud,auth_path=self.root/'unused')
        for key in ('channel/stable.json','assets/moect-icon.png','../private','packages/../private','announcements/a/../key','other/file'):
            with self.subTest(key=key),self.assertRaises(ValueError):client.delete(key)
        with patch.object(client,'token',return_value='synthetic'),patch.object(client.opener,'open',return_value=io.BytesIO(b'{}')) as sent:
            client.delete('packages/99.0.0/synthetic.exe')
        self.assertEqual(sent.call_args.args[0].get_method(),'DELETE')
        self.assertIn('/r2/buckets/moect-test/objects/packages/',sent.call_args.args[0].full_url)


class ClientRevocationTests(unittest.TestCase):
    setUp=online_fixtures.OnlineTests.setUp
    accept=online_fixtures.OnlineTests.accept
    ready_installer=online_fixtures.OnlineTests.ready_installer

    def revoked(self):
        data=copy.deepcopy(self.feed);data.update(sequence=11,announcements=[],release=None);return data

    def owned_ready(self):
        app=self.ready_installer();old=self.online.download_path
        target=old.parent/(self.feed['release']['packages']['installer']['sha256']+'.exe');old.rename(target);self.online.download_path=target
        return app,target

    def test_new_snapshot_removes_unread_notice_timer_and_its_unshared_image_cache(self):
        expected=self.feed['announcements'][0]['assets']['https://updates.example.invalid/image.png']
        image=self.online.root/'images'/expected;image.parent.mkdir(parents=True);image.write_bytes(b'public image')
        preserved=self.online.root/'images/private-note.txt';preserved.write_text('keep')
        self.online.visible['synthetic-1']=(1,None);self.accept(self.revoked())
        self.assertEqual(self.online.status()['unread_count'],0);self.assertEqual(self.online.visible,{})
        self.assertFalse(image.exists());self.assertEqual(preserved.read_text(),'keep')
        other=type(self.online)(self.service,self.config)
        try:self.assertEqual(other.status()['unread_count'],0)
        finally:other.close()

    def test_withdrawn_ready_package_is_unavailable_and_only_owned_cache_is_removed(self):
        app,target=self.owned_ready();unrelated=target.parent/'user-file.exe';unrelated.write_bytes(b'keep')
        self.accept(self.revoked())
        self.assertEqual(self.online.status()['download']['status'],'revoked');self.assertFalse(target.exists())
        self.assertEqual(unrelated.read_bytes(),b'keep');self.assertFalse(hasattr(self.online,'download_envelope'))

    def test_withdrawal_during_network_read_cannot_finish_as_ready(self):
        outer=self
        class Response(io.BytesIO):
            def read(self,*args):
                outer.accept(outer.revoked());return super().read(*args)
        with patch.object(self.online,'_opener') as opener:
            opener.return_value.open.return_value=Response(b'MZ'+b'x'*18)
            self.online.download_update();self.online.pool.shutdown(wait=True)
        self.assertEqual(self.online.status()['download']['status'],'revoked');self.assertFalse(self.online.downloading)
        self.assertFalse(list((self.online.root/'downloads').glob('*.exe*')))

    def test_apply_checks_fresh_feed_and_never_launches_a_withdrawn_update(self):
        app,target=self.owned_ready();removed=self.revoked();envelope=sign_feed(removed,self.key.export_key(format='PEM'))
        with patch.object(self.online,'install_mode',return_value='installer'),patch('core.online.current_feed',return_value=(envelope,removed)),patch('core.online.subprocess.Popen') as process:
            with self.assertRaisesRegex(ValueError,'撤回'):self.online.prepare_apply()
        process.assert_not_called();self.assertFalse(self.service._updating);self.assertFalse(target.exists())

    def test_offline_confirmation_blocks_installation_but_keeps_valid_download_for_retry(self):
        app,target=self.owned_ready()
        with patch.object(self.online,'install_mode',return_value='installer'),patch('core.online.current_feed',side_effect=ValueError('无法联网确认')),patch('core.online.subprocess.Popen') as process:
            with self.assertRaisesRegex(ValueError,'联网'):self.online.prepare_apply()
        process.assert_not_called();self.assertTrue(target.exists());self.assertFalse(self.service._updating)

    def test_a_new_publication_of_the_same_version_has_a_distinct_identity(self):
        app,target=self.owned_ready();changed=copy.deepcopy(self.feed);changed['sequence']=11;changed['release']['id']='new-publication'
        self.accept(changed);self.assertEqual(self.online.status()['download']['status'],'revoked')
        self.assertFalse(target.exists());self.assertTrue(self.online.status()['has_update'])

    def test_invalid_signature_never_revokes_trusted_content_or_downloads(self):
        app,target=self.owned_ready();invalid=sign_feed(self.revoked(),self.key.export_key(format='PEM'));invalid['signature']='A'*88
        with self.assertRaisesRegex(ValueError,'签名'):self.online._accept(invalid)
        self.assertTrue(target.exists());self.assertEqual(self.online.status()['download']['status'],'ready');self.assertEqual(self.online.status()['unread_count'],1)

    def test_notice_only_sequence_change_keeps_the_exact_release_installable(self):
        app,target=self.owned_ready();changed=copy.deepcopy(self.feed);changed.update(sequence=11,announcements=[])
        envelope=sign_feed(changed,self.key.export_key(format='PEM'))
        with patch.object(self.online,'install_mode',return_value='installer'),patch('core.online.sys.executable',str(app/'Moect.exe')),patch('core.online.current_feed',return_value=(envelope,changed)),patch('core.online.subprocess.Popen') as process:
            self.assertEqual(self.online.prepare_apply(),{'ready':True})
        process.assert_called_once();self.assertTrue(target.exists())

    def test_optional_release_ids_accept_legacy_and_reject_invalid_values(self):
        self.accept(self.feed)
        for uid in ('release-synthetic_1',None,'bad/id',''):
            changed=copy.deepcopy(self.feed);changed['release']['id']=uid
            if uid=='release-synthetic_1':self.accept(changed)
            else:
                with self.assertRaisesRegex(ValueError,'更新编号'):self.accept(changed)

    def test_cached_valid_package_is_not_replaced_by_a_leftover_partial_file(self):
        expected=self.feed['release']['packages']['installer']['sha256'];target=self.online.root/'downloads'/(expected+'.exe')
        target.parent.mkdir(parents=True);target.write_bytes(b'MZ'+b'x'*18);target.with_suffix('.exe.part').write_bytes(b'old incomplete download')
        with patch.object(self.online,'_opener',side_effect=AssertionError('A valid cached package needs no transfer')):
            self.online.download_update();self.online.pool.shutdown(wait=True)
        self.assertEqual(target.read_bytes(),b'MZ'+b'x'*18);self.assertEqual(self.online.status()['download']['status'],'ready')

    def test_independent_updater_confirmation_rejects_removal_replacement_and_old_signed_sequences(self):
        require_current_release(self.feed['release'],copy.deepcopy(self.feed['release']))
        for changed in (None,{**self.feed['release'],'id':'replacement'}):
            with self.assertRaisesRegex(ValueError,'撤回'):require_current_release(self.feed['release'],changed)
        signed=sign_feed(self.feed,self.key.export_key(format='PEM'))
        with patch('core.channel_control.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=io.BytesIO(json.dumps(signed).encode())
            with self.assertRaisesRegex(ValueError,'停止安装'):current_feed(self.config,minimum_sequence=11)


if __name__=='__main__':unittest.main()
