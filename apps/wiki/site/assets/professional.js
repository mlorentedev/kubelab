/* Professional Wiki Enhancements */

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
        const scrollPercent = (scrollTop / docHeight) * 100;
        
        progressBar.style.width = scrollPercent + '%';
        
        if (scrollTop > 100) {
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
        if (window.pageYOffset > 300) {
            backToTop.classList.add('visible');
        } else {
            backToTop.classList.remove('visible');
        }
    }
    
    backToTop.addEventListener('click', function() {
        window.scrollTo({
            top: 0,
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
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            e.preventDefault();
            const targetId = this.getAttribute('href').substring(1);
            const target = document.getElementById(targetId);
            
            if (target) {
                const offsetTop = target.offsetTop - 100; // Account for fixed header
                window.scrollTo({
                    top: offsetTop,
                    behavior: 'smooth'
                });
                
                // Update URL without jumping
                history.replaceState(null, null, '#' + targetId);
                
                // Brief highlight effect
                target.style.backgroundColor = 'rgba(255, 111, 0, 0.1)';
                setTimeout(() => {
                    target.style.backgroundColor = '';
                }, 2000);
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
            window.scrollTo({ top: 0, behavior: 'smooth' });
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
            button.style.background = '#4caf50';
            
            setTimeout(() => {
                button.textContent = originalText;
                button.style.background = '';
            }, 2000);
        }
    });
}

function monitorPerformance() {
    // Basic performance monitoring
    window.addEventListener('load', function() {
        const perfData = performance.getEntriesByType('navigation')[0];
        const loadTime = perfData.loadEventEnd - perfData.loadEventStart;
        
        // Add performance badge for debugging (only in dev mode)
        if (window.location.hostname === 'localhost' || 
            window.location.hostname.includes('dev')) {
            
            const perfBadge = document.createElement('div');
            perfBadge.style.cssText = `
                position: fixed; bottom: 10px; left: 10px;
                background: rgba(0,0,0,0.8); color: white;
                padding: 5px 10px; border-radius: 4px;
                font-size: 12px; z-index: 9999;
                font-family: monospace;
            `;
            perfBadge.textContent = `Load: ${Math.round(loadTime)}ms`;
            document.body.appendChild(perfBadge);
            
            setTimeout(() => perfBadge.remove(), 5000);
        }
    });
}

// Additional professional features
function addTableOfContentsEnhancement() {
    const toc = document.querySelector('.md-nav--secondary');
    if (!toc) return;
    
    // Add collapse/expand functionality for long ToCs
    if (toc.children.length > 10) {
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
    setTimeout(addTableOfContentsEnhancement, 100);
});

// Export functions for potential external use
window.WikiProfessional = {
    createProgressBar,
    createBackToTopButton,
    enhanceSearch,
    enhanceAnchorLinks
};