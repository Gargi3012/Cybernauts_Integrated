/**
 * Flowiz Custom Pink Pointer / Cursor Follower
 * 
 * Elegant, hardware-accelerated mouse follower dot designed for the Flowiz platform.
 * Features:
 *  - High-performance requestAnimationFrame loop with lerp easing
 *  - Pure GPU transform (translate3d) — 0 layout shifts, 0 repaints
 *  - Idle sleep mode: pauses animation loop when mouse is stationary (0% CPU idle)
 *  - Event delegation on document for dynamic SPA interactive element detection
 *  - Contextual scaling over buttons/links/cards, softened text mode over inputs
 *  - Touch/mobile bypass (pointer: coarse) & prefers-reduced-motion compliance
 *  - pointer-events: none — zero interference with clicks, selections, or inputs
 */

(function () {
  'use strict';

  // 1. Check for touch devices / coarse pointer — bypass completely
  const isTouchDevice = () => {
    return (
      'ontouchstart' in window ||
      navigator.maxTouchPoints > 0 ||
      window.matchMedia('(pointer: coarse)').matches ||
      !window.matchMedia('(hover: hover)').matches
    );
  };

  if (isTouchDevice()) {
    return;
  }

  // 2. Selectors for interactive and text elements
  const INTERACTIVE_SELECTOR = [
    'a',
    'button',
    'input[type="button"]',
    'input[type="submit"]',
    'input[type="reset"]',
    'input[type="checkbox"]',
    'input[type="radio"]',
    '[role="button"]',
    '[role="link"]',
    '[role="tab"]',
    '[role="menuitem"]',
    '.btn',
    '.sidebar-link',
    '.tab-item',
    '.clickable',
    '.card-clickable',
    '.pipeline-card',
    '.action-btn',
    '.table-action-btn',
    '.lead-table-row',
    '.overview-lead-item',
    'summary'
  ].join(',');

  const TEXT_SELECTOR = [
    'input[type="text"]',
    'input[type="search"]',
    'input[type="email"]',
    'input[type="password"]',
    'input[type="tel"]',
    'input[type="number"]',
    'input:not([type])',
    'textarea',
    '[contenteditable="true"]'
  ].join(',');

  // 3. State management
  let targetX = -100;
  let targetY = -100;
  let currentX = -100;
  let currentY = -100;
  let isVisible = false;
  let isRunning = false;
  let firstMove = true;
  let rafId = null;

  // Accessibility: prefers-reduced-motion
  const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  let easing = motionQuery.matches ? 1.0 : 0.20;

  if (motionQuery.addEventListener) {
    motionQuery.addEventListener('change', (e) => {
      easing = e.matches ? 1.0 : 0.20;
    });
  }

  // 4. Create and inject follower element once DOM is ready
  function initCursor() {
    // Prevent duplicate injection
    if (document.getElementById('flowizCursorFollower')) return;

    const follower = document.createElement('div');
    follower.id = 'flowizCursorFollower';
    follower.className = 'flowiz-cursor-follower';
    follower.setAttribute('aria-hidden', 'true');

    const dot = document.createElement('div');
    dot.className = 'flowiz-cursor-dot';
    follower.appendChild(dot);

    document.body.appendChild(follower);

    // Animation loop using lerp
    function render() {
      if (!isRunning) return;

      const dx = targetX - currentX;
      const dy = targetY - currentY;

      currentX += dx * easing;
      currentY += dy * easing;

      follower.style.transform = `translate3d(${currentX}px, ${currentY}px, 0)`;

      // Sleep optimization: when within threshold of target, snap and suspend loop
      if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) {
        currentX = targetX;
        currentY = targetY;
        follower.style.transform = `translate3d(${currentX}px, ${currentY}px, 0)`;
        isRunning = false;
        return;
      }

      rafId = requestAnimationFrame(render);
    }

    function wakeLoop() {
      if (!isRunning) {
        isRunning = true;
        rafId = requestAnimationFrame(render);
      }
    }

    // Window mouse movement
    window.addEventListener('mousemove', (e) => {
      targetX = e.clientX;
      targetY = e.clientY;

      if (firstMove) {
        currentX = targetX;
        currentY = targetY;
        follower.style.transform = `translate3d(${currentX}px, ${currentY}px, 0)`;
        firstMove = false;
      }

      if (!isVisible) {
        isVisible = true;
        follower.classList.add('is-visible');
      }

      wakeLoop();
    }, { passive: true });

    // Viewport enter / leave tracking
    document.addEventListener('mouseleave', () => {
      isVisible = false;
      follower.classList.remove('is-visible');
    }, { passive: true });

    document.addEventListener('mouseenter', (e) => {
      targetX = e.clientX;
      targetY = e.clientY;
      if (firstMove) {
        currentX = targetX;
        currentY = targetY;
        follower.style.transform = `translate3d(${currentX}px, ${currentY}px, 0)`;
        firstMove = false;
      }
      isVisible = true;
      follower.classList.add('is-visible');
      wakeLoop();
    }, { passive: true });

    window.addEventListener('blur', () => {
      isVisible = false;
      follower.classList.remove('is-visible');
    }, { passive: true });

    // Delegated interactive element detection
    document.addEventListener('mouseover', (e) => {
      const target = e.target;
      if (!target || !(target instanceof Element)) return;

      if (target.closest(TEXT_SELECTOR)) {
        follower.classList.add('is-text');
        follower.classList.remove('is-interactive');
      } else if (target.closest(INTERACTIVE_SELECTOR)) {
        follower.classList.add('is-interactive');
        follower.classList.remove('is-text');
      } else {
        const cursor = window.getComputedStyle(target).cursor;
        if (cursor === 'pointer') {
          follower.classList.add('is-interactive');
          follower.classList.remove('is-text');
        } else {
          follower.classList.remove('is-interactive', 'is-text');
        }
      }
    }, { passive: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCursor);
  } else {
    initCursor();
  }
})();
