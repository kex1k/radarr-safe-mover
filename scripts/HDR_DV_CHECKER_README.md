# HDR and Dolby Vision Checker Scripts

Два скрипта для проверки медиафайлов на наличие HDR и Dolby Vision метаданных.

## Особенности

- Рекурсивный обход директорий
- Классификация файлов на 4 категории:
  - **DV + HDR10** - Dolby Vision с полными HDR10 метаданными
  - **HDR10** - Стандартный HDR10
  - **HDR** - Любой HDR (включая HLG)
  - **SDR** - Standard Dynamic Range (без HDR)
- Сортировка результатов по пути файла
- Подробная статистика

## Скрипты

### 1. Python версия (`check_hdr_dv.py`)

Более функциональная версия с дополнительными возможностями.

**Требования:**
- Python 3.6+
- ffprobe (из пакета ffmpeg)

**Использование:**
```bash
# Базовая проверка
./check_hdr_dv.py /path/to/movies

# Подробный вывод с прогрессом
./check_hdr_dv.py /path/to/movies --verbose

# Показать все файлы в результатах
./check_hdr_dv.py /path/to/movies --details

# Сохранить результаты в файл
./check_hdr_dv.py /path/to/movies --output results.txt

# Все опции вместе
./check_hdr_dv.py /path/to/movies --verbose --details --output results.txt
```

**Опции:**
- `directory` - Директория для сканирования (обязательно)
- `-v, --verbose` - Показывать детальный прогресс
- `-d, --details` - Показывать все файлы в результатах
- `-o, --output FILE` - Сохранить результаты в файл

### 2. Shell версия (`check_hdr_dv.sh`)

Быстрая версия для простого использования.

**Требования:**
- bash
- ffprobe (из пакета ffmpeg)
- jq (для парсинга JSON)
- bc (для расчетов)

**Использование:**
```bash
# Базовая проверка
./check_hdr_dv.sh /path/to/movies

# Сохранить детальные результаты
./check_hdr_dv.sh /path/to/movies --save
```

## Критерии классификации

### DV + HDR10
- `side_data_list` содержит `"Dolby Vision RPU"`
- `color_space: "bt2020nc"`
- `color_primaries: "bt2020"`
- `color_transfer: "smpte2084"`

### HDR10
- `color_space: "bt2020nc"` или `"bt2020c"`
- `color_primaries: "bt2020"`
- `color_transfer: "smpte2084"`

### HDR
- Любое из:
  - `color_space` содержит `"bt2020"`
  - `color_primaries` содержит `"bt2020"`
  - `color_transfer` содержит `"smpte2084"`
  - `color_transfer` содержит `"arib-std-b67"` (HLG)

### SDR
- Все остальные файлы (включая файлы с ошибками чтения)

## Поддерживаемые форматы

- `.mkv`
- `.mp4`
- `.avi`
- `.m4v`
- `.ts`
- `.mov`
- `.webm`

## Пример вывода

```
================================================================================
MEDIA FILES CLASSIFICATION
================================================================================

DV + HDR10 (2 files):
----------------------------------------
  /movies/Spider-Man.No.Way.Home.2021.4K.DoVi.mkv
  /movies/Avengers.Endgame.2019.4K.DV.mkv

HDR10 (5 files):
----------------------------------------
  /movies/Movie1.2021.4K.HDR.mkv
  /movies/Movie2.2021.4K.HDR10.mkv
  /movies/Movie3.2021.4K.HDR.mkv
  /movies/Movie4.2021.4K.HDR.mkv
  /movies/Movie5.2021.4K.HDR.mkv

HDR (1 files):
----------------------------------------
  /movies/Movie6.2021.4K.HLG.mkv

SDR (10 files):
----------------------------------------
  /movies/Movie7.2021.1080p.mkv
  /movies/Movie8.2021.1080p.mkv
  ... and 8 more files

================================================================================
SUMMARY: 18 total files
  DV + HDR10:   2 ( 11.1%)
  HDR10:        5 ( 27.8%)
  HDR:          1 (  5.6%)
  SDR:         10 ( 55.6%)
================================================================================
```

## Установка зависимостей

### Ubuntu/Debian:
```bash
sudo apt update
sudo apt install ffmpeg jq bc
```

### CentOS/RHEL:
```bash
sudo yum install epel-release
sudo yum install ffmpeg jq bc
```

### macOS:
```bash
brew install ffmpeg jq bc
```

## Производительность

- Python версия: ~2-3 файла в секунду
- Shell версия: ~1-2 файла в секунду
- Зависит от размера файлов и скорости диска

## Ограничения

- Только видеофайлы (аудио не проверяется)
- Требуется ffprobe в PATH
- macOS metadata файлы (._*) игнорируются
- Файлы с ошибками чтения классифицируются как SDR

## Troubleshooting

### "ffprobe not found"
Установите ffmpeg:
```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

### "jq not found" (только для shell версии)
```bash
# Ubuntu/Debian
sudo apt install jq

# macOS
brew install jq
```

### Медленная работа
- Используйте SSD для медиафайлов
- Ограничьте сканирование конкретными директориями
- Используйте Python версию для лучшей производительности

## Лицензия

MIT License