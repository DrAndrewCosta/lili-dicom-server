import os, io, socket, logging, zipfile, subprocess
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
from PIL import Image
from flask import Flask, render_template, jsonify, send_from_directory, send_file, abort, url_for, request, Response, redirect

from pydicom import dcmread
from pydicom.dataset import FileMetaDataset
from pydicom.uid import (ExplicitVRLittleEndian, ImplicitVRLittleEndian, ExplicitVRBigEndian,
    JPEGBaseline, JPEGExtended, JPEGLossless, JPEGLosslessSV1, JPEGLSNearLossless, JPEGLSLossless,
    RLELossless, DeflatedExplicitVRLittleEndian)

from pynetdicom import AE, evt, StoragePresentationContexts, build_context
from pynetdicom.sop_class import Verification

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

AE_TITLE = os.getenv("AE_TITLE","PACSANDREW").strip()
DICOM_PORT = int(os.getenv("DICOM_PORT","11112"))
WEB_PORT = int(os.getenv("WEB_PORT","8080"))
STORE_DIR = Path(os.getenv("STORE_DIR", str(Path(__file__).parent / "storage")))
STORE_DIR.mkdir(parents=True, exist_ok=True)

PDF_COLS = int(os.getenv("PDF_COLS","4"))
PDF_ROWS = int(os.getenv("PDF_ROWS","2"))
PDF_MARGIN = float(os.getenv("PDF_MARGIN","36"))
PDF_HEADER = os.getenv("PDF_HEADER","Dr. Andrew Costa - ultrassomdermatologico.com")
PDF_STUDY = os.getenv("PDF_STUDY","1").lower() not in ("0","false","no","off")

BRAND_TITLE = os.getenv("BRAND_TITLE","LILI DICOM")
BRAND_COLOR = os.getenv("BRAND_COLOR","#255375")

# Defaults updated per your request: admin/admin and print-direct on
BASIC_AUTH_USER = os.getenv("BASIC_AUTH_USER","admin").strip()
BASIC_AUTH_PASS = os.getenv("BASIC_AUTH_PASS","admin").strip()
PRINT_DIRECT = os.getenv("PRINT_DIRECT","1").lower() in ("1","true","on","yes")
PRINTER_NAME = os.getenv("PRINTER_NAME","").strip()  # empty => impressora padrão do macOS
ALLOW_IPS = [ip.strip() for ip in os.getenv("ALLOW_IPS","127.0.0.1,::1").split(",") if ip.strip()]

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler(Path(__file__).parent / "dicom_server.log"), logging.StreamHandler()])
logger = logging.getLogger("dicom")

def get_ip_addresses():
    ips=set(); ips.add("127.0.0.1")
    try:
        hn=socket.gethostname(); ips.add(socket.gethostbyname(hn))
    except Exception: pass
    try:
        s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("8.8.8.8",80))
        ips.add(s.getsockname()[0]); s.close()
    except Exception: pass
    return sorted(ips)

def unauthorized():
    return Response("Auth required", 401, {"WWW-Authenticate": 'Basic realm="DICOM UI"'})
def check_auth():
    if not BASIC_AUTH_USER: return True
    auth = request.headers.get("Authorization","")
    if not auth.startswith("Basic "): return False
    import base64
    try:
        userpass = base64.b64decode(auth.split(" ",1)[1]).decode("utf-8")
        user, pw = userpass.split(":",1)
        return (user == BASIC_AUTH_USER) and (pw == BASIC_AUTH_PASS)
    except Exception:
        return False

app = Flask(__name__,
            template_folder=str(Path(__file__).parent / "templates"),
            static_folder=str(Path(__file__).parent / "static"))

@app.before_request
def _basic_auth_guard():
    if request.path in ("/healthz","/readyz"): return
    if not check_auth(): return unauthorized()

def normalize_to_uint8(arr):
    arr = arr.astype(np.float32)
    lo = np.percentile(arr, 1.0); hi = np.percentile(arr, 99.0)
    if hi <= lo:
        lo, hi = float(arr.min()), float(arr.max() if arr.max()!=arr.min() else (arr.min()+1))
    arr = np.clip((arr - lo) / (hi - lo), 0, 1) * 255.0
    return arr.astype(np.uint8)

def ds_to_pil(ds):
    try:
        arr = ds.pixel_array
    except Exception as e:
        logger.warning(f"Preview skipped: {e}"); return None
    if arr.ndim==2:
        img = Image.fromarray(normalize_to_uint8(arr),'L')
        if getattr(ds,"PhotometricInterpretation","").upper()=="MONOCHROME1":
            arr = 255 - np.array(img); img = Image.fromarray(arr.astype(np.uint8),'L')
        return img.convert("RGB")
    elif arr.ndim==3:
        if arr.shape[2]==3: return Image.fromarray(arr.astype(np.uint8),"RGB")
        else: return Image.fromarray(normalize_to_uint8(arr[...,0]),'L').convert("RGB")
    return None

import re
_re_inst = re.compile(r"i(\\d+)", re.IGNORECASE)
def _files_sorted_by_instance(files):
    def key(p):
        m = _re_inst.search(p.stem)
        if m:
            try: return (int(m.group(1)), p.stem)
            except: pass
        return (999999, p.stem)
    return sorted(files, key=key)
def _caption_from_name(p):
    m = _re_inst.search(p.stem)
    return f"Inst #{int(m.group(1))}" if m else p.stem

def build_contact_sheet_pdf(previews_dir: Path, pdf_path: Path):
    files = [f for f in previews_dir.glob("*.png")]
    if not files: return
    files = _files_sorted_by_instance(files)
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    PAGE_W, PAGE_H = A4; margin = PDF_MARGIN; cols, rows = PDF_COLS, PDF_ROWS
    header_h = 20 if PDF_HEADER.strip() else 0
    c = canvas.Canvas(str(pdf_path), pagesize=A4); c.setAuthor("DICOM Server")
    usable_h = PAGE_H - (rows+1)*margin - header_h
    cell_w = (PAGE_W - (cols+1)*margin)/cols; cell_h = usable_h/rows
    for i, p in enumerate(files):
        if i % (cols*rows) == 0:
            if i>0: c.showPage()
            if header_h: c.setFont("Helvetica", 11); c.drawCentredString(PAGE_W/2, PAGE_H - margin/2 - 6, PDF_HEADER)
        idx = i % (cols*rows); r = rows-1-(idx//cols); col = idx%cols
        x = margin + col*(cell_w+margin); y = margin + r*(cell_h+margin) + header_h
        try: im = Image.open(p).convert("RGB")
        except: continue
        iw, ih = im.size; scale = min(cell_w/iw, (cell_h-12-4)/ih)
        dw, dh = iw*scale, ih*scale; dx = x+(cell_w-dw)/2; dy = y+(cell_h-12-dh)/2 + 6
        buf = io.BytesIO(); im.save(buf, format="JPEG", quality=85, optimize=True); buf.seek(0)
        c.drawImage(ImageReader(buf), dx, dy, width=dw, height=dh)
        c.setFont("Helvetica",8); c.drawCentredString(x+cell_w/2, y+2, _caption_from_name(p))
    c.showPage(); c.save()

def build_study_pdf(study_dir: Path, out_pdf: Path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    PAGE_W, PAGE_H = A4; margin = PDF_MARGIN; cols, rows = PDF_COLS, PDF_ROWS
    header_h = 20 if PDF_HEADER.strip() else 0
    files_any=False; c=None
    for sdir in sorted([d for d in study_dir.iterdir() if d.is_dir()]):
        previews = sdir / "previews"
        if not previews.is_dir(): continue
        files = [f for f in previews.glob("*.png")]
        if not files: continue
        files = _files_sorted_by_instance(files)
        if c is None:
            c = canvas.Canvas(str(out_pdf), pagesize=A4); c.setAuthor("DICOM Server")
        usable_h = PAGE_H - (rows+1)*margin - header_h
        cell_w = (PAGE_W - (cols+1)*margin)/cols; cell_h = usable_h/rows
        for i, p in enumerate(files):
            files_any=True
            if i % (cols*rows) == 0:
                if i>0: c.showPage()
                if header_h:
                    c.setFont("Helvetica",11); c.drawCentredString(PAGE_W/2, PAGE_H - margin/2 - 6, PDF_HEADER)
                    c.setFont("Helvetica",10); c.drawString(margin, PAGE_H - margin - (header_h + 6), f"Série: {sdir.name}")
            idx = i % (cols*rows); r = rows-1-(idx//cols); col = idx%cols
            x = margin + col*(cell_w+margin); y = margin + r*(cell_h+margin) + header_h
            try: im = Image.open(p).convert("RGB")
            except: continue
            iw, ih = im.size; scale = min(cell_w/iw, (cell_h-12-4)/ih)
            dw, dh = iw*scale, ih*scale; dx = x+(cell_w-dw)/2; dy = y+(cell_h-12-dh)/2 + 6
            buf = io.BytesIO(); im.save(buf, format="JPEG", quality=85, optimize=True); buf.seek(0)
            c.drawImage(ImageReader(buf), dx, dy, width=dw, height=dh)
            c.setFont("Helvetica",8); c.drawCentredString(x+cell_w/2, y+2, _caption_from_name(p))
    if c and files_any: c.showPage(); c.save()

class DicomServer:
    def __init__(self, ae_title, port, store_dir: Path):
        self.ae_title=ae_title; self.port=port; self.store_dir=store_dir
        self.ae = AE(ae_title=ae_title)
        ts_list = [ExplicitVRLittleEndian, ImplicitVRLittleEndian, ExplicitVRBigEndian,
            JPEGBaseline, JPEGExtended, JPEGLossless, JPEGLosslessSV1, JPEGLSNearLossless, JPEGLSLossless,
            RLELossless, DeflatedExplicitVRLittleEndian]
        self.ae.supported_contexts = [build_context(cx.abstract_syntax, ts_list) for cx in StoragePresentationContexts]
        self.ae.add_supported_context(Verification)
        self.ae.maximum_pdu_size = 16*1024*1024
        self.ae.acse_timeout = 30; self.ae.dimse_timeout = 30; self.ae.network_timeout = 30
        self.ae.maximum_associations = 25
        self.server=None
    def handle_store(self, event):
        try:
            ds = event.dataset; fmeta = FileMetaDataset()
            try:
                req = event.request
                fmeta.MediaStorageSOPClassUID = req.AffectedSOPClassUID
                fmeta.MediaStorageSOPInstanceUID = req.AffectedSOPInstanceUID
                fmeta.TransferSyntaxUID = event.context.transfer_syntax
            except: pass
            ds.file_meta = fmeta; ds.is_little_endian=True; ds.is_implicit_VR=False
            now = datetime.now(); study_uid = getattr(ds,"StudyInstanceUID","UnknownStudy"); series_uid = getattr(ds,"SeriesInstanceUID","UnknownSeries"); sop_uid = getattr(ds,"SOPInstanceUID", now.strftime("%H%M%S%f"))
            series_dir = self.store_dir / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d") / study_uid / series_uid
            series_dir.mkdir(parents=True, exist_ok=True)
            out_path = series_dir / f"{sop_uid}.dcm"; ds.save_as(out_path, write_like_original=False)
            try:
                img = ds_to_pil(ds)
                if img is not None:
                    previews = series_dir / "previews"; previews.mkdir(exist_ok=True)
                    existing = sorted(previews.glob("*.png")); idx = len(existing) + 1
                    inst = getattr(ds,"InstanceNumber", None); sort_key=999999
                    if inst is not None:
                        try: sort_key=max(0,int(str(inst)))
                        except: sort_key=999999
                    img.save(previews / f"i{sort_key:05d}_{idx:04d}.png", format='PNG', optimize=True)
            except Exception as e:
                logger.warning(f"no preview: {e}")
            try:
                previews = series_dir / "previews"
                if previews.exists(): build_contact_sheet_pdf(previews, series_dir / "SeriesContactSheet.pdf")
                if PDF_STUDY:
                    build_study_pdf(series_dir.parent, series_dir.parent / "StudyContactSheet.pdf")
            except Exception as e:
                logger.warning(f"pdf fail: {e}")
            return 0x0000
        except Exception as e:
            logger.exception(f"C-STORE error: {e}")
            return 0xA700
    def handle_echo(self, event): return 0x0000
    def start(self):
        handlers=[(evt.EVT_C_STORE,self.handle_store),(evt.EVT_C_ECHO,self.handle_echo)]
        self.server = self.ae.start_server(("", self.port), block=False, evt_handlers=handlers)
        logger.info(f"DICOM server started AE={self.ae_title} PORT={self.port} STORE={self.store_dir}")
        return self.server

dicom_server = DicomServer(AE_TITLE, DICOM_PORT, STORE_DIR); dicom_server.start()

def human_date_from_dir(d: Path):
    try:
        y,m,dd = d.parts[-3:]
        return f"{dd}/{m}/{y}"
    except: return d.name
def pick_one_dcm(series_dir: Path):
    for p in series_dir.iterdir():
        if p.is_file() and p.suffix.lower()==".dcm": return p
    return None
def get_study_metadata(study_dir: Path):
    meta = {"patient_name":None,"patient_id":None,"study_desc":None,"date":None}
    for sdir in sorted([x for x in study_dir.iterdir() if x.is_dir()]):
        dcm = pick_one_dcm(sdir)
        if dcm:
            try:
                ds = dcmread(str(dcm), stop_before_pixels=True, force=True)
                meta["patient_name"] = str(getattr(ds,"PatientName", "")) or None
                meta["patient_id"] = str(getattr(ds,"PatientID", "")) or None
                meta["study_desc"] = str(getattr(ds,"StudyDescription", "")) or None
                sd = getattr(ds,"StudyDate", None) or getattr(ds,"SeriesDate", None)
                if sd and len(str(sd))>=8:
                    y,m,d = sd[:4], sd[4:6], sd[6:8]; meta["date"] = f"{d}/{m}/{y}"
                break
            except Exception: continue
    return meta
def iter_days(base_dir: Path, days:int=7):
    now = datetime.now()
    for i in range(days):
        dt = now - timedelta(days=i)
        d = base_dir / dt.strftime("%Y") / dt.strftime("%m") / dt.strftime("%d")
        if d.exists(): yield d

def _client_ip_allowed(req):
    ip = req.headers.get("X-Forwarded-For", req.remote_addr or "")
    ip = (ip or "").split(",")[0].strip()
    return (ip in ALLOW_IPS)

from flask import jsonify
@app.route("/")
def index():
    info = {"ae_title": AE_TITLE, "port": DICOM_PORT, "store_dir": str(STORE_DIR.resolve()),
            "host_ips": get_ip_addresses(), "pdf_study": PDF_STUDY, "pdf_header": PDF_HEADER,
            "basic_auth": bool(BASIC_AUTH_USER), "print_direct": PRINT_DIRECT}
    return render_template("index.html", info=info, brand_title=BRAND_TITLE, brand_color=BRAND_COLOR)

@app.route("/healthz")
def healthz(): return jsonify({"status":"ok"}), 200
@app.route("/readyz")
def readyz(): return jsonify({"ready":True}), 200

@app.route("/logs")
def logs():
    log_path = Path(__file__).parent / "dicom_server.log"
    try:
        with open(log_path,"r",encoding="utf-8",errors="ignore") as f:
            return jsonify({"lines": f.readlines()[-500:]})
    except: return jsonify({"lines":[]})

@app.route("/storage/<path:subpath>")
def storage(subpath): return send_from_directory(STORE_DIR, subpath, as_attachment=False)

@app.route("/browse")
def browse():
    days = int(request.args.get("days", "7"))
    studies_data = []
    for day_dir in iter_days(STORE_DIR, days=days):
        y = day_dir.parts[-3]; m = day_dir.parts[-2]; d = day_dir.parts[-1]
        ymd = f"{y}{m}{d}"
        for study in sorted([x for x in day_dir.iterdir() if x.is_dir()]):
            series_dirs = [s for s in sorted(study.iterdir()) if s.is_dir()]
            total_prev=0; first_preview=None; first_preview_url=None; series_count = 0
            for sdir in series_dirs:
                series_count += 1
                previews = sdir / "previews"
                if previews.is_dir():
                    files = sorted(previews.glob("*.png")); total_prev += len(files)
                    if not first_preview and files:
                        first_preview = files[0]
                        first_preview_url = "/storage/" + str(first_preview.relative_to(STORE_DIR)).replace("\\","/")
            meta = get_study_metadata(study)
            study_pdf = study / "StudyContactSheet.pdf"
            study_pdf_url = "/storage/" + str(study_pdf.relative_to(STORE_DIR)).replace("\\","/") if study_pdf.exists() else None
            zip_url = url_for("download_study_zip", ymd=ymd, study_uid=study.name)
            print_direct_url = url_for("print_direct_study", ymd=ymd, study_uid=study.name) if PRINT_DIRECT else None
            studies_data.append({
                "ymd": ymd, "study_dir": study, "study_uid": study.name,
                "study_uid_short": study.name[:12] + ("…" if len(study.name)>12 else ""),
                "series_count": series_count, "total_previews": total_prev,
                "first_preview": bool(first_preview),"first_preview_url": first_preview_url,
                "patient_name": meta.get("patient_name"), "patient_id": meta.get("patient_id"),
                "study_desc": meta.get("study_desc"),
                "date_human": meta.get("date") or f"{d}/{m}/{y}",
                "study_pdf_url": study_pdf_url, "zip_url": zip_url,
                "study_page_url": url_for("study_page", ymd=ymd, study_uid=study.name),
                "print_direct_url": print_direct_url,
                "haystack": " ".join([meta.get("patient_name") or "", meta.get("patient_id") or "", study.name, ymd])
            })
    info = {"ae_title": AE_TITLE, "port": DICOM_PORT, "store_dir": str(STORE_DIR.resolve()),
            "host_ips": get_ip_addresses(), "pdf_study": PDF_STUDY, "pdf_header": PDF_HEADER,
            "basic_auth": bool(BASIC_AUTH_USER), "print_direct": PRINT_DIRECT}
    return render_template("browse.html", info=info, brand_title=BRAND_TITLE, brand_color=BRAND_COLOR, studies=studies_data, days=days)

@app.route("/studies")
def studies_redirect(): return redirect("/browse")
@app.route("/series")
def series_redirect(): return redirect("/browse")

@app.route("/study/<ymd>/<study_uid>")
def study_page(ymd, study_uid):
    if not (len(ymd)==8 and ymd.isdigit()): abort(400)
    y,m,d = ymd[:4], ymd[4:6], ymd[6:]
    study_dir = STORE_DIR / y / m / d / study_uid
    if not study_dir.exists(): abort(404)
    meta = get_study_metadata(study_dir)
    study_pdf = study_dir / "StudyContactSheet.pdf"
    meta["study_pdf_url"] = "/storage/" + str(study_pdf.relative_to(STORE_DIR)).replace("\\","/") if study_pdf.exists() else None
    meta["zip_url"] = url_for("download_study_zip", ymd=ymd, study_uid=study_uid)
    meta["print_direct_url"] = url_for("print_direct_study", ymd=ymd, study_uid=study_uid) if PRINT_DIRECT else None
    series_rows = []
    for sdir in sorted([x for x in study_dir.iterdir() if x.is_dir()]):
        previews = sdir / "previews"
        n = len(list(previews.glob("*.png"))) if previews.is_dir() else 0
        pdf = sdir / "SeriesContactSheet.pdf"
        pdf_url = "/storage/" + str(pdf.relative_to(STORE_DIR)).replace("\\","/") if pdf.exists() else None
        series_rows.append({"series_uid": sdir.name, "n_prev": n, "pdf_url": pdf_url})
    info = {"ae_title": AE_TITLE, "port": DICOM_PORT, "store_dir": str(STORE_DIR.resolve()),
            "host_ips": get_ip_addresses(), "pdf_study": PDF_STUDY, "pdf_header": PDF_HEADER,
            "basic_auth": bool(BASIC_AUTH_USER), "print_direct": PRINT_DIRECT}
    return render_template("study.html", info=info, brand_title=BRAND_TITLE, brand_color=BRAND_COLOR, study_uid=study_uid, meta=meta, series_rows=series_rows)

@app.route("/download/study/<ymd>/<study_uid>.zip")
def download_study_zip(ymd, study_uid):
    if not (len(ymd)==8 and ymd.isdigit()): abort(400)
    y,m,d = ymd[:4], ymd[4:6], ymd[6:]
    study_dir = STORE_DIR / y / m / d / study_uid
    if not study_dir.exists(): abort(404)
    mem = io.BytesIO()
    with zipfile.ZipFile(mem,"w",zipfile.ZIP_DEFLATED) as z:
        for p in study_dir.rglob("*"):
            if p.is_file(): z.write(p, arcname=str(p.relative_to(study_dir)))
    mem.seek(0)
    return send_file(mem, mimetype="application/zip", as_attachment=True, download_name=f"{study_uid}.zip")

@app.route("/print/direct/study/<ymd>/<study_uid>", methods=["POST"])
def print_direct_study(ymd, study_uid):
    if not PRINT_DIRECT: abort(404)
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    ip = (ip or "").split(",")[0].strip()
    if ip not in ALLOW_IPS: abort(403)
    if not (len(ymd)==8 and ymd.isdigit()): abort(400)
    y,m,d = ymd[:4], ymd[4:6], ymd[6:]
    pdf = STORE_DIR / y / m / d / study_uid / "StudyContactSheet.pdf"
    if not pdf.exists(): abort(404, "PDF não encontrado")
    cmd = ["lp"]
    if PRINTER_NAME: cmd += ["-d", PRINTER_NAME]
    cmd += ["-o","media=A4","-o","fit-to-page", str(pdf)]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return jsonify({"ok": True})
    except Exception:
        abort(500, "Falha ao imprimir")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=WEB_PORT, debug=False)
