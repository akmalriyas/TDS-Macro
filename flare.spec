# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Collect all winrt, pynput, and tds_macro submodules
hidden_imports = []
hidden_imports += collect_submodules('winrt')
hidden_imports += collect_submodules('pynput')
hidden_imports += collect_submodules('tds_macro')
hidden_imports += [
    'winocr',
    'webview.platforms.edgechromium',
    'clr_loader',
    'pythonnet',
    'win32gui',
    'win32con',
    'win32process',
    'win32api',
]

# Assets & Web UI data files
added_files = [
    ('tds_macro/ui/web', 'tds_macro/ui/web'),
    ('tds_macro/assets', 'tds_macro/assets'),
]

# Add webview hook data
added_files += collect_data_files('webview')

a = Analysis(
    ['run_flare.py'],
    pathex=['.'],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
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
