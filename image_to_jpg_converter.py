"""
Image to JPG Converter — Streamlit App
=======================================
Convert berbagai format gambar (PNG, BMP, TIFF, WEBP, GIF, ICO, dll)
menjadi JPG dengan kualitas maksimal (tanpa kompresi berlebihan).

Cara menjalankan:
    pip install streamlit pillow pillow-heif
    streamlit run image_to_jpg_converter.py
"""

import io
import zipfile
from pathlib import Path

import streamlit as st
from PIL import Image, ImageOps

# Opsional: dukungan format HEIC/HEIF (foto iPhone)
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_SUPPORTED = True
except ImportError:
    HEIC_SUPPORTED = False


st.set_page_config(page_title="Image → JPG Converter", page_icon="🖼️", layout="centered")

st.title("🖼️ Konversi Gambar ke JPG (Kualitas Tinggi)")
st.write(
    "Upload gambar dalam format apa pun (PNG, BMP, TIFF, WEBP, GIF, ICO"
    + (", HEIC/HEIF" if HEIC_SUPPORTED else "")
    + ") lalu unduh hasilnya dalam format JPG tanpa kehilangan kualitas signifikan."
)

if not HEIC_SUPPORTED:
    st.info(
        "💡 Untuk mendukung file HEIC/HEIF (foto iPhone), install juga: "
        "`pip install pillow-heif`",
        icon="ℹ️",
    )

with st.sidebar:
    st.header("⚙️ Pengaturan Kualitas")
    quality = st.slider(
        "Kualitas JPG",
        min_value=85,
        max_value=100,
        value=100,
        help="100 = kualitas terbaik (mendekati lossless), ukuran file lebih besar.",
    )
    keep_max_size = st.checkbox(
        "Pertahankan resolusi asli (jangan resize)",
        value=True,
        disabled=True,
        help="Resolusi asli selalu dipertahankan, tool ini tidak melakukan resize.",
    )
    subsampling = st.selectbox(
        "Chroma Subsampling",
        options=[("Tanpa subsampling (kualitas terbaik)", 0), ("4:2:2", 1), ("4:2:0 (default JPG)", 2)],
        format_func=lambda x: x[0],
        index=0,
        help="Pilih 'Tanpa subsampling' untuk hasil paling mendekati gambar asli.",
    )[1]
    st.caption("Rekomendasi default: Quality 100, No Subsampling → hasil JPG mendekati lossless.")


def convert_to_jpg(file_bytes: bytes, filename: str, quality: int, subsampling: int):
    """Convert single image bytes to high-quality JPG bytes."""
    img = Image.open(io.BytesIO(file_bytes))

    # Perbaiki orientasi berdasarkan metadata EXIF (foto dari kamera/HP)
    img = ImageOps.exif_transpose(img)

    # JPG tidak mendukung transparansi (RGBA/P/LA) -> flatten ke background putih
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])  # gunakan alpha channel sbg mask
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


uploaded_files = st.file_uploader(
    "Pilih satu atau beberapa gambar",
    type=["png", "bmp", "tiff", "tif", "webp", "gif", "ico", "jfif", "jpg", "jpeg"]
    + (["heic", "heif"] if HEIC_SUPPORTED else []),
    accept_multiple_files=True,
)

if uploaded_files:
    st.subheader(f"📂 {len(uploaded_files)} file siap dikonversi")

    results = []  # list of (new_filename, jpg_bytes)
    errors = []

    progress = st.progress(0, text="Memproses gambar...")

    for i, uf in enumerate(uploaded_files):
        try:
            jpg_bytes = convert_to_jpg(uf.getvalue(), uf.name, quality, subsampling)
            new_name = Path(uf.name).stem + ".jpg"
            results.append((new_name, jpg_bytes))
        except Exception as e:
            errors.append((uf.name, str(e)))
        progress.progress((i + 1) / len(uploaded_files), text=f"Memproses {uf.name}...")

    progress.empty()

    if errors:
        with st.expander(f"⚠️ {len(errors)} file gagal dikonversi"):
            for name, err in errors:
                st.write(f"- **{name}**: {err}")

    if results:
        st.success(f"✅ {len(results)} gambar berhasil dikonversi ke JPG!")

        # Preview + tombol download per file
        for new_name, jpg_bytes in results:
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
                    file_name=new_name,
                    mime="image/jpeg",
                    key=f"dl_{new_name}",
                )
            st.divider()

        # Download semua sekaligus dalam ZIP jika lebih dari 1 file
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
    st.info("Silakan upload gambar untuk mulai konversi.")
