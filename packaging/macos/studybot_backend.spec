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

# pypdfium2 ships the native PDFium library in pypdfium2_raw.
pdfium_datas, pdfium_binaries, pdfium_imports = collect_all("pypdfium2")
raw_datas, raw_binaries, raw_imports = collect_all("pypdfium2_raw")

analysis = Analysis(
    [str(here / "backend_entry.py")],
    binaries=pdfium_binaries + raw_binaries,
    datas=pdfium_datas + raw_datas,
    hiddenimports=hidden_imports + pdfium_imports + raw_imports,
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
