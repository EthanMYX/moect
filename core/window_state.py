"""Physical-pixel window placement, with monitor/DPI recovery and native mask."""
DEFAULT_SIZE=(1080,800)
MIN_SIZE=(1000,680)


def rect_valid(value):
    return isinstance(value,dict) and all(type(value.get(k)) is int for k in ('x','y','width','height')) and \
        abs(value['x'])<=100000 and abs(value['y'])<=100000 and 0<value['width']<=32768 and 0<value['height']<=32768


def restore_placement(saved,screens):
    """Fit to the current work area, including removed/negative-origin screens."""
    if not rect_valid(saved) or not screens:return None
    def overlap(screen):
        return max(0,min(saved['x']+saved['width'],screen['x']+screen['width'])-max(saved['x'],screen['x']))* \
            max(0,min(saved['y']+saved['height'],screen['y']+screen['height'])-max(saved['y'],screen['y']))
    target=next((s for s in screens if s['name']==saved.get('monitor')),None)
    if target is None:
        target=max(screens,key=overlap)
        if not overlap(target):target=next((s for s in screens if s.get('primary')),screens[0])
    old_dpi=saved.get('dpi',96)
    if type(old_dpi) is not int or not 48<=old_dpi<=768:old_dpi=96
    ratio=target['dpi']/old_dpi
    width=min(target['width'],max(round(MIN_SIZE[0]*target['dpi']/96),round(saved['width']*ratio)))
    height=min(target['height'],max(round(MIN_SIZE[1]*target['dpi']/96),round(saved['height']*ratio)))
    origin=saved.get('work_area')
    if saved.get('monitor')==target['name'] and rect_valid(origin):
        x=target['x']+round((saved['x']-origin['x'])*ratio)
        y=target['y']+round((saved['y']-origin['y'])*ratio)
    elif overlap(target):x,y=saved['x'],saved['y']
    else:x,y=target['x']+(target['width']-width)//2,target['y']+(target['height']-height)//2
    return dict(x=max(target['x'],min(x,target['x']+target['width']-width)),
                y=max(target['y'],min(y,target['y']+target['height']-height)),width=width,height=height,
                maximized=saved.get('maximized') is True,dpi=target['dpi'])


def frame_color(background,masked=False,dark=False):
    if not masked:return background
    opacity=.5 if dark else .25
    return '#'+''.join(f'{round(int(background[i:i+2],16)*(1-opacity)):02x}' for i in (1,3,5))


class WindowPlacement:
    """Runs on the WinForms UI thread; persist only normal bounds, never minimized."""
    def __init__(self,form,service,frame):
        from System.Drawing import Point,Size
        from System.Windows.Forms import Screen,FormStartPosition,FormWindowState,Timer
        import ctypes
        import ctypes.wintypes as wt
        self.form=form;self.service=service;self.frame=frame;self.ready=False;self.normal=None
        def area(screen):
            r=screen.WorkingArea
            return dict(x=r.X,y=r.Y,width=r.Width,height=r.Height)
        def dpi_of(screen):
            try:
                user=ctypes.windll.user32
                user.MonitorFromPoint.argtypes=[wt.POINT,wt.DWORD];user.MonitorFromPoint.restype=wt.HANDLE
                r=screen.Bounds;monitor=user.MonitorFromPoint(wt.POINT(r.X+1,r.Y+1),2)
                query=ctypes.windll.shcore.GetDpiForMonitor
                query.argtypes=[wt.HANDLE,ctypes.c_int,ctypes.POINTER(wt.UINT),ctypes.POINTER(wt.UINT)]
                x=wt.UINT();y=wt.UINT()
                if query(monitor,0,ctypes.byref(x),ctypes.byref(y))==0:return x.value
            except (OSError,AttributeError):pass
            return round(frame.devicePixelRatioF()*96)
        self.area=area
        screens=[dict(name=s.DeviceName,primary=s.Primary,dpi=dpi_of(s),**area(s)) for s in Screen.AllScreens]
        saved=restore_placement(service.config.get('window_placement'),screens)
        if not saved and screens:
            screen=next((s for s in screens if s['primary']),screens[0]);dpi=screen['dpi']
            width=min(screen['width'],round(DEFAULT_SIZE[0]*dpi/96));height=min(screen['height'],round(DEFAULT_SIZE[1]*dpi/96))
            saved=dict(x=screen['x']+(screen['width']-width)//2,y=screen['y']+(screen['height']-height)//2,
                       width=width,height=height,dpi=dpi,maximized=False)
        if saved:
            form.StartPosition=FormStartPosition.Manual
            form.Location=Point(saved['x'],saved['y'])
            work=Screen.FromPoint(form.Location).WorkingArea
            form.MinimumSize=Size(min(work.Width,round(MIN_SIZE[0]*saved['dpi']/96)),min(work.Height,round(MIN_SIZE[1]*saved['dpi']/96)))
            form.Size=Size(saved['width'],saved['height'])
            self.normal=form.Bounds
            if saved['maximized']:form.WindowState=FormWindowState.Maximized
        self.timer=Timer();self.timer.Interval=600
        def save(*_):
            self.timer.Stop()
            if not self.ready or form.WindowState==FormWindowState.Minimized:return
            bounds=form.Bounds if form.WindowState==FormWindowState.Normal else form.RestoreBounds
            if bounds.Width<=0 or bounds.Height<=0:bounds=self.normal
            if bounds is None:return
            self.normal=bounds;screen=Screen.FromRectangle(bounds)
            state=dict(x=bounds.X,y=bounds.Y,width=bounds.Width,height=bounds.Height,
                dpi=round(frame.devicePixelRatioF()*96),monitor=screen.DeviceName,work_area=area(screen),
                maximized=form.WindowState==FormWindowState.Maximized)
            try:
                with service.lock:service.config['window_placement']=state;service.save()
            except OSError:pass # Never let a storage error escape a native event callback.
        def changed(*_):
            if self.ready and form.WindowState!=FormWindowState.Minimized:self.timer.Stop();self.timer.Start()
        def shown(*_):self.ready=True;changed()
        def closing(_sender,event):
            if not event.Cancel:save()
        def closed(*_):self.timer.Stop();self.timer.Dispose()
        self.handlers=(save,changed,shown,closing,closed)
        self.timer.Tick+=save;form.Move+=changed;form.Resize+=changed;form.ResizeEnd+=save
        form.Shown+=shown;form.FormClosing+=closing;form.FormClosed+=closed
