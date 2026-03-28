// Post-Processing — WebGL bloom + vignette for visual polish
const PostProcessing = {
    enabled: false,
    _rt1: null,
    _rt2: null,
    _bloomScene: null,
    _bloomCamera: null,
    _bloomMesh: null,
    _compositeMesh: null,
    _compositeScene: null,

    init(renderer) {
        // Only enable on desktop with decent GPU
        const isMobile = /iphone|ipad|android/i.test(navigator.userAgent);
        if (isMobile) return;

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

            this.enabled = true;
        } catch(e) {
            if (GameState.debug) console.warn('[POST] Failed to init post-processing:', e);
            this.enabled = false;
        }
    },

    render(renderer, scene, camera) {
        if (!this.enabled) {
            renderer.render(scene, camera);
            return;
        }

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
    },

    onResize() {
        if (!this.enabled) return;
        const w = window.innerWidth, h = window.innerHeight;
        const scale = 0.5;
        this._rt1.setSize(w * scale, h * scale);
        this._rt2.setSize(w, h);
        this._bloomMesh.material.uniforms.resolution.value.set(w * scale, h * scale);
        this._compositeMesh.material.uniforms.resolution.value.set(w, h);
    }
};
