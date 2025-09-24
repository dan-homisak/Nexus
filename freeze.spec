# PyInstaller spec to bundle Nexus
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.building.build_main import COLLECT, EXE, PYZ, Analysis
from PyInstaller.building.datastruct import Tree

hidden = collect_submodules('uvicorn') + collect_submodules('pydantic')

a = Analysis(
    ['run_app.py'],  # this file opens the browser and runs uvicorn
    pathex=[],
    binaries=[],
    datas=[
        Tree('frontend', prefix='frontend'),  # include UI
        ('requirements.txt', 'requirements.txt'),
    ],
    hiddenimports=hidden,
    noarchive=False,
)

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='nexus',
    console=True,            # set False if you want no console window
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name='nexus')
