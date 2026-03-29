// Crafting System — combine materials into equipment
const Crafting = {
    _open: false,
    _recipes: [
        { name: 'Iron Blade', materials: { 'Scrap Metal': 3 }, result: { type: 'weapon', name: 'Iron Blade', damage: 8, rarity: 'common' }, gold: 20 },
        { name: 'Steel Shield', materials: { 'Scrap Metal': 2, 'Power Cell': 1 }, result: { type: 'armor', name: 'Steel Shield', defense: 5, rarity: 'common' }, gold: 30 },
        { name: 'Plasma Edge', materials: { 'Power Cell': 3 }, result: { type: 'weapon', name: 'Plasma Edge', damage: 15, element: 'fire', rarity: 'rare' }, gold: 80 },
        { name: 'Nano Vest', materials: { 'Scrap Metal': 2, 'Power Cell': 2 }, result: { type: 'armor', name: 'Nano Vest', defense: 10, rarity: 'rare' }, gold: 100 },
        { name: 'Void Reaper', materials: { 'Power Cell': 5, 'Scrap Metal': 3 }, result: { type: 'weapon', name: 'Void Reaper', damage: 25, element: 'void', rarity: 'epic' }, gold: 200 },
    ],

    // Echo-only recipes — only available during specific echo conditions
    _echoRecipes: [
        { name: 'Echo Blade', materials: { 'Power Cell': 2 }, result: { type: 'weapon', name: 'Echo Blade', damage: 20, element: 'cosmic', rarity: 'epic' }, gold: 100, condition: function(L3) { return L3.tension > 0.5; }, conditionLabel: 'Tension > 50%' },
        { name: 'Harmony Shield', materials: { 'Scrap Metal': 2 }, result: { type: 'armor', name: 'Harmony Shield', defense: 15, rarity: 'epic' }, gold: 80, condition: function(L3) { return L3.socialEnergy > 0.5; }, conditionLabel: 'Social > 50%' },
        { name: 'Vitality Core', materials: { 'Power Cell': 1, 'Scrap Metal': 1 }, result: { type: 'accessory', name: 'Vitality Core', rarity: 'epic' }, gold: 60, condition: function(L3) { return L3.vitality > 0.6; }, conditionLabel: 'Vitality > 60%' },
    ],

    toggle() {
        this._open = !this._open;
        if (this._open) this._show();
        else this._hide();
    },

    _show() {
        var el = document.getElementById('crafting-panel');
        if (!el) this._create();
        el = document.getElementById('crafting-panel');
        if (el) el.style.display = 'block';
        this._render();
        if (typeof Audio !== 'undefined' && Audio.playMenuOpen) Audio.playMenuOpen();
    },

    _hide() {
        var el = document.getElementById('crafting-panel');
        if (el) el.style.display = 'none';
    },

    _create() {
        var el = document.createElement('div');
        el.id = 'crafting-panel';
        el.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);width:360px;max-height:80vh;background:rgba(22,27,34,0.95);border:1px solid rgba(48,54,61,0.8);border-radius:12px;z-index:9100;overflow:hidden;display:none;font-family:"SF Mono",monospace;backdrop-filter:blur(12px);';
        el.innerHTML = '<div style="padding:12px 16px;border-bottom:1px solid rgba(48,54,61,0.5);display:flex;justify-content:space-between;align-items:center;"><span style="font-size:12px;font-weight:700;letter-spacing:2px;color:#d29922;">CRAFTING</span><button id="crafting-close" style="background:none;border:none;color:#8b949e;font-size:18px;cursor:pointer;">&times;</button></div><div id="crafting-recipes" style="padding:10px 16px;overflow-y:auto;max-height:60vh;"></div>';
        document.body.appendChild(el);
        document.getElementById('crafting-close').addEventListener('click', function() { Crafting.toggle(); });

        var style = document.createElement('style');
        style.textContent = '.craft-recipe{padding:10px;margin-bottom:8px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:8px;}.craft-recipe:hover{border-color:rgba(210,153,34,0.3);}.craft-name{font-size:12px;font-weight:600;color:#e6edf3;margin-bottom:4px;}.craft-mats{font-size:10px;color:#8b949e;margin-bottom:4px;}.craft-result{font-size:10px;color:#d29922;}.craft-btn{background:rgba(210,153,34,0.15);border:1px solid rgba(210,153,34,0.3);color:#d29922;padding:4px 12px;font:inherit;font-size:10px;border-radius:4px;cursor:pointer;letter-spacing:1px;margin-top:4px;}.craft-btn:hover{background:rgba(210,153,34,0.25);}.craft-btn:disabled{opacity:0.3;cursor:default;}';
        document.head.appendChild(style);
    },

    _render() {
        var el = document.getElementById('crafting-recipes');
        if (!el) return;
        var inv = typeof Inventory !== 'undefined' ? Inventory : null;
        var gold = typeof PlayerStats !== 'undefined' ? PlayerStats.gold : 0;

        // Get echo state for conditional recipes
        var echoL3 = null;
        if (typeof EchoEngine !== 'undefined') {
            var ef = EchoEngine.getCurrentFrame();
            if (ef && ef.echoes && ef.echoes.L3) echoL3 = ef.echoes.L3;
        }

        // Combine base + available echo recipes
        var allRecipes = this._recipes.slice();
        if (echoL3) {
            this._echoRecipes.forEach(function(er) {
                if (er.condition(echoL3)) {
                    allRecipes.push(Object.assign({}, er, { _echo: true }));
                }
            });
        }

        el.innerHTML = allRecipes.map(function(r, i) {
            var canCraft = true;
            var matList = Object.entries(r.materials).map(function(entry) {
                var name = entry[0], need = entry[1];
                var have = inv ? (inv.items || []).filter(function(item) { return item && item.name === name; }).length : 0;
                if (have < need) canCraft = false;
                return '<span style="color:' + (have >= need ? '#3fb950' : '#f85149') + '">' + name + ' ' + have + '/' + need + '</span>';
            }).join(' · ');
            if (gold < r.gold) canCraft = false;

            var rarityColor = r.result.rarity === 'epic' ? '#a78bfa' : r.result.rarity === 'rare' ? '#58a6ff' : '#8b949e';
            var echoBadge = r._echo ? '<span style="color:#d29922;font-size:9px;margin-left:6px;letter-spacing:1px;">ECHO</span>' : '';
            return '<div class="craft-recipe"' + (r._echo ? ' style="border-color:rgba(210,153,34,0.3);background:rgba(210,153,34,0.05);"' : '') + '>' +
                '<div class="craft-name" style="color:' + rarityColor + '">' + r.name + echoBadge + '</div>' +
                '<div class="craft-mats">' + matList + ' · <span style="color:' + (gold >= r.gold ? '#fbbf24' : '#f85149') + '">' + r.gold + 'G</span></div>' +
                '<div class="craft-result">+' + (r.result.damage ? r.result.damage + ' DMG' : r.result.defense + ' DEF') + (r.result.element ? ' [' + r.result.element + ']' : '') + '</div>' +
                '<button class="craft-btn" ' + (canCraft ? 'onclick="Crafting.craft(' + i + ')"' : 'disabled') + '>CRAFT</button></div>';
        }).join('');
    },

    craft(index) {
        // Check both base and echo recipes
        var allRecipes = this._recipes.slice();
        if (typeof EchoEngine !== 'undefined') {
            var ef = EchoEngine.getCurrentFrame();
            if (ef && ef.echoes && ef.echoes.L3) {
                var L3 = ef.echoes.L3;
                this._echoRecipes.forEach(function(er) {
                    if (er.condition(L3)) allRecipes.push(er);
                });
            }
        }
        var r = allRecipes[index];
        if (!r) return;
        var inv = typeof Inventory !== 'undefined' ? Inventory : null;
        if (!inv) return;
        // Check gold
        if (typeof PlayerStats !== 'undefined' && PlayerStats.gold < r.gold) return;
        // Check materials
        for (var name in r.materials) {
            var need = r.materials[name];
            var have = (inv.items || []).filter(function(item) { return item && item.name === name; }).length;
            if (have < need) return;
        }
        // Consume materials
        for (var name in r.materials) {
            var need = r.materials[name];
            for (var i = 0; i < need; i++) {
                var idx = (inv.items || []).findIndex(function(item) { return item && item.name === name; });
                if (idx >= 0) inv.items.splice(idx, 1);
            }
        }
        // Consume gold
        if (typeof PlayerStats !== 'undefined') PlayerStats.gold -= r.gold;
        // Add crafted item
        if (inv.items) inv.items.push(Object.assign({}, r.result, { id: 'crafted-' + Date.now() }));
        if (typeof HUD !== 'undefined') HUD.showToast('Crafted ' + r.name + '!');
        if (typeof Audio !== 'undefined' && Audio.playPickup) Audio.playPickup();
        // Crafting VFX
        if (typeof VFX !== 'undefined' && typeof WorldMode !== 'undefined' && WorldMode.player) {
            VFX.burst(WorldMode.player.mesh.position, 'goldPickup', { count: 12 });
            if (r.result.rarity === 'epic') VFX.burst(WorldMode.player.mesh.position, 'levelUp', { count: 8 });
        }
        this._render();
    }
};
