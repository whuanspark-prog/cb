const state = {
  dashboard: null,
  lastUpdateTime: 0,
  busy: false,
  filters: {
    month: "",
    type: "支出",
    selectedCategory: "",
  },
  messages: [
    {
      role: "assistant",
      text: "你好，我是 Clip Bill。把账单截图扔给我，或者直接说“人淡如菊算餐饮”，右边账本会立刻跟上。",
    },
  ],
};

const colors = ["#1f8a70", "#3d6fb6", "#b88926", "#c44d3c", "#7b61b5", "#607d3b", "#c46f2d", "#557b8a"];
const expenseCategories = [
  "餐饮", "服饰", "日用", "数码", "美妆", "住房", "交通", "娱乐",
  "医疗", "通讯", "学习", "办公", "运动", "人情", "育儿", "宠物",
  "旅行", "追星", "其他", "【待人工确认】",
];
const incomeCategories = [
  "工资", "奖金", "加班", "福利", "公积金", "红包", "兼职", "副业",
  "退款", "投资", "意外收入", "其他", "【待人工确认】",
];
const tips = ["正在提取金额...", "正在比对历史账单...", "正在分类...", "正在写入账本..."];
let tipTimer = null;

const $ = (id) => document.getElementById(id);

function money(value) {
  return `¥ ${Number(value || 0).toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatReply(text) {
  return escapeHtml(text).replace(
    /(\[[^\]]+\]|【[^】]+】|餐饮|交通|日用|学习|投资|红包|收入|支出|其他|待人工确认)/g,
    '<span class="tag">$1</span>'
  );
}

function addMessage(message) {
  state.messages.push(message);
  renderMessages();
}

function renderMessages() {
  const list = $("messageList");
  list.innerHTML = state.messages
    .map((message) => {
      const image = message.image ? `<img src="${message.image}" alt="上传的账单截图" />` : "";
      return `<article class="message ${message.role}">${formatReply(message.text || "")}${image}</article>`;
    })
    .join("");
  list.scrollTop = list.scrollHeight;
}

function setBusy(isBusy) {
  state.busy = isBusy;
  $("typingIndicator").classList.toggle("hidden", !isBusy);
  document.querySelectorAll("button, #messageInput, #fileInput").forEach((el) => {
    el.disabled = isBusy;
  });

  if (tipTimer) {
    clearInterval(tipTimer);
    tipTimer = null;
  }
  if (isBusy) {
    let index = 0;
    $("typingText").textContent = tips[index];
    tipTimer = setInterval(() => {
      index = (index + 1) % tips.length;
      $("typingText").textContent = tips[index];
    }, 1100);
  }
}

function getTransactions() {
  return state.dashboard?.transactions || [];
}

function monthOf(tx) {
  return String(tx.time || "").slice(0, 7);
}

function monthLabel(month) {
  if (!month) return "全部月份";
  const [year, rawMonth] = month.split("-");
  return `${year}年${Number(rawMonth)}月`;
}

function ensureFilterDefaults() {
  const months = [...new Set(getTransactions().map(monthOf).filter(Boolean))].sort().reverse();
  if (!state.filters.month || !months.includes(state.filters.month)) {
    state.filters.month = months[0] || "";
    state.filters.selectedCategory = "";
  }
}

function filteredByMonth() {
  return getTransactions().filter((tx) => !state.filters.month || monthOf(tx) === state.filters.month);
}

function filteredForPie() {
  return filteredByMonth().filter((tx) => tx.type === state.filters.type);
}

function filteredForLedger() {
  return filteredForPie().filter((tx) => {
    return !state.filters.selectedCategory || tx.category === state.filters.selectedCategory;
  });
}

function groupByCategory(transactions) {
  const grouped = new Map();
  transactions.forEach((tx) => {
    grouped.set(tx.category, (grouped.get(tx.category) || 0) + Number(tx.amount || 0));
  });
  return [...grouped.entries()]
    .map(([category, amount]) => ({ category, amount: Math.round(amount * 100) / 100 }))
    .sort((a, b) => b.amount - a.amount);
}

function sumByType(transactions, type) {
  return transactions
    .filter((tx) => tx.type === type)
    .reduce((sum, tx) => sum + Number(tx.amount || 0), 0);
}

function categoriesForType(type) {
  return type === "收入" ? incomeCategories : expenseCategories;
}

function setDashboard(payload) {
  state.dashboard = payload;
  state.lastUpdateTime = Date.now();
  ensureFilterDefaults();
  renderDashboard();
}

async function fetchDashboard() {
  const response = await fetch("/api/dashboard");
  if (!response.ok) throw new Error("账本数据加载失败");
  setDashboard(await response.json());
}

function bumpMetric(id, value) {
  const el = $(id);
  const card = el.closest(".metric-card");
  const previous = el.dataset.value;
  el.dataset.value = String(value);
  el.textContent = id === "pendingMetric" ? Number(value || 0) : money(value);
  if (previous !== undefined && previous !== String(value)) {
    card.classList.remove("bump");
    void card.offsetWidth;
    card.classList.add("bump");
  }
}

function renderDashboard() {
  if (!state.dashboard) return;
  ensureFilterDefaults();
  renderControls();

  const monthRows = filteredByMonth();
  const income = sumByType(monthRows, "收入");
  const expense = sumByType(monthRows, "支出");
  const pending = getTransactions().filter((tx) => tx.category === "【待人工确认】").length;
  const scope = monthLabel(state.filters.month);

  $("incomeLabel").textContent = `${scope}收入`;
  $("expenseLabel").textContent = `${scope}支出`;
  $("balanceLabel").textContent = `${scope}结余`;
  bumpMetric("incomeMetric", income);
  bumpMetric("expenseMetric", expense);
  bumpMetric("balanceMetric", income - expense);
  bumpMetric("pendingMetric", pending);

  renderPie(groupByCategory(filteredForPie()));
  renderBars(state.dashboard.monthly || []);
  renderLedger(filteredForLedger());
}

function renderControls() {
  const months = [...new Set(getTransactions().map(monthOf).filter(Boolean))].sort().reverse();
  $("monthSelect").innerHTML = months
    .map((month) => `<option value="${month}" ${month === state.filters.month ? "selected" : ""}>${monthLabel(month)}</option>`)
    .join("");

  document.querySelectorAll(".type-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.type === state.filters.type);
  });

  const clearButton = $("clearCategoryButton");
  if (state.filters.selectedCategory) {
    clearButton.textContent = `已筛选：${state.filters.selectedCategory} ×`;
    clearButton.classList.remove("hidden");
  } else {
    clearButton.textContent = "";
    clearButton.classList.add("hidden");
  }
}

function polarToCartesian(cx, cy, r, angle) {
  const radian = ((angle - 90) * Math.PI) / 180;
  return {
    x: cx + r * Math.cos(radian),
    y: cy + r * Math.sin(radian),
  };
}

function arcPath(cx, cy, outerRadius, innerRadius, startAngle, endAngle) {
  const outerStart = polarToCartesian(cx, cy, outerRadius, endAngle);
  const outerEnd = polarToCartesian(cx, cy, outerRadius, startAngle);
  const innerStart = polarToCartesian(cx, cy, innerRadius, startAngle);
  const innerEnd = polarToCartesian(cx, cy, innerRadius, endAngle);
  const largeArc = endAngle - startAngle <= 180 ? "0" : "1";

  return [
    "M", outerStart.x, outerStart.y,
    "A", outerRadius, outerRadius, 0, largeArc, 0, outerEnd.x, outerEnd.y,
    "L", innerStart.x, innerStart.y,
    "A", innerRadius, innerRadius, 0, largeArc, 1, innerEnd.x, innerEnd.y,
    "Z",
  ].join(" ");
}

function selectCategory(category) {
  state.filters.selectedCategory = state.filters.selectedCategory === category ? "" : category;
  renderDashboard();
}

function renderPie(categories) {
  const total = categories.reduce((sum, item) => sum + Number(item.amount || 0), 0);
  $("pieTitle").textContent = `${monthLabel(state.filters.month)}${state.filters.type}分类`;
  $("categoryTotal").textContent = money(total);

  const svg = $("pieChart");
  if (!total) {
    state.filters.selectedCategory = "";
    svg.innerHTML = `
      <circle class="pie-empty" cx="90" cy="90" r="72"></circle>
      <circle fill="#fff" cx="90" cy="90" r="42"></circle>
    `;
    $("pieLegend").innerHTML = `<p class="muted">暂无${state.filters.type}数据</p>`;
    $("clearCategoryButton").textContent = "";
    $("clearCategoryButton").classList.add("hidden");
    return;
  }

  let angle = 0;
  const slices = categories.map((item, index) => {
    const span = (Number(item.amount) / total) * 360;
    const start = angle;
    const end = angle + span;
    angle = end;
    const active = state.filters.selectedCategory === item.category;
    const dimmed = state.filters.selectedCategory && !active;
    const color = colors[index % colors.length];
    return `
      <path
        class="pie-slice ${active ? "active" : ""} ${dimmed ? "dimmed" : ""}"
        d="${arcPath(90, 90, 74, 42, start, end)}"
        fill="${color}"
        data-category="${escapeHtml(item.category)}"
      >
        <title>${escapeHtml(item.category)} ${money(item.amount)}</title>
      </path>
    `;
  });
  svg.innerHTML = slices.join("") + `<circle fill="#fff" cx="90" cy="90" r="39"></circle>`;

  svg.querySelectorAll(".pie-slice").forEach((slice) => {
    slice.addEventListener("click", () => selectCategory(slice.dataset.category));
  });

  $("pieLegend").innerHTML = categories
    .slice(0, 10)
    .map((item, index) => {
      const active = state.filters.selectedCategory === item.category;
      const dimmed = state.filters.selectedCategory && !active;
      const color = colors[index % colors.length];
      const percent = total ? `${((Number(item.amount) / total) * 100).toFixed(1)}%` : "0%";
      return `
        <button class="legend-item ${active ? "active" : ""} ${dimmed ? "dimmed" : ""}" data-category="${escapeHtml(item.category)}" type="button">
          <span class="legend-color" style="background:${color}"></span>
          <span>${escapeHtml(item.category)} · ${percent}</span>
          <strong>${money(item.amount)}</strong>
        </button>
      `;
    })
    .join("");

  $("pieLegend").querySelectorAll(".legend-item").forEach((item) => {
    item.addEventListener("click", () => selectCategory(item.dataset.category));
  });
}

function renderBars(monthly) {
  const chart = $("barChart");
  const visible = monthly.slice(-8);
  const max = Math.max(
    1,
    ...visible.flatMap((item) => [Number(item["收入"] || 0), Number(item["支出"] || 0)])
  );

  chart.innerHTML = visible
    .map((item) => {
      const incomeHeight = Math.max(3, (Number(item["收入"] || 0) / max) * 150);
      const expenseHeight = Math.max(3, (Number(item["支出"] || 0) / max) * 150);
      return `
        <div class="bar-group">
          <div class="bars">
            <span class="bar income" title="收入 ${money(item["收入"])}" style="height:${incomeHeight}px"></span>
            <span class="bar expense" title="支出 ${money(item["支出"])}" style="height:${expenseHeight}px"></span>
          </div>
          <span class="bar-label">${escapeHtml(item.month)}</span>
        </div>
      `;
    })
    .join("");
}

function renderLedger(transactions) {
  const titleParts = [monthLabel(state.filters.month), state.filters.type];
  if (state.filters.selectedCategory) titleParts.push(state.filters.selectedCategory);
  $("ledgerTitle").textContent = `${titleParts.join(" · ")}明细`;
  $("ledgerCount").textContent = `${transactions.length} 笔`;
  $("ledgerBody").innerHTML = transactions
    .map((tx) => {
      const typeClass = tx.type === "收入" ? "income" : "expense";
      const rowClass = tx.highlight ? "new-row" : "";
      const options = categoriesForType(tx.type);
      return `
        <tr class="${rowClass}">
          <td>${escapeHtml(String(tx.time || "").slice(0, 16))}</td>
          <td>${escapeHtml(tx.merchant)}</td>
          <td><span class="type-pill ${typeClass}">${escapeHtml(tx.type)}</span></td>
          <td>
            <select class="category-select" data-id="${tx.id}" aria-label="修改分类">
              ${options
                .map((category) => {
                  const selected = category === tx.category ? "selected" : "";
                  return `<option value="${escapeHtml(category)}" ${selected}>${escapeHtml(category)}</option>`;
                })
                .join("")}
            </select>
          </td>
          <td class="amount-cell">${money(tx.amount)}</td>
        </tr>
      `;
    })
    .join("");

  $("ledgerBody").querySelectorAll(".category-select").forEach((select) => {
    select.addEventListener("change", () => updateTransactionCategory(select));
  });
}

async function updateTransactionCategory(select) {
  const transactionId = select.dataset.id;
  const category = select.value;
  select.disabled = true;
  try {
    const response = await fetch(`/api/transactions/${transactionId}/category`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "分类修改失败");
    addMessage({ role: "assistant", text: `✅ ${data.reply}` });
    if (data.dashboard) {
      setDashboard(data.dashboard);
    } else {
      await fetchDashboard();
    }
  } catch (error) {
    addMessage({ role: "assistant", text: `分类修改失败：${error.message}` });
    await fetchDashboard();
  } finally {
    select.disabled = false;
  }
}

async function sendMessage(text) {
  addMessage({ role: "user", text });
  setBusy(true);
  try {
    const response = await fetch("/api/chat/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "消息处理失败");
    addMessage({ role: "assistant", text: data.reply });
    if (data.dashboard) {
      setDashboard(data.dashboard);
    } else if (data.need_refresh) {
      await fetchDashboard();
    }
  } catch (error) {
    addMessage({ role: "assistant", text: `处理失败：${error.message}` });
  } finally {
    setBusy(false);
  }
}

async function uploadReceipt(file) {
  const imageUrl = URL.createObjectURL(file);
  addMessage({ role: "user", text: `上传了 ${file.name}`, image: imageUrl });
  setBusy(true);

  try {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch("/api/chat/upload", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "截图识别失败");
    addMessage({ role: "assistant", text: data.reply });
    if (data.dashboard) {
      setDashboard(data.dashboard);
    } else {
      await fetchDashboard();
    }
  } catch (error) {
    addMessage({ role: "assistant", text: `识别失败：${error.message}` });
  } finally {
    setBusy(false);
  }
}

function bindEvents() {
  $("chatForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const input = $("messageInput");
    const text = input.value.trim();
    if (!text || state.busy) return;
    input.value = "";
    sendMessage(text);
  });

  $("uploadButton").addEventListener("click", () => {
    if (!state.busy) $("fileInput").click();
  });

  $("fileInput").addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) uploadReceipt(file);
  });

  $("refreshButton").addEventListener("click", () => fetchDashboard());

  $("monthSelect").addEventListener("change", (event) => {
    state.filters.month = event.target.value;
    state.filters.selectedCategory = "";
    renderDashboard();
  });

  document.querySelectorAll(".type-tab").forEach((button) => {
    button.addEventListener("click", () => {
      state.filters.type = button.dataset.type;
      state.filters.selectedCategory = "";
      renderDashboard();
    });
  });

  $("clearCategoryButton").addEventListener("click", () => {
    state.filters.selectedCategory = "";
    renderDashboard();
  });
}

async function boot() {
  renderMessages();
  bindEvents();
  try {
    await fetchDashboard();
  } catch (error) {
    addMessage({ role: "assistant", text: `账本加载失败：${error.message}` });
  }
}

boot();
