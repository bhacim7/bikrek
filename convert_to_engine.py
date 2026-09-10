# -*- coding: utf-8 -*-
"""
.onnx -> .engine (TensorRT, FP16). Bu makinede, bu TensorRT sürümüyle
üretilir; engine başka GPU/sürümde çalışmaz, orada yeniden üretilir.

Kullanım (proje klasöründe):
    python convert_to_engine.py v23m1056.onnx
    python convert_to_engine.py v23m1056.onnx --best     -> ayrıca best.engine olarak kopyalar

Giriş boyutu ONNX dosyasından okunur; elle verilmez (yanlış verilince
sessizce bozuk engine çıkıyordu). Bittiğinde config.YOLO_MODEL_PATH
hatırlatılır: sistem `best.engine` dosyasını yükler.
"""
import os
import shutil
import sys

import tensorrt as trt

TRT_LOGGER = trt.Logger(trt.Logger.WARNING)
_BURASI = os.path.dirname(os.path.abspath(__file__))


def onnx_giris_boyutu(onnx_path):
    import onnx
    m = onnx.load(onnx_path)
    return tuple(d.dim_value for d in m.graph.input[0].type.tensor_type.shape.dim)


def build_engine(onnx_file_path, engine_file_path):
    print(f"ONNX -> engine: {onnx_file_path} -> {engine_file_path}")
    builder = trt.Builder(TRT_LOGGER)
    network = builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
    parser = trt.OnnxParser(network, TRT_LOGGER)
    cfg = builder.create_builder_config()
    cfg.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 1 << 32)   # 4 GB
    if builder.platform_has_fast_fp16:
        cfg.set_flag(trt.BuilderFlag.FP16); print("FP16 açık.")
    else:
        print("FP16 yok, FP32.")
    with open(onnx_file_path, "rb") as f:
        if not parser.parse(f.read()):
            for i in range(parser.num_errors):
                print(parser.get_error(i))
            return False
    print("ONNX ayrıştırıldı; engine oluşturuluyor (birkaç dakika sürebilir)...")
    seri = builder.build_serialized_network(network, cfg)
    if seri is None:
        print("HATA: engine oluşturulamadı."); return False
    with open(engine_file_path, "wb") as f:
        f.write(seri)
    print("Engine yazıldı:", engine_file_path)
    return True


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__); sys.exit(1)
    onnx_yol = args[0]
    if not os.path.isabs(onnx_yol):
        onnx_yol = os.path.join(_BURASI, onnx_yol)
    if not os.path.exists(onnx_yol):
        print("HATA: ONNX bulunamadı:", onnx_yol); sys.exit(1)
    try:
        print("ONNX giriş boyutu:", onnx_giris_boyutu(onnx_yol))
    except Exception as e:
        print("UYARI: giriş boyutu okunamadı:", e)
    engine_yol = os.path.splitext(onnx_yol)[0] + ".engine"
    if not build_engine(onnx_yol, engine_yol):
        sys.exit(1)
    best = os.path.join(_BURASI, "best.engine")
    if "--best" in sys.argv:
        shutil.copyfile(engine_yol, best)
        print("Kopyalandı:", best, "(config.YOLO_MODEL_PATH bunu yükler)")
    else:
        print(f"Not: sistem config.YOLO_MODEL_PATH = best.engine yükler. Bu engine'i kullanmak için\n"
              f"  ya  python convert_to_engine.py {os.path.basename(onnx_yol)} --best\n"
              f"  ya da config.py'de YOLO_MODEL_PATH'i '{os.path.basename(engine_yol)}' yap.")
