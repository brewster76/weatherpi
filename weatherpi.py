import kivy
kivy.require('1.7.2')

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.config import Config
from kivy.logger import Logger, LoggerHistory
from kivy.clock import Clock
from kivy.core.image import ImageData
from kivy.uix.image import Image
from kivy.uix.button import Button
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.textinput import TextInput
from kivy.graphics.texture import Texture
from kivy.properties import StringProperty, ListProperty

import pygame

import os
import configobj
import time
import datetime
import pickle
import traceback
import threading

import elements
import utils
from utils import BASE_DIR

import lifxlan

SETTINGS_FILE = BASE_DIR + "/weather.conf"
CRASHLOG_DIR = BASE_DIR + "/crashlog"

WEATHER_FILE = "/tmp/birthdays.pkl"

WEATHER_SCREEN = "weather"
OPTIONS_SCREEN = "options"
LIFX_SCREEN = "lifx"

# How often to poll lights when screen in focus
REFRESH_INTERVAL_FOREGROUND = 10
REFRESH_INTERVAL_BACKGROUND = 300

LIFX_LAN_ON = [True, 1, "on", 65535]
LIFX_LAN_OFF = [False, 0, "off"]

BUTTON_RED_COLOR =   [1.0, 0.4, 0.4]
BUTTON_GREEN_COLOR = [0.3, 0.6, 0.3]
BUTTON_NEUTRAL_COLOR = [0, 0, 0]
BACKLIGHT_TIMES = [[10, '10 secs'], [20, '20 secs'], [30, '30 secs'], [45, '45 secs'],
                   [60, '1 min'],  [120, '2 mins'], [300, '5 mins'], [-1, 'Always on']]

class OptionsScreen(Screen):
    logger_history = StringProperty("Kivy event log")
    backlight_timeout_label = StringProperty("1 min")

    wifi_color = ListProperty(BUTTON_NEUTRAL_COLOR)
    DHT22_color = ListProperty(BUTTON_NEUTRAL_COLOR)
    wunderground_color = ListProperty(BUTTON_NEUTRAL_COLOR)
    LIFX_color = ListProperty(BUTTON_NEUTRAL_COLOR)

    def __init__(self, **kwargs):
        super(OptionsScreen, self).__init__(**kwargs)

        self.weather_screen_cache = None
        self.bind(on_pre_enter=self.pre_enter_callback)

    def weather_screen(self):
        if self.weather_screen_cache is None:
            for s in self.manager.screens:
                if s.name == WEATHER_SCREEN:
                    self.weather_screen_cache = s

        return self.weather_screen_cache

    def backlight_brightness_change(self, value):
        self.manager.backlight.setBrightness(value)

    def backlight_timeout_change(self, value):
        # set timeout
        self.backlight_timeout_label = BACKLIGHT_TIMES[int(value)][1]
        self.manager.backlight.setTimeout(BACKLIGHT_TIMES[int(value)][0])

    def pre_enter_callback(self, *args):

        self.update_logger()
        self.update_wifi_status()
        self.update_weather_status()
        self.update_DHT_status()

        # TODO: Update every 15 seconds

    def update_wifi_status(self):
        self.wifi_color = BUTTON_GREEN_COLOR if self.ping_host("192.168.1.1") else BUTTON_RED_COLOR

    def update_weather_status(self):
        self.wunderground_color = BUTTON_GREEN_COLOR if self.ping_host("wunderground.com") else BUTTON_RED_COLOR

    def update_DHT_status(self):
        s = self.weather_screen()
        self.DHT22_color = BUTTON_RED_COLOR if s.indoor_sensor.temperature is None else BUTTON_GREEN_COLOR

    def ping_host(self, hostname):
        response = os.system("ping -c 1 -W 1 " + hostname)

        # and then check the response...
        if response == 0:
            return True
        else:
            return False

    def update_logger(self):
        string = ""

        for h in LoggerHistory.history:
            time_string = datetime.datetime.fromtimestamp(h.created).strftime('%Y-%m-%d %H:%M:%S')
            string = "%s %20s  %s\n" % (time_string, h.filename, h.msg) + string

        self.logger_history = string

    def power_off(self):
        Logger.info("WeatherPi: Powering off at user's request")
        os.system("sudo poweroff")

    def restart(self):
        Logger.info("WeatherPi: Rebooting at user's request")
        os.system("sudo reboot")


class TimeChange:
    def __init__(self, settings):
        self.time_format = settings['DateTime']['time']['format']
        self.last_time = self._new_time_string()

    def time_changed(self):
        nt = self._new_time_string()

        if nt == self.last_time:
            return False

        self.last_time = nt
        return True

    def _new_time_string(self):
        return time.strftime(self.time_format)


class Light:
    def __init__(self, lifxlight, rooms):
        self.lifxlight = lifxlight
        self.rooms = rooms

        self.label = self.lifxlight.get_label()
        self.group = self.lifxlight.get_group_label()

        Logger.info("Lights: New light %s / %s" % (self.label, self.group))

        self.button = ToggleButton(text=self.label)
        self.button.bind(state=self.callback)

    def button_state(self):
        return False if self.button.state == 'normal' else True

    def callback(self, instance, value):
        """Ensures that light is set to same state as button"""
        button_state = False if value == 'normal' else True

        light_state = self.get_state()

        if light_state != button_state:
            # Is light offline?
            if light_state is None:
                return

            self.lifxlight.set_power(button_state)
            self.rooms.refresh()

        Logger.debug("Lights: Light is %s, value is %s, get_power is %s" % (self.label, value, self.get_state()))

    def refresh_light(self):
        light_state = self.get_state()

        if light_state is True:
            self.button.state = 'down'

        if light_state is False:
            self.button.state = 'normal'

        if light_state is None:
            self.button.state = 'normal'

    def get_state(self):
        try:
            power = self.lifxlight.get_power()
        except IOError:
            # Light is offline
            return None

        if power in LIFX_LAN_OFF:
            return False

        if power in LIFX_LAN_ON:
            return True

        return None


class Rooms:
    def __init__(self):
        self.room_list = []

    def add_room(self, light):
        for room in self.room_list:
            if room.label == light.group:
                # Room already exists, add another light to it
                room.add_light(light)
                return None

        new_room = Room(light.group)

        self.room_list.append(new_room)

        new_room.add_light(light)

        return new_room.room_button

    def refresh(self):
        for room in self.room_list:
            room.refresh()

    def __str__(self):
        str_list = []

        for room in self.room_list:
            str_list.append("%s" % room)

        return ', '.join(str_list)


class Room:
    def __init__(self, label):
        self.light_list = []
        self.label = label

        self.refresh_in_process = False

        self.room_button = ToggleButton(text=self.label)
        self.room_button.bind(state=self.callback)

    def add_light(self, light):
        self.light_list.append(light)

    def refresh(self):
        self.refresh_in_process = True

        room_state = True

        for light in self.light_list:
            # State is off unless all lights are on
            if light.button_state() is False:
                room_state = False

        self.room_button.state = 'normal' if room_state is False else 'down'

        self.refresh_in_process = False

    def __str__(self):
        light_name_list = []

        for light in self.light_list:
            light_name_list.append(light.label)

        return "%s [%s]" % (self.label, ', '.join(light_name_list))

    def callback(self, instance, value):
        if self.refresh_in_process:
            # User did not press the button
            return

        for light in self.light_list:
            light.button.state = value


class LifxScreen(Screen):
    def __init__(self, settings, **kwargs):
        super(LifxScreen, self).__init__(**kwargs)

        self.lights = None
        self.rooms = None

        self.refresh_clock = None

        # Thread management
        self.refresh_thread = None
        self.refresh_thread_finishing = False
        self.stop_refresh_thread = False

        self.bind(on_pre_enter=self.pre_enter_callback)
        self.bind(on_leave=self.on_leave_callback)

        self.ids['refresh_button'].bind(state=self.refresh_button_slot)

        self.lan = lifxlan.LifxLAN()

        self.refresh_lights()

        self.set_schedule_interval(REFRESH_INTERVAL_BACKGROUND)

    def set_schedule_interval(self, interval):
        if self.refresh_clock is not None:
            self.refresh_clock.cancel()

        self.refresh_clock = Clock.schedule_interval(self.refresh_slot, interval)

    def pre_enter_callback(self, *args):
        Clock.schedule_once(self.refresh_slot, 1)

        self.set_schedule_interval(REFRESH_INTERVAL_FOREGROUND)

    def on_leave_callback(self, *args):
        self.set_schedule_interval(REFRESH_INTERVAL_BACKGROUND)

    def refresh_button_slot(self, instance, value):
        if self.refresh_thread_running():
            if self.refresh_thread_finishing:
                self.ids['refresh_button'].state = 'normal'
            else:
                self.ids['refresh_button'].state = 'down'
        else:
            self.refresh_lights()

    def refresh_slot(self, dt):
        if self.refresh_thread_running() is False:
            self.refresh()

    def refresh_thread_running(self):
        if self.refresh_thread is not None:
            if self.refresh_thread.is_alive():
                return True

        return False

    def refresh_lights(self):
        if self.refresh_thread_running():
            return

        self.refresh_thread = threading.Thread(target=self.find_lights_thread)
        self.refresh_thread.start()

    def find_lights_thread(self):
        Logger.debug("Lights: Find lights thread started")

        self.refresh_thread_finishing = False
        self.ids['refresh_button'].state = 'down'

        if self.lights is not None:
            for light, button in self.lights:
                self.ids['light_layout'].remove_widget(button)

        if self.rooms is not None:
            for room in self.rooms.room_list:
                self.ids['group_layout'].remove_widget(room.room_button)

        self.lights = []
        self.rooms = Rooms()

        for l in self.lan.get_lights():
            # Bail out?
            if self.stop_refresh_thread:
                return

            new_light = Light(l, self.rooms)

            self.ids['light_layout'].add_widget(new_light.button)

            self.lights.append(new_light)

            new_light.refresh_light()

            new_room_button = self.rooms.add_room(new_light)
            if new_room_button is not None:
                self.ids['group_layout'].add_widget(new_room_button)

        self.rooms.refresh()

        self.refresh_thread_finishing = True
        self.ids['refresh_button'].state = 'normal'

        Logger.debug("Lights: Find lights thread finished")

    def refresh(self):
        if self.lights is None:
            # No lights registered yet
            return

        if self.refresh_thread_running():
            return

        self.refresh_thread = threading.Thread(target=self.refresh_lights_thread)
        self.refresh_thread.start()

    def refresh_lights_thread(self):
        Logger.debug("LightS: Refresh lights thread started")

        for light in self.lights:
            if self.stop_refresh_thread:
                # Bail out
                return

            light.refresh_light()

        self.rooms.refresh()

        Logger.debug("Lights: Refresh lights thread finished")

    def on_stop(self):
        if self.refresh_thread_running():
            self.stop_refresh_thread = True
            self.refresh_thread.join()


class WeatherScreen(Screen):
    def __init__(self, settings, **kwargs):
        super(WeatherScreen, self).__init__(**kwargs)

        self.settings = settings

        self.background_colour = utils.listToTuple(settings['Screen']['backgorund_colour'])

        self.element_list = []

        for section_name, function_name in elements.element_types:
            Logger.debug("Weather: %s, %s" % (section_name, function_name))
            if 'Forecast' is section_name:
                for day in settings[section_name].sections:
                    for sub_section in settings[section_name][day].sections:
                        new_element = getattr(elements, function_name)(settings[section_name][day], sub_section,
                                                                       self.background_colour)
                        self.element_list.append(new_element)
            else:
                if section_name in settings:
                    for sub_section in settings[section_name].sections:
                        new_element = getattr(elements, function_name)(settings[section_name], sub_section,
                                                                       self.background_colour)
                        self.element_list.append(new_element)

        self.sun_almanac = utils.almanac(settings['Almanac'])
        self.weather_underground = utils.Wunderground(settings, None)
        self.indoor_sensor = utils.DHT11(settings['DHT11'])

        self.image_size = utils.listToTuple(self.settings['Screen']['size'])

        self.image_surface = pygame.Surface(self.image_size)

        self.image = Image(size=self.image_size)
        self.add_widget(self.image)

        # Lifx screen button
        button_1 = Button(size_hint=(0.15, 0.1), pos_hint={'x': 0.63, 'y': 0.05}, text="Lights")
        button_1.bind(on_release=self.LightsPress)
        self.add_widget(button_1)

        # Options screen button
        button_2 = Button(size_hint=(0.15, 0.1), pos_hint={'x': 0.80, 'y': 0.05}, text="Options")
        button_2.bind(on_release=self.OptionsPress)
        self.add_widget(button_2)

        self.birthday_label = TextInput(size_hint=(0.4, 0.18), pos_hint={'x': 0.57, 'y': 0.2}, text="Birthdays...",
                                    multiline=True, background_color=[0, 0, 0, 0], foreground_color=[0.6, 0.6, 0.6, 1])
        self.add_widget(self.birthday_label)

        self.render()

    def OptionsPress(self, obj):
        self.manager.transition.direction = 'left'
        self.manager.current = OPTIONS_SCREEN

    def LightsPress(self, obj):
        self.manager.transition.direction = 'right'
        self.manager.current = LIFX_SCREEN

    def render(self):
        self.image_surface.fill(self.background_colour)

        for element in self.element_list:
            element.update_condition(self.weather_underground, self.sun_almanac, self.indoor_sensor)
            element.render()

        # Deal with any text alignments
        for element in self.element_list:
            if element.align_to_other is not None:
                for e in self.element_list:
                    if e.element_name == element.align_to_other:
                        element.pos = (e.surface.get_width() + element.align_base_pos, element.pos[1])

        # Blit the new surfaces
        for element in self.element_list:
            element.blit(self.image_surface)

        # And import into kivy
        buffer = pygame.image.tostring(self.image_surface, 'RGB', True)
        imdata = ImageData(self.image_size[0], self.image_size[1], 'rgb', buffer)
        self.image.texture = Texture.create_from_data(imdata)

        self.update_birthdays()

    def update_birthdays(self):
        try:
            pkl_file = open(WEATHER_FILE, 'rb')
        except IOError:
            self.birthday_label.text = "-"
            return

        birthdays = pickle.load(pkl_file)

        # Show first 4 items or the next 30 days, whichever we hit first
        items = 6
        max_delta_days = 30

        new_text = ""

        for b in birthdays:
            if b['delta'] < max_delta_days:
                if items > 0:
                    if len(new_text) > 0:
                        new_text += ", "

                    new_text += "%s in %d days" % (b['summary'], b['delta'])
                    items -= 1

        self.birthday_label.text = new_text


class BacklightScreenManager(ScreenManager):
    """Adds backlight management to the ScreenManager class"""

    def __init__(self, settings, **kwargs):
        super(BacklightScreenManager, self).__init__(**kwargs)

        self.backlight = utils.backlight(settings['Backlight'])
        self.time_tracker = TimeChange(settings)

        self.bind(on_touch_down=self.screen_press)

    def screen_press(self, id, args):
        """Screen pressed, so reset the backlight timer"""
        self.backlight.reset_timer()

    def clock_callback(self, dt):

        # Weather screen update needed?
        if self.backlight.state:
            if self.current_screen.name == WEATHER_SCREEN:
                if self.time_tracker.time_changed():
                    self.current_screen.render()

        if self.backlight.update_backlight():
            # Backlight switched off - switch back to home screen
            self.current = WEATHER_SCREEN

class WeatherApp(App):
    def __init__(self, **kwargs):
        self.lifx_screen = None

        super(WeatherApp, self).__init__(**kwargs)

    def build(self):
        if os.path.isfile(SETTINGS_FILE) is False:
            Logger.exception("WeatherPi: Cannot open configuration file %s" % SETTINGS_FILE)
            exit()

        settings = configobj.ConfigObj(SETTINGS_FILE)

        if 'debug' in settings['General']:
            Logger.setLevel(kivy.logger.logging.DEBUG)

        root = BacklightScreenManager(settings)
        root.transition = kivy.uix.screenmanager.SlideTransition()

        root.add_widget(WeatherScreen(settings, name=WEATHER_SCREEN))
        root.add_widget(OptionsScreen(name=OPTIONS_SCREEN))

        self.lifx_screen = LifxScreen(settings, name=LIFX_SCREEN)
        root.add_widget(self.lifx_screen)

        Clock.schedule_interval(root.clock_callback, 1.0)
        return root

    def on_stop(self):
        self.lifx_screen.on_stop()


if __name__ == '__main__':
    Logger.info("WeatherPi: Weather forecaster starting up...")

    # Get pygame going
    pygame.init()

    if not utils.areWePi():
        # Create a Pi sized window
        Config.set('graphics', 'width', '800')
        Config.set('graphics', 'height', '480')
        Config.set('graphics', 'max_fps', '5')

    WeatherApp().run()

    try:
        WeatherApp().run()
    except:
        if not os.path.exists(CRASHLOG_DIR):
            os.makedirs(CRASHLOG_DIR)

        f = open((CRASHLOG_DIR + '/crashlog_%s') % time.strftime("%Y-%m-%d_%H:%M:%S"), 'w')
        f.write(time.strftime('%c') + '\n')
        f.write('-' * 60 + '\n')
        traceback.print_exc(file=f)
