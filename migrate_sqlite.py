from db_sqlite import db

SCHEMA = """
create table if not exists tenants (
  id text primary key,                 -- store UUID as text
  name text not null,
  slug text not null unique,
  created_at text not null default (datetime('now'))
);

create table if not exists users (
  id text primary key,
  tenant_id text not null,
  email text not null,
  full_name text not null,
  role text not null check (role in ('admin','manager','auditor')),
  password_hash text not null,
  is_active integer not null default 1,
  created_at text not null default (datetime('now')),
  unique (tenant_id, email),
  foreign key (tenant_id) references tenants(id) on delete cascade
);

create index if not exists idx_users_tenant on users(tenant_id);

create table if not exists departments (
  id text primary key,
  tenant_id text not null,
  name text not null,
  created_at text not null default (datetime('now')),
  unique (tenant_id, name),
  foreign key (tenant_id) references tenants(id) on delete cascade
);

create index if not exists idx_departments_tenant on departments(tenant_id);

create table if not exists skills_catalog (
  id text primary key,
  tenant_id text not null,
  skill_key text not null,
  skill_label text not null,
  created_at text not null default (datetime('now')),
  unique (tenant_id, skill_key),
  foreign key (tenant_id) references tenants(id) on delete cascade
);

create index if not exists idx_skills_tenant on skills_catalog(tenant_id);

create table if not exists dept_required_skills (
  id text primary key,
  tenant_id text not null,
  department_id text not null,
  skill_id text not null,
  unique (tenant_id, department_id, skill_id),
  foreign key (tenant_id) references tenants(id) on delete cascade,
  foreign key (department_id) references departments(id) on delete cascade,
  foreign key (skill_id) references skills_catalog(id) on delete cascade
);

create index if not exists idx_deptreq_tenant on dept_required_skills(tenant_id);

create table if not exists people (
  id text primary key,
  tenant_id text not null,
  full_name text not null,
  email text,
  department_id text,
  is_auditor integer not null default 0,
  is_active integer not null default 1,
  created_at text not null default (datetime('now')),
  foreign key (tenant_id) references tenants(id) on delete cascade,
  foreign key (department_id) references departments(id) on delete set null
);

create index if not exists idx_people_tenant on people(tenant_id);

create table if not exists person_skills (
  id text primary key,
  tenant_id text not null,
  person_id text not null,
  skill_id text not null,
  unique (tenant_id, person_id, skill_id),
  foreign key (tenant_id) references tenants(id) on delete cascade,
  foreign key (person_id) references people(id) on delete cascade,
  foreign key (skill_id) references skills_catalog(id) on delete cascade
);

create index if not exists idx_personskills_tenant on person_skills(tenant_id);

-- Add your audits/timetable/findings later similarly; always include tenant_id.
"""

def main():
    with db() as conn:
        conn.executescript(SCHEMA)
    print("SQLite schema ready.")

if __name__ == "__main__":
    main()
