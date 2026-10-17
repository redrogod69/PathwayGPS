"""Bundle backend/app into frontend/public/py/app.zip for the in-browser (Pyodide) engine."""
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / "frontend" / "public" / "py" / "app.zip"
out.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted((ROOT / "backend" / "app").rglob("*.py")):
        if "__pycache__" not in f.parts and f.name != "main.py":
            z.write(f, f.relative_to(ROOT / "backend"))
print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
