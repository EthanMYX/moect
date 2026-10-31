import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
import zstandard
from core.data import Archive, validate_root
from core.exporting import export_session, safe_name, csv_cell
from core.service import Service, options_from

USER='wxid_fixture'; SESSION='fixture@chatroom'


def fixture(root, count=1050):
    for folder in ('contact','session','message'): (root/folder).mkdir(parents=True)
    with closing(sqlite3.connect(root/'contact'/'contact.db')) as con, con:
        con.execute('CREATE TABLE contact (id INTEGER,username TEXT,local_type INTEGER,alias TEXT,remark TEXT,nick_name TEXT,big_head_url TEXT,small_head_url TEXT,description TEXT)')
        con.executemany('INSERT INTO contact VALUES (?,?,0,?,?,?,?,?,?)',
                        [(1,USER,'','我','自己','','',''),(2,'friend','','同事','朋友','','',''),(3,SESSION,'','测试群','测试群','','','')])
    with closing(sqlite3.connect(root/'session'/'session.db')) as con, con:
        con.execute('CREATE TABLE SessionTable (username TEXT,last_timestamp INTEGER,sort_timestamp INTEGER,summary TEXT)')
        con.execute('INSERT INTO SessionTable VALUES (?,?,?,?)',(SESSION,1800000000,1800000000,'synthetic only'))
    table='Msg_'+hashlib.md5(SESSION.encode()).hexdigest()
    for shard in range(2):
        with closing(sqlite3.connect(root/'message'/f'message_{shard}.db')) as con, con:
            con.execute('CREATE TABLE Name2Id (user_name TEXT)')
            con.executemany('INSERT INTO Name2Id VALUES (?)',[(USER,),('friend',)])
            con.execute(f'CREATE TABLE "{table}" (local_id INTEGER, server_id TEXT, local_type INTEGER, sort_seq INTEGER, real_sender_id INTEGER,create_time INTEGER,message_content BLOB,compress_content BLOB,packed_info_data BLOB)')
            for i in range(shard,count,2):
                text='message '+str(i)
                if i==8: text='<script>alert("never")</script> 特殊字符'
                if i==10: text='=2+2'
                if i==12: text='压缩关键词'
                content=zstandard.ZstdCompressor().compress(text.encode()) if i==12 else text
                con.execute(f'INSERT INTO "{table}" VALUES (?,?,?,?,?,?,?,?,?)',
                            (i+1,str(i+1),1,i,1 if i%3==0 else 2,1800000000+i//4,content,None,None))
    return dict(root=str(root),wxid=USER,name='fixture')


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.lib=fixture(self.root/'db')
        self.archive=Archive(self.lib)
    def tearDown(self):
        self.archive.close();self.temp.cleanup()

    def test_cursor_no_skips_or_duplicates_across_shards_and_ties(self):
        self.assertEqual(len(self.archive.sessions()),1)
        seen=[];before=None
        while True:
            page=self.archive.page(SESSION,before=before,limit=43)
            seen.extend(m['server_id'] for m in page['messages'])
            before=page['cursor']
            if not page['more']:break
        self.assertEqual(len(seen),1050)
        self.assertEqual(len(set(seen)),1050)

    def test_search_compressed_and_date_filter(self):
        rows=list(self.archive.messages(SESSION,{'query':'压缩关键词'}))
        self.assertEqual(len(rows),1)
        rows=list(self.archive.messages(SESSION,{'start':1800000001,'end':1800000001}))
        self.assertEqual(len(rows),4)

    def test_export_formats_and_safe_html_chunks(self):
        out=self.root/'out';out.mkdir()
        assets=Path(__file__).parent.parent/'ui'
        session=self.archive.sessions()[0]
        for fmt in ('html','json','jsonl','csv','txt','md'):
            result=export_session(self.archive,session,{'format':fmt},out,assets,lambda n:None,lambda:None)
            self.assertEqual(result['count'],1050)
            path=Path(result['path']);self.assertTrue(path.exists())
            if fmt=='html':
                self.assertEqual(len(list(path.parent.glob('c*.js'))),3)
                self.assertNotIn('<script>alert',path.read_text(encoding='utf-8'))
            if fmt=='json':self.assertEqual(len(json.loads(path.read_text(encoding='utf-8'))['messages']),1050)
            if fmt=='csv':self.assertIn("'=2+2",path.read_text(encoding='utf-8-sig'))

    def test_service_job_persistence_and_private_state(self):
        service=Service(Path(__file__).parent.parent/'ui',root=self.root/'state')
        service.config['export_dir']=str(self.root/'exports')
        service.import_archive(self.lib['root'])
        self.assertNotIn('root',service.state()['library'])
        result=service.export({'sessions':[SESSION],'format':'json','query':'关键词'})
        service.pool.shutdown(wait=True)
        task=service.state()['tasks'][0]
        self.assertEqual(task['status'],'completed')
        self.assertEqual(task['count'],1)
        self.assertNotIn('folder',task)
        self.assertTrue((service.task_folder(result['job'])/'index.html').exists())
        again=Service(Path(__file__).parent.parent/'ui',root=self.root/'state')
        self.assertEqual(again.state()['tasks'][0]['status'],'completed');again.shutdown()

    def test_invalid_options_and_reserved_names(self):
        self.assertEqual(safe_name('CON'),'_CON')
        self.assertNotIn('/',safe_name('../../foo'))
        self.assertEqual(csv_cell('@SUM(A1)'),"'@SUM(A1)")
        with self.assertRaises(ValueError):options_from({'start':'2026-12-01','end':'2026-01-01'})
        self.assertEqual(validate_root(self.lib['root']),self.lib['root'])

    def test_cancelled_job_does_not_run(self):
        service=Service(Path(__file__).parent.parent/'ui',root=self.root/'cancel-state')
        job=service._new_job('export','cancel fixture')
        service.cancel(job['id'])
        service._run(job,lambda:self.fail('cancelled job executed'))
        self.assertEqual(job['status'],'cancelled');service.shutdown()

    def test_qce_preview_bridge_counts_pagination_and_search(self):
        service=Service(Path(__file__).parent.parent/'ui',root=self.root/'preview-state')
        service.library=self.lib
        first=service.qce_preview({'peer':{'peerUid':SESSION},'page':1,'limit':50})
        second=service.qce_preview({'peer':{'peerUid':SESSION},'page':2,'limit':50})
        self.assertEqual(first['totalCount'],1050)
        self.assertEqual(first['totalPages'],21)
        self.assertTrue(first['hasNext'])
        self.assertFalse({m['msgId'] for m in first['messages']} & {m['msgId'] for m in second['messages']})
        search=service.qce_preview({'peer':{'peerUid':SESSION},'filter':{'query':'压缩关键词'}})
        self.assertEqual(search['totalCount'],1)
        self.assertEqual(search['messages'][0]['elements'][0]['textElement']['content'],'压缩关键词')
        service.shutdown()

    def test_date_time_filter_keeps_minutes(self):
        first=options_from({'start':'2026-10-30T10:30','end':'2026-10-30T10:31'})
        self.assertEqual(first['end']-first['start'],119)


if __name__=='__main__':unittest.main()
