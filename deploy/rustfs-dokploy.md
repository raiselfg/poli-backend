# RustFS 1.0.6 в Dokploy

Настройка выполняется в Dokploy и веб-консоли RustFS. Понадобятся два DNS-имени для RustFS и приложение backend в Dokploy. Для примеров ниже используются `s3.example.com` и `rustfs.example.com`. Замени их своими доменами.

## 1. Разверни RustFS в Dokploy

1. Создай сервис **Docker Compose**, выбери источник **Raw** и вставь конфигурацию ниже.
2. Во вкладке **Environment** этого сервиса задай `RUSTFS_ACCESS_KEY` для администратора хранилища и `RUSTFS_SECRET_KEY` с длинным случайным секретом.
3. Направь DNS-записи обоих доменов на сервер Dokploy. Во вкладке **Domains** добавь оба домена для сервиса `rustfs` и включи HTTPS.
4. Сохрани настройки и нажми **Deploy**.

```yaml
services:
  rustfs:
    image: rustfs/rustfs:1.0.6
    command: ["/data"]
    restart: unless-stopped
    environment:
      RUSTFS_ACCESS_KEY: ${RUSTFS_ACCESS_KEY:?Set RUSTFS_ACCESS_KEY}
      RUSTFS_SECRET_KEY: ${RUSTFS_SECRET_KEY:?Set RUSTFS_SECRET_KEY}
      RUSTFS_REGION: eu-central-1
      RUSTFS_ADDRESS: 0.0.0.0:9000
      RUSTFS_CONSOLE_ADDRESS: 0.0.0.0:9001
      RUSTFS_CONSOLE_ENABLE: "true"
    volumes:
      - rustfs-data:/data

volumes:
  rustfs-data:
```

| Домен | Container Port | Назначение |
|---|---:|---|
| `s3.example.com` | `9000` | S3 API для backend и прямые ссылки на изображения |
| `rustfs.example.com` | `9001` | Веб-консоль RustFS |

[Переменные Compose в Dokploy](https://docs.dokploy.com/docs/core/docker-compose) · [Настройка доменов](https://docs.dokploy.com/docs/core/docker-compose/domains)

## 2. Создай бакеты и настрой чтение каталога

1. Открой `https://rustfs.example.com` и войди ключами администратора RustFS. Если появится **Server Configuration**, укажи `https://s3.example.com`.
2. Открой **Browser** слева и нажми **Create Bucket**. Создай `poli-public` для изображений каталога и `poli-private` для вложений заявок. Для `poli-private` оставь режим **Private**.
3. Вернись к списку бакетов через **Browser**. В строке `poli-public` нажми **Settings** в колонке **Actions**. Этот экран также доступен по пути `/buckets?bucket=poli-public` на домене веб-консоли.
4. Открой **Access & Sharing → Access Policy → Edit**, выбери **Custom**, вставь JSON ниже в **Policy Content** и нажми **Save Policy**.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::poli-public/catalog/*"
    }
  ]
}
```

Это правило разрешает анонимное чтение объектов под `catalog/`. [Политики бакетов RustFS](https://docs.rustfs.com/en/administration/data/bucket/policy)

## 3. Создай пользователя backend и назначь ему права

1. В левой колонке RustFS в разделе **Identity** открой **Policies** и нажми кнопку добавления политики. Укажи имя `poli-backend`, вставь в редактор содержимое файла [rustfs-runtime-policy.json](rustfs-runtime-policy.json) и сохрани политику.
2. Открой **Users** в той же колонке и нажми кнопку добавления пользователя. В поле **Username** или **Access Key** впиши `POLIBACKEND`. В поле **Password** или **Secret Key** задай отдельный случайный секрет и сохрани его.
3. Выбери `poli-backend` в поле **Policy** и сохрани пользователя. Если в форме создания этого поля нет, открой созданного пользователя и назначь ему политику в его настройках.
4. Проверь в списке **Users**, что `POLIBACKEND` включён и ему назначена `poli-backend`.

Имя пользователя `POLIBACKEND` служит идентификатором S3-ключа. Второе значение пары — секрет, который ты задал при создании пользователя. [Пользователи и политики RustFS](https://docs.rustfs.com/en/security-compliance/iam/policies)

Если выбрал другие имена бакетов, подставь их в политику `poli-backend`, политику бакета каталога и переменные backend.

## 4. Запусти backend в Dokploy

Открой **Environment** у приложения backend. Добавь или обнови следующие переменные, подставив свой домен S3 API и секрет `POLIBACKEND`. Сохрани настройки и нажми **Deploy**.

```dotenv
S3_ENDPOINT_URL=https://s3.example.com
S3_PUBLIC_BUCKET=poli-public
S3_PRIVATE_BUCKET=poli-private
S3_ACCESS_KEY_ID=POLIBACKEND
S3_SECRET_ACCESS_KEY=<секрет пользователя POLIBACKEND>
IS_REGISTER_DISABLE=true
```

Для production также укажи `APP_ENV=production`, `ALLOW_INSECURE_COOKIES=false` и HTTPS-адреса фронтенда в `ALLOWED_ORIGINS`. Настройки PostgreSQL и остальные переменные перечислены в [.env.example](../.env.example). При старте backend проверяет доступность обоих бакетов.

## 5. Проверь в браузере

1. Загрузи изображение через админку и открой его прямую ссылку S3 в приватном окне браузера. Изображение должно открыться.
2. Отправь заявку с вложением. В том же приватном окне прямая S3-ссылка на объект в `poli-private` должна вернуть `403`, а ссылка `/api/v1/admin/requests/<id>/file` на домене backend должна вернуть `401`.
3. Войди в админку и открой ссылку скачивания через backend. Файл должен скачаться.
