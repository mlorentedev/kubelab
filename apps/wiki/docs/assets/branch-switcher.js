(function () {
  var BRANCHES = (window.__BRANCHES__ || []);        
  var CURRENT  = (window.__CURRENT_BRANCH__ || "");  
  var STORAGE_KEY = "wiki_branch";

  function isBranchSegment(seg){ return BRANCHES.indexOf(seg) >= 0; }
  function currentPathParts(){
    return (location.pathname || "/").split("/").filter(Boolean);
  }
  function buildUrlFor(branch){
    var parts = currentPathParts();
    if (parts.length && isBranchSegment(parts[0])) parts[0] = branch;
    else parts.unshift(branch);
    var path = "/" + parts.join("/") + (location.search || "") + (location.hash || "");
    if (!/\/$/.test(path)) path += "/"; 
    return path;
  }
  function persist(branch){
    try { localStorage.setItem(STORAGE_KEY, branch); } catch(_) {}
  }
  function restore(){
    try { return localStorage.getItem(STORAGE_KEY) || ""; } catch(_) { return ""; }
  }

  try {
    var parts = currentPathParts();
    if (!parts.length || !isBranchSegment(parts[0])) {
      var preferred = restore() || CURRENT || (BRANCHES[0] || "");
      if (preferred) location.replace(buildUrlFor(preferred));
    }
  } catch(_) {}

  function mount(){
    var header = document.querySelector(".md-header__inner");
    if (!header) return requestAnimationFrame(mount);

    var wrap = document.createElement("div");
    wrap.className = "branch-switcher";

    var btn = document.createElement("button");
    btn.className = "bs-btn md-header__button";
    btn.type = "button";
    btn.setAttribute("aria-haspopup", "true");
    btn.setAttribute("aria-expanded", "false");
    btn.title = "Cambiar rama";

    btn.innerHTML = '' +
      '<svg class="md-icon" viewBox="0 0 24 24" aria-hidden="true">' +
      '  <path d="M6,2A2,2 0 0,1 8,4C8,4.74 7.6,5.39 7,5.73V9A5,5 0 0,0 12,14H14A2,2 0 0,1 16,16A2,2 0 0,1 14,18A2,2 0 0,1 12,16H10A7,7 0 0,1 3,9V5.73C2.4,5.39 2,4.74 2,4A2,2 0 0,1 4,2A2,2 0 0,1 6,4M20,2A2,2 0 0,1 22,4A2,2 0 0,1 20,6A2,2 0 0,1 18,4A2,2 0 0,1 20,2Z" />' +
      '</svg>' +
      '<span class="bs-label">' + (CURRENT || restore() || BRANCHES[0] || "") + '</span>' +
      '<svg class="md-icon bs-caret" viewBox="0 0 24 24" aria-hidden="true">' +
      '  <path d="M7,10L12,15L17,10H7Z" />' +
      '</svg>';

    var menu = document.createElement("div");
    menu.className = "bs-menu";
    menu.setAttribute("role","menu");
    BRANCHES.forEach(function (b) {
      var item = document.createElement("button");
      item.className = "bs-item";
      item.setAttribute("role","menuitem");
      item.type = "button";
      item.textContent = b;
      if (b === CURRENT) item.classList.add("is-current");
      item.addEventListener("click", function(){
        persist(b);
        location.assign(buildUrlFor(b));
      });
      menu.appendChild(item);
    });

    function open(){
      btn.setAttribute("aria-expanded","true");
      wrap.classList.add("open");
      var first = menu.querySelector(".bs-item");
      first && first.focus();
    }
    function close(){
      btn.setAttribute("aria-expanded","false");
      wrap.classList.remove("open");
      btn.focus();
    }
    btn.addEventListener("click", function(e){
      e.stopPropagation();
      wrap.classList.contains("open") ? close() : open();
    });
    document.addEventListener("click", function(){ wrap.classList.contains("open") && close(); });
    document.addEventListener("keydown", function(e){
      if (e.key === "Escape" && wrap.classList.contains("open")) { e.preventDefault(); close(); }
      if ((e.key === "v" || e.key === "V") && (e.ctrlKey || e.metaKey)) { e.preventDefault(); wrap.classList.contains("open")? close():open(); }
    });

    var right = header.querySelector(".md-header__options");
    (right || header).appendChild(wrap);
    wrap.appendChild(btn);
    wrap.appendChild(menu);
  }
  mount();

  if (!BRANCHES.length) console.warn("[branch-switcher] No hay ramas cargadas");
})();
