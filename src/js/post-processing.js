// Post-Processing — WebGL bloom + vignette for visual polish
const PostProcessing = {
    enabled: false,
    requested: true,
    supported: false,
    ready: false,
    _rt1: null,
    _rt2: null,
    _bloomScene: null,
    _bloomCamera: null,
    _bloomMesh: null,
    _compositeMesh: null,
    _compositeScene: null,
    _renderer: null,
    _initializing: false,

    setEnabled(value) {
        this.requested = value !== false;
        if (!this.requested && this.ready) {
            this._disposeResources();
            this.ready = false;
        }
        if (this.requested && this.supported && !this.ready && this._renderer && !this._initializing) {
            return this.init(this._renderer);
        }
        this.enabled = this.requested && this.supported && this.ready;
        return this.enabled;
    },

    _isConstrainedDevice() {
        const ua = navigator.userAgent || '';
        return /iphone|ipad|ipod|android/i.test(ua) ||
            (/Macintosh/i.test(ua) && navigator.maxTouchPoints > 1);
    },

    init(renderer) {
        this._renderer = renderer;
        this.enabled = false;
        this.ready = false;
        this.supported = !this._isConstrainedDevice();
        if (!this.supported) return false;
        if (!this.requested) return true;
        this._initializing = true;

        const w = window.innerWidth;
        const h = window.innerHeight;
        const scale = 0.5; // Half-res bloom for performance

        try {
            this._rt1 = new THREE.WebGLRenderTarget(w * scale, h * scale, {
                minFilter: THREE.LinearFilter,
                magFilter: THREE.LinearFilter,
                format: THREE.RGBAFormat
            });
            this._rt2 = new THREE.WebGLRenderTarget(w, h, {
                minFilter: THREE.LinearFilter,
                magFilter: THREE.LinearFilter,
                format: THREE.RGBAFormat
            });

            // Bloom extract + blur (simplified single-pass glow)
            this._bloomScene = new THREE.Scene();
            this._bloomCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

            const bloomMat = new THREE.ShaderMaterial({
                uniforms: {
                    tDiffuse: { value: null },
                    resolution: { value: new THREE.Vector2(w * scale, h * scale) },
                    bloomStrength: { value: 0.4 }
                },
                vertexShader: `
                    varying vec2 vUv;
                    void main() { vUv = uv; gl_Position = vec4(position, 1.0); }
                `,
                fragmentShader: `
                    uniform sampler2D tDiffuse;
                    uniform vec2 resolution;
                    uniform float bloomStrength;
                    varying vec2 vUv;
                    void main() {
                        vec2 texel = 1.0 / resolution;
                        vec4 sum = vec4(0.0);
                        // 9-tap gaussian blur
                        sum += texture2D(tDiffuse, vUv + vec2(-4.0, 0.0) * texel) * 0.028;
                        sum += texture2D(tDiffuse, vUv + vec2(-3.0, 0.0) * texel) * 0.054;
                        sum += texture2D(tDiffuse, vUv + vec2(-2.0, 0.0) * texel) * 0.098;
                        sum += texture2D(tDiffuse, vUv + vec2(-1.0, 0.0) * texel) * 0.14;
                        sum += texture2D(tDiffuse, vUv) * 0.16;
                        sum += texture2D(tDiffuse, vUv + vec2(1.0, 0.0) * texel) * 0.14;
                        sum += texture2D(tDiffuse, vUv + vec2(2.0, 0.0) * texel) * 0.098;
                        sum += texture2D(tDiffuse, vUv + vec2(3.0, 0.0) * texel) * 0.054;
                        sum += texture2D(tDiffuse, vUv + vec2(4.0, 0.0) * texel) * 0.028;
                        // Extract bright areas only
                        float brightness = dot(sum.rgb, vec3(0.299, 0.587, 0.114));
                        vec4 bloom = sum * smoothstep(0.4, 0.8, brightness) * bloomStrength;
                        gl_FragColor = bloom;
                    }
                `
            });

            const quadGeo = new THREE.PlaneGeometry(2, 2);
            this._bloomMesh = new THREE.Mesh(quadGeo, bloomMat);
            this._bloomScene.add(this._bloomMesh);

            // Composite: original + bloom + vignette
            this._compositeScene = new THREE.Scene();
            const compositeMat = new THREE.ShaderMaterial({
                uniforms: {
                    tScene: { value: null },
                    tBloom: { value: null },
                    resolution: { value: new THREE.Vector2(w, h) },
                    vignetteStrength: { value: 0.35 }
                },
                vertexShader: `
                    varying vec2 vUv;
                    void main() { vUv = uv; gl_Position = vec4(position, 1.0); }
                `,
                fragmentShader: `
                    uniform sampler2D tScene;
                    uniform sampler2D tBloom;
                    uniform vec2 resolution;
                    uniform float vignetteStrength;
                    varying vec2 vUv;
                    void main() {
                        vec4 scene = texture2D(tScene, vUv);
                        vec4 bloom = texture2D(tBloom, vUv);
                        // Additive bloom
                        vec3 color = scene.rgb + bloom.rgb;
                        // Vignette
                        vec2 uv = vUv * 2.0 - 1.0;
                        float vignette = 1.0 - dot(uv * 0.5, uv * 0.5);
                        vignette = smoothstep(0.0, 1.0, vignette);
                        color *= mix(1.0 - vignetteStrength, 1.0, vignette);
                        // Subtle film grain
                        float grain = (fract(sin(dot(vUv * resolution, vec2(12.9898, 78.233))) * 43758.5453) - 0.5) * 0.02;
                        color += grain;
                        gl_FragColor = vec4(color, 1.0);
                    }
                `
            });
            this._compositeMesh = new THREE.Mesh(quadGeo.clone(), compositeMat);
            this._compositeScene.add(this._compositeMesh);

            this.ready = true;
            this._initializing = false;
            this.setEnabled(this.requested);
            return true;
        } catch(e) {
            if (GameState.debug) console.warn('[POST] Failed to init post-processing:', e);
            this._disposeResources();
            this.supported = false;
            this.ready = false;
            this.enabled = false;
            this._initializing = false;
            return false;
        }
    },

    render(renderer, scene, camera) {
        if (!this.enabled || !this.ready || !this._rt1 || !this._rt2 ||
            !this._bloomMesh || !this._compositeMesh || !this._bloomScene ||
            !this._compositeScene || !this._bloomCamera) {
            renderer.render(scene, camera);
            return;
        }

        try {
            // Echo-reactive shader parameters
            this._updateEchoUniforms();

            // 1. Render scene to RT2 (full res)
            renderer.setRenderTarget(this._rt2);
            renderer.render(scene, camera);

            // 2. Bloom pass: render RT2 through bloom shader to RT1
            this._bloomMesh.material.uniforms.tDiffuse.value = this._rt2.texture;
            renderer.setRenderTarget(this._rt1);
            renderer.render(this._bloomScene, this._bloomCamera);

            // 3. Composite: combine RT2 (scene) + RT1 (bloom) to screen
            this._compositeMesh.material.uniforms.tScene.value = this._rt2.texture;
            this._compositeMesh.material.uniforms.tBloom.value = this._rt1.texture;
            renderer.setRenderTarget(null);
            renderer.render(this._compositeScene, this._bloomCamera);
        } catch(e) {
            this.enabled = false;
            try { renderer.setRenderTarget(null); } catch(_) {}
            renderer.render(scene, camera);
            if (GameState.debug) console.warn('[POST] Disabled after render failure:', e);
        }
    },

    _updateEchoUniforms() {
        if (!this.ready || !this._bloomMesh || !this._compositeMesh) return;
        if (typeof EchoEngine === 'undefined') return;
        var ef = EchoEngine.getCurrentFrame();
        if (!ef || !ef.echoes || !ef.echoes.L3) return;
        var L3 = ef.echoes.L3;

        // Bloom: brighter during tension (combat glow), dimmer when calm
        var targetBloom = Math.min(0.9, 0.3 + L3.tension * 0.5 + L3.vitality * 0.1);
        var currentBloom = this._bloomMesh.material.uniforms.bloomStrength.value;
        this._bloomMesh.material.uniforms.bloomStrength.value = currentBloom + (targetBloom - currentBloom) * 0.03;

        // Vignette: tighter when tense, relaxed when calm
        var targetVignette = Math.min(0.6, 0.2 + L3.tension * 0.4);
        var currentVignette = this._compositeMesh.material.uniforms.vignetteStrength.value;
        this._compositeMesh.material.uniforms.vignetteStrength.value = currentVignette + (targetVignette - currentVignette) * 0.03;
    },

    onResize() {
        if (!this.ready || !this._rt1 || !this._rt2 || !this._bloomMesh || !this._compositeMesh) return;
        const w = window.innerWidth, h = window.innerHeight;
        const scale = 0.5;
        this._rt1.setSize(w * scale, h * scale);
        this._rt2.setSize(w, h);
        this._bloomMesh.material.uniforms.resolution.value.set(w * scale, h * scale);
        this._compositeMesh.material.uniforms.resolution.value.set(w, h);
    },

    _disposeResources() {
        [this._rt1, this._rt2].forEach(function(target) {
            if (target && target.dispose) target.dispose();
        });
        [this._bloomMesh, this._compositeMesh].forEach(function(mesh) {
            if (!mesh) return;
            if (mesh.geometry && mesh.geometry.dispose) mesh.geometry.dispose();
            if (mesh.material && mesh.material.dispose) mesh.material.dispose();
        });
        this._rt1 = null;
        this._rt2 = null;
        this._bloomScene = null;
        this._bloomCamera = null;
        this._bloomMesh = null;
        this._compositeMesh = null;
        this._compositeScene = null;
    }
};
