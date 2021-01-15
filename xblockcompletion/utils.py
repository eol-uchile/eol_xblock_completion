#!/usr/bin/env python
# -- coding: utf-8 --

from django.conf import settings

from opaque_keys.edx.keys import CourseKey, UsageKey, LearningContextKey

from collections import OrderedDict, defaultdict
from xmodule.modulestore.django import modulestore

from django.contrib.auth.models import User
from django.utils.translation import gettext as _
import logging

from six import binary_type, text_type
from opaque_keys.edx.locator import LibraryUsageLocator
from xblock.core import XBlock
from openedx.core.lib.cache_utils import request_cached
from openedx.core.lib.dynamic_partitions_generators import DynamicPartitionGeneratorsPluginManager

logger = logging.getLogger(__name__)
NEVER = lambda x: False

def get_data_course(course_id):
    course_key = CourseKey.from_string(course_id)
    with modulestore().bulk_operations(course_key):
        course_module = modulestore().get_course(course_key, depth=0)
        include_children_predicate = lambda xblock: xblock.has_children
        return _course_outline_json(course_module)

def _course_outline_json(course_module):
    is_concise = True
    include_children_predicate = lambda xblock: not xblock.category == 'vertical'
    if is_concise:
        include_children_predicate = lambda xblock: xblock.has_children
    return create_xblock_info(
        course_module,
        include_child_info=True,
        course_outline=False if is_concise else True,
        include_children_predicate=include_children_predicate,
        is_concise=is_concise
    )

def create_xblock_info(xblock, data=None, metadata=None, include_ancestor_info=False, include_child_info=False,
                    course_outline=False, include_children_predicate=NEVER, parent_xblock=None, graders=None,
                    course=None, is_concise=False):
    """
        Creates the information needed for client-side XBlockInfo.
        If data or metadata are not specified, their information will not be added
        (regardless of whether or not the xblock actually has data or metadata).
        There are three optional boolean parameters:
        include_ancestor_info - if true, ancestor info is added to the response
        include_child_info - if true, direct child info is included in the response
        is_concise - if true, returns the concise version of xblock info, default is false.
        course_outline - if true, the xblock is being rendered on behalf of the course outline.
            There are certain expensive computations that do not need to be included in this case.
        In addition, an optional include_children_predicate argument can be provided to define whether or
        not a particular xblock should have its children included.
    """
    is_library_block = isinstance(xblock.location, LibraryUsageLocator)
    is_xblock_unit = is_unit(xblock, parent_xblock)
    # this should not be calculated for Sections and Subsections on Unit page or for library blocks
    has_changes = None
    if (is_xblock_unit or course_outline) and not is_library_block:
        has_changes = modulestore().has_changes(xblock)

    if graders is None:
        graders = []

    # We need to load the course in order to retrieve user partition information.
    # For this reason, we load the course once and re-use it when recursively loading children.
    if course is None:
        course = modulestore().get_course(xblock.location.course_key)

    # Compute the child info first so it can be included in aggregate information for the parent
    should_visit_children = include_child_info and (course_outline and not is_xblock_unit or not course_outline)
    if should_visit_children and xblock.has_children:
        child_info = _create_xblock_child_info(
            xblock,
            course_outline,
            graders,
            include_children_predicate=include_children_predicate,
            course=course,
            is_concise=is_concise
        )
    else:
        child_info = None

    xblock_info = {
        'id': text_type(xblock.location),
        'display_name': xblock.display_name_with_default,
        'category': xblock.category,
        'has_children': xblock.has_children
    }
    if is_concise:
        if child_info and child_info.get('children', []):
            xblock_info['child_info'] = child_info
        # Groups are labelled with their internal ids, rather than with the group name. Replace id with display name.
        group_display_name = get_split_group_display_name(xblock, course)
        xblock_info['display_name'] = group_display_name if group_display_name else xblock_info['display_name']
    else:
        logger.error('Error, this code has been removed for this xblock if you want to know the code visit https://github.com/edx/edx-platform/blob/master/cms/djangoapps/contentstore/views/item.py#L1226')
    return xblock_info        

def get_split_group_display_name(xblock, course):
    """
    Returns group name if an xblock is found in user partition groups that are suitable for the split_test module.
    Arguments:
        xblock (XBlock): The courseware component.
        course (XBlock): The course descriptor.
    Returns:
        group name (String): Group name of the matching group xblock.
    """
    for user_partition in get_user_partition_info(xblock, schemes=['random'], course=course):
        for group in user_partition['groups']:
            if u'Group ID {group_id}'.format(group_id=group['id']) == xblock.display_name_with_default:
                return group['name']

def get_user_partition_info(xblock, schemes=None, course=None):
    """
        Retrieve user partition information for an XBlock for display in editors.
        * If a partition has been disabled, it will be excluded from the results.
        * If a group within a partition is referenced by the XBlock, but the group has been deleted,
        the group will be marked as deleted in the results.
        Arguments:
            xblock (XBlock): The courseware component being edited.
        Keyword Arguments:
            schemes (iterable of str): If provided, filter partitions to include only
                schemes with the provided names.
            course (XBlock): The course descriptor.  If provided, uses this to look up the user partitions
                instead of loading the course.  This is useful if we're calling this function multiple
                times for the same course want to minimize queries to the modulestore.
        Returns: list
        Example Usage:
        get_user_partition_info(block, schemes=["cohort", "verification"])
        [
            {
                "id": 12345,
                "name": "Cohorts"
                "scheme": "cohort",
                "groups": [
                    {
                        "id": 7890,
                        "name": "Foo",
                        "selected": True,
                        "deleted": False,
                    }
                ]
            },
            {
                "id": 7292,
                "name": "Midterm A",
                "scheme": "verification",
                "groups": [
                    {
                        "id": 1,
                        "name": "Completed verification at Midterm A",
                        "selected": False,
                        "deleted": False
                    },
                    {
                        "id": 0,
                        "name": "Did not complete verification at Midterm A",
                        "selected": False,
                        "deleted": False,
                    }
                ]
            }
        ]
    """
    course = course or modulestore().get_course(xblock.location.course_key)

    if course is None:
        log.warning(
            u"Could not find course %s to retrieve user partition information",
            xblock.location.course_key
        )
        return []

    if schemes is not None:
        schemes = set(schemes)

    partitions = []
    for p in sorted(get_all_partitions_for_course(course, active_only=True), key=lambda p: p.name):

        # Exclude disabled partitions, partitions with no groups defined
        # The exception to this case is when there is a selected group within that partition, which means there is
        # a deleted group
        # Also filter by scheme name if there's a filter defined.
        selected_groups = set(xblock.group_access.get(p.id, []) or [])
        if (p.groups or selected_groups) and (schemes is None or p.scheme.name in schemes):

            # First, add groups defined by the partition
            groups = []
            for g in p.groups:
                # Falsey group access for a partition mean that all groups
                # are selected.  In the UI, though, we don't show the particular
                # groups selected, since there's a separate option for "all users".
                groups.append({
                    "id": g.id,
                    "name": g.name,
                    "selected": g.id in selected_groups,
                    "deleted": False,
                })

            # Next, add any groups set on the XBlock that have been deleted
            all_groups = set(g.id for g in p.groups)
            missing_group_ids = selected_groups - all_groups
            for gid in missing_group_ids:
                groups.append({
                    "id": gid,
                    "name": _("Deleted Group"),
                    "selected": True,
                    "deleted": True,
                })

            # Put together the entire partition dictionary
            partitions.append({
                "id": p.id,
                "name": six.text_type(p.name),  # Convert into a string in case ugettext_lazy was used
                "scheme": p.scheme.name,
                "groups": groups,
            })

    return partitions

@request_cached()
def get_all_partitions_for_course(course, active_only=False):
    """
    A method that returns all `UserPartitions` associated with a course, as a List.
    This will include the ones defined in course.user_partitions, but it may also
    include dynamically included partitions (such as the `EnrollmentTrackUserPartition`).
    Args:
        course: the course for which user partitions should be returned.
        active_only: if `True`, only partitions with `active` set to True will be returned.
        Returns:
            A List of UserPartitions associated with the course.
    """
    all_partitions = course.user_partitions + _get_dynamic_partitions(course)
    if active_only:
        all_partitions = [partition for partition in all_partitions if partition.active]
    return all_partitions

def _get_dynamic_partitions(course):
    """
    Return the dynamic user partitions for this course.
    If none exists, returns an empty array.
    """
    dynamic_partition_generators = DynamicPartitionGeneratorsPluginManager.get_available_plugins().values()
    generated_partitions = []
    for generator in dynamic_partition_generators:
        generated_partition = generator(course)
        if generated_partition:
            generated_partitions.append(generated_partition)

    return generated_partitions

def _create_xblock_child_info(xblock, course_outline, graders, include_children_predicate=NEVER,
                            course=None, is_concise=False):
    """
    Returns information about the children of an xblock, as well as about the primary category
    of xblock expected as children.
    """
    child_info = {}
    child_category = xblock_primary_child_category(xblock)
    if child_category:
        child_info = {
            'category': child_category,
            'display_name': xblock_type_display_name(child_category, default_display_name=child_category),
        }
    if xblock.has_children and include_children_predicate(xblock):
        child_info['children'] = [
            create_xblock_info(
                child, include_child_info=True, course_outline=course_outline,
                include_children_predicate=include_children_predicate,
                parent_xblock=xblock,
                graders=graders,
                course=course,
                is_concise=is_concise
            ) for child in xblock.get_children()
        ]
    return child_info

def xblock_primary_child_category(xblock):
    """
    Returns the primary child category for the specified xblock, or None if there is not a primary category.
    """
    category = xblock.category
    if category == 'course':
        return 'chapter'
    elif category == 'chapter':
        return 'sequential'
    elif category == 'sequential':
        return 'vertical'
    return None

def xblock_type_display_name(xblock, default_display_name=None):
    """
    Returns the display name for the specified type of xblock. Note that an instance can be passed in
    for context dependent names, e.g. a vertical beneath a sequential is a Unit.
    :param xblock: An xblock instance or the type of xblock.
    :param default_display_name: The default value to return if no display name can be found.
    :return:
    """

    if hasattr(xblock, 'category'):
        category = xblock.category
        if category == 'vertical' and not is_unit(xblock):
            return _('Vertical')
    else:
        category = xblock
    if category == 'chapter':
        return _('Section')
    elif category == 'sequential':
        return _('Subsection')
    elif category == 'vertical':
        return _('Unit')
    component_class = XBlock.load_class(category, select=settings.XBLOCK_SELECT_FUNCTION)
    if hasattr(component_class, 'display_name') and component_class.display_name.default:
        return _(component_class.display_name.default)
    else:
        return default_display_name

def is_unit(xblock, parent_xblock=None):
    """
    Returns true if the specified xblock is a vertical that is treated as a unit.
    A unit is a vertical that is a direct child of a sequential (aka a subsection).
    """
    if xblock.category == 'vertical':
        if parent_xblock is None:
            parent_xblock = get_parent_xblock(xblock)
        parent_category = parent_xblock.category if parent_xblock else None
        return parent_category == 'sequential'
    return False

def get_parent_xblock(xblock):
    """
    Returns the xblock that is the parent of the specified xblock, or None if it has no parent.
    """
    locator = xblock.location
    parent_location = modulestore().get_parent_location(locator)

    if parent_location is None:
        return None
    return modulestore().get_item(parent_location)