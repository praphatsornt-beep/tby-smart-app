"""UI สำหรับแท็บ 🏠 หน้าแรก — แยกจาก app.py"""
import streamlit as st
import pandas as pd
from datetime import date, datetime, timezone, timedelta

import database as db
import iship_api
from ui_helpers import _style_status

_BKK = timezone(timedelta(hours=7))


def render():
    _today = date.today()
    _today_str = _today.strftime("%Y-%m-%d")

    # ── โหลด data (ทั้งหมด cached) ──────────────────────────────────────────
    try:
        _dash_today = db.get_today_transactions()
        _dash_outs  = db.get_outstanding_df()
        _dash_ships = db.get_shipments()
        _dash_pv    = db.get_unbilled_pv_summary()
        _dash_fin   = db.get_finance_summary()
    except Exception as _de:
        st.error(f"โหลดข้อมูลไม่ได้: {_de}")
        st.stop()

    # ── คำนวณ metrics ────────────────────────────────────────────────────────
    _today_sales = sum(float(t.get("total_amount") or 0) for t in _dash_today)
    _today_count = len(_dash_today)
    _today_bills = len({t.get("bill_no") for t in _dash_today if t.get("bill_no")})

    _total_owed  = _dash_outs["ค้างจ่าย"].sum() if not _dash_outs.empty else 0.0
    _total_custs = _dash_outs["ลูกค้า"].nunique() if not _dash_outs.empty else 0

    _cod_pending = [s for s in _dash_ships
                    if float(s.get("cod_amount") or 0) > 0
                    and not s.get("cod_transferred_at")]
    _cod_count  = len(_cod_pending)
    _cod_amt    = sum(float(s.get("cod_amount") or 0) for s in _cod_pending)

    _pv_count = _dash_pv.get("count", 0)
    _pv_total = _dash_pv.get("total_pv", 0.0)

    # ── สินค้าที่ลูกค้าฝาก (เปิดบิลแล้ว + ค้างรับ > 0) ──────────────────────
    _deposits = []
    if not _dash_outs.empty:
        _dep_df = _dash_outs[(_dash_outs["สถานะบิล"] == "เปิดบิลแล้ว") & (_dash_outs["ค้างรับ"] > 0)]
        if not _dep_df.empty:
            _dep_sum = (_dep_df.groupby("สินค้า", as_index=False)["ค้างรับ"].sum()
                        .sort_values("ค้างรับ", ascending=False))
            _deposits = [{"name": r["สินค้า"], "qty": int(r["ค้างรับ"])} for _, r in _dep_sum.iterrows()]

    # ── ยอดขาย 7 วันล่าสุด ──────────────────────────────────────────────────
    _week_start = (_today - timedelta(days=6)).strftime("%Y-%m-%d")
    _week_df = db.get_all_transactions_df(date_from=_week_start, date_to=_today_str)
    if not _week_df.empty:
        _daily_sales = (pd.to_datetime(_week_df["วันที่"]).dt.date
                        .pipe(lambda s: _week_df.groupby(s)["ยอดรวม"].sum()))
    else:
        _daily_sales = pd.Series(dtype=float)
    _week_days = [_today - timedelta(days=_i) for _i in range(6, -1, -1)]
    _chart_df = pd.DataFrame({
        "วัน": [d.strftime("%d/%m") for d in _week_days],
        "ยอดขาย": [float(_daily_sales.get(d, 0)) for d in _week_days],
    }).set_index("วัน")

    # ── Metric cards ─────────────────────────────────────────────────────────
    _dc1, _dc2, _dc3, _dc4 = st.columns(4)
    _dc1.metric("💵 ยอดขายวันนี้",   f"{_today_sales:,.0f} ฿",
                delta=f"{_today_count} รายการ", delta_color="off")
    _dc2.metric("🧾 จำนวนบิลวันนี้", f"{_today_bills}",
                delta=f"{_today_count} รายการสินค้า", delta_color="off")
    _dc3.metric("📋 สินค้าที่ลูกค้าฝาก", f"{len(_deposits)} รายการ",
                delta=f"{sum(d['qty'] for d in _deposits)} ชิ้น" if _deposits else "ไม่มี", delta_color="off")
    _dc4.metric("⚠️ ค้างจ่ายรวม",    f"{_total_owed:,.0f} ฿",
                delta=f"{_total_custs} ลูกค้า", delta_color="off")

    # แสดงสิทธิ์สั่งของ + COD/PV แบบย่อ
    _info_parts = []
    _credit = float(_dash_fin.get("credit", 0) or 0)
    if _credit > 0:
        _info_parts.append(f"💳 สิทธิ์สั่งของคงเหลือ: **{_credit:,.0f} ฿**")
    if _cod_count:
        _info_parts.append(f"🚚 COD รอรับ {_cod_count} รายการ ({_cod_amt:,.0f} ฿)")
    if _pv_count:
        _info_parts.append(f"⭐ PV รอเปิดบิล {_pv_total:,.0f}")
    if _info_parts:
        st.info(" &nbsp;|&nbsp; ".join(_info_parts))

    st.divider()

    # ── ยอดขาย 7 วันล่าสุด + สินค้าที่ลูกค้าฝาก ─────────────────────────────
    _dch1, _dch2 = st.columns([3, 2])
    with _dch1:
        st.markdown("**📊 ยอดขาย 7 วันล่าสุด**")
        st.bar_chart(_chart_df, color="#D9822B", use_container_width=True)
    with _dch2:
        st.markdown("**📋 สินค้าที่ลูกค้าฝาก**")
        if not _deposits:
            st.caption("ไม่มีสินค้าฝาก")
        else:
            for _it in _deposits[:8]:
                _lc1, _lc2 = st.columns([3, 1])
                _lc1.markdown(_it["name"])
                _lc2.markdown(f"**{_it['qty']} ชิ้น**")

    st.divider()

    # ── 2 คอลัมน์: บิลล่าสุด + ลูกค้าค้างสูงสุด ──────────────────────────────
    _dl, _dr = st.columns([3, 2])

    with _dl:
        st.markdown("**🧾 บิลล่าสุด**")
        _recent_bills = pd.DataFrame()
        if not _week_df.empty:
            _recent_bills = (_week_df[_week_df["เลขที่บิล"].notna()]
                              .groupby("เลขที่บิล", as_index=False)
                              .agg(วันที่=("วันที่", "max"), ลูกค้า=("ลูกค้า", "first"),
                                   ยอดรวม=("ยอดรวม", "sum"), ค้างจ่าย=("ค้างจ่าย", "sum"))
                              .sort_values("เลขที่บิล", ascending=False)
                              .head(8))
        if _recent_bills.empty:
            st.caption("ยังไม่มีบิล")
        else:
            _recent_bills["สถานะ"] = _recent_bills["ค้างจ่าย"].apply(
                lambda x: "ชำระแล้ว" if x <= 0.01 else "ค้างชำระ")
            st.dataframe(
                _recent_bills[["เลขที่บิล", "วันที่", "ลูกค้า", "ยอดรวม", "สถานะ"]]
                    .style.format({"ยอดรวม": "{:,.0f}"})
                    .map(_style_status, subset=["สถานะ"]),
                use_container_width=True, hide_index=True,
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

        # ลูกค้าที่มี COD + ยังไม่เปิดบิล (ดึงจาก outstanding ซึ่งโหลดอยู่แล้ว)
        _cod_unbilled_custs = set()
        if not _dash_outs.empty and "สถานะจ่าย" in _dash_outs.columns:
            _cmask = (_dash_outs["สถานะจ่าย"] == "COD") & (_dash_outs["สถานะบิล"] == "ยังไม่เปิดบิล")
            _cod_unbilled_custs = set(_dash_outs.loc[_cmask, "ลูกค้า"].unique())

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
            _cod_h1, _cod_h2 = st.columns([5, 1.4])
            _cod_h1.markdown(f"**💛 COD — ติดตามสถานะ ({len(_cod_rows)} รายการ)**")
            if _cod_h2.button("🔄 อัปเดตยอด COD", key="dash_cod_sync", use_container_width=True):
                try:
                    _pending = db.get_pending_cod_tracking()
                except Exception:
                    _pending = None  # column ยังไม่มี — ดึงทั้งหมด
                if _pending is not None and len(_pending) == 0:
                    st.info("✅ COD ทุกรายการโอนแล้ว ไม่ต้องดึงข้อมูลใหม่")
                else:
                    with st.spinner("กำลังดึงข้อมูลจาก iShip..."):
                        _r = iship_api.get_cod_transfers(days_back=90)
                    if _r.get("error"):
                        st.error(f"❌ {_r['error']}")
                    else:
                        _cod_transfers = _r.get("transfers", {})
                        if _cod_transfers:
                            try:
                                db.mark_cod_transferred(list(_cod_transfers.keys()))
                            except Exception as _mct_e:
                                st.warning(f"⚠️ บันทึกสถานะ COD โอนแล้วไม่สำเร็จ: {_mct_e}")
                            try:
                                _pending_set = set(_pending or [])
                                _newly = {tn: info.get("date", "")
                                          for tn, info in _cod_transfers.items()
                                          if tn in _pending_set}
                                _n_marked = db.mark_cod_paid(_newly)
                                if _n_marked:
                                    st.success(f"✅ บันทึก COD จ่ายแล้ว {_n_marked} รายการ")
                            except Exception as _mcp_e:
                                st.error(f"❌ อัปเดตสถานะจ่าย COD ไม่สำเร็จ: {_mcp_e}")
                            st.rerun()
                        else:
                            st.info("ยังไม่มี COD ที่โอนแล้วในช่วง 90 วัน")
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
