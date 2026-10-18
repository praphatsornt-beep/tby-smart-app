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

  // ── คืนคะแนน [ชื่อลูกค้า] [bill_no] — ผูกบิลจริงที่เปิดแล้วเข้ากับยืมคะแนนที่ค้างคืน ───
  // เพิ่ม 2026-10-18 ตามคำขอ — คู่กับแท็บ 💳 ยืมคะแนน ของแอป Streamlit (pv_loan_ui.py/
  // pv_loans+pv_loan_repayments) บิลที่จะคืนต้องมีอยู่แล้วจริง (เปิดบิลแล้วผ่านบันทึกขาย
  // ปกติ หรือผ่านคำสั่ง "[ชื่อ] CODE-จำนวน..." ด้านล่างนี้ก่อน) คำสั่งนี้แค่ผูก/คำนวณ
  // ฿/PV/BV ของบิลนั้นเข้ากับยืมคะแนนที่ยังค้างอยู่ — ไม่สร้าง transactions ใหม่
  var _repayPv = userMessage.match(/^คืนคะแนน\s+(.+?)\s+(\S+)$/i);
  if (_repayPv) {
    handlePvRepayment_(_repayPv[1].trim(), _repayPv[2].trim(), replyToken);
    return;
  }
  // เลือกว่าจะคืนให้ยืมรายการไหน (ลูกค้าคนนี้มียืมค้างมากกว่า 1 รายการ)
  var _repayPvPick = userMessage.match(/^คืนคะแนน_เลือก\s+(\S+)\s+(\S+)$/i);
  if (_repayPvPick) {
    handlePvRepaymentPick_(_repayPvPick[1], _repayPvPick[2], replyToken);
    return;
  }
  var _repayPvConfirm = userMessage.match(/^ยืนยัน_คืนคะแนน\s+(\S+)\s+(\S+)$/i);
  if (_repayPvConfirm) {
    commitPvRepayment_(_repayPvConfirm[1], _repayPvConfirm[2], replyToken);
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
        { type: 'action', action: { type: 'message', label: 'บันทึกขาย+คืนคะแนน', text: 'เปิดบิล_คืนคะแนน' } },
        { type: 'action', action: { type: 'message', label: 'บันทึกขาย+ยืมคะแนน', text: 'เปิดบิล_ยืมคะแนน' } },
        { type: 'action', action: { type: 'message', label: 'ไม่เปิดบิล', text: 'ไม่เปิดบิล' } },
        { type: 'action', action: { type: 'message', label: '❌ ยกเลิก', text: 'ยกเลิก' } },
      ]);
      return;
    }
    if (_orderState.step === 'waiting_bill'
        && (userMessage === 'เปิดบิล' || userMessage === 'ไม่เปิดบิล'
            || userMessage === 'เปิดบิล_คืนคะแนน' || userMessage === 'เปิดบิล_ยืมคะแนน')) {
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
        commitTbyOrder_(_orderState, replyToken);
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
        results.push("📖 คู่มือ:\n1. addcoffee → ระบบถามทีละขั้น\n   หรือ addcoffee [รหัสเริ่ม] [จำนวนลัง] (B=18 ห่อ/ลัง, S=10 ห่อ/ลัง)\n2. out [ชีท] [วันที่] [เลขสมาชิก] [ชื่อ] [จำนวน]\n(บรรทัดถัดไปพิมพ์แค่ วันที่ เลขสมาชิก ชื่อ จำนวน ได้เลย)\n3. sp → ลิสต์พัสดุ Shopee ตีกลับที่ยังไม่ยืนยันรับคืน เลือกจากเมนูได้เลย\n   หรือ รับคืน CODE [CODE ...] → ยืนยันตรงๆ ด้วยรหัสออเดอร์ (ตามดิจสรุปรายวัน)\n4. [ชื่อลูกค้า] CODE-จำนวน [CODE-จำนวน ...] → บันทึกรายการเข้า TBY SMART APP (ระบบจะถามจ่ายเงิน/รับของ/เปิดบิลทีละขั้น — ตอนถามเปิดบิล เลือก \"บันทึกขาย+คืนคะแนน\" ได้เลยถ้าบิลนี้คือที่ลูกค้าจะใช้คืนคะแนนที่ยืมไว้ หรือเลือก \"บันทึกขาย+ยืมคะแนน\" ถ้าบิลนี้คือที่ลูกค้าขอให้เปิดไปก่อนเพื่อยืมคะแนน ไม่ต้องพิมพ์คำสั่งแยกอีกรอบ)\n5. คืนคะแนน [ชื่อลูกค้า] [เลขบิล] → ผูกบิลที่เปิดแล้วอยู่ก่อนเข้ากับยืมคะแนนที่ค้างคืน (ใช้ตอนบิลนั้นถูกบันทึกไว้แล้วก่อนหน้า)");
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
  var billLabel  = state.bill === 'เปิดบิล' ? '🧾 เปิดบิลแล้ว'
    : state.bill === 'เปิดบิล_คืนคะแนน' ? '🧾 เปิดบิลแล้ว + 🔗 คืนคะแนน'
    : state.bill === 'เปิดบิล_ยืมคะแนน' ? '🧾 เปิดบิลแล้ว + 📝 ยืมคะแนน'
    : '📋 ยังไม่เปิดบิล';

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
// ส่ง replyToken มาด้วยแทนการ return ข้อความเฉยๆ (เดิม) เพราะกรณี "เปิดบิล_คืนคะแนน"
// ที่มียืมคะแนนค้างมากกว่า 1 รายการ ต้องส่งเป็น Quick Reply ปุ่มเลือก ไม่ใช่ข้อความล้วน
function commitTbyOrder_(state, replyToken) {
  var today        = _todayBkk_();
  var billNo        = _getNextBillNo_(today);
  var receiveNow    = state.delivery === 'รับของ';
  var linkPv        = state.bill === 'เปิดบิล_คืนคะแนน';
  var linkLend      = state.bill === 'เปิดบิล_ยืมคะแนน';
  var billStatus    = (state.bill === 'เปิดบิล' || linkPv || linkLend) ? 'เปิดบิลแล้ว' : 'ยังไม่เปิดบิล';
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

  if (!linkPv && !linkLend) {
    replyMessage(replyToken, msg);
    return;
  }

  // ── "บันทึกขาย เก็บ PV ยืมคะแนน" — สร้างรายการยืมคะแนนใหม่ทันทีจากบิลที่เพิ่งเปิดนี้
  // (เพิ่ม 2026-10-18 ตามคำขอ — คู่กับ "บันทึกขาย+คืนคะแนน" ด้านบน ปิดวงจรยืม/คืนคะแนน
  // ให้ทำจบในไลน์ได้ทั้งหมด ไม่ต้องสลับไปเปิดแอป Streamlit) ง่ายกว่าฝั่งคืนคะแนนเพราะ
  // "ยืม" คือสร้างเรคอร์ดใหม่เสมอ ไม่มีของเดิมให้ค้นหา/เลือกแบบฝั่งคืนคะแนน — พอร์ตตรงจาก
  // pv_loan_ui.py's "➕ บันทึกยืมคะแนนใหม่" (สร้าง pv_loans 1 แถว, pv_lent/bv_lent/baht_lent
  // เป็น snapshot จาก get_bill_totals ตอนนั้นเลย ไม่ join สดทุกครั้งที่อ่านทีหลัง)
  if (linkLend) {
    var lendTotals = _getBillTotals_(billNo);
    _sbPost_('pv_loans', {
      id: Utilities.getUuid(), customer_id: state.custId, lend_date: today, lend_bill_no: billNo,
      pv_lent: lendTotals.pv, bv_lent: lendTotals.bv, baht_lent: lendTotals.baht,
      notes: 'บันทึกผ่าน LINE Coffee Log',
    });
    msg += '📝 บันทึกยืมคะแนนให้คุณ' + state.custName + ' แล้ว (' + numFmt_(lendTotals.pv) + ' PV)\n';
    replyMessage(replyToken, msg);
    return;
  }

  // ── "เปิดบิล เก็บ PV คืนคะแนน" — ผูกบิลที่เพิ่งเปิดนี้เข้ากับยืมคะแนนที่ค้างคืนของ
  // ลูกค้าคนนี้ทันที ไม่ต้องพิมพ์คำสั่ง "คืนคะแนน" แยกอีกรอบทีหลัง (เพิ่ม 2026-10-18
  // ตามคำขอ — เดิมถ้าบิลที่จะคืนยังไม่มีอยู่ในระบบเลย ต้องเปิดบิลผ่านคำสั่งนี้ก่อน
  // แล้วค่อยพิมพ์ "คืนคะแนน" แยกอีกคำสั่งหนึ่ง เสียเวลา 2 ขั้น) ยืนยันกับผู้ใช้แล้ว:
  //   1. ถ้าลูกค้าคนนี้ไม่มียืมคะแนนค้างคืนอยู่เลย (พิมพ์ชื่อผิด/คืนครบไปแล้ว) — เปิดบิล
  //      ให้ตามปกติ + แจ้งเตือนเฉยๆ ไม่บล็อกการบันทึก
  //   2. ถ้ามียืมค้างมากกว่า 1 รายการพร้อมกัน — ขึ้นปุ่มเลือกเหมือนคำสั่ง "คืนคะแนน"
  //      เดิมทุกอย่าง (ส่ง "คืนคะแนน_เลือก loanId billNo" ตรงๆ ใช้ handlePvRepaymentPick_
  //      ที่มีอยู่แล้วได้เลย ไม่ต้องเขียนใหม่)
  var outstanding = _getOutstandingPvLoans_(state.custId);
  if (outstanding.length === 0) {
    msg += 'ℹ️ คุณ' + state.custName + ' ไม่มีรายการยืมคะแนนค้างคืนอยู่เลยค่ะ — เปิดบิลให้ตามปกติ\n';
    replyMessage(replyToken, msg);
    return;
  }

  var totals = _getBillTotals_(billNo);
  if (outstanding.length === 1) {
    msg += _autoApplyPvRepayment_(outstanding[0], billNo, totals);
    replyMessage(replyToken, msg);
    return;
  }

  // มียืมค้างมากกว่า 1 รายการ — label ปุ่มสั้นแค่ "เลือก N" รายละเอียด (วันที่ยืม+PV ค้าง)
  // อยู่ในเนื้อข้อความด้านบนแทน กัน LINE ตัด label เกิน 20 ตัวอักษรจนข้อมูลสำคัญหายเงียบๆ
  // (บั๊กที่เจอจริงตอนทำคำสั่ง คืนคะแนน แบบ standalone มาก่อนหน้านี้ในเซสชันเดียวกัน)
  var pickLines = outstanding.map(function(l, idx) {
    return (idx + 1) + '. ยืม ' + l.lend_date + ' — ค้าง ' + numFmt_(l.pv_remaining) + ' PV (บิล ' + l.lend_bill_no + ')';
  }).join('\n');
  var pickItems = outstanding.slice(0, 13).map(function(l, idx) {
    return {
      type: 'action',
      action: { type: 'message', label: 'เลือก ' + (idx + 1), text: 'คืนคะแนน_เลือก ' + l.id + ' ' + billNo },
    };
  });
  sendQuickReplyGas(replyToken,
    msg + '🔍 มียืมคะแนนค้างคืน ' + outstanding.length + ' รายการ เลือกว่าจะคืนให้บิลนี้รายการไหนค่ะ:\n' + pickLines,
    pickItems);
}

// ผูก pv_loan_repayments อัตโนมัติ ตอนสั่ง "เปิดบิล_คืนคะแนน" แล้วลูกค้าคนนี้มียืมค้างอยู่
// พอดี 1 รายการ (ไม่ต้องถามเลือก) — ไม่ใช้ร่วมกับ commitPvRepayment_ ของคำสั่ง "ยืนยัน_
// คืนคะแนน" แบบ standalone ตั้งใจแยกไว้ กันแก้โค้ดที่ทดสอบแล้วของฟีเจอร์เดิมโดยไม่จำเป็น
function _autoApplyPvRepayment_(loan, billNo, totals) {
  _sbPost_('pv_loan_repayments', {
    id: Utilities.getUuid(), loan_id: loan.id, repay_date: _todayBkk_(), repay_bill_no: billNo,
    pv_repaid: totals.pv, bv_repaid: totals.bv, baht_repaid: totals.baht,
    notes: 'บันทึกผ่าน LINE Coffee Log (ผูกอัตโนมัติตอนเปิดบิล_คืนคะแนน)',
  });
  var repaidAfter = _getPvLoanRepaidTotals_(loan.id);
  var pvRemaining = Math.max(0, parseFloat(loan.pv_lent) - repaidAfter.pv);
  var msg = '🔗 ผูกบิลนี้เข้ากับยืมคะแนนที่ค้างอยู่ (ยืม ' + loan.lend_date + ', บิล ' + loan.lend_bill_no + ') แล้ว\n';
  if (pvRemaining <= 0) {
    var diffBaht = repaidAfter.baht - parseFloat(loan.baht_lent);
    msg += '🎉 คืนครบแล้ว!\n';
    if (diffBaht < -0.5) msg += '⚠️ ขาดทุน ฿' + numFmt_(Math.abs(diffBaht)) + '\n';
    else if (diffBaht > 0.5) msg += '🎉 ได้คืนเกินมา ฿' + numFmt_(diffBaht) + '\n';
    else msg += '✅ เท่าทุน\n';
  } else {
    msg += '🟡 ยังค้างคืนอีก ' + numFmt_(pvRemaining) + ' PV\n';
  }
  return msg;
}

// ── ───────────────────────────────────────────────────────────────────────────
// ฟังก์ชันสำหรับ "คืนคะแนน" (เพิ่ม 2026-10-18) — คู่กับแท็บ 💳 ยืมคะแนน ของแอป Streamlit
// (pv_loan_ui.py, ตาราง pv_loans/pv_loan_repayments) ผูกบิลจริงที่เปิดแล้วเข้ากับยืม
// คะแนนที่ยังค้างคืนอยู่ — ไม่มี CacheService state เหมือน TBY order-entry ด้านบน เพราะ
// ทุกขั้นส่ง loanId+billNo กลับมาในปุ่มได้ตรงๆ (เหมือนแพทเทิร์น รับคืน/ยืนยัน_รับคืน
// ของพัสดุ Shopee ด้านบน — เรียบง่ายกว่าเก็บ state ไว้)
// ── ───────────────────────────────────────────────────────────────────────────

// คำนวณยอด ฿/PV/BV รวมของบิลที่ "เปิดบิลแล้ว" เลขนี้ (พอร์ตจาก database.py's
// get_bill_totals — BV อยู่แค่ใน products.bv_per_unit ไม่มีคอลัมน์นี้ใน transactions)
function _getBillTotals_(billNo) {
  var rows = _sbGet_('/rest/v1/transactions?bill_no=eq.' + encodeURIComponent(billNo)
    + '&bill_status=eq.' + encodeURIComponent('เปิดบิลแล้ว')
    + '&select=product_id,qty,total_amount,points_per_unit,customer_id') || [];
  if (rows.length === 0) return { baht: 0, pv: 0, bv: 0, found: false, customer_id: null };

  var baht = 0, pv = 0, productIds = [];
  rows.forEach(function(r) {
    baht += parseFloat(r.total_amount || 0);
    pv += parseFloat(r.points_per_unit || 0) * parseFloat(r.qty || 0);
    if (r.product_id && productIds.indexOf(r.product_id) === -1) productIds.push(r.product_id);
  });
  var bvMap = {};
  if (productIds.length > 0) {
    var enc = productIds.map(function(p) { return encodeURIComponent(p); }).join(',');
    var prodRows = _sbGet_('/rest/v1/products?id=in.(' + enc + ')&select=id,bv_per_unit') || [];
    prodRows.forEach(function(p) { bvMap[p.id] = parseFloat(p.bv_per_unit || 0); });
  }
  var bv = 0;
  rows.forEach(function(r) { bv += (bvMap[r.product_id] || 0) * parseFloat(r.qty || 0); });
  return { baht: baht, pv: pv, bv: bv, found: true, customer_id: rows[0].customer_id };
}

function _getPvLoanById_(loanId) {
  var rows = _sbGet_('/rest/v1/pv_loans?id=eq.' + encodeURIComponent(loanId)
    + '&select=id,customer_id,lend_date,lend_bill_no,pv_lent,bv_lent,baht_lent') || [];
  return rows.length > 0 ? rows[0] : null;
}

function _getPvLoanRepaidTotals_(loanId) {
  var rows = _sbGet_('/rest/v1/pv_loan_repayments?loan_id=eq.' + encodeURIComponent(loanId)
    + '&select=pv_repaid,bv_repaid,baht_repaid') || [];
  var pv = 0, bv = 0, baht = 0;
  rows.forEach(function(r) {
    pv += parseFloat(r.pv_repaid || 0); bv += parseFloat(r.bv_repaid || 0); baht += parseFloat(r.baht_repaid || 0);
  });
  return { pv: pv, bv: bv, baht: baht };
}

// loan + pv_remaining คำนวณสด (ใช้ตอนกดเลือกจากเมนู "มียืมค้างหลายรายการ" — ตอนนั้นมีแค่
// loanId+billNo ส่งกลับมา ต้องดึงรายละเอียด loan ใหม่)
function _getLoanWithRemaining_(loanId) {
  var loan = _getPvLoanById_(loanId);
  if (!loan) return null;
  var repaid = _getPvLoanRepaidTotals_(loanId);
  loan.pv_remaining = Math.max(0, parseFloat(loan.pv_lent) - repaid.pv);
  return loan;
}

function _getCustomerNameById_(customerId) {
  var rows = _sbGet_('/rest/v1/customers?id=eq.' + encodeURIComponent(customerId) + '&select=name') || [];
  return rows.length > 0 ? rows[0].name : customerId;
}

// ยืมคะแนนที่ยังค้างคืนของลูกค้าคนนี้ทั้งหมด (pv_repaid สะสม < pv_lent) เรียงเก่าสุดก่อน
function _getOutstandingPvLoans_(customerId) {
  var loans = _sbGet_('/rest/v1/pv_loans?customer_id=eq.' + encodeURIComponent(customerId)
    + '&select=id,lend_date,lend_bill_no,pv_lent,bv_lent,baht_lent&order=lend_date.asc') || [];
  var outstanding = [];
  loans.forEach(function(l) {
    var repaid = _getPvLoanRepaidTotals_(l.id);
    var pvRemaining = Math.max(0, parseFloat(l.pv_lent) - repaid.pv);
    if (pvRemaining > 0.001) {
      l.pv_remaining = pvRemaining;
      outstanding.push(l);
    }
  });
  return outstanding;
}

function buildPvRepayPreview_(loan, totals, custName, billNo) {
  var afterPv = Math.max(0, loan.pv_remaining - totals.pv);
  var msg = '📋 ยืนยันคืนคะแนน: คุณ' + custName + '\n';
  msg += '─────────────────\n';
  msg += 'ยืมไว้: ' + numFmt_(loan.pv_lent) + ' PV (วันที่ ' + loan.lend_date + ', บิล ' + loan.lend_bill_no + ')\n';
  msg += 'ค้างคืนอยู่: ' + numFmt_(loan.pv_remaining) + ' PV\n';
  msg += '─────────────────\n';
  msg += 'บิล ' + billNo + ' นี้: ฿' + numFmt_(totals.baht) + ' | ' + numFmt_(totals.pv) + ' PV | '
    + numFmt_(totals.bv) + ' BV\n';
  msg += '─────────────────\n';
  msg += (afterPv <= 0 ? '✅ คืนครบแล้ว (เหลือ 0 PV)' : '🟡 ยังค้างอีก ' + numFmt_(afterPv) + ' PV') + '\n';
  return msg;
}

function _showPvRepayConfirm_(loan, totals, custName, billNo, replyToken) {
  sendQuickReplyGas(replyToken, buildPvRepayPreview_(loan, totals, custName, billNo), [
    { type: 'action', action: { type: 'message', label: '✅ ยืนยันบันทึก', text: 'ยืนยัน_คืนคะแนน ' + loan.id + ' ' + billNo } },
    { type: 'action', action: { type: 'message', label: '❌ ยกเลิก', text: 'ยกเลิก' } },
  ]);
}

// คืนคะแนน [ชื่อลูกค้า] [bill_no] — จุดเริ่มต้นของคำสั่ง
function handlePvRepayment_(name, billNo, replyToken) {
  var cust = findOneCustomer_(name, replyToken, 'คืนคะแนน {name} ' + billNo);
  if (!cust) return;

  var outstanding = _getOutstandingPvLoans_(cust.id);
  if (outstanding.length === 0) {
    replyMessage(replyToken, '❌ คุณ' + cust.name + ' ไม่มีรายการยืมคะแนนค้างคืนเลยค่ะ');
    return;
  }

  var totals = _getBillTotals_(billNo);
  if (!totals.found) {
    replyMessage(replyToken, '❌ ไม่พบบิล "' + billNo + '" ที่เปิดบิลแล้ว (เช็คว่าพิมพ์เลขบิลถูกไหมค่ะ)');
    return;
  }
  if (totals.customer_id && totals.customer_id !== cust.id) {
    replyMessage(replyToken, '⚠️ บิล "' + billNo + '" ไม่ใช่ของคุณ' + cust.name + ' ค่ะ เช็คเลขบิลอีกทีนะคะ');
    return;
  }

  if (outstanding.length === 1) {
    _showPvRepayConfirm_(outstanding[0], totals, cust.name, billNo, replyToken);
    return;
  }

  // label ของ Quick Reply ของ LINE ยาวได้สูงสุด 20 ตัวอักษร — ใส่รายละเอียดเต็ม (วันที่ยืม
  // + PV ค้าง) ไว้ในเนื้อข้อความด้านบนปุ่มแทน (เหมือน handleListUnreceivedReturns_) แล้วให้
  // label สั้นๆ แค่ "เลือก N" พอกดแยกแต่ละรายการได้ ไม่งั้นข้อความสำคัญ (PV ค้าง) จะถูก
  // ตัดหายไปเงียบๆ (เจอจริงตอนทดสอบ 2026-10-18 — label ยาวเกิน 20 ตัวจนเลขหายไปหมด)
  var lines = outstanding.map(function(l, idx) {
    return (idx + 1) + '. ยืม ' + l.lend_date + ' — ค้าง ' + numFmt_(l.pv_remaining) + ' PV (บิล ' + l.lend_bill_no + ')';
  }).join('\n');
  var items = outstanding.slice(0, 13).map(function(l, idx) {
    return {
      type: 'action',
      action: {
        type: 'message',
        label: 'เลือก ' + (idx + 1),
        text: 'คืนคะแนน_เลือก ' + l.id + ' ' + billNo,
      },
    };
  });
  sendQuickReplyGas(replyToken,
    '🔍 คุณ' + cust.name + ' มียืมคะแนนค้างคืน ' + outstanding.length + ' รายการ เลือกว่าจะคืนให้รายการไหนค่ะ:\n' + lines,
    items);
}

// คืนคะแนน_เลือก [loanId] [bill_no] — เลือกแล้วจากเมนู "มียืมค้างหลายรายการ" ด้านบน
function handlePvRepaymentPick_(loanId, billNo, replyToken) {
  var loan = _getLoanWithRemaining_(loanId);
  if (!loan) { replyMessage(replyToken, '❌ ไม่พบรายการยืมคะแนนนี้แล้ว (อาจถูกลบไปก่อน)'); return; }
  var totals = _getBillTotals_(billNo);
  if (!totals.found) { replyMessage(replyToken, '❌ ไม่พบบิล "' + billNo + '" ที่เปิดบิลแล้ว'); return; }
  var custName = _getCustomerNameById_(loan.customer_id);
  _showPvRepayConfirm_(loan, totals, custName, billNo, replyToken);
}

// ยืนยัน_คืนคะแนน [loanId] [bill_no] — บันทึกจริงลง pv_loan_repayments
function commitPvRepayment_(loanId, billNo, replyToken) {
  var loan = _getPvLoanById_(loanId);
  if (!loan) { replyMessage(replyToken, '❌ ไม่พบรายการยืมคะแนนนี้แล้ว (อาจถูกลบไปก่อน)'); return; }
  var totals = _getBillTotals_(billNo);
  if (!totals.found) { replyMessage(replyToken, '❌ ไม่พบบิล "' + billNo + '" ที่เปิดบิลแล้ว'); return; }

  _sbPost_('pv_loan_repayments', {
    id: Utilities.getUuid(), loan_id: loanId, repay_date: _todayBkk_(), repay_bill_no: billNo,
    pv_repaid: totals.pv, bv_repaid: totals.bv, baht_repaid: totals.baht,
    notes: 'บันทึกผ่าน LINE Coffee Log',
  });

  var repaidAfter = _getPvLoanRepaidTotals_(loanId);
  var pvRemaining = Math.max(0, parseFloat(loan.pv_lent) - repaidAfter.pv);
  var custName = _getCustomerNameById_(loan.customer_id);

  var msg = '✅ บันทึกคืนคะแนนให้คุณ' + custName + ' แล้ว\n';
  msg += 'บิลที่คืน: ' + billNo + ' (฿' + numFmt_(totals.baht) + ' | ' + numFmt_(totals.pv) + ' PV | '
    + numFmt_(totals.bv) + ' BV)\n';
  if (pvRemaining <= 0) {
    var diffBaht = repaidAfter.baht - parseFloat(loan.baht_lent);
    msg += '🎉 คืนครบแล้ว!\n';
    if (diffBaht < -0.5) msg += '⚠️ ขาดทุน ฿' + numFmt_(Math.abs(diffBaht)) + '\n';
    else if (diffBaht > 0.5) msg += '🎉 ได้คืนเกินมา ฿' + numFmt_(diffBaht) + '\n';
    else msg += '✅ เท่าทุน\n';
  } else {
    msg += '🟡 ยังค้างคืนอีก ' + numFmt_(pvRemaining) + ' PV\n';
  }
  replyMessage(replyToken, msg);
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
