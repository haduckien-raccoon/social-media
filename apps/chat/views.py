# import json
# import logging

# from django.contrib.auth.decorators import login_required
# from django.core.exceptions import PermissionDenied, ValidationError
# from django.db.models import Count, Q
# from django.http import JsonResponse
# from django.shortcuts import get_object_or_404, render
# from django.views.decorators.http import require_GET, require_POST

# from apps.accounts.models import User
# from apps.chat.models import Conversation, Message
# from apps.chat.service import (
# 	create_conversation,
# 	create_message,
# 	find_direct_conversation,
# 	get_messages_for_conversation,
# 	get_or_create_direct_conversation,
# 	get_unread_count,
# 	list_conversations_for_user,
# 	mark_conversation_read,
# 	serialize_message,
# 	toggle_message_reaction,
# 	MAX_ATTACHMENT_SIZE_BYTES,
# )
# from apps.friends.models import Friend


# INITIAL_MESSAGE_LIMIT = 30
# logger = logging.getLogger(__name__)


# def _validation_error_message(exc: ValidationError) -> str:
# 	if hasattr(exc, "messages") and exc.messages:
# 		return exc.messages[0]
# 	return str(exc)


# def _parse_json_body(request):
# 	if not request.body:
# 		return {}
# 	try:
# 		return json.loads(request.body.decode("utf-8"))
# 	except (json.JSONDecodeError, UnicodeDecodeError):
# 		raise ValidationError("Invalid JSON payload.")


# def _parse_limit(raw_limit):
# 	try:
# 		return max(1, min(int(raw_limit), 100))
# 	except (TypeError, ValueError):
# 		return 50


# def _avatar_url(user: User) -> str:
# 	if hasattr(user, "profile") and getattr(user.profile, "avatar", None):
# 		try:
# 			return user.profile.avatar.url
# 		except Exception:
# 			pass
# 	return f"https://ui-avatars.com/api/?name={user.username}"


# def _display_name(user: User) -> str:
# 	if hasattr(user, "profile"):
# 		full_name = (getattr(user.profile, "full_name", "") or "").strip()
# 		if full_name:
# 			return full_name
# 	return user.username


# def _direct_conversation_map(user: User) -> dict[int, int]:
# 	direct_conversations = (
# 		Conversation.objects.filter(participants=user)
# 		.annotate(participant_count=Count("participants", distinct=True))
# 		.filter(participant_count=2)
# 		.prefetch_related("participants")
# 	)

# 	conversation_map: dict[int, int] = {}
# 	for conversation in direct_conversations:
# 		for participant in conversation.participants.all():
# 			if participant.pk == user.pk:
# 				continue
# 			conversation_map[participant.pk] = conversation.pk

# 	return conversation_map


# def _search_friends_payload(user: User, query: str = "", limit: int = 20) -> list[dict]:
# 	logger.info("_search_friends_payload user_id=%s query=%s limit=%s", user.id, query, limit)
# 	friend_query = Friend.objects.filter(Q(user=user) | Q(friend=user)).select_related(
# 		"friend",
# 		"friend__profile",
# 		"user",
# 		"user__profile",
# 	)
# 	logger.info("_search_friends_payload friend_query count=%s", friend_query.count())
# 	if query:
# 		friend_query = friend_query.filter(
# 			Q(user=user, friend__username__icontains=query)
# 			| Q(user=user, friend__email__icontains=query)
# 			| Q(user=user, friend__profile__full_name__icontains=query)
# 			| Q(friend=user, user__username__icontains=query)
# 			| Q(friend=user, user__email__icontains=query)
# 			| Q(friend=user, user__profile__full_name__icontains=query)
# 		)

# 	conversation_map = _direct_conversation_map(user)
# 	results = []
# 	seen_ids = set()
# 	for relation in friend_query.order_by("id"):
# 		friend_user = relation.friend if relation.user_id == user.id else relation.user
# 		logger.info("_search_friends_payload relation id=%s user_id=%s friend_id=%s friend_user_id=%s", relation.id, relation.user_id, relation.friend_id, friend_user.id)
# 		if not friend_user or friend_user.id in seen_ids:
# 			continue
# 		seen_ids.add(friend_user.id)
# 		results.append(
# 			{
# 				"id": friend_user.id,
# 				"username": friend_user.username,
# 				"full_name": _display_name(friend_user),
# 				"avatar": _avatar_url(friend_user),
# 				"conversation_id": conversation_map.get(friend_user.id),
# 			}
# 		)
# 		if limit and len(results) >= limit:
# 			break

# 	logger.info("_search_friends_payload results count=%s", len(results))
# 	return results


# # @login_required
# # @require_GET
# # def chat_page_view(request):
# # 	conversations = list_conversations_for_user(request.user)
# # 	conversation_ids = {conversation["id"] for conversation in conversations}

# # 	active_conversation_id = None
# # 	requested_conversation_id = request.GET.get("conversation_id")
# # 	if requested_conversation_id:
# # 		try:
# # 			candidate_id = int(requested_conversation_id)
# # 			if candidate_id in conversation_ids:
# # 				active_conversation_id = candidate_id
# # 		except (TypeError, ValueError):
# # 			active_conversation_id = None

# # 	if active_conversation_id is None and conversations:
# # 		active_conversation_id = conversations[0]["id"]

# # 	# Bỏ qua hoàn toàn logic query get_messages_for_conversation để giảm tải DB
# # 	initial_messages = []

# # 	context = {
# # 		"initial_conversations": conversations,
# # 		"initial_active_conversation_id": active_conversation_id,
# # 		"initial_messages": initial_messages,
# # 		"initial_friend_candidates": _search_friends_payload(request.user, limit=20),
# # 		"ws_token": getattr(request, "_new_access_token", None) or request.COOKIES.get("access", ""),
# # 	}
# # 	return render(request, "chat/room.html", context)
# @login_required
# @require_GET
# def chat_page_view(request):
#     conversations = list_conversations_for_user(request.user)
#     conversation_ids = {conversation["id"] for conversation in conversations}
#     requested_friend_id = None
#     requested_friend = None

#     raw_friend_id = request.GET.get("friend_id")
#     if raw_friend_id:
#         try:
#             requested_friend_id = int(raw_friend_id)
#         except (TypeError, ValueError):
#             requested_friend_id = None

#     if requested_friend_id and requested_friend_id != request.user.id:
#         requested_friend = User.objects.filter(id=requested_friend_id).first()

#     active_conversation_id = None
#     requested_conversation_id = request.GET.get("conversation_id")
#     if requested_conversation_id:
#         try:
#             candidate_id = int(requested_conversation_id)
#             if candidate_id in conversation_ids:
#                 active_conversation_id = candidate_id
#         except (TypeError, ValueError):
#             active_conversation_id = None

#     if active_conversation_id is None and conversations:
#         active_conversation_id = conversations[0]["id"]

#     # Tải tin nhắn mới nhất cho cuộc trò chuyện đang active
#     initial_messages = []
#     if active_conversation_id:
#         try:
#             conversation = Conversation.objects.get(id=active_conversation_id)
#             # Lấy 30 tin nhắn gần nhất, sắp xếp cũ -> mới
#             messages, _ = get_messages_for_conversation(
#                 request.user,
#                 conversation,
#                 limit=INITIAL_MESSAGE_LIMIT,  # đã định nghĩa là 30
#             )
#             initial_messages = messages
#         except (Conversation.DoesNotExist, PermissionDenied):
#             pass

#     context = {
#         "initial_conversations": conversations,
#         "initial_active_conversation_id": active_conversation_id,
#         "initial_messages": initial_messages,
#         "initial_friend_candidates": _search_friends_payload(request.user, limit=20),
#         "initial_friend_id": requested_friend.id if requested_friend else "",
#         "ws_token": getattr(request, "_new_access_token", None) or request.COOKIES.get("access", ""),
#     }
#     return render(request, "chat/room.html", context)


# @login_required
# @require_POST
# def create_conversation_view(request):
# 	try:
# 		participant_ids = request.POST.getlist("participant_ids")
# 		if not participant_ids:
# 			payload = _parse_json_body(request)
# 			participant_ids = payload.get("participant_ids", [])

# 		if not isinstance(participant_ids, list):
# 			raise ValidationError("participant_ids must be a list.")

# 		conversation = create_conversation(request.user, participant_ids)
# 		return JsonResponse({"conversation_id": conversation.id}, status=201)
# 	except ValidationError as exc:
# 		return JsonResponse({"error": _validation_error_message(exc)}, status=400)


# @login_required
# @require_GET
# def list_conversations_view(request):
# 	results = list_conversations_for_user(request.user)
# 	return JsonResponse({"results": results}, status=200)


# @login_required
# @require_GET
# def unread_count_view(request):
# 	conversations = Conversation.objects.filter(participants=request.user).distinct()
# 	unread_total = sum(get_unread_count(conversation, request.user) for conversation in conversations)
# 	return JsonResponse({"unread_count": unread_total}, status=200)


# @login_required
# @require_GET
# def list_messages_view(request, conversation_id):
# 	conversation = get_object_or_404(Conversation, id=conversation_id)
# 	include_all_messages = request.GET.get("all") == "1"
# 	before_id_raw = request.GET.get("before_id")

# 	before_id = None
# 	if before_id_raw:
# 		try:
# 			before_id = int(before_id_raw)
# 		except (TypeError, ValueError):
# 			return JsonResponse({"error": "before_id must be an integer."}, status=400)

# 	try:
# 		messages, unread_count = get_messages_for_conversation(
# 			request.user,
# 			conversation,
# 			limit=None if include_all_messages else _parse_limit(request.GET.get("limit")),
# 			before_id=before_id,
# 		)
# 		return JsonResponse({"results": messages, "unread_count": unread_count}, status=200)
# 	except PermissionDenied as exc:
# 		return JsonResponse({"error": str(exc)}, status=403)


# @login_required
# @require_GET
# def search_friends_view(request):
# 	query = (request.GET.get("q") or "").strip()
# 	results = _search_friends_payload(request.user, query=query, limit=20)
# 	# Debug output to help trace friend search behavior.
# 	try:
# 		total_friends = (
# 			Friend.objects.filter(Q(user=request.user) | Q(friend=request.user))
# 			.values_list("user_id", "friend_id")
# 			.distinct()
# 			.count()
# 		)
# 		matched_usernames = [item.get("username") for item in results]
# 		logger.info(
# 			"chat.search_friends user_id=%s query=%s total_friends=%s matches=%s usernames=%s",
# 			request.user.id,
# 			query,
# 			total_friends,
# 			len(results),
# 			matched_usernames,
# 		)
# 	except Exception:
# 		logger.exception("chat.search_friends debug logging failed")
# 	return JsonResponse({"results": results}, status=200)


# @login_required
# @require_POST
# def start_chat_with_friend_view(request, friend_id):
# 	friend_user = get_object_or_404(User, id=friend_id)
# 	if friend_user.pk == request.user.pk:
# 		return JsonResponse({"error": "Cannot create chat with yourself."}, status=400)

# 	is_friend = Friend.objects.filter(
# 		Q(user=request.user, friend=friend_user)
# 		| Q(user=friend_user, friend=request.user)
# 	).exists()
# 	if not is_friend:
# 		return JsonResponse({"error": "You can only start chat with your friends."}, status=403)

# 	# Don't create conversation yet - will be created when first message is sent
# 	return JsonResponse(
# 		{
# 			"friend": {
# 				"id": friend_user.id,
# 				"username": friend_user.username,
# 				"full_name": _display_name(friend_user),
# 				"avatar": _avatar_url(friend_user),
# 			}
# 		},
# 		status=200,
# 	)


# @login_required
# @require_POST
# def send_message_view(request, conversation_id):
# 	conversation = get_object_or_404(Conversation, id=conversation_id)

# 	try:
# 		content = request.POST.get("content", "")
# 		if request.content_type and request.content_type.startswith("application/json"):
# 			payload = _parse_json_body(request)
# 			content = payload.get("content", "")

# 		attachments = request.FILES.getlist("attachments")
# 		message = create_message(
# 			request.user,
# 			conversation,
# 			content=content,
# 			attachments=attachments,
# 		)
# 		return JsonResponse({"message": serialize_message(message, viewer=request.user)}, status=201)
# 	except PermissionDenied as exc:
# 		return JsonResponse({"error": str(exc)}, status=403)
# 	except ValidationError as exc:
# 		return JsonResponse({"error": _validation_error_message(exc)}, status=400)


# @login_required
# @require_POST
# def mark_read_view(request, conversation_id):
# 	conversation = get_object_or_404(Conversation, id=conversation_id)

# 	try:
# 		participant = mark_conversation_read(request.user, conversation)
# 		return JsonResponse(
# 			{
# 				"conversation_id": conversation.id,
# 				"last_read_at": participant.last_read_at.isoformat() if participant.last_read_at else None,
# 				"unread_count": get_unread_count(conversation, request.user),
# 			},
# 			status=200,
# 		)
# 	except PermissionDenied as exc:
# 		return JsonResponse({"error": str(exc)}, status=403)


# @login_required
# @require_POST
# def toggle_message_reaction_view(request, message_id):
# 	message = get_object_or_404(Message, id=message_id, is_deleted=False)

# 	try:
# 		reaction_type = request.POST.get("reaction")
# 		if not reaction_type:
# 			payload = _parse_json_body(request)
# 			reaction_type = payload.get("reaction")

# 		result = toggle_message_reaction(request.user, message, reaction_type)
# 		return JsonResponse(result, status=200)
# 	except PermissionDenied as exc:
# 		return JsonResponse({"error": str(exc)}, status=403)
# 	except ValidationError as exc:
# 		return JsonResponse({"error": _validation_error_message(exc)}, status=400)


# @login_required
# @require_POST
# def send_first_message_view(request, friend_id):
# 	"""Send first message to a friend. Creates conversation if not exists."""
# 	friend_user = get_object_or_404(User, id=friend_id)
# 	if friend_user.pk == request.user.pk:
# 		return JsonResponse({"error": "Cannot chat with yourself."}, status=400)

# 	is_friend = Friend.objects.filter(
# 		Q(user=request.user, friend=friend_user)
# 		| Q(user=friend_user, friend=request.user)
# 	).exists()
# 	if not is_friend:
# 		return JsonResponse({"error": "You can only chat with your friends."}, status=403)

# 	# Parse content from form data
# 	content = request.POST.get("content", "").strip()

# 	# Handle file attachments
# 	attachments = []
# 	if request.FILES:
# 		for key in request.FILES:
# 			for uploaded_file in request.FILES.getlist(key):
# 				if uploaded_file.size > MAX_ATTACHMENT_SIZE_BYTES:
# 					return JsonResponse({"error": f"File {uploaded_file.name} exceeds 20MB limit."}, status=400)
# 				attachments.append(uploaded_file)

# 	if not content and not attachments:
# 		return JsonResponse({"error": "Message content or attachments are required."}, status=400)

# 	# Create conversation if not exists
# 	conversation, _ = get_or_create_direct_conversation(request.user, friend_user)

# 	# Send message
# 	try:
# 		message = create_message(
# 			user=request.user,
# 			conversation=conversation,
# 			content=content,
# 			attachments=attachments,
# 		)
# 	except (PermissionDenied, ValidationError) as exc:
# 		return JsonResponse({"error": str(exc)}, status=403)

# 	# Broadcast conversation update to all participants (realtime push)
# 	try:
# 		from apps.chat.consumer import broadcast_conversation_to_participants
# 		from channels.layers import get_channel_layer
# 		channel_layer = get_channel_layer()
# 		if channel_layer:
# 			# Use async_to_sync to call the async function
# 			from asgiref.sync import async_to_sync
# 			async_to_sync(broadcast_conversation_to_participants)(channel_layer, conversation.id)
# 	except Exception as exc:
# 		logger.warning("Failed to broadcast conversation update: %s", exc)

# 	# Serialize and return
# 	message_payload = serialize_message(message, request.user)
# 	conversation_payload = None
# 	for item in list_conversations_for_user(request.user):
# 		if item["id"] == conversation.id:
# 			conversation_payload = item
# 			break

# 	if conversation_payload is None:
# 		conversation_payload = {
# 			"id": conversation.id,
# 			"participants": [
# 				{
# 					"id": friend_user.id,
# 					"username": friend_user.username,
# 					"full_name": _display_name(friend_user),
# 					"avatar": _avatar_url(friend_user),
# 				}
# 			],
# 			"updated_at": conversation.updated_at.isoformat(),
# 			"created_at": conversation.created_at.isoformat(),
# 			"unread_count": 0,
# 			"last_message": message_payload,
# 		}

# 	return JsonResponse(
# 		{
# 			"conversation": conversation_payload,
# 			"message": message_payload,
# 		},
# 		status=201,
# 	)
import json
import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import User
from apps.chat.models import Conversation, Message
from apps.chat.service import (
	MAX_ATTACHMENT_SIZE_BYTES,
	chat_status_for_user,
	create_conversation,
	create_message,
	ensure_user_can_chat,
	find_direct_conversation,
	get_conversation_chat_block_payload,
	get_messages_for_conversation,
	get_or_create_direct_conversation,
	get_unread_count,
	list_conversations_for_user,
	mark_conversation_read,
	serialize_message,
	toggle_message_reaction,
)
from apps.friends.models import Friend


INITIAL_MESSAGE_LIMIT = 30
logger = logging.getLogger(__name__)


def _validation_error_message(exc: ValidationError) -> str:
	if hasattr(exc, "messages") and exc.messages:
		return exc.messages[0]
	return str(exc)


def _parse_json_body(request):
	if not request.body:
		return {}
	try:
		return json.loads(request.body.decode("utf-8"))
	except (json.JSONDecodeError, UnicodeDecodeError):
		raise ValidationError("Invalid JSON payload.")


def _parse_limit(raw_limit):
	try:
		return max(1, min(int(raw_limit), 100))
	except (TypeError, ValueError):
		return 50


def _avatar_url(user: User) -> str:
	if hasattr(user, "profile") and getattr(user.profile, "avatar", None):
		try:
			return user.profile.avatar.url
		except Exception:
			pass
	return f"https://ui-avatars.com/api/?name={user.username}"


def _display_name(user: User) -> str:
	if hasattr(user, "profile"):
		full_name = (getattr(user.profile, "full_name", "") or "").strip()
		if full_name:
			return full_name
	return user.username


def _user_chat_payload(user: User, *, conversation_id: int | None = None) -> dict:
	chat_status = chat_status_for_user(user)
	payload = {
		"id": user.id,
		"username": user.username,
		"full_name": _display_name(user),
		"avatar": _avatar_url(user),
		"chat_status": chat_status,
		"can_message": chat_status["can_message"],
		"blocked_reason": chat_status["blocked_reason"],
	}
	if conversation_id is not None:
		payload["conversation_id"] = conversation_id
	return payload


def _direct_conversation_map(user: User) -> dict[int, int]:
	direct_conversations = (
		Conversation.objects.filter(participants=user)
		.annotate(participant_count=Count("participants", distinct=True))
		.filter(participant_count=2)
		.prefetch_related("participants")
	)

	conversation_map: dict[int, int] = {}
	for conversation in direct_conversations:
		for participant in conversation.participants.all():
			if participant.pk == user.pk:
				continue
			conversation_map[participant.pk] = conversation.pk

	return conversation_map


def _search_friends_payload(user: User, query: str = "", limit: int = 20) -> list[dict]:
	logger.info("_search_friends_payload user_id=%s query=%s limit=%s", user.id, query, limit)
	friend_query = Friend.objects.filter(Q(user=user) | Q(friend=user)).select_related(
		"friend",
		"friend__profile",
		"user",
		"user__profile",
	)
	logger.info("_search_friends_payload friend_query count=%s", friend_query.count())
	if query:
		friend_query = friend_query.filter(
			Q(user=user, friend__username__icontains=query)
			| Q(user=user, friend__email__icontains=query)
			| Q(user=user, friend__profile__full_name__icontains=query)
			| Q(friend=user, user__username__icontains=query)
			| Q(friend=user, user__email__icontains=query)
			| Q(friend=user, user__profile__full_name__icontains=query)
		)

	conversation_map = _direct_conversation_map(user)
	results = []
	seen_ids = set()
	for relation in friend_query.order_by("id"):
		friend_user = relation.friend if relation.user_id == user.id else relation.user
		logger.info("_search_friends_payload relation id=%s user_id=%s friend_id=%s friend_user_id=%s", relation.id, relation.user_id, relation.friend_id, friend_user.id)
		if not friend_user or friend_user.id in seen_ids:
			continue
		seen_ids.add(friend_user.id)
		results.append(
			_user_chat_payload(
				friend_user,
				conversation_id=conversation_map.get(friend_user.id),
			)
		)
		if limit and len(results) >= limit:
			break

	logger.info("_search_friends_payload results count=%s", len(results))
	return results


# @login_required
# @require_GET
# def chat_page_view(request):
# 	conversations = list_conversations_for_user(request.user)
# 	conversation_ids = {conversation["id"] for conversation in conversations}

# 	active_conversation_id = None
# 	requested_conversation_id = request.GET.get("conversation_id")
# 	if requested_conversation_id:
# 		try:
# 			candidate_id = int(requested_conversation_id)
# 			if candidate_id in conversation_ids:
# 				active_conversation_id = candidate_id
# 		except (TypeError, ValueError):
# 			active_conversation_id = None

# 	if active_conversation_id is None and conversations:
# 		active_conversation_id = conversations[0]["id"]

# 	# Bỏ qua hoàn toàn logic query get_messages_for_conversation để giảm tải DB
# 	initial_messages = []

# 	context = {
# 		"initial_conversations": conversations,
# 		"initial_active_conversation_id": active_conversation_id,
# 		"initial_messages": initial_messages,
# 		"initial_friend_candidates": _search_friends_payload(request.user, limit=20),
# 		"ws_token": getattr(request, "_new_access_token", None) or request.COOKIES.get("access", ""),
# 	}
# 	return render(request, "chat/room.html", context)
@login_required
@require_GET
def chat_page_view(request):
    conversations = list_conversations_for_user(request.user)
    conversation_ids = {conversation["id"] for conversation in conversations}
    requested_friend_id = None
    requested_friend = None

    raw_friend_id = request.GET.get("friend_id")
    if raw_friend_id:
        try:
            requested_friend_id = int(raw_friend_id)
        except (TypeError, ValueError):
            requested_friend_id = None

    if requested_friend_id and requested_friend_id != request.user.id:
        requested_friend = User.objects.filter(id=requested_friend_id).first()

    active_conversation_id = None
    requested_conversation_id = request.GET.get("conversation_id")
    if requested_conversation_id:
        try:
            candidate_id = int(requested_conversation_id)
            if candidate_id in conversation_ids:
                active_conversation_id = candidate_id
        except (TypeError, ValueError):
            active_conversation_id = None

    if active_conversation_id is None and conversations:
        active_conversation_id = conversations[0]["id"]

    # Tải tin nhắn mới nhất cho cuộc trò chuyện đang active
    initial_messages = []
    if active_conversation_id:
        try:
            conversation = Conversation.objects.get(id=active_conversation_id)
            # Lấy 30 tin nhắn gần nhất, sắp xếp cũ -> mới
            messages, _ = get_messages_for_conversation(
                request.user,
                conversation,
                limit=INITIAL_MESSAGE_LIMIT,  # đã định nghĩa là 30
            )
            initial_messages = messages
        except (Conversation.DoesNotExist, PermissionDenied):
            pass

    context = {
        "initial_conversations": conversations,
        "initial_active_conversation_id": active_conversation_id,
        "initial_messages": initial_messages,
        "initial_friend_candidates": _search_friends_payload(request.user, limit=20),
        "initial_friend_id": requested_friend.id if requested_friend else "",
        "ws_token": getattr(request, "_new_access_token", None) or request.COOKIES.get("access", ""),
    }
    return render(request, "chat/room.html", context)


@login_required
@require_POST
def create_conversation_view(request):
	try:
		participant_ids = request.POST.getlist("participant_ids")
		if not participant_ids:
			payload = _parse_json_body(request)
			participant_ids = payload.get("participant_ids", [])

		if not isinstance(participant_ids, list):
			raise ValidationError("participant_ids must be a list.")

		conversation = create_conversation(request.user, participant_ids)
		return JsonResponse({"conversation_id": conversation.id}, status=201)
	except PermissionDenied as exc:
		return JsonResponse({"error": str(exc)}, status=403)
	except ValidationError as exc:
		return JsonResponse({"error": _validation_error_message(exc)}, status=400)


@login_required
@require_GET
def list_conversations_view(request):
	results = list_conversations_for_user(request.user)
	return JsonResponse({"results": results}, status=200)


@login_required
@require_GET
def unread_count_view(request):
	conversations = Conversation.objects.filter(participants=request.user).distinct()
	unread_total = sum(get_unread_count(conversation, request.user) for conversation in conversations)
	return JsonResponse({"unread_count": unread_total}, status=200)


@login_required
@require_GET
def list_messages_view(request, conversation_id):
	conversation = get_object_or_404(Conversation, id=conversation_id)
	include_all_messages = request.GET.get("all") == "1"
	before_id_raw = request.GET.get("before_id")

	before_id = None
	if before_id_raw:
		try:
			before_id = int(before_id_raw)
		except (TypeError, ValueError):
			return JsonResponse({"error": "before_id must be an integer."}, status=400)

	try:
		messages, unread_count = get_messages_for_conversation(
			request.user,
			conversation,
			limit=None if include_all_messages else _parse_limit(request.GET.get("limit")),
			before_id=before_id,
		)
		chat_block = get_conversation_chat_block_payload(request.user, conversation)
		return JsonResponse(
			{
				"results": messages,
				"unread_count": unread_count,
				"chat_block": chat_block,
				"can_send_message": not chat_block["blocked"],
				"blocked_reason": chat_block["reason"],
			},
			status=200,
		)
	except PermissionDenied as exc:
		return JsonResponse({"error": str(exc)}, status=403)


@login_required
@require_GET
def search_friends_view(request):
	query = (request.GET.get("q") or "").strip()
	results = _search_friends_payload(request.user, query=query, limit=20)
	# Debug output to help trace friend search behavior.
	try:
		total_friends = (
			Friend.objects.filter(Q(user=request.user) | Q(friend=request.user))
			.values_list("user_id", "friend_id")
			.distinct()
			.count()
		)
		matched_usernames = [item.get("username") for item in results]
		logger.info(
			"chat.search_friends user_id=%s query=%s total_friends=%s matches=%s usernames=%s",
			request.user.id,
			query,
			total_friends,
			len(results),
			matched_usernames,
		)
	except Exception:
		logger.exception("chat.search_friends debug logging failed")
	return JsonResponse({"results": results}, status=200)


@login_required
@require_POST
def start_chat_with_friend_view(request, friend_id):
	friend_user = get_object_or_404(User, id=friend_id)
	if friend_user.pk == request.user.pk:
		return JsonResponse({"error": "Cannot create chat with yourself."}, status=400)

	is_friend = Friend.objects.filter(
		Q(user=request.user, friend=friend_user)
		| Q(user=friend_user, friend=request.user)
	).exists()
	if not is_friend:
		return JsonResponse({"error": "You can only start chat with your friends."}, status=403)

	try:
		ensure_user_can_chat(request.user, for_current_user=True)
		ensure_user_can_chat(friend_user)
	except PermissionDenied as exc:
		return JsonResponse(
			{
				"error": str(exc),
				"friend": _user_chat_payload(friend_user),
			},
			status=403,
		)

	# Don't create conversation yet - will be created when first message is sent
	return JsonResponse({"friend": _user_chat_payload(friend_user)}, status=200)


@login_required
@require_POST
def send_message_view(request, conversation_id):
	conversation = get_object_or_404(Conversation, id=conversation_id)

	try:
		content = request.POST.get("content", "")
		if request.content_type and request.content_type.startswith("application/json"):
			payload = _parse_json_body(request)
			content = payload.get("content", "")

		attachments = request.FILES.getlist("attachments")
		message = create_message(
			request.user,
			conversation,
			content=content,
			attachments=attachments,
		)
		return JsonResponse({"message": serialize_message(message, viewer=request.user)}, status=201)
	except PermissionDenied as exc:
		return JsonResponse({"error": str(exc)}, status=403)
	except ValidationError as exc:
		return JsonResponse({"error": _validation_error_message(exc)}, status=400)


@login_required
@require_POST
def mark_read_view(request, conversation_id):
	conversation = get_object_or_404(Conversation, id=conversation_id)

	try:
		participant = mark_conversation_read(request.user, conversation)
		return JsonResponse(
			{
				"conversation_id": conversation.id,
				"last_read_at": participant.last_read_at.isoformat() if participant.last_read_at else None,
				"unread_count": get_unread_count(conversation, request.user),
			},
			status=200,
		)
	except PermissionDenied as exc:
		return JsonResponse({"error": str(exc)}, status=403)


@login_required
@require_POST
def toggle_message_reaction_view(request, message_id):
	message = get_object_or_404(Message, id=message_id, is_deleted=False)

	try:
		reaction_type = request.POST.get("reaction")
		if not reaction_type:
			payload = _parse_json_body(request)
			reaction_type = payload.get("reaction")

		result = toggle_message_reaction(request.user, message, reaction_type)
		return JsonResponse(result, status=200)
	except PermissionDenied as exc:
		return JsonResponse({"error": str(exc)}, status=403)
	except ValidationError as exc:
		return JsonResponse({"error": _validation_error_message(exc)}, status=400)


@login_required
@require_POST
def send_first_message_view(request, friend_id):
	"""Send first message to a friend. Creates conversation if not exists."""
	friend_user = get_object_or_404(User, id=friend_id)
	if friend_user.pk == request.user.pk:
		return JsonResponse({"error": "Cannot chat with yourself."}, status=400)

	is_friend = Friend.objects.filter(
		Q(user=request.user, friend=friend_user)
		| Q(user=friend_user, friend=request.user)
	).exists()
	if not is_friend:
		return JsonResponse({"error": "You can only chat with your friends."}, status=403)

	# Parse content from form data
	content = request.POST.get("content", "").strip()

	# Handle file attachments
	attachments = []
	if request.FILES:
		for key in request.FILES:
			for uploaded_file in request.FILES.getlist(key):
				if uploaded_file.size > MAX_ATTACHMENT_SIZE_BYTES:
					return JsonResponse({"error": f"File {uploaded_file.name} exceeds 20MB limit."}, status=400)
				attachments.append(uploaded_file)

	if not content and not attachments:
		return JsonResponse({"error": "Message content or attachments are required."}, status=400)

	# Create conversation if not exists
	try:
		conversation, _ = get_or_create_direct_conversation(request.user, friend_user)
	except PermissionDenied as exc:
		return JsonResponse({"error": str(exc), "friend": _user_chat_payload(friend_user)}, status=403)
	except ValidationError as exc:
		return JsonResponse({"error": _validation_error_message(exc)}, status=400)

	# Send message
	try:
		message = create_message(
			user=request.user,
			conversation=conversation,
			content=content,
			attachments=attachments,
		)
	except (PermissionDenied, ValidationError) as exc:
		return JsonResponse({"error": str(exc)}, status=403)

	# Broadcast conversation update to all participants (realtime push)
	try:
		from apps.chat.consumer import broadcast_conversation_to_participants
		from channels.layers import get_channel_layer
		channel_layer = get_channel_layer()
		if channel_layer:
			# Use async_to_sync to call the async function
			from asgiref.sync import async_to_sync
			async_to_sync(broadcast_conversation_to_participants)(channel_layer, conversation.id)
	except Exception as exc:
		logger.warning("Failed to broadcast conversation update: %s", exc)

	# Serialize and return
	message_payload = serialize_message(message, request.user)
	conversation_payload = None
	for item in list_conversations_for_user(request.user):
		if item["id"] == conversation.id:
			conversation_payload = item
			break

	if conversation_payload is None:
		chat_block = get_conversation_chat_block_payload(request.user, conversation)
		conversation_payload = {
			"id": conversation.id,
			"participants": [_user_chat_payload(friend_user)],
			"updated_at": conversation.updated_at.isoformat(),
			"created_at": conversation.created_at.isoformat(),
			"unread_count": 0,
			"last_message": message_payload,
			"chat_block": chat_block,
			"can_send_message": not chat_block["blocked"],
			"blocked_reason": chat_block["reason"],
		}

	return JsonResponse(
		{
			"conversation": conversation_payload,
			"message": message_payload,
		},
		status=201,
	)
