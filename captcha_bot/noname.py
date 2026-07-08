from __future__ import annotations

from pathlib import Path
import os
import time

import cv2
import numpy as np
from ppadb.client import Client as AdbClient


# Mac/emulator için referans ekran: dikey 1080x1920.
# Görsel algılama başarısız olursa bu koordinatlar oranlanarak kullanılır.
REFERANS_GENISLIK = 1080
REFERANS_YUKSEKLIK = 1920
SLIDER_START_X = 170
SLIDER_START_Y = 1165
TAMAM_X = 540
TAMAM_Y = 1650

HAREKET_ORANI = float(os.getenv("TICARION_CAPTCHA_HAREKET_ORANI", "1.00"))
HEDEF_OFFSET_X = int(os.getenv("TICARION_CAPTCHA_OFFSET_X", "0"))
MIN_ESLESME_GUVENI = float(os.getenv("TICARION_CAPTCHA_MIN_GUVEN", "0.42"))

KLASOR = Path(__file__).resolve().parent
DEBUG_GORSEL = KLASOR / "captcha_debug.png"
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


def goruntu_varyantlari(gray):
    return {
        "gray": gray,
        "equalized": cv2.equalizeHist(gray),
        "edges": cv2.Canny(gray, 50, 150),
    }


def sablon_varyanti(template, ad: str):
    if ad == "equalized":
        return cv2.equalizeHist(template)
    if ad == "edges":
        return cv2.Canny(template, 50, 150)
    return template


def sablon_merkezini_bul(img_gray, dosya: str, beklenen_olcek: float):
    template = cv2.imread(str(KLASOR / dosya), 0)
    if template is None:
        raise RuntimeError(f"CAPTCHA şablonu okunamadı: {dosya}")

    en_iyi = None
    for varyant_adi, kaynak in goruntu_varyantlari(img_gray).items():
        template_varyanti = sablon_varyanti(template, varyant_adi)
        for carpan in (0.60, 0.70, 0.80, 0.90, 1.0, 1.10, 1.20, 1.35, 1.50, 1.70):
            olcek = beklenen_olcek * carpan
            if olcek <= 0:
                continue
            yeniden = cv2.resize(
                template_varyanti, None, fx=olcek, fy=olcek, interpolation=cv2.INTER_AREA
            )
            h, w = yeniden.shape[:2]
            if h < 12 or w < 12 or h > kaynak.shape[0] or w > kaynak.shape[1]:
                continue
            res = cv2.matchTemplate(kaynak, yeniden, cv2.TM_CCOEFF_NORMED)
            _, guven, _, max_loc = cv2.minMaxLoc(res)
            if en_iyi is None or guven > en_iyi["guven"]:
                en_iyi = {
                    "guven": guven,
                    "max_loc": max_loc,
                    "w": w,
                    "h": h,
                    "olcek": olcek,
                    "varyant": varyant_adi,
                }

    if en_iyi is None:
        raise RuntimeError(f"{dosya} için uygun şablon ölçeği bulunamadı.")
    if en_iyi["guven"] < MIN_ESLESME_GUVENI:
        raise RuntimeError(
            f"{dosya} eşleşme güveni düşük: {en_iyi['guven']:.2f} "
            f"(ölçek {en_iyi['olcek']:.2f}, yöntem {en_iyi['varyant']})"
        )

    merkez = (
        en_iyi["max_loc"][0] + (en_iyi["w"] // 2),
        en_iyi["max_loc"][1] + (en_iyi["h"] // 2),
    )
    return merkez, en_iyi["guven"], en_iyi["olcek"], en_iyi["varyant"]


def renk_ve_sekille_merkezleri_bul(img):
    """Şablon tutmazsa yeşil parça ve beyaz kesik kareyi bulur."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    yukseklik, genislik = img.shape[:2]

    yesil = cv2.inRange(hsv, np.array([35, 55, 55]), np.array([100, 255, 255]))
    yesil = cv2.morphologyEx(yesil, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    konturlar, _ = cv2.findContours(yesil, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    yesil_adaylar = []
    for kontur in konturlar:
        x, y, w, h = cv2.boundingRect(kontur)
        alan = cv2.contourArea(kontur)
        if alan < 18 or w < 4 or h < 4:
            continue
        if y < yukseklik * 0.20 or y > yukseklik * 0.75:
            continue
        yesil_adaylar.append((alan, x, y, w, h))
    if not yesil_adaylar:
        raise RuntimeError("Yeşil CAPTCHA parçası renk yöntemiyle bulunamadı.")

    _, x, y, w, h = max(yesil_adaylar)
    parca = (x + w // 2, y + h // 2)

    band_y1 = max(0, parca[1] - round(100 * yukseklik / REFERANS_YUKSEKLIK))
    band_y2 = min(yukseklik, parca[1] + round(100 * yukseklik / REFERANS_YUKSEKLIK))
    band = img[band_y1:band_y2]
    hsv_band = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    beyaz = cv2.inRange(hsv_band, np.array([0, 0, 140]), np.array([179, 110, 255]))
    beyaz = cv2.morphologyEx(beyaz, cv2.MORPH_CLOSE, np.ones((13, 13), np.uint8))
    beyaz = cv2.dilate(beyaz, np.ones((5, 5), np.uint8), iterations=1)
    konturlar, _ = cv2.findContours(beyaz, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    hedef_adaylari = []
    for kontur in konturlar:
        bx, by, bw, bh = cv2.boundingRect(kontur)
        global_x = bx
        global_y = band_y1 + by
        if global_x <= parca[0] + 20:
            continue
        oran = bw / max(1, bh)
        if not 0.55 <= oran <= 1.55:
            continue
        if bw < 18 or bh < 18 or bw > genislik * 0.25 or bh > yukseklik * 0.20:
            continue
        alan = cv2.contourArea(kontur)
        hedef_adaylari.append((alan, global_x, global_y, bw, bh))

    if not hedef_adaylari:
        raise RuntimeError("Beyaz CAPTCHA boşluğu renk/şekil yöntemiyle bulunamadı.")

    _, bx, by, bw, bh = max(hedef_adaylari)
    hedef = (bx + bw // 2, by + bh // 2)
    return hedef, parca, "renk-sekil"


def merkezleri_bul(img, gray, beklenen_sablon_olcegi):
    yukseklik, genislik = img.shape[:2]
    try:
        hedef, hedef_guveni, hedef_olcegi, hedef_yontemi = sablon_merkezini_bul(
            gray, "bosluk.png", beklenen_sablon_olcegi
        )
        parca, parca_guveni, parca_olcegi, parca_yontemi = sablon_merkezini_bul(
            gray, "parca.png", beklenen_sablon_olcegi
        )
        if not (yukseklik * 0.20 <= parca[1] <= yukseklik * 0.75):
            raise RuntimeError(f"?ablon par?a konumu mant?ks?z: {parca}")
        if not (yukseklik * 0.20 <= hedef[1] <= yukseklik * 0.75):
            raise RuntimeError(f"?ablon bo?luk konumu mant?ks?z: {hedef}")
        y_tolerans = max(35, round(35 * yukseklik / REFERANS_YUKSEKLIK))
        if abs(hedef[1] - parca[1]) > y_tolerans:
            raise RuntimeError(
                f"?ablon par?a/bo?luk hizas? tutars?z: par?a={parca}, bo?luk={hedef}, tolerans={y_tolerans}"
            )
        return hedef, parca, hedef_guveni, parca_guveni, hedef_olcegi, parca_olcegi, hedef_yontemi, parca_yontemi
    except Exception as sablon_hatasi:
        print(f"?ablon y?ntemi ba?ar?s?z; renk/?ekil y?ntemi deneniyor: {sablon_hatasi}")
        hedef, parca, yontem = renk_ve_sekille_merkezleri_bul(img)
        return hedef, parca, 1.0, 1.0, 1.0, 1.0, yontem, yontem

def slider_noktasini_bul(img, sx: float, sy: float) -> tuple[int, int]:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    yukseklik, genislik = img.shape[:2]
    # Fotoğraftaki slider noktası açık mavi/cyan.
    maske = cv2.inRange(hsv, np.array([85, 60, 80]), np.array([115, 255, 255]))
    konturlar, _ = cv2.findContours(maske, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    adaylar = []
    for kontur in konturlar:
        x, y, w, h = cv2.boundingRect(kontur)
        alan = cv2.contourArea(kontur)
        if alan < 15 or w < 4 or h < 4:
            continue
        if y < yukseklik * 0.45 or y > yukseklik * 0.80:
            continue
        if x > genislik * 0.35:
            continue
        adaylar.append((alan, x, y, w, h))
    if adaylar:
        _, x, y, w, h = max(adaylar)
        return x + w // 2, y + h // 2
    print("Mavi slider noktası bulunamadı; eski ölçekli başlangıç kullanılacak.")
    return olcekli_nokta(SLIDER_START_X, SLIDER_START_Y, sx, sy)


def dogrula_butonunu_bul(img, sx: float, sy: float) -> tuple[int, int]:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    yukseklik, genislik = img.shape[:2]
    # Kırmızı/pembe Doğrula butonu.
    maske1 = cv2.inRange(hsv, np.array([0, 45, 120]), np.array([12, 255, 255]))
    maske2 = cv2.inRange(hsv, np.array([165, 45, 120]), np.array([179, 255, 255]))
    maske = cv2.bitwise_or(maske1, maske2)
    maske = cv2.morphologyEx(maske, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    konturlar, _ = cv2.findContours(maske, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    adaylar = []
    for kontur in konturlar:
        x, y, w, h = cv2.boundingRect(kontur)
        alan = cv2.contourArea(kontur)
        if alan < 600 or w < genislik * 0.20 or h < 18:
            continue
        if y < yukseklik * 0.55:
            continue
        adaylar.append((alan, x, y, w, h))
    if adaylar:
        _, x, y, w, h = max(adaylar)
        return x + w // 2, y + h // 2
    print("Kırmızı Doğrula butonu bulunamadı; eski ölçekli tıklama kullanılacak.")
    return olcekli_nokta(TAMAM_X, TAMAM_Y, sx, sy)


def debug_gorseli_kaydet(img, hedef=None, parca=None, slider=None, buton=None) -> None:
    kopya = img.copy()
    if hedef:
        cv2.circle(kopya, hedef, 12, (0, 0, 255), 3)
        cv2.putText(kopya, "bosluk", (hedef[0] + 15, hedef[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    if parca:
        cv2.circle(kopya, parca, 12, (0, 255, 0), 3)
        cv2.putText(kopya, "parca", (parca[0] + 15, parca[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    if slider:
        cv2.circle(kopya, slider, 12, (255, 0, 0), 3)
        cv2.putText(kopya, "slider", (slider[0] + 15, slider[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
    if buton:
        cv2.circle(kopya, buton, 12, (0, 255, 255), 3)
        cv2.putText(kopya, "dogrula", (buton[0] + 15, buton[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    cv2.imwrite(str(DEBUG_GORSEL), kopya)
    print(f"Debug CAPTCHA görseli kaydedildi: {DEBUG_GORSEL}")


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

    try:
        (
            (hedef_x, hedef_y),
            (parca_x, parca_y),
            hedef_guveni,
            parca_guveni,
            hedef_olcegi,
            parca_olcegi,
            hedef_yontemi,
            parca_yontemi,
        ) = merkezleri_bul(img, gray, beklenen_sablon_olcegi)
    except Exception:
        debug_gorseli_kaydet(img)
        raise

    y_tolerans = max(25, round(25 * sy))
    if abs(hedef_y - parca_y) > y_tolerans:
        debug_gorseli_kaydet(img, (hedef_x, hedef_y), (parca_x, parca_y))
        raise RuntimeError(
            "CAPTCHA parçası ile boşluk aynı hizada değil; sürükleme iptal edildi. "
            f"Parça Y={parca_y}, boşluk Y={hedef_y}, tolerans={y_tolerans}"
        )

    slider_start_x, slider_start_y = slider_noktasini_bul(img, sx, sy)
    tamam_x, tamam_y = dogrula_butonunu_bul(img, sx, sy)

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
        f"Parça: {parca_x},{parca_y} ({parca_guveni:.0%}, ölçek {parca_olcegi:.2f}, {parca_yontemi}) | "
        f"Boşluk: {hedef_x},{hedef_y} ({hedef_guveni:.0%}, ölçek {hedef_olcegi:.2f}, {hedef_yontemi}) | "
        f"Slider: {slider_start_x},{slider_start_y} -> {nihai_x},{slider_start_y} | "
        f"Doğrula: {tamam_x},{tamam_y}"
    )
    debug_gorseli_kaydet(
        img,
        (hedef_x, hedef_y),
        (parca_x, parca_y),
        (slider_start_x, slider_start_y),
        (tamam_x, tamam_y),
    )

    device.shell(f"input swipe {slider_start_x} {slider_start_y} {nihai_x} {slider_start_y} 950")

    time.sleep(1.5)
    device.shell(f"input tap {tamam_x} {tamam_y}")


if __name__ == "__main__":
    captchayi_gec()
