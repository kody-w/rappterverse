/* ───────────────────────────────────────────────
   warp.js — Hyperspace warp tunnel transition
   Three.js r128 · seededRandom from config.js
   ─────────────────────────────────────────────── */

const Warp = {
    active: false,
    canvas: null,
    ctx: null,
    stars: [],
    progress: 0,
    duration: 1800,
    startTime: 0,
    callback: null,
    animFrameId: null,

    /* ── Initialise 400 stars and begin the tunnel ── */
    start(callback) {
        this.canvas = document.getElementById('warp-canvas');
        this.ctx = this.canvas.getContext('2d');
        this.canvas.width = window.innerWidth;
        this.canvas.height = window.innerHeight;

        const cx = this.canvas.width / 2;
        const cy = this.canvas.height / 2;
        const rng = seededRandom('warp-' + Date.now());

        this.stars = [];
        for (let i = 0; i < 400; i++) {
            this.stars.push({
                x: cx,
                y: cy,
                prevX: cx,
                prevY: cy,
                angle: rng() * Math.PI * 2,
                speed: 2 + rng() * 6,
                z: rng()
            });
        }

        this.progress = 0;
        this.startTime = performance.now();
        this.callback = callback;
        this.active = true;

        const overlay = document.getElementById('warp-overlay');
        if (overlay) overlay.classList.add('active');

        if (typeof Audio !== 'undefined') Audio.playWarp();

        this.animate();
    },

    /* ── Per-frame update ── */
    animate() {
        if (!this.active) return;

        const now = performance.now();
        this.progress = Math.min((now - this.startTime) / this.duration, 1);

        const ctx = this.ctx;
        const w = this.canvas.width;
        const h = this.canvas.height;
        const cx = w / 2;
        const cy = h / 2;

        // Ease-in acceleration curve
        const accel = this.progress * this.progress;

        // Clear to black
        ctx.fillStyle = '#000';
        ctx.fillRect(0, 0, w, h);

        // ── Draw stars ──
        for (let i = 0; i < this.stars.length; i++) {
            const s = this.stars[i];
            s.prevX = s.x;
            s.prevY = s.y;

            const velocity = s.speed * (1 + accel * 12);
            s.x += Math.cos(s.angle) * velocity;
            s.y += Math.sin(s.angle) * velocity;

            const dx = s.x - cx;
            const dy = s.y - cy;
            const dist = Math.sqrt(dx * dx + dy * dy);
            const maxDist = Math.sqrt(cx * cx + cy * cy);

            // Streak line width grows with distance
            const lw = 1 + (dist / maxDist) * 2;

            // Colour: white core → blue at edges
            const blue = Math.min(Math.floor(200 + (dist / maxDist) * 55), 255);
            const green = Math.max(Math.floor(220 - (dist / maxDist) * 180), 40);
            const alpha = Math.min(0.4 + accel * 0.6, 1);
            ctx.strokeStyle = `rgba(${green},${green},${blue},${alpha})`;
            ctx.lineWidth = lw;

            ctx.beginPath();
            ctx.moveTo(s.prevX, s.prevY);
            ctx.lineTo(s.x, s.y);
            ctx.stroke();

            // Reset stars that leave the screen
            if (s.x < -10 || s.x > w + 10 || s.y < -10 || s.y > h + 10) {
                s.x = cx;
                s.y = cy;
                s.prevX = cx;
                s.prevY = cy;
            }
        }

        // ── Centre glow (pulsing) ──
        const pulse = 1 + 0.15 * Math.sin(now * 0.008);
        const glowRadius = (40 + accel * 80) * pulse;
        const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowRadius);
        glow.addColorStop(0, `rgba(255,255,255,${0.6 + accel * 0.4})`);
        glow.addColorStop(0.4, `rgba(180,200,255,${0.3 * accel})`);
        glow.addColorStop(1, 'rgba(100,140,255,0)');
        ctx.fillStyle = glow;
        ctx.fillRect(cx - glowRadius, cy - glowRadius, glowRadius * 2, glowRadius * 2);

        // ── Bright flash at the very end ──
        if (this.progress > 0.85) {
            const flash = (this.progress - 0.85) / 0.15;
            ctx.fillStyle = `rgba(255,255,255,${flash * flash})`;
            ctx.fillRect(0, 0, w, h);
        }

        // ── Done? ──
        if (this.progress >= 1) {
            this.cleanup();
            if (this.callback) this.callback();
            return;
        }

        this.animFrameId = requestAnimationFrame(() => this.animate());
    },

    /* ── Tear down ── */
    cleanup() {
        this.active = false;
        if (this.animFrameId) {
            cancelAnimationFrame(this.animFrameId);
            this.animFrameId = null;
        }
        const overlay = document.getElementById('warp-overlay');
        if (overlay) overlay.classList.remove('active');
    }
};
