import datetime
import json
import os
import pickle
import pygame
import sqlite3
import syslog
import threading
import time
import urllib

try:
    import astral
except ImportError:
    pass

__author__ = 'nick'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONDITIONS_FILE = BASE_DIR + '/conditions.p'
SEMAPHORE_FILE = '/tmp/DHT22'

def settings_path(path):
    """Returns path if it's an absolute path, otherwise adds base directory of source file to beginning"""
    return os.path.join(BASE_DIR, path)

def pass_error_wrapper(gen):
    while True:
        try:
            yield next(gen)
        except StopIteration:
            raise
        except NameError as e:
            print(e)
            raise StopIteration


class eventQueue:
    """Handles input events either from pygame, or the touchscreen driver if we're running on the Raspberry pi"""
    def __init__(self):
        self.touchscreen = None

        if areWePi():
            import ft5406
            self.touchscreen = ft5406.Touchscreen()

    def __iter__(self):
        return self

    def next(self):
        if self.touchscreen is None:
            # No touchscreen - use the pygame event queue
            for event in pygame.event.get():
                return event

            # No events remaining
            raise StopIteration

        for touch in self.touchscreen.poll():
            if touch.slot == 0:
                if touch.valid is True:
                    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, {'pos': (touch.x, touch.y)})
                else:
                    return pygame.event.Event(pygame.MOUSEBUTTONUP, {'pos': (touch.x, touch.y)})

        # No events remaining
        raise StopIteration

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


class DHT11(object):
    """Periodically takes reads from a DHT11 type temperature and pressure sensor"""

    def __init__(self, conf_settings):
        self.threading_interval = int(conf_settings['update'])
        self.oldest_reading = int(conf_settings['oldest'])

        self.temperature = None
        self.humidity = None

        thread = threading.Thread(target=self.run, args=())
        thread.daemon = True                            # Daemonize thread
        thread.start()                                  # Start the execution

    def refresh(self):
        self.temperature = None
        self.humidity = None

        try:
            sensor_reading = pickle.load(open(SEMAPHORE_FILE, 'rb'))

            if time.time() - sensor_reading['time'] < self.oldest_reading:
                self.temperature = sensor_reading['temperature']
                self.humidity = sensor_reading['humidity']
        except IOError:
            pass

    def run(self):
        while True:
            self.refresh()

            time.sleep(self.threading_interval)

class Wunderground(object):
    """Handles getting forecasts out of Weather Underground"""

    def __init__(self, conf_settings, backlight):
        self.backlight = backlight

        self.api_key = conf_settings['Wunderground']['api_key']

        # URLs
        self.forecast_url = conf_settings['Wunderground']['forecast_url'] % self.api_key
        self.conditions_url = conf_settings['Wunderground']['conditions_url'] % self.api_key
        self.offline = conf_settings['Wunderground'].as_bool('offline')

        if self.offline is True:
            print "Weather forecasting is offline"

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
        if self.backlight is not None:
            if self.backlight.state is False:
                # Only update if background_update interval reached
                if time.time() - self.last_update[update_type] < self.update_interval['background']:
                    return False

        # Backlight is on, or not implemented (Kivy Weather)
        if time.time() - self.last_update[update_type] < self.update_interval[update_type]:
            return False

        syslog.syslog(syslog.LOG_DEBUG, "Updating %s from weather underground" % update_type)

        return True


    def updateForecast(self):
        if self.updateRequired('forecast') is False:
            return False

        newforecast = self.get_json(self.forecast_url)
        if newforecast is not None:
            if 'forecast' in newforecast:
                self.forecast = newforecast['forecast']['simpleforecast']['forecastday']

                for i in range(0, len(self.forecast)):
                    self.forecast[i]['high_low'] = "%s / %s" % (self.forecast[i]['high']['celsius'],
                                                                  self.forecast[i]['low']['celsius'])

                self.last_update['forecast'] = time.time()

                return True

        # Not successful
        syslog.syslog(syslog.LOG_INFO, "Unable to update forecast from WUnderground")

        # Wait a minute before tryng again
        self.last_update['forecast'] += 60

        return False

    def updateConditions(self):
        if self.updateRequired('conditions') is False:
            return False

        newconditions = self.get_json(self.conditions_url)
        if newconditions is not None:
            try:
                self.conditions = newconditions['current_observation']
            except KeyError:
                print "updateConditions():"
                print newconditions
                raise KeyError('current_observation')

            new_wind = "%s, %.1f" % (self.conditions['wind_dir'], self.conditions['wind_mph'])
            self.conditions['new_wind'] = new_wind

            self.last_update['conditions'] = time.time()

            return True

        syslog.syslog(syslog.LOG_INFO, "Unable to update conditions from WUnderground")

        # Wait a minute before tryng again
        self.last_update['conditions'] += 60

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

        try:
            decoded_string = json.loads(response.read())
        except ValueError:
            syslog.syslog(syslog.LOG_DEBUG, "json.loads() returned ValueError")
            return None

        return decoded_string

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
        self.brightness_command = settings['brightness_command']
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
        """Returns true if backlight switched off during call"""
        timenow = datetime.datetime.now().time()

        for (on_time, off_time, weekday_only) in self.on_off:
            if timenow > on_time.time() and timenow < off_time.time():
                if self.state is False:
                    if weekday_only:
                        if (datetime.datetime.today().weekday() < 5):
                            self.turnOnBacklight()

                    else:
                        self.turnOnBacklight()

                return False

        if self.state is True:
            if self.timeout > 0:  # negative value means always on
                if (time.time() - self.timer) > self.timeout:
                    self.turnOffBacklight()
                    return True

        return False

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.reset_timer()

    def turnOnBacklight(self):
        self.state = True
        syslog.syslog(syslog.LOG_DEBUG, "Turning backlight on")

        if self.pi:
            os.system(self.on_command)

    def turnOffBacklight(self):
        self.state = False
        syslog.syslog(syslog.LOG_DEBUG, "Turning backlight off")

        if self.pi:
            os.system(self.off_command)

    def setBrightness(self, brightness):
        if self.pi:
            os.system(self.brightness_command % brightness)

    def setTimeout(self, new_timeout):
        self.timeout = new_timeout

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
    def __init__(self, database_settings):
        if 'update' in database_settings:
            self.update_interval = int(database_settings['update'])
        else:
            self.update_interval = None

        self.last_updated = None

        self.db = sqlite3.connect(database_settings['filename'])

        self.cursor = self.db.cursor()

        self.schema = [['datetime', 'REAL'],
                       ['temp',     'REAL'],
                       ['pressure', 'REAL'],
                       ['humidity', 'REAL']]

        # Do we need to create a new table?
        try:
            self.cursor.execute("SELECT * from history LIMIT 1")
        except sqlite3.OperationalError:
            self.cursor.execute("CREATE TABLE history(%s)" % self._create_table_text())
            self.db.commit()
            syslog.syslog(syslog.LOG_INFO, "Created new data table in database %s" % database_settings['filename'])

    def log_reading(self, weather_underground, indoor_sensor):
        data_dict = {}

        data_dict['humidity'] = indoor_sensor.humidity
        data_dict['temp'] = indoor_sensor.temperature
        data_dict['pressure'] = weather_underground.conditions['pressure_mb']

        self.write_reading(data_dict)
        self.last_updated = time.time()

    def write_reading(self, data_dict):
        """Saves reading to the database.
        Expects a dictionary in the format {'datetime': 12345678, 'level': float value,
                                             'station': "Abingdon Lock', 'stream': "upstream"} """

        # Time specified?
        if not self._time_specified(data_dict):
            data_dict['datetime'] = int(time.time())

        field_list = ', '.join(data_dict.keys())
        value_list = ('?,'*len(data_dict))[:-1]
        value_tuple = tuple(data_dict.values())

        sql_string = "INSERT into history (%s) VALUES (%s)" % (field_list, value_list)

        self.cursor.execute(sql_string, value_tuple)
        self.db.commit()

        syslog.syslog(syslog.LOG_DEBUG, "Wrote to database (%d)" % data_dict['datetime'])

    def updateDue(self):
        if self.last_updated is None:
            return True

        if self.update_interval is not None:
            if (time.time() - self.update_interval) > self.last_updated:
                return True

        return False

    def query(self, fields):
        """Fields = list of fields to be returned by query, e.g. ['datetime', 'temp']

        returns a list in format: [[1234, 1235, ...], [26.1, 26.2, ...]]
        """
        sql_string = "SELECT %s FROM history" % ', '.join(fields)

        self.cursor.execute(sql_string)
        rows = self.cursor.fetchall()

        query_list = []

        for i in range(len(fields)):

            new_list = []

            for row in rows:
                new_list.append(row[i])

            query_list.append(new_list)

        return query_list

    def _time_specified(self, data_dict):
        if 'datetime' in data_dict:
            if data_dict['datetime'] is not None:
                return True

        return False

    def _create_table_text(self):
        text = ""

        for i in range(0, len(self.schema)):
            if i > 0:
                text = text + ", "

            text = text + "%s %s" % (self.schema[i][0], self.schema[i][1])

        return text
