import os
import sys
from ultralytics import YOLO
import tensorrt as trt

TRT_LOGGER = trt.Logger(trt.Logger.WARNING)


# img_size parametresi (Yükseklik, Genişlik) formatında varsayılan olarak güncellendi
def pt_to_onnx(pt_path, onnx_path, img_size=(608, 1056)):
    model = YOLO(pt_path)
    # imgsz parametresi tuple veya liste olarak verildiğinde YOLO bunu otomatik işler
    model.export(format="onnx", opset=12, imgsz=img_size, dynamic=False)

    if not os.path.exists(onnx_path):
        raise FileNotFoundError(f"ONNX oluşturulamadı: {onnx_path}")
    print("✅ ONNX export tamamlandı:", onnx_path)


if __name__ == "__main__":
    pt_path = "/HSSmultipocess/best.pt"
    onnx_path = pt_path.replace(".pt", ".onnx")
    engine_path = pt_path.replace(".pt", ".engine")

    # Çözünürlük (Yükseklik: 608, Genişlik: 1056) olarak fonksiyona geçiriliyor
    pt_to_onnx(pt_path, onnx_path, img_size=(608, 1056))