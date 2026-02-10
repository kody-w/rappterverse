// equipment.js — Equipment / Gear system

const EQUIPMENT_SLOTS = {
    weapon:    { name: 'Weapon',    icon: 'W', statKey: 'damage' },
    armor:     { name: 'Armor',     icon: 'A', statKey: 'defense' },
    accessory: { name: 'Accessory', icon: 'R', statKey: 'special' }
};

const EQUIPMENT_MAP = {
    'Scrap Metal':    { slot: 'armor',     stats: { defense: 3 } },
    'Power Cell':     { slot: 'accessory', stats: { energyRegen: 0.5 } },
    'Frost Blade':    { slot: 'weapon',    stats: { damage: 8,  element: 'ice' } },
    'Magma Sword':    { slot: 'weapon',    stats: { damage: 10, element: 'fire' } },
    'Void Dagger':    { slot: 'weapon',    stats: { damage: 12, element: 'void' } },
    'Star Blade':     { slot: 'weapon',    stats: { damage: 18, element: 'cosmic', critChance: 0.1 } },
    'Guardian Plate': { slot: 'armor',     stats: { defense: 12, maxHpBonus: 30 } },
    'Nano Armor':     { slot: 'armor',     stats: { defense: 8,  hpRegen: 1 } },
    'Berserker Badge':{ slot: 'accessory', stats: { damage: 8, attackSpeed: 1.2 } },
    'Vampiric Fang':  { slot: 'accessory', stats: { damage: 5, lifesteal: 0.12 } },
    'Swift Boots':    { slot: 'accessory', stats: { moveSpeed: 1.15, dodgeChance: 0.08 } }
};

const Equipment = {
    gear: { weapon: null, armor: null, accessory: null },
    panel: null,

    init() {
        this.gear = { weapon: null, armor: null, accessory: null };
        this.panel = document.getElementById('equipment-panel');
        this.updateUI();
    },

    isEquippable(itemName) {
        return itemName in EQUIPMENT_MAP;
    },

    equipItem(itemName) {
        const entry = EQUIPMENT_MAP[itemName];
        if (!entry) return null;
        const slot = entry.slot;
        const displaced = this.gear[slot] ? this.gear[slot].name : null;
        this.gear[slot] = { name: itemName, stats: Object.assign({}, entry.stats) };
        this.updateUI();
        if (typeof Audio !== 'undefined') Audio.playClick();
        return displaced;
    },

    unequipItem(slot) {
        if (!this.gear[slot]) return null;
        const name = this.gear[slot].name;
        this.gear[slot] = null;
        this.updateUI();
        return name;
    },

    getStats() {
        const additive = ['damage', 'defense', 'maxHpBonus', 'critChance',
                          'dodgeChance', 'lifesteal', 'energyRegen', 'hpRegen'];
        const multiplicative = ['attackSpeed', 'moveSpeed'];
        const out = {};
        additive.forEach(k => { out[k] = 0; });
        multiplicative.forEach(k => { out[k] = 1; });

        for (const slot of Object.keys(this.gear)) {
            const item = this.gear[slot];
            if (!item) continue;
            for (const [k, v] of Object.entries(item.stats)) {
                if (k === 'element') continue;
                if (multiplicative.includes(k)) out[k] *= v;
                else out[k] = (out[k] || 0) + v;
            }
        }
        return out;
    },

    getEquippedElement() {
        const w = this.gear.weapon;
        return w && w.stats.element ? w.stats.element : null;
    },

    toggle() {
        if (!this.panel) this.panel = document.getElementById('equipment-panel');
        if (!this.panel) return;
        this.panel.classList.toggle('visible');
        this.updateUI();
    },

    updateUI() {
        if (!this.panel) this.panel = document.getElementById('equipment-panel');
        if (!this.panel) return;

        let html = '<div class="equip-title">EQUIPMENT</div><div class="equip-slots">';
        for (const [slot, meta] of Object.entries(EQUIPMENT_SLOTS)) {
            const item = this.gear[slot];
            const equipped = item ? ' equipped' : '';
            html += `<div class="equip-slot${equipped}">`;
            html += `<span class="equip-label">[${meta.icon}] ${meta.name}</span>`;
            if (item) {
                html += `<span class="equip-name">${item.name}</span>`;
                const statStr = Object.entries(item.stats)
                    .filter(([k]) => k !== 'element')
                    .map(([k, v]) => `${k}: ${v}`)
                    .join(', ');
                if (statStr) html += `<span class="equip-stats">${statStr}</span>`;
                if (item.stats.element) html += `<span class="equip-element">${item.stats.element}</span>`;
            } else {
                html += '<span class="equip-empty">Empty</span>';
            }
            html += '</div>';
        }
        html += '</div>';

        // Aggregated stats
        const stats = this.getStats();
        html += '<div class="equip-summary">';
        if (stats.damage)    html += `<span class="equip-stat-line bold">DMG ${stats.damage}</span>`;
        if (stats.defense)   html += `<span class="equip-stat-line bold">DEF ${stats.defense}</span>`;
        if (stats.maxHpBonus)  html += `<span class="equip-stat-line">HP+ ${stats.maxHpBonus}</span>`;
        if (stats.critChance)  html += `<span class="equip-stat-line">Crit ${(stats.critChance * 100).toFixed(0)}%</span>`;
        if (stats.dodgeChance) html += `<span class="equip-stat-line">Dodge ${(stats.dodgeChance * 100).toFixed(0)}%</span>`;
        if (stats.lifesteal)   html += `<span class="equip-stat-line">Steal ${(stats.lifesteal * 100).toFixed(0)}%</span>`;
        if (stats.attackSpeed !== 1) html += `<span class="equip-stat-line">ASpd x${stats.attackSpeed.toFixed(2)}</span>`;
        if (stats.moveSpeed !== 1)   html += `<span class="equip-stat-line">MSpd x${stats.moveSpeed.toFixed(2)}</span>`;
        if (stats.energyRegen)  html += `<span class="equip-stat-line">E.Regen ${stats.energyRegen}/s</span>`;
        if (stats.hpRegen)      html += `<span class="equip-stat-line">HP.Regen ${stats.hpRegen}/s</span>`;
        const el = this.getEquippedElement();
        if (el) html += `<span class="equip-stat-line element">Element: ${el}</span>`;
        html += '</div>';

        this.panel.innerHTML = html;
    },

    cleanup() {
        this.gear = { weapon: null, armor: null, accessory: null };
        if (this.panel) {
            this.panel.classList.remove('visible');
            this.panel.innerHTML = '';
        }
    }
};
