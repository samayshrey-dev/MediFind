/**
 * MediAI DarkVeil WebGL Component (React Bits DarkVeil Port)
 * Volumetric, fluid dark veil & silky atmospheric shader with theme tinting.
 * Supports WebGL2, WebGL1, and Canvas2D fallback.
 */
(function () {
  'use strict';

  function hexToRgb(hex) {
    hex = (hex || '#88E788').replace(/^#/, '');
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

  // WebGL 2.0 (GLSL 3.00 ES) Shaders
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
uniform float uHueShift;
uniform float uNoiseIntensity;
uniform float uScanlineIntensity;
uniform float uSpeed;
uniform float uScanlineFrequency;
uniform float uWarpAmount;
uniform vec3 uColorPrimary;
uniform vec3 uColorSecondary;
uniform vec3 uColorDark;

out vec4 fragColor;

// Hash & Noise
float hash(vec2 p) {
  return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453123);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  float a = hash(i);
  float b = hash(i + vec2(1.0, 0.0));
  float c = hash(i + vec2(0.0, 1.0));
  float d = hash(i + vec2(1.0, 1.0));
  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

mat2 rot2D(float angle) {
  float s = sin(angle);
  float c = cos(angle);
  return mat2(c, -s, s, c);
}

float fbm(vec2 p) {
  float v = 0.0;
  float a = 0.5;
  mat2 rot = rot2D(0.5);
  for (int i = 0; i < 5; i++) {
    v += a * noise(p);
    p = rot * p * 2.0 + vec2(100.0);
    a *= 0.5;
  }
  return v;
}

// Hue Shift Transformation
vec3 rgb2hsv(vec3 c) {
  vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
  vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
  vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
  float d = q.x - min(q.w, q.y);
  float e = 1.0e-10;
  return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}

vec3 hsv2rgb(vec3 c) {
  vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
  vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
  return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
}

void main() {
  vec2 uv = gl_FragCoord.xy / uResolution.xy;
  vec2 aspect = vec2(uResolution.x / uResolution.y, 1.0);
  vec2 p = (uv - 0.5) * aspect * 2.4;

  float t = uTime * uSpeed * 0.4;

  // Subtle Mouse Influence
  vec2 mouseOffset = (uMouse - 0.5) * 0.25;
  p += mouseOffset;

  // Domain Warping / Volumetric Silk Layers
  vec2 q = vec2(0.0);
  q.x = fbm(p + vec2(0.0, 0.0) + t * 0.18);
  q.y = fbm(p + vec2(5.2, 1.3) + t * 0.14);

  vec2 r = vec2(0.0);
  r.x = fbm(p + (4.0 + uWarpAmount * 2.0) * q + vec2(1.7, 9.2) + t * 0.12);
  r.y = fbm(p + (4.0 + uWarpAmount * 2.0) * q + vec2(8.3, 2.8) + t * 0.09);

  float f = fbm(p + 4.0 * r);

  // MediAI Theme Color Mapping (Deep Emerald Navy -> Emerald Green -> Pastel Mint Highlight)
  vec3 color = mix(uColorDark, uColorSecondary, clamp(f * f * 3.5, 0.0, 1.0));
  color = mix(color, uColorPrimary, clamp(length(q) * 0.75, 0.0, 1.0));
  color = mix(color, vec3(0.533, 0.906, 0.533), clamp(pow(r.x, 2.2) * 1.2, 0.0, 1.0));

  // Hue Shift
  if (uHueShift != 0.0) {
    vec3 hsv = rgb2hsv(color);
    hsv.x = fract(hsv.x + uHueShift / 360.0);
    color = hsv2rgb(hsv);
  }

  // Scanlines
  if (uScanlineIntensity > 0.0) {
    float freq = uScanlineFrequency > 0.0 ? uScanlineFrequency : 400.0;
    float scanline = sin(uv.y * freq) * 0.5 + 0.5;
    color *= mix(1.0, 0.85 + 0.15 * scanline, uScanlineIntensity);
  }

  // Film Noise / Grain
  if (uNoiseIntensity > 0.0) {
    float grain = (hash(uv * (uTime + 1.0)) - 0.5) * uNoiseIntensity;
    color += grain;
  }

  // Vignette
  float vig = length(uv - 0.5);
  color *= (1.0 - smoothstep(0.3, 0.95, vig) * 0.35);

  fragColor = vec4(clamp(color, 0.0, 1.0), 1.0);
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
uniform float uHueShift;
uniform float uNoiseIntensity;
uniform float uScanlineIntensity;
uniform float uSpeed;
uniform float uScanlineFrequency;
uniform float uWarpAmount;
uniform vec3 uColorPrimary;
uniform vec3 uColorSecondary;
uniform vec3 uColorDark;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453123);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  float a = hash(i);
  float b = hash(i + vec2(1.0, 0.0));
  float c = hash(i + vec2(0.0, 1.0));
  float d = hash(i + vec2(1.0, 1.0));
  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

mat2 rot2D(float angle) {
  float s = sin(angle);
  float c = cos(angle);
  return mat2(c, -s, s, c);
}

float fbm(vec2 p) {
  float v = 0.0;
  float a = 0.5;
  mat2 rot = rot2D(0.5);
  for (int i = 0; i < 5; i++) {
    v += a * noise(p);
    p = rot * p * 2.0 + vec2(100.0);
    a *= 0.5;
  }
  return v;
}

vec3 rgb2hsv(vec3 c) {
  vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
  vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
  vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
  float d = q.x - min(q.w, q.y);
  float e = 1.0e-10;
  return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}

vec3 hsv2rgb(vec3 c) {
  vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
  vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
  return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
}

void main() {
  vec2 uv = gl_FragCoord.xy / uResolution.xy;
  vec2 aspect = vec2(uResolution.x / uResolution.y, 1.0);
  vec2 p = (uv - 0.5) * aspect * 2.4;

  float t = uTime * uSpeed * 0.4;
  vec2 mouseOffset = (uMouse - 0.5) * 0.25;
  p += mouseOffset;

  vec2 q = vec2(0.0);
  q.x = fbm(p + vec2(0.0, 0.0) + t * 0.18);
  q.y = fbm(p + vec2(5.2, 1.3) + t * 0.14);

  vec2 r = vec2(0.0);
  r.x = fbm(p + (4.0 + uWarpAmount * 2.0) * q + vec2(1.7, 9.2) + t * 0.12);
  r.y = fbm(p + (4.0 + uWarpAmount * 2.0) * q + vec2(8.3, 2.8) + t * 0.09);

  float f = fbm(p + 4.0 * r);

  vec3 color = mix(uColorDark, uColorSecondary, clamp(f * f * 3.5, 0.0, 1.0));
  color = mix(color, uColorPrimary, clamp(length(q) * 0.75, 0.0, 1.0));
  color = mix(color, vec3(0.533, 0.906, 0.533), clamp(pow(r.x, 2.2) * 1.2, 0.0, 1.0));

  if (uHueShift != 0.0) {
    vec3 hsv = rgb2hsv(color);
    hsv.x = fract(hsv.x + uHueShift / 360.0);
    color = hsv2rgb(hsv);
  }

  if (uScanlineIntensity > 0.0) {
    float freq = uScanlineFrequency > 0.0 ? uScanlineFrequency : 400.0;
    float scanline = sin(uv.y * freq) * 0.5 + 0.5;
    color *= mix(1.0, 0.85 + 0.15 * scanline, uScanlineIntensity);
  }

  if (uNoiseIntensity > 0.0) {
    float grain = (hash(uv * (uTime + 1.0)) - 0.5) * uNoiseIntensity;
    color += grain;
  }

  float vig = length(uv - 0.5);
  color *= (1.0 - smoothstep(0.3, 0.95, vig) * 0.35);

  gl_FragColor = vec4(clamp(color, 0.0, 1.0), 1.0);
}
`;

  class DarkVeil {
    constructor(canvas, options = {}) {
      this.canvas = canvas;
      this.options = Object.assign({
        hueShift: 0.0,
        noiseIntensity: 0.0,
        scanlineIntensity: 0.0,
        speed: 0.5,
        scanlineFrequency: 0.0,
        warpAmount: 0.0,
        colorPrimary: '#88E788',
        colorSecondary: '#10B981',
        colorDark: '#0A1818'
      }, options);

      this.gl = this.canvas.getContext('webgl2', { alpha: false, antialias: false, powerPreference: 'high-performance' });
      this.isWebGL2 = !!this.gl;
      if (!this.gl) {
        this.gl = this.canvas.getContext('webgl', { alpha: false });
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
        console.warn('DarkVeil shader link failed, falling back to 2D canvas:', gl.getProgramInfoLog(this.program));
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

      // Uniforms
      this.uTime = gl.getUniformLocation(this.program, 'uTime');
      this.uResolution = gl.getUniformLocation(this.program, 'uResolution');
      this.uMouse = gl.getUniformLocation(this.program, 'uMouse');
      this.uHueShift = gl.getUniformLocation(this.program, 'uHueShift');
      this.uNoiseIntensity = gl.getUniformLocation(this.program, 'uNoiseIntensity');
      this.uScanlineIntensity = gl.getUniformLocation(this.program, 'uScanlineIntensity');
      this.uSpeed = gl.getUniformLocation(this.program, 'uSpeed');
      this.uScanlineFrequency = gl.getUniformLocation(this.program, 'uScanlineFrequency');
      this.uWarpAmount = gl.getUniformLocation(this.program, 'uWarpAmount');
      this.uColorPrimary = gl.getUniformLocation(this.program, 'uColorPrimary');
      this.uColorSecondary = gl.getUniformLocation(this.program, 'uColorSecondary');
      this.uColorDark = gl.getUniformLocation(this.program, 'uColorDark');

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
        console.warn('DarkVeil shader error:', gl.getShaderInfoLog(shader));
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

      this.mouse.x += (this.mouse.targetX - this.mouse.x) * 0.06;
      this.mouse.y += (this.mouse.targetY - this.mouse.y) * 0.06;

      gl.useProgram(this.program);

      gl.uniform1f(this.uTime, elapsed);
      gl.uniform2f(this.uResolution, this.canvas.width, this.canvas.height);
      gl.uniform2f(this.uMouse, this.mouse.x, this.mouse.y);

      const cPrimary = hexToRgb(this.options.colorPrimary || '#88E788');
      const cSecondary = hexToRgb(this.options.colorSecondary || '#10B981');
      const cDark = hexToRgb(this.options.colorDark || '#0A1818');

      gl.uniform3f(this.uColorPrimary, cPrimary[0], cPrimary[1], cPrimary[2]);
      gl.uniform3f(this.uColorSecondary, cSecondary[0], cSecondary[1], cSecondary[2]);
      gl.uniform3f(this.uColorDark, cDark[0], cDark[1], cDark[2]);

      gl.uniform1f(this.uHueShift, this.options.hueShift);
      gl.uniform1f(this.uNoiseIntensity, this.options.noiseIntensity);
      gl.uniform1f(this.uScanlineIntensity, this.options.scanlineIntensity);
      gl.uniform1f(this.uSpeed, this.options.speed);
      gl.uniform1f(this.uScanlineFrequency, this.options.scanlineFrequency);
      gl.uniform1f(this.uWarpAmount, this.options.warpAmount);

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
        const t = (now - this.startTime) * 0.001 * this.options.speed;

        const grad = ctx.createLinearGradient(0, 0, w, h);
        grad.addColorStop(0, '#0A1818');
        grad.addColorStop(0.5, '#064E3B');
        grad.addColorStop(1, '#88E788');

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

  window.DarkVeil = DarkVeil;

  // Auto-initialize all .dark-veil-canvas elements
  function initAllDarkVeils() {
    const canvases = document.querySelectorAll('.dark-veil-canvas, [data-dark-veil]');
    canvases.forEach(canvas => {
      if (canvas._darkVeilInstance) return;
      canvas._darkVeilInstance = new DarkVeil(canvas, {
        hueShift: parseFloat(canvas.dataset.hueShift) || 0.0,
        noiseIntensity: parseFloat(canvas.dataset.noiseIntensity) || 0.0,
        scanlineIntensity: parseFloat(canvas.dataset.scanlineIntensity) || 0.0,
        speed: parseFloat(canvas.dataset.speed) || 0.5,
        scanlineFrequency: parseFloat(canvas.dataset.scanlineFrequency) || 0.0,
        warpAmount: parseFloat(canvas.dataset.warpAmount) || 0.0,
        colorPrimary: canvas.dataset.colorPrimary || '#88E788',
        colorSecondary: canvas.dataset.colorSecondary || '#10B981',
        colorDark: canvas.dataset.colorDark || '#0A1818'
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAllDarkVeils);
  } else {
    initAllDarkVeils();
  }
})();
