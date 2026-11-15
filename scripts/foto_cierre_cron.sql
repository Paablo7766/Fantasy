-- Fotos del mercado antes del cierre de las 14:08 (Madrid).
--
-- Render gratuito duerme tras 15 min sin visitas, así que un reloj dentro del
-- servidor no se despierta solo. Supabase llama cada día a POST /api/remote/foto-cierre:
--   * 13:47 de Madrid → foto temprana, a una hora al azar hasta las 14:01;
--   * 14:00 de Madrid → última foto, a una hora al azar entre 14:06:15 y 14:07:10
--     (recoge las pujas de los últimos minutos).
-- Cada foto es UNA petición al mercado de LaLiga. Guarda tu puja, el número de
-- pujas y el valor de cada anuncio en el diario de subastas (market_board).
--
-- Cómo instalarlo (una sola vez): Supabase → SQL Editor → pega esto → cambia
-- PEGA_AQUI_EL_TOKEN por el valor de REMOTE_REFRESH_TOKEN que tienes en Render
-- (Render → tu servicio → Environment) → Run.
--
-- pg_cron va en UTC: cada llamada tiene horario de invierno y de verano. La que
-- cae fuera de su franja en Madrid el servidor la ignora.

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

-- 13:47 de Madrid (temprana)
select cron.schedule('foto-cierre-invierno', '47 12 * * *', 'select public.foto_cierre_llamar()');
select cron.schedule('foto-cierre-verano', '47 11 * * *', 'select public.foto_cierre_llamar()');
-- 14:00 de Madrid (última)
select cron.schedule('foto-cierre-ultima-invierno', '0 13 * * *', 'select public.foto_cierre_llamar()');
select cron.schedule('foto-cierre-ultima-verano', '0 12 * * *', 'select public.foto_cierre_llamar()');

-- Comprobar (después de las 14:10):
--   select jobname, status, start_time from cron.job_run_details d join cron.job j using (jobid)
--    where jobname like 'foto-cierre%' order by start_time desc limit 8;
--   select id, status_code, content from net._http_response order by created desc limit 5;
-- Quitarlo:
--   select cron.unschedule(jobname) from cron.job where jobname like 'foto-cierre%';
