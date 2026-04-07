(function () {
  function getCookie(name) {
    const source = `; ${document.cookie}`;
    const parts = source.split(`; ${name}=`);
    if (parts.length === 2) {
      return parts.pop().split(";").shift();
    }
    return "";
  }

  function randomRequestId(prefix = "ui") {
    if (window.crypto && crypto.randomUUID) {
      return `${prefix}-${crypto.randomUUID()}`;
    }
    return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 10000)}`;
  }

  function setButtonLoading(button, loading, defaultText) {
    if (!button) {
      return;
    }

    if (loading) {
      button.dataset.defaultText = defaultText || button.textContent;
      button.textContent = "Processing...";
      button.disabled = true;
      return;
    }

    button.disabled = false;
    button.textContent = button.dataset.defaultText || defaultText || button.textContent;
  }

  function appendInlineAlert(container, message, level = "info") {
    if (!container) {
      return;
    }

    const className =
      level === "success"
        ? "alert-success"
        : level === "error"
          ? "alert-error"
          : level === "warning"
            ? "alert-warning"
            : "alert-info";

    const node = document.createElement("div");
    node.className = `alert ${className}`;
    node.textContent = message;
    container.prepend(node);

    window.setTimeout(() => {
      node.remove();
    }, 4000);
  }

  window.UIUtils = {
    getCookie,
    randomRequestId,
    setButtonLoading,
    appendInlineAlert,
  };
})();
