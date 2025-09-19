import base64
import io
import logging
import os
import shutil
import socket
import subprocess
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)
from PIL import Image
from pydicom import dcmread
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import (
    DeflatedExplicitVRLittleEndian,
    ExplicitVRBigEndian,
    ExplicitVRLittleEndian,
    ImplicitVRLittleEndian,
    JPEGBaseline,
    JPEGExtended,
    JPEGLSLossless,
    JPEGLSNearLossless,
    JPEGLossless,
    JPEGLosslessSV1,
    RLELossless,
)
from pynetdicom import AE, evt, StoragePresentationContexts
from pynetdicom.sop_class import Verification
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

# ---------------------------------------------------------------------------
# Environment & configuration
# ---------------------------------------------------------------------------

AE_TITLE = os.getenv("AE_TITLE", "PACSANDREW").strip() or "PACSANDREW"
DICOM_PORT = int(os.getenv("DICOM_PORT", "11112"))
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
STORE_DIR = Path(os.getenv("STORE_DIR", Path(__file__).parent / "storage")).resolve()
STORE_DIR.mkdir(parents=True, exist_ok=True)

PDF_COLS = int(os.getenv("PDF_COLS", "2"))
PDF_ROWS = int(os.getenv("PDF_ROWS", "4"))
PDF_HEADER = os.getenv(
    "PDF_HEADER", "Dr. Andrew Costa - ultrassomdermatologico.com"
).strip()
PDF_STUDY = os.getenv("PDF_STUDY", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

BASIC_AUTH_USER = os.getenv("BASIC_AUTH_USER", "admin").strip()
BASIC_AUTH_PASS = os.getenv("BASIC_AUTH_PASS", "admin").strip()
PRINT_DIRECT = os.getenv("PRINT_DIRECT", "1").strip().lower() in {
    "1",
    "true",
    "on",
    "yes",
}
PRINTER_NAME = os.getenv("PRINTER_NAME", "").strip()
ALLOW_IPS = [
    ip.strip()
    for ip in os.getenv("ALLOW_IPS", "127.0.0.1,::1").split(",")
    if ip.strip()
]
BRAND_TITLE = os.getenv("BRAND_TITLE", "LILI DICOM").strip() or "LILI DICOM"
BRAND_COLOR = os.getenv("BRAND_COLOR", "#255375").strip() or "#255375"

LOG_PATH = Path(__file__).parent / "dicom_server.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
LOGGER = logging.getLogger("lili_dicom")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _percentile_window(arr: np.ndarray) -> Tuple[float, float]:
    try:
        lo = float(np.percentile(arr, 1.0))
        hi = float(np.percentile(arr, 99.0))
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            raise ValueError
        return lo, hi
    except Exception:
        lo = float(np.min(arr))
        hi = float(np.max(arr))
        if hi <= lo:
            hi = lo + 1.0
        return lo, hi


def dataset_to_image(ds: FileDataset) -> Optional[Image.Image]:
    """Return a RGB PIL.Image from the dataset or None if not possible."""

    if not hasattr(ds, "pixel_array"):
        return None
    try:
        array = ds.pixel_array
    except Exception as exc:  # pragma: no cover - relies on native handlers
        LOGGER.warning("pixel_array unavailable: %s", exc)
        return None

    if array.ndim == 2:
        lo, hi = _percentile_window(array.astype(np.float32))
        scaled = np.clip((array - lo) / (hi - lo), 0, 1) * 255.0
        img = Image.fromarray(scaled.astype(np.uint8), mode="L")
        if getattr(ds, "PhotometricInterpretation", "MONOCHROME2").upper() == "MONOCHROME1":
            img = Image.fromarray(255 - np.array(img), mode="L")
        return img.convert("RGB")

    if array.ndim == 3:
        if array.shape[-1] == 3:
            return Image.fromarray(array.astype(np.uint8), mode="RGB")
        if array.shape[0] == 3:
            return Image.fromarray(np.moveaxis(array, 0, -1).astype(np.uint8), mode="RGB")
        lo, hi = _percentile_window(array[..., 0].astype(np.float32))
        scaled = np.clip((array[..., 0] - lo) / (hi - lo), 0, 1) * 255.0
        return Image.fromarray(scaled.astype(np.uint8), mode="L").convert("RGB")

    return None


def _safe_instance_number(ds: FileDataset) -> int:
    value = getattr(ds, "InstanceNumber", None)
    try:
        return int(str(value))
    except Exception:
        return 999999


def _unique_preview_path(previews_dir: Path, instance_number: int) -> Path:
    previews_dir.mkdir(parents=True, exist_ok=True)
    index = 1
    while True:
        candidate = previews_dir / f"i{instance_number:05d}_{index:04d}.png"
        if not candidate.exists():
            return candidate
        index += 1


def save_preview_image(ds: FileDataset, series_dir: Path) -> Optional[Path]:
    image = dataset_to_image(ds)
    if image is None:
        return None
    previews_dir = series_dir / "previews"
    outfile = _unique_preview_path(previews_dir, _safe_instance_number(ds))
    outfile.parent.mkdir(parents=True, exist_ok=True)
    try:
        image.save(outfile, format="PNG", optimize=True)
        return outfile
    except Exception as exc:
        LOGGER.warning("failed to save preview: %s", exc)
        return None


def _draw_contact_sheet(
    image_paths: Sequence[Path],
    destination: Path,
    header: str,
    subtitle: Optional[str] = None,
) -> None:
    PAGE_W, PAGE_H = A4
    cols, rows = max(PDF_COLS, 1), max(PDF_ROWS, 1)
    per_page = max(cols * rows, 1)

    margin_x = 24.0
    margin_y = 24.0
    gutter_x = 12.0
    gutter_y = 12.0

    header_height = 0.0
    if header:
        header_height += 20.0
    if subtitle:
        header_height += 16.0
    if header_height:
        header_height += 8.0

    usable_width = PAGE_W - 2 * margin_x - gutter_x * (cols - 1)
    usable_height = PAGE_H - 2 * margin_y - header_height - gutter_y * (rows - 1)
    cell_w = usable_width / cols
    cell_h = usable_height / rows

    c = canvas.Canvas(str(destination), pagesize=A4)
    c.setTitle("Contact Sheet")

    total_pages = (len(image_paths) + per_page - 1) // per_page if image_paths else 0

    def draw_header(page_number: int) -> None:
        if not (header or subtitle):
            return
        y = PAGE_H - margin_y
        if header:
            c.setFont("Helvetica-Bold", 13)
            c.drawCentredString(PAGE_W / 2, y, header)
            y -= 18
        if subtitle:
            subtext = subtitle
            if total_pages > 1:
                subtext = f"{subtitle} — Página {page_number}/{total_pages}"
            c.setFont("Helvetica", 10)
            c.drawCentredString(PAGE_W / 2, y, subtext)

    for idx, image_path in enumerate(image_paths):
        if idx % per_page == 0:
            if idx:
                c.showPage()
            draw_header(idx // per_page + 1)

        pos = idx % per_page
        row = pos // cols
        col = pos % cols
        origin_x = margin_x + col * (cell_w + gutter_x)
        top_y = PAGE_H - margin_y - header_height - row * (cell_h + gutter_y)

        try:
            with Image.open(image_path) as image:
                image = image.convert("RGB")
                buf = io.BytesIO()
                image.save(buf, format="JPEG", quality=90, optimize=True)
                buf.seek(0)
                reader = ImageReader(buf)
                iw, ih = image.size
        except Exception as exc:  # pragma: no cover - depends on PIL
            LOGGER.warning("could not load preview for PDF: %s", exc)
            continue

        scale = min(cell_w / iw, cell_h / ih)
        draw_w = iw * scale
        draw_h = ih * scale
        dx = origin_x + (cell_w - draw_w) / 2
        dy = top_y - cell_h + (cell_h - draw_h) / 2
        c.drawImage(reader, dx, dy, width=draw_w, height=draw_h)

    c.save()


def _draw_diagnostic_pdf(destination: Path, header: str, lines: Sequence[str]) -> None:
    PAGE_W, PAGE_H = A4
    margin = 36.0
    c = canvas.Canvas(str(destination), pagesize=A4)
    if header:
        c.setFont("Helvetica", 11)
        c.drawCentredString(PAGE_W / 2, PAGE_H - margin / 2 - 6, header)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(margin, PAGE_H - margin - 24, "PDF de diagnóstico")
    c.setFont("Helvetica", 10)
    y = PAGE_H - margin - 48
    for line in lines:
        c.drawString(margin, y, f"- {line}")
        y -= 14
        if y <= margin:
            c.showPage()
            y = PAGE_H - margin
    if y == PAGE_H - margin:
        c.showPage()
    c.save()


def _series_preview_files(series_dir: Path) -> List[Path]:
    previews_dir = series_dir / "previews"
    if previews_dir.is_dir():
        return sorted(previews_dir.glob("*.png"))
    return []


def _collect_dicom_files(series_dir: Path) -> List[Path]:
    return sorted(p for p in series_dir.glob("*.dcm"))


def ensure_previews_for_series(series_dir: Path, limit: Optional[int] = None) -> Tuple[List[Path], List[str]]:
    errors: List[str] = []
    previews = _series_preview_files(series_dir)

    dicoms = _collect_dicom_files(series_dir)
    if not dicoms:
        return previews, errors

    target = len(dicoms) if limit is None else max(min(limit, len(dicoms)), 0)
    if target == 0:
        return [], errors
    if len(previews) >= target:
        return sorted(previews)[:target], errors

    for path in dicoms:
        if len(previews) >= target:
            break
        try:
            ds = dcmread(str(path), force=True)
        except Exception as exc:
            errors.append(f"Falha ao ler {path.name}: {exc}")
            continue
        if not hasattr(ds, "PixelData"):
            errors.append(f"{path.name} não possui PixelData")
            continue
        saved = save_preview_image(ds, series_dir)
        if saved is not None:
            previews.append(saved)

    return sorted(previews)[:target], errors


def generate_series_pdf(series_dir: Path, *, allow_preview_generation: bool = True) -> Path:
    pdf_path = series_dir / "SeriesContactSheet.pdf"
    previews, errors = ensure_previews_for_series(
        series_dir,
        limit=None if allow_preview_generation else 0,
    )
    if previews:
        subtitle = f"Série: {series_dir.name}"
        _draw_contact_sheet(previews, pdf_path, PDF_HEADER, subtitle=subtitle)
    else:
        if allow_preview_generation:
            errors.append("Nenhum preview disponível para esta série.")
        _draw_diagnostic_pdf(pdf_path, PDF_HEADER, errors)
    return pdf_path


def generate_study_pdf(study_dir: Path, *, allow_preview_generation: bool = True) -> Path:
    pdf_path = study_dir / "StudyContactSheet.pdf"
    all_previews: List[Path] = []
    errors: List[str] = []
    for series_dir in sorted(p for p in study_dir.iterdir() if p.is_dir()):
        previews, p_errors = ensure_previews_for_series(series_dir, limit=1 if allow_preview_generation else None)
        all_previews.extend(previews)
        errors.extend(p_errors)
    if all_previews:
        _draw_contact_sheet(all_previews, pdf_path, PDF_HEADER)
    else:
        if allow_preview_generation:
            errors.append("Nenhuma miniatura foi criada para o estudo.")
        _draw_diagnostic_pdf(pdf_path, PDF_HEADER, errors)
    return pdf_path


def _iter_day_dirs() -> Iterable[Path]:
    for year_dir in sorted(STORE_DIR.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir() or not month_dir.name.isdigit():
                continue
            for day_dir in sorted(month_dir.iterdir()):
                if day_dir.is_dir() and day_dir.name.isdigit():
                    yield day_dir


def find_study_dir(study_uid: str) -> Optional[Path]:
    matches: List[Path] = []
    for day_dir in _iter_day_dirs():
        candidate = day_dir / study_uid
        if candidate.is_dir():
            matches.append(candidate)
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def find_series_dir(series_uid: str) -> Optional[Path]:
    matches: List[Path] = []
    for day_dir in _iter_day_dirs():
        for study_dir in day_dir.iterdir():
            if not study_dir.is_dir():
                continue
            candidate = study_dir / series_uid
            if candidate.is_dir():
                matches.append(candidate)
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def _pick_date_parts(ds: FileDataset) -> Tuple[str, str, str]:
    candidates = [
        getattr(ds, "StudyDate", ""),
        getattr(ds, "SeriesDate", ""),
        getattr(ds, "AcquisitionDate", ""),
        getattr(ds, "ContentDate", ""),
    ]
    for value in candidates:
        value = str(value)
        if len(value) >= 8 and value[:8].isdigit():
            return value[:4], value[4:6], value[6:8]
    now = datetime.now()
    return now.strftime("%Y"), now.strftime("%m"), now.strftime("%d")


def _study_metadata_from_series(series_dir: Path) -> dict:
    metadata = {
        "patient_name": None,
        "patient_id": None,
        "study_desc": None,
        "study_date": None,
    }
    dicoms = _collect_dicom_files(series_dir)
    if not dicoms:
        return metadata
    try:
        ds = dcmread(str(dicoms[0]), stop_before_pixels=True, force=True)
    except Exception:
        return metadata
    metadata["patient_name"] = str(getattr(ds, "PatientName", "") or "") or None
    metadata["patient_id"] = str(getattr(ds, "PatientID", "") or "") or None
    metadata["study_desc"] = str(getattr(ds, "StudyDescription", "") or "") or None
    date_val = getattr(ds, "StudyDate", "") or getattr(ds, "SeriesDate", "")
    if date_val and len(str(date_val)) >= 8:
        metadata["study_date"] = f"{str(date_val)[6:8]}/{str(date_val)[4:6]}/{str(date_val)[:4]}"
    return metadata


def collect_study_metadata(study_dir: Path) -> dict:
    metadata = {
        "patient_name": None,
        "patient_id": None,
        "study_desc": None,
        "study_date": None,
    }
    for series_dir in sorted(p for p in study_dir.iterdir() if p.is_dir()):
        series_meta = _study_metadata_from_series(series_dir)
        for key, value in series_meta.items():
            if value and not metadata.get(key):
                metadata[key] = value
        if metadata["patient_name"] or metadata["patient_id"]:
            break
    return metadata


def iter_recent_day_dirs(days: int) -> Iterable[Path]:
    now = datetime.now()
    for i in range(days):
        dt = now - timedelta(days=i)
        day_dir = STORE_DIR / dt.strftime("%Y") / dt.strftime("%m") / dt.strftime("%d")
        if day_dir.exists():
            yield day_dir


def get_host_ips() -> List[str]:
    hosts = {"127.0.0.1"}
    try:
        hostname = socket.gethostname()
        hosts.add(socket.gethostbyname(hostname))
    except Exception:
        pass
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        hosts.add(sock.getsockname()[0])
        sock.close()
    except Exception:
        pass
    return sorted(hosts)


def _client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return (request.remote_addr or "").strip()


def _ensure_auth() -> Optional[Response]:
    if not BASIC_AUTH_USER:
        return None
    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return Response("Auth required", 401, {"WWW-Authenticate": 'Basic realm="LILI DICOM"'})
    try:
        decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
        user, password = decoded.split(":", 1)
    except Exception:
        return Response("Auth required", 401, {"WWW-Authenticate": 'Basic realm="LILI DICOM"'})
    if user == BASIC_AUTH_USER and password == BASIC_AUTH_PASS:
        return None
    return Response("Auth required", 401, {"WWW-Authenticate": 'Basic realm="LILI DICOM"'})


# ---------------------------------------------------------------------------
# DICOM Server
# ---------------------------------------------------------------------------


class DicomServer:
    def __init__(self, ae_title: str, port: int, store_dir: Path) -> None:
        self.ae_title = ae_title
        self.port = port
        self.store_dir = store_dir
        self.ae = AE(ae_title=ae_title)
        transfer_syntaxes = [
            ExplicitVRLittleEndian,
            ImplicitVRLittleEndian,
            ExplicitVRBigEndian,
            JPEGBaseline,
            JPEGExtended,
            JPEGLossless,
            JPEGLosslessSV1,
            JPEGLSNearLossless,
            JPEGLSLossless,
            RLELossless,
            DeflatedExplicitVRLittleEndian,
        ]
        for context in StoragePresentationContexts:
            self.ae.add_supported_context(
                context.abstract_syntax,
                transfer_syntaxes,
            )
        self.ae.add_supported_context(Verification)
        self.ae.maximum_pdu_size = 16 * 1024 * 1024
        self.ae.acse_timeout = 30
        self.ae.dimse_timeout = 30
        self.ae.network_timeout = 30
        self.ae.maximum_associations = 25
        self.server = None

    def start(self) -> None:
        handlers = [
            (evt.EVT_C_STORE, self.handle_store),
            (evt.EVT_C_ECHO, self.handle_echo),
        ]
        self.server = self.ae.start_server(("", self.port), block=False, evt_handlers=handlers)
        LOGGER.info("DICOM server started (AE=%s, port=%s)", self.ae_title, self.port)

    @staticmethod
    def handle_echo(event) -> int:  # pragma: no cover - network callback
        return 0x0000

    def handle_store(self, event) -> int:  # pragma: no cover - network callback
        try:
            ds = event.dataset
            file_meta = FileMetaDataset()
            try:
                request = event.request
                file_meta.MediaStorageSOPClassUID = request.AffectedSOPClassUID
                file_meta.MediaStorageSOPInstanceUID = request.AffectedSOPInstanceUID
                file_meta.TransferSyntaxUID = event.context.transfer_syntax
            except Exception:
                pass
            ds.file_meta = file_meta
            ds.is_little_endian = True
            ds.is_implicit_VR = False

            year, month, day = _pick_date_parts(ds)
            study_uid = getattr(ds, "StudyInstanceUID", datetime.now().strftime("%Y%m%d%H%M%S"))
            series_uid = getattr(ds, "SeriesInstanceUID", "UnknownSeries")
            sop_uid = getattr(ds, "SOPInstanceUID", datetime.now().strftime("%H%M%S%f"))

            series_dir = self.store_dir / year / month / day / study_uid / series_uid
            series_dir.mkdir(parents=True, exist_ok=True)
            outfile = series_dir / f"{sop_uid}.dcm"
            ds.save_as(outfile, write_like_original=False)
            LOGGER.info("Stored SOP %s in %s", sop_uid, series_dir)

            try:
                preview_path = save_preview_image(ds, series_dir)
                if preview_path:
                    LOGGER.info("Generated preview %s", preview_path.name)
            except Exception as exc:
                LOGGER.warning("Preview generation failed: %s", exc)

            try:
                generate_series_pdf(series_dir, allow_preview_generation=False)
                if PDF_STUDY:
                    generate_study_pdf(series_dir.parent, allow_preview_generation=False)
            except Exception as exc:
                LOGGER.warning("PDF generation failed: %s", exc)

            return 0x0000
        except Exception as exc:
            LOGGER.exception("C-STORE handler failure: %s", exc)
            return 0xA700


DICOM_SERVER: Optional[DicomServer]
if os.getenv("LILI_DISABLE_DICOM_SERVER", "0").strip() == "1":
    LOGGER.info("DICOM server start disabled by LILI_DISABLE_DICOM_SERVER=1")
    DICOM_SERVER = None
else:
    DICOM_SERVER = DicomServer(AE_TITLE, DICOM_PORT, STORE_DIR)
    DICOM_SERVER.start()

# ---------------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------------

app = Flask(
    __name__,
    template_folder=str(Path(__file__).parent / "templates"),
    static_folder=str(Path(__file__).parent / "static"),
)


@app.before_request
def require_authentication():  # pragma: no cover - integrates with Flask
    if request.path in {"/healthz", "/readyz"}:
        return None
    return _ensure_auth()


@app.route("/")
def root():
    return redirect(url_for("browse"))


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/readyz")
def readyz():
    return jsonify({"ready": True})


@app.route("/logs")
def http_logs():
    try:
        with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as handle:
            tail = handle.readlines()[-500:]
    except FileNotFoundError:
        tail = []
    return jsonify({"lines": tail})


@app.route("/storage/<path:subpath>")
def http_storage(subpath: str):
    return send_from_directory(STORE_DIR, subpath)


def _info_payload() -> dict:
    return {
        "ae_title": AE_TITLE,
        "port": DICOM_PORT,
        "web_port": WEB_PORT,
        "store_dir": str(STORE_DIR),
        "host_ips": get_host_ips(),
        "pdf_header": PDF_HEADER,
        "pdf_study": PDF_STUDY,
        "basic_auth": bool(BASIC_AUTH_USER),
        "print_direct": PRINT_DIRECT,
    }


@app.route("/")
def index():
    return redirect(url_for("browse"))


@app.route("/browse")
def browse():
    days = int(request.args.get("days", "7"))
    studies: List[dict] = []
    for day_dir in iter_recent_day_dirs(days):
        y, m, d = day_dir.parts[-3:]
        ymd = f"{y}{m}{d}"
        for study_dir in sorted(p for p in day_dir.iterdir() if p.is_dir()):
            metadata = collect_study_metadata(study_dir)
            first_preview = None
            first_preview_url = None
            total_previews = 0
            for series_dir in sorted(p for p in study_dir.iterdir() if p.is_dir()):
                previews = _series_preview_files(series_dir)
                if previews:
                    total_previews += len(previews)
                    if not first_preview:
                        rel = previews[0].relative_to(STORE_DIR)
                        first_preview = previews[0]
                        first_preview_url = url_for("http_storage", subpath=str(rel).replace(os.sep, "/"))
            study_pdf_path = study_dir / "StudyContactSheet.pdf"
            study_pdf_url = None
            if study_pdf_path.exists():
                rel = study_pdf_path.relative_to(STORE_DIR)
                study_pdf_url = url_for("http_storage", subpath=str(rel).replace(os.sep, "/"))
            studies.append(
                {
                    "ymd": ymd,
                    "study_uid": study_dir.name,
                    "study_uid_short": study_dir.name[:14] + ("…" if len(study_dir.name) > 14 else ""),
                    "patient_name": metadata.get("patient_name"),
                    "patient_id": metadata.get("patient_id"),
                    "study_desc": metadata.get("study_desc"),
                    "date_human": metadata.get("study_date") or f"{d}/{m}/{y}",
                    "first_preview": bool(first_preview),
                    "first_preview_url": first_preview_url,
                    "total_previews": total_previews,
                    "series_count": len([p for p in study_dir.iterdir() if p.is_dir()]),
                    "study_pdf_url": study_pdf_url,
                    "study_pdf_ready": bool(study_pdf_url),
                    "study_page_url": url_for("study_page", ymd=ymd, study_uid=study_dir.name),
                    "zip_url": url_for("download_study_zip", ymd=ymd, study_uid=study_dir.name),
                    "haystack": " ".join(
                        filter(
                            None,
                            [
                                metadata.get("patient_name"),
                                metadata.get("patient_id"),
                                study_dir.name,
                                ymd,
                            ],
                        )
                    ),
                }
            )
    return render_template(
        "browse.html",
        info=_info_payload(),
        brand_title=BRAND_TITLE,
        brand_color=BRAND_COLOR,
        studies=studies,
        days=days,
    )


@app.route("/studies")
def redirect_studies():
    return redirect(url_for("browse"))


@app.route("/series")
def redirect_series():
    return redirect(url_for("browse"))


@app.route("/study/<ymd>/<study_uid>")
def study_page(ymd: str, study_uid: str):
    if len(ymd) != 8 or not ymd.isdigit():
        abort(400, description="Data inválida")
    y, m, d = ymd[:4], ymd[4:6], ymd[6:]
    study_dir = STORE_DIR / y / m / d / study_uid
    if not study_dir.exists():
        abort(404, description="Estudo não encontrado")
    metadata = collect_study_metadata(study_dir)
    metadata["date_human"] = metadata.get("study_date") or f"{d}/{m}/{y}"
    study_pdf_path = study_dir / "StudyContactSheet.pdf"
    if study_pdf_path.exists():
        rel = study_pdf_path.relative_to(STORE_DIR)
        metadata["study_pdf_url"] = url_for("http_storage", subpath=str(rel).replace(os.sep, "/"))
        metadata["study_pdf_ready"] = True
    else:
        metadata["study_pdf_url"] = None
        metadata["study_pdf_ready"] = False
    metadata["zip_url"] = url_for("download_study_zip", ymd=ymd, study_uid=study_uid)
    series_rows = []
    for series_dir in sorted(p for p in study_dir.iterdir() if p.is_dir()):
        previews = _series_preview_files(series_dir)
        series_pdf_path = series_dir / "SeriesContactSheet.pdf"
        series_pdf_ready = series_pdf_path.exists()
        series_pdf_url = None
        if series_pdf_ready:
            rel = series_pdf_path.relative_to(STORE_DIR)
            series_pdf_url = url_for("http_storage", subpath=str(rel).replace(os.sep, "/"))
        series_rows.append(
            {
                "series_uid": series_dir.name,
                "preview_count": len(previews),
                "series_pdf_url": series_pdf_url,
                "series_pdf_ready": series_pdf_ready,
            }
        )
    return render_template(
        "study.html",
        info=_info_payload(),
        brand_title=BRAND_TITLE,
        brand_color=BRAND_COLOR,
        study_uid=study_uid,
        meta=metadata,
        series_rows=series_rows,
    )


@app.route("/download/study/<ymd>/<study_uid>.zip")
def download_study_zip(ymd: str, study_uid: str):
    if len(ymd) != 8 or not ymd.isdigit():
        abort(400, description="Data inválida")
    y, m, d = ymd[:4], ymd[4:6], ymd[6:]
    study_dir = STORE_DIR / y / m / d / study_uid
    if not study_dir.exists():
        abort(404, description="Estudo não encontrado")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in study_dir.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(study_dir)
                zf.write(file_path, arcname=str(arcname))
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{study_uid}.zip",
    )


def _ensure_series_pdf(series_uid: str) -> Path:
    series_dir = find_series_dir(series_uid)
    if series_dir is None:
        abort(404, description="Série não encontrada")
    return generate_series_pdf(series_dir, allow_preview_generation=True)


def _ensure_study_pdf(study_uid: str) -> Path:
    study_dir = find_study_dir(study_uid)
    if study_dir is None:
        abort(404, description="Estudo não encontrado")
    return generate_study_pdf(study_dir, allow_preview_generation=True)


@app.route("/pdf/study/<study_uid>")
def http_pdf_study(study_uid: str):
    pdf_path = _ensure_study_pdf(study_uid)
    return send_file(pdf_path, mimetype="application/pdf", as_attachment=False)


@app.route("/pdf/series/<series_uid>")
def http_pdf_series(series_uid: str):
    pdf_path = _ensure_series_pdf(series_uid)
    return send_file(pdf_path, mimetype="application/pdf", as_attachment=False)


def _print_via_lp(pdf_path: Path) -> Tuple[bool, str]:
    lp_path = shutil.which("lp")
    if not lp_path:
        return False, "Comando lp (CUPS) não encontrado"
    command = [lp_path]
    if PRINTER_NAME:
        command.extend(["-d", PRINTER_NAME])
    command.extend(["-o", "media=A4", "-o", "fit-to-page", str(pdf_path)])
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:
        return False, str(exc)
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or "Falha desconhecida no lp"
        return False, stderr
    return True, completed.stdout.strip()


@app.route("/print/study/<study_uid>")
def http_print_study(study_uid: str):
    direct = request.args.get("direct", "0") == "1"
    pdf_path = _ensure_study_pdf(study_uid)
    if not direct:
        return redirect(url_for("http_pdf_study", study_uid=study_uid))
    if not PRINT_DIRECT:
        abort(403, description="Impressão direta desabilitada")
    if _client_ip() not in ALLOW_IPS:
        abort(403, description="IP não autorizado para impressão direta")
    ok, message = _print_via_lp(pdf_path)
    status = 200 if ok else 500
    return jsonify({"ok": ok, "printed": ok, "message": message}), status


@app.route("/print/series/<series_uid>")
def http_print_series(series_uid: str):
    direct = request.args.get("direct", "0") == "1"
    pdf_path = _ensure_series_pdf(series_uid)
    if not direct:
        return redirect(url_for("http_pdf_series", series_uid=series_uid))
    if not PRINT_DIRECT:
        abort(403, description="Impressão direta desabilitada")
    if _client_ip() not in ALLOW_IPS:
        abort(403, description="IP não autorizado para impressão direta")
    ok, message = _print_via_lp(pdf_path)
    status = 200 if ok else 500
    return jsonify({"ok": ok, "printed": ok, "message": message}), status


if __name__ == "__main__":  # pragma: no cover - manual execution
    LOGGER.info("Starting Flask app on 0.0.0.0:%s", WEB_PORT)
    app.run(host="0.0.0.0", port=WEB_PORT, debug=False)
