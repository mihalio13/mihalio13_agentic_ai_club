from django.contrib import admin

from .models import Attendance, Comment, Event


class AttendanceInline(admin.TabularInline[Attendance, Event]):
    model = Attendance
    extra = 0
    raw_id_fields = ("user",)


@admin.register(Event)
class EventAdmin(admin.ModelAdmin[Event]):
    list_display = ("title", "author", "starts_at", "capacity", "visibility")
    list_filter = ("visibility",)
    search_fields = ("title", "author__email")
    raw_id_fields = ("author",)
    readonly_fields = ("invite_token", "created_at", "updated_at")
    inlines = (AttendanceInline,)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin[Comment]):
    list_display = ("event", "author", "created_at")
    search_fields = ("body", "author__email")
    raw_id_fields = ("event", "author")
