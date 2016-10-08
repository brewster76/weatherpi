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

import elements
import utils

SETTINGS_FILE = "/home/pi/Pygame/weather_nolifx.conf"
WEATHER_FILE = "/tmp/birthdays.pkl"

WEATHER_SCREEN = "weather"
OPTIONS_SCREEN = "options"
LIFX_SCREEN = "lifx"

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
        Logger.info("Powering off at user's request")
        os.system("sudo poweroff")

    def restart(self):
        Logger.info("Rebooting at user's request")
        os.system("sudo reboot")


class TimeChange():
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


class LifxScreen(Screen):
    def __init__(self, settings, **kwargs):
        super(LifxScreen, self).__init__(**kwargs)
        self.lights = utils.lifxLights(settings)

        # Options screen button

        self.bind(on_pre_enter=self.pre_enter_callback)
        self.bind(on_leave=self.on_leave_callback)

    def pre_enter_callback(self, *args):
        self.lights.refresh()

        for light_button in self.lights.light_button_list:
            self.ids.light_box.add_widget(light_button)

    def on_leave_callback(self, *args):
        self.ids.light_box.clear_widgets()


class WeatherScreen(Screen):
    def __init__(self, settings, **kwargs):
        super(WeatherScreen, self).__init__(**kwargs)

        self.settings = settings

        self.background_colour = utils.listToTuple(settings['Screen']['backgorund_colour'])

        self.element_list = []

        for section_name, function_name in elements.element_types:
            Logger.info("%s, %s" % (section_name, function_name))
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
    def build(self):
        if os.path.isfile(SETTINGS_FILE) is False:
            Logger.exception("Cannot open configuration file %s" % SETTINGS_FILE)
            exit()

        settings = configobj.ConfigObj(SETTINGS_FILE)

        if 'debug' in settings['General']:
            Logger.setLevel(kivy.logger.logging.DEBUG)

        root = BacklightScreenManager(settings)
        root.transition = kivy.uix.screenmanager.SlideTransition()

        root.add_widget(WeatherScreen(settings, name=WEATHER_SCREEN))
        root.add_widget(OptionsScreen(name=OPTIONS_SCREEN))
        root.add_widget(LifxScreen(settings, name=LIFX_SCREEN))

        Clock.schedule_interval(root.clock_callback, 1.0)
        return root


if __name__ == '__main__':
    Logger.info("Weather forecaster starting up...")

    # Get pygame going
    pygame.init()

    if not utils.areWePi():
        # Create a Pi sized window
        Config.set('graphics', 'width', '800')
        Config.set('graphics', 'height', '480')
        Config.set('graphics', 'max_fps', '5')

    try:
        WeatherApp().run()
    except:
        f = open('/home/pi/Pygame/crashlogs/crashlog_%s' % time.strftime("%Y-%m-%d_%H:%M:%S"), 'w')
        f.write(time.strftime('%c') + '\n')
        f.write('-' * 60 + '\n')
        traceback.print_exc(file=f)
