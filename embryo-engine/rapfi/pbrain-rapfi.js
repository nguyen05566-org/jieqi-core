#!/usr/bin/env node
// pbrain-rapfi.js — Node wrapper cho Rapfi WASM (Gomocup protocol qua stdin/stdout).
// Thay thế pbrain-embryo: đọc lệnh từ stdin, đẩy vào engine, stdout engine ghi ra stdout.
//
// QUAN TRỌNG (root-cause của bug cũ): engine xử lý lệnh đồng bộ trong
// sendCommand() -> gomocupLoopOnce(). Khi ở BOARD-input mode, engine tự đọc
// tiếp từ FS-input callback cho tới DONE; nếu queue rỗng thì callback trả
// null = engine hiểu là hết input -> auto-DONE với bàn thiếu đá -> đi sai.
// Giải pháp: gom cả block "BOARD ... DONE" thành MỘT entry nhiều dòng trong
// queue (sendCommand với chuỗi chứa '\n') — callback đi hết chuỗi, không bao
// giờ rỗng giữa chừng. Nudge bằng dòng rống nếu loop-once trả sớm.
'use strict';
const path = require('path');
const fs = require('fs');

const createRapfi = require(path.join(__dirname, 'rapfi-single-simd128.js'));

const dbgPath = process.env.RAPFI_DEBUG_LOG || null;
const t0 = Date.now();
function dbg(msg) {
  if (dbgPath) {
    try { fs.appendFileSync(dbgPath, `${Date.now() - t0}ms ${msg}\n`); } catch (e) {}
  }
}

let engine = null;
let ready = false;
let dead = false;
let sbuf = '';
let blockBuf = null;      // đang gom BOARD..DONE
let nudgeTimer = null;
let moveSeen = false;

function isMoveLine(s) { return /^\d+\s*,\s*\d+$/.test(s.trim()); }

function emit(line) {
  if (dead) return;
  if (isMoveLine(line)) moveSeen = true;
  try { process.stdout.write(line + '\n'); } catch (e) { /* pipe closed */ }
}

function stopNudge() {
  if (nudgeTimer) { clearInterval(nudgeTimer); nudgeTimer = null; }
}

function sendBlock(block) {
  if (dead || !engine) return;
  moveSeen = false;
  dbg(`sendBlock ${block.split('\n').length} lines`);
  try { engine.sendCommand(block); }
  catch (e) { dbg(`sendBlock ERROR: ${e && e.message ? e.message : e}`); return; }
  // Nếu gomocupLoopOnce trả sau dòng đầu (loop-once), nudge k() bằng dòng
  // rỗng để engine tiếp tục đọc phần còn lại của block cho tới khi có nước.
  stopNudge();
  nudgeTimer = setInterval(() => {
    if (dead || moveSeen) { stopNudge(); return; }
    try { engine.sendCommand(''); } catch (e) { stopNudge(); }
  }, 40);
  setTimeout(() => stopNudge(), 15000);
}

function handleCommand(cmd) {
  dbg(`line: ${cmd}`);
  if (/^BOARD$/i.test(cmd)) { blockBuf = [cmd]; return; }
  if (blockBuf !== null) {
    blockBuf.push(cmd);
    if (/^DONE$/i.test(cmd)) {
      const block = blockBuf.join('\n');
      blockBuf = null;
      sendBlock(block);
    }
    return;
  }
  if (!engine || !ready) { dbg('drop (engine not ready)'); return; }
  try { engine.sendCommand(cmd); }
  catch (e) { dbg(`send ERROR: ${e && e.message ? e.message : e}`); }
}

function pumpStdin() {
  if (dead) return;
  const b = Buffer.alloc(65536);
  let n = 0;
  try { n = fs.readSync(0, b, 0, 65536); } catch (e) {
    setTimeout(pumpStdin, 10); return;
  }
  if (n === 0) { setTimeout(pumpStdin, 10); return; }
  sbuf += b.toString('utf8', 0, n);
  let idx;
  while ((idx = sbuf.indexOf('\n')) >= 0 && !dead) {
    const line = sbuf.slice(0, idx).trim();
    sbuf = sbuf.slice(idx + 1);
    if (line) handleCommand(line);
  }
  setTimeout(pumpStdin, 0);
}

dbg(`boot pid=${process.pid} node=${process.version}`);

createRapfi({
  locateFile: (url) => path.join(__dirname, /^rapfi.*\.data$/.test(url) ? 'rapfi.data' : path.basename(url)),
  onReceiveStdout: (o) => { const s = String(o); dbg(`out: ${s.slice(0, 60)}`); emit(s); },
  onReceiveStderr: () => {},
  onExit: (code) => { dbg(`exit ${code}`); dead = true; process.exit(typeof code === 'number' ? code : 0); },
  setStatus: () => {},
}).then((inst) => {
  engine = inst;
  ready = true;
  dbg('ready');
  pumpStdin();
}).catch((err) => {
  dbg(`init ERROR: ${err && err.message ? err.message : err}`);
  process.stderr.write('[rapfi-wrapper] init error: ' + err + '\n');
  process.exit(1);
});

process.on('SIGTERM', () => { dead = true; process.exit(0); });
process.on('SIGINT', () => { dead = true; process.exit(0); });
