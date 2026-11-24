from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from events.models import Comment

pytestmark = pytest.mark.django_db


def post_comment(client: Client, event, body: str):
    return client.post(reverse("events:add_comment", args=[event.pk]), {"body": body})


class TestComments:
    def test_add_comment(self, stranger_client: Client, stranger, make_event) -> None:
        event = make_event()
        response = post_comment(stranger_client, event, "  Круто!  ")
        assert response.status_code == 302
        comment = Comment.objects.get()
        assert comment.body == "Круто!"
        assert comment.author == stranger

    @pytest.mark.parametrize("body", ["", "    ", "\n\n", "x" * 2001])
    def test_invalid_comment_rejected(self, stranger_client: Client, make_event, body) -> None:
        event = make_event()
        response = post_comment(stranger_client, event, body)
        assert response.status_code == 400
        assert not Comment.objects.exists()

    def test_anonymous_cannot_comment(self, client: Client, make_event) -> None:
        event = make_event()
        assert post_comment(client, event, "hi").status_code == 302
        assert not Comment.objects.exists()

    def test_xss_is_escaped(self, stranger_client: Client, make_event) -> None:
        event = make_event()
        payload = '<script>alert("xss")</script><img src=x onerror=alert(1)>'
        post_comment(stranger_client, event, payload)
        page = stranger_client.get(event.get_absolute_url()).content.decode()
        assert "<script>alert" not in page
        assert "<img src=x" not in page
        assert "&lt;script&gt;" in page

    def test_xss_in_event_title_and_description(self, client: Client, make_event) -> None:
        event = make_event(title="<b>bold</b>", description="<script>x()</script>")
        page = client.get(event.get_absolute_url()).content.decode()
        assert "<script>x()" not in page
        assert "<b>bold</b>" not in page
        home = client.get(reverse("events:home")).content.decode()
        assert "<b>bold</b>" not in home

    def test_comment_author_can_delete(self, stranger_client: Client, stranger, make_event):
        event = make_event()
        comment = Comment.objects.create(event=event, author=stranger, body="oops")
        url = reverse("events:delete_comment", args=[comment.pk])
        assert stranger_client.post(url).status_code == 302
        assert not Comment.objects.exists()

    def test_event_author_can_moderate(
        self, author_client: Client, author, stranger, make_event
    ) -> None:
        event = make_event(author=author)
        comment = Comment.objects.create(event=event, author=stranger, body="spam")
        author_client.post(reverse("events:delete_comment", args=[comment.pk]))
        assert not Comment.objects.exists()

    def test_others_cannot_delete(self, stranger_client: Client, make_user, make_event) -> None:
        event = make_event()
        comment = Comment.objects.create(event=event, author=make_user(), body="mine")
        url = reverse("events:delete_comment", args=[comment.pk])
        assert stranger_client.post(url).status_code == 404
        assert stranger_client.get(url).status_code == 405
        assert Comment.objects.exists()

    def test_comment_rate_limit(self, stranger_client: Client, make_event) -> None:
        event = make_event()
        for i in range(10):
            post_comment(stranger_client, event, f"msg {i}")
        assert post_comment(stranger_client, event, "one more").status_code == 429
        assert Comment.objects.count() == 10

    def test_comments_paginated(self, client: Client, make_event, stranger) -> None:
        event = make_event()
        Comment.objects.bulk_create(
            Comment(event=event, author=stranger, body=f"c{i}") for i in range(35)
        )
        page1 = client.get(event.get_absolute_url()).content.decode()
        page2 = client.get(event.get_absolute_url(), {"comments": 2}).content.decode()
        assert "Коментарі (35)" in page1
        assert "c34" in page1
        assert "c0<" in page2 or ">c0" in page2
        assert client.get(event.get_absolute_url(), {"comments": "999"}).status_code == 200
        assert client.get(event.get_absolute_url(), {"comments": "abc"}).status_code == 200
