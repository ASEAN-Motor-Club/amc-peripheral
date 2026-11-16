(() => {
  const tray = document.querySelector('[data-compare-tray]');
  if (!tray) return;
  const boxes = [...document.querySelectorAll('.compare-check input[type="checkbox"]')];
  const count = tray.querySelector('[data-compare-count]');
  const slots = tray.querySelector('[data-compare-slots]');
  const clear = tray.querySelector('[data-compare-clear]');
  const MAX = 4;

  function render() {
    const picked = boxes.filter(box => box.checked);
    count.textContent = String(picked.length);
    slots.replaceChildren(...picked.map(box => {
      const code = document.createElement('code');
      code.textContent = `#${box.value}`;
      return code;
    }));
    for (const box of boxes) {
      box.disabled = !box.checked && picked.length >= MAX;
    }
    tray.hidden = picked.length === 0;
  }

  for (const box of boxes) box.addEventListener('change', render);
  clear.addEventListener('click', () => {
    for (const box of boxes) box.checked = false;
    render();
  });
  render();
})();
