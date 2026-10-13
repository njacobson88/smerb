/**
 * SMERB App-Prompt Suppressor
 *
 * Reddit and X nag mobile-web users to switch to their native apps: sticky
 * "Open App" pills, "View in Reddit App" bottom bars, and (for some users)
 * a blocking "Get the app to keep using Reddit" sheet that also locks page
 * scrolling. Participants browse through this WebView, so those prompts are
 * dead ends for them. This script hides the prompts and, when a hidden sheet
 * had locked scrolling, restores it.
 *
 * Three layers, so a Reddit/X markup change degrades gracefully:
 *   1. Known selectors (IDs/tags observed in the study app or published).
 *   2. Structural rule: anything linking to an app-store / deep-link host
 *      (onelink.me, app.link, deep_link_value, store URLs) is a prompt. The
 *      link itself is hidden; if it sits inside a short bottom sheet / dialog
 *      that mentions the app, the whole sheet is hidden.
 *   3. Text rule: a fixed/sticky element with little text that reads like an
 *      app upsell ("Open in app", "Get the app", ...) is hidden.
 *
 * Every suppression is reported once to Flutter as an `app_prompt_suppressed`
 * event (selector + text) so staff can see how often it happens and audit
 * false positives. Safe to inject more than once (idempotent).
 */
(function () {
  'use strict';
  if (window.__SMERB_PROMPT_SUPPRESSOR__) return;
  window.__SMERB_PROMPT_SUPPRESSOR__ = true;

  var host = location.hostname;
  var platform = /reddit\.com$/.test(host) ? 'reddit'
               : /(twitter\.com|x\.com)$/.test(host) ? 'twitter' : null;
  if (!platform) return;

  // --- Layer 1: known selectors ---------------------------------------------
  var KNOWN = {
    reddit: [
      '#xpromo-bottom-sheet',                        // "View in Reddit App" bar (seen in-app 2026-10)
      'faceplate-bottom-sheet[id*="xpromo"]',
      '#sticky-community-header-open-app-cta',       // red "Open App" pill in the community header (logged in)
      '#xpromo-small-header, #open-app-header-cta',  // "Open App" in the global header (logged out, seen 2026-10)
      '[id*="open-app-cta"], [id*="open-app-header"], [id*="xpromo"]',
      '#app-upsell-blocking-bottom-sheet-seo',       // "Get the app to keep using Reddit" (blocking)
      '#app-upsell-blocking-bottom-sheet-direct',
      '[id*="app-upsell"]',
      'xpromo-nsfw-blocking-modal, xpromo-app-selector, xpromo-bottom-bar',
      // Reddit's current prompt system (found in its JS bundles, 2026-10):
      // a banner, and a modal that renders as a bottom sheet or full-screen
      // block; the NSFW gate is a separate container with a "view in app" slot.
      'configured-xpromo-banner, configured-xpromo-modal, xpromo-nsfw-blocking-container',
      '[class*="configured-xpromo"]',
      '[class*="XPromo"], [class*="xpromo"]',       // legacy mobile-web classes
      'shreddit-app-banner, shreddit-xpromo-banner',
    ],
    twitter: [
      // No X-specific ids verified yet (needs a logged-in session to inspect);
      // X is covered by the deep-link and text rules below. The logged-out
      // "Log in / Sign up" bar is deliberately NOT hidden: participants need it.
      'div[aria-label*="Open X in app" i], div[aria-label*="Open Twitter in app" i]',
    ],
  };

  // Deep links into the native app: always a prompt, wherever they appear.
  var APP_LINK = /onelink\.me|app\.link|deep_link_value|\bintent:\/\/|^reddit:\/\/|^twitter:\/\/|^market:\/\//i;
  // Store pages: a prompt only inside an upsell sheet (a post may legitimately link to one).
  var STORE_LINK = /play\.google\.com\/store\/apps|apps\.apple\.com|itunes\.apple\.com/i;
  var UPSELL_TEXT = /\b(open|get|view|continue|use|try|download|install|see)\b[^.]{0,40}\bapp\b|\bin the app\b|\bapp store\b|\bgoogle play\b|keep using reddit/i;
  var SHEET = 'faceplate-bottom-sheet, rpl-bottom-sheet, .rpl-bottom-sheet, rpl-modal-card, faceplate-modal, shreddit-interstitial, [role="dialog"], [data-testid="sheetDialog"]';
  // Classes Reddit puts on <body> to freeze the page behind a blocking sheet
  // (re-added dynamically, so they are stripped on every scan while we hold).
  var LOCK_CLASSES = ['rpl-scroll-lock', 'scroll-is-blocked'];
  var MAX_SHEET_TEXT = 320;   // app-upsell sheets are terse; real content isn't

  // --- Hiding ---------------------------------------------------------------
  var HIDE_ATTR = 'data-smerb-hidden';
  var style = document.createElement('style');
  style.id = 'smerb-prompt-suppressor';
  style.textContent =
    KNOWN[platform].join(',\n') + ', [' + HIDE_ATTR + '] { display: none !important; visibility: hidden !important; pointer-events: none !important; }\n' +
    // Applied only while a hidden sheet is holding the page's scroll lock.
    // Reddit freezes the page with body.scroll-is-blocked {touch-action:none;
    // overflow:hidden} and body.rpl-scroll-lock {overflow:hidden!important};
    // this out-specifies both.
    'html.smerb-unlock-scroll, html.smerb-unlock-scroll body { overflow-y: auto !important; position: static !important; touch-action: auto !important; overscroll-behavior: auto !important; }';
  (document.head || document.documentElement).appendChild(style);

  var reported = new Set();
  function describe(el) {
    var s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    var t = el.getAttribute('data-testid'); if (t) s += '[' + t + ']';
    return s;
  }
  function report(el, rule, text) {
    var key = rule + '|' + describe(el);
    if (reported.has(key)) return;
    reported.add(key);
    try {
      if (window.flutter_inappwebview && window.flutter_inappwebview.callHandler) {
        window.flutter_inappwebview.callHandler('SmerbChannel', JSON.stringify({
          type: 'app_prompt_suppressed', timestamp: Date.now(), url: location.href, platform: platform,
          data: { rule: rule, selector: describe(el), text: (text || '').slice(0, 120) },
        }));
      }
    } catch (e) { /* reporting is best-effort */ }
  }
  function hide(el, rule, text) {
    if (!el || el === document.body || el === document.documentElement) return;
    if (el.hasAttribute(HIDE_ATTR)) return;   // already handled (and reported) under its first matching rule
    {
      el.setAttribute(HIDE_ATTR, rule);
      // Reddit's sheets register with an overlay manager that locks scroll
      // while they are "open"; closing them properly keeps its state sane.
      try {
        var closer = el.querySelector('button[aria-label*="close" i], button[aria-label*="dismiss" i], [slot="close"], button[data-testid*="close" i]');
        if (closer) closer.click();
        if (el.hasAttribute('open')) el.removeAttribute('open');
        // Reddit's configured-xpromo components listen for this to tear
        // themselves down (and release the scroll lock) exactly as if the
        // participant had tapped their own dismiss control.
        if (/xpromo/i.test(el.localName + ' ' + el.className)) {
          el.dispatchEvent(new CustomEvent('dismiss-configured-xpromo', { bubbles: true, composed: true }));
        }
      } catch (e) { /* ignore */ }
    }
    report(el, rule, text);
  }
  function shortText(el) {
    // Text nodes joined by spaces (innerText is empty for display:none
    // elements and textContent runs words from adjacent elements together).
    var parts = [], w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT), n;
    while ((n = w.nextNode())) { var v = n.nodeValue.trim(); if (v) parts.push(v); if (parts.length > 60) break; }
    return parts.join(' ').replace(/\s+/g, ' ');
  }

  // --- Layer 2 & 3 ------------------------------------------------------------
  function isDeepLinkHref(h) { return !!h && APP_LINK.test(h); }

  function scanRoot(root) {
    // Known selectors: matched by CSS already; still mark+report so the
    // overlay manager is closed and the event is logged.
    var i, el;
    var known = root.querySelectorAll(KNOWN[platform].join(','));
    for (i = 0; i < known.length; i++) hide(known[i], 'known', shortText(known[i]));

    // Structural: deep links to the native app / store.
    var links = root.querySelectorAll('a[href], [data-href], button[formaction]');
    for (i = 0; i < links.length; i++) {
      el = links[i];
      var href = el.getAttribute('href') || el.getAttribute('data-href') || el.getAttribute('formaction') || '';
      var deep = isDeepLinkHref(href), store = STORE_LINK.test(href);
      if (!deep && !store) continue;
      var sheet = el.closest(SHEET);
      var text = sheet ? shortText(sheet) : '';
      if (sheet && text.length <= MAX_SHEET_TEXT && UPSELL_TEXT.test(text)) hide(sheet, 'deeplink-sheet', text);
      else if (deep) hide(el, 'deeplink', shortText(el));
    }

    // Text: small fixed/sticky upsell bars that use neither a known id nor a
    // deep link. Prompts are mounted near the top of the tree, so only the
    // first few levels are checked — getComputedStyle on every node of a
    // Reddit feed would be far too slow to run on each mutation.
    walkShallow(root, 0, function (el) {
      if (el.hasAttribute(HIDE_ATTR) || el.closest('[' + HIDE_ATTR + ']')) return;
      var cs = getComputedStyle(el);
      if (cs.position !== 'fixed' && cs.position !== 'sticky') return;
      var r = el.getBoundingClientRect();
      if (r.width < innerWidth * 0.5 || r.height < 36 || r.height > innerHeight * 0.6) return;
      var t = shortText(el);
      if (t.length === 0 || t.length > 160 || !UPSELL_TEXT.test(t)) return;
      // Never hide the site's own navigation/header, which can be sticky and
      // happens to contain words like "app" in menus; those are long anyway.
      if (el.closest('header, reddit-header-small, reddit-header-large, [role="banner"], [role="navigation"]')) return;
      hide(el, 'upsell-text', t);
    });
  }

  var MAX_DEPTH = 6;
  function walkShallow(root, depth, fn) {
    if (depth > MAX_DEPTH) return;
    var kids = root.children || [];
    for (var i = 0; i < kids.length; i++) {
      var el = kids[i];
      fn(el);
      if (el.shadowRoot) walkShallow(el.shadowRoot, depth + 1, fn);
      walkShallow(el, depth + 1, fn);
    }
  }

  var holding = false;
  function unlockScrollIfHeld() {
    if (!document.body) return;   // document-start run, before <body> exists
    // Only intervene when something we hid is still holding the lock.
    var hiddenSheet = document.querySelector('[' + HIDE_ATTR + ']');
    var body = document.body, bodyCs = getComputedStyle(body);
    var classLocked = LOCK_CLASSES.some(function (c) { return body.classList.contains(c); });
    var locked = classLocked || bodyCs.overflowY === 'hidden' || bodyCs.position === 'fixed';
    var visibleDialog = Array.prototype.some.call(document.querySelectorAll(SHEET), function (d) {
      if (d.hasAttribute(HIDE_ATTR)) return false;
      var r = d.getBoundingClientRect(), cs = getComputedStyle(d);
      return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth
        && cs.visibility !== 'hidden' && cs.display !== 'none' && cs.opacity !== '0';
    });
    holding = !!hiddenSheet && locked && !visibleDialog;
    document.documentElement.classList.toggle('smerb-unlock-scroll', holding);
    if (holding && classLocked) LOCK_CLASSES.forEach(function (c) { body.classList.remove(c); });
  }
  // While holding the page open behind a hidden blocking sheet, keep Reddit's
  // touchmove handlers (which preventDefault to freeze scrolling) from running.
  window.addEventListener('touchmove', function (e) {
    if (holding) e.stopImmediatePropagation();
  }, { capture: true, passive: true });

  var scheduled = false, lastScan = 0, lastScanMs = 0;
  function scan() {
    scheduled = false;
    lastScan = Date.now();
    var t0 = performance.now();
    try { scanRoot(document); } catch (e) { window.__smerbPromptError = String(e && e.stack || e); }
    try { unlockScrollIfHeld(); } catch (e) { window.__smerbPromptError = String(e && e.stack || e); }
    lastScanMs = performance.now() - t0;
  }
  function schedule() {
    if (scheduled) return;
    scheduled = true;
    setTimeout(scan, Math.max(50, 400 - (Date.now() - lastScan)));
  }
  // Debug hook (used by the emulator tests): force a scan and report its cost.
  window.__smerbPromptScan = function () { scan(); return { ms: Math.round(lastScanMs * 10) / 10, hidden: document.querySelectorAll('[' + HIDE_ATTR + ']').length }; };

  new MutationObserver(schedule).observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['open', 'class', 'style', 'href'] });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', schedule);
  schedule();
  // SPA navigations and late-arriving sheets.
  setInterval(schedule, 2000);
  window.addEventListener('popstate', schedule);
})();
