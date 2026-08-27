// Proves the hook contract end to end. Delete once real effects exist.
window.FleetFX.register({
  name: "_smoke",
  onEvent(e){ console.log("[fx] event", e.type, e.soul || e.repo); },
  drawOver(w){
    const c = w.ctx;
    c.save(); c.globalAlpha = .35; c.fillStyle = "#3ddc84";
    c.font = "9px ui-monospace,Menlo,monospace"; c.textAlign = "left";
    c.fillText(`fx ok · ${w.souls.length} souls · frame ${w.frame}`, 14, w.h - 12);
    c.restore();
  },
});
