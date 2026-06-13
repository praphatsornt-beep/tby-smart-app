"""UI สำหรับแท็บการเงิน — แยกจาก app.py"""
import io
import uuid

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from datetime import date

import database as db
import iship_api

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


def _render_wht_cert_html(cr: dict, ci: dict, period: str) -> str:
    _year, _month = period.split("-")
    _pay_date = _parse_date(cr.get("wht_issue_date"))
    _amount = float(cr.get("commission_amount", 0))
    _wht_amount = float(cr.get("wht_amount", 0))
    _amount_text = _thai_baht_text(_wht_amount)
    _doc_no = cr.get("wht_doc_no") or "—"

    _css = """
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Sarabun',sans-serif;padding:20px;color:#111;background:#fff;font-size:13px}
  .title{text-align:center;font-size:16px;font-weight:700;margin-bottom:2px}
  .subtitle{text-align:center;font-size:12px;color:#444;margin-bottom:12px}
  .docno{text-align:right;font-size:12px;margin-bottom:8px}
  .box{border:1px solid #000;padding:10px;margin-bottom:10px}
  .box h3{font-size:13px;margin-bottom:6px}
  .row{display:flex;gap:8px;margin-bottom:3px}
  .row .lbl{min-width:140px;color:#444}
  table{width:100%;border-collapse:collapse;margin-top:8px;border:1px solid #000}
  th{background:#000;color:#fff;padding:6px;text-align:center;font-size:12px;border:1px solid #000}
  td{padding:6px;border:1px solid #aaa;font-size:12px;text-align:center}
  .total-words{margin-top:8px;font-size:12px}
  .sign{margin-top:40px;text-align:center;font-size:12px}
  .sign .line{margin-bottom:6px}
  .btn{display:block;margin:0 auto 14px;padding:7px 28px;background:#c0392b;color:#fff;
       border:none;border-radius:6px;font-size:13px;cursor:pointer}
  @media print{
    .btn{display:none}
    @page{size:A4;margin:15mm}
    *{-webkit-print-color-adjust:exact;print-color-adjust:exact}
    th{background:#000!important;color:#fff!important}
  }"""

    _body = f"""
<div class="docno">เลขที่ {_doc_no}</div>
<div class="title">หนังสือรับรองการหักภาษี ณ ที่จ่าย</div>
<div class="subtitle">ตามมาตรา 50 ทวิ แห่งประมวลรัษฎากร</div>

<div class="box">
  <h3>ผู้มีหน้าที่หักภาษี ณ ที่จ่าย</h3>
  <div class="row"><span class="lbl">ชื่อ:</span><span>{ci.get('our_name','') or '—'}</span></div>
  <div class="row"><span class="lbl">เลขประจำตัวผู้เสียภาษี:</span><span>{ci.get('our_tax_id','') or '—'}</span></div>
  <div class="row"><span class="lbl">ที่อยู่:</span><span>{ci.get('our_address','') or '—'}</span></div>
</div>

<div class="box">
  <h3>ผู้ถูกหักภาษี ณ ที่จ่าย</h3>
  <div class="row"><span class="lbl">ชื่อ:</span><span>{ci.get('hq_name','') or '—'}</span></div>
  <div class="row"><span class="lbl">เลขประจำตัวผู้เสียภาษี:</span><span>{ci.get('hq_tax_id','') or '—'}</span></div>
  <div class="row"><span class="lbl">ที่อยู่:</span><span>{ci.get('hq_address','') or '—'}</span></div>
</div>

<table>
  <tr>
    <th>ประเภทเงินได้ที่จ่าย</th>
    <th>วันเดือนปีที่จ่าย</th>
    <th>จำนวนเงินที่จ่าย (บาท)</th>
    <th>ภาษีที่หักไว้ (บาท)</th>
  </tr>
  <tr>
    <td>ค่าคอมมิชชั่น/ค่าบริการ — ประจำเดือน {_THAI_MONTHS[int(_month)]} {int(_year)+543}</td>
    <td>{_pay_date.day}/{_pay_date.month}/{_pay_date.year+543}</td>
    <td>{_amount:,.2f}</td>
    <td>{_wht_amount:,.2f}</td>
  </tr>
  <tr>
    <td colspan="2" style="text-align:right;font-weight:700">รวม</td>
    <td style="font-weight:700">{_amount:,.2f}</td>
    <td style="font-weight:700">{_wht_amount:,.2f}</td>
  </tr>
</table>

<div class="total-words">ภาษีที่หักไว้ทั้งสิ้น ({_amount_text})</div>

<div class="sign">
  <div class="line">ลงชื่อ ......................................................... ผู้จ่ายเงิน</div>
  <div>วันที่ {_pay_date.day}/{_pay_date.month}/{_pay_date.year+543}</div>
</div>
"""

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{_css}</style></head><body>
<button class="btn" onclick="window.print()">🖨️ พิมพ์</button>
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

        # ── ตรวจสอบสถานะ COD Transfer ────────────────────────────────────────────
        with st.expander("🔍 ตรวจสอบสถานะ COD (iShip)", expanded=False):
            st.caption("ดึงข้อมูลจาก iShip แล้ว match กับ tracking ใน shipments table")
            if st.button("🔄 ดึงข้อมูล COD Transfer", key="cod_fetch"):
                with st.spinner("กำลัง login และดึงข้อมูล..."):
                    _cod_result = iship_api.get_cod_transfers(days_back=60)
                if _cod_result.get("error"):
                    st.error(f"❌ {_cod_result['error']}")
                _cod_map = _cod_result.get("transfers", {})
                if _cod_map:
                    st.success(f"✅ พบ {len(_cod_map)} tracking ที่โอนแล้ว")
                    _cod_df = pd.DataFrame([
                        {"tracking": tn, "วันที่โอน": v["date"], "ยอด COD": v["cod_amount"],
                         "ยอดสุทธิ": v["net"], "สถานะ": v["status"], "WD": v["wd_id"]}
                        for tn, v in _cod_map.items()
                    ])
                    st.dataframe(_cod_df, use_container_width=True, hide_index=True)
                elif not _cod_result.get("error"):
                    st.info("ไม่พบรายการ COD ใน 60 วันที่ผ่านมา")
                    st.json(_cod_result.get("_debug", {}))

    with _tab_wht:
        # ── ค่าคอมมิชชั่น & ใบหัก ณ ที่จ่าย (50 ทวิ) / เคลม VAT ──────────────────
        st.markdown("### 📑 ค่าคอมมิชชั่น & ใบหัก ณ ที่จ่าย (50 ทวิ)")

        with st.expander("⚙️ ข้อมูลบริษัท (ผู้จ่าย / ผู้ถูกหักภาษี)", expanded=False):
            _ci = db.get_company_info()
            cic1, cic2 = st.columns(2)
            with cic1:
                st.markdown("**TBY (เรา) — ผู้มีหน้าที่หักภาษี ณ ที่จ่าย**")
                ci_our_name = st.text_input("ชื่อ", value=_ci.get("our_name", "") or "", key="ci_our_name")
                ci_our_tax_id = st.text_input("เลขประจำตัวผู้เสียภาษี", value=_ci.get("our_tax_id", "") or "", key="ci_our_tax_id")
                ci_our_address = st.text_area("ที่อยู่", value=_ci.get("our_address", "") or "", key="ci_our_address")
            with cic2:
                st.markdown("**สำนักงานใหญ่ — ผู้ถูกหักภาษี ณ ที่จ่าย**")
                ci_hq_name = st.text_input("ชื่อ", value=_ci.get("hq_name", "") or "", key="ci_hq_name")
                ci_hq_tax_id = st.text_input("เลขประจำตัวผู้เสียภาษี", value=_ci.get("hq_tax_id", "") or "", key="ci_hq_tax_id")
                ci_hq_address = st.text_area("ที่อยู่", value=_ci.get("hq_address", "") or "", key="ci_hq_address")
            if st.button("💾 บันทึกข้อมูลบริษัท", key="ci_save"):
                db.upsert_company_info({
                    "our_name": ci_our_name, "our_tax_id": ci_our_tax_id, "our_address": ci_our_address,
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

        with st.form(f"commission_form_{cm_period}"):
            st.markdown(f"**บันทึกข้อมูลเดือน {_THAI_MONTHS[cm_month]} {cm_year + 543}**")
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                cm_amount = st.number_input("ค่าคอมมิชชั่น (฿)", min_value=0.0, step=100.0,
                    value=float(_cr.get("commission_amount", 0)), key=f"cm_amount_{cm_period}")
                cm_wht_rate = st.number_input("อัตราหัก ณ ที่จ่าย (%)", min_value=0.0, max_value=100.0, step=0.5,
                    value=float(_cr.get("wht_rate", 3.0)), key=f"cm_wht_rate_{cm_period}")
                cm_doc_no = st.text_input("เลขที่ใบหัก ณ ที่จ่าย", value=_cr.get("wht_doc_no", "") or "", key=f"cm_doc_no_{cm_period}")
            _wht_amount = round(cm_amount * cm_wht_rate / 100, 2)
            _net_amount = round(cm_amount - _wht_amount, 2)
            with fc2:
                st.metric("ภาษีหัก ณ ที่จ่าย", f"{_wht_amount:,.2f} ฿")
                st.metric("ยอดสุทธิที่ได้รับ", f"{_net_amount:,.2f} ฿")
                cm_wht_issued = st.checkbox("ออกใบหัก ณ ที่จ่ายแล้ว", value=bool(_cr.get("wht_issued", False)), key=f"cm_wht_issued_{cm_period}")
                cm_wht_issue_date = st.date_input("วันที่ออกเอกสาร", value=_parse_date(_cr.get("wht_issue_date")), key=f"cm_wht_issue_date_{cm_period}")
            with fc3:
                cm_received = st.checkbox("ได้รับเงินค่าคอมมิชชั่นแล้ว", value=bool(_cr.get("commission_received", False)), key=f"cm_received_{cm_period}")
                cm_received_date = st.date_input("วันที่ได้รับเงิน", value=_parse_date(_cr.get("commission_received_date")), key=f"cm_received_date_{cm_period}")

            st.divider()
            st.markdown("**เคลม VAT จากสำนักงานใหญ่** (VAT ที่เราจ่ายล่วงหน้าไปก่อน แล้วออกเอกสารขอเบิกคืน)")
            vc1, vc2, vc3 = st.columns(3)
            with vc1:
                cm_vat_claim = st.number_input("ยอด VAT ที่ขอเบิกคืน (฿)", min_value=0.0, step=10.0,
                    value=float(_cr.get("vat_claim_amount", 0)), key=f"cm_vat_claim_{cm_period}")
            with vc2:
                cm_vat_doc_issued = st.checkbox("ออกเอกสารเคลม VAT แล้ว", value=bool(_cr.get("vat_claim_doc_issued", False)), key=f"cm_vat_doc_issued_{cm_period}")
                cm_vat_doc_date = st.date_input("วันที่ออกเอกสารเคลม", value=_parse_date(_cr.get("vat_claim_doc_date")), key=f"cm_vat_doc_date_{cm_period}")
            with vc3:
                cm_vat_received = st.checkbox("ได้รับเงินคืน VAT แล้ว", value=bool(_cr.get("vat_claim_received", False)), key=f"cm_vat_received_{cm_period}")
                cm_vat_received_date = st.date_input("วันที่ได้รับคืน", value=_parse_date(_cr.get("vat_claim_received_date")), key=f"cm_vat_received_date_{cm_period}")

            cm_notes = st.text_area("หมายเหตุ", value=_cr.get("notes", "") or "", key=f"cm_notes_{cm_period}")
            cm_submitted = st.form_submit_button("💾 บันทึก", type="primary", use_container_width=True)

        if cm_submitted:
            db.upsert_commission_record({
                "period": cm_period,
                "commission_amount": cm_amount,
                "wht_rate": cm_wht_rate,
                "wht_amount": _wht_amount,
                "net_amount": _net_amount,
                "wht_doc_no": cm_doc_no,
                "wht_issued": cm_wht_issued,
                "wht_issue_date": str(cm_wht_issue_date) if cm_wht_issued else None,
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

        if _cr and float(_cr.get("commission_amount", 0)) > 0:
            if st.button("🖨️ พิมพ์ใบหัก ณ ที่จ่าย (50 ทวิ)", key=f"cm_print_{cm_period}", use_container_width=True):
                _wht_html = _render_wht_cert_html(_cr, _ci, cm_period)
                components.html(_wht_html, height=700, scrolling=True)

        # ── สรุปทุกเดือน ──────────────────────────────────────────────────────────
        _cm_df = db.get_commission_records()
        if not _cm_df.empty:
            st.divider()
            st.markdown("**📋 สรุปรายเดือน**")
            _show_cm = _cm_df.copy()
            _show_cm["หัก ณ ที่จ่าย"] = _show_cm.apply(
                lambda r: "✅ออกแล้ว" if r.get("wht_issued") else "—", axis=1)
            _show_cm["รับเงิน"] = _show_cm.apply(
                lambda r: "✅รับแล้ว" if r.get("commission_received") else "⏳ยังไม่รับ", axis=1)
            _show_cm["เคลม VAT"] = _show_cm.apply(
                lambda r: ("✅รับคืนแล้ว" if r.get("vat_claim_received")
                           else ("📄ออกเอกสารแล้ว" if r.get("vat_claim_doc_issued") else "—")), axis=1)
            _disp = _show_cm[[
                "period", "commission_amount", "wht_amount", "net_amount",
                "หัก ณ ที่จ่าย", "รับเงิน", "vat_claim_amount", "เคลม VAT",
            ]].rename(columns={
                "period": "เดือน", "commission_amount": "ค่าคอมมิชชั่น",
                "wht_amount": "ภาษีหัก ณ ที่จ่าย", "net_amount": "สุทธิ",
                "vat_claim_amount": "ยอด VAT เคลม",
            })
            st.dataframe(
                _disp.style.format({
                    "ค่าคอมมิชชั่น": "{:,.2f}", "ภาษีหัก ณ ที่จ่าย": "{:,.2f}",
                    "สุทธิ": "{:,.2f}", "ยอด VAT เคลม": "{:,.2f}",
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
