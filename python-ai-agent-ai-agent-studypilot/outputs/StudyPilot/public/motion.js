"use strict";
// Local-only motion. No requests, copies in storage, or changes to learning data.
window.StudyMotion = (() => {
  const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  const animations = new Set();
  let leaving = null, frame = 0;
  const enabled = () => !reduced?.matches && typeof Element.prototype.animate === "function";
  function animate(node, frames, options, done = () => {}) {
    const animation = node.animate(frames, options);
    animations.add(animation);
    animation.finished.catch(() => {}).finally(() => {
      animations.delete(animation);
      animation.cancel();
      done();
    });
  }
  function reset() {
    animations.forEach(animation => animation.cancel());
    animations.clear();
    leaving?.remove();
    leaving = null;
  }
  function replace(container, next, transition) {
    let previous = container.querySelector(":scope > .page:not(.page-leaving)");
    const previousStyle = previous && getComputedStyle(previous);
    const opacity = previousStyle?.opacity || "1";
    const transform = previousStyle?.transform || "none";
    previous = transition && enabled() ? previous?.cloneNode(true) : null;
    reset();
    container.replaceChildren(next);
    if (!transition || !enabled()) return;
    if (previous) {
      previous.classList.add("page-leaving");
      previous.inert = true;
      previous.setAttribute("aria-hidden", "true");
      // Only the live page has IDs or named inputs. The inert snapshot cannot
      // capture drafts, submit forms, or alter detached forms awaiting a request.
      previous.querySelectorAll("[id],[name]").forEach(node => {
        node.removeAttribute("id"); node.removeAttribute("name");
      });
      previous.querySelectorAll('input[type="password"]').forEach(node => {node.value = "";});
      container.append(previous);
      leaving = previous;
      animate(previous, [{opacity, transform}, {opacity: 0, transform: "translate3d(0,-6px,0)"}],
        {duration: 180, easing: "cubic-bezier(.4,0,1,1)", fill: "both"}, () => {
          previous.remove();
          if (leaving === previous) leaving = null;
        });
    }
    animate(next, [{opacity: 0, transform: "translate3d(0,12px,0)"}, {opacity: 1, transform: "translate3d(0,0,0)"}],
      {duration: 380, delay: previous ? 70 : 0, easing: "cubic-bezier(.16,1,.3,1)", fill: "both"});
  }
  function positionCapsule() {
    frame = 0;
    const nav = document.querySelector("#navigation");
    const active = nav.querySelector('[aria-current="page"]');
    const capsule = nav.querySelector(".nav-capsule");
    if (nav.hidden || !active || !capsule) return;
    capsule.style.transform = `translate3d(${active.offsetLeft}px,${active.offsetTop}px,0)`;
    capsule.style.width = `${active.offsetWidth}px`;
    capsule.style.height = `${active.offsetHeight}px`;
    if (!capsule.dataset.ready) {
      // Initial placement must not slide across the entire navigation bar.
      capsule.getBoundingClientRect();
      capsule.dataset.ready = "true";
    }
  }
  function navigation() {
    if (!frame) frame = requestAnimationFrame(positionCapsule);
  }
  reduced?.addEventListener("change", () => {reset(); navigation();});
  window.addEventListener("resize", navigation, {passive: true});
  if (window.ResizeObserver) new ResizeObserver(navigation).observe(document.querySelector("#navigation"));
  document.fonts?.ready.then(navigation);
  return {replace, reset, navigation};
})();
