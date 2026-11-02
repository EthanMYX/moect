"""Synthetic account catalogs and portable exports. Never opens a live account."""
import hashlib
import io
import json
import sqlite3
import shutil
import random
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import pad
from PIL import Image

from core.account_assets import StickerCatalog,MomentsCatalog,moment_from_row
from core.account_exporting import export_stickers,export_moments
from core.data import Archive
from core.exporting import export_folder_name,unused_folder
from core.media_codec import MediaCodec
from core.service import Service
from core.sticker_cache import derive_emoticon_key
from core.themes import ACCENT_IDS,palette
from core.sns_codec import Isaac64
from core.account_exporting import MomentResources
from core.resources import ResourceStore
from tests.test_resources import media_fixture,PNG,MP4,ASSETS
from tests.test_core import USER

FAVORITE='a'*32;MEMBER='b'*32;MISSING='c'*32;THUMB='d'*32;PACKAGE='synthetic.package'


def animated_gif():
    output=io.BytesIO();frames=[Image.new('RGB',(8,8),color) for color in ('red','blue')]
    frames[0].save(output,format='GIF',save_all=True,append_images=frames[1:],duration=100,loop=0)
    return output.getvalue()


def asset_fixture(root):
    library=media_fixture(root);database=Path(library['root'])
    (database/'emoticon').mkdir();(database/'sns').mkdir()
    with closing(sqlite3.connect(database/'emoticon/emoticon.db')) as con,con:
        con.executescript('''
        CREATE TABLE kNonStoreEmoticonTable(md5 TEXT,caption TEXT,aes_key TEXT,auth_key TEXT,cdn_url TEXT,thumb_url TEXT);
        CREATE TABLE kFavEmoticonOrderTable(md5 TEXT);
        CREATE TABLE kCustomEmoticonOrderTable(md5 TEXT);
        CREATE TABLE kStoreEmoticonPackageTable(package_id_ TEXT,package_name_ TEXT,remove_time_ INTEGER,sort_order_ INTEGER);
        CREATE TABLE kStoreEmoticonFilesTable(package_id_ TEXT,md5_ TEXT,sort_order_ INTEGER,emoticon_offset_ INTEGER,emoticon_size_ INTEGER,thumb_offset_ INTEGER,thumb_size_ INTEGER);
        CREATE TABLE kStoreEmoticonCaptionsTable(package_id_ TEXT,md5_ TEXT,language_ TEXT,caption_ TEXT);
        ''')
        con.executemany('INSERT INTO kNonStoreEmoticonTable VALUES (?,?,?,?,?,?)',[(FAVORITE,'合成收藏','secret-aes-value','secret-auth-value','https://example.invalid/never-download',''),(MISSING,'未缓存','','','',''),(THUMB,'仅缩略图','','','','')])
        con.executemany('INSERT INTO kFavEmoticonOrderTable VALUES (?)',[(FAVORITE,),(MISSING,),(THUMB,)])
        con.executemany('INSERT INTO kStoreEmoticonPackageTable VALUES (?,?,?,?)',[(PACKAGE,'合成专辑',0,1),('removed','已删除',1,2)])
        gif=animated_gif()
        con.execute('INSERT INTO kStoreEmoticonFilesTable VALUES (?,?,?,?,?,?,?)',(PACKAGE,MEMBER,1,len(PNG),len(gif),0,0))
        con.executemany('INSERT INTO kStoreEmoticonCaptionsTable VALUES (?,?,?,?)',[(PACKAGE,MEMBER,'en','Title'),(PACKAGE,MEMBER,'zh_CN','动画标题')])
    cache=Path(library['account_dir'])/'business/emoticon';key=derive_emoticon_key('12345678',USER)
    def encrypted(path,blob):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(AES.new(key,AES.MODE_CBC,iv=key).encrypt(pad(blob,16)))
    encrypted(cache/'Persist'/FAVORITE[:2]/FAVORITE,PNG)
    encrypted(cache/'Thumb'/THUMB[:2]/(THUMB+'.thumb'),PNG)
    digest=hashlib.md5(PACKAGE.encode()).hexdigest();encrypted(cache/'PersistStore'/digest[:2]/digest,PNG+gif)
    xml='<SnsDataItem><TimelineObject><id>100</id><username>'+USER+'</username><createTime>1800000000</createTime><contentDesc>自己的合成动态 &lt;script&gt;</contentDesc><ContentObject><type>1</type><title>合成标题</title><mediaList><media><type>2</type><url md5="'+FAVORITE+'">https://example.invalid/private-media?token=secret-token</url></media></mediaList></ContentObject></TimelineObject></SnsDataItem>'
    with closing(sqlite3.connect(database/'sns/sns.db')) as con,con:
        con.execute('CREATE TABLE SnsTimeLine(tid INTEGER,user_name TEXT,content TEXT,pack_info_buf TEXT)')
        con.executemany('INSERT INTO SnsTimeLine VALUES (?,?,?,?)',[(100,USER,xml,''),(101,'friend',xml.replace(USER,'friend').replace('<id>100</id>','<id>101</id>'),''),(102,USER,xml.replace(USER,'friend'),''),(103,USER,'unrecognized-serialized-content','')])
    sns=Path(library['account_dir'])/'cache/2026-11/Sns/Img'/FAVORITE[:2]/FAVORITE;sns.parent.mkdir(parents=True);sns.write_bytes(PNG)
    return library,key


class AccountAssetTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.library,self.key=asset_fixture(self.root)
        self.archive=Archive(self.library);self.addCleanup(self.archive.close)
        for name in ('core.media_codec.app_data_root','core.sticker_cache.app_data_root'):
            context=patch(name,return_value=self.root/'private-state');context.start();self.addCleanup(context.stop)
        context=patch('core.sticker_cache.discover_emoticon_key',return_value=self.key);context.start();self.addCleanup(context.stop)

    def test_catalog_uses_favorite_order_and_real_installed_package_members(self):
        catalog=StickerCatalog(self.library)
        self.assertEqual([g['name'] for g in catalog.groups],['收藏的表情','合成专辑'])
        self.assertEqual([m['md5'] for m in catalog.groups[0]['members']],[FAVORITE,MISSING,THUMB])
        self.assertEqual(catalog.groups[1]['members'][0]['caption'],'动画标题')
        public=json.dumps(catalog.summary())
        self.assertNotIn('aes_key',public);self.assertNotIn('secret-auth-value',public)

    def test_album_export_decodes_package_offsets_preserves_animation_and_labels_thumbnails(self):
        catalog=StickerCatalog(self.library);destination=self.root/'albums';destination.mkdir()
        with patch('core.resources.ResourceStore._download',side_effect=AssertionError('Local-only export performed a download')):
            result=export_stickers(self.archive,self.library,{'groups':[g['id'] for g in catalog.groups],'download':False},destination,ASSETS,lambda *a:None,lambda:None,lambda _:None)
        data=json.loads((destination/'data.json').read_text(encoding='utf-8'))
        self.assertEqual(result['count'],4);self.assertEqual(result['resource_summary']['missing'],1)
        self.assertEqual(result['resource_summary']['available'],3)
        member=next(row for row in data['items'] if row['md5']==MEMBER)
        with Image.open(destination/member['resources'][0]['path']) as image:self.assertEqual(image.n_frames,2)
        thumb=next(row for row in data['items'] if row['md5']==THUMB)
        self.assertEqual(thumb['quality'],'thumbnail');self.assertEqual(thumb['resources'][0]['role'],'thumbnail')
        for name in ('data.json','index.html','resource-report.jsonl'):
            content=(destination/name).read_text(encoding='utf-8')
            for secret in ('secret-aes-value','secret-auth-value','secret-token','aes_key'):self.assertNotIn(secret,content)
        self.assertFalse(list(destination.rglob('*.db')));self.assertFalse(list(destination.rglob('*key*')))

    def test_moments_are_exactly_owner_only_even_when_xml_author_disagrees(self):
        catalog=MomentsCatalog(self.library,USER);posts=list(catalog.posts())
        self.assertEqual({p['id'] for p in posts},{'100','103'})
        self.assertEqual(catalog.summary()['count'],2)
        for post in posts:self.assertEqual(post['author'],USER)
        self.assertIsNone(moment_from_row({'tid':1,'user_name':'friend','content':'anything'},USER))

    def test_moments_export_uses_verified_local_image_and_never_exports_media_credentials(self):
        destination=self.root/'moments';destination.mkdir()
        with patch('core.resources.ResourceStore._download',side_effect=AssertionError('Cached image should not download')):
            result=export_moments(self.archive,self.library,{'includeImages':True,'includeVideos':False},destination,ASSETS,lambda *a:None,lambda:None,lambda _:None)
        data=json.loads((destination/'data.json').read_text(encoding='utf-8'))
        self.assertEqual(result['count'],2)
        valid=next(row for row in data['items'] if row['id']=='100')
        self.assertEqual((destination/valid['resources'][0]['path']).read_bytes(),PNG)
        self.assertNotIn('secret-token',(destination/'data.json').read_text(encoding='utf-8'))
        self.assertNotIn('<script>',(destination/'index.html').read_text(encoding='utf-8').split('const data=')[1].split(',size=')[0])
        self.assertTrue(data['partial_local_cache'])

    def test_skip_images_happens_before_any_media_lookup_or_download(self):
        destination=self.root/'text-moments';destination.mkdir()
        with patch('core.account_exporting.MomentResources.local_candidates',side_effect=AssertionError('Skipped image touched local media')),patch('core.resources.ResourceStore._download',side_effect=AssertionError('Skipped image downloaded')):
            result=export_moments(self.archive,self.library,{'includeImages':False,'includeVideos':False},destination,ASSETS,lambda *a:None,lambda:None,lambda _:None)
        self.assertEqual(result['resource_summary']['skipped'],1)
        self.assertFalse(list((destination/'resources').rglob('*.png')))

    def test_sns_encrypted_image_over_one_keystream_block_is_decrypted_offline(self):
        seed='998877665544332211';image=Image.frombytes('RGB',(64,64),random.Random(62).randbytes(64*64*3))
        output=io.BytesIO();image.save(output,format='PNG');raw=output.getvalue();self.assertGreater(len(raw),2048)
        cache=Path(self.library['account_dir'])/'cache/2026-11/Sns/Img'/FAVORITE[:2]/FAVORITE
        cache.write_bytes(Isaac64(seed).xor(raw))
        database=Path(self.library['root'])/'sns/sns.db'
        with closing(sqlite3.connect(database)) as con,con:
            content=con.execute('SELECT content FROM SnsTimeLine WHERE tid=100').fetchone()[0]
            content=content.replace('<url md5=',f'<url key="{seed}" token="synthetic-sns-token" md5=')
            con.execute('UPDATE SnsTimeLine SET content=? WHERE tid=100',(content,))
        destination=self.root/'encrypted-sns';destination.mkdir()
        with patch('core.resources.ResourceStore._download',side_effect=AssertionError('Encrypted cached image should not download')):
            export_moments(self.archive,self.library,{'includeImages':True},destination,ASSETS,lambda *a:None,lambda:None,lambda _:None)
        data=json.loads((destination/'data.json').read_text(encoding='utf-8'));post=next(p for p in data['items'] if p['id']=='100')
        self.assertEqual((destination/post['resources'][0]['path']).read_bytes(),raw)
        for name in ('data.json','index.html','resource-report.jsonl'):
            public=(destination/name).read_text(encoding='utf-8');self.assertNotIn(seed,public);self.assertNotIn('synthetic-sns-token',public)

    def test_sns_video_prefix_is_decrypted_and_image_covers_never_become_video(self):
        seed='123459876543210';destination=self.root/'video-sns';destination.mkdir()
        encrypted=self.root/'encrypted-video';encrypted.write_bytes(Isaac64(seed).xor(MP4))
        cover=self.root/'cover.png';cover.write_bytes(PNG)
        store=ResourceStore(self.archive.data,'',destination,options={'includeAvatars':False})
        try:
            resolver=MomentResources(store)
            with patch.object(store.codec,'video',side_effect=AssertionError('A cover image must not be transcoded into a fake video')):
                self.assertIsNone(resolver.convert(cover,'video',{}))
            resource=resolver.convert(encrypted,'video',{'stream_keys':[seed]})
            self.assertIsNotNone(resource);self.assertEqual((destination/resource['path']).read_bytes(),MP4)
        finally:store.close()

    def test_wxgf_conversion_keeps_multiple_hevc_frames(self):
        frames=[Image.new('RGB',(32,32),color) for color in ('red','blue','green')]
        source=self.root/'animated.gif';frames[0].save(source,save_all=True,append_images=frames[1:],duration=100,loop=0)
        stream=self.root/'synthetic.hevc';codec=MediaCodec(lambda:None)
        code,errors=codec._run(['-loglevel','error','-i',str(source),'-c:v','libx265','-pix_fmt','yuv420p',
                              '-x265-params','pools=1:frame-threads=1','-f','hevc',str(stream)],15)
        self.assertEqual(code,0,errors[-300:])
        result=codec.sticker(b'wxgf'+stream.read_bytes())
        self.assertIsNotNone(result)
        with Image.open(io.BytesIO(result)) as image:self.assertGreaterEqual(image.n_frames,3)

    def test_bridge_export_job_opens_correct_collection_and_invalid_groups_clean_staging(self):
        service=Service(ASSETS,self.root/'state');service.library=self.library;service.config['export_dir']=str(self.root/'exports')
        try:
            first=service.export_account({'kind':'moments','start':'2026-01-01','end':'2030-12-31','includeImages':False,'includeVideos':False})
            service.export_account({'kind':'stickers','groups':['../../not-a-group'],'download':False})
            service.pool.shutdown(wait=True)
            tasks=service.state()['tasks'];self.assertEqual(tasks[0]['status'],'failed');self.assertEqual(tasks[1]['status'],'completed')
            self.assertEqual(service.task_file(first['job']).name,'index.html')
            self.assertIn('我的朋友圈',service.task_folder(first['job']).name)
            self.assertFalse(list((self.root/'exports').glob('.partial_*')))
        finally:service.shutdown()

    def test_refresh_cancelled_by_logout_cannot_restore_library(self):
        service=Service(ASSETS,self.root/'refresh-state');service.library=service.config['library']=self.library
        # Match the service's private key-cache location without using real credentials.
        keys_file=Path(self.library['root']).parent/'keys.json';keys_file.write_text('{}')
        try:
            with patch.object(service.pool,'submit') as submit:service.refresh_assets()
            def decrypt(keys,source,destination,**kwargs):
                path=Path(destination)/'sns/sns.db';path.parent.mkdir(parents=True);path.write_bytes(b'fixture')
                service.logout();return {'ok':['sns/sns.db'],'failed':[]}
            with patch('wx4.key.load_keys',return_value={'sns/sns.db':{'enc_key':'synthetic'}}),patch('wx4.decrypt.decrypt_all',side_effect=decrypt):
                fn,*args=submit.call_args.args;fn(*args)
            self.assertIsNone(service.library);self.assertEqual(service.state()['tasks'][0]['status'],'cancelled')
            self.assertFalse(list(Path(self.library['root']).parent.glob('assets_*')))
        finally:service.shutdown()

    def test_refresh_publishes_new_snapshot_and_preserves_untouched_database(self):
        service=Service(ASSETS,self.root/'refresh-success');service.library=service.config['library']=self.library
        old_revision=service.state()['library']['data_revision']
        original=Path(self.library['root'])/'sns/sns.db';before=original.read_bytes()
        (Path(self.library['root']).parent/'keys.json').write_text('{}')
        def decrypt(keys,source,destination,**kwargs):
            path=Path(destination)/'sns/sns.db';path.parent.mkdir(parents=True);shutil.copy2(original,path)
            with closing(sqlite3.connect(path)) as con,con:con.execute('INSERT INTO SnsTimeLine VALUES (?,?,?,?)',(104,USER,'unsupported-own-cache',''))
            return {'ok':['sns/sns.db'],'failed':[]}
        try:
            with patch('wx4.key.load_keys',return_value={'sns/sns.db':{'enc_key':'synthetic'}}),patch('wx4.decrypt.decrypt_all',side_effect=decrypt):
                service.refresh_assets();service.pool.shutdown(wait=True)
            self.assertEqual(service.state()['tasks'][0]['status'],'completed')
            self.assertNotEqual(service.state()['library']['data_revision'],old_revision)
            self.assertEqual(service.account_assets({'kind':'moments','start':'1970-01-01','end':'2030-12-31'})['count'],3)
            self.assertEqual(service.account_assets({'kind':'stickers'})['total'],4)
            self.assertEqual(original.read_bytes(),before)
            new_root=Path(service.library['assets_root']);self.assertTrue(new_root.is_dir())
            service.logout();self.assertTrue(new_root.is_dir())
        finally:service.shutdown()


class AppearanceAndFolderTests(unittest.TestCase):
    def test_standard_isaac64_fixed_vectors_and_result_block_refill(self):
        expected=[0x9d39247e33776d41,0x2af7398005aaa5c7,0x44db015024623547,0x9c15f73e62a76ae2,
                  0x75834465489c0c89,0x3290ac3a203001bf,0x0fbbad1f61042279,0xe83a908ff2fb60ca]
        generator=Isaac64(0);words=[generator.word() for _ in range(512)]
        self.assertEqual(words[:8],expected);self.assertNotEqual(words[:256],words[256:])
        with self.assertRaises(ValueError):Isaac64('not-a-seed')

    def test_all_eight_accents_persist_with_dark_mode_and_old_config_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for accent in ACCENT_IDS:
                service=Service(ASSETS,root)
                service.settings({'accent':accent,'theme':'dark'});service.shutdown()
                again=Service(ASSETS,root)
                try:
                    self.assertEqual(again.state()['accent'],accent);self.assertEqual(again.state()['theme'],'dark')
                    self.assertEqual(again.state()['appearance']['background'],palette('dark',accent)['background'])
                    with self.assertRaises(ValueError):again.settings({'accent':[]})
                finally:again.shutdown()
            config=json.loads((root/'config.json').read_text(encoding='utf-8'));config['accent']=[]
            (root/'config.json').write_text(json.dumps(config),encoding='utf-8')
            migrated=Service(ASSETS,root)
            try:self.assertEqual(migrated.state()['accent'],'violet')
            finally:migrated.shutdown()

    def test_readable_folder_names_sanitize_identity_and_avoid_collision(self):
        name=export_folder_name('昵称/群聊:测试','wxid_fixture@chatroom',datetime(2026,11,1,18,30))
        self.assertTrue(name.startswith('昵称_群聊_测试_wxid_fixture@chatroom_2026-11-01_18-30-00'))
        self.assertNotIn('/',name);self.assertNotIn(':',name)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/name).mkdir();second=unused_folder(root,name)
            self.assertEqual(second.name,name+'_2');self.assertEqual(second.parent,root)


if __name__=='__main__':unittest.main()
