// Local Practice Shop — purchases never spend canonical RAPPcoin
const Shop = {
    _open: false,
    _items: [
        // Consumables
        { name: 'Health Potion', category: 'consumable', cost: 50, icon: '❤️', desc: 'Restore 40 HP', effect: 'heal', value: 40 },
        { name: 'Mana Crystal', category: 'consumable', cost: 40, icon: '💎', desc: 'Restore 30 MP', effect: 'mana', value: 30 },
        { name: 'Ward', category: 'consumable', cost: 75, icon: '👁️', desc: 'Reveal area for 60s', effect: 'ward', value: 60 },
        { name: 'Speed Elixir', category: 'consumable', cost: 100, icon: '⚡', desc: '+50% speed for 10s', effect: 'speed', value: 10 },
        // Weapons
        { name: 'Short Sword', category: 'weapon', cost: 150, icon: '🗡️', desc: '+10 damage', stats: { damage: 10 } },
        { name: 'Flame Blade', category: 'weapon', cost: 350, icon: '🔥', desc: '+18 damage, fire element', stats: { damage: 18 }, element: 'fire' },
        { name: 'Void Edge', category: 'weapon', cost: 600, icon: '🌀', desc: '+28 damage, void element', stats: { damage: 28 }, element: 'void' },
        { name: 'Starbreaker', category: 'weapon', cost: 1200, icon: '⭐', desc: '+45 damage, 10% crit', stats: { damage: 45, critChance: 0.1 } },
        // Armor
        { name: 'Leather Vest', category: 'armor', cost: 120, icon: '🛡️', desc: '+5 defense', stats: { defense: 5 } },
        { name: 'Chain Mail', category: 'armor', cost: 300, icon: '⛓️', desc: '+12 defense', stats: { defense: 12 } },
        { name: 'Titan Plate', category: 'armor', cost: 800, icon: '🏛️', desc: '+25 defense, +50 HP', stats: { defense: 25, maxHp: 50 } },
        // Boots
        { name: 'Swift Boots', category: 'boots', cost: 200, icon: '👟', desc: '+15% move speed', stats: { moveSpeed: 0.15 } },
        { name: 'Phase Boots', category: 'boots', cost: 450, icon: '💨', desc: '+25% move speed, +5 damage', stats: { moveSpeed: 0.25, damage: 5 } },
        // Accessories
        { name: 'Lifesteal Ring', category: 'accessory', cost: 500, icon: '💍', desc: '10% lifesteal on hit', stats: { lifesteal: 0.1 } },
        { name: 'Mana Pendant', category: 'accessory', cost: 300, icon: '📿', desc: '+20 max MP, +3 MP regen', stats: { maxMp: 20, mpRegen: 3 } },
    ],
    _category: 'all',

    toggle() {
        this._open = !this._open;
        if (this._open) this._show(); else this._hide();
    },

    _show() {
        var el = document.getElementById('shop-panel');
        if (!el) this._create();
        el = document.getElementById('shop-panel');
        if (el) el.style.display = 'block';
        this._render();
        if (typeof Audio !== 'undefined' && Audio.playMenuOpen) Audio.playMenuOpen();
    },

    _hide() {
        var el = document.getElementById('shop-panel');
        if (el) el.style.display = 'none';
    },

    _create() {
        var el = document.createElement('div');
        el.id = 'shop-panel';
        el.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);width:420px;max-height:85vh;background:rgba(22,27,34,0.95);border:1px solid rgba(210,153,34,0.3);border-radius:12px;z-index:9100;overflow:hidden;display:none;font-family:"SF Mono",monospace;backdrop-filter:blur(12px);';
        el.innerHTML = '<div style="padding:12px 16px;border-bottom:1px solid rgba(48,54,61,0.5);display:flex;justify-content:space-between;align-items:center;">' +
            '<span style="font-size:12px;font-weight:700;letter-spacing:2px;color:#d29922;">LOCAL PRACTICE SHOP</span>' +
            '<div style="display:flex;gap:4px;align-items:center;">' +
            '<span id="shop-gold" style="color:#fbbf24;font-size:11px;font-weight:700;">0 PG</span>' +
            '<button id="shop-close" style="background:none;border:none;color:#8b949e;font-size:18px;cursor:pointer;margin-left:8px;">&times;</button>' +
            '</div></div>' +
            '<div id="shop-tabs" style="padding:8px 16px;display:flex;gap:6px;border-bottom:1px solid rgba(48,54,61,0.3);"></div>' +
            '<div id="shop-items" style="padding:10px 16px;overflow-y:auto;max-height:60vh;"></div>';
        document.body.appendChild(el);
        document.getElementById('shop-close').addEventListener('click', function() { Shop.toggle(); });

        var style = document.createElement('style');
        style.textContent = '.shop-tab{background:none;border:1px solid rgba(255,255,255,0.1);color:#8b949e;padding:3px 10px;font:inherit;font-size:9px;border-radius:4px;cursor:pointer;letter-spacing:1px;text-transform:uppercase;}.shop-tab:hover,.shop-tab.active{border-color:rgba(210,153,34,0.4);color:#d29922;}.shop-item{display:flex;align-items:center;gap:10px;padding:8px;margin-bottom:6px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);border-radius:8px;transition:border-color 0.15s;}.shop-item:hover{border-color:rgba(210,153,34,0.3);}.shop-icon{font-size:20px;width:32px;text-align:center;}.shop-info{flex:1;}.shop-name{font-size:11px;font-weight:600;color:#e6edf3;}.shop-desc{font-size:9px;color:#8b949e;margin-top:2px;}.shop-cost{font-size:11px;color:#fbbf24;font-weight:700;white-space:nowrap;}.shop-buy{background:rgba(210,153,34,0.15);border:1px solid rgba(210,153,34,0.3);color:#d29922;padding:4px 10px;font:inherit;font-size:9px;border-radius:4px;cursor:pointer;letter-spacing:1px;}.shop-buy:hover{background:rgba(210,153,34,0.25);}.shop-buy:disabled{opacity:0.3;cursor:default;}';
        document.head.appendChild(style);
    },

    _render() {
        var gold = typeof PlayerStats !== 'undefined' ? PlayerStats.gold : 0;
        var goldEl = document.getElementById('shop-gold');
        if (goldEl) goldEl.textContent = gold + ' PG';

        // Tabs
        var tabsEl = document.getElementById('shop-tabs');
        if (tabsEl) {
            var cats = ['all', 'consumable', 'weapon', 'armor', 'boots', 'accessory'];
            tabsEl.innerHTML = cats.map(function(c) {
                return '<button class="shop-tab' + (Shop._category === c ? ' active' : '') + '" onclick="Shop._category=\'' + c + '\';Shop._render();">' + c + '</button>';
            }).join('');
        }

        // Items
        var itemsEl = document.getElementById('shop-items');
        if (!itemsEl) return;
        var filtered = this._category === 'all' ? this._items : this._items.filter(function(i) { return i.category === Shop._category; });

        var priceMod = this._getPriceMod();
        var priceTag = '';
        if (priceMod > 1.05) priceTag = ' <span style="color:#f85149;font-size:9px;">↑WAR TAX</span>';
        else if (priceMod < 0.95) priceTag = ' <span style="color:#00ff88;font-size:9px;">↓SOCIAL DISCOUNT</span>';

        itemsEl.innerHTML = filtered.map(function(item, i) {
            var idx = Shop._items.indexOf(item);
            var adjustedCost = Math.max(1, Math.round(item.cost * priceMod));
            var canBuy = gold >= adjustedCost;
            var costColor = priceMod > 1.05 ? '#f85149' : priceMod < 0.95 ? '#00ff88' : '#fbbf24';
            return '<div class="shop-item">' +
                '<span class="shop-icon">' + item.icon + '</span>' +
                '<div class="shop-info"><div class="shop-name">' + item.name + '</div><div class="shop-desc">' + item.desc + '</div></div>' +
                '<span class="shop-cost" style="color:' + costColor + '">' + adjustedCost + ' PG' + priceTag + '</span>' +
                '<button class="shop-buy" ' + (canBuy ? 'onclick="Shop.buy(' + idx + ')"' : 'disabled') + '>BUY</button></div>';
        }).join('');
    },

    _getPriceMod() {
        var mod = 1.0;
        if (typeof EchoEngine !== 'undefined') {
            var ef = EchoEngine.getCurrentFrame();
            if (ef && ef.echoes && ef.echoes.L3) {
                mod = 1 + ef.echoes.L3.tension * 0.25 - ef.echoes.L3.socialEnergy * 0.15;
                mod = Math.max(0.8, Math.min(1.3, mod));
            }
        }
        return mod;
    },

    buy(index) {
        var item = this._items[index];
        if (!item) return;
        var cost = Math.round(item.cost * this._getPriceMod());
        if (typeof PlayerStats === 'undefined' || PlayerStats.gold < cost) return;

        PlayerStats.gold -= cost;

        if (item.effect === 'heal') {
            PlayerStats.heal(item.value);
            if (typeof HUD !== 'undefined') HUD.showToast('Used ' + item.name + ' — +' + item.value + ' HP');
        } else if (item.effect === 'mana') {
            PlayerStats.restoreMp(item.value);
            if (typeof HUD !== 'undefined') HUD.showToast('Used ' + item.name + ' — +' + item.value + ' MP');
        } else if (item.effect === 'ward') {
            if (typeof FogOfWar !== 'undefined') FogOfWar.placeWard();
            if (typeof HUD !== 'undefined') HUD.showToast('Ward placed at your location');
        } else if (item.effect === 'speed') {
            if (typeof WorldMode !== 'undefined') {
                var origSpeed = WorldMode.playerSpeed;
                WorldMode.playerSpeed *= 1.5;
                setTimeout(function() { WorldMode.playerSpeed = origSpeed; }, item.value * 1000);
            }
            if (typeof HUD !== 'undefined') HUD.showToast('Speed boost for ' + item.value + 's!');
        } else if (item.stats) {
            // Equipment — add to inventory
            if (typeof Inventory !== 'undefined' && Inventory.items) {
                Inventory.items.push(Object.assign({}, item, { id: 'shop-' + Date.now() }));
                if (typeof HUD !== 'undefined') HUD.showToast('Bought ' + item.name);
            }
        }

        if (typeof Audio !== 'undefined' && Audio.playPickup) Audio.playPickup();
        PlayerStats.save();
        this._render();
    }
};
