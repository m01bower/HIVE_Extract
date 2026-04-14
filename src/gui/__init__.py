"""GUI package for HIVE_Extract (optional — not available on headless servers)."""

try:
    from gui.date_picker import DateRangeDialog, select_date_range
    __all__ = ["DateRangeDialog", "select_date_range"]
except ImportError:
    __all__ = []
