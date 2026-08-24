"""
Image to JPG Converter — Streamlit App
=======================================
Convert berbagai format gambar (PNG, BMP, TIFF, WEBP, GIF, JFIF, ICO, dll)
menjadi JPG dengan kualitas maksimal (tanpa kompresi berlebihan).

Mendukung upload gambar satuan ATAU file arsip (ZIP, RAR, 7Z) — tool akan
otomatis mengekstrak semua gambar di dalamnya (termasuk di sub-folder
bertingkat), lalu mengonversi semuanya sekaligus.

Deteksi gambar TIDAK hanya berdasarkan ekstensi file — tool juga membaca
isi (konten) file untuk memastikan itu benar-benar gambar, jadi file dengan
ekstensi salah/aneh tetap terdeteksi dan ikut dikonversi.

Cara menjalankan:
    pip install -r requirements.txt
    streamlit run image_to_jpg_converter.py

Catatan untuk dukungan RAR:
    Butuh salah satu program eksternal terpasang di sistem: `unrar`,
    `unar`, `7z`, atau `bsdtar`.
    - Windows : download UnRAR dari rarlab.com/rar_add.htm, taruh
                unrar.exe di folder ini atau tambahkan ke PATH
    - macOS   : brew install unar
    - Linux   : sudo apt install unrar   (atau: sudo apt install p7zip-full)
"""

import io
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import streamlit as st
from PIL import Image, ImageOps

# ---------------------------------------------------------------------------
# Deteksi library / tool opsional
# ---------------------------------------------------------------------------

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_SUPPORTED = True
except ImportError:
    HEIC_SUPPORTED = False

try:
    import py7zr
    SEVENZ_LIB_SUPPORTED = True
except ImportError:
    SEVENZ_LIB_SUPPORTED = False

# Tool eksternal untuk membongkar RAR (dicoba berurutan, pakai yang pertama ketemu)
RAR_TOOL_CANDIDATES = ["unrar", "unar", "7z", "7za", "bsdtar"]
RAR_TOOL = next((t for t in RAR_TOOL_CANDIDATES if shutil.which(t)), None)
RAR_SUPPORTED = RAR_TOOL is not None

# Tool eksternal 7z sebagai fallback kalau library py7zr tidak ada
SEVENZ_TOOL = next((t for t in ["7z", "7za"] if shutil.which(t)), None)
SEVENZ_SUPPORTED = SEVENZ_LIB_SUPPORTED or (SEVENZ_TOOL is not None)


KNOWN_IMAGE_EXTENSIONS = {
    ".png", ".bmp", ".tiff", ".tif", ".webp", ".gif", ".ico",
    ".jfif", ".jpg", ".jpeg", ".ppm", ".pgm", ".pbm", ".tga",
}
if HEIC_SUPPORTED:
    KNOWN_IMAGE_EXTENSIONS |= {".heic", ".heif"}

ARCHIVE_EXTENSIONS = {".zip"}
if RAR_SUPPORTED:
    ARCHIVE_EXTENSIONS.add(".rar")
if SEVENZ_SUPPORTED:
    ARCHIVE_EXTENSIONS.add(".7z")

JUNK_MARKERS = ("__MACOSX", ".DS_Store", "Thumbs.db")


def is_junk(path: str) -> bool:
    name = Path(path).name
    return any(m in path for m in JUNK_MARKERS) or name.startswith(".")


def sniff_is_image(data: bytes) -> bool:
    """Cek isi (konten) file, bukan cuma ekstensi — untuk file yang
    ekstensinya asing/tidak dikenal tapi sebenarnya gambar valid."""
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        return True
    except Exception:
        return False


def looks_like_image(path: str, data: bytes) -> bool:
    """Deteksi gambar: cek ekstensi dulu (cepat), kalau ekstensi tidak
    dikenal baru sniff isi file (lebih lambat tapi menangkap ekstensi salah)."""
    ext = Path(path).suffix.lower()
    if ext in KNOWN_IMAGE_EXTENSIONS:
        return True
    # Ekstensi tak dikenal / tidak ada -> coba baca isinya
    if ext in ARCHIVE_EXTENSIONS or ext in {".txt", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".exe"}:
        return False  # jelas bukan gambar, skip sniff biar cepat
    return sniff_is_image(data)


# ---------------------------------------------------------------------------
# Ekstraksi arsip
# ---------------------------------------------------------------------------

def extract_from_zip(file_bytes: bytes):
    """-> list of (relative_path, raw_bytes) khusus entri yang terdeteksi gambar."""
    found = []
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir() or is_junk(info.filename):
                continue
            data = zf.read(info.filename)
            if looks_like_image(info.filename, data):
                found.append((info.filename, data))
    return found


def _extract_via_subprocess(tool: str, archive_path: str, out_dir: str):
    """Jalankan tool eksternal untuk extract arsip ke folder out_dir."""
    if tool == "unrar":
        cmd = ["unrar", "x", "-y", "-inul", archive_path, out_dir + os.sep]
    elif tool == "unar":
        cmd = ["unar", "-f", "-quiet", "-output-directory", out_dir, archive_path]
    elif tool in ("7z", "7za"):
        cmd = [tool, "x", "-y", f"-o{out_dir}", archive_path]
    elif tool == "bsdtar":
        cmd = ["bsdtar", "-xf", archive_path, "-C", out_dir]
    else:
        raise RuntimeError(f"Tool tidak dikenal: {tool}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return result


def extract_from_rar(file_bytes: bytes):
    """Extract RAR pakai tool eksternal (subprocess) -> lebih kompatibel
    lintas OS/varian tool dibanding library python rarfile."""
    if not RAR_SUPPORTED:
        raise RuntimeError(
            "Tidak ada program pembongkar RAR di sistem ini. Install salah satu: "
            "unrar, unar, 7z, atau bsdtar."
        )
    found = []
    work_dir = tempfile.mkdtemp()
    archive_path = os.path.join(work_dir, "archive.rar")
    out_dir = os.path.join(work_dir, "out")
    os.makedirs(out_dir, exist_ok=True)
    try:
        with open(archive_path, "wb") as f:
            f.write(file_bytes)

        # Coba tool utama; kalau gagal/tidak ada file ter-extract, coba tool lain yang tersedia
        tools_to_try = [RAR_TOOL] + [t for t in RAR_TOOL_CANDIDATES if t != RAR_TOOL and shutil.which(t)]
        last_error = None
        extracted_any = False
        for tool in tools_to_try:
            try:
                result = _extract_via_subprocess(tool, archive_path, out_dir)
                if any(Path(out_dir).rglob("*")):
                    extracted_any = True
                    break
                last_error = result.stderr or result.stdout
            except Exception as e:
                last_error = str(e)

        if not extracted_any:
            raise RuntimeError(f"Semua tool RAR gagal mengekstrak. Detail: {last_error}")

        for root, _, files in os.walk(out_dir):
            for fname in files:
                full_path = os.path.join(root, fname)
                rel_path = os.path.relpath(full_path, out_dir)
                if is_junk(rel_path):
                    continue
                with open(full_path, "rb") as f:
                    data = f.read()
                if looks_like_image(rel_path, data):
                    found.append((rel_path.replace(os.sep, "/"), data))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    return found


def extract_from_7z(file_bytes: bytes):
    found = []
    work_dir = tempfile.mkdtemp()
    archive_path = os.path.join(work_dir, "archive.7z")
    out_dir = os.path.join(work_dir, "out")
    os.makedirs(out_dir, exist_ok=True)
    try:
        with open(archive_path, "wb") as f:
            f.write(file_bytes)

        used_lib = False
        if SEVENZ_LIB_SUPPORTED:
            try:
                with py7zr.SevenZipFile(archive_path, mode="r") as zf:
                    zf.extractall(path=out_dir)
                used_lib = True
            except Exception:
                used_lib = False

        if not used_lib:
            if not SEVENZ_TOOL:
                raise RuntimeError("Tidak ada library py7zr maupun program 7z di sistem ini.")
            result = _extract_via_subprocess(SEVENZ_TOOL, archive_path, out_dir)
            if not any(Path(out_dir).rglob("*")):
                raise RuntimeError(f"Gagal mengekstrak 7z. Detail: {result.stderr or result.stdout}")

        for root, _, files in os.walk(out_dir):
            for fname in files:
                full_path = os.path.join(root, fname)
                rel_path = os.path.relpath(full_path, out_dir)
                if is_junk(rel_path):
                    continue
                with open(full_path, "rb") as f:
                    data = f.read()
                if looks_like_image(rel_path, data):
                    found.append((rel_path.replace(os.sep, "/"), data))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
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
    "Upload gambar satuan (format apa pun"
    + (", termasuk HEIC/HEIF" if HEIC_SUPPORTED else "")
    + ") **atau** upload file arsip (ZIP"
    + (", RAR" if RAR_SUPPORTED else "")
    + (", 7Z" if SEVENZ_SUPPORTED else "")
    + "). Tool ini otomatis mendeteksi & mengekstrak semua gambar di "
    "dalamnya — termasuk di sub-folder bertingkat — berdasarkan isi file, "
    "bukan cuma ekstensinya."
)

missing_notes = []
if not HEIC_SUPPORTED:
    missing_notes.append("`pip install pillow-heif` → dukungan file **HEIC/HEIF** (foto iPhone)")
if not RAR_SUPPORTED:
    missing_notes.append(
        "Install salah satu program: `unrar` / `unar` / `7z` / `bsdtar` di sistem → dukungan arsip **RAR** "
        "(contoh Linux: `sudo apt install unrar`, macOS: `brew install unar`)"
    )
if not SEVENZ_SUPPORTED:
    missing_notes.append("`pip install py7zr` atau install program `7z` di sistem → dukungan arsip **7Z**")

if missing_notes:
    with st.expander("💡 Fitur tambahan yang bisa diaktifkan"):
        for note in missing_notes:
            st.markdown(f"- {note}")
else:
    st.caption(f"✅ Semua format arsip didukung (RAR via `{RAR_TOOL}`).")

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

# file_uploader butuh daftar tipe eksplisit untuk filter dialog browser,
# tapi deteksi sebenarnya tetap berbasis isi file (lihat looks_like_image)
upload_types = (
    list(ext.lstrip(".") for ext in KNOWN_IMAGE_EXTENSIONS)
    + list(ext.lstrip(".") for ext in ARCHIVE_EXTENSIONS)
)

uploaded_files = st.file_uploader(
    "Pilih gambar satuan, atau upload file arsip (ZIP/RAR/7Z) berisi banyak gambar",
    type=upload_types,
    accept_multiple_files=True,
)

if uploaded_files:
    image_sources = []  # (relative_path_no_ext, raw_bytes, asal_file)
    archive_count = 0

    with st.spinner("Memindai & mendeteksi file yang diupload..."):
        for uf in uploaded_files:
            ext = Path(uf.name).suffix.lower()
            raw = uf.getvalue()

            if ext in ARCHIVE_EXTENSIONS:
                archive_count += 1
                archive_root = Path(uf.name).stem
                try:
                    found = extract_images_from_archive(raw, uf.name)
                    if not found:
                        st.warning(f"⚠️ Tidak ada gambar yang ditemukan di dalam **{uf.name}**.")
                    for inner_path, data in found:
                        rel_path = str(Path(archive_root) / Path(inner_path).with_suffix(""))
                        image_sources.append((rel_path, data, uf.name))
                except zipfile.BadZipFile:
                    st.error(f"❌ **{uf.name}** bukan file ZIP yang valid / rusak.")
                except Exception as e:
                    st.error(f"❌ Gagal membuka **{uf.name}**: {e}")
            elif looks_like_image(uf.name, raw):
                rel_path = str(Path(uf.name).with_suffix(""))
                image_sources.append((rel_path, raw, uf.name))
            else:
                st.warning(f"⚠️ **{uf.name}** dilewati — bukan gambar/arsip yang bisa dikenali.")

    if archive_count:
        st.caption(f"🔍 {archive_count} file arsip dipindai, ditemukan {len(image_sources)} gambar total.")

    if image_sources:
        st.subheader(f"📂 {len(image_sources)} gambar siap dikonversi")

        results = []  # (path_with_folder.jpg, jpg_bytes)
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
                flat_name = Path(new_name).name
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
