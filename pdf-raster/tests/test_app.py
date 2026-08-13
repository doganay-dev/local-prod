import io

from PIL import Image, ImageChops

from app import MAX_W, app


def _simple_pdf():
    """Build a dependency-free one-page PDF containing a black rectangle."""
    stream = b"0 0 0 rg\n20 20 160 60 re f\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Resources << >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"endstream",
    ]
    result = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(result))
        result.extend(b"%d 0 obj\n" % index + obj + b"\nendobj\n")
    xref = len(result)
    result.extend(b"xref\n0 %d\n" % (len(objects) + 1))
    result.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        result.extend(b"%010d 00000 n \n" % offset)
    result.extend(
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objects) + 1, xref)
    )
    return bytes(result)


def test_healthz_reports_limits():
    response = app.test_client().get("/healthz")
    assert response.status_code == 200
    assert response.json == {
        "status": "ok",
        "max_pdf_bytes": 25 * 1024 * 1024,
        "max_width": MAX_W,
    }


def test_rejects_empty_and_non_pdf_bodies():
    client = app.test_client()
    assert client.post("/").status_code == 400
    assert client.post("/", data=b"not a PDF").status_code == 400


def test_rejects_body_over_configured_limit():
    original_limit = app.config["MAX_CONTENT_LENGTH"]
    app.config["MAX_CONTENT_LENGTH"] = 10
    try:
        response = app.test_client().post("/", data=b"%PDF-" + (b"x" * 6))
        assert response.status_code == 413
    finally:
        app.config["MAX_CONTENT_LENGTH"] = original_limit


def test_standard_fill_square_contract_and_default_white_background():
    response = app.test_client().post("/?w=512&fill=0.60", data=_simple_pdf())
    assert response.status_code == 200
    assert response.content_type == "image/png"
    assert response.headers["X-Pdf-Pages"] == "1"
    assert response.headers["X-Out-Px"] == "512x512"

    image = Image.open(io.BytesIO(response.data)).convert("RGB")
    assert image.size == (512, 512)
    assert image.getpixel((0, 0)) == (255, 255, 255)
    non_white = ImageChops.difference(image, Image.new("RGB", image.size, "white")).getbbox()
    assert non_white is not None
    assert max(non_white[2] - non_white[0], non_white[3] - non_white[1]) <= 315


def test_high_fill_defaults_to_1600_square():
    response = app.test_client().post("/", data=_simple_pdf())
    assert response.status_code == 200
    assert response.headers["X-Out-Px"] == "1600x1600"
    image = Image.open(io.BytesIO(response.data)).convert("RGB")
    non_white = ImageChops.difference(image, Image.new("RGB", image.size, "white")).getbbox()
    assert non_white is not None
    longest = max(non_white[2] - non_white[0], non_white[3] - non_white[1])
    assert 1300 <= longest <= 1390


def test_page_fit_preserves_page_aspect_ratio():
    response = app.test_client().post("/?w=512&fit=page", data=_simple_pdf())
    assert response.status_code == 200
    image = Image.open(io.BytesIO(response.data))
    assert image.size == (512, 256)
    assert response.headers["X-Content-Px"] == "page"


def test_width_and_fill_are_clamped():
    response = app.test_client().post("/?w=99999&fill=5", data=_simple_pdf())
    assert response.status_code == 200
    assert response.headers["X-Out-Px"] == f"{MAX_W}x{MAX_W}"
