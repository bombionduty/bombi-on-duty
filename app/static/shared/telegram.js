/*
 * Shared Telegram Mini App helpers.
 * Every API call sends the raw initData in the X-Telegram-Init-Data header so
 * the backend can validate the caller server-side (spec section 7).
 */
const TG = window.Telegram ? window.Telegram.WebApp : null;

function tgInit() {
  if (TG) {
    TG.ready();
    TG.expand();
  }
}

function initData() {
  return TG ? TG.initData : "";
}

function startParam() {
  // Which task/checklist to open, from the ?startapp=... deep link.
  //
  // IMPORTANT: on mobile Telegram the Mini App webview is often REUSED, and
  // `initDataUnsafe.start_param` can keep the value from the FIRST launch of the
  // session — so after submitting one checklist, reopening for the next would
  // reload the previous (already-submitted) task. The launch URL hash carries
  // `tgWebAppStartParam` for the CURRENT open, so we read that first.
  try {
    const hash = (window.location.hash || "").replace(/^#/, "");
    const fromHash = new URLSearchParams(hash).get("tgWebAppStartParam");
    if (fromHash) return fromHash;
  } catch (e) { /* fall through */ }
  if (TG && TG.initDataUnsafe && TG.initDataUnsafe.start_param) {
    return TG.initDataUnsafe.start_param;
  }
  return "";
}

function qs(name) {
  return new URLSearchParams(window.location.search).get(name);
}

async function api(path, { method = "GET", body = null, form = null } = {}) {
  const headers = { "X-Telegram-Init-Data": initData() };
  let payload = null;
  if (form) {
    payload = form; // FormData sets its own content-type
  } else if (body) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(path, { method, headers, body: payload });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail; } catch (e) {}
    throw new Error(detail);
  }
  return res.json();
}

// Append auth to an evidence image URL (img tags cannot send headers).
function evidenceUrl(baseUrl) {
  const sep = baseUrl.includes("?") ? "&" : "?";
  return baseUrl + sep + "auth=" + encodeURIComponent(initData());
}

function toast(msg) {
  if (TG && TG.showAlert) TG.showAlert(msg);
  else alert(msg);
}

function showError(msg) {
  const el = document.getElementById("error");
  if (el) { el.textContent = msg; el.style.display = "block"; }
  else toast(msg);
}

// Transient green success banner (auto-hides). Used for "Uploaded complete".
function flash(msg) {
  let el = document.getElementById("flash");
  if (!el) {
    el = document.createElement("div");
    el.id = "flash";
    el.style.cssText = "position:sticky;top:0;z-index:99;background:rgba(46,158,91,.18);" +
      "color:#2e9e5b;padding:12px;border-radius:10px;margin-bottom:12px;" +
      "font-weight:700;text-align:center;";
    document.body.prepend(el);
  }
  el.textContent = msg;
  el.style.display = "block";
  if (window.Telegram && Telegram.WebApp.HapticFeedback) {
    Telegram.WebApp.HapticFeedback.notificationOccurred("success");
  }
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.style.display = "none"; }, 3000);
}
