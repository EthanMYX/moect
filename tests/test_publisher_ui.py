"""Built author UI with synthetic bridge/data; no live author changes or publishing."""
import base64
import functools
import http.server
import json
import threading
import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright
from tests.test_resources import PNG

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class PublisherUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(ROOT)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/ui-publisher/publisher.html'
        cls.runtime = sync_playwright().start()
        cls.browser = cls.runtime.chromium.launch(channel='msedge', headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.runtime.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def page(self, invalid=False, block_script=False):
        context = self.browser.new_context(viewport={'width':1120, 'height':800}, reduced_motion='reduce')
        self.addCleanup(context.close)
        page = context.new_page()
        if block_script:
            page.route('**/ui-publisher/assets/*.js', lambda route: route.abort())
        data_url = 'data:image/png;base64,' + base64.b64encode(PNG).decode('ascii')
        state={'ui_generation':1,'editor':{'title':'Synthetic notice','body':'A synthetic picture.\n\n![Synthetic picture](editor-images/synthetic.png)','days':90,'tab':'announcement'},
               'theme':'light','connection':{'status':'connected'},'job':{'status':'idle'},'notices':[],'history':[],'retired':[],'cleanup_pending':[],'setup_error':{'invalid':True} if invalid else ''}
        page.add_init_script('window.__imageData=' + json.dumps(data_url) + ';window.__state=' + json.dumps(state) + r''';
          window.__calls=[];window.__imageCalls=[];
          const state=window.__state;
          window.pywebview={api:{invoke:async(action,payload={})=>{
            window.__calls.push(action);
            let result={ok:true};
            if(action==='publisher_state'||action==='publisher_check')result=state;
            else if(action==='publisher_preview_image'){
              window.__imageCalls.push(payload.source);await new Promise(resolve=>setTimeout(resolve,70));result={url:window.__imageData};
            }else if(action==='publisher_save_editor'){state.editor={...payload};}
            return {result:structuredClone(result)};
          }}};
        ''')
        page.goto(self.url)
        return page

    def test_preview_image_survives_polling_typing_and_theme_changes(self):
        page = self.page()
        page.wait_for_function('()=>window.__publisherReady===true')
        page.wait_for_function("()=>document.querySelector('.pub-preview .pub-markdown img')?.naturalWidth>0")
        page.evaluate("()=>window.__originalImage=document.querySelector('.pub-preview .pub-markdown img')")
        page.wait_for_function("()=>window.__calls.filter(a=>a==='publisher_state').length>=4")
        self.assertTrue(page.evaluate('()=>window.__originalImage.isConnected'))
        self.assertEqual(page.evaluate('window.__imageCalls'), ['editor-images/synthetic.png'])
        page.locator('.pub-body-input').fill('Edited synthetic text.\n\n![Synthetic picture](editor-images/synthetic.png)')
        page.get_by_text('Edited synthetic text.', exact=True).wait_for()
        page.get_by_role('button', name='切换深色外观', exact=True).click()
        self.assertTrue(page.evaluate("()=>document.querySelector('.pub-preview .pub-markdown img')===window.__originalImage"))
        self.assertEqual(page.evaluate('window.__imageCalls'), ['editor-images/synthetic.png'])
        self.assertEqual(page.evaluate("window.__calls.filter(a=>a==='publisher_start').length"), 0)

    def test_readiness_is_sent_after_first_successful_render(self):
        page = self.page()
        page.wait_for_function("()=>window.__calls.includes('publisher_ui_ready')")
        self.assertFalse(page.locator('#publisher-boot').is_visible())
        self.assertTrue(page.locator('.pub-app').is_visible())

    def test_failed_entry_script_shows_recovery_instead_of_empty_white_window(self):
        page = self.page(block_script=True)
        page.locator('#publisher-boot-retry').wait_for()
        self.assertTrue(page.get_by_text('界面暂时未能载入', exact=True).is_visible())
        page.locator('#publisher-boot-retry').click()
        self.assertIn('publisher_reload_ui', page.evaluate('window.__calls'))

    def test_render_exception_has_recovery_and_never_publishes(self):
        page = self.page(invalid=True)
        page.locator('#publisher-boot-retry').wait_for()
        page.wait_for_function("()=>window.__calls.includes('publisher_ui_error')")
        self.assertFalse(page.evaluate('window.__publisherReady'))
        self.assertNotIn('publisher_start', page.evaluate('window.__calls'))


if __name__ == '__main__':
    unittest.main()
