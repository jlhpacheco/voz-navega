// Voz Navega — frontend (wave 2).
// Patient voice screen + navigator panel, built against the contract in
// ARCHITECTURE.md §2.2: POST /api/sessions, POST /api/sessions/{id}/turns,
// GET /api/sessions, GET /api/sessions/{id},
// POST /api/sessions/{id}/verify-resource, POST .../approve,
// POST .../edit-summary (409 gate semantics per §3.3).
// If the sessions API is not live yet, the page falls back to the
// scaffold's POST /api/turn so it never opens dead.

"use strict";

const APPROVER = "Elena — Synthetic Demo Navigator";
const CRISIS_DEFAULT =
  "🚨 If this is an emergency, call 911 now — or call your care team.";

const BARRIER_LABELS = {
  transport: "Getting a ride",
  cost: "Cost of care",
  childcare: "Childcare",
  work_schedule: "Work schedule",
  fear: "Fear / worry",
  language: "Language",
  health_literacy: "Understanding the care",
  other: "Other hard part",
};

const STAGE_LABELS = {
  GREETING: "Saying hello",
  INTAKE: "Listening to your concern",
  DISCOVERY: "Asking about your day-to-day",
  EXPLAIN: "Explaining in plain words",
  QUESTIONS: "Building your doctor questions",
  RESOURCES: "Finding help for the hard parts",
  HANDOFF: "With your navigator for review",
  PENDING_APPROVAL: "Waiting for your navigator",
  APPROVED_SENT: "Approved and sent",
  CLOSED: "All done",
  ESCALATED: "Stopped — a human will help",
};

const $ = (id) => document.getElementById(id);
const els = {
  orbBtn: $("orbBtn"), orbState: $("orbState"), orbHint: $("orbHint"),
  stageChip: $("stageChip"), transcript: $("transcript"),
  textForm: $("textForm"), textInput: $("textInput"), sendBtn: $("sendBtn"),
  muteBtn: $("muteBtn"), crisisBanner: $("crisisBanner"),
  crisisText: $("crisisText"),
  barrierChips: $("barrierChips"), barrierEmpty: $("barrierEmpty"),
  questionList: $("questionList"), questionEmpty: $("questionEmpty"),
  resourceList: $("resourceList"), resourceEmpty: $("resourceEmpty"),
  replayEn: $("replayEn"), replayEs: $("replayEs"),
  stopReplay: $("stopReplay"), replayNote: $("replayNote"),
  navQueue: $("navQueue"), navRefresh: $("navRefresh"),
  navSessionMeta: $("navSessionMeta"), navEscalated: $("navEscalated"),
  summaryText: $("summaryText"), summaryEdit: $("summaryEdit"),
  editSummaryBtn: $("editSummaryBtn"), saveSummaryBtn: $("saveSummaryBtn"),
  summaryMsg: $("summaryMsg"), navResources: $("navResources"),
  navResourcesEmpty: $("navResourcesEmpty"), approveBtn: $("approveBtn"),
  gateMsg: $("gateMsg"), approvedBox: $("approvedBox"),
  approvedBy: $("approvedBy"),
};

const S = {
  sessionId: null,
  session: null,      // last full session snapshot
  legacy: false,      // true when only the scaffold /api/turn answers
  lang: "en",
  state: "GREETING",
  crisis: false,
  crisisFor: null,    // session id the crisis lock belongs to
  muted: false,
  greetingText: "",
  greetingSpoken: false,
  playing: false,
  playTimer: null,
};

// ---------- HTTP ----------
async function api(path, opts) {
  try {
    const res = await fetch(path, opts);
    let data = null;
    try { data = await res.json(); } catch (e) { /* empty body */ }
    return { ok: res.ok, status: res.status, data };
  } catch (err) {
    return { ok: false, status: 0, data: null };
  }
}
function postJSON(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}
function detailOf(data, fallback) {
  if (!data) return fallback;
  if (typeof data.detail === "string") return data.detail;
  if (typeof data.message === "string") return data.message;
  if (typeof data.error === "string") return data.error;
  return fallback;
}

// ---------- Speech out (browser SpeechSynthesis) ----------
let voices = [];
function loadVoices() {
  if ("speechSynthesis" in window) voices = window.speechSynthesis.getVoices();
}
if ("speechSynthesis" in window) {
  loadVoices();
  window.speechSynthesis.onvoiceschanged = loadVoices;
}
function setOrb(label, mode) {
  els.orbState.textContent = label;
  els.orbBtn.classList.toggle("listening", mode === "listening");
  els.orbBtn.classList.toggle("speaking", mode === "speaking");
}
function speak(text, lang) {
  if (S.muted || !text || !("speechSynthesis" in window)) return;
  const target = (lang || S.lang) === "es" ? "es" : "en";
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = target === "es" ? "es-US" : "en-US";
  u.rate = 0.95;
  const v = voices.find((x) => x.lang && x.lang.toLowerCase().startsWith(target));
  if (v) u.voice = v;
  u.onstart = () => {
    setOrb("Speaking", "speaking");
    if (text === S.greetingText) S.greetingSpoken = true;
  };
  u.onend = () => setOrb("Idle", "idle");
  window.speechSynthesis.speak(u);
}
// Browsers may hold speech until the first touch — retry the greeting then.
window.addEventListener("pointerdown", () => {
  if (!S.greetingSpoken && S.greetingText && !S.playing) {
    speak(S.greetingText, S.lang);
  }
});

// ---------- Rendering ----------
function turnText(t) {
  if (typeof t === "string") return t;
  return (t && (t.text || t.reply)) || "";
}
function isPatientTurn(t) {
  if (!t || typeof t === "string") return false;
  const sp = (t.speaker || t.role || "").toLowerCase();
  return sp === "patient" || sp === "user" || sp === "you";
}
function bubbleEl(t) {
  const text = turnText(t);
  const patient = isPatientTurn(t);
  const div = document.createElement("div");
  div.className = "bubble " + (patient ? "patient" : "companion");
  const who = document.createElement("span");
  who.className = "who";
  who.textContent = patient ? "You" : "Voz Navega";
  div.appendChild(who);
  div.appendChild(document.createTextNode(text));
  const gloss = t && typeof t === "object" ? t.gloss : null;
  if (gloss && gloss.trim() && gloss.trim() !== text.trim()) {
    const g = document.createElement("span");
    g.className = "gloss";
    g.textContent = gloss;
    div.appendChild(g);
  }
  return div;
}
function renderTranscript(turns) {
  els.transcript.innerHTML = "";
  (turns || []).forEach((t) => {
    if (turnText(t)) els.transcript.appendChild(bubbleEl(t));
  });
  const last = els.transcript.lastElementChild;
  if (last) last.scrollIntoView({ block: "end" });
}
function addLooseBubble(patient, text, gloss) {
  const t = { speaker: patient ? "patient" : "companion", text, gloss };
  els.transcript.appendChild(bubbleEl(t));
  const last = els.transcript.lastElementChild;
  if (last) last.scrollIntoView({ block: "end" });
}
function resourceName(r) {
  if (typeof r === "string") return r;
  return (r && (r.name || r.title || r.type)) || "Resource";
}

function renderPanels(src) {
  const barriers = (src && src.barriers_found) || [];
  els.barrierChips.innerHTML = "";
  els.barrierEmpty.style.display = barriers.length ? "none" : "";
  barriers.forEach((b) => {
    const name = typeof b === "string" ? b : b.barrier || b.name || "other";
    const chip = document.createElement("div");
    chip.className = "chip";
    const nm = document.createElement("span");
    nm.className = "chip-name";
    nm.textContent = BARRIER_LABELS[name] || name;
    chip.appendChild(nm);
    const by = b && typeof b === "object" ? b.confirmed_by : null;
    const tag = document.createElement("span");
    tag.className = "chip-tag" + (by === "probe" ? " probe" : "");
    tag.textContent = by === "probe" ? "We found it by asking" : "You told me";
    chip.appendChild(tag);
    const ev = b && typeof b === "object" ? b.evidence || b.quote : null;
    if (ev) {
      const w = document.createElement("span");
      w.className = "chip-why";
      w.textContent = "“" + ev + "”";
      chip.appendChild(w);
    }
    els.barrierChips.appendChild(chip);
  });
  const qs = (src && src.question_list) || [];
  els.questionList.innerHTML = "";
  els.questionEmpty.style.display = qs.length ? "none" : "";
  qs.forEach((q) => {
    const li = document.createElement("li");
    li.textContent = typeof q === "string" ? q : q.text || q.question || "";
    els.questionList.appendChild(li);
  });
  const rs = (src && src.resources) || [];
  els.resourceList.innerHTML = "";
  els.resourceEmpty.style.display = rs.length ? "none" : "";
  rs.forEach((r) => {
    const li = document.createElement("li");
    const nm = document.createElement("span");
    nm.className = "r-name";
    nm.textContent = resourceName(r);
    const st = document.createElement("span");
    st.className = "r-state" + (r && r.verified ? " ok" : "");
    st.textContent =
      r && r.verified ? "✓ Checked by your navigator" : "Your navigator checks this first";
    li.appendChild(nm);
    li.appendChild(st);
    els.resourceList.appendChild(li);
  });
}

function summaryString(sum) {
  if (!sum) return "";
  if (typeof sum === "string") return sum;
  if (typeof sum.text === "string") return sum.text;
  if (typeof sum.summary === "string") return sum.summary;
  const parts = [];
  ["concern", "explanation", "barriers", "questions", "resources", "notes"]
    .forEach((k) => {
      if (sum[k]) {
        parts.push(k + ": " + (Array.isArray(sum[k]) ? sum[k].join("; ") : sum[k]));
      }
    });
  return parts.length ? parts.join("\n") : JSON.stringify(sum, null, 2);
}
function isApproved(sess) {
  return !!(
    sess &&
    (sess.approval_record ||
      sess.state === "APPROVED_SENT" ||
      sess.approval_status === "APPROVED_SENT")
  );
}
function handoffReady(sess) {
  if (!sess) return false;
  return (
    sess.approval_status === "PENDING_APPROVAL" ||
    !!summaryString(sess.summary) ||
    sess.state === "PENDING_APPROVAL" ||
    sess.state === "HANDOFF"
  );
}
function updateApproveGate(sess) {
  const btn = els.approveBtn;
  const msg = els.gateMsg;
  btn.disabled = true;
  msg.classList.remove("error");
  if (!sess) {
    msg.textContent =
      "Approve unlocks when the handoff is ready and every offered resource is verified.";
    return;
  }
  if (sess.state === "ESCALATED") {
    msg.textContent =
      "This case went straight to a human. The system cannot approve it.";
    return;
  }
  if (isApproved(sess)) {
    msg.textContent = "Already approved and sent.";
    return;
  }
  if (!handoffReady(sess)) {
    msg.textContent =
      "Waiting for the conversation to reach handoff — the summary appears here first.";
    return;
  }
  const left = (sess.resources || []).filter((r) => !(r && r.verified)).length;
  if (left > 0) {
    msg.textContent =
      "Verify every offered resource first — " + left + " still unverified.";
    return;
  }
  btn.disabled = false;
  msg.textContent =
    "Ready: every resource is verified. Approving sends the handoff as final.";
}

function renderNavigator(sess) {
  if (!sess) {
    els.navSessionMeta.textContent = S.legacy
      ? "Navigator panel connects when the session service is live."
      : "No session loaded yet.";
    updateApproveGate(null);
    return;
  }
  els.navSessionMeta.textContent =
    "Case " + (sess.id || S.sessionId || "") +
    " · Stage: " + (STAGE_LABELS[sess.state] || sess.state || "—") +
    " · Fictional demo patient";
  els.navEscalated.hidden = sess.state !== "ESCALATED";
  if (els.summaryEdit.hidden) {
    const sum = summaryString(sess.summary);
    els.summaryText.textContent =
      sum || "No summary yet — it appears when the conversation reaches handoff.";
  }
  els.editSummaryBtn.hidden = !(
    summaryString(sess.summary) &&
    sess.state !== "ESCALATED" &&
    !isApproved(sess)
  );
  const rs = sess.resources || [];
  els.navResources.innerHTML = "";
  els.navResourcesEmpty.style.display = rs.length ? "none" : "";
  rs.forEach((r, i) => {
    const li = document.createElement("li");
    const nm = document.createElement("span");
    nm.className = "r-name";
    nm.textContent = resourceName(r);
    li.appendChild(nm);
    const row = document.createElement("div");
    row.className = "r-actions";
    if (r && r.verified) {
      const ok = document.createElement("span");
      ok.className = "r-verified";
      ok.textContent = "✓ Verified by the navigator";
      row.appendChild(ok);
    } else {
      const st = document.createElement("span");
      st.className = "r-unverified";
      st.textContent = "Not verified yet";
      row.appendChild(st);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "verify-btn";
      btn.textContent = "Verify — I checked this resource";
      btn.disabled = sess.state === "ESCALATED" || isApproved(sess);
      btn.addEventListener("click", () => verifyResource(r, i, btn));
      row.appendChild(btn);
    }
    li.appendChild(row);
    els.navResources.appendChild(li);
  });
  const ap = sess.approval_record;
  if (isApproved(sess)) {
    els.approvedBox.hidden = false;
    const by = (ap && ap.by) || APPROVER;
    const at = ap && ap.at ? " · " + ap.at : "";
    els.approvedBy.textContent =
      "Approved by " + by + at +
      (by === APPROVER ? " (synthetic demo navigator)" : "");
  } else {
    els.approvedBox.hidden = true;
  }
  updateApproveGate(sess);
}

// ---------- Crisis ----------
function enterCrisis(banner) {
  if (S.crisis) return;
  S.crisis = true;
  S.crisisFor = S.sessionId;
  let txt = "";
  if (typeof banner === "string") txt = banner;
  else if (banner && typeof banner === "object") txt = banner.text || banner.title || "";
  els.crisisText.textContent = txt && txt.trim() ? txt : CRISIS_DEFAULT;
  els.crisisBanner.hidden = false;
  els.textInput.disabled = true;
  els.sendBtn.disabled = true;
  els.orbBtn.disabled = true;
  setOrb("Stopped", "idle");
  els.orbHint.textContent =
    "This conversation has stopped. A human navigator will help from here.";
  if (recognizer) {
    try { recognizer.stop(); } catch (e) { /* not listening */ }
  }
  els.crisisBanner.scrollIntoView({ block: "start" });
}
function leaveCrisis() {
  S.crisis = false;
  S.crisisFor = null;
  els.crisisBanner.hidden = true;
  els.textInput.disabled = false;
  els.sendBtn.disabled = false;
  els.orbBtn.disabled = false;
  els.orbHint.textContent = "Tap the orb and speak — or type below.";
  setOrb("Idle", "idle");
}

// ---------- Session state ----------
function applySession(sess) {
  if (!sess) return;
  S.session = sess;
  if (sess.id) S.sessionId = sess.id;
  if (sess.language) {
    S.lang = sess.language === "es" ? "es" : "en";
    if (recognizer) recognizer.lang = S.lang === "es" ? "es-US" : "en-US";
  }
  if (sess.state) S.state = sess.state;
  els.stageChip.textContent = STAGE_LABELS[S.state] || S.state;
  renderTranscript(sess.turns || []);
  renderPanels(sess);
  renderNavigator(sess);
  if (sess.state === "ESCALATED") {
    enterCrisis(sess.banner);
  } else if (S.crisis && sess.id !== S.crisisFor) {
    leaveCrisis();
  }
}
async function refreshSession() {
  if (!S.sessionId) return null;
  const r = await api("/api/sessions/" + encodeURIComponent(S.sessionId));
  if (r.ok && r.data) {
    const sess = r.data.session || r.data;
    applySession(sess);
    return sess;
  }
  return null;
}

// ---------- Actions ----------
let sending = false;
async function sendTurn(text) {
  const heard = (text || "").trim();
  if (!heard || S.crisis || S.playing || sending) return;
  sending = true;
  setOrb("Thinking", "idle");
  try {
    if (S.legacy || !S.sessionId) {
      const r = await postJSON("/api/turn", { text: heard });
      const d = r.data || {};
      addLooseBubble(true, heard);
      const reply = d.reply || "";
      if (reply) addLooseBubble(false, reply);
      if (d.state === "ESCALATED" || d.banner) {
        enterCrisis(d.banner);
        if (reply) speak(reply, S.lang);
      } else if (reply) {
        speak(reply, S.lang);
      }
      return;
    }
    const r = await postJSON(
      "/api/sessions/" + encodeURIComponent(S.sessionId) + "/turns",
      { text: heard }
    );
    if (!r.ok) {
      els.orbHint.textContent = "That did not go through — please try again.";
      return;
    }
    const d = r.data || {};
    const ct = d.companion_turn;
    const ctext =
      typeof ct === "string" ? ct : (ct && ct.text) || d.reply || "";
    if (d.state) {
      S.state = d.state;
      els.stageChip.textContent = STAGE_LABELS[d.state] || d.state;
    }
    if (d.language) S.lang = d.language === "es" ? "es" : "en";
    if (d.barriers_found || d.question_list || d.resources) renderPanels(d);
    // Escalation first, with the server's own banner text, before the
    // session refresh re-renders (applySession would use the default).
    if (d.state === "ESCALATED" || d.banner) enterCrisis(d.banner);
    const fresh = await refreshSession();
    if (!fresh) {
      addLooseBubble(true, heard);
      if (ctext) addLooseBubble(false, ctext, ct && ct.gloss);
    }
    if (ctext) speak(ctext, S.lang);
  } finally {
    sending = false;
    if (!S.crisis) setOrb("Idle", "idle");
  }
}

async function verifyResource(r, i, btn) {
  if (!S.sessionId) return;
  btn.disabled = true;
  const body = { resource: resourceName(r), name: resourceName(r), index: i };
  if (r && typeof r === "object") {
    if (r.type) body.type = r.type;
    if (r.barrier) body.barrier = r.barrier;
    if (r.id) body.resource_id = r.id;
  }
  const res = await postJSON(
    "/api/sessions/" + encodeURIComponent(S.sessionId) + "/verify-resource",
    body
  );
  if (!res.ok) {
    els.gateMsg.textContent =
      "Could not verify — " +
      detailOf(res.data, "the server refused (HTTP " + res.status + ").");
    els.gateMsg.classList.add("error");
    btn.disabled = false;
    return;
  }
  await refreshSession();
}

async function approve() {
  if (!S.sessionId || !S.session) return;
  els.approveBtn.disabled = true;
  const preTurns = S.session.turns ? S.session.turns.length : 0;
  const res = await postJSON(
    "/api/sessions/" + encodeURIComponent(S.sessionId) + "/approve",
    { by: APPROVER }
  );
  if (!res.ok) {
    // Restore the button from the local snapshot first — the server's
    // reason is written LAST so the gate recompute cannot clobber it.
    updateApproveGate(S.session);
    els.gateMsg.textContent =
      "Not approved — " +
      detailOf(res.data, "the server refused (HTTP " + res.status + ").");
    els.gateMsg.classList.add("error");
    return;
  }
  const fresh = await refreshSession();
  if (!fresh && res.data) applySession(res.data.session || res.data);
  if (fresh && fresh.turns && fresh.turns.length > preTurns) {
    const news = fresh.turns.slice(preTurns).filter((t) => !isPatientTurn(t));
    const last = news[news.length - 1];
    if (last && turnText(last)) speak(turnText(last), S.lang);
  }
}
els.approveBtn.addEventListener("click", approve);

els.editSummaryBtn.addEventListener("click", () => {
  if (!S.session) return;
  els.summaryEdit.value = summaryString(S.session.summary);
  els.summaryEdit.hidden = false;
  els.summaryText.style.display = "none";
  els.saveSummaryBtn.hidden = false;
  els.editSummaryBtn.hidden = true;
  els.summaryMsg.textContent = "";
});
els.saveSummaryBtn.addEventListener("click", async () => {
  if (!S.sessionId) return;
  const text = els.summaryEdit.value;
  const res = await postJSON(
    "/api/sessions/" + encodeURIComponent(S.sessionId) + "/edit-summary",
    { summary: text, text }
  );
  if (!res.ok) {
    els.summaryMsg.textContent =
      "Could not save — " +
      detailOf(res.data, "the server refused (HTTP " + res.status + ").");
    return;
  }
  els.summaryEdit.hidden = true;
  els.summaryText.style.display = "";
  els.saveSummaryBtn.hidden = true;
  els.summaryMsg.textContent = "Edits saved.";
  await refreshSession();
});

// ---------- Navigator queue ----------
async function loadQueue() {
  const r = await api("/api/sessions");
  const list =
    r.ok && Array.isArray(r.data) ? r.data : (r.data && r.data.sessions) || [];
  els.navQueue.innerHTML = "";
  list.forEach((s) => {
    if (!s || !s.id) return;
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.type = "button";
    if (s.id === S.sessionId) b.className = "current";
    b.appendChild(document.createTextNode(s.id + " "));
    const st = document.createElement("span");
    st.className = "q-state" + (s.state === "ESCALATED" ? " esc" : "");
    st.textContent = s.state || "";
    b.appendChild(st);
    b.addEventListener("click", async () => {
      stopPlayback();
      const rr = await api("/api/sessions/" + encodeURIComponent(s.id));
      if (rr.ok && rr.data) applySession(rr.data.session || rr.data);
    });
    li.appendChild(b);
    els.navQueue.appendChild(li);
  });
  return list;
}
els.navRefresh.addEventListener("click", async () => {
  await refreshSession();
  await loadQueue();
});

// ---------- Golden replay ----------
function findGolden(list, lang) {
  const all = (list || []).filter((s) => s && s.id);
  const tagged = all.filter(
    (s) =>
      s.golden ||
      s.seeded ||
      s.replay ||
      /golden|replay|seed/i.test(String(s.id || ""))
  );
  // The seeded golden session is a completed walk to HANDOFF — prefer
  // advanced, well-filled sessions over a visitor's fresh greeting.
  const advanced = all.filter(
    (s) =>
      ["HANDOFF", "PENDING_APPROVAL", "APPROVED_SENT", "CLOSED"].includes(
        s.state
      ) || (s.turns_count || 0) >= 6
  );
  const pools = [tagged, advanced, all];
  for (const pool of pools) {
    if (!pool.length) continue;
    const hit = pool.find((s) => (s.language || "") === lang);
    if (hit) return hit;
    if (lang === "en") {
      const en = pool.find((s) => !s.language || s.language === "en");
      if (en) return en;
    }
  }
  return null;
}
function stopPlayback() {
  S.playing = false;
  if (S.playTimer) clearTimeout(S.playTimer);
  S.playTimer = null;
  els.stopReplay.hidden = true;
}
async function startReplay(lang) {
  if (S.playing) return;
  const list = await loadQueue();
  const g = findGolden(list, lang);
  if (!g) {
    els.replayNote.textContent =
      "The golden replay is not loaded in this demo yet.";
    return;
  }
  const r = await api("/api/sessions/" + encodeURIComponent(g.id));
  const sess = r.ok && r.data ? r.data.session || r.data : g;
  const turns = sess.turns || [];
  if (!turns.length) {
    els.replayNote.textContent = "That replay has no turns to play.";
    return;
  }
  S.playing = true;
  els.stopReplay.hidden = false;
  els.replayNote.textContent =
    "Playing the golden conversation (" +
    (lang === "es" ? "Spanish" : "English") +
    ")…";
  els.transcript.innerHTML = "";
  renderPanels({});
  let i = 0;
  const step = () => {
    if (!S.playing) return;
    if (i >= turns.length) {
      stopPlayback();
      applySession(sess);
      els.replayNote.textContent =
        "Replay finished — the full case is in the navigator panel.";
      return;
    }
    const t = turns[i++];
    if (turnText(t)) {
      els.transcript.appendChild(bubbleEl(t));
      const last = els.transcript.lastElementChild;
      if (last) last.scrollIntoView({ block: "end" });
    }
    if (!isPatientTurn(t) && turnText(t)) {
      speak(turnText(t), sess.language || lang);
    }
    S.playTimer = setTimeout(step, 3200);
  };
  step();
}
els.replayEn.addEventListener("click", () => startReplay("en"));
els.replayEs.addEventListener("click", () => startReplay("es"));
els.stopReplay.addEventListener("click", stopPlayback);

// ---------- Voice input (progressive enhancement) ----------
const SpeechRecognition =
  window.SpeechRecognition || window.webkitSpeechRecognition;
let recognizer = null;
if (SpeechRecognition) {
  recognizer = new SpeechRecognition();
  recognizer.interimResults = true;
  recognizer.lang = "en-US";
  let finalText = "";
  recognizer.onstart = () => setOrb("Listening…", "listening");
  recognizer.onresult = (ev) => {
    let interim = "";
    for (let i = ev.resultIndex; i < ev.results.length; i++) {
      const res = ev.results[i];
      if (res.isFinal) finalText += res[0].transcript;
      else interim += res[0].transcript;
    }
    els.textInput.value = (finalText + " " + interim).trim();
  };
  recognizer.onend = () => {
    setOrb("Idle", "idle");
    if (finalText.trim()) {
      els.textInput.value = finalText.trim();
      els.orbHint.textContent =
        "I typed what you said — check it, then press Send.";
      els.textInput.focus();
    }
    finalText = "";
  };
  recognizer.onerror = (e) => {
    setOrb("Idle", "idle");
    if (e && e.error === "not-allowed") {
      els.orbHint.textContent =
        "The microphone is blocked — typing works just as well.";
    }
  };
} else {
  els.orbHint.textContent =
    "Voice input is not available in this browser — type below instead.";
}
els.orbBtn.addEventListener("click", () => {
  if (S.crisis) return;
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  if (recognizer) {
    try {
      recognizer.start();
    } catch (e) {
      /* already listening */
    }
  } else {
    els.textInput.focus();
  }
});

// ---------- Mute / composer ----------
els.muteBtn.addEventListener("click", () => {
  S.muted = !S.muted;
  els.muteBtn.textContent = S.muted ? "🔇 Voice off" : "🔊 Voice on";
  els.muteBtn.setAttribute("aria-pressed", String(S.muted));
  if (S.muted && "speechSynthesis" in window) window.speechSynthesis.cancel();
});
els.textForm.addEventListener("submit", (ev) => {
  ev.preventDefault();
  const text = els.textInput.value.trim();
  if (!text) return;
  els.textInput.value = "";
  sendTurn(text);
});

// ---------- Boot: a session starts on load, greeting first ----------
async function boot() {
  const r = await postJSON("/api/sessions", {});
  const payload = r.data && (r.data.session || r.data);
  if ((r.status === 201 || r.ok) && payload && (payload.id || r.data.session_id)) {
    if (r.data.session_id && !payload.id) payload.id = r.data.session_id;
    applySession(payload);
    const g = (payload.turns || []).find((t) => !isPatientTurn(t));
    if (g && turnText(g)) {
      S.greetingText = turnText(g);
      speak(S.greetingText, S.lang);
    }
    loadQueue();
    return;
  }
  // Sessions API not live yet — scaffold fallback (never opens dead).
  S.legacy = true;
  els.stageChip.textContent = "Demo (scaffold brain)";
  const hello =
    "Hello, I am Voz Navega, your voice companion. Tap the orb and tell " +
    "me what is on your mind about your next doctor visit.";
  S.greetingText = hello;
  addLooseBubble(false, hello);
  speak(hello, "en");
  renderNavigator(null);
}
boot();
