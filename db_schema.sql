-- Supabase SQL schema for Membership ERP (Schema A)
create table if not exists users (
  user_id serial primary key,
  email text unique,
  name text,
  password_hash text,
  role text
);

create table if not exists members (
  member_id serial primary key,
  membership_no text unique,
  parent_name text,
  phone_number text,
  child_name text,
  child_dob date,
  member_since date
);

create table if not exists plans (
  plan_id serial primary key,
  plan_type text,
  entitled_visits integer,
  per_visit_hours integer,
  price numeric,
  validity_days integer
);

create table if not exists member_plan (
  mp_id serial primary key,
  member_id integer references members(member_id),
  plan_id integer references plans(plan_id),
  start_date date,
  end_date date,
  visits_used integer default 0
);

create table if not exists visits (
  visit_id serial primary key,
  member_id integer references members(member_id),
  visit_date timestamptz,
  hours_used integer,
  notes text
);

-- helper RPC to get member count (for membership_no generation)
create or replace function get_member_count() returns integer language sql stable as $$
  select count(*) from members;
$$;

-- helper RPC to run arbitrary SQL if needed (use with caution)
-- NOTE: Supabase by default doesn't allow executing arbitrary SQL in RPC like this without additional setup.
-- The app uses fallback merging client-side if RPC unavailable.
