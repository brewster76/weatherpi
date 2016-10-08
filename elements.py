import pygame
import pygame.gfxdraw
import time
import syslog
import math

from kivy.logger import Logger

import utils

element_types = [['DateTime', 'DateTimeElementClass'],
                 ['LifXButtons', 'lifxButonClass'],
                 ['Text', 'TextElementClass'],
                 ['Conditions', 'ConditionElementClass'],
                 ['Icons', 'IconElementClass'],
                 ['Forecast', 'ForecastElementClass'],
                 ['Almanac', 'AlmanacElementClass'],
                 ['DHT11', 'DHT11ElementClass']]

class elementClass:
    """Superclass. Must provide a render() function"""
    def __init__(self, conf_settings, element_name, background_colour=None):
        self.conf_settings = conf_settings
        self.element_settings = utils.accumulateLeaves(conf_settings[element_name])
        
        if 'font' in self.element_settings:
            try:
                font_path = utils.settings_path(self.element_settings['font'][0])
                self.font = pygame.font.Font(font_path, int(self.element_settings['font'][1]))
            except IOError:
                Logger.warning("Cannot locate font %s" % font_path)
                self.font = None
        else:
            self.font = None

        self.pos = utils.listToTuple(self.element_settings['pos'])

        if 'size' in self.element_settings:
            self.size = utils.listToTuple(self.element_settings['size'])
            self.rect = pygame.Rect(self.pos[0], self.pos[1], self.size[0], self.size[1])
        else:
            self.size = None
            self.rect = None

        self.element_name = element_name

        if 'colour' in self.element_settings:
            self.colour = utils.listToTuple(self.element_settings['colour'])
        else:
            self.colour = None

        if background_colour is None:
            self.background_colour = (0, 0, 0)
        else:
            self.background_colour = background_colour

        # How often to update
        if 'update' in self.element_settings:
            self.update_interval = int(self.element_settings['update'])
        else:
            self.update_interval = None

        self.last_updated = None

        # Whether we're aligned to another element
        self.align_to_other = None

        self.surface = None

    def blank_surface(self):
        if self.surface is not None:
            self.surface.fill(self.background_colour)

    def handleEvent(self, eventObj):
        return False # This class is meant to be overridden.

    def update_condition(self, weather_underground, sun_almanac, indoor_sensor):
        pass # This class is meant to be overridden.

    def render(self):
        pass # This class is meant to be overridden.

    def blit(self, screen):
        if self.surface is not None:
            screen.blit(self.surface, self.pos)

    def updateDue(self):
        if self.last_updated is None:
            return True

        if self.update_interval is not None:
            if (time.time() - self.update_interval) > self.last_updated:
                return True

        return False


class IconElementClass(elementClass):
    def __init__(self, conf_settings, element_name, background_colour):
        elementClass.__init__(self, conf_settings, element_name, background_colour)

        self.icon_file = None
        self.source = self.element_settings['source']
        self.text = None

        if 'day' in self.element_settings:
            self.day = int(self.element_settings['day'])
        else:
            self.day = None

        self.surface = pygame.Surface(self.size)

    def update_condition(self, weather_underground, sun_almanac, indoor_sensor):
        """Extract from weather underground supplied URL"""
        url = ""

        if 'conditions' == self.source:
            url = weather_underground.conditions['icon_url']

        if 'forecast' == self.source:
            url = weather_underground.forecast[self.day]['icon_url']
            self.text = weather_underground.forecast[self.day]['date']['weekday_short']

        last_slash = None
        for i in range(0, len(url)):
            if '/' == url[i]:
                last_slash = i

        if last_slash is None:
            syslog.syslog(syslog.LOG_CRIT, "Not a valid URL: %s" % url)
            return

        self.icon_file = utils.BASE_DIR + "/icons/" + url[last_slash + 1:-4] + ".png"

    def render(self):
        elementClass.render(self)
        if self.icon_file is None:
            # Nothing doing
            return

        self.surface = pygame.image.load(self.icon_file)
        self.surface = pygame.transform.scale(self.surface, self.size)

class pygameButtonClass(elementClass):
    def __init__(self, conf_settings, element_name, background_colour):
        elementClass.__init__(self, conf_settings, element_name, background_colour)

        # TODO: Shouldn't this be "fill_colour" ?
        self.back_colour = utils.listToTuple(self.element_settings['back_colour'])
        self.click_colour = utils.listToTuple(self.element_settings['click_colour'])

        self.ellipse_pos = (int(self.size[0] / 2), int(self.size[1] / 2))
        self.ellipse_rad = int(self.size[0] * 0.48), int(self.size[1] * 0.48)

        if 'text' in self.element_settings:
            self.text = self.element_settings['text']
        else:
            self.text = None

        self.surface = pygame.Surface(self.size)
        #self.surface.set_colorkey((0, 0, 0))     # Set black as transparent

        self.mouse_down = False

    def render(self):
        """ Render the surface, and brighten it up at the end if it's pressed"""
        if type(self.back_colour) is list:
            segments = len(self.back_colour)
            pie_span = 360.0 / segments

            for i in range(0, segments):
                pygame.gfxdraw.filled_polygon(self.surface, self.pie_points(self.ellipse_pos[0], self.ellipse_pos[1],
                                                                            self.ellipse_rad[0], self.ellipse_rad[1],
                                                                            (i - 1) * pie_span, i * pie_span),
                                              self.back_colour[i])

        else:
            pygame.gfxdraw.filled_ellipse(self.surface, self.ellipse_pos[0], self.ellipse_pos[1], self.ellipse_rad[0],
                                     self.ellipse_rad[1], self.back_colour)

        for i in range(0, 2):
            pygame.gfxdraw.aaellipse(self.surface, self.ellipse_pos[0], self.ellipse_pos[1], self.ellipse_rad[0] - i,
                                     self.ellipse_rad[1] - i, self.colour)

        if self.mouse_down is True:
            # Brighten things up
            self.brighten_up(1.5)


    def pie_points(self, cx, cy, rx, ry, start_angle, end_angle):
        p = [(cx, cy)]

        # Get points on arc
        for n in range(int(start_angle), int(end_angle)):
            x = cx + int(rx * math.cos(n * math.pi / 180))
            y = cy + int(ry * math.sin(n * math.pi / 180))
            p.append((x, y))
        p.append((cx, cy))

        return p

    def brighten_up(self, multiplier):
        # Haven't figured out how to do this yet
        pass


    def brighten_color(self, color_val, multiplier):
        color_val = int(color_val * multiplier)

        if color_val > 255:
            color_val = 255

        return color_val

    def handleEvent(self, event):
        syslog.syslog(syslog.LOG_DEBUG, "Detected event.pos = %d, %d, rectangle limits = (%d, %d), (%d, %d)" %
                      (event.pos[0], event.pos[1], self.rect[0], self.rect[1], self.rect[2] + self.rect[0],
                       self.rect[3] + self.rect[1]))

        if self.rect.collidepoint(event.pos):
            if event.type is pygame.MOUSEBUTTONDOWN:
                self.mouse_down = True

                self.render()
                return True

            if event.type is pygame.MOUSEBUTTONUP:
                if self.mouse_down is True:
                    self.mouse_down = False

                    self.buttonpress()
                    self.render()
                    return True

        return False

    def buttonpress(self):
        pass    # This class is meant to be overridden

class lifxButonClass(pygameButtonClass):
    def __init__(self, conf_settings, element_name, background_colour):
        pygameButtonClass.__init__(self, conf_settings, element_name, background_colour)

        if 'light' in self.element_settings:
            self.light = utils.lifxLight(light=self.element_settings['light'])
        else:
            if 'group' in self.element_settings:
                self.light = utils.lifxLight(group=self.element_settings['group'])
            else:
                raise ValueError("lifxButonClass: Must specify either a light or a group")

        offline_icon = self.element_settings['offline_icon']
        self.icon_surface = pygame.image.load(offline_icon)
        self.icon_surface = pygame.transform.scale(self.icon_surface, (int(self.size[0] * 0.7), int(self.size[1] * 0.7)))

        self.show_offline_icon = False

        self._update_colour(self.light.power())
        self.render()

    def buttonpress(self):
        self._update_colour(self.light.toggle())

    def update_condition(self, weather_underground, sun_almanac, indoor_sensor):
        if self.updateDue():
            self._update_colour(self.light.power())
            #print "Update due: %s, power = %s" % (self.light.light_name, self.light.power())
            self.last_updated = time.time()
        pass

    def render(self):
        # Capture zero length background colour lists
        if type(self.back_colour) is list:
            if 0 == len(self.back_colour):
                self.back_colour = (0, 0, 0)

        pygameButtonClass.render(self)

        if self.show_offline_icon is True:
            self.surface.blit(self.icon_surface,(int(self.size[0] * 0.15), int(self.size[1] * 0.15)))

    def _update_colour(self, power):
        self.back_colour = (0, 0, 0)

        if power is not None:
            self.show_offline_icon = False
            if power is True:
                self.back_colour = self.light.lifx_rgb_color()
        else:
            self.show_offline_icon = True

class DateTimeElementClass(elementClass):
    def __init__(self, conf_settings, element_name, background_colour):
        elementClass.__init__(self, conf_settings, element_name, background_colour)

        self.text_format = self.element_settings['format']

    def render(self):
        text = time.strftime(self.text_format)
        self.surface = self.font.render(text, True, self.colour)

class AlmanacElementClass(elementClass):
    def __init__(self, conf_settings, element_name, background_colour):
        elementClass.__init__(self, conf_settings, element_name, background_colour)

        self.text_format = self.element_settings['format']

        self.text = None

    def render(self):
        if self.text is not None:
            self.surface = self.font.render(self.text, True, self.colour)

    def update_condition(self, weather_underground, sun_almanac, indoor_sensor):
        sun = sun_almanac.sun[self.element_name]

        self.text = sun.strftime(self.text_format)


class TextElementClass(elementClass):
    def __init__(self, conf_settings, element_name, background_colour):
        elementClass.__init__(self, conf_settings, element_name, background_colour)

        self.text = self.element_settings['text']

        self.align_to_other = None
        self.align_base_pos = None

        if 'align_condition' in self.element_settings:
            self.align_to_other = self.element_settings['align_condition']
            self.align_base_pos = self.pos[0]

    def render(self):
        self.surface = self.font.render(self.text, True, self.colour)

class ForecastElementClass(elementClass):
    def __init__(self, conf_settings, element_name, background_colour):
        elementClass.__init__(self, conf_settings, element_name, background_colour)

        self.text_format = self.element_settings['text']
        self.day = int(self.element_settings['day'])

        self.units = None
        if 'units' in self.element_settings:
            self.units = self.element_settings['units']

        self.text = None

        self.align_to_other = None
        self.align_base_pos = None

        self.hide = None
        if 'hide' in self.element_settings:
            self.hide = self.element_settings['hide']

        if 'align_condition' in self.element_settings:
            self.align_to_other = self.element_settings['align_condition']
            self.align_base_pos = self.pos[0]

    def update_condition(self, weather_underground, sun_almanac, indoor_sensor):
        try:
            wu_element = weather_underground.forecast[self.day][self.element_name]
        except KeyError:
            Logger.warning("Could not find forecast element [%s][%s]" % (self.day, self.element_name))
            self.text = "Err"
            return

        if self.units is not None:
            wu_element = wu_element[self.units]
            self.text = self.text_format % wu_element
        else:
            self.text = wu_element

        if self.hide is not None:
            if type(wu_element) is int:
                if wu_element < int(self.hide):
                    self.text = ""
            else:
                syslog.syslog(syslog.LOG_INFO, "Don't know how to deal with wu_element type: %s" % type(wu_element))

    def render(self):
        self.surface = self.font.render(self.text, True, self.colour)

class ConditionElementClass(elementClass):
    def __init__(self, conf_settings, element_name, background_colour):
        elementClass.__init__(self, conf_settings, element_name, background_colour)

        self.text_format = self.element_settings['text']
        self.text = None

    def update_condition(self, weather_underground, sun_almanac, indoor_sensor):
        try:
            self.text = self.text_format % weather_underground.conditions[self.element_name]
        except KeyError:
            Logger.warning("Could not find condition element [%s]" % self.element_name)
            self.text = "Err"
            return

    def render(self):
        self.surface = self.font.render(self.text, True, self.colour)

class DHT11ElementClass(elementClass):
    def __init__(self, conf_settings, element_name, background_colour):
        elementClass.__init__(self, conf_settings, element_name, background_colour)

        self.text_format = self.element_settings['text']
        self.text = None

    def update_condition(self, weather_underground, sun_almanac, indoor_sensor):
        reading = getattr(indoor_sensor, self.element_name)

        if reading is None:
            syslog.syslog(syslog.LOG_DEBUG, "indoor_sensor element [%s] in None" % self.element_name)
            self.text = "Err"
            return

        try:
            self.text = self.text_format % reading
        except KeyError:
            syslog.syslog(syslog.LOG_DEBUG, "Could not find indoor_sensor element [%s]" % self.element_name)
            self.text = "Err"
            return

    def render(self):
        self.surface = self.font.render(self.text, True, self.colour)
