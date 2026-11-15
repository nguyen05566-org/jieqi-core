// ================== BOT CHINH - gamevh-caro-bot ==================
// Luong:
//   1. Playwright mo Chromium that -> vao login.jsp -> goi username/password
//      nhu nguoi (go tung ky tu), tick AUTO_LOGIN, bam "Dang nhap".
//   2. Vao https://gamevh.net/play/caro/0 -> client game tu bat tay WebSocket
//      bang token cua trang (chinh la luong cua nguoi choi that).
//   3. Bridge (bridge.js) tiem vao trang: doc tat ca tin nhan WS den, cung
//      cap API de gui LIST_BET_AMT / CREATE_RULE / SET_READY / PLAY qua
//      dung OutboundMessage cua client -> tin hieu tren wire giong 100%.
//   4. Den luot -> engine pbrain-embryo (Caro6, ban 15x19) tinh nuoc ->
//      PLAY. Vong lap tu dong: tao ban -> cho doi thu -> san sang -> choi
//      -> ket thuc van -> san sang tiep; mat ket noi -> tu phuc hoi.
//
// Chay: CARO_USER=... CARO_PASSWD=... node bot.js

'use strict';

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const cfg = require('./config');
const { EmbryoEngine } = require('./engine');
const { buildBridgeSource } = require('./bridge');

// ---------------- helpers ----------------
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const log = (tag, msg) => console.log(`[${new Date().toLocaleTimeString('vi-VN')}] [${tag}] ${msg}`);
function withTimeout(promise, ms, what) {
  return Promise.race([
    promise,
    sleep(ms).then(() => { throw new Error(what + ' sau ' + ms + 'ms'); }),
  ]);
}

// ---------------- trang thai bot ----------------
const st = {
  running: true,
  startTime: Date.now(),
  slot: -1, isPlaying: false, turnSlot: -1, inTable: false,
  readyFlag: false, pendingMove: false, moving: false,
  tableId: null, betAmts: [], betAmtsLoaded: false,
  pendingCreate: false, lastCreateAt: 0, createRetries: 0,
  tableLostAt: null, opponentGoneAt: null,
  lastMyMove: null, pendingKickId: null, pendingKickSent: false, lastKickAt: 0,
  lastReloadAt: 0, lastReconcileLog: 0,
  wins: 0, losses: 0, draws: 0, totalGames: 0,
  engineMoves: 0, engineFallbacks: 0,
};
let page = null, context = null, browser = null;
const engine = new EmbryoEngine({
  binary: cfg.ENGINE_BINARY || undefined,
  timeoutTurn: cfg.ENGINE_TIMEOUT_TURN_MS,
  moveTimeoutS: cfg.ENGINE_MOVE_TIMEOUT_S,
  matchTimeoutMs: cfg.ENGINE_MATCH_TIMEOUT_MS,
  syncMode: cfg.ENGINE_SYNC,
});

// ---------------- event pipeline ----------------
const eventQueue = [];
const eventLog = [];
let pumpActive = false;
async function pump() {
  if (pumpActive) return;
  pumpActive = true;
  while (eventQueue.length > 0) {
    const ev = eventQueue.shift();
    try { await onEvent(ev); } catch (e) { log('BOT', 'onEvent ' + ev.cmd + ' error: ' + e.message); }
  }
  pumpActive = false;
}
function waitForEvent(predicate, timeoutMs) {
  const startIdx = eventLog.length;
  return new Promise((resolve) => {
    const t0 = Date.now();
    const iv = setInterval(() => {
      for (let i = startIdx; i < eventLog.length; i++) {
        if (predicate(eventLog[i])) { clearInterval(iv); resolve(eventLog[i]); return; }
      }
      if (Date.now() - t0 > timeoutMs) { clearInterval(iv); resolve(null); }
    }, 100);
  });
}

// ---------------- bridge helpers ----------------
async function getBridgeState() {
  if (!page || page.isClosed()) throw new Error('page closed');
  return await page.evaluate(() => window.__caroBot ? window.__caroBot.state() : null);
}
const CREATE_ARGS = [
  ['matchDuration', cfg.MATCH_DURATION],
  ['turnDuration', cfg.TURN_DURATION],
  ['accDuration', cfg.ACC_DURATION],
  ['blockSoftware', cfg.BLOCK_SOFTWARE],
];
function resolveBetId(betAmts, wantXu) {
  if (!betAmts || !betAmts.length) return 0;
  for (const ba of betAmts) if (ba.value === wantXu) return ba.id;
  const lower = betAmts.filter(ba => ba.value > 0 && ba.value <= wantXu);
  if (lower.length) return lower.reduce((a, b) => (b.value > a.value ? b : a)).id;
  return 0;
}

// ---------------- hanh dong game ----------------
async function createNewTable(reason) {
  if (st.pendingCreate) return;
  st.pendingCreate = true;
  st.lastCreateAt = Date.now();
  try {
    log('BOT', `Tao ban moi (${reason})...`);
    const state = await getBridgeState();
    if (!state.betAmtsLoaded) {
      await page.evaluate(() => window.__caroBot.listBetAmt());
      const ev = await waitForEvent(e => e.cmd === 'LIST_BET_AMT', 10000);
      if (ev && ev.parsed && ev.parsed.status === 0) st.betAmts = ev.parsed.betAmts;
      else { log('BOT', 'LIST_BET_AMT loi -> thu lai sau'); return; }
    } else {
      st.betAmts = state.betAmts;
    }
    const betId = resolveBetId(st.betAmts, cfg.BET_XU);
    log('BOT', `CREATE_RULE betId=${betId} (muon ${cfg.BET_XU}xu, co st.betAmts.length=${st.betAmts.length})`);
    await page.evaluate((bid) => window.__caroBot.createTable(bid, CREATE_ARGS), betId);
    st.createRetries++;
    const ev = await waitForEvent(e => e.cmd === 'CREATE_RULE', 10000);
    if (ev && ev.parsed && ev.parsed.status === 0) {
      st.tableId = ev.parsed.tableId;
      st.createRetries = 0;
      log('BOT', `BAN MOI OK id=${st.tableId}`);
      await sleep(500);
      await page.evaluate(() => window.__caroBot.getTable());
    } else {
      log('BOT', 'CREATE_RULE that bai ' + JSON.stringify(ev && ev.parsed || {}) + ' -> thu lai sau 1s');
      if (st.createRetries >= 5) {
        log('BOT', 'Qua 5 lan tao ban loi -> nghi 20s, de watchdog thu lai sau');
        await sleep(20000);
        return;
      }
      await sleep(1000);
      st.pendingCreate = false;
      await createNewTable('retry-' + st.createRetries);
    }
  } catch (e) {
    log('BOT', 'createNewTable error: ' + e.message);
    await sleep(1500);
  } finally {
    st.pendingCreate = false;
  }
}

async function doReady(where) {
  if (st.readyFlag || st.isPlaying) return;
  st.readyFlag = true;
  try {
    log('BOT', `SET_READY (${where})`);
    await page.evaluate(() => window.__caroBot.ready());
  } catch (e) { st.readyFlag = false; log('BOT', 'doReady error: ' + e.message); }
}

function emptyNearFromStones(stones, w, h, x0, y0) {
  const occ = new Set(stones.map(s => s[0] + ',' + s[1]));
  for (let r = 0; r < 10; r++) {
    for (let dx = -r; dx <= r; dx++) {
      for (let dy = -r; dy <= r; dy++) {
        const x = x0 + dx, y = y0 + dy;
        if (x >= 0 && x < w && y >= 0 && y < h && !occ.has(x + ',' + y)) return [x, y];
      }
    }
  }
  return [Math.floor(w / 2), Math.floor(h / 2)];
}

async function ensureEngine(mySide) {
  if (!engine.alive()) {
    log('Embryo', 'Khoi dong engine...');
    const ok = await engine.start(mySide);
    if (!ok) throw new Error('khong khoi dong duoc engine');
  }
  return true;
}

async function doMove(reason) {
  if (st.moving || st.pendingMove || !st.isPlaying) return;
  st.moving = true;
  st.pendingMove = true;
  const t0 = Date.now();
  try {
    const state = await getBridgeState();
    if (!state || !state.isPlaying || state.slot < 0) return;
    const stones = state.stones;
    const w = state.boardW || 15, h = state.boardH || 19;
    const mySide = state.slot === 0 ? 0 : 1;

    // delay de giong nguoi suy nghi
    const thinkDelay = cfg.THINK_MIN_MS + Math.random() * Math.max(0, cfg.THINK_MAX_MS - cfg.THINK_MIN_MS);
    await sleep(thinkDelay);
    if (!st.isPlaying) return;

    await ensureEngine(mySide);
    let x = -1, y = -1;
    const occupied = (px, py) => stones.some(s => s[0] === px && s[1] === py);
    const valid = (mv) => mv && mv[0] >= 0 && mv[0] < w && mv[1] >= 0 && mv[1] < h && !occupied(mv[0], mv[1]);

    try {
      const mv = await withTimeout(engine.getMove(stones, mySide), cfg.ENGINE_MOVE_TIMEOUT_S * 1000, 'engine-treo');
      if (valid(mv)) { x = mv[0]; y = mv[1]; st.engineMoves++; }
      else {
        st.engineFallbacks++;
        log('BOT', `[Embryo] Nuoc khong hop le: ${JSON.stringify(mv)} -> fallback + reset engine`);
        engine.stop();
      }
    } catch (e) {
      st.engineFallbacks++;
      log('BOT', `[Embryo] ${e.message} -> reset engine, dung fallback`);
      engine.stop();
    }

    if (x < 0) {
      // fallback: o trong gan nuoc cuoi (mirror python near_last)
      const last = stones.length ? stones[stones.length - 1] : null;
      [x, y] = emptyNearFromStones(stones, w, h, last ? last[0] : Math.floor(w / 2), last ? last[1] : Math.floor(h / 2));
    }

    const pos = y * w + x;
    st.lastMyMove = [x, y];
    await page.evaluate((p) => window.__caroBot.play(p), pos);
    log('BOT', `MOVE (${x},${y}) pos=${pos} took ${((Date.now() - t0) / 1000).toFixed(2)}s [Embryo] (${reason})`);
  } catch (e) {
    st.pendingMove = false;
    log('BOT', 'doMove error: ' + e.message);
  } finally {
    st.moving = false;
  }
}

async function refreshTable() {
  try { await page.evaluate(() => window.__caroBot.getTable()); } catch (e) { /* ignore */ }
}

async function scheduleKickWinner(results, delayMs) {
  const winnerSid = Object.keys(results).map(Number)
    .find(sid => sid !== st.slot && sid >= 0 && (results[sid] === 1 || results[sid] === 11));
  if (winnerSid === undefined) {
    log('BOT', 'Thua nhung khong tim thay nguoi thang -> san sang binh thuong');
    return false;
  }
  setTimeout(async () => {
    try {
      if (st.isPlaying || !st.inTable) return;
      const s2 = await getBridgeState();
      if (!s2 || s2.isPlaying || !s2.inTable) return;
      const info = (s2.playerInfo && s2.playerInfo[winnerSid]) || null;
      if (!info || info.id === undefined || info.id === null) {
        log('BOT', 'Bo kick: nguoi thang khong con o ban');
        return;
      }
      log('BOT', `Bot thua -> kick nguoi thang "${info.name}" sau khi thua (KICK_ON_LOSS=1)`);
      st.readyFlag = false;
      st.pendingKickSent = true;
      await page.evaluate((pid) => window.__caroBot.kick(pid), info.id);
      st.lastKickAt = Date.now();
      setTimeout(async () => {
        try { if (st.inTable) await refreshTable(); } catch (e) { /* ignore */ }
      }, 3000);
    } catch (e) { log('BOT', 'kick error: ' + e.message); st.pendingKickSent = false; }
  }, delayMs);
  return true;
}

// ---------------- xu ly event tu bridge ----------------
async function onEvent(ev) {
  const p = ev.parsed || {};
  switch (ev.cmd) {
    case 'LOGIN': {
      if (p.status === 0 && p.path === 'REFRESH') {
        log('BOT', 'LOGIN REFRESH -> reload trang de login lai');
        await reloadPage('login-refresh');
      } else if (p.status !== 0) {
        log('BOT', 'LOGIN FAILED status=' + p.status + ' ' + (p.error || ''));
      } else {
        log('BOT', 'LOGIN OK (path=' + p.path + ')');
      }
      break;
    }
    case 'ENTER_PLACE': {
      if (p.status !== 0) log('BOT', 'ENTER_PLACE status=' + p.status + ' ' + (p.error || ''));
      break;
    }
    case 'CREATE_RULE': {
      if (p.status === 0) log('BOT', 'CREATE_RULE OK table=' + p.tableId);
      break;
    }
    case 'GET_TABLE_DATA_EX': {
      if (!p.ok) {
        if ((p.error || '').toLowerCase().includes('not in table')) {
          st.inTable = false; st.tableId = null;
          await createNewTable('not-in-table');
        }
        break;
      }
      st.slot = p.slot; st.isPlaying = p.isPlaying; st.turnSlot = p.turnSlot;
      st.inTable = true;
      const opp = p.opponentSeated;
      log('TABLE', `Slot=${st.slot} Playing=${st.isPlaying} Turn=slot${st.turnSlot} opp=${opp}`);
      if (st.isPlaying && st.turnSlot === st.slot && !st.moving && !st.pendingMove) {
        setImmediate(() => doMove('table'));
      } else if (!st.isPlaying && st.slot >= 0) {
        if (opp) { if (!st.readyFlag) doReady('doi thu da ngoi'); }
        else st.readyFlag = false;
      } else if (!st.isPlaying && st.slot < 0) {
        st.inTable = false; st.tableId = null;
        await sleep(1000);
        await createNewTable('slot-am');
      }
      break;
    }
    case 'START_MATCH': {
      st.totalGames++;
      st.isPlaying = true; st.readyFlag = false; st.pendingMove = false; st.moving = false;
      st.lastMyMove = null; st.opponentGoneAt = null;
      const mySym = p.mySymbol === 0 ? 'O' : 'X';
      log('BOT', `=== GAME ${st.totalGames} === Me=${mySym} board=${p.w}x${p.h} stones=${p.n}`);
      // restart engine moi van (RESTART + RECTSTART, opening book active)
      try {
        const mySide = p.mySymbol;
        if (engine.alive()) await engine.restart(mySide);
        else await engine.start(mySide);
      } catch (e) { log('BOT', 'engine restart error: ' + e.message); }
      break;
    }
    case 'SET_TURN': {
      if (p.sid === st.slot && st.isPlaying && !st.moving && !st.pendingMove) {
        setImmediate(() => doMove('set-turn'));
      } else if (st.inTable && st.slot >= 0 && !st.isPlaying && !st.readyFlag) {
        // server dem nguoc accDuration khi doi thu vua vao ban -> READY ngay
        log('BOT', `SET_TURN lobby countdown=${p.turnTimeout}s -> SET_READY ngay!`);
        doReady('lobby-countdown');
      }
      break;
    }
    case 'MOVE': {
      if (p.mine) { st.pendingMove = false; st.lastMyMove = null; }
      if (st.moving) log('BOT', `[MOVE] Doi thu danh trong luc engine dang tinh (${p.x},${p.y}) - lan sau se sync full board`);
      break;
    }
    case 'PLAY': {
      if (p.status !== 0) {
        log('BOT', 'PLAY error ' + p.status + ' -> undo + resync');
        st.pendingMove = false;
        st.lastMyMove = null;
        await sleep(500);
        await refreshTable();
      }
      break;
    }
    case 'GAMEOVER': {
      st.isPlaying = false; st.pendingMove = false;
      const myResult = p.myResult;
      if (myResult === 1 || myResult === 11) { st.wins++; log('BOT', '>>> WIN! <<<'); }
      else if (myResult === 2 || myResult === 4 || myResult === 12) { st.losses++; log('BOT', '>>> LOSE! <<<'); }
      else { st.draws++; log('BOT', '>>> DRAW! <<<'); }
      saveStats();
      if (st.tableLostAt) {
        st.tableLostAt = null;
        await sleep(2000);
        await createNewTable('table-lost');
        break;
      }
      if ((myResult === 2 || myResult === 4 || myResult === 12) && cfg.KICK_ON_LOSS) {
        const kicked = await scheduleKickWinner(p.results || {}, 5000);
        if (kicked) break;
      }
      log('BOT', 'O lai ban, san sang sau ' + cfg.READY_DELAY_AFTER_GAMEOVER_S + 's...');
      setTimeout(async () => {
        try {
          if (!st.isPlaying && st.inTable) {
            await refreshTable();
            if (!st.isPlaying && st.inTable) doReady('sau-gameover');
          }
        } catch (e) { /* ignore */ }
      }, cfg.READY_DELAY_AFTER_GAMEOVER_S * 1000);
      break;
    }
    case 'PLAYER_ENTERED': {
      if (p.placeLevel < 4) break;
      log('BOT', `Phat hien ${p.name} vao ban -> cap nhat trang thai + READY (accDuration=${cfg.ACC_DURATION}s)`);
      await refreshTable();
      if (st.slot >= 0 && !st.isPlaying && !st.readyFlag) doReady('player-entered');
      break;
    }
    case 'PLAYER_EXITED': {
      if (p.placeLevel < 4) break;
      if (p.slot !== null && p.slot === st.slot) {
        if (st.isPlaying) { st.tableLostAt = Date.now(); }
        else { st.inTable = false; await sleep(1000); await createNewTable('ban-bi-huy'); }
      } else if (st.isPlaying) {
        if (st.opponentGoneAt === null) {
          st.opponentGoneAt = Date.now();
          log('BOT', 'Doi thu roi giua van -> o lai ban, cho GAMEOVER');
        }
      } else if (st.inTable) {
        log('BOT', 'Co nguoi roi ban -> cap nhat trang thai');
        await refreshTable();
      }
      break;
    }
    case 'KICK_PLAYER': {
      if (st.pendingKickSent) {
        st.pendingKickSent = false;
        log('BOT', `Kick ket qua: status=${p.status} ${p.error || 'OK'}`);
        await sleep(1000);
        if (st.inTable) await refreshTable();
        break;
      }
      log('BOT', 'Bot bi kick khoi ban: ' + (p.error || ''));
      st.isPlaying = false; st.inTable = false; st.pendingMove = false;
      st.tableId = null;
      await sleep(1000);
      await createNewTable('bi-kick');
      break;
    }
    case 'ALERT': {
      log('ALERT', p.content || '');
      break;
    }
    case 'BRIDGE_ERR': {
      log('BRIDGE', 'parse error: ' + (p.error || ''));
      break;
    }
  }
}

// ---------------- watchdog + reconcile ----------------
async function reloadPage(reason) {
  const now = Date.now();
  if (now - st.lastReloadAt < 30000) return;
  st.lastReloadAt = now;
  log('BOT', 'Reload trang (' + reason + ')...');
  try { await page.reload({ waitUntil: 'domcontentloaded', timeout: 45000 }); } catch (e) { log('BOT', 'reload error: ' + e.message); }
  // session mat -> trang quay ve login.jsp: dang nhap lai nhu nguoi
  try {
    if (page && !page.isClosed() && page.url().includes('login.jsp')) {
      log('BOT', 'Session het -> dang nhap lai nhu nguoi that...');
      await humanLogin(page);
      await waitBridgeReady(60000);
      await waitLoginOk(30000);
    }
  } catch (e) { log('BOT', 're-login sau reload error: ' + e.message); }
}

async function watchdogTick() {
  if (!st.running) return;
  // runtime limit
  const runtimeMs = cfg.RUNTIME_HOURS * 3600 * 1000;
  if (Date.now() - st.startTime > runtimeMs) {
    log('BOT', 'Het thoi gian chay (RUNTIME_HOURS=' + cfg.RUNTIME_HOURS + ') -> dung bot');
    shutdown();
    return;
  }
  let s = null;
  try { s = await getBridgeState(); } catch (e) {
    // trang bi dong -> mo lai
    if (page && page.isClosed()) { try { page = await context.newPage(); await setupPage(page); } catch (e2) {} }
    return;
  }
  if (!s || !s.installed) return;

  // dong bo slot/playing tu bridge
  st.slot = s.slot; st.isPlaying = s.isPlaying; st.inTable = s.inTable;
  st.turnSlot = s.turnSlot; st.betAmts = s.betAmts; st.betAmtsLoaded = s.betAmtsLoaded;
  st.tableId = s.tableId;

  // ket noi chet / im lang lau
  if ((!s.connActive && s.lastMsgAgeMs > 20000) || s.lastMsgAgeMs > cfg.ACTIVITY_STALE_S * 1000) {
    await reloadPage('mat-ket-noi-' + Math.round(s.lastMsgAgeMs / 1000) + 's');
    return;
  }

  // reconcile hanh dong
  if (s.isPlaying && s.turnSlot === s.slot && !st.moving && !st.pendingMove) {
    doMove('watchdog');
  } else if (!s.isPlaying && s.slot >= 0 && s.opponentSeated && !st.readyFlag) {
    doReady('watchdog');
  }

  if (st.tableLostAt && Date.now() - st.tableLostAt > 8000) {
    st.tableLostAt = null; st.tableId = null;
    await createNewTable('watchdog-table-lost');
  }
  if (st.opponentGoneAt && st.isPlaying && Date.now() - st.opponentGoneAt > 15000) {
    st.opponentGoneAt = null;
    await refreshTable();
  }
  if (!s.isPlaying && !s.inTable && s.betAmtsLoaded && !st.pendingCreate
    && Date.now() - st.lastCreateAt > 12000) {
    await createNewTable('watchdog-lobby');
  }
  if (st.pendingCreate && Date.now() - st.lastCreateAt > 15000) st.pendingCreate = false;

  // kick khong co phan hoi 15s -> resync
  if (st.lastKickAt && Date.now() - st.lastKickAt > 15000) {
    st.lastKickAt = 0; st.pendingKickSent = false;
    if (st.inTable) await refreshTable();
  }
}

function saveStats() {
  try {
    fs.writeFileSync(path.join(__dirname, 'stats.json'), JSON.stringify({
      W: st.wins, L: st.losses, D: st.draws, Games: st.totalGames,
      engineMoves: st.engineMoves, engineFallbacks: st.engineFallbacks,
      savedAt: new Date().toISOString(),
    }, null, 2));
  } catch (e) { /* ignore */ }
}

// ---------------- setup browser + login ----------------
function setupPageHandlers(p) {
  p.on('dialog', (d) => { d.accept().catch(() => {}); });
}

async function setupPage(p) {
  setupPageHandlers(p);
  // binding day event ve Node
  await p.exposeBinding('__caroEmit', (source, ev) => {
    eventLog.push(ev);
    if (eventLog.length > 2000) eventLog.splice(0, 1000);
    eventQueue.push(ev);
    pump();
  });
  // mo trang login truoc - humanLogin se tu vao GAME_URL sau khi login xong
  await p.goto(cfg.LOGIN_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
}

async function humanLogin(p) {
  await p.goto(cfg.LOGIN_URL, { waitUntil: 'domcontentloaded', timeout: 45000 });
  if (!p.url().includes('login.jsp')) {
    log('BOT', 'Da login tu session truoc (AUTO_LOGIN) -> ' + p.url());
    await p.goto(cfg.GAME_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
    return true;
  }
  log('BOT', 'Trang dang nhap da san sang');

  // go nhu nguoi that
  await p.locator('#USER_NAME').click();
  await p.locator('#USER_NAME').pressSequentially(cfg.USER, { delay: 25 + Math.random() * 45 });
  await sleep(400 + Math.random() * 500);
  await p.locator('#PASSWORD').click();
  await p.locator('#PASSWORD').pressSequentially(cfg.PASSWD, { delay: 25 + Math.random() * 45 });
  await sleep(300 + Math.random() * 400);
  const chk = p.locator('#chk_AUTO_LOGIN');
  if (await chk.count() > 0 && !(await chk.isChecked())) {
    await chk.check();
    await sleep(150 + Math.random() * 250);
  }
  log('BOT', 'Bam nut "Dang nhap"...');
  await p.locator('#LOGIN').click();
  await p.waitForFunction(() => !location.href.includes('login.jsp'), null, { timeout: 30000 });
  log('BOT', 'Dang nhap THANH CONG -> ' + p.url());
  await p.goto(cfg.GAME_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  return true;
}

async function waitBridgeReady(maxMs) {
  const t0 = Date.now();
  while (Date.now() - t0 < maxMs) {
    try {
      const ok = await page.evaluate(() => window.__caroBot && window.__caroBot.isReady());
      if (ok) return true;
    } catch (e) { /* ignore */ }
    await sleep(500);
  }
  return false;
}

async function waitLoginOk(maxMs) {
  const t0 = Date.now();
  while (Date.now() - t0 < maxMs) {
    try {
      const s = await getBridgeState();
      if (s && s.loginOk) { log('BOT', 'Client game da bat tay WS + LOGIN OK'); return true; }
    } catch (e) { /* ignore */ }
    await sleep(500);
  }
  return false;
}

async function shutdown() {
  if (!st.running) return;
  st.running = false;
  log('BOT', `Dung bot. W/L/D = ${st.wins}/${st.losses}/${st.draws}/${st.totalGames}`);
  saveStats();
  try { engine.stop(); } catch (e) { /* ignore */ }
  try {
    if (cfg.AUTH_STATE_FILE && context) await context.storageState({ path: cfg.AUTH_STATE_FILE });
  } catch (e) { /* ignore */ }
  try { if (browser) await browser.close(); } catch (e) { /* ignore */ }
  process.exit(0);
}

// ---------------- main ----------------
(async () => {
  console.log('='.repeat(56));
  console.log('BOT CARO GAMEVH - Playwright login + ENGINE EMBRYO (Caro6)');
  console.log('='.repeat(56));
  log('BOT', `Tai khoan: ${cfg.USER} | cuoc ${cfg.BET_XU}xu | headless=${cfg.HEADLESS} | runtime ${cfg.RUNTIME_HOURS}h`);

  // dam bao engine co mat
  const bin = await EmbryoEngine.ensureBinary();
  log('BOT', bin ? 'Engine ready: ' + bin : 'CANH BAO: khong co engine -> se danh fallback gan nuoc cuoi');

  browser = await chromium.launch({
    headless: cfg.HEADLESS,
    args: ['--no-first-run', '--no-default-browser-check', '--disable-infobars'],
  });
  const storageState = (cfg.AUTH_STATE_FILE && fs.existsSync(cfg.AUTH_STATE_FILE)) ? cfg.AUTH_STATE_FILE : undefined;
  context = await browser.newContext({
    locale: 'vi-VN',
    timezoneId: 'Asia/Ho_Chi_Minh',
    viewport: { width: cfg.VIEWPORT_W, height: cfg.VIEWPORT_H },
    userAgent: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
    storageState,
  });
  // tiem bridge vao moi trang truoc khi JS game chay
  await context.addInitScript(buildBridgeSource());

  page = await context.newPage();
  await setupPage(page);

  // 1) DANG NHAP nhu nguoi that
  let loginDone = false;
  for (let attempt = 1; attempt <= 3 && !loginDone; attempt++) {
    try { loginDone = await humanLogin(page); }
    catch (e) { log('BOT', `Login lan ${attempt} loi: ${e.message}`); await sleep(2000); await page.reload({ waitUntil: 'domcontentloaded' }).catch(() => {}); }
  }
  if (!loginDone) { log('BOT', 'Dang nhap that bai 3 lan -> thoat'); await shutdown(); return; }

  // 2) Vao game cho client tu bat tay WS
  await waitBridgeReady(60000);
  if (!(await waitLoginOk(30000))) {
    log('BOT', 'Khong thay LOGIN OK -> reload thu lai');
    await reloadPage('khong-login-ok');
    await waitBridgeReady(60000);
    if (!(await waitLoginOk(30000))) { log('BOT', 'Van khong login duoc -> thoat'); await shutdown(); return; }
  }
  const s0 = await getBridgeState();
  log('BOT', `Nick: ${s0.nickname} | token=${s0.token} | placePath=${s0.placePath}`);

  // cho client vao place (lobby) - best effort
  const enterEv = await waitForEvent(e => e.cmd === 'ENTER_PLACE' && e.parsed && e.parsed.status === 0, 20000);
  if (enterEv) log('BOT', 'ENTER_PLACE OK');
  else log('BOT', 'Khong thay ENTER_PLACE - van thu tao ban (client co the da tu vao)');

  // 3) watchdog + tao ban dau tien
  const wd = setInterval(() => { watchdogTick().catch(e => log('BOT', 'watchdog error: ' + e.message)); }, 10000);
  st._wd = wd;

  await createNewTable('khoi-dong');

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);

  // giu process chay cho event pump xu ly
  while (st.running) await sleep(1000);
})().catch(async (e) => {
  console.error('[FATAL]', e);
  await shutdown();
});
