// Browser-only appearance preference; no credentials or study data enter storage.
export default function ({ parentElement, data }) {
  installMotion();
  const root = document.documentElement;
  const storageKey = "studypilot.appearance.v1";
  const valid = mode => mode === "light" || mode === "dark";
  const buttons = [...parentElement.querySelectorAll("[data-mode]")];
  const date = parentElement.querySelector("[data-pilot-date]");
  if (date) date.textContent = data.date;

  function nativeTheme(mode) {
    // Streamlit's host theme protocol also updates canvas tables, charts and portals.
    // Only this local app's origins are accepted in .streamlit/config.toml.
    const dark = mode === "dark";
    window.postMessage({
      stCommVersion: 1,
      type: "SET_CUSTOM_THEME_CONFIG",
      themeName: "StudyPilot",
      themeInfo: {
        base: dark ? 1 : 0,
        primaryColor: dark ? "#f28a70" : "#b74731",
        backgroundColor: dark ? "#191c20" : "#f8f6f0",
        secondaryBackgroundColor: dark ? "#24282e" : "#f0ede5",
        textColor: dark ? "#f0ede5" : "#262520",
        borderColor: dark ? "#454b54" : "#ddd9cf",
        linkColor: dark ? "#f6a18a" : "#a9402d",
      },
    }, window.location.origin);
  }

  function apply(mode, persist = false) {
    if (!valid(mode)) return;
    const changed = root.dataset.pilotTheme !== mode;
    root.dataset.pilotTheme = mode;
    root.style.colorScheme = mode;
    buttons.forEach(button => button.setAttribute("aria-pressed", String(button.dataset.mode === mode)));
    if (persist) {
      try { localStorage.setItem(storageKey, mode); } catch { /* Private/restricted storage: keep current tab preference. */ }
    }
    if (changed) nativeTheme(mode);
  }

  let saved;
  try { saved = localStorage.getItem(storageKey); } catch { /* Storage may be disabled. */ }
  apply(valid(saved) ? saved : (valid(root.dataset.pilotTheme) ? root.dataset.pilotTheme : "light"));
  // On script reruns retain the DOM preference; do not reapply native theme or animate the whole page.
  const onClick = event => apply(event.currentTarget.dataset.mode, true);
  buttons.forEach(button => button.addEventListener("click", onClick));
  const onStorage = event => {
    if (event.key === storageKey && valid(event.newValue)) apply(event.newValue);
  };
  window.addEventListener("storage", onStorage);
  return () => {
    buttons.forEach(button => button.removeEventListener("click", onClick));
    window.removeEventListener("storage", onStorage);
  };
}

// One controller per document, including after Streamlit remounts the masthead.
// It observes only rendered UI; it never reads or writes account/form state.
function installMotion() {
  const version = "motion-6";
  if (window.__pilotMotion?.version === version) return;
  window.__pilotMotion?.dispose();
  const root = document.documentElement;
  const app = document.querySelector('[data-testid="stApp"]');
  if (!app) return;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  const pageSelector = '[class*="st-key-page-content-"]';
  let current = null, currentId = null, pending = null;
  let frame = 0, nav = null, capsule = null, navResize = null;
  let capsuleSelection = null;
  const animations = new Set();
  root.dataset.pilotMotion = version;

  function renderedPage() {
    const pages = [...app.querySelectorAll(pageSelector)];
    const page = pages.findLast(node => !node.closest('[data-stale="true"]'));
    if (page) return {node: page, id: `page-${page.className.match(/st-key-page-content-(\d+)/)?.[1]}`};
    const auth = app.querySelector('.st-key-auth-shell:has(.page-intro)');
    const choice = app.querySelector('.st-key-auth_mode input:checked');
    return auth ? {node: auth, id: `auth-${choice?.value ?? "receipt"}`} : null;
  }

  function adopt(view, animate = false) {
    document.querySelectorAll('.pilot-current-page').forEach(node => {
      if (node !== view.node) node.classList.remove('pilot-current-page');
    });
    current = view.node;
    currentId = view.id;
    current.classList.add('pilot-current-page');
    if (animate && !reduced.matches) {
      const animation = current.animate([
        {opacity: 0, transform: 'translate3d(0, 12px, 0)'},
        {opacity: 1, transform: 'translate3d(0, 0, 0)'},
      ], {duration: 380, easing: 'cubic-bezier(.16,1,.3,1)'});
      animations.add(animation);
      animation.finished.catch(() => {}).finally(() => {
        animations.delete(animation);
        if (!pending && !animations.size) delete root.dataset.pilotTransition;
      });
    }
  }

  function positionCapsule() {
    const group = document.querySelector('.st-key-top-navigation [role="radiogroup"]');
    if (!group) {
      navResize?.disconnect(); navResize = null; nav = null; capsule = null; capsuleSelection = null;
      return;
    }
    if (nav !== group) {
      navResize?.disconnect();
      nav = group;
      capsule = document.createElement('span');
      capsule.className = 'pilot-nav-capsule';
      capsule.setAttribute('aria-hidden', 'true');
      nav.appendChild(capsule);
      navResize = new ResizeObserver(positionCapsule);
      navResize.observe(nav);
    }
    const requested = pending?.id.startsWith('page-') ? pending.id.slice(5) : null;
    const selected = (requested !== null ? nav.querySelector(`input[value="${requested}"]`)?.closest('label') : null)
      ?? nav.querySelector('label:has(input:checked)');
    if (!selected) return;
    capsuleSelection = selected.querySelector('input')?.value;
    const box = selected.getBoundingClientRect(), parent = nav.getBoundingClientRect();
    const geometry = {width:`${box.width}px`, height:`${box.height}px`,
      transform:`translate3d(${box.left - parent.left}px, ${box.top - parent.top}px, 0)`};
    for (const [property, value] of Object.entries(geometry)) {
      if (capsule.style[property] !== value) capsule.style[property] = value;
    }
    if (!nav.classList.contains('pilot-nav-ready')) {
      nav.classList.add('pilot-nav-ready');
      requestAnimationFrame(() => { if (capsule) capsule.dataset.ready = 'true'; });
    }
  }

  function cancelPending() {
    if (!pending) return;
    clearTimeout(pending.timer);
    pending.snapshot?.remove();
    pending = null;
    delete root.dataset.pilotNavigation;
    if (!animations.size) delete root.dataset.pilotTransition;
  }

  function snapshotPage() {
    if (!current?.isConnected || reduced.matches) return null;
    const box = current.getBoundingClientRect();
    const copy = current.cloneNode(true);
    copy.classList.remove('pilot-current-page');
    copy.querySelectorAll('script,iframe,object').forEach(node => node.remove());
    copy.querySelectorAll('[id],[name]').forEach(node => { node.removeAttribute('id'); node.removeAttribute('name'); });
    copy.querySelectorAll('a,button,input,textarea,select,[tabindex]').forEach(node => node.setAttribute('tabindex', '-1'));
    copy.querySelectorAll('input[type="password"]').forEach(node => { node.value = ''; node.removeAttribute('value'); });
    // cloneNode does not copy canvas pixels. Preserve local chart/table appearance.
    const originalCanvases = current.querySelectorAll('canvas');
    copy.querySelectorAll('canvas').forEach((canvas, index) => {
      const original = originalCanvases[index];
      if (!original) return;
      const rect = original.getBoundingClientRect();
      if (rect.bottom <= 0 || rect.top >= window.innerHeight || rect.right <= 0 || rect.left >= window.innerWidth) return;
      try { canvas.getContext('2d')?.drawImage(original, 0, 0); } catch { /* A missing canvas never blocks navigation. */ }
    });
    Object.assign(copy.style, {position:'absolute', left:`${box.left}px`, top:`${box.top}px`,
      width:`${box.width}px`, height:`${box.height}px`, margin:'0', background:'var(--paper)', transform:'none'});
    const layer = document.createElement('div');
    layer.className = 'pilot-page-snapshot';
    layer.setAttribute('aria-hidden', 'true');
    layer.inert = true;
    layer.appendChild(copy);
    document.body.appendChild(layer);
    return layer;
  }

  function begin(id) {
    if (pending?.id === id) return;
    const previousPending = !!pending;
    const previousSnapshot = pending?.snapshot;
    if (pending) pending.snapshot = null;
    cancelPending();
    if (id === currentId && !previousPending) return;
    animations.forEach(animation => animation.cancel());
    const request = {id, timer: null, snapshot: previousSnapshot ?? snapshotPage(), finishing: false};
    pending = request;
    root.dataset.pilotLastNavigation = id;
    root.dataset.pilotNavigation = 'pending';
    positionCapsule();
    // A slow/failed backend must never leave a frozen overlay or locked controls.
    request.timer = setTimeout(() => {
      if (pending === request) { cancelPending(); queueScan(); }
    }, 1800);
    // A local inert snapshot keeps the header and navigation fully interactive.
    // Native view transitions can suppress input during their update callback.
    if (!reduced.matches) root.dataset.pilotTransition = 'active';
    queueScan();
  }

  function scan() {
    frame = 0;
    const selection = pending?.id.startsWith('page-') ? pending.id.slice(5) : nav?.querySelector('input:checked')?.value;
    if (!nav?.isConnected || selection !== capsuleSelection) positionCapsule();
    // This attribute belongs to the rendered Streamlit UI, not server/session state.
    if (app.getAttribute('data-test-script-state') !== 'notRunning') return;
    const view = renderedPage();
    if (!view) return;
    if (pending) {
      const request = pending;
      if (view.id !== request.id || request.finishing) return;
      request.finishing = true;
      // Let the finished layout settle before the browser captures its new view.
      requestAnimationFrame(() => requestAnimationFrame(() => {
        if (pending !== request) return;
        const latest = renderedPage();
        if (!latest || latest.id !== request.id || app.getAttribute('data-test-script-state') !== 'notRunning') {
          request.finishing = false; queueScan(); return;
        }
        adopt(latest, true);
        if (request.snapshot) {
          const snapshot = request.snapshot;
          request.snapshot = null;
          const exit = snapshot.animate([{opacity:1,transform:'translate3d(0,0,0)'},
            {opacity:0,transform:'translate3d(0,-6px,0)'}], {duration:180,easing:'cubic-bezier(.4,0,1,1)',fill:'forwards'});
          animations.add(exit);
          exit.finished.catch(() => {}).finally(() => {
            snapshot.remove(); animations.delete(exit);
            if (!pending && !animations.size) delete root.dataset.pilotTransition;
          });
        }
        clearTimeout(request.timer);
        pending = null;
        delete root.dataset.pilotNavigation;
      }));
    } else if (view.id !== currentId || !current?.isConnected) {
      adopt(view, view.id !== currentId);
    }
  }

  function queueScan() { if (!frame) frame = requestAnimationFrame(scan); }
  function onChange(event) {
    if (!(event.target instanceof HTMLInputElement) || event.target.type !== 'radio') return;
    if (event.target.closest('.st-key-top-navigation')) begin(`page-${event.target.value}`);
    else if (event.target.closest('.st-key-auth_mode')) begin(`auth-${event.target.value}`);
  }
  const shortcuts = {
    'hero_create': 2, 'hero_profile': 1, 'records_to_tasks': 2,
    'overview_to_tasks': 2, 'overview_to_goals': 1,
  };
  function onClick(event) {
    if (!(event.target instanceof Element)) return;
    // React Aria may update radios through a click without a native change event.
    const label = event.target.closest('.st-key-top-navigation label,.st-key-auth_mode label');
    const input = label?.querySelector('input[type="radio"]');
    if (input) {
      begin(`${label.closest('.st-key-top-navigation') ? 'page' : 'auth'}-${input.value}`);
      return;
    }
    if (!event.target.closest('button')) return;
    for (const [key, page] of Object.entries(shortcuts)) {
      if (event.target.closest(`.st-key-${key}`)) { begin(`page-${page}`); return; }
    }
  }
  function onKeydown(event) {
    if (!['ArrowRight','ArrowDown','ArrowLeft','ArrowUp','Home','End'].includes(event.key)) return;
    const group = event.target.closest?.('.st-key-top-navigation [role="radiogroup"],.st-key-auth_mode [role="radiogroup"]');
    if (!group) return;
    const options = [...group.querySelectorAll('input[type="radio"]')];
    const index = options.findIndex(input => input.checked);
    if (index < 0) return;
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1
      : (index + (['ArrowRight','ArrowDown'].includes(event.key) ? 1 : -1) + options.length) % options.length;
    begin(`${group.closest('.st-key-top-navigation') ? 'page' : 'auth'}-${options[next].value}`);
  }
  function onReducedMotion() {
    if (reduced.matches) {
      cancelPending();
      animations.forEach(animation => animation.cancel());
    }
  }
  // Input and chart DOM updates don't need a page scan or forced layout.
  // Scan at script completion, when navigation is pending, or after remounting.
  const observer = new MutationObserver(records => {
    if (pending || !current?.isConnected || (nav && !nav.isConnected)
        || records.some(record => record.target === app && record.attributeName === 'data-test-script-state')) queueScan();
  });
  observer.observe(app, {childList: true, subtree: true, attributes: true,
    attributeFilter: ['data-test-script-state', 'data-stale']});
  document.addEventListener('change', onChange, true);
  document.addEventListener('click', onClick, true);
  document.addEventListener('keydown', onKeydown, true);
  reduced.addEventListener('change', onReducedMotion);
  window.__pilotMotion = {version, dispose() {
    cancelPending();
    animations.forEach(animation => animation.cancel());
    observer.disconnect(); navResize?.disconnect();
    if (frame) cancelAnimationFrame(frame);
    capsule?.remove(); nav?.classList.remove('pilot-nav-ready');
    document.removeEventListener('change', onChange, true);
    document.removeEventListener('click', onClick, true);
    document.removeEventListener('keydown', onKeydown, true);
    reduced.removeEventListener('change', onReducedMotion);
    delete root.dataset.pilotMotion;
  }};
  queueScan();
}
