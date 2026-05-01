from django.urls import path
from . import views

app_name = "groups"

urlpatterns = [
    path("", views.group_list, name="group_list"),
    path("create/", views.create_group, name="create_group"),
    path("<int:group_id>/", views.group_detail, name="group_detail"),
    path("<int:group_id>/edit/", views.update_group, name="update_group"),
    path("<int:group_id>/delete/", views.delete_group, name="delete_group"),

    path("<int:group_id>/join/", views.join_group, name="join_group"),
    path("<int:group_id>/leave/", views.leave_group, name="leave_group"),

    path("<int:group_id>/approve/<int:member_id>/", views.approve_member, name="approve_member"),
    path("<int:group_id>/reject/<int:member_id>/", views.reject_member, name="reject_member"),
    path("<int:group_id>/ban/<int:member_id>/", views.ban_member, name="ban_member"),
    path('<int:group_id>/manage/', views.manage_group, name='manage_group'),
    path('<int:group_id>/manage/', views.manage_group, name='manage_group'),

    #Post in group
    path("<int:group_id>/create-post/", views.create_post_in_group, name="create_post_in_group"),
    #Kiểm duyệt
    path("<int:group_id>/post/<int:post_id>/approve/", views.approve_post_in_group, name="approve_post"),
    path("<int:group_id>/post/<int:post_id>/reject/", views.reject_post_in_group, name="reject_post"),
    # report
    path("<int:group_id>/report/", views.report_item, name="report_item"),
    path("<int:group_id>/manage/report-action/", views.handle_report_action, name="handle_report_action"),
]