[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License][license-shield]][license]
[![Support author][donate-tinkoff-shield]][donate-tinkoff]
[![Support author][donate-boosty-shield]][donate-boosty]

[license-shield]: https://img.shields.io/static/v1?label=Лицензия&message=MIT&color=orange&logo=license
[license]: https://opensource.org/licenses/MIT

[donate-tinkoff-shield]: https://img.shields.io/static/v1?label=Поддержать+автора&message=Тинькофф&color=yellow
[donate-tinkoff]: https://www.tinkoff.ru/cf/3dZPaLYDBAI

[donate-boosty-shield]: https://img.shields.io/static/v1?label=Поддержать+автора&message=Boosty&color=red
[donate-boosty]: https://boosty.to/dentra

# Интеграция Кварта-С для Home Assistant

Интеграция позволяет получить доступ к информации о переданных показателей счетчиков [Кварта-С](http://www.kvarta-c.ru/voda.php), а так же предоставляет сервис обновления показаний.

## Установка
* Откройте HACS->Интеграции->(меню "три точки")->Пользовательские репозитории
* Добавьте пользовательский репозиторий `dentra/ha-kvarta-c` в поле репозиторий, в поле Категория выберете `Интеграция`

## Настройка
* Откройте Конфигурация->Устройсва и службы->Добавить интеграцию
* В поисковой строке введите `kvartac` и выберети интеграцию `Kvarta-C`
* Введите данные организации, лицевого счета и пароль

## Использование

В зависимости от данных лицевого счта, будут созданы соотвествующие сенсоры.

По-умолчанию, обновление данных происходит раз в 12 часов, Вы всегда можете изменить этот парамтр в настройках службы.

## Изменение значений

Используйте визульный редактор и службу `kvartac.update_value`

Или воспользуйтесь примером ниже:
```yaml
service: kvartac.update_value
data:
  entity_id: sensor.0000_000000000_service1counter1_value
  value: 48
```

## Ваша благодарность

Если этот проект оказался для вас полезен и/или вы хотите поддержать его дальнейше развитие, то всегда можно оставить вашу благодарность [переводом на карту](https://www.tinkoff.ru/cf/3dZPaLYDBAI), [разовыми донатом или подпиской на boosty](https://boosty.to/dentra).