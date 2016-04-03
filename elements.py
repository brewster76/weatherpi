import pygame
import time
import syslog

import utils


class elementClass:
    """Superclass. Must provide a render() function"""
    def __init__(self, conf_settings, element_name, background_colour=None):
        self.conf_settings = conf_settings
        self.element_settings = utils.accumulateLeaves(conf_settings[element_name])
        
        if 'font' in self.element_settings:
            self.font = pygame.font.Font(self.element_settings['font'][0], int(self.element_settings['font'][1]))
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
        pass # This class is meant to be overridden.

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

        self.icon_file = "icons/" + url[last_slash + 1:-4] + ".png"

    def render(self):
        elementClass.render(self)
        if self.icon_file is None:
            # Nothing doing
            return

        self.surface = pygame.image.load(self.icon_file)
        self.surface = pygame.transform.scale(self.surface, self.size)

class pygameButton(elementClass):
    def __init__(self, conf_settings, element_name, background_colour):
        elementClass.__init__(self, conf_settings, element_name, background_colour)

        # TODO: Shouldn't this be "fill_colour" ?
        self.back_colour = utils.listToTuple(self.element_settings['back_colour'])
        self.click_colour = utils.listToTuple(self.element_settings['click_colour'])

        self.surface = pygame.Surface(self.size)
        self.mouse_down = False

    def render(self):
        if self.mouse_down is True:
            self.surface.fill(self.click_colour)
        else:
            self.surface.fill(self.back_colour)

        pygame.draw.rect(self.surface, self.colour, (0, 0, self.size[0], self.size[1]), 3)

    def handleEvent(self, event):
        if event.type not in (pygame.MOUSEBUTTONUP, pygame.MOUSEBUTTONDOWN):
            return ()
        # The button only cares bout mouse-related events

        if self.rect.collidepoint(event.pos):
            if event.type is pygame.MOUSEBUTTONDOWN:
                self.mouse_down = True

            if event.type is pygame.MOUSEBUTTONUP:
                if self.mouse_down is True:
                    syslog.syslog(syslog.LOG_INFO, "%s: CLICK!" % self.element_name)
                    self.mouse_down = False
        else:
            self.mouse_down = False


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
            syslog.syslog(syslog.LOG_DEBUG, "Could not find forecast element [%s][%s]" % (self.day, self.element_name))
            self.text = "Err"
            return

        if self.units is not None:
            wu_element = wu_element[self.units]

        self.text = self.text_format % wu_element

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
            syslog.syslog(syslog.LOG_DEBUG, "Could not find condition element [%s]" % self.element_name)
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