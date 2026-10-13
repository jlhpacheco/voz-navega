// Voz Navega — scaffold frontend (wave 1).
// Voice in: Web Speech API recognition (where available).
// Voice out: speechSynthesis. Every turn also posts to /api/turn (stub in
// wave 1, real companion engine in wave 2) and lands in the transcript.

"use strict";

const orbBtn = document.getElementById("orbBtn");
const orbState = document.getElementById("orbState");
const orbHint = document.getElementById("orbHint");
const transcript = document.getElementById("transcript");
const textForm = document.getElementById("textForm");
const textInput = document.getElementById("textInput");

function setState(label, mode) {
  orbState.textContent = label;
  orbBtn.classList.toggle("listening", mode === "listening");
  orbBtn.classList.toggle("speaking", mode === "speaking");
}

function addBubble(who, text) {
  const div = document.createElement("div");
  div.className = "bubble " + (who === "You" ? "patient" : "companion");
  const label = document.createElement("span");
  label.className = "who";
  label.textContent = who;
  div.appendChild(label);
  div.appendChild(document.createTextNode(text));
  transcript.appendChild(div);
  div.scrollIntoView({ behavior: "smooth", block: "end" });
}

function speak(text) {
  if (!("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = "en-US";
  utter.onstart = () => setState("Speaking", "speaking");
  utter.onend = () => setState("Idle", "idle");
  window.speechSynthesis.speak(utter);
}

async function sendTurn(text) {
  addBubble("You", text);
  setState("Thinking", "idle");
  try {
    const res = await fetch("/api/turn", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await res.json();
    addBubble("Voz Navega", data.reply);
    speak(data.reply);
  } catch (err) {
    addBubble("Voz Navega", "Sorry — I could not reach my brain just now. Please try again.");
    setState("Idle", "idle");
  }
}

// --- Voice input (progressive enhancement) ---
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognizer = null;

if (SpeechRecognition) {
  recognizer = new SpeechRecognition();
  recognizer.lang = "en-US";
  recognizer.interimResults = false;
  recognizer.onstart = () => setState("Listening…", "listening");
  recognizer.onresult = (event) => {
    const text = event.results[0][0].transcript;
    setState("Idle", "idle");
    if (text.trim()) sendTurn(text.trim());
  };
  recognizer.onerror = () => setState("Idle", "idle");
  recognizer.onend = () => {
    if (orbState.textContent.startsWith("Listening")) setState("Idle", "idle");
  };
} else {
  orbHint.textContent = "Voice input is not available in this browser — type below instead.";
}

orbBtn.addEventListener("click", () => {
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  if (recognizer) {
    try { recognizer.start(); } catch (e) { /* already listening */ }
  } else {
    textInput.focus();
  }
});

textForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = textInput.value.trim();
  if (!text) return;
  textInput.value = "";
  sendTurn(text);
});

// Greeting so the page never opens silent.
addBubble("Voz Navega",
  "Hello, I am Voz Navega, your voice companion. Tap the orb and tell me " +
  "what is on your mind about your next doctor visit.");
