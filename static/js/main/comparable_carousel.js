(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.RadarComparableCarousel = api;
}(typeof window !== 'undefined' ? window : globalThis, function () {
  function paginate(items, size) {
    const source = Array.isArray(items) ? items : [];
    const safeSize = Math.max(1, Number(size) || 1);
    const pages = [];
    for (let index = 0; index < source.length; index += safeSize) {
      pages.push(source.slice(index, index + safeSize));
    }
    return pages;
  }

  function pageSize(width) {
    const viewport = Number(width) || 0;
    if (viewport >= 1100) return 6;
    if (viewport >= 600) return 4;
    return 1;
  }

  function clampPage(page, total) {
    const max = Math.max(0, (Number(total) || 0) - 1);
    return Math.min(max, Math.max(0, Number(page) || 0));
  }

  function statusLabel(page, total) {
    const count = Math.max(0, Number(total) || 0);
    return count ? `Trang ${clampPage(page, count) + 1} / ${count}` : '';
  }

  function swipeDirection(startX, endX) {
    const delta = Number(startX) - Number(endX);
    if (Math.abs(delta) < 45) return 0;
    return delta > 0 ? 1 : -1;
  }

  function mount(rootElement, items, options) {
    const root = rootElement;
    const config = options || {};
    if (!root) return { destroy() {} };

    const track = root.querySelector('[data-comparable-track]');
    const previous = root.querySelector('[data-comparable-prev]');
    const next = root.querySelector('[data-comparable-next]');
    const status = root.querySelector('[data-comparable-status]');
    const dots = root.querySelector('[data-comparable-dots]');
    const controls = root.querySelector('[data-comparable-controls]');
    const view = root.ownerDocument && root.ownerDocument.defaultView;
    if (!track) return { destroy() {} };

    let currentPage = 0;
    let touchStartX = 0;
    let resizeTimer = null;
    let pages = [];

    function cardHtml(item) {
      const renderer = view && view.RadarSignalCard;
      if (!renderer || typeof renderer.render !== 'function') return '';
      return renderer.render(item, {
        context: 'comparable',
        openMode: config.openMode || 'link',
        openHandler: config.openHandler || 'openSignal',
        showFavorite: false,
        showContact: false,
      });
    }

    function update() {
      currentPage = clampPage(currentPage, pages.length);
      track.querySelectorAll('.sm-comparable-slide').forEach((slide, index) => {
        const active = index === currentPage;
        slide.hidden = !active;
        slide.setAttribute('aria-hidden', active ? 'false' : 'true');
      });
      if (previous) previous.disabled = currentPage <= 0;
      if (next) next.disabled = currentPage >= pages.length - 1;
      if (status) status.textContent = statusLabel(currentPage, pages.length);
      if (dots) {
        dots.querySelectorAll('button').forEach((dot, index) => {
          dot.classList.toggle('active', index === currentPage);
          dot.setAttribute('aria-current', index === currentPage ? 'true' : 'false');
        });
      }
    }

    function goTo(page) {
      currentPage = clampPage(page, pages.length);
      update();
    }

    function render() {
      const size = pageSize(view ? view.innerWidth : 1440);
      pages = paginate(items, size);
      currentPage = clampPage(currentPage, pages.length);
      if (!pages.length) {
        track.innerHTML = '<div class="sm-empty-state">Chưa có lô tương tự phù hợp.</div>';
      } else {
        track.innerHTML = pages.map((page, pageIndex) => `
          <div class="sm-comparable-slide" role="group" aria-label="Nhóm ${pageIndex + 1} / ${pages.length}">
            <div class="sm-comparable-grid">${page.map(cardHtml).join('')}</div>
          </div>
        `).join('');
      }
      if (dots) {
        dots.innerHTML = pages.map((_, index) => `
          <button type="button" aria-label="Xem nhóm ${index + 1}" data-page="${index}"></button>
        `).join('');
      }
      if (controls) controls.hidden = pages.length <= 1;
      update();
    }

    function onPrevious() { goTo(currentPage - 1); }
    function onNext() { goTo(currentPage + 1); }
    function onDots(event) {
      const button = event.target.closest('[data-page]');
      if (button) goTo(Number(button.dataset.page));
    }
    function onKeydown(event) {
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        onPrevious();
      } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        onNext();
      }
    }
    function onTouchStart(event) {
      touchStartX = event.changedTouches[0].clientX;
    }
    function onTouchEnd(event) {
      const direction = swipeDirection(touchStartX, event.changedTouches[0].clientX);
      if (direction) goTo(currentPage + direction);
    }
    function onResize() {
      if (resizeTimer) view.clearTimeout(resizeTimer);
      resizeTimer = view.setTimeout(render, 120);
    }

    if (previous) previous.addEventListener('click', onPrevious);
    if (next) next.addEventListener('click', onNext);
    if (dots) dots.addEventListener('click', onDots);
    root.addEventListener('keydown', onKeydown);
    root.addEventListener('touchstart', onTouchStart, { passive: true });
    root.addEventListener('touchend', onTouchEnd, { passive: true });
    if (view) view.addEventListener('resize', onResize);
    render();

    return {
      destroy() {
        if (previous) previous.removeEventListener('click', onPrevious);
        if (next) next.removeEventListener('click', onNext);
        if (dots) dots.removeEventListener('click', onDots);
        root.removeEventListener('keydown', onKeydown);
        root.removeEventListener('touchstart', onTouchStart);
        root.removeEventListener('touchend', onTouchEnd);
        if (view) view.removeEventListener('resize', onResize);
        if (resizeTimer && view) view.clearTimeout(resizeTimer);
      },
      goTo,
    };
  }

  return { paginate, pageSize, clampPage, statusLabel, swipeDirection, mount };
}));
