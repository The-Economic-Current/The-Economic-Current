(function () {
  "use strict";
  var chips = Array.prototype.slice.call(document.querySelectorAll("#evchips .chip"));
  var events = Array.prototype.slice.call(document.querySelectorAll(".event"));
  chips.forEach(function (c) { c.addEventListener("click", function () {
    var t = c.getAttribute("data-type");
    chips.forEach(function (o) { o.setAttribute("aria-pressed", o === c ? "true" : "false"); });
    events.forEach(function (e) { e.hidden = !!t && e.getAttribute("data-type") !== t; });
  }); });
})();
