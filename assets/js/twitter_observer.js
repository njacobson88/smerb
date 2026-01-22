/**
 * SMERB Twitter/X Observer
 * Captures user interactions and content exposure on Twitter/X
 */

(function() {
  'use strict';

  // Prevent double injection
  if (window.__SMERB_TWITTER_INITIALIZED__) {
    console.log('[SMERB] Twitter observer already initialized, skipping');
    return;
  }
  window.__SMERB_TWITTER_INITIALIZED__ = true;

  console.log('[SMERB] Initializing Twitter observer...');

  // ============================================================================
  // CONFIGURATION
  // ============================================================================

  const CONFIG = {
    VIEWPORT_THRESHOLD: 0.5,        // 50% visible = "seen"
    SCROLL_DEBOUNCE_MS: 500,        // Throttle scroll events
    MIN_EXPOSURE_MS: 1000,          // Min time to count as exposure
    MAX_TEXT_LENGTH: 5000,          // Max text to capture
    ENABLE_LOGGING: false,          // Console logging (disabled for performance)
    CAPTURE_SCROLL: false,          // Disable scroll events for better performance
  };

  // ============================================================================
  // STATE
  // ============================================================================

  const state = {
    exposedContent: new Map(),      // Track what's currently visible
    lastScrollY: 0,                 // For scroll direction
    scrollTimeout: null,            // Debounce timer
    observedElements: new Set(),    // Already observed elements
  };

  // ============================================================================
  // TWITTER/X SELECTORS (Updated Dec 2025)
  // ============================================================================

  const SELECTORS = {
    // Tweets/Posts in feed
    tweet: 'article[data-testid="tweet"], div[data-testid="cellInnerDiv"] article',

    // Replies/Comments
    reply: 'div[data-testid="reply"]',

    // Interaction buttons
    like: 'div[data-testid="like"], button[data-testid="like"]',
    unlike: 'div[data-testid="unlike"], button[data-testid="unlike"]',
    retweet: 'div[data-testid="retweet"], button[data-testid="retweet"]',
    reply_button: 'div[data-testid="reply"], button[data-testid="reply"]',
    share: 'div[data-testid="shareMenu"], button[aria-label*="Share"]',
    bookmark: 'div[data-testid="bookmark"], button[data-testid="bookmark"]',

    // Content elements
    tweetText: 'div[data-testid="tweetText"], div[lang]',
    tweetAuthor: 'div[data-testid="User-Name"] a, a[role="link"][href^="/"]',
    tweetTime: 'time',
    media: 'div[data-testid="tweetPhoto"] img, div[data-testid="videoPlayer"] video',
    quotedTweet: 'div[data-testid="tweet"] div[role="link"]',
  };

  // ============================================================================
  // UTILITY FUNCTIONS
  // ============================================================================

  function log(...args) {
    if (CONFIG.ENABLE_LOGGING) {
      console.log('[SMERB]', ...args);
    }
  }

  function sendToFlutter(eventType, data) {
    try {
      const payload = {
        type: eventType,
        timestamp: Date.now(),
        url: window.location.href,
        platform: 'twitter',
        data: data
      };

      // Send to Flutter via JavaScript handler (flutter_inappwebview format)
      if (window.flutter_inappwebview && window.flutter_inappwebview.callHandler) {
        window.flutter_inappwebview.callHandler('SmerbChannel', JSON.stringify(payload));
        log('Sent event:', eventType, data);
      } else {
        console.warn('[SMERB] Flutter channel not available');
      }
    } catch (error) {
      console.error('[SMERB] Error sending to Flutter:', error);
    }
  }

  // ============================================================================
  // CONTENT EXTRACTION
  // ============================================================================

  function extractTweetId(element) {
    // Try to find tweet ID from link href
    const linkEl = element.querySelector('a[href*="/status/"]');
    if (linkEl) {
      const match = linkEl.href.match(/\/status\/(\d+)/);
      if (match) return `tweet_${match[1]}`;
    }

    // Try aria-labelledby
    const labelledBy = element.getAttribute('aria-labelledby');
    if (labelledBy) return `tweet_${labelledBy}`;

    // Fallback to synthetic ID
    return `tweet_synthetic_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }

  function extractTweetData(element) {
    try {
      const data = {
        contentId: extractTweetId(element),
        contentType: 'tweet',
      };

      // Tweet text
      const textEl = element.querySelector(SELECTORS.tweetText);
      if (textEl) {
        data.textContent = textEl.textContent.trim().substring(0, CONFIG.MAX_TEXT_LENGTH);
      }

      // Author
      const authorEl = element.querySelector(SELECTORS.tweetAuthor);
      if (authorEl) {
        const username = authorEl.getAttribute('href')?.replace('/', '');
        if (username) {
          data.authorUsername = username;
        }
      }

      // Time
      const timeEl = element.querySelector(SELECTORS.tweetTime);
      if (timeEl) {
        data.tweetTime = timeEl.getAttribute('datetime') || timeEl.textContent;
      }

      // Media
      const mediaElements = Array.from(element.querySelectorAll(SELECTORS.media));
      if (mediaElements.length > 0) {
        data.mediaUrls = mediaElements
          .map(el => el.src || el.poster)
          .filter(src => src && src.startsWith('http'));
        data.hasMedia = true;
        data.mediaCount = data.mediaUrls.length;
      }

      // Check for quoted tweet
      const quotedTweet = element.querySelector(SELECTORS.quotedTweet);
      if (quotedTweet) {
        data.hasQuotedTweet = true;
      }

      // Extract engagement metrics if visible
      const likesEl = element.querySelector('[data-testid="like"] span');
      if (likesEl) {
        data.likes = parseMetric(likesEl.textContent);
      }

      const retweetsEl = element.querySelector('[data-testid="retweet"] span');
      if (retweetsEl) {
        data.retweets = parseMetric(retweetsEl.textContent);
      }

      const repliesEl = element.querySelector('[data-testid="reply"] span');
      if (repliesEl) {
        data.replies = parseMetric(repliesEl.textContent);
      }

      return data;
    } catch (error) {
      console.error('[SMERB] Error extracting tweet data:', error);
      return null;
    }
  }

  function parseMetric(text) {
    if (!text) return null;
    const cleanText = text.trim().toLowerCase();

    // Handle K, M notation
    if (cleanText.includes('k')) {
      return Math.round(parseFloat(cleanText) * 1000);
    }
    if (cleanText.includes('m')) {
      return Math.round(parseFloat(cleanText) * 1000000);
    }

    const num = parseInt(cleanText);
    return isNaN(num) ? null : num;
  }

  // ============================================================================
  // INTERSECTION OBSERVER - Tracks what's visible
  // ============================================================================

  const intersectionObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      const contentId = extractTweetId(entry.target);
      if (!contentId) return;

      if (entry.isIntersecting && entry.intersectionRatio >= CONFIG.VIEWPORT_THRESHOLD) {
        // Content entered viewport
        if (!state.exposedContent.has(contentId)) {
          state.exposedContent.set(contentId, {
            startTime: Date.now(),
            element: entry.target,
            wasInteractedWith: false,
          });

          // Send immediate event when content enters viewport
          const tweetData = extractTweetData(entry.target);
          if (tweetData) {
            sendToFlutter('content_visible', {
              ...tweetData,
              enteredViewportAt: Date.now(),
              scrollDepth: window.scrollY / document.body.scrollHeight,
            });
          }

          log('Tweet entered viewport:', contentId);
        }
      } else {
        // Content left viewport
        if (state.exposedContent.has(contentId)) {
          const exposureData = state.exposedContent.get(contentId);
          const duration = Date.now() - exposureData.startTime;

          // Only record if exposed long enough
          if (duration >= CONFIG.MIN_EXPOSURE_MS) {
            const tweetData = extractTweetData(exposureData.element);

            if (tweetData) {
              sendToFlutter('content_exposure', {
                ...tweetData,
                exposureDurationMs: duration,
                scrollDepth: window.scrollY / document.body.scrollHeight,
                wasInteractedWith: exposureData.wasInteractedWith,
              });
            }
          }

          state.exposedContent.delete(contentId);
          log('Tweet left viewport:', contentId, 'duration:', duration);
        }
      }
    });
  }, {
    threshold: [0, CONFIG.VIEWPORT_THRESHOLD, 1.0]
  });

  // ============================================================================
  // MUTATION OBSERVER - Watches for new content
  // ============================================================================

  function observeNewContent() {
    // Observe tweets
    const tweets = document.querySelectorAll(SELECTORS.tweet);
    tweets.forEach(tweet => {
      if (!state.observedElements.has(tweet)) {
        intersectionObserver.observe(tweet);
        state.observedElements.add(tweet);
      }
    });

    console.log('[SMERB] Observing', tweets.length, 'tweets');

    // Send diagnostic info to Flutter
    if (tweets.length > 0) {
      sendToFlutter('diagnostic', {
        tweetsFound: tweets.length,
        pageType: detectPageType(),
        url: window.location.href,
      });
    }
  }

  const mutationObserver = new MutationObserver((mutations) => {
    let hasNewContent = false;

    mutations.forEach(mutation => {
      mutation.addedNodes.forEach(node => {
        if (node.nodeType === Node.ELEMENT_NODE) {
          hasNewContent = true;
        }
      });
    });

    if (hasNewContent) {
      observeNewContent();
    }
  });

  // Start observing DOM changes
  mutationObserver.observe(document.body, {
    childList: true,
    subtree: true
  });

  // ============================================================================
  // CLICK TRACKING
  // ============================================================================

  function detectInteractionType(element) {
    const testId = element.getAttribute('data-testid');
    const ariaLabel = element.getAttribute('aria-label')?.toLowerCase() || '';

    // Twitter-specific button detection
    if (testId === 'like' || testId === 'unlike' || ariaLabel.includes('like')) return 'like';
    if (testId === 'retweet' || ariaLabel.includes('repost')) return 'retweet';
    if (testId === 'reply' || ariaLabel.includes('reply')) return 'reply';
    if (testId === 'bookmark' || ariaLabel.includes('bookmark')) return 'bookmark';
    if (testId === 'shareMenu' || ariaLabel.includes('share')) return 'share';

    return null;
  }

  document.addEventListener('click', (event) => {
    // Check if this is a button interaction
    const button = event.target.closest('button, div[role="button"]');
    if (button) {
      const interactionType = detectInteractionType(button);
      if (interactionType) {
        // Find the tweet this button belongs to
        const tweet = button.closest(SELECTORS.tweet);
        if (tweet) {
          const contentId = extractTweetId(tweet);
          if (contentId) {
            // Mark as interacted
            if (state.exposedContent.has(contentId)) {
              state.exposedContent.get(contentId).wasInteractedWith = true;
            }

            sendToFlutter('interaction', {
              interactionType: interactionType,
              targetContentId: contentId,
              targetContentType: 'tweet',
            });

            log('Interaction:', interactionType, 'on', contentId);
          }
        }
        return;
      }
    }

    // Check if this is a tweet click (navigating to tweet detail)
    const clickedTweet = event.target.closest(SELECTORS.tweet);
    if (clickedTweet) {
      const contentId = extractTweetId(clickedTweet);
      if (!contentId) return;

      const clickedLink = event.target.closest('a');
      const isTweetLink = clickedLink && clickedLink.href && clickedLink.href.includes('/status/');

      if (isTweetLink) {
        // Mark as interacted
        if (state.exposedContent.has(contentId)) {
          state.exposedContent.get(contentId).wasInteractedWith = true;
        }

        const tweetData = extractTweetData(clickedTweet);
        if (tweetData) {
          sendToFlutter('tweet_click', {
            ...tweetData,
            clickedOn: 'tweet_link',
            wasInViewport: state.exposedContent.has(contentId),
          });
        }

        log('Tweet clicked:', contentId);
      }
    }
  }, { capture: true });

  // ============================================================================
  // PAGE VIEW TRACKING
  // ============================================================================

  function trackPageView() {
    const pageType = detectPageType();

    sendToFlutter('page_view', {
      pageType: pageType,
      pageTitle: document.title,
      referrerUrl: document.referrer || null,
      loadTimeMs: performance.now(),
    });

    log('Page view:', pageType, document.title);
  }

  function detectPageType() {
    const path = window.location.pathname;

    if (path === '/' || path === '/home') {
      return 'timeline';
    }
    if (path.includes('/status/')) {
      return 'tweet_detail';
    }
    if (path.match(/^\/[^\/]+$/)) {
      return 'profile';
    }
    if (path.includes('/search')) {
      return 'search';
    }
    if (path.includes('/notifications')) {
      return 'notifications';
    }
    if (path.includes('/messages')) {
      return 'messages';
    }

    return 'other';
  }

  // ============================================================================
  // INITIALIZATION
  // ============================================================================

  function init() {
    log('Twitter observer initialized');

    // Track initial page view
    trackPageView();

    // Start observing existing content
    observeNewContent();

    // Notify Flutter that we're ready
    sendToFlutter('observer_ready', {
      platform: 'twitter',
      url: window.location.href,
      timestamp: Date.now(),
    });
  }

  // Wait for DOM to be ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
