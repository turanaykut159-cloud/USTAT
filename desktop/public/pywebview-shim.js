/**
 * ÜSTAT v5.9 — pywebview → electronAPI shim.
 *
 * pywebview js_api'yi window.pywebview.api olarak açar.
 * React bileşenleri window.electronAPI kullanır (Electron mirası).
 * Bu script aradaki köprüyü kurar.
 *
 * Vite public/ klasöründe → dist/'e olduğu gibi kopyalanır.
 * index.html'de React'ten ÖNCE yüklenir.
 */
(function () {
  var MAX_RETRIES = 50;   // 50 × 100ms = 5sn
  var retries = 0;

  function createShim() {
    var api = (window.pywebview && window.pywebview.api) || window.pywebviewApi;
    if (!api) {
      retries++;
      if (retries < MAX_RETRIES) {
        setTimeout(createShim, 100);
      }
      return;
    }

    window.electronAPI = {
      windowMinimize:        function ()    { return api.minimize(); },
      windowMaximize:        function ()    { return api.maximize(); },
      windowClose:           function ()    { return api.close_window(); },
      windowIsMaximized:     function ()    { return api.is_maximized(); },
      toggleAlwaysOnTop:     function ()    { return api.toggle_on_top(); },
      getAlwaysOnTop:        function ()    { return api.get_on_top(); },
      setAlwaysOnTop:        function (val) { return api.set_on_top(val); },
      safeQuit:              function ()    { return api.safe_quit(); },
      logToMain:             function (level, msg) { return api.log_from_renderer(level, msg); },
      launchMT5:             function (creds) { return api.launch_mt5(JSON.stringify(creds)); },
      sendOTP:               function (code)  { return api.send_otp(code); },
      getMT5Status:          function ()    { return api.get_mt5_status(); },
      getSavedCredentials:   function ()    { return api.get_saved_credentials(); },
      clearCredentials:      function ()    { return api.clear_credentials(); },
      verifyMT5Connection:   function ()    { return api.verify_mt5(); },
      onFocusOTPInputRequested: function () { return function () {}; }
    };

    console.log('[USTAT] electronAPI shim aktif (pywebview backend)');
  }

  // pywebview hazırsa hemen, değilse event + polling
  if (window.pywebview && window.pywebview.api) {
    createShim();
  } else {
    window.addEventListener('pywebviewready', createShim);
    setTimeout(createShim, 100);
  }
})();
