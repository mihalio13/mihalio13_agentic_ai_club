// Тусовка — покращення UX. Без JS усе продовжує працювати (progressive enhancement).
// Жодних inline-скриптів/обробників: усе підключається тут, щоб CSP лишалась суворою.
(function () {
  "use strict";

  var MAX_UPLOAD = 5 * 1024 * 1024;
  var ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp"];

  function closest(el, selector) {
    return el && el.closest ? el.closest(selector) : null;
  }

  // --- Підтвердження небезпечних дій + захист від подвійного натискання -----
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    var question = form.getAttribute("data-confirm");
    if (question && !window.confirm(question)) {
      event.preventDefault();
      return;
    }
    var buttons = form.querySelectorAll("button[type=submit]");
    window.setTimeout(function () {
      buttons.forEach(function (b) { b.disabled = true; b.setAttribute("aria-busy", "true"); });
    }, 0);
  });

  // Після «Назад» у браузері (bfcache) кнопки знову активні.
  window.addEventListener("pageshow", function () {
    document.querySelectorAll("form button[type=submit]").forEach(function (b) {
      b.disabled = false;
      b.removeAttribute("aria-busy");
    });
  });

  // --- Кліки: копіювання, закриття тостів, показ пароля, меню --------------
  document.addEventListener("click", function (event) {
    var target = event.target;

    var copyBtn = closest(target, "[data-copy]");
    if (copyBtn) {
      var input = document.getElementById(copyBtn.getAttribute("data-copy"));
      var label = copyBtn.querySelector("span") || copyBtn;
      if (!input) return;
      var done = function () {
        var original = label.textContent;
        label.textContent = "Скопійовано";
        copyBtn.classList.add("btn-success");
        window.setTimeout(function () {
          label.textContent = original;
          copyBtn.classList.remove("btn-success");
        }, 1800);
      };
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(input.value).then(done, function () { input.select(); });
      } else {
        input.select();
        try { document.execCommand("copy"); done(); } catch (e) { /* скопіюють вручну */ }
      }
      return;
    }

    var dismiss = closest(target, "[data-dismiss]");
    if (dismiss) {
      var toast = closest(dismiss, ".toast");
      if (toast) toast.remove();
      return;
    }

    var toggle = closest(target, "[data-toggle-password]");
    if (toggle) {
      var field = document.getElementById(toggle.getAttribute("data-toggle-password"));
      if (!field) return;
      var show = field.type === "password";
      field.type = show ? "text" : "password";
      toggle.setAttribute("aria-pressed", show ? "true" : "false");
      toggle.setAttribute("aria-label", show ? "Сховати пароль" : "Показати пароль");
      return;
    }

    // Закрити меню акаунта при кліку поза ним.
    document.querySelectorAll("details[data-menu][open]").forEach(function (menu) {
      if (!menu.contains(target)) menu.removeAttribute("open");
    });
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    document.querySelectorAll("details[data-menu][open]").forEach(function (menu) {
      menu.removeAttribute("open");
      var summary = menu.querySelector("summary");
      if (summary) summary.focus();
    });
  });

  // Успішні повідомлення зникають самі.
  document.querySelectorAll(".toast-success, .toast-info").forEach(function (toast) {
    window.setTimeout(function () { toast.remove(); }, 6000);
  });

  // --- Дата: не даємо обрати минуле в календарі ----------------------------
  document.querySelectorAll('input[type="datetime-local"]').forEach(function (input) {
    var now = new Date();
    now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
    var min = now.toISOString().slice(0, 16);
    if (!input.value || input.value >= min) input.min = min;
  });

  // --- Обкладинка: перевірка і прев'ю до відправки -------------------------
  document.querySelectorAll("[data-dropzone]").forEach(function (zone) {
    var input = zone.querySelector('input[type="file"]');
    var preview = zone.querySelector("[data-dropzone-preview]");
    var name = zone.querySelector("[data-dropzone-name]");
    var defaultName = name ? name.textContent : "";
    var currentUrl = null;
    if (!input) return;

    function reset(message) {
      input.value = "";
      zone.classList.remove("has-preview");
      if (preview) preview.hidden = true;
      if (name) name.textContent = defaultName;
      if (message) window.alert(message);
    }

    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      if (currentUrl) { URL.revokeObjectURL(currentUrl); currentUrl = null; }
      if (!file) { reset(); return; }
      if (ALLOWED_TYPES.indexOf(file.type) === -1) { reset("Підтримуються лише JPEG, PNG та WebP."); return; }
      if (file.size > MAX_UPLOAD) { reset("Файл завеликий: максимум 5 МБ."); return; }
      if (name) name.textContent = file.name;
      if (preview) {
        currentUrl = URL.createObjectURL(file);
        preview.src = currentUrl;
        preview.hidden = false;
        zone.classList.add("has-preview");
      }
    });

    ["dragenter", "dragover"].forEach(function (type) {
      zone.addEventListener(type, function () { zone.classList.add("is-dragover"); });
    });
    ["dragleave", "drop"].forEach(function (type) {
      zone.addEventListener(type, function () { zone.classList.remove("is-dragover"); });
    });
  });
})();
