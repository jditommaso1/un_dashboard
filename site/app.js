/* UN Alignment — map + chart. Data from site/data (built by pipeline/). */
(async function () {
  "use strict";

  // ---------- Data ----------
  const [meta, topo] = await Promise.all([
    fetch("data/meta.json").then((r) => r.json()),
    fetch("data/geo.json").then((r) => r.json()),
  ]);
  const features = topojson.feature(topo, topo.objects.f).features;
  const Y0 = meta.years[0], Y1 = meta.years[meta.years.length - 1];
  const S = meta.status_codes;
  const MIN_VOTES = meta.config.min_votes;
  const DEPENDENT = new Set(["colony", "protectorate", "mandate", "occupied", "dependent"]);

  const refCache = new Map();
  function loadRef(cow) {
    if (!refCache.has(cow)) refCache.set(cow, fetch(`data/ref/${cow}.json`).then((r) => r.json()));
    return refCache.get(cow);
  }

  const idx = (y) => y - Y0;
  const country = (cow) => meta.countries[String(cow)];
  function nameOf(cow, y) {
    const c = country(cow);
    if (!c) return null;
    const h = c.hist.find(([a, b]) => a <= y && y <= b);
    return h ? h[2] : c.name;
  }
  const statusOf = (cow, y) => (country(cow) ? country(cow).status[idx(y)] : S.non_member);
  const override = (kind, cow, y) =>
    meta.map_overrides.find((o) => o.kind === kind && o.cow === cow && o.from_year <= y && y <= o.to_year);
  const predOf = (cow) => meta.predecessors.find((p) => p.successor === cow);
  const visible = (f, y) => f.properties.y.some(([a, b]) => a <= y && y <= b);
  const ordinal = (n) => n + (["th", "st", "nd", "rd"][(n % 100 - 20) % 10] || ["th", "st", "nd", "rd"][n % 100] || "th");
  const fmt = (s) => s.toFixed(2);

  // ---------- Colour ----------
  // Diverging: vivid red (opposed) -> dim grey (0.5, neutral) -> vivid blue (aligned). The inner
  // stops keep chroma high until close to 0.5, so moderate scores stay saturated rather than greyish.
  const color = d3.scaleLinear()
    .domain([0, 0.3, 0.5, 0.7, 1])
    .range(["#ff1e46", "#e8325e", "#5a5f7a", "#2f86f0", "#14b8ff"])
    .interpolate(d3.interpolateLab).clamp(true);

  // ---------- State (mirrored in the URL hash) ----------
  const state = { ref: 2, year: 1985, sel: null };
  (function readHash() {
    const h = new URLSearchParams(location.hash.slice(1));
    const r = +h.get("ref"), y = +h.get("year"), c = +h.get("c");
    if (country(r)) state.ref = r;
    if (y >= Y0 && y <= Y1) state.year = y;
    if (country(c)) state.sel = c;
  })();
  function writeHash() {
    const h = new URLSearchParams({ ref: state.ref, year: state.year });
    if (state.sel) h.set("c", state.sel);
    history.replaceState(null, "", "#" + h);
  }

  // ---------- Controls ----------
  const refSel = document.getElementById("ref");
  const byName = Object.entries(meta.countries).sort((a, b) => a[1].name.localeCompare(b[1].name));
  const featured = document.createElement("optgroup");
  featured.label = "Major powers and examples";
  meta.featured_refs.forEach((c) => featured.append(new Option(country(c).name, c)));
  const all = document.createElement("optgroup");
  all.label = "All member states";
  byName.forEach(([c, v]) => all.append(new Option(v.name, c)));
  refSel.append(featured, all);

  const yearIn = document.getElementById("year");
  const yearOut = document.getElementById("year-out");
  const yearInfo = document.getElementById("year-info");
  yearIn.min = Y0; yearIn.max = Y1;

  const playBtn = document.getElementById("play");
  const playIcon = document.getElementById("play-icon");
  let timer = null;
  function setPlaying(on) {
    if (on && !timer) {
      if (state.year >= Y1) setYear(Y0);
      timer = setInterval(() => (state.year >= Y1 ? setPlaying(false) : setYear(state.year + 1)), 650);
    } else if (!on && timer) {
      clearInterval(timer);
      timer = null;
    }
    playIcon.setAttribute("d", timer ? "M4 2.5h3v11H4zM9 2.5h3v11H9z" : "M4 2.5v11l9-5.5z");
    playBtn.setAttribute("aria-label", timer ? "Pause" : "Play through the years");
  }
  playBtn.addEventListener("click", () => setPlaying(!timer));
  yearIn.addEventListener("input", () => { setPlaying(false); setYear(+yearIn.value); });
  refSel.addEventListener("change", () => setRef(+refSel.value));

  // ---------- Map ----------
  const W = 960;
  const fc = { type: "FeatureCollection", features };
  // Equirectangular with standard parallel 23°: x = λ·cos 23°, y = φ. Relative to plain
  // equirectangular it is 8% taller for its width, so the narrower (92%) map keeps full height.
  const K = Math.cos(23.07 * Math.PI / 180); // 0.92
  const eqRaw = (l, p) => [l * K, p];
  eqRaw.invert = (x, y) => [x / K, y];
  const projection = d3.geoProjection(eqRaw).fitWidth(W - 16, fc);
  const path = d3.geoPath(projection);
  const [[, by0], [, by1]] = path.bounds(fc);
  projection.translate([projection.translate()[0] + 8, projection.translate()[1] - by0 + 8]);
  const H = Math.ceil(by1 - by0 + 16);

  const svg = d3.select("#map").attr("viewBox", `0 0 ${W} ${H}`);
  const defs = svg.append("defs");
  function hatch(id, bgVar, lineVar, angle, gap = 4, width = 1) {
    const p = defs.append("pattern").attr("id", id).attr("patternUnits", "userSpaceOnUse")
      .attr("width", gap).attr("height", gap).attr("patternTransform", `rotate(${angle})`);
    p.append("rect").attr("width", gap).attr("height", gap).style("fill", `var(${bgVar})`);
    return p.append("line").attr("x1", 0).attr("y1", 0).attr("x2", 0).attr("y2", gap)
      .style("stroke", `var(${lineVar})`).style("stroke-width", width);
  }
  hatch("pat-dep", "--dependent-bg", "--dependent-line", 45, 4, 1);
  hatch("pat-occ", "--occupied-bg", "--occupied-line", 135, 3.5, 1.2);
  const repLine = hatch("pat-rep", "--nonmember", "--nonmember", 45, 5, 2.2);

  // Glow: a tight and a wide blur of the countries layered under the crisp shapes. The filter sits
  // on an untransformed wrapper so the halo keeps its on-screen size when zoomed.
  const glow = defs.append("filter").attr("id", "glow").attr("x", "-5%").attr("y", "-5%")
    .attr("width", "110%").attr("height", "110%").attr("color-interpolation-filters", "sRGB");
  glow.append("feGaussianBlur").attr("in", "SourceGraphic").attr("stdDeviation", 1.6).attr("result", "near");
  glow.append("feGaussianBlur").attr("in", "SourceGraphic").attr("stdDeviation", 6).attr("result", "far");
  glow.append("feColorMatrix").attr("in", "far").attr("type", "matrix")
    .attr("values", "1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 0.9 0").attr("result", "farDim");
  const merge = glow.append("feMerge");
  ["farDim", "near", "SourceGraphic"].forEach((r) => merge.append("feMergeNode").attr("in", r));

  svg.append("rect").attr("class", "ocean").attr("width", W).attr("height", H);
  const root = svg.append("g").attr("filter", "url(#glow)").append("g");
  root.append("path").attr("class", "graticule").attr("d", path(d3.geoGraticule10()));
  const countryPaths = root.append("g").selectAll("path").data(features).join("path")
    .attr("class", "country").attr("d", path);
  const dotted = features.filter((f) => f.properties.pt);
  const dotG = root.append("g");
  const dots = dotG.selectAll("circle.dot").data(dotted).join("circle").attr("class", "dot")
    .attr("cx", (f) => projection(f.properties.pt)[0]).attr("cy", (f) => projection(f.properties.pt)[1]);
  const hits = dotG.selectAll("circle.hit").data(dotted).join("circle").attr("class", "hit")
    .attr("cx", (f) => projection(f.properties.pt)[0]).attr("cy", (f) => projection(f.properties.pt)[1]);
  function sizeDots(k) { dots.attr("r", 2.6 / k); hits.attr("r", 7 / k); }
  sizeDots(1);

  const zoom = d3.zoom().scaleExtent([1, 12]).translateExtent([[0, 0], [W, H]])
    .filter((e) => (e.type === "wheel" ? e.ctrlKey || e.metaKey : !e.button))
    .on("zoom", (e) => { root.attr("transform", e.transform); sizeDots(e.transform.k); });
  svg.call(zoom);
  document.querySelectorAll(".zoom button").forEach((b) => b.addEventListener("click", () => {
    const z = b.dataset.zoom;
    if (z === "reset") svg.transition().call(zoom.transform, d3.zoomIdentity);
    else svg.transition().call(zoom.scaleBy, z === "in" ? 1.6 : 1 / 1.6);
  }));

  let refData = null;

  /** Everything the map and tooltip need to know about one feature in the current year. */
  function describe(f) {
    const p = f.properties, y = state.year;
    const refName = nameOf(state.ref, y) || country(state.ref).name;
    if (p.k === "occ") {
      return { fill: "url(#pat-occ)", name: p.n, sub: `Held by ${nameOf(p.c, y) || "another state"}`, note: p.note };
    }
    const sf = p.c != null ? override("score_from", p.c, y) : null;
    const seat = sf ? sf.value : p.c;
    const name = sf ? sf.label.split(" — ")[0] : (country(p.c) ? nameOf(p.c, y) : p.n);
    const note = sf && sf.label.includes(" — ") ? sf.label.split(" — ")[1] : null;
    const st = seat != null ? statusOf(seat, y) : S.non_member;

    if (st !== S.non_member) {
      const d = { name, note, cow: seat };
      if (seat === state.ref) return { ...d, fill: "var(--ref)", sub: "Reference country" };
      if (statusOf(state.ref, y) === S.non_member) return { ...d, fill: "var(--noscore)", sub: `${refName} did not hold a UN seat in this session` };
      if (st === S.suspended) return { ...d, fill: "var(--noscore)", sub: "Suspended from participation this session" };
      if (st === S.absent) return { ...d, fill: "var(--noscore)", sub: "Did not vote this session", note: note || "Usually the loss of a vote for unpaid dues (UN Charter Article 19)." };
      const cell = refData && refData.d[seat] ? refData.d[seat][idx(y)] : null;
      if (!cell) return { ...d, fill: "var(--noscore)", sub: `No contested votes shared with ${refName}` };
      const [s, n] = cell;
      if (n < MIN_VOTES) return { ...d, fill: "var(--noscore)", score: s / 1000, n, sub: `Too few shared contested votes to score (fewer than ${MIN_VOTES})` };
      return { ...d, fill: color(s / 1000), score: s / 1000, n };
    }

    const clickable = country(p.c) ? p.c : null;
    const rep = p.c != null ? override("represented_by", p.c, y) : null;
    if (rep) {
      const cell = refData && refData.d[rep.value] ? refData.d[rep.value][idx(y)] : null;
      const repFill = rep.value === state.ref ? "var(--ref)" : cell && cell[1] >= MIN_VOTES ? color(cell[0] / 1000) : "var(--noscore)";
      return { name: p.n, fill: "url(#pat-rep)", repFill, sub: rep.label, cow: clickable,
        note: cell ? `The seat's alignment: ${fmt(cell[0] / 1000)} on ${cell[1]} votes` : null };
    }
    const vacancy = p.c != null ? override("seat_label", p.c, y) : null;
    if (vacancy) return { name, fill: "var(--nonmember)", sub: vacancy.label, cow: clickable };
    if (DEPENDENT.has(p.s)) {
      const owner = p.on || (p.o != null ? nameOf(p.o, y) : null);
      const kind = p.s === "dependent" ? "Dependent territory" : `Dependent territory (${p.s})`;
      return { name: p.n, fill: "url(#pat-dep)", sub: owner ? `${kind} of ${owner}` : kind, cow: clickable };
    }
    return { name: country(p.c) ? nameOf(p.c, y) : p.n, fill: "var(--nonmember)", sub: "Not a UN member", cow: clickable };
  }

  let described = new Map();
  function renderMap() {
    const y = state.year;
    described = new Map();
    let repFill = null;
    features.forEach((f) => { if (visible(f, y)) described.set(f, describe(f)); });
    described.forEach((d) => { if (d.repFill) repFill = d.repFill; });
    if (repFill) repLine.style("stroke", repFill);
    const show = (f) => described.has(f);
    countryPaths.style("display", (f) => (show(f) ? null : "none"))
      .style("fill", (f) => (show(f) ? described.get(f).fill : null))
      .classed("selected", (f) => show(f) && state.sel != null && described.get(f).cow === state.sel);
    dots.style("display", (f) => (show(f) ? null : "none"))
      .style("fill", (f) => (show(f) ? described.get(f).fill : null))
      .classed("selected", (f) => show(f) && state.sel != null && described.get(f).cow === state.sel);
    hits.style("display", (f) => (show(f) ? null : "none"));
    renderLegend(!!repFill);
  }

  // ---------- Tooltip ----------
  const tip = document.getElementById("tooltip");
  const wrap = document.querySelector(".map-wrap");
  function showTip(e, f) {
    const d = described.get(f);
    if (!d) return;
    const refName = nameOf(state.ref, state.year);
    let html = `<div class="tt-name">${d.name}</div>`;
    if (d.score != null && d.n >= MIN_VOTES) {
      html += `<div class="tt-score" style="color:${color(d.score)}">${fmt(d.score)}</div><div class="tt-sub">agreement with ${refName} on ${d.n} contested vote${d.n === 1 ? "" : "s"}</div>`;
    } else if (d.score != null) {
      html += `<div class="tt-sub">${d.sub} — ${fmt(d.score)} on ${d.n} vote${d.n === 1 ? "" : "s"}</div>`;
    } else if (d.sub) {
      html += `<div class="tt-sub">${d.sub}</div>`;
    }
    if (d.note) html += `<div class="tt-note">${d.note}</div>`;
    tip.innerHTML = html;
    tip.hidden = false;
    const r = wrap.getBoundingClientRect();
    const x = e.clientX - r.left, yy = e.clientY - r.top;
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    tip.style.left = Math.min(Math.max(8, x + 14), r.width - tw - 8) + "px";
    tip.style.top = (yy + 14 + th > r.height ? yy - th - 10 : yy + 14) + "px";
  }
  function hoverOn(e, f) {
    countryPaths.classed("hover", (g) => g === f);
    dots.classed("hover", (g) => g === f);
    showTip(e, f);
  }
  function hoverOff() {
    countryPaths.classed("hover", false);
    dots.classed("hover", false);
    tip.hidden = true;
  }
  [countryPaths, hits].forEach((sel) => sel
    .on("pointermove", hoverOn).on("pointerleave", hoverOff)
    .on("click", (e, f) => {
      const d = described.get(f);
      if (d && d.cow != null && d.cow !== state.ref) select(d.cow);
    }));

  // ---------- Legend ----------
  const legend = document.getElementById("legend");
  function swatch(style) { return `<span class="sw" style="${style}"></span>`; }
  function patternSwatch(id) {
    return `<svg class="sw" viewBox="0 0 14 14" aria-hidden="true"><rect width="14" height="14" fill="url(#${id})"/></svg>`;
  }
  function renderLegend(showRep) {
    const refName = nameOf(state.ref, state.year) || country(state.ref).name;
    const stops = d3.range(0, 1.001, 0.1).map((t) => `${color(t)} ${t * 100}%`).join(",");
    legend.innerHTML = `
      <div class="ramp">
        <span class="ramp-title">Agreement with ${refName}</span>
        <span class="ramp-bar" style="background:linear-gradient(to right,${stops})"></span>
        <span class="ramp-ticks"><span>0</span><span>0.25</span><span>0.5</span><span>0.75</span><span>1</span></span>
        <span class="ramp-words"><span>Mostly opposed</span><span>Neutral</span><span>Mostly aligned</span></span>
      </div>
      <div class="keys">
        <span class="key">${swatch("background:var(--ref)")}Reference</span>
        <span class="key">${swatch("background:var(--noscore)")}Member, no score this session</span>
        <span class="key">${swatch("background:var(--nonmember)")}Not a UN member</span>
        <span class="key">${patternSwatch("pat-dep")}Dependent territory</span>
        <span class="key">${patternSwatch("pat-occ")}Occupied or annexed, not recognised by the UN</span>
        ${showRep ? `<span class="key">${patternSwatch("pat-rep")}Represented by the Republic of China</span>` : ""}
      </div>`;
  }

  // ---------- Year info ----------
  function renderYear() {
    const y = state.year, info = meta.year_info[idx(y)];
    yearIn.value = y;
    yearOut.textContent = `${y} · ${ordinal(info.session)} session`;
    const refName = nameOf(state.ref, y) || country(state.ref).name;
    const span = `${y}–${String(y + 1).slice(2)}`;
    let text;
    if (info.decisions === 0) {
      text = `<strong>No recorded votes.</strong> The ${ordinal(info.session)} session (${span}) avoided all recorded votes during the dispute over arrears under Article 19.`;
    } else {
      text = `${ordinal(info.session)} session (${span}): <strong>${info.contested}</strong> of ${info.decisions} recorded votes on resolutions were contested.`;
      if (info.contested < MIN_VOTES) text += ` <strong>That is below the ${MIN_VOTES}-vote minimum, so no pair can be scored this session.</strong>`;
      const rs = statusOf(state.ref, y);
      if (rs === S.non_member) {
        text += ` <strong>${refName} did not hold a UN seat in this session.</strong>`;
        const rp = predOf(state.ref);
        if (rp && y <= rp.until && rp.predecessor !== state.ref) text += ` Choose ${nameOf(rp.predecessor, y)} to see it.`;
      }
      else if (rs !== S.member) text += ` <strong>${refName} cast no votes in this session.</strong>`;
    }
    yearInfo.innerHTML = text;
  }

  // ---------- Chart ----------
  const panel = document.getElementById("panel");
  const chartEl = document.getElementById("chart");
  document.getElementById("panel-close").addEventListener("click", () => select(null));
  document.getElementById("make-ref").addEventListener("click", () => {
    const old = state.ref;
    state.ref = state.sel;
    state.sel = old;
    refSel.value = state.ref;
    update();
  });

  // Keyboard/list access to the chart without the map.
  const pick = document.getElementById("pick");
  byName.forEach(([c, v]) => pick.append(new Option(v.name, c)));
  pick.addEventListener("change", () => select(pick.value ? +pick.value : null));

  async function chartSeries(target, ref) {
    const tp = predOf(target), rp = predOf(ref);
    const codeAt = (c, p, y) => (p && y <= p.until ? p.predecessor : c);
    const refs = new Set(meta.years.map((y) => codeAt(ref, rp, y)));
    const files = new Map(await Promise.all([...refs].map(async (c) => [c, await loadRef(c)])));
    return meta.years.map((y) => {
      const t = codeAt(target, tp, y), r = codeAt(ref, rp, y);
      const pred = (tp && y <= tp.until) || (rp && y <= rp.until);
      const cell = t !== r && files.get(r).d[t] ? files.get(r).d[t][idx(y)] : null;
      return { y, t, r, pred, s: cell ? cell[0] / 1000 : null, n: cell ? cell[1] : 0 };
    });
  }

  let chartToken = 0;
  let chartX = null;
  async function renderChart() {
    const token = ++chartToken;
    pick.value = state.sel == null ? "" : String(state.sel);
    if (state.sel == null) {
      panel.hidden = true;
      return;
    }
    const target = state.sel, ref = state.ref;
    const series = await chartSeries(target, ref);
    if (token !== chartToken) return;
    panel.hidden = false;
    const tName = country(target).name, rName = country(ref).name;
    document.getElementById("chart-title").textContent = `${tName} and ${rName}`;
    document.getElementById("chart-sub").textContent = "Agreement on contested votes, by session";
    document.getElementById("make-ref").textContent = `Use ${tName} as reference`;

    const scored = series.filter((d) => d.s != null && d.n >= MIN_VOTES);
    const cw = 320, ch = 150, m ={ t: 10, r: 10, b: 22, l: 32 };
    const x = d3.scaleLinear([Y0, Y1], [m.l, cw - m.r]);
    chartX = x;
    const yS = d3.scaleLinear([0, 1], [ch - m.b, m.t]);
    chartEl.innerHTML = "";
    const c = d3.select(chartEl).append("svg").attr("viewBox", `0 0 ${cw} ${ch}`)
      .attr("role", "img").attr("aria-label", `Line chart of ${tName}'s agreement with ${rName} by session`);
    [0, 0.25, 0.5, 0.75, 1].forEach((v) => {
      c.append("line").attr("class", v === 0 ? "baseline" : v === 0.5 ? "midline" : "gridline").attr("x1", m.l).attr("x2", cw - m.r).attr("y1", yS(v)).attr("y2", yS(v));
      c.append("text").attr("class", "tick-label").attr("x", m.l - 6).attr("y", yS(v) + 3.5).attr("text-anchor", "end").text(v === 0 || v === 1 ? v : v.toFixed(2));
    });
    [1950, 1970, 1990, 2010].forEach((v) =>
      c.append("text").attr("class", "tick-label").attr("x", x(v)).attr("y", ch - 6).attr("text-anchor", "middle").text(v));
    c.append("line").attr("class", "now-rule").attr("x1", x(state.year)).attr("x2", x(state.year)).attr("y1", m.t).attr("y2", ch - m.b);

    // Segments: consecutive scored sessions sharing solid/dashed style; a style change shares its join point.
    const segs = [];
    let cur = null;
    series.forEach((d, i) => {
      const ok = d.s != null && d.n >= MIN_VOTES;
      if (!ok) { cur = null; return; }
      if (cur && cur.pred === d.pred && series[i - 1] === cur.pts[cur.pts.length - 1]) cur.pts.push(d);
      else {
        const prev = series[i - 1];
        const start = cur && prev === cur.pts[cur.pts.length - 1] ? [prev] : [];
        cur = { pred: d.pred, pts: [...start, d] };
        segs.push(cur);
      }
    });
    const line = d3.line().x((d) => x(d.y)).y((d) => yS(d.s));
    segs.forEach((sg) => {
      if (sg.pts.length === 1) c.append("circle").attr("class", "marker").attr("r", 3).attr("cx", x(sg.pts[0].y)).attr("cy", yS(sg.pts[0].s));
      else c.append("path").attr("class", sg.pred ? "line pred" : "line").attr("d", line(sg.pts));
    });
    if (!scored.length) {
      const related = [predOf(ref), predOf(target)].some((p) => p && (p.predecessor === target || p.predecessor === ref));
      c.append("text").attr("class", "tick-label").attr("x", (m.l + cw - m.r) / 2).attr("y", ch / 2).attr("text-anchor", "middle")
        .text(related ? "One is the other's predecessor; they never sat together" : "No sessions with enough shared contested votes");
    }

    // Crosshair + tooltip
    const cross = c.append("line").attr("class", "cross").attr("y1", m.t).attr("y2", ch - m.b).style("display", "none");
    const mark = c.append("circle").attr("class", "marker").attr("r", 4).style("display", "none");
    let ctip = chartEl.querySelector(".chart-tip");
    if (!ctip) { ctip = document.createElement("div"); ctip.className = "chart-tip"; chartEl.append(ctip); }
    ctip.hidden = true;
    c.append("rect").attr("x", m.l).attr("y", 0).attr("width", cw - m.l - m.r).attr("height", ch - m.b).attr("fill", "transparent")
      .on("pointermove", (e) => {
        const [px] = d3.pointer(e);
        const yr = Math.round(x.invert(px));
        const d = series[idx(Math.max(Y0, Math.min(Y1, yr)))];
        cross.attr("x1", x(d.y)).attr("x2", x(d.y)).style("display", null);
        const ok = d.s != null && d.n >= MIN_VOTES;
        mark.style("display", ok ? null : "none").attr("cx", x(d.y)).attr("cy", ok ? yS(d.s) : 0);
        const who = [];
        if (d.t !== target || (predOf(target) && d.pred && d.y <= predOf(target).until)) who.push(nameOf(d.t, d.y));
        if (d.r !== ref || (predOf(ref) && d.pred && d.y <= predOf(ref).until)) who.push(`vs ${nameOf(d.r, d.y)}`);
        ctip.innerHTML = `<strong>${d.y}</strong> ` + (ok ? `${fmt(d.s)} · ${d.n} votes` : d.s != null ? `${d.n} vote${d.n === 1 ? "" : "s"}, too few` : "no score") +
          (who.length ? `<br><span style="color:var(--ink-2)">as ${who.join(" ")}</span>` : "");
        ctip.hidden = false;
        const scale = chartEl.clientWidth / cw;
        ctip.style.left = Math.min(x(d.y) * scale + 8, chartEl.clientWidth - ctip.offsetWidth) + "px";
      })
      .on("pointerleave", () => { cross.style("display", "none"); mark.style("display", "none"); ctip.hidden = true; })
      .on("click", (e) => { const yr = Math.round(x.invert(d3.pointer(e)[0])); setYear(Math.max(Y0, Math.min(Y1, yr))); });

    // Key for dashed predecessor periods
    const notes = [predOf(target), predOf(ref)].filter((p) => p && series.some((d) => d.pred && d.s != null));
    const dash = `<svg width="22" height="8" aria-hidden="true"><line x1="1" y1="4" x2="21" y2="4" stroke="var(--accent)" stroke-width="2" stroke-dasharray="4 3"/></svg>`;
    document.getElementById("chart-key").innerHTML = notes.length
      ? `${dash} Dashed: ${notes.map((p) => `${p.label} (to ${p.until})`).join("; ")}. Gaps: sessions with fewer than ${MIN_VOTES} shared contested votes.`
      : `Gaps: sessions with fewer than ${MIN_VOTES} shared contested votes, or no shared seat. Click the chart to jump to a year.`;

    // Data table
    const rows = series.filter((d) => d.s != null);
    document.getElementById("chart-table").innerHTML =
      `<thead><tr><th>Session</th><th>Score</th><th>Votes</th></tr></thead><tbody>` +
      rows.map((d) => `<tr><td>${d.y}${d.pred ? "*" : ""}</td><td>${d.n >= MIN_VOTES ? fmt(d.s) : "—"}</td><td>${d.n}</td></tr>`).join("") +
      `</tbody>` + (rows.some((d) => d.pred) ? `<caption style="caption-side:bottom;text-align:left;color:var(--ink-2)">* predecessor period</caption>` : "");
  }

  // ---------- Updates ----------
  async function update() {
    writeHash();
    refData = await loadRef(state.ref);
    renderYear();
    renderMap();
    renderChart();
  }
  function setYear(y) {
    state.year = y;
    writeHash();
    renderYear();
    renderMap();
    if (chartX) d3.select(chartEl).select(".now-rule").attr("x1", chartX(y)).attr("x2", chartX(y));
  }
  function setRef(c) { state.ref = c; if (state.sel === c) state.sel = null; update(); }
  function select(c) { state.sel = c; writeHash(); renderMap(); renderChart(); }

  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, select, textarea") || (e.key === " " && e.target.matches("button, summary"))) return;
    if (e.key === "ArrowRight") setYear(Math.min(Y1, state.year + 1));
    else if (e.key === "ArrowLeft") setYear(Math.max(Y0, state.year - 1));
    else if (e.key === " ") { e.preventDefault(); setPlaying(!timer); }
  });

  refSel.value = state.ref;
  const methodCfg = meta.config;
  document.getElementById("method-text").textContent =
    `The score is the average agreement between two states over the session's contested votes on whole draft resolutions: ` +
    `the same vote counts ${methodCfg.scoring.same}, yes against no ${methodCfg.scoring.yes_vs_no}, and a vote against an abstention ${methodCfg.scoring.vote_vs_abstain}. ` +
    `A vote is contested unless more than ${Math.round(methodCfg.contested.threshold * 100)}% of the states voting yes, no or abstain cast the same vote. ` +
    `Absences are left out, and pairs with fewer than ${MIN_VOTES} shared contested votes in a session are not scored.`;
  update();
})();
