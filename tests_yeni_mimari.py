"""Yeni mimarinin birim testleri: eşleştirme, dost/düşman, durum makinesi."""
import sys, time
sys.path.insert(0, r"C:\Users\barış hacim\PycharmProjects\PythonProject\HSSmultipocess")

import numpy as np
import cv2
import config
import engagement
import spotter_module as sp

hata = 0


def kontrol(ad, kosul, ek=""):
    global hata
    if not kosul:
        hata += 1
    print(f"  [{'OK ' if kosul else 'HATA'}] {ad}{(' — ' + ek) if ek else ''}")


def det(sinif, x, y, w, h, skor=0.9):
    return {'class_name': sinif, 'bbox': (x, y, w, h), 'score': skor}


print("=" * 70)
print("1. HEDEF CIFTI ESLESTIRME (geometrik, mesafeden bagimsiz)")
print("=" * 70)

# 15 metre: maket 96 px, balon 30 px, balon maketin ~1.2 maket-genisligi altinda
uzak = [det('dusman-Drone', 600, 300, 96, 60), det('balon', 633, 415, 30, 30)]
c = engagement.cift_eslestir(uzak)
kontrol("uzak hedef eslesti", len(c) == 1 and c[0].balon is not None)
kontrol("sinif dusman", engagement.dusman_mi(c[0].sinif), c[0].sinif)

# 5 metre: her sey 3 kat buyuk. AYNI kural calismali (normalize edildigi icin)
yakin = [det('dusman-Drone', 400, 200, 288, 180), det('balon', 499, 545, 90, 90)]
c = engagement.cift_eslestir(yakin)
kontrol("yakin hedef eslesti (ayni kural)", len(c) == 1 and c[0].balon is not None)

# Balon maketin USTUNDE ise eslesmemeli
ters = [det('dusman-Drone', 600, 400, 96, 60), det('balon', 633, 300, 30, 30)]
c = engagement.cift_eslestir(ters)
kontrol("balon ustteyse eslesmez", c[0].balon is None)

# Balon yatayda cok uzaksa eslesmemeli
kaymis = [det('dusman-Drone', 600, 300, 96, 60), det('balon', 900, 415, 30, 30)]
c = engagement.cift_eslestir(kaymis)
kontrol("yatayda uzak balon eslesmez", c[0].balon is None)

# Iki hedef: her maket kendi balonuyla eslesmeli
ikili = [det('dusman-F16', 200, 300, 90, 55), det('balon', 230, 410, 28, 28),
         det('dost-Helikopter', 800, 300, 90, 55), det('balon', 830, 410, 28, 28)]
c = engagement.cift_eslestir(ikili)
kontrol("iki cift kuruldu", len(c) == 2)
dogru = all(x.balon is not None for x in c)
kontrol("her maket kendi balonunu aldi", dogru)
siniflar = sorted(x.sinif for x in c)
kontrol("dost ve dusman ayri", siniflar == ['dost-Helikopter', 'dusman-F16'], str(siniflar))

# Tek basina duran balon hedef cifti olusturmaz (hayalet eleyici)
c = engagement.cift_eslestir([det('balon', 600, 400, 30, 30)])
kontrol("yalniz balon cift olusturmaz", len(c) == 0)

print()
print("=" * 70)
print("2. NISAN NOKTASI ve YEDEK YOL")
print("=" * 70)
c = engagement.cift_eslestir(uzak)[0]
cx, cy, r, gercek = c.nisan_noktasi()
# Nisan noktasi AIM_POINT_HEIGHT_RATIO ile belirleniyor; su anda 0.5 =
# balonun TAM MERKEZI. Oran buyutulurse kutunun ust tarafina kayar (paralaks
# telafisi; gerekce config.py icinde).
_ust, _yuk = uzak[1]['bbox'][1], uzak[1]['bbox'][3]
_beklenen_y = _ust + (1.0 - config.AIM_POINT_HEIGHT_RATIO) * _yuk
kontrol("balon varken balona nisan (yatayda merkez)",
        gercek and abs(cx - 648) < 2, f"cx={cx:.0f}")
kontrol("nisan noktasi ayarlanan orana uyuyor",
        abs(cy - _beklenen_y) < 1.0,
        f"y={cy:.1f}, beklenen {_beklenen_y:.1f} (oran {config.AIM_POINT_HEIGHT_RATIO})")
kontrol("nisan noktasi kutunun ICINDE kaliyor",
        _ust <= cy <= _ust + _yuk, f"{_ust} <= {cy:.1f} <= {_ust+_yuk}")
# Oran 0.5 iken nisan TAM MERKEZ olmali; buyudukce yukari kaymali.
_merkez_y = _ust + _yuk / 2.0
if abs(config.AIM_POINT_HEIGHT_RATIO - 0.5) < 1e-9:
    kontrol("oran 0.5 -> nisan noktasi TAM MERKEZ",
            abs(cy - _merkez_y) < 1e-6, f"y={cy:.1f}, merkez {_merkez_y:.1f}")
else:
    _kayma_cm = (config.AIM_POINT_HEIGHT_RATIO - 0.5) * 2 * 7.0
    kontrol("oran > 0.5 -> nisan noktasi merkezin USTUNDE",
            cy < _merkez_y, f"{_kayma_cm:.1f} cm yukari (paralaks 5.5 cm)")
c2 = engagement.HedefCifti(uzak[0], None, 0.0)
cx2, cy2, r2, gercek2 = c2.nisan_noktasi()
kontrol("balon yokken maketten turetiliyor", (not gercek2) and cy2 > uzak[0]['bbox'][1],
        f"({cx2:.0f},{cy2:.0f})")

print()
print("=" * 70)
print("3. GOZCU DOST/DUSMAN — mesafeden bagimsizlik")
print("=" * 70)


def sahne(gen, yuk, hedefler):
    """hedefler: [(cx, cy, balon_cap, maket_gen, maket_yuk, maket_rengi)]"""
    img = np.zeros((yuk, gen, 3), np.uint8)
    for cx, cy, cap, mg, my, renk in hedefler:
        cv2.circle(img, (cx, cy), cap // 2, (0, 0, 230), -1)          # kirmizi balon
        bgr = (230, 60, 0) if renk == 'mavi' else (0, 0, 230)
        ust = cy - int(cap * 1.6)
        cv2.rectangle(img, (cx - mg // 2, ust - my // 2),
                      (cx + mg // 2, ust + my // 2), bgr, -1)
    return img


# Kritik senaryo: YAKIN DOST + UZAK DUSMAN.
# "En buyuk kirmizi = dusman" kurali burada CUVALLIYOR; geometri kurali dogru
# cevabi vermeli.
img = sahne(1280, 720, [
    (300, 400, 120, 340, 110, 'mavi'),   # YAKIN DOST  (buyuk mavi maket)
    (1000, 380, 34, 90, 32, 'kirmizi'),  # UZAK DUSMAN (kucuk kirmizi maket)
])
yon = sp.IzYoneticisi()
izler, kirmizi, mavi = sp.kareyi_coz(img, yon, time.time())
izler, _, _ = sp.kareyi_coz(img, yon, time.time() + 0.04)   # gorulme >= 2 icin

bulunan = {}
for iz in izler:
    yan = 'sol' if iz.yaw < 0 else 'sag'
    bulunan[yan] = iz
print(f"  bulunan iz sayisi: {len(izler)}")
for iz in izler:
    print(f"    yaw {iz.yaw:+6.1f}  sinif={iz.sinif:9s} mavi_oran={iz.mavi_oran:.2f} "
          f"kirmizi_alan={iz.kirmizi_alan}")

kontrol("iki hedef de bulundu", len(izler) == 2)
if 'sol' in bulunan and 'sag' in bulunan:
    kontrol("yakin buyuk hedef DOST olarak isaretlendi",
            bulunan['sol'].sinif == sp.DOST, bulunan['sol'].sinif)
    kontrol("uzak kucuk hedef DUSMAN olarak isaretlendi",
            bulunan['sag'].sinif == sp.DUSMAN, bulunan['sag'].sinif)
    # ESKI kuralin cuvalladigini goster
    eski_kural = max(izler, key=lambda i: i.kirmizi_alan)
    print(f"  >>> ESKI kural ('en buyuk kirmizi') secerdi: yaw {eski_kural.yaw:+.1f} "
          f"({eski_kural.sinif})")
    kontrol("eski kural gercekten dostu secerdi (sorunun kaniti)",
            eski_kural.sinif == sp.DOST)

print()
print("=" * 70)
print("4. ADAY SIRALAMA — Asama 3'te dost EN SONA siralanir (elenmez)")
print("=" * 70)
kl = engagement.KaraListe()
izl = [iz.sozluk() for iz in izler]
s3 = engagement.aday_sirala(izl, kl, 'task3')
# ESKIDEN dost adaylari listeden SILINIYORDU. Gozcu dusmani yanlislikla dost
# sayarsa o hedef bir daha hic denenmiyordu; sona siralamanin maliyeti ise
# yalnizca zaman, cunku ates kilidi zaten `dusman-` sarti ariyor.
kontrol("asama3: dost aday listede KALIYOR",
        any(i['sinif'] == 'dost' for i in s3), str([i['sinif'] for i in s3]))
kontrol("asama3: dusman dosttan ONCE deneniyor",
        s3[0]['sinif'] == 'dusman' and s3[-1]['sinif'] == 'dost',
        str([i['sinif'] for i in s3]))
s2 = engagement.aday_sirala(izl, kl, 'task2')
kontrol("asama2: en buyuk kirmizi once", len(s2) >= 1 and s2[0]['kirmizi_alan'] >=
        (s2[1]['kirmizi_alan'] if len(s2) > 1 else 0))

print()
print("=" * 70)
print("5. DURUM MAKINESI — dost dogrulamasi angajmani iptal etmeli")
print("=" * 70)
m = engagement.AngajmanMakinesi()
m.basla('task3')
kontrol("baslangic TARAMA", m.durum == engagement.TARAMA, m.durum)

sahte_iz = [{'id': 1, 'yaw': 12.0, 'pitch': -2.0, 'yaw_hiz': 1.0, 'pitch_hiz': 0.0,
             'sinif': 'kararsiz', 'mavi_oran': 0.4, 'kirmizi_alan': 900,
             'cap': 20, 'gorulme': 5, 'kayip': 0}]
hedef = m.tarama_adimi(sahte_iz)
kontrol("YONELME'ye gecti", m.durum == engagement.YONELME, m.durum)
kontrol("hedef acisi ONGORULU (hiz x sure eklenmis)", hedef[0] > 12.0,
        f"{hedef[0]:.3f} > 12.0")

m.yonelme_adimi(hedef[0], hedef[1])
kontrol("taret oturunca DOGRULAMA", m.durum == engagement.DOGRULAMA, m.durum)

# DOST dogrulanirsa: kara listeye girmeli, TARAMA'ya donmeli
dost_cift = engagement.cift_eslestir(
    [det('dost-F16', 600, 300, 96, 60, 0.9), det('balon', 633, 415, 30, 30, 0.9)])
for _ in range(config.VERIFY_CONFIRM_FRAMES):
    m.dogrulama_adimi(dost_cift)
kontrol("dost -> TARAMA'ya donuldu", m.durum == engagement.TARAMA, m.durum)
kontrol("dost kara listeye alindi", m.kara_liste.icinde_mi(hedef[0], hedef[1]))
kontrol("kara listedeki aday bir daha secilmiyor",
        m.tarama_adimi([{**sahte_iz[0], 'yaw': hedef[0], 'pitch': hedef[1]}]) is None)

# DUSMAN dogrulanirsa: KILIT'e gecmeli
m2 = engagement.AngajmanMakinesi()
m2.basla('task2')
h = m2.tarama_adimi(sahte_iz)
m2.yonelme_adimi(h[0], h[1])
dusman_cift = engagement.cift_eslestir(uzak)
for _ in range(config.VERIFY_CONFIRM_FRAMES):
    m2.dogrulama_adimi(dusman_cift)
kontrol("dusman -> KILIT", m2.durum == engagement.KILIT, m2.durum)

# Nisan tutulunca ATES
for _ in range(config.AIM_HOLD_FRAMES):
    m2.kilit_adimi(2.0, 15.0, True)
kontrol("nisan tutulunca ATES", m2.durum == engagement.ATES, m2.durum)

print()
print("=" * 70)
print("6. ATES KILIDI")
print("=" * 70)
cift = dusman_cift[0]
izin, ger = engagement.ates_serbest_mi(cift, m2, True, True, 0.0, 0.0, 0.0)
kontrol("tum kosullar tamamsa serbest", izin, ger)

izin, ger = engagement.ates_serbest_mi(cift, m2, False, True, 0.0, 0.0, 0.0)
kontrol("balon GORULMEDIYSE engellenir (eski Asama3 acigi)", not izin, ger)

izin, ger = engagement.ates_serbest_mi(
    engagement.HedefCifti(None, cift.balon, 1.0), m2, True, True, 0.0, 0.0, 0.0)
kontrol("maket yoksa engellenir", not izin, ger)

dost = engagement.cift_eslestir(
    [det('dost-F16', 600, 300, 96, 60), det('balon', 633, 415, 30, 30)])[0]
izin, ger = engagement.ates_serbest_mi(dost, m2, True, True, 0.0, 0.0, 0.0)
kontrol("DOST'a ates engellenir", not izin, ger)

izin, ger = engagement.ates_serbest_mi(cift, m2, True, False, 0.0, 0.0, 0.0)
kontrol("nisan disindaysa engellenir", not izin, ger)

izin, ger = engagement.ates_serbest_mi(cift, m2, True, True, 5.0, -15.0, 15.0)
kontrol("atesiz bolgede engellenir", not izin, ger)

izin, ger = engagement.ates_serbest_mi(cift, m2, True, True, 0.0, 0.0, 0.0)
kontrol("atesiz bolge (0,0) tanimsiz sayilir — eski hata", izin, ger)

print()
print("=" * 70)
print("7. OLCEK KONTROLLERI (15 metre, gercek boyutlar)")
print("=" * 70)
balon_aci = 2 * np.degrees(np.arctan(0.07 / 15))
maket_aci = 2 * np.degrees(np.arctan(0.225 / 15))
b_avci = balon_aci / config.HUNTER_DPP_YAW
m_avci = maket_aci / config.HUNTER_DPP_YAW
b_gozcu = balon_aci / config.SPOTTER_DPP_YAW
print(f"  balon 14 cm @ 15 m: {balon_aci:.3f} derece -> avci {b_avci:.0f} px, gozcu {b_gozcu:.0f} px")
print(f"  maket 45 cm @ 15 m: {maket_aci:.3f} derece -> avci {m_avci:.0f} px")
kontrol("balon avcida YOLO icin yeterli (>=20 px)", b_avci >= 20, f"{b_avci:.0f} px")
kontrol("balon gozcude blob icin yeterli (>=8 px)", b_gozcu >= 8, f"{b_gozcu:.0f} px")
kontrol("gozcu min blob alani balonun altinda",
        config.SPOTTER_MIN_BLOB_AREA < 3.14 * (b_gozcu / 2) ** 2,
        f"{config.SPOTTER_MIN_BLOB_AREA} < {3.14*(b_gozcu/2)**2:.0f}")

# Hedef acisal hizi ve feedforward olu bandi
for mesafe in (15, 8, 5):
    b = 7.5
    x = mesafe
    w = np.degrees(b / (x * x + b * b) * 0.4)
    ff_var = w >= config.FEEDFORWARD_VELOCITY_DEADBAND
    kalan = w * config.FEEDFORWARD_LEAD_TIME / config.HUNTER_DPP_YAW
    print(f"  {mesafe:2d} m: hedef {w:.2f} derece/sn | ff {'ACIK' if ff_var else 'kapali'} "
          f"| ff'siz kalan hata {kalan:.0f} px")
kontrol("olu bant gercek hedef hizlarinin altinda",
        config.FEEDFORWARD_VELOCITY_DEADBAND < 2.6,
        f"{config.FEEDFORWARD_VELOCITY_DEADBAND} < 2.6")

# Hata kapisi acisal anlamini korumali
tam, sifir = config.FEEDFORWARD_ERROR_GATE_PIXELS
print(f"  hata kapisi: {tam:.0f}/{sifir:.0f} px = "
      f"{tam*config.HUNTER_DPP_YAW:.2f}/{sifir*config.HUNTER_DPP_YAW:.2f} derece")
kontrol("hata kapisi genis kameradaki aciyi koruyor (~1.6/6.4 derece)",
        abs(tam * config.HUNTER_DPP_YAW - 1.6) < 0.2 and
        abs(sifir * config.HUNTER_DPP_YAW - 6.4) < 0.4)

# Avci gorus acisi devir teslime yetiyor mu
fov_y = config.HUNTER_WIDTH * config.HUNTER_DPP_YAW
fov_p = config.HUNTER_HEIGHT * abs(config.HUNTER_DPP_PITCH)
print(f"  avci gorus acisi: {fov_y:.1f} x {fov_p:.1f} derece")
kontrol("devir teslim payi yeterli (yari-pitch > 5 derece)", fov_p / 2 > 5,
        f"{fov_p/2:.1f}")

# --- 8. TEK BASINA BALON (kalibrasyon senaryosu) ---
print()
print("=" * 70)
print("8. TEK BASINA BALON — kalibrasyon icin kilitlenebilmeli, ates edilememeli")
print("=" * 70)
tek = [det('balon', 500, 400, 120, 120)]
kontrol("otonom modda cift olusmaz (guvenlik)",
        len(engagement.cift_eslestir(tek)) == 0)
_c = engagement.cift_eslestir(tek, tek_balonlara_izin=True)
kontrol("manuel/kalibrasyon modunda kilitlenebilir",
        len(_c) == 1 and _c[0].balon is not None and _c[0].maket is None)
_m = engagement.AngajmanMakinesi(); _m.basla('task2')
_m.durum = engagement.ATES; _m.dogrulanan_sinif = 'dusman-Drone'
_izin, _ger = engagement.ates_serbest_mi(_c[0], _m, True, True, 0.0, 0.0, 0.0)
kontrol("tek balona ATES asla serbest degil", not _izin, _ger)
_kar = [det('dusman-Drone', 600, 300, 96, 60), det('balon', 633, 415, 30, 30),
        det('balon', 200, 700, 40, 40)]
kontrol("manuel: cift + yalniz balon = 2 hedef",
        len(engagement.cift_eslestir(_kar, tek_balonlara_izin=True)) == 2)
kontrol("otonom: yalniz balon elenir = 1 hedef",
        len(engagement.cift_eslestir(_kar)) == 1)


# --- 9. DOGRULAMA ZAMAN ASIMI: aday kisa sureli kara listeye girmeli ---
print()
print("=" * 70)
print("9. DOGRULAMA ZAMAN ASIMI — bos acida sonsuz dongu olmamali")
print("=" * 70)
# Saha kaydi (AnalizVideo.mp4 17-23 sn): taret gozcunun -21 derece dedigi
# adaya gitti, avcida hicbir cift goremedi, DOGRULAMA zaman asimina ugradi,
# TARAMA ayni adayi yine sectii ve taret 4 saniye bos duvara bakti.
_iz_a = {'id': 1, 'yaw': -21.0, 'pitch': -0.4, 'yaw_hiz': 0.0, 'pitch_hiz': 0.0,
         'sinif': 'dusman', 'kirmizi_alan': 5000, 'gorulme': 9}
_iz_b = {'id': 2, 'yaw': 12.0, 'pitch': 1.0, 'yaw_hiz': 0.0, 'pitch_hiz': 0.0,
         'sinif': 'dusman', 'kirmizi_alan': 2000, 'gorulme': 9}
_m9 = engagement.AngajmanMakinesi()
_m9.basla('task2')
_ilk = _m9.tarama_adimi([_iz_a, _iz_b])
kontrol("once en buyuk kirmizi alanli aday secilir", _ilk is not None and abs(_ilk[0] + 21.0) < 0.01,
        f"{_ilk}")
_m9._gec(engagement.DOGRULAMA)
_m9.durum_zamani = time.time() - (config.ENGAGE_VERIFY_TIMEOUT + 0.1)
_m9.dogrulama_adimi([])          # avcida hicbir cift yok
kontrol("zaman asiminda TARAMA'ya donuldu", _m9.durum == engagement.TARAMA, _m9.durum)
kontrol("basarisiz aday kara listeye alindi",
        _m9.kara_liste.icinde_mi(-21.0, -0.4))
_ikinci = _m9.tarama_adimi([_iz_a, _iz_b])
kontrol("TARAMA artik SIRADAKI adaya geciyor",
        _ikinci is not None and abs(_ikinci[0] - 12.0) < 0.01, f"{_ikinci}")
kontrol("kara liste KISA omurlu (kalici eleme degil)",
        0 < config.BLACKLIST_VERIFY_TTL_SEC < config.BLACKLIST_TTL_SEC,
        f"{config.BLACKLIST_VERIFY_TTL_SEC} sn")

# --- 10. PITCH REDUKTORU: adim/derece ve darbe hizi tavani ---
print()
print("=" * 70)
print("10. PITCH REDUKTORU (PLF060 1:5) — adim/derece ve darbe tavani")
print("=" * 70)
import motor_fire_module as mfm
kontrol("pitch redüksiyonu 5.0", abs(mfm.GEAR_RATIO_PITCH - 5.0) < 1e-9,
        f"{mfm.GEAR_RATIO_PITCH}")
kontrol("pitch yaw'dan daha ince cozunurluklu",
        mfm.STEPS_PER_DEGREE_PITCH > mfm.STEPS_PER_DEGREE_YAW,
        f"pitch {mfm.STEPS_PER_DEGREE_PITCH:.3f} > yaw {mfm.STEPS_PER_DEGREE_YAW:.3f}")
_tavan = 1.0 / (2 * mfm.MIN_DELAY)
for _ad, _oy, _op in (("saf yaw", 1.0, 0.0), ("saf pitch", 0.0, 1.0),
                      ("capraz", 1.0, 1.0)):
    _hiz = 1.0 / (2 * mfm._servo_gecikme_siniri(_oy, _op))
    kontrol(f"otonom darbe hizi donanim tavanini asmiyor ({_ad})",
            _hiz <= _tavan + 1e-6, f"{_hiz:.0f} <= {_tavan:.0f} darbe/sn")
# 1:5'te SERVO_MAX_DEG_PER_SEC (100) pitch'te donanim tavanina kirpilir.
_pitch_otonom = (1.0 / (2 * mfm._servo_gecikme_siniri(0.0, 1.0))
                 / mfm.STEPS_PER_DEGREE_PITCH)
_yaw_otonom = (1.0 / (2 * mfm._servo_gecikme_siniri(1.0, 0.0))
               / mfm.STEPS_PER_DEGREE_YAW)
print(f"  otonom tepe hiz: yaw {_yaw_otonom:.0f} derece/sn, "
      f"pitch {_pitch_otonom:.0f} derece/sn (kirpilmis)")
kontrol("yaw tam hizina cikabiliyor",
        abs(_yaw_otonom - mfm.SERVO_MAX_DEG_PER_SEC) < 1.0, f"{_yaw_otonom:.0f}")
# Devir teslim butcesi: en kotu pitch yolu ~20 derece, ENGAGE_SLEW_TIMEOUT icinde
# bitmeli. Pitch hizi bunun altina duserse yalpalama zaman asimina ugrar.
kontrol("pitch hizi devir teslim butcesine yetiyor",
        20.0 / _pitch_otonom < config.ENGAGE_SLEW_TIMEOUT * 0.5,
        f"20 derece / {_pitch_otonom:.0f} = {20.0/_pitch_otonom:.2f} sn "
        f"< {config.ENGAGE_SLEW_TIMEOUT*0.5:.2f} sn")
_coz = 1.0 / mfm.STEPS_PER_DEGREE_PITCH
kontrol("pitch cozunurlugu olu bandin altinda",
        _coz / abs(config.HUNTER_DPP_PITCH) < config.PID_DEADBAND_PIXELS,
        f"{_coz:.4f} derece/adim = {_coz/abs(config.HUNTER_DPP_PITCH):.1f} px")

# --- 11. YENI AVCI KAMERA (Arducam B0495C / AR0234 + 12 mm) ---
print()
print("=" * 70)
print("11. YENI AVCI KAMERA (AR0234 + 12 mm) ve MODEL GIRISI UYUMU")
print("=" * 70)
_PIKSEL_UM, _ODAK_MM = 3.0, 12.0


def _ima_odak(dpp, piksel_sayisi):
    """Olculen derece/pikselin ima ettigi odak uzakligi (mm)."""
    fov = piksel_sayisi * dpp
    return (piksel_sayisi * _PIKSEL_UM / 1000.0) / (2 * np.tan(np.radians(fov / 2)))


_fy = _ima_odak(config.HUNTER_DPP_YAW, config.HUNTER_WIDTH)
_fp = _ima_odak(abs(config.HUNTER_DPP_PITCH), config.HUNTER_HEIGHT)
_ETK_G0, _ETK_Y0 = config.hunter_etkin_kare()
print(f"  ima edilen odak: yaw {_fy:.2f} mm, pitch {_fp:.2f} mm "
      f"(takilan lens {_ODAK_MM:.0f} mm)")
# Olculen degeri teorik degere ZORLAMIYORUZ (lens gercekte 11.5-12.5 mm
# olabilir); yalnizca fiziksel olarak makul mu diye bakiyoruz.
kontrol("derece/piksel takilan lensle uyumlu (12 +- 1.5 mm)",
        abs(_fy - _ODAK_MM) < 1.5 and abs(_fp - _ODAK_MM) < 1.5,
        f"yaw {_fy:.2f} mm, pitch {_fp:.2f} mm")
# KARE PIKSEL + REKTILINEER LENS => iki eksende |derece/piksel| AYNI OLMALI.
# Sahada bir kez 1.40 kat fark cikti ve yaw kazanci sessizce %40 hatali
# calisiyordu; bu kontrol onu yakalamak icin var.
#
# KUCUK bir fark KASITLI olabilir: yaw'da dislide mekanik bosluk var ve
# sahada derece/piksel'i biraz yukseltmek telafi olarak kullanildi. Bu YAN
# ETKILI bir cozum -- ayni sabit dunya-acisi defterini, hiz tahminini ve
# gozcu devir teslimi karsilastirmasini da kaydiriyor. Temizi KP_YAW'i
# yukseltmektir. Bu yuzden %10'a kadar tolere ediliyor, otesi hata sayiliyor.
_oran = config.HUNTER_DPP_YAW / abs(config.HUNTER_DPP_PITCH)
print(f"  yaw/pitch olcek orani: {_oran:.4f} "
      f"(1.0 olmali; kucuk sapma bosluk telafisi olabilir)")
kontrol("yaw ve pitch olcegi fiziksel olarak tutarli (fark < %10)",
        abs(_oran - 1.0) < 0.10,
        f"{config.HUNTER_DPP_YAW} vs {abs(config.HUNTER_DPP_PITCH)}")
kontrol("pitch isareti negatif (goruntude asagi = pitch azalir)",
        config.HUNTER_DPP_PITCH < 0)

# --- Kamera karesi ile MODEL GIRISI arasindaki uyum ---
_ETK_G, _ETK_Y = config.hunter_etkin_kare()
_kamera_en = _ETK_G / _ETK_Y
_model_en = config.IMG_WIDTH / config.IMG_HEIGHT
print(f"  kamera {config.HUNTER_WIDTH}x{config.HUNTER_HEIGHT} -> kirpma sonrasi "
      f"{_ETK_G}x{_ETK_Y} (en/boy {_kamera_en:.3f})  ->  model "
      f"{config.IMG_WIDTH}x{config.IMG_HEIGHT} (en/boy {_model_en:.3f})")
kontrol("en/boy bozulmasi ihmal edilebilir (<%5)",
        abs(_kamera_en / _model_en - 1.0) < 0.05,
        f"%{abs(_kamera_en/_model_en - 1)*100:.1f}")
_kucultme = config.HUNTER_WIDTH / config.IMG_WIDTH
print(f"  kucultme carpani: {_kucultme:.2f}x, suzgec {config.MODEL_RESIZE_INTERPOLATION}")
# INTER_LINEAR kucultmede yalnizca birkac komsuyu ornekler; 1.4 katin
# ustunde piksel ATLAR (aliasing + gurultu). O bolgede AREA zorunlu.
kontrol("buyuk kucultmede dogru suzgec kullaniliyor",
        _kucultme <= 1.4 or config.MODEL_RESIZE_INTERPOLATION == "AREA",
        f"{_kucultme:.2f}x -> {config.MODEL_RESIZE_INTERPOLATION}")
kontrol("suzgec adi gecerli",
        config.MODEL_RESIZE_INTERPOLATION in ("AREA", "LINEAR"),
        config.MODEL_RESIZE_INTERPOLATION)

_gs = config.HUNTER_WIDTH * config.HUNTER_DPP_YAW
_gd = _ETK_Y0 * abs(config.HUNTER_DPP_PITCH)
print(f"  gorus acisi: {_gs:.1f} x {_gd:.1f} derece")
kontrol("dikey yari gorus acisi devir tesleme yetiyor (>5 derece)",
        _gd / 2 > 5.0, f"{_gd/2:.1f} derece")

_balon_px = balon_aci / config.HUNTER_DPP_YAW
_balon_model = _balon_px * config.IMG_WIDTH / config.HUNTER_WIDTH
print(f"  15 m'de balon: kaynak {_balon_px:.0f} px -> model uzayinda "
      f"{_balon_model:.0f} px")
kontrol("balon model uzayinda YOLO icin yeterli (>=16 px)", _balon_model >= 16,
        f"{_balon_model:.0f} px")
# Model uzayindaki boyut YALNIZCA gorus acisina bagli olmali; cozunurlugu
# degistirmek hedefi buyutmez. Bu ozdeslik bozulursa bir yerde tutarsizlik var.
_dogrudan = balon_aci / _gs * config.IMG_WIDTH
kontrol("model uzayi boyutu yalnizca gorus acisina bagli",
        abs(_balon_model - _dogrudan) < 0.5,
        f"{_balon_model:.1f} == {_dogrudan:.1f}")
# Tespit gurultusu esikleri KAYNAK COZUNURLUGE bagli; 1280x720'de kaldigimiz
# icin eski (sahada ayarlanmis) degerler aynen gecerli olmali.
# Tespit gurultusu kaynak genisligiyle olcekleniyor (model girisi 1056 sabit).
# Esikler bu orana gore ayarlanmis olmali; 1280'de 5 px, 1920'de 7 px.
_beklenen_olu = round(5.0 * (config.HUNTER_WIDTH / 1280.0))
kontrol("olu bant kaynak cozunurluge gore olceklenmis",
        abs(config.PID_DEADBAND_PIXELS - _beklenen_olu) <= 1.0,
        f"{config.PID_DEADBAND_PIXELS} px (beklenen ~{_beklenen_olu}) = "
        f"{config.PID_DEADBAND_PIXELS*config.HUNTER_DPP_YAW:.3f} derece")
# En sik yapilan hata: cozunurluk degistirilip derece/piksel unutuluyor
# (veya tersi). Ima edilen ODAK UZAKLIGI bu ikisinin BIRLIKTE dogru olmasini
# gerektirir; biri degisip digeri kalirsa odak sacma bir degere firlar.
kontrol("cozunurluk ve derece/piksel BIRLIKTE guncellenmis",
        abs(_ima_odak(config.HUNTER_DPP_YAW, config.HUNTER_WIDTH) - _ODAK_MM) < 1.5,
        f"ima edilen odak {_ima_odak(config.HUNTER_DPP_YAW, config.HUNTER_WIDTH):.2f} mm")

# --- 12. ISTER UYUMU: avci onceligi, dost eleme, asamaya gore ceza ---
print()
print("=" * 70)
print("12. ISTER UYUMU — avci onceligi / dost siralamasi / dost cezasi")
print("=" * 70)


def _cift(sinif='dusman-F16', skor=0.9):
    return engagement.cift_eslestir(
        [det(sinif, 600, 300, 96, 60, skor), det('balon', 633, 415, 30, 30, skor)])


_izl = [{'id': 9, 'yaw': -21.0, 'pitch': -0.4, 'yaw_hiz': 0.0, 'pitch_hiz': 0.0,
         'sinif': 'dusman', 'kirmizi_alan': 9000, 'gorulme': 9}]

# (a) Avci gecerli bir cift goruyorsa gozcuye HIC gidilmemeli
m12 = engagement.AngajmanMakinesi(); m12.basla('task2')
_sec = m12.tarama_adimi(_izl, _cift(), [(2.0, 1.0)])
kontrol("avci hedefi goruyorken aci komutu URETILMIYOR", _sec is None, str(_sec))
kontrol("dogrudan DOGRULAMA'ya gecildi", m12.durum == engagement.DOGRULAMA, m12.durum)
kontrol("hedef acisi ciftin GERCEK acisina ayarlandi",
        abs(m12.hedef_yaw - 2.0) < 1e-6 and abs(m12.hedef_pitch - 1.0) < 1e-6,
        f"{m12.hedef_yaw}, {m12.hedef_pitch}")

# (b) Ayni cift kara listedeyse avci onceligi devreye GIRMEMELI
m12b = engagement.AngajmanMakinesi(); m12b.basla('task2')
m12b.kara_liste.ekle(2.0, 1.0, 5.0, 'dost')
_sec = m12b.tarama_adimi(_izl, _cift(), [(2.0, 1.0)])
kontrol("kara listedeki cifte tekrar angaje OLUNMUYOR",
        m12b.durum == engagement.YONELME, m12b.durum)
kontrol("bunun yerine gozcunun acisina gidiliyor",
        _sec is not None and abs(_sec[0] + 21.0) < 0.01, str(_sec))

# (c) Guveni dusuk veya maketi olmayan cift avci onceligi vermemeli
m12c = engagement.AngajmanMakinesi(); m12c.basla('task2')
m12c.tarama_adimi(_izl, _cift(skor=0.30), [(2.0, 1.0)])
kontrol("dusuk guvenli cift avci onceligi kazanmiyor",
        m12c.durum == engagement.YONELME, m12c.durum)
m12d = engagement.AngajmanMakinesi(); m12d.basla('task2')
m12d.tarama_adimi(_izl, engagement.cift_eslestir(
    [det('balon', 633, 415, 30, 30)], tek_balonlara_izin=True), [(2.0, 1.0)])
kontrol("maketi olmayan cift avci onceligi kazanmiyor",
        m12d.durum == engagement.YONELME, m12d.durum)

# (d) Asama 3: gozcunun 'dost' dedigi iz ELENMEMELI, sona siralanmali
kl12 = engagement.KaraListe()
_karisik = [
    {'id': 1, 'yaw': -10.0, 'pitch': 0.0, 'yaw_hiz': 0.0, 'pitch_hiz': 0.0,
     'sinif': 'dost', 'kirmizi_alan': 20000, 'gorulme': 9},
    {'id': 2, 'yaw': 5.0, 'pitch': 0.0, 'yaw_hiz': 0.0, 'pitch_hiz': 0.0,
     'sinif': 'kararsiz', 'kirmizi_alan': 3000, 'gorulme': 9},
    {'id': 3, 'yaw': 20.0, 'pitch': 0.0, 'yaw_hiz': 0.0, 'pitch_hiz': 0.0,
     'sinif': 'dusman', 'kirmizi_alan': 1000, 'gorulme': 9},
]
_s3 = engagement.aday_sirala(_karisik, kl12, 'task3')
kontrol("asama3: dost artik ELENMIYOR (gozcu yanilirsa hedef kaybolmasin)",
        len(_s3) == 3, f"{len(_s3)} aday")
kontrol("asama3 sirasi: dusman -> kararsiz -> dost",
        [i['sinif'] for i in _s3] == ['dusman', 'kararsiz', 'dost'],
        str([i['sinif'] for i in _s3]))
_s2 = engagement.aday_sirala(_karisik, kl12, 'task2')
kontrol("asama2: sinif ayrimi yok, en buyuk kirmizi once",
        _s2[0]['kirmizi_alan'] == 20000, str(_s2[0]['kirmizi_alan']))

# (e) DOST cezasi asamaya gore: asama 2'de kisa, asama 3'te kalici
def _dost_cezasi(asama):
    mm = engagement.AngajmanMakinesi(); mm.basla(asama)
    h = mm.tarama_adimi(_izl)
    mm.yonelme_adimi(h[0], h[1])
    for _ in range(config.VERIFY_CONFIRM_FRAMES):
        mm.dogrulama_adimi(_cift('dost-F16'))
    return mm._dost_ttl(), mm.kara_liste.icinde_mi(h[0], h[1])

_ttl2, _var2 = _dost_cezasi('task2')
_ttl3, _var3 = _dost_cezasi('task3')
kontrol("asama3'te dost cezasi pratikte kalici", _ttl3 >= 600.0, f"{_ttl3} sn")
kontrol("asama2'de dost cezasi KISA (ortamda dost yok, bu bir YOLO hatasi)",
        _ttl2 <= config.BLACKLIST_VERIFY_TTL_SEC, f"{_ttl2} sn")
kontrol("her iki asamada da kara listeye giriliyor", _var2 and _var3)

# --- 13. CAPRAZ ESLESME ve KILIT KOPRUSU ---
print()
print("=" * 70)
print("13. CAPRAZ ESLESME KORUMASI ve KILIT KOPRUSU")
print("=" * 70)

# (a) Dusmanin maketi + DOSTUN balonu: ESLESMEMELI.
# Dusmanin kendi balonu o karede tespit edilmemis; dostun balonu yatayda yakin.
_capraz = [det('dusman-F16', 600, 300, 126, 80),
           det('dost-Helikopter', 760, 300, 100, 70),
           det('balon', 790, 430, 40, 40)]          # DOSTUN balonu
_c13 = engagement.cift_eslestir(_capraz)
_dusman = next(c for c in _c13 if engagement.dusman_mi(c.sinif))
_dost = next(c for c in _c13 if engagement.dost_mu(c.sinif))
kontrol("dusman maketi DOSTUN balonunu kapamiyor", _dusman.balon is None)
kontrol("balon dogru sahibiyle (dost) eslesti", _dost.balon is not None)
# Ates kilidi acisindan sonuc: dusman ciftinin balonu yok -> ates serbest degil
_m13 = engagement.AngajmanMakinesi(); _m13.basla('task3')
_m13.durum = engagement.ATES; _m13.dogrulanan_sinif = 'dusman-F16'
_izn, _ger = engagement.ates_serbest_mi(_dusman, _m13, True, True, 0.0, 0.0, 0.0)
kontrol("dostun balonuna ates ENGELLENDI", not _izn, _ger)

# (b) Ayni sahnede dusmanin KENDI balonu varsa dogru eslesmeli
_normal = _capraz + [det('balon', 640, 430, 40, 40)]
_c13b = engagement.cift_eslestir(_normal)
_d2 = next(c for c in _c13b if engagement.dusman_mi(c.sinif))
kontrol("kendi balonu varken dusman dogru esleiyor", _d2.balon is not None)
kontrol("balon gercekten dusmanin altindaki",
        abs((_d2.balon['bbox'][0] + 20) - 660) < 5, str(_d2.balon['bbox']))

# (c) KILIT koprusu: maket bir kare gorunmezse balon tek basina takip edilir
_m14 = engagement.AngajmanMakinesi(); _m14.basla('task2')
_m14.durum = engagement.KILIT
_m14.dogrulanan_sinif = 'dusman-F16'
_tam = engagement.cift_eslestir([det('dusman-F16', 600, 300, 126, 80),
                                 det('balon', 640, 430, 40, 40)])
_sec, _kopru = _m14.kilit_hedefi_sec(_tam, [(5.0, 1.0)])
kontrol("maket varken normal takip", _sec is not None and not _kopru)
kontrol("kilit acisi kaydedildi", _m14.kilit_aci == (5.0, 1.0))

_yalniz = engagement.cift_eslestir([det('balon', 640, 430, 40, 40)],
                                   tek_balonlara_izin=True)
_sec, _kopru = _m14.kilit_hedefi_sec(_yalniz, [(5.1, 1.0)])
kontrol("maket kaybolunca balon KOPRU ile takip ediliyor",
        _sec is not None and _kopru, f"kopru={_kopru}")
kontrol("durum hala KILIT", _m14.durum == engagement.KILIT, _m14.durum)

# (d) Kopru YANDAKI hedefe atlamamali
_m15 = engagement.AngajmanMakinesi(); _m15.basla('task2')
_m15.durum = engagement.KILIT; _m15.dogrulanan_sinif = 'dusman-F16'
_m15.kilit_aci = (5.0, 1.0)
_sec, _kopru = _m15.kilit_hedefi_sec(_yalniz, [(5.0 + 3 * config.LOCK_BRIDGE_MAX_DEG, 1.0)])
kontrol("uzaktaki balona KOPRU KURULMUYOR", _sec is None, f"{_sec}")

# (e) Kopru butcesi dolunca kilit birakilir
_m16 = engagement.AngajmanMakinesi(); _m16.basla('task2')
_m16.durum = engagement.KILIT; _m16.dogrulanan_sinif = 'dusman-F16'
_m16.kilit_aci = (5.0, 1.0)
for _ in range(config.LOCK_BRIDGE_MAX_FRAMES + 1):
    _m16.kilit_hedefi_sec(_yalniz, [(5.0, 1.0)])
kontrol("kopru butcesi dolunca TARAMA'ya donuluyor",
        _m16.durum == engagement.TARAMA, _m16.durum)

# (f) EMNIYET AGI: kilit acisinda BASKA SINIFTAN maket belirirse kilit dusmeli
_m17 = engagement.AngajmanMakinesi(); _m17.basla('task3')
_m17.durum = engagement.KILIT; _m17.dogrulanan_sinif = 'dusman-F16'
_m17.kilit_aci = (5.0, 1.0)
_dost_cift = engagement.cift_eslestir([det('dost-Helikopter', 600, 300, 126, 80),
                                       det('balon', 640, 430, 40, 40)])
# TEK KARE kilidi DUSURMEMELI: sahada 0.1-0.2 saniye suren sahte etiketler
# goruldu (guven 0.6'ya kadar). Zamansal onay olmadan bir hayalet iyi bir
# kilidi TARAMA'ya gonderiyordu.
_m17.kilit_hedefi_sec(_dost_cift, [(5.0, 1.0)])
kontrol("TEK karelik yabanci maket kilidi DUSURMUYOR",
        _m17.durum == engagement.KILIT, _m17.durum)
# Ama israrla goruluyorsa kilit birakilmali
for _ in range(config.LOCK_ABORT_CONFIRM_FRAMES - 1):
    _sec, _ = _m17.kilit_hedefi_sec(_dost_cift, [(5.0, 1.0)])
kontrol("kilit acisinda DOST ISRARLA gorulunce kilit birakildi",
        _sec is None and _m17.durum == engagement.TARAMA, _m17.durum)
# Arada dogru sinif gorulurse sayac SIFIRLANMALI
_m19 = engagement.AngajmanMakinesi(); _m19.basla('task3')
_m19.durum = engagement.KILIT; _m19.dogrulanan_sinif = 'dusman-F16'
_m19.kilit_aci = (5.0, 1.0)
_dusman_cift19 = engagement.cift_eslestir(
    [det('dusman-F16', 600, 300, 126, 80), det('balon', 640, 430, 40, 40)])
for _ in range(config.LOCK_ABORT_CONFIRM_FRAMES + 2):
    _m19.kilit_hedefi_sec(_dost_cift, [(5.0, 1.0)])       # yabanci
    _m19.kilit_hedefi_sec(_dusman_cift19, [(5.0, 1.0)])   # dogru sinif
kontrol("arada dogru sinif gorulurse iptal sayaci sifirlaniyor",
        _m19.durum == engagement.KILIT, _m19.durum)

# (g) R2: dogrulanan sinif tutmayan ciftte RASTGELE hedefe dusulmuyor
_m18 = engagement.AngajmanMakinesi(); _m18.basla('task3')
_m18.durum = engagement.KILIT; _m18.dogrulanan_sinif = 'dusman-Drone'
_sec, _ = _m18.kilit_hedefi_sec(_dost_cift, [(40.0, 9.0)])   # cok uzakta
kontrol("sinif tutmayan cifte SESSIZCE dusulmuyor", _sec is None, f"{_sec}")

print()
print("=" * 70)
print("14. NISAN SUREKLILIGI, IMHA DOGRULAMA, BOYUT KAPISI")
print("=" * 70)

# (a) Kaynak degisiminde pitch sicramasi -- salinimin kok nedeni.
# Saha geometrisi (asama2-3-hedefTakip.mp4): maket 162x208, balon 78x74.
_mk = det('dusman-F16', 800, 300, 162, 208)
_bl = det('balon', 842, 533, 78, 74)
_c_tam = engagement.cift_eslestir([_mk, _bl])[0]
_ofs = _c_tam.olculen_ofset()
_n_tam = _c_tam.nisan_noktasi()
kontrol("balon varken olculen ofset uretiliyor",
        _ofs is not None and abs(_ofs[0]) < 0.01,
        f"dx/mw={_ofs[0]:.3f} dy/mw={_ofs[1]:.3f}")

_c_yok = engagement.cift_eslestir([_mk])[0]
_n_sabit = _c_yok.nisan_noktasi()                        # eski sabit formul
_n_ogrn = _c_yok.nisan_noktasi(ogrenilen_ofset=_ofs)     # ogrenilmis
_sicrama_sabit = abs(_n_sabit[1] - _n_tam[1])
_sicrama_ogrn = abs(_n_ogrn[1] - _n_tam[1])
kontrol("sabit formul GERCEKTEN sicrama uretiyor (regresyon tanigi)",
        _sicrama_sabit > 20.0, f"{_sicrama_sabit:.1f} px")
kontrol("ogrenilen ofset sicramayi SIFIRLIYOR",
        _sicrama_ogrn < 0.5, f"{_sicrama_ogrn:.2f} px (sabit formul {_sicrama_sabit:.1f})")
kontrol("ogrenilen yolda balon 'gercek gorundu' SAYILMIYOR",
        _n_ogrn[3] is False, f"{_n_ogrn[3]}")

# (b) Hedef Takip: balon yoksa maketin TAM ORTASI (tahmin yok)
_n_mrk = _c_yok.nisan_noktasi(maket_merkezine=True)
kontrol("takip modu maketin tam ortasina nisan aliyor",
        abs(_n_mrk[0] - (800 + 81)) < 0.5 and abs(_n_mrk[1] - (300 + 104)) < 0.5,
        f"({_n_mrk[0]:.0f}, {_n_mrk[1]:.0f}) beklenen (881, 404)")

# (c) Imha dogrulama penceresi
# Pencere artik GECIKMELI: once FIRE_CONFIRM_DELAY_SEC (patlama suresi)
# bekleniyor, balon ancak ondan SONRA sayilmaya basliyor.
_PENCERE = config.FIRE_CONFIRM_DELAY_SEC + config.FIRE_CONFIRM_SEC


def _ates_edip_bekle(balon_var, kare=8):
    m = engagement.AngajmanMakinesi(); m.basla('task2')
    m._gec(engagement.ATES); m.ates_kaydet()
    ilk = m.ates_dogrulama_adimi(balon_var)
    # Sayim penceresinin ICINE gir (gecikme gecti, sure dolmadi) ki
    # balon gorulme sayaci gercekten islesin.
    t0 = m.son_ates_zamani
    for i in range(kare):
        m.son_ates_zamani = t0 - (config.FIRE_CONFIRM_DELAY_SEC + 0.01
                                  + i * 0.01)
        m.ates_dogrulama_adimi(balon_var)
    m.son_ates_zamani = t0 - _PENCERE - 0.01
    son = m.ates_dogrulama_adimi(balon_var)
    return ilk, son, m

_ilk, _son, _ = _ates_edip_bekle(False)
kontrol("ates ANINDA imha sayilmiyor (pencere aciliyor)", _ilk == 'bekle', _ilk)
kontrol("balon kaybolunca imha ONAYLANIYOR", _son == 'onaylandi', _son)

_ilk, _son, _ = _ates_edip_bekle(True)
kontrol("balon duruyorsa TEKRAR ates isteniyor", _son == 'tekrar', _son)

# Butce dolunca pes edilmeli (sonsuz ates dongusu olmasin)
_m20 = engagement.AngajmanMakinesi(); _m20.basla('task2')
_m20._gec(engagement.ATES)
for _ in range(config.FIRE_MAX_ATTEMPTS):
    _m20.ates_kaydet()
    _t20 = _m20.son_ates_zamani
    # Once sayim penceresinde balonu gordur, sonra pencereyi doldur
    for _i in range(6):
        _m20.son_ates_zamani = _t20 - (config.FIRE_CONFIRM_DELAY_SEC + 0.01 + _i * 0.01)
        _m20.ates_dogrulama_adimi(True)
    _m20.son_ates_zamani = _t20 - _PENCERE - 0.01
    _sonuc20 = _m20.ates_dogrulama_adimi(True)
kontrol("atis butcesi dolunca 'pes' ediliyor", _sonuc20 == 'pes',
        f"{_sonuc20} ({_m20.ates_sayisi} atis)")

# Tek karelik kacirma "imha" sanilmamali
_m21 = engagement.AngajmanMakinesi(); _m21.basla('task2')
_m21._gec(engagement.ATES); _m21.ates_kaydet()
_t21 = _m21.son_ates_zamani
# Sayim penceresinin icinde: balon cogunlukla goruluyor (MAX_SEEN'i asacak)
for _i, _g in enumerate((True, False, True, True, False, True, True, True)):
    _m21.son_ates_zamani = _t21 - (config.FIRE_CONFIRM_DELAY_SEC + 0.01 + _i * 0.01)
    _m21.ates_dogrulama_adimi(_g)
_m21.son_ates_zamani = _t21 - _PENCERE - 0.01
kontrol("pencerede balon ISRARLA gorulduyse imha SAYILMIYOR",
        _m21.ates_dogrulama_adimi(True) == 'tekrar',
        f"{_m21._ates_balon_gorulme} kare goruldu, esik {config.FIRE_CONFIRM_MAX_SEEN}")

# TARAMA'ya donunce atis butcesi ve ofset sifirlanmali
_m22 = engagement.AngajmanMakinesi(); _m22.basla('task2')
_m22._gec(engagement.ATES); _m22.ates_kaydet()
_m22.nisan_ofseti = (0.0, 1.0, 0.2)
_m22._gec(engagement.TARAMA)
kontrol("yeni hedefe gecince atis butcesi sifirlaniyor",
        _m22.ates_sayisi == 0 and _m22.nisan_ofseti is None,
        f"ates={_m22.ates_sayisi} ofset={_m22.nisan_ofseti}")

# (d) Sinif bazli boyut kapisi: olculen gercek/sahte kutular
import inference_module as _im
for _ad, _sinif, _px, _bekle in (
        ("gercek maket", 'dusman-F16', 172, True),
        ("gercek balon", 'balon', 78, True),
        ("gercek balon 7.5 m", 'balon', 100, True),
        ("sahte fuze (olculdu)", 'dusman-fuze', 693, False),
        ("sahte kutu 2", 'dusman-F16', 487, False),
        ("sahte kutu 3", 'dusman-F16', 445, False)):
    kontrol(f"boyut kapisi: {_ad} {_px} px -> {'gecmeli' if _bekle else 'elenmeli'}",
            _im._acisal_boyut_makul_mu((0, 0, _px, _px), _sinif) is _bekle)

print()
print("=" * 70)
print("15. GOZCU GOSTERIM BLOKLARI (yalnizca cizim, yonlendirmeye etkisiz)")
print("=" * 70)

_g = np.zeros((720, 1280, 3), np.uint8); _g[:] = (35, 35, 35)


def _ucak(x, y, renk):
    cv2.rectangle(_g, (x - 8, y - 40), (x + 8, y + 40), renk, -1)
    cv2.rectangle(_g, (x - 35, y - 6), (x + 35, y + 6), renk, -1)


_KRM, _MAV = (40, 40, 220), (220, 120, 40)
_ucak(320, 300, _KRM)                          # balonsuz kirmizi maket
_ucak(450, 300, _MAV)                          # dost mavi maket
cv2.circle(_g, (450, 358), 11, _KRM, -1)       # dostun balonu
_ucak(750, 285, _KRM)                          # dusman maket
cv2.circle(_g, (750, 343), 11, _KRM, -1)       # dusmanin balonu

_hsv = cv2.cvtColor(_g, cv2.COLOR_BGR2HSV)
_krm = sp._temizle(sp._maske(_hsv, config.SPOTTER_RED_RANGES))
_mav = sp._temizle(sp._maske(_hsv, config.SPOTTER_BLUE_RANGES))

_adaylar = sp.balon_adaylari(_krm)
_bloklar = sp.gosterim_bloklari(_krm, _mav)
_blok_aday = [b for b in _bloklar if b['aday']]
_blok_elenen = [b for b in _bloklar if b['renk'] == 'kirmizi' and not b['aday']]
_blok_mavi = [b for b in _bloklar if b['renk'] == 'mavi']

kontrol("gosterim aday sayisi GERCEK aday sayisiyla ayni",
        len(_blok_aday) == len(_adaylar), f"{len(_blok_aday)} vs {len(_adaylar)}")
kontrol("elenen kirmizi maketler cizim listesinde var",
        len(_blok_elenen) >= 2, f"{len(_blok_elenen)} adet")
kontrol("mavi blob cizim listesinde var (dost gorunur olsun)",
        len(_blok_mavi) >= 1, f"{len(_blok_mavi)} adet")
kontrol("mavi blob ASLA aday degil",
        all(not b['aday'] for b in _blok_mavi))
kontrol("maket elenme sebebi DOLGUNLUK olarak raporlaniyor",
        any('dolgunluk' in b['ret'] for b in _blok_elenen),
        ", ".join(sorted({b['ret'] for b in _blok_elenen})))

# Cizim etiketi ile gercek karar ASLA ayrismamali (tek kapi: balon_kapisi)
_uyum = True
for _b in _bloklar:
    if _b['renk'] != 'kirmizi':
        continue
    _gercek = any(abs(a['cx'] - (_b['x'] + _b['w'] / 2.0)) < 3 and
                  abs(a['cy'] - (_b['y'] + _b['h'] / 2.0)) < 3 for a in _adaylar)
    if _gercek != _b['aday']:
        _uyum = False
kontrol("cizimin 'aday' etiketi gercek kararla birebir uyuyor", _uyum)

# YONLENDIRME DEGISMEDI: izler hala yalnizca balon adaylarindan uretiliyor
_yon = sp.IzYoneticisi()
_izler, _, _ = sp.kareyi_coz(_g, _yon, 1000.0)
kontrol("iz sayisi = balon aday sayisi (maketler iz acmiyor)",
        len(_izler) == len(_adaylar), f"{len(_izler)} iz / {len(_adaylar)} aday")
kontrol("dost balonu 'dost', dusman balonu 'dusman' siniflandi",
        sorted(i.sinif for i in _izler) == ['dost', 'dusman'],
        ", ".join(sorted(i.sinif for i in _izler)))

print()
print("=" * 70)
print("16. IMHA DOGRULAMA KILIDI ve REZONANS SUZGECI")
print("=" * 70)

# (a) SAHA SENARYOSU: ates 7.60 sn, balon 8.10'da kayboldu (0.5 sn sonra).
# Gecikmeli sayim olmadan bu 15 kare "balon hala orada" sayiliyordu.
_m23 = engagement.AngajmanMakinesi(); _m23.basla('task3')
_m23._gec(engagement.ATES); _m23.ates_kaydet()
_t23 = _m23.son_ates_zamani
_sonuc23 = None
for _k in range(80):
    _gecen = _k / 30.0
    _m23.son_ates_zamani = _t23 - _gecen
    _sonuc23 = _m23.ates_dogrulama_adimi(_gecen < 0.50)   # balon 0.5 sn daha gorunur
    if _sonuc23 != 'bekle':
        break
kontrol("patlamis balon 0.5 sn daha gorunse de IMHA ONAYLANIYOR",
        _sonuc23 == 'onaylandi',
        f"{_sonuc23}, pencerede sayilan {_m23._ates_balon_gorulme} kare")

# Balon gercekten duruyorsa hala 'tekrar' demeli (koruma kaybolmamali)
_m24 = engagement.AngajmanMakinesi(); _m24.basla('task3')
_m24._gec(engagement.ATES); _m24.ates_kaydet()
_t24 = _m24.son_ates_zamani
for _k in range(80):
    _m24.son_ates_zamani = _t24 - _k / 30.0
    _s24 = _m24.ates_dogrulama_adimi(True)
    if _s24 != 'bekle':
        break
kontrol("balon GERCEKTEN duruyorsa hala 'tekrar'", _s24 == 'tekrar', _s24)

# (b) KILITLENME CIKISI -- 18. bolumdeki 20 saniyelik takilmanin caresi
_m25 = engagement.AngajmanMakinesi(); _m25.basla('task3')
_m25.dogrulanan_sinif = 'dusman-Fuze'; _m25._gec(engagement.ATES)
_m25.ates_kaydet()
_birak = None
for _k in range(1, 300):
    if _m25.ates_engellendi():
        _birak = _k
        break
kontrol("ates ardisik engellenince hedef BIRAKILIYOR",
        _birak == config.FIRE_RETRY_GIVEUP_FRAMES,
        f"{_birak} kare (esik {config.FIRE_RETRY_GIVEUP_FRAMES})")
_m25.imha_edilemedi()
kontrol("birakildiktan sonra TARAMA'ya donuluyor",
        _m25.durum == engagement.TARAMA, _m25.durum)

# Basarili ates engel sayacini sifirlamali
_m25.basla('task3'); _m25._gec(engagement.ATES)
_m25.ates_engellendi(); _m25.ates_engellendi()
_m25.ates_kaydet()
kontrol("basarili ates engel sayacini sifirliyor",
        _m25.ates_engel_ardisik == 0, f"{_m25.ates_engel_ardisik}")

# TARAMA'ya gecince de sifirlanmali
_m26 = engagement.AngajmanMakinesi(); _m26.basla('task2')
_m26._gec(engagement.ATES); _m26.ates_kaydet(); _m26.ates_engellendi()
_m26._gec(engagement.TARAMA)
kontrol("TARAMA'ya gecince ates/engel sayaclari sifirlaniyor",
        _m26.ates_sayisi == 0 and _m26.ates_engel_ardisik == 0,
        f"ates={_m26.ates_sayisi} engel={_m26.ates_engel_ardisik}")

# (c) REZONANS SUZGECI frekans tepkisi
import math as _math
_a = config.PID_OUTPUT_SMOOTHING
kontrol("PID cikis suzgeci ETKIN (0 ise sonumleme yok)", _a > 0.0, f"{_a}")
if _a > 0:
    _fc = -_math.log(1 - _a) * 30.0 / (2 * _math.pi)
    _kaz = lambda f: 1.0 / _math.sqrt(1 + (f / _fc) ** 2)
    kontrol("kesim frekansi olculen salinim bandinin (2.2-3.2 Hz) ALTINDA",
            _fc < 2.2, f"fc={_fc:.2f} Hz")
    kontrol("yavas yonelme (0.5 Hz) neredeyse hic bastirilmiyor",
            _kaz(0.5) > 0.90, f"kazanc {_kaz(0.5):.2f}")
    kontrol("rezonans bandi (2.7 Hz) belirgin bastiriliyor",
            _kaz(2.7) < 0.65, f"kazanc {_kaz(2.7):.2f}")

print()
print("=" * 70)
print("17. DOGRULAMADA BALON SARTI ve DAR KARA LISTE")
print("=" * 70)

# (a) SAHA SENARYOSU (analizaşama3.mp4): balonsuz dusman-F16'ya kilitlenildi
# ve 42 saniye cikilamadi. Dogrulama artik balonu sart kosuyor.
_balonsuz = engagement.cift_eslestir([det('dusman-F16', 800, 300, 130, 150)])
_balonlu = engagement.cift_eslestir(
    [det('dusman-F16', 800, 300, 130, 150), det('balon', 845, 470, 45, 45)])
_m27 = engagement.AngajmanMakinesi(); _m27.basla('task3')
_m27.hedef_yaw, _m27.hedef_pitch = -0.17, 0.0     # sahada olculen aci
_m27._gec(engagement.DOGRULAMA)
_s27 = None
# Balona SURE TANINIYOR (VERIFY_NO_BALLOON_GIVEUP_SEC): sinif tutarliligi
# 4 karede saglansa da balon gec gorulebilecegi icin hemen elenmiyor.
# Sanal zamani ilerleterek o esigi asiyoruz.
_t27 = _m27.durum_zamani
for _k in range(int(config.VERIFY_NO_BALLOON_GIVEUP_SEC * 30) + 4):
    _m27.durum_zamani = _t27 - _k / 30.0
    _s27 = _m27.dogrulama_adimi(_balonsuz)
    if _m27.durum != engagement.DOGRULAMA:
        break
kontrol("balonsuz hedef ~%.2f sn icinde birakiliyor" % config.VERIFY_NO_BALLOON_GIVEUP_SEC,
        _k / 30.0 <= config.VERIFY_NO_BALLOON_GIVEUP_SEC + 0.10,
        f"{_k} kare = {_k/30.0:.2f} sn")

# Balon GEC gorulurse (esigin icinde) hedef KACIRILMAMALI
_m27b = engagement.AngajmanMakinesi(); _m27b.basla('task3')
_m27b.hedef_yaw, _m27b.hedef_pitch = 0.0, 0.0
_m27b._gec(engagement.DOGRULAMA)
_t27b = _m27b.durum_zamani
_gec_esik = int(config.VERIFY_NO_BALLOON_GIVEUP_SEC * 30) - 3
for _k in range(60):
    _m27b.durum_zamani = _t27b - _k / 30.0
    _m27b.dogrulama_adimi(_balonlu if _k >= _gec_esik else _balonsuz)
    if _m27b.durum != engagement.DOGRULAMA:
        break
kontrol("balon GEC gorulurse hedef kacirilmiyor",
        _m27b.durum == engagement.KILIT,
        f"{_m27b.durum} (balon {_gec_esik/30.0:.2f} sn'de goruldu)")
kontrol("balonsuz hedef KILIT'e ALINMIYOR",
        _m27.durum == engagement.TARAMA, _m27.durum)
kontrol("balonsuz hedef kara listeye giriyor",
        _m27.kara_liste.icinde_mi(-0.17, 0.0))

# KOMSU HEDEF ETKILENMEMELI -- "bir daha gitmeme" riskinin testi
kontrol("olculen komsu hedef (+6.23 der) SERBEST kaliyor",
        not _m27.kara_liste.icinde_mi(6.23, 0.0))
kontrol("1 metre yanal ayrim (16 m -> 3.58 der) SERBEST kaliyor",
        not _m27.kara_liste.icinde_mi(-0.17 + 3.58, 0.0),
        f"dar yaricap {config.BLACKLIST_NO_BALLOON_RADIUS_DEG} derece")
# Eski genis yaricapla komsu KAPANIRDI -- regresyon tanigi
kontrol("genis yaricap (4.0) 3.58 dereceyi kapatirdi (sorunun kaniti)",
        3.58 <= config.BLACKLIST_RADIUS_DEG)

# (b) BALONLU hedef hala dogrulanmali
_m28 = engagement.AngajmanMakinesi(); _m28.basla('task3')
_m28.hedef_yaw, _m28.hedef_pitch = 6.23, 0.0
_m28._gec(engagement.DOGRULAMA)
for _k in range(config.VERIFY_CONFIRM_FRAMES + 1):
    _s28 = _m28.dogrulama_adimi(_balonlu)
kontrol("balonlu hedef KILIT'e aliniyor", _m28.durum == engagement.KILIT, _m28.durum)

# Balon ARA SIRA gorulse de yeter (anlik kayip cezalandirilmamali)
_m29 = engagement.AngajmanMakinesi(); _m29.basla('task3')
_m29.hedef_yaw, _m29.hedef_pitch = 0.0, 0.0
_m29._gec(engagement.DOGRULAMA)
for _k in range(config.VERIFY_CONFIRM_FRAMES + 1):
    _m29.dogrulama_adimi(_balonlu if _k == 1 else _balonsuz)
kontrol("balon 4 karede SADECE 1 kez gorulse de kilitleniyor",
        _m29.durum == engagement.KILIT,
        f"{_m29.durum} (esik {config.VERIFY_MIN_BALLOON_FRAMES} kare)")

# (c) KILIT zaman asimi da kara listeye almali (emniyet agi)
_m30 = engagement.AngajmanMakinesi(); _m30.basla('task3')
_m30.hedef_yaw, _m30.hedef_pitch = 10.0, 0.0
_m30.dogrulanan_sinif = 'dusman-F16'
_m30._gec(engagement.KILIT)
_m30.durum_zamani -= config.ENGAGE_LOCK_TIMEOUT + 0.1
_m30.kilit_adimi(50.0, 20.0, False)
kontrol("kilit zaman asiminda TARAMA'ya donuluyor",
        _m30.durum == engagement.TARAMA, _m30.durum)
kontrol("kilit zaman asiminda KARA LISTEYE de aliniyor",
        _m30.kara_liste.icinde_mi(10.0, 0.0),
        "eskiden alinmiyordu -> ayni hedefe aninda geri donuluyordu")
kontrol("kilit zaman asimi komsuyu kapatmiyor",
        not _m30.kara_liste.icinde_mi(10.0 + 3.58, 0.0))

# (d) Gozcu esikleri: SAHADA OLCULEN balon gecmeli
kontrol("gozcu: olculen balon (alan 34) artik gecer",
        config.SPOTTER_MIN_BLOB_AREA <= 34,
        f"esik {config.SPOTTER_MIN_BLOB_AREA}")
kontrol("gozcu: olculen balon dolgunlugu (0.50) artik gecer",
        config.SPOTTER_BALLOON_MIN_FILL <= 0.50,
        f"esik {config.SPOTTER_BALLOON_MIN_FILL}")
kontrol("gozcu kapisi 34 px / 0.53 dolgunluk balonu GECIRIYOR",
        sp.balon_kapisi(34, 8, 8) is None)

print()
print("=" * 70)
print(f"SONUC: {'TUM TESTLER GECTI' if hata == 0 else str(hata) + ' TEST BASARISIZ'}")
print("=" * 70)
sys.exit(1 if hata else 0)
