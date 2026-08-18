// ============================================
// MediFind Dark / Light Theme Toggle System
// ============================================
(function() {
    function applySavedTheme() {
        const savedTheme = localStorage.getItem('medifind-theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
        if (savedTheme === 'dark') {
            document.documentElement.setAttribute('data-theme', 'dark');
        } else {
            document.documentElement.removeAttribute('data-theme');
        }
    }

    function updateToggleUI(theme) {
        const icon = document.getElementById('theme-icon');
        const btn = document.getElementById('theme-toggle');
        if (!icon) return;

        if (theme === 'dark') {
            icon.className = 'fa-solid fa-sun text-warning fs-6';
            if (btn) {
                btn.setAttribute('title', 'Switch to Light Mode');
                btn.classList.remove('btn-outline-secondary');
                btn.classList.add('btn-outline-light');
            }
        } else {
            icon.className = 'fa-solid fa-moon text-dark fs-6';
            if (btn) {
                btn.setAttribute('title', 'Switch to Dark Mode');
                btn.classList.remove('btn-outline-light');
                btn.classList.add('btn-outline-secondary');
            }
        }
    }

    // Apply theme immediately on script load to prevent flashing
    applySavedTheme();

    document.addEventListener('DOMContentLoaded', () => {
        const toggleBtn = document.getElementById('theme-toggle');
        const activeTheme = localStorage.getItem('medifind-theme') || (document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light');
        updateToggleUI(activeTheme);

        if (toggleBtn) {
            toggleBtn.addEventListener('click', (e) => {
                e.preventDefault();
                const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
                const newTheme = isDark ? 'light' : 'dark';

                if (newTheme === 'dark') {
                    document.documentElement.setAttribute('data-theme', 'dark');
                } else {
                    document.documentElement.removeAttribute('data-theme');
                }

                localStorage.setItem('medifind-theme', newTheme);
                updateToggleUI(newTheme);
            });
        }
    });
})();
