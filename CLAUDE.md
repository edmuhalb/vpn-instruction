# VPN Instruction & Self-Service Portal

Сайт для раздачи VPN-конфигов семье/друзьям через AmneziaVPN (AmneziaWG).
Пользователь вводит имя → получает персональный `vpn://` URL → вставляет в приложение.

## Деплой

- **Хостинг фронта/прокси:** Vercel
  - Продакшн URL: https://edward-vpn-instruction.vercel.app
  - Репозиторий: https://github.com/edmuhalb/vpn-instruction
  - Автодеплой по `git push` в `main`
- **VPN-сервер (VPS):** `194.226.169.15` (Ubuntu 22.04)
  - Логин: `root`, доступ через SSH или VNC-консоль хостера
  - AmneziaVPN крутится в Docker: контейнеры `amnezia-awg2` и `amnezia-xray`
  - Конфиг WG: `/opt/amnezia/awg/awg0.conf` (внутри контейнера `amnezia-awg2`)
  - Подсеть: `10.8.1.0/24`, порт: `37930`

## Архитектура

```
Браузер → edward-vpn-instruction.vercel.app
          ├─ / (index.html)          — инструкция + форма получения конфига
          ├─ /admin.html             — админка (список/удаление)
          ├─ /api/create  (Vercel)   — прокси → VPS (POST создаёт пир)
          └─ /api/users   (Vercel)   — прокси → VPS (GET список / DELETE пир)
                    │
                    ↓ HTTP (т.к. Vercel HTTPS не может в MixedContent)
          VPS: http://194.226.169.15:8765
          └─ Python API (api.py, systemd: vpn-api.service)
                └─ docker exec amnezia-awg2 awg/awg set ...
```

Vercel-функции нужны как прокси потому что фронт на HTTPS, а у VPS нет TLS.

## Файлы проекта

| Файл | Назначение |
|---|---|
| `index.html` | Лендинг + форма получения конфига |
| `admin.html` | Админка: список пользователей, удаление |
| `api/create.js` | Vercel proxy → POST http://VPS:8765/create |
| `api/users.js` | Vercel proxy → GET/DELETE http://VPS:8765/users |
| `api.py` | Основной Python API на VPS (http.server) |
| `vpn-api.service` | systemd unit для `api.py` |
| `vercel.json`, `package.json` | Конфиги Vercel |

## Конфигурация

- **Админ-пароль:** `11111111` (переменная `API_SECRET` в `api.py`, и захардкожен в `api/*.js`)
- **AmneziaWG параметры** (Jc/Jmin/Jmax/S1-S4/H1-H4) захардкожены в `api.py` — скопированы с сервера.
- **Server public key** — вычисляется из `PrivateKey` в `awg0.conf` через `awg pubkey`.
- **Preshared key** — общий на всех пиров (берётся из первого `[Peer]` блока в конфиге).

## API endpoints на VPS (порт 8765)

Все требуют заголовок `X-Secret: 11111111`.

- `POST /create` `{name}` → `{config, url, name}` — создаёт пир, возвращает `.conf` и `vpn://base64(json)` URL
- `GET  /users` → `{users: [{name, ip, pubkey, active}]}` — список всех пиров
- `DELETE /users` `{pubkey}` → `{ok: true}` — удаляет пир из live WG и из файла
- `GET  /logs` → `{logs: [...]}` — последние 50 записей (in-memory ring buffer)

## Как обновить API на сервере

```bash
# Через SSH или VNC-консоль:
curl -o /opt/vpn-api/api.py https://raw.githubusercontent.com/edmuhalb/vpn-instruction/main/api.py
systemctl restart vpn-api
systemctl status vpn-api
journalctl -u vpn-api -n 30 --no-pager
```

## Известные нюансы

- **Публичные ключи** содержат `+`, `=`, `/` — в HTML нельзя инлайнить в `onclick`, используем индекс массива в `window._users`.
- **Mixed Content** — фронт на HTTPS, VPS на HTTP, поэтому всё через Vercel-прокси.
- **Preview deploys** Vercel защищены Vercel Auth (403) — админка работает только на продакшн-домене.
- **IP-allocation** — следующий свободный IP в `10.8.1.x` ищется парсингом `AllowedIPs` в конфиге.
- **Удаление** использует `awg set peer PUBKEY remove` для live + вычищает `[Peer]` блок из файла.

## Что планировалось дальше

1. HTTPS на VPS (Caddy/nginx + Let's Encrypt) — чтобы убрать Vercel-прокси.
2. Оплата (Stripe/ЮКасса) — автовыдача конфига после платежа.
3. Срок действия конфигов, автоотключение по неоплате.
4. Миграция секрета из захардкоженного в env vars Vercel.
