// Fog of War — vision system with wards
const FogOfWar = {
    _mesh: null,
    _canvas: null,
    _ctx: null,
    _tex: null,
    _wards: [],
    _visionRadius: 25,
    _wardRadius: 20,
    _wardDuration: 60,
    _size: 256,
    _scene: null,
    _bounds: null,
    enabled: true,

    init(scene, w) {
        this._scene = scene;
        this._bounds = w.bounds;
        this._wards = [];

        // Create fog plane covering the world
        var worldSize = Math.max(w.bounds.x, w.bounds.z) * 2 + 10;
        this._canvas = document.createElement('canvas');
        this._canvas.width = this._size;
        this._canvas.height = this._size;
        this._ctx = this._canvas.getContext('2d');
        this._tex = new THREE.CanvasTexture(this._canvas);
        this._tex.minFilter = THREE.LinearFilter;

        var geo = new THREE.PlaneGeometry(worldSize, worldSize);
        var mat = new THREE.MeshBasicMaterial({
            map: this._tex, transparent: true, side: THREE.DoubleSide,
            depthWrite: false
        });
        this._mesh = new THREE.Mesh(geo, mat);
        this._mesh.rotation.x = -Math.PI / 2;
        this._mesh.position.y = 0.5;
        scene.add(this._mesh);
    },

    update(playerPos) {
        if (!this.enabled || !this._ctx) return;
        var ctx = this._ctx;
        var S = this._size;
        var bx = this._bounds.x, bz = this._bounds.z;
        var maxB = Math.max(bx, bz) + 5;

        // Fill with fog (dark)
        ctx.fillStyle = 'rgba(5, 5, 16, 0.65)';
        ctx.fillRect(0, 0, S, S);

        // Clear vision circles (erase fog)
        ctx.globalCompositeOperation = 'destination-out';

        // Player vision
        if (playerPos) {
            var px = (playerPos.x / maxB + 1) * 0.5 * S;
            var pz = (playerPos.z / maxB + 1) * 0.5 * S;
            var vr = (this._visionRadius / maxB) * 0.5 * S;
            var grad = ctx.createRadialGradient(px, pz, 0, px, pz, vr);
            grad.addColorStop(0, 'rgba(0,0,0,1)');
            grad.addColorStop(0.7, 'rgba(0,0,0,0.8)');
            grad.addColorStop(1, 'rgba(0,0,0,0)');
            ctx.fillStyle = grad;
            ctx.fillRect(0, 0, S, S);
        }

        // Tower vision
        if (typeof WorldLanes !== 'undefined') {
            WorldLanes.towers.forEach(function(t) {
                if (t.hp <= 0 || t.faction !== 'explorer') return;
                var tx = (t.mesh.position.x / maxB + 1) * 0.5 * S;
                var tz = (t.mesh.position.z / maxB + 1) * 0.5 * S;
                var tr = (12 / maxB) * 0.5 * S;
                var grad = ctx.createRadialGradient(tx, tz, 0, tx, tz, tr);
                grad.addColorStop(0, 'rgba(0,0,0,0.9)');
                grad.addColorStop(1, 'rgba(0,0,0,0)');
                ctx.fillStyle = grad;
                ctx.fillRect(0, 0, S, S);
            });
        }

        // Ward vision
        var now = Date.now();
        var self = this;
        this._wards = this._wards.filter(function(w) {
            var elapsed = (now - w.placed) / 1000;
            if (elapsed > w.duration) {
                if (w.mesh && w.mesh.parent) w.mesh.parent.remove(w.mesh);
                return false;
            }
            var wx = (w.x / maxB + 1) * 0.5 * S;
            var wz = (w.z / maxB + 1) * 0.5 * S;
            var wr = (self._wardRadius / maxB) * 0.5 * S;
            var fade = elapsed > w.duration - 10 ? (w.duration - elapsed) / 10 : 1;
            var grad = ctx.createRadialGradient(wx, wz, 0, wx, wz, wr);
            grad.addColorStop(0, 'rgba(0,0,0,' + (0.8 * fade) + ')');
            grad.addColorStop(1, 'rgba(0,0,0,0)');
            ctx.fillStyle = grad;
            ctx.fillRect(0, 0, S, S);
            return true;
        });

        ctx.globalCompositeOperation = 'source-over';
        this._tex.needsUpdate = true;
    },

    placeWard() {
        if (typeof WorldMode === 'undefined' || !WorldMode.player) return;
        var p = WorldMode.player.mesh.position;
        var ward = {
            x: p.x, z: p.z,
            placed: Date.now(),
            duration: this._wardDuration,
            mesh: null
        };

        // Visual ward marker
        var g = new THREE.Group();
        var eye = new THREE.Mesh(
            new THREE.SphereGeometry(0.3, 8, 6),
            new THREE.MeshStandardMaterial({
                color: 0x00d4ff, emissive: 0x00d4ff, emissiveIntensity: 0.5,
                transparent: true, opacity: 0.6
            })
        );
        eye.position.y = 0.5;
        g.add(eye);
        var ring = new THREE.Mesh(
            new THREE.RingGeometry(0.5, 0.7, 12),
            new THREE.MeshBasicMaterial({ color: 0x00d4ff, side: THREE.DoubleSide, transparent: true, opacity: 0.3 })
        );
        ring.rotation.x = -Math.PI / 2;
        ring.position.y = 0.02;
        g.add(ring);
        g.position.set(p.x, 0, p.z);
        if (this._scene) this._scene.add(g);
        ward.mesh = g;

        this._wards.push(ward);
        if (typeof HUD !== 'undefined') HUD.showToast('Ward placed — reveals area for ' + this._wardDuration + 's');
    },

    cleanup() {
        if (this._mesh && this._mesh.parent) this._mesh.parent.remove(this._mesh);
        this._wards.forEach(function(w) {
            if (w.mesh && w.mesh.parent) w.mesh.parent.remove(w.mesh);
        });
        this._wards = [];
        this._mesh = null;
    }
};
