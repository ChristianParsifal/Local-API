"""Verify the frozen executable starts its actual HTTP gateway."""
import argparse
import json
import socket
import subprocess
import sys
import ctypes
import tempfile
import time
from pathlib import Path
import httpx

root=Path(__file__).parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--exe',type=Path,default=root/'dist'/'Antares Gateway.exe')
parser.add_argument('--desktop',action='store_true')
args=parser.parse_args()
exe=args.exe.resolve()
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
directory=tempfile.mkdtemp(prefix='exe-smoke-',dir=str(root))
desktop=args.desktop
proc=subprocess.Popen([str(exe),'--minimized' if desktop else '--headless','--port',str(port),'--data-dir',directory])
report={'exe':str(exe),'port':port}
try:
    for _ in range(120):
        if proc.poll() is not None:raise RuntimeError('Executable exited: '+str(proc.returncode))
        try:
            response=httpx.get(f'http://127.0.0.1:{port}/v1/models',timeout=.5)
            if response.status_code==401:
                report['http_status']=401;report['ok']=True;break
        except httpx.HTTPError:pass
        time.sleep(.25)
    else:raise RuntimeError('Gateway startup timed out')
    report['database_created']=(Path(directory)/'monitor.sqlite3').exists()
    if desktop:
        titles=[]
        callback_type=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
        @callback_type
        def collect(hwnd,param):
            text=ctypes.create_unicode_buffer(512)
            ctypes.windll.user32.GetWindowTextW(hwnd,text,512)
            if text.value=='Antares API Monitor':titles.append(text.value)
            return True
        for _ in range(60):
            ctypes.windll.user32.EnumWindows(collect,0)
            if titles:break
            time.sleep(.25)
        report['desktop_window_found']=bool(titles)
        report['ok']=report['ok'] and bool(titles)
except Exception as exc:
    report.update(ok=False,error=repr(exc))
finally:
    subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],check=False)
    try:proc.wait(timeout=10)
    except subprocess.TimeoutExpired:proc.kill();proc.wait()
    (root/'exe-smoke-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
raise SystemExit(0 if report.get('ok') and report.get('database_created') else 1)
