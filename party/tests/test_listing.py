"""Головна сторінка, пошук, профіль."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from .conftest import attend

pytestmark = pytest.mark.django_db
HOME = reverse("events:home")


def test_home_lists_only_upcoming_public(client: Client, make_event) -> None:
    make_event(title="Майбутня публічна")
    make_event(title="Минула подія", starts_at=timezone.now() - timedelta(hours=1))
    make_event(title="Приватна подія", visibility="private")
    page = client.get(HOME).content.decode()
    assert "Майбутня публічна" in page
    assert "Минула подія" not in page
    assert "Приватна подія" not in page


def test_home_sorted_by_date(client: Client, make_event) -> None:
    make_event(title="Пізніше", starts_at=timezone.now() + timedelta(days=10))
    make_event(title="Раніше", starts_at=timezone.now() + timedelta(days=1))
    page = client.get(HOME).content.decode()
    assert page.index("Раніше") < page.index("Пізніше")


def test_seat_counter_on_cards(client: Client, make_event, make_user) -> None:
    full = make_event(title="Повна", capacity=1)
    attend(full, make_user())
    open_event = make_event(title="Вільна", capacity=5)
    attend(open_event, make_user())
    page = client.get(HOME).content.decode()
    assert "Вільно 4 з 5" in page
    assert "Місць немає" in page


@pytest.mark.parametrize("query", ["тусовка", "ТУСОВКА", "  Тусовка  ", "сов"])
def test_search_is_case_insensitive_for_cyrillic(client: Client, make_event, query: str):
    make_event(title="Велика Тусовка")
    make_event(title="Інша подія")
    page = client.get(HOME, {"q": query}).content.decode()
    assert "Велика Тусовка" in page
    assert "Інша подія" not in page


def test_search_no_results(client: Client, make_event) -> None:
    make_event(title="Йога")
    page = client.get(HOME, {"q": "покер"}).content.decode()
    assert "Нічого не знайдено" in page


def test_search_wildcards_are_literal(client: Client, make_event) -> None:
    make_event(title="Звичайна")
    for q in ["%", "_", "%%", "\\"]:
        assert "Звичайна" not in client.get(HOME, {"q": q}).content.decode()


def test_search_query_too_long(client: Client) -> None:
    assert client.get(HOME, {"q": "x" * 1000}).status_code == 200


def test_pagination(client: Client, make_event) -> None:
    for i in range(15):
        make_event(title=f"Подія-{i:02d}", starts_at=timezone.now() + timedelta(days=i + 1))
    first = client.get(HOME).content.decode()
    second = client.get(HOME, {"page": 2}).content.decode()
    assert "Подія-00" in first
    assert "Подія-12" not in first
    assert "Подія-12" in second
    assert client.get(HOME, {"page": "nonsense"}).status_code == 200
    assert client.get(HOME, {"page": 99999}).status_code == 200


def test_empty_home(client: Client) -> None:
    assert "Поки що немає майбутніх подій" in client.get(HOME).content.decode()


@settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(query=st.text(max_size=150))
def test_search_never_crashes(client: Client, query: str) -> None:
    """Property-based: будь-який рядок у пошуку дає 200, а не 500."""
    query = query.replace("\x00", "")
    assert client.get(HOME, {"q": query}).status_code == 200


class TestProfile:
    def test_requires_login(self, client: Client) -> None:
        response = client.get(reverse("events:profile"))
        assert response.status_code == 302

    def test_shows_created_and_attending(
        self, stranger_client: Client, stranger, make_event
    ) -> None:
        make_event(author=stranger, title="Моя подія")
        joined = make_event(title="Йду сюди")
        attend(joined, stranger)
        past = make_event(title="Була колись", starts_at=timezone.now() - timedelta(days=3))
        attend(past, stranger)
        make_event(title="Чужа подія")
        page = stranger_client.get(reverse("events:profile")).content.decode()
        assert "Моя подія" in page
        assert "Йду сюди" in page
        assert "Була колись" in page
        assert "Запис закрито" in page
        assert "Чужа подія" not in page
