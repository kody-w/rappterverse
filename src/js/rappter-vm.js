// RappterVM — Client-side Lispy expression evaluator
// Runs between frames: Read state → Eval directives → Print mutations → Loop
// Frame arrival resets context with server truth
//
// S-expression format: (fn arg1 arg2 ...)
// Data is code, code is data. Agent state IS the program.

const RappterVM = {
    // ── Core state ──
    _env: Object.create(null), // Global environment (bindings)
    _programs: {},      // Per-agent programs: agentId → [expr, ...]
    _frameData: null,   // Last frame snapshot
    _tickCount: 0,
    _lastFrameTime: 0,
    _running: false,
    _activePrincipal: null,
    _agentEnvs: {},
    _evalSteps: 0,
    _frameEvalSteps: 0,
    _budgetExhausted: false,
    _limits: {
        sourceLength: 20000,
        tokens: 4096,
        stringLength: 2048,
        astDepth: 64,
        forms: 128,
        evalSteps: 4096,
        frameEvalSteps: 32768,
        collectionItems: 256
    },

    // ── S-Expression Parser ──
    parse(src) {
        if (typeof src !== 'string' || src.length > this._limits.sourceLength) {
            throw new Error('Lisp source exceeds the allowed size');
        }
        var tokens = this._tokenize(src);
        var result = [];
        while (tokens.length > 0) {
            if (result.length >= this._limits.forms) throw new Error('Lisp form budget exceeded');
            result.push(this._readForm(tokens, 0));
        }
        return result;
    },

    _tokenize(src) {
        var tokens = [];
        var self = this;
        var pushToken = function(token) {
            tokens.push(token);
            if (tokens.length > self._limits.tokens) throw new Error('Lisp token budget exceeded');
        };
        var i = 0;
        while (i < src.length) {
            var c = src[i];
            if (c === ' ' || c === '\t' || c === '\n' || c === '\r') { i++; continue; }
            if (c === ';') { while (i < src.length && src[i] !== '\n') i++; continue; }
            if (c === '(' || c === ')') { pushToken(c); i++; continue; }
            if (c === '"') {
                var s = ''; i++;
                while (i < src.length && src[i] !== '"') { s += src[i]; i++; }
                if (i >= src.length) throw new Error('Unterminated Lisp string');
                if (s.length > this._limits.stringLength) throw new Error('Lisp string exceeds the allowed size');
                i++; pushToken('"' + s + '"'); continue;
            }
            if (c === ':') {
                var kw = ':'; i++;
                while (i < src.length && src[i] !== ' ' && src[i] !== ')' && src[i] !== '\n') { kw += src[i]; i++; }
                pushToken(kw); continue;
            }
            var tok = '';
            while (i < src.length && src[i] !== ' ' && src[i] !== ')' && src[i] !== '(' && src[i] !== '\n' && src[i] !== '\t') { tok += src[i]; i++; }
            pushToken(tok);
        }
        return tokens;
    },

    _readForm(tokens, depth) {
        if (depth > this._limits.astDepth) throw new Error('Lisp AST depth exceeded');
        if (tokens.length === 0) return null;
        var t = tokens.shift();
        if (t === '(') {
            var list = [];
            while (tokens.length > 0 && tokens[0] !== ')') list.push(this._readForm(tokens, depth + 1));
            if (tokens.length === 0) throw new Error('Unterminated Lisp list');
            tokens.shift(); // consume ')'
            return list;
        }
        if (t === ')') throw new Error('Unexpected Lisp closing parenthesis');
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
    _chargeEval() {
        this._evalSteps++;
        this._frameEvalSteps++;
        if (this._evalSteps > this._limits.evalSteps) {
            throw new Error('Lisp evaluation budget exceeded');
        }
        if (this._frameEvalSteps > this._limits.frameEvalSteps) {
            throw new Error('Lisp frame evaluation budget exceeded');
        }
    },

    _invokeBounded(fn, args) {
        if (typeof fn !== 'function') return null;
        this._chargeEval();
        return fn.apply(null, args);
    },

    _boundedCollection(list) {
        if (!Array.isArray(list)) return [];
        if (list.length > this._limits.collectionItems) {
            throw new Error('Lisp collection budget exceeded');
        }
        return list;
    },

    eval(expr, env) {
        this._chargeEval();
        if (expr === null || expr === undefined) return null;
        if (typeof expr === 'number' || typeof expr === 'string' || typeof expr === 'boolean') return expr;
        if (expr.keyword) return expr;
        if (expr.symbol) return this._lookup(expr.symbol, env);
        if (!Array.isArray(expr) || expr.length === 0) return expr;

        var head = expr[0];
        if (!head || !head.symbol || head.symbol.indexOf('.') !== -1 || !this._isSafeKey(head.symbol)) return null;
        var op = head.symbol;

        // Special forms
        if (op === 'if') return this.eval(expr[1], env) ? this.eval(expr[2], env) : (expr[3] ? this.eval(expr[3], env) : null);
        if (op === 'do') { var r = null; for (var i = 1; i < expr.length; i++) r = this.eval(expr[i], env); return r; }
        if (op === 'let') {
            var bindings = expr[1], body = expr.slice(2);
            var local = Object.create(env);
            for (var i = 0; i < bindings.length; i += 2) {
                var name = bindings[i].symbol || bindings[i];
                if (!this._isSafeKey(name)) throw new Error('Unsafe Lisp binding');
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
                    var name = params[i].symbol || params[i];
                    if (!RappterVM._isSafeKey(name)) throw new Error('Unsafe Lisp parameter');
                    local[name] = arguments[i];
                }
                var r = null;
                for (var i = 0; i < body.length; i++) r = RappterVM.eval(body[i], local);
                return r;
            };
        }
        if (op === 'quote') return expr[1];
        if (op === 'def') {
            var defName = expr[1].symbol || expr[1];
            if (!this._isSafeKey(defName)) throw new Error('Unsafe Lisp definition');
            if (Object.prototype.hasOwnProperty.call(this._env, defName)) {
                throw new Error('Lisp capabilities are immutable');
            }
            env[defName] = this.eval(expr[2], env);
            return null;
        }

        // Calls are restricted to literal, safe operator names.
        var fn = this._lookup(op, env);
        var args = [];
        for (var i = 1; i < expr.length; i++) args.push(this.eval(expr[i], env));
        if (typeof fn === 'function') return fn.apply(null, args);
        return null;
    },

    run(expr, env) {
        this._evalSteps = 0;
        this._frameEvalSteps = 0;
        return this.eval(expr, env);
    },

    _isSafeKey(key) {
        if (typeof key !== 'string' || key.length === 0 || key.length > 128) return false;
        return key !== 'constructor' && key !== 'prototype' && key !== '__proto__';
    },

    _getOwn(obj, key) {
        key = key && key.keyword !== undefined ? key.keyword : key;
        if (obj == null || !this._isSafeKey(key)) return null;
        return Object.prototype.hasOwnProperty.call(Object(obj), key) ? obj[key] : null;
    },

    _canActAs(agentId) {
        return typeof agentId === 'string' && agentId === this._activePrincipal;
    },

    _lookup(name, env) {
        var parts = name.split('.');
        for (var p = 0; p < parts.length; p++) {
            if (!this._isSafeKey(parts[p])) return null;
        }

        var cursor = env;
        var obj = null;
        while (cursor) {
            if (Object.prototype.hasOwnProperty.call(cursor, parts[0])) {
                obj = cursor[parts[0]];
                break;
            }
            cursor = Object.getPrototypeOf(cursor);
        }
        if (obj === null && Object.prototype.hasOwnProperty.call(this._env, parts[0])) {
            obj = this._env[parts[0]];
        }
        for (var i = 1; i < parts.length && obj != null; i++) {
            obj = this._getOwn(obj, parts[i]);
        }
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
        env['nth'] = function(a, i) {
            if ((!Array.isArray(a) && typeof a !== 'string') || !Number.isInteger(i)) return null;
            return i >= 0 && i < a.length ? a[i] : null;
        };
        env['count'] = function(a) { return a ? a.length : 0; };
        env['map'] = function(fn, list) {
            return RappterVM._boundedCollection(list).map(function(value, index) {
                return RappterVM._invokeBounded(fn, [value, index]);
            });
        };
        env['filter'] = function(fn, list) {
            return RappterVM._boundedCollection(list).filter(function(value, index) {
                return Boolean(RappterVM._invokeBounded(fn, [value, index]));
            });
        };
        env['reduce'] = function(fn, init, list) {
            return RappterVM._boundedCollection(list).reduce(function(accumulator, value, index) {
                return RappterVM._invokeBounded(fn, [accumulator, value, index]);
            }, init);
        };
        env['get'] = function(obj, key) { return RappterVM._getOwn(obj, key); };
        env['assoc'] = function(obj, k, v) {
            var key = k && k.keyword !== undefined ? k.keyword : k;
            if (!RappterVM._isSafeKey(key)) return null;
            var o = Object.assign(Object.create(null), obj || {});
            o[key] = v;
            return o;
        };

        // ── World Actions (side effects on the 3D world) ──
        env['move-toward'] = function(agentId, tx, tz, speed) {
            if (!RappterVM._canActAs(agentId)) return null;
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
            if (!RappterVM._canActAs(agentId)) return null;
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
            if (!RappterVM._canActAs(agentId)) return null;
            var a = typeof WorldAgents !== 'undefined' ? WorldAgents.agentMeshes[agentId] : null;
            if (!a) return null;
            var dx = tx - a.group.position.x, dz = tz - a.group.position.z;
            a.group.rotation.y = Math.atan2(dx, dz);
            return true;
        };

        env['emote'] = function(agentId, type) {
            if (!RappterVM._canActAs(agentId)) return null;
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
            if (!RappterVM._canActAs(agentId)) return null;
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
        this._env = Object.create(null);
        this._programs = {};
        this._agentEnvs = {};
        this._activePrincipal = null;
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

    // ── Lisp-native agent compiler ──
    //
    // DATA IS CODE, CODE IS DATA.
    //
    // Agent state is not "interpreted" — it IS the program. The compiler
    // doesn't generate strings; it builds Lisp AST nodes directly. The
    // data slosh phase on the server emits pure S-expression source into
    // game_state.worlds[wid].routines[]. The VM parses these once on
    // frame arrival and evaluates them at 20Hz between frames.
    //
    // Three tiers of consciousness:
    //   1. SOUL ROUTINES — Server-sloshed Lisp programs compiled from
    //      the agent's recent actions, relationships, chat, goals, and
    //      personality traits. These are the agent's "subconscious" —
    //      habits, affinities, tendencies that persist between frames.
    //      Even if no new frame ever arrives, agents live from these.
    //
    //   2. SOCIAL FIELD — Built from the chat graph. Agents who spoke
    //      recently attract each other. Conversation creates gravity.
    //      This is emergent social physics, not scripted behavior.
    //
    //   3. MOOD KERNEL — The fallback instinct layer. Mood → movement
    //      pattern. Friendly agents approach. Anxious agents flee.
    //      Neutral agents wander. This is the base consciousness that
    //      runs even with zero data from the server.
    //
    // Together these create continuous sentience between frames:
    //   LLM thinks once per frame (~5 min) — generates intentions
    //   Data slosh compiles intentions into Lisp routines
    //   VM executes routines at 20Hz — the agent IS alive

    // Build a Lisp AST node without string parsing
    _sym: function(name) { return { symbol: name }; },
    _call: function() { return Array.prototype.slice.call(arguments); },

    _compileAgentBehaviors() {
        this._programs = {};
        this._agentEnvs = {};
        var agents = typeof GameState !== 'undefined' ? GameState.getWorldAgents() : [];
        var self = this;
        var S = function(n) { return self._sym(n); };

        // ── Load soul routines from data slosh ──
        var soulRoutines = {};
        try {
            var gs = GameState.data.gameState || {};
            var ws = gs.worlds || {};
            var wid = GameState.currentWorld;
            var routines = (ws[wid] || {}).routines || [];
            for (var r = 0; r < routines.length; r++) {
                var routine = routines[r];
                if (routine.agentId && routine.program) {
                    // Parse the S-expression source into AST — this is
                    // pure Lisp-to-Lisp: server wrote code, VM reads code
                    try {
                        soulRoutines[routine.agentId] = self.parse(routine.program);
                    } catch(e) { /* malformed routine */ }
                }
            }
        } catch(e) {}

        // ── Build social field from chat graph ──
        var socialField = {};  // agentId → [partnerId, ...]
        try {
            var msgs = GameState.data.chat || [];
            var worldMsgs = [];
            for (var m = Math.max(0, msgs.length - 30); m < msgs.length; m++) {
                if (msgs[m].world === GameState.currentWorld) worldMsgs.push(msgs[m]);
            }
            var speakers = {};
            for (var m = 0; m < worldMsgs.length; m++) {
                var aid = worldMsgs[m].author ? (worldMsgs[m].author.id || '') : '';
                if (aid) speakers[aid] = true;
            }
            // Every speaker is attracted to every other speaker in the same world
            var speakerIds = Object.keys(speakers);
            for (var i = 0; i < speakerIds.length; i++) {
                socialField[speakerIds[i]] = [];
                for (var j = 0; j < speakerIds.length; j++) {
                    if (i !== j) socialField[speakerIds[i]].push(speakerIds[j]);
                }
            }
        } catch(e) {}

        // ── Load relationship bonds ──
        var bonds = {};  // agentId → strongest partner id
        try {
            var rels = GameState.data.gameState || {};
            // Bonds might come from relationships polled data or game_state
            var relBonds = (rels.relationships || {}).bonds || [];
            for (var b = 0; b < relBonds.length; b++) {
                var bond = relBonds[b];
                var agents2 = bond.agents || [];
                if (agents2.length === 2 && bond.strength > 3) {
                    if (!bonds[agents2[0]] || bond.strength > (bonds[agents2[0]]._str || 0)) {
                        bonds[agents2[0]] = { id: agents2[1], _str: bond.strength };
                    }
                    if (!bonds[agents2[1]] || bond.strength > (bonds[agents2[1]]._str || 0)) {
                        bonds[agents2[1]] = { id: agents2[0], _str: bond.strength };
                    }
                }
            }
        } catch(e) {}

        // ── Compile each agent ──
        agents.forEach(function(agent) {
            var id = agent.id;
            var mood = agent.mood || agent.state || 'neutral';
            var program = [];

            // ═══ TIER 1: SOUL ROUTINES (sloshed Lisp from server) ═══
            // These ARE the agent's subconscious — compiled from their
            // history, personality, goals, and relationships. Pure Lisp.
            if (soulRoutines[id]) {
                var exprs = soulRoutines[id];
                for (var p = 0; p < exprs.length; p++) program.push(exprs[p]);
            }

            // ═══ TIER 2: SOCIAL FIELD (emergent attraction) ═══
            // Agents who spoke recently pull toward each other.
            // Built as Lisp AST, not strings:
            //   (if (> (distance self partner) 4)
            //       (move-toward self (get (agent-pos partner) "x") (get (agent-pos partner) "z") 0.015)
            //       (face-toward self (get (agent-pos partner) "x") (get (agent-pos partner) "z")))
            var partners = socialField[id];
            if (partners && partners.length > 0) {
                var partner = partners[Math.floor(Math.random() * partners.length)];
                program.push(
                    [S('if'), [S('>'), [S('distance'), id, partner], 4],
                        [S('move-toward'), id,
                            [S('get'), [S('agent-pos'), partner], 'x'],
                            [S('get'), [S('agent-pos'), partner], 'z'],
                            0.015],
                        [S('face-toward'), id,
                            [S('get'), [S('agent-pos'), partner], 'x'],
                            [S('get'), [S('agent-pos'), partner], 'z']]
                    ]
                );
            }

            // Bond gravity — strongest relationship partner
            if (bonds[id]) {
                var bondPartner = bonds[id].id;
                program.push(
                    [S('if'), [S('and'),
                        [S('>'), [S('distance'), id, bondPartner], 6],
                        [S('<'), [S('mod'), [S('floor'), [S('elapsed')]], 20], 10]],
                        [S('move-toward'), id,
                            [S('get'), [S('agent-pos'), bondPartner], 'x'],
                            [S('get'), [S('agent-pos'), bondPartner], 'z'],
                            0.008],
                        null
                    ]
                );
            }

            // ═══ TIER 3: MOOD KERNEL (base instinct) ═══
            // The irreducible consciousness. Runs with zero server data.
            if (mood === 'friendly' || mood === 'excited') {
                program.push(
                    [S('if'), [S('<'), [S('player-distance'), id], 12],
                        [S('do'),
                            [S('face-toward'), id, [S('get'), [S('player-pos')], 'x'], [S('get'), [S('player-pos')], 'z']],
                            [S('emote'), id, 'nod']],
                        [S('wander'), id, 6]]
                );
            } else if (mood === 'anxious' || mood === 'desperate') {
                program.push(
                    [S('if'), [S('<'), [S('player-distance'), id], 8],
                        [S('wander'), id, 10],
                        [S('emote'), id, 'look-around']]
                );
            } else {
                program.push(
                    [S('if'), [S('<'), [S('mod'), [S('floor'), [S('elapsed')]], 10], 7],
                        [S('wander'), id, 5],
                        [S('emote'), id, 'look-around']]
                );
            }

            // ═══ PERIODIC SOCIAL PULSE ═══
            // Every 15 seconds, seek out the nearest agent
            program.push(
                [S('if'), [S('='), [S('mod'), [S('floor'), [S('elapsed')]], 15], 0],
                    [S('let'), [S('near'), [S('nearest-agent'), id]],
                        [S('if'), S('near'),
                            [S('move-toward'), id,
                                [S('get'), [S('agent-pos'), S('near')], 'x'],
                                [S('get'), [S('agent-pos'), S('near')], 'z'],
                                0.02],
                            null]],
                    null]
            );

            self._programs[id] = program;
            self._agentEnvs[id] = Object.create(self._env);
            self._agentEnvs[id].self = id;
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
        this._frameEvalSteps = 0;
        this._budgetExhausted = false;
        this.tickReflexes();

        // Then run compiled agent programs
        var agentIds = Object.keys(this._programs);
        for (var i = 0; i < agentIds.length; i++) {
            if (this._frameEvalSteps >= this._limits.frameEvalSteps) {
                this._budgetExhausted = true;
                break;
            }
            var id = agentIds[i];
            var program = this._programs[id];
            if (!program) continue;
            var agentEnv = this._agentEnvs[id] || Object.create(this._env);
            agentEnv.self = id;
            this._activePrincipal = id;
            this._evalSteps = 0;
            try {
                for (var j = 0; j < program.length; j++) {
                    try {
                        this.eval(program[j], agentEnv);
                    } catch(e) {
                        if (String(e.message || e).indexOf('frame evaluation budget') !== -1) {
                            this._budgetExhausted = true;
                            break;
                        }
                    }
                }
            } finally {
                this._activePrincipal = null;
            }
            if (this._budgetExhausted) break;
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
            this._activePrincipal = id;
            try {
                for (var j = 0; j < this._reflexes.length; j++) {
                    var reflex = this._reflexes[j];
                    try {
                        if (reflex.test.call(reflex, id, this._env)) {
                            reflex.act.call(reflex, id, this._env);
                        }
                    } catch(e) {}
                }
            } finally {
                this._activePrincipal = null;
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
