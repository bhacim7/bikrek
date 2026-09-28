# -*- coding: utf-8 -*-
"""
FAZ 4 — enkoder kaydını çözümle: ölçek, boşluk ve kaçırmayı AYIR.

Kullanım:
    python enkoder_analiz.py enkoder_kayit/enkoder_20260908_213000.csv
    python enkoder_analiz.py --test        (sentetik veriyle kendini sınar)

Kayıt: bukrek_main, config.ENCODER_LOG=True iken her Pi raporunda bir satır
yazar (t, sayac_yaw, sayac_pitch, enk_yaw, enk_ok, enk_ham).

Ölçüm dizisi (arayüzden, her adımdan sonra 1.5-2 sn DUR):
    0 → +10 → +20 → … → +60 → +50 → … → 0 → −10 → … → −60 → −50 → … → 0
Aynı yönde ardışık duruşlar ÖLÇEĞİ verir (enk = a·sayaç + b), iki yönün
kesişim farkı (b₊ − b₋) BOŞLUĞU verir, artık dağılımı KAÇIRMAYI (adım
kaybı, rastgele) verir. Sıfıra dönüşlerdeki Δ ayrıca listelenir.

Model:  enk = a·sayaç + b_yön ,  yön = duruşa gelirken sayaç artıyorsa +.
Taret, yön değişiminde komutu b kadar geç izler; + yönden gelince geride
(enk küçük), − yönden gelince ileride (enk büyük) → b₋ − b₊ ≈ boşluk.
"""
import sys
import numpy as np

DURUS_SURE = 0.6      # sn: bu süre boyunca ikisi de sabitse duruş
DURUS_ESIK = 0.06     # derece: pencere içindeki oynama sınırı
MIN_HAREKET = 2.0     # derece: iki duruş arası bundan azsa aynı duruş sayılır


def oku(yol):
    t, s, e = [], [], []
    with open(yol, encoding="utf-8") as f:
        next(f)
        for satir in f:
            p = satir.strip().split(",")
            if len(p) < 5 or p[3] == "" or p[4] != "1":
                continue
            t.append(float(p[0])); s.append(float(p[1])); e.append(float(p[3]))
    return np.array(t), np.array(s), np.array(e)


def duruslar(t, s, e):
    """(sayaç, enk, yön) listesi. yön: +1 / −1 / 0 (ilk duruş)."""
    out = []
    n = len(t)
    i = 0
    while i < n:
        j = i
        while j < n and t[j] - t[i] < DURUS_SURE:
            j += 1
        if j >= n:
            break
        pen_s = s[i:j]; pen_e = e[i:j]
        if pen_s.max() - pen_s.min() < DURUS_ESIK and pen_e.max() - pen_e.min() < DURUS_ESIK:
            # duruşu uzat: sabit kaldığı sürece
            k = j
            while k < n and abs(s[k] - pen_s[0]) < DURUS_ESIK and abs(e[k] - pen_e[0]) < DURUS_ESIK:
                k += 1
            ms, me = float(np.median(s[i:k])), float(np.median(e[i:k]))
            if not out or abs(ms - out[-1][0]) >= MIN_HAREKET:
                yon = 0 if not out else (1 if ms > out[-1][0] else -1)
                out.append((ms, me, yon))
            i = k
        else:
            i += 1
    return out


def coz(dur):
    """Ortak eğim, yöne bağlı kesişim: enk = a·s + b_yön (en küçük kareler)."""
    d = [x for x in dur if x[2] != 0]
    if len(d) < 4:
        return None
    S = np.array([x[0] for x in d]); E = np.array([x[1] for x in d]); Y = np.array([x[2] for x in d])
    A = np.column_stack([S, (Y > 0).astype(float), (Y < 0).astype(float)])
    (a, bp, bm), *_ = np.linalg.lstsq(A, E, rcond=None)
    artik = E - A @ np.array([a, bp, bm])
    return dict(a=a, b_arti=bp, b_eksi=bm, bosluk=bm - bp, artik_rms=float(np.sqrt(np.mean(artik ** 2))),
                artik_max=float(np.abs(artik).max()), n=len(d))


def rapor(dur, sonuc):
    print(f"{'sayac':>8} {'enkoder':>9} {'delta':>7}  yon")
    for s, e, y in dur:
        print(f"{s:8.2f} {e:9.2f} {e - s:7.2f}  {'+' if y > 0 else '-' if y < 0 else 'ilk'}")
    sifir = [(s, e) for s, e, y in dur if abs(s) < 1.0 and y != 0]
    if sifir:
        print("\nSIFIRA DONUSLER (sayac ~0 iken enkoder):", ", ".join(f"{e:+.2f}" for _, e in sifir))
    if sonuc is None:
        print("\nYeterli durus yok (en az 4, iki yonde)."); return
    print(f"""
OLCEK   a = {sonuc['a']:.4f}   (enk / sayac; 1.000 = birebir. Kamera olcegiyle R'ye cevrilir,
          bkz. ENKODER_ENTEGRASYON.md 7.3. a-1 = {100*(sonuc['a']-1):+.1f} %)
BOSLUK  b(-) - b(+) = {sonuc['bosluk']:+.2f} derece   (yon degisiminde taretin komutu gec izledigi miktar)
          b(+) = {sonuc['b_arti']:+.2f}   b(-) = {sonuc['b_eksi']:+.2f}
KACIRMA artik RMS {sonuc['artik_rms']:.2f} derece, max {sonuc['artik_max']:.2f}   (modelin aciklayamadigi rastgele kisim)
          {sonuc['n']} durus kullanildi""")


def _sentetik():
    rng = np.random.default_rng(1)
    a, bos = 1.024, 0.8
    hedefler = list(range(0, 70, 10)) + list(range(50, -70, -10)) + list(range(-50, 10, 10))
    t, s, e = [], [], []
    zaman = 0.0; onceki = 0.0
    for h in hedefler:
        yon = 1 if h > onceki else -1
        # hareket: 1 sn boyunca dogrusal
        for k in range(50):
            sv = onceki + (h - onceki) * k / 50
            t.append(zaman); s.append(sv); e.append(a * sv + rng.normal(0, 0.02)); zaman += 0.02
        # durus: 1.5 sn
        kayma = -bos / 2 if yon > 0 else bos / 2
        gurultu = rng.normal(0, 0.05)
        for k in range(75):
            t.append(zaman); s.append(h); e.append(a * h + kayma + gurultu + rng.normal(0, 0.01)); zaman += 0.02
        onceki = h
    return np.array(t), np.array(s), np.array(e), a, bos


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    if sys.argv[1] == "--test":
        t, s, e, a0, b0 = _sentetik()
        d = duruslar(t, s, e); r = coz(d); rapor(d, r)
        ok = r is not None and abs(r['a'] - a0) < 0.005 and abs(r['bosluk'] - b0) < 0.15
        print("\nSENTETIK TEST:", "GECTI" if ok else "KALDI", f"(gercek a={a0}, bosluk={b0})")
        sys.exit(0 if ok else 1)
    t, s, e = oku(sys.argv[1])
    print(f"{len(t)} satir, {t[-1]-t[0]:.0f} sn")
    d = duruslar(t, s, e); rapor(d, coz(d))
