from django import template
from django.db.models import Q


register = template.Library()


@register.filter
def instances_and_widgets(bound_field):
    """
    Returns a list of two-tuples of instances and widgets, designed to
    be used with ModelMultipleChoiceField and CheckboxSelectMultiple widgets.

    Allows templates to loop over a multiple checkbox field and display the
    related model instance, such as for a table with checkboxes.

    Usage:
       {% for instance, widget in form.my_field_name|instances_and_widgets %}
           <p>{{ instance }}: {{ widget }}</p>
       {% endfor %}

    Source: https://stackoverflow.com/a/27545910
    """
    instance_widgets = []
    for index, instance in enumerate(bound_field.field.queryset.all()):
        widget = copy(bound_field[index])
        # Hide the choice label so it just renders as a checkbox
        widget.choice_label = ''
        instance_widgets.append((instance, widget))
    return instance_widgets


@register.filter
def get_value_from_dict(dict_data, key):
    """
    Usage example {{ your_dict|get_value_from_dict:your_key }}.
    """
    if not isinstance(dict_data, dict):
        return dict_data
    return dict_data.get(key, None)


@register.simple_tag
def user_has_permission(user, permission, obj):
    return user.has_perm(permission, obj)


@register.filter
def is_truthy(collection):
    return any([bool(value) for value in collection or []])


@register.filter
def remove_empty(collection):
    return [value for value in collection if bool(value)]

@register.simple_tag
def unit_authorization_highest_per_user(unit, permissions = []):
    if permissions:
        qs = unit.authorizations.none()
        if 'unit:can_approve_reservations' in permissions:
            permissions.remove('unit:can_approve_reservations')
            qs = unit.authorizations.can_approve_reservations(unit)
        qs |= unit.authorizations.highest_per_user().filter(level__in=permissions)
        return qs.order_by('authorized__first_name')
    return unit.authorizations.highest_per_user().order_by('authorized__first_name')


@register.simple_tag
def get_query_params(request, key):
    return request.GET.getlist(key)

@register.filter
def replace(string, value):
    return string.replace(*value.split('|'))

@register.filter
def disabled(form):
    form.field.widget.attrs.update({'disabled': True})
    return form
