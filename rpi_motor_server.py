# rpi_motor_server.py
# Bu betik Raspberry Pi üzerinde çalışacak ve PC'den gelen komutları işleyecektir.

print("SCRIPT BAŞLADI! (Satır 1 - Dosya Başlangıcı)")  # Betiğin başladığını gösteren ilk çıktı

import socket
import json
import sys
import time
import traceback  # Hata ayıklama için eklendi
import threading  # Manuel hareket ve periyodik açı gönderme için thread ekledik

print("DEBUG (Satır 10 - Temel importlar tamamlandı.)")
sys.stdout.flush()

# Motor ve Ateşleme kontrol modüllerini import et
# Bu dosyaların Raspberry Pi üzerinde rpi_motor_server.py ile aynı dizinde olduğundan emin olun.
import motor_fire_module

print("DEBUG (Satır 17 - motor_fire_module import edildi.)")
sys.stdout.flush()

# Raspberry Pi GPIO kütüphanesini içeri aktar (eğer Linux'ta çalışıyorsa)
# Bu LGpio nesnesi sadece emergency_stop_handler için kullanılır.
# Motor ve ateşleme kontrolü motor_fire_module içinde yönetilir.
LGpio = None
lgh = None  # LGpio handle'ı
try:
    import lgpio

    LGpio = lgpio

    # motor_fire_module'deki initialize_gpio fonksiyonu artık LGpio handle'ını açıyor
    # Burada sadece acil durdurma butonu için dinleyici kurmak amacıyla var.
    # En iyisi, motor_fire_module'ün initialize_gpio'sunun LGpio.gpiochip_open'ı yönetmesidir.

    print("DEBUG (rpi_motor_server): lgpio modülü başarıyla import edildi.")
    sys.stdout.flush()
except ModuleNotFoundError:
    print("UYARI (rpi_motor_server): lgpio modülü bulunamadı. Acil durdurma butonu devre dışı.")
    sys.stdout.flush()
except Exception as e:
    print(f"HATA (rpi_motor_server): lgpio import edilirken veya handle açılırken hata: {e}")
    traceback.print_exc()
    sys.stdout.flush()

# Sunucu ayarları
HOST = '0.0.0.0'  # Tüm arayüzlerden gelen bağlantıları dinle
PORT = 12345  # PC uygulamasındaki port ile aynı olmalı

# Bağlantı durumu bayrakları
client_connected = threading.Event()
client_connected.clear()

# Global bağlantı değişkenleri
conn = None
addr = None
server_socket = None


# Acil durdurma butonu için callback
def emergency_stop_handler(chip, gpio, level, tick):
    # Butona basıldığında (LOW) veya bırakıldığında (HIGH) tetiklenebilir.
    # Genellikle basıldığında (LOW) durdurma işlemi yapılır.
    if level == 0:  # Butona basıldığında (LOW)
        print("\n!!! ACİL DURDURMA BUTONUNA BASILDI !!! Tüm motorlar durduruluyor ve çıkılıyor.")
        sys.stdout.flush()
        motor_fire_module.stop_all_motors()  # Tüm motorları durdur ve devre dışı bırak
        motor_fire_module.cleanup_gpio()  # GPIO kaynaklarını temizle
        # Uygulamayı güvenli bir şekilde kapatmak için bir bayrak ayarla
        global client_connected
        client_connected.clear()  # Bağlantıyı kes
        # sys.exit(1) # sys.exit() kullanmaktan kaçının, cleanup'ı engeller


# Açıları periyodik olarak PC'ye göndermek için iş parçacığı
def angle_sender_loop():
    while client_connected.is_set():
        try:
            current_yaw, current_pitch = motor_fire_module.get_current_angles()
            response = {
                "action": "get_angles",
                "status": "ok",
                "current_yaw": current_yaw,
                "current_pitch": current_pitch
            }
            if conn:
                conn.sendall((json.dumps(response) + '\n').encode('utf-8'))
            time.sleep(0.07)  # Her 100ms'de bir açıları gönder
        except BrokenPipeError:
            print("UYARI (rpi_motor_server): Açı gönderilirken bağlantı kesildi (BrokenPipeError).")
            sys.stdout.flush()
            client_connected.clear()
            break
        except Exception as e:
            print(f"HATA (rpi_motor_server): Açı gönderilirken hata: {e}")
            traceback.print_exc()
            sys.stdout.flush()
            client_connected.clear()
            break
    print("DEBUG (rpi_motor_server): Açı gönderme döngüsü sonlandı.")
    sys.stdout.flush()


# Manuel hareket döngüsü (rpi_motor_server'da kalır, ancak motor_fire_module'den komutları alır)
def manual_move_loop():
    while client_connected.is_set():
        # motor_fire_module'deki global değişkenleri kullanarak hareket et
        # Bu değerler set_manual_move_direction tarafından ayarlanır
        yaw_dir = motor_fire_module._yaw_moving_direction
        pitch_dir = motor_fire_module._pitch_moving_direction
        degrees_to_move = motor_fire_module._manual_degrees_to_move

        if (yaw_dir != 0 or pitch_dir != 0) and degrees_to_move > 0:
            # Bu fonksiyon artık motor_fire_module içinde adım hesaplamasını yapıyor
            motor_fire_module.perform_manual_move_step()  # Artık parametre almıyor
            # Manuel hareket komutları arasındaki gecikme.
            # PC tarafı 30ms'de bir komut gönderiyorsa, burası da ona yakın olmalı.
            time.sleep(0.03)  # 30ms gecikme
        else:
            time.sleep(0.01)  # Hareket yoksa kısa bir bekleme
    print("DEBUG (rpi_motor_server): Manuel hareket döngüsü sonlandı.")
    sys.stdout.flush()


def run_server():
    global conn, addr, server_socket, lgh  # lgh'yi global olarak tanımladık
    print("DEBUG (rpi_motor_server): Sunucu başlatılıyor...")
    sys.stdout.flush()

    # GPIO'yu başlat
    motor_fire_module.initialize_gpio()
    # initialize_gpio() içinde motorlar artık etkinleştiriliyor, burada tekrar set_motors_enabled(True) yapmaya gerek yok.
    if not motor_fire_module._gpio_initialized:  # _gpio_initialized bayrağını kontrol et
        print("KRİTİK HATA: GPIO başlatılamadı, sunucu başlatılamıyor.")
        sys.stdout.flush()
        return

    # Acil durdurma butonu dinleyicisini ayarla
    if LGpio:
        try:
            # motor_fire_module zaten handle'ı açtığı için burada tekrar açmaya gerek yok.
            # Sadece callback'i ayarlıyoruz.
            lgh = motor_fire_module.get_lgpio_instance()  # motor_fire_module'den handle'ı al
            if lgh is None or lgh < 0:
                raise RuntimeError(f"LGpio handle motor_fire_module'den alınamadı veya geçersiz: {lgh}")

            # Acil durdurma pini zaten initialize_gpio içinde INPUT ve PULL_UP olarak ayarlandı.
            # Burada sadece callback'i ekliyoruz.
            LGpio.callback(lgh, motor_fire_module.EMERGENCY_STOP_PIN, motor_fire_module.LGpio.EITHER_EDGE,
                           emergency_stop_handler)
            print(
                f"DEBUG (rpi_motor_server): Acil durdurma butonu (GPIO {motor_fire_module.EMERGENCY_STOP_PIN}) dinleniyor.")
            sys.stdout.flush()
        except Exception as e:
            print(f"HATA (rpi_motor_server): Acil durdurma butonu ayarlanamadı: {e}")
            traceback.print_exc()
            sys.stdout.flush()

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind((HOST, PORT))
        server_socket.listen(1)
        print(f"DEBUG (rpi_motor_server): Sunucu {HOST}:{PORT} üzerinde dinliyor.")
        sys.stdout.flush()
    except socket.error as e:
        print(f"HATA (rpi_motor_server): Soket hatası: {e}")
        sys.stdout.flush()
        cleanup_on_exit()
        return
    except Exception as e:
        print(f"HATA (rpi_motor_server): Sunucu başlatılırken beklenmedik hata: {e}")
        traceback.print_exc()
        sys.stdout.flush()
        cleanup_on_exit()
        return

    # Açı gönderme iş parçacığını başlat
    angle_sender_thread = threading.Thread(target=angle_sender_loop)
    angle_sender_thread.daemon = True  # Ana program kapanınca bu thread de kapanır

    # Manuel hareket iş parçacığını başlat
    manual_move_thread = threading.Thread(target=manual_move_loop)
    manual_move_thread.daemon = True

    try:
        conn, addr = server_socket.accept()
        
        # NAGLE ALGORİTMASI DEVRE DIŞI BIRAKMA
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        
        conn.settimeout(0.01)  # Engellemeyen okuma için kısa zaman aşımı
        client_connected.set()
        print(f"DEBUG (rpi_motor_server): Bağlantı kabul edildi: {addr}")
        sys.stdout.flush()

        angle_sender_thread.start()
        manual_move_thread.start()

        buffer = ""
        while client_connected.is_set():
            try:
                data = conn.recv(1024).decode('utf-8')
                if not data:
                    print("UYARI (rpi_motor_server): İstemci bağlantıyı kapattı.")
                    sys.stdout.flush()
                    break
                buffer += data
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    try:
                        command = json.loads(line)
                        print(f"DEBUG (rpi_motor_server): Komut alındı: {command}")
                        sys.stdout.flush()
                        process_command(command)
                    except json.JSONDecodeError:
                        print(f"HATA (rpi_motor_server): Geçersiz JSON alındı: {line}")
                        sys.stdout.flush()
                    except Exception as e:
                        print(f"HATA (rpi_motor_server): Komut işlenirken hata: {e}")
                        traceback.print_exc()
                        sys.stdout.flush()
            except socket.timeout:
                pass  # Veri yok, normal
            except socket.error as e:
                print(f"HATA (rpi_motor_server): Soket hatası: {e}. Bağlantı kesiliyor.")
                sys.stdout.flush()
                break
            except Exception as e:
                print(f"HATA (rpi_motor_server): Veri alınırken beklenmedik hata: {e}")
                traceback.print_exc()
                sys.stdout.flush()
                break
    except socket.timeout:
        print("UYARI (rpi_motor_server): Bağlantı beklenirken zaman aşımı.")
        sys.stdout.flush()
    except Exception as e:
        print(f"HATA (rpi_motor_server): Sunucu döngüsünde hata: {e}")
        traceback.print_exc()
        sys.stdout.flush()
    finally:
        cleanup_on_exit()
        # Thread'lerin bitmesini bekle
        if angle_sender_thread.is_alive():
            print("DEBUG (rpi_motor_server): Açı gönderme thread'i kapatılıyor...")
            sys.stdout.flush()
            angle_sender_thread.join(timeout=1)
        if manual_move_thread.is_alive():
            print("DEBUG (rpi_motor_server): Manuel hareket thread'i kapatılıyor...")
            sys.stdout.flush()
            manual_move_thread.join(timeout=1)
        print("DEBUG (rpi_motor_server): Tüm iş parçacıkları kapatıldı.")
        sys.stdout.flush()


def process_command(command):
    """İstemciden gelen komutları işler."""
    action = command.get("action")
    response = {"status": "error", "message": "Bilinmeyen hata"}

    if action == "set_angles":
        yaw = command.get("yaw", motor_fire_module.get_current_angles()[0])
        pitch = command.get("pitch", motor_fire_module.get_current_angles()[1])

        motor_fire_module.set_motor_angles(yaw, pitch)

        response = {"action": "set_angles", "status": "ok", "current_yaw": motor_fire_module.get_current_angles()[0],
                    "current_pitch": motor_fire_module.get_current_angles()[1]}
        print(f"DEBUG (rpi_motor_server): 'set_angles' komutu işlendi. Hedef Yaw: {yaw}, Pitch: {pitch}")
        sys.stdout.flush()
    elif action == "get_angles":
        current_yaw, current_pitch = motor_fire_module.get_current_angles()
        response = {"action": "get_angles", "status": "ok", "current_yaw": current_yaw,
                    "current_pitch": current_pitch}
        print(
            f"DEBUG (rpi_motor_server): 'get_angles' komutu işlendi. Mevcut Yaw: {current_yaw}, Pitch: {current_pitch}")
        sys.stdout.flush()
    elif action == "fire":
        motor_fire_module.fire_weapon()
        response = {"action": "fire", "status": "ok", "message": "Silah ateşlendi."}
        print("DEBUG (rpi_motor_server): 'fire' komutu işlendi.")
        sys.stdout.flush()
    elif action == "reset_angles":
        motor_fire_module.reset_current_angles()
        response = {"action": "reset_angles", "status": "ok", "message": "Açılar sıfırlandı."}
        print("DEBUG (rpi_motor_server): 'reset_angles' komutu işlendi.")
        sys.stdout.flush()
    elif action == "move_by_direction":
        yaw_dir = command.get("yaw_direction", 0)
        pitch_dir = command.get("pitch_direction", 0)
        degrees_to_move = command.get("degrees_to_move", 0.0)

        motor_fire_module.set_manual_move_direction(yaw_dir, pitch_dir, degrees_to_move)

        current_yaw, current_pitch = motor_fire_module.get_current_angles()
        response = {"action": "move_by_direction", "status": "ok", "current_yaw": current_yaw,
                    "current_pitch": current_pitch}
        print(
            f"DEBUG (rpi_motor_server): 'move_by_direction' komutu işlendi. Yaw Yön: {yaw_dir}, Pitch Yön: {pitch_dir}, Derece: {degrees_to_move}")
        sys.stdout.flush()
    elif action == "set_proportional_angles_delta":
        delta_yaw = command.get("delta_yaw", 0.0)
        delta_pitch = command.get("delta_pitch", 0.0)

        current_yaw, current_pitch = motor_fire_module.get_current_angles()
        target_yaw = current_yaw + delta_yaw
        target_pitch = current_pitch + delta_pitch

        motor_fire_module.set_motor_angles(target_yaw, target_pitch)

        current_yaw, current_pitch = motor_fire_module.get_current_angles()
        response = {"action": "set_proportional_angles_delta", "status": "ok", "current_yaw": current_yaw,
                    "current_pitch": current_pitch}
        print(
            f"DEBUG (rpi_motor_server): 'set_proportional_angles_delta' komutu işlendi. Delta Yaw: {delta_yaw:.2f}, Delta Pitch: {delta_pitch:.2f}")
        sys.stdout.flush()
    else:
        print(f"UYARI (rpi_motor_server): Bilinmeyen komut alındı: {command}")
        sys.stdout.flush()

    try:
        if 'conn' in globals() and conn:
            conn.sendall((json.dumps(response) + '\n').encode('utf-8'))
    except BrokenPipeError:
        print("UYARI (rpi_motor_server): Yanıt gönderilirken bağlantı kesildi (BrokenPipeError).")
        sys.stdout.flush()
        client_connected.clear()
    except Exception as e:
        print(f"HATA (rpi_motor_server): Yanıt gönderilirken hata: {e}")
        sys.stdout.flush()
        traceback.print_exc()


def cleanup_on_exit():
    """Sunucu kapatılırken kaynakları temizler."""
    global conn, server_socket
    client_connected.clear()  # Tüm thread'lerin durmasını tetikle

    if 'angle_sender_thread' in globals() and angle_sender_thread.is_alive():
        angle_sender_thread.join(timeout=1)
    if 'manual_move_thread' in globals() and manual_move_thread.is_alive():
        manual_move_thread.join(timeout=1)

    if conn:
        conn.close()
        print("DEBUG (rpi_motor_server): Bağlantı kapatıldı.")
        sys.stdout.flush()
    if server_socket:
        server_socket.close()
        print("DEBUG (rpi_motor_server): Sunucu soketi kapatıldı.")
        sys.stdout.flush()

    motor_fire_module.stop_all_motors()  # Tüm motorları durdur ve devre dışı bırak
    motor_fire_module.cleanup_gpio()
    print("DEBUG (rpi_motor_server): motor_fire_module.cleanup_gpio() çağrıldı.")
    sys.stdout.flush()
    print("DEBUG (rpi_motor_server - __main__): Sunucu betiği tamamen kapatıldı.")
    sys.stdout.flush()


# BU SATIR KESİNLİKLE HİÇBİR GİRİNTİ OLMADAN EN SOLDA OLMALIDIR
if __name__ == '__main__':
    print("DEBUG (rpi_motor_server - __main__): Sunucu betiği başlatılıyor.")
    sys.stdout.flush()
    try:
        run_server()
    except KeyboardInterrupt:
        print("Sunucu manuel olarak durduruldu (KeyboardInterrupt).")
        sys.stdout.flush()
    finally:
        print("DEBUG (rpi_motor_server - __main__): Son temizlik işlemleri başlatılıyor.")
        sys.stdout.flush()
        # run_server'ın finally bloğu tüm temizliği halletmeli, burası sadece yedek.
        # cleanup_on_exit() # run_server'ın finally bloğunda zaten çağrılıyor
