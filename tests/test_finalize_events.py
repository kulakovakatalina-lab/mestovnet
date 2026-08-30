"""Совместимость устаревшего входа finalize_events.py."""
from unittest.mock import Mock

import finalize_events


def test_finalize_events_delegates_to_canonical_parser(monkeypatch):
    canonical_main = Mock(return_value=[{"id": "event-1"}])
    monkeypatch.setattr(finalize_events, "run_canonical_pipeline", canonical_main)

    result = finalize_events.main(days_back=21, dry_run=True)

    assert result == [{"id": "event-1"}]
    canonical_main.assert_called_once_with(days_back=21, dry_run=True)
