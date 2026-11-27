"""Build dist/SO-Mini-Dashboard.exe with PyInstaller:  pip install pyinstaller  then  python build_exe.py"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
version = re.search(r'__version__ = "([^"]+)"', (ROOT / "stellar_dashboard/__init__.py").read_text()).group(1)
nums = (re.findall(r"\d+", version) + ["0"] * 4)[:4]
build = ROOT / "build"
build.mkdir(exist_ok=True)
info = build / "version_info.txt"
info.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({",".join(nums)}), prodvers=({",".join(nums)})),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('ProductName', 'SO Mini Dashboard'),
    StringStruct('FileDescription', 'SO Mini Dashboard (read-only Stellar Odyssey dashboard)'),
    StringStruct('FileVersion', '{version}'),
    StringStruct('ProductVersion', '{version}'),
    StringStruct('OriginalFilename', 'SO-Mini-Dashboard.exe')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""", encoding="utf-8")
sep = ";" if sys.platform == "win32" else ":"
subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
                "--name", "SO-Mini-Dashboard", "--version-file", str(info),
                "--add-data", f"stellar_dashboard/page.html{sep}stellar_dashboard",
                "--add-data", f"relic_planner/dungeons_panel.html{sep}relic_planner",
                "--hidden-import", "relic_planner.dashboard",
                "launcher.py"], cwd=ROOT, check=True)
print(f"Built dist/SO-Mini-Dashboard.exe (version {version})")
