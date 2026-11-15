-- Foto del mercado antes del cierre de las 14:08 (Madrid).
--
-- Render gratuito duerme tras 15 min sin visitas, así que un reloj dentro del
-- servidor no se despierta solo. Supabase llama cada día a las 13:47 de Madrid a
-- POST /api/remote/foto-cierre; el servidor espera un rato al azar (hasta 13 min,
-- nunca después de las 14:03) y hace UNA petición al mercado de LaLiga. Guarda tu
-- puja, el número de pujas y el valor de cada anuncio en el diario de subastas.
--
-- Cómo instalarlo (una sola vez): Supabase → SQL Editor → pega esto → cambia
-- PEGA_AQUI_EL_TOKEN por el valor de REMOTE_REFRESH_TOKEN que tienes en Render
-- (Render → tu servicio → Environment) → Run.
--
-- pg_cron va en UTC: hay un horario de invierno (12:47 UTC) y otro de verano
-- (11:47 UTC). El que cae fuera de 13:30–14:03 en Madrid el servidor lo ignora.

create extension if not exists pg_cron;
create extension if not exists pg_net;

-- La contraseña queda cifrada en Vault, no en el texto del cron.
select vault.create_secret('PEGA_AQUI_EL_TOKEN', 'foto_cierre_token', 'Gatillo remoto de Render (REMOTE_REFRESH_TOKEN)');

create or replace function public.foto_cierre_llamar() returns bigint
language sql
security definer
set search_path = public, extensions
as $$
  select net.http_post(
    url := 'https://fantasy-wf53.onrender.com/api/remote/foto-cierre',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'X-Remote-Token', (select decrypted_secret from vault.decrypted_secrets where name = 'foto_cierre_token' limit 1)
    ),
    body := '{}'::jsonb,
    -- Render tarda ~45 s en despertar.
    timeout_milliseconds := 90000
  );
$$;

revoke all on function public.foto_cierre_llamar() from public, anon, authenticated;

select cron.schedule('foto-cierre-invierno', '47 12 * * *', 'select public.foto_cierre_llamar()');
select cron.schedule('foto-cierre-verano', '47 11 * * *', 'select public.foto_cierre_llamar()');

-- Comprobar (después de las 13:50):
--   select * from cron.job_run_details where command like '%foto_cierre%' order by start_time desc limit 5;
--   select id, status_code, content from net._http_response order by created desc limit 5;
-- Quitarlo:
--   select cron.unschedule('foto-cierre-invierno'); select cron.unschedule('foto-cierre-verano');
