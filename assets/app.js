(function () {
  "use strict";
  var PAGE = 20;
  function fmt(o) { try { return new Intl.DateTimeFormat(undefined, o); } catch (e) { return null; } }
  var full = fmt({ day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
  var dayF = fmt({ weekday: "long", day: "numeric", month: "short", year: "numeric" });
  var tz = ""; try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch (e) {}

  function rel(d) {
    var m = Math.round((Date.now() - d.getTime()) / 60000);
    if (m < 1) return "just now";
    if (m < 60) return m + " min ago";
    if (m < 1440) return Math.round(m / 60) + " h ago";
    if (m < 43200) return Math.round(m / 1440) + " d ago";
    return "";
  }
  document.querySelectorAll("time.full, time.t").forEach(function (t) {
    var d = new Date(t.getAttribute("datetime"));
    if (isNaN(d) || !full) return;
    var r = t.classList.contains("t") && !t.closest(".upd") ? rel(d) : "";
    t.textContent = full.format(d);
    if (r) t.insertAdjacentHTML("afterend", ' <span class="rel">(' + r + ")</span>");
  });
  var today = document.getElementById("today");
  if (today && dayF) today.textContent = dayF.format(new Date()) + (tz ? " (" + tz + ")" : "");

  var feed = document.getElementById("feed");
  if (!feed) return;
  var loading = document.getElementById("loading"); if (loading) loading.hidden = true;
  var note = document.getElementById("tz");
  if (note && tz) note.textContent = "Times are shown in your time zone (" + tz + "). Each story keeps its original publication time.";

  var stories = Array.prototype.slice.call(feed.querySelectorAll(".story"));
  var st = { q: "", cat: "", region: "", days: 0, sort: "new", shown: PAGE };
  var q = document.getElementById("q"), region = document.getElementById("region"), when = document.getElementById("when"),
      sort = document.getElementById("sort"), more = document.getElementById("more"), none = document.getElementById("none"),
      count = document.getElementById("count"), chips = Array.prototype.slice.call(document.querySelectorAll("#chips .chip"));

  function ordered() {
    var list = stories.slice();
    if (st.sort === "pri") {
      list.sort(function (a, b) { return (b.dataset.pri - a.dataset.pri) || (b.dataset.ts || "").localeCompare(a.dataset.ts || ""); });
    } else {
      list.sort(function (a, b) { return (b.dataset.ts || "").localeCompare(a.dataset.ts || ""); });
    }
    return list;
  }
  function match(s) {
    if (st.cat && s.dataset.cat !== st.cat) return false;
    if (st.region && s.dataset.region !== st.region) return false;
    if (st.q) { var words = st.q.split(/\s+/); for (var i = 0; i < words.length; i++) if (s.dataset.text.indexOf(words[i]) < 0) return false; }
    if (st.days) {
      if (!s.dataset.ts) return false; // undated stories cannot be placed in a date range
      if (Date.now() - new Date(s.dataset.ts).getTime() > st.days * 86400000) return false;
    }
    return true;
  }
  function render() {
    var list = ordered(), hits = list.filter(match), n = 0;
    list.forEach(function (s) { feed.appendChild(s); s.hidden = true; });
    hits.forEach(function (s, i) { if (i < st.shown) { s.hidden = false; n++; } });
    if (none) none.hidden = hits.length !== 0;
    if (more) more.hidden = hits.length <= st.shown;
    if (count) count.textContent = hits.length ? "Showing " + n + " of " + hits.length + " stories" : "";
  }
  function reset() { st.shown = PAGE; render(); }
  var timer; if (q) q.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(function () { st.q = q.value.trim().toLowerCase(); reset(); }, 150); });
  chips.forEach(function (c) { c.addEventListener("click", function () {
    st.cat = c.getAttribute("data-cat"); chips.forEach(function (o) { o.setAttribute("aria-pressed", o === c ? "true" : "false"); }); reset(); }); });
  if (region) region.addEventListener("change", function () { st.region = region.value; reset(); });
  if (when) when.addEventListener("change", function () { st.days = parseInt(when.value || "0", 10); reset(); });
  if (sort) sort.addEventListener("change", function () { st.sort = sort.value; reset(); });
  if (more) more.addEventListener("click", function () { st.shown += PAGE; render(); });
  render();
})();
