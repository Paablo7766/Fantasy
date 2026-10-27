-- DDL de LALIGA Fantasy para PostgreSQL / Supabase.
-- Ejecutar en el SQL Editor del proyecto (o `supabase db query -f scripts/init_supabase.sql`).
-- El backend usa la service role key: RLS queda activo y el rol service_role lo omite.

create table if not exists public.player_links (
    player_id text not null,
    source text not null,
    external_id text,
    external_name text not null,
    club text,
    position text,
    confidence double precision not null,
    manual boolean not null default false,
    updated_at double precision not null,
    primary key (player_id, source)
);

create index if not exists player_links_source_idx
    on public.player_links (source);

create table if not exists public.match_audits (
    player_id text not null,
    source text not null,
    external_name text,
    candidate_name text,
    confidence double precision not null,
    reason text not null,
    created_at double precision not null,
    primary key (player_id, source)
);

create index if not exists match_audits_source_idx
    on public.match_audits (source);

create table if not exists public.scraper_cache (
    cache_key text primary key,
    url text not null,
    kind text not null,
    status_code integer not null,
    stored_at double precision not null,
    expires_at double precision not null,
    body text not null
);

create index if not exists scraper_cache_expires_idx
    on public.scraper_cache (expires_at);

create table if not exists public.cash_ledgers (
    league_id text not null,
    team_id text not null,
    manager_name text,
    initial_budget_eur bigint,
    premiums_eur bigint not null default 0,
    purchases_eur bigint not null default 0,
    clauses_eur bigint not null default 0,
    sales_eur bigint not null default 0,
    reconstructed_cash_eur bigint,
    observed_cash_eur bigint,
    balanced boolean,
    gap_eur bigint,
    ignored_events integer not null default 0,
    events jsonb not null default '[]'::jsonb,
    fingerprint text,
    updated_at double precision not null,
    primary key (league_id, team_id)
);

create index if not exists cash_ledgers_league_idx
    on public.cash_ledgers (league_id);

create table if not exists public.price_snapshots (
    player_id text not null,
    day text not null,
    league_id text,
    market_value bigint,
    market_value_change bigint,
    stored_at double precision not null,
    primary key (player_id, day)
);

create index if not exists price_snapshots_league_day_idx
    on public.price_snapshots (league_id, day);

create index if not exists price_snapshots_day_idx
    on public.price_snapshots (day);

alter table public.player_links enable row level security;
alter table public.match_audits enable row level security;
alter table public.scraper_cache enable row level security;
alter table public.cash_ledgers enable row level security;
alter table public.price_snapshots enable row level security;
