"""Synthetic attachment and identity fixtures. Never opens a real account."""
import base64
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
from core.data import Archive
from core.exporting import export_session
from core.service import Service
from wx4.media import SIG_V1,SIG_V2,V1_KEY,decode_dat
from wx4.reader import reference_text
from tests.test_core import fixture,USER,SESSION

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGMIqFgAAAKEAWkyLad+AAAAAElFTkSuQmCC')
# Valid one-frame MP4, not just an ftyp header.
MP4=base64.b64decode('AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAMUbW9vdgAAAGxtdmhkAAAAAAAAAAAAAAAAAAAD6AAAA+gAAQAAAQAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAj90cmFrAAAAXHRraGQAAAADAAAAAAAAAAAAAAABAAAAAAAAA+gAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAABAAAAAQAAAAAAAkZWR0cwAAABxlbHN0AAAAAAAAAAEAAAPoAAAAAAABAAAAAAG3bWRpYQAAACBtZGhkAAAAAAAAAAAAAAAAAABAAAAAQABVxAAAAAAALWhkbHIAAAAAAAAAAHZpZGUAAAAAAAAAAAAAAABWaWRlb0hhbmRsZXIAAAABYm1pbmYAAAAUdm1oZAAAAAEAAAAAAAAAAAAAACRkaW5mAAAAHGRyZWYAAAAAAAAAAQAAAAx1cmwgAAAAAQAAASJzdGJsAAAAvnN0c2QAAAAAAAAAAQAAAK5hdmMxAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAABAAEABIAAAASAAAAAAAAAABFUxhdmM2MS4xOS4xMDAgbGlieDI2NAAAAAAAAAAAAAAAGP//AAAANGF2Y0MBZAAK/+EAF2dkAAqs2V7ARAAAAwAEAAADAAg8SJZYAQAGaOvjyyLA/fj4AAAAABBwYXNwAAAAAQAAAAEAAAAUYnRydAAAAAAAABYoAAAWKAAAABhzdHRzAAAAAAAAAAEAAAABAABAAAAAABxzdHNjAAAAAAAAAAEAAAABAAAAAQAAAAEAAAAUc3RzegAAAAAAAALFAAAAAQAAABRzdGNvAAAAAAAAAAEAAANEAAAAYXVkdGEAAABZbWV0YQAAAAAAAAAhaGRscgAAAAAAAAAAbWRpcmFwcGwAAAAAAAAAAAAAAAAsaWxzdAAAACSpdG9vAAAAHGRhdGEAAAABAAAAAExhdmY2MS43LjEwMAAAAAhmcmVlAAACzW1kYXQAAAKtBgX//6ncRem95tlIt5Ys2CDZI+7veDI2NCAtIGNvcmUgMTY0IHIzMTkyIGMyNGUwNmMgLSBILjI2NC9NUEVHLTQgQVZDIGNvZGVjIC0gQ29weWxlZnQgMjAwMy0yMDI0IC0gaHR0cDovL3d3dy52aWRlb2xhbi5vcmcveDI2NC5odG1sIC0gb3B0aW9uczogY2FiYWM9MSByZWY9MyBkZWJsb2NrPTE6MDowIGFuYWx5c2U9MHgzOjB4MTEzIG1lPWhleCBzdWJtZT03IHBzeT0xIHBzeV9yZD0xLjAwOjAuMDAgbWl4ZWRfcmVmPTEgbWVfcmFuZ2U9MTYgY2hyb21hX21lPTEgdHJlbGxpcz0xIDh4OGRjdD0xIGNxbT0wIGRlYWR6b25lPTIxLDExIGZhc3RfcHNraXA9MSBjaHJvbWFfcXBfb2Zmc2V0PS0yIHRocmVhZHM9MSBsb29rYWhlYWRfdGhyZWFkcz0xIHNsaWNlZF90aHJlYWRzPTAgbnI9MCBkZWNpbWF0ZT0xIGludGVybGFjZWQ9MCBibHVyYXlfY29tcGF0PTAgY29uc3RyYWluZWRfaW50cmE9MCBiZnJhbWVzPTMgYl9weXJhbWlkPTIgYl9hZGFwdD0xIGJfYmlhcz0wIGRpcmVjdD0xIHdlaWdodGI9MSBvcGVuX2dvcD0wIHdlaWdodHA9MiBrZXlpbnQ9MjUwIGtleWludF9taW49MSBzY2VuZWN1dD00MCBpbnRyYV9yZWZyZXNoPTAgcmNfbG9va2FoZWFkPTQwIHJjPWNyZiBtYnRyZWU9MSBjcmY9MjMuMCBxY29tcD0wLjYwIHFwbWluPTAgcXBtYXg9NjkgcXBzdGVwPTQgaXBfcmF0aW89MS40MCBhcT0xOjEuMDAAgAAAABBliIQAFf/+98nvwKbr29+B')
ASSETS=Path(__file__).parent.parent/'ui'


def media_fixture(root):
    lib=fixture(root/'db',count=2)
    lib['account_dir']=str(root/'account')
    con=sqlite3.connect(root/'db/contact/contact.db')
    con.execute('ALTER TABLE contact DROP COLUMN description')
    con.execute('UPDATE contact SET nick_name=?,alias=? WHERE username=?',('合成昵称','synthetic_alias',USER))
    con.commit();con.close()
    with closing(sqlite3.connect(root/'db/contact/head_image.db')) as con,con:
        con.execute('CREATE TABLE ContactHeadImg1 (usrName TEXT, headImgBuf BLOB)')
        con.executemany('INSERT INTO ContactHeadImg1 VALUES (?,?)',[(u,PNG) for u in (USER,'friend',SESSION)])
    h=hashlib.md5(SESSION.encode()).hexdigest()
    image=root/'account/msg/attach'/h/'2026-10/Img';image.mkdir(parents=True)
    plain=root/'account/msg/video';plain.mkdir(parents=True)
    files=root/'account/msg/file';files.mkdir(parents=True)
    (image/('a'*32+'.dat')).write_bytes(bytes(b^0x5a for b in PNG))
    (plain/('b'*32+'.mp4')).write_bytes(MP4)
    (files/'fixture.pdf').write_bytes(b'%PDF-1.4 synthetic')
    (files/'unrelated-private.txt').write_bytes(b'never export this')
    (root/'outside-secret.txt').write_text('never export this')
    table='Msg_'+h
    rows=[(3,'<msg><img md5="'+'a'*32+'"/></msg>',None),
          (43,'<msg><videomsg md5="'+'b'*32+'"/></msg>',None),
          (49,'<msg><appmsg><type>5</type><title>网站标题</title><des>简介</des><url>https://example.com/article?a=1&amp;b=2</url></appmsg></msg>',None),
          ((33<<32)|49,'<msg><appmsg><type>33</type><title>小程序页面</title><url>https://example.com/mini</url><sourcedisplayname>示例小程序</sourcedisplayname><weappinfo><appid>wx_fixture</appid><username>gh_fixture</username><pagepath>pages/demo?id=1</pagepath></weappinfo></appmsg></msg>',None),
          (49,'<msg><appmsg><type>6</type><title>fixture.pdf</title></appmsg></msg>',None),
          (3,'<msg><img md5="'+'c'*32+'"/></msg>',None)]
    with closing(sqlite3.connect(root/'db/message/message_0.db')) as con,con:
        for i,(typ,content,packed) in enumerate(rows,10):
            con.execute(f'INSERT INTO "{table}" VALUES (?,?,?,?,?,?,?,?,?)',(i,str(i),typ,i,2,1800000000+i,content,None,packed))
    return lib


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        cache_patch=patch('core.media_codec.app_data_root',return_value=self.root/'app-state')
        cache_patch.start();self.addCleanup(cache_patch.stop)
        self.lib=media_fixture(self.root);self.archive=Archive(self.lib)
    def tearDown(self):self.archive.close();self.temp.cleanup()

    def test_profile_optional_columns_and_directory_suffix(self):
        self.assertEqual(self.archive.profile()['name'],'合成昵称')
        self.assertEqual(self.archive.profile()['alias'],'synthetic_alias')
        self.assertTrue(self.archive.profile()['avatar_url'].startswith('data:image/png'))
        self.assertTrue(self.archive.sessions()[0]['avatar_url'].startswith('data:'))
        lib=dict(self.lib,wxid=USER+'_a1b2')
        archive=Archive(lib)
        try:self.assertEqual(archive.profile()['wxid'],USER)
        finally:archive.close()

    def test_html_copies_only_selected_resources_and_avatars(self):
        out=self.root/'html';out.mkdir()
        result=export_session(self.archive,self.archive.sessions()[0],{'format':'html'},out,ASSETS,lambda n:None,lambda:None)
        folder=Path(result['path']).parent
        messages=json.loads((folder/'c000001.js').read_text(encoding='utf-8').removeprefix('window.__wxChunk=').removesuffix(';'))
        by_id={str(m['server_id']):m for m in messages}
        for id,kind in [('10','image'),('11','video'),('14','file')]:
            r=by_id[id]['resources'][0]
            self.assertEqual(r['kind'],kind)
            self.assertTrue((folder/r['path']).is_file())
            self.assertTrue((folder/by_id[id]['avatar']).is_file())
        self.assertEqual((folder/by_id['10']['resources'][0]['path']).read_bytes(),PNG)
        self.assertEqual(by_id['15']['resource_status'],'missing')
        self.assertEqual(by_id['13']['extra']['miniprogram']['page_path'],'pages/demo?id=1')
        self.assertEqual(by_id['12']['extra']['title'],'网站标题')
        self.assertFalse(any(b'never export this' in p.read_bytes() for p in folder.rglob('*') if p.is_file()))
        self.assertNotIn('_resource_source',by_id['10'])

    def test_json_and_text_reference_portable_sidecars(self):
        out=self.root/'json';out.mkdir()
        for fmt in ('json','txt','md','csv','jsonl'):
            result=export_session(self.archive,self.archive.sessions()[0],{'format':fmt},out,ASSETS,lambda n:None,lambda:None)
            path=Path(result['path'])
            self.assertIn('resources/',path.read_text(encoding='utf-8-sig'))
            if fmt=='json':
                rows=json.loads(path.read_text(encoding='utf-8'))['messages']
                for m in rows:
                    for r in m['resources']:self.assertTrue((out/r['path']).is_file())

    def test_encrypted_image_is_preserved_and_reported(self):
        h=hashlib.md5(SESSION.encode()).hexdigest()
        p=self.root/'account/msg/attach'/h/'2026-10/Img'/('a'*32+'.dat')
        padded=PNG+bytes([16-len(PNG)%16])*(16-len(PNG)%16)
        p.write_bytes(SIG_V2+struct.pack('<LL',len(PNG),0)+b'\x00'+AES.new(b'0123456789abcdef',AES.MODE_ECB).encrypt(padded))
        out=self.root/'encrypted';out.mkdir()
        with patch('core.media_codec.find_dat_aes_key',return_value=None):
            result=export_session(self.archive,self.archive.sessions()[0],{'format':'json'},out,ASSETS,lambda n:None,lambda:None)
        rows=json.loads(Path(result['path']).read_text(encoding='utf-8'))['messages']
        msg=next(m for m in rows if str(m['server_id'])=='10')
        self.assertEqual(msg['resource_status'],'encrypted')
        self.assertEqual((out/msg['resources'][0]['path']).read_bytes(),p.read_bytes())

    def test_native_task_names_migration_delete_and_file_open(self):
        service=Service(ASSETS,self.root/'state');service.library=self.lib
        service.config['export_dir']=str(self.root/'exports')
        job=service.export({'sessions':[SESSION],'format':'json'})['job']
        service.pool.shutdown(wait=True)
        task=service.state()['tasks'][0]
        self.assertEqual(task['title'],'测试群');self.assertEqual(task['format'],'json')
        path=service.task_file(job);self.assertEqual(path.suffix,'.json')
        service.delete_task(job)
        self.assertTrue(path.is_file());self.assertEqual(service.state()['tasks'],[])
        service.shutdown()

    def test_v1_png_integrity_and_binary_packed_hash(self):
        padding=16-len(PNG)%16
        encrypted=AES.new(V1_KEY,AES.MODE_ECB).encrypt(PNG+bytes([padding])*padding)
        raw=SIG_V1+struct.pack('<LL',len(PNG),0)+b'\x00'+encrypted
        self.assertEqual(decode_dat(raw),PNG)
        digest=bytes.fromhex('1234567890abcdef1234567890abcdef')
        self.assertIn(digest.hex(),reference_text(b'\x0a\x10'+digest))

    def test_reference_db_associates_server_ids(self):
        self.archive.close()
        with closing(sqlite3.connect(self.root/'db/message/message_resource.db')) as con,con:
            con.execute('CREATE TABLE MessageResourceInfo (msg_svr_id TEXT,packed_info BLOB)')
            con.execute('INSERT INTO MessageResourceInfo VALUES (?,?)',('11',('b'*32).encode()))
        table='Msg_'+hashlib.md5(SESSION.encode()).hexdigest()
        with closing(sqlite3.connect(self.root/'db/message/message_0.db')) as con,con:
            con.execute(f'UPDATE "{table}" SET message_content=? WHERE server_id=?',('<msg><videomsg/></msg>','11'))
        self.archive=Archive(self.lib)
        out=self.root/'refs';out.mkdir()
        result=export_session(self.archive,self.archive.sessions()[0],{'format':'json'},out,ASSETS,lambda n:None,lambda:None)
        rows=json.loads(Path(result['path']).read_text(encoding='utf-8'))['messages']
        video=next(m for m in rows if str(m['server_id'])=='11')
        self.assertEqual(video['resources'][0]['kind'],'video')

    def test_active_record_cannot_be_deleted(self):
        svc=Service(ASSETS,self.root/'active-state');job=svc._new_job('export','fixture')
        with self.assertRaises(ValueError):svc.delete_task(job['id'])
        svc.shutdown()


if __name__=='__main__':unittest.main()
