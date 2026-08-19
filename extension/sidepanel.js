const DEFAULT_API_URL = "https://yt-rag-477224356188.asia-south2.run.app";

const state = {
  apiUrl: DEFAULT_API_URL,
  videoId: null,
};

const el = {
  settingsToggle: document.getElementById("settings-toggle"),
  settingsPanel: document.getElementById("settings-panel"),
  apiUrlInput: document.getElementById("api-url"),
  saveSettings: document.getElementById("save-settings"),
  videoUrl: document.getElementById("video-url"),
  loadBtn: document.getElementById("load-btn"),
  videoStatus: document.getElementById("video-status"),
  chatWindow: document.getElementById("chat-window"),
  question: document.getElementById("question"),
  sendBtn: document.getElementById("send-btn"),
};

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// Minimal markdown -> HTML: bold, italics, bullet/numbered lists, paragraphs.
function renderMarkdown(text) {
  const lines = escapeHtml(text).split("\n");
  const htmlParts = [];
  let listItems = [];
  let listTag = null;

  function flushList() {
    if (listItems.length) {
      htmlParts.push(`<${listTag}>${listItems.join("")}</${listTag}>`);
      listItems = [];
      listTag = null;
    }
  }

  function inline(s) {
    return s
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*(?!\*)(.+?)\*(?!\*)/g, "$1<em>$2</em>");
  }

  for (const rawLine of lines) {
    const line = rawLine.trim();
    const bulletMatch = line.match(/^[*-]\s+(.*)/);
    const numberedMatch = line.match(/^\d+\.\s+(.*)/);

    if (bulletMatch) {
      if (listTag !== "ul") { flushList(); listTag = "ul"; }
      listItems.push(`<li>${inline(bulletMatch[1])}</li>`);
    } else if (numberedMatch) {
      if (listTag !== "ol") { flushList(); listTag = "ol"; }
      listItems.push(`<li>${inline(numberedMatch[1])}</li>`);
    } else {
      flushList();
      if (line) htmlParts.push(`<p>${inline(line)}</p>`);
    }
  }
  flushList();

  return htmlParts.join("");
}

function addBubble(role, text) {
  const bubble = document.createElement("div");
  bubble.className = `bubble ${role}`;
  if (role === "assistant") {
    bubble.innerHTML = renderMarkdown(text);
  } else {
    bubble.textContent = text;
  }
  el.chatWindow.appendChild(bubble);
  el.chatWindow.scrollTop = el.chatWindow.scrollHeight;
  return bubble;
}

async function init() {
  const stored = await chrome.storage.sync.get(["apiUrl"]);
  state.apiUrl = stored.apiUrl || DEFAULT_API_URL;
  el.apiUrlInput.value = state.apiUrl;

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab && tab.url && /youtube\.com\/watch\?.*v=/.test(tab.url)) {
    el.videoUrl.value = tab.url;
  }
}

el.settingsToggle.addEventListener("click", () => {
  el.settingsPanel.classList.toggle("hidden");
});

el.saveSettings.addEventListener("click", async () => {
  const url = el.apiUrlInput.value.trim().replace(/\/$/, "");
  if (!url) return;
  state.apiUrl = url;
  await chrome.storage.sync.set({ apiUrl: url });
  el.settingsPanel.classList.add("hidden");
});

el.loadBtn.addEventListener("click", async () => {
  const url = el.videoUrl.value.trim();
  if (!url) return;

  el.loadBtn.disabled = true;
  el.videoStatus.textContent = "Loading video...";

  try {
    const res = await fetch(`${state.apiUrl}/videos`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();
    state.videoId = data.video_id;
    el.videoStatus.textContent = `Video ID: ${state.videoId} indexed successfully.`;
  } catch (e) {
    el.videoStatus.textContent = `Error: ${e.message}`;
  } finally {
    el.loadBtn.disabled = false;
  }
});

async function sendMessage() {
  const question = el.question.value.trim();
  if (!question || !state.videoId) return;

  addBubble("user", question);
  el.question.value = "";
  el.sendBtn.disabled = true;

  const assistantBubble = addBubble("assistant", "...");

  try {
    const res = await fetch(`${state.apiUrl}/ask/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_id: state.videoId, query: question }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let answer = "";
    assistantBubble.innerHTML = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      answer += decoder.decode(value, { stream: true });
      assistantBubble.innerHTML = renderMarkdown(answer);
      el.chatWindow.scrollTop = el.chatWindow.scrollHeight;
    }
  } catch (e) {
    assistantBubble.textContent = `Error: ${e.message}`;
  } finally {
    el.sendBtn.disabled = false;
  }
}

el.sendBtn.addEventListener("click", sendMessage);
el.question.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});

init();
