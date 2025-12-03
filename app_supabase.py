"""
Membership ERP - Supabase-backed Streamlit app
Schema choice: A (same as your SQLite schema)
This app reads SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY from environment variables.
Create a .env locally or set the secrets in Streamlit Cloud.
"""

import os
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io
import qrcode
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# Supabase client
from supabase import create_client, Client

# Read keys from env
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    st.error("Supabase credentials not set. Please set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in environment.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

st.set_page_config(page_title="Membership ERP (Supabase)", layout="wide")
st.title("Membership ERP — Supabase backend")

# ---------- Helpers ----------
def generate_membership_no():
    # Use count from supabase
    res = supabase.rpc("get_member_count").execute()
    count = 0
    try:
        if res and res.data is not None:
            count = int(res.data)
    except Exception:
        count = 0
    return f"ZPHSI-{count+1:04d}"

def df_from_list(data):
    try:
        return pd.DataFrame(data)
    except Exception:
        return pd.DataFrame()

# ---------- CRUD operations ----------
def add_member(parent_name, phone, child_name, child_dob):
    membership_no = generate_membership_no()
    member_since = datetime.now().date().isoformat()
    payload = {
        "membership_no": membership_no,
        "parent_name": parent_name,
        "phone_number": phone,
        "child_name": child_name,
        "child_dob": child_dob,
        "member_since": member_since
    }
    res = supabase.table("members").insert(payload).execute()
    return membership_no

def get_members_df():
    res = supabase.table("members").select("*").order("member_id", desc=False).execute()
    return df_from_list(res.data)

def update_member(member_id, parent_name, phone, child_name, child_dob):
    payload = {
        "parent_name": parent_name,
        "phone_number": phone,
        "child_name": child_name,
        "child_dob": child_dob
    }
    supabase.table("members").update(payload).eq("member_id", member_id).execute()

def delete_member(member_id):
    supabase.table("members").delete().eq("member_id", member_id).execute()

def get_plans_df():
    res = supabase.table("plans").select("*").order("plan_id", desc=False).execute()
    return df_from_list(res.data)

def add_plan(plan_type, entitled_visits, per_visit_hours, price, validity_days):
    payload = {
        "plan_type": plan_type,
        "entitled_visits": entitled_visits,
        "per_visit_hours": per_visit_hours,
        "price": price,
        "validity_days": validity_days
    }
    supabase.table("plans").insert(payload).execute()

def assign_plan_to_member(member_id, plan_id, start_date=None):
    if start_date is None:
        start_date = datetime.now().date().isoformat()
    # fetch validity
    res = supabase.table("plans").select("validity_days").eq("plan_id", plan_id).execute()
    if not res.data:
        return
    validity_days = res.data[0]["validity_days"]
    start_dt = datetime.fromisoformat(start_date).date()
    end_dt = start_dt + timedelta(days=validity_days)
    payload = {
        "member_id": member_id,
        "plan_id": plan_id,
        "start_date": start_dt.isoformat(),
        "end_date": end_dt.isoformat(),
        "visits_used": 0
    }
    supabase.table("member_plan").insert(payload).execute()

def get_member_plans_df():
    sql = """
    SELECT mp.*, m.membership_no, p.plan_type, p.entitled_visits
    FROM member_plan mp
    JOIN members m ON mp.member_id = m.member_id
    JOIN plans p ON mp.plan_id = p.plan_id
    ORDER BY mp.mp_id DESC
    """
    # Try RPC; if not available, fetch client-side
    res = supabase.rpc("custom_sql_query", {"query_text": sql}).execute()
    if res.error or res.data is None:
        mp = df_from_list(supabase.table("member_plan").select("*").execute().data)
        members = df_from_list(supabase.table("members").select("member_id,membership_no").execute().data)
        plans = df_from_list(supabase.table("plans").select("plan_id,plan_type,entitled_visits").execute().data)
        if not mp.empty:
            mp = mp.merge(members, on="member_id", how="left").merge(plans, on="plan_id", how="left")
        return mp
    return df_from_list(res.data)

def record_visit(member_id, hours_used=1, notes=""):
    payload = {
        "member_id": member_id,
        "visit_date": datetime.now().isoformat(),
        "hours_used": hours_used,
        "notes": notes
    }
    supabase.table("visits").insert(payload).execute()
    # update member_plan visits_used (latest active)
    res = supabase.table("member_plan").select("*").eq("member_id", member_id).gte("end_date", datetime.now().date().isoformat()).order("mp_id", desc=True).limit(1).execute()
    if res.data:
        mp = res.data[0]
        new_visits = (mp.get("visits_used") or 0) + 1
        supabase.table("member_plan").update({"visits_used": new_visits}).eq("mp_id", mp["mp_id"]).execute()
        # if completed - certificate flow can be added here

def get_visits_df():
    res = supabase.table("visits").select("*,membership:members(membership_no)").order("visit_date", desc=True).execute()
    data = res.data or []
    rows = []
    for r in data:
        row = r.copy()
        if "membership" in row and isinstance(row["membership"], dict):
            row["membership_no"] = row["membership"].get("membership_no")
            row.pop("membership", None)
        rows.append(row)
    return df_from_list(rows)

# QR and certificate helpers
def generate_qr_image(membership_no):
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(membership_no)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white")

def generate_certificate_pdf(member_id, membership_no):
    res = supabase.table("members").select("parent_name,child_name").eq("member_id", member_id).execute()
    parent_name = child_name = ""
    if res.data:
        parent_name = res.data[0].get("parent_name", "")
        child_name = res.data[0].get("child_name", "")
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(width/2, height-150, "Certificate of Completion")
    c.setFont("Helvetica", 16)
    c.drawCentredString(width/2, height-200, f"Presented to: {child_name}")
    c.setFont("Helvetica", 12)
    c.drawCentredString(width/2, height-230, f"Parent: {parent_name}")
    c.drawCentredString(width/2, height-260, f"Membership No: {membership_no}")
    c.drawCentredString(width/2, height-290, f"Date: {datetime.now().date().isoformat()}")
    c.showPage(); c.save(); buffer.seek(0)
    return buffer.getvalue()

# UI
st.sidebar.title("Navigation")
menu = st.sidebar.selectbox("Go to", ["Home","Members","Plans","Assign Plan","Record Visit","Reports","Export Data","Settings"])

if menu == "Home":
    st.header("Membership ERP - Supabase")
    st.markdown("Manage members, plans, visits with Supabase as backend.")

if menu == "Settings":
    st.header("Settings")
    st.info("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY as environment variables or Streamlit secrets.")

if menu == "Members":
    st.header("Members")
    with st.expander("Add new member"):
        with st.form("add_member"):
            parent_name = st.text_input("Parent name")
            phone = st.text_input("Phone")
            child_name = st.text_input("Child name")
            child_dob = st.date_input("Child DOB")
            if st.form_submit_button("Add"):
                membership_no = add_member(parent_name, phone, child_name, child_dob.isoformat())
                st.toast(f"Member added: {membership_no}", icon="🎉")
                img = generate_qr_image(membership_no)
                buf = io.BytesIO(); img.save(buf, format="PNG")
                st.image(Image.open(io.BytesIO(buf.getvalue())), width=150)
                st.download_button("Download QR", data=buf.getvalue(), file_name=f"{membership_no}.png")
    st.markdown("---")
    df = get_members_df()
    if df.empty:
        st.info("No members")
    else:
        sel = st.selectbox("Select member", df["membership_no"].tolist())
        row = df[df["membership_no"]==sel].iloc[0]
        st.subheader(f"Edit: {row['membership_no']}")
        col1, col2 = st.columns([2,1])
        with col1:
            parent_new = st.text_input("Parent name", value=row["parent_name"], key=f"p{row['membership_no']}")
            phone_new = st.text_input("Phone", value=row["phone_number"], key=f"ph{row['membership_no']}")
            child_new = st.text_input("Child", value=row["child_name"], key=f"c{row['membership_no']}")
            try:
                dob_val = pd.to_datetime(row["child_dob"]).date()
            except Exception:
                dob_val = datetime.now().date()
            dob_new = st.date_input("Child DOB", value=dob_val, key=f"d{row['membership_no']}")
            if st.button("Update"):
                update_member(int(row["member_id"]), parent_new, phone_new, child_new, dob_new.isoformat())
                st.toast("Member updated", icon="✔️")
                st.rerun()
        with col2:
            st.code(str(row["membership_no"]))
            if st.button("Delete"):
                delete_member(int(row["member_id"]))
                st.toast("Member deleted", icon="🗑️")
                st.rerun()

if menu == "Plans":
    st.header("Plans")
    with st.form("add_plan"):
        plan_type = st.text_input("Plan Type")
        entitled_visits = st.number_input("Entitled visits", min_value=1, value=10)
        per_visit_hours = st.number_input("Hours per visit", min_value=1, value=1)
        price = st.number_input("Price", min_value=0.0, value=0.0)
        validity_days = st.number_input("Validity days", min_value=1, value=30)
        if st.form_submit_button("Add plan"):
            add_plan(plan_type, int(entitled_visits), int(per_visit_hours), float(price), int(validity_days))
            st.toast("Plan added", icon="✔️")
    st.markdown("---")
    st.dataframe(get_plans_df())

if menu == "Assign Plan":
    st.header("Assign Plan")
    members = get_members_df(); plans = get_plans_df()
    if members.empty or plans.empty:
        st.info("Add members and plans first")
    else:
        mem = st.selectbox("Select member", members["membership_no"].tolist())
        plan_opt = plans.apply(lambda r: f"{r['plan_id']} - {r['plan_type']} (Visits: {r['entitled_visits']})", axis=1).tolist()
        plan_sel = st.selectbox("Select plan", plan_opt)
        start_date = st.date_input("Start date", value=datetime.now().date())
        if st.button("Assign"):
            plan_id = int(plan_sel.split(" - ")[0])
            member_row = members[members["membership_no"]==mem].iloc[0]
            assign_plan_to_member(member_row["member_id"], plan_id, start_date.isoformat())
            st.toast("Plan assigned", icon="📘")

if menu == "Record Visit":
    st.header("Record Visit")
    members = get_members_df()
    if members.empty:
        st.info("Add members first")
    else:
        mem = st.selectbox("Select member", members["membership_no"].tolist())
        hours = st.number_input("Hours used", min_value=1, value=1)
        notes = st.text_input("Notes")
        if st.button("Record"):
            member_row = members[members["membership_no"]==mem].iloc[0]
            record_visit(member_row["member_id"], int(hours), notes)
            st.toast("Visit recorded", icon="⏱️")

if menu == "Reports":
    st.header("Reports")
    st.subheader("Member Plans")
    st.dataframe(get_member_plans_df())
    st.subheader("Visits")
    st.dataframe(get_visits_df())

if menu == "Export Data":
    st.header("Export")
    if st.button("Export to Excel"):
        members = get_members_df()
        plans = get_plans_df()
        member_plan = get_member_plans_df()
        visits = get_visits_df()
        # force text
        if "membership_no" in members.columns: members["membership_no"] = members["membership_no"].astype(str).apply(lambda x: "'" + x)
        if "membership_no" in member_plan.columns: member_plan["membership_no"] = member_plan["membership_no"].astype(str).apply(lambda x: "'" + x)
        if "membership_no" in visits.columns: visits["membership_no"] = visits["membership_no"].astype(str).apply(lambda x: "'" + x)
        with io.BytesIO() as buffer:
            with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
                members.to_excel(writer, sheet_name="members", index=False)
                plans.to_excel(writer, sheet_name="plans", index=False)
                member_plan.to_excel(writer, sheet_name="member_plan", index=False)
                visits.to_excel(writer, sheet_name="visits", index=False)
            st.download_button("Download Excel", data=buffer.getvalue(), file_name="membership_export.xlsx")
