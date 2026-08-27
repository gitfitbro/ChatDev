(() => {
  "use strict";

  const fx = window.FleetFX;
  if (!fx || typeof fx.register !== "function") return;

  const INK = "#111820";
  const SHADOW = "#070a0d";
  const GHOST_PALE = "#d7e7ff";
  const PAPER = "#eef6ff";
  const STATES = {
    working: "#3ddc84",
    idle: "#f5b544",
    stalled: "#ff5d5d",
  };
  const KINDS = {
    claude: {
      body: "#c96f42", dark: "#633726", skin: "#f2c49e",
      accent: "#ffd28a", eye: "#25140f",
    },
    codex: {
      body: "#65a9ff", dark: "#254e80", skin: "#dbeaff",
      accent: "#77f2de", eye: "#081421",
    },
    grok: {
      body: "#b983ff", dark: "#533474", skin: "#e6caff",
      accent: "#ff7ad9", eye: "#1b1028",
    },
    agent: {
      body: "#8995a5", dark: "#3e4957", skin: "#d8dee8",
      accent: "#f5b544", eye: "#111820",
    },
  };

  function block(c, color, x, y, w, h) {
    c.fillStyle = color;
    c.fillRect(x, y, w, h);
  }

  function drawShadow(c) {
    // The two stepped blocks fully cover the default ellipse.
    block(c, SHADOW, -6, 7, 12, 5);
    block(c, SHADOW, -8, 9, 16, 3);
  }

  function drawLegs(c, p, walking, step) {
    block(c, INK, -5, 3, 10, 7);
    block(c, p.dark, -4, 4, 3, 6);
    block(c, p.dark, 1, 4, 3, 6);
    block(c, INK, -5 - (walking && step ? 1 : 0), 9, 5, 3);
    block(c, INK, walking && step ? 1 : 0, 9, 5, 3);
  }

  function drawGhostTail(c, p, step) {
    block(c, INK, -6, -6, 12, 12);
    block(c, p.body, -5, -5, 10, 10);
    block(c, p.dark, -5, 4, 3, 4 + step);
    block(c, p.body, -2, 4, 4, 5 - step);
    block(c, p.dark, 2, 4, 3, 4 + step);
  }

  function drawTorso(c, p, ghost) {
    // This underpaint is deliberately larger than world.html's rounded body.
    block(c, INK, -6, -6, 12, 11);
    block(c, p.body, -5, -5, 10, 9);
    block(c, p.dark, -5, 2, 10, 2);
    block(c, ghost ? GHOST_PALE : p.accent, -1, -4, 2, 5);
  }

  function drawClaudeHead(c, p, eyesShut, facing) {
    block(c, p.skin, -4, -15, 8, 8);
    block(c, p.body, -5, -16, 10, 3);
    block(c, p.body, -5, -13, 2, 6);
    block(c, p.dark, 3, -13, 2, 6);
    block(c, p.accent, -2, -16, 4, 1);
    if (eyesShut) {
      block(c, p.eye, -3, -11, 2, 1);
      block(c, p.eye, 1, -11, 2, 1);
    } else {
      block(c, p.eye, -2 + facing, -12, 1, 2);
      block(c, p.eye, 1 + facing, -12, 1, 2);
    }
  }

  function drawCodexHead(c, p, eyesShut, facing, pulse) {
    block(c, p.body, -4, -15, 8, 8);
    block(c, p.dark, -5, -14, 1, 6);
    block(c, p.dark, 4, -14, 1, 6);
    block(c, p.dark, -4, -13, 8, 4);
    if (eyesShut) {
      block(c, p.accent, -3, -11, 2, 1);
      block(c, p.accent, 1, -11, 2, 1);
    } else {
      block(c, p.accent, -2 + facing, -12, 2, 2);
      block(c, p.accent, 1 + facing, -12, 2, 2);
    }
    block(c, p.accent, -1, -17, 2, 2);
    if (pulse === 2) block(c, p.accent, -2, -18, 4, 1);
  }

  function drawGrokHead(c, p, eyesShut, facing) {
    block(c, p.skin, -4, -15, 8, 8);
    block(c, p.dark, -5, -15, 2, 8);
    block(c, p.body, -4, -16, 8, 3);
    block(c, p.body, 2, -17, 4, 3);
    block(c, p.accent, 4, -16, 2, 1);
    if (eyesShut) {
      block(c, p.eye, -3, -11, 2, 1);
      block(c, p.eye, 1, -11, 2, 1);
    } else {
      block(c, p.eye, -2 + facing, -12, 1, 2);
      block(c, p.accent, 1 + facing, -12, 2, 2);
    }
  }

  function drawAgentHead(c, p, eyesShut, facing) {
    block(c, p.skin, -4, -15, 8, 8);
    block(c, p.body, -5, -16, 10, 4);
    block(c, p.dark, -5, -12, 2, 5);
    block(c, p.dark, 3, -12, 2, 5);
    block(c, p.accent, -1, -16, 2, 2);
    if (eyesShut) {
      block(c, p.eye, -3, -10, 2, 1);
      block(c, p.eye, 1, -10, 2, 1);
    } else {
      block(c, p.eye, -2 + facing, -11, 1, 2);
      block(c, p.eye, 1 + facing, -11, 1, 2);
    }
  }

  function drawHead(c, kind, p, eyesShut, facing, pulse) {
    // The square outline covers every pixel of the default circular head.
    block(c, INK, -5, -16, 10, 10);
    if (kind === "claude") drawClaudeHead(c, p, eyesShut, facing);
    else if (kind === "codex") drawCodexHead(c, p, eyesShut, facing, pulse);
    else if (kind === "grok") drawGrokHead(c, p, eyesShut, facing);
    else drawAgentHead(c, p, eyesShut, facing);
  }

  function drawIdle(c, p, walking, step, facing) {
    const swing = walking && step ? facing : 0;
    block(c, INK, -8 + swing, -4, 3, 9);
    block(c, p.body, -7 + swing, -3, 2, 7);
    block(c, INK, 5 - swing, -4, 3, 9);
    block(c, p.body, 5 - swing, -3, 2, 7);
    block(c, STATES.idle, -4, 1, 2, 2);
  }

  function drawWorking(c, p, pulse) {
    // Hands reach over a tiny keyboard: active and visibly at the desk.
    block(c, INK, -8, -3, 3, 8);
    block(c, p.body, -7, -2, 2, 6);
    block(c, INK, 5, -3, 3, 8);
    block(c, p.body, 5, -2, 2, 6);
    block(c, INK, -7, 3, 14, 4);
    block(c, STATES.working, -5, 4, 3, 1);
    block(c, STATES.working, -1, 4, 2, 1);
    block(c, STATES.working, 2, 4, 3, 1);

    // This replaces the primitive's three typing dots, not a second indicator.
    block(c, INK, -6, -20, 12, 4);
    for (let i = 0; i < 3; i += 1) {
      block(c, STATES.working, -4 + i * 4, -19, 2, i === pulse ? 2 : 1);
    }
  }

  function drawStalled(c, p) {
    block(c, INK, -8, -4, 3, 10);
    block(c, p.dark, -7, -3, 2, 8);
    block(c, INK, 5, -4, 3, 10);
    block(c, p.dark, 5, -3, 2, 8);
    block(c, STATES.stalled, -4, 1, 2, 2);

    // A pixel speech tile covers the rising text glyph drawn by the base renderer.
    block(c, INK, 6, -25, 8, 11);
    block(c, "#2a1218", 7, -24, 6, 9);
    block(c, STATES.stalled, 8, -23, 4, 1);
    block(c, STATES.stalled, 10, -22, 1, 1);
    block(c, STATES.stalled, 9, -21, 1, 1);
    block(c, STATES.stalled, 8, -20, 4, 1);
    block(c, STATES.stalled, 10, -18, 2, 1);
    block(c, STATES.stalled, 9, -17, 1, 1);
    block(c, STATES.stalled, 8, -16, 4, 1);
  }

  function drawArtifact(c, p, lift) {
    // Overscan by two pixels so the primitive page cannot peek around this one.
    block(c, INK, -7, -29 + lift, 14, 17);
    block(c, PAPER, -6, -28 + lift, 12, 15);
    block(c, "#b8c7d9", 3, -28 + lift, 3, 3);
    block(c, "#8191a5", -4, -24 + lift, 8, 1);
    block(c, "#8191a5", -4, -21 + lift, 7, 1);
    block(c, "#8191a5", -4, -18 + lift, 8, 1);
    block(c, STATES.working, -5, -15 + lift, 10, 1);
    block(c, p.skin, -8, -18 + lift, 2, 4);
    block(c, p.skin, 6, -18 + lift, 2, 4);
  }

  function drawSprite(c, soul, frame) {
    if (!soul || !Number.isFinite(soul.x) || !Number.isFinite(soul.y)) return;

    const kind = Object.prototype.hasOwnProperty.call(KINDS, soul.kind) ? soul.kind : "agent";
    const p = KINDS[kind];
    const phase = Number.isFinite(soul.phase) ? soul.phase : 0;
    const ghost = soul.presence === "ghost";
    const stalled = soul.state === "stalled" || soul.room?.state === "stalled";
    const working = !stalled && (soul.state === "working" || soul.state === "running" ||
      soul.state === "busy" || soul.state === "thinking");
    const pulse = Math.abs(Math.floor(frame / 6 + phase)) % 3;
    const step = Math.abs(Math.floor(frame / 8 + phase)) % 2;
    const facing = soul.flip < 0 ? -1 : 0;
    const bob = ghost
      ? Math.sin(frame * 0.04 + phase) * 2.4
      : Math.sin(frame * (soul.walking ? 0.18 : 0.05) + phase) * (soul.walking ? 1.4 : 0.7);

    c.save();
    try {
      c.translate(Math.round(soul.x), Math.round(soul.y + bob));
      c.globalAlpha = ghost ? 0.46 : 1;

      if (ghost) drawGhostTail(c, p, step);
      else {
        drawShadow(c);
        drawLegs(c, p, Boolean(soul.walking), step);
      }
      drawTorso(c, p, ghost);
      drawHead(c, kind, p, stalled, facing, pulse);

      if (stalled) drawStalled(c, p);
      else if (working) drawWorking(c, p, pulse);
      else drawIdle(c, p, Boolean(soul.walking), step, soul.flip < 0 ? -1 : 1);

      if (Array.isArray(soul.artifacts) && soul.artifacts.length) {
        c.globalAlpha = ghost ? 0.78 : 1;
        drawArtifact(c, p, Math.round(Math.sin(frame * 0.06 + phase) * 1.2));
      }
    } finally {
      c.restore();
    }
  }

  fx.register({
    name: "sprites",
    drawOver(world) {
      try {
        if (!world || !world.ctx || !Array.isArray(world.souls)) return;
        const frame = Number.isFinite(world.frame) ? world.frame : 0;
        for (const soul of world.souls) {
          try { drawSprite(world.ctx, soul, frame); }
          catch (_) { /* One malformed soul degrades to its primitive. */ }
        }
      } catch (_) { /* An unusable world degrades to the base renderer. */ }
    },
  });
})();
