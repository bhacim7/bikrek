import cv2
import time
import queue
import numpy as np
import sys
import traceback
import json
import config

# UI'a gönderilen karenin genişliği. Yükseklik en-boy oranından hesaplanır.
DISPLAY_WIDTH = 810

# --- Sınıf adından renk çıkarımı (hayalet filtresi için) ---
# Anahtar: sınıf adında aranacak parça. Değer: HSV aralıkları listesi.
# OpenCV HSV'de H 0-179 aralığındadır; kırmızı iki uçta olduğu için iki aralık.
# NOT: Kırmızı aralık sahada ölçülmüş veriyle doğrulandı. Mavi ve yeşil
# aralıklar tipik değerlerdir, sahada doğrulanmadı; bu yüzden eşik gevşek
# tutuldu (yanlışlıkla gerçek tespit elemekten kaçınmak için).
# Mavi doygunluk eşiği kasıtlı olarak yüksek (140): sahadaki soluk camgöbeği
# duvar (H=95, S=77) S>100 ile mavi oranını %5.63'e çıkarıp eşiği kıl payı
# aşıyordu ve karenin %85'ini kaplayan sahte bir 'blue_balloon' filtreden
# geçmişti. S>140 ile duvarın katkısı %0.16'ya düşüyor; gerçek bir mavi balon
# bu doygunluğu rahatça aşar.
_KIRMIZI = [((0, 120, 70), (10, 255, 255)), ((170, 120, 70), (179, 255, 255))]
_MAVI = [((100, 140, 60), (130, 255, 255))]


def _sinif_rengi(class_name):
    """
    Sınıf adından beklenen rengi çıkarır; bilinmiyorsa None.

    Yeni sınıf şeması: 'balon' (kırmızı), 'dost-*' (mavi), 'dusman-*'
    (kırmızı). Bu eşleme YENİ MİMARİDE KRİTİK: dost-F16 ile dusman-F16 aynı
    geometriye sahip ve YOLO'nun onları ayırdığı tek şey renk. Bu filtre,
    modelin renk kararını bağımsız olarak çapraz doğrular.
    """
    ad = (class_name or '').lower()
    if ad.startswith(config.FRIEND_PREFIX.lower()):
        return _MAVI
    if ad.startswith(config.ENEMY_PREFIX.lower()):
        return _KIRMIZI
    if ad == config.BALLOON_CLASS.lower():
        return _KIRMIZI
    return None


def _renk_tutarli_mi(frame, bbox, renk):
    """
    Kutunun içinde sınıfın ima ettiği renk gerçekten var mı?

    YOLO bu sahnede düz tavanda 'red_balloon' üretiyor (sahada güven 0.66'ya
    kadar çıktı). Sınıfın adı rengi söylediğine göre, kutuda o renkten eser
    olmaması tespitin sahte olduğunun güçlü göstergesidir. Ölçümde gerçek
    balon kutuları ortalama %77, hayaletler %0.1 renk içeriyordu.
    """
    x, y, w, h = [int(v) for v in bbox]
    yuk, gen = frame.shape[:2]
    # Kenar payı bırak: kutu sınırları arka planı kapsayabilir
    pay_x, pay_y = max(1, w // 8), max(1, h // 8)
    x0, y0 = max(0, x + pay_x), max(0, y + pay_y)
    x1, y1 = min(gen, x + w - pay_x), min(yuk, y + h - pay_y)
    if x1 <= x0 or y1 <= y0:
        return True  # Ölçemiyorsak elemeyiz

    kirp = frame[y0:y1, x0:x1]
    hsv = cv2.cvtColor(kirp, cv2.COLOR_BGR2HSV)
    maske = None
    for alt, ust in renk:
        m = cv2.inRange(hsv, np.array(alt, np.uint8), np.array(ust, np.uint8))
        maske = m if maske is None else cv2.bitwise_or(maske, m)
    oran = float(np.count_nonzero(maske)) / maske.size
    return oran >= config.DETECTION_COLOR_MIN_RATIO


def _boyut_makul_mu(frame, bbox):
    """
    Kutu karenin makul bir oranından büyük mü?

    Renk kontrolünden bağımsız ikinci savunma hattı. Sahada karenin %85'ini
    kaplayan sahte bir tespit üretildi; balon hangi mesafede olursa olsun
    kareyi bu kadar dolduramaz.
    """
    _, _, w, h = bbox
    yuk, gen = frame.shape[:2]
    if gen <= 0 or yuk <= 0:
        return True
    return (float(w) * float(h)) / (gen * yuk) <= config.DETECTION_MAX_AREA_RATIO


def renk_filtresi(frame, detections):
    """Saçma boyutlu ve sınıfının rengini içermeyen tespitleri eler."""
    if not config.DETECTION_COLOR_CHECK or frame is None:
        return detections
    kalan = []
    for det in detections:
        if not _boyut_makul_mu(frame, det['bbox']):
            continue
        renk = _sinif_rengi(det['class_name'])
        if renk is None or _renk_tutarli_mi(frame, det['bbox'], renk):
            kalan.append(det)
    return kalan


class YoloModel:
    def __init__(self, model_path, img_width, img_height):
        self.model_path = model_path
        self.img_width = img_width
        self.img_height = img_height

        self.model_type = None # "tensorrt" or "onnx"
        self.session = None # for onnx

        # TensorRT variables
        self.trt_runtime = None
        self.trt_engine = None
        self.trt_context = None
        self.trt_inputs = []
        self.trt_outputs = []
        self.trt_bindings = []
        self.trt_stream = None
        self.trt_input_binding_idx = None
        self.trt_output_binding_idx = None

        # ONNX variables
        self.input_name = None
        self.output_name = None

        self.load_model()

    def load_model(self):
        print(f"Loading YOLO model: {self.model_path}")

        # Defer imports
        try:
            import tensorrt as trt
            import pycuda.driver as cuda
            import pycuda.autoinit
            TRT_AVAILABLE = True
            self.trt_module = trt
            self.cuda_module = cuda
        except Exception:
            TRT_AVAILABLE = False

        import onnxruntime as ort

        if self.model_path.endswith(".engine") and TRT_AVAILABLE:
            try:
                TRT_LOGGER = self.trt_module.Logger(self.trt_module.Logger.WARNING)
                self.trt_runtime = self.trt_module.Runtime(TRT_LOGGER)
                with open(self.model_path, "rb") as f:
                    self.trt_engine = self.trt_runtime.deserialize_cuda_engine(f.read())
                if not self.trt_engine:
                    raise RuntimeError("Failed to load TensorRT engine.")

                self.trt_context = self.trt_engine.create_execution_context()

                for i in range(self.trt_engine.num_io_tensors):
                    binding_name = self.trt_engine.get_tensor_name(i)
                    binding_shape = self.trt_engine.get_tensor_shape(binding_name)
                    binding_is_input = self.trt_engine.get_tensor_mode(binding_name) == self.trt_module.TensorIOMode.INPUT

                    if binding_is_input:
                        self.trt_input_binding_idx = i
                        if len(binding_shape) == 4:
                            self.img_height = binding_shape[2]
                            self.img_width = binding_shape[3]
                    else:
                        self.trt_output_binding_idx = i

                self.trt_inputs = []
                self.trt_outputs = []
                self.trt_bindings = [None] * self.trt_engine.num_io_tensors
                self.trt_stream = self.cuda_module.Stream()

                for i in range(self.trt_engine.num_io_tensors):
                    binding_name = self.trt_engine.get_tensor_name(i)
                    binding_shape = self.trt_engine.get_tensor_shape(binding_name)
                    binding_dtype = self.trt_engine.get_tensor_dtype(binding_name)

                    size = self.trt_module.volume(binding_shape) * binding_dtype.itemsize
                    host_mem = self.cuda_module.pagelocked_empty(self.trt_module.volume(binding_shape), dtype=self.trt_module.nptype(binding_dtype))
                    device_mem = self.cuda_module.mem_alloc(size)
                    self.trt_bindings[i] = int(device_mem)

                    if self.trt_engine.get_tensor_mode(binding_name) == self.trt_module.TensorIOMode.INPUT:
                        self.trt_inputs.append({'host': host_mem, 'device': device_mem})
                    else:
                        self.trt_outputs.append({'host': host_mem, 'device': device_mem})

                self.model_type = "tensorrt"
                print("TensorRT engine loaded successfully.")
                return
            except Exception as e:
                print(f"Error loading TensorRT engine: {e}")
                traceback.print_exc()
                # Fallback to ONNX
                self.model_path = self.model_path.replace(".engine", ".onnx")
                print("Falling back to ONNX...")

        if self.model_path.endswith(".onnx"):
            try:
                providers = []
                if 'CUDAExecutionProvider' in ort.get_available_providers():
                    providers.append('CUDAExecutionProvider')
                    cuda_provider_options = {
                        "device_id": 0,
                        "arena_extend_strategy": "kNextPowerOfTwo",
                        "cudnn_conv_algo_search": "EXHAUSTIVE",
                        "do_copy_in_default_stream": True,
                        "enable_cuda_graph": False
                    }
                    sess_options = ort.SessionOptions()
                    sess_options.add_session_config_entry("session.provider.options",
                                                        json.dumps({"CUDAExecutionProvider": cuda_provider_options}))
                else:
                    sess_options = ort.SessionOptions()
                providers.append('CPUExecutionProvider')

                self.session = ort.InferenceSession(self.model_path, sess_options=sess_options, providers=providers)
                print("ONNX model loaded successfully.")

                self.input_name = self.session.get_inputs()[0].name
                self.output_name = self.session.get_outputs()[0].name
                input_shape = self.session.get_inputs()[0].shape

                if len(input_shape) == 4:
                    self.img_height = input_shape[2]
                    self.img_width = input_shape[3]
                self.model_type = "onnx"
            except Exception as e:
                print(f"Error loading ONNX model: {e}")
                self.model_type = None
        else:
            print("Unsupported model format.")

    def _preprocess(self, frame):
        img = cv2.resize(frame, (self.img_width, self.img_height))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = img.transpose((2, 0, 1)).astype(np.float32) / 255.0
        img = np.expand_dims(img, axis=0)
        return img

    def _postprocess(self, output, orig_width, orig_height, classes_list):
        boxes = []
        confidences = []
        class_ids = []

        predictions = np.squeeze(output).T
        scores = np.max(predictions[:, 4:], axis=1)
        valid_predictions = predictions[scores > config.CONF_THRESHOLD]
        valid_scores = scores[scores > config.CONF_THRESHOLD]

        for i in range(len(valid_predictions)):
            row = valid_predictions[i]
            score = valid_scores[i]
            class_id = np.argmax(row[4:])

            center_x, center_y, w, h = row[:4]
            x = int((center_x - w / 2) * orig_width / self.img_width)
            y = int((center_y - h / 2) * orig_height / self.img_height)
            width = int(w * orig_width / self.img_width)
            height = int(h * orig_height / self.img_height)

            boxes.append([x, y, width, height])
            confidences.append(float(score))
            class_ids.append(class_id)

        indices = cv2.dnn.NMSBoxes(boxes, confidences, config.CONF_THRESHOLD, config.NMS_THRESHOLD)
        if len(indices) > 0:
            indices = indices.flatten()
            filtered_boxes = [boxes[i] for i in indices]
            filtered_confidences = [confidences[i] for i in indices]
            filtered_class_ids = [class_ids[i] for i in indices]

            detections = []
            for i in range(len(filtered_boxes)):
                x, y, w, h = filtered_boxes[i]
                class_idx = filtered_class_ids[i]
                class_name = classes_list[class_idx] if class_idx < len(classes_list) else "Unknown"
                detections.append({
                    'bbox': (x, y, w, h),
                    'score': filtered_confidences[i],
                    'class_name': class_name
                })
            return detections
        return []

    def infer(self, frame, classes_list):
        if self.model_type is None or frame is None:
            return []

        input_image = self._preprocess(frame)
        orig_height, orig_width = frame.shape[:2]

        if self.model_type == "tensorrt":
            np.copyto(self.trt_inputs[0]['host'], input_image.flatten())
            self.cuda_module.memcpy_htod_async(self.trt_inputs[0]['device'], self.trt_inputs[0]['host'], self.trt_stream)
            self.trt_context.execute_v2(self.trt_bindings)
            self.cuda_module.memcpy_dtoh_async(self.trt_outputs[0]['host'], self.trt_outputs[0]['device'], self.trt_stream)
            self.trt_stream.synchronize()

            output_shape = self.trt_engine.get_tensor_shape(self.trt_engine.get_tensor_name(self.trt_output_binding_idx))
            output = self.trt_outputs[0]['host'].reshape(output_shape)

        elif self.model_type == "onnx":
            outputs = self.session.run([self.output_name], {self.input_name: input_image})
            output = outputs[0]
        else:
            return []

        return self._postprocess(output, orig_width, orig_height, classes_list)

# Çıkarım hatası tekrar tekrar yazdırılmasın diye tek seferlik bayrak.
_cikarim_hatasi_yazildi = [False]


def inference_worker(command_queue, frame_queue, result_queue):
    """
    Multiprocessing worker to run AI inference on frames.
    """
    print("Inference worker started.")
    sys.stdout.flush()

    # ÜÇ AŞAMA DA TEK MODELİ KULLANIR. Eskiden Aşama 3 ayrı bir ağırlık
    # yüklüyordu; artık görev değişiminde model yeniden yükleme gecikmesi yok.
    #
    # Model yüklemesi HATA VERİRSE süreç ölmemeli. Eskiden ölüyordu ve sonuç
    # kuyruğuna hiçbir şey gelmediği için arayüzde görüntü tamamen kayboluyordu
    # — kamera sapasağlam çalışırken ekran siyah kalıyordu ve sebebi
    # arayüzden hiç anlaşılmıyordu. Artık model yoksa tespit yapılmaz ama
    # KARELER AKMAYA DEVAM EDER; en azından görüntü görülür ve hata bellidir.
    model = None
    try:
        model = YoloModel(config.YOLO_MODEL_PATH, config.IMG_WIDTH, config.IMG_HEIGHT)
        print("Cikarim: model hazir.")
    except Exception:
        print("!!! CIKARIM: MODEL YUKLENEMEDI — tespit calismayacak, "
              "goruntu akmaya devam edecek !!!")
        traceback.print_exc()
    sys.stdout.flush()

    current_task = None
    is_running = False

    while True:
        # Check for commands
        try:
            cmd = command_queue.get_nowait()
            if isinstance(cmd, dict):
                action = cmd.get("action")
                if action == "SET_TASK":
                    current_task = cmd.get("task")
                    print(f"Inference worker task set to: {current_task}")
                elif action == "START":
                    is_running = True
                elif action == "STOP":
                    is_running = False
                    current_task = None
                elif action == "QUIT":
                    print("Inference worker quitting.")
                    break
        except queue.Empty:
            pass

        # Process frames
        try:
            frame_time, frame = frame_queue.get(timeout=0.01)

            # Check for camera error signal
            if frame is None and frame_time == -1.0:
                try:
                    result_queue.put_nowait((-1.0, None, [], None, None, 0, 0))
                except queue.Full:
                    # Kuyruk doluysa yer aç: hata sinyali kaybolmamalı.
                    try:
                        result_queue.get_nowait()
                        result_queue.put_nowait((-1.0, None, [], None, None, 0, 0))
                    except (queue.Empty, queue.Full):
                        pass
                continue

            detections = []
            qr_data = None
            qr_bbox = None

            if is_running and current_task is not None and model is not None:
                # Tek bir çıkarım hatası da süreci öldürmemeli: kare akışı
                # tespitten daha önceliklidir, operatör hiç değilse görüntüyü
                # görebilmeli.
                try:
                    detections = model.infer(frame, config.CLASSES)
                except Exception:
                    if not _cikarim_hatasi_yazildi[0]:
                        _cikarim_hatasi_yazildi[0] = True
                        print("!!! CIKARIM HATASI (bir kez yazdirilir) !!!")
                        traceback.print_exc()
                        sys.stdout.flush()
                    detections = []

                # Hayalet eleme: sınıfının rengini içermeyen tespitleri at.
                # Burada yapılıyor çünkü ham çözünürlüklü kare yalnızca bu
                # süreçte mevcut ve kutu koordinatları da bu kareye göre.
                detections = renk_filtresi(frame, detections)

            # Kareyi IPC yükünü azaltmak için küçült. Tespit kutuları HAM çözünürlükte
            # kalır; kilitli hedefin rengini yalnızca UI bildiği için çizimi UI yapar.
            # En-boy oranı korunur, böylece kamera hangi çözünürlüğü verirse versin
            # görüntü bozulmaz ve UI tek bir ölçek katsayısıyla koordinat dönüştürebilir.
            orig_height, orig_width = frame.shape[:2]
            if orig_width > DISPLAY_WIDTH:
                display_height = max(1, int(round(DISPLAY_WIDTH * orig_height / orig_width)))
                downscaled_frame = cv2.resize(frame, (DISPLAY_WIDTH, display_height))
            else:
                downscaled_frame = frame

            # Send result even if empty so UI can update the video
            if result_queue.full():
                try:
                    result_queue.get_nowait()
                except queue.Empty:
                    pass
            try:
                result_queue.put_nowait(
                    (frame_time, downscaled_frame, detections, qr_data, qr_bbox, orig_width, orig_height))
            except queue.Full:
                pass

        except queue.Empty:
            pass
