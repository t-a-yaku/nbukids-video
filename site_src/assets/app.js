/* Відеотека НБУ для дітей: фільтр на сторінці, підказки карти, пошук */
(function () {
  "use strict";

  function norm(s) {
    return (s || "").toLowerCase()
      .replace(/[’ʼ'`"«»]/g, "")
      .replace(/ё/g, "е")
      .replace(/[^0-9a-zа-яіїєґ\s-]/g, " ")
      .replace(/\s+/g, " ").trim();
  }
  function plural(n, one, few, many) {
    var a = n % 10, b = n % 100;
    if (a === 1 && b !== 11) return n + " " + one;
    if (a >= 2 && a <= 4 && (b < 12 || b > 14)) return n + " " + few;
    return n + " " + many;
  }
  var topForm = document.querySelector(".vhead .search");
  var searchUrl = topForm ? topForm.getAttribute("action") : "poshuk/";

  /* 1. Фільтр карток на сторінці серії чи розділу */
  document.querySelectorAll("[data-filter]").forEach(function (box) {
    var input = box.querySelector("input");
    var empty = box.querySelector(".filter-empty");
    var grid = box.nextElementSibling;
    while (grid && !grid.classList.contains("grid")) grid = grid.nextElementSibling;
    if (!grid) return;
    var cards = Array.prototype.slice.call(grid.querySelectorAll(".card"));
    cards.forEach(function (c) { c._t = norm(c.getAttribute("data-title")); });
    input.addEventListener("input", function () {
      var words = norm(input.value).split(" ").filter(Boolean);
      var shown = 0;
      cards.forEach(function (c) {
        var ok = words.every(function (w) { return c._t.indexOf(w) !== -1; });
        c.hidden = !ok;
        if (ok) shown++;
      });
      empty.hidden = shown > 0;
    });
    var global = box.querySelector("[data-global]");
    if (global) global.addEventListener("click", function (e) {
      e.preventDefault();
      location.href = searchUrl + "?q=" + encodeURIComponent(input.value);
    });
  });

  /* 2. Карта: підпис під картою і підсвічування області у списку */
  document.querySelectorAll(".mapbox").forEach(function (box) {
    var tip = box.querySelector(".map-tip");
    var initial = tip ? tip.textContent : "";
    var links = box.querySelectorAll(".regions a");
    box.querySelectorAll(".map a").forEach(function (a) {
      var name = a.getAttribute("data-name");
      var n = +a.getAttribute("data-count");
      function on() {
        if (tip) tip.textContent = name + " — " + (n ? plural(n, "матеріал", "матеріали", "матеріалів") : "матеріали готуються");
        links.forEach(function (l) { l.classList.toggle("hl", l.getAttribute("href") === a.getAttribute("href")); });
      }
      function off() {
        if (tip) tip.textContent = initial;
        links.forEach(function (l) { l.classList.remove("hl"); });
      }
      a.addEventListener("mouseenter", on);
      a.addEventListener("focus", on);
      a.addEventListener("mouseleave", off);
      a.addEventListener("blur", off);
    });
  });

  /* 3. Сторінка пошуку */
  var form = document.querySelector("[data-search-page]");
  if (!form) return;
  var input = form.querySelector("input");
  var results = document.querySelector("[data-results]");
  var status = document.querySelector("[data-status]");
  var pills = document.querySelector("[data-sec-filter]");
  var root = form.getAttribute("data-root");
  var params = new URLSearchParams(location.search);
  input.value = params.get("q") || "";
  var index = null, secFilter = -1;

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
  }
  var MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня", "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"];
  function hdate(d) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d || "");
    return m ? (+m[3]) + " " + MONTHS[+m[2] - 1] + " " + m[1] : "";
  }

  /* «Луцька», «казки», «лікарем» → основа слова, щоб знаходились і інші відмінки */
  function stem(w) {
    return w.length > 4 ? w.replace(/(ами|ями|ові|еві|ого|ому|ими|іми|ий|ій|ою|ею|ам|ям|ах|ях|ом|ем|ів|их|а|я|у|ю|і|и|о|е|ь|й)$/, "") : w;
  }
  function run() {
    if (!index) return;
    var q = norm(input.value);
    var words = q.split(" ").filter(Boolean).map(stem);
    var url = new URL(location.href);
    if (input.value) url.searchParams.set("q", input.value); else url.searchParams.delete("q");
    history.replaceState(null, "", url);
    if (!words.length) {
      results.innerHTML = "";
      pills.hidden = true;
      status.textContent = "Введіть слово: назву казки, міста, річки чи професії.";
      return;
    }
    var found = [];
    index.items.forEach(function (it) {
      var title = it._t, all = it._all, score = 0;
      for (var i = 0; i < words.length; i++) {
        var w = words[i];
        if (all.indexOf(w) === -1) return;
        score += title.indexOf(w) !== -1 ? (title.indexOf(w) === 0 || title.indexOf(" " + w) !== -1 ? 3 : 2) : 1;
      }
      found.push({ it: it, score: score });
    });
    found.sort(function (a, b) { return b.score - a.score || (b.it.d > a.it.d ? 1 : -1); });

    var bySec = {};
    found.forEach(function (f) { bySec[f.it.s] = (bySec[f.it.s] || 0) + 1; });
    var secs = Object.keys(bySec);
    if (secFilter !== -1 && !bySec[secFilter]) secFilter = -1;
    pills.hidden = secs.length < 2;
    pills.innerHTML = '<button type="button" data-s="-1" aria-pressed="' + (secFilter === -1) + '">Усі <em>' + found.length + "</em></button>" +
      secs.map(function (s) {
        return '<button type="button" data-s="' + s + '" aria-pressed="' + (secFilter === +s) + '">' + esc(index.sections[s]) + " <em>" + bySec[s] + "</em></button>";
      }).join("");

    var shown = found.filter(function (f) { return secFilter === -1 || f.it.s === secFilter; }).slice(0, 120);
    status.textContent = found.length ? "Знайдено " + plural(found.length, "відео", "відео", "відео") : "Нічого не знайдено. Спробуйте інше або коротше слово.";
    results.innerHTML = shown.map(function (f) {
      var it = f.it;
      return '<a class="card" href="' + root + esc(it.u) + '">' +
        '<span class="thumb"><img src="' + (it.th ? esc(it.th) : root + "assets/no-thumb.svg") + '" alt="" width="320" height="180" loading="lazy"><span class="play" aria-hidden="true"></span></span>' +
        '<span class="card-body"><span class="card-title">' + esc(it.t) + "</span>" +
        '<span class="card-meta">' + esc(it.p) + (it.d ? " · " + hdate(it.d) : "") + "</span>" +
        (it.r ? '<span class="chip">📍 ' + esc(it.r.replace(" область", "")) + "</span>" : "") +
        "</span></a>";
    }).join("");
  }

  pills.addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (!b) return;
    secFilter = +b.getAttribute("data-s");
    run();
  });
  form.addEventListener("submit", function (e) { e.preventDefault(); run(); });
  var timer;
  input.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(run, 150); });

  status.textContent = "Завантаження…";
  fetch(form.getAttribute("data-index"))
    .then(function (r) { return r.json(); })
    .then(function (data) {
      data.items.forEach(function (it) {
        it._t = norm(it.t);
        it._all = norm([it.t, it.p, it.r, data.sections[it.s], it.x].join(" "));
      });
      index = data;
      run();
    })
    .catch(function () { status.textContent = "Не вдалося завантажити пошук. Оновіть сторінку."; });
})();
