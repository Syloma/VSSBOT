"""Yalnız JackTheRipper ve YAVUZ 54 hesaplarında uzay farmı çalıştırır."""

from __future__ import annotations

import subprocess
import time
import unicodedata

import otomasyon as bot
from chrome_dom import ChromeDOM
from hesap_hafizasi import hesap_hafizasi


HEDEF_HESAPLAR = ("jacktheripper", "yavuz54", "volkanarslan")


def sade_ad(metin: str) -> str:
    metin = unicodedata.normalize("NFKD", (metin or "").casefold())
    return "".join(karakter for karakter in metin if karakter.isalnum())


def uzay_hesaplarini_getir():
    bulunan = {}
    for hesap in hesap_hafizasi.tumunu_getir():
        oyun_adi = hesap.oyun_adi or bot.HESAP_OYUN_ADLARI.get(hesap.kullanici_adi, "")
        sade = sade_ad(oyun_adi)
        for hedef in HEDEF_HESAPLAR:
            if hedef in sade:
                bulunan[hedef] = hesap
    eksik = [hedef for hedef in HEDEF_HESAPLAR if hedef not in bulunan]
    if eksik:
        raise RuntimeError("Uzay farmı hesapları bulunamadı: " + ", ".join(eksik))
    return [bulunan[hedef] for hedef in HEDEF_HESAPLAR]


def altyapiyi_hazirla() -> None:
    if not bot.BLUESTACKS.exists():
        raise FileNotFoundError(f"BlueStacks bulunamadı: {bot.BLUESTACKS}")
    if not bot.ADB.exists():
        raise FileNotFoundError(f"BlueStacks ADB bulunamadı: {bot.ADB}")
    if not bot.NONAME_BOT.exists():
        raise FileNotFoundError(f"Doğrulama yardımcısı bulunamadı: {bot.NONAME_BOT}")
    pencere = bot.pencereyi_bul(bot.WINDOW_TITLE)
    if not pencere:
        subprocess.Popen([str(bot.BLUESTACKS), "--instance", bot.INSTANCE])
        bot.pencereyi_bekle()
    bot.chrome_ac()
    time.sleep(5)
    bot.tam_ekrani_garantile()


def enerji_bitene_kadar_farm_yap(dom: ChromeDOM, hesap) -> None:
    """Geçici arızalarda hesabı bırakmaz; enerji bitene kadar farmı sürdürür."""
    while True:
        try:
            enerji = bot.yasam_enerjisini_oku(dom)
        except Exception as hata:
            print(
                f"Yaşam enerjisi okunamadı; hesaptan çıkılmayacak, 5 saniye sonra "
                f"tekrar denenecek: {hata}",
                flush=True,
            )
            time.sleep(5)
            continue

        print(f"Kalan yaşam enerjisi: {enerji}", flush=True)
        if enerji <= 0:
            print("Yaşam enerjisi bitti; artık hesaptan çıkılabilir.", flush=True)
            return

        try:
            devam = bot.uzay_normal_saldiri_yap(dom, hesap, mevcut_enerji=enerji)
            if devam is False:
                print("Enerji seçilen korsana yetmiyor; hesaptan çıkılabilir.", flush=True)
                return
        except bot.LazerMermisiUretimHatasi as hata:
            print(
                f"⛔ Lazer Mermisi hazırlanamadı; bu hesap atlanıyor: {hata}",
                flush=True,
            )
            return
        except Exception as hata:
            print(f"Uzay farmında arıza oluştu: {hata}", flush=True)
        time.sleep(2)


def main() -> None:
    # Volkan Arslan ana otomasyonda opsiyoneldir; burada da her tur sorulur.
    hesaplar = bot.calisacak_hesaplari_sec(uzay_hesaplarini_getir())
    print("Uzay farmı hesapları: " + ", ".join(bot.hesap_adi(h) for h in hesaplar), flush=True)
    altyapiyi_hazirla()
    dom = ChromeDOM(str(bot.ADB), bot.ADB_ADDRESS)
    dom.baglan()
    dom.site_verisini_temizle("https://www.ticariononline.com")
    dom.adrese_git(bot.BASLANGIC_SAYFASI_URL)
    dom.gereksiz_ticarion_sekmelerini_kapat()
    dom.secici_bekle('input[name="mail"]')

    for sira, hesap in enumerate(hesaplar, 1):
        print(f"Uzay hesabı {sira}/{len(hesaplar)}: {bot.hesap_adi(hesap)}", flush=True)
        giris_yapildi = False
        try:
            bot.giris_yap_ve_dogrula(dom, hesap)
            giris_yapildi = True
            enerji_bitene_kadar_farm_yap(dom, hesap)
        except Exception as hata:
            print(f"Uzay farmı iptal edildi; sıradaki hesaba geçiliyor: {hata}", flush=True)
        finally:
            if giris_yapildi:
                bot.guvenli_cikis_yap(dom, hesap)
            else:
                bot.oturumu_sifirla(dom)
    print("✓ Tüm uzay farmı hesapları tamamlandı.", flush=True)


if __name__ == "__main__":
    main()
