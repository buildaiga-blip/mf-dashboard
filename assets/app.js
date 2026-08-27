const MFAPI_BASE = "https://api.mfapi.in/mf";
const PERIODS = ["1M", "3M", "6M", "1Y", "3Y", "5Y"];
const RETURN_PERIOD_DAYS = { "1M": 30, "3M": 91, "6M": 182, "1Y": 365, "3Y": 1095, "5Y": 1825 };
const LIVE_REFRESH_CONCURRENCY = 6; // be polite to the free API
const ACTIVE_MAX_STALE_DAYS = 15; // NAVs publish on every business day; older than this suggests a matured/wound-up scheme
// Which category "group" values (from data.json) show up under which tab.
const TAB_GROUPS = { equity: ["Equity", "Hybrid"], debt: ["Debt"] };
let DATA = null;
let sortState = { equity: "1Y", debt: "3M" };

// ---------- Tabs ----------
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => (p.style.display = "none"));
    tab.classList.add("active");
    document.getElementById(tab.dataset.target).style.display = "block";
  });
});

// ---------- Sub-tabs (e.g. Regulatory / News inside Financial Updates) ----------
document.querySelectorAll(".subtab").forEach((subtab) => {
  subtab.addEventListener("click", () => {
    const parent = subtab.closest(".tab-panel");
    parent.querySelectorAll(".subtab").forEach((t) => t.classList.remove("active"));
    parent.querySelectorAll(".subtab-panel").forEach((p) => (p.style.display = "none"));
    subtab.classList.add("active");
    document.getElementById(subtab.dataset.subtarget).style.display = "block";
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

// ---------- Live refresh (runs entirely in the visitor's browser, no server) ----------
// Parses date strings like "16-08-2026" (mfapi.in format) into Date objects.
function parseMfapiDate(str) {
  const [d, m, y] = str.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function navOnOrBefore(historyNewestFirst, targetDate) {
  for (const [d, nav] of historyNewestFirst) {
    if (d <= targetDate) return nav;
  }
  return null;
}

// Mirrors compute_returns() in fetch_universe.py, run client-side.
function computeReturnsFromHistory(historyNewestFirst) {
  if (!historyNewestFirst || historyNewestFirst.length < 2) return null;
  const [latestDate, latestNav] = historyNewestFirst[0];
  const out = {};
  for (const [label, days] of Object.entries(RETURN_PERIOD_DAYS)) {
    const target = new Date(latestDate);
    target.setDate(target.getDate() - days);
    const pastNav = navOnOrBefore(historyNewestFirst, target);
    if (!pastNav || pastNav <= 0) {
      out[label] = null;
      continue;
    }
    const simpleChange = (latestNav - pastNav) / pastNav;
    if (days > 365) {
      const years = days / 365;
      out[label] = Math.round((Math.pow(latestNav / pastNav, 1 / years) - 1) * 10000) / 100;
    } else {
      out[label] = Math.round(simpleChange * 10000) / 100;
    }
  }
  out.nav = latestNav;
  out.nav_date = `${String(latestDate.getDate()).padStart(2, "0")}-${latestDate.toLocaleString("en-US", { month: "short" })}-${latestDate.getFullYear()}`;
  return out;
}

async function fetchFullNavHistory(schemeCode) {
  const res = await fetch(`${MFAPI_BASE}/${schemeCode}`);
  if (!res.ok) return null;
  const json = await res.json();
  const rows = (json.data || [])
    .map((r) => [parseMfapiDate(r.date), parseFloat(r.nav)])
    .filter(([d, nav]) => !isNaN(d.getTime()) && !isNaN(nav));
  return rows; // newest-first, matching mfapi.in's own ordering
}

// Simple concurrency-limited map so we don't fire 80 requests at once.
async function mapWithConcurrency(items, limit, worker) {
  const results = new Array(items.length);
  let next = 0;
  async function runOne() {
    while (next < items.length) {
      const i = next++;
      results[i] = await worker(items[i], i);
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, runOne));
  return results;
}

async function refreshAllLive() {
  if (!DATA || !DATA.categories) return;
  const btn = document.getElementById("live-refresh-btn");
  const originalLabel = btn.textContent;
  btn.disabled = true;

  const allFunds = DATA.categories.flatMap((cat) => cat.funds.map((f) => ({ cat, f })));
  let done = 0;

  await mapWithConcurrency(allFunds, LIVE_REFRESH_CONCURRENCY, async ({ f }) => {
    try {
      const history = await fetchFullNavHistory(f.schemeCode);
      const fresh = computeReturnsFromHistory(history);
      if (fresh) Object.assign(f, fresh);
    } catch {
      // leave the fund's last-known values in place on failure
    } finally {
      done++;
      btn.textContent = `Refreshing... ${done}/${allFunds.length}`;
    }
  });

  // Recompute each category's average for the currently ranked metric, active funds only
  DATA.categories.forEach((cat) => {
    const withMetric = cat.funds.filter(
      (f) => isFundActive(f) && f[cat.rank_metric] !== null && f[cat.rank_metric] !== undefined
    );
    cat.avg = withMetric.length
      ? Math.round((withMetric.reduce((s, f) => s + f[cat.rank_metric], 0) / withMetric.length) * 100) / 100
      : null;
  });

  DATA.updated = "Live — refreshed just now in your browser (" + new Date().toLocaleTimeString() + ")";
  document.getElementById("updated-label").textContent = DATA.updated;
  renderRankings();

  btn.disabled = false;
  btn.textContent = originalLabel;
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

// ---------- Active-fund filter ----------
// Parses display dates like "16-Aug-2026" (the format nav_date is stored in) into a Date.
function parseDisplayDate(str) {
  if (!str) return null;
  const d = new Date(str);
  return isNaN(d.getTime()) ? null : d;
}

// A fund only counts as "active" if it has a NAV date and that date isn't stale
// (matured / wound-up / delisted schemes stop publishing NAVs and fall behind).
function isFundActive(f) {
  const d = parseDisplayDate(f.nav_date);
  if (!d) return false;
  const ageDays = (Date.now() - d.getTime()) / 86400000;
  return ageDays <= ACTIVE_MAX_STALE_DAYS;
}

// ---------- Sort pills (independent per tab) ----------
document.querySelectorAll(".pill[data-period]").forEach((pill) => {
  pill.addEventListener("click", () => {
    const group = pill.dataset.tabgroup;
    document
      .querySelectorAll(`.pill[data-tabgroup="${group}"]`)
      .forEach((p) => p.classList.remove("active"));
    pill.classList.add("active");
    sortState[group] = pill.dataset.period;
    renderRankings();
  });
});

function renderRankings() {
  const containers = {
    equity: document.getElementById("equity-rankings-container"),
    debt: document.getElementById("debt-rankings-container"),
  };
  Object.values(containers).forEach((c) => (c.innerHTML = ""));

  if (!DATA || !DATA.categories) {
    Object.values(containers).forEach((c) => {
      c.innerHTML = '<div class="empty-state">No data yet — run fetch_universe.py or wait for the next scheduled refresh.</div>';
    });
    return;
  }

  Object.entries(TAB_GROUPS).forEach(([tabKey, groups]) => {
    const container = containers[tabKey];
    const currentSort = sortState[tabKey];
    const cats = DATA.categories.filter((cat) => groups.includes(cat.group));

    if (cats.length === 0) {
      container.innerHTML = '<div class="empty-state">No categories in this tab yet.</div>';
      return;
    }

    cats.forEach((cat) => {
      const activeFunds = cat.funds.filter(isFundActive);
      const funds = [...activeFunds].sort((a, b) => {
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

      if (funds.length === 0) {
        const empty = document.createElement("div");
        empty.className = "empty-state";
        empty.textContent = "No active funds currently on record for this category — run a data refresh.";
        card.appendChild(empty);
        container.appendChild(card);
        return;
      }

      const scrollWrap = document.createElement("div");
      scrollWrap.className = "table-scroll";

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
      scrollWrap.appendChild(table);
      card.appendChild(scrollWrap);
      container.appendChild(card);
    });
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
    "Tip: scheme codes are visible in the Equity/Debt tabs (per fund row) or search the scheme name at mfapi.in.";
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

document.getElementById("live-refresh-btn").addEventListener("click", refreshAllLive);

// ---------- Financial Updates tab ----------
let UPDATES_DATA = null;
let activeSourceFilter = "All";

async function loadUpdates() {
  try {
    const res = await fetch("data/regulatory_updates.json", { cache: "no-store" });
    UPDATES_DATA = await res.json();
  } catch {
    UPDATES_DATA = { items: [] };
  }
  renderUpdates();
}

function renderUpdates() {
  const container = document.getElementById("updates-container");
  if (!UPDATES_DATA) return;

  const items = UPDATES_DATA.items.filter(
    (it) => activeSourceFilter === "All" || it.source === activeSourceFilter
  );

  if (items.length === 0) {
    container.innerHTML = '<div class="empty-state">No announcements matching this filter in the last 2 days — check the News sub-tab for general coverage.</div>';
  } else {
    container.innerHTML = items
      .map(
        (it) => `
      <div class="update-item">
        <div class="update-item-top">
          <span class="source-badge source-${it.source}">${it.source}</span>
          <span class="topic-badge">${it.topic}</span>
          <span class="update-date">${it.published}</span>
        </div>
        <div class="update-title"><a href="${it.link}" target="_blank" rel="noopener">${it.title}</a></div>
        ${it.summary ? `<div style="color:var(--text-dim); font-size:12px; margin-top:4px;">${it.summary}</div>` : ""}
        <div style="color:var(--text-dim); font-size:11.5px; margin-top:4px;">${it.feed_label}</div>
      </div>
    `
      )
      .join("");
  }
}

document.querySelectorAll('#update-source-filters .pill').forEach((pill) => {
  pill.addEventListener("click", () => {
    document.querySelectorAll('#update-source-filters .pill').forEach((p) => p.classList.remove("active"));
    pill.classList.add("active");
    activeSourceFilter = pill.dataset.source;
    renderUpdates();
  });
});

// ---------- News sub-tab ----------
let NEWS_DATA = null;
let activeNewsCategory = "All";

async function loadNews() {
  try {
    const res = await fetch("data/news.json", { cache: "no-store" });
    NEWS_DATA = await res.json();
  } catch {
    NEWS_DATA = { items: [] };
  }
  renderNews();
  renderResearch(); // re-run now that live headlines are available for sector tie-ins
}

function renderNews() {
  const container = document.getElementById("news-container");
  if (!NEWS_DATA) return;

  const items = NEWS_DATA.items.filter(
    (it) => activeNewsCategory === "All" || it.category === activeNewsCategory
  );

  if (items.length === 0) {
    container.innerHTML = '<div class="empty-state">No news yet — run the GitHub Action to populate this feed.</div>';
    return;
  }

  container.innerHTML = items
    .map(
      (it) => `
    <div class="update-item">
      <div class="update-item-top">
        <span class="topic-badge news-category-badge">${it.category}</span>
        <span class="update-date">${it.published}</span>
      </div>
      <div class="update-title"><a href="${it.link}" target="_blank" rel="noopener">${it.title}</a></div>
      <div style="color:var(--text-dim); font-size:11.5px; margin-top:4px;">${it.source}</div>
    </div>
  `
    )
    .join("");
}

document.querySelectorAll('#news-category-filters .pill').forEach((pill) => {
  pill.addEventListener("click", () => {
    document.querySelectorAll('#news-category-filters .pill').forEach((p) => p.classList.remove("active"));
    pill.classList.add("active");
    activeNewsCategory = pill.dataset.category;
    renderNews();
  });
});

// ---------- Economic Trends tab ----------
let TRENDS_DATA = null;
const chartInstances = {};

async function loadTrends() {
  try {
    const res = await fetch("data/macro_trends.json", { cache: "no-store" });
    TRENDS_DATA = await res.json();
  } catch {
    TRENDS_DATA = { indicators: {}, current_policy_rates: {}, market_pulse: {} };
  }
  renderPolicyRates();
  renderTrends();
  renderMarketPulse(); // Research tab's market strip depends on this same data
}

function renderPolicyRates() {
  const container = document.getElementById("policy-rates-container");
  const rates = (TRENDS_DATA && TRENDS_DATA.current_policy_rates) || {};
  const keys = Object.keys(rates);
  if (keys.length === 0) {
    container.innerHTML =
      '<div class="empty-state" style="padding:14px;">No policy rates extracted yet — run the GitHub Action to scan RBI announcements.</div>';
    return;
  }
  const order = ["repo_rate", "reverse_repo_rate", "sdf_rate", "msf_rate", "bank_rate"];
  container.innerHTML = order
    .filter((k) => rates[k])
    .map((k) => {
      const r = rates[k];
      return `
        <div class="policy-rate-chip" title="${r.source_title}">
          <div class="policy-rate-label">${r.label}</div>
          <div class="policy-rate-value">${r.value.toFixed(2)}%</div>
          <div class="policy-rate-date">As of ${formatDisplayDate(r.as_of)}${r.link ? ` · <a href="${r.link}" target="_blank" rel="noopener">source</a>` : ""}</div>
        </div>
      `;
    })
    .join("");
}

function renderTrends() {
  const container = document.getElementById("trends-container");
  container.innerHTML = "";
  if (!TRENDS_DATA || !TRENDS_DATA.indicators) return;

  const zoomAvailable = typeof Chart !== "undefined" && Chart.registry.plugins.get("zoom");

  Object.entries(TRENDS_DATA.indicators).forEach(([key, series]) => {
    const card = document.createElement("div");
    card.className = "trend-card";
    const points = series.points || [];
    const latest = points.length ? points[points.length - 1] : null;
    const asOf = series.as_of || (latest ? latest.date : null);

    card.innerHTML = `
      <div class="trend-card-head">
        <h4>${series.label}</h4>
        <div class="trend-latest-block">
          <div class="trend-latest">${latest ? latest.value.toFixed(2) + " " + series.unit : "No data"}</div>
          <div class="trend-as-of">${asOf ? "As of " + formatDisplayDate(asOf) : ""}</div>
        </div>
      </div>
      <div class="trend-chart-wrap"><canvas id="chart-${key}"></canvas></div>
      ${points.length > 0 && zoomAvailable ? `<button class="reset-zoom-btn" data-chart-key="${key}">Reset zoom</button>` : ""}
      <div style="color:var(--text-dim); font-size:11px; margin-top:6px;">Source: ${series.source || "N/A"}${points.length === 0 ? " — not yet populated, run the GitHub Action" : ""}</div>
    `;
    container.appendChild(card);

    if (points.length > 0 && typeof Chart !== "undefined") {
      const ctx = card.querySelector(`#chart-${key}`).getContext("2d");
      if (chartInstances[key]) chartInstances[key].destroy();
      chartInstances[key] = new Chart(ctx, {
        type: "line",
        data: {
          labels: points.map((p) => p.date),
          datasets: [
            {
              label: series.label,
              data: points.map((p) => p.value),
              borderColor: "#d4a72c",
              backgroundColor: "rgba(212,167,44,0.12)",
              fill: true,
              tension: 0.25,
              pointRadius: 0,
              pointHoverRadius: 5,
              pointHoverBackgroundColor: "#d4a72c",
              pointHitRadius: 12,
              borderWidth: 2,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: "index", intersect: false },
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: "#16213a",
              borderColor: "#d4a72c",
              borderWidth: 1,
              titleColor: "#e8ecf4",
              bodyColor: "#e8ecf4",
              padding: 10,
              callbacks: {
                title: (items) => formatDisplayDate(items[0].label),
                label: (item) => `${series.label}: ${item.parsed.y.toFixed(2)} ${series.unit}`,
                afterLabel: (item) => {
                  const p = points[item.dataIndex];
                  return p && p.note ? p.note : "";
                },
              },
            },
            zoom: zoomAvailable
              ? {
                  pan: { enabled: true, mode: "x" },
                  zoom: {
                    wheel: { enabled: true },
                    pinch: { enabled: true },
                    mode: "x",
                  },
                }
              : undefined,
          },
          scales: {
            x: { ticks: { color: "#8b96ac", maxTicksLimit: 6 }, grid: { color: "#24304a" } },
            y: { ticks: { color: "#8b96ac" }, grid: { color: "#24304a" } },
          },
        },
      });
    } else if (points.length > 0 && typeof Chart === "undefined") {
      card.querySelector(".trend-chart-wrap").innerHTML =
        '<div class="empty-state">Chart library failed to load from CDN — check your internet connection or that cdnjs.cloudflare.com isn\'t blocked, then reload.</div>';
    }
  });

  container.querySelectorAll(".reset-zoom-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const chart = chartInstances[btn.dataset.chartKey];
      if (chart && chart.resetZoom) chart.resetZoom();
    });
  });
}

function formatDisplayDate(isoOrDateStr) {
  const d = new Date(isoOrDateStr);
  if (isNaN(d.getTime())) return isoOrDateStr;
  return d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
}

// ---------- Research tab ----------
function renderMarketPulse() {
  const container = document.getElementById("market-pulse-container");
  if (!container) return;
  const pulse = TRENDS_DATA && TRENDS_DATA.market_pulse;
  if (!pulse || (!pulse.sensex && !pulse.nifty)) {
    container.innerHTML = "";
    return;
  }
  container.innerHTML = `
    <div class="market-pulse-strip">
      ${pulse.sensex ? `<div class="pulse-chip"><div class="pulse-label">S&P BSE Sensex</div><div class="pulse-value">${pulse.sensex.toLocaleString("en-IN")}</div></div>` : ""}
      ${pulse.nifty ? `<div class="pulse-chip"><div class="pulse-label">Nifty 50</div><div class="pulse-value">${pulse.nifty.toLocaleString("en-IN")}</div></div>` : ""}
      <div class="pulse-asof">As of ${formatDisplayDate(pulse.as_of)} · Source: ${pulse.source}</div>
    </div>
  `;
}

function findRelatedHeadline(keywords) {
  if (!NEWS_DATA || !NEWS_DATA.items) return null;
  const lowerKeywords = keywords.map((k) => k.toLowerCase());
  return (
    NEWS_DATA.items.find((it) => {
      const title = it.title.toLowerCase();
      return lowerKeywords.some((k) => title.includes(k));
    }) || null
  );
}

function renderResearch() {
  if (typeof SECTOR_THEMES === "undefined") return;
  document.getElementById("research-last-reviewed").textContent = `Last reviewed: ${LAST_REVIEWED}`;
  const container = document.getElementById("research-container");
  container.innerHTML = SECTOR_THEMES.map((s) => {
    const headline = findRelatedHeadline(s.keywords || []);
    return `
    <div class="sector-card">
      <h4>${s.icon || ""} ${s.sector}</h4>
      <p class="sector-thesis">${s.thesis}</p>
      <div class="company-chips">
        ${s.companies.map((c) => `<span class="company-chip">${c}</span>`).join("")}
      </div>
      ${headline ? `<div class="related-headline">📰 <a href="${headline.link}" target="_blank" rel="noopener">${headline.title}</a></div>` : ""}
    </div>
  `;
  }).join("");
}

// ---------- Init ----------
loadData();
renderPortfolio();
loadUpdates();
loadNews();
loadTrends();
renderResearch();
