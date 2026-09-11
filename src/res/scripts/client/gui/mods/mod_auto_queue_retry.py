# -*- coding: utf-8 -*-

"""Grand Battle search helper by nidin, using random-queue retries.

The configured hotkey (F8 by default) starts the cycle for the vehicle
currently selected in the hangar.
If the visible waiting timer reaches the configured number of seconds, the mod leaves
the queue, waits for the dequeue confirmation, and enters it again.
Press the hotkey again to stop the cycle and leave the queue immediately.
"""

__author__ = 'nidin'
__version__ = '1.3.1'

import BigWorld
import Keys

from CurrentVehicle import g_currentVehicle
from PlayerEvents import g_playerEvents
from constants import QUEUE_TYPE
from gui import InputHandler, SystemMessages
from gui.prb_control.dispatcher import g_prbLoader
from gui.prb_control.settings import CTRL_ENTITY_TYPE


DEFAULT_HOTKEY = [Keys.KEY_F8]
MOD_LINKAGE = 'nidin.auto_queue_retry'
LEGACY_MOD_LINKAGE = 'local.auto_queue_retry'
DEFAULT_VISIBLE_TIMEOUT = 15
MIN_VISIBLE_TIMEOUT = 5
MAX_VISIBLE_TIMEOUT = 60
QUEUE_TIMER_OFFSET = 2.0
DEFAULT_REQUEUE_DELAY = 2.0
MIN_REQUEUE_DELAY = 1.0
MAX_REQUEUE_DELAY = 15.0
DEFAULT_MAX_RESTARTS = 20
MIN_MAX_RESTARTS = 5
MAX_MAX_RESTARTS = 100
RESTARTS_STEP = 5
SETTINGS_VERSION = 5
# onEnqueued arrives roughly two seconds before the visible waiting timer
# starts, so the internal callback includes QUEUE_TIMER_OFFSET.

_settings = {
    'enabled': True,
    'visibleTimeout': DEFAULT_VISIBLE_TIMEOUT,
    'requeueDelay': DEFAULT_REQUEUE_DELAY,
    'hotkey': DEFAULT_HOTKEY,
    'maxRestarts': DEFAULT_MAX_RESTARTS,
}

_active = False
_hotkeyHeld = False
_callbackID = None
_attempt = 0
_restarts = 0
_modsSettingsApi = None


def _log(message):
    print '[nidin.auto_queue_retry] %s' % message


def _notify(message, messageType=None):
    if messageType is None:
        messageType = SystemMessages.SM_TYPE.Information
    try:
        SystemMessages.pushMessage(message, type=messageType)
    except Exception as error:
        _log('notification failed: %r' % error)


def _cancelCallback():
    global _callbackID
    if _callbackID is not None:
        try:
            BigWorld.cancelCallback(_callbackID)
        except Exception:
            pass
        _callbackID = None


def _schedule(delay, callback):
    global _callbackID
    _cancelCallback()
    _callbackID = BigWorld.callback(delay, callback)


def _visibleTimeout():
    try:
        value = int(round(float(_settings.get(
            'visibleTimeout', DEFAULT_VISIBLE_TIMEOUT))))
    except (TypeError, ValueError):
        value = DEFAULT_VISIBLE_TIMEOUT
    return max(MIN_VISIBLE_TIMEOUT, min(MAX_VISIBLE_TIMEOUT, value))


def _queueTimeout():
    return float(_visibleTimeout()) + QUEUE_TIMER_OFFSET


def _requeueDelay():
    try:
        value = float(_settings.get('requeueDelay', DEFAULT_REQUEUE_DELAY))
    except (TypeError, ValueError):
        value = DEFAULT_REQUEUE_DELAY
    value = max(MIN_REQUEUE_DELAY, min(MAX_REQUEUE_DELAY, value))
    return round(value * 2.0) / 2.0


def _maxRestarts():
    try:
        value = float(_settings.get('maxRestarts', DEFAULT_MAX_RESTARTS))
    except (TypeError, ValueError):
        value = DEFAULT_MAX_RESTARTS
    value = max(MIN_MAX_RESTARTS, min(MAX_MAX_RESTARTS, value))
    return int(round(value / RESTARTS_STEP) * RESTARTS_STEP)


def _isEnabled():
    return bool(_settings.get('enabled', True))


def _isHotkeyPressed(event):
    keyset = _settings.get('hotkey') or DEFAULT_HOTKEY
    if _modsSettingsApi is not None:
        try:
            return bool(_modsSettingsApi.checkKeyset(keyset))
        except Exception as error:
            _log('hotkey check failed, using F8 fallback: %r' % error)
    return event.key == Keys.KEY_F8


def _getRandomQueueEntity():
    dispatcher = g_prbLoader.getDispatcher()
    if dispatcher is None:
        return (None, None)
    entity = dispatcher.getEntity()
    if entity is None or entity.getCtrlType() != CTRL_ENTITY_TYPE.PREQUEUE:
        return (dispatcher, None)
    if entity.getQueueType() != QUEUE_TYPE.RANDOMS:
        return (dispatcher, None)
    return (dispatcher, entity)


def _stop(message=None, leaveQueue=False, messageType=None):
    global _active
    _active = False
    _cancelCallback()

    if leaveQueue:
        _, entity = _getRandomQueueEntity()
        if entity is not None and entity.isInQueue():
            entity.exitFromQueue()

    if message:
        _notify(message, messageType)
    _log('stopped%s' % (': ' + message if message else ''))


def _enterQueue():
    global _callbackID, _attempt
    _callbackID = None
    if not _active:
        return

    dispatcher, entity = _getRandomQueueEntity()
    if dispatcher is None:
        _stop(u'Поиск ГС остановлен: диспетчер боёв ещё не готов.',
              messageType=SystemMessages.SM_TYPE.Warning)
        return
    if entity is None:
        _stop(u'Поиск ГС работает только в одиночном случайном бою.',
              messageType=SystemMessages.SM_TYPE.Warning)
        return
    if entity.isInQueue():
        _onEnqueued(QUEUE_TYPE.RANDOMS)
        return

    _attempt += 1
    _log('entering random queue, attempt %d, vehicle invID=%s' % (
        _attempt, g_currentVehicle.invID))
    if not dispatcher.doAction():
        _stop(u'Поиск ГС остановлен: кнопка «В бой» сейчас недоступна.',
              messageType=SystemMessages.SM_TYPE.Warning)


def _onQueueTimeout():
    global _callbackID, _restarts
    _callbackID = None
    if not _active:
        return

    _, entity = _getRandomQueueEntity()
    if entity is None:
        _stop(u'Поиск ГС остановлен: режим очереди изменился.',
              messageType=SystemMessages.SM_TYPE.Warning)
        return
    if not entity.isInQueue():
        return

    _restarts += 1
    _log('visible timer target reached; leaving queue for restart %d/%d' % (
        _restarts, _maxRestarts()))
    entity.exitFromQueue()


def _onEnqueued(queueType, *args):
    global _callbackID
    if not _active or queueType != QUEUE_TYPE.RANDOMS:
        return
    if _restarts >= _maxRestarts():
        _cancelCallback()
        _notify(u'Достигнут лимит %d перезапусков. Ожидаем бой без дальнейшей '
                u'отмены поиска.' % _maxRestarts())
        _log('restart limit reached; waiting in queue without timeout')
        return
    timeout = _queueTimeout()
    _log('queue confirmed; timeout scheduled for %.1f seconds '
         '(visible target: %d)' % (timeout, _visibleTimeout()))
    _schedule(timeout, _onQueueTimeout)


def _onDequeued(queueType, *args):
    if not _active or queueType != QUEUE_TYPE.RANDOMS:
        return
    delay = _requeueDelay()
    _log('dequeue confirmed; next attempt scheduled in %.1f seconds' % delay)
    _schedule(delay, _enterQueue)


def _onArenaCreated(*args):
    if _active:
        _stop(u'Бой найден. Поиск ГС завершён.')


def _onEnqueueFailure(queueType, errorCode, *args):
    if _active and queueType == QUEUE_TYPE.RANDOMS:
        _stop(u'Поиск ГС остановлен: сервер отклонил вход в очередь.',
              messageType=SystemMessages.SM_TYPE.Error)


def _onKickedFromQueue(queueType, reasonCode=None, *args):
    if _active and queueType == QUEUE_TYPE.RANDOMS:
        _stop(u'Поиск ГС остановлен: сервер исключил игрока из очереди.',
              messageType=SystemMessages.SM_TYPE.Error)


def _start():
    global _active, _attempt, _restarts
    if not _isEnabled():
        _notify(u'Поиск ГС отключён в настройках модификаций.',
                SystemMessages.SM_TYPE.Warning)
        return
    if not g_currentVehicle.isPresent() or not g_currentVehicle.invID:
        _notify(u'Поиск ГС: сначала выберите исправный танк в ангаре.',
                SystemMessages.SM_TYPE.Warning)
        return

    dispatcher, entity = _getRandomQueueEntity()
    if dispatcher is None or entity is None:
        _notify(u'Поиск ГС работает только в одиночном случайном бою.',
                SystemMessages.SM_TYPE.Warning)
        return

    _active = True
    _attempt = 0
    _restarts = 0
    _notify(u'Поиск ГС запущен. Повторное нажатие горячей клавиши — отмена. '
            u'Выход на %d-й секунде таймера, лимит — %d перезапусков.' % (
                _visibleTimeout(), _maxRestarts()))
    _log('started')
    _enterQueue()


def _handleKeyDown(event):
    global _hotkeyHeld
    if not event.isKeyDown() or _hotkeyHeld or not _isHotkeyPressed(event):
        return
    _hotkeyHeld = True
    if _active:
        _stop(u'Поиск ГС отменён горячей клавишей.', leaveQueue=True)
    else:
        _start()


def _handleKeyUp(event):
    global _hotkeyHeld
    if _hotkeyHeld and not _isHotkeyPressed(event):
        _hotkeyHeld = False


def _onModSettingsChanged(linkage, newSettings):
    global _settings
    if linkage != MOD_LINKAGE:
        return
    _settings = dict(newSettings or {})
    _settings['visibleTimeout'] = _visibleTimeout()
    _settings['requeueDelay'] = _requeueDelay()
    _settings['maxRestarts'] = _maxRestarts()
    _log('settings changed: enabled=%s, visible timer target=%d seconds, '
         'requeue delay=%.1f seconds, max restarts=%d' % (
             _isEnabled(), _visibleTimeout(), _requeueDelay(), _maxRestarts()))
    if _active and not _isEnabled():
        _stop(u'Поиск ГС отключён в настройках модификаций.',
              leaveQueue=True)


def _registerSettings():
    global _settings, _modsSettingsApi
    template = {
        'modDisplayName': u'Поиск генерального сражения (nidin)',
        'settingsVersion': SETTINGS_VERSION,
        'enabled': True,
        'column1': [
            {
                'type': 'Slider',
                'text': u'Время ожидания в очереди',
                'tooltip': (u'{HEADER}Время ожидания{/HEADER}'
                            u'{BODY}Когда видимый таймер достигнет этого значения, '
                            u'мод выйдет из очереди, выдержит настроенную паузу и снова '
                            u'нажмёт «В бой».{/BODY}'),
                'minimum': MIN_VISIBLE_TIMEOUT,
                'maximum': MAX_VISIBLE_TIMEOUT,
                'snapInterval': 1,
                'value': DEFAULT_VISIBLE_TIMEOUT,
                'format': '{{value}} сек.',
                'varName': 'visibleTimeout',
            },
            {
                'type': 'Slider',
                'text': u'Пауза перед повторным поиском',
                'tooltip': (u'{HEADER}Пауза между попытками{/HEADER}'
                            u'{BODY}Сколько секунд мод ждёт после подтверждения '
                            u'выхода из очереди, прежде чем снова нажать «В бой».{/BODY}'),
                'minimum': MIN_REQUEUE_DELAY,
                'maximum': MAX_REQUEUE_DELAY,
                'snapInterval': 0.5,
                'value': DEFAULT_REQUEUE_DELAY,
                'format': '{{value}} сек.',
                'varName': 'requeueDelay',
            },
            {
                'type': 'HotKey',
                'text': u'Горячая клавиша запуска и отмены',
                'tooltip': (u'{HEADER}Управление автопоиском{/HEADER}'
                            u'{BODY}Первое нажатие запускает автоматический поиск, '
                            u'повторное — останавливает его и выходит из очереди.{/BODY}'),
                'value': DEFAULT_HOTKEY,
                'varName': 'hotkey',
            },
            {
                'type': 'Slider',
                'text': u'Максимальное число перезапусков',
                'tooltip': (u'{HEADER}Лимит перезапусков{/HEADER}'
                            u'{BODY}После указанного числа повторных входов мод '
                            u'перестанет отменять поиск и будет ждать бой без '
                            u'ограничения времени.{/BODY}'),
                'minimum': MIN_MAX_RESTARTS,
                'maximum': MAX_MAX_RESTARTS,
                'snapInterval': RESTARTS_STEP,
                'value': DEFAULT_MAX_RESTARTS,
                'format': '{{value}}',
                'varName': 'maxRestarts',
            },
        ],
        'column2': [
            {'type': 'Label', 'text': u'Автор: nidin'},
            {'type': 'Label',
             'text': u'Включите «Генеральное сражение» в настройках игры.'},
        ],
    }
    try:
        from gui.modsSettingsApi import g_modsSettingsApi
        _modsSettingsApi = g_modsSettingsApi
        savedSettings = g_modsSettingsApi.getModSettings(
            MOD_LINKAGE, template)
        if savedSettings is not None:
            _settings = dict(savedSettings)
            g_modsSettingsApi.registerCallback(
                MOD_LINKAGE, _onModSettingsChanged)
        else:
            # Reading getModSettings for the legacy ID would activate its old
            # menu row. Read a snapshot instead; API 1.7.0 removes inactive
            # templates when the settings window opens.
            storedSettings = getattr(g_modsSettingsApi, 'state', {}).get(
                'settings', {})
            previousSettings = storedSettings.get(MOD_LINKAGE)
            if previousSettings is None:
                previousSettings = storedSettings.get(LEGACY_MOD_LINKAGE)
            previousSettings = dict(previousSettings or {})
            registeredSettings = g_modsSettingsApi.setModTemplate(
                MOD_LINKAGE, template, _onModSettingsChanged)
            if registeredSettings is None:
                raise RuntimeError('ModsSettingsAPI template registration failed')
            _settings = dict(registeredSettings)
            if previousSettings:
                for key in ('enabled', 'visibleTimeout', 'requeueDelay',
                            'hotkey', 'maxRestarts'):
                    if key in previousSettings:
                        _settings[key] = previousSettings[key]
                g_modsSettingsApi.updateModSettings(
                    MOD_LINKAGE, dict(_settings))
                g_modsSettingsApi.saveState()
                _log('previous settings migrated to nidin identifier')
        _settings['visibleTimeout'] = _visibleTimeout()
        _settings['requeueDelay'] = _requeueDelay()
        _settings['maxRestarts'] = _maxRestarts()
        _log('ModsSettingsAPI registered; visible timer target=%d seconds, '
             'requeue delay=%.1f seconds, max restarts=%d' % (
                 _visibleTimeout(), _requeueDelay(), _maxRestarts()))
    except Exception as error:
        _log('ModsSettingsAPI unavailable; using %d seconds: %r' % (
            DEFAULT_VISIBLE_TIMEOUT, error))


_registerSettings()

InputHandler.g_instance.onKeyDown += _handleKeyDown
InputHandler.g_instance.onKeyUp += _handleKeyUp
g_playerEvents.onEnqueued += _onEnqueued
g_playerEvents.onDequeued += _onDequeued
g_playerEvents.onArenaCreated += _onArenaCreated
g_playerEvents.onEnqueueFailure += _onEnqueueFailure
g_playerEvents.onKickedFromQueue += _onKickedFromQueue

_log('loaded: configurable hotkey starts/cancels, visible timer target is %d seconds' %
     _visibleTimeout())
