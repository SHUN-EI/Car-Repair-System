(function () {
  var details = Array.prototype.slice.call(document.querySelectorAll('details.gate'));
  var expandBtn = document.getElementById('expand-all');
  var collapseBtn = document.getElementById('collapse-all');

  function setAll(open) {
    details.forEach(function (d) { d.open = open; });
  }

  if (expandBtn) expandBtn.addEventListener('click', function () { setAll(true); });
  if (collapseBtn) collapseBtn.addEventListener('click', function () { setAll(false); });

  window.addEventListener('keydown', function (e) {
    if (e.key === 'e' && !e.ctrlKey && !e.metaKey && !e.altKey) {
      var tag = (document.activeElement && document.activeElement.tagName) || '';
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;
      setAll(true);
    }
  });
})();
