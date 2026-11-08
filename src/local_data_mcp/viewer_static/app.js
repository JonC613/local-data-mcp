"use strict";

const $ = (id) => document.getElementById(id);
const tokenFromUrl = location.hash.slice(1);
if (tokenFromUrl) {
  sessionStorage.setItem("local-viewer-token", tokenFromUrl);
  history.replaceState(null, "", location.pathname);
}
const token = sessionStorage.getItem("local-viewer-token") || "";
const state = { source: null, table: null, tableOffset: 0, tableMore: false,
  auditOffset: 0, auditMore: false, auditSnapshot: null, auditFilters: {} };
const pageSize = 50;

function notice(message) { $("notice").textContent = message || ""; $("notice").hidden = !message; }
async function api(path, params = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") query.set(key, String(value));
  }
  const response = await fetch(path + (query.size ? `?${query}` : ""), {
    headers: { "X-Viewer-Token": token }, cache: "no-store"
  });
  let payload;
  try { payload = await response.json(); }
  catch { throw new Error("Unable to access the viewer. Open the full session link printed in the terminal."); }
  if (!response.ok || !payload.ok) throw new Error(payload.error?.message || "The request failed.");
  return payload.data;
}
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function showDetail(title, value, warning = "") {
  $("detail-title").textContent = title;
  $("detail-warning").textContent = warning;
  $("detail-warning").hidden = !warning;
  $("detail-content").textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  $("detail-dialog").showModal();
}
function formatCell(value) {
  if (value === null) return "NULL";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleString();
}
function activeView(source) {
  state.source = source;
  for (const button of document.querySelectorAll(".nav-item")) {
    button.classList.toggle("active", button.dataset.source === source);
    button.setAttribute("aria-current", button.dataset.source === source ? "page" : "false");
  }
  $("welcome").hidden = !!source;
  $("database").hidden = !source || source === "audit";
  $("audit").hidden = source !== "audit";
  $("refresh").hidden = !source;
  const labels = {mock: ["MOCK DATABASE", "Mock database", "Browse the sample customers, products, and orders."],
    phish: ["PHISH DATABASE", "Phish database", "Explore your local catalog of shows, songs, and import history."],
    audit: ["AUDIT LOG", "Audit log", "Follow what was requested and what the tools returned."]};
  if (source) {
    $("breadcrumb").textContent = labels[source][0];
    $("eyebrow").textContent = "LOCAL SOURCE / " + labels[source][0];
    $("title").textContent = labels[source][1];
    $("subtitle").textContent = labels[source][2];
  }
  notice("");
}
async function openSource(source) {
  activeView(source);
  if (source === "audit") {
    state.auditOffset = 0; state.auditSnapshot = null;
    await loadAudit();
    return;
  }
  state.table = null; state.tableOffset = 0;
  $("filter-query").value = "";
  $("table-tabs").replaceChildren();
  $("table-head").replaceChildren(); $("table-body").replaceChildren();
  $("table-title").textContent = "Select a table";
  $("table-page-info").textContent = "";
  $("table-prev").disabled = true; $("table-next").disabled = true;
  try {
    const data = await api("/api/tables", {source});
    if (!data.tables.length) throw new Error("No approved tables are available in this database.");
    for (const name of data.tables) {
      const tab = element("button", name.replace(/^phish_/, "").replaceAll("_", " "), "tab");
      tab.dataset.table = name;
      tab.addEventListener("click", () => selectTable(name));
      $("table-tabs").append(tab);
    }
    await selectTable(data.tables[0]);
  } catch (error) { notice(error.message); }
}
async function selectTable(table) {
  state.table = table; state.tableOffset = 0;
  $("filter-query").value = "";
  $("filter-column").replaceChildren(new Option("Choose a column", ""));
  for (const tab of $("table-tabs").children) tab.classList.toggle("active", tab.dataset.table === table);
  await loadRows();
}
async function loadRows() {
  if (!state.table) return;
  notice("");
  try {
    const data = await api("/api/rows", {source: state.source, table: state.table, limit: pageSize,
      offset: state.tableOffset, column: $("filter-column").value, query: $("filter-query").value});
    state.tableMore = data.has_more;
    $("table-title").textContent = state.table.replace(/^phish_/, "").replaceAll("_", " ");
    $("table-description").textContent = "Ordered by " + data.order_by.join(", ") + ". Select a cell to inspect its value.";
    const selected = $("filter-column").value;
    $("filter-column").replaceChildren(new Option("Choose a column", ""), ...data.columns.map(c => new Option(c, c)));
    $("filter-column").value = selected;
    const head = element("tr");
    for (const name of data.columns) head.append(element("th", name));
    $("table-head").replaceChildren(head);
    $("table-body").replaceChildren();
    for (const record of data.rows) {
      const row = element("tr");
      for (const name of data.columns) {
        const cell = element("td");
        const button = element("button", formatCell(record[name]), "cell-button");
        button.type = "button";
        button.addEventListener("click", () => showDetail(name, record[name]));
        cell.append(button); row.append(cell);
      }
      $("table-body").append(row);
    }
    if (!data.rows.length) {
      const cell = element("td", "No records match this view.", "empty"); cell.colSpan = Math.max(data.columns.length, 1);
      const row = element("tr"); row.append(cell); $("table-body").append(row);
    }
    $("table-page-info").textContent = data.rows.length ? `Rows ${data.offset + 1}–${data.offset + data.rows.length}` : "No rows";
    $("table-prev").disabled = state.tableOffset === 0;
    $("table-next").disabled = !data.has_more;
  } catch (error) { notice(error.message); }
}
function getAuditFilters() {
  const start = $("audit-start").value, end = $("audit-end").value;
  return {tool: $("audit-tool").value.trim(), outcome: $("audit-outcome").value,
    request_id: $("audit-request").value.trim(), start: start ? new Date(start).toISOString() : "",
    end: end ? new Date(end).toISOString() : ""};
}
async function loadAudit() {
  notice("");
  try {
    const data = await api("/api/audit", {...state.auditFilters, limit: pageSize,
      offset: state.auditOffset, snapshot: state.auditSnapshot});
    state.auditSnapshot = data.snapshot; state.auditMore = data.has_more;
    $("audit-body").replaceChildren();
    for (const event of data.events) {
      const row = element("tr");
      for (const value of [formatTime(event.timestamp_utc), event.tool || "—", event.outcome || "—", event.request_id || "—"]) {
        row.append(element("td", value));
      }
      const cell = element("td"), button = element("button", "View →", "event-button");
      button.type = "button";
      button.addEventListener("click", async () => {
        try {
          const detail = await api("/api/audit/detail", {snapshot: state.auditSnapshot, position: event.position});
          const legacy = detail.event.schema_version === 1 ? "This is a version 1 audit event. Its recorded values may have been truncated by the earlier audit writer." : "";
          showDetail("Audit event", detail.event, legacy);
        } catch (error) { notice(error.message); }
      });
      cell.append(button); row.append(cell); $("audit-body").append(row);
    }
    if (!data.events.length) {
      const cell = element("td", "No audit events match these filters.", "empty"); cell.colSpan = 5;
      const row = element("tr"); row.append(cell); $("audit-body").append(row);
    }
    $("audit-page-info").textContent = data.events.length ? `Events ${data.offset + 1}–${data.offset + data.events.length} · snapshot at ${data.snapshot} bytes` : "No events in this snapshot";
    $("audit-prev").disabled = state.auditOffset === 0;
    $("audit-next").disabled = !data.has_more;
  } catch (error) { notice(error.message); }
}

for (const button of document.querySelectorAll(".nav-item")) button.addEventListener("click", () => openSource(button.dataset.source));
for (const button of document.querySelectorAll("[data-open]")) button.addEventListener("click", () => openSource(button.dataset.open));
$("table-filter").addEventListener("submit", event => { event.preventDefault(); state.tableOffset = 0; loadRows(); });
$("clear-filter").addEventListener("click", () => { $("filter-column").value = ""; $("filter-query").value = ""; state.tableOffset = 0; loadRows(); });
$("table-prev").addEventListener("click", () => { state.tableOffset = Math.max(0, state.tableOffset - pageSize); loadRows(); });
$("table-next").addEventListener("click", () => { if (state.tableMore) { state.tableOffset += pageSize; loadRows(); } });
$("audit-filter").addEventListener("submit", event => { event.preventDefault(); try { state.auditFilters = getAuditFilters(); state.auditOffset = 0; state.auditSnapshot = null; loadAudit(); } catch { notice("Enter valid dates and times."); } });
$("audit-clear").addEventListener("click", () => { $("audit-filter").reset(); state.auditFilters = {}; state.auditOffset = 0; state.auditSnapshot = null; loadAudit(); });
$("audit-prev").addEventListener("click", () => { state.auditOffset = Math.max(0, state.auditOffset - pageSize); loadAudit(); });
$("audit-next").addEventListener("click", () => { if (state.auditMore) { state.auditOffset += pageSize; loadAudit(); } });
$("refresh").addEventListener("click", () => { if (state.source === "audit") { state.auditSnapshot = null; state.auditOffset = 0; loadAudit(); } else { state.tableOffset = 0; loadRows(); } });
$("detail-close").addEventListener("click", () => $("detail-dialog").close());
api("/api/sources").catch(error => notice(error.message));
