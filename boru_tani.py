"""
Boru hattı tanılama: kamera -> çıkarım -> sonuç kuyruğu, arayüz OLMADAN.

kamera_tani.py kameraların sağlam olduğunu gösterdiyse ama arayüzde görüntü
gelmiyorsa, kırılma noktası bu zincirin içindedir. Bu araç zinciri
uygulamadaki gibi kurar ve her adımda ne olduğunu yazar.
"""

import multiprocessing as mp
import queue
import time
import traceback

import config


def model_testi():
    print("=" * 66)
    print("1. YOLO MODELI YUKLENIYOR")
    print("=" * 66)
    print(f"  yol: {config.YOLO_MODEL_PATH}")
    import os
    if not os.path.exists(config.YOLO_MODEL_PATH):
        print("  !!! DOSYA YOK !!!")
        return False
    print(f"  boyut: {os.path.getsize(config.YOLO_MODEL_PATH) / 1e6:.1f} MB")
    try:
        from inference_module import YoloModel
        t0 = time.time()
        m = YoloModel(config.YOLO_MODEL_PATH, config.IMG_WIDTH, config.IMG_HEIGHT)
        print(f"  YoloModel olusturuldu ({time.time() - t0:.1f} sn)")

        import numpy as np
        sahte = np.zeros((720, 1280, 3), np.uint8)
        t0 = time.time()
        det = m.infer(sahte, config.CLASSES)
        print(f"  test cikarimi calisti ({time.time() - t0:.2f} sn), "
              f"{len(det)} tespit (bos karede 0 beklenir)")
        print("  SONUC: model SORUNSUZ")
        return True
    except Exception:
        print("  !!! MODEL YUKLENEMEDI !!!")
        traceback.print_exc()
        print("\n  Bu, cikarim surecinin baslar baslamaz olmesine ve sonuc")
        print("  kuyruguna hicbir sey gelmemesine yol acar -> arayuzde")
        print("  goruntu yok. Cozum: .engine dosyasini bu makinede/bu")
        print("  TensorRT surumuyle yeniden uretin.")
        return False


def boru_testi(sure=8.0):
    from camera_module import camera_worker
    from inference_module import inference_worker

    print()
    print("=" * 66)
    print(f"2. AVCI BORU HATTI  (kamera -> cikarim -> sonuc), {sure:.0f} sn")
    print("=" * 66)

    cam_q = mp.Queue()
    frame_q = mp.Queue(maxsize=2)
    inf_q = mp.Queue()
    res_q = mp.Queue(maxsize=2)

    cam_p = mp.Process(target=camera_worker, args=(cam_q, frame_q, "hunter"))
    cam_p.daemon = True
    cam_p.start()
    inf_p = mp.Process(target=inference_worker, args=(inf_q, frame_q, res_q))
    inf_p.daemon = True
    inf_p.start()

    print("  surecler baslatildi, model yuklenmesi icin 8 sn bekleniyor...")
    time.sleep(8)
    print(f"  kamera sureci canli: {cam_p.is_alive()}")
    print(f"  cikarim sureci canli: {inf_p.is_alive()}")
    if not inf_p.is_alive():
        print("  !!! CIKARIM SURECI OLMUS — yukaridaki model hatasina bakin !!!")

    cam_q.put("START")
    inf_q.put({"action": "START"})
    inf_q.put({"action": "SET_TASK", "task": "task1"})
    print("  START gonderildi, sonuclar bekleniyor...")

    basla = time.time()
    sonuc, hata, tespitli = 0, 0, 0
    ilk_bilgi = None
    while time.time() - basla < sure:
        try:
            r = res_q.get(timeout=0.5)
        except queue.Empty:
            continue
        ft, frame, det, qr, qrb, ow, oh = r
        if frame is None and ft == -1.0:
            hata += 1
            continue
        sonuc += 1
        if det:
            tespitli += 1
        if ilk_bilgi is None:
            ilk_bilgi = (frame.shape, ow, oh)

    gecen = time.time() - basla
    print(f"\n  sonuc kuyrugundan gelen: {sonuc} kare ({sonuc / gecen:.1f}/sn)")
    print(f"  kamera hata sinyali    : {hata}")
    print(f"  tespit iceren kare     : {tespitli}")
    if ilk_bilgi:
        print(f"  kucultulmus kare       : {ilk_bilgi[0]}  (ham {ilk_bilgi[1]}x{ilk_bilgi[2]})")

    print()
    if sonuc == 0:
        print("  SONUC: BORU HATTI TIKALI. Arayuzdeki 'goruntu yok' sorunu burada.")
        if not inf_p.is_alive():
            print("  -> cikarim sureci olmus: model yuklenemedi")
        elif hata:
            print("  -> kamera hata sinyali gonderiyor: indeks mesgul olabilir")
        else:
            print("  -> kamera kare uretmiyor: HUNTER_CAMERA_INDICES yanlis olabilir")
    else:
        print("  SONUC: boru hatti CALISIYOR. Sorun arayuz katmaninda.")

    cam_q.put("QUIT")
    inf_q.put({"action": "QUIT"})
    time.sleep(1)
    for p in (cam_p, inf_p):
        if p.is_alive():
            p.terminate()
    return sonuc > 0


def gozcu_testi(sure=6.0):
    from spotter_module import spotter_worker
    print()
    print("=" * 66)
    print(f"3. GOZCU SURECI, {sure:.0f} sn")
    print("=" * 66)
    cmd_q = mp.Queue()
    res_q = mp.Queue(maxsize=2)
    p = mp.Process(target=spotter_worker, args=(cmd_q, res_q))
    p.daemon = True
    p.start()
    time.sleep(1)
    cmd_q.put("START")

    basla = time.time()
    sonuc, onizleme, izli = 0, 0, 0
    hata_mesaji = None
    while time.time() - basla < sure:
        try:
            r = res_q.get(timeout=0.5)
        except queue.Empty:
            continue
        if 'hata' in r:
            hata_mesaji = r['hata']
            continue
        sonuc += 1
        if 'onizleme' in r:
            onizleme += 1
        if r.get('izler'):
            izli += 1

    gecen = time.time() - basla
    print(f"  gelen sonuc      : {sonuc} ({sonuc / gecen:.1f}/sn)")
    print(f"  onizleme iceren  : {onizleme}  (~5/sn beklenir)")
    print(f"  iz bulunan kare  : {izli}")
    if hata_mesaji:
        print(f"  HATA: {hata_mesaji}")
    print()
    if sonuc == 0:
        print("  SONUC: GOZCU CALISMIYOR -> SPOTTER_CAMERA_INDICES yanlis olabilir")
    elif onizleme == 0:
        print("  SONUC: gozcu calisiyor ama onizleme gondermiyor (arayuzde panel bos kalir)")
    else:
        print("  SONUC: gozcu SORUNSUZ")

    cmd_q.put("QUIT")
    time.sleep(1)
    if p.is_alive():
        p.terminate()
    return sonuc > 0


if __name__ == '__main__':
    mp.freeze_support()
    print("ARAYUZU KAPATTIGINIZDAN EMIN OLUN.\n")
    model_ok = model_testi()
    boru_ok = boru_testi()
    gozcu_ok = gozcu_testi()
    print()
    print("=" * 66)
    print("OZET")
    print("=" * 66)
    print(f"  model yukleniyor      : {'EVET' if model_ok else 'HAYIR'}")
    print(f"  avci boru hatti       : {'EVET' if boru_ok else 'HAYIR'}")
    print(f"  gozcu sureci          : {'EVET' if gozcu_ok else 'HAYIR'}")
