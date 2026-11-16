(function () {
  "use strict";
  var data = [];
  var $ = function (id) { return document.getElementById(id); };
  var list = $("results"), count = $("count");
  var MAX = 200;
  var fmt = null;
  try { fmt = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }); } catch (e) {}

  function render() {
    var q = $("q").value.trim().toLowerCase();
    var from = $("from").value, to = $("to").value;
    var cat = $("cat").value, reg = $("reg").value, src = $("src").value;
    var out = data.filter(function (r) {
      if (q && r.t.toLowerCase().indexOf(q) === -1) return false;
      if (cat && r.c !== cat) return false;
      if (reg && r.r !== reg) return false;
      if (src && r.p !== src) return false;
      var day = r.d ? r.d.slice(0, 10) : "";
      if (from && (!day || day < from)) return false;
      if (to && (!day || day > to)) return false;
      return true;
    });
    list.textContent = "";
    out.slice(0, MAX).forEach(function (r) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = r.u; a.rel = "noopener noreferrer"; a.target = "_blank"; a.textContent = r.t;
      var meta = document.createElement("p");
      meta.className = "meta";
      var parts = [r.p, r.c, r.r, r.d && fmt ? fmt.format(new Date(r.d)) : (r.d || "Date not provided")];
      parts.forEach(function (t, i) {
        var s = document.createElement("span");
        if (i === 0) s.className = "pub";
        s.textContent = t;
        meta.appendChild(s);
      });
      li.appendChild(a); li.appendChild(meta); list.appendChild(li);
    });
    count.textContent = out.length === 0 ? "No stories match." :
      "Showing " + Math.min(out.length, MAX) + " of " + out.length + " stories. Date filters use the UTC publication date.";
  }

  fetch("../data/archive.json").then(function (r) { return r.json(); }).then(function (j) {
    data = j; render();
  }).catch(function () { count.textContent = "The archive could not be loaded."; });

  ["q", "from", "to", "cat", "reg", "src"].forEach(function (id) {
    $(id).addEventListener("input", render);
    $(id).addEventListener("change", render);
  });
  $("af").addEventListener("submit", function (e) { e.preventDefault(); });
})();
