"use strict";
/* Sprinto Outreach UI. Vanilla JS, no build step. All dynamic text goes through esc(). */

const MAX_DOMAINS = 5;
const MAX_BATCHES = 3; // "Run pipeline" presses per browser session; the server enforces the real per-IP caps
const API_STAGES = ["scrape", "extract", "qualify", "poc", "draft", "send"];
const STEPS = [
  { id: "scrape", api: "scrape", icon: "globe", name: "Scrape", tool: "HTTP fetch", what: "Reads the homepage, about, security, customers and careers pages for raw signal." },
  { id: "extract", api: "extract", icon: "list", name: "Extract", tool: "Gemini", what: "Turns page text into structured company facts, each with a verbatim quote and source URL." },
  { id: "qualify", api: "qualify", icon: "target", name: "Qualify", tool: "Gemini + ICP rubric", what: "Scores the company against the ICP as a min/max interval; an agent loop fetches more pages when data is missing." },
  { id: "poc", api: "poc", icon: "user-search", name: "Find contact", tool: "Hunter.io", what: "Searches the domain and ranks the people it finds by company-size band to pick the decision-maker." },
  { id: "pain", api: "draft", icon: "bulb", name: "Pain points", tool: "Gemini", what: "Picks the two most likely pains for that person's role, each tied to evidence from the company's own pages." },
  { id: "draft", api: "draft", icon: "pen", name: "Draft email", tool: "Gemini + validator", what: "Writes a short email to the person by name with a specific hook, then validates length, links and claims." },
  { id: "send", api: "send", icon: "send", name: "Send", tool: "Resend", what: "Dry-run preview first; on confirmation sends to the owner's own inbox only." },
];
const OUTCOMES = {
  qualified: { label: "Qualified", icon: "check", cls: "b-ok" },
  sent: { label: "Sent", icon: "send", cls: "b-ok" },
  disqualified: { label: "Disqualified", icon: "x", cls: "b-bad" },
  insufficient: { label: "Insufficient data", icon: "help", cls: "b-warn" },
  no_contact: { label: "No contact", icon: "user-x", cls: "b-warn" },
  rejected_draft: { label: "Rejected draft", icon: "file-x", cls: "b-warn" },
  failed: { label: "Failed", icon: "alert", cls: "b-bad" },
  running: { label: "Running", icon: "loader", cls: "b-info" },
  queued: { label: "Queued", icon: "circle", cls: "b-neutral" },
};
const FAQ = [
  ["Who does an email ever go to?", "<p>Only to the owner's own address. The recipient is fixed on the server and any recipient in a request is ignored. The real person found by Hunter appears only inside the subject tag, so you can judge the match without anyone being contacted.</p>"],
  ["Does it send straight away?", "<p>No. Every run ends in a dry-run preview of the exact payload. Sending needs you to tick a confirmation box and press the send button, and the server also requires an explicit confirm flag. A per-hour send cap falls back to the preview with a clear message.</p>"],
  ["What stops it burning credits or being abused?", "<ul><li>Per-IP request and run-start limits, a live Hunter search budget, and a cap on live sends.</li><li>At most 5 domains per run and 3 runs per browser session.</li><li>Strict domain validation: public hostnames only, no IPs, localhost or paths.</li></ul>"],
  ["How is untrusted page text handled?", "<p>Website text is treated as data, never as instructions. Extracted facts must carry a quote that actually appears on the page, facts that fail that check are dropped, and pages that look like prompt injection are flagged.</p>"],
  ["Which claims can the email make?", "<p>Only facts quoted from the company's own pages (evidence ids E1, E2...) and a short whitelist of Sprinto claims (S1, S2). The validator checks the greeting uses the person's first name, the body is 50 to 90 words, there are no URLs, and every claim maps to a known id. The email ends with a CAN-SPAM / GDPR style footer.</p>"],
  ["What are the known limits?", "<ul><li>Company sites rarely state funding or headcount, so many real companies land in the unknown band. You can continue them with a logged manual override.</li><li>Hunter may have no named person for a small company; the run then stops with no contact.</li><li>Rate limits and budgets are best effort per server instance and reset on a cold start.</li><li>Rubric weights are starting hypotheses, not measured truth.</li></ul>"],
  ["How do I rerun or batch it?", "<p>Edit the domain list and press Run pipeline again. Results for a domain are cached server side, so rerunning the same domain makes no new model calls. Use Clear results to start fresh, and Download decision log to keep a copy.</p>"],
];

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ico = (n, cls = "") => `<svg class="ic ${cls}" aria-hidden="true"><use href="#i-${n}"/></svg>`;
const fmtMs = (ms) => (ms == null ? "" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "");
const link = (u) => (safeUrl(u) ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(u)}</a>` : esc(u || ""));

const store = {
  get(k, area = "session") { try { return window[area + "Storage"].getItem(k); } catch (e) { return null; } },
  set(k, v, area = "session") { try { window[area + "Storage"].setItem(k, v); return true; } catch (e) { return false; } },
  del(k, area = "session") { try { window[area + "Storage"].removeItem(k); } catch (e) {} },
};

let runs = [];
let owner = "";
let busy = false;
let rubric = null;
let sort = { k: null, dir: 1 };
let counter = 0;

/* ---------- toasts ---------- */
function toast(msg, type = "info") {
  const el = document.createElement("div");
  el.className = "toast " + (type === "err" ? "err" : "");
  el.setAttribute("role", type === "err" ? "alert" : "status");
  el.innerHTML = `${ico(type === "err" ? "alert" : "check")}<span>${esc(msg)}</span><button class="icon-btn" type="button" aria-label="Dismiss notification">${ico("close")}</button>`;
  el.querySelector("button").addEventListener("click", () => el.remove());
  $("toasts").appendChild(el);
  setTimeout(() => el.remove(), type === "err" ? 9000 : 5000);
}

/* ---------- theme ---------- */
function applyThemeUi() {
  const dark = document.documentElement.dataset.theme === "dark" ||
    (!document.documentElement.dataset.theme && window.matchMedia("(prefers-color-scheme: dark)").matches);
  const b = $("themeBtn");
  b.setAttribute("aria-pressed", String(dark));
  b.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
  $("themeIcon").innerHTML = `<use href="#i-${dark ? "sun" : "moon"}"/>`;
}
$("themeBtn").addEventListener("click", () => {
  const dark = $("themeBtn").getAttribute("aria-pressed") === "true";
  const next = dark ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  store.set("theme", next, "local");
  applyThemeUi();
});
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyThemeUi);

/* ---------- static sections ---------- */
function renderStatic() {
  $("howSteps").innerHTML = STEPS.map((s, i) => `<li class="step-card"><div class="step-top"><span class="step-ic">${ico(s.icon)}</span><div><div class="step-n">Step ${i + 1}</div><h3>${esc(s.name)}</h3></div></div><p>${esc(s.what)}</p><span class="tool">${esc(s.tool)}</span></li>`).join("");
  $("faqAcc").innerHTML = FAQ.map(([q, a]) => `<details><summary>${esc(q)}${ico("chevron", "chev")}</summary><div class="ans">${a}</div></details>`).join("");
}

/* ---------- interval bar ---------- */
function ivBar(min, max, qmin, rmax, compact) {
  const c = (n) => Math.max(0, Math.min(100, n));
  const left = c(min), width = Math.max(1, c(max) - c(min));
  return `<div class="ivbar ${compact ? "compact" : ""}" role="img" aria-label="Score interval ${min} to ${max} out of 100. Reject below ${rmax}, qualify at ${qmin} or above.">
    <div class="iv-range" style="left:${left}%;width:${width}%"></div>
    <div class="iv-mark" style="left:${rmax}%"><span>reject &lt; ${rmax}</span></div>
    <div class="iv-mark" style="left:${qmin}%"><span>qualify &ge; ${qmin}</span></div></div>
    <div class="iv-scale"><span>0</span><span>min ${min}, max ${max}</span><span>100</span></div>`;
}
function ivVerdict(min, max, qmin, rmax) {
  if (min >= qmin) return ["Qualified: even counting every unknown as zero, the score clears " + qmin + ".", "ok"];
  if (max < rmax) return ["Rejected: even counting every unknown at full weight, the score stays below " + rmax + ".", "bad"];
  return ["Unknown band: the research loop fetches up to 3 more pages, then the company is qualified, rejected, or marked insufficient data.", "warn"];
}
function updateIvDemo() {
  let min = +$("ivMin").value, max = +$("ivMax").value;
  if (max < min) { max = min; $("ivMax").value = String(max); }
  $("ivMinOut").textContent = min; $("ivMaxOut").textContent = max;
  const qmin = rubric ? rubric.qualify_min : 60, rmax = rubric ? rubric.reject_max : 45;
  $("ivBar").innerHTML = ivBar(min, max, qmin, rmax, false);
  const [txt] = ivVerdict(min, max, qmin, rmax);
  $("ivVerdict").textContent = txt;
}
["ivMin", "ivMax"].forEach((id) => $(id).addEventListener("input", updateIvDemo));

/* ---------- rubric ---------- */
async function loadRubric() {
  const box = $("rubricBox");
  box.setAttribute("aria-busy", "true");
  try {
    const res = await fetch("/api/rubric");
    if (!res.ok) throw new Error("HTTP " + res.status);
    rubric = await res.json();
  } catch (e) {
    box.setAttribute("aria-busy", "false");
    box.innerHTML = `<div class="callout warn" role="status">${ico("alert")}<div>The rubric could not be loaded. <button class="btn btn-secondary btn-sm" type="button" id="rubricRetry">Retry</button></div></div>`;
    $("rubricRetry").addEventListener("click", loadRubric);
    updateIvDemo();
    return;
  }
  const maxW = Math.max(...rubric.signals.map((s) => s.weight), 1);
  const rows = rubric.signals.map((s) => `<tr><th scope="row">${esc(s.label)}<br><small>${esc(s.id)}, group ${esc(s.group)}</small></th>
    <td class="num"><div class="wbar"><div class="wbar-track"><div class="wbar-fill" style="width:${(s.weight / maxW) * 100}%"></div></div><b>${esc(s.weight)}</b></div></td>
    <td>${(s.where_found || []).map((k) => `<span class="chip-kind">${esc(k)}</span>`).join("") || "<small>derived</small>"}</td></tr>`).join("");
  box.setAttribute("aria-busy", "false");
  box.innerHTML = `<p><span class="badge b-info">Rubric ${esc(rubric.version)}</span> <span class="hash" title="sha256 of the rubric file">sha256 ${esc(rubric.sha256)}</span></p>
    <p class="hint">${esc(rubric.description)}</p>
    <h3>Hard gates (fail one and the company is rejected)</h3>
    <ul class="gate-list">${rubric.gates.map((g) => `<li>${esc(g.label)} <small>(${esc(g.field)} fails on ${esc(JSON.stringify(g.fail_values))})</small></li>`).join("")}</ul>
    <h3>Weighted signals (weights sum to ${rubric.signals.reduce((a, s) => a + s.weight, 0)})</h3>
    <div class="table-wrap"><table class="data"><caption class="sr">Rubric signals with weights and where each is found</caption><thead><tr><th scope="col">Signal</th><th scope="col">Weight</th><th scope="col">Where it is found</th></tr></thead><tbody>${rows}</tbody></table></div>
    <h3>Penalties (already certified means lower need)</h3>
    <ul class="gate-list">${rubric.penalties.map((p) => `<li>${esc(p.label)}: <b>-${esc(p.points)}</b> <small>(${esc(p.requires.join(" + "))}${p.excludes.length ? ", not " + esc(p.excludes.join(", ")) : ""})</small></li>`).join("") || "<li>None</li>"}</ul>`;
  document.querySelectorAll("[data-q]").forEach((el) => { el.textContent = rubric[el.dataset.q]; });
  updateIvDemo();
}

/* ---------- domains input ---------- */
function parseDomains(text) {
  const parts = text.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);
  const valid = [], bad = [], dupes = [];
  const label = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
  for (const raw of parts) {
    let d = raw.toLowerCase().replace(/^[a-z]+:\/\//, "").split(/[/?#]/)[0].replace(/^www\./, "").replace(/\.$/, "");
    const labels = d.split(".");
    const ok = d.length <= 253 && labels.length >= 2 && labels.every((l) => label.test(l)) && !/^\d+$/.test(labels[labels.length - 1]) && !["local", "localhost", "internal", "lan", "home", "corp", "test", "invalid"].includes(labels[labels.length - 1]);
    if (!ok) { bad.push(raw); continue; }
    if (valid.includes(d)) { dupes.push(d); continue; }
    valid.push(d);
  }
  return { valid, bad, dupes };
}
function refreshChips() {
  const { valid, bad, dupes } = parseDomains($("domains").value);
  $("chips").innerHTML = valid.map((d) => `<span class="chip">${ico("check")}${esc(d)}</span>`).join("") + bad.map((d) => `<span class="chip bad">${ico("x")}${esc(d)}</span>`).join("");
  const errs = [];
  if (bad.length) errs.push(`Not a valid public domain: ${bad.join(", ")}. Use a name like example.com (no IP addresses or localhost).`);
  if (valid.length > MAX_DOMAINS) errs.push(`At most ${MAX_DOMAINS} domains per run (you entered ${valid.length}).`);
  if (dupes.length) errs.push(`Duplicates removed: ${dupes.join(", ")}.`);
  $("domErr").textContent = errs.join("\n");
  $("domains").setAttribute("aria-invalid", bad.length || valid.length > MAX_DOMAINS ? "true" : "false");
  return { valid, bad, tooMany: valid.length > MAX_DOMAINS };
}
$("domains").addEventListener("input", refreshChips);
$("exampleBtn").addEventListener("click", () => { $("domains").value = "vanta.com\nlinear.app\ncalendly.com"; refreshChips(); $("domains").focus(); });
$("clearBtn").addEventListener("click", () => {
  if (busy) { toast("A run is in progress. Wait for it to finish.", "err"); return; }
  runs = []; save(); renderAll();
});

/* ---------- persistence ---------- */
function save() {
  const payload = { owner, runs, batches: batchesUsed() };
  if (store.set("runs.v1", JSON.stringify(payload))) return;
  const slim = { owner, batches: batchesUsed(), runs: runs.map((r) => ({ ...r, state: null })) };
  store.set("runs.v1", JSON.stringify(slim));
}
function restore() {
  const raw = store.get("runs.v1");
  if (!raw) return;
  try {
    const p = JSON.parse(raw);
    owner = p.owner || "";
    runs = (p.runs || []).map((r) => {
      if (r.status === "running" || r.status === "queued") { r.status = "failed"; r.error = "Interrupted by a page refresh. Run the domain again."; r.current = null; }
      return r;
    });
    counter = runs.reduce((m, r) => Math.max(m, r.id), 0);
  } catch (e) { runs = []; }
}
const batchesUsed = () => parseInt(store.get("batches") || "0", 10);
function showRunsLeft() { $("runsLeft").textContent = `${Math.max(0, MAX_BATCHES - batchesUsed())} of ${MAX_BATCHES} runs left in this browser session.`; }

/* ---------- API ---------- */
async function api(path, body) {
  const headers = {};
  const pw = store.get("pw");
  if (pw) headers["x-app-password"] = pw;
  const opt = { method: body ? "POST" : "GET", headers };
  if (body) { headers["content-type"] = "application/json"; opt.body = JSON.stringify(body); }
  let res, data;
  try { res = await fetch(path, opt); } catch (e) { return { status: 0, data: { message: "Network error: could not reach the server." } }; }
  try { data = await res.json(); } catch (e) { data = { message: `Unexpected response (HTTP ${res.status}).` }; }
  return { status: res.status, data };
}

/* ---------- pipeline driving ---------- */
const stageOf = (run, api) => run.results && run.results[api];
function currentStepId(run) { return run.current; }

async function callStage(run, apiStage, extra = {}) {
  run.current = apiStage; run.status = "running";
  renderRun(run);
  const t0 = performance.now();
  const body = Object.assign({ stage: apiStage, domain: run.domain, state: run.state || {} }, extra);
  const { status, data } = await api("/api/run", body);
  const ms = Math.round(performance.now() - t0);
  run.current = null;
  run.timings[apiStage] = ms;
  if (status !== 200) {
    run.status = "failed";
    run.results[apiStage] = { stage: apiStage, status: "failed", detail: `${data.error || "error"}: ${data.message || status}` };
    run.error = data.message || `HTTP ${status}`;
    if (status === 429) toast(data.message || "Rate limit reached. Try again in a minute.", "err");
    else if (status === 503) { $("notConfigured").hidden = false; toast("The server is not configured yet.", "err"); }
    else if (status === 401) { toast("Wrong or missing password.", "err"); store.del("pw"); setTimeout(() => location.reload(), 1200); }
    else toast(`${run.domain}: ${run.error}`, "err");
    save(); renderAll();
    return { ok: false, data };
  }
  if (data.state) run.state = data.state;
  if (data.owner_email) owner = data.owner_email;
  run.results[apiStage] = data;
  if (data.send_note) toast(data.send_note);
  const ok = data.status === "ok";
  run.status = ok ? "running" : data.status === "stopped" ? "stopped" : "failed";
  if (!ok && data.status === "failed") toast(`${run.domain}: ${data.detail || "stage failed"}`, "err");
  save(); renderAll();
  return { ok, data };
}

async function continueFrom(run, apiStage) {
  const idx = API_STAGES.indexOf(apiStage);
  for (const s of API_STAGES.slice(idx)) {
    const r = await callStage(run, s, s === "poc" ? { live_hunter: $("optHunter").checked } : {});
    if (!r.ok) { save(); return; }
  }
  run.status = "done";
  save(); renderAll();
}

async function runBatch(domains) {
  busy = true; $("runBtn").disabled = true; $("runBtn").setAttribute("aria-busy", "true");
  const batch = domains.map((d) => ({ id: ++counter, domain: d, state: {}, results: {}, timings: {}, status: "queued", current: null, allowOverride: $("optOverride").checked, confirmed: false }));
  runs = batch.concat(runs.filter((r) => !domains.includes(r.domain)));
  renderAll();
  for (const run of batch) {
    await continueFrom(run, "scrape");
    if (run.error && /rate limit|per minute|per hour/i.test(run.error)) {
      batch.filter((r) => r.status === "queued").forEach((r) => { r.status = "failed"; r.error = "Skipped: rate limit reached."; });
      break;
    }
  }
  busy = false; $("runBtn").disabled = false; $("runBtn").removeAttribute("aria-busy");
  save(); renderAll(); // after busy=false so action buttons render enabled
}

$("runForm").addEventListener("submit", (e) => {
  e.preventDefault();
  if (busy) return;
  const { valid, bad, tooMany } = refreshChips();
  if (!valid.length && !bad.length) { $("domErr").textContent = "Enter at least one company domain."; $("domains").focus(); return; }
  if (bad.length || tooMany) { $("domains").focus(); return; }
  if (batchesUsed() >= MAX_BATCHES) { $("domErr").textContent = `Session limit reached (${MAX_BATCHES} runs). Close this tab and reopen to continue.`; return; }
  store.set("batches", String(batchesUsed() + 1)); showRunsLeft();
  runBatch(valid);
  $("runs").scrollIntoView({ behavior: "smooth", block: "start" });
});

async function overrideRun(id) {
  const run = runs.find((r) => r.id === id);
  if (!run || busy) return;
  busy = true;
  const r = await callStage(run, "qualify", { override_insufficient: true });
  if (r.ok) await continueFrom(run, "poc");
  busy = false; renderAll();
}
async function sendRun(id) {
  const run = runs.find((r) => r.id === id);
  if (!run || busy || !run.confirmed) return;
  busy = true;
  const r = await callStage(run, "send", { confirm_send: true });
  if (r.ok) run.status = "done";
  busy = false;
  save(); renderAll();
}

/* ---------- derived values ---------- */
function outcomeOf(run) {
  if (run.status === "queued") return "queued";
  if (run.status === "running") return "running";
  const res = run.results || {};
  if (Object.values(res).some((r) => r.status === "failed") || (run.status === "failed")) return "failed";
  const stopped = Object.values(res).find((r) => r.status === "stopped");
  if (stopped) {
    const m = { insufficient_data: "insufficient", disqualified: "disqualified", no_contact: "no_contact", rejected_draft: "rejected_draft" };
    return m[stopped.stop_reason] || "failed";
  }
  const send = res.send;
  if (send && send.status === "ok") return send.result && send.result.mode === "sent" ? "sent" : "qualified";
  return run.status === "done" ? "qualified" : "running";
}
function scoreOf(run) {
  const q = stageOf(run, "qualify");
  const s = q && q.result && q.result.score;
  return s && s.score_min != null ? { min: s.score_min, max: s.score_max } : null;
}
function contactOf(run) {
  const p = stageOf(run, "poc");
  const c = p && p.result && p.result.contact;
  return c ? [c.first_name, c.last_name].filter(Boolean).join(" ") : "";
}
const draftOf = (run) => { const d = stageOf(run, "draft"); return d && d.result && d.result.draft ? d.result : null; };
function statusText(run) {
  const o = outcomeOf(run);
  if (o === "sent") return "Sent to owner";
  if (o === "qualified") return "Draft ready (dry run, not sent)";
  if (o === "running") return "Working on " + (run.current || "next step");
  if (o === "queued") return "Waiting";
  const last = Object.values(run.results || {}).filter((r) => r.status !== "ok").pop();
  return last ? [last.stop_reason, last.detail].filter(Boolean).join(": ").slice(0, 140) : (run.error || "");
}
function stepState(run, step) {
  const r = stageOf(run, step.api);
  if (run.current === step.api && run.status === "running") return "running";
  if (step.id === "pain" && r) {
    const has = r.result && r.result.pain_points && r.result.pain_points.length;
    if (r.status === "failed") return "failed";
    return has || r.status === "ok" ? "done" : "stopped";
  }
  if (r) return r.status === "ok" ? "done" : r.status === "stopped" ? "stopped" : "failed";
  const ended = ["stopped", "failed", "done"].includes(run.status);
  return ended ? "skipped" : "pending";
}
const STEP_ICON = { done: "check", running: "loader", stopped: "alert", failed: "x", pending: "circle", skipped: "circle" };

/* ---------- stage detail builders ---------- */
const quote = (q, url) => (q ? `<blockquote class="q">&ldquo;${esc(q)}&rdquo;<cite>${link(url)}</cite></blockquote>` : "");
const tableWrap = (html) => `<div class="table-wrap">${html}</div>`;

function scrapeDetail(r) {
  const res = r.result || {};
  const pages = res.pages || [];
  const rows = pages.map((p) => `<tr><td>${esc(p.kind || "other")}</td><td>${link(p.url)}</td><td>${esc(p.status)}${p.reason ? `<br><small>${esc(p.reason)}</small>` : ""}</td><td class="num">${esc(p.chars || 0)}</td><td>${p.from_cache ? "cache" : "live"}</td></tr>`).join("");
  return `<p><b>${esc(res.usable ?? 0)}</b> usable of ${pages.length} pages. Kinds found: ${(res.kinds_found || []).map((k) => `<span class="chip-kind">${esc(k)}</span>`).join("") || "none"}</p>
    ${pages.length ? tableWrap(`<table class="data"><caption class="sr">Pages fetched</caption><thead><tr><th scope="col">Kind</th><th scope="col">URL</th><th scope="col">Status</th><th scope="col">Chars</th><th scope="col">Source</th></tr></thead><tbody>${rows}</tbody></table>`) : ""}`;
}
function factRows(profile) {
  const rows = [];
  const one = (label, f, val) => { if (f) rows.push([label, val(f), f.quote, f.source_url]); };
  one("Name", profile.name, (f) => f.value);
  one("Offering", profile.offering, (f) => f.value);
  one("B2B", profile.is_b2b, (f) => (f.value ? "Yes" : "No"));
  one("Stage", profile.stage, (f) => f.value + (f.as_of ? ` (as of ${f.as_of})` : ""));
  one("Headcount", profile.headcount, (f) => f.value);
  (profile.compliance_mentions || []).forEach((f) => one("Compliance", f, (x) => `${x.framework} (${x.status})`));
  (profile.hiring_signals || []).forEach((f) => one("Hiring", f, (x) => x.role));
  (profile.enterprise_customers || []).forEach((f) => one("Enterprise customer", f, (x) => x.name));
  return rows;
}
function extractDetail(r) {
  const res = r.result || {};
  const rows = factRows(res.profile || {});
  return `<p><b>${esc(res.evidence_kept ?? 0)}</b> of ${esc(res.evidence_total ?? 0)} evidenced facts kept${(res.evidence_dropped || []).length ? `, ${res.evidence_dropped.length} dropped because the quote was not found on the page` : ""}.${(res.injection_suspected_pages || []).length ? ` <span class="badge b-warn">${ico("alert")}Possible prompt injection on ${res.injection_suspected_pages.length} page(s), treated as data</span>` : ""}</p>
    ${rows.length ? tableWrap(`<table class="data"><caption class="sr">Extracted facts with evidence</caption><thead><tr><th scope="col">Field</th><th scope="col">Value</th><th scope="col">Evidence</th></tr></thead><tbody>${rows.map(([k, v, q, u]) => `<tr><th scope="row">${esc(k)}</th><td>${esc(v)}</td><td>${quote(q, u)}</td></tr>`).join("")}</tbody></table>`) : "<p class='hint'>No facts were stated on the pages.</p>"}`;
}
function qualifyDetail(r) {
  const q = r.result;
  if (!q) return `<p>${esc(r.detail || "")}</p>`;
  const sc = q.score || {};
  const th = q.thresholds || {};
  const qmin = th.qualify_min ?? (rubric && rubric.qualify_min) ?? 60, rmax = th.reject_max ?? (rubric && rubric.reject_max) ?? 45;
  let h = "";
  if (q.override) h += `<div class="override-banner">${ico("alert")}<span>Manual override: ${esc(q.override_note || "continued despite insufficient data")}</span></div>`;
  h += `<p><b>Rubric verdict:</b> <span class="badge ${q.verdict === "qualified" ? "b-ok" : q.verdict === "disqualified" ? "b-bad" : "b-warn"}">${esc(q.verdict)}</span> ${esc(q.reason || "")}</p>`;
  if (sc.score_min != null) h += ivBar(sc.score_min, sc.score_max, qmin, rmax, true);
  if (q.rubric_version) h += `<p class="hint">Rubric ${esc(q.rubric_version)} <span class="hash">sha256 ${esc(q.rubric_sha256 || "")}</span></p>`;
  if ((sc.gates || []).length) h += `<h4>Hard gates</h4>` + tableWrap(`<table class="data"><caption class="sr">Gates</caption><thead><tr><th scope="col">Gate</th><th scope="col">Result</th><th scope="col">Basis</th></tr></thead><tbody>${sc.gates.map((g) => `<tr><td>${esc(g.label || g.id)}</td><td>${esc(g.status)}</td><td>${esc(g.basis)}${(g.evidence || []).map((e) => quote(e.quote, e.source_url)).join("")}</td></tr>`).join("")}</tbody></table>`);
  if ((sc.signals || []).length) {
    h += `<h4>Signals</h4>` + tableWrap(`<table class="data"><caption class="sr">Score breakdown per signal</caption><thead><tr><th scope="col">Signal</th><th scope="col">Points</th><th scope="col">Why, with evidence</th></tr></thead><tbody>${sc.signals.map((s) => {
      const known = s.status === "known";
      const pts = known ? `${s.points_min}` : `0 to ${s.weight}`;
      const pct = ((known ? s.points_min : s.points_max) / (s.weight || 1)) * 100;
      return `<tr><th scope="row">${esc(s.label || s.id)}<br><small>weight ${esc(s.weight)}, ${esc(s.status)}</small></th><td class="num"><div class="wbar"><div class="wbar-track"><div class="wbar-fill" style="width:${Math.min(100, pct)}%"></div></div><b>${esc(pts)}</b></div></td><td>${esc(s.basis)}${(s.evidence || []).map((e) => quote(e.quote, e.source_url)).join("")}</td></tr>`;
    }).join("")}</tbody></table>`);
  }
  if ((sc.penalties || []).length) h += `<p><b>Penalties:</b> ${sc.penalties.map((p) => esc((p.label || p.id) + " -" + p.points)).join("; ")}</p>`;
  const ag = q.research;
  if (ag && ag.stop_reason && ag.stop_reason !== "not_needed") {
    h += `<h4>Research loop</h4><p>Stop reason: <span class="badge b-neutral">${esc(ag.stop_reason)}</span> after ${esc(ag.fetches ?? 0)} fetch(es).</p>`;
    if ((ag.steps || []).length) h += tableWrap(`<table class="data"><caption class="sr">Research steps</caption><thead><tr><th scope="col">#</th><th scope="col">Page</th><th scope="col">Reason</th><th scope="col">Outcome</th><th scope="col">Score after</th></tr></thead><tbody>${ag.steps.map((s) => `<tr><td>${esc(s.iteration)}</td><td>${link(s.url) || esc(s.tool)}</td><td>${esc(s.reason || "")}</td><td>${esc(s.outcome)}${s.refusal ? `<br><small>${esc(s.refusal)}</small>` : ""}</td><td class="num">${esc(s.score_min)} to ${esc(s.score_max)}</td></tr>`).join("")}</tbody></table>`);
  } else if (ag) h += `<p class="hint">No research needed: the first pass was decisive.</p>`;
  if ((q.decided_with_unknowns || []).length) h += `<p class="hint">Unknown signals: ${q.decided_with_unknowns.map(esc).join(", ")}</p>`;
  return h;
}
function pocDetail(r) {
  const p = r.result;
  if (!p) return `<p>${esc(r.detail || r.stop_reason || "")}</p>`;
  const c = p.contact || {};
  const name = [c.first_name, c.last_name].filter(Boolean).join(" ");
  let h = `<dl class="kv"><dt>Chosen</dt><dd><b>${esc(name)}</b>, ${esc(c.position || "")}</dd><dt>Email</dt><dd>${esc(c.email || "")}${c.confidence != null ? ` <small>confidence ${esc(c.confidence)}</small>` : ""} <span class="badge b-neutral">${esc(c.source || "")}</span></dd>${c.linkedin ? `<dt>LinkedIn</dt><dd>${link(c.linkedin)}</dd>` : ""}<dt>Why</dt><dd>${esc(p.reason || "")}</dd><dt>Size band</dt><dd>${esc(p.band || "")}: ${esc(p.band_basis || "")}</dd></dl>`;
  const cands = (p.top_candidates || []).slice(0, 3);
  if (cands.length) h += `<h4>Top candidates (of ${esc(p.candidates_seen ?? cands.length)} seen)</h4>` + tableWrap(`<table class="data"><caption class="sr">Ranked candidates</caption><thead><tr><th scope="col">Rank</th><th scope="col">Person</th><th scope="col">Title</th><th scope="col">Score</th><th scope="col">Ranking notes</th></tr></thead><tbody>${cands.map((x, i) => `<tr><td>${i + 1}</td><td>${esc([x.first_name, x.last_name].filter(Boolean).join(" "))}${x.linkedin ? `<br>${link(x.linkedin)}` : ""}</td><td>${esc(x.position || "")}<br><small>${esc(x.category || "")}</small></td><td class="num">${esc(x.score)}</td><td>${esc((x.notes || []).join("; "))}${x.eligible === false ? " (not eligible)" : ""}</td></tr>`).join("")}</tbody></table>`);
  if ((p.risks || []).length) h += `<p class="hint">Risks: ${p.risks.map(esc).join("; ")}</p>`;
  return h;
}
function painDetail(r) {
  const d = r.result;
  const pains = (d && d.pain_points) || [];
  if (!pains.length) return `<p class="hint">No pain points available for this run.</p>`;
  const pack = (d.evidence_pack || []);
  return `<div class="pains">${pains.map((p, i) => {
    const ev = pack.find((e) => e.id === p.evidence_id);
    return `<div class="pain"><span class="badge b-info">Pain ${i + 1}</span><p><b>${esc(p.pain)}</b></p><p class="hint">Why it fits the role: ${esc(p.role_link)}</p><p class="hint">Evidence ${esc(p.evidence_id)}</p>${ev ? quote(ev.quote, ev.source_url) : ""}</div>`;
  }).join("")}</div>${d.pain_points_source ? `<p class="hint">Source: ${esc(d.pain_points_source)}</p>` : ""}`;
}
function wordCount(t) { return (t || "").trim().split(/\s+/).filter(Boolean).length; }
function validatorChecks(d) {
  const core = d.core_body || "";
  const ids = new Set((d.evidence_pack || []).map((e) => e.id));
  const claims = d.claims_used || [];
  const wl = claims.length > 0 && claims.every((c) => /^S\d+$/.test(c.evidence_id) || ids.has(c.evidence_id));
  const wc = wordCount(core);
  return [
    ["Greets the person by first name", !!d.greets_by_first_name],
    [`Body is 50 to 90 words (${wc})`, wc >= 50 && wc <= 90],
    ["No URLs in the body", !/https?:\/\/|www\./i.test(core)],
    ["Every claim maps to evidence or a whitelisted Sprinto claim", wl],
  ];
}
function draftDetail(r) {
  const d = r.result;
  if (!d || !d.draft) return `<p>${esc(r.detail || r.stop_reason || "")}</p>`;
  const checks = validatorChecks(d);
  const v = d.validation;
  return `<p class="hint">Subject</p><p><b>${esc(d.draft.subject)}</b></p><div class="mail">${esc(d.draft.body)}</div>
    <h4>Validator</h4><ul class="checks">${checks.map(([t, ok]) => `<li>${ico(ok ? "check" : "x")}<span>${esc(t)}</span> <span class="badge ${ok ? "b-ok" : "b-bad"}">${ok ? "pass" : "fail"}</span></li>`).join("")}</ul>
    ${v ? `<p class="hint">Server validator: ${v.ok ? "passed" : "failed"} after ${esc(v.attempts)} attempt(s)${(v.failures || []).length ? ": " + v.failures.map(esc).join("; ") : ""}</p>` : ""}`;
}
function sendDetail(r) {
  const s = r.result;
  if (!s) return `<p>${esc(r.detail || "")}</p>`;
  const p = s.payload || {};
  const live = s.mode === "sent";
  return `<p><span class="badge ${live ? "b-ok" : "b-warn"}">${ico(live ? "send" : "mail")}${live ? "Sent" : "Dry run, not sent"}</span>${s.id ? ` <small>id ${esc(s.id)}</small>` : ""}</p>
    <dl class="kv"><dt>From</dt><dd>${esc(p.from)}</dd><dt>To</dt><dd>${esc([].concat(p.to || []).join(", "))}</dd><dt>Subject</dt><dd>${esc(p.subject)}</dd></dl><div class="mail">${esc(p.text || "")}</div>`;
}

/* ---------- run card ---------- */
function stageDetails(run) {
  const defs = [
    ["scrape", "scrape", "Scrape: pages found by kind", scrapeDetail], ["extract", "extract", "Extract: company profile and evidence", extractDetail],
    ["qualify", "qualify", "Qualify: score breakdown", qualifyDetail], ["poc", "poc", "Find contact: ranked candidates", pocDetail],
    ["pain", "draft", "Pain points", painDetail], ["draft", "draft", "Draft email", draftDetail], ["send", "send", "Send", sendDetail],
  ];
  return defs.map(([key, api, title, fn]) => {
    const r = stageOf(run, api);
    if (!r) return "";
    if (key === "pain" && !(r.result && r.result.pain_points)) return "";
    const open = run.open && run.open[key] ? " open" : "";
    let body;
    try { body = r.result || key === "qualify" ? fn(r) : `<p>${esc([r.stop_reason, r.detail].filter(Boolean).join(": "))}</p>`; } catch (e) { body = "<p class='hint'>Detail unavailable.</p>"; }
    const extra = r.status !== "ok" ? `<p><span class="badge ${r.status === "stopped" ? "b-warn" : "b-bad"}">${esc(r.status)}</span> ${esc([r.stop_reason, r.detail].filter(Boolean).join(": "))}</p>` : "";
    return `<details class="stage" data-key="${key}"${open}><summary>${ico(STEPS.find((s) => s.id === key).icon)}${esc(title)}${ico("chevron", "chev")}</summary><div class="stage-body">${extra}${body}</div></details>`;
  }).join("");
}
function actionBoxes(run) {
  let h = "";
  const q = stageOf(run, "qualify");
  if (q && q.status === "stopped" && q.stop_reason === "insufficient_data" && run.allowOverride && !stageOf(run, "poc")) {
    const sc = (q.result && q.result.score) || {};
    h += `<div class="action-box warn"><p><b>Score ${esc(sc.score_min)} to ${esc(sc.score_max)} is in the unknown band.</b> The rubric could not decide. Continuing is your call, it is recorded in the decision log, and it is never offered for disqualified companies.</p><button class="btn btn-secondary btn-sm" type="button" data-act="override" data-id="${run.id}" data-fid="ov${run.id}"${busy ? " disabled" : ""}>Continue anyway (manual override, logged)</button></div>`;
  } else if (q && q.status === "stopped" && q.stop_reason === "insufficient_data" && !run.allowOverride) {
    h += `<p class="hint">Manual override was switched off for this run.</p>`;
  }
  const s = stageOf(run, "send");
  if (s && s.status === "ok" && s.result && s.result.mode === "dry_run" && draftOf(run)) {
    const o = owner || "the owner";
    h += `<div class="action-box"><p><b>Draft ready as a dry run.</b> Nothing has been sent.</p>
      <label class="check"><input type="checkbox" data-act="confirm" data-id="${run.id}" data-fid="cf${run.id}"${run.confirmed ? " checked" : ""}> <span>I understand this sends a real email, to the owner's address only (${esc(o)}).</span></label>
      <div class="row"><button class="btn btn-cta btn-sm" type="button" data-act="send" data-id="${run.id}" data-fid="sd${run.id}"${run.confirmed && !busy ? "" : " disabled"}>${ico("send")}Send the email to ${esc(o)}</button>
      <button class="btn btn-ghost btn-sm" type="button" data-act="copy" data-id="${run.id}">${ico("copy")}Copy email</button></div></div>`;
  } else if (draftOf(run)) {
    h += `<div class="row" style="margin-top:12px"><button class="btn btn-ghost btn-sm" type="button" data-act="copy" data-id="${run.id}">${ico("copy")}Copy email</button></div>`;
  }
  return h;
}
function runHtml(run) {
  const o = outcomeOf(run), m = OUTCOMES[o];
  const running = run.status === "running";
  const steps = STEPS.map((s, i) => {
    const st = stepState(run, s);
    const ms = run.timings && run.timings[s.api];
    return `<li class="stp" data-s="${st}"><svg class="ic ${st === "running" ? "spin" : ""}" aria-hidden="true"><use href="#i-${st === "done" ? "check" : STEP_ICON[st]}"/></svg><span>${i + 1}. ${esc(s.name)}<span class="sr">: ${st}</span></span><span class="ms">${st === "running" ? "working" : (st === "done" || st === "stopped" || st === "failed") && ms ? fmtMs(ms) : ""}</span></li>`;
  }).join("");
  const total = Object.values(run.timings || {}).reduce((a, b) => a + b, 0);
  const skeleton = running ? `<div class="skeleton sk-line" aria-hidden="true"></div><div class="skeleton sk-line" style="width:70%" aria-hidden="true"></div>` : "";
  return `<article class="run" id="run-${run.id}" aria-busy="${running}" aria-labelledby="rt-${run.id}">
    <div class="run-head"><h3 id="rt-${run.id}">${esc(run.domain)}</h3><div class="row"><span class="badge ${m.cls}">${ico(m.icon, o === "running" ? "spin" : "")}${m.label}</span>${total ? `<small>${fmtMs(total)} total</small>` : ""}</div></div>
    <ol class="stepper" aria-label="Pipeline steps for ${esc(run.domain)}">${steps}</ol>
    <p class="hint" role="status">${esc(statusText(run))}</p>${skeleton}
    ${stageDetails(run)}${actionBoxes(run)}</article>`;
}
function renderRun(run) {
  const el = $("run-" + run.id);
  if (!el) { renderAll(); return; }
  const fid = document.activeElement && document.activeElement.dataset && document.activeElement.dataset.fid;
  el.outerHTML = runHtml(run);
  if (fid) { const n = document.querySelector(`[data-fid="${fid}"]`); if (n && !n.disabled) n.focus(); }
}

/* ---------- summary, counts, decision log ---------- */
function renderSummary() {
  const rows = runs.map((r) => ({ run: r, domain: r.domain, outcome: OUTCOMES[outcomeOf(r)].label, key: outcomeOf(r), score: (scoreOf(r) || { min: -1 }).min, contact: contactOf(r), subject: (draftOf(r) || { draft: { subject: "" } }).draft.subject, status: statusText(r) }));
  const tally = {};
  rows.forEach((x) => { tally[x.key] = (tally[x.key] || 0) + 1; });
  $("counts").innerHTML = Object.keys(OUTCOMES).filter((k) => tally[k]).map((k) => `<div class="count"><span class="badge ${OUTCOMES[k].cls}">${ico(OUTCOMES[k].icon)}</span><b>${tally[k]}</b><span>${OUTCOMES[k].label}</span></div>`).join("");
  $("sumEmpty").hidden = rows.length > 0; $("sumWrap").hidden = rows.length === 0;
  if (sort.k) rows.sort((a, b) => (a[sort.k] > b[sort.k] ? 1 : a[sort.k] < b[sort.k] ? -1 : 0) * sort.dir);
  $("sumBody").innerHTML = rows.map((x) => {
    const m = OUTCOMES[x.key], sc = scoreOf(x.run);
    return `<tr><th scope="row"><a href="#run-${x.run.id}">${esc(x.domain)}</a></th><td><span class="badge ${m.cls}">${ico(m.icon)}${m.label}</span></td><td class="num">${sc ? `${sc.min} to ${sc.max}` : "n/a"}</td><td>${esc(x.contact || "n/a")}</td><td>${esc(x.subject || "n/a")}</td><td>${esc(x.status)}</td></tr>`;
  }).join("");
  document.querySelectorAll("#sumTable thead th").forEach((th) => {
    const k = th.querySelector(".sort").dataset.k;
    th.setAttribute("aria-sort", sort.k === k ? (sort.dir === 1 ? "ascending" : "descending") : "none");
  });
}
document.querySelectorAll(".sort").forEach((b) => b.addEventListener("click", () => {
  sort = sort.k === b.dataset.k ? { k: sort.k, dir: -sort.dir } : { k: b.dataset.k, dir: 1 };
  renderSummary();
}));

function companyLog(run) {
  const q = stageOf(run, "qualify");
  if (!q || !q.result) return `<p class="hint">${esc(q ? [q.stop_reason, q.detail].filter(Boolean).join(": ") : "Not reached.")}</p>`;
  return qualifyDetail(q);
}
function personLog(run) {
  const p = stageOf(run, "poc");
  if (!p || !p.result) return `<p class="hint">${esc(p ? [p.stop_reason, p.detail].filter(Boolean).join(": ") : "Not reached: the company did not get past qualification.")}</p>`;
  return pocDetail(p);
}
function emailLog(run) {
  const dr = stageOf(run, "draft");
  const d = dr && dr.result;
  if (!d || !d.draft) return `<p class="hint">${esc(dr ? [dr.stop_reason, dr.detail].filter(Boolean).join(": ") : "Not reached.")}</p>`;
  const hooks = d.hook_map || [];
  let h = `<p class="hint">Subject</p><p><b>${esc(d.draft.subject)}</b></p><div class="mail">${esc(d.draft.body)}</div>`;
  h += `<h4>Hook-to-evidence map</h4>` + (hooks.length ? tableWrap(`<table class="data"><caption class="sr">Each claim in the email and its evidence</caption><thead><tr><th scope="col">Claim in the email</th><th scope="col">Evidence id</th><th scope="col">Quote and source</th></tr></thead><tbody>${hooks.map((x) => `<tr><td>${esc(x.claim)}</td><td>${esc(x.evidence_id)}</td><td>${quote(x.quote, x.source_url) || "<small>whitelisted Sprinto claim</small>"}</td></tr>`).join("")}</tbody></table>`) : "<p class='hint'>No hook map recorded.</p>");
  if ((d.claims_used || []).length) h += `<p class="hint">Claims used: ${d.claims_used.map((c) => esc(c.claim) + " [" + esc(c.evidence_id) + "]").join("; ")}</p>`;
  h += painDetail(dr);
  h += `<h4>Validator result</h4><ul class="checks">${validatorChecks(d).map(([t, ok]) => `<li>${ico(ok ? "check" : "x")}<span>${esc(t)}</span> <span class="badge ${ok ? "b-ok" : "b-bad"}">${ok ? "pass" : "fail"}</span></li>`).join("")}</ul>`;
  return h;
}
function renderLog() {
  const have = runs.filter((r) => Object.keys(r.results || {}).length);
  $("logEmpty").hidden = have.length > 0; $("dlBtn").disabled = have.length === 0;
  $("logBody").innerHTML = have.map((run) => {
    const m = OUTCOMES[outcomeOf(run)];
    const ov = (stageOf(run, "qualify") || {}).result && stageOf(run, "qualify").result.override;
    return `<article class="dpanel" id="log-${run.id}"><div class="run-head"><h3>${esc(run.domain)}</h3><span class="badge ${m.cls}">${ico(m.icon)}${m.label}</span></div>
      ${ov ? `<div class="override-banner">${ico("alert")}<span>Qualified by manual override, not by the rubric.</span></div>` : ""}
      <div class="dsec" style="border-top:0;margin-top:0;padding-top:0"><h4>${ico("target")}Why this company</h4>${companyLog(run)}</div>
      <div class="dsec"><h4>${ico("user-search")}Why this person</h4>${personLog(run)}</div>
      <div class="dsec"><h4>${ico("pen")}Why this email</h4>${emailLog(run)}</div></article>`;
  }).join("");
}
function renderAll() {
  $("runs").innerHTML = runs.map(runHtml).join("");
  $("emptyRuns").hidden = runs.length > 0;
  renderSummary(); renderLog();
}

/* ---------- markdown export, copy ---------- */
function mdQuote(q, u) { return q ? `\n    > "${q}" (${u})` : ""; }
function buildMarkdown() {
  const out = [`# Sprinto outreach decision log`, ``, `Generated ${new Date().toISOString()}. Rubric ${rubric ? rubric.version + " sha256 " + rubric.sha256 : "unavailable"}.`, ""];
  for (const run of runs) {
    out.push(`## ${run.domain}`, ``, `Outcome: **${OUTCOMES[outcomeOf(run)].label}**. ${statusText(run)}`, "");
    const q = stageOf(run, "qualify"), qr = q && q.result;
    out.push(`### Why this company`);
    if (qr) {
      if (qr.override) out.push(``, `> **MANUAL OVERRIDE: qualified by manual override, not by the rubric.** ${qr.override_note || ""}`);
      const sc = qr.score || {};
      out.push(``, `Rubric verdict: ${qr.verdict}. ${qr.reason || ""}`, `Score interval: ${sc.score_min} to ${sc.score_max} (qualify at ${(qr.thresholds || {}).qualify_min}, reject below ${(qr.thresholds || {}).reject_max}).`, "");
      (sc.signals || []).forEach((s) => out.push(`- ${s.label || s.id} (weight ${s.weight}, ${s.status}, ${s.status === "known" ? "+" + s.points_min : "0.." + s.weight}): ${s.basis}${(s.evidence || []).map((e) => mdQuote(e.quote, e.source_url)).join("")}`));
      (sc.gates || []).forEach((g) => out.push(`- gate ${g.label || g.id}: ${g.status}. ${g.basis}`));
      (sc.penalties || []).forEach((p) => out.push(`- penalty ${p.label || p.id}: -${p.points}`));
      const ag = qr.research;
      if (ag && ag.stop_reason !== "not_needed") { out.push("", `Research loop stop reason: ${ag.stop_reason}`); (ag.steps || []).forEach((s) => out.push(`- step ${s.iteration}: ${s.url || s.tool} because ${s.reason || "n/a"} -> ${s.outcome}`)); }
    } else out.push("", q ? `${q.stop_reason || q.status}: ${q.detail || ""}` : "Not reached.");
    out.push("", `### Why this person`);
    const p = stageOf(run, "poc"), pr = p && p.result;
    if (pr) {
      const c = pr.contact;
      out.push("", `Chosen: ${[c.first_name, c.last_name].filter(Boolean).join(" ")}, ${c.position} (${c.email}, ${c.source}).`, `Reason: ${pr.reason}`, `Band: ${pr.band} (${pr.band_basis})`, "");
      (pr.top_candidates || []).slice(0, 3).forEach((x, i) => out.push(`${i + 1}. ${[x.first_name, x.last_name].filter(Boolean).join(" ")}, ${x.position}, score ${x.score}. ${(x.notes || []).join("; ")}`));
    } else out.push("", p ? `${p.stop_reason || p.status}: ${p.detail || ""}` : "Not reached.");
    out.push("", `### Why this email`);
    const dr = stageOf(run, "draft"), d = dr && dr.result;
    if (d && d.draft) {
      out.push("", `Subject: ${d.draft.subject}`, "", "```", d.draft.body, "```", "", "Pain points:");
      (d.pain_points || []).forEach((x) => out.push(`- ${x.pain} (role link: ${x.role_link}; evidence ${x.evidence_id})`));
      out.push("", "Hook-to-evidence map:");
      (d.hook_map || []).forEach((x) => out.push(`- ${x.claim} [${x.evidence_id}]${mdQuote(x.quote, x.source_url)}`));
      out.push("", "Validator:"); validatorChecks(d).forEach(([t, ok]) => out.push(`- ${ok ? "PASS" : "FAIL"}: ${t}`));
      const s = stageOf(run, "send");
      if (s && s.result) out.push("", `Send: ${s.result.mode === "sent" ? "SENT to owner" : "dry run only, not sent"}.`);
    } else out.push("", dr ? `${dr.stop_reason || dr.status}: ${dr.detail || ""}` : "Not reached.");
    out.push("");
  }
  return out.join("\n");
}
$("dlBtn").addEventListener("click", () => {
  const blob = new Blob([buildMarkdown()], { type: "text/markdown;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "decision-log.md";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});
async function copyEmail(id) {
  const run = runs.find((r) => r.id === id), d = run && draftOf(run);
  if (!d) return;
  const text = `Subject: ${d.draft.subject}\n\n${d.draft.body}`;
  try { await navigator.clipboard.writeText(text); toast("Email copied to the clipboard."); }
  catch (e) {
    const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); toast("Email copied to the clipboard."); } catch (e2) { toast("Copy failed. Select the text and copy it manually.", "err"); }
    ta.remove();
  }
}

/* ---------- delegated events ---------- */
$("runs").addEventListener("click", (e) => {
  const b = e.target.closest("[data-act]"); if (!b) return;
  const id = +b.dataset.id;
  if (b.dataset.act === "override") overrideRun(id);
  else if (b.dataset.act === "send") sendRun(id);
  else if (b.dataset.act === "copy") copyEmail(id);
});
$("runs").addEventListener("change", (e) => {
  const c = e.target.closest('[data-act="confirm"]'); if (!c) return;
  const run = runs.find((r) => r.id === +c.dataset.id); if (!run) return;
  run.confirmed = c.checked; renderRun(run);
});
$("runs").addEventListener("toggle", (e) => {
  const d = e.target; if (!d.matches || !d.matches("details.stage")) return;
  const art = d.closest(".run"); const run = art && runs.find((r) => "run-" + r.id === art.id);
  if (run) { run.open = run.open || {}; run.open[d.dataset.key] = d.open; }
}, true);

/* ---------- auth + init ---------- */
function showForm() { $("loginBox").hidden = true; $("runForm").hidden = false; showRunsLeft(); }
async function unlock() {
  $("loginErr").textContent = "";
  const pw = $("pw").value;
  if (!pw) { $("loginErr").textContent = "Enter the password."; return; }
  store.set("pw", pw);
  const { status, data } = await api("/api/run", { stage: "bogus", domain: "example.com" }); // 400 means the password was accepted
  if (status === 401) { store.del("pw"); $("loginErr").textContent = "Wrong password."; return; }
  if (status === 429) { $("loginErr").textContent = data.message || "Too many requests."; return; }
  $("pw").value = ""; $("lockBtn").hidden = false; showForm();
}
$("loginBtn").addEventListener("click", unlock);
$("pw").addEventListener("keydown", (e) => { if (e.key === "Enter") unlock(); });
$("lockBtn").addEventListener("click", () => { store.del("pw"); store.del("runs.v1"); location.reload(); });

async function init() {
  renderStatic(); applyThemeUi(); restore(); renderAll(); refreshChips(); updateIvDemo();
  loadRubric();
  const { status, data } = await api("/api/health");
  if (status !== 200) { toast(data.message || "Could not reach the server.", "err"); showForm(); return; }
  if (!data.configured) { $("notConfigured").hidden = false; $("runForm").hidden = true; return; }
  if (data.auth_required) {
    if (store.get("pw")) { $("lockBtn").hidden = false; showForm(); } else { $("runForm").hidden = true; $("loginBox").hidden = false; }
  } else showForm();
}
init();
