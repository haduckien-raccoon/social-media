(function () {
  const THROTTLE_MS = {
    heartbeat: 1500,
    typing: 900,
  };

  const MAX_LOG_LINES = 180;
  const MAX_FEED_ROOT_COMMENTS_PREVIEW = 5;

  const REACTION_META = {
    like: { icon: "fa-regular fa-thumbs-up", label: "Like" },
    love: { icon: "fa-solid fa-heart", label: "Love" },
    haha: { icon: "fa-regular fa-face-laugh", label: "Haha" },
    wow: { icon: "fa-regular fa-face-surprise", label: "Wow" },
    sad: { icon: "fa-regular fa-face-sad-tear", label: "Sad" },
    angry: { icon: "fa-regular fa-face-angry", label: "Angry" },
  };

  const state = {
    posts: [],
    commentsByPost: new Map(),
    activePostId: null,
    ws: null,
    wsConnected: false,
    wsManualClose: false,
    reconnectTimer: null,
    reconnectAttempt: 0,
    subscribedPostId: null,
    feedSubscribed: false,
    viewers: new Map(),
    typingUsers: new Set(),
    lastActionAt: {
      heartbeat: 0,
      typing: 0,
    },
    logLines: [],
    recentMutationEvents: new Map(),
    devDrawerOpen: false,
    openReplyForms: new Set(),
    openEditForms: new Set(),
    openReactionMenus: new Set(),
    expandedReplyThreads: new Set(),
  };

  const elements = {};
  const ui = window.UIUtils || {
    randomRequestId: (prefix) => `${prefix || "ui"}-${Date.now()}`,
    getCookie: () => "",
    setButtonLoading: (button, loading, text) => {
      if (!button) {
        return;
      }
      if (loading) {
        button.dataset.defaultText = text || button.textContent;
        button.textContent = "Processing...";
        button.disabled = true;
      } else {
        button.textContent = button.dataset.defaultText || text || button.textContent;
        button.disabled = false;
      }
    },
    appendInlineAlert: null,
  };

  function getCurrentUserId() {
    const raw = elements.root && elements.root.dataset.currentUserId;
    const parsed = Number(raw);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }

  function reactionValues() {
    const raw = (elements.root && elements.root.dataset.reactions) || "";
    return raw
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function getRequestId() {
    return ui.randomRequestId("demo");
  }

  function getCsrfToken() {
    return ui.getCookie("csrftoken");
  }

  function setLastRequestId(requestId) {
    if (elements.lastRequestId && requestId) {
      elements.lastRequestId.textContent = requestId;
    }
  }

  function showAlert(message, level = "info") {
    if (ui.appendInlineAlert && elements.alertStack) {
      ui.appendInlineAlert(elements.alertStack, message, level);
      return;
    }
    window.alert(message);
  }

  function setWsStatus(status, text) {
    if (!elements.wsStatusChip || !elements.wsStatusText) {
      return;
    }
    elements.wsStatusChip.classList.remove("connected", "disconnected", "reconnecting");
    elements.wsStatusChip.classList.add(status);
    elements.wsStatusText.textContent = text;
  }

  function formatTime(value) {
    if (!value) {
      return "-";
    }
    const timestamp = Date.parse(value);
    if (!Number.isFinite(timestamp)) {
      return String(value);
    }
    return new Date(timestamp).toLocaleString();
  }

  function formatBytes(bytes) {
    const size = Number(bytes || 0);
    if (!size) {
      return "0 B";
    }

    const units = ["B", "KB", "MB", "GB"];
    let current = size;
    let index = 0;

    while (current >= 1024 && index < units.length - 1) {
      current /= 1024;
      index += 1;
    }

    return `${current.toFixed(current >= 100 || index === 0 ? 0 : 1)} ${units[index]}`;
  }

  function escapeHtml(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function parseJsonSafely(text) {
    try {
      return text ? JSON.parse(text) : null;
    } catch (_err) {
      return null;
    }
  }

  function pushLog(kind, payload) {
    const entry = `[${new Date().toLocaleTimeString()}] ${kind} ${JSON.stringify(payload)}`;
    state.logLines.push(entry);

    if (state.logLines.length > MAX_LOG_LINES) {
      state.logLines.splice(0, state.logLines.length - MAX_LOG_LINES);
    }

    if (elements.eventLog) {
      elements.eventLog.textContent = state.logLines.join("\n");
      elements.eventLog.scrollTop = elements.eventLog.scrollHeight;
    }
  }

  function shouldHandleMutationEvent(payload) {
    const eventName = payload.event || "";
    if (!eventName.startsWith("comment.") && !eventName.startsWith("reaction.")) {
      return true;
    }

    const requestId = payload.request_id;
    const postId = Number(payload.post_id || 0);
    if (!requestId || !postId) {
      return true;
    }

    const now = Date.now();
    Array.from(state.recentMutationEvents.entries()).forEach(([key, ts]) => {
      if (now - ts > 2000) {
        state.recentMutationEvents.delete(key);
      }
    });

    const dedupeKey = `${requestId}:${postId}`;
    if (state.recentMutationEvents.has(dedupeKey)) {
      return false;
    }

    state.recentMutationEvents.set(dedupeKey, now);
    return true;
  }

  async function apiRequest(path, options = {}) {
    const requestId = getRequestId();
    setLastRequestId(requestId);

    const method = options.method || "GET";
    const headers = {
      Accept: "application/json",
      "X-Request-ID": requestId,
      ...(options.headers || {}),
    };

    const csrfToken = getCsrfToken();
    if (csrfToken && method !== "GET" && method !== "HEAD") {
      headers["X-CSRFToken"] = csrfToken;
    }

    let body;
    if (options.formData) {
      body = options.formData;
    } else if (options.body && method !== "GET" && method !== "HEAD") {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(options.body);
    }

    const response = await fetch(path, {
      method,
      headers,
      body,
      credentials: "include",
    });

    const text = await response.text();
    const data = parseJsonSafely(text);

    if (!response.ok) {
      const detail = (data && (data.detail || data.message || data.error)) || `HTTP ${response.status}`;
      const err = new Error(detail);
      err.status = response.status;
      err.payload = data;
      err.requestId = requestId;
      throw err;
    }

    pushLog("api.response", { path, method, status: response.status, request_id: requestId });
    return { data, requestId };
  }

  function commentListByPost(postId) {
    return state.commentsByPost.get(Number(postId)) || [];
  }

  function splitCommentTree(postId) {
    const comments = commentListByPost(postId);
    const roots = [];
    const repliesByParent = new Map();

    comments.forEach((comment) => {
      if (comment.parent) {
        if (!repliesByParent.has(comment.parent)) {
          repliesByParent.set(comment.parent, []);
        }
        repliesByParent.get(comment.parent).push(comment);
      } else {
        roots.push(comment);
      }
    });

    return { roots, repliesByParent };
  }

  function getPostById(postId) {
    return state.posts.find((item) => Number(item.id) === Number(postId)) || null;
  }

  function isOwnComment(comment) {
    const currentUserId = getCurrentUserId();
    return !!currentUserId && !!comment.author && Number(comment.author.id) === Number(currentUserId);
  }

  function resetPresenceForNextPost() {
    state.viewers.clear();
    state.typingUsers.clear();
    renderViewers();
  }

  function normalizeActivePost() {
    if (!state.posts.length) {
      state.activePostId = null;
      return;
    }

    if (!state.activePostId || !state.posts.some((post) => Number(post.id) === Number(state.activePostId))) {
      state.activePostId = Number(state.posts[0].id);
    }
  }

  function trimInlineStatesForComments() {
    const allCommentIds = new Set();
    Array.from(state.commentsByPost.values()).forEach((comments) => {
      comments.forEach((comment) => allCommentIds.add(Number(comment.id)));
    });

    [state.openReplyForms, state.openEditForms, state.openReactionMenus, state.expandedReplyThreads].forEach((bucket) => {
      Array.from(bucket).forEach((commentId) => {
        if (!allCommentIds.has(Number(commentId))) {
          bucket.delete(commentId);
        }
      });
    });
  }

  function pruneCommentCache() {
    const visiblePostIds = new Set(state.posts.map((post) => Number(post.id)));
    Array.from(state.commentsByPost.keys()).forEach((postId) => {
      if (!visiblePostIds.has(Number(postId))) {
        state.commentsByPost.delete(Number(postId));
      }
    });
  }

  function renderAttachmentPickerPreview() {
    if (!elements.postAttachments || !elements.attachmentPickerPreview) {
      return;
    }

    const files = Array.from(elements.postAttachments.files || []);
    if (!files.length) {
      elements.attachmentPickerPreview.textContent = "No file selected.";
      return;
    }

    elements.attachmentPickerPreview.innerHTML = files
      .map((file) => `<span class="attachment-chip">${escapeHtml(file.name)} (${formatBytes(file.size)})</span>`)
      .join("");
  }

  function renderPostAttachment(attachment) {
    const safeUrl = escapeHtml(attachment.url || "#");
    const safeName = escapeHtml(attachment.name || "file");
    const type = attachment.type || attachment.preview_kind;

    if (type === "image") {
      return `
        <a class="feed-attachment feed-attachment-image" href="${safeUrl}" target="_blank" rel="noreferrer">
          <img src="${safeUrl}" alt="${safeName}">
        </a>
      `;
    }

    if (type === "audio") {
      return `
        <div class="feed-attachment feed-attachment-audio">
          <audio controls preload="none" src="${safeUrl}"></audio>
          <p>${safeName}</p>
        </div>
      `;
    }

    return `
      <a class="feed-attachment feed-attachment-file" href="${safeUrl}" target="_blank" rel="noreferrer">
        <span><i class="fa-regular fa-file"></i> ${safeName}</span>
        <small>${formatBytes(attachment.size)}</small>
      </a>
    `;
  }

  function renderReactionPicker(commentId, postId) {
    const isOpen = state.openReactionMenus.has(Number(commentId));
    const hiddenClass = isOpen ? "" : "hidden";

    return `
      <div class="reaction-picker ${hiddenClass}" data-role="reaction-picker" data-comment-id="${commentId}">
        ${reactionValues()
          .map((reaction) => {
            const meta = REACTION_META[reaction] || { icon: "fa-regular fa-face-smile", label: reaction };
            return `
              <button
                class="btn btn-soft btn-sm reaction-btn"
                type="button"
                data-action="react-comment"
                data-comment-id="${commentId}"
                data-post-id="${postId}"
                data-reaction-type="${reaction}"
                title="React ${meta.label}"
              >
                <i class="${meta.icon}"></i>
                ${meta.label}
              </button>
            `;
          })
          .join("")}
      </div>
    `;
  }

  function renderInlineReplyForm(comment, postId) {
    const isOpen = state.openReplyForms.has(Number(comment.id));
    const hiddenClass = isOpen ? "" : "hidden";

    return `
      <form class="inline-editor ${hiddenClass}" data-action="create-reply-comment" data-post-id="${postId}" data-parent-id="${comment.id}">
        <textarea class="textarea-control" name="content" placeholder="Write your reply..." required></textarea>
        <div class="inline-actions mt-12">
          <button class="btn btn-primary btn-sm" type="submit">Send reply</button>
          <button class="btn btn-soft btn-sm" type="button" data-action="toggle-reply-form" data-comment-id="${comment.id}">Cancel</button>
        </div>
      </form>
    `;
  }

  function renderInlineEditForm(comment, postId) {
    const isOpen = state.openEditForms.has(Number(comment.id));
    const hiddenClass = isOpen ? "" : "hidden";

    return `
      <form class="inline-editor ${hiddenClass}" data-action="edit-comment-submit" data-post-id="${postId}" data-comment-id="${comment.id}">
        <textarea class="textarea-control" name="content" required>${escapeHtml(comment.content || "")}</textarea>
        <div class="inline-actions mt-12">
          <button class="btn btn-primary btn-sm" type="submit">Save edit</button>
          <button class="btn btn-soft btn-sm" type="button" data-action="toggle-edit-form" data-comment-id="${comment.id}">Cancel</button>
        </div>
      </form>
    `;
  }

  function renderCommentCard(comment, postId, options = {}) {
    const showReplyToggle = !!options.showReplyToggle;
    const repliesCount = Number(options.repliesCount || 0);
    const isReplyItem = !!options.isReplyItem;
    const canEdit = isOwnComment(comment) && !comment.is_deleted;
    const canReply = !comment.is_deleted && !isReplyItem;

    const deletedBadge = comment.is_deleted ? '<span class="badge badge-soft">deleted</span>' : "";
    const editedBadge = comment.edited_at ? '<span class="badge badge-soft">edited</span>' : "";

    const rootToggleButton =
      showReplyToggle && repliesCount > 0
        ? `
            <button
              class="icon-btn"
              type="button"
              data-action="toggle-detail-replies"
              data-comment-id="${comment.id}"
              title="Show/hide replies"
            >
              <i class="fa-solid fa-chevron-down"></i>
              <span>${repliesCount} replies</span>
            </button>
          `
        : "";

    return `
      <article class="comment-shell ${comment.is_deleted ? "is-deleted" : ""} ${isReplyItem ? "is-reply" : ""}">
        <header class="comment-head">
          <div>
            <strong>${escapeHtml(comment.author && comment.author.username ? comment.author.username : "Unknown")}</strong>
            <p class="comment-meta">#${comment.id} · ${formatTime(comment.created_at)}</p>
          </div>
          <div class="inline-actions">
            ${deletedBadge}
            ${editedBadge}
          </div>
        </header>

        <p class="comment-content">${escapeHtml(comment.content || "")}</p>

        <footer class="comment-actions-row">
          ${canReply
            ? `
              <button
                class="icon-btn"
                type="button"
                data-action="toggle-reply-form"
                data-comment-id="${comment.id}"
                title="Reply directly under this root comment"
              >
                <i class="fa-solid fa-reply"></i>
                <span>Reply</span>
              </button>
            `
            : ""}

          <button
            class="icon-btn"
            type="button"
            data-action="toggle-reaction-menu"
            data-comment-id="${comment.id}"
            title="Chọn reaction cho comment"
            ${comment.is_deleted ? "disabled" : ""}
          >
            <i class="fa-regular fa-face-smile"></i>
            <span>React (${Number(comment.reactions_count || 0)})</span>
          </button>

          ${canEdit
            ? `
              <button
                class="icon-btn"
                type="button"
                data-action="toggle-edit-form"
                data-comment-id="${comment.id}"
                title="Edit comment trong 15 phút"
              >
                <i class="fa-regular fa-pen-to-square"></i>
                <span>Edit</span>
              </button>
            `
            : ""}

          ${canEdit
            ? `
              <button
                class="icon-btn danger"
                type="button"
                data-action="delete-comment"
                data-post-id="${postId}"
                data-comment-id="${comment.id}"
                title="Soft delete comment"
              >
                <i class="fa-regular fa-trash-can"></i>
                <span>Delete</span>
              </button>
            `
            : ""}

          ${rootToggleButton}
        </footer>

        ${renderReactionPicker(comment.id, postId)}
        ${canReply ? renderInlineReplyForm(comment, postId) : ""}
        ${canEdit ? renderInlineEditForm(comment, postId) : ""}
      </article>
    `;
  }

  function renderFeedPost(post) {
    const postId = Number(post.id);
    const isActive = Number(state.activePostId) === postId;
    const { roots, repliesByParent } = splitCommentTree(postId);
    const rootsPreview = roots.slice(Math.max(0, roots.length - MAX_FEED_ROOT_COMMENTS_PREVIEW));
    const attachments = Array.isArray(post.attachments) ? post.attachments : [];

    return `
      <article class="feed-post ${isActive ? "is-active" : ""}" data-post-id="${postId}">
        <header class="feed-post-head">
          <div>
            <p class="feed-post-author">${escapeHtml(post.author && post.author.username ? post.author.username : "Unknown")}</p>
            <p class="feed-post-meta">Post #${postId} · ${formatTime(post.created_at)}</p>
          </div>
          <button class="btn ${isActive ? "btn-primary" : "btn-soft"} btn-sm" data-action="set-active-post" data-post-id="${postId}">
            ${isActive ? "Viewing" : "Open detail"}
          </button>
        </header>

        ${post.content ? `<p class="feed-post-content">${escapeHtml(post.content)}</p>` : ""}

        ${attachments.length ? `<div class="feed-attachments">${attachments.map(renderPostAttachment).join("")}</div>` : ""}

        <div class="feed-post-stats">
          <span><i class="fa-regular fa-comment"></i> ${Number(post.comments_count || 0)} comments</span>
          <span><i class="fa-regular fa-heart"></i> ${Number(post.reactions_count || 0)} reactions</span>
        </div>

        <div class="post-action-row mt-12">
          ${reactionValues()
            .map((reaction) => {
              const meta = REACTION_META[reaction] || { icon: "fa-regular fa-face-smile", label: reaction };
              return `
                <button
                  class="btn btn-soft btn-sm"
                  type="button"
                  data-action="react-post"
                  data-post-id="${postId}"
                  data-reaction-type="${reaction}"
                >
                  <i class="${meta.icon}"></i>
                  ${meta.label}
                </button>
              `;
            })
            .join("")}
        </div>

        <section class="comment-preview-wrap mt-16">
          <div class="mini-toolbar">
            <h3 class="feed-comments-title"><i class="fa-regular fa-comments"></i> Latest root comments (${Math.min(roots.length, MAX_FEED_ROOT_COMMENTS_PREVIEW)}/${roots.length})</h3>
            ${roots.length > MAX_FEED_ROOT_COMMENTS_PREVIEW
              ? `<button class="btn btn-soft btn-sm" type="button" data-action="set-active-post" data-post-id="${postId}">View all</button>`
              : ""}
          </div>

          <div class="comment-preview-list mt-12">
            ${rootsPreview.length
              ? rootsPreview
                  .map((rootComment) =>
                    renderCommentCard(rootComment, postId, {
                      repliesCount: (repliesByParent.get(rootComment.id) || []).length,
                    })
                  )
                  .join("")
              : '<p class="empty-inline">No comments yet.</p>'}
          </div>

          <form class="inline-editor mt-12" data-action="create-root-comment" data-post-id="${postId}">
            <textarea class="textarea-control" name="content" placeholder="Comment directly under this post..." required></textarea>
            <div class="inline-actions mt-12">
              <button class="btn btn-primary btn-sm" type="submit">
                <i class="fa-solid fa-comment-dots"></i>
                Add comment
              </button>
            </div>
          </form>
        </section>
      </article>
    `;
  }

  function renderFeed() {
    if (!elements.feedPostList) {
      return;
    }

    if (!state.posts.length) {
      elements.feedPostList.innerHTML = '<p class="empty-state">Feed is empty. Create a post to start.</p>';
      return;
    }

    elements.feedPostList.innerHTML = state.posts.map(renderFeedPost).join("");
  }

  function renderActivePostSelect() {
    if (!elements.activePostSelect) {
      return;
    }

    if (!state.posts.length) {
      elements.activePostSelect.innerHTML = '<option value="">No post available</option>';
      return;
    }

    elements.activePostSelect.innerHTML = state.posts
      .map((post) => {
        const postId = Number(post.id);
        const selected = postId === Number(state.activePostId) ? "selected" : "";
        const label = `#${post.id} · ${(post.author && post.author.username) || "Unknown"} · ${post.content || "Attachment post"}`;
        return `<option value="${postId}" ${selected}>${escapeHtml(label).slice(0, 96)}</option>`;
      })
      .join("");
  }

  function renderDetailSummary() {
    if (!elements.detailPostSummary) {
      return;
    }

    if (!state.activePostId) {
      elements.detailPostSummary.innerHTML = '<p class="muted">Select a post to view full thread.</p>';
      return;
    }

    const post = getPostById(state.activePostId);
    if (!post) {
      elements.detailPostSummary.innerHTML = '<p class="muted">Post not found in current feed.</p>';
      return;
    }

    elements.detailPostSummary.innerHTML = `
      <div class="detail-summary-card">
        <p><strong>${escapeHtml(post.author && post.author.username ? post.author.username : "Unknown")}</strong></p>
        <p class="muted">Post #${post.id} · ${formatTime(post.created_at)}</p>
        ${post.content ? `<p class="detail-summary-content">${escapeHtml(post.content)}</p>` : ""}
      </div>
    `;
  }

  function renderDetailThread() {
    if (!elements.detailThread) {
      return;
    }

    if (!state.activePostId) {
      elements.detailThread.innerHTML = '<p class="empty-state">Select post to open detail thread.</p>';
      return;
    }

    const postId = Number(state.activePostId);
    const { roots, repliesByParent } = splitCommentTree(postId);

    if (!roots.length) {
      elements.detailThread.innerHTML = '<p class="empty-state">No comments for this post yet.</p>';
      return;
    }

    elements.detailThread.innerHTML = roots
      .map((rootComment) => {
        const replies = repliesByParent.get(rootComment.id) || [];
        const isExpanded = state.expandedReplyThreads.has(Number(rootComment.id));

        return `
          <section class="detail-comment-block">
            ${renderCommentCard(rootComment, postId, {
              showReplyToggle: true,
              repliesCount: replies.length,
            })}

            ${replies.length
              ? `
                <div class="reply-list ${isExpanded ? "" : "hidden"}" data-parent-id="${rootComment.id}">
                  ${replies
                    .map((reply) =>
                      renderCommentCard(reply, postId, {
                        isReplyItem: true,
                      })
                    )
                    .join("")}
                </div>
              `
              : ""}
          </section>
        `;
      })
      .join("");
  }

  function renderViewers() {
    if (!elements.viewerList) {
      return;
    }

    if (!state.viewers.size) {
      elements.viewerList.innerHTML = '<li class="muted">No online viewers yet.</li>';
      return;
    }

    elements.viewerList.innerHTML = Array.from(state.viewers.values())
      .map((viewer) => {
        const typing = state.typingUsers.has(viewer.id)
          ? '<span class="badge badge-soft">typing...</span>'
          : '<span class="badge badge-soft">online</span>';

        return `
          <li>
            <span>${escapeHtml(viewer.username)} (#${viewer.id})</span>
            ${typing}
          </li>
        `;
      })
      .join("");
  }

  function renderAll() {
    trimInlineStatesForComments();
    renderFeed();
    renderActivePostSelect();
    renderDetailSummary();
    renderDetailThread();
    renderViewers();

    if (elements.detailRootCommentForm) {
      elements.detailRootCommentForm.dataset.postId = state.activePostId || "";
      const button = elements.detailRootCommentForm.querySelector("button[type='submit']");
      if (button) {
        button.disabled = !state.activePostId;
      }
    }
  }

  async function fetchFeed() {
    const { data } = await apiRequest(`${elements.root.dataset.apiBase}/feed`);
    state.posts = (data && data.results) || [];
    normalizeActivePost();
    pruneCommentCache();
  }

  async function ensureComments(postId, options = {}) {
    const normalizedPostId = Number(postId);
    if (!normalizedPostId) {
      return [];
    }

    if (!options.force && state.commentsByPost.has(normalizedPostId)) {
      return state.commentsByPost.get(normalizedPostId) || [];
    }

    const { data } = await apiRequest(`${elements.root.dataset.apiBase}/posts/${normalizedPostId}/comments`);
    const comments = (data && data.results) || [];
    state.commentsByPost.set(normalizedPostId, comments);
    return comments;
  }

  async function hydrateCommentsForVisiblePosts(options = {}) {
    const postIds = state.posts.map((post) => Number(post.id));
    await Promise.all(postIds.map((postId) => ensureComments(postId, options)));
  }

  async function replaceSinglePost(postId) {
    const normalizedPostId = Number(postId);
    if (!normalizedPostId) {
      return;
    }

    const { data } = await apiRequest(`${elements.root.dataset.apiBase}/posts/${normalizedPostId}`);
    const index = state.posts.findIndex((post) => Number(post.id) === normalizedPostId);
    if (index >= 0) {
      state.posts[index] = data;
    } else {
      state.posts.unshift(data);
    }
  }

  async function refreshFeedHydrated(options = {}) {
    await fetchFeed();
    await hydrateCommentsForVisiblePosts(options);
    renderAll();
    syncPostSubscription(state.activePostId, { force: true });
  }

  async function refreshPostData(postId) {
    const normalizedPostId = Number(postId);
    if (!normalizedPostId) {
      await refreshFeedHydrated({ force: true });
      return;
    }

    await Promise.all([
      replaceSinglePost(normalizedPostId).catch(async () => {
        await fetchFeed();
      }),
      ensureComments(normalizedPostId, { force: true }),
    ]);

    normalizeActivePost();
    renderAll();
  }

  function buildWsUrl() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}${elements.root.dataset.wsPath}`;
  }

  function reconnectDelayMs() {
    const base = 900;
    return Math.min(12000, base * 2 ** state.reconnectAttempt);
  }

  function scheduleReconnect() {
    if (state.wsManualClose) {
      return;
    }

    const delay = reconnectDelayMs();
    state.reconnectAttempt += 1;
    setWsStatus("reconnecting", `Reconnecting in ${Math.ceil(delay / 1000)}s`);

    state.reconnectTimer = window.setTimeout(() => {
      connectWebSocket();
    }, delay);
  }

  function sendWsAction(action, data = {}, options = {}) {
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
      if (!options.silent) {
        showAlert("WebSocket is not connected.", "warning");
      }
      return null;
    }

    const requestId = getRequestId();
    setLastRequestId(requestId);

    const payload = {
      action,
      request_id: requestId,
      ...data,
    };

    state.ws.send(JSON.stringify(payload));
    pushLog("ws.client", payload);
    return requestId;
  }

  function syncPostSubscription(nextPostId, options = {}) {
    const postId = nextPostId ? Number(nextPostId) : null;
    const previousPostId = state.subscribedPostId;

    if (!state.wsConnected) {
      state.subscribedPostId = postId;
      return;
    }

    if (previousPostId && previousPostId !== postId) {
      sendWsAction("unsubscribe_post", { post_id: previousPostId }, { silent: true });
    }

    if (postId && (postId !== previousPostId || options.force)) {
      sendWsAction("subscribe_post", { post_id: postId }, { silent: true });
    }

    state.subscribedPostId = postId;
  }

  function syncFeedSubscription() {
    if (!state.wsConnected) {
      return;
    }
    sendWsAction("subscribe_feed", {}, { silent: true });
  }

  function connectWebSocket() {
    if (state.reconnectTimer) {
      window.clearTimeout(state.reconnectTimer);
      state.reconnectTimer = null;
    }

    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      return;
    }

    try {
      state.ws = new WebSocket(buildWsUrl());
      setWsStatus("reconnecting", "Connecting...");
    } catch (err) {
      pushLog("ws.error", { message: err.message });
      scheduleReconnect();
      return;
    }

    state.ws.onopen = () => {
      state.wsConnected = true;
      state.reconnectAttempt = 0;
      setWsStatus("connected", "Connected");
      pushLog("ws.open", { at: new Date().toISOString() });

      syncFeedSubscription();
      syncPostSubscription(state.activePostId, { force: true });
    };

    state.ws.onclose = (event) => {
      state.wsConnected = false;
      setWsStatus("disconnected", `Disconnected (${event.code})`);
      pushLog("ws.close", { code: event.code, reason: event.reason || "" });
      scheduleReconnect();
    };

    state.ws.onerror = () => {
      pushLog("ws.error", { message: "WebSocket error" });
    };

    state.ws.onmessage = (event) => {
      const payload = parseJsonSafely(event.data);
      if (!payload) {
        return;
      }
      handleServerEvent(payload);
    };
  }

  function handlePresenceEvent(eventName, data, postId) {
    if (Number(postId) !== Number(state.activePostId)) {
      return;
    }

    if (eventName === "presence.snapshot") {
      state.viewers.clear();
      (data.viewers || []).forEach((viewer) => {
        state.viewers.set(viewer.id, viewer);
      });
      renderViewers();
      return;
    }

    if (!data.user) {
      return;
    }

    if (eventName === "presence.joined") {
      state.viewers.set(data.user.id, data.user);
      renderViewers();
      return;
    }

    if (eventName === "presence.left") {
      state.viewers.delete(data.user.id);
      state.typingUsers.delete(data.user.id);
      renderViewers();
    }
  }

  function handleTypingEvent(eventName, data, postId) {
    if (Number(postId) !== Number(state.activePostId) || !data.user) {
      return;
    }

    if (eventName === "typing.started") {
      state.typingUsers.add(data.user.id);
      renderViewers();
      return;
    }

    if (eventName === "typing.stopped") {
      state.typingUsers.delete(data.user.id);
      renderViewers();
    }
  }

  async function handleDataRefreshTrigger(eventName, payload) {
    const data = payload.data || {};
    const payloadPostId = Number(payload.post_id || data.post_id || 0);

    if (eventName === "feed.snapshot") {
      state.feedSubscribed = !!data.subscribed;
      return;
    }

    if (eventName === "post.created" || eventName === "post.created.following") {
      await refreshFeedHydrated({ force: true });
      return;
    }

    if (eventName.startsWith("comment.") || eventName.startsWith("reaction.")) {
      if (!shouldHandleMutationEvent(payload)) {
        return;
      }
      await refreshPostData(payloadPostId || state.activePostId);
      return;
    }
  }

  function handleServerEvent(payload) {
    pushLog("ws.server", payload);

    if (payload.request_id) {
      setLastRequestId(payload.request_id);
    }

    const eventName = payload.event || "unknown";
    const data = payload.data || {};

    if (eventName.startsWith("presence.")) {
      handlePresenceEvent(eventName, data, payload.post_id);
    }

    if (eventName.startsWith("typing.")) {
      handleTypingEvent(eventName, data, payload.post_id);
    }

    if (eventName === "error") {
      showAlert(data.message || "WS error", "warning");
    }

    handleDataRefreshTrigger(eventName, payload).catch((err) => {
      pushLog("ui.error", { stage: "event_refresh", message: err.message });
    });
  }

  function canRunAction(actionKey) {
    const now = Date.now();
    const lastAt = state.lastActionAt[actionKey] || 0;
    if (now - lastAt < THROTTLE_MS[actionKey]) {
      return false;
    }

    state.lastActionAt[actionKey] = now;
    return true;
  }

  async function setActivePost(postId, options = {}) {
    state.activePostId = postId ? Number(postId) : null;
    resetPresenceForNextPost();

    if (state.activePostId) {
      await ensureComments(state.activePostId);
    }

    renderAll();
    syncPostSubscription(state.activePostId, { force: !!options.force });
  }

  function toggleSetMember(setRef, value) {
    const normalized = Number(value);
    if (setRef.has(normalized)) {
      setRef.delete(normalized);
      return false;
    }

    setRef.add(normalized);
    return true;
  }

  async function submitCreateComment(postId, content, parentId) {
    const payload = { content: String(content || "").trim() };
    if (!payload.content) {
      throw new Error("Comment content cannot be empty");
    }
    if (parentId) {
      payload.parent_id = Number(parentId);
    }

    await apiRequest(`${elements.root.dataset.apiBase}/posts/${postId}/comments`, {
      method: "POST",
      body: payload,
    });

    await refreshPostData(postId);
  }

  async function submitEditComment(postId, commentId, content) {
    const normalizedContent = String(content || "").trim();
    if (!normalizedContent) {
      throw new Error("Comment content cannot be empty");
    }

    await apiRequest(`${elements.root.dataset.apiBase}/comments/${commentId}`, {
      method: "PATCH",
      body: { content: normalizedContent },
    });

    await refreshPostData(postId);
  }

  async function submitDeleteComment(postId, commentId) {
    await apiRequest(`${elements.root.dataset.apiBase}/comments/${commentId}`, {
      method: "DELETE",
    });

    state.openReplyForms.delete(Number(commentId));
    state.openEditForms.delete(Number(commentId));
    state.openReactionMenus.delete(Number(commentId));
    await refreshPostData(postId);
  }

  async function submitCommentReaction(postId, commentId, reactionType) {
    await apiRequest(`${elements.root.dataset.apiBase}/comments/${commentId}/reaction`, {
      method: "PUT",
      body: { reaction_type: reactionType },
    });

    await refreshPostData(postId);
  }

  async function submitPostReaction(postId, reactionType) {
    await apiRequest(`${elements.root.dataset.apiBase}/posts/${postId}/reaction`, {
      method: "PUT",
      body: { reaction_type: reactionType },
    });

    await refreshPostData(postId);
  }

  function toggleDevDrawer(open) {
    state.devDrawerOpen = !!open;
    if (!elements.devStreamDrawer || !elements.devStreamBackdrop) {
      return;
    }

    elements.devStreamDrawer.classList.toggle("is-open", state.devDrawerOpen);
    elements.devStreamBackdrop.classList.toggle("hidden", !state.devDrawerOpen);
    elements.devStreamDrawer.setAttribute("aria-hidden", state.devDrawerOpen ? "false" : "true");
  }

  async function handleActionButton(actionButton) {
    const action = actionButton.dataset.action;
    if (!action) {
      return;
    }

    const postId = Number(actionButton.dataset.postId || state.activePostId || 0);
    const commentId = Number(actionButton.dataset.commentId || 0);
    const reactionType = actionButton.dataset.reactionType;

    if (action === "set-active-post") {
      if (!postId) {
        return;
      }
      await setActivePost(postId, { force: true });
      return;
    }

    if (action === "react-post") {
      if (!postId) {
        showAlert("Missing post id.", "warning");
        return;
      }
      await submitPostReaction(postId, reactionType);
      showAlert("Post reaction synced.", "success");
      return;
    }

    if (action === "toggle-reply-form") {
      if (!commentId) {
        return;
      }
      toggleSetMember(state.openReplyForms, commentId);
      state.openEditForms.delete(commentId);
      renderAll();
      return;
    }

    if (action === "toggle-edit-form") {
      if (!commentId) {
        return;
      }
      toggleSetMember(state.openEditForms, commentId);
      state.openReplyForms.delete(commentId);
      renderAll();
      return;
    }

    if (action === "toggle-reaction-menu") {
      if (!commentId) {
        return;
      }
      toggleSetMember(state.openReactionMenus, commentId);
      renderAll();
      return;
    }

    if (action === "react-comment") {
      if (!postId || !commentId || !reactionType) {
        showAlert("Missing comment reaction data.", "warning");
        return;
      }
      await submitCommentReaction(postId, commentId, reactionType);
      showAlert("Comment reaction synced.", "success");
      return;
    }

    if (action === "delete-comment") {
      if (!postId || !commentId) {
        return;
      }

      const ok = window.confirm("Delete this comment? This performs soft delete and keeps history.");
      if (!ok) {
        return;
      }

      await submitDeleteComment(postId, commentId);
      showAlert("Comment soft-deleted.", "success");
      return;
    }

    if (action === "toggle-detail-replies") {
      if (!commentId) {
        return;
      }
      toggleSetMember(state.expandedReplyThreads, commentId);
      renderAll();
    }
  }

  async function handleFormSubmit(form) {
    const action = form.dataset.action;
    const postId = Number(form.dataset.postId || state.activePostId || 0);
    const parentId = Number(form.dataset.parentId || 0);
    const commentId = Number(form.dataset.commentId || 0);

    if (action === "create-root-comment") {
      const content = form.elements.content && form.elements.content.value;
      await submitCreateComment(postId, content, null);
      form.reset();
      showAlert("Comment created.", "success");
      return;
    }

    if (action === "create-reply-comment") {
      const content = form.elements.content && form.elements.content.value;
      await submitCreateComment(postId, content, parentId || null);
      state.openReplyForms.delete(parentId);
      form.reset();
      renderAll();
      showAlert("Reply created.", "success");
      return;
    }

    if (action === "edit-comment-submit") {
      const content = form.elements.content && form.elements.content.value;
      await submitEditComment(postId, commentId, content);
      state.openEditForms.delete(commentId);
      form.reset();
      renderAll();
      showAlert("Comment updated.", "success");
      return;
    }
  }

  function bindEvents() {
    elements.postAttachments.addEventListener("change", renderAttachmentPickerPreview);

    elements.refreshFeedBtn.addEventListener("click", async () => {
      try {
        await refreshFeedHydrated({ force: true });
        showAlert("Feed refreshed.", "success");
      } catch (err) {
        showAlert(`Refresh failed: ${err.message}`, "error");
      }
    });

    elements.activePostSelect.addEventListener("change", async () => {
      try {
        await setActivePost(Number(elements.activePostSelect.value || 0), { force: true });
      } catch (err) {
        showAlert(`Change active post failed: ${err.message}`, "error");
      }
    });

    elements.createPostForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const content = String(form.content.value || "").trim();
      const files = Array.from(elements.postAttachments.files || []);

      if (!content && !files.length) {
        showAlert("Post must have content or attachment.", "warning");
        return;
      }

      const formData = new FormData();
      formData.append("content", content);
      files.forEach((file) => formData.append("attachments", file));

      ui.setButtonLoading(elements.createPostBtn, true, "Publish to Feed");
      try {
        const { data } = await apiRequest(`${elements.root.dataset.apiBase}/posts`, {
          method: "POST",
          formData,
        });

        form.reset();
        renderAttachmentPickerPreview();
        await refreshFeedHydrated({ force: true });
        if (data && data.id) {
          await setActivePost(Number(data.id), { force: true });
        }
        showAlert("Post published.", "success");
      } catch (err) {
        showAlert(`Create post failed: ${err.message}`, "error");
      } finally {
        ui.setButtonLoading(elements.createPostBtn, false, "Publish to Feed");
      }
    });

    const interactionRoots = [elements.feedPostList, elements.detailThread];

    interactionRoots.forEach((rootEl) => {
      rootEl.addEventListener("click", async (event) => {
        const actionButton = event.target.closest("[data-action]");
        if (!actionButton) {
          return;
        }

        const action = actionButton.dataset.action;
        if (action === "react-comment" || action === "react-post" || action === "delete-comment" || action.startsWith("toggle") || action === "set-active-post") {
          event.preventDefault();
          try {
            await handleActionButton(actionButton);
          } catch (err) {
            showAlert(`${action.replaceAll("-", " ")} failed: ${err.message}`, "error");
          }
        }
      });

      rootEl.addEventListener("submit", async (event) => {
        const form = event.target.closest("form[data-action]");
        if (!form) {
          return;
        }
        event.preventDefault();

        const submitButton = form.querySelector("button[type='submit']");
        ui.setButtonLoading(submitButton, true, submitButton && submitButton.textContent ? submitButton.textContent.trim() : "Submit");

        try {
          await handleFormSubmit(form);
        } catch (err) {
          const action = form.dataset.action || "form";
          showAlert(`${action.replaceAll("-", " ")} failed: ${err.message}`, "error");
        } finally {
          ui.setButtonLoading(submitButton, false, submitButton && submitButton.textContent ? submitButton.textContent.trim() : "Submit");
        }
      });
    });

    elements.detailRootCommentForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const postId = Number(state.activePostId || form.dataset.postId || 0);
      const content = form.elements.content && form.elements.content.value;
      const submitButton = form.querySelector("button[type='submit']");

      if (!postId) {
        showAlert("Choose active post first.", "warning");
        return;
      }

      ui.setButtonLoading(submitButton, true, "Add Comment");
      try {
        await submitCreateComment(postId, content, null);
        form.reset();
        showAlert("Comment created.", "success");
      } catch (err) {
        showAlert(`Create comment failed: ${err.message}`, "error");
      } finally {
        ui.setButtonLoading(submitButton, false, "Add Comment");
      }
    });

    elements.heartbeatBtn.addEventListener("click", () => {
      if (!state.activePostId) {
        showAlert("Choose active post before heartbeat.", "warning");
        return;
      }
      if (!canRunAction("heartbeat")) {
        showAlert("Heartbeat is throttled on client.", "warning");
        return;
      }
      sendWsAction("heartbeat", { post_id: state.activePostId });
    });

    elements.typingStartBtn.addEventListener("click", () => {
      if (!state.activePostId) {
        showAlert("Choose active post before typing.", "warning");
        return;
      }
      if (!canRunAction("typing")) {
        showAlert("Typing action is throttled.", "warning");
        return;
      }
      sendWsAction("typing_start", { post_id: state.activePostId });
    });

    elements.typingStopBtn.addEventListener("click", () => {
      if (!state.activePostId) {
        showAlert("Choose active post before typing.", "warning");
        return;
      }
      if (!canRunAction("typing")) {
        showAlert("Typing action is throttled.", "warning");
        return;
      }
      sendWsAction("typing_stop", { post_id: state.activePostId });
    });

    elements.wsReconnectBtn.addEventListener("click", () => {
      if (state.ws) {
        state.wsManualClose = false;
        state.ws.close(4000, "manual_reconnect");
      }
      connectWebSocket();
    });

    elements.feedSubscribeBtn.addEventListener("click", () => {
      sendWsAction("subscribe_feed");
    });

    elements.feedUnsubscribeBtn.addEventListener("click", () => {
      sendWsAction("unsubscribe_feed");
    });

    elements.subscribeBtn.addEventListener("click", () => {
      if (!state.activePostId) {
        showAlert("Choose active post before subscribe.", "warning");
        return;
      }
      sendWsAction("subscribe_post", { post_id: state.activePostId });
      state.subscribedPostId = state.activePostId;
    });

    elements.unsubscribeBtn.addEventListener("click", () => {
      if (!state.activePostId) {
        showAlert("Choose active post before unsubscribe.", "warning");
        return;
      }
      sendWsAction("unsubscribe_post", { post_id: state.activePostId });
      if (Number(state.subscribedPostId) === Number(state.activePostId)) {
        state.subscribedPostId = null;
      }
    });

    elements.clearLogBtn.addEventListener("click", () => {
      state.logLines = [];
      if (elements.eventLog) {
        elements.eventLog.textContent = "";
      }
    });

    elements.devStreamToggleBtn.addEventListener("click", () => toggleDevDrawer(true));
    elements.devStreamCloseBtn.addEventListener("click", () => toggleDevDrawer(false));
    elements.devStreamBackdrop.addEventListener("click", () => toggleDevDrawer(false));

    window.addEventListener("beforeunload", () => {
      state.wsManualClose = true;
      if (state.ws) {
        state.ws.close(1000, "page_unload");
      }
    });
  }

  function cacheElements() {
    elements.root = document.getElementById("realtime-demo-root");
    elements.alertStack = document.getElementById("demo-alert-stack");

    elements.wsStatusChip = document.getElementById("ws-status-chip");
    elements.wsStatusText = document.getElementById("ws-status-text");
    elements.lastRequestId = document.getElementById("last-request-id");
    elements.wsReconnectBtn = document.getElementById("ws-reconnect-btn");

    elements.createPostForm = document.getElementById("create-post-form");
    elements.createPostBtn = document.getElementById("create-post-btn");
    elements.postAttachments = document.getElementById("post-attachments");
    elements.attachmentPickerPreview = document.getElementById("attachment-picker-preview");

    elements.refreshFeedBtn = document.getElementById("refresh-feed-btn");
    elements.feedPostList = document.getElementById("feed-post-list");

    elements.activePostSelect = document.getElementById("active-post-select");
    elements.detailPostSummary = document.getElementById("detail-post-summary");
    elements.detailRootCommentForm = document.getElementById("detail-root-comment-form");
    elements.detailThread = document.getElementById("detail-thread");

    elements.heartbeatBtn = document.getElementById("heartbeat-btn");
    elements.typingStartBtn = document.getElementById("typing-start-btn");
    elements.typingStopBtn = document.getElementById("typing-stop-btn");
    elements.viewerList = document.getElementById("viewer-list");

    elements.devStreamToggleBtn = document.getElementById("dev-stream-toggle-btn");
    elements.devStreamDrawer = document.getElementById("dev-stream-drawer");
    elements.devStreamBackdrop = document.getElementById("dev-stream-backdrop");
    elements.devStreamCloseBtn = document.getElementById("dev-stream-close-btn");

    elements.feedSubscribeBtn = document.getElementById("feed-subscribe-btn");
    elements.feedUnsubscribeBtn = document.getElementById("feed-unsubscribe-btn");
    elements.subscribeBtn = document.getElementById("subscribe-btn");
    elements.unsubscribeBtn = document.getElementById("unsubscribe-btn");
    elements.clearLogBtn = document.getElementById("clear-log-btn");
    elements.eventLog = document.getElementById("event-log");
  }

  function validateElements() {
    const required = [
      "root",
      "createPostForm",
      "postAttachments",
      "refreshFeedBtn",
      "feedPostList",
      "activePostSelect",
      "detailRootCommentForm",
      "detailThread",
      "heartbeatBtn",
      "typingStartBtn",
      "typingStopBtn",
      "viewerList",
      "wsReconnectBtn",
      "devStreamToggleBtn",
      "devStreamDrawer",
      "devStreamBackdrop",
      "devStreamCloseBtn",
      "feedSubscribeBtn",
      "feedUnsubscribeBtn",
      "subscribeBtn",
      "unsubscribeBtn",
      "clearLogBtn",
      "eventLog",
    ];

    return required.every((key) => !!elements[key]);
  }

  async function init() {
    cacheElements();
    if (!elements.root) {
      return;
    }

    if (!validateElements()) {
      showAlert("Realtime demo UI is missing required elements.", "error");
      return;
    }

    bindEvents();
    renderAttachmentPickerPreview();
    connectWebSocket();

    try {
      await refreshFeedHydrated({ force: true });
      if (state.activePostId) {
        await setActivePost(state.activePostId, { force: true });
      }
    } catch (err) {
      showAlert(`Initial load failed: ${err.message}`, "error");
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
