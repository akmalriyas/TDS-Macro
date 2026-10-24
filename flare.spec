# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

extra_binaries = []
extra_datas = [
    ('tds_macro/ui/web', 'tds_macro/ui/web'),
    ('tds_macro/assets', 'tds_macro/assets'),
    ('FlareMacro.exe.config', '.'),
]
extra_hiddenimports = [
    'clr',
    'winocr',
    'webview.platforms.edgechromium',
    'win32gui',
    'win32con',
    'win32process',
    'win32api',
]

extra_hiddenimports += collect_submodules('winrt')
extra_hiddenimports += collect_submodules('tds_macro')

# Collect all binaries, datas, and hidden imports for pythonnet, clr_loader, and webview
for pkg in ['pythonnet', 'clr_loader', 'webview']:
    d, b, h = collect_all(pkg)
    extra_datas.extend(d)
    extra_binaries.extend(b)
    extra_hiddenimports.extend(h)

a = Analysis(
    ['run_flare.py'],
    pathex=['.'],
    binaries=extra_binaries,
    datas=extra_datas,
    hiddenimports=extra_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'unittest', 'pytest', 'IPython', 'jupyter'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FlareMacro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='tds_macro/assets/app_icon.ico',
    version='version_info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='FlareMacro',
)

import shutil
try:
    shutil.copy2('FlareMacro.exe.config', Path('dist') / 'FlareMacro' / 'FlareMacro.exe.config')
except Exception:
    pass
