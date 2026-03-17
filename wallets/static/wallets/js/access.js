/**
 * BoltPocket wallet access via URL fragment.
 * Raw key lives in the # fragment — never sent to server.
 * Client hashes it, POSTs hash to server.
 * Server verifies, sets session cookie, JS loads dashboard inline.
 * URL stays as /wallet/#key — bookmarkable.
 */

function sha256(message) {
    function rightRotate(value, amount) {
        return (value >>> amount) | (value << (32 - amount));
    }

    var mathPow = Math.pow;
    var maxWord = mathPow(2, 32);

    var k = [], hash = [], i, j;
    var isComposite = {};
    for (var candidate = 2, primeCount = 0; primeCount < 64; candidate++) {
        if (!isComposite[candidate]) {
            for (i = 0; i < 313; i += candidate) {
                isComposite[i] = candidate;
            }
            hash[primeCount] = (mathPow(candidate, .5) * maxWord) | 0;
            k[primeCount++] = (mathPow(candidate, 1 / 3) * maxWord) | 0;
        }
    }

    var msg = message;
    var msgLength = msg.length;

    var words = [];
    for (i = 0; i < msgLength; i++) {
        j = i >> 2;
        words[j] = (words[j] || 0) + ((msg.charCodeAt(i) & 0xff) << ((3 - (i & 3)) * 8));
    }

    var totalBits = msgLength * 8;
    j = msgLength >> 2;
    words[j] = (words[j] || 0) + (0x80 << ((3 - (msgLength & 3)) * 8));

    var totalWords = (((msgLength + 8) >> 6) + 1) * 16;
    words[totalWords - 1] = totalBits;

    var h = hash.slice(0, 8);

    for (var block = 0; block < totalWords;) {
        var w = [];
        for (i = 0; i < 64; i++) {
            if (i < 16) {
                w[i] = words[block + i] | 0;
            } else {
                var s0w = w[i - 15];
                var s0 = rightRotate(s0w, 7) ^ rightRotate(s0w, 18) ^ (s0w >>> 3);
                var s1w = w[i - 2];
                var s1 = rightRotate(s1w, 17) ^ rightRotate(s1w, 19) ^ (s1w >>> 10);
                w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
            }

            var a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
            var S1 = rightRotate(e, 6) ^ rightRotate(e, 11) ^ rightRotate(e, 25);
            var ch = (e & f) ^ (~e & g);
            var temp1 = (hh + S1 + ch + k[i] + w[i]) | 0;
            var S0 = rightRotate(a, 2) ^ rightRotate(a, 13) ^ rightRotate(a, 22);
            var maj = (a & b) ^ (a & c) ^ (b & c);
            var temp2 = (S0 + maj) | 0;

            h = [(temp1 + temp2) | 0, a, b, c, (d + temp1) | 0, e, f, g];
        }

        for (i = 0; i < 8; i++) {
            h[i] = (h[i] + hash[i]) | 0;
            hash[i] = h[i];
        }
        block += 16;
    }

    var hex = '';
    for (i = 0; i < 8; i++) {
        for (j = 3; j >= 0; j--) {
            var b = (hash[i] >> (j * 8)) & 0xff;
            hex += ('0' + b.toString(16)).slice(-2);
        }
    }
    return hex;
}

async function authenticate() {
    var rawKey = window.location.hash.substring(1);
    if (!rawKey) {
        // No key — try loading dashboard directly (session might still be valid)
        loadDashboard();
        return;
    }

    document.getElementById('status').textContent = 'Authenticating...';

    var clientHash = sha256(rawKey);

    var response = await fetch('/wallet/auth/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: clientHash }),
    });

    if (response.ok) {
        loadDashboard();
    } else {
        document.getElementById('status').textContent = 'Invalid access key.';
    }
}

async function loadDashboard() {
    try {
        var response = await fetch('/wallet/dashboard/');
        if (response.redirected || !response.ok) {
            document.getElementById('status').textContent = 'Session expired. Use your full wallet URL.';
            return;
        }
        var html = await response.text();
        document.open();
        document.write(html);
        document.close();
    } catch (e) {
        document.getElementById('status').textContent = 'Failed to load wallet.';
    }
}

document.addEventListener('DOMContentLoaded', authenticate);
