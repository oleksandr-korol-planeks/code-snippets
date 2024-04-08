import calendar
import logging
from datetime import timedelta

from appness_scope.constants import Frequency
from appness_scope.models import CustomScopeQuestion
from authentication.models import User
from django.conf import settings
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from social_django.utils import load_strategy

CALENDAR_NAME = "app"
CALENDAR_SUMMARY = "Contains events from app app"
WEEK_DURATION = 7

logger = logging.getLogger("django")


class GoogleCalendarService:
    def __init__(self, user: User) -> None:
        """Create a google calendar service for user with social authorization"""
        self.client_id = settings.SOCIAL_AUTH_GOOGLE_OAUTH2_KEY
        self.client_secret = settings.SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET
        self.user = user
        social = user.social_auth.get(provider="google-oauth2")
        token = social.get_access_token(load_strategy())
        credentials = Credentials.from_authorized_user_info(
            info={
                "access_token": token,
                "refresh_token": social.extra_data.get("refresh_token"),
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        self.service = build("calendar", "v3", credentials=credentials)
        self.calendar_id = self._get_calendar_for_user()

    def create_event(self, event: CustomScopeQuestion) -> None:
        """
        Inserts event to google calendar based on CustomScopeQuestion

        Args:
            event (CustomScopeQuestion): CustomScopeQuestion instance
        """
        payload = self._prepare_event_data(event)

        try:
            result = self.service.events().insert(calendarId=self.calendar_id, body=payload).execute()
            event.google_calendar_id = result["id"]
            event.save(update_fields=["google_calendar_id"])
        except Exception as error:
            logger.error(f"Error creating event: {error}")
            event.user.google_calendar_id = None
            event.user.save(update_fields=["google_calendar_id"])

    def delete_event(self, event: CustomScopeQuestion) -> None:
        """
        Deletes event from Google Calendar based on CustomScopeQuestion instance.

        Args:
            event (CustomScopeQuestion): CustomScopeQuestion instance
        """
        if not event.google_calendar_id:
            # If there is no Google Calendar ID, there is nothing to delete
            return
        try:
            self.service.events().delete(
                calendarId=self.calendar_id, eventId=event.google_calendar_id
            ).execute()
            event.google_calendar_id = None
            event.save(update_fields=["google_calendar_id"])
        except Exception as error:
            logging.error(f"Error deleting event: {error}")

    def update_event(self, event: CustomScopeQuestion) -> None:
        """
        Updates event on Google Calendar based on CustomScopeQuestion instance.

        Creates new event if event.google_calendar_id is None

        Args:
            event (CustomScopeQuestion): CustomScopeQuestion instance
        """
        payload = self._prepare_event_data(event)
        if not event.google_calendar_id:
            # If there is no Google Calendar ID, create event
            self.create_event(payload)
        try:
            self.service.events().update(
                calendarId=self.calendar_id,
                eventId=event.google_calendar_id,
                body=payload,
            ).execute()
        except Exception as error:
            logging.error(f"Error updating event: {error}")

    @staticmethod
    def _prepare_event_data(event: CustomScopeQuestion) -> dict:
        """Convert our custom action to a Google Calendar event

        [Api docs](https://developers.google.com/calendar/api/guides/create-events)

        [recurrence specs](https://datatracker.ietf.org/doc/html/rfc5545#section-3.8.5)
        """
        payload = {"summary": event.title}
        event_time = event.event_time or settings.DEFAULT_TIME_FOR_EVENTS
        tz = event.user.timezone or "UTC"
        event_start = event.created_at.replace(hour=event_time.hour, minute=event_time.minute, second=event_time.second)
        event_duration = event.score or settings.DEFAULT_SCORE
        payload["start"] = {
            "dateTime": f"{event_start.strftime('%Y-%m-%dT%H:%M:%S')}",
            "timeZone": tz,
        }
        payload["end"] = {
            "dateTime": f"{(event_start + timedelta(minutes=event_duration)).strftime('%Y-%m-%dT%H:%M:%S')}",
            "timeZone": tz,
        }
        if event.frequency == Frequency.DAILY.name:
            payload["recurrence"] = ["RRULE:FREQ=DAILY;"]
        if event.frequency == Frequency.MONTHLY.name:
            # * In case of monthly event we can setup for specific date
            if event.event_day:
                event_start = event_start.replace(day=event.event_day)
                payload["start"] = {
                    "dateTime": f"{event_start.strftime('%Y-%m-%dT%H:%M:%S')}",
                    "timeZone": tz,
                }
                payload["end"] = {
                    "dateTime": f"{(event_start + timedelta(minutes=event_duration)).strftime('%Y-%m-%dT%H:%M:%S')}",
                    "timeZone": tz,
                }
            payload["recurrence"] = ["RRULE:FREQ=MONTHLY;"]
        if event.frequency == Frequency.WEEKLY.name:
            # * Here we need to calculate how much days before first calendar week from schedule appear
            day = event.created_at.weekday()
            target_days = [getattr(calendar, item) for item in event.schedule]
            days_difference = [(target_day - day + WEEK_DURATION) % WEEK_DURATION for target_day in target_days]
            days_difference.sort()
            # * Step event start to first day from schedule
            event_start = event_start + timedelta(days=days_difference[0])
            payload["start"] = {
                "dateTime": f"{event_start.strftime('%Y-%m-%dT%H:%M:%S')}",
                "timeZone": tz,
            }
            payload["end"] = {
                "dateTime": f"{(event_start + timedelta(minutes=event_duration)).strftime('%Y-%m-%dT%H:%M:%S')}",
                "timeZone": tz,
            }
            day_list = ",".join([item[:2] for item in event.schedule])
            payload["recurrence"] = [f"RRULE:FREQ=WEEKLY;BYDAY={day_list};"]
        return payload

    def _get_calendar_for_user(self) -> int:
        """
        Create a calendar for user in Google Calendar if it doesn't exist already.
        Store Google Calendar id in user model and return it.

        Returns:
            int: Google Calendar id

        Raises:
            Exception: If there is an error creating calendar
        """
        if self.user.google_calendar_id:
            return self.user.google_calendar_id
        try:
            calendar = (
                self.service.calendars()
                .insert(
                    body={
                        "summary": CALENDAR_NAME,
                        "description": CALENDAR_SUMMARY,
                    }
                )
                .execute()
            )
            self.user.google_calendar_id = calendar["id"]
            self.user.save(update_fields=["google_calendar_id"])
            return calendar["id"]
        except Exception as error:
            logging.error(f"Error creating calendar: {error}")
