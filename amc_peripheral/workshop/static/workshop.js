(() => {
  const tray = document.querySelector('[data-compare-tray]');
  if (!tray) return;
  const boxes = [...document.querySelectorAll('.compare-check input[type="checkbox"]')];
  const count = tray.querySelector('[data-compare-count]');
  const slots = tray.querySelector('[data-compare-slots]');
  const clear = tray.querySelector('[data-compare-clear]');
  const open = tray.querySelector('[data-compare-open]');
  const dialog = document.querySelector('[data-compare-dialog]');
  const body = dialog?.querySelector('[data-compare-body]');
  const MAX = 4;

  const articleFor = (box) => box.closest('.vehicle-card');

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function renderColumn(article) {
    const column = element('article', 'compare-column');
    const link = article.querySelector('h3 a');
    const image = article.querySelector('.card-visual img');
    const picture = element('img');
    picture.src = image?.currentSrc || image?.src || '';
    picture.alt = link ? `${link.textContent} preview` : 'Workshop build preview';
    picture.width = 480;
    picture.height = 270;
    picture.loading = 'eager';
    if (article.dataset.snapshotKey) column.append(element('div', 'compare-placeholder', 'Snapshot pending'));
    else column.append(picture);

    const heading = element('h3');
    const headingLink = element('a', '', link?.textContent || 'Build');
    headingLink.href = link?.href || '#';
    heading.append(headingLink);
    column.append(heading);

    const byline = article.querySelector('.byline');
    if (byline) {
      const copy = element('p', 'byline');
      copy.append(...[...byline.childNodes].map((node) => node.cloneNode(true)));
      column.append(copy);
    }
    const badges = article.querySelector('.badges');
    if (badges) {
      const list = badges.cloneNode(true);
      list.setAttribute('aria-label', 'Configuration features');
      column.append(list);
    }
    const meta = article.querySelector('.card-meta');
    if (meta) {
      const copy = meta.cloneNode(true);
      copy.querySelector('time')?.remove();
      column.append(copy);
    }
    const viewer = element('a', 'primary-button', 'View in 3D');
    viewer.href = `${link?.href || '#'}viewer/`;
    column.append(viewer);
    return column;
  }

  function render() {
    const picked = boxes.filter((box) => box.checked);
    count.textContent = String(picked.length);
    slots.replaceChildren(...picked.map((box) => {
      const code = document.createElement('code');
      code.textContent = `#${box.value}`;
      return code;
    }));
    for (const box of boxes) {
      box.disabled = !box.checked && picked.length >= MAX;
    }
    tray.hidden = picked.length === 0;
    open.disabled = picked.length < 2;
  }

  for (const box of boxes) box.addEventListener('change', render);
  clear.addEventListener('click', () => {
    for (const box of boxes) box.checked = false;
    render();
  });
  open.addEventListener('click', () => {
    const picked = boxes.filter((box) => box.checked).slice(0, MAX);
    if (!body || picked.length < 2) return;
    body.replaceChildren(...picked.map((box) => renderColumn(articleFor(box))));
    dialog.showModal();
  });
  render();
})();
