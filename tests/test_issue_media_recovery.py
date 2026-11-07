"""Issue 6–8 regressions; synthetic files and mocked process access only."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.account_exporting import export_moments
from core.image_recovery import recent_image_samples, recover_local_images
from core.resources import ResourceStore
from core.service import Service
from core.sticker_cache import StickerCache
from tests.test_account_assets import asset_fixture, FAVORITE
from tests.test_core import SESSION
from tests.test_image_recovery import encrypted_image
from tests.test_resources import PNG, ASSETS


class IssueMediaRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.library, self.emoticon_key = asset_fixture(self.root)
        self.service = Service(ASSETS, self.root / 'state')
        self.service.library = self.service.config['library'] = self.library
        self.addCleanup(self.service.shutdown)
        self.key = b'SyntheticKey1234'
        self.sns = Path(self.library['account_dir']) / 'cache/2026-11/Sns/Img' / FAVORITE[:2] / FAVORITE
        self.sns.write_bytes(encrypted_image(self.key))
        for target in ('core.media_codec.find_dat_aes_key', 'core.sticker_cache.discover_emoticon_key'):
            context = patch(target, return_value=None)
            context.start();self.addCleanup(context.stop)
        context = patch('core.media_codec.app_data_root', return_value=self.root / 'state')
        context.start();self.addCleanup(context.stop)

    def test_preview_is_local_and_encrypted_is_not_reported_as_missing(self):
        with patch('core.image_recovery.find_dat_aes_key', side_effect=AssertionError('No automatic recovery')):
            preview = self.service.account_assets({'kind': 'moments'})
        post = next(post for post in preview['posts'] if post['id'] == '100')
        self.assertFalse(post['thumbnails'])
        self.assertIn('encrypted', post['media_status'])
        output = self.root / 'output';output.mkdir()
        with self.service.read_archive() as archive:
            export_moments(archive, self.library, {}, output, ASSETS, lambda *args: None, lambda: None, lambda _: None)
        result = json.loads((output / 'data.json').read_text(encoding='utf-8'))
        post = next(post for post in result['items'] if post['id'] == '100')
        self.assertEqual(post['media_diagnostics'][0]['reason'], 'aes_key_unavailable')
        self.assertGreater(result['resource_summary']['encrypted'], 0)
        self.assertNotIn(self.key.decode(), (output / 'resource-report.jsonl').read_text(encoding='utf-8'))

    def test_recovery_clears_failed_preview_and_exports_with_the_verified_key(self):
        self.service.account_assets({'kind': 'moments'})
        revision = self.service.state()['library']['data_revision']
        with patch('core.image_recovery.find_dat_aes_key', return_value=self.key) as scanner:
            job = self.service.call('recover_images', {})
            self.service.pool.shutdown(wait=True)
        self.assertEqual(self.service.config['tasks'][-1]['status'], 'completed')
        self.assertEqual(self.service.config['tasks'][-1]['id'], job['job'])
        self.assertLessEqual(scanner.call_args.kwargs['timeout'], 45)
        self.assertNotEqual(self.service.state()['library']['data_revision'], revision)
        self.assertFalse(self.service._moments_preview_cache)
        result = self.service.account_assets({'kind': 'moments'})
        post = next(post for post in result['posts'] if post['id'] == '100')
        self.assertTrue(post['thumbnails'])
        output = self.root / 'recovered-export';output.mkdir()
        with self.service.read_archive() as archive:
            export_moments(archive, self.library, {}, output, ASSETS, lambda *args: None, lambda: None, lambda _: None)
        result = json.loads((output / 'data.json').read_text(encoding='utf-8'))
        self.assertTrue(next(post for post in result['items'] if post['id'] == '100')['resources'])
        self.assertEqual(self.service._cache_readers, 0)

    def test_cancelled_account_recovery_cannot_restore_a_logged_out_library(self):
        def recover(*args, **kwargs):
            self.service.logout()
            return self.key
        with patch('core.image_recovery.find_dat_aes_key', side_effect=recover):
            self.service.recover_images();self.service.pool.shutdown(wait=True)
        self.assertIsNone(self.service.library)
        self.assertEqual(self.service.config['tasks'][-1]['status'], 'cancelled')
        self.assertFalse(list((self.root / 'state').rglob('image-keys.json')))

    def test_invalid_recovered_key_is_not_saved(self):
        with self.service.read_archive() as archive:
            with patch('core.image_recovery.find_dat_aes_key', return_value=b'WrongSynthetic01'):
                with self.assertRaisesRegex(ValueError, '未通过完整校验'):
                    recover_local_images(archive.data, lambda: None, lambda _: None)
        self.assertFalse(list((self.root / 'state').rglob('image-keys.json')))

    def test_process_permission_failure_is_distinct_from_missing_files(self):
        def denied(*args, **kwargs):
            kwargs['diagnostics'].update(processes_found=3, processes_readable=0)
            return None
        with self.service.read_archive() as archive:
            with patch('core.image_recovery.find_dat_aes_key', side_effect=denied):
                with self.assertRaisesRegex(ValueError, '无法读取微信进程'):
                    recover_local_images(archive.data, lambda: None, lambda _: None)

    def test_recent_samples_are_sorted_and_do_not_include_other_accounts(self):
        recent = self.sns.with_name('f' * 32)
        recent.write_bytes(encrypted_image(self.key));os.utime(recent, (200, 200));os.utime(self.sns, (100, 100))
        (self.root / 'other-account.dat').write_bytes(encrypted_image(self.key))
        with self.service.read_archive() as archive:
            samples = recent_image_samples(archive.data)
        self.assertEqual(samples, [recent, self.sns])

    def test_manual_chat_retry_searches_account_cache_without_network(self):
        original = Path(self.library['account_dir']) / 'msg/attach' / hashlib.md5(SESSION.encode()).hexdigest() / ('2026-10/Img/' + 'a' * 32 + '.dat')
        moved = Path(self.library['account_dir']) / 'cache/2026-11/Chat/' / original.name
        moved.parent.mkdir(parents=True);original.replace(moved)
        hint = {'session': SESSION, 'shard': 0, 'local_id': 10, 'server_id': '10'}
        with patch('core.resources.ResourceStore._download', side_effect=AssertionError('Preview must stay offline')):
            self.assertNotIn('url', self.service.preview_media(hint))
            result = self.service.preview_media({**hint, 'retry': True})
        self.assertTrue(result['url'].startswith('data:image/png;base64,'))

    def test_chat_emoji_reuses_the_same_local_cache_as_sticker_export(self):
        output = self.root / 'emoji';output.mkdir()
        with self.service.read_archive() as archive:
            decoder = StickerCache(archive.data, None, lambda: None)
            decoder.key_path.parent.mkdir(parents=True, exist_ok=True)
            decoder.key_path.write_bytes(self.emoticon_key)
            store = ResourceStore(archive.data, SESSION, output, preview=True)
            try:
                with patch.object(store, '_download', side_effect=AssertionError('Local cache must not download')):
                    message = store.enrich({'kind':'emoji','sender_wxid':'','text':'[动画表情]',
                                            '_media':{'hashes':[FAVORITE]},'extra':{}})
                self.assertEqual(message['resources'][0]['kind'], 'image')
                self.assertEqual((output / message['resources'][0]['path']).read_bytes(), PNG)
                self.assertEqual(store.sticker_decoder.scan_timeout, 0)
            finally:
                store.close()

    def test_recovery_is_blocked_during_storage_maintenance(self):
        self.service._maintenance = True
        with self.assertRaisesRegex(ValueError, '整理缓存'):
            self.service.recover_images()

    def test_unverified_emoticon_key_is_not_persisted(self):
        output = self.root / 'invalid-emoji';output.mkdir()
        with self.service.read_archive() as archive:
            store = ResourceStore(archive.data, SESSION, output)
            try:
                decoder = StickerCache(archive.data, store.codec, lambda: None)
                raw = decoder.safe_read(decoder.base / 'Persist' / FAVORITE[:2] / FAVORITE)
                with patch('core.sticker_cache.discover_emoticon_key', return_value=b'WrongSynthetic01'):
                    self.assertIsNone(decoder.render(raw))
                self.assertIsNone(decoder.key)
                self.assertFalse(decoder.key_path.exists())
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
