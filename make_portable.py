import zipfile, os, pathlib, sys

src = pathlib.Path(r"C:\Users\emira\desktop\Hearth\dist\Hearth")
out = pathlib.Path(r"C:\Users\emira\desktop\Hearth\dist\Hearth-0.4.3-Portable.zip")

if out.exists():
    out.unlink()

(src / "portable.dat").write_text("PORTABLE")

with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    for f in src.rglob("*"):
        if f.is_file():
            zf.write(f, f.relative_to(src))

size_mb = out.stat().st_size / 1024 / 1024
print(f"Created: {out}")
print(f"Size: {size_mb:.1f} MB")
