/**
 * SMERB Reddit Observer
 * Captures user interactions and content exposure on Reddit mobile web
 */

(function() {
  'use strict';

  // Prevent double injection
  if (window.__SMERB_REDDIT_INITIALIZED__) {
    console.log('[SMERB] Already initialized, skipping');
    return;
  }
  window.__SMERB_REDDIT_INITIALIZED__ = true;

  console.log('[SMERB] Initializing Reddit observer...');

  // ============================================================================
  // CONFIGURATION
  // ============================================================================

  const CONFIG = {
    VIEWPORT_THRESHOLD: 0.5,        // 50% visible = "seen"
    SCROLL_DEBOUNCE_MS: 500,        // Throttle scroll events (increased for performance)
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
  // REDDIT SELECTORS (Updated Dec 2024)
  // ============================================================================

  const SELECTORS = {
    // Posts in feed (old Reddit, new Reddit, mobile)
    post: 'div.thing[data-fullname^="t3_"], shreddit-post, [data-testid="post-container"], article[id^="t3_"], div.Post',

    // Comments - comprehensive selector list
    comment: [
      'div.thing[data-type="comment"]',  // Old Reddit
      'shreddit-comment',                 // New Reddit web component
      '[data-testid="comment"]',          // React testid
      'div.Comment',                      // Class-based
      '[thing-id^="t1_"]',               // Thing ID attribute
      '[thingid^="t1_"]',                // Alternative casing
      'comment',                          // Simple tag
      '[id^="t1_-comment"]',             // ID pattern
    ].join(', '),

    // Upvote/downvote buttons (old Reddit uses div.arrow)
    upvote: 'div.arrow.up, div.arrow.upmod, button[aria-label*="upvote" i], button[icon="upvote"], button[name="upvote"]',
    downvote: 'div.arrow.down, div.arrow.downmod, button[aria-label*="downvote" i], button[icon="downvote"], button[name="downvote"]',

    // Share, save, etc. (old Reddit uses <a> tags)
    share: 'a.share-button, button[aria-label*="share" i], a[aria-label*="share" i]',
    save: 'a.save-button, button[aria-label*="save" i], button[data-click-id="save"]',

    // Content elements (old Reddit uses simpler structure)
    postContent: 'div.expando, div.usertext-body, .md, [slot="text-body"], [data-testid="post-content"], div.RichTextJSON-root',
    postTitle: 'a.title, p.title > a, h1, [slot="title"], [data-testid="post-title"], h3',
    postAuthor: 'a.author, a[href*="/user/"], a[href*="/u/"], shreddit-author',
    postSubreddit: 'a.subreddit, a[href*="/r/"], [slot="subreddit"], a[data-click-id="subreddit"]',

    // Media
    image: 'img[src*="redd.it"], img[src*="reddit.com"]',
    video: 'video, shreddit-player',
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
        platform: 'reddit',
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

  function extractPostId(element) {
    // OLD REDDIT: Try data-fullname attribute (format: t3_abc123)
    const fullname = element.getAttribute('data-fullname');
    if (fullname && fullname.startsWith('t3_')) {
      return fullname;
    }

    // Try shreddit-post attribute
    if (element.tagName === 'SHREDDIT-POST') {
      return element.getAttribute('id') || element.getAttribute('post-id');
    }

    // Try article ID (format: t3_abc123)
    if (element.id && element.id.startsWith('t3_')) {
      return element.id;
    }

    // Try data attribute
    const postId = element.getAttribute('data-post-id') ||
                   element.getAttribute('post-id');
    if (postId) return postId;

    // Try to find in permalink
    const permalink = element.querySelector('a[href*="/comments/"]');
    if (permalink) {
      const match = permalink.href.match(/comments\/([a-z0-9]+)/);
      if (match) return 't3_' + match[1];
    }

    return null;
  }

  function extractPostData(element) {
    try {
      const data = {
        contentId: extractPostId(element),
        contentType: 'post',
      };

      // Title
      const titleEl = element.querySelector(SELECTORS.postTitle);
      if (titleEl) {
        data.title = titleEl.textContent.trim().substring(0, CONFIG.MAX_TEXT_LENGTH);
      }

      // Text content
      const contentEl = element.querySelector(SELECTORS.postContent);
      if (contentEl) {
        data.textContent = contentEl.textContent.trim().substring(0, CONFIG.MAX_TEXT_LENGTH);
      }

      // Author
      const authorEl = element.querySelector(SELECTORS.postAuthor);
      if (authorEl) {
        const authorMatch = authorEl.href?.match(/\/user\/([^\/]+)/);
        data.authorUsername = authorMatch ? authorMatch[1] : authorEl.textContent.trim();
      }

      // Subreddit
      const subredditEl = element.querySelector(SELECTORS.postSubreddit);
      if (subredditEl) {
        const subMatch = subredditEl.href?.match(/\/r\/([^\/]+)/);
        data.subreddit = subMatch ? subMatch[1] : subredditEl.textContent.trim();
      }

      // Score/upvotes
      const scoreEl = element.querySelector('[id*="vote-"], faceplate-number');
      if (scoreEl) {
        const scoreText = scoreEl.textContent.trim();
        data.upvotes = parseScore(scoreText);
      }

      // Comment count
      const commentsEl = element.querySelector('[aria-label*="comment" i]');
      if (commentsEl) {
        const commentText = commentsEl.textContent.trim();
        const match = commentText.match(/(\d+)/);
        if (match) data.comments = parseInt(match[1]);
      }

      // Media URLs - improved to capture more image types
      const images = Array.from(element.querySelectorAll(SELECTORS.image));
      if (images.length > 0) {
        data.mediaUrls = images
          .map(img => img.src)
          .filter(src => src && !src.includes('icon') && !src.includes('avatar') && !src.includes('thumbnail'));
      }

      // Video detection
      const video = element.querySelector(SELECTORS.video);
      if (video) {
        data.hasVideo = true;
        if (video.src) {
          data.videoUrl = video.src;
        }
      }

      return data;
    } catch (error) {
      console.error('[SMERB] Error extracting post data:', error);
      return null;
    }
  }

  function extractCommentId(element) {
    // Try shreddit-comment attributes (most common on new Reddit)
    if (element.tagName === 'SHREDDIT-COMMENT') {
      const thingId = element.getAttribute('thing-id') || element.getAttribute('thingid');
      if (thingId) return thingId;

      const commentId = element.getAttribute('comment-id') || element.getAttribute('id');
      if (commentId) {
        // Ensure it has t1_ prefix
        return commentId.startsWith('t1_') ? commentId : `t1_${commentId}`;
      }
    }

    // Try data-fullname attribute (format: t1_abc123) for old Reddit
    const fullname = element.getAttribute('data-fullname');
    if (fullname && fullname.startsWith('t1_')) {
      return fullname;
    }

    // Try thing-id or thingid attributes
    const thingId = element.getAttribute('thing-id') || element.getAttribute('thingid');
    if (thingId) return thingId;

    // Try data attribute
    const commentId = element.getAttribute('data-comment-id') || element.getAttribute('comment-id');
    if (commentId) {
      return commentId.startsWith('t1_') ? commentId : `t1_${commentId}`;
    }

    // Try ID attribute
    if (element.id && element.id.startsWith('t1_')) {
      return element.id;
    }

    // Last resort: generate from position + timestamp
    console.warn('[SMERB] No comment ID found, generating synthetic ID');
    return `t1_synthetic_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }

  function extractCommentData(element) {
    try {
      const data = {
        contentId: extractCommentId(element),
        contentType: 'comment',
      };

      // Comment text - try multiple selectors for different Reddit versions
      let textContent = '';

      // For shreddit-comment web components, text is in a slot
      const textSelectors = [
        'div[slot="comment"]',             // New Reddit slot container (most common)
        'div[slot="comment"] p',           // Paragraphs within slot
        'p',                                // Direct paragraph
        '.md',                              // Old Reddit markdown
        '.Comment__body',                   // Class-based
        'div[data-testid="comment"]',      // Test ID
        '[contenteditable]',                // Editable content
      ];

      for (const selector of textSelectors) {
        const textEl = element.querySelector(selector);
        if (textEl && textEl.textContent.trim().length > 0) {
          textContent = textEl.textContent.trim();
          break;
        }
      }

      // Aggressive fallback: use the entire element's text but clean it
      if (!textContent || textContent.length < 5) {
        // Clone element to avoid modifying the DOM
        const clone = element.cloneNode(true);

        // Remove unwanted elements (buttons, author info, vote counts, etc.)
        const removeSelectors = [
          'button',
          'shreddit-author',
          'faceplate-number',
          '[slot="credit-bar"]',
          '[aria-label*="upvote"]',
          '[aria-label*="downvote"]',
          '[aria-label*="share"]',
          'time',
        ];

        removeSelectors.forEach(sel => {
          clone.querySelectorAll(sel).forEach(el => el.remove());
        });

        const cleanedText = clone.textContent.trim();
        if (cleanedText && cleanedText.length > 0) {
          textContent = cleanedText;
        }
      }

      if (textContent) {
        data.textContent = textContent.substring(0, CONFIG.MAX_TEXT_LENGTH);
      }

      // Author - try shreddit-author first
      const authorEl = element.querySelector('shreddit-author, a[href*="/user/"], a[href*="/u/"], a.author');
      if (authorEl) {
        // For shreddit-author, the author attribute contains the username
        const authorAttr = authorEl.getAttribute('author');
        if (authorAttr) {
          data.authorUsername = authorAttr;
        } else if (authorEl.href) {
          const authorMatch = authorEl.href.match(/\/user\/([^\/]+)/);
          data.authorUsername = authorMatch ? authorMatch[1] : authorEl.textContent.trim();
        } else {
          data.authorUsername = authorEl.textContent.trim();
        }
      }

      // Score - try faceplate-number first (new Reddit)
      const scoreEl = element.querySelector('faceplate-number, [id*="vote-"], .score, [aria-label*="score"]');
      if (scoreEl) {
        const scoreText = scoreEl.textContent.trim() || scoreEl.getAttribute('number');
        data.upvotes = parseScore(scoreText);
      }

      // Parent post ID - look up the tree for the post container
      let current = element.parentElement;
      while (current) {
        if (current.matches && (current.matches('shreddit-post') || current.matches('[id^="t3_"]'))) {
          data.parentPostId = extractPostId(current);
          break;
        }
        current = current.parentElement;
      }

      return data;
    } catch (error) {
      console.error('[SMERB] Error extracting comment data:', error);
      return null;
    }
  }

  function parseScore(scoreText) {
    if (!scoreText) return null;

    const text = scoreText.toLowerCase().trim();

    // Handle "k" notation (e.g., "5.2k")
    if (text.includes('k')) {
      const num = parseFloat(text);
      return Math.round(num * 1000);
    }

    // Handle regular numbers
    const num = parseInt(text);
    return isNaN(num) ? null : num;
  }

  // ============================================================================
  // INTERSECTION OBSERVER - Tracks what's visible
  // ============================================================================

  const intersectionObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      // Determine if this is a post or comment
      const isComment = entry.target.matches(SELECTORS.comment);
      const contentId = isComment ? extractCommentId(entry.target) : extractPostId(entry.target);
      if (!contentId) return;

      if (entry.isIntersecting && entry.intersectionRatio >= CONFIG.VIEWPORT_THRESHOLD) {
        // Content entered viewport
        if (!state.exposedContent.has(contentId)) {
          state.exposedContent.set(contentId, {
            startTime: Date.now(),
            element: entry.target,
            wasExpanded: false,
            isComment: isComment,
          });

          // Send immediate event when content enters viewport
          const contentData = isComment ? extractCommentData(entry.target) : extractPostData(entry.target);
          if (contentData) {
            sendToFlutter('content_visible', {
              ...contentData,
              enteredViewportAt: Date.now(),
              scrollDepth: window.scrollY / document.body.scrollHeight,
              wasExpanded: false,
            });
          }

          log('Content entered viewport:', contentId, isComment ? '(comment)' : '(post)');
        }
      } else {
        // Content left viewport
        if (state.exposedContent.has(contentId)) {
          const exposureData = state.exposedContent.get(contentId);
          const duration = Date.now() - exposureData.startTime;

          // Only record if exposed long enough
          if (duration >= CONFIG.MIN_EXPOSURE_MS) {
            const contentData = exposureData.isComment
              ? extractCommentData(exposureData.element)
              : extractPostData(exposureData.element);

            if (contentData) {
              sendToFlutter('content_exposure', {
                ...contentData,
                exposureDurationMs: duration,
                scrollDepth: window.scrollY / document.body.scrollHeight,
                wasExpanded: exposureData.wasExpanded,
              });
            }
          }

          state.exposedContent.delete(contentId);
          log('Content left viewport:', contentId, 'duration:', duration);
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
    // Observe posts
    const posts = document.querySelectorAll(SELECTORS.post);
    posts.forEach(post => {
      if (!state.observedElements.has(post)) {
        intersectionObserver.observe(post);
        state.observedElements.add(post);
      }
    });

    // Observe comments
    const comments = document.querySelectorAll(SELECTORS.comment);

    // DIAGNOSTIC: Log first comment element structure
    if (comments.length > 0 && CONFIG.ENABLE_LOGGING) {
      const firstComment = comments[0];
      console.log('[SMERB DEBUG] First comment element:', {
        tagName: firstComment.tagName,
        id: firstComment.id,
        className: firstComment.className,
        attributes: Array.from(firstComment.attributes).map(a => `${a.name}="${a.value}"`),
        innerHTML: firstComment.innerHTML.substring(0, 200)
      });
    }

    comments.forEach(comment => {
      if (!state.observedElements.has(comment)) {
        intersectionObserver.observe(comment);
        state.observedElements.add(comment);
      }
    });

    // Always log comment count for debugging
    console.log('[SMERB] Observing', posts.length, 'posts and', comments.length, 'comments');

    // Send diagnostic info to Flutter
    if (comments.length > 0) {
      sendToFlutter('diagnostic', {
        postsFound: posts.length,
        commentsFound: comments.length,
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
  // SCROLL TRACKING
  // ============================================================================

  if (CONFIG.CAPTURE_SCROLL) {
    window.addEventListener('scroll', () => {
      clearTimeout(state.scrollTimeout);

      state.scrollTimeout = setTimeout(() => {
        const scrollY = window.scrollY;
        const direction = scrollY > state.lastScrollY ? 'down' : 'up';

        sendToFlutter('scroll', {
          scrollPosition: scrollY,
          viewportHeight: window.innerHeight,
          contentHeight: document.body.scrollHeight,
          scrollDirection: direction,
          scrollVelocity: Math.abs(scrollY - state.lastScrollY),
        });

        state.lastScrollY = scrollY;
      }, CONFIG.SCROLL_DEBOUNCE_MS);
    }, { passive: true });
  }

  // ============================================================================
  // CLICK TRACKING
  // ============================================================================

  function detectInteractionType(element) {
    const ariaLabel = element.getAttribute('aria-label')?.toLowerCase() || '';
    const icon = element.getAttribute('icon')?.toLowerCase() || '';

    // Reddit-specific button detection
    if (ariaLabel.includes('upvote') || icon === 'upvote') return 'upvote';
    if (ariaLabel.includes('downvote') || icon === 'downvote') return 'downvote';
    if (ariaLabel.includes('share')) return 'share';
    if (ariaLabel.includes('save')) return 'save';
    if (ariaLabel.includes('comment')) return 'comment';

    return null;
  }

  document.addEventListener('click', (event) => {
    // Check if this is a button interaction first
    const button = event.target.closest('button, a[role="button"]');
    if (button) {
      const interactionType = detectInteractionType(button);
      if (interactionType) {
        // Find the post this button belongs to
        const post = button.closest(SELECTORS.post);
        if (post) {
          const contentId = extractPostId(post);
          if (contentId) {
            sendToFlutter('interaction', {
              interactionType: interactionType,
              targetContentId: contentId,
              targetContentType: 'post',
              elementText: button.textContent?.trim().substring(0, 100),
            });

            log('Interaction:', interactionType, 'on', contentId);
          }
        }
        return; // Don't process as post click
      }
    }

    // Check if this is a post click
    const clickedPost = event.target.closest(SELECTORS.post);
    if (clickedPost) {
      const contentId = extractPostId(clickedPost);
      if (!contentId) return;

      // Check if user clicked on a link (title, image, thumbnail, etc.)
      const clickedLink = event.target.closest('a');

      // Detect different types of clicks
      const isTitle = event.target.closest(SELECTORS.postTitle);
      const isImage = event.target.closest('img') || event.target.tagName === 'IMG';
      const isExpando = event.target.closest('div.expando, button[aria-label*="Expand"]');

      // Check if the link leads to comments page
      const isPostLink = clickedLink && clickedLink.href && clickedLink.href.includes('/comments/');

      if (isTitle || isImage || isExpando || isPostLink) {
        // Mark post as expanded
        if (state.exposedContent.has(contentId)) {
          state.exposedContent.get(contentId).wasExpanded = true;
        }

        // Determine what was clicked
        let clickedOn = 'unknown';
        if (isTitle) clickedOn = 'title';
        else if (isImage) clickedOn = 'image';
        else if (isExpando) clickedOn = 'expando';
        else if (isPostLink) clickedOn = 'post_link';

        // Send post click event
        const postData = extractPostData(clickedPost);
        if (postData) {
          sendToFlutter('post_click', {
            ...postData,
            clickedOn: clickedOn,
            clickTarget: event.target.tagName,
            wasInViewport: state.exposedContent.has(contentId),
          });
        }

        log('Post clicked:', contentId, 'on', clickedOn);
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

    // If this is a post detail page, capture the full post content
    if (pageType === 'post') {
      capturePostDetail();
    }
  }

  function capturePostDetail() {
    // Find the main post element
    const mainPost = document.querySelector(SELECTORS.post);
    if (!mainPost) return;

    const postData = extractPostData(mainPost);
    if (!postData) return;

    // Enhanced image capture for post detail pages
    const allImages = Array.from(document.querySelectorAll('img[src*="redd.it"], img[src*="reddit.com"], img[src*="imgur"]'));
    const imageUrls = allImages
      .map(img => img.src)
      .filter(src => src && !src.includes('icon') && !src.includes('avatar') && !src.includes('thumbnail') && src.includes('http'));

    if (imageUrls.length > 0) {
      postData.mediaUrls = imageUrls;
    }

    // Send post detail event
    sendToFlutter('post_detail_view', {
      ...postData,
      viewedAt: Date.now(),
      commentCount: document.querySelectorAll(SELECTORS.comment).length,
    });

    log('Post detail captured:', postData.contentId, 'with', imageUrls.length, 'images');
  }

  function detectPageType() {
    const path = window.location.pathname;

    if (path === '/' || path.startsWith('/r/') && path.split('/').length <= 3) {
      return 'feed';
    }
    if (path.includes('/comments/')) {
      return 'post';
    }
    if (path.includes('/user/')) {
      return 'profile';
    }
    if (path.includes('/search')) {
      return 'search';
    }

    return 'other';
  }

  // ============================================================================
  // INITIALIZATION
  // ============================================================================

  function init() {
    log('Reddit observer initialized');

    // Track initial page view
    trackPageView();

    // Start observing existing content
    observeNewContent();

    // Notify Flutter that we're ready
    sendToFlutter('observer_ready', {
      platform: 'reddit',
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
