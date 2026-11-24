"""Запис на подію: ліміт місць, повторні натискання, минулі події, гонки."""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from django.db import close_old_connections
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from events import services
from events.models import Attendance

from .conftest import attend

pytestmark = pytest.mark.django_db


def join(client: Client, event):
    return client.post(reverse("events:join", args=[event.pk]))


def leave(client: Client, event):
    return client.post(reverse("events:leave", args=[event.pk]))


class TestJoinLeave:
    def test_join_and_counter(self, stranger_client: Client, stranger, make_event) -> None:
        event = make_event(capacity=3)
        assert join(stranger_client, event).status_code == 302
        assert Attendance.objects.filter(event=event, user=stranger).exists()
        page = stranger_client.get(event.get_absolute_url()).content.decode()
        assert "Вільно <strong>2</strong> з 3" in page
        assert "Ви йдете" in page

    def test_double_join_is_idempotent(self, stranger_client: Client, make_event) -> None:
        event = make_event(capacity=3)
        join(stranger_client, event)
        join(stranger_client, event)
        assert Attendance.objects.filter(event=event).count() == 1

    def test_full_event_rejects(self, stranger_client: Client, stranger, make_event, make_user):
        event = make_event(capacity=1)
        attend(event, make_user())
        response = join(stranger_client, event)
        assert response.status_code == 302
        assert not Attendance.objects.filter(user=stranger).exists()
        page = stranger_client.get(event.get_absolute_url()).content.decode()
        assert "вільних місць уже немає" in page

    def test_full_event_ui_states(self, client: Client, stranger_client, make_event, make_user):
        event = make_event(capacity=1)
        attend(event, make_user())
        for c in (client, stranger_client):
            page = c.get(event.get_absolute_url()).content.decode()
            assert "Місць немає" in page
            assert "Увійдіть, щоб записатися" not in page
            assert ">Іду<" not in page

    def test_author_cannot_take_seat(self, author_client: Client, author, make_event) -> None:
        event = make_event(author=author)
        join(author_client, event)
        assert not Attendance.objects.exists()

    def test_cannot_join_past_event(self, stranger_client: Client, make_event) -> None:
        event = make_event(starts_at=timezone.now() - timedelta(minutes=1))
        join(stranger_client, event)
        assert not Attendance.objects.exists()

    def test_leave_frees_seat(self, stranger_client: Client, stranger, make_event) -> None:
        event = make_event(capacity=1)
        attend(event, stranger)
        assert leave(stranger_client, event).status_code == 302
        assert not Attendance.objects.exists()

    def test_cannot_leave_after_start(self, stranger_client: Client, stranger, make_event):
        event = make_event(starts_at=timezone.now() + timedelta(days=1))
        attend(event, stranger)
        event.starts_at = timezone.now() - timedelta(hours=1)
        event.save()
        leave(stranger_client, event)
        assert Attendance.objects.filter(user=stranger).exists()

    def test_leave_when_not_attending_is_harmless(self, stranger_client: Client, make_event):
        event = make_event()
        assert leave(stranger_client, event).status_code == 302

    def test_get_not_allowed(self, stranger_client: Client, make_event) -> None:
        event = make_event()
        assert stranger_client.get(reverse("events:join", args=[event.pk])).status_code == 405
        assert not Attendance.objects.exists()

    def test_anonymous_redirected_to_login(self, client: Client, make_event) -> None:
        event = make_event()
        response = join(client, event)
        assert response.status_code == 302
        assert reverse("accounts:login") in response["Location"]
        assert not Attendance.objects.exists()
        assert leave(client, event).status_code == 302

    def test_join_nonexistent_event(self, stranger_client: Client) -> None:
        assert stranger_client.post(reverse("events:join", args=[999999])).status_code == 404

    def test_service_rejects_deleted_event(self, stranger) -> None:
        with pytest.raises(services.EventActionError):
            services.join_event(424242, stranger)

    def test_join_requires_csrf(self, stranger, make_event) -> None:
        event = make_event()
        client = Client(enforce_csrf_checks=True)
        client.force_login(stranger)
        assert join(client, event).status_code == 403
        assert not Attendance.objects.exists()


class TestParticipantsManagement:
    def test_author_sees_participants_others_do_not(
        self, author_client: Client, author, stranger_client: Client, stranger, make_event
    ) -> None:
        event = make_event(author=author)
        attend(event, stranger)
        author_page = author_client.get(event.get_absolute_url()).content.decode()
        assert 'id="participants"' in author_page
        assert "Незнайомець" in author_page
        stranger_page = stranger_client.get(event.get_absolute_url()).content.decode()
        assert 'id="participants"' not in stranger_page

    def test_participant_emails_never_exposed(
        self, author_client: Client, author, stranger, make_event
    ) -> None:
        event = make_event(author=author)
        attend(event, stranger)
        assert stranger.email not in author_client.get(event.get_absolute_url()).content.decode()

    def test_author_removes_participant(
        self, author_client: Client, author, stranger, make_event
    ) -> None:
        event = make_event(author=author)
        attend(event, stranger)
        url = reverse("events:remove_participant", args=[event.pk, stranger.pk])
        assert author_client.post(url).status_code == 302
        assert not Attendance.objects.exists()

    def test_non_author_cannot_remove(self, stranger_client: Client, make_user, make_event) -> None:
        event = make_event()
        victim = make_user()
        attend(event, victim)
        url = reverse("events:remove_participant", args=[event.pk, victim.pk])
        assert stranger_client.post(url).status_code == 404
        assert Attendance.objects.filter(user=victim).exists()

    def test_service_level_author_check(self, stranger, make_event, make_user) -> None:
        event = make_event()
        with pytest.raises(services.EventActionError):
            services.remove_participant(event.pk, stranger, make_user().pk)
        with pytest.raises(services.EventActionError):
            services.regenerate_invite(event.pk, stranger)


@pytest.mark.django_db(transaction=True)
def test_concurrent_joins_never_overbook(make_event, make_user) -> None:
    """20 користувачів одночасно тиснуть «Іду» на подію з 5 місцями."""
    event = make_event(capacity=5)
    users = [make_user() for _ in range(20)]
    barrier = threading.Barrier(len(users))
    errors: list[BaseException] = []

    def worker(user) -> None:
        try:
            barrier.wait()
            services.join_event(event.pk, user)
        except services.EventActionError:
            pass
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            close_old_connections()

    threads = [threading.Thread(target=worker, args=(u,)) for u in users]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert Attendance.objects.filter(event=event).count() == 5
