# -*- coding: utf-8 -*-
"""
Servo tetik kalibrasyon ve TESHIS araci — RASPBERRY PI UZERINDE calisir.

    python3 servo_tani.py

IKI SERVO TIPI VAR ve tetik icin tamamen farkli kullanilirlar:

  STANDART (180 derece)  : darbe genisligi = KONUM
        1500 us = merkez, 1833 us = +30 derece. Yaz, oraya gider, BEKLER.
        Tetik icin ideal: "cek" ve "birak" iki sabit sayidir.

  SUREKLI DONUS (360)    : darbe genisligi = HIZ ve YON
        1500 us = DUR. 1700 us = bir yone donmeye baslar ve DURMAZ.
        Konum kavrami yok (potansiyometresi sokulmus). Tetik icin
        "su hizda su kadar SURE don" demek gerekir -- acik dongu.

Elinizdeki MG995 her iki surumde de satiliyor; etiketten anlasilmiyor.
Once 'x' TESHISI ile hangisi oldugunu belirleyin.

KOMUTLAR
    x       : TESHIS -- servo tipini belirler (once bunu calistirin)
    m       : mod degistir (konum <-> hiz)
    ? / h   : komutlari tekrar yazdir

  KONUM MODU (standart servo)
    a / d   : -10 / +10 us      z / c : -50 / +50 us      s / w : -2 / +2 us
    r       : bu degeri DINLENME olarak kaydet
    p       : bu degeri CEKILI olarak kaydet
    t       : kayitli iki deger arasinda git-gel provasi

  HIZ MODU (surekli donus servosu)
    f       : ILERI don (FIRE_SERVO_CW_US)        <- basili tutmak gerekmez
    b       : GERI don  (FIRE_SERVO_CCW_US)
    space   : DUR (notr)
    + / -   : hizi artir / azalt (notrdan uzaklik)
    1 / 2   : hareket suresini -0.05 / +0.05 sn
    t       : ileri(sure) -> dur -> geri(sure) -> dur provasi

    0       : darbeyi kes (servo gevser)
    q       : cik

GUVENLIK: kalibrasyon SILAH TAKILI DEGILKEN yapilmali. 500-2500 us disina
izin verilmiyor. Surekli donus servosunda mekanik sinira dayanmak servoyu
zorlar -- prova sirasinde ses/isinma olursa sureyi kisaltin.
"""
import sys
import time

try:
    import lgpio
except ImportError:
    print("HATA: lgpio yok. Bu arac Raspberry Pi uzerinde calisir:")
    print("  sudo apt install python3-lgpio")
    sys.exit(1)

SERVO_PIN = 12
FREQ = 50
ALT, UST = 500, 2500
NOTR = 1500

# --- gpiochip bul (motor_fire_module._find_gpiochip ile ayni mantik) ---
# gpio_get_chip_info -> [status, lines, name, label];  LABEL = info[3]
_LABELS = ('pinctrl-rp1', 'pinctrl-bcm2712', 'pinctrl-bcm2711', 'pinctrl-bcm2835')
h = None
_yedek = None
for n in range(32):
    try:
        aday = lgpio.gpiochip_open(n)
    except Exception:
        continue
    try:
        bilgi = lgpio.gpio_get_chip_info(aday)
        hat = int(bilgi[1])
        etiket = str(bilgi[3])
        print("  gpiochip%-2d  %-24s %d hat" % (n, etiket, hat))
        if etiket in _LABELS:
            h = aday
            print("gpiochip%d secildi (%s)" % (n, etiket))
            break
        if hat >= 40 and _yedek is None:
            _yedek = (n, aday, etiket)
            continue
    except Exception as e:
        print("  gpiochip%d bilgisi okunamadi: %s" % (n, e))
    lgpio.gpiochip_close(aday)

if h is None and _yedek is not None:
    n, h, etiket = _yedek
    print("UYARI: bilinen etiket yok, 40+ hatli gpiochip%d kullanilacak (%s)"
          % (n, etiket))
elif h is not None and _yedek is not None:
    lgpio.gpiochip_close(_yedek[1])

if h is None:
    print("HATA: 40 pinli basliga ait gpiochip bulunamadi (gpiodetect ile bakin).")
    sys.exit(1)

lgpio.gpio_claim_output(h, SERVO_PIN, 0)


def darbe(us):
    """us = 0 ise darbeyi kes (servo gevser)."""
    lgpio.tx_servo(h, SERVO_PIN, int(us), FREQ, 0, 0)


def yardim():
    print("""
  x      TESHIS (servo tipini belirle)      m  mod degistir      ?  bu liste
  KONUM: a/d -+10   z/c -+50   s/w -+2   r dinlenme   p cekili   t prova
  HIZ  : f ileri    b geri     space dur  +/- hiz     1/2 sure   t prova
  0      darbeyi kes            q  cik
""")


def teshis():
    """
    Servo tipini belirler.

    YONTEM: notr (1500) ver, sonra notrdan belirgin uzak bir deger ver ve
    BEKLE. Standart servo o konuma gidip DURUR (ses kesilir). Surekli donus
    servosu DURMADAN doner (kol surekli doner, ses devam eder).
    """
    print()
    print("=" * 62)
    print("TESHIS -- servoyu IZLEYIN ve sorulara cevap verin")
    print("=" * 62)
    print("Kola isaret koyun (bant/kalem) ki donus gorulebilsin.")
    input("Hazir olunca Enter...")

    print("\n1) Notr (1500 us) veriliyor, 2 saniye...")
    darbe(NOTR)
    time.sleep(2.0)

    print("2) 1800 us veriliyor, 3 SANIYE BOYUNCA IZLEYIN...")
    darbe(1800)
    time.sleep(3.0)
    print("   -> notr'a donuluyor")
    darbe(NOTR)
    time.sleep(1.0)

    print()
    c = input("Kol 3 saniye boyunca DURMADAN mi dondu, yoksa bir yere gidip\n"
              "DURDU mu?  [d = durmadan dondu / s = gidip durdu] > ").strip().lower()
    print()
    if c.startswith('d'):
        print("=> SUREKLI DONUS (360) SERVOSU.")
        print("   Konum kontrolu YAPILAMAZ. Tetik icin sure bazli hiz komutu")
        print("   gerekiyor: 'm' ile HIZ moduna gecin.")
        print()
        print("   NOT: bu tip tetik icin ideal degil. Mumkunse STANDART (180)")
        print("   servo kullanin -- cek/birak iki sabit sayi olur ve tekrar")
        print("   edilebilirligi cok daha iyidir.")
        return 'hiz'
    elif c.startswith('s'):
        print("=> STANDART (180) SERVO. Konum modu dogru.")
        print("   Hareket COK AZ geldiyse sebep servo tipi degil BESLEME")
        print("   olabilir: MG995 kalkista 1-2 A ceker, Pi'nin 5V pini")
        print("   yetmez. Ayri 5-6V BEC kullanin, GND'ler ortak olsun.")
        return 'konum'
    else:
        print("Cevap anlasilmadi, mod degistirilmedi.")
        return None


# --- durum ---
mod = 'konum'          # 'konum' | 'hiz'
deger = NOTR           # konum modunda darbe genisligi
hiz = 300              # hiz modunda notrdan uzaklik (us)
sure = 0.30            # hiz modunda tek yon hareket suresi (sn)
dinlenme = None
cekili = None

darbe(NOTR)
print()
print("Baslangic: %d us (notr). SERVO TIPI BILINMIYOR." % NOTR)
print("ONCE 'x' yazip TESHIS calistirin.")
yardim()

try:
    while True:
        if mod == 'konum':
            istem = "[KONUM %4d us | dinlenme=%s cekili=%s] > " % (
                deger, dinlenme, cekili)
        else:
            istem = "[HIZ  ileri=%d geri=%d sure=%.2fs] > " % (
                NOTR + hiz, NOTR - hiz, sure)
        try:
            k = input(istem).strip().lower()
        except EOFError:
            break
        if not k:
            continue

        if k == 'q':
            break
        elif k in ('?', 'h'):
            yardim()
        elif k == 'x':
            sonuc = teshis()
            if sonuc:
                mod = sonuc
                deger = NOTR
        elif k == 'm':
            mod = 'hiz' if mod == 'konum' else 'konum'
            darbe(NOTR)
            deger = NOTR
            print("  mod: %s" % mod.upper())
        elif k == '0':
            darbe(0)
            print("  darbe kesildi (servo gevsek).")

        # ---------------- KONUM MODU ----------------
        elif mod == 'konum' and k in ('a', 'd', 'z', 'c', 's', 'w'):
            adim = {'a': -10, 'd': 10, 'z': -50, 'c': 50, 's': -2, 'w': 2}[k]
            yeni = max(ALT, min(UST, deger + adim))
            if yeni == deger:
                print("  sinirda (%d-%d us)" % (ALT, UST))
            deger = yeni
            darbe(deger)
        elif mod == 'konum' and k == 'r':
            dinlenme = deger
            print("  dinlenme = %d us" % dinlenme)
        elif mod == 'konum' and k == 'p':
            cekili = deger
            print("  cekili = %d us" % cekili)
        elif mod == 'konum' and k == 't':
            if dinlenme is None or cekili is None:
                print("  once r ve p ile iki degeri kaydedin.")
                continue
            print("  prova: %d -> %d -> %d us" % (dinlenme, cekili, dinlenme))
            darbe(cekili)
            time.sleep(0.20)
            darbe(dinlenme)
            time.sleep(0.20)
            deger = dinlenme

        # ---------------- HIZ MODU ----------------
        elif mod == 'hiz' and k == 'f':
            darbe(NOTR + hiz)
            print("  ILERI (%d us) -- durdurmak icin space" % (NOTR + hiz))
        elif mod == 'hiz' and k == 'b':
            darbe(NOTR - hiz)
            print("  GERI (%d us) -- durdurmak icin space" % (NOTR - hiz))
        elif mod == 'hiz' and k in ('space', ' ', 'n'):
            darbe(NOTR)
            print("  DUR (notr %d us)" % NOTR)
        elif mod == 'hiz' and k in ('+', '='):
            hiz = min(900, hiz + 50)
            print("  hiz = %d us (ileri %d, geri %d)" % (hiz, NOTR + hiz, NOTR - hiz))
        elif mod == 'hiz' and k == '-':
            hiz = max(50, hiz - 50)
            print("  hiz = %d us (ileri %d, geri %d)" % (hiz, NOTR + hiz, NOTR - hiz))
        elif mod == 'hiz' and k == '1':
            sure = max(0.05, sure - 0.05)
            print("  sure = %.2f sn" % sure)
        elif mod == 'hiz' and k == '2':
            sure = min(2.00, sure + 0.05)
            print("  sure = %.2f sn" % sure)
        elif mod == 'hiz' and k == 't':
            print("  prova: ileri %.2fs -> dur -> geri %.2fs -> dur" % (sure, sure))
            darbe(NOTR + hiz)
            time.sleep(sure)
            darbe(NOTR)
            time.sleep(0.30)
            darbe(NOTR - hiz)
            time.sleep(sure)
            darbe(NOTR)
            print("  bitti. Kol BASLANGIC konumuna dondu mu? Donmediyse")
            print("  sureleri esitlemek icin 1/2 ile ayarlayin.")
        else:
            print("  bu modda gecersiz komut: %r  ('?' ile listeye bakin)" % k)

finally:
    try:
        darbe(NOTR)
        time.sleep(0.4)
        darbe(0)
    except Exception:
        pass
    lgpio.gpiochip_close(h)
    print()
    print("=" * 62)
    if mod == 'konum' and dinlenme is not None and cekili is not None:
        print("STANDART SERVO -- motor_fire_module.py'ye:")
        print("    FIRE_SERVO_MODE    = 'konum'")
        print("    FIRE_SERVO_REST_US = %d" % dinlenme)
        print("    FIRE_SERVO_PULL_US = %d" % cekili)
        print("fark: %d us = ~%.0f derece"
              % (abs(cekili - dinlenme), abs(cekili - dinlenme) / 11.1))
    elif mod == 'hiz':
        print("SUREKLI DONUS SERVOSU -- motor_fire_module.py'ye:")
        print("    FIRE_SERVO_MODE      = 'hiz'")
        print("    FIRE_SERVO_NEUTRAL_US = %d" % NOTR)
        print("    FIRE_SERVO_SPEED_US  = %d      # notrdan uzaklik" % hiz)
        print("    FIRE_SERVO_LEG_SEC   = %.2f" % sure)
        print()
        print("UYARI: acik dongu -- servo nereye geldigini bilmiyor. Her")
        print("atisla konum kayabilir. Mumkunse STANDART servoya gecin.")
    else:
        print("Kayit tamamlanmadi.")
