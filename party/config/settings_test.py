"""Налаштування для автотестів (pytest)."""

from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("DJANGO_DEBUG", "0")

from config.settings import *  # noqa: F403
from config.settings import BASE_DIR, DATABASES

ALLOWED_HOSTS = ["testserver", "localhost"]
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Швидкий хешер лише для тестів — продакшн використовує Argon2.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "tusovka-tests",
    }
}

if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    # Файлова тестова БД, щоб тест на паралельне бронювання працював з різних потоків.
    DATABASES["default"]["TEST"] = {"NAME": str(BASE_DIR / ".pytest-db.sqlite3")}
