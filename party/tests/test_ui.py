"""Інтерфейс: фільтри шаблонів, бейджі, демо-дані."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.test import Client
from django.urls import reverse
from hypothesis import given
from hypothesis import strategies as st

from accounts.models import User
from events.models import Event
from events.templatetags.ui import hue, initial, plural_uk

from .conftest import attend

FORMS = "подія,події,подій"


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (0, "подій"),
        (1, "подія"),
        (2, "події"),
        (4, "події"),
        (5, "подій"),
        (11, "подій"),
        (12, "подій"),
        (14, "подій"),
        (21, "подія"),
        (22, "події"),
        (111, "подій"),
        (101, "подія"),
    ],
)
def test_plural_uk(n: int, expected: str) -> None:
    assert plural_uk(n, FORMS) == expected


def test_plural_uk_bad_input() -> None:
    assert plural_uk("abc", FORMS) == "подій"
    assert plural_uk(1, "одна") == "одна"


@given(st.integers())
def test_hue_always_in_palette(value: int) -> None:
    assert 0 <= hue(value) < 8


def test_hue_and_initial_edge_cases() -> None:
    assert hue(None) == 0
    assert hue("x") == 0
    assert initial("  олена ") == "О"
    assert initial("") == "?"
    assert initial(None) == "?"


@pytest.mark.django_db
class TestCardsAndPages:
    def test_going_badge_only_for_attendee(
        self, stranger_client: Client, stranger, client: Client, make_event
    ) -> None:
        event = make_event(title="Пробіжка")
        attend(event, stranger)
        assert "Ви йдете" in stranger_client.get(reverse("events:home")).content.decode()
        assert "Ви йдете" not in client.get(reverse("events:home")).content.decode()

    def test_counter_pluralization_on_home(self, client: Client, make_event, make_user) -> None:
        event = make_event(capacity=10)
        for _ in range(2):
            attend(event, make_user())
        page = client.get(reverse("events:home")).content.decode()
        assert "2 учасники" in page
        assert "1 подія попереду" in page

    def test_featured_is_soonest_event_with_free_seats(
        self, client: Client, make_event, make_user
    ) -> None:
        from datetime import timedelta

        from django.utils import timezone

        full = make_event(
            title="Повна найближча", capacity=1, starts_at=timezone.now() + timedelta(hours=2)
        )
        attend(full, make_user())
        make_event(title="Вільна пізніша", starts_at=timezone.now() + timedelta(days=2))
        page = client.get(reverse("events:home")).content.decode()
        feature = page.split('class="hero-feature"', 1)[1].split("</aside>", 1)[0]
        assert "Вільна пізніша" in feature
        assert "Повна найближча" not in feature
        # під час пошуку блоку немає
        assert (
            "hero-feature"
            not in client.get(reverse("events:home"), {"q": "Вільна"}).content.decode()
        )

    def test_no_featured_when_everything_full(self, client: Client, make_event, make_user):
        event = make_event(capacity=1)
        attend(event, make_user())
        assert "hero-feature" not in client.get(reverse("events:home")).content.decode()

    def test_low_seats_warning_class(self, client: Client, make_event, make_user) -> None:
        event = make_event(capacity=3)
        attend(event, make_user())
        assert "seats-low" in client.get(reverse("events:home")).content.decode()

    def test_profile_stats(self, stranger_client: Client, stranger, make_event) -> None:
        make_event(author=stranger)
        attend(make_event(), stranger)
        page = stranger_client.get(reverse("events:profile")).content.decode()
        assert "1</strong> майбутня подія" in page
        assert "1</strong> створена" in page

    def test_pages_render_for_all_states(
        self, author_client: Client, author, stranger_client: Client, stranger, make_event
    ) -> None:
        private = make_event(author=author, visibility="private")
        attend(private, stranger)
        urls = [
            reverse("events:home"),
            reverse("events:create"),
            reverse("events:profile"),
            private.get_absolute_url(),
            reverse("events:edit", args=[private.pk]),
            reverse("events:delete", args=[private.pk]),
            reverse("accounts:password_change"),
        ]
        for url in urls:
            assert author_client.get(url).status_code == 200, url
        assert stranger_client.get(private.get_absolute_url()).status_code == 200


@pytest.mark.django_db
class TestSeedDemo:
    def test_refuses_in_production(self, settings) -> None:
        settings.DEBUG = False
        with pytest.raises(CommandError):
            call_command("seed_demo")
        assert not Event.objects.exists()

    def test_creates_and_is_idempotent(self, settings) -> None:
        settings.DEBUG = True
        call_command("seed_demo", stdout=StringIO())
        count = Event.objects.count()
        assert count >= 5
        assert Event.objects.filter(visibility="private").exists()
        demo = User.objects.filter(email__endswith="@demo.tusovka.invalid")
        assert all(not u.has_usable_password() for u in demo)

        out = StringIO()
        call_command("seed_demo", stdout=out)
        assert "вже є" in out.getvalue()
        assert Event.objects.count() == count

        call_command("seed_demo", "--reset", stdout=StringIO())
        assert Event.objects.count() == count

    def test_force_flag(self, settings) -> None:
        settings.DEBUG = False
        call_command("seed_demo", "--force", stdout=StringIO())
        assert Event.objects.exists()
