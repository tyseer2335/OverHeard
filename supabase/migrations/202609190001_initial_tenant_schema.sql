create extension if not exists pgcrypto;

create table public.organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(name) between 1 and 100),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now()
);

create table public.organization_members (
  organization_id uuid not null references public.organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null default 'member' check (role in ('owner', 'admin', 'member')),
  created_at timestamptz not null default now(),
  primary key (organization_id, user_id)
);

create table public.products (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 100),
  youtube_query text not null check (char_length(youtube_query) between 1 and 200),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, organization_id)
);

create unique index products_organization_name_unique
  on public.products (organization_id, lower(name));

create table public.ingestion_jobs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  product_id uuid not null,
  requested_by uuid not null references auth.users(id) on delete restrict,
  status text not null default 'queued'
    check (status in ('queued', 'running', 'completed', 'failed')),
  videos_found integer not null default 0 check (videos_found >= 0),
  videos_processed integer not null default 0 check (videos_processed >= 0),
  comments_indexed integer not null default 0 check (comments_indexed >= 0),
  error text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  foreign key (product_id, organization_id)
    references public.products(id, organization_id) on delete cascade
);

create index products_organization_id_idx on public.products (organization_id);
create index ingestion_jobs_product_id_created_at_idx
  on public.ingestion_jobs (product_id, created_at desc);

create or replace function public.set_updated_at()
returns trigger language plpgsql set search_path = '' as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger products_set_updated_at
before update on public.products
for each row execute function public.set_updated_at();

create or replace function public.is_org_member(target_organization_id uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.organization_members
    where organization_id = target_organization_id
      and user_id = (select auth.uid())
  );
$$;

create or replace function public.has_org_role(
  target_organization_id uuid,
  allowed_roles text[]
)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.organization_members
    where organization_id = target_organization_id
      and user_id = (select auth.uid())
      and role = any(allowed_roles)
  );
$$;

create or replace function public.create_organization(p_name text)
returns uuid language plpgsql security definer set search_path = '' as $$
declare
  new_id uuid;
  caller_id uuid := auth.uid();
begin
  if caller_id is null then
    raise exception 'Authentication required';
  end if;
  if char_length(trim(p_name)) not between 1 and 100 then
    raise exception 'Organization name must be between 1 and 100 characters';
  end if;

  insert into public.organizations (name, created_by)
  values (trim(p_name), caller_id)
  returning id into new_id;

  insert into public.organization_members (organization_id, user_id, role)
  values (new_id, caller_id, 'owner');
  return new_id;
end;
$$;

alter table public.organizations enable row level security;
alter table public.organization_members enable row level security;
alter table public.products enable row level security;
alter table public.ingestion_jobs enable row level security;

create policy organizations_select_members on public.organizations
for select to authenticated using (public.is_org_member(id));
create policy organizations_update_admins on public.organizations
for update to authenticated
using (public.has_org_role(id, array['owner', 'admin']))
with check (public.has_org_role(id, array['owner', 'admin']));

create policy members_select_members on public.organization_members
for select to authenticated using (public.is_org_member(organization_id));
create policy members_insert_admins on public.organization_members
for insert to authenticated
with check (public.has_org_role(organization_id, array['owner', 'admin']));
create policy members_update_admins on public.organization_members
for update to authenticated
using (public.has_org_role(organization_id, array['owner', 'admin']))
with check (public.has_org_role(organization_id, array['owner', 'admin']));
create policy members_delete_admins on public.organization_members
for delete to authenticated
using (public.has_org_role(organization_id, array['owner', 'admin']));

create policy products_select_members on public.products
for select to authenticated using (public.is_org_member(organization_id));
create policy products_insert_admins on public.products
for insert to authenticated
with check (public.has_org_role(organization_id, array['owner', 'admin']));
create policy products_update_admins on public.products
for update to authenticated
using (public.has_org_role(organization_id, array['owner', 'admin']))
with check (public.has_org_role(organization_id, array['owner', 'admin']));
create policy products_delete_admins on public.products
for delete to authenticated
using (public.has_org_role(organization_id, array['owner', 'admin']));

create policy jobs_select_members on public.ingestion_jobs
for select to authenticated using (public.is_org_member(organization_id));
create policy jobs_insert_members on public.ingestion_jobs
for insert to authenticated
with check (
  public.is_org_member(organization_id)
  and requested_by = (select auth.uid())
);
create policy jobs_update_requester on public.ingestion_jobs
for update to authenticated
using (
  public.is_org_member(organization_id)
  and requested_by = (select auth.uid())
)
with check (
  public.is_org_member(organization_id)
  and requested_by = (select auth.uid())
);

revoke all on public.organizations from anon;
revoke all on public.organization_members from anon;
revoke all on public.products from anon;
revoke all on public.ingestion_jobs from anon;
grant select, update on public.organizations to authenticated;
grant select, insert, update, delete on public.organization_members to authenticated;
grant select, insert, update, delete on public.products to authenticated;
grant select, insert, update on public.ingestion_jobs to authenticated;
revoke execute on function public.create_organization(text) from public;
grant execute on function public.create_organization(text) to authenticated;

revoke execute on function public.is_org_member(uuid) from public;
revoke execute on function public.has_org_role(uuid, text[]) from public;
grant execute on function public.is_org_member(uuid) to authenticated;
grant execute on function public.has_org_role(uuid, text[]) to authenticated;
