/*
 * Admin Mini App (spec sections 25-34). Mobile-first, tabbed, large buttons.
 * Each page calls the /api/admin/* endpoints. Auth via Telegram initData header.
 */
const PAGES = [
  ["today", "Today"], ["schedule", "Schedule"], ["assignments", "Tasks"],
  ["staff", "Staff"], ["checklists", "Checklists"], ["timing", "Timing"],
  ["evidence", "Evidence"], ["recoveries", "Recoveries"], ["reviews", "OIC Reviews"],
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
        <button class="ghost" onclick="saveSched('${r.Date}')">💾 Save ${esc(r.Date)}</button>
        <button class="secondary" onclick="notifyAssignment('${r.Date}')">📢 Notify Group</button></div>`;
    });
    h += `<button class="secondary" onclick="copyWeek()">Copy This Week → Next Week</button>`;
    app.innerHTML = h;
  },

  /* -------------------------------------------------- ASSIGNMENTS (Tasks) */
  async assignments(app) {
    const data = await api(`/api/admin/assignments`);
    const staff = data.staff;
    const opts = staff.map(s =>
      `<option value="${esc(s["Staff ID"])}">${esc(s["Staff Name"])}</option>`).join("");
    const todayStr = new Date().toISOString().slice(0, 10);

    let h = `<h1>Staff Tasks</h1>
      <p class="sub">Assign ad-hoc tasks (not part of opening/closing). The card posts
        to the group 15 min before it's due; staff complete it with a photo, then
        get reminders every 2 hours until done.</p>
      <div class="card"><h2>➕ Assign a task</h2>
        <label>Staff</label><select id="a_staff">${opts}</select>
        <label>Task</label><input id="a_title" placeholder="e.g. Restock the Biscoff display"/>
        <label>Due date</label><input id="a_date" type="date" value="${todayStr}"/>
        <label>Due time (optional)</label><input id="a_time" type="time"/>
        <label>Repeat</label>
        <select id="a_rec">
          <option value="">Does not repeat</option>
          <option value="days:1">Every day</option>
          <option value="weekly">Every week (same weekday)</option>
          <option value="days:3">Every 3 days</option>
          <option value="days:7">Every 7 days</option>
        </select>
        <button onclick="assignTask()">➕ Assign Task</button></div>`;

    const open = data.assignments.filter(a => a.Status === "Open");
    const done = data.assignments.filter(a => a.Status === "Done");
    h += `<h2>Open (${open.length})</h2>`;
    if (!open.length) h += `<p class="muted">No open tasks.</p>`;
    open.forEach(a => {
      const due = a["Due Date"] ? `${esc(a["Due Date"])}${a["Due Time"] ? " " + esc(a["Due Time"]) : ""}` : "no date";
      const rep = a["Recurrence Rule"] ? ` · 🔁 ${esc(a["Recurrence Rule"])}` : "";
      h += `<div class="card"><div class="row"><strong>${esc(a.Title)}</strong>
        <span class="pill">Open</span></div>
        <div class="muted">👤 ${esc(a["Assigned Staff Name"])} · 📅 ${due}${rep}</div>
        <button class="ghost" onclick="cancelAssignment('${esc(a["Assignment ID"])}')">🗑 Cancel</button></div>`;
    });
    if (done.length) {
      h += `<h2>Recently done (${done.length})</h2>`;
      done.slice(0, 10).forEach(a => {
        h += `<div class="card"><div class="row"><strong>${esc(a.Title)}</strong>
          <span class="pill ok">Done ✅</span></div>
          <div class="muted">👤 ${esc(a["Assigned Staff Name"])}</div></div>`;
      });
    }
    app.innerHTML = h;
  },

  /* -------------------------------------------------------------- STAFF */
  async staff(app) {
    const d = await api(`/api/admin/staff`);
    let h = `<h1>Staff</h1>`;
    if (d.duplicates.length) h += `<div id="error" style="display:block">Duplicate active Telegram IDs: ${d.duplicates.join(", ")}</div>`;
    d.staff.forEach(s => {
      const id = esc(s["Staff ID"]);
      h += `<div class="card"><div class="row"><strong>${esc(s["Staff Name"])}</strong>
        <span class="pill ${isTrue(s.Active)?"ok":"warn"}">${esc(s.Role)} · ${isTrue(s.Active)?"Active":"Inactive"}</span></div>
        <div class="muted">Bot started: ${isTrue(s["Private Bot Started"])?"yes ✅":"no ⚠️"}</div>
        <label>Name</label><input id="en_${id}" value="${esc(s["Staff Name"])}"/>
        <label>Telegram User ID</label><input id="et_${id}" inputmode="numeric" value="${esc(s["Telegram User ID"])}"/>
        <label>Username (for @tagging, optional)</label><input id="eu_${id}" value="${esc(s["Telegram Username"])}" placeholder="without the @"/>
        <button onclick="saveStaff('${id}')">💾 Save Changes</button>
        <button class="ghost" onclick="assignOIC('${id}')">Make Store OIC</button>
        ${isTrue(s.Active)?`<button class="ghost" onclick="deactivate('${id}')">Set Inactive</button>`
                          :`<button class="ghost" onclick="reactivate('${id}')">Set Active</button>`}</div>`;
    });
    h += `<div class="card"><h2>➕ Add staff</h2>
      <label>Name</label><input id="ns_name"/>
      <label>Telegram User ID (they get this from /start)</label><input id="ns_tg" inputmode="numeric"/>
      <label>Username (optional, without @)</label><input id="ns_user"/>
      <label>Role</label><select id="ns_role"><option>Staff</option><option>Store OIC</option></select>
      <button onclick="addStaff()">Add Staff</button>
      <p class="muted">Tip: ask each staff to message the bot <b>/start</b> — it replies with their Telegram ID to paste here.</p></div>`;
    app.innerHTML = h;
  },

  /* --------------------------------------------------------- CHECKLISTS */
  async checklists(app) {
    const types = ["Opening Check", "Opener Handover", "Closing Check"];
    let h = `<h1>Checklists</h1><p class="sub">Edit a name/type, reorder, or delete. Changes apply to <b>future</b> tasks only.</p>`;
    for (const t of types) {
      const d = await api(`/api/admin/checklists?type=${encodeURIComponent(t)}`);
      h += `<h2>${esc(t)}</h2>`;
      d.items.forEach(it => {
        const id = esc(it["Item ID"]);
        h += `<div class="card">
          <label>Item name</label><input id="in_${id}" value="${esc(it["Item Name"])}"/>
          <label>Type</label>${typeSelect("ity_"+id, it["Item Type"])}
          <label>Sort order</label><input id="iso_${id}" inputmode="numeric" value="${esc(it["Sort Order"])}"/>
          <label><input type="checkbox" id="ir_${id}" ${isTrue(it.Required)?"checked":""} style="width:auto"/> Required</label>
          <label><input type="checkbox" id="ia_${id}" ${isTrue(it.Active)?"checked":""} style="width:auto"/> Active</label>
          <button onclick="saveItem('${id}')">💾 Save</button>
          <button class="ghost" onclick="deleteItem('${id}','${esc(it["Item Name"])}')">🗑 Delete</button>
        </div>`;
      });
      h += `<div class="card"><h2>➕ Add to ${esc(t)}</h2>
        <label>Item name</label><input id="ni_${esc(t)}"/>
        <label>Type</label>${typeSelect("nt_"+esc(t), "Attestation")}
        <label><input type="checkbox" id="nr_${esc(t)}" checked style="width:auto"/> Required</label>
        <button onclick="addItem('${esc(t)}')">Add item</button></div>`;
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
async function notifyAssignment(date) {
  await api(`/api/admin/notify-assignment`, { method: "POST", body: { date } });
  toast("📢 Notified staff group");
}
async function assignTask() {
  const title = val("a_title");
  if (!title) { toast("Enter a task title."); return; }
  await api(`/api/admin/assignments`, { method: "POST", body: {
    action: "add", staff_id: val("a_staff"), title,
    due_date: val("a_date"), due_time: val("a_time"),
    recurrence_rule: val("a_rec") } });
  toast("✅ Task assigned — it'll post to the group 15 min before it's due");
  go("assignments");
}
async function cancelAssignment(id) {
  await api(`/api/admin/assignments`, { method: "POST", body: { action: "cancel", assignment_id: id } });
  toast("Cancelled");
  go("assignments");
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
    name: val("ns_name"), telegram_user_id: val("ns_tg"),
    username: val("ns_user"), role: val("ns_role") } });
  go("staff");
}
async function saveStaff(id) {
  await api(`/api/admin/staff`, { method:"POST", body:{ action:"update", staff_id:id, changes:{
    "Staff Name": val("en_"+id),
    "Telegram User ID": val("et_"+id),
    "Telegram Username": val("eu_"+id).replace(/^@/, "")
  }}});
  toast("Saved ✅"); go("staff");
}
async function reactivate(id) { await api(`/api/admin/staff`, { method:"POST", body:{action:"update", staff_id:id, changes:{"Active":"TRUE","Date Deactivated":""}}}); go("staff"); }
async function deactivate(id) { await api(`/api/admin/staff`, { method:"POST", body:{action:"deactivate", staff_id:id}}); go("staff"); }
async function assignOIC(id) { await api(`/api/admin/staff`, { method:"POST", body:{action:"assign_oic", staff_id:id}}); toast("OIC assigned"); go("staff"); }
const ITEM_TYPES = ["Attestation", "Live Camera Photo", "Gallery Screenshot", "Number Entry", "Short Text Entry"];
function typeSelect(id, current) {
  return `<select id="${id}">` + ITEM_TYPES.map(t =>
    `<option ${t===current?"selected":""}>${t}</option>`).join("") + `</select>`;
}
async function saveItem(id) {
  await api(`/api/admin/checklists`, { method:"POST", body:{ action:"update", item_id:id, changes:{
    "Item Name": val("in_"+id),
    "Item Type": val("ity_"+id),
    "Sort Order": val("iso_"+id) || "0",
    "Required": document.getElementById("ir_"+id).checked ? "TRUE" : "FALSE",
    "Active": document.getElementById("ia_"+id).checked ? "TRUE" : "FALSE",
  }}});
  toast("Saved ✅"); go("checklists");
}
async function deleteItem(id, name) {
  if (!confirm(`Delete "${name}"? It will be removed from future checklists. Past records keep their own copy.`)) return;
  await api(`/api/admin/checklists`, { method:"POST", body:{action:"delete", item_id:id}});
  toast("Deleted 🗑"); go("checklists");
}
async function archiveItem(id) { await api(`/api/admin/checklists`, { method:"POST", body:{action:"archive", item_id:id}}); go("checklists"); }
async function addItem(type) {
  const name = val("ni_"+type);
  if (!name) { toast("Enter an item name first."); return; }
  await api(`/api/admin/checklists`, { method:"POST", body:{ action:"add",
    checklist_type:type, item_name:name, item_type: val("nt_"+type),
    required: document.getElementById("nr_"+type).checked }});
  toast("Added ✅"); go("checklists");
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
