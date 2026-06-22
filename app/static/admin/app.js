/*
 * Admin Mini App (spec sections 25-34). Mobile-first, tabbed, large buttons.
 * Each page calls the /api/admin/* endpoints. Auth via Telegram initData header.
 */
const PAGES = [
  ["today", "Today"], ["schedule", "Schedule"], ["staff", "Staff"],
  ["checklists", "Checklists"], ["timing", "Timing"], ["evidence", "Evidence"],
  ["recoveries", "Recoveries"], ["reviews", "OIC Reviews"],
  ["announcements", "Announce"], ["reports", "Reports"],
  ["settings", "Settings"], ["test", "Test"],
];

document.addEventListener("DOMContentLoaded", () => {
  tgInit();
  renderTabs();
  go(qs("page") || "today");
});

function renderTabs() {
  document.getElementById("tabbar").innerHTML = PAGES.map(
    ([id, label]) => `<button data-tab="${id}">${label}</button>`).join("");
  document.querySelectorAll("[data-tab]").forEach(b =>
    b.onclick = () => go(b.getAttribute("data-tab")));
}

function setActive(page) {
  document.querySelectorAll("[data-tab]").forEach(b =>
    b.classList.toggle("active", b.getAttribute("data-tab") === page));
}

async function go(page) {
  setActive(page);
  const app = document.getElementById("app");
  app.innerHTML = `<div class="spinner">Loading…</div>`;
  try { await PAGE_FN[page](app); }
  catch (e) { showError(e.message); app.innerHTML = ""; }
}

const today = () => qs("date") || new Date().toISOString().slice(0, 10);

const PAGE_FN = {
  /* -------------------------------------------------------------- TODAY */
  async today(app) {
    const d = await api(`/api/admin/today?date=${today()}`);
    let h = `<h1>Today — ${esc(d.date)}</h1>
      <p class="sub">Status: ${esc(d.day_status || "—")} • Opener: ${esc(d.opener||"—")} • Closer: ${esc(d.closer||"—")}</p>`;
    d.tasks.forEach(t => {
      h += `<div class="card"><div class="row"><strong>${esc(t.checklist_type)}</strong>
        ${statusPill(t.status)}</div>
        <div class="muted">${esc(t.assigned||"—")} • ${esc(t.result||"")} ${esc(t.evidence||"")}</div>
        ${t.missing && t.missing.length ? `<div class="muted">Missing: ${t.missing.map(esc).join(", ")}</div>` : ""}
        <div class="muted">Resolution: ${esc(t.resolution||"")}</div></div>`;
    });
    h += `<button class="secondary" onclick="sendEvidence('${esc(d.date)}')">📤 Send All Evidence Here</button>
      <button class="ghost" onclick="markClosed('${esc(d.date)}')">Mark This Day Closed</button>`;
    app.innerHTML = h;
  },

  /* ----------------------------------------------------------- SCHEDULE */
  async schedule(app) {
    const data = await api(`/api/admin/schedule`);
    const staff = (await api(`/api/admin/staff`)).staff.filter(s => isTrue(s.Active));
    const opts = (sel) => staff.map(s =>
      `<option value="${esc(s["Staff ID"])}" ${sel===s["Staff ID"]?"selected":""}>${esc(s["Staff Name"])}</option>`).join("");
    let h = `<h1>Schedule</h1>`;
    data.rows.forEach(r => {
      h += `<div class="card"><strong>${esc(r.Date)} (${esc(r.Day||"")})</strong>
        <label>Status</label>
        <select id="st_${r.Date}"><option ${r.Status==="OPEN"?"selected":""}>OPEN</option>
          <option ${r.Status==="CLOSED"?"selected":""}>CLOSED</option></select>
        <label>Opener</label><select id="op_${r.Date}"><option value="">—</option>${opts(r["Opener Staff ID"])}</select>
        <label>Closer</label><select id="cl_${r.Date}"><option value="">—</option>${opts(r["Closer Staff ID"])}</select>
        <button class="ghost" onclick="saveSched('${r.Date}')">Save ${esc(r.Date)}</button></div>`;
    });
    h += `<button class="secondary" onclick="copyWeek()">Copy This Week → Next Week</button>`;
    app.innerHTML = h;
  },

  /* -------------------------------------------------------------- STAFF */
  async staff(app) {
    const d = await api(`/api/admin/staff`);
    let h = `<h1>Staff</h1>`;
    if (d.duplicates.length) h += `<div id="error" style="display:block">Duplicate active Telegram IDs: ${d.duplicates.join(", ")}</div>`;
    d.staff.forEach(s => {
      h += `<div class="card"><div class="row"><strong>${esc(s["Staff Name"])}</strong>
        <span class="pill ${isTrue(s.Active)?"ok":"warn"}">${isTrue(s.Active)?"Active":"Inactive"}</span></div>
        <div class="muted">${esc(s.Role)} • TG ${esc(s["Telegram User ID"])} • Bot started: ${isTrue(s["Private Bot Started"])?"yes":"no"}</div>
        <button class="ghost" onclick="assignOIC('${esc(s["Staff ID"])}')">Make Store OIC</button>
        ${isTrue(s.Active)?`<button class="ghost" onclick="deactivate('${esc(s["Staff ID"])}')">Set Inactive</button>`:""}</div>`;
    });
    h += `<div class="card"><h2>Add staff</h2>
      <label>Name</label><input id="ns_name"/>
      <label>Telegram User ID</label><input id="ns_tg" inputmode="numeric"/>
      <label>Role</label><select id="ns_role"><option>Staff</option><option>Store OIC</option></select>
      <button onclick="addStaff()">Add</button></div>`;
    app.innerHTML = h;
  },

  /* --------------------------------------------------------- CHECKLISTS */
  async checklists(app) {
    const types = ["Opening Check", "Opener Handover", "Closing Check"];
    let h = `<h1>Checklists</h1>`;
    for (const t of types) {
      const d = await api(`/api/admin/checklists?type=${encodeURIComponent(t)}`);
      h += `<h2>${esc(t)}</h2>`;
      d.items.forEach(it => {
        h += `<div class="card"><div class="row"><strong>${esc(it["Item Name"])}</strong>
          <span class="pill ${isTrue(it.Active)?"ok":"warn"}">${esc(it["Item Type"])}</span></div>
          <div class="muted">${isTrue(it.Required)?"Required":"Optional"} ${it["Days of Week"]?("• "+esc(it["Days of Week"])):""}</div>
          ${isTrue(it.Active)?`<button class="ghost" onclick="archiveItem('${esc(it["Item ID"])}')">Archive</button>`:""}</div>`;
      });
      h += `<button class="ghost" onclick="addItem('${esc(t)}')">+ Add item to ${esc(t)}</button>`;
    }
    app.innerHTML = h;
  },

  /* ------------------------------------------------------------ TIMING */
  async timing(app) {
    const d = await api(`/api/admin/timing`);
    let h = `<h1>Timing (Asia/Manila)</h1>`;
    d.timing.forEach(r => {
      h += `<div class="card"><strong>${esc(r["Checklist Type"])} (${esc(r["Day Type"])})</strong>
        <label>Release</label><input id="rl_${r["Checklist Type"]}_${r["Day Type"]}" value="${esc(r["Release Time"])}"/>
        <label>Staff reminders (comma)</label><input id="rm_${r["Checklist Type"]}_${r["Day Type"]}" value="${esc(r["Staff Reminder Times"])}"/>
        <label>OIC escalation</label><input id="es_${r["Checklist Type"]}_${r["Day Type"]}" value="${esc(r["OIC Escalation Time"])}"/>
        <label>Cutoff</label><input id="co_${r["Checklist Type"]}_${r["Day Type"]}" value="${esc(r["Cutoff Time"])}"/>
        <button class="ghost" onclick="saveTiming('${esc(r["Checklist Type"])}','${esc(r["Day Type"])}')">Save</button></div>`;
    });
    app.innerHTML = h;
  },

  /* ---------------------------------------------------------- EVIDENCE */
  async evidence(app) {
    const d = await api(`/api/admin/evidence?date=${today()}`);
    let h = `<h1>Evidence — ${esc(d.date)}</h1>
      <button class="secondary" onclick="sendEvidence('${esc(d.date)}')">📤 Send All Here</button>`;
    if (!d.evidence.length) h += `<p class="muted">No evidence yet.</p>`;
    d.evidence.forEach(e => {
      h += `<div class="card">
        <img class="preview" src="${evidenceUrl(e.image_url)}" loading="lazy"/>
        <div class="muted">${esc(e.checklist_type)} • ${esc(e.uploader)} (${esc(e.uploader_role)})
          ${e.is_recovery?"• OIC Recovery":""}</div>
        <div class="muted">${esc(e.capture_source)} • ${esc(e.metadata_result)}
          ${e.possible_duplicate?'<span class="pill bad">duplicate?</span>':""}
          ${e.review_status?('<span class="pill warn">'+esc(e.review_status)+'</span>'):""}</div></div>`;
    });
    app.innerHTML = h;
  },

  /* -------------------------------------------------------- RECOVERIES */
  async recoveries(app) {
    const d = await api(`/api/admin/recoveries?date=${today()}`);
    let h = `<h1>Recoveries — ${esc(today())}</h1>`;
    if (!d.recoveries.length) h += `<p class="muted">No recoveries.</p>`;
    d.recoveries.forEach(r => {
      h += `<div class="card"><strong>${esc(r["Original Assigned Staff Name"])}</strong>
        <div class="muted">Recovered by ${esc(r["OIC Name"])} • ${esc(r["Recovery Submitted At"])}</div>
        <div class="muted">Reason: ${esc(r["Recovery Reason"])}</div></div>`;
    });
    app.innerHTML = h;
  },

  /* ------------------------------------------------------------ REVIEWS */
  async reviews(app) {
    const d = await api(`/api/admin/reviews`);
    let h = `<h1>OIC Reviews</h1>`;
    if (!d.reviews.length) h += `<p class="muted">Nothing pending. 🎉</p>`;
    d.reviews.forEach(r => {
      h += `<div class="card"><strong>${esc(r["Review Reason"])}</strong>
        <div class="muted">Task ${esc(r["Task ID"])} • ${esc(r["Requested At"])}</div></div>`;
    });
    app.innerHTML = h;
  },

  /* ------------------------------------------------------ ANNOUNCEMENTS */
  async announcements(app) {
    app.innerHTML = `<h1>Announcements</h1>
      <div class="card"><label>Message</label><textarea id="annMsg"></textarea>
      <button onclick="sendAnnounce()">Post to Staff Group</button></div>`;
  },

  /* ------------------------------------------------------------ REPORTS */
  async reports(app) {
    const d = await api(`/api/admin/report`);
    app.innerHTML = `<h1>Weekly Report</h1>
      <div class="card" style="white-space:pre-wrap">${d.text.replace(/<[^>]+>/g,"")}</div>`;
  },

  /* ----------------------------------------------------------- SETTINGS */
  async settings(app) {
    const d = await api(`/api/admin/settings`);
    let h = `<h1>Settings</h1><div class="card">`;
    Object.entries(d.settings).forEach(([k, v]) => {
      h += `<label>${esc(k)}</label><input id="set_${k}" value="${esc(v)}"/>`;
    });
    h += `<button onclick="saveSettings(${JSON.stringify(Object.keys(d.settings))})">Save Settings</button></div>`;
    app.innerHTML = h;
  },

  /* --------------------------------------------------------------- TEST */
  async test(app) {
    app.innerHTML = `<h1>Test Mode</h1>
      <button class="secondary" onclick="runTest('release')">Release Today's Tasks</button>
      <button class="secondary" onclick="runTest('summary')">Send Today's Summary</button>
      <button class="secondary" onclick="runTest('weekly')">Send Weekly Report</button>`;
  },
};

/* --------------------------------------------------------------- actions */
async function saveSched(date) {
  await api(`/api/admin/schedule`, { method: "POST", body: {
    date, status: val(`st_${date}`),
    opener_staff_id: val(`op_${date}`), closer_staff_id: val(`cl_${date}`) } });
  toast("Saved " + date);
}
async function copyWeek() {
  const s = new Date(); const src = s.toISOString().slice(0,10);
  s.setDate(s.getDate()+7); const tgt = s.toISOString().slice(0,10);
  const r = await api(`/api/admin/copyweek`, { method: "POST", body: { source_start: src, target_start: tgt } });
  toast(`Copied ${r.copied.length}, skipped ${r.skipped.length}`);
}
async function markClosed(date) {
  await api(`/api/admin/schedule`, { method: "POST", body: { date, status: "CLOSED" } });
  toast("Marked closed"); go("today");
}
async function addStaff() {
  await api(`/api/admin/staff`, { method: "POST", body: { action: "add",
    name: val("ns_name"), telegram_user_id: val("ns_tg"), role: val("ns_role") } });
  go("staff");
}
async function deactivate(id) { await api(`/api/admin/staff`, { method:"POST", body:{action:"deactivate", staff_id:id}}); go("staff"); }
async function assignOIC(id) { await api(`/api/admin/staff`, { method:"POST", body:{action:"assign_oic", staff_id:id}}); toast("OIC assigned"); go("staff"); }
async function archiveItem(id) { await api(`/api/admin/checklists`, { method:"POST", body:{action:"archive", item_id:id}}); go("checklists"); }
async function addItem(type) {
  const name = prompt("Item name?"); if (!name) return;
  const item_type = prompt("Type: Attestation / Live Camera Photo / Gallery Screenshot / Number Entry / Short Text Entry", "Attestation");
  await api(`/api/admin/checklists`, { method:"POST", body:{ action:"add", checklist_type:type, item_name:name, item_type, required:true }});
  go("checklists");
}
async function saveTiming(ct, dt) {
  await api(`/api/admin/timing`, { method:"POST", body:{
    checklist_type: ct, day_type: dt,
    release: val(`rl_${ct}_${dt}`), reminders: val(`rm_${ct}_${dt}`),
    escalation: val(`es_${ct}_${dt}`), cutoff: val(`co_${ct}_${dt}`) }});
  toast("Timing saved");
}
async function sendEvidence(date) { const r = await api(`/api/admin/send-evidence`, { method:"POST", body:{date}}); toast(`Sent ${r.sent} file(s) to your chat.`); }
async function sendAnnounce() { await api(`/api/admin/announce`, { method:"POST", body:{message: val("annMsg")}}); toast("Posted."); }
async function saveSettings(keys) {
  const settings = {}; keys.forEach(k => settings[k] = val(`set_${k}`));
  await api(`/api/admin/settings`, { method:"POST", body:{settings}}); toast("Saved.");
}
async function runTest(what) { await api(`/api/admin/test/${what}`, { method:"POST" }); toast("Done — check your chat."); }

/* ---------------------------------------------------------------- utils */
function val(id) { const e = document.getElementById(id); return e ? e.value.trim() : ""; }
function isTrue(v) { return String(v).toLowerCase() === "true" || v === true; }
function statusPill(s) {
  const map = { "Submitted On Time":"ok", "All Complete":"ok", "Pending":"warn",
    "Submitted Late":"warn", "Not Submitted":"bad", "Closed Day":"warn" };
  return `<span class="pill ${map[s]||"warn"}">${esc(s||"—")}</span>`;
}
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g,
    c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
}
