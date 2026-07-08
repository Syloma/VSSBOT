from pathlib import Path
import os
import time

import cv2
import numpy as np
from ppadb.client import Client as AdbClient


# Bu değerler eski sabit ayarın alındığı referans ekran içindir.
# Farklı çözünürlükte X/Y koordinatları ekran oranına göre ölçeklenir.
REFERANS_GENISLIK = 1600
REFERANS_YUKSEKLIK = 900
SLIDER_START_X = 573
SLIDER_START_Y = 615
TAMAM_X = 800
TAMAM_Y = 825

HAREKET_ORANI = 1.10
HEDEF_OFFSET_X = 0
MIN_ESLESME_GUVENI = 0.65

KLASOR = Path(__file__).resolve().parent
ADB_HOST = os.getenv("TICARION_ADB_HOST", "127.0.0.1")
ADB_SERVER_PORT = int(os.getenv("TICARION_ADB_SERVER_PORT", "5037"))
ADB_ADDRESS = os.getenv("TICARION_ADB_ADDRESS", "127.0.0.1:5565").strip()


def emulatore_baglan():
    client = AdbClient(host=ADB_HOST, port=ADB_SERVER_PORT)
    cihazlar = client.devices()
    if ADB_ADDRESS:
        cihaz = next((d for d in cihazlar if d.serial == ADB_ADDRESS), None)
        if cihaz is not None:
            return cihaz
        if cihazlar:
            print(f"{ADB_ADDRESS} bulunamadı; ilk görünen ADB cihazı seçiliyor: {cihazlar[0].serial}")
            return cihazlar[0]
    elif cihazlar:
        return cihazlar[0]

    gorunen = ", ".join(d.serial for d in cihazlar) or "yok"
    beklenen = ADB_ADDRESS or "ilk görünen cihaz"
    raise RuntimeError(f"ADB cihazı bulunamadı. Beklenen: {beklenen}. Görünenler: {gorunen}")


def ekran_olcegi(genislik: int, yukseklik: int) -> tuple[float, float]:
    return genislik / REFERANS_GENISLIK, yukseklik / REFERANS_YUKSEKLIK


def olcekli_nokta(x: int, y: int, sx: float, sy: float) -> tuple[int, int]:
    return round(x * sx), round(y * sy)


def sinirla(deger: int, alt: int, ust: int) -> int:
    return max(alt, min(ust, deger))


def sablon_merkezini_bul(img_gray, dosya: str, beklenen_olcek: float):
    template = cv2.imread(str(KLASOR / dosya), 0)
    if template is None:
        raise RuntimeError(f"CAPTCHA şablonu okunamadı: {dosya}")

    en_iyi = None
    # Farklı emulator çözünürlüklerinde CAPTCHA görseli de küçülüp büyüyebilir.
    # Bu yüzden şablonu beklenen ölçeğin çevresinde birkaç boyutta deniyoruz.
    for carpan in (0.75, 0.85, 0.95, 1.0, 1.05, 1.15, 1.25, 1.35):
        olcek = beklenen_olcek * carpan
        if olcek <= 0:
            continue
        yeniden = cv2.resize(template, None, fx=olcek, fy=olcek, interpolation=cv2.INTER_AREA)
        h, w = yeniden.shape[:2]
        if h < 12 or w < 12 or h > img_gray.shape[0] or w > img_gray.shape[1]:
            continue
        res = cv2.matchTemplate(img_gray, yeniden, cv2.TM_CCOEFF_NORMED)
        _, guven, _, max_loc = cv2.minMaxLoc(res)
        if en_iyi is None or guven > en_iyi["guven"]:
            en_iyi = {"guven": guven, "max_loc": max_loc, "w": w, "h": h, "olcek": olcek}

    if en_iyi is None:
        raise RuntimeError(f"{dosya} için uygun şablon ölçeği bulunamadı.")
    if en_iyi["guven"] < MIN_ESLESME_GUVENI:
        raise RuntimeError(
            f"{dosya} eşleşme güveni düşük: {en_iyi['guven']:.2f} "
            f"(ölçek {en_iyi['olcek']:.2f})"
        )

    merkez = (
        en_iyi["max_loc"][0] + (en_iyi["w"] // 2),
        en_iyi["max_loc"][1] + (en_iyi["h"] // 2),
    )
    return merkez, en_iyi["guven"], en_iyi["olcek"]


def captchayi_gec():
    device = emulatore_baglan()
    time.sleep(1)

    result = device.screencap()
    img = cv2.imdecode(np.frombuffer(result, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("Ekran görüntüsü okunamadı.")

    yukseklik, genislik = img.shape[:2]
    sx, sy = ekran_olcegi(genislik, yukseklik)
    beklenen_sablon_olcegi = min(sx, sy)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    (hedef_x, hedef_y), hedef_guveni, hedef_olcegi = sablon_merkezini_bul(
        gray, "bosluk.png", beklenen_sablon_olcegi
    )
    (parca_x, parca_y), parca_guveni, parca_olcegi = sablon_merkezini_bul(
        gray, "parca.png", beklenen_sablon_olcegi
    )

    y_tolerans = max(25, round(25 * sy))
    if abs(hedef_y - parca_y) > y_tolerans:
        raise RuntimeError(
            "CAPTCHA parçası ile boşluk aynı hizada değil; sürükleme iptal edildi. "
            f"Parça Y={parca_y}, boşluk Y={hedef_y}, tolerans={y_tolerans}"
        )

    slider_start_x, slider_start_y = olcekli_nokta(SLIDER_START_X, SLIDER_START_Y, sx, sy)
    tamam_x, tamam_y = olcekli_nokta(TAMAM_X, TAMAM_Y, sx, sy)

    goruntu_mesafesi = hedef_x - parca_x
    slider_mesafesi = round(goruntu_mesafesi * HAREKET_ORANI)
    nihai_x = slider_start_x + slider_mesafesi + round(HEDEF_OFFSET_X * sx)
    nihai_x = sinirla(nihai_x, 0, genislik - 1)
    slider_start_y = sinirla(slider_start_y, 0, yukseklik - 1)
    tamam_x = sinirla(tamam_x, 0, genislik - 1)
    tamam_y = sinirla(tamam_y, 0, yukseklik - 1)

    print(
        f"--> Ekran: {genislik}x{yukseklik} | "
        f"Ölçek: x={sx:.2f}, y={sy:.2f} | "
        f"Parça: {parca_x},{parca_y} ({parca_guveni:.0%}, ölçek {parca_olcegi:.2f}) | "
        f"Boşluk: {hedef_x},{hedef_y} ({hedef_guveni:.0%}, ölçek {hedef_olcegi:.2f}) | "
        f"Slider: {slider_start_x},{slider_start_y} -> {nihai_x},{slider_start_y}"
    )

    device.shell(f"input swipe {slider_start_x} {slider_start_y} {nihai_x} {slider_start_y} 850")

    time.sleep(1.5)
    device.shell(f"input tap {tamam_x} {tamam_y}")


if __name__ == "__main__":
    captchayi_gec()
