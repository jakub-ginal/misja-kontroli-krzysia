const ui = {
  widgets: document.getElementById("widgets"),
  status: document.getElementById("status"),
  messageForm: document.getElementById("message-form"),
  messageInput: document.getElementById("message-input"),
  messageList: document.getElementById("message-list"),
};

const store = {
  config: null,
  charts: {},
  buffers: {},
  elements: {},
  maxPoints: 40,
  lastTimestamp: null,
};

async function fetchJSON(url, options) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.error || `HTTP ${response.status}`);
  }
  return body;
}

function buildChart(canvas, param) {
  return new Chart(canvas, {
    type: "line",
    data: {
      labels: [],
      datasets: [{
        label: param.label,
        data: [],
        borderColor: "#4ec9ff",
        backgroundColor: "rgba(78, 201, 255, 0.15)",
        fill: true,
        tension: 0.3,
        pointRadius: 0,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { display: false },
        y: { suggestedMin: param.min, suggestedMax: param.max },
      },
    },
  });
}

function createCard(param) {
  const card = document.createElement("article");
  card.className = "card";

  const title = document.createElement("h2");
  title.textContent = param.label + (param.unit ? ` (${param.unit})` : "");
  card.appendChild(title);

  if (param.widget === "chart") {
    const box = document.createElement("div");
    box.className = "chart-box";
    const canvas = document.createElement("canvas");
    box.appendChild(canvas);
    card.appendChild(box);
    store.charts[param.key] = buildChart(canvas, param);
  } else if (param.widget === "gauge") {
    const bar = document.createElement("div");
    bar.className = "gauge";
    const fill = document.createElement("div");
    fill.className = "gauge-fill";
    bar.appendChild(fill);
    const label = document.createElement("div");
    label.className = "gauge-value";
    card.append(bar, label);
    store.elements[param.key] = { fill, value: label };
  } else {
    const label = document.createElement("div");
    label.className = "big-value";
    card.appendChild(label);
    store.elements[param.key] = { value: label };
  }
  return card;
}

function renderConfig() {
  ui.widgets.innerHTML = "";
  store.charts = {};
  store.elements = {};
  store.buffers = {};
  for (const param of store.config.params) {
    store.buffers[param.key] = [];
    ui.widgets.appendChild(createCard(param));
  }
}

function updateWidget(param, value) {
  if (param.widget === "chart") {
    const chart = store.charts[param.key];
    const buffer = store.buffers[param.key];
    buffer.push(value);
    if (buffer.length > store.maxPoints) buffer.shift();
    chart.data.labels = buffer.map(() => "");
    chart.data.datasets[0].data = [...buffer];
    chart.update();
  } else if (param.widget === "gauge") {
    const element = store.elements[param.key];
    const min = param.min ?? 0;
    const max = param.max ?? 100;
    const percent = ((value - min) / (max - min)) * 100;
    element.fill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
    element.value.textContent = `${value} ${param.unit ?? ""}`.trim();
  } else {
    store.elements[param.key].value.textContent = value;
  }
}

async function pollData() {
  try {
    const record = await fetchJSON("/api/data");
    if (record.timestamp !== store.lastTimestamp) {
      store.lastTimestamp = record.timestamp;
      for (const param of store.config.params) {
        const value = record.values[param.key];
        if (value !== undefined) updateWidget(param, value);
      }
    }
    ui.status.textContent = "online";
    ui.status.className = "status online";
  } catch (error) {
    ui.status.textContent = "błąd: " + error.message;
    ui.status.className = "status offline";
  }
}

async function loadMessages() {
  let history;
  try {
    history = await fetchJSON("/api/messages?limit=20");
  } catch (error) {
    ui.messageList.textContent = "błąd historii: " + error.message;
    return;
  }
  ui.messageList.innerHTML = "";
  for (const message of history.messages) {
    const item = document.createElement("li");
    const time = new Date(message.timestamp * 1000).toLocaleTimeString();
    item.textContent = `[${time}] ${message.text}`;
    ui.messageList.appendChild(item);
  }
}

async function sendMessage(event) {
  event.preventDefault();
  const text = ui.messageInput.value.trim();
  if (!text) return;
  try {
    await fetchJSON("/api/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    ui.messageInput.value = "";
    await loadMessages();
  } catch (error) {
    ui.status.textContent = "błąd: " + error.message;
    ui.status.className = "status offline";
  }
}

async function main() {
  ui.messageForm.addEventListener("submit", sendMessage);
  try {
    store.config = await fetchJSON("/api/config");
    renderConfig();
    await pollData();
    await loadMessages();
    const interval = store.config.refresh_interval_ms || 1500;
    setInterval(() => {
      pollData();
      loadMessages();
    }, interval);
  } catch (error) {
    ui.status.textContent = "błąd: " + error.message;
    ui.status.className = "status offline";
  }
}

main();
