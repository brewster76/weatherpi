from utils import backlight

__author__ = 'nick'

import os
import sys
import configobj
import pygame
import syslog

import utils
import elements

SETTINGS_FILE = "weather.conf"

syslog.syslog(syslog.LOG_INFO, "Weather forecaster starting up...")

settings = configobj.ConfigObj(SETTINGS_FILE)

sun_almanac = utils.almanac(settings['Almanac'])

# Get pygame going
pygame.init()

backlight = backlight(settings['Backlight'])

if settings['Screen'].as_bool('framebuffer'):
    # Check which frame buffer drivers are available
    # Start with fbcon since directfb hangs with composite output
    drivers = ['fbcon', 'directfb', 'svgalib']
    found = False
    for driver in drivers:
        # Make sure that SDL_VIDEODRIVER is set
        if not os.getenv('SDL_VIDEODRIVER'):
            os.putenv('SDL_VIDEODRIVER', driver)
        try:
            pygame.display.init()
        except pygame.error:
            syslog.syslog(syslog.LOG_CRIT, 'Driver: {0} failed.'.format(driver))
            continue
        found = True
        break

    if not found:
        raise Exception('No suitable video driver found!')

    size = (pygame.display.Info().current_w, pygame.display.Info().current_h)
    syslog.syslog(syslog.LOG_INFO, "Framebuffer size: %d x %d" % (size[0], size[1]))
    pygame.mouse.set_visible(False)
    
    screen = pygame.display.set_mode(size, pygame.FULLSCREEN)
else:
    screen = pygame.display.set_mode(utils.listToTuple(settings['Screen']['size']))

background_colour = utils.listToTuple(settings['Screen']['backgorund_colour'])
screen.fill(background_colour)

element_list = []
element_types = [['DateTime',   'DateTimeElementClass'],
                 ['Buttons',    'pygameButtonClass'],
                 ['Text',       'TextElementClass'],
                 ['Conditions', 'ConditionElementClass'],
                 ['Icons',      'IconElementClass'],
                 ['Forecast',   'ForecastElementClass'],
                 ['Almanac',    'AlmanacElementClass'],
                 ['DHT11',      'DHT11ElementClass']]

for section_name, function_name in element_types:
    if 'Forecast' is section_name:
        for day in settings[section_name].sections:
            for sub_section in settings[section_name][day].sections:
                new_element = getattr(elements, function_name)(settings[section_name][day], sub_section, background_colour)
                element_list.append(new_element)
    else:
        for sub_section in settings[section_name].sections:
            new_element = getattr(elements, function_name)(settings[section_name], sub_section, background_colour)
            element_list.append(new_element)

weather_underground = utils.Wunderground(settings, backlight)
indoor_sensor = utils.DHT11(settings['DHT11'])

screen_update = utils.screenUpdate(settings['Screen'])
database = utils.Database(settings['Database'])

while True:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            sys.exit()

        for element in element_list:
            element.handleEvent(event)
            backlight.handle_event(event)

    backlight.update_backlight()

    # Only update screen if backlight is on
    if backlight.state and screen_update.updateDue():

        for element in element_list:
            element.blank_surface()
            element.blit(screen)

            element.update_condition(weather_underground, sun_almanac, indoor_sensor)
            element.render()

        # Deal with any text alignments
        for element in element_list:
            if element.align_to_other is not None:
                for e in element_list:
                    if e.element_name == element.align_to_other:
                        element.pos = (e.surface.get_width() + element.align_base_pos, element.pos[1])

        # Blit the new surfaces
        for element in element_list:
            element.blit(screen)

        pygame.display.update()

        screen_update.updateDone()

    if database.updateDue():
        database.log_reading(weather_underground, indoor_sensor)

    pygame.time.Clock().tick(10)