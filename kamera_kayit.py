"""
AVCI KAMERA KAYIT ARACI — etiketleme verisi toplamak icin (2026-09-24).

Kamerayi, sistemin CALISMA ANINDA kullandigi ayarlarin AYNISIYLA acar ve
kaydeder. Amac: etiketlenecek goruntunun, modelin sahada gordugu
goruntuyle birebir ayni olmasi. Farkli pozlama/kirpma ile toplanmis veri,
modele sahada hic karsilasmayacagi bir dagilim ogretir.

AYARLARIN AYNI OLDUGU NASIL GARANTI EDILIYOR: cozunurluk, FOURCC, kare
hizi ve UVC denetimleri `config`'ten okunur; UVC uygulamasi ve model
en/boy kirpmasi icin `camera_module`'un KENDI fonksiyonlari cagrilir
(`_uvc_uygula`, `_model_oranina_kirp`). Yani burada ikinci bir kopya
yok — boru hatti degisirse bu arac da otomatik ayni degisir.

KULLANIM
    python kamera_kayit.py                    # avci kamera, varsayilanlar
    python kamera_kayit.py --kamera spotter   # gozcu kamera
    python kamera_kayit.py --png              # ayrica her kareyi PNG yaz
    python kamera_kayit.py --kirpma-yok       # model kirpmasi olmadan
    python kamera_kayit.py --klasor D:/veri   # cikti klasoru

TUSLAR
    BOSLUK : kaydi DURDUR / DEVAM ETTIR   (istenen tus)
    K      : tek kare anlik goruntu (PNG)
    Q veya ESC : cik

NOT: kamerayi ayni anda iki program acamaz. Bu araci calistirmadan once
ana arayuzu (bukrek_main) kapatin.
"""

import argparse
import os
import sys
import time

import cv2

import config
import camera_module


def _kamera_ac(kamera_adi):
    """
    Kamerayi boru hattiyla AYNI sirayla ve ayni ayarlarla acar.

    Sira onemli: FOURCC -> cozunurluk -> kare hizi -> UVC denetimleri.
    `camera_module` da tam olarak bu sirayi kullaniyor; format degisimi
    bazi suruculerde denetimleri sifirladigi icin UVC en sona birakildi.
    """
    ayar = config.KAMERA_AYARLARI[kamera_adi]
    capture = None
    for index in ayar["indices"]:
        print(f"Kamera {index} deneniyor (CAP_DSHOW)...")
        try:
            aday = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            if aday.isOpened():
                capture = aday
                print(f"Kamera {index} acildi.")
                break
            aday.release()
        except Exception as e:
            print(f"  kamera {index} acilamadi: {e}")
    if capture is None:
        return None, None

    if ayar["mjpg"]:
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, ayar["width"])
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, ayar["height"])
    if ayar.get("fps"):
        capture.set(cv2.CAP_PROP_FPS, ayar["fps"])

    gercek_g = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    gercek_y = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    gercek_fps = capture.get(cv2.CAP_PROP_FPS)
    print(f"{kamera_adi}: {gercek_g}x{gercek_y} @ {gercek_fps:.0f} fps, "
          f"format {camera_module._fourcc_metni(capture)} "
          f"(istenen: {'MJPG' if ayar['mjpg'] else 'surucu varsayilani'})")
    if (gercek_g, gercek_y) != (ayar["width"], ayar["height"]):
        print(f"UYARI: istenen {ayar['width']}x{ayar['height']} alinamadi.")

    # Beyaz dengesi / pozlama / odak — boru hattiyla AYNI fonksiyon.
    camera_module._uvc_uygula(capture, kamera_adi)
    return capture, (gercek_fps if gercek_fps and gercek_fps > 1 else 15.0)


def _cift_boyuta_kirp(kare):
    """
    Kareyi CIFT sayili genislik/yukseklige kirpar.

    NEDEN: MJPG/JPEG tek sayili boyutu kabul etmiyor. OpenCV bunu SESSIZCE
    yapiyor — olculdu: 1920x1105 istendiginde dosya 1920x1104 olarak
    yazildi ve hicbir uyari cikmadi. Etiketleme verisinde bu kabul edilemez;
    kutu koordinatlari modelin gordugu kareyle birebir ortusmeli.
    Kirpmayi BIZ yapiyoruz ki ne oldugu belli olsun ve PNG'ler ile video
    ayni kareyi gostersin.
    """
    yuk, gen = kare.shape[:2]
    return kare[:yuk - (yuk % 2), :gen - (gen % 2)]


def _yazici_ac(yol, fps, boyut):
    """MJPG AVI: kare kare cozulebilir, her Windows kurulumunda calisir."""
    fourcc = cv2.VideoWriter_fourcc(*'MJPG')
    yazici = cv2.VideoWriter(yol, fourcc, fps, boyut)
    if not yazici.isOpened():
        print(f"HATA: kayit dosyasi acilamadi: {yol}")
        return None
    return yazici


def _dosyayi_dogrula(yol, beklenen_boyut, beklenen_kare):
    """
    Kayit bitince dosyayi GERI OKUYUP boyut ve kare sayisini dogrular.

    Kodek sessizce boyut degistirebildigi icin (yukariya bakin) sonucu
    varsaymak yerine olcuyoruz. Uyusmazlik varsa ekrana acikca yazilir.
    """
    cap = cv2.VideoCapture(yol)
    if not cap.isOpened():
        return False, "dosya acilamadi"
    gen = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    yuk = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    if (gen, yuk) != tuple(beklenen_boyut):
        return False, (f"BOYUT UYUSMUYOR: beklenen {beklenen_boyut[0]}x"
                       f"{beklenen_boyut[1]}, dosyada {gen}x{yuk}")
    if beklenen_kare and abs(n - beklenen_kare) > 2:
        return False, f"kare sayisi uyusmuyor: beklenen {beklenen_kare}, dosyada {n}"
    return True, f"{gen}x{yuk}, {n} kare"


def _bilgi_ciz(kare, kayitta, kare_sayisi, sure, duraklama_sayisi):
    """Onizlemeye durum yazisi basar. KAYDEDILEN kareye DEGIL, yalnizca
    ekranda gosterilen kopyaya cizilir — kayit temiz kalir."""
    g = kare.shape[1]
    renk = (0, 0, 255) if kayitta else (160, 160, 160)
    metin = "KAYIT" if kayitta else "DURAKLADI"
    cv2.rectangle(kare, (0, 0), (g, 46), (0, 0, 0), -1)
    cv2.circle(kare, (26, 23), 11, renk, -1 if kayitta else 2)
    cv2.putText(kare, metin, (48, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.8, renk, 2)
    cv2.putText(kare, f"kare {kare_sayisi}   {sure:5.1f} sn   duraklama {duraklama_sayisi}",
                (210, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (230, 230, 230), 1)
    cv2.putText(kare, "BOSLUK: dur/devam   K: kare kaydet   Q: cik",
                (g - 520 if g > 560 else 210, 31),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (140, 200, 255), 1)


def main():
    ap = argparse.ArgumentParser(description="Avci/gozcu kamera kayit araci")
    ap.add_argument('--kamera', default='hunter', choices=['hunter', 'spotter'])
    ap.add_argument('--klasor', default='kamera_kayit',
                    help="cikti klasoru (varsayilan: kamera_kayit)")
    ap.add_argument('--png', action='store_true',
                    help="videoya EK OLARAK her kareyi PNG yaz (kayipsiz, etiketleme icin)")
    ap.add_argument('--kirpma-yok', action='store_true',
                    help="model en/boy kirpmasini UYGULAMA (ham kare kaydedilir)")
    ap.add_argument('--onizleme-yok', action='store_true',
                    help="onizleme penceresi acma (tus kontrolu calismaz)")
    args = ap.parse_args()

    kamera_adi = args.kamera
    kirp = not args.kirpma_yok

    print("=" * 64)
    print(f"KAMERA KAYIT — {kamera_adi}")
    print("Ana arayuz (bukrek_main) ACIKSA kapatin; kamera paylasilmaz.")
    print("=" * 64)

    capture, fps = _kamera_ac(kamera_adi)
    if capture is None:
        print("HATA: hicbir kamera acilamadi.")
        return 1

    # Ilk kareyi al: kayit boyutu KIRPMADAN SONRAKI boyut olmali.
    for _ in range(30):
        ok, kare = capture.read()
        if ok and kare is not None and kare.size:
            break
        time.sleep(0.05)
    else:
        print("HATA: kameradan kare okunamadi.")
        capture.release()
        return 1

    if kirp:
        kare = camera_module._model_oranina_kirp(kare, kamera_adi)
    model_yuk, model_gen = kare.shape[:2]
    kare = _cift_boyuta_kirp(kare)
    yuk, gen = kare.shape[:2]
    print(f"Kayit boyutu: {gen}x{yuk} "
          f"({'model orani kirpildi' if kirp else 'ham kare'}), {fps:.0f} fps")
    if (gen, yuk) != (model_gen, model_yuk):
        print(f"  NOT: MJPG cift sayili boyut istedigi icin "
              f"{model_gen}x{model_yuk} -> {gen}x{yuk} kirpildi "
              f"(alttan/sagdan en fazla 1 piksel).")

    os.makedirs(args.klasor, exist_ok=True)
    damga = time.strftime("%Y%m%d_%H%M%S")
    video_yolu = os.path.join(args.klasor, f"{kamera_adi}_{damga}.avi")
    yazici = _yazici_ac(video_yolu, fps, (gen, yuk))
    if yazici is None:
        capture.release()
        return 1
    png_klasoru = None
    if args.png:
        png_klasoru = os.path.join(args.klasor, f"{kamera_adi}_{damga}_kareler")
        os.makedirs(png_klasoru, exist_ok=True)
        print(f"PNG klasoru: {png_klasoru}")
    print(f"Video: {video_yolu}")
    print("BOSLUK ile kaydi durdurup devam ettirebilirsiniz. Q ile cikis.\n")

    kayitta = True
    kaydedilen = 0
    duraklama = 0
    anlik = 0
    baslangic = time.time()
    kayit_suresi = 0.0
    son_an = time.time()
    onizleme = not args.onizleme_yok
    pencere = f"Kamera Kayit — {kamera_adi}  (BOSLUK: dur/devam, Q: cik)"

    try:
        while True:
            ok, kare = capture.read()
            if not ok or kare is None or kare.size == 0:
                # Tek kare kaybi normal; ust uste olursa kullanici gorur.
                if onizleme and cv2.waitKey(1) & 0xFF in (ord('q'), 27):
                    break
                continue

            if kirp:
                kare = camera_module._model_oranina_kirp(kare, kamera_adi)
            kare = _cift_boyuta_kirp(kare)
            if kare.shape[1] != gen or kare.shape[0] != yuk:
                # Kamera kare boyutunu degistirdiyse kayit bozulmasin.
                print(f"UYARI: kare boyutu degisti ({kare.shape[1]}x{kare.shape[0]}), "
                      f"bu kare atlandi.")
                continue

            simdi = time.time()
            if kayitta:
                kayit_suresi += simdi - son_an
                yazici.write(kare)
                if png_klasoru:
                    cv2.imwrite(os.path.join(png_klasoru, f"{kaydedilen:06d}.png"), kare)
                kaydedilen += 1
            son_an = simdi

            if onizleme:
                gosterim = kare.copy()
                _bilgi_ciz(gosterim, kayitta, kaydedilen, kayit_suresi, duraklama)
                if gosterim.shape[1] > 1280:
                    olcek = 1280.0 / gosterim.shape[1]
                    gosterim = cv2.resize(
                        gosterim, None, fx=olcek, fy=olcek,
                        interpolation=cv2.INTER_AREA)
                cv2.imshow(pencere, gosterim)
                tus = cv2.waitKey(1) & 0xFF
                if tus == ord(' '):
                    kayitta = not kayitta
                    if not kayitta:
                        duraklama += 1
                    print(f"  [{'KAYIT' if kayitta else 'DURAKLADI'}] "
                          f"kare {kaydedilen}, {kayit_suresi:.1f} sn")
                elif tus in (ord('k'), ord('K')):
                    anlik += 1
                    yol = os.path.join(args.klasor,
                                       f"{kamera_adi}_{damga}_anlik{anlik:03d}.png")
                    cv2.imwrite(yol, kare)
                    print(f"  anlik goruntu: {yol}")
                elif tus in (ord('q'), ord('Q'), 27):
                    break
                # Pencere capraziyla kapatilirsa da cikilsin.
                if cv2.getWindowProperty(pencere, cv2.WND_PROP_VISIBLE) < 1:
                    break
    except KeyboardInterrupt:
        print("\nCtrl+C ile durduruldu.")
    finally:
        yazici.release()
        capture.release()
        if onizleme:
            cv2.destroyAllWindows()

    gecen = time.time() - baslangic
    print("\n" + "=" * 64)
    print(f"Kaydedilen kare : {kaydedilen}")
    print(f"Kayit suresi    : {kayit_suresi:.1f} sn "
          f"(toplam acik kalma {gecen:.1f} sn, {duraklama} duraklama)")
    if kaydedilen and kayit_suresi > 0:
        print(f"Gerceklesen fps : {kaydedilen / kayit_suresi:.1f}")
    print(f"Video           : {video_yolu}")
    ok, ayrinti = _dosyayi_dogrula(video_yolu, (gen, yuk), kaydedilen)
    print(f"Dogrulama       : {'TAMAM' if ok else 'SORUN'} — {ayrinti}")
    if png_klasoru:
        print(f"PNG kareler     : {png_klasoru}")
    print("=" * 64)
    return 0


if __name__ == '__main__':
    sys.exit(main())
