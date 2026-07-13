#!/usr/bin/env node
'use strict';

const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const vm = require('vm');

function loadObject(path, name, context) {
    const source = fs.readFileSync(path, 'utf8');
    return vm.runInContext(`${source}\n;${name};`, context);
}

function testEscapingAndCredentialRemoval() {
    const context = vm.createContext({ console, Math, Number, String });
    const config = fs.readFileSync('src/js/config.js', 'utf8');
    const helpers = vm.runInContext(`${config}\n;({ escapeHTML });`, context);
    assert.strictEqual(
        helpers.escapeHTML('<img src=x onerror="globalThis.pwned=true">'),
        '&lt;img src=x onerror=&quot;globalThis.pwned=true&quot;&gt;'
    );

    const agents = fs.readFileSync('src/js/world-agents.js', 'utf8');
    const main = fs.readFileSync('src/js/main.js', 'utf8');
    assert(!agents.includes("getItem('rappterverse-token')"), 'browser must not read a GitHub token');
    assert(!agents.includes('/dispatches'), 'browser must not send authenticated repository dispatches');
    assert(main.includes("removeItem('rappterverse-token')"), 'legacy browser tokens must be removed on startup');

    const hud = fs.readFileSync('src/js/hud.js', 'utf8');
    const quests = fs.readFileSync('src/js/quests.js', 'utf8');
    assert(hud.includes('escapeHTML(text)'), 'chat content must be escaped');
    assert(hud.includes('escapeHTML(author)'), 'chat authors must be escaped');
    assert(quests.includes('escapeHTML(q.description'), 'quest descriptions must be escaped');
}

function testLispSandbox() {
    const context = vm.createContext({
        console,
        Date,
        Math,
        Object,
        Array,
        Number,
        String,
        Boolean,
        JSON,
        setTimeout,
        clearTimeout
    });
    const machine = loadObject('src/js/rappter-vm.js', 'RappterVM', context);
    machine.init();
    context.WorldAgents = {
        agentMeshes: {
            alpha: {
                group: { position: { x: 0, z: 0 }, rotation: { y: 0 } },
                homePos: { x: 0, z: 0 }
            },
            beta: {
                group: { position: { x: 0, z: 0 }, rotation: { y: 0 } },
                homePos: { x: 0, z: 0 }
            }
        }
    };

    const canary = machine.parse(
        '(let (ctor (get + "constructor")) (ctor "globalThis.__vmPwned = true"))'
    );
    canary.forEach(form => machine.run(form, machine._env));
    assert.strictEqual(context.__vmPwned, undefined, 'constructor chain escaped the evaluator');

    const nthCanary = machine.parse(
        '(let (ctor (nth + "constructor") pwn (ctor "globalThis.__vmPwned = 42")) (pwn))'
    );
    nthCanary.forEach(form => machine.run(form, machine._env));
    assert.strictEqual(context.__vmPwned, undefined, 'nth escaped the evaluator');

    machine._activePrincipal = 'alpha';
    machine._env['move-toward']('beta', 10, 0, 1);
    assert.strictEqual(context.WorldAgents.agentMeshes.beta.group.position.x, 0, 'routine acted as another agent');
    machine._env['move-toward']('alpha', 10, 0, 1);
    assert.strictEqual(context.WorldAgents.agentMeshes.alpha.group.position.x, 1, 'routine could not act as itself');
    machine._activePrincipal = null;

    const alphaEnv = Object.create(machine._env);
    const betaEnv = Object.create(machine._env);
    machine.run(machine.parse('(def private-value 7)')[0], alphaEnv);
    assert.strictEqual(machine._lookup('private-value', betaEnv), null, 'agent definition leaked across principals');
    assert.throws(
        () => machine.run(machine.parse('(def move-toward 1)')[0], alphaEnv),
        /immutable/
    );

    for (const file of fs.readdirSync('state/programs/_lispvm').filter(name => name.endsWith('.lisp'))) {
        machine.parse(fs.readFileSync(`state/programs/_lispvm/${file}`, 'utf8'));
    }

    assert.throws(
        () => machine.parse('('.repeat(70) + '1' + ')'.repeat(70)),
        /depth/
    );
    assert.throws(
        () => machine.parse('(do ' + '1 '.repeat(5000) + ')'),
        /token budget/
    );
    assert.throws(
        () => machine.parse('1 '.repeat(129)),
        /form budget/
    );

    const oversized = '(map (fn (x) x) (quote (' + '1 '.repeat(257) + ')))';
    assert.throws(
        () => machine.run(machine.parse(oversized)[0], machine._env),
        /collection budget/
    );

    const hundred = '1 '.repeat(100);
    const nested = '(map (fn (x) (map + (quote (' + hundred + ')))) '
        + '(quote (' + hundred + ')))';
    assert.throws(
        () => machine.run(machine.parse(nested)[0], machine._env),
        /evaluation budget/
    );

    const frameProgram = machine.parse(
        '(map + (quote (' + '1 '.repeat(250) + ')))'
    );
    machine._programs = {};
    machine._agentEnvs = {};
    for (let index = 0; index < 140; index++) {
        const id = `budget-${index}`;
        machine._programs[id] = frameProgram;
        machine._agentEnvs[id] = Object.create(machine._env);
    }
    machine._running = true;
    machine._tickCount = 2;
    machine.tick();
    assert.strictEqual(machine._budgetExhausted, true, 'global frame budget was not enforced');
    assert(
        machine._frameEvalSteps <= machine._limits.frameEvalSteps + 1,
        'frame budget substantially overran its cap'
    );
}

function responseFor(path) {
    if (path === 'state/agents.json') return { agents: [{ id: 'safe-001', world: 'hub' }] };
    if (path === 'state/chat.json') return { messages: [] };
    if (path === 'state/actions.json') return { actions: [] };
    if (path === 'state/npcs.json') return { npcs: [] };
    if (path === 'state/game_state.json') return { _meta: {}, worlds: {} };
    if (path === 'state/frame_counter.json') return { frame: 1 };
    if (path === 'state/programs/_lispvm/_status.json') return { agents: {} };
    if (path === 'state/chronicles.json') return { chronicles: [] };
    if (path.endsWith('/config.json')) return { id: path.split('/')[1] };
    if (path.endsWith('/objects.json')) return { objects: [] };
    throw new Error(`unexpected path: ${path}`);
}

async function testCanonicalStagedPolling() {
    const urls = [];
    let failedPath = null;
    let tamperedPath = null;
    let manager = null;
    const document = {
        body: { appendChild() {} },
        getElementById() { return null; },
        querySelector() { return null; },
        createElement() { return { style: {}, textContent: '' }; }
    };
    const GameState = {
        debug: false,
        data: {
            agents: [],
            chat: [],
            actions: [],
            npcs: [],
            gameState: {},
            frameCounter: {},
            brainstem: {},
            chronicles: {},
            worldConfigs: {},
            worldObjects: {}
        }
    };
    const context = vm.createContext({
        console,
        Date,
        Error,
        Promise,
        Set,
        AbortController,
        TextEncoder,
        crypto: crypto.webcrypto,
        setTimeout,
        clearTimeout,
        document,
        GameState,
        Chronicle: { onData() { throw new Error('consumer failure'); } },
        RAW: 'https://raw.githubusercontent.com/kody-w/rappterverse/main',
        POLL_INTERVAL: 15000,
        fetch: async url => {
            urls.push(url);
            const path = url.split('/main/')[1].split('?')[0];
            if (path === failedPath) return { ok: false, status: 503 };
            let content;
            if (path === 'state/snapshot.json') {
                const resources = {};
                for (const resource of manager._resources) {
                    const payload = JSON.stringify(responseFor(resource[1]));
                    resources[resource[1]] = {
                        sha256: crypto.createHash('sha256').update(payload).digest('hex'),
                        bytes: Buffer.byteLength(payload)
                    };
                }
                content = JSON.stringify({
                    _meta: {lastUpdate: '2026-01-01T00:00:00Z', version: 1},
                    revision: 'a'.repeat(64),
                    resources
                });
            } else {
                const payload = responseFor(path);
                if (path === tamperedPath) payload._tampered = true;
                content = JSON.stringify(payload);
            }
            return {
                ok: true,
                status: 200,
                json: async () => JSON.parse(content),
                text: async () => content
            };
        }
    });
    manager = loadObject('src/js/data.js', 'DataManager', context);

    const first = manager.fetchAllState();
    const duplicate = manager.fetchAllState();
    assert.strictEqual(first, duplicate, 'concurrent callers must share one poll');
    const firstResult = await first;
    assert.strictEqual(firstResult.ok, true);
    assert.strictEqual(
        urls.length,
        manager._resources.length + 1,
        'one poll should fetch the manifest and each declared resource once'
    );
    assert(urls.every(url => url.includes('/main/')), 'polling used a non-canonical branch');

    const lastKnownAgents = GameState.data.agents;
    const requestsAfterFirst = urls.length;
    const unchangedResult = await manager.fetchAllState();
    assert.strictEqual(unchangedResult.unchanged, true);
    assert.strictEqual(
        urls.length - requestsAfterFirst,
        1,
        'unchanged snapshot fetched more than the manifest'
    );

    manager.currentRevision = null;
    failedPath = 'state/agents.json';
    const failedResult = await manager.fetchAllState();
    assert.strictEqual(failedResult.ok, false);
    assert.strictEqual(
        GameState.data.agents,
        lastKnownAgents,
        'failed snapshot replaced last-known-good state'
    );

    failedPath = null;
    manager.currentRevision = null;
    tamperedPath = 'state/actions.json';
    const tamperedResult = await manager.fetchAllState();
    assert.strictEqual(tamperedResult.ok, false, 'hash mismatch was accepted');
    assert.strictEqual(
        GameState.data.agents,
        lastKnownAgents,
        'hash mismatch partially replaced last-known-good state'
    );
}

function createPostProcessingHarness(userAgent, failAllocation) {
    let allocations = 0;
    class RenderTarget {
        constructor() {
            allocations++;
            if (failAllocation) throw new Error('allocation failed');
            this.texture = {};
        }
        setSize() {}
        dispose() {}
    }
    class Scene { add() {} }
    class Camera {}
    class Vector2 { set() {} }
    class Material {
        constructor(options) { this.uniforms = options.uniforms; }
        dispose() {}
    }
    class Geometry {
        clone() { return new Geometry(); }
        dispose() {}
    }
    class Mesh {
        constructor(geometry, material) {
            this.geometry = geometry;
            this.material = material;
        }
    }
    const context = vm.createContext({
        console,
        navigator: { userAgent, maxTouchPoints: /iPad/.test(userAgent) ? 5 : 0 },
        window: { innerWidth: 1280, innerHeight: 720 },
        GameState: { debug: false },
        THREE: {
            WebGLRenderTarget: RenderTarget,
            Scene,
            OrthographicCamera: Camera,
            Vector2,
            ShaderMaterial: Material,
            PlaneGeometry: Geometry,
            Mesh,
            LinearFilter: 1,
            RGBAFormat: 1
        }
    });
    const post = loadObject('src/js/post-processing.js', 'PostProcessing', context);
    const renderer = {
        renders: 0,
        targets: [],
        render() { this.renders++; },
        setRenderTarget(target) { this.targets.push(target); }
    };
    return { post, renderer, allocations: () => allocations };
}

function testCapabilitySafePostProcessing() {
    const mobile = createPostProcessingHarness('iPhone', false);
    mobile.post.setEnabled(true);
    assert.strictEqual(mobile.post.init(mobile.renderer), false);
    assert.strictEqual(mobile.allocations(), 0);
    mobile.post.render(mobile.renderer, {}, {});
    assert.strictEqual(mobile.renderer.renders, 1, 'mobile did not use direct rendering');

    const disabled = createPostProcessingHarness('Desktop', false);
    disabled.post.setEnabled(false);
    assert.strictEqual(disabled.post.init(disabled.renderer), true);
    assert.strictEqual(disabled.post.enabled, false, 'saved bloom=false was overwritten');
    assert.strictEqual(disabled.allocations(), 0, 'disabled bloom allocated render targets');
    disabled.post.render(disabled.renderer, {}, {});
    assert.strictEqual(disabled.renderer.renders, 1);

    const desktop = createPostProcessingHarness('Desktop', false);
    desktop.post.setEnabled(true);
    assert.strictEqual(desktop.post.init(desktop.renderer), true);
    desktop.post.render(desktop.renderer, {}, {});
    assert.strictEqual(desktop.renderer.renders, 3, 'desktop bloom did not execute three render passes');

    const failed = createPostProcessingHarness('Desktop', true);
    failed.post.setEnabled(true);
    assert.strictEqual(failed.post.init(failed.renderer), false);
    failed.post.render(failed.renderer, {}, {});
    assert.strictEqual(failed.renderer.renders, 1, 'allocation failure did not fall back');
}

function testDashboardTrustBoundary() {
    const dashboard = fs.readFileSync('docs/dashboard.html', 'utf8');
    assert(!/onclick="open(?:Agent|Sub)\('\$\{/.test(dashboard), 'remote IDs remain in inline handlers');
    assert(!dashboard.includes('tooltip.innerHTML'), 'graph tooltip still executes remote HTML');
    assert(dashboard.includes("${esc(a.avatar||'👤')}"), 'agent avatars are not escaped');
    assert(dashboard.includes("const weather = esc(wi.weather || '')"), 'weather is not escaped');
    assert(dashboard.includes('safeExternalUrl(r.html_url)'), 'workflow URLs are not validated');
    const escBody = dashboard.match(/function esc\(s\) \{([\s\S]*?)\n\}/);
    assert(escBody, 'dashboard escape helper missing');
    const dashboardEscape = new Function('s', escBody[1]);
    assert.strictEqual(
        dashboardEscape(`https://example.com/\"onmouseover=\"alert(1)'`),
        'https://example.com/&quot;onmouseover=&quot;alert(1)&#39;'
    );

    const inlineScripts = [...dashboard.matchAll(/<script>([\s\S]*?)<\/script>/g)];
    assert(inlineScripts.length > 0, 'dashboard script missing');
    inlineScripts.forEach(match => new Function(match[1]));
}

function testLocalPracticeBoundary() {
    const state = fs.readFileSync('src/js/state.js', 'utf8');
    const agents = fs.readFileSync('src/js/world-agents.js', 'utf8');
    const layout = fs.readFileSync('src/html/layout.html', 'utf8');
    const shop = fs.readFileSync('src/js/shop.js', 'utf8');
    const stats = fs.readFileSync('src/js/player-stats.js', 'utf8');
    const quests = fs.readFileSync('src/js/quests.js', 'utf8');
    assert(state.includes('localChat: []'), 'local overlay state is missing');
    assert(agents.includes('GameState.data.localChat.push(pokeMsg)'), 'local poke mutates canonical chat');
    assert(!agents.includes('GameState.data.chat.push(pokeMsg)'), 'canonical chat is mutated by local poke');
    assert(layout.includes('LOCAL PRACTICE'), 'local practice mode is not visible');
    assert(layout.includes('MAIN · SYNCING'), 'canonical main status is not visible');
    assert(shop.includes('LOCAL PRACTICE SHOP'), 'shop authority is ambiguous');
    assert(stats.includes('Practice Gold'), 'local currency is still presented as canonical gold');
    assert(quests.includes('GameState.data.localChat'), 'local poke cannot progress local guide quest');
    const main = fs.readFileSync('src/js/main.js', 'utf8');
    const bridge = fs.readFileSync('src/js/bridge.js', 'utf8');
    assert(main.includes('if (Bridge.open) return;'), 'main loop renders behind Bridge');
    assert(!main.includes("e.code === 'Tab' && GameState.mode === 'world'"), 'Tab still hijacks focus');
    assert(main.includes('if (e.shiftKey) HUD.toggleFullmap()'), 'full map lost keyboard access');
    assert(!main.includes('Math.floor(time) % 3'), 'main loop still redraws Bridge screens');
    assert(
        bridge.includes("!['galaxy', 'world'].includes(GameState.mode)"),
        'Bridge can still open during transition render loops'
    );
}

function testAbilityOwnedResourceDisposal() {
    const source = fs.readFileSync('src/js/abilities.js', 'utf8');
    assert(source.includes('_disposeOwnedMesh(mesh)'), 'ability disposal helper missing');
    assert(
        source.includes('this._disposeOwnedMesh(p.mesh)'),
        'expired projectiles are not disposed'
    );
    assert(
        source.includes('this._disposeOwnedMesh(e.mesh)'),
        'expired ability effects are not disposed'
    );
    assert(
        source.includes('clearInterval(this._novaShakeTimer)'),
        'Nova timer survives cleanup'
    );
}

function testSnapshotManifestParity() {
    const source = fs.readFileSync('src/js/data.js', 'utf8');
    const declared = [...source.matchAll(/\['[^']+', '([^']+\.json)', true\]/g)]
        .map(match => match[1])
        .sort();
    const snapshot = JSON.parse(fs.readFileSync('state/snapshot.json', 'utf8'));
    const manifested = Object.keys(snapshot.resources).sort();
    assert.deepStrictEqual(manifested, declared, 'frontend resources drifted from snapshot manifest');
    if (process.env.ALLOW_DERIVED_STATE_DRIFT === '1') return;
    for (const resourcePath of manifested) {
        const content = fs.readFileSync(resourcePath);
        assert.strictEqual(
            snapshot.resources[resourcePath].sha256,
            crypto.createHash('sha256').update(content).digest('hex'),
            `${resourcePath} hash drifted from snapshot manifest`
        );
    }
}

async function main() {
    testEscapingAndCredentialRemoval();
    testLispSandbox();
    await testCanonicalStagedPolling();
    testCapabilitySafePostProcessing();
    testDashboardTrustBoundary();
    testLocalPracticeBoundary();
    testSnapshotManifestParity();
    testAbilityOwnedResourceDisposal();
    console.log('Frontend trust and polling tests passed');
}

main().catch(error => {
    console.error(error);
    process.exit(1);
});
