"""Tier-1 settings audit: notification_apprise_urls is hidden from the editable surface (registry +
ConfigUpdateRequest) but stays readable in ConfigView for back-compat. default_retention_policy is editable again now
that raw_retention acts on it."""

from arm_common.config_metadata import CONFIG_FIELD_META
from arm_common.schemas import ConfigUpdateRequest, ConfigView

_HIDDEN = {"notification_apprise_urls"}


def test_hidden_fields_absent_from_registry():
    keys = {m.key for m in CONFIG_FIELD_META}
    assert _HIDDEN.isdisjoint(keys), f"still in registry: {_HIDDEN & keys}"


def test_hidden_fields_not_editable():
    assert _HIDDEN.isdisjoint(set(ConfigUpdateRequest.model_fields)), "still editable"


def test_hidden_fields_still_readable_in_view():
    view_fields = set(ConfigView.model_fields)
    assert _HIDDEN <= view_fields, f"lost from ConfigView: {_HIDDEN - view_fields}"


def test_retention_policy_is_registered_and_editable():
    meta = next(m for m in CONFIG_FIELD_META if m.key == "default_retention_policy")
    assert meta.editable and meta.enum_values == ["keep_forever", "prune_after_session"]
    assert "default_retention_policy" in ConfigUpdateRequest.model_fields
