# Ticarion BOT2

Ticarion otomasyon botu. Bu repo Windows ve özellikle macOS üzerinde farklı cihaz/emulator kurulumlarına daha kolay taşınması için göreli yollar ve ortam değişkenleriyle hazırlanmıştır.

## Güvenli dosyalar

Gerçek `hesaplar.json`, veritabanı ve log dosyaları repoya eklenmez. Örnek dosyadan kopyalayın:

```bash
cp hesaplar.example.json hesaplar.json
```

Sonra `hesaplar.json` içindeki kullanıcı adı/şifreleri kendi cihazınızda doldurun.

## Kurulum - macOS

```bash
cd BOT2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
brew install android-platform-tools
```

BlueStacks veya Android emulator açık olmalı. ADB cihazını kontrol edin:

```bash
adb devices
```

Mac'te cihaz serial'ı farklı çıkıyorsa `.env.example` içindeki ayarları terminalde export edin. Örneğin:

```bash
export TICARION_ADB_PATH=adb
export TICARION_ADB_ADDRESS=
export TICARION_BLUESTACKS_PATH=/Applications/BlueStacks.app
```

`TICARION_ADB_ADDRESS` boş bırakılırsa CAPTCHA yardımcısı ilk görünen ADB cihazını kullanır.

Çalıştırma:

```bash
chmod +x baslat.sh baslat_uzay.sh kazanc_raporu.sh
./baslat.sh
```

## Kurulum - Windows

```bat
cd BOT2
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
BASLAT.bat
```

BlueStacks farklı yerdeyse ortam değişkeniyle belirtin:

```bat
set TICARION_ADB_PATH=C:\Program Files\BlueStacks_nxt\HD-Adb.exe
set TICARION_BLUESTACKS_PATH=C:\Program Files\BlueStacks_nxt\HD-Player.exe
set TICARION_ADB_ADDRESS=127.0.0.1:5565
```

## Önemli macOS notu

Mac'te Windows'taki pencere bulma/F11 tam ekran API'si yoktur. Bot ADB ve Chrome üzerinden çalışır; BlueStacks/emulator penceresinin açık ve Chrome'un erişilebilir olması gerekir.
