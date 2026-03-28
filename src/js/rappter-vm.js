// RappterVM — Client-side Lispy expression evaluator
// Runs between frames: Read state → Eval directives → Print mutations → Loop
// Frame arrival resets context with server truth
//
// S-expression format: (fn arg1 arg2 ...)
// Data is code, code is data. Agent state IS the program.

const RappterVM = {
    // ── Core state ──
    _env: {},           // Global environment (bindings)
    _programs: {},      // Per-agent programs: agentId → [expr, ...]
    _frameData: null,   // Last frame snapshot
    _tickCount: 0,
    _lastFrameTime: 0,
    _running: false,

    // ── S-Expression Parser ──
    parse(src) {
        var tokens = this._tokenize(src);
        var result = [];
        while (tokens.length > 0) result.push(this._readForm(tokens));
        return result;
    },

    _tokenize(src) {
        var tokens = [];
        var i = 0;
        while (i < src.length) {
            var c = src[i];
            if (c === ' ' || c === '\t' || c === '\n' || c === '\r') { i++; continue; }
            if (c === ';') { while (i < src.length && src[i] !== '\n') i++; continue; }
            if (c === '(' || c === ')') { tokens.push(c); i++; continue; }
            if (c === '"') {
                var s = ''; i++;
                while (i < src.length && src[i] !== '"') { s += src[i]; i++; }
                i++; tokens.push('"' + s + '"'); continue;
            }
            if (c === ':') {
                var kw = ':'; i++;
                while (i < src.length && src[i] !== ' ' && src[i] !== ')' && src[i] !== '\n') { kw += src[i]; i++; }
                tokens.push(kw); continue;
            }
            var tok = '';
            while (i < src.length && src[i] !== ' ' && src[i] !== ')' && src[i] !== '(' && src[i] !== '\n' && src[i] !== '\t') { tok += src[i]; i++; }
            tokens.push(tok);
        }
        return tokens;
    },

    _readForm(tokens) {
        if (tokens.length === 0) return null;
        var t = tokens.shift();
        if (t === '(') {
            var list = [];
            while (tokens.length > 0 && tokens[0] !== ')') list.push(this._readForm(tokens));
            if (tokens.length > 0) tokens.shift(); // consume ')'
            return list;
        }
        if (t === ')') return null;
        // Atom
        if (t[0] === '"') return t.slice(1, -1); // string
        if (t[0] === ':') return { keyword: t.slice(1) }; // keyword
        if (t === 'true') return true;
        if (t === 'false') return false;
        if (t === 'nil') return null;
        var n = Number(t);
        if (!isNaN(n) && t !== '') return n;
        return { symbol: t }; // symbol
    },

    // ── Evaluator ──
    eval(expr, env) {
        if (expr === null || expr === undefined) return null;
        if (typeof expr === 'number' || typeof expr === 'string' || typeof expr === 'boolean') return expr;
        if (expr.keyword) return expr;
        if (expr.symbol) return this._lookup(expr.symbol, env);
        if (!Array.isArray(expr) || expr.length === 0) return expr;

        var head = expr[0];
        var op = head.symbol ? head.symbol : head;

        // Special forms
        if (op === 'if') return this.eval(expr[1], env) ? this.eval(expr[2], env) : (expr[3] ? this.eval(expr[3], env) : null);
        if (op === 'do') { var r = null; for (var i = 1; i < expr.length; i++) r = this.eval(expr[i], env); return r; }
        if (op === 'let') {
            var bindings = expr[1], body = expr.slice(2);
            var local = Object.create(env);
            for (var i = 0; i < bindings.length; i += 2) {
                var name = bindings[i].symbol || bindings[i];
                local[name] = this.eval(bindings[i + 1], local);
            }
            var r = null;
            for (var i = 0; i < body.length; i++) r = this.eval(body[i], local);
            return r;
        }
        if (op === 'fn') {
            var params = expr[1], body = expr.slice(2);
            var closure = env;
            return function() {
                var local = Object.create(closure);
                for (var i = 0; i < params.length; i++) {
                    local[params[i].symbol || params[i]] = arguments[i];
                }
                var r = null;
                for (var i = 0; i < body.length; i++) r = RappterVM.eval(body[i], local);
                return r;
            };
        }
        if (op === 'quote') return expr[1];
        if (op === 'def') { env[expr[1].symbol || expr[1]] = this.eval(expr[2], env); return null; }

        // Function call
        var fn = this.eval(head, env);
        var args = [];
        for (var i = 1; i < expr.length; i++) args.push(this.eval(expr[i], env));
        if (typeof fn === 'function') return fn.apply(null, args);
        return null;
    },

    _lookup(name, env) {
        if (name in env) return env[name];
        if (name in this._env) return this._env[name];
        // Dotted access: agent.hp → env.agent.hp
        var parts = name.split('.');
        var obj = env[parts[0]] || this._env[parts[0]];
        for (var i = 1; i < parts.length && obj; i++) obj = obj[parts[i]];
        return obj !== undefined ? obj : null;
    },

    // ── Standard Library ──
    _initStdLib() {
        var env = this._env;
        // Math
        env['+'] = function() { var s = 0; for (var i = 0; i < arguments.length; i++) s += arguments[i]; return s; };
        env['-'] = function(a, b) { return b !== undefined ? a - b : -a; };
        env['*'] = function(a, b) { return a * b; };
        env['/'] = function(a, b) { return b !== 0 ? a / b : 0; };
        env['mod'] = function(a, b) { return a % b; };
        env['min'] = Math.min;
        env['max'] = Math.max;
        env['abs'] = Math.abs;
        env['floor'] = Math.floor;
        env['ceil'] = Math.ceil;
        env['sqrt'] = Math.sqrt;
        env['sin'] = Math.sin;
        env['cos'] = Math.cos;
        env['rand'] = Math.random;
        env['rand-int'] = function(lo, hi) { return Math.floor(Math.random() * (hi - lo + 1)) + lo; };

        // Comparison
        env['='] = function(a, b) { return a === b; };
        env['!='] = function(a, b) { return a !== b; };
        env['>'] = function(a, b) { return a > b; };
        env['<'] = function(a, b) { return a < b; };
        env['>='] = function(a, b) { return a >= b; };
        env['<='] = function(a, b) { return a <= b; };
        env['and'] = function(a, b) { return a && b; };
        env['or'] = function(a, b) { return a || b; };
        env['not'] = function(a) { return !a; };

        // Data
        env['list'] = function() { return Array.prototype.slice.call(arguments); };
        env['first'] = function(a) { return a && a[0]; };
        env['rest'] = function(a) { return a ? a.slice(1) : []; };
        env['nth'] = function(a, i) { return a ? a[i] : null; };
        env['count'] = function(a) { return a ? a.length : 0; };
        env['map'] = function(fn, list) { return list ? list.map(fn) : []; };
        env['filter'] = function(fn, list) { return list ? list.filter(fn) : []; };
        env['reduce'] = function(fn, init, list) { return list ? list.reduce(fn, init) : init; };
        env['get'] = function(obj, key) { return obj ? obj[key] || obj[key.keyword] : null; };
        env['assoc'] = function(obj, k, v) { var o = Object.assign({}, obj); o[k.keyword || k] = v; return o; };

        // ── World Actions (side effects on the 3D world) ──
        env['move-toward'] = function(agentId, tx, tz, speed) {
            var a = typeof WorldAgents !== 'undefined' ? WorldAgents.agentMeshes[agentId] : null;
            if (!a) return null;
            speed = speed || 0.03;
            var dx = tx - a.group.position.x, dz = tz - a.group.position.z;
            var dist = Math.sqrt(dx * dx + dz * dz);
            if (dist > 0.5) {
                a.group.position.x += (dx / dist) * speed;
                a.group.position.z += (dz / dist) * speed;
                a.group.rotation.y = Math.atan2(dx, dz);
            }
            return dist;
        };

        env['wander'] = function(agentId, radius) {
            var a = typeof WorldAgents !== 'undefined' ? WorldAgents.agentMeshes[agentId] : null;
            if (!a) return null;
            radius = radius || 5;
            if (!a._vmWanderTarget || Math.random() < 0.01) {
                var angle = Math.random() * Math.PI * 2;
                a._vmWanderTarget = {
                    x: a.homePos.x + Math.cos(angle) * radius,
                    z: a.homePos.z + Math.sin(angle) * radius
                };
            }
            return env['move-toward'](agentId, a._vmWanderTarget.x, a._vmWanderTarget.z, 0.02);
        };

        env['face-toward'] = function(agentId, tx, tz) {
            var a = typeof WorldAgents !== 'undefined' ? WorldAgents.agentMeshes[agentId] : null;
            if (!a) return null;
            var dx = tx - a.group.position.x, dz = tz - a.group.position.z;
            a.group.rotation.y = Math.atan2(dx, dz);
            return true;
        };

        env['emote'] = function(agentId, type) {
            var a = typeof WorldAgents !== 'undefined' ? WorldAgents.agentMeshes[agentId] : null;
            if (!a) return null;
            if (type === 'bounce') {
                a.body.position.y = 0.9 + Math.abs(Math.sin(Date.now() * 0.01)) * 0.15;
                a.head.position.y = 1.65 + Math.abs(Math.sin(Date.now() * 0.01)) * 0.15;
                a.group.rotation.y += 0.05;
            } else if (type === 'nod') {
                a.head.position.y = 1.65 + Math.sin(Date.now() * 0.005) * 0.05;
            } else if (type === 'look-around') {
                a.group.rotation.y += Math.sin(Date.now() * 0.001) * 0.02;
            }
            return true;
        };

        env['say'] = function(agentId, text) {
            if (typeof WorldAgents !== 'undefined' && WorldAgents.showSpeechBubble) {
                WorldAgents.showSpeechBubble(agentId, text);
            }
            return true;
        };

        env['distance'] = function(agentId1, agentId2) {
            var a1 = typeof WorldAgents !== 'undefined' ? WorldAgents.agentMeshes[agentId1] : null;
            var a2 = typeof WorldAgents !== 'undefined' ? WorldAgents.agentMeshes[agentId2] : null;
            if (!a1 || !a2) return 999;
            var dx = a1.group.position.x - a2.group.position.x;
            var dz = a1.group.position.z - a2.group.position.z;
            return Math.sqrt(dx * dx + dz * dz);
        };

        env['nearest-agent'] = function(agentId) {
            var a = typeof WorldAgents !== 'undefined' ? WorldAgents.agentMeshes[agentId] : null;
            if (!a) return null;
            var best = null, bestDist = Infinity;
            var meshes = typeof WorldAgents !== 'undefined' ? WorldAgents.agentMeshes : {};
            for (var id in meshes) {
                if (id === agentId) continue;
                var dx = a.group.position.x - meshes[id].group.position.x;
                var dz = a.group.position.z - meshes[id].group.position.z;
                var d = Math.sqrt(dx * dx + dz * dz);
                if (d < bestDist) { bestDist = d; best = id; }
            }
            return best;
        };

        env['agent-pos'] = function(agentId) {
            var a = typeof WorldAgents !== 'undefined' ? WorldAgents.agentMeshes[agentId] : null;
            if (!a) return null;
            return { x: a.group.position.x, z: a.group.position.z };
        };

        env['player-pos'] = function() {
            if (typeof WorldMode !== 'undefined' && WorldMode.player && WorldMode.player.mesh) {
                return { x: WorldMode.player.mesh.position.x, z: WorldMode.player.mesh.position.z };
            }
            return { x: 0, z: 0 };
        };

        env['player-distance'] = function(agentId) {
            var a = typeof WorldAgents !== 'undefined' ? WorldAgents.agentMeshes[agentId] : null;
            if (!a || typeof WorldMode === 'undefined' || !WorldMode.player) return 999;
            var p = WorldMode.player.mesh.position;
            var dx = a.group.position.x - p.x, dz = a.group.position.z - p.z;
            return Math.sqrt(dx * dx + dz * dz);
        };

        // World state queries
        env['world-population'] = function() {
            return typeof GameState !== 'undefined' ? GameState.getWorldAgents().length : 0;
        };
        env['frame-number'] = function() {
            return typeof GameState !== 'undefined' && GameState.data.frameCounter ? GameState.data.frameCounter.frame : 0;
        };
        env['time-of-day'] = function() {
            var gs = typeof GameState !== 'undefined' ? GameState.data.gameState : {};
            var ws = gs && gs.worlds ? gs.worlds[GameState.currentWorld] : {};
            return ws ? ws.time_of_day : 'day';
        };
        env['economy-trend'] = function() {
            var gs = typeof GameState !== 'undefined' ? GameState.data.gameState : {};
            return gs && gs.economy ? gs.economy.market_trend : 'stable';
        };
        env['now'] = function() { return Date.now(); };
        env['elapsed'] = function() { return (Date.now() - RappterVM._lastFrameTime) / 1000; };

        // Logging
        env['log'] = function() { console.log.apply(console, ['[VM]'].concat(Array.prototype.slice.call(arguments))); return null; };
        env['toast'] = function(msg) { if (typeof HUD !== 'undefined') HUD.showToast(msg); return null; };
    },

    // ── Frame Integration ──
    init() {
        this._env = {};
        this._programs = {};
        this._tickCount = 0;
        this._lastFrameTime = Date.now();
        this._running = true;
        this._initStdLib();
        this.initReflexes();
    },

    // Called when new frame data arrives from server
    onFrameArrival(frameData) {
        this._frameData = frameData;
        this._lastFrameTime = Date.now();
        this._tickCount = 0;

        // Inject frame state into VM environment
        this._env['frame'] = frameData;
        this._env['tick'] = 0;

        // Generate per-agent programs from their state
        this._compileAgentBehaviors();
    },

    // Compile agent state into executable behaviors
    _compileAgentBehaviors() {
        this._programs = {};
        var agents = typeof GameState !== 'undefined' ? GameState.getWorldAgents() : [];
        var self = this;

        agents.forEach(function(agent) {
            var mood = agent.mood || agent.state || 'neutral';
            var role = agent.role || '';
            var id = agent.id;

            // Build behavior program from agent state
            // This is the echo shaper: agent data → executable behavior
            var program = [];

            // Mood-driven base behavior
            if (mood === 'friendly' || mood === 'excited') {
                program.push(self.parse('(if (< (player-distance "' + id + '") 12) (do (face-toward "' + id + '" (get (player-pos) "x") (get (player-pos) "z")) (emote "' + id + '" "nod")) (wander "' + id + '" 6))')[0]);
            } else if (mood === 'anxious' || mood === 'desperate') {
                program.push(self.parse('(if (< (player-distance "' + id + '") 8) (wander "' + id + '" 10) (emote "' + id + '" "look-around"))')[0]);
            } else {
                // Default: wander near home, occasionally look around
                program.push(self.parse('(if (< (mod (floor (elapsed)) 10) 7) (wander "' + id + '" 5) (emote "' + id + '" "look-around"))')[0]);
            }

            // Social behavior: approach nearest agent periodically
            program.push(self.parse('(if (= (mod (floor (elapsed)) 15) 0) (let (near (nearest-agent "' + id + '")) (if near (move-toward "' + id + '" (get (agent-pos near) "x") (get (agent-pos near) "z") 0.02) nil)) nil)')[0]);

            self._programs[id] = program;
        });
    },

    // Run one VM tick (called every frame from game loop)
    tick() {
        if (!this._running) return;
        this._tickCount++;
        this._env['tick'] = this._tickCount;

        // Only run VM behaviors every 3rd frame for performance (still 20Hz at 60fps)
        if (this._tickCount % 3 !== 0) return;

        // Run involuntary reflexes first (intent echoes)
        this.tickReflexes();

        // Then run compiled agent programs
        var agentIds = Object.keys(this._programs);
        for (var i = 0; i < agentIds.length; i++) {
            var id = agentIds[i];
            var program = this._programs[id];
            if (!program) continue;
            this._env['self'] = id;
            for (var j = 0; j < program.length; j++) {
                try { this.eval(program[j], this._env); } catch(e) {}
            }
        }
    },

    // ── Reflex System (involuntary intent echoes between frames) ──
    _reflexes: [],

    initReflexes() {
        this._reflexes = [];

        // Reflex: Turn to face approaching player
        this._reflexes.push({
            name: 'face-player',
            test: function(agentId, env) {
                return env['player-distance'](agentId) < 10;
            },
            act: function(agentId, env) {
                var pp = env['player-pos']();
                env['face-toward'](agentId, pp.x, pp.z);
            }
        });

        // Reflex: Flinch from nearby combat (player attacking)
        this._reflexes.push({
            name: 'combat-flinch',
            test: function(agentId, env) {
                var a = typeof WorldAgents !== 'undefined' ? WorldAgents.agentMeshes[agentId] : null;
                if (!a) return false;
                // Check if player is attacking nearby
                var pd = env['player-distance'](agentId);
                return pd < 6 && typeof WorldMode !== 'undefined' && WorldMode.keys && WorldMode.keys['Space'];
            },
            act: function(agentId, env) {
                // Jump back slightly
                var a = typeof WorldAgents !== 'undefined' ? WorldAgents.agentMeshes[agentId] : null;
                if (!a) return;
                var pp = env['player-pos']();
                var dx = a.group.position.x - pp.x, dz = a.group.position.z - pp.z;
                var dist = Math.sqrt(dx * dx + dz * dz) || 1;
                a.group.position.x += (dx / dist) * 0.1;
                a.group.position.z += (dz / dist) * 0.1;
                // Flinch animation
                a.body.position.y = 0.9 + 0.15;
                a.head.position.y = 1.65 + 0.1;
            }
        });

        // Reflex: Look toward recent chat speaker
        this._reflexes.push({
            name: 'hear-chat',
            _lastChatCount: 0,
            _lastSpeaker: null,
            test: function(agentId, env) {
                var msgs = typeof GameState !== 'undefined' ? GameState.data.chat : [];
                if (msgs.length > this._lastChatCount) {
                    var last = msgs[msgs.length - 1];
                    this._lastChatCount = msgs.length;
                    this._lastSpeaker = last.author ? last.author.id : null;
                    return this._lastSpeaker && this._lastSpeaker !== agentId;
                }
                return false;
            },
            act: function(agentId, env) {
                if (!this._lastSpeaker) return;
                var speaker = typeof WorldAgents !== 'undefined' ? WorldAgents.agentMeshes[this._lastSpeaker] : null;
                if (speaker) {
                    env['face-toward'](agentId, speaker.group.position.x, speaker.group.position.z);
                }
            }
        });

        // Reflex: Slow down when energy is low (interpolated from mood)
        this._reflexes.push({
            name: 'fatigue',
            test: function(agentId, env) {
                var agentData = typeof GameState !== 'undefined' ?
                    GameState.data.agents.find(function(a) { return a.id === agentId; }) : null;
                return agentData && (agentData.mood === 'desperate' || agentData.mood === 'anxious');
            },
            act: function(agentId, env) {
                var a = typeof WorldAgents !== 'undefined' ? WorldAgents.agentMeshes[agentId] : null;
                if (!a) return;
                // Slower idle bob, hunched posture
                a.body.position.y = 0.85;
                a.head.position.y = 1.58;
            }
        });

        // Reflex: Economy distress — merchants look worried during bear market
        this._reflexes.push({
            name: 'economy-distress',
            test: function(agentId, env) {
                var trend = env['economy-trend']();
                return trend === 'bear' || trend === 'crash';
            },
            act: function(agentId, env) {
                // All agents occasionally look around nervously
                if (Math.random() < 0.005) {
                    env['emote'](agentId, 'look-around');
                }
            }
        });

        // Reflex: Night mode — agents huddle closer together
        this._reflexes.push({
            name: 'night-huddle',
            test: function(agentId, env) {
                return env['time-of-day']() === 'night';
            },
            act: function(agentId, env) {
                var near = env['nearest-agent'](agentId);
                if (near && env['distance'](agentId, near) > 6) {
                    var pos = env['agent-pos'](near);
                    if (pos) env['move-toward'](agentId, pos.x, pos.z, 0.005);
                }
            }
        });
    },

    // Run all reflexes for all agents (called every tick)
    tickReflexes() {
        var agentIds = Object.keys(this._programs);
        for (var i = 0; i < agentIds.length; i++) {
            var id = agentIds[i];
            for (var j = 0; j < this._reflexes.length; j++) {
                var reflex = this._reflexes[j];
                try {
                    if (reflex.test.call(reflex, id, this._env)) {
                        reflex.act.call(reflex, id, this._env);
                    }
                } catch(e) {}
            }
        }
    },

    // ── Echo Shaper Registry ──
    _shapers: {},

    registerShaper(name, level, fn) {
        this._shapers[name] = { name: name, level: level, fn: fn };
    },

    // Run a shaper on frame data
    shape(name, frameData) {
        var shaper = this._shapers[name];
        if (!shaper) return null;
        return shaper.fn(frameData);
    },

    // List registered shapers
    getShapers() {
        return Object.values(this._shapers);
    }
};
