// Minimal canvas "map" used only for self-testing the audit tool.
function MockMap(el, opts) {
  opts = opts || {};
  const c = el.querySelector('canvas');
  const ctx = c.getContext('2d');
  let cx = 0, cy = 0, z = 1;
  function draw() {
    ctx.fillStyle = '#e8f0e0';
    ctx.fillRect(0, 0, c.width, c.height);
    const step = Math.max(12, Math.round(60 * z));
    const ox = ((cx % step) + step) % step, oy = ((cy % step) + step) % step;
    const bx = Math.floor(cx / step), by = Math.floor(cy / step);
    for (let i = -1; i < c.width / step + 2; i++) {
      for (let j = -1; j < c.height / step + 2; j++) {
        const gx = i + bx, gy = j + by;
        const h = (((gx * 73856093) ^ (gy * 19349663)) >>> 0);
        ctx.fillStyle = 'hsl(' + (h % 360) + ',60%,' + (35 + (h % 35)) + '%)';
        ctx.fillRect(i * step - ox, j * step - oy, step - 4, step - 4);
      }
    }
  }
  draw();
  let hovering = false;
  if (opts.hoverOnly) {  // keyboard works only while the mouse pointer is over the map
    el.addEventListener('mouseenter', function () { hovering = true; });
    el.addEventListener('mouseleave', function () { hovering = false; });
  }
  if (opts.holdPan) {  // like ArcGIS 4.2x: arrow keys pan smoothly only while held down (needs >= 2 frames)
    let held = null, last = null;
    el.addEventListener('keydown', function (e) {
      if (/^Arrow/.test(e.key)) { e.preventDefault(); if (!e.repeat) { held = e.key; last = null; } }
    });
    el.addEventListener('keyup', function (e) { if (e.key === held) held = null; });
    (function frame(t) {
      if (held) {
        if (last !== null) {
          const d = (t - last) * 0.6;
          if (held === 'ArrowRight') cx += d; else if (held === 'ArrowLeft') cx -= d;
          else if (held === 'ArrowUp') cy -= d; else cy += d;
          draw();
        }
        last = t;
      }
      requestAnimationFrame(frame);
    })(0);
    opts = Object.assign({}, opts, {keyboard: true, noArrows: true});
  }
  if (opts.keyboard) {
    (opts.hoverOnly ? document : el).addEventListener('keydown', function (e) {
      if (opts.hoverOnly && !hovering) return;
      let used = true;
      if (opts.noArrows && /^Arrow/.test(e.key)) used = false;
      else if (e.key === 'ArrowRight') cx += 50;
      else if (e.key === 'ArrowLeft') cx -= 50;
      else if (e.key === 'ArrowUp') cy -= 50;
      else if (e.key === 'ArrowDown') cy += 50;
      else if (e.key === '+' || e.key === '=') z *= 1.5;
      else if (e.key === '-') z /= 1.5;
      else if (opts.trap && e.key === 'Tab') { /* swallow Tab: keyboard trap */ }
      else used = false;
      if (used) { e.preventDefault(); draw(); }
    });
  }
  el.querySelectorAll('[data-zoom]').forEach(function (b) {
    b.addEventListener('click', function () { z *= (b.dataset.zoom === 'in' ? 1.5 : 1 / 1.5); draw(); });
  });
}
