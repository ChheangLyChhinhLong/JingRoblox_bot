create extension if not exists pgcrypto;

create table if not exists public.users (
    telegram_id bigint primary key,
    username text,
    first_name text not null,
    language text not null default 'km' check (language in ('km', 'en')),
    created_at timestamptz not null default now()
);

create table if not exists public.bot_settings (
    key text primary key,
    value text not null default ''
);

create table if not exists public.categories (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    description text not null default '',
    active boolean not null default true,
    sort_order integer not null default 0
);

create table if not exists public.products (
    id uuid primary key default gen_random_uuid(),
    category_id uuid not null references public.categories(id),
    name text not null,
    description text not null default '',
    price numeric(10, 2) not null check (price > 0),
    active boolean not null default true,
    sort_order integer not null default 0
);

create table if not exists public.orders (
    id uuid primary key default gen_random_uuid(),
    chat_id bigint not null,
    product_id uuid not null references public.products(id),
    quantity integer not null check (quantity > 0),
    total numeric(10, 2) not null,
    status text not null default 'pending' check (status in ('pending', 'paid', 'expired', 'failed', 'cancelled')),
    transaction_id text unique,
    payment_url text,
    created_at timestamptz not null default now(),
    delivery_claimed_at timestamptz,
    delivered_at timestamptz
);

alter table public.orders add column if not exists payment_message_id bigint;

create table if not exists public.stock_items (
    id uuid primary key default gen_random_uuid(),
    product_id uuid not null references public.products(id),
    credential_cipher text not null,
    credential_fingerprint text not null,
    status text not null default 'available' check (status in ('available', 'reserved', 'sold')),
    order_id uuid references public.orders(id),
    created_at timestamptz not null default now(),
    unique(product_id, credential_fingerprint)
);

create index if not exists stock_available_idx on public.stock_items(product_id) where status = 'available';
create index if not exists orders_pending_idx on public.orders(status, created_at) where status = 'pending';

alter table public.users enable row level security;
alter table public.bot_settings enable row level security;
alter table public.categories enable row level security;
alter table public.products enable row level security;
alter table public.orders enable row level security;
alter table public.stock_items enable row level security;

create or replace function public.reserve_order(p_chat_id bigint, p_product_id uuid, p_quantity integer)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
    v_order_id uuid;
    v_price numeric(10, 2);
    v_stock_ids uuid[];
begin
    if p_quantity < 1 or p_quantity > 3 then raise exception 'Quantity must be between 1 and 3'; end if;
    select price into v_price from products where id = p_product_id and active = true;
    if v_price is null then raise exception 'Product is not available'; end if;
    select array_agg(id) into v_stock_ids from (
        select id from stock_items where product_id = p_product_id and status = 'available'
        order by created_at for update skip locked limit p_quantity
    ) available;
    if coalesce(array_length(v_stock_ids, 1), 0) < p_quantity then raise exception 'Insufficient stock'; end if;
    insert into orders(chat_id, product_id, quantity, total)
    values (p_chat_id, p_product_id, p_quantity, v_price * p_quantity) returning id into v_order_id;
    update stock_items set status = 'reserved', order_id = v_order_id where id = any(v_stock_ids);
    return jsonb_build_object('id', v_order_id, 'total', v_price * p_quantity);
end;
$$;

create or replace function public.set_order_payment(p_order_id uuid, p_transaction_id text, p_payment_url text)
returns void language plpgsql security definer set search_path = public as $$
begin
    update orders set transaction_id = p_transaction_id, payment_url = p_payment_url
    where id = p_order_id and status = 'pending';
    if not found then raise exception 'Pending order not found'; end if;
end;
$$;

create or replace function public.release_order(p_order_id uuid, p_status text)
returns void language plpgsql security definer set search_path = public as $$
begin
    if p_status not in ('cancelled', 'expired', 'failed') then raise exception 'Invalid release status'; end if;
    update orders set status = p_status where id = p_order_id and status = 'pending';
    update stock_items set status = 'available', order_id = null
    where order_id = p_order_id and status = 'reserved';
end;
$$;

create or replace function public.fulfill_order(p_order_id uuid)
returns text[] language plpgsql security definer set search_path = public as $$
declare
    v_status text;
    v_delivered_at timestamptz;
    v_delivery_claimed_at timestamptz;
    v_credentials text[];
begin
    select status, delivered_at, delivery_claimed_at
    into v_status, v_delivered_at, v_delivery_claimed_at
    from orders where id = p_order_id for update;
    if v_status = 'pending' then
        update orders set status = 'paid' where id = p_order_id;
        update stock_items set status = 'sold' where order_id = p_order_id and status = 'reserved';
    elsif v_status <> 'paid' then
        return array[]::text[];
    end if;
    if v_delivered_at is not null then return array[]::text[]; end if;
    if v_delivery_claimed_at > now() - interval '5 minutes' then return array[]::text[]; end if;
    update orders set delivery_claimed_at = now() where id = p_order_id;
    select array_agg(credential_cipher order by created_at) into v_credentials
    from stock_items where order_id = p_order_id and status = 'sold';
    return coalesce(v_credentials, array[]::text[]);
end;
$$;

create or replace function public.mark_order_delivered(p_order_id uuid)
returns void language sql security definer set search_path = public as $$
    update orders set delivered_at = now(), delivery_claimed_at = null
    where id = p_order_id and status = 'paid' and delivered_at is null;
$$;

create or replace function public.available_stock_count(p_product_id uuid)
returns integer language sql stable security definer set search_path = public as $$
    select count(*)::integer from stock_items where product_id = p_product_id and status = 'available';
$$;

create or replace function public.sales_summary()
returns jsonb language sql stable security definer set search_path = public as $$
    select jsonb_build_object(
        'paid_orders', count(*),
        'total_revenue', coalesce(sum(total), 0),
        'today_revenue', coalesce(sum(total) filter (where created_at >= current_date), 0)
    ) from orders where status = 'paid';
$$;

revoke all on function public.reserve_order(bigint, uuid, integer) from public, anon, authenticated;
revoke all on function public.set_order_payment(uuid, text, text) from public, anon, authenticated;
revoke all on function public.release_order(uuid, text) from public, anon, authenticated;
revoke all on function public.fulfill_order(uuid) from public, anon, authenticated;
revoke all on function public.mark_order_delivered(uuid) from public, anon, authenticated;
revoke all on function public.available_stock_count(uuid) from public, anon, authenticated;
revoke all on function public.sales_summary() from public, anon, authenticated;
grant execute on function public.reserve_order(bigint, uuid, integer) to service_role;
grant execute on function public.set_order_payment(uuid, text, text) to service_role;
grant execute on function public.release_order(uuid, text) to service_role;
grant execute on function public.fulfill_order(uuid) to service_role;
grant execute on function public.mark_order_delivered(uuid) to service_role;
grant execute on function public.available_stock_count(uuid) to service_role;
grant execute on function public.sales_summary() to service_role;
