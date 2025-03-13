const toggleButton = document.getElementById('menu-toggle');
const menu = document.getElementById('menu');
const menuLinks = document.querySelectorAll('#menu-link');

function resetMenuLinks() {
  menuLinks.forEach((link, index) => {
    link.classList.remove('animate-fadeIn');
    link.classList.add('-translate-y-5', 'opacity-0');
    link.style.transitionDelay = `${(index + 1) * 100}ms`;
  });
}

function animateMenuLinks(show) {
  menuLinks.forEach((link, index) => {
    if (show) {
      link.classList.add('animate-fadeIn');
      link.classList.remove('-translate-y-5', 'opacity-0');
    } else {
      link.classList.remove('animate-fadeIn');
      link.classList.add('-translate-y-5', 'opacity-0');
    }
  });
}

function closeMenu() {
  if (!menu) return;

  menu.classList.add('hidden');
  animateMenuLinks(false);

  if (toggleButton) {
    toggleButton.classList.remove('border-gray-800', 'bg-gray-300', 'text-gray-800');
    toggleButton.classList.add('border-gray-600', 'bg-gray-100', 'text-gray-800');
  }
}

function openMenu() {
  if (!menu) return;

  menu.classList.remove('hidden');
  animateMenuLinks(true);

  if (toggleButton) {
    toggleButton.classList.add('border-gray-800', 'bg-gray-300', 'text-gray-800');
    toggleButton.classList.remove('border-gray-600', 'bg-gray-100', 'text-gray-800');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  if (!toggleButton || !menu) return;

  // Initially reset and close menu
  resetMenuLinks();
  closeMenu();

  toggleButton.addEventListener('click', (e) => {
    e.stopPropagation();
    if (menu.classList.contains('hidden')) {
      openMenu();
    } else {
      closeMenu();
    }
  });

  // Close menu when clicking outside
  document.addEventListener('click', (e) => {
    if (!menu.contains(e.target) && !toggleButton.contains(e.target)) {
      closeMenu();
    }
  });

  // Close menu when a link is clicked
  menuLinks.forEach((link) => {
    link.addEventListener('click', closeMenu);
  });

  // Close menu on scroll, resize, orientation change
  window.addEventListener('scroll', closeMenu);
  window.addEventListener('resize', closeMenu);
  window.addEventListener('orientationchange', closeMenu);
});
