"""
Gözcü (spotter) kamera süreci.

Gövdeye SABİT, zoomsuz, geniş açılı kamera. YOLO çalıştırmaz — yalnızca
OpenCV renk analizi yapar ve hedef adaylarının gövde çerçevesindeki MUTLAK
açısını üretir.

Neden ayrı bir süreçte hem yakalama hem analiz:
    Renk analizi ucuz (1280x720'de inRange + connectedComponents ~3-5 ms),
    ama kareyi kuyruğa koymak pahalı (2.7 MB pickle/kare). Analizi yakalayan
    süreçte yapıp yalnızca birkaç yüz baytlık sonucu göndermek doğru tasarım.
    UI önizlemesi ayrı ve düşük hızda gider.

Neden gözcünün hız tahmini avcınınkinden temiz:
    Gözcü gövdeye sabit olduğu için taretin hareketi ölçümünü hiç etkilemez.
    Geçen fazda uğraştığımız "taret dönünce sahte hedef hızı" sızıntısı bu
    hatta YAPISAL OLARAK yoktur.

Neden dost/düşman ayrımı yoğunlukla değil geometriyle yapılıyor:
    "En büyük kırmızı = düşman" kuralı mesafeye duyarlı ve saha görselinde
    çuvallıyor (uzak düşman 3.600 px, yakın dost 16.200 px kırmızı veriyor;
    dostun altında da kırmızı balon olduğu için tabanı sıfır değil).
    Bunun yerine balonun ÜSTÜNDEKİ pencerede mavi/kırmızı ORANINA bakıyoruz.
    Pencere balonun kendi çapıyla ölçeklendiği için mesafe sadeleşir.
"""

import queue
import time

import cv2
import numpy as np

import config

# UI önizlemesi bu genişliğe küçültülür ve bu hızda gönderilir.
ONIZLEME_GENISLIK = 480
ONIZLEME_HZ = 5.0

# Aday sınıflandırma etiketleri
DOST = 'dost'
DUSMAN = 'dusman'
KARARSIZ = 'kararsiz'


def _maske(hsv, araliklar):
    """Verilen HSV aralıklarının birleşiminden ikili maske üretir."""
    toplam = None
    for alt, ust in araliklar:
        m = cv2.inRange(hsv, np.array(alt, np.uint8), np.array(ust, np.uint8))
        toplam = m if toplam is None else cv2.bitwise_or(toplam, m)
    return toplam


def _temizle(maske):
    """Tek piksellik gürültüyü at, parçalı blobları birleştir."""
    cekirdek = np.ones((3, 3), np.uint8)
    maske = cv2.morphologyEx(maske, cv2.MORPH_OPEN, cekirdek)
    return cv2.morphologyEx(maske, cv2.MORPH_CLOSE, cekirdek)


def balon_adaylari(kirmizi_maske):
    """
    Kırmızı maskeden balon adaylarını çıkarır.

    Balon yuvarlaktır; uzun ince lekeler maket parçası, kablo veya
    yansımadır ve elenir.
    """
    n, _, stats, merkezler = cv2.connectedComponentsWithStats(kirmizi_maske, 8)
    adaylar = []
    en_kucuk, en_buyuk = config.SPOTTER_BALLOON_ASPECT
    for i in range(1, n):
        alan = int(stats[i, cv2.CC_STAT_AREA])
        if alan < config.SPOTTER_MIN_BLOB_AREA:
            continue
        w = int(stats[i, cv2.CC_STAT_WIDTH])
        h = int(stats[i, cv2.CC_STAT_HEIGHT])
        if h <= 0:
            continue
        oran = w / float(h)
        if not (en_kucuk <= oran <= en_buyuk):
            continue
        # DOLGUNLUK: blob kendi kutusunu ne kadar dolduruyor? Daire icin
        # pi/4 = 0.785. Sahada olculdu: gercek balon 0.70, kirmizi F16
        # maketi 0.37. En-boy orani tek basina yetmiyordu -- maketin
        # kutusu da kabaca kare cikabildigi icin 'balon' sayilip iz
        # aciliyordu (gozcu_tani.py aday #0).
        if alan / float(w * h) < config.SPOTTER_BALLOON_MIN_FILL:
            continue
        adaylar.append({
            'cx': float(merkezler[i][0]),
            'cy': float(merkezler[i][1]),
            'w': w, 'h': h,
            'alan': alan,
            'cap': float(max(w, h)),
        })
    return adaylar


def maket_penceresi(aday, kare_gen, kare_yuk):
    """
    Balonun üstünde, maketin bulunması beklenen dikdörtgeni verir.

    Pencere balonun KENDİ piksel çapıyla ölçeklenir — bu yüzden hedefin
    mesafesinden bağımsızdır. 8 metrede de 20 metrede de aynı bölgeye bakar.
    """
    cap = aday['cap']
    alt_kat, ust_kat = config.SPOTTER_MODEL_WINDOW_ABOVE
    yari_gen = cap * config.SPOTTER_MODEL_WINDOW_WIDTH

    y1 = int(round(aday['cy'] - cap * alt_kat))          # pencerenin ALT kenarı
    y0 = int(round(aday['cy'] - cap * ust_kat))          # pencerenin ÜST kenarı
    x0 = int(round(aday['cx'] - yari_gen))
    x1 = int(round(aday['cx'] + yari_gen))

    x0 = max(0, x0); y0 = max(0, y0)
    x1 = min(kare_gen, x1); y1 = min(kare_yuk, y1)
    return x0, y0, x1, y1


def dost_dusman(aday, kirmizi_maske, mavi_maske):
    """
    Balonun üstündeki pencerede mavi/kırmızı oranına bakarak sınıflandırır.

    Bir ORAN döndürüldüğü için mesafe sadeleşir: hem mavi hem kırmızı piksel
    sayısı mesafenin karesiyle küçülür, oranları sabit kalır.

    Ara bölge KARARSIZ olarak işaretlenir ve karar avcının YOLO'suna bırakılır.
    Gözcü hiçbir zaman nihai merci değildir.
    """
    yuk, gen = kirmizi_maske.shape[:2]
    x0, y0, x1, y1 = maket_penceresi(aday, gen, yuk)
    if x1 <= x0 or y1 <= y0:
        return KARARSIZ, 0.0, 0, 0

    kirmizi = int(np.count_nonzero(kirmizi_maske[y0:y1, x0:x1]))
    mavi = int(np.count_nonzero(mavi_maske[y0:y1, x0:x1]))
    toplam = kirmizi + mavi
    if toplam < config.SPOTTER_MIN_BLOB_AREA:
        # Üstte hiçbir şey yok: tek başına duran bir balon. Hedef çifti
        # değil; avcı doğrulasın.
        return KARARSIZ, 0.0, kirmizi, mavi

    mavi_oran = mavi / float(toplam)
    if mavi_oran >= config.SPOTTER_FRIEND_BLUE_RATIO:
        return DOST, mavi_oran, kirmizi, mavi
    if mavi_oran <= config.SPOTTER_ENEMY_BLUE_RATIO:
        return DUSMAN, mavi_oran, kirmizi, mavi
    return KARARSIZ, mavi_oran, kirmizi, mavi


def piksel_to_aci(cx, cy, gen, yuk):
    """
    Gözcü piksel konumunu GÖVDE çerçevesinde mutlak açıya çevirir.

    Gözcü gövdeye sabit olduğu için burada taret açısına hiç ihtiyaç yok —
    ölü zaman telafisi gerekmez. Avcı hattındaki karmaşıklığın tamamı
    kameranın taretle dönmesinden kaynaklanıyordu.
    """
    yaw = (cx - gen / 2.0) * config.SPOTTER_DPP_YAW + config.SPOTTER_YAW_OFFSET
    pitch = (cy - yuk / 2.0) * config.SPOTTER_DPP_PITCH + config.SPOTTER_PITCH_OFFSET
    return yaw, pitch


class Iz:
    """
    Gözcünün tuttuğu kalıcı hedef izi.

    Neden kare kare blob listesi yetmiyor: devir teslim öngörü gerektiriyor.
    Gözcü gecikmesi (~0.05 s) + taret yalpalama süresi (30-40 derece için
    0.34-0.45 s) toplamda ~0.5 saniye. Bu sürede hedef yol alır ve taret
    ölçülen açıya giderse hedefi avcının dar görüş açısında (±11.4 yaw,
    ±6.65 pitch) bulamayabilir. Bu yüzden iz, açısal HIZ da üretir.
    """

    _sonraki_id = 1

    def __init__(self, yaw, pitch, zaman):
        self.id = Iz._sonraki_id
        Iz._sonraki_id += 1
        self.yaw = yaw
        self.pitch = pitch
        self.yaw_hiz = 0.0
        self.pitch_hiz = 0.0
        self.zaman = zaman
        self.kayip = 0
        self.gorulme = 1
        self.sinif = KARARSIZ
        self.mavi_oran = 0.0
        self.kirmizi_alan = 0
        self.cap = 0.0

    def guncelle(self, yaw, pitch, zaman):
        dt = zaman - self.zaman
        if dt > 1e-3:
            ham_y = (yaw - self.yaw) / dt
            ham_p = (pitch - self.pitch) / dt
            r = config.MAX_TARGET_RATE_DEG_S
            ham_y = max(-r, min(r, ham_y))
            ham_p = max(-r, min(r, ham_p))
            self.yaw_hiz = self._yumusat(ham_y, self.yaw_hiz)
            self.pitch_hiz = self._yumusat(ham_p, self.pitch_hiz)
        self.yaw = yaw
        self.pitch = pitch
        self.zaman = zaman
        self.kayip = 0
        self.gorulme += 1

    @staticmethod
    def _yumusat(ham, mevcut):
        """Avcı hattındakiyle aynı uyarlamalı asimetrik yumuşatma."""
        if abs(ham) < abs(mevcut):
            a = config.VELOCITY_DECAY_SMOOTHING
        elif abs(ham) >= config.VELOCITY_FAST_THRESHOLD:
            a = config.VELOCITY_FAST_SMOOTHING
        else:
            a = config.VELOCITY_SMOOTHING
        return a * ham + (1 - a) * mevcut

    def tahmin(self, ileri_sn):
        """`ileri_sn` saniye sonraki açıyı verir (devir teslim öngörüsü)."""
        return (self.yaw + self.yaw_hiz * ileri_sn,
                self.pitch + self.pitch_hiz * ileri_sn)

    def sozluk(self):
        return {
            'id': self.id,
            'yaw': round(self.yaw, 3),
            'pitch': round(self.pitch, 3),
            'yaw_hiz': round(self.yaw_hiz, 3),
            'pitch_hiz': round(self.pitch_hiz, 3),
            'sinif': self.sinif,
            'mavi_oran': round(self.mavi_oran, 3),
            'kirmizi_alan': self.kirmizi_alan,
            'cap': round(self.cap, 1),
            'gorulme': self.gorulme,
            'kayip': self.kayip,
        }


class IzYoneticisi:
    """Kare kare blobları kalıcı izlerle eşleştirir."""

    def __init__(self):
        self.izler = []

    def guncelle(self, olcumler, zaman):
        """olcumler: [(yaw, pitch, sinif, mavi_oran, kirmizi_alan, cap), ...]"""
        eslesen = set()
        for yaw, pitch, sinif, mavi_oran, kirmizi, cap in olcumler:
            en_iyi, en_iyi_mesafe = None, config.SPOTTER_TRACK_MATCH_DEG
            for iz in self.izler:
                if id(iz) in eslesen:
                    continue
                # İzin tahmin edilen konumuna göre eşleştir; hareketli hedefte
                # ham konuma göre eşleştirmek kare kare kaymaya yol açar.
                t_yaw, t_pitch = iz.tahmin(zaman - iz.zaman)
                mesafe = ((yaw - t_yaw) ** 2 + (pitch - t_pitch) ** 2) ** 0.5
                if mesafe < en_iyi_mesafe:
                    en_iyi, en_iyi_mesafe = iz, mesafe
            if en_iyi is None:
                en_iyi = Iz(yaw, pitch, zaman)
                self.izler.append(en_iyi)
            else:
                en_iyi.guncelle(yaw, pitch, zaman)
            eslesen.add(id(en_iyi))
            en_iyi.sinif = sinif
            en_iyi.mavi_oran = mavi_oran
            en_iyi.kirmizi_alan = kirmizi
            en_iyi.cap = cap

        for iz in self.izler:
            if id(iz) not in eslesen:
                iz.kayip += 1
        self.izler = [iz for iz in self.izler
                      if iz.kayip <= config.SPOTTER_TRACK_MAX_MISS]
        return self.izler


def kareyi_coz(frame, iz_yoneticisi, zaman):
    """
    Tek bir kareyi analiz eder ve güncel iz listesini döndürür.

    Süreçten bağımsız saf fonksiyon — birim testi ve kayıttan tekrar
    oynatma için doğrudan çağrılabilir.
    """
    yuk, gen = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    kirmizi = _temizle(_maske(hsv, config.SPOTTER_RED_RANGES))
    mavi = _temizle(_maske(hsv, config.SPOTTER_BLUE_RANGES))

    olcumler = []
    for aday in balon_adaylari(kirmizi):
        sinif, mavi_oran, k, m = dost_dusman(aday, kirmizi, mavi)
        yaw, pitch = piksel_to_aci(aday['cx'], aday['cy'], gen, yuk)
        # Kırmızı alan = balonun kendisi + üstteki pencerede bulunan kırmızı.
        # Sıralamada kullanılıyor ama SINIFLANDIRMADA kullanılmıyor.
        olcumler.append((yaw, pitch, sinif, mavi_oran, aday['alan'] + k,
                         aday['cap']))

    return iz_yoneticisi.guncelle(olcumler, zaman), kirmizi, mavi


def _kamera_ac():
    for index in config.SPOTTER_CAMERA_INDICES:
        try:
            cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            if cap.isOpened():
                # FOURCC çözünürlükten ÖNCE ayarlanmalı; sonra ayarlanırsa
                # sürücü çoğu zaman çözünürlüğü sıfırlar.
                if config.SPOTTER_USE_MJPG:
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.SPOTTER_WIDTH)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.SPOTTER_HEIGHT)
                g = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                y = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                print(f"Gozcu kamera {index} acildi: {g}x{y}")
                return cap, index
        except Exception as e:
            print(f"Gozcu kamera {index} acilamadi: {e}")
    return None, None


def spotter_worker(command_queue, result_queue):
    """Gözcü süreci: yakala, analiz et, küçük sonuç gönder."""
    print("Gozcu worker basladi.")
    cap = None
    acilan_indeks = None
    calisiyor = False
    yonetici = IzYoneticisi()
    son_onizleme = 0.0

    while True:
        try:
            cmd = command_queue.get_nowait()
            if cmd == "START":
                if not calisiyor:
                    cap, acilan_indeks = _kamera_ac()
                    if cap is None:
                        try:
                            result_queue.put_nowait({'hata': 'gozcu kamera acilamadi'})
                        except queue.Full:
                            pass
                    else:
                        calisiyor = True
                        yonetici = IzYoneticisi()
            elif cmd == "STOP":
                if cap is not None:
                    cap.release()
                    cap = None
                calisiyor = False
                yonetici = IzYoneticisi()
                while not result_queue.empty():
                    try:
                        result_queue.get_nowait()
                    except queue.Empty:
                        break
            elif cmd == "QUIT":
                if cap is not None:
                    cap.release()
                print("Gozcu worker kapaniyor.")
                break
        except queue.Empty:
            pass

        if not (calisiyor and cap is not None and cap.isOpened()):
            time.sleep(0.01)
            continue

        ok, frame = cap.read()
        if not ok or frame is None or frame.size == 0:
            time.sleep(0.005)
            continue

        yakalama = time.time()
        try:
            izler, kirmizi, _ = kareyi_coz(frame, yonetici, yakalama)
        except Exception as e:
            print(f"Gozcu analiz hatasi: {e}")
            continue

        sonuc = {
            'zaman': yakalama,
            'izler': [iz.sozluk() for iz in izler],
            'gen': frame.shape[1],
            'yuk': frame.shape[0],
            # Hangi kameranın açıldığı arayüzde görünsün: indeks ataması
            # Windows'ta USB portuna göre değişiyor ve yanlış eşleşme
            # "görüntü gelmiyor" gibi görünüyor.
            'indeks': acilan_indeks,
        }

        # Önizleme yalnızca düşük hızda ve küçültülmüş gider; tam kareyi her
        # seferinde göndermek IPC'yi gereksiz yere doldurur.
        if yakalama - son_onizleme >= 1.0 / ONIZLEME_HZ:
            son_onizleme = yakalama
            olcek = ONIZLEME_GENISLIK / float(frame.shape[1])
            kucuk = cv2.resize(frame, (ONIZLEME_GENISLIK,
                                       max(1, int(frame.shape[0] * olcek))))
            sonuc['onizleme'] = kucuk
            sonuc['onizleme_olcek'] = olcek

        if result_queue.full():
            try:
                result_queue.get_nowait()
            except queue.Empty:
                pass
        try:
            result_queue.put_nowait(sonuc)
        except queue.Full:
            pass
