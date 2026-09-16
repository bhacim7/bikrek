# -*- coding: utf-8 -*-
"""Iki kosumun enkoder kayitlarini ayni olcutlerle karsilastir."""
import csv
import numpy as np


def yukle(yol):
    r = list(csv.DictReader(open(yol)))
    t = np.array([float(x['t']) for x in r])
    sy = np.array([float(x['sayac_yaw']) for x in r])
    ey = np.array([float(x['enk_yaw']) for x in r])
    sp = np.array([float(x['sayac_pitch']) for x in r])
    return t - t[0], sy, ey, sp


def olc(ad, t, sy, ey, a, b):
    m = (t >= a) & (t <= b)
    tt, s, e = t[m], sy[m], ey[m]
    ds = np.diff(s)
    dt = np.maximum(np.diff(tt), 1e-3)
    buyuk = np.abs(ds) > 0.02
    isaret = np.sign(ds[buyuk])
    yon = int(np.sum(isaret[1:] * isaret[:-1] < 0)) if len(isaret) > 1 else 0
    sure = b - a
    ve = np.abs(np.diff(e) / dt)
    # komut araliklari (sayac degisim anlari)
    degis = np.where(np.abs(ds) > 1e-6)[0]
    bosluk = np.diff(tt[degis]) if len(degis) > 1 else np.array([0.0])
    fark = s - e
    print(f"{ad:26s} sure {sure:5.1f} sn | yon degisimi {yon:3d} "
          f"({yon / sure * 55:5.1f}/55sn) | tepe enk hiz {ve.max():6.1f} d/s | "
          f"p99 hiz {np.percentile(ve, 99):5.1f} | sayac adimi p90 {np.percentile(np.abs(ds[np.abs(ds) > 1e-6]), 90):.2f} "
          f"max {np.abs(ds).max():.2f} | durus>150ms {int(np.sum(bosluk > 0.15))}/{len(bosluk)} | "
          f"|sayac-enk| ort {np.mean(np.abs(fark)):.2f} max {np.abs(fark).max():.2f}")
    return yon / sure * 55, ve.max()


print("=" * 150)
t1, s1, e1, p1 = yukle(r"enkoder_kayit/enkoder_20260916_142911.csv")
# 1. kosum: video 3.0-51.5 -> CSV ofseti 61.507-3.2
o1 = 61.507 - 3.2
olc("ONCE  (asama3Denem)", t1, s1, e1, o1 + 3.0, o1 + 51.5)

t2, s2, e2, p2 = yukle(r"enkoder_kayit/enkoder_20260916_152053.csv")
o2 = 229.03 - 3.75      # video t=3.75'te -1.9'dan ayriliyor
olc("SONRA (asama3Deneme2)", t2, s2, e2, o2 + 3.7, o2 + 19.0)
print("=" * 150)

# SONRA kosumunda 0.5 sn'lik ozet
print("\nSONRA kosumu, video zamanina hizalanmis (0.5 sn adim):")
print(" vid_t  sayac    enk   fark  pitch")
m = (t2 >= o2) & (t2 <= o2 + 20.5)
tt, s, e, p = t2[m] - o2, s2[m], e2[m], p2[m]
for k in np.arange(0, 20.5, 0.5):
    sel = (tt >= k) & (tt < k + 0.5)
    if sel.any():
        print(f"{k:5.1f} {s[sel][-1]:7.2f} {e[sel][-1]:7.2f} {s[sel][-1] - e[sel][-1]:6.2f} {p[sel][-1]:6.2f}")

# ates anı civari (video 4.4-5.2)
print("\nAtes ani civari (video 4.3-5.0 s), 21 ms cozunurlukte:")
sel = (tt >= 4.3) & (tt <= 5.0)
for x, y, z in zip(tt[sel], s[sel], e[sel]):
    print(f"{x:6.2f} {y:7.2f} {z:7.2f} {y - z:6.2f}")
