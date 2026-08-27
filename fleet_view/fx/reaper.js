/* fx/reaper.js — a crewmate that vanished gets collected.
 *
 * On a `vanished` event a figure walks in from the nearest edge, crosses to the spot
 * where that crewmate was standing, takes it, and walks back out. Three or four
 * seconds, then the floor is exactly as it was. Nothing is drawn when no one has died.
 *
 * The whole difficulty is knowing where to walk to. By the time `vanished` is
 * delivered, world.html has already re-laid out the floor from the poll that no longer
 * contains the soul, so `world.soul(event.soul)` is usually already undefined - the
 * capture the README asks for succeeds only in the rare case where the event arrives a
 * poll late. So this file also remembers where every soul was standing, per frame, and
 * falls back to that, then to the room, then to drawing nothing. A reaper at the wrong
 * desk is a lie about a real agent; no reaper is merely a missed effect.
 */
(function () {
  "use strict";

  var MAX_ACTIVE   = 3;    // several can vanish at once; more than three is a pile-up
  var MAX_PENDING  = 6;
  var PENDING_TTL  = 900;  // ~15s: a reaping that arrives long after the fact reads as a glitch
  var MEMORY_TTL   = 1800; // ~30s of last-known positions, so the map cannot grow all day
  var REAP_FRAMES  = 54;
  var LEAVE_FRAMES = 66;
  var WALK_SPEED   = 3.4;

  var CLOAK   = "#141a22", CLOAK_LO = "#0b0f14", RIM = "#3c4653";
  var VOID    = "#05070a", GLINT = "#c9d4e2";
  var STEEL   = "#8792a2", SOUL = "#cfe0ff";

  var active = [];                 // reapings currently on screen
  var pending = [];                // waiting for a free reaper
  var lastSeen = new Map();        // soul id -> {x, y, f}
  var pruned = 0;

  var clamp = function (v, a, b) { return v < a ? a : v > b ? b : v; };
  var ease  = function (u) { u = clamp(u, 0, 1); return u * u * (3 - 2 * u); };
  var lerp  = function (a, b, u) { return a + (b - a) * u; };
  var num   = function (v) { return typeof v === "number" && isFinite(v); };

  /* Where was this crewmate standing? Four answers, in descending order of truth. */
  function locate(event, world) {
    var live = world.soul(event.soul);
    if (live && num(live.x) && num(live.y)) return { x: live.x, y: live.y };

    var seen = lastSeen.get(event.soul);
    if (seen) return { x: seen.x, y: seen.y };

    // The renderer's soul id is `${roomId}:${index}:${kind}`, so the room survives even
    // when the position does not. Fall back to the room's name only if that fails.
    var parts = String(event.soul || "").split(":");
    var room = parts.length > 2 ? world.room(parts.slice(0, -2).join(":")) : null;
    if (!room && event.room) {
      room = world.rooms.filter(function (r) { return r.name === event.room; })[0];
    }
    if (room && num(room.x)) return { x: room.x + room.w / 2, y: room.y + room.h / 2 };

    return null;   // rather nothing than the wrong desk
  }

  function job(at, kind, world) {
    var fromLeft = at.x < world.w / 2;
    var edgeX = fromLeft ? -34 : world.w + 34;
    var standX = at.x + (fromLeft ? -16 : 16);
    var walk = clamp(Math.abs(standX - edgeX) / WALK_SPEED, 40, 110);
    return {
      x: at.x, y: at.y, kind: kind || "",
      edgeX: edgeX, standX: standX, flip: fromLeft ? 1 : -1,
      walk: walk, start: world.frame, phase: (world.frame % 97) / 97 * 6.283,
      total: walk + REAP_FRAMES + LEAVE_FRAMES,
    };
  }

  /* ---- state, advanced once per frame from the first hook the floor calls ---- */
  function tick(world) {
    var f = world.frame, i;

    for (i = 0; i < world.souls.length; i++) {
      var s = world.souls[i];
      if (num(s.x) && num(s.y)) lastSeen.set(s.id, { x: s.x, y: s.y, f: f });
    }
    if (f - pruned > 240) {                       // bounded: the page can be open for hours
      pruned = f;
      lastSeen.forEach(function (v, k) { if (f - v.f > MEMORY_TTL) lastSeen.delete(k); });
    }

    active = active.filter(function (j) { return f - j.start < j.total; });

    while (pending.length && active.length < MAX_ACTIVE) {
      var p = pending.shift();
      if (f - p.f > PENDING_TTL) continue;        // too late to be about anything
      active.push(job(p.at, p.kind, world));
    }
  }

  /* ---- the figure ---- */
  function scythe(c, x, y, angle, flip, alpha) {
    c.save();
    c.translate(x, y);
    c.scale(flip, 1);
    c.rotate(angle);
    c.globalAlpha = alpha * 0.95;
    c.lineCap = "round"; c.lineJoin = "round";
    c.strokeStyle = "#4d5967"; c.lineWidth = 1.7;   // the snath, light enough to read on a dark floor
    c.beginPath(); c.moveTo(0.5, 8); c.lineTo(-0.5, -30); c.stroke();
    c.strokeStyle = STEEL; c.lineWidth = 1.6;       // the blade, hooked back over the shaft
    c.beginPath();
    c.moveTo(-0.5, -30);
    c.quadraticCurveTo(9, -32, 12.5, -23.5);
    c.quadraticCurveTo(8, -26.5, 1, -25.5);
    c.stroke();
    c.restore();
  }

  function reaper(c, j, f, x, y, arm, alpha, walking) {
    var sway = Math.sin(f * (walking ? 0.16 : 0.05) + j.phase) * (walking ? 1.5 : 0.7);

    c.save();
    c.globalAlpha = alpha;

    c.fillStyle = "#00000044";                    // it drags a little dark along with it
    c.beginPath(); c.ellipse(x, y + 11, 8, 2.8, 0, 0, 6.284); c.fill();

    scythe(c, x + j.flip * 7, y - 1, arm, j.flip, alpha);

    // A robe: narrow at the crown, widening to a hem that trails behind the walk.
    var g = c.createLinearGradient(0, y - 30, 0, y + 12);
    g.addColorStop(0, CLOAK); g.addColorStop(1, CLOAK_LO);
    c.beginPath();
    c.moveTo(x, y - 30);
    c.quadraticCurveTo(x + 6.5, y - 29, x + 7.5, y - 17);
    c.quadraticCurveTo(x + 9.5, y - 2, x + 9 + sway, y + 12);
    c.quadraticCurveTo(x + 4.5, y + 9, x, y + 12);
    c.quadraticCurveTo(x - 4.5, y + 9, x - 9 + sway, y + 12);
    c.quadraticCurveTo(x - 9.5, y - 2, x - 7.5, y - 17);
    c.quadraticCurveTo(x - 6.5, y - 29, x, y - 30);
    c.closePath();
    c.fillStyle = g; c.fill();
    c.strokeStyle = RIM; c.lineWidth = 1; c.stroke();

    c.fillStyle = VOID;                           // under the hood, nothing
    c.beginPath(); c.ellipse(x + j.flip * 0.9, y - 21, 4.4, 5.4, 0, 0, 6.284); c.fill();

    c.globalAlpha = alpha * (0.55 + 0.45 * Math.abs(Math.sin(f * 0.035 + j.phase)));
    c.fillStyle = GLINT;
    c.fillRect(x + j.flip * 2.4 - 1.4, y - 21.6, 1.3, 1.3);
    c.fillRect(x + j.flip * 0.2 - 1.4, y - 21.6, 1.3, 1.3);

    c.restore();
  }

  window.FleetFX.register({
    name: "reaper",

    onEvent: function (event, world) {
      // `ghosted` is a terminal closing, not a death - world.html already haunts it.
      if (!event || event.type !== "vanished") return;
      var at = locate(event, world);
      if (!at || !num(at.x) || !num(at.y)) return;
      if (pending.length >= MAX_PENDING) pending.shift();
      pending.push({ at: at, kind: event.kind, f: world.frame });
    },

    // First hook of the frame, so it also carries the bookkeeping.
    drawUnder: function (world) {
      tick(world);
      if (!active.length) return;
      var c = world.ctx, f = world.frame;

      c.save();
      try {
        for (var i = 0; i < active.length; i++) {
          var j = active[i], t = f - j.start - j.walk;
          if (t < 0) continue;

          // A ring closes on the spot as the scythe comes down, then fades.
          var close = ease(t / 26);
          if (t <= 30) {
            c.globalAlpha = 0.42 * (1 - close * 0.3);
            c.strokeStyle = SOUL; c.lineWidth = 1;
            c.beginPath(); c.arc(j.x, j.y + 9, lerp(13, 2, close), 0, 6.284); c.stroke();
          }
          var fade = clamp(1 - (t - 26) / (REAP_FRAMES - 26 + LEAVE_FRAMES * 0.5), 0, 1);
          if (t > 20) {
            c.globalAlpha = 0.34 * fade;
            c.fillStyle = "#0b0f14";
            c.beginPath(); c.ellipse(j.x, j.y + 8, 7, 2.4, 0, 0, 6.284); c.fill();
          }
        }
      } finally { c.restore(); }
    },

    drawOver: function (world) {
      if (!active.length) return;
      var c = world.ctx, f = world.frame;

      c.save();
      try {
        for (var i = 0; i < active.length; i++) {
          var j = active[i], t = f - j.start;
          var x, alpha = 1, arm = -0.12, walking = false;

          if (t < j.walk) {                        // in
            var u = ease(t / j.walk);
            x = lerp(j.edgeX, j.standX, u);
            alpha = clamp(t / 14, 0, 1);
            walking = true;
          } else if (t < j.walk + REAP_FRAMES) {   // the pause, and the taking
            var r = t - j.walk;
            x = j.standX;
            arm = r < 14 ? lerp(-0.12, -0.62, ease(r / 14))
                : r < 26 ? lerp(-0.62, 0.5, ease((r - 14) / 12))
                         : lerp(0.5, -0.12, ease((r - 26) / (REAP_FRAMES - 26)));
          } else {                                 // out
            var v = ease((t - j.walk - REAP_FRAMES) / LEAVE_FRAMES);
            x = lerp(j.standX, j.edgeX, v);
            alpha = clamp(1 - (v - 0.55) / 0.45, 0, 1);
            walking = true;
          }
          if (!num(x) || alpha <= 0.01) continue;

          var bob = walking ? Math.sin(f * 0.17 + j.phase) * 1.3
                            : Math.sin(f * 0.05 + j.phase) * 0.6;
          reaper(c, j, f, x, j.y + bob, arm, alpha, walking);

          // What it took, rising. Abstract on purpose: this marks a real departure,
          // it does not draw a character that is no longer there.
          var s = t - j.walk - 26;
          if (s > 0 && s < 46) {
            var su = s / 46;
            c.globalAlpha = (1 - su) * 0.75;
            c.fillStyle = SOUL;
            for (var k = 0; k < 3; k++) {
              var kk = su + k * 0.16;
              if (kk > 1) continue;
              c.beginPath();
              c.arc(j.x + Math.sin(kk * 7 + k * 2 + j.phase) * 4,
                    j.y + 4 - kk * 34, 2.2 - kk * 1.5, 0, 6.284);
              c.fill();
            }
            c.globalAlpha = (1 - su) * 0.5;
            c.fillStyle = "#93a1b0";
            c.font = "9px ui-monospace,Menlo,monospace";
            c.textAlign = "center";
            c.fillText(j.kind, j.x, j.y + 22);
          }
        }
      } finally { c.restore(); }
    },
  });
})();
