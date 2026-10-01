# AD5X Camera Manager

Менеджер нескольких камер для **Flashforge Adventurer 5X (AD5X) + Z-Mod**.

> Текущий development baseline: **0.1.9-beta**. Код камер основан на физически проверенной ветке 0.1.7-beta; в 0.1.9-beta установка и обновление переведены на штатную git/plugin-схему Z-Mod.

[English](README.md)

## Возможности

- несколько USB UVC-камер одновременно;
- привязка по VID/PID, serial и USB path вместо зависимости только от `/dev/videoN`;
- отбрасывание metadata-node и внутреннего `felix-vdec`;
- `mjpg_streamer`, отдельные resolution/FPS/buffers/HTTP port для каждой камеры;
- проверенный sensor-level разворот штатной OV3660 на 180°;
- Creality Nebula CCX2F3298 принудительно удерживается в цветном DAY-режиме: проверенный UVC XU control + watchdog каждые 60 секунд;
- веб-интерфейс `http://IP_ПРИНТЕРА:8095/` с живыми превью;
- CPU/load/RAM и измерение фактического FPS;
- отдельные логи и автоматическое восстановление камер;
- основная камера на `:8080` для совместимости с Z-Mod;
- синхронизация камер в Fluidd/Moonraker с выбором MJPEG / Adaptive MJPEG / UV4L-MJPEG;
- Camera Manager можно добавить во Fluidd как HTTP Page;
- обновление через git/Moonraker Update Manager без ручной распаковки ZIP.

## Правильная структура для Z-Mod

Git-репозиторий и изменяемые данные разделены:

```text
/opt/config/mod_data/plugins/ad5x_camera_manager/   # git checkout
/opt/config/mod_data/ad5x_camera_manager/           # cameras.json, logs, backups, runtime
```

То есть обновления git не должны конфликтовать с `cameras.json` и логами.

Интеграция Klipper добавляется в рекомендованный Z-Mod файл `mod_data/user.cfg`. В `printer.cfg` плагин больше ничего не дописывает, поэтому `SAVE_CONFIG` остаётся последним блоком файла.

## Первая установка на AD5X

Через SSH:

```sh
chroot /usr/data/.mod/.zmod/
cd /opt/config/mod_data/plugins/
git clone https://github.com/genrudko/ad5x-camera-manager.git ad5x_camera_manager
cd ad5x_camera_manager
sh install.sh
```

После установки, когда принтер свободен:

```gcode
FIRMWARE_RESTART
```

Один раз перезапусти Moonraker или весь принтер, чтобы в **Fluidd → Обновление программного обеспечения** появилась запись `ad5x_camera_manager`.

`install.sh` при отсутствии записи сам добавляет в `mod_data/user.moonraker.conf`:

```ini
[update_manager ad5x_camera_manager]
type: git_repo
channel: dev
path: /opt/config/mod_data/plugins/ad5x_camera_manager
origin: https://github.com/genrudko/ad5x-camera-manager.git
is_system_service: False
primary_branch: main
```

## Обновление

После первичной установки обновляемся штатно через **Fluidd → Обновление программного обеспечения**. При обновлении Z-Mod вызывает `update.sh`; пользовательский `cameras.json`, логи и backup не перезаписываются.

## Отключение

Из каталога репозитория:

```sh
sh uninstall.sh
```

Скрипт останавливает Camera Manager, убирает только наш include из `mod_data/user.cfg`, восстанавливает исходный `START` штатной камеры и **сохраняет** камеры/логи/backups.

## Текущий статус

Проект пока beta. Две камеры, reboot persistence и recovery тестируются на реальном AD5X; перед production-статусом ещё нужен полноценный print soak с двумя активными камерами.

Файлы `/usr/data/zmod/...` плагин не патчит.

## Лицензия

Лицензия проекта пока не выбрана.
