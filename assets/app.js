(function () {
  "use strict";
  var tz = "";
  try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch (e) {}

  function local(opts) {
    try { return new Intl.DateTimeFormat(undefined, opts); } catch (e) { return null; }
  }
  var timeFmt = local({ hour: "2-digit", minute: "2-digit" });
  var fullFmt = local({ day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
  var dayFmt = local({ weekday: "long", day: "numeric", month: "long", year: "numeric" });

  // Status line: full local date and time
  document.querySelectorAll("time.full").forEach(function (t) {
    var d = new Date(t.getAttribute("datetime"));
    if (fullFmt && !isNaN(d)) t.textContent = fullFmt.format(d);
  });

  var feed = document.getElementById("feed");
  if (!feed) return;

  var tzNote = document.getElementById("tz");
  if (tzNote && tz) tzNote.textContent = "Times shown in your time zone (" + tz + "). Original publication times are stored in UTC.";

  var stories = Array.prototype.slice.call(feed.querySelectorAll(".story"));
  var lastDay = "";
  stories.forEach(function (s) {
    var ts = s.getAttribute("data-ts");
    var d = ts ? new Date(ts) : null;
    if (!d || isNaN(d) || !timeFmt || !dayFmt) return;
    var t = s.querySelector("time.t");
    if (t) t.textContent = timeFmt.format(d);
    var key = d.getFullYear() + "-" + d.getMonth() + "-" + d.getDate();
    if (key !== lastDay) {
      lastDay = key;
      var h = document.createElement("h2");
      h.className = "day";
      h.textContent = dayFmt.format(d);
      feed.insertBefore(h, s);
    }
  });

  // Filters
  var state = { cat: "", region: "" };
  var chips = Array.prototype.slice.call(document.querySelectorAll(".chip"));
  var region = document.getElementById("region");
  var none = document.getElementById("none");

  function apply() {
    var shown = 0;
    var pendingHeading = null, headingHasRow = false;
    Array.prototype.slice.call(feed.children).forEach(function (el) {
      if (el.classList.contains("day")) {
        if (pendingHeading) pendingHeading.hidden = !headingHasRow;
        pendingHeading = el; headingHasRow = false;
        return;
      }
      var ok = (!state.cat || el.getAttribute("data-cat") === state.cat) &&
               (!state.region || el.getAttribute("data-region") === state.region);
      el.hidden = !ok;
      if (ok) { shown++; headingHasRow = true; }
    });
    if (pendingHeading) pendingHeading.hidden = !headingHasRow;
    if (none) none.hidden = shown !== 0;
  }

  chips.forEach(function (c) {
    c.addEventListener("click", function () {
      state.cat = c.getAttribute("data-cat");
      chips.forEach(function (o) { o.setAttribute("aria-pressed", o === c ? "true" : "false"); });
      apply();
    });
  });
  if (region) region.addEventListener("change", function () { state.region = region.value; apply(); });
})();
