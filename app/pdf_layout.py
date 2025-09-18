# app/pdf_layout.py
import os, json
from reportlab.lib.utils import ImageReader

def _draw_fit(c, img_reader: ImageReader, x, y, w, h, pad=6):
    """Desenha a imagem centrada no retângulo (x,y,w,h) mantendo proporção."""
    iw, ih = img_reader.getSize()
    sw = max((w - 2*pad) / float(iw), 0.001)
    sh = max((h - 2*pad) / float(ih), 0.001)
    s = min(sw, sh)
    dw, dh = iw * s, ih * s
    dx = x + (w - dw) / 2.0
    dy = y + (h - dh) / 2.0
    c.drawImage(img_reader, dx, dy, width=dw, height=dh, mask='auto')

def _iter_slots(content_x, content_y, content_w, content_h):
    """
    Define os slots (retângulos) do layout.
    - Se PDF_LAYOUT_SPEC (JSON) existir, usa-o (valores relativos 0..1).
    - Se PDF_LAYOUT_PRESET=GRUPO1, usa um mosaico “estilo anexo”.
    - Caso contrário, retorna lista vazia (o chamador cai no layout grade).
    """
    spec = os.getenv("PDF_LAYOUT_SPEC", "").strip()
    if spec:
        slots_rel = json.loads(spec)
    else:
        preset = os.getenv("PDF_LAYOUT_PRESET", "").strip().upper()
        if preset == "GRUPO1":
            # Topo: 2 blocos grandes; Meio/baixo: 6 miniaturas
            slots_rel = [
                {"x":0.00, "y":0.55, "w":0.66, "h":0.45},
                {"x":0.66, "y":0.55, "w":0.34, "h":0.45},
                {"x":0.00, "y":0.27, "w":0.33, "h":0.25},
                {"x":0.33, "y":0.27, "w":0.33, "h":0.25},
                {"x":0.66, "y":0.27, "w":0.34, "h":0.25},
                {"x":0.00, "y":0.00, "w":0.33, "h":0.25},
                {"x":0.33, "y":0.00, "w":0.33, "h":0.25},
                {"x":0.66, "y":0.00, "w":0.34, "h":0.25},
            ]
        else:
            slots_rel = []

    slots_abs = []
    for r in slots_rel:
        slots_abs.append((
            content_x + r["x"] * content_w,
            content_y + r["y"] * content_h,
            r["w"] * content_w,
            r["h"] * content_h,
        ))
    return slots_abs

def render_page_mosaic(c, page_imgs, content_x, content_y, content_w, content_h):
    """
    Desenha as imagens de page_imgs nos slots do mosaico.
    Retorna True se usou mosaico; False se não havia preset/JSON (usar grade).
    """
    slots = _iter_slots(content_x, content_y, content_w, content_h)
    if not slots:
        return False
    for img in page_imgs[:len(slots)]:
        reader = ImageReader(img)  # BytesIO ou caminho de arquivo
        x, y, w, h = slots.pop(0)
        _draw_fit(c, reader, x, y, w, h)
    return True
