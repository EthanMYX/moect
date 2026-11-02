"""Code-only placement, durable preferences and standalone archive navigation."""
import json
import re
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

from core.service import Service
from core.window_state import restore_placement,frame_color,DEFAULT_SIZE
from tests.test_resources import ASSETS


class WindowStateTests(unittest.TestCase):
    def setUp(self):
        self.screen={'name':'primary','x':0,'y':0,'width':1920,'height':1040,'dpi':96,'primary':True}
        self.saved={'x':100,'y':120,'width':1200,'height':800,'dpi':96,'monitor':'primary',
                    'work_area':dict(self.screen),'maximized':False}

    def test_same_monitor_size_position_and_maximized_state_survive(self):
        result=restore_placement(self.saved,[self.screen])
        for key in ('x','y','width','height'):self.assertEqual(result[key],self.saved[key])
        self.assertFalse(result['maximized'])
        result=restore_placement({**self.saved,'maximized':True},[self.screen])
        self.assertTrue(result['maximized']);self.assertEqual(result['width'],1200)
        self.assertLess(DEFAULT_SIZE[0],1360)

    def test_dpi_changes_preserve_logical_size_and_relative_position(self):
        screen={**self.screen,'dpi':144,'width':2880,'height':1560,'x':1920}
        result=restore_placement(self.saved,[screen])
        self.assertEqual((result['x'],result['y'],result['width'],result['height']),(2070,180,1800,1200))

    def test_negative_monitor_origins_and_removed_monitor_fit_inside_work_area(self):
        left={**self.screen,'name':'left','x':-1920,'primary':False}
        saved={**self.saved,'x':-1800,'monitor':'left','work_area':dict(left)}
        self.assertEqual(restore_placement(saved,[left,self.screen])['x'],-1800)
        result=restore_placement(saved,[self.screen])
        self.assertGreaterEqual(result['x'],0);self.assertLessEqual(result['x']+result['width'],1920)
        self.assertLessEqual(result['y']+result['height'],1040)
        small={**self.screen,'width':900,'height':600}
        result=restore_placement(self.saved,[small]);self.assertEqual((result['width'],result['height']),(900,600))

    def test_invalid_geometry_falls_back_and_mask_matches_light_and_dark_alpha(self):
        for value in (None,{},[],{**self.saved,'width':True},{**self.saved,'x':float('nan')},{**self.saved,'width':0}):
            self.assertIsNone(restore_placement(value,[self.screen]))
        self.assertEqual(frame_color('#ffffff',True),'#bfbfbf')
        self.assertEqual(frame_color('#101010',True,True),'#080808')
        self.assertEqual(frame_color('#7056c4'),'#7056c4')

    def test_sort_preferences_default_recent_and_persist_with_other_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            service=Service(ASSETS,temp)
            try:
                self.assertEqual(service.state()['session_sort'],{'field':'lastActivity','order':'desc'})
                wanted={'field':'name','order':'asc'}
                service.settings({'session_sort':wanted,'accent':'blue'})
                reloaded=Service(ASSETS,temp)
                try:
                    self.assertEqual(reloaded.state()['session_sort'],wanted)
                    self.assertEqual(reloaded.config['accent'],'blue')
                finally:reloaded.shutdown()
                for value in (None,[],{'field':'bad','order':'asc'},{'field':'name','order':'sideways'}):
                    with self.assertRaises(ValueError):service.settings({'session_sort':value,'accent':'violet'})
                self.assertEqual(service.config['session_sort'],wanted);self.assertEqual(service.config['accent'],'blue')
            finally:service.shutdown()

    def test_full_client_overlay_never_repaints_native_frame_and_resize_is_validated(self):
        from edge_app import Api
        with tempfile.TemporaryDirectory() as temp:
            service=Service(ASSETS,temp);api=Api(service);edges=[]
            form=SimpleNamespace(BackColor='',Invoke=lambda action:action())
            api._window=SimpleNamespace(native=form)
            api._frame=SimpleNamespace(resize=edges.append,isMaximized=lambda:False)
            modules={'System':SimpleNamespace(Action=lambda fn:fn),
                     'System.Drawing':SimpleNamespace(ColorTranslator=SimpleNamespace(FromHtml=lambda color:color))}
            try:
                with patch.dict('sys.modules',modules):
                    self.assertNotIn('error',api.invoke('window_overlay',{'active':True}))
                    self.assertEqual(form.BackColor,'')
                    self.assertNotIn('error',api.invoke('settings',{'accent':'green','theme':'dark'}))
                    self.assertEqual(form.BackColor,service.appearance()['background'])
                    api.invoke('window_overlay',{'active':False})
                    self.assertEqual(form.BackColor,service.appearance()['background'])
                    self.assertIn('error',api.invoke('window_overlay',{'active':'yes'}))
                    for edge in ('n','s','e','w','nw','ne','sw','se'):
                        self.assertNotIn('error',api.invoke('window_resize',{'edge':edge}))
                    self.assertEqual(len(edges),8)
                    for edge in (None,'bad',[],True):self.assertIn('error',api.invoke('window_resize',{'edge':edge}))
                    self.assertEqual(len(edges),8)
            finally:service.shutdown()


class ArchivePaginationTests(unittest.TestCase):
    def test_actual_query_loads_latest_keeps_numbered_jump_and_filters_bounded(self):
        source=(ASSETS/'viewer.html').read_text(encoding='utf-8')
        model=re.search(r'^function paginationModel[^\n]+',source,re.M).group()
        render=source[source.index('function renderPagination('):source.index('function draw(){')]
        helpers='\n'.join(re.search(r'^function '+name+r'[^\n]+',source,re.M).group() for name in ('matches','outside'))
        query=source[source.index('async function query('):source.index('async function jump(')]
        script='''const assert=require('node:assert/strict');
let page=0,pageGroup=0,reading=false,records=[],generation=0,total=0,selection=null,size=80,loads=[],scrolled=[];
let filter={q:'',start:null,end:null},manifest={count:1360,chunks:[]};
const chunks=Array.from({length:17},(_,i)=>Array.from({length:80},(_,j)=>({create_time:i*80+j,text:String(i*80+j)})));
manifest.chunks=chunks.map(rows=>({count:rows.length,start_time:rows[0].create_time,end_time:rows.at(-1).create_time}));
function fake(){return {children:[],disabled:false,hidden:false,textContent:'',replaceChildren(){this.children=[]},append(el){this.children.push(el)},setAttribute(k,v){this[k]=v}}}
const elements=new Map(),$=id=>{if(!elements.has(id))elements.set(id,fake());return elements.get(id)};
const element=(tag,cls,value)=>({...fake(),textContent:String(value)});
const document={documentElement:{scrollHeight:5000}},scrollTo=(x,y)=>scrolled.push(y),requestAnimationFrame=fn=>fn();
const filters=()=>({...filter}),searchable=m=>m.text,load=async i=>{loads.push(i);return chunks[i]};
function draw(){renderPagination()}
'''+model+'\n'+render+'\n'+helpers+'\n'+query+'''
(async()=>{
 await query();assert.equal(page,16);assert.equal(records[0].create_time,1280);assert.equal(records.at(-1).create_time,1359);assert.deepEqual(loads,[16]);assert.equal(scrolled.at(-1),5000);
 assert.deepEqual($('#page-buttons').children.map(b=>+b.textContent),[11,12,13,14,15,16,17]);assert.equal($('#prev-group').disabled,false);assert.equal($('#next-group').disabled,true);
 pageGroup=0;renderPagination(false);assert.deepEqual($('#page-buttons').children.map(b=>+b.textContent),[1,2,3,4,5,6,7,8,9,10]);assert.equal(page,16);assert.equal($('#next-group').disabled,false);
 await $('#page-buttons').children[2].onclick();assert.equal(page,2);assert.equal(records[0].create_time,160);assert.equal(scrolled.at(-1),0);
 filter={q:'',start:300,end:304};await query();assert.deepEqual(records.map(r=>r.create_time),[300,301,302,303,304]);assert.equal(page,0);assert.equal($('#prev-group').hidden,true);assert.equal($('#next-group').hidden,true);
 filter={q:'none',start:null,end:null};await query();assert.equal(total,0);assert.equal(records.length,0);assert.equal($('#page-buttons').children.length,0);assert.equal($('#next').disabled,true);
 assert.deepEqual(paginationModel(800,0).numbers,[1,2,3,4,5,6,7,8,9,10]);assert.equal(paginationModel(801,0).nextGroup,true);assert.deepEqual(paginationModel(801,10).numbers,[11]);
})().catch(e=>{console.error(e);process.exitCode=1});'''
        result=subprocess.run(['node'],input=script,text=True,encoding='utf-8',capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_invalid_stored_sort_recovers_without_affecting_other_preferences(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp)/'config.json').write_text(json.dumps({'session_sort':'bad','accent':'violet','theme':'dark'}))
            service=Service(ASSETS,temp)
            try:
                self.assertEqual(service.state()['session_sort']['field'],'lastActivity')
                self.assertEqual(service.config['theme'],'dark')
            finally:service.shutdown()


if __name__=='__main__':unittest.main()
