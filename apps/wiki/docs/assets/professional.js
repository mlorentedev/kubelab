/ Professional Wiki Enhancements /

document.addEventListener('DOMContentLoaded', function() {
    // Reading progress bar
    createProgressBar();

    // Back to top button
    createBackToTopButton();

    // Enhanced search functionality
    enhanceSearch();

    // Smooth anchor scrolling
    enhanceAnchorLinks();

    // Keyboard shortcuts
    addKeyboardShorts();

    // Enhanced copy functionality
    enhanceCopyButtons();

    // Page load performance monitoring
    monitorPerformance();
});

function createProgressBar() {
    const progressBar = document.createElement('div');
    progressBar.className = 'progress-bar';
    progressBar.id = 'reading-progress';
    document.body.appendChild(progressBar);

    function updateProgress() {
        const scrollTop = window.pageYOffset;
        const docHeight = document.body.scrollHeight - window.innerHeight;
        const scrollPercent = (scrollTop / docHeight)  ;

        progressBar.style.width = scrollPercent + '%';

        if (scrollTop > ) {
            progressBar.classList.add('visible');
        } else {
            progressBar.classList.remove('visible');
        }
    }

    window.addEventListener('scroll', updateProgress);
    updateProgress();
}

function createBackToTopButton() {
    const backToTop = document.createElement('button');
    backToTop.className = 'back-to-top';
    backToTop.innerHTML = '↑';
    backToTop.setAttribute('aria-label', 'Volver al inicio');
    backToTop.title = 'Volver al inicio';
    document.body.appendChild(backToTop);

    function toggleVisibility() {
        if (window.pageYOffset > ) {
            backToTop.classList.add('visible');
        } else {
            backToTop.classList.remove('visible');
        }
    }

    backToTop.addEventListener('click', function() {
        window.scrollTo({
            top: ,
            behavior: 'smooth'
        });
    });

    window.addEventListener('scroll', toggleVisibility);
    toggleVisibility();
}

function enhanceSearch() {
    const searchInput = document.querySelector('.md-search__input');
    if (!searchInput) return;

    // Add search shortcuts and enhancements
    searchInput.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            searchInput.blur();
        }
    });

    // Add search suggestions based on page content
    const suggestions = [
        'troubleshooting', 'deployment', 'architecture', 'docker',
        'ci/cd', 'contributing', 'versioning', 'how-to'
    ];

    searchInput.setAttribute('list', 'search-suggestions');
    const datalist = document.createElement('datalist');
    datalist.id = 'search-suggestions';

    suggestions.forEach(suggestion => {
        const option = document.createElement('option');
        option.value = suggestion;
        datalist.appendChild(option);
    });

    searchInput.parentNode.appendChild(datalist);
}

function enhanceAnchorLinks() {
    document.querySelectorAll('a[href^=""]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            e.preventDefault();
            const targetId = this.getAttribute('href').substring();
            const target = document.getElementById(targetId);

            if (target) {
                const offsetTop = target.offsetTop - ; // Account for fixed header
                window.scrollTo({
                    top: offsetTop,
                    behavior: 'smooth'
                });

                // Update URL without jumping
                history.replaceState(null, null, '' + targetId);

                // Brief highlight effect
                target.style.backgroundColor = 'rgba(, , , .)';
                setTimeout(() => {
                    target.style.backgroundColor = '';
                }, );
            }
        });
    });
}

function addKeyboardShorts() {
    document.addEventListener('keydown', function(e) {
        // Ctrl/Cmd + K for search
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            const searchInput = document.querySelector('.md-search__input');
            if (searchInput) {
                searchInput.focus();
            }
        }

        // Ctrl/Cmd + Home for back to top
        if ((e.ctrlKey || e.metaKey) && e.key === 'Home') {
            e.preventDefault();
            window.scrollTo({ top: , behavior: 'smooth' });
        }

        // ESC to close modals/overlays
        if (e.key === 'Escape') {
            const openDropdown = document.querySelector('.branch-switcher.open');
            if (openDropdown) {
                openDropdown.classList.remove('open');
            }
        }
    });
}

function enhanceCopyButtons() {
    // Enhanced feedback for copy operations
    document.addEventListener('click', function(e) {
        if (e.target.classList.contains('md-code__copy') ||
            e.target.closest('.md-code__copy')) {

            const button = e.target.classList.contains('md-code__copy') ?
                          e.target : e.target.closest('.md-code__copy');

            // Visual feedback
            const originalText = button.textContent;
            button.textContent = '✓';
            button.style.background = 'caf';

            setTimeout(() => {
                button.textContent = originalText;
                button.style.background = '';
            }, );
        }
    });
}

function monitorPerformance() {
    // Basic performance monitoring
    window.addEventListener('load', function() {
        const perfData = performance.getEntriesByType('navigation')[];
        const loadTime = perfData.loadEventEnd - perfData.loadEventStart;

        // Add performance badge for debugging (only in dev mode)
        if (window.location.hostname === 'localhost' ||
            window.location.hostname.includes('dev')) {

            const perfBadge = document.createElement('div');
            perfBadge.style.cssText = `
                position: fixed; bottom: px; left: px;
                background: rgba(,,,.); color: white;
                padding: px px; border-radius: px;
                font-size: px; z-index: ;
                font-family: monospace;
            `;
            perfBadge.textContent = `Load: ${Math.round(loadTime)}ms`;
            document.body.appendChild(perfBadge);

            setTimeout(() => perfBadge.remove(), );
        }
    });
}

// Additional professional features
function addTableOfContentsEnhancement() {
    const toc = document.querySelector('.md-nav--secondary');
    if (!toc) return;

    // Add collapse/expand functionality for long ToCs
    if (toc.children.length > ) {
        const collapseBtn = document.createElement('button');
        collapseBtn.textContent = 'Colapsar índice';
        collapseBtn.className = 'md-nav__button md-nav__button--collapse';
        collapseBtn.addEventListener('click', function() {
            toc.classList.toggle('collapsed');
            collapseBtn.textContent = toc.classList.contains('collapsed') ?
                                    'Expandir índice' : 'Colapsar índice';
        });

        toc.insertBefore(collapseBtn, toc.firstChild);
    }
}

// Initialize additional features after DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    setTimeout(addTableOfContentsEnhancement, );
});

// Export functions for potential external use
window.WikiProfessional = {
    createProgressBar,
    createBackToTopButton,
    enhanceSearch,
    enhanceAnchorLinks
};
