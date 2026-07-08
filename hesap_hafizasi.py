from dataclasses import dataclass
import json
import os
from pathlib import Path


@dataclass(slots=True)
class Hesap:
    kullanici_adi: str
    sifre: str
    oyun_adi: str = ""


class HesapHafizasi:
    def __init__(self, dosya: str | Path | None = None) -> None:
        varsayilan = os.getenv("TICARION_HESAPLAR_JSON") or Path(__file__).with_name("hesaplar.json")
        self._dosya = Path(dosya) if dosya else Path(varsayilan).expanduser()
        self._hesaplar: dict[str, Hesap] = {}
        self._yukle()

    def _yukle(self) -> None:
        if not self._dosya.exists():
            return
        for kayit in json.loads(self._dosya.read_text(encoding="utf-8")):
            hesap = Hesap(**kayit)
            self._hesaplar[hesap.kullanici_adi] = hesap

    def _kaydet(self) -> None:
        veri = [
            {
                "kullanici_adi": hesap.kullanici_adi,
                "sifre": hesap.sifre,
                "oyun_adi": hesap.oyun_adi,
            }
            for hesap in self._hesaplar.values()
        ]
        self._dosya.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")

    def ekle(self, kullanici_adi: str, sifre: str) -> Hesap:
        kullanici_adi = kullanici_adi.strip()
        if not kullanici_adi:
            raise ValueError("Kullanıcı adı boş olamaz.")
        if kullanici_adi in self._hesaplar:
            raise ValueError("Bu kullanıcı adı zaten kayıtlı.")
        hesap = Hesap(kullanici_adi, sifre)
        self._hesaplar[kullanici_adi] = hesap
        self._kaydet()
        return hesap

    def getir(self, kullanici_adi: str) -> Hesap | None:
        return self._hesaplar.get(kullanici_adi)

    def oyun_adi_guncelle(self, kullanici_adi: str, oyun_adi: str) -> None:
        hesap = self.getir(kullanici_adi)
        if not hesap:
            raise ValueError("Hesap bulunamadı.")
        hesap.oyun_adi = oyun_adi.strip()
        self._kaydet()

    def sil(self, kullanici_adi: str) -> bool:
        silindi = self._hesaplar.pop(kullanici_adi, None) is not None
        if silindi:
            self._kaydet()
        return silindi

    def tumunu_getir(self) -> list[Hesap]:
        return list(self._hesaplar.values())

    def temizle(self) -> None:
        self._hesaplar.clear()
        self._kaydet()


hesap_hafizasi = HesapHafizasi()
