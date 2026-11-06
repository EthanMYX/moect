"""Failure-path and lifecycle regressions using isolated, synthetic data."""
import hashlib
import json
import os
import shutil
import sqlite3
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from concurrent.futures import ThreadPoolExecutor

from core.avatars import AvatarStore, avatar_host
from core.data import Archive
from core.exporting import export_session, export_index
from core.resources import ResourceStore
from core.media_codec import ImageKeys
from core.service import Service
from core import storage
from core.update_apply import replace_portable
from tests.test_core import fixture, SESSION
from tests.test_resources import ASSETS, media_fixture
from wx4.reader import Wx4Data
from wx4.decrypt import merge_wal, PAGE_SZ


class AuditTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.service = Service(ASSETS, self.root/'state')
        self.addCleanup(self.service.shutdown)

    def test_failed_job_creation_and_history_save_leave_no_phantom_state(self):
        with patch('core.service.atomic_json', side_effect=OSError('Synthetic disk failure')):
            with self.assertRaises(OSError):
                self.service._new_job('export', 'Synthetic')
        self.assertEqual(self.service.config['tasks'], [])
        self.assertEqual(self.service.events, {})
        for index in range(81):
            self.service.config['tasks'].append(dict(id=str(index), kind='export', status='completed'))
        with patch('core.service.atomic_json', side_effect=OSError('Synthetic disk failure')):
            with self.assertRaises(OSError):
                self.service.save()
        self.assertEqual(len(self.service.config['tasks']), 81)

    def test_failed_delete_and_settings_save_roll_back_in_memory(self):
        job = self.service._new_job('export', 'Synthetic')
        job['status'] = 'completed'
        before = dict(self.service.config)
        with patch.object(self.service, 'save', side_effect=OSError('Synthetic disk failure')):
            with self.assertRaises(OSError):
                self.service.delete_task(job['id'])
            self.assertIn(job['id'], self.service.events)
            self.assertIn(job, self.service.config['tasks'])
            with self.assertRaises(OSError):
                self.service.settings({'theme':'dark', 'accent':'green'})
        self.assertEqual(self.service.config, before)

    def test_partial_queue_submission_cancels_all_without_starting_work(self):
        jobs = [(self.service._new_job('export', str(index)), Mock()) for index in range(3)]
        with patch.object(self.service.pool, 'submit', side_effect=[Mock(), RuntimeError('Synthetic executor failure')]):
            with self.assertRaises(ValueError):
                self.service._submit_jobs(jobs)
        for job, work in jobs:
            self.service._run(job, work)
            self.assertEqual(job['status'], 'cancelled')
            work.assert_not_called()
        self.assertFalse(self.service._maintenance)

    def test_shutdown_between_creation_and_submission_cancels_job(self):
        job = self.service._new_job('connect', 'Synthetic')
        self.service.shutdown()
        with self.assertRaises(ValueError):
            self.service._submit_jobs([(job, Mock())])
        self.assertEqual(job['status'], 'cancelled')

    def test_background_save_failure_is_visible_in_task_details(self):
        job = self.service._new_job('export', 'Synthetic')
        with patch.object(self.service, 'save', side_effect=OSError('Synthetic disk failure')):
            self.service._run(job, lambda: None)
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['error_code'], 'state_save_failed')
        self.assertIn('保存失败', job['detail'])

    def test_cache_readers_guard_avatar_catalog_import_and_failed_archive_open(self):
        def reading_avatar(*args, **kwargs):
            self.assertEqual(self.service._cache_readers, 1)
            with self.assertRaises(ValueError):
                self.service.storage_job('storage_cleanup')
        with patch('core.service.AvatarStore.blob', side_effect=reading_avatar):
            self.assertEqual(self.service.avatar('https://qpic.cn/synthetic'), {'url':''})
        self.service.library = {'root':'synthetic', 'name':'Synthetic'}
        def reading_catalog(library):
            self.assertEqual(self.service._cache_readers, 1)
            with self.assertRaises(ValueError):
                self.service.storage_job('storage_cleanup')
            return SimpleNamespace(summary=lambda:{'available':False})
        with patch('core.account_assets.StickerCatalog', side_effect=reading_catalog):
            self.assertEqual(self.service.account_assets({'kind':'stickers'}), {'available':False})
        with patch.object(self.service, 'archive', side_effect=ValueError('Synthetic missing snapshot')):
            with self.assertRaises(ValueError), self.service.read_archive():
                pass
        self.assertEqual(self.service._cache_readers, 0)
        with self.service.cache_access(), self.assertRaisesRegex(ValueError, '预览'):
            self.service.online.prepare_apply()
        self.service._maintenance = True
        with patch('core.service.validate_root') as validate:
            with self.assertRaises(ValueError):
                self.service.import_archive('synthetic')
            validate.assert_not_called()
        self.service._maintenance = False

    def test_storage_inventory_rejects_linked_category_roots(self):
        root = self.service.root/'archives';root.mkdir()
        (root/'synthetic.db').write_bytes(b'Synthetic content')
        with patch('core.storage.is_link', side_effect=lambda path:Path(path)==root):
            with self.assertRaises(ValueError):
                list(storage.files_below(root))
        with patch('core.storage.is_link', return_value=True):
            with self.assertRaises(ValueError):
                storage.managed_root(self.service, self.service.root)

    def test_invalid_config_fields_recover_but_legacy_account_remains_reconnectable(self):
        root = self.root/'old-state';root.mkdir()
        (root/'config.json').write_text(json.dumps({'theme':[], 'tasks':[None, {}, 3], 'storage_history':{},
            'export_dir':None, 'storage_dir':[], 'library':{'account_dir':'Synthetic account'}}), encoding='utf-8')
        service = Service(ASSETS, root)
        try:
            self.assertEqual(service.config['theme'], 'light')
            self.assertEqual(service.config['tasks'], [])
            self.assertEqual(service.config['storage_history'], [])
            self.assertEqual(service.library['account_dir'], 'Synthetic account')
            with self.assertRaises(ValueError):
                service.archive()
            service.state()
        finally:
            service.shutdown()

    def test_reader_constructor_failure_closes_all_database_connections(self):
        library = fixture(self.root/'database', count=2)
        connections = []
        original = sqlite3.connect
        def capture(*args, **kwargs):
            connection = original(*args, **kwargs)
            connections.append(connection)
            return connection
        with patch('wx4.reader.sqlite3.connect', side_effect=capture), patch.object(Wx4Data, '_load_rooms', side_effect=ValueError('Synthetic format failure')):
            with self.assertRaises(ValueError):
                Wx4Data(library['root'])
        self.assertTrue(connections)
        for connection in connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute('SELECT 1')

    def test_resource_constructor_failure_closes_index_and_temporary_directory(self):
        archive = Archive(fixture(self.root/'database', count=2));self.addCleanup(archive.close)
        folder = self.root/'out';folder.mkdir()
        created = []
        original = tempfile.TemporaryDirectory
        def capture(*args, **kwargs):
            temporary = original(*args, **kwargs)
            created.append(Path(temporary.name))
            return temporary
        with patch('core.resources.tempfile.TemporaryDirectory', side_effect=capture), patch('core.resources.ImageKeys', side_effect=ValueError('Synthetic key cache failure')):
            with self.assertRaises(ValueError):
                ResourceStore(archive.data, SESSION, folder)
        self.assertTrue(created)
        self.assertTrue(all(not path.exists() for path in created))

    def test_export_setup_failure_closes_resources_before_first_message(self):
        archive = Archive(fixture(self.root/'database', count=2));self.addCleanup(archive.close)
        folder = self.root/'out';folder.mkdir()
        stores = []
        def capture(*args, **kwargs):
            store = ResourceStore(*args, **kwargs);stores.append(store)
            return store
        with patch('core.exporting.ResourceStore', side_effect=capture):
            with self.assertRaises(FileNotFoundError):
                export_session(archive, archive.sessions()[0], {'format':'html'}, folder, self.root/'missing-assets', lambda _: None, lambda: None)
        self.assertTrue(stores[0].report.closed)
        self.assertFalse(Path(stores[0].tmp.name).exists())
        stores[0].close()

    def test_corrupted_preview_cache_regenerates_and_avatar_errors_are_bounded(self):
        self.service.library = media_fixture(self.root/'media')
        payload = {'session':SESSION, 'shard':0, 'local_id':10, 'server_id':'10'}
        first = self.service.preview_media(payload)
        path = next((self.service.storage_root/'previews').glob('*/preview.json'))
        path.write_text('[]')
        self.assertEqual(self.service.preview_media(payload)['url'], first['url'])
        self.assertEqual(self.service._cache_readers, 0)
        for url in (None, 'https://[invalid', 'https://qpic.cn:bad/a', 'https://qpic.cn:444/a'):
            self.assertFalse(avatar_host(url))
        url = 'https://qpic.cn/synthetic'
        cache = self.root/'avatars';cache.mkdir()
        (cache/(hashlib.sha256(url.encode()).hexdigest()+'.img')).write_bytes(b'synthetic')
        store = AvatarStore(SimpleNamespace(_conns={}, avatar_of=lambda _:url), cache)
        with patch.object(Path, 'read_bytes', side_effect=PermissionError('Synthetic denied cache')):
            self.assertIsNone(store.blob('synthetic'))

    def test_failed_portable_replacement_restores_program_and_cleans_partial_files(self):
        target, stage, recovery = (self.root/name for name in ('program', 'stage', 'recovery'))
        for root in (target, stage):
            (root/'_internal').mkdir(parents=True)
            (root/'Moect.exe').write_bytes(root.name.encode())
            (root/'_internal/module.py').write_text(root.name)
            (root/'program-files.json').write_text(json.dumps({'version':'1.2.5','files':['Moect.exe','_internal/module.py']}))
        recovery.mkdir()
        copy = shutil.copy2
        def fail_copy(source, destination, *args, **kwargs):
            if str(destination).endswith('module.py.moect-new'):
                Path(destination).write_text('partial')
                raise OSError('Synthetic copy failure')
            return copy(source, destination, *args, **kwargs)
        with patch('core.update_apply.shutil.copy2', side_effect=fail_copy):
            with self.assertRaises(OSError):
                replace_portable(target, stage, recovery)
        self.assertEqual((target/'Moect.exe').read_bytes(), b'program')
        self.assertEqual((target/'_internal/module.py').read_text(), 'program')
        self.assertEqual(list(target.rglob('*.moect-new')), [])

    def test_zip_publication_race_preserves_existing_export(self):
        staging = self.root/'staging';staging.mkdir();(staging/'record.txt').write_text('Synthetic export')
        output = self.root/'exports';output.mkdir()
        job = self.service._new_job('export', 'Synthetic')
        rename = os.rename
        occupied = output/'Synthetic.zip'
        def race(source, destination):
            if Path(destination) == occupied:
                occupied.write_bytes(b'Existing user archive')
                raise FileExistsError('Synthetic filename race')
            return rename(source, destination)
        result = {'path':str(staging/'record.txt')}
        with patch('core.service.os.rename', side_effect=race):
            self.service._finish_export_files(job, result, staging, output, 'Synthetic', {'zip':True}, None, 0)
        self.assertEqual(occupied.read_bytes(), b'Existing user archive')
        self.assertNotEqual(Path(result['path']), occupied)
        self.assertTrue(Path(result['path']).is_file())

    def test_wal_streaming_applies_only_committed_current_generation_frames(self):
        database = self.root/'snapshot.db'
        wal = self.root/'snapshot.db-wal'
        database.write_bytes(b'O' * PAGE_SZ * 2)
        header = struct.pack('>8I', 0x377f0682, 3007000, PAGE_SZ, 0, 7, 9, 0, 0)
        def frame(page, commit, value, salts=(7, 9)):
            return struct.pack('>6I', page, commit, *salts, 0, 0) + value * PAGE_SZ
        wal.write_bytes(header + frame(1, 0, b'A') + frame(2, 2, b'B')
                        + frame(1, 100, b'X', salts=(1, 2)) + frame(1, 0, b'C'))
        open_file = open
        class BoundedWal:
            def __init__(self, stream):
                self.stream = stream
            def __getattr__(self, name):
                return getattr(self.stream, name)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.stream.close()
            def read(self, size=-1):
                if not 0 < size <= PAGE_SZ:
                    raise AssertionError('WAL reads must stay bounded')
                return self.stream.read(size)
        def bounded_open(path, *args, **kwargs):
            stream = open_file(path, *args, **kwargs)
            return BoundedWal(stream) if Path(path) == wal else stream
        with patch('wx4.decrypt.open', side_effect=bounded_open), patch('wx4.decrypt.decrypt_page', side_effect=lambda key, page, number:page):
            self.assertEqual(merge_wal(database, wal, b'synthetic'), 2)
        self.assertEqual(database.read_bytes(), b'A' * PAGE_SZ + b'B' * PAGE_SZ)
        before = database.read_bytes()
        wal.write_bytes(header + frame(1, 0, b'Z') + b'truncated')
        self.assertEqual(merge_wal(database, wal, b'synthetic'), 0)
        self.assertEqual(database.read_bytes(), before)

    def test_corrupt_database_timestamp_does_not_abort_message_parsing(self):
        archive = Archive(fixture(self.root/'timestamp-database', count=2));self.addCleanup(archive.close)
        row = dict(local_id=1, server_id=1, local_type=1, sort_seq=1, real_sender_id=1,
                   create_time=2**63-1, message_content='Synthetic preserved content',
                   compress_content=None, packed_info_data=None)
        message = archive.data._build_msg(row, {1:'synthetic'}, SESSION, 0)
        self.assertEqual(message['text'], 'Synthetic preserved content')
        self.assertEqual(message['time_str'], '')

    def test_non_html_export_index_follows_selected_archive_theme(self):
        folder = self.root/'themed-export';folder.mkdir()
        record = folder/'record.txt';record.write_text('Synthetic content')
        export_index(folder, [{'name':'Synthetic','path':str(record),'format':'txt','count':1}],
                     theme={'mode':'dark','accent':'green'})
        html = (folder/'index.html').read_text(encoding='utf-8')
        self.assertIn('color-scheme:dark', html)
        self.assertIn('background:var(--background)', html)
        self.assertIn('a{color:var(--primary)', html)

    def test_concurrent_image_key_saves_use_independent_atomic_files(self):
        data = SimpleNamespace(root=str(self.root), wxid='synthetic', cache_root=self.service.root,
                               account_dir=lambda:str(self.root))
        stores = [ImageKeys(data, lambda:None) for _ in range(2)]
        barrier = threading.Barrier(2, timeout=5)
        temporary_files = []
        rename = os.replace
        def synchronized_replace(source, destination):
            temporary_files.append(Path(source))
            barrier.wait()
            return rename(source, destination)
        with patch('core.media_codec.os.replace', side_effect=synchronized_replace), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(store._save) for store in stores]
            for future in futures:
                future.result(timeout=10)
        self.assertEqual(len(set(temporary_files)), 2)
        self.assertTrue(all(not path.exists() for path in temporary_files))
        self.assertEqual(json.loads(stores[0].path.read_text())['schema'], 2)
