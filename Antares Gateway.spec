# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules
import ssl
ssl_policy = Path(ssl.__file__).with_name('codex-rejected-cas.pem')
ssl_datas = [(str(ssl_policy), '.')] if ssl_policy.is_file() else []
a = Analysis(['app.py'], pathex=[], binaries=[],
 datas=[('index.html','.'),('antares.css','.'),('antares-logo.png','.')] + ssl_datas,
 hiddenimports=collect_submodules('uvicorn') + collect_submodules('pystray'),
 hookspath=[],hooksconfig={},runtime_hooks=[],excludes=[],noarchive=False,optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,a.binaries,a.datas,[],name='Antares Gateway',debug=False,
 bootloader_ignore_signals=False,strip=False,upx=False,console=False,
 disable_windowed_traceback=False,argv_emulation=False,target_arch=None,
 codesign_identity=None,entitlements_file=None)
