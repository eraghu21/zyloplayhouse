"""
app.py - Membership ERP (Supabase-backed, Full CRM Suite)

Usage:
- Set these secrets in Streamlit Cloud or environment:
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY

- Deploy: streamlit run app.py

Notes:
- This file uses the Supabase service_role key for admin operations.
- For production security, consider anon + RLS and server-side functions.
- Option D helper functions are included at the bottom to create an admin user and test basic flows.
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
import hashlib
import typing as T

try:
    from supabase import create_client, Client
except Exception as e:
    st = None
    raise ImportError("supabase package not installed. Run `pip install supabase`") from e

# --- Config / Secrets ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Supabase credentials not found. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in environment or Streamlit secrets.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

st.set_page_config(page_title="Membership ERP - CRM Suite", layout="wide")
st.title("Membership ERP — CRM / Business Suite (Supabase)")

# ---------- Utilities ----------
def hash_password(pw: str) -> str:
    salt = "erp_salt_v1"
    return hashlib.sha256((salt + pw).encode()).hexdigest()

def df_from_res(res) -> pd.DataFrame:
    try:
        return pd.DataFrame(res.data or [])
    except Exception:
        return pd.DataFrame()

def safe_get(res, key, default=None):
    try:
        return res.data[0].get(key, default) if res and res.data else default
    except Exception:
        return default

# ---------- Auth / Users (staff) ----------
def create_staff_user(email: str, name: str, password: str, role: str = "staff") -> T.Tuple[bool,str]:
    # Insert only if not exists
    existing = supabase.table("users").select("user_id").eq("email", email).execute()
    if existing.data:
        return False, "User already exists"
    payload = {"email": email, "name": name, "password_hash": hash_password(password), "role": role}
    supabase.table("users").insert(payload).execute()
    return True, "Created"

def verify_staff(email: str, password: str) -> T.Tuple[bool, T.Optional[str], T.Optional[str]]:
    res = supabase.table("users").select("user_id,password_hash,role,name").eq("email", email).execute()
    if not res.data:
        return False, None, None
    rec = res.data[0]
    return rec["password_hash"] == hash_password(password), rec.get("role"), rec.get("name")

# ---------- Members ----------
def generate_membership_no() -> str:
    res = supabase.rpc("get_member_count").execute()
    try:
        # supabase rpc may return integer directly or list etc.
        count = int(res.data) if isinstance(res.data, (int, float, str)) else int(res.data or 0)
    except Exception:
        # fallback: count rows
        try:
            rows = supabase.table("members").select("member_id", count="count").execute()
            count = len(rows.data or [])
        except Exception:
            count = 0
    return f"ZPHSI-{count+1:04d}"

def add_member(parent_name: str, phone: str, child_name: str, child_dob: str, parent_email: T.Optional[str] = None) -> str:
    membership_no = generate_membership_no()
    payload = {
        "membership_no": membership_no,
        "parent_name": parent_name,
        "phone_number": phone,
        "child_name": child_name,
        "child_dob": child_dob,
        "parent_email": parent_email,
        "member_since": datetime.now().date().isoformat()
    }
    supabase.table("members").insert(payload).execute()
    return membership_no

def get_members_df() -> pd.DataFrame:
    res = supabase.table("members").select("*").order("member_id", desc=False).execute()
    return df_from_res(res)

def update_member(member_id: int, parent_name: str, phone: str, child_name: str, child_dob: str, parent_email: T.Optional[str] = None):
    payload = {
        "parent_name": parent_name,
        "phone_number": phone,
        "child_name": child_name,
        "child_dob": child_dob,
        "parent_email": parent_email
    }
    supabase.table("members").update(payload).eq("member_id", member_id).execute()

def delete_member(member_id: int):
    supabase.table("members").delete().eq("member_id", member_id).execute()

# ---------- Plans ----------
def add_plan(plan_name: str, price: float, duration_days: int):
    payload = {"plan_name": plan_name, "price": price, "duration_days": duration_days}
    supabase.table("plans").insert(payload).execute()

def get_plans_df() -> pd.DataFrame:
    res = supabase.table("plans").select("*").order("plan_id", desc=False).execute()
    return df_from_res(res)

def assign_plan(member_id: int, plan_id: int, start_date: T.Optional[str] = None):
    if start_date is None:
        start_date = datetime.now().date().isoformat()
    res = supabase.table("plans").select("duration_days").eq("plan_id", plan_id).execute()
    if not res.data:
        return
    validity = res.data[0]["duration_days"]
    s = pd.to_datetime(start_date).date()
    e = s + timedelta(days=int(validity))
    payload = {"member_id": member_id, "plan_id": plan_id, "start_date": s.isoformat(), "end_date": e.isoformat(), "visits_used": 0}
    supabase.table("member_plan").insert(payload).execute()

def get_member_plans_df() -> pd.DataFrame:
    mp = df_from_res(supabase.table("member_plan").select("*").order("mp_id", desc=False).execute())
    members = df_from_res(supabase.table("members").select("member_id,membership_no,parent_name").execute())
    plans = df_from_res(supabase.table("plans").select("plan_id,plan_name,duration_days").execute())
    if not mp.empty:
        mp = mp.merge(members, on="member_id", how="left").merge(plans, on="plan_id", how="left")
    return mp

# ---------- Visits ----------
def record_visit(member_id: int, hours_used: int = 1, notes: str = ""):
    payload = {"member_id": member_id, "visit_date": datetime.now().isoformat(), "hours_used": hours_used, "notes": notes}
    supabase.table("visits").insert(payload).execute()
    # update member_plan visits_used
    res = supabase.table("member_plan").select("*").eq("member_id", member_id).gte("end_date", datetime.now().date().isoformat()).order("mp_id", desc=True).limit(1).execute()
    if res.data:
        mp = res.data[0]
        new_visits = (mp.get("visits_used") or 0) + 1
        supabase.table("member_plan").update({"visits_used": new_visits}).eq("mp_id", mp["mp_id"]).execute()

def get_visits_df() -> pd.DataFrame:
    # select nested member membership_no via projection
    res = supabase.table("visits").select("*,member:members(membership_no)").order("visit_date", desc=True).execute()
    data = res.data or []
    rows = []
    for r in data:
        row = dict(r)
        if "member" in row and isinstance(row["member"], dict):
            row["membership_no"] = row["member"].get("membership_no")
            row.pop("member", None)
        rows.append(row)
    return df_from_res(rows)

# ---------- Invoices & Payments ----------
def create_invoice(member_id: int, amount: float, description: str):
    payload = {"member_id": member_id, "amount": amount, "description": description, "status": "unpaid", "invoice_date": datetime.now().date().isoformat()}
    supabase.table("invoices").insert(payload).execute()

def pay_invoice(invoice_id: int, amount_paid: float, method: str = "offline", note: T.Optional[str] = None):
    supabase.table("payments").insert({"invoice_id": invoice_id, "amount_paid": amount_paid, "method": method, "paid_at": datetime.now().isoformat(), "note": note}).execute()
    supabase.table("invoices").update({"status": "paid"}).eq("invoice_id", invoice_id).execute()

def get_invoices_df() -> pd.DataFrame:
    inv = df_from_res(supabase.table("invoices").select("*").order("invoice_id", desc=True).execute())
    members = df_from_res(supabase.table("members").select("member_id,membership_no").execute())
    if not inv.empty:
        inv = inv.merge(members, on="member_id", how="left")
    return inv

# ---------- QR & PDF helpers ----------
def generate_qr_image(membership_no: str):
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(membership_no)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white")

def generate_invoice_pdf(invoice_row: dict) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    c.setFont("Helvetica-Bold", 20)
    c.drawString(80, height-80, "Invoice")
    c.setFont("Helvetica", 12)
    y = height - 120
    for k, v in invoice_row.items():
        c.drawString(80, y, f"{k}: {v}")
        y -= 20
    c.showPage(); c.save(); buffer.seek(0)
    return buffer.getvalue()

# ---------- UI ----------
if "staff_user" not in st.session_state:
    st.session_state.staff_user = None

pages = ["Login","Dashboard","Members","Plans","Member Plans","Visits","Invoices","Reports","Export","Settings","OptionD"]
page = st.sidebar.selectbox("Page", pages)

# LOGIN
if page == "Login":
    st.header("Staff Login")
    email = st.text_input("Email")
    pwd = st.text_input("Password", type="password")
    if st.button("Login"):
        ok, role, name = verify_staff(email, pwd)
        if ok:
            st.session_state.staff_user = {"email": email, "role": role, "name": name}
            st.toast(f"Welcome {name}", icon="✔️")
            st.rerun()
        else:
            st.error("Invalid credentials")

if page != "Login" and not st.session_state.staff_user:
    st.warning("Please login (Login page)")
    st.stop()

# DASHBOARD
if page == "Dashboard":
    st.header("Dashboard")
    members = get_members_df()
    plans = get_plans_df()
    visits = get_visits_df()
    st.metric("Total Members", len(members))
    st.metric("Total Plans", len(plans))
    visits_30 = 0
    if not visits.empty and "visit_date" in visits.columns:
        try:
            visits_30 = len(visits[pd.to_datetime(visits["visit_date"]) >= (datetime.now() - timedelta(days=30)).isoformat()])
        except Exception:
            visits_30 = len(visits)
    st.metric("Visits (last 30 days)", visits_30)
    if st.button("Create sample member"):
        add_member("Parent Sample","9999999999","Child Sample", datetime.now().date().isoformat())
        st.toast("Sample member added", icon="🎉")
        st.rerun()

# MEMBERS
if page == "Members":
    st.header("Members")
    with st.expander("Add Member"):
        with st.form("add_member_form"):
            parent = st.text_input("Parent name")
            phone = st.text_input("Phone")
            child = st.text_input("Child name")
            dob = st.date_input("Child DOB")
            parent_email = st.text_input("Parent email (optional)")
            if st.form_submit_button("Add Member"):
                mn = add_member(parent, phone, child, dob.isoformat(), parent_email or None)
                st.toast(f"Member added: {mn}", icon="🎉")
                st.rerun()
    df = get_members_df()
    if df.empty:
        st.info("No members")
    else:
        st.dataframe(df)
        sel = st.selectbox("Select Membership No to edit", df["membership_no"].tolist())
        row = df[df["membership_no"]==sel].iloc[0]
        st.subheader("Edit selected member")
        col1, col2 = st.columns([2,1])
        with col1:
            pnew = st.text_input("Parent", value=row["parent_name"], key="pe")
            phone_new = st.text_input("Phone", value=row["phone_number"], key="phe")
            child_new = st.text_input("Child", value=row["child_name"], key="ce")
            try:
                dobval = pd.to_datetime(row["child_dob"]).date()
            except Exception:
                dobval = datetime.now().date()
            dob_new = st.date_input("DOB", value=dobval, key="de")
            email_new = st.text_input("Parent email", value=row.get("parent_email",""), key="ee")
            if st.button("Update Member"):
                update_member(row["member_id"], pnew, phone_new, child_new, dob_new.isoformat(), email_new or None)
                st.toast("Member updated", icon="✔️")
                st.rerun()
        with col2:
            if st.button("Delete Member"):
                delete_member(row["member_id"])
                st.toast("Member deleted", icon="🗑️")
                st.rerun()

# PLANS
if page == "Plans":
    st.header("Plans")
    with st.form("add_plan_form"):
        plan_name = st.text_input("Plan name")
        price = st.number_input("Price", min_value=0.0, value=0.0)
        duration = st.number_input("Duration days", min_value=1, value=30)
        if st.form_submit_button("Add Plan"):
            add_plan(plan_name, price, int(duration))
            st.toast("Plan added", icon="✔️")
            st.rerun()
    st.dataframe(get_plans_df())

# MEMBER PLANS
if page == "Member Plans":
    st.header("Assign / View Member Plans")
    members = get_members_df()
    plans = get_plans_df()
    if members.empty or plans.empty:
        st.info("Add members and plans first")
    else:
        msel = st.selectbox("Select member", members["membership_no"].tolist())
        psel = st.selectbox("Select plan", plans["plan_name"].tolist())
        start_date = st.date_input("Start date", value=datetime.now().date())
        if st.button("Assign Plan"):
            member_row = members[members["membership_no"]==msel].iloc[0]
            plan_row = plans[plans["plan_name"]==psel].iloc[0]
            assign_plan(member_row["member_id"], plan_row["plan_id"], start_date.isoformat())
            st.toast("Plan assigned", icon="📘")
            st.rerun()
    st.subheader("All Member Plans")
    st.dataframe(get_member_plans_df())

# VISITS
if page == "Visits":
    st.header("Record Visit")
    members = get_members_df()
    if members.empty:
        st.info("Add members first")
    else:
        msel = st.selectbox("Select member", members["membership_no"].tolist())
        hours = st.number_input("Hours used", min_value=1, value=1)
        notes = st.text_input("Notes")
        if st.button("Record Visit"):
            member_row = members[members["membership_no"]==msel].iloc[0]
            record_visit(member_row["member_id"], int(hours), notes)
            st.toast("Visit recorded", icon="⏱️")
            st.rerun()
    st.subheader("Recent Visits")
    st.dataframe(get_visits_df())

# INVOICES
if page == "Invoices":
    st.header("Invoices & Payments")
    members = get_members_df()
    if members.empty:
        st.info("Add members first")
    else:
        msel = st.selectbox("Select member for invoice", members["membership_no"].tolist())
        amount = st.number_input("Amount", min_value=0.0, value=0.0)
        desc = st.text_input("Description")
        if st.button("Create Invoice"):
            mr = members[members["membership_no"]==msel].iloc[0]
            create_invoice(mr["member_id"], float(amount), desc)
            st.toast("Invoice created", icon="🧾")
            st.rerun()
    st.subheader("All Invoices")
    st.dataframe(get_invoices_df())
    invsel = st.text_input("Enter invoice_id to mark paid")
    if st.button("Mark Paid"):
        if invsel.strip():
            pay_invoice(int(invsel.strip()), 0.0, method="offline", note="Marked paid by staff")
            st.toast("Invoice paid", icon="💰")
            st.rerun()

# REPORTS
if page == "Reports":
    st.header("Reports Dashboard")
    st.subheader("Members")
    st.dataframe(get_members_df())
    st.subheader("Member Plans")
    st.dataframe(get_member_plans_df())
    st.subheader("Visits")
    st.dataframe(get_visits_df())
    st.subheader("Invoices")
    st.dataframe(get_invoices_df())

# EXPORT
if page == "Export":
    st.header("Export Data")
    if st.button("Export all to Excel"):
        members = get_members_df()
        plans = get_plans_df()
        mp = get_member_plans_df()
        visits = get_visits_df()
        invoices = get_invoices_df()
        # ensure membership_no preserved as text in Excel
        for df in (members, mp, visits, invoices):
            if "membership_no" in df.columns:
                df["membership_no"] = df["membership_no"].astype(str).apply(lambda x: "'" + x)
        with io.BytesIO() as buffer:
            with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
                members.to_excel(writer, sheet_name="members", index=False)
                plans.to_excel(writer, sheet_name="plans", index=False)
                mp.to_excel(writer, sheet_name="member_plan", index=False)
                visits.to_excel(writer, sheet_name="visits", index=False)
                invoices.to_excel(writer, sheet_name="invoices", index=False)
            st.download_button("Download Excel", data=buffer.getvalue(), file_name="membership_export.xlsx")

# SETTINGS
if page == "Settings":
    st.header("Settings & Notes")
    st.info("Supabase SERVICE_ROLE key is used for admin operations. For production, consider RLS and using anon keys plus server functions.")
    st.markdown("Notifications and email sending can be integrated here (SMTP).")

# OPTION D - Admin creation & quick test helpers
if page == "OptionD":
    st.header("Option D — Create Admin & Test")
    st.markdown("Use this page to create an admin user and run quick tests.")
    with st.expander("Create Admin User"):
        email = st.text_input("Admin email", key="adm_email")
        name = st.text_input("Admin name", key="adm_name")
        pwd = st.text_input("Admin password", type="password", key="adm_pwd")
        if st.button("Create Admin"):
            ok, msg = create_staff_user(email, name, pwd, role="admin")
            if ok:
                st.toast("Admin created", icon="✔️")
            else:
                st.error(msg)
    st.markdown("---")
    st.markdown("### Quick tests")
    if st.button("Add sample member"):
        mn = add_member("Test Parent","9999999999","Test Child", datetime.now().date().isoformat())
        st.toast(f"Added {mn}", icon="🎉")
    if st.button("Run all-read test"):
        try:
            _ = get_members_df()
            _ = get_plans_df()
            _ = get_member_plans_df()
            _ = get_visits_df()
            _ = get_invoices_df()
            st.success("Read tests OK")
        except Exception as e:
            st.error(f"Read tests failed: {e}")
