from django.urls import path

from . import views

app_name = "events"

urlpatterns = [
    path("", views.home, name="home"),
    path("profile/", views.profile, name="profile"),
    path("events/new/", views.create, name="create"),
    path("events/<int:pk>/", views.detail, name="detail"),
    path("events/<int:pk>/edit/", views.edit, name="edit"),
    path("events/<int:pk>/delete/", views.delete, name="delete"),
    path("events/<int:pk>/cover/", views.cover, name="cover"),
    path("events/<int:pk>/join/", views.join, name="join"),
    path("events/<int:pk>/leave/", views.leave, name="leave"),
    path("events/<int:pk>/comments/", views.add_comment, name="add_comment"),
    path("events/<int:pk>/invite/regenerate/", views.regenerate_invite, name="regenerate_invite"),
    path(
        "events/<int:pk>/participants/<int:user_id>/remove/",
        views.remove_participant,
        name="remove_participant",
    ),
    path("comments/<int:pk>/delete/", views.delete_comment, name="delete_comment"),
    path("invite/<str:token>/", views.invite, name="invite"),
]
