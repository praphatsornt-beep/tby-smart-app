/* ==========================================================================
 * Coffee Log — LINE bot backend (Google Apps Script)
 *
 * แยกระบบต่างหากจาก gas_line_webhook.js โดยสิ้นเชิง — คนละ LINE Official
 * Account, คนละ Google account (บอทนี้อยู่ใต้ praphatsorn.t@gmail.com ส่วน
 * LINE OA "zhulian TBY" หลักของร้านอยู่ใต้ zhulian.ttby@gmail.com), และเขียน
 * ข้อมูลลง Google Sheets โดยตรง (SpreadsheetApp) ไม่แตะ Supabase/ระบบ TBY
 * SMART APP เลย — เก็บไฟล์นี้ไว้ในโปรเจกต์นี้แค่เพื่อสำรอง/อ้างอิงโค้ดเท่านั้น
 * ตัวจริงที่รันอยู่คือ Web App ที่ deploy แยกต่างหาก:
 *   https://script.google.com/macros/s/AKfycbwUFceMrT4n6udWPV0CweUfBh2U4zByvkTrgwHfslVWXOvlsYGh3L3dhw57AG7vFr50/exec
 * แก้ไฟล์นี้แล้วต้องไปแปะ/deploy ที่ Apps Script ตัวจริงเองด้วย ไม่มีการ sync
 * อัตโนมัติจาก git repo นี้ไปที่ Apps Script เลย
 *
 * ใช้จัดการสต็อกกาแฟแบบเลขซีเรียล ผ่าน LINE โดยมี 2 กลุ่มคำสั่งหลัก:
 *   - addcoffee [รหัสเริ่ม] [จำนวน]  (หรือ "addcoffee" เฉยๆ ให้ระบบถามทีละขั้น)
 *     ลงทะเบียนแถวซีเรียลใหม่ในชีท "Coffee" + ตัวอักษรตัวแรกของรหัส (เช่น
 *     BCG9451 → ชีท CoffeeB) สถานะเริ่มต้น "ว่าง"
 *   - out [ชีท] [วันที่] [เลขสมาชิก] [ชื่อ] [จำนวน]  เติมแถวว่างถัดไปในชีทนั้น
 *     ด้วยวันที่/ชื่อ/เลขสมาชิก แล้วตั้งสถานะ "ส่งแล้ว" — บรรทัดถัดไปพิมพ์แค่
 *     วันที่ เลขสมาชิก ชื่อ จำนวน (ไม่ต้องพิมพ์ชื่อชีทซ้ำ) ได้เลย
 *
 * ป้อนข้อมูลเข้ารายงานกระทบยอด TBYกาแฟ[เดือน]_2026.xlsx รายเดือน (ดู
 * .claude/skills/tby-accounting/SKILL.md หัวข้อ "Coffee serial number
 * reconciliation")
 *
 * ⚠️ security: ต้นฉบับที่ user ส่งมา (2026-09-21) hardcode LINE_ACCESS_TOKEN
 * เป็น plaintext ตรงๆ ในไฟล์ — repo นี้เป็น public GitHub repo จึงห้าม commit
 * token จริงลงไปเด็ดขาด เปลี่ยนมาอ่านจาก PropertiesService Script Properties
 * แทนแล้ว (แพทเทิร์นเดียวกับ gas_line_webhook.js) ต้องไปตั้งค่าใน Apps Script
 * ตัวจริง: Project Settings → Script Properties → เพิ่มคีย์ LINE_ACCESS_TOKEN
 * ========================================================================== */

function getLineAccessToken_() {
  return PropertiesService.getScriptProperties().getProperty('LINE_ACCESS_TOKEN');
}

function doPost(e) {
  if (!e || !e.postData) return;
  var contents = JSON.parse(e.postData.contents);
  var event = contents.events[0];
  if (!event || event.type !== 'message' || event.message.type !== 'text') return;

  var replyToken  = event.replyToken;
  var userMessage = event.message.text.trim();
  var _userId     = (event.source || {}).userId || '';
  var _cache      = CacheService.getScriptCache();
  var _cacheKey   = 'addcoffee_' + _userId;

  // ── หา LINE userId ของบัญชีที่คุยกับบอทนี้ (ใช้ตอน redirect การแจ้งเตือน
  // ของ TBY SMART APP มาที่บอทนี้แทน — userId เป็นค่าเฉพาะต่อ OA เท่านั้น) ──
  if (userMessage.toLowerCase() === 'myid') {
    replyMessage(replyToken, 'userId: ' + _userId);
    return;
  }

  // ── Multi-step addcoffee flow ────────────────────────────────────────────
  var _stateRaw = _userId ? _cache.get(_cacheKey) : null;
  if (_stateRaw) {
    var _state = JSON.parse(_stateRaw);

    if (userMessage === 'ยกเลิก') {
      _cache.remove(_cacheKey);
      replyMessage(replyToken, '❌ ยกเลิกแล้วค่ะ');
      return;
    }

    if (_state.step === 'waiting_serial') {
      if (!/^[A-Za-z]+\d+$/i.test(userMessage)) {
        replyMessage(replyToken, '❌ รหัสไม่ถูกต้อง (เช่น BCG9451)\nพิมพ์ใหม่ หรือ ยกเลิก');
        return;
      }
      _state.step   = 'waiting_qty';
      _state.serial = userMessage.toUpperCase();
      _cache.put(_cacheKey, JSON.stringify(_state), 300);
      replyMessage(replyToken, '📦 รหัสเริ่มต้น: ' + _state.serial + '\nจะเพิ่มกี่แก้ว?');
      return;
    }

    if (_state.step === 'waiting_qty') {
      var _qty = parseInt(userMessage);
      if (isNaN(_qty) || _qty <= 0) {
        replyMessage(replyToken, '❌ จำนวนไม่ถูกต้อง พิมพ์ใหม่ หรือ ยกเลิก');
        return;
      }
      _state.step = 'waiting_confirm';
      _state.qty  = _qty;
      _cache.put(_cacheKey, JSON.stringify(_state), 300);

      var _m    = _state.serial.match(/^([A-Za-z]+)(\d+)$/i);
      var _pfx  = _m[1].toUpperCase();
      var _sNum = parseInt(_m[2]);
      var _end  = _pfx + (_sNum + _qty - 1).toString().padStart(_m[2].length, '0');
      var _sh   = 'Coffee' + _pfx.charAt(0).toUpperCase();

      sendQuickReplyGas(replyToken,
        '📋 ตรวจสอบก่อนบันทึก\n' +
        '📊 ชีท: ' + _sh + '\n' +
        '🔢 ' + _state.serial + ' → ' + _end + '\n' +
        '📦 จำนวน: ' + _qty + ' รายการ',
        [
          { type: 'action', action: { type: 'message', label: '✅ ยืนยันบันทึก', text: 'ยืนยัน_addcoffee' } },
          { type: 'action', action: { type: 'message', label: '❌ ยกเลิก',       text: 'ยกเลิก'           } }
        ]
      );
      return;
    }

    if (_state.step === 'waiting_confirm') {
      if (userMessage === 'ยืนยัน_addcoffee') {
        _cache.remove(_cacheKey);
        replyMessage(replyToken, preRegisterSerials(SpreadsheetApp.getActiveSpreadsheet(), _state.serial, _state.qty));
      } else {
        sendQuickReplyGas(replyToken, '⚠️ กรุณากดปุ่มยืนยันหรือยกเลิก',
          [
            { type: 'action', action: { type: 'message', label: '✅ ยืนยันบันทึก', text: 'ยืนยัน_addcoffee' } },
            { type: 'action', action: { type: 'message', label: '❌ ยกเลิก',       text: 'ยกเลิก'           } }
          ]
        );
      }
      return;
    }
  }

  // ── เริ่ม addcoffee flow ──────────────────────────────────────────────────
  if (userMessage.toLowerCase() === 'addcoffee') {
    if (_userId) _cache.put(_cacheKey, JSON.stringify({ step: 'waiting_serial' }), 300);
    replyMessage(replyToken, '📦 addcoffee\nพิมพ์รหัสเริ่มต้น (เช่น BCG9451)\n\nพิมพ์ ยกเลิก เพื่อยกเลิก');
    return;
  }

  // ── คำสั่งปกติ ────────────────────────────────────────────────────────────
  var lines = userMessage.split(/\n/);
  var results = [];
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var lock = LockService.getScriptLock();
  var lastSheetName = "";

  lines.forEach(function(line) {
    var text = line.trim();
    if (!text) return;
    var data    = text.split(/\s+/);
    var command = data[0].toLowerCase();
    try {
      if (command === "out") {
        lastSheetName = data[1];
        results.push(handleCoffeeOut(ss, data.slice(1).join(" "), lock, true));
      } else if (/^\d{1,2}\/\d{1,2}\/\d{4}/.test(text)) {
        if (!lastSheetName) {
          results.push("❌ บรรทัดนี้ไม่มีชื่อชีทอ้างอิง: " + text);
        } else {
          results.push(handleCoffeeOut(ss, lastSheetName + " " + text, lock, false));
        }
      } else if (command === "addcoffee") {
        if (data.length >= 3) {
          results.push(preRegisterSerials(ss, data[1], parseInt(data[2])));
        } else {
          results.push("⚠️ พิมพ์ addcoffee เพียงอย่างเดียว แล้วระบบจะถามทีละขั้น");
        }
      } else if (command === "manual") {
        results.push("📖 คู่มือ:\n1. addcoffee → ระบบถามทีละขั้น\n   หรือ addcoffee [รหัสเริ่ม] [จำนวน]\n2. out [ชีท] [วันที่] [เลขสมาชิก] [ชื่อ] [จำนวน]\n(บรรทัดถัดไปพิมพ์แค่ วันที่ เลขสมาชิก ชื่อ จำนวน ได้เลย)");
      } else {
        results.push("⚠️ ไม่พบคำสั่ง: " + command);
      }
    } catch (err) {
      results.push("❌ Error: " + err.message);
    }
  });

  if (results.length > 0) replyMessage(replyToken, results.join("\n" + "━".repeat(15) + "\n"));
}

function handleCoffeeOut(ss, text, lock, isFirstLine) {
  if (!lock.tryLock(15000)) return "⚠️ ระบบไม่ว่าง";
  try {
    var match = text.match(/(\S+)\s+(\d{1,2}\/\d{1,2}\/\d{4})\s+(\S+)\s+(.*?)\s+(\d+)$/);
    if (!match) return "❌ รูปแบบผิด: " + text;

    var sheetName = match[1];
    var vDate     = parseDate(match[2]);
    var vMemberId = match[3];
    var vName     = match[4].trim();
    var vQty      = parseInt(match[5]);

    var sheet = ss.getSheetByName(sheetName);
    if (!sheet) return "❌ ไม่พบชีท: " + sheetName;

    var data = sheet.getDataRange().getValues();
    var count = 0;

    for (var i = 1; i < data.length && count < vQty; i++) {
      if (!data[i][4] || data[i][4] === "ว่าง") {
        var row = i + 1;
        sheet.getRange(row, 1).setValue(vDate).setNumberFormat("dd/mm/yyyy");
        sheet.getRange(row, 3).setValue(vName);
        sheet.getRange(row, 4).setValue("'" + vMemberId);
        sheet.getRange(row, 5).setValue("ส่งแล้ว");
        count++;
      }
    }

    var prefix = isFirstLine ? "✅ " + sheetName + ": " : "🔹 ";
    return prefix + vName + " (" + count + " แก้ว)";
  } finally { lock.releaseLock(); }
}

function preRegisterSerials(ss, sc, q) {
  var m = sc.match(/^([A-Za-z]+)(\d+)$/);
  if (!m) return "❌ รหัสผิด (เช่น BCG9451)";
  var prefix    = m[1];
  var startNum  = parseInt(m[2]);
  var sheetName = "Coffee" + prefix.charAt(0).toUpperCase();
  var sheet     = ss.getSheetByName(sheetName);
  if (!sheet) return "❌ ไม่พบชีท: " + sheetName;

  var rows = [];
  for (var i = 0; i < q; i++) {
    rows.push(["", prefix + (startNum + i).toString().padStart(m[2].length, "0"), "", "", "ว่าง"]);
  }
  sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, 5).setValues(rows);
  return "📦 เพิ่มใน " + sheetName + " " + q + " รายการสำเร็จ";
}

function parseDate(s) {
  var p = s.split('/');
  return new Date(p[2], p[1] - 1, p[0]);
}

function replyMessage(token, msg) {
  UrlFetchApp.fetch('https://api.line.me/v2/bot/message/reply', {
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + getLineAccessToken_() },
    method: 'post',
    payload: JSON.stringify({ replyToken: token, messages: [{ type: 'text', text: msg }] })
  });
}

function sendQuickReplyGas(token, text, items) {
  UrlFetchApp.fetch('https://api.line.me/v2/bot/message/reply', {
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + getLineAccessToken_() },
    method: 'post',
    payload: JSON.stringify({
      replyToken: token,
      messages: [{ type: 'text', text: text, quickReply: { items: items } }]
    })
  });
}
