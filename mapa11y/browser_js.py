"""JavaScript snippets evaluated inside audited pages (each runs per frame unless noted)."""

def _wrap(inner):
    """Wrap a function-expression snippet so the shared helpers are in scope."""
    return "(arg) => {\n" + HELPERS + "\nreturn (" + inner.strip() + ")(arg);\n}"


# Shared helpers, available to the snippets below.
HELPERS = r"""
const __MAP_SELECTORS = [
  ['ArcGIS JS 4.x', '.esri-view'],
  ['ArcGIS JS 4.x components', 'arcgis-map, arcgis-scene'],
  ['ArcGIS JS 3.x', '.esriMapContainer, .esriMap'],
  ['Leaflet', '.leaflet-container'],
  ['MapLibre', '.maplibregl-map'],
  ['Mapbox', '.mapboxgl-map'],
  ['OpenLayers', '.ol-viewport'],
  ['Google Maps', '.gm-style'],
];
function __roots() {
  const roots = [document];
  let count = 0;
  (function collect(root) {
    const w = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    let node;
    while ((node = w.nextNode()) && count < 60000) {
      count++;
      if (node.shadowRoot) { roots.push(node.shadowRoot); collect(node.shadowRoot); }
    }
  })(document);
  return roots;
}
function __deepAll(sel) {
  const out = [];
  for (const r of __roots()) out.push(...r.querySelectorAll(sel));
  return out;
}
function __visible(el, minW, minH) {
  const r = el.getBoundingClientRect();
  if (r.width < minW || r.height < minH) return false;
  const s = getComputedStyle(el);
  return s.visibility !== 'hidden' && s.display !== 'none' && parseFloat(s.opacity || '1') > 0.05;
}
function __up(n) { return n.parentNode || n.host || null; }
function __inMap(el) {
  let n = el;
  while (n) {
    if (n.nodeType === 1 && n.getAttribute && n.getAttribute('data-mapa11y') === 'map') return true;
    n = __up(n);
  }
  return false;
}
function __deepActive() {
  let a = document.activeElement;
  while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement;
  return a;
}
function __accName(el) {
  if (!el || !el.getAttribute) return '';
  const lb = el.getAttribute('aria-labelledby');
  if (lb) {
    const t = lb.split(/\s+/).map(id => { const e = document.getElementById(id); return e ? e.textContent : ''; }).join(' ').trim();
    if (t) return t;
  }
  const al = el.getAttribute('aria-label');
  if (al && al.trim()) return al.trim();
  if (el.tagName === 'IMG' && el.getAttribute('alt')) return el.getAttribute('alt').trim();
  const ti = el.getAttribute('title');
  if (ti && ti.trim()) return ti.trim();
  if (/^(BUTTON|A|CALCITE-BUTTON|CALCITE-ACTION)$/.test(el.tagName)) {
    const tx = (el.getAttribute('text') || el.innerText || __slotText(el) || '').trim();
    if (tx) return tx;
  }
  const root = el.getRootNode && el.getRootNode();
  if (root && root.host && /^(BUTTON|A)$/.test(el.tagName)) {   // inner button of a web component: use the host's label
    const h = root.host;
    const hl = h.getAttribute('aria-label') || h.getAttribute('label') || h.getAttribute('text') || h.getAttribute('title');
    if (hl && hl.trim()) return hl.trim();
  }
  return '';
}
function __slotText(el) {
  let t = '';
  for (const sl of (el.querySelectorAll ? el.querySelectorAll('slot') : [])) {
    for (const n of sl.assignedNodes({flatten: true})) t += ' ' + (n.textContent || '');
  }
  return t.trim();
}
function __desc(el) {
  if (!el || !el.getAttribute) return '';
  const d = el.getAttribute('aria-describedby');
  if (!d) return '';
  return d.split(/\s+/).map(id => { const e = document.getElementById(id); return e ? e.textContent : ''; }).join(' ').trim();
}
const __DIALOG_SEL = '[role=dialog],[role=alertdialog],[aria-modal=true],calcite-modal,calcite-dialog,.jimu-dialog,.jimu-popup,.dijitDialog,' +
  '[class*="splash" i],[id*="splash" i],[class*="disclaimer" i],[id*="disclaimer" i],[class*="modal" i],[class*="dialog" i]';
function __coversMap(a, mapEl) {   // a focusable layer laid over the map panel (ArcGIS Dashboards' keyboard zones)
  const r = a.getBoundingClientRect(), m = mapEl.getBoundingClientRect();
  const ma = m.width * m.height, ra = r.width * r.height;
  if (ma < 1 || ra < 1) return false;
  const ix = Math.max(0, Math.min(r.right, m.right) - Math.max(r.left, m.left));
  const iy = Math.max(0, Math.min(r.bottom, m.bottom) - Math.max(r.top, m.top));
  return ix * iy >= 0.9 * ma && ra <= 1.6 * ma;
}
function __flatUp(n) { return n.assignedSlot || n.parentNode || n.host || null; }  // as rendered: slotted content sits in its slot
function __contains(anc, el) {
  for (let n = el; n; n = __flatUp(n)) if (n === anc) return true;
  return false;
}
const __PW_SEL = 'input[type=password],calcite-input[type=password]';
const __SIGNIN_RE = /please (sign|log) ?in\b|\b(sign|log) ?in to (access|https?:|continue|view)|you (must|need to) (sign|log) ?in/i;
function __isSigninBox(n) {   // a (small) dialog that holds a visible password field or asks the user to sign in
  if (!(n && n.nodeType === 1 && n.matches && n.matches(__DIALOG_SEL) && __visible(n, 20, 20))) return false;
  if ([...n.querySelectorAll(__PW_SEL)].some(e => __visible(e, 20, 8))) return true;
  const t = (n.innerText || '');
  return t.length < 600 && __SIGNIN_RE.test(t);
}
function __inSignin(el) {
  for (let n = el; n; n = __up(n)) {
    if (__isSigninBox(n)) return true;
  }
  return false;
}
function __inDialog(el) {
  let n = el;
  while (n) {
    if (n.nodeType === 1 && n.matches && n.matches(__DIALOG_SEL)) return true;
    n = __up(n);
  }
  return false;
}
"""

DETECT_MAP = _wrap(r"""
() => {
  for (const el of __deepAll('[data-mapa11y]')) el.removeAttribute('data-mapa11y');
  const cands = [];
  for (const [lib, sel] of __MAP_SELECTORS) {
    for (const el of __deepAll(sel)) {
      if (__visible(el, 150, 100)) {
        const r = el.getBoundingClientRect();
        cands.push({el, lib, area: r.width * r.height});
      }
    }
  }
  if (!cands.length) return {found: false};
  cands.sort((a, b) => b.area - a.area);
  const best = cands[0];
  // Climb to the outermost same-size ancestor that is clearly the map element
  // (e.g. ArcGIS 3.x / Web AppBuilder: <div id="map" aria-label="Map Area"> wraps .esriMapContainer).
  let mark = best.el, climbed = 0;
  const b0 = best.el.getBoundingClientRect();
  for (let n = __up(best.el), i = 0; n && n.nodeType === 1 && i < 4; n = __up(n), i++) {
    if (n === document.body || n === document.documentElement) break;
    const r = n.getBoundingClientRect();
    const same = Math.abs(r.x - b0.x) <= 4 && Math.abs(r.y - b0.y) <= 4 &&
                 Math.abs(r.width - b0.width) <= 8 && Math.abs(r.height - b0.height) <= 8;
    if (!same) break;
    const idc = (n.id || '') + ' ' + (typeof n.className === 'string' ? n.className : '');
    const label = (n.getAttribute('aria-label') || '');
    if (/map/i.test(idc) || /map/i.test(label)) { mark = n; climbed = i + 1; }
  }
  mark.setAttribute('data-mapa11y', 'map');
  const r = mark.getBoundingClientRect();
  return {found: true, lib: best.lib, libs: [...new Set(cands.map(c => c.lib))], n_maps: cands.length,
          climbed, x: r.x, y: r.y, w: r.width, h: r.height};
}
""")

FOCUS_INFO = _wrap(r"""
() => {
  if (!document.hasFocus()) return {hasFocus: false};
  const a = __deepActive();
  if (!a) return {hasFocus: true, tag: null};
  if (a.tagName === 'IFRAME' || a.tagName === 'FRAME') return {hasFocus: true, tag: a.tagName, isFrame: true};
  const isBody = (a === document.body || a === document.documentElement);
  const r = a.getBoundingClientRect();
  const mapEl = __deepAll('[data-mapa11y=map]')[0];
  // tag each focused element once, so a real loop (same elements again) is told apart from a long list of look-alikes
  if (!isBody && a.setAttribute && !a.getAttribute('data-mapa11y-fid')) {
    window.__mapa11yFid = (window.__mapa11yFid || 0) + 1;
    a.setAttribute('data-mapa11y-fid', String(window.__mapa11yFid));
  }
  return {
    hasFocus: true, tag: a.tagName, isBody, fid: (a.getAttribute && a.getAttribute('data-mapa11y-fid')) || '',
    id: a.id || '', cls: (typeof a.className === 'string' ? a.className : '').slice(0, 120),
    role: a.getAttribute('role') || '', name: __accName(a).slice(0, 120),
    text: (a.innerText || __slotText(a) || '').trim().slice(0, 60), tabindex: a.getAttribute('tabindex'),
    href: (a.getAttribute('href') || '').slice(0, 300), hrefAbs: (typeof a.href === 'string' ? a.href.split('#')[0] : ''),
    pageUrl: location.href.split('#')[0].slice(0, 300),
    type: (a.getAttribute('type') || '').toLowerCase(),
    checked: a.getAttribute('aria-checked') || (a.type === 'checkbox' ? String(a.checked) :
             (/CHECKBOX/.test(a.tagName) ? String(a.hasAttribute('checked') || a.checked === true) : '')),
    disabled: !!(a.disabled || a.getAttribute('aria-disabled') === 'true'),
    inMap: __inMap(a), inDialog: __inDialog(a), inSignin: __inSignin(a), w: r.width, h: r.height, x: Math.round(r.x), y: Math.round(r.y),
    containsMap: !!(mapEl && a !== mapEl && !isBody && !__inMap(a) && (__contains(a, mapEl) || __coversMap(a, mapEl))),
    frameUrl: location.href.slice(0, 80),
  };
}
""")

DIALOG_PRESENT = _wrap(r"""
() => {
  const vw = innerWidth, vh = innerHeight;
  for (const el of __deepAll(__DIALOG_SEL)) {
    if (!__visible(el, 120, 60)) continue;
    const r = el.getBoundingClientRect();
    if (r.width * r.height >= 0.10 * vw * vh) {
      return {present: true, text: (el.innerText || '').trim().slice(0, 160)};
    }
  }
  return {present: false};
}
""")

MAP_INFO = _wrap(r"""
() => {
  const map = __deepAll('[data-mapa11y=map]')[0];
  if (!map) return {found: false};
  const inside = [];
  const roots = __roots();
  const all = [];
  for (const r of roots) all.push(...r.querySelectorAll('*'));
  for (const e of all) if (__inMap(e)) inside.push(e);
  const focusable = inside.filter(e => {
    const ti = e.getAttribute('tabindex');
    if (ti !== null) return parseInt(ti, 10) >= 0;
    return /^(A|BUTTON|INPUT|SELECT|TEXTAREA)$/.test(e.tagName) && !e.disabled && (e.tagName !== 'A' || e.hasAttribute('href'));
  });
  // the map "surface" = the largest focusable (or role=application) element covering >= 25% of the map
  const mr = map.getBoundingClientRect();
  const mapArea = Math.max(1, mr.width * mr.height);
  const surfaceCands = [map, ...inside].filter(e => {
    const ti = e.getAttribute('tabindex');
    if (ti === null && e.getAttribute('role') !== 'application') return false;
    if (/^(A|BUTTON|INPUT|SELECT|TEXTAREA)$/.test(e.tagName) || /^CALCITE-/.test(e.tagName)) return false;
    const r = e.getBoundingClientRect();
    return r.width * r.height >= 0.25 * mapArea;
  }).sort((a, b) => { const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect(); return rb.width * rb.height - ra.width * ra.height; });
  const surface = surfaceCands[0] || null;
  const zoomSel = '.esri-zoom, arcgis-zoom, .leaflet-control-zoom-in, .maplibregl-ctrl-zoom-in, .mapboxgl-ctrl-zoom-in, .ol-zoom-in, button[aria-label*="zoom in" i], button[title*="zoom in" i], calcite-action[text*="zoom in" i], calcite-button[label*="zoom in" i], [aria-label*="zoom in" i], [title*="zoom in" i]';
  const zooms = __deepAll(zoomSel).filter(e => __visible(e, 8, 8));
  const zoomInfo = zooms.slice(0, 4).map(e => ({tag: e.tagName, cls: (typeof e.className === 'string' ? e.className : '').slice(0, 60),
                                                  name: __accName(e).slice(0, 60),
                                                  focusable: (e.getAttribute('tabindex') !== null && parseInt(e.getAttribute('tabindex'), 10) >= 0) || /^(BUTTON|A|CALCITE-BUTTON|CALCITE-ACTION)$/.test(e.tagName) || !!e.querySelector('button,calcite-button,calcite-action')}));
  // legend: rows that show a symbol but carry no text label
  const legendRows = __deepAll('.esri-legend__layer-row, .esri-legend-layer-row, .legend-item, .esriLegendLayer tr');
  let rowsNoText = 0;
  for (const row of legendRows) if (!(row.innerText || '').trim() && !__accName(row)) rowsNoText++;
  const legendPresent = __deepAll('.esri-legend, arcgis-legend, .esriLegend, .legend, .leaflet-control-legend').some(e => __visible(e, 20, 20));
  // tabular / list alternative to the map, outside the map container
  let tables = 0;
  for (const t of __deepAll('table, [role=grid], [role=table]')) {
    if (__inMap(t)) continue;
    const rows = t.querySelectorAll('tr, [role=row]').length;
    if (rows >= 4) tables++;
  }
  const featureTable = __deepAll('.esri-feature-table, arcgis-feature-table, .esri-grid, .feature-table, vaadin-grid').length > 0;
  let ver = '';
  try {
    const res = performance.getEntriesByType('resource').map(e => e.name);
    for (const n of res) { const m = n.match(/js\.arcgis\.com\/(\d+\.\d+)/); if (m) { ver = m[1]; break; } }
  } catch (e) {}
  if (!ver) {
    for (const s of document.querySelectorAll('script[src]')) { const m = s.src.match(/js\.arcgis\.com\/(\d+\.\d+)/); if (m) { ver = m[1]; break; } }
  }
  return {
    found: true,
    container: {tag: map.tagName, role: map.getAttribute('role') || '', name: __accName(map).slice(0, 160),
                desc: __desc(map).slice(0, 200), tabindex: map.getAttribute('tabindex')},
    surface: surface ? {tag: surface.tagName, role: surface.getAttribute('role') || '', name: __accName(surface).slice(0, 160),
                        desc: __desc(surface).slice(0, 200), tabindex: surface.getAttribute('tabindex'),
                        cls: (typeof surface.className === 'string' ? surface.className : '').slice(0, 80)} : null,
    n_inside: inside.length, n_focusable_in_map: focusable.length,
    n_canvas: inside.filter(e => e.tagName === 'CANVAS').length,
    zoom_controls: zoomInfo, n_zoom_controls: zooms.length,
    legend_present: legendPresent, legend_rows: legendRows.length, legend_rows_without_text: rowsNoText,
    n_data_tables_outside_map: tables, feature_table_widget: featureTable,
    arcgis_js_version: ver, title: document.title, lang: document.documentElement.getAttribute('lang') || '',
  };
}
""")

FOCUS_PROGRAMMATIC = _wrap(r"""
() => {
  const map = __deepAll('[data-mapa11y=map]')[0];
  if (!map) return false;
  const all = [];
  for (const r of __roots()) all.push(...r.querySelectorAll('*'));
  const mr = map.getBoundingClientRect();
  const mapArea = Math.max(1, mr.width * mr.height);
  const big = e => { const r = e.getBoundingClientRect(); return r.width * r.height >= 0.25 * mapArea; };
  const cands = all.filter(e => __inMap(e) && (e.hasAttribute('tabindex') || e.getAttribute('role') === 'application') && big(e));
  cands.unshift(map);
  try { const a = __deepActive(); if (a && a.blur) a.blur(); } catch (e) {}
  for (const c of cands) {
    try { c.focus({preventScroll: true}); } catch (e) {}
    if (__deepActive() === c) return true;
  }
  return false;
}
""")

APP_STATE = _wrap(r"""
() => {
  const foc = __deepAll('a[href],button,input,select,textarea,[tabindex]').filter(e => {
    const t = e.getAttribute('tabindex');
    return (t === null || parseInt(t, 10) >= 0) && !e.disabled && __visible(e, 2, 2);
  });
  return {
    n: foc.length, outside: foc.filter(e => !__inMap(e)).length,
    wab: !!(window.jimuConfig || document.getElementById('jimu-layout-manager')),
    wabWidgets: document.querySelectorAll('.jimu-widget').length,
    loading: __deepAll('#main-loading,.jimu-main-loading').some(e => __visible(e, 20, 20)),
  };
}
""")

FOCUS_CONTEXT = _wrap(r"""
() => {
  // text around the focused element (the message a dialog's OK button belongs to)
  const a = __deepActive();
  for (let n = a ? __up(a) : null, k = 0; n && k < 6; n = __up(n), k++) {
    if (n.nodeType !== 1 || n === document.body) continue;
    const t = (n.innerText || '').trim();
    if (t.length > 25) return t.slice(0, 200);
  }
  return '';
}
""")

PAGE_TEXT = _wrap(r"""
() => ((document.body && document.body.innerText) || '').slice(0, 3000)
""")

LOGIN_PRESENT = _wrap(r"""
() => {
  const pw = __deepAll('input[type=password]').filter(e => __visible(e, 20, 8));
  const u = location.href;
  return {login: pw.length > 0 || /oauth2\/authorize|\/home\/signin|login\.microsoftonline|\/sign-?in(\.html?|\/|\?|#|$)/i.test(u), url: u.slice(0, 200)};
}
""")

SIGNIN_CANCEL = _wrap(r"""
() => {
  // A sign-in box over the app (e.g. a secured layer in a public app): click its Cancel / Close button.
  // Never touches OK / Sign In. Full sign-in pages are left alone (handled as login_required).
  if (/oauth2\/authorize|\/home\/signin|login\.microsoftonline|\/sign-?in(\.html?|\/|\?|#|$)/i.test(location.href)) return {prompt: false};
  const pw = __deepAll(__PW_SEL).filter(e => __visible(e, 20, 8));
  const boxes = __deepAll(__DIALOG_SEL).filter(__isSigninBox);
  const starts = pw.length ? [pw[0]] : boxes.slice(0, 1);
  if (!starts.length) return {prompt: false};
  const re = /^\s*(cancel|close|not now|skip|no thanks|\u00d7|x)\s*$/i;
  const ok = b => [b.innerText, b.value, b.getAttribute('aria-label'), b.getAttribute('title')]
                    .some(t => t && re.test(String(t)));
  for (let n = starts[0], k = 0; n && k < 12; n = __up(n), k++) {
    if (n.nodeType !== 1) continue;
    const btns = [...n.querySelectorAll('button,[role=button],input[type=button],input[type=reset],calcite-button,' +
                                        '.dijitButtonNode,[tabindex]')]
      .filter(b => __visible(b, 4, 4) && ok(b))
      .sort((a, b) => (/cancel/i.test(b.innerText || '') ? 1 : 0) - (/cancel/i.test(a.innerText || '') ? 1 : 0));
    if (btns.length) {
      const b = btns[0];
      if (b.getAttribute('data-mapa11y-cancelled')) return {prompt: true, clicked: false, stuck: true, text: ''};
      const text = (n.innerText || '').trim().slice(0, 160);
      b.setAttribute('data-mapa11y-cancelled', '1');   // same box still there next time -> Cancel did not work
      b.click();
      return {prompt: true, clicked: true, text};
    }
  }
  return {prompt: true, clicked: false, text: ''};
}
""")

DEEP_ACTIVE_HANDLE = _wrap(r"""
() => __deepActive()
""")

# Runs in the TOP frame only. axe is injected into every frame by an init script.
RUN_AXE = r"""
async ([tags, frameWait, hardTimeout]) => {
  if (!window.axe) return {error: 'axe not loaded'};
  const opts = {runOnly: {type: 'tag', values: tags}, resultTypes: ['violations'],
                iframes: true, frameWaitTime: frameWait, elementRef: false, performanceTimer: false};
  let res;
  try {
    res = await Promise.race([
      axe.run(document, opts),
      new Promise((_, rej) => setTimeout(() => rej(new Error('axe timeout')), hardTimeout)),
    ]);
  } catch (e) { return {error: String(e && e.message || e)}; }
  function inMapTarget(t) {
    if (!Array.isArray(t) || t.length !== 1 || typeof t[0] !== 'string') return null;
    try {
      const el = document.querySelector(t[0]);
      if (!el) return null;
      let n = el;
      while (n) { if (n.nodeType === 1 && n.getAttribute && n.getAttribute('data-mapa11y') === 'map') return true; n = n.parentNode || n.host || null; }
      return false;
    } catch (e) { return null; }
  }
  const viol = res.violations.map(v => ({
    id: v.id, impact: v.impact, help: v.help, tags: v.tags.filter(t => /^wcag/.test(t)),
    n_nodes: v.nodes.length,
    n_nodes_in_map: v.nodes.filter(n => inMapTarget(n.target) === true).length,
    examples: v.nodes.slice(0, 3).map(n => ({target: JSON.stringify(n.target).slice(0, 200), html: (n.html || '').slice(0, 200)})),
  }));
  const inc = res.incomplete.map(v => ({id: v.id, impact: v.impact, n_nodes: v.nodes.length}));
  return {engine: res.testEngine && res.testEngine.version, url: res.url, violations: viol, incomplete: inc,
          n_passes: res.passes.length, n_inapplicable: res.inapplicable.length};
}
"""
