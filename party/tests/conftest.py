from __future__ import annotations

import io
import itertools
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone
from PIL import Image

from accounts.models import User
from events.models import Attendance, Event

PASSWORD = "Sup3r-Secret-Pass!"
_counter = itertools.count(1)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    cache.clear()


@pytest.fixture
def make_user(db: None) -> Callable[..., User]:
    def factory(email: str | None = None, name: str | None = None) -> User:
        n = next(_counter)
        return User.objects.create_user(
            email=email or f"user{n}@example.com",
            password=PASSWORD,
            display_name=name or f"Користувач {n}",
        )

    return factory


@pytest.fixture
def make_event(db: None, make_user: Callable[..., User]) -> Callable[..., Event]:
    def factory(author: User | None = None, **fields: Any) -> Event:
        data: dict[str, Any] = {
            "title": f"Подія {next(_counter)}",
            "description": "Опис",
            "starts_at": timezone.now() + timedelta(days=3),
            "capacity": 10,
            "visibility": Event.Visibility.PUBLIC,
        }
        data.update(fields)
        return Event.objects.create(author=author or make_user(), **data)

    return factory


@pytest.fixture
def author(make_user: Callable[..., User]) -> User:
    return make_user(email="author@example.com", name="Авторка")


@pytest.fixture
def stranger(make_user: Callable[..., User]) -> User:
    return make_user(email="stranger@example.com", name="Незнайомець")


def login(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


@pytest.fixture
def author_client(author: User) -> Client:
    return login(Client(), author)


@pytest.fixture
def stranger_client(stranger: User) -> Client:
    return login(Client(), stranger)


def attend(event: Event, user: User) -> Attendance:
    return Attendance.objects.create(event=event, user=user)


def image_bytes(fmt: str = "PNG", size: tuple[int, int] = (64, 48), **save: Any) -> bytes:
    buf = io.BytesIO()
    mode = "RGB" if fmt != "PNG" else "RGBA"
    Image.new(mode, size, (200, 80, 40)).save(buf, format=fmt, **save)
    return buf.getvalue()


def upload(data: bytes, name: str = "cover.png", content_type: str = "image/png") -> Any:
    return SimpleUploadedFile(name, data, content_type=content_type)


def future_local(days: int = 5) -> str:
    return timezone.localtime(timezone.now() + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")


def past_local(days: int = 1) -> str:
    return timezone.localtime(timezone.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")
