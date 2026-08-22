/**
 * MediAI ColorBends WebGL Component (React Bits ColorBends Port)
 * Fluid, wavy color ribbons & domain warping shader with interactive mouse parallax.
 * Supports WebGL2, WebGL1, and Canvas2D fallback.
 */
(function () {
  'use strict';

  function hexToRgb(hex) {
    hex = (hex || '#8a5cff').replace(/^#/, '');
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
uniform vec3 uColor1;
uniform vec3 uColor2;
uniform vec3 uColor3;
uniform vec3 uBaseColor;
uniform float uRotation;
uniform float uSpeed;
uniform float uScale;
uniform float uFrequency;
uniform float uWarpStrength;
uniform float uMouseInfluence;
uniform float uNoise;
uniform float uParallax;
uniform int uIterations;
uniform float uIntensity;
uniform float uBandWidth;
uniform bool uTransparent;
uniform float uAutoRotate;

out vec4 fragColor;

// Simplex-style 2D Noise
vec3 permute(vec3 x) { return mod(((x*34.0)+1.0)*x, 289.0); }
float snoise(vec2 v){
  const vec4 C = vec4(0.211324865405187, 0.366025403784439, -0.577350269189626, 0.024390243902439);
  vec2 i  = floor(v + dot(v, C.yy) );
  vec2 x0 = v -   i + dot(i, C.xx);
  vec2 i1  = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
  vec4 x12 = x0.xyxy + C.xxzz;
  x12.xy -= i1;
  i = mod(i, 289.0);
  vec3 p = permute( permute( i.y + vec3(0.0, i1.y, 1.0 )) + i.x + vec3(0.0, i1.x, 1.0 ));
  vec3 m = max(0.5 - vec3(dot(x0,x0), dot(x12.xy,x12.xy), dot(x12.zw,x12.zw)), 0.0);
  m = m*m ;
  m = m*m ;
  vec3 x = 2.0 * fract(p * C.www) - 1.0;
  vec3 h = abs(x) - 0.5;
  vec3 ox = floor(x + 0.5);
  vec3 a0 = x - ox;
  m *= 1.79284291400159 - 0.85373472095314 * ( a0*a0 + h*h );
  vec3 g;
  g.x  = a0.x  * x0.x  + h.x  * x0.y;
  g.yz = a0.yz * x12.xz + h.yz * x12.yw;
  return 130.0 * dot(m, g);
}

void main() {
  vec2 uv = gl_FragCoord.xy / uResolution.xy;
  vec2 aspect = vec2(uResolution.x / uResolution.y, 1.0);
  vec2 p = (uv - 0.5) * aspect * uScale;

  float t = uTime * uSpeed;

  // Rotation
  float angle = radians(uRotation) + uTime * uAutoRotate * 0.05;
  float s = sin(angle);
  float c = cos(angle);
  p = mat2(c, -s, s, c) * p;

  // Mouse Parallax
  vec2 mouseParallax = (uMouse - 0.5) * uMouseInfluence * uParallax;
  p += mouseParallax;

  // Domain Warping Iterations
  for (int i = 0; i < 3; i++) {
    if (i >= uIterations) break;
    float fi = float(i) + 1.0;
    vec2 warp = vec2(
      sin(p.y * uFrequency * fi + t + snoise(p + t * 0.2) * uNoise * 4.0),
      cos(p.x * uFrequency * fi - t * 0.8 + snoise(p.yx - t * 0.15) * uNoise * 4.0)
    );
    p += warp * (uWarpStrength / fi) * 0.4;
  }

  // Wavy Color Bands
  float noiseVal = snoise(p * 1.5 + t * 0.3) * uNoise * 3.0;
  float band = sin(p.x * uBandWidth + noiseVal + t * 1.2);
  float normBand = 0.5 + 0.5 * band;

  // 3-Color Ribbon Interpolation (Color1 -> Color2 -> Color3)
  vec3 color;
  if (normBand < 0.5) {
    float f = smoothstep(0.0, 0.5, normBand);
    color = mix(uColor1, uColor2, f);
  } else {
    float f = smoothstep(0.5, 1.0, normBand);
    color = mix(uColor2, uColor3, f);
  }

  // Blend with Base Accent Color
  color = mix(uBaseColor, color, 0.85);
  color *= uIntensity;

  // Alpha / Transparency
  float alpha = 1.0;
  if (uTransparent) {
    alpha = clamp(smoothstep(0.08, 0.88, normBand) * 0.65 + 0.15, 0.0, 0.75);
  }

  fragColor = vec4(color, alpha);
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
uniform vec3 uBaseColor;
uniform float uRotation;
uniform float uSpeed;
uniform float uScale;
uniform float uFrequency;
uniform float uWarpStrength;
uniform float uMouseInfluence;
uniform float uNoise;
uniform float uParallax;
uniform int uIterations;
uniform float uIntensity;
uniform float uBandWidth;
uniform int uTransparent;
uniform float uAutoRotate;

vec3 permute(vec3 x) { return mod(((x*34.0)+1.0)*x, 289.0); }
float snoise(vec2 v){
  const vec4 C = vec4(0.211324865405187, 0.366025403784439, -0.577350269189626, 0.024390243902439);
  vec2 i  = floor(v + dot(v, C.yy) );
  vec2 x0 = v -   i + dot(i, C.xx);
  vec2 i1  = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
  vec4 x12 = x0.xyxy + C.xxzz;
  x12.xy -= i1;
  i = mod(i, 289.0);
  vec3 p = permute( permute( i.y + vec3(0.0, i1.y, 1.0 )) + i.x + vec3(0.0, i1.x, 1.0 ));
  vec3 m = max(0.5 - vec3(dot(x0,x0), dot(x12.xy,x12.xy), dot(x12.zw,x12.zw)), 0.0);
  m = m*m ;
  m = m*m ;
  vec3 x = 2.0 * fract(p * C.www) - 1.0;
  vec3 h = abs(x) - 0.5;
  vec3 ox = floor(x + 0.5);
  vec3 a0 = x - ox;
  m *= 1.79284291400159 - 0.85373472095314 * ( a0*a0 + h*h );
  vec3 g;
  g.x  = a0.x  * x0.x  + h.x  * x0.y;
  g.yz = a0.yz * x12.xz + h.yz * x12.yw;
  return 130.0 * dot(m, g);
}

void main() {
  vec2 uv = gl_FragCoord.xy / uResolution.xy;
  vec2 aspect = vec2(uResolution.x / uResolution.y, 1.0);
  vec2 p = (uv - 0.5) * aspect * uScale;

  float t = uTime * uSpeed;

  float angle = radians(uRotation) + uTime * uAutoRotate * 0.05;
  float s = sin(angle);
  float c = cos(angle);
  p = mat2(c, -s, s, c) * p;

  vec2 mouseParallax = (uMouse - 0.5) * uMouseInfluence * uParallax;
  p += mouseParallax;

  for (int i = 0; i < 3; i++) {
    if (i >= uIterations) break;
    float fi = float(i) + 1.0;
    vec2 warp = vec2(
      sin(p.y * uFrequency * fi + t + snoise(p + t * 0.2) * uNoise * 4.0),
      cos(p.x * uFrequency * fi - t * 0.8 + snoise(p.yx - t * 0.15) * uNoise * 4.0)
    );
    p += warp * (uWarpStrength / fi) * 0.4;
  }

  float noiseVal = snoise(p * 1.5 + t * 0.3) * uNoise * 3.0;
  float band = sin(p.x * uBandWidth + noiseVal + t * 1.2);
  float normBand = 0.5 + 0.5 * band;

  vec3 color;
  if (normBand < 0.5) {
    float f = smoothstep(0.0, 0.5, normBand);
    color = mix(uColor1, uColor2, f);
  } else {
    float f = smoothstep(0.5, 1.0, normBand);
    color = mix(uColor2, uColor3, f);
  }

  color = mix(uBaseColor, color, 0.85);
  color *= uIntensity;

  float alpha = 1.0;
  if (uTransparent == 1) {
    alpha = clamp(smoothstep(0.08, 0.88, normBand) * 0.65 + 0.15, 0.0, 0.75);
  }

  gl_FragColor = vec4(color, alpha);
}
`;

  class ColorBends {
    constructor(canvas, options = {}) {
      this.canvas = canvas;
      this.options = Object.assign({
        colors: ['#88E788', '#10B981', '#00ffd1'],
        color: '#88E788',
        rotation: 90,
        speed: 0.2,
        scale: 1.0,
        frequency: 1.0,
        warpStrength: 1.0,
        mouseInfluence: 1.0,
        noise: 0.15,
        parallax: 0.5,
        iterations: 1,
        intensity: 1.5,
        bandWidth: 6.0,
        transparent: true,
        autoRotate: 0.0
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
        console.warn('ColorBends shader link failed, falling back to 2D canvas:', gl.getProgramInfoLog(this.program));
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
      this.uColor1 = gl.getUniformLocation(this.program, 'uColor1');
      this.uColor2 = gl.getUniformLocation(this.program, 'uColor2');
      this.uColor3 = gl.getUniformLocation(this.program, 'uColor3');
      this.uBaseColor = gl.getUniformLocation(this.program, 'uBaseColor');
      this.uRotation = gl.getUniformLocation(this.program, 'uRotation');
      this.uSpeed = gl.getUniformLocation(this.program, 'uSpeed');
      this.uScale = gl.getUniformLocation(this.program, 'uScale');
      this.uFrequency = gl.getUniformLocation(this.program, 'uFrequency');
      this.uWarpStrength = gl.getUniformLocation(this.program, 'uWarpStrength');
      this.uMouseInfluence = gl.getUniformLocation(this.program, 'uMouseInfluence');
      this.uNoise = gl.getUniformLocation(this.program, 'uNoise');
      this.uParallax = gl.getUniformLocation(this.program, 'uParallax');
      this.uIterations = gl.getUniformLocation(this.program, 'uIterations');
      this.uIntensity = gl.getUniformLocation(this.program, 'uIntensity');
      this.uBandWidth = gl.getUniformLocation(this.program, 'uBandWidth');
      this.uTransparent = gl.getUniformLocation(this.program, 'uTransparent');
      this.uAutoRotate = gl.getUniformLocation(this.program, 'uAutoRotate');

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
        console.warn('ColorBends shader error:', gl.getShaderInfoLog(shader));
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

      // Mouse tracking
      this.mouse.x += (this.mouse.targetX - this.mouse.x) * 0.08;
      this.mouse.y += (this.mouse.targetY - this.mouse.y) * 0.08;

      gl.useProgram(this.program);

      gl.uniform1f(this.uTime, elapsed);
      gl.uniform2f(this.uResolution, this.canvas.width, this.canvas.height);
      gl.uniform2f(this.uMouse, this.mouse.x, this.mouse.y);

      const colors = this.options.colors || ['#88E788', '#4ADE80', '#10B981'];
      const c1 = hexToRgb(colors[0] || '#88E788');
      const c2 = hexToRgb(colors[1] || '#4ADE80');
      const c3 = hexToRgb(colors[2] || '#10B981');
      const cBase = hexToRgb(this.options.color || '#88E788');

      gl.uniform3f(this.uColor1, c1[0], c1[1], c1[2]);
      gl.uniform3f(this.uColor2, c2[0], c2[1], c2[2]);
      gl.uniform3f(this.uColor3, c3[0], c3[1], c3[2]);
      gl.uniform3f(this.uBaseColor, cBase[0], cBase[1], cBase[2]);

      gl.uniform1f(this.uRotation, this.options.rotation);
      gl.uniform1f(this.uSpeed, this.options.speed);
      gl.uniform1f(this.uScale, this.options.scale);
      gl.uniform1f(this.uFrequency, this.options.frequency);
      gl.uniform1f(this.uWarpStrength, this.options.warpStrength);
      gl.uniform1f(this.uMouseInfluence, this.options.mouseInfluence);
      gl.uniform1f(this.uNoise, this.options.noise);
      gl.uniform1f(this.uParallax, this.options.parallax);
      gl.uniform1i(this.uIterations, Math.max(1, parseInt(this.options.iterations) || 1));
      gl.uniform1f(this.uIntensity, this.options.intensity);
      gl.uniform1f(this.uBandWidth, this.options.bandWidth);
      gl.uniform1f(this.uAutoRotate, this.options.autoRotate);

      if (this.isWebGL2) {
        gl.uniform1i(this.uTransparent, this.options.transparent ? 1 : 0);
      } else {
        gl.uniform1i(this.uTransparent, this.options.transparent ? 1 : 0);
      }

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
        grad.addColorStop(0, 'rgba(136, 231, 136, 0.45)');
        grad.addColorStop(0.5, 'rgba(74, 222, 128, 0.45)');
        grad.addColorStop(1, 'rgba(16, 185, 129, 0.45)');

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

  window.ColorBends = ColorBends;

  // Auto-initialize all .color-bends-canvas elements
  function initAllColorBends() {
    const canvases = document.querySelectorAll('.color-bends-canvas, [data-color-bends]');
    canvases.forEach(canvas => {
      if (canvas._colorBendsInstance) return;
      let colors = ['#88E788', '#4ADE80', '#10B981'];
      if (canvas.dataset.colors) {
        try {
          colors = JSON.parse(canvas.dataset.colors);
        } catch (e) {
          colors = canvas.dataset.colors.split(',').map(s => s.trim());
        }
      }
      canvas._colorBendsInstance = new ColorBends(canvas, {
        colors: colors,
        color: canvas.dataset.color || '#88E788',
        rotation: parseFloat(canvas.dataset.rotation) || 90,
        speed: parseFloat(canvas.dataset.speed) || 0.2,
        scale: parseFloat(canvas.dataset.scale) || 1.0,
        frequency: parseFloat(canvas.dataset.frequency) || 1.0,
        warpStrength: parseFloat(canvas.dataset.warpStrength) || 1.0,
        mouseInfluence: parseFloat(canvas.dataset.mouseInfluence) || 1.0,
        noise: parseFloat(canvas.dataset.noise) || 0.15,
        parallax: parseFloat(canvas.dataset.parallax) || 0.5,
        iterations: parseInt(canvas.dataset.iterations) || 1,
        intensity: parseFloat(canvas.dataset.intensity) || 1.5,
        bandWidth: parseFloat(canvas.dataset.bandWidth) || 6.0,
        transparent: canvas.dataset.transparent !== 'false',
        autoRotate: parseFloat(canvas.dataset.autoRotate) || 0.0
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAllColorBends);
  } else {
    initAllColorBends();
  }
})();
