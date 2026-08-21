// MedFinder Main Global Interactions
document.addEventListener("DOMContentLoaded", function () {
    // 1. Navbar Scroll elevation
    const nav = document.querySelector(".navbar");
    if (nav) {
        window.addEventListener("scroll", () => {
            if (window.scrollY > 40) {
                nav.classList.add("scrolled");
            } else {
                nav.classList.remove("scrolled");
            }
        });
    }

    // 2. Chip Search Tag Autofill
    document.querySelectorAll(".chips span, .search-tag-chip").forEach(chip => {
        chip.addEventListener("click", () => {
            const searchInput = document.querySelector(".search-box input, #medicineSearch, input[name='medicine']");
            if (searchInput) {
                const queryText = chip.getAttribute("data-query") || chip.innerText.trim();
                searchInput.value = queryText;
                const form = searchInput.closest("form");
                if (form) {
                    const submitBtn = form.querySelector("button[type='submit']");
                    if (submitBtn) submitBtn.focus();
                }
            }
        });
    });
});