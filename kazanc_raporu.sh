#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -c "import otomasyon; otomasyon.kazanc_raporunu_yazdir()"
