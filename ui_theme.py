"""Màu, font và các khối giao diện dùng chung (Tkinter thuần, không cần thư viện thêm)."""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

BG = "#F4F5F7"
CARD = "#FFFFFF"
BORDER = "#E2E5E9"
TEXT = "#1F2328"
MUTED = "#6B7280"
ACCENT = "#2563EB"
ACCENT_DARK = "#1D4ED8"
ACCENT_SOFT = "#EFF4FF"
GREEN = "#15803D"
GREEN_SOFT = "#E8F5EC"
AMBER = "#B45309"
RED = "#B91C1C"
SIDEBAR = "#111827"
SIDEBAR_HOVER = "#1F2937"
SIDEBAR_ACTIVE = "#2563EB"
SIDEBAR_TEXT = "#D1D5DB"
SIDEBAR_MUTED = "#6B7280"

FAMILY = "Segoe UI" if sys.platform == "win32" else "Helvetica"
BASE = 10 if sys.platform == "win32" else 13


def font(delta: int = 0, weight: str = "normal") -> tuple:
    return (FAMILY, BASE + delta, weight)


LABELS = {
    "body": (TEXT, font()),
    "muted": (MUTED, font(-1)),
    "h1": (TEXT, font(6, "bold")),
    "h2": (TEXT, font(2, "bold")),
    "bold": (TEXT, font(0, "bold")),
    "big": (TEXT, font(5, "bold")),
    "ok": (GREEN, font(0, "bold")),
    "warn": (AMBER, font(0, "bold")),
    "err": (RED, font(0, "bold")),
}


def apply(root: tk.Tk) -> None:
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=BG, foreground=TEXT, font=font(), bordercolor=BORDER, lightcolor=BORDER,
                darkcolor=BORDER, focuscolor=ACCENT, troughcolor="#E5E7EB", selectbackground="#DBEAFE",
                selectforeground=TEXT)
    s.configure("Card.TFrame", background=CARD)
    for where, bg in (("Page", BG), ("Card", CARD)):
        for kind, (fg, f) in LABELS.items():
            s.configure(f"{where}.{kind}.TLabel", background=bg, foreground=fg, font=f)

    flat = dict(relief="flat", borderwidth=1, padding=(14, 7))
    s.configure("TButton", background="#F3F4F6", foreground=TEXT, bordercolor="#D1D5DB", lightcolor="#F3F4F6",
                darkcolor="#F3F4F6", **flat)
    s.map("TButton", background=[("disabled", "#F9FAFB"), ("pressed", "#D1D5DB"), ("active", "#E5E7EB")],
          lightcolor=[("active", "#E5E7EB")], darkcolor=[("active", "#E5E7EB")],
          bordercolor=[("disabled", BORDER)], foreground=[("disabled", "#9CA3AF")])
    s.configure("Accent.TButton", background=ACCENT, foreground="white", bordercolor=ACCENT, lightcolor=ACCENT,
                darkcolor=ACCENT, font=font(0, "bold"), **flat)
    s.map("Accent.TButton", background=[("disabled", "#A5C0F5"), ("pressed", ACCENT_DARK), ("active", ACCENT_DARK)],
          bordercolor=[("disabled", "#A5C0F5"), ("active", ACCENT_DARK)],
          lightcolor=[("disabled", "#A5C0F5"), ("active", ACCENT_DARK)],
          darkcolor=[("disabled", "#A5C0F5"), ("active", ACCENT_DARK)], foreground=[("disabled", "white")])
    s.configure("Small.TButton", padding=(12, 3))
    s.configure("Small.Accent.TButton", padding=(12, 3))

    field = dict(fieldbackground=CARD, bordercolor=BORDER, lightcolor=CARD, darkcolor=CARD, padding=6, insertcolor=TEXT)
    s.configure("TEntry", **field)
    s.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)])
    s.configure("TCombobox", arrowcolor=MUTED, background=CARD, **field)
    s.map("TCombobox", fieldbackground=[("readonly", CARD)], bordercolor=[("focus", ACCENT)],
          selectbackground=[("readonly", CARD)], selectforeground=[("readonly", TEXT)])
    root.option_add("*TCombobox*Listbox.font", font())
    root.option_add("*TCombobox*Listbox.selectBackground", "#DBEAFE")
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)

    s.configure("TCheckbutton", background=CARD, font=font(), indicatorbackground=CARD, indicatorforeground=ACCENT)
    s.map("TCheckbutton", background=[("active", CARD)], indicatorbackground=[("pressed", "#DBEAFE")])

    s.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT, rowheight=30 if BASE == 10 else 26,
                bordercolor=CARD, lightcolor=CARD, darkcolor=CARD, borderwidth=0, font=font())
    s.map("Treeview", background=[("selected", "#DBEAFE")], foreground=[("selected", TEXT)])
    s.configure("Treeview.Heading", background="#F9FAFB", foreground=MUTED, font=font(-1, "bold"), relief="flat",
                padding=(8, 6), bordercolor=BORDER, lightcolor="#F9FAFB", darkcolor="#F9FAFB")
    s.map("Treeview.Heading", background=[("active", "#F3F4F6")])
    s.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor="#E5E7EB", bordercolor="#E5E7EB",
                lightcolor=ACCENT, darkcolor=ACCENT, thickness=6)
    s.configure("Vertical.TScrollbar", background="#E5E7EB", troughcolor=CARD, bordercolor=CARD, arrowcolor=MUTED,
                lightcolor="#E5E7EB", darkcolor="#E5E7EB", gripcount=0, arrowsize=12)


def label(parent, text: str = "", kind: str = "body", card: bool = True, wrap: bool = False, **kw) -> ttk.Label:
    widget = ttk.Label(parent, text=text, style=f"{'Card' if card else 'Page'}.{kind}.TLabel", **kw)
    if wrap:  # tự xuống dòng theo bề rộng thật của khung
        widget.bind("<Configure>", lambda e: e.widget.configure(wraplength=max(200, e.width - 4)))
    return widget


def text_box(parent, height: int, wrap: str = "word") -> tk.Text:
    return tk.Text(parent, height=height, wrap=wrap, undo=True, font=font(), relief="flat", bg=CARD, fg=TEXT,
                   insertbackground=TEXT, highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT,
                   padx=8, pady=6, selectbackground="#DBEAFE")


class Page(ttk.Frame):
    """Một màn hình: tiêu đề, mô tả ngắn, rồi các thẻ."""

    def __init__(self, parent, title: str, subtitle: str = ""):
        super().__init__(parent, padding=(28, 16, 28, 12))
        label(self, title, "h1", card=False).pack(anchor="w")
        if subtitle:
            label(self, subtitle, "muted", card=False, wrap=True).pack(fill="x", pady=(2, 12))


def card(parent, title: str = "", desc: str = "", expand: bool = False, pady=(0, 12), padding: int = 16) -> ttk.Frame:
    outer = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
    outer.pack(fill="both" if expand else "x", expand=expand, pady=pady)
    inner = ttk.Frame(outer, style="Card.TFrame", padding=padding)
    inner.pack(fill="both", expand=True)
    if title:
        label(inner, title, "h2").pack(anchor="w")
    if desc:
        label(inner, desc, "muted", wrap=True).pack(fill="x", pady=(2, 10))
    elif title:
        ttk.Frame(inner, style="Card.TFrame", height=8).pack()
    return inner


def row(parent, pady=(0, 0)) -> ttk.Frame:
    frame = ttk.Frame(parent, style="Card.TFrame")
    frame.pack(fill="x", pady=pady)
    return frame


def table(parent, columns: list[tuple], height: int = 4, expand: bool = True) -> ttk.Treeview:
    """columns: (key, tiêu đề, rộng, căn lề, co giãn)."""
    holder = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
    holder.pack(fill="both" if expand else "x", expand=expand, pady=(0, 8))
    tree = ttk.Treeview(holder, columns=[c[0] for c in columns], show="headings", height=height, selectmode="extended")
    for key, text, width, anchor, stretch in columns:
        tree.heading(key, text=text, anchor=anchor)
        tree.column(key, width=width, minwidth=60, anchor=anchor, stretch=stretch)
    scroll = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    for tag, color in (("ok", GREEN), ("warn", AMBER), ("err", RED), ("next", ACCENT), ("muted", MUTED)):
        tree.tag_configure(tag, foreground=color)
    return tree


class Sidebar(tk.Frame):
    def __init__(self, parent, on_select):
        super().__init__(parent, bg=SIDEBAR, width=232)
        self.pack_propagate(False)
        self.on_select = on_select
        self.items: dict[str, tuple] = {}
        self.active = None
        tk.Label(self, text="YouTube → Facebook", bg=SIDEBAR, fg="white", font=font(3, "bold"), anchor="w",
                 padx=20).pack(fill="x", pady=(20, 2))
        tk.Label(self, text="Tải video và tự đăng Page", bg=SIDEBAR, fg=SIDEBAR_MUTED, font=font(-1), anchor="w",
                 padx=20).pack(fill="x", pady=(0, 8))

    def group(self, text: str) -> None:
        tk.Label(self, text=text.upper(), bg=SIDEBAR, fg=SIDEBAR_MUTED, font=font(-2, "bold"), anchor="w",
                 padx=20).pack(fill="x", pady=(14, 4))

    def item(self, key: str, text: str) -> None:
        frame = tk.Frame(self, bg=SIDEBAR, cursor="hand2")
        frame.pack(fill="x", padx=10, pady=1)
        name = tk.Label(frame, text=text, bg=SIDEBAR, fg=SIDEBAR_TEXT, font=font(), anchor="w", padx=12, pady=7)
        name.pack(side="left", fill="x", expand=True)
        mark = tk.Label(frame, text="", bg=SIDEBAR, fg="#4ADE80", font=font(0, "bold"), padx=10)
        mark.pack(side="right")
        for widget in (frame, name, mark):
            widget.bind("<Button-1>", lambda e, k=key: self.on_select(k))
            widget.bind("<Enter>", lambda e, k=key: self.paint(k, hover=True))
            widget.bind("<Leave>", lambda e, k=key: self.paint(k))
        self.items[key] = (frame, name, mark)

    def paint(self, key: str, hover: bool = False) -> None:
        frame, name, mark = self.items[key]
        bg = SIDEBAR_ACTIVE if key == self.active else SIDEBAR_HOVER if hover else SIDEBAR
        for widget in (frame, name, mark):
            widget.configure(bg=bg)
        name.configure(fg="white" if key == self.active else SIDEBAR_TEXT)

    def set_active(self, key: str) -> None:
        self.active = key
        for k in self.items:
            self.paint(k)

    def set_mark(self, key: str, text: str, color: str = "#4ADE80") -> None:
        self.items[key][2].configure(text=text, fg=color)
