from pathlib import Path
import os
import shutil

from ppadb.client import Client as AdbClient


BLUESTACKS = Path(os.getenv("TICARION_BLUESTACKS_PATH", r"C:\Program Files\BlueStacks_nxt\HD-Player.exe"))
ADB = Path(os.getenv("TICARION_ADB_PATH", shutil.which("adb") or r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe"))
INSTANCE = os.getenv("TICARION_BLUESTACKS_INSTANCE", "Pie64_1")
WINDOW_TITLE = os.getenv("TICARION_WINDOW_TITLE", "BlueStacks App Player 1")
ADB_ADDRESS = os.getenv("TICARION_ADB_ADDRESS", "127.0.0.1:5565").strip()
ISLEM_BEKLEME = 2.0
GIRIS_DENEME_SINIRI = 3

ADB_HOST = "127.0.0.1"
ADB_SERVER_PORT = 5037
ADB_PORT = int(ADB_ADDRESS.rsplit(":", 1)[1]) if ":" in ADB_ADDRESS else 0
EMULATOR_SERIAL = f"emulator-{ADB_PORT - 1}" if ADB_PORT else ""


def cihaz_hazir_mi(device) -> bool:
    try:
        return device.get_state() == "device"
    except Exception as hata:
        print(f"UYARI: {device.serial} durumu okunamadı: {hata}")
        return False


def emulatore_baglan():
    beklenen_seriler = (
        ADB_ADDRESS,
        EMULATOR_SERIAL,
    )
    try:
        devices = AdbClient(host=ADB_HOST, port=ADB_SERVER_PORT).devices()
    except Exception as hata:
        raise RuntimeError(f"ADB cihaz listesi alınamadı: {hata}") from hata

    bulunan = {device.serial: device for device in devices}
    for seri in [s for s in beklenen_seriler if s]:
        device = bulunan.get(seri)
        if device and cihaz_hazir_mi(device):
            print(
                f"[OK] {INSTANCE} cihazı seçildi: {seri} "
                f"(BlueStacks ADB portu: {ADB_PORT})"
            )
            return device
    for device in devices:
        if cihaz_hazir_mi(device):
            print(f"[OK] Otomatik seçilen cihaz: {device.serial}")
            return device

    durumlar = []
    for device in devices:
        try:
            durum = device.get_state()
        except Exception:
            durum = "erişilemiyor"
        durumlar.append(f"{device.serial}={durum}")
    raise RuntimeError(
        f"{INSTANCE} cihazı bulunamadı. Beklenen: {', '.join(beklenen_seriler)}. "
        f"Görünenler: {', '.join(durumlar) or 'yok'}"
    )


if __name__ == "__main__":
    try:
        emulatore_baglan()
    except Exception as hata:
        print(f"HATA: {hata}")
        raise SystemExit(1)
