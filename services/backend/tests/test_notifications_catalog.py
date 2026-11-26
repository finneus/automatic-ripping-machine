from arm_backend.notifications import catalog as cat


class _FakePlugin:
    def __init__(self, *, scheme, name, tokens=None, args=None, url="https://docs", setup_url=None):
        self.secure_protocol = scheme
        self.protocol = None
        self.service_name = name
        self.service_url = url
        self.setup_url = setup_url
        self.template_tokens = tokens or {}
        self.template_args = args or {}


class _FakeManager:
    def __init__(self, plugins):
        self._plugins = plugins

    def load_modules(self):
        return None

    def plugins(self):
        return self._plugins


def _patch(monkeypatch, plugins):
    cat.build_catalog.cache_clear()
    monkeypatch.setattr(cat, "_get_manager", lambda: _FakeManager(plugins))


def test_catalog_builds_required_and_advanced(monkeypatch) -> None:
    p = _FakePlugin(
        scheme="discord",
        name="Discord",
        tokens={"webhook_id": {"name": "Webhook ID", "type": "string", "required": True, "private": True}},
        args={"format": {"name": "Format", "type": "choice:string", "values": ["text", "markdown"], "default": "text"}},
    )
    _patch(monkeypatch, [p])
    c = cat.build_catalog()
    svc = c["services"][0]
    assert svc["id"] == "discord"
    assert svc["name"] == "Discord"
    assert svc["required_fields"][0] == {
        "key": "webhook_id",
        "label": "Webhook ID",
        "type": "string",
        "private": True,
        "required": True,
    }
    adv = svc["advanced_fields"][0]
    assert adv["type"] == "choice"
    assert adv["values"] == ["markdown", "text"]
    assert adv["default"] == "text"


def test_catalog_carries_the_apprise_setup_page(monkeypatch) -> None:
    p = _FakePlugin(scheme="discord", name="Discord", setup_url="https://appriseit.com/services/discord/")
    _patch(monkeypatch, [p])
    assert cat.build_catalog()["services"][0]["setup_url"] == "https://appriseit.com/services/discord/"


def test_catalog_falls_back_to_the_apprise_wiki_page(monkeypatch) -> None:
    p = _FakePlugin(scheme="jira", name="Jira")
    _patch(monkeypatch, [p])
    assert cat.build_catalog()["services"][0]["setup_url"] == "https://github.com/caronc/apprise/wiki/Notify_jira"


def test_catalog_blocklist_and_alias_skipped(monkeypatch) -> None:
    p = _FakePlugin(
        scheme="x",
        name="X",
        args={
            "verify": {"name": "v", "type": "bool"},
            "real": {"name": "r", "type": "string"},
            "alias": {"alias_of": "real"},
        },
    )
    _patch(monkeypatch, [p])
    c = cat.build_catalog()
    keys = [f["key"] for f in c["services"][0]["advanced_fields"]]
    assert keys == ["real"]


def test_catalog_dedup_and_featured(monkeypatch) -> None:
    p1 = _FakePlugin(scheme="discord", name="Discord")
    p2 = _FakePlugin(scheme="discord", name="Discord dup")
    p3 = _FakePlugin(scheme="zzz", name="Zzz")
    _patch(monkeypatch, [p1, p2, p3])
    c = cat.build_catalog()
    ids = [s["id"] for s in c["services"]]
    assert ids.count("discord") == 1
    assert c["featured"] == ["discord"]  # only featured ids that exist
    # services sorted by name (lowercased): "Discord" before "Zzz"
    assert ids == ["discord", "zzz"]


def test_catalog_skips_plugin_with_no_scheme(monkeypatch) -> None:
    p = _FakePlugin(scheme=None, name="NoScheme")
    p.protocol = None
    _patch(monkeypatch, [p])
    c = cat.build_catalog()
    assert c["services"] == []


def test_catalog_unwraps_enum_default_value(monkeypatch) -> None:
    # a default carrying a ``.value`` (apprise enum-ish) is unwrapped -> line 53
    class _Enumish:
        value = "html"

    p = _FakePlugin(
        scheme="x",
        name="X",
        args={"format": {"name": "Format", "type": "string", "default": _Enumish()}},
    )
    _patch(monkeypatch, [p])
    c = cat.build_catalog()
    assert c["services"][0]["advanced_fields"][0]["default"] == "html"


def test_catalog_normalizes_plain_type_and_list_scheme(monkeypatch) -> None:
    # scheme as a list -> _service_id takes [0]; plain "string" advanced type -> passthrough
    p = _FakePlugin(
        scheme=["multi", "multis"],
        name="Multi",
        args={"token": {"name": "Token", "type": "string"}},
    )
    _patch(monkeypatch, [p])
    c = cat.build_catalog()
    svc = c["services"][0]
    assert svc["id"] == "multi"  # list scheme -> first element
    assert svc["advanced_fields"][0]["type"] == "string"  # plain type passthrough


def test_catalog_skips_plugin_that_raises(monkeypatch) -> None:
    bad = _FakePlugin(scheme="bad", name="Bad")

    # template_tokens that raises on .items()
    class _Boom:
        def items(self):
            raise RuntimeError("boom")

    bad.template_tokens = _Boom()
    good = _FakePlugin(scheme="good", name="Good")
    _patch(monkeypatch, [bad, good])
    c = cat.build_catalog()
    assert [s["id"] for s in c["services"]] == ["good"]


_TARGETS_TOKENS = {
    "bot_token": {"name": "Bot Token", "type": "string", "required": True, "private": True},
    "targets": {"name": "Target Chat ID", "type": "list:string"},
}


def test_catalog_offers_recipients_as_a_to_field(monkeypatch) -> None:
    p = _FakePlugin(
        scheme="tgram",
        name="Telegram",
        tokens=_TARGETS_TOKENS,
        args={"format": {"name": "Format", "type": "string"}, "to": {"alias_of": "targets"}},
    )
    _patch(monkeypatch, [p])
    adv = cat.build_catalog()["services"][0]["advanced_fields"]
    assert adv[0] == {
        "key": "to",
        "label": "Target Chat ID (comma-separated)",
        "type": "string",
        "private": False,
        "required": False,
    }
    assert [f["key"] for f in adv] == ["to", "format"]


def test_targets_field_defaults_the_label_when_the_token_has_no_name() -> None:
    p = _FakePlugin(scheme="x", name="X", tokens={"targets": {}}, args={"to": {"alias_of": "targets"}})
    assert cat._targets_field(p)["label"] == "Targets (comma-separated)"


def test_targets_field_is_none_without_a_to_alias() -> None:
    assert cat._targets_field(_FakePlugin(scheme="x", name="X", tokens=_TARGETS_TOKENS)) is None


def test_targets_field_is_none_when_to_aliases_something_else() -> None:
    p = _FakePlugin(scheme="x", name="X", tokens=_TARGETS_TOKENS, args={"to": {"alias_of": "user"}})
    assert cat._targets_field(p) is None


def test_targets_field_is_none_without_a_targets_token() -> None:
    p = _FakePlugin(scheme="x", name="X", args={"to": {"alias_of": "targets"}})
    assert cat._targets_field(p) is None


def test_targets_field_handles_plugins_without_templates() -> None:
    p = _FakePlugin(scheme="x", name="X")
    p.template_args = None
    p.template_tokens = None
    assert cat._targets_field(p) is None


def test_real_telegram_channel_composes_a_url_apprise_sends_to_the_chat() -> None:
    """End to end against the installed apprise: the catalog's Telegram form, filled in, composes a URL whose chat id
    apprise picks up (no network: `add` only parses)."""
    import apprise

    from arm_backend.notifications.field_map import compose_url_from_fields

    cat.build_catalog.cache_clear()
    try:
        tgram = next(s for s in cat.build_catalog()["services"] if s["id"] == "tgram")
        assert "to" in [f["key"] for f in tgram["advanced_fields"]]
        url = compose_url_from_fields("tgram", {"bot_token": "123456789:" + "A" * 35, "to": "-1001234,987"})
    finally:
        cat.build_catalog.cache_clear()
    assert url is not None and url.endswith("?to=-1001234%2C987")
    sender = apprise.Apprise()
    assert sender.add(url)
    assert [chat for chat, _topic in sender[0].targets] == [-1001234, 987]
def test_featured_notify_fields_match_the_live_apprise_catalog() -> None:
    """The docs registry declares each featured service's fields without importing
    Apprise; this holds that list to the catalog the real Apprise plugins build."""
    from arm_common.field_docs import FEATURED_NOTIFY_FIELDS

    cat.build_catalog.cache_clear()
    try:
        services = {s["id"]: s for s in cat.build_catalog()["services"]}
    finally:
        cat.build_catalog.cache_clear()
    assert list(FEATURED_NOTIFY_FIELDS) == cat.FEATURED_SERVICES
    # Field order follows Apprise's template args, which a version bump may
    # reorder without changing coverage, so the fields compare as sets.
    live = {
        sid: {f["key"] for f in services[sid]["required_fields"] + services[sid]["advanced_fields"]}
        for sid in cat.FEATURED_SERVICES
    }
    assert live == {sid: set(keys) for sid, keys in FEATURED_NOTIFY_FIELDS.items()}
