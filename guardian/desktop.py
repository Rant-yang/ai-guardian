"""Small native WebView2 companion. No shell or filesystem methods exposed to JS."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import threading
import time
import urllib.request
from urllib.parse import urlencode

ROOT=Path(__file__).resolve().parent.parent
ORIGIN='http://127.0.0.1:8765'


def recover_position(bounds,workareas):
    """Keep the top controls reachable, including after monitor removal."""
    x,y,width,height=bounds
    areas=[area for area in workareas if area[2]>0 and area[3]>0]
    if not areas or width<=0 or height<=0:return None
    for left,top,w,h in areas:
        visible_w=min(x+width,left+w)-max(x,left)
        # A visible lower corner is insufficient when the top controls are lost.
        visible_h=min(y+min(48,height),top+h)-max(y,top)
        if visible_w>=min(48,width,w) and visible_h>=min(48,height,h):return None
    candidates=[(min(max(x,left),left+max(0,w-width)),
                 min(max(y,top),top+max(0,h-height))) for left,top,w,h in areas]
    return min(candidates,key=lambda p:(p[0]-x)**2+(p[1]-y)**2)


def install_screen_recovery(form):
    """Own-form UI-thread timer; no focus changes, desktop capture or foreign windows."""
    from System.Drawing import Point
    from System.Windows.Forms import Control,MouseButtons,Screen,Timer,FormWindowState
    timer=Timer();timer.Interval=2000
    def tick(sender,event):
        if form.IsDisposed or not form.Visible or form.WindowState==FormWindowState.Minimized:return
        if Control.MouseButtons!=getattr(MouseButtons,'None'):return
        areas=[(s.WorkingArea.X,s.WorkingArea.Y,s.WorkingArea.Width,s.WorkingArea.Height) for s in Screen.AllScreens]
        target=recover_position((form.Left,form.Top,form.Width,form.Height),areas)
        if target is not None:form.Location=Point(*target)
    def closed(sender,event):timer.Stop();timer.Dispose()
    timer.Tick += tick
    form.FormClosed += closed
    timer.Start()
    return timer


def configure_composition(hwnd):
    """Request alpha composition without a color key or a tinted glass sheet."""
    from ctypes import wintypes
    dwm=ctypes.WinDLL('dwmapi')
    gdi=ctypes.WinDLL('gdi32')
    class Margins(ctypes.Structure):
        _fields_=[(name,ctypes.c_int) for name in ('left','right','top','bottom')]
    class BlurBehind(ctypes.Structure):
        _fields_=[('flags',wintypes.DWORD),('enabled',wintypes.BOOL),
                  ('region',wintypes.HRGN),('transition',wintypes.BOOL)]
    dwm.DwmExtendFrameIntoClientArea.argtypes=[wintypes.HWND,ctypes.POINTER(Margins)]
    dwm.DwmExtendFrameIntoClientArea.restype=ctypes.c_long
    dwm.DwmSetWindowAttribute.argtypes=[wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
    dwm.DwmSetWindowAttribute.restype=ctypes.c_long
    dwm.DwmEnableBlurBehindWindow.argtypes=[wintypes.HWND,ctypes.POINTER(BlurBehind)]
    dwm.DwmEnableBlurBehindWindow.restype=ctypes.c_long
    gdi.CreateRectRgn.argtypes=[ctypes.c_int]*4
    gdi.CreateRectRgn.restype=wintypes.HRGN
    gdi.DeleteObject.argtypes=[wintypes.HANDLE]
    # A full negative-margin glass surface can acquire the system gray tint.
    result=dwm.DwmExtendFrameIntoClientArea(hwnd,ctypes.byref(Margins(0,0,0,0)))
    if result!=0:raise RuntimeError('DWM frame reset failed')
    none=ctypes.c_int(1)  # DWMSBT_NONE (Windows 11); older systems may reject it.
    backdrop=dwm.DwmSetWindowAttribute(hwnd,38,ctypes.byref(none),ctypes.sizeof(none))
    region=gdi.CreateRectRgn(0,0,-1,-1)
    if not region:raise RuntimeError('DWM region creation failed')
    try:
        # Empty blur region enables alpha composition without desktop blur.
        result=dwm.DwmEnableBlurBehindWindow(hwnd,ctypes.byref(BlurBehind(3,True,region,False)))
        if result!=0:raise RuntimeError('DWM alpha composition failed')
    finally:gdi.DeleteObject(region)
    return {'alpha_composition':True,'system_backdrop_disabled':backdrop==0}


def launch_ticket():
    token=(ROOT/'.local/admin-token').read_text(encoding='utf-8').strip()
    request=urllib.request.Request(ORIGIN+'/api/launch-ticket',b'{}',
        {'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request,timeout=5) as response:return json.load(response)['ticket']


class Controls:
    def __init__(self):
        self._console_window=None
        self._console_lock=threading.Lock()

    def alert_visible(self, visible):
        if not isinstance(visible,bool):raise ValueError('Boolean required')
        self._window.resize(360,510 if visible else 330)

    def close(self):
        self._window.destroy()

    def toggle_pin(self):
        self._window.on_top=not self._window.on_top
        return self._window.on_top

    def connection_ticket(self):
        """Reconnect our own refreshed WebView without asking for a long-lived token."""
        return {'ticket':launch_ticket()}

    def prepare_source_navigation(self):
        """Transfer this user-click's foreground permission to our local backend.

        The JS caller cannot choose a PID, URL or command. Windows still decides
        whether the calling Guardian window currently has foreground rights.
        """
        from ctypes import wintypes
        token=(ROOT/'.local/admin-token').read_text(encoding='utf-8').strip()
        request=urllib.request.Request(ORIGIN+'/api/source/prepare',b'{}',
            {'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request,timeout=3) as response:pid=json.load(response).get('foreground_process_id')
        if type(pid) is not int or not 0<pid<2**32:raise ValueError('Invalid Guardian process')
        user=ctypes.WinDLL('user32',use_last_error=True)
        user.AllowSetForegroundWindow.argtypes=[wintypes.DWORD]
        user.AllowSetForegroundWindow.restype=wintypes.BOOL
        return {'foreground_permission_granted':bool(user.AllowSetForegroundWindow(pid))}

    def open_console(self, event_id=None):
        if event_id is not None and (not isinstance(event_id,str) or not 0<len(event_id)<=128
                                    or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in event_id)):
            raise ValueError('Invalid event ID')
        import webview
        with self._console_lock:
            params={'connect':launch_ticket()}
            if event_id:params['event']=event_id
            url=ORIGIN+'/#'+urlencode(params)
            if self._console_window is None:
                target=webview.create_window('Guardian · 事件详情与审批',url,js_api=self,
                    width=1280,height=860,min_size=(960,640),background_color='#09090b')
                self._console_window=target
                def closed():
                    with self._console_lock:
                        if self._console_window is target:self._console_window=None
                target.events.closed += closed
            else:
                target=self._console_window
                target.load_url(url)
                target.restore()
                target.show()
            # WinForms focus must run on its UI thread; cross-thread TopMost can hang.
            from System import Action
            target.native.Invoke(Action(lambda:target.native.Activate()))
            return {'opened':True}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--smoke',action='store_true',help='Launch, report native configuration, and close')
    args=parser.parse_args()
    if os.name!='nt':raise RuntimeError('This launcher requires Windows WebView2')
    # Prevent accidental duplicate always-on-top panels. The mutex is released on exit.
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p]
    kernel.CreateMutexW.restype=ctypes.c_void_p
    mutex=kernel.CreateMutexW(None,False,'Local\\GuardianDesktopOverlay')
    if not mutex:raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error()==183:return
    import webview
    controls=Controls()
    window=webview.create_window('Guardian Desktop',ORIGIN+'/overlay#connect='+launch_ticket(),
        js_api=controls,width=360,height=330,min_size=(320,260),frameless=True,transparent=True,
        background_color='#010203',shadow=False,on_top=True,easy_drag=False,resizable=False)
    controls._window=window
    ready=threading.Event()
    composition_status={}

    def native_setup():
        from System import Action
        from System.Drawing import Color
        def apply():
            form=window.native
            # Keep native hit testing: color keys also discard mouse input.
            form.TransparencyKey=Color.Empty
            form.BackColor=Color.Black
            composition_status.update(configure_composition(form.Handle.ToInt64()))
            form.webview.DefaultBackgroundColor=Color.Transparent
            form.ShowInTaskbar=True
            if not hasattr(controls,'_screen_recovery'):
                controls._screen_recovery=install_screen_recovery(form)
            def guard_navigation(sender,event):
                if str(event.Uri).split('#',1)[0] != ORIGIN+'/overlay':event.Cancel=True
            form.webview.NavigationStarting += guard_navigation
            ready.set()
        window.native.Invoke(Action(apply))

    window.events.loaded += native_setup

    def verify():
        if not ready.wait(20):
            (ROOT/'.local/desktop-status.json').write_text(json.dumps({'loaded':False}),encoding='utf-8')
            if args.smoke:window.destroy()
            return
        # Only inspect this app's own DOM and native properties. No desktop capture.
        for _ in range(30):
            if window.evaluate_js("typeof connected!=='undefined' && connected"):break
            time.sleep(.2)
        if args.smoke:window.evaluate_js("document.body.classList.add('show-overlay-controls')")
        status=window.evaluate_js("""({route:location.pathname,transparent:getComputedStyle(document.body).backgroundColor,
            overlay:document.body.classList.contains('desktop-overlay'),connected,
            viewport:[innerWidth,innerHeight],cards:document.querySelectorAll('.evt').length,
            filters:['filter','source-filter','session-filter'].map(id=>{const r=document.getElementById(id).getBoundingClientRect();return {id,x:r.x,y:r.y,width:r.width};}),
            lastCardBottom:document.querySelector('.evt:last-child')?.getBoundingClientRect().bottom||0})""")
        status.update(loaded=True,frameless=window.frameless,on_top=window.on_top,
                      native_color_key=not window.native.TransparencyKey.IsEmpty,
                      width=window.width,height=window.height)
        status.update(composition_status)
        from System import Action
        from System.Drawing import Point
        if args.smoke:
            window.native.Invoke(Action(lambda:window.native.Activate()))
            status['source_foreground_permission']=controls.prepare_source_navigation()
            # Exercise a real reload without a URL ticket, not just a mocked bridge.
            window.evaluate_js("token='';connected=false")
            window.native.Invoke(Action(lambda:window.native.webview.Reload()))
            deadline=time.monotonic()+15
            restored=False
            while time.monotonic()<deadline:
                try:
                    restored=window.evaluate_js("typeof connected!=='undefined'&&connected&&location.hash===''&&document.getElementById('login').hidden")
                    if restored:break
                except Exception:pass
                time.sleep(.2)
            status['native_refresh_reconnected_without_manual_token']=bool(restored)
            window.evaluate_js("document.body.classList.add('show-overlay-controls')")
        def hit_checks():
            class NativePoint(ctypes.Structure):
                _fields_=[('x',ctypes.c_long),('y',ctypes.c_long)]
            user=ctypes.windll.user32
            user.WindowFromPoint.argtypes=[NativePoint];user.WindowFromPoint.restype=ctypes.c_void_p
            user.GetAncestor.argtypes=[ctypes.c_void_p,ctypes.c_uint];user.GetAncestor.restype=ctypes.c_void_p
            scale=window.native._scale
            points=[('drag',status['viewport'][0]/2,65)]+[(f['id'],f['x']+f['width']/2,f['y']+10) for f in status['filters']]
            status['mouse_hits']={}
            for name,x,y in points:
                point=window.native.PointToScreen(Point(int(x*scale),int(y*scale)))
                target=user.WindowFromPoint(NativePoint(point.X,point.Y))
                status['mouse_hits'][name]=user.GetAncestor(target,2)==window.native.Handle.ToInt64()
        window.native.Invoke(Action(hit_checks))
        if args.smoke:
            original=(window.x,window.y)
            from System import Action
            from System.Drawing import Point
            from System.Windows.Forms import Screen
            def move_outside():
                edge=max(s.WorkingArea.Right for s in Screen.AllScreens)
                window.native.Location=Point(edge+1000,100)
            window.native.Invoke(Action(move_outside))
            time.sleep(2.5)
            recovered=[]
            def check_recovered():
                form=window.native
                areas=[(s.WorkingArea.X,s.WorkingArea.Y,s.WorkingArea.Width,s.WorkingArea.Height) for s in Screen.AllScreens]
                recovered.append(recover_position((form.Left,form.Top,form.Width,form.Height),areas) is None)
            window.native.Invoke(Action(check_recovered))
            status['offscreen_recovery']=bool(recovered and recovered[0])
            window.move(*original)
            window.evaluate_js("document.querySelector('#viz').dispatchEvent(new MouseEvent('mousedown',{bubbles:true,button:0,clientX:20,clientY:20}));")
            window.evaluate_js(f"window.dispatchEvent(new MouseEvent('mousemove',{{screenX:{original[0]+44},screenY:{original[1]+36}}}));")
            time.sleep(.5)
            window.evaluate_js("window.dispatchEvent(new MouseEvent('mouseup'));")
            status['drag_bridge_moved']=(window.x,window.y)!=original
            window.move(*original)
            status['filter_hit_targets']=window.evaluate_js("['filter','source-filter','session-filter'].map(id=>{const el=document.getElementById(id),r=el.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)?.id===id;})")
            window.evaluate_js("document.body.classList.remove('show-overlay-controls')")
            idle_height=window.height
            controls.alert_visible(True)
            time.sleep(.2)
            status['risk_resize_expands']=window.height>idle_height
            controls.alert_visible(False)
            # Exercise the actual page button and bridge using an existing record.
            target_id=window.evaluate_js("events.find(e=>!e.is_demo)?.event_id||null")
            if target_id:
                window.evaluate_js("desktopRisks.splice(0,desktopRisks.length,events.find(e=>!e.is_demo));renderDesktopRisk();document.getElementById('desktop-alert-open').click();")
            else:
                window.evaluate_js("document.getElementById('overlay-console').click();")
            for _ in range(60):
                target=controls._console_window
                if target and target.events.loaded.is_set():
                    try:
                        detail=target.evaluate_js("({connected:typeof connected!=='undefined'&&connected,selected:typeof selected!=='undefined'?selected:null})")
                        if detail and detail['connected'] and (not target_id or detail['selected']==target_id):break
                    except Exception:pass
                time.sleep(.2)
            else:detail={'connected':False,'selected':None}
            status['source_action_bounds']=window.evaluate_js("['desktop-alert-source','desktop-alert-open'].map(id=>{const el=document.getElementById(id),r=el.getBoundingClientRect();return {id,visible:r.width>0&&r.height>0&&r.bottom<=innerHeight,hit:document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)?.id===id};})")
            status['detail_window_connected']=detail['connected']
            status['detail_event_matches']=detail['selected']==target_id if target_id else None
            if controls._console_window and detail['connected']:
                status['replay_controls']=controls._console_window.evaluate_js("""(()=>{
                    const start=document.getElementById('replay-start');const rect=start.getBoundingClientRect();
                    const visible=rect.width>0&&rect.height>0;start.click();
                    const active=!!replay, count=replay?.rows.length||0;
                    const readOnly=['approval-controls','review-controls','source-controls','feedback-controls'].every(id=>!document.getElementById(id).querySelector('button'));
                    document.getElementById('replay-step').click();const stepped=count>1?replay.index===1:true;
                    document.getElementById('replay-exit').click();
                    return {visible,active,count,readOnly,stepped,returnedLive:replay===null};
                })()""")
            if controls._console_window and detail['connected']:
                status['semantic_settings']=controls._console_window.evaluate_js("""(()=>{
                    const panel=document.getElementById('semantic-settings');panel.open=true;
                    const preview=document.getElementById('semantic-preview');preview.scrollIntoView({block:'center'});
                    const r=preview.getBoundingClientRect();
                    return {present:!!panel,previewVisible:r.width>0&&r.height>0,
                        previewHit:document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===preview,
                        selectedClients:panel.querySelectorAll('input:checked').length,
                        status:document.getElementById('semantic-status').textContent};
                })()""")
            if controls._console_window and detail['connected']:
                status['investigation_controls']=controls._console_window.evaluate_js("""(()=>{
                    const button=[...document.querySelectorAll('#investigation-controls button')].find(el=>el.textContent==='查看相关动作证据');
                    if(!button)return {available:false};
                    button.scrollIntoView({block:'center'});const r=button.getBoundingClientRect();
                    const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===button;
                    button.click();return {available:true,hit,scopePresent:!!document.getElementById('review-scope')};
                })()""")
                if status['investigation_controls'].get('available'):
                    for _ in range(15):
                        investigation_status=controls._console_window.evaluate_js("({loaded:!!investigationSnapshot,matched:investigationSnapshot?.anchor_event_id===selected,count:investigationSnapshot?.events.length||0})")
                        if investigation_status.get('loaded'):break
                        time.sleep(.2)
                    status['investigation_controls'].update(investigation_status)
            if controls._console_window and detail['connected']:
                status['connection_verification']=controls._console_window.evaluate_js("""(()=>{
                    const button=[...document.querySelectorAll('#integration-controls button')].find(el=>el.textContent==='验证普通对话接入'&&!el.disabled);
                    if(!button)return {available:false};
                    button.scrollIntoView({block:'center'});const r=button.getBoundingClientRect();
                    const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===button;
                    button.click();return {available:true,hit};
                })()""")
                if status['connection_verification'].get('available'):
                    for _ in range(15):
                        verification_ready=controls._console_window.evaluate_js("document.getElementById('connection-verification').textContent.includes('验证提示词')")
                        if verification_ready:break
                        time.sleep(.2)
                    status['connection_verification']['started']=bool(verification_ready)
            if controls._console_window and detail['connected']:
                status['recording_privacy']=controls._console_window.evaluate_js("""(()=>{
                    const priorMode=privacyMode,priorEvents=events,priorSelected=selected;
                    const fixture={...events[0],event_id:'privacy-fixture',tool_name:'PRIVATE_TOOL_SENTINEL',session_id:'PRIVATE_SESSION_SENTINEL',action_preview:{targets:['PRIVATE_TARGET_SENTINEL']}};
                    events=[fixture];applyPrivacy(true);details(fixture);render();
                    renderSessions([{key:'fixture',adapter:'claude-hook',session_id:'PRIVATE_SESSION_SENTINEL',events:1}]);
                    const columns=[...document.querySelectorAll('.grid>.col')];
                    const result={columnsHidden:columns.length===3&&getComputedStyle(columns[0]).display==='none'&&getComputedStyle(columns[2]).display==='none',
                        visibleTextMasked:!document.body.innerText.includes('PRIVATE_'),
                        rawMasked:document.getElementById('raw').textContent==='录屏隐私：记录已隐藏',
                        noApprovalControls:!document.querySelector('#approval-controls button')};
                    events=priorEvents;selected=priorSelected;applyPrivacy(priorMode);render();
                    return result;
                })()""")
            if controls._console_window and detail['connected']:
                status['task_context_input']=controls._console_window.evaluate_js("""(()=>{
                    const event=events.find(e=>e.event_id===selected);if(!event)return {available:false};
                    renderModelReview(event);
                    const input=document.querySelector('#review-controls textarea');if(!input)return {available:false};
                    input.scrollIntoView({block:'center'});const r=input.getBoundingClientRect();
                    const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===input;
                    input.value='SYNTHETIC_TASK_CONTEXT';input.dispatchEvent(new Event('input'));
                    const result={available:true,hit,draftMatched:reviewTaskDraft==='SYNTHETIC_TASK_CONTEXT',
                        explicitSendLabel:document.querySelector('#review-controls button:last-child')?.textContent.includes('任务说明')};
                    clearReviewTask();renderModelReview(event);result.cleared=reviewTaskDraft==='';return result;
                })()""")
            if controls._console_window:controls._console_window.destroy()
            status['animation']=window.evaluate_js("""({
                debug:document.getElementById('dbg')?.textContent||'',
                canvasWidth:document.getElementById('viz')?.width||0,
                canvasHeight:document.getElementById('viz')?.height||0
            })""")
            (ROOT/'.local/desktop-interaction-test.json').write_text(json.dumps(status),encoding='utf-8')
        (ROOT/'.local/desktop-status.json').write_text(json.dumps(status),encoding='utf-8')
        if args.smoke:
            time.sleep(1)
            window.destroy()
    try:
        webview.start(verify,gui='edgechromium',debug=False,private_mode=True)
    finally:
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        kernel.CloseHandle(mutex)


if __name__=='__main__':main()
