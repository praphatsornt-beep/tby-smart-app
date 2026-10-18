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
 *   - addcoffee [รหัสเริ่ม] [จำนวนลัง]  (หรือ "addcoffee" เฉยๆ ให้ระบบถามทีละขั้น)
 *     ลงทะเบียนแถวซีเรียลใหม่ในชีท "Coffee" + ตัวอักษรตัวแรกของรหัส (เช่น
 *     BCG9451 → ชีท CoffeeB) สถานะเริ่มต้น "ว่าง" — "จำนวน" ที่กรอกคือจำนวน
 *     "ลัง" ไม่ใช่จำนวนห่อตรงๆ (เปลี่ยน 2026-09-21 ตามที่ user ระบุ): ตัวอักษร
 *     แรกของรหัส B = กาแฟ 40 ซอง ลังละ 18 ห่อ, S = กาแฟ 84 ซอง ลังละ 10 ห่อ
 *     (ดู `UNITS_PER_BOX` ด้านล่าง — ตัวอักษรอื่นที่ยังไม่รู้จัก default 1 ห่อ/ลัง
 *     คือพฤติกรรมเดิม) ตอบกลับบอกเลขซีเรียลตัวสุดท้ายที่ลงทะเบียนเสมอ
 *   - out [ชีท] [วันที่] [เลขสมาชิก] [ชื่อ] [จำนวน]  เติมแถวว่างถัดไปในชีทนั้น
 *     ด้วยวันที่/ชื่อ/เลขสมาชิก แล้วตั้งสถานะ "ส่งแล้ว" — บรรทัดถัดไปพิมพ์แค่
 *     วันที่ เลขสมาชิก ชื่อ จำนวน (ไม่ต้องพิมพ์ชื่อชีทซ้ำ) ได้เลย (จำนวนที่นี่ยัง
 *     เป็นจำนวนห่อตรงๆ เหมือนเดิม ไม่เกี่ยวกับ addcoffee/ลัง)
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

// ── Supabase REST (เพิ่ม 2026-10-18 เฉพาะคำสั่ง "รับคืน" ด้านล่าง) ──────────────
// บอทนี้ไม่เคยคุยกับ Supabase มาก่อน (เขียนลง Google Sheets อย่างเดียว ดูคอมเมนต์หัว
// ไฟล์) — ต้องตั้ง Script Properties เพิ่ม 2 ตัวใน Apps Script ตัวจริง: SUPABASE_URL
// (เช่น https://xxxx.supabase.co), SUPABASE_KEY (anon key จาก Supabase > Settings > API)
// ใช้ค่าเดียวกับที่ gas_line_webhook.js/tools/*.py ของ TBY SMART APP ใช้อยู่แล้วได้เลย
function getSupabaseUrl_() { return PropertiesService.getScriptProperties().getProperty('SUPABASE_URL'); }
function getSupabaseKey_() { return PropertiesService.getScriptProperties().getProperty('SUPABASE_KEY'); }
function _sbGet_(path) {
  return JSON.parse(UrlFetchApp.fetch(getSupabaseUrl_() + path, {
    headers: { 'apikey': getSupabaseKey_(), 'Authorization': 'Bearer ' + getSupabaseKey_() },
    muteHttpExceptions: true,
  }).getContentText());
}
function _sbPatch_(path, data) {
  UrlFetchApp.fetch(getSupabaseUrl_() + path, {
    method: 'PATCH',
    headers: {
      'apikey': getSupabaseKey_(), 'Authorization': 'Bearer ' + getSupabaseKey_(),
      'Content-Type': 'application/json', 'Prefer': 'return=minimal',
    },
    payload: JSON.stringify(data),
    muteHttpExceptions: true,
  });
}
function _sbPost_(table, data) {
  UrlFetchApp.fetch(getSupabaseUrl_() + '/rest/v1/' + table, {
    method: 'POST',
    headers: {
      'apikey': getSupabaseKey_(), 'Authorization': 'Bearer ' + getSupabaseKey_(),
      'Content-Type': 'application/json', 'Prefer': 'return=minimal',
    },
    payload: JSON.stringify(data),
    muteHttpExceptions: true,
  });
}

// จำนวนห่อต่อ 1 ลัง แยกตามตัวอักษรตัวแรกของรหัส (ตัวเดียวกับที่ใช้เลือกชีท
// "Coffee" + ตัวอักษรนี้) — B = กาแฟ 40 ซอง (ลังละ 18 ห่อ), S = กาแฟ 84 ซอง
// (ลังละ 10 ห่อ) เพิ่มเข้ามา 2026-09-21 ตามที่ user ระบุ ตัวอักษรอื่นที่ยังไม่
// รู้จัก default เป็น 1 (พฤติกรรมเดิม คือ "จำนวน" หมายถึงจำนวนห่อตรงๆ) —
// เพิ่มคู่ใหม่ตรงนี้ได้เลยถ้ามีสินค้าเพิ่ม
var UNITS_PER_BOX = { 'B': 18, 'S': 10 };

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

  // ── รับคืน CODE [CODE ...] — ยืนยันว่าพัสดุ Shopee ตีกลับได้คืนร้านจริงแล้ว ───────
  // เพิ่ม 2026-10-18: digest สรุปออเดอร์ Shopee ของ TBY SMART APP (tools/email_daily_
  // digest.py) ถูกย้ายมาส่งเข้า LINE OA นี้ (Coffee Log) แทน OA ลูกค้าหลัก "zhulian TBY"
  // แล้ว (กันข้อมูลภายในปนกับแชทลูกค้า — ดูคอมเมนต์หัวไฟล์/memory coffee-line-oa-separate-
  // system) ดังนั้นคำสั่งยืนยัน "ได้รับพัสดุตีกลับคืนแล้ว" ต้องอยู่ที่นี่ ไม่ใช่
  // gas_line_webhook.js (เคยเพิ่มผิดไฟล์ไปก่อน แก้ย้ายมาที่นี่) — พิมพ์รหัส order_sn
  // ตรงจากบรรทัด "📦 พัสดุ Shopee มีปัญหา/ตีกลับ" ในดิจ (ตัด # นำหน้าออกให้เอง) แล้วตั้ง
  // ecommerce_return_emails.received_back_at ผ่าน Supabase REST ตรงๆ — เหมือนปุ่ม
  // "✅ ยืนยันได้รับของคืนแล้ว" ที่หน้าแรกของแอป (db.mark_ecommerce_return_received)
  if (/^รับคืน\s+\S/i.test(userMessage)) {
    handleEcommerceReturnReceived_(userMessage.replace(/^รับคืน\s+/i, ''), replyToken, false);
    return;
  }
  if (/^ยืนยัน_รับคืน\s+\S/i.test(userMessage)) {
    handleEcommerceReturnReceived_(userMessage.replace(/^ยืนยัน_รับคืน\s+/i, ''), replyToken, true);
    return;
  }

  // ── sp — เมนู "รับคืน" ลิสต์พัสดุ Shopee ตีกลับที่ยังไม่ยืนยันรับคืน ให้เลือกจาก
  // Quick Reply ได้เลย (เพิ่ม 2026-10-18 ตามคำขอ: ไม่ต้องจำ/พิมพ์เลข order_sn เอง) —
  // เลือกแล้วบันทึกทันที (ส่ง "ยืนยัน_รับคืน CODE" ตรงๆ ไม่ต้องผ่านขั้นยืนยันซ้ำอีกที
  // เพราะตัวเลือกในลิสต์มาจาก DB จริงอยู่แล้ว ไม่มีความเสี่ยงพิมพ์รหัสผิด)
  if (userMessage.toLowerCase() === 'sp') {
    handleListUnreceivedReturns_(replyToken);
    return;
  }

  // ── บันทึกรายการขาย/เบิกของเข้า TBY SMART APP จากไลน์นี้โดยตรง ─────────────────
  // เพิ่ม 2026-10-18 ตามคำขอ (บอทนี้จะใช้บันทึกข้อมูลหลังร้านต่อไป ไม่ใช่แค่กาแฟ) —
  // พิมพ์ "[ชื่อลูกค้า] CODE-จำนวน [CODE-จำนวน ...]" เฉยๆ ไม่ต้องมีคำสั่งนำหน้า แล้วบอท
  // จะถามทีละขั้น (จ่ายเงิน/ไม่จ่าย → รับของ/ส่งของ → เปิดบิล/ไม่เปิดบิล → ยืนยัน/ยกเลิก)
  // ก่อนเขียนลง Supabase transactions จริง — ยืนยันกับผู้ใช้แล้ว 3 จุด:
  //   1. ไม่สร้างพัสดุ/ออเดอร์ iShip จริง — "ส่งของ" แค่ติดสถานะในระบบเฉยๆ (ตีความว่า
  //      ของยังไม่ถึงมือลูกค้าจริง เทียบเท่า "ฝากของ" ในแอปหลัก → initial_qty_received=0
  //      ส่วน "รับของ" = ลูกค้าได้ของแล้ว → initial_qty_received=qty เหมือน "รับของแล้ว"
  //      ของแอปหลัก — ดู record_ui.py's receive_now/m_receipt ถ้าตีความผิดแก้ได้ตรงนี้)
  //   2. รูปแบบคำสั่ง: พิมพ์ชื่อ+รายการเฉยๆ แล้วให้บอทถามทีละขั้น (ไม่ใช่คำสั่งสำเร็จรูป
  //      แบบ เบิก/เบิกจ่าย ของ gas_line_webhook.js)
  //   3. ไม่ต้องมี #staffTag นำหน้า — OA นี้ใช้ภายในอยู่แล้ว
  // ไม่มีขั้นยืนยันซ้อนสองรอบ (ตอบปุ่มสุดท้ายแล้วค่อยมีปุ่ม "ยืนยันบันทึก" อีกรอบเดียว)
  var _orderCacheKey  = 'tbyorder_' + _userId;
  var _orderStateRaw  = _userId ? _cache.get(_orderCacheKey) : null;
  if (_orderStateRaw) {
    var _orderState = JSON.parse(_orderStateRaw);

    if (userMessage === 'ยกเลิก') {
      _cache.remove(_orderCacheKey);
      replyMessage(replyToken, '❌ ยกเลิกแล้วค่ะ ยังไม่มีการบันทึกข้อมูล');
      return;
    }

    if (_orderState.step === 'waiting_pay' && (userMessage === 'จ่ายเงิน' || userMessage === 'ไม่จ่าย')) {
      _orderState.pay  = userMessage;
      _orderState.step = 'waiting_delivery';
      _cache.put(_orderCacheKey, JSON.stringify(_orderState), 300);
      sendQuickReplyGas(replyToken, '📦 รับของแล้ว หรือ ยังไม่ได้ส่งของ (ส่งของ)?', [
        { type: 'action', action: { type: 'message', label: 'รับของ', text: 'รับของ' } },
        { type: 'action', action: { type: 'message', label: 'ส่งของ', text: 'ส่งของ' } },
        { type: 'action', action: { type: 'message', label: '❌ ยกเลิก', text: 'ยกเลิก' } },
      ]);
      return;
    }
    if (_orderState.step === 'waiting_delivery' && (userMessage === 'รับของ' || userMessage === 'ส่งของ')) {
      _orderState.delivery = userMessage;
      _orderState.step     = 'waiting_bill';
      _cache.put(_orderCacheKey, JSON.stringify(_orderState), 300);
      sendQuickReplyGas(replyToken, '🧾 เปิดบิล หรือ ไม่เปิดบิล?', [
        { type: 'action', action: { type: 'message', label: 'เปิดบิล', text: 'เปิดบิล' } },
        { type: 'action', action: { type: 'message', label: 'ไม่เปิดบิล', text: 'ไม่เปิดบิล' } },
        { type: 'action', action: { type: 'message', label: '❌ ยกเลิก', text: 'ยกเลิก' } },
      ]);
      return;
    }
    if (_orderState.step === 'waiting_bill' && (userMessage === 'เปิดบิล' || userMessage === 'ไม่เปิดบิล')) {
      _orderState.bill = userMessage;
      _orderState.step = 'waiting_confirm';
      _cache.put(_orderCacheKey, JSON.stringify(_orderState), 300);
      sendQuickReplyGas(replyToken, buildTbyOrderPreview_(_orderState), [
        { type: 'action', action: { type: 'message', label: '✅ ยืนยันบันทึก', text: 'ยืนยัน_tbyorder' } },
        { type: 'action', action: { type: 'message', label: '❌ ยกเลิก', text: 'ยกเลิก' } },
      ]);
      return;
    }
    if (_orderState.step === 'waiting_confirm') {
      if (userMessage === 'ยืนยัน_tbyorder') {
        _cache.remove(_orderCacheKey);
        replyMessage(replyToken, commitTbyOrder_(_orderState));
      } else {
        sendQuickReplyGas(replyToken, '⚠️ กรุณากดปุ่มยืนยันหรือยกเลิกค่ะ', [
          { type: 'action', action: { type: 'message', label: '✅ ยืนยันบันทึก', text: 'ยืนยัน_tbyorder' } },
          { type: 'action', action: { type: 'message', label: '❌ ยกเลิก', text: 'ยกเลิก' } },
        ]);
      }
      return;
    }
    // พิมพ์อย่างอื่นมาตอนกำลังรออยู่กลางขั้น — เตือนให้เลือกจากปุ่มหรือยกเลิก
    replyMessage(replyToken, '⚠️ กรุณาเลือกจากปุ่มด้านบน หรือพิมพ์ "ยกเลิก" ค่ะ');
    return;
  }

  // ── เริ่มรายการใหม่: "[ชื่อลูกค้า] CODE-จำนวน [CODE-จำนวน ...]" ไม่ต้องมีคำสั่งนำหน้า —
  // รหัสสินค้าจริงเป็น LETTERS+4DIGITS เสมอ (ยืนยันแล้วทั้งระบบ) ใช้แยกส่วน "ชื่อ" ออก
  // จากส่วน "รายการ" แบบไม่ต้องมีคำสั่งคั่นกลาง
  var _orderStart = userMessage.match(/^(.+?)\s+((?:[A-Za-z]+\d{4}-\d+(?:\.\d+)?\s*)+)$/i);
  if (_orderStart) {
    startTbyOrder_(_orderStart[1].trim(), _orderStart[2].trim(), replyToken, _userId, _cache, _orderCacheKey);
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
      replyMessage(replyToken, '📦 รหัสเริ่มต้น: ' + _state.serial + '\nจะเพิ่มกี่ลัง?');
      return;
    }

    if (_state.step === 'waiting_qty') {
      var _boxQty = parseInt(userMessage);
      if (isNaN(_boxQty) || _boxQty <= 0) {
        replyMessage(replyToken, '❌ จำนวนไม่ถูกต้อง พิมพ์ใหม่ หรือ ยกเลิก');
        return;
      }
      _state.step = 'waiting_confirm';
      _state.qty  = _boxQty;   // เก็บเป็น "จำนวนลัง" — คูณเป็นจำนวนห่อจริงตอน preRegisterSerials
      _cache.put(_cacheKey, JSON.stringify(_state), 300);

      var _m           = _state.serial.match(/^([A-Za-z]+)(\d+)$/i);
      var _pfx         = _m[1].toUpperCase();
      var _sNum        = parseInt(_m[2]);
      var _firstLetter = _pfx.charAt(0);
      var _unitsPerBox = UNITS_PER_BOX[_firstLetter] || 1;
      var _totalUnits  = _boxQty * _unitsPerBox;
      var _end         = _pfx + (_sNum + _totalUnits - 1).toString().padStart(_m[2].length, '0');
      var _sh          = 'Coffee' + _firstLetter;

      sendQuickReplyGas(replyToken,
        '📋 ตรวจสอบก่อนบันทึก\n' +
        '📊 ชีท: ' + _sh + '\n' +
        '🔢 ' + _state.serial + ' → ' + _end + '\n' +
        '📦 จำนวน: ' + _boxQty + ' ลัง (' + _totalUnits + ' ห่อ)',
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
        results.push("📖 คู่มือ:\n1. addcoffee → ระบบถามทีละขั้น\n   หรือ addcoffee [รหัสเริ่ม] [จำนวนลัง] (B=18 ห่อ/ลัง, S=10 ห่อ/ลัง)\n2. out [ชีท] [วันที่] [เลขสมาชิก] [ชื่อ] [จำนวน]\n(บรรทัดถัดไปพิมพ์แค่ วันที่ เลขสมาชิก ชื่อ จำนวน ได้เลย)\n3. sp → ลิสต์พัสดุ Shopee ตีกลับที่ยังไม่ยืนยันรับคืน เลือกจากเมนูได้เลย\n   หรือ รับคืน CODE [CODE ...] → ยืนยันตรงๆ ด้วยรหัสออเดอร์ (ตามดิจสรุปรายวัน)\n4. [ชื่อลูกค้า] CODE-จำนวน [CODE-จำนวน ...] → บันทึกรายการเข้า TBY SMART APP (ระบบจะถามจ่ายเงิน/รับของ/เปิดบิลทีละขั้น)");
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

function preRegisterSerials(ss, sc, boxQty) {
  var m = sc.match(/^([A-Za-z]+)(\d+)$/);
  if (!m) return "❌ รหัสผิด (เช่น BCG9451)";
  var prefix      = m[1];
  var startNum    = parseInt(m[2]);
  var firstLetter = prefix.charAt(0).toUpperCase();
  var sheetName   = "Coffee" + firstLetter;
  var sheet       = ss.getSheetByName(sheetName);
  if (!sheet) return "❌ ไม่พบชีท: " + sheetName;

  // boxQty = จำนวนลัง ไม่ใช่จำนวนห่อโดยตรง — คูณด้วยจำนวนห่อ/ลังตามตัวอักษรแรกของ
  // รหัส (UNITS_PER_BOX) ก่อนสร้างแถวจริง (เพิ่ม 2026-09-21 ตามที่ user ระบุ)
  var unitsPerBox = UNITS_PER_BOX[firstLetter] || 1;
  var q = boxQty * unitsPerBox;

  var rows = [];
  for (var i = 0; i < q; i++) {
    rows.push(["", prefix + (startNum + i).toString().padStart(m[2].length, "0"), "", "", "ว่าง"]);
  }
  sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, 5).setValues(rows);

  var endSerial = prefix + (startNum + q - 1).toString().padStart(m[2].length, "0");
  return "📦 เพิ่มใน " + sheetName + " " + boxQty + " ลัง (" + q + " ห่อ)\n🔢 " + sc.toUpperCase() + " → " + endSerial;
}

function handleListUnreceivedReturns_(replyToken) {
  var rows = _sbGet_(
    '/rest/v1/ecommerce_return_emails?platform=eq.shopee&received_back_at=is.null' +
    '&select=order_sn,shop_name,carrier_name,tracking_no&order=last_seen_at.desc'
  ) || [];
  if (rows.length === 0) {
    replyMessage(replyToken, '✅ ไม่มีพัสดุ Shopee ตีกลับที่รอยืนยันรับคืนค่ะ');
    return;
  }

  if (rows.length <= 13) {
    var lines = rows.map(function(r) {
      return '📦 ' + r.order_sn + ' — ' + (r.shop_name || '-') + ' (' + (r.carrier_name || '-') + ' ' + (r.tracking_no || '-') + ')';
    });
    var items = rows.map(function(r) {
      return { type: 'action', action: { type: 'message', label: r.order_sn.substring(0, 20), text: 'ยืนยัน_รับคืน ' + r.order_sn } };
    });
    sendQuickReplyGas(replyToken, '📦 รับคืน — เลือกออเดอร์ที่ได้รับคืนแล้ว:\n' + lines.join('\n'), items);
  } else {
    // เกิน 13 รายการ — Quick Reply ของ LINE โชว์ได้สูงสุด 13 ปุ่ม แสดงรายการแรก 13
    // แบบข้อความล้วนแทน แล้วให้พิมพ์ "รับคืน CODE" เองสำหรับที่เหลือ
    var names = rows.slice(0, 13).map(function(r) { return r.order_sn; }).join(', ');
    replyMessage(replyToken, '📦 พัสดุตีกลับที่รอยืนยัน (' + rows.length + ' รายการ): ' + names + ' ...\nพิมพ์ "รับคืน CODE" เพื่อยืนยันค่ะ');
  }
}

function handleEcommerceReturnReceived_(rawCodes, replyToken, confirmed) {
  var codes = rawCodes.trim().split(/\s+/).map(function(c) { return c.replace(/^#/, '').toUpperCase(); });

  if (!confirmed) {
    sendQuickReplyGas(replyToken,
      '📦 ยืนยันว่าได้รับพัสดุตีกลับคืนร้านแล้ว:\n' + codes.join('\n') + '\n\n(จะบันทึกในระบบว่า "ได้รับคืนแล้ว")',
      [
        { type: 'action', action: { type: 'message', label: '✅ ยืนยันบันทึก', text: 'ยืนยัน_รับคืน ' + codes.join(' ') } },
        { type: 'action', action: { type: 'message', label: '❌ ยกเลิก', text: 'ยกเลิก' } }
      ]);
    return;
  }

  var enc = codes.map(function(c) { return encodeURIComponent(c); }).join(',');
  var existing = _sbGet_('/rest/v1/ecommerce_return_emails?platform=eq.shopee&order_sn=in.(' + enc + ')&select=order_sn') || [];
  var foundSet = {};
  existing.forEach(function(r) { foundSet[r.order_sn] = true; });
  var notFound = codes.filter(function(c) { return !foundSet[c]; });

  var msg = '';
  if (existing.length > 0) {
    _sbPatch_('/rest/v1/ecommerce_return_emails?platform=eq.shopee&order_sn=in.(' + enc + ')',
      { received_back_at: new Date().toISOString() });
    msg += '✅ บันทึกแล้วว่าได้รับคืน:\n' + existing.map(function(r) { return r.order_sn; }).join('\n') + '\n';
  }
  if (notFound.length > 0) {
    msg += '⚠️ ไม่พบรหัสนี้ในระบบ เช็คอีกทีค่ะ: ' + notFound.join(', ');
  }
  replyMessage(replyToken, msg.trim() || '❌ ไม่พบรหัสที่พิมพ์ในระบบเลย');
}

// ── ───────────────────────────────────────────────────────────────────────────
// ฟังก์ชันสำหรับ "บันทึกรายการขาย/เบิกของเข้า TBY SMART APP" (เพิ่ม 2026-10-18) —
// พอร์ตมาจาก gas_line_webhook.js's _getProducts/numFmt/_today/_getNextBillNo/
// findOneCustomer (ชื่อฟังก์ชันต่อ _ ท้ายกันชนกับต้นฉบับ เผื่อวันหลังก็อปโค้ดชิ้นอื่น
// มาจากไฟล์นั้นเพิ่มแล้วชื่อซ้ำกัน) — ตัดส่วน COD/ค่าส่ง/iShip ออกหมด เพราะฟีเจอร์นี้
// แค่ติดสถานะในระบบ ไม่สร้างพัสดุจริง (ยืนยันกับผู้ใช้แล้ว)
// ── ───────────────────────────────────────────────────────────────────────────

var _cachedProducts_ = null;
function _getProducts_() {
  if (_cachedProducts_) return _cachedProducts_;
  var _raw = _sbGet_('/rest/v1/products?select=id,name,name_mm,price,points_per_unit,weight_grams&order=id');
  if (!Array.isArray(_raw)) {
    throw new Error('_getProducts_ non-array response: ' + JSON.stringify(_raw));
  }
  _cachedProducts_ = _raw.map(function(p) {
    return [p.id, p.name, p.name_mm || '', p.price, p.points_per_unit, (p.weight_grams || 0) / 1000];
  });
  return _cachedProducts_;
}

function numFmt_(n) {
  return Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function _todayBkk_() {
  return Utilities.formatDate(new Date(), 'Asia/Bangkok', 'yyyy-MM-dd');
}

// เลขที่บิล YYMMDD-NNN ถัดไป (รูปแบบเดียวกับ database.py get_next_bill_no /
// gas_line_webhook.js's _getNextBillNo)
function _getNextBillNo_(dateStr) {
  var prefix = dateStr.replace(/-/g, '').substring(2);
  var rows = _sbGet_('/rest/v1/transactions?bill_no=like.' + prefix + '-*&select=bill_no') || [];
  var maxNum = 0;
  rows.forEach(function(r) {
    var bn = r.bill_no || '';
    if (bn.indexOf(prefix + '-') === 0) {
      var n = parseInt(bn.split('-')[1], 10);
      if (!isNaN(n) && n > maxNum) maxNum = n;
    }
  });
  var next = maxNum + 1;
  var nextStr = next < 10 ? '00' + next : next < 100 ? '0' + next : '' + next;
  return prefix + '-' + nextStr;
}

// Levenshtein edit distance (ตัวเล็ก-ใหญ่ไม่สน) — ใช้หาชื่อ "ใกล้เคียง" ให้เลือกตอน
// ไม่เจอตรงๆ เลย (เพิ่ม 2026-10-18 ตามคำขอ) ไม่มี library ให้ใช้ใน Apps Script เลย
// เขียน DP ตรงไปตรงมา (O(n*m) โอเคสำหรับความยาวชื่อคน ไม่ใช่ข้อความยาวๆ)
function _levenshtein_(a, b) {
  a = (a || '').toLowerCase(); b = (b || '').toLowerCase();
  var m = a.length, n = b.length;
  var dp = [];
  for (var i = 0; i <= m; i++) { dp.push([i]); }
  for (var j = 0; j <= n; j++) { dp[0][j] = j; }
  for (var i = 1; i <= m; i++) {
    for (var j = 1; j <= n; j++) {
      dp[i][j] = a.charAt(i - 1) === b.charAt(j - 1)
        ? dp[i - 1][j - 1]
        : 1 + Math.min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]);
    }
  }
  return dp[m][n];
}

// ค้นหาลูกค้า 1 คนจากชื่อ — ต่างจาก gas_line_webhook.js's findOneCustomer 2 จุด:
// (1) ตอบข้อความชัดเจนเมื่อไม่พบเลย (ไม่เงียบ) เพราะที่นี่ไม่มีคำสั่งนำหน้าบอกเจตนา
// ("[ชื่อ] CODE-จำนวน" ธรรมดา) ผู้ใช้ควรรู้ทันทีว่าพิมพ์ชื่อผิดหรือหาไม่เจอ ไม่ใช่เงียบ
// แล้วงงว่าทำไมบอทไม่ตอบ (2) ถ้าหาไม่เจอเลยทั้ง ilike และตัดช่องว่างเทียบ ลองเสนอชื่อ
// "ใกล้เคียง" ด้วย Levenshtein distance ให้เลือกแทนที่จะจบที่ "ไม่พบ" เฉยๆ (เพิ่มตามคำขอ
// 2026-10-18 — เผื่อพิมพ์ชื่อผิด/สะกดเพี้ยนเล็กน้อย เช่นพิมพ์ "Pyu Win" แทน "Phyu Win")
function findOneCustomer_(name, replyToken, resendTemplate) {
  var enc = encodeURIComponent('%' + name + '%');
  var rows = _sbGet_('/rest/v1/customers?name=ilike.' + enc + '&select=id,name');
  var allRows = null; // ดึงทั้งหมดครั้งเดียว ใช้ซ้ำได้ทั้ง fallback ตัดช่องว่าง และ fuzzy ด้านล่าง

  if (!rows || rows.length === 0) {
    allRows = _sbGet_('/rest/v1/customers?select=id,name') || [];
    var needle = name.trim().toLowerCase().replace(/\s+/g, '');
    rows = allRows.filter(function(c) {
      return c.name.toLowerCase().replace(/\s+/g, '').indexOf(needle) !== -1;
    });
  }

  if (!rows || rows.length === 0) {
    if (!allRows) allRows = _sbGet_('/rest/v1/customers?select=id,name') || [];
    var needleTrim = name.trim();
    var scored = allRows.map(function(c) { return { c: c, dist: _levenshtein_(needleTrim, c.name) }; })
      .sort(function(a, b) { return a.dist - b.dist; });
    // threshold ยอมรับ — ผ่อนตามความยาวชื่อที่พิมพ์มา (ชื่อสั้นต้องใกล้เคียงกว่าชื่อยาว)
    var threshold = Math.max(2, Math.ceil(needleTrim.length * 0.5));
    var close = scored.filter(function(s) { return s.dist <= threshold; }).slice(0, 5).map(function(s) { return s.c; });

    if (close.length > 0) {
      var closeItems = close.map(function(c) {
        var text = (resendTemplate || '{name}').replace('{name}', c.name);
        return { type: 'action', action: { type: 'message', label: c.name.substring(0, 20), text: text } };
      });
      sendQuickReplyGas(replyToken, '❓ ไม่พบ "' + name + '" ตรงๆ — ใกล้เคียงชื่อนี้ไหมคะ:', closeItems);
      return null;
    }
    replyMessage(replyToken, '❌ ไม่พบลูกค้าชื่อ "' + name + '" ในระบบค่ะ');
    return null;
  }

  if (rows.length === 1 && rows[0].name.toLowerCase() !== name.trim().toLowerCase()) {
    var firstWord = name.trim().split(/\s+/)[0];
    if (firstWord.length >= 2) {
      var prefixEnc = encodeURIComponent(firstWord + '%');
      var similar = _sbGet_('/rest/v1/customers?name=ilike.' + prefixEnc + '&select=id,name') || [];
      if (similar.length > 1) rows = similar;
    }
  }

  if (rows.length > 1) {
    if (rows.length <= 13) {
      var items = rows.map(function(c) {
        var text = (resendTemplate || '{name}').replace('{name}', c.name);
        return { type: 'action', action: { type: 'message', label: c.name.substring(0, 20), text: text } };
      });
      sendQuickReplyGas(replyToken, '🔍 พบ ' + rows.length + ' คน ตรงกับ "' + name + '" เลือกเลยค่ะ:', items);
    } else {
      var names = rows.slice(0, 13).map(function(c) { return c.name; }).join(', ');
      replyMessage(replyToken, '🔍 พบ ' + rows.length + ' คน: ' + names + ' ...\nพิมพ์ชื่อให้ชัดขึ้นค่ะ');
    }
    return null;
  }
  return rows[0];
}

// เริ่มรายการใหม่ — ตรวจสินค้า/ลูกค้าให้ครบก่อน แล้วเข้าขั้นแรกของ flow (ถามจ่ายเงินไหม)
function startTbyOrder_(name, itemsText, replyToken, userId, cache, orderCacheKey) {
  var itemTokens = itemsText.trim().split(/\s+/);
  var pData = _getProducts_();
  var lines = '', notFound = '', valid = [];

  itemTokens.forEach(function(tok) {
    var p    = tok.split('-');
    var code = p[0].toUpperCase();
    var qty  = parseFloat(p[1]);
    var prod = null;
    for (var i = 0; i < pData.length; i++) {
      if (pData[i][0].toString().toUpperCase() === code) {
        prod = { name: pData[i][1], price: pData[i][3], pv: pData[i][4] };
        break;
      }
    }
    if (!prod) { notFound += '❌ ไม่พบสินค้า [' + code + ']\n'; return; }
    var totalAmt = prod.price * qty;
    valid.push({ code: code, qty: qty, name: prod.name, price: prod.price, pv: prod.pv, totalAmt: totalAmt });
    lines += '📦 [' + code + '] ' + prod.name + '\n      ' + qty + ' ชิ้น x ฿' + numFmt_(prod.price) + ' = ฿' + numFmt_(totalAmt) + '\n';
  });

  if (valid.length === 0) {
    replyMessage(replyToken, notFound || '❌ ไม่พบสินค้าที่ระบุ');
    return;
  }

  var _resendItems = valid.map(function(it) { return it.code + '-' + it.qty; }).join(' ');
  var cust = findOneCustomer_(name, replyToken, '{name} ' + _resendItems);
  if (!cust) return; // findOneCustomer_ ตอบไปแล้ว (ไม่พบ/ให้เลือกจากเมนู)

  var state = {
    step: 'waiting_pay',
    custId: cust.id, custName: cust.name,
    items: valid, lines: lines, notFound: notFound,
  };
  if (userId) cache.put(orderCacheKey, JSON.stringify(state), 300);

  sendQuickReplyGas(replyToken,
    (notFound ? notFound + '\n' : '') + '📋 คุณ' + cust.name + '\n' + lines + '\n💰 จ่ายเงินหรือยัง?',
    [
      { type: 'action', action: { type: 'message', label: 'จ่ายเงิน', text: 'จ่ายเงิน' } },
      { type: 'action', action: { type: 'message', label: 'ไม่จ่าย', text: 'ไม่จ่าย' } },
      { type: 'action', action: { type: 'message', label: '❌ ยกเลิก', text: 'ยกเลิก' } },
    ]
  );
}

function buildTbyOrderPreview_(state) {
  var totalAll = state.items.reduce(function(s, it) { return s + it.totalAmt; }, 0);
  var totalPV  = state.items.reduce(function(s, it) { return s + it.pv * it.qty; }, 0);
  var payLabel   = state.pay      === 'จ่ายเงิน' ? '✅ จ่ายแล้ว' : '🔴 ค้างจ่าย';
  var delivLabel = state.delivery === 'รับของ'   ? '✅ รับของแล้ว' : '📦 ยังไม่ได้รับ (ส่งของ)';
  var billLabel  = state.bill     === 'เปิดบิล'   ? '🧾 เปิดบิลแล้ว' : '📋 ยังไม่เปิดบิล';

  var msg = '📋 ตรวจสอบก่อนบันทึก: คุณ' + state.custName + '\n';
  msg += '─────────────────\n' + state.lines + '─────────────────\n';
  msg += '💰 ยอดรวม: ฿' + numFmt_(totalAll) + ' (' + payLabel + ')\n';
  msg += '📦 สถานะรับของ: ' + delivLabel + '\n';
  msg += '🧾 สถานะบิล: ' + billLabel + '\n';
  if (state.bill === 'ไม่เปิดบิล') msg += '✨ คะแนนรอเปิดบิล: ' + numFmt_(totalPV) + ' PV\n';
  return msg;
}

// บันทึกจริงลง Supabase transactions — สูตร transaction_type/initial_qty_received
// เดียวกับ record_ui.py's บันทึกขาย (receive_now/m_bill logic)
function commitTbyOrder_(state) {
  var today        = _todayBkk_();
  var billNo        = _getNextBillNo_(today);
  var receiveNow    = state.delivery === 'รับของ';
  var billStatus    = state.bill === 'เปิดบิล' ? 'เปิดบิลแล้ว' : 'ยังไม่เปิดบิล';
  var payStatus     = state.pay  === 'จ่ายเงิน' ? 'จ่ายแล้ว' : 'ค้างจ่าย';
  var transactionType = (billStatus === 'ยังไม่เปิดบิล' && receiveNow) ? 'เบิกของก่อน' : 'ขายปกติ';

  state.items.forEach(function(it) {
    _sbPost_('transactions', {
      id: Utilities.getUuid(),
      date: today,
      customer_id: state.custId,
      product_id: it.code,
      product_name: it.name,
      qty: it.qty,
      price_per_unit: it.price,
      points_per_unit: it.pv,
      total_amount: it.totalAmt,
      initial_qty_received: receiveNow ? it.qty : 0,
      transaction_type: transactionType,
      bill_status: billStatus,
      pay_status: payStatus,
      notes: 'บันทึกผ่าน LINE Coffee Log',
      bill_no: billNo,
    });
  });

  var totalAll = state.items.reduce(function(s, it) { return s + it.totalAmt; }, 0);
  var totalPV  = state.items.reduce(function(s, it) { return s + it.pv * it.qty; }, 0);
  var msg = '✅ บันทึกแล้ว คุณ' + state.custName + '\n';
  msg += '─────────────────\n' + state.lines + '─────────────────\n';
  msg += '💰 ยอดรวม: ฿' + numFmt_(totalAll) + (payStatus === 'จ่ายแล้ว' ? ' (จ่ายแล้ว)' : ' (ค้างจ่าย)') + '\n';
  if (billStatus === 'ยังไม่เปิดบิล') msg += '✨ คะแนนรอเปิดบิล: ' + numFmt_(totalPV) + ' PV\n';
  msg += '🧾 เลขที่บิล: ' + billNo + '\n';
  return msg;
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
