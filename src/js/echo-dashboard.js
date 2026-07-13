// Echo Dashboard — Full echo engine readout overlay
// Toggle: backtick (`) key

const EchoDashboard = {
    _open: false,
    _el: null,

    toggle() {
        this._open = !this._open;
        if (this._open) this._show();
        else this._hide();
    },

    _show() {
        if (!this._el) this._create();
        this._el.classList.add('visible');
        this._render();
    },

    _hide() {
        if (this._el) this._el.classList.remove('visible');
    },

    _create() {
        var el = document.createElement('div');
        el.id = 'echo-dashboard';
        el.innerHTML = '<div class="echo-dash-header">' +
            '<span class="echo-dash-title">ECHO ENGINE</span>' +
            '<button class="echo-dash-close" id="echo-dash-close">&times;</button>' +
            '</div><div class="echo-dash-body" id="echo-dash-body"></div>';
        document.body.appendChild(el);
        document.getElementById('echo-dash-close').addEventListener('click', function() { EchoDashboard.toggle(); });
        this._el = el;
    },

    _render() {
        var body = document.getElementById('echo-dash-body');
        if (!body) return;
        var html = '';

        if (typeof EchoEngine === 'undefined') {
            body.innerHTML = '<div style="color:#8b949e;font-size:11px;">Echo Engine not loaded.</div>';
            return;
        }

        var ef = EchoEngine.getCurrentFrame();
        if (!ef || !ef.echoes) {
            body.innerHTML = '<div style="color:#8b949e;font-size:11px;">No echo frames captured yet.</div>';
            return;
        }

        var L1 = ef.echoes.L1 || {};
        var L2 = ef.echoes.L2 || {};
        var L3 = ef.echoes.L3 || {};
        var L6 = ef.echoes.L6 || {};

        // L3 Atmosphere bars
        html += '<div class="echo-dash-section">';
        html += '<div class="echo-dash-label">L3 ATMOSPHERE</div>';
        html += this._bar('Tension', L3.tension || 0, this._tensionColor(L3.tension || 0));
        html += this._bar('Vitality', L3.vitality || 0, '#00ff88');
        html += this._bar('Social Energy', L3.socialEnergy || 0, '#ffd700');
        html += this._bar('Light Intensity', L3.lightIntensity || 1, '#aaccff');
        html += this._bar('Particle Density', L3.particleDensity || 0.5, '#aa44ff');
        html += this._bar('Music Intensity', L3.musicIntensity || 0, '#ff8800');
        html += '</div>';

        // L2 Narrative
        html += '<div class="echo-dash-section">';
        html += '<div class="echo-dash-label">L2 NARRATIVE</div>';
        html += '<div class="echo-dash-narrative">' + escapeHTML(L2.narrative || 'No narrative.') + '</div>';
        html += '<div class="echo-dash-meta">Dominant mood: ' + escapeHTML(L2.dominantMood || 'neutral') + '</div>';
        html += '</div>';

        // L1 Combat digest
        if (L1.combat && L1.combat.wave > 0) {
            html += '<div class="echo-dash-section">';
            html += '<div class="echo-dash-label">L1 COMBAT</div>';
            html += this._bar('Momentum', (L1.combat.momentum || 50) / 100, L1.combat.momentum > 60 ? '#00ff88' : L1.combat.momentum < 40 ? '#ff4444' : '#ffaa00');
            html += '<div class="echo-dash-value"><span>Wave ' + escapeHTML(L1.combat.wave) + '</span><span>' + escapeHTML(L1.combat.creepCount) + ' units</span>';
            if (L1.combat.bossActive) html += '<span style="color:#aa44ff">BOSS</span>';
            html += '</div></div>';
        }

        // L6 Temporal depth
        html += '<div class="echo-dash-section">';
        html += '<div class="echo-dash-label">L6 TEMPORAL DEPTH</div>';
        html += '<div class="echo-dash-value">';
        html += '<span>Pop: ' + escapeHTML(L6.populationTrend || 'stable') + '</span>';
        html += '<span>Econ: ' + escapeHTML(L6.economicArc || 'steady') + '</span>';
        html += '<span>Mood stable: ' + (L6.moodStability ? 'yes' : 'no') + '</span>';
        html += '</div></div>';

        // Active echo event
        if (typeof EchoEvents !== 'undefined' && EchoEvents._activeEvent) {
            html += '<div class="echo-dash-section">';
            html += '<div class="echo-dash-event">' + escapeHTML(EchoEvents._activeEvent.name) + ' — ' + Math.ceil(EchoEvents._eventTimer) + 's remaining</div>';
            html += '</div>';
        }

        // Tension history sparkline (text version — vertical bars)
        if (typeof HUD !== 'undefined' && HUD._tensionHistory && HUD._tensionHistory.length > 5) {
            html += '<div class="echo-dash-section">';
            html += '<div class="echo-dash-label">TENSION HISTORY</div>';
            html += '<div class="echo-dash-history">';
            var hist = HUD._tensionHistory.slice(-60);
            for (var i = 0; i < hist.length; i++) {
                var h = Math.max(2, Math.round(hist[i] * 30));
                html += '<div class="echo-dash-history-bar" style="height:' + h + 'px;background:' + this._tensionColor(hist[i]) + '"></div>';
            }
            html += '</div></div>';
        }

        // Session history
        var sessions = EchoEngine.getSessionHistory();
        if (sessions.length > 0) {
            html += '<div class="echo-dash-section">';
            html += '<div class="echo-dash-label">SESSION HISTORY (' + sessions.length + ' sessions)</div>';
            var last = sessions[sessions.length - 1];
            html += '<div class="echo-dash-value">';
            html += '<span>Last: T' + Math.round(last.avgTension * 100) + '% V' + Math.round(last.avgVitality * 100) + '%</span>';
            html += '<span>Peak: ' + Math.round(last.peakTension * 100) + '%</span>';
            html += '<span>' + last.frames + ' frames</span>';
            html += '</div></div>';
        }

        // Frame info
        html += '<div class="echo-dash-section">';
        html += '<div class="echo-dash-label">FRAME</div>';
        html += '<div class="echo-dash-meta">Frame ' + escapeHTML(ef.frame || '?') + ' · ' + EchoEngine.getFrameCount() + ' frames buffered · ' + (EchoEngine.isLive() ? 'LIVE' : 'SCRUBBING') + '</div>';
        html += '</div>';

        body.innerHTML = html;
    },

    _bar(label, value, color) {
        var pct = Math.round(Math.min(1, Math.max(0, value)) * 100);
        return '<div class="echo-dash-bar"><div class="echo-dash-bar-fill" style="width:' + pct + '%;background:' + color + '"></div></div>' +
            '<div class="echo-dash-value"><span>' + escapeHTML(label) + '</span><span>' + pct + '%</span></div>';
    },

    _tensionColor(t) {
        if (t > 0.6) return '#ff4444';
        if (t > 0.3) return '#ffaa00';
        return '#00ff88';
    }
};
