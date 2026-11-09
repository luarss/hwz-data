const state = {
  meta: null,
  series: null,
  movers: null,
  items: null,
  itemSearchText: null,
  times: [],
  charts: [],
  compare: [],
};

const view = document.getElementById("view");
const resizeObserver = new ResizeObserver((entries) => {
  for (const entry of entries) {
    const plot = entry.target.plot;
    if (plot) plot.setSize({ width: entry.contentRect.width, height: plot.height });
  }
});

const VENDOR_NAMES = {
  bizgram: "Bizgram",
  dynacore: "Dynacore",
  fuwell: "Fuwell",
  infinity: "Infinity",
  laser: "Laser",
  pc_themes: "PC Themes",
  prime_pc: "Prime PC",
  techdeals: "TechDeals",
  tradepac: "Tradepac",
};

const fetchJson = (path) => fetch(path).then((response) => response.json());
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const seriesColor = (position) => cssVar(`--series-${(position % 8) + 1}`);
const vendorName = (vendor) => VENDOR_NAMES[vendor] ?? vendor;
const vendorColor = (vendor) => seriesColor(state.meta.vendors.indexOf(vendor));

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (character) => `&#${character.charCodeAt(0)};`);
}

function monthLabel(timestamp) {
  return new Date(timestamp * 1000).toLocaleDateString("en-SG", { month: "short", year: "numeric", timeZone: "UTC" });
}

function monthText(month) {
  const [year, monthNumber] = month.split("-").map(Number);
  return monthLabel(Date.UTC(year, monthNumber - 1, 1) / 1000);
}

function formatPrice(value) {
  if (value == null) return "—";
  return `S$${value.toLocaleString("en-SG", { maximumFractionDigits: value < 100 ? 2 : 0 })}`;
}

function formatCount(value) {
  return value == null ? "—" : value.toLocaleString("en-SG");
}

function formatIndex(value) {
  return value == null ? "—" : value.toFixed(1);
}

function lastIndex(values) {
  for (let position = values.length - 1; position >= 0; position--) {
    if (values[position] != null) return position;
  }
  return -1;
}

function percentChange(values, stepsBack) {
  const latest = lastIndex(values);
  if (latest < 0) return null;
  const reference = latest - stepsBack;
  if (stepsBack === Infinity) {
    const first = values.findIndex((value) => value != null);
    return first === latest ? null : (values[latest] / values[first] - 1) * 100;
  }
  if (reference < 0 || values[reference] == null) return null;
  return (values[latest] / values[reference] - 1) * 100;
}

function changeHtml(change) {
  if (change == null) return '<span class="muted">—</span>';
  const rounded = change.toFixed(1);
  if (Math.abs(change) < 0.05) return '<span class="muted">0.0%</span>';
  const className = change > 0 ? "up" : "down";
  const arrow = change > 0 ? "▲" : "▼";
  return `<span class="${className}">${arrow} ${change > 0 ? "+" : ""}${rounded}%</span>`;
}

function latestValue(values) {
  const position = lastIndex(values);
  return position < 0 ? null : values[position];
}

function destroyCharts() {
  for (const plot of state.charts) {
    resizeObserver.unobserve(plot.root.parentElement);
    plot.destroy();
  }
  state.charts = [];
}

function lineChart(container, lines, options = {}) {
  const { height = 280, format = formatIndex, sparkline = false } = options;
  const textColor = cssVar("--text-secondary");
  const gridColor = cssVar("--grid");
  const axis = {
    stroke: textColor,
    grid: { stroke: gridColor, width: 1 },
    ticks: { stroke: gridColor, width: 1 },
    font: "11px system-ui, sans-serif",
  };
  const plotOptions = {
    width: Math.max(container.clientWidth, 120),
    height,
    padding: sparkline ? [4, 2, 4, 2] : [12, 12, 0, 0],
    scales: { x: { time: true } },
    axes: sparkline
      ? [{ show: false }, { show: false }]
      : [axis, { ...axis, size: 64, values: (plot, ticks) => ticks.map(format) }],
    legend: { show: !sparkline, live: true },
    cursor: sparkline ? { show: false } : { drag: { x: false, y: false }, points: { size: 8 } },
    series: [
      { value: (plot, timestamp) => (timestamp == null ? "—" : monthLabel(timestamp)) },
      ...lines.map((line) => ({
        label: line.label,
        stroke: line.color,
        width: line.width ?? 2,
        dash: line.dash,
        spanGaps: true,
        points: { show: !sparkline, size: 5, fill: line.color },
        value: (plot, value) => (value == null ? "—" : format(value)),
      })),
    ],
  };
  const plot = new uPlot(plotOptions, [state.times, ...lines.map((line) => line.values)], container);
  container.plot = plot;
  resizeObserver.observe(container);
  state.charts.push(plot);
  return plot;
}

function seriesFor(key) {
  return state.series[key];
}

function setActiveTab(name) {
  for (const link of document.querySelectorAll("#tabs a")) {
    link.classList.toggle("active", link.getAttribute("href") === `#/${name}`);
  }
}

function route() {
  destroyCharts();
  const [name = "overview", ...rest] = location.hash.replace(/^#\/?/, "").split("/");
  const parameter = rest.length ? decodeURIComponent(rest.join("/")) : null;
  const renderers = {
    overview: renderOverview,
    shops: renderShops,
    components: renderComponents,
    brands: renderBrands,
    items: renderItems,
  };
  const renderer = renderers[name] ?? renderOverview;
  setActiveTab(renderers[name] ? name : "overview");
  renderer(parameter);
  window.scrollTo({ top: 0 });
}

function tile(label, value, sub = "") {
  return `<div class="card tile"><div class="label">${label}</div><div class="value">${value}</div><div class="sub">${sub}</div></div>`;
}

function smallMultiples(container, entries) {
  container.innerHTML = entries
    .map(
      (entry, position) => `
      <a class="card multiple" href="${entry.href}" style="text-decoration:none;color:inherit">
        <div class="head"><span class="name">${escapeHtml(entry.label)}</span>
          <span class="stats">${formatIndex(latestValue(entry.series.index))}</span></div>
        <div class="stats muted">3m ${changeHtml(percentChange(entry.series.index, 3))}
          · 12m ${changeHtml(percentChange(entry.series.index, 12))}
          · ${formatCount(latestValue(entry.series.n))} listed</div>
        <div class="chart" data-position="${position}"></div>
      </a>`
    )
    .join("");
  for (const element of container.querySelectorAll(".chart")) {
    const entry = entries[Number(element.dataset.position)];
    lineChart(element, [{ label: entry.label, values: entry.series.index, color: cssVar("--accent"), width: 1.5 }], {
      height: 60,
      sparkline: true,
    });
  }
}

async function loadMovers() {
  if (!state.movers) state.movers = await fetchJson("data/movers.json");
  return state.movers;
}

function moversTable(rows) {
  if (!rows.length) return '<p class="muted">No price changes in the latest lists.</p>';
  return `<div class="table-wrap"><table>
    <thead><tr><th>Item</th><th>Shop</th><th class="num">Was</th><th class="num">Now</th><th class="num">Change</th></tr></thead>
    <tbody>${rows
      .map(
        (row) => `<tr>
        <td class="wrap">${escapeHtml(row.item)}<div class="muted">${escapeHtml(row.component)}${row.brand ? " · " + escapeHtml(row.brand) : ""}</div></td>
        <td>${vendorName(row.vendor)}<div class="muted">${monthText(row.month)}</div></td>
        <td class="num">${formatPrice(row.previous)}</td>
        <td class="num">${formatPrice(row.price)}</td>
        <td class="num">${changeHtml((row.price / row.previous - 1) * 100)}</td>
      </tr>`
      )
      .join("")}</tbody></table></div>`;
}

async function renderMovers(container, filter = () => true, limit = 15) {
  const movers = await loadMovers();
  if (!container.isConnected) return;
  container.innerHTML = `
    <div class="card"><h3>Biggest price drops (latest list per shop)</h3>${moversTable(movers.drops.filter(filter).slice(0, limit))}</div>
    <div class="card"><h3>Biggest price rises (latest list per shop)</h3>${moversTable(movers.rises.filter(filter).slice(0, limit))}</div>`;
}

function renderOverview() {
  const { meta } = state;
  const overall = seriesFor("all");
  const latestPosition = lastIndex(overall.n);
  view.innerHTML = `
    <section><h2>Overview</h2><p class="muted">${monthText(meta.months[0])} – ${monthText(meta.months.at(-1))}, ${meta.vendors.length} shops</p></section>
    <section class="grid tiles">
      ${tile("Market index", formatIndex(latestValue(overall.index)), `since start ${changeHtml(percentChange(overall.index, Infinity))}`)}
      ${tile("Last month", changeHtml(percentChange(overall.index, 1)), "index change")}
      ${tile("Last 12 months", changeHtml(percentChange(overall.index, 12)), "index change")}
      ${tile("Listings", formatCount(overall.n[latestPosition]), `in ${monthText(meta.months[latestPosition])}`)}
      ${tile("Unique items", formatCount(meta.totals.items), `${formatCount(meta.totals.tracked_items)} with 3+ months of history`)}
      ${tile("Price moves", `<span class="up">▲${formatCount(overall.up[latestPosition])}</span> <span class="down">▼${formatCount(overall.down[latestPosition])}</span>`, "items repriced last month")}
    </section>
    <section class="grid two">
      <div class="card"><h3>Market price index (all shops, all components)</h3><div class="chart" id="overall-index"></div></div>
      <div class="card"><h3>Price moves per month (items repriced vs previous list)</h3><div class="chart" id="overall-moves"></div></div>
    </section>
    <section><h3>Components — price index, click to drill down</h3><div class="grid multiples" id="component-multiples"></div></section>
    <section class="grid two" id="movers"></section>`;
  lineChart(document.getElementById("overall-index"), [
    { label: "Market index", values: overall.index, color: cssVar("--accent") },
  ]);
  lineChart(
    document.getElementById("overall-moves"),
    [
      { label: "Price rises", values: overall.up.map((value, position) => (position === 0 ? null : value)), color: seriesColor(1) },
      { label: "Price drops", values: overall.down.map((value, position) => (position === 0 ? null : value)), color: seriesColor(0) },
    ],
    { format: formatCount }
  );
  smallMultiples(
    document.getElementById("component-multiples"),
    meta.components
      .map((component) => ({ label: component, href: `#/components/${encodeURIComponent(component)}`, series: seriesFor(`component:${component}`) }))
      .filter((entry) => entry.series)
  );
  renderMovers(document.getElementById("movers"));
}

function summaryRow(label, series, href, extraCells = "") {
  const latest = lastIndex(series.n);
  return `<tr class="clickable" data-href="${href}">
    <td>${label}</td>${extraCells}
    <td class="num">${formatCount(series.n[latest])}</td>
    <td class="num">${formatIndex(latestValue(series.index))}</td>
    <td class="num">${changeHtml(percentChange(series.index, 1))}</td>
    <td class="num">${changeHtml(percentChange(series.index, 3))}</td>
    <td class="num">${changeHtml(percentChange(series.index, 12))}</td>
  </tr>`;
}

function summaryTable(headLabel, rows, extraHead = "") {
  return `<div class="table-wrap"><table>
    <thead><tr><th>${headLabel}</th>${extraHead}<th class="num">Listings (latest)</th><th class="num">Index</th><th class="num">1m</th><th class="num">3m</th><th class="num">12m</th></tr></thead>
    <tbody>${rows.join("")}</tbody></table></div>`;
}

function wireRowLinks(container) {
  container.addEventListener("click", (event) => {
    const row = event.target.closest("tr[data-href]");
    if (row) location.hash = row.dataset.href;
  });
}

function chipsHtml(options, selected, hrefFor) {
  return `<div class="chips">${options
    .map(
      (option) =>
        `<a class="chip ${option.value === selected ? "active" : ""}" href="${hrefFor(option.value)}" style="text-decoration:none">${escapeHtml(option.label)}</a>`
    )
    .join("")}</div>`;
}

function renderShops(selectedVendor) {
  const { meta } = state;
  const vendor = meta.vendors.includes(selectedVendor) ? selectedVendor : null;
  view.innerHTML = `
    <section><h2>Shops</h2><p class="muted">Price index and catalogue size per shop. Pick a shop to see its components.</p></section>
    <section class="grid two">
      <div class="card"><h3>Price index by shop</h3><div class="chart" id="shop-index"></div></div>
      <div class="card"><h3>Listings per month by shop</h3><div class="chart" id="shop-listings"></div></div>
    </section>
    <section class="card"><h3>Shop summary</h3><div id="shop-table">${summaryTable(
      "Shop",
      meta.vendors.map((name) =>
        summaryRow(`<span class="swatch" style="background:${vendorColor(name)}"></span>${vendorName(name)}`, seriesFor(`vendor:${name}`), `#/shops/${name}`, `<td>${monthText(meta.vendor_latest_month[name])}</td>`)
      ),
      "<th>Latest list</th>"
    )}</div></section>
    <section>
      <h3>Components by shop</h3>
      ${chipsHtml(meta.vendors.map((name) => ({ value: name, label: vendorName(name) })), vendor, (name) => `#/shops/${name}`)}
    </section>
    <section class="grid multiples" id="shop-multiples">${vendor ? "" : '<p class="muted">Select a shop above.</p>'}</section>
    <section class="grid two" id="movers"></section>`;
  lineChart(
    document.getElementById("shop-index"),
    meta.vendors.map((name) => ({ label: vendorName(name), values: seriesFor(`vendor:${name}`).index, color: vendorColor(name) }))
  );
  lineChart(
    document.getElementById("shop-listings"),
    meta.vendors.map((name) => ({
      label: vendorName(name),
      values: seriesFor(`vendor:${name}`).n.map((value) => value || null),
      color: vendorColor(name),
    })),
    { format: formatCount }
  );
  wireRowLinks(document.getElementById("shop-table"));
  if (!vendor) return;
  smallMultiples(
    document.getElementById("shop-multiples"),
    meta.components
      .map((component) => ({
        label: component,
        href: `#/components/${encodeURIComponent(component)}`,
        series: seriesFor(`vendor:${vendor}|${component}`),
      }))
      .filter((entry) => entry.series)
  );
  renderMovers(document.getElementById("movers"), (row) => row.vendor === vendor, 10);
}

function renderComponents(selectedComponent) {
  const { meta } = state;
  const component = meta.components.includes(selectedComponent) ? selectedComponent : meta.components[0];
  const overall = seriesFor(`component:${component}`);
  const vendors = meta.vendors.filter((name) => seriesFor(`vendor:${name}|${component}`));
  const brandRows = meta.brands
    .map((brand) => ({ brand, series: seriesFor(`brand:${brand}|${component}`) }))
    .filter((entry) => entry.series && latestValue(entry.series.n) > 0)
    .sort((a, b) => b.series.n.reduce((sum, value) => sum + value, 0) - a.series.n.reduce((sum, value) => sum + value, 0));
  view.innerHTML = `
    <section><h2>Components</h2>
      ${chipsHtml(meta.components.map((name) => ({ value: name, label: name })), component, (name) => `#/components/${encodeURIComponent(name)}`)}
    </section>
    <section class="grid tiles">
      ${tile(`${escapeHtml(component)} index`, formatIndex(latestValue(overall.index)), `since start ${changeHtml(percentChange(overall.index, Infinity))}`)}
      ${tile("Last 3 months", changeHtml(percentChange(overall.index, 3)), "index change")}
      ${tile("Last 12 months", changeHtml(percentChange(overall.index, 12)), "index change")}
      ${tile("Median listed price", formatPrice(latestValue(overall.median)), "latest month, mix-dependent")}
    </section>
    <section class="grid two">
      <div class="card"><h3>${escapeHtml(component)} price index by shop</h3><div class="chart" id="component-index"></div></div>
      <div class="card"><h3>${escapeHtml(component)} listings by shop</h3><div class="chart" id="component-listings"></div></div>
    </section>
    <section class="card"><h3>${escapeHtml(component)} by brand</h3><div id="brand-table">${
      brandRows.length
        ? summaryTable("Brand", brandRows.map((entry) => summaryRow(escapeHtml(entry.brand), entry.series, `#/brands/${encodeURIComponent(entry.brand)}`)))
        : '<p class="muted">No tracked brands in this component.</p>'
    }</div></section>
    <section class="grid two" id="movers"></section>`;
  lineChart(document.getElementById("component-index"), [
    { label: "All shops", values: overall.index, color: cssVar("--neutral-line"), width: 3, dash: [6, 4] },
    ...vendors.map((name) => ({ label: vendorName(name), values: seriesFor(`vendor:${name}|${component}`).index, color: vendorColor(name) })),
  ]);
  lineChart(
    document.getElementById("component-listings"),
    vendors.map((name) => ({
      label: vendorName(name),
      values: seriesFor(`vendor:${name}|${component}`).n.map((value) => value || null),
      color: vendorColor(name),
    })),
    { format: formatCount }
  );
  wireRowLinks(document.getElementById("brand-table"));
  renderMovers(document.getElementById("movers"), (row) => row.component === component, 10);
}

function renderBrands(selectedBrand) {
  const { meta } = state;
  const brandTotals = meta.brands
    .map((brand) => ({ brand, series: seriesFor(`brand:${brand}`) }))
    .filter((entry) => entry.series)
    .sort((a, b) => b.series.n.reduce((sum, value) => sum + value, 0) - a.series.n.reduce((sum, value) => sum + value, 0));
  const brand = brandTotals.some((entry) => entry.brand === selectedBrand) ? selectedBrand : brandTotals[0].brand;
  const series = seriesFor(`brand:${brand}`);
  view.innerHTML = `
    <section><h2>Brands</h2>
      <div class="controls"><label for="brand-select">Brand</label>
        <select id="brand-select">${brandTotals
          .map((entry) => `<option value="${escapeHtml(entry.brand)}" ${entry.brand === brand ? "selected" : ""}>${escapeHtml(entry.brand)}</option>`)
          .join("")}</select></div>
    </section>
    <section class="grid tiles">
      ${tile(`${escapeHtml(brand)} index`, formatIndex(latestValue(series.index)), `since start ${changeHtml(percentChange(series.index, Infinity))}`)}
      ${tile("Last 3 months", changeHtml(percentChange(series.index, 3)), "index change")}
      ${tile("Last 12 months", changeHtml(percentChange(series.index, 12)), "index change")}
      ${tile("Listings", formatCount(latestValue(series.n)), "latest month")}
    </section>
    <section class="card"><h3>${escapeHtml(brand)} vs market price index</h3><div class="chart" id="brand-index"></div></section>
    <section><h3>${escapeHtml(brand)} by component</h3><div class="grid multiples" id="brand-multiples"></div></section>
    <section class="card"><h3>All tracked brands</h3><div id="brands-table">${summaryTable(
      "Brand",
      brandTotals.map((entry) => summaryRow(escapeHtml(entry.brand), entry.series, `#/brands/${encodeURIComponent(entry.brand)}`))
    )}</div></section>
    <section class="grid two" id="movers"></section>`;
  document.getElementById("brand-select").addEventListener("change", (event) => {
    location.hash = `#/brands/${encodeURIComponent(event.target.value)}`;
  });
  lineChart(document.getElementById("brand-index"), [
    { label: "Market", values: seriesFor("all").index, color: cssVar("--neutral-line"), width: 3, dash: [6, 4] },
    { label: brand, values: series.index, color: seriesColor(0) },
  ]);
  smallMultiples(
    document.getElementById("brand-multiples"),
    meta.components
      .map((component) => ({
        label: component,
        href: `#/components/${encodeURIComponent(component)}`,
        series: seriesFor(`brand:${brand}|${component}`),
      }))
      .filter((entry) => entry.series && entry.series.n.reduce((sum, value) => sum + value, 0) >= 20)
  );
  wireRowLinks(document.getElementById("brands-table"));
  renderMovers(document.getElementById("movers"), (row) => row.brand === brand, 10);
}

async function loadItems() {
  if (!state.items) {
    state.items = await fetchJson("data/items.json");
    state.itemSearchText = state.items.map((row) => row[0].toLowerCase());
  }
  return state.items;
}

function itemValues(row) {
  const values = new Array(state.meta.months.length).fill(null);
  for (const [monthPosition, price] of row[4]) values[monthPosition] = price;
  return values;
}

function itemLabel(row) {
  return `${row[0]} (${vendorName(state.meta.vendors[row[1]])})`;
}

async function renderItems() {
  const { meta } = state;
  view.innerHTML = `
    <section><h2>Items</h2><p class="muted">Search ${formatCount(meta.totals.tracked_items)} items listed in at least 3 months. Click rows to compare (up to 8).</p></section>
    <section class="card"><h3>Price history</h3><div class="chart" id="item-chart"></div><div id="compare-list" class="chips"></div></section>
    <section class="card">
      <div class="controls">
        <input type="search" id="item-query" placeholder="e.g. RTX 5070, B650M, 990 Pro" autocomplete="off">
        <select id="item-vendor"><option value="">All shops</option>${meta.vendors.map((name, position) => `<option value="${position}">${vendorName(name)}</option>`).join("")}</select>
        <select id="item-component"><option value="">All components</option>${meta.components.map((name, position) => `<option value="${position}">${escapeHtml(name)}</option>`).join("")}</select>
      </div>
      <div id="item-results"><p class="muted">Loading items…</p></div>
    </section>`;
  const items = await loadItems();
  if (!document.getElementById("item-results")) return;
  const query = document.getElementById("item-query");
  const vendorSelect = document.getElementById("item-vendor");
  const componentSelect = document.getElementById("item-component");
  let timer;
  const update = () => renderItemResults(items, query.value, vendorSelect.value, componentSelect.value);
  query.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(update, 120);
  });
  vendorSelect.addEventListener("change", update);
  componentSelect.addEventListener("change", update);
  document.getElementById("item-results").addEventListener("click", (event) => {
    const row = event.target.closest("tr[data-item]");
    if (!row) return;
    toggleCompare(Number(row.dataset.item));
  });
  document.getElementById("compare-list").addEventListener("click", (event) => {
    const chip = event.target.closest("[data-item]");
    if (chip) toggleCompare(Number(chip.dataset.item));
  });
  if (!state.compare.length) state.compare = [0];
  update();
  renderCompare();
}

function toggleCompare(position) {
  const existing = state.compare.indexOf(position);
  if (existing >= 0) state.compare.splice(existing, 1);
  else if (state.compare.length < 8) state.compare.push(position);
  renderCompare();
}

function renderCompare() {
  const container = document.getElementById("item-chart");
  if (!container) return;
  destroyCharts();
  container.innerHTML = "";
  const rows = state.compare.map((position) => state.items[position]);
  document.getElementById("compare-list").innerHTML = rows
    .map(
      (row, slot) =>
        `<button class="chip" data-item="${state.compare[slot]}" title="Remove"><span class="swatch" style="background:${seriesColor(slot)}"></span>${escapeHtml(itemLabel(row))} ✕</button>`
    )
    .join("");
  if (!rows.length) {
    container.innerHTML = '<p class="muted">Select items below.</p>';
    return;
  }
  lineChart(
    container,
    rows.map((row, slot) => ({ label: itemLabel(row), values: itemValues(row), color: seriesColor(slot) })),
    { format: formatPrice }
  );
}

function renderItemResults(items, queryText, vendorValue, componentValue) {
  const terms = queryText.toLowerCase().split(/\s+/).filter(Boolean);
  const vendorFilter = vendorValue === "" ? null : Number(vendorValue);
  const componentFilter = componentValue === "" ? null : Number(componentValue);
  const matches = [];
  for (let position = 0; position < items.length && matches.length < 100; position++) {
    const row = items[position];
    if (vendorFilter != null && row[1] !== vendorFilter) continue;
    if (componentFilter != null && row[2] !== componentFilter) continue;
    const text = state.itemSearchText[position];
    if (terms.every((term) => text.includes(term))) matches.push(position);
  }
  const container = document.getElementById("item-results");
  if (!matches.length) {
    container.innerHTML = '<p class="muted">No matches.</p>';
    return;
  }
  container.innerHTML = `<div class="table-wrap"><table>
    <thead><tr><th>Item</th><th>Shop</th><th class="num">First</th><th class="num">Latest</th><th class="num">Change</th><th class="num">Months</th></tr></thead>
    <tbody>${matches
      .map((position) => {
        const row = items[position];
        const points = row[4];
        const first = points[0];
        const last = points.at(-1);
        return `<tr class="clickable" data-item="${position}">
          <td class="wrap">${escapeHtml(row[0])}<div class="muted">${escapeHtml(state.meta.components[row[2]])}${row[3] >= 0 ? " · " + escapeHtml(state.meta.brands[row[3]]) : ""}</div></td>
          <td>${vendorName(state.meta.vendors[row[1]])}</td>
          <td class="num">${formatPrice(first[1])}<div class="muted">${monthText(state.meta.months[first[0]])}</div></td>
          <td class="num">${formatPrice(last[1])}<div class="muted">${monthText(state.meta.months[last[0]])}</div></td>
          <td class="num">${changeHtml((last[1] / first[1] - 1) * 100)}</td>
          <td class="num">${points.length}</td>
        </tr>`;
      })
      .join("")}</tbody></table></div>`;
}

async function init() {
  const [meta, series] = await Promise.all([fetchJson("data/meta.json"), fetchJson("data/series.json")]);
  state.meta = meta;
  state.series = series;
  state.times = meta.months.map((month) => {
    const [year, monthNumber] = month.split("-").map(Number);
    return Date.UTC(year, monthNumber - 1, 1) / 1000;
  });
  document.getElementById("updated").textContent = `Updated ${new Date(meta.generated_at).toLocaleString("en-SG", { dateStyle: "medium", timeStyle: "short" })}`;
  window.addEventListener("hashchange", route);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", route);
  route();
}

init().catch((error) => {
  view.innerHTML = `<p class="muted">Failed to load data: ${escapeHtml(error.message)}</p>`;
});
