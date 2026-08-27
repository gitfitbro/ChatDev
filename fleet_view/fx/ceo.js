/* fx/ceo.js — the coordinator on the floor.
 *
 * One person dispatches every crewmate on this screen from a single terminal, and until
 * now that person was the only thing in the building with no body. This puts them on the
 * floor: a figure standing apart from the rooms, at a fixed station.
 *
 * It is a landmark, not a character. There is no feed for what the operator is doing —
 * no heartbeat, no state, no task — so the figure does not move, does not think, and
 * never says anything. Inventing an inner life for it would be the same lie this floor
 * exists to avoid. The only thing it is allowed to do is react to something that really
 * happened: when the server reports `appeared`, a crewmate is now in a room that had
 * nobody in it a poll ago, and someone walks out from the station toward that room and
 * is gone. That walk is the dispatch, drawn once.
 *
 * Idle cost is a static figure and a floor decal — no animation, nothing that moves,
 * because this is left open all day.
 */
(function () {
  "use strict";

  const FX = window.FleetFX;
  if (!FX || typeof FX.register !== "function") return;   // no host, no effect

  const MAX_WALKERS = 14;      // a burst of dispatches, not an unbounded crowd
  const MAX_PULSES = 6;
  const GRID_X = 30, GRID_Y = 20;
  const FULL_CLEAR = 37;       // clearance at which the figure is drawn full size
  const MIN_SCALE = 0.45;

  // Muted and outlined, so it never reads as one of the solid, saturated crewmates.
  const INK = "#c3cdda", SHELL = "#39434f", EDGE = "#7d8b9c";
  const DECAL = "#222b36", DESK = "#1b232d", DESK_EDGE = "#2b3644";
  const LABEL = "#5d6a79", COURIER = "#8a99ab";

  let station = null;          // {x, y, clear} — y is the figure's ground line
  let sig = "";                // layout fingerprint; the search only reruns when it changes
  let walkers = [];
  let pulses = [];

  /* ---- where the figure stands ------------------------------------------------ */

  // Distance from a point to a room's rectangle; 0 anywhere inside it.
  function gap(x, y, r) {
    const dx = Math.max(r.x - x, 0, x - (r.x + r.w));
    const dy = Math.max(r.y - y, 0, y - (r.y + r.h));
    return Math.hypot(dx, dy);
  }

  function clearanceAt(x, y, rooms) {
    let best = Infinity;
    for (const r of rooms) {
      if (!r || !Number.isFinite(r.x) || !Number.isFinite(r.w)) continue;   // ignore, never throw
      const d = gap(x, y, r);
      if (d < best) best = d;
      if (best === 0) return 0;
    }
    return best === Infinity ? FULL_CLEAR : best;
  }

  // The side panel is over the floor, not part of it — nothing may be parked under it.
  // Measuring it flushes layout, so this is sampled a few times a second at most and
  // never once per frame.
  let rightAt = -1e9, rightVal = 0;
  function rightLimit(w) {
    if (rightVal && w.frame - rightAt < 20) return rightVal;
    rightAt = w.frame;
    rightVal = w.w;
    try {
      const side = document.getElementById("side");
      if (side && !side.classList.contains("hidden") &&
          getComputedStyle(side).display !== "none") {
        const box = side.getBoundingClientRect();
        if (box.width > 4) rightVal = Math.max(160, box.left);
      }
    } catch (e) { /* no DOM to ask; the whole canvas is the floor */ }
    return rightVal;
  }

  // Sweep the floor for the emptiest point. Ties go low and left — away from the HUD,
  // and roughly where you would stand if you had just walked in.
  function findStation(w) {
    const rooms = w.rooms || [];
    const right = rightLimit(w);
    const x0 = 34, x1 = right - 34, y0 = 58, y1 = w.h - 26;
    if (!(x1 > x0 && y1 > y0)) return null;

    const found = [];
    let best = -1;
    for (let i = 0; i <= GRID_X; i++) {
      const x = x0 + (x1 - x0) * (i / GRID_X);
      for (let j = 0; j <= GRID_Y; j++) {
        const y = y0 + (y1 - y0) * (j / GRID_Y);
        const clear = clearanceAt(x, y, rooms);
        if (clear > best) best = clear;
        found.push({ x, y, clear });
      }
    }
    if (best <= 0) {
      // Every sample lands inside a room: the floor is full. Take the bottom-left
      // corner and draw small rather than pretending there is space.
      return { x: x0, y: y1, clear: 0 };
    }
    const ties = found.filter(p => p.clear >= best * 0.9);
    ties.sort((a, b) => (b.y - b.x * 0.5) - (a.y - a.x * 0.5));
    return ties[0];
  }

  function scaleFor(clear) {
    return Math.max(MIN_SCALE, Math.min(1, (clear - 4) / FULL_CLEAR));
  }

  // Re-run the search only when the floor actually changed shape, and keep the current
  // spot unless it has become meaningfully worse — a landmark that hops every poll is
  // not a landmark.
  function keepStation(w) {
    const rooms = w.rooms || [];
    const last = rooms.length ? rooms[rooms.length - 1] : null;
    const now = [w.w, w.h, rightLimit(w), rooms.length,
                 last ? [last.x | 0, last.y | 0, last.w | 0, last.h | 0].join(",") : "-"].join("|");
    if (now === sig && station) return station;
    sig = now;

    const found = findStation(w);
    if (!found) { station = null; return null; }
    if (station) {
      const held = clearanceAt(station.x, station.y, rooms);
      const inside = station.x > 28 && station.x < rightLimit(w) - 28 &&
                     station.y > 52 && station.y < w.h - 20;
      if (inside && held >= found.clear * 0.75) {
        station = { x: station.x, y: station.y, clear: held };
        return station;
      }
    }
    station = found;
    return station;
  }

  /* ---- drawing ---------------------------------------------------------------- */

  function box(c, x, y, w, h, r) {
    c.beginPath();
    if (typeof c.roundRect === "function") c.roundRect(x, y, w, h, r);
    else c.rect(x, y, w, h);
  }

  // A standing figure at a console: taller than a crewmate, and a different shape
  // rather than a different colour, so it reads as not-one-of-them even at a glance.
  // Nothing here is driven by data, because there is no data about this person.
  function drawCoordinator(c, x, y, s) {
    c.save();
    c.translate(x, y);
    c.scale(s, s);

    c.fillStyle = "#00000055";                              // shadow
    c.beginPath(); c.ellipse(0, 0, 9, 3, 0, 0, 7); c.fill();

    c.strokeStyle = DECAL; c.lineWidth = 1;                 // the station itself
    c.beginPath(); c.ellipse(0, 0, 22, 6.5, 0, 0, 7); c.stroke();

    c.beginPath();                                          // a long coat, not a block
    c.moveTo(-6.5, -24); c.lineTo(6.5, -24);
    c.lineTo(8.5, -1.5); c.lineTo(-8.5, -1.5); c.closePath();
    c.fillStyle = SHELL; c.fill();
    c.strokeStyle = EDGE; c.lineWidth = 1.2; c.stroke();
    c.beginPath(); c.moveTo(-6.5, -19.5); c.lineTo(6.5, -19.5); c.stroke();

    c.fillStyle = INK;                                      // head
    c.beginPath(); c.arc(0, -29.5, 5.2, 0, 7); c.fill();
    c.strokeStyle = EDGE; c.lineWidth = 1; c.stroke();
    c.fillStyle = "#0b0d10";
    c.fillRect(-2.6, -30.8, 1.6, 2); c.fillRect(1, -30.8, 1.6, 2);

    c.fillStyle = DESK;                                     // one terminal, one desk
    box(c, -11, -5.5, 22, 5, 1.5); c.fill();
    c.strokeStyle = DESK_EDGE; c.lineWidth = 1; c.stroke();

    c.fillStyle = LABEL;
    c.font = "9px ui-monospace,Menlo,monospace";
    c.textAlign = "center";
    c.fillText("coordinator", 0, 16);
    c.restore();
  }

  // One ring, once, when a dispatch leaves. Gone in under a second.
  function drawPulse(c, p, frame, s) {
    const age = frame - p.born, life = 34;
    if (age > life) return false;
    const k = age / life;
    c.save();
    c.globalAlpha = (1 - k) * 0.5;
    c.strokeStyle = EDGE; c.lineWidth = 1;
    c.beginPath();
    c.ellipse(p.x, p.y + 4 * s, (22 + k * 26) * s, (7 + k * 8) * s, 0, 0, 7);
    c.stroke();
    c.restore();
    return true;
  }

  // Somebody sent out to a room. Not an agent and never labelled as one: it is the
  // dispatch itself, and it stops existing the moment it gets there.
  function walkerAt(k, wk) {
    const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;   // ease in/out
    const u = 1 - e;
    return {
      x: u * u * wk.ax + 2 * u * e * wk.cx + e * e * wk.bx,
      y: u * u * wk.ay + 2 * u * e * wk.cy + e * e * wk.by,
    };
  }

  function drawWalker(c, wk, frame) {
    const k = (frame - wk.born) / wk.life;
    if (k >= 1) return false;
    const p = walkerAt(k, wk);
    const ahead = walkerAt(Math.min(1, k + 0.02), wk);
    const fade = Math.min(1, k / 0.1) * Math.min(1, (1 - k) / 0.18);
    const s = wk.s;

    c.save();
    c.fillStyle = COURIER;
    for (let i = 1; i <= 4; i++) {                          // the path taken so far
      const t = k - i * 0.05;
      if (t <= 0) break;
      const q = walkerAt(t, wk);
      c.globalAlpha = fade * 0.22 * (1 - i / 5);
      c.beginPath(); c.arc(q.x, q.y + 9 * s, 1.4 * s, 0, 7); c.fill();
    }

    c.globalAlpha = fade;
    c.fillStyle = "#00000044";
    c.beginPath(); c.ellipse(p.x, p.y + 10 * s, 5 * s, 2 * s, 0, 0, 7); c.fill();

    const swing = Math.sin(frame * 0.3 + wk.phase) * 3 * s;   // legs long enough to read
    c.strokeStyle = COURIER; c.lineWidth = 1.7 * s; c.lineCap = "round";
    c.beginPath();
    c.moveTo(p.x - 1.7 * s, p.y + 3 * s); c.lineTo(p.x - 1.7 * s + swing, p.y + 9 * s);
    c.moveTo(p.x + 1.7 * s, p.y + 3 * s); c.lineTo(p.x + 1.7 * s - swing, p.y + 9 * s);
    c.stroke();

    c.fillStyle = COURIER;
    box(c, p.x - 4 * s, p.y - 4 * s, 8 * s, 8 * s, 2.5 * s); c.fill();
    c.fillStyle = INK;
    c.beginPath(); c.arc(p.x, p.y - 9 * s, 3.6 * s, 0, 7); c.fill();
    c.fillStyle = "#0b0d10";
    const face = ahead.x >= p.x ? 1.2 * s : -1.2 * s;
    c.fillRect(p.x - 1.9 * s + face, p.y - 10 * s, 1.3 * s, 1.5 * s);
    c.fillRect(p.x + 0.3 * s + face, p.y - 10 * s, 1.3 * s, 1.5 * s);
    c.restore();
    return true;
  }

  /* ---- the hooks -------------------------------------------------------------- */

  FX.register({
    name: "ceo",

    onEvent(event, w) {
      if (!event || event.type !== "appeared" || !w) return;
      const here = keepStation(w);
      if (!here) return;

      // Where the new crewmate actually is. It was in the snapshot that produced this
      // event, so it is on the floor now; if the room is all we can resolve, aim there.
      let tx = null, ty = null;
      const soul = event.soul && w.soul ? w.soul(event.soul) : null;
      if (soul && Number.isFinite(soul.x) && Number.isFinite(soul.y)) {
        tx = soul.home && Number.isFinite(soul.home.x) ? soul.home.x : soul.x;
        ty = soul.home && Number.isFinite(soul.home.y) ? soul.home.y : soul.y;
      } else {
        const room = (w.rooms || []).find(r => r.name === event.room);
        if (room) { tx = room.x + room.w / 2; ty = room.y + room.h - 40; }
      }
      if (tx === null || ty === null) return;

      const s = scaleFor(here.clear);
      const dx = tx - here.x, dy = ty - (here.y - 14 * s);
      const dist = Math.hypot(dx, dy) || 1;
      // Fan concurrent dispatches apart so two at once read as two, not one.
      const lane = walkers.length % 4;
      const bow = Math.min(70, dist * 0.2) * (lane % 2 ? -1 : 1) * (0.5 + lane * 0.25);

      walkers.push({
        soul: event.soul,
        ax: here.x, ay: here.y - 14 * s,
        bx: tx, by: ty,
        cx: (here.x + tx) / 2 - (dy / dist) * bow,
        cy: (here.y - 14 * s + ty) / 2 + (dx / dist) * bow,
        born: w.frame, life: Math.max(48, Math.min(150, dist / 1.7)),
        phase: (walkers.length * 1.7) % 6.28, s: 0.9,
      });
      if (walkers.length > MAX_WALKERS) walkers.splice(0, walkers.length - MAX_WALKERS);

      pulses.push({ x: here.x, y: here.y, born: w.frame });
      if (pulses.length > MAX_PULSES) pulses.splice(0, pulses.length - MAX_PULSES);
    },

    // Under the characters: a walker arriving at a desk should disappear behind the
    // crewmate it was sent to, and nothing here may ever cover somebody real.
    drawUnder(w) {
      if (!w || !w.ctx) return;
      const here = keepStation(w);
      if (!here) return;
      const c = w.ctx, frame = w.frame;
      const s = scaleFor(here.clear);

      // The floor may have been relaid under a walker mid-journey; follow the soul if
      // it is still there, otherwise finish at the last place it was known to be.
      for (const wk of walkers) {
        const soul = wk.soul && w.soul ? w.soul(wk.soul) : null;
        if (soul && soul.home && Number.isFinite(soul.home.x)) {
          wk.bx = soul.home.x; wk.by = soul.home.y;
        }
      }

      if (pulses.length) pulses = pulses.filter(p => drawPulse(c, p, frame, s));
      drawCoordinator(c, here.x, here.y, s);
      if (walkers.length) walkers = walkers.filter(wk => drawWalker(c, wk, frame));
    },
  });
})();
