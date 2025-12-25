import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText
import csv
import os
import re
import requests
from PIL import Image, ImageTk
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

# ---------- Globals ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
all_rows = []
headers = []
zip_lookup = {}
photo_images = {}

THUMB_SIZE = (100, 100)
COL_WIDTH = 250
MAX_WORKERS = 6

# Networking
session = requests.Session()
thumb_pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)

# ---------- Helpers ----------
def num(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    m = re.search(r"\d+(\.\d+)?", s)
    return float(m.group()) if m else None

def load_zip_lookup(filename):
    zip_lookup.clear()
    try:
        with open(filename, encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) >= 2:
                    zip_lookup[parts[0]] = parts[1]
    except FileNotFoundError:
        messagebox.showerror("Missing File", f"{filename} not found.")

def fetch_thumbnail(mls_number, size=THUMB_SIZE):
    url = f"http://media.mlspin.com/photo.aspx?mls={mls_number}&n=0&w=300&h=300"
    try:
        r = session.get(url, timeout=5)
        r.raise_for_status()
        img = Image.open(BytesIO(r.content))
        img.thumbnail(size)
        return ImageTk.PhotoImage(img)
    except:
        return ImageTk.PhotoImage(Image.new("RGB", size, "gray"))

def fetch_thumbnail_async_safe(mls_number, tree, item_id):
    if mls_number in photo_images:
        if item_id in tree.get_children():
            tree.item(item_id, image=photo_images[mls_number])
        return

    def worker():
        thumb = fetch_thumbnail(mls_number)
        photo_images[mls_number] = thumb

        def apply():
            if item_id in tree.get_children():
                tree.item(item_id, image=thumb)

        tree.after(0, apply)

    thumb_pool.submit(worker)

# ---------- Main App ----------
def open_property_search_window():
    global all_rows, headers, tree
    sort_state = {}

    root = tk.Tk()
    root.title("Property Viewer with Thumbnails")
    root.geometry("1800x800")

    # Load ZIP lookup
    load_zip_lookup(os.path.join(BASE_DIR, "zipcode.txt"))

    # ---------- Left Filter Panel ----------
    left = tk.Frame(root)
    left.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)

    # Filter Variables
    bed_var = tk.StringVar()
    bath_var = tk.StringVar()
    price_min = tk.StringVar()
    price_max = tk.StringVar()
    sq_ft_min = tk.StringVar()
    remarks_var = tk.StringVar()
    county_var = tk.StringVar()
    town_var = tk.StringVar()

    # Apply filters
    def apply_filters(*_):
        if not all_rows or not headers:
            return

        idx = {h: headers.index(h) for h in headers}
        remarks_idx = idx.get("REMARKS")
        town_idx = idx.get("TOWN_NUM")

        filtered = []
        for r in all_rows:
            try:
                if county_var.get() and r[idx["COUNTY"]] != county_var.get():
                    continue
                if town_var.get() and town_idx is not None and r[town_idx] != town_var.get():
                    continue
                if bed_var.get() and (num(r[idx.get("NO_BEDROOMS")]) or 0) < num(bed_var.get()):
                    continue
                if bath_var.get() and (num(r[idx.get("NO_BATHS")]) or 0) < num(bath_var.get()):
                    continue
                if price_min.get() and (num(r[idx.get("LIST_PRICE")]) or 0) < num(price_min.get()):
                    continue
                if price_max.get() and (num(r[idx.get("LIST_PRICE")]) or 0) > num(price_max.get()):
                    continue
                if sq_ft_min.get() and (num(r[idx.get("SQUARE_FEET")]) or 0) < num(sq_ft_min.get()):
                    continue
                if remarks_var.get() and remarks_idx is not None:
                    if remarks_var.get().lower() not in str(r[remarks_idx]).lower():
                        continue
            except Exception as e:
                print(f"Filter error: {e}")
                continue

            filtered.append(r)

        refresh_table(filtered)

    # Helper to create input fields
    def field(label, var):
        tk.Label(left, text=label).pack(anchor="w")
        tk.Entry(left, textvariable=var, width=15).pack(anchor="w")
        var.trace_add("write", apply_filters)

    tk.Button(left, text="Load File", command=lambda: load_file()).pack(pady=5)
    tk.Label(left, text="Filters", font=("Arial", 11, "bold")).pack(anchor="w", pady=(10, 5))

    field("Min Beds", bed_var)
    field("Min Baths", bath_var)
    field("Price Min", price_min)
    field("Price Max", price_max)
    field("Min Sq Ft", sq_ft_min)
    field("Remarks Contains", remarks_var)

    tk.Label(left, text="County").pack(anchor="w", pady=(10, 0))
    county_dropdown = ttk.Combobox(left, textvariable=county_var, state="readonly", width=15)
    county_dropdown.pack(anchor="w")
    county_var.trace_add("write", apply_filters)

    tk.Label(left, text="Town").pack(anchor="w", pady=(10, 0))
    town_dropdown = ttk.Combobox(left, textvariable=town_var, state="readonly", width=20)
    town_dropdown.pack(anchor="w")
    town_var.trace_add("write", apply_filters)

    # ---------- Table ----------
    frame = tk.Frame(root)
    frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    tree = ttk.Treeview(frame)
    vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)

    tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

    vsb.pack(side=tk.RIGHT, fill=tk.Y)
    hsb.pack(side=tk.BOTTOM, fill=tk.X)
    tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    style = ttk.Style()
    style.configure("Treeview", font=("Courier", 10), rowheight=THUMB_SIZE[1]+20)

    # ---------- Sorting ----------
    def sort_by_column(col):
        items = []
        for k in tree.get_children(""):
            val = tree.set(k, col)
            try:
                val_sort = float(val)
            except:
                val_sort = str(val).lower()
            items.append((val_sort, k))

        reverse = sort_state.get(col, False)
        items.sort(reverse=reverse)
        for index, (_, k) in enumerate(items):
            tree.move(k, "", index)

        sort_state[col] = not reverse

    # ---------- Refresh Table ----------
    def refresh_table(rows):
        tree.delete(*tree.get_children())
        visible_cols = [h for h in headers if h != "PHOTO"]
        tree["columns"] = visible_cols

        tree.heading("#0", text="Photo")
        tree.column("#0", width=THUMB_SIZE[0]+20, anchor="center", stretch=False)

        for col in visible_cols:
            tree.heading(col, text=col, command=lambda c=col: sort_by_column(c))
            tree.column(col, width=COL_WIDTH, minwidth=150, stretch=True)

        placeholder = ImageTk.PhotoImage(Image.new("RGB", THUMB_SIZE, "lightgray"))

        for i, r in enumerate(rows):
            mls = str(r[headers.index("LIST_NO")]).strip() if "LIST_NO" in headers else ""
            values = [r[j] for j, h in enumerate(headers) if h != "PHOTO"]
            item_id = tree.insert("", "end", image=placeholder, values=values)
            if mls:
                # Load top-down with a slight delay to keep UI responsive
                tree.after(i*50, lambda m=mls, item=item_id: fetch_thumbnail_async_safe(m, tree, item))

    # ---------- Row Details ----------
    def on_row_selected(event):
        sel = tree.focus()
        if not sel:
            return
        values = tree.item(sel, "values")
        if not values:
            return

        # Detail window
        detail_win = tk.Toplevel(root)
        detail_win.title("Property Details")
        detail_win.geometry("900x700")

        # Info text
        text = ScrolledText(detail_win, wrap=tk.WORD, width=100, height=15)
        text.pack(fill=tk.X, expand=False)
        visible_headers = [h for h in headers if h != "PHOTO"]
        for i, h in enumerate(visible_headers):
            text.insert(tk.END, f"{h}: {values[i]}\n")
        text.configure(state="disabled")

        # ---------- Image Frame ----------
        canvas_frame = tk.Frame(detail_win)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(canvas_frame)
        scrollbar = tk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0,0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Load all property images
        mls = str(values[visible_headers.index("LIST_NO")]).strip() if "LIST_NO" in visible_headers else ""
        if mls:
            # Try 50 images max (can adjust)
            for n in range(50):
                def make_image(n=n):
                    url = f"http://media.mlspin.com/photo.aspx?mls={mls}&n={n}&w=300&h=300"
                    try:
                        r = session.get(url, timeout=5)
                        r.raise_for_status()
                        img = Image.open(BytesIO(r.content))
                        img.thumbnail((200,200))
                        photo = ImageTk.PhotoImage(img)

                        lbl = tk.Label(scrollable_frame, image=photo)
                        lbl.image = photo  # keep reference
                        lbl.grid(row=n//4, column=n%4, padx=5, pady=5)

                        # Click to enlarge
                        def on_click(event, img=img):
                            win = tk.Toplevel(detail_win)
                            win.title("Image")
                            imgtk = ImageTk.PhotoImage(img.resize((600,600)))
                            lbl2 = tk.Label(win, image=imgtk)
                            lbl2.image = imgtk
                            lbl2.pack()
                        lbl.bind("<Button-1>", on_click)
                    except:
                        return
                thumb_pool.submit(make_image)

    tree.bind("<<TreeviewSelect>>", on_row_selected)

    # ---------- Load File ----------
    def load_file():
        global headers, all_rows

        path = filedialog.askopenfilename(filetypes=[("CSV / TXT", "*.csv *.txt")])
        if not path:
            return

        with open(path, encoding="utf-8", errors="replace") as f:
            rows = list(csv.reader(f, delimiter="|"))

        headers[:] = [h.strip() for h in rows[0]]
        all_rows[:] = rows[1:]

        # Map ZIP to Town
        zip_idx = headers.index("ZIP") if "ZIP" in headers else None
        town_idx = headers.index("TOWN_NUM") if "TOWN_NUM" in headers else None
        if zip_idx is not None and town_idx is not None:
            for r in all_rows:
                if r[zip_idx] in zip_lookup:
                    r[town_idx] = zip_lookup[r[zip_idx]]

        # Populate county dropdown
        if "COUNTY" in headers:
            counties = sorted(set(r[headers.index("COUNTY")] for r in all_rows))
            county_dropdown["values"] = [""] + counties
            county_dropdown.set("")

        # Populate town dropdown
        if town_idx is not None:
            towns = sorted(set(r[town_idx] for r in all_rows if r[town_idx]))
            town_dropdown["values"] = [""] + towns
            town_dropdown.set("")

        refresh_table(all_rows)

    root.mainloop()

# ---------- Run App ----------
open_property_search_window()

