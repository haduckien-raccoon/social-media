(function () {
    "use strict";

    // ─── Constants ────────────────────────────────────────────────────────────
    var MAX_ATTACHMENT_SIZE_BYTES = 20 * 1024 * 1024;
    var MESSAGE_PAGE_SIZE = 30;
    var SCROLL_LOAD_THRESHOLD = 200;
    var REACTION_EMOJI = { like: "👍", love: "❤️", haha: "😆", wow: "😮", sad: "😢", angry: "😡" };

    // ─── Helpers ──────────────────────────────────────────────────────────────
    function parseScriptJSON(id, fallback) {
        var el = document.getElementById(id);
        if (!el || !el.textContent) return fallback;
        try { return JSON.parse(el.textContent); } catch (e) { return fallback; }
    }

    function toInt(val, fb) {
        var n = Number.parseInt(val, 10);
        return Number.isFinite(n) ? n : fb;
    }

    function escapeHtml(val) {
        var d = document.createElement("div");
        d.textContent = val == null ? "" : String(val);
        return d.innerHTML;
    }

    function getCookie(name) {
        var match = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
        return match ? decodeURIComponent(match[1]) : null;
    }

    function buildUrl(tpl, id) {
        return String(tpl || "").replace("/0/", "/" + String(id) + "/");
    }

    function fileSizeLabel(n) {
        if (n < 1024) return n + " B";
        if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
        return (n / 1048576).toFixed(1) + " MB";
    }

    function formatTime(iso) {
        if (!iso) return "";
        var d = new Date(iso);
        if (isNaN(d)) return "";
        var now = Date.now();
        var diff = Math.floor((now - d.getTime()) / 1000);
        if (diff < 60) return "Vừa xong";
        if (diff < 3600) return Math.floor(diff / 60) + " phút";
        if (diff < 86400) return Math.floor(diff / 3600) + " giờ";
        var dd = Math.floor(diff / 86400);
        if (dd < 7) return dd + " ngày";
        return d.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" });
    }

    function formatFullTime(iso) {
        if (!iso) return "";
        var d = new Date(iso);
        if (isNaN(d)) return "";
        return d.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
    }

    function readFileAsBase64(file) {
        return new Promise(function (resolve, reject) {
            var r = new FileReader();
            r.onload = function () {
                var s = String(r.result || "");
                var i = s.indexOf(",");
                resolve(i >= 0 ? s.slice(i + 1) : s);
            };
            r.onerror = function () { reject(r.error || new Error("Read failed")); };
            r.readAsDataURL(file);
        });
    }

    async function buildWsAttachments(files) {
        return Promise.all(files.map(async function (f) {
            return {
                name: f.name,
                content_type: f.type || "application/octet-stream",
                content_base64: await readFileAsBase64(f)
            };
        }));
    }

    function isSocketOpen(ws) { return ws && ws.readyState === WebSocket.OPEN; }

    // ─── DOM refs ─────────────────────────────────────────────────────────────
    var cfg = document.getElementById("chat-config");
    if (!cfg) return;

    var elConvList      = document.getElementById("conversation-list");
    var elFriendResults = document.getElementById("friend-search-results");
    var elFriendResultsInline = document.getElementById("friend-search-inline-results");
    var elFriendSearch  = document.getElementById("friend-search-input");
    var elConvFilter    = document.getElementById("conversation-filter-input");
    var elMsgList       = document.getElementById("chat-message-list");
    var elHeader        = document.getElementById("chat-active-header");
    var elMsgSearch     = document.getElementById("chat-message-search-input");
    var elForm          = document.getElementById("chat-compose-form");
    var elInput         = document.getElementById("chat-message-input");
    var elFiles         = document.getElementById("chat-attachments-input");
    var elFilesPreview  = document.getElementById("chat-attachments-preview");
    var elSendBtn       = document.getElementById("chat-send-button");

    // ─── URLs ─────────────────────────────────────────────────────────────────
    var urls = {
        listConversations:   cfg.dataset.listConversationsUrl,
        listMsgsTpl:         cfg.dataset.listMessagesTemplate,
        sendMsgTpl:          cfg.dataset.sendMessageTemplate,
        markReadTpl:         cfg.dataset.markReadTemplate,
        toggleReactionTpl:   cfg.dataset.toggleReactionTemplate,
        searchFriends:       cfg.dataset.searchFriendsUrl,
        startFriendChatTpl:  cfg.dataset.startFriendChatTemplate
    };

    var wsToken = cfg.dataset.wsToken || "";

    // ─── State ────────────────────────────────────────────────────────────────
    var state = {
        currentUserId:      toInt(cfg.dataset.currentUserId, 0),
        activeConvId:       toInt(cfg.dataset.activeConversationId, null),
        conversations:      parseScriptJSON("chat-initial-conversations", []),
        friendCandidates:   parseScriptJSON("chat-initial-friends", []),
        msgsByConv:         {},
        paging:             {},
        ws:                 null,
        wsConvId:           null,
        wsConnected:        false,
        wsQueue:            [],
        wsReconnectTimer:   null,
        wsReconnectAttempts:0,
        sending:            false,
        stickToBottom:      true,
        convFilter:         "",
        friendSearch:       "",
        msgSearch:          "",
        typingTimers:       {},
        isTyping:           false,
        typingDebounce:     null
    };

    var friendResultsTarget = null;

    function pickFriendResultsTarget() {
        var useInline = window.matchMedia("(max-width: 1100px)").matches;
        friendResultsTarget = (useInline && elFriendResultsInline) ? elFriendResultsInline : elFriendResults;
        return friendResultsTarget;
    }

    // Bỏ qua lấy tin nhắn ban đầu từ DOM để ép lazy load qua API
    var initMsgs = parseScriptJSON("chat-initial-messages", []); 
    if (state.activeConvId && Array.isArray(initMsgs) && initMsgs.length) {
        var sorted = initMsgs.slice().sort(function (a, b) {
            return new Date(a.created_at || 0) - new Date(b.created_at || 0);
        });
        state.msgsByConv[state.activeConvId] = sorted;
        _setPaging(state.activeConvId, sorted, MESSAGE_PAGE_SIZE, false, sorted.length);
    }

    // ─── Paging helpers ───────────────────────────────────────────────────────
    function _getPaging(convId) {
        if (!convId) return { oldestId: null, hasMore: true, loading: false };
        if (!state.paging[convId]) state.paging[convId] = { oldestId: null, hasMore: true, loading: false };
        return state.paging[convId];
    }

    function _setPaging(convId, msgs, pageSize, isOlder, count) {
        var p = _getPaging(convId);
        if (Array.isArray(msgs) && msgs.length) p.oldestId = msgs[0].id;
        var c = Number.isFinite(count) ? count : (Array.isArray(msgs) ? msgs.length : 0);
        if (isOlder) { if (c < pageSize) p.hasMore = false; }
        else { p.hasMore = c >= pageSize; }
        return p;
    }

    // ─── Conversation helpers ─────────────────────────────────────────────────
    function convTitle(conv) {
        var ps = Array.isArray(conv.participants) ? conv.participants : [];
        if (!ps.length) return "Hội thoại";
        return ps.map(function (p) { return p.full_name || p.username; }).join(", ");
    }

    function convAvatar(conv) {
        var ps = Array.isArray(conv.participants) ? conv.participants : [];
        if (!ps.length) return "https://ui-avatars.com/api/?name=Chat";
        var p = ps[0];
        return p.avatar || "https://ui-avatars.com/api/?name=" + encodeURIComponent(p.username || "U");
    }

    function convSubtitle(conv) {
        var lm = conv.last_message;
        if (!lm) return "Chưa có tin nhắn";
        var preview = lm.preview || "Tin nhắn mới";
        if (lm.sender_id === state.currentUserId) preview = "Bạn: " + preview;
        return preview;
    }

    function sortConvs() {
        state.conversations.sort(function (a, b) {
            return new Date(b.updated_at || b.created_at || 0) - new Date(a.updated_at || a.created_at || 0);
        });
    }

    // ─── Render: Conversation List ────────────────────────────────────────────
    function renderConvList() {
        if (!elConvList) return;
        sortConvs();
        var term = state.convFilter.trim().toLowerCase();
        var filtered = state.conversations.filter(function (c) {
            if (!term) return true;
            return convTitle(c).toLowerCase().includes(term) || convSubtitle(c).toLowerCase().includes(term);
        });

        if (!filtered.length) {
            elConvList.innerHTML = '<div class="chat-empty-state">Không tìm thấy hội thoại.</div>';
            return;
        }

        elConvList.innerHTML = filtered.map(function (c) {
            var isActive = state.activeConvId === c.id;
            var unread = toInt(c.unread_count, 0);
            var lm = c.last_message;
            var isUnread = unread > 0;

            return '<article class="chat-conv-item' + (isActive ? " active" : "") + (isUnread ? " unread" : "") + '" data-id="' + c.id + '">' +
                '<div class="chat-conv-avatar-wrap">' +
                    '<img class="chat-avatar" src="' + escapeHtml(convAvatar(c)) + '" alt="">' +
                    '<span class="chat-online-dot"></span>' +
                '</div>' +
                '<div class="chat-conv-text">' +
                    '<div class="chat-conv-row">' +
                        '<span class="chat-conv-name' + (isUnread ? " fw-bold" : "") + '">' + escapeHtml(convTitle(c)) + '</span>' +
                        '<span class="chat-conv-time">' + escapeHtml(lm ? formatTime(lm.created_at) : "") + '</span>' +
                    '</div>' +
                    '<div class="chat-conv-row">' +
                        '<span class="chat-conv-preview' + (isUnread ? " fw-bold" : "") + '">' + escapeHtml(convSubtitle(c)) + '</span>' +
                        (isUnread ? '<span class="chat-unread-dot"></span>' : '') +
                    '</div>' +
                '</div>' +
            '</article>';
        }).join("");
    }

    // ─── Render: Active Header ────────────────────────────────────────────────
    function renderHeader() {
        if (!elHeader) return;
        if (!state.activeConvId) {
            elHeader.innerHTML =
                '<div class="chat-header-empty">' +
                    '<span class="chat-header-logo-dot"></span>' +
                    '<div><h3>Messenger</h3><p>Chọn một cuộc trò chuyện để bắt đầu</p></div>' +
                '</div>' +
                '<div class="chat-header-actions"><input id="chat-message-search-input" type="text" placeholder="🔍 Tìm tin nhắn..."></div>';
            rebindMsgSearch();
            return;
        }
        var conv = state.conversations.find(function (c) { return c.id === state.activeConvId; });
        if (!conv) return;
        var avatarSrc = convAvatar(conv);
        var title = convTitle(conv);

        elHeader.innerHTML =
            '<div class="chat-header-info">' +
                '<div class="chat-header-avatar-wrap">' +
                    '<img class="chat-header-avatar" src="' + escapeHtml(avatarSrc) + '" alt="">' +
                    '<span class="chat-online-dot"></span>' +
                '</div>' +
                '<div class="chat-header-text">' +
                    '<h3>' + escapeHtml(title) + '</h3>' +
                    '<span class="chat-header-status">' + (state.wsConnected ? '🟢 Đang hoạt động' : '⚪ Đang kết nối...') + '</span>' +
                '</div>' +
            '</div>' +
            '<div class="chat-header-actions">' +
                '<input id="chat-message-search-input" type="text" placeholder="🔍 Tìm tin nhắn...">' +
            '</div>';
        rebindMsgSearch();
    }

    function rebindMsgSearch() {
        var el = document.getElementById("chat-message-search-input");
        if (el) {
            el.value = state.msgSearch;
            el.addEventListener("input", function (e) {
                state.msgSearch = e.target.value || "";
                renderMsgList(false);
            });
        }
    }

    // ─── Render: Messages ─────────────────────────────────────────────────────
    function msgMatchesSearch(msg, term) {
        if (!term) return true;
        if ((msg.content || "").toLowerCase().includes(term)) return true;
        if ((msg.sender_full_name || msg.sender_username || "").toLowerCase().includes(term)) return true;
        return (msg.attachments || []).some(function (a) { return (a.name || "").toLowerCase().includes(term); });
    }

    function attachmentHtml(msg) {
        var atts = Array.isArray(msg.attachments) ? msg.attachments : [];
        if (!atts.length) return "";
        return '<div class="chat-attachments">' + atts.map(function (a) {
            var ct = a.content_type || "";
            if (ct.startsWith("image/")) {
                return '<a href="' + escapeHtml(a.url || "#") + '" target="_blank" rel="noopener noreferrer">' +
                    '<img class="chat-att-img" src="' + escapeHtml(a.url || "") + '" alt="ảnh">' +
                    '</a>';
            }
            return '<a class="chat-att-file" href="' + escapeHtml(a.url || "#") + '" target="_blank" rel="noopener noreferrer">' +
                '<span class="chat-att-icon">📎</span>' +
                '<span class="chat-att-name">' + escapeHtml(a.name || "tệp") + '</span>' +
                '<span class="chat-att-size">(' + escapeHtml(fileSizeLabel(toInt(a.size, 0))) + ')</span>' +
                '</a>';
        }).join("") + '</div>';
    }

    function reactionBar(msg) {
        var summary = msg.reaction_summary || {};
        var keys = Object.keys(summary);
        if (!keys.length) return "";
        var parts = keys.map(function (k) {
            return '<span class="chat-rxn-chip" title="' + escapeHtml(k) + '">' +
                escapeHtml(REACTION_EMOJI[k] || k) + ' ' +
                escapeHtml(String(summary[k])) +
            '</span>';
        }).join("");
        return '<div class="chat-rxn-bar">' + parts + '</div>';
    }

    function reactionPicker(msg) {
        var myRxn = msg.current_user_reaction || "";
        return '<div class="chat-rxn-actions" data-msg-id="' + escapeHtml(msg.id) + '">' +
            '<button type="button" class="chat-rxn-toggle" title="Cảm xúc">🙂</button>' +
            '<div class="chat-rxn-picker">' +
                Object.keys(REACTION_EMOJI).map(function (k) {
                    return '<button type="button" class="chat-rxn-opt' + (myRxn === k ? " active" : "") + '" data-rxn="' + k + '" title="' + k + '">' +
                        REACTION_EMOJI[k] +
                    '</button>';
                }).join("") +
            '</div>' +
        '</div>';
    }

    function shouldShowAvatar(msgs, idx) {
        var msg = msgs[idx];
        if (msg.sender_id === state.currentUserId) return false;
        var next = msgs[idx + 1];
        if (!next) return true;
        return next.sender_id !== msg.sender_id;
    }

    function shouldShowTime(msgs, idx) {
        var msg = msgs[idx];
        var prev = msgs[idx - 1];
        if (!prev) return true;
        var diff = new Date(msg.created_at || 0) - new Date(prev.created_at || 0);
        return diff > 5 * 60 * 1000;
    }

    function renderMsgList(forceBottom) {
        if (!elMsgList) return;

        var prevScrollTop = elMsgList.scrollTop;
        var prevScrollH   = elMsgList.scrollHeight;
        var clientH       = elMsgList.clientHeight;
        var nearBottom    = (prevScrollH - prevScrollTop - clientH) < 80;

        if (!state.activeConvId) {
            elMsgList.innerHTML = '<div class="chat-empty-state">Chọn hội thoại để bắt đầu nhắn tin 💬</div>';
            return;
        }

        var msgs = state.msgsByConv[state.activeConvId] || [];
        if (!msgs.length) {
            elMsgList.innerHTML = '<div class="chat-empty-state">Chưa có tin nhắn nào. Hãy gửi tin nhắn đầu tiên! 👋</div>';
            return;
        }

        var paging = _getPaging(state.activeConvId);
        var term   = (state.msgSearch || "").trim().toLowerCase();
        var filtered = msgs.filter(function (m) { return msgMatchesSearch(m, term); });

        if (!filtered.length) {
            elMsgList.innerHTML = '<div class="chat-empty-state">Không tìm thấy tin nhắn phù hợp.</div>';
            return;
        }

        var topHtml = "";
        if (!term) {
            if (paging.loading) {
                topHtml = '<div class="chat-history-loader loading"><span class="chat-spinner"></span> Đang tải...</div>';
            } else if (paging.hasMore) {
                topHtml = '<div class="chat-history-loader hint">Kéo lên để xem tin nhắn cũ hơn ↑</div>';
            } else {
                topHtml = '<div class="chat-history-loader end">— Đầu cuộc hội thoại —</div>';
            }
        }

        var html = "";
        var lastDate = "";
        filtered.forEach(function (msg, idx) {
            var isMine = msg.sender_id === state.currentUserId;
            var msgDate = msg.created_at ? new Date(msg.created_at).toLocaleDateString("vi-VN") : "";

            if (msgDate && msgDate !== lastDate) {
                lastDate = msgDate;
                html += '<div class="chat-date-sep"><span>' + escapeHtml(msgDate) + '</span></div>';
            }

            var showTime = shouldShowTime(filtered, idx);
            var showAvatar = shouldShowAvatar(filtered, idx);
            var seenByOthers = isMine && Array.isArray(msg.seen_by_user_ids) && msg.seen_by_user_ids.some(function (id) {
                return toInt(id, 0) !== state.currentUserId;
            });

            var nextMsg = filtered[idx + 1];
            var prevMsg = filtered[idx - 1];
            var sameAsPrev = prevMsg && prevMsg.sender_id === msg.sender_id;
            var sameAsNext = nextMsg && nextMsg.sender_id === msg.sender_id;
            var bubblePos = "";
            if (!sameAsPrev && !sameAsNext) bubblePos = "solo";
            else if (!sameAsPrev) bubblePos = "top";
            else if (!sameAsNext) bubblePos = "bottom";
            else bubblePos = "mid";

            var avatarHtml = "";
            if (!isMine) {
                avatarHtml = showAvatar
                    ? '<img class="chat-msg-avatar" src="' + escapeHtml(msg.sender_avatar || "https://ui-avatars.com/api/?name=" + encodeURIComponent(msg.sender_username || "U")) + '" alt="">'
                    : '<span class="chat-msg-avatar-spacer"></span>';
            }

            var contentHtml = escapeHtml(msg.content || "");
            contentHtml = contentHtml.replace(/(https?:\/\/[^\s<>"]+)/g, function (url) {
                return '<a href="' + escapeHtml(url) + '" target="_blank" rel="noopener noreferrer" class="chat-link">' + escapeHtml(url) + '</a>';
            });

            html +=
                '<div class="chat-msg-row ' + (isMine ? "me" : "other") + ' pos-' + bubblePos + '" data-msg-id="' + escapeHtml(msg.id) + '">' +
                    avatarHtml +
                    '<div class="chat-msg-body">' +
                        (showTime ? '<div class="chat-msg-time-label">' + escapeHtml(formatFullTime(msg.created_at)) + '</div>' : '') +
                        '<div class="chat-bubble pos-' + bubblePos + '">' +
                            '<div class="chat-bubble-content">' + contentHtml + '</div>' +
                            attachmentHtml(msg) +
                        '</div>' +
                        reactionBar(msg) +
                        '<div class="chat-msg-meta">' +
                            (seenByOthers ? '<span class="chat-seen">✓✓ Đã xem</span>' : '') +
                        '</div>' +
                        reactionPicker(msg) +
                    '</div>' +
                '</div>';
        });

        elMsgList.innerHTML = topHtml + html;

        // Xử lý scroll đồng bộ ngay sau khi cập nhật DOM
        var newScrollH = elMsgList.scrollHeight;
        if (forceBottom || state.stickToBottom || nearBottom) {
            elMsgList.scrollTop = elMsgList.scrollHeight;
            state.stickToBottom = true;
            
            var images = elMsgList.querySelectorAll('img');
            images.forEach(function(img) {
                img.addEventListener('load', function() {
                    elMsgList.scrollTop = elMsgList.scrollHeight;
                });
            });
        } else {
            // Giữ nguyên vị trí cuộn mượt mà khi chèn thêm tin nhắn cũ lên đầu
            elMsgList.scrollTop = prevScrollTop + (newScrollH - prevScrollH);
            state.stickToBottom = false;
        }
    }

    // ─── Render: Friend results ───────────────────────────────────────────────
    function renderFriends() {
        var target = friendResultsTarget || pickFriendResultsTarget();
        if (!target) return;
        if (!(state.friendSearch || "").trim()) {
            target.innerHTML = "";
            return;
        }
        if (!state.friendCandidates.length) {
            target.innerHTML = '<div class="chat-empty-state">Chưa có bạn bè nào.</div>';
            return;
        }
        target.innerHTML = state.friendCandidates.map(function (f) {
            var sub = f.conversation_id ? "Đã có hội thoại" : "@" + (f.username || "");
            return '<article class="chat-friend-item" data-id="' + f.id + '">' +
                '<img class="chat-avatar" src="' + escapeHtml(f.avatar || "") + '" alt="">' +
                '<div class="chat-user-text">' +
                    '<div class="chat-user-name">' + escapeHtml(f.full_name || f.username) + '</div>' +
                    '<div class="chat-user-sub">' + escapeHtml(sub) + '</div>' +
                '</div>' +
                '<button type="button" class="chat-start-btn" data-friend-id="' + f.id + '">Nhắn tin</button>' +
            '</article>';
        }).join("");
    }

    // ─── Render: Attachment preview ───────────────────────────────────────────
    function renderFilesPreview() {
        if (!elFilesPreview || !elFiles) return;
        var files = Array.from(elFiles.files || []);
        if (!files.length) { elFilesPreview.innerHTML = ""; return; }
        elFilesPreview.innerHTML = files.map(function (f) {
            return '<li><span class="chat-file-chip">📎 ' + escapeHtml(f.name) + ' <em>(' + escapeHtml(fileSizeLabel(f.size)) + ')</em></span></li>';
        }).join("");
    }

    // ─── Data mutations ───────────────────────────────────────────────────────
    function upsertMsg(convId, msg) {
        if (!state.msgsByConv[convId]) state.msgsByConv[convId] = [];
        var msgs = state.msgsByConv[convId];
        var idx = msgs.findIndex(function (m) { return m.id === msg.id; });
        if (idx >= 0) msgs[idx] = Object.assign({}, msgs[idx], msg);
        else msgs.push(msg);
        msgs.sort(function (a, b) { return new Date(a.created_at || 0) - new Date(b.created_at || 0); });
    }

    function mergeConv(conv) {
        var idx = state.conversations.findIndex(function (c) { return c.id === conv.id; });
        if (idx >= 0) state.conversations[idx] = conv;
        else state.conversations.unshift(conv);
    }

    function touchConvWithMsg(convId, msg, increaseUnread) {
        var conv = state.conversations.find(function (c) { return c.id === convId; });
        if (!conv) { refreshConvs(); return; }
        var preview = msg.content || (msg.attachments && msg.attachments.length ? "[Tệp đính kèm]" : "");
        conv.updated_at = msg.created_at || new Date().toISOString();
        conv.last_message = {
            id: msg.id, sender_id: msg.sender_id, sender_username: msg.sender_username,
            sender_full_name: msg.sender_full_name, sender_avatar: msg.sender_avatar,
            preview: preview, message_type: msg.message_type,
            created_at: msg.created_at,
            is_read_by_me: msg.sender_id === state.currentUserId
        };
        if (increaseUnread) conv.unread_count = toInt(conv.unread_count, 0) + 1;
    }

    // ─── WebSocket ────────────────────────────────────────────────────────────
    function sendWs(payload, convId) {
        var target = convId || state.activeConvId;
        if (isSocketOpen(state.ws) && state.wsConvId === target) {
            state.ws.send(JSON.stringify(payload));
            return true;
        }
        state.wsQueue.push({ convId: target, payload: payload });
        if (target) openSocket(target);
        return false;
    }

    function flushWsQueue() {
        if (!isSocketOpen(state.ws)) return;
        var pending = state.wsQueue.slice();
        state.wsQueue = [];
        pending.forEach(function (entry) {
            if (entry.convId && entry.convId !== state.wsConvId) { state.wsQueue.push(entry); return; }
            try { state.ws.send(JSON.stringify(entry.payload)); } catch (e) { /* noop */ }
        });
    }

    function scheduleReconnect(convId) {
        if (state.wsReconnectTimer) return;
        state.wsReconnectAttempts += 1;
        var delay = Math.min(1000 * Math.pow(2, state.wsReconnectAttempts), 10000);
        state.wsReconnectTimer = setTimeout(function () {
            state.wsReconnectTimer = null;
            if (state.activeConvId === convId) openSocket(convId);
        }, delay);
    }

    function closeSocket() {
        if (state.ws) { try { state.ws.close(); } catch (e) { /* noop */ } }
        state.ws = null; state.wsConvId = null; state.wsConnected = false;
    }

    function openSocket(convId) {
        if (!convId) { closeSocket(); return; }
        if (state.ws && state.wsConvId === convId) return;
        closeSocket();
        if (!window.WebSocket) return;
        var proto = location.protocol === "https:" ? "wss" : "ws";
        var url = proto + "://" + location.host + "/ws/chat/" + convId + "/";
        if (wsToken) url += "?token=" + encodeURIComponent(wsToken);
        state.ws = new WebSocket(url);
        state.wsConvId = convId;
        state.wsConnected = false;

        state.ws.onopen = function () {
            state.wsConnected = true;
            state.wsReconnectAttempts = 0;
            if (state.wsReconnectTimer) { clearTimeout(state.wsReconnectTimer); state.wsReconnectTimer = null; }
            flushWsQueue();
            renderHeader();
        };

        state.ws.onmessage = function (e) {
            var payload;
            try { payload = JSON.parse(e.data || "{}"); } catch (err) { return; }
            handleWsEvent(payload);
        };

        state.ws.onclose = function () {
            state.wsConnected = false;
            renderHeader();
            if (state.activeConvId === state.wsConvId) {
                setTimeout(function () {
                    if (state.activeConvId === convId) openSocket(convId);
                }, 1500);
            }
            scheduleReconnect(convId);
        };

        state.ws.onerror = function () {
            state.wsConnected = false;
            scheduleReconnect(convId);
        };
    }

    function handleWsEvent(payload) {
        if (!payload || !payload.event) return;

        if (payload.event === "error") {
            console.warn("[chat ws error]", payload.detail);
            return;
        }

        if (payload.event === "message_new") {
            var convId = toInt(payload.conversation_id, null);
            var msg = payload.message;
            if (!convId || !msg) return;
            upsertMsg(convId, msg);
            var increaseUnread = state.activeConvId !== convId && msg.sender_id !== state.currentUserId;
            touchConvWithMsg(convId, msg, increaseUnread);
            renderConvList();
            renderHeader();
            if (state.activeConvId === convId) {
                renderMsgList(true);
                markRead(convId);
                showNotification(msg);
            }
            return;
        }

        if (payload.event === "conversation_read") {
            var rConvId = toInt(payload.conversation_id, null);
            var readerId = toInt(payload.reader_id, 0);
            var readAt = payload.last_read_at;
            if (!rConvId || !readAt) return;
            var readAtMs = new Date(readAt).getTime();
            (state.msgsByConv[rConvId] || []).forEach(function (m) {
                var mMs = new Date(m.created_at || 0).getTime();
                if (mMs <= readAtMs) {
                    if (!Array.isArray(m.seen_by_user_ids)) m.seen_by_user_ids = [];
                    if (!m.seen_by_user_ids.includes(readerId)) m.seen_by_user_ids.push(readerId);
                }
            });
            var conv = state.conversations.find(function (c) { return c.id === rConvId; });
            if (conv && readerId === state.currentUserId && Number.isFinite(payload.unread_count)) {
                conv.unread_count = payload.unread_count;
                if (conv.last_message) conv.last_message.is_read_by_me = true;
            }
            renderConvList();
            if (state.activeConvId === rConvId) renderMsgList(false);
            return;
        }

        if (payload.event === "message_reaction") {
            var rxConvId = toInt(payload.conversation_id, null);
            var msgId = toInt(payload.message_id, null);
            if (!rxConvId || !msgId) return;
            var m = (state.msgsByConv[rxConvId] || []).find(function (x) { return x.id === msgId; });
            if (!m) return;
            m.reaction_summary = payload.reaction_summary || {};
            if (toInt(payload.user_id, 0) === state.currentUserId) m.current_user_reaction = payload.reaction_type || null;
            if (state.activeConvId === rxConvId) renderMsgList(false);
        }
    }

    // ─── Notification ─────────────────────────────────────────────────────────
    function showNotification(msg) {
        if (document.hasFocus()) return;
        if (!("Notification" in window) || Notification.permission !== "granted") return;
        var sender = msg.sender_full_name || msg.sender_username || "Tin nhắn mới";
        var body = msg.content || (msg.attachments && msg.attachments.length ? "Đã gửi tệp đính kèm" : "");
        var n = new Notification(sender, { body: body, icon: msg.sender_avatar || "" });
        setTimeout(function () { n.close(); }, 4000);
    }

    function requestNotificationPermission() {
        if ("Notification" in window && Notification.permission === "default") {
            Notification.requestPermission();
        }
    }

    // ─── API calls ────────────────────────────────────────────────────────────
    async function refreshConvs() {
        try {
            var res = await fetch(urls.listConversations, { headers: { "X-Requested-With": "XMLHttpRequest" } });
            if (!res.ok) return;
            var data = await res.json();
            state.conversations = Array.isArray(data.results) ? data.results : [];
            renderConvList();
            renderHeader();
        } catch (e) { /* noop */ }
    }

    async function loadMessages(convId, opts) {
        opts = opts || {};
        var limit = toInt(opts.limit, MESSAGE_PAGE_SIZE) || MESSAGE_PAGE_SIZE;
        var endpoint = buildUrl(urls.listMsgsTpl, convId) + "?limit=" + limit;
        if (opts.beforeId) endpoint += "&before_id=" + encodeURIComponent(opts.beforeId);
        try {
            var res = await fetch(endpoint, { headers: { "X-Requested-With": "XMLHttpRequest" } });
            if (!res.ok) return;
            var data = await res.json();
            var incoming = Array.isArray(data.results) ? data.results : [];
            var isOlder = Boolean(opts.beforeId);
            var changed = false;

            if (isOlder) {
                var existing = state.msgsByConv[convId] || [];
                var existIds = new Set(existing.map(function (m) { return m.id; }));
                var older = incoming.filter(function (m) { return !existIds.has(m.id); });
                if (older.length) {
                    state.msgsByConv[convId] = older.concat(existing);
                    changed = true;
                }
            } else {
                var cur = state.msgsByConv[convId] || [];
                var incoming_sorted = incoming.slice().sort(function (a, b) { return new Date(a.created_at || 0) - new Date(b.created_at || 0); });
                if (!cur.length || cur[cur.length - 1].id !== incoming_sorted[incoming_sorted.length - 1]?.id) {
                    state.msgsByConv[convId] = incoming_sorted;
                    changed = true;
                }
            }

            var final = state.msgsByConv[convId] || incoming;
            _setPaging(convId, final, limit, isOlder, incoming.length);

            var conv = state.conversations.find(function (c) { return c.id === convId; });
            if (conv && Number.isFinite(data.unread_count)) conv.unread_count = data.unread_count;

            if (changed || opts.forceRender) renderMsgList(Boolean(opts.scrollToBottom));
            if (changed) { renderConvList(); renderHeader(); }
            if (!opts.skipMarkRead && !isOlder) markRead(convId);
        } catch (e) { /* noop */ }
    }

    async function loadOlderMessages(convId) {
        var paging = _getPaging(convId);
        if (!paging.hasMore || paging.loading || !paging.oldestId) return;
        paging.loading = true;
        renderMsgList(false);
        await loadMessages(convId, { beforeId: paging.oldestId, limit: MESSAGE_PAGE_SIZE, forceRender: true, scrollToBottom: false, skipMarkRead: true });
        paging.loading = false;
        renderMsgList(false);
    }

    async function markRead(convId) {
        if (!convId) return;
        sendWs({ action: "mark_read" }, convId);
    }

    async function searchFriends() {
        var q = state.friendSearch.trim();
        if (!q) {
            state.friendCandidates = [];
            renderFriends();
            return;
        }
        var endpoint = urls.searchFriends + (q ? "?q=" + encodeURIComponent(q) : "");
        try {
            var res = await fetch(endpoint, { headers: { "X-Requested-With": "XMLHttpRequest" } });
            if (!res.ok) return;
            var data = await res.json();
            state.friendCandidates = Array.isArray(data.results) ? data.results : [];
            renderFriends();
        } catch (e) { /* noop */ }
    }

    async function startChatWithFriend(friendId, btn) {
        if (!friendId) return;
        if (btn) btn.disabled = true;
        try {
            var res = await fetch(buildUrl(urls.startFriendChatTpl, friendId), {
                method: "POST",
                headers: { "X-CSRFToken": getCookie("csrftoken"), "X-Requested-With": "XMLHttpRequest" }
            });
            var data = await res.json();
            if (!res.ok) { alert(data.error || "Không thể bắt đầu hội thoại."); return; }
            if (data.conversation) mergeConv(data.conversation);
            if (data.conversation && Array.isArray(data.messages)) {
                var sorted = data.messages.slice().sort(function (a, b) { return new Date(a.created_at || 0) - new Date(b.created_at || 0); });
                state.msgsByConv[data.conversation.id] = sorted;
                _setPaging(data.conversation.id, sorted, MESSAGE_PAGE_SIZE, false, sorted.length);
                setActiveConv(data.conversation.id, { messages: sorted });
            }
            var cand = state.friendCandidates.find(function (f) { return f.id === friendId; });
            if (cand && data.conversation) cand.conversation_id = data.conversation.id;
            renderFriends();
        } catch (e) { alert("Không thể bắt đầu hội thoại."); }
        finally { if (btn) btn.disabled = false; }
    }

    // ─── Active conversation ──────────────────────────────────────────────────
    function setActiveConv(convId, opts) {
        opts = opts || {};
        state.activeConvId = convId;
        state.stickToBottom = true;
        state.msgSearch = "";
        _getPaging(convId);
        renderConvList();
        renderHeader();

        if (Array.isArray(opts.messages)) {
            state.msgsByConv[convId] = opts.messages;
            _setPaging(convId, opts.messages, MESSAGE_PAGE_SIZE, false, opts.messages.length);
            renderMsgList(true);
        } else {
            renderMsgList(false);
            loadMessages(convId, { scrollToBottom: true, forceRender: true });
        }

        openSocket(convId);
        markRead(convId);
        if (elInput) { elInput.focus(); }
    }

    // ─── Send message ─────────────────────────────────────────────────────────
    async function sendMessage(e) {
        e.preventDefault();
        if (!state.activeConvId || state.sending) return;
        if (!isSocketOpen(state.ws) || state.wsConvId !== state.activeConvId) {
            openSocket(state.activeConvId);
            return;
        }

        var content = (elInput.value || "").trim();
        var files = Array.from(elFiles ? elFiles.files || [] : []);
        if (!content && !files.length) return;

        for (var i = 0; i < files.length; i++) {
            if (files[i].size >= MAX_ATTACHMENT_SIZE_BYTES) {
                alert("Mỗi file phải nhỏ hơn 20MB.");
                return;
            }
        }

        state.sending = true;
        if (elSendBtn) elSendBtn.disabled = true;

        try {
            var attachments = [];
            if (files.length) {
                try { attachments = await buildWsAttachments(files); }
                catch (err) { alert("Không thể đọc file đính kèm."); return; }
            }
            sendWs({ action: "send_message", content: content, attachments: attachments }, state.activeConvId);
            elInput.value = "";
            if (elFiles) elFiles.value = "";
            renderFilesPreview();
            state.stickToBottom = true;
            renderMsgList(true);
        } catch (err) {
            alert("Không thể gửi tin nhắn. Vui lòng thử lại.");
        } finally {
            state.sending = false;
            if (elSendBtn) elSendBtn.disabled = false;
            if (elInput) elInput.focus();
        }
    }

    // ─── Scroll management ────────────────────────────────────────────────────
    function updateStickToBottom() {
        if (!elMsgList) return;
        state.stickToBottom = (elMsgList.scrollHeight - elMsgList.scrollTop - elMsgList.clientHeight) < 80;
    }

    function maybeLoadOlder() {
        if (!elMsgList || !state.activeConvId) return;
        if ((state.msgSearch || "").trim()) return;
        var paging = _getPaging(state.activeConvId);
        if (!paging.hasMore || paging.loading) return;
        if (elMsgList.scrollHeight <= elMsgList.clientHeight) return;
        if (elMsgList.scrollTop <= SCROLL_LOAD_THRESHOLD) loadOlderMessages(state.activeConvId);
    }

    // ─── Event binding ────────────────────────────────────────────────────────
    function bindEvents() {
        if (elConvFilter) {
            elConvFilter.addEventListener("input", function (e) {
                state.convFilter = e.target.value || "";
                renderConvList();
            });
        }

        if (elFriendSearch) {
            var friendTimer = null;
            elFriendSearch.addEventListener("input", function (e) {
                state.friendSearch = e.target.value || "";
                clearTimeout(friendTimer);
                friendTimer = setTimeout(searchFriends, 300);
            });
        }

        if (elConvList) {
            elConvList.addEventListener("click", function (e) {
                var item = e.target.closest(".chat-conv-item");
                if (!item) return;
                var id = toInt(item.dataset.id, null);
                if (id) setActiveConv(id);
            });
        }

        if (elForm) elForm.addEventListener("submit", sendMessage);

        if (elInput) {
            elInput.addEventListener("keydown", function (e) {
                if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    elForm && elForm.dispatchEvent(new Event("submit", { cancelable: true }));
                }
            });
            elInput.addEventListener("input", function () {
                elInput.style.height = "auto";
                elInput.style.height = Math.min(elInput.scrollHeight, 120) + "px";
            });
        }

        if (elFiles) elFiles.addEventListener("change", renderFilesPreview);

        if (elMsgList) {
            elMsgList.addEventListener("scroll", function () {
                updateStickToBottom();
                maybeLoadOlder();
            });

            elMsgList.addEventListener("click", function (e) {
                var toggleBtn = e.target.closest(".chat-rxn-toggle");
                if (toggleBtn) {
                    var actions = toggleBtn.closest(".chat-rxn-actions");
                    var picker = actions && actions.querySelector(".chat-rxn-picker");
                    if (!picker) return;
                    document.querySelectorAll(".chat-rxn-picker.show").forEach(function (p) {
                        if (p !== picker) p.classList.remove("show");
                    });
                    picker.classList.toggle("show");
                    e.stopPropagation();
                    return;
                }

                var rxnOpt = e.target.closest(".chat-rxn-opt");
                if (rxnOpt) {
                    var actions2 = rxnOpt.closest(".chat-rxn-actions");
                    var msgId = actions2 ? toInt(actions2.dataset.msgId, null) : null;
                    var rxn = rxnOpt.dataset.rxn;
                    if (msgId && rxn) sendWs({ action: "toggle_reaction", message_id: msgId, reaction: rxn }, state.activeConvId);
                    document.querySelectorAll(".chat-rxn-picker.show").forEach(function (p) { p.classList.remove("show"); });
                    return;
                }
            });
        }

        function bindFriendResultsClick(target) {
            if (!target) return;
            target.addEventListener("click", function (e) {
                var btn = e.target.closest(".chat-start-btn");
                if (!btn) return;
                var friendId = toInt(btn.dataset.friendId, null);
                if (friendId) startChatWithFriend(friendId, btn);
            });
        }

        bindFriendResultsClick(elFriendResults);
        bindFriendResultsClick(elFriendResultsInline);

        document.addEventListener("click", function (e) {
            if (!e.target.closest(".chat-rxn-actions")) {
                document.querySelectorAll(".chat-rxn-picker.show").forEach(function (p) { p.classList.remove("show"); });
            }
        });

        window.addEventListener("beforeunload", closeSocket);
        window.addEventListener("resize", function () {
            var prev = friendResultsTarget;
            pickFriendResultsTarget();
            if (prev !== friendResultsTarget) renderFriends();
        });
    }

    // ─── Init ─────────────────────────────────────────────────────────────────
    function init() {
        requestNotificationPermission();
        pickFriendResultsTarget();
        renderConvList();
        renderFriends();
        renderFilesPreview();
        bindEvents();

        // Refresh friend list to keep results current.
        searchFriends();

        if (state.activeConvId) {
            var cached = state.msgsByConv[state.activeConvId];
            if (Array.isArray(cached) && cached.length) {
                setActiveConv(state.activeConvId, { messages: cached });
            } else {
                setActiveConv(state.activeConvId);
            }
            return;
        }

        if (state.conversations.length) {
            setActiveConv(state.conversations[0].id);
            return;
        }

        renderHeader();
        renderMsgList(false);
    }

    init();
})();