(function () {
  if (document.body) {
    document.body.classList.remove('no-js');
  } else {
    document.addEventListener('DOMContentLoaded', function () {
      if (document.body) {
        document.body.classList.remove('no-js');
      }
    });
  }

  // Register PWA Service Worker immediately so Chrome Desktop & Mobile offer "Install App"
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      // Remove any legacy Flutter service worker & stale cache entries
      navigator.serviceWorker.getRegistrations().then(function (regs) {
        regs.forEach(function (reg) {
          if (reg.active && reg.active.scriptURL && reg.active.scriptURL.indexOf('flutter_service_worker.js') !== -1) {
            reg.unregister();
          }
        });
      });
      if ('caches' in window) {
        caches.keys().then(function (keys) {
          keys.forEach(function (k) {
            if (k.indexOf('flutter-app') !== -1 || k.indexOf('flutter-temp') !== -1) {
              caches.delete(k);
            }
          });
        });
      }
      navigator.serviceWorker.register('/sw.js').then(function (reg) {
        reg.update();
        console.debug('BAROGROOVE PWA Service Worker active:', reg.scope);
      }).catch(function (err) {
        console.warn('BAROGROOVE Service Worker registration failed:', err);
      });
    });
  }

  // Capture Chrome's native beforeinstallprompt event for 1-click app install
  window.deferredPwaPrompt = null;
  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    window.deferredPwaPrompt = e;
    window.dispatchEvent(new CustomEvent('barogroove-pwa-installable'));
  });

  window.addEventListener('appinstalled', function () {
    window.deferredPwaPrompt = null;
    window.dispatchEvent(new CustomEvent('barogroove-pwa-installed'));
  });

  window.isBarogroovePwaInstallable = function () {
    return Boolean(window.deferredPwaPrompt);
  };

  window.isBarogrooveStandalone = function () {
    return (
      window.matchMedia('(display-mode: standalone)').matches ||
      window.matchMedia('(display-mode: window-controls-overlay)').matches ||
      window.navigator.standalone === true
    );
  };

  window.triggerBarogroovePwaInstall = async function () {
    if (!window.deferredPwaPrompt) {
      return 'unavailable';
    }
    try {
      window.deferredPwaPrompt.prompt();
      var choice = await window.deferredPwaPrompt.userChoice;
      window.deferredPwaPrompt = null;
      return choice && choice.outcome ? choice.outcome : 'dismissed';
    } catch (err) {
      console.warn('PWA install prompt error:', err);
      return 'error';
    }
  };

  window.addEventListener('load', function () {
    var boot = document.getElementById('bg-boot');
    window.addEventListener('flutter-first-frame', function () {
      if (!boot) return;
      boot.classList.add('hidden');
      setTimeout(function () { boot.remove(); }, 260);
    });
  });
})();
