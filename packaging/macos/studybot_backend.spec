# PyInstaller spec for the bundled StudyBot engine (one-folder build).
# Build with scripts/build_macos_app.sh; see packaging/macos/README.md.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

here = Path(SPECPATH)

# uvicorn and websockets pick protocol/lifespan implementations by name at runtime.
hidden_imports = (
    collect_submodules("studybot")
    + collect_submodules("uvicorn")
    + collect_submodules("websockets")
)

# PyMuPDF ships its native MuPDF libraries as data files next to the Python package.
mupdf_datas, mupdf_binaries, mupdf_imports = collect_all("pymupdf")

analysis = Analysis(
    [str(here / "backend_entry.py")],
    binaries=mupdf_binaries,
    datas=mupdf_datas,
    hiddenimports=hidden_imports + mupdf_imports,
    excludes=["tkinter", "pytest", "pip", "setuptools", "pyinstaller", "PyInstaller"],
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="studybot-backend",
    console=True,
)
COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    name="studybot_backend",
)
