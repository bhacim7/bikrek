import sys
import cv2
import PyQt5
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QSizePolicy, \
    QSpacerItem, QGroupBox, QLineEdit, QMessageBox, QRadioButton
from PyQt5.QtGui import QPixmap, QImage, QPainter, QPen, QFont
from PyQt5.QtCore import QTimer, Qt, QCoreApplication, QThread, pyqtSignal

import time
import os
import math
import numpy as np
import traceback
import multiprocessing as mp
import queue
from collections import deque

import config
from rpi_communicator import RPiCommunicator
from camera_module import camera_worker
from inference_module import inference_worker
from spotter_module import spotter_worker
import engagement
from engagement import (BOSTA, TARAMA, YONELME, DOGRULAMA, KILIT, ATES)

class HavaSavunmaArayuz(QWidget):
    def __init__(self, camera_cmd_q, inference_cmd_q, result_q,
                 spotter_cmd_q=None, spotter_result_q=None):
        print("HATA AYIKLAMA: HavaSavunmaArayuz başlatıldı.")
        super().__init__()
        self.setWindowTitle('Hava Savunma Sistemi Arayüzü')
        # Maksimize edilmezse kullanilacak baslangic boyutu. 2560x1600 idi:
        # yukseklik cogu ekrandan buyuk oldugu icin pencere tasiyordu.
        self.setGeometry(60, 60, 2000, 1100)
        self.setStyleSheet("background-color: black;")

        # Multiprocessing queues
        self.camera_cmd_q = camera_cmd_q
        self.inference_cmd_q = inference_cmd_q
        self.result_q = result_q
        # Gözcü kuyrukları. None olabilir (tek kameralı hata ayıklama için);
        # o durumda otonom aşamalar gözcüsüz, yalnızca avcının gördüğüyle
        # çalışır ve tarama yapamaz.
        self.spotter_cmd_q = spotter_cmd_q
        self.spotter_result_q = spotter_result_q

        # --- UI Elemanları Oluşturma ---
        print("HATA AYIKLAMA: UI elemanları oluşturuluyor.")
        self.camera_label = QLabel(self)
        # AVCI PANELI ESNEK. Sabit boyut verilirse (ilk denemede 1280x737
        # verilmişti) pencere `showMaximized()` ile 2560'a açıldığında panel
        # 1280'de kalıyor ve ekranın yarısı boş kalıyordu. Artık pencereyle
        # birlikte büyüyor; `_display_frame` her karede etiketin GÜNCEL
        # boyutuna sığdırdığı için ek bir iş gerekmiyor.
        #
        # Alt sınır, düzenin çökmemesi için. Üst sınır yok: ekran ne kadar
        # genişse o kadar büyür.
        _av_g, _av_y = config.ui_avci_etiket_boyutu()
        self.camera_label.setMinimumSize(_av_g, _av_y)
        self.camera_label.setSizePolicy(QSizePolicy.Expanding,
                                        QSizePolicy.Expanding)
        # HİZALAMA AÇIKÇA ORTALANIYOR — VARSAYILAN DEĞİL.
        # QLabel'in pixmap varsayılanı `AlignLeft | AlignVCenter`'dır. Kamera
        # 1920x1200 (16:10) verdiği için pixmap KeepAspectRatio ile 1728x1080
        # oluyor ve 1920 genişliğindeki etikete SOLA YASLI çiziliyordu:
        #   - sağda 192 piksellik boşluk (sahada "kamera ile butonlar arasında
        #     boşluk var" olarak görüldü),
        #   - görüntünün merkezi etiketin 864'ünde, oysa tıklama kodu etiket
        #     merkezini (960) kullanıyordu -> 96 piksellik sabit kayma.
        # Sonuç: nişangahın 96 piksel sağına kadar yapılan tıklamalar NEGATİF
        # hata üretip tareti SOLA gönderiyordu. Ekran kaydından doğrulandı:
        # imleç nişangahın 27 piksel sağındayken taret -1.3 derece gitti;
        # (27-96) x 0.01919 = -1.32 derece.
        # Ortalamak hem boşluğu simetrik yapıyor hem de `_etiket_to_kare`
        # dönüşümünü kesinleştiriyor.
        self.camera_label.setAlignment(Qt.AlignCenter)
        self.camera_label.setStyleSheet("background-color: black;")

        # GÖZCÜ önizlemesi. Gözcünün ne gördüğünü ve hangi açıyı ürettiğini
        # ekranda görmeden sahada hata ayıklamak imkânsız.
        # Genişlik config'ten; `spotter_module.ONIZLEME_GENISLIK` de aynı
        # değeri kullanıyor, yani önizleme bu boyutta ÜRETİLİYOR — panel
        # büyüdüğünde görüntü gerilmiyor, gerçekten netleşiyor.
        self.spotter_label = QLabel(self)
        self.spotter_label.setFixedSize(config.UI_GOZCU_GENISLIK,
                                        config.UI_GOZCU_GENISLIK * 9 // 16)
        self.spotter_label.setAlignment(Qt.AlignCenter)
        self.spotter_label.setStyleSheet("background-color: #101010; color: #888;")
        self.spotter_label.setText("Gözcü: kapalı")
        self.spotter_info_label = QLabel("Gözcü: -")
        self.spotter_info_label.setStyleSheet("color: #9ad; font-size: 12px;")

        self.status_label = QLabel("Durum: Hazır")
        self.status_label.setStyleSheet("color: white; font-size: 14px;")
        self.target_info_label = QLabel("Hedef Bilgisi: Yok")
        self.target_info_label.setStyleSheet("color: white; font-size: 14px;")

        # Üst bilgi satırı (yaw/pitch/kare sayaçları). ARTIK DÜZENE BAĞLI:
        # eskiden `move(1530, 5)` ile MUTLAK konumdaydı ve genişliği 760'a
        # sabitlenmişti. Pencere daraldığında (avcı paneli 1920'den 1280'e
        # inince) 1530+760 = 2290 piksel, pencerenin dışına taşıyordu.
        self.info_label = QLabel(self)
        self.info_label.setFixedHeight(30)
        self.info_label.setAlignment(Qt.AlignCenter)
        self.update_info_panel("BUKREK Hava Savunma Sistemi")
        print("HATA AYIKLAMA: UI elemanları oluşturuldu.")

        self.no_fire_yaw_start = 0.0
        self.no_fire_yaw_end = 0.0

        self.movement_restricted_yaw_start = 0
        self.movement_restricted_yaw_end = 0

        # Nişan toleransı artık sabit piksel DEĞİL: balonun yarıçapının bir
        # oranı (config.AIM_TOLERANCE_RATIO). Balon 15 metrede avcıda 30
        # piksel, 5 metrede 90 piksel; sabit bir eşik ikisinde çok farklı
        # anlam taşırdı. Bu alan yalnızca geriye dönük varsayılan.
        self.aiming_tolerance = config.AIM_TOLERANCE_MIN_PIXELS
        # Öncelikli durum mesajının ekranda kalacağı son an.
        self._oncelikli_mesaj_bitis = 0.0

        # --- Gözcü / angajman durumu ---
        self.gozcu_izler = []          # gözcü sürecinden gelen son iz listesi
        self.gozcu_zamani = 0.0
        self.gozcu_indeks = None       # gözcünün açtığı kamera indeksi
        self.gozcu_onizleme = None
        self.gozcu_bloklari = []       # SADECE cizim: gozcunun ham bloblari
        self.angajman = engagement.AngajmanMakinesi()
        self.aktif_cift = None         # o karedeki maket+balon çifti
        self.balon_gercek_goruldu = False
        self._son_angajman_komutu = 0.0
        # Kilitli hedefin GERÇEK tespit kutuları (çizim için).
        self._kilitli_bboxlar = set()
        self._nisan_alinan_bbox = None
        # Hedef Takip modunda takip edilen noktanın son konumu (süreklilik).
        self._takip_hedef_kimlik = None

        # Kameranın ham kare boyutu. İlk sonuç geldiğinde inference sürecinden
        # gerçek değerlerle güncellenir; buradakiler yalnızca başlangıç değeridir.
        self.frame_orig_w = 1080
        self.frame_orig_h = 720

        self.current_yaw_angle = 0.0
        self.current_pitch_angle = 0.0

        self.target_destroyed = False
        self.target_lost_time = 0.0
        self.prediction_time_limit = 0.5

        self.waiting_for_new_engagement_command = False
        self.engagement_home_position_yaw = 0
        self.engagement_home_position_pitch = 0
        self.qr_degrees = {}
        self.current_qr_char = None
        self.active_engagement_target_color = None
        self.active_engagement_target_shape = None
        self.current_tracked_target_class = None
        self.current_tracked_target_bbox = None
        self.is_ready_to_engage_from_qr = False

        self.is_aimed_at_target = False
        self.is_target_active = False

        self.missing_frames = 0
        self.MAX_MISSING_FRAMES = config.MAX_MISSING_FRAMES
        # Tahmin bu kadar kare genişliğinden fazla dışarı taşarsa hedef kayıp
        # sayılır. Tahminin kontrolden çıkıp tareti savurmasına karşı emniyet.
        self.PREDICTION_LIMIT_FRAMES = 1.5
        self.MAX_TARGET_RATE_DEG_S = config.MAX_TARGET_RATE_DEG_S

        # Kilitlenmeden önce adayın ard arda kaç karede aynı yerde görüldüğü.
        # Hayalet tespitleri birkaç kare sürüyor; gerçek hedef sürekli görünür.
        self._aday_ardisik = 0
        self._aday_konum = None
        # Bu iki eşik AÇISAL olguları korur, dolayısıyla derece/piksel
        # değişince yeniden ölçeklenmeleri gerekir. 3x zoomlu Logitech'te
        # (0.01783 d/px) 120 px = 2.14 derece, 250 px = 4.46 derece idi;
        # AR0234 + 12 mm lenste 1920x1080'de (0.014324 d/px) aynı açılar
        # 150 ve 311 px. Çözünürlük 1280'e düşerse ikisi de 1.5'e bölünmeli.
        self.LOCK_CONFIRM_TOL_PX = 150  # aday "aynı yerde" sayılma toleransı
        self.MAX_REACQUISITION_DISTANCE_PIXELS = 311

        # --- PID Kontrol Değişkenleri ---
        # Kazançlar ve derece/piksel artık config.py'da: saha ayarı tek dosyadan
        # yapılabilsin ve kalibrasyon aracının ürettiği değerin bir yeri olsun.
        self.KP_YAW = config.KP_YAW
        self.KI_YAW = 0.0001
        self.KD_YAW = 0.001

        self.KP_PITCH = config.KP_PITCH
        self.KI_PITCH = 0.0001
        self.KD_PITCH = 0.001

        self.pid_update_time = time.time()
        self.integral_yaw = 0.0
        self.last_error_yaw = 0.0
        # Rezonans sonumleme suzgecinin hafizasi (bkz. PID_OUTPUT_SMOOTHING)
        self._pid_cikis_yaw = 0.0
        self._pid_cikis_pitch = 0.0
        self.integral_pitch = 0.0
        self.last_error_pitch = 0.0

        self.current_pid_range = "TEK_SET"

        # --- İleri Besleme ve Tahminsel Kontrol için Değişkenler ---
        self.last_target_x = None
        self.last_target_y = None
        self.last_frame_time = None
        self.last_target_velocity_x = 0.0
        self.last_target_velocity_y = 0.0

        # Hedefin DÜNYA açısal hızı (derece/sn) — feedforward için.
        # DİKKAT: piksel hızı (last_target_velocity_*) bu iş için KULLANILAMAZ.
        # Takip çalışırken hedef karede merkeze yakın kalır, yani hedef dünyada
        # hızla kaysa bile piksel hızı sıfıra yakındır. Doğru sinyal hedefin
        # dünyadaki açısı: taret_açısı + piksel_hatasının_derece_karşılığı.
        # (Piksel hızı yeniden-edinme tahmininde kullanılmaya devam ediyor;
        #  orada görüntü uzayında olması doğru.)
        self.target_world_yaw_rate = 0.0
        self.target_world_pitch_rate = 0.0
        self._last_world_yaw = None
        self._last_world_pitch = None
        self._last_world_time = None

        # Zaman damgalı açı geçmişi (ölü zaman telafisi için). 20 Hz'de
        # 120 kayıt ~6 saniye; kamera gecikmesi bunun çok altında.
        # 50 Hz raporla ~4 sn geçmiş. Ölü zaman telafisi en fazla birkaç yüz
        # milisaniye geriye bakar, bu fazlasıyla yeterli.
        self._angle_history = deque(maxlen=200)
        self._son_aci_etiketi = 0.0
        # Yaw enkoderi (FAZ 3: yalnızca gösterim). None = Pi hiç raporlamadı.
        # {"ok": bool, "yaw": float|None, "raw": int|None}
        self._enkoder = None
        self._enkoder_kayit = None      # CSV dosya nesnesi (config.ENCODER_LOG); False = vazgeçildi
        self._enkoder_kayit_n = 0
        # Feedforward degisim hizi siniri icin onceki degerler
        self._ff_onceki_yaw = 0.0
        self._ff_onceki_pitch = 0.0
        # İşlenen karenin ÇEKİLME zamanı (time.time() değil!)
        self._capture_time = None

        # Hedefin en son GERÇEKTEN görüldüğü andaki dünya açısı. Hedef
        # kaybolduğunda tahmin bundan yürütülür; piksel uzayında tahmin
        # taretin kendi hareketini hedefin hareketi sanıyordu.
        self._son_gorulen_dunya_yaw = None
        self._son_gorulen_dunya_pitch = None
        self._son_gorulen_zaman = 0.0

        # Kalibrasyon sırasında PID askıya alınır (taret hedefi ortalamaya
        # çalışırsa ölçüm yapılamaz).
        self._calibrating = False

        # Tek komutta istenebilecek en büyük açı değişimi. Bloklayan eski Pi
        # yapısında büyük komut tehlikeliydi (uzun blok = kuyruk birikmesi);
        # pozisyon servosunda değil, bu yüzden uzak hedefe daha az çevrimde
        # ulaşmak için yükseltildi.
        self.MAX_OUTPUT_DEGREE = 15.0

        # Ölü bant ve minimum çıkış, PİKSEL cinsinden tanımlanıp dereceye
        # çevrilir. Gürültü kaynağı YOLO kutu merkezi olduğu için doğal birim
        # pikseldir; ayrıca kalibrasyon değişince kendiliğinden ölçeklenir.
        self.MIN_OUTPUT_DEGREE_THRESHOLD = (config.MIN_OUTPUT_PIXELS
                                            * abs(config.DEGREES_PER_PIXEL_YAW))
        self.pid_deadband_yaw = config.PID_DEADBAND_PIXELS * abs(config.DEGREES_PER_PIXEL_YAW)
        self.pid_deadband_pitch = config.PID_DEADBAND_PIXELS * abs(config.DEGREES_PER_PIXEL_PITCH)

        self.DEGREES_PER_PIXEL_YAW = config.DEGREES_PER_PIXEL_YAW
        self.DEGREES_PER_PIXEL_PITCH = config.DEGREES_PER_PIXEL_PITCH


        self.manual_step_size = 1.0

        # Manuel yön komutu, yön değişince gönderilir. Bu aralıkta bir de
        # "canlıyım" tekrarı gider; Pi tarafındaki watchdog bununla beslenir.
        # MANUAL_COMMAND_TIMEOUT (0.35 sn) değerinden belirgin küçük olmalı.
        self.manual_keepalive_interval = 0.1
        self._last_manual_direction = (0, 0)
        self._last_manual_send_time = 0.0

        # Açı komutları için minimum gönderme aralığı
        self.last_angle_command_send_time = time.time()
        self.angle_command_minimum_interval = 0.04

        # Ateşleme bekleme süresi
        self.last_fire_time = 0.0
        self.fire_cooldown_interval = 0.3

        # Tekrarlayan hata mesajlarını önlemek için
        self.last_status_message = ""
        self.last_status_time = 0
        self.status_message_cooldown_interval = 0.5

        print("HATA AYIKLAMA: RPiCommunicator başlatılıyor.")
        self.rpi_thread = RPiCommunicator(config.RPI_IP, config.RPI_PORT)
        self.rpi_thread.status_update_signal.connect(self._update_status_label)
        self.rpi_thread.connection_status_signal.connect(self._update_rpi_connection_status)
        self.rpi_thread.angles_update_signal.connect(self._update_current_angles)
        self.rpi_thread.encoder_update_signal.connect(self._update_encoder_state)
        self.rpi_thread.response_received_signal.connect(self._process_rpi_response)
        self.rpi_thread.start()
        print("HATA AYIKLAMA: RPiCommunicator başlatıldı.")

        print("HATA AYIKLAMA: Ana düzen ve grup kutuları oluşturuluyor.")
        # DÜZEN: üstte bilgi satırı, altında [avcı | sağ panel].
        #
        # Eskiden ana düzen tek bir QHBoxLayout'tu ve kamera etiketi
        # `addWidget(self.camera_label, 8)` ile 8 GERME PAYIYLA ekleniyordu.
        # Etiket sabit boyutlu olduğu için o pay ona hiç geçmiyor, artan alan
        # sağdaki esnek widget'lara (butonlar yatayda Expanding) dağılıyordu.
        # Avcı paneli küçültülünce butonlar açılan boşluğu doldurup sola
        # kayıyordu — sahada görülen tam olarak buydu.
        #
        # Artık germe payı yok; artan alan açıkça bir addStretch'e gidiyor,
        # yani paneller sabit kalıyor ve boşluk sağda toplanıyor.
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(12, 8, 12, 12)
        main_layout.setSpacing(10)
        main_layout.addWidget(self.info_label)

        govde_layout = QHBoxLayout()
        govde_layout.setSpacing(16)      # avci ile sag panel arasi
        # Germe payi 1: artan yatay alanin TAMAMI avci paneline gidiyor.
        govde_layout.addWidget(self.camera_label, 1)

        right_layout = QVBoxLayout()
        right_layout.setSpacing(12)      # gruplar arasi nefes payi
        right_layout.addWidget(self.spotter_label)
        right_layout.addWidget(self.spotter_info_label)
        right_layout.addSpacerItem(QSpacerItem(10, 10, QSizePolicy.Minimum, QSizePolicy.Fixed))

        right_layout.addWidget(self.status_label)
        right_layout.addWidget(self.target_info_label)
        right_layout.addSpacerItem(QSpacerItem(10, 10, QSizePolicy.Minimum, QSizePolicy.Fixed))

        # --- GÖREVLER Grup Kutusu ---
        tasks_group_box = QGroupBox("GÖREVLER")
        tasks_group_box.setStyleSheet(
            self.grup_stili())
        task_layout = QVBoxLayout()
        task_layout.setSpacing(10)

        self.task1_button = QPushButton("Aşama 1", self)
        self.task2_button = QPushButton("Aşama 2", self)
        self.task3_button = QPushButton("Aşama 3", self)
        self.takip_button = QPushButton("Hedef Takip (ateşsiz)", self)
        self.manual_control_mode_button = QPushButton("Tam Manuel Kontrol", self)

        self.apply_button_style(self.task1_button, font_size=19, padding=15)
        self.apply_button_style(self.task2_button, font_size=19, padding=15)
        self.apply_button_style(self.task3_button, font_size=19, padding=15)
        self.apply_button_style(self.takip_button, font_size=19, padding=15,
                                bg_color="#2E7D64", hover_color="#3E9C80")
        self.apply_button_style(self.manual_control_mode_button, font_size=19, padding=15)

        task_layout.addWidget(self.task1_button)
        task_layout.addWidget(self.task2_button)
        task_layout.addWidget(self.task3_button)
        task_layout.addWidget(self.takip_button)
        task_layout.addWidget(self.manual_control_mode_button)
        tasks_group_box.setLayout(task_layout)
        # GOREVLER burada EKLENMIYOR: asagida KONTROL ile yan yana konuyor.
        # Ikisi alt alta oldugunda sag panel ~1140 piksel yuksekliga
        # ulasip ekrana sigmiyordu; yan yana koyunca ~250 piksel kazaniliyor.
        right_layout.addSpacerItem(
            QSpacerItem(10, 10, QSizePolicy.Minimum, QSizePolicy.Fixed))

        # --- Aşama 3 Ayarları Grup Kutusu (YENİ) ---
        self.task3_settings_group_box = QGroupBox("Aşama 3 Ayarları")
        self.task3_settings_group_box.setStyleSheet(
            self.grup_stili())
        task3_settings_layout = QVBoxLayout()
        self.a_label = QLabel("Angajman Bölgesi A (°):")
        self.a_label.setStyleSheet("color: white; font-size: 12px;")
        self.a_input = QLineEdit(self)
        self.a_input.setPlaceholderText("örn: -30.0")
        self.a_input.setStyleSheet("color: black; background-color: white; font-size: 12px;")

        self.b_label = QLabel("Angajman Bölgesi B (°):")
        self.b_label.setStyleSheet("color: white; font-size: 12px;")
        self.b_input = QLineEdit(self)
        self.b_input.setPlaceholderText("örn: 30.0")
        self.b_input.setStyleSheet("color: black; background-color: white; font-size: 12px;")

        self.task3_start_button = QPushButton("Angajmanı Al", self)
        self.apply_button_style(self.task3_start_button, font_size=19, padding=15, bg_color="#007bff")

        task3_settings_layout.addWidget(self.a_label)
        task3_settings_layout.addWidget(self.a_input)
        task3_settings_layout.addWidget(self.b_label)
        task3_settings_layout.addWidget(self.b_input)
        task3_settings_layout.addWidget(self.task3_start_button)
        self.task3_settings_group_box.setLayout(task3_settings_layout)
        right_layout.addWidget(self.task3_settings_group_box)
        self.task3_settings_group_box.setVisible(False)

        # --- KONTROL Grup Kutusu ---
        control_group_box = QGroupBox("KONTROL")
        control_group_box.setStyleSheet(
            self.grup_stili())
        control_layout = QVBoxLayout()
        control_layout.setSpacing(10)

        self.connect_rpi_button = QPushButton('RPi Bağla', self)
        self.apply_button_style(self.connect_rpi_button, font_size=17, padding=13)
        control_layout.addWidget(self.connect_rpi_button)

        camera_buttons_layout = QHBoxLayout()
        camera_buttons_layout.setSpacing(10)
        self.start_button = QPushButton('Başlat', self)
        self.stop_button = QPushButton('Durdur', self)

        self.apply_button_style(self.start_button, font_size=17, padding=13, bg_color="#28a745",
                                hover_color="#218838", pressed_color="#1e7e34")
        self.apply_button_style(self.stop_button, font_size=17, padding=13, bg_color="#dc3545",
                                hover_color="#c82333", pressed_color="#bd2130")

        camera_buttons_layout.addWidget(self.start_button)
        camera_buttons_layout.addWidget(self.stop_button)
        control_layout.addLayout(camera_buttons_layout)

        self.stop_task_button = QPushButton('Görevi Durdur', self)
        self.fire_weapon_button = QPushButton("ATEŞ ET")

        self.apply_button_style(self.stop_task_button, font_size=17, padding=13, bg_color="#ffc107",
                                hover_color="#e0a800", pressed_color="#d39e00")
        self.apply_button_style(self.fire_weapon_button, font_size=21, padding=17, bg_color="#dc3545",
                                hover_color="#c82333", pressed_color="#bd2130")

        control_layout.addWidget(self.stop_task_button)
        control_layout.addWidget(self.fire_weapon_button)

        self.reset_angles_button = QPushButton("Açıları Sıfırla (0,0)", self)
        self.apply_button_style(self.reset_angles_button, font_size=17, padding=13, bg_color="#17a2b8",
                                hover_color="#138496", pressed_color="#117a8b")
        control_layout.addWidget(self.reset_angles_button)

        self.calibrate_button = QPushButton("Derece/Piksel Ölç", self)
        self.apply_button_style(self.calibrate_button, font_size=15, padding=11, bg_color="#6f42c1",
                                hover_color="#5a32a3", pressed_color="#4e2a8e")
        control_layout.addWidget(self.calibrate_button)

        control_group_box.setLayout(control_layout)
        # GOREVLER ve KONTROL yan yana. Genislik sag panele bolusturuluyor,
        # her iki kutu da esit pay aliyor.
        gruplar_satiri = QHBoxLayout()
        gruplar_satiri.setSpacing(14)
        gruplar_satiri.addWidget(tasks_group_box, 1)
        gruplar_satiri.addWidget(control_group_box, 1)
        right_layout.addLayout(gruplar_satiri)

        # --- Ateş Kontrolü ve Kısıtlı Bölge Ayarları Grup Kutusu ---
        self.fire_control_group_box = QGroupBox("Ateş Kontrolü ve Kısıtlı Bölge Ayarları")
        self.fire_control_group_box.setStyleSheet(
            self.grup_stili())
        fire_control_layout = QVBoxLayout()
        fire_control_layout.setSpacing(10)

        no_fire_start_layout = QHBoxLayout()
        label_no_fire_start = QLabel("Ateşsiz Bölge Başlangıç Yaw (°):")
        label_no_fire_start.setStyleSheet("color: white; font-size: 12px;")
        no_fire_start_layout.addWidget(label_no_fire_start)
        self.no_fire_start_input = QLineEdit(self)
        self.no_fire_start_input.setPlaceholderText(f"örn: -15.0")
        self.no_fire_start_input.setStyleSheet("color: black; background-color: white; font-size: 12px;")
        self.no_fire_start_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        no_fire_start_layout.addWidget(self.no_fire_start_input)
        fire_control_layout.addLayout(no_fire_start_layout)

        no_fire_end_layout = QHBoxLayout()
        label_no_fire_end = QLabel("Ateşsiz Bölge Bitiş Yaw (°):")
        label_no_fire_end.setStyleSheet("color: white; font-size: 12px;")
        no_fire_end_layout.addWidget(label_no_fire_end)
        self.no_fire_end_input = QLineEdit(self)
        self.no_fire_end_input.setPlaceholderText(f"örn: 15.0")
        self.no_fire_end_input.setStyleSheet("color: black; background-color: white; font-size: 12px;")
        self.no_fire_end_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        no_fire_end_layout.addWidget(self.no_fire_end_input)
        fire_control_layout.addLayout(no_fire_end_layout)

        no_fire_buttons_layout = QHBoxLayout()
        self.apply_no_fire_zone_button = QPushButton("Ateşsiz Bölge Uygula", self)
        self.apply_button_style(self.apply_no_fire_zone_button, font_size=15, padding=11, bg_color="#007bff",
                                hover_color="#0069d9", pressed_color="#0062cc")
        no_fire_buttons_layout.addWidget(self.apply_no_fire_zone_button)

        self.clear_no_fire_zone_button = QPushButton("Ateşsiz Bölgeyi Temizle", self)
        self.apply_button_style(self.clear_no_fire_zone_button, font_size=15, padding=11, bg_color="#6c757d",
                                hover_color="#5a6268", pressed_color="#545b62")
        no_fire_buttons_layout.addWidget(self.clear_no_fire_zone_button)
        fire_control_layout.addLayout(no_fire_buttons_layout)

        self.fire_control_group_box.setLayout(fire_control_layout)
        right_layout.addWidget(self.fire_control_group_box)
        self.fire_control_group_box.setVisible(True)

        # --- MANUEL YÖN KONTROLÜ Grup Kutusu ---
        self.direct_manual_control_group_box = QGroupBox("Doğrudan Manuel Kontrol")
        self.direct_manual_control_group_box.setStyleSheet(
            self.grup_stili())
        direct_manual_control_layout = QVBoxLayout()

        grid_layout = QVBoxLayout()

        self.up_button = QPushButton("Yukarı", self)
        self.down_button = QPushButton("Aşağı", self)
        self.left_button = QPushButton("Sol", self)
        self.right_button = QPushButton("Sağ", self)

        self.apply_button_style(self.up_button, font_size=17, padding=13)
        self.apply_button_style(self.down_button, font_size=17, padding=13)
        self.apply_button_style(self.left_button, font_size=17, padding=13)
        self.apply_button_style(self.right_button, font_size=17, padding=13)

        grid_layout.addWidget(self.up_button, alignment=Qt.AlignCenter)

        h_layout_lr = QHBoxLayout()
        h_layout_lr.addWidget(self.left_button)
        h_layout_lr.addWidget(self.right_button)
        grid_layout.addLayout(h_layout_lr)

        grid_layout.addWidget(self.down_button, alignment=Qt.AlignCenter)

        direct_manual_control_layout.addLayout(grid_layout)
        self.direct_manual_control_group_box.setLayout(direct_manual_control_layout)
        right_layout.addWidget(self.direct_manual_control_group_box)
        self.direct_manual_control_group_box.setVisible(False)

        right_layout.addSpacerItem(
            QSpacerItem(10, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))

        # Sag panel SABIT genislikte bir konteynere aliniyor. Layout'a
        # dogrudan eklenseydi icindeki butonlar (yatayda Expanding) artan
        # alani doldurup panelin genisligini pencereye gore degistirirdi.
        sag_panel = QWidget(self)
        sag_panel.setLayout(right_layout)
        sag_panel.setFixedWidth(config.UI_GOZCU_GENISLIK
                                + config.UI_SAG_PANEL_PAYI)
        govde_layout.addWidget(sag_panel, 0, Qt.AlignTop)
        # BURADA addStretch YOK: artan alani avci paneli aliyor, yoksa
        # panel kucuk kalip ekranin yarisi bos gorunuyordu.

        main_layout.addLayout(govde_layout, 1)

        self.setLayout(main_layout)
        print("HATA AYIKLAMA: Düzen ayarlandı.")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)

        self.frame_counter = 0
        # --- Görüntü yolu sayaçları (tanılama) ---
        # "Kamera açık ama ekran siyah" gibi durumlarda zincirin hangi
        # halkasında koptuğunu ekrandan görebilmek için. Konsola bakmadan
        # ayırt edilebilmeli: zamanlayıcı çalışıyor mu, sonuç geliyor mu,
        # çizim yapılıyor mu.
        self._tani = {'tik': 0, 'bos': 0, 'sonuc': 0, 'ciz': 0, 'hata': 0}
        self._tani_son_yazdirma = 0.0
        # Arka plan süreçleri (ana bloktan atanır). Canlı olup olmadıklarını
        # bilmeden "kuyruk neden boş" sorusu cevaplanamıyor: süreç ölmüşse
        # kuyruk sonsuza kadar boş kalır ve arayüzde bu hiç görünmez.
        self.surecler = {}

        self.crosshair_movable = False
        self.crosshair_fixed_center = True
        self.crosshair_x = 0
        self.crosshair_y = 0
        self.active_task = None

        self.camera_label.setMouseTracking(True)
        self.camera_label.mouseMoveEvent = self.mouse_move_event
        self.camera_label.mousePressEvent = self.mouse_press_event
        print("HATA AYIKLAMA: Kamera ve Zamanlayıcı ayarları yapılandırıldı.")

        print("HATA AYIKLAMA: Sinyaller bağlanıyor.")
        self.task1_button.clicked.connect(self.task1)
        self.task2_button.clicked.connect(self.task2)
        # Aşama 3 artık doğrudan angajmana giriyor; eski QR tabanlı ayar
        # akışı (setup_task3) kullanılmıyor.
        self.task3_button.clicked.connect(self.task3)
        self.takip_button.clicked.connect(self.hedef_takip)
        self.manual_control_mode_button.clicked.connect(self.set_full_manual_mode)
        self.start_button.clicked.connect(self.start_camera)
        self.stop_button.clicked.connect(self.stop_camera)
        self.stop_task_button.clicked.connect(self.cancel_task)
        self.fire_weapon_button.clicked.connect(self.fire_weapon)
        self.connect_rpi_button.clicked.connect(self.connect_rpi_threaded)
        self.reset_angles_button.clicked.connect(self.reset_rpi_angles)
        self.calibrate_button.clicked.connect(self.start_calibration)
        self.apply_no_fire_zone_button.clicked.connect(self.apply_no_fire_zone_settings)
        self.clear_no_fire_zone_button.clicked.connect(self.clear_no_fire_zone_settings)
        self.task3_start_button.clicked.connect(self.start_task3_engagement)

        self.movement_states = {
            'yaw_left': False,
            'yaw_right': False,
            'pitch_up': False,
            'pitch_down': False
        }
        self.manual_yaw_direction = 0
        self.manual_pitch_direction = 0

        self.manual_movement_timer = QTimer(self)
        self.manual_movement_timer.timeout.connect(self._continuously_update_motor_position)

        self.up_button.pressed.connect(lambda: self._handle_manual_button_press('pitch_up'))
        self.up_button.released.connect(lambda: self._set_movement_state('pitch_up', False))
        self.down_button.pressed.connect(lambda: self._handle_manual_button_press('pitch_down'))
        self.down_button.released.connect(lambda: self._set_movement_state('pitch_down', False))
        self.left_button.pressed.connect(lambda: self._handle_manual_button_press('yaw_left'))
        self.left_button.released.connect(lambda: self._set_movement_state('yaw_left', False))
        self.right_button.pressed.connect(lambda: self._handle_manual_button_press('yaw_right'))
        self.right_button.released.connect(lambda: self._set_movement_state('yaw_right', False))
        print("HATA AYIKLAMA: Sinyaller bağlandı.")

        QCoreApplication.instance().aboutToQuit.connect(self.close_event)
        print("HATA AYIKLAMA: HavaSavunmaArayuz başlatma tamamlandı.")

    @staticmethod
    def grup_stili():
        """
        Grup kutusu stili — tek yerde.

        Eskiden dört ayrı yerde aynı satır tekrar ediyordu ve `padding: 5px`
        ile içerik çerçeveye yapışıyordu; başlık da çerçevenin üstüne
        biniyordu (QGroupBox başlığı için `margin-top` + `subcontrol-origin`
        gerekiyor). Kenarlık saf beyazdan gri tonuna alındı: beyaz çerçeve
        siyah zeminde göze batıp içeriği bastırıyordu.
        """
        return """
            QGroupBox {
                color: #e8e8e8;
                font-size: 16px;
                font-weight: bold;
                border: 2px solid #5a5a5a;
                border-radius: 10px;
                margin-top: 14px;
                padding: 18px 14px 14px 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 14px;
                padding: 0 8px;
            }
        """

    def apply_button_style(self, button, font_size=30, padding=20, bg_color="#808080", hover_color="#A9A9A9",
                           pressed_color="#696969"):
        button.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg_color};
                color: white;
                border: 2px solid {bg_color};
                border-radius: 8px;
                padding: {padding}px;
                font-size: {font_size}px;
                font-weight: bold;
                box-shadow: 2px 2px 4px rgba(0, 0, 0, 0.5);
                width: 100%;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
                border: 2px solid {hover_color};
                box-shadow: 4px 4px 6px rgba(0, 0, 0, 0.7);
            }}
            QPushButton:pressed {{
                background-color: {pressed_color};
                border: 2px solid {bg_color};
                box-shadow: inset 2px 2px 4px rgba(0, 0, 0, 0.7);
            }}
        """)
        button.clicked.connect(button.clearFocus)

    def _update_status_label(self, message, oncelikli=False, sure=5.0):
        """
        Durum çubuğunu günceller.

        `oncelikli=True` verilen mesaj `sure` saniye boyunca EKRANDA KALIR ve
        sıradan güncellemeler onu ezemez.

        Buna ihtiyaç var çünkü `update_frame` her karede (saniyede ~25 kez)
        göreve ait bir durum metni yazıyor. Kullanıcı bir butona bastığında
        çıkan hata mesajı bir sonraki karede siliniyordu — sahada "Derece/
        Piksel Ölç'e basıyorum, hiçbir şey olmuyor" olarak görüldü; oysa
        buton "kilitli bir hedef gerekli" diyordu ve mesaj 40 ms yaşıyordu.
        """
        simdi = time.time()
        if not oncelikli and simdi < getattr(self, '_oncelikli_mesaj_bitis', 0.0):
            return
        if oncelikli:
            self._oncelikli_mesaj_bitis = simdi + sure
            self.status_label.setText(message)
            self.last_status_message = message
            self.last_status_time = simdi
            print(f"DURUM: {message}")
            return
        if message != self.last_status_message or (
                simdi - self.last_status_time > self.status_message_cooldown_interval):
            self.status_label.setText(message)
            self.last_status_message = message
            self.last_status_time = simdi

    def connect_rpi_threaded(self):
        if not self.rpi_thread.is_connected:
            self._update_status_label("Durum: Raspberry Pi'ye bağlanılıyor...")
            if not self.rpi_thread.isRunning():
                self.rpi_thread.start()
        else:
            self._update_status_label("Durum: Zaten Raspberry Pi'ye bağlı.")

    def _update_rpi_connection_status(self, is_connected):
        self.rpi_connection_status = is_connected
        if is_connected:
            self.connect_rpi_button.setEnabled(False)
            self._update_status_label("Durum: Raspberry Pi'ye Bağlandı!")
        else:
            self.connect_rpi_button.setEnabled(True)
            self._update_status_label("Durum: Raspberry Pi bağlantısı kesildi.")

    def _angle_at(self, t):
        """
        Verilen ZAMANDAKİ taret açısını döndürür.

        Bu, ölü zaman telafisinin çekirdeği: piksel hatası kamera karesinin
        ÇEKİLDİĞİ anda geçerliydi, taret o zamandan beri hareket etti. Hatayı
        o andaki açıya eklemek hedefin dünyadaki gerçek açısını verir.
        Geçmiş yoksa mevcut açıya düşülür (eski davranış).

        Açı raporu ayrık aralıklarla gelir; aradaki anlar ARADEĞERLENİR.
        Eskiden en yakın önceki kayıt olduğu gibi döndürülüyordu (sıfırıncı
        derece tutma) ve bu, örnekleme aralığının yarısı kadar sistematik bir
        gecikme bırakıyordu. Taret dönerken bu gecikme doğrudan açı hatasına,
        o da hedefin dünya açısında sahte bir kaymaya dönüşüyordu. Kare kare
        türevi alındığında ortaya taret hızıyla orantılı, tamamen sahte bir
        "hedef hızı" çıkıyor ve feedforward onu kovalıyordu.

        Sahada ölçüldü (ekran kaydından, hedef GERÇEKTEN sabitken):
          - oturmuş ama mikro hareketli taret : sahte hedef hızı 8.1 derece/sn
          - salınım fazı                      : sahte hedef hızı 14.4 derece/sn
        Elde gezdirilen balonun gerçek hızı 5-15 derece/sn olduğu için gürültü
        sinyal kadar büyüktü; feedforward'ı açmak bu yüzden işleri kötüleştiriyordu.
        """
        if not self._angle_history:
            return self.current_yaw_angle, self.current_pitch_angle
        onceki = None
        for kayit in self._angle_history:
            if kayit[0] <= t:
                onceki = kayit
            else:
                if onceki is None:
                    return kayit[1], kayit[2]        # t geçmişin başından eski
                araligi = kayit[0] - onceki[0]
                if araligi <= 0:
                    break
                w = (t - onceki[0]) / araligi
                return (onceki[1] + w * (kayit[1] - onceki[1]),
                        onceki[2] + w * (kayit[2] - onceki[2]))
        if onceki is None:
            return self.current_yaw_angle, self.current_pitch_angle
        return onceki[1], onceki[2]                  # t geçmişin sonundan yeni

    def _hiz_alfa(self, ham, mevcut):
        """
        Hız yumuşatma katsayısını duruma göre seçer.

        Tek bir katsayı iki çelişen ihtiyaca hizmet edemiyor:

          - SABİT hedefte hız tahmini saf gürültüdür. Yavaş yumuşatma (0.3)
            gerekir; hızlısı (0.5-0.6) gürültüyü feedforward'a geçirir ve
            taret hedefe oturmak yerine ufak salınımlar yapar.
          - HAREKETLİ hedefte el hareketi sabit hızlı değil, sürekli
            İVMELENİYOR. Yavaş yumuşatma 2-3 kare (80-120 ms) geriden gelir,
            feedforward hep bir önceki hızı telafi eder ve nişangah kutunun
            kenarında kalır. Hızlı yumuşatma bunu kapatır.

        Bu yüzden katsayı hızın BÜYÜKLÜĞÜNE göre seçiliyor: eşiğin üstünde
        sinyal gürültüden baskındır, altında değildir. Sönme (hız azalma)
        durumu her iki halde de en hızlı katsayıyı kullanır — hedef durduğunda
        feedforward'ın anında kesilmesi gerekiyor, yoksa taret hedefi aşıyor.
        """
        if abs(ham) < abs(mevcut):
            return config.VELOCITY_DECAY_SMOOTHING
        if abs(ham) >= config.VELOCITY_FAST_THRESHOLD:
            return config.VELOCITY_FAST_SMOOTHING
        return config.VELOCITY_SMOOTHING

    def _tahmin_hizi(self):
        """
        Hedef KAYBOLDUGUNDA kullanilacak hiz; feedforward'inkinden dar sinirli.

        Feedforward olculen hizi kullanir ve hedef o sirada GORUNURDUR.
        Kayipta ise korlemesine ekstrapolasyon yapilir; hatali bir hiz tahmini
        hayali hedefi uzaga kacirir (80 derece/sn x 5 kare = 16 derece).
        Bu yuzden iki sinir ayri tutuluyor.
        """
        r = config.PREDICTION_MAX_RATE_DEG_S
        return (max(-r, min(r, self.target_world_yaw_rate)),
                max(-r, min(r, self.target_world_pitch_rate)))

    def _piksel_to_dunya(self, px, py, zaman):
        """
        Bir piksel konumunu hedefin DÜNYA açısına çevirir.

        Kare çekildiğindeki taret açısı kullanılır; böylece sonuç taretin
        hareketinden bağımsızdır. Sabit bir hedefin dünya açısı, taret ne kadar
        dönerse dönsün değişmez — tahmin bu yüzden dünya uzayında yapılmalıdır.
        """
        yaw_cap, pitch_cap = self._angle_at(zaman)
        dunya_yaw = yaw_cap + (px - self.frame_orig_w // 2) * self.DEGREES_PER_PIXEL_YAW
        dunya_pitch = pitch_cap + (py - self.frame_orig_h // 2) * self.DEGREES_PER_PIXEL_PITCH
        return dunya_yaw, dunya_pitch

    def _dunya_to_piksel(self, dunya_yaw, dunya_pitch, zaman):
        """
        Dünya açısını piksel konumuna çevirir.

        DİKKAT: Dönüşüm, KARENİN ÇEKİLDİĞİ andaki taret açısını kullanmak
        ZORUNDA. Bir karedeki piksel konumu, o kare çekilirken taretin nerede
        olduğunu yansıtır. Burada "şu anki" açıyı kullanmak, process_tracking'in
        aynı pikseli çekilme anındaki açıyla yorumlamasıyla çelişir; aradaki
        fark (gecikme boyunca dönülen açı) her çevrimde tahmine eklenir, hız
        tahminini büyütür ve tahmin katlanarak patlar. Sahada bu, hatanın
        149 px'den 2093 px'e, oradan 3.541.501 px'e fırlaması olarak görüldü.
        """
        yaw_ref, pitch_ref = self._angle_at(zaman)
        px = (self.frame_orig_w // 2
              + (dunya_yaw - yaw_ref) / self.DEGREES_PER_PIXEL_YAW)
        py = (self.frame_orig_h // 2
              + (dunya_pitch - pitch_ref) / self.DEGREES_PER_PIXEL_PITCH)
        return px, py

    # ================= GÖZCÜ / ANGAJMAN =================

    def _gozcu_oku(self):
        """Gözcü sürecinden gelen son sonucu al (bayat olanları atarak)."""
        if self.spotter_result_q is None:
            return
        son = None
        while True:
            try:
                son = self.spotter_result_q.get_nowait()
            except queue.Empty:
                break
        if son is None:
            return
        if 'hata' in son:
            self.spotter_info_label.setText(f"Gözcü HATA: {son['hata']}")
            return
        self.gozcu_izler = son.get('izler', [])
        self.gozcu_zamani = son.get('zaman', time.time())
        self.gozcu_indeks = son.get('indeks')
        if 'onizleme' in son:
            self.gozcu_onizleme = (son['onizleme'], son.get('onizleme_olcek', 1.0))
            # Bloklar onizleme ile BIRLIKTE geliyor; ayni karenin
            # goruntusu ve bloblari eslesik kalsin diye burada guncelleniyor.
            self.gozcu_bloklari = son.get('bloklar', [])

    def _gozcu_ciz(self):
        """
        Gözcü önizlemesini izlerle VE ham bloblarla birlikte çiz.

        Görsel dil:
          kalın daire      -> AKTİF İZ. Aday sayıldı, taret buraya gidebilir.
                              Rengi sınıfı verir (kırmızı düşman, mavi dost,
                              sarı kararsız).
          ince kırmızı kutu-> kırmızı blob, balon kapısından GEÇEMEDİ.
                              Yanında elenme sebebi yazılı.
          ince mavi kutu   -> mavi blob. Gözcü maviyi görüyor ama mavi
                              HİÇBİR ZAMAN aday üretmez (bkz.
                              `spotter_module.gosterim_bloklari`).

        Bloblar YALNIZCA GÖSTERİM. Hedef seçimi ve taret yönlendirmesi
        yalnızca izlere bakar; bu çizim onlara hiç dokunmaz.
        """
        if self.gozcu_onizleme is None:
            return
        kare, olcek = self.gozcu_onizleme
        kare = kare.copy()
        yuk, gen = kare.shape[:2]

        # Önce ham bloblar (arkada kalsınlar), sonra izler.
        for blok in self.gozcu_bloklari:
            x = int(blok['x'] * olcek)
            y = int(blok['y'] * olcek)
            w = max(2, int(blok['w'] * olcek))
            h = max(2, int(blok['h'] * olcek))
            if blok['renk'] == 'mavi':
                # Etiket YOK: kutunun rengi zaten "mavi blob" diyor. Metin
                # yazmak yandaki kırmızı maketin sebebiyle üst üste biniyor.
                renk, etiket = (255, 150, 40), ''
            elif blok['aday']:
                # Bu blob zaten iz olarak daireyle çizilecek; kutusu ince kalsın.
                renk, etiket = (0, 220, 220), ''
            else:
                # Elenme sebebi kısaltılıyor: önizleme 480 px geniş, uzun
                # metin komşu blobun üstüne taşıyor.
                renk = (90, 90, 235)
                etiket = blok['ret'].replace('dolgunluk', 'dolg').replace('en/boy', 'oran')
            cv2.rectangle(kare, (x, y), (x + w, y + h), renk, 1)
            if etiket:
                cv2.putText(kare, etiket, (x, max(8, y - 3)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.28, renk, 1)

        for iz in self.gozcu_izler:
            # Açıdan piksele geri dönüş (önizleme ölçeğinde)
            px = int(gen / 2 + (iz['yaw'] - config.SPOTTER_YAW_OFFSET)
                     / config.SPOTTER_DPP_YAW * olcek)
            py = int(yuk / 2 + (iz['pitch'] - config.SPOTTER_PITCH_OFFSET)
                     / config.SPOTTER_DPP_PITCH * olcek)
            renk = {'dusman': (0, 0, 255), 'dost': (255, 120, 0)}.get(
                iz['sinif'], (0, 200, 255))
            cv2.circle(kare, (px, py), 10, renk, 2)
            cv2.putText(kare, f"{iz['yaw']:+.0f}", (px + 12, py + 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, renk, 1)
        cv2.line(kare, (gen // 2 - 8, yuk // 2), (gen // 2 + 8, yuk // 2), (0, 255, 0), 1)
        cv2.line(kare, (gen // 2, yuk // 2 - 8), (gen // 2, yuk // 2 + 8), (0, 255, 0), 1)
        rgb = cv2.cvtColor(kare, cv2.COLOR_BGR2RGB)
        img = QImage(rgb.data, gen, yuk, 3 * gen, QImage.Format_RGB888)
        self.spotter_label.setPixmap(QPixmap.fromImage(img).scaled(
            self.spotter_label.width(), self.spotter_label.height(),
            Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _nisan_tespiti(self, cift, maket_merkezine=False):
        """
        Hedef çiftinden PID'in kullanacağı sanal bir tespit üretir.

        Balon varsa oraya nişan alınır. Balon 15 metrede avcıda yalnızca 30
        piksel — YOLO için küçük-nesne sınırı. Tespit zayıfladığında nişan
        noktası maketten türetilir; bu geçiş `balon_gercek_goruldu` ile
        işaretlenir ve ATEŞ kilidi gerçek balon görülmeden ateşe izin vermez.

        TÜRETME ARTIK ÖLÇÜME DAYANIYOR. Balon her görüldüğünde maket
        kutusuna göre bağıl konumu öğreniliyor (`nisan_ofsetini_ogren`) ve
        balon kaybolduğunda sabit `PAIR_FALLBACK_AIM_OFFSET` formülü yerine
        o ölçüm kullanılıyor. Sabit formül sahada balon merkezinin 25-34
        piksel yukarısına düşüyordu ve her kaynak değişimi saf bir pitch
        sıçraması üretiyordu — kilit salınımının kök nedeni buydu.

        `kaynak_bbox`: nişan noktasını üreten GERÇEK tespitlerin kutuları.
        Çizim bunları kullanıyor; sanal kutu hiçbir tespitin bbox'ı olmadığı
        için "kilitli hedef kırmızı" kuralı eskiden hiç tutmuyordu.
        """
        self.angajman.nisan_ofsetini_ogren(cift)
        nokta = cift.nisan_noktasi(
            ogrenilen_ofset=self.angajman.nisan_ofseti,
            maket_merkezine=maket_merkezine)
        if nokta is None:
            return None
        cx, cy, yaricap, gercek = nokta
        self.balon_gercek_goruldu = gercek
        yaricap = max(4.0, yaricap)
        kaynak = []
        if cift.balon is not None:
            kaynak.append(tuple(int(v) for v in cift.balon['bbox']))
        if cift.maket is not None:
            kaynak.append(tuple(int(v) for v in cift.maket['bbox']))
        return {
            'bbox': (int(cx - yaricap), int(cy - yaricap),
                     int(2 * yaricap), int(2 * yaricap)),
            'class_name': cift.sinif or config.BALLOON_CLASS,
            'score': cift.guven,
            'yaricap': yaricap,
            'kaynak_bbox': kaynak,
            'nisan_bbox': (tuple(int(v) for v in cift.balon['bbox'])
                           if cift.balon is not None else None),
        }

    @staticmethod
    def _guvene_gore_ayikla(liste):
        """
        Aday havuzunu GÜVENE göre ayıklar.

        Eski kural yalnızca "kareye en yakın" idi ve güveni hiç dikkate
        almıyordu; sahada tavandaki hayalet (0.66) tam merkezde olduğu için
        gerçek balonu (0.81) yenmişti. Belirgin şekilde daha güvenli bir
        tespit varsa, zayıf olanlar yarışa hiç girmiyor.
        """
        if not liste:
            return liste
        en_iyi = max(d['score'] for d in liste)
        esik = en_iyi - config.ACQUIRE_CONFIDENCE_MARGIN
        return [d for d in liste if d['score'] >= esik]

    def _takip_hedefi_sec(self, ciftler):
        """
        Hedef Takip modunda takip edilecek çifti seçer — SÜREKLİLİKLE.

        Eskiden burada doğrudan `ciftler[0]` (kare merkezine en yakın çift)
        kullanılıyordu ve seçim her karede sıfırdan yapılıyordu. Sahada
        ölçüldü (asama2-3-hedefTakip.mp4, kare 825): merkeze yaklaşan bir
        hayalet tespit yüzünden nişan hatası TEK KAREDE 400 piksel sıçradı,
        sonraki karede 0'a döndü. PID'e giren bu sıçrama taret sarsıntısına
        dönüşüyordu.

        Artık bir hedef seçildikten sonra, ONA EN YAKIN çift tercih ediliyor;
        hedef yalnızca gerçekten kaybolduğunda (yakınında hiçbir çift
        kalmadığında) yenisi seçiliyor.
        """
        if not ciftler:
            return None

        def nokta(cift):
            n = cift.nisan_noktasi(maket_merkezine=True)
            return None if n is None else (n[0], n[1])

        onceki = getattr(self, '_takip_hedef_kimlik', None)
        if onceki is not None:
            en_iyi, en_kisa = None, float('inf')
            for c in ciftler:
                p = nokta(c)
                if p is None:
                    continue
                d = ((p[0] - onceki[0]) ** 2 + (p[1] - onceki[1]) ** 2) ** 0.5
                if d < en_kisa:
                    en_iyi, en_kisa = c, d
            # Eşik kare genişliğinin oranı: çözünürlükten bağımsız kalsın.
            if en_iyi is not None and en_kisa <= config.TRACK_REACQUIRE_PIXELS:
                self._takip_hedef_kimlik = nokta(en_iyi)
                return en_iyi

        secim = next((c for c in ciftler if nokta(c) is not None), None)
        self._takip_hedef_kimlik = nokta(secim) if secim is not None else None
        return secim

    def _ciftleri_sirala(self, detections, merkez_x, merkez_y, tek_balon=False):
        """Tespitlerden çiftleri kurup kare merkezine yakınlığa göre sıralar."""
        ciftler = engagement.cift_eslestir(detections, tek_balonlara_izin=tek_balon)

        def uzaklik(c):
            kaynak = c.balon if c.balon is not None else c.maket
            if kaynak is None:
                return float('inf')
            x, y, w, h = kaynak['bbox']
            return ((x + w / 2 - merkez_x) ** 2 + (y + h / 2 - merkez_y) ** 2) ** 0.5

        return sorted(ciftler, key=uzaklik)

    def _cift_acilari(self, ciftler):
        """
        Her hedef çiftinin nişan noktasının GÖVDE çerçevesindeki dünya açısı.

        Durum makinesi kara listeyi bu çerçevede tutuyor; avcının gördüğü bir
        çifte doğrudan angaje olup olamayacağına karar verebilmek için çiftin
        piksel konumunun açıya çevrilmesi gerekiyor. Dönüşüm KARE ÇEKİLME
        anındaki taret açısını kullanır — "şu anki" açıyla yapılırsa taretin
        dönüşü hedefin hareketi sanılır (bu hata daha önce tahmin patlamasına
        yol açmıştı).
        """
        zaman = self._capture_time or time.time()
        acilar = []
        for cift in ciftler:
            nokta = cift.nisan_noktasi()
            if nokta is None:
                acilar.append(None)
                continue
            acilar.append(self._piksel_to_dunya(nokta[0], nokta[1], zaman))
        return acilar

    def _angajman_adimi(self, ciftler, acilar=()):
        """
        Durum makinesini bir adım ilerletir.

        HER KAREDE çağrılır (bkz. `update_frame`). Eskiden yalnızca "hedef
        edinme" dalından çağrılıyordu; hedefe kilitlenir kilitlenmez o dal
        devre dışı kalıyor ve makine DOĞRULAMA'da donuyordu — KİLİT'e hiç
        geçilemediği için `kilit_adimi` de, ATEŞ de erişilemezdi.

        Ayrıca otonom aşamalarda DURUM ÇUBUĞUNUN TEK YAZARIDIR: her durum
        için bir metin yazar, böylece `update_frame` sonundaki genel
        "Durum: Hazır." yazısı otonom aşamalara hiç dokunmaz.

        Döner: PID'e verilecek sanal tespit (veya None). TARAMA/YÖNELME
        durumlarında taret gözcünün verdiği MUTLAK açıya gider; bu açı gövde
        çerçevesinde olduğu için taretin mevcut konumundan bağımsızdır.
        """
        m = self.angajman
        if m.durum == TARAMA:
            # ÖNCE AVCI. Elimizdeki karede angaje edilebilir bir çift varsa
            # gözcüye hiç gidilmez; ister bunu açıkça söylüyor ve sahada
            # tersinin bedeli ölçüldü (taret gördüğü hedefin yanından geçip
            # boş açıya gitti).
            secim = m.tarama_adimi(self.gozcu_izler, ciftler, acilar)
            if m.durum == DOGRULAMA:
                self._update_status_label(
                    f"Durum: Avcı hedefi zaten görüyor "
                    f"({ciftler[0].sinif}), doğrulanıyor...")
                return self._nisan_tespiti(ciftler[0])
            if secim is None:
                self._update_status_label(
                    f"Durum: TARAMA — gözcüde uygun aday yok "
                    f"({len(self.gozcu_izler)} iz).")
                return None
            yaw, pitch = secim
            self.send_angle_command(yaw, pitch + config.BALLISTIC_PITCH_OFFSET,
                                    force=True)
            self._update_status_label(
                f"Durum: Aday seçildi, yöneliniyor: {yaw:+.1f}°, {pitch:+.1f}°")
            return None

        if m.durum == YONELME:
            if not m.yonelme_adimi(self.current_yaw_angle, self.current_pitch_angle):
                # Taret henüz oturmadı; hedefi yeniden komut etmeye gerek yok
                # (pozisyon servosu son hedefi zaten tutuyor).
                if m.durum == YONELME and m.hedef_yaw is not None:
                    self._update_status_label(
                        f"Durum: YÖNELME — {m.hedef_yaw:+.1f}°, {m.hedef_pitch:+.1f}° "
                        f"(şu an {self.current_yaw_angle:+.1f}°, "
                        f"{self.current_pitch_angle:+.1f}°)")
                return None
            self._update_status_label("Durum: Taret yerleşti, doğrulanıyor...")
            return None

        if m.durum == DOGRULAMA:
            sonuc = m.dogrulama_adimi(ciftler)
            if sonuc is not None and engagement.dost_mu(sonuc):
                self.target_info_label.setText(
                    f"Hedef Bilgisi: DOST ({sonuc}) — atlanıyor.")
                self._update_status_label("Durum: Dost tespit edildi, sıradaki adaya geçiliyor.")
            elif sonuc is not None:
                self.target_info_label.setText(f"Hedef Bilgisi: DÜŞMAN ({sonuc}).")
            else:
                self._update_status_label(
                    f"Durum: DOĞRULAMA — {len(ciftler)} çift görülüyor "
                    f"({m.gecen():.1f}/{config.ENGAGE_VERIFY_TIMEOUT:.1f} sn)")
            # Doğrulama sırasında da nişan almaya devam et: çift varsa PID
            # onu ortalasın, böylece KİLİT'e geçince zaten yakınız.
            if ciftler:
                return self._nisan_tespiti(ciftler[0])
            return None

        if m.durum in (KILIT, ATES):
            # Hedef seçimi durum makinesinde: doğrulanan sınıfla eşleşen
            # maketli çift, yoksa son kilit açısına çok yakın YALNIZ BALON
            # (köprü), o da yoksa hedef yok.
            #
            # ESKİDEN burada "eşleşen yoksa merkeze en yakın çifte düş" vardı.
            # O çift DOSTUN çifti olabiliyordu: taret dostu ortalamaya başlıyor,
            # ateş kilidi kestiği için KİLİT<->ATEŞ arasında gidip geliyor ve
            # gerçek düşmandan uzaklaşıyordu. Artık eşleşme yoksa hedef yok.
            secili, kopruden = m.kilit_hedefi_sec(ciftler, acilar)
            if secili is None:
                self._update_status_label(
                    f"Durum: {m.durum} — hedef bu karede yok "
                    f"({len(ciftler)} kayıt, imha {m.imha_sayisi})")
                self.aktif_cift = None
                return None
            # Nişan durumu ve balon görünürlüğü de yazılıyor: otonom modda
            # durum çubuğunun tek yazarı burası, operatörün "neden ateş
            # etmiyor" sorusunu ekrandan yanıtlayabilmesi gerekiyor.
            _bal = "balon VAR" if self.balon_gercek_goruldu else "BALON YOK"
            _nis = "nişan TAMAM" if self.is_aimed_at_target else "nişan bekliyor"
            self._update_status_label(
                f"Durum: {m.durum} — {m.dogrulanan_sinif or '?'}"
                f"{' [köprü]' if kopruden else ''} | {_bal} | {_nis} "
                f"({len(ciftler)} kayıt, imha {m.imha_sayisi})")
            self.aktif_cift = secili
            return self._nisan_tespiti(secili)

        return None

    def _otonom_hedefi_benimse(self, sanal, kare_zamani):
        """
        Durum makinesinin seçtiği sanal hedefi PID'in takip hedefi yapar.

        Otonom aşamalarda hedefin TEK kaynağı budur. Eski akışta hedef bir kez
        kilitlendikten sonra "YOLO takip" dalı devralıyordu; o dal hedefi
        SINIF ADIYLA yeniden buluyor, `_nisan_tespiti` ise balonun üstüne
        nişan alıp kutuya MAKETİN sınıf adını yazıyor. Sonuç: takip dalı maket
        kutusunu buluyor ve taret balona değil maketin kendisine nişan alıyordu.

        Döner: PID'e verilecek kutu, veya zamansal onay tamamlanmadıysa None.
        """
        bbox = sanal['bbox']
        cx = bbox[0] + bbox[2] // 2
        cy = bbox[1] + bbox[3] // 2

        if self.current_tracked_target_class is None:
            # İlk kilit: hayalet tespite karşı zamansal onay. Sahada tavandaki
            # hayalet (0.66) gerçek balondan (0.44) yüksek güvenle çıkmıştı ve
            # yalnızca 2 kare sürmüştü.
            if (self._aday_konum is not None
                    and abs(cx - self._aday_konum[0]) <= self.LOCK_CONFIRM_TOL_PX
                    and abs(cy - self._aday_konum[1]) <= self.LOCK_CONFIRM_TOL_PX):
                self._aday_ardisik += 1
            else:
                self._aday_ardisik = 1
            self._aday_konum = (cx, cy)
            if self._aday_ardisik < config.LOCK_CONFIRM_FRAMES:
                self._update_status_label(
                    f"Durum: Aday hedef doğrulanıyor "
                    f"({self._aday_ardisik}/{config.LOCK_CONFIRM_FRAMES})...")
                return None
            self._aday_ardisik = 0
            self._aday_konum = None
            self.reset_pid_state()
            self.last_target_velocity_x = 0.0
            self.last_target_velocity_y = 0.0
        elif self.last_target_x is not None and self.last_frame_time is not None:
            dt = kare_zamani - self.last_frame_time
            if dt > 0:
                self.last_target_velocity_x = (cx - self.last_target_x) / dt
                self.last_target_velocity_y = (cy - self.last_target_y) / dt

        self.current_tracked_target_class = sanal['class_name']
        self.current_tracked_target_bbox = bbox
        self.target_destroyed = False
        self.waiting_for_new_engagement_command = False
        self.target_lost_time = 0.0
        self.missing_frames = 0
        self.last_target_x = cx
        self.last_target_y = cy
        self.last_frame_time = kare_zamani

        # GERÇEK tespitin dünya açısı; hedef bir kare kaybolursa tahmin
        # bundan yürütülür (piksel uzayında değil — taretin kendi dönüşü
        # hedefin hareketi sanılmasın).
        self._son_gorulen_dunya_yaw, self._son_gorulen_dunya_pitch = \
            self._piksel_to_dunya(cx, cy, self._capture_time or kare_zamani)
        self._son_gorulen_zaman = kare_zamani
        return bbox

    def _otonom_ates_denemesi(self):
        """
        ATEŞ durumundaysa kilitleri kontrol edip ateşler, sonra İMHAYI DOĞRULAR.

        Eski kodda Aşama 3, TAHMİN EDİLMİŞ (görülmemiş) hedefe ateş
        edebiliyordu; `balon_gercek_goruldu` ve maket kontrolü bunu kapatır.

        İMHA DOĞRULAMASI: ateş komutu artık hedefi doğrudan imha saymıyor.
        Sahada ölçüldü — ateşten sonra hedef 12 saniye kara listeye giriyor
        ve balon patlamamış olsa bile sistem onu görmezden geliyordu. Artık
        ateşin ardından bir doğrulama penceresi açılıyor: balon kaybolduysa
        imha onaylanır, hâlâ duruyorsa aynı hedefe yeniden ateş edilir.
        """
        if self.angajman.durum != ATES:
            return

        # --- Ateş edilmiş, doğrulama penceresi açık mı? ---
        if self.angajman.ates_sayisi > 0:
            sonuc = self.angajman.ates_dogrulama_adimi(self.balon_gercek_goruldu)
            if sonuc == 'bekle':
                self._update_status_label(
                    f"Durum: ATEŞ — imha doğrulanıyor "
                    f"({self.angajman.ates_sayisi}. atış)")
                return
            if sonuc == 'onaylandi':
                self._update_status_label(
                    f"Durum: İMHA DOĞRULANDI — balon kayboldu "
                    f"({self.angajman.ates_sayisi} atış)")
                self.angajman.imha_edildi()
                self.aktif_cift = None
                return
            if sonuc == 'pes':
                self._update_status_label(
                    f"Durum: Balon duruyor ama atış bütçesi doldu "
                    f"({config.FIRE_MAX_ATTEMPTS}) — sıradaki hedefe.")
                self.angajman.imha_edilemedi()
                self.aktif_cift = None
                return
            # 'tekrar': balon hâlâ orada, aşağıdaki ateş yoluna düşülür.

        izin, gerekce = engagement.ates_serbest_mi(
            self.aktif_cift, self.angajman, self.balon_gercek_goruldu,
            self.is_aimed_at_target, self.current_yaw_angle,
            self.no_fire_yaw_start, self.no_fire_yaw_end)
        if not izin:
            if self.angajman.ates_sayisi > 0:
                # Zaten ateş edilmiş ve pencere 'tekrar' demişti, ama ateş
                # kilidi izin vermiyor. Bu kareleri SAY: eşiği aşarsa hedef
                # bırakılır. Bu sayaç olmadan sistem burada sonsuza kadar
                # takılıyordu (18. bölüm: 20 saniyelik kilitlenme).
                if self.angajman.ates_engellendi():
                    self._update_status_label(
                        f"Durum: Ateş açılamıyor ({gerekce}) — hedef bırakılıyor.")
                    self.angajman.imha_edilemedi()
                    self.aktif_cift = None
                    return
                self._update_status_label(
                    f"Ateş engellendi: {gerekce} "
                    f"({self.angajman.ates_engel_ardisik}/"
                    f"{config.FIRE_RETRY_GIVEUP_FRAMES})")
                return
            self._update_status_label(f"Ateş engellendi: {gerekce}")
            if self.angajman.gecen() > 1.5:
                self.angajman._gec(KILIT)
            return

        self.send_command_to_rpi({"action": "fire"})
        self.last_fire_time = time.time()
        self.angajman.ates_kaydet()
        self._update_status_label(
            f"Durum: ATEŞ — {self.aktif_cift.sinif} "
            f"({self.angajman.imha_sayisi + 1}. hedef, "
            f"{self.angajman.ates_sayisi}. atış)")

    def _update_current_angles(self, yaw, pitch):
        self.current_yaw_angle = yaw
        self.current_pitch_angle = pitch
        # Ölü zaman telafisi için açı geçmişi (PC saati ile damgalanır;
        # kamera karesinin zaman damgası da aynı saatten gelir).
        self._angle_history.append((time.time(), yaw, pitch))
        # Etiket güncellemesi kısıtlanıyor: açı raporu 50 Hz'e çıkarıldı ve her
        # örnekte Qt etiketi yenilemek boşuna yük. Geçmiş tam hızda tutuluyor,
        # sadece görsel yenileme ~15 Hz'e iniyor.
        simdi = time.time()
        if simdi - self._son_aci_etiketi >= 0.066:
            self._son_aci_etiketi = simdi
            self._bilgi_panelini_yenile()

    def _update_encoder_state(self, d):
        """Pi'den gelen enkoder raporu. Kontrole karışmaz; panelde gösterilir,
        sağlık değişince durum çubuğunda bir kez uyarır."""
        onceki = self._enkoder
        self._enkoder = d
        self._enkoder_kaydet(d)
        if onceki is not None and onceki.get("ok") and not d.get("ok"):
            self._update_status_label("Uyarı: yaw ENKODERİ veri vermiyor (kablo/güç?). Sistem adım sayacıyla devam ediyor.")
        elif (onceki is None or not onceki.get("ok")) and d.get("ok"):
            self._update_status_label("Durum: yaw enkoderi bağlandı.")

    def _enkoder_kaydet(self, d):
        """FAZ 4 kaydı: adım sayacı ve enkoder yan yana, her raporda bir satır.
        Dosya ilk raporda açılır; hata olursa kayıt sessizce kapanır, arayüz
        etkilenmez."""
        if not getattr(config, "ENCODER_LOG", False) or self._enkoder_kayit is False:
            return
        try:
            if self._enkoder_kayit is None:
                os.makedirs(config.ENCODER_LOG_DIR, exist_ok=True)
                yol = os.path.join(config.ENCODER_LOG_DIR,
                                   time.strftime("enkoder_%Y%m%d_%H%M%S.csv"))
                self._enkoder_kayit = open(yol, "w", encoding="utf-8")
                self._enkoder_kayit.write("t,sayac_yaw,sayac_pitch,enk_yaw,enk_ok,enk_ham\n")
                print(f"Enkoder kaydı: {yol}")
            ey = d.get("yaw")
            ham = d.get("raw")
            self._enkoder_kayit.write(
                f"{time.time():.3f},{self.current_yaw_angle:.3f},{self.current_pitch_angle:.3f},"
                f"{'' if ey is None else format(float(ey), '.3f')},{int(bool(d.get('ok')))},"
                f"{'' if ham is None else ham}\n")
            self._enkoder_kayit_n += 1
            if self._enkoder_kayit_n % 50 == 0:
                self._enkoder_kayit.flush()
        except Exception as e:
            print(f"Enkoder kaydı durdu: {e}")
            try:
                self._enkoder_kayit.close()
            except Exception:
                pass
            self._enkoder_kayit = False

    def _process_rpi_response(self, response_data):
        if response_data.get("status") == "ok":
            if response_data.get("action") == "fire":
                print("Ateşleme Başarılı!")
                # OTONOM MODLARDA `target_destroyed` BURADA SET EDİLMEZ.
                # Pi'nin "ateş komutu çalıştı" yanıtı, balonun patladığı
                # anlamına gelmiyor — o kararı imha doğrulama penceresi
                # veriyor (`ates_dogrulama_adimi`). Burada bayrağı kaldırmak
                # iki şeyi birden bozuyordu: servolama koşulu
                # `not self.target_destroyed` olduğu için taret doğrulama
                # penceresi boyunca hedefi bırakıyor, ve `reset_pid_state()`
                # tam da ikinci atış gerekebilecek anda kilidi sıfırlıyordu.
                if self.active_task in self.OTONOM_MODLAR:
                    self._update_status_label("Durum: Ateşleme başarılı, imha doğrulanıyor...")
                elif self.active_task == 'task1':
                    self.target_destroyed = True
                    self.waiting_for_new_engagement_command = True
                    self._update_status_label("Durum: Hedef yok edildi. Yeni angajman bekleniyor...")
                    self.target_info_label.setText("Hedef Bilgisi: Yok Edildi.")
                    self.reset_pid_state()
                else:
                    self._update_status_label("Durum: Ateşleme Başarılı!")
            elif response_data.get("action") == "reset_angles":
                self._update_status_label("Durum: Taret açıları Raspberry Pi'de (0,0) olarak sıfırlandı.")
                self.update_info_panel("Taret açıları sıfırlandı: Yaw 0.0°, Pitch 0.0°")
                self.reset_pid_state()
            elif response_data.get("action") == "test_motor_movement":
                self._update_status_label(f"Durum: Motor Testi: {response_data.get('message')}")
        else:
            error_message = response_data.get('message', 'Bilinmeyen Hata')
            self._update_status_label(f"Hata: RPi yanıtı: {error_message}")

    def send_command_to_rpi(self, command_dict):
        if self.rpi_thread.is_connected:
            self.rpi_thread.command_queue.put(command_dict)
            return True
        else:
            self._update_status_label("Hata: Raspberry Pi'ye bağlı değil, komut gönderilemedi.")
            return False

    def send_proportional_move_command(self, delta_yaw, delta_pitch):
        if not self.rpi_thread.is_connected:
            self._update_status_label(
                "Hata: Raspberry Pi'ye bağlı değil, orantılı hareket komutu gönderilemedi.")
            return False

        current_time = time.time()
        if current_time - self.last_angle_command_send_time < self.angle_command_minimum_interval:
            return False

        command = {"action": "set_proportional_angles_delta", "delta_yaw": delta_yaw, "delta_pitch": delta_pitch}
        self.last_angle_command_send_time = current_time
        return self.send_command_to_rpi(command)

    def start_camera(self):
        try:
            self.camera_cmd_q.put("START")
            self.inference_cmd_q.put({"action": "START"})
            if self.spotter_cmd_q is not None:
                self.spotter_cmd_q.put("START")

            self._update_status_label("Durum: Kamera Başlatıldı.")
            self.timer.start(int(self.angle_command_minimum_interval * 1000))

            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.update_info_panel("BUKREK Hava Savunma Sistemi Başlatıldı")
        except Exception as e:
            self._update_status_label(f"Durum: Hata: {str(e)[:50]}...")

    def _gozcu_durdur(self):
        if self.spotter_cmd_q is not None:
            self.spotter_cmd_q.put("STOP")
        self.gozcu_izler = []
        self.gozcu_onizleme = None
        self.gozcu_bloklari = []
        self.spotter_label.setText("Gözcü: kapalı")
        self.spotter_info_label.setText("Gözcü: -")

    def stop_camera(self):
        self.camera_cmd_q.put("STOP")
        self.inference_cmd_q.put({"action": "STOP"})
        self._gozcu_durdur()
        self.timer.stop()

        self._update_status_label("Durum: Kamera Durduruldu.")
        self.target_info_label.setText("Hedef Bilgisi: Yok")

        # Clear result queue
        while not self.result_q.empty():
            try:
                self.result_q.get_nowait()
            except queue.Empty:
                break

        self.active_task = None
        self.camera_label.clear()
        self._stop_all_manual_movement()
        self.reset_pid_state()
        self.is_target_active = False
        self.is_aimed_at_target = False
        self.target_destroyed = False
        self.waiting_for_new_engagement_command = False
        self.target_lost_time = 0.0
        self.current_tracked_target_class = None
        self.current_tracked_target_bbox = None
        self.missing_frames = 0

        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def cancel_task(self):
        self.angajman.durdur()
        self.aktif_cift = None
        self._kilitli_bboxlar = set()
        self._nisan_alinan_bbox = None
        self._takip_hedef_kimlik = None
        self.active_task = None
        self.inference_cmd_q.put({"action": "SET_TASK", "task": None})

        self.target_destroyed = False
        self.waiting_for_new_engagement_command = False
        self.target_lost_time = 0.0
        self.current_tracked_target_class = None
        self.current_tracked_target_bbox = None
        self.missing_frames = 0

        self.is_ready_to_engage_from_qr = False
        self.qr_degrees = {}
        self.current_qr_char = None
        self.task3_settings_group_box.setVisible(False)

        self._update_status_label("Durum: Görev durduruldu.")
        self.target_info_label.setText("Hedef Bilgisi: Yok")
        self._stop_all_manual_movement()
        self.movement_restricted_yaw_start = 0
        self.movement_restricted_yaw_end = 0
        self.active_engagement_target_color = None
        self.active_engagement_target_shape = None
        self.fire_control_group_box.setVisible(True)
        self.direct_manual_control_group_box.setVisible(False)
        self.is_target_active = False
        self.is_aimed_at_target = False
        self.reset_pid_state()

    def reset_pid_state(self):
        self._ff_onceki_yaw = 0.0
        self._ff_onceki_pitch = 0.0
        # Suzgec hafizasi da sifirlanmali: yeni hedefe gecerken eski
        # hedefin cikisini sizdirmasin.
        self._pid_cikis_yaw = 0.0
        self._pid_cikis_pitch = 0.0
        self.integral_yaw = 0.0
        self.last_error_yaw = 0.0
        self.integral_pitch = 0.0
        self.last_error_pitch = 0.0
        self.last_target_x = None
        self.last_target_y = None
        self.last_frame_time = None
        self.last_target_velocity_x = 0.0
        self.last_target_velocity_y = 0.0
        self.target_world_yaw_rate = 0.0
        self.target_world_pitch_rate = 0.0
        self._last_world_yaw = None
        self._last_world_pitch = None
        self._last_world_time = None
        self._son_gorulen_dunya_yaw = None
        self._son_gorulen_dunya_pitch = None
        self._son_gorulen_zaman = 0.0
        self.current_pid_range = "TEK_SET"
        self.missing_frames = 0

    def _angajman_baslat(self, asama):
        """Otonom aşamaları başlatırken durum makinesini de sıfırla."""
        self.angajman.basla(asama)
        self.aktif_cift = None

    def task1(self):
        self.cancel_task()
        self.active_task = 'task1'
        self.inference_cmd_q.put({"action": "SET_TASK", "task": 'task1'})

        # AŞAMA 1 = TAMAMEN MANUEL. Taret otonom servolama YAPMAZ; operatör
        # ok tuşlarıyla nişan alır ve ATEŞ ET ile ateşler. YOLO yine çalışır
        # ama yalnızca GÖSTERİM için — operatör hedefleri ekranda görsün diye.
        # (Tam Manuel Kontrol'den farkı budur: orada YOLO hiç çalışmaz.)
        self.crosshair_movable = True
        self.crosshair_fixed_center = False
        self.task3_settings_group_box.setVisible(False)
        self._update_status_label(
            "Durum: Aşama 1 - Tam manuel kontrol (YOLO yalnızca gösterim).")
        self.target_info_label.setText("Hedef Bilgisi: Manuel mod.")

        self.target_destroyed = False
        self.waiting_for_new_engagement_command = True
        self.target_lost_time = 0.0
        self.current_tracked_target_class = None
        self.current_tracked_target_bbox = None
        self.missing_frames = 0
        self.movement_restricted_yaw_start = 0
        self.movement_restricted_yaw_end = 0
        self.fire_control_group_box.setVisible(True)
        self.direct_manual_control_group_box.setVisible(True)
        try:
            self._start_manual_movement_timer()
        except Exception as e:
            self._update_status_label(f"Hata: Manuel mod başlatma hatası: {str(e)[:50]}...")
        # Tespit/kilitlenme hattı AÇIK kalır. Taret otonom hareket etmez
        # (servolama OTONOM_MODLAR ile sınırlı) ama hedef ekranda işaretlenir
        # ve `current_tracked_target_class` dolar.
        #
        # İkincisi zorunlu: "Derece/Piksel Ölç" kalibrasyonu Aşama 1 + KİLİTLİ
        # HEDEF şartı arıyor. Burayı False bırakmak kalibrasyon butonunu
        # "kilitli bir hedef gerekli" hatasıyla çalışmaz hale getiriyordu.
        # (Tam Manuel Kontrol'de False kalır — orada YOLO hiç kullanılmaz.)
        self.is_target_active = True
        self.is_aimed_at_target = False

    def task2(self):
        self.cancel_task()
        self.active_task = 'task2'
        self.inference_cmd_q.put({"action": "SET_TASK", "task": 'task2'})

        self.crosshair_movable = False
        self.crosshair_fixed_center = True
        self.task3_settings_group_box.setVisible(False)
        self._angajman_baslat('task2')
        self._update_status_label(
            "Durum: Aşama 2 (Hızlı İmha) — gözcü tarıyor, tüm hedefler düşman.")
        self.target_info_label.setText("Hedef Bilgisi: Düşman maket + kırmızı balon.")

        self.target_destroyed = False
        self.waiting_for_new_engagement_command = True
        self.target_lost_time = 0.0
        self.current_tracked_target_class = None
        self.current_tracked_target_bbox = None
        self.missing_frames = 0
        self.movement_restricted_yaw_start = 0
        self.movement_restricted_yaw_end = 0
        self.fire_control_group_box.setVisible(True)
        self.direct_manual_control_group_box.setVisible(False)
        self.is_target_active = True
        self.is_aimed_at_target = False

    def task3(self):
        """Aşama 3'ü doğrudan başlatır (eski QR tabanlı ayar akışı yerine)."""
        self.cancel_task()
        self.active_task = 'task3'
        self.inference_cmd_q.put({"action": "SET_TASK", "task": 'task3'})
        self.crosshair_movable = False
        self.crosshair_fixed_center = True
        if hasattr(self, 'task3_settings_group_box'):
            self.task3_settings_group_box.setVisible(False)
        self.target_destroyed = False
        self.waiting_for_new_engagement_command = True
        self.target_lost_time = 0.0
        self.current_tracked_target_class = None
        self.current_tracked_target_bbox = None
        self.missing_frames = 0
        self.fire_control_group_box.setVisible(True)
        self.direct_manual_control_group_box.setVisible(False)
        self.is_target_active = True
        self.is_aimed_at_target = False
        self._task3_baslat()

    def setup_task3(self):
        self.cancel_task()
        self.active_task = 'task3_setup'
        self.task3_settings_group_box.setVisible(True)
        self.fire_control_group_box.setVisible(True)
        self.direct_manual_control_group_box.setVisible(False)
        self._update_status_label("Durum: Aşama 3 - Angajman ayarları bekleniyor.")
        self.target_info_label.setText("Hedef Bilgisi: Yok (Ayar Bekleniyor).")
        self.is_target_active = False

    def _task3_baslat(self):
        """Aşama 3: iki dost bir düşman; yalnızca düşmanın balonu vurulacak."""
        self._angajman_baslat('task3')
        self._update_status_label(
            "Durum: Aşama 3 (Dost/Düşman) — yalnızca düşman maketin balonu hedeflenecek.")
        self.target_info_label.setText("Hedef Bilgisi: Düşman aranıyor.")

    def start_task3_engagement(self):
        self.cancel_task()
        self.active_task = 'task3'
        self.inference_cmd_q.put({"action": "SET_TASK", "task": 'task3'})

        self.crosshair_movable = False
        self.crosshair_fixed_center = True
        self.fire_control_group_box.setVisible(True)
        self.direct_manual_control_group_box.setVisible(False)
        self.is_ready_to_engage_from_qr = False

        try:
            a_degree = float(self.a_input.text())
            b_degree = float(self.b_input.text())
            self.qr_degrees = {'A': a_degree, 'B': b_degree}
            self._update_status_label("Durum: Aşama 3 Ayarları kaydedildi. QR kodu bekleniyor...")
            self.target_info_label.setText("Hedef Bilgisi: QR Kod.")
            self.is_target_active = True
            self.waiting_for_new_engagement_command = True
            self.reset_pid_state()
        except ValueError:
            self._update_status_label("Hata: Lütfen geçerli sayısal değerler girin.")
            self.cancel_task()
            return

    def hedef_takip(self):
        """
        HEDEF TAKİP — kilitlen ve takip et, ASLA otonom ateş etme.

        Görev aşamalarından farkı: angajman durum makinesi HİÇ başlatılmaz.
        Yani gözcü devir teslimi yok, dost/düşman doğrulaması yok, ateş yolu
        yok. Yalnızca avcının o karede gördüğü en yakın hedefe kilitlenip
        onu nişangahta tutar.

        Ne işe yarar: kilitlenme kalitesini (oturma süresi, kalan hata,
        salınım) ateş riski olmadan ölçmek. Ölçüm için durum çubuğuna canlı
        nişan hatası piksel VE derece cinsinden yazılıyor, tolerans içinde
        olup olmadığıyla birlikte.

        Hedef seçimi manuel/Aşama 1 yolunu kullanır: maket+balon çifti varsa
        balona, yalnız maket varsa maketten türetilen noktaya, yalnız balon
        varsa balona nişan alınır — "tespit edilen herhangi bir hedef".
        """
        self.cancel_task()
        self.active_task = 'takip'
        self.inference_cmd_q.put({"action": "SET_TASK", "task": 'takip'})

        self.crosshair_movable = False
        self.crosshair_fixed_center = True
        self.task3_settings_group_box.setVisible(False)
        self._update_status_label(
            "Durum: Hedef Takip — kilitlenip takip edilecek, otonom ateş YOK.")
        self.target_info_label.setText("Hedef Bilgisi: Hedef aranıyor.")

        self.target_destroyed = False
        self.waiting_for_new_engagement_command = True
        self.target_lost_time = 0.0
        self.current_tracked_target_class = None
        self.current_tracked_target_bbox = None
        self.missing_frames = 0
        self.movement_restricted_yaw_start = 0
        self.movement_restricted_yaw_end = 0
        self.fire_control_group_box.setVisible(True)
        self.direct_manual_control_group_box.setVisible(False)
        self.is_target_active = True
        self.is_aimed_at_target = False

    def set_full_manual_mode(self):
        self.cancel_task()
        self.active_task = 'full_manual'
        self.task3_settings_group_box.setVisible(False)
        self._update_status_label("Durum: Tam Manuel Kontrol Modu Aktif.")
        self.target_info_label.setText("Hedef Bilgisi: Yok (Manuel).")
        self.crosshair_movable = True
        self.crosshair_fixed_center = False
        self.fire_control_group_box.setVisible(True)
        self.direct_manual_control_group_box.setVisible(True)
        try:
            self._start_manual_movement_timer()
        except Exception as e:
            self._update_status_label(f"Hata: Manuel mod başlatma hatası: {str(e)[:50]}...")
        self.is_target_active = False
        self.is_aimed_at_target = False

    # Operatörün ok tuşlarıyla tareti sürebildiği modlar.
    MANUEL_MODLAR = ('full_manual', 'task1')
    # ANGAJMAN MAKİNESİNİN çalıştığı modlar (gözcü devir teslimi, doğrulama,
    # kilit, ateş). Yalnızca görev aşamaları.
    OTONOM_MODLAR = ('task2', 'task3')
    # PID'in tareti hedefe ORTALADIĞI modlar. 'takip' angajman makinesini
    # çalıştırmaz — yani gözcü devir teslimi ve ateş yolu kapalıdır — ama
    # avcının gördüğü hedefi ortalar. Kilitlenme kalitesini ateş riski
    # olmadan ölçmek için.
    SERVO_MODLAR = OTONOM_MODLAR + ('takip',)

    def _handle_manual_button_press(self, direction_key):
        if self.active_task not in self.MANUEL_MODLAR:
            return

        self.movement_states[direction_key] = True
        self._update_manual_directions_from_states()
        self._start_manual_movement_timer()
        self._update_status_label(f"Durum: Manuel hareket etkin: {direction_key}.")

    def _set_movement_state(self, direction_key, is_pressed):
        if self.active_task not in self.MANUEL_MODLAR:
            return

        self.movement_states[direction_key] = is_pressed
        self._update_manual_directions_from_states()
        self._start_manual_movement_timer()

    def _start_manual_movement_timer(self):
        if any(self.movement_states.values()):
            if not self.manual_movement_timer.isActive():
                self.manual_movement_timer.start(10)
        else:
            if self.manual_movement_timer.isActive():
                self.manual_movement_timer.stop()
            self._update_status_label("Durum: Manuel hareket durduruldu.")
            if self.rpi_thread.is_connected:
                # force=True: duruş komutu her koşulda gitmeli.
                self._send_manual_direction(0, 0, force=True)

    def _update_manual_directions_from_states(self):
        self.manual_yaw_direction = 0
        self.manual_pitch_direction = 0

        if self.movement_states['yaw_left']:
            self.manual_yaw_direction = -1
        elif self.movement_states['yaw_right']:
            self.manual_yaw_direction = 1

        if self.movement_states['pitch_up']:
            self.manual_pitch_direction = 1
        elif self.movement_states['pitch_down']:
            self.manual_pitch_direction = -1

        if self.movement_states['yaw_left'] and self.movement_states['yaw_right']:
            self.manual_yaw_direction = 0
        if self.movement_states['pitch_up'] and self.movement_states['pitch_down']:
            self.manual_pitch_direction = 0

    def _send_manual_direction(self, yaw_dir, pitch_dir, force=False):
        """
        Manuel yön komutunu gönderir; yalnızca yön DEĞİŞTİĞİNDE veya canlılık
        aralığı dolduğunda.

        Önceden bu komut 10 ms'de bir koşulsuz gönderiliyordu (saniyede 100
        komut). Pi bunun ancak onda birini tüketebildiği için kuyruk birikiyor,
        "dur" komutu birikmiş hareket komutlarının arkasında kalıyor ve buton
        bırakıldıktan sonra taret dönmeye devam ediyordu.

        Periyodik tekrar, Pi tarafındaki watchdog'u beslemek için gereklidir:
        komut akışı kesilirse (arayüz çöker, ağ kopar) taret kendiliğinden
        durur. Bu yüzden aralık MANUAL_COMMAND_TIMEOUT'tan belirgin küçük olmalı.
        """
        simdi = time.time()
        degisti = (yaw_dir, pitch_dir) != self._last_manual_direction
        canlilik_zamani = (simdi - self._last_manual_send_time) >= self.manual_keepalive_interval

        if not (force or degisti or canlilik_zamani):
            return

        hareket_var = yaw_dir != 0 or pitch_dir != 0
        self.send_command_to_rpi({
            "action": "move_by_direction",
            "yaw_direction": yaw_dir,
            "pitch_direction": pitch_dir,
            "degrees_to_move": self.manual_step_size if hareket_var else 0,
        })
        self._last_manual_direction = (yaw_dir, pitch_dir)
        self._last_manual_send_time = simdi

    def _continuously_update_motor_position(self):
        if self.active_task not in self.MANUEL_MODLAR or not self.rpi_thread.is_connected:
            self._stop_all_manual_movement()
            return

        self._send_manual_direction(self.manual_yaw_direction, self.manual_pitch_direction)

    def _stop_all_manual_movement(self):
        for key in self.movement_states:
            self.movement_states[key] = False
        if self.manual_movement_timer.isActive():
            self.manual_movement_timer.stop()
        self.manual_yaw_direction = 0
        self.manual_pitch_direction = 0
        self._update_status_label("Durum: Manuel hareket durduruldu.")
        if self.rpi_thread.is_connected:
            # force=True: duruş komutu her koşulda gitmeli.
            self._send_manual_direction(0, 0, force=True)

    def _bilgi_panelini_yenile(self):
        """
        Üst bilgi satırının TEK yazarı.

        Eskiden iki ayrı yer bu satıra FARKLI metinler yazıyordu:
        `_update_current_angles` (Pi'den ~15 Hz) yalnızca açıları,
        `update_frame` (~25 Hz) açıları + kare sayaçlarını. İki metin
        saniyede ~40 kez dönüşümlü yazıldığı için satır gözle okunamayacak
        kadar titriyordu — sahada "yazılar çakarlı gibi açılıp kapanıyor"
        olarak görüldü. Artık ikisi de bu fonksiyonu çağırıyor, dolayısıyla
        içerik her zaman aynı.
        """
        # Enkoder: adım sayacının yanında GERÇEK yaw ve ikisinin farkı.
        # Fark büyüyorsa adım sayacı gerçeği kaybetmiştir (kaçırılan adım,
        # dişli boşluğu, elle zorlanmış taret). FAZ 3'te yalnızca izlenir.
        if self._enkoder is None:
            enk = ""
        elif not self._enkoder.get("ok") or self._enkoder.get("yaw") is None:
            enk = "  |  enk: YOK"
        else:
            ey = float(self._enkoder["yaw"])
            fark = (ey - self.current_yaw_angle + 180) % 360 - 180
            enk = f"  |  enk {ey:+.2f}° (Δ{fark:+.2f}°)"
        self.update_info_panel(
            f"Mevcut Yaw: {self.current_yaw_angle:.1f}°, "
            f"Pitch: {self.current_pitch_angle:.1f}°{enk}  |  "
            f"kare {self._tani['sonuc']} / çizim {self._tani['ciz']}")

    def update_info_panel(self, text):
        self.info_label.setText(f"<h2 style='color: white; text-align: center;'>{text}</h2>")

    def apply_no_fire_zone_settings(self):
        try:
            start_yaw = float(self.no_fire_start_input.text())
            end_yaw = float(self.no_fire_end_input.text())
            self.no_fire_yaw_start = start_yaw
            self.no_fire_yaw_end = end_yaw
            self._update_status_label(
                f"Durum: Ateşsiz Bölge Güncellendi: Yaw [{start_yaw:.1f}°, {end_yaw:.1f}°]")
        except ValueError:
            self._update_status_label("Hata: Lütfen ateşsiz bölge için geçerli sayısal değerler girin.")

    def clear_no_fire_zone_settings(self):
        self.no_fire_yaw_start = 0.0
        self.no_fire_yaw_end = 0.0
        self.no_fire_start_input.setText("0.0")
        self.no_fire_end_input.setText("0.0")
        self._update_status_label("Durum: Ateşsiz Bölge Temizlendi.")

    def send_angle_command(self, yaw, pitch, force=False):
        """
        Mutlak açı komutu gönderir.

        :param force: Hız sınırını atla. Kalibrasyon gibi TEK SEFERLİK ve
            gönderildiğinden emin olunması gereken komutlar için gereklidir;
            aksi halde PID'in az önce gönderdiği komut yüzünden sessizce düşer.
        """
        if not self.rpi_thread.is_connected:
            self._update_status_label("Hata: Raspberry Pi'ye bağlı değil, açı komutu gönderilemedi.")
            return False

        current_time = time.time()
        if not force and current_time - self.last_angle_command_send_time < 0.1:
            return False

        command = {"action": "set_angles", "yaw": yaw, "pitch": pitch}
        self.last_angle_command_send_time = current_time
        return self.send_command_to_rpi(command)

    def fire_weapon(self):
        if not self.rpi_thread.is_connected:
            self._update_status_label("Hata: Raspberry Pi'ye bağlı değil, ateş edilemez.")
            return
        try:
            current_time = time.time()
            if current_time - self.last_fire_time < self.fire_cooldown_interval:
                self._update_status_label("Uyarı: Ateşleme denemesi çok hızlı. Lütfen bekleyin.")
                return

            if self.is_in_no_fire_zone(self.current_yaw_angle):
                self._update_status_label("Uyarı: Ateşsiz bölgedesiniz! Ateşleme engellendi.")
                return

            # Aşama 1 tamamen manuel: nişan kilidi aranmaz, operatör karar verir.
            if self.active_task in self.MANUEL_MODLAR:
                self.send_command_to_rpi({"action": "fire"})
                self.last_fire_time = current_time
                return

            if self.active_task in ['task2', 'task3']:
                if not self.is_aimed_at_target:
                    self._update_status_label("Uyarı: Hedef nişan alma toleransı dışında! Ateşleme engellendi.")
                    return

            self.send_command_to_rpi({"action": "fire"})
            self.last_fire_time = current_time
        except Exception as e:
            self._update_status_label(f"Hata: Ateşleme hatası: {str(e)[:50]}...")

    # --- Derece/piksel kalibrasyonu ---
    # Bilinen bir açı komutu verilir, hedefin görüntüde kaç piksel kaydığı
    # ölçülür: derece/piksel = verilen_açı / kayan_piksel.
    # Mevcut modlarla bu ölçülemiyordu: Aşama 1'de taret hedefi aktif olarak
    # ortaladığı için hata sıfıra gidiyor, tam manuel modda ise görev None
    # olduğu için tespit hiç çalışmıyor ve piksel bilgisi yok.

    # Test açısı KADEMELİ büyütülür: derece/piksel önceden bilinmediği için tek
    # bir açı her sisteme uymaz. Küçük açı yeterli piksel kayması üretmezse
    # (redüksiyon beklenenden büyükse) sıradaki daha büyük açı denenir.
    CALIBRATION_ANGLE_STEPS = (4.0, 12.0, 30.0, 70.0)
    CALIBRATION_ARRIVE_TOL = 0.25  # Hedef açıya varmış sayılma toleransı (derece)
    CALIBRATION_TIMEOUT = 60.0     # Tüm ölçümün üst sınırı (saniye)
    CALIBRATION_MIN_SHIFT_PX = 15  # Bu kadar kaymadıysa ölçüm güvenilmez

    # Açı raporu "vardım" dediğinde kamera karesi hâlâ hareketin ortasını
    # gösteriyor olabilir (kamera + çıkarım gecikmesi ~150 ms). Bu yüzden
    # açının değil, GÖRÜNTÜNÜN oturması beklenir: hedefin piksel konumu
    # ardışık karelerde değişmeyi bırakana kadar ölçüm alınmaz.
    CALIBRATION_PIXEL_STABLE_TOL = 3   # piksel
    CALIBRATION_STABLE_FRAMES = 4      # bu kadar ardışık kare sabit kalmalı

    def start_calibration(self):
        """Derece/piksel ölçümünü başlatır."""
        if not self.rpi_thread.is_connected:
            self._update_status_label("Hata: Kalibrasyon için RPi bağlantısı gerekli.", oncelikli=True)
            return
        if self.active_task != 'task1':
            self._update_status_label("Hata: Kalibrasyon için önce Aşama 1'i başlatın.", oncelikli=True)
            return
        if self.current_tracked_target_class is None:
            self._update_status_label("Hata: Kalibrasyon için kilitli bir hedef gerekli.", oncelikli=True)
            return

        self._calibrating = True
        self._cal_phase = 'yaw_ileri_gonder'
        self._cal_start_time = time.time()
        self._cal_samples = []
        self._cal_results = {}
        self._cal_target_angle = None
        self._cal_ref_px = None
        self._cal_ref_angle = None
        self._cal_step_idx = 0  # Hangi test açısındayız (kademeli büyütme)
        self._update_status_label("Kalibrasyon: Hedefi SABİT tutun, ölçüm başlıyor...",
                                  oncelikli=True, sure=3.0)
        print("KALİBRASYON: başladı. Hedefi olabildiğince sabit tutun.")

    def _cal_ekseni_varmis_mi(self, eksen):
        """Taret komut edilen açıya gerçekten vardı mı?"""
        mevcut = self.current_yaw_angle if eksen == 'yaw' else self.current_pitch_angle
        fark = (self._cal_target_angle - mevcut + 180) % 360 - 180
        return abs(fark) <= self.CALIBRATION_ARRIVE_TOL

    def _cal_komut_gonder(self, eksen, delta):
        """Test açısını gönderir; hız sınırını atlar ve gönderildiğini doğrular."""
        if eksen == 'yaw':
            self._cal_target_angle = self.current_yaw_angle + delta
            gonderildi = self.send_angle_command(self._cal_target_angle,
                                                 self.current_pitch_angle, force=True)
        else:
            self._cal_target_angle = self.current_pitch_angle + delta
            gonderildi = self.send_angle_command(self.current_yaw_angle,
                                                 self._cal_target_angle, force=True)
        return gonderildi

    def _calibration_tick(self, target_x, target_y):
        """
        Kalibrasyon durum makinesi; PID askıdayken her karede bir çağrılır.

        Her eksende hareket İLERİ ve GERİ yapılır, iki ölçüm ortalanır: hedef
        elde tutulduğu için sabit yönlü kayma kaçınılmaz, çift yönlü ölçüm bunu
        büyük ölçüde iptal eder.

        Ayrıca nominal komut açısı değil, açı raporundan okunan GERÇEKLEŞEN açı
        farkı kullanılır; böylece komut tam uygulanmasa da ölçüm doğru kalır.
        """
        try:
            if time.time() - self._cal_start_time > self.CALIBRATION_TIMEOUT:
                self._bitir_kalibrasyon("Hata: Kalibrasyon zaman aşımına uğradı.")
                return

            faz = self._cal_phase

            # Tahmin edilmiş konumla ölçüm yapma. Hedef birkaç karedir
            # görülmüyorsa update_frame bbox'ı TAHMİN ediyor; o konum taretin
            # hareketini yansıtmaz ve kayma yapay olarak sıfıra yakın çıkar.
            if getattr(self, 'missing_frames', 0) > 0:
                return

            # --- Komut gönderme fazları ---
            if faz.endswith('_gonder'):
                eksen = 'yaw' if faz.startswith('yaw') else 'pitch'
                yon = 1.0 if '_ileri_' in faz else -1.0
                self._cal_ref_px = target_x if eksen == 'yaw' else target_y
                self._cal_ref_angle = (self.current_yaw_angle if eksen == 'yaw'
                                       else self.current_pitch_angle)
                aci = self.CALIBRATION_ANGLE_STEPS[self._cal_step_idx]
                if not self._cal_komut_gonder(eksen, yon * aci):
                    self._bitir_kalibrasyon("Hata: Açı komutu gönderilemedi.")
                    return
                self._cal_phase = faz.replace('_gonder', '_bekle')
                self._cal_stable_count = 0
                self._cal_last_px = None
                self._update_status_label(
                    f"Kalibrasyon: {eksen.upper()} ölçülüyor ({aci:.0f}°), hedefi sabit tutun...")
                return

            # --- Varış bekleme fazları ---
            if faz.endswith('_bekle'):
                eksen = 'yaw' if faz.startswith('yaw') else 'pitch'
                if not self._cal_ekseni_varmis_mi(eksen):
                    return  # Açı henüz varmadı

                simdiki_px = target_x if eksen == 'yaw' else target_y

                # Açı vardı ama görüntü hâlâ hareket ediyor olabilir; piksel
                # konumu sabitlenene kadar ölçüm alma. Bu beklenmediğinde ileri
                # ve geri ölçümler birbirini tutmuyordu (152 px'e karşı 56 px).
                if (self._cal_last_px is not None
                        and abs(simdiki_px - self._cal_last_px) <= self.CALIBRATION_PIXEL_STABLE_TOL):
                    self._cal_stable_count += 1
                else:
                    self._cal_stable_count = 0
                self._cal_last_px = simdiki_px
                if self._cal_stable_count < self.CALIBRATION_STABLE_FRAMES:
                    return  # Görüntü henüz oturmadı
                simdiki_aci = (self.current_yaw_angle if eksen == 'yaw'
                               else self.current_pitch_angle)
                kayma_px = self._cal_ref_px - simdiki_px
                aci_farki = (simdiki_aci - self._cal_ref_angle + 180) % 360 - 180

                print(f"KALİBRASYON [{eksen}]: komut {aci_farki:+.2f}° -> "
                      f"piksel {self._cal_ref_px:.0f} -> {simdiki_px:.0f} "
                      f"(kayma {kayma_px:+.0f} px)")

                if abs(kayma_px) < self.CALIBRATION_MIN_SHIFT_PX:
                    # Kayma yetersiz: daha büyük açıyla tekrar dene.
                    if self._cal_step_idx + 1 < len(self.CALIBRATION_ANGLE_STEPS):
                        self._cal_step_idx += 1
                        yeni = self.CALIBRATION_ANGLE_STEPS[self._cal_step_idx]
                        print(f"KALİBRASYON: kayma yetersiz, {yeni:.0f}° ile tekrar deneniyor.")
                        self._cal_phase = faz.replace('_bekle', '_gonder')
                        return
                    self._bitir_kalibrasyon(
                        f"Hata: {eksen.upper()} en büyük açıda bile yeterli kayma üretmedi "
                        f"({kayma_px:.0f} px). Taret fiziksel olarak hareket ediyor mu?")
                    return

                self._cal_samples.append((eksen, aci_farki / kayma_px))

                # Sıradaki faza geç
                sirali = {
                    'yaw_ileri_bekle': 'yaw_geri_gonder',
                    'yaw_geri_bekle': 'pitch_ileri_gonder',
                    'pitch_ileri_bekle': 'pitch_geri_gonder',
                    'pitch_geri_bekle': None,
                }
                self._cal_phase = sirali[faz]
                if self._cal_phase is None:
                    self._rapor_kalibrasyon()
        except Exception as e:
            self._bitir_kalibrasyon(f"Hata: Kalibrasyon başarısız: {str(e)[:40]}")

    def _rapor_kalibrasyon(self):
        yaw_ler = [v for e, v in self._cal_samples if e == 'yaw']
        pitch_ler = [v for e, v in self._cal_samples if e == 'pitch']
        if not yaw_ler or not pitch_ler:
            self._bitir_kalibrasyon("Hata: Yeterli ölçüm toplanamadı.")
            return

        # Tutarlılık kontrolü: ileri ve geri ölçümler birbirini tutmalı.
        # Tutmuyorsa ortalamak yanlış bir sayı üretir; ölçüm reddedilmeli.
        def tutarli(deger_listesi):
            if len(deger_listesi) < 2:
                return True
            if any(v * deger_listesi[0] <= 0 for v in deger_listesi):
                return False  # işaret uyuşmazlığı
            buyuk = max(abs(v) for v in deger_listesi)
            kucuk = min(abs(v) for v in deger_listesi)
            return buyuk <= kucuk * 1.35  # en fazla %35 sapma

        yaw_tutarli = tutarli(yaw_ler)
        pitch_tutarli = tutarli(pitch_ler)

        y = sum(yaw_ler) / len(yaw_ler)
        p = sum(pitch_ler) / len(pitch_ler)

        # Makullük kontrolü: derece/piksel x kare genişliği = yatay görüş açısı.
        # Geniş bant bilinçli: telefoto bir kurulum 20 derecenin altına inebilir,
        # geniş açı 120'ye çıkabilir. Amaç meşru kurulumları elemek değil, fiziksel
        # olarak imkânsız sonuçları (yüzlerce derece) yakalamak.
        fov_yatay = abs(y) * self.frame_orig_w
        fov_dikey = abs(p) * self.frame_orig_h
        makul = 15.0 <= fov_yatay <= 130.0

        gecerli = makul and yaw_tutarli and pitch_tutarli

        print("=" * 64)
        print("KALİBRASYON SONUCU")
        print(f"  yaw ölçümleri  : {', '.join(f'{v:.5f}' for v in yaw_ler)}"
              f"   {'tutarlı' if yaw_tutarli else '<< TUTARSIZ'}")
        print(f"  pitch ölçümleri: {', '.join(f'{v:.5f}' for v in pitch_ler)}"
              f"   {'tutarlı' if pitch_tutarli else '<< TUTARSIZ'}")
        print(f"  ima edilen görüş açısı: yatay {fov_yatay:.0f}°, dikey {fov_dikey:.0f}°"
              f"   {'makul' if makul else '<< MAKUL DEĞİL'}")

        if not gecerli:
            print()
            print("  ÖLÇÜM GEÇERSİZ — config.py'a YAZMAYIN.")
            if not (yaw_tutarli and pitch_tutarli):
                print("  İleri ve geri ölçümler birbirini tutmuyor. En olası sebep:")
                print("  hedef ölçüm sırasında hareket etti. Balonu sabitleyip tekrarlayın.")
            if not makul:
                print("  Görüş açısı fiziksel olarak mümkün olmayan bir değerde.")
            print("=" * 64)
            self._update_status_label("Hata: Kalibrasyon geçersiz, tekrarlayın (konsola bakın).")
            self._bitir_kalibrasyon(None)
            return

        oran = abs(y / self.DEGREES_PER_PIXEL_YAW) if self.DEGREES_PER_PIXEL_YAW else 0
        onerilen_kp = config.KP_YAW / oran if oran else config.KP_YAW

        self._update_status_label(f"Durum: Kalibrasyon bitti: YAW={y:.5f} PITCH={p:.5f}")
        print()
        print("  config.py içine yazın:")
        print(f"    DEGREES_PER_PIXEL_YAW   = {y:.5f}")
        print(f"    DEGREES_PER_PIXEL_PITCH = {p:.5f}")
        print(f"  (mevcut: {self.DEGREES_PER_PIXEL_YAW:.5f} / {self.DEGREES_PER_PIXEL_PITCH:.5f})")
        print()
        print("  DÖNGÜ KAZANCI = KP x derece/piksel")
        print(f"  Bu değer {oran:.1f} kat değişiyor. Aynı davranışı korumak için")
        print(f"  KP_YAW {config.KP_YAW:.2f} -> {onerilen_kp:.2f} yapılmalıydı; ANCAK bu")
        print("  değer zaten olması gerekenden düşüktü (takip yavaştı). Doğru")
        print("  kalibrasyonla KP artık gerçek anlamını taşıdığı için 0.5-0.7")
        print("  aralığı hem hızlı hem kararlı olmalıdır.")
        print("=" * 64)
        self._bitir_kalibrasyon(None)

    def _bitir_kalibrasyon(self, hata_mesaji):
        self._calibrating = False
        self._cal_phase = None
        self.reset_pid_state()
        if hata_mesaji:
            self._update_status_label(hata_mesaji)
            print(f"KALİBRASYON: {hata_mesaji}")

    def reset_rpi_angles(self):
        if not self.rpi_thread.is_connected:
            self._update_status_label("Hata: Raspberry Pi'ye bağlı değil, açılar sıfırlanamaz.")
            return
        self.send_command_to_rpi({"action": "reset_angles"})

    def close_event(self, event=None):
        # aboutToQuit sinyali parametresiz yayılır, closeEvent ise bir olay geçirir;
        # ikisinden de çağrılabilmesi için event isteğe bağlı tutuldu.
        self.stop_camera()
        if self.rpi_thread.isRunning():
            self.rpi_thread.request_stop()
            self.rpi_thread.wait(2000)

        # Send quit signals to processes
        self.camera_cmd_q.put("QUIT")
        self.inference_cmd_q.put({"action": "QUIT"})
        if self.spotter_cmd_q is not None:
            self.spotter_cmd_q.put("QUIT")

        if event is not None:
            event.accept()

    def update_frame(self):
        self._tani['tik'] += 1
        simdi_tani = time.time()
        if simdi_tani - self._tani_son_yazdirma >= 2.0:
            self._tani_son_yazdirma = simdi_tani
            t = self._tani
            canli = " ".join(
                f"{ad}={'CANLI' if p.is_alive() else 'OLDU'}"
                for ad, p in self.surecler.items()) or "surec bilgisi yok"
            print(f"TANI: tik={t['tik']} bos_kuyruk={t['bos']} sonuc={t['sonuc']} "
                  f"cizim={t['ciz']} hata={t['hata']} | {canli} | "
                  f"etiket={self.camera_label.width()}x{self.camera_label.height()} "
                  f"gorunur={self.camera_label.isVisible()} "
                  f"pixmap={'VAR' if self.camera_label.pixmap() else 'YOK'}")

        # GÖZCÜ ÖNCE. Avcı hattından (kamera -> çıkarım -> sonuç kuyruğu)
        # bağımsız olmalı: aşağıdaki erken çıkışların arkasında kalırsa,
        # avcı veya YOLO tarafında bir sorun olduğunda gözcü paneli de
        # kararıyor ve hangi hattın bozuk olduğu anlaşılamıyor.
        try:
            self._gozcu_oku()
            self._gozcu_ciz()
            # Kamera indeksi de yazılıyor: Windows'ta indeks ataması USB
            # portuna göre değişiyor ve yanlış eşleşme "görüntü gelmiyor"
            # gibi görünüyor. Hangi kameranın nerede olduğunu ekrandan
            # görebilmek gerekiyor.
            _ix = f"kam{self.gozcu_indeks}" if self.gozcu_indeks is not None else "kam?"
            # Blob sayımı: "gözcü hiçbir şey görmüyor" ile "görüyor ama aday
            # saymıyor" ayrımı ekrandan anlaşılsın. İkisi çok farklı sorunlar.
            _k = sum(1 for b in self.gozcu_bloklari if b['renk'] == 'kirmizi')
            _m = sum(1 for b in self.gozcu_bloklari if b['renk'] == 'mavi')
            _blok = f" | blob K{_k}/M{_m}"
            if self.gozcu_izler:
                en_iyi = self.gozcu_izler[0]
                self.spotter_info_label.setText(
                    f"Gözcü [{_ix}]: {len(self.gozcu_izler)} iz{_blok} | ilk: "
                    f"{en_iyi['yaw']:+.1f}° {en_iyi['pitch']:+.1f}° "
                    f"({en_iyi['sinif']}, {en_iyi['yaw_hiz']:+.1f}°/s)")
            elif self.gozcu_onizleme is not None:
                self.spotter_info_label.setText(
                    f"Gözcü [{_ix}]: çalışıyor, iz yok{_blok}")
            else:
                self.spotter_info_label.setText("Gözcü: veri gelmiyor")
        except Exception as e:
            self.spotter_info_label.setText(f"Gözcü hatası: {str(e)[:40]}")

        try:
            # Poll result queue
            try:
                # We pull the latest result
                latest_result = None
                while not self.result_q.empty():
                    latest_result = self.result_q.get_nowait()

                if latest_result is None:
                    self._tani['bos'] += 1
                    return # No new frame yet
                self._tani['sonuc'] += 1

                frame_time, frame, detections, qr_data, qr_bbox, original_w, original_h = latest_result

                # Check for camera error
                if frame is None and frame_time == -1.0:
                    self._update_status_label("Hata: Kameradan kare okunamadı. Kamera durduruluyor.")
                    self.stop_camera()
                    return

            except queue.Empty:
                return

            display_frame = frame
            current_frame_time = time.time()
            # Karenin ÇEKİLME zamanı (kamera sürecinde, aynı PC saatiyle
            # damgalanır). Ölü zaman telafisi buna dayanıyor.
            self._capture_time = frame_time

            # Kalibrasyon güvenlik ağı: hedef ölçüm sırasında kaybolursa
            # _calibration_tick hiç çağrılmaz ve PID kalıcı olarak askıda
            # kalırdı. Bu kontrol her karede çalıştığı için o durumu yakalar.
            if self._calibrating and (current_frame_time - self._cal_start_time
                                      > self.CALIBRATION_TIMEOUT):
                self._bitir_kalibrasyon("Hata: Kalibrasyon zaman aşımına uğradı (hedef kayboldu?).")

            # Tespit koordinatları ve takip/PID matematiği kameranın HAM çözünürlüğünde
            # yürür; gösterilen kare ise küçültülmüş olabilir. Ham boyutu inference
            # sürecinden alıyoruz, böylece kamera hangi çözünürlüğü verirse versin
            # nişan merkezi doğru kalır.
            self.frame_orig_w = original_w
            self.frame_orig_h = original_h
            center_x_frame, center_y_frame = original_w // 2, original_h // 2

            # Crosshair drawing on the downscaled frame for display
            h, w, ch = display_frame.shape
            # Ham koordinatları gösterim karesine taşımak için ölçek katsayıları
            draw_scale_x = w / original_w if original_w else 1.0
            draw_scale_y = h / original_h if original_h else 1.0
            center_x_display, center_y_display = w // 2, h // 2
            crosshair_color = (0, 255, 0)
            crosshair_size = 10
            cv2.line(display_frame, (center_x_display - crosshair_size, center_y_display),
                     (center_x_display + crosshair_size, center_y_display),
                     crosshair_color, 2)
            cv2.line(display_frame, (center_x_display, center_y_display - crosshair_size),
                     (center_x_display, center_y_display + crosshair_size),
                     crosshair_color, 2)

            self._bilgi_panelini_yenile()

            current_target_bbox_for_pid = None
            detected_class_status = None

            # =========== ANGAJMAN DURUM MAKİNESİ — HER KAREDE BİR ADIM ===========
            # Eskiden bu adım yalnızca aşağıdaki "hedef edinme" dalından
            # çağrılıyordu. Hedefe kilitlenir kilitlenmez o dal devre dışı
            # kalıyor, makine DOĞRULAMA'da donuyor, KİLİT'e hiç geçilemiyordu;
            # dolayısıyla `kilit_adimi` ve otonom ateş fiilen erişilemezdi.
            # Adım artık daldan bağımsız, her karede bir kez atılıyor.
            ciftler = []
            acilar = []
            sanal_hedef = None
            if self.is_target_active and self.active_task in self.OTONOM_MODLAR:
                # GÜVEN FİLTRESİ OTONOM YOLDA UYGULANMIYOR.
                # `_guvene_gore_ayikla` en yüksek skordan 0.15 çıkarıp altındaki
                # HER ŞEYİ atıyor. Yeni mimaride maket ve balon FARKLI sınıflar
                # ve doğal olarak farklı güven seviyelerinde çıkıyorlar; sahada
                # maket 0.56 / balon 0.81 ölçüldü, eşik 0.66 oldu ve MAKET
                # elendi -> çift kurulamadı -> tahmin devreye girdi. Ayrıca
                # tehlikeli bir yan etkisi var: yakın bir DOST (0.80) uzak bir
                # DÜŞMANI (0.50) listeden silebiliyor.
                # Hayalet koruması zaten üç katmanda var: CONF_THRESHOLD,
                # çift geometrisi ve renk tutarlılığı; kimlik kararı ise
                # VERIFY_MIN_CONFIDENCE (0.55) ile ayrıca korunuyor.
                #
                # `tek_balon=True`: yalnız balonlar da listeye giriyor ki KİLİT
                # köprüsü onları kullanabilsin. Doğrulama ve ateş kilidi maketi
                # ayrıca şart koştuğu için güvenlik kaybı yok.
                ciftler = self._ciftleri_sirala(
                    detections, center_x_frame, center_y_frame, tek_balon=True)
                acilar = self._cift_acilari(ciftler)
                # Genel bilgi önce yazılır; makinenin daha özel mesajları
                # (DOST/DÜŞMAN) bunun üstüne yazsın diye.
                self.target_info_label.setText(
                    f"Hedef: {self.angajman.durum} | {len(ciftler)} çift | "
                    f"imha {self.angajman.imha_sayisi}")
                sanal_hedef = self._angajman_adimi(ciftler, acilar)

                # Taret gözcünün verdiği MUTLAK açıya giderken avcı hattındaki
                # eski kilit yaşamamalı: yaşarsa aşağıdaki "YOLO takip" dalı
                # PID'i çalıştırır ve `send_angle_command` ile TARAMA'nın
                # gönderdiği açı arasında iki komut yarışır. Bu durumlarda
                # hedefin tek sahibi durum makinesidir.
                if self.angajman.durum in (BOSTA, TARAMA, YONELME):
                    self.current_tracked_target_class = None
                    self.current_tracked_target_bbox = None
                    self.missing_frames = 0
                    self._aday_ardisik = 0
                    self._aday_konum = None

            elif self.is_target_active and self.active_task == 'takip':
                # HEDEF TAKİP: angajman makinesi yok ama hedef seçimi yine de
                # ÇİFT üzerinden. Eski "takip" dalına bırakılamaz, çünkü o dal
                # hedefi SINIF ADIYLA yeniden buluyor; `_nisan_tespiti` balonun
                # üstüne nişan alıp kutuya MAKETİN sınıf adını yazdığı için
                # taret balona değil maketin kendisine kilitlenirdi.
                # `tek_balon=True`: maket olmadan da (yalnız balon) takip
                # edilebilir — "tespit edilen herhangi bir hedef".
                ciftler = self._ciftleri_sirala(
                    detections, center_x_frame, center_y_frame, tek_balon=True)
                acilar = self._cift_acilari(ciftler)
                secili = self._takip_hedefi_sec(ciftler)
                if secili is not None:
                    self.aktif_cift = secili
                    # `maket_merkezine=True`: balon yoksa MAKETİN TAM ORTASINA
                    # nişan alınır, "balonun olması gereken yer" tahmin
                    # EDİLMEZ. Bu mod bir ölçüm aracı; sahada balonsuz bir
                    # makette nişangah kutunun altına düşüyordu ve kullanıcı
                    # haklı olarak kutunun ortasını bekliyordu.
                    sanal_hedef = self._nisan_tespiti(secili, maket_merkezine=True)
                    self.target_info_label.setText(
                        f"Hedef: {secili.sinif or 'balon'} takip ediliyor "
                        f"({len(ciftler)} aday)")
                else:
                    self.aktif_cift = None
                    self._takip_hedef_kimlik = None
                    self.target_info_label.setText("Hedef Bilgisi: Hedef yok.")

            if self.is_target_active:
                # NOT: Aşama 3'ün eski QR tabanlı akışı BURADAN KALDIRILDI.
                # Koşulu `active_task == 'task3' and waiting_for_new_engagement_command
                # and not is_ready_to_engage_from_qr` idi; `task3()` bu üçünü de
                # sağladığı için Aşama 3'te HER KARE bu dala giriliyor, artık
                # olmayan bir QR kodu bekleniyor ve durum makinesine hiç
                # ulaşılamıyordu. Sahada "Aşama 3'e basıyorum, taret hiç
                # kıpırdamıyor" olarak görüldü (AnalizVideo.mp4, 29-35 sn).
                if sanal_hedef is not None:
                    current_target_bbox_for_pid = self._otonom_hedefi_benimse(
                        sanal_hedef, current_frame_time)
                    if current_target_bbox_for_pid is not None:
                        detected_class_status = sanal_hedef['class_name']

                elif (self.current_tracked_target_class is not None
                      and not self.target_destroyed
                      and self.active_task != 'takip'):
                    # 'takip' bu dala GİRMEZ: hedef görünmediğinde tahmin
                    # yürütmek yerine kilidi bırakıp taretin son açıyı
                    # tutmasını istiyoruz. Bu mod bir ölçüm aracı; tespit
                    # sürekliliğini olduğu gibi göstermesi gerekir.
                    closest_locked_detection = None
                    min_locked_distance = float('inf')

                    last_tracked_center_x = self.current_tracked_target_bbox[0] + self.current_tracked_target_bbox[2] // 2 if self.current_tracked_target_bbox else center_x_frame
                    last_tracked_center_y = self.current_tracked_target_bbox[1] + self.current_tracked_target_bbox[3] // 2 if self.current_tracked_target_bbox else center_y_frame

                    # Yeniden edinme arama merkezi de DÜNYA uzayında tahmin
                    # edilir; piksel uzayında yapılırsa taretin kendi hareketi
                    # hedefin hareketi sanılıp arama yanlış yere bakar.
                    if self.missing_frames > 0 and self._son_gorulen_dunya_yaw is not None:
                        gecen = current_frame_time - self._son_gorulen_zaman
                        ty, tp = self._tahmin_hizi()
                        tahmin_dunya_yaw = self._son_gorulen_dunya_yaw + ty * gecen
                        tahmin_dunya_pitch = self._son_gorulen_dunya_pitch + tp * gecen
                        px, py = self._dunya_to_piksel(
                            tahmin_dunya_yaw, tahmin_dunya_pitch,
                            self._capture_time or current_frame_time)
                        last_tracked_center_x = int(px)
                        last_tracked_center_y = int(py)

                    for det in detections:
                        if det['class_name'] == self.current_tracked_target_class:
                            x, y, det_w, det_h = det['bbox']
                            det_center_x = x + det_w // 2
                            det_center_y = y + det_h // 2
                            distance = np.sqrt((det_center_x - last_tracked_center_x) ** 2 + (det_center_y - last_tracked_center_y) ** 2)

                            if distance < min_locked_distance and distance < self.MAX_REACQUISITION_DISTANCE_PIXELS:
                                min_locked_distance = distance
                                closest_locked_detection = det

                    if closest_locked_detection:
                        current_target_bbox_for_pid = closest_locked_detection['bbox']
                        detected_class_status = closest_locked_detection['class_name']
                        self.target_info_label.setText(
                            f"Hedef: YOLO Takip Ediyor ({detected_class_status}).")
                        self.target_lost_time = 0.0
                        self.missing_frames = 0
                        self.current_tracked_target_bbox = current_target_bbox_for_pid

                        if self.last_target_x is not None and self.last_frame_time is not None:
                            delta_time_for_velocity = current_frame_time - self.last_frame_time
                            if delta_time_for_velocity > 0:
                                self.last_target_velocity_x = (current_target_bbox_for_pid[0] + current_target_bbox_for_pid[2] // 2 - self.last_target_x) / delta_time_for_velocity
                                self.last_target_velocity_y = (current_target_bbox_for_pid[1] + current_target_bbox_for_pid[3] // 2 - self.last_target_y) / delta_time_for_velocity


                        self.last_target_x = current_target_bbox_for_pid[0] + current_target_bbox_for_pid[2] // 2
                        self.last_target_y = current_target_bbox_for_pid[1] + current_target_bbox_for_pid[3] // 2
                        self.last_frame_time = current_frame_time

                        # GERÇEK tespitin dünya açısını sakla. Tahmin bundan
                        # yürütülür; tahmin edilmiş konumlardan türetilmez ki
                        # hata birikmesin.
                        self._son_gorulen_dunya_yaw, self._son_gorulen_dunya_pitch = \
                            self._piksel_to_dunya(self.last_target_x, self.last_target_y,
                                                  self._capture_time or current_frame_time)
                        self._son_gorulen_zaman = current_frame_time

                    else:
                        self.missing_frames += 1

                        if self.missing_frames <= self.MAX_MISSING_FRAMES:
                            self._update_status_label(
                                f"Durum: Hedef kaybedildi, tahminle takip etmeye çalışılıyor ({self.MAX_MISSING_FRAMES - self.missing_frames} kare kaldı).")
                            self.target_info_label.setText("Hedef: Takip Kayboldu. Tahminle hareket ediyor.")

                            # Tahmin DÜNYA uzayında yapılır. Piksel uzayında
                            # yapılırsa taretin kendi dönüşü (120°/s'de 1881
                            # piksel/sn) hedefin hareketi sanılır; hayali hedef
                            # kareyi terk eder ve taret onu kovalar. Sahada
                            # "saçma hareketler" olarak görülen davranış buydu.
                            # Sabit bir hedefin dünya açısı taret dönse de
                            # değişmez, dolayısıyla tahmin doğal olarak durur.
                            if (self._son_gorulen_dunya_yaw is not None
                                    and self.current_tracked_target_bbox is not None):
                                gecen = current_frame_time - self._son_gorulen_zaman
                                ty, tp = self._tahmin_hizi()
                                tahmin_dunya_yaw = self._son_gorulen_dunya_yaw + ty * gecen
                                tahmin_dunya_pitch = self._son_gorulen_dunya_pitch + tp * gecen
                                predicted_x, predicted_y = self._dunya_to_piksel(
                                    tahmin_dunya_yaw, tahmin_dunya_pitch,
                                    self._capture_time or current_frame_time)

                                # GÜVENLİK SINIRI: tahmin karenin makul bir
                                # komşuluğunun dışına çıktıysa artık hedefi
                                # temsil etmiyordur. Bu olduğunda tahminle
                                # devam etmek tareti savuruyor; hedefi kayıp
                                # saymak doğrusu.
                                sinir_x = self.frame_orig_w * self.PREDICTION_LIMIT_FRAMES
                                sinir_y = self.frame_orig_h * self.PREDICTION_LIMIT_FRAMES
                                if (abs(predicted_x - self.frame_orig_w // 2) > sinir_x
                                        or abs(predicted_y - self.frame_orig_h // 2) > sinir_y):
                                    print(f"UYARI: Tahmin kare dışına taştı "
                                          f"({predicted_x:.0f}, {predicted_y:.0f}); hedef kayıp sayılıyor.")
                                    self.missing_frames = self.MAX_MISSING_FRAMES + 1
                                    current_target_bbox_for_pid = None
                                else:
                                    _, _, w_last, h_last = self.current_tracked_target_bbox
                                    current_target_bbox_for_pid = (
                                        int(predicted_x - w_last / 2), int(predicted_y - h_last / 2),
                                        w_last, h_last)
                            else:
                                current_target_bbox_for_pid = None
                        else:
                            current_target_bbox_for_pid = None
                            self.current_tracked_target_class = None
                            self.current_tracked_target_bbox = None
                            self.target_destroyed = True
                            self.waiting_for_new_engagement_command = True
                            self.target_info_label.setText("Hedef: Takip Kayboldu. Yeni hedef aranıyor.")
                            self.reset_pid_state()

                elif self.waiting_for_new_engagement_command or self.current_tracked_target_class is None:
                    candidate_target = None
                    minimum_distance = float('inf')

                    if self.active_task in self.OTONOM_MODLAR:
                        # Otonom aşamalarda hedefi durum makinesi seçer ve o
                        # adım YUKARIDA, her karede zaten atıldı. Buraya
                        # düşülmesi "makine bu karede hedef vermedi" demektir
                        # (TARAMA / YÖNELME, veya çift görünmüyor).
                        self._aday_ardisik = 0
                        self._aday_konum = None
                        current_target_bbox_for_pid = None
                        self.current_tracked_target_class = None
                        self.current_tracked_target_bbox = None
                        self.target_lost_time = 0.0
                    else:
                        # --- HEDEF SEÇİMİ: artık tek nesne değil ÇİFT ---
                        # data.yaml'da tek bir 'balon' sınıfı var, yani balon
                        # dost/düşman bilgisi TAŞIMIYOR. Karar zorunlu olarak
                        # üstündeki maketten geliyor. Eşleştirme geometriktir ve
                        # maketin kutu genişliğine normalize edildiği için
                        # mesafeden bağımsız çalışır; aynı zamanda hayalet
                        # eleyicidir (tek başına duran balon hedef sayılmaz).
                        # Aşama 1 ve manuel modda tek başına duran balon da
                        # kilitlenebilir: kalibrasyon aracının sabit bir piksel
                        # referansına ihtiyacı var ve elde çoğu zaman yalnızca
                        # balon oluyor.
                        ciftler = self._ciftleri_sirala(
                            self._guvene_gore_ayikla(detections),
                            center_x_frame, center_y_frame, tek_balon=True)

                        # Aşama 1 ve tam manuel: yalnızca gösterim amaçlı en
                        # yakın çift işaretlenir, otonom servolama yapılmaz.
                        if ciftler:
                            self.aktif_cift = ciftler[0]
                            sanal = self._nisan_tespiti(ciftler[0])
                            if sanal is not None:
                                candidate_target = sanal
                                detected_class_status = sanal['class_name']
                            self.target_info_label.setText(
                                f"Hedef Bilgisi: {ciftler[0].sinif or 'balon'} algılandı.")
                        else:
                            self.aktif_cift = None
                            self.target_info_label.setText("Hedef Bilgisi: Hedef çifti yok.")

                    # --- Hayalet tespite karşı zamansal onay ---
                    # YOLO tek tük yanlış pozitif üretiyor. Sahada tavanda
                    # red_balloon (0.59) hayaleti gerçek balondan (0.44) YÜKSEK
                    # güvenle çıktı; hedef seçme kuralı "kareye en yakın tespit"
                    # olduğu ve hayalet tam merkezde olduğu için kilitlenildi ve
                    # taret gerçek balona gitmedi. Hayalet yalnızca 2 kare sürdü.
                    # Bu yüzden bir aday, ard arda birkaç karede aynı yerde
                    # görülmeden kilitlenmeye alınmıyor.
                    if candidate_target:
                        cx = candidate_target['bbox'][0] + candidate_target['bbox'][2] // 2
                        cy = candidate_target['bbox'][1] + candidate_target['bbox'][3] // 2
                        if (self._aday_konum is not None
                                and abs(cx - self._aday_konum[0]) <= self.LOCK_CONFIRM_TOL_PX
                                and abs(cy - self._aday_konum[1]) <= self.LOCK_CONFIRM_TOL_PX):
                            self._aday_ardisik += 1
                        else:
                            self._aday_ardisik = 1
                        self._aday_konum = (cx, cy)

                        if self._aday_ardisik < config.LOCK_CONFIRM_FRAMES:
                            # Henüz doğrulanmadı: kilitlenme yok, hareket yok.
                            self._update_status_label(
                                f"Durum: Aday hedef doğrulanıyor "
                                f"({self._aday_ardisik}/{config.LOCK_CONFIRM_FRAMES})...")
                            candidate_target = None
                    else:
                        self._aday_ardisik = 0
                        self._aday_konum = None

                    if candidate_target:
                        self._aday_ardisik = 0
                        self._aday_konum = None
                        self.current_tracked_target_class = candidate_target['class_name']
                        self.current_tracked_target_bbox = candidate_target['bbox']
                        self.target_destroyed = False
                        self.waiting_for_new_engagement_command = False
                        self.target_lost_time = 0.0
                        self.missing_frames = 0
                        current_target_bbox_for_pid = candidate_target['bbox']
                        self.reset_pid_state()

                        self.last_target_x = current_target_bbox_for_pid[0] + current_target_bbox_for_pid[2] // 2
                        self.last_target_y = current_target_bbox_for_pid[1] + current_target_bbox_for_pid[3] // 2
                        self.last_frame_time = current_frame_time
                        self.last_target_velocity_x = 0.0
                        self.last_target_velocity_y = 0.0
                    else:
                        current_target_bbox_for_pid = None
                        self.current_tracked_target_class = None
                        self.current_tracked_target_bbox = None
                        # Otonom aşamalarda bilgi satırının yazarı durum
                        # makinesidir; burada ezilmemeli.
                        if (self.active_task not in self.OTONOM_MODLAR
                                and self.target_destroyed
                                and self.waiting_for_new_engagement_command):
                            self.target_info_label.setText("Hedef Bilgisi: Yok Edildi. Yeni angajman bekleniyor.")
                        self.target_lost_time = 0.0

            # Kilitli hedefin GERÇEK kutularını belirle (çizim bunları kullanır).
            self._kilitli_bboxlar = set()
            self._nisan_alinan_bbox = None
            if sanal_hedef is not None:
                self._kilitli_bboxlar = set(sanal_hedef.get('kaynak_bbox') or ())
                self._nisan_alinan_bbox = sanal_hedef.get('nisan_bbox')
            elif current_target_bbox_for_pid is not None:
                # Manuel / Aşama 1: hedef zaten gerçek bir tespitin kutusu,
                # sanal nişan noktası üretilmiyor.
                self._nisan_alinan_bbox = tuple(
                    int(v) for v in current_target_bbox_for_pid)

            # Tespit kutularını çiz: kilitli hedef kırmızı, aynı sınıftan diğerleri
            # sarı, gerisi yeşil. Kutular ham çözünürlükte geldiği için gösterim
            # karesine ölçeklenir.
            for det in detections:
                x, y, w_det, h_det = [int(v) for v in det['bbox']]
                x = int(x * draw_scale_x)
                y = int(y * draw_scale_y)
                w_det = int(w_det * draw_scale_x)
                h_det = int(h_det * draw_scale_y)

                # KİLİTLİ HEDEF KUTUSU: eskiden koşul
                # `det['bbox'] == current_target_bbox_for_pid` idi ve otonom
                # modda ASLA tutmuyordu — çünkü o bbox `_nisan_tespiti`'nin
                # ürettiği SANAL kutu (nişan noktası etrafında 2r x 2r), sınıf
                # adı da maketin adı. Sonuç: maket "aynı sınıftan diğeri"
                # sayılıp sarı, balon farklı sınıf olduğu için yeşil çiziliyor,
                # hiçbir kutu kırmızı olmuyordu. Artık nişan noktasını ÜRETEN
                # gerçek tespitlerin kutuları işaretleniyor:
                #   kırmızı  = nişan alınan kutu (balon)
                #   turuncu  = kilitli çiftin kimlik kutusu (maket)
                det_bbox = tuple(int(v) for v in det['bbox'])
                if det_bbox == self._nisan_alinan_bbox:
                    yolo_draw_color = (0, 0, 255)      # nişan alınan: kırmızı
                elif det_bbox in self._kilitli_bboxlar:
                    yolo_draw_color = (0, 165, 255)    # kilitli çiftin maketi: turuncu
                elif (self.current_tracked_target_class
                      and det['class_name'] == self.current_tracked_target_class):
                    yolo_draw_color = (0, 255, 255)    # aynı sınıftan diğerleri: sarı
                else:
                    yolo_draw_color = (0, 255, 0)      # gerisi: yeşil

                cv2.rectangle(display_frame, (x, y), (x + w_det, y + h_det), yolo_draw_color, 2)
                cv2.putText(display_frame, f"YOLO: {det['class_name']} ({det['score']:.2f})", (x, y - 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, yolo_draw_color, 1)

            # --- Otonom servolama / kalibrasyon ---
            # Servolama YALNIZCA Aşama 2 ve 3'te. Aşama 1 tamamen manuel olduğu
            # için orada tespit edilen hedef yalnızca ekranda işaretlenir.
            #
            # AMA: `process_tracking` aynı zamanda KALİBRASYON durum makinesinin
            # tek çağıranıdır (`_calibration_tick`). Kalibrasyon `task1` şartı
            # arıyor, servolama ise `OTONOM_MODLAR` şartı — ikisi birbirini
            # dışlıyordu ve "Derece/Piksel Ölç" butonu hiç ilerlemiyordu:
            # ilk mesaj yazılıyor, tick bir kez bile çağrılmıyor, 60 sn sonra
            # zaman aşımına düşüyordu (AnalizVideo.mp4, 10-16 sn).
            # `process_tracking` kalibrasyon sırasında zaten PID'i atlayıp
            # doğrudan tick'e gidiyor, dolayısıyla burada kapıyı açmak taretin
            # Aşama 1'de kendiliğinden hareket etmesine yol açmaz.
            if (current_target_bbox_for_pid and not self.target_destroyed
                    and (self.active_task in self.SERVO_MODLAR or self._calibrating)):
                x_pid, y_pid, w_pid, h_pid = [int(v) for v in current_target_bbox_for_pid]
                target_center_x = x_pid + w_pid // 2
                target_center_y = y_pid + h_pid // 2
                self.process_tracking(target_center_x, target_center_y, display_frame, 0, current_frame_time)
            else:
                self.reset_pid_state()
                self.is_aimed_at_target = False
                if self.active_task not in ['full_manual'] and self.active_task not in self.OTONOM_MODLAR:
                    if not self.target_destroyed and not self.waiting_for_new_engagement_command:
                        self.target_info_label.setText("Hedef Bilgisi: Yok.")

                # NOT: burada eskiden Aşama 3 için "eve dön" yolu vardı
                # (`process_tracking_to_home_position`). O da QR akışının
                # parçasıydı ve `engagement_home_position` hiçbir zaman
                # ayarlanmadığı için taret her hedef kaybında (0,0)'a
                # sürülüyordu. Angajman makinesi hedef kaybını zaten kendi
                # yönetiyor (TARAMA'ya döner ve sıradaki adaya yönelir);
                # ikisi aynı anda çalışsaydı taret iki farklı açıya
                # çekiştirilirdi. Kaldırıldı.

            # --- Durum metinleri ---
            # DİKKAT: buradaki eski OTOMATİK ATEŞ yolları KALDIRILDI.
            # Aşama 2 ateşi `detected_class_status == "red_balloon"` gibi artık
            # var olmayan bir sınıf adına bakıyordu; Aşama 3 ise HİÇBİR sınıf
            # kontrolü yapmıyordu ve TAHMİN EDİLMİŞ (görülmemiş) bir hedefe
            # ateş edebiliyordu. Ateş kararının tek yeri artık
            # `_otonom_ates_denemesi()` ve `engagement.ates_serbest_mi()`;
            # orada dokuz koşul birden aranıyor.
            #
            # DURUM ÇUBUĞU: her mod için TEK yazar.
            # Eskiden son dal `elif self.active_task != 'task3_setup'` idi ve
            # Aşama 2/3 dahil her karede koşulsuz "Durum: Hazır." yazıyordu.
            # `task2()`/`_task3_baslat()`'ın yazdığı mesaj ve angajman
            # makinesinin bütün ara durumları 40 ms sonra siliniyordu; sahada
            # Aşama 2 ve 3 boyunca ekranda yalnızca "Hazır." görülüyordu ve
            # sistemin ne yaptığı hiç anlaşılamıyordu. Otonom aşamalarda yazar
            # artık `_angajman_adimi` (ve ateş engellenirse
            # `_otonom_ates_denemesi`); burası onlara dokunmuyor.
            if self.active_task == 'task1':
                if self._calibrating:
                    pass  # kalibrasyon durum makinesi kendi metnini yazıyor
                else:
                    self._update_status_label(
                        "Durum: Aşama 1 - Tam manuel kontrol (ok tuşları + ATEŞ ET).")
            elif self.active_task == 'full_manual':
                if self.is_in_no_fire_zone(self.current_yaw_angle):
                    self._update_status_label(
                        f"Durum: Tam Manuel Kontrol Modu - Ateşsiz Bölgede! Yaw: {self.current_yaw_angle:.1f}°, Pitch: {self.current_pitch_angle:.1f}°")
                else:
                    self._update_status_label(
                        f"Durum: Tam Manuel Kontrol Modu - Yaw: {self.current_yaw_angle:.1f}°, Pitch: {self.current_pitch_angle:.1f}°")
                self.target_info_label.setText("Hedef Bilgisi: Kullanıcı Kontrollü.")
            elif self.active_task == 'takip':
                # Bu mod bir ÖLÇÜM ARACI: canlı nişan hatasını hem piksel hem
                # derece cinsinden, tolerans bilgisiyle birlikte yaz.
                if current_target_bbox_for_pid:
                    _bx, _by, _bw, _bh = current_target_bbox_for_pid
                    _ex = (_bx + _bw // 2) - self.frame_orig_w // 2
                    _ey = (_by + _bh // 2) - self.frame_orig_h // 2
                    _e = (_ex ** 2 + _ey ** 2) ** 0.5
                    _r = max(_bw, _bh) / 2.0
                    _tol = max(config.AIM_TOLERANCE_MIN_PIXELS,
                               _r * config.AIM_TOLERANCE_RATIO)
                    self._update_status_label(
                        f"Takip: hata {_e:.0f} px = "
                        f"{_e * abs(self.DEGREES_PER_PIXEL_YAW):.3f}° "
                        f"(yaw {_ex:+.0f}, pitch {_ey:+.0f}) | "
                        f"tolerans {_tol:.0f} px -> "
                        f"{'İÇİNDE' if _e <= _tol else 'dışında'}")
                else:
                    self._update_status_label(
                        "Durum: Hedef Takip — hedef aranıyor (otonom ateş YOK).")
            elif self.active_task in self.OTONOM_MODLAR:
                pass
            elif self.active_task != 'task3_setup':
                self._update_status_label("Durum: Hazır.")
                self.target_info_label.setText("Hedef Bilgisi: Yok.")

            self._display_frame(display_frame)
            self.frame_counter += 1

        except Exception as main_loop_error:
            self._tani['hata'] += 1
            print(f"KRİTİK HATA: update_frame ana döngüsünde beklenmedik hata: {main_loop_error}")
            traceback.print_exc()
            self._update_status_label(f"KRİTİK HATA: UI Güncelleme Hatası: {str(main_loop_error)[:50]}...")

    def is_in_no_fire_zone(self, current_yaw_angle):
        zone_start = self.no_fire_yaw_start
        zone_end = self.no_fire_yaw_end
        normalized_yaw = (current_yaw_angle + 180) % 360 - 180

        if zone_start <= zone_end:
            is_within_zone = self.no_fire_yaw_start <= normalized_yaw <= self.no_fire_yaw_end
        else:
            is_within_zone = normalized_yaw >= self.no_fire_yaw_start or normalized_yaw <= self.no_fire_yaw_end

        return is_within_zone

    def is_in_movement_restricted_zone(self, target_yaw_angle):
        is_within_zone = False
        start = self.movement_restricted_yaw_start
        end = self.movement_restricted_yaw_end

        target_yaw_angle = target_yaw_angle % 360
        if target_yaw_angle < 0:
            target_yaw_angle += 360

        start_normalized = start % 360
        if start_normalized < 0:
            start_normalized += 360

        end_normalized = end % 360
        if end_normalized < 0:
            end_normalized += 360

        if start_normalized <= end_normalized:
            if start_normalized <= target_yaw_angle <= end_normalized:
                is_within_zone = True
        else:
            if target_yaw_angle >= start_normalized or target_yaw_angle <= end_normalized:
                is_within_zone = True
        return is_within_zone

    # İlk karenin gerçekten çizildiğini konsola bir kez bildirmek için.
    _ilk_kare_bildirildi = False

    def _display_frame(self, frame):
        try:
            if frame is None or frame.size == 0:
                if not self._ilk_kare_bildirildi:
                    print("TANI: _display_frame BOS KARE aldi")
                return

            try:
                rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_image.shape
                bytes_per_line = ch * w
                if not rgb_image.flags['C_CONTIGUOUS']:
                    rgb_image = np.ascontiguousarray(rgb_image)
                qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
                # Qt.SmoothTransformation ZORUNLU: varsayılan Qt.FastTransformation
                # en yakın komşu demek. Etiket 1920x1080, kare 1280x720 olduğu
                # için 1.5 kat büyütme yapılıyor ve en yakın komşuyla bu
                # merdivenli/bulanık görünüyordu. Sahada "kamera netsiz" diye
                # görülen sorunun ikinci yarısı buydu.
                pixmap_obj = qt_image.scaled(self.camera_label.width(), self.camera_label.height(),
                                             Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.camera_label.setPixmap(QPixmap.fromImage(pixmap_obj))
                self._tani['ciz'] += 1
                if not self._ilk_kare_bildirildi:
                    self._ilk_kare_bildirildi = True
                    print(f"TANI: ilk kare cizildi | kaynak {w}x{h} | "
                          f"etiket {self.camera_label.width()}x{self.camera_label.height()} | "
                          f"pixmap {pixmap_obj.width()}x{pixmap_obj.height()} | "
                          f"etiket gorunur: {self.camera_label.isVisible()}")
            except Exception:
                # Konsola TAM izi yaz: durum çubuğundaki 50 karakterlik kırpılmış
                # mesajla hata ayıklamak imkânsız.
                traceback.print_exc()
                self._update_status_label("Hata: Görüntü dönüşüm hatası (ayrıntı konsolda)")
        except Exception:
            traceback.print_exc()
            self._update_status_label("Hata: Görüntüleme hatası (ayrıntı konsolda)")

    def process_tracking(self, target_x, target_y, frame, target_area_unused, current_frame_time):
        if not self.rpi_thread.is_connected or self.active_task == 'full_manual' or self.target_destroyed:
            return

        # Kalibrasyon sırasında taret hedefi ortalamamalı; ölçüm bilinen bir açı
        # komutuna karşılık gelen piksel kaymasına dayanıyor.
        if self._calibrating:
            self._calibration_tick(target_x, target_y)
            return

        # Hedef koordinatları kameranın ham çözünürlüğüne göredir; gösterilen kare
        # küçültülmüş olabileceği için merkez, frame'den değil ham boyuttan alınır.
        center_x = self.frame_orig_w // 2
        center_y = self.frame_orig_h // 2

        error_yaw_pixel = target_x - center_x
        error_pitch_pixel = target_y - center_y

        # Piksel hatasının derece karşılığı. DİKKAT: bu hata, kamera karesinin
        # ÇEKİLDİĞİ andaki durumu yansıtır; "şu an"ı değil.
        capture_error_yaw = error_yaw_pixel * self.DEGREES_PER_PIXEL_YAW
        capture_error_pitch = error_pitch_pixel * self.DEGREES_PER_PIXEL_PITCH

        # Nişan toleransı balonun YARIÇAPININ oranı olarak tanımlı. Sabit
        # piksel eşiği mesafeye göre anlam değiştirirdi: balon 15 metrede
        # avcıda 30 piksel, 5 metrede 90 piksel. Oran ikisinde de aynı
        # fiziksel isabet payına karşılık gelir.
        _yaricap = None
        if self.current_tracked_target_bbox:
            _yaricap = max(self.current_tracked_target_bbox[2],
                           self.current_tracked_target_bbox[3]) / 2.0
        _tolerans = config.AIM_TOLERANCE_MIN_PIXELS
        if _yaricap:
            _tolerans = max(_tolerans, _yaricap * config.AIM_TOLERANCE_RATIO)
        self.is_aimed_at_target = (abs(error_yaw_pixel) <= _tolerans and
                                   abs(error_pitch_pixel) <= _tolerans)

        # --- ÖLÜ ZAMAN TELAFİSİ ---
        # Kamera + çıkarım gecikmesi boyunca (~100-200 ms) taret hareket etmeye
        # devam eder. Bayat hatayı taretin ŞU ANKİ açısına eklemek, o sürede kat
        # edilen yolu İKİ KEZ saymak demektir; taret hedefi aşar ve geri döner.
        # Ölçümde bu, gecikmeyle büyüyen 150-340 pikselllik aşım üretiyordu.
        #
        # Doğrusu: hatayı kare çekildiğindeki açıya ekleyip hedefin DÜNYA
        # açısını bulmak, sonra düzeltmeyi taretin şu anki açısına göre
        # hesaplamak. Böylece aşım gecikmeden bağımsız hale gelir.
        # Kare zaman damgası sensörün POZLADIĞI an değil, karenin OKUNDUĞU
        # andır. Aradaki USB + MJPG boru hattı gecikmesi CAPTURE_LATENCY_OFFSET
        # ile geriye alınır; telafi edilmezse taret hızlıyken hedefin dünya
        # açısı ileride hesaplanır ve taret hedefi aşar.
        capture_t = self._capture_time if self._capture_time is not None else current_frame_time
        capture_t -= config.CAPTURE_LATENCY_OFFSET
        yaw_at_capture, pitch_at_capture = self._angle_at(capture_t)

        world_yaw = yaw_at_capture + capture_error_yaw
        world_pitch = pitch_at_capture + capture_error_pitch

        error_yaw_degree = (world_yaw - self.current_yaw_angle + 180) % 360 - 180
        error_pitch_degree = (world_pitch - self.current_pitch_angle + 180) % 360 - 180

        # Kilit durumundayken nişan tutuldu mu diye durum makinesini besle.
        # Ateş, tolerans AIM_HOLD_FRAMES kare korunduktan sonra serbest kalır.
        if self.angajman.durum == KILIT:
            _hata_px = (error_yaw_pixel ** 2 + error_pitch_pixel ** 2) ** 0.5
            self.angajman.kilit_adimi(_hata_px, _yaricap or 8.0,
                                      self.balon_gercek_goruldu)
        if self.angajman.durum == ATES:
            self._otonom_ates_denemesi()

        # OTONOM MODLARDA DURUM ÇUBUĞUNUN TEK YAZARI `_angajman_adimi`.
        #
        # Bu satır eskiden otonom modda da çalışıyor ve durum makinesinin
        # yazdığı mesajı AYNI KAREDE eziyordu. Sonuç: sistemin hangi durumda
        # olduğu ekranda hiç görünmüyordu. Sahada ölçüldü (analizaşama3.mp4):
        # 2.6 saniyeden 11.8 saniyeye kadar kesintisiz "Hedefe nişan alındı"
        # yazdı; sistem o sırada KİLİT'te takılıydı ve TARAMA'ya dönüp aynı
        # hedefi geri seçiyordu — ama bu ekrandan okunamadığı için sorunun
        # nerede olduğu ancak videodan piksel ölçerek bulunabildi.
        #
        # Artık yalnızca MANUEL/Aşama 1 yolunda yazılıyor. Otonom modda nişan
        # bilgisi `_angajman_adimi`'nin KİLİT mesajına ekleniyor.
        if (self.is_aimed_at_target
                and self.active_task not in self.OTONOM_MODLAR
                and not self.target_destroyed):
            current_time = time.time()
            if current_time - self.last_fire_time >= self.fire_cooldown_interval:
                try:
                    self._update_status_label("Durum: Hedefe nişan alındı, otomatik ateş bekleniyor...")
                except Exception:
                    pass

        delta_time = current_frame_time - self.pid_update_time
        self.pid_update_time = current_frame_time

        # --- Hız ileri-beslemesi ---
        # Saf oransal denetim hareketli hedefte kalıcı olarak geride kalır:
        # çıkış ancak hata sıfırdan farklıysa üretilir, dolayısıyla kayan bir
        # hedefte hata hiç kapanmaz. Bu terim, hedefin ölçüm gecikmesi boyunca
        # kat edeceği yolu önceden ekleyerek o gecikmeyi telafi eder.
        #
        # Hedefin DÜNYA açısı = taretin açısı + hatanın derece karşılığı.
        # Türevi hedefin gerçek açısal hızını verir. (Piksel hızını kullanmak
        # işe yaramaz: takip çalışırken hedef karede merkezde kalır, piksel hızı
        # sıfıra yakın çıkar.) Gürültüye karşı EMA ile yumuşatılır.
        # world_yaw / world_pitch yukarıda ölü zaman telafisiyle zaten hesaplandı
        # (hedefin dünyadaki açısı); burada yalnızca türevi alınıyor.
        if self._last_world_time is not None:
            dt_world = current_frame_time - self._last_world_time
            if dt_world > 0:
                ham_yaw_rate = (world_yaw - self._last_world_yaw) / dt_world
                ham_pitch_rate = (world_pitch - self._last_world_pitch) / dt_world

                # ASİMETRİK yumuşatma: hız azalırken daha hızlı sön.
                # Simetrik olduğunda hedef durduğu anda tahmin birkaç kare
                # boyunca yüksek kalıyor, feedforward itmeye devam ediyor ve
                # taret hedefi geçip geri dönüyordu. Hız artarken yavaş kalmak
                # ise gürültü sıçramalarını reddetmek için gerekli.
                a_yaw = self._hiz_alfa(ham_yaw_rate, self.target_world_yaw_rate)
                a_pitch = self._hiz_alfa(ham_pitch_rate, self.target_world_pitch_rate)

                self.target_world_yaw_rate = (a_yaw * ham_yaw_rate
                                              + (1 - a_yaw) * self.target_world_yaw_rate)
                self.target_world_pitch_rate = (a_pitch * ham_pitch_rate
                                                + (1 - a_pitch) * self.target_world_pitch_rate)

                # Fiziksel üst sınır. Gerçek bir hedef bu hızı aşmaz; aşan bir
                # tahmin hesap hatasıdır ve sınırlanmazsa hem feedforward'ı hem
                # kayıp anındaki tahmini katlanarak büyütür.
                r = self.MAX_TARGET_RATE_DEG_S
                self.target_world_yaw_rate = max(-r, min(r, self.target_world_yaw_rate))
                self.target_world_pitch_rate = max(-r, min(r, self.target_world_pitch_rate))
        self._last_world_yaw = world_yaw
        self._last_world_pitch = world_pitch
        self._last_world_time = current_frame_time

        # --- Feedforward kapıları ---
        # Üç ayrı kapı var; üçü de aynı gerçeğe dayanıyor: hız tahmininin
        # güvenilirliği duruma göre çok değişiyor ve feedforward güvenilmez
        # olduğu anda zarar veriyor.

        # 1) YUMUŞAK ÖLÜ BANT. Sert eşik, hız eşiği geçtiği anda feedforward'ı
        #    sıfırdan tam değerine sıçratıyordu (4 °/s eşikte 0.7° = 13 piksel).
        #    Hedef yön değiştirirken hız sıfırdan geçtiği için bu sıçrama her
        #    yön değişiminde yaşanıyor ve sahada "bir anda salınım başlıyor"
        #    olarak görülüyordu. Artık ölü bant ile iki katı arasında 0'dan
        #    1'e doğrusal olarak açılıyor.
        db = config.FEEDFORWARD_VELOCITY_DEADBAND

        def _db_katsayi(hiz):
            m = abs(hiz)
            if m <= db:
                return 0.0
            if m >= 2 * db:
                return 1.0
            return (m - db) / db

        # 2) HATA KAPISI. Feedforward'ın işi, KİLİTLİ takipte hedefin ölçüm
        #    gecikmesi boyunca kat ettiği yolu telafi etmek. Hata büyükken
        #    (edinme manevrası) taret tepe hızında dönüyor ve tam o anda açı
        #    telemetrisi en güvenilmez halinde: Pi adım atarken gönderici iş
        #    parçacığı gecikiyor, 15 ms'lik bir gecikme 89 °/s'de 1.3° = 25
        #    piksel açı hatası demek. Bu hata hız tahminine sızıyor, sızıntı
        #    feedforward'ı besliyor, feedforward tareti daha hızlı döndürüyor
        #    ve sızıntı büyüyor — pozitif geri besleme. Sahada 10 saniye süren
        #    ±4° salınım buydu. Zaten hata büyükken oransal terim feedforward'ın
        #    yüz katı; kapatmanın hiçbir maliyeti yok.
        hata_px = math.hypot(error_yaw_degree / self.DEGREES_PER_PIXEL_YAW,
                             error_pitch_degree / self.DEGREES_PER_PIXEL_PITCH)
        tam, sifir = config.FEEDFORWARD_ERROR_GATE_PIXELS
        if hata_px >= sifir:
            kapi = 0.0
        elif hata_px <= tam:
            kapi = 1.0
        else:
            kapi = (sifir - hata_px) / (sifir - tam)

        k_yaw = _db_katsayi(self.target_world_yaw_rate) * kapi
        k_pitch = _db_katsayi(self.target_world_pitch_rate) * kapi

        lead = config.FEEDFORWARD_LEAD_TIME * config.FEEDFORWARD_GAIN
        feedforward_yaw = self.target_world_yaw_rate * lead * k_yaw
        feedforward_pitch = self.target_world_pitch_rate * lead * k_pitch

        # Hatalı bir hız tahmininin tareti savurmasını engelle
        ff_limit = config.FEEDFORWARD_MAX_DEGREE
        feedforward_yaw = max(-ff_limit, min(ff_limit, feedforward_yaw))
        feedforward_pitch = max(-ff_limit, min(ff_limit, feedforward_pitch))

        # 3) DEĞİŞİM HIZI SINIRI. Yukarıdaki iki kapıdan sonra bile hız tahmini
        #    kare kare zıplayabiliyor ve feedforward onu aynen aktarıyor. Bu,
        #    takibin "akıcı" değil "kasıntılı" görünmesinin doğrudan sebebi.
        #    Ölçümde yön değiştirme sayısı 157'den 69'a indi, üstelik ortalama
        #    hata da 32.2'den 31.4 piksele düştü — yani yumuşatmanın bedeli yok.
        adim = config.FEEDFORWARD_MAX_STEP_DEGREE
        feedforward_yaw = self._ff_onceki_yaw + max(
            -adim, min(adim, feedforward_yaw - self._ff_onceki_yaw))
        feedforward_pitch = self._ff_onceki_pitch + max(
            -adim, min(adim, feedforward_pitch - self._ff_onceki_pitch))
        self._ff_onceki_yaw = feedforward_yaw
        self._ff_onceki_pitch = feedforward_pitch

        self.integral_yaw += error_yaw_degree * delta_time
        self.integral_yaw = max(min(self.integral_yaw, 20.0), -20.0)

        derivative_yaw = (error_yaw_degree - self.last_error_yaw) / delta_time if delta_time > 0 else 0
        output_yaw = (self.KP_YAW * error_yaw_degree +
                      self.KI_YAW * self.integral_yaw +
                      self.KD_YAW * derivative_yaw +
                      feedforward_yaw)
        self.last_error_yaw = error_yaw_degree

        self.integral_pitch += error_pitch_degree * delta_time
        self.integral_pitch = max(min(self.integral_pitch, 20.0), -20.0)

        derivative_pitch = (error_pitch_degree - self.last_error_pitch) / delta_time if delta_time > 0 else 0
        output_pitch = (self.KP_PITCH * error_pitch_degree +
                        self.KI_PITCH * self.integral_pitch +
                        self.KD_PITCH * derivative_pitch +
                        feedforward_pitch)
        self.last_error_pitch = error_pitch_degree

        if abs(error_yaw_degree) < self.pid_deadband_yaw:
            output_yaw = 0.0
            self.integral_yaw = 0.0
        if abs(error_pitch_degree) < self.pid_deadband_pitch:
            output_pitch = 0.0
            self.integral_pitch = 0.0

        # --- REZONANS SÖNÜMLEME ---
        # Sahada ölçüldü: kilit salınımının %91-96'sı taretin KENDİ hareketi
        # ve baskın frekansı 2.24-3.15 Hz — FAZ 3'te ölçülen yapısal
        # rezonansla (2.7 Hz) aynı bant. Denetleyici saf oransal olduğu ve
        # döngüde ~185 ms ölü zaman bulunduğu için o frekansta salınıyor.
        #
        # Birinci derece alçak geçiren süzgeç: DC kazancı 1.0 kalır (hedefe
        # oturma hızı değişmez), rezonans bandındaki bileşen bastırılır.
        # Ölü bant SONRASINA konuldu ki süzgecin hafızası sıfır çıkışta da
        # boşalsın; aksi halde deadband'a girildiğinde süzgeç eski değeri
        # sızdırmaya devam ederdi.
        _a = config.PID_OUTPUT_SMOOTHING
        if _a > 0.0:
            output_yaw = _a * output_yaw + (1.0 - _a) * self._pid_cikis_yaw
            output_pitch = _a * output_pitch + (1.0 - _a) * self._pid_cikis_pitch
            self._pid_cikis_yaw = output_yaw
            self._pid_cikis_pitch = output_pitch

        if 0 < abs(output_yaw) < self.MIN_OUTPUT_DEGREE_THRESHOLD:
            output_yaw = 0.0
        if 0 < abs(output_pitch) < self.MIN_OUTPUT_DEGREE_THRESHOLD:
            output_pitch = 0.0

        output_yaw = max(min(output_yaw, self.MAX_OUTPUT_DEGREE), -self.MAX_OUTPUT_DEGREE)
        output_pitch = max(min(output_pitch, self.MAX_OUTPUT_DEGREE), -self.MAX_OUTPUT_DEGREE)

        if self.active_task == 'task3':
            predicted_yaw_after_move = self.current_yaw_angle + output_yaw
            if self.is_in_movement_restricted_zone(predicted_yaw_after_move):
                output_yaw = 0.0
                print("Uyarı: Hedef Yaw açısı kısıtlı hareket bölgesinde! Yaw hareketi engellendi.")

        if output_yaw != 0.0 or output_pitch != 0.0:
            self.send_proportional_move_command(output_yaw, output_pitch)
        else:
            self.target_info_label.setText(
                f"Hedef: Nişan Alındı. Hata: Yaw {error_yaw_pixel}px, Pitch {error_pitch_pixel}px")

        self.last_target_x = target_x
        self.last_target_y = target_y
        self.last_frame_time = current_frame_time

        self.target_info_label.setText(
            f"Hedef: Takip Ediliyor. Hata: Yaw {error_yaw_pixel}px, Pitch {error_pitch_pixel}px")

    def process_tracking_to_home_position(self):
        if not self.rpi_thread.is_connected or self.active_task == 'full_manual':
            return

        current_yaw, current_pitch = self.current_yaw_angle, self.current_pitch_angle

        target_yaw_home = self.engagement_home_position_yaw
        target_pitch_home = self.engagement_home_position_pitch

        error_yaw_degree = target_yaw_home - current_yaw
        error_pitch_degree = target_pitch_home - current_pitch

        error_yaw_degree = (error_yaw_degree + 180) % 360 - 180
        error_pitch_degree = (error_pitch_degree + 180) % 360 - 180

        if abs(error_yaw_degree) < 0.5 and abs(error_pitch_degree) < 0.5:
            self._update_status_label(f"Durum: Ana konuma ulaşıldı. Yeni QR bekleniyor.")
            return

        current_time = time.time()
        delta_time = current_time - self.pid_update_time
        self.pid_update_time = current_time

        new_pid_range_home = "ANA_KONUM"
        if self.current_pid_range != new_pid_range_home:
            self.reset_pid_state()
            self.current_pid_range = new_pid_range_home

        actual_Kp_yaw = self.KP_YAW
        actual_Ki_yaw = self.KI_YAW
        actual_Kd_yaw = self.KD_YAW
        actual_Kp_pitch = self.KP_PITCH
        actual_Ki_pitch = self.KI_PITCH
        actual_Kd_pitch = self.KD_PITCH

        self.integral_yaw += error_yaw_degree * delta_time
        self.integral_yaw = max(min(self.integral_yaw, 20.0), -20.0)

        derivative_yaw = (error_yaw_degree - self.last_error_yaw) / delta_time if delta_time > 0 else 0
        output_yaw = actual_Kp_yaw * error_yaw_degree + actual_Ki_yaw * self.integral_yaw + actual_Kd_yaw * derivative_yaw
        self.last_error_yaw = error_yaw_degree

        self.integral_pitch += error_pitch_degree * delta_time
        self.integral_pitch = max(min(self.integral_pitch, 20.0), -20.0)

        derivative_pitch = (error_pitch_degree - self.last_error_pitch) / delta_time if delta_time > 0 else 0
        output_pitch = actual_Kp_pitch * error_pitch_degree + actual_Ki_pitch * self.integral_pitch + actual_Kd_pitch * derivative_pitch
        self.last_error_pitch = error_pitch_degree

        if abs(error_yaw_degree) < self.pid_deadband_yaw:
            output_yaw = 0.0
            self.integral_yaw = 0.0
        if abs(error_pitch_degree) < self.pid_deadband_pitch:
            output_pitch = 0.0
            self.integral_pitch = 0.0

        if 0 < abs(output_yaw) < self.MIN_OUTPUT_DEGREE_THRESHOLD:
            output_yaw = 0.0
        if 0 < abs(output_pitch) < self.MIN_OUTPUT_DEGREE_THRESHOLD:
            output_pitch = 0.0

        output_yaw = max(min(output_yaw, self.MAX_OUTPUT_DEGREE), -self.MAX_OUTPUT_DEGREE)
        output_pitch = max(min(output_pitch, self.MAX_OUTPUT_DEGREE), -self.MAX_OUTPUT_DEGREE)

        if output_yaw != 0.0 or output_pitch != 0.0:
            self.send_proportional_move_command(output_yaw, output_pitch)
        else:
            self._update_status_label(
                f"Durum: Ana konum ulaşıldı: Yaw {current_yaw:.1f}°, Pitch {current_pitch:.1f}°")
            return

        self.target_info_label.setText(
            f"Hedef: Ana Konuma Dönülüyor. Hata: Yaw {error_yaw_degree:.1f}°, Pitch {error_pitch_degree:.1f}°")

    def mouse_move_event(self, event):
        if self.crosshair_movable:
            self.crosshair_x = event.x()
            self.crosshair_y = event.y()
            self.camera_label.update()

    def _etiket_to_kare(self, x, y):
        """
        Fare (etiket) koordinatını KAMERA HAM piksel koordinatına çevirir.

        Arada üç ayrı ölçek var ve üçü de birbirinden farklı olabilir:

            etiket (Qt mantıksal piksel, DPI ölçeklemesine bağlı)
              -> pixmap (KeepAspectRatio ile sığdırılmış, QLabel ORTALAR)
              -> gösterim karesi (config.DISPLAY_WIDTH)
              -> kamera ham karesi (HUNTER_WIDTH)

        Eski kod yalnızca `camera_label.width()` kullanıyordu. Pixmap
        etiketten küçük olduğunda (DPI ölçeklemesi veya en-boy farkı) QLabel
        onu ortalar; bu durumda hem ölçek hem de kenar boşluğu hesaba
        katılmadığı için tıklama yanlış piksele düşüyordu.

        Döner: (ham_x, ham_y) veya tıklama görüntünün dışındaysa None.
        """
        pm = self.camera_label.pixmap()
        if pm is None or not self.frame_orig_w or not self.frame_orig_h:
            return None
        # Yüksek DPI'da pixmap CİHAZ pikseli tutar; mantıksal boyuta çevir.
        dpr = pm.devicePixelRatio() or 1.0
        pw = pm.width() / dpr
        ph = pm.height() / dpr
        if pw <= 0 or ph <= 0:
            return None
        # QLabel pixmap'i ortalar; sol/üst kenar boşluğu bu.
        ofs_x = (self.camera_label.width() - pw) / 2.0
        ofs_y = (self.camera_label.height() - ph) / 2.0
        px = x - ofs_x
        py = y - ofs_y
        if not (0 <= px < pw and 0 <= py < ph):
            return None
        return px * self.frame_orig_w / pw, py * self.frame_orig_h / ph

    def mouse_press_event(self, event):
        if not (self.crosshair_movable and event.button() == Qt.LeftButton):
            return

        nokta = self._etiket_to_kare(event.x(), event.y())
        if nokta is None:
            self._update_status_label(
                "Uyarı: Tıklama görüntü alanının dışında (veya kare yok).",
                oncelikli=True, sure=2.0)
            return
        ham_x, ham_y = nokta

        # HEDEF AÇI, "şu anki açı + tıklama farkı" DEĞİL, tıklanan pikselin
        # DÜNYA açısı olarak hesaplanıyor.
        #
        # Eski yol `current_yaw_angle + delta` idi ve iki ayrı zamanı
        # karıştırıyordu: piksel, karenin ÇEKİLDİĞİ ana ait; `current_yaw_angle`
        # ise ŞU ANA. Taret önceki komuttan hâlâ yol alıyorsa (ya da yapısal
        # çınlama sönmemişse) aradaki fark tıklama farkından BÜYÜK olabiliyor
        # ve küçük tıklamalar ters yöne komut üretiyordu — sahada
        # "nişangahın hemen sağına tıklıyorum, taret sola gidiyor; uzağa
        # tıklayınca doğru gidiyor" olarak görüldü. Uzak tıklamada fark
        # gecikmeyi bastırdığı için sorun görünmüyordu.
        #
        # `_piksel_to_dunya` pikseli KARE ÇEKİLME anındaki taret açısıyla
        # eşleştirir; piksel ve açı aynı ana ait olduğu için gecikme sadeleşir.
        # PID de tam olarak bu dönüşümü kullanıyor.
        zaman = self._capture_time or time.time()
        hedef_yaw, hedef_pitch = self._piksel_to_dunya(ham_x, ham_y, zaman)

        pm = self.camera_label.pixmap()
        print(f"Fare tıklaması: etiket=({event.x()},{event.y()}) "
              f"etiket_boyut={self.camera_label.width()}x{self.camera_label.height()} "
              f"pixmap={pm.width()}x{pm.height()} (dpr={pm.devicePixelRatio():g}) "
              f"ham=({ham_x:.0f},{ham_y:.0f})/{self.frame_orig_w}x{self.frame_orig_h}")
        print(f"Manuel Tıklama Hedef Açılar: Yaw {hedef_yaw:.2f}°, "
              f"Pitch {hedef_pitch:.2f}° (mevcut {self.current_yaw_angle:.2f}°, "
              f"{self.current_pitch_angle:.2f}°)")
        # force=True: tek seferlik operatör komutu 0.1 sn'lik hız sınırına
        # takılıp sessizce düşmemeli.
        self.send_angle_command(hedef_yaw, hedef_pitch, force=True)


if __name__ == '__main__':
    # Needed for multiprocessing on Windows and sometimes Linux depending on the context
    mp.freeze_support()

    # Create queues
    camera_cmd_q = mp.Queue()
    frame_q = mp.Queue(maxsize=2)
    inference_cmd_q = mp.Queue()
    result_q = mp.Queue(maxsize=2)
    # Gözcü kendi sürecinde hem yakalar hem analiz eder. Kareyi kuyruğa
    # koymak pahalı (2.7 MB pickle/kare); analizi yakalayan süreçte yapıp
    # yalnızca birkaç yüz baytlık sonucu göndermek doğru tasarım.
    spotter_cmd_q = mp.Queue()
    spotter_result_q = mp.Queue(maxsize=2)

    # Start processes
    cam_process = mp.Process(target=camera_worker,
                             args=(camera_cmd_q, frame_q, "hunter"))
    cam_process.daemon = True
    cam_process.start()

    spotter_process = mp.Process(target=spotter_worker,
                                 args=(spotter_cmd_q, spotter_result_q))
    spotter_process.daemon = True
    spotter_process.start()

    inf_process = mp.Process(target=inference_worker, args=(inference_cmd_q, frame_q, result_q))
    inf_process.daemon = True
    inf_process.start()

    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    window = HavaSavunmaArayuz(camera_cmd_q, inference_cmd_q, result_q,
                               spotter_cmd_q, spotter_result_q)
    window.surecler = {'kamera': cam_process, 'cikarim': inf_process,
                       'gozcu': spotter_process}
    window.showMaximized()

    try:
        sys.exit(app.exec_())
    except Exception as e:
        print(f"Uygulama beklenmedik bir hata ile kapandı: {e}")
        traceback.print_exc()
    finally:
        # Cleanup
        camera_cmd_q.put("QUIT")
        inference_cmd_q.put({"action": "QUIT"})
        spotter_cmd_q.put("QUIT")
        cam_process.join(timeout=2)
        inf_process.join(timeout=2)
        spotter_process.join(timeout=2)
        for surec in (cam_process, inf_process, spotter_process):
            if surec.is_alive():
                surec.terminate()
