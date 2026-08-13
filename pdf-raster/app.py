# -*- coding: utf-8 -*-
"""Internal PDF-to-PNG service for the local metal workflow.

The raster contract intentionally matches the existing Cloud Run function while
adding a health endpoint and an explicit 25 MiB request ceiling. The service is
not published to the Windows host by docker-compose; authentication therefore
belongs at the Compose network boundary rather than in the payload contract.
"""

from __future__ import annotations

import io
import os

import pypdfium2 as pdfium
from flask import Flask, Response, jsonify, request
from PIL import Image, ImageChops
from werkzeug.exceptions import RequestEntityTooLarge


DEFAULT_W = int(os.environ.get("DEFAULT_WIDTH", "1600"))
DEFAULT_FILL = float(os.environ.get("DEFAULT_FILL", "0.86"))
MAX_W = 3000
MAX_PDF_BYTES = int(os.environ.get("MAX_PDF_BYTES", str(25 * 1024 * 1024)))
PROBE_W = 800
BLEED_PT = 1.0

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_PDF_BYTES


def _render(page, scale, crop, transparent):
    bitmap = page.render(
        scale=scale,
        crop=crop,
        draw_annots=False,
        fill_color=(0, 0, 0, 0) if transparent else (255, 255, 255, 255),
    )
    return bitmap.to_pil()


def _content_bbox_pt(img, page_w, page_h, transparent):
    """Return PDFium crop margins in points, or None for an empty page."""
    if transparent and img.mode == "RGBA":
        bbox = img.getchannel("A").getbbox()
    else:
        rgb = img.convert("RGB")
        white = Image.new("RGB", rgb.size, (255, 255, 255))
        bbox = ImageChops.difference(rgb, white).getbbox()
    if not bbox:
        return None

    sx = page_w / float(img.width)
    sy = page_h / float(img.height)
    left = max(0.0, bbox[0] * sx - BLEED_PT)
    top = max(0.0, bbox[1] * sy - BLEED_PT)
    right = max(0.0, page_w - bbox[2] * sx - BLEED_PT)
    bottom = max(0.0, page_h - bbox[3] * sy - BLEED_PT)

    if page_w - left - right < 8 or page_h - top - bottom < 8:
        return None
    return (left, bottom, right, top)


def rasterize_pdf(pdf_bytes, canvas_w, fill, square, transparent):
    doc = pdfium.PdfDocument(pdf_bytes)
    pages = len(doc)
    if pages == 0:
        raise ValueError("PDF sayfa icermiyor")

    page = doc[0]
    page_w, page_h = page.get_size()
    if page_w <= 0 or page_h <= 0:
        raise ValueError("Gecersiz sayfa boyutu")

    if not square:
        scale = min(canvas_w / max(page_w, page_h), MAX_W / max(page_w, page_h))
        img = _render(page, scale, (0, 0, 0, 0), transparent)
        return img, pages, (round(page_w, 1), round(page_h, 1)), "page"

    probe = _render(page, PROBE_W / max(page_w, page_h), (0, 0, 0, 0), transparent)
    crop = _content_bbox_pt(probe, page_w, page_h, transparent)
    if crop is None:
        crop = (0, 0, 0, 0)
    content_w = page_w - crop[0] - crop[2]
    content_h = page_h - crop[3] - crop[1]

    target_long = canvas_w * fill
    scale = min(target_long / max(content_w, content_h), MAX_W / max(content_w, content_h))
    content = _render(page, scale, crop, transparent)

    mode = "RGBA" if transparent else "RGB"
    background = (0, 0, 0, 0) if transparent else (255, 255, 255)
    canvas = Image.new(mode, (canvas_w, canvas_w), background)
    content = content.convert(mode)
    canvas.paste(content, ((canvas_w - content.width) // 2, (canvas_w - content.height) // 2))
    return canvas, pages, (round(page_w, 1), round(page_h, 1)), "%dx%d" % content.size


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok", "max_pdf_bytes": MAX_PDF_BYTES, "max_width": MAX_W})


@app.post("/")
def rasterize():
    pdf_bytes = request.get_data(cache=False)
    if not pdf_bytes:
        return Response(
            "govde bos - ham PDF baytlari bekleniyor",
            status=400,
            content_type="text/plain; charset=utf-8",
        )
    if pdf_bytes[:5] != b"%PDF-":
        return Response("govde PDF degil", status=400, content_type="text/plain; charset=utf-8")

    try:
        canvas_w = int(request.args.get("w", DEFAULT_W))
    except ValueError:
        canvas_w = DEFAULT_W
    canvas_w = max(256, min(canvas_w, MAX_W))

    try:
        fill = float(request.args.get("fill", DEFAULT_FILL))
    except ValueError:
        fill = DEFAULT_FILL
    fill = max(0.3, min(fill, 1.0))

    square = request.args.get("fit", "square") != "page"
    transparent = request.args.get("bg", "white") == "transparent"

    try:
        image, pages, source_points, content_px = rasterize_pdf(
            pdf_bytes, canvas_w, fill, square, transparent
        )
    except Exception as exc:
        return Response(
            "PDF acilamadi: %s" % exc,
            status=400,
            content_type="text/plain; charset=utf-8",
        )

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return Response(
        output.getvalue(),
        status=200,
        content_type="image/png",
        headers={
            "X-Pdf-Pages": str(pages),
            "X-Src-Points": "%sx%s" % source_points,
            "X-Content-Px": content_px,
            "X-Out-Px": "%sx%s" % (image.width, image.height),
        },
    )


@app.errorhandler(RequestEntityTooLarge)
def request_too_large(_error):
    return Response(
        "PDF 25 MiB sinirini asiyor",
        status=413,
        content_type="text/plain; charset=utf-8",
    )

