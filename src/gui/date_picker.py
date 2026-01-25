"""Date range selection dialog for HIVE_Extract."""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date, datetime
from typing import Optional, Tuple
from calendar import monthrange


def first_of_last_month() -> date:
    """Get the first day of the previous month."""
    today = date.today()
    if today.month == 1:
        return date(today.year - 1, 12, 1)
    return date(today.year, today.month - 1, 1)


def last_of_last_month() -> date:
    """Get the last day of the previous month."""
    today = date.today()
    if today.month == 1:
        last_month = 12
        year = today.year - 1
    else:
        last_month = today.month - 1
        year = today.year
    _, last_day = monthrange(year, last_month)
    return date(year, last_month, last_day)


def first_of_this_month() -> date:
    """Get the first day of the current month."""
    today = date.today()
    return date(today.year, today.month, 1)


def first_of_this_year() -> date:
    """Get the first day of the current year."""
    return date(date.today().year, 1, 1)


class DateRangeDialog(tk.Toplevel):
    """Dialog for selecting a date range."""

    def __init__(self, parent: Optional[tk.Tk] = None):
        """
        Initialize the date range dialog.

        Args:
            parent: Parent window (optional)
        """
        # Create a root window if none provided
        self._own_root = False
        if parent is None:
            parent = tk.Tk()
            parent.withdraw()
            self._own_root = True

        super().__init__(parent)

        self.title("HIVE Extract - Select Date Range")
        self.resizable(False, False)

        # Result variables
        self.result: Optional[Tuple[date, date]] = None

        # Default dates: first of last month to today
        self._from_date = first_of_last_month()
        self._to_date = date.today()

        # Create UI
        self._create_widgets()

        # Center the dialog
        self._center_window()

        # Make modal
        self.transient(parent)
        self.grab_set()

        # Handle window close
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _create_widgets(self):
        """Create the dialog widgets."""
        # Main frame with padding
        main_frame = ttk.Frame(self, padding="20")
        main_frame.grid(row=0, column=0, sticky="nsew")

        # Title
        title_label = ttk.Label(
            main_frame,
            text="Select Date Range for Time Tracking Export",
            font=("Segoe UI", 11, "bold"),
        )
        title_label.grid(row=0, column=0, columnspan=6, pady=(0, 20))

        # From Date
        ttk.Label(main_frame, text="From Date:", font=("Segoe UI", 10)).grid(
            row=1, column=0, sticky="e", padx=(0, 10)
        )

        self._from_month = tk.StringVar(value=str(self._from_date.month))
        self._from_day = tk.StringVar(value=str(self._from_date.day))
        self._from_year = tk.StringVar(value=str(self._from_date.year))

        # Month dropdown
        from_month_combo = ttk.Combobox(
            main_frame,
            textvariable=self._from_month,
            values=[str(i) for i in range(1, 13)],
            width=5,
            state="readonly",
        )
        from_month_combo.grid(row=1, column=1, padx=2)

        ttk.Label(main_frame, text="/").grid(row=1, column=2)

        # Day dropdown
        from_day_combo = ttk.Combobox(
            main_frame,
            textvariable=self._from_day,
            values=[str(i) for i in range(1, 32)],
            width=5,
            state="readonly",
        )
        from_day_combo.grid(row=1, column=3, padx=2)

        ttk.Label(main_frame, text="/").grid(row=1, column=4)

        # Year dropdown
        current_year = date.today().year
        from_year_combo = ttk.Combobox(
            main_frame,
            textvariable=self._from_year,
            values=[str(i) for i in range(2020, current_year + 1)],
            width=7,
            state="readonly",
        )
        from_year_combo.grid(row=1, column=5, padx=2)

        # To Date
        ttk.Label(main_frame, text="To Date:", font=("Segoe UI", 10)).grid(
            row=2, column=0, sticky="e", padx=(0, 10), pady=(10, 0)
        )

        self._to_month = tk.StringVar(value=str(self._to_date.month))
        self._to_day = tk.StringVar(value=str(self._to_date.day))
        self._to_year = tk.StringVar(value=str(self._to_date.year))

        to_month_combo = ttk.Combobox(
            main_frame,
            textvariable=self._to_month,
            values=[str(i) for i in range(1, 13)],
            width=5,
            state="readonly",
        )
        to_month_combo.grid(row=2, column=1, padx=2, pady=(10, 0))

        ttk.Label(main_frame, text="/").grid(row=2, column=2, pady=(10, 0))

        to_day_combo = ttk.Combobox(
            main_frame,
            textvariable=self._to_day,
            values=[str(i) for i in range(1, 32)],
            width=5,
            state="readonly",
        )
        to_day_combo.grid(row=2, column=3, padx=2, pady=(10, 0))

        ttk.Label(main_frame, text="/").grid(row=2, column=4, pady=(10, 0))

        to_year_combo = ttk.Combobox(
            main_frame,
            textvariable=self._to_year,
            values=[str(i) for i in range(2020, current_year + 1)],
            width=7,
            state="readonly",
        )
        to_year_combo.grid(row=2, column=5, padx=2, pady=(10, 0))

        # Quick buttons frame
        quick_frame = ttk.LabelFrame(main_frame, text="Quick Select", padding="10")
        quick_frame.grid(row=3, column=0, columnspan=6, pady=20, sticky="ew")

        ttk.Button(quick_frame, text="Last Month", command=self._set_last_month).grid(
            row=0, column=0, padx=5
        )
        ttk.Button(quick_frame, text="This Month", command=self._set_this_month).grid(
            row=0, column=1, padx=5
        )
        ttk.Button(quick_frame, text="This Year", command=self._set_this_year).grid(
            row=0, column=2, padx=5
        )

        # Action buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=4, column=0, columnspan=6, pady=(10, 0))

        ttk.Button(
            button_frame, text="OK", command=self._on_ok, width=12
        ).grid(row=0, column=0, padx=10)
        ttk.Button(
            button_frame, text="Cancel", command=self._on_cancel, width=12
        ).grid(row=0, column=1, padx=10)

    def _center_window(self):
        """Center the dialog on screen."""
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"+{x}+{y}")

    def _set_last_month(self):
        """Set dates to last month."""
        from_d = first_of_last_month()
        to_d = last_of_last_month()
        self._update_date_vars(from_d, to_d)

    def _set_this_month(self):
        """Set dates to this month."""
        from_d = first_of_this_month()
        to_d = date.today()
        self._update_date_vars(from_d, to_d)

    def _set_this_year(self):
        """Set dates to this year."""
        from_d = first_of_this_year()
        to_d = date.today()
        self._update_date_vars(from_d, to_d)

    def _update_date_vars(self, from_d: date, to_d: date):
        """Update the date variable values."""
        self._from_month.set(str(from_d.month))
        self._from_day.set(str(from_d.day))
        self._from_year.set(str(from_d.year))

        self._to_month.set(str(to_d.month))
        self._to_day.set(str(to_d.day))
        self._to_year.set(str(to_d.year))

    def _get_dates(self) -> Tuple[date, date]:
        """Get the selected dates from the UI."""
        from_d = date(
            int(self._from_year.get()),
            int(self._from_month.get()),
            int(self._from_day.get()),
        )
        to_d = date(
            int(self._to_year.get()),
            int(self._to_month.get()),
            int(self._to_day.get()),
        )
        return from_d, to_d

    def _on_ok(self):
        """Handle OK button click."""
        try:
            from_d, to_d = self._get_dates()

            if from_d > to_d:
                messagebox.showerror(
                    "Invalid Date Range",
                    "From date must be before or equal to To date.",
                )
                return

            if to_d > date.today():
                messagebox.showerror(
                    "Invalid Date Range",
                    "To date cannot be in the future.",
                )
                return

            self.result = (from_d, to_d)
            self._close()

        except ValueError as e:
            messagebox.showerror("Invalid Date", f"Please enter valid dates: {e}")

    def _on_cancel(self):
        """Handle Cancel button click."""
        self.result = None
        self._close()

    def _close(self):
        """Close the dialog."""
        self.grab_release()
        self.destroy()
        if self._own_root:
            self.master.destroy()


def select_date_range() -> Optional[Tuple[date, date]]:
    """
    Show the date range selection dialog.

    Returns:
        Tuple of (from_date, to_date) or None if cancelled
    """
    # Create hidden root window
    root = tk.Tk()
    root.withdraw()

    # Create and show dialog
    dialog = DateRangeDialog(root)

    # Wait for dialog to close
    root.wait_window(dialog)

    result = dialog.result

    # Clean up
    root.destroy()

    return result


if __name__ == "__main__":
    # Test the dialog
    result = select_date_range()
    if result:
        print(f"Selected: {result[0]} to {result[1]}")
    else:
        print("Cancelled")
