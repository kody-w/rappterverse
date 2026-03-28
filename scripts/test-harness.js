// Headless Digital Twin Test Harness — Node.js vm-based game simulator
// Mocks THREE.js + DOM + browser APIs, loads all game JS, drives gameplay programmatically
'use strict';
const vm = require('vm');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');

// ── THREE.js Mock ──
class Vector3 {
    constructor(x,y,z) { this.x=x||0; this.y=y||0; this.z=z||0; }
    set(x,y,z) { this.x=x; this.y=y; this.z=z; return this; }
    copy(v) { this.x=v.x; this.y=v.y; this.z=v.z; return this; }
    clone() { return new Vector3(this.x, this.y, this.z); }
    add(v) { this.x+=v.x; this.y+=v.y; this.z+=v.z; return this; }
    normalize() { var l=this.length(); if(l>0){this.x/=l;this.y/=l;this.z/=l;} return this; }
    length() { return Math.sqrt(this.x*this.x+this.y*this.y+this.z*this.z); }
    distanceTo(v) { return Math.sqrt((this.x-v.x)**2+(this.y-v.y)**2+(this.z-v.z)**2); }
    lerp(v,t) { this.x+=(v.x-this.x)*t; this.y+=(v.y-this.y)*t; this.z+=(v.z-this.z)*t; return this; }
    multiplyScalar(s) { this.x*=s; this.y*=s; this.z*=s; return this; }
}

class MockColor {
    constructor(c) { this._hex = c || 0; }
    setHex(h) { this._hex = h; } getHex() { return this._hex; }
    set(c) { this._hex = typeof c === 'number' ? c : 0; }
    multiplyScalar() { return this; }
    toString() { return '#' + (this._hex||0).toString(16).padStart(6,'0'); }
}

function mkMesh(geo, mat) {
    return {
        position: new Vector3(), rotation: {x:0,y:0,z:0}, scale: new Vector3(1,1,1),
        visible: true, parent: null, children: [], userData: {},
        geometry: geo || { type:'', attributes:{position:{array:new Float32Array(48843)}}, setAttribute(){}, computeVertexNormals(){}, dispose(){}, setFromPoints(){ return this; } },
        material: mat || { color: new MockColor(), emissive: new MockColor(), emissiveIntensity:0, opacity:1, dispose(){}, uniforms:{} },
        add(c) { this.children.push(c); c.parent = this; },
        remove(c) { var i=this.children.indexOf(c); if(i>=0)this.children.splice(i,1); c.parent=null; },
        traverse(fn) { fn(this); this.children.forEach(c => { if(c.traverse) c.traverse(fn); else fn(c); }); },
        lookAt() {},
    };
}

function buildTHREE() {
    var geoFactory = function() { return { type:'', attributes:{position:{array:new Float32Array(300)}}, setAttribute(){}, computeVertexNormals(){}, dispose(){}, setFromPoints(){ return this; } }; };
    var matFactory = function(p) { return { color: new MockColor(p&&p.color), emissive: new MockColor(), emissiveIntensity:0, opacity: (p&&p.opacity)||1, transparent:false, dispose(){}, uniforms:{} }; };

    return {
        Vector3, Vector2: function(x,y){this.x=x||0;this.y=y||0;this.set=function(a,b){this.x=a;this.y=b;}},
        Color: MockColor,
        Scene: function() { var s = mkMesh(); s.background=null; s.fog=null; return s; },
        PerspectiveCamera: function() { var c = mkMesh(); c.aspect=1; c.updateProjectionMatrix=function(){}; return c; },
        OrthographicCamera: function() { return mkMesh(); },
        Mesh: function(g,m) { return mkMesh(g,m); },
        Group: function() { return mkMesh(); },
        Line: function(g,m) { return mkMesh(g,m); },
        LineSegments: function(g,m) { return mkMesh(g,m); },
        Points: function(g,m) { var p=mkMesh(g,m); p.geometry={attributes:{position:{array:new Float32Array(2400),needsUpdate:false}}}; return p; },
        Sprite: function(m) { return mkMesh(null,m); },
        SpriteMaterial: matFactory, MeshStandardMaterial: matFactory, MeshBasicMaterial: matFactory,
        MeshPhongMaterial: matFactory, LineBasicMaterial: matFactory, PointsMaterial: matFactory,
        ShaderMaterial: function(o) { return Object.assign({uniforms:{}},o); },
        BufferGeometry: function() { return geoFactory(); },
        BufferAttribute: function(a,s) { this.array=a; },
        Float32BufferAttribute: function(a,s) { this.array = typeof a === 'number' ? new Float32Array(a) : new Float32Array(a); },
        PlaneGeometry: function(w,h,sw,sh) { sw=sw||1;sh=sh||1; var g=geoFactory(); g.attributes.position.array=new Float32Array((sw+1)*(sh+1)*3); return g; },
        BoxGeometry: geoFactory, SphereGeometry: geoFactory, CylinderGeometry: geoFactory,
        ConeGeometry: geoFactory, RingGeometry: geoFactory, CircleGeometry: geoFactory,
        DodecahedronGeometry: geoFactory, OctahedronGeometry: geoFactory, IcosahedronGeometry: geoFactory,
        TorusGeometry: geoFactory, TubeGeometry: geoFactory, EdgesGeometry: geoFactory,
        GridHelper: function() { return mkMesh(); },
        AmbientLight: function(c,i) { var l=mkMesh(); l.intensity=i||1; l.color=new MockColor(c); return l; },
        DirectionalLight: function(c,i) { var l=mkMesh(); l.intensity=i||1; l.color=new MockColor(c); return l; },
        PointLight: function(c,i,r) { var l=mkMesh(); l.intensity=i||1; return l; },
        FogExp2: function() {},
        WebGLRenderer: function() { return { setSize(){}, setPixelRatio(){}, render(){}, setRenderTarget(){}, domElement:{style:{}}, toneMapping:0, toneMappingExposure:1 }; },
        WebGLRenderTarget: function() { return { texture:{}, setSize(){} }; },
        Clock: function() { return { _d:0.016, _e:0, getDelta(){ return this._d; }, getElapsedTime(){ return this._e; } }; },
        CatmullRomCurve3: function(pts) { this.getPoint=function(){return new Vector3();}; },
        CanvasTexture: function(c) { this.needsUpdate=false; },
        Raycaster: function() { this.setFromCamera=function(){}; this.intersectObjects=function(){return[];}; this.params={Mesh:{threshold:0.5}}; },
        DoubleSide:2, BackSide:1, AdditiveBlending:2, ACESFilmicToneMapping:4,
        LinearFilter:1006, RGBAFormat:1023, VertexColors:2,
    };
}

// ── DOM Mock ──
function mkEl(tag, id) {
    return {
        id: id||'', tagName: tag||'DIV', textContent:'', innerHTML:'', value:'', max:0,
        style: new Proxy({},{set:()=>true,get:()=>''}),
        classList: { _s:new Set(), add(c){this._s.add(c);}, remove(c){this._s.delete(c);}, toggle(c,f){if(f!==undefined){f?this._s.add(c):this._s.delete(c);}else{this._s.has(c)?this._s.delete(c):this._s.add(c);}}, contains(c){return this._s.has(c);} },
        children:[], childNodes:[], parentNode:null, dataset:{},
        appendChild(c){this.children.push(c);c.parentNode=this;return c;},
        removeChild(c){var i=this.children.indexOf(c);if(i>=0)this.children.splice(i,1);return c;},
        addEventListener(){}, removeEventListener(){},
        querySelector(){return mkEl();}, querySelectorAll(sel){ if(sel==='.ability-slot') return Array.from({length:5},()=>mkEl('DIV')); return []; },
        closest(){return null;}, click(){}, remove(){},
        setAttribute(){}, getAttribute(){return null;},
        getBoundingClientRect(){return{x:0,y:0,width:800,height:600,top:0,left:0};},
        getContext(){ return {
            fillStyle:'',strokeStyle:'',font:'',textAlign:'',textBaseline:'',lineWidth:1,globalAlpha:1,globalCompositeOperation:'source-over',
            fillRect(){},clearRect(){},strokeRect(){},fillText(){},strokeText(){},
            beginPath(){},closePath(){},moveTo(){},lineTo(){},arc(){},stroke(){},fill(){},
            roundRect(){},
            createRadialGradient(){return{addColorStop(){}};},createLinearGradient(){return{addColorStop(){}};},
            drawImage(){},save(){},restore(){},translate(){},rotate(){},scale(){},
            measureText(){return{width:0};},
        }; },
    };
}

function buildDOM() {
    var _els = {};
    return {
        getElementById(id) { if(!_els[id]) _els[id]=mkEl('DIV',id); return _els[id]; },
        createElement(tag) { return mkEl(tag); },
        createTextNode(t) { return {textContent:t}; },
        body: mkEl('BODY'), head: mkEl('HEAD'),
        addEventListener(){}, removeEventListener(){},
        querySelectorAll(sel) { if(sel==='.ability-slot') return Array.from({length:5},()=>mkEl('DIV')); return []; },
        querySelector() { return mkEl(); },
        _els: _els, // expose for assertions
    };
}

function buildAudioCtx() {
    var node = function(){ return { gain:{value:0.3,setValueAtTime(){},linearRampToValueAtTime(){},exponentialRampToValueAtTime(){},cancelScheduledValues(){},setTargetAtTime(){}}, frequency:{value:440,setValueAtTime(){},exponentialRampToValueAtTime(){}}, type:'sine', connect(){return this;}, disconnect(){}, start(){}, stop(){}, buffer:null, loop:false, playbackRate:{value:1}, Q:{value:1} }; };
    return function() { return { destination:{}, sampleRate:44100, state:'running', currentTime:0, createGain:node, createOscillator:node, createBufferSource:node, createBiquadFilter:node, createBuffer(ch,len){return{getChannelData(){return new Float32Array(len);}};}, resume(){return Promise.resolve();}, close(){return Promise.resolve();} }; };
}

// ── Create World Factory ──
function createWorld(worldId) {
    worldId = worldId || 'arena';
    var _mockTime = 0;
    var _elapsed = 0;

    var store = new Map();
    var MockAudioCtx = buildAudioCtx();
    var doc = buildDOM();
    var THREE = buildTHREE();

    var ctx = vm.createContext({
        THREE: THREE,
        document: doc,
        window: { addEventListener(){}, removeEventListener(){}, innerWidth:1920, innerHeight:1080, SpeechRecognition:null, webkitSpeechRecognition:null, devicePixelRatio:1, location:{search:'',href:'',origin:'https://test',pathname:'/'}, Hands:null, Camera:null, AudioContext:MockAudioCtx, webkitAudioContext:MockAudioCtx },
        navigator: { userAgent:'node-test-harness', clipboard:{writeText(){return Promise.resolve();}} },
        localStorage: { getItem(k){return store.get(k)||null;}, setItem(k,v){store.set(k,String(v));}, removeItem(k){store.delete(k);}, clear(){store.clear();} },
        performance: { now(){ return _mockTime; } },
        console: { log(){}, warn(){}, error: console.error },
        Math:Math, Date:Date, Array:Array, Object:Object, String:String, Number:Number, JSON:JSON, Set:Set, Map:Map,
        Uint8Array:Uint8Array, Uint8ClampedArray:Uint8ClampedArray, Float32Array:Float32Array, Int32Array:Int32Array,
        parseInt:parseInt, parseFloat:parseFloat, isNaN:isNaN, isFinite:isFinite, Infinity:Infinity, NaN:NaN,
        Promise:Promise, Error:Error, TypeError:TypeError, ReferenceError:ReferenceError, RegExp:RegExp,
        requestAnimationFrame(){return 0}, cancelAnimationFrame(){},
        setTimeout(fn,ms){ if(ms===0||ms===undefined) try{fn();}catch(e){} return 0; },
        setInterval(){return 0}, clearTimeout(){}, clearInterval(){},
        fetch(){return Promise.resolve({ok:false,status:0,json(){return Promise.resolve(null);}});},
        URL:{createObjectURL(){return'';},revokeObjectURL(){}},
        Blob:function(){}, FileReader:function(){this.readAsText=function(){};},
        URLSearchParams:function(){this.get=function(){return null;};},
        Image:function(){},
        alert(){}, confirm(){return false},
    });

    // Stub Boot before loading main.js
    vm.runInContext('var Boot = { run(){}, skip(){}, done:true, completed:true };', ctx);

    // Load all JS files in bundle order
    var bundleSh = fs.readFileSync(path.join(ROOT, 'scripts/bundle.sh'), 'utf8');
    var jsFiles = [];
    bundleSh.replace(/src\/js\/[\w-]+\.js/g, function(m) { jsFiles.push(m); });

    for (var i = 0; i < jsFiles.length; i++) {
        var fpath = path.join(ROOT, jsFiles[i]);
        if (!fs.existsSync(fpath)) continue;
        var src = fs.readFileSync(fpath, 'utf8');
        // For main.js: let IIFE run but Boot is stubbed and rAF is no-op
        try {
            vm.runInContext(src, ctx, { filename: jsFiles[i], timeout: 10000 });
        } catch(e) {
            // Some files may error on init (e.g. PostProcessing) — that's OK
        }
    }

    // Patch Inventory.items if missing (crafting/shop depend on it)
    vm.runInContext('if(typeof Inventory!=="undefined" && !Inventory.items) Inventory.items=[];', ctx);

    // Initialize the world
    vm.runInContext('GameState.currentWorld="' + worldId + '";', ctx);
    try {
        vm.runInContext('WorldMode.init("' + worldId + '")', ctx, { timeout: 15000 });
    } catch(e) {
        // Init may partially fail on some subsystems — that's OK for testing
    }

    // ── Harness API ──
    function tick(delta) {
        delta = delta || 1/60;
        _mockTime += delta * 1000;
        _elapsed += delta;
        try {
            vm.runInContext('if(GameState.clock){GameState.clock._d=' + delta + ';GameState.clock._e=' + _elapsed + ';}', ctx);
            vm.runInContext('if(WorldMode.active) WorldMode.update(' + delta + ',' + _elapsed + ')', ctx, { timeout: 5000 });
        } catch(e) {}
    }

    function tickSeconds(secs) {
        var frames = Math.ceil(secs * 60);
        for (var i = 0; i < frames; i++) tick(1/60);
    }

    function attack() {
        try {
            return vm.runInContext('WorldCombat.playerAttack(WorldMode.player.mesh.position)', ctx);
        } catch(e) { return false; }
    }

    function useAbility(idx) {
        try { return vm.runInContext('Abilities.useAbility(' + idx + ')', ctx); } catch(e) { return false; }
    }

    function buyItem(idx) {
        try { vm.runInContext('Shop.buy(' + idx + ')', ctx); } catch(e) {}
    }

    function craft(idx) {
        try { vm.runInContext('Crafting.craft(' + idx + ')', ctx); } catch(e) {}
    }

    function movePlayerTo(x, z) {
        try { vm.runInContext('WorldMode.player.mesh.position.set(' + x + ',0,' + z + ')', ctx); } catch(e) {}
    }

    function getState() {
        try {
            return JSON.parse(vm.runInContext('JSON.stringify({' +
                'player:{hp:PlayerStats.hp,maxHp:PlayerStats.maxHp,mp:PlayerStats.mp,gold:PlayerStats.gold,' +
                'level:PlayerStats.level,xp:PlayerStats.xp,xpToLevel:PlayerStats.xpToLevel,' +
                'kills:PlayerStats.kills,deaths:PlayerStats.deaths,dead:PlayerStats.dead,' +
                'baseDamage:PlayerStats.baseDamage,shielded:PlayerStats.shielded},' +
                'combat:{creepCount:WorldCombat.creeps.filter(function(c){return c.alive}).length,' +
                'waveNumber:WorldCombat.waveNumber,momentum:WorldCombat.momentum,' +
                'warmup:WorldCombat._warmupActive,' +
                'hordeCreeps:WorldCombat.creeps.filter(function(c){return c.alive&&c.faction==="horde"}).length,' +
                'explorerCreeps:WorldCombat.creeps.filter(function(c){return c.alive&&c.faction==="explorer"}).length,' +
                'bossActive:WorldCombat.bossActive},' +
                'abilities:{levels:Abilities.levels.slice(),skillPoints:Abilities.skillPoints},' +
                'thrones:{explorer:WorldLanes.thrones.explorer?WorldLanes.thrones.explorer.hp:0,' +
                'horde:WorldLanes.thrones.horde?WorldLanes.thrones.horde.hp:0},' +
                'inventory:{count:Inventory.items?Inventory.items.length:0}' +
                '})', ctx));
        } catch(e) { return { error: e.message }; }
    }

    function run(code) {
        return vm.runInContext(code, ctx, { timeout: 5000 });
    }

    return { tick, tickSeconds, attack, useAbility, buyItem, craft, movePlayerTo, getState, run, ctx, store };
}

module.exports = { createWorld };
