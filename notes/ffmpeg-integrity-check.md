# FFmpeg Integrity Check Commands

## Базовая проверка MKV файлов

### Software Decoding (максимальная проверка)
```bash
time ffmpeg -xerror -err_detect explode -skip_frame nokey -i /path/to/file.mkv -map 0:v -f null -
```

**Опции:**
- `-xerror` — выход при ошибке
- `-err_detect explode` — агрессивное обнаружение ошибок
- `-skip_frame nokey` — проверять только ключевые кадры (быстрее)
- `-map 0:v` — только видео поток
- `-f null -` — декодировать без записи
- `time` — показать общее время выполнения

**Вывод:** ffmpeg показывает fps, speed, прогресс + итоговое время (real/user/sys)

---

## Hardware Decoding (Intel Quick Sync / VAAPI)

### Для систем с Intel GPU (Apollo Lake и новее)

**Проверка поддержки VAAPI:**
```bash
vainfo
```

Должен показать профили: `VAProfileH264Main`, `VAProfileHEVCMain`, `VAProfileVP9Profile0`

**Команда с VAAPI (работает на headless системах):**
```bash
time ffmpeg -xerror -init_hw_device vaapi=va:/dev/dri/card0 -hwaccel vaapi -hwaccel_device va -hwaccel_output_format vaapi -i /path/to/file.mkv -map 0:v -f null -
```

**Альтернатива (если card0 не работает):**
```bash
time ffmpeg -xerror -init_hw_device vaapi=va:/dev/dri/renderD128 -hwaccel vaapi -hwaccel_device va -hwaccel_output_format vaapi -i /path/to/file.mkv -map 0:v -f null -
```

**Опции:**
- `-init_hw_device vaapi=va:/dev/dri/card0` — инициализация VAAPI устройства
- `-hwaccel vaapi` — использовать VAAPI для декодирования
- `-hwaccel_device va` — указать устройство для hwaccel
- `-hwaccel_output_format vaapi` — оставить кадры в GPU памяти

**Примечание:** VAAPI работает только с поддерживаемыми кодеками (H.264, H.265/HEVC, VP9). Для других кодеков ffmpeg автоматически переключится на software decoding.

---

## Диагностика проблем с VAAPI

### Проверить наличие Intel GPU устройств:
```bash
ls -la /dev/dri/
```
Должны быть: `card0`, `renderD128`

### Проверить загружен ли драйвер i915:
```bash
lsmod | grep i915
```

### Проверить модель процессора:
```bash
cat /proc/cpuinfo | grep "model name" | head -1
```

### Установить драйверы VAAPI (Debian/Ubuntu):
```bash
sudo apt install intel-media-va-driver vainfo
```

Для старых систем:
```bash
sudo apt install i965-va-driver vainfo
```

### Проверить права доступа:
```bash
id
```
Пользователь должен быть в группах `video` и `render`:
```bash
sudo usermod -aG video,render $USER
# Перелогиниться или:
newgrp video
```

---

## Сравнение производительности

**Software decoding:**
- Полная проверка всех ошибок
- Медленнее (speed ~1x)
- Работает с любыми кодеками

**Hardware decoding (VAAPI):**
- Быстрее (speed может быть 5-10x)
- Меньше нагрузка на CPU
- Работает только с H.264, HEVC, VP9
- Может пропустить некоторые мелкие ошибки битстрима

---

## Источник команд

Команды взяты из [`operations/integrity_checker.py`](../operations/integrity_checker.py:376) — метод `_ffmpeg_check()`.

Оригинальная команда использует `ionice` и `nice` для минимального приоритета:
```bash
ionice -c3 nice -n19 ffmpeg -v error -xerror -err_detect explode -skip_frame nokey -i filepath -map 0:v -f null -