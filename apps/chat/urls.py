from django.urls import path

from apps.chat import views


app_name = "chat"


urlpatterns = [
	path("", views.chat_page_view, name="chat_home"),

	# Chat UI support APIs
	path("api/conversations/", views.list_conversations_view, name="list_conversations"),
	path("api/conversations/create/", views.create_conversation_view, name="create_conversation"),
	path(
		"api/conversations/<int:conversation_id>/messages/",
		views.list_messages_view,
		name="list_messages",
	),
	path(
		"api/conversations/<int:conversation_id>/messages/send/",
		views.send_message_view,
		name="send_message",
	),
	path(
		"api/conversations/<int:conversation_id>/read/",
		views.mark_read_view,
		name="mark_read",
	),
	path(
		"api/messages/<int:message_id>/reaction/",
		views.toggle_message_reaction_view,
		name="toggle_message_reaction",
	),
	path("api/friends/search/", views.search_friends_view, name="search_friends"),
	path(
		"api/friends/<int:friend_id>/start/",
		views.start_chat_with_friend_view,
		name="start_chat_with_friend",
	),

	# Legacy paths (kept for backward compatibility)
	path("conversations/", views.list_conversations_view, name="list_conversations_legacy"),
	path("conversations/create/", views.create_conversation_view, name="create_conversation_legacy"),
	path(
		"conversations/<int:conversation_id>/messages/",
		views.list_messages_view,
		name="list_messages_legacy",
	),
	path(
		"conversations/<int:conversation_id>/messages/send/",
		views.send_message_view,
		name="send_message_legacy",
	),
	path(
		"conversations/<int:conversation_id>/read/",
		views.mark_read_view,
		name="mark_read_legacy",
	),
	path(
		"messages/<int:message_id>/reaction/",
		views.toggle_message_reaction_view,
		name="toggle_message_reaction_legacy",
	),
]
