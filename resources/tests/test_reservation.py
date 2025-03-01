import datetime
import pytest

import arrow
from django.core.exceptions import ValidationError
from django.utils.translation import activate
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from resources.enums import UnitAuthorizationLevel
from resources.models import (
    Day,
    Period,
    Reservation,
    ReservationMetadataSet,
    Resource,
    ResourceType,
    Unit,
    UnitAuthorization,
    ReservationHomeMunicipalityField,
    ReservationHomeMunicipalitySet,
)


class ReservationTestCase(TestCase):

    def setUp(self):
        u1 = Unit.objects.create(name='Unit 1', id='unit_1', time_zone='Europe/Helsinki')
        u2 = Unit.objects.create(name='Unit 2', id='unit_2', time_zone='Europe/Helsinki')
        rt = ResourceType.objects.create(name='Type 1', id='type_1', main_type='space')
        Resource.objects.create(name='Resource 1a', id='r1a', unit=u1, type=rt)
        Resource.objects.create(name='Resource 1b', id='r1b', unit=u1, type=rt)
        Resource.objects.create(name='Resource 2a', id='r2a', unit=u2, type=rt)
        Resource.objects.create(name='Resource 2b', id='r2b', unit=u2, type=rt)

        p1 = Period.objects.create(start='2116-06-01', end='2116-09-01', unit=u1, name='')
        p2 = Period.objects.create(start='2116-06-01', end='2116-09-01', unit=u2, name='')
        p3 = Period.objects.create(start='2116-06-01', end='2116-09-01', resource_id='r1a', name='')
        Day.objects.create(period=p1, weekday=0, opens='08:00', closes='22:00')
        Day.objects.create(period=p2, weekday=1, opens='08:00', closes='16:00')
        Day.objects.create(period=p3, weekday=0, opens='08:00', closes='18:00')

        u1.update_opening_hours()
        u2.update_opening_hours()

    def test_opening_hours(self):
        r1a = Resource.objects.get(id='r1a')
        r1b = Resource.objects.get(id='r1b')

        date = arrow.get('2116-06-01').date()
        end = arrow.get('2116-06-02').date()
        days = r1a.get_opening_hours(begin=date, end=end)  # Monday
        hours = days[date][0]  # first day object of chosen days
        self.assertEqual(hours['opens'].time(), datetime.time(8, 00))
        self.assertEqual(hours['closes'].time(), datetime.time(18, 00))

        days = r1b.get_opening_hours(begin=date, end=end)  # Monday
        hours = days[date][0]  # first day object of chosen days
        self.assertEqual(hours['opens'].time(), datetime.time(8, 00))
        self.assertEqual(hours['closes'].time(), datetime.time(22, 00))

    def test_reservation(self):
        r1a = Resource.objects.get(id='r1a')
        r1b = Resource.objects.get(id='r1b')

        tz = timezone.get_current_timezone()
        begin = tz.localize(datetime.datetime(2116, 6, 1, 8, 0, 0))
        end = begin + datetime.timedelta(hours=2)

        reservation = Reservation.objects.create(resource=r1a, begin=begin, end=end)
        reservation.clean()

        # Attempt overlapping reservation
        with self.assertRaises(ValidationError):
            reservation = Reservation(resource=r1a, begin=begin, end=end)
            reservation.clean()

        valid_begin = begin + datetime.timedelta(hours=3)
        valid_end = end + datetime.timedelta(hours=3)

        # Attempt incorrectly aligned begin time
        with self.assertRaises(ValidationError):
            reservation = Reservation(resource=r1a, begin=valid_begin + datetime.timedelta(minutes=1), end=valid_end)
            reservation.clean()

        # Attempt incorrectly aligned end time
        with self.assertRaises(ValidationError):
            reservation = Reservation(resource=r1a, begin=valid_begin, end=valid_end + datetime.timedelta(minutes=1))
            reservation.clean()

        # Attempt reservation that starts before the resource opens
        # Should not raise an exception as this check isn't included in model clean
        reservation = Reservation(
            resource=r1a,
            begin=begin - datetime.timedelta(hours=1),
            end=begin
        )
        reservation.clean()

        begin = tz.localize(datetime.datetime(2116, 6, 1, 16, 0, 0))
        end = begin + datetime.timedelta(hours=2)

        # Make a reservation that ends when the resource closes
        reservation = Reservation(resource=r1a, begin=begin, end=end)
        reservation.clean()

        # Attempt reservation that ends after the resource closes
        # Should not raise an exception as this check isn't included in model clean
        reservation = Reservation(resource=r1a, begin=begin, end=end + datetime.timedelta(hours=1))
        reservation.clean()


@pytest.mark.django_db
def test_need_manual_confirmation_metadata_set(resource_in_unit):
    data_set = ReservationMetadataSet.objects.get(name='default')
    assert data_set.supported_fields.exists()
    assert data_set.required_fields.exists()


@freeze_time('2115-04-02')
@pytest.mark.django_db
def test_valid_reservation_duration_with_slot_size(resource_with_opening_hours):
    resource_with_opening_hours.min_period = datetime.timedelta(hours=1)
    resource_with_opening_hours.slot_size = datetime.timedelta(minutes=30)
    resource_with_opening_hours.save()

    tz = timezone.get_current_timezone()
    begin = tz.localize(datetime.datetime(2115, 6, 1, 8, 0, 0))
    end = begin + datetime.timedelta(hours=2, minutes=30)

    reservation = Reservation(resource=resource_with_opening_hours, begin=begin, end=end)
    reservation.clean()


@freeze_time('2115-04-02')
@pytest.mark.django_db
def test_invalid_reservation_duration_with_slot_size(resource_with_opening_hours):
    activate('en')

    resource_with_opening_hours.min_period = datetime.timedelta(hours=1)
    resource_with_opening_hours.slot_size = datetime.timedelta(minutes=30)
    resource_with_opening_hours.save()

    tz = timezone.get_current_timezone()
    begin = tz.localize(datetime.datetime(2115, 6, 1, 8, 0, 0))
    end = begin + datetime.timedelta(hours=2, minutes=45)

    reservation = Reservation(resource=resource_with_opening_hours, begin=begin, end=end)

    with pytest.raises(ValidationError) as error:
        reservation.clean()
    assert error.value.code == 'invalid_time_slot'


@freeze_time('2115-04-02')
@pytest.mark.django_db
def test_admin_may_bypass_min_period(resource_with_opening_hours, user):
    """
    Admin users should be able to bypass min_period,
    and their minimum reservation time should be limited by slot_size
    """
    activate('en')

    # min_period is bypassed respecting slot_size restriction
    resource_with_opening_hours.min_period = datetime.timedelta(hours=1)
    resource_with_opening_hours.slot_size = datetime.timedelta(minutes=30)
    resource_with_opening_hours.save()

    tz = timezone.get_current_timezone()
    begin = tz.localize(datetime.datetime(2115, 6, 1, 8, 0, 0))
    end = begin + datetime.timedelta(hours=0, minutes=30)

    UnitAuthorization.objects.create(
        subject=resource_with_opening_hours.unit,
        level=UnitAuthorizationLevel.admin,
        authorized=user,
    )

    reservation = Reservation(resource=resource_with_opening_hours, begin=begin, end=end, user=user)
    reservation.clean()

    # min_period is bypassed and slot_size restriction is violated
    resource_with_opening_hours.slot_size = datetime.timedelta(minutes=25)
    resource_with_opening_hours.save()

    with pytest.raises(ValidationError) as error:
        reservation.clean()
    assert error.value.code == 'invalid_time_slot'

@pytest.mark.django_db
def test_reservation_home_municipality_field_str():
    home_municipality_field = ReservationHomeMunicipalityField.objects.create(name='test municipality')
    assert str(home_municipality_field) == 'test municipality'

@pytest.mark.django_db
def test_reservation_home_municipality_set_str():
    home_municipality_set = ReservationHomeMunicipalitySet.objects.create(name='test municipality set')
    assert str(home_municipality_set) == 'test municipality set'



@pytest.mark.parametrize('virtual_address', (
    None,
    'jokin://linkki/jonnekkin'
))
@pytest.mark.django_db
def test_reservation_notification_template_takes_place_virtually(resource_in_unit, virtual_address):

    tz = timezone.get_current_timezone()
    begin = tz.localize(datetime.datetime(2115, 6, 1, 8, 0, 0))
    end = begin + datetime.timedelta(hours=0, minutes=30)

    reservation = Reservation(
        resource=resource_in_unit,
        takes_place_virtually=True,
        virtual_address=virtual_address,
        begin=begin,
        end=end
    )
    context = reservation.get_notification_context('fi')
    assert 'takes_place_virtually' in context
    if virtual_address:
        assert 'virtual_address' in context
    else:
        assert 'virtual_address' not in context
