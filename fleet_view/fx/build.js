(() => {
  "use strict";

  const STORAGE_KEY = "fleet.fx.build.v1";
  const BRICK_W = 10;
  const BRICK_H = 7;
  const GAP = 2;
  const RISE_FRAMES = 42;

  function emptyCounts(){ return Object.create(null); }

  function loadCounts(){
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) return emptyCounts();
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return emptyCounts();

      const safe = emptyCounts();
      for (const [key, count] of Object.entries(parsed))
        if (Number.isSafeInteger(count) && count > 0) safe[key] = count;
      return safe;
    } catch (_) {
      return emptyCounts();
    }
  }

  const counts = loadCounts();
  const rising = new Map();

  function saveCounts(){
    try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(counts)); }
    catch (_) { /* Decoration still works for this session when storage is unavailable. */ }
  }

  function roomKey(room){
    if (!room || room.id === undefined || room.id === null) return null;
    return `${String(room.repo || "")}\u0000${String(room.id)}`;
  }

  function shippedNumber(event){
    const match = /^#(\d+)$/.exec(String(event?.room || ""));
    if (!match) return null;
    const number = Number(match[1]);
    return Number.isSafeInteger(number) ? number : null;
  }

  function shippedRoom(event, world){
    const number = shippedNumber(event);
    if (number === null || !Array.isArray(world?.rooms)) return null;

    const matches = world.rooms.filter(room => room?.pr !== undefined &&
      room.pr !== null && Number(room.pr) === number);
    if (!matches.length) return null;

    // PR numbers repeat across repositories. If the event names a repository, an
    // unmatched or ambiguous room is not evidence enough to decorate anything.
    if (event.repo !== undefined && event.repo !== null) {
      const inRepo = matches.filter(room => String(room?.repo || "") === String(event.repo));
      return inRepo.length === 1 ? inRepo[0] : null;
    }
    return matches.length === 1 ? matches[0] : null;
  }

  function onEvent(event, world){
    try {
      if (event?.type !== "shipped") return;
      const room = shippedRoom(event, world);
      const key = roomKey(room);
      if (!key) return;

      const count = Number.isSafeInteger(counts[key]) ? counts[key] + 1 : 1;
      if (!Number.isSafeInteger(count)) return;
      counts[key] = count;
      rising.set(key, {
        index: count - 1,
        start: Number.isFinite(world?.frame) ? world.frame : 0,
      });
      saveCounts();
    } catch (_) {
      // An effect is decoration. Bad event or storage data must never stop the floor.
    }
  }

  function drawWall(ctx, room, count, frame, rise){
    const {x, y, w, h} = room || {};
    if (![x, y, w, h].every(Number.isFinite) || w < 36 || h < 58) return;

    const cols = Math.max(1, Math.min(8, Math.floor((w - 26) / (BRICK_W + GAP))));
    const rows = Math.max(1, Math.min(5, Math.floor((h - 48) / (BRICK_H + GAP))));
    const capacity = cols * rows;
    const visible = Math.min(count, capacity);
    const animatedSlot = Math.min(count - 1, capacity - 1);
    const floorY = y + h - 11;
    const right = x + w - 12;
    let topY = floorY - BRICK_H;

    ctx.save();
    try {
      const foundationW = Math.min(cols, visible) * (BRICK_W + GAP) + 4;
      ctx.fillStyle = "#09100d";
      ctx.fillRect(right - foundationW + 2, floorY + 2, foundationW, 3);
      ctx.fillStyle = "#2a4b3d";
      ctx.fillRect(right - foundationW, floorY, foundationW, 2);

      for (let slot = 0; slot < visible; slot++) {
        const row = Math.floor(slot / cols);
        const col = slot % cols;
        const targetX = right - BRICK_W - col * (BRICK_W + GAP) - (row % 2 ? GAP : 0);
        const targetY = floorY - BRICK_H - row * (BRICK_H + GAP);
        topY = Math.min(topY, targetY);

        let brickY = targetY;
        let progress = 1;
        if (rise && slot === animatedSlot) {
          progress = Math.max(0, Math.min(1, (frame - rise.start) / RISE_FRAMES));
          const eased = 1 - Math.pow(1 - progress, 3);
          brickY = floorY + (targetY - floorY) * eased;
        }

        ctx.globalAlpha = .55 + progress * .45;
        ctx.fillStyle = slot === animatedSlot && progress < 1 ? "#66f2a3" : "#347254";
        ctx.fillRect(targetX, brickY, BRICK_W, BRICK_H);
        ctx.strokeStyle = "#79c99c";
        ctx.lineWidth = .7;
        ctx.strokeRect(targetX + .35, brickY + .35, BRICK_W - .7, BRICK_H - .7);

        if (slot === animatedSlot && progress < 1) {
          ctx.globalAlpha = 1 - progress;
          ctx.fillStyle = "#b9ffd5";
          const phase = Math.floor(frame / 4);
          for (let spark = 0; spark < 3; spark++) {
            const sx = targetX + 2 + ((phase + spark * 3) % 8);
            const sy = brickY - 2 - ((phase + spark * 2) % 7);
            ctx.fillRect(sx, sy, 1.5, 1.5);
          }
        }
      }

      ctx.globalAlpha = .9;
      ctx.fillStyle = "#9adbb5";
      ctx.font = "8px ui-monospace,Menlo,monospace";
      ctx.textAlign = "right";
      ctx.fillText(`×${count}`, right, topY - 4);
    } finally {
      ctx.restore();
    }
  }

  function drawUnder(world){
    try {
      const ctx = world?.ctx;
      if (!ctx || !Array.isArray(world?.rooms)) return;
      const frame = Number.isFinite(world.frame) ? world.frame : 0;

      for (const room of world.rooms) {
        const key = roomKey(room);
        const count = key ? counts[key] : 0;
        if (!Number.isSafeInteger(count) || count < 1) continue;

        const rise = rising.get(key);
        drawWall(ctx, room, count, frame, rise);
        if (rise && frame - rise.start >= RISE_FRAMES) rising.delete(key);
      }
    } catch (_) {
      // Invalid canvas state should cost only this decoration and this frame.
    }
  }

  try {
    window.FleetFX?.register?.({name: "build", onEvent, drawUnder});
  } catch (_) {
    // A missing registry means the host is not ready; there is nothing useful to draw.
  }
})();
