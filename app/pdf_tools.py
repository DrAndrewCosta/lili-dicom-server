# app/pdf_tools.py
import os, io, glob, shutil
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader

import pydicom
from pydicom.pixel_data_handlers.util import apply_voi_lut
import numpy as np
from PIL import Image

from .pdf_layout import render_page_mosaic, _draw_fit

def find_first_dir(root, name):
    """Procura (recursivamente) o diretório cujo basename == name e retorna o caminho."""
    for cur, dirs, files in os.walk(root):
        if os.path.basename(cur) == name:
            return cur
        for d in dirs:
            if d == name:
                return os.path.join(cur, d)
    return None

def _human_ts_name(ts):
    try:
        return str(ts)
    except Exception:
        return f"{ts!r}"

def _dicom_to_pil(ds):
    """Converte um dataset DICOM em PIL.Image (8-bit) respeitando VOI LUT quando possível."""
    arr = ds.pixel_array  # pode lançar NotImplementedError para compressão não suportada
    try:
        arr = apply_voi_lut(arr, ds)
    except Exception:
        pass
    if getattr(ds, "PhotometricInterpretation", "MONOCHROME2").startswith("MONO"):
        arr = arr.astype(np.float32)
        lo, hi = float(np.min(arr)), float(np.max(arr))
        if hi <= lo: hi = lo + 1.0
        arr = (arr - lo) / (hi - lo)
        arr = (arr * 255.0).clip(0, 255).astype(np.uint8)
        im = Image.fromarray(arr, mode="L").convert("RGB")
    else:
        if arr.dtype != np.uint8:
            m = float(arr.max()) if arr.max() else 1.0
            arr = (arr / m * 255.0).clip(0,255).astype(np.uint8)
        if arr.ndim == 3 and arr.shape[-1] in (3, 4):
            im = Image.fromarray(arr[..., :3], mode="RGB")
        else:
            im = Image.fromarray(arr).convert("RGB")
    return im

def _collect_images_from_series(series_dir, max_per_series=None):
    """
    Coleta imagens (primeiras instâncias de cada série). Retorna (streams, notas).
    """
    streams, notes = [], []
    dcms = sorted(glob.glob(os.path.join(series_dir, "*.dcm")))
    if not dcms:
        dcms = sorted(glob.glob(os.path.join(series_dir, "**", "*.dcm"), recursive=True))
    if max_per_series:
        dcms = dcms[:max_per_series]
    for fp in dcms:
        ts_uid = None
        try:
            # pega TS sem carregar PixelData
            ds_head = pydicom.dcmread(fp, stop_before_pixels=True, force=True)
            ts_uid = getattr(ds_head, "file_meta", None)
            ts_uid = getattr(ts_uid, "TransferSyntaxUID", None)
        except Exception:
            pass
        try:
            ds = pydicom.dcmread(fp, force=True)
            if not hasattr(ds, "PixelData"):
                continue
            pil = _dicom_to_pil(ds)
            bio = io.BytesIO()
            pil.save(bio, format="PNG")
            bio.seek(0)
            streams.append(bio)
        except NotImplementedError:
            notes.append(f"Compressão não suportada em {os.path.basename(fp)} (TS={_human_ts_name(ts_uid)})")
        except Exception as e:
            notes.append(f"Falha ao ler {os.path.basename(fp)}: {e.__class__.__name__}")
    return streams, notes

def _collect_images_from_study(study_dir, max_series=None, max_per_series=1):
    """Coleta imagens do estudo – por padrão 1 imagem por série. Retorna (imgs, notas)."""
    imgs, notes = [], []
    subdirs = [d for d in sorted(os.listdir(study_dir)) if os.path.isdir(os.path.join(study_dir, d))]
    if max_series:
        subdirs = subdirs[:max_series]
    for d in subdirs:
        series_dir = os.path.join(study_dir, d)
        s_imgs, s_notes = _collect_images_from_series(series_dir, max_per_series=max_per_series)
        imgs.extend(s_imgs)
        notes.extend(s_notes)
    return imgs, notes

def _page_header(c, header_text, page_w, page_h, margin_left, margin_top):
    if not header_text:
        return 0.0
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(colors.HexColor(os.getenv("BRAND_COLOR", "#255375")))
    c.drawString(margin_left, page_h - margin_top + 0.3*cm, header_text)
    return 0.9*cm  # altura reservada do cabeçalho

def _save_empty_pdf(out_path, header, lines):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    c = canvas.Canvas(out_path, pagesize=A4)
    page_w, page_h = A4
    ml, mr, mb, mt = 1.5*cm, 1.5*cm, 1.7*cm, 1.7*cm
    _page_header(c, header, page_w, page_h, ml, mt)
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.black)
    y = page_h - mt - 0.8*cm
    c.drawString(ml, y, "PDF de contato — diagnóstico")
    y -= 0.6*cm
    c.setFont("Helvetica", 10.5)
    text = [
        "Não foi possível gerar miniaturas neste estudo/série.",
        "Possíveis causas: compressão DICOM não suportada neste ambiente, ou instâncias sem PixelData.",
        "Dicas: instale os plugins de decodificação (pylibjpeg-openjpeg, pylibjpeg-libjpeg) — já incluídos —",
        "ou acrescente GDCM se necessário; verifique /logs para detalhes."
    ]
    for line in text + list(dict.fromkeys(lines or []))[:10]:
        if y < mb + 1.5*cm:
            c.showPage(); y = page_h - mt - 1.0*cm
        c.drawString(ml, y, f"- {line}")
        y -= 0.45*cm
    c.showPage()
    c.save()
    return out_path

def _save_pdf(pages_images, out_path, title_header=None):
    """
    Escreve um PDF com as imagens fornecidas, aplicando mosaico ou grade.
    pages_images: lista de listas; cada item = imagens daquela página.
    """
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    c = canvas.Canvas(out_path, pagesize=A4)
    page_w, page_h = A4
    margin_left  = 1.5*cm
    margin_right = 1.5*cm
    margin_bottom = 1.7*cm
    margin_top = 1.7*cm

    for page_imgs in pages_images:
        header_h = _page_header(c, title_header, page_w, page_h, margin_left, margin_top)
        content_x = margin_left
        content_y = margin_bottom
        content_w = page_w - margin_left - margin_right
        content_h = page_h - header_h - margin_bottom

        used = render_page_mosaic(c, page_imgs, content_x, content_y, content_w, content_h)
        if not used:
            rows = int(os.getenv("PDF_ROWS", "2"))
            cols = int(os.getenv("PDF_COLS", "4"))
            cell_w = content_w / float(cols)
            cell_h = content_h / float(rows)
            i = 0
            for r in range(rows):
                for col in range(cols):
                    if i >= len(page_imgs):
                        break
                    reader = ImageReader(page_imgs[i])
                    x = content_x + col * cell_w
                    y = content_y + (rows - 1 - r) * cell_h
                    _draw_fit(c, reader, x, y, cell_w, cell_h)
                    i += 1
        c.showPage()
    c.save()
    return out_path

def build_study_pdf(study_dir, study_uid, store_dir):
    """
    Gera (ou sobrescreve) o PDF único do estudo e retorna o caminho.
    Nome: <study_dir>/_study.pdf
    """
    out_path = os.path.join(study_dir, "_study.pdf")
    imgs, notes = _collect_images_from_study(study_dir, max_per_series=1)
    if not imgs:
        # Gera PDF de diagnóstico em vez de estourar 500
        header = os.getenv("PDF_HEADER", "")
        return _save_empty_pdf(out_path, header, notes)
    slots = int(os.getenv("PDF_COLS", "4")) * int(os.getenv("PDF_ROWS", "2"))
    if os.getenv("PDF_LAYOUT_PRESET", "").strip().upper() == "GRUPO1" or os.getenv("PDF_LAYOUT_SPEC", "").strip():
        slots = 8
    pages = [imgs[i:i+slots] for i in range(0, len(imgs), slots)]
    header = os.getenv("PDF_HEADER", "")
    return _save_pdf(pages, out_path, title_header=header)

def build_series_pdf(series_dir, series_uid):
    """
    Gera (ou sobrescreve) o PDF da série e retorna o caminho.
    Nome: <series_dir>/_series_<series_uid>.pdf
    """
    out_path = os.path.join(series_dir, f"_series_{series_uid}.pdf")
    imgs, notes = _collect_images_from_series(series_dir, max_per_series=8)
    if not imgs:
        header = os.getenv("PDF_HEADER", "")
        return _save_empty_pdf(out_path, header, notes)
    slots = int(os.getenv("PDF_COLS", "4")) * int(os.getenv("PDF_ROWS", "2"))
    if os.getenv("PDF_LAYOUT_PRESET", "").strip().upper() == "GRUPO1" or os.getenv("PDF_LAYOUT_SPEC", "").strip():
        slots = 8
    pages = [imgs[i:i+slots] for i in range(0, len(imgs), slots)]
    header = os.getenv("PDF_HEADER", "")
    return _save_pdf(pages, out_path, title_header=header)
