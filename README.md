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

Интеграция позволяет получить доступ к информации о переданных показаниях счетчиков [Кварта-С](https://www.kvarta-c.ru/voda.php), а также предоставляет сервис передачи новых показаний.

Требуется Home Assistant 2025.10 или новее.

## Установка

- Откройте HACS->Интеграции->(меню "три точки")->Пользовательские репозитории
- Добавьте пользовательский репозиторий `dentra/ha-kvarta-c` в поле Репозиторий, в поле Категория выберите `Интеграция`

## Настройка

- Откройте Настройки->Устройства и службы->Добавить интеграцию
- В поисковой строке введите `kvartac` и выберите интеграцию `Kvarta-C`
- Введите номер организации, лицевой счет и пароль

Если сохраненный пароль перестанет подходить, Home Assistant предложит ввести новый, удалять и добавлять интеграцию заново не нужно.

## Использование

В зависимости от данных лицевого счета будут созданы соответствующие сенсоры счетчиков и сенсор с датой предыдущих показаний.

По умолчанию обновление данных происходит раз в 12 часов. Этот параметр, как и остальные, можно изменить в настройках службы.

## Передача показаний

Используйте визуальный редактор и действие `kvartac.update_value`.

Или воспользуйтесь примером ниже:

```yaml
action: kvartac.update_value
target:
  entity_id: sensor.0000_000000000_service1counter1
data:
  value: 48
```

Новое значение должно быть больше предыдущего.

## Ваша благодарность

Если этот проект оказался для вас полезен и/или вы хотите поддержать его дальнейшее развитие, то всегда можно оставить вашу благодарность [переводом на карту](https://www.tinkoff.ru/cf/3dZPaLYDBAI), [разовым донатом или подпиской на boosty](https://boosty.to/dentra).