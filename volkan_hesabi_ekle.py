"""Volkan Arslan hesabını parola ekranda görünmeden otomasyona kaydeder."""

from getpass import getpass

from hesap_hafizasi import hesap_hafizasi


def main() -> None:
    mevcut = next(
        (h for h in hesap_hafizasi.tumunu_getir() if h.oyun_adi.casefold().strip() == "volkan arslan"),
        None,
    )
    if mevcut:
        print("Volkan Arslan hesabı zaten kayıtlı.")
        return

    kullanici_adi = input("Volkan Arslan giriş e-postası: ").strip()
    sifre = getpass("Volkan Arslan parolası (ekranda görünmez): ")
    if not kullanici_adi or not sifre:
        raise SystemExit("E-posta ve parola boş olamaz.")
    hesap = hesap_hafizasi.ekle(kullanici_adi, sifre)
    hesap_hafizasi.oyun_adi_guncelle(hesap.kullanici_adi, "Volkan Arslan")
    print("Volkan Arslan opsiyonel hesap olarak kaydedildi.")


if __name__ == "__main__":
    main()
