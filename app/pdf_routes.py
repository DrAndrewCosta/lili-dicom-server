# app/pdf_routes.py
import os, shutil, subprocess
from flask import send_file, abort, request, Blueprint, redirect, url_for, jsonify

from .pdf_tools import (
    find_first_dir, build_study_pdf, build_series_pdf
)

pdfbp = Blueprint("pdfbp", __name__)

def _store_dir():
    return os.getenv("STORE_DIR", "storage")

def _allowed_remote_addr():
    allow = os.getenv("ALLOW_IPS", "127.0.0.1,::1")
    return [x.strip() for x in allow.split(",") if x.strip()]

def _ensure_study_pdf(study_uid):
    sdir = find_first_dir(_store_dir(), study_uid)
    if not sdir:
        abort(404, description="Estudo não encontrado.")
    pdf_path = os.path.join(sdir, "_study.pdf")
    try:
        if os.getenv("REGEN_PDF", "0") == "1" or not os.path.exists(pdf_path):
            pdf_path = build_study_pdf(sdir, study_uid, _store_dir())
    except Exception as e:
        abort(422, description=f"Falha ao gerar PDF do estudo: {e}")
    return pdf_path

def _ensure_series_pdf(series_uid):
    sdir = find_first_dir(_store_dir(), series_uid)
    if not sdir:
        abort(404, description="Série não encontrada.")
    pdf_path = os.path.join(sdir, f"_series_{series_uid}.pdf")
    try:
        if os.getenv("REGEN_PDF", "0") == "1" or not os.path.exists(pdf_path):
            pdf_path = build_series_pdf(sdir, series_uid)
    except Exception as e:
        abort(422, description=f"Falha ao gerar PDF da série: {e}")
    return pdf_path

def _lp_print(pdf_path):
    """Impressão direta via CUPS (lp). Usa PRINTER_NAME, se definido."""
    printer = os.getenv("PRINTER_NAME", "").strip()
    lp = shutil.which("lp")
    if not lp:
        return False, "Comando 'lp' (CUPS) não encontrado no sistema."
    cmd = [lp]
    if printer:
        cmd += ["-d", printer]
    cmd += [pdf_path]
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        if p.returncode != 0:
            return False, p.stderr.decode("utf-8", errors="ignore") or "Falha desconhecida no lp"
        return True, ""
    except Exception as e:
        return False, str(e)

@pdfbp.get("/pdf/study/<study_uid>")
def pdf_study(study_uid):
    pdf_path = _ensure_study_pdf(study_uid)
    return send_file(pdf_path, mimetype="application/pdf", as_attachment=False, download_name=f"{study_uid}.pdf")

@pdfbp.get("/pdf/series/<series_uid>")
def pdf_series(series_uid):
    pdf_path = _ensure_series_pdf(series_uid)
    return send_file(pdf_path, mimetype="application/pdf", as_attachment=False, download_name=f"{series_uid}.pdf")

@pdfbp.get("/print/study/<study_uid>")
def print_study(study_uid):
    direct = request.args.get("direct", "0") == "1" or os.getenv("PRINT_DIRECT", "0") == "1"
    pdf_path = _ensure_study_pdf(study_uid)
    if direct:
        if request.remote_addr not in _allowed_remote_addr():
            abort(403, description="IP não autorizado para impressão direta.")
        ok, err = _lp_print(pdf_path)
        if not ok:
            return jsonify({"ok": False, "printed": False, "error": err}), 500
        return jsonify({"ok": True, "printed": True})
    return redirect(url_for("pdfbp.pdf_study", study_uid=study_uid))

@pdfbp.get("/print/series/<series_uid>")
def print_series(series_uid):
    direct = request.args.get("direct", "0") == "1" or os.getenv("PRINT_DIRECT", "0") == "1"
    pdf_path = _ensure_series_pdf(series_uid)
    if direct:
        if request.remote_addr not in _allowed_remote_addr():
            abort(403, description="IP não autorizado para impressão direta.")
        ok, err = _lp_print(pdf_path)
        if not ok:
            return jsonify({"ok": False, "printed": False, "error": err}), 500
        return jsonify({"ok": True, "printed": True})
    return redirect(url_for("pdfbp.pdf_series", series_uid=series_uid))

def register_pdf_routes(app):
    app.register_blueprint(pdfbp)
