(function () {
    const key = 'mind-garden-theme';
    const root = document.documentElement;
    const toggle = document.getElementById('themeToggle');

    const applyTheme = (theme) => {
        root.setAttribute('data-bs-theme', theme);
        if (toggle) {
            toggle.textContent = theme === 'dark' ? 'Light mode' : 'Dark mode';
        }
        localStorage.setItem(key, theme);
    };

    const stored = localStorage.getItem(key) || 'light';
    applyTheme(stored);

    if (toggle) {
        toggle.addEventListener('click', () => {
            const current = root.getAttribute('data-bs-theme') || 'light';
            applyTheme(current === 'dark' ? 'light' : 'dark');
        });
    }
})();
