import cv2
import time
import queue

import config

def camera_worker(command_queue, frame_queue, kamera_adi="hunter"):
    """
    Kareleri yakalayıp kuyruğa koyan süreç.

    `kamera_adi` ile hangi kameranın ayarlarının kullanılacağı seçilir.
    Sistemde iki kamera var (gözcü ve avcı); gözcünün kendi süreci
    spotter_module'de çünkü orada yakalama ile analiz aynı yerde yapılıyor.
    Bu işçi normalde AVCI kamera için kullanılır.
    """
    ayar = config.KAMERA_AYARLARI[kamera_adi]
    print(f"Kamera worker basladi: {kamera_adi}")
    capture = None
    is_running = False
    ardisik_hata = 0
    acilis_zamani = 0.0

    # Kamera açıldıktan hemen sonraki ilk okumalar boş dönebilir: UVC
    # kameralar (özellikle Logitech BRIO) çözünürlük/FOURCC ayarlandıktan
    # sonra akışa başlamak için birkaç yüz milisaniye ister.
    ISINMA_SN = 2.0
    # Isınmadan sonra kamerayı ölü saymak için gereken ARDIŞIK hata sayısı.
    # Tek bir boş okuma kalıcı arıza değildir; USB'de tekil kare kaybı olur.
    MAX_ARDISIK_HATA = 30

    while True:
        # Check for commands
        try:
            cmd = command_queue.get_nowait()
            if cmd == "START":
                if not is_running:
                    camera_indices = ayar["indices"]
                    capture = None
                    for index in camera_indices:
                        print(f"Trying camera {index} with CAP_DSHOW...")
                        try:
                            temp_capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
                            if temp_capture.isOpened():
                                capture = temp_capture
                                print(f"Camera {index} (CAP_DSHOW) opened successfully.")
                                break
                        except Exception as e:
                            print(f"Error opening camera {index} (CAP_DSHOW): {e}")

                    if capture and capture.isOpened():
                        # FOURCC çözünürlükten ÖNCE ayarlanmalı; sonra ayarlanırsa
                        # sürücü çoğu zaman çözünürlüğü sıfırlar.
                        if ayar["mjpg"]:
                            capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))

                        capture.set(cv2.CAP_PROP_FRAME_WIDTH, ayar["width"])
                        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, ayar["height"])
                        actual_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
                        actual_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        actual_fps = capture.get(cv2.CAP_PROP_FPS)
                        # Gerçekleşen FOURCC de yazılıyor: MJPG kayıplı sıkıştırma
                        # olduğu için hangi formatın müzakere edildiğini bilmeden
                        # "görüntü neden bulanık" sorusuna cevap verilemiyor.
                        _fcc = int(capture.get(cv2.CAP_PROP_FOURCC))
                        fourcc = "".join(chr((_fcc >> (8 * i)) & 0xFF) for i in range(4)) if _fcc else "?"
                        print(f"{kamera_adi}: kamera {index}, {actual_width}x{actual_height} "
                              f"@ {actual_fps:.0f} fps, format {fourcc} "
                              f"(istenen: {'MJPG' if ayar['mjpg'] else 'surucu varsayilani'})")
                        if (actual_width, actual_height) != (ayar["width"], ayar["height"]):
                            print(f"UYARI ({kamera_adi}): istenen {ayar['width']}x{ayar['height']} "
                                  f"alinamadi, kamera {actual_width}x{actual_height} veriyor.")
                        is_running = True
                        ardisik_hata = 0
                        acilis_zamani = time.time()
                    else:
                        print("ERROR: Could not open any camera.")
                        # Send an error frame to notify the inference/UI process
                        try:
                            frame_queue.put_nowait((-1.0, None))
                        except queue.Full:
                            pass
            elif cmd == "STOP":
                if capture and capture.isOpened():
                    capture.release()
                    capture = None
                is_running = False
                print("Camera stopped.")
                # Clear the queue to prevent stale frames
                while not frame_queue.empty():
                    try:
                        frame_queue.get_nowait()
                    except queue.Empty:
                        break
            elif cmd == "QUIT":
                print("Camera worker quitting.")
                if capture and capture.isOpened():
                    capture.release()
                break
        except queue.Empty:
            pass

        # Capture and push frame
        if is_running and capture and capture.isOpened():
            ret, frame = capture.read()
            if ret and frame is not None and frame.size > 0:
                ardisik_hata = 0
                # Discard old frames if queue is full (keep it real-time)
                if frame_queue.full():
                    try:
                        frame_queue.get_nowait()
                    except queue.Empty:
                        pass

                try:
                    frame_queue.put_nowait((time.time(), frame))
                except queue.Full:
                    pass
            else:
                # ESKİDEN: tek bir başarısız okuma kamerayı KALICI olarak ölü
                # sayıyordu (is_running = False). Logitech BRIO açılıştan
                # hemen sonra birkaç boş kare veriyor ve kamera bir daha hiç
                # açılmıyordu — arayüzde "ışık yanıyor ama görüntü siyah"
                # olarak görülen sorun buydu. Gözcü süreci aynı durumu
                # tolere ettiği için orada sorun çıkmıyordu.
                ardisik_hata += 1
                if time.time() - acilis_zamani < ISINMA_SN:
                    time.sleep(0.02)      # ısınma: sessizce bekle
                    continue
                if ardisik_hata < MAX_ARDISIK_HATA:
                    time.sleep(0.005)     # tekil kare kaybı: yut
                    continue
                print(f"HATA ({kamera_adi}): {ardisik_hata} ardisik bos okuma, "
                      f"kamera olu sayiliyor.")
                is_running = False
                try:
                    frame_queue.put_nowait((-1.0, None))
                except queue.Full:
                    pass

        else:
            time.sleep(0.01) # Sleep to avoid high CPU usage when stopped
