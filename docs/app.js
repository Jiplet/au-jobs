/*
  app.js - renders the au-jobs treemap.

  What it does: fetches data.json (built by build_site.py), builds a two-level
  hierarchy (ANZSCO major group -> occupation unit group), and draws it as a D3
  treemap. Area is always employment. Colour is whichever metric the "Colour by"
  dropdown picks. Clicking a major group (or any tile inside it) zooms the whole
  canvas into that group's occupations; the breadcrumb takes you back out.
  Search dims non-matching tiles without changing the layout underneath them.

  No build step and no bundler: this is one plain script tag, loaded after the
  vendored D3 in vendor/d3.v7.min.js. Open docs/index.html through a local server
  (fetch() needs http://, not file://) - `make serve` does that for you.

  Colour ramps are the dataviz skill's validated default palette (sequential blue,
  diverging blue<->red), reused unchanged - see README design notes for why.
*/

(function () {
  'use strict';

  const svg = d3.select('#treemap');
  const tooltip = document.getElementById('tooltip');
  const legendEl = document.getElementById('legend');
  const breadcrumbEl = document.getElementById('breadcrumb');
  const crumbRoot = document.getElementById('crumb-root');
  const layerSelect = document.getElementById('layer-select');
  const searchInput = document.getElementById('search');
  const aboutToggle = document.getElementById('about-toggle');
  const aboutPanel = document.getElementById('about-panel');
  const noDataBanner = document.getElementById('no-data-banner');

  const SEQ_RAMP = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b'];
  const DIV_RAMP = ['#d03b3b', '#e89c9c', '#f0efec', '#9ec5f4', '#256abf'];
  const MISSING_FILL = '#e1e0d9';
  const SHORTAGE_ORDER = ['NS', 'R', 'M', 'S'];
  const SHORTAGE_COLOURS = { NS: '#cde2fb', R: '#6da7ec', M: '#256abf', S: '#0d366b' };
  const SHORTAGE_LABELS = { NS: 'No shortage', R: 'Regional shortage', M: 'Metropolitan shortage', S: 'National shortage' };

  const LAYER_META = {
    ai_exposure: { field: 'ai_exposure_score', kind: 'sequential', label: 'Digital AI exposure (0-10)', layerCountKey: 'ai_exposure', domainHint: [0, 10] },
    avg_weekly_earnings: { field: 'avg_weekly_earnings', kind: 'sequential', label: 'Average weekly earnings (AUD)', layerCountKey: 'earnings' },
    growth_5y_pct: { field: 'growth_5y_pct', kind: 'diverging', label: '5-year projected growth (%)', layerCountKey: 'growth' },
    shortage_rating: { field: 'shortage_rating', kind: 'ordinal', label: 'Skills shortage rating', layerCountKey: 'shortage' },
  };

  let dataset = null;
  let currentLayer = 'ai_exposure';
  let currentMajorCode = null; // null = show all major groups; otherwise zoomed into one
  let searchTerm = '';
  let resizeTimer = null;

  fetch('data.json')
    .then((r) => {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then((json) => {
      dataset = json;
      reportMissingLayers();
      render();
    })
    .catch((err) => {
      noDataBanner.style.display = 'block';
      noDataBanner.textContent = 'Could not load data.json: ' + err.message +
        ' (if you opened this file directly, run "make serve" and use http://localhost:8000 instead)';
    });

  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(render, 150);
  });

  layerSelect.addEventListener('change', () => {
    currentLayer = layerSelect.value;
    render();
  });

  searchInput.addEventListener('input', () => {
    searchTerm = searchInput.value.trim().toLowerCase();
    applySearchDimming();
  });

  aboutToggle.addEventListener('click', () => {
    aboutPanel.classList.toggle('open');
  });

  crumbRoot.addEventListener('click', () => {
    currentMajorCode = null;
    render();
  });

  function reportMissingLayers() {
    const notes = [];
    const layers = dataset.meta.layers;
    Object.values(LAYER_META).forEach((meta) => {
      if ((layers[meta.layerCountKey] || 0) === 0) {
        notes.push(meta.label + ' is not available in this build');
      }
    });
    if (notes.length) {
      noDataBanner.style.display = 'block';
      noDataBanner.textContent = notes.join('  |  ');
    }
  }

  // Occupations with no employment figure still need a small positive area so they
  // show up as a thin sliver (with a "no employment data" note in the tooltip)
  // rather than vanishing - d3's treemap sum can't lay out a zero-area node.
  function employmentValue(o) {
    if (o.employment_thousands !== null && o.employment_thousands !== undefined) {
      return o.employment_thousands;
    }
    return dataset._minEmployment != null ? dataset._minEmployment * 0.4 : 0.05;
  }

  function computeMinEmployment() {
    const values = dataset.occupations
      .map((o) => o.employment_thousands)
      .filter((v) => v !== null && v !== undefined && v > 0);
    dataset._minEmployment = values.length ? d3.min(values) : 0.1;
  }

  function majorGroups() {
    const map = new Map();
    dataset.occupations.forEach((o) => {
      if (o.major_group_code === null) return;
      if (!map.has(o.major_group_code)) {
        map.set(o.major_group_code, { code: o.major_group_code, name: o.major_group, children: [] });
      }
      map.get(o.major_group_code).children.push(o);
    });
    return Array.from(map.values()).sort((a, b) => a.code - b.code);
  }

  function buildHierarchy() {
    if (currentMajorCode === null) {
      const groups = majorGroups();
      const root = { name: 'root', children: groups };
      return d3.hierarchy(root)
        .sum((d) => (d.children ? 0 : employmentValue(d)))
        .sort((a, b) => b.value - a.value);
    }
    const group = majorGroups().find((g) => g.code === currentMajorCode);
    const root = { name: group.name, children: group.children };
    return d3.hierarchy(root)
      .sum((d) => (d.children ? 0 : employmentValue(d)))
      .sort((a, b) => b.value - a.value);
  }

  // --- colour scales -----------------------------------------------------------------

  function makeColourScale(layerKey) {
    const meta = LAYER_META[layerKey];

    if (meta.kind === 'ordinal') {
      return {
        meta,
        colour: (o) => (o.shortage_rating ? SHORTAGE_COLOURS[o.shortage_rating] : null),
      };
    }

    const values = dataset.occupations
      .map((o) => o[meta.field])
      .filter((v) => v !== null && v !== undefined);

    if (meta.kind === 'sequential') {
      const domain = meta.domainHint || [d3.min(values), d3.max(values)];
      const scale = d3.scaleLinear().domain(domain).range([0, 1]).clamp(true);
      const interp = d3.interpolateRgbBasis(SEQ_RAMP);
      return {
        meta,
        domain,
        interp,
        colour: (o) => {
          const v = o[meta.field];
          return v === null || v === undefined ? null : interp(scale(v));
        },
      };
    }

    // diverging
    const maxAbs = Math.max(Math.abs(d3.min(values)), Math.abs(d3.max(values)));
    const scale = d3.scaleLinear().domain([-maxAbs, 0, maxAbs]).range([0, 0.5, 1]).clamp(true);
    const interp = d3.interpolateRgbBasis(DIV_RAMP);
    return {
      meta,
      domain: [-maxAbs, maxAbs],
      interp,
      colour: (o) => {
        const v = o[meta.field];
        return v === null || v === undefined ? null : interp(scale(v));
      },
    };
  }

  function textIsDark(hex) {
    if (!hex) return true;
    const c = d3.rgb(hex);
    const lum = (0.299 * c.r + 0.587 * c.g + 0.114 * c.b) / 255;
    return lum > 0.58; // true = tile is light, use dark text
  }

  // --- rendering -----------------------------------------------------------------------

  function render() {
    if (!dataset) return;
    computeMinEmployment();

    const main = document.querySelector('main');
    const width = main.clientWidth;
    const height = main.clientHeight;
    svg.attr('viewBox', `0 0 ${width} ${height}`).attr('width', width).attr('height', height);
    svg.selectAll('*').remove();

    const colourScale = makeColourScale(currentLayer);
    const root = buildHierarchy();

    const showGroupLabels = currentMajorCode === null;
    const treemap = d3.treemap()
      .tile(d3.treemapSquarify)
      .size([width, height])
      .paddingOuter(showGroupLabels ? 3 : 2)
      .paddingTop(showGroupLabels ? (d) => (d.depth === 1 ? 20 : 0) : 0)
      .paddingInner(1)
      .round(true);

    treemap(root);

    if (showGroupLabels) {
      svg.selectAll('rect.major-bg')
        .data(root.children)
        .join('rect')
        .attr('class', 'tile major-group')
        .attr('x', (d) => d.x0)
        .attr('y', (d) => d.y0)
        .attr('width', (d) => Math.max(0, d.x1 - d.x0))
        .attr('height', (d) => Math.max(0, d.y1 - d.y0))
        .attr('fill', 'none')
        .attr('stroke', 'var(--text-muted)')
        .attr('stroke-width', 1.5)
        .attr('stroke-opacity', 0.5)
        .on('click', (event, d) => {
          currentMajorCode = d.data.code;
          render();
        });

      svg.selectAll('text.major-label')
        .data(root.children)
        .join('text')
        .attr('class', 'major-label')
        .attr('x', (d) => d.x0 + 4)
        .attr('y', (d) => d.y0 + 13)
        .text((d) => `${d.data.name} (click to zoom)`)
        .style('display', (d) => (d.x1 - d.x0 < 60 ? 'none' : null));
    }

    const leaves = root.leaves();

    const tileGroup = svg.selectAll('g.leaf')
      .data(leaves)
      .join('g')
      .attr('class', 'leaf')
      .attr('transform', (d) => `translate(${d.x0},${d.y0})`);

    tileGroup.append('rect')
      .attr('class', 'tile')
      .attr('data-code', (d) => d.data.code)
      .attr('width', (d) => Math.max(0, d.x1 - d.x0))
      .attr('height', (d) => Math.max(0, d.y1 - d.y0))
      .attr('fill', (d) => colourScale.colour(d.data) || MISSING_FILL)
      .on('mousemove', (event, d) => showTooltip(event, d.data))
      .on('mouseleave', hideTooltip)
      .on('click', (event, d) => {
        if (currentMajorCode === null) {
          currentMajorCode = d.data.major_group_code;
          render();
        }
      });

    tileGroup.each(function (d) {
      const w = d.x1 - d.x0;
      const h = d.y1 - d.y0;
      if (w < 34 || h < 16) return;
      const fill = colourScale.colour(d.data) || MISSING_FILL;
      const dark = textIsDark(fill);
      const g = d3.select(this);
      g.append('text')
        .attr('class', 'tile-label ' + (dark ? 'on-light' : 'on-dark'))
        .attr('x', 4)
        .attr('y', 13)
        .text(truncate(d.data.title, w));
      if (h > 32) {
        g.append('text')
          .attr('class', 'tile-sublabel ' + (dark ? 'on-light' : 'on-dark'))
          .attr('x', 4)
          .attr('y', 26)
          .text(formatEmployment(d.data));
      }
    });

    renderBreadcrumb();
    renderLegend(colourScale);
    applySearchDimming();
  }

  function truncate(text, widthPx) {
    const maxChars = Math.max(3, Math.floor(widthPx / 6.2));
    return text.length > maxChars ? text.slice(0, maxChars - 1) + '…' : text;
  }

  function formatEmployment(o) {
    if (o.employment_thousands === null || o.employment_thousands === undefined) return 'no employment data';
    const persons = o.employment_thousands * 1000;
    return persons >= 1000
      ? (persons / 1000).toFixed(0) + 'k employed'
      : Math.round(persons) + ' employed';
  }

  function renderBreadcrumb() {
    breadcrumbEl.querySelectorAll('.crumb-major').forEach((el) => el.remove());
    if (currentMajorCode === null) return;
    const group = majorGroups().find((g) => g.code === currentMajorCode);
    const span = document.createElement('span');
    span.className = 'crumb-major';
    span.textContent = ' › ' + (group ? group.name : currentMajorCode);
    breadcrumbEl.appendChild(span);
  }

  function renderLegend(colourScale) {
    const meta = colourScale.meta;
    legendEl.innerHTML = '';
    const title = document.createElement('div');
    title.className = 'legend-title';
    title.textContent = meta.label;
    legendEl.appendChild(title);

    if (meta.kind === 'ordinal') {
      const swatches = document.createElement('div');
      swatches.className = 'swatches';
      SHORTAGE_ORDER.forEach((code) => {
        const row = document.createElement('div');
        row.className = 'swatch';
        row.innerHTML = `<i style="background:${SHORTAGE_COLOURS[code]}"></i>${SHORTAGE_LABELS[code]}`;
        swatches.appendChild(row);
      });
      legendEl.appendChild(swatches);
    } else {
      const ramp = document.createElement('div');
      ramp.className = 'ramp';
      const stops = meta.kind === 'diverging' ? DIV_RAMP : SEQ_RAMP;
      ramp.style.background = `linear-gradient(to right, ${stops.join(',')})`;
      legendEl.appendChild(ramp);

      const labels = document.createElement('div');
      labels.className = 'scale-labels';
      if (meta.kind === 'diverging') {
        labels.innerHTML = `<span>shrinking ${fmtDomain(colourScale.domain[0])}%</span><span>0</span><span>+${fmtDomain(colourScale.domain[1])}%</span>`;
      } else {
        labels.innerHTML = `<span>${fmtDomain(colourScale.domain[0])}</span><span>${fmtDomain(colourScale.domain[1])}</span>`;
      }
      legendEl.appendChild(labels);
    }

    const missing = document.createElement('div');
    missing.className = 'missing-note';
    missing.innerHTML = '<i></i> no data for this occupation';
    legendEl.appendChild(missing);
  }

  function fmtDomain(v) {
    if (v === undefined || v === null) return 'n/a';
    return Math.abs(v) >= 100 ? Math.round(v).toLocaleString() : (Math.round(v * 10) / 10);
  }

  function showTooltip(event, o) {
    const rows = [
      ['Major group', o.major_group || 'n/a'],
      ['Employment', formatEmployment(o)],
      ['Avg weekly earnings', o.avg_weekly_earnings != null ? '$' + Math.round(o.avg_weekly_earnings).toLocaleString() : 'n/a'],
      ['5yr growth', o.growth_5y_pct != null ? o.growth_5y_pct + '%' : 'n/a'],
      ['10yr growth', o.growth_10y_pct != null ? o.growth_10y_pct + '%' : 'n/a'],
      ['Skills shortage', o.shortage_rating ? SHORTAGE_LABELS[o.shortage_rating] : 'n/a'],
      ['AI exposure', o.ai_exposure_score != null ? o.ai_exposure_score + ' / 10' : 'n/a'],
    ];

    let html = `<div class="t-title">${escapeHtml(o.title)} <span class="t-code">#${o.code}</span></div>`;
    rows.forEach(([label, value]) => {
      html += `<div class="t-row"><span>${label}</span><span>${escapeHtml(String(value))}</span></div>`;
    });
    if (o.ai_exposure_rationale) {
      html += `<div class="t-rationale">${escapeHtml(o.ai_exposure_rationale)}</div>`;
    }
    tooltip.innerHTML = html;
    tooltip.style.display = 'block';
    positionTooltip(event);
  }

  function positionTooltip(event) {
    const pad = 14;
    let x = event.clientX + pad;
    let y = event.clientY + pad;
    if (x + 300 > window.innerWidth) x = event.clientX - 300 - pad;
    if (y + 160 > window.innerHeight) y = event.clientY - 160 - pad;
    tooltip.style.left = x + 'px';
    tooltip.style.top = y + 'px';
  }

  function hideTooltip() {
    tooltip.style.display = 'none';
  }

  function escapeHtml(str) {
    return str.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function applySearchDimming() {
    svg.selectAll('rect.tile[data-code]').each(function (d) {
      const el = d3.select(this);
      const match = !searchTerm || el.datum().data.title.toLowerCase().includes(searchTerm);
      el.classed('dimmed', !match);
    });
  }
})();
