#!/usr/bin/env node
'use strict';

const assert = require('assert');
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

    const canary = machine.parse('(((get + "constructor") "globalThis.__vmPwned = true"))');
    canary.forEach(form => machine.run(form, machine._env));
    assert.strictEqual(context.__vmPwned, undefined, 'constructor chain escaped the evaluator');

    const nthCanary = machine.parse(
        '(let (ctor (nth + "constructor") pwn (ctor "globalThis.__vmPwned = 42")) (pwn))'
    );
    nthCanary.forEach(form => machine.run(form, machine._env));
    assert.strictEqual(context.__vmPwned, undefined, 'nth escaped the evaluator');

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
}

function responseFor(path) {
    if (path === 'state/agents.json') return { agents: [{ id: 'safe-001', world: 'hub' }] };
    if (path === 'state/chat.json') return { messages: [] };
    if (path === 'state/actions.json') return { actions: [] };
    if (path === 'state/npcs.json') return { npcs: [] };
    if (path === 'state/game_state.json') return { _meta: {}, worlds: {} };
    if (path === 'state/frame_counter.json') return { frame: 1 };
    if (path === 'state/programs/_lispvm/_status.json') return { agents: {} };
    if (path.endsWith('/config.json')) return { id: path.split('/')[1] };
    if (path.endsWith('/objects.json')) return { objects: [] };
    throw new Error(`unexpected path: ${path}`);
}

async function testCanonicalStagedPolling() {
    const urls = [];
    let failedPath = null;
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
        setTimeout,
        clearTimeout,
        document,
        GameState,
        RAW: 'https://raw.githubusercontent.com/kody-w/rappterverse/main',
        POLL_INTERVAL: 15000,
        fetch: async url => {
            urls.push(url);
            const path = url.split('/main/')[1].split('?')[0];
            if (path === failedPath) return { ok: false, status: 503 };
            return { ok: true, status: 200, json: async () => responseFor(path) };
        }
    });
    const manager = loadObject('src/js/data.js', 'DataManager', context);

    const first = manager.fetchAllState();
    const duplicate = manager.fetchAllState();
    assert.strictEqual(first, duplicate, 'concurrent callers must share one poll');
    const firstResult = await first;
    assert.strictEqual(firstResult.ok, true);
    assert.strictEqual(urls.length, 17, 'one poll should fetch each resource once');
    assert(urls.every(url => url.includes('/main/')), 'polling used a non-canonical branch');

    const lastKnownAgents = GameState.data.agents;
    failedPath = 'state/agents.json';
    const failedResult = await manager.fetchAllState();
    assert.strictEqual(failedResult.ok, false);
    assert.strictEqual(
        GameState.data.agents,
        lastKnownAgents,
        'failed snapshot replaced last-known-good state'
    );
}

async function main() {
    testEscapingAndCredentialRemoval();
    testLispSandbox();
    await testCanonicalStagedPolling();
    console.log('Frontend trust and polling tests passed');
}

main().catch(error => {
    console.error(error);
    process.exit(1);
});
