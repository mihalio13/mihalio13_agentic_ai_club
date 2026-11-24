"""Product quality: немає тупикових сценаріїв і «білих» сторінок."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.contrib.auth import get_user
from django.core import mail
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from events.models import Attendance, RemovedParticipant

from .conftest import PASSWORD, attend

pytestmark = pytest.mark.django_db

RESET = reverse("accounts:password_reset")
NEW_PASSWORD = "Fresh-Start-Pass-2026"


def reset_link_from_mail() -> str:
    body = str(mail.outbox[-1].body)
    match = re.search(r"https?://[^/\s]+(/accounts/password/reset/[^\s]+/)", body)
    assert match, body
    return match.group(1)


class TestPasswordReset:
    def test_login_page_links_to_reset(self, client: Client) -> None:
        page = client.get(reverse("accounts:login")).content.decode()
        assert RESET in page
        assert "Забули пароль?" in page

    def test_full_reset_flow(self, client: Client, make_user) -> None:
        user = make_user(email="lost@example.com")
        response = client.post(RESET, {"email": "LOST@example.com"})
        assert response.status_code == 302
        assert response["Location"] == reverse("accounts:password_reset_done")
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["lost@example.com"]
        assert "відновлення пароля" in mail.outbox[0].subject

        link = reset_link_from_mail()
        response = client.get(link, follow=True)
        assert "Новий пароль" in response.content.decode()
        set_password_url = response.redirect_chain[-1][0]
        response = client.post(
            set_password_url, {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD}
        )
        assert response["Location"] == reverse("accounts:password_reset_complete")
        user.refresh_from_db()
        assert user.check_password(NEW_PASSWORD)
        assert not user.check_password(PASSWORD)
        # посилання одноразове
        assert "Посилання недійсне" in client.get(link, follow=True).content.decode()

    def test_unknown_email_looks_the_same_and_sends_nothing(self, client: Client) -> None:
        response = client.post(RESET, {"email": "ghost@example.com"})
        assert response.status_code == 302
        assert response["Location"] == reverse("accounts:password_reset_done")
        assert mail.outbox == []

    def test_weak_new_password_rejected(self, client: Client, make_user) -> None:
        user = make_user(email="lost@example.com")
        client.post(RESET, {"email": "lost@example.com"})
        response = client.get(reset_link_from_mail(), follow=True)
        set_password_url = response.redirect_chain[-1][0]
        response = client.post(set_password_url, {"new_password1": "123", "new_password2": "123"})
        assert response.status_code == 200
        user.refresh_from_db()
        assert user.check_password(PASSWORD)

    def test_forged_token_rejected(self, client: Client, make_user) -> None:
        make_user(email="victim@example.com")
        url = reverse("accounts:password_reset_confirm", args=["MQ", "forged-token"])
        assert "Посилання недійсне" in client.get(url, follow=True).content.decode()

    def test_reset_rate_limited_per_email(self, client: Client, make_user) -> None:
        make_user(email="target@example.com")
        for _ in range(3):
            client.post(RESET, {"email": "target@example.com"})
        assert client.post(RESET, {"email": "target@example.com"}).status_code == 429
        assert len(mail.outbox) == 3

    def test_reset_logs_out_other_sessions(self, client: Client, make_user) -> None:
        user = make_user(email="lost@example.com")
        other = Client()
        other.force_login(user)
        client.post(RESET, {"email": "lost@example.com"})
        response = client.get(reset_link_from_mail(), follow=True)
        client.post(
            response.redirect_chain[-1][0],
            {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD},
        )
        assert not get_user(other).is_authenticated

    def test_pages_render(self, client: Client) -> None:
        assert client.get(RESET).status_code == 200
        assert client.get(reverse("accounts:password_reset_done")).status_code == 200
        assert client.get(reverse("accounts:password_reset_complete")).status_code == 200


class TestNoBlankPages:
    @pytest.mark.parametrize("action", ["join", "leave", "add_comment", "regenerate_invite"])
    def test_get_on_action_url_shows_helpful_page(
        self, stranger_client: Client, make_event, action
    ):
        event = make_event()
        response = stranger_client.get(reverse(f"events:{action}", args=[event.pk]))
        assert response.status_code == 405
        html = response.content.decode()
        assert "не можна відкрити напряму" in html
        assert f'href="/events/{event.pk}/"' in html
        assert "POST" in response["Allow"]

    def test_405_outside_events_links_home(self, client: Client) -> None:
        response = client.get(reverse("accounts:logout"))
        assert response.status_code == 405
        assert "Повернутися до події" not in response.content.decode()
        assert "На головну" in response.content.decode()


class TestRemovedParticipant:
    def test_removed_cannot_rejoin(
        self, author_client: Client, stranger_client: Client, stranger, author, make_event
    ) -> None:
        event = make_event(author=author)
        attend(event, stranger)
        author_client.post(reverse("events:remove_participant", args=[event.pk, stranger.pk]))
        assert RemovedParticipant.objects.filter(event=event, user=stranger).exists()

        stranger_client.post(reverse("events:join", args=[event.pk]))
        assert not Attendance.objects.filter(user=stranger).exists()
        page = stranger_client.get(event.get_absolute_url()).content.decode()
        assert "прибрав вас" in page
        assert ">Іду<" not in page

        author_page = author_client.get(event.get_absolute_url()).content.decode()
        assert "Прибрані (1)" in author_page

    def test_author_can_restore(
        self, author_client: Client, stranger_client: Client, stranger, author, make_event
    ) -> None:
        event = make_event(author=author)
        attend(event, stranger)
        author_client.post(reverse("events:remove_participant", args=[event.pk, stranger.pk]))
        author_client.post(reverse("events:restore_participant", args=[event.pk, stranger.pk]))
        stranger_client.post(reverse("events:join", args=[event.pk]))
        assert Attendance.objects.filter(user=stranger, event=event).exists()

    def test_only_author_can_restore(
        self, stranger_client: Client, stranger, make_event, make_user
    ) -> None:
        event = make_event()
        RemovedParticipant.objects.create(event=event, user=stranger)
        url = reverse("events:restore_participant", args=[event.pk, stranger.pk])
        assert stranger_client.post(url).status_code == 404
        assert RemovedParticipant.objects.filter(user=stranger).exists()

    def test_removing_non_participant_creates_no_ban(
        self, author_client: Client, author, make_event, make_user
    ) -> None:
        event = make_event(author=author)
        bystander = make_user()
        author_client.post(reverse("events:remove_participant", args=[event.pk, bystander.pk]))
        author_client.post(reverse("events:remove_participant", args=[event.pk, 999999]))
        assert not RemovedParticipant.objects.exists()

    def test_service_restore_checks_author(self, stranger, make_event) -> None:
        from events import services

        with pytest.raises(services.EventActionError):
            services.restore_participant(make_event().pk, stranger, stranger.pk)


class TestStartedEventWording:
    def test_just_started_is_not_called_finished(self, stranger_client: Client, make_event):
        event = make_event(starts_at=timezone.now() - timedelta(minutes=5))
        page = stranger_client.get(event.get_absolute_url()).content.decode()
        assert "Уже почалася" in page
        assert "запис закрито" in page
        assert "вже відбулася" not in page

    def test_old_event_is_past(self, client: Client, make_event) -> None:
        event = make_event(starts_at=timezone.now() - timedelta(days=2))
        page = client.get(event.get_absolute_url()).content.decode()
        assert "Минула подія" in page
        assert "Подія вже відбулася." in page


def test_card_links_are_named_by_event_title(client: Client, make_event) -> None:
    make_event(title="Вечір джазу")
    html = client.get(reverse("events:home")).content.decode()
    assert re.search(r'<a class="ev-card-link" href="/events/\d+/">Вечір джазу</a>', html)
    assert "Відкрити подію:" not in html


def test_profile_lists_upcoming_first_then_recent_past(
    stranger_client: Client, stranger, make_event
) -> None:
    now = timezone.now()
    make_event(author=stranger, title="Далеке майбутнє", starts_at=now + timedelta(days=60))
    make_event(author=stranger, title="Скоро", starts_at=now + timedelta(days=1))
    make_event(author=stranger, title="Давно минула", starts_at=now - timedelta(days=60))
    make_event(author=stranger, title="Нещодавно минула", starts_at=now - timedelta(days=1))
    html = stranger_client.get(reverse("events:profile")).content.decode()
    section = html.split('id="created-heading"', 1)[1]
    order = [
        section.index(t) for t in ["Скоро", "Далеке майбутнє", "Нещодавно минула", "Давно минула"]
    ]
    assert order == sorted(order)
