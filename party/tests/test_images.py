"""Завантаження обкладинок: лише справжні картинки, без метаданих і «бомб»."""

from __future__ import annotations

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from events.images import MAX_SIDE, InvalidImageError, process_cover

from .conftest import image_bytes, upload


def test_png_is_reencoded_to_webp() -> None:
    result = process_cover(upload(image_bytes("PNG")))
    assert result.content_type == "image/webp"
    with Image.open(io.BytesIO(result.data)) as img:
        assert img.format == "WEBP"
        assert img.size == (64, 48)


@pytest.mark.parametrize("fmt", ["JPEG", "WEBP"])
def test_other_allowed_formats(fmt: str) -> None:
    assert process_cover(upload(image_bytes(fmt), name=f"a.{fmt.lower()}")).width == 64


def test_large_image_is_downscaled() -> None:
    result = process_cover(upload(image_bytes("JPEG", (4000, 1000)), name="big.jpg"))
    assert result.width == MAX_SIDE
    assert result.height == 400


def test_exif_metadata_is_stripped() -> None:
    exif = Image.Exif()
    exif[0x010F] = "SpyCam"  # Make
    exif[0x8825] = {2: (50.0, 27.0, 0.0)}  # GPS
    data = image_bytes("JPEG", exif=exif.tobytes())
    with Image.open(io.BytesIO(data)) as original:
        assert original.getexif()
    result = process_cover(upload(data, name="gps.jpg"))
    with Image.open(io.BytesIO(result.data)) as cleaned:
        assert not cleaned.getexif()
        assert "exif" not in cleaned.info


@pytest.mark.parametrize(
    ("data", "name"),
    [
        (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "x.svg"),
        (b"<html><script>alert(1)</script></html>", "x.png"),
        (b"GIF89a" + b"\x00" * 100, "x.gif"),
        (b"\x89PNG\r\n\x1a\n" + b"truncated garbage", "broken.png"),
        (b"", "empty.png"),
    ],
)
def test_non_images_rejected(data: bytes, name: str) -> None:
    with pytest.raises(InvalidImageError):
        process_cover(SimpleUploadedFile(name, data, content_type="image/png"))


def test_gif_rejected_even_if_valid() -> None:
    with pytest.raises(InvalidImageError, match="JPEG, PNG"):
        process_cover(upload(image_bytes("GIF"), name="a.gif"))


def test_decompression_bomb_rejected() -> None:
    # 1-бітний PNG 10000x10000 важить кілька КБ, але в пам'яті — сотні МБ.
    buf = io.BytesIO()
    Image.new("1", (10_000, 10_000)).save(buf, format="PNG")
    assert len(buf.getvalue()) < 100_000
    with pytest.raises(InvalidImageError):
        process_cover(upload(buf.getvalue(), name="bomb.png"))


def test_file_over_limit_rejected(settings) -> None:
    settings.MAX_COVER_UPLOAD_BYTES = 1000
    with pytest.raises(InvalidImageError, match="5 МБ"):
        process_cover(upload(image_bytes("PNG", (300, 300)) + b"\x00" * 2000))


def test_file_over_limit_without_declared_size(settings) -> None:
    settings.MAX_COVER_UPLOAD_BYTES = 1000
    f = upload(b"\x00" * 2000)
    f.size = None
    with pytest.raises(InvalidImageError):
        process_cover(f)


def test_transparent_palette_png_keeps_alpha() -> None:
    img = Image.new("P", (10, 10))
    img.info["transparency"] = 0
    buf = io.BytesIO()
    img.save(buf, format="PNG", transparency=0)
    result = process_cover(upload(buf.getvalue()))
    with Image.open(io.BytesIO(result.data)) as out:
        assert out.mode == "RGBA"


@pytest.mark.django_db
def test_invalid_cover_shows_form_error(author_client) -> None:
    from django.urls import reverse

    from events.models import Event

    from .conftest import future_local

    response = author_client.post(
        reverse("events:create"),
        {
            "title": "Т",
            "starts_at": future_local(),
            "capacity": "5",
            "visibility": "public",
            "cover": SimpleUploadedFile("evil.svg", b"<svg onload=alert(1)>", "image/svg+xml"),
        },
    )
    assert response.status_code == 200
    assert "Не вдалося прочитати зображення" in response.content.decode()
    assert not Event.objects.exists()
