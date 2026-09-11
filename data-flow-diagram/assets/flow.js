(function () {
  var stage = document.getElementById("stage");
  var wrap = document.getElementById("stageWrap");
  var panel = document.getElementById("ovPanel");
  var toggle = document.getElementById("ovToggle");
  var DESIGN_W = 1140, DESIGN_H = 820;

  function fit() {
    var w = wrap.clientWidth - 4;
    var h = wrap.clientHeight - 4;
    var s = Math.min(w / DESIGN_W, h / DESIGN_H);
    stage.style.transform = "scale(" + s + ")";
  }

  toggle.addEventListener("click", function () {
    var opening = !panel.classList.contains("open");
    panel.classList.toggle("open", opening);
    var body = panel.querySelector(".ov-body");
    body.addEventListener("transitionend", function onEnd() {
      body.removeEventListener("transitionend", onEnd);
      fit();
    });
    setTimeout(fit, 320);
  });

  window.addEventListener("resize", fit);
  fit();
})();
