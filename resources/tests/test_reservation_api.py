import pytest
import datetime
import re
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.core import mail
from django.test.utils import override_settings
from django.utils import dateparse, timezone, translation
from guardian.shortcuts import assign_perm, remove_perm
from freezegun import freeze_time
from icalendar import Calendar
from parler.utils.context import switch_language
from rest_framework.exceptions import ErrorDetail

from caterings.models import CateringOrder, CateringProvider

from resources.enums import UnitAuthorizationLevel
from resources.models import (
    Period, Day, Reservation, ReservationBulk,
    Resource, ResourceGroup, ReservationMetadataField,
    ReservationMetadataSet, UnitAuthorization, ReservationReminder
)
from resources.models.utils import build_reservations_ical_file, RespaNotificationAction
from notifications.models import NotificationTemplate, NotificationType
from notifications.tests.utils import check_received_mail_exists
from .utils import (
    check_disallowed_methods, assert_non_field_errors_contain,
    assert_response_objects, MAX_QUERIES, assert_translated_response_contains
)


DEFAULT_RESERVATION_EXTRA_FIELDS = ('reserver_name', 'reserver_phone_number', 'reserver_address_street',
                                    'reserver_address_zip', 'reserver_address_city', 'billing_address_street',
                                    'billing_address_zip', 'billing_address_city', 'company', 'event_description',
                                    'reserver_id', 'number_of_participants', 'reserver_email_address')

DEFAULT_REQUIRED_RESERVATION_EXTRA_FIELDS = ('reserver_name', 'reserver_phone_number', 'reserver_address_street',
                                             'reserver_address_zip', 'reserver_address_city', 'event_description',
                                             'reserver_id', 'reserver_email_address')

User = get_user_model()


@pytest.fixture
def list_url():
    return reverse('reservation-list')


@pytest.fixture
def detail_url(reservation):
    return reverse('reservation-detail', kwargs={'pk': reservation.pk})

@pytest.fixture
def recurring_url():
    return reverse('reservationbulk-list')

@pytest.mark.django_db
@pytest.fixture(autouse=True)
def day_and_period(resource_in_unit):
    period = Period.objects.create(
        start='2115-04-01',
        end='2115-05-01',
        resource_id=resource_in_unit.id,
        name='test_period'
    )
    Day.objects.create(period=period, weekday=3, opens='08:00', closes='16:00')
    resource_in_unit.update_opening_hours()


@pytest.mark.django_db
@pytest.fixture
def reservation_data(resource_in_unit):
    return {
        'resource': resource_in_unit.pk,
        'begin': '2115-04-04T11:00:00+02:00',
        'end': '2115-04-04T12:00:00+02:00'
    }


@pytest.fixture
def reservation_data_extra(reservation_data):
    extra_data = reservation_data.copy()
    extra_data.update({
        'reserver_name': 'Test Reserver',
        'reserver_phone_number': '0700555555',
        'reserver_address_street': 'Omenatie 102',
        'reserver_address_zip': '00930',
        'reserver_address_city': 'Helsinki',
        'event_description': 'a very secret meeting',
        'reserver_id': '1234567-8',
        'number_of_participants': 5000,
        'billing_address_street': 'Pihlajakatu',
        'billing_address_zip': '00001',
        'billing_address_city': 'Tampere',
        'company': 'a very secret association',
        'reserver_email_address': 'test.reserver@test.com',
        'reservation_extra_questions': 'Some question here',
    })
    return extra_data

@pytest.mark.django_db
@pytest.fixture
def recurring_reservation_data(resource_in_unit4_1):
    return {
        'resource': resource_in_unit4_1.pk,
        'reserver_name': 'Test Reserver',
        'reserver_email_address': 'test.reserver@test.com',
        'reserver_phone_number': '0700555555',
        'reserver_address_street': 'Mansikkatie 11',
        'reserver_address_zip': '20180',
        'reserver_address_city': 'Turku',
        'reservation_stack': [{
            'begin': '2115-04-04T11:00:00+02:00',
             'end': '2115-04-04T12:00:00+02:00',
        },{
            'begin': '2115-04-05T11:00:00+02:00',
            'end': '2115-04-05T12:00:00+02:00',
        },{
            'begin': '2115-04-06T11:00:00+02:00',
            'end': '2115-04-06T12:00:00+02:00'
        }]
    }

@pytest.mark.django_db
@pytest.fixture
def reservation(resource_in_unit, user):
    return Reservation.objects.create(
        resource=resource_in_unit,
        begin='2115-04-04T09:00:00+02:00',
        end='2115-04-04T10:00:00+02:00',
        user=user,
        event_subject='some fancy event',
        host_name='esko',
        reserver_name='martta',
        state=Reservation.CONFIRMED
    )


@pytest.fixture
def reservation2(resource_in_unit2, user):
    return Reservation.objects.create(
        resource=resource_in_unit2,
        begin='2115-04-05T09:00:00+02:00',
        end='2115-04-05T10:00:00+02:00',
        user=user,
        event_subject='not so fancy event',
        host_name='markku',
        reserver_name='pirkko',
        state=Reservation.CONFIRMED
    )


@pytest.fixture
def reservation3(resource_in_unit2, user2):
    # the same as reservation2 but different user
    return Reservation.objects.create(
        resource=resource_in_unit2,
        begin='2115-04-05T09:00:00+02:00',
        end='2115-04-05T10:00:00+02:00',
        user=user2,
        event_subject='not so fancy event',
        host_name='markku',
        reserver_name='pirkko',
        state=Reservation.CONFIRMED
    )


@pytest.mark.django_db
@pytest.fixture
def reservation4(resource_in_unit4_1, user):
    # reservation in unit 4 which has overlap restriction
    return Reservation.objects.create(
        resource=resource_in_unit4_1,
        begin='2115-04-04T09:00:00+02:00',
        end='2115-04-04T10:00:00+02:00',
        user=user,
        reserver_name='testi testaaja',
        state=Reservation.CONFIRMED
    )


@pytest.mark.django_db
@pytest.fixture
def reservation5(resource_in_unit4_2, user):
    # reservation in unit 4 which has overlap restriction
    return Reservation.objects.create(
        resource=resource_in_unit4_2,
        begin='2115-04-04T12:00:00+02:00',
        end='2115-04-04T13:00:00+02:00',
        user=user,
        reserver_name='testi testaaja',
        state=Reservation.CONFIRMED
    )


@pytest.mark.django_db
@pytest.fixture
def other_resource(space_resource_type, test_unit):
    return Resource.objects.create(
        type=space_resource_type,
        authentication="none",
        name="other resource",
        unit=test_unit,
        id="otherresourceid",
    )


@pytest.fixture
def reservations_in_all_states(resource_in_unit, user):
    all_states = (
        Reservation.CANCELLED, Reservation.CONFIRMED, Reservation.DENIED, Reservation.REQUESTED,
        Reservation.WAITING_FOR_PAYMENT, Reservation.WAITING_FOR_CASH_PAYMENT
    )
    reservations = dict()
    for i, state in enumerate(all_states, 1):
        reservations[state] = Reservation.objects.create(
            resource=resource_in_unit,
            begin='2115-04-0%sT09:00:00+02:00' % i,
            end='2115-04-0%sT10:00:00+02:00' % i,
            user=user,
            state=state
        )
    return reservations


@pytest.fixture
def reservations_in_all_states2(resource_in_unit2, user):
    all_states = (
        Reservation.CANCELLED, Reservation.CONFIRMED, Reservation.DENIED, Reservation.REQUESTED,
        Reservation.WAITING_FOR_PAYMENT, Reservation.WAITING_FOR_CASH_PAYMENT
    )
    reservations = dict()
    for i, state in enumerate(all_states, 1):
        reservations[state] = Reservation.objects.create(
            resource=resource_in_unit2,
            begin='2115-04-0%sT09:00:00+02:00' % i,
            end='2115-04-0%sT10:00:00+02:00' % i,
            user=user,
            state=state
        )
    return reservations


@pytest.fixture
def reservation_created_notification():
    with translation.override('en'):
        return NotificationTemplate.objects.create(
            type=NotificationType.RESERVATION_CREATED,
            is_default_template=True,
            short_message='Normal reservation created short message.',
            subject='Normal reservation created subject.',
            body='Normal reservation created body.',
        )

@pytest.fixture
def reservation_created_by_official_notification():
    with translation.override('fi'): # Staff user preferred language is always fallback. (fi)
        return NotificationTemplate.objects.create(
            type=NotificationType.RESERVATION_CREATED_BY_OFFICIAL,
            is_default_template=True,
            short_message = 'Virkailija on luonut varauksen lyhyt viesti.',
            subject = 'Virkailija on luonut varauksen aihe.',
            body = 'Virkailija on luonut varauksen viesti.'
        )

@pytest.fixture
def reservation_modified_by_official_notification():
    with translation.override('en'):
        return NotificationTemplate.objects.create(
            type=NotificationType.RESERVATION_MODIFIED_BY_OFFICIAL,
            is_default_template=True,
            short_message='reservation modified by official short message.',
            subject='reservation modified by official subject.',
            body='reservation modified by official body.',
        )


@pytest.fixture
def reservation_modified_notification():
    with translation.override('en'):
        return NotificationTemplate.objects.create(
            type=NotificationType.RESERVATION_MODIFIED,
            is_default_template=True,
            short_message='reservation modified short message.',
            subject='reservation modified subject.',
            body='reservation modified body.',
        )


@pytest.mark.django_db
def test_disallowed_methods(all_user_types_api_client, list_url):
    """
    Tests that PUT, PATCH and DELETE aren't allowed to reservation list endpoint.
    """
    check_disallowed_methods(all_user_types_api_client, (list_url, ), ('put', 'patch', 'delete'))


@pytest.mark.django_db
def test_reservation_requires_authenticated_user(api_client, list_url, reservation_data):
    """
    Tests that an unauthenticated user cannot create a reservation.
    """
    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 401


@pytest.mark.django_db
def test_authenticated_user_can_make_reservation(api_client, list_url, reservation_data, resource_in_unit, user):
    """
    Tests that an authenticated user can create a reservation.
    """
    api_client.force_authenticate(user=user)

    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201, "Request failed with: %s" % (str(response.content, 'utf8'))
    reservation = Reservation.objects.filter(user=user).latest('created_at')
    assert reservation.resource == resource_in_unit
    assert reservation.begin == dateparse.parse_datetime('2115-04-04T11:00:00+02:00')
    assert reservation.end == dateparse.parse_datetime('2115-04-04T12:00:00+02:00')


@pytest.mark.django_db
def test_authenticated_user_can_modify_reservation(
        api_client, detail_url, reservation_data, resource_in_unit, user):
    """
    Tests that an authenticated user can modify her own reservation
    """
    api_client.force_authenticate(user=user)

    response = api_client.put(detail_url, data=reservation_data)
    assert response.status_code == 200
    reservation = Reservation.objects.get(pk=response.data['id'])
    assert reservation.resource == resource_in_unit
    assert reservation.begin == dateparse.parse_datetime('2115-04-04T11:00:00+02:00')
    assert reservation.end == dateparse.parse_datetime('2115-04-04T12:00:00+02:00')


@pytest.mark.django_db
def test_another_user_modifies_reservations(
        api_client, detail_url, reservation_data, resource_in_unit, user2):
    """
    Tests that an authenticated user can modify her own reservation
    """
    api_client.force_authenticate(user=user2)

    # No permission
    response = api_client.put(detail_url, data=reservation_data)
    assert response.status_code == 403

    # Explicit permission
    assign_perm('unit:can_modify_reservations', user2, resource_in_unit.unit)
    response = api_client.put(detail_url, data=reservation_data)
    assert response.status_code == 200

    reservation = Reservation.objects.get(pk=response.data['id'])
    assert reservation.resource == resource_in_unit
    assert reservation.begin == dateparse.parse_datetime('2115-04-04T11:00:00+02:00')
    assert reservation.end == dateparse.parse_datetime('2115-04-04T12:00:00+02:00')


@pytest.mark.django_db
def test_authenticated_user_can_delete_reservation(api_client, detail_url, reservation, user):
    """
    Tests that an authenticated user can delete her own reservation
    """

    api_client.force_authenticate(user=user)
    reservation_id = reservation.id
    response = api_client.delete(detail_url)
    assert response.status_code == 204
    assert Reservation.objects.filter(pk=reservation_id).count() == 1
    reservation.refresh_from_db()
    assert reservation.state == Reservation.CANCELLED


@pytest.mark.django_db
def test_reservation_limit_per_user(api_client, list_url, reservation, reservation_data, user):
    """
    Tests that a user cannot exceed her active reservation limit for one resource.
    """
    api_client.force_authenticate(user=user)

    # the user already has one reservation, making another reservation should not be possible as the active reservation
    # limit is one
    response = api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')

    assert response.status_code == 400
    assert_non_field_errors_contain(response, 'Maximum number of active reservations for this resource exceeded.')


@pytest.mark.django_db
def test_old_reservations_are_excluded(api_client, list_url, resource_in_unit, reservation_data, user):
    """
    Tests that a reservation in the past doesn't count when checking reservation limit.
    """

    # the user already has this reservation which is in the past.
    Reservation.objects.create(
        resource=resource_in_unit,
        begin=dateparse.parse_datetime('2005-04-07T09:00:00+02:00'),
        end=dateparse.parse_datetime('2005-04-07T10:00:00+02:00'),
        user=user,
    )
    api_client.force_authenticate(user=user)

    # making another reservation should be possible because the other reservation is in the past.
    response = api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')

    assert response.status_code == 201


@pytest.mark.django_db
def test_general_admins_have_no_reservation_limit(
        api_client, list_url, reservation, reservation_data,
        general_admin):
    """
    Tests that the reservation limits for a resource do not apply to staff.
    """
    api_client.force_authenticate(user=general_admin)

    # the admin already has one reservation, and should be able to make
    # a second one regardless of the fact that that the limit is one.
    response = api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')

    assert response.status_code == 201


@pytest.mark.django_db
def test_opening_hours(api_client, list_url, reservation_data, resource_group,
                       user):
    """
    Tests that a normal user cannot make reservations outside open hours.
    """
    api_client.force_authenticate(user=user)

    # invalid day
    reservation_data['begin'] = '2115-06-01T09:00:00+02:00'
    reservation_data['end'] = '2115-06-01T10:00:00+02:00'
    response = api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == 400
    assert_non_field_errors_contain(response, 'You must start and end the reservation during opening hours')

    # valid begin time, end time after closing time
    reservation_data['begin'] = '2115-04-04T10:00:00+02:00'
    reservation_data['end'] = '2115-04-04T21:00:00+02:00'
    response = api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == 400
    assert_non_field_errors_contain(response, 'You must start and end the reservation during opening hours')

    # begin time before opens, valid end time
    reservation_data['begin'] = '2115-04-04T05:00:00+02:00'
    reservation_data['end'] = '2115-04-04T10:00:00+02:00'
    response = api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == 400
    assert_non_field_errors_contain(response, 'You must start and end the reservation during opening hours')

    # If the user has explicit permission ignore opening hours, the reservation should
    # be allowed.
    reservation_data['end'] = '2115-04-04T07:00:00+02:00'
    resource = resource_group.resources.first()
    group = user.groups.create(name='test group')
    assign_perm('unit:can_ignore_opening_hours', group, resource.unit)
    response = api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == 201
    Reservation.objects.all().delete()
    remove_perm('unit:can_ignore_opening_hours', group, resource.unit)

    assign_perm('group:can_ignore_opening_hours', group, resource_group)
    response = api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == 201


@pytest.mark.django_db
def test_normal_user_cannot_make_reservation_longer_than_max_period(api_client, list_url, reservation_data, user):
    """
    Tests that a normal user cannot make reservations longer than the resource's max period.
    """
    api_client.force_authenticate(user=user)

    # the reservation's length is 3h (11 -> 14) while the maximum is 2h
    reservation_data['end'] = '2115-04-04T14:00:00+02:00'
    response = api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == 400
    assert_non_field_errors_contain(response, 'The maximum reservation length is')


@pytest.mark.django_db
def test_admin_can_make_reservation_outside_open_hours(
        api_client, list_url, reservation_data, general_admin):
    """
    Tests that a staff member can make reservations outside opening hours.

    Also tests that the resource's max period doesn't limit staff.
    """
    api_client.force_authenticate(user=general_admin)

    # begin time before opening time, end time after closing time, longer than max period 2h
    reservation_data['begin'] = '2115-04-04T05:00:00+02:00'
    reservation_data['end'] = '2115-04-04T21:00:00+02:00'
    response = api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == 201


@pytest.mark.django_db
def test_comments_are_only_for_admins(
        api_client, list_url, reservation_data,
        user, staff_user, general_admin):
    api_client.force_authenticate(user=user)
    reservation_data['comments'] = 'test comment'
    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 400

    # Try again with bare is_staff. Still DENIED.
    api_client.force_authenticate(user=staff_user)
    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 400

    api_client.force_authenticate(general_admin)
    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201

    response = api_client.get(response.data['url'])
    assert response.data['comments'] == 'test comment'

    api_client.force_authenticate(user=user)
    response = api_client.get(response.data['url'])
    assert 'comments' not in response.data


@pytest.mark.parametrize('user_fixture, expected_status', [
    (None, 401),
    ('user', 400),
    ('user2', 201),
    ('staff_user', 201),
    ('unit4_manager_user', 201),
])
@pytest.mark.django_db
def test_comments_can_be_created_by_correct_people_when_resource_sets_is_reservable_by_all(
        api_client, list_url, resource_in_unit, resource_in_unit3, reservation_data, user_fixture, expected_status,
        user, user2, staff_user, unit4_manager_user):
    """
    Tests that only staff users that have rights to some unit can create
    reservations for customers to a resource which has reservable_by_all_staff set to True.
    """
    # update resource metadata_set to include these fields.
    field_1 = ReservationMetadataField.objects.get(field_name='reserver_name')
    field_2 = ReservationMetadataField.objects.get(field_name='reserver_phone_number')
    field_3 = ReservationMetadataField.objects.get(field_name='reserver_email_address')
    metadata_set = ReservationMetadataSet.objects.create(
        name='updated_metadata',
    )
    metadata_set.supported_fields.set([field_1, field_2, field_3])
    resource_in_unit.reservation_metadata_set = ReservationMetadataSet.objects.get(name='updated_metadata')
    resource_in_unit.reservable_by_all_staff = True
    resource_in_unit.save()

    test_comment = 'test comment abc'
    reservation_data.update({
        'comments': test_comment,
        'reserver_email_address': 'test.reserver@test.com',
        'reserver_name': 'Veikko Varaaja'
    })

    if user_fixture:
        test_user = locals().get(user_fixture)
        if test_user == user2:
            # user2 is an admin in another unit.
            reservation_data.update({'reserver_email_address': user2.email})
            UnitAuthorization.objects.create(
                subject=resource_in_unit3.unit, level=UnitAuthorizationLevel.admin, authorized=test_user)
            test_user.is_staff = True
            test_user.save()

        api_client.force_authenticate(test_user)

    response = api_client.post(list_url, data=reservation_data)

    assert response.status_code == expected_status
    if response.status_code == 201:
        assert response.data['comments'] == test_comment


@pytest.mark.parametrize('user_fixture, expected_status_post, expected_status_put ', [
    (None, 401, 400),
    ('user', 400, 400),
    ('user2', 201, 200),
    ('staff_user', 201, 200),
    ('unit4_manager_user', 201, 200),
])
@pytest.mark.django_db
def test_comments_can_be_updated_by_correct_people_when_resource_sets_is_reservable_by_all(
        api_client, list_url, resource_in_unit, resource_in_unit3, reservation_data, user_fixture, expected_status_post, expected_status_put,
        user, user2, staff_user, unit4_manager_user):
    """
    Tests that only staff users that have rights to some unit, can create and update
    reservations that they've created for customers to a resource where reservable_by_all_staff is True.
    """
    # update resource metadata_set to include these fields.
    field_1 = ReservationMetadataField.objects.get(field_name='reserver_name')
    field_2 = ReservationMetadataField.objects.get(field_name='reserver_phone_number')
    field_3 = ReservationMetadataField.objects.get(field_name='reserver_email_address')
    metadata_set = ReservationMetadataSet.objects.create(
        name='updated_metadata',
    )
    metadata_set.supported_fields.set([field_1, field_2, field_3])
    resource_in_unit.reservation_metadata_set = ReservationMetadataSet.objects.get(name='updated_metadata')
    resource_in_unit.reservable_by_all_staff = True
    resource_in_unit.save()
    # create initial reservation
    reservation_data.update({
        'comments': 'test comment abc',
        'reserver_email_address': 'test.reserver@test.com',
        'reserver_name': 'Veikko Varaaja'
    })

    if user_fixture:
        test_user = locals().get(user_fixture)
        if test_user == user2:
            # user2 is an admin in another unit.
            UnitAuthorization.objects.create(
                subject=resource_in_unit3.unit, level=UnitAuthorizationLevel.admin, authorized=test_user)
            test_user.is_staff = True
            test_user.save()

        api_client.force_authenticate(test_user)

    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == expected_status_post
    if response.status_code == 201:
        reservation = Reservation.objects.filter(user=test_user).first()
        updated_comment = 'updated comment text'
        # update comment
        reservation_data.update({
            'comments': updated_comment
        })
        detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})
        response = api_client.put(detail_url, data=reservation_data, format='json')
        assert response.status_code == expected_status_put
        if response.status_code == 200:
            assert response.data['comments'] == updated_comment


@pytest.mark.django_db
def test_anon_and_other_users_cannot_see_virtual_event_data(api_client, reservation, user2):
    """
    Tests that anon and regular users besides the reserver cannot see virtual event data
    """
    reservation.takes_place_virtually = True
    reservation.virtual_address = 'some virtual address'
    reservation.save()

    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})

    # anon should not be able to see virtual data
    response = api_client.get(detail_url)
    assert 'takes_place_virtually' not in response.data
    assert 'virtual_address' not in response.data

    # other regular users besides the reserver should not be able to see virtual data
    api_client.force_authenticate(user=user2)
    response = api_client.get(detail_url)
    assert 'takes_place_virtually' not in response.data
    assert 'virtual_address' not in response.data


@pytest.mark.django_db
def test_reserver_can_see_virtual_event_data(api_client, reservation, user):
    """
    Tests that regular reserver can see virtual event data
    """
    reservation.takes_place_virtually = True
    reservation.virtual_address = 'some virtual address'
    reservation.save()

    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})
    api_client.force_authenticate(user=user)
    response = api_client.get(detail_url)
    assert 'takes_place_virtually' in response.data
    assert response.data['takes_place_virtually'] == True
    assert 'virtual_address' in response.data
    assert response.data['virtual_address'] == 'some virtual address'


@pytest.mark.django_db
def test_unit_managers_and_admins_can_see_virtual_event_data(
        api_client, reservation, staff_user, resource_in_unit):
    """
    Tests that unit managers and admins can see virtual event data
    """
    reservation.takes_place_virtually = True
    reservation.virtual_address = 'some virtual address'
    reservation.save()

    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})
    # unit manager
    UnitAuthorization.objects.create(
        subject=resource_in_unit.unit, level=UnitAuthorizationLevel.manager, authorized=staff_user)
    api_client.force_authenticate(user=staff_user)
    response = api_client.get(detail_url)
    assert 'takes_place_virtually' in response.data
    assert response.data['takes_place_virtually'] == True
    assert 'virtual_address' in response.data
    assert response.data['virtual_address'] == 'some virtual address'

    # unit admin
    UnitAuthorization.objects.create(
        subject=resource_in_unit.unit, level=UnitAuthorizationLevel.admin, authorized=staff_user)
    api_client.force_authenticate(user=staff_user)
    response = api_client.get(detail_url)
    assert 'takes_place_virtually' in response.data
    assert response.data['takes_place_virtually'] == True
    assert 'virtual_address' in response.data
    assert response.data['virtual_address'] == 'some virtual address'


@pytest.mark.django_db
def test_anon_and_regular_users_cannot_set_virtual_data(
        api_client, reservation, reservation_data, user, user2):
    """
    Tests that anon and regular users cannot set virtual event data
    """
    reservation_data['takes_place_virtually'] = True
    reservation_data['virtual_address'] = 'some virtual address'
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})
    # anon
    response = api_client.put(detail_url, reservation_data)
    assert response.status_code == 401
    # other regular user
    api_client.force_authenticate(user=user2)
    response = api_client.put(detail_url, reservation_data)
    assert response.status_code == 403
    # regular reserver
    api_client.force_authenticate(user=user)
    response = api_client.put(detail_url, reservation_data)
    assert response.status_code == 400


@pytest.mark.django_db
def test_managers_and_admin_users_can_set_virtual_data(
        api_client, reservation, reservation_data, resource_in_unit, staff_user):
    """
    Tests that unit manager and admin users can set virtual event data
    """
    reservation_data['takes_place_virtually'] = True
    reservation_data['virtual_address'] = 'some virtual address'
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})

    # unit manager
    UnitAuthorization.objects.create(
        subject=resource_in_unit.unit, level=UnitAuthorizationLevel.manager, authorized=staff_user)
    api_client.force_authenticate(user=staff_user)
    response = api_client.put(detail_url, reservation_data)
    assert response.status_code == 200
    # unit admin
    UnitAuthorization.objects.create(
        subject=resource_in_unit.unit, level=UnitAuthorizationLevel.admin, authorized=staff_user)
    api_client.force_authenticate(user=staff_user)
    response = api_client.put(detail_url, reservation_data)
    assert response.status_code == 200


@pytest.mark.django_db
def test_reserver_can_update_reservation_that_has_virtual_data(
        api_client, reservation, reservation_data, user):
    """
    Tests that regular reserver can update their reservation that has virtual event data
    without changing the virtual event data
    """
    reservation.takes_place_virtually = True
    reservation.virtual_address = 'some virtual address'
    reservation.save()

    reservation_data['number_of_participants'] = 3
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})
    api_client.force_authenticate(user=user)
    response = api_client.put(detail_url, reservation_data)
    assert response.status_code == 200


@pytest.mark.django_db
def test_superusers_can_see_created_at(api_client, reservation, staff_user):
    """Tests that superusers can see reservation created at"""

    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})

    staff_user.is_superuser = True
    staff_user.save()
    api_client.force_authenticate(user=staff_user)
    response = api_client.get(detail_url)
    assert 'created_at' in response.data
    assert response.data['created_at'] == reservation.created_at


@pytest.mark.parametrize('unit_perm', ['admin', 'manager', 'viewer'])
@pytest.mark.django_db
def test_unit_staff_can_see_created_at(
        api_client, reservation, staff_user, resource_in_unit, unit_perm):
    """Tests that unit staff can see reservation created at"""

    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})

    UnitAuthorization.objects.create(
        subject=resource_in_unit.unit, level=UnitAuthorizationLevel[unit_perm], authorized=staff_user)
    api_client.force_authenticate(user=staff_user)
    response = api_client.get(detail_url)
    assert 'created_at' in response.data
    assert response.data['created_at'] == reservation.created_at


@pytest.mark.django_db
def test_anon_and_regular_users_cannot_see_created_at(api_client, reservation, user, user2):
    """Tests that anon and regular users cannot see created at"""
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})

    response = api_client.get(detail_url)
    assert 'created_at' not in response.data

    api_client.force_authenticate(user=user)
    response = api_client.get(detail_url)
    assert 'created_at' not in response.data

    api_client.force_authenticate(user=user2)
    response = api_client.get(detail_url)
    assert 'created_at' not in response.data


@pytest.mark.django_db
def test_user_data_correct_and_only_for_admins(
        api_client, reservation, user, general_admin):
    """
    Tests that user object is returned within Reservation data and it is in the correct form.

    Also tests that only staff can see the user object.
    """
    api_client.force_authenticate(user=user)
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})
    response = api_client.get(detail_url)
    assert 'user' not in response.data

    api_client.force_authenticate(user=general_admin)
    response = api_client.get(detail_url)
    user_obj = response.data['user']
    assert len(user_obj) == 3
    assert user_obj['display_name'] == 'Cem Kaner'
    assert user_obj['email'] == 'cem@kaner.com'
    assert user_obj['id'] is not None


@pytest.mark.django_db
def test_reservation_can_be_modified_by_overlapping_reservation(api_client, reservation, reservation_data, user):
    """
    Tests that a reservation can be modified with times that overlap with the original times.
    """
    api_client.force_authenticate(user=user)
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})

    # try to extend the original reservation by 1 hour
    reservation_data['begin'] = '2115-04-04T09:00:00+02:00'
    reservation_data['end'] = '2115-04-04T11:00:00+02:00'
    response = api_client.put(detail_url, reservation_data)
    assert response.status_code == 200
    reservation = Reservation.objects.get(pk=reservation.pk)
    assert reservation.begin == dateparse.parse_datetime('2115-04-04T09:00:00+02:00')
    assert reservation.end == dateparse.parse_datetime('2115-04-04T11:00:00+02:00')


@pytest.mark.parametrize('perm_type', ['unit', 'resource_group'])
@pytest.mark.django_db
def test_non_reservable_resource_restrictions(
        api_client, list_url, resource_group,
        reservation_data, user, group, perm_type, general_admin):
    """
    Tests that a normal user cannot make a reservation to a
    non-reservable resource but admins can.

    Creating a new reservation with POST and updating an existing one with PUT are both tested.
    """
    resource_in_unit = resource_group.resources.first()
    resource_in_unit.reservable = False
    resource_in_unit.save()
    api_client.force_authenticate(user=user)
    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 403

    # Create a reservation and try to change that with PUT
    reservation = Reservation.objects.create(
        resource=resource_in_unit,
        begin=dateparse.parse_datetime('2115-04-07T09:00:00+02:00'),
        end=dateparse.parse_datetime('2115-04-07T10:00:00+02:00'),
        user=user,
    )
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})
    response = api_client.put(detail_url, reservation_data)
    reservation.delete()

    assert Reservation.objects.count() == 0

    # an admin should be allowed to create and update
    api_client.force_authenticate(user=general_admin)
    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201

    staff_reservation_data = reservation_data.copy()
    staff_reservation_data['id'] = response.json()['id']
    staff_reservation_data['begin'] = dateparse.parse_datetime('2115-04-08T09:00:00+02:00')
    staff_reservation_data['end'] = dateparse.parse_datetime('2115-04-08T10:00:00+02:00')
    detail_url = reverse('reservation-detail', kwargs={'pk': staff_reservation_data['id']})
    response = api_client.put(detail_url, data=staff_reservation_data)
    assert response.status_code == 200
    Reservation.objects.first().delete()
    assert Reservation.objects.count() == 0

    # If the has explicit permission to make reservations, it should be allowed.
    user.groups.add(group)
    if perm_type == 'unit':
        assign_perm('unit:can_make_reservations', group, resource_in_unit.unit)
    elif perm_type == 'resource_group':
        assign_perm('group:can_make_reservations', group, resource_group)

    api_client.force_authenticate(user=user)
    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201
    detail_url = reverse('reservation-detail', kwargs={'pk': response.json()['id']})
    response = api_client.put(detail_url, data=reservation_data)
    assert response.status_code == 200


@pytest.mark.django_db
def test_reservation_restrictions_by_owner(
        api_client, list_url, reservation, reservation_data,
        user2, general_admin):
    """
    Tests that a normal user can't modify other people's reservations
    while an admin can.
    """
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})
    api_client.force_authenticate(user=user2)

    response = api_client.put(detail_url, reservation_data)
    assert response.status_code == 403
    response = api_client.delete(detail_url, reservation_data)
    assert response.status_code == 403

    # an admin should be allowed to perform every modifying method even
    # that she is not the user in the reservation
    api_client.force_authenticate(user=general_admin)
    response = api_client.put(detail_url, reservation_data)
    assert response.status_code == 200
    response = api_client.delete(detail_url, reservation_data)
    assert response.status_code == 204


@pytest.mark.django_db
def test_normal_users_cannot_make_reservations_for_others(
        api_client, list_url, reservation, reservation_data, user, user2):
    """
    Tests that a normal user cannot make a reservation for other people.
    """
    api_client.force_authenticate(user=user)
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})

    # set bigger max reservations limit so that it won't be a limiting factor here
    reservation.resource.max_reservations_per_user = 2
    reservation.resource.save()

    # set another user for new reservations
    reservation_data['user'] = {'id': user2.uuid}

    # modify an existing reservation, and verify that user isn't changed
    response = api_client.put(detail_url, data=reservation_data, format='json')
    assert response.status_code == 200
    new_reservation = Reservation.objects.get(id=response.data['id'])
    assert new_reservation.user == user

    # make a new reservation and verify that user isn't the other one
    reservation_data['begin'] = dateparse.parse_datetime('2115-04-04T13:00:00+02:00')
    reservation_data['end'] = dateparse.parse_datetime('2115-04-04T14:00:00+02:00')
    response = api_client.post(list_url, data=reservation_data, format='json')
    assert response.status_code == 201
    new_reservation = Reservation.objects.get(id=response.data['id'])
    assert new_reservation.user == user


@pytest.mark.django_db
def test_admins_can_make_reservations_for_others(
        api_client, list_url, reservation, reservation_data,
        user2, general_admin):
    """
    Tests that a staff member can make reservations for other people without normal user restrictions.
    """
    api_client.force_authenticate(user=general_admin)

    # dealing with another user's reservation
    reservation.user = user2
    reservation.save()
    reservation_data['user'] = {'id': user2.uuid}

    # modify an existing reservation
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})
    response = api_client.put(detail_url, data=reservation_data, format='json')
    assert response.status_code == 200
    new_reservation = Reservation.objects.get(id=response.data['id'])
    assert new_reservation.user == user2

    # create a new reservation, which is also too long, outside the opening hours and exceeds normal user
    # reservation limit. creating such a reservation for a normal user should be possible for a staff member
    reservation_data['begin'] = dateparse.parse_datetime('2115-04-04T13:00:00+02:00')
    reservation_data['end'] = dateparse.parse_datetime('2115-04-04T20:00:00+02:00')
    response = api_client.post(list_url, data=reservation_data, format='json')
    assert response.status_code == 201
    new_reservation = Reservation.objects.get(id=response.data['id'])
    assert new_reservation.user == user2


@pytest.mark.django_db
def test_strong_reservation(api_client, list_url, reservation_data, strong_user, user, strong_resource):
    api_client.force_authenticate(strong_user)
    reservation_data['resource'] = strong_resource.id
    reservation_data['begin'] = dateparse.parse_datetime('2115-04-04T13:00:00+02:00')
    reservation_data['end'] = dateparse.parse_datetime('2115-04-04T14:00:00+02:00')
    response = api_client.post(list_url, data=reservation_data, format='json')
    assert response.status_code == 201
    api_client.force_authenticate(user)
    response = api_client.post(list_url, data=reservation_data, format='json')
    assert response.status_code == 403


@pytest.mark.django_db
def test_reservation_user_filter(api_client, list_url, reservation, resource_in_unit, user, user2):
    """
    Tests that reservation user and is_own filtering work correctly.
    """

    reservation2 = Reservation.objects.create(
        resource=resource_in_unit,
        begin=dateparse.parse_datetime('2115-04-07T11:00:00+02:00'),
        end=dateparse.parse_datetime('2115-04-07T12:00:00+02:00'),
        user=user2,
        state=Reservation.CONFIRMED,
    )

    # even unauthenticated user should see all the reservations
    response = api_client.get(list_url)
    assert response.data['count'] == 2

    # filtering by user
    response = api_client.get(list_url + '?user=%s' % user.uuid)
    assert response.data['count'] == 1
    assert response.data['results'][0]['id'] == reservation.id

    # filtering by is_own
    api_client.force_authenticate(user=user)
    response = api_client.get(list_url + '?is_own=true')
    assert response.data['count'] == 1
    assert response.data['results'][0]['id'] == reservation.id
    response = api_client.get(list_url + '?is_own=false')
    assert response.data['count'] == 1
    assert response.data['results'][0]['id'] == reservation2.id


@pytest.mark.django_db
def test_reservation_time_filters(api_client, list_url, reservation, resource_in_unit, user):
    reservation2 = Reservation.objects.create(
        resource=resource_in_unit,
        begin=dateparse.parse_datetime('2015-04-07T11:00:00+02:00'),
        end=dateparse.parse_datetime('2015-04-07T12:00:00+02:00'),
        user=user,
        state=Reservation.CONFIRMED,
    )

    # without the filter, only the reservation in the future should be returned
    response = api_client.get(list_url)
    assert response.data['count'] == 1
    assert response.data['results'][0]['id'] == reservation.id

    # with the 'all' filter, both reservations should be returned
    response = api_client.get(list_url + '?all=true')
    assert response.data['count'] == 2
    assert {reservation.id, reservation2.id}.issubset(set(res['id'] for res in response.data['results']))

    # with start or end, both reservations should be returned
    # filtering by start date only
    response = api_client.get(list_url + '?start=2065-04-06')
    assert response.data['count'] == 1
    assert response.data['results'][0]['id'] == reservation.id

    # filtering by end date only
    response = api_client.get(list_url + '?end=2065-04-06')
    assert response.data['count'] == 1
    assert response.data['results'][0]['id'] == reservation2.id

    # filtering by start and end times
    response = api_client.get(list_url + '?start=2065-04-06T11:00:00%2b02:00' + '&end=2065-04-06T12:00:00%2b02:00')
    assert response.data['count'] == 0
    response = api_client.get(list_url + '?start=2005-04-07T11:30:00%2b02:00' + '&end=2115-04-04T09:30:00%2b02:00')
    assert response.data['count'] == 2
    assert {reservation.id, reservation2.id}.issubset(set(res['id'] for res in response.data['results']))


@pytest.mark.parametrize("input_hours,input_mins,expected", [
    (2, 30, '2 hours 30 minutes'),
    (1, 30, '1 hour 30 minutes'),
    (1, 0, '1 hour'),
    (0, 30, '30 minutes'),
    (0, 1, '1 minute'),
])
@pytest.mark.django_db
def test_max_reservation_period_error_message(
        api_client, list_url, resource_in_unit, reservation_data, user, input_hours, input_mins, expected):
    """
    Tests that maximum reservation period error is returned in correct humanized form.
    """

    reservation_data['end'] = '2115-04-04T16:00:00+02:00'  # too long reservation

    resource_in_unit.max_period = datetime.timedelta(hours=input_hours, minutes=input_mins)
    resource_in_unit.save()

    api_client.force_authenticate(user=user)
    response = api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == 400
    assert response.data['non_field_errors'][0] == 'The maximum reservation length is %s' % expected


@pytest.mark.django_db
def test_reservation_excels(staff_api_client, list_url, detail_url, reservation, user):
    """
    Tests that reservation list and detail endpoints return .xlsx files when requested
    """

    response = staff_api_client.get(
        list_url,
        HTTP_ACCEPT='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        HTTP_ACCEPT_LANGUAGE='en',
    )
    assert response.status_code == 200
    assert response.headers['Content-Disposition'] == 'attachment; filename=reservations.xlsx'
    assert len(response.content) > 0

    response = staff_api_client.get(
        detail_url,
        HTTP_ACCEPT='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        HTTP_ACCEPT_LANGUAGE='en',
    )
    assert response.status_code == 200
    assert response.headers['Content-Disposition'] == 'attachment; filename=reservation-{}.xlsx'.format(reservation.pk)
    assert len(response.content) > 0


@pytest.mark.parametrize('need_manual_confirmation, expected_state', [
    (False, Reservation.CONFIRMED),
    (True, Reservation.REQUESTED)
])
@pytest.mark.django_db
def test_state_on_new_reservations(user_api_client, list_url, reservation_data_extra, resource_in_unit,
                                   need_manual_confirmation, expected_state):
    resource_in_unit.need_manual_confirmation = need_manual_confirmation
    if need_manual_confirmation:
        resource_in_unit.reservation_metadata_set = ReservationMetadataSet.objects.get(name='default')
    resource_in_unit.save()
    response = user_api_client.post(list_url, data=reservation_data_extra)
    assert response.status_code == 201
    reservation = Reservation.objects.latest('created_at')
    assert reservation.state == expected_state


@pytest.mark.parametrize('state', [
    'illegal_state',
    '',
    None,
])
@pytest.mark.django_db
def test_illegal_state_set(user_api_client, list_url, detail_url, reservation_data, state):
    reservation_data['state'] = state
    response = user_api_client.post(list_url, data=reservation_data, format='json')
    assert response.status_code == 400
    assert 'state' in response.data
    response = user_api_client.put(detail_url, data=reservation_data, format='json')
    assert response.status_code == 400
    assert 'state' in response.data


@pytest.mark.parametrize('need_manual_confirmation', [
    False,
    True
])
@pytest.mark.django_db
def test_extra_fields_visibility(user_api_client, list_url, detail_url, reservation, resource_in_unit,
                                 need_manual_confirmation):
    resource_in_unit.need_manual_confirmation = need_manual_confirmation
    if need_manual_confirmation:
        resource_in_unit.reservation_metadata_set = ReservationMetadataSet.objects.get(name='default')
    resource_in_unit.save()

    for url in (list_url, detail_url):
        response = user_api_client.get(url)
        assert response.status_code == 200
        reservation_data = response.data['results'][0] if 'results' in response.data else response.data
        for field_name in DEFAULT_RESERVATION_EXTRA_FIELDS:
            assert (field_name in reservation_data) is need_manual_confirmation


@pytest.mark.parametrize('user_fixture, has_perm, expected_visibility', [
    ('user', False, True),
    ('user2', False, False),
    ('staff_user', False, False),
    ('general_admin', False, True),
    ('user2', True, True),
])
@pytest.mark.django_db
def test_extra_fields_visibility_per_user(
        user_api_client,
        user, user2, staff_user, general_admin,
        list_url, detail_url,
        reservation, resource_in_unit,
        user_fixture, has_perm, expected_visibility):
    resource_in_unit.reservation_metadata_set = ReservationMetadataSet.objects.get(name='default')
    resource_in_unit.save()

    test_user = locals().get(user_fixture)
    user_api_client.force_authenticate(test_user)
    if has_perm:
        assign_perm('unit:can_view_reservation_extra_fields', test_user, resource_in_unit.unit)

    for url in (list_url, detail_url):
        response = user_api_client.get(url)
        assert response.status_code == 200
        reservation_data = response.data['results'][0] if 'results' in response.data else response.data
        for field_name in DEFAULT_RESERVATION_EXTRA_FIELDS:
            assert (field_name in reservation_data) is expected_visibility


@pytest.mark.django_db
def test_extra_fields_required_for_paid_reservations(user_api_client, staff_api_client, staff_user, list_url,
                                                     resource_in_unit, reservation_data):
    resource_in_unit.need_manual_confirmation = True
    resource_in_unit.reservation_metadata_set = ReservationMetadataSet.objects.get(name='default')
    resource_in_unit.save()

    response = user_api_client.post(list_url, data=reservation_data)
    assert response.status_code == 400
    assert set(DEFAULT_REQUIRED_RESERVATION_EXTRA_FIELDS) == set(response.data)

    response = staff_api_client.post(list_url, data=reservation_data)
    assert response.status_code == 400
    assert set(DEFAULT_REQUIRED_RESERVATION_EXTRA_FIELDS) == set(response.data)

    assign_perm('unit:can_approve_reservation', staff_user, resource_in_unit.unit)
    response = staff_api_client.post(list_url, data=reservation_data)
    assert response.status_code == 400
    assert set(DEFAULT_REQUIRED_RESERVATION_EXTRA_FIELDS) == set(response.data)


@pytest.mark.django_db
def test_staff_event_restrictions(user_api_client, staff_api_client, staff_user, list_url, resource_in_unit,
                                  reservation_data):
    resource_in_unit.need_manual_confirmation = True
    resource_in_unit.reservation_metadata_set = ReservationMetadataSet.objects.get(name='default')
    resource_in_unit.save()
    reservation_data['staff_event'] = True

    # normal user
    response = user_api_client.post(list_url, data=reservation_data)
    assert response.status_code == 400
    assert set(DEFAULT_REQUIRED_RESERVATION_EXTRA_FIELDS) == set(response.data)

    # staff member
    response = staff_api_client.post(list_url, data=reservation_data)
    assert response.status_code == 400
    assert set(DEFAULT_REQUIRED_RESERVATION_EXTRA_FIELDS) == set(response.data)

    # unit manager but reserver_name and event_description missing
    UnitAuthorization.objects.create(subject=resource_in_unit.unit,
                                     level=UnitAuthorizationLevel.manager, authorized=staff_user)
    response = staff_api_client.post(list_url, data=reservation_data)
    assert response.status_code == 400
    assert {'reserver_name', 'event_description'} == set(response.data)


@pytest.mark.django_db
def test_new_staff_event_gets_confirmed(user_api_client, staff_api_client, staff_user, list_url, resource_in_unit,
                                        reservation_data, reservation_data_extra):
    resource_in_unit.need_manual_confirmation = True
    resource_in_unit.reservation_metadata_set = ReservationMetadataSet.objects.get(name='default')
    resource_in_unit.save()

    # reservation should not be be confirmed if the user doesn't have approve permission
    response = staff_api_client.post(list_url, data=reservation_data_extra)
    assert response.status_code == 201
    reservation = Reservation.objects.get(id=response.data['id'])
    assert reservation.state == Reservation.REQUESTED

    reservation.delete()

    UnitAuthorization.objects.create(subject=resource_in_unit.unit,
                                     level=UnitAuthorizationLevel.manager, authorized=staff_user)
    reservation_data['staff_event'] = True
    reservation_data['reserver_name'] = 'herra huu'
    reservation_data['event_description'] = 'herra huun bileet'
    response = staff_api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201, "Request failed with: %s" % (str(response.content, 'utf8'))
    reservation = Reservation.objects.get(id=response.data['id'])
    assert reservation.state == Reservation.CONFIRMED


@pytest.mark.django_db
def test_extra_fields_can_be_set_for_paid_reservations(user_api_client, list_url, reservation_data_extra,
                                                       resource_in_unit):
    resource_in_unit.max_reservations_per_user = 2
    resource_in_unit.need_manual_confirmation = True
    resource_in_unit.reservation_metadata_set = ReservationMetadataSet.objects.get(name='default')
    resource_in_unit.save()

    response = user_api_client.post(list_url, data=reservation_data_extra)
    assert response.status_code == 201
    reservation = Reservation.objects.latest('created_at')
    assert reservation.reserver_address_street == 'Omenatie 102'

    reservation_data_extra['reserver_address_street'] = 'Karhutie 8'
    response = user_api_client.put('%s%s/' % (list_url, reservation.pk), data=reservation_data_extra)
    assert response.status_code == 200
    reservation.refresh_from_db()
    assert reservation.reserver_address_street == 'Karhutie 8'


@pytest.mark.django_db
def test_extra_fields_ignored_for_non_paid_reservations(user_api_client, list_url, reservation_data_extra,
                                                        resource_in_unit):
    response = user_api_client.post(list_url, data=reservation_data_extra)
    assert response.status_code == 201
    reservation = Reservation.objects.latest('created_at')
    assert reservation.reserver_name == ''
    assert reservation.number_of_participants == 1


@pytest.mark.django_db
def test_user_can_see_her_reservations_in_all_states(user_api_client, list_url, reservations_in_all_states):
    response = user_api_client.get(list_url)
    assert response.status_code == 200
    assert response.data['count'] == 6


@pytest.mark.django_db
def test_user_cannot_see_others_denied_or_cancelled_reservations(api_client, user2, list_url,
                                                                 reservations_in_all_states):
    api_client.force_authenticate(user=user2)
    response = api_client.get(list_url)
    assert response.status_code == 200
    assert response.data['count'] == 4
    expected = {
        Reservation.CONFIRMED, Reservation.REQUESTED, Reservation.WAITING_FOR_PAYMENT,
        Reservation.WAITING_FOR_CASH_PAYMENT
    }
    assert {r['state'] for r in response.data['results']} == expected


@pytest.mark.django_db
def test_admins_can_see_reservations_in_all_states(
        api_client, list_url, general_admin, reservations_in_all_states):
    api_client.force_authenticate(user=general_admin)
    response = api_client.get(list_url)
    assert response.status_code == 200
    assert response.data['count'] == 6


@pytest.mark.django_db
def test_unit_manager_can_see_all_reservations_in_their_unit(
        resource_in_unit, api_client, staff_user, reservations_in_all_states, list_url):
    """
    Tests that unit managers can see reservations made to their resources in all 6 reservation states
    """
    UnitAuthorization.objects.create(subject=resource_in_unit.unit,
                                     level=UnitAuthorizationLevel.manager, authorized=staff_user)
    api_client.force_authenticate(user=staff_user)
    response = api_client.get(list_url)
    assert response.status_code == 200
    assert response.data['count'] == 6


@pytest.mark.django_db
def test_unit_admin_can_see_all_reservations_in_their_unit(
        resource_in_unit, api_client, staff_user, reservations_in_all_states, list_url):
    """
    Tests that unit admins can see reservations made to their resources in all 6 reservation states
    """
    UnitAuthorization.objects.create(subject=resource_in_unit.unit,
                                     level=UnitAuthorizationLevel.admin, authorized=staff_user)
    api_client.force_authenticate(user=staff_user)
    response = api_client.get(list_url)
    assert response.status_code == 200
    assert response.data['count'] == 6


@pytest.mark.django_db
def test_unit_manager_cannot_see_all_reservations_not_in_their_unit(
        resource_in_unit, api_client, staff_user, reservations_in_all_states2, list_url):
    """
    Tests that unit managers can only see reservations made to other than their own unit in the
    4 allowed reservation states
    """
    UnitAuthorization.objects.create(subject=resource_in_unit.unit,
                                     level=UnitAuthorizationLevel.manager, authorized=staff_user)
    api_client.force_authenticate(user=staff_user)
    response = api_client.get(list_url)
    assert response.status_code == 200
    assert response.data['count'] == 4


@pytest.mark.django_db
def test_unit_admin_cannot_see_all_reservations_not_in_their_unit(
        resource_in_unit, api_client, staff_user, reservations_in_all_states2, list_url):
    """
    Tests that unit admins can only see reservations made to other than their own unit in the
    4 allowed reservation states
    """
    UnitAuthorization.objects.create(subject=resource_in_unit.unit,
                                     level=UnitAuthorizationLevel.admin, authorized=staff_user)
    api_client.force_authenticate(user=staff_user)
    response = api_client.get(list_url)
    assert response.status_code == 200
    assert response.data['count'] == 4


@pytest.mark.django_db
def test_reservation_cannot_be_confirmed_without_permission(
        api_client, user_api_client, detail_url, reservation,
        reservation_data, user2):
    reservation.state = Reservation.REQUESTED
    reservation.save()
    reservation_data['state'] = Reservation.CONFIRMED

    response = user_api_client.put(detail_url, data=reservation_data)
    assert response.status_code == 400
    assert 'state' in response.data

    api_client.force_authenticate(user=user2)
    response = api_client.put(detail_url, data=reservation_data)
    assert response.status_code == 403
    assert response.data['detail'].code == 'permission_denied'


@pytest.mark.django_db
def test_reservation_can_be_confirmed_with_permission(
        api_client, general_admin, detail_url, reservation,
        reservation_data):
    reservation.state = Reservation.REQUESTED
    reservation.save()
    reservation_data['state'] = Reservation.CONFIRMED
    assign_perm('unit:can_approve_reservation',
                general_admin, reservation.resource.unit)
    api_client.force_authenticate(user=general_admin)
    response = api_client.put(detail_url, data=reservation_data)
    assert response.status_code == 200
    reservation.refresh_from_db()
    assert reservation.state == Reservation.CONFIRMED
    assert reservation.approver == general_admin


@pytest.mark.django_db
def test_reservation_patch_has_arrived(api_client, general_admin, detail_url, reservation):
    reservation.has_arrived = False
    reservation.save()
    api_client.force_authenticate(user=general_admin)
    response = api_client.patch(detail_url, data={
        'has_arrived': True
    })
    assert response.status_code == 200
    reservation.refresh_from_db()
    assert reservation.has_arrived == True


@pytest.mark.django_db
def test_reservation_patch_fail_has_arrived(api_client, user2, detail_url, reservation):
    reservation.has_arrived = False
    reservation.save()
    api_client.force_authenticate(user=user2)
    response = api_client.patch(detail_url, data={
        'has_arrived': True
    })
    assert response.status_code == 403
    reservation.refresh_from_db()
    assert reservation.has_arrived == False


@pytest.mark.django_db
def test_user_cannot_modify_or_cancel_manually_confirmed_reservation(user_api_client, detail_url, reservation,
                                                                     reservation_data_extra, resource_in_unit):
    resource_in_unit.need_manual_confirmation = True
    resource_in_unit.reservation_metadata_set = ReservationMetadataSet.objects.get(name='default')
    resource_in_unit.save()

    response = user_api_client.put(detail_url, data=reservation_data_extra)
    assert response.status_code == 403

    response = user_api_client.delete(detail_url)
    assert response.status_code == 403


@pytest.mark.parametrize('username, expected_visibility', [
    (None, False),  # unauthenticated user
    ('test_user', True),  # own reservation
    ('test_user2', False),  # someone else's reservation
    ('test_staff_user', False),  # staff
    ('test_general_admin', True),  # admin
])
@pytest.mark.django_db
def test_extra_fields_visibility_for_different_user_types(
        api_client, user, user2, staff_user, general_admin,
        list_url, detail_url,
        reservation, resource_in_unit, username, expected_visibility):
    resource_in_unit.need_manual_confirmation = True
    resource_in_unit.reservation_metadata_set = ReservationMetadataSet.objects.get(name='default')
    resource_in_unit.save()
    if username:
        api_client.force_authenticate(user=User.objects.get(username=username))

    for url in (list_url, detail_url):
        response = api_client.get(url)
        assert response.status_code == 200
        reservation_data = response.data['results'][0] if 'results' in response.data else response.data
        for field_name in DEFAULT_RESERVATION_EXTRA_FIELDS:
            assert (field_name in reservation_data) is expected_visibility


@pytest.mark.parametrize('state', [
    Reservation.CANCELLED,
    Reservation.DENIED
])
@pytest.mark.django_db
def test_denied_and_cancelled_reservations_not_active(user_api_client, reservation, reservation_data, list_url,
                                                      resource_in_unit, state):
    reservation.state = state
    reservation.save()

    # test reservation max limit
    response = user_api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201

    # test overlapping reservation
    resource_in_unit.max_reservations_per_user = 2
    resource_in_unit.save()
    reservation_data['begin'] = reservation.begin
    reservation_data['end'] = reservation.end
    response = user_api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201


@pytest.mark.django_db
def test_cannot_make_reservation_in_the_past(user_api_client, reservation_data, list_url):
    reservation_data.update(
        begin='2010-04-04T11:00:00+02:00',
        end='2010-04-04T12:00:00+02:00'
    )
    response = user_api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == 400
    assert_non_field_errors_contain(response, 'past')


@pytest.mark.django_db
def test_need_manual_confirmation_filter(user_api_client, user, list_url, reservation, other_resource):
    other_resource.need_manual_confirmation = True
    other_resource.reservation_metadata_set = ReservationMetadataSet.objects.get(name='default')
    other_resource.save()
    reservation_needing_confirmation = Reservation.objects.create(
        resource=other_resource,
        begin='2115-04-05T09:00:00+02:00',
        end='2115-04-05T10:00:00+02:00',
        user=user,
    )

    # no filter, expect both reservations
    response = user_api_client.get(list_url)
    assert response.status_code == 200
    reservation_ids = set([res['id'] for res in response.data['results']])
    assert reservation_ids == {reservation.id, reservation_needing_confirmation.id}

    # filter false, expect only first reservation
    response = user_api_client.get('%s%s' % (list_url, '?need_manual_confirmation=false'))
    assert response.status_code == 200
    reservation_ids = set([res['id'] for res in response.data['results']])
    assert reservation_ids == {reservation.id}

    # filter true, expect only second reservation
    response = user_api_client.get('%s%s' % (list_url, '?need_manual_confirmation=true'))
    assert response.status_code == 200
    reservation_ids = set([res['id'] for res in response.data['results']])
    assert reservation_ids == {reservation_needing_confirmation.id}


@pytest.mark.parametrize('state_filter, expected_states', [
    ('', ['requested', 'confirmed', 'denied', 'cancelled', 'waiting_for_payment', 'waiting_for_cash_payment']),
    ('?state=requested', ['requested']),
    ('?state=confirmed,requested', ['confirmed', 'requested']),
    ('?state=confirmed,   requested    ,', ['confirmed', 'requested'])
])
@pytest.mark.django_db
def test_state_filters(user_api_client, user, list_url, reservations_in_all_states, state_filter, expected_states):
    response = user_api_client.get('%s%s' % (list_url, state_filter))
    assert response.status_code == 200
    reservation_ids = set([res['id'] for res in response.data['results']])
    assert reservation_ids == set(reservations_in_all_states[state].id for state in expected_states)


@override_settings(RESPA_MAILS_ENABLED=True)
@pytest.mark.parametrize('perm_type', ['unit', 'resource_group'])
@pytest.mark.django_db
def test_reservation_mails(
        api_client, general_admin, user_api_client, test_unit2,
        list_url, reservation_data_extra, perm_type):
    resource = Resource.objects.get(id=reservation_data_extra['resource'])
    resource.need_manual_confirmation = True
    resource.reservation_metadata_set = ReservationMetadataSet.objects.get(name='default')
    resource.save()
    if perm_type == 'unit':
        assign_perm('unit:can_approve_reservation',
                    general_admin, resource.unit)
    elif perm_type == 'resource_group':
        resource_group = resource.groups.create(name='test group')
        assign_perm('group:can_approve_reservation',
                    general_admin, resource_group)

    # create other admin user who should not receive mails because he
    # doesn't have permission to the right unit
    other_official = get_user_model().objects.create(
        username='other_unit_official',
        first_name='Ozzy',
        last_name='Official',
        email='ozzy@test_unit2.com',
        is_staff=True,
        is_general_admin=True,
        preferred_language='en'
    )

    assign_perm('unit:can_approve_reservation', other_official, test_unit2)

    # test REQUESTED
    reservation_data_extra['state'] = Reservation.REQUESTED
    reservation_data_extra['preferred_language'] = 'en'
    response = user_api_client.post(list_url, data=reservation_data_extra, format='json')
    assert response.status_code == 201

    # 2 mails should be sent, one to the customer, and one to the admin
    # who can approve the reservation (and no mail for the other admin)
    assert len(mail.outbox) == 2
    check_received_mail_exists(
        "You've made a preliminary reservation",
        reservation_data_extra['reserver_email_address'],
        ('made a preliminary reservation', 'Starts: April 4, 2115, 11 a.m.'),
        clear_outbox=False
    )
    # Staff will use fallback language
    check_received_mail_exists(
        'Alustava varaus tehty',
        general_admin.email,
        'Uusi alustava varaus on tehty'
    )

    detail_url = '%s%s/' % (list_url, response.data['id'])

    # test DENIED
    reservation_data_extra['state'] = Reservation.DENIED
    api_client.force_authenticate(user=general_admin)
    response = api_client.put(detail_url, data=reservation_data_extra, format='json')
    assert response.status_code == 200
    assert len(mail.outbox) == 1
    check_received_mail_exists(
        'Reservation denied',
        reservation_data_extra['reserver_email_address'],
        'has been denied.'
    )

    # test CONFIRMED
    reservation_data_extra['state'] = Reservation.CONFIRMED
    response = api_client.put(detail_url, data=reservation_data_extra, format='json')
    assert response.status_code == 200
    assert len(mail.outbox) == 1
    check_received_mail_exists(
        'Reservation confirmed',
        reservation_data_extra['reserver_email_address'],
        'has been confirmed.',
        clear_outbox=False
    )
    assert 'this resource rocks' in str(mail.outbox[0].message())
    mail.outbox = []

    with translation.override('en'):
        NotificationTemplate.objects.create(
            type=NotificationType.RESERVATION_CANCELLED_BY_OFFICIAL,
            is_default_template=True,
            subject='Reservation cancelled',
            body='Reservation has been cancelled.',
        )

    # test CANCELLED
    reservation_data_extra['state'] = Reservation.CANCELLED
    response = api_client.delete(detail_url, format='json')

    assert response.status_code == 204
    assert len(mail.outbox) == 1
    check_received_mail_exists(
        'Reservation cancelled',
        reservation_data_extra['reserver_email_address'],
        'has been cancelled.'
    )


@override_settings(RESPA_MAILS_ENABLED=True)
@pytest.mark.parametrize('perm_type', ['unit', 'resource_group'])
@pytest.mark.django_db
def test_reservation_mails_in_finnish(
        api_client, general_admin, user_api_client, test_unit2,
        list_url, reservation_data_extra, perm_type, user):
    reservation_data_extra['preferred_language'] = 'fi'

    resource = Resource.objects.get(id=reservation_data_extra['resource'])
    resource.need_manual_confirmation = True
    resource.reservation_metadata_set = ReservationMetadataSet.objects.get(name='default')
    resource.save()
    if perm_type == 'unit':
        assign_perm('unit:can_approve_reservation', general_admin, resource.unit)
    elif perm_type == 'resource_group':
        resource_group = resource.groups.create(name='test group')
        assign_perm('group:can_approve_reservation', general_admin, resource_group)

    user.preferred_language = 'fi'
    user.save(update_fields=('preferred_language',))
    general_admin.preferred_language = 'fi'
    general_admin.save(update_fields=('preferred_language',))

    # create another admin who should not receive mails because he
    # doesn't have permission to the right unit
    other_official = get_user_model().objects.create(
        username='other_unit_official',
        first_name='Ozzy',
        last_name='Official',
        email='ozzy@test_unit2.com',
        is_staff=True,
        is_general_admin=True,
        preferred_language='fi'
    )

    assign_perm('unit:can_approve_reservation', other_official, test_unit2)

    # test REQUESTED
    reservation_data_extra['state'] = Reservation.REQUESTED
    response = user_api_client.post(list_url, data=reservation_data_extra, format='json')
    assert response.status_code == 201

    # 2 mails should be sent, one to the customer, and one to the admin
    # who can approve the reservation (and no mail for the other admin)
    assert len(mail.outbox) == 2

    check_received_mail_exists(
        'Olet tehnyt alustavan varauksen',
        reservation_data_extra['reserver_email_address'],
        ('Olet tehnyt alustavan varauksen', 'Alkaa: 4. huhtikuuta 2115 kello 11.00'),
        clear_outbox=False
    )
    check_received_mail_exists(
        'Alustava varaus tehty',
        general_admin.email,
        'Uusi alustava varaus on tehty'
    )

    detail_url = '%s%s/' % (list_url, response.data['id'])

    # test DENIED
    reservation_data_extra['state'] = Reservation.DENIED
    api_client.force_authenticate(user=general_admin)
    response = api_client.put(detail_url, data=reservation_data_extra, format='json')
    assert response.status_code == 200
    assert len(mail.outbox) == 1
    check_received_mail_exists(
        'Varaus hylätty',
        reservation_data_extra['reserver_email_address'],
        'Varauksesi on hylätty.'
    )

    # test CONFIRMED
    reservation_data_extra['state'] = Reservation.CONFIRMED
    response = api_client.put(detail_url, data=reservation_data_extra, format='json')
    assert response.status_code == 200
    assert len(mail.outbox) == 1

    check_received_mail_exists(
        'Varaus vahvistettu',
        reservation_data_extra['reserver_email_address'],
        'Varauksesi on hyväksytty.',
        clear_outbox=False
    )
    assert 'this resource rocks' in str(mail.outbox[0].message())
    mail.outbox = []

    with translation.override('fi'):
        NotificationTemplate.objects.create(
            type=NotificationType.RESERVATION_CANCELLED_BY_OFFICIAL,
            is_default_template=True,
            subject='Varaus peruttu',
            body='Varauksesi on peruttu.',
        )

    # test CANCELLED
    reservation_data_extra['state'] = Reservation.CANCELLED
    response = api_client.delete(detail_url, format='json')
    assert response.status_code == 204
    assert len(mail.outbox) == 1
    check_received_mail_exists(
        'Varaus peruttu',
        reservation_data_extra['reserver_email_address'],
        'Varauksesi on peruttu.'
    )


@override_settings(RESPA_MAILS_ENABLED=True)
@pytest.mark.django_db
def test_reservation_created_mail(user_api_client, resource_in_unit, list_url, reservation_data, user, reservation_created_notification):
    reservation_data['preferred_language'] = 'en'

    response = user_api_client.post(list_url, data=reservation_data, format='json')
    file_name, ical_file, mimetype = mail.outbox[0].attachments[0]
    assert response.status_code == 201
    assert len(mail.outbox[0].attachments) == 1
    Calendar.from_ical(ical_file)
    assert len(mail.outbox) == 1
    check_received_mail_exists(
        'Normal reservation created subject.',
        user.email,
        'Normal reservation created body.'
    )

@override_settings(RESPA_MAILS_ENABLED=True, RESPA_SMS_ENABLED=True)
@pytest.mark.django_db
@pytest.mark.parametrize('reserver_email_address,reserver_phone_number,expected_return_type', [
        ('customer@example.org', None, RespaNotificationAction.EMAIL),
        (None, '+358404040404', RespaNotificationAction.SMS),
        ('customer@example.org', '+358404040404', RespaNotificationAction.EMAIL),
        (None, None, RespaNotificationAction.EMAIL)
])
def test_send_reservation_mail_return_type(
    resource_in_unit, reserver_phone_number, reserver_email_address,
    staff_api_client, list_url, reservation_data, expected_return_type,
    user, reservation_created_by_official_notification):
    if reserver_email_address:
        reservation_data['reserver_email_address'] = reserver_email_address
    if reserver_phone_number:
        reservation_data['reserver_phone_number'] = reserver_phone_number

    meta_field = ReservationMetadataField.objects.get(field_name='reserver_email_address')
    meta_field2 = ReservationMetadataField.objects.get(field_name='reserver_phone_number')
    metadata_set = ReservationMetadataSet.objects.create(
        name='updated_metadata',
    )
    metadata_set.supported_fields.set([meta_field, meta_field2])
    resource_in_unit.reservation_metadata_set = metadata_set
    resource_in_unit.send_sms_notification = True
    resource_in_unit.save()


    response = staff_api_client.post(list_url, data=reservation_data, format='json')
    assert response.status_code == 201
    reservation = Reservation.objects.get(pk=response.json()['id'])
    attachment = 'reservation.ics', build_reservations_ical_file([reservation]), 'text/calendar'
    kwargs = {'attachments': [attachment]}
    if not reserver_email_address and not reserver_phone_number:
        kwargs['user'] = user
    return_type = reservation.send_reservation_mail(NotificationType.RESERVATION_CREATED_BY_OFFICIAL, **kwargs)
    assert return_type == expected_return_type


@override_settings(RESPA_MAILS_ENABLED=True)
@pytest.mark.django_db
def test_no_reservation_created_mail_for_staff_reservation(
        staff_api_client, list_url, reservation_data, user, reservation_created_notification):
    response = staff_api_client.post(list_url, data=reservation_data, format='json')
    assert response.status_code == 201
    assert len(mail.outbox) == 0


@override_settings(RESPA_MAILS_ENABLED=True)
@pytest.mark.django_db
def test_reservation_html_mail(user_api_client, list_url, reservation_data, user, reservation_created_notification):
    with switch_language(reservation_created_notification, 'en'):
        reservation_created_notification.html_body = '<b>HTML</b> body'
        reservation_created_notification.save()

    reservation_data['preferred_language'] = 'en'
    response = user_api_client.post(list_url, data=reservation_data, format='json')
    assert response.status_code == 201

    assert len(mail.outbox) == 1
    check_received_mail_exists(
        'Normal reservation created subject.',
        user.email,
        'Normal reservation created body.',
        html_body='<b>HTML</b> body',
    )


@override_settings(RESPA_MAILS_ENABLED=True)
@pytest.mark.django_db
def test_reservation_mail_empty_text_body_should_become_html_body_without_tags(user_api_client, list_url,
                                                                               reservation_data, user,
                                                                               reservation_created_notification):
    with switch_language(reservation_created_notification, 'en'):
        reservation_created_notification.body = ''
        reservation_created_notification.html_body = '<b>HTML</b> body'
        reservation_created_notification.save()
    reservation_data['preferred_language'] = 'en'
    response = user_api_client.post(list_url, data=reservation_data, format='json')
    assert response.status_code == 201

    assert len(mail.outbox) == 1
    check_received_mail_exists(
        'Normal reservation created subject.',
        user.email,
        'HTML body',
        html_body='<b>HTML</b> body',
    )


@override_settings(RESPA_MAILS_ENABLED=True)
@pytest.mark.django_db
def test_reservation_mail_can_have_subject_only(user_api_client, list_url, reservation_data, user,
                                                reservation_created_notification):
    with switch_language(reservation_created_notification, 'en'):
        reservation_created_notification.body = ''
        reservation_created_notification.html_body = ''
        reservation_created_notification.save()
    reservation_data['preferred_language'] = 'en'
    response = user_api_client.post(list_url, data=reservation_data, format='json')
    assert response.status_code == 201

    assert len(mail.outbox) == 1
    check_received_mail_exists(
        'Normal reservation created subject.',
        user.email,
        '',
        html_body='',
        clear_outbox=False,
    )
    assert mail.outbox[0].body == ''


@override_settings(RESPA_MAILS_ENABLED=True)
@pytest.mark.django_db
def test_reservation_mail_can_be_disabled(user_api_client, list_url, reservation_data):
    response = user_api_client.post(list_url, data=reservation_data, format='json')
    assert response.status_code == 201

    assert len(mail.outbox) == 0


@override_settings(RESPA_MAILS_ENABLED=True, RESPA_IMAGE_BASE_URL='https://foo.bar/baz/')
@pytest.mark.django_db
def test_reservation_mail_images(user_api_client, user, list_url, reservation_data, resource_in_unit,
                                 reservation_created_notification):
    from resources.models.resource import ResourceImage

    with switch_language(reservation_created_notification, 'en'):
        reservation_created_notification.body = 'image url: {{ resource_main_image_url }}'
        reservation_created_notification.html_body = 'image: <img src="{{ resource_ground_plan_image_url }}">'
        reservation_created_notification.save()
    reservation_data['preferred_language'] = 'en'
    main_image = ResourceImage.objects.create(resource=resource_in_unit, type='main')
    ResourceImage.objects.create(resource=resource_in_unit, type='ground_plan')
    last_ground_plan_image = ResourceImage.objects.create(resource=resource_in_unit, type='ground_plan')

    response = user_api_client.post(list_url, data=reservation_data, format='json')
    assert response.status_code == 201

    assert len(mail.outbox) == 1
    check_received_mail_exists(
        'Normal reservation created subject.',
        user.email,
        'image url: https://foo.bar/baz/resource_image/{}'.format(main_image.id),
        html_body='image: <img src="https://foo.bar/baz/resource_image/{}">'.format(last_ground_plan_image.id),
    )


@override_settings(RESPA_MAILS_ENABLED=True)
@pytest.mark.django_db
def test_reservation_modified_email_by_official(reservation, reservation_data, staff_api_client, staff_user,
                                                reservation_modified_by_official_notification):
    reservation.reserver_email_address = 'test@tester.com'
    reservation.save()
    UnitAuthorization.objects.create(subject=reservation.resource.unit,
                                     level=UnitAuthorizationLevel.manager, authorized=staff_user)
    reservation_data['preferred_language'] = 'en'
    reservation_data['reserver_name'] = 'new name'
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})
    response = staff_api_client.put(detail_url, data=reservation_data, format='json')
    assert response.status_code == 200
    assert len(mail.outbox) == 1
    check_received_mail_exists(
        'reservation modified by official subject.',
        'test@tester.com',
        'reservation modified by official body.'
    )


@override_settings(RESPA_MAILS_ENABLED=True)
@pytest.mark.django_db
def test_reservation_modified_email_by_official_comment_only(reservation, reservation_data, staff_api_client, staff_user,
                                                             reservation_modified_by_official_notification):
    reservation.reserver_email_address = 'test@tester.com'
    reservation.save()
    UnitAuthorization.objects.create(subject=reservation.resource.unit,
                                     level=UnitAuthorizationLevel.manager, authorized=staff_user)
    reservation_data['preferred_language'] = 'en'
    reservation_data['comments'] = 'test comment'
    reservation_data['begin'] = reservation.begin
    reservation_data['end'] = reservation.end
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})
    response = staff_api_client.put(detail_url, data=reservation_data, format='json')
    assert response.status_code == 200
    assert len(mail.outbox) == 0


@pytest.mark.parametrize('perm_type', ['unit', 'resource_group'])
@pytest.mark.django_db
def test_can_approve_filter(staff_api_client, staff_user, list_url, reservation,
                            perm_type):
    reservation.resource.need_manual_confirmation = True
    reservation.resource.reservation_metadata_set = ReservationMetadataSet.objects.get(name='default')
    reservation.resource.save()
    reservation.state = Reservation.REQUESTED
    reservation.save()

    response = staff_api_client.get('%s%s' % (list_url, '?can_approve=true'))
    assert response.status_code == 200
    assert len(response.data['results']) == 0

    assign_perm('unit:can_approve_reservation', staff_user, reservation.resource.unit)

    response = staff_api_client.get('%s%s' % (list_url, '?can_approve=true'))
    assert response.status_code == 200
    assert len(response.data['results']) == 1


@pytest.mark.django_db
def test_access_code_cannot_be_set_if_type_none(user_api_client, list_url, resource_in_unit, reservation_data):
    reservation_data['access_code'] = '023543'
    response = user_api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == 400
    assert 'This field cannot have a value with this resource' in response.data['access_code']


@pytest.mark.django_db
def test_invalid_pin6_access_code(user_api_client, list_url, resource_in_unit, reservation_data):
    resource_in_unit.access_code_type = Resource.ACCESS_CODE_TYPE_PIN6
    resource_in_unit.save()
    reservation_data['access_code'] = 'xxx'
    reservation_data['resource'] = resource_in_unit.id

    response = user_api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == 400
    assert 'Invalid value' in response.data['access_code']


@pytest.mark.django_db
def test_pin6_access_code_is_generated_if_not_set(user_api_client, list_url, resource_in_unit, reservation_data):
    resource_in_unit.access_code_type = Resource.ACCESS_CODE_TYPE_PIN6
    resource_in_unit.save()

    response = user_api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201
    new_reservation = Reservation.objects.get(id=response.data['id'])
    assert re.match('^[0-9]{6}$', new_reservation.access_code)


@pytest.mark.django_db
def test_pin6_access_code_can_be_set(user_api_client, list_url, resource_in_unit, reservation_data):
    resource_in_unit.access_code_type = Resource.ACCESS_CODE_TYPE_PIN6
    resource_in_unit.save()
    reservation_data['access_code'] = '023543'
    reservation_data['resource'] = resource_in_unit.id

    response = user_api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201
    new_reservation = Reservation.objects.get(id=response.data['id'])
    assert new_reservation.access_code == '023543'


@pytest.mark.django_db
def test_pin4_access_code_is_not_generated(user_api_client, list_url, resource_in_unit, reservation_data):
    resource_in_unit.access_code_type = Resource.ACCESS_CODE_TYPE_PIN4
    resource_in_unit.generate_access_codes = False
    resource_in_unit.save()

    response = user_api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201
    new_reservation = Reservation.objects.get(id=response.data['id'])
    assert not new_reservation.access_code


@pytest.mark.django_db
def test_pin6_access_code_cannot_be_modified(user_api_client, resource_in_unit, reservation, reservation_data):
    resource_in_unit.access_code_type = Resource.ACCESS_CODE_TYPE_PIN6
    resource_in_unit.save()
    reservation.access_code = '123456'
    reservation.save()
    reservation_data['access_code'] = '654321'

    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})
    response = user_api_client.put(detail_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == 400
    assert 'This field cannot be changed' in response.data['access_code']


@pytest.mark.parametrize('username, has_perm, expected', [
    ('test_user', False, True),  # own reservation
    ('test_user2', False, False),  # someone else's reservation
    ('test_user2', True, True),  # someone else's reservation but having the permission
    ('test_staff_user', False, False),  # staff
    ('test_general_admin', False, True),  # admin
])
@pytest.mark.django_db
def test_access_code_visibility(
        user, user2, staff_user, general_admin,
        api_client, resource_in_unit, reservation, username, has_perm,
        expected):
    resource_in_unit.access_code_type = Resource.ACCESS_CODE_TYPE_PIN6
    resource_in_unit.save()
    reservation.access_code = '123456'
    reservation.save()
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})

    current_user = User.objects.get(username=username)
    if has_perm:
        assign_perm('unit:can_view_reservation_access_code', current_user, resource_in_unit.unit)
    api_client.force_authenticate(current_user)

    response = api_client.get(detail_url)
    assert response.status_code == 200
    if expected:
        assert response.data['access_code'] == '123456'
    else:
        assert 'access_code' not in response.data


@override_settings(RESPA_MAILS_ENABLED=True)
@pytest.mark.django_db
def test_reservation_created_with_access_code_mail(user_api_client, user, resource_in_unit, list_url, reservation_data):
    reservation_data['preferred_language'] = 'en'

    # The mail should not be sent if access code type is none
    response = user_api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201
    assert len(mail.outbox) == 0

    reservation_data['access_code'] = '007007'
    resource_in_unit.access_code_type = Resource.ACCESS_CODE_TYPE_PIN6
    resource_in_unit.save()
    Reservation.objects.get(id=response.data['id']).delete()

    response = user_api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201
    file_name, ical_file, mimetype = mail.outbox[0].attachments[0]
    assert len(mail.outbox[0].attachments) == 1
    Calendar.from_ical(ical_file)
    check_received_mail_exists(
        'Reservation created',
        user.email,
        'Your access code for the resource: 007007',
    )

    # Verify that modifying the reservation doesn't trigger the mail
    reservation_data['end'] = '2115-04-04T12:00:00+02:00'
    detail_url = reverse('reservation-detail', kwargs={'pk': response.data['id']})
    response = user_api_client.put(detail_url, data=reservation_data)
    assert response.status_code == 200
    assert len(mail.outbox) == 0


@freeze_time('2115-04-02')
@pytest.mark.django_db
def test_reservation_reservable_before(user_api_client, resource_in_unit, list_url, reservation_data):
    resource_in_unit.reservable_max_days_in_advance = 10
    resource_in_unit.save()

    reservation_data['begin'] = timezone.now().replace(hour=12, minute=0, second=0) + datetime.timedelta(days=11)
    reservation_data['end'] = timezone.now().replace(hour=13, minute=0, second=0) + datetime.timedelta(days=11)

    response = user_api_client.post(list_url, data=reservation_data)
    assert response.status_code == 400
    assert_non_field_errors_contain(response, 'The resource is reservable only before')

    reservation_data['begin'] = timezone.now().replace(hour=12, minute=0, second=0) + datetime.timedelta(days=9)
    reservation_data['end'] = timezone.now().replace(hour=13, minute=0, second=0) + datetime.timedelta(days=9)

    response = user_api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201


@freeze_time('2115-04-02')
@pytest.mark.django_db
def test_reservation_reservable_after(user_api_client, resource_in_unit, list_url, reservation_data):
    resource_in_unit.reservable_min_days_in_advance = 8
    resource_in_unit.save()

    reservation_data['begin'] = timezone.now().replace(hour=12, minute=0, second=0) + datetime.timedelta(days=9)
    reservation_data['end'] = timezone.now().replace(hour=13, minute=0, second=0) + datetime.timedelta(days=9)

    response = user_api_client.post(list_url, data=reservation_data)
    msg = 'expected status_code {}, received {} with message "{}"'
    assert response.status_code == 201, msg.format(201, response.status_code, response.data)

    reservation_data['begin'] = timezone.now().replace(hour=12, minute=0, second=0) + datetime.timedelta(days=7)
    reservation_data['end'] = timezone.now().replace(hour=13, minute=0, second=0) + datetime.timedelta(days=7)

    response = user_api_client.post(list_url, data=reservation_data)
    msg = 'expected status_code {}, received {} with message "{}"'
    assert response.status_code == 400, msg.format(400, response.status_code, response.data)
    assert_non_field_errors_contain(response, 'The resource is reservable only after')


@freeze_time('2115-04-02')
@pytest.mark.django_db
def test_admins_can_make_reservations_despite_delay(
        api_client, list_url, resource_in_unit, reservation_data, general_admin):
    """
    Admin should be able to make reservations regardless of reservation delay limitations
    """
    api_client.force_authenticate(user=general_admin)
    resource_in_unit.reservable_min_days_in_advance = 10
    resource_in_unit.save()

    reservation_data['begin'] = timezone.now().replace(hour=12, minute=0, second=0) + datetime.timedelta(days=9)
    reservation_data['end'] = timezone.now().replace(hour=13, minute=0, second=0) + datetime.timedelta(days=9)

    response = api_client.post(list_url, data=reservation_data)
    msg = 'expected status_code {}, received {} with message "{}"'

    assert response.status_code == 201, msg.format(201, response.status_code, response.data)


@freeze_time('2115-04-02')
@pytest.mark.django_db
def test_reservation_reservable_before_payment_update(user_api_client, reservation, resource_in_unit):
    """
    Tests that when reservation state is ready for payment and update has no changing data i.e. user is trying to
    pay the reservation, update can be made even if reservable before would normally prevent it
    """
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})

    field_1 = ReservationMetadataField.objects.get(field_name='reserver_name')
    metadata_set = ReservationMetadataSet.objects.create(name='test_set',)
    metadata_set.supported_fields.set([field_1])
    reservation.resource.reservation_metadata_set = metadata_set
    reservation.resource.save(update_fields=('reservation_metadata_set',))

    resource_in_unit.reservable_max_days_in_advance = 5
    resource_in_unit.need_manual_confirmation = True
    resource_in_unit.save()

    reservation.begin = timezone.now().replace(hour=12, minute=0, second=0) + datetime.timedelta(days=9)
    reservation.end = timezone.now().replace(hour=13, minute=0, second=0) + datetime.timedelta(days=9)
    reservation.state = Reservation.READY_FOR_PAYMENT
    reservation.save()

    reservation_data = {
        'resource': resource_in_unit.id,
        'begin': reservation.begin,
        'end': reservation.end,
        'state': Reservation.READY_FOR_PAYMENT,
        'reserver_name': 'Test Updater'
    }

    # attempt to modify reservation, not pay
    response = user_api_client.put(detail_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == 400
    assert_non_field_errors_contain(response, 'The resource is reservable only before')

    # attempt to only update/pay reservation
    reservation_data = {
        'resource': resource_in_unit.id,
        'begin': reservation.begin,
        'end': reservation.end,
        'state': Reservation.READY_FOR_PAYMENT
    }
    response = user_api_client.put(detail_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == 200


@pytest.mark.django_db
def test_reservation_metadata_set(user_api_client, reservation, list_url, reservation_data):
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})
    field_1 = ReservationMetadataField.objects.get(field_name='reserver_name')
    field_2 = ReservationMetadataField.objects.get(field_name='reserver_phone_number')
    field_3 = ReservationMetadataField.objects.get(field_name='reservation_extra_questions')
    metadata_set = ReservationMetadataSet.objects.create(
        name='test_set',
    )
    metadata_set.supported_fields.set([field_1, field_2, field_3])
    metadata_set.required_fields.set([field_1])

    reservation.resource.reservation_metadata_set = metadata_set
    reservation.resource.save(update_fields=('reservation_metadata_set',))
    reservation_data['resource'] = reservation.resource.pk

    response = user_api_client.put(detail_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == 400
    assert 'This field is required.' in response.data['reserver_name']

    reservation_data['reserver_name'] = 'Mr. Reserver'
    reservation_data['reserver_phone_number'] = '0700-555555'
    reservation_data['reserver_address_street'] = 'ignored street 7'
    reservation_data['reservation_extra_questions'] = 'Yes this is extra question'

    response = user_api_client.put(detail_url, data=reservation_data)
    assert response.status_code == 200

    reservation.refresh_from_db()
    assert reservation.reserver_name == 'Mr. Reserver'
    assert reservation.reserver_phone_number == '0700-555555'
    assert reservation.reserver_address_street != 'ignored street 7'
    assert reservation.reservation_extra_questions == 'Yes this is extra question'


@pytest.mark.django_db
def test_detail_endpoint_does_not_need_all_true_filter(user_api_client, user, resource_in_unit):
    reservation_in_the_past = Reservation.objects.create(
        resource=resource_in_unit,
        begin='2005-04-04T09:00:00+02:00',
        end='2005-04-04T10:00:00+02:00',
        user=user,
    )

    detail_url = reverse('reservation-detail', kwargs={'pk': reservation_in_the_past.pk})
    response = user_api_client.get(detail_url)
    assert response.status_code == 200


@pytest.mark.django_db
def test_user_permissions_field(
        api_client, user_api_client,
        user, user2,
        resource_in_unit, reservation, detail_url):
    response = api_client.get(detail_url)
    assert response.status_code == 200
    assert response.data['user_permissions'] == {'can_delete': False, 'can_modify': False}

    response = user_api_client.get(detail_url)
    assert response.status_code == 200
    assert response.data['user_permissions'] == {'can_delete': True, 'can_modify': True}

    user_api_client.force_authenticate(user2)
    response = user_api_client.get(detail_url)
    assert response.status_code == 200
    assert response.data['user_permissions'] == {'can_delete': False, 'can_modify': False}

    user2.is_staff = True
    user2.save()
    response = user_api_client.get(detail_url)
    assert response.status_code == 200
    assert response.data['user_permissions'] == {'can_delete': False, 'can_modify': False}

    user2.is_general_admin = True
    user2.save()
    response = user_api_client.get(detail_url)
    assert response.status_code == 200
    assert response.data['user_permissions'] == {'can_delete': True, 'can_modify': True}


@pytest.mark.parametrize('filtering', (
    'event_subject=not so fancy',
    'host_name=arkku',
    'reserver_name=irkko',
))
@pytest.mark.django_db
def test_charfield_filters(user_api_client, staff_api_client, user, staff_user, reservation, reservation2,
                           reservation3, list_url, filtering):
    # without filters all reservations should be returned
    response = user_api_client.get(list_url)
    assert response.status_code == 200
    assert_response_objects(response, [reservation, reservation2, reservation3])

    url_with_filters = list_url + '?' + filtering

    # with the filter only one of the matching reservations should be returned
    # because the other one belongs to a different user
    response = user_api_client.get(url_with_filters)
    assert response.status_code == 200
    assert_response_objects(response, reservation2)

    # superusers don't have the above restriction
    staff_user.is_superuser = True
    staff_user.save()
    response = staff_api_client.get(url_with_filters)
    assert response.status_code == 200
    assert_response_objects(response, (reservation2, reservation3))

    # having the right permission allows the user to filter the other user's reservation also
    assign_perm('unit:can_view_reservation_extra_fields', user, reservation3.resource.unit)
    response = user_api_client.get(url_with_filters)
    assert response.status_code == 200
    assert_response_objects(response, (reservation2, reservation3))
    remove_perm('unit:can_view_reservation_extra_fields', user, reservation3.resource.unit)

    response = user_api_client.get(url_with_filters)
    assert response.status_code == 200
    assert_response_objects(response, reservation2)

    resource_group = reservation3.resource.groups.create(name='group3')
    group = user.groups.create(name='user group')
    assign_perm('group:can_view_reservation_extra_fields', group, resource_group)
    response = user_api_client.get(url_with_filters)
    assert response.status_code == 200
    assert_response_objects(response, (reservation2, reservation3))


@pytest.mark.django_db
def test_resource_name_filter(user_api_client, user, reservation, reservation2, reservation3, list_url):
    response = user_api_client.get(list_url)
    assert response.status_code == 200
    assert_response_objects(response, (reservation, reservation2, reservation3))

    response = user_api_client.get(list_url + '?resource_name=in unit 2')
    assert response.status_code == 200
    assert_response_objects(response, (reservation2, reservation3))


@pytest.mark.django_db
def test_is_favorite_resource_filter(user_api_client, user, resource_in_unit, reservation, reservation2,
                                     reservation3, list_url):
    user.favorite_resources.add(resource_in_unit)

    response = user_api_client.get(list_url + '?is_favorite_resource=true')
    assert response.status_code == 200
    assert_response_objects(response, reservation)

    response = user_api_client.get(list_url + '?is_favorite_resource=false')
    assert response.status_code == 200
    assert_response_objects(response, (reservation2, reservation3))


@pytest.mark.django_db
def test_resource_group_filter(user_api_client, user, reservation, reservation2, reservation3, resource_in_unit,
                               resource_in_unit2, resource_in_unit3, list_url):
    reservation2.resource = resource_in_unit2
    reservation2.save()

    reservation3.resource = resource_in_unit3
    reservation3.user = user
    reservation3.save()

    group_1 = ResourceGroup.objects.create(name='test group 1', identifier='test_group_1')
    resource_in_unit.groups.set([group_1])

    group_2 = ResourceGroup.objects.create(name='test group 2', identifier='test_group_2')
    resource_in_unit2.groups.set([group_1, group_2])

    group_3 = ResourceGroup.objects.create(name='test group 3', identifier='test_group_3')
    resource_in_unit3.groups.set([group_3])

    response = user_api_client.get(list_url)
    assert response.status_code == 200
    assert_response_objects(response, (reservation, reservation2, reservation3))

    response = user_api_client.get(list_url + '?' + 'resource_group=' + group_1.identifier)
    assert response.status_code == 200
    assert_response_objects(response, (reservation, reservation2))

    response = user_api_client.get(list_url + '?' + 'resource_group=' + group_2.identifier)
    assert response.status_code == 200
    assert_response_objects(response, reservation2)

    response = user_api_client.get(list_url + '?' + 'resource_group=%s,%s' % (group_1.identifier, group_2.identifier))
    assert response.status_code == 200
    assert_response_objects(response, (reservation, reservation2))

    response = user_api_client.get(list_url + '?' + 'resource_group=foobar')
    assert response.status_code == 200
    assert len(response.data['results']) == 0


@pytest.mark.django_db
def test_unit_filter(user_api_client, reservation, reservation2, resource_in_unit2, list_url):
    reservation2.resource = resource_in_unit2
    reservation2.save()

    response = user_api_client.get(list_url)
    assert response.status_code == 200
    assert_response_objects(response, (reservation, reservation2))

    response = user_api_client.get(list_url + '?unit=' + resource_in_unit2.unit.id)
    assert response.status_code == 200
    assert_response_objects(response, reservation2)

    response = user_api_client.get(list_url + '?unit=foobar')
    assert response.status_code == 200
    assert not len(response.data['results'])


@pytest.mark.django_db
def test_has_catering_order_filter(user_api_client, user, user2, resource_in_unit, reservation, reservation2,
                                   reservation3, list_url):
    provider = CateringProvider.objects.create(
        name='Kaikkein Kovin Catering Oy',
        price_list_url_fi='www.kaikkeinkovincatering.biz/hinnasto/',
    )
    CateringOrder.objects.create(
        reservation=reservation,
        provider=provider
    )
    CateringOrder.objects.create(
        reservation=reservation3,
        provider=provider
    )
    response = user_api_client.get(list_url + '?has_catering_order=true')
    assert response.status_code == 200
    assert_response_objects(response, reservation)

    response = user_api_client.get(list_url + '?has_catering_order=false')
    assert response.status_code == 200
    assert_response_objects(response, reservation2)

    user.is_superuser = True
    user.save()
    response = user_api_client.get(list_url + '?has_catering_order=true')
    assert response.status_code == 200
    assert_response_objects(response, (reservation, reservation3))

    user.is_superuser = False
    user.save()
    assign_perm('unit:can_view_reservation_catering_orders', user, reservation3.resource.unit)
    response = user_api_client.get(list_url + '?has_catering_order=true')
    assert response.status_code == 200
    assert_response_objects(response, (reservation, reservation3))
    remove_perm('unit:can_view_reservation_catering_orders', user, reservation3.resource.unit)

    resource_group = reservation3.resource.groups.create(name='rg1')
    assign_perm('group:can_view_reservation_catering_orders', user, resource_group)
    response = user_api_client.get(list_url + '?has_catering_order=true')
    assert response.status_code == 200
    assert_response_objects(response, (reservation, reservation3))


@pytest.mark.django_db
def test_has_catering_order_field(
        user_api_client, user, user2, reservation, detail_url):
    reservation.user = user2
    reservation.save()

    response = user_api_client.get(detail_url)
    assert response.status_code == 200
    assert 'has_catering_order' not in response.data

    user_api_client.force_authenticate(user2)
    response = user_api_client.get(detail_url)
    assert response.status_code == 200
    assert response.data['has_catering_order'] is False

    provider = CateringProvider.objects.create(
        name='Kaikkein Kovin Catering Oy',
        price_list_url_fi='www.kaikkeinkovincatering.biz/hinnasto/',
    )
    CateringOrder.objects.create(
        reservation=reservation,
        provider=provider,
    )

    response = user_api_client.get(detail_url)
    assert response.status_code == 200
    assert response.data['has_catering_order'] is True

    user_api_client.force_authenticate(user)
    user.is_general_admin = True
    user.save()

    response = user_api_client.get(detail_url)
    assert response.status_code == 200
    assert response.data['has_catering_order'] is True

    user.is_general_admin = False
    user.save()
    assign_perm('unit:can_view_reservation_catering_orders', user, reservation.resource.unit)
    reservation.catering_orders.all().delete()

    response = user_api_client.get(detail_url)
    assert response.status_code == 200
    assert response.data['has_catering_order'] is False


@pytest.mark.django_db
def test_normal_user_can_not_make_staff_reservation(
        api_client, list_url, reservation_data_extra, user):
    """
    Authenticated normal user should not be able to create a staff event reservation.
    """
    api_client.force_authenticate(user=user)
    reservation_data_extra['staff_event'] = True

    response = api_client.post(list_url, data=reservation_data_extra)
    assert response.status_code == 400


@pytest.mark.django_db
def test_manager_can_make_staff_reservation(
        resource_in_unit, list_url, reservation_data, staff_user, staff_api_client):
    """
    User with manager status on the resource should be able to make staff event reservations.
    """
    reservation_data['staff_event'] = True
    reservation_data['reserver_name'] = 'herra huu'
    reservation_data['event_description'] = 'herra huun bileet'
    UnitAuthorization.objects.create(subject=resource_in_unit.unit,
                                     level=UnitAuthorizationLevel.manager, authorized=staff_user)
    response = staff_api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201, "Request failed with: %s" % (str(response.content, 'utf8'))
    assert response.data.get('staff_event', False) is True
    reservation = Reservation.objects.get(id=response.data['id'])
    assert reservation.staff_event is True


@pytest.mark.django_db
def test_resource_filter(resource_in_unit, resource_in_unit2, other_resource, reservation, reservation2, reservation3,
                         api_client, list_url):
    # this should not be returned
    reservation3.resource = other_resource
    reservation3.save(update_fields=('resource',))

    response = api_client.get(list_url + '?resource={}'.format(resource_in_unit.id))
    assert response.status_code == 200
    assert_response_objects(response, reservation)

    response = api_client.get(list_url + '?resource={},{}'.format(resource_in_unit.id, resource_in_unit2.id))
    assert response.status_code == 200
    assert_response_objects(response, (reservation, reservation2))


@pytest.mark.django_db
def test_reservation_default_type(reservation_data, user_api_client):
    """ Reservation should return default reservation type """
    list_url = reverse('reservation-list')
    response = user_api_client.post(list_url, data=reservation_data)
    detail_url = reverse('reservation-detail', kwargs={'pk': response.data['id']})
    response = user_api_client.get(detail_url)
    assert response.data['type'] == Reservation.TYPE_NORMAL


@pytest.mark.django_db
def test_reservation_normal_type_normal_user(resource_in_unit, reservation_data, user_api_client):
    """ Normal user should be able to create a NORMAL type reservation """
    list_url = reverse('reservation-list')
    reservation_data['type'] = Reservation.TYPE_NORMAL
    response = user_api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201
    assert response.data['type'] == Reservation.TYPE_NORMAL


@pytest.mark.django_db
def test_reservation_block_type_normal_user(resource_in_unit, reservation_data, user_api_client):
    """ Normal user should not be able to create a BLOCKED type reservation """
    list_url = reverse('reservation-list')
    reservation_data['type'] = Reservation.TYPE_BLOCKED
    response = user_api_client.post(list_url, data=reservation_data)
    assert response.status_code == 400


@pytest.mark.django_db
def test_reservation_block_type_manager(resource_in_unit, reservation_data, api_client, unit_manager_user):
    """ Unit manager user should be able to create a BLOCKED type reservation """
    api_client.force_authenticate(unit_manager_user)
    list_url = reverse('reservation-list')
    reservation_data['type'] = Reservation.TYPE_BLOCKED
    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201
    assert response.data['type'] == Reservation.TYPE_BLOCKED
    reservation_obj = Reservation.objects.get(id=response.data['id'])
    assert reservation_obj.type == Reservation.TYPE_BLOCKED


@pytest.mark.django_db
def test_reservation_block_type_no_required_fields(resource_in_unit, reservation_data, api_client, unit_manager_user):
    """
    It should be possible to create blocked type reservations without filling in any required fields
    when the user has permission to create blocked reservations
    """
    field_1 = ReservationMetadataField.objects.get(field_name='reserver_name')
    field_2 = ReservationMetadataField.objects.get(field_name='reserver_phone_number')
    field_3 = ReservationMetadataField.objects.get(field_name='reserver_email_address')
    metadata_set = ReservationMetadataSet.objects.create(
        name='updated_metadata',
    )
    metadata_set.supported_fields.set([field_1, field_2, field_3])
    metadata_set.required_fields.set([field_1, field_2, field_3])
    resource_in_unit.reservation_metadata_set = ReservationMetadataSet.objects.get(name='updated_metadata')
    resource_in_unit.save()

    api_client.force_authenticate(unit_manager_user)
    list_url = reverse('reservation-list')
    reservation_data['type'] = Reservation.TYPE_BLOCKED
    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201
    assert response.data['type'] == Reservation.TYPE_BLOCKED
    reservation_obj = Reservation.objects.get(id=response.data['id'])
    assert reservation_obj.type == Reservation.TYPE_BLOCKED


@pytest.mark.django_db
def test_reservation_cannot_add_bogus_type(resource_in_unit, reservation_data, api_client, unit_manager_user):
    """ User should not be able to add a non-supported type to reservation """
    api_client.force_authenticate(unit_manager_user)
    list_url = reverse('reservation-list')
    reservation_data['type'] = 'foobar'
    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 400


@pytest.mark.django_db
def test_manager_can_make_reservations(
    resource_in_unit,
    resource_in_unit2,
    api_client, unit_manager_user,
    reservation_data,
    list_url
):
    # unit_manager_user is manager of resource_in_unit
    resource_in_unit.reservable = False
    resource_in_unit.save()
    api_client.force_authenticate(user=unit_manager_user)
    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201

    # unit_manager_user is NOT manager of resource_in_unit2
    resource_in_unit2.reservable = False
    resource_in_unit2.save()
    reservation_data['resource'] = resource_in_unit2.pk
    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 403


@pytest.mark.django_db
def test_manager_can_modify_reservations(resource_in_unit, resource_in_unit2, api_client, unit_manager_user, reservation_data, list_url, detail_url):
    # unit_manager_user is manager of resource_in_unit (resource of reservation_data)
    api_client.force_authenticate(user=unit_manager_user)
    response = api_client.put(detail_url, data=reservation_data)
    assert response.status_code == 200

    # unit_manager_user is NOT manager of resource_in_unit2
    reservation_data['resource'] = resource_in_unit2.pk
    response = api_client.put(detail_url, data=reservation_data)
    assert response.status_code == 400


@freeze_time('2115-04-02')
@pytest.mark.django_db
def test_manager_can_ignore_opening_hours(api_client, list_url, reservation_data, unit_manager_user, user):
    # regular user should not be aple to ignore opening hours
    api_client.force_authenticate(user=user)
    reservation_data['begin'] = '2115-04-04T06:00:00+02:00'
    reservation_data['end'] = '2115-04-04T08:00:00+02:00'
    response = api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == 400

    api_client.force_authenticate(user=unit_manager_user)
    reservation_data['begin'] = '2115-04-04T06:00:00+02:00'
    reservation_data['end'] = '2115-04-04T08:00:00+02:00'
    response = api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == 201


@pytest.mark.django_db
def test_manager_can_view_reservation_access_code(api_client, resource_in_unit, reservation, unit_manager_user):
    resource_in_unit.access_code_type = Resource.ACCESS_CODE_TYPE_PIN6
    resource_in_unit.save()
    reservation.access_code = '123456'
    reservation.save()
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})

    api_client.force_authenticate(user=unit_manager_user)
    response = api_client.get(detail_url)
    assert response.status_code == 200
    assert response.data['access_code'] == '123456'


@pytest.mark.django_db
def test_manager_can_view_reservation_extra_fields(api_client, resource_in_unit, reservation, unit_manager_user):
    resource_in_unit.reservation_metadata_set = ReservationMetadataSet.objects.get(name='default')
    resource_in_unit.save()
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})
    api_client.force_authenticate(user=unit_manager_user)

    response = api_client.get(detail_url)
    assert response.status_code == 200
    for field_name in DEFAULT_RESERVATION_EXTRA_FIELDS:
        assert (field_name in response.data) is True


@pytest.mark.django_db
def test_manager_can_access_reservation_comments(api_client, resource_in_unit, reservation, unit_manager_user):
    reservation.comments = 'To be a foo or not to be a foo, that is the question'
    reservation.save()
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})
    api_client.force_authenticate(user=unit_manager_user)

    response = api_client.get(detail_url)
    assert response.status_code == 200
    assert response.data['comments'] == 'To be a foo or not to be a foo, that is the question'


@pytest.mark.django_db
def test_manager_can_view_reservation_catering_orders(api_client, reservation, unit_manager_user):
    provider = CateringProvider.objects.create(
        name='Ihan Hyva Catering Oy',
        price_list_url_fi='www.ihanhyva.foobar/hinnasto/',
    )
    CateringOrder.objects.create(
        reservation=reservation,
        provider=provider
    )

    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})
    api_client.force_authenticate(user=unit_manager_user)

    response = api_client.get(detail_url)
    assert response.status_code == 200
    assert response.data['has_catering_order'] == True


@pytest.mark.django_db
def test_viewer_can_view_reservation_access_code(api_client, reservation, unit_viewer_user, resource_in_unit):
    resource_in_unit.access_code_type = Resource.ACCESS_CODE_TYPE_PIN6
    resource_in_unit.save()
    reservation.access_code = '123456'
    reservation.save()
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})

    api_client.force_authenticate(user=unit_viewer_user)
    response = api_client.get(detail_url)
    assert response.status_code == 200
    assert response.data['access_code'] == '123456'


@pytest.mark.django_db
def test_viewer_can_view_reservation_extra_fields(api_client, resource_in_unit, reservation, unit_viewer_user):
    resource_in_unit.reservation_metadata_set = ReservationMetadataSet.objects.get(name='default')
    resource_in_unit.save()
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})
    api_client.force_authenticate(user=unit_viewer_user)

    response = api_client.get(detail_url)
    assert response.status_code == 200
    for field_name in DEFAULT_RESERVATION_EXTRA_FIELDS:
        assert (field_name in response.data) is True


@pytest.mark.django_db
def test_viewer_can_access_reservation_comments(api_client, reservation, unit_viewer_user):
    reservation.comments = 'To be a foo or not to be a foo, that is the question'
    reservation.save()
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})
    api_client.force_authenticate(user=unit_viewer_user)

    response = api_client.get(detail_url)
    assert response.status_code == 200
    assert response.data['comments'] == 'To be a foo or not to be a foo, that is the question'


@pytest.mark.django_db
def test_viewer_can_view_reservation_user(api_client, reservation, unit_viewer_user, user):
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation.pk})
    api_client.force_authenticate(user=unit_viewer_user)

    response = api_client.get(detail_url)
    assert response.status_code == 200
    assert response.data['user']['email'] == user.email


@pytest.mark.django_db
def test_viewer_can_modify_reservations(resource_in_unit, resource_in_unit2, api_client, unit_viewer_user, reservation_data, detail_url):
    # unit_viewer_user is viewer of resource_in_unit (resource of reservation_data)
    api_client.force_authenticate(user=unit_viewer_user)
    response = api_client.put(detail_url, data=reservation_data)
    assert response.status_code == 200

    # unit_viewer_user is NOT viewer of resource_in_unit2
    reservation_data['resource'] = resource_in_unit2.pk
    response = api_client.put(detail_url, data=reservation_data)
    assert response.status_code == 400


@pytest.mark.django_db
def test_viewer_can_comment_reservations(resource_in_unit, api_client, unit_viewer_user, reservation_data, detail_url):
    api_client.force_authenticate(user=unit_viewer_user)
    reservation_data['comments'] = 'test comment'
    response = api_client.put(detail_url, data=reservation_data)
    assert response.status_code == 200


@pytest.mark.django_db
def test_admin_can_make_staff_reservation(
        resource_in_unit, list_url, reservation_data, unit_admin_user, api_client):
    """
    User with admin status on the resource should be able to make staff event reservations.
    """
    reservation_data['staff_event'] = True
    reservation_data['reserver_name'] = 'herra huu'
    reservation_data['event_description'] = 'herra huun bileet'

    api_client.force_authenticate(user=unit_admin_user)
    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201, "Request failed with: %s" % (str(response.content, 'utf8'))
    assert response.data.get('staff_event', False) is True
    reservation = Reservation.objects.get(id=response.data['id'])
    assert reservation.staff_event is True


@pytest.mark.django_db
def test_admin_can_create_special_type_reservation(
        resource_in_unit, list_url, reservation_data, unit_admin_user, api_client):
    """
    User with admin status on the resource should be able to make special type reservations.
    """
    reservation_data['type'] = Reservation.TYPE_BLOCKED

    api_client.force_authenticate(user=unit_admin_user)
    response = api_client.post(list_url, data=reservation_data)

    assert response.status_code == 201
    reservation = Reservation.objects.get(id=response.data['id'])
    assert reservation.type == Reservation.TYPE_BLOCKED


@pytest.mark.django_db
def test_manager_can_create_special_type_reservation(
        resource_in_unit, list_url, reservation_data, unit_manager_user, api_client):
    """
    User with manager status on the resource should be able to make special type reservations.
    """
    reservation_data['type'] = Reservation.TYPE_BLOCKED

    api_client.force_authenticate(user=unit_manager_user)
    response = api_client.post(list_url, data=reservation_data)

    assert response.status_code == 201
    reservation = Reservation.objects.get(id=response.data['id'])
    assert reservation.type == Reservation.TYPE_BLOCKED


@pytest.mark.django_db
def test_admin_can_bypass_manual_confirmation(
        resource_in_unit, list_url, reservation_data, unit_admin_user, api_client):
    """
    User with admin status on the resource should be able to bypass manual confirmation.
    """

    resource_in_unit.need_manual_confirmation = True
    resource_in_unit.save()

    api_client.force_authenticate(user=unit_admin_user)
    response = api_client.post(list_url, data=reservation_data)

    assert response.status_code == 201
    reservation = Reservation.objects.get(id=response.data['id'])
    assert reservation.state != Reservation.REQUESTED


@pytest.mark.django_db
def test_manager_can_bypass_manual_confirmation(
        resource_in_unit, list_url, reservation_data, unit_manager_user, api_client):
    """
    User with manager status on the resource should be able to bypass manual confirmation.
    """

    resource_in_unit.need_manual_confirmation = True
    resource_in_unit.save()

    api_client.force_authenticate(user=unit_manager_user)
    response = api_client.post(list_url, data=reservation_data)

    assert response.status_code == 201
    reservation = Reservation.objects.get(id=response.data['id'])
    assert reservation.state != Reservation.REQUESTED


@pytest.mark.django_db
def test_query_counts(user_api_client, staff_api_client, list_url, django_assert_max_num_queries):
    """
    Test that DB query count is less than allowed
    """
    with django_assert_max_num_queries(MAX_QUERIES):
        user_api_client.get(list_url)

    with django_assert_max_num_queries(MAX_QUERIES):
        staff_api_client.get(list_url)


@pytest.mark.django_db
def test_admin_may_bypass_min_period(resource_in_unit, user, user_api_client, list_url):
    # min_period is bypassed respecting slot_size restriction
    resource_in_unit.min_period = datetime.timedelta(hours=1)
    resource_in_unit.slot_size = datetime.timedelta(minutes=30)
    resource_in_unit.save()

    UnitAuthorization.objects.create(
        subject=resource_in_unit.unit,
        level=UnitAuthorizationLevel.admin,
        authorized=user,
    )

    tz = timezone.get_current_timezone()
    begin = tz.localize(datetime.datetime(2115, 6, 1, 8, 0, 0))
    end = begin + datetime.timedelta(hours=0, minutes=30)

    reservation_data = {
        'resource': resource_in_unit.pk,
        'begin': begin,
        'end': end,
    }

    response = user_api_client.post(list_url, reservation_data)
    assert response.status_code == 201
    Reservation.objects.all().delete()

    # min_period is bypassed and slot_size restriction is violated
    resource_in_unit.slot_size = datetime.timedelta(minutes=25)
    resource_in_unit.save()

    response = user_api_client.post(list_url, reservation_data)
    assert response.status_code == 400


@pytest.mark.django_db
def test_can_ignore_max_period(resource_with_opening_hours, user, user_api_client, list_url):
    resource_with_opening_hours.max_period = datetime.timedelta(hours=1)
    resource_with_opening_hours.save()

    tz = timezone.get_current_timezone()
    begin = tz.localize(datetime.datetime(2115, 6, 1, 8, 0, 0))
    end = begin + datetime.timedelta(hours=2)

    reservation_data = {
        'resource': resource_with_opening_hours.pk,
        'begin': begin,
        'end': end,
    }

    # Normal user can not ignore max_period
    response = user_api_client.post(list_url, reservation_data)
    assert response.status_code == 400

    UnitAuthorization.objects.create(
        subject=resource_with_opening_hours.unit,
        level=UnitAuthorizationLevel.admin,
        authorized=user,
    )

    # Admin can ignore max_period
    response = user_api_client.post(list_url, reservation_data)
    assert response.status_code == 201
    UnitAuthorization.objects.filter(authorized=user).delete()
    Reservation.objects.filter(user=user, resource=resource_with_opening_hours).delete()

    UnitAuthorization.objects.create(
        subject=resource_with_opening_hours.unit,
        level=UnitAuthorizationLevel.manager,
        authorized=user,
    )

    # Manager can ignore max_period
    response = user_api_client.post(list_url, reservation_data)
    assert response.status_code == 201


@pytest.mark.django_db
def test_can_ignore_max_reservations_per_user(resource_with_opening_hours, user, user_api_client, list_url):
    resource_with_opening_hours.max_reservations_per_user = 1
    resource_with_opening_hours.save()

    tz = timezone.get_current_timezone()
    begin = tz.localize(datetime.datetime(2115, 6, 1, 8, 0, 0))
    end = begin + datetime.timedelta(hours=1)

    reservation_data = {
        'resource': resource_with_opening_hours.pk,
        'begin': begin,
        'end': end,
    }

    begin2 = tz.localize(datetime.datetime(2115, 6, 2, 8, 0, 0))
    end2 = begin2 + datetime.timedelta(hours=1)

    reservation_data_2 = {
        'resource': resource_with_opening_hours.pk,
        'begin': begin2,
        'end': end2,
    }

    # Normal user can not ignore max_reservations_per_user
    response = user_api_client.post(list_url, reservation_data)
    assert response.status_code == 201
    response = user_api_client.post(list_url, reservation_data_2)
    assert response.status_code == 400
    Reservation.objects.filter(user=user, resource=resource_with_opening_hours).delete()

    UnitAuthorization.objects.create(
        subject=resource_with_opening_hours.unit,
        level=UnitAuthorizationLevel.admin,
        authorized=user,
    )

    # Admin can ignore max_reservations_per_user
    response = user_api_client.post(list_url, reservation_data)
    assert response.status_code == 201
    response = user_api_client.post(list_url, reservation_data_2)
    assert response.status_code == 201
    Reservation.objects.filter(user=user, resource=resource_with_opening_hours).delete()
    UnitAuthorization.objects.filter(authorized=user).delete()

    UnitAuthorization.objects.create(
        subject=resource_with_opening_hours.unit,
        level=UnitAuthorizationLevel.manager,
        authorized=user,
    )

    # Manager can ignore max_reservations_per_user
    response = user_api_client.post(list_url, reservation_data)
    assert response.status_code == 201
    response = user_api_client.post(list_url, reservation_data_2)
    assert response.status_code == 201


@pytest.mark.django_db
def test_disallow_overlapping_reservations(resource_in_unit, resource_in_unit2, user, user_api_client, list_url):
    expected_error = ErrorDetail(
        string="['This unit does not allow overlapping reservations for its resources']",
        code='conflicting_reservation'
    )
    resource_in_unit.unit.disallow_overlapping_reservations = True
    resource_in_unit.unit.save()

    period = Period.objects.create(
        start=datetime.date(2115, 1, 1),
        end=datetime.date(2115, 12, 31),
        resource=resource_in_unit, name='regular hours'
    )
    period2 = Period.objects.create(
        start=datetime.date(2115, 1, 1),
        end=datetime.date(2115, 12, 31),
        resource=resource_in_unit2, name='regular hours'
    )

    for weekday in range(0, 7):
        Day.objects.create(
            period=period,
            weekday=weekday,
            opens=datetime.time(8, 0),
            closes=datetime.time(18, 0)
        )
        Day.objects.create(
            period=period2,
            weekday=weekday,
            opens=datetime.time(8, 0),
            closes=datetime.time(18, 0)
        )

    resource_in_unit.update_opening_hours()
    resource_in_unit2.update_opening_hours()

    resource_in_unit2.unit = resource_in_unit.unit
    resource_in_unit2.save()

    # Initial reservation, which should be created normally
    reservation_data = {
        'resource': resource_in_unit.pk,
        'begin': '2115-04-04T12:00:00+02:00',
        'end': '2115-04-04T14:00:00+02:00'
    }
    response = user_api_client.post(list_url, reservation_data)
    assert response.status_code == 201

    # Try every possibility to overlap existing reservation
    reservation_data2 = {
        'resource': resource_in_unit2.pk,
        'begin': '2115-04-04T11:00:00+02:00',
        'end': '2115-04-04T12:30:00+02:00'
    }
    reservation_data3 = {
        'resource': resource_in_unit2.pk,
        'begin': '2115-04-04T13:30:00+02:00',
        'end': '2115-04-04T14:30:00+02:00'
    }
    reservation_data4 = {
        'resource': resource_in_unit2.pk,
        'begin': '2115-04-04T12:30:00+02:00',
        'end': '2115-04-04T13:00:00+02:00'
    }
    reservation_data5 = {
        'resource': resource_in_unit2.pk,
        'begin': '2115-04-04T12:00:00+02:00',
        'end': '2115-04-04T14:00:00+02:00'
    }
    reservation_data6 = {
        'resource': resource_in_unit2.pk,
        'begin': '2115-04-04T12:30:00+02:00',
        'end': '2115-04-04T13:00:00+02:00'
    }

    response2 = user_api_client.post(list_url, reservation_data2, HTTP_ACCEPT_LANGUAGE='en')
    assert response2.data['non_field_errors'][0] == expected_error
    assert response2.status_code == 400

    response3 = user_api_client.post(list_url, reservation_data3, HTTP_ACCEPT_LANGUAGE='en')
    assert response3.data['non_field_errors'][0] == expected_error
    assert response3.status_code == 400

    response4 = user_api_client.post(list_url, reservation_data4, HTTP_ACCEPT_LANGUAGE='en')
    assert response4.data['non_field_errors'][0] == expected_error
    assert response4.status_code == 400

    response5 = user_api_client.post(list_url, reservation_data5, HTTP_ACCEPT_LANGUAGE='en')
    assert response5.data['non_field_errors'][0] == expected_error
    assert response5.status_code == 400

    response6 = user_api_client.post(list_url, reservation_data6, HTTP_ACCEPT_LANGUAGE='en')
    assert response6.data['non_field_errors'][0] == expected_error
    assert response6.status_code == 400

    # Admin user should be allowed to overlap reservations
    UnitAuthorization.objects.create(
        subject=resource_in_unit.unit,
        level=UnitAuthorizationLevel.admin,
        authorized=user,
    )
    response_admin = user_api_client.post(list_url, reservation_data2)
    assert response_admin.status_code == 201

    created_reservation = Reservation.objects.get(id=response_admin.data['id'])
    created_reservation.delete()

    # Manager user should be allowed to overlap reservations as well
    UnitAuthorization.objects.all().delete()
    UnitAuthorization.objects.create(
        subject=resource_in_unit.unit,
        level=UnitAuthorizationLevel.manager,
        authorized=user,
    )
    response_manager = user_api_client.post(list_url, reservation_data2)
    assert response_manager.status_code == 201

    # Cancelled reservations should not be taken into account
    UnitAuthorization.objects.all().delete()
    Reservation.objects.all().delete()
    response = user_api_client.post(list_url, reservation_data)
    assert response.status_code == 201
    reservation = Reservation.objects.all()[0]
    reservation.set_state(Reservation.CANCELLED, user)

    assert reservation.state == Reservation.CANCELLED

    response2 = user_api_client.post(list_url, reservation_data2)
    assert response2.status_code == 201


@pytest.mark.django_db
def test_reservation_can_be_made_to_unit_with_overlap_restriction_when_no_overlap(
    api_client, reservation_data, user, list_url, resource_in_unit4_1
):
    """
    Tests that a reservation can be made to a resource in unit with overlap restriction
    when there is no overlap
    """
    api_client.force_authenticate(user=user)
    reservation_data['resource'] = resource_in_unit4_1.pk
    reservation_data['begin'] = '2115-04-04T09:00:00+02:00'
    reservation_data['end'] = '2115-04-04T10:00:00+02:00'
    response = api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == 201


@pytest.mark.parametrize("resource,is_staff,expected", [
    (1, False, 400),
    (2, False, 400),
    (1, True, 400),
    (2, True, 201),
])
@pytest.mark.django_db
def test_reservations_made_to_unit_with_overlap_restriction_when_overlapping(
    resource, is_staff, expected, api_client, reservation_data,
    user, unit4_manager_user, list_url, resource_in_unit4_1, resource_in_unit4_2, reservation4
):
    """
    Tests that reservations are handled correctly to resources in units with overlap
    restrictions
    """
    if is_staff:
        api_client.force_authenticate(user=unit4_manager_user)
    else:
        api_client.force_authenticate(user=user)

    reservation_data['resource'] = resource_in_unit4_1.pk if resource == 1 else resource_in_unit4_2.pk
    reservation_data['begin'] = '2115-04-04T09:00:00+02:00'
    reservation_data['end'] = '2115-04-04T10:00:00+02:00'
    response = api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == expected


@pytest.mark.django_db
def test_reservation_can_be_updated_in_unit_with_overlap_restriction_when_no_overlap(
    api_client, reservation_data, user, resource_in_unit4_1, reservation4
):
    """
    Tests that a reservation can be updated to a resource in unit with overlap restriction
    when there is no overlap
    """
    api_client.force_authenticate(user=user)
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation4.pk})

    reservation_data['resource'] = resource_in_unit4_1.pk
    reservation_data['begin'] = '2115-04-04T09:00:00+02:00'
    reservation_data['end'] = '2115-04-04T12:00:00+02:00'
    response = api_client.put(detail_url, reservation_data)
    assert response.status_code == 200
    reservation = Reservation.objects.get(pk=reservation4.pk)
    assert reservation.begin == dateparse.parse_datetime('2115-04-04T09:00:00+02:00')
    assert reservation.end == dateparse.parse_datetime('2115-04-04T12:00:00+02:00')


@pytest.mark.django_db
def test_reservation_can_be_made_to_unit_with_per_user_overlap_restriction_when_no_overlap(
    api_client, reservation_data, user, list_url, resource_in_unit4_1
):
    """
    Tests that a reservation can be made to a resource in unit with per user overlap restriction
    when there is no overlap
    """
    resource_in_unit4_1.disallow_overlapping_reservations_per_user = True
    resource_in_unit4_1.save()
    api_client.force_authenticate(user=user)
    reservation_data['resource'] = resource_in_unit4_1.pk
    reservation_data['begin'] = '2115-04-04T09:00:00+02:00'
    reservation_data['end'] = '2115-04-04T10:00:00+02:00'
    response = api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == 201


@pytest.mark.parametrize("same_user,expected", [
    (True, 400),
    (False, 201),
])
@pytest.mark.django_db
def test_reservations_made_to_unit_with_per_user_overlap_restriction(
    api_client, reservation_data, user, user2, list_url, test_unit4, resource_in_unit4_2,
    reservation4, same_user, expected
):
    """
    Tests that reservations are handled correctly to a resource in unit with per user overlap restriction
    when same or other user has made a reservation to another resource in the same unit with overlapping time
    """
    test_unit4.disallow_overlapping_reservations_per_user = True
    test_unit4.save()
    if same_user:
        api_client.force_authenticate(user=user)
    else:
        api_client.force_authenticate(user=user2)

    reservation_data['resource'] = resource_in_unit4_2.pk
    reservation_data['begin'] = '2115-04-04T09:00:00+02:00'
    reservation_data['end'] = '2115-04-04T10:00:00+02:00'
    response = api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == expected
    if expected == 400:
        assert response.data.get('non_field_errors')[0].code == 'conflicting_reservation'


@pytest.mark.django_db
def test_reservation_can_be_made_to_unit_with_per_user_overlap_restriction_and_anon_user(
    api_client, reservation_data, list_url, test_unit4, resource_in_unit4_2, reservation4
):
    """Tests that anon users can bypass per user overlap restriction"""
    test_unit4.disallow_overlapping_reservations_per_user = True
    test_unit4.save()
    resource_in_unit4_2.authentication = 'unauthenticated'
    resource_in_unit4_2.save()

    reservation_data['resource'] = resource_in_unit4_2.pk
    reservation_data['begin'] = '2115-04-04T09:00:00+02:00'
    reservation_data['end'] = '2115-04-04T10:00:00+02:00'
    response = api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == 201


@pytest.mark.django_db
def test_reservation_can_be_updated_in_unit_with_per_user_overlap_restriction_when_no_overlap(
    api_client, reservation_data, user, resource_in_unit4_1, reservation4, test_unit4
):
    """
    Tests that a reservation can be updated to a resource in unit with per user overlap restriction
    when there is no overlap
    """
    test_unit4.disallow_overlapping_reservations_per_user = True
    test_unit4.save()
    api_client.force_authenticate(user=user)
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation4.pk})

    reservation_data['resource'] = resource_in_unit4_1.pk
    reservation_data['begin'] = '2115-04-04T09:00:00+02:00'
    reservation_data['end'] = '2115-04-04T12:00:00+02:00'
    response = api_client.put(detail_url, reservation_data)
    assert response.status_code == 200
    reservation = Reservation.objects.get(pk=reservation4.pk)
    assert reservation.begin == dateparse.parse_datetime('2115-04-04T09:00:00+02:00')
    assert reservation.end == dateparse.parse_datetime('2115-04-04T12:00:00+02:00')


@pytest.mark.django_db
def test_reservation_cannot_be_updated_in_unit_with_per_user_overlap_restriction_when_overlapping(
    api_client, reservation_data, user, resource_in_unit4_1, reservation4, reservation5, test_unit4
):
    """
    Tests that a reservation cannot be updated to a resource in unit with per user overlap restriction
    when there is overlap
    """
    test_unit4.disallow_overlapping_reservations_per_user = True
    test_unit4.save()
    api_client.force_authenticate(user=user)
    detail_url = reverse('reservation-detail', kwargs={'pk': reservation4.pk})

    # update reservation to overlap with reservation5
    reservation_data['resource'] = resource_in_unit4_1.pk
    reservation_data['begin'] = '2115-04-04T09:00:00+02:00'
    reservation_data['end'] = '2115-04-04T13:00:00+02:00'
    response = api_client.put(detail_url, reservation_data)
    assert response.status_code == 400
    assert response.data.get('non_field_errors')[0].code == 'conflicting_reservation'


@pytest.mark.parametrize("begin,end,expected", [
    ('2115-04-03T09:00:00+02:00', '2115-04-03T09:30:00+02:00', 201),
    ('2115-04-04T08:00:00+02:00', '2115-04-04T08:30:00+02:00', 201),
    ('2115-04-04T08:30:00+02:00', '2115-04-04T09:00:00+02:00', 201),
    ('2115-04-04T08:30:00+02:00', '2115-04-04T09:30:00+02:00', 400),
    ('2115-04-04T08:30:00+02:00', '2115-04-04T10:00:00+02:00', 400),
    ('2115-04-04T08:30:00+02:00', '2115-04-04T11:00:00+02:00', 400),
    ('2115-04-04T09:00:00+02:00', '2115-04-04T09:30:00+02:00', 400),
    ('2115-04-04T09:00:00+02:00', '2115-04-04T10:00:00+02:00', 400),
    ('2115-04-04T09:00:00+02:00', '2115-04-04T11:00:00+02:00', 400),
    ('2115-04-04T09:30:00+02:00', '2115-04-04T10:00:00+02:00', 400),
    ('2115-04-04T09:30:00+02:00', '2115-04-04T11:00:00+02:00', 400),
    ('2115-04-04T10:00:00+02:00', '2115-04-04T10:30:00+02:00', 201),
    ('2115-04-04T10:30:00+02:00', '2115-04-04T11:00:00+02:00', 201),
    ('2115-04-05T09:00:00+02:00', '2115-04-05T09:30:00+02:00', 201),
])
@pytest.mark.django_db
def test_reservations_made_to_unit_with_overlap_restriction_with_different_times(
    begin, end, expected, api_client, reservation_data, user, list_url,
    resource_in_unit4_1, resource_in_unit4_2, reservation4, reservation5
):
    """
    Tests that reservations are handled correctly to resources in units with overlap
    restrictions when reserving different length reservations and with different overlaps
    """
    api_client.force_authenticate(user=user)
    reservation_data['resource'] = resource_in_unit4_2.pk
    reservation_data['begin'] = begin
    reservation_data['end'] = end
    response = api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == expected
    if expected == 400:
        assert response.data.get('non_field_errors')[0].code == 'conflicting_reservation'

@pytest.mark.django_db
def test_reservation_not_allowed_during_maintenance_mode(
    api_client, user, list_url, reservation_data_extra, maintenance_mode):
    api_client.force_authenticate(user=user)

    response = api_client.post(list_url, data=reservation_data_extra)
    assert response.status_code == 400
    assert_non_field_errors_contain(response, 'Reservations are disabled at this moment')


@pytest.mark.django_db
def test_reservation_reminder_create(
    api_client, user, list_url, reservation_data,
    resource_with_reservation_reminders):
    api_client.force_authenticate(user=user)
    reservation_data['resource'] = resource_with_reservation_reminders.pk
    reservation_data['reserver_name'] = 'Nordea Demo'
    reservation_data['reserver_email_address'] = 'jey@example.com'
    reservation_data['reserver_phone_number'] = '+358404040404'
    response = api_client.post(list_url, data=reservation_data, HTTP_ACCEPT_LANGUAGE='en')
    assert response.status_code == 201
    assert ReservationReminder.objects.count() == 1


@override_settings(RESPA_MAILS_ENABLED=True)
@pytest.mark.django_db
def test_no_notification_on_reservation_type_blocked(
    resource_in_unit, reservation_data,
    staff_api_client, staff_user, list_url,
    reservation_created_by_official_notification):
    UnitAuthorization.objects.create(subject=resource_in_unit.unit,
                                     level=UnitAuthorizationLevel.manager, authorized=staff_user)

    reservation_data['resource'] = resource_in_unit.pk
    reservation_data['reserver_name'] = 'Staff reservation normal'
    reservation_data['type'] = Reservation.TYPE_BLOCKED

    response = staff_api_client.post(list_url, data=reservation_data, format='json')
    assert response.status_code == 201
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_recurring_reservation(
    resource_in_unit4_1, recurring_reservation_data,
    staff_api_client, staff_user, recurring_url):
    UnitAuthorization.objects.create(subject=resource_in_unit4_1.unit,
                                     level=UnitAuthorizationLevel.manager, authorized=staff_user)
    
    recurring_reservation_data['reserver_name'] = 'Recurring reservation'
    assert ReservationBulk.objects.count() == 0
    assert Reservation.objects.count() == 0

    response = staff_api_client.post(recurring_url, data=recurring_reservation_data, format='json')
    assert response.status_code == 201
    assert ReservationBulk.objects.count() == 1
    
    reservation_bulk = ReservationBulk.objects.first()
    assert reservation_bulk.reservations.count() == 3


@pytest.mark.django_db
def test_recurring_reservation_too_many_reservations_at_once(
    resource_in_unit4_1, recurring_reservation_data,
    staff_api_client, staff_user, recurring_url):
    UnitAuthorization.objects.create(subject=resource_in_unit4_1.unit,
                                     level=UnitAuthorizationLevel.manager, authorized=staff_user)
    
    recurring_reservation_data['reserver_name'] = 'Recurring reservation'

    first_reservation = recurring_reservation_data['reservation_stack'][0]
    for _ in range(0,101): recurring_reservation_data['reservation_stack'].append(first_reservation)
    response = staff_api_client.post(recurring_url, data=recurring_reservation_data, format='json')
    assert response.status_code == 406


@pytest.mark.django_db
def test_recurring_reservation_bad_period(
    resource_in_unit4_1, recurring_reservation_data,
    staff_api_client, staff_user, recurring_url):
    UnitAuthorization.objects.create(subject=resource_in_unit4_1.unit,
                                     level=UnitAuthorizationLevel.manager, authorized=staff_user)
    
    recurring_reservation_data['reserver_name'] = 'Recurring reservation'

    recurring_reservation_data['reservation_stack'] = [{
        'begin': '2115-04-04T11:00:00+02:00',
        'end': '2115-04-05T12:00:00+02:00',
    }]
    response = staff_api_client.post(recurring_url, data=recurring_reservation_data, format='json')
    assert response.status_code == 400

@pytest.mark.django_db
def test_recurring_reservation_reminders(
    resource_in_unit4_1, recurring_reservation_data,
    staff_api_client, staff_user, recurring_url):
    UnitAuthorization.objects.create(subject=resource_in_unit4_1.unit,
                                     level=UnitAuthorizationLevel.manager, authorized=staff_user)
    resource_in_unit4_1.unit.sms_reminder = True
    resource_in_unit4_1.unit.save()

    meta_field = ReservationMetadataField.objects.get(field_name='reserver_phone_number')
    metadata_set = ReservationMetadataSet.objects.create(
        name='metadata_with_reserver_phone_number',
    )
    metadata_set.supported_fields.set([meta_field])
    metadata_set.required_fields.set([meta_field])
    resource_in_unit4_1.reservation_metadata_set = metadata_set
    resource_in_unit4_1.save()
    response = staff_api_client.post(recurring_url, data=recurring_reservation_data, format='json')
    assert response.status_code == 201
    assert ReservationBulk.objects.count() == 1
    
    reservation_bulk = ReservationBulk.objects.first()
    assert reservation_bulk.reservations.count() == 3

    for reservation in reservation_bulk.reservations.all():
        assert reservation.reminder is not None
        
@pytest.mark.django_db
@freeze_time('2115-04-04')
def test_reservation_cooldown_unit_staff(
    resource_with_cooldown, reservation_data,
    staff_api_client, staff_user, 
    api_client, user, list_url):
    UnitAuthorization.objects.create(subject=resource_with_cooldown.unit,
                                     level=UnitAuthorizationLevel.manager, authorized=staff_user)
    reservation_data['resource'] = resource_with_cooldown.pk
    
    api_client.force_authenticate(user=user)
    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201

    reservation_data['begin'] = '2115-04-04T12:00:00+02:00'
    reservation_data['end'] = '2115-04-04T13:00:00+02:00'

    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 400
    assert_translated_response_contains(response, 'cooldown', 'Cannot be reserved during cooldown')

    staff_api_client.force_authenticate(user=staff_user)
    response = staff_api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201

@pytest.mark.django_db
@freeze_time('2115-04-04')
def test_reservation_cooldown_after_first_reservation(
        resource_with_cooldown, reservation_data,
        api_client, user, list_url):
    reservation_data['resource'] = resource_with_cooldown.pk
    api_client.force_authenticate(user=user)
    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201

    reservation_data['begin'] = '2115-04-04T12:00:00+02:00'
    reservation_data['end'] = '2115-04-04T13:00:00+02:00'
    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 400
    assert_translated_response_contains(response, 'cooldown', 'Cannot be reserved during cooldown')

@pytest.mark.django_db
@freeze_time('2115-04-04')
def test_reservation_cooldown_before_first_reservation(
        resource_with_cooldown, reservation_data,
        api_client, user, list_url):
    reservation_data['resource'] = resource_with_cooldown.pk
    api_client.force_authenticate(user=user)
    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201

    reservation_data['begin'] = '2115-04-04T10:00:00+02:00'
    reservation_data['end'] = '2115-04-04T11:00:00+02:00'
    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 400
    assert_translated_response_contains(response, 'cooldown', 'Cannot be reserved during cooldown')

@pytest.mark.django_db
def test_overnight_reservation(
    resource_with_overnight_reservations,
    reservation_data, api_client, user,
    list_url):
    reservation_data['begin'] = '2115-04-04T08:00:00+02:00'
    reservation_data['end'] = '2115-04-05T09:00:00+02:00'
    reservation_data['resource'] = resource_with_overnight_reservations.pk
    api_client.force_authenticate(user=user)
    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 201

@pytest.mark.django_db
def test_overnight_reservation_disabled(
    resource_with_overnight_reservations,
    reservation_data, api_client, user,
    list_url):
    resource_with_overnight_reservations.overnight_reservations = False
    resource_with_overnight_reservations.save()
    reservation_data['begin'] = '2115-04-04T08:00:00+02:00'
    reservation_data['end'] = '2115-04-05T09:00:00+02:00'
    reservation_data['resource'] = resource_with_overnight_reservations.pk
    api_client.force_authenticate(user=user)
    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 400

@pytest.mark.django_db
def test_too_long_overnight_reservation_disallowed(
    resource_with_overnight_reservations,
    reservation_data, api_client, user,
    list_url):
    reservation_data['begin'] = '2115-04-04T08:00:00+02:00'
    reservation_data['end'] = '2115-04-06T09:00:00+02:00'
    reservation_data['resource'] = resource_with_overnight_reservations.pk
    api_client.force_authenticate(user=user)
    response = api_client.post(list_url, data=reservation_data)
    assert response.status_code == 400
