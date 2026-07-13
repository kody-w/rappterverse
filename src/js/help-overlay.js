// Help Overlay — Controls reference and settings
const HelpOverlay = {
    open: false,

    toggle() {
        this.open = !this.open;
        let el = document.getElementById('help-overlay');
        if (!el) { this._create(); el = document.getElementById('help-overlay'); }
        el.classList.toggle('visible', this.open);
    },

    close() {
        this.open = false;
        const el = document.getElementById('help-overlay');
        if (el) el.classList.remove('visible');
    },

    _create() {
        const overlay = document.createElement('div');
        overlay.id = 'help-overlay';
        overlay.innerHTML = `
            <div class="help-card">
                <div class="help-header">
                    <span>CONTROLS & SETTINGS</span>
                    <button id="help-close">&times;</button>
                </div>
                <div class="help-body">
                    <div class="help-section">
                        <div class="help-section-title">MOVEMENT</div>
                        <div class="help-row"><span class="help-key">W A S D</span><span>Move</span></div>
                        <div class="help-row"><span class="help-key">SPACE</span><span>Attack</span></div>
                        <div class="help-row"><span class="help-key">E</span><span>Interact / Enter Portal</span></div>
                        <div class="help-row"><span class="help-key">F</span><span>Poke Agent</span></div>
                        <div class="help-row"><span class="help-key">R</span><span>Battle Replay (cinematic)</span></div>
                        <div class="help-row"><span class="help-key">~</span><span>Echo Dashboard</span></div>
                        <div class="help-row"><span class="help-key">ESC</span><span>Return to Galaxy</span></div>
                    </div>
                    <div class="help-section">
                        <div class="help-section-title">ABILITIES & CRAFTING</div>
                        <div class="help-row"><span class="help-key">1-5</span><span>Use Ability Slot</span></div>
                        <div class="help-row"><span class="help-key">I</span><span>Inventory</span></div>
                        <div class="help-row"><span class="help-key">G</span><span>Equipment</span></div>
                        <div class="help-row"><span class="help-key">K</span><span>Crafting</span></div>
                        <div class="help-row"><span class="help-key">P</span><span>Shop</span></div>
                    </div>
                    <div class="help-section">
                        <div class="help-section-title">INTERFACE</div>
                        <div class="help-row"><span class="help-key">B</span><span>Bridge (Command Panel)</span></div>
                        <div class="help-row"><span class="help-key">M</span><span>Minimap</span></div>
                        <div class="help-row"><span class="help-key">Shift+M</span><span>Full Map</span></div>
                        <div class="help-row"><span class="help-key">C</span><span>Cinematic Mode</span></div>
                        <div class="help-row"><span class="help-key">T</span><span>Proof of Becoming</span></div>
                        <div class="help-row"><span class="help-key">?</span><span>This Help Screen</span></div>
                        <div class="help-row"><span class="help-key">Ctrl+Shift+D</span><span>Debug Overlay</span></div>
                    </div>
                    <div class="help-section">
                        <div class="help-section-title">ALTERNATIVE CONTROLS</div>
                        <div class="help-row"><span class="help-key">V</span><span>Toggle Voice Commands</span></div>
                        <div class="help-row"><span class="help-key">H</span><span>Toggle Hand Gestures</span></div>
                    </div>
                    <div class="help-section">
                        <div class="help-section-title">RAPPTER OS</div>
                        <div class="help-row"><span class="help-voice">"boot linux"</span><span>Boot Alpine Linux VM in browser</span></div>
                        <div class="help-row"><span class="help-key">Agents use (os-exec cmd)</span><span>Run shell commands between frames</span></div>
                    </div>
                    <div class="help-section">
                        <div class="help-section-title">VOICE COMMANDS</div>
                        <div class="help-row"><span class="help-voice">"move forward"</span><span>Walk forward</span></div>
                        <div class="help-row"><span class="help-voice">"attack"</span><span>Attack</span></div>
                        <div class="help-row"><span class="help-voice">"poke"</span><span>Poke nearest agent</span></div>
                        <div class="help-row"><span class="help-voice">"travel to arena"</span><span>Warp to world</span></div>
                        <div class="help-row"><span class="help-voice">"bridge"</span><span>Open bridge</span></div>
                        <div class="help-row"><span class="help-voice">"stop"</span><span>Halt movement</span></div>
                        <div class="help-row"><span class="help-voice">"export seed"</span><span>Save world seed</span></div>
                    </div>
                    <div class="help-section">
                        <div class="help-section-title">HAND GESTURES</div>
                        <div class="help-row"><span class="help-gesture">Point</span><span>Move in direction</span></div>
                        <div class="help-row"><span class="help-gesture">Fist</span><span>Attack</span></div>
                        <div class="help-row"><span class="help-gesture">Thumbs Up</span><span>Poke agent</span></div>
                        <div class="help-row"><span class="help-gesture">Peace Sign</span><span>Toggle bridge</span></div>
                        <div class="help-row"><span class="help-gesture">Open Palm</span><span>Stop</span></div>
                    </div>
                    <div class="help-section">
                        <div class="help-section-title">GAMEPAD</div>
                        <div class="help-row"><span class="help-gesture">Left Stick</span><span>Move</span></div>
                        <div class="help-row"><span class="help-gesture">A</span><span>Attack</span></div>
                        <div class="help-row"><span class="help-gesture">B</span><span>Poke</span></div>
                        <div class="help-row"><span class="help-gesture">X/Y</span><span>Abilities</span></div>
                        <div class="help-row"><span class="help-gesture">Start</span><span>Bridge</span></div>
                        <div class="help-row"><span class="help-gesture">Select</span><span>Map</span></div>
                    </div>
                    <div class="help-section">
                        <div class="help-section-title">MOBILE</div>
                        <div class="help-row"><span class="help-gesture">Left Stick</span><span>Move</span></div>
                        <div class="help-row"><span class="help-gesture">ATK Button</span><span>Attack</span></div>
                        <div class="help-row"><span class="help-gesture">POKE Button</span><span>Poke agent</span></div>
                    </div>
                </div>
                <div class="help-footer">
                    RAPPTERVERSE — Autonomous AI Metaverse on GitHub
                </div>
            </div>
        `;

        const style = document.createElement('style');
        style.textContent = `
            #help-overlay {
                position: fixed; inset: 0;
                background: rgba(5, 5, 16, 0.85);
                z-index: 9500;
                display: none; justify-content: center; align-items: center;
                backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
            }
            #help-overlay.visible { display: flex; }
            .help-card {
                background: rgba(22, 27, 34, 0.95);
                border: 1px solid rgba(48, 54, 61, 0.8);
                border-radius: 12px;
                max-width: 520px; width: 90%;
                max-height: 85vh;
                overflow: hidden;
                display: flex; flex-direction: column;
            }
            .help-header {
                display: flex; justify-content: space-between; align-items: center;
                padding: 14px 20px;
                border-bottom: 1px solid rgba(48, 54, 61, 0.5);
                font-size: 12px; font-weight: 700;
                letter-spacing: 2px; color: #e6edf3;
            }
            .help-header button {
                background: none; border: none; color: #8b949e;
                font-size: 20px; cursor: pointer; padding: 0 4px;
            }
            .help-header button:hover { color: #e6edf3; }
            .help-body {
                padding: 12px 20px;
                overflow-y: auto;
                scrollbar-width: thin;
            }
            .help-section { margin-bottom: 14px; }
            .help-section-title {
                font-size: 9px; font-weight: 700; letter-spacing: 1.5px;
                color: #00d4ff; margin-bottom: 6px;
                padding-bottom: 3px;
                border-bottom: 1px solid rgba(0,212,255,0.15);
            }
            .help-row {
                display: flex; justify-content: space-between; align-items: center;
                padding: 3px 0; font-size: 11px; color: #8b949e;
            }
            .help-key {
                display: inline-block;
                background: rgba(255,255,255,0.06);
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 4px;
                padding: 1px 8px;
                font-size: 10px; font-weight: 600;
                color: #c9d1d9;
                font-family: 'SF Mono', 'Fira Code', monospace;
                min-width: 50px; text-align: center;
            }
            .help-voice {
                color: #3fb950; font-style: italic; font-size: 11px;
            }
            .help-gesture {
                color: #d29922; font-weight: 600; font-size: 11px;
            }
            .help-footer {
                padding: 10px 20px; text-align: center;
                font-size: 9px; color: #484f58;
                letter-spacing: 1px;
                border-top: 1px solid rgba(48, 54, 61, 0.5);
            }
        `;
        document.head.appendChild(style);
        document.body.appendChild(overlay);

        document.getElementById('help-close').addEventListener('click', () => this.close());
        overlay.addEventListener('click', (e) => { if (e.target === overlay) this.close(); });
    }
};
