(function () {
  'use strict';
  
  // Configuration
  const CONFIG = {
    BRANCHES: window.__BRANCHES__ || [],
    CURRENT: window.__CURRENT_BRANCH__ || "",
    STORAGE_KEY: "wiki_branch",
    ANIMATION_DURATION: 200,
    DEBOUNCE_DELAY: 100
  };

  // Utility functions
  const utils = {
    isBranchSegment: (seg) => CONFIG.BRANCHES.indexOf(seg) >= 0,
    
    currentPathParts: () => (location.pathname || "/").split("/").filter(Boolean),
    
    buildUrlFor: (branch) => {
      const parts = utils.currentPathParts();
      if (parts.length && utils.isBranchSegment(parts[0])) {
        parts[0] = branch;
      } else {
        parts.unshift(branch);
      }
      let path = "/" + parts.join("/") + (location.search || "") + (location.hash || "");
      if (!/\/$/.test(path)) path += "/";
      return path;
    },
    
    persist: (branch) => {
      try { 
        localStorage.setItem(CONFIG.STORAGE_KEY, branch); 
      } catch(e) { 
        console.warn('Failed to persist branch preference:', e);
      }
    },
    
    restore: () => {
      try { 
        return localStorage.getItem(CONFIG.STORAGE_KEY) || ""; 
      } catch(e) { 
        return ""; 
      }
    },
    
    debounce: (func, delay) => {
      let timeoutId;
      return (...args) => {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => func.apply(null, args), delay);
      };
    }
  };

  // Initialize branch routing
  function initializeRouting() {
    try {
      const parts = utils.currentPathParts();
      if (!parts.length || !utils.isBranchSegment(parts[0])) {
        const preferred = utils.restore() || CONFIG.CURRENT || CONFIG.BRANCHES[0];
        if (preferred && CONFIG.BRANCHES.includes(preferred)) {
          location.replace(utils.buildUrlFor(preferred));
        }
      }
    } catch(e) {
      console.warn('Branch routing initialization failed:', e);
    }
  }

  // Create branch switcher component
  function createBranchSwitcher() {
    // Main container
    const container = document.createElement("div");
    container.className = "branch-switcher";
    container.setAttribute("role", "group");
    container.setAttribute("aria-label", "Branch switcher");

    // Branch info display
    const branchInfo = createBranchInfo();
    
    // Dropdown button
    const button = createDropdownButton();
    
    // Dropdown menu
    const menu = createDropdownMenu();

    // Assemble component
    container.appendChild(branchInfo);
    container.appendChild(button);
    container.appendChild(menu);

    // Add event listeners
    setupEventListeners(container, button, menu);

    return container;
  }

  function createBranchInfo() {
    const branchInfo = document.createElement("div");
    branchInfo.className = "branch-info";
    
    const label = document.createElement("span");
    label.className = "branch-label";
    label.textContent = "rama:";
    
    const currentBranch = document.createElement("span");
    currentBranch.className = "current-branch";
    currentBranch.id = "current-branch-display";
    currentBranch.textContent = getCurrentBranch();
    currentBranch.title = `Current branch: ${getCurrentBranch()}`;
    
    branchInfo.appendChild(label);
    branchInfo.appendChild(currentBranch);
    
    return branchInfo;
  }

  function createDropdownButton() {
    const button = document.createElement("button");
    button.className = "bs-btn";
    button.type = "button";
    button.setAttribute("aria-haspopup", "true");
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-label", "Switch branch");
    button.title = "Switch branch (Ctrl+V)";
    
    return button;
  }

  function createDropdownMenu() {
    const menu = document.createElement("div");
    menu.className = "bs-menu";
    menu.setAttribute("role", "menu");
    menu.setAttribute("aria-label", "Available branches");

    CONFIG.BRANCHES.forEach((branch, index) => {
      const item = createMenuItem(branch, index);
      menu.appendChild(item);
    });

    return menu;
  }

  function createMenuItem(branch, index) {
    const item = document.createElement("button");
    item.className = "bs-menu-item";
    item.setAttribute("role", "menuitem");
    item.type = "button";
    item.textContent = branch;
    item.title = `Switch to ${branch} branch`;
    
    if (branch === CONFIG.CURRENT) {
      item.classList.add("current");
      item.setAttribute("aria-current", "true");
    }
    
    // Add keyboard shortcut hint for first few items
    if (index < 9) {
      item.setAttribute("data-shortcut", `${index + 1}`);
    }
    
    item.addEventListener("click", () => handleBranchSwitch(branch));
    
    return item;
  }

  function getCurrentBranch() {
    return CONFIG.CURRENT || utils.restore() || CONFIG.BRANCHES[0] || "";
  }

  function handleBranchSwitch(branch) {
    if (branch === getCurrentBranch()) return;
    
    // Add loading state
    const container = document.querySelector('.branch-switcher');
    container?.classList.add('loading');
    
    // Update display immediately for better UX
    const currentDisplay = document.getElementById("current-branch-display");
    if (currentDisplay) {
      currentDisplay.textContent = branch;
      currentDisplay.title = `Current branch: ${branch}`;
    }
    
    // Persist choice
    utils.persist(branch);
    
    // Navigate with slight delay to show loading state
    setTimeout(() => {
      location.assign(utils.buildUrlFor(branch));
    }, 150);
  }

  function setupEventListeners(container, button, menu) {
    let isOpen = false;
    
    const open = () => {
      if (isOpen) return;
      isOpen = true;
      button.setAttribute("aria-expanded", "true");
      container.classList.add("open");
      
      // Focus first menu item
      const firstItem = menu.querySelector(".bs-menu-item");
      if (firstItem) {
        setTimeout(() => firstItem.focus(), 50);
      }
      
      // Close on outside click
      setTimeout(() => {
        document.addEventListener("click", handleOutsideClick);
      }, 0);
    };
    
    const close = () => {
      if (!isOpen) return;
      isOpen = false;
      button.setAttribute("aria-expanded", "false");
      container.classList.remove("open");
      document.removeEventListener("click", handleOutsideClick);
      button.focus();
    };
    
    const handleOutsideClick = (e) => {
      if (!container.contains(e.target)) {
        close();
      }
    };
    
    // Button click handler
    button.addEventListener("click", (e) => {
      e.stopPropagation();
      isOpen ? close() : open();
    });
    
    // Keyboard navigation
    const handleKeyNavigation = utils.debounce((e) => {
      const focusedElement = document.activeElement;
      const menuItems = Array.from(menu.querySelectorAll(".bs-menu-item"));
      const currentIndex = menuItems.indexOf(focusedElement);
      
      switch(e.key) {
        case "Escape":
          e.preventDefault();
          if (isOpen) close();
          break;
          
        case "ArrowDown":
          if (isOpen) {
            e.preventDefault();
            const nextIndex = Math.min(currentIndex + 1, menuItems.length - 1);
            menuItems[nextIndex]?.focus();
          }
          break;
          
        case "ArrowUp":
          if (isOpen) {
            e.preventDefault();
            const prevIndex = Math.max(currentIndex - 1, 0);
            menuItems[prevIndex]?.focus();
          }
          break;
          
        case "Home":
          if (isOpen) {
            e.preventDefault();
            menuItems[0]?.focus();
          }
          break;
          
        case "End":
          if (isOpen) {
            e.preventDefault();
            menuItems[menuItems.length - 1]?.focus();
          }
          break;
          
        case "Enter":
        case " ":
          if (focusedElement && menuItems.includes(focusedElement)) {
            e.preventDefault();
            focusedElement.click();
          }
          break;
      }
      
      // Number key shortcuts (1-9)
      if (isOpen && /^[1-9]$/.test(e.key)) {
        e.preventDefault();
        const index = parseInt(e.key) - 1;
        if (menuItems[index]) {
          menuItems[index].click();
        }
      }
    }, CONFIG.DEBOUNCE_DELAY);
    
    document.addEventListener("keydown", handleKeyNavigation);
    
    // Global shortcut (Ctrl/Cmd + V)
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && (e.key === "v" || e.key === "V")) {
        e.preventDefault();
        isOpen ? close() : open();
      }
    });
    
    // Clean up on unmount
    container.addEventListener("cleanup", () => {
      document.removeEventListener("keydown", handleKeyNavigation);
      document.removeEventListener("click", handleOutsideClick);
    });
  }

  function mountComponent() {
    const header = document.querySelector(".md-header__inner");
    if (!header) {
      // Retry mounting if header not found
      setTimeout(mountComponent, 100);
      return;
    }

    // Remove existing instance
    const existing = header.querySelector(".branch-switcher");
    if (existing) {
      existing.dispatchEvent(new CustomEvent("cleanup"));
      existing.remove();
    }

    const switcher = createBranchSwitcher();
    
    // Mount in appropriate location
    const options = header.querySelector(".md-header__options");
    const target = options || header;
    target.appendChild(switcher);
  }

  function initialize() {
    // Validate configuration
    if (!CONFIG.BRANCHES.length) {
      console.warn("[branch-switcher] No branches configured");
      return;
    }

    // Initialize routing
    initializeRouting();
    
    // Mount component
    mountComponent();
    
    // Handle page navigation (SPA-like behavior)
    window.addEventListener("popstate", () => {
      setTimeout(initialize, 100);
    });

    console.log(`[branch-switcher] Initialized with ${CONFIG.BRANCHES.length} branches`);
  }

  // Auto-initialize when DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }

  // Expose API for external usage
  window.BranchSwitcher = {
    switch: handleBranchSwitch,
    current: getCurrentBranch,
    available: CONFIG.BRANCHES,
    remount: mountComponent
  };

})();