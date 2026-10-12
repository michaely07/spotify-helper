// Tools open in a popup (<dialog>) over the current page. Each tool is a normal server page; we fetch it and
// show its <main> inside the popup, and keep links and forms inside the popup. Without JS the pages still work.

const modal = document.getElementById("modal");
const modalBody = modal.querySelector(".modal-body");
const modalStatus = modal.querySelector(".modal-status");
const modalBack = modal.querySelector("[data-modal-back]");
const busy = document.getElementById("busy");

let history_ = [];      // URLs shown in the popup, for its Back button
let applied = false;    // a change was applied in Spotify while the popup was open
let created = false;    // ...and it created a playlist the page behind doesn't list yet
let loading = false;

function setLoading(on) {
  loading = on;
  modalBody.classList.toggle("loading", on);
  modalStatus.textContent = on ? "Working… big playlists can take a minute the first time." : "";
}

async function loadInModal(url, init = {}, { remember = true } = {}) {
  if (loading) return;
  setLoading(true);
  let resp, html;
  try {
    resp = await fetch(url, init);
    html = await resp.text();
  } catch {
    setLoading(false);
    modalBody.innerHTML = '<div class="card error"><p>Couldn\'t reach the app. Is it still running?</p></div>';
    return;
  }
  const requested = new URL(url, location.href);
  const landed = new URL(resp.url);
  if (landed.pathname === "/" && requested.pathname !== "/") {
    location.href = "/";  // bounced home (e.g. logged out): show the real home page
    return;
  }
  const doc = new DOMParser().parseFromString(html, "text/html");
  modalBody.innerHTML = (doc.querySelector("main") || doc.body).innerHTML;
  modal.scrollTop = 0;
  // history_'s last entry is the page on screen; null marks one that can't be re-fetched. A successful POST
  // answered directly (e.g. "Apply") is a point of no return, so Back is cleared there. A failed one (an
  // error page) can step back to the form. A POST that redirected landed on a re-fetchable page.
  if ((init.method || "GET") !== "GET" && !resp.redirected) {
    if (resp.ok) history_ = []; else history_.push(null);
  } else if (remember) history_.push(resp.url);
  modalBack.hidden = history_.length < 2;
  setLoading(false);
  applyUpdates();
  const heading = modalBody.querySelector("h1");
  if (heading) heading.setAttribute("tabindex", "-1"), heading.focus({ preventScroll: true });
}

// After "Apply", the result page carries new track counts; update the page behind the popup right away.
function applyUpdates() {
  const marker = modalBody.querySelector("[data-updated]");
  if (!marker) return;
  applied = true;
  created ||= marker.dataset.created === "true";
  const totals = JSON.parse(marker.dataset.updated || "{}");
  for (const [pid, total] of Object.entries(totals)) {
    document.querySelectorAll(`[data-count-for="${CSS.escape(pid)}"]`).forEach((el) => { el.textContent = total; });
  }
}

function openModal(url) {
  history_ = [];
  modalBody.innerHTML = "";
  modalBack.hidden = true;
  if (!modal.open) modal.showModal();
  loadInModal(url);
}

function modalGoBack() {
  if (history_.length < 2) return modal.close();
  history_.pop();
  while (history_.length && history_[history_.length - 1] === null) history_.pop();
  if (!history_.length) return modal.close();
  loadInModal(history_[history_.length - 1], {}, { remember: false });
}

modal.addEventListener("close", () => {
  modalBody.innerHTML = "";
  // The home page's counts were updated in place; anything else (or a new playlist) needs a fresh render.
  if (applied && (created || location.pathname !== "/")) location.reload();
  applied = created = false;
});

modalBack.addEventListener("click", modalGoBack);

document.addEventListener("click", (e) => {
  const toggle = e.target.closest("[data-check-all]");
  if (toggle) {
    e.preventDefault();
    const boxes = toggle.closest("form").querySelectorAll(`input[type=checkbox][name="${toggle.dataset.checkAll}"]:not(:disabled)`);
    const anyOff = [...boxes].some((b) => !b.checked);
    boxes.forEach((b) => { b.checked = anyOff; });
    return;
  }

  const inModal = modal.contains(e.target);
  if (inModal && e.target.closest("[data-close]")) { e.preventDefault(); modal.close(); return; }
  if (e.target.closest("[data-back]")) {
    e.preventDefault();
    if (inModal) modalGoBack(); else history.back();
    return;
  }

  const link = e.target.closest("a[href]");
  if (!link || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
  const url = new URL(link.href, location.href);
  if (link.target === "_blank" || url.origin !== location.origin) return;
  if (inModal) { e.preventDefault(); loadInModal(url.href); return; }
  if (link.hasAttribute("data-modal")) { e.preventDefault(); openModal(url.href); return; }
  if (link.hasAttribute("data-busy")) busy.hidden = false;
});

document.addEventListener("submit", (e) => {
  const form = e.target;
  if (!modal.contains(form)) { busy.hidden = false; return; }
  e.preventDefault();
  // A form without an action submits to the page it came from, which is the popup's page, not the one behind.
  const here = history_.filter(Boolean).pop() || location.href;
  const action = new URL(form.getAttribute("action") || here, location.href);
  const data = new URLSearchParams(new FormData(form));
  if ((form.method || "get").toLowerCase() === "post") {
    form.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    loadInModal(action.href, { method: "POST", body: data });
  } else {
    action.search = data.toString();
    loadInModal(action.href);
  }
});

window.addEventListener("pageshow", () => { busy.hidden = true; });
