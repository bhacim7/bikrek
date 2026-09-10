# -*- coding: utf-8 -*-
"""
.pt -> .onnx (avcı modeli).

Kullanım (proje klasöründe):
    python convert_to_onnx.py v23m1056.pt              -> 736x1280 (varsayılan, deploy boyutu)
    python convert_to_onnx.py v23m1056.pt 608 1056     -> yükseklik genişlik

Model 1056'da eğitilmiş olsa da 1280'de çalıştırmak sorun değildir:
eğitimdeki `scale=0.5` augmentasyonu nesneleri 0.5-1.5 kat aralığında
gösterir, 1280 ise 1.21 kat; küçük balon fazladan piksel kazanır. Tespit
v16'ya göre kötüleşirse 608 1056 ile tekrar dene (`yolo_kalite.py` ile A/B).

Çıktı: aynı adla .onnx, aynı klasörde. Sonunda ONNX çıkış şekli okunur ve
sınıf sayısı config.CLASSES ile karşılaştırılır — uyumsuzsa deploy'da
sınıflar sessizce kayar, o yüzden burada bağırır.
"""
import os
import sys

from ultralytics import YOLO

import config

_BURASI = os.path.dirname(os.path.abspath(__file__))


def pt_to_onnx(pt_path, img_size=(736, 1280)):
    model = YOLO(pt_path)
    # nms=False: YOLO26'nın uçtan uca başı DEĞİL, [1, 4+nc, N] çıkışı;
    # inference_module._postprocess bunu bekliyor (ONNX meta'da 'nms': False).
    onnx_path = model.export(format="onnx", opset=12, imgsz=img_size, dynamic=False, simplify=True, nms=False)
    if not onnx_path or not os.path.exists(onnx_path):
        raise FileNotFoundError(f"ONNX oluşturulamadı: {onnx_path}")
    print("ONNX yazıldı:", onnx_path)
    return onnx_path


def sinif_kontrol(onnx_path):
    try:
        import onnx
    except ImportError:
        print("UYARI: 'onnx' paketi yok, çıkış şekli kontrol edilemedi (pip install onnx).")
        return
    m = onnx.load(onnx_path)
    giris = [d.dim_value for d in m.graph.input[0].type.tensor_type.shape.dim]
    cikis = [d.dim_value for d in m.graph.output[0].type.tensor_type.shape.dim]
    nc = cikis[1] - 4 if len(cikis) == 3 else None
    print(f"giriş {giris}  çıkış {cikis}  -> modelde {nc} sınıf, config.CLASSES'ta {len(config.CLASSES)}")
    if nc != len(config.CLASSES):
        print("!!! SINIF SAYISI UYUŞMUYOR: config.CLASSES'ı data.yaml sırasıyla birebir güncelle. "
              "Aksi halde sınıflar sessizce kayar / 'Unknown' düşer.")
    meta = {p.key: p.value for p in m.metadata_props}
    if "names" in meta:
        print("model sınıf adları:", meta["names"][:200])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    pt = sys.argv[1]
    if not os.path.isabs(pt):
        pt = os.path.join(_BURASI, pt)
    if not os.path.exists(pt):
        print("HATA: .pt bulunamadı:", pt); sys.exit(1)
    boyut = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) >= 4 else (736, 1280)
    print(f"{os.path.basename(pt)} -> ONNX, giriş {boyut[0]}x{boyut[1]} (YxG)")
    yol = pt_to_onnx(pt, boyut)
    sinif_kontrol(yol)
    print("Sonraki adım:  python convert_to_engine.py", os.path.basename(yol))
