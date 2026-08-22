/**
 * MediAI Scanner WebGL Component (React Bits Scanner Port)
 * Oscilloscope-style interference bands with vertical/horizontal sweep,
 * 3-color ramp, mouse interaction, scanlines, grain, and glow.
 * Compatible with WebGL2, WebGL1, and Canvas2D fallback.
 */
(function () {
  'use strict';

  function hexToRgb(hex) {
    hex = (hex || '#5227FF').replace(/^#/, '');
    if (hex.length === 3) {
      hex = hex.split('').map(c => c + c).join('');
    }
    const num = parseInt(hex, 16);
    return [
      ((num >> 16) & 255) / 255,
      ((num >> 8) & 255) / 255,
      (num & 255) / 255
    ];
  }

  // WebGL 2.0 Shaders
  const VERT_GL2 = `#version 300 es
in vec2 position;
void main() {
  gl_Position = vec4(position, 0.0, 1.0);
}
`;

  const FRAG_GL2 = `#version 300 es
precision highp float;

uniform float uTime;
uniform vec2 uResolution;
uniform vec2 uMouse;
uniform vec3 uColor1;
uniform vec3 uColor2;
uniform vec3 uColor3;
uniform float uSpeed;
uniform float uSweepSpeed;
uniform float uSweepWidth;
uniform float uSweepFalloff;
uniform float uScale;
uniform float uFrequency;
uniform float uRipple;
uniform float uBandDensity;
uniform float uLineSharpness;
uniform float uGlow;
uniform int uScanDirection;
uniform float uColorSpread;
uniform float uBrightness;
uniform float uContrast;
uniform float uSoftness;
uniform float uVignette;
uniform bool uScanline;
uniform bool uGrain;
uniform float uGrainIntensity;
uniform float uOpacity;
uniform bool uMouseInteraction;
uniform float uMouseRadius;
uniform float uMouseStrength;

out vec4 fragColor;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453123);
}

void main() {
  vec2 uv = gl_FragCoord.xy / uResolution.xy;
  vec2 aspect = vec2(uResolution.x / uResolution.y, 1.0);
  vec2 p = (uv - 0.5) * aspect * uScale;

  float t = uTime * uSpeed;
  float sweepT = uTime * uSweepSpeed;

  // Mouse distortion
  float mouseDist = length((uv - uMouse) * aspect);
  float mouseInfl = 0.0;
  if (uMouseInteraction) {
    mouseInfl = smoothstep(uMouseRadius, 0.0, mouseDist) * uMouseStrength;
  }

  // Direction coordinates (0 = vertical sweep, 1 = horizontal sweep)
  float coord = (uScanDirection == 0) ? uv.y : uv.x;
  float crossCoord = (uScanDirection == 0) ? p.x : p.y;

  // Continuous sweeping beam
  float sweepPos = mod(sweepT, 1.0);
  float dSweep = abs(coord - sweepPos);
  dSweep = min(dSweep, 1.0 - dSweep);
  float sweepBeam = exp(-pow(dSweep * uSweepFalloff / uSweepWidth, 2.0));

  // Multi-frequency wave & interference bands
  float wavePhase = coord * uBandDensity * 3.14159265 + t;
  float rippleOffset = sin(crossCoord * uFrequency + t * 0.7) * uRipple * 8.0;
  rippleOffset += mouseInfl * 3.0 * sin(mouseDist * 25.0 - t * 3.0);

  float wave = sin(wavePhase + rippleOffset);
  float band = pow(clamp(0.5 + 0.5 * wave, 0.0, 1.0), uLineSharpness);

  // Glow factor
  float glowFactor = (band * 0.7 + sweepBeam * 0.85 + mouseInfl * 0.6) * uGlow;

  // Softness blend
  float softBand = mix(band, 0.5 + 0.5 * wave, uSoftness * 0.25);

  // 3-Color Ramp Distribution
  float rampFactor = clamp(softBand * uColorSpread + sweepBeam * 0.55, 0.0, 1.0);
  vec3 baseColor = mix(uColor1, uColor2, rampFactor);
  vec3 finalColor = mix(baseColor, uColor3, clamp(pow(band, 2.0) * (sweepBeam + 0.4) + glowFactor, 0.0, 1.0));

  // Fine Scanline overlay
  if (uScanline) {
    float sl = sin(gl_FragCoord.y * 1.5) * 0.5 + 0.5;
    finalColor *= mix(1.0, 0.88 + 0.12 * sl, 0.65);
  }

  // Vignette
  float vig = length(uv - 0.5);
  finalColor *= (1.0 - smoothstep(0.25, 0.9, vig) * uVignette);

  // Film Grain
  if (uGrain) {
    float grainVal = (hash(uv * (uTime * 0.15 + 1.0)) - 0.5) * uGrainIntensity;
    finalColor += grainVal;
  }

  // Contrast & Brightness
  finalColor = ((finalColor - 0.5) * uContrast + 0.5) * uBrightness;
  finalColor = clamp(finalColor, 0.0, 1.0);

  float alpha = clamp((band * 0.75 + sweepBeam * 0.85 + glowFactor * 1.0 + mouseInfl * 0.5), 0.0, 1.0) * uOpacity;
  fragColor = vec4(finalColor, alpha);
}
`;

  // WebGL 1.0 (GLSL 1.00 ES) Shaders for 100% universal browser compatibility
  const VERT_GL1 = `
attribute vec2 position;
void main() {
  gl_Position = vec4(position, 0.0, 1.0);
}
`;

  const FRAG_GL1 = `
precision highp float;

uniform float uTime;
uniform vec2 uResolution;
uniform vec2 uMouse;
uniform vec3 uColor1;
uniform vec3 uColor2;
uniform vec3 uColor3;
uniform float uSpeed;
uniform float uSweepSpeed;
uniform float uSweepWidth;
uniform float uSweepFalloff;
uniform float uScale;
uniform float uFrequency;
uniform float uRipple;
uniform float uBandDensity;
uniform float uLineSharpness;
uniform float uGlow;
uniform int uScanDirection;
uniform float uColorSpread;
uniform float uBrightness;
uniform float uContrast;
uniform float uSoftness;
uniform float uVignette;
uniform int uScanline;
uniform int uGrain;
uniform float uGrainIntensity;
uniform float uOpacity;
uniform int uMouseInteraction;
uniform float uMouseRadius;
uniform float uMouseStrength;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453123);
}

void main() {
  vec2 uv = gl_FragCoord.xy / uResolution.xy;
  vec2 aspect = vec2(uResolution.x / uResolution.y, 1.0);
  vec2 p = (uv - 0.5) * aspect * uScale;

  float t = uTime * uSpeed;
  float sweepT = uTime * uSweepSpeed;

  float mouseDist = length((uv - uMouse) * aspect);
  float mouseInfl = 0.0;
  if (uMouseInteraction == 1) {
    mouseInfl = smoothstep(uMouseRadius, 0.0, mouseDist) * uMouseStrength;
  }

  float coord = (uScanDirection == 0) ? uv.y : uv.x;
  float crossCoord = (uScanDirection == 0) ? p.x : p.y;

  float sweepPos = mod(sweepT, 1.0);
  float dSweep = abs(coord - sweepPos);
  dSweep = min(dSweep, 1.0 - dSweep);
  float sweepBeam = exp(-pow(dSweep * uSweepFalloff / uSweepWidth, 2.0));

  float wavePhase = coord * uBandDensity * 3.14159265 + t;
  float rippleOffset = sin(crossCoord * uFrequency + t * 0.7) * uRipple * 8.0;
  rippleOffset += mouseInfl * 3.0 * sin(mouseDist * 25.0 - t * 3.0);

  float wave = sin(wavePhase + rippleOffset);
  float band = pow(clamp(0.5 + 0.5 * wave, 0.0, 1.0), uLineSharpness);

  float glowFactor = (band * 0.7 + sweepBeam * 0.85 + mouseInfl * 0.6) * uGlow;
  float softBand = mix(band, 0.5 + 0.5 * wave, uSoftness * 0.25);

  float rampFactor = clamp(softBand * uColorSpread + sweepBeam * 0.55, 0.0, 1.0);
  vec3 baseColor = mix(uColor1, uColor2, rampFactor);
  vec3 finalColor = mix(baseColor, uColor3, clamp(pow(band, 2.0) * (sweepBeam + 0.4) + glowFactor, 0.0, 1.0));

  if (uScanline == 1) {
    float sl = sin(gl_FragCoord.y * 1.5) * 0.5 + 0.5;
    finalColor *= mix(1.0, 0.88 + 0.12 * sl, 0.65);
  }

  float vig = length(uv - 0.5);
  finalColor *= (1.0 - smoothstep(0.25, 0.9, vig) * uVignette);

  if (uGrain == 1) {
    float grainVal = (hash(uv * (uTime * 0.15 + 1.0)) - 0.5) * uGrainIntensity;
    finalColor += grainVal;
  }

  finalColor = ((finalColor - 0.5) * uContrast + 0.5) * uBrightness;
  finalColor = clamp(finalColor, 0.0, 1.0);

  float alpha = clamp((band * 0.75 + sweepBeam * 0.85 + glowFactor * 1.0 + mouseInfl * 0.5), 0.0, 1.0) * uOpacity;
  gl_FragColor = vec4(finalColor, alpha);
}
`;

  class Scanner {
    constructor(canvas, options = {}) {
      this.canvas = canvas;
      this.options = Object.assign({
        color1: '#10B981',
        color2: '#06B6D4',
        color3: '#34D399',
        speed: 0.45,
        sweepSpeed: 0.22,
        sweepWidth: 1.8,
        sweepFalloff: 5.5,
        scale: 1.5,
        frequency: 2.0,
        ripple: 0.20,
        bandDensity: 10.0,
        lineSharpness: 5.0,
        glow: 0.25,
        scanDirection: 'vertical',
        colorSpread: 0.7,
        brightness: 1.0,
        contrast: 1.15,
        softness: 1.5,
        vignette: 0.35,
        scanline: true,
        grain: true,
        grainIntensity: 0.04,
        opacity: 0.35,
        mouseInteraction: true,
        mouseRadius: 0.5,
        mouseStrength: 0.5
      }, options);

      this.gl = this.canvas.getContext('webgl2', { alpha: true, antialias: false, powerPreference: 'high-performance' });
      this.isWebGL2 = !!this.gl;
      if (!this.gl) {
        this.gl = this.canvas.getContext('webgl', { alpha: true });
      }

      this.mouse = { x: 0.5, y: 0.5, targetX: 0.5, targetY: 0.5 };
      this.startTime = performance.now();
      this.rafId = null;
      this.boundOnMouseMove = this.onMouseMove.bind(this);
      this.boundOnResize = this.onResize.bind(this);

      if (this.gl) {
        this.initWebGL();
      } else {
        this.initFallback2D();
      }
    }

    initWebGL() {
      const gl = this.gl;
      const vertSource = this.isWebGL2 ? VERT_GL2 : VERT_GL1;
      const fragSource = this.isWebGL2 ? FRAG_GL2 : FRAG_GL1;

      const vertShader = this.createShader(gl.VERTEX_SHADER, vertSource);
      const fragShader = this.createShader(gl.FRAGMENT_SHADER, fragSource);
      if (!vertShader || !fragShader) {
        this.initFallback2D();
        return;
      }

      this.program = gl.createProgram();
      gl.attachShader(this.program, vertShader);
      gl.attachShader(this.program, fragShader);
      gl.linkProgram(this.program);

      if (!gl.getProgramParameter(this.program, gl.LINK_STATUS)) {
        console.warn('Scanner shader link failed, falling back to 2D canvas:', gl.getProgramInfoLog(this.program));
        this.initFallback2D();
        return;
      }

      const quad = new Float32Array([
        -1, -1,
         1, -1,
        -1,  1,
        -1,  1,
         1, -1,
         1,  1,
      ]);

      const buffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(gl.ARRAY_BUFFER, quad, gl.STATIC_DRAW);

      const posLoc = gl.getAttribLocation(this.program, 'position');
      gl.enableVertexAttribArray(posLoc);
      gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 0, 0);

      // Uniform Locations
      this.uTime = gl.getUniformLocation(this.program, 'uTime');
      this.uResolution = gl.getUniformLocation(this.program, 'uResolution');
      this.uMouse = gl.getUniformLocation(this.program, 'uMouse');
      this.uColor1 = gl.getUniformLocation(this.program, 'uColor1');
      this.uColor2 = gl.getUniformLocation(this.program, 'uColor2');
      this.uColor3 = gl.getUniformLocation(this.program, 'uColor3');
      this.uSpeed = gl.getUniformLocation(this.program, 'uSpeed');
      this.uSweepSpeed = gl.getUniformLocation(this.program, 'uSweepSpeed');
      this.uSweepWidth = gl.getUniformLocation(this.program, 'uSweepWidth');
      this.uSweepFalloff = gl.getUniformLocation(this.program, 'uSweepFalloff');
      this.uScale = gl.getUniformLocation(this.program, 'uScale');
      this.uFrequency = gl.getUniformLocation(this.program, 'uFrequency');
      this.uRipple = gl.getUniformLocation(this.program, 'uRipple');
      this.uBandDensity = gl.getUniformLocation(this.program, 'uBandDensity');
      this.uLineSharpness = gl.getUniformLocation(this.program, 'uLineSharpness');
      this.uGlow = gl.getUniformLocation(this.program, 'uGlow');
      this.uScanDirection = gl.getUniformLocation(this.program, 'uScanDirection');
      this.uColorSpread = gl.getUniformLocation(this.program, 'uColorSpread');
      this.uBrightness = gl.getUniformLocation(this.program, 'uBrightness');
      this.uContrast = gl.getUniformLocation(this.program, 'uContrast');
      this.uSoftness = gl.getUniformLocation(this.program, 'uSoftness');
      this.uVignette = gl.getUniformLocation(this.program, 'uVignette');
      this.uScanline = gl.getUniformLocation(this.program, 'uScanline');
      this.uGrain = gl.getUniformLocation(this.program, 'uGrain');
      this.uGrainIntensity = gl.getUniformLocation(this.program, 'uGrainIntensity');
      this.uOpacity = gl.getUniformLocation(this.program, 'uOpacity');
      this.uMouseInteraction = gl.getUniformLocation(this.program, 'uMouseInteraction');
      this.uMouseRadius = gl.getUniformLocation(this.program, 'uMouseRadius');
      this.uMouseStrength = gl.getUniformLocation(this.program, 'uMouseStrength');

      this.bindEvents();
      this.onResize();
      this.render = this.renderWebGL.bind(this);
      this.rafId = requestAnimationFrame(this.render);
    }

    createShader(type, source) {
      const gl = this.gl;
      const shader = gl.createShader(type);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        console.warn('Scanner shader error:', gl.getShaderInfoLog(shader));
        gl.deleteShader(shader);
        return null;
      }
      return shader;
    }

    bindEvents() {
      const parent = this.canvas.closest('section') || this.canvas.parentElement || window;
      parent.addEventListener('mousemove', this.boundOnMouseMove, { passive: true });
      window.addEventListener('resize', this.boundOnResize, { passive: true });
    }

    onMouseMove(e) {
      const rect = this.canvas.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return;
      this.mouse.targetX = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      this.mouse.targetY = Math.max(0, Math.min(1, 1.0 - (e.clientY - rect.top) / rect.height));
    }

    onResize() {
      const rect = this.canvas.parentElement ? this.canvas.parentElement.getBoundingClientRect() : { width: window.innerWidth, height: 600 };
      const dpr = Math.min(window.devicePixelRatio || 1, 2.0);
      const w = Math.floor((rect.width || window.innerWidth) * dpr);
      const h = Math.floor((rect.height || 600) * dpr);

      if (this.canvas.width !== w || this.canvas.height !== h) {
        this.canvas.width = w;
        this.canvas.height = h;
        if (this.gl) {
          this.gl.viewport(0, 0, w, h);
        }
      }
    }

    renderWebGL(now) {
      const gl = this.gl;
      if (!gl || !this.program) return;

      const elapsed = (now - this.startTime) * 0.001;

      // Smooth mouse tracking
      this.mouse.x += (this.mouse.targetX - this.mouse.x) * 0.1;
      this.mouse.y += (this.mouse.targetY - this.mouse.y) * 0.1;

      gl.useProgram(this.program);

      gl.uniform1f(this.uTime, elapsed);
      gl.uniform2f(this.uResolution, this.canvas.width, this.canvas.height);
      gl.uniform2f(this.uMouse, this.mouse.x, this.mouse.y);

      const c1 = hexToRgb(this.options.color1);
      const c2 = hexToRgb(this.options.color2);
      const c3 = hexToRgb(this.options.color3);

      gl.uniform3f(this.uColor1, c1[0], c1[1], c1[2]);
      gl.uniform3f(this.uColor2, c2[0], c2[1], c2[2]);
      gl.uniform3f(this.uColor3, c3[0], c3[1], c3[2]);

      gl.uniform1f(this.uSpeed, this.options.speed);
      gl.uniform1f(this.uSweepSpeed, this.options.sweepSpeed);
      gl.uniform1f(this.uSweepWidth, this.options.sweepWidth);
      gl.uniform1f(this.uSweepFalloff, this.options.sweepFalloff);
      gl.uniform1f(this.uScale, this.options.scale);
      gl.uniform1f(this.uFrequency, this.options.frequency);
      gl.uniform1f(this.uRipple, this.options.ripple);
      gl.uniform1f(this.uBandDensity, this.options.bandDensity);
      gl.uniform1f(this.uLineSharpness, this.options.lineSharpness);
      gl.uniform1f(this.uGlow, this.options.glow);
      gl.uniform1i(this.uScanDirection, this.options.scanDirection === 'horizontal' ? 1 : 0);
      gl.uniform1f(this.uColorSpread, this.options.colorSpread);
      gl.uniform1f(this.uBrightness, this.options.brightness);
      gl.uniform1f(this.uContrast, this.options.contrast);
      gl.uniform1f(this.uSoftness, this.options.softness);
      gl.uniform1f(this.uVignette, this.options.vignette);

      if (this.isWebGL2) {
        gl.uniform1i(this.uScanline, this.options.scanline ? 1 : 0);
        gl.uniform1i(this.uGrain, this.options.grain ? 1 : 0);
        gl.uniform1i(this.uMouseInteraction, this.options.mouseInteraction ? 1 : 0);
      } else {
        gl.uniform1i(this.uScanline, this.options.scanline ? 1 : 0);
        gl.uniform1i(this.uGrain, this.options.grain ? 1 : 0);
        gl.uniform1i(this.uMouseInteraction, this.options.mouseInteraction ? 1 : 0);
      }

      gl.uniform1f(this.uGrainIntensity, this.options.grainIntensity);
      gl.uniform1f(this.uOpacity, this.options.opacity);
      gl.uniform1f(this.uMouseRadius, this.options.mouseRadius);
      gl.uniform1f(this.uMouseStrength, this.options.mouseStrength);

      gl.drawArrays(gl.TRIANGLES, 0, 6);

      this.rafId = requestAnimationFrame(this.render);
    }

    initFallback2D() {
      const ctx = this.canvas.getContext('2d');
      if (!ctx) return;
      this.bindEvents();
      this.onResize();

      const render2D = (now) => {
        const w = this.canvas.width;
        const h = this.canvas.height;
        ctx.clearRect(0, 0, w, h);
        const t = (now - this.startTime) * 0.001 * this.options.sweepSpeed;
        const sweepY = (t % 1.0) * h;

        const grad = ctx.createLinearGradient(0, sweepY - 120, 0, sweepY + 120);
        grad.addColorStop(0, 'rgba(82, 39, 255, 0)');
        grad.addColorStop(0.3, 'rgba(82, 39, 255, 0.4)');
        grad.addColorStop(0.5, 'rgba(255, 159, 252, 0.85)');
        grad.addColorStop(0.7, 'rgba(255, 255, 255, 0.9)');
        grad.addColorStop(1, 'rgba(82, 39, 255, 0)');

        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, w, h);

        this.rafId = requestAnimationFrame(render2D);
      };
      this.rafId = requestAnimationFrame(render2D);
    }

    destroy() {
      if (this.rafId) cancelAnimationFrame(this.rafId);
      const parent = this.canvas.closest('section') || this.canvas.parentElement || window;
      parent.removeEventListener('mousemove', this.boundOnMouseMove);
      window.removeEventListener('resize', this.boundOnResize);
    }
  }

  window.Scanner = Scanner;

  // Auto-initialize all .scanner-canvas elements
  function initAllScanners() {
    const canvases = document.querySelectorAll('.scanner-canvas, [data-scanner]');
    canvases.forEach(canvas => {
      if (canvas._scannerInstance) return;
      canvas._scannerInstance = new Scanner(canvas, {
        color1: canvas.dataset.color1 || '#5227FF',
        color2: canvas.dataset.color2 || '#FF9FFC',
        color3: canvas.dataset.color3 || '#FFFFFF',
        speed: parseFloat(canvas.dataset.speed) || 0.5,
        sweepSpeed: parseFloat(canvas.dataset.sweepSpeed) || 0.25,
        sweepWidth: parseFloat(canvas.dataset.sweepWidth) || 1.6,
        sweepFalloff: parseFloat(canvas.dataset.sweepFalloff) || 6.0,
        scale: parseFloat(canvas.dataset.scale) || 1.5,
        frequency: parseFloat(canvas.dataset.frequency) || 2.0,
        ripple: parseFloat(canvas.dataset.ripple) || 0.22,
        bandDensity: parseFloat(canvas.dataset.bandDensity) || 11.0,
        lineSharpness: parseFloat(canvas.dataset.lineSharpness) || 5.5,
        glow: parseFloat(canvas.dataset.glow) || 0.22,
        scanDirection: canvas.dataset.scanDirection || 'vertical',
        colorSpread: parseFloat(canvas.dataset.colorSpread) || 0.7,
        brightness: parseFloat(canvas.dataset.brightness) || 1.0,
        contrast: parseFloat(canvas.dataset.contrast) || 1.15,
        softness: parseFloat(canvas.dataset.softness) || 1.4,
        vignette: parseFloat(canvas.dataset.vignette) || 0.45,
        scanline: canvas.dataset.scanline !== 'false',
        grain: canvas.dataset.grain !== 'false',
        grainIntensity: parseFloat(canvas.dataset.grainIntensity) || 0.05,
        opacity: parseFloat(canvas.dataset.opacity) || 1.0,
        mouseInteraction: canvas.dataset.mouseInteraction !== 'false',
        mouseRadius: parseFloat(canvas.dataset.mouseRadius) || 0.5,
        mouseStrength: parseFloat(canvas.dataset.mouseStrength) || 0.5
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAllScanners);
  } else {
    initAllScanners();
  }
})();
