"""Безпечна обробка завантажених обкладинок.

Файл ніколи не зберігається «як є»: ми перевіряємо формат за вмістом (а не за
розширенням чи Content-Type), відсікаємо «бомби декомпресії», знімаємо EXIF
(геолокація з телефона!) і перекодовуємо в WebP. Тому SVG з JavaScript,
HTML-поліглоти та інші трюки не доходять до браузера.
"""

from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
MAX_PIXELS = 40_000_000  # ~ 8000x5000
MAX_SIDE = 1600
WEBP_QUALITY = 82


class InvalidImageError(ValueError):
    pass


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    width: int
    height: int
    sha256: str
    content_type: str = "image/webp"


def _read_limited(upload: UploadedFile[bytes]) -> bytes:
    limit: int = settings.MAX_COVER_UPLOAD_BYTES
    if upload.size is not None and upload.size > limit:
        raise InvalidImageError("Файл завеликий: максимум 5 МБ.")
    upload.seek(0)
    raw = bytes(upload.read(limit + 1))
    if len(raw) > limit:
        raise InvalidImageError("Файл завеликий: максимум 5 МБ.")
    if not raw:
        raise InvalidImageError("Файл порожній.")
    return raw


def process_cover(upload: UploadedFile[bytes]) -> ProcessedImage:
    raw = _read_limited(upload)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as probe:
                if probe.format not in ALLOWED_FORMATS:
                    raise InvalidImageError("Підтримуються лише JPEG, PNG та WebP.")
                width, height = probe.size
                if width < 1 or height < 1 or width * height > MAX_PIXELS:
                    raise InvalidImageError("Зображення має завелику роздільну здатність.")
                probe.verify()

            with Image.open(io.BytesIO(raw)) as source:
                source.seek(0)  # для анімацій беремо перший кадр
                image = ImageOps.exif_transpose(source) or source
                image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
                has_alpha = image.mode in ("RGBA", "LA") or (
                    image.mode == "P" and "transparency" in image.info
                )
                image = image.convert("RGBA" if has_alpha else "RGB")
                out = io.BytesIO()
                # Без exif=/icc_profile= — метадані не переносяться.
                image.save(out, format="WEBP", quality=WEBP_QUALITY, method=4)
                final_width, final_height = image.size
    except InvalidImageError:
        raise
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        ValueError,
        EOFError,
    ) as exc:
        raise InvalidImageError("Не вдалося прочитати зображення. Оберіть інший файл.") from exc

    data = out.getvalue()
    return ProcessedImage(
        data=data,
        width=final_width,
        height=final_height,
        sha256=hashlib.sha256(data).hexdigest(),
    )
