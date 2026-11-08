from toolbox import web_push


def test_sin_claves_no_envia_nada(monkeypatch):
    monkeypatch.delenv("VAPID_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
    assert web_push.enabled() is False
    assert web_push.send_to_all("a", "b") == 0


def test_suscripcion_local_ida_y_vuelta(monkeypatch, tmp_path):
    monkeypatch.setenv("FANTASY_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    sub = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "x", "auth": "y"}}
    assert web_push.save_subscription({"endpoint": "http://mal"}) is False
    assert web_push.save_subscription(sub) is True
    assert web_push.list_subscriptions() == [sub]
    web_push.remove_subscription(sub["endpoint"])
    assert web_push.list_subscriptions() == []


def test_claves_generadas_tienen_forma_vapid():
    pub, priv = web_push.generate_keys()
    assert len(pub) == 87 and len(priv) == 43
