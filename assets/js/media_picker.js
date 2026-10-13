/**
 * SMERB Media Picker
 *
 * Resolves "what media did the participant just long-press?" for the app's
 * Save-media sheet. The native long-press hit test only knows about plain
 * <img> / <a><img> pairs and nothing inside shadow DOM, so instead the page
 * remembers the last touch point and, when asked, walks down through shadow
 * roots to the element under it and finds the nearest image or video.
 *
 * Returns null when nothing saveable is there (text, icons, avatars), or a
 * `{kind, url, supported}` object. `supported:false` means a video whose
 * stream isn't a downloadable file (HLS/blob) — the app explains that
 * instead of failing silently.
 */
(function () {
  'use strict';
  if (window.__SMERB_MEDIA_PICKER__) return;
  window.__SMERB_MEDIA_PICKER__ = true;

  var last = null;
  document.addEventListener('touchstart', function (e) {
    var t = e.touches && e.touches[0];
    if (t) last = { x: t.clientX, y: t.clientY };
  }, { capture: true, passive: true });
  document.addEventListener('pointerdown', function (e) {
    last = { x: e.clientX, y: e.clientY };
  }, { capture: true, passive: true });

  function deepElementFromPoint(x, y) {
    var el = document.elementFromPoint(x, y), prev = null;
    while (el && el.shadowRoot && el !== prev) {
      prev = el;
      var inner = el.shadowRoot.elementFromPoint(x, y);
      if (!inner || inner === el) break;
      el = inner;
    }
    return el;
  }

  // closest() that keeps climbing out of shadow roots.
  function closestAcrossShadow(el, sel) {
    while (el) {
      if (el.matches && el.matches(sel)) return el;
      el = el.parentElement || (el.parentNode && el.parentNode.host) || null;
    }
    return null;
  }

  // Reddit's player advertises progressive MP4 renditions (video+audio)
  // alongside the HLS stream it actually plays; pick the largest.
  function redditMp4(player) {
    try {
      var m = JSON.parse(player.getAttribute('packaged-media-json') || 'null');
      var list = (m && m.playbackMp4s && m.playbackMp4s.permutations) || [];
      var best = null;
      list.forEach(function (p) {
        var s = p && p.source;
        if (!s || !s.url) return;
        var w = (s.dimensions && s.dimensions.width) || 0;
        if (!best || w > best.w) best = { url: s.url, w: w };
      });
      return best && best.url;
    } catch (e) { return null; }
  }

  function isDirectMp4(u) { return /^https?:/.test(u) && /\.mp4(\?|$)/i.test(u); }

  // X serves a downsized variant by default; ask for the large one.
  function upgradeImageUrl(u) {
    try {
      var x = new URL(u);
      if (/(^|\.)pbs\.twimg\.com$/.test(x.hostname) && x.searchParams.has('name')) {
        x.searchParams.set('name', 'large');
        return x.toString();
      }
    } catch (e) { /* keep original */ }
    return u;
  }

  window.__smerbMediaAtLastTouch = function () {
    if (!last) return null;
    var el = deepElementFromPoint(last.x, last.y);
    if (!el) return null;

    var player = closestAcrossShadow(el, 'shreddit-player, shreddit-player-2');
    if (player) {
      var url = redditMp4(player);
      var src = player.getAttribute('src') || '';
      if (!url && isDirectMp4(src)) url = src;
      return { kind: 'video', url: url || null, poster: player.getAttribute('poster') || null, supported: !!url };
    }

    var video = closestAcrossShadow(el, 'video') || (el.querySelector && el.querySelector('video'));
    if (video) {
      var vs = video.currentSrc || video.src || '';
      var srcEl = video.querySelector('source[src]');
      if (!/^https?:/.test(vs) && srcEl) vs = srcEl.getAttribute('src') || '';
      var ok = isDirectMp4(vs);
      return { kind: 'video', url: ok ? vs : null, poster: video.poster || null, supported: ok };
    }

    var img = el.tagName === 'IMG' ? el : (closestAcrossShadow(el, 'img') || (el.querySelector && el.querySelector('img')));
    if (!img) {
      // CSS background images (some galleries / X media cards).
      var n = el;
      for (var i = 0; i < 4 && n; i++) {
        var bg = getComputedStyle(n).backgroundImage || '';
        var m = bg.match(/url\(["']?(https?:[^"')]+)/);
        if (m) return { kind: 'image', url: m[1], supported: true };
        n = n.parentElement;
      }
      return null;
    }
    var u = img.currentSrc || img.src || '';
    if (!/^https?:/.test(u)) return null;
    // Avatars, icons, emoji: not what anyone means by "save this image".
    if (img.naturalWidth && img.naturalWidth < 96 && img.naturalHeight < 96) return null;
    return { kind: 'image', url: upgradeImageUrl(u), supported: true, width: img.naturalWidth || 0, height: img.naturalHeight || 0 };
  };
})();
