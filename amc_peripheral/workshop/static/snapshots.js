(() => {
  const cards = [...document.querySelectorAll("[data-snapshot-key][data-snapshot-api]")];
  if (!cards.length) return;

  const pending = new Map();
  let pollTimer = null;

  const finish = (article, snapshot) => {
    const key = article.dataset.snapshotKey;
    if (snapshot.status === "ready" && snapshot.url) {
      const image = article.querySelector(".card-visual img");
      const cardUrl = snapshot.url.replace(/\.webp$/, "-card.webp");
      image.src = cardUrl;
      image.srcset = `${cardUrl} 480w, ${snapshot.url} 960w`;
      article.querySelectorAll("[data-preview-pending]").forEach((element) => {
        element.hidden = true;
      });
      pending.delete(key);
      delete article.dataset.snapshotApi;
      return;
    }
    if (["unsupported", "failed_permanent"].includes(snapshot.status)) {
      article.querySelectorAll("[data-preview-pending]").forEach((element) => {
        element.hidden = true;
      });
      pending.delete(key);
      delete article.dataset.snapshotApi;
    }
  };

  const poll = async () => {
    pollTimer = null;
    if (!pending.size || document.hidden) return;
    const keys = [...pending.keys()].slice(0, 48);
    try {
      const response = await fetch(`/api/workshop/snapshots?keys=${encodeURIComponent(keys.join(","))}`, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (response.ok) {
        const payload = await response.json();
        for (const [key, snapshot] of Object.entries(payload.snapshots || {})) {
          const article = pending.get(key);
          if (article && snapshot) finish(article, snapshot);
        }
      }
    } catch (error) {
      console.debug("snapshot batch poll failed", error);
    }
    schedulePoll();
  };

  const schedulePoll = () => {
    if (!pollTimer && pending.size) pollTimer = window.setTimeout(poll, 4000);
  };

  const enqueue = async (article) => {
    if (!article.dataset.snapshotApi) return;
    const key = article.dataset.snapshotKey;
    pending.set(key, article);
    schedulePoll();
    try {
      const response = await fetch(article.dataset.snapshotApi, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (response.ok) finish(article, await response.json());
    } catch (error) {
      console.debug("snapshot enqueue failed", error);
    }
  };

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) schedulePoll();
  });

  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        observer.unobserve(entry.target);
        enqueue(entry.target);
      }
    }, { rootMargin: "250px 0px" });
    cards.forEach((card) => observer.observe(card));
  } else {
    cards.forEach(enqueue);
  }
})();
