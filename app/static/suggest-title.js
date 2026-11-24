// "Suggest title" button on the task form.
// The browser only sends the description to OUR server (/tasks/suggest-title);
// the server calls Claude with the API key, which never reaches the browser.
(function () {
  const button = document.querySelector('[data-testid="suggest-title"]');
  if (!button) return;
  const title = document.querySelector('[data-testid="input-title"]');
  const description = document.querySelector('[data-testid="input-description"]');
  const status = document.querySelector('[data-testid="suggest-status"]');

  button.addEventListener("click", async () => {
    button.disabled = true;
    status.textContent = "Thinking…";
    try {
      const res = await fetch("/tasks/suggest-title", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description: description.value }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        title.value = data.title;
        status.textContent = "Suggested by AI. Check it and edit if needed.";
      } else {
        status.textContent = (typeof data.detail === "string" && data.detail) || "Couldn't suggest a title.";
      }
    } catch (err) {
      status.textContent = "Network error, try again.";
    } finally {
      button.disabled = false;
    }
  });
})();
