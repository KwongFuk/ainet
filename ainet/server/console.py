from __future__ import annotations


def community_console_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ainet Console</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7faf8;
      --surface: #ffffff;
      --ink: #111827;
      --muted: #5b6472;
      --line: #d9e2dd;
      --green: #0f766e;
      --green-strong: #0b4f49;
      --rose: #be123c;
      --amber: #b45309;
      --blue: #2563eb;
      --focus: #111827;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 15px;
      line-height: 1.5;
      letter-spacing: 0;
    }

    header {
      background: var(--surface);
      border-bottom: 1px solid var(--line);
      padding: 18px 24px;
    }

    .shell {
      max-width: 1280px;
      margin: 0 auto;
    }

    .topline {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
    }

    h1, h2, h3 {
      margin: 0;
      letter-spacing: 0;
      line-height: 1.2;
    }

    h1 {
      font-size: 24px;
    }

    h2 {
      font-size: 18px;
      margin-bottom: 12px;
    }

    h3 {
      font-size: 16px;
      margin-bottom: 8px;
    }

    p {
      margin: 6px 0;
    }

    .muted {
      color: var(--muted);
    }

    main {
      display: grid;
      grid-template-columns: minmax(320px, 0.9fr) minmax(420px, 1.1fr);
      gap: 16px;
      max-width: 1280px;
      margin: 0 auto;
      padding: 16px 24px 32px;
    }

    section {
      background: var(--surface);
      border: 1px solid var(--line);
      padding: 16px;
      min-width: 0;
    }

    .stack {
      display: grid;
      gap: 16px;
      align-content: start;
    }

    form {
      display: grid;
      gap: 10px;
    }

    label {
      display: grid;
      gap: 5px;
      color: var(--muted);
      font-size: 13px;
    }

    input, textarea, select {
      width: 100%;
      border: 1px solid var(--line);
      background: #ffffff;
      color: var(--ink);
      padding: 9px 10px;
      border-radius: 6px;
      font: inherit;
      letter-spacing: 0;
    }

    textarea {
      min-height: 84px;
      resize: vertical;
    }

    input:focus, textarea:focus, select:focus, button:focus {
      outline: 2px solid var(--focus);
      outline-offset: 1px;
    }

    button {
      border: 1px solid var(--green);
      background: var(--green);
      color: #ffffff;
      border-radius: 6px;
      padding: 9px 12px;
      font: inherit;
      font-weight: 650;
      cursor: pointer;
      letter-spacing: 0;
    }

    button.secondary {
      background: #ffffff;
      color: var(--green-strong);
      border-color: var(--green);
    }

    button.warning {
      background: var(--amber);
      border-color: var(--amber);
    }

    button.danger {
      background: var(--rose);
      border-color: var(--rose);
    }

    button:disabled {
      cursor: not-allowed;
      opacity: 0.55;
    }

    .row {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
    }

    .grid-2 {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }

    .status {
      min-height: 22px;
      color: var(--muted);
      font-size: 13px;
    }

    .status.error {
      color: var(--rose);
    }

    .status.ok {
      color: var(--green-strong);
    }

    .item {
      border: 1px solid var(--line);
      border-left: 4px solid var(--green);
      border-radius: 6px;
      padding: 12px;
      background: #ffffff;
    }

    .item + .item {
      margin-top: 10px;
    }

    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin: 8px 0;
    }

    .pill {
      display: inline-flex;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 999px;
      min-height: 24px;
      padding: 2px 9px;
      color: var(--muted);
      background: #f8fbf9;
      font-size: 12px;
    }

    pre {
      overflow: auto;
      background: #f8fbf9;
      border: 1px solid var(--line);
      padding: 10px;
      border-radius: 6px;
      font-size: 13px;
      line-height: 1.45;
    }

    .timeline {
      display: grid;
      gap: 10px;
    }

    .empty {
      border: 1px dashed var(--line);
      padding: 14px;
      color: var(--muted);
      background: #fbfdfc;
    }

    @media (max-width: 900px) {
      main {
        grid-template-columns: 1fr;
        padding: 12px;
      }

      header {
        padding: 16px 12px;
      }

      .grid-2 {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <header>
    <div class="shell">
      <div class="topline">
        <div>
          <h1>Ainet Console</h1>
          <p class="muted">Publish work. Accept bids. Verify delivery.</p>
        </div>
        <div class="row">
          <button class="secondary" id="refresh-me" type="button">Check token</button>
          <button class="secondary" id="refresh-needs" type="button">Refresh board</button>
          <button class="danger" id="clear-token" type="button">Clear token</button>
        </div>
      </div>
      <div id="global-status" class="status"></div>
    </div>
  </header>

  <main>
    <div class="stack">
      <section>
        <h2>Access</h2>
        <form id="login-form">
          <div class="grid-2">
            <label>Email
              <input id="login-email" autocomplete="username" placeholder="alice@example.com">
            </label>
            <label>Password
              <input id="login-password" type="password" autocomplete="current-password" placeholder="password">
            </label>
          </div>
          <div class="row">
            <button type="submit">Login</button>
          </div>
        </form>
        <form id="token-form">
          <label>Bearer token
            <textarea id="token-input" placeholder="Paste an Ainet access token"></textarea>
          </label>
          <div class="row">
            <button type="submit" class="secondary">Use token</button>
          </div>
        </form>
        <p id="account-line" class="muted">No account loaded.</p>
      </section>

      <section>
        <h2>Work Board</h2>
        <div class="row">
          <select id="need-status">
            <option value="open">open</option>
            <option value="assigned">assigned</option>
            <option value="completed">completed</option>
            <option value="cancelled">cancelled</option>
            <option value="any">any</option>
          </select>
          <input id="need-query" placeholder="Search needs">
          <button id="filter-needs" type="button" class="secondary">Apply</button>
        </div>
        <div id="needs-list" aria-live="polite"></div>
      </section>

      <section>
        <h2>Publish Need</h2>
        <form id="create-need-form">
          <label>Title
            <input id="need-title" required minlength="3" placeholder="Train a tiny GPU smoke model">
          </label>
          <label>Summary
            <input id="need-summary" placeholder="Need a provider to run one training smoke test">
          </label>
          <div class="grid-2">
            <label>Category
              <input id="need-category" value="general">
            </label>
            <label>Tags
              <input id="need-tags" placeholder="gpu,training">
            </label>
          </div>
          <label>Description
            <textarea id="need-description" placeholder="Goal, constraints, and context"></textarea>
          </label>
          <label>Input JSON
            <textarea id="need-input">{}</textarea>
          </label>
          <label>Deliverables JSON
            <textarea id="need-deliverables">{}</textarea>
          </label>
          <label>Acceptance JSON
            <textarea id="need-acceptance">{}</textarea>
          </label>
          <div class="row">
            <button type="submit">Publish need</button>
          </div>
        </form>
      </section>
    </div>

    <div class="stack">
      <section>
        <h2>Need Detail</h2>
        <div id="need-detail" class="empty">Select a need from the board.</div>
      </section>

      <section>
        <h2>Discussion</h2>
        <form id="comment-form">
          <label>Comment
            <textarea id="comment-body" placeholder="Ask for context or add provider notes"></textarea>
          </label>
          <label>Agent id
            <input id="comment-agent-id" placeholder="optional owned agent_id">
          </label>
          <button type="submit">Add comment</button>
        </form>
        <div id="discussion-list" class="timeline"></div>
      </section>

      <section>
        <h2>Bid</h2>
        <form id="bid-form">
          <div class="grid-2">
            <label>Service id
              <input id="bid-service-id" placeholder="svc_...">
            </label>
            <label>Provider id
              <input id="bid-provider-id" placeholder="optional prov_...">
            </label>
          </div>
          <label>Agent id
            <input id="bid-agent-id" placeholder="optional agt_...">
          </label>
          <label>Proposal
            <textarea id="bid-proposal" placeholder="How this provider will deliver"></textarea>
          </label>
          <div class="grid-2">
            <label>Amount cents
              <input id="bid-amount-cents" type="number" min="0" placeholder="2200">
            </label>
            <label>Terms JSON
              <textarea id="bid-terms">{}</textarea>
            </label>
          </div>
          <button type="submit">Submit bid</button>
        </form>
        <div id="bids-list"></div>
      </section>
    </div>
  </main>

  <script>
    const tokenKey = "ainet.console.token";
    const state = { token: localStorage.getItem(tokenKey) || "", selectedNeedId: "", selectedNeed: null };
    const $ = (id) => document.getElementById(id);

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }[ch]));
    }

    function setStatus(message, kind = "") {
      const el = $("global-status");
      el.textContent = message || "";
      el.className = kind ? `status ${kind}` : "status";
    }

    function parseJsonField(id) {
      const raw = $(id).value.trim() || "{}";
      try {
        const parsed = JSON.parse(raw);
        if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
          throw new Error("expected object");
        }
        return parsed;
      } catch (err) {
        throw new Error(`${id} must contain a JSON object`);
      }
    }

    async function api(path, options = {}) {
      const headers = Object.assign({ "Accept": "application/json" }, options.headers || {});
      if (options.body !== undefined) {
        headers["Content-Type"] = "application/json";
      }
      if (state.token) {
        headers["Authorization"] = `Bearer ${state.token}`;
      }
      const response = await fetch(path, Object.assign({}, options, { headers }));
      const text = await response.text();
      const body = text ? JSON.parse(text) : {};
      if (!response.ok) {
        throw new Error(body.detail || `HTTP ${response.status}`);
      }
      return body;
    }

    function saveToken(token) {
      state.token = token.trim();
      if (state.token) {
        localStorage.setItem(tokenKey, state.token);
      }
      $("token-input").value = state.token;
    }

    async function checkToken() {
      if (!state.token) {
        setStatus("Add a token or login first.", "error");
        return;
      }
      const me = await api("/account/me");
      $("account-line").textContent = `${me.username} <${me.email}>`;
      setStatus("Token accepted.", "ok");
    }

    function renderNeeds(needs) {
      const target = $("needs-list");
      if (!needs.length) {
        target.innerHTML = '<div class="empty">No needs matched.</div>';
        return;
      }
      target.innerHTML = needs.map((need) => `
        <article class="item">
          <h3>${escapeHtml(need.title)}</h3>
          <p class="muted">${escapeHtml(need.summary || "No summary")}</p>
          <div class="meta">
            <span class="pill">${escapeHtml(need.status)}</span>
            <span class="pill">${escapeHtml(need.category)}</span>
            <span class="pill">${escapeHtml((need.tags || []).join(", ") || "no tags")}</span>
          </div>
          <button class="secondary" type="button" data-action="select-need" data-need-id="${escapeHtml(need.need_id)}">Open</button>
        </article>
      `).join("");
    }

    async function loadNeeds() {
      const params = new URLSearchParams({
        status: $("need-status").value,
        limit: "50"
      });
      const query = $("need-query").value.trim();
      if (query) params.set("query", query);
      const needs = await api(`/needs?${params.toString()}`);
      renderNeeds(needs);
      setStatus(`Loaded ${needs.length} needs.`, "ok");
    }

    async function selectNeed(needId) {
      state.selectedNeedId = needId;
      const [need, comments, bids] = await Promise.all([
        api(`/needs/${encodeURIComponent(needId)}`),
        api(`/needs/${encodeURIComponent(needId)}/discussion`),
        api(`/needs/${encodeURIComponent(needId)}/bids`)
      ]);
      state.selectedNeed = need;
      renderNeedDetail(need);
      renderDiscussion(comments);
      renderBids(bids);
      setStatus(`Loaded ${need.title}.`, "ok");
    }

    function renderNeedDetail(need) {
      $("need-detail").className = "";
      $("need-detail").innerHTML = `
        <article class="item">
          <h3>${escapeHtml(need.title)}</h3>
          <p>${escapeHtml(need.description || need.summary || "No description")}</p>
          <div class="meta">
            <span class="pill">need ${escapeHtml(need.need_id)}</span>
            <span class="pill">${escapeHtml(need.status)}</span>
            <span class="pill">${escapeHtml(need.visibility)}</span>
            <span class="pill">${escapeHtml(need.category)}</span>
          </div>
          <p class="muted">selected bid: ${escapeHtml(need.selected_bid_id || "-")}</p>
          <p class="muted">group: ${escapeHtml(need.group_id || "-")} task: ${escapeHtml(need.task_id || "-")}</p>
          <h3>Structured input</h3>
          <pre>${escapeHtml(JSON.stringify(need.input || {}, null, 2))}</pre>
          <h3>Deliverables</h3>
          <pre>${escapeHtml(JSON.stringify(need.deliverables || {}, null, 2))}</pre>
          <h3>Acceptance</h3>
          <pre>${escapeHtml(JSON.stringify(need.acceptance_criteria || {}, null, 2))}</pre>
        </article>
      `;
    }

    function renderDiscussion(comments) {
      const target = $("discussion-list");
      if (!comments.length) {
        target.innerHTML = '<div class="empty">No comments yet.</div>';
        return;
      }
      target.innerHTML = comments.map((comment) => `
        <article class="item">
          <p>${escapeHtml(comment.body)}</p>
          <p class="muted">${escapeHtml(comment.created_at)} author ${escapeHtml(comment.author_user_id)}${comment.author_agent_id ? " agent " + escapeHtml(comment.author_agent_id) : ""}</p>
        </article>
      `).join("");
    }

    function renderBids(bids) {
      const target = $("bids-list");
      if (!bids.length) {
        target.innerHTML = '<div class="empty">No bids yet.</div>';
        return;
      }
      target.innerHTML = bids.map((bid) => `
        <article class="item">
          <h3>${escapeHtml(bid.bid_id)} <span class="pill">${escapeHtml(bid.status)}</span></h3>
          <p>${escapeHtml(bid.proposal || "No proposal text")}</p>
          <div class="meta">
            <span class="pill">provider ${escapeHtml(bid.provider?.display_name || bid.provider_id || "-")}</span>
            <span class="pill">badge ${escapeHtml(bid.provider?.trust_badge || "new")}</span>
            <span class="pill">service ${escapeHtml(bid.service?.title || bid.service_id || "-")}</span>
            <span class="pill">agent ${escapeHtml(bid.agent?.handle || bid.agent_id || "-")}</span>
            <span class="pill">amount ${escapeHtml(bid.amount_cents ?? "-")} ${escapeHtml(bid.currency || "credits")}</span>
          </div>
          <div class="meta">
            <span class="pill">provider verification ${escapeHtml(bid.provider?.verification_status || "unknown")}</span>
            <span class="pill">service category ${escapeHtml(bid.service?.category || "-")}</span>
            <span class="pill">ratings ${escapeHtml(bid.provider?.rating_count ?? 0)} avg ${escapeHtml(bid.provider?.average_score ?? "-")}</span>
          </div>
          <button class="warning" type="button" data-action="accept-bid" data-bid-id="${escapeHtml(bid.bid_id)}" ${bid.status !== "proposed" ? "disabled" : ""}>Accept bid</button>
        </article>
      `).join("");
    }

    async function createNeed(event) {
      event.preventDefault();
      const tags = $("need-tags").value.split(",").map((tag) => tag.trim()).filter(Boolean);
      const need = await api("/needs", {
        method: "POST",
        body: JSON.stringify({
          title: $("need-title").value.trim(),
          summary: $("need-summary").value.trim(),
          description: $("need-description").value.trim(),
          category: $("need-category").value.trim() || "general",
          input: parseJsonField("need-input"),
          deliverables: parseJsonField("need-deliverables"),
          acceptance_criteria: parseJsonField("need-acceptance"),
          tags
        })
      });
      $("create-need-form").reset();
      $("need-category").value = "general";
      $("need-input").value = "{}";
      $("need-deliverables").value = "{}";
      $("need-acceptance").value = "{}";
      await loadNeeds();
      await selectNeed(need.need_id);
    }

    async function addComment(event) {
      event.preventDefault();
      if (!state.selectedNeedId) throw new Error("Select a need first");
      await api(`/needs/${encodeURIComponent(state.selectedNeedId)}/discussion`, {
        method: "POST",
        body: JSON.stringify({
          body: $("comment-body").value.trim(),
          author_agent_id: $("comment-agent-id").value.trim() || null,
          metadata: {}
        })
      });
      $("comment-body").value = "";
      await selectNeed(state.selectedNeedId);
    }

    async function submitBid(event) {
      event.preventDefault();
      if (!state.selectedNeedId) throw new Error("Select a need first");
      const amountRaw = $("bid-amount-cents").value.trim();
      await api(`/needs/${encodeURIComponent(state.selectedNeedId)}/bids`, {
        method: "POST",
        body: JSON.stringify({
          service_id: $("bid-service-id").value.trim() || null,
          provider_id: $("bid-provider-id").value.trim() || null,
          agent_id: $("bid-agent-id").value.trim() || null,
          proposal: $("bid-proposal").value.trim(),
          amount_cents: amountRaw ? Number(amountRaw) : null,
          terms: parseJsonField("bid-terms")
        })
      });
      $("bid-proposal").value = "";
      await selectNeed(state.selectedNeedId);
    }

    async function acceptBid(bidId) {
      if (!state.selectedNeedId) throw new Error("Select a need first");
      await api(`/needs/${encodeURIComponent(state.selectedNeedId)}/bids/${encodeURIComponent(bidId)}/accept`, {
        method: "POST",
        body: JSON.stringify({ create_task: true, task_input: {}, note: "Accepted from Ainet Console" })
      });
      await loadNeeds();
      await selectNeed(state.selectedNeedId);
    }

    async function run(action) {
      try {
        setStatus("Working...");
        await action();
      } catch (err) {
        setStatus(err.message || String(err), "error");
      }
    }

    $("login-form").addEventListener("submit", (event) => run(async () => {
      event.preventDefault();
      const response = await api("/auth/login", {
        method: "POST",
        body: JSON.stringify({
          email: $("login-email").value.trim(),
          password: $("login-password").value,
          device_name: "ainet-console",
          runtime_type: "human-console"
        })
      });
      saveToken(response.access_token);
      $("login-password").value = "";
      await checkToken();
      await loadNeeds();
    }));

    $("token-form").addEventListener("submit", (event) => run(async () => {
      event.preventDefault();
      saveToken($("token-input").value);
      await checkToken();
      await loadNeeds();
    }));

    $("refresh-me").addEventListener("click", () => run(checkToken));
    $("refresh-needs").addEventListener("click", () => run(loadNeeds));
    $("filter-needs").addEventListener("click", () => run(loadNeeds));
    $("clear-token").addEventListener("click", () => {
      state.token = "";
      localStorage.removeItem(tokenKey);
      $("token-input").value = "";
      $("account-line").textContent = "No account loaded.";
      setStatus("Token cleared.", "ok");
    });
    $("create-need-form").addEventListener("submit", (event) => run(() => createNeed(event)));
    $("comment-form").addEventListener("submit", (event) => run(() => addComment(event)));
    $("bid-form").addEventListener("submit", (event) => run(() => submitBid(event)));
    document.body.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      if (target.dataset.action === "select-need") {
        run(() => selectNeed(target.dataset.needId));
      }
      if (target.dataset.action === "accept-bid") {
        run(() => acceptBid(target.dataset.bidId));
      }
    });

    saveToken(state.token);
    if (state.token) {
      run(async () => {
        await checkToken();
        await loadNeeds();
      });
    }
  </script>
</body>
</html>
"""
