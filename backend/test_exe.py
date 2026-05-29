import sys
from pathlib import Path
import subprocess

print("sys.executable:", sys.executable)
mineru_exe = str(Path(sys.executable).parent / "mineru.exe")
print("mineru_exe:", mineru_exe)
print("exists:", Path(mineru_exe).exists())

try:
    subprocess.run([mineru_exe, "--help"], capture_output=True, text=True, check=True)
    print("subprocess.run successful")
except Exception as e:
    print("subprocess.run failed:", repr(e))
