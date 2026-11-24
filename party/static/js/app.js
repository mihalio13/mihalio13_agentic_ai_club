// Невеликі покращення UX. Без JS усе продовжує працювати (progressive enhancement).
(function () {
  "use strict";

  // Підтвердження небезпечних дій: <form data-confirm="Текст питання">
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    var question = form.getAttribute("data-confirm");
    if (question && !window.confirm(question)) {
      event.preventDefault();
      return;
    }
    // Захист від подвійного натискання (дубль запису / коментаря).
    var buttons = form.querySelectorAll("button[type=submit]");
    window.setTimeout(function () {
      buttons.forEach(function (b) { b.disabled = true; });
    }, 0);
  });

  // Після «Назад» у браузері (bfcache) кнопки знову активні.
  window.addEventListener("pageshow", function () {
    document.querySelectorAll("form button[type=submit]").forEach(function (b) { b.disabled = false; });
  });

  // Копіювання посилання-запрошення: <button data-copy="id-поля">
  document.addEventListener("click", function (event) {
    var button = event.target.closest ? event.target.closest("[data-copy]") : null;
    if (!button) return;
    var input = document.getElementById(button.getAttribute("data-copy"));
    if (!input) return;
    var done = function () {
      var original = button.textContent;
      button.textContent = "Скопійовано ✓";
      window.setTimeout(function () { button.textContent = original; }, 1800);
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(input.value).then(done, function () { input.select(); });
    } else {
      input.select();
      try { document.execCommand("copy"); done(); } catch (e) { /* користувач скопіює вручну */ }
    }
  });

  // Не даємо обрати дату в минулому в календарі.
  document.querySelectorAll('input[type="datetime-local"]').forEach(function (input) {
    var now = new Date();
    now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
    if (!input.value || input.value >= now.toISOString().slice(0, 16)) {
      input.min = now.toISOString().slice(0, 16);
    }
  });

  // Перевірка розміру файлу ще до відправки.
  document.querySelectorAll('input[type="file"]').forEach(function (input) {
    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      if (file && file.size > 5 * 1024 * 1024) {
        window.alert("Файл завеликий: максимум 5 МБ.");
        input.value = "";
      }
    });
  });
})();
