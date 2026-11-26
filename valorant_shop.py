"""Valorant Shop & Locker - Valorant muss nicht installiert sein.
pip install requests pillow pywebview
Login über das offizielle Riot-Anmeldefenster. Passwörter werden nie gespeichert.
"""
import io, os, subprocess, sys, tempfile, threading, tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, parse_qs
import requests
from PIL import Image, ImageTk

API = "https://valorant-api.com/v1"
AUTH_URL = ("https://auth.riotgames.com/authorize?redirect_uri=https%3A%2F%2Fplayvalorant.com%2Fopt_in"
            "&client_id=play-valorant-web-prod&response_type=token%20id_token&nonce=1&scope=account%20openid")
VP = "85ad13f7-3d1b-5128-9eb2-7cd8ee0b5741"
SKIN_LEVEL_TYPE = "e7c63390-eda7-46e0-bb7a-a6abdacd2433"
PLATFORM = ("ew0KCSJwbGF0Zm9ybVR5cGUiOiAiUEMiLA0KCSJwbGF0Zm9ybU9TIjogIldpbmRvd3MiLA0KCSJwbGF0Zm9ybU9TVmVy"
            "c2lvbiI6ICIxMC4wLjE5MDQyLjEuMjU2LjY0Yml0IiwNCgkicGxhdGZvcm1DaGlwc2V0IjogIlVua25vd24iDQp9")

# Farben: fast schwarz, ruhige Flächen, ein dunkelblauer Akzent
BG, SIDE, SURF, HOVER, LINE = "#0d0e12", "#090a0d", "#15171d", "#1c1f27", "#23262f"
TXT, MUTED, ACC, ACC_H, ACC_TXT, ERR = "#e8eaf0", "#7b8194", "#2f4bb8", "#3b5bdb", "#8aa4ff", "#e5646a"
MAC = sys.platform == "darwin"
FONT = ".AppleSystemUIFont" if MAC else "Segoe UI"
_bytes, _photos = {}, {}


# ---------- Daten ----------
def get_bytes(url):
    if url and url not in _bytes:
        _bytes[url] = requests.get(url, timeout=15).content
    return _bytes.get(url)


def login(url):
    q = parse_qs(urlparse(url.strip()).fragment)
    access, id_token = q["access_token"][0], q["id_token"][0]
    bearer = {"Authorization": f"Bearer {access}"}
    def ok(r):
        r.raise_for_status()
        return r.json()
    ent = ok(requests.post("https://entitlements.auth.riotgames.com/api/token/v1",
                           headers=bearer, json={}, timeout=15))["entitlements_token"]
    puuid = ok(requests.get("https://auth.riotgames.com/userinfo", headers=bearer, timeout=15))["sub"]
    geo = ok(requests.put("https://riot-geo.pas.si.riotgames.com/pas/v1/product/valorant",
                          headers=bearer, json={"id_token": id_token}, timeout=15))["affinities"]["live"]
    shard = {"latam": "na", "br": "na"}.get(geo, geo)
    ver = requests.get(f"{API}/version", timeout=10).json()["data"]["riotClientVersion"]
    h = {**bearer, "X-Riot-Entitlements-JWT": ent, "X-Riot-ClientPlatform": PLATFORM,
         "X-Riot-ClientVersion": ver}
    return h, puuid, f"https://pd.{shard}.a.pvp.net"


def fetch_shop(creds):
    h, puuid, pd = creds
    r = requests.post(f"{pd}/store/v3/storefront/{puuid}", headers=h, json={}, timeout=15)
    data = r.json() if r.status_code == 200 else {}
    if "SkinsPanelLayout" not in data:
        r = requests.get(f"{pd}/store/v2/storefront/{puuid}", headers=h, timeout=15)
        data = r.json() if r.status_code == 200 else {}
    if "SkinsPanelLayout" not in data:
        raise RuntimeError(f"Shop-Antwort unerwartet (HTTP {r.status_code}): {r.text[:200]}")
    layout = data["SkinsPanelLayout"]
    store = layout.get("SingleItemStoreOffers") or []
    uids = layout.get("SingleItemOffers") or [o["OfferID"] for o in store]
    secs = layout.get("SingleItemOffersRemainingDurationInSeconds", 0)
    prices = {o.get("OfferID"): (o.get("Cost") or {}).get(VP) for o in store}
    if not prices:
        try:
            offers = requests.get(f"{pd}/store/v1/offers", headers=h, timeout=15).json().get("Offers", [])
            prices = {o.get("OfferID"): (o.get("Cost") or {}).get(VP) for o in offers}
        except Exception:
            pass
    items = []
    for uid in uids:
        d = requests.get(f"{API}/weapons/skinlevels/{uid}", timeout=15).json().get("data") or {}
        get_bytes(d.get("displayIcon"))
        items.append((d.get("displayName", uid), prices.get(uid, "?"), d.get("displayIcon")))
    return items, secs


def fetch_locker(creds):
    h, puuid, pd = creds
    r = requests.get(f"{pd}/store/v1/entitlements/{puuid}/{SKIN_LEVEL_TYPE}", headers=h, timeout=15)
    r.raise_for_status()
    owned = {e["ItemID"] for e in r.json()["Entitlements"]}
    out = {}
    for w in requests.get(f"{API}/weapons", timeout=30).json()["data"]:
        for s in w["skins"]:
            if s["displayName"].startswith(("Standard", "Random")):
                continue
            if any(l["uuid"] in owned for l in s["levels"]):
                icon = (s.get("displayIcon") or s["levels"][0].get("displayIcon")
                        or (s["chromas"][0].get("fullRender") if s["chromas"] else None))
                out.setdefault(w["displayName"], []).append((s["displayName"], icon))
    return {k: sorted(v) for k, v in sorted(out.items())}


def login_window(outfile):
    """Eigener Prozess: zeigt die Riot-Anmeldung, schreibt die Weiterleitungs-URL in outfile."""
    try:
        import time, webview
        win = webview.create_window("Riot Login", AUTH_URL, width=520, height=740)
        def watch():
            while True:
                time.sleep(0.3)
                try:
                    url = win.get_current_url()
                except Exception:
                    return
                if url and "access_token=" in url:
                    open(outfile, "w").write(url)
                    win.destroy()
                    return
        store = os.path.expanduser("~/.valorant_shop")
        os.makedirs(store, exist_ok=True)
        webview.start(watch, private_mode=False, storage_path=store)
    except Exception as e:
        open(outfile, "w").write(f"ERR: {type(e).__name__}: {e}")
    os._exit(0)


# ---------- UI-Bausteine ----------
def photo(url, size):
    key = (url, size)
    if key not in _photos and _bytes.get(url):
        im = Image.open(io.BytesIO(_bytes[url])).convert("RGBA")
        im.thumbnail(size, Image.LANCZOS)
        _photos[key] = ImageTk.PhotoImage(im)
    return _photos.get(key)


def font(size=11, bold=False):
    return (FONT, size, "bold") if bold else (FONT, size)


def text(parent, s="", size=11, fg=TXT, bold=False, bg=None, **kw):
    return tk.Label(parent, text=s, fg=fg, bg=bg or parent["bg"], font=font(size, bold), **kw)


def button(parent, s, cmd, primary=True):
    base, hov = (ACC, ACC_H) if primary else (SURF, HOVER)
    b = tk.Label(parent, text=s, fg="white" if primary else TXT, bg=base, font=font(11, True),
                 padx=22, pady=10, cursor="hand2")
    b.bind("<Button-1>", lambda e: cmd())
    b.bind("<Enter>", lambda e: b.config(bg=hov))
    b.bind("<Leave>", lambda e: b.config(bg=base))
    return b


def skin_card(parent, name, url, sub=None, size=(180, 76)):
    c = tk.Frame(parent, bg=SURF)
    inner = tk.Frame(c, bg=SURF, padx=16, pady=16)
    inner.pack(fill="both", expand=True)
    p = photo(url, size)
    if p:
        img = tk.Label(inner, image=p, bg=SURF)
        img.image = p
        img.pack(pady=(4, 14))
    text(inner, name, 11, TXT, True, anchor="w", justify="left", wraplength=size[0]).pack(anchor="w", fill="x")
    if sub:
        text(inner, sub, 10, ACC_TXT, anchor="w").pack(anchor="w", pady=(4, 0))
    return c


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Valorant Shop")
        self.geometry("1100x720")
        self.minsize(940, 600)
        self.configure(bg=BG)
        self.creds, self.locker, self.token, self.nav = None, None, 0, {}
        bar = tk.Frame(self, bg=SIDE)
        bar.pack(side="bottom", fill="x")
        self.status = text(bar, "", 9, MUTED, anchor="w", wraplength=900, justify="left")
        self.status.pack(fill="x", padx=20, pady=7)
        self.root_frame = tk.Frame(self, bg=BG)
        self.root_frame.pack(fill="both", expand=True)
        self.login_view()

    # --- Hilfen ---
    def clear(self, w):
        for c in w.winfo_children():
            c.destroy()

    def say(self, msg="", err=False):
        self.status.config(text=msg, fg=ERR if err else MUTED)

    def bg(self, fn, done, loading="Lade ..."):
        t = self.token
        self.say(loading)
        def work():
            try:
                res = fn()
                self.after(0, lambda: (self.say(), done(res) if t == self.token else None))
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                self.after(0, lambda: self.say(msg, True))
        threading.Thread(target=work, daemon=True).start()

    # --- Login ---
    def login_view(self):
        self.clear(self.root_frame)
        box = tk.Frame(self.root_frame, bg=BG)
        box.place(relx=0.5, rely=0.46, anchor="center")
        text(box, "Valorant Shop", 28, TXT, True).pack()
        text(box, "Dein täglicher Shop und dein Locker.\nOhne installiertes Valorant.", 12, MUTED,
             justify="center").pack(pady=(10, 34))
        button(box, "Mit Riot anmelden", self.do_login).pack()
        text(box, "Die Anmeldung läuft über das offizielle Riot-Fenster.\n"
                  "Es werden keine Passwörter gespeichert.", 10, MUTED, justify="center").pack(pady=(28, 0))

    def do_login(self):
        def run():
            out = tempfile.mktemp(suffix=".txt")
            cmd = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, os.path.abspath(__file__)]
            subprocess.run(cmd + ["--login", out], timeout=900)
            url = open(out).read() if os.path.exists(out) else ""
            if os.path.exists(out):
                os.remove(out)
            if "access_token=" not in url:
                raise RuntimeError(url or "Anmeldung abgebrochen")
            return login(url)
        def done(creds):
            self.creds = creds
            self.main_view()
        self.bg(run, done, "Warte auf Anmeldung ...")

    # --- Hauptansicht ---
    def main_view(self):
        self.clear(self.root_frame)
        side = tk.Frame(self.root_frame, bg=SIDE, width=210)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        text(side, "Valorant Shop", 14, TXT, True, anchor="w").pack(fill="x", padx=24, pady=(28, 28))
        for key, label, cmd in (("shop", "Daily Shop", self.show_shop), ("locker", "Locker", self.show_locker)):
            n = tk.Label(side, text=label, font=font(12), fg=MUTED, bg=SIDE, anchor="w", padx=24, pady=10,
                         cursor="hand2")
            n.pack(fill="x")
            n.bind("<Button-1>", lambda e, c=cmd: c())
            self.nav[key] = n
        self.content = tk.Frame(self.root_frame, bg=BG)
        self.content.pack(side="left", fill="both", expand=True, padx=40, pady=32)
        self.show_shop()

    def page(self, key, title, sub=""):
        self.token += 1
        for k, n in self.nav.items():
            n.config(fg=TXT if k == key else MUTED, bg=HOVER if k == key else SIDE)
        self.clear(self.content)
        head = tk.Frame(self.content, bg=BG)
        head.pack(fill="x", pady=(0, 24))
        text(head, title, 24, TXT, True).pack(side="left")
        self.sub = text(head, sub, 11, MUTED)
        self.sub.pack(side="left", padx=16, pady=(8, 0))
        return head

    # --- Shop ---
    def show_shop(self):
        head = self.page("shop", "Daily Shop")
        button(head, "Aktualisieren", self.show_shop, False).pack(side="right")
        self.bg(lambda: fetch_shop(self.creds), self.render_shop)

    def render_shop(self, res):
        items, secs = res
        self.sub.config(text=f"Rotation in {secs // 3600} Std. {secs % 3600 // 60} Min.")
        row = tk.Frame(self.content, bg=BG)
        row.pack(fill="x")
        for i, (name, price, url) in enumerate(items):
            row.grid_columnconfigure(i, weight=1, uniform="c")
            skin_card(row, name, url, f"{price} VP", (190, 90)).grid(
                row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0 if i == len(items) - 1 else 8))

    # --- Locker ---
    def show_locker(self):
        self.page("locker", "Locker")
        if self.locker:
            return self.render_locker(self.locker)
        self.bg(lambda: fetch_locker(self.creds), self.render_locker)

    def render_locker(self, data):
        self.locker = data
        self.sub.config(text=f"{sum(len(v) for v in data.values())} Skins")
        side = tk.Frame(self.content, bg=BG, width=170)
        side.pack(side="left", fill="y", padx=(0, 24))
        area = tk.Frame(self.content, bg=BG)
        area.pack(side="left", fill="both", expand=True)
        self.weapons = {}
        for w, skins in data.items():
            l = tk.Label(side, text=f"{w}   {len(skins)}", font=font(11), fg=MUTED, bg=BG, anchor="w",
                         padx=12, pady=6, cursor="hand2")
            l.pack(fill="x")
            l.bind("<Button-1>", lambda e, w=w: self.open_weapon(w, area))
            self.weapons[w] = l
        if data:
            self.open_weapon(next(iter(data)), area)

    def open_weapon(self, weapon, area):
        self.token += 1
        for w, l in self.weapons.items():
            l.config(fg=TXT if w == weapon else MUTED, bg=SURF if w == weapon else BG)
        self.clear(area)
        skins = self.locker[weapon]
        def fetch():
            with ThreadPoolExecutor(8) as ex:
                list(ex.map(lambda s: get_bytes(s[1]), skins))
        self.bg(fetch, lambda _: self.grid_skins(area, skins))

    def grid_skins(self, area, skins):
        self.clear(area)
        cv = tk.Canvas(area, bg=BG, highlightthickness=0, bd=0)
        cv.pack(fill="both", expand=True)
        inner = tk.Frame(cv, bg=BG)
        win = cv.create_window((0, 0), window=inner, anchor="nw")
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        div = 1 if MAC else 120
        cv.bind("<Enter>", lambda e: cv.bind_all("<MouseWheel>", lambda ev: cv.yview_scroll(int(-ev.delta / div), "units")))
        cv.bind("<Leave>", lambda e: cv.unbind_all("<MouseWheel>"))
        cols = 3
        for c in range(cols):
            inner.grid_columnconfigure(c, weight=1, uniform="s")
        for i, (name, url) in enumerate(skins):
            skin_card(inner, name, url, size=(170, 70)).grid(row=i // cols, column=i % cols,
                                                            sticky="nsew", padx=6, pady=6)


if __name__ == "__main__":
    if "--login" in sys.argv:
        login_window(sys.argv[sys.argv.index("--login") + 1])
    else:
        App().mainloop()
