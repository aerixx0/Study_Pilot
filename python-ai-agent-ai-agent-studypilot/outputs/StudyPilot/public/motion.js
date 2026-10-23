"use strict";
// Local-only motion. No requests, copies in storage, or changes to learning data.
window.StudyMotion = (() => {
  const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  const animations = new Set();
  const workspaceAnimations = new Set();
  let workspaceActive = false, flight = null, workspaceRun = 0;
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
  function stopWorkspace() {
    workspaceRun++;
    workspaceAnimations.forEach(animation => animation.cancel());
    workspaceAnimations.clear();
    flight?.remove(); flight = null;
    delete document.body.dataset.workspaceMoving;
  }
  function workspace(active, animated = true) {
    if (workspaceActive === active) return;
    const nav = document.querySelector("#navigation");
    const buttons = [...nav.querySelectorAll("button")];
    // Read the current visual position before cancelling an interrupted flight.
    const before = buttons.map(button => button.getBoundingClientRect());
    const oldLabels = buttons.map(button => button.querySelector(".nav-label").getBoundingClientRect());
    const oldNav = (flight || nav).getBoundingClientRect();
    const oldBrand = document.querySelector(".brand").getBoundingClientRect();
    stopWorkspace();
    workspaceActive = active;
    document.body.dataset.workspace = active ? "conversation" : "";
    delete document.body.dataset.sidebarOpen;
    ["conversation-sidebar-tools", "conversation-topbar", "workspace-menu", "sidebar-backdrop"].forEach(id => {
      document.getElementById(id).hidden = !active;
    });
    document.querySelector("#workspace-menu").setAttribute("aria-expanded", "false");
    document.body.dataset.workspaceMoving = "true";
    positionCapsule();
    if (!animated || !enabled() || window.innerWidth <= 900 || nav.hidden) {
      delete document.body.dataset.workspaceMoving;
      return;
    }
    const run = workspaceRun;
    const options = {duration: 620, easing: "cubic-bezier(.16,1,.3,1)", fill: "both"};
    const play = (node, keyframes, extra = {}) => {
      const animation = node.animate(keyframes, {...options, ...extra});
      workspaceAnimations.add(animation);
      animation.finished.catch(() => {}).finally(() => {
        workspaceAnimations.delete(animation);
        animation.cancel();
        if (run === workspaceRun && !workspaceAnimations.size) {
          flight?.remove(); flight = null;
          delete document.body.dataset.workspaceMoving;
          navigation();
        }
      });
    };
    const target = nav.getBoundingClientRect();
    flight = document.createElement("div");
    flight.className = "navigation-flight";
    flight.setAttribute("aria-hidden", "true");
    Object.assign(flight.style, {left: `${target.left}px`, top: `${target.top}px`, width: `${target.width}px`, height: `${target.height}px`});
    document.body.append(flight);
    play(flight, [
      {transformOrigin: "top left", transform: `translate(${oldNav.left-target.left}px,${oldNav.top-target.top}px) scale(${oldNav.width/Math.max(1,target.width)},${oldNav.height/Math.max(1,target.height)})`, borderRadius: "21px"},
      {transformOrigin: "top left", transform: "translate(0,0) scale(1,1)", borderRadius: active ? "16px" : "21px"}
    ]);
    const targets = buttons.map(button => ({button:button.getBoundingClientRect(),label:button.querySelector(".nav-label").getBoundingClientRect()}));
    buttons.forEach((button, i) => {
      const after = targets[i].button, label = targets[i].label;
      play(button, [
        {transform: `translate(${before[i].left-after.left}px,${before[i].top-after.top}px)`},
        {transform: "translate(0,0)"}
      ]);
      play(button.querySelector(".nav-label"), [
        {transform:`translate(${oldLabels[i].left-before[i].left-label.left+after.left}px,${oldLabels[i].top-before[i].top-label.top+after.top}px)`},
        {transform:"translate(0,0)"}
      ]);
      if(active)play(button.querySelector(".nav-icon"),[{opacity:0},{opacity:1}],{duration:440,delay:100});
    });
    const brand = document.querySelector(".brand");
    const newBrand = brand.getBoundingClientRect();
    play(brand, [{transformOrigin:"top left", transform:`translate(${oldBrand.left-newBrand.left}px,${oldBrand.top-newBrand.top}px) scale(${oldBrand.width/Math.max(1,newBrand.width)})`}, {transformOrigin:"top left",transform:"translate(0,0) scale(1)"}]);
  }
  reduced?.addEventListener("change", () => {reset(); stopWorkspace(); navigation();});
  window.addEventListener("resize", () => {stopWorkspace(); navigation();}, {passive: true});
  if (window.ResizeObserver) new ResizeObserver(navigation).observe(document.querySelector("#navigation"));
  document.fonts?.ready.then(navigation);
  return {replace, reset, navigation, workspace};
})();
