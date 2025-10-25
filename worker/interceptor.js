(function() {
    // 檢查URL如果是查詢API，則用 local API /trade/setPayloadMapping 傳遞資料
    async function sendDataWhenUrlMatch(apiUrl, payloadData, tradeId) {
        const urlKeywordPoe2 = '/api/trade2/search/';
        const urlKeywordPoe1 = '/api/trade/search/';
        let poeType = null;
        let leagueName = null;

        function extractLastPathSegment(url) {
            const match = url.match(/\/([^\/?#]+)(?:[?#]|$)/);
            if (!match) return null;
            
            const encodedPart = match[1];
            const decodedPart = decodeURIComponent(encodedPart); // ✅ 將 %20 等解碼回正常字串
            return decodedPart;
        }

        if (apiUrl.includes(urlKeywordPoe1)) {
            poeType = 1;
            leagueName = extractLastPathSegment(apiUrl);
        }
        if (apiUrl.includes(urlKeywordPoe2)) {
            poeType = 2;
            leagueName = extractLastPathSegment(apiUrl);
        }

        if (tradeId && poeType && leagueName) {
            try {
                const res = await fetch("http://localhost:5000/trade/setPayloadMapping", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ tradeId, payloadData, poeType, leagueName })
                });
                const data = await res.json();
                console.log("Response:", data);
                return data; // ✅ 把結果 return 出去
            } catch (err) {
                console.error("Fetch error:", err);
                throw err; // ✅ 錯誤拋出，方便外層 try/catch 處理
            }
        }
        
    }
      

    if (window.__api_logger_installed_v2) {
        console.warn('API logger v2 already installed.');
        return;
    }
    window.__api_logger_installed_v2 = true;

    const safeLog = (...args) => console.log('%c[API-LOGGER]', 'color: #0a84ff; font-weight:600;', ...args);

    // ---- body parsing: best-effort to produce JS object when possible ----
    async function tryParseBody(body) {
        try {
            if (body === null || body === undefined) return null;

            // Request object (fetch input)
            if (typeof Request !== 'undefined' && body instanceof Request) {
                try {
                    const clone = body.clone();
                    const txt = await clone.text();
                    try { return JSON.parse(txt); } catch(e) { return txt; }
                } catch(e) {
                    return { __type: 'Request', note: 'read-failed', error: String(e) };
                }
            }

            // FormData -> object (files summarized)
            if (typeof FormData !== 'undefined' && body instanceof FormData) {
                const out = {};
                for (const [k, v] of body.entries()) {
                    if (typeof File !== 'undefined' && v instanceof File) {
                        out[k] = { __type: 'File', name: v.name, size: v.size, mime: v.type };
                    } else if (typeof Blob !== 'undefined' && v instanceof Blob) {
                        out[k] = { __type: 'Blob', size: v.size, mime: v.type };
                    } else {
                        out[k] = v;
                    }
                }
                return out;
            }

            // URLSearchParams -> object
            if (typeof URLSearchParams !== 'undefined' && body instanceof URLSearchParams) {
                return Object.fromEntries([...body.entries()]);
            }

            // Blob / File -> try text then JSON
            if (typeof Blob !== 'undefined' && body instanceof Blob) {
                const txt = await body.text();
                try { return JSON.parse(txt); } catch(e) { return txt.slice(0, 200); }
            }

            // ArrayBuffer / TypedArray -> try decode as text
            if (body instanceof ArrayBuffer || ArrayBuffer.isView && ArrayBuffer.isView(body)) {
                try {
                    const arr = body instanceof ArrayBuffer ? new Uint8Array(body) : new Uint8Array(body.buffer || body);
                    const txt = new TextDecoder().decode(arr);
                    try { return JSON.parse(txt); } catch(e) { return txt.slice(0, 200); }
                } catch(e) {
                    return { __type: 'ArrayBuffer', error: String(e) };
                }
            }

            // If it's already a plain object (e.g., someone passed an object)
            if (typeof body === 'object') {
                // avoid very large or circular structures — attempt JSON stringify
                try {
                    JSON.stringify(body); // quick test for serializability
                    return body;
                } catch (e) {
                    return { __type: 'object', note: 'non-serializable', error: String(e) };
                }
            }

            // string -> try parse JSON
            if (typeof body === 'string') {
                const trimmed = body.trim();
                if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
                    try { return JSON.parse(trimmed); } catch (e) { /* fallthrough */ }
                }
                // maybe urlencoded form: a=1&b=2
                if (trimmed.includes('=') && trimmed.includes('&')) {
                    try {
                        return Object.fromEntries(new URLSearchParams(trimmed));
                    } catch(e) {}
                }
                return trimmed.length > 1000 ? trimmed.slice(0, 1000) + '... (truncated)' : trimmed;
            }

            // fallback: toString
            return String(body);
        } catch (e) {
            return { __type: 'parse-failed', error: String(e) };
        }
    }

    // ---- patch fetch ----
    const _origFetch = window.fetch;
    window.fetch = async function(input, init) {
        try {
            // derive url & method
            let url = '<unknown>';
            let method = 'GET';
            let candidateBody = null;

            if (typeof input === 'string') {
                url = input;
                if (init && init.method) method = init.method;
                candidateBody = init && init.body;
            } else if (input && typeof input === 'object') {
                // Request object
                url = input.url || url;
                method = input.method || method;
                // prefer init.body if present, else try to read from Request (clone)
                candidateBody = init && init.body ? init.body : input;
            }

            const parsed = await tryParseBody(candidateBody);
            safeLog('[fetch] ->', method, url);
            console.log('[fetch] payload -> %o', parsed); // object-friendly

            const resp = await _origFetch.apply(this, arguments);

            // keep previous behavior for response preview
            (async () => {
                try {
                    const c = resp.clone();
                    const ct = c.headers && c.headers.get && c.headers.get('content-type') || '';
                    if (ct.includes('application/json')) {
                        const j = await c.json();
                        safeLog('[fetch] <- response', resp.status, url);
                        console.log('[fetch] response json -> %o', j);

                        await sendDataWhenUrlMatch(url, parsed, j.id);
                    } else {
                        const txt = await c.text();
                        safeLog('[fetch] <- response', resp.status, url);
                        console.log('[fetch] response text ->', txt.slice(0, 500));
                    }
                } catch (e) {
                    safeLog('[fetch] <- response (read failed)', resp.status, url, e);
                }
            })();

            return resp;
        } catch (err) {
            console.error('[API-LOGGER][fetch error]', err);
            throw err;
        }
    };

    // ---- patch XMLHttpRequest ----
    const XHROpen = XMLHttpRequest.prototype.open;
    const XHRSend = XMLHttpRequest.prototype.send;

    XMLHttpRequest.prototype.open = function(method, url) {
        try {
            this.__api_logger = { method, url };
        } catch(e) {}
        return XHROpen.apply(this, arguments);
    };

    XMLHttpRequest.prototype.send = function(body) {
        const meta = this.__api_logger || {};
        let parsed = null; // ✅ 提前宣告變數，供後續使用
    
        (async () => {
            parsed = await tryParseBody(body); // ✅ 指派給外層變數
            safeLog('[XHR] ->', meta.method || 'GET', meta.url || '<unknown>');
            console.log('[XHR] payload -> %o', parsed);
        })();

        this.addEventListener('readystatechange', function() {
            try {
                if (this.readyState === 4) {
                    let respPreview = null;
                    try {
                        respPreview = (typeof this.responseText === 'string')
                            ? this.responseText.slice(0, 1000)
                            : this.response;
                    } catch (e) {
                        respPreview = '<unreadable>';
                    }
                    safeLog('[XHR] <-', this.status, meta.method || 'GET', meta.url || '<unknown>');
                    console.log('[XHR] response preview ->', respPreview);

                    (async () => {
                        await sendDataWhenUrlMatch(meta.url, parsed, JSON.parse(this.responseText).id);
                    })()
                }
            } catch (e) {
                console.error('[API-LOGGER][XHR read error]', e);
            }
        });

        return XHRSend.apply(this, arguments);
    };

    // ---- patch WebSocket (lightweight) ----
    try {
        const _OrigWS = window.WebSocket;
        function WrappedWebSocket(url, protocols) {
            const ws = protocols ? new _OrigWS(url, protocols) : new _OrigWS(url);
            safeLog('[WebSocket] new', url);
            const origSend = ws.send;
            ws.send = function(data) {
                (async () => {
                    const parsed = await tryParseBody(data);
                    safeLog('[WebSocket] send ->', url);
                    console.log('[WebSocket] payload -> %o', parsed);
                })();
                return origSend.apply(this, arguments);
            };
            return ws;
        }
        WrappedWebSocket.prototype = _OrigWS.prototype;
        WrappedWebSocket.CONNECTING = _OrigWS.CONNECTING;
        WrappedWebSocket.OPEN = _OrigWS.OPEN;
        WrappedWebSocket.CLOSING = _OrigWS.CLOSING;
        WrappedWebSocket.CLOSED = _OrigWS.CLOSED;
        window.WebSocket = WrappedWebSocket;
    } catch (e) {
        console.warn('[API-LOGGER] WebSocket patch failed', e);
    }

    safeLog('Installed fetch/XMLHttpRequest/WebSocket logger v2 — payloads will be parsed into objects when possible.');
})();
