# Membership ERP Streamlit App with Supabase
import streamlit as st
from supabase import create_client, Client
from datetime import datetime, timedelta
import pandas as pd
import hashlib
import io

# ---------------- Supabase Setup ----------------
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------- Helpers ----------------
def hash_password(password: str) -> str:
    salt = "streamlit_salt_v1"
    return hashlib.sha256((salt + password).encode()).hexdigest()

def verify_staff(email: str, password: str):
    res = supabase.table("users").select("user_id,password_hash,role,name").eq("email", email).execute()
    data = res.data
    if not data:
        return False, None, None
    user = data[0]
    if user["password_hash"] == hash_password(password):
        return True, user["role"], user["name"]
    return False, None, None

def add_staff(email, name, password, role="staff"):
    supabase.table("users").insert({
        "email": email,
        "name": name,
        "password_hash": hash_password(password),
        "role": role
    }).execute()

# ---------------- Member Functions ----------------
def add_member(parent_name, phone, child_name, child_dob):
    member_since = datetime.now().date().isoformat()
    res = supabase.table("members").insert({
        "parent_name": parent_name,
        "phone_number": phone,
        "child_name": child_name,
        "child_dob": child_dob,
        "member_since": member_since
    }).execute()
    return res.data[0]["member_id"]

def update_member(member_id, parent_name, phone, child_name, child_dob):
    supabase.table("members").update({
        "parent_name": parent_name,
        "phone_number": phone,
        "child_name": child_name,
        "child_dob": child_dob
    }).eq("member_id", member_id).execute()

def delete_member(member_id):
    supabase.table("members").delete().eq("member_id", member_id).execute()

def get_members_df():
    res = supabase.table("members").select("*").order("member_id", desc=False).execute()
    df = pd.DataFrame(res.data)
    return df

# ---------------- Plans ----------------
def add_plan(plan_type, entitled_visits, per_visit_hours, price, validity_days):
    supabase.table("plans").insert({
        "plan_type": plan_type,
        "entitled_visits": entitled_visits,
        "per_visit_hours": per_visit_hours,
        "price": price,
        "validity_days": validity_days
    }).execute()

def get_plans_df():
    res = supabase.table("plans").select("*").order("plan_id", desc=False).execute()
    return pd.DataFrame(res.data)

# ---------------- Member Plan ----------------
def assign_plan_to_member(member_id, plan_id, start_date=None):
    if start_date is None:
        start_date = datetime.now().date()
    else:
        start_date = datetime.fromisoformat(start_date).date()
    plan = supabase.table("plans").select("validity_days,entitled_visits").eq("plan_id", plan_id).execute().data[0]
    end_date = start_date + timedelta(days=plan["validity_days"])
    supabase.table("member_plan").insert({
        "member_id": member_id,
        "plan_id": plan_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "visits_used": 0
    }).execute()

def get_member_plans_df():
    res = supabase.table("member_plan").select("*,member_id(*),plan_id(*)").order("mp_id", desc=True).execute()
    df = pd.DataFrame(res.data)
    return df

# ---------------- Visits ----------------
def record_visit(member_id, hours_used=1, notes=""):
    visit_date = datetime.now().isoformat()
    supabase.table("visits").insert({
        "member_id": member_id,
        "visit_date": visit_date,
        "hours_used": hours_used,
        "notes": notes
    }).execute()

def get_visits_df():
    res = supabase.table("visits").select("*,member_id(*)").order("visit_date", desc=True).execute()
    df = pd.DataFrame(res.data)
    return df

# ---------------- Streamlit UI ----------------
st.set_page_config(page_title="Membership ERP", layout="wide")
st.title("Membership ERP (Supabase)")

# Session
if "user" not in st.session_state: st.session_state.user = None

menu = st.sidebar.selectbox("Go to", ["Home","Login","Members","Plans","Assign Plan","Record Visit","Reports","Option D Admin"])

# --- Home ---
if menu == "Home":
    st.markdown("### Quick actions")
    st.markdown("- Login to manage the ERP")

# --- Login ---
if menu == "Login":
    st.header("Login")
    email = st.text_input("Email")
    pwd = st.text_input("Password", type="password")
    if st.button("Login"):
        ok, role, name = verify_staff(email, pwd)
        if ok:
            st.session_state.user = {"email": email, "role": role, "name": name}
            st.success(f"Logged in as {name} ({role})")
        else:
            st.error("Invalid credentials")

# Protected pages
if menu in ["Members","Plans","Assign Plan","Record Visit","Reports","Option D Admin"] and not st.session_state.get("user"):
    st.error("Please login first via the Login page")

# --- Members ---
if menu == "Members" and st.session_state.get("user"):
    st.subheader("➕ Add / Edit Members")
    with st.form("add_member"):
        parent_name = st.text_input("Parent Name *")
        phone = st.text_input("Phone Number *")
        child_name = st.text_input("Child Name *")
        child_dob = st.date_input("Child DOB")
        submitted = st.form_submit_button("Add Member")
        if submitted:
            if not parent_name or not phone or not child_name:
                st.error("Please fill required fields")
            else:
                member_id = add_member(parent_name, phone, child_name, child_dob.isoformat())
                st.toast("Saved successfully!", icon="✔️")

    st.markdown("---")
    st.subheader("👥 Existing Members")
    df = get_members_df()
    if not df.empty:
        sel = st.selectbox("Select member to edit", df["member_id"].tolist())
        if sel:
            row = df[df["member_id"]==sel].iloc[0]
            parent_new = st.text_input("Parent Name", value=row["parent_name"], key="pedit")
            phone_new = st.text_input("Phone Number", value=row["phone_number"], key="ph_edit")
            child_new = st.text_input("Child Name", value=row["child_name"], key="c_edit")
            dob_new = st.date_input("Child DOB", value=pd.to_datetime(row["child_dob"]).date(), key="dob_edit")
            if st.button("Update Member"):
                update_member(sel, parent_new, phone_new, child_new, dob_new.isoformat())
                st.toast("Saved successfully!", icon="✔️")
            if st.button("Delete Member"):
                delete_member(sel)
                st.toast("Deleted successfully!", icon="✔️")

# --- Plans ---
if menu == "Plans" and st.session_state.get("user"):
    st.subheader("Manage Plans")
    with st.form("add_plan"):
        plan_type = st.text_input("Plan Type")
        entitled_visits = st.number_input("No. of Visits", min_value=1, value=10)
        per_visit_hours = st.number_input("Hours per Visit", min_value=1, value=1)
        price = st.number_input("Price", min_value=0.0, value=0.0)
        validity_days = st.number_input("Validity (days)", min_value=1, value=30)
        if st.form_submit_button("Add Plan"):
            add_plan(plan_type, int(entitled_visits), int(per_visit_hours), float(price), int(validity_days))
            st.toast("Saved successfully!", icon="✔️")
    st.markdown("---")
    st.subheader("Existing Plans")
    st.dataframe(get_plans_df())

# --- Assign Plan ---
if menu == "Assign Plan" and st.session_state.get("user"):
    st.subheader("Assign Plan to Member")
    members_df = get_members_df()
    plans_df = get_plans_df()
    if members_df.empty or plans_df.empty:
        st.info("Add members and plans first")
    else:
        mem_sel = st.selectbox("Select Member", members_df["member_id"].tolist())
        plan_sel = st.selectbox("Select Plan", plans_df["plan_id"].tolist())
        start_date = st.date_input("Start Date", value=datetime.now().date())
        if st.button("Assign Plan"):
            assign_plan_to_member(mem_sel, plan_sel, start_date.isoformat())
            st.toast("Saved successfully!", icon="✔️")

# --- Record Visit ---
if menu == "Record Visit" and st.session_state.get("user"):
    st.subheader("Record Visit / Check-in")
    members_df = get_members_df()
    if not members_df.empty:
        mem_sel = st.selectbox("Select Member for Visit", members_df["member_id"].tolist())
        hours_used = st.number_input("Hours Used", min_value=1, value=1)
        notes = st.text_input("Notes (optional)")
        if st.button("Record Visit"):
            record_visit(mem_sel, int(hours_used), notes)
            st.toast("Saved successfully!", icon="✔️")

# --- Reports ---
if menu == "Reports" and st.session_state.get("user"):
    st.subheader("Member Plans")
    st.dataframe(get_member_plans_df())
    st.subheader("Visits")
    st.dataframe(get_visits_df())

# --- Option D Admin Creator ---
if menu == "Option D Admin" and st.session_state.get("user"):
    st.subheader("Create Admin/Staff User")
    with st.form("add_admin"):
        email = st.text_input("Email")
        name = st.text_input("Name")
        password = st.text_input("Password", type="password")
        role = st.selectbox("Role", ["admin","staff"])
        if st.form_submit_button("Create User"):
            add_staff(email, name, password, role)
            st.toast("User created successfully!", icon="✔️")
