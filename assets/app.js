const MFAPI_BASE = "https://api.mfapi.in/mf";
const PERIODS = ["1M", "3M", "6M", "1Y", "3Y", "5Y"];
let DATA = null;
let currentSort = "1Y";

// ---------- Tabs ----------
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => (p.style.display = "none"));
    tab.classList.add("active");
    document.getElementById(tab.dataset.target).style.display = "block";
  });
});

// ---------- Data load ----------
async function loadData() {
  const res = await fetch("data/data.json", { cache: "no-store" });
  DATA = await res.json();
  document.getElementById("updated-label").textContent = DATA.updated;
  renderRankings();
  populateSchemeDropdownHint();
}

function colorForReturn(value, group) {
  if (value === null || value === undefined) return "#2a3552";
  // Debt/Hybrid returns are annualized-ish and smaller magnitude than equity 1Y CAGR;
  // scale bands per group so colors stay meaningful across categories.
  const bands =
    group === "Debt"
      ? [5, 6.5, 8, 9.5, 11]
      : group === "Hybrid"
      ? [5, 8, 11, 14, 17]
      : [5, 10, 15, 20, 25]; // Equity
  const colors = ["#5a2a1f", "#0f4a2c", "#1b6b3d", "#278f4e", "#4db877", "#85d6a3"];
  let idx = 0;
  for (let i = 0; i < bands.length; i++) {
    if (value >= bands[i]) idx = i + 1;
  }
  return colors[idx];
}

function fmtPct(v) {
  if (v === null || v === undefined) return "N/A";
  return v.toFixed(2) + "%";
}

// ---------- Sort pills ----------
document.querySelectorAll(".pill[data-period]").forEach((pill) => {
  pill.addEventListener("click", () => {
    document.querySelectorAll(".pill[data-period]").forEach((p) => p.classList.remove("active"));
    pill.classList.add("active");
    currentSort = pill.dataset.period;
    renderRankings();
  });
});

function renderRankings() {
  const container = document.getElementById("rankings-container");
  container.innerHTML = "";
  if (!DATA || !DATA.categories) {
    container.innerHTML = '<div class="empty-state">No data yet — run fetch_universe.py or wait for the next scheduled refresh.</div>';
    return;
  }

  DATA.categories.forEach((cat) => {
    const funds = [...cat.funds].sort((a, b) => {
      const av = a[currentSort] ?? -999;
      const bv = b[currentSort] ?? -999;
      return bv - av;
    });

    const card = document.createElement("div");
    card.className = "category-card";

    const title = document.createElement("div");
    title.className = "category-title";
    title.innerHTML = `
      <div>
        <span class="group-tag group-${cat.group}">${cat.group}</span>
        <h3 style="display:inline">${cat.label}</h3>
      </div>
      <div class="category-meta">${cat.rating} &nbsp;|&nbsp; ${cat.horizon} &nbsp;|&nbsp; Avg ${cat.rank_metric}: <strong style="color:var(--gold)">${fmtPct(cat.avg)}</strong></div>
    `;
    card.appendChild(title);

    const table = document.createElement("table");
    const thead = document.createElement("thead");
    thead.innerHTML = `<tr>
      <th>#</th><th>Fund</th><th>NAV</th><th>Date</th>
      ${PERIODS.map((p) => `<th style="text-align:right">${p}</th>`).join("")}
    </tr>`;
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    funds.forEach((f, i) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><span class="rank-badge">${i + 1}</span></td>
        <td class="fund-name">${f.fund}</td>
        <td>₹${f.nav?.toFixed ? f.nav.toFixed(2) : f.nav}</td>
        <td>${f.nav_date || ""}</td>
        ${PERIODS.map((p) => {
          const v = f[p];
          const bg = colorForReturn(v, cat.group);
          const highlight = p === currentSort ? "outline:1px solid var(--gold);" : "";
          return `<td class="ret-cell" style="background:${bg};${highlight}">${fmtPct(v)}</td>`;
        }).join("")}
      `;
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    card.appendChild(table);
    container.appendChild(card);
  });
}

// ---------- Portfolio Tracker ----------
const PORTFOLIO_KEY = "mf_personal_portfolio_v1";

function loadPortfolio() {
  try {
    return JSON.parse(localStorage.getItem(PORTFOLIO_KEY)) || [];
  } catch {
    return [];
  }
}

function savePortfolio(rows) {
  localStorage.setItem(PORTFOLIO_KEY, JSON.stringify(rows));
}

function populateSchemeDropdownHint() {
  const hint = document.getElementById("scheme-code-hint");
  if (!DATA || !hint) return;
  hint.textContent =
    "Tip: scheme codes are visible in Fund Rankings (hover a row) or search the scheme name at mfapi.in.";
}

async function fetchLatestNav(schemeCode) {
  const res = await fetch(`${MFAPI_BASE}/${schemeCode}/latest`);
  if (!res.ok) throw new Error("Scheme not found");
  const json = await res.json();
  const row = json.data && json.data[0];
  return {
    name: json.meta ? json.meta.scheme_name : `Scheme ${schemeCode}`,
    nav: row ? parseFloat(row.nav) : null,
    date: row ? row.date : null,
  };
}

async function renderPortfolio() {
  const rows = loadPortfolio();
  const tbody = document.getElementById("portfolio-body");
  const totalCell = document.getElementById("portfolio-total");
  tbody.innerHTML = '<tr><td colspan="6" class="loading">Fetching live NAVs...</td></tr>';

  if (rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No holdings yet — add a scheme code and units above.</td></tr>';
    totalCell.textContent = "₹0.00";
    return;
  }

  let total = 0;
  const rendered = [];
  for (const r of rows) {
    try {
      const live = await fetchLatestNav(r.schemeCode);
      const value = live.nav ? live.nav * r.units : 0;
      total += value;
      rendered.push({ ...r, ...live, value });
    } catch {
      rendered.push({ ...r, name: `Scheme ${r.schemeCode} (fetch failed)`, nav: null, value: 0 });
    }
  }

  tbody.innerHTML = "";
  rendered.forEach((r, idx) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="fund-name">${r.name}</td>
      <td>${r.schemeCode}</td>
      <td>${r.units}</td>
      <td>₹${r.nav ? r.nav.toFixed(2) : "N/A"}</td>
      <td>₹${r.value.toFixed(2)}</td>
      <td><button class="remove-btn" data-idx="${idx}">Remove</button></td>
    `;
    tbody.appendChild(tr);
  });

  const totalRow = document.createElement("tr");
  totalRow.className = "total-row";
  totalRow.innerHTML = `<td colspan="4">Total Portfolio Value</td><td colspan="2">₹${total.toFixed(2)}</td>`;
  tbody.appendChild(totalRow);

  tbody.querySelectorAll(".remove-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const rows2 = loadPortfolio();
      rows2.splice(parseInt(btn.dataset.idx, 10), 1);
      savePortfolio(rows2);
      renderPortfolio();
    });
  });
}

document.getElementById("add-holding-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const codeInput = document.getElementById("input-scheme-code");
  const unitsInput = document.getElementById("input-units");
  const code = codeInput.value.trim();
  const units = parseFloat(unitsInput.value);
  if (!code || !units || units <= 0) return;
  const rows = loadPortfolio();
  rows.push({ schemeCode: code, units });
  savePortfolio(rows);
  codeInput.value = "";
  unitsInput.value = "";
  renderPortfolio();
});

document.getElementById("refresh-portfolio-btn").addEventListener("click", renderPortfolio);

// ---------- Init ----------
loadData();
renderPortfolio();
