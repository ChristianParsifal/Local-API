import argparse
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def dpapi(data, encrypt=True):
    if os.name != 'nt':
        raise RuntimeError('Credential persistence requires Windows DPAPI')
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, output = Blob(len(data), buffer), Blob()
    crypt = ctypes.windll.crypt32
    if encrypt:
        ok = crypt.CryptProtectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output))
    else:
        ok = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))


class API:
    def __init__(self, directory):
        from backend.core import Monitor
        from backend.gateway import Gateway
        self.monitor=Monitor(directory,dpapi,lambda data:dpapi(data,False))
        self.gateway=Gateway(self.monitor)

    def call(self, action, payload=None):
        try:
            p=payload or {}
            if action=='start_gateway':data=self.gateway.start()
            elif action=='stop_gateway':data=self.gateway.stop()
            else:
                if action=='save_settings' and 'autostart' in p:self.autostart(bool(p['autostart']))
                data=self.monitor.action(action,p)
            return {'ok':True,'data':data,'error':None}
        except Exception as exc:return {'ok':False,'data':None,'error':str(exc)}

    def autostart(self,enabled):
        import winreg
        command='"'+sys.executable+'"'
        if not getattr(sys,'frozen',False):command+=' "'+str(Path(__file__).resolve())+'"'
        command+=' --minimized'
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            if enabled:winreg.SetValueEx(key,'AntaresGateway',0,winreg.REG_SZ,command)
            else:
                try:winreg.DeleteValue(key,'AntaresGateway')
                except FileNotFoundError:pass


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--headless',action='store_true');parser.add_argument('--minimized',action='store_true')
    parser.add_argument('--port',type=int);parser.add_argument('--data-dir',default=str(Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'AntaresGateway'))
    parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    if args.self_test:
        import unittest
        test_dir=Path(__file__).parent/'tests'
        if not test_dir.is_dir():raise RuntimeError('Self tests require source distribution tests directory')
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(str(test_dir),pattern='test_backend*.py'))
        return 0 if result.wasSuccessful() else 1
    mutex=None
    if os.name=='nt':
        import hashlib
        kernel=ctypes.windll.kernel32
        kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
        kernel.CreateMutexW.restype=wintypes.HANDLE
        mutex=kernel.CreateMutexW(None,False,'Local\\AntaresGateway-'+hashlib.sha256(str(Path(args.data_dir).resolve()).lower().encode()).hexdigest())
        if kernel.GetLastError()==183:
            if not args.headless:ctypes.windll.user32.MessageBoxW(None,'Antares 已在运行，请从系统托盘打开面板。','Antares',0)
            return 1
    api=API(args.data_dir)
    if args.port:
        result=api.call('save_settings',{'port':args.port})
        if not result['ok']:raise RuntimeError(result['error'])
    status=api.gateway.start()
    if not status['running']:raise RuntimeError(status['error'] or 'Gateway failed to start')
    if args.headless:
        import time
        try:
            while api.gateway.thread.is_alive():time.sleep(.5)
        except KeyboardInterrupt:pass
        finally:api.gateway.stop()
        return 0
    import webview
    import pystray
    from PIL import Image, ImageDraw
    import threading
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
    window=webview.create_window('Antares API Monitor',(root/'index.html').as_uri(),js_api=api,width=1440,height=920,min_size=(900,650),hidden=args.minimized)
    exiting=threading.Event()
    def show(*_):window.show();window.restore()
    def quit_app(*_):
        exiting.set();icon.stop();api.gateway.stop();window.destroy()
    def closing():
        if not exiting.is_set() and api.monitor.settings['close_to_tray']:
            window.hide();return False
        exiting.set();icon.stop();api.gateway.stop();return True
    window.events.closing+=closing
    image=Image.new('RGB',(64,64),'#1387c0');ImageDraw.Draw(image).text((20,18),'A',fill='white')
    icon=pystray.Icon('AntaresGateway',image,'Antares API Monitor',menu=pystray.Menu(pystray.MenuItem('打开面板',show,default=True),pystray.MenuItem('退出',quit_app)))
    threading.Thread(target=icon.run,daemon=True).start()
    try:webview.start(private_mode=True,debug=False)
    finally:exiting.set();icon.stop();api.gateway.stop()
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception:
        import traceback
        detail=traceback.format_exc()
        directory=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'AntaresGateway'
        directory.mkdir(parents=True,exist_ok=True)
        (directory/'startup-error.log').write_text(detail,encoding='utf-8')
        if os.name=='nt' and not sys.stderr:
            ctypes.windll.user32.MessageBoxW(None,'启动失败，详情见 '+str(directory/'startup-error.log'),'Antares',16)
        else:print(detail,file=sys.stderr)
        raise SystemExit(1)

