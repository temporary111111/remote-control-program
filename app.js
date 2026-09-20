(function() {
    'use strict';

    const state = {
        pc: null,
        ws: null,
        tunnelUrl: '',
        dataChannel: null,
        video: document.getElementById('remote-video'),
        connecting: false,
        controlEnabled: false,
        reconnectAttempts: 0,
        maxReconnectAttempts: 10,
        reconnectDelay: 3000,
        reconnectTimer: null,
        intentionalDisconnect: false,
    };

    const elements = {
        overlay: document.getElementById('connect-overlay'),
        tunnelUrl: document.getElementById('tunnel-url'),
        connectBtn: document.getElementById('connect-btn'),
        connectStatus: document.getElementById('connect-status'),
        toolbar: document.getElementById('toolbar'),
        connectionStatus: document.getElementById('connection-status'),
        controlToggleBtn: document.getElementById('control-toggle-btn'),
        fullscreenBtn: document.getElementById('fullscreen-btn'),
        disconnectBtn: document.getElementById('disconnect-btn'),
        unmuteBtn: document.getElementById('unmute-btn'),
        loading: document.getElementById('loading'),
    };

    function showStatus(message, type = 'info') {
        elements.connectStatus.textContent = message;
        elements.connectStatus.className = `status visible ${type}`;
    }

    function hideStatus() {
        elements.connectStatus.className = 'status';
    }

    function setConnecting(isConnecting) {
        state.connecting = isConnecting;
        elements.connectBtn.disabled = isConnecting;
        elements.connectBtn.textContent = isConnecting ? 'Connecting...' : 'Connect';
        elements.tunnelUrl.disabled = isConnecting;
    }

    function showToolbar() {
        elements.toolbar.classList.remove('hidden');
    }

    function hideToolbar() {
        elements.toolbar.classList.add('hidden');
    }

    function showLoading(show) {
        elements.loading.classList.toggle('hidden', !show);
    }

    function updateConnectionStatus(connected) {
        elements.connectionStatus.textContent = connected ? 'Connected' : 'Disconnected';
        elements.connectionStatus.className = `status ${connected ? 'connected' : ''}`;
    }

    async function connect() {
        const url = elements.tunnelUrl.value.trim();
        if (!url) {
            showStatus('Please enter a tunnel URL', 'error');
            return;
        }

        if (!url.startsWith('https://') || !url.includes('.trycloudflare.com')) {
            showStatus('Invalid tunnel URL format', 'error');
            return;
        }

        state.tunnelUrl = url;
        state.intentionalDisconnect = false;
        state.reconnectAttempts = 0;
        if (state.reconnectTimer) {
            clearTimeout(state.reconnectTimer);
            state.reconnectTimer = null;
        }
        setConnecting(true);
        hideStatus();
        showLoading(true);

        try {
            await setupSignaling();
            state.ws.onclose = () => {
                console.log('Signaling lost during session');
                if (!state.intentionalDisconnect && state.pc) {
                    cleanup();
                    startReconnect();
                }
            };
            await setupWebRTC();
            await createOffer();
        } catch (err) {
            console.error('Connection failed:', err);
            showStatus(`Connection failed: ${err.message}`, 'error');
            cleanup();
        } finally {
            setConnecting(false);
            showLoading(false);
        }
    }

    async function setupSignaling() {
        return new Promise((resolve, reject) => {
            let settled = false;
            const wsUrl = state.tunnelUrl.replace('https://', 'wss://') + '/ws';
            state.ws = new WebSocket(wsUrl);

            state.ws.onopen = () => {
                if (settled) return;
                settled = true;
                console.log('Signaling connected');
                resolve();
            };

            state.ws.onerror = (err) => {
                if (settled) return;
                settled = true;
                console.error('Signaling error:', err);
                reject(new Error('Signaling connection failed'));
            };

            state.ws.onclose = () => {
                if (settled) return;
                settled = true;
                console.log('Signaling closed');
                reject(new Error('Signaling disconnected'));
            };

            state.ws.onmessage = (event) => {
                handleSignalingMessage(JSON.parse(event.data));
            };
        });
    }

    function handleSignalingMessage(msg) {
        switch (msg.type) {
            case 'ready':
                console.log('Server ready');
                break;
            case 'answer':
                handleAnswer(msg.payload);
                break;
            case 'ice-candidate':
                handleIceCandidate(msg.payload);
                break;
            case 'error':
                console.error('Server error:', msg.payload.error);
                showStatus(msg.payload.error, 'error');
                break;
        }
    }

    async function setupWebRTC() {
        const config = {
            iceServers: [
                { urls: 'stun:stun.l.google.com:19302' },
                { urls: 'stun:stun1.l.google.com:19302' },
            ],
        };

        state.pc = new RTCPeerConnection(config);

        state.pc.onconnectionstatechange = () => {
            const connState = state.pc ? state.pc.connectionState : 'closed';
            console.log('Connection state:', connState);
            updateConnectionStatus(connState === 'connected');
            
            if (connState === 'connected') {
                elements.overlay.classList.add('hidden');
                showToolbar();
            } else if (['failed', 'disconnected'].includes(connState)) {
                console.log('Connection lost, starting reconnect...');
                cleanup();
                startReconnect();
            }
        };

        state.pc.onicecandidate = (event) => {
            if (event.candidate && state.ws && state.ws.readyState === WebSocket.OPEN) {
                state.ws.send(JSON.stringify({
                    type: 'ice-candidate',
                    payload: {
                        candidate: event.candidate.candidate,
                        sdpMid: event.candidate.sdpMid,
                        sdpMLineIndex: event.candidate.sdpMLineIndex,
                    },
                }));
            }
        };

        state.pc.ontrack = (event) => {
            console.log('Track received:', event.track.kind);
            if (!state.video.srcObject) {
                state.video.srcObject = event.streams[0];
            } else {
                event.streams[0].getTracks().forEach(track => {
                    state.video.srcObject.addTrack(track);
                });
            }
            event.streams[0].getTracks().forEach(track => {
                if (track.kind === 'audio') {
                    track.enabled = true;
                }
            });
        };

        state.video.muted = true;
        elements.unmuteBtn.classList.remove('hidden');

        elements.unmuteBtn.addEventListener('click', () => {
            state.video.muted = false;
            state.video.volume = 1.0;
            elements.unmuteBtn.classList.add('hidden');
        });

        state.dataChannel = state.pc.createDataChannel("input");
        setupDataChannel(state.dataChannel);

        state.pc.ondatachannel = (event) => {
            state.dataChannel = event.channel;
            setupDataChannel(state.dataChannel);
        };
    }

    function setupDataChannel(channel) {
        channel.onopen = () => {
            console.log('Data channel open');
            console.log('Data channel label:', channel.label);
            console.log('Data channel readyState:', channel.readyState);
        };
        channel.onclose = () => console.log('Data channel closed');
        channel.onerror = (err) => console.error('Data channel error:', err);
        channel.onmessage = (event) => console.log('Data channel message:', event.data);
    }

    async function createOffer() {
        const offer = await state.pc.createOffer({
            offerToReceiveAudio: true,
            offerToReceiveVideo: true,
        });
        
        await state.pc.setLocalDescription(offer);

        state.ws.send(JSON.stringify({
            type: 'offer',
            payload: {
                sdp: offer.sdp,
                type: offer.type,
            },
        }));
    }

    async function handleAnswer(payload) {
        if (!state.pc) return;
        await state.pc.setRemoteDescription(new RTCSessionDescription(payload));
    }

    async function handleIceCandidate(payload) {
        if (!state.pc) return;
        try {
            await state.pc.addIceCandidate(payload);
        } catch (err) {
            console.warn('ICE candidate error:', err);
        }
    }

    function sendInput(action, data) {
        if (!state.controlEnabled) return;
        if (state.dataChannel && state.dataChannel.readyState === 'open') {
            state.dataChannel.send(JSON.stringify({ action, data }));
        }
    }

    function setupInputHandlers() {
        let isMouseDown = false;

        state.video.addEventListener('mousedown', (e) => {
            isMouseDown = true;
            state.video.classList.add('cursor-grabbing');
            state.video.classList.remove('cursor-grab');
            const rect = state.video.getBoundingClientRect();
            sendInput('mousedown', {
                button: e.button === 0 ? 'left' : 'right',
                x: (e.clientX - rect.left) / rect.width,
                y: (e.clientY - rect.top) / rect.height,
            });
        });

        state.video.addEventListener('mouseup', (e) => {
            isMouseDown = false;
            state.video.classList.remove('cursor-grabbing');
            state.video.classList.add('cursor-grab');
            const rect = state.video.getBoundingClientRect();
            sendInput('mouseup', {
                button: e.button === 0 ? 'left' : 'right',
                x: (e.clientX - rect.left) / rect.width,
                y: (e.clientY - rect.top) / rect.height,
            });
        });

        state.video.addEventListener('mousemove', (e) => {
            const rect = state.video.getBoundingClientRect();
            sendInput('mousemove', {
                x: (e.clientX - rect.left) / rect.width,
                y: (e.clientY - rect.top) / rect.height,
            });
        });

        state.video.addEventListener('mouseleave', () => {
            if (isMouseDown) {
                isMouseDown = false;
                sendInput('mouseup', { button: 'left' });
            }
            state.video.classList.remove('cursor-grabbing');
            state.video.classList.add('cursor-grab');
        });

        state.video.addEventListener('wheel', (e) => {
            e.preventDefault();
            sendInput('mousewheel', {
                dx: e.deltaX,
                dy: e.deltaY,
            });
        }, { passive: false });

        state.video.addEventListener('contextmenu', (e) => e.preventDefault());

        // Touch support
        state.video.addEventListener('touchstart', (e) => {
            e.preventDefault();
            const touch = e.touches[0];
            const rect = state.video.getBoundingClientRect();
            isMouseDown = true;
            sendInput('mousedown', {
                button: 'left',
                x: (touch.clientX - rect.left) / rect.width,
                y: (touch.clientY - rect.top) / rect.height,
            });
        }, { passive: false });

        state.video.addEventListener('touchmove', (e) => {
            e.preventDefault();
            const touch = e.touches[0];
            const rect = state.video.getBoundingClientRect();
            sendInput('mousemove', {
                x: (touch.clientX - rect.left) / rect.width,
                y: (touch.clientY - rect.top) / rect.height,
            });
        }, { passive: false });

        state.video.addEventListener('touchend', (e) => {
            e.preventDefault();
            isMouseDown = false;
            sendInput('mouseup', { button: 'left' });
        }, { passive: false });

        document.addEventListener('keydown', (e) => {
            if (e.target === elements.tunnelUrl) return;
            if (e.key === 'f' || e.key === 'F') {
                toggleFullscreen();
            } else {
                sendInput('keydown', { key: normalizeKey(e.key) });
            }
        });

        document.addEventListener('keyup', (e) => {
            if (e.target === elements.tunnelUrl) return;
            sendInput('keyup', { key: normalizeKey(e.key) });
        });

        elements.tunnelUrl.addEventListener('input', () => {
            elements.connectBtn.disabled = !elements.tunnelUrl.value.trim();
        });

        elements.connectBtn.addEventListener('click', connect);

        elements.tunnelUrl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !elements.connectBtn.disabled) {
                connect();
            }
        });

        elements.fullscreenBtn.addEventListener('click', toggleFullscreen);

        elements.controlToggleBtn.addEventListener('click', toggleControl);

        elements.disconnectBtn.addEventListener('click', () => {
            state.intentionalDisconnect = true;
            if (state.reconnectTimer) {
                clearTimeout(state.reconnectTimer);
                state.reconnectTimer = null;
            }
            state.reconnectAttempts = 0;
            cleanup();
            elements.overlay.classList.remove('hidden');
            hideToolbar();
            updateConnectionStatus(false);
            const overlayTitle = elements.overlay.querySelector('h1');
            if (overlayTitle) overlayTitle.textContent = 'Remote Desktop';
        });
    }

    function normalizeKey(key) {
        const map = {
            'Escape': 'escape', 'Enter': 'enter', 'Tab': 'tab',
            'Backspace': 'backspace', 'Delete': 'delete',
            'ArrowUp': 'up', 'ArrowDown': 'down', 'ArrowLeft': 'left', 'ArrowRight': 'right',
            'Shift': 'shift', 'Control': 'ctrl', 'Alt': 'alt', 'Meta': 'cmd',
            'CapsLock': 'capslock', 'NumLock': 'numlock', 'ScrollLock': 'scrolllock',
            'Home': 'home', 'End': 'end', 'PageUp': 'pageup', 'PageDown': 'pagedown',
            'Insert': 'insert', ' ': 'space',
        };
        for (let i = 1; i <= 12; i++) {
            map[`F${i}`] = `f${i}`;
        }
        return map[key] || key.toLowerCase();
    }

    function toggleFullscreen() {
        if (!document.fullscreenElement) {
            state.video.requestFullscreen().catch(console.error);
        } else {
            document.exitFullscreen();
        }
    }

    function toggleControl() {
        state.controlEnabled = !state.controlEnabled;
        const btn = elements.controlToggleBtn;
        if (state.controlEnabled) {
            btn.textContent = '🔓';
            btn.classList.remove('control-off');
            btn.classList.add('control-on');
        } else {
            btn.textContent = '🔒';
            btn.classList.remove('control-on');
            btn.classList.add('control-off');
        }
    }

    function cleanup() {
        state.controlEnabled = false;
        const btn = elements.controlToggleBtn;
        if (btn) {
            btn.textContent = '🔒';
            btn.classList.remove('control-on');
            btn.classList.add('control-off');
        }
        if (elements.unmuteBtn) {
            elements.unmuteBtn.classList.add('hidden');
        }
        if (state.video) {
            state.video.muted = true;
        }
        if (state.dataChannel) {
            state.dataChannel.close();
            state.dataChannel = null;
        }
        if (state.pc) {
            state.pc.close();
            state.pc = null;
        }
        if (state.ws) {
            state.ws.close();
            state.ws = null;
        }
        state.video.srcObject = null;
    }

    function startReconnect() {
        if (state.intentionalDisconnect) return;
        if (state.reconnectTimer) return;
        if (state.reconnectAttempts >= state.maxReconnectAttempts) {
            showStatus(`Connection lost after ${state.maxReconnectAttempts} attempts. Click Connect to try again.`, 'error');
            elements.overlay.classList.remove('hidden');
            hideToolbar();
            updateConnectionStatus(false);
            state.reconnectAttempts = 0;
            return;
        }

        state.reconnectAttempts++;
        const delay = state.reconnectDelay * Math.pow(2, state.reconnectAttempts - 1);
        const cappedDelay = Math.min(delay, 60000);

        const overlayTitle = elements.overlay.querySelector('h1');
        if (overlayTitle) {
            overlayTitle.textContent = `Reconnecting... (${state.reconnectAttempts}/${state.maxReconnectAttempts})`;
        }
        elements.overlay.classList.remove('hidden');
        hideToolbar();
        updateConnectionStatus(false);

        console.log(`Reconnecting in ${cappedDelay}ms (attempt ${state.reconnectAttempts})`);

        state.reconnectTimer = setTimeout(async () => {
            state.reconnectTimer = null;
            if (state.intentionalDisconnect) return;
            cleanup();
            try {
                await setupSignaling();
                state.ws.onclose = () => {
                    console.log('Signaling lost during session');
                    if (!state.intentionalDisconnect && state.pc) {
                        cleanup();
                        startReconnect();
                    }
                };
                await setupWebRTC();
                await createOffer();
                state.reconnectAttempts = 0;
                const overlayTitle = elements.overlay.querySelector('h1');
                if (overlayTitle) {
                    overlayTitle.textContent = 'Remote Desktop';
                }
            } catch (err) {
                console.error('Reconnect failed:', err);
                startReconnect();
            }
        }, cappedDelay);
    }

    function init() {
        setupInputHandlers();
        elements.tunnelUrl.focus();
        
        if (navigator.clipboard) {
            navigator.clipboard.readText().then(text => {
                if (text && text.startsWith('https://') && text.includes('.trycloudflare.com')) {
                    elements.tunnelUrl.value = text;
                    elements.connectBtn.disabled = false;
                }
            }).catch(() => {});
        }
    }

    document.addEventListener('DOMContentLoaded', init);
})();