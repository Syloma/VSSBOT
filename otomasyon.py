import ctypes
from ctypes import wintypes
from contextlib import contextmanager
from datetime import datetime
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
import urllib.request
import urllib.error
import unicodedata

from hesap_hafizasi import hesap_hafizasi
from chrome_dom import ChromeDOM


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def kodlamayi_duzelt(metin: str) -> str:
    if any(isaret in metin for isaret in ("â", "ð", "ï")):
        try:
            return metin.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            sade = "".join(ch for ch in metin if ch.isascii() and ch.isprintable()).strip()
            if sade:
                return sade
    return metin


PROJE_KLASORU = Path(__file__).resolve().parent
IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"


def ortam_yolu(anahtar: str, varsayilan: str) -> Path:
    return Path(os.getenv(anahtar, varsayilan)).expanduser()


def adb_varsayilan_yolu() -> str:
    if IS_WINDOWS:
        return r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe"
    return shutil.which("adb") or "adb"


BLUESTACKS = ortam_yolu(
    "TICARION_BLUESTACKS_PATH",
    r"C:\Program Files\BlueStacks_nxt\HD-Player.exe" if IS_WINDOWS else "/Applications/BlueStacks.app",
)
ADB = ortam_yolu("TICARION_ADB_PATH", adb_varsayilan_yolu())
INSTANCE = os.getenv("TICARION_BLUESTACKS_INSTANCE", "Pie64_1")
WINDOW_TITLE = os.getenv("TICARION_WINDOW_TITLE", "BlueStacks App Player 1")
ADB_ADDRESS = os.getenv("TICARION_ADB_ADDRESS", "127.0.0.1:5565").strip()
ISLEM_BEKLEME = 2.0
GIRIS_DENEME_SINIRI = 5
CAPTCHA_YARDIMCI_BEKLEME = 8
GIRIS_DOGRULAMA_SONUC_BEKLEME = 10
LAZER_MERMISI_ALT_SINIR = 50_000
LAZER_MERMISI_URETIM_ADEDI = 1_000_000

# KULLANICI AYARLARI ---------------------------------------------------------
# CAPTCHA yardımcısı ve görsel şablonları proje içinde birlikte tutulur.
NONAME_BOT = Path(os.getenv("TICARION_NONAME_BOT", str(PROJE_KLASORU / "captcha_bot" / "noname.py"))).expanduser()
NONAME_LOG = Path(os.getenv("TICARION_NONAME_LOG", str(PROJE_KLASORU / "noname_hatalari.log"))).expanduser()

# Oyun adları girişten sonra hesaplar.json içine otomatik kaydedilir.
HESAP_OYUN_ADLARI = {}
OPSIYONEL_HESAP_ADLARI = {"volkan arslan"}
# ---------------------------------------------------------------------------

BASLANGIC_SAYFASI_URL = "https://www.ticariononline.com/tr/girisyap.php"
MADEN_REZERVI_URL = "https://www.ticariononline.com/tr/maden-rezervi.php"
EYALET_FABRIKASI_URL = "https://www.ticariononline.com/tr/eyalet-fabrikasi.php"
EYALET_SANAYISI_URL = "https://www.ticariononline.com/tr/sanayi-eyalet.php"
YETENEK_OKULU_URL = "https://www.ticariononline.com/tr/yetenek_okulu.php"
AKTIF_MEKANLAR_URL = "https://www.ticariononline.com/tr/aktifmekanlar.php"
UZAY_GEMISI_URL = "https://www.ticariononline.com/tr/uzay-gemisi.php"
UZAY_FARM_URL = "https://www.ticariononline.com/tr/uzay_farm_haritasi.php"
UZAY_SAVAS_URL = "https://www.ticariononline.com/tr/uzayfarm.php"
KAZANC_DB = Path(os.getenv("TICARION_KAZANC_DB", str(PROJE_KLASORU / "kazanc_kayitlari.db"))).expanduser()
KAZANC_LOG = Path(os.getenv("TICARION_KAZANC_LOG", str(PROJE_KLASORU / "kazanc_kayitlari.jsonl"))).expanduser()
KAZANC_BOT_TOKEN_ENV = "TICARION_KAZANC_BOT_TOKEN"
KAZANC_CHAT_ID_ENV = "TICARION_KAZANC_CHAT_ID"
KAZANC_THREAD_ID_ENV = "TICARION_KAZANC_THREAD_ID"
UZAY_TELEGRAM_CHAT_ID = "-1004341424019"
# Telegram Bot API'de Genel konu için message_thread_id gönderilmez.
UZAY_TELEGRAM_THREAD_ID = ""
URETIM_TELEGRAM_CHAT_ID = "-1004341424019"
URETIM_TELEGRAM_THREAD_ID = "448"
_TELEGRAM_HEDEFLERI_OKUNDU = False


class DogrulamaYardimcisiHatasi(RuntimeError):
    pass


class LazerMermisiUretimHatasi(RuntimeError):
    pass

SW_RESTORE = 9
VK_F11 = 0x7A
KEYEVENTF_KEYUP = 0x0002


def hesap_adi(hesap) -> str:
    return hesap.oyun_adi or HESAP_OYUN_ADLARI.get(hesap.kullanici_adi) or hesap.kullanici_adi


def calisacak_hesaplari_sec(hesaplar):
    """Opsiyonel hesapları her bot turunda kullanıcı tercihine göre süz."""
    otomatik_mod = os.environ.get("TICARION_OTOMATIK_MOD") == "1"
    secilenler = []
    for hesap in hesaplar:
        ad = hesap_adi(hesap)
        if ad.casefold().strip() not in OPSIYONEL_HESAP_ADLARI:
            secilenler.append(hesap)
            continue
        if otomatik_mod:
            print(f"{ad}: otomatik modda atlanacak.", flush=True)
            continue
        cevap = input(f"{ad} hesabı bu tur çalışsın mı? [e/H]: ").strip().casefold()
        if cevap in {"e", "evet"}:
            secilenler.append(hesap)
            print(f"{ad}: bu tur aktif.", flush=True)
        else:
            print(f"{ad}: bu tur atlanacak.", flush=True)
    return secilenler


def enerji_bitti(metin: str) -> bool:
    sade = (metin or "").casefold()
    return "enerji" in sade and any(
        ifade in sade for ifade in ("yetersiz", "bitti", "bitmiştir", "kalmadı", "yok")
    )


@contextmanager
def db_baglantisi():
    db = sqlite3.connect(KAZANC_DB, timeout=5)
    db.execute("PRAGMA busy_timeout=5000")
    try:
        yield db
        db.commit()
    finally:
        db.close()


def kazanc_veritabanini_hazirla() -> None:
    with db_baglantisi() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS kazanc_kayitlari (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tarih TEXT NOT NULL,
                hesap TEXT NOT NULL,
                islem TEXT NOT NULL,
                sonuc TEXT NOT NULL
            )
        """)
        sutunlar = {satir[1] for satir in db.execute("PRAGMA table_info(kazanc_kayitlari)")}
        if "lazer_mermisi_maliyeti" not in sutunlar:
            db.execute(
                "ALTER TABLE kazanc_kayitlari ADD COLUMN lazer_mermisi_maliyeti INTEGER NOT NULL DEFAULT 0"
            )
        if "enerji_maliyeti" not in sutunlar:
            db.execute(
                "ALTER TABLE kazanc_kayitlari ADD COLUMN enerji_maliyeti INTEGER NOT NULL DEFAULT 0"
            )
        db.execute("""
            CREATE TABLE IF NOT EXISTS telegram_hedefleri (
                chat_id TEXT NOT NULL,
                thread_id TEXT NOT NULL DEFAULT '',
                baslik TEXT NOT NULL DEFAULT '',
                aktif INTEGER NOT NULL DEFAULT 1,
                son_gorulme TEXT NOT NULL,
                PRIMARY KEY (chat_id, thread_id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS hatirlatmalar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hesap TEXT NOT NULL,
                tur TEXT NOT NULL,
                bildirim_zamani TEXT NOT NULL,
                gonderildi INTEGER NOT NULL DEFAULT 0
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS ayarlar (
                anahtar TEXT PRIMARY KEY,
                deger TEXT NOT NULL
            )
        """)
        db.execute("PRAGMA journal_mode=WAL")


def ayar_degeri(ad: str) -> str:
    deger = os.getenv(ad, "").strip()
    if deger:
        return deger
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as anahtar:
                return str(winreg.QueryValueEx(anahtar, ad)[0]).strip()
        except OSError:
            pass
    return ""


def telegram_hedeflerini_guncelle(token: str) -> None:
    """Bota yazılmış sohbetleri keşfedip kalıcı hedef listesine ekler."""
    kazanc_veritabanini_hazirla()
    with db_baglantisi() as db:
        satir = db.execute(
            "SELECT deger FROM ayarlar WHERE anahtar='telegram_offset'"
        ).fetchone()
        offset = int(satir[0]) if satir else 0
    try:
        with urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/getUpdates?timeout=0&limit=100&offset={offset}",
            timeout=5,
        ) as cevap:
            guncellemeler = json.load(cevap).get("result", [])
    except Exception as hata:
        print(f"Telegram hedefleri okunamadı: {hata}", flush=True)
        return
    with db_baglantisi() as db:
        for guncelleme in guncellemeler:
            mesaj = guncelleme.get("message") or guncelleme.get("channel_post") or {}
            uyelik = guncelleme.get("my_chat_member") or {}
            if not mesaj and uyelik:
                mesaj = uyelik
            sohbet = mesaj.get("chat", {}) if isinstance(mesaj, dict) else {}
            chat_id = sohbet.get("id")
            if chat_id is None:
                continue
            metin = str(mesaj.get("text") or "")
            yeni_durum = uyelik.get("new_chat_member", {}).get("status") if uyelik else None
            kaydedilebilir = metin.startswith("/start") or yeni_durum in {"member", "administrator"}
            if not kaydedilebilir:
                continue
            thread_id = str(mesaj.get("message_thread_id") or "") if sohbet.get("is_forum") else ""
            baslik = sohbet.get("title") or sohbet.get("username") or sohbet.get("first_name") or ""
            db.execute("""
                INSERT INTO telegram_hedefleri
                    (chat_id, thread_id, baslik, aktif, son_gorulme)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(chat_id, thread_id) DO UPDATE SET
                    baslik=excluded.baslik, aktif=1, son_gorulme=excluded.son_gorulme
            """, (str(chat_id), thread_id, baslik, datetime.now().isoformat(timespec="seconds")))
        if guncellemeler:
            yeni_offset = max(int(x["update_id"]) for x in guncellemeler) + 1
            db.execute("""
                INSERT INTO ayarlar(anahtar, deger) VALUES('telegram_offset', ?)
                ON CONFLICT(anahtar) DO UPDATE SET deger=excluded.deger
            """, (str(yeni_offset),))


def telegram_hedefleri(token: str) -> list[tuple[str, str]]:
    global _TELEGRAM_HEDEFLERI_OKUNDU
    if not _TELEGRAM_HEDEFLERI_OKUNDU:
        telegram_hedeflerini_guncelle(token)
        _TELEGRAM_HEDEFLERI_OKUNDU = True
    hedefler = set()
    sabit_chat = ayar_degeri(KAZANC_CHAT_ID_ENV)
    if sabit_chat:
        # Verilen t.me/c/... bağlantısındaki sayı forum konusu değildir.
        hedefler.add((sabit_chat, ""))
    kazanc_veritabanini_hazirla()
    with db_baglantisi() as db:
        hedefler.update(
            (str(chat_id), str(thread_id)) for chat_id, thread_id in db.execute(
                "SELECT chat_id, thread_id FROM telegram_hedefleri WHERE aktif = 1"
            )
        )
    return sorted(hedefler)


def telegrama_kazanc_gonder(
    mesaj: str, yalniz_uzay: bool = False, yalniz_uretim: bool = False
) -> bool:
    token = ayar_degeri(KAZANC_BOT_TOKEN_ENV)
    if not token:
        print("Telegram kazanç tokeni ayarlı değil; yalnız yerel kayıt yapıldı.", flush=True)
        return False
    if yalniz_uzay:
        hedefler = [(UZAY_TELEGRAM_CHAT_ID, UZAY_TELEGRAM_THREAD_ID)]
    elif yalniz_uretim:
        hedefler = [(URETIM_TELEGRAM_CHAT_ID, URETIM_TELEGRAM_THREAD_ID)]
    else:
        hedefler = [
            (chat_id, thread_id)
            for chat_id, thread_id in telegram_hedefleri(token)
            if chat_id != UZAY_TELEGRAM_CHAT_ID
        ]
    if not hedefler:
        print("Telegram hedefi yok; bota özelden veya gruptan /start yaz.", flush=True)
        return False
    mesaj = unicodedata.normalize("NFC", mesaj)
    basarili = False
    for chat_id, thread_id in hedefler:
        alanlar = {"chat_id": chat_id, "text": mesaj[:4000]}
        if thread_id:
            alanlar["message_thread_id"] = thread_id
        # Windows konsol kod sayfasından tamamen bağımsız taşı: Türkçe harfler
        # JSON içinde \uXXXX olur, Telegram bunları tekrar Unicode'a çevirir.
        veri = json.dumps(alanlar, ensure_ascii=True).encode("ascii")
        istek = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=veri,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(istek, timeout=10) as cevap:
                cevap.read()
            basarili = True
        except urllib.error.HTTPError as hata:
            ayrinti = hata.read().decode("utf-8", errors="replace")
            print(f"Telegram bildirimi {chat_id} hedefine gönderilemedi: {ayrinti}", flush=True)
            if hata.code == 400 and thread_id and "message thread not found" in ayrinti:
                print("Geçersiz Telegram konu kimliği kaldırılıp yeniden deneniyor.", flush=True)
                alanlar.pop("message_thread_id", None)
                tekrar_veri = json.dumps(alanlar, ensure_ascii=True).encode("ascii")
                tekrar_istek = urllib.request.Request(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    data=tekrar_veri,
                    headers={"Content-Type": "application/json; charset=utf-8"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(tekrar_istek, timeout=10) as cevap:
                        cevap.read()
                    basarili = True
                    with db_baglantisi() as db:
                        db.execute(
                            "UPDATE telegram_hedefleri SET aktif=0 WHERE chat_id=? AND thread_id=?",
                            (chat_id, thread_id),
                        )
                        db.execute("""
                            INSERT INTO telegram_hedefleri
                                (chat_id, thread_id, baslik, aktif, son_gorulme)
                            VALUES (?, '', '', 1, ?)
                            ON CONFLICT(chat_id, thread_id) DO UPDATE SET aktif=1
                        """, (chat_id, datetime.now().isoformat(timespec="seconds")))
                    continue
                except Exception as tekrar_hatasi:
                    print(f"Telegram konusuz tekrar gönderim başarısız: {tekrar_hatasi}", flush=True)
            if hata.code in (400, 403):
                with db_baglantisi() as db:
                    db.execute(
                        "UPDATE telegram_hedefleri SET aktif=0 WHERE chat_id=? AND thread_id=?",
                        (chat_id, thread_id),
                    )
        except Exception as hata:
            print(f"Telegram bildirimi {chat_id} hedefine gönderilemedi: {hata}", flush=True)
    return basarili


def uzay_kayit_metnini_sadelestir(metin: str) -> str:
    ganimetler = re.findall(
        r"([\d.]+)\s+adet\s+([A-Za-zÇĞİÖŞÜçğıöşü_-]+)", metin or "", re.IGNORECASE
    )
    xp = re.search(r"([\d.]+)\s*(?:Exp|XP)\b", metin or "", re.IGNORECASE)
    parcalar = [f"{miktar} adet {ad}" for miktar, ad in ganimetler]
    if xp:
        parcalar.append(f"{xp.group(1)} XP")
    if parcalar:
        return " | ".join(parcalar)
    if re.search(r"ödül\s+alamadınız|alt\s+edemediğiniz", metin or "", re.IGNORECASE):
        return "Korsan yenilemedi; ödül alınamadı."
    if enerji_bitti(metin):
        return "Yaşam enerjisi bitti."
    return " ".join((metin or "Sonuç metni okunamadı").split())[:300]


def kazanc_kayit_metnini_sadelestir(islem: str, metin: str) -> str:
    temiz = " ".join((metin or "Sonuç metni okunamadı").split())
    if islem.casefold().startswith("uzay farm"):
        return uzay_kayit_metnini_sadelestir(temiz)
    if islem in {"Eyalet madeni", "Eyalet fabrikası", "Eyalet sanayisi"}:
        maden = re.search(
            r"Maden\s+kazı\s+işleminde\s+([\d.]+)\s+adet\s+"
            r"([A-Za-zÇĞİÖŞÜçğıöşü_-]+)\s+elde\s+ettiniz",
            temiz,
            re.IGNORECASE,
        )
        if maden:
            return f"{maden.group(1)} adet {maden.group(2).upper()} elde edildi."
        uretim = re.search(
            r"([\d.]+)\s+adet\s+ürün\s+deponuza\s+aktarıldı",
            temiz,
            re.IGNORECASE,
        )
        if uretim:
            return f"{uretim.group(1)} adet ürün deponuza aktarıldı."
        if temiz.startswith("İşlem tamamlandı. Yeni durum:"):
            return temiz[:300]
        if "Ticarion line" in temiz or "Varlıklarım" in temiz:
            return "Sonuç doğrulanamadı (eski kayıt)."
    return temiz[:300]


def kazanc_kaydet(
    hesap,
    islem: str,
    sonuc: str,
    lazer_mermisi_maliyeti: int = 0,
    enerji_maliyeti: int = 0,
) -> int:
    temiz = kazanc_kayit_metnini_sadelestir(islem, sonuc)
    tarih = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ad = hesap_adi(hesap)
    kazanc_veritabanini_hazirla()
    with db_baglantisi() as db:
        imlec = db.execute(
            "INSERT INTO kazanc_kayitlari "
            "(tarih, hesap, islem, sonuc, lazer_mermisi_maliyeti, enerji_maliyeti) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tarih, ad, islem, temiz, lazer_mermisi_maliyeti, enerji_maliyeti),
        )
        kayit_id = int(imlec.lastrowid)
    kayit = {
        "tarih": tarih,
        "hesap": ad,
        "islem": islem,
        "sonuc": temiz,
        "kayit_id": kayit_id,
    }
    if lazer_mermisi_maliyeti:
        kayit["lazer_mermisi_maliyeti"] = lazer_mermisi_maliyeti
    if enerji_maliyeti:
        kayit["enerji_maliyeti"] = enerji_maliyeti
    with KAZANC_LOG.open("a", encoding="utf-8") as dosya:
        dosya.write(json.dumps(kayit, ensure_ascii=False) + "\n")
    if islem == "Uzay Farmı":
        uzay_kazancini_telegrama_gonder(hesap, temiz)
    elif islem in {"Eyalet madeni", "Eyalet fabrikası", "Eyalet sanayisi"}:
        uretim_kazancini_telegrama_gonder(hesap, islem, temiz)
    return kayit_id


def uzay_kaydi_mermi_maliyetini_guncelle(kayit_id: int, maliyet: int) -> None:
    """Bir farmın gerçek maliyetini iki stok ölçümü arasındaki farkla kaydeder."""
    if kayit_id <= 0 or maliyet <= 0:
        return
    with db_baglantisi() as db:
        db.execute(
            "UPDATE kazanc_kayitlari SET lazer_mermisi_maliyeti=? WHERE id=?",
            (maliyet, kayit_id),
        )
    if KAZANC_LOG.exists():
        yeni_satirlar = []
        for satir in KAZANC_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                kayit = json.loads(satir)
            except json.JSONDecodeError:
                yeni_satirlar.append(satir)
                continue
            if kayit.get("kayit_id") == kayit_id:
                kayit["lazer_mermisi_maliyeti"] = maliyet
            yeni_satirlar.append(json.dumps(kayit, ensure_ascii=False))
        KAZANC_LOG.write_text("\n".join(yeni_satirlar) + "\n", encoding="utf-8")


def eski_uzay_kayitlarini_sadelestir() -> tuple[int, int]:
    """Eski uzun uzay kayıtlarını DB ve JSONL içinde kısa biçime dönüştürür."""
    kazanc_veritabanini_hazirla()
    db_degisen = 0
    with db_baglantisi() as db:
        satirlar = db.execute(
            "SELECT id, sonuc FROM kazanc_kayitlari WHERE islem LIKE 'Uzay Farm%'"
        ).fetchall()
        for kayit_id, sonuc in satirlar:
            sade = uzay_kayit_metnini_sadelestir(sonuc)
            if sade != sonuc:
                db.execute(
                    "UPDATE kazanc_kayitlari SET sonuc=? WHERE id=?", (sade, kayit_id)
                )
                db_degisen += 1

    log_degisen = 0
    if KAZANC_LOG.exists():
        yeni_satirlar = []
        for satir in KAZANC_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                kayit = json.loads(satir)
            except json.JSONDecodeError:
                yeni_satirlar.append(satir)
                continue
            if str(kayit.get("islem", "")).casefold().startswith("uzay farm"):
                sade = uzay_kayit_metnini_sadelestir(str(kayit.get("sonuc", "")))
                if sade != kayit.get("sonuc"):
                    kayit["sonuc"] = sade
                    log_degisen += 1
            yeni_satirlar.append(json.dumps(kayit, ensure_ascii=False))
        KAZANC_LOG.write_text("\n".join(yeni_satirlar) + "\n", encoding="utf-8")
    return db_degisen, log_degisen


def tum_kazanc_kayitlarini_duzenle() -> tuple[int, int]:
    """DB'yi normalize eder ve JSONL dosyasını DB'den birebir yeniden üretir."""
    kazanc_veritabanini_hazirla()
    degisen = 0
    with db_baglantisi() as db:
        satirlar = db.execute(
            "SELECT id, islem, sonuc FROM kazanc_kayitlari ORDER BY id"
        ).fetchall()
        for kayit_id, islem, sonuc in satirlar:
            yeni_islem = "Uzay Farmı" if islem.casefold().startswith("uzay farm") else islem
            yeni_sonuc = kazanc_kayit_metnini_sadelestir(yeni_islem, sonuc)
            if yeni_islem != islem or yeni_sonuc != sonuc:
                db.execute(
                    "UPDATE kazanc_kayitlari SET islem=?, sonuc=? WHERE id=?",
                    (yeni_islem, yeni_sonuc, kayit_id),
                )
                degisen += 1
        temiz_satirlar = db.execute(
            "SELECT id, tarih, hesap, islem, sonuc, "
            "lazer_mermisi_maliyeti, enerji_maliyeti "
            "FROM kazanc_kayitlari ORDER BY id"
        ).fetchall()

    json_satirlari = []
    for kayit_id, tarih, hesap, islem, sonuc, mermi, enerji in temiz_satirlar:
        kayit = {
            "tarih": tarih,
            "hesap": hesap,
            "islem": islem,
            "sonuc": sonuc,
            "kayit_id": kayit_id,
        }
        if mermi:
            kayit["lazer_mermisi_maliyeti"] = mermi
        if enerji:
            kayit["enerji_maliyeti"] = enerji
        json_satirlari.append(json.dumps(kayit, ensure_ascii=False))
    KAZANC_LOG.write_text("\n".join(json_satirlari) + "\n", encoding="utf-8")
    return degisen, len(json_satirlari)


def sayiyi_ayikla(deger: str) -> int:
    return int(re.sub(r"\D", "", deger or "0") or "0")


def kazanc_kalemlerini_ayikla(metin: str) -> dict[str, int]:
    """Kayıt metnindeki malzeme/uzay taşı ve XP miktarlarını çıkarır."""
    kalemler: dict[str, int] = {}
    for miktar, kaynak in re.findall(
        r"([\d.,]+)\s+adet\s+([A-Za-zÇĞİÖŞÜçğıöşü_-]+)", metin, re.IGNORECASE
    ):
        ad = kaynak.casefold()
        kalemler[ad] = kalemler.get(ad, 0) + sayiyi_ayikla(miktar)

    uretim = re.search(
        r"([\d.,]+)\s+adet\s+([A-Za-zÇĞİÖŞÜçğıöşü_-]+)\s+elde ettiniz",
        metin,
        re.IGNORECASE,
    )
    # Yukarıdaki genel "adet" deseni üretimi zaten ekledi. "adet" yazmayan eski
    # üretim kayıtları için ikinci biçimi de destekle.
    if not uretim:
        eski = re.search(
            r"([\d.,]+)\s+(KERESTE|DEMİR|ÇELİK|PLASTİK|PETROL|TAŞ|CAM)\s+elde ettiniz",
            metin,
            re.IGNORECASE,
        )
        if eski:
            ad = eski.group(2).casefold()
            kalemler[ad] = kalemler.get(ad, 0) + sayiyi_ayikla(eski.group(1))

    xp = re.search(r"([\d.,]+)\s*(?:Exp|XP)\b", metin, re.IGNORECASE)
    if xp:
        kalemler["xp"] = kalemler.get("xp", 0) + sayiyi_ayikla(xp.group(1))
    return kalemler


def kazanc_raporunu_yazdir() -> None:
    """Tüm geçmiş kazançları hesap ve kaynak bazında konsola listeler."""
    kazanc_veritabanini_hazirla()
    with db_baglantisi() as db:
        kayitlar = db.execute(
            "SELECT hesap, islem, sonuc, lazer_mermisi_maliyeti, enerji_maliyeti "
            "FROM kazanc_kayitlari ORDER BY id"
        ).fetchall()

    rapor: dict[str, dict] = {}
    for hesap, islem, sonuc, mermi_maliyeti, enerji_maliyeti in kayitlar:
        hesap_raporu = rapor.setdefault(
            hesap,
            {"kayit": 0, "islemler": {}, "kalemler": {}, "mermi": 0, "enerji": 0, "saldiri": 0},
        )
        hesap_raporu["kayit"] += 1
        if islem.casefold().startswith("uzay farm"):
            islem = "Uzay Farmı"
        hesap_raporu["islemler"][islem] = hesap_raporu["islemler"].get(islem, 0) + 1
        for ad, miktar in kazanc_kalemlerini_ayikla(sonuc).items():
            hesap_raporu["kalemler"][ad] = hesap_raporu["kalemler"].get(ad, 0) + miktar
        if mermi_maliyeti or enerji_maliyeti:
            hesap_raporu["saldiri"] += 1
            hesap_raporu["mermi"] += mermi_maliyeti
            hesap_raporu["enerji"] += enerji_maliyeti

    print("\n📊 TOPLAM KAZANÇ RAPORU", flush=True)
    print("═" * 34, flush=True)
    if not rapor:
        print("Henüz kazanç kaydı yok.", flush=True)
        return
    print(f"👥 {len(rapor)} hesap  •  🧾 {len(kayitlar)} toplam kayıt", flush=True)

    uzay_kalemleri = {"aurorium", "photonium", "voidium", "carbon", "xp"}
    gorunen_adlar = {
        "xp": "XP",
        "demir": "Demir",
        "mermi": "Mermi",
        "urun": "Ürün",
        "kereste": "Kereste",
        "anakart": "Anakart",
        "belge": "Belge",
        "motor": "Motor",
        "aurorium": "Aurorium",
        "photonium": "Photonium",
        "voidium": "Voidium",
        "carbon": "Carbon",
    }

    def kalem_anahtari(ad: str) -> str:
        sade = unicodedata.normalize("NFKD", ad)
        return "".join(k for k in sade if not unicodedata.combining(k)).casefold()

    def bolum_yaz(baslik: str, simge: str, kalemler: list[tuple[str, int]]) -> None:
        if not kalemler:
            return
        print(f"  {simge} {baslik}", flush=True)
        for ad, miktar in sorted(kalemler):
            gorunen = gorunen_adlar.get(ad, ad.title())
            sayi = f"{miktar:,}".replace(",", ".")
            print(f"     {gorunen:<14} {sayi:>12}", flush=True)

    for hesap, bilgi in rapor.items():
        print(f"\n👤 {hesap}", flush=True)
        print("─" * 34, flush=True)
        if bilgi["kalemler"]:
            normalize = {}
            for ad, miktar in bilgi["kalemler"].items():
                anahtar = kalem_anahtari(ad)
                normalize[anahtar] = normalize.get(anahtar, 0) + miktar
            uzay = [(ad, miktar) for ad, miktar in normalize.items() if ad in uzay_kalemleri]
            uretim = [(ad, miktar) for ad, miktar in normalize.items() if ad not in uzay_kalemleri]
            bolum_yaz("Uzay ganimetleri", "🚀", uzay)
            bolum_yaz("Üretim kazançları", "🏭", uretim)
        else:
            print("  Sayısal kazanç bulunamadı.", flush=True)
        if bilgi["saldiri"]:
            mermi_metni = f"{bilgi['mermi']:,}".replace(",", ".")
            print("  💸 Uzay farm maliyeti", flush=True)
            print(f"     Başarılı saldırı {bilgi['saldiri']:>12}", flush=True)
            print(f"     Lazer Mermisi    {mermi_metni:>12}", flush=True)
            if bilgi["enerji"]:
                print(f"     Yaşam Enerjisi   {bilgi['enerji']:>12}", flush=True)
        islem_ozeti = ", ".join(f"{ad}: {adet}" for ad, adet in bilgi["islemler"].items())
        print(f"  🧾 {bilgi['kayit']} kayıt  •  {islem_ozeti}", flush=True)


def uzay_kazancini_ayikla(metin: str) -> tuple[str, str, str] | None:
    """Uzay sonucundan yalnız taş adedi/adı ve XP miktarını ayıklar."""
    tas = re.search(
        r"([\d.]+)\s+adet\s+([A-Za-zÇĞİÖŞÜçğıöşü_-]+)", metin, re.IGNORECASE
    )
    xp = re.search(r"([\d.]+)\s*(?:Exp|XP)\b", metin, re.IGNORECASE)
    if not tas or not xp:
        return None
    return tas.group(1), tas.group(2), xp.group(1)


def uzay_ganimetlerini_ayikla(metin: str) -> tuple[list[tuple[str, str]], str | None]:
    ganimetler = re.findall(
        r"([\d.]+)\s+adet\s+([A-Za-zÇĞİÖŞÜçğıöşü_-]+)", metin, re.IGNORECASE
    )
    xp = re.search(r"([\d.]+)\s*(?:Exp|XP)\b", metin, re.IGNORECASE)
    return ganimetler, xp.group(1) if xp else None


def uzay_sonuc_ozeti(metin: str) -> str:
    """Para, elmas ve menü metinlerini göstermeden gerçek farm sonucunu özetler."""
    ganimetler, xp = uzay_ganimetlerini_ayikla(metin)
    parcalar = [f"{miktar} {ad}" for miktar, ad in ganimetler]
    if xp:
        parcalar.append(f"{xp} XP")
    if parcalar:
        return " + ".join(parcalar)
    if re.search(r"ödül\s+alamadınız|alt\s+edemediğiniz", metin or "", re.IGNORECASE):
        return "Korsan yenilemedi; ödül alınamadı."
    if enerji_bitti(metin):
        return "Yaşam enerjisi yetersiz."
    temiz = " ".join((metin or "").split())
    for baslangic in ("İşlem Başarılı", "Tebrikler", "Yaşam enerjisi"):
        konum = temiz.casefold().find(baslangic.casefold())
        if konum >= 0:
            temiz = temiz[konum:]
            break
    temiz = re.split(r"\s+(?:TAMAM|ANASAYFA|MUHASEBE)\b", temiz, maxsplit=1)[0]
    return temiz[:220] or "Sonuç bilgisi alınamadı."


def uzay_kazancini_telegrama_gonder(hesap, sonuc: str) -> bool:
    ganimetler, xp = uzay_ganimetlerini_ayikla(sonuc)
    if not ganimetler and not xp:
        return False
    ganimet_satirlari = "\n".join(
        f"  • {miktar} {ad.title()}" for miktar, ad in ganimetler
    ) or "  • Ganimet yok"
    return telegrama_kazanc_gonder(
        "🚀 UZAY FARM SONUCU\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👤 {hesap_adi(hesap)}\n\n"
        f"📦 Kazançlar\n{ganimet_satirlari}\n"
        f"⭐ Deneyim: {xp or '0'} XP\n"
        f"🕒 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        yalniz_uzay=True,
    )


def uretim_kazancini_telegrama_gonder(hesap, islem: str, sonuc: str) -> bool:
    kazanc = re.search(
        r"([\d.]+)\s+adet\s+([A-Za-zÇĞİÖŞÜçğıöşü_-]+)", sonuc, re.IGNORECASE
    )
    if not kazanc:
        return False
    miktar, urun = kazanc.groups()
    if islem == "Eyalet fabrikası" and urun.casefold() == "ürün":
        urun = "Fabrika ürünü"
    elif islem == "Eyalet sanayisi" and urun.casefold() == "ürün":
        urun = "Sanayi parçası"
    simge = {
        "Eyalet madeni": "⛏️",
        "Eyalet fabrikası": "🏭",
        "Eyalet sanayisi": "⚙️",
    }[islem]
    return telegrama_kazanc_gonder(
        f"{simge} {hesap_adi(hesap)}\n"
        f"📦 {miktar} {urun.title()}",
        yalniz_uretim=True,
    )


def pencereyi_bul(baslik: str) -> int | None:
    if not IS_WINDOWS:
        return None
    bulunan: list[int] = []
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def kontrol(hwnd: int, _lparam: int) -> bool:
        uzunluk = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        metin = ctypes.create_unicode_buffer(uzunluk + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, metin, uzunluk + 1)
        if metin.value == baslik:
            bulunan.append(hwnd)
            return False
        return True

    ctypes.windll.user32.EnumWindows(enum_proc(kontrol), 0)
    return bulunan[0] if bulunan else None


def pencereyi_bekle(saniye: int = 90) -> int:
    if not IS_WINDOWS:
        time.sleep(min(5, saniye))
        return 0
    bitis = time.time() + saniye
    while time.time() < bitis:
        hwnd = pencereyi_bul(WINDOW_TITLE)
        if hwnd:
            return hwnd
        time.sleep(1)
    raise TimeoutError(f"{WINDOW_TITLE} penceresi açılamadı.")


def tam_ekran_yap(hwnd: int) -> None:
    if not IS_WINDOWS:
        return
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    time.sleep(1)

    # BlueStacks tamamen hazır olduktan sonra gerçek klavye F11 girdisi gönder.
    user32.keybd_event(VK_F11, 0, 0, 0)
    time.sleep(0.1)
    user32.keybd_event(VK_F11, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(2)


def tam_ekranda_mi(hwnd: int) -> bool:
    if not IS_WINDOWS:
        return True
    user32 = ctypes.windll.user32
    alan = wintypes.RECT()
    sol_ust = wintypes.POINT(0, 0)
    sag_alt = wintypes.POINT()
    user32.GetClientRect(hwnd, ctypes.byref(alan))
    sag_alt.x, sag_alt.y = alan.right, alan.bottom
    user32.ClientToScreen(hwnd, ctypes.byref(sol_ust))
    user32.ClientToScreen(hwnd, ctypes.byref(sag_alt))
    return (
        sol_ust.x == 0
        and sol_ust.y == 0
        and sag_alt.x == user32.GetSystemMetrics(0)
        and sag_alt.y == user32.GetSystemMetrics(1)
    )


def tam_ekrani_garantile() -> None:
    if not IS_WINDOWS:
        print("Windows dışı sistem: pencere öne alma/tam ekran adımı atlandı.", flush=True)
        return
    hwnd = pencereyi_bul(WINDOW_TITLE)
    if not hwnd:
        raise RuntimeError("BlueStacks penceresi bulunamadı.")
    if not tam_ekranda_mi(hwnd):
        tam_ekran_yap(hwnd)
    else:
        user32 = ctypes.windll.user32
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)


def giris_yap(dom: ChromeDOM, hesap) -> None:
    oyun_adi = hesap.oyun_adi or HESAP_OYUN_ADLARI.get(hesap.kullanici_adi) or hesap.kullanici_adi
    print(f"Şu hesaba giriliyor: {oyun_adi}", flush=True)

    dom.adrese_git("https://www.ticariononline.com/tr/girisyap.php")
    dom.secici_bekle('input[name="mail"]')
    dom.yaz('input[name="mail"]', hesap.kullanici_adi)
    dom.yaz('input[name="tpass"]', hesap.sifre)
    time.sleep(ISLEM_BEKLEME)
    reklam_dugmesine_bas(dom)
    print("Giriş düğmesine basıldı; doğrulama adımı bekleniyor.", flush=True)


def reklam_dugmesine_bas(dom: ChromeDOM, deneme_sayisi: int = 3) -> None:
    """Reklam İzle düğmesine geçici DOM hatalarında yeniden deneyerek basar."""
    son_hata: Exception | None = None
    for deneme in range(1, deneme_sayisi + 1):
        try:
            dom.tikla("#reklamIzleBtn")
            print("✓ Reklam İzle düğmesine basıldı.", flush=True)
            return
        except (OSError, RuntimeError, TimeoutError) as hata:
            son_hata = hata
            if deneme < deneme_sayisi:
                print(
                    f"⚠ Reklam İzle düğmesi tıklanamadı ({deneme}/{deneme_sayisi}); "
                    "tekrar deneniyor.",
                    flush=True,
                )
                time.sleep(1)
    raise RuntimeError(
        f"Reklam İzle düğmesi {deneme_sayisi} denemede tıklanamadı: {son_hata}"
    )


def giris_yap_ve_dogrula(dom: ChromeDOM, hesap) -> None:
    son_hata: Exception | None = None
    for deneme in range(1, GIRIS_DENEME_SINIRI + 1):
        try:
            print(f"Giriş denemesi {deneme}/{GIRIS_DENEME_SINIRI}", flush=True)
            giris_yap(dom, hesap)
            noname_calistir_ve_bekle(dom, hesap, giris_dogrulamasi=True)
            return
        except DogrulamaYardimcisiHatasi:
            # ADB/yardımcı süreç hatası aynı girişte tekrar deneyerek düzelmez.
            raise
        except (RuntimeError, TimeoutError) as hata:
            son_hata = hata
            print(f"Giriş doğrulanamadı: {hata}. Yeniden deneniyor...", flush=True)
            try:
                dom.adrese_git(BASLANGIC_SAYFASI_URL)
                dom.url_bekle("girisyap.php", saniye=15)
                dom.secici_bekle('input[name="mail"]', saniye=15)
            except (RuntimeError, TimeoutError, OSError) as toparlama_hatasi:
                print(f"Chrome giriş sayfası toparlanıyor: {toparlama_hatasi}", flush=True)
                dom.baglan()
                dom.adrese_git(BASLANGIC_SAYFASI_URL)
                dom.url_bekle("girisyap.php", saniye=20)
                dom.secici_bekle('input[name="mail"]', saniye=20)
            time.sleep(ISLEM_BEKLEME)
    raise RuntimeError(
        f"Giriş {GIRIS_DENEME_SINIRI} denemede doğrulanamadı: {son_hata}"
    )


def cikis_yap(dom: ChromeDOM, hesap) -> None:
    oyun_adi = hesap.oyun_adi or HESAP_OYUN_ADLARI.get(hesap.kullanici_adi) or hesap.kullanici_adi
    tiklandi = dom.calistir("""
        (() => {
            const baglantilar = [...document.querySelectorAll('a')];
            const cikis = baglantilar.find(a => {
                const yazi = (a.textContent || '').toLocaleUpperCase('tr-TR');
                const adres = (a.getAttribute('href') || '').toLocaleLowerCase('tr-TR');
                return yazi.includes('ÇIKIŞ') || adres.includes('cikis');
            });
            if (!cikis) return false;
            cikis.click();
            return true;
        })()
    """)
    if not tiklandi:
        # Hata/geri dönüş sayfalarında alt menü bulunmayabilir. Doğrudan oyunun
        # kendi çıkış uç noktasına gitmek hesap döngüsünü güvenle sürdürür.
        print("Çıkış bağlantısı bu sayfada yok; güvenli çıkış adresi kullanılıyor.", flush=True)
        dom.adrese_git("https://www.ticariononline.com/tr/kapat.php")
    adres = dom.yeni_sayfa_bekle(
        ["geridoninfo.php", "girisyap.php", "index.php", "kapat.php"], saniye=60
    )
    if "geridoninfo.php" in adres:
        mesaj = dom.calistir("document.body?.innerText || ''", "geridoninfo.php") or ""
        print(f"Çıkış bilgisi: {' '.join(mesaj.split())}", flush=True)
    dom.adrese_git("https://www.ticariononline.com/tr/girisyap.php")
    dom.url_bekle("girisyap.php")
    dom.secici_bekle('input[name="mail"]')
    print(f"Hesaptan çıkıldı: {oyun_adi}", flush=True)


def guvenli_cikis_yap(dom: ChromeDOM, hesap) -> None:
    try:
        cikis_yap(dom, hesap)
    except Exception as hata:
        print(f"Normal çıkış başarısız, doğrudan çıkış deneniyor: {hata}", flush=True)
        dom.adrese_git("https://www.ticariononline.com/tr/kapat.php")
        try:
            dom.url_bekle("kapat.php", saniye=15)
        except TimeoutError:
            pass
        dom.adrese_git(BASLANGIC_SAYFASI_URL)
        dom.url_bekle("girisyap.php", saniye=30)
        dom.secici_bekle('input[name="mail"]')


def oturumu_sifirla(dom: ChromeDOM) -> None:
    """Başarısız giriş/CAPTCHA sonrasında sıradaki hesap için temiz giriş açar."""
    try:
        dom.adrese_git("https://www.ticariononline.com/tr/kapat.php")
        time.sleep(1)
        dom.adrese_git(BASLANGIC_SAYFASI_URL)
        dom.url_bekle("girisyap.php", saniye=10)
        dom.secici_bekle('input[name="mail"]', saniye=10)
    except (RuntimeError, TimeoutError, OSError) as hata:
        print(f"Oturum sıfırlanamadı: {hata}", flush=True)


def hesap_islemlerini_yap(dom: ChromeDOM, hesap) -> bool:
    oyun_adi = hesap.oyun_adi or HESAP_OYUN_ADLARI.get(hesap.kullanici_adi) or hesap.kullanici_adi
    print(f"Hesap işlemleri başlayacak: {oyun_adi}", flush=True)
    islemler = [
        ("Eyalet madeni", MADEN_REZERVI_URL),
        ("Eyalet fabrikası", EYALET_FABRIKASI_URL),
        ("Eyalet sanayisi", EYALET_SANAYISI_URL),
    ]
    for ad, adres in islemler:
        try:
            uretim_islemini_yap(dom, hesap, ad, adres)
        except Exception as hata:
            print(f"{ad} hatası; diğer işleme geçiliyor: {hata}", flush=True)
    try:
        maden_egitimini_yap(dom, hesap)
    except Exception as hata:
        print(f"Maden eğitimi hatası; devam ediliyor: {hata}", flush=True)
    try:
        konsey_tahsilatini_yap(dom)
    except Exception as hata:
        print(f"Konsey tahsilatı hatası; devam ediliyor: {hata}", flush=True)
    try:
        ana_sayfa_reklamini_izle(dom, hesap)
    except Exception as hata:
        print(f"Ana sayfa reklamı hatası; hesap işlemleri tamamlanıyor: {hata}", flush=True)
    return True


def yasam_enerjisini_oku(dom: ChromeDOM) -> int:
    """Uzay gemisi sayfasındaki mevcut yaşam enerjisini sayısal olarak döndürür."""
    dom.adrese_git(UZAY_GEMISI_URL)
    dom.url_bekle("uzay-gemisi.php", saniye=20)
    metin = dom.calistir("document.body ? document.body.innerText : ''", "uzay-gemisi.php") or ""
    sade = unicodedata.normalize("NFKD", metin.casefold())
    sade = "".join(karakter for karakter in sade if not unicodedata.combining(karakter))
    eslesme = re.search(r"yasam\s*enerjisi\s*:?\s*([\d.]+)", sade)
    if eslesme:
        return int(eslesme.group(1).replace(".", ""))
    if enerji_bitti(metin):
        return 0
    ozet = " ".join(metin.split())[:300]
    raise RuntimeError(f"Yaşam enerjisi uzay gemisi sayfasından okunamadı: {ozet}")


def korsan_enerji_maliyetini_ayikla(metin: str) -> int | None:
    sade = unicodedata.normalize("NFKD", (metin or "").casefold())
    sade = "".join(karakter for karakter in sade if not unicodedata.combining(karakter))
    for desen in (
        r"(\d+)\s*(?:yasam\s*)?enerji(?:si)?\s*(?:harcar|gerekir|maliyeti)?",
        r"(?:yasam\s*)?enerji(?:si)?\s*(?:maliyeti|harcar|gerekir|:)\s*(\d+)",
    ):
        eslesme = re.search(desen, sade)
        if eslesme:
            return int(eslesme.group(1))
    return None


def lazer_mermisi_bilgisini_ayikla(metin: str) -> tuple[int, int] | None:
    stok = re.search(r"Mevcut\s+Lazer\s+Mermisi\s*:\s*([\d.]+)", metin, re.IGNORECASE)
    maliyet = re.search(
        r"(?:tüm\s+saldırılarda|saldırı[^\n]*)\s*([\d.]+)\s+lazer\s+mermisi\s+harcanır",
        metin,
        re.IGNORECASE,
    )
    if not stok or not maliyet:
        return None
    return sayiyi_ayikla(stok.group(1)), sayiyi_ayikla(maliyet.group(1))


def uzay_gemisi_mermi_stogunu_oku(
    dom: ChromeDOM, deneme_sayisi: int = 5, bekleme: float = 5
) -> int:
    for deneme in range(1, deneme_sayisi + 1):
        try:
            kart = dom.calistir(
                "document.querySelector('[data-target=\"#exampleModalCenterLazerMermisi\"]')?.innerText || ''",
                "uzay-gemisi.php",
            ) or ""
            eslesme = re.search(
                r"Lazer\s+Mermisi\s*([\d.]+)\s*Adet", kart, re.IGNORECASE
            )
            if eslesme:
                return sayiyi_ayikla(eslesme.group(1))
        except (OSError, RuntimeError):
            pass
        if deneme < deneme_sayisi:
            print(
                f"⚠ Lazer Mermisi stoğu okunamadı ({deneme}/{deneme_sayisi}); "
                f"{bekleme:g} saniye sonra tekrar okunacak.",
                flush=True,
            )
            time.sleep(bekleme)
    raise LazerMermisiUretimHatasi(
        f"Lazer Mermisi stoğu {deneme_sayisi} denemede okunamadı."
    )


def lazer_mermisi_uret(dom: ChromeDOM, hesap) -> None:
    """Uzay gemisindeki lazer mermisi bölümünden 1.000.000 adet üretir."""
    dom.adrese_git(UZAY_GEMISI_URL)
    dom.url_bekle("uzay-gemisi.php", saniye=20)
    acildi = dom.calistir(r"""
        (() => {
            const adaylar = [...document.querySelectorAll('a, button, [data-target]')];
            const bolum = adaylar.find(e => /lazer\s*mermi/i.test(
                `${e.innerText || ''} ${e.title || ''} ${e.id || ''} ${e.className || ''}`
            ));
            if (!bolum) return false;
            bolum.click();
            return true;
        })()
    """, "uzay-gemisi.php")
    if not acildi:
        raise LazerMermisiUretimHatasi(
            "Uzay gemisinde Lazer Mermisi bölümü bulunamadı."
        )
    time.sleep(1)
    secildi = dom.calistir(r"""
        (() => {
            const adet = document.querySelector(
                '#exampleModalCenterLazerMermisi #adetInput, '
                + '#exampleModalCenterLazerMermisi input[name="adet"]'
            );
            const olustur = document.querySelector(
                '#exampleModalCenterLazerMermisi button[name="lazer_mermisi_olustur"]'
            );
            if (adet && olustur) {
                adet.value = '1000000';
                adet.dispatchEvent(new Event('input', {bubbles: true}));
                adet.dispatchEvent(new Event('change', {bubbles: true}));
                olustur.click();
                return true;
            }
            const milyon = /(?:1[.,]?000[.,]?000|1000000)/;
            const secenek = [...document.querySelectorAll('option')].find(e => milyon.test(
                `${e.innerText || ''} ${e.value || ''}`
            ));
            if (secenek) {
                secenek.selected = true;
                secenek.parentElement.dispatchEvent(new Event('change', {bubbles: true}));
            }
            const adaylar = [...document.querySelectorAll(
                'button, input[type="submit"], input[type="button"], a'
            )];
            const dugme = adaylar.find(e => milyon.test(
                `${e.innerText || ''} ${e.value || ''} ${e.name || ''} ${e.id || ''}`
            )) || (secenek && adaylar.find(e => /üret|uret|onayla/i.test(
                `${e.innerText || ''} ${e.value || ''}`
            )));
            if (!dugme) return false;
            dugme.click();
            return true;
        })()
    """, "uzay-gemisi.php")
    if not secildi:
        raise LazerMermisiUretimHatasi(
            "1.000.000 Lazer Mermisi üretim seçeneği bulunamadı."
        )
    try:
        noname_calistir_ve_bekle(dom, hesap, giris_dogrulamasi=False)
    except DogrulamaYardimcisiHatasi as hata:
        raise LazerMermisiUretimHatasi(str(hata)) from hata
    sonuc_metni = dom.calistir("document.body ? document.body.innerText : ''") or ""
    if "lazer mermisi oluşturuldu" not in sonuc_metni.casefold():
        raise LazerMermisiUretimHatasi(
            f"Üretim sonucu doğrulanamadı: {uzay_sonuc_ozeti(sonuc_metni)}"
        )
    print("✓ 1.000.000 Lazer Mermisi üretildi.", flush=True)


def lazer_mermisi_uretimini_dene(dom: ChromeDOM, hesap) -> None:
    """Her türlü üretim/DOM hatasını hesabı atlatacak belirgin hataya dönüştürür."""
    try:
        lazer_mermisi_uret(dom, hesap)
    except LazerMermisiUretimHatasi:
        raise
    except Exception as hata:
        raise LazerMermisiUretimHatasi(f"Üretim sırasında hata: {hata}") from hata


def uzay_normal_saldiri_yap(
    dom: ChromeDOM, hesap, mevcut_enerji: int | None = None
) -> bool:
    hedefler = ["Starclaw", "Piranax", "Bloodfang", "Shadowwing", "Revenant", "Voidbreaker"]
    aktif_uzay_savasini_kurtar(dom, hesap)
    dom.adrese_git(UZAY_GEMISI_URL)
    dom.url_bekle("uzay-gemisi.php")
    lazer_gorseli = dom.calistir("""
        document.querySelector(
            'a[data-target="#exampleModalCenterLazer"] img'
        )?.getAttribute('src') || ''
    """, "uzay-gemisi.php")
    seviye_eslesmesi = re.search(r"lazersilahlari/(\d+)\.png", lazer_gorseli)
    if not seviye_eslesmesi:
        print("Uzay saldırıları atlandı: lazer silahı seviyesi okunamadı.", flush=True)
        return
    lazer_seviyesi = int(seviye_eslesmesi.group(1))
    if lazer_seviyesi < 1:
        print("Uzay saldırıları atlandı: lazer seviyesi geçersiz.", flush=True)
        return
    hedef = hedefler[min(lazer_seviyesi, len(hedefler)) - 1]
    gemi_mermi_stogu = uzay_gemisi_mermi_stogunu_oku(dom)
    print(f"Lazer Mermisi stoğu: {gemi_mermi_stogu:,}".replace(",", "."), flush=True)
    if gemi_mermi_stogu < LAZER_MERMISI_ALT_SINIR:
        print(
            f"⚠ Stok {LAZER_MERMISI_ALT_SINIR:,} sınırının altında; farm açılmadan üretilecek."
            .replace(",", "."),
            flush=True,
        )
        lazer_mermisi_uretimini_dene(dom, hesap)
        return True
    adres, metin, enerji_maliyeti = uzay_farm_oturumu_ac(dom, hesap, hedef, mevcut_enerji)
    if "uzayfarm.php" not in adres:
        ozet = uzay_sonuc_ozeti(metin)
        if enerji_bitti(metin):
            kazanc_kaydet(hesap, "Uzay Farmı", "Yaşam enerjisi bitti; farm iptal edildi.")
        print(
            f"Uzay saldırıları durdu: Lazer S{lazer_seviyesi} yalnız {hedef} "
            f"hedefini kullanır. Sonuç: {ozet}",
            flush=True,
        )
        return not enerji_bitti(metin)
    mermi_bilgisi = lazer_mermisi_bilgisini_ayikla(metin)
    if mermi_bilgisi is None:
        raise LazerMermisiUretimHatasi(
            "Lazer Mermisi stoğu okunamadı; güvenlik için farm başlatılmadı."
        )
    mermi_stogu, saldiri_mermi_maliyeti = mermi_bilgisi or (None, None)
    if mermi_stogu is not None:
        print(
            f"Lazer Mermisi: {mermi_stogu:,} • Saldırı maliyeti: {saldiri_mermi_maliyeti:,}"
            .replace(",", "."),
            flush=True,
        )
    if mermi_stogu < LAZER_MERMISI_ALT_SINIR:
        print(
            f"⚠ Lazer Mermisi yalnızca {mermi_stogu:,}; farmdan önce üretim yapılacak."
            .replace(",", "."),
            flush=True,
        )
        lazer_mermisi_uretimini_dene(dom, hesap)
        return True
    print(f"Lazer S{lazer_seviyesi} hedefi: {hedef}", flush=True)
    print(f"Uzay saldırısı: {hedef}", flush=True)
    if not uzay_saldirisini_baslat_ve_dogrula(dom, mermi_stogu):
        if not aktif_uzay_savasini_kurtar(dom, hesap):
            print("Uzay saldırıları durdu: 500 Milyon seçimi başlatılamadı.", flush=True)
            return True
        return True
    savas_takibi = {"son_stok": mermi_stogu}
    threading.Thread(
        target=uzay_savasini_sure_boyunca_guclendir,
        args=(dom, savas_takibi),
        daemon=True,
    ).start()
    try:
        sonuc_adresi = dom.yeni_sayfa_bekle(
            ["geridononay.php", "geridoninfo.php"], saniye=65
        )
    except TimeoutError:
        print("Savaş sonucu gecikti; aktif savaş kurtarma modu çalışıyor.", flush=True)
        aktif_uzay_savasini_kurtar(dom, hesap)
        return True
    sonuc = dom.calistir("document.body?.innerText || ''")
    print(f"✓ Saldırı tamamlandı: {uzay_sonuc_ozeti(sonuc)}", flush=True)
    kayit_id = kazanc_kaydet(
        hesap,
        "Uzay Farmı",
        sonuc,
        enerji_maliyeti=enerji_maliyeti or 0,
    )
    if "geridononay.php" in sonuc_adresi:
        dom.calistir("document.querySelector('.swal2-confirm')?.click(); true")
    yeni_stok = int(savas_takibi.get("son_stok", mermi_stogu))
    gercek_maliyet = max(0, mermi_stogu - yeni_stok)
    if gercek_maliyet:
        uzay_kaydi_mermi_maliyetini_guncelle(kayit_id, gercek_maliyet)
    print(
        f"Farm maliyeti: {gercek_maliyet:,} • Kalan Lazer Mermisi: {yeni_stok:,}"
        .replace(",", "."),
        flush=True,
    )
    if yeni_stok < LAZER_MERMISI_ALT_SINIR:
        print("⚠ Stok sınırın altında; sonraki farmdan önce üretim yapılıyor.", flush=True)
        lazer_mermisi_uretimini_dene(dom, hesap)
    return True


def aktif_uzay_savasini_kurtar(dom: ChromeDOM, hesap=None) -> bool:
    dom.adrese_git(UZAY_SAVAS_URL)
    try:
        dom.url_bekle("uzayfarm.php", saniye=3)
    except TimeoutError:
        return False
    aktif = dom.calistir(
        "Boolean(document.querySelector('#saldirform') && document.querySelector('#countdown'))",
        "uzayfarm.php",
    )
    if not aktif:
        return False
    print("Yarım kalan uzay savaşı bulundu; enerji korunarak tamamlanıyor.", flush=True)
    aktif_metin = dom.calistir("document.body?.innerText || ''", "uzayfarm.php") or ""
    aktif_mermi_bilgisi = lazer_mermisi_bilgisini_ayikla(aktif_metin)
    aktif_mermi = aktif_mermi_bilgisi[0] if aktif_mermi_bilgisi else None
    if not uzay_saldirisini_baslat_ve_dogrula(dom, aktif_mermi):
        return False
    threading.Thread(
        target=uzay_savasini_sure_boyunca_guclendir,
        args=(dom,),
        daemon=True,
    ).start()
    try:
        sonuc_adresi = dom.yeni_sayfa_bekle(["geridononay.php", "geridoninfo.php"], saniye=65)
    except TimeoutError:
        return False
    sonuc = dom.calistir("document.body?.innerText || ''")
    print(f"✓ Yarım kalan savaş tamamlandı: {uzay_sonuc_ozeti(sonuc)}", flush=True)
    if hesap is not None:
        kazanc_kaydet(hesap, "Uzay Farmı", sonuc)
    if enerji_bitti(sonuc):
        return False
    if "geridononay.php" in sonuc_adresi:
        try:
            dom.calistir("document.querySelector('.swal2-confirm')?.click(); true")
        except RuntimeError:
            pass
    return True


def uzay_farm_oturumu_ac(
    dom: ChromeDOM, hesap, hedef: str, mevcut_enerji: int | None = None
) -> tuple[str, str, int | None]:
    modal_id = f"exampleModalCenter{hedef}"
    son_mesaj = "Savaş sayfası açılamadı"
    for deneme in range(1, GIRIS_DENEME_SINIRI + 1):
        try:
            dom.adrese_git(UZAY_FARM_URL)
            dom.url_bekle("uzay_farm_haritasi.php", saniye=15)
        except (RuntimeError, TimeoutError):
            # CAPTCHA/sonuç sayfası sekme odağını değiştirmiş olabilir.
            try:
                dom.adrese_git(UZAY_FARM_URL)
                dom.url_bekle("uzay_farm_haritasi.php", saniye=20)
            except (RuntimeError, TimeoutError):
                dom.baglan()
                dom.adrese_git(UZAY_FARM_URL)
                try:
                    dom.url_bekle("uzay_farm_haritasi.php", saniye=20)
                except TimeoutError:
                    son_mesaj = "Uzay farm haritasına dönülemedi"
                    print(f"{son_mesaj}; farm iptal ediliyor.", flush=True)
                    return "", son_mesaj, None
            if "uzay_farm_haritasi.php" not in dom.adres():
                son_mesaj = "Uzay farm haritasına dönülemedi"
                print(f"{son_mesaj}; farm iptal ediliyor.", flush=True)
                return "", son_mesaj, None
        tiklandi = False
        for _ in range(15):
            try:
                modal_metni = dom.calistir(
                    f"document.querySelector('#{modal_id}')?.innerText || ''",
                    "uzay_farm_haritasi.php",
                ) or ""
                enerji_maliyeti = korsan_enerji_maliyetini_ayikla(modal_metni)
                if mevcut_enerji is not None and enerji_maliyeti is not None:
                    print(
                        f"{hedef} enerji maliyeti: {enerji_maliyeti}; mevcut enerji: {mevcut_enerji}",
                        flush=True,
                    )
                    if mevcut_enerji < enerji_maliyeti:
                        return "", (
                            f"Yaşam enerjisi yetersiz: {hedef} için {enerji_maliyeti}, "
                            f"mevcut {mevcut_enerji}."
                        ), enerji_maliyeti
                tiklandi = bool(dom.calistir(f"""
                    (() => {{
                        const modal = document.querySelector('#{modal_id}');
                        const dugme = modal?.querySelector('button.pzStartBtn');
                        if (!dugme) return false;
                        dugme.click();
                        return true;
                    }})()
                """, "uzay_farm_haritasi.php"))
                if tiklandi:
                    break
            except RuntimeError:
                pass
            time.sleep(0.2)
        if not tiklandi:
            son_mesaj = f"{hedef} saldırı düğmesi bulunamadı"
            continue

        print(
            f"{hedef} farm açma denemesi {deneme}/{GIRIS_DENEME_SINIRI}",
            flush=True,
        )
        noname_calistir_ve_bekle(dom, hesap, giris_dogrulamasi=False)
        try:
            # Doğrulamanın yaptığı gerçek POST/yönlendirmeyi bekle. Burada
            # uzayfarm.php'ye zorla GET atmak savaş oturumunu bozuyordu.
            adres = dom.yeni_sayfa_bekle(
                ["uzayfarm.php", "geridon.php", "geridoninfo.php", "varliklar.php"], saniye=20
            )
        except TimeoutError:
            mevcut = dom.calistir("location.href") or ""
            if "uzayfarm.php" in mevcut:
                adres = mevcut
            else:
                son_mesaj = "Doğrulama sonrası savaş sayfası açılmadı"
                print(f"Uzay farm doğrulanamadı: {son_mesaj}.", flush=True)
                continue

        # uzayfarm.php bazen yalnız bir an görünüp Varlıklar'a yönlendiriliyor.
        # Yönlendirmenin oturması için kısa süre bekleyip gerçek adresi tekrar oku.
        time.sleep(1)
        adres = dom.adres()

        if "varliklar.php" in adres:
            print("Varlıklar sayfasına düşüldü; uzay farmına geri dönülüyor.", flush=True)
            dom.adrese_git(UZAY_SAVAS_URL)
            try:
                dom.url_bekle("uzayfarm.php", saniye=15)
                adres = dom.calistir("location.href") or UZAY_SAVAS_URL
            except TimeoutError:
                son_mesaj = "Varlıklar sayfasından uzay farmına dönülemedi"
                print(f"{son_mesaj}. Yeniden deneniyor...", flush=True)
                continue

        metin = ""
        for _ in range(20):
            try:
                metin = dom.calistir("document.body ? document.body.innerText : ''")
                if metin:
                    break
            except RuntimeError:
                pass
            time.sleep(0.2)
        if "Varlıklarım" in metin or "Hepsini Çalıştır" in metin:
            print("Varlıklar içeriği algılandı; aktif uzay savaşına geri dönülüyor.", flush=True)
            dom.adrese_git(UZAY_SAVAS_URL)
            try:
                dom.url_bekle("uzayfarm.php", saniye=15)
                time.sleep(0.5)
                adres = dom.adres()
                metin = dom.calistir("document.body ? document.body.innerText : ''") or ""
            except TimeoutError:
                son_mesaj = "Varlıklar içeriğinden uzay farmına dönülemedi"
                print(f"{son_mesaj}. Yeniden deneniyor...", flush=True)
                continue
        if enerji_bitti(metin):
            return adres, metin, enerji_maliyeti
        if "uzayfarm.php" in adres:
            aktif = dom.calistir("Boolean(document.querySelector('#saldirform'))")
            if aktif:
                return adres, metin, enerji_maliyeti
        son_mesaj = " ".join(metin.split())[:300] or "Aktif savaş formu bulunamadı"
        print(f"Uzay farm doğrulanamadı: {son_mesaj}. Yeniden deneniyor...", flush=True)
    return "", son_mesaj, None


def uzay_savasini_500m_ile_baslat(dom: ChromeDOM) -> bool:
    # Bazı farmlarda başlat düğmesi sayaç bitimine yaklaşana kadar pasif kalıyor.
    # Açılmış savaşı bırakmamak için bir dakika boyunca hazır olmasını bekle.
    bitis = time.time() + 60
    otuz_saniye_bildirildi = False
    dom_dugmesi_bulunamadi = 0
    while time.time() < bitis:
        try:
            durum = dom.calistir("""
                (() => {
                    const tamam = document.querySelector('.swal2-confirm');
                    if (tamam) tamam.click();
                    const form = document.querySelector('#saldirform');
                    const baslat = document.querySelector('#saldiriBaslat');
                    if (!form || !baslat) return null;

                    const sayac = document.querySelector('#countdown');
                    const yazi = (sayac?.innerText || sayac?.textContent || '').trim();
                    let kalan = null;
                    const parcalar = yazi.match(/\\d+/g)?.map(Number) || [];
                    if (parcalar.length >= 3) kalan = parcalar.at(-3) * 3600 + parcalar.at(-2) * 60 + parcalar.at(-1);
                    else if (parcalar.length === 2) kalan = parcalar[0] * 60 + parcalar[1];
                    else if (parcalar.length === 1) kalan = parcalar[0];

                    const secenekler = [...form.querySelectorAll('input[id^="atak"]')];
                    const elmasMi = e => {
                        const etiket = document.querySelector(`label[for="${e.id}"]`);
                        const metin = `${etiket?.innerText || ''} ${e.parentElement?.innerText || ''}`
                            .toLocaleLowerCase('tr-TR');
                        return metin.includes('elmas') || metin.includes('diamond');
                    };

                    if (kalan !== null && kalan < 30) {
                        secenekler.filter(e => !elmasMi(e)).forEach(e => {
                            if (!e.checked) e.click();
                            e.dispatchEvent(new Event('change', {bubbles: true}));
                        });
                    } else {
                        const secenek = document.querySelector('#atak3');
                        if (secenek && !secenek.checked) secenek.click();
                        if (secenek) secenek.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                    return {
                        kalan,
                        secili: secenekler.filter(e => e.checked).map(e => e.id),
                        hazir: !baslat.disabled
                    };
                })()
            """, "uzayfarm.php")
            if durum and durum.get("kalan") is not None and durum["kalan"] < 30 and not otuz_saniye_bildirildi:
                print(
                    "Sayaç 30 saniyenin altında; Elmas hariç tüm saldırı seçenekleri seçiliyor.",
                    flush=True,
                )
                otuz_saniye_bildirildi = True
            if durum and durum["secili"] and durum["hazir"]:
                return bool(dom.calistir("""
                    (() => {
                        const baslat = document.querySelector('#saldiriBaslat');
                        if (!baslat || baslat.disabled) return false;
                        baslat.click();
                        return true;
                    })()
                """, "uzayfarm.php"))
            if durum is None:
                dom_dugmesi_bulunamadi += 1
                if dom_dugmesi_bulunamadi >= 6:
                    print("Uzay tuşları DOM ile bulunamadı; ADB oto-clicker deneniyor.", flush=True)
                    return uzay_savasini_adb_tiklamayla_baslat(dom)
            else:
                dom_dugmesi_bulunamadi = 0
        except RuntimeError:
            pass
        time.sleep(0.5)
    print("Açık uzay farmı bir dakika beklenmesine rağmen başlatılamadı.", flush=True)
    return uzay_savasini_adb_tiklamayla_baslat(dom)


def uzay_saldirisi_basladi_mi(
    dom: ChromeDOM, onceki_mermi: int | None, saniye: float = 6
) -> bool:
    """Tıklamayı değil, otomatik ateşin gerçekten başladığını doğrular."""
    bitis = time.time() + saniye
    while time.time() < bitis:
        try:
            durum = dom.calistir(r"""
                (() => {
                    const metin = document.body?.innerText || '';
                    const stok = metin.match(/Mevcut\s+Lazer\s+Mermisi\s*:\s*([\d.]+)/i)?.[1] || '';
                    const gorunur = e => e && e.getClientRects().length > 0 &&
                        getComputedStyle(e).display !== 'none' &&
                        getComputedStyle(e).visibility !== 'hidden';
                    const durdur = [...document.querySelectorAll('button, a, input')].some(e =>
                        gorunur(e) && /saldırıyı\s*durdur|saldiriyi\s*durdur/i.test(
                            (e.innerText || e.value || '').trim()
                        )
                    );
                    return {stok, durdur};
                })()
            """, "uzayfarm.php")
            stok = sayiyi_ayikla(durum.get("stok", "")) if durum else 0
            if durum and durum.get("durdur"):
                return True
            if onceki_mermi is not None and stok and stok < onceki_mermi:
                return True
        except (OSError, RuntimeError):
            pass
        time.sleep(0.5)
    return False


def uzay_saldirisini_baslat_ve_dogrula(
    dom: ChromeDOM, onceki_mermi: int | None, deneme_sayisi: int = 3
) -> bool:
    for deneme in range(1, deneme_sayisi + 1):
        if uzay_savasini_500m_ile_baslat(dom) and uzay_saldirisi_basladi_mi(
            dom, onceki_mermi
        ):
            print(f"✓ Otomatik saldırı gerçekten başladı ({deneme}. deneme).", flush=True)
            return True
        if deneme < deneme_sayisi:
            print(
                f"⚠ Saldırı düğmesine basıldı fakat ateş başlamadı "
                f"({deneme}/{deneme_sayisi}); yeniden deneniyor.",
                flush=True,
            )
            time.sleep(1)
    print("⛔ Otomatik saldırı üç denemede başlatılamadı.", flush=True)
    return False


def uzay_savasini_sure_boyunca_guclendir(
    dom: ChromeDOM, takip: dict | None = None
) -> None:
    """X3 yetmezse son 30 saniyede elmas hariç seçenekleri canlı olarak açar."""
    bildirildi = False
    bitis = time.time() + 70
    while time.time() < bitis:
        try:
            if "uzayfarm.php" not in dom.adres():
                return
            durum = dom.calistir(r"""
                (() => {
                    const sayac = document.querySelector('#countdown');
                    const yazi = (sayac?.innerText || sayac?.textContent || '').trim();
                    const p = yazi.match(/\d+/g)?.map(Number) || [];
                    let kalan = null;
                    if (p.length >= 3) kalan = p.at(-3) * 3600 + p.at(-2) * 60 + p.at(-1);
                    else if (p.length === 2) kalan = p[0] * 60 + p[1];
                    else if (p.length === 1) kalan = p[0];
                    const govde = document.body?.innerText || '';
                    const stok = govde.match(
                        /Mevcut\s+Lazer\s+Mermisi\s*:\s*([\d.]+)/i
                    )?.[1] || '';
                    if (kalan === null || kalan >= 30) return {kalan, guclendi: false, stok};
                    const secenekler = [...document.querySelectorAll('#saldirform input[id^="atak"]')];
                    const elmasMi = e => {
                        const etiket = document.querySelector(`label[for="${e.id}"]`);
                        return /elmas|diamond/i.test(
                            `${etiket?.innerText || ''} ${e.parentElement?.innerText || ''}`
                        );
                    };
                    secenekler.filter(e => !elmasMi(e)).forEach(e => {
                        if (!e.checked) e.click();
                        e.dispatchEvent(new Event('change', {bubbles: true}));
                    });
                    return {kalan, guclendi: true, stok};
                })()
            """, "uzayfarm.php")
            if takip is not None and durum and durum.get("stok"):
                takip["son_stok"] = sayiyi_ayikla(durum["stok"])
            if durum and durum.get("guclendi") and not bildirildi:
                print(
                    "⚡ Savaş son 30 saniyeye girdi; puanı tamamlamak için "
                    "elmas hariç ek saldırılar etkinleştirildi.",
                    flush=True,
                )
                bildirildi = True
        except (OSError, RuntimeError):
            pass
        time.sleep(0.5)


def adb_dokun(x: int, y: int) -> bool:
    """noname.py ile aynı yöntemle BlueStacks ekranına fiziksel dokunur."""
    sonuc = subprocess.run(
        [str(ADB), "-s", ADB_ADDRESS, "shell", "input", "tap", str(x), str(y)],
        capture_output=True, text=True, check=False,
    )
    return sonuc.returncode == 0


def uzay_dugme_merkezleri(dom: ChromeDOM) -> dict | None:
    """500 Milyon ile saldırı başlat düğmelerinin ekrandaki merkezlerini bulur."""
    try:
        return dom.calistir("""
            (() => {
                const form = document.querySelector('#saldirform') || document.querySelector('form');
                if (!form) return null;
                const elemanlar = [...form.querySelectorAll('input,button,label')];
                const metin = e => `${e.innerText || ''} ${e.value || ''} ${e.textContent || ''}`
                    .replace(/\\s+/g, ' ').trim().toLocaleLowerCase('tr-TR');
                const secenek = form.querySelector('#atak3') || elemanlar.find(e =>
                    /500\\s*(milyon|mn|m)\\b/.test(metin(e)));
                const baslat = form.querySelector('#saldiriBaslat') || elemanlar.find(e =>
                    /saldır.*başlat|başlat.*saldır/.test(metin(e)));
                const asil = e => e?.matches('input') && e.type === 'radio'
                    ? (form.querySelector(`label[for="${e.id}"]`) || e) : e;
                const merkez = e => {
                    e = asil(e);
                    if (!e) return null;
                    const r = e.getBoundingClientRect();
                    if (!r.width || !r.height) return null;
                    return {x:r.left + r.width / 2, y:r.top + r.height / 2};
                };
                const secimNoktasi = merkez(secenek), baslatNoktasi = merkez(baslat);
                if (!secimNoktasi || !baslatNoktasi) return null;
                return {secenek:secimNoktasi, baslat:baslatNoktasi,
                    dpr:devicePixelRatio, cssEkranYuksekligi:screen.height,
                    cssGorunumYuksekligi:innerHeight};
            })()
        """, "uzayfarm.php")
    except (RuntimeError, OSError):
        return None


def uzay_savasini_adb_tiklamayla_baslat(dom: ChromeDOM) -> bool:
    """DOM bozulursa iki uzay tuşuna ADB oto-clicker yedeğiyle basar."""
    noktalar = uzay_dugme_merkezleri(dom)
    if not noktalar:
        print("ADB yedeği: iki uzay düğmesinin yeri ölçülemedi.", flush=True)
        return False
    boyut = subprocess.run(
        [str(ADB), "-s", ADB_ADDRESS, "shell", "wm", "size"],
        capture_output=True, text=True, check=False,
    ).stdout
    eslesme = re.search(r"(?:Override|Physical) size:\s*(\d+)x(\d+)", boyut)
    if not eslesme:
        print("ADB yedeği: BlueStacks ekran boyutu okunamadı.", flush=True)
        return False
    _genislik, yukseklik = map(int, eslesme.groups())
    dpr = noktalar["dpr"]
    # Chrome'un adres/sekme çubuğu web görünümünün üstündedir.
    # getBoundingClientRect() bu payı içermediğinden fiziksel Y'ye eklenir.
    ust_pay = yukseklik - (noktalar["cssGorunumYuksekligi"] * dpr)
    secenek = (round(noktalar["secenek"]["x"] * dpr),
               round(noktalar["secenek"]["y"] * dpr + ust_pay))
    baslat = (round(noktalar["baslat"]["x"] * dpr),
              round(noktalar["baslat"]["y"] * dpr + ust_pay))
    print(f"DOM tıklaması başarısız; ADB oto-clicker: {secenek} -> {baslat}", flush=True)
    if not adb_dokun(*secenek):
        return False
    time.sleep(0.7)
    if not adb_dokun(*baslat):
        return False
    time.sleep(1)
    return True


def maden_egitimini_yap(dom: ChromeDOM, hesap) -> None:
    dom.adrese_git(YETENEK_OKULU_URL)
    dom.url_bekle("yetenek_okulu.php")
    time.sleep(1)

    secici = 'button[name="maden_yetenegi_standart"]'
    durum = dom.calistir(f"""
        (() => {{
            const dugme = document.querySelector({secici!r});
            return {{
                metin: document.body?.innerText || '',
                yapilabilir: Boolean(dugme && !dugme.disabled)
            }};
        }})()
    """, "yetenek_okulu.php")

    if not durum["yapilabilir"]:
        kalan = re.search(r"Kalan süre\s*:?\s*([^\n]+)", durum["metin"], re.IGNORECASE)
        neden = kalan.group(1).strip() if kalan else "Standart düğmesi kullanılamıyor"
        print(f"Maden Eğitimi şu anda yapılamıyor: {neden}", flush=True)
        return

    print("Maden Eğitimi / Standart başlatılıyor.", flush=True)
    dom.tikla(secici)
    noname_calistir_ve_bekle(dom, hesap, giris_dogrulamasi=False)
    print("Maden Eğitimi / Standart işlemi tamamlandı.", flush=True)


def konsey_tahsilatini_yap(dom: ChromeDOM) -> None:
    dom.adrese_git(AKTIF_MEKANLAR_URL)
    acilan = dom.yeni_sayfa_bekle(["aktifmekanlar.php", "vergidairesi.php"], saniye=30)
    if "vergidairesi.php" in acilan:
        vergiyi_ode(dom)
        dom.adrese_git(AKTIF_MEKANLAR_URL)
        dom.url_bekle("aktifmekanlar.php")
    time.sleep(1)

    durum = dom.calistir("""
        (() => {
            const alan = document.querySelector('#collapse2');
            if (!alan) return {metin: '', yapilabilir: false};
            const adaylar = [...alan.querySelectorAll('button, input[type="submit"], a')];
            const dugme = adaylar.find(e => {
                const yazi = (e.innerText || e.value || '').toLocaleLowerCase('tr-TR');
                return !e.disabled && /tahsil|topla|haraç/.test(yazi);
            });
            return {metin: alan.innerText || '', yapilabilir: Boolean(dugme)};
        })()
    """, "aktifmekanlar.php")

    if not durum["yapilabilir"]:
        zaman = re.search(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", durum["metin"])
        uygun_zaman = zaman.group(0) if zaman else "Tahsilat düğmesi henüz sunulmuyor"
        print(f"Konsey tahsilatı şu anda yapılamıyor. Uygun zaman: {uygun_zaman}", flush=True)
        return

    dom.calistir("""
        (() => {
            const alan = document.querySelector('#collapse2');
            const dugme = [...alan.querySelectorAll('button, input[type="submit"], a')]
                .find(e => /tahsil|topla|haraç/.test(
                    (e.innerText || e.value || '').toLocaleLowerCase('tr-TR')
                ) && !e.disabled);
            dugme.click();
            return true;
        })()
    """, "aktifmekanlar.php")
    time.sleep(2)
    son_metin = dom.calistir("document.body?.innerText || ''")
    zaman = re.search(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", son_metin)
    if zaman:
        print(f"Konsey tahsilatı tamamlandı. Sonraki zaman: {zaman.group(0)}", flush=True)
    else:
        print("Konsey tahsilatı gönderildi.", flush=True)


def vergiyi_ode(dom: ChromeDOM) -> None:
    dom.url_bekle("vergidairesi.php")
    metin = dom.calistir("document.body?.innerText || ''", "vergidairesi.php")
    borc = re.search(r"Vergi Borcunuz\s*([\d.,]+\s*TL)", metin, re.IGNORECASE)
    borc_metni = borc.group(1) if borc else "tutar okunamadı"
    dugme_var = dom.calistir(
        "Boolean(document.querySelector('button[name=\"borcode\"]'))",
        "vergidairesi.php",
    )
    if not dugme_var:
        raise RuntimeError("Vergi borcu ödeme düğmesi bulunamadı.")
    print(f"Vergi borcu ödeniyor: {borc_metni}", flush=True)
    dom.tikla('button[name="borcode"]')
    time.sleep(2)
    print("Vergi ödeme işlemi gönderildi.", flush=True)


def bilgilendirmeyi_onayla(dom: ChromeDOM, hesap) -> None:
    adres = dom.yeni_sayfa_bekle(
        ["geridoninfo.php", "anasayfa.php", "geridon.php"],
        saniye=GIRIS_DOGRULAMA_SONUC_BEKLEME,
    )
    if "geridon.php" in adres:
        hata_metni = dom.calistir("document.body ? document.body.innerText : ''")
        raise RuntimeError(" ".join(hata_metni.split())[:300])
    if "geridoninfo.php" in adres:
        mesaj = dom.calistir("document.body?.innerText || ''", "geridoninfo.php") or ""
        temiz_mesaj = " ".join(mesaj.split())
        print(f"Bilgilendirme: {temiz_mesaj}", flush=True)
        dom.tikla('a[href="anasayfa.php"]')
        dom.url_bekle("anasayfa.php")
    else:
        print("Doğrulama başarılı; anasayfa açıldı.", flush=True)
    oyun_adi = dom.calistir(
        "document.querySelector('a[href^=\"profil.php?kimlik=\"] h6 b')?.textContent?.trim() || ''",
        "anasayfa.php",
    )
    if oyun_adi:
        oyun_adi = kodlamayi_duzelt(oyun_adi)
        hesap_hafizasi.oyun_adi_guncelle(hesap.kullanici_adi, oyun_adi)
        hesap.oyun_adi = oyun_adi
        print(f"Oyun adı sisteme kaydedildi: {oyun_adi}", flush=True)


def captcha_gorunuyor_mu(dom: ChromeDOM, saniye: float = 5) -> bool:
    """Sayfada gerçekten görünür bir CAPTCHA alanı oluşmasını kısa süre bekler."""
    kontrol = r"""
        (() => {
            const gorunur = e => {
                if (!e || !e.isConnected) return false;
                const stil = getComputedStyle(e);
                return stil.display !== 'none' && stil.visibility !== 'hidden' &&
                    Number(stil.opacity || 1) !== 0 && e.getClientRects().length > 0;
            };
            const seciciler = [
                '.g-recaptcha', '.h-captcha', '.cf-turnstile',
                '[class*="captcha" i]', '[id*="captcha" i]',
                'iframe[src*="captcha" i]', 'iframe[src*="recaptcha" i]',
                'iframe[src*="hcaptcha" i]', 'iframe[src*="turnstile" i]',
                'iframe[title*="captcha" i]',
                'img[src*="captcha" i]', 'img[alt*="captcha" i]',
                'input[name*="captcha" i]'
            ];
            if (seciciler.some(s => [...document.querySelectorAll(s)].some(gorunur))) {
                return true;
            }
            return [...document.querySelectorAll(
                '[role="dialog"], .modal.show, .modal[style*="display: block"]'
            )].some(e => gorunur(e) && /captcha|doğrula|robot değil/i.test(e.innerText || ''));
        })()
    """
    bitis = time.time() + saniye
    while time.time() < bitis:
        try:
            if dom.calistir(kontrol):
                return True
        except (OSError, RuntimeError):
            pass
        time.sleep(0.25)
    return False


def noname_calistir_ve_bekle(dom: ChromeDOM, hesap, giris_dogrulamasi: bool = False) -> None:
    if not captcha_gorunuyor_mu(dom):
        print("CAPTCHA görünmedi; noname.py çalıştırılmadı.", flush=True)
        if giris_dogrulamasi:
            bilgilendirmeyi_onayla(dom, hesap)
        return

    son_hata = "Doğrulama yardımcısı başlatılamadı."
    captcha_sonucu_geldi = False
    for deneme in range(1, GIRIS_DENEME_SINIRI + 1):
        surec = noname_botunu_baslat()
        if surec is not None:
            try:
                noname_botunun_bitmesini_bekle(surec)
                break
            except (RuntimeError, TimeoutError) as hata:
                son_hata = str(hata)
        else:
            son_hata = "noname.py başlatılamadı."

        # Yardımcı süreç hata kodu verse bile dokunma tamamlanmış ve oyun CAPTCHA'yı
        # kapatmış olabilir. Başarı sayfasındayken boşuna yeni çözüm denemesi yapma.
        if not captcha_gorunuyor_mu(dom, saniye=1):
            print("✓ CAPTCHA ekrandan kalktı; doğrulama başarılı kabul edildi.", flush=True)
            captcha_sonucu_geldi = True
            break

        if deneme < GIRIS_DENEME_SINIRI:
            print(
                f"⚠ CAPTCHA yardımcısı başarısız ({deneme}/{GIRIS_DENEME_SINIRI}); "
                "ADB yenilenip tekrar denenecek.",
                flush=True,
            )
            adb_baglantisini_yenile(dom)
    else:
        noname_son_hatasini_yazdir()
        if giris_dogrulamasi and sys.stdin.isatty():
            secim = input(
                "CAPTCHA otomatik çözülemedi. Manuel tamamlayıp DOĞRULA'ya bas; "
                "devam için Enter, hesabı atlamak için A yaz: "
            ).strip().casefold()
            if secim != "a":
                bilgilendirmeyi_onayla(dom, hesap)
                return
        raise DogrulamaYardimcisiHatasi(
            f"CAPTCHA yardımcısı {GIRIS_DENEME_SINIRI} denemede çalışmadı: {son_hata}"
        )
    if giris_dogrulamasi:
        tiklandi = captcha_sonucu_geldi or bool(dom.calistir(r"""
            (() => {
                const gorunur = e => e && e.getClientRects().length > 0 &&
                    getComputedStyle(e).display !== 'none' &&
                    getComputedStyle(e).visibility !== 'hidden';
                const dugme = [...document.querySelectorAll(
                    'button, input[type="button"], input[type="submit"], a'
                )].find(e => gorunur(e) && /doğrula|onayla|verify/i.test(
                    (e.innerText || e.value || '').trim()
                ));
                if (!dugme) return false;
                dugme.click();
                return true;
            })()
        """))
        if captcha_sonucu_geldi:
            print("✓ Giriş doğrulaması arka planda tamamlandı.", flush=True)
        elif tiklandi:
            print("✓ CAPTCHA çözüldü; DOĞRULA arka planda tıklandı.", flush=True)
        else:
            tam_ekrani_garantile()
            print(
                "DOĞRULA düğmesi otomatik bulunamadı; BlueStacks öne getirildi, "
                "manuel basman bekleniyor...",
                flush=True,
            )
        bilgilendirmeyi_onayla(dom, hesap)
    else:
        print("noname.py tamamlandı; manuel Doğrula beklenmeden devam ediliyor.", flush=True)


def uretim_sonucunu_ayikla(metin: str) -> str:
    """Sayfanın tamamı yerine yalnız gerçek kazanç cümlesini döndürür."""
    temiz = " ".join((metin or "").split())
    eslesme = re.search(
        r"(İşlem\s+Başarılı\s*!.*?)(?:\s+TAMAM|\s+ANASAYFA|$)",
        temiz,
        re.IGNORECASE,
    )
    if not eslesme:
        return ""
    return eslesme.group(1).strip()


def uretim_durumunu_oku(dom: ChromeDOM, adres: str) -> dict:
    sayfa = Path(adres).name
    dom.adrese_git(adres)
    dom.url_bekle(sayfa)
    time.sleep(0.5)
    durum = dom.calistir("""
        (() => ({
            metin: document.body?.innerText || '',
            yapilabilir: Boolean(
                document.querySelector('button[data-target="#modal1"]') &&
                document.querySelector('#reklamIzleBtn')
            )
        }))()
    """, sayfa)
    kalan = re.search(r"Kalan süre\s*:?\s*([^\n]+)", durum["metin"], re.IGNORECASE)
    durum["kalan"] = kalan.group(1).strip() if kalan else "İşlem düğmesi sunulmuyor"
    return durum


def uretim_islemini_yap(dom: ChromeDOM, hesap, ad: str, adres: str) -> bool:
    ilk_durum = uretim_durumunu_oku(dom, adres)
    if not ilk_durum["yapilabilir"]:
        print(f"{ad} şu anda yapılamıyor: {ilk_durum['kalan']}", flush=True)
        return False

    son_hata = "İşlem sonucu doğrulanamadı"
    for deneme in range(1, GIRIS_DENEME_SINIRI + 1):
        print(f"{ad} denemesi {deneme}/{GIRIS_DENEME_SINIRI}", flush=True)
        dom.tikla('button[data-target="#modal1"]')
        time.sleep(ISLEM_BEKLEME)
        reklam_dugmesine_bas(dom)
        noname_calistir_ve_bekle(dom, hesap, giris_dogrulamasi=False)

        sonuc = ""
        bitis = time.time() + 20
        while time.time() < bitis:
            try:
                govde = dom.calistir("document.body ? document.body.innerText : ''") or ""
                sonuc = uretim_sonucunu_ayikla(govde)
                if sonuc:
                    break
            except (RuntimeError, OSError):
                pass
            time.sleep(0.5)

        son_durum = uretim_durumunu_oku(dom, adres)
        if sonuc or not son_durum["yapilabilir"]:
            kayit_metni = sonuc or f"İşlem tamamlandı. Yeni durum: {son_durum['kalan']}"
            kazanc_kaydet(hesap, ad, kayit_metni)
            print(f"{ad} doğrulandı. Yeni durum: {son_durum['kalan']}", flush=True)
            return True

        son_hata = "Düğme hâlâ aktif; işlem gerçekleşmemiş görünüyor"
        print(f"{ad}: {son_hata}", flush=True)

    raise RuntimeError(f"{ad} başarısız: {son_hata}")


def hesaplari_sirayla_calistir() -> None:
    hesaplar = calisacak_hesaplari_sec(hesap_hafizasi.tumunu_getir())
    if not hesaplar:
        raise RuntimeError("Kayıtlı hesap bulunamadı.")
    if not NONAME_BOT.exists():
        raise FileNotFoundError(
            "noname.py yolu ayarlı değil. otomasyon.py içindeki NONAME_BOT değerini düzenle."
        )

    dom = ChromeDOM(str(ADB), ADB_ADDRESS)
    dom.baglan()
    dom.site_verisini_temizle("https://www.ticariononline.com")
    dom.adrese_git("https://www.ticariononline.com/tr/girisyap.php")
    dom.gereksiz_ticarion_sekmelerini_kapat()
    dom.secici_bekle('input[name="mail"]')
    for sira, hesap in enumerate(hesaplar, start=1):
        print(f"Hesap {sira}/{len(hesaplar)}", flush=True)
        giris_basarili = False
        try:
            giris_yap_ve_dogrula(dom, hesap)
            giris_basarili = True
            hesap_islemlerini_yap(dom, hesap)
        except Exception as hata:
            print(f"{hesap_adi(hesap)} hesap hatası; sıradaki hesaba geçiliyor: {hata}", flush=True)
        finally:
            if giris_basarili:
                guvenli_cikis_yap(dom, hesap)
            else:
                oturumu_sifirla(dom)


def sadece_uretimleri_calistir() -> None:
    """Yalnız eyalet madeni, sanayisi ve fabrikasını çalıştırır."""
    hesaplar = calisacak_hesaplari_sec(hesap_hafizasi.tumunu_getir())
    if not hesaplar:
        raise RuntimeError("Kayıtlı hesap bulunamadı.")
    if not NONAME_BOT.exists():
        raise FileNotFoundError(
            "noname.py yolu ayarlı değil. otomasyon.py içindeki NONAME_BOT değerini düzenle."
        )
    dom = ChromeDOM(str(ADB), ADB_ADDRESS)
    dom.baglan()
    dom.site_verisini_temizle("https://www.ticariononline.com")
    dom.adrese_git("https://www.ticariononline.com/tr/girisyap.php")
    dom.gereksiz_ticarion_sekmelerini_kapat()
    dom.secici_bekle('input[name="mail"]')
    islemler = [
        ("Eyalet madeni", MADEN_REZERVI_URL),
        ("Eyalet sanayisi", EYALET_SANAYISI_URL),
        ("Eyalet fabrikası", EYALET_FABRIKASI_URL),
    ]
    for sira, hesap in enumerate(hesaplar, start=1):
        print(f"Maden/Sanayi/Fabrika hesabı {sira}/{len(hesaplar)}", flush=True)
        giris_basarili = False
        try:
            giris_yap_ve_dogrula(dom, hesap)
            giris_basarili = True
            for ad, adres in islemler:
                try:
                    uretim_islemini_yap(dom, hesap, ad, adres)
                except Exception as hata:
                    print(f"{ad} hatası; sonraki işleme geçiliyor: {hata}", flush=True)
        except Exception as hata:
            print(f"{hesap_adi(hesap)} hesap hatası; sıradaki hesaba geçiliyor: {hata}", flush=True)
        finally:
            if giris_basarili:
                guvenli_cikis_yap(dom, hesap)
            else:
                oturumu_sifirla(dom)


def ana_sayfa_reklamini_izle(dom: ChromeDOM, hesap) -> bool:
    """Ana sayfa reklamını açar; sonuç sayfası gelir gelmez devam eder."""
    dom.adrese_git("https://www.ticariononline.com/tr/anasayfa.php")
    dom.url_bekle("anasayfa.php", saniye=20)
    dugme = dom.calistir(r"""
        (() => {
            const e = document.querySelector('#reklamIzleBtn');
            return e ? (e.innerText || e.value || '').trim() : '';
        })()
    """, "anasayfa.php") or ""
    if not re.search(r"tıkla\s*izle", dugme, re.IGNORECASE):
        print(f"{hesap_adi(hesap)}: İzlenebilir reklam bulunamadı.", flush=True)
        return False
    print(f"{hesap_adi(hesap)}: Ana sayfa reklamı açılıyor.", flush=True)
    reklam_dugmesine_bas(dom)
    noname_calistir_ve_bekle(dom, hesap, giris_dogrulamasi=False)
    sonuc_adresi = dom.yeni_sayfa_bekle(
        ["geridononay.php", "geridoninfo.php"], saniye=60
    )
    print(f"✓ Reklam sonucu alındı: {Path(sonuc_adresi).name}", flush=True)
    dom.adrese_git("https://www.ticariononline.com/tr/anasayfa.php")
    dom.url_bekle("anasayfa.php", saniye=20)
    print(f"✓ {hesap_adi(hesap)} reklam izleme işlemi tamamlandı.", flush=True)
    return True


def sadece_reklamlari_izle() -> None:
    hesaplar = calisacak_hesaplari_sec(hesap_hafizasi.tumunu_getir())
    if not hesaplar:
        raise RuntimeError("Kayıtlı hesap bulunamadı.")
    dom = ChromeDOM(str(ADB), ADB_ADDRESS)
    dom.baglan()
    dom.site_verisini_temizle("https://www.ticariononline.com")
    dom.adrese_git(BASLANGIC_SAYFASI_URL)
    dom.gereksiz_ticarion_sekmelerini_kapat()
    dom.secici_bekle('input[name="mail"]')
    for sira, hesap in enumerate(hesaplar, start=1):
        print(f"Reklam hesabı {sira}/{len(hesaplar)}: {hesap_adi(hesap)}", flush=True)
        giris_basarili = False
        try:
            giris_yap_ve_dogrula(dom, hesap)
            giris_basarili = True
            ana_sayfa_reklamini_izle(dom, hesap)
        except Exception as hata:
            print(f"{hesap_adi(hesap)} reklam hatası; hesap geçiliyor: {hata}", flush=True)
        finally:
            if giris_basarili:
                guvenli_cikis_yap(dom, hesap)
            else:
                oturumu_sifirla(dom)


def calisma_modunu_sec() -> str:
    if os.environ.get("TICARION_OTOMATIK_MOD") == "1":
        print("\nOtomatik mod: 1 - Tam sistem (Volkan hariç)", flush=True)
        return "1"
    print("\nBOT ÇALIŞMA MODU", flush=True)
    print("1 - Tam sistem (uzay farmı hariç)", flush=True)
    print("2 - Sadece Maden + Sanayi + Fabrika", flush=True)
    print("3 - Reklam İzle", flush=True)
    print("4 - Hesap bazında kazanç raporu", flush=True)
    print("0 - Çıkış", flush=True)
    while True:
        secim = input("Seçimin: ").strip()
        if secim in {"0", "1", "2", "3", "4"}:
            return secim
        print("Geçersiz seçim. 0, 1, 2, 3 veya 4 yaz.", flush=True)


def noname_botunu_baslat() -> subprocess.Popen | None:
    if not NONAME_BOT.exists():
        print(
            "noname.py yolu henüz ayarlanmadı. otomasyon.py içindeki "
            "NONAME_BOT değerini düzenle.",
            flush=True,
        )
        return None

    ayarlar = {
        "cwd": str(NONAME_BOT.parent),
        "stdin": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        ayarlar["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        with NONAME_LOG.open("ab") as log:
            log.write(
                f"\n--- {datetime.now().isoformat(timespec='seconds')} ---\n".encode("utf-8")
            )
            surec = subprocess.Popen(
                [sys.executable, str(NONAME_BOT)],
                stdout=log,
                stderr=subprocess.STDOUT,
                **ayarlar,
            )
    except OSError as hata:
        print(f"noname.py süreci açılamadı: {hata}", flush=True)
        return None
    time.sleep(0.5)
    if surec.poll() is not None and surec.returncode != 0:
        print(f"noname.py hemen hata verdi. Çıkış kodu: {surec.returncode}", flush=True)
        noname_son_hatasini_yazdir()
        return None
    return surec


def noname_botunun_bitmesini_bekle(
    surec: subprocess.Popen, saniye: int = CAPTCHA_YARDIMCI_BEKLEME
) -> None:
    try:
        cikis_kodu = surec.wait(timeout=saniye)
    except subprocess.TimeoutExpired as hata:
        surec.terminate()
        try:
            surec.wait(timeout=5)
        except subprocess.TimeoutExpired:
            surec.kill()
            surec.wait(timeout=5)
        raise TimeoutError(
            f"Doğrulama yardımcısı {saniye} saniye içinde tamamlanmadı."
        ) from hata
    if cikis_kodu != 0:
        raise RuntimeError(f"noname.py hata koduyla kapandı: {cikis_kodu}")


def adb_baglantisini_yenile(dom: ChromeDOM | None = None) -> bool:
    if not ADB_ADDRESS:
        return False
    """Geçici ppadb 'closed' hatalarında BlueStacks ADB bağlantısını tazeler."""
    subprocess.run(
        [str(ADB), "disconnect", ADB_ADDRESS], capture_output=True, text=True, check=False
    )
    time.sleep(0.5)
    sonuc = subprocess.run(
        [str(ADB), "connect", ADB_ADDRESS], capture_output=True, text=True, check=False
    )
    time.sleep(0.5)
    if dom is not None:
        try:
            dom.baglan()
        except (OSError, RuntimeError):
            pass
    cevap = f"{sonuc.stdout} {sonuc.stderr}".casefold()
    return sonuc.returncode == 0 and "failed" not in cevap and "unable" not in cevap


def noname_son_hatasini_yazdir() -> None:
    if not NONAME_LOG.exists():
        return
    satirlar = NONAME_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    anlamli = [satir.strip() for satir in satirlar if satir.strip()]
    hata_satirlari = [
        satir for satir in anlamli
        if re.search(r"(?:runtimeerror|exception|error:)\s*", satir, re.IGNORECASE)
    ]
    ozet = (hata_satirlari[-1] if hata_satirlari else (anlamli[-1] if anlamli else ""))[:300]
    if ozet:
        print(f"⚠ CAPTCHA hata özeti: {ozet}", flush=True)


def chrome_ac() -> None:
    if ADB_ADDRESS:
        subprocess.run([str(ADB), "connect", ADB_ADDRESS], capture_output=True, check=False)
    bitis = time.time() + 60
    while time.time() < bitis:
        sonuc = subprocess.run(
            [str(ADB), "-s", ADB_ADDRESS, "shell", "getprop", "sys.boot_completed"],
            capture_output=True,
            text=True,
            check=False,
        )
        if sonuc.stdout.strip() == "1":
            break
        time.sleep(2)

    subprocess.run(
        [
            str(ADB), "-s", ADB_ADDRESS, "shell", "am", "start", "-W",
            "-a", "android.intent.action.VIEW",
            "-d", BASLANGIC_SAYFASI_URL,
            "-p", "com.android.chrome",
        ],
        capture_output=True,
        check=True,
    )


def adb_var_mi() -> bool:
    return ADB.exists() or shutil.which(str(ADB)) is not None


def emulatoru_baslat() -> None:
    if IS_WINDOWS:
        if not BLUESTACKS.exists():
            raise FileNotFoundError(f"BlueStacks bulunamadı: {BLUESTACKS}")
        subprocess.Popen([str(BLUESTACKS), "--instance", INSTANCE])
        pencereyi_bekle()
        return

    if IS_MACOS:
        if BLUESTACKS.exists():
            subprocess.Popen(["open", str(BLUESTACKS)])
        else:
            subprocess.Popen(["open", "-a", "BlueStacks"])
        time.sleep(8)
        return

    if BLUESTACKS.exists():
        subprocess.Popen([str(BLUESTACKS)])
        time.sleep(8)
        return

    print("Emulator otomatik açılamadı; açık olduğunu varsayıp devam ediliyor.", flush=True)


def baslat() -> None:
    calisma_modu = calisma_modunu_sec()
    if calisma_modu == "0":
        print("Bot kapatıldı.", flush=True)
        return
    kazanc_veritabanini_hazirla()
    if calisma_modu == "4":
        kazanc_raporunu_yazdir()
        return
    if not adb_var_mi():
        raise FileNotFoundError(
            f"ADB bulunamad?: {ADB}. Mac i?in Android platform-tools kur veya "
            "TICARION_ADB_PATH ortam de?i?kenini ayarla."
        )

    hwnd = pencereyi_bul(WINDOW_TITLE)
    if not hwnd:
        emulatoru_baslat()

    chrome_ac()
    time.sleep(5)
    tam_ekrani_garantile()
    time.sleep(ISLEM_BEKLEME)
    if calisma_modu == "2":
        sadece_uretimleri_calistir()
    elif calisma_modu == "3":
        sadece_reklamlari_izle()
    else:
        hesaplari_sirayla_calistir()
    

if __name__ == "__main__":
    baslat()
