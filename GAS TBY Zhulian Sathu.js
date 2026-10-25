// ─────────────────────────────────────────────────────────────────────────────
// ⚙️  Script Properties — วิธีตั้งค่า
//    GAS Editor > ⚙️ Project Settings > Script Properties > Add property:
//      CHANNEL_ACCESS_TOKEN  — LINE OA Channel Access Token (LINE Developers Console)
//      WEBHOOK_TOKEN         — รหัสลับที่คุณสุ่มเอง แล้วต่อท้าย Webhook URL ใน LINE
//                              Developers Console > Messaging API เป็น .../exec?token=<ค่านี้>
//                              (Apps Script อ่าน HTTP header ไม่ได้ เลย verify signature ตรงๆ
//                              ไม่ได้ ใช้ query-param secret แทน — ดูคอมเมนต์ใน doPost())
//      SUPABASE_URL          — https://xxxx.supabase.co
//      SUPABASE_KEY          — anon key จาก Supabase > Settings > API
// ─────────────────────────────────────────────────────────────────────────────

var _scriptProps         = PropertiesService.getScriptProperties();
var CHANNEL_ACCESS_TOKEN = _scriptProps.getProperty('CHANNEL_ACCESS_TOKEN');
var QR_IMAGE_URL         = 'https://i.postimg.cc/x1QKRxsh/E2A8A0F2-2BEA-40A8-805C-49273D6A23D9.jpg';

var SUPABASE_URL = _scriptProps.getProperty('SUPABASE_URL');
var SUPABASE_KEY = _scriptProps.getProperty('SUPABASE_KEY');

// คำสั่งเก่า/เบิก/เบิกจ่าย/จ่าย/check ต้องมี #ชื่อผู้บันทึก ที่อยู่ในลิสต์นี้
// (กันลูกค้าพิมพ์โดนคำสั่งโดยไม่ตั้งใจ — ถ้าไม่มี # ในลิสต์นี้ จะไม่ทำงานเลย)
var STAFF_TAGS = ['milk', 'max'];

// รหัสสินค้าที่ของหมดชั่วคราว — ถ้าลูกค้าพิมพ์รหัสนี้ ไม่คำนวณยอด/PV ให้ (ไม่นับรวม
// totalPrice/PV/น้ำหนักด้วย) ตอบแจ้งว่าสินค้าหมดแทน แก้ลิสต์นี้เองได้เลยเวลาของหมด/
// กลับมาเข้าใหม่ (เพิ่ม/ลบรหัสตรงนี้) — เพิ่ม TU3103 ตามคำขอ 2026-09-25, เอาออกแล้ว
// 2026-10-06 (ของมาแล้ว)
var OUT_OF_STOCK_CODES = [];

// โน้ตพื้นที่ห่างไกล/เกาะ (ตอนคำนวณออเดอร์แต่ยังไม่รู้วิธีส่ง) — ภาษาพม่าล้วน เพราะ
// ลูกค้าส่วนใหญ่เป็นแรงงานพม่า ไม่บอกราคาที่แน่นอน (ค่าธรรมเนียมจริงแตกต่างกันตามโซน
// 30/50/60 บาท) แค่แจ้งว่ามีค่าเพิ่มแล้วจะแจ้งราคาจริงทีหลัง — พอร์ตมาจาก
// record_ui.py's _MM_REMOTE_NOTE ให้ทั้งสองฝั่งใช้ข้อความเดียวกัน
var MM_REMOTE_NOTE =
  'ကျွန်းများ သို့မဟုတ် တောင်တန်းဒေသများအတွက် ပို့ဆောင်ခ 50 ဘတ် ' +
  'ထပ်မံပေးဆောင်ရမည် (ကျွန်ုပ်တို့ အမြန်ဆုံး အကြောင်းကြားပါမည်)။';

// โน้ตแจ้งว่าจัดส่งหลังได้รับสลิปโอนเงิน (ไม่ใช้กับ COD — จ่ายปลายทาง ไม่มีสลิป) — เก็บแยก
// ไทย/พม่า ให้เลือกภาษาเดียวได้เวลาลูกค้าพิมพ์ "th "/"mm " ระบุมาเอง (lang !== 'none' →
// ภาษาเดียวตามที่พิมพ์ ไม่ผสม), ส่วน SHIP_AFTER_SLIP_NOTE (รวมทั้งคู่) ใช้เมื่อ lang==='none'
// เท่านั้น (ไม่รู้ภาษาลูกค้า โชว์ทั้งคู่ไว้ก่อน เหมือน MM_REMOTE_NOTE ด้านบน) — ใช้ร่วมกัน 2
// จุด: กรณีระบุวิธีจัดส่งแล้ว (มี SH) และกรณียังไม่ระบุวิธีจัดส่ง (ราคาคู่ ไม่มี SH) ผ่าน
// _shipAfterSlipNoteFor(lang) กันข้อความสองจุดเพี้ยนไม่ตรงกัน
var SHIP_AFTER_SLIP_NOTE_TH = '📦 หลังจากได้รับสลิปโอนเงิน ทางร้านจะถ่ายรูปสินค้าและหน้ากล่องพัสดุให้ค่ะ 😊';
var SHIP_AFTER_SLIP_NOTE_MM = '📦 ငွေလွှဲပြေစာ ရရှိပြီးနောက် ဆိုင်မှ ပစ္စည်းဓာတ်ပုံနှင့် ပါဆယ်ဘောက်စ်ဓာတ်ပုံများကို ပို့ပေးပါမည် 😊';
var SHIP_AFTER_SLIP_NOTE = SHIP_AFTER_SLIP_NOTE_TH + '\n' + SHIP_AFTER_SLIP_NOTE_MM;
function _shipAfterSlipNoteFor(lang) {
  if (lang === 'th') return SHIP_AFTER_SLIP_NOTE_TH;
  if (lang === 'mm') return SHIP_AFTER_SLIP_NOTE_MM;
  return SHIP_AFTER_SLIP_NOTE;
}

// ─── Supabase REST helpers ────────────────────────────────────────────────────

function _sbReadHdrs() {
  return { 'apikey': SUPABASE_KEY, 'Authorization': 'Bearer ' + SUPABASE_KEY };
}
function _sbWriteHdrs() {
  return { 'apikey': SUPABASE_KEY, 'Authorization': 'Bearer ' + SUPABASE_KEY,
           'Content-Type': 'application/json', 'Prefer': 'return=minimal' };
}
function _sbGet(path) {
  return JSON.parse(UrlFetchApp.fetch(SUPABASE_URL + path,
    { headers: _sbReadHdrs(), muteHttpExceptions: true }).getContentText());
}
function _sbPost(table, data) {
  UrlFetchApp.fetch(SUPABASE_URL + '/rest/v1/' + table,
    { method: 'POST', headers: _sbWriteHdrs(), payload: JSON.stringify(data), muteHttpExceptions: true });
}
function _sbPatch(path, data) {
  UrlFetchApp.fetch(SUPABASE_URL + path,
    { method: 'PATCH', headers: _sbWriteHdrs(), payload: JSON.stringify(data), muteHttpExceptions: true });
}

// ─── Product data (cached per request) ────────────────────────────────────────

var _cachedProducts = null;
function _getProducts() {
  if (_cachedProducts) return _cachedProducts;
  var _raw = _sbGet('/rest/v1/products?select=id,name,name_mm,price,points_per_unit,weight_grams&order=id');
  if (!Array.isArray(_raw)) {
    // โยน error ที่มีเนื้อหาจริงจาก Supabase ติดไปด้วย ดีกว่าเงียบแล้วคืน [] ให้ order พังทีหลัง
    throw new Error('_getProducts non-array response: ' + JSON.stringify(_raw));
  }
  _cachedProducts = _raw.map(function(p) {
    return [p.id, p.name, p.name_mm || '', p.price, p.points_per_unit, (p.weight_grams || 0) / 1000];
  });
  return _cachedProducts;
}

// ─── Carrier zones (โซนพื้นที่พิเศษ/ห่างไกล — query สดจาก Supabase) ─────────────
// เดิมไฟล์นี้ hardcode ลิสต์รหัสไปรษณีย์แยกต่างหากจาก flash_zones.py (แอปหลัก) เอง
// แล้วเคย drift ไม่ตรงกัน (2026-07-12, SPX คำนวณผิดที่ 63150 ท่าสองยาง) ตอนนี้ query
// ตาราง carrier_zones ตรงๆ แทน — ตารางนี้ sync มาจาก flash_zones.py ด้วย
// tools/sync_carrier_zones.py (รันทุกครั้งที่แก้โซนในแอปหลัก) ไม่มีลิสต์ให้ hardcode
// ในไฟล์นี้อีกต่อไป กันไม่ให้ drift ซ้ำได้
var _cachedZones = null;
function _getCarrierZones() {
  if (_cachedZones) return _cachedZones;
  var z = { flashRemote: {}, spxRemote: {}, flashTourist: {}, flashTouristIsland: {} };
  try {
    var rows = _sbGet('/rest/v1/carrier_zones?select=carrier,postcode,zone_type');
    if (Array.isArray(rows)) {
      rows.forEach(function(r) {
        if (r.carrier === 'flash') {
          if (r.zone_type === 'remote') z.flashRemote[r.postcode] = true;
          else if (r.zone_type === 'tourist') z.flashTourist[r.postcode] = true;
          else if (r.zone_type === 'tourist_island') z.flashTouristIsland[r.postcode] = true;
        } else if (r.carrier === 'spx' && r.zone_type === 'remote') {
          z.spxRemote[r.postcode] = true;
        }
      });
      z.ok = true;
    } else {
      z.ok = false;
    }
  } catch (err) {
    z.ok = false; // เน็ต/ตารางมีปัญหา — เดินหน้าคำนวณต่อแบบไม่มีค่าพื้นที่พิเศษ ดีกว่าล้ม
    // ทั้งคำสั่งซื้อ แต่ feeNote จะเตือนไว้ว่าเช็คโซนไม่ได้ (ดูจุดที่ใช้ z.ok ด้านล่าง)
  }
  _cachedZones = z;
  return _cachedZones;
}

// ─── doPost ──────────────────────────────────────────────────────────────────

function doPost(e) {
  try {
  // ── Webhook auth: query-param shared secret ────────────────────────────────
  // Apps Script's doPost(e) ไม่ส่ง HTTP headers มาให้เลย (ไม่มี e.headers) เลย verify
  // X-Line-Signature ตามมาตรฐานไม่ได้บนแพลตฟอร์มนี้ (เคยลองแล้วทำให้ทุก request โดน
  // return ทิ้งหมด บอทเงียบสนิม — 2026-07-12) ใช้วิธีนี้แทน: LINE POST ไปที่ URL ตรงๆ
  // ตามที่ตั้งไว้ใน Messaging API เสมอ ต่อท้าย query param ใน Webhook URL ได้ปกติ
  // และ e.parameter อ่านได้ (ต่างจาก header) — ตั้ง Script Property WEBHOOK_TOKEN
  // แล้วตั้ง Webhook URL ใน LINE Developers Console เป็น .../exec?token=<ค่าเดียวกัน>
  var _webhookToken = _scriptProps.getProperty('WEBHOOK_TOKEN');
  var _tokenOk = 'n/a';
  if (_webhookToken) {
    _tokenOk = (e.parameter && e.parameter.token === _webhookToken);
    if (!_tokenOk) return;
  }
  // ─────────────────────────────────────────────────────────────────────────

  var contents = JSON.parse(e.postData.contents);
  var event = contents.events[0];

  // ── กันประมวลผลซ้ำ: LINE จะส่ง event เดิมซ้ำถ้า GAS ตอบกลับช้า ──────────────
  var eventId = event.webhookEventId || (event.message && event.message.id);
  if (eventId) {
    var cache = CacheService.getScriptCache();
    if (cache.get('evt_' + eventId)) return; // เคยประมวลผลแล้ว ข้ามรอบนี้
    cache.put('evt_' + eventId, '1', 600); // จำไว้ 10 นาที
  }

  if (event.type !== 'message' || event.message.type !== 'text') return;

  var replyToken = event.replyToken;
  var rawMsg = event.message.text.trim();

  // ── ลงทะเบียน ──────────────────────────────────────────────────────────────
  if (/^สมัคร\s+\d{9,10}/.test(rawMsg)) {
    var phone = rawMsg.replace(/^สมัคร\s+/, '').trim();
    registerLineUser(event.source.userId, phone, replyToken);
    return;
  }

  // ── ยอดส่วนตัว (ลูกค้าพิมพ์เอง) ──────────────────────────────────────────
  if (rawMsg === 'ยอด' || rawMsg === 'สรุปยอด') {
    sendCustomerSummary(event.source.userId, replyToken);
    return;
  }

  // ── "ยกเลิก" — จากปุ่ม "❌ ยกเลิก" หลังเมนูยืนยันต่างๆ ────────────────────
  if (rawMsg === 'ยกเลิก') {
    sendReply(replyToken, '❌ ยกเลิกแล้วค่ะ ยังไม่มีการบันทึกข้อมูล');
    return;
  }

  // ── คำสั่งบันทึกข้อมูล (เบิก/เบิกจ่าย/check) ───────────────────────────────
  // "เก่า"/"จ่าย" (รับของเก่า/เก็บเงินค้างจ่าย) ย้ายไปทำที่ GAS TBY Smart Bot.js
  // แทนแล้ว (ตัดสินใจ 2026-10-18 — OA นั้นใช้ภายในอยู่แล้ว ไม่ต้องมี #staffTag นำหน้า
  // แบบนี้ และ UX แบบกดปุ่มเลือกบิล/สินค้าเข้ากับ OA นั้นได้ดีกว่า) ดูที่ไฟล์นั้น
  // ต้องมี #milk หรือ #max ในประโยคก่อนจึงจะทำงาน ถ้าไม่มี ปล่อยข้อความไว้เฉยๆ
  var _msg = rawMsg;
  // "ยืนยัน ..." — ขั้นยืนยันบันทึกจริง (มาจากปุ่ม "✅ ยืนยันบันทึก")
  var _confirmed = false;
  if (/^ยืนยัน\s+/.test(_msg)) {
    _confirmed = true;
    _msg = _msg.replace(/^ยืนยัน\s+/, '');
  }

  // #ชื่อผู้บันทึก เช่น #milk #max
  var _staffTag = '';
  var _tagMatch = _msg.match(/#(\S+)/);
  if (_tagMatch) {
    _staffTag = _tagMatch[1];
    _msg = _msg.replace(_tagMatch[0], ' ').replace(/\s+/g, ' ').trim();
  }

  if (_staffTag && STAFF_TAGS.indexOf(_staffTag.toLowerCase()) !== -1) {
    // check [name]
    var _chk = _msg.match(/^check\s+(.+)$/i);
    // [name] เบิก CODE-QTY [CODE-QTY ...] — บันทึกรับของ ไม่จ่ายเงิน (หลายรายการได้)
    var _withdraw = _msg.match(/^(.+?)\s+เบิก\s+([A-Za-z0-9]+-\d+(?:\s+[A-Za-z0-9]+-\d+)*)$/);
    // [name] เบิกจ่าย CODE-QTY [CODE-QTY ...] — บันทึกรับของ + จ่ายเงินแล้ว ยังไม่เปิดบิล (หลายรายการได้)
    var _withdrawPaid = _msg.match(/^(.+?)\s+เบิกจ่าย\s+([A-Za-z0-9]+-\d+(?:\s+[A-Za-z0-9]+-\d+)*)$/);
    // [name] เบิกจ่าย CODE-QTY [CODE-QTY ...] จ่าย AMOUNT — บันทึกรับของ + จ่ายเงินบางส่วน (ไม่ครบยอด)
    var _withdrawPartialPay = _msg.match(/^(.+?)\s+เบิกจ่าย\s+([A-Za-z0-9]+-\d+(?:\s+[A-Za-z0-9]+-\d+)*)\s+จ่าย\s+(\d+(?:\.\d+)?)$/);
    // ads/bv/scb/po วันที่ ค่า... — บันทึกยอดการเงินรายวัน (finance_daily) จาก LINE
    // โดยตรง ไม่ต้องเข้าแอป ทับยอดเดิมของฟิลด์นั้นทั้งหมด (ไม่ใช่บวกเพิ่ม — ยืนยันกับ
    // ผู้ใช้แล้ว 2026-08-20 เพราะพิมพ์ทับผิดจะแก้ตามได้ง่ายกว่าบวกซ้ำแล้วงงว่าทำไมเกิน)
    var _finAds = _msg.match(/^ads\s+(\S+)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)$/i);
    var _finBv  = _msg.match(/^bv\s+(\S+)\s+(\d+(?:\.\d+)?)$/i);
    var _finScb = _msg.match(/^scb\s+(\S+)\s+(\d+(?:\.\d+)?)$/i);
    var _finPo  = _msg.match(/^po\s+(\S+)\s+(\d+(?:\.\d+)?)$/i);

    if (_msg.toLowerCase() === 'คู่มือ' || _msg.toLowerCase() === 'help') { handleManual(replyToken, _staffTag); return; }
    if (_finAds) { handleFinanceEntry('ads', _finAds[1], [parseFloat(_finAds[2]), parseFloat(_finAds[3])], replyToken, _confirmed, _staffTag); return; }
    if (_finBv)  { handleFinanceEntry('bv',  _finBv[1],  [parseFloat(_finBv[2])],  replyToken, _confirmed, _staffTag); return; }
    if (_finScb) { handleFinanceEntry('scb', _finScb[1], [parseFloat(_finScb[2])], replyToken, _confirmed, _staffTag); return; }
    if (_finPo)  { handleFinanceEntry('po',  _finPo[1],  [parseFloat(_finPo[2])],  replyToken, _confirmed, _staffTag); return; }
    if (_msg.toLowerCase().startsWith('groupid')) {
      var _gid = (event.source || {}).groupId || '';
      if (!_gid) { sendReply(replyToken, '❌ ใช้คำสั่งนี้ในกลุ่มเท่านั้น'); return; }
      var _gCustName = _msg.replace(/^groupid\s*/i, '').trim();
      if (!_gCustName) {
        sendReply(replyToken, '🔑 Group ID:\n' + _gid + '\n\nถ้าจะผูกกับลูกค้า พิมพ์:\n#' + _staffTag + ' groupid [ชื่อลูกค้า]');
        return;
      }
      var _gCust = findOneCustomer(_gCustName, replyToken, '#' + _staffTag + ' groupid {name}');
      if (!_gCust) return;
      _sbPatch('/rest/v1/customers?id=eq.' + _gCust.id, { group_id: _gid });
      sendReply(replyToken, '✅ ผูกกลุ่มนี้กับคุณ' + _gCust.name + ' แล้ว\nเวลาแจ้งเตือนจะส่งเข้ากลุ่มนี้ค่ะ');
      return;
    }
    if (_msg.toLowerCase() === 'check') { handleCheckMenu(replyToken); return; }
    if (_chk) {
      var _chkArg = _chk[1].trim();
      // check today / check วันนี้ — สิทธิ์สั่งของคงเหลือ ไม่ใช่ชื่อลูกค้า
      if (_chkArg.toLowerCase() === 'today' || _chkArg === 'วันนี้') { handleFinanceCredit(replyToken); return; }
      handleCustomerByName(_chkArg, replyToken);
      return;
    }

    if (_withdraw) {
      var _items = _withdraw[2].trim().split(/\s+/).map(function(tok) {
        var p = tok.split('-');
        return { code: p[0].toUpperCase(), qty: parseInt(p[1]) };
      });
      handleWithdraw(_withdraw[1].trim(), _items, replyToken, _confirmed, _staffTag);
      return;
    }
    if (_withdrawPartialPay) {
      var _itemsPartial = _withdrawPartialPay[2].trim().split(/\s+/).map(function(tok) {
        var p = tok.split('-');
        return { code: p[0].toUpperCase(), qty: parseInt(p[1]) };
      });
      handleWithdrawPartialPay(_withdrawPartialPay[1].trim(), _itemsPartial, parseFloat(_withdrawPartialPay[3]), replyToken, _confirmed, _staffTag);
      return;
    }
    if (_withdrawPaid) {
      var _itemsPaid = _withdrawPaid[2].trim().split(/\s+/).map(function(tok) {
        var p = tok.split('-');
        return { code: p[0].toUpperCase(), qty: parseInt(p[1]) };
      });
      handleWithdrawPaid(_withdrawPaid[1].trim(), _itemsPaid, replyToken, _confirmed, _staffTag);
      return;
    }
  }

  // ── แปลพม่า ────────────────────────────────────────────────────────────────
  var translatedNote = '';
  if (/[က-အ]/.test(rawMsg)) {
    try { var det = LanguageApp.translate(rawMsg, 'my', 'th'); translatedNote = '\n\n🔍 [แปลไทย]: ' + det; } catch(err) {}
  }

  if (rawMsg.toLowerCase() === 'qr') {
    sendReply(replyToken, '🏦 รายละเอียดการชำระเงิน\nSCB 165-2716485\nZhulian Sathupradit New Agency', QR_IMAGE_URL);
    return;
  }

  // ── คำนวณออเดอร์ ────────────────────────────────────────────────────────────
  // โซนพื้นที่พิเศษ/ห่างไกล — query สดจาก Supabase (carrier_zones, sync มาจาก
  // flash_zones.py) แทนลิสต์ hardcode เดิมที่เคย drift ไม่ตรงกัน (2026-07-12)
  // ดูฟังก์ชัน _getCarrierZones() ด้านบน. หมายเหตุ: บางรหัส (81120,81150,81210,
  // 84280,84360) เป็น "SPX ห่างไกล" ซ้อนกับ "Flash ท่องเที่ยว/เกาะ" พร้อมกัน —
  // โค้ดด้านล่างเช็ค remote ก่อน tourist เสมอ ทำให้เคสเหล่านี้ได้ค่า remote +50
  // แม้จะจบที่ Flash (ซึ่งจริงๆ ควรได้ค่าท่องเที่ยวแบบขั้นบันไดแทน) เป็นข้อจำกัด
  // เดิมของโมเดลนี้ที่ไม่รู้ล่วงหน้าว่าจะจบที่ขนส่งไหน ยังไม่แก้ในรอบนี้
  var _zones = _getCarrierZones();

  var lang = 'none', isCOD = rawMsg.toLowerCase().includes('cod'), userMsg = rawMsg.toLowerCase();
  if (userMsg.startsWith('th ')) { lang = 'th'; userMsg = userMsg.replace('th ', '').trim(); }
  else if (userMsg.startsWith('mm ')) { lang = 'mm'; userMsg = userMsg.replace('mm ', '').trim(); }

  // cod1000 — ลูกค้าจะยื่นเงินสดแบงก์ 1000 ให้คนส่งของ ไม่ใช่ยอดที่ต้องเก็บจริง (ยอดเก็บจริง
  // คือ finalPay คำนวณด้านล่าง) ต้องรู้ว่าต้องทอนลูกค้าเท่าไหร่ — เลขติดกับคำว่า cod ได้เลย
  // ไม่ต้องมีขีด/เว้นวรรค ตามตัวอย่างที่ลูกค้าพิมพ์จริง เช่น "TY2006-1 sh cod1000" (เพิ่ม
  // 2026-10-18 ตามคำขอ) ดึงจาก rawMsg ตรงๆ ก่อนเข้า tokenizer/normalize รหัสสินค้า — ไม่ชน
  // กับ regex normalize รหัสสินค้า typo ด้านล่าง เพราะ "cod" ไม่มีตัวเลข 4 หลัก+จำนวนต่อท้าย
  // ให้ตรงรูปแบบนั้น
  var _codCashMatch = rawMsg.toLowerCase().match(/\bcod[\s-]*(\d+(?:\.\d+)?)\b/);
  var codCashGiven = _codCashMatch ? parseFloat(_codCashMatch[1]) : -1;

  // ลูกค้าพิมพ์รหัสสินค้าเองมักไม่ตรงรูปแบบ CODE-QTY มาตรฐาน — เจอจริงเช่น "ty -2010=1"
  // (เว้นวรรค+ขีดนำหน้าเลข), "tf--2581=1" (ขีดคู่ + ใช้ = คั่นจำนวนแทน -), "tu..2315.2"/
  // "tu.3601.1" (จุดแทนขีด ทั้งคั่นหน้าเลขและคั่นจำนวน บางทีจุดคู่), "tf2581 2" (เว้นวรรค
  // ล้วนๆ ไม่มีสัญลักษณ์เลย ทั้งหน้าเลขและหน้าจำนวน), "t f 2581 . 1" (เว้นวรรคแทรกกลาง
  // ตัวอักษรนำหน้าด้วย — เจอจริง 2026-08-29 เดิม parse เพี้ยนเป็น "F2581" ที่ไม่มีในระบบ
  // แล้วบอทเงียบไม่ตอบอะไรเลย) — normalize เป็น "ty2010-1"/"tf2581-1"/"tu2315-2"/
  // "tu3601-1"/"tf2581-2" ก่อน tokenize เสมอ เพราะรหัสสินค้าจริงเป็น LETTERS+4DIGITS
  // ล้วน ไม่มีขีด/จุด/เว้นวรรคคั่นเอง (พอร์ตมาจาก calc_logic._normalize_customer_codes
  // ในแอป Streamlit ให้ทั้งสองฝั่งอ่านรหัสแบบเดียวกัน) เลข 4 หลักเป๊ะกันชนกับรหัส
  // ไปรษณีย์ 5 หลักใน SH-kgXXXXX และเบอร์โทรลูกค้า (ไม่มีตัวอักษรนำหน้า) โดยไม่ตั้งใจ —
  // ตัวคั่นก่อนจำนวนยอมรับทั้ง .-= อย่างน้อย 1 ตัว หรือเว้นวรรคล้วนๆ ก็ได้ ตัวอักษรนำหน้า
  // เว้นวรรคคั่นแต่ละตัวได้เช่นกัน (สูงสุด 4 ตัว) แล้วเอาช่องว่างออกก่อนต่อกลับเป็นรหัส
  userMsg = userMsg.replace(/([a-z](?:\s?[a-z]){0,3})\s*[-.]{0,2}\s*(\d{4})(?:\s*[-.=]{1,2}\s*|\s+)(\d+(?:\.\d+)?)/g,
    function (_, prefix, num, qty) { return prefix.replace(/\s/g, '') + num + '-' + qty; });

  var pData = _getProducts();
  var tokens = userMsg.split(/[\s\n]+/);

  var orderMap = {}, manualShipPrice = -1, isAutoShip = false, targetZip = '';
  for (var ti = 0; ti < tokens.length; ti++) {
    var token = tokens[ti];

    // คำนวณค่าส่งแบบชั่งน้ำหนัก (auto) — ตัดคำว่า "kg" ออกแล้ว รองรับ "SH12170"
    // (ติดกัน), "SH-12170" (มีขีด), "SH 12170" (เว้นวรรค), และของเดิม
    // "SH-kg12170"/"SH-kg 12170" (ยังรองรับไว้เผื่อลูกค้าเคยชิน) — รหัสไปรษณีย์ไทย
    // มี 5 หลักเสมอ จึงใช้ความยาว 5 หลักแยกจากค่าส่งกำหนดเอง (เช่น SH-5000 ด้านล่าง)
    var shZipMatch = /^SH-?(?:KG)?(\d{5})?$/i.exec(token);
    if (shZipMatch) {
      isAutoShip = true;
      var z = shZipMatch[1];
      if (!z && ti + 1 < tokens.length && /^\d{5}$/.test(tokens[ti + 1])) {
        z = tokens[ti + 1];
        ti++;
      }
      if (z) targetZip = z;
      continue;
    }

    if (token.includes('-')) {
      var parts = token.split('-'), code = parts[0].trim().toUpperCase(), val = parts[1].trim();
      if (code === 'SH') {
        // กำหนดค่าส่งเอง เช่น "SH-5000" — ค่าที่ไม่ใช่รหัสไปรษณีย์ 5 หลัก (เช็คแล้วด้านบน)
        manualShipPrice = parseFloat(val) || 0;
      } else if (/[A-Z]/.test(code)) {
        // รหัสสินค้าจริงเป็น LETTERS+4DIGITS เสมอ — code ที่ไม่มีตัวอักษรเลยไม่ใช่รหัส
        // สินค้าแน่ๆ เจอจริง 2026-08-29: พิมพ์ "3900-5.5=21450" (ราคา-จำนวน=ยอดรวม คำนวณ
        // เองให้ลูกค้าดู) บังเอิญมีขีดคั่นเหมือน CODE-QTY พอดี ทำให้ "3900" ถูกเข้าใจผิดเป็น
        // รหัสสินค้าที่หาไม่เจอ แล้วบอทตอบ "ไม่พบรหัสสินค้า" ให้งงเปล่าๆ — ข้ามเงียบๆ แทน
        orderMap[code] = (orderMap[code] || 0) + (parseFloat(val) || 0);
      }
    }
  }

  var totalPrice = 0, totalPV = 0, productWeight = 0, stockPool = [], detailText = '', outOfStockNote = '';
  Object.keys(orderMap).forEach(function(code) {
    if (OUT_OF_STOCK_CODES.indexOf(code) !== -1) {
      // ของหมด — ไม่นับเข้า totalPrice/PV/น้ำหนักเลย แค่แจ้งแยกไว้ต่างหาก ขึ้นทั้งไทย+พม่า
      // เสมอไม่ว่า lang จะเป็นอะไร (เหมือน MM_REMOTE_NOTE — ลูกค้าส่วนใหญ่เป็นแรงงานพม่า
      // แต่ไม่ค่อยพิมพ์ "mm " นำหน้าเอง พึ่ง lang==='mm' อย่างเดียวจะไม่ถึงคนส่วนใหญ่)
      outOfStockNote += '⚠️ [' + code + '] สินค้าหมด / ပစ္စည်းကုန်ပါပြီ\n';
      return;
    }
    for (var i = 0; i < pData.length; i++) {
      if (pData[i][0].toString().toUpperCase() == code) {
        var qty = orderMap[code], pPrice = pData[i][3], pPV = pData[i][4], pW = pData[i][5];
        totalPrice += pPrice * qty; totalPV += pPV * qty; productWeight += pW * qty;
        if (lang === 'th')
          detailText += '📦 [' + code + '] ' + pData[i][1] + '\n      ' + qty + ' ชิ้น x ฿' + pPrice.toLocaleString() + ' = ฿' + (pPrice * qty).toLocaleString() + '\n';
        else if (lang === 'mm')
          detailText += '📦 [' + code + '] ' + pData[i][2] + '\n      ' + qty + ' ခု x ฿' + pPrice.toLocaleString() + ' = ฿' + (pPrice * qty).toLocaleString() + '\n';
        else
          detailText += '📦 [' + code + '] - ' + qty + ' * ' + pPrice.toLocaleString() + ' = ' + (pPrice * qty).toLocaleString() + '\n';
        for (var n = 0; n < qty; n++) { stockPool.push({ code: code, pv: pPV }); }
        break;
      }
    }
  });

  if (detailText === '' && outOfStockNote !== '') {
    // พิมพ์แต่รหัสของหมด ไม่มีรหัสอื่นที่คำนวณได้เลย — ตอบแค่แจ้งของหมด ไม่ต้องสรุปยอด
    sendReply(replyToken, outOfStockNote.trim() + translatedNote);
    return;
  }
  if (detailText === '' && translatedNote !== '') { sendReply(replyToken, '🇲🇲 Message:\n' + rawMsg + translatedNote); return; }
  else if (detailText === '') {
    // หารหัสสินค้าไม่เจอสักตัว (หรือไม่มีการพิมพ์รหัสแบบ CODE-QTY เลย) — ไม่ต้องตอบกลับ
    // อะไรเลย (ยืนยันจากผู้ใช้ 2026-09-01 ให้เงียบเสมอ แม้พิมพ์รหัสชัดเจนแต่หาไม่เจอ)
    return;
  }

  var totalWeightKg = productWeight + 0.5;
  var summaryHeader = lang === 'th' ? '📜 สรุปยอดคำสั่งซื้อ\n\n' : (lang === 'mm' ? '📜 အော်ဒါအကျဉ်းချုပ်\n\n' : '📝 รายการสินค้า\n\n');
  var summaryText = summaryHeader + detailText + (outOfStockNote ? '\n' + outOfStockNote : '') + '\n';

  var planMatches = rawMsg.toLowerCase().match(/plan\s+([\d\*\s]+)/);
  if (planMatches && lang === 'none') {
    var planList = [];
    planMatches[1].trim().split(/\s+/).forEach(function(p) {
      var bits = p.split('*'); var targetPv = parseInt(bits[0]), count = parseInt(bits[1] || 1);
      for (var c = 0; c < count; c++) planList.push(targetPv);
    });
    planList.sort(function(a, b) { return b - a; });
    summaryText += '📋 แผนจัดบิลผสม:\n';
    planList.forEach(function(target, idx) {
      if (stockPool.length === 0) return;
      var bestSum = 0, bestIndices = [], minDiff = 9999;
      for (var t = 0; t < 1000; t++) {
        var tempSum = 0, tempIndices = [], shuffled = stockPool.map(function(v, i) { return {v: v, i: i}; }).sort(function() { return Math.random() - 0.5; });
        for (var s = 0; s < shuffled.length; s++) {
          if (tempSum + shuffled[s].v.pv <= target + 25) {
            tempSum += shuffled[s].v.pv; tempIndices.push(shuffled[s].i);
            var d = Math.abs(target - tempSum);
            if (d < minDiff) { minDiff = d; bestSum = tempSum; bestIndices = tempIndices.slice(); }
            if (tempSum >= target) break;
          }
        }
      }
      if (bestIndices.length > 0) {
        var billGroup = {};
        bestIndices.sort(function(a, b) { return b - a; }).forEach(function(ii) { var itm = stockPool.splice(ii, 1)[0]; billGroup[itm.code] = (billGroup[itm.code] || 0) + 1; });
        summaryText += '🎯 บิล ' + (idx + 1) + ' (PLAN ' + target + '): ' + Object.keys(billGroup).map(function(k) { return k + '-' + billGroup[k]; }).join(', ') + ' (' + bestSum + ' PV)\n';
      }
    });
    if (stockPool.length > 0) {
      var remainGroup = {}, remainTotalPv = 0;
      stockPool.forEach(function(itm) { remainGroup[itm.code] = (remainGroup[itm.code] || 0) + 1; remainTotalPv += itm.pv; });
      summaryText += '♻️ สินค้าที่ยังไม่เปิดบิล: ' + Object.keys(remainGroup).map(function(k) { return k + '-' + remainGroup[k]; }).join(', ') + ' (รวม ' + remainTotalPv.toLocaleString() + ' PV)\n';
    }
    summaryText += '\n';
  }

  var shipFinal = 0, feeNote = '', hasShipping = false;
  if (isAutoShip) {
    hasShipping = true;
    var shipBase = 39 + (totalWeightKg > 5 ? Math.ceil(totalWeightKg - 5) * 10 : 0);
    var extra = 0;
    if (targetZip !== '') {
      var inFlashRemote = !!_zones.flashRemote[targetZip];
      var inSpxRemote   = !!_zones.spxRemote[targetZip];
      if (inFlashRemote && inSpxRemote) { extra = 50; feeNote = ' (ห่างไกล ' + targetZip + ' [Flash+SPX] +50)'; }
      else if (inFlashRemote) { extra = 50; feeNote = ' (ห่างไกล ' + targetZip + ' [Flash] +50)'; }
      else if (inSpxRemote) { extra = 50; feeNote = ' (ห่างไกล ' + targetZip + ' [SPX] +50)'; }
      else if (_zones.flashTouristIsland[targetZip]) { extra = totalWeightKg <= 7 ? 60 : (totalWeightKg <= 20 ? 130 : 230); feeNote = ' (ท่องเที่ยว+เกาะ ' + targetZip + ' [SPX] +' + extra + ')'; }
      else if (_zones.flashTourist[targetZip]) { extra = totalWeightKg <= 7 ? 30 : (totalWeightKg <= 20 ? 100 : 200); feeNote = ' (ท่องเที่ยว ' + targetZip + ' [SPX] +' + extra + ')'; }
      if (!_zones.ok) feeNote += ' ⚠️เช็คโซนพื้นที่ไม่ได้ตอนนี้ อาจไม่รวมค่าพื้นที่พิเศษ';
    }
    shipFinal = shipBase + extra;
  } else if (manualShipPrice !== -1) { hasShipping = true; shipFinal = manualShipPrice; feeNote = ' (ระบุเอง)'; }

  // เมื่อพิมพ์เลขติดกับ cod (เช่น cod1000) หมายถึง "ยอดเก็บปลายทางที่กำหนดเอง" (เลขกลมๆ
  // ให้ง่ายต่อการจ่าย) ไม่ใช่เงินที่ลูกค้าจะยื่นมาแล้วรอทอนจากยอดที่คำนวณได้ — ค่าธรรมเนียม
  // COD ต้องคิดจากยอดเก็บจริงนี้ (ไม่ใช่จากสินค้า+ค่าส่ง) แล้วส่วนที่เหลือหลังหักค่าธรรมเนียม+
  // ค่าส่ง+สินค้า คือเงินที่ต้องทอนคืนลูกค้า (แก้สูตรตามที่ผู้ใช้ชี้ 2026-10-18 — เดิมเข้าใจผิด
  // ว่าเลขนี้คือเงินสดที่ลูกค้ายื่นมาต่างหาก)
  var codFee = isCOD ? Math.ceil(((isCOD && codCashGiven >= 0) ? codCashGiven : (totalPrice + shipFinal)) * 0.0321) : 0;
  var finalPay = (isCOD && codCashGiven >= 0) ? codCashGiven : (totalPrice + shipFinal + codFee);
  var codChange = (isCOD && codCashGiven >= 0) ? (codCashGiven - codFee - shipFinal - totalPrice) : null;

  summaryText += '✨ ' + totalPV.toLocaleString() + ' PV | ⚖️ ' + totalWeightKg.toFixed(2) + ' kg\n\n';

  // ข้อความบับเบิลที่ 2 แยกจากสรุปยอด — ใช้เฉพาะกรณีลูกค้ายังไม่ระบุวิธีจัดส่ง (ไม่มี SH/ไม่ใช่
  // COD) ตามที่ยืนยันกับผู้ใช้: กรณีนี้แยกเป็น 2 บับเบิล ส่วนกรณีมี SH (ระบุจัดส่งแล้ว) ยังคงรวม
  // เป็นข้อความเดียวเหมือนเดิม ไม่แยก
  var extraBubble = '';

  if (!hasShipping && !isCOD) {
    // ลูกค้ายังไม่บอกว่ารับหน้าร้านหรือจัดส่ง (ไม่มี SH/ไม่ใช่ COD) — โชว์ราคาทั้ง 2
    // แบบในข้อความเดียว แทนที่จะบอกแค่ "ยังไม่รวมค่าจัดส่ง" เฉยๆ (พอร์ตจาก
    // record_ui.py's คำนวณยอด Streamlit ให้บอทกับแอปตอบลูกค้าตรงกัน) shipBase คือ
    // ค่าส่งประมาณตามน้ำหนักล้วน ไม่รวมค่าพื้นที่พิเศษ (ยังไม่รู้รหัสไปรษณีย์จริง)
    var shipBaseEstimate = 39 + (totalWeightKg > 5 ? Math.ceil(totalWeightKg - 5) * 10 : 0);
    var deliverEst = totalPrice + shipBaseEstimate;
    summaryText += (lang === 'mm' ? '💵 ပစ္စည်းဖိုး (ဆိုင်မှာ လာယူပါ): ฿' : '💵 สินค้า (ဆိုင်မှာ လာယူပါ): ฿') + totalPrice.toLocaleString() + '\n';
    summaryText += (lang === 'mm' ? '🚚📦 ပို့ဆောင်မှု (စံပို့ဆောင်မှု): +' : '🚚📦 จัดส่ง (စံပို့ဆောင်မှု): +') + shipBaseEstimate + ' = ฿' + deliverEst.toLocaleString() + '\n';
    summaryText += '\n' + MM_REMOTE_NOTE;

    // เรียงบัญชีธนาคารก่อน แล้วค่อยโน้ตจัดส่งหลังสลิปตามหลัง (ตามที่ผู้ใช้ขอ) — บัญชีธนาคาร
    // โชว์เสมอไม่ว่า lang จะเป็นอะไร (2026-09-25 ผู้ใช้ขอเพิ่มให้กรณี lang==='none' ด้วย
    // จากเดิมที่กันไว้เฉพาะ lang!=='none') ส่วนโน้ตข้อความยังใช้ภาษาเดียวตามที่พิมพ์
    // (th/mm) หรือทั้งคู่ถ้าไม่ระบุ (lang==='none') ผ่าน _shipAfterSlipNoteFor เหมือนเดิม
    extraBubble += '🏦 SCB 165-2716485\n👤 Zhulian Sathupradit New Agency\n\n';
    extraBubble += _shipAfterSlipNoteFor(lang);
  } else {
    summaryText += (lang === 'mm' ? '💵 ပစ္စည်းဖိုး: ฿' : '💵 สินค้า: ฿') + totalPrice.toLocaleString() + '\n';
    if (hasShipping) summaryText += (lang === 'mm' ? '🚚 ပို့ခ: ฿' : '🚚 ค่าส่ง: ฿') + shipFinal.toLocaleString() + feeNote + '\n';

    if (codChange !== null) {
      // cod1000 (ยอดเก็บปลายทางกำหนดเอง) — ดูคอมเมนต์ที่ codFee/finalPay ด้านบน
      summaryText += (lang === 'mm' ? '💰 ကောက်ခံမည့်ငွေ (သတ်မှတ်ထား): ฿' : '💰 ยอดเก็บปลายทาง (กำหนดเอง): ฿') + codCashGiven.toLocaleString() + '\n';
      summaryText += (lang === 'mm' ? '➕ COD ကြေး 3.21%: ฿' : '➕ ค่าธรรมเนียม COD 3.21%: ฿') + codFee.toLocaleString() + '\n';
      summaryText += '\n' + codCashGiven.toLocaleString() + ' - ' + codFee + ' - ' + shipFinal + ' - ' + totalPrice + ' = ' + codChange.toLocaleString() + '\n';
      if (codChange >= 0) {
        summaryText += (lang === 'mm' ? '🔄 ပြန်ပေးရငွေ: ฿' : '🔄 ทอนลูกค้า: ฿') + codChange.toLocaleString() + '\n';
      } else {
        summaryText += (lang === 'mm' ? '⚠️ ကောက်ခံမည့်ငွေ မလုံလောက်ပါ လိုသေးသည်: ฿' : '⚠️ ยอดเก็บปลายทางที่กำหนดไม่พอ ขาดอีก: ฿') + Math.abs(codChange).toLocaleString() + '\n';
      }
    } else {
      if (isCOD) summaryText += '➕ COD: ฿' + codFee.toLocaleString() + '\n';
      var calcFormula = totalPrice.toString();
      if (shipFinal > 0) calcFormula += ' + ' + shipFinal;
      if (codFee > 0) calcFormula += ' + ' + codFee;
      summaryText += '\n' + calcFormula + ' = ' + finalPay.toLocaleString() + '\n';
      summaryText += '💰 ' + (isCOD ? (lang === 'mm' ? 'ပစ္စည်းရောက်ငွေချေ: ' : 'ยอดปลายทาง: ') : (lang === 'mm' ? 'စုစုပေါင်းကျသင့်ငွေ: ' : 'ยอดโอนสุทธิ: ')) + '฿' + finalPay.toLocaleString() + '\n';
    }

    // กรณีมี SH (ระบุจัดส่งแล้ว) ไม่ใช่ COD: lang==='none' (ไม่ระบุภาษา) → จบแค่ยอดโอนสุทธิ
    // เฉยๆ ไม่ต่อท้ายอะไร (ยืนยันกับผู้ใช้แล้ว) แต่ถ้าพิมพ์ "th "/"mm " ระบุภาษามาเอง → โชว์
    // บัญชีธนาคาร + โน้ตจัดส่งหลังสลิปภาษาเดียวตามที่พิมพ์ (ไม่ผสมสองภาษา ต่างจากกรณีไม่มี SH
    // ที่ lang==='none' ยังโชว์ทั้งคู่ไว้เป็นบับเบิลที่ 2)
    if (!hasShipping) summaryText += '\nပို့ဆောင်ခ သီးသန့်ဖြစ်သည်။\nราคานี้ยังไม่รวมค่าจัดส่ง';
    else if (!isCOD && lang !== 'none') {
      summaryText += '\n🏦 SCB 165-2716485\n👤 Zhulian Sathupradit New Agency\n\n' + _shipAfterSlipNoteFor(lang);
    }
  }

  if (extraBubble) {
    sendReply(replyToken, [summaryText + translatedNote, extraBubble]);
  } else {
    sendReply(replyToken, summaryText + translatedNote);
  }
  } catch (err) {
    // GAS ไม่มี log ที่ดูง่าย — เก็บ error ล่าสุดไว้ใน Script Property แทน
    // (ดูได้ผ่าน GAS Editor > Project Settings > Script Properties เท่านั้น ไม่มี
    // endpoint สาธารณะให้ดูอีกแล้ว และไม่เก็บเศษ secret ใด ๆ ไว้ในนี้)
    _scriptProps.setProperty('LAST_ERROR',
      Utilities.formatDate(new Date(), 'Asia/Bangkok', 'yyyy-MM-dd HH:mm:ss') + ' | ' +
      String(err) + (err.stack ? (' | STACK: ' + err.stack) : '') +
      ' | replyToken=' + (typeof replyToken !== 'undefined' ? replyToken : 'n/a'));
  }
}

// ─── sendReply ────────────────────────────────────────────────────────────────

function sendReply(token, text, imageUrl) {
  // รับได้ทั้ง string เดียว (ปกติ) หรือ array ของ string หลายข้อความ — ส่งเป็นหลายบับเบิลใน
  // reply call เดียวกัน (replyToken ใช้ได้แค่ครั้งเดียว ยิงซ้ำไม่ได้ ต้องรวมเป็น array นี้แทน
  // การเรียก sendReply สองรอบ) ใช้ตอนอยากแยกสรุปยอด/โน้ตจัดส่งออกเป็นคนละบับเบิล
  var texts = Array.isArray(text) ? text : [text];
  var messages = texts.map(function(t) { return { type: 'text', text: t }; });
  if (imageUrl) messages.push({ type: 'image', originalContentUrl: imageUrl, previewImageUrl: imageUrl });
  UrlFetchApp.fetch('https://api.line.me/v2/bot/message/reply', {
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + CHANNEL_ACCESS_TOKEN },
    method: 'post',
    payload: JSON.stringify({ replyToken: token, messages: messages })
  });
}

// ─── Number formatter ─────────────────────────────────────────────────────────

function numFmt(n) {
  return Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

// ─── Today's date (Bangkok) ───────────────────────────────────────────────────

function _today() {
  return Utilities.formatDate(new Date(), 'Asia/Bangkok', 'yyyy-MM-dd');
}

// สร้างเลขที่บิล YYMMDD-NNN ถัดไป (รูปแบบเดียวกับ database.py get_next_bill_no)
function _getNextBillNo(dateStr) {
  var prefix = dateStr.replace(/-/g, '').substring(2);
  var rows = _sbGet('/rest/v1/transactions?bill_no=like.' + prefix + '-*&select=bill_no') || [];
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

// ─── บันทึกยอดการเงินรายวัน (finance_daily) จาก LINE — #milk ads/bv/scb/po ────
// map ตรงกับคอลัมน์ใน finance_daily / fin_ui.py หน้า 💵 การเงิน → ยอดขาย ทุกตัว
var _FIN_FIELDS = {
  ads: { fields: ['registration_fee', 'sales_amount'], labels: ['ค่าสมัคร', 'ยอดขาย รวม VAT'] },
  bv:  { fields: ['bv_amount'],        labels: ['BV (หักยอดค้าง)'] },
  scb: { fields: ['transfer_amount'],  labels: ['ยอดโอนให้บริษัท'] },
  po:  { fields: ['po_amount'],        labels: ['PO สั่งของ ไม่รวม VAT'] },
};

// แปลง token วันที่จาก LINE เป็น 'YYYY-MM-DD' — รองรับ "วันนี้"/"today" และ D/M
// (ปีปัจจุบันเสมอ ไม่รองรับข้ามปี — ถ้าต้องย้อนปีเก่ากว่านั้น ให้กรอกในแอปแทน)
function _parseFinDate(tok) {
  if (tok === 'วันนี้' || tok.toLowerCase() === 'today') return _today();
  var m = /^(\d{1,2})\/(\d{1,2})$/.exec(tok);
  if (!m) return null;
  var d = parseInt(m[1], 10), mo = parseInt(m[2], 10);
  if (d < 1 || d > 31 || mo < 1 || mo > 12) return null;
  var y = new Date().getFullYear();
  return y + '-' + (mo < 10 ? '0' + mo : mo) + '-' + (d < 10 ? '0' + d : d);
}

function _getFinanceDay(dateStr) {
  var rows = _sbGet('/rest/v1/finance_daily?entry_date=eq.' + dateStr + '&select=*');
  return (rows && rows.length > 0) ? rows[0] : null;
}

// ─── check today — สิทธิ์สั่งของคงเหลือ (คำนวณซ้ำสูตรเดียวกับ database.py) ─────
// สูตรนี้ต้อง sync มือกับ get_finance_df()/get_finance_summary() ใน database.py
// เสมอถ้าแก้ตรงนั้น (net = Σ(โอน+bv+ปรับ) − Σ(ขาย+ค่าสมัคร), auto_stock = สต๊อกยกมา
// (ค่า stock_value>0 ตัวแรกตามวันที่) + ΣPO − Σ(ขาย/1.07), เพดาน 1,100,000)
// — เอาผลรวมทั้งประวัติ (เทียบเท่า cumsum ที่แถวสุดท้าย) ไม่ต้องมี array ราย row
function handleFinanceCredit(replyToken) {
  var rows = _sbGet('/rest/v1/finance_daily?select=entry_date,transfer_amount,sales_amount,'
    + 'po_amount,registration_fee,bv_amount,stock_value,adjustment&order=entry_date.asc') || [];
  if (!Array.isArray(rows) || rows.length === 0) {
    sendReply(replyToken, '❌ ยังไม่มีข้อมูลการเงินในระบบเลยค่ะ');
    return;
  }
  var sumTransferBvAdj = 0, sumSalesReg = 0, sumPo = 0, sumSales = 0;
  var openingStock = 0, openingFound = false;
  rows.forEach(function(r) {
    sumTransferBvAdj += (r.transfer_amount || 0) + (r.bv_amount || 0) + (r.adjustment || 0);
    sumSalesReg      += (r.sales_amount || 0) + (r.registration_fee || 0);
    sumPo            += (r.po_amount || 0);
    sumSales         += (r.sales_amount || 0);
    if (!openingFound && (r.stock_value || 0) > 0) { openingStock = r.stock_value; openingFound = true; }
  });
  var net        = sumTransferBvAdj - sumSalesReg;
  var autoStock  = openingStock + sumPo - (sumSales / 1.07);
  var credit     = (1100000 + net) / 1.07 - autoStock;
  var overpaid   = Math.max(0, net);
  var outstanding = Math.max(0, -net);
  var lastDate   = rows[rows.length - 1].entry_date;

  var msg = '📊 สิทธิ์สั่งของ (ข้อมูลล่าสุดถึง ' + lastDate + ')\n─────────────────\n';
  msg += '🚩 ยอดค้างโอน: ฿' + numFmt(outstanding) + '\n';
  msg += '💰 เงินโอนเกิน: ฿' + numFmt(overpaid) + '\n';
  msg += '📦 สต๊อก ไม่รวม VAT: ฿' + numFmt(autoStock) + '\n';
  msg += '🛒 สิทธิ์สั่งของคงเหลือ: ฿' + numFmt(credit) + (credit < 0 ? ' ⚠️ เกินวงเงิน' : '') + '\n';

  sendReply(replyToken, msg);
}

// kind: 'ads'|'bv'|'scb'|'po', dateTok: token วันที่ดิบจาก LINE, values: [เลข, ...]
// ตามลำดับ _FIN_FIELDS[kind].fields — ทับยอดเดิมของฟิลด์นั้นเท่านั้น ฟิลด์อื่นของวันนั้น
// (เช่น stock_value/adjustment ที่กรอกจากแอป) คงค่าเดิมไว้ เพราะ finance_daily เป็น
// delete+insert ทั้งแถวเสมอ (ไม่มี upsert จริงของ Postgres) ต้องอ่านของเดิมมา merge ก่อน
function handleFinanceEntry(kind, dateTok, values, replyToken, confirmed, staffTag) {
  var dateStr = _parseFinDate(dateTok);
  if (!dateStr) {
    sendReply(replyToken, '❌ วันที่ไม่ถูกต้อง: "' + dateTok + '"\nพิมพ์แบบ วัน/เดือน เช่น 6/8 หรือ วันนี้');
    return;
  }
  var def = _FIN_FIELDS[kind];
  var preview = def.labels.map(function(lbl, i) { return lbl + ': ฿' + numFmt(values[i]); }).join('\n');

  if (!confirmed) {
    sendQuickReply(replyToken,
      '📝 ยืนยันบันทึกข้อมูลการเงินวันที่ ' + dateStr + ' ค่ะ (ทับยอดเดิมของฟิลด์นี้ถ้ามี)\n' + preview,
      [
        { type: 'action', action: { type: 'message', label: '✅ ยืนยันบันทึก',
            text: 'ยืนยัน #' + staffTag + ' ' + kind + ' ' + dateTok + ' ' + values.join(' ') } },
        { type: 'action', action: { type: 'message', label: '❌ ยกเลิก', text: 'ยกเลิก' } }
      ]);
    return;
  }

  var existing = _getFinanceDay(dateStr);
  var row = {
    id:               Utilities.getUuid(),
    entry_date:       dateStr,
    transfer_amount:  existing ? existing.transfer_amount : 0,
    sales_amount:     existing ? existing.sales_amount : 0,
    po_amount:        existing ? existing.po_amount : 0,
    registration_fee: existing ? existing.registration_fee : 0,
    bv_amount:        existing ? existing.bv_amount : 0,
    stock_value:      existing ? existing.stock_value : 0,
    adjustment:       existing ? existing.adjustment : 0,
    notes:            existing ? (existing.notes || '') : '',
  };
  def.fields.forEach(function(f, i) { row[f] = values[i]; });

  UrlFetchApp.fetch(SUPABASE_URL + '/rest/v1/finance_daily?entry_date=eq.' + dateStr,
    { method: 'DELETE', headers: _sbWriteHdrs(), muteHttpExceptions: true });
  _sbPost('finance_daily', row);

  sendReply(replyToken, '✅ บันทึกข้อมูลการเงินวันที่ ' + dateStr + ' แล้วค่ะ\n' + preview);
}

// ─── ลงทะเบียน LINE ──────────────────────────────────────────────────────────

function registerLineUser(userId, phone, replyToken) {
  phone = phone.replace(/\D/g, '');
  var rows = _sbGet('/rest/v1/customers?phone=eq.' + phone + '&select=id,name');
  if (!rows || rows.length === 0) {
    sendReply(replyToken, '❌ ไม่พบเบอร์ ' + phone + ' ในระบบ\nกรุณาติดต่อร้านค้า');
    return;
  }
  var cust = rows[0];
  _sbPatch('/rest/v1/customers?id=eq.' + cust.id, { line_user_id: userId });
  sendReply(replyToken,
    '✅ ลงทะเบียนสำเร็จค่ะ!\nสวัสดี ' + cust.name + ' 🙏\n' +
    'ตอนนี้รับการแจ้งเตือนสถานะพัสดุผ่าน LINE ได้แล้วนะคะ');
}

// ─── สรุปยอด (ลูกค้าพิมพ์ "ยอด") ─────────────────────────────────────────────

function sendCustomerSummary(userId, replyToken) {
  var custs = _sbGet('/rest/v1/customers?line_user_id=eq.' + userId + '&select=id,name');
  if (!custs || custs.length === 0) {
    sendReply(replyToken, '❌ ยังไม่ได้ลงทะเบียน LINE\nพิมพ์: สมัคร [เบอร์โทร] เพื่อเชื่อมบัญชี');
    return;
  }
  buildAndSendSummary(custs[0].id, custs[0].name, replyToken);
}

// ─── buildAndSendSummary (ใช้ร่วมกัน) ────────────────────────────────────────

function buildAndSendSummary(custId, custName, replyToken) {
  // คะแนนที่ยังไม่เปิดบิล — นับเฉพาะจำนวนที่ยังไม่เปิดจริงต่อแถว (qty -
  // Σbill_open_events.qty_opened) ไม่ใช่ทั้งแถว เพราะตอนนี้เปิดบิลบางส่วนได้
  // โดยไม่แยกแถวแล้ว (bill_status ยังเป็น "ยังไม่เปิดบิล" จนกว่าจะเปิดครบ)
  var unbilledTxns = _sbGet(
    '/rest/v1/transactions?customer_id=eq.' + custId
    + '&bill_status=eq.' + encodeURIComponent('ยังไม่เปิดบิล')
    + '&select=id,bill_no,qty,points_per_unit'
  ) || [];
  var unbilledTxnIds = unbilledTxns.map(function(t) { return t.id; });
  var openEvents = unbilledTxnIds.length > 0 ? (_sbGet(
    '/rest/v1/bill_open_events?transaction_id=in.(' + unbilledTxnIds.join(',') + ')&select=transaction_id,qty_opened'
  ) || []) : [];
  var openedMap = {};
  openEvents.forEach(function(e) {
    openedMap[e.transaction_id] = (openedMap[e.transaction_id] || 0) + parseInt(e.qty_opened || 0, 10);
  });
  // billPVMap: คะแนนรอเปิดบิลแยกต่อเลขบิล (ไม่ใช่แค่รวมยอดเดียวท้ายข้อความ) — ลูกค้า/
  // ร้านค้าที่มีหลายบิลยังไม่เปิดพร้อมกัน จะรู้ว่าบิลไหนมีกี่ PV ค้างอยู่
  var billPVMap = {};
  var unbilledPV = unbilledTxns.reduce(function(s, t) {
    var unbilledQty = Math.max(0, t.qty - Math.max(0, openedMap[t.id] || 0));
    var pv = parseFloat(t.points_per_unit || 0) * unbilledQty;
    var bKey = t.bill_no || '(ไม่มีเลขบิล)';
    billPVMap[bKey] = (billPVMap[bKey] || 0) + pv;
    return s + pv;
  }, 0);

  // ดึง 6 เดือนล่าสุดโดยไม่กรอง pay_status
  // (จ่ายครบแล้วแต่ยังไม่รับของก็ต้องโชว์)
  var cutoff = new Date();
  cutoff.setMonth(cutoff.getMonth() - 6);
  var cutoffStr = Utilities.formatDate(cutoff, 'Asia/Bangkok', 'yyyy-MM-dd');
  var txns = _sbGet(
    '/rest/v1/transactions?customer_id=eq.' + custId
    + '&date=gte.' + cutoffStr
    + '&select=id,product_id,product_name,qty,total_amount,pay_status,points_per_unit,initial_qty_received,bill_no'
    + '&order=bill_no.desc&limit=50'
  ) || [];

  var txnIds = txns.map(function(t) { return t.id; });
  var events = txnIds.length > 0 ? (_sbGet(
    '/rest/v1/partial_events?transaction_id=in.(' + txnIds.join(',') + ')&select=transaction_id,amount_paid,qty_received'
  ) || []) : [];

  var paidMap = {}, receivedMap = {};
  events.forEach(function(e) {
    paidMap[e.transaction_id] = (paidMap[e.transaction_id] || 0) + parseFloat(e.amount_paid || 0);
    receivedMap[e.transaction_id] = (receivedMap[e.transaction_id] || 0) + parseInt(e.qty_received || 0);
  });

  var totalOutstanding = 0, hasAny = false;
  var billMap = {}, billOrder = [];
  txns.forEach(function(t) {
    var paid = paidMap[t.id] || 0;
    var outstanding = t.pay_status === 'จ่ายแล้ว' ? 0 : Math.max(0, parseFloat(t.total_amount) - paid);
    var received = (t.initial_qty_received || 0) + (receivedMap[t.id] || 0);
    var remaining = t.qty - received;
    if (outstanding <= 0.01 && remaining <= 0) return;
    hasAny = true;
    if (outstanding > 0.01) totalOutstanding += outstanding;
    var bill = t.bill_no || '(ไม่มีเลขบิล)';
    if (!billMap[bill]) { billMap[bill] = { outstanding: 0, items: [] }; billOrder.push(bill); }
    if (outstanding > 0.01) billMap[bill].outstanding += outstanding;
    if (remaining > 0) billMap[bill].items.push({ t: t, remaining: remaining });
  });

  // บิลที่มี PV ค้างเปิดแต่ของรับ+จ่ายครบแล้ว (เลย loop ข้างบนไม่ถูกเก็บ) ก็ต้องโชว์
  // เลขบิลนั้นด้วย ไม่งั้น PV ของบิลนั้นจะไม่ถูกพิมพ์ที่ไหนเลย
  Object.keys(billPVMap).forEach(function(bKey) {
    if (billPVMap[bKey] <= 0) return;
    if (!billMap[bKey]) { billMap[bKey] = { outstanding: 0, items: [] }; billOrder.push(bKey); }
    hasAny = true;
  });

  if (!hasAny && unbilledPV === 0) {
    sendReply(replyToken, '✅ สวัสดีค่ะ คุณ' + custName + '\nไม่มียอดค้างชำระค่ะ 🙏');
    return;
  }

  var msg = '📊 สรุปยอด คุณ' + custName + '\n─────────────────\n';

  billOrder.forEach(function(bill) {
    var grp = billMap[bill];
    msg += '📋 บิล ' + bill + '\n';
    grp.items.forEach(function(item) {
      var t = item.t;
      msg += '  ▫️ [' + (t.product_id || '') + '] ' + t.product_name + ' — ค้างรับ ' + item.remaining + '/' + t.qty + ' ชิ้น\n';
    });
    if (grp.outstanding > 0.01) {
      msg += '  💰 ค้างจ่าย: ฿' + numFmt(grp.outstanding) + '\n';
    }
    if (billPVMap[bill] > 0) {
      msg += '  ✨ คะแนนรอเปิดบิล: ' + numFmt(billPVMap[bill]) + ' PV\n';
    }
  });

  if (billOrder.length > 0) msg += '─────────────────\n';
  msg += totalOutstanding > 0
    ? '💰 ยอดค้างจ่ายรวม: ฿' + numFmt(totalOutstanding) + '\n'
    : '💰 ไม่มียอดค้างจ่าย\n';
  if (unbilledPV > 0) {
    msg += '✨ คะแนนรอเปิดบิล: ' + numFmt(unbilledPV) + ' PV\n';
  }

  sendReply(replyToken, msg);
}

// ─── findOneCustomer — ค้นหาลูกค้า 1 คนจากชื่อ ────────────────────────────────

function findOneCustomer(name, replyToken, resendTemplate) {
  var enc = encodeURIComponent('%' + name + '%');
  var rows = _sbGet('/rest/v1/customers?name=ilike.' + enc + '&select=id,name');

  if (!rows || rows.length === 0) {
    // ลองค้นแบบไม่สนใจวรรค (เช่น "mokham" → "Mo Kham")
    var needle = name.trim().toLowerCase().replace(/\s+/g, '');
    var allRows = _sbGet('/rest/v1/customers?select=id,name') || [];
    rows = allRows.filter(function(c) {
      return c.name.toLowerCase().replace(/\s+/g, '').indexOf(needle) !== -1;
    });
  }
  if (!rows || rows.length === 0) return null;

  if (rows.length === 1 && rows[0].name.toLowerCase() !== name.trim().toLowerCase()) {
    // เจอ 1 คนพอดี แต่ชื่อที่พิมพ์ไม่ตรงเป๊ะ (เช่น "chit no" ตรงกับ "Chit Noe" แต่ยังมี
    // "Chit Kyi"/"Chit Moe" ที่ใกล้เคียงด้วย) เช็คชื่อที่ขึ้นต้นเหมือนกันอีกที
    // ถ้าพิมพ์ชื่อตรงเป๊ะอยู่แล้ว ไม่ต้องเช็ค (กันวนซ้ำตอนกดยืนยันชื่อที่เลือกแล้ว)
    var firstWord = name.trim().split(/\s+/)[0];
    if (firstWord.length >= 2) {
      var prefixEnc = encodeURIComponent(firstWord + '%');
      var similar = _sbGet('/rest/v1/customers?name=ilike.' + prefixEnc + '&select=id,name') || [];
      if (similar.length > 1) rows = similar;
    }
  }

  if (rows.length > 1) {
    if (rows.length <= 13) {
      var items = rows.map(function(c) {
        var text = (resendTemplate || 'check {name}').replace('{name}', c.name);
        return { type: 'action', action: { type: 'message', label: c.name.substring(0, 20), text: text } };
      });
      sendQuickReply(replyToken, '🔍 พบ ' + rows.length + ' คน ตรงกับ "' + name + '" เลือกเลยค่ะ:', items);
    } else {
      var names = rows.slice(0, 13).map(function(c) { return c.name; }).join(', ');
      sendReply(replyToken, '🔍 พบ ' + rows.length + ' คน: ' + names + ' ...\nพิมพ์ชื่อให้ชัดขึ้นค่ะ');
    }
    return null;
  }
  return rows[0];
}

// ─── คู่มือ — แสดงคำสั่งที่ใช้งานได้ทั้งหมด ──────────────────────────────────

function handleManual(replyToken, staffTag) {
  var tag = '#' + staffTag;
  var msg = '📖 คู่มือคำสั่ง LINE OA\n';
  msg += '─────────────────\n';
  msg += '⚠️ คำสั่งบันทึก/แก้ไขข้อมูลทุกตัว ต้องมี ' + tag + ' นำหน้าเสมอ\n';
  msg += '(ถ้าไม่มี #milk หรือ #max ระบบจะไม่ตอบกลับเลย)\n\n';

  msg += '🔍 ดูยอด/ตรวจสอบ\n';
  msg += '  • ' + tag + ' check  — เลือกลูกค้าจากเมนู\n';
  msg += '  • ' + tag + ' check [ชื่อ]  — ดูยอดค้างจ่าย/ค้างรับของลูกค้า\n';
  msg += '  • ' + tag + ' check today  — สิทธิ์สั่งของคงเหลือ (ข้อมูลล่าสุดในระบบ)\n\n';

  msg += 'ℹ️ รับของเก่าที่ค้างส่ง/เก็บเงินค้างจ่าย ย้ายไปทำที่ LINE Coffee Log แทนแล้ว\n\n';

  msg += '🆕 รับของใหม่ (ยังไม่เปิดบิล)\n';
  msg += '  • ' + tag + ' [ชื่อ] เบิก CODE-จำนวน CODE-จำนวน ...  — รับของ ค้างจ่าย\n';
  msg += '  • ' + tag + ' [ชื่อ] เบิกจ่าย CODE-จำนวน CODE-จำนวน ...  — รับของ + จ่ายเงินแล้ว\n';
  msg += '  • ' + tag + ' [ชื่อ] เบิกจ่าย CODE-จำนวน CODE-จำนวน ... จ่าย จำนวนเงิน  — รับของ + จ่ายบางส่วน\n\n';

  msg += '💵 บันทึกยอดการเงินรายวัน (ทับยอดเดิมของวันนั้นถ้ามี)\n';
  msg += '  • ' + tag + ' ads วัน/เดือน ค่าสมัคร ยอดขาย  — เช่น ' + tag + ' ads 6/8 500 12000\n';
  msg += '  • ' + tag + ' bv วัน/เดือน จำนวนเงิน  — BV หักยอดค้าง\n';
  msg += '  • ' + tag + ' scb วัน/เดือน จำนวนเงิน  — ยอดโอนให้บริษัท\n';
  msg += '  • ' + tag + ' po วัน/เดือน จำนวนเงิน  — PO สั่งของ ไม่รวม VAT\n';
  msg += '  • ใช้ "วันนี้" แทนวัน/เดือนได้ (ไม่รองรับข้ามปี)\n\n';

  msg += '✅ ทุกคำสั่งบันทึกจริง จะมีปุ่ม "ยืนยันบันทึก" ให้กดก่อนเสมอ\n';
  msg += '─────────────────\n';
  msg += '👤 คำสั่งสำหรับลูกค้า (ไม่ต้องมี #tag)\n';
  msg += '  • สมัคร เบอร์โทร  — ผูกไลน์กับบัญชีลูกค้า\n';
  msg += '  • ยอด / สรุปยอด  — ดูยอดค้างจ่าย/ค้างรับของตัวเอง\n';
  msg += '  • qr  — ดูข้อมูลโอนเงิน\n';
  msg += '  • คำนวณออเดอร์ เช่น CODE-จำนวน SHรหัสไปรษณีย์ cod plan ... (กำหนดค่าส่งเองใช้ SH-ตัวเลข เช่น SH-5000) — คำนวณราคา/PV/ค่าส่ง\n';

  sendReply(replyToken, msg);
}

// ─── check (ไม่มีชื่อ) — แสดง Quick Reply ให้เลือกลูกค้า ────────────────────

function handleCheckMenu(replyToken) {
  var customers = _sbGet('/rest/v1/customers?select=id,name&order=name.asc') || [];
  if (customers.length === 0) {
    sendReply(replyToken, '❌ ไม่พบข้อมูลลูกค้าในระบบ');
    return;
  }
  if (customers.length <= 13) {
    var items = customers.map(function(c) {
      return {
        type: 'action',
        action: { type: 'message', label: c.name.substring(0, 20), text: 'check ' + c.name }
      };
    });
    sendQuickReply(replyToken, '🔍 เลือกลูกค้าที่ต้องการดูยอด:', items);
  } else {
    var names = customers.map(function(c) { return c.name; }).join(', ');
    sendReply(replyToken, '🔍 ลูกค้าทั้งหมด:\n' + names + '\n\nพิมพ์: check [ชื่อ] เพื่อดูยอดค่ะ');
  }
}

function sendQuickReply(token, text, items) {
  UrlFetchApp.fetch('https://api.line.me/v2/bot/message/reply', {
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + CHANNEL_ACCESS_TOKEN },
    method: 'post',
    payload: JSON.stringify({
      replyToken: token,
      messages: [{ type: 'text', text: text, quickReply: { items: items } }]
    })
  });
}

// ─── check [name] — เจ้าของร้านดูยอดค้าง ────────────────────────────────────

function handleCustomerByName(name, replyToken) {
  var cust = findOneCustomer(name, replyToken, 'check {name}');
  if (!cust) return;
  buildAndSendSummary(cust.id, cust.name, replyToken);
}

// ─── [name] เบิก CODE-QTY [CODE-QTY ...] — รับของ ค้างจ่าย ยังไม่เปิดบิล ──

function handleWithdraw(name, items, replyToken, confirmed, staffTag) {
  var _resendItems = items.map(function(i) { return i.code + '-' + i.qty; }).join(' ');
  var cust = findOneCustomer(name, replyToken, '#' + staffTag + ' {name} เบิก ' + _resendItems);
  if (!cust) return;

  var pData = _getProducts();
  var today = _today();

  var rows = [], lines = '', notFound = '';
  items.forEach(function(item) {
    var prod = null;
    for (var i = 0; i < pData.length; i++) {
      if (pData[i][0].toString().toUpperCase() === item.code) {
        prod = { name: pData[i][1], price: pData[i][3], pv: pData[i][4] };
        break;
      }
    }
    if (!prod) { notFound += '❌ ไม่พบสินค้า [' + item.code + ']\n'; return; }

    var totalAmt = prod.price * item.qty;
    rows.push({
      id: Utilities.getUuid(),
      date: today,
      customer_id: cust.id,
      product_id: item.code,
      product_name: prod.name,
      qty: item.qty,
      price_per_unit: prod.price,
      points_per_unit: prod.pv,
      total_amount: totalAmt,
      initial_qty_received: item.qty,
      transaction_type: 'เบิกของก่อน',
      bill_status: 'ยังไม่เปิดบิล',
      pay_status: 'ค้างจ่าย',
      notes: '#' + staffTag,
      bill_no: null
    });
    lines += '📦 [' + item.code + '] ' + prod.name + '\n      ' + item.qty + ' ชิ้น x ฿' + numFmt(prod.price) + ' = ฿' + numFmt(totalAmt) + '\n';
  });

  if (rows.length === 0) {
    sendReply(replyToken, notFound || '❌ ไม่พบสินค้าที่ระบุ');
    return;
  }

  var totalAll = rows.reduce(function(s, r) { return s + r.total_amount; }, 0);
  var totalPV = rows.reduce(function(s, r) { return s + parseFloat(r.points_per_unit || 0) * r.qty; }, 0);

  if (!confirmed) {
    var preview = notFound;
    preview += '📋 ตรวจสอบก่อนบันทึก: คุณ' + cust.name + ' (ค้างจ่าย / ยังไม่เปิดบิล)\n';
    preview += '─────────────────\n' + lines + '─────────────────\n';
    preview += '💰 ค้างจ่ายรวม: ฿' + numFmt(totalAll) + '\n';
    preview += '✨ คะแนนรอเปิดบิล: ' + numFmt(totalPV) + ' PV\n';
    sendQuickReply(replyToken, preview, [{
      type: 'action',
      action: { type: 'message', label: '✅ ยืนยันบันทึก', text: 'ยืนยัน #' + staffTag + ' ' + cust.name + ' เบิก ' + _resendItems }
    }, {
      type: 'action',
      action: { type: 'message', label: '❌ ยกเลิก', text: 'ยกเลิก' }
    }]);
    return;
  }

  var billNo = _getNextBillNo(today);
  rows.forEach(function(r) { r.bill_no = billNo; _sbPost('transactions', r); });

  var msg = notFound;
  msg += '✅ บันทึกรับของ คุณ' + cust.name + ' (ค้างจ่าย / ยังไม่เปิดบิล)\n';
  msg += '─────────────────\n' + lines + '─────────────────\n';
  msg += '💰 ค้างจ่ายรวม: ฿' + numFmt(totalAll) + '\n';
  msg += '✨ คะแนนรอเปิดบิล: ' + numFmt(totalPV) + ' PV\n';
  msg += '🧾 เลขที่บิล: ' + billNo + '\n';
  sendReply(replyToken, msg);
}

// ─── [name] เบิกจ่าย CODE-QTY [CODE-QTY ...] — รับของ + จ่ายเงินแล้ว ยังไม่เปิดบิล ──

function handleWithdrawPaid(name, items, replyToken, confirmed, staffTag) {
  var _resendItems = items.map(function(i) { return i.code + '-' + i.qty; }).join(' ');
  var cust = findOneCustomer(name, replyToken, '#' + staffTag + ' {name} เบิกจ่าย ' + _resendItems);
  if (!cust) return;

  var pData = _getProducts();
  var today = _today();

  var rows = [], lines = '', notFound = '';
  items.forEach(function(item) {
    var prod = null;
    for (var i = 0; i < pData.length; i++) {
      if (pData[i][0].toString().toUpperCase() === item.code) {
        prod = { name: pData[i][1], price: pData[i][3], pv: pData[i][4] };
        break;
      }
    }
    if (!prod) { notFound += '❌ ไม่พบสินค้า [' + item.code + ']\n'; return; }

    var totalAmt = prod.price * item.qty;
    rows.push({
      id: Utilities.getUuid(),
      date: today,
      customer_id: cust.id,
      product_id: item.code,
      product_name: prod.name,
      qty: item.qty,
      price_per_unit: prod.price,
      points_per_unit: prod.pv,
      total_amount: totalAmt,
      initial_qty_received: item.qty,
      transaction_type: 'เบิกของก่อน',
      bill_status: 'ยังไม่เปิดบิล',
      pay_status: 'จ่ายแล้ว',
      notes: '#' + staffTag,
      bill_no: null
    });
    lines += '📦 [' + item.code + '] ' + prod.name + '\n      ' + item.qty + ' ชิ้น x ฿' + numFmt(prod.price) + ' = ฿' + numFmt(totalAmt) + '\n';
  });

  if (rows.length === 0) {
    sendReply(replyToken, notFound || '❌ ไม่พบสินค้าที่ระบุ');
    return;
  }

  var totalAll = rows.reduce(function(s, r) { return s + r.total_amount; }, 0);
  var totalPV = rows.reduce(function(s, r) { return s + parseFloat(r.points_per_unit || 0) * r.qty; }, 0);

  if (!confirmed) {
    var preview = notFound;
    preview += '📋 ตรวจสอบก่อนบันทึก: คุณ' + cust.name + ' (รับของ + จ่ายเงินแล้ว ยังไม่เปิดบิล)\n';
    preview += '─────────────────\n' + lines + '─────────────────\n';
    preview += '💵 รับเงินแล้ว: ฿' + numFmt(totalAll) + '\n';
    preview += '✨ คะแนนรอเปิดบิล: ' + numFmt(totalPV) + ' PV\n';
    sendQuickReply(replyToken, preview, [{
      type: 'action',
      action: { type: 'message', label: '✅ ยืนยันบันทึก', text: 'ยืนยัน #' + staffTag + ' ' + cust.name + ' เบิกจ่าย ' + _resendItems }
    }, {
      type: 'action',
      action: { type: 'message', label: '❌ ยกเลิก', text: 'ยกเลิก' }
    }]);
    return;
  }

  var billNo = _getNextBillNo(today);
  rows.forEach(function(r) { r.bill_no = billNo; _sbPost('transactions', r); });

  var msg = notFound;
  msg += '✅ บันทึกรับของ + จ่ายเงินแล้ว คุณ' + cust.name + ' (ยังไม่เปิดบิล)\n';
  msg += '─────────────────\n' + lines + '─────────────────\n';
  msg += '💵 รับเงินแล้ว: ฿' + numFmt(totalAll) + '\n';
  msg += '✨ คะแนนรอเปิดบิล: ' + numFmt(totalPV) + ' PV\n';
  msg += '🧾 เลขที่บิล: ' + billNo + '\n';
  sendReply(replyToken, msg);
}

// ─── [name] เบิกจ่าย CODE-QTY ... จ่าย AMOUNT — บันทึกรับของ + จ่ายเงินบางส่วน ──

function handleWithdrawPartialPay(name, items, payAmount, replyToken, confirmed, staffTag) {
  var _resendItems = items.map(function(i) { return i.code + '-' + i.qty; }).join(' ');
  var _resendSuffix = 'เบิกจ่าย ' + _resendItems + ' จ่าย ' + payAmount;
  var cust = findOneCustomer(name, replyToken, '#' + staffTag + ' {name} ' + _resendSuffix);
  if (!cust) return;

  var pData = _getProducts();
  var today = _today();

  var rows = [], lines = '', notFound = '';
  items.forEach(function(item) {
    var prod = null;
    for (var i = 0; i < pData.length; i++) {
      if (pData[i][0].toString().toUpperCase() === item.code) {
        prod = { name: pData[i][1], price: pData[i][3], pv: pData[i][4] };
        break;
      }
    }
    if (!prod) { notFound += '❌ ไม่พบสินค้า [' + item.code + ']\n'; return; }

    var totalAmt = prod.price * item.qty;
    rows.push({
      id: Utilities.getUuid(),
      date: today,
      customer_id: cust.id,
      product_id: item.code,
      product_name: prod.name,
      qty: item.qty,
      price_per_unit: prod.price,
      points_per_unit: prod.pv,
      total_amount: totalAmt,
      initial_qty_received: item.qty,
      transaction_type: 'เบิกของก่อน',
      bill_status: 'ยังไม่เปิดบิล',
      pay_status: 'ค้างจ่าย',
      notes: '#' + staffTag,
      bill_no: null
    });
    lines += '📦 [' + item.code + '] ' + prod.name + '\n      ' + item.qty + ' ชิ้น x ฿' + numFmt(prod.price) + ' = ฿' + numFmt(totalAmt) + '\n';
  });

  if (rows.length === 0) {
    sendReply(replyToken, notFound || '❌ ไม่พบสินค้าที่ระบุ');
    return;
  }

  var totalAll = rows.reduce(function(s, r) { return s + r.total_amount; }, 0);
  var totalPV = rows.reduce(function(s, r) { return s + parseFloat(r.points_per_unit || 0) * r.qty; }, 0);
  var applyPay = Math.min(payAmount, totalAll);
  var payNote = (payAmount > totalAll)
    ? '⚠️ ยอดรวมมีเพียง ฿' + numFmt(totalAll) + ' บันทึกรับเงิน ฿' + numFmt(applyPay) + ' (ส่วนเกินไม่บันทึก)\n' : '';

  // กระจายยอดจ่ายตามสัดส่วนยอดรวมของแต่ละรายการ
  var remaining = applyPay;
  rows.forEach(function(r, idx) {
    var share;
    if (idx === rows.length - 1) {
      share = remaining;
    } else {
      share = Math.min(Math.round((r.total_amount / totalAll) * applyPay * 100) / 100, remaining);
    }
    remaining -= share;
    r._pay_share = share;
    if (share >= r.total_amount - 0.01) r.pay_status = 'จ่ายแล้ว';
  });

  if (!confirmed) {
    var preview = notFound + payNote;
    preview += '📋 ตรวจสอบก่อนบันทึก: คุณ' + cust.name + ' (เบิกของ + จ่ายบางส่วน)\n';
    preview += '─────────────────\n' + lines + '─────────────────\n';
    preview += '💰 ยอดรวม: ฿' + numFmt(totalAll) + '\n';
    preview += '💵 รับเงิน: ฿' + numFmt(applyPay) + '\n';
    preview += '🔴 ค้างจ่าย: ฿' + numFmt(totalAll - applyPay) + '\n';
    preview += '✨ คะแนนรอเปิดบิล: ' + numFmt(totalPV) + ' PV\n';
    sendQuickReply(replyToken, preview, [{
      type: 'action',
      action: { type: 'message', label: '✅ ยืนยันบันทึก', text: 'ยืนยัน #' + staffTag + ' ' + cust.name + ' ' + _resendSuffix }
    }, {
      type: 'action',
      action: { type: 'message', label: '❌ ยกเลิก', text: 'ยกเลิก' }
    }]);
    return;
  }

  var billNo = _getNextBillNo(today);
  rows.forEach(function(r) {
    r.bill_no = billNo;
    var share = r._pay_share;
    delete r._pay_share;
    _sbPost('transactions', r);
    if (share > 0 && r.pay_status !== 'จ่ายแล้ว') {
      _sbPost('partial_events', {
        id: Utilities.getUuid(), date: today,
        transaction_id: r.id,
        qty_received: 0, amount_paid: share, event_type: 'จ่ายเงิน',
        notes: '#' + staffTag
      });
    }
  });

  var msg = notFound + payNote;
  msg += '✅ บันทึกเบิกของ + รับเงินบางส่วน คุณ' + cust.name + ' (ยังไม่เปิดบิล)\n';
  msg += '─────────────────\n' + lines + '─────────────────\n';
  msg += '💰 ยอดรวม: ฿' + numFmt(totalAll) + '\n';
  msg += '💵 รับเงินแล้ว: ฿' + numFmt(applyPay) + '\n';
  msg += '🔴 ค้างจ่าย: ฿' + numFmt(totalAll - applyPay) + '\n';
  msg += '✨ คะแนนรอเปิดบิล: ' + numFmt(totalPV) + ' PV\n';
  msg += '🧾 เลขที่บิล: ' + billNo + '\n';
  sendReply(replyToken, msg);
}

// ─── doGet — product list ─────────────────────────────────────────────────────

function doGet(e) {
  var products = _getProducts().map(function(p) {
    return { code: p[0].toUpperCase(), nameTH: p[1], nameMM: p[2], price: p[3], pv: p[4] };
  });
  return ContentService.createTextOutput(JSON.stringify(products))
    .setMimeType(ContentService.MimeType.JSON);
}
