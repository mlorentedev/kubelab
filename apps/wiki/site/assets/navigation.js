/**
 * Enhanced Navigation and UX for mlorente.dev Wiki
 * Provides smooth navigation, keyboard shortcuts, and mobile optimizations
 */

(function() {
  'use strict';

  // Configuration
  const CONFIG = {
    scrollOffset: 80,
    animationDuration: 300,
    mobileBreakpoint: 768
  };

  // Utilities
  const isMobile = () => window.innerWidth <= CONFIG.mobileBreakpoint;
  const debounce = (func, wait) => {
    let timeout;
    return function executedFunction(...args) {
      const later = () => {
        clearTimeout(timeout);
        func(...args);
      };
      clearTimeout(timeout);
      timeout = setTimeout(later, wait);
    };
  };

  // Enhanced scroll behavior
  function enhanceScrolling() {
    // Add smooth scrolling for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
      anchor.addEventListener('click', function(e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
          const offsetTop = target.offsetTop - CONFIG.scrollOffset;
          window.scrollTo({
            top: offsetTop,
            behavior: 'smooth'
          });
        }
      });
    });
  }

  // Progressive enhancement for navigation
  function enhanceNavigation() {
    const nav = document.querySelector('.md-nav');
    if (!nav) return;

    // Add keyboard navigation
    nav.addEventListener('keydown', function(e) {
      const currentLink = document.activeElement;
      const allLinks = Array.from(nav.querySelectorAll('.md-nav__link'));
      const currentIndex = allLinks.indexOf(currentLink);

      switch(e.key) {
        case 'ArrowDown':
          e.preventDefault();
          const nextIndex = Math.min(currentIndex + 1, allLinks.length - 1);
          allLinks[nextIndex]?.focus();
          break;
        case 'ArrowUp':
          e.preventDefault();
          const prevIndex = Math.max(currentIndex - 1, 0);
          allLinks[prevIndex]?.focus();
          break;
        case 'Home':
          e.preventDefault();
          allLinks[0]?.focus();
          break;
        case 'End':
          e.preventDefault();
          allLinks[allLinks.length - 1]?.focus();
          break;
      }
    });

    // Add visual indicators for current section
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          // Update active navigation item based on current section
          const id = entry.target.id;
          if (id) {
            nav.querySelectorAll('.md-nav__link').forEach(link => {
              link.classList.remove('md-nav__link--active');
              if (link.getAttribute('href')?.includes(id)) {
                link.classList.add('md-nav__link--active');
              }
            });
          }
        }
      });
    }, {
      rootMargin: '-20% 0px -80% 0px'
    });

    // Observe all headings for active navigation updates
    document.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(heading => {
      if (heading.id) {
        observer.observe(heading);
      }
    });
  }

  // Mobile-specific enhancements
  function enhanceMobileExperience() {
    if (!isMobile()) return;

    // Add touch gestures for navigation
    let startX, startY;
    const nav = document.querySelector('.md-sidebar');

    if (nav) {
      nav.addEventListener('touchstart', (e) => {
        startX = e.touches[0].clientX;
        startY = e.touches[0].clientY;
      }, { passive: true });

      nav.addEventListener('touchmove', (e) => {
        if (!startX || !startY) return;

        const diffX = e.touches[0].clientX - startX;
        const diffY = e.touches[0].clientY - startY;

        // Horizontal swipe detected
        if (Math.abs(diffX) > Math.abs(diffY) && Math.abs(diffX) > 50) {
          if (diffX > 0) {
            // Swipe right - could expand navigation
            nav.classList.add('md-sidebar--expanded');
          } else {
            // Swipe left - could collapse navigation
            nav.classList.remove('md-sidebar--expanded');
          }
        }

        startX = null;
        startY = null;
      }, { passive: true });
    }

    // Optimize viewport for mobile
    const viewport = document.querySelector('meta[name="viewport"]');
    if (viewport) {
      viewport.setAttribute('content', 'width=device-width, initial-scale=1.0, maximum-scale=5.0, user-scalable=yes');
    }
  }

  // Reading progress indicator
  function addReadingProgress() {
    const content = document.querySelector('.md-content__inner');
    if (!content) return;

    // Create progress bar
    const progressBar = document.createElement('div');
    progressBar.style.cssText = `
      position: fixed;
      top: 0;
      left: 0;
      height: 3px;
      background: linear-gradient(90deg, var(--md-accent-fg-color), var(--md-primary-fg-color));
      z-index: 9999;
      transition: width 0.1s ease;
      width: 0%;
    `;
    document.body.appendChild(progressBar);

    // Update progress on scroll
    const updateProgress = debounce(() => {
      const scrollTop = window.pageYOffset;
      const docHeight = document.documentElement.scrollHeight - window.innerHeight;
      const scrollPercent = (scrollTop / docHeight) * 100;
      progressBar.style.width = Math.min(scrollPercent, 100) + '%';
    }, 10);

    window.addEventListener('scroll', updateProgress, { passive: true });
    updateProgress(); // Initial call
  }

  // Enhanced search functionality
  function enhanceSearch() {
    const searchInput = document.querySelector('.md-search__input');
    if (!searchInput) return;

    // Add keyboard shortcuts for search
    document.addEventListener('keydown', (e) => {
      // Ctrl/Cmd + K or / to focus search
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        searchInput.focus();
      } else if (e.key === '/' && !e.target.matches('input, textarea')) {
        e.preventDefault();
        searchInput.focus();
      }
    });

    // Add search hints
    const searchForm = searchInput.closest('.md-search__form');
    if (searchForm) {
      const hint = document.createElement('div');
      hint.style.cssText = `
        position: absolute;
        right: 10px;
        top: 50%;
        transform: translateY(-50%);
        font-size: 0.7rem;
        color: var(--md-default-fg-color--light);
        pointer-events: none;
        opacity: 0.7;
      `;
      hint.textContent = isMobile() ? '🔍' : 'Ctrl+K';
      searchForm.style.position = 'relative';
      searchForm.appendChild(hint);

      // Hide hint when typing
      searchInput.addEventListener('input', () => {
        hint.style.opacity = searchInput.value ? '0' : '0.7';
      });
    }
  }

  // Accessibility improvements
  function enhanceAccessibility() {
    // Add skip link
    const skipLink = document.createElement('a');
    skipLink.href = '#main';
    skipLink.textContent = 'Ir al contenido principal';
    skipLink.style.cssText = `
      position: absolute;
      top: -40px;
      left: 6px;
      background: var(--md-accent-fg-color);
      color: white;
      padding: 8px;
      border-radius: 4px;
      text-decoration: none;
      font-weight: 600;
      z-index: 10000;
      transition: top 0.2s ease;
    `;
    skipLink.addEventListener('focus', () => {
      skipLink.style.top = '6px';
    });
    skipLink.addEventListener('blur', () => {
      skipLink.style.top = '-40px';
    });
    document.body.insertBefore(skipLink, document.body.firstChild);

    // Mark main content
    const mainContent = document.querySelector('.md-content__inner');
    if (mainContent && !mainContent.id) {
      mainContent.id = 'main';
    }

    // Improve focus indicators
    const style = document.createElement('style');
    style.textContent = `
      .md-nav__link:focus,
      .md-search__input:focus,
      .md-tabs__link:focus {
        outline: 2px solid var(--md-accent-fg-color);
        outline-offset: 2px;
        border-radius: 4px;
      }
    `;
    document.head.appendChild(style);
  }

  // Back to top button
  function addBackToTop() {
    const button = document.createElement('button');
    button.innerHTML = '↑';
    button.setAttribute('aria-label', 'Volver arriba');
    button.style.cssText = `
      position: fixed;
      bottom: 2rem;
      right: 2rem;
      width: 50px;
      height: 50px;
      background: var(--md-accent-fg-color);
      color: white;
      border: none;
      border-radius: 50%;
      cursor: pointer;
      font-size: 1.2rem;
      font-weight: bold;
      opacity: 0;
      transform: translateY(20px);
      transition: all 0.3s ease;
      box-shadow: 0 4px 8px rgba(0,0,0,0.2);
      z-index: 1000;
    `;

    button.addEventListener('click', () => {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });

    // Show/hide based on scroll
    const toggleButton = debounce(() => {
      if (window.pageYOffset > 300) {
        button.style.opacity = '1';
        button.style.transform = 'translateY(0)';
      } else {
        button.style.opacity = '0';
        button.style.transform = 'translateY(20px)';
      }
    }, 100);

    window.addEventListener('scroll', toggleButton, { passive: true });
    document.body.appendChild(button);
  }

  // Performance optimizations
  function optimizePerformance() {
    // Lazy load images
    if ('IntersectionObserver' in window) {
      const imageObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            const img = entry.target;
            if (img.dataset.src) {
              img.src = img.dataset.src;
              img.removeAttribute('data-src');
              imageObserver.unobserve(img);
            }
          }
        });
      });

      document.querySelectorAll('img[data-src]').forEach(img => {
        imageObserver.observe(img);
      });
    }

    // Preload critical resources
    const preloadLink = document.createElement('link');
    preloadLink.rel = 'preload';
    preloadLink.as = 'style';
    preloadLink.href = 'assets/minimal.css';
    document.head.appendChild(preloadLink);
  }

  // Initialize all enhancements when DOM is ready
  function init() {
    enhanceScrolling();
    enhanceNavigation();
    enhanceMobileExperience();
    addReadingProgress();
    enhanceSearch();
    enhanceAccessibility();
    addBackToTop();
    optimizePerformance();

    // Log initialization for debugging
    console.log('📚 Wiki navigation enhancements loaded');
  }

  // Wait for DOM to be ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Handle page transitions (for SPA-like behavior)
  window.addEventListener('popstate', () => {
    setTimeout(init, 100);
  });

})();