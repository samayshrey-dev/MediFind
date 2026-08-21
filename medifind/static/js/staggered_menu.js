/**
 * StaggeredMenu — Animated Overlay Drawer Component
 * Staggered entrance link animations, numbered items, and social links.
 */
class StaggeredMenuController {
  constructor(options = {}) {
    this.position = options.position || 'right';
    this.displaySocials = options.displaySocials !== false;
    this.displayItemNumbering = options.displayItemNumbering !== false;
    this.accentColor = options.accentColor || '#10b981';
    this.onMenuOpen = options.onMenuOpen || (() => {});
    this.onMenuClose = options.onMenuClose || (() => {});

    this.backdrop = document.getElementById('staggeredMenuBackdrop');
    this.panel = document.getElementById('staggeredMenuPanel');
    this.openTriggers = document.querySelectorAll('.staggered-menu-trigger');
    this.closeBtn = document.getElementById('staggeredMenuClose');

    this.isOpen = false;
    this.init();
  }

  init() {
    if (!this.panel) return;

    this.openTriggers.forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        this.open();
      });
    });

    if (this.closeBtn) {
      this.closeBtn.addEventListener('click', (e) => {
        e.preventDefault();
        this.close();
      });
    }

    if (this.backdrop) {
      this.backdrop.addEventListener('click', () => this.close());
    }

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && this.isOpen) {
        this.close();
      }
    });
  }

  open() {
    if (!this.panel) return;
    this.isOpen = true;
    if (this.backdrop) this.backdrop.classList.add('open');
    this.panel.classList.add('open');
    document.body.style.overflow = 'hidden';
    this.onMenuOpen();
  }

  close() {
    if (!this.panel) return;
    this.isOpen = false;
    if (this.backdrop) this.backdrop.classList.remove('open');
    this.panel.classList.remove('open');
    document.body.style.overflow = '';
    this.onMenuClose();
  }
}

document.addEventListener('DOMContentLoaded', () => {
  window.staggeredMenuInstance = new StaggeredMenuController({
    position: 'right',
    displaySocials: true,
    displayItemNumbering: true,
    accentColor: '#10b981'
  });
});
