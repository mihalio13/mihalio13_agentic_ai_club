from __future__ import annotations

import pytest
from django.contrib.auth import get_user
from django.test import Client
from django.urls import reverse

from accounts.models import User

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db

REGISTER = reverse("accounts:register")
LOGIN = reverse("accounts:login")
LOGOUT = reverse("accounts:logout")


def register(client: Client, **overrides: str):
    data = {
        "email": "new@example.com",
        "display_name": "Оля",
        "password1": PASSWORD,
        "password2": PASSWORD,
    }
    data.update(overrides)
    return client.post(REGISTER, data)


class TestRegistration:
    def test_register_creates_user_logs_in_and_hashes_password(self, client: Client) -> None:
        response = register(client)
        assert response.status_code == 302
        user = User.objects.get(email="new@example.com")
        assert user.password != PASSWORD
        assert user.check_password(PASSWORD)
        assert get_user(client).is_authenticated

    def test_email_is_case_insensitive_unique(self, client: Client, make_user) -> None:
        make_user(email="taken@example.com")
        response = register(client, email="  TAKEN@Example.COM ")
        assert response.status_code == 200
        assert "уже існує" in response.content.decode()
        assert User.objects.filter(email="taken@example.com").count() == 1

    @pytest.mark.parametrize(
        "password", ["short1!", "1234567890123", "password1234", "new@example.com"]
    )
    def test_weak_passwords_rejected(self, client: Client, password: str) -> None:
        response = register(client, password1=password, password2=password)
        assert response.status_code == 200
        assert not User.objects.exists()

    def test_password_too_long_rejected(self, client: Client) -> None:
        long = "Aa1!" * 40
        response = register(client, password1=long, password2=long)
        assert response.status_code == 200
        assert not User.objects.exists()

    def test_password_mismatch(self, client: Client) -> None:
        response = register(client, password2=PASSWORD + "x")
        assert "не збігаються" in response.content.decode()
        assert not User.objects.exists()

    @pytest.mark.parametrize("email", ["", "not-an-email", "a@", "@b.com"])
    def test_invalid_email(self, client: Client, email: str) -> None:
        register(client, email=email)
        assert not User.objects.exists()

    def test_blank_display_name(self, client: Client) -> None:
        register(client, display_name="   ")
        assert not User.objects.exists()

    def test_cannot_escalate_privileges_via_extra_fields(self, client: Client) -> None:
        register(client, is_staff="on", is_superuser="on")
        user = User.objects.get()
        assert not user.is_staff
        assert not user.is_superuser

    def test_registration_rate_limited(self, client: Client) -> None:
        for i in range(10):
            register(client, email=f"bad{i}@example.com", password2="mismatch")
        response = register(client, email="final@example.com")
        assert response.status_code == 429
        assert not User.objects.filter(email="final@example.com").exists()


class TestLogin:
    def test_login_success(self, client: Client, make_user) -> None:
        make_user(email="me@example.com")
        response = client.post(LOGIN, {"email": "ME@example.com", "password": PASSWORD})
        assert response.status_code == 302
        assert get_user(client).is_authenticated

    def test_wrong_password_and_unknown_email_look_identical(
        self, client: Client, make_user
    ) -> None:
        make_user(email="me@example.com")
        wrong = client.post(LOGIN, {"email": "me@example.com", "password": "nope-nope-1"})
        unknown = client.post(LOGIN, {"email": "ghost@example.com", "password": "nope-nope-1"})
        assert wrong.status_code == unknown.status_code == 200
        assert "Невірний email або пароль" in wrong.content.decode()
        assert "Невірний email або пароль" in unknown.content.decode()
        assert not get_user(client).is_authenticated

    def test_inactive_user_cannot_login(self, client: Client, make_user) -> None:
        user = make_user(email="off@example.com")
        user.is_active = False
        user.save()
        client.post(LOGIN, {"email": "off@example.com", "password": PASSWORD})
        assert not get_user(client).is_authenticated

    def test_brute_force_on_one_account_is_blocked(self, client: Client, make_user) -> None:
        make_user(email="victim@example.com")
        for _ in range(8):
            client.post(LOGIN, {"email": "victim@example.com", "password": "wrong-pass-1"})
        # навіть правильний пароль після ліміту не допомагає — атакуючий нічого не дізнається
        response = client.post(LOGIN, {"email": "victim@example.com", "password": PASSWORD})
        assert response.status_code == 429
        assert not get_user(client).is_authenticated

    def test_spoofed_forwarded_for_does_not_bypass_ip_limit(self, client: Client, settings) -> None:
        settings.TRUSTED_PROXY_COUNT = 1
        for i in range(30):
            client.post(
                LOGIN,
                {"email": f"x{i}@example.com", "password": "wrong-pass-1"},
                HTTP_X_FORWARDED_FOR=f"10.0.0.{i}, 203.0.113.7",
            )
        response = client.post(
            LOGIN,
            {"email": "y@example.com", "password": "wrong-pass-1"},
            HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.7",
        )
        assert response.status_code == 429

    @pytest.mark.parametrize(
        "next_url",
        ["https://evil.example.com/", "//evil.example.com", "javascript:alert(1)", "/\\evil.com"],
    )
    def test_open_redirect_blocked(self, client: Client, make_user, next_url: str) -> None:
        make_user(email="me@example.com")
        response = client.post(
            LOGIN, {"email": "me@example.com", "password": PASSWORD, "next": next_url}
        )
        assert response.status_code == 302
        assert response["Location"] == reverse("events:home")

    def test_safe_next_is_followed(self, client: Client, make_user) -> None:
        make_user(email="me@example.com")
        response = client.post(
            LOGIN, {"email": "me@example.com", "password": PASSWORD, "next": "/profile/"}
        )
        assert response["Location"] == "/profile/"

    def test_session_id_rotates_on_login(self, client: Client, make_user) -> None:
        make_user(email="me@example.com")
        client.get(reverse("events:home"))
        session = client.session
        session["probe"] = 1
        session.save()
        before = client.cookies["sessionid"].value
        client.post(LOGIN, {"email": "me@example.com", "password": PASSWORD})
        assert client.cookies["sessionid"].value != before

    def test_logged_in_user_redirected_from_auth_pages(self, author_client: Client) -> None:
        assert author_client.get(LOGIN).status_code == 302
        assert author_client.get(REGISTER).status_code == 302


class TestLogout:
    def test_logout_requires_post(self, author_client: Client) -> None:
        assert author_client.get(LOGOUT).status_code == 405
        assert get_user(author_client).is_authenticated

    def test_logout(self, author_client: Client) -> None:
        response = author_client.post(LOGOUT)
        assert response.status_code == 302
        assert not get_user(author_client).is_authenticated

    def test_logout_requires_csrf(self, author) -> None:
        client = Client(enforce_csrf_checks=True)
        client.force_login(author)
        assert client.post(LOGOUT).status_code == 403
        assert get_user(client).is_authenticated


class TestPasswordChange:
    URL = reverse("accounts:password_change")

    def test_requires_login(self, client: Client) -> None:
        assert client.get(self.URL).status_code == 302

    def test_change_password_keeps_session(self, author_client: Client, author) -> None:
        new = "Brand-New-Pass-42"
        response = author_client.post(
            self.URL,
            {"old_password": PASSWORD, "new_password1": new, "new_password2": new},
        )
        assert response.status_code == 302
        author.refresh_from_db()
        assert author.check_password(new)
        assert author_client.get(reverse("events:profile")).status_code == 200

    def test_wrong_old_password(self, author_client: Client, author) -> None:
        new = "Brand-New-Pass-42"
        author_client.post(
            self.URL, {"old_password": "wrong", "new_password1": new, "new_password2": new}
        )
        author.refresh_from_db()
        assert author.check_password(PASSWORD)


def test_user_manager_rules(db) -> None:
    with pytest.raises(ValueError, match="Email"):
        User.objects.create_user(email="", password="x", display_name="X")
    admin = User.objects.create_superuser(
        email="Admin@Example.com", password=PASSWORD, display_name="Адмін"
    )
    assert admin.is_staff
    assert admin.is_superuser
    assert admin.email == "admin@example.com"
    assert str(admin) == "Адмін"
