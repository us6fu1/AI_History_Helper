# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_dynamic_libs


llama_cpp_binaries = collect_dynamic_libs('llama_cpp')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=llama_cpp_binaries,
    datas=[
        ('assets', 'assets'),
        ('data\\models.json', 'data'),
        ('data\\textbooks.json', 'data'),
        ('..\\Materials', 'Materials'),
    ],
    hiddenimports=['PySide6.QtSvg', 'llama_cpp.llama_speculative'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ИИ-помощник учителя',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\app.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ИИ-помощник учителя',
)
