"""Приватні події: бачать лише ті, хто має посилання-запрошення."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from events.models import Attendance, Comment, Event, EventCover

from .conftest import attend

pytestmark = pytest.mark.django_db


@pytest.fixture
def private_event(make_event, author) -> Event:
    event = make_event(author=author, title="Таємна вечірка", visibility="private")
    EventCover.objects.create(event=event, data=b"RIFF....WEBP", width=1, height=1, sha256="0" * 64)
    event.has_cover = True
    event.save()
    return event


def invite_url(event: Event, token: str | None = None) -> str:
    return reverse("events:invite", args=[token or event.invite_token])


class TestHidden:
    def test_not_on_home_or_search(self, client: Client, private_event) -> None:
        home = client.get(reverse("events:home")).content.decode()
        search = client.get(reverse("events:home"), {"q": "Таємна"}).content.decode()
        assert "Таємна вечірка" not in home
        assert "Таємна вечірка" not in search

    @pytest.mark.parametrize("who", ["anonymous", "stranger"])
    def test_every_endpoint_is_404_without_invite(
        self, who, client: Client, stranger_client: Client, private_event
    ) -> None:
        c = client if who == "anonymous" else stranger_client
        pk = private_event.pk
        assert c.get(reverse("events:detail", args=[pk])).status_code == 404
        assert c.get(reverse("events:cover", args=[pk])).status_code == 404
        assert c.post(reverse("events:join", args=[pk])).status_code == 404
        assert c.post(reverse("events:add_comment", args=[pk]), {"body": "x"}).status_code == 404
        assert not Attendance.objects.exists()
        assert not Comment.objects.exists()

    def test_cannot_delete_comment_on_hidden_event(
        self, stranger_client: Client, stranger, private_event
    ) -> None:
        comment = Comment.objects.create(event=private_event, author=stranger, body="old")
        response = stranger_client.post(reverse("events:delete_comment", args=[comment.pk]))
        assert response.status_code == 404

    def test_wrong_or_huge_token(self, stranger_client: Client, private_event) -> None:
        assert stranger_client.get(invite_url(private_event, "wrong-token")).status_code == 404
        assert stranger_client.get(invite_url(private_event, "a" * 500)).status_code == 404

    def test_public_token_of_other_event_does_not_unlock(
        self, stranger_client: Client, private_event, make_event
    ) -> None:
        public = make_event()
        stranger_client.get(invite_url(public))
        detail = reverse("events:detail", args=[private_event.pk])
        assert stranger_client.get(detail).status_code == 404

    def test_not_in_profile_of_stranger(self, stranger_client: Client, private_event) -> None:
        page = stranger_client.get(reverse("events:profile")).content.decode()
        assert "Таємна вечірка" not in page


class TestInvite:
    def test_invite_grants_access_and_strips_token(
        self, stranger_client: Client, private_event
    ) -> None:
        response = stranger_client.get(invite_url(private_event))
        assert response.status_code == 302
        assert response["Location"] == private_event.get_absolute_url()
        assert private_event.invite_token not in response["Location"]
        assert stranger_client.get(response["Location"]).status_code == 200
        assert (
            stranger_client.get(reverse("events:cover", args=[private_event.pk])).status_code == 200
        )

    def test_anonymous_can_view_with_invite_then_join_after_login(
        self, client: Client, stranger, private_event
    ) -> None:
        client.get(invite_url(private_event))
        assert client.get(private_event.get_absolute_url()).status_code == 200
        client.force_login(stranger)  # вхід зберігає дані сесії
        client.post(reverse("events:join", args=[private_event.pk]))
        assert Attendance.objects.filter(user=stranger, event=private_event).exists()

    def test_invitee_can_join_and_comment(
        self, stranger_client: Client, stranger, private_event
    ) -> None:
        stranger_client.get(invite_url(private_event))
        stranger_client.post(reverse("events:join", args=[private_event.pk]))
        stranger_client.post(
            reverse("events:add_comment", args=[private_event.pk]), {"body": "Буду!"}
        )
        assert Attendance.objects.filter(user=stranger).exists()
        assert Comment.objects.filter(author=stranger).exists()
        profile = stranger_client.get(reverse("events:profile")).content.decode()
        assert "Таємна вечірка" in profile

    def test_regenerating_token_revokes_old_link(
        self, author_client: Client, stranger_client: Client, private_event
    ) -> None:
        old = private_event.invite_token
        stranger_client.get(invite_url(private_event))
        assert stranger_client.get(private_event.get_absolute_url()).status_code == 200

        response = author_client.post(reverse("events:regenerate_invite", args=[private_event.pk]))
        assert response.status_code == 302
        private_event.refresh_from_db()
        assert private_event.invite_token != old
        # стара сесійна «перепустка» й старе посилання більше не працюють
        assert stranger_client.get(private_event.get_absolute_url()).status_code == 404
        assert stranger_client.get(invite_url(private_event, old)).status_code == 404

    def test_attendee_keeps_access_after_regeneration(
        self, author_client: Client, stranger, private_event
    ) -> None:
        attend(private_event, stranger)
        author_client.post(reverse("events:regenerate_invite", args=[private_event.pk]))
        c = Client()
        c.force_login(stranger)
        assert c.get(private_event.get_absolute_url()).status_code == 200

    def test_only_author_can_regenerate(self, stranger_client: Client, private_event) -> None:
        url = reverse("events:regenerate_invite", args=[private_event.pk])
        stranger_client.get(invite_url(private_event))
        assert stranger_client.post(url).status_code == 404

    def test_author_sees_invite_link_but_invitee_does_not(
        self, author_client: Client, stranger_client: Client, private_event
    ) -> None:
        token = private_event.invite_token
        assert token in author_client.get(private_event.get_absolute_url()).content.decode()
        stranger_client.get(invite_url(private_event))
        assert token not in stranger_client.get(private_event.get_absolute_url()).content.decode()

    def test_invite_link_rate_limited(self, client: Client, private_event) -> None:
        for i in range(60):
            client.get(invite_url(private_event, f"guess{i}"))
        assert client.get(invite_url(private_event)).status_code == 429

    def test_session_invite_store_is_bounded(
        self, stranger_client: Client, make_event, author
    ) -> None:
        from django.core.cache import cache

        events = [make_event(author=author, visibility="private") for _ in range(105)]
        for event in events:
            cache.clear()  # rate limit тут не перевіряємо
            stranger_client.get(invite_url(event))
        invites = stranger_client.session["event_invites"]
        assert len(invites) == 100
        assert str(events[-1].pk) in invites
