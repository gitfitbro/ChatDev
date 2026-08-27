/* fx/reaper.js — a crewmate that vanished gets collected.
 *
 * On a `vanished` event a figure walks in from the near edge of the floor, crosses to
 * the spot where that crewmate was standing, takes it, and walks back out. Three or
 * four seconds, then the floor is exactly as it was. Nothing is drawn when no one has
 * died.
 *
 * The whole difficulty is knowing where to walk to. By the time `vanished` is
 * delivered, world.html has already re-laid out the floor from the poll that no longer
 * contains the soul, so `world.soul(event.soul)` is usually already undefined — the
 * capture the README asks for succeeds only in the rare case where the event arrives a
 * poll late. So this file also remembers where every soul was standing, per frame, and
 * falls back to that, then to the room, then to drawing nothing. A reaper at the wrong
 * desk is a lie about a real agent; no reaper is merely a missed effect.
 *
 * For the same reason the destination is held as an offset inside its room rather than
 * as a point on the screen: the floor re-lays itself out on every poll and on every
 * resize, and a walk lasts longer than the gap between two polls. Anchored to the room,
 * the reaper still arrives at the desk it set out for.
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
  var MARGIN       = 34;   // how far outside the floor it waits

  var CLOAK = "#141a22", CLOAK_LO = "#0b0f14", RIM = "#3c4653";
  var VOID  = "#05070a", GLINT = "#c9d4e2";
  var STEEL = "#8792a2", SOUL = "#cfe0ff";

  var active = [];              // reapings currently on screen
  var pending = [];             // waiting for a free reaper
  var lastSeen = new Map();     // soul id -> {x, y, f}
  var pruned = 0;

  var clamp = function (v, a, b) { return v < a ? a : v > b ? b : v; };
  var ease  = function (u) { u = clamp(u, 0, 1); return u * u * (3 - 2 * u); };
  var lerp  = function (a, b, u) { return a + (b - a) * u; };
  var num   = function (v) { return typeof v === "number" && isFinite(v); };

  /* The room this event happened in. The renderer's soul id is `${roomId}:${i}:${kind}`
   * and room ids contain colons of their own, so rebuild it from all but the last two. */
  function roomOf(event, world) {
    var parts = String((event && event.soul) || "").split(":");
    var room = parts.length > 2 ? world.room(parts.slice(0, -2).join(":")) : null;
    if (room) return room;
    if (!event || !event.room) return null;
    var rooms = world.rooms || [];
    for (var i = 0; i < rooms.length; i++) if (rooms[i].name === event.room) return rooms[i];
    return null;
  }

  /* Where was this crewmate standing? Three answers, in descending order of truth. */
  function locate(event, world) {
    var live = world.soul(event.soul);
    if (live && num(live.x) && num(live.y)) return { x: live.x, y: live.y };

    var seen = lastSeen.get(event.soul);
    if (seen) return { x: seen.x, y: seen.y };

    var room = roomOf(event, world);      // the desk is lost; the room is still true
    if (room && num(room.x)) return { x: room.x + room.w / 2, y: room.y + room.h / 2 };

    return null;                          // rather nothing than the wrong desk
  }

  /* The floor's own bounds, not the canvas's: the right of the window belongs to the
   * side panel, and a reaper that walks in behind it is a reaper you never see. */
  function bounds(world) {
    var rooms = world.rooms || [], lo = Infinity, hi = -Infinity;
    for (var i = 0; i < rooms.length; i++) {
      if (!num(rooms[i].x) || !num(rooms[i].w)) continue;
      if (rooms[i].x < lo) lo = rooms[i].x;
      if (rooms[i].x + rooms[i].w > hi) hi = rooms[i].x + rooms[i].w;
    }
    if (!isFinite(lo) || !isFinite(hi)) { lo = 0; hi = world.w; }
    return { lo: Math.max(-MARGIN, lo - MARGIN), hi: Math.min(world.w + MARGIN, hi + MARGIN) };
  }

  /* A job holds an offset inside a room, so it survives the floor being re-laid out. */
  function job(at, room, event, world) {
    var b = bounds(world);
    var mid = (b.lo + b.hi) / 2;
    var j = {
      roomId: room ? room.id : null,
      dx: room ? at.x - room.x : 0,
      dy: room ? at.y - room.y : 0,
      ax: at.x, ay: at.y,                        // if the room goes, the last point stands
      kind: (event && event.kind) || "",
      fromLeft: at.x < mid,
      start: world.frame,
      phase: (world.frame % 97) / 97 * 6.283,
      total: 0,
    };
    j.flip = j.fromLeft ? 1 : -1;
    var here = where(j, world);
    j.walk = clamp(Math.abs((j.fromLeft ? b.lo : b.hi) - here.x) / WALK_SPEED, 40, 110);
    j.total = j.walk + REAP_FRAMES + LEAVE_FRAMES;
    return j;
  }

  /* Where the spot is *now*. Rooms move between polls; the desk inside one does not. */
  function where(j, world) {
    var room = j.roomId ? world.room(j.roomId) : null;
    if (room && num(room.x) && num(room.y)) return { x: room.x + j.dx, y: room.y + j.dy };
    return { x: j.ax, y: j.ay };
  }

  /* ---- state, advanced once per frame from the first hook the floor calls ---- */
  function tick(world) {
    var f = world.frame, souls = world.souls || [], i;

    for (i = 0; i < souls.length; i++) {
      var s = souls[i];
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
      active.push(job(p.at, p.room, p.event, world));
    }
  }

  /* ---- the figure ----
   * Drawn in the order you would see it: shadow, robe, then the scythe in front of the
   * robe and clear of the crown. Behind the robe the snath disappears inside the
   * silhouette and all that shows is a hook over the head, which reads as a cartoon
   * ghost rather than as something carrying a tool.
   */
  function scythe(c, x, y, angle, flip, alpha) {
    c.save();
    c.translate(x, y);
    c.scale(flip, 1);
    c.rotate(angle);
    c.globalAlpha = alpha;
    c.lineCap = "round"; c.lineJoin = "round";
    c.strokeStyle = "#59657460"; c.lineWidth = 3.2;  // a hint of shadow so it sits off the robe
    c.beginPath(); c.moveTo(0, 13); c.lineTo(0, -25); c.stroke();
    c.strokeStyle = "#5c6a79"; c.lineWidth = 1.8;    // the snath
    c.beginPath(); c.moveTo(0.6, 13); c.lineTo(-0.6, -26); c.stroke();
    c.strokeStyle = STEEL; c.lineWidth = 1.7;        // the blade, hooked back over the shaft
    c.beginPath();
    c.moveTo(-0.6, -26);
    c.quadraticCurveTo(10, -28.5, 14, -19);
    c.quadraticCurveTo(8.5, -22.5, 1.2, -21.5);
    c.stroke();
    c.restore();
  }

  function reaper(c, j, f, x, y, arm, alpha, walking) {
    var sway = Math.sin(f * (walking ? 0.16 : 0.05) + j.phase) * (walking ? 1.6 : 0.7);
    var lean = j.flip * 1.2;                      // the cowl points the way it is going

    c.save();
    c.globalAlpha = alpha;

    c.fillStyle = "#00000044";                    // it drags a little dark along with it
    c.beginPath(); c.ellipse(x, y + 11, 8, 2.8, 0, 0, 6.284); c.fill();

    // A robe: a peaked cowl, narrow shoulders, and a hem that trails behind the walk.
    var g = c.createLinearGradient(0, y - 34, 0, y + 12);
    g.addColorStop(0, CLOAK); g.addColorStop(0.62, CLOAK); g.addColorStop(1, CLOAK_LO);
    c.beginPath();
    c.moveTo(x + lean, y - 34);
    c.quadraticCurveTo(x + 7, y - 30, x + 7.8, y - 18);
    c.quadraticCurveTo(x + 9.6, y - 3, x + 9.5 + sway, y + 12);
    c.quadraticCurveTo(x + 4.5, y + 9, x, y + 12);
    c.quadraticCurveTo(x - 4.5, y + 9, x - 9.5 + sway, y + 12);
    c.quadraticCurveTo(x - 9.6, y - 3, x - 7.8, y - 18);
    c.quadraticCurveTo(x - 7, y - 30, x + lean, y - 34);
    c.closePath();
    c.fillStyle = g; c.fill();
    c.strokeStyle = RIM; c.lineWidth = 1; c.stroke();

    // Under the hood, nothing: a void set back inside the cowl, with the lit edge of
    // the hood around it. No eyes — two dots at this size only ever read as a face.
    c.beginPath();
    c.ellipse(x + j.flip * 1.2, y - 23, 4.6, 6, -j.flip * 0.12, 0, 6.284);
    c.fillStyle = VOID; c.fill();
    c.strokeStyle = "#2a323c"; c.lineWidth = 0.9; c.stroke();

    // One cold ember deep in the cowl, breathing. One is a presence; two are eyes.
    c.globalAlpha = alpha * (0.28 + 0.34 * Math.abs(Math.sin(f * 0.035 + j.phase)));
    c.fillStyle = GLINT;
    c.beginPath(); c.ellipse(x + j.flip * 1.6, y - 22.4, 1.15, 1.5, 0, 0, 6.284); c.fill();
    c.globalAlpha = alpha;

    scythe(c, x + j.flip * 11.5, y - 2, arm, j.flip, alpha);

    c.restore();
  }

  window.FleetFX.register({
    name: "reaper",

    onEvent: function (event, world) {
      // `ghosted` is a terminal closing, not a death — world.html already haunts it.
      if (!event || event.type !== "vanished" || !world) return;
      var at = locate(event, world);
      if (!at || !num(at.x) || !num(at.y)) return;
      if (pending.length >= MAX_PENDING) pending.shift();
      pending.push({ at: at, room: roomOf(event, world), event: event, f: world.frame });
    },

    // First hook of the frame, so it also carries the bookkeeping.
    drawUnder: function (world) {
      if (!world || !world.ctx) return;
      tick(world);
      if (!active.length) return;
      var c = world.ctx, f = world.frame;

      c.save();
      try {
        for (var i = 0; i < active.length; i++) {
          var j = active[i], t = f - j.start - j.walk;
          if (t < 0) continue;
          var p = where(j, world);

          // A ring closes on the spot as the scythe comes down, then fades.
          var close = ease(t / 26);
          if (t <= 30) {
            c.globalAlpha = 0.42 * (1 - close * 0.3);
            c.strokeStyle = SOUL; c.lineWidth = 1;
            c.beginPath(); c.arc(p.x, p.y + 9, lerp(13, 2, close), 0, 6.284); c.stroke();
          }
          var fade = clamp(1 - (t - 26) / (REAP_FRAMES - 26 + LEAVE_FRAMES * 0.5), 0, 1);
          if (t > 20) {
            c.globalAlpha = 0.34 * fade;
            c.fillStyle = "#0b0f14";
            c.beginPath(); c.ellipse(p.x, p.y + 8, 7, 2.4, 0, 0, 6.284); c.fill();
          }
        }
      } finally { c.restore(); }
    },

    drawOver: function (world) {
      if (!active.length || !world || !world.ctx) return;
      var c = world.ctx, f = world.frame, b = bounds(world);

      c.save();
      try {
        for (var i = 0; i < active.length; i++) {
          var j = active[i], t = f - j.start;
          var p = where(j, world);
          var edgeX = j.fromLeft ? b.lo : b.hi;
          var standX = p.x + (j.fromLeft ? -16 : 16);
          var x, alpha = 1, arm = -0.12, walking = false;

          if (t < j.walk) {                        // in
            x = lerp(edgeX, standX, ease(t / j.walk));
            alpha = clamp(t / 14, 0, 1);
            walking = true;
          } else if (t < j.walk + REAP_FRAMES) {   // the pause, and the taking
            var r = t - j.walk;
            x = standX;
            arm = r < 14 ? lerp(-0.12, -0.62, ease(r / 14))
                : r < 26 ? lerp(-0.62, 0.5, ease((r - 14) / 12))
                         : lerp(0.5, -0.12, ease((r - 26) / (REAP_FRAMES - 26)));
          } else {                                 // out
            var v = ease((t - j.walk - REAP_FRAMES) / LEAVE_FRAMES);
            x = lerp(standX, edgeX, v);
            alpha = clamp(1 - (v - 0.55) / 0.45, 0, 1);
            walking = true;
          }
          if (!num(x) || alpha <= 0.01) continue;

          var bob = walking ? Math.sin(f * 0.17 + j.phase) * 1.3
                            : Math.sin(f * 0.05 + j.phase) * 0.6;
          reaper(c, j, f, x, p.y + bob, arm, alpha, walking);

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
              c.arc(p.x + Math.sin(kk * 7 + k * 2 + j.phase) * 4,
                    p.y + 4 - kk * 34, 2.2 - kk * 1.5, 0, 6.284);
              c.fill();
            }
            c.globalAlpha = (1 - su) * 0.5;
            c.fillStyle = "#93a1b0";
            c.font = "9px ui-monospace,Menlo,monospace";
            c.textAlign = "center";
            c.fillText(j.kind, p.x, p.y + 22);
          }
        }
      } finally { c.restore(); }
    },
  });
})();
