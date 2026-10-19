(function () {
  'use strict';
  let installPrompt = null;
  let installed = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

  window.addEventListener('beforeinstallprompt', function (event) {
    event.preventDefault();
    installPrompt = event;
    updateDialog();
  });
  window.addEventListener('appinstalled', function () {
    installed = true;
    installPrompt = null;
    updateDialog();
  });

  function updateDialog() {
    const dialog = document.getElementById('radarInstallDialog');
    if (!dialog) return;
    const steps = document.getElementById('radarInstallSteps');
    const confirm = document.getElementById('radarInstallConfirm');
    const status = document.getElementById('radarInstallStatus');
    confirm.hidden = installed || !installPrompt;
    steps.replaceChildren();
    status.textContent = installed ? 'Radar BDS đã được cài. Bạn có thể mở bằng biểu tượng trên màn hình chính.' : '';
    if (installed || installPrompt) return;
    const instructions = isIOS ? [
      'Mở radarbds.vn bằng Safari nếu bạn đang ở trình duyệt trong Facebook hoặc ứng dụng khác.',
      'Bấm Chia sẻ, chọn Thêm vào Màn hình chính.',
      'Bật Mở dưới dạng ứng dụng web nếu có, rồi bấm Thêm.'
    ] : /Android/i.test(navigator.userAgent) ? [
      'Mở radarbds.vn bằng Chrome nếu bạn đang ở trình duyệt trong Facebook hoặc ứng dụng khác.',
      'Bấm menu ⋮, tìm Cài đặt ứng dụng hoặc Thêm vào màn hình chính.',
      'Làm theo hướng dẫn của trình duyệt để xác nhận cài đặt.'
    ] : [
      'Mở radarbds.vn bằng Chrome hoặc Edge.',
      'Tìm biểu tượng cài ứng dụng ở thanh địa chỉ hoặc mục cài ứng dụng trong menu trình duyệt.',
      'Nếu không có tùy chọn này, bạn vẫn có thể dùng đầy đủ Radar BDS trên web.'
    ];
    instructions.forEach(function (text) {
      const item = document.createElement('li');
      item.textContent = text;
      steps.appendChild(item);
    });
  }

  document.addEventListener('click', function (event) {
    const trigger = event.target.closest('[data-radar-install]');
    if (!trigger) return;
    const dialog = document.getElementById('radarInstallDialog');
    if (!dialog) return;
    if (typeof window.closeToolsSheet === 'function') window.closeToolsSheet();
    const toolsMenu = document.getElementById('toolsMenu');
    if (toolsMenu) toolsMenu.open = false;
    document.querySelectorAll('.seo-nav-tab[aria-expanded="true"], #seoNavToggle[aria-expanded="true"]').forEach(function (button) {
      button.setAttribute('aria-expanded', 'false');
    });
    updateDialog();
    if (!dialog.open) dialog.showModal();
  }, { capture: true });

  document.addEventListener('DOMContentLoaded', function () {
    const dialog = document.getElementById('radarInstallDialog');
    if (dialog) document.body.appendChild(dialog);
    const confirm = document.getElementById('radarInstallConfirm');
    if (!confirm) return;
    confirm.addEventListener('click', async function () {
      if (!installPrompt || confirm.disabled) return;
      const prompt = installPrompt;
      installPrompt = null;
      confirm.disabled = true;
      try {
        await prompt.prompt();
        const choice = await prompt.userChoice;
        updateDialog();
        document.getElementById('radarInstallStatus').textContent = choice.outcome === 'accepted'
          ? 'Bạn đã đồng ý cài. Trình duyệt sẽ hoàn tất cài đặt Radar BDS.'
          : 'Bạn có thể cài lại từ menu trình duyệt bất cứ lúc nào.';
      } catch (_) {
        updateDialog();
        document.getElementById('radarInstallStatus').textContent = 'Chưa mở được hộp thoại cài đặt. Hãy dùng menu trình duyệt theo hướng dẫn trên.';
      } finally {
        confirm.disabled = false;
      }
    });
  }, { once: true });
})();
