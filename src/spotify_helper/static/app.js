// Show a "working" hint on slow actions, and wire up select-all buttons.
document.addEventListener("submit", () => { document.getElementById("busy").hidden = false; });
document.addEventListener("click", (e) => {
  const busyLink = e.target.closest("a[data-busy]");
  if (busyLink) document.getElementById("busy").hidden = false;
  const toggle = e.target.closest("[data-check-all]");
  if (toggle) {
    e.preventDefault();
    const boxes = toggle.closest("form").querySelectorAll(`input[type=checkbox][name="${toggle.dataset.checkAll}"]`);
    const anyOff = [...boxes].some((b) => !b.checked);
    boxes.forEach((b) => { b.checked = anyOff; });
  }
});
window.addEventListener("pageshow", () => { document.getElementById("busy").hidden = true; });
