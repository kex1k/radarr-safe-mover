# Path Mapping Guide

## Проблема

Когда Radarr работает в Docker контейнере, он возвращает пути внутри контейнера (например `/media/movies_ssd`), но скрипт `fix_movie_directories.py` запускается на хосте, где реальные пути могут быть другими (например `/mnt/storage/movies_ssd`).

## Решение

Используйте маппинг путей в конфигурационном файле `data/config.json`.

## Настройка

Откройте файл `data/config.json` и добавьте секцию `path_mappings`:

```json
{
  "radarr_host": "localhost",
  "radarr_port": "7878",
  "radarr_api_key": "your-api-key-here",
  "ssd_root_folder": "/media/movies_ssd",
  "hdd_root_folder": "/media/movies_hdd",
  "path_mappings": [
    {
      "docker": "/media/movies_ssd",
      "host": "/mnt/storage/movies_ssd"
    },
    {
      "docker": "/media/movies_hdd",
      "host": "/mnt/storage/movies_hdd"
    }
  ]
}
```

## Параметры

- **`docker`** - путь внутри Docker контейнера (как его видит Radarr)
- **`host`** - реальный путь на хосте (где физически лежат файлы)

## Как это работает

1. Скрипт получает от Radarr путь в формате Docker: `/media/movies_ssd/Movie.2024/movie.mkv`
2. Используя маппинг, конвертирует его в путь хоста: `/mnt/storage/movies_ssd/Movie.2024/movie.mkv`
3. Выполняет операции с файлами на хосте
4. При обновлении Radarr конвертирует путь обратно в формат Docker

## Примеры конфигураций

### Пример 1: Стандартный Docker Compose

Docker volumes:
```yaml
volumes:
  - /mnt/storage/movies_ssd:/media/movies_ssd
  - /mnt/storage/movies_hdd:/media/movies_hdd
```

Config.json:
```json
{
  "path_mappings": [
    {
      "docker": "/media/movies_ssd",
      "host": "/mnt/storage/movies_ssd"
    },
    {
      "docker": "/media/movies_hdd",
      "host": "/mnt/storage/movies_hdd"
    }
  ]
}
```

### Пример 2: Synology NAS

Docker volumes:
```yaml
volumes:
  - /volume1/movies/ssd:/movies_ssd
  - /volume1/movies/hdd:/movies_hdd
```

Config.json:
```json
{
  "ssd_root_folder": "/movies_ssd",
  "hdd_root_folder": "/movies_hdd",
  "path_mappings": [
    {
      "docker": "/movies_ssd",
      "host": "/volume1/movies/ssd"
    },
    {
      "docker": "/movies_hdd",
      "host": "/volume1/movies/hdd"
    }
  ]
}
```

### Пример 3: Без Docker (локальный Radarr)

Если Radarr запущен локально (не в Docker), маппинг не нужен:

```json
{
  "radarr_host": "localhost",
  "radarr_port": "7878",
  "radarr_api_key": "your-api-key-here",
  "ssd_root_folder": "/mnt/storage/movies_ssd",
  "hdd_root_folder": "/mnt/storage/movies_hdd",
  "path_mappings": []
}
```

## Проверка конфигурации

Запустите скрипт в режиме dry-run для проверки:

```bash
python scripts/fix_movie_directories.py --dry-run
```

Скрипт покажет:
- Какие маппинги используются
- Как пути конвертируются (Docker → Host)
- Какие изменения будут сделаны

Пример вывода:
```
SSD Root Folder (Docker): /media/movies_ssd
SSD Root Folder (Host):   /mnt/storage/movies_ssd
Path mappings configured: 2 mapping(s)
  [1] /media/movies_ssd -> /mnt/storage/movies_ssd
  [2] /media/movies_hdd -> /mnt/storage/movies_hdd
```

## Устранение проблем

### Ошибка: "SSD root folder does not exist on host"

Проверьте:
1. Правильность путей в `path_mappings`
2. Что директория действительно существует на хосте
3. Права доступа к директории

### Ошибка: "Path mapping X missing 'docker' or 'host' key"

Убедитесь, что каждый маппинг содержит оба ключа:
```json
{
  "docker": "/path/in/docker",
  "host": "/path/on/host"
}
```

### Предупреждение: "No path mappings configured"

Если вы видите это предупреждение и Radarr работает в Docker, добавьте маппинги в конфиг.

## Дополнительная информация

- Маппинги применяются в порядке их определения
- Первый подходящий маппинг используется
- Если маппинг не найден, используется оригинальный путь
- Пути нормализуются (убираются trailing slashes)