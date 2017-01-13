import sublime
import sublime_plugin
import os
import shutil
import datetime
import json
import requests


# Pulses will be sent after intervals of this many seconds
PULSE_TIMEOUT = 10

# Default URL for the API
DEFAULT_URL = 'https://codestats.net/api/my/pulses'


def log(*msg):
    print('code-stats-sublime:', *msg)


def show_first_time_setup():
    """
    Show first time setup if user settings file doesn't exist yet.
    """
    user_settings_file = os.path.join(sublime.packages_path(), 'User', 'CodeStats.sublime-settings')

    if not os.path.isfile(user_settings_file):
        sublime.run_command('edit_settings', {
            'base_file': '${packages}/CodeStats/Settings/CodeStats.sublime-settings',
            'default': """// Put your custom settings here, check the default settings file for keys.
{}"""
        })


def send_pulses():
    # If required settings are not defined, don't act
    if not Config.has_required_settings():
        return

    window = sublime.active_window()
    pulses = Pulse.pulses_to_send

    if Pulse.current_pulse is not None:
        pulses += [str(Pulse.current_pulse)]

    failed_pulses = []

    window.status_message('C::S submitting…')
    for pulse in pulses:
        failed = False
        r = None
        try:
            r = requests.post(
                Config.api_url,
                headers={
                    'content-type': 'application/json',
                    'x-api-token': Config.api_key,
                },
                data=pulse
            )

            if r.status_code != 201:
                failed = True
                log('Pulse failed with status', r.status_code, 'and content:', r.text)
                window.status_message('C::S submit failed: {} {}'.format(r.status_code, r.text))

        except requests.exceptions.RequestException as e:
            failed = True
            log('Pulse failed with exception', str(e))
            window.status_message('C::S error: ' + str(e))

        if failed:
            failed_pulses += [pulse]

    Pulse.current_pulse = None
    Pulse.pulses_to_send = failed_pulses

    if len(failed_pulses) == 0:
        window.status_message('')


class Config:
    """
    Configuration handler. Listens to changes in plugin configuration.
    """

    api_key = None
    api_url = None
    initted = False

    @classmethod
    def init(cls):
        cls.load_settings()

        cls.settings.add_on_change('API_URL', cls.url_changed)
        cls.settings.add_on_change('API_KEY', cls.key_changed)

        cls.initted = True

        if not cls.__is_undefined__(cls.api_key):
            log('Initialised with key {}.'.format(cls.api_key))
        else:
            log('Initialised with no key.')

    @classmethod
    def load_settings(cls):
        cls.settings = sublime.load_settings('CodeStats.sublime-settings')
        cls.url_changed()
        cls.key_changed()

    @classmethod
    def url_changed(cls):
        cls.api_url = cls.settings.get('API_URL', DEFAULT_URL)
        log('URL changed to {}.'.format(cls.api_url))

    @classmethod
    def key_changed(cls):
        cls.api_key = cls.settings.get('API_KEY', None)
        log('Key changed to {}.'.format(cls.api_key))

    @classmethod
    def has_required_settings(cls):
        return not cls.__is_undefined__(cls.api_url) and not cls.__is_undefined__(cls.api_key)

    @classmethod
    def has_init(cls):
        return cls.initted

    @staticmethod
    def __is_undefined__(value):
        return value is None or value == ''


class Timer:
    """
    Timer that runs given function after given time.
    """

    def __init__(self, fun):
        self.fun = fun
        self.set_timeout()

    def run(self):
        self.fun()

    def set_timeout(self):
        sublime.set_timeout_async(lambda: self.run(), PULSE_TIMEOUT * 1000)


class Pulse:
    """
    Represents one Pulse to be sent to the API.
    """

    # Current active pulse
    current_pulse = None

    # JSONified pulses waiting for sending because of network problems
    pulses_to_send = []

    def __init__(self):
        self.xps = {}

    def add_xp(self, language, amount):
        """
        Add XP with the given language and given amount into the pulse.
        """
        xp = self.xps.get(language, 0) + amount
        self.xps[language] = xp

    def __str__(self):
        # Convert pulse into JSON string that can be sent to API
        ret = {'coded_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
        ret['xps'] = [{'language': l, 'xp': x} for l, x in self.xps.items()]
        return json.dumps(ret)

    @classmethod
    def get_pulse(cls):
        """
        Get or create currently active Pulse.
        """
        if cls.current_pulse is None:
            cls.current_pulse = Pulse()

        return cls.current_pulse


class ChangeListener(sublime_plugin.EventListener):
    """
    Event listener that listens to changes in any editors and counts them.

    Changes seem to be a good approximation of characters typed in Sublime Text.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.timer = None

    def timer_run(self):
        send_pulses()
        self.timer = None

    def on_modified_async(self, view):
        # If plugin isn't fully loaded yet, don't do anything
        if not Config.has_init():
            return

        # Prevent XP from other views than editor view (widgets are builtin stuff
        # like menus, find dialogs, etc.)
        if view.settings().get('is_widget'):
            return

        # Start timer if not already started
        if self.timer is None:
            self.timer = Timer(lambda: self.timer_run())

        pulse = Pulse.get_pulse()
        syntax_file = os.path.basename(view.settings().get('syntax'))
        language = os.path.splitext(syntax_file)[0]

        pulse.add_xp(language, 1)


def plugin_loaded():
    Config.init()

    if not Config.has_required_settings():
        show_first_time_setup()
