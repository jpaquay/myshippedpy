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

  window.addEventListener('load', function () {
    var boot = document.getElementById('bg-boot');
    window.addEventListener('flutter-first-frame', function () {
      if (!boot) return;
      boot.classList.add('hidden');
      setTimeout(function () { boot.remove(); }, 260);
    });
  });
})();
