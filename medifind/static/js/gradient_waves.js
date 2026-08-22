/**
 * MediAI GradientWaves WebGL Component (React Bits GradientWaves Port)
 * 3D undulating perspective wave terrain & raymarched gradient shader.
 * Features top-down/bottom perspective, multi-octave swells, turbulence,
 * horizon fog, crest lighting, film grain, and interactive mouse parallax.
 * Supports WebGL2, WebGL1, and Canvas2D fallback.
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
uniform vec3 uHorizonColor;
uniform vec3 uWaveColor;
uniform vec3 uCrestColor;
uniform float uSpeed;
uniform float uAmplitude;
uniform float uWaveScale;
uniform float uWaveRatio;
uniform float uSwell;
uniform float uTurbulence;
uniform float uTilt;
uniform float uZoom;
uniform float uHeight;
uniform float uFogDepth;
uniform float uBrightness;
uniform float uOpacity;
uniform bool uMouseInteraction;
uniform float uParallaxStrength;
uniform bool uGrain;
uniform float uGrainIntensity;
uniform bool uInvertTop;

out vec4 fragColor;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453123);
}

mat2 rot2D(float a) {
  float c = cos(a), s = sin(a);
  return mat2(c, -s, s, c);
}

// Wave Heightfield Function
float getWaveHeight(vec2 p, float t) {
  vec2 pos = p * uWaveScale * 0.25;
  float h = 0.0;
  float weight = 1.0;
  float freq = 1.0;
  mat2 r = rot2D(0.45);

  // Large Swell Waves
  float swellPhase = (pos.x * uWaveRatio + pos.y * (2.0 - uWaveRatio)) * 0.75 + t * 0.8;
  h += sin(swellPhase) * (uSwell / 35.0) * 0.8;

  // Multi-Octave Turbulence Harmonics
  for (int i = 0; i < 4; i++) {
    vec2 pRot = pos * freq;
    float wave = sin(pRot.x + t * (float(i) * 0.3 + 0.7)) * cos(pRot.y * 0.8 - t * 0.5);
    h += wave * weight * (uTurbulence / 20.0) * 0.45;
    pos = r * pos * 1.6;
    weight *= 0.55;
    freq *= 1.45;
  }

  return h * uAmplitude;
}

void main() {
  vec2 uv = gl_FragCoord.xy / uResolution.xy;
  
  // Invert Y for top-down wave flow if requested
  if (uInvertTop) {
    uv.y = 1.0 - uv.y;
  }

  vec2 aspect = vec2(uResolution.x / uResolution.y, 1.0);
  vec2 screenP = (uv - 0.5) * aspect;

  float t = uTime * uSpeed * 0.6;

  // Camera Setup
  vec2 mouseParallax = vec2(0.0);
  if (uMouseInteraction) {
    mouseParallax = (uMouse - 0.5) * uParallaxStrength * 1.5;
  }

  vec3 ro = vec3(mouseParallax.x * 2.0, uHeight + mouseParallax.y * 0.8, -uZoom * 3.5);
  vec3 rd = normalize(vec3(screenP.x, screenP.y * uTilt - 0.25, 1.35));

  // Raymarch Wave Surface
  float depth = 0.5;
  float maxDepth = uFogDepth * 1.8;
  float hitDist = -1.0;
  vec3 hitPos = vec3(0.0);
  float waveH = 0.0;

  for (int i = 0; i < 48; i++) {
    vec3 p = ro + rd * depth;
    waveH = getWaveHeight(p.xz, t);
    float diff = p.y - waveH;
    
    if (diff < 0.02) {
      hitDist = depth;
      hitPos = p;
      break;
    }
    depth += max(0.06, diff * 0.45);
    if (depth > maxDepth) break;
  }

  vec3 finalColor;

  if (hitDist > 0.0) {
    // Normal estimation
    vec2 eps = vec2(0.04, 0.0);
    float hL = getWaveHeight(hitPos.xz - eps.xy, t);
    float hR = getWaveHeight(hitPos.xz + eps.xy, t);
    float hD = getWaveHeight(hitPos.xz - eps.yx, t);
    float hU = getWaveHeight(hitPos.xz + eps.yx, t);
    vec3 normal = normalize(vec3(hL - hR, 2.0 * eps.x, hD - hU));

    // Crest Factor (peaks & sharp slope)
    float crestFactor = clamp((waveH + uAmplitude * 0.6) / (uAmplitude * 1.4), 0.0, 1.0);
    crestFactor = pow(crestFactor, 2.6);

    // Diffuse & Specular Lighting
    vec3 lightDir = normalize(vec3(0.3, 0.9, -0.6));
    float diff = clamp(dot(normal, lightDir), 0.0, 1.0);
    vec3 halfVec = normalize(lightDir - rd);
    float spec = pow(clamp(dot(normal, halfVec), 0.0, 1.0), 18.0) * 0.8;

    // Color Blending (Horizon -> Wave Color -> Crest Highlight)
    vec3 surfaceColor = mix(uWaveColor, uCrestColor, crestFactor * 0.85 + spec);
    surfaceColor *= (diff * 0.65 + 0.45);

    // Atmospheric Depth / Fog
    float fog = smoothstep(1.0, uFogDepth, hitDist);
    finalColor = mix(surfaceColor, uHorizonColor, fog * 0.85);
  } else {
    // Horizon Sky Gradient
    float skyGradient = smoothstep(-0.3, 0.6, screenP.y);
    finalColor = mix(uHorizonColor, uWaveColor * 0.6, skyGradient * 0.4);
  }

  // Film Grain
  if (uGrain) {
    float grainVal = (hash(gl_FragCoord.xy * (uTime * 0.1 + 1.0)) - 0.5) * uGrainIntensity;
    finalColor += grainVal;
  }

  finalColor *= uBrightness;

  fragColor = vec4(clamp(finalColor, 0.0, 1.0), uOpacity);
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
uniform vec3 uHorizonColor;
uniform vec3 uWaveColor;
uniform vec3 uCrestColor;
uniform float uSpeed;
uniform float uAmplitude;
uniform float uWaveScale;
uniform float uWaveRatio;
uniform float uSwell;
uniform float uTurbulence;
uniform float uTilt;
uniform float uZoom;
uniform float uHeight;
uniform float uFogDepth;
uniform float uBrightness;
uniform float uOpacity;
uniform int uMouseInteraction;
uniform float uParallaxStrength;
uniform int uGrain;
uniform float uGrainIntensity;
uniform int uInvertTop;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453123);
}

mat2 rot2D(float a) {
  float c = cos(a), s = sin(a);
  return mat2(c, -s, s, c);
}

float getWaveHeight(vec2 p, float t) {
  vec2 pos = p * uWaveScale * 0.25;
  float h = 0.0;
  float weight = 1.0;
  float freq = 1.0;
  mat2 r = rot2D(0.45);

  float swellPhase = (pos.x * uWaveRatio + pos.y * (2.0 - uWaveRatio)) * 0.75 + t * 0.8;
  h += sin(swellPhase) * (uSwell / 35.0) * 0.8;

  for (int i = 0; i < 4; i++) {
    vec2 pRot = pos * freq;
    float wave = sin(pRot.x + t * (float(i) * 0.3 + 0.7)) * cos(pRot.y * 0.8 - t * 0.5);
    h += wave * weight * (uTurbulence / 20.0) * 0.45;
    pos = r * pos * 1.6;
    weight *= 0.55;
    freq *= 1.45;
  }

  return h * uAmplitude;
}

void main() {
  vec2 uv = gl_FragCoord.xy / uResolution.xy;
  if (uInvertTop == 1) {
    uv.y = 1.0 - uv.y;
  }

  vec2 aspect = vec2(uResolution.x / uResolution.y, 1.0);
  vec2 screenP = (uv - 0.5) * aspect;

  float t = uTime * uSpeed * 0.6;

  vec2 mouseParallax = vec2(0.0);
  if (uMouseInteraction == 1) {
    mouseParallax = (uMouse - 0.5) * uParallaxStrength * 1.5;
  }

  vec3 ro = vec3(mouseParallax.x * 2.0, uHeight + mouseParallax.y * 0.8, -uZoom * 3.5);
  vec3 rd = normalize(vec3(screenP.x, screenP.y * uTilt - 0.25, 1.35));

  float depth = 0.5;
  float maxDepth = uFogDepth * 1.8;
  float hitDist = -1.0;
  vec3 hitPos = vec3(0.0);
  float waveH = 0.0;

  for (int i = 0; i < 48; i++) {
    vec3 p = ro + rd * depth;
    waveH = getWaveHeight(p.xz, t);
    float diff = p.y - waveH;
    
    if (diff < 0.02) {
      hitDist = depth;
      hitPos = p;
      break;
    }
    depth += max(0.06, diff * 0.45);
    if (depth > maxDepth) break;
  }

  vec3 finalColor;

  if (hitDist > 0.0) {
    vec2 eps = vec2(0.04, 0.0);
    float hL = getWaveHeight(hitPos.xz - eps.xy, t);
    float hR = getWaveHeight(hitPos.xz + eps.xy, t);
    float hD = getWaveHeight(hitPos.xz - eps.yx, t);
    float hU = getWaveHeight(hitPos.xz + eps.yx, t);
    vec3 normal = normalize(vec3(hL - hR, 2.0 * eps.x, hD - hU));

    float crestFactor = clamp((waveH + uAmplitude * 0.6) / (uAmplitude * 1.4), 0.0, 1.0);
    crestFactor = pow(crestFactor, 2.6);

    vec3 lightDir = normalize(vec3(0.3, 0.9, -0.6));
    float diff = clamp(dot(normal, lightDir), 0.0, 1.0);
    vec3 halfVec = normalize(lightDir - rd);
    float spec = pow(clamp(dot(normal, halfVec), 0.0, 1.0), 18.0) * 0.8;

    vec3 surfaceColor = mix(uWaveColor, uCrestColor, crestFactor * 0.85 + spec);
    surfaceColor *= (diff * 0.65 + 0.45);

    float fog = smoothstep(1.0, uFogDepth, hitDist);
    finalColor = mix(surfaceColor, uHorizonColor, fog * 0.85);
  } else {
    float skyGradient = smoothstep(-0.3, 0.6, screenP.y);
    finalColor = mix(uHorizonColor, uWaveColor * 0.6, skyGradient * 0.4);
  }

  if (uGrain == 1) {
    float grainVal = (hash(gl_FragCoord.xy * (uTime * 0.1 + 1.0)) - 0.5) * uGrainIntensity;
    finalColor += grainVal;
  }

  finalColor *= uBrightness;

  gl_FragColor = vec4(clamp(finalColor, 0.0, 1.0), uOpacity);
}
`;

  class GradientWaves {
    constructor(canvas, options = {}) {
      this.canvas = canvas;
      this.options = Object.assign({
        horizonColor: '#5227FF',
        waveColor: '#FF9FFC',
        crestColor: '#FFFFFF',
        speed: 0.4,
        amplitude: 2.5,
        waveScale: 0.6,
        waveRatio: 0.9,
        swell: 35.0,
        turbulence: 20.0,
        tilt: 1.11,
        zoom: 1.0,
        height: 5.5,
        fogDepth: 15.0,
        detail: 'medium',
        brightness: 1.0,
        opacity: 1.0,
        mouseInteraction: true,
        parallaxStrength: 0.5,
        grain: true,
        grainIntensity: 0.05,
        invertTop: true // "make this from the top instead of the bottom"
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
        console.warn('GradientWaves shader link failed, falling back to 2D canvas:', gl.getProgramInfoLog(this.program));
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
      this.uHorizonColor = gl.getUniformLocation(this.program, 'uHorizonColor');
      this.uWaveColor = gl.getUniformLocation(this.program, 'uWaveColor');
      this.uCrestColor = gl.getUniformLocation(this.program, 'uCrestColor');
      this.uSpeed = gl.getUniformLocation(this.program, 'uSpeed');
      this.uAmplitude = gl.getUniformLocation(this.program, 'uAmplitude');
      this.uWaveScale = gl.getUniformLocation(this.program, 'uWaveScale');
      this.uWaveRatio = gl.getUniformLocation(this.program, 'uWaveRatio');
      this.uSwell = gl.getUniformLocation(this.program, 'uSwell');
      this.uTurbulence = gl.getUniformLocation(this.program, 'uTurbulence');
      this.uTilt = gl.getUniformLocation(this.program, 'uTilt');
      this.uZoom = gl.getUniformLocation(this.program, 'uZoom');
      this.uHeight = gl.getUniformLocation(this.program, 'uHeight');
      this.uFogDepth = gl.getUniformLocation(this.program, 'uFogDepth');
      this.uBrightness = gl.getUniformLocation(this.program, 'uBrightness');
      this.uOpacity = gl.getUniformLocation(this.program, 'uOpacity');
      this.uMouseInteraction = gl.getUniformLocation(this.program, 'uMouseInteraction');
      this.uParallaxStrength = gl.getUniformLocation(this.program, 'uParallaxStrength');
      this.uGrain = gl.getUniformLocation(this.program, 'uGrain');
      this.uGrainIntensity = gl.getUniformLocation(this.program, 'uGrainIntensity');
      this.uInvertTop = gl.getUniformLocation(this.program, 'uInvertTop');

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
        console.warn('GradientWaves shader error:', gl.getShaderInfoLog(shader));
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

      const cHorizon = hexToRgb(this.options.horizonColor || '#5227FF');
      const cWave = hexToRgb(this.options.waveColor || '#FF9FFC');
      const cCrest = hexToRgb(this.options.crestColor || '#FFFFFF');

      gl.uniform3f(this.uHorizonColor, cHorizon[0], cHorizon[1], cHorizon[2]);
      gl.uniform3f(this.uWaveColor, cWave[0], cWave[1], cWave[2]);
      gl.uniform3f(this.uCrestColor, cCrest[0], cCrest[1], cCrest[2]);

      gl.uniform1f(this.uSpeed, this.options.speed);
      gl.uniform1f(this.uAmplitude, this.options.amplitude);
      gl.uniform1f(this.uWaveScale, this.options.waveScale);
      gl.uniform1f(this.uWaveRatio, this.options.waveRatio);
      gl.uniform1f(this.uSwell, this.options.swell);
      gl.uniform1f(this.uTurbulence, this.options.turbulence);
      gl.uniform1f(this.uTilt, this.options.tilt);
      gl.uniform1f(this.uZoom, this.options.zoom);
      gl.uniform1f(this.uHeight, this.options.height);
      gl.uniform1f(this.uFogDepth, this.options.fogDepth);
      gl.uniform1f(this.uBrightness, this.options.brightness);
      gl.uniform1f(this.uOpacity, this.options.opacity);
      gl.uniform1f(this.uParallaxStrength, this.options.parallaxStrength);
      gl.uniform1f(this.uGrainIntensity, this.options.grainIntensity);

      if (this.isWebGL2) {
        gl.uniform1i(this.uMouseInteraction, this.options.mouseInteraction ? 1 : 0);
        gl.uniform1i(this.uGrain, this.options.grain ? 1 : 0);
        gl.uniform1i(this.uInvertTop, this.options.invertTop ? 1 : 0);
      } else {
        gl.uniform1i(this.uMouseInteraction, this.options.mouseInteraction ? 1 : 0);
        gl.uniform1i(this.uGrain, this.options.grain ? 1 : 0);
        gl.uniform1i(this.uInvertTop, this.options.invertTop ? 1 : 0);
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

        const grad = ctx.createLinearGradient(0, 0, 0, h);
        grad.addColorStop(0, '#5227FF');
        grad.addColorStop(0.6, '#FF9FFC');
        grad.addColorStop(1, '#FFFFFF');

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

  window.GradientWaves = GradientWaves;

  // Auto-initialize all .gradient-waves-canvas elements
  function initAllGradientWaves() {
    const canvases = document.querySelectorAll('.gradient-waves-canvas, [data-gradient-waves]');
    canvases.forEach(canvas => {
      if (canvas._gradientWavesInstance) return;
      canvas._gradientWavesInstance = new GradientWaves(canvas, {
        horizonColor: canvas.dataset.horizonColor || '#5227FF',
        waveColor: canvas.dataset.waveColor || '#FF9FFC',
        crestColor: canvas.dataset.crestColor || '#FFFFFF',
        speed: parseFloat(canvas.dataset.speed) || 0.4,
        amplitude: parseFloat(canvas.dataset.amplitude) || 2.5,
        waveScale: parseFloat(canvas.dataset.waveScale) || 0.6,
        waveRatio: parseFloat(canvas.dataset.waveRatio) || 0.9,
        swell: parseFloat(canvas.dataset.swell) || 35.0,
        turbulence: parseFloat(canvas.dataset.turbulence) || 20.0,
        tilt: parseFloat(canvas.dataset.tilt) || 1.11,
        zoom: parseFloat(canvas.dataset.zoom) || 1.0,
        height: parseFloat(canvas.dataset.height) || 5.5,
        fogDepth: parseFloat(canvas.dataset.fogDepth) || 15.0,
        detail: canvas.dataset.detail || 'medium',
        brightness: parseFloat(canvas.dataset.brightness) || 1.0,
        opacity: parseFloat(canvas.dataset.opacity) || 1.0,
        mouseInteraction: canvas.dataset.mouseInteraction !== 'false',
        parallaxStrength: parseFloat(canvas.dataset.parallaxStrength) || 0.5,
        grain: canvas.dataset.grain !== 'false',
        grainIntensity: parseFloat(canvas.dataset.grainIntensity) || 0.05,
        invertTop: canvas.dataset.invertTop !== 'false' // Top-down waves
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAllGradientWaves);
  } else {
    initAllGradientWaves();
  }
})();
