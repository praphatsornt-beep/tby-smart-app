"""UI สำหรับแท็บ 🏠 หน้าแรก — แยกจาก app.py"""
import streamlit as st
import pandas as pd
from datetime import date, datetime, timezone, timedelta

import database as db

_BKK = timezone(timedelta(hours=7))


def render():
    _today = date.today()
    _today_str = _today.strftime("%Y-%m-%d")
    _thai_days = ["จันทร์","อังคาร","พุธ","พฤหัสบดี","ศุกร์","เสาร์","อาทิตย์"]
    _thai_months = ["","ม.ค.","ก.พ.","มี.ค.","เม.ย.","พ.ค.","มิ.ย.","ก.ค.","ส.ค.","ก.ย.","ต.ค.","พ.ย.","ธ.ค."]
    _day_name = _thai_days[_today.weekday()]
    st.caption(f"📅 วัน{_day_name} {_today.day} {_thai_months[_today.month]} {_today.year + 543}")

    # ── โหลด data (ทั้งหมด cached) ──────────────────────────────────────────
    try:
        _dash_txn   = db.get_all_transactions_df()
        _dash_outs  = db.get_outstanding_df()
        _dash_ships = db.get_shipments()
        _dash_pv    = db.get_unbilled_pv_summary()
        _dash_fin   = db.get_finance_summary()
    except Exception as _de:
        st.error(f"โหลดข้อมูลไม่ได้: {_de}")
        st.stop()

    # ── คำนวณ metrics ────────────────────────────────────────────────────────
    _today_txn = _dash_txn[_dash_txn["วันที่"] == _today_str] if not _dash_txn.empty else pd.DataFrame()
    _today_sales = _today_txn["ยอดรวม"].sum() if not _today_txn.empty else 0.0
    _today_count = len(_today_txn)

    _total_owed  = _dash_outs["ค้างจ่าย"].sum() if not _dash_outs.empty else 0.0
    _total_custs = _dash_outs["ลูกค้า"].nunique() if not _dash_outs.empty else 0

    _cod_pending = [s for s in _dash_ships
                    if float(s.get("cod_amount") or 0) > 0
                    and not s.get("cod_transferred_at")]
    _cod_count  = len(_cod_pending)
    _cod_amt    = sum(float(s.get("cod_amount") or 0) for s in _cod_pending)

    _pv_count = _dash_pv.get("count", 0)
    _pv_total = _dash_pv.get("total_pv", 0.0)

    # ── Metric cards ─────────────────────────────────────────────────────────
    _dc1, _dc2, _dc3, _dc4 = st.columns(4)
    _dc1.metric("💵 ยอดขายวันนี้",   f"{_today_sales:,.0f} ฿",
                delta=f"{_today_count} รายการ", delta_color="off")
    _dc2.metric("⚠️ ค้างจ่ายรวม",    f"{_total_owed:,.0f} ฿",
                delta=f"{_total_custs} ลูกค้า", delta_color="off")
    _dc3.metric("🚚 COD รอรับ",       f"{_cod_count} รายการ",
                delta=f"{_cod_amt:,.0f} ฿" if _cod_amt else "ไม่มี", delta_color="off")
    _dc4.metric("⭐ PV รอเปิดบิล",   f"{_pv_total:,.0f} PV",
                delta=f"{_pv_count} รายการ", delta_color="off")

    # แสดงสิทธิ์สั่งของถ้ามี finance data
    _credit = float(_dash_fin.get("credit", 0) or 0)
    if _credit > 0:
        st.info(f"💳 สิทธิ์สั่งของคงเหลือ: **{_credit:,.0f} ฿**")

    st.divider()

    # ── 2 คอลัมน์: รายการวันนี้ + ลูกค้าค้างสูงสุด ──────────────────────────
    _dl, _dr = st.columns([3, 2])

    with _dl:
        st.markdown("**📋 รายการที่บันทึกวันนี้**")
        if _today_txn.empty:
            st.caption("ยังไม่มีรายการวันนี้")
        else:
            _show_today = _today_txn[["เลขที่บิล","ลูกค้า","สินค้า","ยอดรวม","สถานะบิล"]].copy()
            _show_today = _show_today.rename(columns={"เลขที่บิล": "บิล", "ยอดรวม": "ยอด (฿)"})
            st.dataframe(
                _show_today.style.format({"ยอด (฿)": "{:,.0f}"}),
                use_container_width=True, hide_index=True,
                height=min(35 * len(_show_today) + 38, 320),
            )

    with _dr:
        st.markdown("**🔴 ลูกค้าค้างสูงสุด (Top 5)**")
        if _dash_outs.empty:
            st.caption("ไม่มียอดค้าง")
        else:
            _top5 = (_dash_outs.groupby("ลูกค้า")
                     .agg(ค้างจ่าย=("ค้างจ่าย","sum"), ค้างรับ=("ค้างรับ","sum"))
                     .sort_values("ค้างจ่าย", ascending=False)
                     .head(5)
                     .reset_index())
            st.dataframe(
                _top5.style.format({"ค้างจ่าย": "{:,.0f}", "ค้างรับ": "{:.0f}"}),
                use_container_width=True, hide_index=True,
            )

    # ── helper ───────────────────────────────────────────────────────────────
    def _parse_sdt(s_str):
        try:
            return datetime.fromisoformat(s_str.replace("Z", "+00:00"))
        except Exception:
            return None

    def _items_str(sh):
        its = sh.get("items") or []
        return ", ".join(
            f"{it.get('name') or it.get('product_id','')} ×{it.get('qty',1)}"
            for it in its
        ) if its else "—"

    if _dash_ships:
        _TERMINAL_S  = {"จัดส่งแล้ว", "ตีกลับ", "ยกเลิก"}
        _now_utc     = datetime.now(timezone.utc)
        _cutoff      = _now_utc - timedelta(days=3)

        # ลูกค้าที่มี COD + ยังไม่เปิดบิล
        _cod_unbilled_custs = set()
        if not _dash_txn.empty and "สถานะจ่าย" in _dash_txn.columns and "สถานะบิล" in _dash_txn.columns:
            _cmask = (_dash_txn["สถานะจ่าย"] == "COD") & (_dash_txn["สถานะบิล"] == "ยังไม่เปิดบิล")
            _cod_unbilled_custs = set(_dash_txn.loc[_cmask, "ลูกค้า"].unique())

        _slow_ships, _problem_ships, _cod_rows = [], [], []

        for _sh in _dash_ships:
            _cname = ((_sh.get("customers") or {}).get("name") or _sh.get("recipient_name", "—"))
            _sdt   = _parse_sdt(_sh.get("created_at", ""))
            _stat  = _sh.get("delivery_status") or "ไม่มีข้อมูล"
            _its   = _items_str(_sh)
            _date_str = _sdt.astimezone(_BKK).strftime("%d/%m/%y") if _sdt else "—"

            # ── COD ──────────────────────────────────────────────────────
            if float(_sh.get("cod_amount") or 0) > 0:
                _paid = bool(_sh.get("cod_transferred_at"))
                if not _paid:
                    _cod_rows.append({
                        "ลูกค้า":    _cname,
                        "สินค้า":    _its,
                        "COD (฿)":   int(_sh.get("cod_amount") or 0),
                        "Tracking":  _sh.get("tracking_no", "—"),
                        "ขนส่ง":     _sh.get("carrier", ""),
                        "วันที่ส่ง": _date_str,
                        "สถานะ":     "💛 รอรับ COD",
                    })
                elif _cname in _cod_unbilled_custs:
                    _cod_rows.append({
                        "ลูกค้า":    _cname,
                        "สินค้า":    _its,
                        "COD (฿)":   int(_sh.get("cod_amount") or 0),
                        "Tracking":  _sh.get("tracking_no", "—"),
                        "ขนส่ง":     _sh.get("carrier", ""),
                        "วันที่ส่ง": _date_str,
                        "สถานะ":     "✅ รับแล้ว — ยังไม่เปิดบิล",
                    })
                # else: COD รับแล้ว + เปิดบิลแล้ว → ไม่แสดง

            # ── พัสดุมีปัญหา ────────────────────────────────────────────
            if _sh.get("delivery_status") in {"ตีกลับ", "ยกเลิก"}:
                _problem_ships.append({
                    "ลูกค้า":    _cname,
                    "สินค้า":    _its,
                    "Tracking":  _sh.get("tracking_no", "—"),
                    "ขนส่ง":     _sh.get("carrier", ""),
                    "วันที่ส่ง": _date_str,
                    "สถานะ":     _stat,
                })

            # ── พัสดุเกิน 3 วัน (ไม่รวม COD — ติดตามใน section COD แล้ว) ──
            elif (float(_sh.get("cod_amount") or 0) == 0
                    and _sh.get("tracking_no")
                    and _sh.get("delivery_status") not in _TERMINAL_S
                    and _sdt and _sdt < _cutoff):
                _slow_ships.append({
                    "ลูกค้า":       _cname,
                    "สินค้า":       _its,
                    "Tracking":     _sh.get("tracking_no", ""),
                    "ขนส่ง":        _sh.get("carrier", ""),
                    "วันที่ส่ง":    _date_str,
                    "วัน":          (_now_utc - _sdt).days,
                    "สถานะ":        _stat,
                })

        # ── แสดง COD ─────────────────────────────────────────────────────
        if _cod_rows:
            st.divider()
            st.markdown(f"**💛 COD — ติดตามสถานะ ({len(_cod_rows)} รายการ)**")
            _cod_df = pd.DataFrame(_cod_rows)
            st.dataframe(_cod_df.style.format({"COD (฿)": "{:,.0f}"}),
                         use_container_width=True, hide_index=True,
                         height=min(35 * len(_cod_df) + 38, 280))

        # ── แสดงพัสดุล่าช้า ──────────────────────────────────────────────
        if _slow_ships:
            st.divider()
            st.markdown(f"**⏳ พัสดุเกิน 3 วัน ยังไม่ถึง ({len(_slow_ships)} รายการ)**")
            st.dataframe(pd.DataFrame(_slow_ships),
                         use_container_width=True, hide_index=True,
                         height=min(35 * len(_slow_ships) + 38, 300))

        # ── แสดงพัสดุมีปัญหา ─────────────────────────────────────────────
        if _problem_ships:
            st.divider()
            st.markdown(f"**⚠️ พัสดุที่มีปัญหา ตีกลับ/ยกเลิก ({len(_problem_ships)} รายการ)**")
            st.dataframe(pd.DataFrame(_problem_ships),
                         use_container_width=True, hide_index=True,
                         height=min(35 * len(_problem_ships) + 38, 300))
