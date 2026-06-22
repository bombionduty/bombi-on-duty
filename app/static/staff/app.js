/*
 * Staff checklist Mini App (spec sections 5, 8, 9, 11, 12, 16).
 * One simple form per checkpoint: proof items + a combined attestation block.
 */
const PROOF_TYPES = ["Live Camera Photo", "Gallery Screenshot", "Number Entry", "Short Text Entry"];

let STATE = {
  mode: "task",          // "task" | "recovery"
  taskId: null,
  payload: null,
  attestationMode: null, // "all_complete" | "issue"
  issues: {},            // task_item_id -> details
  generalNote: "",
};

document.addEventListener("DOMContentLoaded", boot);

async function boot() {
  tgInit();
  const param = startParam() || qs("startapp") || qs("token") || "";
  try {
    if (param.startsWith("recovery_")) {
      STATE.mode = "recovery";
      STATE.taskId = param.slice("recovery_".length);
      await loadRecovery();
    } else if (param) {
      const data = await api(`/api/task/by-token/${encodeURIComponent(param)}`);
      STATE.payload = data;
      STATE.taskId = data.task_id;
      renderTask();
    } else {
      showError("No checklist link found. Please open this from the staff group button.");
    }
  } catch (e) {
    showError(e.message);
    document.getElementById("app").innerHTML = "";
  }
}

/* ----------------------------------------------------------- TASK RENDER */
function renderTask() {
  const p = STATE.payload;
  const app = document.getElementById("app");
  const proofItems = p.items.filter(i => PROOF_TYPES.includes(i.type));
  const attestItems = p.items.filter(i => i.type === "Attestation" || i.type === "Yes or No");

  let html = `
    <h1>${esc(p.checklist_type)}</h1>
    <p class="sub">${esc(p.operating_date)} • Assigned: ${esc(p.assigned_staff)} • Due ${esc(p.deadline)}</p>
  `;

  if (proofItems.length) html += `<h2>Required Proof</h2>`;
  proofItems.forEach(it => { html += proofCard(it); });

  if (attestItems.length) {
    html += `<h2>Confirm Requirements</h2><div class="card"><div id="attestList">`;
    attestItems.forEach(it => {
      html += `<div class="checkitem"><div>✔️</div><div>${esc(it.name)}
        ${it.instructions ? `<div class="muted">${esc(it.instructions)}</div>` : ""}</div></div>`;
    });
    html += `</div>
      <p style="font-weight:600;margin-top:10px">Are all listed requirements complete?</p>
      <button id="btnAllComplete" class="secondary">Everything Listed Is Complete</button>
      <button id="btnReportIssue" class="ghost">Report an Issue</button>
      <div id="issueBox"></div>
    </div>`;
  }

  html += `
    <div class="card">
      <p class="muted">${esc(p.final_acknowledgement)}</p>
      <button id="btnSubmit" disabled>Submit ${esc(shortName(p.checklist_type))}</button>
    </div>`;

  app.innerHTML = html;
  proofItems.forEach(it => wireProof(it));
  if (attestItems.length) {
    document.getElementById("btnAllComplete").onclick = () => chooseAttestation("all_complete", attestItems);
    document.getElementById("btnReportIssue").onclick = () => chooseAttestation("issue", attestItems);
  } else {
    STATE.attestationMode = "all_complete"; // nothing to attest
  }
  document.getElementById("btnSubmit").onclick = submitTask;
  refreshSubmit();
}

function shortName(t) { return t.replace("Opener ", "").replace(" Check", t.includes("Closing") ? " Closing" : ""); }

function proofCard(it) {
  const done = it.completed;
  const pill = done ? `<span class="pill ok">Received</span>` : `<span class="pill warn">Required</span>`;
  let body = "";
  if (it.type === "Live Camera Photo") {
    body = `
      <div id="cam_${it.task_item_id}"></div>
      <button class="secondary" data-cam="${it.task_item_id}">📷 Take Photo Now</button>
      <button class="ghost" data-gallery="${it.task_item_id}">Upload from Gallery</button>
      <input type="file" accept="image/*" capture="environment" style="display:none" data-fileinput="${it.task_item_id}" />`;
  } else if (it.type === "Gallery Screenshot") {
    body = `
      <button class="secondary" data-gallery="${it.task_item_id}">Upload Screenshot</button>
      <input type="file" accept="image/*" style="display:none" data-fileinput="${it.task_item_id}" />`;
  } else if (it.type === "Number Entry") {
    body = `<input type="number" inputmode="decimal" data-num="${it.task_item_id}" value="${esc(it.response||"")}" />
      <button class="ghost" data-savetext="${it.task_item_id}">Save</button>`;
  } else if (it.type === "Short Text Entry") {
    body = `<input type="text" data-text="${it.task_item_id}" value="${esc(it.response||"")}" />
      <button class="ghost" data-savetext="${it.task_item_id}">Save</button>`;
  }
  return `<div class="card" id="card_${it.task_item_id}">
    <div class="row"><strong>${esc(it.name)}</strong>${pill}</div>
    ${it.instructions ? `<p class="muted">${esc(it.instructions)}</p>` : ""}
    <div id="proofstate_${it.task_item_id}"></div>
    ${body}
  </div>`;
}

function wireProof(it) {
  const id = it.task_item_id;
  const camBtn = document.querySelector(`[data-cam="${id}"]`);
  if (camBtn) camBtn.onclick = () => openCamera(it);
  const galBtn = document.querySelector(`[data-gallery="${id}"]`);
  const fileInput = document.querySelector(`[data-fileinput="${id}"]`);
  if (galBtn && fileInput) {
    galBtn.onclick = () => fileInput.click();
    fileInput.onchange = () => {
      if (fileInput.files[0]) uploadProof(it, fileInput.files[0],
        it.type === "Live Camera Photo" ? "Gallery Fallback" : "Live Camera");
    };
  }
  const saveBtn = document.querySelector(`[data-savetext="${id}"]`);
  if (saveBtn) saveBtn.onclick = () => saveText(it);
  if (it.completed && it.evidence && it.evidence.length) showProofDone(it, it.evidence[0]);
}

/* ----------------------------------------------------------- LIVE CAMERA */
async function openCamera(it) {
  const box = document.getElementById(`cam_${it.task_item_id}`);
  box.innerHTML = "";
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" } }, audio: false,
    });
  } catch (e) {
    box.innerHTML = `<p class="muted">Camera unavailable (${esc(e.name)}). Use gallery upload instead, then you can retake with the camera later.</p>`;
    return;
  }
  const video = document.createElement("video");
  video.autoplay = true; video.playsInline = true; video.className = "preview";
  video.srcObject = stream;
  const snap = document.createElement("button");
  snap.textContent = "Capture";
  box.appendChild(video); box.appendChild(snap);

  snap.onclick = () => {
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth; canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0);
    stream.getTracks().forEach(t => t.stop());
    box.innerHTML = "";
    const img = document.createElement("img"); img.className = "preview";
    img.src = canvas.toDataURL("image/jpeg", 0.9);
    const useBtn = document.createElement("button"); useBtn.textContent = "Use This Photo";
    const retake = document.createElement("button"); retake.className = "ghost"; retake.textContent = "Retake";
    box.appendChild(img); box.appendChild(useBtn); box.appendChild(retake);
    retake.onclick = () => openCamera(it);
    useBtn.onclick = () => canvas.toBlob(b => uploadProof(it, b, "Live Camera"), "image/jpeg", 0.9);
  };
}

/* ----------------------------------------------------------- UPLOAD */
async function uploadProof(it, fileOrBlob, captureSource) {
  const fd = new FormData();
  fd.append("task_item_id", it.task_item_id);
  fd.append("capture_source", captureSource);
  fd.append("file", fileOrBlob, (fileOrBlob.name || "photo.jpg"));
  setProofState(it, "Uploading…");
  try {
    const r = await api(`/api/task/${STATE.taskId}/upload`, { method: "POST", form: fd });
    it.completed = true;
    showProofDone(it, { thumb_url: r.thumb_url, metadata_result: r.metadata_result,
                        possible_duplicate: r.possible_duplicate });
  } catch (e) {
    setProofState(it, "");
    showError(e.message);
  }
  refreshSubmit();
}

function showProofDone(it, ev) {
  const card = document.getElementById(`card_${it.task_item_id}`);
  if (card) {
    const pill = card.querySelector(".pill");
    if (pill) { pill.className = "pill ok"; pill.textContent = "Received"; }
  }
  let extra = ev.metadata_result ? `<span class="muted"> • ${esc(ev.metadata_result)}</span>` : "";
  if (ev.possible_duplicate) extra += ` <span class="pill bad">possible duplicate</span>`;
  setProofState(it, `<div class="row"><img class="thumb" src="${evidenceUrl(ev.thumb_url)}"/>${extra}</div>`);
}

function setProofState(it, html) {
  const el = document.getElementById(`proofstate_${it.task_item_id}`);
  if (el) el.innerHTML = html;
}

async function saveText(it) {
  const input = document.querySelector(`[data-num="${it.task_item_id}"], [data-text="${it.task_item_id}"]`);
  const val = input.value.trim();
  if (!val) { showError("Please enter a value."); return; }
  try {
    await api(`/api/task/${STATE.taskId}/text`, { method: "POST",
      body: { task_item_id: it.task_item_id, response: val } });
    it.completed = true;
    setProofState(it, `<span class="pill ok">Saved: ${esc(val)}</span>`);
  } catch (e) { showError(e.message); }
  refreshSubmit();
}

/* ----------------------------------------------------------- ATTESTATION */
function chooseAttestation(mode, attestItems) {
  STATE.attestationMode = mode;
  document.getElementById("btnAllComplete").className = mode === "all_complete" ? "" : "secondary";
  document.getElementById("btnReportIssue").className = mode === "issue" ? "" : "ghost";
  const box = document.getElementById("issueBox");
  if (mode === "all_complete") { box.innerHTML = ""; STATE.issues = {}; refreshSubmit(); return; }
  let html = `<p class="muted" style="margin-top:12px">Select only the items with problems:</p>`;
  attestItems.forEach(it => {
    html += `<label style="font-weight:500"><input type="checkbox" data-issue="${it.task_item_id}" style="width:auto"/> ${esc(it.name)}</label>
      <textarea data-issuedetail="${it.task_item_id}" placeholder="What's the problem?" style="display:none"></textarea>`;
  });
  html += `<label>General notes (optional)</label><textarea data-generalnote></textarea>`;
  box.innerHTML = html;
  attestItems.forEach(it => {
    const cb = box.querySelector(`[data-issue="${it.task_item_id}"]`);
    const det = box.querySelector(`[data-issuedetail="${it.task_item_id}"]`);
    cb.onchange = () => { det.style.display = cb.checked ? "block" : "none"; refreshSubmit(); };
    det.oninput = refreshSubmit;
  });
  box.querySelector("[data-generalnote]").oninput = (e) => { STATE.generalNote = e.target.value; };
  refreshSubmit();
}

function collectIssues() {
  const out = [];
  document.querySelectorAll("[data-issue]").forEach(cb => {
    if (cb.checked) {
      const id = cb.getAttribute("data-issue");
      const det = document.querySelector(`[data-issuedetail="${id}"]`).value.trim();
      out.push({ task_item_id: id, details: det });
    }
  });
  return out;
}

/* ----------------------------------------------------------- SUBMIT */
function requiredProofDone() {
  return STATE.payload.items
    .filter(i => i.required && PROOF_TYPES.includes(i.type))
    .every(i => i.completed);
}

function attestationOk() {
  if (STATE.attestationMode === "all_complete") return true;
  if (STATE.attestationMode === "issue") {
    const issues = collectIssues();
    return issues.length > 0 && issues.every(i => i.details.length > 0);
  }
  return false;
}

function refreshSubmit() {
  const btn = document.getElementById("btnSubmit");
  if (btn) btn.disabled = !(requiredProofDone() && attestationOk());
}

async function submitTask() {
  const issues = STATE.attestationMode === "issue" ? collectIssues() : [];
  if (STATE.generalNote) issues.push({ task_item_id: "general", details: STATE.generalNote });
  try {
    const r = await api(`/api/task/${STATE.taskId}/submit`, { method: "POST",
      body: { completion_mode: STATE.attestationMode, issues } });
    document.getElementById("app").innerHTML =
      `<div class="card"><h1>✅ Submitted</h1><p>Status: ${esc(r.status)} — ${esc(r.result)}</p>
       <p class="muted">You can close this window.</p></div>`;
    if (window.Telegram) Telegram.WebApp.HapticFeedback?.notificationOccurred("success");
  } catch (e) { showError(e.message); }
}

/* ----------------------------------------------------------- RECOVERY */
async function loadRecovery() {
  const p = await api(`/api/recovery/${STATE.taskId}`);
  const app = document.getElementById("app");
  let html = `<h1>OIC Recovery</h1>
    <p class="sub">${esc(p.checklist_type)} • ${esc(p.operating_date)} • Originally: ${esc(p.original_assignee)} (${esc(p.original_status)})</p>
    <div class="card"><strong>Already completed</strong>
      ${p.completed_items.map(i => `<div class="checkitem">✔️ ${esc(i.name)}</div>`).join("") || `<p class="muted">None</p>`}
    </div>
    <h2>Missing items to recover</h2>`;
  p.missing_items.forEach(it => {
    html += `<div class="card" id="rcard_${it.task_item_id}">
      <div class="row"><strong>${esc(it.name)}</strong><span class="pill warn">Missing</span></div>
      <button class="secondary" data-rgallery="${it.task_item_id}">Upload Evidence</button>
      <input type="file" accept="image/*" style="display:none" data-rfile="${it.task_item_id}"/>
    </div>`;
  });
  html += `<div class="card">
      <label>Recovery reason (required)</label><textarea id="recReason"></textarea>
      <label>Notes (optional)</label><textarea id="recNotes"></textarea>
      <p class="muted">${esc(p.confirmation)}</p>
      <button id="recSubmit">Submit OIC Recovery</button>
    </div>`;
  app.innerHTML = html;
  p.missing_items.forEach(it => {
    const btn = document.querySelector(`[data-rgallery="${it.task_item_id}"]`);
    const fi = document.querySelector(`[data-rfile="${it.task_item_id}"]`);
    btn.onclick = () => fi.click();
    fi.onchange = () => { if (fi.files[0]) recUpload(it, fi.files[0]); };
  });
  document.getElementById("recSubmit").onclick = recSubmit;
}

async function recUpload(it, file) {
  const fd = new FormData();
  fd.append("task_item_id", it.task_item_id);
  fd.append("capture_source", "Gallery Fallback");
  fd.append("file", file, file.name || "recovery.jpg");
  try {
    await api(`/api/recovery/${STATE.taskId}/upload`, { method: "POST", form: fd });
    const card = document.getElementById(`rcard_${it.task_item_id}`);
    card.querySelector(".pill").className = "pill ok";
    card.querySelector(".pill").textContent = "Recovered";
  } catch (e) { showError(e.message); }
}

async function recSubmit() {
  const reason = document.getElementById("recReason").value.trim();
  if (!reason) { showError("A recovery reason is required."); return; }
  try {
    await api(`/api/recovery/${STATE.taskId}/submit`, { method: "POST",
      body: { reason, notes: document.getElementById("recNotes").value.trim() } });
    document.getElementById("app").innerHTML =
      `<div class="card"><h1>✅ Recovery recorded</h1>
       <p class="muted">The original employee's record is preserved. You can close this window.</p></div>`;
  } catch (e) { showError(e.message); }
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g,
    c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
}
