# motor_fire_module.py
# Bu dosya, Raspberry Pi üzerindeki tüm GPIO tabanlı motor ve ateşleme controlünü yönetir.
# control1.py'deki akıcı ve eşzamanlı motor kontrol mantığı ve parametreleri entegre edilmiştir.

import sys
import time  # time.sleep() kullanmak için eklendi
import traceback
import math

# LGpio kütüphanesi ve pin tanımlamaları için global değişkenler
# LGpio, RPi.GPIO'dan farklı olarak bir "handle" (işleyici) gerektirir.
lgh = None  # LGpio handle'ı
LGpio = None  # lgpio modülünün kendisi

# control1.py'den alınan pin tanımlamaları
YAW_ENA_PIN = 17
YAW_DIR_PIN = 27
YAW_STEP_PIN = 22
PITCH_ENA_PIN = 24
PITCH_DIR_PIN = 23
PITCH_STEP_PIN = 25
FIRE_PIN = 16  # control1.py'deki RELAY_PIN'e karşılık gelir

# rpi_motor_server.py'den alınan acil durdurma pini
EMERGENCY_STOP_PIN = 18

# GPIO'nun başarıyla başlatılıp başlatılmadığını gösteren bayrak
_gpio_initialized = False

# Simüle edilmiş taret açıları (gerçek enkoderler olmadığında kullanılır)
# Açıları -180 ile 180 arasında tutmak için başlangıçta 0.0 olarak ayarla
_simulated_yaw = 0.0
_simulated_pitch = 0.0

# Manuel hareket için yön değişkenleri (rpi_motor_server tarafından ayarlanır)
_yaw_moving_direction = 0  # -1: sol, 0: dur, 1: sağ
_pitch_moving_direction = 0  # -1: aşağı, 0: dur, 1: yukarı
_manual_degrees_to_move = 0.0 # Manuel hareket için her adımda hareket edilecek derece miktarı

# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# !!! ÖNEMLİ KALİBRASYON AYARLARI - KENDİ SİSTEMİNİZE GÖRE AYARLAMANIZ GEREKİR !!!
# !!! BU DEĞERLER, SİZİN MOTORUNUZUN VE MEKANİK SİSTEMİNİZİN GERÇEKTE BİR DERECE
# !!! DÖNMEK İÇİN KAÇ ADIM ATTIĞINI GÖSTERMELİDİR. YANLIŞ AYARLANIRSA,
# !!! YAZILIMDAKİ AÇI FİZİKSEL HAREKETLERDEN FARKLI OLACAKTIR.
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

STEPS_PER_REVOLUTION = 200  # Bir tam tur için adım sayısı (örn: 1.8 derece/adım motor için 200 tam adım)
MICROSTEPS = 32  # Sürücünüz 6400 Pulse/rev ise 32 olarak ayarlı kalmalı. Lütfen doğrulayın!
# DİKKAT: Motor sürücünüzün (örn: DRV8825) üzerindeki MS1, MS2, MS3 pinlerinin ayarlarını kontrol edin!
# Bu pinler mikro adımlama modunu belirler. Kodunuzdaki MICROSTEPS değeri, sürücünüzün fiziksel ayarlarıyla eşleşmelidir.
# Örneğin, 1/32 mikro adımlama için tüm MS pinleri HIGH (veya sürücüye göre farklı) olmalıdır.

# AYARLANDI: STEP_DELAY motorların adım kaçırmaması ve akıcı çalışması için çok küçük bir değere çekildi.
# Bu değer, her bir adım darbesinin (HIGH veya LOW) süresidir.
# Eğer motorlar hala adım atlıyorsa, bu değeri biraz artırmayı deneyin (örn: 0.0002 veya 0.0005).
# Eğer çok yavaş hareket ediyorsa, daha da düşürmeyi deneyin (örn: 0.00005).
STEP_DELAY = 0.001  # 100 mikrosaniye (0.001'den 0.0001'e düşürüldü)

PULSE_TIME = 0.1  # Ateşleme rölesinin çekili kalma süresi (saniye) - control1.py ile uyumlu.

# Step motor için adım/derece oranı (kalibrasyon gerekli!)
# Bu değerleri kalibrasyon testi ile güncelleyin!
STEPS_PER_DEGREE_YAW = 17.777 # Yaklaşık 17.777
STEPS_PER_DEGREE_PITCH = 17.777  # Yaklaşık 17.777

# Motor yönleri için sabitler
# DİKKAT: Bu değerler motor sürücünüzün DIR pininin nasıl çalıştığına bağlıdır.
# Eğer motor yönleri tersse, bu değerleri ters çevirin (örn: DIR_CW = 0, DIR_CCW = 1).
DIR_CW = 0  # Saat yönü (veya ileri/yukarı)
DIR_CCW = 1  # Saat yönünün tersi (veya geri/aşağı)

# LGpio pin modları ve seviyeleri için sabitler
LGPIO_HIGH = 1
LGPIO_LOW = 0
LGPIO_INPUT = 0
LGPIO_OUTPUT = 1

# Röle aktif/pasif durumları
# DİKKAT: Rölenizin nasıl tetiklendiğine bağlı olarak bu değerleri ayarlayın!
# Eğer röle LOW sinyali ile aktif oluyorsa: RELAY_ACTIVE = LGPIO_LOW, RELAY_INACTIVE = LGPIO_HIGH
# Eğer röle HIGH sinyali ile aktif oluyorsa: RELAY_ACTIVE = LGPIO_HIGH, RELAY_INACTIVE = LGPIO_LOW
RELAY_ACTIVE = LGPIO_HIGH # Varsayılan olarak HIGH ile aktif olduğunu varsayıyoruz
RELAY_INACTIVE = LGPIO_LOW # Varsayılan olarak LOW ile pasif olduğunu varsayıyoruz


def initialize_gpio():
    """
    Tüm motor ve ateşleme GPIO pinlerini başlatır ve motorları etkinleştirir.
    Bu fonksiyon sadece rpi_motor_server.py tarafından bir kez çağrılmalıdır.
    """
    global lgh, LGpio, _gpio_initialized, RELAY_ACTIVE, RELAY_INACTIVE
    print("DEBUG (motor_fire_module): initialize_gpio() çağrıldı.")
    sys.stdout.flush()
    if sys.platform == 'linux':
        try:
            import lgpio
            LGpio = lgpio

            lgh = LGpio.gpiochip_open(0)  # Genellikle ilk GPIO çipi (chip 0) kullanılır
            if lgh < 0:
                raise RuntimeError(f"LGpio handle açılamadı, hata kodu: {lgh}")
            print(f"DEBUG (motor_fire_module): LGpio handle ({lgh}) başarıyla açıldı.")
            sys.stdout.flush()

            # Röle aktif/pasif değerleri, rölenizin tetikleme mantığına göre ayarlanmalı
            print(f"DEBUG (motor_fire_module): RELAY_ACTIVE: {RELAY_ACTIVE}, RELAY_INACTIVE: {RELAY_INACTIVE}")
            sys.stdout.flush()

            # Tüm motor pinlerini çıkış olarak ayarla
            # Motorları başlangıçta ETKİNLEŞTİR (ENABLE LOW) - Kullanıcının isteği üzerine
            LGpio.gpio_claim_output(lgh, YAW_ENA_PIN, LGPIO_LOW) # ENABLE LOW = Enabled (DRV8825 için)
            LGpio.gpio_claim_output(lgh, PITCH_ENA_PIN, LGPIO_LOW) # ENABLE LOW = Enabled (DRV8825 için)

            LGpio.gpio_claim_output(lgh, YAW_DIR_PIN, LGPIO_LOW)
            LGpio.gpio_claim_output(lgh, YAW_STEP_PIN, LGPIO_LOW)
            LGpio.gpio_claim_output(lgh, PITCH_DIR_PIN, LGPIO_LOW)
            LGpio.gpio_claim_output(lgh, PITCH_STEP_PIN, LGPIO_LOW)

            print(
                "DEBUG (motor_fire_module): Motor GPIO pinleri başarıyla ÇIKIŞ olarak ayarlandı ve ETKİNLEŞTİRİLDİ.")
            sys.stdout.flush()

            # Ateşleme pini (başlangıçta güvenli durumda RELAY_INACTIVE)
            LGpio.gpio_claim_output(lgh, FIRE_PIN, RELAY_INACTIVE)
            print(
                f"DEBUG (motor_fire_module): FIRE_PIN ({FIRE_PIN}) başlangıçta RELAY_INACTIVE ({RELAY_INACTIVE}) yapıldı.")
            sys.stdout.flush()

            # Acil durdurma pini (giriş olarak ayarla, pull-up direnci ile)
            LGpio.gpio_claim_input(lgh, EMERGENCY_STOP_PIN, LGpio.SET_PULL_UP)
            print(
                f"DEBUG (motor_fire_module): EMERGENCY_STOP_PIN {EMERGENCY_STOP_PIN} giriş olarak ayarlandı (PULL_UP).")
            sys.stdout.flush()

            _gpio_initialized = True
            print(
                "DEBUG (motor_fire_module): Tüm GPIO pinleri başarıyla başlatıldı.")
            sys.stdout.flush()
        except ModuleNotFoundError:
            print(
                "Hata (motor_fire_module): lgpio modülü bulunamadı. Raspberry Pi üzerinde olduğunuzdan emin olun ve lgpio'yu yükleyin.")
            sys.stdout.flush()
            lgh = None
            LGpio = None
            _gpio_initialized = False
        except Exception as e:
            print(f"Hata (motor_fire_module): GPIO başlatılırken genel hata oluştu: {e}")
            sys.stdout.flush()
            traceback.print_exc()
            if lgh is not None and lgh >= 0:
                LGpio.gpiochip_close(lgh)  # Hata durumunda da kapatma
            lgh = None
            LGpio = None
    else:
        print("DEBUG (motor_fire_module): Simülasyon modu: GPIO başlatma atlandı.")
        sys.stdout.flush()
        _gpio_initialized = True
        # Simülasyon modunda röle değerlerini varsayılan olarak ayarla
        RELAY_ACTIVE = 0 # Simülasyon modunda 0 aktif, 1 pasif olarak kabul edelim
        RELAY_INACTIVE = 1


def set_motors_enabled(enable):
    """
    Motorların ENABLE pinlerini kontrol eder.
    True: Motorları etkinleştir (güç ver, tutma torku sağla)
    False: Motorları devre dışı bırak (güç kes, tutma torkunu kaldır)
    """
    if not _gpio_initialized or lgh is None:
        print(f"UYARI (set_motors_enabled): GPIO başlatılmadı, ENABLE pini kontrol edilemez.")
        sys.stdout.flush()
        return

    try:
        if enable:
            # Motorları etkinleştir (ENABLE LOW = Enabled)
            LGpio.gpio_write(lgh, YAW_ENA_PIN, LGPIO_LOW)
            LGpio.gpio_write(lgh, PITCH_ENA_PIN, LGPIO_LOW)
            print("DEBUG (set_motors_enabled): Motorlar ETKİNLEŞTİRİLDİ (ENABLE LOW).")
            sys.stdout.flush()
        else:
            # Motorları devre dışı bırak (ENABLE HIGH = Disabled)
            LGpio.gpio_write(lgh, YAW_ENA_PIN, LGPIO_HIGH)
            LGpio.gpio_write(lgh, PITCH_ENA_PIN, LGPIO_HIGH)
            print("DEBUG (set_motors_enabled): Motorlar DEVRE DIŞI BIRAKILDI (ENABLE HIGH).")
            sys.stdout.flush()
        time.sleep(0.000001)  # Kısa bir gecikme
    except Exception as e:
        print(f"HATA (set_motors_enabled): Motor ENABLE pinleri ayarlanırken hata: {e}")
        traceback.print_exc()
        sys.stdout.flush()


def move_steppers_simultaneous(steps_yaw, steps_pitch):
    """
    İki step motoru aynı anda, belirtilen adım sayısı kadar döndürür.
    Bu fonksiyon, control1.py'deki eşzamanlı hareket mantığını kullanır.
    Bu fonksiyon çağrıldığında motorların zaten etkin (enabled) olduğu varsayılır.
    :param steps_yaw: Yaw motoru için atılacak adım sayısı (pozitif veya negatif).
    :param steps_pitch: Pitch motoru için atılacak adım sayısı (pozitif veya negatif).
    """
    if not _gpio_initialized or lgh is None:
        print("DEBUG (move_steppers_simultaneous): GPIO başlatılmamış veya handle yok, hareket atlandı.")
        sys.stdout.flush()
        return

    # Yön pinlerini ayarla
    # Pozitif adımlar için DIR_CW, negatif adımlar için DIR_CCW.
    # Eğer motor yönleri tersse, DIR_CW ve DIR_CCW sabitlerini yukarıda ters çevirin.
    dir_yaw_gpio_value = DIR_CW if steps_yaw >= 0 else DIR_CCW
    dir_pitch_gpio_value = DIR_CW if steps_pitch >= 0 else DIR_CCW

    try:
        LGpio.gpio_write(lgh, YAW_DIR_PIN, dir_yaw_gpio_value)
        LGpio.gpio_write(lgh, PITCH_DIR_PIN, dir_pitch_gpio_value)
        time.sleep(0.000001)  # Yön sinyalinin oturması için kısa gecikme

        abs_steps_yaw = abs(int(steps_yaw))
        abs_steps_pitch = abs(int(steps_pitch))
        max_steps = max(abs_steps_yaw, abs_steps_pitch)

        if max_steps == 0:
            print("DEBUG (move_steppers_simultaneous): 0 adım için hareket yok.")
            sys.stdout.flush()
            return

        print(
            f"DEBUG (move_steppers_simultaneous): Motorlar hareket ediyor. Yaw: {abs_steps_yaw} adım (Yön: {'CW' if dir_yaw_gpio_value == DIR_CW else 'CCW'}), Pitch: {abs_steps_pitch} adım (Yön: {'CW' if dir_pitch_gpio_value == DIR_CW else 'CCW'}). STEP_DELAY: {STEP_DELAY}")
        sys.stdout.flush()

        # Her adım için STEP_DELAY'in yarısı kadar HIGH, yarısı kadar LOW
        step_pulse_duration = STEP_DELAY / 2.0

        for i in range(max_steps):
            # Sadece ilgili motor için adım sinyali gönder
            if i < abs_steps_yaw:
                LGpio.gpio_write(lgh, YAW_STEP_PIN, LGPIO_HIGH)
            if i < abs_steps_pitch:
                LGpio.gpio_write(lgh, PITCH_STEP_PIN, LGPIO_HIGH)
            time.sleep(step_pulse_duration)  # Adım sinyali HIGH kalma süresi

            # Adım sinyalini LOW yap
            LGpio.gpio_write(lgh, YAW_STEP_PIN, LGPIO_LOW)
            LGpio.gpio_write(lgh, PITCH_STEP_PIN, LGPIO_LOW)
            time.sleep(step_pulse_duration)  # Adımlar arası bekleme süresi (bir sonraki adıma kadar bekleme)

        print("DEBUG (move_steppers_simultaneous): Motor hareketi tamamlandı.")
        sys.stdout.flush()

    except Exception as e:
        print(f"KRİTİK LGpio hatası (move_steppers_simultaneous): {e}")
        sys.stdout.flush()
        traceback.print_exc()


def set_motor_angles(yaw_angle, pitch_angle):
    """
    Taretin yatay (yaw) ve dikey (pitch) açılarını ayarlar.
    Bu fonksiyon eşzamanlı adım atma fonksiyonunu kullanır.
    """
    global _simulated_yaw, _simulated_pitch
    print(f"DEBUG (motor_fire_module): set_motor_angles çağrıldı. Hedef Yaw: {yaw_angle}, Hedef Pitch: {pitch_angle}")
    sys.stdout.flush()

    target_yaw = float(yaw_angle)
    target_pitch = float(pitch_angle)

    if _gpio_initialized and lgh is not None:
        current_yaw, current_pitch = get_current_angles()
        print(f"DEBUG (motor_fire_module): Mevcut Açı: Yaw {current_yaw:.3f}°, Pitch {current_pitch:.3f}°")
        sys.stdout.flush()

        # Açısal farkı hesapla ve -180 ile 180 arasına normalize et
        delta_yaw = target_yaw - current_yaw
        delta_yaw = (delta_yaw + 180) % 360 - 180  # Normalizasyon

        delta_pitch = target_pitch - current_pitch
        delta_pitch = (delta_pitch + 180) % 360 - 180  # Normalizasyon

        print(f"DEBUG (motor_fire_module): Delta Açı: Yaw {delta_yaw:.3f}°, Pitch {delta_pitch:.3f}°")
        sys.stdout.flush()

        # Adım sayılarını hesapla
        steps_yaw = int(round(delta_yaw * STEPS_PER_DEGREE_YAW))
        steps_pitch = int(round(delta_pitch * STEPS_PER_DEGREE_PITCH))
        print(f"DEBUG (motor_fire_module): Hesaplanan Adım: Yaw {steps_yaw}, Pitch {steps_pitch}")
        sys.stdout.flush()

        if steps_yaw != 0 or steps_pitch != 0:
            # Motorlar zaten initialize_gpio() tarafından etkinleştirildi, tekrar etkinleştirmeye gerek yok.
            print(
                f"DEBUG (motor_fire_module): Motorlar hareket ettiriliyor: Yaw {steps_yaw} adım, Pitch {steps_pitch} adım.")
            sys.stdout.flush()
            move_steppers_simultaneous(steps_yaw, steps_pitch)

            # SİMUULE EDİLMİŞ AÇILARI GERÇEKLEŞEN ADIMLARA GÖRE GÜNCELLE
            _simulated_yaw += steps_yaw / STEPS_PER_DEGREE_YAW
            _simulated_pitch += steps_pitch / STEPS_PER_DEGREE_PITCH

            # Açıları -180 ile 180 aralığında tut
            _simulated_yaw = (_simulated_yaw + 180) % 360 - 180
            _simulated_pitch = (_simulated_pitch + 180) % 360 - 180

            print(
                f"DEBUG (motor_fire_module): Simüle edilmiş açılar güncellendi: Yaw {_simulated_yaw:.3f}°, Pitch {_simulated_pitch:.3f}°")
            sys.stdout.flush()
        else:
            print("DEBUG (motor_fire_module): Hedef açılara zaten ulaşıldı veya adım sayısı 0, hareket yok.")
            sys.stdout.flush()


def set_manual_move_direction(yaw_direction, pitch_direction, degrees_to_move):
    """
    Manuel hareket için motorların hareket yönünü ve her adımda hareket edilecek derece miktarını ayarlar.
    Bu değerler perform_manual_move_step tarafından kullanılır.
    :param yaw_direction: -1 (sol), 0 (dur), 1 (sağ)
    :param pitch_direction: -1 (aşağı), 0 (dur), 1 (yukarı)
    :param degrees_to_move: Her adımda hareket edilecek derece miktarı.
    """
    global _yaw_moving_direction, _pitch_moving_direction, _manual_degrees_to_move
    _yaw_moving_direction = yaw_direction
    _pitch_moving_direction = pitch_direction
    _manual_degrees_to_move = degrees_to_move
    print(
        f"DEBUG (motor_fire_module): Manuel hareket yönleri ayarlandı: Yaw {yaw_direction}, Pitch {pitch_direction}, Derece: {degrees_to_move}")
    sys.stdout.flush()


def perform_manual_move_step():
    """
    Manuel hareket yönlerine ve _manual_degrees_to_move değerine göre tek bir adım hareketi gerçekleştirir.
    Bu fonksiyon rpi_motor_server'daki ayrı bir thread tarafından sürekli çağrılmalıdır.
    """
    global _simulated_yaw, _simulated_pitch

    if not _gpio_initialized or lgh is None:
        # Simülasyon modunda
        _simulated_yaw += _yaw_moving_direction * _manual_degrees_to_move
        _simulated_pitch += _pitch_moving_direction * _manual_degrees_to_move
        _simulated_yaw = (_simulated_yaw + 180) % 360 - 180
        _simulated_pitch = (_simulated_pitch + 180) % 360 - 180
        print(
            f"DEBUG (motor_fire_module - manual): Simüle edilmiş manuel adım. Mevcut Yaw: {_simulated_yaw:.3f}°, Pitch: {_simulated_pitch:.3f}°")
        sys.stdout.flush()
        return

    # Gerçek motor hareketi
    # Manuel hareket yönüne göre adım sayılarını hesapla (işareti doğru ayarla)
    steps_yaw = int(round(_yaw_moving_direction * _manual_degrees_to_move * STEPS_PER_DEGREE_YAW))
    steps_pitch = int(round(_pitch_moving_direction * _manual_degrees_to_move * STEPS_PER_DEGREE_PITCH))
    print(f"DEBUG (motor_fire_module - manual): Hesaplanan Adım: Yaw {steps_yaw}, Pitch {steps_pitch} (Her adımda {_manual_degrees_to_move} derece)")
    sys.stdout.flush()

    if steps_yaw != 0 or steps_pitch != 0:
        # Motorlar zaten etkinleştirildi, tekrar etkinleştirmeye gerek yok.
        move_steppers_simultaneous(steps_yaw, steps_pitch)

        # SİMUULE EDİLMİŞ AÇILARI GERÇEKLEŞEN ADIMLARA GÖRE GÜNCELLE
        _simulated_yaw += steps_yaw / STEPS_PER_DEGREE_YAW
        _simulated_pitch += steps_pitch / STEPS_PER_DEGREE_PITCH

        # Açıları -180 ile 180 aralığında tut
        _simulated_yaw = (_simulated_yaw + 180) % 360 - 180
        _simulated_pitch = (_simulated_pitch + 180) % 360 - 180
        print(
            f"DEBUG (motor_fire_module - manual): Simüle edilmiş açılar güncellendi: Yaw {_simulated_yaw:.3f}°, Pitch {_simulated_pitch:.3f}°")
        sys.stdout.flush()


def fire_weapon():
    """
    Ateşleme mekanizmasını tetikler.
    """
    print("DEBUG (motor_fire_module): fire_weapon() çağrıldı.")
    sys.stdout.flush()
    if not _gpio_initialized or lgh is None or RELAY_ACTIVE is None or RELAY_INACTIVE is None:
        print("Hata (motor_fire_module): GPIO veya FIRE_PIN başlatılmadı, ateşleme mümkün değil (Simülasyon).")
        sys.stdout.flush()
        return

    try:
        print(
            f"DEBUG (motor_fire_module): GPIO {FIRE_PIN} -> RELAY_ACTIVE ({RELAY_ACTIVE}) yapılıyor (Ateşleme Başladı).")
        sys.stdout.flush()
        LGpio.gpio_write(lgh, FIRE_PIN, RELAY_ACTIVE)
        time.sleep(PULSE_TIME)
        print(
            f"DEBUG (motor_fire_module): GPIO {FIRE_PIN} -> RELAY_INACTIVE ({RELAY_INACTIVE}) yapılıyor (Ateşleme Bitti).")
        sys.stdout.flush()
        LGpio.gpio_write(lgh, FIRE_PIN, RELAY_INACTIVE)
        time.sleep(0.1) # Rölenin tamamen kapanması için kısa bir bekleme
        print("DEBUG (motor_fire_module): Ateşleme tamamlandı.")
        sys.stdout.flush()
    except Exception as e:
        print(f"KRİTİK LGpio hatası (motor_fire_module): {e}. Pin: {FIRE_PIN}")
        sys.stdout.flush()
        traceback.print_exc()


def get_current_angles():
    """
    Taretin mevcut yatay (yaw) ve dikey (pitch) açılarını döndürür.
    Gerçek bir sistemde, sensörlerden (örn: enkoderler) okunmalıdır.
    Şimdilik simüle edilmiş değerleri döndürüyoruz.
    """
    global _simulated_yaw, _simulated_pitch
    return _simulated_yaw, _simulated_pitch


def reset_current_angles():
    """
    Taretin mevcut simüle edilmiş açılarını 0.0 yaw ve 0.0 pitch olarak sıfırlar.
    Bu, taretin mevcut konumunu yeni 'sıfır' noktası olarak ayarlamak için kullanılır.
    """
    global _simulated_yaw, _simulated_pitch
    _simulated_yaw = 0.0
    _simulated_pitch = 0.0
    print("DEBUG (motor_fire_module): Taret açıları 0.0 yaw, 0.0 pitch olarak sıfırlandı.")
    sys.stdout.flush()


def get_emergency_stop_pin():
    """Acil durdurma pin numarasını döndürür."""
    return EMERGENCY_STOP_PIN


def get_lgpio_instance():
    """LGpio handle'ını döndürür."""
    return lgh


def cleanup_gpio():
    """
    Tüm GPIO pinlerini temizler.
    Bu fonksiyon, GPIO kaynaklarını serbest bırakır ancak motorları devre dışı bırakmaz.
    Motorların tutma torkunu korumak için ENABLE pinleri LOW'da kalır.
    """
    global _gpio_initialized, lgh
    print("DEBUG (motor_fire_module): cleanup_gpio() çağrıldı.")
    sys.stdout.flush()
    if _gpio_initialized and lgh is not None and lgh >= 0:
        try:
            # set_motors_enabled(False) # KALDIRILDI: Kullanıcının isteği üzerine motorlar devre dışı bırakılmayacak.
            if FIRE_PIN is not None and RELAY_INACTIVE is not None:
                LGpio.gpio_write(lgh, FIRE_PIN, RELAY_INACTIVE) # Ateşleme pinini güvenli duruma getir
                print(
                    f"DEBUG (motor_fire_module): Fire pin ({FIRE_PIN}) RELAY_INACTIVE ({RELAY_INACTIVE}) yapıldı (Güvenli Durum).")
                sys.stdout.flush()

            LGpio.gpiochip_close(lgh)
            print("DEBUG (motor_fire_module): LGpio handle kapatıldı.")
            sys.stdout.flush()
            lgh = None
            _gpio_initialized = False
        except Exception as e:
            print(f"Hata (motor_fire_module): GPIO temizlenirken hata oluştu: {e}")
            sys.stdout.flush()
            traceback.print_exc()
    else:
        print("UYARI (motor_fire_module): lgpio kullanılamıyor veya handle yok, GPIO temizlenemedi.")
        sys.stdout.flush()


def test_single_motor_step(motor_type, direction_input, num_steps):
    """
    Tek bir motoru belirli bir yönde ve adım sayısında test etmek için.
    :param motor_type: 'yaw' veya 'pitch'
    :param direction_input: 1 (ileri/sağ/yukarı) veya 0 (geri/sol/aşağı)
    :param num_steps: Atılacak adım sayısı
    """
    print(
        f"DEBUG (motor_fire_module): test_single_motor_step çağrıldı. Motor: {motor_type}, Yön Girişi: {direction_input}, Adım: {num_steps}")
    sys.stdout.flush()
    if not _gpio_initialized or lgh is None:
        print(f"Hata (motor_fire_module): GPIO başlatılmadı veya kullanılamaz durumda. Test yapılamaz.")
        sys.stdout.flush()
        return False

    if num_steps <= 0:
        print(f"DEBUG (motor_fire_module): 0 veya negatif adım sayısı ({num_steps}) için hareket yok.")
        sys.stdout.flush()
        return True

    steps_yaw = 0
    steps_pitch = 0

    # direction_input (1 veya 0) değerini kullanarak adım yönünü ayarla
    # 1: pozitif adım (sağ/yukarı), 0: negatif adım (sol/aşağı)
    if motor_type == 'yaw':
        steps_yaw = num_steps if direction_input == 1 else -num_steps
    elif motor_type == 'pitch':
        steps_pitch = num_steps if direction_input == 1 else -num_steps
    else:
        print("Hata (motor_fire_module): Geçersiz motor tipi. 'yaw' veya 'pitch' olmalı.")
        sys.stdout.flush()
        return False

    print(f"DEBUG (motor_fire_module - test): Hesaplanan Adım: Yaw {steps_yaw}, Pitch {steps_pitch}")
    sys.stdout.flush()

    try:
        # Motorlar zaten initialize_gpio() ile etkinleştirildi.
        move_steppers_simultaneous(steps_yaw, steps_pitch)

        # Test fonksiyonunda da simüle edilmiş açıları güncelle
        if motor_type == 'yaw':
            _simulated_yaw += steps_yaw / STEPS_PER_DEGREE_YAW
            _simulated_yaw = (_simulated_yaw + 180) % 360 - 180
        elif motor_type == 'pitch':
            _simulated_pitch += steps_pitch / STEPS_PER_DEGREE_PITCH
            _simulated_pitch = (_simulated_pitch + 180) % 360 - 180

        print(
            f"DEBUG (motor_fire_module): {motor_type} motoru {num_steps} adım test edildi. Mevcut Açı: Yaw {_simulated_yaw:.3f}°, Pitch {_simulated_pitch:.3f}°")
        sys.stdout.flush()
        return True
    except Exception as e:
        print(f"Hata (motor_fire_module): {motor_type} motor testi sırasında hata oluştu: {e}")
        sys.stdout.flush()
        traceback.print_exc()
        return False


def run_calibration_test(motor_type, degrees_to_move):
    """
    Motor kalibrasyonu için belirli bir derece hareket ettirir ve kullanıcıdan geri bildirim alır.
    Bu fonksiyonu doğrudan motor_fire_module.py dosyasını çalıştırarak kullanabilirsiniz.
    """
    if not _gpio_initialized:
        print("Hata: GPIO başlatılmadı, kalibrasyon testi yapılamaz.")
        sys.stdout.flush()
        return

    print(f"\n--- {motor_type.upper()} Motor Kalibrasyon Testi ---")
    print(f"Hedef: {degrees_to_move} derece hareket ettirilecek.")
    print(
        f"Mevcut {motor_type} STEPS_PER_DEGREE: {STEPS_PER_DEGREE_YAW if motor_type == 'yaw' else STEPS_PER_DEGREE_PITCH}")
    sys.stdout.flush()

    initial_yaw, initial_pitch = get_current_angles()
    print(f"Başlangıç Açılar: Yaw {initial_yaw:.1f}°, Pitch {initial_pitch:.1f}°")
    sys.stdout.flush()

    # Motorlar zaten initialize_gpio() ile etkinleştirildi.

    if motor_type == 'yaw':
        target_yaw = initial_yaw + degrees_to_move
        set_motor_angles(target_yaw, initial_pitch)
    elif motor_type == 'pitch':
        target_pitch = initial_pitch + degrees_to_move
        set_motor_angles(initial_yaw, target_pitch)

    time.sleep(2)  # Motorun hareketini tamamlaması için bekle

    final_yaw, final_pitch = get_current_angles()
    print(f"Bitiş Açılar (Simüle Edilmiş): Yaw {final_yaw:.1f}°, Pitch {final_pitch:.1f}°")
    sys.stdout.flush()

    print("\n!!! DİKKAT: Lütfen taretin fiziksel olarak ne kadar döndüğünü ölçün. !!!")
    print(f"Hedeflenen hareket: {degrees_to_move} derece.")
    sys.stdout.flush()
    actual_movement_str = input(f"Fiziksel olarak {motor_type} motoru kaç derece döndü? (örn: 58.5): ")
    try:
        actual_movement = float(actual_movement_str)
        if actual_movement == 0:
            print("Hata: Motor hiç hareket etmedi. Bağlantıları veya güç kaynağını kontrol edin.")
            sys.stdout.flush()
            return

        current_steps_per_degree = STEPS_PER_DEGREE_YAW if motor_type == 'yaw' else STEPS_PER_DEGREE_PITCH
        new_steps_per_degree = (current_steps_per_degree / actual_movement) * degrees_to_move

        print(f"\n--- KALİBRASYON SONUCU ---")
        print(f"Mevcut {motor_type} STEPS_PER_DEGREE: {current_steps_per_degree:.3f}")
        print(f"Fiziksel olarak dönülen derece: {actual_movement:.1f}°")
        print(f"ÖNERİLEN YENİ {motor_type} STEPS_PER_DEGREE: {new_steps_per_degree:.3f}")
        print(
            f"Lütfen motor_fire_module.py dosyasındaki 'STEPS_PER_DEGREE_{motor_type.upper()}' değerini bu yeni değerle güncelleyin.")
        print("Bu testi birkaç kez tekrarlayarak ve ortalama alarak daha doğru bir değer bulabilirsiniz.")
        print("Eğer motor yavaşlıyorsa veya titriyorsa, STEP_DELAY değerini artırmayı deneyin (örn: 0.0002 veya 0.0005).")
        sys.stdout.flush()

    except ValueError:
        print("Geçersiz giriş. Lütfen sayısal bir değer girin.")
        sys.stdout.flush()
    except Exception as e:
        print(f"Kalibrasyon sırasında hata oluştu: {e}")
        sys.stdout.flush()
        traceback.print_exc()


def stop_all_motors():
    """
    Tüm motor hareketlerini durdurur ve motorları devre dışı bırakır.
    Bu fonksiyon acil durdurma durumlarında veya motorların tamamen durdurulması istendiğinde çağrılmalıdır.
    """
    # Step pinlerini LOW yaparak motor adımlarını durdur
    if LGpio and lgh is not None and _gpio_initialized:
        try:
            LGpio.gpio_write(lgh, YAW_STEP_PIN, LGPIO_LOW)
            LGpio.gpio_write(lgh, PITCH_STEP_PIN, LGPIO_LOW)
            print("DEBUG (motor_fire_module): Tüm motor hareketleri durduruldu (STEP pinleri LOW).")
            sys.stdout.flush()
        except Exception as e:
            print(f"HATA (stop_all_motors): STEP pinleri LOW yapılırken hata: {e}")
            traceback.print_exc()
            sys.stdout.flush()
    else:
        print("UYARI (motor_fire_module): lgpio kullanılamıyor veya handle yok, motorlar durdurulamadı.")
        sys.stdout.flush()
    #set_motors_enabled(False)  # Motorları durdurduktan sonra devre dışı bırak


# YENİ: Doğrudan Yaw motoru testi için fonksiyon
def test_direct_yaw_movement_steps(steps, direction):
    """
    Yaw motorunu doğrudan belirli adım sayısı ve yönde hareket ettirir.
    Bu fonksiyon, kalibrasyon testinden daha temel bir seviyede motoru test etmek içindir.
    :param steps: Atılacak adım sayısı.
    :param direction: 0 (geri/sol) veya 1 (ileri/sağ).
    """
    print(f"\n--- Doğrudan YAW Motoru Adım Testi ---")
    print(f"Hedef: {steps} adım {'ileri/sağ' if direction == 1 else 'geri/sol'} yönde hareket ettirilecek.")
    sys.stdout.flush()

    if not _gpio_initialized or lgh is None:
        print(f"Hata (test_direct_yaw_movement_steps): GPIO başlatılmadı veya kullanılamaz durumda. Test yapılamaz.")
        sys.stdout.flush()
        return False

    if steps <= 0:
        print(f"DEBUG (test_direct_yaw_movement_steps): 0 veya negatif adım sayısı ({steps}) için hareket yok.")
        sys.stdout.flush()
        return True

    dir_gpio_value = DIR_CW if direction == 1 else DIR_CCW

    try:
        set_motors_enabled(True) # Test için motoru etkinleştir
        LGpio.gpio_write(lgh, YAW_DIR_PIN, dir_gpio_value)
        time.sleep(0.000001) # Yön sinyalinin oturması için kısa gecikme

        step_pulse_duration = STEP_DELAY / 2.0

        print(f"DEBUG (test_direct_yaw_movement_steps): Yaw motoru hareket ediyor. {steps} adım. STEP_DELAY: {STEP_DELAY}")
        sys.stdout.flush()

        for i in range(steps):
            LGpio.gpio_write(lgh, YAW_STEP_PIN, LGPIO_HIGH)
            time.sleep(step_pulse_duration)
            LGpio.gpio_write(lgh, YAW_STEP_PIN, LGPIO_LOW)
            time.sleep(step_pulse_duration)
            if i % 100 == 0: # Her 100 adımda bir çıktı ver
                print(f"DEBUG (test_direct_yaw_movement_steps): Yaw motoru adım {i+1}/{steps}")
                sys.stdout.flush()

        print("DEBUG (test_direct_yaw_movement_steps): Yaw motoru hareketi tamamlandı.")
        sys.stdout.flush()
        return True
    except Exception as e:
        print(f"HATA (test_direct_yaw_movement_steps): Yaw motoru testi sırasında hata oluştu: {e}")
        sys.stdout.flush()
        traceback.print_exc()
        return False
    finally:
        set_motors_enabled(False) # Test sonrası motoru devre dışı bırak

# YENİ: Doğrudan Pitch motoru testi için fonksiyon
def test_direct_pitch_movement_steps(steps, direction):
    """
    Pitch motorunu doğrudan belirli adım sayısı ve yönde hareket ettirir.
    Bu fonksiyon, kalibrasyon testinden daha temel bir seviyede motoru test etmek içindir.
    :param steps: Atılacak adım sayısı.
    :param direction: 0 (geri/aşağı) veya 1 (ileri/yukarı).
    """
    print(f"\n--- Doğrudan PITCH Motoru Adım Testi ---")
    print(f"Hedef: {steps} adım {'ileri/yukarı' if direction == 1 else 'geri/aşağı'} yönde hareket ettirilecek.")
    sys.stdout.flush()

    if not _gpio_initialized or lgh is None:
        print(f"Hata (test_direct_pitch_movement_steps): GPIO başlatılmadı veya kullanılamaz durumda. Test yapılamaz.")
        sys.stdout.flush()
        return False

    if steps <= 0:
        print(f"DEBUG (test_direct_pitch_movement_steps): 0 veya negatif adım sayısı ({steps}) için hareket yok.")
        sys.stdout.flush()
        return True

    dir_gpio_value = DIR_CW if direction == 1 else DIR_CCW

    try:
        set_motors_enabled(True) # Test için motoru etkinleştir
        LGpio.gpio_write(lgh, PITCH_DIR_PIN, dir_gpio_value)
        time.sleep(0.000001) # Yön sinyalinin oturması için kısa gecikme

        step_pulse_duration = STEP_DELAY / 2.0

        print(f"DEBUG (test_direct_pitch_movement_steps): Pitch motoru hareket ediyor. {steps} adım. STEP_DELAY: {STEP_DELAY}")
        sys.stdout.flush()

        for i in range(steps):
            LGpio.gpio_write(lgh, PITCH_STEP_PIN, LGPIO_HIGH)
            time.sleep(step_pulse_duration)
            LGpio.gpio_write(lgh, PITCH_STEP_PIN, LGPIO_LOW)
            time.sleep(step_pulse_duration)
            if i % 100 == 0: # Her 100 adımda bir çıktı ver
                print(f"DEBUG (test_direct_pitch_movement_steps): Pitch motoru adım {i+1}/{steps}")
                sys.stdout.flush()

        print("DEBUG (test_direct_pitch_movement_steps): Pitch motoru hareketi tamamlandı.")
        sys.stdout.flush()
        return True
    except Exception as e:
        print(f"HATA (test_direct_pitch_movement_steps): Pitch motoru testi sırasında hata oluştu: {e}")
        sys.stdout.flush()
        traceback.print_exc()
        return False
    finally:
        set_motors_enabled(False) # Test sonrası motoru devre dışı bırak


if __name__ == '__main__':
    # Bu bölüm, motor_fire_module.py'yi doğrudan çalıştırdığınızda test etmenizi sağlar.
    print("motor_fire_module.py doğrudan çalıştırıldı. GPIO başlatılıyor.")
    sys.stdout.flush()
    initialize_gpio() # Motorlar burada etkinleştirilecek
    if _gpio_initialized:
        reset_current_angles()
        print("\n--- Motor Kalibrasyon ve Test Menüsü ---")
        print("1. Yaw Motoru Kalibrasyonu (örn: 90 derece)")
        print("2. Pitch Motoru Kalibrasyonu (örn: 30 derece)")
        print("3. Ateşleme Testi")
        print("4. Doğrudan YAW Motoru Adım Testi")
        print("5. Doğrudan PITCH Motoru Adım Testi") # Yeni seçenek
        print("6. Çıkış") # Seçenek numarası güncellendi
        sys.stdout.flush()

        while True:
            choice = input("Seçiminizi yapın (1-6): ") # Seçenek aralığı güncellendi
            if choice == '1':
                try:
                    degrees = float(input("Yaw motorunu kaç derece hareket ettirmek istersiniz? (örn: 90): "))
                    run_calibration_test('yaw', degrees)
                except ValueError:
                    print("Geçersiz derece girişi.")
                    sys.stdout.flush()
            elif choice == '2':
                try:
                    degrees = float(input("Pitch motorunu kaç derece hareket ettirmek istersiniz? (örn: 30): "))
                    run_calibration_test('pitch', degrees)
                except ValueError:
                    print("Geçersiz derece girişi.")
                    sys.stdout.flush()
            elif choice == '3':
                print("Ateşleme testi yapılıyor...")
                sys.stdout.flush()
                fire_weapon()
                time.sleep(1)
                print("Ateşleme testi tamamlandı.")
                sys.stdout.flush()
            elif choice == '4':
                try:
                    steps = int(input("Yaw motorunu kaç adım hareket ettirmek istersiniz? (örn: 1600): "))
                    direction_str = input("Yön (ileri/sağ için 1, geri/sol için 0): ")
                    direction = int(direction_str)
                    if direction not in [0, 1]:
                        print("Geçersiz yön girişi. Lütfen 0 veya 1 girin.")
                        sys.stdout.flush()
                        continue
                    test_direct_yaw_movement_steps(steps, direction)
                except ValueError:
                    print("Geçersiz adım veya yön girişi.")
                    sys.stdout.flush()
            elif choice == '5': # Yeni doğrudan Pitch testi seçeneği
                try:
                    steps = int(input("Pitch motorunu kaç adım hareket ettirmek istersiniz? (örn: 1600): "))
                    direction_str = input("Yön (ileri/yukarı için 1, geri/aşağı için 0): ")
                    direction = int(direction_str)
                    if direction not in [0, 1]:
                        print("Geçersiz yön girişi. Lütfen 0 veya 1 girin.")
                        sys.stdout.flush()
                        continue
                    test_direct_pitch_movement_steps(steps, direction)
                except ValueError:
                    print("Geçersiz adım veya yön girişi.")
                    sys.stdout.flush()
            elif choice == '6': # Çıkış seçeneği güncellendi
                print("Çıkılıyor...")
                sys.stdout.flush()
                break
            else:
                print("Geçersiz seçim.")
                sys.stdout.flush()
            time.sleep(0.5)
    else:
        print("GPIO başlatılamadığı için testler yapılamadı.")
        sys.stdout.flush()
    cleanup_gpio() # Çıkışta motorları devre dışı bırakmaz, sadece GPIO kaynaklarını temizler
    print("motor_fire_module.py betiği tamamen kapatıldı.")
    sys.stdout.flush()
