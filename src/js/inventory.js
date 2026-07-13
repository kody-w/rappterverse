// inventory.js — Combo tracker & Inventory system

const ComboSystem = {
    count: 0,
    timer: 0,
    timeout: 3,
    killStreak: 0,
    bestStreak: 0,

    _streakAnnouncements: {
        3: 'KILLING SPREE',
        5: 'RAMPAGE',
        7: 'DOMINATING',
        10: 'UNSTOPPABLE',
        15: 'GODLIKE',
        20: 'BEYOND GODLIKE'
    },

    registerKill() {
        this.count++;
        this.killStreak++;
        this.timer = this.timeout;
        if (this.killStreak > this.bestStreak) this.bestStreak = this.killStreak;
        this.updateDisplay();
        if (typeof Audio !== 'undefined') Audio.playClick();

        // Kill streak announcer
        var announcement = this._streakAnnouncements[this.killStreak];
        if (announcement) {
            this._showStreakBanner(announcement, this.killStreak);
        }

        // Escalating VFX for combo chains
        if (typeof VFX !== 'undefined' && typeof WorldMode !== 'undefined' && WorldMode.player) {
            var pos = WorldMode.player.mesh.position;
            if (this.count >= 10) {
                VFX.burst(pos, 'novaBlast', { count: 20 });
                VFX.screenFlash('#ffd700', 0.3);
            } else if (this.count >= 5) {
                VFX.burst(pos, 'levelUp', { count: 12 });
                VFX.screenFlash('#00ffff', 0.2);
            } else if (this.count >= 3) {
                VFX.burst(pos, 'goldPickup', { count: 6 });
            }
        }
        // Gamepad rumble on streak milestones
        if (announcement && typeof GamepadControls !== 'undefined' && GamepadControls.rumble) {
            GamepadControls.rumble(0.6, 0.3, 200);
        }
    },

    _streakBannerEl: null,
    _streakFadeTimeout: null,

    _showStreakBanner(text, streak) {
        var overlay = this._streakBannerEl;
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.style.cssText = 'position:fixed;top:25%;left:50%;transform:translateX(-50%);z-index:8600;pointer-events:none;opacity:0;transition:opacity 0.3s;';
            document.body.appendChild(overlay);
            this._streakBannerEl = overlay;
        }
        var color = streak >= 15 ? '#ffd700' : streak >= 10 ? '#ff4444' : streak >= 7 ? '#aa44ff' : '#00ffff';
        var fontSize = Math.min(60, 24 + streak);
        overlay.innerHTML = '<div style="font-family:monospace;font-size:' + fontSize + 'px;font-weight:bold;color:' + color + ';letter-spacing:4px;text-shadow:0 0 20px ' + color + ',0 0 40px ' + color + ';text-transform:uppercase;">' + text + '</div>' +
            '<div style="font-family:monospace;font-size:14px;color:rgba(255,255,255,0.5);text-align:center;margin-top:4px;">' + streak + ' KILL STREAK</div>';
        // Clear any pending fade so re-trigger resets the timer
        if (this._streakFadeTimeout) clearTimeout(this._streakFadeTimeout);
        overlay.style.opacity = '1';
        var self = this;
        this._streakFadeTimeout = setTimeout(function() {
            overlay.style.opacity = '0';
            self._streakFadeTimeout = null;
        }, 2000);
        // Log for replay
        if (typeof ReplaySystem !== 'undefined') ReplaySystem.logEvent('streak', { text: text, streak: streak });
    },

    getMultiplier() {
        if (this.count >= 10) return 2.0;
        if (this.count >= 5) return 1.5;
        if (this.count >= 3) return 1.25;
        return 1.0;
    },

    getGrade() {
        if (this.count >= 20) return 'SSS';
        if (this.count >= 15) return 'SS';
        if (this.count >= 10) return 'S';
        if (this.count >= 7) return 'A';
        if (this.count >= 5) return 'B';
        if (this.count >= 3) return 'C';
        return 'D';
    },

    update(delta) {
        if (this.count > 0) {
            this.timer -= delta;
            if (this.timer <= 0) {
                this.count = 0;
                this.killStreak = 0;
                this.updateDisplay();
            }
        }
    },

    updateDisplay() {
        const el = document.getElementById('combo-display');
        if (!el) return;
        if (this.count >= 2) {
            el.style.display = 'flex';
            document.getElementById('combo-count').textContent = this.count;
            document.getElementById('combo-grade').textContent = this.getGrade();
            document.getElementById('combo-multiplier').textContent = `x${this.getMultiplier().toFixed(2)}`;
        } else {
            el.style.display = 'none';
        }
    },

    reset() {
        this.count = 0;
        this.timer = 0;
        this.killStreak = 0;
        this.updateDisplay();
    }
};

// ---------------------------------------------------------------------------

const Inventory = {
    slots: [],
    maxSlots: 16,
    open: false,
    droppedItems: [],

    ITEMS: {
        health_potion: { id: 'health_potion', name: 'Health Potion', icon: '❤️', stackable: true, maxStack: 10, dropWeight: 30 },
        mana_crystal:  { id: 'mana_crystal',  name: 'Mana Crystal',  icon: '💎', stackable: true, maxStack: 10, dropWeight: 25 },
        scrap_metal:   { id: 'scrap_metal',   name: 'Scrap Metal',   icon: '⚙️', stackable: false, maxStack: 1, dropWeight: 12 },
        power_cell:    { id: 'power_cell',    name: 'Power Cell',    icon: '🔋', stackable: false, maxStack: 1, dropWeight: 8 },
        frost_blade:   { id: 'frost_blade',   name: 'Frost Blade',   icon: '🗡️', stackable: false, maxStack: 1, dropWeight: 5 },
        magma_sword:   { id: 'magma_sword',   name: 'Magma Sword',   icon: '🗡️', stackable: false, maxStack: 1, dropWeight: 4 },
        void_dagger:   { id: 'void_dagger',   name: 'Void Dagger',   icon: '🗡️', stackable: false, maxStack: 1, dropWeight: 3 },
        star_blade:    { id: 'star_blade',    name: 'Star Blade',    icon: '🗡️', stackable: false, maxStack: 1, dropWeight: 1 },
        guardian_plate: { id: 'guardian_plate', name: 'Guardian Plate', icon: '🛡️', stackable: false, maxStack: 1, dropWeight: 4 },
        nano_armor:    { id: 'nano_armor',    name: 'Nano Armor',    icon: '🛡️', stackable: false, maxStack: 1, dropWeight: 4 },
        berserker_badge: { id: 'berserker_badge', name: 'Berserker Badge', icon: '🏅', stackable: false, maxStack: 1, dropWeight: 3 },
        vampiric_fang: { id: 'vampiric_fang', name: 'Vampiric Fang', icon: '🦷', stackable: false, maxStack: 1, dropWeight: 3 },
        swift_boots:   { id: 'swift_boots',   name: 'Swift Boots',   icon: '👢', stackable: false, maxStack: 1, dropWeight: 3 },
    },

    init() {
        this.slots = [];
        for (let i = 0; i < this.maxSlots; i++) this.slots.push({ item: null });
        this.open = false;
        this.droppedItems = [];
        this.renderGrid();
    },

    toggle() {
        this.open = !this.open;
        const panel = document.getElementById('inventory-panel');
        if (panel) panel.style.display = this.open ? 'block' : 'none';
        this.renderGrid();
    },

    addItem(itemId) {
        const template = this.ITEMS[itemId];
        if (!template) return false;

        // Try stacking first
        if (template.stackable) {
            for (const slot of this.slots) {
                if (slot.item && slot.item.id === itemId && slot.item.count < template.maxStack) {
                    slot.item.count++;
                    this._onAdd(template);
                    return true;
                }
            }
        }

        // Find empty slot
        for (const slot of this.slots) {
            if (!slot.item) {
                slot.item = { id: template.id, name: template.name, icon: template.icon,
                              count: 1, stackable: template.stackable, maxStack: template.maxStack };
                this._onAdd(template);
                return true;
            }
        }
        if (typeof HUD !== 'undefined') HUD.showToast('Inventory full!');
        return false;
    },

    _onAdd(template) {
        this.renderGrid();
        if (typeof Audio !== 'undefined') Audio.playClick();
        if (typeof HUD !== 'undefined') HUD.showToast(`+1 ${template.icon} ${template.name}`);
    },

    useItem(slotIndex) {
        const slot = this.slots[slotIndex];
        if (!slot || !slot.item) return;
        const id = slot.item.id;

        if (id === 'health_potion') {
            if (typeof PlayerStats !== 'undefined') PlayerStats.heal(30);
            if (typeof HUD !== 'undefined') HUD.showToast('Healed +30 HP');
            this.removeItem(slotIndex);
        } else if (id === 'mana_crystal') {
            if (typeof PlayerStats !== 'undefined') PlayerStats.restoreMp(20);
            if (typeof HUD !== 'undefined') HUD.showToast('Restored +20 MP');
            this.removeItem(slotIndex);
        } else if (typeof Equipment !== 'undefined' && Equipment.isEquippable(slot.item.name)) {
            const displaced = Equipment.equipItem(slot.item.name);
            this.removeItem(slotIndex);
            if (displaced) this.addItem(this._nameToId(displaced));
            if (typeof HUD !== 'undefined') HUD.showToast(`Equipped ${slot.item ? slot.item.name : 'item'}`);
        } else {
            if (typeof HUD !== 'undefined') HUD.showToast('Used for crafting');
        }
        this.renderGrid();
        if (typeof Audio !== 'undefined') Audio.playClick();
    },

    _nameToId(name) {
        for (const [id, item] of Object.entries(this.ITEMS)) {
            if (item.name === name) return id;
        }
        return null;
    },

    removeItem(slotIndex, count) {
        count = count || 1;
        const slot = this.slots[slotIndex];
        if (!slot || !slot.item) return;
        slot.item.count -= count;
        if (slot.item.count <= 0) slot.item = null;
    },

    renderGrid() {
        const grid = document.getElementById('inventory-grid');
        if (!grid) return;
        grid.innerHTML = '';
        for (let i = 0; i < this.maxSlots; i++) {
            const div = document.createElement('div');
            div.className = 'inventory-slot';
            const it = this.slots[i] && this.slots[i].item;
            if (it) {
                div.innerHTML = `<span class="inv-icon">${escapeHTML(it.icon)}</span>` +
                    (it.count > 1 ? `<span class="inv-count">${escapeHTML(it.count)}</span>` : '');
                div.onclick = () => this.useItem(i);
            }
            grid.appendChild(div);
        }
    },

    _echoDropBoost() {
        // Echo L3: tension affects drop quality
        if (typeof EchoEngine === "undefined") return 1;
        var f = EchoEngine.getCurrentFrame();
        if (!f || !f.echoes || !f.echoes.L3) return 1;
        return 1 + f.echoes.L3.tension * 0.5; // up to 50% better drops during high tension
    },

    spawnDrop(position, worldId, waveNumber, creepIndex) {
        const rng = seededRandom(worldId * 10000 + waveNumber * 100 + creepIndex);
        if (rng() < 0.3) return; // 30% chance no drop

        // Weighted selection
        const entries = Object.values(this.ITEMS);
        const totalW = entries.reduce((s, e) => s + e.dropWeight, 0);
        let roll = rng() * totalW, picked = entries[0];
        for (const e of entries) { roll -= e.dropWeight; if (roll <= 0) { picked = e; break; } }

        if (typeof THREE === 'undefined') return;
        const colors = {
            health_potion: 0xff4444, mana_crystal: 0x4488ff, scrap_metal: 0x888888, power_cell: 0x44ff44,
            frost_blade: 0x88ccff, magma_sword: 0xff4400, void_dagger: 0x8800ff, star_blade: 0xffd700,
            guardian_plate: 0x4488aa, nano_armor: 0x44cc88, berserker_badge: 0xff6622, vampiric_fang: 0xcc0044, swift_boots: 0x66aaff
        };
        const geo = new THREE.BoxGeometry(0.4, 0.4, 0.4);
        const mat = new THREE.MeshStandardMaterial({ color: colors[picked.id] || 0xffffff, emissive: colors[picked.id] || 0xffffff, emissiveIntensity: 0.5 });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set(position.x, position.y + 0.5, position.z);
        mesh.userData = { baseY: position.y + 0.5, time: 0 };

        if (typeof WorldCombat !== 'undefined' && WorldCombat.scene) WorldCombat.scene.add(mesh);
        this.droppedItems.push({ mesh, item: picked, position: mesh.position.clone() });
    },

    collectNearby(playerPos) {
        for (let i = this.droppedItems.length - 1; i >= 0; i--) {
            const d = this.droppedItems[i];
            const dx = d.mesh.position.x - playerPos.x;
            const dz = d.mesh.position.z - playerPos.z;
            if (dx * dx + dz * dz < 25) { // within 5 units
                if (this.addItem(d.item.id)) {
                    if (typeof VFX !== 'undefined') VFX.burst(d.mesh.position, 'goldPickup');
                    if (d.mesh.parent) d.mesh.parent.remove(d.mesh);
                    this.droppedItems.splice(i, 1);
                }
            }
        }
    },

    updateDrops(delta) {
        for (const d of this.droppedItems) {
            d.mesh.userData.time += delta;
            d.mesh.rotation.y += delta * 1.5;
            d.mesh.position.y = d.mesh.userData.baseY + Math.sin(d.mesh.userData.time * 2) * 0.15;
        }
    },

    cleanup() {
        for (const d of this.droppedItems) {
            if (d.mesh.parent) d.mesh.parent.remove(d.mesh);
            if (d.mesh.geometry) d.mesh.geometry.dispose();
            if (d.mesh.material) {
                if (Array.isArray(d.mesh.material)) d.mesh.material.forEach(m => m.dispose());
                else d.mesh.material.dispose();
            }
        }
        this.droppedItems = [];
        this.slots = [];
        this.open = false;
        const panel = document.getElementById('inventory-panel');
        if (panel) panel.style.display = 'none';
    }
};
