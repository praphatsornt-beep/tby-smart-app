// ─────────────────────────────────────────────────────────────────────────────
// ⚙️  Script Properties — วิธีตั้งค่า
//    GAS Editor > ⚙️ Project Settings > Script Properties > Add property:
//      CHANNEL_ACCESS_TOKEN  — LINE OA Channel Access Token (LINE Developers Console)
//      CHANNEL_SECRET        — LINE OA Channel Secret (สำหรับ verify webhook signature)
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
    // DEBUG ชั่วคราว — โยน error ที่มีเนื้อหาจริงจาก Supabase ติดไปด้วย
    throw new Error('_getProducts non-array response: ' + JSON.stringify(_raw));
  }
  _cachedProducts = _raw.map(function(p) {
    return [p.id, p.name, p.name_mm || '', p.price, p.points_per_unit, (p.weight_grams || 0) / 1000];
  });
  return _cachedProducts;
}

// ─── doPost ──────────────────────────────────────────────────────────────────

function doPost(e) {
  try {
  // ── DEBUG ชั่วคราว ──────────────────────────────────────────────────────
  var _dbgSigOk = 'n/a';
  // ─────────────────────────────────────────────────────────────────────────

  // ── LINE webhook signature verification (HMAC-SHA256) ─────────────────────
  var _channelSecret = _scriptProps.getProperty('CHANNEL_SECRET');
  if (_channelSecret) {
    var _sig      = (e.headers && e.headers['X-Line-Signature']) || '';
    var _computed = Utilities.base64Encode(
      Utilities.computeHmacSha256Signature(e.postData.contents, _channelSecret)
    );
    _dbgSigOk = (_sig === _computed); // DEBUG ชั่วคราว
    if (_sig !== _computed) return;
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

  // ── DEBUG ชั่วคราว — พิมพ์ "debug" ใน LINE เพื่อดูค่าตรงนี้ ──────────────────
  if (event.message.text.trim().toLowerCase() === 'debug') {
    sendReply(event.replyToken,
      'sig match=' + _dbgSigOk +
      '\nCHANNEL_ACCESS_TOKEN len=' + (CHANNEL_ACCESS_TOKEN ? CHANNEL_ACCESS_TOKEN.length : 'MISSING') +
      '\nSUPABASE_URL=' + SUPABASE_URL +
      '\nSUPABASE_KEY len=' + (SUPABASE_KEY ? SUPABASE_KEY.length : 'MISSING'));
    return;
  }
  // ─────────────────────────────────────────────────────────────────────────
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
    var _ppCacheCancel = CacheService.getScriptCache();
    _ppCacheCancel.remove('pp_' + event.source.userId);
    sendReply(replyToken, '❌ ยกเลิกแล้วค่ะ ยังไม่มีการบันทึกข้อมูล');
    return;
  }

  // ── พิมพ์ตัวเลขอย่างเดียว หลังกดปุ่ม "✏️ จ่ายบางส่วน" — ใช้เป็นยอดที่จะจ่าย ──
  var _bareAmt = rawMsg.match(/^(\d+(?:\.\d+)?)$/);
  if (_bareAmt) {
    var _ppCache = CacheService.getScriptCache();
    var _ppKey = 'pp_' + event.source.userId;
    var _ppRaw = _ppCache.get(_ppKey);
    if (_ppRaw) {
      var _pp = JSON.parse(_ppRaw);
      _ppCache.remove(_ppKey);
      handlePayment(_pp.name, _pp.billNo, parseFloat(_bareAmt[1]), replyToken, false, _pp.staffTag);
      return;
    }
  }

  // ── คำสั่งบันทึกข้อมูล (เก่า/เบิก/เบิกจ่าย/จ่าย/check) ───────────────────────
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
    // [name] เก่า CODE-QTY [CODE-QTY ...] (จ่าย[bill] amount)? — รับของได้หลายรายการ
    var _old = _msg.match(/^(.+?)\s+เก่า\s+([A-Za-z0-9]+-\d+(?:\s+[A-Za-z0-9]+-\d+)*)(?:\s+จ่าย(\S+)\s+(\d+(?:\.\d+)?))?$/);
    // [name] เก่า  (ไม่ระบุ CODE-QTY — แสดงรายการของค้างรับทั้งหมด)
    var _oldMenu = _msg.match(/^(.+?)\s+เก่า$/);
    // [name] เบิก CODE-QTY [CODE-QTY ...] — บันทึกรับของ ไม่จ่ายเงิน (หลายรายการได้)
    var _withdraw = _msg.match(/^(.+?)\s+เบิก\s+([A-Za-z0-9]+-\d+(?:\s+[A-Za-z0-9]+-\d+)*)$/);
    // [name] เบิกจ่าย CODE-QTY [CODE-QTY ...] — บันทึกรับของ + จ่ายเงินแล้ว ยังไม่เปิดบิล (หลายรายการได้)
    var _withdrawPaid = _msg.match(/^(.+?)\s+เบิกจ่าย\s+([A-Za-z0-9]+-\d+(?:\s+[A-Za-z0-9]+-\d+)*)$/);
    // [name] เบิกจ่าย CODE-QTY [CODE-QTY ...] จ่าย AMOUNT — บันทึกรับของ + จ่ายเงินบางส่วน (ไม่ครบยอด)
    var _withdrawPartialPay = _msg.match(/^(.+?)\s+เบิกจ่าย\s+([A-Za-z0-9]+-\d+(?:\s+[A-Za-z0-9]+-\d+)*)\s+จ่าย\s+(\d+(?:\.\d+)?)$/);
    // [name] จ่าย[bill] amount  (bill ไม่ระบุได้ — ระบบจะให้เลือกจากบิลค้างจ่ายของลูกค้า)
    var _pay = _msg.match(/^(.+?)\s+จ่าย(\S*)\s+(\d+(?:\.\d+)?)$/);
    // [name] จ่าย  (ไม่ระบุยอด/บิล — แสดงบิลค้างจ่ายทั้งหมดให้เลือก)
    var _payMenu = _msg.match(/^(.+?)\s+จ่าย$/);
    // [name] จ่ายบางส่วน[bill] — ปุ่มจากเมนู แจ้งวิธีพิมพ์จ่ายบางส่วน
    var _payPartial = _msg.match(/^(.+?)\s+จ่ายบางส่วน([A-Za-z0-9\-]+)$/);
    // [name] จ่าย[bill]  (เลือกบิลแล้ว ยังไม่ระบุยอด — เลือกจ่ายเต็ม/บางส่วน)
    var _payBillMenu = _msg.match(/^(.+?)\s+จ่าย([A-Za-z0-9\-]+)$/);

    if (_msg.toLowerCase() === 'คู่มือ' || _msg.toLowerCase() === 'help') { handleManual(replyToken, _staffTag); return; }
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
    if (_chk) { handleCustomerByName(_chk[1].trim(), replyToken); return; }

    if (_old) {
      var _oldItems = _old[2].trim().split(/\s+/).map(function(tok) {
        var p = tok.split('-');
        return { code: p[0].toUpperCase(), qty: parseInt(p[1]) };
      });
      handleOldGoods(
        _old[1].trim(), _oldItems,
        _old[4] ? parseFloat(_old[4]) : 0, _old[3] || null, replyToken, _confirmed, _staffTag
      );
      return;
    }
    if (_oldMenu) { handleOldGoodsMenu(_oldMenu[1].trim(), replyToken, _staffTag); return; }
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
    if (_pay) { handlePayment(_pay[1].trim(), _pay[2], parseFloat(_pay[3]), replyToken, _confirmed, _staffTag); return; }
    if (_payMenu) { handlePaymentMenu(_payMenu[1].trim(), replyToken, _staffTag); return; }
    if (_payPartial) { handlePayPartialPrompt(_payPartial[1].trim(), _payPartial[2], replyToken, _staffTag, event.source.userId); return; }
    if (_payBillMenu) { handlePayBillMenu(_payBillMenu[1].trim(), _payBillMenu[2], replyToken, _staffTag); return; }
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
  // รายชื่อพื้นที่ห่างไกล 3 ชุดนี้ต้องตรงกับ flash_zones.py (FLASH_ZONES ที่ zone=="remote")
  // และ SPX_REMOTE ในแอปหลักเป๊ะๆ — คำนวณด้วย set difference จาก 2 ลิสต์นั้นตรงๆ (อย่าเดา)
  // อัปเดตล่าสุด 2026-07-12 หลัง audit ค่าส่งทุกขนส่งในแอปหลัก แก้บั๊กที่ SPX เคยใช้โซนของ
  // Flash ผิด (เช่น 63150 ท่าสองยาง ไม่ใช่พื้นที่ห่างไกลของ SPX ทั้งที่เป็นของ Flash)
  // หมายเหตุ: บางรหัส (81120,81150,81210,84280,84360) เป็น "SPX ห่างไกล" ซ้อนกับ
  // "Flash ท่องเที่ยว/เกาะ" พร้อมกัน — โค้ดด้านล่างเช็ค remote ก่อน tourist เสมอ ทำให้เคส
  // เหล่านี้ได้ค่า remote +50 แม้จะจบที่ Flash (ซึ่งจริงๆ ควรได้ค่าท่องเที่ยวแบบขั้นบันไดแทน)
  // เป็นข้อจำกัดเดิมของโมเดลนี้ที่ไม่รู้ล่วงหน้าว่าจะจบที่ขนส่งไหน ยังไม่แก้ในรอบนี้
  var bothRemote = ["50260","50270","50310","50350","55220","58110","58120","58130","58140","58150","63170","67260","71180","71240","94120","94230","95110","95130","95150","95160","95170","96110","96120","96130","96140","96150","96160","96190","96210","96220"];
  var flashOnlyRemote = ["55130","63150","82150","94000","94110","94130","94140","94150","94160","94170","94180","94190","94220","95000","95120","95140","96000","96170","96180"];
  var spxOnlyRemote = ["20120","23170","50160","50240","50250","51160","52160","52180","52230","56160","57170","57180","57260","57310","57340","58000","81120","81150","81210","82160","84280","84360","84370"];
  var touristIslandZips = ["20120","20150","21160","23000","23170","81000","81130","81150","81180","81210","82000","82160","84140","84220","84280","84310","84320","84330","84360","85000","91000","92110","92120"];
  var touristZips = ["20260","81120","82110","82130","82140","82190","82220","83000","83100","83110","83120","83130","83150"];

  var lang = 'none', isCOD = rawMsg.toLowerCase().includes('cod'), userMsg = rawMsg.toLowerCase();
  if (userMsg.startsWith('th ')) { lang = 'th'; userMsg = userMsg.replace('th ', '').trim(); }
  else if (userMsg.startsWith('mm ')) { lang = 'mm'; userMsg = userMsg.replace('mm ', '').trim(); }

  var pData = _getProducts();
  var tokens = userMsg.split(/[\s\n]+/);

  var orderMap = {}, manualShipPrice = -1, isAutoShip = false, targetZip = '';
  for (var ti = 0; ti < tokens.length; ti++) {
    var token = tokens[ti];
    if (token.includes('-')) {
      var parts = token.split('-'), code = parts[0].trim().toUpperCase(), val = parts[1].trim();
      if (code === 'SH') {
        if (val.startsWith('kg')) {
          isAutoShip = true;
          var z = val.replace('kg', '');
          if (z.length !== 5 && ti + 1 < tokens.length && /^\d{5}$/.test(tokens[ti + 1])) {
            // รองรับ "SH-kg 12170" (เว้นวรรค) เช่นเดียวกับ "SH-kg12170"
            z = tokens[ti + 1];
            ti++;
          }
          if (z.length === 5) targetZip = z;
        }
        else { manualShipPrice = parseFloat(val) || 0; }
      } else { orderMap[code] = (orderMap[code] || 0) + (parseFloat(val) || 0); }
    }
  }

  var totalPrice = 0, totalPV = 0, productWeight = 0, stockPool = [], detailText = '';
  Object.keys(orderMap).forEach(function(code) {
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

  if (detailText === '' && translatedNote !== '') { sendReply(replyToken, '🇲🇲 Message:\n' + rawMsg + translatedNote); return; }
  else if (detailText === '') return;

  var totalWeightKg = productWeight + 0.5;
  var summaryHeader = lang === 'th' ? '📜 สรุปยอดคำสั่งซื้อ\n\n' : (lang === 'mm' ? '📜 အော်ဒါအကျဉ်းချုပ်\n\n' : '📝 รายการสินค้า\n\n');
  var summaryText = summaryHeader + detailText + '\n';

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
      if (bothRemote.includes(targetZip)) { extra = 50; feeNote = ' (ห่างไกล ' + targetZip + ' [Flash+SPX] +50)'; }
      else if (flashOnlyRemote.includes(targetZip)) { extra = 50; feeNote = ' (ห่างไกล ' + targetZip + ' [Flash] +50)'; }
      else if (spxOnlyRemote.includes(targetZip)) { extra = 50; feeNote = ' (ห่างไกล ' + targetZip + ' [SPX] +50)'; }
      else if (touristIslandZips.includes(targetZip)) { extra = totalWeightKg <= 7 ? 60 : (totalWeightKg <= 20 ? 130 : 230); feeNote = ' (ท่องเที่ยว+เกาะ ' + targetZip + ' [SPX] +' + extra + ')'; }
      else if (touristZips.includes(targetZip)) { extra = totalWeightKg <= 7 ? 30 : (totalWeightKg <= 20 ? 100 : 200); feeNote = ' (ท่องเที่ยว ' + targetZip + ' [SPX] +' + extra + ')'; }
    }
    shipFinal = shipBase + extra;
  } else if (manualShipPrice !== -1) { hasShipping = true; shipFinal = manualShipPrice; feeNote = ' (ระบุเอง)'; }

  var codFee = isCOD ? Math.ceil((totalPrice + shipFinal) * 0.0321) : 0;
  var finalPay = totalPrice + shipFinal + codFee;

  summaryText += '✨ ' + totalPV.toLocaleString() + ' PV | ⚖️ ' + totalWeightKg.toFixed(2) + ' kg\n\n';
  summaryText += (lang === 'mm' ? '💵 ပစ္စည်းဖိုး: ฿' : '💵 สินค้า: ฿') + totalPrice.toLocaleString() + '\n';
  if (hasShipping) summaryText += (lang === 'mm' ? '🚚 ပို့ခ: ฿' : '🚚 ค่าส่ง: ฿') + shipFinal.toLocaleString() + feeNote + '\n';
  if (isCOD) summaryText += '➕ COD (3%): ฿' + codFee.toLocaleString() + '\n';

  var calcFormula = totalPrice.toString();
  if (shipFinal > 0) calcFormula += ' + ' + shipFinal;
  if (codFee > 0) calcFormula += ' + ' + codFee;
  summaryText += '\n' + calcFormula + ' = ' + finalPay.toLocaleString() + '\n';
  summaryText += '💰 ' + (isCOD ? (lang === 'mm' ? 'ပစ္စည်းရောက်ငွေချေ: ' : 'ยอดปลายทาง: ') : (lang === 'mm' ? 'စုစုပေါင်းကျသင့်ငွေ: ' : 'ยอดโอนสุทธิ: ')) + '฿' + finalPay.toLocaleString() + '\n';

  if (!hasShipping) summaryText += '\nပို့ဆောင်ခ သီးသန့်ဖြစ်သည်။\nราคานี้ยังไม่รวมค่าจัดส่ง';
  else if (!isCOD && lang !== 'none') summaryText += '\n🏦 SCB 165-2716485\n👤 Zhulian Sathupradit New Agency';

  sendReply(replyToken, summaryText + translatedNote);
  } catch (err) {
    // DEBUG ชั่วคราว — เก็บ error ไว้ดูผ่าน ?debug=1
    var _dbgKey = SUPABASE_KEY || '';
    var _dbgTok = CHANNEL_ACCESS_TOKEN || '';
    _scriptProps.setProperty('LAST_ERROR',
      Utilities.formatDate(new Date(), 'Asia/Bangkok', 'yyyy-MM-dd HH:mm:ss') + ' | ' +
      String(err) + (err.stack ? (' | STACK: ' + err.stack) : '') +
      ' | SUPABASE_URL=' + SUPABASE_URL +
      ' | SUPABASE_KEY len=' + _dbgKey.length + ' last6=' + _dbgKey.slice(-6) +
      ' | CHANNEL_ACCESS_TOKEN len=' + _dbgTok.length + ' last6=' + _dbgTok.slice(-6) +
      ' | replyToken=' + (typeof replyToken !== 'undefined' ? replyToken : 'n/a'));
  }
}

// ─── sendReply ────────────────────────────────────────────────────────────────

function sendReply(token, text, imageUrl) {
  var messages = [{ type: 'text', text: text }];
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
  // คะแนนที่ยังไม่เปิดบิล
  var unbilledTxns = _sbGet(
    '/rest/v1/transactions?customer_id=eq.' + custId
    + '&bill_status=eq.' + encodeURIComponent('ยังไม่เปิดบิล')
    + '&select=id,qty,points_per_unit'
  ) || [];
  var unbilledPV = unbilledTxns.reduce(function(s, t) {
    return s + parseFloat(t.points_per_unit || 0) * t.qty;
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
  msg += '  • ' + tag + ' check [ชื่อ]  — ดูยอดค้างจ่าย/ค้างรับของลูกค้า\n\n';

  msg += '📦 รับของเก่าที่ค้างส่ง\n';
  msg += '  • ' + tag + ' [ชื่อ] เก่า  — แสดงรายการของค้างรับทั้งหมด แยกตามบิล\n';
  msg += '  • ' + tag + ' [ชื่อ] เก่า CODE-จำนวน CODE-จำนวน ...  — บันทึกรับของ (หลายรายการได้)\n';
  msg += '  • ' + tag + ' [ชื่อ] เก่า CODE-จำนวน ... จ่ายเลขบิล จำนวนเงิน  — รับของ+จ่ายเงินพร้อมกัน\n\n';

  msg += '💰 รับเงิน/เก็บเงินค้างจ่าย\n';
  msg += '  • ' + tag + ' [ชื่อ] จ่าย  — แสดงบิลค้างจ่ายทั้งหมดให้เลือก\n';
  msg += '  • ' + tag + ' [ชื่อ] จ่ายเลขบิล จำนวนเงิน  — บันทึกรับเงิน (จ่ายบางส่วนได้)\n\n';

  msg += '🆕 รับของใหม่ (ยังไม่เปิดบิล)\n';
  msg += '  • ' + tag + ' [ชื่อ] เบิก CODE-จำนวน CODE-จำนวน ...  — รับของ ค้างจ่าย\n';
  msg += '  • ' + tag + ' [ชื่อ] เบิกจ่าย CODE-จำนวน CODE-จำนวน ...  — รับของ + จ่ายเงินแล้ว\n';
  msg += '  • ' + tag + ' [ชื่อ] เบิกจ่าย CODE-จำนวน CODE-จำนวน ... จ่าย จำนวนเงิน  — รับของ + จ่ายบางส่วน\n\n';

  msg += '✅ ทุกคำสั่งบันทึกจริง จะมีปุ่ม "ยืนยันบันทึก" ให้กดก่อนเสมอ\n';
  msg += '─────────────────\n';
  msg += '👤 คำสั่งสำหรับลูกค้า (ไม่ต้องมี #tag)\n';
  msg += '  • สมัคร เบอร์โทร  — ผูกไลน์กับบัญชีลูกค้า\n';
  msg += '  • ยอด / สรุปยอด  — ดูยอดค้างจ่าย/ค้างรับของตัวเอง\n';
  msg += '  • qr  — ดูข้อมูลโอนเงิน\n';
  msg += '  • คำนวณออเดอร์ เช่น CODE-จำนวน SH-kgรหัสไปรษณีย์ cod plan ... — คำนวณราคา/PV/ค่าส่ง\n';

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

// ─── _getOpenBills — รายการบิลค้างจ่ายของลูกค้า [{bill_no, outstanding}] ──────

function _getOpenBills(customerId) {
  var txns = _sbGet(
    '/rest/v1/transactions?customer_id=eq.' + customerId
    + '&pay_status=neq.จ่ายแล้ว&bill_no=not.is.null'
    + '&select=id,bill_no,total_amount'
  ) || [];
  if (txns.length === 0) return [];

  var txnIds = txns.map(function(t) { return t.id; });
  var events = _sbGet(
    '/rest/v1/partial_events?transaction_id=in.(' + txnIds.join(',') + ')&select=transaction_id,amount_paid'
  ) || [];
  var paidMap = {};
  events.forEach(function(e) {
    paidMap[e.transaction_id] = (paidMap[e.transaction_id] || 0) + parseFloat(e.amount_paid || 0);
  });

  var billMap = {};
  txns.forEach(function(t) {
    var outstanding = parseFloat(t.total_amount) - (paidMap[t.id] || 0);
    if (outstanding <= 0.01) return;
    billMap[t.bill_no] = (billMap[t.bill_no] || 0) + outstanding;
  });

  return Object.keys(billMap).map(function(b) { return { bill_no: b, outstanding: billMap[b] }; });
}

// ─── check [name] — เจ้าของร้านดูยอดค้าง ────────────────────────────────────

function handleCustomerByName(name, replyToken) {
  var cust = findOneCustomer(name, replyToken, 'check {name}');
  if (!cust) return;
  buildAndSendSummary(cust.id, cust.name, replyToken);
}

// ─── [name] จ่าย (ไม่ระบุยอด/บิล) — แสดงบิลค้างจ่ายให้เลือก ──────────────────

function handlePaymentMenu(name, replyToken, staffTag) {
  var cust = findOneCustomer(name, replyToken, '#' + staffTag + ' {name} จ่าย');
  if (!cust) return;

  var openBills = _getOpenBills(cust.id);
  if (openBills.length === 0) {
    sendReply(replyToken, '✅ คุณ' + cust.name + ' ไม่มียอดค้างจ่ายแล้วค่ะ');
    return;
  }

  if (openBills.length <= 13) {
    var billItems = openBills.map(function(b) {
      return {
        type: 'action',
        action: {
          type: 'message',
          label: (b.bill_no + ' ฿' + numFmt(b.outstanding)).substring(0, 20),
          text: '#' + staffTag + ' ' + cust.name + ' จ่าย' + b.bill_no
        }
      };
    });
    sendQuickReply(replyToken, '🧾 คุณ' + cust.name + ' มียอดค้างจ่าย เลือกบิลที่จะจ่ายค่ะ:', billItems);
  } else {
    var billNames = openBills.slice(0, 13).map(function(b) { return b.bill_no + ' (฿' + numFmt(b.outstanding) + ')'; }).join(', ');
    sendReply(replyToken, '🧾 คุณ' + cust.name + ' มีบิลค้างจ่าย: ' + billNames + ' ...\nพิมพ์ #' + staffTag + ' ' + cust.name + ' จ่าย[เลขบิล] [จำนวนเงิน] ค่ะ');
  }
}

// ─── [name] จ่าย[bill] (เลือกบิลแล้ว ไม่ระบุยอด) — เลือกจ่ายเต็ม/บางส่วน ──────

function handlePayBillMenu(name, billNo, replyToken, staffTag) {
  var cust = findOneCustomer(name, replyToken, '#' + staffTag + ' {name} จ่าย' + billNo);
  if (!cust) return;

  var openBills = _getOpenBills(cust.id);
  var bill = openBills.filter(function(b) { return b.bill_no === billNo; })[0];
  if (!bill) {
    sendReply(replyToken, '⚠️ ไม่พบยอดค้างของบิล ' + billNo + ' หรือจ่ายครบแล้วค่ะ');
    return;
  }

  var amt = Math.round(bill.outstanding);
  sendQuickReply(replyToken, '🧾 บิล ' + billNo + ' ค้างจ่าย ฿' + numFmt(bill.outstanding) + ' ของคุณ' + cust.name + ' — จ่ายเต็มหรือบางส่วนคะ:', [
    {
      type: 'action',
      action: {
        type: 'message',
        label: ('✅ จ่ายเต็ม ฿' + numFmt(bill.outstanding)).substring(0, 20),
        text: '#' + staffTag + ' ' + cust.name + ' จ่าย' + billNo + ' ' + amt
      }
    },
    {
      type: 'action',
      action: {
        type: 'message',
        label: '✏️ จ่ายบางส่วน',
        text: '#' + staffTag + ' ' + cust.name + ' จ่ายบางส่วน' + billNo
      }
    }
  ]);
}

// ─── [name] จ่ายบางส่วน[bill] — ปุ่มจากเมนู แจ้งวิธีพิมพ์จ่ายบางส่วน ──────────

function handlePayPartialPrompt(name, billNo, replyToken, staffTag, userId) {
  var cust = findOneCustomer(name, replyToken, '#' + staffTag + ' {name} จ่ายบางส่วน' + billNo);
  if (!cust) return;

  var openBills = _getOpenBills(cust.id);
  var bill = openBills.filter(function(b) { return b.bill_no === billNo; })[0];
  if (!bill) {
    sendReply(replyToken, '⚠️ ไม่พบยอดค้างของบิล ' + billNo + ' หรือจ่ายครบแล้วค่ะ');
    return;
  }

  CacheService.getScriptCache().put('pp_' + userId,
    JSON.stringify({ name: cust.name, billNo: billNo, staffTag: staffTag }), 300);
  sendReply(replyToken, '✏️ พิมพ์จำนวนเงินที่จะจ่ายค่ะ (ยอดค้างบิล ' + billNo + ' ฿' + numFmt(bill.outstanding) + ')');
}

// ─── [name] จ่าย[bill] amount — บันทึกรับเงิน ────────────────────────────────

function handlePayment(name, billNo, payAmount, replyToken, confirmed, staffTag) {
  var cust = findOneCustomer(name, replyToken, '#' + staffTag + ' {name} จ่าย' + billNo + ' ' + payAmount);
  if (!cust) return;

  // ไม่ได้ระบุเลขที่บิล — ให้เลือกจากบิลที่ยังค้างจ่ายของลูกค้าคนนี้
  if (!billNo) {
    var openBills = _getOpenBills(cust.id);
    if (openBills.length === 0) {
      sendReply(replyToken, '✅ คุณ' + cust.name + ' ไม่มียอดค้างจ่ายแล้วค่ะ');
      return;
    }
    if (openBills.length === 1) {
      billNo = openBills[0].bill_no;
    } else if (openBills.length <= 13) {
      var billItems = openBills.map(function(b) {
        return {
          type: 'action',
          action: {
            type: 'message',
            label: (b.bill_no + ' (฿' + numFmt(b.outstanding) + ')').substring(0, 20),
            text: '#' + staffTag + ' ' + cust.name + ' จ่าย' + b.bill_no + ' ' + payAmount
          }
        };
      });
      sendQuickReply(replyToken, '🧾 คุณ' + cust.name + ' มีบิลค้างจ่ายหลายบิล เลือกบิลที่จะจ่ายค่ะ:', billItems);
      return;
    } else {
      var billNames = openBills.slice(0, 13).map(function(b) { return b.bill_no; }).join(', ');
      sendReply(replyToken, '🧾 คุณ' + cust.name + ' มีบิลค้างจ่าย: ' + billNames + ' ...\nพิมพ์ระบุเลขที่บิลด้วยค่ะ');
      return;
    }
  }

  var txns = _sbGet(
    '/rest/v1/transactions?customer_id=eq.' + cust.id
    + '&bill_no=eq.' + encodeURIComponent(billNo)
    + '&pay_status=neq.จ่ายแล้ว'
    + '&select=id,product_id,product_name,qty,total_amount,initial_qty_received'
    + '&order=date.asc'
  ) || [];

  if (txns.length === 0) {
    sendReply(replyToken, '❌ ไม่พบยอดค้างในบิล ' + billNo + ' ของคุณ' + cust.name);
    return;
  }

  var txnIds = txns.map(function(t) { return t.id; });
  var events = _sbGet(
    '/rest/v1/partial_events?transaction_id=in.(' + txnIds.join(',') + ')&select=transaction_id,amount_paid'
  ) || [];

  var paidMap = {};
  events.forEach(function(e) {
    paidMap[e.transaction_id] = (paidMap[e.transaction_id] || 0) + parseFloat(e.amount_paid || 0);
  });

  var outList = txns.map(function(t) {
    return { txn: t, outstanding: parseFloat(t.total_amount) - (paidMap[t.id] || 0) };
  }).filter(function(x) { return x.outstanding > 0.01; });

  var totalOwed = outList.reduce(function(s, x) { return s + x.outstanding; }, 0);

  var overNote = '';
  var actualPay = payAmount;
  if (payAmount > totalOwed + 0.01) {
    overNote = '⚠️ ยอดค้างมีเพียง ฿' + numFmt(totalOwed) + ' บันทึกเฉพาะส่วนที่ค้างนะคะ\n';
    actualPay = totalOwed;
  }

  var remaining = actualPay, confirmLines = '', today = _today(), plannedWrites = [];
  outList.forEach(function(x) {
    if (remaining < 0.01) return;
    var applyAmt = Math.min(remaining, x.outstanding);
    remaining -= applyAmt;
    var newPaid = (paidMap[x.txn.id] || 0) + applyAmt;
    var fullyPaid = newPaid >= parseFloat(x.txn.total_amount) - 0.01;

    plannedWrites.push({ txnId: x.txn.id, applyAmt: applyAmt, fullyPaid: fullyPaid });

    var status = fullyPaid ? '(ชำระครบ ✓)' : '(ยังค้าง ฿' + numFmt(x.outstanding - applyAmt) + ')';
    confirmLines += '💰 [' + (x.txn.product_id || '') + '] ' + x.txn.product_name + ': ฿' + numFmt(applyAmt) + ' ' + status + '\n';
  });

  if (!confirmed) {
    var preview = overNote;
    preview += '📋 ตรวจสอบก่อนบันทึก: รับเงิน ฿' + numFmt(actualPay) + ' จากคุณ' + cust.name + ' (บิล ' + billNo + ')\n';
    preview += '─────────────────\n' + confirmLines + '─────────────────\n';
    preview += '💰 ยอดค้างหลังจ่าย: ฿' + numFmt(Math.max(0, totalOwed - actualPay)) + '\n';
    sendQuickReply(replyToken, preview, [{
      type: 'action',
      action: { type: 'message', label: '✅ ยืนยันบันทึก', text: 'ยืนยัน #' + staffTag + ' ' + cust.name + ' จ่าย' + billNo + ' ' + payAmount }
    }, {
      type: 'action',
      action: { type: 'message', label: '❌ ยกเลิก', text: 'ยกเลิก' }
    }]);
    return;
  }

  plannedWrites.forEach(function(w) {
    _sbPost('partial_events', {
      id: Utilities.getUuid(), date: today,
      transaction_id: w.txnId,
      amount_paid: w.applyAmt, qty_received: 0, event_type: 'จ่ายเงิน',
      notes: '#' + staffTag
    });
    if (w.fullyPaid) _sbPatch('/rest/v1/transactions?id=eq.' + w.txnId, { pay_status: 'จ่ายแล้ว' });
  });

  var msg = overNote;
  msg += '✅ บันทึกรับเงิน ฿' + numFmt(actualPay) + ' จากคุณ' + cust.name + ' (บิล ' + billNo + ')\n';
  msg += '─────────────────\n' + confirmLines + '─────────────────\n';
  msg += '💰 ยอดค้างหลังจ่าย: ฿' + numFmt(Math.max(0, totalOwed - actualPay)) + '\n';
  sendReply(replyToken, msg);
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

// ─── [name] เก่า (ไม่ระบุ CODE-QTY) — แสดงรายการของค้างรับทั้งหมด ───────────

function handleOldGoodsMenu(name, replyToken, staffTag) {
  var cust = findOneCustomer(name, replyToken, '#' + staffTag + ' {name} เก่า');
  if (!cust) return;

  var cutoff = new Date();
  cutoff.setMonth(cutoff.getMonth() - 6);
  var cutoffStr = Utilities.formatDate(cutoff, 'Asia/Bangkok', 'yyyy-MM-dd');
  var txns = _sbGet(
    '/rest/v1/transactions?customer_id=eq.' + cust.id
    + '&date=gte.' + cutoffStr
    + '&select=id,product_id,product_name,qty,initial_qty_received,bill_no'
    + '&order=bill_no.desc&limit=50'
  ) || [];

  var txnIds = txns.map(function(t) { return t.id; });
  var events = txnIds.length > 0 ? (_sbGet(
    '/rest/v1/partial_events?transaction_id=in.(' + txnIds.join(',') + ')&select=transaction_id,qty_received'
  ) || []) : [];
  var receivedMap = {};
  events.forEach(function(e) {
    receivedMap[e.transaction_id] = (receivedMap[e.transaction_id] || 0) + parseInt(e.qty_received || 0);
  });

  var billMap = {}, billOrder = [], hasAny = false;
  txns.forEach(function(t) {
    var received = (t.initial_qty_received || 0) + (receivedMap[t.id] || 0);
    var remaining = t.qty - received;
    if (remaining <= 0) return;
    hasAny = true;
    var bill = t.bill_no || '(ไม่มีเลขบิล)';
    if (!billMap[bill]) { billMap[bill] = []; billOrder.push(bill); }
    billMap[bill].push({ code: t.product_id, name: t.product_name, remaining: remaining });
  });

  if (!hasAny) {
    sendReply(replyToken, '✅ คุณ' + cust.name + ' ไม่มีของค้างรับแล้วค่ะ');
    return;
  }

  var msg = '📦 ของค้างรับของคุณ' + cust.name + '\n─────────────────\n';
  billOrder.forEach(function(bill) {
    msg += '📋 บิล ' + bill + '\n';
    billMap[bill].forEach(function(item) {
      msg += '  ▫️ [' + (item.code || '') + '] ' + item.name + ' — ค้างรับ ' + item.remaining + ' ชิ้น\n';
    });
  });
  msg += '─────────────────\n';
  msg += '👉 พิมพ์ #' + staffTag + ' ' + cust.name + ' เก่า [CODE]-[จำนวน] เพื่อบันทึกรับของค่ะ';

  sendReply(replyToken, msg);
}

// ─── [name] เก่า CODE-QTY [CODE-QTY ...] (จ่าย[bill] amount)? — บันทึกรับของ(+จ่าย) ────────

function handleOldGoods(name, items, payAmount, billNo, replyToken, confirmed, staffTag) {
  var _resendSuffix = 'เก่า ' + items.map(function(it) { return it.code + '-' + it.qty; }).join(' ')
    + (payAmount > 0 ? ' จ่าย' + billNo + ' ' + payAmount : '');
  var cust = findOneCustomer(name, replyToken, '#' + staffTag + ' {name} ' + _resendSuffix);
  if (!cust) return;

  var results = [], notFound = [];

  items.forEach(function(it) {
    var txnUrl = '/rest/v1/transactions?customer_id=eq.' + cust.id
      + '&product_id=eq.' + encodeURIComponent(it.code)
      + '&select=id,product_name,qty,total_amount,pay_status,initial_qty_received,bill_no'
      + '&order=date.asc';
    if (billNo) txnUrl += '&bill_no=eq.' + encodeURIComponent(billNo);
    var txns = _sbGet(txnUrl) || [];
    if (txns.length === 0) { notFound.push(it.code); return; }

    var txnIds = txns.map(function(t) { return t.id; });
    var events = _sbGet(
      '/rest/v1/partial_events?transaction_id=in.(' + txnIds.join(',') + ')&select=transaction_id,amount_paid,qty_received'
    ) || [];
    var paidMap = {}, receivedMap = {};
    events.forEach(function(e) {
      paidMap[e.transaction_id] = (paidMap[e.transaction_id] || 0) + parseFloat(e.amount_paid || 0);
      receivedMap[e.transaction_id] = (receivedMap[e.transaction_id] || 0) + parseInt(e.qty_received || 0);
    });

    // หา transaction แรกที่ยังมีของค้างรับ
    var target = null;
    for (var i = 0; i < txns.length; i++) {
      var t = txns[i];
      var totalReceived = (t.initial_qty_received || 0) + (receivedMap[t.id] || 0);
      var pendingQty = t.qty - totalReceived;
      if (pendingQty > 0) { target = { txn: t, pendingQty: pendingQty, paid: paidMap[t.id] || 0, totalReceived: totalReceived }; break; }
    }
    // ไม่มีของค้างรับแล้ว แต่ยังค้างจ่าย (เช่น มาจาก เบิก ที่รับของครบแล้ว) → ให้บันทึกจ่ายเงินได้
    if (!target) {
      for (var j = 0; j < txns.length; j++) {
        var tj = txns[j];
        if (tj.pay_status !== 'จ่ายแล้ว') {
          target = { txn: tj, pendingQty: 0, paid: paidMap[tj.id] || 0, totalReceived: (tj.initial_qty_received || 0) + (receivedMap[tj.id] || 0) };
          break;
        }
      }
    }
    if (!target) { notFound.push(it.code); return; }

    results.push({ code: it.code, requestedQty: it.qty, target: target, actualQty: Math.min(it.qty, target.pendingQty) });
  });

  if (results.length === 0) {
    sendReply(replyToken, '❌ ไม่พบรายการ/ของค้างรับ [' + items.map(function(it) { return it.code; }).join(', ') + '] ของคุณ' + cust.name);
    return;
  }

  // เงินที่จ่ายมา (ถ้ามี) จะบันทึกไว้กับรายการสุดท้าย
  var payTarget = results[results.length - 1].target;
  var existingPaid = payTarget.paid;
  var maxPay = parseFloat(payTarget.txn.total_amount) - existingPaid;
  var applyPay = payAmount > 0 ? Math.min(payAmount, maxPay) : 0;
  var newPaid = existingPaid + applyPay;
  var fullyPaid = newPaid >= parseFloat(payTarget.txn.total_amount) - 0.01;

  var noteLines = '';
  if (notFound.length) noteLines += '⚠️ ไม่พบ/ไม่มีของค้างรับ: ' + notFound.join(', ') + '\n';
  results.forEach(function(r) {
    if (r.actualQty < r.requestedQty) {
      noteLines += '⚠️ [' + r.code + '] ค้างรับมีเพียง ' + r.target.pendingQty + ' ชิ้น บันทึก ' + r.actualQty + ' ชิ้น\n';
    }
  });
  if (payAmount > 0 && applyPay < payAmount) {
    noteLines += '⚠️ ยอดค้างในรายการนี้มีเพียง ฿' + numFmt(maxPay) + ' บันทึกเฉพาะส่วนที่ค้างนะคะ\n';
  }

  var msg = noteLines + (confirmed ? '✅ บันทึกรับของ' : '📋 ตรวจสอบก่อนบันทึก:') + ' คุณ' + cust.name + '\n';
  msg += '─────────────────\n';
  results.forEach(function(r) {
    var t = r.target.txn;
    var billInfo = t.bill_no ? ' (บิล ' + t.bill_no + ')' : '';
    var pendingAfter = t.qty - (r.target.totalReceived + r.actualQty);
    msg += '📦 [' + r.code + '] ' + t.product_name + billInfo + '\n';
    if (r.actualQty > 0) {
      msg += '   รับ ' + r.actualQty + ' ชิ้น | ค้างรับเหลือ ' + pendingAfter + ' ชิ้น\n';
    } else {
      msg += '   (ไม่มีของค้างรับ)\n';
    }
  });
  if (applyPay > 0) {
    var payStatus = fullyPaid ? '(ชำระครบ ✓)' : '(ยังค้าง ฿' + numFmt(parseFloat(payTarget.txn.total_amount) - newPaid) + ')';
    msg += '💰 รับเงิน ฿' + numFmt(applyPay) + ' ' + payStatus + '\n';
  }
  msg += '─────────────────\n';

  if (!confirmed) {
    sendQuickReply(replyToken, msg, [{
      type: 'action',
      action: { type: 'message', label: '✅ ยืนยันบันทึก', text: 'ยืนยัน #' + staffTag + ' ' + cust.name + ' ' + _resendSuffix }
    }, {
      type: 'action',
      action: { type: 'message', label: '❌ ยกเลิก', text: 'ยกเลิก' }
    }]);
    return;
  }

  results.forEach(function(r, idx) {
    var isPayTarget = (idx === results.length - 1);
    var pay = isPayTarget ? applyPay : 0;
    if (r.actualQty === 0 && pay === 0) return;
    _sbPost('partial_events', {
      id: Utilities.getUuid(), date: _today(),
      transaction_id: r.target.txn.id,
      qty_received: r.actualQty, amount_paid: pay,
      event_type: r.actualQty > 0 ? (pay > 0 ? 'ทั้งคู่' : 'รับของ') : 'จ่ายเงิน',
      notes: '#' + staffTag
    });
  });
  if (fullyPaid && applyPay > 0) _sbPatch('/rest/v1/transactions?id=eq.' + payTarget.txn.id, { pay_status: 'จ่ายแล้ว' });

  sendReply(replyToken, msg);
}

// ─── doGet — product list ─────────────────────────────────────────────────────

function doGet(e) {
  // DEBUG ชั่วคราว — เปิด URL ของ deployment ต่อท้ายด้วย ?debug=1 เพื่อดู error ล่าสุด
  if (e.parameter && e.parameter.debug) {
    return ContentService.createTextOutput(_scriptProps.getProperty('LAST_ERROR') || '(no error recorded)');
  }
  var products = _getProducts().map(function(p) {
    return { code: p[0].toUpperCase(), nameTH: p[1], nameMM: p[2], price: p[3], pv: p[4] };
  });
  return ContentService.createTextOutput(JSON.stringify(products))
    .setMimeType(ContentService.MimeType.JSON);
}
