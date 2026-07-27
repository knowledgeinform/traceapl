(function () {
  function debounce(fn, delay) {
    let timer = null;
    return function (...args) {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => fn.apply(this, args), delay);
    };
  }

  const LOOKUPS = {
    employee: {
      endpoint: "/api/employees/search",
      searching: "Searching employee directory...",
      none: "No employee matches found. You can still type a name or email manually.",
      className: "employee-suggestions",
    },
    "work-program": {
      endpoint: "/api/work-programs/search",
      searching: "Searching work programs...",
      none: "No work program matches found. You can still type one manually.",
      className: "employee-suggestions",
    },
    location: {
      endpoint: "/api/locations/search",
      searching: "Searching storage locations...",
      none: "No location matches found. You can still type a location manually.",
      className: "employee-suggestions",
    },
  };

  function closeAll(except) {
    document.querySelectorAll(".employee-suggestions").forEach((el) => {
      if (el !== except) el.classList.remove("open");
    });
  }

  function getLookupType(input) {
    if (input.dataset.employeeAutocomplete !== undefined) return "employee";
    return input.dataset.denodoAutocomplete || input.dataset.lookupAutocomplete || "employee";
  }

  function attachAutocomplete(input) {
    if (!input || input.dataset.traceaplAutocompleteReady === "1") return;
    const lookupType = getLookupType(input);
    const config = LOOKUPS[lookupType];
    if (!config) return;

    input.dataset.traceaplAutocompleteReady = "1";
    input.setAttribute("autocomplete", "off");

    const wrapper = document.createElement("div");
    wrapper.className = "employee-autocomplete-wrap";
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);

    const suggestions = document.createElement("div");
    suggestions.className = config.className;
    suggestions.setAttribute("role", "listbox");
    wrapper.appendChild(suggestions);

    function setStatus(message) {
      suggestions.innerHTML = "";
      const item = document.createElement("div");
      item.className = "employee-suggestion muted";
      item.textContent = message;
      suggestions.appendChild(item);
      suggestions.classList.add("open");
    }

    function chooseItem(item) {
      input.value = item.value || item.label || item.display_name || "";
      input.dataset.lookupValue = input.value;
      input.dataset.lookupType = lookupType;
      if (lookupType === "employee") {
        input.dataset.employeeId = item.employee_id || "";
        input.dataset.employeeEmail = item.email || "";
        input.dataset.employeeName = item.display_name || "";
      }
      suggestions.classList.remove("open");
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    async function search() {
      const query = input.value.trim();
      if (query.length < 2) {
        suggestions.classList.remove("open");
        suggestions.innerHTML = "";
        return;
      }

      setStatus(config.searching);
      try {
        const response = await fetch(`${config.endpoint}?q=${encodeURIComponent(query)}`, {
          headers: { "Accept": "application/json" },
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const items = await response.json();
        suggestions.innerHTML = "";
        if (!Array.isArray(items) || !items.length) {
          setStatus(config.none);
          return;
        }

        items.forEach((item) => {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "employee-suggestion";
          button.setAttribute("role", "option");
          const title = item.display_name || item.label || item.value || "Unnamed result";
          const secondary = item.email || item.secondary || item.team || "";
          const tertiary = item.team && item.email ? item.team : "";
          button.innerHTML = `
            <strong>${title}</strong>
            ${secondary ? `<span>${secondary}</span>` : ""}
            ${tertiary ? `<small>${tertiary}</small>` : ""}
          `;
          button.addEventListener("click", () => chooseItem(item));
          suggestions.appendChild(button);
        });
        suggestions.classList.add("open");
      } catch (error) {
        setStatus(`${lookupType.replace("-", " ")} lookup unavailable. You can still type a value manually.`);
      }
    }

    const debouncedSearch = debounce(search, 250);
    input.addEventListener("input", debouncedSearch);
    input.addEventListener("focus", function () {
      closeAll(suggestions);
      if (input.value.trim().length >= 2) debouncedSearch();
    });
    input.addEventListener("keydown", function (event) {
      if (event.key === "Escape") suggestions.classList.remove("open");
    });
  }

  function init() {
    document.querySelectorAll("[data-employee-autocomplete], [data-denodo-autocomplete], [data-lookup-autocomplete]").forEach(attachAutocomplete);
  }

  document.addEventListener("click", function (event) {
    if (!event.target.closest(".employee-autocomplete-wrap")) closeAll(null);
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // Characterization rows in the new-sample form are created dynamically. Expose
  // a small hook so future dynamic inputs can opt in without reloading the page.
  window.TraceAPLAttachAutocomplete = attachAutocomplete;
})();
