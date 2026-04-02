# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Cat Sentry Pro.
Usage: pyinstaller build.spec
"""

import os
import sys
from pathlib import Path

block_cipher = None

# Paths
HERE = os.path.abspath(os.path.dirname(SPEC))

a = Analysis(
    [os.path.join(HERE, 'cat_sentry_pro.py')],
    pathex=[HERE],
    binaries=[],
    datas=[
        (os.path.join(HERE, 'index.html'), '.'),
        (os.path.join(HERE, 'config.json.example'), '.'),
        (os.path.join(HERE, 'yolov8m.pt'), '.'),
    ],
    hiddenimports=[
        'ultralytics',
        'torch',
        'cv2',
        'numpy',
        'requests',
        'PIL',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'tkinter',
        'IPython',
        'jupyter',
        'notebook',
    ],
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
    name='cat_sentry_pro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # Show console for log output
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='cat_sentry_pro',
)
