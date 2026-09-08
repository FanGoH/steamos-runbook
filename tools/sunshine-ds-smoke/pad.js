/* Shared Gamepad HUD for sunshine-ds capture smoke pages. */
(function () {
  const NAMES = [
    "A", "B", "X", "Y",
    "LB", "RB", "LT", "RT",
    "View", "Menu", "LS", "RS",
    "Up", "Down", "Left", "Right",
    "Guide"
  ];

  const statusEl = document.getElementById("pad-status");
  const buttonsEl = document.getElementById("pad-buttons");
  const sticksEl = document.getElementById("pad-sticks");
  const box = document.getElementById("box");
  let seen = false;

  function ensureButtons(count) {
    if (!buttonsEl || buttonsEl.childElementCount === count) {
      return;
    }
    buttonsEl.replaceChildren();
    for (let i = 0; i < count; i++) {
      const d = document.createElement("div");
      d.className = "btn";
      d.dataset.i = String(i);
      d.textContent = NAMES[i] || ("b" + i);
      buttonsEl.appendChild(d);
    }
  }

  function deadzone(v) {
    return Math.abs(v) < 0.08 ? 0 : v;
  }

  function tick() {
    const pads = navigator.getGamepads ? navigator.getGamepads() : [];
    let gp = null;
    for (let i = 0; i < pads.length; i++) {
      if (pads[i]) {
        gp = pads[i];
        break;
      }
    }

    if (!gp) {
      if (statusEl) {
        statusEl.textContent = seen
          ? "gamepad disconnected — press a button"
          : "waiting for gamepad — press any button on Thor";
        statusEl.className = "pad-wait";
      }
      if (box && box.dataset.fromPad === "1") {
        box.style.animation = "";
        box.style.left = "";
        box.style.top = "";
        box.textContent = "MOVE";
        box.dataset.fromPad = "";
      }
      requestAnimationFrame(tick);
      return;
    }

    seen = true;
    if (statusEl) {
      statusEl.textContent = gp.id + "  index " + gp.index;
      statusEl.className = "pad-ok";
    }
    ensureButtons(gp.buttons.length);
    if (buttonsEl) {
      for (let i = 0; i < gp.buttons.length; i++) {
        const el = buttonsEl.children[i];
        if (!el) {
          continue;
        }
        const b = gp.buttons[i];
        const v = typeof b.value === "number" ? b.value : (b.pressed ? 1 : 0);
        el.classList.toggle("on", v > 0.15);
        el.style.setProperty("--v", v.toFixed(2));
      }
    }

    const lx = deadzone(gp.axes[0] || 0);
    const ly = deadzone(gp.axes[1] || 0);
    const rx = deadzone(gp.axes[2] || 0);
    const ry = deadzone(gp.axes[3] || 0);
    if (sticksEl) {
      sticksEl.textContent =
        "LS " + lx.toFixed(2) + "," + ly.toFixed(2) +
        "   RS " + rx.toFixed(2) + "," + ry.toFixed(2);
    }

    if (box) {
      box.dataset.fromPad = "1";
      box.style.animation = "none";
      const bw = box.offsetWidth || 200;
      const bh = box.offsetHeight || 200;
      const x = ((lx + 1) / 2) * Math.max(0, innerWidth - bw);
      const y = ((ly + 1) / 2) * Math.max(0, innerHeight - bh);
      box.style.left = x + "px";
      box.style.top = y + "px";
      box.textContent = gp.buttons[0] && gp.buttons[0].pressed ? "A" : "PAD";
    }

    requestAnimationFrame(tick);
  }

  window.addEventListener("gamepadconnected", function (e) {
    seen = true;
    if (statusEl) {
      statusEl.textContent = "connected: " + e.gamepad.id;
      statusEl.className = "pad-ok";
    }
  });
  window.addEventListener("gamepaddisconnected", function () {
    if (statusEl) {
      statusEl.textContent = "gamepad disconnected — press a button";
      statusEl.className = "pad-wait";
    }
  });

  tick();
})();
