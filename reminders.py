import httplib2
from datetime import date
from operator import itemgetter

from oauth2client import tools
from oauth2client.file import Storage
from oauth2client.client import OAuth2WebServerFlow, FlowExchangeError

from apiclient.discovery import build

from kivy.logger import Logger


REMINDERS_FILE = 'reminders.dat'
PICKLE_FILE = 'calendar.pkl'

USER_AGENT = 'reminders/v1.0'
FLOW_SCOPE = 'https://www.googleapis.com/auth/calendar.readonly'


class reminders():

    def __init__(self, settings):

        credentials = self._get_credentials(settings)

        http = httplib2.Http()
        http = credentials.authorize(http)

        self.service = build(serviceName='calendar', version='v3', http=http, developerKey='YOUR_DEVELOPER_KEY')

        self.calendar_identifier = self._get_calendar_identifier()

    def update(self):
        birthdays = []

        page_token = None
        while True:
            today = date.today()

            events = self.service.events().list(calendarId=self.calendar_identifier['id'],
                                                pageToken=page_token).execute()
            for event in events['items']:
                if 'date' in event['start']:
                    month = int(event['start']['date'][5:7])
                    day = int(event['start']['date'][8:10])
                    year = today.year
                    d = date(year, month, day)

                    delta = (d - today).days
                    if delta < 0:
                        year += 1
                        d = date(year, month, day)

                        delta = (d - today).days

                    birthdays.append({'date': d,
                                      'delta': delta,
                                      'summary': event['summary']})

            page_token = events.get('nextPageToken')
            if not page_token:
                break

        # Sort by time delta
        birthdays = sorted(birthdays, key=itemgetter('delta'))

        week_count = 0
        month_count = 0

        email = "<h2>Birthdays this week...</h2>\n"

        for b in birthdays:
            if b['delta'] <= 7:
                email += "<p>%s : %s</p>\n" % (b['date'].strftime('%a %d %b'), b['summary'])
                week_count += 1

        if week_count == 0:
            email += "<p>None!</p>\n"

        email += "<h2>Birthdays this month...</h2>\n"

        for b in birthdays:
            if b['delta'] <= 31 and b['delta'] > 7:
                email += "<p>%s : %s</p>\n" % (b['date'].strftime('%a %d %b'), b['summary'])
                month_count += 1

        if month_count == 0:
            email += "<p>None!</p>\n"

        email += "<br>"
        email += "<h3>This week: <strong>%d</strong>, this month: <strong>%d</strong></h3>\n" % (
        week_count, month_count)

        email += "<br>"

        print email

    def _get_credentials(self, settings):
        flow = OAuth2WebServerFlow(client_id=settings['client_id'], client_secret=settings['client_secret'],
                                   scope=FLOW_SCOPE, user_agent=USER_AGENT, redirect_uri='http://www.dajda.net')

        storage = Storage(REMINDERS_FILE)
        credentials = storage.get()
        if credentials is None or credentials.invalid == True:
            credentials = tools.run_flow(flow, storage)

        return credentials

    def _get_calendar_identifier(self):

        page_token = None

        while True:
            calendar_list = self.service.calendarList().list(pageToken=page_token).execute()

            for calendar_list_entry in calendar_list['items']:
                if calendar_list_entry['summary'].lower() == "birthdays":
                    if calendar_list_entry['description'].lower() == "birthdays and anniversaries":
                        calendar_identifier = {'id'          : calendar_list_entry['id'],
                                               'description' : calendar_list_entry['description']}

            page_token = calendar_list.get('nextPageToken')
            if not page_token:
                break

        return calendar_identifier