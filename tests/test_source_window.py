import os
import unittest
from guardian.source_window import SourceWindows,Win32

class Fake:
    def __init__(self):
        self.rows={10:dict(pid=10,parent=20,created=300,name='python.exe'),20:dict(pid=20,parent=30,created=200,name='claude.exe'),30:dict(pid=30,parent=0,created=100,name='windowsterminal.exe')}
        self.visible=[(42,30)];self.active=0;self.calls=[];self.allow=True
    def process(self,pid):return self.rows.get(pid)
    def windows(self):return self.visible
    def activate(self,hwnd):
        self.calls.append(hwnd)
        if self.allow:self.active=hwnd
    def foreground(self):return self.active

class SourceWindowTests(unittest.TestCase):
    def console_api(self):
        api=Fake()
        api.rows[20]['parent']=0  # Terminal UI is not an ancestor of the CLI.
        api.rows[40]=dict(pid=40,parent=30,created=150,name='openconsole.exe')
        api.visible=[(42,30),(43,30)]  # Two windows owned by one terminal process.
        api.source_console=lambda pid:99 if pid==10 else None
        api.console_target=lambda hwnd:(43,40) if hwnd==99 else None
        return api

    def test_console_association_selects_exact_nonancestor_window(self):
        api=self.console_api();windows=SourceWindows(api)
        target=windows.capture(10)
        self.assertEqual(target['hwnd'],43)
        self.assertEqual(api.calls,[])
        self.assertTrue(windows.activate(target)['window_foreground_verified'])
        self.assertEqual(api.calls,[43])

    def test_changed_console_owner_or_reused_console_process_never_activates(self):
        for change in ('owner','reuse','closed'):
            api=self.console_api();windows=SourceWindows(api);target=windows.capture(10)
            if change=='owner':api.console_target=lambda hwnd:(42,40)
            if change=='reuse':api.rows[40]['created']=999
            if change=='closed':api.visible=[(42,30)]
            self.assertFalse(windows.activate(target)['window_foreground_verified'])
            self.assertEqual(api.calls,[])

    def test_console_hint_cannot_activate_arbitrary_nonterminal_application(self):
        api=self.console_api();api.rows[30]['name']='unrelated.exe'
        self.assertIsNone(SourceWindows(api).capture(10));self.assertEqual(api.calls,[])

    def test_client_owned_console_requires_actual_console_class(self):
        api=self.console_api();api.rows[30]['name']='python.exe';api.rows[40]['name']='python.exe'
        api.class_name=lambda hwnd:'ConsoleWindowClass'
        windows=SourceWindows(api);target=windows.capture(10)
        self.assertTrue(windows.activate(target)['window_foreground_verified'])
        api.calls.clear();api.class_name=lambda hwnd:'UnrelatedWindow'
        self.assertFalse(windows.activate(target)['window_foreground_verified'])
        self.assertIsNone(windows.capture(10));self.assertEqual(api.calls,[])

    def test_capture_only_records_one_ancestor_terminal_and_never_activates(self):
        api=Fake();windows=SourceWindows(api)
        target=windows.capture(10)
        self.assertEqual(target,{'pid':30,'created':100,'hwnd':42});self.assertEqual(api.calls,[])
        self.assertTrue(windows.activate(target)['window_foreground_verified']);self.assertEqual(api.calls,[42])
    def test_ambiguity_invalid_pid_and_reused_parent_fail_closed(self):
        api=Fake();windows=SourceWindows(api)
        for pid in (True,'10',-1,2**32):self.assertIsNone(windows.capture(pid))
        api.visible.append((43,30));self.assertIsNone(windows.capture(10))
        api.visible=[(42,30)];api.rows[30]['created']=400
        self.assertIsNone(windows.capture(10));self.assertEqual(api.calls,[])
    def test_stale_pid_closed_or_ambiguous_window_never_activates(self):
        for change in ('reuse','closed','multiple','image'):
            api=Fake();windows=SourceWindows(api);target=windows.capture(10)
            if change=='reuse':api.rows[30]['created']=999
            elif change=='closed':api.visible=[]
            elif change=='multiple':api.visible.append((43,30))
            else:api.rows[30]['name']='unrelated.exe'
            self.assertFalse(windows.activate(target)['window_foreground_verified']);self.assertEqual(api.calls,[])
    def test_os_refusal_is_not_reported_as_foreground(self):
        api=Fake();api.allow=False;windows=SourceWindows(api)
        self.assertEqual(windows.activate(windows.capture(10))['window_reason'],'os_not_confirmed')
    @unittest.skipUnless(os.name=='nt','Windows native process query')
    def test_native_query_matches_own_process_without_activating_any_window(self):
        result=Win32().process(os.getpid())
        self.assertIsNotNone(result)
        self.assertEqual(result['pid'],os.getpid());self.assertEqual(result['parent'],os.getppid())
        self.assertGreater(result['created'],0);self.assertIn(result['name'],('python.exe','pythonw.exe'))

if __name__=='__main__':unittest.main()
