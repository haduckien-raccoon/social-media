(function () {
    "use strict";

    var MAX_ATTACHMENT_SIZE_BYTES = 20 * 1024 * 1024;

    function parseScriptJSON(elementId, fallbackValue) {
        var element = document.getElementById(elementId);
        if (!element || !element.textContent) {
            return fallbackValue;
        }
        try {
            return JSON.parse(element.textContent);
        } catch (error) {
            return fallbackValue;
        }
    }

    function toInteger(value, fallbackValue) {
        var parsed = Number.parseInt(value, 10);
        return Number.isFinite(parsed) ? parsed : fallbackValue;
    }

    function formatRelativeTime(isoValue) {
        if (!isoValue) {
            return "Vua xong";
        }
        var dateValue = new Date(isoValue);
        if (Number.isNaN(dateValue.getTime())) {
            return "Vua xong";
        }

        var diffSeconds = Math.max(0, Math.floor((Date.now() - dateValue.getTime()) / 1000));
        if (diffSeconds < 60) {
            return "Vua xong";
        }
        var diffMinutes = Math.floor(diffSeconds / 60);
        if (diffMinutes < 60) {
            return String(diffMinutes) + " phut truoc";
        }
        var diffHours = Math.floor(diffMinutes / 60);
        if (diffHours < 24) {
            return String(diffHours) + " gio truoc";
        }
        var diffDays = Math.floor(diffHours / 24);
        return String(diffDays) + " ngay truoc";
    }

    function escapeHtml(value) {
        var div = document.createElement("div");
        div.textContent = value == null ? "" : String(value);
        return div.innerHTML;
    }

    function getCookie(name) {
        var cookieValue = null;
        if (document.cookie && document.cookie !== "") {
            var cookies = document.cookie.split(";");
            for (var index = 0; index < cookies.length; index += 1) {
                var cookie = cookies[index].trim();
                if (cookie.substring(0, name.length + 1) === name + "=") {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    function buildUrl(urlTemplate, idValue) {
        return String(urlTemplate || "").replace("/0/", "/" + String(idValue) + "/");
    }

    function fileSizeLabel(fileSize) {
        if (fileSize < 1024) {
            return String(fileSize) + " B";
        }
        if (fileSize < 1024 * 1024) {
            return (fileSize / 1024).toFixed(1) + " KB";
        }
        return (fileSize / (1024 * 1024)).toFixed(1) + " MB";
    }

    function isSocketOpen(socket) {
        return socket && socket.readyState === WebSocket.OPEN;
    }

    function readFileAsBase64(file) {
        return new Promise(function (resolve, reject) {
            var reader = new FileReader();
            reader.onload = function () {
                var result = reader.result || "";
                var base64Value = String(result);
                var commaIndex = base64Value.indexOf(",");
                resolve(commaIndex >= 0 ? base64Value.slice(commaIndex + 1) : base64Value);
            };
            reader.onerror = function () {
                reject(reader.error || new Error("File read failed"));
            };
            reader.readAsDataURL(file);
        });
    }

    async function buildWsAttachments(files) {
        var attachments = await Promise.all(files.map(async function (file) {
            var base64Content = await readFileAsBase64(file);
            return {
                name: file.name,
                content_type: file.type || "application/octet-stream",
                content_base64: base64Content
            };
        }));
        return attachments;
    }

    var REACTION_EMOJI = {
        like: "👍",
        love: "❤️",
        haha: "😆",
        wow: "😮",
        sad: "😢",
        angry: "😡"
    };

    var configElement = document.getElementById("chat-config");
    if (!configElement) {
        return;
    }

    var conversationListElement = document.getElementById("conversation-list");
    var friendSearchResultElement = document.getElementById("friend-search-results");
    var friendSearchInputElement = document.getElementById("friend-search-input");
    var conversationFilterInputElement = document.getElementById("conversation-filter-input");
    var messageListElement = document.getElementById("chat-message-list");
    var activeHeaderElement = document.getElementById("chat-active-header");
    var messageSearchInputElement = document.getElementById("chat-message-search-input");
    var composeFormElement = document.getElementById("chat-compose-form");
    var messageInputElement = document.getElementById("chat-message-input");
    var attachmentsInputElement = document.getElementById("chat-attachments-input");
    var attachmentsPreviewElement = document.getElementById("chat-attachments-preview");
    var sendButtonElement = document.getElementById("chat-send-button");

    var state = {
        currentUserId: toInteger(configElement.dataset.currentUserId, 0),
        activeConversationId: toInteger(configElement.dataset.activeConversationId, null),
        conversations: parseScriptJSON("chat-initial-conversations", []),
        friendCandidates: parseScriptJSON("chat-initial-friends", []),
        messagesByConversation: {},
        ws: null,
        wsConversationId: null,
        wsConnected: false,
        wsQueue: [],
        wsReconnectTimer: null,
        wsReconnectAttempts: 0,
        sending: false,
        conversationFilterTerm: "",
        friendSearchTerm: "",
        messageSearchTerm: ""
    };

    var initialMessages = parseScriptJSON("chat-initial-messages", []);
    if (state.activeConversationId && Array.isArray(initialMessages)) {
        state.messagesByConversation[state.activeConversationId] = initialMessages;
    }

    var urls = {
        listConversations: configElement.dataset.listConversationsUrl,
        listMessagesTemplate: configElement.dataset.listMessagesTemplate,
        sendMessageTemplate: configElement.dataset.sendMessageTemplate,
        markReadTemplate: configElement.dataset.markReadTemplate,
        toggleReactionTemplate: configElement.dataset.toggleReactionTemplate,
        searchFriends: configElement.dataset.searchFriendsUrl,
        startFriendChatTemplate: configElement.dataset.startFriendChatTemplate
    };

    var wsToken = configElement.dataset.wsToken || "";

    function getConversationTitle(conversation) {
        var participants = Array.isArray(conversation.participants) ? conversation.participants : [];
        if (!participants.length) {
            return "Hoi thoai";
        }
        return participants.map(function (participant) {
            return participant.full_name || participant.username;
        }).join(", ");
    }

    function getConversationSubtitle(conversation) {
        var lastMessage = conversation.last_message;
        if (!lastMessage) {
            return "Chua co tin nhan";
        }
        var preview = lastMessage.preview || "Tin nhan moi";
        return preview;
    }

    function conversationAvatar(conversation) {
        var participants = Array.isArray(conversation.participants) ? conversation.participants : [];
        if (!participants.length) {
            return "https://ui-avatars.com/api/?name=Chat";
        }
        return participants[0].avatar || "https://ui-avatars.com/api/?name=" + encodeURIComponent(participants[0].username || "Chat");
    }

    function sortConversationsInPlace() {
        state.conversations.sort(function (left, right) {
            var leftTime = new Date(left.updated_at || left.created_at || 0).getTime();
            var rightTime = new Date(right.updated_at || right.created_at || 0).getTime();
            return rightTime - leftTime;
        });
    }

    function renderConversationList() {
        if (!conversationListElement) {
            return;
        }

        sortConversationsInPlace();
        var filterTerm = (state.conversationFilterTerm || "").trim().toLowerCase();
        var filteredConversations = state.conversations.filter(function (conversation) {
            if (!filterTerm) {
                return true;
            }
            var title = getConversationTitle(conversation).toLowerCase();
            var subtitle = getConversationSubtitle(conversation).toLowerCase();
            return title.indexOf(filterTerm) >= 0 || subtitle.indexOf(filterTerm) >= 0;
        });

        if (!filteredConversations.length) {
            conversationListElement.innerHTML = '<div class="chat-empty-state">Khong tim thay hoi thoai phu hop.</div>';
            return;
        }

        conversationListElement.innerHTML = filteredConversations.map(function (conversation) {
            var isActive = state.activeConversationId === conversation.id;
            var unreadCount = toInteger(conversation.unread_count, 0);
            var unreadBadge = unreadCount > 0
                ? '<span class="chat-unread-badge">' + escapeHtml(unreadCount > 99 ? "99+" : String(unreadCount)) + "</span>"
                : "";

            return '' +
                '<article class="chat-conversation-item' + (isActive ? " active" : "") + '" data-conversation-id="' + escapeHtml(conversation.id) + '">' +
                    '<div class="chat-user-summary">' +
                        '<img class="chat-avatar" src="' + escapeHtml(conversationAvatar(conversation)) + '" alt="avatar">' +
                        '<div class="chat-user-text">' +
                            '<div class="chat-user-name">' + escapeHtml(getConversationTitle(conversation)) + '</div>' +
                            '<div class="chat-user-sub">' + escapeHtml(getConversationSubtitle(conversation)) + '</div>' +
                        '</div>' +
                    '</div>' +
                    unreadBadge +
                '</article>';
        }).join("");
    }

    function renderActiveHeader() {
        if (!activeHeaderElement) {
            return;
        }

        if (!state.activeConversationId) {
            activeHeaderElement.innerHTML = "<h3>Chon mot hoi thoai</h3><span>Ban co the tim ban be o cot ben phai de nhan tin thu.</span>";
            return;
        }

        var conversation = state.conversations.find(function (item) {
            return item.id === state.activeConversationId;
        });

        if (!conversation) {
            activeHeaderElement.innerHTML = "<h3>Khong tim thay hoi thoai</h3><span>Vui long thu lai.</span>";
            return;
        }

        var subtitle = "Dang ket noi realtime";
        if (conversation.last_message && conversation.last_message.created_at) {
            subtitle = "Cap nhat " + formatRelativeTime(conversation.last_message.created_at);
        }

        activeHeaderElement.innerHTML = "<h3>" + escapeHtml(getConversationTitle(conversation)) + "</h3><span>" + escapeHtml(subtitle) + "</span>";
    }

    function reactionSummaryText(message) {
        var summary = message.reaction_summary || {};
        var keys = Object.keys(summary);
        if (!keys.length) {
            return "";
        }

        return keys.map(function (reactionKey) {
            var emoji = REACTION_EMOJI[reactionKey] || reactionKey;
            return emoji + " " + summary[reactionKey];
        }).join("  ");
    }

    function attachmentHtml(message) {
        var attachments = Array.isArray(message.attachments) ? message.attachments : [];
        if (!attachments.length) {
            return "";
        }

        return '<div class="chat-attachments">' + attachments.map(function (attachment) {
            var contentType = attachment.content_type || "";
            if (contentType.indexOf("image/") === 0) {
                return '<a href="' + escapeHtml(attachment.url || "#") + '" target="_blank" rel="noopener noreferrer">' +
                    '<img class="chat-attachment-image" src="' + escapeHtml(attachment.url || "") + '" alt="attachment image">' +
                '</a>';
            }

            return '<a class="chat-attachment-file" href="' + escapeHtml(attachment.url || "#") + '" target="_blank" rel="noopener noreferrer">' +
                '<span>📎</span>' +
                '<span>' + escapeHtml(attachment.name || "tep dinh kem") + '</span>' +
                '<span>(' + escapeHtml(fileSizeLabel(toInteger(attachment.size, 0))) + ')</span>' +
            '</a>';
        }).join("") + '</div>';
    }

    function messageMatchesSearch(message, searchTerm) {
        if (!searchTerm) {
            return true;
        }

        var content = (message.content || "").toLowerCase();
        if (content.indexOf(searchTerm) >= 0) {
            return true;
        }

        var senderName = (message.sender_full_name || message.sender_username || "").toLowerCase();
        if (senderName.indexOf(searchTerm) >= 0) {
            return true;
        }

        var attachments = Array.isArray(message.attachments) ? message.attachments : [];
        return attachments.some(function (attachment) {
            var name = (attachment.name || "").toLowerCase();
            return name.indexOf(searchTerm) >= 0;
        });
    }

    function renderMessageList(scrollToBottom) {
        if (!messageListElement) {
            return;
        }

        var previousScrollTop = messageListElement.scrollTop;
        var previousScrollHeight = messageListElement.scrollHeight;
        var nearBottom = previousScrollHeight - (previousScrollTop + messageListElement.clientHeight) < 40;

        if (!state.activeConversationId) {
            messageListElement.innerHTML = '<div class="chat-empty-state">Chon hoi thoai de bat dau chat.</div>';
            return;
        }

        var messages = state.messagesByConversation[state.activeConversationId] || [];
        if (!messages.length) {
            messageListElement.innerHTML = '<div class="chat-empty-state">Hoi thoai nay chua co tin nhan.</div>';
            return;
        }

        var searchTerm = (state.messageSearchTerm || "").trim().toLowerCase();
        var filteredMessages = messages.filter(function (message) {
            return messageMatchesSearch(message, searchTerm);
        });

        if (!filteredMessages.length) {
            messageListElement.innerHTML = '<div class="chat-empty-state">Khong tim thay tin nhan phu hop.</div>';
            return;
        }

        messageListElement.innerHTML = filteredMessages.map(function (message) {
            var isMine = message.sender_id === state.currentUserId;
            var rowClass = isMine ? "me" : "other";
            var seenByOthers = Array.isArray(message.seen_by_user_ids) && message.seen_by_user_ids.some(function (readerId) {
                return toInteger(readerId, 0) !== state.currentUserId;
            });
            var readState = isMine && seenByOthers ? '<span class="chat-read-status">Da xem</span>' : "";
            var reactionSummary = reactionSummaryText(message);

            return '' +
                '<article class="chat-message-row ' + rowClass + '" data-message-id="' + escapeHtml(message.id) + '">' +
                    '<div class="chat-bubble">' +
                        '<div>' + escapeHtml(message.content || "") + '</div>' +
                        attachmentHtml(message) +
                    '</div>' +
                    '<div class="chat-meta">' +
                        '<span>' + escapeHtml(message.sender_full_name || message.sender_username || "User") + '</span>' +
                        '<span>' + escapeHtml(formatRelativeTime(message.created_at)) + '</span>' +
                        readState +
                    '</div>' +
                    '<div class="chat-reaction-line">' + escapeHtml(reactionSummary) + '</div>' +
                    '<div class="chat-reaction-actions" data-message-id="' + escapeHtml(message.id) + '">' +
                        '<button type="button" class="chat-reaction-toggle">Cam xuc</button>' +
                        '<div class="chat-reaction-picker">' +
                            '<button type="button" class="chat-reaction-option" data-reaction="like">👍</button>' +
                            '<button type="button" class="chat-reaction-option" data-reaction="love">❤️</button>' +
                            '<button type="button" class="chat-reaction-option" data-reaction="haha">😆</button>' +
                            '<button type="button" class="chat-reaction-option" data-reaction="wow">😮</button>' +
                            '<button type="button" class="chat-reaction-option" data-reaction="sad">😢</button>' +
                            '<button type="button" class="chat-reaction-option" data-reaction="angry">😡</button>' +
                        '</div>' +
                    '</div>' +
                '</article>';
        }).join("");

        if (scrollToBottom || nearBottom) {
            messageListElement.scrollTop = messageListElement.scrollHeight;
        } else {
            var nextScrollHeight = messageListElement.scrollHeight;
            messageListElement.scrollTop = previousScrollTop + (nextScrollHeight - previousScrollHeight);
        }
    }

    function messagesChanged(conversationId, incoming) {
        var existing = state.messagesByConversation[conversationId] || [];
        if (existing.length !== incoming.length) {
            return true;
        }
        if (!existing.length) {
            return false;
        }
        return existing[existing.length - 1].id !== incoming[incoming.length - 1].id;
    }

    function renderAttachmentPreview() {
        if (!attachmentsPreviewElement || !attachmentsInputElement) {
            return;
        }

        var selectedFiles = Array.from(attachmentsInputElement.files || []);
        if (!selectedFiles.length) {
            attachmentsPreviewElement.innerHTML = "";
            return;
        }

        attachmentsPreviewElement.innerHTML = selectedFiles.map(function (file) {
            return "<li>" + escapeHtml(file.name) + " (" + escapeHtml(fileSizeLabel(file.size)) + ")</li>";
        }).join("");
    }

    function renderFriendResults() {
        if (!friendSearchResultElement) {
            return;
        }

        if (!state.friendCandidates.length) {
            friendSearchResultElement.innerHTML = '<div class="chat-empty-state">Khong tim thay ban be.</div>';
            return;
        }

        friendSearchResultElement.innerHTML = state.friendCandidates.map(function (friend) {
            var subtitle = friend.username || "";
            if (friend.conversation_id) {
                subtitle += " - Da co hoi thoai";
            }

            return '' +
                '<article class="chat-friend-item" data-friend-id="' + escapeHtml(friend.id) + '">' +
                    '<div class="chat-user-summary">' +
                        '<img class="chat-avatar" src="' + escapeHtml(friend.avatar || "") + '" alt="friend avatar">' +
                        '<div class="chat-user-text">' +
                            '<div class="chat-user-name">' + escapeHtml(friend.full_name || friend.username) + '</div>' +
                            '<div class="chat-user-sub">' + escapeHtml(subtitle) + '</div>' +
                        '</div>' +
                    '</div>' +
                    '<button type="button" class="chat-start-btn" data-friend-id="' + escapeHtml(friend.id) + '">Nhan tin</button>' +
                '</article>';
        }).join("");
    }

    function mergeConversation(conversation) {
        var index = state.conversations.findIndex(function (item) {
            return item.id === conversation.id;
        });
        if (index >= 0) {
            state.conversations[index] = conversation;
        } else {
            state.conversations.push(conversation);
        }
    }

    function upsertMessage(conversationId, message) {
        if (!state.messagesByConversation[conversationId]) {
            state.messagesByConversation[conversationId] = [];
        }

        var messages = state.messagesByConversation[conversationId];
        var existingIndex = messages.findIndex(function (item) {
            return item.id === message.id;
        });

        if (existingIndex >= 0) {
            messages[existingIndex] = Object.assign({}, messages[existingIndex], message);
        } else {
            messages.push(message);
        }

        messages.sort(function (left, right) {
            return new Date(left.created_at || 0).getTime() - new Date(right.created_at || 0).getTime();
        });
    }

    async function refreshConversations() {
        try {
            var response = await fetch(urls.listConversations, {
                headers: { "X-Requested-With": "XMLHttpRequest" }
            });
            if (!response.ok) {
                return;
            }

            var payload = await response.json();
            state.conversations = Array.isArray(payload.results) ? payload.results : [];
            renderConversationList();
            renderActiveHeader();
        } catch (error) {
            // keep the current state when refresh fails
        }
    }

    async function loadMessages(conversationId, options) {
        if (!conversationId) {
            return;
        }

        var opts = options || {};

        var endpoint = buildUrl(urls.listMessagesTemplate, conversationId) + "?all=1";
        try {
            var response = await fetch(endpoint, {
                headers: { "X-Requested-With": "XMLHttpRequest" }
            });
            if (!response.ok) {
                return;
            }

            var payload = await response.json();
            var incomingMessages = Array.isArray(payload.results) ? payload.results : [];
            var hasChanges = messagesChanged(conversationId, incomingMessages);
            if (hasChanges) {
                state.messagesByConversation[conversationId] = incomingMessages;
            }

            var conversation = state.conversations.find(function (item) {
                return item.id === conversationId;
            });
            if (conversation && Number.isFinite(payload.unread_count)) {
                conversation.unread_count = payload.unread_count;
            }

            if (hasChanges || opts.forceRender) {
                renderMessageList(Boolean(opts.scrollToBottom));
            }

            if (hasChanges) {
                renderConversationList();
                renderActiveHeader();
            }

            if (!opts.skipMarkRead) {
                markConversationRead(conversationId);
            }
        } catch (error) {
            // ignore temporary errors
        }
    }

    async function markConversationRead(conversationId) {
        if (!conversationId) {
            return;
        }
        sendWsAction({ action: "mark_read" }, conversationId);
    }

    function closeSocket() {
        if (state.ws) {
            try {
                state.ws.close();
            } catch (error) {
                // noop
            }
        }
        state.ws = null;
        state.wsConversationId = null;
        state.wsConnected = false;
    }

    function scheduleReconnect(conversationId) {
        if (state.wsReconnectTimer) {
            return;
        }

        state.wsReconnectAttempts += 1;
        var delayMs = Math.min(1000 * Math.pow(2, state.wsReconnectAttempts), 10000);
        state.wsReconnectTimer = window.setTimeout(function () {
            state.wsReconnectTimer = null;
            if (state.activeConversationId === conversationId) {
                openSocket(conversationId);
            }
        }, delayMs);
    }

    function flushWsQueue() {
        if (!isSocketOpen(state.ws)) {
            return;
        }

        var pending = state.wsQueue.slice();
        state.wsQueue = [];
        pending.forEach(function (entry) {
            if (entry.conversationId && entry.conversationId !== state.wsConversationId) {
                state.wsQueue.push(entry);
                return;
            }
            try {
                state.ws.send(JSON.stringify(entry.payload));
            } catch (error) {
                // keep going even if one payload fails
            }
        });
    }

    function sendWsAction(payload, conversationId) {
        var targetConversationId = conversationId || state.activeConversationId;
        if (isSocketOpen(state.ws) && state.wsConversationId === targetConversationId) {
            state.ws.send(JSON.stringify(payload));
            return true;
        }

        state.wsQueue.push({ conversationId: targetConversationId, payload: payload });
        if (targetConversationId) {
            openSocket(targetConversationId);
        }
        return false;
    }

    function openSocket(conversationId) {
        if (!conversationId) {
            closeSocket();
            return;
        }

        if (state.ws && state.wsConversationId === conversationId) {
            return;
        }

        closeSocket();
        if (!window.WebSocket) {
            return;
        }

        var wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";
        var wsUrl = wsProtocol + "://" + window.location.host + "/ws/chat/" + String(conversationId) + "/";
        if (wsToken) {
            wsUrl += "?token=" + encodeURIComponent(wsToken);
        }
        state.ws = new WebSocket(wsUrl);
        state.wsConversationId = conversationId;
        state.wsConnected = false;

        state.ws.onopen = function () {
            state.wsConnected = true;
            state.wsReconnectAttempts = 0;
            if (state.wsReconnectTimer) {
                window.clearTimeout(state.wsReconnectTimer);
                state.wsReconnectTimer = null;
            }
            flushWsQueue();
        };

        state.ws.onmessage = function (event) {
            var payload = {};
            try {
                payload = JSON.parse(event.data || "{}");
            } catch (error) {
                return;
            }
            handleSocketEvent(payload);
        };

        state.ws.onclose = function () {
            state.wsConnected = false;
            if (state.activeConversationId === state.wsConversationId) {
                window.setTimeout(function () {
                    if (state.activeConversationId === conversationId) {
                        openSocket(conversationId);
                    }
                }, 1200);
            }
            scheduleReconnect(conversationId);
        };

        state.ws.onerror = function () {
            state.wsConnected = false;
            scheduleReconnect(conversationId);
        };
    }

    function touchConversationWithMessage(conversationId, message, shouldIncreaseUnread) {
        var conversation = state.conversations.find(function (item) {
            return item.id === conversationId;
        });

        if (!conversation) {
            refreshConversations();
            return;
        }

        var previewText = message.content || "";
        if (!previewText && Array.isArray(message.attachments) && message.attachments.length) {
            previewText = "[Tin nhan dinh kem]";
        }

        conversation.updated_at = message.created_at || new Date().toISOString();
        conversation.last_message = {
            id: message.id,
            sender_id: message.sender_id,
            sender_username: message.sender_username,
            sender_full_name: message.sender_full_name,
            sender_avatar: message.sender_avatar,
            preview: previewText,
            message_type: message.message_type,
            created_at: message.created_at,
            is_read_by_me: message.sender_id === state.currentUserId
        };

        if (shouldIncreaseUnread) {
            conversation.unread_count = toInteger(conversation.unread_count, 0) + 1;
        }
    }

    function handleSocketEvent(payload) {
        if (!payload || !payload.event) {
            return;
        }

        if (payload.event === "error") {
            if (payload.detail) {
                window.alert(payload.detail);
            }
            return;
        }

        if (payload.event === "message_new") {
            var conversationId = toInteger(payload.conversation_id, null);
            var message = payload.message;
            if (!conversationId || !message) {
                return;
            }

            upsertMessage(conversationId, message);
            var increaseUnread = state.activeConversationId !== conversationId && message.sender_id !== state.currentUserId;
            touchConversationWithMessage(conversationId, message, increaseUnread);

            renderConversationList();
            renderActiveHeader();

            if (state.activeConversationId === conversationId) {
                renderMessageList(true);
                markConversationRead(conversationId);
            }
            return;
        }

        if (payload.event === "conversation_read") {
            var readConversationId = toInteger(payload.conversation_id, null);
            var readerId = toInteger(payload.reader_id, 0);
            var readAt = payload.last_read_at;
            if (!readConversationId || !readAt) {
                return;
            }

            var readAtTime = new Date(readAt).getTime();
            var messages = state.messagesByConversation[readConversationId] || [];
            messages.forEach(function (message) {
                var messageTime = new Date(message.created_at || 0).getTime();
                if (messageTime <= readAtTime) {
                    if (!Array.isArray(message.seen_by_user_ids)) {
                        message.seen_by_user_ids = [];
                    }
                    if (message.seen_by_user_ids.indexOf(readerId) < 0) {
                        message.seen_by_user_ids.push(readerId);
                    }
                }
            });

            var conversation = state.conversations.find(function (item) {
                return item.id === readConversationId;
            });
            if (conversation && readerId === state.currentUserId && Number.isFinite(payload.unread_count)) {
                conversation.unread_count = payload.unread_count;
                if (conversation.last_message) {
                    conversation.last_message.is_read_by_me = true;
                }
            }

            renderConversationList();
            if (state.activeConversationId === readConversationId) {
                renderMessageList(false);
            }
            return;
        }

        if (payload.event === "message_reaction") {
            var reactionConversationId = toInteger(payload.conversation_id, null);
            var messageId = toInteger(payload.message_id, null);
            if (!reactionConversationId || !messageId) {
                return;
            }

            var reactionMessages = state.messagesByConversation[reactionConversationId] || [];
            var reactionMessage = reactionMessages.find(function (item) {
                return item.id === messageId;
            });
            if (!reactionMessage) {
                return;
            }

            reactionMessage.reaction_summary = payload.reaction_summary || {};
            if (toInteger(payload.user_id, 0) === state.currentUserId) {
                reactionMessage.current_user_reaction = payload.reaction_type || null;
            }

            if (state.activeConversationId === reactionConversationId) {
                renderMessageList(false);
            }
        }
    }

    function setActiveConversation(conversationId, options) {
        var opts = options || {};
        state.activeConversationId = conversationId;

        renderConversationList();
        renderActiveHeader();

        if (Array.isArray(opts.messages)) {
            state.messagesByConversation[conversationId] = opts.messages;
            renderMessageList(true);
        } else {
            renderMessageList(false);
            loadMessages(conversationId, { scrollToBottom: true, forceRender: true });
        }

        openSocket(conversationId);
        markConversationRead(conversationId);
    }

    async function sendMessage(event) {
        event.preventDefault();

        if (!state.activeConversationId || state.sending) {
            return;
        }

        if (!isSocketOpen(state.ws) || state.wsConversationId !== state.activeConversationId) {
            window.alert("Mat ket noi realtime. Vui long tai lai trang.");
            return;
        }

        var content = (messageInputElement.value || "").trim();
        var selectedFiles = Array.from(attachmentsInputElement.files || []);

        if (!content && !selectedFiles.length) {
            return;
        }

        for (var index = 0; index < selectedFiles.length; index += 1) {
            if (selectedFiles[index].size >= MAX_ATTACHMENT_SIZE_BYTES) {
                window.alert("Moi file phai nho hon 20MB.");
                return;
            }
        }

        state.sending = true;
        sendButtonElement.disabled = true;

        try {
            var wsAttachments = [];
            if (selectedFiles.length) {
                try {
                    wsAttachments = await buildWsAttachments(selectedFiles);
                } catch (error) {
                    window.alert("Khong the doc file dinh kem.");
                    return;
                }
            }

            sendWsAction({
                action: "send_message",
                content: content,
                attachments: wsAttachments
            }, state.activeConversationId);

            messageInputElement.value = "";
            attachmentsInputElement.value = "";
            renderAttachmentPreview();
        } catch (error) {
            window.alert("Khong the gui tin nhan. Vui long thu lai.");
        } finally {
            state.sending = false;
            sendButtonElement.disabled = false;
        }
    }

    async function toggleReaction(messageId, reactionType) {
        sendWsAction({
            action: "toggle_reaction",
            message_id: messageId,
            reaction: reactionType
        }, state.activeConversationId);
    }

    async function searchFriends() {
        var query = (state.friendSearchTerm || "").trim();
        var endpoint = urls.searchFriends;
        if (query) {
            endpoint += "?q=" + encodeURIComponent(query);
        }

        try {
            var response = await fetch(endpoint, {
                headers: { "X-Requested-With": "XMLHttpRequest" }
            });
            if (!response.ok) {
                return;
            }
            var payload = await response.json();
            state.friendCandidates = Array.isArray(payload.results) ? payload.results : [];
            renderFriendResults();
        } catch (error) {
            // keep current friend list
        }
    }

    async function startChatWithFriend(friendId, triggerButton) {
        if (!friendId) {
            return;
        }

        if (triggerButton) {
            triggerButton.disabled = true;
        }

        try {
            var response = await fetch(buildUrl(urls.startFriendChatTemplate, friendId), {
                method: "POST",
                headers: {
                    "X-CSRFToken": getCookie("csrftoken"),
                    "X-Requested-With": "XMLHttpRequest"
                }
            });
            var payload = await response.json();

            if (!response.ok) {
                window.alert(payload.error || "Khong the bat dau hoi thoai.");
                return;
            }

            if (payload.conversation) {
                mergeConversation(payload.conversation);
            }

            if (payload.conversation && Array.isArray(payload.messages)) {
                state.messagesByConversation[payload.conversation.id] = payload.messages;
                setActiveConversation(payload.conversation.id, { messages: payload.messages });
            }

            var candidate = state.friendCandidates.find(function (item) {
                return item.id === friendId;
            });
            if (candidate && payload.conversation) {
                candidate.conversation_id = payload.conversation.id;
            }

            renderFriendResults();
        } catch (error) {
            window.alert("Khong the bat dau hoi thoai.");
        } finally {
            if (triggerButton) {
                triggerButton.disabled = false;
            }
        }
    }

    function bindEvents() {
        if (conversationFilterInputElement) {
            conversationFilterInputElement.addEventListener("input", function (event) {
                state.conversationFilterTerm = event.target.value || "";
                renderConversationList();
            });
        }

        if (messageSearchInputElement) {
            messageSearchInputElement.addEventListener("input", function (event) {
                state.messageSearchTerm = event.target.value || "";
                renderMessageList(false);
            });
        }

        if (friendSearchInputElement) {
            var friendSearchTimer = null;
            friendSearchInputElement.addEventListener("input", function (event) {
                state.friendSearchTerm = event.target.value || "";
                window.clearTimeout(friendSearchTimer);
                friendSearchTimer = window.setTimeout(searchFriends, 250);
            });
        }

        if (conversationListElement) {
            conversationListElement.addEventListener("click", function (event) {
                var item = event.target.closest(".chat-conversation-item");
                if (!item) {
                    return;
                }
                var conversationId = toInteger(item.dataset.conversationId, null);
                if (!conversationId) {
                    return;
                }
                setActiveConversation(conversationId);
            });
        }

        if (composeFormElement) {
            composeFormElement.addEventListener("submit", sendMessage);
        }

        if (attachmentsInputElement) {
            attachmentsInputElement.addEventListener("change", renderAttachmentPreview);
        }

        if (messageListElement) {
            messageListElement.addEventListener("click", function (event) {
                var toggleButton = event.target.closest(".chat-reaction-toggle");
                if (toggleButton) {
                    var parent = toggleButton.closest(".chat-reaction-actions");
                    if (!parent) {
                        return;
                    }
                    var picker = parent.querySelector(".chat-reaction-picker");
                    if (!picker) {
                        return;
                    }

                    var isVisible = picker.classList.contains("show");
                    document.querySelectorAll(".chat-reaction-picker.show").forEach(function (item) {
                        item.classList.remove("show");
                    });
                    if (!isVisible) {
                        picker.classList.add("show");
                    }
                    return;
                }

                var reactionButton = event.target.closest(".chat-reaction-option");
                if (reactionButton) {
                    var actions = reactionButton.closest(".chat-reaction-actions");
                    var messageId = actions ? toInteger(actions.dataset.messageId, null) : null;
                    var reactionType = reactionButton.dataset.reaction;
                    if (messageId && reactionType) {
                        toggleReaction(messageId, reactionType);
                    }

                    document.querySelectorAll(".chat-reaction-picker.show").forEach(function (item) {
                        item.classList.remove("show");
                    });
                }
            });
        }

        if (friendSearchResultElement) {
            friendSearchResultElement.addEventListener("click", function (event) {
                var startButton = event.target.closest(".chat-start-btn");
                if (!startButton) {
                    return;
                }
                var friendId = toInteger(startButton.dataset.friendId, null);
                if (!friendId) {
                    return;
                }
                startChatWithFriend(friendId, startButton);
            });
        }

        document.addEventListener("click", function (event) {
            if (!event.target.closest(".chat-reaction-actions")) {
                document.querySelectorAll(".chat-reaction-picker.show").forEach(function (item) {
                    item.classList.remove("show");
                });
            }
        });

        window.addEventListener("beforeunload", closeSocket);
    }

    function initialize() {
        renderConversationList();
        renderFriendResults();
        renderAttachmentPreview();
        bindEvents();

        if (state.activeConversationId) {
            var cachedMessages = state.messagesByConversation[state.activeConversationId];
            if (Array.isArray(cachedMessages) && cachedMessages.length) {
                setActiveConversation(state.activeConversationId, { messages: cachedMessages });
                return;
            }
            setActiveConversation(state.activeConversationId);
            return;
        }

        if (state.conversations.length) {
            setActiveConversation(state.conversations[0].id);
            return;
        }

        renderActiveHeader();
        renderMessageList(false);
    }

    initialize();
})();
