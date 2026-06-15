"""UI สำหรับแท็บการเงิน — แยกจาก app.py"""
import io
import uuid

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from datetime import date

import database as db

_THAI_MONTHS = ["", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
                "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]


def _parse_date(s):
    if not s:
        return date.today()
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:
        return date.today()


def _thai_baht_text(amount: float) -> str:
    """แปลงจำนวนเงินเป็นข้อความภาษาไทย เช่น 1234.50 -> หนึ่งพันสองร้อยสามสิบสี่บาทห้าสิบสตางค์"""
    _digits = ["ศูนย์", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า"]
    _units = ["", "สิบ", "ร้อย", "พัน", "หมื่น", "แสน"]

    def _read_chunk(num_str: str) -> str:
        result = ""
        n = len(num_str)
        for i, ch in enumerate(num_str):
            d = int(ch)
            if d == 0:
                continue
            pos = n - i - 1
            if pos == 1:
                if d == 1:
                    result += "สิบ"
                elif d == 2:
                    result += "ยี่สิบ"
                else:
                    result += _digits[d] + "สิบ"
            elif pos == 0:
                if d == 1 and n > 1:
                    result += "เอ็ด"
                else:
                    result += _digits[d]
            else:
                result += _digits[d] + _units[pos]
        return result

    amount = round(float(amount) + 1e-9, 2)
    baht = int(amount)
    satang = int(round((amount - baht) * 100))

    if baht == 0:
        baht_text = "ศูนย์"
    else:
        groups = []
        s = str(baht)
        while s:
            groups.append(s[-6:])
            s = s[:-6]
        parts = []
        for i in range(len(groups) - 1, -1, -1):
            g_int = int(groups[i])
            if g_int == 0:
                continue
            text = _read_chunk(str(g_int))
            if i > 0:
                text += "ล้าน"
            parts.append(text)
        baht_text = "".join(parts)

    result = baht_text + "บาท"
    if satang > 0:
        result += _read_chunk(str(satang)) + "สตางค์"
    else:
        result += "ถ้วน"
    return result


def _render_receipt_html(cr: dict, ci: dict, period: str) -> str:
    _year, _month = period.split("-")
    _doc_date = _parse_date(cr.get("receipt_date"))
    _amount = float(cr.get("commission_amount", 0))
    _vat = float(cr.get("vat_claim_amount", 0))
    _grand = _amount + _vat
    _amount_text = _thai_baht_text(_grand)
    _book_no = cr.get("receipt_book_no") or "—"
    _seq = cr.get("receipt_seq")
    _no_text = f"{(int(_year) + 543) % 100}/{int(_seq):03d}" if _seq else "—"
    _desc = f"ค่าคอมมิชชั่นประจำเดือน{_THAI_MONTHS[int(_month)]} {(int(_year) + 543) % 100}"

    _css = """
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Sarabun',sans-serif;background:#eef0f3;padding:24px;color:#1a1a1a}
  .sheet{max-width:720px;margin:0 auto;background:#fff;padding:28px 34px;box-shadow:0 0 14px rgba(0,0,0,.10)}
  .headerflex{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:14px;padding-bottom:12px;border-bottom:2px solid #1a5fb4}
  .headerflex .left{text-align:left;flex:1;min-width:0}
  .headerflex .name-th{font-size:14px;font-weight:700}
  .headerflex .name-en{font-size:11px;color:#555;margin-top:2px}
  .headerflex .addr{font-size:11px;color:#555;margin-top:2px}
  .headerflex .taxid{display:inline-block;border:1px solid #999;border-radius:4px;padding:2px 12px;margin-top:6px;font-size:11px;color:#444}
  .headerflex .right{text-align:right;white-space:nowrap;flex-shrink:0}
  .headerflex .right .th{font-weight:700;font-size:15px;color:#1a5fb4}
  .headerflex .right .en{font-size:11px;color:#1a5fb4;margin-top:2px}
  .headerflex .right .orig{font-size:11px;color:#1a5fb4;margin-top:2px;font-weight:600}
  .headerflex .right .docnos{font-size:12px;margin-top:8px;color:#333}
  .headerflex .right .docnos b{font-weight:700}
  .frombox{border:1px solid #ccc;border-radius:8px;padding:12px;margin-bottom:14px}
  .frombox .row{display:flex;justify-content:space-between;margin-bottom:4px;font-size:12px}
  .frombox .taxid{display:inline-block;border:1px solid #999;border-radius:4px;padding:2px 10px;margin-top:4px;font-size:11px;color:#444}
  table.items{width:100%;border-collapse:collapse;margin-bottom:14px;border:1px solid #999}
  table.items th{padding:10px 8px;font-size:11px;text-align:center;background:#1a5fb4;color:#fff;font-weight:600}
  table.items td{padding:12px 8px;font-size:12px;border-bottom:1px solid #eee;vertical-align:top}
  table.items td.num{text-align:center;color:#888}
  table.items tr.empty-row td{height:34px}
  table.items tr:last-child td{border-bottom:none}
  .bottom{display:flex;gap:18px;margin-bottom:14px;align-items:flex-start}
  .payment{flex:1.2;font-size:12px;padding-top:4px}
  .payment label{display:block;margin-bottom:10px;white-space:nowrap}
  .amountwords{background:#f0f0f0;border-radius:6px;padding:8px 12px;font-size:12px;color:#444;margin-bottom:12px}
  .totals{flex:1;border:1px solid #999;border-radius:8px;overflow:hidden}
  .totals .row{display:flex;justify-content:space-between;padding:8px 12px;border-bottom:1px solid #eee;font-size:12px}
  .totals .row:last-child{border-bottom:none;font-weight:700;background:#eaf2fb;color:#1a5fb4;font-size:13px}
  .signatures{display:flex;justify-content:space-around;text-align:center;font-size:12px;margin-top:60px}
  .signatures .line{margin-bottom:8px;border-top:1px dotted #999;padding-top:36px;min-width:200px}
  .btn{display:block;margin:0 auto 14px;padding:8px 32px;background:#1a5fb4;color:#fff;
       border:none;border-radius:6px;font-size:13px;cursor:pointer}
  .tip{text-align:center;font-size:11px;color:#888;margin-bottom:10px}
  @media print{
    body{background:#fff;padding:0}
    .sheet{box-shadow:none;max-width:none;padding:0;min-height:267mm;display:flex;flex-direction:column}
    .signatures{margin-top:auto;padding-top:60px}
    .btn,.tip{display:none}
    @page{size:A4;margin:15mm}
  }"""

    _body = f"""
<div class="sheet">
<div class="headerflex">
  <div class="left">
    <div class="name-th">{ci.get('our_name','') or '—'}</div>
    <div class="addr">{ci.get('our_address','') or '—'}</div>
    <div class="addr">{('Tel. ' + ci.get('our_tel')) if ci.get('our_tel') else ''}</div>
    <div class="taxid">เลขประจำตัวผู้เสียภาษี {ci.get('our_tax_id','') or '—'}</div>
  </div>
  <div class="right">
    <div class="th">ใบเสร็จรับเงิน / ใบกำกับภาษี</div>
    <div class="en">Receipt / Tax Invoice</div>
    <div class="orig">ต้นฉบับ / Original</div>
    <div class="docnos">เล่มที่ <b>{_book_no}</b>&nbsp;&nbsp;&nbsp;เลขที่ <b>{_no_text}</b></div>
  </div>
</div>

<div class="frombox">
  <div class="row"><span>ได้รับเงินจาก {ci.get('hq_name','') or '—'}</span><span>วันที่ {_doc_date.day}/{_doc_date.month}/{_doc_date.year+543}</span></div>
  <div class="row"><span>{ci.get('hq_address','') or '—'}</span></div>
  <div class="taxid">เลขประจำตัวผู้เสียภาษี {ci.get('hq_tax_id','') or '—'}</div>
</div>

<table class="items">
  <tr><th style="width:8%">ลำดับ<br>No.</th><th>รายการสินค้า/บริการ<br>Description</th><th style="width:20%">จำนวนเงิน<br>Amount</th></tr>
  <tr><td class="num">1</td><td>{_desc}</td><td style="text-align:right;font-weight:600">{_amount:,.2f}</td></tr>
  <tr class="empty-row"><td colspan="3">&nbsp;</td></tr>
  <tr class="empty-row"><td colspan="3">&nbsp;</td></tr>
</table>

<div class="bottom">
  <div class="payment">
    <div class="amountwords">({_amount_text})</div>
    <label>☐ เงินสด</label>
    <label>☐ เช็ค/ดราฟต์ธนาคาร เลขที่ ............... วันที่ ...............</label>
  </div>
  <div class="totals">
    <div class="row"><span>รวมมูลค่าสินค้า/บริการ<br>SUB TOTAL</span><span>{_amount:,.2f}</span></div>
    <div class="row"><span>ภาษีมูลค่าเพิ่ม 7%<br>VALUE ADDED TAX 7%</span><span>{_vat:,.2f}</span></div>
    <div class="row"><span>จำนวนเงินรวมทั้งสิ้น<br>GRAND TOTAL</span><span>{_grand:,.2f}</span></div>
  </div>
</div>

<div class="signatures">
  <div><div class="line"></div>ผู้รับเงิน / CASHIER<br>วันที่ Date ............/............/............</div>
  <div><div class="line"></div>ผู้จัดการทั่วไป / MANAGER<br>วันที่ Date ............/............/............</div>
</div>
</div>
"""

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{_css}</style></head><body>
<button class="btn" onclick="window.print()">🖨️ พิมพ์</button>
<div class="tip">เคล็ดลับ: ตอนพิมพ์ ให้ปิดตัวเลือก "Headers and footers" ในหน้าตั้งค่าพิมพ์ จะได้ไม่มีวันที่/URL แทรกที่หัว-ท้ายกระดาษ</div>
{_body}
<br><button class="btn" onclick="window.print()">🖨️ พิมพ์</button>
</body></html>"""


def render():
    st.subheader("💵 การเงิน")
    _tab_sales, _tab_wht = st.tabs(["💰 ยอดขาย", "📑 ใบหัก ณ ที่จ่าย (50 ทวิ)"])

    with _tab_sales:
        fin_summary = db.get_finance_summary()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("🚩 ยอดค้างโอน (฿)", f"{fin_summary['outstanding']:,.2f}")
        m2.metric("💰 เงินโอนเกิน (฿)", f"{fin_summary['overpaid']:,.2f}")
        m3.metric("📦 สต๊อก ไม่รวม VAT (฿)", f"{fin_summary['stock']:,.2f}")
        credit_val = fin_summary["credit"]
        m4.metric("🛒 สิทธิ์สั่งของคงเหลือ (฿)", f"{credit_val:,.2f}",
                  delta=None if credit_val >= 0 else "⚠️ เกินวงเงิน")

        st.divider()

        with st.expander("🗓️ เปิดเดือนใหม่ (กรอกครั้งเดียวต้นเดือน)"):
            ob_date  = st.date_input("วันที่เปิดเดือน", value=date.today().replace(day=1), key="ob_date")
            _ob = db.get_finance_entry(str(ob_date)) or {}
            ob_adj = float(_ob.get("adjustment", 0))
            ob1, ob2 = st.columns(2)
            with ob1:
                ob_overpaid = st.number_input("โอนเกินยกมา (฿)", min_value=0.0, step=100.0,
                    value=max(0.0, ob_adj), key=f"ob_over_{ob_date}")
                ob_stock    = st.number_input("สต๊อกยกมา ไม่รวม VAT (฿)", min_value=0.0, step=100.0,
                    value=float(_ob.get("stock_value", 0)), key=f"ob_stock_{ob_date}")
            with ob2:
                ob_owed     = st.number_input("ค้างโอนยกมา (฿)", min_value=0.0, step=100.0,
                    value=max(0.0, -ob_adj), key=f"ob_owed_{ob_date}")
            if st.button("💾 บันทึกยอดยกมา", type="secondary", use_container_width=True, key="ob_save"):
                db.upsert_finance_entry({
                    "id": str(uuid.uuid4()), "entry_date": str(ob_date),
                    "transfer_amount": 0, "registration_fee": 0,
                    "sales_amount": 0, "bv_amount": 0, "po_amount": 0,
                    "stock_value": ob_stock,
                    "adjustment": ob_overpaid - ob_owed,
                    "notes": "ยอดยกมา",
                })
                st.success("✅ บันทึกยอดยกมาแล้ว")
                st.rerun()

        with st.expander("➕ กรอกข้อมูลประจำวัน", expanded=True):
            fin_date = st.date_input("วันที่", value=date.today(), key="fin_date")
            _ex = db.get_finance_entry(str(fin_date)) or {}
            if _ex:
                st.info("📋 มีข้อมูลวันนี้แล้ว — แก้ไขแล้วกด บันทึก เพื่ออัปเดต")
            fc1, fc2 = st.columns(2)
            with fc1:
                fin_transfer = st.number_input("ยอดโอนให้บริษัท (฿)", min_value=0.0, step=100.0, value=float(_ex.get("transfer_amount", 0)), key=f"fin_transfer_{fin_date}")
                fin_sales    = st.number_input("ยอดขาย รวม VAT (฿)",   min_value=0.0, step=100.0, value=float(_ex.get("sales_amount", 0)), key=f"fin_sales_{fin_date}")
                fin_po       = st.number_input("PO สั่งของ ไม่รวม VAT (฿)", min_value=0.0, step=100.0, value=float(_ex.get("po_amount", 0)), key=f"fin_po_{fin_date}")
            with fc2:
                fin_reg      = st.number_input("ค่าสมัคร (฿)",    min_value=0.0, step=100.0, value=float(_ex.get("registration_fee", 0)), key=f"fin_reg_{fin_date}")
                fin_bv       = st.number_input("BV (หักยอดค้าง) (฿)", min_value=0.0, step=100.0, value=float(_ex.get("bv_amount", 0)), key=f"fin_bv_{fin_date}")
            fin_notes = st.text_input("หมายเหตุ", value=_ex.get("notes", "") or "", key=f"fin_notes_{fin_date}")

            if st.button("💾 บันทึก", type="primary", use_container_width=True, key="fin_save"):
                db.upsert_finance_entry({
                    "id":               str(uuid.uuid4()),
                    "entry_date":       str(fin_date),
                    "transfer_amount":  fin_transfer,
                    "registration_fee": fin_reg,
                    "sales_amount":     fin_sales,
                    "bv_amount":        fin_bv,
                    "po_amount":        fin_po,
                    "stock_value":      0,
                    "adjustment":       0,
                    "notes":            fin_notes,
                })
                st.success("✅ บันทึกแล้ว")
                st.rerun()

        st.divider()

        # ── สรุปภาษีซื้อ / ภาษีขาย ───────────────────────────────────────────────
        with st.expander("🧾 สรุปภาษีซื้อ / ภาษีขาย", expanded=False):
            _tax_df = db.get_finance_df()
            if _tax_df.empty:
                st.info("ยังไม่มีข้อมูล")
            else:
                _tax_df["entry_date"] = pd.to_datetime(_tax_df["entry_date"])
                _min_m = _tax_df["entry_date"].dt.to_period("M").min()
                _max_m = _tax_df["entry_date"].dt.to_period("M").max()
                _months = pd.period_range(_min_m, _max_m, freq="M")
                _month_labels = [str(m) for m in _months]
                tc1, tc2 = st.columns(2)
                _sel_from = tc1.selectbox("ตั้งแต่เดือน", _month_labels, index=len(_month_labels)-1, key="tax_from")
                _sel_to   = tc2.selectbox("ถึงเดือน",     _month_labels, index=len(_month_labels)-1, key="tax_to")

                _mask = (
                    (_tax_df["entry_date"].dt.to_period("M") >= pd.Period(_sel_from, "M")) &
                    (_tax_df["entry_date"].dt.to_period("M") <= pd.Period(_sel_to, "M"))
                )
                _tdf = _tax_df[_mask]

                _sales_vat    = float(_tdf["sales_amount"].sum())
                _sales_ex_vat = _sales_vat / 1.07
                _output_vat   = _sales_vat - _sales_ex_vat
                _po_ex_vat    = float(_tdf["po_amount"].sum())
                _input_vat    = _po_ex_vat * 0.07
                _net_vat      = _output_vat - _input_vat

                tv1, tv2 = st.columns(2)
                with tv1:
                    st.markdown("**📤 ภาษีขาย (Output VAT)**")
                    st.metric("ยอดขาย รวม VAT",    f"{_sales_vat:,.2f} ฿")
                    st.metric("ยอดขาย ไม่รวม VAT", f"{_sales_ex_vat:,.2f} ฿")
                    st.metric("ภาษีขาย 7%",        f"{_output_vat:,.2f} ฿")
                with tv2:
                    st.markdown("**📥 ภาษีซื้อ (Input VAT)**")
                    st.metric("ยอดซื้อ ไม่รวม VAT", f"{_po_ex_vat:,.2f} ฿")
                    st.metric("ภาษีซื้อ 7%",        f"{_input_vat:,.2f} ฿")
                    _color = "normal" if _net_vat >= 0 else "inverse"
                    st.metric("VAT ต้องชำระสุทธิ",
                               f"{abs(_net_vat):,.2f} ฿",
                               delta="ต้องจ่าย" if _net_vat >= 0 else "ขอคืนได้",
                               delta_color=_color)

        st.divider()

        fin_df = db.get_finance_df()
        if fin_df.empty:
            st.info("ยังไม่มีข้อมูล — กรอกข้อมูลด้านบนก่อนครับ")
        else:
            display_fin = fin_df[[
                "entry_date", "transfer_amount", "bv_amount", "registration_fee",
                "sales_amount", "po_amount",
                "auto_stock", "ยอดค้างโอน", "เงินโอนเกิน", "สิทธิ์สั่งของ",
            ]].copy()
            display_fin.columns = [
                "วันที่", "โอน", "BV", "สมัคร", "ขาย", "PO",
                "สต๊อก", "ค้างโอน", "โอนเกิน", "สิทธิ์สั่งของ",
            ]
            display_fin["วันที่"] = pd.to_datetime(display_fin["วันที่"])

            _fmt = {
                "โอน": "{:,.2f}", "BV": "{:,.2f}", "สมัคร": "{:,.2f}", "ขาย": "{:,.2f}",
                "PO": "{:,.2f}", "สต๊อก": "{:,.2f}",
                "ค้างโอน": "{:,.2f}", "โอนเกิน": "{:,.2f}", "สิทธิ์สั่งของ": "{:,.2f}",
            }

            def _style_fin(df):
                return (df.style.format(_fmt)
                        .map(lambda v: "background-color:#6b1a1a;color:white" if isinstance(v, float) and v > 0.01 else "",
                             subset=["ค้างโอน"])
                        .map(lambda v: "background-color:#6b1a1a;color:white" if isinstance(v, float) and v < -0.01 else "",
                             subset=["สิทธิ์สั่งของ"]))

            _periods = sorted(display_fin["วันที่"].dt.to_period("M").unique(), reverse=True)
            for _i, _per in enumerate(_periods):
                _mdf = display_fin[display_fin["วันที่"].dt.to_period("M") == _per].sort_values("วันที่", ascending=False)
                _label = (f"📅 {_THAI_MONTHS[_per.month]} {_per.year + 543} — "
                          f"ขาย {_mdf['ขาย'].sum():,.0f} ฿ | PO {_mdf['PO'].sum():,.0f} ฿")
                with st.expander(_label, expanded=(_i == 0)):
                    st.dataframe(
                        _style_fin(_mdf),
                        use_container_width=True,
                        hide_index=True,
                    )

            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                display_fin.to_excel(writer, index=False, sheet_name="การเงิน")
            st.download_button(
                "📥 Export Excel",
                data=buf.getvalue(),
                file_name=f"finance_{date.today()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        st.divider()

    with _tab_wht:
        # ── ค่าคอมมิชชั่น & ใบเสร็จรับเงิน/ใบกำกับภาษี / เคลม VAT ──────────────────
        st.markdown("### 📑 ค่าคอมมิชชั่น & ใบเสร็จรับเงิน/ใบกำกับภาษี")

        with st.expander("⚙️ ข้อมูลบริษัท (ผู้ออกใบเสร็จ / ผู้จ่ายเงิน)", expanded=False):
            _ci = db.get_company_info()
            cic1, cic2 = st.columns(2)
            with cic1:
                st.markdown("**TBY (เรา) — ผู้ออกใบเสร็จรับเงิน/ใบกำกับภาษี**")
                ci_our_name = st.text_input("ชื่อ", value=_ci.get("our_name", "") or "", key="ci_our_name")
                ci_our_tax_id = st.text_input("เลขประจำตัวผู้เสียภาษี", value=_ci.get("our_tax_id", "") or "", key="ci_our_tax_id")
                ci_our_tel = st.text_input("เบอร์โทร/แฟกซ์", value=_ci.get("our_tel", "") or "", key="ci_our_tel")
                ci_our_address = st.text_area("ที่อยู่", value=_ci.get("our_address", "") or "", key="ci_our_address")
            with cic2:
                st.markdown("**สำนักงานใหญ่ — ได้รับเงินจาก (ผู้จ่ายค่าคอมมิชชั่น)**")
                ci_hq_name = st.text_input("ชื่อ", value=_ci.get("hq_name", "") or "", key="ci_hq_name")
                ci_hq_tax_id = st.text_input("เลขประจำตัวผู้เสียภาษี", value=_ci.get("hq_tax_id", "") or "", key="ci_hq_tax_id")
                ci_hq_address = st.text_area("ที่อยู่", value=_ci.get("hq_address", "") or "", key="ci_hq_address")
            if st.button("💾 บันทึกข้อมูลบริษัท", key="ci_save"):
                db.upsert_company_info({
                    "our_name": ci_our_name, "our_tax_id": ci_our_tax_id, "our_tel": ci_our_tel, "our_address": ci_our_address,
                    "hq_name": ci_hq_name, "hq_tax_id": ci_hq_tax_id, "hq_address": ci_hq_address,
                })
                st.success("✅ บันทึกข้อมูลบริษัทแล้ว")
                st.rerun()

        _ci = db.get_company_info()
        _cm_today = date.today()
        _cm_years = list(range(_cm_today.year - 2, _cm_today.year + 2))
        cmh1, cmh2 = st.columns(2)
        cm_year = cmh1.selectbox("ปี", _cm_years, index=_cm_years.index(_cm_today.year), key="cm_year")
        cm_month = cmh2.selectbox("เดือน", list(range(1, 13)),
                                   format_func=lambda m: f"{m} - {_THAI_MONTHS[m]}",
                                   index=_cm_today.month - 1, key="cm_month")
        cm_period = f"{cm_year}-{cm_month:02d}"
        _cr = db.get_commission_record(cm_period) or {}
        _cm_df_all = db.get_commission_records()

        # ── คำนวณเลขที่/เล่มที่ใบเสร็จเริ่มต้น (รันอัตโนมัติ) ──
        _year_code = (cm_year + 543) % 100
        _default_book_no = _cr.get("receipt_book_no") or ""
        _default_seq = _cr.get("receipt_seq")
        if not _cm_df_all.empty:
            _prev = _cm_df_all[_cm_df_all["period"] != cm_period]
            if not _default_book_no and not _prev.empty:
                _default_book_no = _prev.iloc[0].get("receipt_book_no") or ""
            if _default_seq is None:
                _same_year = _prev[_prev["period"].str[:4].astype(int).apply(lambda y: (y + 543) % 100) == _year_code]
                if not _same_year.empty and _same_year["receipt_seq"].notna().any():
                    _default_seq = int(_same_year["receipt_seq"].max()) + 1
        if _default_seq is None:
            _default_seq = 1

        with st.form(f"commission_form_{cm_period}"):
            st.markdown(f"**บันทึกข้อมูลเดือน {_THAI_MONTHS[cm_month]} {cm_year + 543}**")
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                cm_amount = st.number_input("ค่าคอมมิชชั่น (฿)", min_value=0.0, step=100.0,
                    value=float(_cr.get("commission_amount", 0)), key=f"cm_amount_{cm_period}")
                cm_wht_rate = st.number_input("อัตราหัก ณ ที่จ่าย (%)", min_value=0.0, max_value=100.0, step=0.5,
                    value=float(_cr.get("wht_rate", 3.0)), key=f"cm_wht_rate_{cm_period}")
            _wht_amount = round(cm_amount * cm_wht_rate / 100, 2)
            _net_amount = round(cm_amount - _wht_amount, 2)
            with fc2:
                st.metric("ภาษีหัก ณ ที่จ่าย", f"{_wht_amount:,.2f} ฿")
                st.metric("ยอดสุทธิที่ได้รับ", f"{_net_amount:,.2f} ฿")
                cm_received = st.checkbox("ได้รับเงินค่าคอมมิชชั่นแล้ว", value=bool(_cr.get("commission_received", False)), key=f"cm_received_{cm_period}")
                cm_received_date = st.date_input("วันที่ได้รับเงิน", value=_parse_date(_cr.get("commission_received_date")), key=f"cm_received_date_{cm_period}")
            with fc3:
                cm_receipt_book_no = st.text_input("เล่มที่ใบเสร็จ", value=_cr.get("receipt_book_no") or _default_book_no, key=f"cm_receipt_book_no_{cm_period}")
                cm_receipt_seq = st.number_input("เลขที่ใบเสร็จ (ลำดับ)", min_value=1, step=1,
                    value=int(_cr.get("receipt_seq") or _default_seq), key=f"cm_receipt_seq_{cm_period}")
                cm_receipt_date = st.date_input("วันที่ออกใบเสร็จ", value=_parse_date(_cr.get("receipt_date")), key=f"cm_receipt_date_{cm_period}")
                st.caption(f"เลขที่เอกสาร: {_year_code}/{int(cm_receipt_seq):03d}")

            st.divider()
            st.markdown("**เคลม VAT จากสำนักงานใหญ่** (VAT 7% ของค่าคอมมิชชั่น — คำนวณอัตโนมัติ)")
            cm_vat_claim = round(cm_amount * 0.07, 2)
            vc1, vc2, vc3 = st.columns(3)
            with vc1:
                st.metric("ยอด VAT 7% ที่ขอเบิกคืน", f"{cm_vat_claim:,.2f} ฿")
            with vc2:
                cm_vat_doc_issued = st.checkbox("ออกเอกสารเคลม VAT แล้ว", value=bool(_cr.get("vat_claim_doc_issued", False)), key=f"cm_vat_doc_issued_{cm_period}")
                cm_vat_doc_date = st.date_input("วันที่ออกเอกสารเคลม", value=_parse_date(_cr.get("vat_claim_doc_date")), key=f"cm_vat_doc_date_{cm_period}")
            with vc3:
                cm_vat_received = st.checkbox("ได้รับเงินคืน VAT แล้ว", value=bool(_cr.get("vat_claim_received", False)), key=f"cm_vat_received_{cm_period}")
                cm_vat_received_date = st.date_input("วันที่ได้รับคืน", value=_parse_date(_cr.get("vat_claim_received_date")), key=f"cm_vat_received_date_{cm_period}")

            cm_notes = st.text_area("หมายเหตุ", value=_cr.get("notes", "") or "", key=f"cm_notes_{cm_period}")
            cm_submitted = st.form_submit_button("💾 บันทึก", type="primary", use_container_width=True)

        if cm_submitted:
            try:
                db.upsert_commission_record({
                    "period": cm_period,
                    "commission_amount": cm_amount,
                    "wht_rate": cm_wht_rate,
                    "wht_amount": _wht_amount,
                    "net_amount": _net_amount,
                    "receipt_book_no": cm_receipt_book_no,
                    "receipt_seq": int(cm_receipt_seq),
                    "receipt_date": str(cm_receipt_date),
                    "commission_received": cm_received,
                    "commission_received_date": str(cm_received_date) if cm_received else None,
                    "vat_claim_amount": cm_vat_claim,
                    "vat_claim_doc_issued": cm_vat_doc_issued,
                    "vat_claim_doc_date": str(cm_vat_doc_date) if cm_vat_doc_issued else None,
                    "vat_claim_received": cm_vat_received,
                    "vat_claim_received_date": str(cm_vat_received_date) if cm_vat_received else None,
                    "notes": cm_notes,
                })
                st.success("✅ บันทึกแล้ว")
                st.rerun()
            except Exception as e:
                st.error(f"❌ บันทึกไม่สำเร็จ: {e}")

        if _cr and float(_cr.get("commission_amount", 0)) > 0:
            if st.button("🖨️ พิมพ์ใบเสร็จรับเงิน/ใบกำกับภาษี", key=f"cm_print_{cm_period}", use_container_width=True):
                _receipt_html = _render_receipt_html(_cr, _ci, cm_period)
                components.html(_receipt_html, height=700, scrolling=True)

        # ── บันทึกรายการ (Ledger) ────────────────────────────────────────────────
        _cm_df = db.get_commission_records()
        if not _cm_df.empty:
            st.divider()
            st.markdown("**📋 บันทึกรายการ (Ledger)**")
            _show_cm = _cm_df.copy()
            _show_cm["เลขที่"] = _show_cm.apply(
                lambda r: (f"{(int(r['period'][:4]) + 543) % 100}/{int(r['receipt_seq']):03d}"
                           if pd.notna(r.get("receipt_seq")) else "—"), axis=1)
            _show_cm["เล่มที่"] = _show_cm["receipt_book_no"].fillna("—")
            _show_cm["วันที่"] = _show_cm["receipt_date"].apply(
                lambda d: (lambda dt: f"{dt.day}/{dt.month}/{dt.year + 543}")(_parse_date(d)) if pd.notna(d) and d else "—")
            _show_cm["รายละเอียด"] = _show_cm["period"].apply(
                lambda p: f"ค่าคอมมิชชั่นประจำเดือน{_THAI_MONTHS[int(p.split('-')[1])]} {(int(p.split('-')[0]) + 543) % 100}")
            _show_cm["status transfer"] = _show_cm.apply(
                lambda r: "transfer" if r.get("commission_received") else "—", axis=1)
            _show_cm["status vat claim"] = _show_cm.apply(
                lambda r: "transfer" if r.get("vat_claim_received")
                          else ("ขอเบิกแล้ว" if r.get("vat_claim_doc_issued") else "—"), axis=1)
            _disp = _show_cm[[
                "เลขที่", "เล่มที่", "วันที่", "รายละเอียด", "commission_amount",
                "wht_amount", "status transfer", "vat_claim_amount", "status vat claim", "net_amount",
            ]].rename(columns={
                "commission_amount": "จำนวนเงิน",
                "wht_amount": "หัก ณ ที่จ่าย 3%",
                "vat_claim_amount": "vat claim",
                "net_amount": "commission",
            })
            st.dataframe(
                _disp.style.format({
                    "จำนวนเงิน": "{:,.2f}", "หัก ณ ที่จ่าย 3%": "{:,.2f}",
                    "vat claim": "{:,.2f}", "commission": "{:,.2f}",
                }),
                use_container_width=True, hide_index=True,
            )

            # ── สรุปสิ้นปี ────────────────────────────────────────────────────────
            st.markdown("**📆 สรุปสิ้นปี**")
            _cm_df["year"] = _cm_df["period"].str[:4]
            _year_summary = _cm_df.groupby("year", as_index=False).agg(
                ค่าคอมมิชชั่นรวม=("commission_amount", "sum"),
                ภาษีหักไว้รวม=("wht_amount", "sum"),
                สุทธิรวม=("net_amount", "sum"),
                VAT_เคลมรวม=("vat_claim_amount", "sum"),
            ).rename(columns={"year": "ปี", "VAT_เคลมรวม": "VAT เคลมรวม"})
            _year_summary["ปี (พ.ศ.)"] = _year_summary["ปี"].astype(int) + 543
            st.dataframe(
                _year_summary[["ปี (พ.ศ.)", "ค่าคอมมิชชั่นรวม", "ภาษีหักไว้รวม", "สุทธิรวม", "VAT เคลมรวม"]]
                .style.format({
                    "ค่าคอมมิชชั่นรวม": "{:,.2f}", "ภาษีหักไว้รวม": "{:,.2f}",
                    "สุทธิรวม": "{:,.2f}", "VAT เคลมรวม": "{:,.2f}",
                }),
                use_container_width=True, hide_index=True,
            )
