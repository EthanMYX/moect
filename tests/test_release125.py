"""Release 1.2.5 regressions with synthetic data and isolated storage."""
import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
import base64
import hashlib
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pyzipper

from core.archive_packaging import export_options, package_folder, public_options, update_options
from core.data import Archive
from core.diagnostics import write_report
from core.exporting import export_session
from core.service import Service, Cancelled
from core import storage
from tests.test_core import fixture, SESSION
from tests.test_resources import media_fixture, ASSETS
from wx4.paths import selected_account_dirs
from tests.test_audio_and_connection import silk_fixture


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_preferences_default_off_and_windows_protects_remembered_unicode_password(self):
        self.assertEqual(public_options({}), {'zip': False, 'encrypt': False, 'has_password': False})
        value = update_options({}, {'encrypt': True, 'password': '中文密码 🔐 test'})
        self.assertNotIn('中文密码', json.dumps(value, ensure_ascii=False))
        self.assertTrue(public_options(value)['zip'])
        options, password = export_options(json.loads(json.dumps(value)), {})
        self.assertEqual(password.decode(), '中文密码 🔐 test')
        value = update_options(options, {'zip': False})
        self.assertEqual(public_options(value), {'zip': False, 'encrypt': False, 'has_password': True})
        self.assertEqual(export_options(update_options(value, {'encrypt': True}), {})[1], password)
        with self.assertRaises(ValueError):
            export_options({}, {'archiveEncrypt': True})

    def test_plain_and_aes_archives_are_verified_and_preserve_unicode_paths(self):
        source = self.root/'source';source.mkdir()
        (source/'中文 # 100%.html').write_text('<p>合成聊天</p>', encoding='utf-8')
        for password in (None, b'synthetic-password'):
            target = self.root/('encrypted.zip' if password else 'plain.zip')
            package_folder(source, target, password, lambda: None, lambda _: None)
            reader = pyzipper.AESZipFile if password else zipfile.ZipFile
            with reader(target) as archive:
                if password:
                    archive.setpassword(password)
                    self.assertTrue(all(item.flag_bits & 1 for item in archive.infolist()))
                    with self.assertRaises(RuntimeError):
                        archive.read('中文 # 100%.html', pwd=b'wrong')
                self.assertIn('合成聊天', archive.read('中文 # 100%.html').decode())
        self.assertTrue((source/'中文 # 100%.html').is_file())

    def test_cancelled_compression_removes_only_partial_zip(self):
        source = self.root/'source';source.mkdir();(source/'record').write_bytes(b'x'*1024)
        target = self.root/'cancelled.zip'
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls >= 3:
                raise Cancelled()
        with self.assertRaises(Cancelled):
            package_folder(source, target, None, cancel, lambda _: None)
        self.assertFalse(target.exists())
        self.assertEqual((source/'record').read_bytes(), b'x'*1024)

    def test_service_encrypted_export_is_openable_and_remembered_after_restart(self):
        library = fixture(self.root/'db', count=3)
        service = Service(ASSETS, self.root/'state')
        service.library = service.config['library'] = library
        service.config['export_dir'] = str(self.root/'exports')
        response = service.export({'sessions': [SESSION], 'format': 'html', 'quickExport': True,
                                   'archiveEncrypt': True, 'archivePassword': 'private-123'})
        service.pool.shutdown(wait=True)
        task = service.config['tasks'][-1]
        self.assertEqual(task['status'], 'completed', task['detail'])
        path = service.task_file(response['job'])
        self.assertEqual(path.suffix, '.zip')
        self.assertGreater(task['size_info']['archive_bytes'], 0)
        self.assertGreater(task['size_info']['source_db_bytes'], 0)
        with pyzipper.AESZipFile(path) as archive:
            archive.setpassword(b'private-123')
            self.assertTrue(any(name.endswith('/index.html') for name in archive.namelist()))
            self.assertTrue(all('private-123' not in archive.read(name).decode('utf-8', 'ignore') for name in archive.namelist()))
        self.assertNotIn('private-123', json.dumps(service.state()))
        service.shutdown()
        again = Service(ASSETS, self.root/'state')
        self.addCleanup(again.shutdown)
        self.assertTrue(again.state()['archive_options']['encrypt'])
        self.assertEqual(export_options(again.config['archive_options'], {})[1], b'private-123')


class ExcelAndPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = patch('core.media_codec.app_data_root', return_value=self.root/'cache')
        self.cache.start();self.addCleanup(self.cache.stop)

    def test_excel_splits_long_unicode_text_and_sheets_without_formula_or_id_loss(self):
        archive = Archive(fixture(self.root/'db', count=3));self.addCleanup(archive.close)
        original = next(archive.messages(SESSION))
        content = '=' + '中文🔐'*15000
        messages = [dict(original, server_id='326543963595411110', text=content), dict(original, text='=2+2')]
        folder = self.root/'output';folder.mkdir()
        with patch.object(archive, 'messages', return_value=iter(messages)), patch('core.excel_export.EXCEL_ROWS', 3):
            result = export_session(archive, archive.sessions()[0], {'format': 'xlsx', 'quickExport': True}, folder, ASSETS, lambda _: None, lambda: None)
        self.assertEqual(result['count'], 2)
        with zipfile.ZipFile(result['path']) as workbook:
            sheets = [name for name in workbook.namelist() if name.startswith('xl/worksheets/sheet') and name.endswith('.xml')]
            self.assertGreater(len(sheets), 1)
            namespace = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            reconstructed = []
            for name in sorted(sheets):
                xml = ET.fromstring(workbook.read(name))
                self.assertFalse(xml.findall('.//x:f', namespace))
                for row in xml.findall('.//x:sheetData/x:row', namespace)[1:]:
                    values = {cell.attrib['r'].rstrip('0123456789'): ''.join(t.text or '' for t in cell.findall('.//x:t', namespace)) for cell in row}
                    if values['G'] == '326543963595411110':
                        reconstructed.append(values['F'])
            self.assertEqual(''.join(reconstructed), content)

    def test_preview_reads_local_images_and_voice_without_network_or_key_scanning(self):
        library = media_fixture(self.root)
        service = Service(ASSETS, self.root/'state');service.library = library;self.addCleanup(service.shutdown)
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Preview must stay local')), patch('core.media_codec.find_dat_aes_key', side_effect=AssertionError('No process scanning')):
            result = service.preview_media({'session': SESSION, 'shard': 0, 'local_id': 10, 'server_id': '10'})
        self.assertTrue(result['url'].startswith('data:image/png;base64,'))
        with self.assertRaises(ValueError):
            service.preview_media({'session': SESSION, 'shard': 0, 'local_id': 10, 'server_id': 'wrong'})
        self.assertEqual(service._cache_readers, 0)

    def test_contact_categories_separate_official_and_retained_unknown(self):
        archive = Archive(fixture(self.root/'db', count=1));self.addCleanup(archive.close)
        data = archive.data
        data.contacts['verified_account'] = {'verify_flag': 8}
        for name, category in [('friend','friend'),('gh_example','official'),('verified_account','official'),('group@chatroom','group'),('filehelper','other'),('local-msg:'+'a'*32,'other')]:
            self.assertEqual(data.session_category(name), category)

    def test_preview_converts_database_silk_to_playable_wav(self):
        library = fixture(self.root/'db', count=2)
        table = 'Msg_' + hashlib.md5(SESSION.encode()).hexdigest()
        with closing(sqlite3.connect(self.root/'db/message/message_0.db')) as connection, connection:
            connection.execute(f'UPDATE "{table}" SET local_type=34, message_content=?', ('<msg><voicemsg voicelength="200"/></msg>',))
        with closing(sqlite3.connect(self.root/'db/message/media_0.db')) as connection, connection:
            connection.executescript('CREATE TABLE Name2Id(user_name TEXT); CREATE TABLE VoiceInfo(chat_name_id INTEGER,svr_id INTEGER,create_time INTEGER,voice_data BLOB);')
            connection.execute('INSERT INTO Name2Id VALUES(?)', (SESSION,))
            connection.execute('INSERT INTO VoiceInfo VALUES(1,1,1800000000,?)', (silk_fixture(),))
        service = Service(ASSETS, self.root/'state');service.library = library;self.addCleanup(service.shutdown)
        result = service.preview_media({'session': SESSION, 'shard': 0, 'local_id': 1, 'server_id': '1'})
        self.assertEqual(result['kind'], 'audio')
        self.assertEqual(base64.b64decode(result['url'].split(',', 1)[1])[:4], b'RIFF')


class StorageAndDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.service = Service(ASSETS, self.root/'state');self.addCleanup(self.service.shutdown)
        slot = self.service.root/'archives/account'
        self.library = fixture(slot/'snapshot_123456abcdef', count=2)
        self.service.library = self.service.config['library'] = self.library
        (slot/'keys.json').write_text('synthetic private material')
        self.expired = slot/'snapshot_000000000000';self.expired.mkdir();(self.expired/'old.db').write_bytes(b'old')
        self.service.config['export_dir'] = str(self.root/'exports')

    def execute(self, kind, directory=None):
        with patch.object(self.service.pool, 'submit') as submit:
            self.service.storage_job(kind, directory)
        function, job, work = submit.call_args.args
        function(job, work)
        self.assertEqual(job['status'], 'completed', job['detail'])
        return job

    def test_verified_migration_and_cleanup_keep_live_data_keys_and_exports(self):
        old_root = self.service.root
        self.execute('storage_migrate', str(self.root/'D盘缓存'))
        target = self.service.storage_root
        self.assertNotEqual(target, old_root)
        self.assertEqual((target/'archives/account/keys.json').read_text(), 'synthetic private material')
        current = Path(self.service.library['root'])
        self.assertTrue(current.is_relative_to(target))
        self.assertTrue((current/'session/session.db').is_file())
        self.assertTrue((old_root/'config.json').is_file())
        self.execute('storage_cleanup')
        self.assertTrue(current.is_dir())
        self.assertFalse((target/'archives/account/snapshot_000000000000').exists())
        self.assertFalse(self.expired.exists())
        self.assertTrue((old_root/'archives/account/keys.json').is_file())
        self.assertTrue((target/'archives/account/keys.json').is_file())
        self.assertFalse(self.service._maintenance)

    def test_migration_rolls_back_on_config_failure_and_rejects_source_overlap(self):
        job = self.service._new_job('storage_migrate', 'Synthetic migration')
        with patch.object(self.service, 'save', side_effect=OSError('Synthetic disk failure')):
            with self.assertRaises(OSError):
                storage.migrate(self.service, self.root/'target', job)
        self.assertEqual(self.service.library, self.library)
        self.assertEqual(self.service.storage_root, self.service.root)
        self.assertFalse((self.root/'target/MoectData').exists())
        self.assertTrue(Path(self.library['root']).is_dir())
        with self.assertRaises(ValueError):
            storage.migrate(self.service, self.service.root/'nested', job)

    def test_storage_management_waits_for_pending_exports_and_cache_readers(self):
        self.service._new_job('export', 'Synthetic queued export')
        with self.assertRaises(ValueError):
            self.service.storage_job('storage_cleanup')
        self.service.config['tasks'].clear();self.service._cache_readers = 1
        with self.assertRaises(ValueError):
            self.service.storage_job('storage_cleanup')

    def test_directory_picker_accepts_root_account_database_and_subdirectory(self):
        root = self.root/'微信数据/xwechat_files'
        for name in ('wxid_one_ab12', 'wxid_two_cd34'):
            (root/name/'db_storage/session').mkdir(parents=True)
        self.assertEqual(len(selected_account_dirs(root)), 2)
        self.assertEqual(len(selected_account_dirs(root.parent)), 2)
        for suffix in ('', '/db_storage', '/db_storage/session'):
            self.assertEqual(selected_account_dirs(str(root/'wxid_one_ab12') + suffix)[0]['wxid'], 'wxid_one')
        install = self.root/'微信安装';install.mkdir();(install/'Weixin.exe').touch()
        with self.assertRaisesRegex(ValueError, '安装目录'):
            selected_account_dirs(install)

    def test_unavailable_cache_location_can_reset_without_deleting_data(self):
        self.service.storage_warning = 'Synthetic unavailable disk'
        old = Path(self.library['root'])
        state = self.service.reset_storage()
        self.assertIsNone(state['library'])
        self.assertEqual(state['storage_warning'], '')
        self.assertTrue(old.is_dir())
        self.assertEqual(self.service.storage_root, self.service.root.resolve())

    def test_diagnostic_report_omits_titles_paths_messages_keys_and_passwords(self):
        self.service.config['tasks'] = [dict(kind='connect', status='failed', progress=45, title='private name',
                                           detail='private chat', folder='private path', stage='snapshot',
                                           diagnostic={'failed_databases': 1, 'password': 'secret', 'key': 'private key'})]
        result = write_report(self.service, self.root/'report')
        text = Path(result['path']).read_text(encoding='utf-8')
        for private in ('private name', 'private chat', 'private path', 'secret', 'private key'):
            self.assertNotIn(private, text)
        self.assertIn('failed_databases', text)
        self.service.config['tasks'] = []
