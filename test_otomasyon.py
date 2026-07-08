import tempfile
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import otomasyon
import uzay_farmi


class OtomasyonSafFonksiyonTestleri(unittest.TestCase):
    def test_enerji_bitisini_ayirt_eder(self):
        self.assertTrue(otomasyon.enerji_bitti("Yaşam enerjiniz yetersiz"))
        self.assertTrue(otomasyon.enerji_bitti("Enerji bitti"))
        self.assertFalse(otomasyon.enerji_bitti("5 enerji kazandınız"))

    def test_yalniz_gercek_uretim_sonucunu_ayiklar(self):
        metin = (
            "Ticarion İşlem Başarılı ! Maden kazı işleminde 76.869.000 adet "
            "KERESTE elde ettiniz. TAMAM ANASAYFA"
        )
        self.assertEqual(
            otomasyon.uretim_sonucunu_ayikla(metin),
            "İşlem Başarılı ! Maden kazı işleminde 76.869.000 adet KERESTE elde ettiniz.",
        )
        self.assertEqual(otomasyon.uretim_sonucunu_ayikla("Varlıklarım Boşta araç var"), "")

    def test_uzay_hesap_adi_normalizasyonu(self):
        self.assertEqual(uzay_farmi.sade_ad("☠️YAVUZ 54⭐️"), "yavuz54")

    def test_veritabani_baglantisi_dosyayi_kilitlemez(self):
        with tempfile.TemporaryDirectory() as klasor:
            db = Path(klasor) / "test.db"
            log = Path(klasor) / "test.jsonl"
            with patch.object(otomasyon, "KAZANC_DB", db), patch.object(
                otomasyon, "KAZANC_LOG", log
            ):
                otomasyon.kazanc_veritabanini_hazirla()
                with otomasyon.db_baglantisi() as baglanti:
                    baglanti.execute(
                        "INSERT INTO kazanc_kayitlari(tarih,hesap,islem,sonuc) "
                        "VALUES('x','x','x','x')"
                    )
                db.unlink()
                self.assertFalse(db.exists())

    def test_uretim_bir_kez_tiklanir_ve_kazanc_dogrulanir(self):
        class SahteHesap:
            oyun_adi = "TEST"
            kullanici_adi = "test"

        class SahteDOM:
            tamamlandi = False
            reklam_tiklama = 0

            def adrese_git(self, _adres):
                return None

            def url_bekle(self, _sayfa, saniye=30):
                return None

            def tikla(self, secici):
                if secici == "#reklamIzleBtn":
                    self.reklam_tiklama += 1
                    self.tamamlandi = True

            def calistir(self, javascript, _sayfa=None):
                if "yapilabilir" in javascript:
                    return {
                        "metin": "Kalan süre: 2 saat" if self.tamamlandi else "Hazır",
                        "yapilabilir": not self.tamamlandi,
                    }
                return (
                    "İşlem Başarılı ! Maden kazı işleminde 10 KERESTE elde ettiniz. TAMAM"
                    if self.tamamlandi
                    else ""
                )

        dom = SahteDOM()
        with patch.object(otomasyon, "noname_calistir_ve_bekle"), patch.object(
            otomasyon, "kazanc_kaydet"
        ) as kaydet, patch.object(otomasyon.time, "sleep"):
            sonuc = otomasyon.uretim_islemini_yap(
                dom, SahteHesap(), "Eyalet madeni", otomasyon.MADEN_REZERVI_URL
            )
        self.assertTrue(sonuc)
        self.assertEqual(dom.reklam_tiklama, 1)
        self.assertIn("10 KERESTE", kaydet.call_args.args[2])

    def test_uzay_tasi_ve_xp_ayiklanir(self):
        sonuc = otomasyon.uzay_kazancini_ayikla(
            "Tebrikler! Uzay korsanını alt ederek 2 adet photonium ve 2 Exp kazandınız."
        )
        self.assertEqual(sonuc, ("2", "photonium", "2"))

    def test_uzay_ozeti_para_ve_elmasi_gostermez(self):
        metin = (
            "Ticarion line 💎 3.965 Elmas 💸 787,85 Trilyon TL İşlem Başarılı! "
            "30 adet aurorium, 4 adet carbon ve 30 Exp kazandınız. TAMAM ANASAYFA"
        )
        ozet = otomasyon.uzay_sonuc_ozeti(metin)
        self.assertEqual(ozet, "30 aurorium + 4 carbon + 30 XP")
        self.assertNotIn("Elmas", ozet)
        self.assertNotIn("Trilyon", ozet)

    def test_uzay_kaydi_yalniz_ganimet_ve_xp_icerir(self):
        metin = (
            "Ticarion line 3.952 Elmas 881,69 Trilyon TL İşlem Başarılı! "
            "2 adet aurorium ve 2 Exp kazandınız. TAMAM ANASAYFA"
        )
        self.assertEqual(
            otomasyon.uzay_kayit_metnini_sadelestir(metin),
            "2 adet aurorium | 2 XP",
        )

    def test_odulsuz_uzay_kaydi_sadelestirilir(self):
        metin = (
            "Ticarion line 3.943 Elmas 880,64 Trilyon TL İşlem Başarılı! "
            "Uzay korsanını alt edemediğiniz için bir ödül alamadınız. TAMAM ANASAYFA"
        )
        beklenen = "Korsan yenilemedi; ödül alınamadı."
        self.assertEqual(otomasyon.uzay_kayit_metnini_sadelestir(metin), beklenen)
        self.assertEqual(otomasyon.uzay_sonuc_ozeti(metin), beklenen)

    def test_eski_uretim_sayfa_dokumu_kazanc_sayilmaz(self):
        self.assertEqual(
            otomasyon.kazanc_kayit_metnini_sadelestir(
                "Eyalet fabrikası", "Ticarion line 100 Elmas Varlıklarım Hepsini Çalıştır"
            ),
            "Sonuç doğrulanamadı (eski kayıt).",
        )

    def test_kazanc_kalemleri_hesaplanir(self):
        kalemler = otomasyon.kazanc_kalemlerini_ayikla(
            "10 adet KERESTE elde ettiniz. 2 adet photonium ve 3 Exp kazandınız."
        )
        self.assertEqual(kalemler, {"kereste": 10, "photonium": 2, "xp": 3})

    def test_yasam_enerjisi_uzay_gemisi_sayfasindan_okunur(self):
        class SahteDOM:
            def adrese_git(self, _adres):
                return None

            def url_bekle(self, _sayfa, saniye=30):
                return None

            def calistir(self, _javascript, _sayfa=None):
                return "Uzay Gemisi\nYaşam Enerjisi: 1.250"

        self.assertEqual(otomasyon.yasam_enerjisini_oku(SahteDOM()), 1250)

    def test_uzay_farmi_enerji_bitene_kadar_hesabi_birakmaz(self):
        class SahteHesap:
            oyun_adi = "YAVUZ 54"
            kullanici_adi = "yavuz"

        with patch.object(uzay_farmi.bot, "uzay_normal_saldiri_yap") as farm, patch.object(
            uzay_farmi.bot, "yasam_enerjisini_oku", side_effect=[7, 0]
        ), patch.object(uzay_farmi.time, "sleep"):
            uzay_farmi.enerji_bitene_kadar_farm_yap(object(), SahteHesap())
        self.assertEqual(farm.call_count, 1)

    def test_korsan_aciklamasindan_enerji_maliyeti_okunur(self):
        self.assertEqual(
            otomasyon.korsan_enerji_maliyetini_ayikla("Bu saldırı 3 yaşam enerjisi harcar."),
            3,
        )

    def test_lazer_mermisi_stok_ve_maliyeti_okunur(self):
        metin = (
            "Mevcut Lazer Mermisi : 3.718.843 Adet\n"
            "NOT : Tüm saldırılarda 1.000 lazer mermisi harcanır."
        )
        self.assertEqual(otomasyon.lazer_mermisi_bilgisini_ayikla(metin), (3718843, 1000))

    def test_uzay_gemisi_mermi_karti_okunur(self):
        class SahteDOM:
            def calistir(self, _javascript, _sayfa=None):
                return "Lazer Mermisi\n1.000.344 Adet"

        self.assertEqual(otomasyon.uzay_gemisi_mermi_stogunu_oku(SahteDOM()), 1000344)

    def test_mermi_stogu_gecici_okuma_hatasinda_tekrar_dener(self):
        class SahteDOM:
            cevaplar = iter(["", "yükleniyor", "Lazer Mermisi\n55.000 Adet"])

            def calistir(self, _javascript, _sayfa=None):
                return next(self.cevaplar)

        with patch.object(otomasyon.time, "sleep") as bekle:
            stok = otomasyon.uzay_gemisi_mermi_stogunu_oku(SahteDOM())
        self.assertEqual(stok, 55000)
        self.assertEqual(bekle.call_count, 2)

    def test_otomatik_saldiri_mermi_azalmasiyla_dogrulanir(self):
        class SahteDOM:
            def calistir(self, _javascript, _sayfa=None):
                return {"stok": "99.000", "durdur": False}

        self.assertTrue(otomasyon.uzay_saldirisi_basladi_mi(SahteDOM(), 100000))

    def test_mermi_uretilemezse_hesap_tekrar_farma_sokulmaz(self):
        class SahteHesap:
            oyun_adi = "TEST"
            kullanici_adi = "test"

        with patch.object(
            uzay_farmi.bot, "yasam_enerjisini_oku", return_value=10
        ), patch.object(
            uzay_farmi.bot,
            "uzay_normal_saldiri_yap",
            side_effect=otomasyon.LazerMermisiUretimHatasi("üretilemedi"),
        ) as farm:
            uzay_farmi.enerji_bitene_kadar_farm_yap(object(), SahteHesap())
        farm.assert_called_once()

    def test_telegrama_kisa_kazanc_mesajlari_gider(self):
        class SahteHesap:
            oyun_adi = "TEST"
            kullanici_adi = "test"

        with tempfile.TemporaryDirectory() as klasor, patch.object(
            otomasyon, "KAZANC_DB", Path(klasor) / "test.db"
        ), patch.object(otomasyon, "KAZANC_LOG", Path(klasor) / "test.jsonl"), patch.object(
            otomasyon, "telegrama_kazanc_gonder"
        ) as gonder:
            otomasyon.kazanc_kaydet(
                SahteHesap(), "Eyalet madeni", "10 adet KERESTE elde ettiniz."
            )
            self.assertIn("10 Kereste", gonder.call_args.args[0])
            self.assertNotIn("elde ettiniz", gonder.call_args.args[0])
            self.assertTrue(gonder.call_args.kwargs["yalniz_uretim"])
            gonder.reset_mock()
            otomasyon.kazanc_kaydet(
                SahteHesap(),
                "Uzay Farmı",
                "2 adet aurorium ve 3 Exp kazandınız.",
            )
            gonder.assert_called_once()
            self.assertIn("Aurorium", gonder.call_args.args[0])
            self.assertIn("Deneyim: 3 XP", gonder.call_args.args[0])
            self.assertTrue(gonder.call_args.kwargs["yalniz_uzay"])

    def test_fabrika_ve_sanayi_telegram_etiketleri(self):
        class SahteHesap:
            oyun_adi = "TEST"
            kullanici_adi = "test"

        with tempfile.TemporaryDirectory() as klasor, patch.object(
            otomasyon, "KAZANC_DB", Path(klasor) / "test.db"
        ), patch.object(otomasyon, "KAZANC_LOG", Path(klasor) / "test.jsonl"), patch.object(
            otomasyon, "telegrama_kazanc_gonder"
        ) as gonder:
            otomasyon.kazanc_kaydet(
                SahteHesap(), "Eyalet fabrikası", "1174 adet ürün deponuza aktarıldı."
            )
            self.assertIn("1174 Fabrika Ürünü", gonder.call_args.args[0])
            self.assertTrue(gonder.call_args.kwargs["yalniz_uretim"])
            gonder.reset_mock()
            otomasyon.kazanc_kaydet(
                SahteHesap(), "Eyalet sanayisi", "20 adet ürün deponuza aktarıldı."
            )
            self.assertIn("20 Sanayi Parçası", gonder.call_args.args[0])
            self.assertTrue(gonder.call_args.kwargs["yalniz_uretim"])

    def test_noname_surecinin_cikis_kodu_dogrulanir(self):
        basarili = subprocess.Popen([sys.executable, "-c", "raise SystemExit(0)"])
        otomasyon.noname_botunun_bitmesini_bekle(basarili, saniye=5)
        hatali = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"])
        with self.assertRaises(RuntimeError):
            otomasyon.noname_botunun_bitmesini_bekle(hatali, saniye=5)

    def test_captcha_yoksa_noname_baslatilmaz(self):
        class SahteDOM:
            def calistir(self, _javascript):
                return False

        with patch.object(otomasyon, "noname_botunu_baslat") as baslat, patch.object(
            otomasyon.time, "sleep"
        ):
            otomasyon.noname_calistir_ve_bekle(SahteDOM(), object())
        baslat.assert_not_called()

    def test_captcha_varsa_noname_baslatilir(self):
        class SahteDOM:
            def calistir(self, _javascript):
                return True

        surec = object()
        with patch.object(otomasyon, "noname_botunu_baslat", return_value=surec) as baslat, patch.object(
            otomasyon, "noname_botunun_bitmesini_bekle"
        ) as bekle, patch.object(otomasyon, "tam_ekrani_garantile"):
            otomasyon.noname_calistir_ve_bekle(SahteDOM(), object())
        baslat.assert_called_once_with()
        bekle.assert_called_once_with(surec)


if __name__ == "__main__":
    unittest.main()
