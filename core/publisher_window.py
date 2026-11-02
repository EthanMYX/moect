"""Native startup cover and WebView2 failure recovery for the author console."""
import json
import os
from datetime import datetime, timezone


class PublisherWindow:
    def __init__(self, api, form):
        from System.Drawing import ColorTranslator, Font, Point, Size, ContentAlignment
        from System.Windows.Forms import Panel, Label, Button, DockStyle, FlatStyle, Timer

        self.api = api
        self.form = form
        self.guard = api._startup
        self.closed = False
        self.core = None
        self.must_recreate = False
        self.events = []
        self.log_lock = self.guard.lock
        self.path = api._service.root / 'startup-diagnostic.json'
        self.panel = Panel()
        self.panel.Dock = DockStyle.Fill
        self.panel.BackColor = ColorTranslator.FromHtml(api._service.appearance()['background'])
        self.title = Label()
        self.title.Text = 'Moect 发布中心'
        self.title.Font = Font('Microsoft YaHei UI', 19)
        self.title.ForeColor = ColorTranslator.FromHtml('#9777da')
        self.title.TextAlign = ContentAlignment.MiddleCenter
        self.message = Label()
        self.message.Text = '正在加载界面，请稍候…'
        self.message.Font = Font('Microsoft YaHei UI', 10)
        self.message.ForeColor = ColorTranslator.FromHtml('#92869f')
        self.message.TextAlign = ContentAlignment.MiddleCenter
        self.retry = Button()
        self.retry.Text = '重新加载界面'
        self.retry.BackColor = ColorTranslator.FromHtml('#7955c4')
        self.retry.ForeColor = ColorTranslator.FromHtml('#ffffff')
        self.retry.FlatStyle = FlatStyle.Flat
        self.retry.FlatAppearance.BorderSize = 0
        self.retry.Font = Font('Microsoft YaHei UI', 10)
        self.retry.Visible = False
        self.exit = Button()
        self.exit.Text = '关闭'
        self.exit.FlatStyle = FlatStyle.Flat
        self.exit.FlatAppearance.BorderSize = 0
        self.exit.ForeColor = ColorTranslator.FromHtml('#92869f')
        self.exit.Font = Font('Microsoft YaHei UI', 10)
        self.exit.Visible = True
        for control in (self.title, self.message, self.retry, self.exit):
            self.panel.Controls.Add(control)

        def layout(*_):
            width = form.ClientSize.Width
            height = form.ClientSize.Height
            self.title.Location = Point(0, max(0, height // 2 - 90))
            self.title.Size = Size(width, 60)
            self.message.Location = Point(20, max(0, height // 2 - 25))
            self.message.Size = Size(max(1, width - 40), 54)
            self.retry.Location = Point(max(0, width // 2 - 150), height // 2 + 45)
            self.retry.Size = Size(180, 40)
            self.exit.Location = Point(width // 2 + 45, height // 2 + 45)
            self.exit.Size = Size(100, 40)

        self._handlers = [layout, lambda *_: self.reload(manual=True), lambda *_: api._window.destroy()]
        form.Resize += self._handlers[0]
        self.retry.Click += self._handlers[1]
        self.exit.Click += self._handlers[2]
        form.Controls.Add(self.panel)
        self.panel.BringToFront()
        layout()
        self._initialization = self.initialized
        self._navigation = self.navigation
        self._completed = self.completed
        form.webview.CoreWebView2InitializationCompleted += self._initialization
        form.webview.NavigationStarting += self._navigation
        form.webview.NavigationCompleted += self._completed
        if form.webview.CoreWebView2 is not None:
            self.initialized(form.webview, None)
        self.timer = Timer()
        self.timer.Interval = 350
        self._timer_tick = lambda *_: self.tick()
        self.timer.Tick += self._timer_tick
        self.timer.Start()
        self.record('window_created')

    def record(self, code, **metadata):
        # Never record keys, tokens, announcement bodies, URLs or editor input.
        with self.log_lock:
            try:
                events = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(events, list):
                    events = []
            except (OSError, ValueError):
                events = []
            events.append({'at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                           'pid': os.getpid(), 'code': code, 'generation': self.guard.generation,
                           'retries': self.guard.retries, **metadata})
            try:
                temporary = self.path.with_suffix('.tmp')
                temporary.write_text(json.dumps(events[-100:], ensure_ascii=False), encoding='utf-8')
                os.replace(temporary, self.path)
            except OSError:
                pass

    def initialized(self, sender, args):
        if self.closed:
            return
        if args is not None and not args.IsSuccess:
            self.must_recreate = True
            self.record('webview_initialization_failed')
            self.guard.fail('webview_initialization_failed')
            return
        core = sender.CoreWebView2
        if core is None or core is self.core:
            return
        self.core = core
        self.must_recreate = False
        self._process_failed = self.process_failed
        core.ProcessFailed += self._process_failed
        try:
            core.Settings.IsNonClientRegionSupportEnabled = True
            core.AddScriptToExecuteOnDocumentCreatedAsync('window.__wceNativeRegions=true;')
        except Exception:
            pass
        self.record('webview_initialized')

    def navigation(self, *_):
        if not self.closed:
            self.guard.begin_document()
            self.record('navigation_started')

    def completed(self, sender, args):
        if self.closed:
            return
        self.record('navigation_completed', success=bool(args.IsSuccess))
        if not args.IsSuccess:
            self.guard.fail('navigation_failed')

    def process_failed(self, sender, args):
        if not self.closed:
            kind = str(args.ProcessFailedKind)
            if kind == 'BrowserProcessExited':
                self.must_recreate = True
            self.record('webview_process_failed', kind=kind)
            self.guard.fail('webview_process_failed')

    def recreate(self):
        # WebView2 cannot Reload a terminated browser or a failed environment.
        # Recreate only the browser control; the service and its job stay alive.
        from webview.platforms.edgechromium import EdgeChrome
        old = self.form.webview
        try:
            old.CoreWebView2InitializationCompleted -= self._initialization
            old.NavigationStarting -= self._navigation
            old.NavigationCompleted -= self._completed
            if self.core is not None:
                self.core.ProcessFailed -= self._process_failed
        except Exception:
            pass
        self.core = None
        self.form.Controls.Remove(old)
        old.Dispose()
        profile = self.api._service.root / 'webview2-recovery' / f'{os.getpid()}-{self.guard.generation}'
        profile.mkdir(parents=True, exist_ok=True)
        self.form.browser = EdgeChrome(self.form, self.api._window, str(profile))
        self.form.webview = self.form.browser.webview
        self.form.webview.CoreWebView2InitializationCompleted += self._initialization
        self.form.webview.NavigationStarting += self._navigation
        self.form.webview.NavigationCompleted += self._completed
        self.panel.BringToFront()
        if self.form.webview.CoreWebView2 is not None:
            self.initialized(self.form.webview, None)
        self.record('browser_control_recreated')

    def reload(self, manual=False):
        if self.closed:
            return
        if manual:
            self.guard.manual_retry()
        self.panel.Show()
        self.panel.BringToFront()
        self.retry.Visible = False
        self.exit.Visible = True
        self.message.Text = '正在重新加载界面，后台任务不会重复提交…'
        self.record('manual_reload' if manual else 'automatic_reload')
        try:
            if self.must_recreate or self.form.webview.IsDisposed:
                self.recreate()
            elif self.form.webview.CoreWebView2 is not None:
                self.form.webview.CoreWebView2.Reload()
            else:
                self.form.webview.EnsureCoreWebView2Async(None)
        except Exception:
            self.record('reload_failed')
            self.guard.fail('reload_failed')

    def tick(self):
        if self.closed:
            return
        if self.guard.is_ready:
            self.panel.Hide()
            return
        self.panel.Show()
        self.panel.BringToFront()
        action = self.guard.tick()
        if action == 'reload':
            self.reload()
        elif action == 'failed':
            self.record('startup_recovery_exhausted', reason=self.guard.reason)
            self.message.Text = '界面暂时未能载入。作者资料和已保存的草稿仍在本机。'
            self.retry.Visible = self.exit.Visible = True

    def close_blocked(self):
        if not self.guard.is_ready:
            self.message.Text = '发布任务仍在后台处理，请等待完成后再关闭。'
        else:
            try:
                self.form.webview.CoreWebView2.ExecuteScriptAsync('window.dispatchEvent(new Event("publisher-close-blocked"));')
            except Exception:
                pass

    def close(self):
        self.closed = True
        self.timer.Stop()
        self.timer.Dispose()
