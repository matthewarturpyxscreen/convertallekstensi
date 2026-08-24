"""
Image to JPG Converter — Streamlit App
=======================================
Convert berbagai format gambar (PNG, BMP, TIFF, WEBP, GIF, ICO, dll)
menjadi JPG dengan kualitas maksimal (tanpa kompresi berlebihan).

Mendukung upload gambar satuan ATAU file arsip (ZIP, RAR, 7Z) — tool akan
otomatis mendeteksi dan mengekstrak semua gambar di dalamnya (termasuk di
dalam sub-folder), lalu mengonversi semuanya sekaligus.

Cara menjalankan:
    pip install -r requirements.txt
    streamlit run image_to_jpg_converter.py

Catatan untuk dukungan RAR:
    Selain `pip install rarfile`, sistem operasi butuh binary `unrar` atau
    `unar` terpasang (mis. `sudo apt install unrar` di Ubuntu/Debian,
    `brew install unar` di macOS). Tanpa ini, ekstraksi RAR tidak akan jalan.
"""

import io
import os
import tempfile
import zipfile
from pathlib import Path

import streamlit as st
from PIL import Image, ImageOps

# ---------------------------------------------------------------------------
# Deteksi library opsional
# ---------------------------------------------------------------------------

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_SUPPORTED = True
except ImportError:
    HEIC_SUPPORTED = False

try:
    import rarfile
    RAR_SUPPORTED = True
except ImportError:
    RAR_SUPPORTED = False

try:
    import py7zr
    SEVENZ_SUPPORTED = True
except ImportError:
    SEVENZ_SUPPORTED = False


IMAGE_EXTENSIONS = {
    ".png", ".bmp", ".tiff", ".tif", ".webp", ".gif", ".ico",
    ".jfif", ".jpg", ".jpeg", ".ppm", ".pgm", ".pbm", ".tga",
}
if HEIC_SUPPORTED:
    IMAGE_EXTENSIONS |= {".heic", ".heif"}

ARCHIVE_EXTENSIONS = {".zip"}
if RAR_SUPPORTED:
    ARCHIVE_EXTENSIONS.add(".rar")
if SEVENZ_SUPPORTED:
    ARCHIVE_EXTENSIONS.add(".7z")


def is_image(filename: str) -> bool:
    return Path(filename).suffix.lower() in IMAGE_EXTENSIONS


def is_junk(filename: str) -> bool:
    """Skip file sampah bawaan arsip (macOS metadata, hidden files, dsb)."""
    name = Path(filename).name
    return "__MACOSX" in filename or name.startswith(".")


# ---------------------------------------------------------------------------
# Ekstraksi gambar dari arsip
# ---------------------------------------------------------------------------

def extract_from_zip(file_bytes: bytes):
    """-> list of (relative_path, raw_bytes)"""
    found = []
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir() or is_junk(info.filename):
                continue
            if is_image(info.filename):
                found.append((info.filename, zf.read(info.filename)))
    return found


def extract_from_rar(file_bytes: bytes):
    found = []
    with tempfile.NamedTemporaryFile(suffix=".rar", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        with rarfile.RarFile(tmp_path) as rf:
            for info in rf.infolist():
                if info.is_dir() or is_junk(info.filename):
                    continue
                if is_image(info.filename):
                    found.append((info.filename, rf.read(info.filename)))
    finally:
        os.unlink(tmp_path)
    return found


def extract_from_7z(file_bytes: bytes):
    found = []
    with tempfile.NamedTemporaryFile(suffix=".7z", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    extract_dir = tempfile.mkdtemp()
    try:
        with py7zr.SevenZipFile(tmp_path, mode="r") as zf:
            names = zf.getnames()
            wanted = [n for n in names if is_image(n) and not is_junk(n)]
            if wanted:
                zf.extract(path=extract_dir, targets=wanted)
        for name in wanted:
            extracted_path = os.path.join(extract_dir, name)
            if os.path.isfile(extracted_path):
                with open(extracted_path, "rb") as f:
                    found.append((name, f.read()))
    finally:
        os.unlink(tmp_path)
        import shutil
        shutil.rmtree(extract_dir, ignore_errors=True)
    return found


def extract_images_from_archive(file_bytes: bytes, filename: str):
    """Dispatch ke extractor yang sesuai berdasarkan ekstensi arsip."""
    ext = Path(filename).suffix.lower()
    if ext == ".zip":
        return extract_from_zip(file_bytes)
    elif ext == ".rar":
        return extract_from_rar(file_bytes)
    elif ext == ".7z":
        return extract_from_7z(file_bytes)
    return []


# ---------------------------------------------------------------------------
# Konversi gambar -> JPG kualitas tinggi
# ---------------------------------------------------------------------------

def convert_to_jpg(file_bytes: bytes, quality: int, subsampling: int) -> bytes:
    img = Image.open(io.BytesIO(file_bytes))

    # Perbaiki orientasi berdasarkan metadata EXIF (foto dari kamera/HP)
    img = ImageOps.exif_transpose(img)

    # JPG tidak mendukung transparansi -> flatten ke background putih
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    output = io.BytesIO()
    img.save(
        output,
        format="JPEG",
        quality=quality,
        subsampling=subsampling,
        optimize=True,
    )
    output.seek(0)
    return output.getvalue()


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Image → JPG Converter", page_icon="🖼️", layout="centered")

st.title("🖼️ Konversi Gambar ke JPG (Kualitas Tinggi)")
st.write(
    "Upload gambar satuan (PNG, BMP, TIFF, WEBP, GIF, ICO"
    + (", HEIC/HEIF" if HEIC_SUPPORTED else "")
    + ") **atau** upload file arsip (ZIP"
    + (", RAR" if RAR_SUPPORTED else "")
    + (", 7Z" if SEVENZ_SUPPORTED else "")
    + ") — semua gambar di dalamnya (termasuk di sub-folder) akan otomatis "
    "terdeteksi dan dikonversi ke JPG."
)

missing_notes = []
if not HEIC_SUPPORTED:
    missing_notes.append("`pip install pillow-heif` → dukungan file **HEIC/HEIF** (foto iPhone)")
if not RAR_SUPPORTED:
    missing_notes.append("`pip install rarfile` + binary `unrar`/`unar` di sistem → dukungan arsip **RAR**")
if not SEVENZ_SUPPORTED:
    missing_notes.append("`pip install py7zr` → dukungan arsip **7Z**")

if missing_notes:
    with st.expander("💡 Fitur tambahan yang bisa diaktifkan"):
        for note in missing_notes:
            st.markdown(f"- {note}")

with st.sidebar:
    st.header("⚙️ Pengaturan Kualitas")
    quality = st.slider(
        "Kualitas JPG",
        min_value=85,
        max_value=100,
        value=100,
        help="100 = kualitas terbaik (mendekati lossless), ukuran file lebih besar.",
    )
    subsampling = st.selectbox(
        "Chroma Subsampling",
        options=[("Tanpa subsampling (kualitas terbaik)", 0), ("4:2:2", 1), ("4:2:0 (default JPG)", 2)],
        format_func=lambda x: x[0],
        index=0,
        help="Pilih 'Tanpa subsampling' untuk hasil paling mendekati gambar asli.",
    )[1]
    st.caption("Rekomendasi default: Quality 100, No Subsampling → hasil JPG mendekati lossless.")

upload_types = (
    ["png", "bmp", "tiff", "tif", "webp", "gif", "ico", "jfif", "jpg", "jpeg", "ppm", "pgm", "pbm", "tga"]
    + (["heic", "heif"] if HEIC_SUPPORTED else [])
    + list(ext.lstrip(".") for ext in ARCHIVE_EXTENSIONS)
)

uploaded_files = st.file_uploader(
    "Pilih gambar satuan, atau upload file arsip (ZIP/RAR/7Z) berisi banyak gambar",
    type=upload_types,
    accept_multiple_files=True,
)

if uploaded_files:
    # Kumpulkan semua sumber gambar: (relative_path_no_ext, raw_bytes, asal_file)
    image_sources = []
    archive_count = 0

    with st.spinner("Memindai file yang diupload..."):
        for uf in uploaded_files:
            ext = Path(uf.name).suffix.lower()
            if ext in ARCHIVE_EXTENSIONS:
                archive_count += 1
                archive_root = Path(uf.name).stem
                try:
                    found = extract_images_from_archive(uf.getvalue(), uf.name)
                    if not found:
                        st.warning(f"⚠️ Tidak ada gambar yang ditemukan di dalam **{uf.name}**.")
                    for inner_path, raw in found:
                        rel_path = str(Path(archive_root) / Path(inner_path).with_suffix(""))
                        image_sources.append((rel_path, raw, uf.name))
                except zipfile.BadZipFile:
                    st.error(f"❌ **{uf.name}** bukan file ZIP yang valid / rusak.")
                except Exception as e:
                    err_text = str(e)
                    if RAR_SUPPORTED and ("Cannot find working tool" in err_text or "RarCannotExec" in type(e).__name__):
                        st.error(
                            f"❌ Gagal membuka **{uf.name}**: program `unrar`/`unar` tidak ditemukan di sistem.\n\n"
                            "Library Python `rarfile` sudah terpasang, tapi proses ekstraksi RAR "
                            "sebenarnya butuh program eksternal. Install salah satu:\n"
                            "- **Windows**: download UnRAR dari rarlab.com/rar_add.htm, taruh `unrar.exe` "
                            "di folder yang sama dengan script ini atau tambahkan ke PATH\n"
                            "- **macOS**: `brew install unar`\n"
                            "- **Linux**: `sudo apt install unrar`\n\n"
                            "Lalu restart aplikasi ini."
                        )
                    else:
                        st.error(f"❌ Gagal membuka **{uf.name}**: {err_text}")
            elif is_image(uf.name):
                rel_path = str(Path(uf.name).with_suffix(""))
                image_sources.append((rel_path, uf.getvalue(), uf.name))
            else:
                st.warning(f"⚠️ **{uf.name}** dilewati — format tidak dikenali.")

    if archive_count:
        st.caption(f"🔍 {archive_count} file arsip dipindai, ditemukan {len(image_sources)} gambar total.")

    if image_sources:
        st.subheader(f"📂 {len(image_sources)} gambar siap dikonversi")

        results = []  # list of (path_with_folder.jpg, jpg_bytes)
        errors = []

        progress = st.progress(0, text="Memproses gambar...")

        for i, (rel_path, raw_bytes, source_name) in enumerate(image_sources):
            try:
                jpg_bytes = convert_to_jpg(raw_bytes, quality, subsampling)
                new_name = rel_path + ".jpg"
                results.append((new_name, jpg_bytes))
            except Exception as e:
                errors.append((f"{source_name} → {rel_path}", str(e)))
            progress.progress((i + 1) / len(image_sources), text=f"Memproses {rel_path}...")

        progress.empty()

        if errors:
            with st.expander(f"⚠️ {len(errors)} file gagal dikonversi"):
                for name, err in errors:
                    st.write(f"- **{name}**: {err}")

        if results:
            st.success(f"✅ {len(results)} gambar berhasil dikonversi ke JPG!")

            for idx, (new_name, jpg_bytes) in enumerate(results):
                flat_name = Path(new_name).name  # nama file saja, untuk download tunggal
                col1, col2 = st.columns([1, 2])
                with col1:
                    st.image(jpg_bytes, caption=new_name, use_container_width=True)
                with col2:
                    size_kb = len(jpg_bytes) / 1024
                    st.write(f"**{new_name}**")
                    st.write(f"Ukuran: {size_kb:.1f} KB")
                    st.download_button(
                        label="⬇️ Download JPG",
                        data=jpg_bytes,
                        file_name=flat_name,
                        mime="image/jpeg",
                        key=f"dl_{idx}_{new_name}",
                    )
                st.divider()

            if len(results) > 1:
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                    for new_name, jpg_bytes in results:
                        zf.writestr(new_name, jpg_bytes)
                zip_buffer.seek(0)

                st.download_button(
                    label=f"⬇️ Download Semua ({len(results)} file) sebagai ZIP",
                    data=zip_buffer,
                    file_name="converted_images.zip",
                    mime="application/zip",
                    type="primary",
                )
else:
    st.info("Silakan upload gambar atau file arsip (ZIP/RAR/7Z) untuk mulai konversi.")
