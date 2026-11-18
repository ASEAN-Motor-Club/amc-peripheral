(() => {
  const stage = document.getElementById("item-viewer-stage");
  const frame = document.getElementById("item-viewer-frame");
  const status = document.getElementById("item-viewer-status");
  const button = document.getElementById("item-viewer-fullscreen");
  if (!stage || !frame || !button) return;

  let ready = false;
  let fallbackExpanded = false;
  const showFallback = (message) => {
    stage.classList.add("viewer-fallback");
    frame.setAttribute("aria-hidden", "true");
    if (status) {
      status.textContent = message;
      status.hidden = false;
    }
  };
  window.setTimeout(() => {
    if (!ready && status) {
      status.textContent = "Still loading 3D…";
      status.hidden = false;
    }
  }, 20000);

  window.addEventListener("message", (event) => {
    if (event.origin !== window.location.origin || event.source !== frame.contentWindow) return;
    const data = event.data;
    if (!data || data.source !== "amc-mt-viewer") return;
    if (data.type === "ready") {
      if (data.stage !== "complete") {
        frame.hidden = false;
        frame.setAttribute("aria-hidden", "false");
        stage.classList.add("is-interactive");
        if (status) {
          status.textContent = "Loading vehicle and decals…";
          status.hidden = false;
        }
        return;
      }
      ready = true;
      frame.hidden = false;
      frame.setAttribute("aria-hidden", "false");
      stage.classList.remove("viewer-fallback");
      stage.classList.add("is-interactive");
      if (status) status.hidden = true;
      return;
    }
    if (data.type === "error" && !ready) {
      showFallback("Interactive 3D could not be loaded; showing the static preview.");
    }
  });

  const updateButton = () => {
    const expanded = document.fullscreenElement === stage || fallbackExpanded;
    button.textContent = expanded ? "Exit fullscreen" : "Fullscreen";
    button.setAttribute("aria-pressed", String(expanded));
  };

  const toggleFallback = () => {
    fallbackExpanded = !fallbackExpanded;
    stage.classList.toggle("viewer-expanded", fallbackExpanded);
    document.body.classList.toggle("viewer-expanded-open", fallbackExpanded);
    updateButton();
  };

  button.addEventListener("click", async () => {
    if (document.fullscreenElement === stage) {
      await document.exitFullscreen();
      return;
    }
    if (fallbackExpanded) {
      toggleFallback();
      return;
    }
    if (stage.requestFullscreen) {
      try {
        await stage.requestFullscreen();
        return;
      } catch (error) {
        console.debug("native fullscreen unavailable; using expanded layout", error);
      }
    }
    toggleFallback();
  });

  document.addEventListener("fullscreenchange", updateButton);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && fallbackExpanded) toggleFallback();
  });
  updateButton();
})();
