"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const icon = (n, cls = "") => `<svg class="ico ${cls}"><use href="#i-${n}"/></svg>`;
const fmt = (n) => Number(n || 0).toLocaleString("en-US");
const hms = (s) => (!s || isNaN(s) || s < 0) ? "00:00:00" : [s / 3600, (s % 3600) / 60, s % 60].map((v) => String(Math.floor(v)).padStart(2, "0")).join(":");

let api = null;
let view = "queue";
let state = null;
let taskSig = "";
let presets = {};
let editing = null;
let toastTimer = 0;

const toast = (msg) => {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
};

/* ------------------------------------------------------------ navigation */
function switchView(name) {
  if (view === name) return; // Never reset scroll or re-render if clicking inside the current view
  view = name;
  $$(".view").forEach((v) => (v.hidden = v.dataset.view !== name));
  $$(".tab").forEach((t) => t.classList.toggle("on", t.dataset.view === name));
  $$(".rail-btn[data-view]").forEach((t) => t.classList.toggle("on", t.dataset.view === name));
  $("#stage").scrollTop = 0;
  if (name === "analytics") loadAnalytics();
  if (name === "live") { renderLive(); loadLog(); }
}
// Attach navigation listeners ONLY to the tab and rail buttons, NOT to section.view containers
$$(".tab[data-view], .rail-btn[data-view]").forEach((b) => b.addEventListener("click", () => switchView(b.dataset.view)));
$("#hook").addEventListener("click", () => switchView("webhooks"));

/* ---------------------------------------------------------------- queue */
function taskCard(t) {
  const running = t.state === "running";
  const ring = running ? "flame" : t.state === "done" ? "check" : "hourglass";
  const label = running ? "IN PROGRESS" : t.state === "done" ? "COMPLETED" : "PENDING";
  const loop = t.loop_count ? `${t.runs_completed}/${t.loop_count}` : t.runs_completed ? `∞ · ${t.runs_completed} done` : "Infinite";
  let live = "";
  let bar = "";
  if (running && state) {
    const w = state.wave ?? 0;
    live = `<span class="live">${icon("wave")}Wave: <b>${w}/${t.waves}</b></span>`;
    bar = `<div class="bar"><i style="width:${Math.min(100, (w / t.waves) * 100)}%"></i></div>`;
  }
  return `
  <article class="card ${t.state}" data-id="${t.id}">
    <div class="grip" title="Drag to reorder">${icon("grip")}</div>
    <div class="ring">${icon(ring)}</div>
    <div class="card-main">
      <div class="card-title"><h3>${esc(t.name)}</h3><span class="pill ${t.state}">${label}</span></div>
      <div class="meta">
        <span>${icon("map")}Map: <b>${esc(t.map_name)}</b></span>
        <span>${icon("shield")}Mode: <b>${esc(t.gamemode)}</b></span>
        ${live || `<span>${icon("wave")}Waves: <b>${t.waves}</b></span>`}
        <span>${icon("repeat")}Loop: <b>${loop}</b></span>
        ${t.coins_earned ? `<span>${icon("coins")}<b>${fmt(t.coins_earned)}</b> coins</span>` : ""}
      </div>
      ${bar}
    </div>
    <div class="card-actions">
      <button class="icon-btn" data-act="edit" aria-label="Edit task">${icon("pencil")}</button>
      <button class="icon-btn del" data-act="del" aria-label="Delete task">${icon("trash")}</button>
    </div>
  </article>`;
}

function renderQueue() {
  const q = $("#queue");
  if (!state || !state.tasks || state.tasks.length === 0) {
    q.innerHTML = `
      <div class="empty-queue">
        <div class="empty-queue-title">NO ACTIVE TASKS IN QUEUE</div>
        <p class="empty-queue-sub">Click <b>+ ADD TASK</b> in the top right to configure a farm run.</p>
      </div>`;
    return;
  }
  q.innerHTML = state.tasks.map(taskCard).join("") +
    `<p class="hint">Tasks run top to bottom. Drag the handle to reorder, or add another task to chain farms.</p>`;
}

$("#queue").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-act]");
  if (!btn) return;
  const id = btn.closest(".card").dataset.id;
  const t = state.tasks.find((x) => x.id === id);
  if (btn.dataset.act === "edit") openModal(t);
  if (btn.dataset.act === "del") {
    if (t && t.state === "running") return toast("Stop the macro before deleting the running task.");
    api.delete_task(id).then(refresh);
  }
});

/* drag to reorder (grip only) */
let dragEl = null;
$("#queue").addEventListener("mousedown", (e) => {
  const g = e.target.closest(".grip");
  if (g) g.closest(".card").draggable = true;
});
$("#queue").addEventListener("dragstart", (e) => {
  dragEl = e.target.closest(".card");
  if (!dragEl) return;
  dragEl.classList.add("dragging");
  e.dataTransfer.effectAllowed = "move";
});
$("#queue").addEventListener("dragover", (e) => {
  if (!dragEl) return;
  e.preventDefault();
  const over = e.target.closest(".card");
  if (!over || over === dragEl) return;
  const r = over.getBoundingClientRect();
  over.parentNode.insertBefore(dragEl, e.clientY < r.top + r.height / 2 ? over : over.nextSibling);
});
$("#queue").addEventListener("dragend", () => {
  if (!dragEl) return;
  dragEl.classList.remove("dragging");
  dragEl.draggable = false;
  dragEl = null;
  api.reorder_tasks($$("#queue .card").map((c) => c.dataset.id)).then(refresh);
});

/* ---------------------------------------------------------------- modal */
function setLoops(infinite, n) {
  $("#f-inf").setAttribute("aria-pressed", infinite);
  $("#f-fin").setAttribute("aria-pressed", !infinite);
  $("#f-loops").disabled = infinite;
  if (n) $("#f-loops").value = n;
}
function openModal(task) {
  editing = task || null;
  $("#modal-title").textContent = task ? "EDIT TASK" : "ADD TASK";
  const sel = $("#f-preset");
  sel.innerHTML = Object.entries(presets).map(([k, v]) => `<option value="${k}">${esc(v.label)}</option>`).join("");
  sel.value = task ? task.preset : Object.keys(presets)[0];
  const spec = presets[sel.value] || { label: "Dead Ahead Coin Farm", max_scouts: 20, default_scouts: 16 };
  $("#f-name").value = task ? task.name : spec.label;
  const sc = $("#f-scouts");
  sc.max = spec.max_scouts;
  sc.value = task ? task.scout_count : spec.default_scouts;
  $("#f-scouts-v").textContent = sc.value;
  setLoops(!task || !task.loop_count, task && task.loop_count);
  $("#f-del").hidden = !task;
  $("#scrim").hidden = false;
  $("#f-name").focus();
  $("#f-name").select();
}
const closeModal = () => ($("#scrim").hidden = true);
$("#add-task").addEventListener("click", () => openModal(null));
$("#f-cancel").addEventListener("click", closeModal);
$("#scrim").addEventListener("mousedown", (e) => { if (e.target.id === "scrim") closeModal(); });
$("#f-scouts").addEventListener("input", (e) => ($("#f-scouts-v").textContent = e.target.value));
$("#f-inf").addEventListener("click", () => setLoops(true));
$("#f-fin").addEventListener("click", () => { setLoops(false); $("#f-loops").focus(); });
$("#f-preset").addEventListener("change", (e) => {
  const s = presets[e.target.value];
  if (!editing && s) $("#f-name").value = s.label;
});
$("#f-del").addEventListener("click", () => {
  if (editing && editing.state === "running") return toast("Stop the macro before deleting the running task.");
  if (editing) {
    api.delete_task(editing.id).then(() => { closeModal(); refresh(); });
  }
});
$("#task-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const infinite = $("#f-inf").getAttribute("aria-pressed") === "true";
  await api.save_task({
    id: editing ? editing.id : undefined,
    preset: $("#f-preset").value,
    name: $("#f-name").value,
    loop_count: infinite ? 0 : Math.max(1, parseInt($("#f-loops").value, 10) || 1),
    scout_count: parseInt($("#f-scouts").value, 10),
  });
  closeModal();
  refresh();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

/* ----------------------------------------------------------------- dock */
function updateDock() {
  const s = state;
  if (!s) return;
  const run = s.status === "RUNNING", pause = s.status === "PAUSED", idle = s.status === "IDLE";
  const empty = !s.tasks || s.tasks.length === 0;
  $("#dot").className = "dot " + (run ? "run" : pause ? "pause" : "");
  $("#sys").textContent = empty && idle ? "Idle (No Tasks)" : (s.sys || "Idle");
  $("#elapsed").textContent = hms(s.elapsed);
  $("#coins").textContent = fmt(s.coins);
  const start = $("#btn-start");
  start.disabled = !idle || empty;
  start.classList.toggle("idle", idle && !empty);
  $("#btn-pause").disabled = idle;
  $("#btn-pause span").textContent = pause ? "RESUME" : "PAUSE";
  $("#btn-pause use").setAttribute("href", pause ? "#i-play" : "#i-pause");
  $("#btn-stop").disabled = idle;
  $("#hook").classList.toggle("on", s.webhook);
  $("#hook-v").textContent = s.webhook ? "CONNECTED" : "NOT SET";
}
$("#btn-start").addEventListener("click", () => {
  if (!state || !state.tasks || state.tasks.length === 0) {
    return toast("Queue is empty. Click + ADD TASK first.");
  }
  api.start();
});
$("#btn-pause").addEventListener("click", () => api.pause());
$("#btn-stop").addEventListener("click", () => api.stop());

/* ----------------------------------------------------------- live/analytics */
const kpi = (label, value, cls = "") => `<div class="kpi"><span>${label}</span><b class="${cls}">${value}</b></div>`;
function renderLive() {
  if (!state) return;
  const s = state;
  $("#live-kpis").innerHTML =
    kpi("Status", s.sys || s.status, s.status === "RUNNING" ? "red" : "") +
    kpi("Game screen", esc(s.game_state || "—")) +
    kpi("Wave", s.wave ?? "—") +
    kpi("Cash", s.cash != null ? "$" + fmt(s.cash) : "—") +
    kpi("Scouts placed", s.scouts) +
    kpi("Runs (W/L)", `${s.runs} (${s.wins}/${s.runs - s.wins})`) +
    kpi("Coins / hr", fmt(s.coins_per_hr));
}
async function loadLog() {
  if (view !== "live") return;
  const lines = await api.get_log();
  const box = $("#log");
  const stick = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.textContent = lines.length ? lines.join("\n") : "No activity yet. Press Start.";
  if (stick) box.scrollTop = box.scrollHeight;
}
async function loadAnalytics() {
  const a = await api.get_analytics();
  const s = a.summary;
  const rate = s.runs ? Math.round((s.wins / s.runs) * 100) + "%" : "—";
  $("#an-kpis").innerHTML =
    kpi("Runs", s.runs) + kpi("Win rate", rate) + kpi("Coins earned", fmt(s.coins_total), "red") +
    kpi("Coins / hr", fmt(Math.round(s.coins_per_hour))) + kpi("XP earned", fmt(s.xp_total));

  const hrs = a.hourly;
  const max = Math.max(1, ...hrs.map((h) => h.coins));
  $("#chart").innerHTML = hrs.length
    ? `<div style="display:flex;align-items:flex-end;gap:10px;height:100%">${hrs.map((h) => `
        <div title="${fmt(h.coins)} coins · ${h.runs} runs" style="flex:1;max-width:64px;display:flex;flex-direction:column;justify-content:flex-end;height:100%;gap:6px">
          <div style="height:${Math.max(3, (h.coins / max) * 78)}%;background:linear-gradient(180deg,var(--accent),rgba(242,17,61,.35));border-radius:3px 3px 0 0"></div>
          <span style="font-size:10px;color:var(--muted);text-align:center">${h.hour.slice(11, 16)}</span>
        </div>`).join("")}</div>`
    : `<div class="empty">No completed runs yet.</div>`;

  const cls = (r) => (["victory", "triumph", "win"].includes(r) ? "w" : r === "defeat" ? "l" : "e");
  const word = (r) => (["victory", "triumph", "win"].includes(r) ? "TRIUMPH" : r.toUpperCase());
  const mmss = (d) => `${Math.floor(d / 60)}m ${String(Math.floor(d % 60)).padStart(2, "0")}s`;
  $("#runs").innerHTML = a.runs.length
    ? `<thead><tr><th>Ended</th><th>Result</th><th>Map</th><th class="num">Wave</th><th class="num">Coins</th><th class="num">XP</th><th class="num">Time</th></tr></thead><tbody>` +
      a.runs.map((r) => `<tr><td>${r.ended ? new Date(r.ended).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}</td>
        <td class="${cls(r.result)}">${word(r.result)}</td><td>${esc(r.map || "—")}</td><td class="num">${r.wave ?? "—"}</td>
        <td class="num">${fmt(r.coins)}</td><td class="num">${fmt(r.xp)}</td><td class="num">${mmss(r.duration)}</td></tr>`).join("") + "</tbody>"
    : `<tbody><tr><td style="color:var(--dim);padding:22px;text-align:center">No runs recorded yet.</td></tr></tbody>`;
}


let currentHotkeys = { start: "F1", pause: "F2", stop: "F3", overlay: "F7" };
let recordingAction = null;
let modalAction = null;

const HOTKEY_OPTIONS = [
  "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
  "INSERT", "DELETE", "HOME", "END", "PAGEUP", "PAGEDOWN",
  "NUMPAD0", "NUMPAD1", "NUMPAD2", "NUMPAD3", "NUMPAD4", "NUMPAD5", "NUMPAD6", "NUMPAD7", "NUMPAD8", "NUMPAD9"
];

function renderKeycaps() {
  ["start", "pause", "stop", "overlay"].forEach((act) => {
    const valEl = $(`#hk-val-${act}`);
    const isRec = recordingAction === act;
    const btn = $(`#hk-btn-${act}`);
    if (valEl) valEl.textContent = isRec ? "[ ... ]" : (currentHotkeys[act] || "NONE");
    if (btn) {
      btn.classList.toggle("recording", isRec);
      const sub = btn.querySelector(".hk-sub");
      if (sub) sub.textContent = isRec ? "PRESS ANY KEY..." : "PRESS TO BIND";
    }
  });
  updateHotkeyBadges(currentHotkeys);
}

function updateHotkeyBadges(s) {
  if (!s) return;
  const kStart = s.start || s.hotkey_start || currentHotkeys.start;
  const kPause = s.pause || s.hotkey_pause || currentHotkeys.pause;
  const kStop = s.stop || s.hotkey_stop || currentHotkeys.stop;
  if ($("#badge-start")) $("#badge-start").textContent = kStart;
  if ($("#badge-pause")) $("#badge-pause").textContent = kPause;
  if ($("#badge-stop")) $("#badge-stop").textContent = kStop;
}

// Hotkey Recording & Custom Palette Logic
["start", "pause", "stop", "overlay"].forEach((act) => {
  $(`#hk-btn-${act}`)?.addEventListener("click", () => {
    recordingAction = recordingAction === act ? null : act;
    renderKeycaps();
  });
  $(`#hk-drop-${act}`)?.addEventListener("click", () => {
    openHkModal(act);
  });
});

document.addEventListener("keydown", async (e) => {
  if (!recordingAction) return;
  if (e.key === "Escape") {
    recordingAction = null;
    renderKeycaps();
    return;
  }
  e.preventDefault();
  e.stopPropagation();

  let k = e.key.toUpperCase();
  if (k.startsWith("ARROW")) k = k.replace("ARROW", "");
  const aliases = { " ": "SPACE", "CONTROL": "CTRL", "ALT": "ALT", "SHIFT": "SHIFT" };
  k = aliases[k] || k;

  const act = recordingAction;
  recordingAction = null;
  currentHotkeys[act] = k;
  renderKeycaps();

  await api.save_settings(collect());
  toast(`Hotkey bound: ${act.toUpperCase()} -> ${k}`);
});

function openHkModal(action) {
  modalAction = action;
  const titles = { start: "START / RESUME", pause: "PAUSE / RESUME", stop: "EMERGENCY STOP", overlay: "TOGGLE HUD" };
  $("#hk-modal-title").textContent = `BIND: ${titles[action] || action.toUpperCase()}`;
  $("#hk-modal-sub").textContent = "SELECT A PRESET KEY FROM THE PALETTE";

  const pal = $("#hk-palette");
  pal.innerHTML = HOTKEY_OPTIONS.map((k) => `
    <button type="button" class="hk-item ${currentHotkeys[action] === k ? "active" : ""}" data-k="${k}">${k}</button>
  `).join("");

  $("#hk-modal-scrim").hidden = false;
}

function closeHkModal() {
  $("#hk-modal-scrim").hidden = true;
  modalAction = null;
}

$("#hk-modal-close")?.addEventListener("click", closeHkModal);
$("#hk-modal-scrim")?.addEventListener("mousedown", (e) => {
  if (e.target.id === "hk-modal-scrim") closeHkModal();
});
$("#hk-palette")?.addEventListener("click", async (e) => {
  const item = e.target.closest(".hk-item");
  if (!item || !modalAction) return;
  const chosen = item.dataset.k;
  const act = modalAction;
  currentHotkeys[act] = chosen;
  closeHkModal();
  renderKeycaps();
  await api.save_settings(collect());
  toast(`Hotkey set: ${act.toUpperCase()} -> ${chosen}`);
});

/* ----------------------------------------------------------- modifiers */
const MODIFIERS_CATALOG = [
  {
    id: "explosive",
    name: "Exploding Enemies",
    short: "Explosive",
    multiplier: "+8% Coins",
    multiplierVal: 0.08,
    icon: "#i-bomb",
    desc: "Enemies detonate upon defeat dealing lethal area splash damage.",
    supported: true,
  },
  {
    id: "glass",
    name: "Glass",
    short: "Glass",
    multiplier: "+7% Coins",
    multiplierVal: 0.07,
    icon: "#i-glass",
    desc: "All towers and enemies suffer reduced max health and increased lethality.",
    supported: true,
  },
  {
    id: "faster_enemies",
    name: "Faster Enemies",
    short: "Swift",
    multiplier: "+10% Coins",
    multiplierVal: 0.10,
    icon: "#i-zap",
    desc: "All enemy units move 25% faster throughout all waves.",
    supported: false,
  },
  {
    id: "regen_enemies",
    name: "Regenerating Enemies",
    short: "Regen",
    multiplier: "+6% Coins",
    multiplierVal: 0.06,
    icon: "#i-heart",
    desc: "Enemies constantly regenerate a portion of their max health.",
    supported: false,
  },
  {
    id: "mystery_boss",
    name: "Mystery Boss",
    short: "Mystery",
    multiplier: "+12% Coins",
    multiplierVal: 0.12,
    icon: "#i-skull",
    desc: "The final wave features an unpredictable mutated boss encounter.",
    supported: false,
  },
];

let selectedModifiers = ["Exploding Enemies", "Glass"];
let modalSelectedModifiers = [];

function normalizeModName(name) {
  const n = (name || "").toLowerCase().trim();
  if (n.includes("explod") || n.includes("bomb")) return "explosive";
  if (n.includes("glass")) return "glass";
  if (n.includes("fast") || n.includes("swift")) return "faster_enemies";
  if (n.includes("regen")) return "regen_enemies";
  if (n.includes("boss") || n.includes("myster")) return "mystery_boss";
  return n;
}

function renderModifiersRow(enabled) {
  const countEl = $("#mod-active-count");
  const barEl = $("#mod-chips-bar");
  const chipsEl = $("#mod-active-chips");
  if (!countEl || !barEl || !chipsEl) return;

  barEl.classList.toggle("disabled", !enabled);
  if (!enabled) {
    countEl.textContent = "OFF";
    countEl.className = "badge off";
    chipsEl.innerHTML = `<span class="mod-chip empty">Modifiers Disabled (Vanilla Match)</span>`;
    return;
  }

  const activeMods = MODIFIERS_CATALOG.filter((m) =>
    selectedModifiers.some((sm) => normalizeModName(sm) === m.id)
  );

  countEl.textContent = `${activeMods.length} ACTIVE`;
  countEl.className = "badge";

  if (!activeMods.length) {
    chipsEl.innerHTML = `<span class="mod-chip empty">No Modifiers Selected</span>`;
  } else {
    chipsEl.innerHTML = activeMods
      .map(
        (m) =>
          `<span class="mod-chip"><svg class="ico"><use href="${m.icon}"/></svg>${esc(m.name)}</span>`
      )
      .join("");
  }
}

function updateModModalStats() {
  const supportedMods = MODIFIERS_CATALOG.filter((m) => m.supported);
  const activeSupported = supportedMods.filter((m) =>
    modalSelectedModifiers.some((sm) => normalizeModName(sm) === m.id)
  );

  let totalBonus = 0;
  activeSupported.forEach((m) => {
    totalBonus += m.multiplierVal;
  });

  const bonusPct = Math.round(totalBonus * 100);
  const mult = (1 + totalBonus).toFixed(2);

  if ($("#mod-sum-count"))
    $("#mod-sum-count").textContent = `${activeSupported.length} / ${supportedMods.length} SUPPORTED`;
  if ($("#mod-sum-bonus"))
    $("#mod-sum-bonus").textContent = `+${bonusPct}% COINS (${mult}x)`;
  if ($("#mod-foot-note"))
    $("#mod-foot-note").textContent = `${activeSupported.length} modifiers will be voted in match lobby`;
}

function renderModCatalog() {
  const cat = $("#mod-catalog");
  if (!cat) return;

  cat.innerHTML = MODIFIERS_CATALOG.map((m) => {
    const isSelected = modalSelectedModifiers.some(
      (sm) => normalizeModName(sm) === m.id
    );
    const cls = [
      "mod-card",
      isSelected ? "selected" : "",
      !m.supported ? "disabled" : "",
    ]
      .filter(Boolean)
      .join(" ");

    const statusBadge = m.supported
      ? `<span class="mod-card-status ready">READY</span>`
      : `<span class="mod-card-status soon">COMING SOON</span>`;

    return `
      <div class="${cls}" data-id="${m.id}" data-supported="${m.supported}">
        <div class="mod-card-top">
          <div class="mod-card-icon-wrap"><svg class="ico"><use href="${m.icon}"/></svg></div>
          <div class="grow"></div>
          ${statusBadge}
          <div class="mod-card-check"><svg class="ico"><use href="#i-check"/></svg></div>
        </div>
        <div class="mod-card-info">
          <div class="mod-card-title">
            <b>${esc(m.name)}</b>
            <span class="mod-card-bonus">${m.multiplier}</span>
          </div>
          <div class="mod-card-desc">${esc(m.desc)}</div>
        </div>
      </div>
    `;
  }).join("");

  updateModModalStats();
}

function openModifiersModal() {
  modalSelectedModifiers = [...selectedModifiers];
  renderModCatalog();
  $("#mod-modal-scrim").hidden = false;
}

function closeModifiersModal() {
  $("#mod-modal-scrim").hidden = true;
}

$("#btn-open-modifiers")?.addEventListener("click", openModifiersModal);
$("#mod-modal-close")?.addEventListener("click", closeModifiersModal);
$("#mod-btn-cancel")?.addEventListener("click", closeModifiersModal);
$("#mod-modal-scrim")?.addEventListener("mousedown", (e) => {
  if (e.target.id === "mod-modal-scrim") closeModifiersModal();
});

$("#mod-catalog")?.addEventListener("click", (e) => {
  const card = e.target.closest(".mod-card");
  if (!card) return;
  const modId = card.dataset.id;
  const isSupported = card.dataset.supported === "true";
  if (!isSupported) {
    toast("Modifier calibration pending in upcoming game update.");
    return;
  }

  const def = MODIFIERS_CATALOG.find((m) => m.id === modId);
  if (!def) return;

  const idx = modalSelectedModifiers.findIndex(
    (sm) => normalizeModName(sm) === modId
  );
  if (idx >= 0) {
    modalSelectedModifiers.splice(idx, 1);
  } else {
    modalSelectedModifiers.push(def.name);
  }

  renderModCatalog();
});

$("#mod-act-select-all")?.addEventListener("click", () => {
  const supported = MODIFIERS_CATALOG.filter((m) => m.supported).map(
    (m) => m.name
  );
  modalSelectedModifiers = supported;
  renderModCatalog();
});

$("#mod-act-clear")?.addEventListener("click", () => {
  modalSelectedModifiers = [];
  renderModCatalog();
});

$("#mod-btn-apply")?.addEventListener("click", async () => {
  selectedModifiers = [...modalSelectedModifiers];
  closeModifiersModal();
  const enabled = $("#set-modifiers-enabled")
    ? $("#set-modifiers-enabled").checked
    : true;
  renderModifiersRow(enabled);
  await api.save_settings(collect());
  toast(`Saved modifiers: ${selectedModifiers.join(", ") || "None"}`);
});

/* -------------------------------------------------------------- settings */
function updateBpBadge(enabled) {
  const badge = $("#bp-active-badge");
  if (!badge) return;
  badge.textContent = enabled ? "ACTIVE" : "OFF";
  badge.className = "badge " + (enabled ? "" : "off");
}

async function loadSettings() {
  const s = await api.get_settings();
  if ($("#set-play-again")) $("#set-play-again").checked = Boolean(s.use_play_again);
  if ($("#set-verify")) $("#set-verify").checked = Boolean(s.verify_scout_once);
  const bpEnabled = Boolean(s.battlepass_farm);
  if ($("#set-battlepass-farm")) $("#set-battlepass-farm").checked = bpEnabled;
  updateBpBadge(bpEnabled);
  if ($("#set-show-hud")) $("#set-show-hud").checked = Boolean(s.show_hud);
  if ($("#set-modifiers-enabled")) $("#set-modifiers-enabled").checked = Boolean(s.enable_modifiers !== false);
  if (Array.isArray(s.modifiers)) {
    selectedModifiers = s.modifiers;
  }
  renderModifiersRow($("#set-modifiers-enabled") ? $("#set-modifiers-enabled").checked : true);

  if ($("#set-url")) $("#set-url").value = s.webhook_url || "";
  if ($("#set-on-win")) $("#set-on-win").checked = Boolean(s.webhook_on_triumph);
  if ($("#set-on-loss")) $("#set-on-loss").checked = Boolean(s.webhook_on_defeat);
  if ($("#set-on-error")) $("#set-on-error").checked = Boolean(s.webhook_on_error);
  if ($("#set-on-hourly")) $("#set-on-hourly").checked = Boolean(s.webhook_hourly);

  // Set hotkeys
  currentHotkeys.start = s.hotkey_start || "F1";
  currentHotkeys.pause = s.hotkey_pause || "F2";
  currentHotkeys.stop = s.hotkey_stop || "F3";
  currentHotkeys.overlay = s.hotkey_overlay || "F7";
  renderKeycaps();
}

const collect = () => ({
  use_play_again: $("#set-play-again") ? $("#set-play-again").checked : true,
  verify_scout_once: $("#set-verify") ? $("#set-verify").checked : true,
  battlepass_farm: $("#set-battlepass-farm") ? $("#set-battlepass-farm").checked : false,
  enable_modifiers: $("#set-modifiers-enabled") ? $("#set-modifiers-enabled").checked : true,
  modifiers: selectedModifiers,
  show_hud: $("#set-show-hud") ? $("#set-show-hud").checked : false,
  webhook_url: $("#set-url") ? $("#set-url").value.trim() : "",
  webhook_on_triumph: $("#set-on-win") ? $("#set-on-win").checked : true,
  webhook_on_defeat: $("#set-on-loss") ? $("#set-on-loss").checked : true,
  webhook_on_error: $("#set-on-error") ? $("#set-on-error").checked : true,
  webhook_hourly: $("#set-on-hourly") ? $("#set-on-hourly").checked : true,
  hotkey_start: currentHotkeys.start,
  hotkey_pause: currentHotkeys.pause,
  hotkey_stop: currentHotkeys.stop,
  hotkey_overlay: currentHotkeys.overlay,
});

["#set-play-again", "#set-verify", "#set-on-win", "#set-on-loss", "#set-on-error", "#set-on-hourly"].forEach((id) => {
  const el = $(id);
  if (el) el.addEventListener("change", () => api.save_settings(collect()));
});

$("#set-battlepass-farm")?.addEventListener("change", async (e) => {
  updateBpBadge(e.target.checked);
  await api.save_settings(collect());
  toast(e.target.checked ? "Battlepass Farm enabled (auto-sweeps dropped tokens)." : "Battlepass Farm disabled.");
});

$("#set-modifiers-enabled")?.addEventListener("change", async (e) => {
  renderModifiersRow(e.target.checked);
  await api.save_settings(collect());
  toast(e.target.checked ? "Game modifiers enabled." : "Game modifiers disabled (Vanilla match).");
});

$("#set-show-hud")?.addEventListener("change", async (e) => {
  const data = collect();
  await api.save_settings(data);
  api.set_hud_visible(e.target.checked);
  toast(e.target.checked ? "In-game HUD enabled." : "In-game HUD hidden.");
});

const whStatus = (msg, cls = "") => { const el = $("#wh-status"); el.textContent = msg; el.className = "inline-status " + cls; };
$("#wh-save").addEventListener("click", async () => {
  const url = $("#set-url").value.trim();
  if (url && !url.startsWith("https://discord.com/api/webhooks/")) return whStatus("That is not a Discord webhook URL.", "err");
  await api.save_settings(collect());
  whStatus(url ? "Saved." : "Webhook removed.", "ok");
  refresh();
});
$("#wh-test").addEventListener("click", async () => {
  const url = $("#set-url").value.trim();
  if (!url) return whStatus("Enter a webhook URL first.", "err");
  whStatus("Sending…");
  await api.save_settings(collect());
  const r = await api.test_webhook(url);
  whStatus(r.ok ? "Test message delivered." : r.message, r.ok ? "ok" : "err");
  refresh();
});
$("#reset-progress").addEventListener("click", async () => {
  if (state.status !== "IDLE") return toast("Stop the macro first.");
  await api.reset_progress();
  toast("Queue progress reset.");
  refresh();
});

/* ---------------------------------------------------------- window chrome */
$("#wc-min").addEventListener("click", () => api.win_minimize());
$("#wc-max").addEventListener("click", () => api.win_maximize());
$("#wc-close").addEventListener("click", () => api.win_close());

/* ------------------------------------------------------------------ loop */
async function refresh() {
  state = await api.get_state();
  const sig = JSON.stringify(state.tasks) + state.wave + state.status;
  if (sig !== taskSig && !dragEl) { taskSig = sig; renderQueue(); }
  updateDock();
  if (view === "live") renderLive();
}
async function tick() {
  try { await refresh(); if (view === "live") await loadLog(); } catch (e) { /* window closing */ }
  setTimeout(tick, 700);
}
window.addEventListener("pywebviewready", async () => {
  api = window.pywebview.api;
  presets = await api.presets();
  await loadSettings();
  await refresh();
  switchView("queue");
  tick();
});
