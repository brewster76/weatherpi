import json
import os
import pickle
import pygame
import urllib
import time
import datetime
import syslog
import astral
import threading
import sqlite3

__author__ = 'nick'

CONDITIONS_FILE = 'conditions.p'

def accumulateLeaves(d, max_level=99):
    """Merges leaf options above a ConfigObj section with itself, accumulating the results.

    This routine is useful for specifying defaults near the root node,
    then having them overridden in the leaf nodes of a ConfigObj.

    d: instance of a configobj.Section (i.e., a section of a ConfigObj)

    Returns: a dictionary with all the accumulated scalars, up to max_level deep,
    going upwards

    Example: Supply a default color=blue, size=10. The section "dayimage" overrides the former:

    >>> import configobj
    >>> c = configobj.ConfigObj({"color":"blue", "size":10, "dayimage":{"color":"red", "position":{"x":20, "y":30}}});
    >>> print accumulateLeaves(c["dayimage"])
    {'color': 'red', 'size': 10}
    >>> print accumulateLeaves(c["dayimage"], max_level=0)
    {'color': 'red'}
    >>> print accumulateLeaves(c["dayimage"]["position"])
    {'color': 'red', 'size': 10, 'y': 30, 'x': 20}
    >>> print accumulateLeaves(c["dayimage"]["position"], max_level=1)
    {'color': 'red', 'y': 30, 'x': 20}
    """

    import configobj

    # Use recursion. If I am the root object, then there is nothing above
    # me to accumulate. Start with a virgin ConfigObj
    if d.parent is d :
        cum_dict = configobj.ConfigObj()
    else:
        if max_level:
            # Otherwise, recursively accumulate scalars above me
            cum_dict = accumulateLeaves(d.parent, max_level-1)
        else:
            cum_dict = configobj.ConfigObj()

    # Now merge my scalars into the results:
    merge_dict = {}
    for k in d.scalars :
        merge_dict[k] = d[k]
    cum_dict.merge(merge_dict)
    return cum_dict


def listToTuple(*lists):
    """Converts a list of strings to a tuple of integers"""
    new_list = []

    for list in lists:
        for item in list:
            new_list.append(int(item))

    return tuple(new_list)

def areWePi():
    import platform

    return (platform.machine() == 'armv7l')


class Wunderground(object):
    """Handles getting forecasts out of Weather Underground"""

    def __init__(self, conf_settings, backlight):
        self.backlight = backlight

        self.api_key = conf_settings['Wunderground']['api_key']

        # URLs
        self.forecast_url = conf_settings['Wunderground']['forecast_url'] % self.api_key
        self.conditions_url = conf_settings['Wunderground']['conditions_url'] % self.api_key
        self.offline = conf_settings['Wunderground'].as_bool('offline')

        self.conditions = self.forecast = None

        self.update_interval = {}
        self.update_interval['background'] = int(conf_settings['Wunderground']['background_update'])
        self.update_interval['forecast'] =   int(conf_settings['Wunderground']['forecast_update'])
        self.update_interval['conditions'] = int(conf_settings['Wunderground']['conditions_update'])
        self.threading_interval = 1     # sleep for 1 sec at a time

        self.last_update = {'forecast': 0, 'conditions': 0}

        # Ensure conditions and forecast have a value before going to background updating
        self.refresh()

        thread = threading.Thread(target=self.run, args=())
        thread.daemon = True                            # Daemonize thread
        thread.start()                                  # Start the execution

    def updateRequired(self, update_type):
        if self.backlight.state is False:
            # Only update if background_update interval reached
            if time.time() - self.last_update[update_type] < self.update_interval['background']:
                return False

        # Backlight is on
        if time.time() - self.last_update[update_type] < self.update_interval[update_type]:
            return False

        syslog.syslog(syslog.LOG_INFO, "Updating %s from weather underground" % update_type)

        return True


    def updateForecast(self):
        if self.updateRequired('forecast') is False:
            return False

        newforecast = self.get_json(self.forecast_url)
        if newforecast is not None:
            self.forecast = newforecast['forecast']['simpleforecast']['forecastday']

            for i in range(0, len(self.forecast)):
                self.forecast[i]['high_low'] = "%s / %s" % (self.forecast[i]['high']['celsius'],
                                                              self.forecast[i]['low']['celsius'])

            self.last_update['forecast'] = time.time()

            return True

        syslog.syslog(syslog.LOG_INFO, "Unable to update forecast from WUnderground")

        return False

    def updateConditions(self):
        if self.updateRequired('conditions') is False:
            return False

        newconditions = self.get_json(self.conditions_url)
        if newconditions is not None:
            self.conditions = newconditions['current_observation']

            new_wind = "%s, %.1f" % (self.conditions['wind_dir'], self.conditions['wind_mph'])
            self.conditions['new_wind'] = new_wind

            #
            # Update database file here
            #

            self.last_update['conditions'] = time.time()

            return True

        syslog.syslog(syslog.LOG_INFO, "Unable to update conditions from WUnderground")

        return False

    def refresh(self):
        if self.offline is False:

            # Update forecast and save new conditions if something has changed
            if (self.updateForecast() is True) and (self.updateConditions() is True):

                # Save for offline use
                if (self.forecast is not None) and (self.conditions is not None):
                    pickle.dump((self.forecast, self.conditions), open(CONDITIONS_FILE, 'wb'))

        if (self.forecast is None) or (self.conditions is None):
            # Load most recent data in case nothing found
            (self.forecast, self.conditions) = pickle.load(open(CONDITIONS_FILE, 'rb'))

    def run(self):
        while True:
            self.refresh()

            time.sleep(self.threading_interval)

    def get_json(self, url):
        try:
            response = urllib.urlopen(url)
        except IOError:
            syslog.syslog(syslog.LOG_DEBUG, "get_json(%s) returned IOError" % url)
            return None

        return json.loads(response.read())

    def summary(self):
        return "Conditions now: %s C, %s mbar, %s humidity, %s mm rain today" % (self.conditions['temp_c'],
                                                                                 self.conditions['pressure_mb'],
                                                                                 self.conditions['relative_humidity'],
                                                                                 self.conditions['precip_today_metric'])

class almanac(object):
    def __init__(self, settings):
        a = astral.Astral()
        a.solar_depression = 'civil'
        city = a[settings['location']]

        self.sun = city.sun(local=True)

    def refresh(self):
        pass

class backlight():
    def __init__(self, settings):

        self.on_command = settings['on_command']
        self.off_command = settings['off_command']
        self.timeout = int(settings['timeout'])
        self.state = False   # True = backlight on, False = backlight off
        self.pi = areWePi()

        self.on_off = []
        for section in settings['OnTime'].sections:
            on_time = datetime.datetime.strptime(settings['OnTime'][section]['on'], '%H:%M')
            off_time = datetime.datetime.strptime(settings['OnTime'][section]['off'], '%H:%M')
            weekday_only = None

            if 'weekdays_only' in settings['OnTime'][section]:
                weekday_only = settings['OnTime'][section].as_bool('weekdays_only')

            self.on_off.append((on_time, off_time, weekday_only))

        # Reset the timer and switch the backlight on
        self.reset_timer()

    def reset_timer(self):
        self.timer = time.time()

        if self.state is False:
            self.turnOnBacklight()

    def update_backlight(self):
        timenow = datetime.datetime.now().time()

        for (on_time, off_time, weekday_only) in self.on_off:
            if timenow > on_time.time() and timenow < off_time.time():
                if self.state is False:
                    if weekday_only:
                        if (datetime.datetime.today().weekday() < 5):
                            self.turnOnBacklight()

                    else:
                        self.turnOnBacklight()
                return

        if self.state is True:
            if (time.time() - self.timer) > self.timeout:
                self.turnOffBacklight()


    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONUP:
            self.reset_timer()

    def turnOnBacklight(self):
        self.state = True
        syslog.syslog(syslog.LOG_INFO, "Turning backlight on")

        if self.pi:
            os.system(self.on_command)

    def turnOffBacklight(self):
        self.state = False
        syslog.syslog(syslog.LOG_INFO, "Turning backlight off")

        if self.pi:
            os.system(self.off_command)

class screenUpdate:
    def __init__(self, conf_settings):
        self.update_interval = int(conf_settings['update'])
        self.last_updated = 0

    def updateDue(self):
        if (time.time() - self.update_interval) > self.last_updated:
            return True

        return False

    def updateDone(self):
        self.last_updated = time.time()

# Deal with the sqlite database
class Database():
    def __init__(self, database_path):
        self.db = sqlite3.connect(database_path)
        self.cursor = self.db.cursor()

        # Do we need to create a new table?
        try:
            self.cursor.execute("SELECT * from history LIMIT 1")
        except sqlite3.OperationalError:
            self.cursor.execute("CREATE TABLE history(date TEXT, time TEXT, temp REAL, pressure REAL, humidity REAL)")
            self.db.commit()
            print "Created new data table in database %s" % database_path

    def log_reading(self, data_tuple):
        """Saves reading to the database.
        Expects a dictionary in the format {'date': "dd/mm/yyyy", 'time': 'hh:mm', 'level': float value,
                                             'station': "Abingdon Lock', 'stream': "upstream"} """

        # Was a real record found?
        if (data_tuple['date'] is None) or (data_tuple['time'] is None):
            syslog.syslog(syslog.LOG_WARNING, "Database.log_reading - no data received")
            return

        self.cursor.execute("INSERT into history(date, time, temp, pressure, humidity) VALUES (?,?,?,?,?)",
                            (data_tuple['date'], data_tuple['time'], data_tuple['temp'],
                             data_tuple['pressure'], data_tuple['humidity']))
        self.db.commit()