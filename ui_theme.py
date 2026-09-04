import tkinter as tk
from tkinter import ttk


COLORS = {
    "navy": "#172235",
    "navy_light": "#26364f",
    "surface": "#ffffff",
    "canvas": "#edf2f7",
    "border": "#b8c4d4",
    "primary": "#176b4d",
    "primary_dark": "#0f5138",
    "text": "#17202a",
    "muted": "#5f6f82",
    "selection": "#2f80ed",
}


def configure_theme(root):
    root.configure(bg=COLORS["canvas"])
    root.option_add("*Font", "{Segoe UI} 10")
    root.option_add("*Button.Font", "{Segoe UI} 10 bold")
    root.option_add("*Entry.Font", "{Segoe UI} 10")
    root.option_add("*Listbox.Font", "{Segoe UI} 10")

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(
        "Treeview",
        background=COLORS["surface"],
        fieldbackground=COLORS["surface"],
        foreground=COLORS["text"],
        rowheight=30,
        borderwidth=1,
        relief="sunken",
    )
    style.map(
        "Treeview",
        background=[("selected", COLORS["selection"])],
        foreground=[("selected", "white")],
    )
    style.configure(
        "Treeview.Heading",
        background="#dbe4ef",
        foreground=COLORS["text"],
        font=("Segoe UI", 10, "bold"),
        padding=(8, 8),
        relief="raised",
        borderwidth=1,
    )
    style.map("Treeview.Heading", background=[("active", "#c6d3e2")])
    style.configure("TNotebook", background=COLORS["canvas"], borderwidth=1, relief="ridge")
    style.configure(
        "TNotebook.Tab",
        background="#d6e0eb",
        foreground=COLORS["text"],
        font=("Segoe UI", 10, "bold"),
        padding=(16, 9),
        relief="raised",
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", COLORS["surface"]), ("active", "#e7eef6")],
        foreground=[("selected", COLORS["primary_dark"])],
    )
    style.configure("TCombobox", padding=6, relief="sunken")
    style.configure("Vertical.TScrollbar", arrowsize=16, relief="raised")


def _button_hover(button):
    normal = button.cget("background")
    active = button.cget("activebackground")
    button.bind("<Enter>", lambda event: button.configure(background=active), add="+")
    button.bind("<Leave>", lambda event: button.configure(background=normal), add="+")


def polish_widgets(parent):
    """Apply a consistent dimensional finish without changing page behavior."""
    try:
        widgets = parent.winfo_children()
    except tk.TclError:
        return

    for widget in widgets:
        try:
            if isinstance(widget, tk.Button):
                bg = widget.cget("background")
                if bg in ("SystemButtonFace", "#f0f0f0"):
                    bg = "#e8eef5"
                widget.configure(
                    background=bg,
                    activebackground="#c9d6e5" if bg.startswith("#") else bg,
                    activeforeground=widget.cget("foreground"),
                    relief="raised",
                    bd=2,
                    cursor="hand2",
                    highlightthickness=0,
                )
                _button_hover(widget)
            elif isinstance(widget, tk.Entry):
                widget.configure(relief="sunken", bd=2, highlightthickness=1,
                                 highlightbackground=COLORS["border"],
                                 highlightcolor=COLORS["selection"])
            elif isinstance(widget, tk.LabelFrame):
                widget.configure(relief="groove", bd=2,
                                 highlightbackground=COLORS["border"])
            elif isinstance(widget, tk.Frame):
                if widget.cget("background") in ("white", "#ffffff", "#f9fafb"):
                    widget.configure(relief="ridge", bd=max(int(widget.cget("bd") or 0), 1))
        except (tk.TclError, ValueError):
            pass
        polish_widgets(widget)
