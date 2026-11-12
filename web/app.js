// Presentation only. Every number below arrives from the API ready to show.
// The token lives in memory (not localStorage), so a page refresh logs you out on purpose.
(() => {
  "use strict";
  let token = null;
  const $ = (id) => document.getElementById(id);

  async function api(path, options = {}) {
    const headers = { "Content-Type": "application/json" };
    if (token) headers.Authorization = "Bearer " + token;
    const response = await fetch(path, { ...options, headers });
    if (response.status === 401 && token) { logout(); throw new Error("Session ended. Please log in again."); }
    if (!response.ok) {
      let message = "Request failed";
      try { message = (await response.json()).detail || message; } catch (e) { /* keep default */ }
      throw new Error(typeof message === "string" ? message : "Request failed");
    }
    return response.json();
  }

  const show = (value, suffix = "") => (value === null || value === undefined ? "n/a" : Number(value).toLocaleString("en-IN") + suffix);

  function cell(row, text) { const td = document.createElement("td"); td.textContent = text; row.appendChild(td); }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  function card(label, value, hint) {
    const div = document.createElement("div"); div.className = "card";
    for (const [cls, text] of [["label", label], ["value", value], ["hint", hint || ""]]) {
      const el = document.createElement("div"); el.className = cls; el.textContent = text; div.appendChild(el);
    }
    return div;
  }

  function renderMetrics(d) {
    $("period").textContent = "Period " + d.period[0] + " to " + d.period[1];
    const cards = $("cards"); clear(cards);
    const pop = d.hires_period_over_period;
    cards.append(
      card("People in view", show(d.unique_people), "people, not candidate records"),
      card("At Offer on " + d.applications_at_offer.as_at, show(d.applications_at_offer.count), "from stage history"),
      card("Median time to hire", show(d.time_to_hire.median_days, " days"), show(d.time_to_hire.hires) + " hires"),
      card("Offer acceptance", show(d.offer_acceptance.rate_pct, "%"), show(d.offer_acceptance.accepted) + " accepted, " + show(d.offer_acceptance.declined) + " declined"),
      card("Hires vs previous period", show(pop.current) + " vs " + show(pop.previous),
           pop.previous_period_incomplete ? "previous period has incomplete data" : (pop.change_pct === null ? "no previous hires" : show(pop.change_pct, "% change"))),
      card("Total offered salary (INR)", show(d.offered_salary_total_inr), "all offer statuses")
    );
    const body = $("funnel").tBodies[0]; clear(body);
    for (const s of d.stage_conversion) {
      const tr = document.createElement("tr");
      cell(tr, s.stage); cell(tr, show(s.reached)); cell(tr, show(s.conversion_from_previous_pct, "%"));
      body.appendChild(tr);
    }
  }

  function renderRequisitions(list) {
    const body = $("reqs").tBodies[0]; clear(body);
    for (const r of list) {
      const tr = document.createElement("tr"); tr.className = "clickable";
      for (const v of [r.req_id, r.title, r.department, r.status, show(r.applications), show(r.offers), show(r.hires)]) cell(tr, v);
      tr.addEventListener("click", () => loadCandidates(r.req_id));
      body.appendChild(tr);
    }
  }

  async function loadCandidates(reqId) {
    $("app-error").textContent = "";
    try {
      const d = await api("/requisitions/" + encodeURIComponent(reqId) + "/candidates");
      $("cand-title").textContent = "Candidates for " + d.req_id; $("cand-title").hidden = false; $("cands").hidden = false;
      const body = $("cands").tBodies[0]; clear(body);
      for (const c of d.candidates) {
        const tr = document.createElement("tr");
        cell(tr, c.name); cell(tr, c.source); cell(tr, String(c.applied_at).slice(0, 10)); cell(tr, c.stage);
        body.appendChild(tr);
      }
    } catch (e) { $("app-error").textContent = e.message; }
  }

  async function loadDashboard() {
    $("app-error").textContent = "";
    try {
      const [metrics, reqs] = await Promise.all([api("/metrics"), api("/requisitions")]);
      renderMetrics(metrics); renderRequisitions(reqs.requisitions);
    } catch (e) { $("app-error").textContent = e.message; }
  }

  function logout() {
    token = null;
    $("app-view").hidden = true; $("who").hidden = true; $("login-view").hidden = false;
    $("cand-title").hidden = true; $("cands").hidden = true;
  }

  $("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("login-error").textContent = "";
    try {
      const result = await api("/auth/login", { method: "POST", body: JSON.stringify({ email: $("email").value, password: $("password").value }) });
      token = result.access_token; $("password").value = "";
      $("who-text").textContent = result.user.name + " (" + result.user.role.replace("_", " ") + ")";
      $("who").hidden = false; $("login-view").hidden = true; $("app-view").hidden = false;
      await loadDashboard();
    } catch (e) { $("login-error").textContent = e.message; }
  });
  $("logout").addEventListener("click", logout);
})();
