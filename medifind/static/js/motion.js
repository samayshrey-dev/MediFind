/**
 * MedFinder Motion & Interaction Engine
 * Lightweight, GPU-accelerated, natural physics transitions
 */

(function () {
  'use strict';

  const isReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // 1. Scroll Progress Bar
  function initScrollProgress() {
    const progressBar = document.getElementById('scrollProgressBar');
    if (!progressBar || isReducedMotion) return;

    let ticking = false;
    window.addEventListener('scroll', function () {
      if (!ticking) {
        window.requestAnimationFrame(function () {
          const winScroll = document.documentElement.scrollTop || document.body.scrollTop;
          const height = document.documentElement.scrollHeight - document.documentElement.clientHeight;
          const scrolled = height > 0 ? (winScroll / height) * 100 : 0;
          progressBar.style.width = scrolled + '%';
          ticking = false;
        });
        ticking = true;
      }
    }, { passive: true });
  }

  // 2. IntersectionObserver for Scroll-Reveal
  function initScrollReveal() {
    if (isReducedMotion) {
      document.querySelectorAll('.reveal, .reveal-scale, .reveal-stagger').forEach(el => {
        el.classList.add('revealed');
      });
      return;
    }

    if (!('IntersectionObserver' in window)) {
      document.querySelectorAll('.reveal, .reveal-scale, .reveal-stagger').forEach(el => {
        el.classList.add('revealed');
      });
      return;
    }

    const observer = new IntersectionObserver(function (entries, obs) {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('revealed');
          // Disconnect once revealed for maximum performance
          obs.unobserve(entry.target);
        }
      });
    }, {
      rootMargin: '0px 0px -40px 0px',
      threshold: 0.08
    });

    document.querySelectorAll('.reveal, .reveal-scale, .reveal-stagger').forEach(el => {
      observer.observe(el);
    });
  }

  // 3. Smooth Number Count-Up Animation
  function initNumberCounters() {
    const counters = document.querySelectorAll('.counter[data-target]');
    if (!counters.length) return;

    if (isReducedMotion || !('IntersectionObserver' in window)) {
      counters.forEach(counter => {
        const target = parseFloat(counter.getAttribute('data-target')) || 0;
        const prefix = counter.getAttribute('data-prefix') || '';
        const suffix = counter.getAttribute('data-suffix') || '';
        counter.innerText = prefix + target.toLocaleString() + suffix;
      });
      return;
    }

    const counterObserver = new IntersectionObserver(function (entries, obs) {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          const counter = entry.target;
          const target = parseFloat(counter.getAttribute('data-target')) || 0;
          const prefix = counter.getAttribute('data-prefix') || '';
          const suffix = counter.getAttribute('data-suffix') || '';
          const duration = 550; // ms
          const startTime = performance.now();

          function updateNumber(currentTime) {
            const elapsed = currentTime - startTime;
            const progress = Math.min(elapsed / duration, 1);
            // Ease out cubic
            const eased = 1 - Math.pow(1 - progress, 3);
            const currentVal = Math.floor(eased * target);

            counter.innerText = prefix + currentVal.toLocaleString() + suffix;

            if (progress < 1) {
              requestAnimationFrame(updateNumber);
            } else {
              counter.innerText = prefix + target.toLocaleString() + suffix;
            }
          }

          requestAnimationFrame(updateNumber);
          obs.unobserve(counter);
        }
      });
    }, { threshold: 0.2 });

    counters.forEach(c => counterObserver.observe(c));
  }

  // 4. Navbar Scroll Blur / Elevation
  function initNavbarScroll() {
    const navbar = document.querySelector('.navbar');
    if (!navbar) return;

    let ticking = false;
    window.addEventListener('scroll', function () {
      if (!ticking) {
        window.requestAnimationFrame(function () {
          if (window.scrollY > 20) {
            navbar.classList.add('scrolled');
          } else {
            navbar.classList.remove('scrolled');
          }
          ticking = false;
        });
        ticking = true;
      }
    }, { passive: true });
  }

  // 5. Initial Hero Stagger Entrance on Page Load
  function initHeroEntrance() {
    if (isReducedMotion) return;
    const heroElements = document.querySelectorAll('.hero-entrance');
    heroElements.forEach((el, index) => {
      setTimeout(() => {
        el.classList.add('revealed');
      }, index * 80 + 50);
    });
  }

  // Initialize on DOM Ready
  document.addEventListener('DOMContentLoaded', function () {
    initScrollProgress();
    initNavbarScroll();
    initScrollReveal();
    initNumberCounters();
    initHeroEntrance();
  });

  // Expose helper to dynamically trigger reveal on newly created DOM elements
  window.MedFinderMotion = {
    refreshReveals: function () {
      initScrollReveal();
      initNumberCounters();
    }
  };
})();
