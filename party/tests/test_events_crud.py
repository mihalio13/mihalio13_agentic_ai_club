"""Створення, редагування, видалення подій і перевірка прав автора (IDOR)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from events.models import Attendance, Comment, Event, EventCover

from .conftest import attend, future_local, image_bytes, past_local, upload

pytestmark = pytest.mark.django_db

CREATE = reverse("events:create")


def event_data(**overrides):
    data = {
        "title": "Настолки в п'ятницю",
        "description": "Беріть друзів",
        "starts_at": future_local(),
        "capacity": "12",
        "visibility": "public",
    }
    data.update(overrides)
    return data


class TestCreate:
    def test_requires_login(self, client: Client) -> None:
        response = client.post(CREATE, event_data())
        assert response.status_code == 302
        assert reverse("accounts:login") in response["Location"]
        assert not Event.objects.exists()

    def test_create_public_event(self, author_client: Client, author) -> None:
        response = author_client.post(CREATE, event_data())
        event = Event.objects.get()
        assert response.status_code == 302
        assert response["Location"] == event.get_absolute_url()
        assert event.author == author
        assert event.capacity == 12
        assert len(event.invite_token) >= 40

    def test_create_with_cover(self, author_client: Client) -> None:
        data = event_data(cover=upload(image_bytes("PNG")))
        assert author_client.post(CREATE, data).status_code == 302
        event = Event.objects.get()
        assert event.has_cover
        assert EventCover.objects.get(event=event).content_type == "image/webp"

    def test_author_cannot_be_spoofed(self, author_client: Client, author, stranger) -> None:
        author_client.post(CREATE, event_data(author=stranger.pk, invite_token="x" * 43))
        event = Event.objects.get()
        assert event.author == author
        assert event.invite_token != "x" * 43

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("title", ""),
            ("title", "   "),
            ("title", "x" * 121),
            ("capacity", "0"),
            ("capacity", "-5"),
            ("capacity", "10001"),
            ("capacity", "abc"),
            ("capacity", "1.5"),
            ("starts_at", "not-a-date"),
            ("starts_at", ""),
            ("visibility", "secret"),
            ("description", "x" * 5001),
        ],
    )
    def test_invalid_input_rejected(self, author_client: Client, field: str, value: str) -> None:
        response = author_client.post(CREATE, event_data(**{field: value}))
        assert response.status_code == 200
        assert not Event.objects.exists()

    def test_past_date_rejected(self, author_client: Client) -> None:
        response = author_client.post(CREATE, event_data(starts_at=past_local()))
        assert "в майбутньому" in response.content.decode()
        assert not Event.objects.exists()

    def test_too_far_future_rejected(self, author_client: Client) -> None:
        far = (timezone.localtime() + timedelta(days=365 * 6)).strftime("%Y-%m-%dT%H:%M")
        author_client.post(CREATE, event_data(starts_at=far))
        assert not Event.objects.exists()

    def test_title_whitespace_normalized(self, author_client: Client) -> None:
        author_client.post(CREATE, event_data(title="  Багато    пробілів  "))
        assert Event.objects.get().title == "Багато пробілів"

    def test_form_page_renders(self, author_client: Client) -> None:
        assert author_client.get(CREATE).status_code == 200


class TestEdit:
    def test_author_can_edit(self, author_client: Client, author, make_event) -> None:
        event = make_event(author=author)
        url = reverse("events:edit", args=[event.pk])
        assert author_client.get(url).status_code == 200
        response = author_client.post(url, event_data(title="Нова назва"))
        assert response.status_code == 302
        event.refresh_from_db()
        assert event.title == "Нова назва"
        assert event.title_search == "нова назва"

    def test_other_user_gets_404_on_edit(self, stranger_client: Client, author, make_event) -> None:
        event = make_event(author=author, title="Оригінал")
        url = reverse("events:edit", args=[event.pk])
        assert stranger_client.get(url).status_code == 404
        assert stranger_client.post(url, event_data(title="Зламано")).status_code == 404
        event.refresh_from_db()
        assert event.title == "Оригінал"

    def test_anonymous_cannot_edit(self, client: Client, make_event) -> None:
        event = make_event()
        response = client.post(reverse("events:edit", args=[event.pk]), event_data())
        assert response.status_code == 302

    def test_capacity_cannot_drop_below_attendees(
        self, author_client: Client, author, make_event, make_user
    ) -> None:
        event = make_event(author=author, capacity=5)
        for _ in range(3):
            attend(event, make_user())
        url = reverse("events:edit", args=[event.pk])
        response = author_client.post(url, event_data(capacity="2"))
        assert response.status_code == 200
        assert "не може бути менше" in response.content.decode()
        event.refresh_from_db()
        assert event.capacity == 5
        assert author_client.post(url, event_data(capacity="3")).status_code == 302

    def test_past_event_editable_without_changing_date(
        self, author_client: Client, author, make_event
    ) -> None:
        start = timezone.now() - timedelta(days=2)
        event = make_event(author=author, starts_at=start.replace(second=0, microsecond=0))
        local = timezone.localtime(event.starts_at).strftime("%Y-%m-%dT%H:%M")
        url = reverse("events:edit", args=[event.pk])
        response = author_client.post(url, event_data(starts_at=local, title="Фотозвіт"))
        assert response.status_code == 302
        event.refresh_from_db()
        assert event.title == "Фотозвіт"

    def test_replace_and_remove_cover(self, author_client: Client, author, make_event) -> None:
        event = make_event(author=author)
        url = reverse("events:edit", args=[event.pk])
        author_client.post(url, event_data(cover=upload(image_bytes("JPEG"), "a.jpg")))
        event.refresh_from_db()
        first_version = event.cover_version
        assert event.has_cover
        author_client.post(url, event_data(cover=upload(image_bytes("PNG", (90, 30)))))
        event.refresh_from_db()
        assert event.cover_version != first_version
        assert author_client.get(url).status_code == 200  # форма з чекбоксом «прибрати»
        author_client.post(url, event_data(remove_cover="on"))
        event.refresh_from_db()
        assert not event.has_cover
        assert not EventCover.objects.filter(event=event).exists()

    def test_make_private_hides_from_home(self, author_client: Client, author, make_event) -> None:
        event = make_event(author=author, title="Стане приватною")
        author_client.post(
            reverse("events:edit", args=[event.pk]),
            event_data(title="Стане приватною", visibility="private"),
        )
        assert "Стане приватною" not in Client().get(reverse("events:home")).content.decode()


class TestDelete:
    def test_get_shows_confirmation_and_does_not_delete(
        self, author_client: Client, author, make_event
    ) -> None:
        event = make_event(author=author)
        response = author_client.get(reverse("events:delete", args=[event.pk]))
        assert response.status_code == 200
        assert Event.objects.filter(pk=event.pk).exists()

    def test_author_deletes_with_cascade(
        self, author_client: Client, author, make_event, stranger
    ) -> None:
        event = make_event(author=author)
        attend(event, stranger)
        Comment.objects.create(event=event, author=stranger, body="hi")
        response = author_client.post(reverse("events:delete", args=[event.pk]))
        assert response.status_code == 302
        assert not Event.objects.exists()
        assert not Attendance.objects.exists()
        assert not Comment.objects.exists()

    def test_other_user_cannot_delete(self, stranger_client: Client, make_event) -> None:
        event = make_event()
        assert stranger_client.post(reverse("events:delete", args=[event.pk])).status_code == 404
        assert Event.objects.filter(pk=event.pk).exists()

    def test_delete_requires_csrf(self, author, make_event) -> None:
        event = make_event(author=author)
        client = Client(enforce_csrf_checks=True)
        client.force_login(author)
        assert client.post(reverse("events:delete", args=[event.pk])).status_code == 403
        assert Event.objects.filter(pk=event.pk).exists()


def test_model_str_and_defaults(make_event, stranger) -> None:
    event = make_event(title="Назва")
    assert str(event) == "Назва"
    a = attend(event, stranger)
    assert "Назва" in str(a)
    c = Comment.objects.create(event=event, author=stranger, body="Текст коментаря")
    assert "Текст" in str(c)
    other = make_event()
    assert event.invite_token != other.invite_token


def test_db_constraints_protect_capacity(make_event) -> None:
    from django.db import IntegrityError, transaction

    event = make_event()
    with pytest.raises(IntegrityError), transaction.atomic():
        Event.objects.filter(pk=event.pk).update(capacity=0)
