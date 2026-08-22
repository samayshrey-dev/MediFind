/**
 * TextType — Typewriter Typing Effect Component (React Bits Vanilla JS Port)
 * Configured with User Specifications:
 * typingSpeed: 75, pauseDuration: 1500, deletingSpeed: 50, showCursor: true, cursorCharacter: "_", cursorBlinkDuration: 0.5s
 */
class TextType {
  constructor(elementId, cursorId, options = {}) {
    this.element = document.getElementById(elementId);
    this.cursor = document.getElementById(cursorId);
    if (!this.element) return;

    this.texts = options.texts || options.text || [
      "Find the medicine you need.",
      "Search verified nearby pharmacies.",
      "Compare real-time live inventory.",
      "Reserve and pick up with confidence."
    ];
    this.typingSpeed = options.typingSpeed || 75;
    this.pauseDuration = options.pauseDuration || 1500;
    this.deletingSpeed = options.deletingSpeed || 50;
    this.showCursor = options.showCursor !== false;
    this.cursorCharacter = options.cursorCharacter || "_";
    this.variableSpeedEnabled = options.variableSpeedEnabled || false;
    this.variableSpeedMin = options.variableSpeedMin || 60;
    this.variableSpeedMax = options.variableSpeedMax || 120;
    this.cursorBlinkDuration = options.cursorBlinkDuration || 0.5;

    this.currentTextIndex = 0;
    this.currentCharIndex = 0;
    this.isDeleting = false;

    if (this.cursor) {
      this.cursor.textContent = this.showCursor ? this.cursorCharacter : "";
      this.cursor.style.animationDuration = `${this.cursorBlinkDuration}s`;
    }

    this.tick();
  }

  getSpeed() {
    if (this.isDeleting) return this.deletingSpeed;
    if (this.variableSpeedEnabled) {
      return Math.floor(Math.random() * (this.variableSpeedMax - this.variableSpeedMin + 1)) + this.variableSpeedMin;
    }
    return this.typingSpeed;
  }

  tick() {
    if (!this.element) return;
    const currentFullText = this.texts[this.currentTextIndex];

    if (this.isDeleting) {
      this.currentCharIndex--;
      this.element.textContent = currentFullText.substring(0, this.currentCharIndex);
    } else {
      this.currentCharIndex++;
      this.element.textContent = currentFullText.substring(0, this.currentCharIndex);
    }

    let nextDelay = this.getSpeed();

    if (!this.isDeleting && this.currentCharIndex === currentFullText.length) {
      this.isDeleting = true;
      nextDelay = this.pauseDuration;
    } else if (this.isDeleting && this.currentCharIndex === 0) {
      this.isDeleting = false;
      this.currentTextIndex = (this.currentTextIndex + 1) % this.texts.length;
      nextDelay = 200;
    }

    setTimeout(() => this.tick(), nextDelay);
  }
}

function initMedFinderTextType() {
  // Consumer Landing Page Typewriter
  if (document.getElementById("textTypeContent")) {
    new TextType("textTypeContent", "textTypeCursor", {
      texts: [
        "Find the medicine you need.",
        "Search verified nearby pharmacies.",
        "Compare real-time live inventory.",
        "Reserve and pick up with confidence."
      ],
      typingSpeed: 75,
      pauseDuration: 1500,
      showCursor: true,
      cursorCharacter: "_",
      deletingSpeed: 50,
      variableSpeedEnabled: false,
      variableSpeedMin: 60,
      variableSpeedMax: 120,
      cursorBlinkDuration: 0.5
    });
  }

  // Pharmacy Landing Page Typewriter
  const pharmElem = document.getElementById("pharmacyDynamicHeadline") || document.getElementById("pharmacyTextTypeContent");
  if (pharmElem) {
    const pharmId = pharmElem.id;
    new TextType(pharmId, "pharmacyTextTypeCursor", {
      texts: [
        "Manage your pharmacy.",
        "Manage your inventory.",
        "Manage incoming orders.",
        "Manage store operations."
      ],
      typingSpeed: 75,
      pauseDuration: 1500,
      showCursor: true,
      cursorCharacter: "_",
      deletingSpeed: 50,
      variableSpeedEnabled: false,
      variableSpeedMin: 60,
      variableSpeedMax: 120,
      cursorBlinkDuration: 0.5
    });
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initMedFinderTextType);
} else {
  initMedFinderTextType();
}
