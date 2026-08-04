import socket
import json
import traceback
import queue
import time
from PyQt5.QtCore import QThread, pyqtSignal

class RPiCommunicator(QThread):
    # Sinyaller: Ana arayüze bilgi göndermek için
    status_update_signal = pyqtSignal(str)
    connection_status_signal = pyqtSignal(bool)
    angles_update_signal = pyqtSignal(float, float)  # yaw, pitch
    response_received_signal = pyqtSignal(dict)  # Genel yanıtlar için

    def __init__(self, rpi_ip, rpi_port):
        super().__init__()
        self.rpi_ip = rpi_ip
        self.rpi_port = rpi_port
        self.rpi_socket = None
        self.is_connected = False
        self.command_queue = queue.Queue()  # Ana iş parçacığından komut almak için
        self.stop_requested = False
        self.socket_buffer = ""  # Gelen veriler için tampon

    def run(self):
        print("RPiCommunicator iş parçacığı başlatıldı.")
        while not self.stop_requested:
            if not self.is_connected:
                self._connect_to_rpi()
                if not self.is_connected:
                    time.sleep(1)  # Bağlantı başarısız olursa kısa bir süre bekle
                    continue

            # Komut kuyruğunu kontrol et ve gönder
            try:
                command = self.command_queue.get(timeout=0.01)  # Çok kısa zaman aşımı
                if command:
                    self._send_command(command)
            except queue.Empty:
                pass  # Kuyruk boş, devam et

            # Yanıtları dinle (engellemeyen veya kısa engellemeli)
            response = self._receive_response_non_blocking()
            if response:
                self.response_received_signal.emit(response)
                # Eğer bir açı güncellemesi ise, sinyali doğrudan yay
                if response.get("action") in ["get_angles", "set_angles", "move_by_direction",
                                              "set_proportional_angles_delta"] and response.get("status") == "ok":
                    yaw = response.get("current_yaw", 0.0)
                    pitch = response.get("current_pitch", 0.0)
                    self.angles_update_signal.emit(yaw, pitch)

            # CPU kullanımını azaltmak için küçük bir gecikme
            time.sleep(0.001)

        print("RPiCommunicator iş parçacığı durduruldu.")
        self._disconnect_rpi()

    def _connect_to_rpi(self):
        print(f"HATA AYIKLAMA (RPiComm): RPi'ye bağlanılıyor: {self.rpi_ip}:{self.rpi_port}...")
        try:
            self.rpi_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.rpi_socket.settimeout(5)  # Bağlantı zaman aşımı
            self.rpi_socket.connect((self.rpi_ip, self.rpi_port))
            self.rpi_socket.settimeout(0.01)  # Veri alışverişi için çok kısa zaman aşımı
            self.is_connected = True
            self.connection_status_signal.emit(True)
            self.status_update_signal.emit("Durum: Raspberry Pi'ye Bağlandı!")
            print(
                f"HATA AYIKLAMA (RPiComm): Raspberry Pi'ye {self.rpi_ip}:{self.rpi_port} üzerinden başarıyla bağlanıldı.")
            # Bağlantıdan sonra RPi'den başlangıç açılarını iste (RPi periyodik olarak gönderdiği için gereksiz olabilir)
            self.command_queue.put({"action": "get_angles"})  # Kuyruğa ekle, iş parçacığı işleyecek
        except socket.error as e:
            print(f"HATA (RPiComm): RPi Bağlantı Hatası: {e}")
            traceback.print_exc()
            self.is_connected = False
            self.connection_status_signal.emit(False)
            self.status_update_signal.emit(f"Hata: RPi Bağlantı Hatası: {e}")
            if self.rpi_socket:
                self.rpi_socket.close()
            self.rpi_socket = None
        except Exception as e:
            print(f"HATA (RPiComm): Beklenmedik RPi bağlantı hatası: {e}")
            traceback.print_exc()
            self.is_connected = False
            self.connection_status_signal.emit(False)
            self.status_update_signal.emit(f"Hata: RPi Bağlantı Hatası: {e}")
            if self.rpi_socket:
                self.rpi_socket.close()
            self.rpi_socket = None
        finally:
            if not self.is_connected and self.rpi_socket:
                self.rpi_socket.close()
                self.rpi_socket = None

    def _disconnect_rpi(self):
        print("HATA AYIKLAMA (RPiComm): _disconnect_rpi çağrıldı.")
        if self.rpi_socket and self.is_connected:
            try:
                self.rpi_socket.shutdown(socket.SHUT_RDWR)
                self.rpi_socket.close()
                self.rpi_socket = None
                self.is_connected = False
                self.socket_buffer = ""
                self.connection_status_signal.emit(False)
                self.status_update_signal.emit("Durum: Raspberry Pi bağlantısı kesildi.")
                print("HATA AYIKLAMA: Raspberry Pi bağlantısı kesildi.")
            except Exception as e:
                print(f"HATA (RPiComm): RPi bağlantısı kesilirken hata: {e}")
                traceback.print_exc()
                self.status_update_signal.emit(f"Hata: RPi bağlantı kesme hatası: {e}")

    def _send_command(self, command_dict):
        if not self.is_connected or self.rpi_socket is None:
            self.status_update_signal.emit("Hata: Raspberry Pi'ye bağlı değil, komut gönderilemedi.")
            print("HATA (RPiComm): Raspberry Pi'ye bağlı değil, komut gönderilemedi.")
            return False
        try:
            message = (json.dumps(command_dict) + '\\n').encode('utf-8')
            print(f"HATA AYIKLAMA (RPiComm): Komut gönderildi: {message.decode('utf-8').strip()}")
            self.rpi_socket.sendall(message)
            return True
        except socket.error as e:
            print(f"HATA (RPiComm): Komut gönderilirken soket bağlantı hatası: {e}. Bağlantı kesiliyor.")
            traceback.print_exc()
            self.status_update_signal.emit(f"Hata: RPi bağlantısı kesildi: {e}")
            self._disconnect_rpi()
            return False
        except Exception as e:
            print(f"HATA (RPiComm): Komut gönderilirken hata: {e}")
            traceback.print_exc()
            self.status_update_signal.emit(f"Hata: Komut gönderilemedi: {e}")
            return False

    def _receive_response_non_blocking(self):
        """
        Soket bağlantısından yanıtı engellemeyen bir şekilde okur.
        Tam bir JSON mesajı alınana kadar tamponlar.
        """
        if not self.is_connected or self.rpi_socket is None:
            return None

        try:
            # Engellemeyen okuma için zaman aşımını 0.01 saniyeye ayarla
            self.rpi_socket.settimeout(0.01)
            chunk = self.rpi_socket.recv(1024).decode('utf-8')
            if not chunk:
                print("HATA AYIKLAMA (RPiComm): _receive_response_non_blocking: Sunucu bağlantıyı kapattı (boş parça).")
                self._disconnect_rpi()
                return None

            self.socket_buffer += chunk

            if '\\n' in self.socket_buffer:
                message, self.socket_buffer = self.socket_buffer.split('\\n', 1)
                try:
                    return json.loads(message)
                except json.JSONDecodeError as e:
                    print(f"HATA (RPiComm): JSON ayrıştırma hatası: {e}. Hatalı veri: '{message[:100]}...'")
                    self.status_update_signal.emit(f"Hata: RPi yanıtı ayrıştırılamadı: {e}")
                    return None

            if len(self.socket_buffer) > 4096:
                print("UYARI (RPiComm): Tampon çok büyüdü, '\\n' bulunamadı. Tampon temizleniyor.")
                self.socket_buffer = ""
                return None

        except socket.timeout:
            pass  # Veri yok, normal
        except socket.error as e:
            print(f"HATA (RPiComm): Yanıt alınırken soket hatası: {e}. Bağlantı kesiliyor.")
            traceback.print_exc()
            self.status_update_signal.emit(f"Hata: RPi bağlantısı kesildi: {e}")
            self._disconnect_rpi()
        except Exception as e:
            print(f"HATA (RPiComm): Yanıt alınırken beklenmedik hata: {e}")
            traceback.print_exc()
            self._disconnect_rpi()
        return None

    def request_stop(self):
        self.stop_requested = True
