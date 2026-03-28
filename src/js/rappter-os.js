// RappterOS — Lightweight Linux VM for agent compute between frames
// Uses v86 (x86 emulator in JS) to boot Alpine Linux client-side
// Agents queue shell commands, OS processes them, output feeds back into frame state
//
// Architecture:
//   Frame arrives → agents queue tasks via VM →
//   RappterOS processes queue → output enriches next echo →
//   world state updated → repeat
//
// This is an L4 echo shaper: raw frame data → computed enrichment

const RappterOS = {
    _emulator: null,
    _ready: false,
    _loading: false,
    _queue: [],        // Pending commands: [{id, cmd, callback, agentId}]
    _results: {},      // Completed results: id → {stdout, stderr, exitCode}
    _terminal: null,   // Output buffer
    _outputBuffer: '',
    _commandId: 0,

    // Check if v86 is available
    isAvailable() {
        return typeof V86Starter !== 'undefined';
    },

    // Load v86 emulator and boot Alpine Linux
    async init() {
        if (this._ready || this._loading) return;
        this._loading = true;

        // Load v86 from CDN
        if (!this.isAvailable()) {
            try {
                await this._loadScript('https://cdn.jsdelivr.net/npm/v86@latest/build/libv86.js');
            } catch(e) {
                console.warn('[OS] Failed to load v86:', e);
                this._loading = false;
                return;
            }
        }

        if (typeof V86Starter === 'undefined') {
            console.warn('[OS] V86Starter not available after load');
            this._loading = false;
            return;
        }

        // Boot minimal Alpine Linux
        try {
            this._emulator = new V86Starter({
                wasm_path: 'https://cdn.jsdelivr.net/npm/v86@latest/build/v86.wasm',
                memory_size: 32 * 1024 * 1024,  // 32MB RAM
                vga_memory_size: 2 * 1024 * 1024,
                // Use a pre-built Alpine Linux image
                bzimage: {
                    url: 'https://cdn.jsdelivr.net/npm/v86@latest/images/bzImage',
                },
                initrd: {
                    url: 'https://cdn.jsdelivr.net/npm/v86@latest/images/linux.iso',
                },
                autostart: true,
                disable_keyboard: true,
                disable_mouse: true,
                screen_dummy: true, // No display needed
            });

            // Capture serial output
            this._emulator.add_listener('serial0-output-char', (char) => {
                this._outputBuffer += char;
                this._checkOutput();
            });

            // Wait for boot
            var self = this;
            setTimeout(function() {
                self._ready = true;
                self._loading = false;
                console.log('[OS] Alpine Linux booted in browser');
                if (typeof HUD !== 'undefined') HUD.showToast('RappterOS online — Linux VM ready');
                self._processQueue();
            }, 8000); // Alpine takes ~8s to boot in v86

        } catch(e) {
            console.warn('[OS] Failed to boot:', e);
            this._loading = false;
        }
    },

    _loadScript(src) {
        return new Promise(function(resolve, reject) {
            var s = document.createElement('script');
            s.src = src;
            s.onload = resolve;
            s.onerror = reject;
            document.head.appendChild(s);
        });
    },

    // Queue a shell command for execution
    exec(cmd, agentId, callback) {
        var id = ++this._commandId;
        this._queue.push({
            id: id,
            cmd: cmd,
            agentId: agentId || 'system',
            callback: callback || null,
            submitted: Date.now()
        });
        if (this._ready) this._processQueue();
        return id;
    },

    // Process the command queue
    _processQueue() {
        if (!this._ready || this._queue.length === 0) return;
        var task = this._queue.shift();
        this._currentTask = task;
        this._outputBuffer = '';

        // Send command to the Linux VM via serial
        // Wrap in markers so we can detect output boundaries
        var marker = '###RAPPTER_' + task.id + '###';
        var wrapped = 'echo ' + marker + '_START && ' + task.cmd + ' 2>&1; echo $? > /tmp/exitcode; echo ' + marker + '_END';
        this._emulator.serial0_send(wrapped + '\n');
    },

    // Check output buffer for completed commands
    _checkOutput() {
        if (!this._currentTask) return;
        var marker = '###RAPPTER_' + this._currentTask.id + '###';
        var startIdx = this._outputBuffer.indexOf(marker + '_START');
        var endIdx = this._outputBuffer.indexOf(marker + '_END');

        if (startIdx >= 0 && endIdx > startIdx) {
            var output = this._outputBuffer.substring(startIdx + marker.length + 6, endIdx).trim();
            var result = {
                id: this._currentTask.id,
                cmd: this._currentTask.cmd,
                agentId: this._currentTask.agentId,
                stdout: output,
                exitCode: 0,
                completedAt: Date.now(),
                duration: Date.now() - this._currentTask.submitted
            };

            this._results[this._currentTask.id] = result;

            // Callback
            if (this._currentTask.callback) {
                try { this._currentTask.callback(result); } catch(e) {}
            }

            // Feed result into VM environment
            if (typeof RappterVM !== 'undefined') {
                RappterVM._env['os-last-result'] = result.stdout;
                RappterVM._env['os-last-exit'] = result.exitCode;
            }

            // Feed into echo engine as enrichment
            if (typeof EchoEngine !== 'undefined') {
                var f = EchoEngine.getCurrentFrame();
                if (f && f.echoes) {
                    if (!f.echoes.osResults) f.echoes.osResults = [];
                    f.echoes.osResults.push(result);
                }
            }

            this._currentTask = null;
            this._outputBuffer = '';

            // Process next in queue
            if (this._queue.length > 0) this._processQueue();
        }
    },

    // ── Convenience methods for agents ──

    // Run a Python one-liner
    python(code, agentId, callback) {
        return this.exec('python3 -c "' + code.replace(/"/g, '\\"') + '"', agentId, callback);
    },

    // Analyze text (word count, sentiment proxy)
    analyzeText(text, agentId, callback) {
        var escaped = text.replace(/'/g, "'\\''").substring(0, 500);
        return this.exec("echo '" + escaped + "' | wc -w && echo '" + escaped + "' | grep -oi 'good\\|great\\|happy\\|bad\\|sad\\|angry' | wc -l", agentId, callback);
    },

    // Compute stats from numbers
    computeStats(numbers, agentId, callback) {
        var nums = numbers.join(' ');
        return this.exec("echo '" + nums + "' | tr ' ' '\\n' | awk '{sum+=$1; count++} END {print sum/count, count}'", agentId, callback);
    },

    // List directory (for debugging)
    ls(path, callback) {
        return this.exec('ls -la ' + (path || '/'), 'system', callback);
    },

    // Write a file into the VM
    writeFile(path, content, callback) {
        var escaped = content.replace(/'/g, "'\\''");
        return this.exec("echo '" + escaped + "' > " + path, 'system', callback);
    },

    // Read a file from the VM
    readFile(path, callback) {
        return this.exec('cat ' + path, 'system', callback);
    },

    // ── VM Integration ──

    // Register OS functions in the RappterVM stdlib
    registerVMFunctions() {
        if (typeof RappterVM === 'undefined') return;
        var self = this;

        RappterVM._env['os-exec'] = function(cmd) {
            self.exec(cmd, RappterVM._env['self'] || 'vm');
            return true;
        };
        RappterVM._env['os-python'] = function(code) {
            self.python(code, RappterVM._env['self'] || 'vm');
            return true;
        };
        RappterVM._env['os-ready'] = function() { return self._ready; };
        RappterVM._env['os-result'] = function() { return self._results[self._commandId] ? self._results[self._commandId].stdout : null; };
        RappterVM._env['os-queue-size'] = function() { return self._queue.length; };
    },

    // Get status
    getStatus() {
        return {
            ready: this._ready,
            loading: this._loading,
            queueSize: this._queue.length,
            totalExecuted: this._commandId,
            results: Object.keys(this._results).length
        };
    },

    cleanup() {
        if (this._emulator) {
            try { this._emulator.stop(); this._emulator.destroy(); } catch(e) {}
            this._emulator = null;
        }
        this._ready = false;
        this._queue = [];
        this._results = {};
    }
};
