"""UI for 💳 ยืมคะแนน sub-tab of 🗂️ รายละเอียดบิล — split out of bill_detail_ui.py for
size, same reason as shipment_history_ui.py/history_all_ui.py/cod_tracking_ui.py.

ลูกค้าให้ร้านเปิดบิล (สินค้าอะไรก็ได้) ไปก่อนเพื่อนับคะแนน (PV/BV) ให้ทันที แล้วลูกค้าจะ
"คืนคะแนน" ทีหลังด้วยการซื้อของจริงอีกบิลหนึ่ง — หน้านี้แค่ "แท็ก" บิลที่เปิดไปแล้วจริง
(bill_status='เปิดบิลแล้ว') ว่าเป็นยืม/คืนคะแนน ไม่ได้สร้างบิล/transactions ใหม่เอง
(การขายจริงยังทำผ่านบันทึกขายตามปกติ) — ดู database.py's get_bill_totals/get_pv_loans_df.
render(customers)."""
from datetime import date

import pandas as pd
import streamlit as st

import database as db


def render(customers: list) -> None:
    st.caption(
        "ลูกค้าให้ร้านเปิดบิล (สินค้าอะไรก็ได้) ไปก่อนเพื่อนับคะแนนให้ทันที "
        "แล้วลูกค้าจะคืนคะแนนทีหลังด้วยการซื้อของจริงอีกบิลหนึ่ง — บันทึกยอด ฿/PV/BV "
        "ที่เสียไปตอนยืม เทียบกับยอดที่ได้คืนจริง จะรู้ว่าร้านขาดทุนหรือไม่ตอนปิดยอด"
    )

    cust_map = {c["name"]: c for c in customers}
    cust_names = sorted(cust_map.keys(), key=str.casefold)

    with st.expander("➕ บันทึกยืมคะแนนใหม่"):
        _cust_sel = st.selectbox("ลูกค้า", cust_names, key="pvl_new_cust",
                                  index=None, placeholder="เลือกลูกค้า...")
        if _cust_sel:
            _cid = cust_map[_cust_sel]["id"]
            _bills_df = db.get_customer_opened_bills_df(_cid)
            if _bills_df.empty:
                st.info("ลูกค้าคนนี้ยังไม่มีบิลที่เปิดบิลแล้วเลย — ต้องบันทึกขายแบบเปิดบิลก่อน")
            else:
                _opts = [
                    f"{r['bill_no']} · {r['date']} · ฿{float(r['total_amount']):,.0f} · {float(r['pv']):,.0f} PV"
                    for _, r in _bills_df.iterrows()
                ]
                _bill_sel = st.selectbox("เลือกบิลที่เปิดไปเพื่อยืมคะแนน", _opts,
                                          key="pvl_new_bill", index=None, placeholder="เลือกบิล...")
                if _bill_sel:
                    _bill_no = _bill_sel.split(" · ")[0]
                    _totals = db.get_bill_totals(_bill_no)
                    st.markdown(
                        f"💰 ฿{_totals['baht']:,.0f}  |  ✨ {_totals['pv']:,.0f} PV  |  🔷 {_totals['bv']:,.0f} BV"
                    )
                    _lend_date = st.date_input("วันที่ยืม", value=date.today(), key="pvl_new_date")
                    _note = st.text_input("หมายเหตุ (ไม่บังคับ)", key="pvl_new_note")
                    if st.button("💾 บันทึกยืมคะแนน", key="pvl_new_save", type="primary"):
                        db.create_pv_loan(
                            customer_id=_cid, lend_date=str(_lend_date), lend_bill_no=_bill_no,
                            pv_lent=_totals["pv"], bv_lent=_totals["bv"], baht_lent=_totals["baht"],
                            notes=_note,
                        )
                        st.success(f"✅ บันทึกยืมคะแนนให้คุณ{_cust_sel} แล้ว ({_totals['pv']:,.0f} PV)")
                        st.rerun()

    st.divider()
    st.subheader("📋 รายการยืมคะแนน")
    _loans_df = db.get_pv_loans_df()
    if _loans_df.empty:
        st.info("ยังไม่มีรายการยืมคะแนนเลย")
        return

    _show_settled = st.checkbox("แสดงที่คืนครบแล้วด้วย", key="pvl_show_settled")
    _view_df = _loans_df if _show_settled else _loans_df[~_loans_df["is_settled"]]
    if _view_df.empty:
        st.success("✅ ไม่มีรายการค้างคืนเลย")

    for _, loan in _view_df.iterrows():
        _diff_baht = float(loan["baht_repaid"]) - float(loan["baht_lent"])
        _status_icon = "✅" if loan["is_settled"] else "🟡"
        with st.expander(
            f"{_status_icon} คุณ{loan['customer_name']} — ยืม {float(loan['pv_lent']):,.0f} PV "
            f"({loan['lend_date']}) · ค้างคืนอีก {float(loan['pv_remaining']):,.0f} PV"
        ):
            st.markdown(f"**บิลที่ยืม:** `{loan['lend_bill_no']}` ({loan['lend_date']})")
            st.markdown(
                f"ยืมไป: ฿{float(loan['baht_lent']):,.0f} | {float(loan['pv_lent']):,.0f} PV | "
                f"{float(loan['bv_lent']):,.0f} BV"
            )
            st.markdown(
                f"คืนแล้วรวม: ฿{float(loan['baht_repaid']):,.0f} | {float(loan['pv_repaid']):,.0f} PV | "
                f"{float(loan['bv_repaid']):,.0f} BV"
            )
            if loan["is_settled"]:
                if _diff_baht < -0.01:
                    st.error(f"⚠️ ขาดทุน ฿{abs(_diff_baht):,.0f}")
                elif _diff_baht > 0.01:
                    st.success(f"🎉 ได้คืนเกินมา ฿{_diff_baht:,.0f}")
                else:
                    st.success("✅ คืนครบเท่าทุน")
            if loan.get("notes"):
                st.caption(f"หมายเหตุ: {loan['notes']}")

            _repays_df = db.get_pv_loan_repayments_df(loan["id"])
            if not _repays_df.empty:
                st.dataframe(
                    _repays_df[["repay_date", "repay_bill_no", "pv_repaid", "bv_repaid", "baht_repaid", "notes"]]
                    .rename(columns={
                        "repay_date": "วันที่คืน", "repay_bill_no": "เลขบิล", "pv_repaid": "PV",
                        "bv_repaid": "BV", "baht_repaid": "฿", "notes": "หมายเหตุ",
                    }),
                    hide_index=True, width="stretch",
                )

            if not loan["is_settled"]:
                st.markdown("**✅ บันทึกการคืนคะแนน**")
                _bills_df2 = db.get_customer_opened_bills_df(loan["customer_id"])
                _used_bills = set(_repays_df["repay_bill_no"]) if not _repays_df.empty else set()
                _exclude = _used_bills | {loan["lend_bill_no"]}
                _bills_df2 = _bills_df2[~_bills_df2["bill_no"].isin(_exclude)] if not _bills_df2.empty else _bills_df2
                if _bills_df2.empty:
                    st.caption("ยังไม่มีบิลใหม่ของลูกค้าคนนี้ให้เลือกบันทึกคืน")
                else:
                    _opts2 = [
                        f"{r['bill_no']} · {r['date']} · ฿{float(r['total_amount']):,.0f} · {float(r['pv']):,.0f} PV"
                        for _, r in _bills_df2.iterrows()
                    ]
                    _repay_sel = st.selectbox(
                        "เลือกบิลที่ลูกค้าซื้อจริงเพื่อคืนคะแนน", _opts2,
                        key=f"pvl_repay_bill_{loan['id']}", index=None, placeholder="เลือกบิล...",
                    )
                    if _repay_sel:
                        _rbill_no = _repay_sel.split(" · ")[0]
                        _rtotals = db.get_bill_totals(_rbill_no)
                        st.markdown(
                            f"💰 ฿{_rtotals['baht']:,.0f}  |  ✨ {_rtotals['pv']:,.0f} PV  |  "
                            f"🔷 {_rtotals['bv']:,.0f} BV"
                        )
                        _repay_date = st.date_input(
                            "วันที่คืน", value=date.today(), key=f"pvl_repay_date_{loan['id']}"
                        )
                        _rnote = st.text_input("หมายเหตุ (ไม่บังคับ)", key=f"pvl_repay_note_{loan['id']}")
                        if st.button("💾 บันทึกการคืนคะแนน", key=f"pvl_repay_save_{loan['id']}", type="primary"):
                            db.add_pv_loan_repayment(
                                loan_id=loan["id"], repay_date=str(_repay_date), repay_bill_no=_rbill_no,
                                pv_repaid=_rtotals["pv"], bv_repaid=_rtotals["bv"], baht_repaid=_rtotals["baht"],
                                notes=_rnote,
                            )
                            st.success("✅ บันทึกการคืนคะแนนแล้ว")
                            st.rerun()

            if st.button("🗑️ ลบรายการยืมนี้ (รวมประวัติคืนทั้งหมด)", key=f"pvl_delete_{loan['id']}"):
                db.delete_pv_loan(loan["id"])
                st.rerun()
