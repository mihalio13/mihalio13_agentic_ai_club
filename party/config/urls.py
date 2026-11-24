from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from core import views as core_views

urlpatterns = [
    path("healthz", core_views.healthz, name="healthz"),
    path(settings.ADMIN_URL, admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("", include("events.urls")),
]

handler400 = "core.views.bad_request"
handler403 = "core.views.permission_denied"
handler404 = "core.views.page_not_found"
handler500 = "core.views.server_error"
