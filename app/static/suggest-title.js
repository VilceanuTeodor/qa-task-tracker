// "Suggest title" button on the task form.
// The browser only sends the description to OUR server (/tasks/suggest-title);
// the server calls Claude with the API key, which never reaches the browser.
(function () {
  const button = document.querySelector('[data-testid="suggest-title"]');
  if (!button) return;
  const title = document.querySelector('[data-testid="input-title"]');
  const description = document.querySelector('[data-testid="input-description"]');
  const status = document.querySelector('[data-testid="suggest-status"]');

  // Titles already suggested for the current description. They're sent along so each
  // press asks for a DIFFERENT title (the same request would otherwise get the same answer).
  let suggested = [];
  description.addEventListener("input", () => { suggested = []; });

  button.addEventListener("click", async () => {
    // Also avoid whatever is in the title box now (e.g. the existing title when editing a task).
    const previous = [...suggested];
    const current = title.value.trim();
    if (current && !previous.includes(current)) previous.push(current);

    button.disabled = true;
    status.textContent = "Thinking…";
    try {
      const res = await fetch("/tasks/suggest-title", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description: description.value, previous: previous.slice(-5) }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        title.value = data.title;
        suggested.push(data.title);
        status.textContent = "Suggested by AI. Check it and edit if needed, or click again for another one.";
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
