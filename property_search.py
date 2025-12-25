import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText
import csv
import os
import re
from more_itertools import sample
import requests
from PIL import Image, ImageTk
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
import sys

# ---------- Globals ----------
# Handles PyInstaller temporary path
BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))

all_rows = []
headers = []
zip_lookup = {}
photo_images = {}

THUMB_SIZE = (100, 100)
COL_WIDTH = 250

# Networking
session = requests.Session()
thumb_pool = ThreadPoolExecutor(max_workers=6)

# ---------- Helpers ----------
def num(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    m = re.search(r"\d+(\.\d+)?", s)
    return float(m.group()) if m else None

def load_zip_lookup():
    zip_lookup.clear()
    path = os.path.join(BASE_DIR, "zipcode.txt")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) >= 2:
                    zip_lookup[parts[0]] = parts[1]
    except FileNotFoundError:
        messagebox.showerror("Missing File", f"{path} not found.")

def fetch_thumbnail(mls_number, size=THUMB_SIZE):
    url = f"http://media.mlspin.com/photo.aspx?mls={mls_number}&n=0&w=150&h=150"
    try:
        r = session.get(url, timeout=5)
        r.raise_for_status()
        img = Image.open(BytesIO(r.content))
        img.thumbnail(size)
        return ImageTk.PhotoImage(img)
    except:
        return ImageTk.PhotoImage(Image.new("RGB", size, "gray"))

def fetch_thumbnail_async(mls_number, tree, item_id):
    if mls_number in photo_images:
        return

    def worker():
        thumb = fetch_thumbnail(mls_number)
        photo_images[mls_number] = thumb

        def apply():
            # Check if item still exists
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

    # Load ZIP lookup automatically
    load_zip_lookup()

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

    tk.Button(left, text="Load Property File", command=lambda: load_file()).pack(pady=5)
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
    style.configure("Treeview", font=("Courier", 10), rowheight=THUMB_SIZE[1] + 20)

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
    # ---------- Refresh Table ----------
    def refresh_table(rows):
        tree.delete(*tree.get_children())
        visible_cols = [h for h in headers if h != "PHOTO"]
        tree["columns"] = visible_cols

        tree.heading("#0", text="Photo")
        tree.column("#0", width=THUMB_SIZE[0] + 20, anchor="center", stretch=False)

        for col in visible_cols:
            tree.heading(col, text=col, command=lambda c=col: sort_by_column(c))
            tree.column(col, width=COL_WIDTH, minwidth=150, stretch=True)

        # Create one placeholder image for all rows
        placeholder = ImageTk.PhotoImage(Image.new("RGB", THUMB_SIZE, "lightgray"))

        # Insert rows
        items_to_fetch = []
        for r in rows:
            mls = str(r[headers.index("LIST_NO")]).strip() if "LIST_NO" in headers else ""
            values = [r[i] for i, h in enumerate(headers) if h != "PHOTO"]
            item_id = tree.insert("", "end", image=placeholder, values=values)
            if mls:
                items_to_fetch.append((mls, item_id))

        # Fetch thumbnails **top-to-bottom** with a small delay between each
        for i, (mls, item_id) in enumerate(items_to_fetch):
            tree.after(i * 50, lambda m=mls, item=item_id: fetch_thumbnail_async(m, tree, item))


        # ---------- Row Details ----------
    def on_row_selected(event):
        sel = tree.focus()
        if not sel:
            return
        values = tree.item(sel, "values")
        if not values:
            return

        # New detail window
        detail_win = tk.Toplevel(root)
        detail_win.title("Property Details")
        detail_win.geometry("1000x800")

        # Scrollable frame for images
        img_frame_canvas = tk.Canvas(detail_win)
        img_frame_canvas.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True)
        img_scrollbar = tk.Scrollbar(detail_win, orient="vertical", command=img_frame_canvas.yview)
        img_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        img_frame_canvas.configure(yscrollcommand=img_scrollbar.set)
        img_frame = tk.Frame(img_frame_canvas)
        img_frame_canvas.create_window((0, 0), window=img_frame, anchor="nw")

        # Text details at top
        text = ScrolledText(detail_win, wrap=tk.WORD, height=12)
        text.pack(fill=tk.X, expand=False)
        visible_headers = [h for h in headers if h != "PHOTO"]
        for i, h in enumerate(visible_headers):
            text.insert(tk.END, f"{h}: {values[i]}\n")
        text.configure(state="disabled")

        # Load all images for this property (rows can have multiple photos)
        mls = str(values[visible_headers.index("LIST_NO")]).strip() if "LIST_NO" in visible_headers else ""
        images = []

        def load_all_images():
            idx = 0
            while True:
                try:
                    url = f"http://media.mlspin.com/photo.aspx?mls={mls}&n={idx}&w=300&h=300"
                    r = session.get(url, timeout=5)
                    r.raise_for_status()
                    img = Image.open(BytesIO(r.content))
                    img.thumbnail((300, 300))
                    photo_img = ImageTk.PhotoImage(img)
                    images.append(photo_img)

                    # Click to enlarge
                    def make_click_handler(img=img):
                        def handler(event):
                            top = tk.Toplevel(detail_win)
                            top.title("Image")
                            tk_img = ImageTk.PhotoImage(img)
                            lbl = tk.Label(top, image=tk_img)
                            lbl.image = tk_img
                            lbl.pack()
                        return handler

                    lbl = tk.Label(img_frame, image=photo_img, cursor="hand2")
                    lbl.image = photo_img
                    lbl.grid(row=idx // 4, column=idx % 4, padx=5, pady=5)
                    lbl.bind("<Button-1>", make_click_handler(img))

                    idx += 1
                except:
                    break
            img_frame.update_idletasks()
            img_frame_canvas.configure(scrollregion=img_frame_canvas.bbox("all"))

        load_all_images()

    tree.bind("<<TreeviewSelect>>", on_row_selected)

    # ---------- Load Property File ----------
    def load_file():
        global headers, all_rows

        path = filedialog.askopenfilename(
            title="Select property file",
            filetypes=[("CSV / TXT", "*.csv *.txt"), ("All files", "*.*")]
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
                sample = f.read(4096)
                f.seek(0)

                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters="|,\t")
                except csv.Error:
                    dialect = csv.excel
                    dialect.delimiter = "|"

                reader = csv.reader(f, dialect)
                rows = [row for row in reader if any(cell.strip() for cell in row)]

            if not rows or len(rows) < 2:
                messagebox.showerror(
                    "File Error",
                    "The selected file contains no readable rows.\n"
                    "Check delimiter and encoding."
                )
                return

            headers[:] = [h.strip() for h in rows[0]]
            all_rows[:] = rows[1:]

            # Validate required columns
            required = {"LIST_NO", "ZIP", "COUNTY"}
            missing = required - set(headers)
            if missing:
                messagebox.showerror(
                    "Invalid File",
                    f"Missing required columns:\n{', '.join(missing)}"
                )
                return

            # ZIP → Town mapping
            zip_idx = headers.index("ZIP")
            town_idx = headers.index("TOWN_NUM") if "TOWN_NUM" in headers else None
            if town_idx is not None:
                for r in all_rows:
                    if r[zip_idx] in zip_lookup:
                        r[town_idx] = zip_lookup[r[zip_idx]]

            # Populate dropdowns
            if "COUNTY" in headers:
                counties = sorted({r[headers.index("COUNTY")] for r in all_rows if r[headers.index("COUNTY")]})
                county_dropdown["values"] = [""] + counties
                county_dropdown.set("")

            if town_idx is not None:
                towns = sorted({r[town_idx] for r in all_rows if r[town_idx]})
                town_dropdown["values"] = [""] + towns
                town_dropdown.set("")

            refresh_table(all_rows)

            messagebox.showinfo(
                "Loaded",
                f"Loaded {len(all_rows)} rows successfully."
            )

        except Exception as e:
            messagebox.showerror("Load Error", str(e))

            refresh_table(all_rows)

    root.mainloop()

# ---------- Run App ----------
if __name__ == "__main__":
    open_property_search_window()
